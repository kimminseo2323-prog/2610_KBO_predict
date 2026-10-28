"""MyKBOStats 수집 CLI: 주간 일정 -> games.jsonl, FINAL 경기 박스스코어 -> boxscores.jsonl.gz."""
import argparse
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests

from kbo_predict import KST, raw_store
from kbo_predict.mykbo_client import SLEEP_S, fetch_html, week_path
from kbo_predict.mykbo_parse import parse_game, parse_week

PROGRESS_EVERY = 20
STALE_LIVE_DAYS = 2  # 이만큼 지난 LIVE 행은 경기 페이지로 확인한다 (경기 페이지가 하루쯤 늦을 수 있다)


def season_range(season: int) -> tuple[date, date]:
    return date(season, 3, 1), date(season, 11, 30)


def _fetch_box(row: dict, sleep_s: float, errors: list[dict]) -> dict | None:
    """경기 페이지 가져오기 + 파싱 + game_id 검사. 실패하면 errors에 기록하고 None."""
    try:
        box = parse_game(fetch_html(row["path"], sleep_s=sleep_s))
        if box["game_id"] != row["game_id"]:
            raise ValueError(f"game_id mismatch: week={row['game_id']} page={box['game_id']}")
        return box
    except (ValueError, KeyError, requests.RequestException) as e:
        err = {"game_id": row["game_id"], "path": row["path"], "error": f"{type(e).__name__}: {e}"}
        errors.append(err)
        print(f"[collect] {err['path']}: {err['error']}", file=sys.stderr, flush=True)
        return None


def collect_range(from_date: date, to_date: date, *, season: int | None = None, sleep_s: float = SLEEP_S,
                  today: date | None = None) -> dict:
    today = today or datetime.now(KST).date()
    stale_cutoff = (today - timedelta(days=STALE_LIVE_DAYS)).isoformat()
    errors: list[dict] = []
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
                # 주간 일정에서 멈춘 LIVE 행: 경기 페이지가 FINAL+양팀 점수일 때만 확정 (결과를 지어내지 않는다)
                boxes = {}
                for r in s_rows:
                    if r["status"] == "LIVE" and r["date"] <= stale_cutoff:
                        box = _fetch_box(r, sleep_s, errors)
                        if box and box["status"] == "FINAL" and None not in (box["away"]["score"], box["home"]["score"]):
                            r.update(status="FINAL", away_score=box["away"]["score"], home_score=box["home"]["score"])
                            boxes[r["game_id"]] = box
                raw_store.upsert_games(s, s_rows)
                games += len(s_rows)
                if s not in done:
                    done[s] = set(raw_store.load_boxscores(s))
                have = done[s]
                for r in s_rows:
                    if r["status"] != "FINAL" or r["game_id"] in have:
                        continue
                    box = boxes.get(r["game_id"]) or _fetch_box(r, sleep_s, errors)
                    if box is None:
                        continue
                    pending[s][r["game_id"]] = box
                    have.add(r["game_id"])
                    fetched_games += 1
                    if fetched_games % PROGRESS_EVERY == 0:
                        flush()
                        print(f"[collect] {fetched_games} boxscores fetched (week of {d})", file=sys.stderr, flush=True)
            d += timedelta(days=7)
    finally:
        flush()
    return {"weeks": weeks, "games": games, "boxscores": boxscores, "errors": errors}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="MyKBOStats 일정/박스스코어 수집")
    ap.add_argument("--sleep", type=float, default=SLEEP_S)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--season", type=int, help="시즌 전체 (3/1~11/30)")
    grp.add_argument("--from", dest="from_date", type=date.fromisoformat)
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat)
    args = ap.parse_args(argv)
    if args.season:
        out = collect_range(*season_range(args.season), season=args.season, sleep_s=args.sleep)
    else:
        if not args.to_date:
            ap.error("--from requires --to")
        out = collect_range(args.from_date, args.to_date, sleep_s=args.sleep)
    print(out)


if __name__ == "__main__":
    main()
