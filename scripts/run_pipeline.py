"""일일 파이프라인: 수집 -> 정산 -> 예측 -> 전망 -> 발행.

발행 파일 (data/public):
- latest.json: 오늘 경기 예측 + outlook(전망 카드: 진행 중 시리즈 / 가을야구 확률 / 다음 경기 날짜).
  오늘 경기 행이 하나도 없으면 손대지 않는다 (전날 내용 유지).
- history.csv: 경기 전 예측 기록과 정산 결과.
- status.json: 실행 결과. mode = "live"(오늘~14일 안에 취소 아닌 경기가 있음) 또는 "rewind"(비시즌 —
  사이트가 되감기 모드로 연다).
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from kbo_predict import KST, raw_store, seasons
from kbo_predict.cluster import load_bundle as load_clusters
from kbo_predict.cluster import load_labels, require_names, types_map
from kbo_predict.collect import collect_missing_boxscores, collect_range, fetch_starters
from kbo_predict.predict import canceled_entry, predict_game
from kbo_predict.publish import settle_history, upsert_history, write_latest, write_status
from kbo_predict.rewind import state_before
from kbo_predict.simulate import load_postseason, outlook_for
from kbo_predict.train_win import load_bundle


# upto('YYYY-MM-DD') 경기 직전 시점의 리그 상태. 되감기(rewind)와 같은 함수를 쓰도록 kbo_predict.rewind로 옮겼다.
# 이름(build_state)은 기존 테스트·노트북이 그대로 쓰도록 별칭으로 남긴다.
build_state = state_before


CLUSTERS_PKL = Path("models/clusters.pkl")
TEAM_PKL = Path("models/team-2026.pkl")  # 선발 없는 팀 모델 — 전망(outlook) 시뮬레이션용 (예측 확률에는 안 쓴다)
LIVE_WINDOW_DAYS = 14  # status.json mode: 오늘부터 이 일수 안에 경기가 있으면 "live", 없으면 "rewind"


def starter_types(clusters_path: Path, season: int) -> dict[int, dict] | None:
    """투수 player_id -> {"id", "name"}: 직전 시즌(season-1) 투수 유형. latest.json 선발 블록의 type 칸에 쓴다.
    직전 시즌을 쓰는 이유: 시즌 중 유형은 표본이 작아 흔들리고, 상성 피처(features)도 직전 시즌 유형을 쓴다.
    clusters.pkl이 없으면 None (유형 없이 예전처럼 돈다 — 선발 블록의 type은 모두 null).
    이름표(config/cluster_labels.yaml)가 없으면 FileNotFoundError, 유형 번호에 이름이 빠져 있으면 ValueError —
    run()이 잡아서 status.json의 collect_errors에 경고로 남기고 유형 없이 계속한다."""
    clusters_path = Path(clusters_path)
    if not clusters_path.exists():
        return None
    obj = load_clusters(clusters_path)
    labels = load_labels()
    pit = obj["pitcher"]
    # 유형 수 k: 번들이 있으면 그 k, (테스트용 최소 묶음처럼) 없으면 배정된 유형 번호의 최댓값 + 1
    k = pit["bundle"]["k"] if "bundle" in pit else int(pit["assigned"]["type"].max()) + 1
    require_names(labels, "pitcher", k)
    names = labels["pitcher"]
    return {pid: {"id": t["pitcher"], "name": names[t["pitcher"]]["name"]}
            for (s, pid), t in types_map(obj).items() if s == season - 1 and "pitcher" in t}


def status_mode(games: list[dict], on: date) -> str:
    """status.json의 mode. on ~ on+14일 안에 취소 아닌 경기(시범·정규·포스트시즌 무엇이든)가 있으면 "live",
    없으면 "rewind" (비시즌 — 사이트가 지난 시즌 되감기를 연다)."""
    lo, hi = on.isoformat(), (on + timedelta(days=LIVE_WINDOW_DAYS)).isoformat()
    return "live" if any(lo <= g["date"] <= hi and g["status"] != "CANCELED" for g in games) else "rewind"


def latest_outlook(team_path: Path, season: int, on: str, games: list[dict], state, collect_errors: list[str]) -> dict:
    """latest.json의 outlook 카드 (simulate.outlook_for: series / playoff_race / next_game — 모두 그날 경기 전 기준).
    팀 모델(team_path)이 없거나, 불러오기·시뮬레이션이 실패하면 {"type": "next_game", ...}로 대신하고
    collect_errors와 stderr에 경고를 남긴다 (starter_types와 같은 방식 — 전망 때문에 예측 발행이 멈추지 않게)."""
    team_path = Path(team_path)
    try:
        if not team_path.exists():
            raise FileNotFoundError(f"{team_path} not found")
        return outlook_for(season, on, games, state=state, team_bundle=load_bundle(team_path),
                           ps_config=load_postseason(season))
    except Exception as e:  # 깨진 pkl, 대진표 오류 등
        collect_errors.append(f"outlook unavailable ({team_path}): {e!r}")
        print(f"[pipeline] outlook unavailable, using next_game: {e!r}", file=sys.stderr)
        later = sorted(g["date"] for g in games if g["date"] > on and g["status"] != "CANCELED")
        return {"type": "next_game", "next_game_date": later[0] if later else None, "as_of": on}


def run(target: date, *, data_dir: Path, model_path: Path, meta: dict, fetch: bool = True,
        clusters_path: Path = CLUSTERS_PKL, team_path: Path = TEAM_PKL) -> dict:
    data_dir = Path(data_dir)
    season = target.year
    iso = target.isoformat()
    pub = data_dir / "public"

    # ① 수집 (경기·박스스코어 → 빠진 박스스코어 다시 받기 → 오늘 예정 경기의 예고 선발)
    collect_errors: list[str] = []
    if fetch:
        try:
            out = collect_range(target - timedelta(days=7), target + timedelta(days=14))
            collect_errors += [f"{e['path']}: {e['error']}" for e in out["errors"]]
            # 수집 창(−7일)을 벗어난 FINAL인데 박스스코어가 없는 경기 (최대 20경기, 5초 간격)
            miss = collect_missing_boxscores(season)
            collect_errors += [f"{e['path']}: {e['error']}" for e in miss["errors"]]
            today = [g for g in raw_store.load_games(season) if g["date"] == iso and g["status"] == "SCHEDULED"]
            if today:  # 오늘 예정 경기가 없으면(비시즌·휴식일) 경기 페이지를 요청하지 않는다
                st = fetch_starters(today, fetched_at=meta["generated_at"])
                raw_store.upsert_starters(season, list(st["starters"].values()))
                collect_errors += [f"{e['path']}: {e['error']}" for e in st["errors"]]
        except Exception as e:  # 네트워크 오류뿐 아니라 파서/예기치 않은 예외도 status.json은 남긴다
            collect_errors.append(repr(e))
            print(f"[pipeline] collect failed, continuing with existing data: {e!r}", file=sys.stderr)
            if not raw_store.load_games(season):
                raise
    if season not in seasons.REGULAR_SEASON:
        collect_errors.append(f"season {season} not registered in REGULAR_SEASON; using 03-01..10-31 fallback")
    games = raw_store.load_games(season)

    bundle = load_bundle(model_path)
    meta = {**meta, "model_version": bundle["version"]}

    # ② 정산
    settled = settle_history(pub / "history.csv", games)

    # ③ 상태 누적 (직전 시즌 + target 이전 당해 정규시즌 FINAL — 학습 시 build_dataset과 동일)
    state = build_state(season, iso)
    starters = raw_store.load_starters(season)  # 저장된 예고 선발 (--no-fetch여도 이전에 받은 값을 쓴다)
    try:  # 선발 유형 표시용 (예측 확률에는 쓰지 않는다) — 실패해도 예측·발행은 유형 없이 계속한다
        sp_types = starter_types(clusters_path, season)
    except Exception as e:  # 깨진 clusters.pkl, 이름표 없음·빠짐 등
        sp_types = None
        collect_errors.append(f"starter types unavailable ({clusters_path}): {e!r}")
        print(f"[pipeline] starter types unavailable, continuing without them: {e!r}", file=sys.stderr)

    # ④ 예측 (취소 경기는 예측 없이 표시만)
    day = [g for g in games if g["date"] == iso]
    entries = []
    for g in day:
        if g["status"] == "CANCELED":
            entries.append(canceled_entry(g))
        else:
            e = predict_game(bundle, g, state, starters.get(g["game_id"]), starter_types=sp_types)
            e["status_note"] = g.get("status_note")
            entries.append(e)
    preds = [e for e in entries if e["status"] != "CANCELED"]

    # ⑤ 전망 + 발행 (경기 행이 아예 없으면 latest 유지 — 전망 시뮬레이션도 돌리지 않는다)
    if entries:
        outlook = latest_outlook(team_path, season, iso, games, state, collect_errors)
        write_latest(pub / "latest.json", date=iso, games=entries, meta=meta, outlook=outlook)
        # history의 model_version = 실제로 예측한 번들의 버전 (패키지 상수가 아니라)
        upsert_history(pub / "history.csv", preds, predicted_at=meta["generated_at"],
                       model_version=meta["model_version"])

    # ⑥ status
    upcoming = [g["date"] for g in games if g["date"] > iso and g["status"] != "CANCELED"]
    write_status(pub / "status.json", mode=status_mode(games, target),
                 next_game_date=min(upcoming) if upcoming else None,
                 games_today=len(preds), meta=meta, collect_errors=collect_errors)
    return {"games_today": len(preds), "settled": settled}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (기본: KST 오늘)")
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args(argv)
    now = datetime.now(KST)
    target = date.fromisoformat(args.date) if args.date else now.date()
    meta = {
        "generated_at": now.isoformat(timespec="seconds"),
        "commit_sha": os.environ.get("GITHUB_SHA"),
        "run_url": os.environ.get("RUN_URL"),
    }
    out = run(target, data_dir=Path("data"), model_path=Path("models/win_model.pkl"), meta=meta,
              fetch=not args.no_fetch)
    print(out)


if __name__ == "__main__":
    main()
