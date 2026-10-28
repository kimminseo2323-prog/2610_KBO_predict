from datetime import date
from scripts.season_bounds import find_end

def _g(gid, d, status="FINAL"):
    return {"game_id": gid, "date": d, "status": status, "home_code": "A", "away_code": "B"}

def test_find_end_counts_final_and_live_from_opening():
    games = [_g(1, "2020-03-01"), *(_g(10 + i, f"2020-05-{5 + i // 2:02d}") for i in range(6)),
             _g(99, "2020-05-08", "LIVE"), _g(100, "2020-05-12")]
    out = find_end(games, date(2020, 5, 5), total=7)
    assert out["end"] == date(2020, 5, 8) and out["count"] == 8
    assert out["count_through_end"] == 7  # 05-05~05-07의 6경기 + 05-08 LIVE 1경기 (05-12 경기 제외)
    assert out["team_games"] == {"A": 7, "B": 7}
    assert out["next_game"] == date(2020, 5, 12) and out["gap_days"] == 4

def test_find_end_short_season_reports_last_date():
    games = [_g(1, "2020-05-05"), _g(2, "2020-05-06")]
    out = find_end(games, date(2020, 5, 5), total=720)
    assert out["count"] == 2 and out["end"] == date(2020, 5, 6) and out["next_game"] is None
