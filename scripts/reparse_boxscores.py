"""로컬 HTML 캐시로 박스스코어를 다시 파싱해 새 칸(2루타·3루타·도루·한글 이름)을 채운다.

기존 칸이 하나라도 달라지면 그 game_id를 출력하고 비정상 종료한다(아무 파일도 쓰지 않음).
네트워크 요청은 하지 않는다.

    python -X utf8 scripts/reparse_boxscores.py --cache data/cache/html --seasons 2015-2026 [--dry-run]
"""
import argparse
import sys
from collections import Counter
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


def label_counts(recs) -> Counter:
    """records_unmatched 항목 수를 라벨별로 센다 ('HR off'는 따로)."""
    c: Counter = Counter()
    for r in recs:
        for u in r.get("records_unmatched", []):
            c["HR off" if u.startswith("HR off:") else u.split(":")[0]] += 1
    return c


def vote_ko_names(recs, min_share: float = 0.6) -> dict[int, str]:
    """모든 경기의 names_ko에서 선수별 한글 이름을 다수결로 정한다 (1위가 득표의 60% 이상일 때만)."""
    votes: dict[int, Counter] = {}
    for r in recs:
        for pid, ko in r.get("names_ko", {}).items():
            votes.setdefault(int(pid), Counter())[ko] += 1
    out = {}
    for pid, c in votes.items():
        ko, n = c.most_common(1)[0]
        if n / sum(c.values()) >= min_share:
            out[pid] = ko
    return out


def _unmatched_hangul(rec: dict):
    """(이름, 종류) 목록. 종류 'bat'은 타자 행, 'pit'은 투수 행에서 찾는다(HR off). E는 둘 다라 건너뛴다."""
    for u in rec.get("records_unmatched", []):
        label, _, rest = u.partition(": ")
        name = rest.split(" (", 1)[0].strip()
        if label != "E" and any("가" <= ch <= "힣" for ch in name):
            yield name, ("pit" if label == "HR off" else "bat")


def infer_aliases(recs, min_games: int = 3) -> dict[tuple[str, str], int]:
    """기록표 한글 이름과 행 이름이 영영 안 맞는 선수(개명 등)를 찾는다.
    같은 (이름, 종류)가 못 붙은 모든 경기에서, 그 경기에 이미 다른 한글 이름이 붙은 선수를 뺀 후보를 교집합해
    정확히 한 명이 남으면(그리고 3경기 이상) 그 선수의 별칭으로 본다."""
    cand: dict[tuple[str, str], set[int]] = {}
    games: Counter = Counter()
    for r in recs:
        for key in set(_unmatched_hangul(r)):
            rows = r["pitching" if key[1] == "pit" else "batting"]
            ids = {x["player_id"] for t in ("away", "home") for x in rows[t] if str(x["player_id"]) not in r["names_ko"]}
            cand[key] = ids if key not in cand else cand[key] & ids
            games[key] += 1
    return {k: next(iter(v)) for k, v in cand.items() if len(v) == 1 and games[k] >= min_games}


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

    # 두 번째 패스: 다른 경기에서 알아낸 한글 이름으로, 아직 못 붙인 항목이 있는 경기만 다시 파싱한다
    before = label_counts(r for season in parse_seasons(args.seasons) for r in raw_store.load_boxscores(season).values())
    ko_map = vote_ko_names(r for new in new_by_season.values() for r in new.values())
    aliases = infer_aliases(r for new in new_by_season.values() for r in new.values())
    print(f"ko name votes: {len(ko_map)} players, aliases: {len(aliases)}", flush=True)
    for season, new in new_by_season.items():
        old = raw_store.load_boxscores(season)
        for gid, rec in list(new.items()):
            if not rec.get("records_unmatched"):
                continue
            files = sorted(cache.glob(f"games_{gid}-*.html"))
            ids = {r["player_id"] for side in ("batting", "pitching") for t in ("away", "home") for r in rec[side][t]}
            ko = {p: ko_map[p] for p in ids if p in ko_map}
            for name, kind in set(_unmatched_hangul(rec)):
                if aliases.get((name, kind)) in ids:
                    ko[aliases[(name, kind)]] = name
            fresh = parse_game(files[0].read_text(encoding="utf-8"), ko)
            if strip_new(fresh) != strip_new(old[gid]):
                mismatches.append(gid)
            else:
                new[gid] = fresh
    after = label_counts(r for new in new_by_season.values() for r in new.values())
    print("\nunmatched by label (before -> after):")
    for k in sorted(set(before) | set(after)):
        print(f"  {k:7s} {before[k]:5d} -> {after[k]:5d}")
    print(f"  total   {sum(before.values()):5d} -> {sum(after.values()):5d}")
    rows = [(r[0], r[1], r[2], r[3], r[4],
             sum(len(x["records_unmatched"]) for x in new_by_season[r[0]].values()),
             sum(u.startswith("HR off:") for x in new_by_season[r[0]].values() for u in x["records_unmatched"]))
            for r in rows]

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
