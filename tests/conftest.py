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
