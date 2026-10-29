"""parity 검사: 커밋된 산출물을 저장소의 원본 데이터와 코드만으로 다시 만들 수 있는지 확인한다. 네트워크 없음.

    python -X utf8 scripts/check_parity.py            # 전체 (노트북 02~05 실행 포함)
    python -X utf8 scripts/check_parity.py --quick    # 노트북 생략 (ci.yml · weekly_retrain.yml)

판정 항목 (모두 같아야 exit 0, 하나라도 다르면 exit 1 + 다른 파일·키 목록):
    (1) 다시 만든 features.parquet · matchup.parquet · 선수 유형 CSV의 SHA256 vs models/manifest.json
        (report·team 항목의 features_sha256, report.matchup_sha256, clusters.types_sha256)
        + 다시 맞춘 군집 묶음 vs 커밋된 models/clusters.pkl (cluster.compare: 중심 atol 1e-9 · 맞춤 시즌 라벨 동일)
    (2) train_report 재계산 vs data/public/model_report.json (generated_at · commit_sha · run_url 제외),
        train_team 요약 vs model_report.json의 ablation.no_starter,
        다시 학습한 report-2026 · team-2026 번들의 예측(피처 parquet 전 행) vs 커밋된 pkl (atol 1e-9).
        win_model.pkl(라이브)은 manifest의 live.features_sha256이 다시 만든 parquet와 같을 때만 같은 방법으로 비교한다
        (시즌 중에는 매일 경기가 쌓여 라이브 모델이 더 옛 parquet로 학습돼 있는 것이 정상이라 그때는 건너뛴다).
    (3) players.json · teams.json 재생성(cluster publish와 같은 함수) vs 커밋본 (generated_at · commit_sha 제외)
    (4) 되감기 샘플 날짜(--rewind-dates) 재생성 vs data/public/rewind/2026/{date}.json (generated_at · commit_sha 제외)
    (5) 노트북 02~05 실행 (오류 출력 0) — --quick이면 건너뛴다. 없는 노트북은 '없음'으로 적고 건너뛴다.

입력 규칙: 군집이 들어가는 하류 산출물(상성 parquet · cluster_quality · players/teams.json · 되감기 선발 유형)은 커밋된
models/clusters.pkl로 만든다 — 커밋된 pkl이 기준이고(다른 BLAS에서는 마지막 자리가 다를 수 있다), 군집을 다시 맞출 수
있는지는 (1)이 따로 본다. 승패 모델이 들어가는 하류(teams.json의 model_expected · 되감기)는 (2)에서 다시 학습한 번들로 만든다.

재생성 산출물은 --out(기본 artifacts/parity/, gitignore)에만 쓴다. 커밋된 파일은 읽기만 한다.
(노트북 02는 스스로 data/processed/features.parquet를 쓴다 — gitignore 폴더이고, 노트북을 그대로 실행하는 것이 검사다.)
"""
import argparse
import json
import math
import os
import shutil
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT):  # `python scripts/check_parity.py`로 실행해도 kbo_predict·scripts를 찾게
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

DEFAULT_REWIND_DATES = "2026-04-01,2026-07-01,2026-10-12"
REWIND_SEASON = 2026
NOTEBOOKS = ("02", "03", "04", "05")                # 실행할 노트북 번호 (01 수집 노트북은 네트워크라 제외)
META_KEYS = ("generated_at", "commit_sha")          # 실행마다 달라지는 최상위 키 — 비교에서 뺀다
REPORT_META_KEYS = META_KEYS + ("run_url",)
PRED_ATOL = 1e-9                                    # 번들 예측 비교 허용 오차 (cluster compare · live --skip-if-same과 같다)
REPORT_REL_TOL = 1e-9                               # 보고서 지표(실수) 비교 허용 오차 — first_diff 참조

