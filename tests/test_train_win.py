"""train_win 테스트: 모델 코어(LR·LightGBM 공통 인터페이스, 요인 분해 항등식, 결정성, 캘리브레이션, 번들 저장)와
평가·보고서·학습 CLI(베이스라인, 캘리브레이션 표, McNemar, 시즌 OOF, train_report/train_live, manifest)."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest
from scipy.stats import rankdata
from sklearn.metrics import log_loss

from kbo_predict import MODEL_VERSION, REPORT_VERSION, TEAM_VERSION, train_win
from kbo_predict.features import (FACTOR_LABELS, FEATURE_NAMES, TEAM_FEATURES, load_features, parquet_fingerprint,
                                  save_features)
from kbo_predict.train_win import (
    LGBM_PARAMS,
    SEED,
    _baseline_preds,
    _correct,
    apply_calibrator,
    baselines,
    calibration_table,
    evaluate,
    explain,
    feature_importance,
    fit_calibrator,
    fit_model,
    load_bundle,
    mcnemar_p,
    oof_predictions,
    predict_proba,
    predict_raw,
    save_bundle,
    train_live,
    train_report,
    train_team,
    write_manifest,
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


def test_fit_model_rejects_empty_calibration_frame_before_fitting(data, monkeypatch):
    # 빈 calib_df는 비싼 학습을 하기 전에 거절해야 한다 → 추정기를 만들기만 해도 실패하게 바꿔 둔다.
    def boom(*a, **k):
        raise AssertionError("estimator built before calib_df check")
    monkeypatch.setattr(train_win, "_new_estimator", boom)
    with pytest.raises(ValueError, match="no calibration rows"):
        _fit(data, "lr", calibration="platt", calib_df=data["calib"].iloc[:0])


def test_platt_is_unregularized():
    p = np.linspace(0.05, 0.95, 50)
    cal = fit_calibrator("platt", p, (p > 0.5).astype(int))
    assert cal.penalty is None  # 교과서 Platt: 축소(정규화) 없음


# ---------- 평가 · 베이스라인 · 통계 ----------

def test_baselines_hand_computed():
    df = pd.DataFrame({
        "win_pct_diff":     [0.1, -0.2, 0.0, np.nan, 0.3, -0.1],
        "starter_era_diff": [-1.0, 0.5, 0.0, np.nan, 1.0, -0.5],
        "y":                [1, 0, 0, 1, 0, 1],
    })
    # home_always: 전부 홈(1) → y=1인 3/6
    # better_win_pct: 예측 [1,0,1(0→홈),1(NaN→홈),1,0] vs y → 맞음 1,1,0,1,0,0 = 3/6
    # lower_starter_era: 예측 [1,0,1(0→홈),1(NaN→홈),0,1] vs y → 맞음 1,1,0,1,1,1 = 5/6
    assert baselines(df) == pytest.approx({"home_always": 0.5, "better_win_pct": 0.5, "lower_starter_era": 5 / 6})


def test_calibration_table_bins_and_boundaries():
    p = np.array([0.0, 0.05, 0.1, 0.3, 0.95, 1.0])
    y = np.array([0, 0, 1, 1, 1, 0])
    table = calibration_table(p, y, bins=10)
    assert len(table) == 10
    assert [(b["lo"], b["hi"]) for b in table] == [(i / 10, (i + 1) / 10) for i in range(10)]
    assert [b["n"] for b in table] == [2, 1, 0, 1, 0, 0, 0, 0, 0, 2]  # 0.1은 [0.1,0.2), 1.0은 마지막 칸
    assert table[0]["pred_mean"] == pytest.approx(0.025) and table[0]["actual_rate"] == 0.0
    assert table[9]["pred_mean"] == pytest.approx(0.975) and table[9]["actual_rate"] == 0.5
    assert table[2]["pred_mean"] is None and table[2]["actual_rate"] is None
    json.dumps(table)  # 순수 파이썬 값만 (numpy 타입 없음)


def test_mcnemar_known_values():
    # 불일치: a만 맞음 5, b만 맞음 1 (나머지 14경기는 둘 다 맞거나 둘 다 틀림)
    a = np.array([True] * 5 + [False] * 1 + [True] * 10 + [False] * 4)
    b = np.array([False] * 5 + [True] * 1 + [True] * 10 + [False] * 4)
    assert mcnemar_p(a, b) == pytest.approx(0.21875)
    assert mcnemar_p(b, a) == pytest.approx(0.21875)
    assert mcnemar_p(a, a) == 1.0  # 불일치 없음
    assert mcnemar_p(np.array([True, False]), np.array([False, True])) == 1.0  # 1:1 → 상한 1


def test_evaluate_keys_and_values(data):
    bundle = _fit(data, "lr")
    out = evaluate(bundle, data["test"])
    assert set(out) == {"n", "accuracy", "log_loss", "brier"}
    assert out["n"] == len(data["test"])
    p, y = predict_proba(bundle, data["test"]), data["test"]["y"].to_numpy()
    assert out["accuracy"] == pytest.approx(((p >= 0.5) == y).mean())
    assert out["brier"] == pytest.approx(((p - y) ** 2).mean())
    assert all(type(v) in (int, float) for v in out.values())


@pytest.mark.parametrize("kind", ["lr", "lgbm"])
def test_feature_importance_normalized_sorted_labeled(data, kind):
    imp = feature_importance(_fit(data, kind, n_estimators=100))
    assert len(imp) == len(FEATURE_NAMES) and {d["name"] for d in imp} == set(FEATURE_NAMES)
    assert sum(d["importance"] for d in imp) == pytest.approx(1.0)
    assert [d["importance"] for d in imp] == sorted((d["importance"] for d in imp), reverse=True)
    assert all(d["label"] == FACTOR_LABELS[d["name"]] for d in imp)
    assert imp[0]["name"] == "win_pct_diff"  # 가장 강한 진짜 신호


@pytest.mark.parametrize("kind", ["lr", "lgbm"])
def test_fit_model_with_feature_subset(data, kind):
    """features=TEAM_FEATURES(19개)로 학습하면 번들·예측·요인 분해·OOF 모두 그 19개 열만 쓴다 (선발 피처 무시)."""
    bundle = _fit(data, kind, n_estimators=60, features=TEAM_FEATURES)
    assert bundle["features"] == TEAM_FEATURES and len(bundle["features"]) == 19
    test = data["test"]
    shuffled = test.copy()
    starter_cols = [c for c in FEATURE_NAMES if c not in TEAM_FEATURES]
    shuffled[starter_cols] = shuffled[starter_cols].to_numpy()[::-1]  # 선발 열을 섞어도 예측이 같아야 함
    np.testing.assert_array_equal(predict_raw(bundle, test), predict_raw(bundle, shuffled))
    contrib, base = explain(bundle, test)
    assert contrib.shape == (len(test), 19)
    np.testing.assert_allclose(contrib.sum(axis=1) + base, _logit(predict_raw(bundle, test)), rtol=0, atol=1e-6)
    assert _fit(data, kind, n_estimators=60)["features"] == FEATURE_NAMES  # 기본값은 26개 그대로
    df = data["train"][data["train"]["season"].isin([2023, 2024])]  # 합성 시즌 2개
    oof = oof_predictions(df, kind=kind, n_estimators=60, features=TEAM_FEATURES)
    m = fit_model(df[df["season"] == 2024], kind=kind, n_estimators=60, version="x", seasons=[2024],
                  features=TEAM_FEATURES)
    mask = (df["season"] == 2023).to_numpy()
    np.testing.assert_array_equal(oof[mask], predict_raw(m, df[mask]))


def test_oof_predictions_leave_one_season_out(data):
    df = data["train"][data["train"]["season"].isin([2023, 2024])]  # 합성 시즌 2개
    df = df.sample(frac=1, random_state=1).reset_index(drop=True)  # 두 시즌이 섞인 행 순서도 지켜야 함
    oof = oof_predictions(df, kind="lr", n_estimators=50)
    assert oof.shape == (len(df),)
    for s, other in ((2023, 2024), (2024, 2023)):
        m = fit_model(df[df["season"] == other], kind="lr", version="x", seasons=[other])
        mask = (df["season"] == s).to_numpy()
        np.testing.assert_array_equal(oof[mask], predict_raw(m, df[mask]))
    with pytest.raises(ValueError):
        oof_predictions(df[df["season"] == 2023], kind="lr", n_estimators=50)  # 시즌 1개로는 불가


# ---------- 보고서 · 라이브 학습 ----------

META = {"generated_at": "2026-10-29T12:00:00+09:00", "commit_sha": "abc123", "run_url": None,
        "features_sha256": "f" * 64}
REPORT_KEYS = {"model_version", "generated_at", "commit_sha", "run_url", "features_sha256", "features_fingerprint",
               "train_seasons",
               "val_season", "test_season", "n", "models", "selected", "baselines", "significance",
               "calibration_bins", "feature_importance", "matchup_feature_ablation", "cluster_quality",
               "starter_source", "ablation"}
BASELINE_ORDER = ["home_always", "better_win_pct", "lower_starter_era"]
SPLIT = dict(train_seasons=range(2023, 2025), val_season=2025, test_season=2026)


@pytest.fixture(scope="module")
def season_df(data):
    """합성 4시즌(2023~2026, 시즌당 500경기) — train 2023·2024 / val 2025 / test 2026."""
    return pd.concat([data["train"], data["calib"], data["test"]]).reset_index(drop=True)


@pytest.fixture(scope="module")
def report(season_df):
    return train_report(season_df, **SPLIT, meta=META)


def test_train_report_keys_and_selection(report):
    rep, bundle = report
    assert set(rep) == REPORT_KEYS
    assert rep["model_version"] == REPORT_VERSION and rep["generated_at"] == META["generated_at"]
    assert rep["features_sha256"] == META["features_sha256"] and rep["commit_sha"] == "abc123"
    assert rep["train_seasons"] == [2023, 2024] and rep["val_season"] == 2025 and rep["test_season"] == 2026
    assert rep["n"] == {"train": 1000, "val": 500, "test": 500}
    assert rep["selected"] in {"lr", "lgbm"}
    model_keys = {"calibration", "calibration_fit", "calibration_val_logloss", "val", "test"}
    assert set(rep["models"]["lr"]) == model_keys
    assert set(rep["models"]["lgbm"]) == model_keys | {"best_iteration"}
    assert 1 <= rep["models"]["lgbm"]["best_iteration"] < 2000
    for kind in ("lr", "lgbm"):
        m = rep["models"][kind]
        assert m["calibration_fit"] == "loso_oof_train"
        losses = m["calibration_val_logloss"]
        assert set(losses) == {"none", "platt", "isotonic"}
        assert losses[m["calibration"]] == min(losses.values())  # val 로그 손실이 가장 낮은 방법을 골랐다
        assert m["val"]["log_loss"] == pytest.approx(losses[m["calibration"]])
        assert set(m["test"]) == {"n", "accuracy", "log_loss", "brier"}
    other = "lgbm" if rep["selected"] == "lr" else "lr"
    assert rep["models"][rep["selected"]]["val"]["log_loss"] <= rep["models"][other]["val"]["log_loss"]
    assert set(rep["baselines"]) == {"val", "test"}
    assert set(rep["baselines"]["test"]) == {"home_always", "better_win_pct", "lower_starter_era"}
    sig = rep["significance"]
    assert set(sig) == {"vs", "selected_on", "mcnemar_p", "model_correct", "baseline_correct", "all"}
    # 비교 대상은 val(2025) 정확도가 가장 높은 베이스라인 — test 결과로 고르지 않는다 (동률이면 앞의 것)
    assert sig["selected_on"] == "val"
    base_val = rep["baselines"]["val"]
    assert sig["vs"] == next(b for b in BASELINE_ORDER if base_val[b] == max(base_val.values()))
    assert list(sig["all"]) == BASELINE_ORDER
    for name, s in sig["all"].items():
        assert set(s) == {"mcnemar_p", "model_correct", "baseline_correct"} and 0 <= s["mcnemar_p"] <= 1
        assert s["baseline_correct"] == round(rep["baselines"]["test"][name] * 500)
        assert s["model_correct"] == sig["model_correct"]
    assert sig["all"][sig["vs"]] == {k: sig[k] for k in ("mcnemar_p", "model_correct", "baseline_correct")}
    assert rep["starter_source"] == {"train_test": "actual (boxscore pitching order 1)",
                                     "live": "announced (schedule page)"}
    assert sig["model_correct"] == round(rep["models"][rep["selected"]]["test"]["accuracy"] * 500)
    assert sig["baseline_correct"] == round(rep["baselines"]["test"][sig["vs"]] * 500)
    assert 0 <= sig["mcnemar_p"] <= 1
    assert len(rep["calibration_bins"]) == 10 and sum(b["n"] for b in rep["calibration_bins"]) == 500
    assert len(rep["feature_importance"]) == len(FEATURE_NAMES)
    assert rep["matchup_feature_ablation"] is None and rep["cluster_quality"] is None
    # 번들: 선택된 알고리즘, report 버전, 선택된 캘리브레이션, 학습은 train 시즌만
    assert bundle["kind"] == rep["selected"] and bundle["version"] == REPORT_VERSION
    assert bundle["calibration"] == rep["models"][rep["selected"]]["calibration"]
    assert bundle["seasons"] == [2023, 2024] and bundle["n_games"] == 1000
    if bundle["kind"] == "lgbm":
        assert bundle["n_estimators"] == rep["models"]["lgbm"]["best_iteration"]
    json.dumps(rep, ensure_ascii=False, sort_keys=True)  # 직렬화 가능 (numpy 타입 없음)


def test_train_report_bundle_reproduces_test_metrics(report, season_df):
    rep, bundle = report
    test = season_df[season_df["season"] == 2026]
    assert evaluate(bundle, test) == rep["models"][rep["selected"]]["test"]


@pytest.mark.parametrize("method", ["platt", "isotonic"])
def test_train_report_calibrators_fit_on_train_oof_not_val(report, season_df, method):
    """캘리브레이터는 train 시즌 OOF 예측으로 맞춘다 (val은 방법 선택에만). 보고서가 기록한 val 로그 손실을 재현한다."""
    rep, _ = report
    train = season_df[season_df["season"].isin([2023, 2024])]
    val = season_df[season_df["season"] == 2025]
    for kind in ("lr", "lgbm"):
        n_est = rep["models"]["lgbm"]["best_iteration"]
        raw = fit_model(train, kind=kind, n_estimators=n_est, version="x", seasons=[2023, 2024])
        cal = fit_calibrator(method, oof_predictions(train, kind=kind, n_estimators=n_est), train["y"].to_numpy())
        want = log_loss(val["y"], apply_calibrator(cal, predict_raw(raw, val)), labels=[0, 1])
        assert rep["models"][kind]["calibration_val_logloss"][method] == pytest.approx(want, abs=1e-12)


def test_train_report_no_starter_ablation(report, season_df):
    """ablation.no_starter: 선택된 알고리즘을 팀 피처 19개만으로 같은 절차(트리 수는 val early stopping,
    캘리브레이션은 selected와 같은 방법을 train LOSO OOF로)로 다시 학습한 val·test 지표."""
    rep, _ = report
    ab = rep["ablation"]
    assert set(ab) == {"no_starter"}
    ns = ab["no_starter"]
    assert set(ns) == {"kind", "calibration", "best_iteration", "features", "n_features", "val", "test"}
    assert ns["kind"] == rep["selected"] and ns["calibration"] == rep["models"][rep["selected"]]["calibration"]
    assert ns["n_features"] == 19 and ns["features"] == TEAM_FEATURES
    for part, n in (("val", 500), ("test", 500)):
        assert set(ns[part]) == {"n", "accuracy", "log_loss", "brier"} and ns[part]["n"] == n
    if ns["kind"] == "lgbm":
        assert 1 <= ns["best_iteration"] < 2000
    else:
        assert ns["best_iteration"] is None
    # 같은 절차를 손으로 재현하면 test 지표가 똑같다
    train = season_df[season_df["season"].isin([2023, 2024])]
    test = season_df[season_df["season"] == 2026]
    n_est = ns["best_iteration"] or 300
    b = fit_model(train, kind=ns["kind"], n_estimators=n_est, version="x", seasons=[2023, 2024],
                  features=TEAM_FEATURES)
    if ns["calibration"] != "none":
        oof = oof_predictions(train, kind=ns["kind"], n_estimators=n_est, features=TEAM_FEATURES)
        b["calibrator"] = fit_calibrator(ns["calibration"], oof, train["y"].to_numpy())
    assert evaluate(b, test) == ns["test"]


def test_significance_comparator_chosen_on_val_not_test(season_df):
    """test 시즌에서만 '선발 ERA 낮은 팀'이 완벽한 규칙이 되게 바꿔도 비교 대상은 val 최고 베이스라인이다."""
    df = season_df.copy()
    rng = np.random.default_rng(7)
    t = (df["season"] == 2026).to_numpy()
    df.loc[t, "starter_era_diff"] = (1 - 2 * df.loc[t, "y"].to_numpy()) * (0.1 + rng.random(t.sum()))
    rep, bundle = train_report(df, **SPLIT, meta=META)
    sig, base = rep["significance"], rep["baselines"]
    assert max(base["test"], key=base["test"].get) == "lower_starter_era"  # 전제: test 최고는 선발 ERA
    val_best = next(b for b in BASELINE_ORDER if base["val"][b] == max(base["val"].values()))
    assert val_best != "lower_starter_era"  # 전제: val 최고는 다른 규칙
    assert sig["vs"] == val_best and sig["selected_on"] == "val"
    test = df[t]
    y = test["y"].to_numpy()
    model_ok = _correct(predict_proba(bundle, test), y)
    for name, pred in _baseline_preds(test).items():
        assert sig["all"][name]["mcnemar_p"] == mcnemar_p(model_ok, pred == y)


def test_train_report_rejects_missing_season(season_df):
    with pytest.raises(ValueError, match="2027"):
        train_report(season_df, train_seasons=range(2023, 2025), val_season=2025, test_season=2027, meta=META)


def test_train_report_deterministic_via_parquet(tmp_path, season_df):
    """리뷰 포커스 5: 같은 parquet → train_report 두 번 → generated_at만 빼면 JSON이 바이트 단위로 같다."""
    path = tmp_path / "features.parquet"
    save_features(season_df, path)
    dumps = []
    for stamp in ("2026-10-29T12:00:00+09:00", "2026-10-29T13:00:00+09:00"):
        rep, _ = train_report(load_features(path), **SPLIT, meta={**META, "generated_at": stamp})
        rep.pop("generated_at")
        dumps.append(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True))
    assert dumps[0] == dumps[1]


@pytest.mark.parametrize("kind,calibration", [("lr", "platt"), ("lgbm", "isotonic"), ("lgbm", "none")])
def test_train_live_uses_all_seasons_and_oof_calibrator(season_df, kind, calibration):
    bundle = train_live(season_df, kind=kind, calibration=calibration, n_estimators=60, meta=META)
    assert bundle["version"] == MODEL_VERSION and bundle["kind"] == kind
    assert bundle["seasons"] == [2023, 2024, 2025, 2026] and bundle["n_games"] == len(season_df)
    assert bundle["calibration"] == calibration and bundle["trained_at"] == META["generated_at"]
    assert (bundle["calibrator"] is None) == (calibration == "none")
    if calibration != "none":
        oof = oof_predictions(season_df, kind=kind, n_estimators=60)
        want = fit_calibrator(calibration, oof, season_df["y"].to_numpy())
        p = predict_raw(bundle, season_df.iloc[:50])
        np.testing.assert_array_equal(apply_calibrator(bundle["calibrator"], p), apply_calibrator(want, p))


def test_train_live_features_kwarg(season_df):
    """M-5: features를 주면 그 피처만으로 학습·캘리브레이션한다 (기본은 FEATURE_NAMES 26개)."""
    bundle = train_live(season_df, kind="lr", calibration="platt", n_estimators=60, meta=META,
                        features=TEAM_FEATURES)
    assert bundle["features"] == list(TEAM_FEATURES)
    oof = oof_predictions(season_df, kind="lr", n_estimators=60, features=TEAM_FEATURES)
    want = fit_calibrator("platt", oof, season_df["y"].to_numpy())
    p = predict_raw(bundle, season_df.iloc[:50])
    np.testing.assert_array_equal(apply_calibrator(bundle["calibrator"], p), apply_calibrator(want, p))
    assert train_live(season_df, kind="lr", calibration="none", n_estimators=60, meta=META)["features"] == FEATURE_NAMES


def test_write_manifest_updates_one_model_and_keeps_others(tmp_path, data):
    """manifest는 모델별로 (파일 해시, 버전, 그 모델을 만든 parquet 해시)를 적는다.
    한 명령은 자기 모델 항목만 갱신하고, 다른 항목은 기존 manifest에서 그대로 둔다."""
    f1, f2 = tmp_path / "f1.parquet", tmp_path / "f2.parquet"
    save_features(pd.DataFrame({"game_id": [1], "v": [0.1]}), f1)
    save_features(pd.DataFrame({"game_id": [1], "v": [0.2]}), f2)
    a, b = tmp_path / "models" / "a.pkl", tmp_path / "models" / "b.pkl"
    save_bundle(_fit(data, "lr"), a)
    save_bundle(_fit(data, "lgbm"), b)
    out = tmp_path / "models" / "manifest.json"
    write_manifest(out, name="report", bundle_path=a, features_path=f1, meta=META)
    text = out.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    entry_a = {"path": a.as_posix(), "sha256": hashlib.sha256(a.read_bytes()).hexdigest(), "version": "v-test",
               "features_sha256": hashlib.sha256(f1.read_bytes()).hexdigest(),
               "features_fingerprint": parquet_fingerprint(f1)}
    assert json.loads(text) == {"generated_at": META["generated_at"], "commit_sha": "abc123",
                                "models": {"report": entry_a}}
    save_bundle(_fit(data, "lr"), a)  # 디스크의 report pkl이 바뀌어도 live 명령은 report 항목을 건드리지 않는다
    write_manifest(out, name="live", bundle_path=b, features_path=f2, meta={**META, "generated_at": "later"})
    m = json.loads(out.read_text(encoding="utf-8"))
    assert m["generated_at"] == "later" and m["models"]["report"] == entry_a
    assert m["models"]["live"]["features_sha256"] == hashlib.sha256(f2.read_bytes()).hexdigest()
    assert m["models"]["live"]["features_fingerprint"] == parquet_fingerprint(f2) != entry_a["features_fingerprint"]
    assert m["models"]["live"]["sha256"] == hashlib.sha256(b.read_bytes()).hexdigest()


def test_commit_sha_from_env_then_git(monkeypatch):
    """M-4: GITHUB_SHA가 있으면 그 값, 없으면 git rev-parse HEAD, git도 실패하면 None."""
    import subprocess
    monkeypatch.setenv("GITHUB_SHA", "envsha")
    assert train_win._commit_sha() == "envsha"
    monkeypatch.delenv("GITHUB_SHA")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="deadbeef\n"))
    assert train_win._commit_sha() == "deadbeef"

    def boom(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(subprocess, "run", boom)
    assert train_win._commit_sha() is None
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 128, stdout=""))
    assert train_win._commit_sha() is None


def _cli_parquet(tmp_path, extra_rows: int = 0):
    """기본 분할(2015~2024 / 2025 / 2026)을 쓰는 12시즌짜리 작은 합성 parquet. extra_rows만큼 2026 행을 덧붙인다."""
    rng = np.random.default_rng(3)
    n = 12 * 120
    X = pd.DataFrame(rng.normal(0, 1, (n, len(FEATURE_NAMES))), columns=FEATURE_NAMES)
    y = (rng.random(n) < 1 / (1 + np.exp(-2 * X["win_pct_diff"]))).astype(int)
    df = X.assign(season=np.repeat(range(2015, 2027), 120), y=y)
    if extra_rows:
        df = pd.concat([df, df[df["season"] == 2026].iloc[:extra_rows]], ignore_index=True)
    path = tmp_path / "data/processed/features.parquet"
    save_features(df, path)
    return path


def test_cli_report_then_live(tmp_path, monkeypatch):
    """CLI: report → model_report.json + report-2026.pkl, live → win_model.pkl(v0.2), 각자 자기 manifest 항목 갱신.
    live는 보고서에서 selected·calibration·best_iteration만 읽으므로, parquet가 바뀌어도(경기 추가) 다시 학습된다."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_SHA", "cafe01")
    feats = _cli_parquet(tmp_path)
    with pytest.raises(SystemExit):
        train_win.main(["live"])  # 보고서가 없으면 live는 실패
    train_win.main(["report"])
    rep = json.loads((tmp_path / "data/public/model_report.json").read_text(encoding="utf-8"))
    assert set(rep) == REPORT_KEYS and rep["train_seasons"] == list(range(2015, 2025))
    assert rep["commit_sha"] == "cafe01"
    assert load_bundle(tmp_path / "models/report-2026.pkl")["version"] == REPORT_VERSION
    report_entry = json.loads((tmp_path / "models/manifest.json").read_text(encoding="utf-8"))["models"]["report"]
    assert report_entry["features_sha256"] == rep["features_sha256"]

    feats = _cli_parquet(tmp_path, extra_rows=30)  # 새 경기가 쌓인 parquet (보고서와 해시가 다르다)
    new_hash = hashlib.sha256(feats.read_bytes()).hexdigest()
    assert new_hash != rep["features_sha256"]
    train_win.main(["live"])
    live = load_bundle(tmp_path / "models/win_model.pkl")
    assert live["version"] == MODEL_VERSION and live["kind"] == rep["selected"]
    assert live["calibration"] == rep["models"][rep["selected"]]["calibration"]
    assert live["n_games"] == 12 * 120 + 30
    manifest = json.loads((tmp_path / "models/manifest.json").read_text(encoding="utf-8"))
    assert manifest["models"]["report"] == report_entry  # report 항목은 report 때 값 그대로
    assert manifest["models"]["live"]["features_sha256"] == new_hash
    assert {k: v["version"] for k, v in manifest["models"].items()} == {"report": REPORT_VERSION, "live": MODEL_VERSION}


