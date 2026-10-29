"""train_win 모델 코어 테스트: LR·LightGBM 공통 인터페이스, 요인 분해 항등식, 결정성, 캘리브레이션, 번들 저장."""
import numpy as np
import pandas as pd
import pytest
from scipy.stats import rankdata

from kbo_predict.features import FEATURE_NAMES
from kbo_predict.train_win import (
    LGBM_PARAMS,
    SEED,
    apply_calibrator,
    explain,
    fit_calibrator,
    fit_model,
    load_bundle,
    predict_proba,
    predict_raw,
    save_bundle,
)

BUNDLE_KEYS = {"kind", "model", "features", "calibration", "calibrator", "version",
               "trained_at", "n_games", "seasons", "n_estimators"}


def _logit(p):
    return np.log(p / (1 - p))


@pytest.fixture(scope="module")
def data():
    """합성 데이터 2000행: 진짜 로짓 = 2·승률차 − 1·선발ERA차 + 잡음, 나머지 24개 피처는 잡음.
    선발 피처 일부와 다른 피처 몇 칸은 NaN(결측)으로 비워 둔다."""
    rng = np.random.default_rng(0)
    n = 2000
    X = pd.DataFrame(rng.normal(0, 1, (n, len(FEATURE_NAMES))), columns=FEATURE_NAMES)
    logit = 2 * X["win_pct_diff"] - 1 * X["starter_era_diff"] + rng.normal(0, 0.5, n)
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    starter_cols = [c for c in FEATURE_NAMES if c.startswith("starter_") and c != "starter_known"]
    X.loc[rng.random(n) < 0.15, starter_cols] = np.nan  # 선발 기록 없는 경기
    for c in ("prev_season_diff", "h2h_home_pct", "obp_diff"):
        X.loc[rng.random(n) < 0.05, c] = np.nan
    df = X.assign(y=y, season=np.repeat([2023, 2024, 2025, 2026], n // 4))
    return {"train": df.iloc[:1200], "calib": df.iloc[1200:1600], "test": df.iloc[1600:]}


def _fit(data, kind, **kw):
    return fit_model(data["train"], kind=kind, version="v-test", seasons=[2023, 2024], **kw)


@pytest.mark.parametrize("kind", ["lr", "lgbm"])
def test_lr_and_lgbm_fit_predict_shape_and_range(data, kind):
    bundle = _fit(data, kind, n_estimators=100)
    assert set(bundle) == BUNDLE_KEYS
    assert bundle["kind"] == kind and bundle["features"] == FEATURE_NAMES
    assert bundle["calibration"] == "none" and bundle["calibrator"] is None
    assert bundle["version"] == "v-test" and bundle["seasons"] == [2023, 2024]
    assert bundle["n_games"] == 1200
    assert bundle["n_estimators"] == (100 if kind == "lgbm" else None)

    test = data["test"]
    p = predict_proba(bundle, test)
    assert p.shape == (len(test),) and np.isfinite(p).all()
    assert ((p > 0) & (p < 1)).all()
    np.testing.assert_array_equal(p, predict_raw(bundle, test))  # 캘리브레이션 없음 → 같은 값
    acc = ((p >= 0.5).astype(int) == test["y"].to_numpy()).mean()
    assert acc > 0.65, acc  # 진짜 신호(승률차·선발ERA차)를 배웠는지


def test_explain_identity_lr(data):
    bundle = _fit(data, "lr")
    test = data["test"]
    contrib, base = explain(bundle, test)
    assert contrib.shape == (len(test), len(FEATURE_NAMES)) and base.shape == (len(test),)
    np.testing.assert_allclose(contrib.sum(axis=1) + base, _logit(predict_raw(bundle, test)), rtol=0, atol=1e-6)
    # 신호 방향: 승률차는 홈 승 쪽(+), 선발 ERA차는 홈 패 쪽(−)으로 기여
    i_wp, i_era = FEATURE_NAMES.index("win_pct_diff"), FEATURE_NAMES.index("starter_era_diff")
    assert np.corrcoef(contrib[:, i_wp], test["win_pct_diff"])[0, 1] > 0.99
    assert bundle["model"].named_steps["clf"].coef_[0][i_era] < 0


def test_explain_identity_lgbm(data):
    bundle = _fit(data, "lgbm", n_estimators=100)
    test = data["test"]
    contrib, base = explain(bundle, test)
    assert contrib.shape == (len(test), len(FEATURE_NAMES)) and base.shape == (len(test),)
    np.testing.assert_allclose(contrib.sum(axis=1) + base, _logit(predict_raw(bundle, test)), rtol=0, atol=1e-6)


@pytest.mark.parametrize("kind", ["lr", "lgbm"])
def test_determinism_same_bits(data, kind):
    a = _fit(data, kind, n_estimators=100)
    b = _fit(data, kind, n_estimators=100)
    assert np.array_equal(predict_proba(a, data["test"]), predict_proba(b, data["test"]))
    assert LGBM_PARAMS["seed"] == SEED == 42 and LGBM_PARAMS["deterministic"] is True


@pytest.mark.parametrize("method", ["platt", "isotonic"])
def test_calibration_platt_and_isotonic_change_probs_but_keep_order(data, method):
    bundle = _fit(data, "lgbm", n_estimators=100, calibration=method, calib_df=data["calib"])
    assert bundle["calibration"] == method and bundle["calibrator"] is not None
    test = data["test"]
    raw, cal = predict_raw(bundle, test), predict_proba(bundle, test)
    assert cal.shape == raw.shape and ((cal > 0) & (cal < 1)).all()
    assert not np.allclose(cal, raw)
    np.testing.assert_array_equal(cal, apply_calibrator(bundle["calibrator"], raw))
    if method == "platt":  # 단조 증가 함수 → 순위가 정확히 보존
        assert np.array_equal(rankdata(raw), rankdata(cal))
    else:  # 계단 함수 → 순위는 동률이 생길 수 있지만 뒤집히지는 않음
        assert np.all(np.diff(cal[np.argsort(raw, kind="stable")]) >= 0)
        assert cal.min() >= 0.01 and cal.max() <= 0.99


def test_calibrator_helpers_and_argument_errors(data):
    p = np.array([0.2, 0.5, 0.9])
    np.testing.assert_array_equal(apply_calibrator(None, p), p)
    with pytest.raises(ValueError):
        fit_calibrator("beta", p, np.array([0, 1, 1]))
    with pytest.raises(ValueError):
        _fit(data, "lr", calibration="platt")  # calib_df 없음
    with pytest.raises(ValueError):
        _fit(data, "svm")


def test_fit_model_rejects_empty_frame(data):
    with pytest.raises(ValueError, match="no training rows"):
        fit_model(data["train"].iloc[:0], kind="lr", version="v-test", seasons=[])


def test_bundle_roundtrip(tmp_path, data):
    bundle = _fit(data, "lgbm", n_estimators=100, calibration="isotonic", calib_df=data["calib"])
    path = tmp_path / "sub" / "win_model.pkl"
    save_bundle(bundle, path)
    loaded = load_bundle(path)
    assert set(loaded) == BUNDLE_KEYS
    assert {k: loaded[k] for k in BUNDLE_KEYS - {"model", "calibrator"}} == \
        {k: bundle[k] for k in BUNDLE_KEYS - {"model", "calibrator"}}
    test = data["test"]
    assert np.array_equal(predict_proba(loaded, test), predict_proba(bundle, test))
    for got, want in zip(explain(loaded, test), explain(bundle, test)):
        assert np.array_equal(got, want)
