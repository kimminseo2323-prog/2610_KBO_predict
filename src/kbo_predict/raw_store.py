"""원본 데이터 저장: games.jsonl (일정), records.jsonl.gz (박스스코어)."""
import gzip
import json
import os
from pathlib import Path


def _season_dir(season: int) -> Path:
    return Path(os.environ.get("KBO_DATA_DIR", "data")) / "raw" / str(season)


def games_path(season: int) -> Path:
    return _season_dir(season) / "games.jsonl"


def records_path(season: int) -> Path:
    return _season_dir(season) / "records.jsonl.gz"


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def load_games(season: int) -> list[dict]:
    path = games_path(season)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def upsert_games(season: int, games: list[dict]) -> int:
    by_id = {g["gameId"]: g for g in load_games(season)}
    changed = 0
    for g in games:
        if by_id.get(g["gameId"]) != g:
            by_id[g["gameId"]] = g
            changed += 1
    ordered = sorted(by_id.values(), key=lambda g: (g["gameDate"], g["gameId"]))
    path = games_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for g in ordered:
            f.write(_dumps(g) + "\n")
    return changed


def load_records(season: int) -> dict[str, dict]:
    path = records_path(season)
    if not path.exists():
        return {}
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                out[row["gameId"]] = row["recordData"]
    return out


def append_records(season: int, records: dict[str, dict]) -> int:
    existing = set(load_records(season))
    new = {gid: rec for gid, rec in records.items() if gid not in existing}
    if not new:
        return 0
    path = records_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "at", encoding="utf-8", newline="\n") as f:
        for gid, rec in new.items():
            f.write(_dumps({"gameId": gid, "recordData": rec}) + "\n")
    return len(new)
