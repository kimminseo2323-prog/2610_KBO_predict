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

from kbo_predict import FROZEN_SEASONS, KST, raw_store, seasons
from kbo_predict.cluster import load_bundle as load_clusters
from kbo_predict.cluster import load_labels, require_names, types_map
from kbo_predict.collect import collect_missing_boxscores, collect_range, fetch_starters
from kbo_predict.predict import canceled_entry, predict_game, raw_prob
from kbo_predict.publish import drop_history, settle_history, upsert_history, write_latest, write_status
from kbo_predict.rewind import state_before
from kbo_predict.simulate import load_postseason, next_game_card, outlook_for, season_result, unneeded_games
from kbo_predict.train_win import load_bundle
from kbo_predict import whatif


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


def latest_outlook(team_path: Path, season: int, on: str, games: list[dict], state, collect_errors: list[str],
                   today_probs: dict[int, float] | None = None) -> dict:
    """latest.json의 outlook 카드 (simulate.outlook_for: series / playoff_race / next_game — 모두 그날 경기 전 기준).
    today_probs = {game_id: 반올림 전 P(홈 승)} — 오늘 경기의 승패 모델(예고 선발 포함) 확률. 시리즈 카드는 오늘 경기에
    이 확률을 쓴다 (스펙 §8 — latest.json 경기 항목의 home_win_prob와 같은 예측).
    팀 모델(team_path)이 없거나, 불러오기·시뮬레이션이 실패하면 {"type": "next_game", ...}로 대신하고
    collect_errors와 stderr에 경고를 남긴다 (starter_types와 같은 방식 — 전망 때문에 예측 발행이 멈추지 않게)."""
    team_path = Path(team_path)
    try:
        if not team_path.exists():
            raise FileNotFoundError(f"{team_path} not found")
        return outlook_for(season, on, games, state=state, team_bundle=load_bundle(team_path),
                           ps_config=load_postseason(season), today_probs=today_probs)
    except Exception as e:  # 깨진 pkl, 대진표 오류 등
        collect_errors.append(f"outlook unavailable ({team_path}): {e!r}")
        print(f"[pipeline] outlook unavailable, using next_game: {e!r}", file=sys.stderr)
        return next_game_card(on, games)


def season_games(season: int, collect_errors: list[str] | None = None) -> tuple[list[dict], set[int]]:
    """그 시즌 경기 목록에서 '승부가 난 시리즈의 남은 예정 경기'(simulate.unneeded_games)를 뺀 것과 뺀 game_id.
    대진표를 읽지 못해도 예측은 계속한다 (뺄 경기 없음 + 경고)."""
    games = raw_store.load_games(season)
    try:
        skip = unneeded_games(season, games, load_postseason(season))
    except Exception as e:
        skip = set()
        if collect_errors is not None:
            collect_errors.append(f"postseason config unavailable: {e!r}")
    return [g for g in games if g["game_id"] not in skip], skip


def started(g: dict, now: datetime) -> bool:
    """경기 시작 시각(datetime_utc)이 지났는가. 시각이 없으면 False (날짜만으로는 판단하지 않는다)."""
    t = g.get("datetime_utc")
    if not t:
        return False
    return datetime.fromisoformat(t.replace("Z", "+00:00")) <= now


LOOKAHEAD_DAYS = 3   # 경기가 없는 날(휴식일·이동일)에는 이 날수 안의 다음 경기일을 미리 예측해 발행한다


def lookahead_target(games: list[dict], target: date) -> tuple[date, str]:
    """target에 경기 행이 하나도 없으면(취소 경기도 없음) LOOKAHEAD_DAYS 안에서 예정(SCHEDULED) 경기가 있는 가장 가까운
    날짜로 바꾼다 — 포스트시즌 휴식일에 "다음 경기까지" 대신 다음 경기 예측을 보여 주기 위해. 그 날짜의 예고 선발은
    아직 없을 수 있다(그러면 선발 없이 예측하고 경기 당일 실행이 다시 예측한다 — history는 경기당 마지막 예측만 남긴다).
    정산·상태 누적은 바뀐 날짜 기준이지만 정규시즌 FINAL만 세므로 결과가 새지 않는다. 바꿀 날이 없으면 그대로."""
    iso = target.isoformat()
    if any(g["date"] == iso for g in games):
        return target, iso
    limit = (target + timedelta(days=LOOKAHEAD_DAYS)).isoformat()
    nxt = sorted(g["date"] for g in games if iso < g["date"] <= limit and g["status"] == "SCHEDULED")
    if not nxt:
        return target, iso
    print(f"[pipeline] no games on {iso}; previewing next game day {nxt[0]}", file=sys.stderr)
    return date.fromisoformat(nxt[0]), nxt[0]


