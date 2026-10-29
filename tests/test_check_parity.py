"""scripts/check_parity.py: JSON 비교기(first_diff · parity_compare), 표·exit 코드, 실데이터 전체 실행(slow)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import check_parity as cp

ROOT = Path(__file__).resolve().parents[1]
PLAYERS = ROOT / "data" / "public" / "players.json"


def test_first_diff_reports_first_key_path():
    a = {"b": [1, {"x": 0.5}], "a": "s", "n": float("nan")}
    assert cp.first_diff(a, json.loads(json.dumps(a, allow_nan=True))) is None   # NaN끼리는 같다
    assert cp.first_diff(a, {**a, "b": [1, {"x": 0.25}]}) == "b[1].x: 0.5 != 0.25"
    assert cp.first_diff(a, {**a, "b": [1]}) == "b: 길이 2 != 1"
    assert "키가 다름" in cp.first_diff(a, {"a": "s"})
    assert cp.first_diff({"k": 1}, {"k": 1.0}) is None                            # 정수·실수 같은 값
    assert cp.first_diff({"k": True}, {"k": 1}) is not None                       # bool은 숫자로 보지 않는다
    assert cp.first_diff({"k": None}, {"k": 0}) is not None
    # 허용 오차: 보고서 지표의 BLAS 마지막 자리 차이만 넘어간다
    assert cp.first_diff([0.24713564811891783], [0.24713564811891747]) is not None
    assert cp.first_diff([0.24713564811891783], [0.24713564811891747], rel_tol=1e-9) is None
    assert cp.first_diff([0.5], [0.5001], rel_tol=1e-9) is not None


def _fake_repo(tmp_path):
    """커밋본 폴더(data/public/players.json)와 재생성 폴더(players.json) — 실제 players.json 한 벌씩.
    재생성본은 실행 시각·커밋만 다르게 둔다 (비교에서 빠지는 키)."""
    committed, regen = tmp_path / "repo", tmp_path / "regen"
    (committed / "data/public").mkdir(parents=True)
    regen.mkdir()
    shutil.copy(PLAYERS, committed / "data/public/players.json")
    obj = json.loads(PLAYERS.read_text(encoding="utf-8"))
    obj.update(generated_at="2099-01-01T00:00:00+09:00", commit_sha="0" * 40)
    (regen / "players.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return committed, regen, [(Path("data/public/players.json"), "players.json", cp.META_KEYS)]


def test_check_parity_detects_tamper(tmp_path, capsys):
    """players.json의 x 하나를 바꾸면 다름 → exit 1, 출력에 파일 이름과 키 경로. 안 바꾸면 exit 0."""
    committed, regen, specs = _fake_repo(tmp_path)
    assert cp.parity_compare(committed, regen, specs) == []                  # generated_at·commit_sha는 무시
    t = cp.Table()
    t.add("players.json", "c", "r", True)
    assert cp.render(t) == 0 and "parity: 모두 같음" in capsys.readouterr().out

    path = committed / "data/public/players.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["players"][17]["x"] = round(obj["players"][17]["x"] + 0.001, 3)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    diffs = cp.parity_compare(committed, regen, specs)
    assert len(diffs) == 1 and diffs[0].startswith("data/public/players.json: players[17].x: ")
    t = cp.Table()
    t.add("players.json", "c", "r", not diffs, diffs)
    assert cp.render(t) == 1
    out = capsys.readouterr().out
    assert "players.json" in out and "players[17].x" in out and "| players.json | c | r | 다름 |" in out


def test_parity_compare_missing_or_broken_files(tmp_path):
    committed, regen, specs = _fake_repo(tmp_path)
    (regen / "players.json").write_text("{not json", encoding="utf-8")
    assert "재생성본을 읽을 수 없음" in cp.parity_compare(committed, regen, specs)[0]
    (committed / "data/public/players.json").unlink()
    assert "커밋본을 읽을 수 없음" in cp.parity_compare(committed, regen, specs)[0]


def test_table_failures_and_skips():
    t = cp.Table()
    t.add("노트북 05", "없음", "-", None, note="없음 (건너뜀)")             # 판정 없음은 실패가 아니다
    assert t.ok
    t.fail("models", ValueError("boom"))
    assert not t.ok and t.rows[-1][-1] == "다름" and "boom" in t.diffs[0]


@pytest.mark.slow
def test_check_parity_passes_on_committed(tmp_path):
    """실데이터: --quick으로 커밋된 산출물을 모두 다시 만들면 같다 (exit 0). 재생성본은 tmp에만 쓴다."""
    r = subprocess.run([sys.executable, "-X", "utf8", "scripts/check_parity.py", "--quick", "--out", str(tmp_path)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=1800)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "parity: 모두 같음" in r.stdout and "| 다름 |" not in r.stdout
    assert (tmp_path / "model_report.json").exists() and (tmp_path / "site/players.json").exists()
