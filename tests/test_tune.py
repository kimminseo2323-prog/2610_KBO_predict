"""tune.py: 후보 6계열 랜덤 서치의 규칙 — 설정 뽑기가 결정적이고, 2026 시험 시즌을 고르는 데 쓰지 않으며,
지금 모델(로지스틱 회귀 C=1)이 비교 기준으로 늘 들어 있는지."""
import json

import numpy as np
import pandas as pd
import pytest

from kbo_predict import tune
from kbo_predict.features import FEATURE_NAMES


def _toy(seasons=range(2015, 2027), n=60, seed=0):
    """시즌마다 n경기, 피처 몇 개가 승패와 약하게 상관된 가짜 데이터 (NaN 조금 포함)."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in seasons:
        X = rng.normal(size=(n, len(FEATURE_NAMES)))
        logit = 0.15 + 0.8 * X[:, 0] - 0.5 * X[:, 3]
        y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
        X[rng.random(X.shape) < 0.03] = np.nan
        df = pd.DataFrame(X, columns=FEATURE_NAMES)
        df["season"], df["y"] = s, y
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


def test_sample_configs_deterministic_and_unique():
    for fam in tune.FAMILIES:
        a, b = tune.sample_configs(fam, 12), tune.sample_configs(fam, 12)
        assert a == b, fam
        keys = [json.dumps(c, sort_keys=True, default=str) for c in a]
        assert len(keys) == len(set(keys)), fam
        for c in a:
            assert set(c) == set(tune.SPACE[fam]) and all(c[k] in tune.SPACE[fam][k] for k in c), fam
    assert tune.CURRENT[1] in tune.sample_configs("logreg", 40)  # 지금 모델 설정은 늘 후보에 있다
    assert len(tune.sample_configs("logreg", 40)) == 14           # 로지스틱 회귀는 조합 전부


@pytest.mark.parametrize("family", tune.FAMILIES)
def test_every_family_fits_and_predicts_probabilities(family):
    df = _toy(seasons=[2015, 2016], n=80)
    cfg = tune.sample_configs(family, 1)[0]
    if "n_estimators" in cfg:
        cfg = {**cfg, "n_estimators": 20}
    if "max_iter" in cfg:
        cfg = {**cfg, "max_iter": 20}
    p = tune.fit_predict(family, cfg, df[df.season == 2015], df[df.season == 2016])
    assert p.shape == (80,) and np.all((p >= 0) & (p <= 1))


def test_cv_uses_only_past_seasons_and_never_2026(monkeypatch):
    seen = []
    real = tune.fit_predict

    def spy(family, params, train, test):
        seen.append((sorted(set(train["season"])), sorted(set(test["season"]))))
        return real(family, params, train, test)

    monkeypatch.setattr(tune, "fit_predict", spy)
    sc = tune.cv_score("logreg", tune.CURRENT[1], _toy())
    assert set(sc["per_season_log_loss"]) == set(tune.CV_SEASONS)
    for train_s, test_s in seen:
        assert len(test_s) == 1 and max(train_s) < test_s[0] and tune.TEST_SEASON not in train_s + test_s


def test_final_round_calibrates_without_test(monkeypatch):
    """결승: 캘리브레이터는 학습 시즌 LOSO로만 맞추고(시험·검증 시즌 미사용), 방법은 검증으로 고른다."""
    seen = []
    real = tune.fit_predict

    def spy(family, params, train, test):
        seen.append(sorted(set(train["season"])))
        return real(family, params, train, test)

    monkeypatch.setattr(tune, "fit_predict", spy)
    out = tune.final_round(*tune.CURRENT, _toy())
    assert out["calibration"] in tune.CALIBRATIONS
    assert set(out["calibration_val_logloss"]) == set(tune.CALIBRATIONS)
    assert all(tune.VAL_SEASON not in s and tune.TEST_SEASON not in s for s in seen)
    assert out["val"]["n"] == 60 and out["test"]["n"] == 60


def test_run_small_report_shape():
    rep = tune.run(_toy(n=50), n_iter=2, families=("logreg", "xgboost"), log=lambda *a: None)
    assert rep["protocol"]["test_used_for_selection"] is False
    assert {f["family"] for f in rep["finalists"]} == {"logreg", "xgboost"}
    vals = [f["val"]["log_loss"] for f in rep["finalists"]]
    assert vals == sorted(vals) and rep["recommended"]["family"] == rep["finalists"][0]["family"]
    assert rep["recommended"]["adopt"] == (rep["recommended"]["val_logloss_gain_vs_current"] > tune.ADOPT_MARGIN)
    json.dumps(rep, default=str)  # JSON으로 저장할 수 있다