def test_cli_report_refuses_to_overwrite_frozen_report(tmp_path, monkeypatch):
    """보고서는 한 번 만든 뒤 얼려 둔다: 이미 있으면 --force 없이는 거부하고 파일을 건드리지 않는다."""
    monkeypatch.chdir(tmp_path)
    _cli_parquet(tmp_path)
    frozen = tmp_path / "data/public/model_report.json"
    frozen.parent.mkdir(parents=True)
    frozen.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="model_report.json exists; use --force to overwrite the frozen report"):
        train_win.main(["report"])
    assert frozen.read_text(encoding="utf-8") == "{}\n" and not (tmp_path / "models").exists()
    train_win.main(["report", "--force"])
    assert set(json.loads(frozen.read_text(encoding="utf-8"))) == REPORT_KEYS


def test_cli_report_force_refuses_to_drop_matchup_and_cluster_blocks(tmp_path, monkeypatch):
    """기존 보고서에 matchup_feature_ablation·cluster_quality가 있는데 --matchup·--clusters 없이 report --force면
    블록이 null로 되돌아가므로 정식 명령을 알려 주며 거부한다. --reset-blocks면 일부러 지우는 것이라 진행한다."""
    monkeypatch.chdir(tmp_path)
    _cli_parquet(tmp_path)
    frozen = tmp_path / "data/public/model_report.json"
    frozen.parent.mkdir(parents=True)
    old = json.dumps({"matchup_feature_ablation": {"adopt": False}, "cluster_quality": {"version": "c"}}) + "\n"
    frozen.write_text(old, encoding="utf-8")
    canonical = "report --force --matchup data/processed/matchup.parquet --clusters models/clusters.pkl"
    with pytest.raises(SystemExit, match="matchup_feature_ablation, cluster_quality") as e:
        train_win.main(["report", "--force"])
    assert canonical in str(e.value) and "--reset-blocks" in str(e.value)
    with pytest.raises(SystemExit, match=r"non-null cluster_quality;"):    # --matchup만 주면 군집 블록만 문제
        train_win.main(["report", "--force", "--matchup", "data/processed/matchup.parquet"])
    assert frozen.read_text(encoding="utf-8") == old and not (tmp_path / "models").exists()
    train_win.main(["report", "--force", "--reset-blocks"])
    rep = json.loads(frozen.read_text(encoding="utf-8"))
    assert rep["matchup_feature_ablation"] is None and rep["cluster_quality"] is None