def run(target: date, *, data_dir: Path, model_path: Path, meta: dict, fetch: bool = True,
        clusters_path: Path = CLUSTERS_PKL, team_path: Path = TEAM_PKL) -> dict:
    data_dir = Path(data_dir)
    season = target.year
    iso = target.isoformat()
    pub = data_dir / "public"

    # ① 수집 (경기·박스스코어 → 오늘 예정 경기의 예고 선발 → 빠진 박스스코어 다시 받기)
    collect_errors: list[str] = []
    if fetch:
        window_start = target - timedelta(days=7)
        collect_ok = False
        try:
            out = collect_range(window_start, target + timedelta(days=14))
            collect_errors += [f"{e['path']}: {e['error']}" for e in out["errors"]]
            target, iso = lookahead_target(season_games(season)[0], target)
            today = [g for g in season_games(season)[0] if g["date"] == iso and g["status"] == "SCHEDULED"]
            if today:  # 오늘 예정 경기가 없으면(비시즌·휴식일) 경기 페이지를 요청하지 않는다
                st = fetch_starters(today, fetched_at=meta["generated_at"])
                raw_store.upsert_starters(season, list(st["starters"].values()))
                collect_errors += [f"{e['path']}: {e['error']}" for e in st["errors"]]
            collect_ok = True
        except Exception as e:  # 네트워크 오류뿐 아니라 파서/예기치 않은 예외도 status.json은 남긴다
            collect_errors.append(repr(e))
            print(f"[pipeline] collect failed, continuing with existing data: {e!r}", file=sys.stderr)
            if not raw_store.load_games(season):
                raise
        # 수집 창(−7일) 밖의 FINAL인데 박스스코어가 없는 경기 (최근 순 최대 20경기, 5초 간격).
        # 예고 선발 뒤에 따로 돌린다 — 여기서 실패해도 오늘 예측에 필요한 수집은 이미 끝났다.
        # 건너뛰는 경우 둘: (1) 위 수집이 예외로 멈췄으면 (사이트가 내려가 있을 때 20경기 × 5초를 더 기다리지 않게),
        # (2) 얼린 시즌(FROZEN_SEASONS, 2015~2026)이면 — 얼린 산출물(report-2026 · team-2026 · clusters-2026 · 되감기)은
        # 지금 있는 박스스코어로 만들어졌고 check_parity가 그대로 다시 만드는지 본다. 매일 작업이 그 시즌의 옛 박스스코어를
        # 새로 받으면 parity가 깨지므로, 얼린 시즌은 매일 작업이 다시 받지 않는다 (필요하면 사람이 받고 다시 얼린다).
        if collect_ok and season not in FROZEN_SEASONS:
            try:
                miss = collect_missing_boxscores(season, before=window_start.isoformat())
                collect_errors += [f"{e['path']}: {e['error']}" for e in miss["errors"]]
            except Exception as e:
                collect_errors.append(f"missing boxscores: {e!r}")
                print(f"[pipeline] missing-boxscore refetch failed: {e!r}", file=sys.stderr)
    if season not in seasons.REGULAR_SEASON:
        collect_errors.append(f"season {season} not registered in REGULAR_SEASON; using 03-01..10-31 fallback")
    games, skipped = season_games(season, collect_errors)  # 승부 난 시리즈의 열리지 않을 경기는 없는 것으로 본다
    if not fetch:
        target, iso = lookahead_target(games, target)

    bundle = load_bundle(model_path)
    meta = {**meta, "model_version": bundle["version"]}

    # ② 정산 (+ 열리지 않을 경기의 예측 행 지우기)
    settled = settle_history(pub / "history.csv", games)
    if skipped:
        drop_history(pub / "history.csv", skipped)
        _drop_from_latest(pub / "latest.json", skipped)

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
    # 경기 시작 시각이 지난 경기는 시작 전 마지막 예측을 그대로 둔다: 원천 사이트가 경기 중에도 '예정'으로 두고
    # GitHub 예약 실행이 몇 시간씩 늦어, 시작 뒤에 예측이 다시 기록된 일이 있었다(2026-11-06·07).
    now = datetime.fromisoformat(meta["generated_at"])
    prev_latest = _read_json(pub / "latest.json")
    prev = {e["game_id"]: e for e in (prev_latest or {}).get("games", [])} if (prev_latest or {}).get("date") == iso else {}
    day = [g for g in games if g["date"] == iso]
    entries, locked = [], set()
    for g in day:
        if g["status"] == "CANCELED":
            entries.append(canceled_entry(g))
        elif started(g, now) and g["game_id"] in prev:
            entries.append({**prev[g["game_id"]], "status": g["status"], "status_note": g.get("status_note")})
            locked.add(g["game_id"])
        else:
            e = predict_game(bundle, g, state, starters.get(g["game_id"]), starter_types=sp_types)
            e["status_note"] = g.get("status_note")
            entries.append(e)
    preds = [e for e in entries if e["status"] != "CANCELED"]
    # 시리즈 전망의 오늘 경기 확률: 위 예측과 같은 승패 모델·같은 입력의 반올림 전 값 (스펙 §8)
    today_probs = {g["game_id"]: raw_prob(bundle, g, state, starters.get(g["game_id"]))
                   for g in day if g["status"] != "CANCELED" and g["game_id"] not in locked}

    # ⑤ 전망 + 발행 (경기 행이 아예 없으면 latest 유지 — 전망 시뮬레이션도 돌리지 않는다)
    if entries:
        outlook = latest_outlook(team_path, season, iso, games, state, collect_errors, today_probs)
        write_latest(pub / "latest.json", date=iso, games=entries, meta=meta, outlook=outlook)
        # history의 model_version = 실제로 예측한 번들의 버전 (패키지 상수가 아니라)
        upsert_history(pub / "history.csv", [e for e in preds if e["game_id"] not in locked],
                       predicted_at=meta["generated_at"], model_version=meta["model_version"])
        # 선발 바꿔 보기(사이트): 모델 숫자 + 경기별 후보 선발 기록. 실패해도 예측 발행은 그대로 (표시용 부가 기능)
        try:
            boxes = raw_store.load_boxscores(season)
            blocks = [whatif.game_block(g, state, starters.get(g["game_id"]), games, boxes, regular_only=False)
                      for g in day if g["status"] != "CANCELED"]
            write_whatif(pub / "whatif.json", date=iso, model=whatif.model_params(bundle), games=blocks, meta=meta)
        except Exception as e:
            collect_errors.append(f"whatif unavailable: {e!r}")
            print(f"[pipeline] whatif unavailable, continuing: {e!r}", file=sys.stderr)

    # ⑥ status
    upcoming = [g["date"] for g in games if g["date"] > iso and g["status"] != "CANCELED"]
    write_status(pub / "status.json", mode=status_mode(games, target),
                 next_game_date=min(upcoming) if upcoming else None,
                 games_today=len(preds), meta=meta, collect_errors=collect_errors,
                 season_result=_season_result(season, games, collect_errors))
    return {"games_today": len(preds), "settled": settled}


