"""시즌별 정규시즌 종료일 탐색 (백필 데이터 기반 검증용).

개막일 이후 FINAL/LIVE 경기를 (date, game_id) 순으로 세어 total(720)번째 경기의 날짜를
정규시즌 마지막 날로 본다. 판단 근거는 세 가지: 720번째 경기 시점에 모든 팀이 정확히 144경기
(team_games), 그 다음 경기가 포스트시즌 대진, 그리고 count_through_end 점검.
포스트시즌이 하루 만에 시작될 수 있으므로 gap_days는 1일일 수도 있다(참고용).
같은 날 열린 순위 결정전은 count_through_end가 total보다 커서 드러난다(seasons.EXCLUDED_GAMES 참고).
CLI: python -X utf8 scripts/season_bounds.py --season 2015 --opening 2015-03-28
"""
import argparse
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def find_end(games: list[dict], opening: date, total: int = 720) -> dict:
    played = sorted(
        (g["date"], g["game_id"])
        for g in games
        if g["status"] in ("FINAL", "LIVE") and date.fromisoformat(g["date"]) >= opening
    )
    if not played:
        return {"end": None, "count": 0, "count_through_end": 0, "team_games": {}, "next_game": None, "gap_days": None, "per_day": {}}
    end = date.fromisoformat(played[min(total, len(played)) - 1][0])
    later = [d for d, _ in played if date.fromisoformat(d) > end]
    next_game = date.fromisoformat(later[0]) if later else None
    per_day_all = Counter(d for d, _ in played)
    per_day = {}
    for k in range(-5, 6):
        key = (end + timedelta(days=k)).isoformat()
        per_day[key] = per_day_all.get(key, 0)
    through_end = sum(1 for d, _ in played if date.fromisoformat(d) <= end)
    team_games: Counter = Counter()
    by_key = {(g["date"], g["game_id"]): g for g in games if g["status"] in ("FINAL", "LIVE")}
    for key in played[:total]:
        g = by_key[key]
        team_games[g.get("home_code")] += 1
        team_games[g.get("away_code")] += 1
    return {
        "end": end,
        "count": len(played),
        "count_through_end": through_end,
        "team_games": dict(sorted(team_games.items())),
        "next_game": next_game,
        "gap_days": (next_game - end).days if next_game else None,
        "per_day": per_day,
    }


def main() -> None:
    for p in (_ROOT, _ROOT / "src"):  # CLI 실행 시에만 import 경로 보강
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from kbo_predict.raw_store import load_games

    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--opening", type=date.fromisoformat, required=True)
    ap.add_argument("--total", type=int, default=720)
    a = ap.parse_args()
    out = find_end(load_games(a.season), a.opening, a.total)
    print(f"season={a.season} opening={a.opening}")
    for k in ("end", "count", "count_through_end", "next_game", "gap_days", "team_games"):
        print(f"{k}: {out[k]}")
    print("per_day:")
    for d, n in out["per_day"].items():
        print(f"  {d}: {n}")
    if out["count"] < a.total:
        print(f"WARNING: count {out['count']} < total {a.total}")


if __name__ == "__main__":
    main()