# ---------- 상성 피처 전후 비교 · 군집 품질 ----------

MATCHUP_NAMES = ["bat_type0_diff", "bat_type1_diff", "starter_type0_diff", "starter_type1_diff", "types_known"]
ABLATION_KEYS = {"features_added", "without", "with", "mcnemar_p_test", "adopt", "note", "validation_scope",
                 "fit_seasons", "cluster_version"}


@pytest.fixture(scope="module")
def small_df(season_df):
    return season_df.assign(game_id=np.arange(len(season_df)) + 1000)


@pytest.fixture(scope="module")
def small_matchup(small_df):
    """game_id + 상성 열 (일부는 y와 약하게 상관, 일부 NaN). 행 순서를 섞어 game_id로 붙는지 확인한다."""
    rng = np.random.default_rng(11)
    n = len(small_df)
    y = small_df["y"].to_numpy()
    b0 = 0.3 * (y - 0.5) + rng.normal(0, 0.3, n)
    m = pd.DataFrame({"game_id": small_df["game_id"].to_numpy(), "bat_type0_diff": b0, "bat_type1_diff": -b0,
                      "starter_type0_diff": rng.integers(-1, 2, n), "starter_type1_diff": rng.integers(-1, 2, n),
                      "types_known": rng.integers(0, 2, n)})
    m.loc[rng.random(n) < 0.1, ["bat_type0_diff", "bat_type1_diff"]] = np.nan
    return m.sample(frac=1.0, random_state=1).reset_index(drop=True)


