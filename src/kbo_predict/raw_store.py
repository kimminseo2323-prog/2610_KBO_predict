"""원본(파싱된) 데이터 저장: games.jsonl, boxscores.jsonl.gz."""
import gzip
import json
import os
from pathlib import Path


def data_dir() -> Path:
    return Path(os.environ.get("KBO_DATA_DIR", "data"))


def games_path(season: int) -> Path:
    return data_dir() / "raw" / str(season) / "games.jsonl"


def boxscores_path(season: int) -> Path:
    return data_dir() / "raw" / str(season) / "boxscores.jsonl.gz"


def _dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def load_games(season: int) -> list[dict]:
    path = games_path(season)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def upsert_games(season: int, games: list[dict]) -> int:
    """game_id 기준 덮어쓰기. 신규 + 내용이 바뀐 경기 수를 반환."""
    by_id = {g["game_id"]: g for g in load_games(season)}
    changed = 0
    for g in games:
        old = by_id.get(g["game_id"])
        if old:  # LIVE/FINAL 행은 시간·구장이 비어 오므로 저장된 값을 유지
            g = dict(g)
            for k in ("time_kst", "stadium"):
                if g.get(k) is None and old.get(k) is not None:
                    g[k] = old[k]
        if by_id.get(g["game_id"]) != g:
            by_id[g["game_id"]] = g
            changed += 1
    if changed:
        path = games_path(season)
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(by_id.values(), key=lambda g: (g["date"], g["game_id"]))
        with path.open("w", encoding="utf-8", newline="\n") as f:
            for g in ordered:
                f.write(_dumps(g) + "\n")
    return changed


def load_boxscores(season: int) -> dict[int, dict]:
    path = boxscores_path(season)
    if not path.exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return {r["game_id"]: r for r in rows}


def append_boxscores(season: int, boxscores: dict[int, dict]) -> int:
    """이미 있는 game_id는 건너뛰고 새 박스스코어만 추가. 추가 수를 반환."""
    existing = load_boxscores(season)
    new = {gid: b for gid, b in boxscores.items() if gid not in existing}
    if new:
        path = boxscores_path(season)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "at", encoding="utf-8", newline="\n") as f:
            for gid, b in new.items():
                f.write(_dumps({**b, "game_id": gid}) + "\n")
    return len(new)
