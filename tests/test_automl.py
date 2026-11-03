"""automl.py: FLAML 탐색 결과를 "설정으로 다시 만든 모델"로 결승을 치르는 규칙 —
2026 시험 시즌은 고르는 데 쓰지 않고, 같은 설정이면 같은 점수가 나온다(노트북 재현의 근거)."""
import json

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from kbo_predict import automl
from tests.test_tune import _toy


def test_imputed_uses_train_median_only():
    df = _toy(n=30)
    train, val, test = automl._split(df)
    a, b = automl._imputed(train, test)
    assert not a.isna().any().any() and not b.isna().any().any()
    med = train[automl.FEATURE_NAMES[0]].median()
    nan_rows = test[automl.FEATURE_NAMES[0]].isna()
    if nan_rows.any():
        assert np.allclose(b.loc[nan_rows, automl.FEATURE_NAMES[0]], med)


def test_describe_rebuild_roundtrip_single_thread():
    desc = automl.describe(LogisticRegression(C=0.5, n_jobs=4, max_iter=500))
    assert desc["params"]["n_jobs"] == 1 and desc["params"]["C"] == 0.5
    assert desc["params"]["random_state"] == automl.SEED  # 비어 있던 시드는 고정 (saga 풀이기 재현)
    m = automl.rebuild(desc)
    assert isinstance(m, LogisticRegression) and m.C == 0.5
    json.dumps(desc)


def test_final_round_deterministic_and_test_not_used_for_calibration(monkeypatch):
    df = _toy(n=40)
    desc = automl.describe(LogisticRegression(C=1.0, max_iter=500))
    seen = []
    real = automl.fit_calibrator
    monkeypatch.setattr(automl, "fit_calibrator", lambda m, p, y: seen.append(len(y)) or real(m, p, y))
    a = automl.final_round(desc, df)
    b = automl.final_round(desc, df)
    assert a["val"] == b["val"] and a["test"] == b["test"] and a["calibration"] in automl.CALIBRATIONS
    n_train = int(df["season"].isin(automl.tune.TRAIN_SEASONS).sum())
    assert seen and all(n == n_train for n in seen)  # 보정은 학습 시즌 OOF로만


@pytest.mark.slow
def test_run_small_budget_report_shape():
    pytest.importorskip("flaml")
    rep = automl.run(_toy(n=40), time_budget=5, log=lambda *a: None)
    assert rep["protocol"]["test_used_for_selection"] is False
    assert rep["automl_final"]["model"]["class"] and "correct_test" not in rep["automl_final"]
    json.dumps(rep, default=str)