@pytest.fixture(scope="module")
def matchup_report(small_df, small_matchup):
    cq = {"version": "x", "fit_seasons": [2015, 2016]}
    return train_report(small_df, **SPLIT, matchup=small_matchup, cluster_quality=cq, meta={})


def test_report_matchup_ablation_keys(matchup_report):
    report, _ = matchup_report
    ab = report["matchup_feature_ablation"]
    assert set(ab) == ABLATION_KEYS
    assert report["cluster_quality"] == {"version": "x", "fit_seasons": [2015, 2016]}
    assert ab["features_added"] == MATCHUP_NAMES
    assert ab["cluster_version"] == "x" and ab["fit_seasons"] == [2015, 2016]
    assert ab["without"]["test"] == report["models"][report["selected"]]["test"]  # 전 = 본 모델과 동일
    assert ab["without"]["val"] == report["models"][report["selected"]]["val"]
    for part in ("val", "test"):
        assert set(ab["with"][part]) == {"n", "accuracy", "log_loss", "brier"} and ab["with"][part]["n"] == 500
    assert 0 <= ab["mcnemar_p_test"] <= 1
    assert ab["adopt"] is (ab["with"]["val"]["log_loss"] < ab["without"]["val"]["log_loss"] - 0.001)
    assert ab["note"].startswith("선택된 알고리즘·캘리브레이션·트리 수 고정, 피처만 추가. 라이브 반영은 4단계.")
    assert "2015~2016" in ab["note"] and ab["validation_scope"] in ab["note"] and "실제 선발" in ab["note"]
    assert "두 비교 모두 시간 외 비교" in ab["validation_scope"]  # 맞춤 2015~2016은 검증(2025)·test(2026) 이전
    json.dumps(report, ensure_ascii=False, sort_keys=True)


