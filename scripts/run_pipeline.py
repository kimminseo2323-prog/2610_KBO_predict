"""일일 파이프라인: 수집 -> 정산 -> 예측 -> 발행."""
import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from kbo_predict import KST, raw_store, seasons
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
    collect_errors: list[str] = []
    if fetch:
        try:
            out = collect_range(target - timedelta(days=7), target + timedelta(days=14))
            collect_errors = [f"{e['path']}: {e['error']}" for e in out["errors"]]
        except requests.RequestException as e:
            collect_errors = [repr(e)]
            print(f"[pipeline] collect failed, continuing with existing data: {e!r}", file=sys.stderr)
            if not raw_store.load_games(season):
                raise
    games = raw_store.load_games(season)

    bundle = load_bundle(model_path)
    meta = {**meta, "model_version": bundle["version"]}

    # ② 정산
    settled = settle_history(pub / "history.csv", games)

    # ③ 상태 누적 (target 이전 정규시즌 FINAL 경기만 — 학습 시 build_training_frame과 동일)
    state = LeagueState()
    for g in sorted((g for g in games if g["status"] == "FINAL" and g["date"] < iso
                     and seasons.is_regular(int(g["season"]), date.fromisoformat(g["date"]))),
                    key=lambda g: (g["date"], g["game_id"])):
        state.update(g)

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
            e = predict_game(bundle, g, state)
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
