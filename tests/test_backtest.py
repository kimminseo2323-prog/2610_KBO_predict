"""backtest.py: 여러 시즌 시험의 규칙 — 시즌마다 그 앞 시즌들로만 학습하고, Elo는 그 경기 결과를 보지 않으며,
후보 선택은 개발 시즌(2018~2025) log loss로만 한다."""
import json

import numpy as np
import pandas as pd
import pytest

from kbo_predict import backtest
from kbo_predict.features import FEATURE_NAMES

TEAMS = ["OB", "LT", "KT", "WO", "SK", "SS", "HH", "HT", "LG", "NC"]


def _games(seasons=range(2015, 2027), n=40, seed=0):
    """시즌마다 n경기, 날짜·팀 코드·피처(승패와 약하게 상관)를 가진 가짜 경기 표."""
    rng = np.random.default_rng(seed)
    rows, gid = [], 0
    for s in seasons:
        for k in range(n):
            h, a = rng.choice(TEAMS, size=2, replace=False)
            x = rng.normal(size=len(FEATURE_NAMES))
            y = int(rng.random() < 1 / (1 + np.exp(-(0.1 + 0.7 * x[0]))))
            gid += 1
            rows.append({"game_id": gid, "date": f"{s}-05-{1 + k % 28:02d}", "season": s, "home_code": h, "away_code": a,
                         **dict(zip(FEATURE_NAMES, x)), "y": y})
    return pd.DataFrame(rows)


def test_elo_is_pre_game_and_ignores_own_result():
    df = _games(n=30)
    base = backtest.elo_feature(df)
    flipped = df.copy()
    i = flipped.index[200]
    flipped.loc[i, "y"] = 1 - flipped.loc[i, "y"]
    after = backtest.elo_feature(flipped)
    order = df.sort_values(["date", "game_id"]).index
    pos = list(order).index(i)
    # 그 경기와 그 앞 경기의 Elo 차이는 그대로, 뒤 경기만 바뀔 수 있다
    assert np.allclose(base.loc[order[: pos + 1]], after.loc[order[: pos + 1]])
    assert not np.allclose(base.loc[order[pos + 1:]], after.loc[order[pos + 1:]])
    # 첫 경기: 두 팀 모두 1500 → 차이 = 홈 이점
    assert base.loc[order[0]] == pytest.approx(backtest.ELO_HOME)


def test_predictions_train_only_on_earlier_seasons(monkeypatch):
    seen = []
    real = backtest._fit_predict

    def spy(cand, train, test, cols):
        seen.append((int(train["season"].max()), int(test["season"].min()), int(test["season"].max())))
        return real(cand, train, test, cols)

    monkeypatch.setattr(backtest, "_fit_predict", spy)
    small = {"current": backtest.CANDIDATES["current"], "l1_elo": backtest.CANDIDATES["l1_elo"]}
    pred = backtest.predictions(_games(n=30), seasons=[2018, 2026], candidates=small, log=lambda *a: None)
    assert seen and all(tmax < s0 and s0 == s1 for tmax, s0, s1 in seen)
    assert set(pred["season"]) == {2018, 2026} and {"current", "l1_elo", "rule_lower_starter_era"} <= set(pred.columns)
    assert pred[["current", "l1_elo"]].apply(lambda c: c.between(0, 1).all()).all()


def test_paired_t_p():
    rng = np.random.default_rng(1)
    a = rng.normal(size=5000)
    assert backtest.paired_t_p(a, a) == 1.0
    assert backtest.paired_t_p(a + 0.2, a + rng.normal(scale=0.01, size=5000)) < 1e-6
    assert 0.0 <= backtest.paired_t_p(a, rng.normal(size=5000)) <= 1.0


def test_run_report_shape_and_selection_rule(monkeypatch):
    monkeypatch.setattr(backtest, "CANDIDATES", {k: backtest.CANDIDATES[k] for k in ("current", "l1", "l1_elo")})
    rep = backtest.run(_games(n=40), log=lambda *a: None)
    dev = rep["pooled"]["dev"]
    assert rep["chosen"] == min(rep["candidates"], key=lambda n: dev[n]["log_loss"])  # 개발 시즌으로만 고른다
    assert rep["pooled"]["test"]["seasons"] == [2026] and rep["pooled"]["all"]["n"] == sum(v["n"] for v in rep["by_season"].values())
    assert "mcnemar_p_vs_current" in rep["pooled"]["all"]["tests"]["l1"] and "mcnemar_p_vs_current" not in rep["pooled"]["all"]["tests"]["current"]
    json.dumps(rep, default=str)