def test_report_matchup_does_not_change_main_report(report, matchup_report):
    """상성 비교를 더해도 나머지 보고서(본 모델·선택·지표)와 선택 번들의 확률은 그대로다."""
    plain, plain_bundle = report
    rep, bundle = matchup_report
    drop = {"matchup_feature_ablation", "cluster_quality", "generated_at", "commit_sha", "run_url",
            "features_sha256"}
    assert {k: v for k, v in rep.items() if k not in drop} == {k: v for k, v in plain.items() if k not in drop}
    assert bundle["features"] == FEATURE_NAMES


def test_report_matchup_with_reproduces_by_hand(matchup_report, small_df, small_matchup):
    """with = 선택된 알고리즘·캘리브레이션 방법·트리 수를 고정하고 피처만 늘려, 캘리브레이터는 train LOSO OOF로."""
    rep, _ = matchup_report
    kind, cal = rep["selected"], rep["models"][rep["selected"]]["calibration"]
    n_est = rep["models"]["lgbm"]["best_iteration"] if kind == "lgbm" else 300
    df = small_df.merge(small_matchup, on="game_id")
    train, test = df[df["season"].isin([2023, 2024])], df[df["season"] == 2026]
    feats = FEATURE_NAMES + MATCHUP_NAMES
    b = fit_model(train, kind=kind, n_estimators=n_est, version="x", seasons=[2023, 2024], features=feats)
    if cal != "none":
        oof = oof_predictions(train, kind=kind, n_estimators=n_est, features=feats)
        b["calibrator"] = fit_calibrator(cal, oof, train["y"].to_numpy())
    assert evaluate(b, test) == rep["matchup_feature_ablation"]["with"]["test"]


