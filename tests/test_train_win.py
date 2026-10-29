"""train_win 테스트: 모델 코어(LR·LightGBM 공통 인터페이스, 요인 분해 항등식, 결정성, 캘리브레이션, 번들 저장)와
평가·보고서·학습 CLI(베이스라인, 캘리브레이션 표, McNemar, 시즌 OOF, train_report/train_live, manifest)."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest
from scipy.stats import rankdata

from kbo_predict import MODEL_VERSION, REPORT_VERSION, train_win
from kbo_predict.features import FACTOR_LABELS, FEATURE_NAMES, load_features, save_features
from kbo_predict.train_win import (
    LGBM_PARAMS,
    SEED,
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
REPORT_KEYS = {"model_version", "generated_at", "commit_sha", "run_url", "features_sha256", "train_seasons",
               "val_season", "test_season", "n", "models", "selected", "baselines", "significance",
               "calibration_bins", "feature_importance", "matchup_feature_ablation", "cluster_quality"}
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
    assert set(rep["models"]["lr"]) == {"calibration", "val", "test"}
    assert set(rep["models"]["lgbm"]) == {"calibration", "best_iteration", "val", "test"}
    assert 1 <= rep["models"]["lgbm"]["best_iteration"] < 2000
    for kind in ("lr", "lgbm"):
        assert rep["models"][kind]["calibration"] in {"none", "platt", "isotonic"}
        assert set(rep["models"][kind]["test"]) == {"n", "accuracy", "log_loss", "brier"}
    other = "lgbm" if rep["selected"] == "lr" else "lr"
    assert rep["models"][rep["selected"]]["val"]["log_loss"] <= rep["models"][other]["val"]["log_loss"]
    assert set(rep["baselines"]) == {"val", "test"}
    assert set(rep["baselines"]["test"]) == {"home_always", "better_win_pct", "lower_starter_era"}
    sig = rep["significance"]
    assert set(sig) == {"vs", "mcnemar_p", "model_correct", "baseline_correct"}
    assert rep["baselines"]["test"][sig["vs"]] == max(rep["baselines"]["test"].values())
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


def test_write_manifest(tmp_path, data):
    feats = tmp_path / "features.parquet"
    feats.write_bytes(b"parquet-bytes")
    a = tmp_path / "models" / "a.pkl"
    save_bundle(_fit(data, "lr"), a)
    out = tmp_path / "models" / "manifest.json"
    write_manifest(out, features_path=feats, bundles={"live": a}, meta=META)
    text = out.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert json.loads(text) == {
        "generated_at": META["generated_at"], "commit_sha": "abc123",
        "features_sha256": hashlib.sha256(b"parquet-bytes").hexdigest(), "features_path": feats.as_posix(),
        "models": {"live": {"path": a.as_posix(), "sha256": hashlib.sha256(a.read_bytes()).hexdigest(),
                            "version": "v-test"}},
    }


def test_cli_report_then_live(tmp_path, monkeypatch):
    """CLI: report → model_report.json + report-2026.pkl, live → win_model.pkl(v0.2), 둘 다 manifest 갱신.
    기본 분할(2015~2024 / 2025 / 2026)을 쓰므로 12시즌짜리 작은 합성 parquet을 만든다."""
    rng = np.random.default_rng(3)
    n = 12 * 120
    X = pd.DataFrame(rng.normal(0, 1, (n, len(FEATURE_NAMES))), columns=FEATURE_NAMES)
    y = (rng.random(n) < 1 / (1 + np.exp(-2 * X["win_pct_diff"]))).astype(int)
    df = X.assign(season=np.repeat(range(2015, 2027), 120), y=y)
    monkeypatch.chdir(tmp_path)
    save_features(df, tmp_path / "data/processed/features.parquet")
    with pytest.raises(SystemExit):
        train_win.main(["live"])  # 보고서가 없으면 live는 실패
    train_win.main(["report"])
    rep = json.loads((tmp_path / "data/public/model_report.json").read_text(encoding="utf-8"))
    assert set(rep) == REPORT_KEYS and rep["train_seasons"] == list(range(2015, 2025))
    assert load_bundle(tmp_path / "models/report-2026.pkl")["version"] == REPORT_VERSION
    train_win.main(["live"])
    live = load_bundle(tmp_path / "models/win_model.pkl")
    assert live["version"] == MODEL_VERSION and live["kind"] == rep["selected"]
    assert live["calibration"] == rep["models"][rep["selected"]]["calibration"]
    manifest = json.loads((tmp_path / "models/manifest.json").read_text(encoding="utf-8"))
    assert manifest["features_sha256"] == rep["features_sha256"]
    assert {k: v["version"] for k, v in manifest["models"].items()} == {"report": REPORT_VERSION, "live": MODEL_VERSION}
