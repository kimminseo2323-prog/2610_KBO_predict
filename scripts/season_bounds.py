"""시즌별 정규시즌 종료일 탐색 (백필 데이터 기반 검증용).

개막일 이후 FINAL/LIVE 경기를 (date, game_id) 순으로 세어 total(720)번째 경기의 날짜를
정규시즌 마지막 날로 본다. 그 뒤 첫 경기까지의 공백(gap_days)이 2일 이상이면 포스트시즌 시작.
CLI: python -X utf8 scripts/season_bounds.py --season 2015 --opening 2015-03-28
"""
import argparse
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def find_end(games: list[dict], opening: date, total: int = 720) -> dict:
    played = sorted(
        (g["date"], g["game_id"])
        for g in games
        if g["status"] in ("FINAL", "LIVE") and date.fromisoformat(g["date"]) >= opening
    )
    if not played:
        return {"end": None, "count": 0, "next_game": None, "gap_days": None, "per_day": {}}
    end = date.fromisoformat(played[min(total, len(played)) - 1][0])
    later = [d for d, _ in played if date.fromisoformat(d) > end]
    next_game = date.fromisoformat(later[0]) if later else None
    per_day_all = Counter(d for d, _ in played)
    per_day = {}
    for k in range(-5, 6):
        key = (end + timedelta(days=k)).isoformat()
        per_day[key] = per_day_all.get(key, 0)
    return {
        "end": end,
        "count": len(played),
        "next_game": next_game,
        "gap_days": (next_game - end).days if next_game else None,
        "per_day": per_day,
    }


def main() -> None:
    from kbo_predict.raw_store import load_games

    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--opening", type=date.fromisoformat, required=True)
    ap.add_argument("--total", type=int, default=720)
    a = ap.parse_args()
    out = find_end(load_games(a.season), a.opening, a.total)
    print(f"season={a.season} opening={a.opening}")
    for k in ("end", "count", "next_game", "gap_days"):
        print(f"{k}: {out[k]}")
    print("per_day:")
    for d, n in out["per_day"].items():
        print(f"  {d}: {n}")
    if out["count"] < a.total:
        print(f"WARNING: count {out['count']} < total {a.total}")


if __name__ == "__main__":
    main()
