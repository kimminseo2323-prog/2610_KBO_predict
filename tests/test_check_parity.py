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


def test_check_features_uses_frozen_seasons(tmp_path, monkeypatch):
    """(1)~(4)의 parquet는 정확히 FROZEN_SEASONS(2015~2026)로 만든다 — 2027 시즌이 data/raw에 있어도 들어가지 않는다."""
    from kbo_predict import FROZEN_SEASONS, cluster, features, raw_store

    class Stop(Exception):
        pass

    calls = []

    def fake_build(seasons, **kw):
        calls.append(list(seasons))
        raise Stop

    monkeypatch.setattr(cluster, "load_bundle", lambda p: {"batter": {"bundle": {"k": 3}}, "pitcher": {"bundle": {"k": 4}}})
    monkeypatch.setattr(cluster, "types_map", lambda obj: {})
    monkeypatch.setattr(raw_store, "available_seasons", lambda: list(range(2015, 2028)))   # 2027이 쌓인 상황
    monkeypatch.setattr(features, "build_dataset", fake_build)
    with pytest.raises(Stop):
        cp.check_features(cp.Table(), tmp_path, {})
    assert calls == [list(FROZEN_SEASONS)] and FROZEN_SEASONS == list(range(2015, 2027))


def test_live_rows_keeps_only_bundle_seasons():
    import pandas as pd

    df = pd.DataFrame({"season": [2025, 2026, 2027, 2027], "x": [1, 2, 3, 4]})
    assert cp.live_rows(df, {"seasons": [2025, 2026]})["x"].tolist() == [1, 2]


def test_first_diff_rel_tol_has_no_absolute_floor():
    assert cp.first_diff([1e-12], [2e-12], rel_tol=1e-9) is not None          # 0 근처도 상대 오차로만
    assert cp.first_diff([0.0], [0.0], rel_tol=1e-9) is None


def test_protected_out(tmp_path):
    repo = tmp_path / "repo"
    assert cp.protected_out(repo / "data/public", repo) and cp.protected_out(repo / "models/x", repo)
    assert not cp.protected_out(repo / "artifacts/parity", repo) and not cp.protected_out(tmp_path / "o", repo)
    with pytest.raises(SystemExit):
        cp.main(["--repo", str(repo), "--out", str(repo / "data/public/parity")])


def test_check_site_wiring_reports_tamper(tmp_path, monkeypatch):
    """실제 check_site 배선: publish_site가 쓴 파일과 cp.PUBLIC의 커밋본을 비교해 다르면 '다름' 행 + 파일·키."""
    from kbo_predict import cluster

    pub = tmp_path / "pub"
    pub.mkdir()
    shutil.copy(PLAYERS, pub / "players.json")
    (pub / "teams.json").write_text(json.dumps({"teams": [{"code": "LG", "wins": 80}], "generated_at": "a"}),
                                    encoding="utf-8")

    def fake_publish(clusters_path, report_path, features_path, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(PLAYERS, out_dir / "players.json")                       # players는 그대로
        (out_dir / "teams.json").write_text(json.dumps({"teams": [{"code": "LG", "wins": 81}], "generated_at": "b"}),
                                            encoding="utf-8")

    monkeypatch.setattr(cp, "PUBLIC", pub)
    monkeypatch.setattr(cluster, "publish_site", fake_publish)
    t = cp.Table()
    cp.check_site(t, tmp_path / "out", {"features": None}, {"report_path": None})
    assert [r[-1] for r in t.rows] == ["같음", "다름"]
    assert len(t.diffs) == 1 and "teams.json: teams[0].wins: 80 != 81" in t.diffs[0]


def test_check_live_skip_vs_require_live():
    """라이브 지문이 다르면 건너뜀(판정 없음), --require-live면 실패."""
    feats = {"live_fingerprint": "b" * 64}
    manifest = {"models": {"live": {"features_fingerprint": "a" * 64}}}
    t = cp.Table()
    cp.check_live(t, manifest, feats, {}, {}, require_live=False)
    assert t.ok and t.rows[0][-1].startswith("건너뜀")
    t = cp.Table()
    cp.check_live(t, manifest, feats, {}, {}, require_live=True)
    assert not t.ok and "--require-live" in t.diffs[0]


def test_required_notebooks_missing_fail(tmp_path, monkeypatch):
    """노트북 02~05가 하나라도 없으면 실패 (05도 필수)."""
    assert cp.REQUIRED_NOTEBOOKS == ("02", "03", "04", "05")
    (tmp_path / "notebooks").mkdir()
    monkeypatch.chdir(tmp_path)
    t = cp.Table()
    cp.check_notebooks(t)
    assert [r[-1] for r in t.rows] == ["다름", "다름", "다름", "다름"]
    assert len(t.diffs) == 4 and "notebooks/05_*.ipynb" in t.diffs[3]


def test_default_paths_are_repo_relative(tmp_path, monkeypatch):
    """--repo 기본값과 build_rewind의 기본 경로는 작업 폴더가 아니라 저장소 루트 기준."""
    from scripts import build_rewind

    seen = {}
    monkeypatch.chdir(tmp_path)                                               # 저장소 밖에서 실행해도
    monkeypatch.setattr(cp, "run", lambda **kw: seen.update(cwd=Path.cwd(), **kw) or cp.Table())
    monkeypatch.setattr(cp, "render", lambda table: 0)
    assert cp.main(["--quick"]) == 0
    assert seen["cwd"] == ROOT and seen["out"] == ROOT / "artifacts" / "parity"
    for p in (build_rewind.OUT_DIR, build_rewind.REPORT_PKL, build_rewind.TEAM_PKL, build_rewind.CLUSTERS_DEFAULT):
        assert p.is_absolute() and ROOT in p.parents


def test_parity_helpers_live_in_package():
    """check_parity의 비교 규칙은 kbo_predict.parity에서 온다 (노트북 03·04가 같은 함수를 쓴다)."""
    from kbo_predict import parity

    assert cp.first_diff is parity.first_diff and cp.REPORT_REL_TOL == parity.REPORT_REL_TOL == 1e-9
    assert parity.same_predictions_close([0.5, 0.25], [0.5 + 1e-12, 0.25])
    assert not parity.same_predictions_close([0.5], [0.5 + 1e-6]) and not parity.same_predictions_close([0.5], [0.5, 0.5])


@pytest.mark.slow
def test_check_parity_passes_on_committed(tmp_path):
    """실데이터: --quick으로 커밋된 산출물을 모두 다시 만들면 같다 (exit 0). 재생성본은 tmp에만 쓴다."""
    r = subprocess.run([sys.executable, "-X", "utf8", "scripts/check_parity.py", "--quick", "--out", str(tmp_path)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=1800)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "parity: 모두 같음" in r.stdout and "| 다름 |" not in r.stdout
    assert (tmp_path / "model_report.json").exists() and (tmp_path / "site/players.json").exists()