PUBLIC = Path("data/public")
MANIFEST = Path("models/manifest.json")
CLUSTERS_PKL = Path("models/clusters.pkl")
REPORT_PKL = Path("models/report-2026.pkl")
TEAM_PKL = Path("models/team-2026.pkl")
LIVE_PKL = Path("models/win_model.pkl")


# ---------- JSON 비교 (저장소 없이도 테스트할 수 있게 순수 함수로) ----------

def first_diff(a, b, path: str = "", *, rel_tol: float = 0.0) -> str | None:
    """a와 b가 처음 다른 곳의 '키 경로: 커밋본 != 재생성' 설명, 같으면 None.
    dict는 키 집합 → 키 이름 순으로, list는 길이 → 원소 순으로 내려간다. NaN끼리는 같다고 본다.
    숫자는 기본으로 정확히 같아야 한다 (같은 코드·같은 입력·같은 기계면 같은 비트). rel_tol > 0이면 실수는
    math.isclose(rel_tol=rel_tol, abs_tol=rel_tol)로 본다 — BLAS 스레드 수·라이브러리가 다르면 로지스틱 회귀의
    마지막 자리(1e-16 수준)가 달라지므로 보고서 지표 비교에만 쓴다 (REPORT_REL_TOL)."""
    where = path or "(최상위)"
    if isinstance(a, dict) and isinstance(b, dict):
        only_a, only_b = sorted(set(a) - set(b), key=str), sorted(set(b) - set(a), key=str)
        if only_a or only_b:
            return f"{where}: 키가 다름 (커밋본에만 {only_a}, 재생성에만 {only_b})"
        for k in sorted(a, key=str):
            d = first_diff(a[k], b[k], f"{path}.{k}" if path else str(k), rel_tol=rel_tol)
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{where}: 길이 {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]", rel_tol=rel_tol)
            if d:
                return d
        return None
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return None
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))
                                       and not isinstance(a, bool) and not isinstance(b, bool)):
        return f"{where}: {a!r} ({type(a).__name__}) != {b!r} ({type(b).__name__})"
    if rel_tol and isinstance(a, float) and isinstance(b, float) and math.isclose(a, b, rel_tol=rel_tol, abs_tol=rel_tol):
        return None
    return None if a == b else f"{where}: {a!r} != {b!r}"


def _strip(obj, ignore) -> object:
    """최상위 dict에서 ignore 키를 뺀 사본 (실행 시각·커밋처럼 매번 달라지는 값)."""
    return {k: v for k, v in obj.items() if k not in ignore} if isinstance(obj, dict) else obj


