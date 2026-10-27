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


@pytest.fixture
def synthetic_df():
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(42)
    n = 400
    wp = rng.normal(0, 0.1, n)
    l10 = rng.normal(0, 0.2, n)
    rd = rng.normal(0, 1.0, n)
    y = ((wp * 4 + rd * 0.3 + rng.normal(0, 0.5, n)) > 0).astype(int)
    dates = pd.date_range("2026-04-01", periods=n, freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame(
        {
            "game_id": range(1, n + 1),
            "date": list(dates),
            "win_pct_diff": wp,
            "last10_diff": l10,
            "run_diff_diff": rd,
            "y": y,
        }
    )


@pytest.fixture
def bundle(synthetic_df):
    from kbo_predict.train_win import fit_model

    return fit_model(synthetic_df)


@pytest.fixture
def bundle_path(bundle, tmp_path):
    from kbo_predict.train_win import save_bundle

    p = tmp_path / "win_model.pkl"
    save_bundle(bundle, p)
    return p
