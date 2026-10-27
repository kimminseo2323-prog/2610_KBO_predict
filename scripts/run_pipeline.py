"""일일 파이프라인: 수집 -> 정산 -> 예측 -> 발행."""
import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from kbo_predict import KST, raw_store
from kbo_predict.collect import collect_range
from kbo_predict.features import LeagueState
from kbo_predict.predict import predict_game
from kbo_predict.publish import settle_history, upsert_history, write_latest, write_status
from kbo_predict.train_win import load_bundle


def run(target: date, *, data_dir: Path, model_path: Path, meta: dict, fetch: bool = True) -> dict:
    data_dir = Path(data_dir)
    season = target.year
    iso = target.isoformat()
    pub = data_dir / "public"

    # ① 수집
    if fetch:
        try:
            collect_range(target - timedelta(days=7), target + timedelta(days=14))
        except requests.RequestException as e:
            print(f"[pipeline] collect failed, continuing with existing data: {e!r}", file=sys.stderr)
            if not raw_store.load_games(season):
                raise
    games = raw_store.load_games(season)

    bundle = load_bundle(model_path)
    meta = {**meta, "model_version": bundle["version"]}

    # ② 정산
    settled = settle_history(pub / "history.csv", games)

    # ③ 상태 누적 (target 이전 FINAL 경기만)
    state = LeagueState()
    for g in sorted((g for g in games if g["status"] == "FINAL" and g["date"] < iso),
                    key=lambda g: (g["date"], g["game_id"])):
        state.update(g)

    # ④ 예측
    today = [g for g in games if g["date"] == iso and g["status"] != "CANCELED"]
    preds = [predict_game(bundle, g, state) for g in today]

    # ⑤ 발행 (경기 없으면 latest 유지)
    if preds:
        write_latest(pub / "latest.json", date=iso, games=preds, meta=meta)
        upsert_history(pub / "history.csv", preds, predicted_at=meta["generated_at"])

    # ⑥ status
    upcoming = [g["date"] for g in games if g["date"] > iso and g["status"] != "CANCELED"]
    write_status(pub / "status.json", mode="live", next_game_date=min(upcoming) if upcoming else None,
                 games_today=len(preds), meta=meta)
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
