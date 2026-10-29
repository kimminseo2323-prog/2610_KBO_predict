"""predict_game 테스트: 출력 모양(기존 키 유지 + 선발 블록 + starter_known), 요인 상위 5(pp 환산),
요인 분해 항등식(explain 직접 호출)과 부호 일관성, 빈 상태(개막일)에서도 죽지 않음(R4)."""
import math

import numpy as np
import pandas as pd
import pytest

from kbo_predict.features import FACTOR_LABELS, FEATURE_NAMES, LeagueState, game_features
from kbo_predict.mykbo_parse import parse_week
from kbo_predict.predict import factor_pp, predict_game
from kbo_predict.train_win import explain, predict_proba, predict_raw

HOME_SP, AWAY_SP = 2730, 1096  # 14050 예고 선발: 홈 Shirakawa Keisho, 원정 Choi Won-tae
STARTERS = {"game_id": 14050, "date": "2026-10-29", "fetched_at": "2026-10-29T09:00:00+09:00",
            "home": {"player_id": HOME_SP, "name": "Shirakawa Keisho"},
            "away": {"player_id": AWAY_SP, "name": "Choi Won-tae"}}
ENTRY_KEYS = {"game_id", "date", "time", "stadium", "round", "status", "home", "away", "home_win_prob", "factors",
              "starter_known"}
SIDE_KEYS = {"code", "name", "starter", "win_pct_season", "last10", "run_diff"}
STARTER_KEYS = {"player_id", "name", "era", "k9", "bb9", "ip", "starts"}


def _game(fixture_html):
    return next(r for r in parse_week(fixture_html("mykbo_week_2026-10-27.html")) if r["game_id"] == 14050)


def _pitch(pid, er):
    """선발(order 1) 6이닝 + 구원(order 2) 3이닝."""
    return [{"player_id": pid, "name": f"P{pid}", "order": 1, "ip_outs": 18, "er": er, "r": er, "hr": 0,
             "bb": 2, "hbp": 0, "so": 6, "np": 95},
            {"player_id": pid + 100000, "name": "RP", "order": 2, "ip_outs": 9, "er": 0, "r": 0, "hr": 0,
             "bb": 1, "hbp": 0, "so": 3, "np": 40}]


def _played_state() -> LeagueState:
    """HT 2승 1패, SS 1승 2패인 상태. 두 예고 선발 모두 선발 기록이 있다 (HT 선발이 더 잘 던짐)."""
    st = LeagueState()
    st.start_season(2026)
    bat = [{"ab": 34, "h": 9, "bb": 3, "hbp": 0, "hr": 1, "so": 7}]
    games = [(1, "2026-09-01", "HT", "SS", 7, 2, HOME_SP, AWAY_SP, 1, 5),
             (2, "2026-09-02", "SS", "HT", 6, 3, AWAY_SP + 1, HOME_SP + 1, 2, 4),
             (3, "2026-09-03", "HT", "SS", 5, 4, HOME_SP + 2, AWAY_SP + 2, 3, 4)]
    for gid, d, home, away, hs, as_, hp, ap, her, aer in games:
        g = {"game_id": gid, "date": d, "season": 2026, "home_code": home, "away_code": away,
             "home_score": hs, "away_score": as_, "status": "FINAL"}
        box = {"game_id": gid, "date": d, "batting": {"home": bat, "away": bat},
               "pitching": {"home": _pitch(hp, her), "away": _pitch(ap, aer)}}
        st.update(g, box)
    return st


def _x(game, state, starters=None) -> pd.DataFrame:
    f = game_features(game, state, starters)
    return pd.DataFrame([[f[n] for n in FEATURE_NAMES]], columns=FEATURE_NAMES)