def test_report_without_matchup_unchanged(small_df):
    a, _ = train_report(small_df, **SPLIT, meta={})
    b, _ = train_report(small_df, **SPLIT, matchup=None, meta={})
    assert a == b and a["matchup_feature_ablation"] is None and a["cluster_quality"] is None


def test_report_matchup_rejects_missing_games(small_df, small_matchup):
    with pytest.raises(ValueError, match="missing 3 game_id"):
        train_report(small_df, **SPLIT, matchup=small_matchup.iloc[3:], meta={})


def test_cli_report_with_matchup_and_clusters(tmp_path, monkeypatch):
    """CLI report --matchup --clusters: 상성 전후 비교와 cluster.quality 결과가 보고서에, 상성 parquet 해시가
    manifest의 report 항목에 들어간다."""
    from kbo_predict import cluster

    monkeypatch.chdir(tmp_path)
    feats = _cli_parquet(tmp_path)
    df = load_features(feats).assign(game_id=lambda d: np.arange(len(d)))
    save_features(df, feats)
    rng = np.random.default_rng(5)
    mu = tmp_path / "data/processed/matchup.parquet"
    save_features(pd.DataFrame({"game_id": df["game_id"], "bat_type0_diff": rng.normal(0, 1, len(df)),
                                "types_known": rng.integers(0, 2, len(df))}), mu)
    calls = {}
    monkeypatch.setattr(cluster, "load_bundle", lambda path: {g: {"bundle": g, "assigned": g} for g in cluster.GROUPS})

    def fake_quality(bundles, assigned, names_cfg):
        calls.update(bundles=bundles, assigned=assigned, names_cfg=names_cfg)
        return {"version": "clusters-test", "fit_seasons": [2015, 2025]}

    monkeypatch.setattr(cluster, "quality", fake_quality)
    train_win.main(["report", "--matchup", str(mu), "--clusters", "models/clusters.pkl"])
    rep = json.loads((tmp_path / "data/public/model_report.json").read_text(encoding="utf-8"))
    assert rep["cluster_quality"] == {"version": "clusters-test", "fit_seasons": [2015, 2025]}
    assert calls["bundles"] == {"batter": "batter", "pitcher": "pitcher"} and set(calls["names_cfg"]) == {
        "batter", "pitcher"}
    ab = rep["matchup_feature_ablation"]
    assert ab["features_added"] == ["bat_type0_diff", "types_known"] and ab["cluster_version"] == "clusters-test"
    entry = json.loads((tmp_path / "models/manifest.json").read_text(encoding="utf-8"))["models"]["report"]
    assert entry["matchup_sha256"] == hashlib.sha256(mu.read_bytes()).hexdigest()


