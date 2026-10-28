from pathlib import Path
import nbformat
from nbclient import NotebookClient

NB = Path(__file__).parent.parent / "notebooks" / "01_데이터_수집과_살펴보기.ipynb"

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
