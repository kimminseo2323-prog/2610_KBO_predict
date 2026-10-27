"""MyKBOStats 수집 CLI: 주간 일정 -> games.jsonl, FINAL 경기 박스스코어 -> boxscores.jsonl.gz."""
import argparse
import sys
from collections import defaultdict
from datetime import date, timedelta

from kbo_predict import raw_store
from kbo_predict.mykbo_client import SLEEP_S, fetch_html, week_path
from kbo_predict.mykbo_parse import parse_game, parse_week

PROGRESS_EVERY = 20


def collect_range(from_date: date, to_date: date, *, season: int | None = None, sleep_s: float = SLEEP_S) -> dict:
    lo, hi = from_date.isoformat(), to_date.isoformat()
    weeks = games = boxscores = 0
    done = {}  # season -> 이미 저장된 박스스코어 game_id 집합 (캐시)
    pending: dict[int, dict[int, dict]] = defaultdict(dict)

    def flush():
        nonlocal boxscores
        for s, batch in pending.items():
            boxscores += raw_store.append_boxscores(s, batch)
        pending.clear()

    fetched_games = 0
    d = from_date
    try:
        while d <= to_date:
            rows = [r for r in parse_week(fetch_html(week_path(d), sleep_s=sleep_s, use_cache=False))
                    if lo <= r["date"] <= hi and (season is None or r["season"] == season)]
            weeks += 1
            by_season = defaultdict(list)
            for r in rows:
                by_season[r["season"]].append(r)
            for s, s_rows in by_season.items():
                raw_store.upsert_games(s, s_rows)
                games += len(s_rows)
                if s not in done:
                    done[s] = set(raw_store.load_boxscores(s))
                have = done[s]
                for r in s_rows:
                    if r["status"] != "FINAL" or r["game_id"] in have:
                        continue
                    box = parse_game(fetch_html(r["path"], sleep_s=sleep_s))
                    if box["game_id"] != r["game_id"]:
                        raise ValueError(f"game_id mismatch: week={r['game_id']} page={box['game_id']} ({r['path']})")
                    pending[s][r["game_id"]] = box
                    have.add(r["game_id"])
                    fetched_games += 1
                    if fetched_games % PROGRESS_EVERY == 0:
                        flush()
                        print(f"[collect] {fetched_games} boxscores fetched (week of {d})", file=sys.stderr, flush=True)
            d += timedelta(days=7)
    finally:
        flush()
    return {"weeks": weeks, "games": games, "boxscores": boxscores}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="MyKBOStats 일정/박스스코어 수집")
    ap.add_argument("--from", dest="from_date", required=True, type=date.fromisoformat)
    ap.add_argument("--to", dest="to_date", required=True, type=date.fromisoformat)
    ap.add_argument("--sleep", type=float, default=SLEEP_S)
    args = ap.parse_args(argv)
    out = collect_range(args.from_date, args.to_date, sleep_s=args.sleep)
    print(out)


if __name__ == "__main__":
    main()
