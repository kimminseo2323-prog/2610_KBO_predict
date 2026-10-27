"""일정 + RESULT 경기 박스스코어 수집 CLI.

사용: python -m kbo_predict.collect --from 2026-03-01 --to 2026-10-31
이미 저장된 record는 건너뛰므로 중단 후 같은 범위로 재실행하면 이어서 진행된다.
"""
import argparse
from datetime import date, timedelta

from .naver_client import fetch_games, fetch_record
from .raw_store import append_records, load_records, upsert_games

PROGRESS_EVERY = 50
FLUSH_EVERY = 20


def _chunks(from_date: date, to_date: date, days: int = 31):
    """API는 size=500 상한이므로 긴 구간은 한 달 단위로 나눠 요청한다."""
    start = from_date
    while start <= to_date:
        end = min(start + timedelta(days=days - 1), to_date)
        yield start, end
        start = end + timedelta(days=1)


def collect_range(
    from_date: date,
    to_date: date,
    *,
    season: int | None = None,
    sleep_s: float = 1.0,
) -> dict:
    season = season or from_date.year
    games = [
        g
        for a, b in _chunks(from_date, to_date)
        for g in fetch_games(a, b, sleep_s=sleep_s)
    ]
    upsert_games(season, games)
    have = set(load_records(season))
    todo = [g["gameId"] for g in games if g["statusCode"] == "RESULT" and g["gameId"] not in have]
    fetched = 0
    batch: dict[str, dict] = {}
    try:
        for i, gid in enumerate(todo, 1):
            batch[gid] = fetch_record(gid, sleep_s=sleep_s)
            if len(batch) >= FLUSH_EVERY:
                fetched += append_records(season, batch)
                batch = {}
            if i % PROGRESS_EVERY == 0:
                print(f"records {i}/{len(todo)}", flush=True)
    finally:
        # 중단/실패해도 지금까지 받은 분은 저장 (재실행 시 이어서 진행)
        if batch:
            fetched += append_records(season, batch)
    return {"games": len(games), "records": fetched}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="from_date", type=date.fromisoformat, required=True)
    p.add_argument("--to", dest="to_date", type=date.fromisoformat, required=True)
    p.add_argument("--sleep", type=float, default=1.0)
    a = p.parse_args()
    print(collect_range(a.from_date, a.to_date, sleep_s=a.sleep))


if __name__ == "__main__":
    main()
