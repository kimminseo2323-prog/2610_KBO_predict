"""로컬 HTML 캐시로 박스스코어를 다시 파싱해 새 칸(2루타·3루타·도루·한글 이름)을 채운다.

기존 칸이 하나라도 달라지면 그 game_id를 출력하고 비정상 종료한다(아무 파일도 쓰지 않음).
네트워크 요청은 하지 않는다.

    python -X utf8 scripts/reparse_boxscores.py --cache data/cache/html --seasons 2015-2026 [--dry-run] [--infer-aliases]

재현성: 한글 이름 다수결(names_ko 투표)은 --seasons와 상관없이 data/raw의 모든 시즌을 대상으로 한다
(--seasons에 없는 시즌은 디스크의 현재 값을 쓴다). 별칭은 data/raw/name_aliases.json이 있으면 항상 그것을 읽고,
--infer-aliases를 줄 때만 (모든 시즌에서) 다시 추론해 덮어쓴다. 별칭 파일은 맨 마지막 쓰기 직전에야 저장한다.
"""
import argparse
import json
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


ALIASES_PATH = "name_aliases.json"  # data/raw/ 아래. 있으면 그대로 읽고, --infer-aliases(또는 파일 없음)일 때만 추론한다


def infer_aliases(recs, ko_map: dict[int, str], min_games: int = 5) -> dict[str, dict]:
    """기록표 한글 이름과 행 이름이 영영 안 맞는 선수(개명 등)를 찾는다.
    같은 (이름, 종류)가 못 붙은 모든 경기에서, 그 경기에 이미 다른 한글 이름이 붙은 선수를 뺀 후보를 교집합해
    정확히 한 명이 남고, 5경기 이상이며, 그 한글 이름이 다른 선수의 다수결 이름이 아니면 그 선수의 별칭으로 본다.
    같은 이름이 타자·투수 양쪽에서 서로 다른 선수로 나오면 버린다."""
    cand: dict[tuple[str, str], set[int]] = {}
    games: Counter = Counter()
    for r in recs:
        for key in set(_unmatched_hangul(r)):
            rows = r["pitching" if key[1] == "pit" else "batting"]
            ids = {x["player_id"] for t in ("away", "home") for x in rows[t] if str(x["player_id"]) not in r["names_ko"]}
            cand[key] = ids if key not in cand else cand[key] & ids
            games[key] += 1
    voted = Counter(ko_map.values())
    out: dict[str, dict] = {}
    dropped = set()
    for (name, kind), ids in cand.items():
        if len(ids) != 1 or games[(name, kind)] < min_games:
            continue
        pid = next(iter(ids))
        if any(v == name and k != pid for k, v in ko_map.items()):
            continue
        if name in out and out[name]["player_id"] != pid:
            dropped.add(name)
        out[name] = {"player_id": pid, "games": games[(name, kind)]}
    return {k: out[k] for k in sorted(out) if k not in dropped}


def parse_seasons(text: str) -> list[int]:
    a, _, b = text.partition("-")
    return list(range(int(a), int(b or a) + 1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="data/cache/html")
    ap.add_argument("--seasons", default="2015-2026")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--infer-aliases", action="store_true", help="별칭 파일이 있어도 다시 추론해 덮어쓴다")
    args = ap.parse_args(argv)
    cache = Path(args.cache)
    targets = parse_seasons(args.seasons)

    old_by_season = {s: raw_store.load_boxscores(s) for s in targets}  # 시즌당 한 번만 읽는다
    new_by_season: dict[int, dict[int, dict]] = {}
    no_cache_by_season: dict[int, int] = {}
    mismatches: list[int] = []
    missing_ids: list[int] = []
    for season in targets:
        new: dict[int, dict] = {}
        no_cache = 0
        for gid, rec in old_by_season[season].items():
            files = sorted(cache.glob(f"games_{gid}-*.html"))
            if not files:
                no_cache += 1
                missing_ids.append(gid)
                new[gid] = fill_none(rec)  # 기록표 칸은 None으로 남긴다
                continue
            fresh = parse_game(files[0].read_text(encoding="utf-8"))
            if strip_new(fresh) != strip_new(rec):
                mismatches.append(gid)
                continue
            new[gid] = fresh
        new_by_season[season] = new
        no_cache_by_season[season] = no_cache
        print(f"season {season} done", flush=True)

    # 두 번째 패스: 다른 경기에서 알아낸 한글 이름으로, 아직 못 붙인 항목이 있는 경기만 다시 파싱한다
    before = label_counts(r for old in old_by_season.values() for r in old.values())
    # 투표·별칭 추론은 항상 모든 시즌에서 (대상 시즌은 방금 파싱한 값, 나머지는 디스크 값)
    all_recs = []
    for season in raw_store.available_seasons():
        all_recs.extend((new_by_season[season] if season in new_by_season else raw_store.load_boxscores(season)).values())
    ko_map = vote_ko_names(all_recs)
    alias_file = raw_store.data_dir() / "raw" / ALIASES_PATH
    inferred = args.infer_aliases or not alias_file.exists()
    aliases = infer_aliases(all_recs, ko_map) if inferred else json.loads(alias_file.read_text(encoding="utf-8"))
    print(f"ko name votes: {len(ko_map)} players, aliases: {len(aliases)}", flush=True)
    for season, new in new_by_season.items():
        for gid, rec in list(new.items()):
            if not rec.get("records_unmatched"):
                continue
            files = sorted(cache.glob(f"games_{gid}-*.html"))
            if not files:
                # 캐시가 없는 경기(첫 패스에서 이미 no_cache·cache-missing으로 셌다): 다시 파싱할 HTML이 없으니 그대로 둔다
                continue
            ids = {r["player_id"] for side in ("batting", "pitching") for t in ("away", "home") for r in rec[side][t]}
            ko = {p: ko_map[p] for p in ids if p in ko_map}
            for name, _kind in set(_unmatched_hangul(rec)):
                if name in aliases and aliases[name]["player_id"] in ids:
                    ko[aliases[name]["player_id"]] = name
            fresh = parse_game(files[0].read_text(encoding="utf-8"), ko)
            if strip_new(fresh) != strip_new(old_by_season[season][gid]):
                mismatches.append(gid)
            else:
                new[gid] = fresh
    after = label_counts(r for new in new_by_season.values() for r in new.values())
    print("\nunmatched by label (before -> after):")
    for k in sorted(set(before) | set(after)):
        print(f"  {k:7s} {before[k]:5d} -> {after[k]:5d}")
    print(f"  total   {sum(before.values()):5d} -> {sum(after.values()):5d}")

    rows = []
    for season in targets:
        new = new_by_season[season]
        recs = list(new.values())
        no_table = sum(1 for r in recs if not (r["batting"]["away"] + r["batting"]["home"])
                       or (r["batting"]["away"] + r["batting"]["home"])[0]["doubles"] is None)
        unmatched = sum(len(r["records_unmatched"]) for r in recs)
        hr_off = sum(u.startswith("HR off:") for r in recs for u in r["records_unmatched"])
        rows.append((season, len(old_by_season[season]), len(old_by_season[season]) - no_cache_by_season[season],
                     no_cache_by_season[season], no_table, unmatched, hr_off))
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
    if inferred:  # 모든 검사를 통과한 뒤, 데이터를 쓰기 직전에 저장
        alias_file.write_text(json.dumps(aliases, ensure_ascii=False, sort_keys=True, indent=1) + chr(10), encoding="utf-8")
    for season, new in new_by_season.items():
        print(f"wrote {raw_store.rewrite_boxscores(season, new)} rows for {season}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
