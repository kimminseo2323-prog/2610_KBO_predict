"""일일 파이프라인: 수집 -> 정산 -> 예측 -> 발행."""
import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from kbo_predict import KST, raw_store, seasons
from kbo_predict.collect import collect_range, fetch_starters
from kbo_predict.features import LeagueState, regular_finals
from kbo_predict.predict import predict_game
from kbo_predict.publish import settle_history, upsert_history, write_latest, write_status
from kbo_predict.train_win import load_bundle


def _regular_finals(games: list[dict], season: int, before: str | None = None) -> list[dict]:
    """상태에 넣을 경기: features.regular_finals(학습과 같은 필터·순서 — 정규시즌 FINAL, (date, game_id) 순)에
    before 컷만 더한다. before가 있으면 그 날짜 전 경기만 (당일 경기 결과가 당일 예측에 새지 않게).
    점수가 없거나 무승부인 경기는 LeagueState.update가 알아서 처리한다 (학습 때와 동일)."""
    return [g for g in regular_finals(games, season) if before is None or g["date"] < before]


def build_state(season: int, upto: str) -> LeagueState:
    """upto('YYYY-MM-DD') 경기 직전 시점의 리그 상태.
    직전 시즌 정규 FINAL 전체(박스스코어 포함) → start_season(season) → 당해 시즌 upto 전날까지의 정규 FINAL.
    학습(features.build_dataset)이 시즌을 이어 붙이는 방식과 같다. 직전 시즌 데이터가 없으면(2015 등) 건너뛴다."""
    state = LeagueState()
    prev_games = raw_store.load_games(season - 1)
    if prev_games:
        state.start_season(season - 1)
        prev_boxes = raw_store.load_boxscores(season - 1)
        for g in _regular_finals(prev_games, season - 1):
            state.update(g, prev_boxes.get(g["game_id"]))
    state.start_season(season)
    boxes = raw_store.load_boxscores(season)
    for g in _regular_finals(raw_store.load_games(season), season, before=upto):
        state.update(g, boxes.get(g["game_id"]))
    return state


def run(target: date, *, data_dir: Path, model_path: Path, meta: dict, fetch: bool = True) -> dict:
    data_dir = Path(data_dir)
    season = target.year
    iso = target.isoformat()
    pub = data_dir / "public"

    # ① 수집 (경기·박스스코어 → 오늘 예정 경기의 예고 선발)
    collect_errors: list[str] = []
    if fetch:
        try:
            out = collect_range(target - timedelta(days=7), target + timedelta(days=14))
            collect_errors += [f"{e['path']}: {e['error']}" for e in out["errors"]]
            today = [g for g in raw_store.load_games(season) if g["date"] == iso and g["status"] == "SCHEDULED"]
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

    # ④ 예측 (취소 경기는 예측 없이 표시만)
    day = [g for g in games if g["date"] == iso]
    entries = []
    for g in day:
        if g["status"] == "CANCELED":
            entries.append({
                "game_id": g["game_id"], "date": g["date"], "time": g.get("time_kst"),
                "stadium": g.get("stadium"), "status": "CANCELED", "status_note": g.get("status_note"),
                "home_win_prob": None, "factors": [],
                "home": {"code": g["home_code"]}, "away": {"code": g["away_code"]},
            })
        else:
            e = predict_game(bundle, g, state, starters.get(g["game_id"]))
            e["status_note"] = g.get("status_note")
            entries.append(e)
    preds = [e for e in entries if e["status"] != "CANCELED"]

    # ⑤ 발행 (경기 행이 아예 없으면 latest 유지)
    if entries:
        write_latest(pub / "latest.json", date=iso, games=entries, meta=meta)
        upsert_history(pub / "history.csv", preds, predicted_at=meta["generated_at"])

    # ⑥ status
    upcoming = [g["date"] for g in games if g["date"] > iso and g["status"] != "CANCELED"]
    write_status(pub / "status.json", mode="live", next_game_date=min(upcoming) if upcoming else None,
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
