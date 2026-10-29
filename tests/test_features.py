import math

import numpy as np
import pandas as pd
import pytest

from kbo_predict import teams
from kbo_predict.features import (
    FACTOR_LABELS,
    FEATURE_NAMES,
    STARTER_FEATURES,
    TEAM_FEATURES,
    LeagueState,
    build_training_frame,
    game_features,
    matchup_feature_names,
    regular_finals,
    starter_ids,
    starter_type,
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


_PIT_KEYS = ("ip_outs", "np", "r", "er", "h", "hr", "so", "bb", "hbp")
_BAT_KEYS = ("ab", "r", "h", "hr", "rbi", "bb", "so", "hbp")


def _pit_row(i, d):
    row = {k: 0 for k in _PIT_KEYS} | {"order": i + 1, "player_id": 9000 + i, "name": f"P{i}"}
    return row | d


def _bat_row(i, d):
    row = {k: 0 for k in _BAT_KEYS} | {"order": i + 1, "player_id": 8000 + i, "name": f"B{i}", "pos": "1B"}
    return row | d


def mkbox(game, home_pitchers=(), away_pitchers=(), home_bat=(), away_bat=()):
    """테스트용 박스스코어. 투수/타자 dict의 빠진 칸은 0으로 채운다 (order 기본값은 목록 순서)."""
    return {
        "date": game["date"],
        "game_id": game["game_id"],
        "status": "FINAL",
        "home": {"code": game["home_code"], "name": game["home"], "score": game["home_score"]},
        "away": {"code": game["away_code"], "name": game["away"], "score": game["away_score"]},
        "batting": {
            "home": [_bat_row(i, d) for i, d in enumerate(home_bat)],
            "away": [_bat_row(i, d) for i, d in enumerate(away_bat)],
        },
        "pitching": {
            "home": [_pit_row(i, d) for i, d in enumerate(home_pitchers)],
            "away": [_pit_row(i, d) for i, d in enumerate(away_pitchers)],
        },
        "linescore": None,
    }


def rows_equal(df_a, df_b, gid):
    """NaN끼리도 같다고 보는 한 경기 피처 행 비교."""
    a = df_a.loc[df_a.game_id == gid, FEATURE_NAMES].reset_index(drop=True)
    b = df_b.loc[df_b.game_id == gid, FEATURE_NAMES].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


# ---------- 이름·라벨 ----------

def test_feature_names_are_26_and_labelled():
    assert len(FEATURE_NAMES) == 26 and set(FACTOR_LABELS) == set(FEATURE_NAMES) | {"bias"}
    assert FEATURE_NAMES == TEAM_FEATURES + STARTER_FEATURES and len(set(FEATURE_NAMES)) == 26
    assert FACTOR_LABELS["bias"] == "기본 홈 어드밴티지"


# ---------- 기본 승패 상태 ----------

def test_state_defaults_when_empty():
    line = LeagueState().team_line("LG", "2026-04-01")
    assert line["win_pct"] is None and line["last10"] is None and line["run_diff"] is None and line["games"] == 0
    assert line["obp"] is None and line["pyth"] is None and line["rest_days"] is None and line["prev_win_pct"] is None
    assert line["home_pct"] is None and line["away_pct"] is None and line["bullpen3"] == 0


def test_state_updates_from_week_fixture(fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2026-08-11.html"))
    s = LeagueState()
    for r in rows:
        s.update(r)
    hh = [r for r in rows if r["status"] == "FINAL" and "HH" in (r["home_code"], r["away_code"])]
    decided = [r for r in hh if r["home_score"] != r["away_score"]]
    wins = sum((r["home_score"] > r["away_score"]) == (r["home_code"] == "HH") for r in decided)
    line = s.team_line("HH", "2026-08-20")
    assert line["win_pct"] == pytest.approx(wins / len(decided))
    assert line["games"] == len(hh)


def test_canceled_and_scheduled_not_counted():
    s = LeagueState()
    s.update(mk("2026-08-16", 1, hs=None, as_=None, status="CANCELED"))
    s.update(mk("2026-08-17", 2, status="SCHEDULED"))
    line = s.team_line("LG", "2026-08-18")
    assert line["win_pct"] is None and line["games"] == 0 and line["rest_days"] is None


def test_draw_counts_runs_but_not_wins():
    s = LeagueState()
    s.update(mk("2026-08-16", 1, hs=3, as_=3))
    line = s.team_line("LG", "2026-08-17")
    # 무승부만 있으면 승률·최근10 분모가 0 → None, 득실차는 경기 수가 분모라 0.0
    assert line["win_pct"] is None and line["last10"] is None and line["games"] == 1 and line["run_diff"] == 0.0
    assert line["pyth"] == pytest.approx(0.5) and line["home_pct"] is None
    assert s.h2h_home_pct("LG", "HH") is None


def test_last10_pyth_and_line_keys():
    s = LeagueState()
    for i in range(12):
        s.update(mk("2026-04-%02d" % (i + 1), i + 1, hs=5 if i < 2 else 1, as_=2 if i < 2 else 3))
    # LG won first 2, lost next 10 -> last 10 are all losses
    line = s.team_line("LG", "2026-04-13")
    assert line["last10"] == 0.0
    assert line["win_pct"] == pytest.approx(2 / 12)
    rf, ra = 2 * 5 + 10 * 1, 2 * 2 + 10 * 3
    assert line["pyth"] == pytest.approx(rf**1.83 / (rf**1.83 + ra**1.83))
    assert set(line) == {
        "win_pct", "last10", "run_diff", "pyth", "games", "obp", "hr_rate", "k_rate", "bb_rate",
        "era", "fip", "k9", "bb9", "home_pct", "away_pct", "prev_win_pct", "rest_days", "bullpen3",
    }


# ---------- 박스스코어 비율 ----------

def test_team_rates_from_boxscore():
    g = mk("2026-04-01", 1, hs=5, as_=3)
    box = mkbox(
        g,
        # 투수 합: ip_outs 27, ER 3, HR 1, BB 2, HBP 0, SO 9 (선발+구원 두 줄로 나눠 합산 확인, None 칸 포함)
        home_pitchers=[{"ip_outs": 18, "er": 2, "hr": 1, "bb": 1, "hbp": None, "so": 6},
                       {"ip_outs": 9, "er": 1, "hr": 0, "bb": 1, "hbp": 0, "so": 3}],
        # 타자 합: AB 30, H 9, BB 3, HBP 1, HR 2, SO 7
        home_bat=[{"ab": 20, "h": 6, "bb": 2, "hbp": 1, "hr": 2, "so": 5, "rbi": None},
                  {"ab": 10, "h": 3, "bb": 1, "hbp": None, "hr": 0, "so": 2}],
    )
    s = LeagueState()
    s.update(g, box)
    line = s.team_line("LG", "2026-04-02")
    assert line["obp"] == pytest.approx(13 / 34)
    assert line["hr_rate"] == pytest.approx(2 / 34)
    assert line["k_rate"] == pytest.approx(7 / 34)
    assert line["bb_rate"] == pytest.approx(3 / 34)
    assert line["era"] == pytest.approx(3.0)
    assert line["fip"] == pytest.approx((13 + 6 - 18) * 3 / 27)
    assert line["k9"] == pytest.approx(9.0)
    assert line["bb9"] == pytest.approx(2.0)
    # 원정(HH)은 박스에 기록 줄이 없어 분모 0 → None
    assert s.team_line("HH", "2026-04-02")["obp"] is None and s.team_line("HH", "2026-04-02")["era"] is None


def test_rates_are_nan_without_boxscore():
    s = LeagueState()
    s.update(mk("2026-04-01", 1, hs=5, as_=2), None)
    line = s.team_line("LG", "2026-04-02")
    assert line["win_pct"] == 1.0 and line["obp"] is None and line["era"] is None
    f = game_features(mk("2026-04-02", 2), s)
    assert f["win_pct_diff"] == pytest.approx(1.0)
    for name in ("obp_diff", "hr_rate_diff", "k_rate_diff", "bb_rate_diff", "era_diff", "fip_diff", "k9_diff", "bb9_diff"):
        assert math.isnan(f[name]), name


# ---------- 누수 ----------

def _leak_games():
    d0 = [mk("2026-04-01", 1, hs=6, as_=2), mk("2026-04-01", 2, home="Samsung Lions", away="Doosan Bears", hs=1, as_=4)]
    d1 = [mk("2026-04-02", 3, hs=3, as_=2), mk("2026-04-02", 4, hs=2, as_=7)]  # 같은 날 LG-HH 더블헤더
    d2 = [mk("2026-04-03", 5, hs=4, as_=4 - 1)]
    return d0 + d1 + d2


def _leak_boxes(games, scale=1):
    sp = {"LG": 101, "HH": 201, "SS": 301, "OB": 401}
    out = {}
    for g in games:
        k = scale if g["game_id"] >= 4 else 1  # 4번(D의 둘째 경기)·5번(D+1)만 바뀐다
        out[g["game_id"]] = mkbox(
            g,
            home_pitchers=[{"player_id": sp[g["home_code"]], "ip_outs": 18 * k, "er": 2 * k, "r": 3 * k, "so": 5 * k, "np": 90},
                           {"ip_outs": 9, "er": 1, "so": 2 * k, "bb": k, "np": 25 * k}],
            away_pitchers=[{"player_id": sp[g["away_code"]], "ip_outs": 15, "er": 4 * k, "r": 4 * k, "bb": 3, "np": 95},
                           {"ip_outs": 9, "er": 0, "so": 4, "np": 30 * k}],
            home_bat=[{"ab": 30 * k, "h": 9 * k, "bb": 2, "hr": k, "so": 6}],
            away_bat=[{"ab": 32, "h": 7 * k, "bb": 4 * k, "hbp": 1, "so": 9 * k}],
        )
    return out


def test_future_games_do_not_change_features():
    games = _leak_games()
    df_a = build_training_frame(games, _leak_boxes(games), season=2026)
    changed = [dict(g) for g in games]
    changed[3].update(home_score=12, away_score=0)  # D의 둘째 경기 결과를 뒤집는다
    changed[4].update(home_score=0, away_score=11)  # D+1 결과도 뒤집는다
    df_b = build_training_frame(changed, _leak_boxes(changed, scale=5), season=2026)
    rows_equal(df_a, df_b, 3)  # D의 첫 경기
    rows_equal(df_a, df_b, 4)  # D의 둘째 경기 자신의 결과·박스도 자기 피처에 안 들어간다
    # 변형이 실제로 반영됐는지 확인 (D+1 피처는 D 둘째 경기 결과를 보므로 달라야 한다)
    assert df_a.loc[df_a.game_id == 5, "win_pct_diff"].item() != df_b.loc[df_b.game_id == 5, "win_pct_diff"].item()
    assert df_a.y.tolist() != df_b.y.tolist()
    # 전날 박스스코어는 반영된다 (피처가 비어 있지 않음)
    assert not math.isnan(df_a.loc[df_a.game_id == 3, "obp_diff"].item())
    assert df_a.loc[df_a.game_id == 3, "starter_known"].item() == 1


def test_same_day_games_do_not_leak():
    games = _leak_games()
    df = build_training_frame(games, _leak_boxes(games), season=2026)
    # 더블헤더 1·2차전(같은 팀, 같은 날)은 피처가 같아야 한다: 1차전 결과·박스가 2차전에 안 들어감
    a = df.loc[df.game_id == 3, FEATURE_NAMES].reset_index(drop=True)
    b = df.loc[df.game_id == 4, FEATURE_NAMES].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    assert df.loc[df.game_id == 3, "season_progress"].item() == pytest.approx(1 / 144)


# ---------- 휴식·불펜·맞대결·장소 ----------

def test_rest_days_and_bullpen3():
    s = LeagueState()
    g1 = mk("2026-04-01", 1, hs=5, as_=2)
    s.update(g1, mkbox(g1, home_pitchers=[{"np": 100}, {"np": 20}, {"np": 15}], away_pitchers=[{"np": 90}, {"np": 10}]))
    g2 = mk("2026-04-03", 2, away="Samsung Lions", hs=1, as_=2)
    s.update(g2, mkbox(g2, home_pitchers=[{"np": 95}, {"np": None}, {"np": 30}]))
    lg = s.team_line("LG", "2026-04-05")
    assert lg["rest_days"] == 2 and lg["bullpen3"] == 30  # 창 04-02~04-04: 04-03의 구원 30구만
    assert s.team_line("LG", "2026-04-04")["bullpen3"] == 65  # 창 04-01~04-03: 35 + 30 (선발 투구수 제외)
    assert s.team_line("LG", "2026-04-03")["bullpen3"] == 35  # 당일 경기는 창 밖
    assert s.team_line("HH", "2026-04-05")["rest_days"] == 4 and s.team_line("HH", "2026-04-05")["bullpen3"] == 0
    f = game_features(mk("2026-04-05", 3), s)
    assert f["rest_diff"] == 2 - 4 and f["bullpen3_diff"] == 30 - 0
    f_nc = game_features(mk("2026-04-05", 4, away="NC Dinos"), s)
    assert math.isnan(f_nc["rest_diff"]) and f_nc["bullpen3_diff"] == 30


def test_h2h_and_venue_pct():
    s = LeagueState()
    s.update(mk("2026-04-01", 1, hs=5, as_=2))  # LG 홈 승
    s.update(mk("2026-04-02", 2, hs=1, as_=2))  # LG 홈 패
    s.update(mk("2026-04-03", 3, home="Hanwha Eagles", away="LG Twins", hs=0, as_=3))  # LG 원정 승
    s.update(mk("2026-04-04", 4, hs=4, as_=4))  # 무승부 (맞대결·장소 승률 분모에서 제외)
    assert s.h2h_home_pct("LG", "HH") == pytest.approx(2 / 3)
    assert s.h2h_home_pct("HH", "LG") == pytest.approx(1 / 3)
    assert s.h2h_home_pct("LG", "SS") is None
    lg, hh = s.team_line("LG", "2026-04-05"), s.team_line("HH", "2026-04-05")
    assert lg["home_pct"] == 0.5 and lg["away_pct"] == 1.0
    assert hh["home_pct"] == 0.0 and hh["away_pct"] == 0.5
    f = game_features(mk("2026-04-05", 5), s)
    assert f["home_venue_pct"] == 0.5 and f["away_venue_pct"] == 0.5 and f["h2h_home_pct"] == pytest.approx(2 / 3)
    assert f["season_progress"] == pytest.approx(4 / 144)
    f2 = game_features(mk("2026-04-05", 6, home="Samsung Lions"), s)
    assert math.isnan(f2["home_venue_pct"]) and math.isnan(f2["h2h_home_pct"])


# ---------- 시즌 연결 ----------

def test_prev_season_via_start_season():
    s = LeagueState()
    s.start_season(2015)
    s.update(mk("2015-04-01", 1, hs=5, as_=2), None)
    s.update(mk("2015-04-02", 2, hs=5, as_=2), None)
    s.update(mk("2015-04-03", 3, hs=1, as_=2), None)
    s.start_season(2016)
    lg = s.team_line("LG", "2016-04-01")
    assert lg["prev_win_pct"] == pytest.approx(2 / 3) and lg["games"] == 0 and lg["win_pct"] is None
    assert lg["rest_days"] is None and s.h2h_home_pct("LG", "HH") is None
    f = game_features(mk("2016-04-01", 10), s)
    assert f["prev_season_diff"] == pytest.approx(2 / 3 - 1 / 3) and f["season_progress"] == 0.0
    assert all(math.isnan(f[n]) for n in ("win_pct_diff", "last10_diff", "run_diff_diff"))  # 당해 0경기 → NaN
    s.start_season(2016)  # 같은 시즌으로 다시 불러도 아무 일 없음 (직전 시즌 기록 유지)
    assert s.team_line("LG", "2016-04-01")["prev_win_pct"] == pytest.approx(2 / 3)
    f_new = game_features(mk("2016-04-01", 11, away="NC Dinos"), s)  # 직전 시즌 기록 없는 팀
    assert math.isnan(f_new["prev_season_diff"])


# ---------- 선발 ----------

def test_starter_features_from_boxscore_order1():
    s = LeagueState()
    s.start_season(2015)
    g15 = mk("2015-05-01", 1, hs=3, as_=2)
    box15 = mkbox(
        g15,
        # 목록 첫 줄이 아니라 order==1 줄이 선발이다
        home_pitchers=[{"order": 2, "player_id": 102, "ip_outs": 3, "er": 0},
                       {"order": 1, "player_id": 101, "ip_outs": 300, "er": 40, "r": 40, "so": 100, "bb": 30}],
        away_pitchers=[{"order": 1, "player_id": 201, "ip_outs": 270, "er": 30, "r": 30, "so": 60, "bb": 10}],
    )
    assert starter_ids(box15) == {"home": {"player_id": 101, "name": "P1"}, "away": {"player_id": 201, "name": "P0"}}
    s.update(g15, box15)
    s.start_season(2016)
    g16 = mk("2016-04-05", 2, hs=1, as_=5)
    s.update(g16, mkbox(
        g16,
        home_pitchers=[{"order": 1, "player_id": 101, "ip_outs": 30, "er": 10, "r": 12, "so": 8, "bb": 3, "hr": 2}],
        away_pitchers=[{"order": 1, "player_id": 201, "ip_outs": 27, "er": 3, "r": 3, "so": 6, "bb": 1}],
    ))
    p = s.pitcher_line(101)
    assert p["era"] == pytest.approx(50 * 27 / 330)
    assert p["ip"] == pytest.approx(110.0)
    assert p["k9"] == pytest.approx(108 * 27 / 330) and p["bb9"] == pytest.approx(33 * 27 / 330)
    assert p["fip"] == pytest.approx((13 * 2 + 3 * 33 - 2 * 108) * 3 / 330)
    assert p["last3_runs"] == pytest.approx((40 + 12) / 2)
    assert p["season"] == {"era": pytest.approx(9.0), "k9": pytest.approx(7.2), "bb9": pytest.approx(2.7),
                           "ip": pytest.approx(10.0), "starts": 1}
    assert s.pitcher_line(102)["last3_runs"] is None  # 구원 등판만 있으면 선발 실점 없음
    q = s.pitcher_line(201)
    f = game_features(mk("2016-04-06", 3), s, {"home": {"player_id": 101, "name": "A"}, "away": {"player_id": 201, "name": "B"}})
    assert f["starter_known"] == 1
    assert f["starter_era_diff"] == pytest.approx(p["era"] - q["era"])
    assert f["starter_fip_diff"] == pytest.approx(p["fip"] - q["fip"])
    assert f["starter_k9_diff"] == pytest.approx(p["k9"] - q["k9"])
    assert f["starter_bb9_diff"] == pytest.approx(p["bb9"] - q["bb9"])
    assert f["starter_ip_diff"] == pytest.approx(110.0 - 99.0)
    assert f["starter_last3_runs_diff"] == pytest.approx(26.0 - 16.5)
    assert f["home_starter"] == p and f["away_starter"] == q


def test_last3_starts_only_cover_previous_and_current_season():
    """최근 3선발 실점은 직전 시즌 + 당해 시즌 선발만 센다 (R8: 라이브 build_state와 같은 창).
    투수 101: 2015 선발 3번 → 2016 구원 1번. 투수 201: 2015 선발 3번 → 2016 선발 1번(실점 7)."""
    s = LeagueState()
    s.start_season(2015)
    for i, runs in enumerate((2, 4, 6)):
        g = mk(f"2015-05-0{i + 1}", 100 + i, hs=3, as_=2)
        s.update(g, mkbox(g, home_pitchers=[{"order": 1, "player_id": 101, "ip_outs": 18, "r": runs}],
                          away_pitchers=[{"order": 1, "player_id": 201, "ip_outs": 18, "r": runs + 1}]))
    s.start_season(2016)
    # 2016 시즌 중에는 2015(직전 시즌) 선발이 아직 센다
    assert s.pitcher_line(101)["last3_runs"] == pytest.approx(4.0)
    g = mk("2016-05-01", 200, hs=1, as_=7)
    s.update(g, mkbox(g, home_pitchers=[{"order": 1, "player_id": 999, "ip_outs": 18},
                                        {"order": 2, "player_id": 101, "ip_outs": 3, "r": 9}],
                      away_pitchers=[{"order": 1, "player_id": 201, "ip_outs": 18, "r": 7}]))
    assert s.pitcher_line(201)["last3_runs"] == pytest.approx((5 + 7 + 7) / 3)  # 2015의 3, 5, 7 중 뒤 둘 + 2016의 7
    s.start_season(2017)
    p101 = s.pitcher_line(101)
    assert p101 is not None and p101["last3_runs"] is None  # 2016은 구원뿐, 2015 선발은 창 밖
    assert s.pitcher_line(201)["last3_runs"] == pytest.approx(7.0)  # 2016 선발 하나만
    s.start_season(2017)  # 같은 시즌 재호출은 아무것도 버리지 않음
    assert s.pitcher_line(201)["last3_runs"] == pytest.approx(7.0)


def test_starter_unknown_sets_flag_zero_and_nan():
    s = LeagueState()
    g = mk("2026-04-01", 1, hs=3, as_=2)
    s.update(g, mkbox(g, home_pitchers=[{"player_id": 101, "ip_outs": 18, "er": 2}]))
    assert starter_ids(None) == {"home": None, "away": None}
    assert s.pitcher_line(999) is None
    nxt = mk("2026-04-02", 2)
    for starters in (None, {"home": None, "away": None},
                     {"home": {"player_id": 101, "name": "A"}, "away": {"player_id": 999, "name": "신인"}}):
        f = game_features(nxt, s, starters)
        assert f["starter_known"] == 0
        assert all(math.isnan(f[n]) for n in STARTER_FEATURES if n != "starter_known")
    assert f["home_starter"] == s.pitcher_line(101) and f["away_starter"] is None


# ---------- 학습 프레임 ----------

def test_training_frame_excludes_draws_and_non_regular():
    games = [
        mk("2026-03-21", 1, hs=5, as_=1),  # 시범경기
        mk("2026-04-01", 2, hs=2, as_=2),  # 무승부
        mk("2026-04-02", 3, hs=3, as_=1),
        mk("2026-04-03", 4, status="CANCELED"),
        mk("2026-04-04", 5, hs=0, as_=1),
        mk("2026-10-20", 6, hs=1, as_=0),  # 포스트시즌
    ]
    df = build_training_frame(games, {}, season=2026)
    assert df.game_id.tolist() == [3, 5] and df.y.tolist() == [1, 0]
    assert list(df.columns) == ["game_id", "date", "season", "home_code", "away_code", *FEATURE_NAMES, "y"]
    # 무승부(2번)는 행은 없지만 상태에는 들어가고, 시범경기(1번)는 상태에도 안 들어간다
    assert df.loc[df.game_id == 3, "season_progress"].item() == pytest.approx(1 / 144)
    assert df.loc[df.game_id == 5, "win_pct_diff"].item() == pytest.approx(1.0)
    assert df.season.tolist() == [2026, 2026] and df.home_code.tolist() == ["LG", "LG"]


def test_regular_finals_filters_and_orders():
    """정규시즌 FINAL만, (date, game_id) 순. 무승부·점수 없는 FINAL은 남긴다 (상태 갱신 쪽에서 처리)."""
    games = [
        mk("2026-04-02", 7, hs=3, as_=1),
        mk("2026-03-21", 1, hs=5, as_=1),       # 시범경기
        mk("2026-04-02", 3, hs=1, as_=1),       # 같은 날 → game_id 순, 무승부도 남김
        mk("2026-04-01", 9, hs=2, as_=0),
        mk("2026-04-03", 4, status="CANCELED"),
        mk("2026-04-04", 5, status="SCHEDULED"),
        mk("2026-10-20", 6, hs=1, as_=0),       # 포스트시즌
    ]
    assert [g["game_id"] for g in regular_finals(games, 2026)] == [9, 3, 7]
    assert regular_finals([], 2026) == []


def test_training_frame_uses_regular_finals(monkeypatch):
    """build_training_frame과 라이브 build_state가 같은 필터(features.regular_finals)를 쓴다."""
    import kbo_predict.features as F

    calls = []
    real = F.regular_finals
    monkeypatch.setattr(F, "regular_finals", lambda games, season: calls.append(season) or real(games, season))
    df = build_training_frame([mk("2026-04-02", 2, hs=1, as_=0), mk("2026-03-21", 1, hs=5, as_=1)], {}, season=2026)
    assert calls == [2026] and df.game_id.tolist() == [2]


def test_training_frame_continues_given_state():
    s = LeagueState()
    s.update(mk("2026-04-01", 1, hs=5, as_=2))
    df = build_training_frame([mk("2026-04-02", 2, hs=1, as_=0)], {}, season=2026, state=s)
    assert df.win_pct_diff.tolist() == [pytest.approx(1.0)]
    assert s.team_line("LG", "2026-04-03")["games"] == 2  # 넘겨준 상태가 이어서 누적됨


# ---------- 시즌 연결 데이터셋 + parquet ----------

@pytest.fixture
def two_season_data(tmp_data_dir):
    """합성 2시즌을 임시 data 폴더에 저장. 2015: LG 2승 1패(승률 2/3), HH 1승 2패."""
    from kbo_predict import raw_store

    raw_store.upsert_games(2015, [
        mk("2015-04-10", 1, hs=5, as_=2), mk("2015-04-11", 2, hs=5, as_=2), mk("2015-04-12", 3, hs=1, as_=2),
    ])
    raw_store.upsert_games(2016, [mk("2016-04-10", 11, hs=3, as_=1), mk("2016-04-09", 10, hs=0, as_=4)])
    return tmp_data_dir


def test_build_dataset_links_seasons(two_season_data):
    from kbo_predict.features import build_dataset

    df = build_dataset([2016, 2015])  # 순서를 섞어 줘도 시즌 오름차순
    assert df.season.tolist() == [2015, 2015, 2015, 2016, 2016]
    assert df.game_id.tolist() == [1, 2, 3, 10, 11]  # 시즌 안에서는 (date, game_id)
    assert df.index.tolist() == list(range(5))
    assert df.columns.tolist() == ["game_id", "date", "season", "home_code", "away_code", *FEATURE_NAMES, "y"]
    first_2016 = df[df.season == 2016].iloc[0]
    assert first_2016.prev_season_diff == pytest.approx(2 / 3 - 1 / 3)  # 2015 최종 승률 차
    assert math.isnan(first_2016.win_pct_diff)  # 당해 0경기


def test_features_parquet_roundtrip_and_sha(two_season_data, tmp_path):
    from kbo_predict.features import build_dataset, features_sha256, load_features, save_features

    df = build_dataset([2015, 2016])
    a, b = tmp_path / "a.parquet", tmp_path / "sub" / "b.parquet"
    save_features(df, a)
    save_features(df, b)  # 없는 폴더도 만든다
    pd.testing.assert_frame_equal(load_features(a), df)
    assert features_sha256(a) == features_sha256(b) and len(features_sha256(a)) == 64
    save_features(df.assign(y=1 - df.y), b)
    assert features_sha256(a) != features_sha256(b)


# ---------- 상성(직전 시즌 유형) 피처 ----------

def _matchup_game(date, gid, hs, as_, home_bat, away_bat, home_sp=10, away_sp=20):
    """LG(홈) vs HH(원정) 한 경기 + 박스스코어. 타자 dict 목록과 양 팀 선발 player_id를 받는다."""
    g = mk(date, gid, hs=hs, as_=as_)
    return g, mkbox(g, home_pitchers=[{"player_id": home_sp, "ip_outs": 27}],
                    away_pitchers=[{"player_id": away_sp, "ip_outs": 24}],
                    home_bat=home_bat, away_bat=away_bat)


@pytest.fixture
def two_season_games():
    """합성 2시즌. 타자 1 = LG, 타자 2 = HH (각 4타수 + 볼넷 1 = 5타석), LG 선발 10, HH 선발 20.
    2025: 2경기, 2026: 3경기 (4/1 개막일, 4/2, 4/3)."""
    bat_h, bat_a = [{"player_id": 1, "ab": 4, "bb": 1}], [{"player_id": 2, "ab": 4, "bb": 1}]
    games, boxes = {2025: [], 2026: []}, {2025: {}, 2026: {}}
    for date, gid, hs, as_ in (("2025-04-10", 1, 5, 2), ("2025-04-11", 2, 1, 3),
                               ("2026-04-01", 11, 4, 2), ("2026-04-02", 12, 2, 6), ("2026-04-03", 13, 3, 1)):
        g, b = _matchup_game(date, gid, hs, as_, bat_h, bat_a)
        games[g["season"]].append(g)
        boxes[g["season"]][gid] = b
    return games, boxes


def build_dataset_from(data, *, types=None, kb=0, kp=0):
    """테스트용 시즌 연결: build_dataset과 같은 순서(시즌마다 start_season → build_training_frame)."""
    games, boxes = data
    state = LeagueState(types=types, kb=kb, kp=kp)
    frames = []
    for season in sorted(games):
        state.start_season(season)
        frames.append(build_training_frame(games[season], boxes[season], season=season, state=state))
    return pd.concat(frames, ignore_index=True)


# (2025, 1) = 타자 유형 1, (2026, 1) = 타자 유형 0 (당해 시즌 유형 — 쓰면 누수), (2025, 2) = 타자 유형 0,
# (2025, 10) = 투수 유형 2. HH 선발 20은 유형 없음.
MATCHUP_TYPES = {(2025, 1): {"batter": 1}, (2026, 1): {"batter": 0}, (2025, 2): {"batter": 0},
                 (2025, 10): {"pitcher": 2}}


def test_matchup_feature_names_order():
    assert matchup_feature_names(2, 3) == ["bat_type0_diff", "bat_type1_diff", "starter_type0_diff",
                                           "starter_type1_diff", "starter_type2_diff", "types_known"]
    assert matchup_feature_names(0, 0) == ["types_known"]


def test_matchup_uses_previous_season_types_only(two_season_games):
    """2026 경기에서 타자 1의 타석은 2025 유형(1)으로 센다 — 2026 유형(0)을 쓰면 홈·원정 모두 유형 0이라 차이가 0."""
    df = build_dataset_from(two_season_games, types=MATCHUP_TYPES, kb=2, kp=3)
    row = df[df.season == 2026].iloc[-1]
    assert row["bat_type1_diff"] > 0 and row["starter_type2_diff"] != 0
    assert row["bat_type1_diff"] == pytest.approx(1.0) and row["bat_type0_diff"] == pytest.approx(-1.0)
    assert row["starter_type2_diff"] == 1 and row["starter_type0_diff"] == 0 and row["starter_type1_diff"] == 0
    assert row["types_known"] == 0  # 원정 선발(20)에 유형이 없다
    # 2025 경기는 2024 유형을 찾는다 → 유형표에 없으므로 타선 NaN, 선발 0 벡터
    r25 = df[df.season == 2025].iloc[-1]
    assert math.isnan(r25["bat_type0_diff"]) and r25["starter_type2_diff"] == 0 and r25["types_known"] == 0


def test_matchup_opening_day_is_nan(two_season_games):
    """개막일에는 당해 시즌 타석이 없다 (직전 시즌 타석은 start_season에서 비워진다) → 타선 비중 NaN."""
    df = build_dataset_from(two_season_games, types=MATCHUP_TYPES, kb=2, kp=3)
    first = df[df.season == 2026].iloc[0]
    assert np.isnan(first["bat_type0_diff"]) and np.isnan(first["bat_type1_diff"]) and first["types_known"] == 0
    assert first["starter_type2_diff"] == 1  # 선발 유형은 개막일에도 안다


def test_matchup_types_known_requires_both_lineups_and_starters(two_season_games):
    types = {**MATCHUP_TYPES, (2025, 20): {"pitcher": 0}}
    df = build_dataset_from(two_season_games, types=types, kb=2, kp=3)
    last = df[df.season == 2026].iloc[-1]
    assert last["types_known"] == 1
    assert last["starter_type2_diff"] == 1 and last["starter_type0_diff"] == -1


def test_lineup_shares_weights_by_pa_and_known_share():
    """유형별 비중은 유형 있는 타석 기준(합 1), 두 번째 값은 팀 전체 타석 중 유형 있는 타석 비율."""
    s = LeagueState(types={(2025, 1): {"batter": 0}, (2025, 2): {"batter": 1}}, kb=2, kp=1)
    s.start_season(2026)
    assert s.lineup_shares("LG") == (None, 0.0)
    g = mk("2026-04-01", 1, hs=3, as_=2)
    s.update(g, mkbox(g, home_bat=[{"player_id": 1, "ab": 3}, {"player_id": 2, "ab": 1, "hbp": 1},
                                   {"player_id": 3, "ab": 4}, {"player_id": None, "ab": 9}]))
    shares, known = s.lineup_shares("LG")
    assert shares == pytest.approx([0.6, 0.4]) and known == pytest.approx(5 / 9)  # player_id 없는 줄은 안 센다
    assert s.lineup_shares("HH") == (None, 0.0)  # 타자 기록 없음
    assert starter_type(s, 99) is None and starter_type(s, None) is None
    s.start_season(2027)  # 새 시즌: 당해 타석이 비워지고 2026 유형을 찾는다
    assert s.lineup_shares("LG") == (None, 0.0)


def test_matchup_columns_absent_without_types(two_season_games):
    """유형표 없이(라이브 기본값) 만들면 기존 26개 피처 열 그대로, game_features에도 상성 키가 없다.
    유형표를 줘도 기본 26개 피처 값은 바뀌지 않는다."""
    plain = build_dataset_from(two_season_games)
    assert list(plain.columns) == ["game_id", "date", "season", "home_code", "away_code", *FEATURE_NAMES, "y"]
    typed = build_dataset_from(two_season_games, types=MATCHUP_TYPES, kb=2, kp=3)
    assert list(typed.columns) == ["game_id", "date", "season", "home_code", "away_code", *FEATURE_NAMES,
                                   *matchup_feature_names(2, 3), "y"]
    pd.testing.assert_frame_equal(typed[plain.columns], plain)
    f = game_features(mk("2026-04-05", 99), LeagueState())
    assert not set(matchup_feature_names(4, 4)) & set(f)


@pytest.fixture
def stored_two_seasons(tmp_data_dir, two_season_games):
    from kbo_predict import raw_store

    games, boxes = two_season_games
    for season in games:
        raw_store.upsert_games(season, games[season])
        raw_store.append_boxscores(season, boxes[season])
    return two_season_games


def test_build_dataset_with_types(stored_two_seasons):
    from kbo_predict.features import build_dataset

    df = build_dataset([2025, 2026], types=MATCHUP_TYPES, kb=2, kp=3)
    pd.testing.assert_frame_equal(df, build_dataset_from(stored_two_seasons, types=MATCHUP_TYPES, kb=2, kp=3))
    assert "types_known" not in build_dataset([2025, 2026]).columns


def _fake_clusters():
    """cluster.types_map이 읽는 모양의 최소 군집 묶음 (MATCHUP_TYPES와 같은 유형, K_b=2, K_p=3)."""
    bat = pd.DataFrame({"season": [2025, 2026, 2025], "player_id": [1, 1, 2], "type": [1, 0, 0]})
    pit = pd.DataFrame({"season": [2025], "player_id": [10], "type": [2]})
    return {"batter": {"bundle": {"k": 2}, "assigned": bat}, "pitcher": {"bundle": {"k": 3}, "assigned": pit}}


def test_cli_matchup_out_keeps_features_parquet_identical(stored_two_seasons, tmp_path, monkeypatch):
    """--matchup-out은 game_id + 상성 열만 저장하고, 같이 쓰는 --out은 유형 없이 만든 parquet와 바이트까지 같다."""
    from kbo_predict import cluster
    from kbo_predict.features import features_sha256, load_features, main

    monkeypatch.setattr(cluster, "load_bundle", lambda path: _fake_clusters())
    plain, both, mu = tmp_path / "plain.parquet", tmp_path / "both.parquet", tmp_path / "matchup.parquet"
    main(["--out", str(plain)])
    main(["--out", str(both), "--matchup-out", str(mu), "--clusters", "fake.pkl"])
    assert features_sha256(plain) == features_sha256(both)
    m = load_features(mu)
    assert list(m.columns) == ["game_id", *matchup_feature_names(2, 3)]
    want = build_dataset_from(stored_two_seasons, types=MATCHUP_TYPES, kb=2, kp=3)
    pd.testing.assert_frame_equal(m, want[["game_id", *matchup_feature_names(2, 3)]])
    with pytest.raises(SystemExit):
        main([])  # --out도 --matchup-out도 없으면 거부