def test_predict_game_shape_keeps_contract(bundle, fixture_html):
    out = predict_game(bundle, _game(fixture_html), _played_state(), STARTERS)
    assert set(out) == ENTRY_KEYS
    assert set(out["home"]) == SIDE_KEYS and set(out["away"]) == SIDE_KEYS
    assert 0 < out["home_win_prob"] < 1 and out["time"] == "18:30" and out["stadium"] == "Gwangju"
    assert out["home"]["code"] == "HT" and out["home"]["name"] == "KIA" and out["away"]["code"] == "SS"
    assert out["round"] == "postseason" and out["status"] == "SCHEDULED"
    assert out["home"]["win_pct_season"] == 0.667 and out["away"]["win_pct_season"] == 0.333


def test_home_win_prob_is_calibrated(bundle, fixture_html):
    game, state = _game(fixture_html), _played_state()
    out = predict_game(bundle, game, state, STARTERS)
    X = _x(game, state, STARTERS)
    assert out["home_win_prob"] == round(float(predict_proba(bundle, X)[0]), 4)
    assert out["home_win_prob"] != round(float(predict_raw(bundle, X)[0]), 4)  # platt가 실제로 적용됨


def test_starter_block_from_season_stats(bundle, fixture_html):
    state = _played_state()
    out = predict_game(bundle, _game(fixture_html), state, STARTERS)
    assert out["starter_known"] is True
    hs, as_ = out["home"]["starter"], out["away"]["starter"]
    assert set(hs) == STARTER_KEYS and set(as_) == STARTER_KEYS
    assert hs["player_id"] == HOME_SP and hs["name"] == "Shirakawa Keisho"
    assert as_["player_id"] == AWAY_SP and as_["name"] == "Choi Won-tae"
    season = state.pitcher_line(HOME_SP)["season"]  # 1선발 6이닝 1자책
    assert hs["era"] == round(season["era"], 2) == 1.5 and hs["ip"] == 6.0 and hs["starts"] == 1
    assert hs["k9"] == 9.0 and hs["bb9"] == 3.0
    assert as_["era"] == 7.5


def test_no_starters_means_starter_known_false(bundle, fixture_html):
    out = predict_game(bundle, _game(fixture_html), _played_state())
    assert out["starter_known"] is False
    assert out["home"]["starter"] is None and out["away"]["starter"] is None
    tba = {**STARTERS, "home": None}  # 원정만 예고
    out = predict_game(bundle, _game(fixture_html), _played_state(), tba)
    assert out["starter_known"] is False and out["home"]["starter"] is None
    assert out["away"]["starter"]["name"] == "Choi Won-tae"


def test_announced_starter_without_record_has_none_stats(bundle, fixture_html):
    rookie = {**STARTERS, "home": {"player_id": 999999, "name": "Rookie"}}
    out = predict_game(bundle, _game(fixture_html), _played_state(), rookie)
    assert out["starter_known"] is False
    assert out["home"]["starter"] == {"player_id": 999999, "name": "Rookie", "era": None, "k9": None,
                                      "bb9": None, "ip": None, "starts": None}


def test_empty_state_does_not_crash_and_emits_none(bundle, fixture_html):
    """R4: 개막일처럼 승패 난 경기가 없는 팀 → 팀 요약 값은 None (round(None)으로 죽지 않음)."""
    out = predict_game(bundle, _game(fixture_html), LeagueState(), STARTERS)
    for side in ("home", "away"):
        assert out[side]["win_pct_season"] is None and out[side]["last10"] is None and out[side]["run_diff"] is None
        assert out[side]["starter"]["era"] is None
    assert 0 < out["home_win_prob"] < 1 and out["starter_known"] is False


def _platt_a(bundle):
    """platt 번들이면 캘리브레이터 기울기 a, 아니면 1 (isotonic·none은 기울기 보정 없음)."""
    return float(bundle["calibrator"].coef_[0][0]) if bundle["calibration"] == "platt" else 1.0


def _all_pp(bundle, X, p):
    """요인 27개(피처 26 + bias)의 pp를 반올림 없이 계산: 기여 × a × p(1−p) × 100."""
    contrib, base = explain(bundle, X)
    names = [FACTOR_LABELS[n] for n in bundle["features"]] + [FACTOR_LABELS["bias"]]
    vals = list(contrib[0]) + [base[0]]
    return {n: v * _platt_a(bundle) * p * (1 - p) * 100 for n, v in zip(names, vals)}


