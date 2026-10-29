"""로컬 HTML 캐시로 박스스코어를 다시 파싱해 새 칸(2루타·3루타·도루·한글 이름)을 채운다.

기존 칸이 하나라도 달라지면 그 game_id를 출력하고 비정상 종료한다(아무 파일도 쓰지 않음).
네트워크 요청은 하지 않는다.

    python -X utf8 scripts/reparse_boxscores.py --cache data/cache/html --seasons 2015-2026 [--dry-run]
"""
import argparse
import sys
from pathlib import Path

from kbo_predict import raw_store
from kbo_predict.mykbo_parse import parse_game

NEW_TOP = {"names_ko", "records_unmatched"}
NEW_BAT = {"doubles", "triples", "sb"}


def strip_new(rec: dict) -> dict:
    """새 키를 뺀 사본. 기존 칸 비교용."""
    out = {k: v for k, v in rec.items() if k not in NEW_TOP}
    out["batting"] = {s: [{k: v for k, v in r.items() if k not in NEW_BAT} for r in rec["batting"][s]]
                      for s in ("away", "home")}
    return out


def fill_none(rec: dict) -> dict:
    """캐시가 없는 경기: 새 칸을 None/빈 값으로 채워 스키마만 맞춘다."""
    out = {**rec, "names_ko": rec.get("names_ko", {}), "records_unmatched": rec.get("records_unmatched", [])}
    out["batting"] = {s: [{**r, **{k: r.get(k) for k in NEW_BAT}} for r in rec["batting"][s]] for s in ("away", "home")}
    return out


def parse_seasons(text: str) -> list[int]:
    a, _, b = text.partition("-")
    return list(range(int(a), int(b or a) + 1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="data/cache/html")
    ap.add_argument("--seasons", default="2015-2026")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    cache = Path(args.cache)

    new_by_season: dict[int, dict[int, dict]] = {}
    rows = []
    mismatches: list[int] = []
    missing_ids: list[int] = []
    for season in parse_seasons(args.seasons):
        old = raw_store.load_boxscores(season)
        new: dict[int, dict] = {}
        reparsed = no_cache = no_table = unmatched = hr_off = 0
        for gid, rec in old.items():
            files = sorted(cache.glob(f"games_{gid}-*.html"))
            if not files:
                no_cache += 1
                missing_ids.append(gid)
                new[gid] = fill_none(rec)  # 기록표 칸은 None으로 남긴다
                no_table += 1
                continue
            fresh = parse_game(files[0].read_text(encoding="utf-8"))
            reparsed += 1
            if strip_new(fresh) != strip_new(rec):
                mismatches.append(gid)
                continue
            new[gid] = fresh
            bat = fresh["batting"]["away"] + fresh["batting"]["home"]
            no_table += (not bat) or bat[0]["doubles"] is None
            unmatched += len(fresh["records_unmatched"])
            hr_off += sum(u.startswith("HR off:") for u in fresh["records_unmatched"])
        new_by_season[season] = new
        rows.append((season, len(old), reparsed, no_cache, no_table, unmatched, hr_off))
        print(f"season {season} done", flush=True)

    print("\nseason  games  reparsed  no_cache  no_table  unmatched  (of which HR off)")
    for r in rows:
        print("%-7d %5d  %8d  %8d  %8d  %9d  %d" % r)
    print("total   %5d  %8d  %8d  %8d  %9d  %d" % tuple(sum(r[i] for r in rows) for i in range(1, 7)))
    if missing_ids:
        print("cache-missing game_ids:", missing_ids)
    if mismatches:
        print("MISMATCH (existing fields changed), nothing written:", sorted(mismatches))
        return 1
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    for season, new in new_by_season.items():
        print(f"wrote {raw_store.rewrite_boxscores(season, new)} rows for {season}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
