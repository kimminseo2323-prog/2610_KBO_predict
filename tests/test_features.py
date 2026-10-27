from datetime import date

import pytest

from kbo_predict import teams
from kbo_predict.features import (
    FACTOR_LABELS,
    FEATURE_NAMES,
    LeagueState,
    build_training_frame,
    game_features,
)
from kbo_predict.mykbo_parse import parse_week


def mk(date, gid, home="LG Twins", away="Hanwha Eagles", hs=None, as_=None, status="FINAL"):
    return {
        "game_id": gid,
        "path": f"/games/{gid}",
        "datetime_utc": f"{date}T09:30:00Z",
        "date": date,
        "season": int(date[:4]),
        "away": away,
        "home": home,
        "away_code": teams.code_for(away),
        "home_code": teams.code_for(home),
        "away_score": as_,
        "home_score": hs,
        "status": status,
        "status_note": "",
        "time_kst": "18:30",
        "stadium": "Test Park",
    }


def test_state_defaults_when_empty():
    s = LeagueState()
    assert s.team_win_pct("LG") == 0.5 and s.team_last10("LG") == 0.5 and s.team_run_diff("LG") == 0.0


def test_state_updates_from_week_fixture(fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2026-08-11.html"))
    s = LeagueState()
    for r in rows:
        s.update(r)
    hh = [r for r in rows if r["status"] == "FINAL" and "HH" in (r["home_code"], r["away_code"])]
    wins = sum((r["home_score"] > r["away_score"]) == (r["home_code"] == "HH") for r in hh if r["home_score"] != r["away_score"])
    assert s.team_win_pct("HH") == pytest.approx(wins / len([r for r in hh if r["home_score"] != r["away_score"]]))
    assert s.team_line("HH")["games"] == len(hh)


def test_canceled_and_scheduled_not_counted():
    s = LeagueState()
    s.update(mk("2026-08-16", 1, hs=None, as_=None, status="CANCELED"))
    s.update(mk("2026-08-17", 2, status="SCHEDULED"))
    assert s.team_win_pct("LG") == 0.5 and s.team_line("LG")["games"] == 0


def test_draw_counts_runs_but_not_wins():
    s = LeagueState()
    s.update(mk("2026-08-16", 1, hs=3, as_=3))
    assert s.team_win_pct("LG") == 0.5 and s.team_last10("LG") == 0.5 and s.team_line("LG")["games"] == 1 and s.team_run_diff("LG") == 0.0


def test_last10_and_line_keys():
    s = LeagueState()
    for i in range(12):
        s.update(mk("2026-04-%02d" % (i + 1), i + 1, hs=5 if i < 2 else 1, as_=2 if i < 2 else 3))
    # LG won first 2, lost next 10 -> last 10 are all losses
    assert s.team_last10("LG") == 0.0
    assert s.team_win_pct("LG") == pytest.approx(2 / 12)
    assert set(s.team_line("LG")) == {"win_pct", "last10", "run_diff", "games"}


def test_game_features_and_labels():
    s = LeagueState()
    s.update(mk("2026-04-01", 1, hs=5, as_=2))
    f = game_features(mk("2026-04-02", 2), s)
    assert set(FEATURE_NAMES) <= set(f) and "home_line" in f and "away_line" in f
    assert f["win_pct_diff"] == pytest.approx(1.0)
    assert f["home_line"]["games"] == 1
    assert FACTOR_LABELS["intercept"] == "홈 어드밴티지"


def test_build_training_frame_has_no_leakage():
    games = [mk("2026-04-01", 1, hs=5, as_=2), mk("2026-04-02", 2, hs=4, as_=1), mk("2026-04-03", 3, hs=0, as_=1)]
    df_a = build_training_frame(games, season=2026)
    df_b = build_training_frame(games[:2] + [mk("2026-04-03", 3, hs=9, as_=1)], season=2026)  # d3 결과만 바꿈
    assert df_a.loc[df_a.game_id == 3, FEATURE_NAMES].values.tolist() == df_b.loc[df_b.game_id == 3, FEATURE_NAMES].values.tolist()
    assert df_a.loc[df_a.game_id == 1, FEATURE_NAMES].values.tolist() == [[0.0, 0.0, 0.0]]  # 첫 경기는 기본값
    assert df_a.loc[df_a.game_id == 3, "win_pct_diff"].item() == pytest.approx(1.0)
    assert df_a.loc[df_a.game_id == 3, "run_diff_diff"].item() == pytest.approx(6.0)  # LG +3, HH −3
    assert df_a.y.tolist() == [1, 1, 0]
    assert list(df_a.columns) == ["game_id", "date", *FEATURE_NAMES, "y"]


def test_build_training_frame_excludes_draws_and_postseason():
    games = [mk("2026-04-01", 1, hs=2, as_=2), mk("2026-04-02", 2, hs=3, as_=1), mk("2026-10-20", 3, hs=1, as_=0)]  # 10-20은 포스트시즌
    df = build_training_frame(games, season=2026)
    assert df.game_id.tolist() == [2]


def test_same_day_games_do_not_leak_into_each_other():
    games = [mk("2026-04-01", 1, hs=5, as_=2), mk("2026-04-01", 2, hs=5, as_=2)]  # 더블헤더
    df = build_training_frame(games, season=2026)
    assert df[FEATURE_NAMES].values.tolist() == [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
