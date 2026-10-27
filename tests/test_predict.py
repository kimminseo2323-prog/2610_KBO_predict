from kbo_predict.features import FACTOR_LABELS, LeagueState
from kbo_predict.mykbo_parse import parse_week
from kbo_predict.predict import predict_game


def _game(fixture_html):
    return next(r for r in parse_week(fixture_html("mykbo_week_2026-10-27.html")) if r["game_id"] == 14050)


def test_predict_game_shape(bundle, fixture_html):
    out = predict_game(bundle, _game(fixture_html), LeagueState())
    assert 0 < out["home_win_prob"] < 1 and out["time"] == "18:30" and out["home"]["code"] == "HT" and out["home"]["name"] == "KIA"
    assert out["round"] == "postseason" and out["home"]["starter"] is None
    assert {f["name"] for f in out["factors"]} == set(FACTOR_LABELS.values())
    assert out["factors"] == sorted(out["factors"], key=lambda f: -abs(f["contribution_pp"]))


def test_predict_game_empty_state_only_home_advantage(bundle, fixture_html):
    out = predict_game(bundle, _game(fixture_html), LeagueState())
    assert all(f["contribution_pp"] == 0.0 for f in out["factors"] if f["name"] != "홈 어드밴티지")