def parity_compare(committed_dir, regen_dir, specs, *, rel_tol: float = 0.0) -> list[str]:
    """JSON 파일 쌍을 비교해 다른 것마다 '파일: 키 경로: 커밋본 != 재생성' 한 줄씩 돌려준다 (같으면 빈 목록).
    specs = [(커밋본 상대 경로, 재생성 상대 경로, 무시할 최상위 키들)] — 경로는 각각 committed_dir · regen_dir 기준.
    파일이 없거나 JSON으로 읽을 수 없으면 그것도 한 줄로 적는다. rel_tol은 first_diff와 같다."""
    committed_dir, regen_dir = Path(committed_dir), Path(regen_dir)
    out = []
    for c_rel, r_rel, ignore in specs:
        name = Path(c_rel).as_posix()
        try:
            a = json.loads((committed_dir / c_rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append(f"{name}: 커밋본을 읽을 수 없음 ({type(e).__name__}: {e})")
            continue
        try:
            b = json.loads((regen_dir / r_rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append(f"{name}: 재생성본을 읽을 수 없음 ({type(e).__name__}: {e})")
            continue
        d = first_diff(_strip(a, ignore), _strip(b, ignore), rel_tol=rel_tol)
        if d:
            out.append(f"{name}: {d}")
    return out


# ---------- 결과 표 ----------

class Table:
    """판정 표의 행들: (항목, 커밋본, 재생성, 결과) + 다른 파일·키 목록. 결과 = 같음 / 다름 / 건너뜀 / 없음."""

    def __init__(self):
        self.rows: list[tuple[str, str, str, str]] = []
        self.diffs: list[str] = []
        self.timings: list[tuple[str, float]] = []

    def add(self, item: str, committed: str, regen: str, ok: bool | None, diffs=(), note: str | None = None,
            ok_note: str | None = None):
        """ok: True 같음 / False 다름 / None 판정 없음(note를 그대로 적는다). ok_note: 같음일 때 덧붙일 설명."""
        result = note if ok is None else ((ok_note or "같음") if ok else "다름")
        self.rows.append((item, committed, regen, result))
        if ok is False:
            self.diffs += list(diffs) or [f"{item}: 다름"]

    def fail(self, item: str, err: BaseException):
        self.rows.append((item, "-", f"오류 {type(err).__name__}", "다름"))
        self.diffs.append(f"{item}: 재생성 중 오류 {err!r}")

    @property
    def ok(self) -> bool:
        return not self.diffs


def render(table: Table) -> int:
    """표를 stdout에 찍고 exit 코드를 돌려준다 (모두 같으면 0, 아니면 1 + 다른 파일·키 목록)."""
    head = ("항목", "커밋본", "재생성", "결과")
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for row in table.rows:
        print("| " + " | ".join(row) + " |")
    if table.timings:
        print("\n걸린 시간: " + ", ".join(f"{name} {sec:.1f}s" for name, sec in table.timings))
    if table.ok:
        print("\nparity: 모두 같음")
        return 0
    print("\nparity: 다름 — 다른 파일·키:")
    for d in table.diffs:
        print(f"  - {d}")
    return 1


def _short(sha: str | None) -> str:
    return sha[:12] if sha else "없음"


def _rel(path: Path) -> str:
    """표에 적을 경로: 작업 폴더(저장소 루트) 기준 상대 경로, 밖이면 절대 경로."""
    try:
        return Path(path).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


# ---------- 항목별 재생성 ----------

def check_features(t: Table, out: Path, manifest: dict) -> dict:
    """(1) features.parquet · matchup.parquet (커밋된 clusters.pkl의 유형으로 상성 열). 반환: 재생성 경로·해시."""
    from kbo_predict import cluster, features, raw_store
    from kbo_predict.train_win import _sha256

    obj = cluster.load_bundle(CLUSTERS_PKL)
    kb, kp = obj["batter"]["bundle"]["k"], obj["pitcher"]["bundle"]["k"]
    df = features.build_dataset(raw_store.available_seasons(), types=cluster.types_map(obj), kb=kb, kp=kp)
    f_path, m_path = out / "features.parquet", out / "matchup.parquet"
    features.save_features(df[features.BASE_COLUMNS], f_path)  # features CLI와 같은 열·같은 저장 함수
    features.save_features(df[["game_id", *features.matchup_feature_names(kb, kp)]], m_path)
    f_sha, m_sha = _sha256(f_path), _sha256(m_path)
    models = manifest.get("models", {})
    for name in ("report", "team"):
        want = models.get(name, {}).get("features_sha256")
        t.add(f"features.parquet ({name} 학습 입력)", _short(want), _short(f_sha), want == f_sha,
              [f"models/manifest.json: models.{name}.features_sha256: {want} != {f_sha}"])
    want = models.get("report", {}).get("matchup_sha256")
    t.add("matchup.parquet (상성 비교 입력)", _short(want), _short(m_sha), want == m_sha,
          [f"models/manifest.json: models.report.matchup_sha256: {want} != {m_sha}"])
    return {"features": f_path, "matchup": m_path, "features_sha256": f_sha}


def check_clusters(t: Table, out: Path, manifest: dict) -> None:
    """(1) 군집을 다시 맞춰 유형 CSV 해시 vs manifest, 중심·라벨 vs 커밋된 clusters.pkl."""
    from kbo_predict import cluster
    from kbo_predict.train_win import _sha256

    obj = cluster.build(cluster.ALL_SEASONS)
    cluster.save_bundle(obj, out / "clusters.pkl")
    cluster.write_types_csv(obj, out / "player_types.csv")
    want, got = manifest.get("models", {}).get("clusters", {}).get("types_sha256"), _sha256(out / "player_types.csv")
    t.add("player_types.csv (선수 유형)", _short(want), _short(got), want == got,
          [f"models/manifest.json: models.clusters.types_sha256: {want} != {got}"])
    res = cluster.compare(cluster.load_bundle(CLUSTERS_PKL), obj)
    worst = max(r["max_center_diff"] for r in res["groups"].values())
    n_lab = sum(r["label_diff"] for r in res["groups"].values())
    t.add("clusters.pkl 중심·맞춤 시즌 라벨", "models/clusters.pkl", f"max Δ {worst:.1e}, 라벨 {n_lab}개 다름",
          res["same"], [f"models/clusters.pkl: {g}: max |center diff| {r['max_center_diff']:.3e}, "
                        f"labels differ {r['label_diff']}/{r['n_fit_rows']}"
                        for g, r in res["groups"].items() if not r["same"]])


def _same_preds(t: Table, item: str, bundle: dict, committed_pkl: Path, df) -> None:
    import numpy as np

    from kbo_predict.train_win import load_bundle, predict_proba

    old = load_bundle(committed_pkl)
    a, b = predict_proba(old, df), predict_proba(bundle, df)
    diff = float(np.max(np.abs(a - b))) if len(a) else 0.0
    ok = old.get("features") == bundle["features"] and bool(np.allclose(a, b, rtol=0.0, atol=PRED_ATOL))
    t.add(item, committed_pkl.as_posix(), f"{len(df)}행 max Δ {diff:.1e}", ok,
          [f"{committed_pkl.as_posix()}: predict_proba max |diff| {diff:.3e} > atol {PRED_ATOL:g} "
           f"(또는 피처 목록이 다름)"])


def check_models(t: Table, out: Path, manifest: dict, feats: dict) -> dict:
    """(2) 보고서 · 팀 모델(· 라이브) 재학습. 반환: 다시 학습한 report · team 번들 (3)(4)에서 쓴다."""
    from kbo_predict import cluster
    from kbo_predict.features import load_features
    from kbo_predict.publish import _write_json
    from kbo_predict.train_win import save_bundle, train_live, train_report, train_team

    df = load_features(feats["features"])
    obj = cluster.load_bundle(CLUSTERS_PKL)  # train_win.main(report --clusters)과 같은 cluster_quality
    cq = cluster.quality(bundles={g: obj[g]["bundle"] for g in cluster.GROUPS},
                         assigned={g: obj[g]["assigned"] for g in cluster.GROUPS}, names_cfg=cluster.load_labels())
    meta = {"generated_at": None, "commit_sha": None, "run_url": None, "features_sha256": feats["features_sha256"]}
    report, report_bundle = train_report(df, meta=meta, matchup=load_features(feats["matchup"]), cluster_quality=cq)
    _write_json(out / "model_report.json", report, indent=2, sort_keys=True)  # 커밋본과 같은 형식 (train_win)
    save_bundle(report_bundle, out / "report-2026.pkl")
    spec = [(PUBLIC / "model_report.json", "model_report.json", REPORT_META_KEYS)]
    diffs = parity_compare(Path("."), out, spec, rel_tol=REPORT_REL_TOL)
    exact = not parity_compare(Path("."), out, spec)
    t.add("model_report.json (train_report)", "data/public/model_report.json", "다시 학습한 보고서", not diffs, diffs,
          ok_note=None if exact else f"같음 (실수 상대 {REPORT_REL_TOL:g} 이내, 비트는 다름)")
    _same_preds(t, "report-2026.pkl 예측", report_bundle, REPORT_PKL, df)

    committed = json.loads((PUBLIC / "model_report.json").read_text(encoding="utf-8"))
    kind = committed["selected"]
    summary, team_bundle = train_team(df, kind=kind, calibration=committed["models"][kind]["calibration"])
    save_bundle(team_bundle, out / "team-2026.pkl")
    summary = json.loads(json.dumps(summary))  # 보고서 JSON과 같은 타입으로 (튜플 → 리스트 등)
    d = first_diff(committed["ablation"]["no_starter"], summary, "ablation.no_starter", rel_tol=REPORT_REL_TOL)
    exact = first_diff(committed["ablation"]["no_starter"], summary) is None
    t.add("ablation.no_starter (train_team)", "model_report.json", "train_team 요약", d is None,
          [f"data/public/model_report.json: {d}"],
          ok_note=None if exact else f"같음 (실수 상대 {REPORT_REL_TOL:g} 이내, 비트는 다름)")
    _same_preds(t, "team-2026.pkl 예측", team_bundle, TEAM_PKL, df)

    live_sha = manifest.get("models", {}).get("live", {}).get("features_sha256")
    if live_sha == feats["features_sha256"]:
        live = train_live(df, kind=kind, calibration=committed["models"][kind]["calibration"],
                          n_estimators=committed["models"]["lgbm"]["best_iteration"], meta=meta)
        _same_preds(t, "win_model.pkl 예측 (라이브)", live, LIVE_PKL, df)
    else:
        t.add("win_model.pkl 예측 (라이브)", _short(live_sha), _short(feats["features_sha256"]), None,
              note="건너뜀 (라이브는 다른 parquet로 학습됨)")
    return {"report": report_bundle, "team": team_bundle, "report_path": out / "report-2026.pkl"}


def check_site(t: Table, out: Path, feats: dict, models: dict) -> None:
    """(3) players.json · teams.json — cluster publish와 같은 함수(publish_site)로 out/site/에."""
    from kbo_predict import cluster

    site = out / "site"
    cluster.publish_site(CLUSTERS_PKL, models["report_path"], feats["features"], site)
    for name in ("players.json", "teams.json"):
        diffs = parity_compare(Path("."), site, [(PUBLIC / name, name, META_KEYS)])
        t.add(name, f"data/public/{name}", _rel(site / name), not diffs, diffs)


def check_rewind(t: Table, out: Path, dates: list[str], models: dict) -> None:
    """(4) 되감기 샘플 날짜 — scripts/build_rewind.py와 같은 입력(선발 유형 = 커밋된 clusters.pkl)으로 빈 폴더에."""
    from kbo_predict.rewind import build_season
    from kbo_predict.simulate import load_postseason
    from scripts.run_pipeline import starter_types

    rewind_dir = out / "rewind"
    shutil.rmtree(rewind_dir, ignore_errors=True)  # --dates 병합 검사가 기존 index.json을 보지 않게 빈 폴더에서
    build_season(REWIND_SEASON, out_dir=rewind_dir, bundle=models["report"], team_bundle=models["team"],
                 meta={"generated_at": None, "commit_sha": None, "run_url": None}, dates=dates,
                 starter_types=starter_types(CLUSTERS_PKL, REWIND_SEASON), ps_config=load_postseason(REWIND_SEASON))
    specs = [(PUBLIC / "rewind" / str(REWIND_SEASON) / f"{d}.json", Path(str(REWIND_SEASON)) / f"{d}.json", META_KEYS)
             for d in dates]
    diffs = parity_compare(Path("."), rewind_dir, specs)
    t.add(f"rewind/{REWIND_SEASON} {len(dates)}일 ({', '.join(d[5:] for d in dates)})",
          f"data/public/rewind/{REWIND_SEASON}", _rel(rewind_dir / str(REWIND_SEASON)), not diffs, diffs)


def check_notebooks(t: Table) -> None:
    """(5) 노트북 02~05를 tests/test_notebooks.py와 같은 방식(nbclient, 작업 폴더 notebooks/)으로 실행. 오류 출력 0."""
    import nbformat

    with warnings.catch_warnings():  # 윈도우에서 jupyter_client가 import 때 내는 경로 안내 경고 (노트북과 무관)
        warnings.filterwarnings("ignore", message="Jupyter is migrating its paths", category=DeprecationWarning)
        from nbclient import NotebookClient

    nb_dir = Path("notebooks").resolve()
    for num in NOTEBOOKS:
        found = sorted(nb_dir.glob(f"{num}_*.ipynb"))
        if not found:
            t.add(f"노트북 {num}", "없음", "-", None, note="없음 (건너뜀)")
            continue
        path = found[0]
        t0 = time.time()
        nb = nbformat.read(path, as_version=4)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Proactor event loop does not implement add_reader")
                NotebookClient(nb, timeout=900, kernel_name="python3",
                               resources={"metadata": {"path": str(nb_dir)}}).execute()
            errors = [o for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", [])
                      if o.get("output_type") == "error"]
            msg = [f"notebooks/{path.name}: {o.get('ename')}: {o.get('evalue')}" for o in errors]
        except Exception as e:  # CellExecutionError 등: 첫 오류 셀에서 멈춘다
            msg = [f"notebooks/{path.name}: {type(e).__name__}: {str(e).strip().splitlines()[-1][:300]}"]
        t.add(f"노트북 {path.stem}", "오류 0", f"오류 {len(msg)} ({time.time() - t0:.0f}s)", not msg, msg)


# ---------- 실행 ----------

def run(*, quick: bool, out: Path, rewind_dates: list[str]) -> Table:
    t = Table()
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def step(name, fn, *args):
        t0 = time.time()
        try:
            return fn(*args)
        except Exception as e:  # 한 항목이 터져도 표는 끝까지 찍는다
            t.fail(name, e)
            return None
        finally:
            t.timings.append((name, time.time() - t0))

    feats = step("features", check_features, t, out, manifest)
    models = step("models", check_models, t, out, manifest, feats) if feats else None
    if feats and models:
        step("site", check_site, t, out, feats, models)
        step("rewind", check_rewind, t, out, rewind_dates, models)
    else:
        t.add("players.json · teams.json · rewind", "-", "-", False, ["(3)(4): 앞 단계 실패로 재생성하지 못함"])
    # 군집 맞춤은 맨 뒤에: cluster._single_thread(threadpool_limits)가 끝난 뒤에도 MKL이 1스레드로 남는 일이 있어
    # (Windows MKL에서 확인), 그 뒤에 학습하면 로지스틱 회귀의 마지막 자리가 커밋본(기본 스레드로 학습)과 달라진다.
    step("clusters", check_clusters, t, out, manifest)
    if quick:
        t.add("노트북 02~05", "-", "-", None, note="건너뜀 (--quick)")
    else:
        step("notebooks", check_notebooks, t)
    return t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="parity 검사: 커밋된 산출물을 다시 만들어 비교 (네트워크 없음)")
    ap.add_argument("--quick", action="store_true", help="노트북 실행(5)을 건너뛴다")
    ap.add_argument("--rewind-dates", default=DEFAULT_REWIND_DATES, help="되감기 비교 날짜 (쉼표 구분)")
    ap.add_argument("--repo", type=Path, default=Path("."), help="저장소 루트 (여기로 이동해 상대 경로로 읽는다)")
    ap.add_argument("--out", type=Path, default=Path("artifacts/parity"), help="재생성 산출물 폴더 (gitignore)")
    args = ap.parse_args(argv)
    out = args.out.resolve()  # --repo로 이동하기 전 기준
    os.chdir(args.repo)
    dates = [d.strip() for d in args.rewind_dates.split(",") if d.strip()]
    if not dates:
        ap.error("--rewind-dates is empty")
    t0 = time.time()
    table = run(quick=args.quick, out=out, rewind_dates=dates)
    code = render(table)
    print(f"총 {time.time() - t0:.1f}s ({'quick' if args.quick else 'full'})")
    return code


if __name__ == "__main__":
    sys.exit(main())
