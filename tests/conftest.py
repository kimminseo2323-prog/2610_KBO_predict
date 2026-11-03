from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_html():
    def load(name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    return load


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("KBO_DATA_DIR", str(data))
    return data


@pytest.fixture(scope="session")
def synthetic_df():
    """합성 학습 데이터 600행 (피처 26개 + y). 실제 경기 피처와 비슷한 크기로 만든다.
    진짜 로짓 = 3·승률차 + 0.3·득실차 − 0.2·선발ERA차, y ~ 베르누이(시그모이드(로짓)). 선발 피처는 일부 결측(NaN).
    신호를 약하게 둬서 실제 경기 상태를 넣어도 확률이 0·1에 붙지 않게 한다 (요인 pp가 0으로 뭉개지지 않게)."""
    import numpy as np
    import pandas as pd

    from kbo_predict.features import FEATURE_NAMES, MODEL_FEATURES

    rng = np.random.default_rng(42)
    n = 600
    X = pd.DataFrame(rng.normal(0, 0.3, (n, len(FEATURE_NAMES))), columns=FEATURE_NAMES)
    X["win_pct_diff"] = rng.normal(0, 0.1, n)
    X["run_diff_diff"] = rng.normal(0, 1.0, n)
    X["starter_era_diff"] = rng.normal(0, 1.5, n)
    X["starter_known"] = (rng.random(n) < 0.8).astype(int)
    starter_cols = [c for c in FEATURE_NAMES if c.startswith("starter_") and c != "starter_known"]
    X.loc[X["starter_known"] == 0, starter_cols] = np.nan
    logit = 3 * X["win_pct_diff"] + 0.3 * X["run_diff_diff"] - 0.2 * X["starter_era_diff"].fillna(0)
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    # Elo 차이(v0.3 피처)는 별도 난수로 마지막에 붙인다 — 위 26개 값·y가 v0.2 때와 똑같이 남게 (고정 기대값이 그대로)
    X["elo_diff"] = np.random.default_rng(7).normal(0, 50, n)
    X = X[MODEL_FEATURES]
    return X.assign(y=y, season=np.repeat([2024, 2025], n // 2))


@pytest.fixture(scope="session")
def bundle(synthetic_df):
    """라이브 모델과 같은 구성(LR + platt 캘리브레이션)의 작은 번들. 캘리브레이터는 뒤쪽 200행으로 맞춘다."""
    from kbo_predict.features import FEATURE_NAMES
    from kbo_predict.train_win import TEAM_LR, fit_model

    # 피처 26개·L2 C=1(TEAM_LR, v0.2 구성): 팀 모델(전망)로도 쓰이고, 고정해 둔 기대값(test_simulate PINNED_1029)이 이 설정으로 계산됐다
    return fit_model(synthetic_df.iloc[:400], kind="lr", calibration="platt", calib_df=synthetic_df.iloc[400:],
                     version="v-test", seasons=[2024, 2025], lr_params=TEAM_LR, features=FEATURE_NAMES)


@pytest.fixture
def bundle_path(bundle, tmp_path):
    from kbo_predict.train_win import save_bundle

    p = tmp_path / "win_model.pkl"
    save_bundle(bundle, p)
    return p