def test_validation_scope_wording():
    """실데이터 설정(맞춤 2015~2025, 검증 2025, test 2026): 검증은 전이적, test만 엄밀한 시간 외 비교."""
    real = train_win._validation_scope(list(range(2015, 2026)), 2025, 2026)
    assert "전이적(transductive)" in real and "test(2026) 비교만 엄밀한 시간 외 비교" in real
    assert "2024" in real and real.count(".") == 1  # 한 문장
    assert "모두" in train_win._validation_scope(list(range(2015, 2027)), 2025, 2026)
    assert "판정하지 않았다" in train_win._validation_scope(None, 2025, 2026)


def test_train_team_matches_report_ablation(small_df):
    report, _ = train_report(small_df, meta={})
    summary, bundle = train_team(small_df, kind=report["selected"],
                                 calibration=report["models"][report["selected"]]["calibration"])
    assert summary == report["ablation"]["no_starter"]  # 같은 절차 -> 같은 숫자
    assert bundle["version"] == TEAM_VERSION == "team-2026" and bundle["features"] == list(TEAM_FEATURES)
    _, b2 = train_team(small_df, kind=report["selected"], calibration=summary["calibration"],
                       meta={"generated_at": "2026-10-29T00:00:00+09:00"})
    assert b2["trained_at"] == "2026-10-29T00:00:00+09:00"


