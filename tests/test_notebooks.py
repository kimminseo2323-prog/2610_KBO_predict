import re
import warnings
from pathlib import Path
import nbformat
import pytest

# 윈도우 환경에서 jupyter_client가 import 시점에 내는 platformdirs 경고만 좁게 무시한다 (노트북 내용과 무관)
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Jupyter is migrating its paths to use standard platformdirs",
                            category=DeprecationWarning)
    from nbclient import NotebookClient

NB_DIR = Path(__file__).parent.parent / "notebooks"
# 노트북 파일 → 첫 마크다운 셀에 적혀 있어야 하는 짝 .py 파일
NOTEBOOKS = {
    "01_데이터_수집과_살펴보기.ipynb": "collect.py",
    "02_피처_만들기.ipynb": "features.py",
}
DEFINES = re.compile(r"^\s*(def|class)\s", re.MULTILINE)  # 노트북에서 함수·클래스를 새로 만들지 않는다 (로직은 src/에)


def _read(name: str):
    return nbformat.read(NB_DIR / name, as_version=4)


# 윈도우 환경에서 zmq가 커널 연결 시 내는 Proactor 경고만 좁게 무시한다 (노트북 내용과 무관)
@pytest.mark.filterwarnings("ignore:Proactor event loop does not implement add_reader family of methods:RuntimeWarning")
@pytest.mark.parametrize("name", NOTEBOOKS)
def test_notebook_executes_without_errors(name):
    nb = _read(name)
    NotebookClient(nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": str(NB_DIR)}}).execute()
    assert all(o.get("output_type") != "error" for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", []))


@pytest.mark.parametrize("name, paired_py", NOTEBOOKS.items())
def test_notebook_has_intro_and_explanations(name, paired_py):
    nb = _read(name)
    intro = nb.cells[0]
    assert intro.cell_type == "markdown" and paired_py in intro.source
    assert "하는 일" in intro.source and "왜" in intro.source
    for i, c in enumerate(nb.cells):
        if c.cell_type == "code":
            assert nb.cells[i - 1].cell_type == "markdown", f"code cell {i} has no explanation above"
            assert not DEFINES.search(c.source), f"code cell {i} defines a function/class — logic belongs in src/"
    code = [c for c in nb.cells if c.cell_type == "code"]
    assert all(c.get("outputs") for c in code), "committed notebook must contain outputs"
    stderr = [i for i, c in enumerate(nb.cells) if c.cell_type == "code"
              for o in c.get("outputs", []) if o.get("output_type") == "stream" and o.get("name") == "stderr"]
    assert not stderr, f"committed outputs contain warnings/stderr in cells {stderr}"