def test_factor_pp_applies_platt_slope_exactly(bundle, fixture_html):
    """platt 번들: 27개 pp 합(상위 5 자르기 전) == a · logit(p_raw) · p(1−p) · 100 (1차 근사의 기울기까지 반영)."""
    assert bundle["calibration"] == "platt"
    a = float(bundle["calibrator"].coef_[0][0])
    assert abs(a - 1) > 1e-3  # 기울기가 1이면 보정 여부를 구분할 수 없다
    game = _game(fixture_html)
    for st, starters in ((_played_state(), STARTERS), (LeagueState(), None)):
        X = _x(game, st, starters)
        p = float(predict_proba(bundle, X)[0])
        p_raw = float(predict_raw(bundle, X)[0])
        items = factor_pp(bundle, X, p)
        assert len(items) == len(FEATURE_NAMES) + 1
        want = a * math.log(p_raw / (1 - p_raw)) * p * (1 - p) * 100
        assert abs(sum(v for _, v in items) - want) < 1e-6
    # isotonic·none은 기울기 보정 없이 기여 × p(1−p) × 100 그대로
    X = _x(game, _played_state(), STARTERS)
    contrib, base = explain(bundle, X)
    for cal in ("none", "isotonic"):
        items = factor_pp({**bundle, "calibration": cal}, X, 0.4)
        assert items[0][1] == pytest.approx(float(contrib[0][0]) * 0.4 * 0.6 * 100, abs=1e-12)
        assert items[-1][1] == pytest.approx(float(base[0]) * 0.4 * 0.6 * 100, abs=1e-12)


def test_factors_top5_by_abs_pp(bundle, fixture_html):
    game, state = _game(fixture_html), _played_state()
    out = predict_game(bundle, game, state, STARTERS)
    factors = out["factors"]
    assert len(factors) == 5 and all(set(f) == {"name", "contribution_pp"} for f in factors)
    assert factors == sorted(factors, key=lambda f: -abs(f["contribution_pp"]))
    X = _x(game, state, STARTERS)
    pp = _all_pp(bundle, X, float(predict_proba(bundle, X)[0]))
    top = sorted(pp.items(), key=lambda kv: -abs(kv[1]))[:5]
    assert [f["name"] for f in factors] == [n for n, _ in top]
    for f, (_, v) in zip(factors, top):
        assert f["contribution_pp"] == round(v, 1)
        assert math.copysign(1, f["contribution_pp"]) > 0 or f["contribution_pp"] < 0  # -0.0은 내보내지 않는다
    assert set(f["name"] for f in factors) <= set(FACTOR_LABELS.values())


def test_explain_identity_and_sign_consistency(bundle, fixture_html):
    """요인 분해 항등식: Σ기여 + base == logit(predict_raw) (캘리브레이션 전).
    부호: 캘리브레이션을 끈 번들에서는 27개 pp 합의 부호 == home_win_prob − 0.5의 부호,
    그리고 출력된 각 요인의 부호 == 그 요인의 로짓 기여 부호."""
    game, state = _game(fixture_html), _played_state()
    X = _x(game, state, STARTERS)
    contrib, base = explain(bundle, X)
    p_raw = float(predict_raw(bundle, X)[0])
    assert abs(contrib.sum() + base[0] - math.log(p_raw / (1 - p_raw))) < 1e-6

    raw_bundle = {**bundle, "calibration": "none", "calibrator": None}
    for st, starters in ((state, STARTERS), (LeagueState(), None)):
        out = predict_game(raw_bundle, game, st, starters)
        Xs = _x(game, st, starters)
        pp = _all_pp(raw_bundle, Xs, out["home_win_prob"])
        assert np.sign(sum(pp.values())) == np.sign(out["home_win_prob"] - 0.5)
        for f in out["factors"]:
            if f["contribution_pp"] != 0:
                assert np.sign(f["contribution_pp"]) == np.sign(pp[f["name"]])