def test_train_team_lgbm_uses_early_stopping_rounds(small_df):
    """lgbm 분기: 팀 피처 19개로 val early stopping을 다시 돌리고, 그 트리 수로 번들을 학습한다."""
    summary, bundle = train_team(small_df, kind="lgbm", calibration="none")
    assert summary["kind"] == "lgbm" and isinstance(summary["best_iteration"], int)
    assert summary["best_iteration"] == bundle["n_estimators"]
    assert bundle["model"].n_estimators == bundle["n_estimators"]
    assert bundle["features"] == list(TEAM_FEATURES) and bundle["calibrator"] is None


def test_team_cli_writes_manifest_entry_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    feats = _cli_parquet(tmp_path)
    with pytest.raises(SystemExit):
        train_win.main(["team"])  # 보고서가 없으면 실패
    train_win.main(["report"])
    train_win.main(["live"])
    rep_path, man_path = tmp_path / "data/public/model_report.json", tmp_path / "models/manifest.json"
    rep_bytes = rep_path.read_bytes()
    before = json.loads(man_path.read_text(encoding="utf-8"))["models"]
    train_win.main(["team"])
    assert rep_path.read_bytes() == rep_bytes
    after = json.loads(man_path.read_text(encoding="utf-8"))["models"]
    assert set(after) == set(before) | {"team"}
    assert all(after[k] == before[k] for k in before)
    pkl = tmp_path / "models/team-2026.pkl"
    b = load_bundle(pkl)
    assert b["version"] == TEAM_VERSION and b["features"] == list(TEAM_FEATURES)
    assert after["team"] == {"path": "models/team-2026.pkl", "sha256": hashlib.sha256(pkl.read_bytes()).hexdigest(),
                             "version": TEAM_VERSION,
                             "features_sha256": hashlib.sha256(feats.read_bytes()).hexdigest(),
                             "features_fingerprint": parquet_fingerprint(feats),
                             "seasons": list(range(2015, 2027))}  # 얼린 시즌 FROZEN_SEASONS


def test_live_skip_if_same(tmp_path, monkeypatch, capsys):
    """live --skip-if-same: 같은 parquet로 다시 학습하면 예측이 같으므로 "unchanged"만 찍고 pkl·manifest를 쓰지 않는다
    (mtime·바이트 불변). parquet에 경기가 늘면 평소처럼 쓴다. live 밖에서 쓰면 거부."""
    monkeypatch.chdir(tmp_path)
    _cli_parquet(tmp_path)
    train_win.main(["report"])
    train_win.main(["live"])
    pkl, man = tmp_path / "models/win_model.pkl", tmp_path / "models/manifest.json"
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in (pkl, man)}
    capsys.readouterr()
    train_win.main(["live", "--skip-if-same"])
    assert "unchanged" in capsys.readouterr().out
    assert {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in (pkl, man)} == before

    feats = _cli_parquet(tmp_path, extra_rows=30)                    # 새 경기 → 예측이 달라진다 → 쓴다
    train_win.main(["live", "--skip-if-same"])
    assert "unchanged" not in capsys.readouterr().out
    assert pkl.read_bytes() != before[pkl][1] and load_bundle(pkl)["n_games"] == 12 * 120 + 30
    live_entry = json.loads(man.read_text(encoding="utf-8"))["models"]["live"]
    assert live_entry["features_sha256"] == hashlib.sha256(feats.read_bytes()).hexdigest()
    with pytest.raises(SystemExit):
        train_win.main(["report", "--force", "--skip-if-same"])


def test_same_predictions_handles_missing_or_broken(tmp_path, data):
    b = _fit(data, "lr")
    assert not train_win.same_predictions(b, tmp_path / "none.pkl", data["test"])
    (tmp_path / "bad.pkl").write_bytes(b"not a pickle")
    assert not train_win.same_predictions(b, tmp_path / "bad.pkl", data["test"])
    save_bundle(b, tmp_path / "b.pkl")
    assert train_win.same_predictions(b, tmp_path / "b.pkl", data["test"])
    assert not train_win.same_predictions(_fit(data, "lgbm"), tmp_path / "b.pkl", data["test"])
