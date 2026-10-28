import warnings
from pathlib import Path
import nbformat
import pytest

# 윈도우 환경에서 jupyter_client가 import 시점에 내는 platformdirs 경고만 좁게 무시한다 (노트북 내용과 무관)
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Jupyter is migrating its paths to use standard platformdirs",
                            category=DeprecationWarning)
    from nbclient import NotebookClient

NB = Path(__file__).parent.parent / "notebooks" / "01_데이터_수집과_살펴보기.ipynb"

# 윈도우 환경에서 zmq가 커널 연결 시 내는 Proactor 경고만 좁게 무시한다 (노트북 내용과 무관)
@pytest.mark.filterwarnings("ignore:Proactor event loop does not implement add_reader family of methods:RuntimeWarning")
def test_notebook_01_executes_without_errors():
    nb = nbformat.read(NB, as_version=4)
    NotebookClient(nb, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(NB.parent)}}).execute()
    assert all(o.get("output_type") != "error" for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", []))

def test_notebook_01_has_intro_and_explanations():
    nb = nbformat.read(NB, as_version=4)
    assert nb.cells[0].cell_type == "markdown" and "collect.py" in nb.cells[0].source
    for i, c in enumerate(nb.cells):
        if c.cell_type == "code":
            assert nb.cells[i - 1].cell_type == "markdown", f"code cell {i} has no explanation above"
    assert all(c.get("outputs") for c in nb.cells if c.cell_type == "code"), "committed notebook must contain outputs"