def _read_json(path: Path) -> dict | None:
    import json
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def _drop_from_latest(path: Path, game_ids: set[int]) -> None:
    """latest.json에 열리지 않을 경기가 남아 있으면 빼고, 그 날짜의 시리즈 전망도 지운다 (승부가 이미 났다).
    빼고 나서 경기가 하나도 안 남으면 파일을 그대로 둔다 — 사이트 계약상 latest.json에는 경기가 있어야 하고,
    status.json이 rewind가 되므로 사이트는 이 파일을 쓰지 않는다. (경기를 빼는 것이 먼저라 이 경우는 생기기 어렵다:
    시리즈가 끝난 뒤의 실행은 열리지 않을 경기를 처음부터 예측하지 않는다.)"""
    import json
    obj = _read_json(path)
    if not obj or not any(g.get("game_id") in game_ids for g in obj.get("games", [])):
        return
    keep = [g for g in obj["games"] if g.get("game_id") not in game_ids]
    if not keep:
        print(f"[pipeline] {path} holds only unneeded games; leaving it (status mode decides what the site shows)", file=sys.stderr)
        return
    obj["games"] = keep
    obj["outlook"] = None
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _season_result(season: int, games: list[dict], collect_errors: list[str]) -> dict | None:
    try:
        return season_result(season, games, load_postseason(season))
    except Exception as e:
        collect_errors.append(f"season result unavailable: {e!r}")
        return None


def write_whatif(path: Path, *, date: str, model: dict | None, games: list[dict], meta: dict) -> None:
    """data/public/whatif.json — 사이트의 "선발 바꿔 보기"가 읽는다 (모델이 로지스틱 회귀가 아니면 model = None)."""
    import json
    obj = {"date": date, "generated_at": meta.get("generated_at"), "model": model, "games": games if model else []}
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


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
