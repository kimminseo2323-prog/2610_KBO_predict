"""원본(파싱된) 데이터 저장: games.jsonl, boxscores/YYYY-MM.jsonl.gz (월별 분할)."""
import gzip
import json
import os
from pathlib import Path


def data_dir() -> Path:
    return Path(os.environ.get("KBO_DATA_DIR", "data"))


def games_path(season: int) -> Path:
    return data_dir() / "raw" / str(season) / "games.jsonl"


def boxscores_dir(season: int) -> Path:
    return data_dir() / "raw" / str(season) / "boxscores"


def boxscores_month_path(season: int, yyyymm: str) -> Path:
    """yyyymm은 'YYYY-MM' 형식. 매일 커밋되는 파일이 커지지 않게 월별로 분할."""
    return boxscores_dir(season) / f"{yyyymm}.jsonl.gz"


def starters_path(season: int) -> Path:
    return data_dir() / "raw" / str(season) / "starters.jsonl"


def available_seasons() -> list[int]:
    """games.jsonl이 있는 시즌을 오름차순으로 반환."""
    raw = data_dir() / "raw"
    if not raw.exists():
        return []
    return sorted(int(p.name) for p in raw.iterdir() if p.name.isdigit() and (p / "games.jsonl").exists())


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
    """월별 파일을 파일명 순으로 모두 읽어 game_id -> 박스스코어로 합친다."""
    out: dict[int, dict] = {}
    for path in sorted(boxscores_dir(season).glob("*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    out[r["game_id"]] = r
    return out


def append_boxscores(season: int, boxscores: dict[int, dict]) -> int:
    """이미 있는 game_id는 건너뛰고 새 박스스코어만 월 파일에 추가. 추가 수를 반환."""
    existing = load_boxscores(season)
    by_month: dict[str, list[tuple[int, dict]]] = {}
    for gid, b in boxscores.items():
        if gid not in existing:
            by_month.setdefault(b["date"][:7], []).append((gid, b))
    for month, items in by_month.items():
        path = boxscores_month_path(season, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "at", encoding="utf-8", newline="\n") as f:
            for gid, b in items:
                f.write(_dumps({**b, "game_id": gid}) + "\n")
    return sum(len(v) for v in by_month.values())


def load_starters(season: int) -> dict[int, dict]:
    """예고 선발 행을 game_id -> 행으로 읽는다."""
    path = starters_path(season)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {r["game_id"]: r for r in (json.loads(line) for line in f if line.strip())}


def upsert_starters(season: int, rows: list[dict]) -> int:
    """game_id 기준 덮어쓰기(fetched_at 제외 비교). 신규 + 선발이 바뀐 행 수를 반환.
    알려진 선발은 None(미정)으로 되돌리지 않는다: 새 행의 한쪽이 None인데 저장된 행의 같은 쪽이 있으면
    저장된 쪽을 유지한다 (섹션이 빠진 페이지·홈만 새로 발표된 페이지를 다시 받아도 이미 알던 선발이 지워지지 않게)."""
    by_id = load_starters(season)
    changed = 0
    for r in rows:
        old = by_id.get(r["game_id"])
        if old is not None:
            r = {**r, **{side: old.get(side) for side in ("away", "home") if r.get(side) is None}}
        # 다시 받아도 선발이 같으면 저장된 행(원래 fetched_at)을 유지한다
        if old is None or {k: v for k, v in old.items() if k != "fetched_at"} != {k: v for k, v in r.items() if k != "fetched_at"}:
            by_id[r["game_id"]] = r
            changed += 1
    if changed:
        path = starters_path(season)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as f:
            for r in sorted(by_id.values(), key=lambda r: (r["date"], r["game_id"])):
                f.write(_dumps(r) + "\n")
    return changed
