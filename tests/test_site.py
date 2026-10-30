"""5단계 사이트(site/)의 공통 레이어·데이터 계약·검증 도구 테스트. 네트워크 없음, 커밋된 data/public/만 읽는다.

- tokens.css가 DESIGN_clay.md의 색·라운드·타입 스케일을 그대로 옮겼는지
- app.js의 TEAMS / FACTOR_LABELS / TYPE_COLORS가 파이썬 원본(teams.py, features.py, cluster_labels.yaml)과 같은지
- scripts/check_site.py가 저장소에서 통과하고(페이지가 아직 없으면 --allow-missing-pages), 금지된 외부 스크립트를 잡는지
- docs/site/data-contract.md 매핑 표의 키 경로가 샘플 파일에 실제로 있는지
- 홈 화면 방어용 fixture(취소·선발 미정·정상 경기, 되감기 status)가 커밋본과 같은 모양인지
"""
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from scripts import check_site

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
ASSETS = SITE / "assets"
DATA = ROOT / "data" / "public"
FIX = ROOT / "tests" / "fixtures" / "site"
DESIGN = ROOT / "DESIGN_clay.md"


def _py_literal(path: Path, name: str):
    """파이썬 모듈을 import하지 않고(무거운 의존성 없이) 최상위 대입 `name = {...}`의 값을 읽는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def _run_check(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "check_site.py"), *args],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8")


# ---------- 디자인 토큰 ----------

def test_tokens_match_design_md():
    """DESIGN_clay.md의 6색 카드·캔버스·서피스·라운드 값과 타입 스케일 최대 크기가 tokens.css에 그대로 있다."""
    design = DESIGN.read_text(encoding="utf-8")
    front = yaml.safe_load(design.split("---")[1])
    css = (ASSETS / "tokens.css").read_text(encoding="utf-8").lower()
    colors, rounded = front["colors"], front["rounded"]

    def var(name):
        m = re.search(rf"--{name}\s*:\s*([^;]+);", css)
        assert m, f"--{name} missing in tokens.css"
        return m.group(1).strip()

    expected = {
        "canvas": colors["canvas"], "surface-soft": colors["surface-soft"], "surface-card": colors["surface-card"],
        "ink": colors["ink"], "body": colors["body"], "muted": colors["muted"], "hairline": colors["hairline"],
        "pink": colors["brand-pink"], "teal": colors["brand-teal"], "lavender": colors["brand-lavender"],
        "peach": colors["brand-peach"], "ochre": colors["brand-ochre"], "cream": colors["surface-card"],
        "mint": colors["brand-mint"], "coral": colors["brand-coral"],
    }
    for name, hexv in expected.items():
        assert var(name) == hexv.lower(), name
    for name, key in {"r-md": "md", "r-lg": "lg", "r-xl": "xl"}.items():
        assert var(name) == rounded[key], name
    for px in (4, 8, 12, 16, 24, 32, 48, 96):
        assert var(f"sp-{px}") == f"{px}px"
    assert '"inter", "pretendard"' in var("font-display") and '"inter", "pretendard"' in var("font-body")
    # 타입 스케일: 클래스마다 DESIGN 값(최대 크기·굵기·줄간격·자간)이 그대로 들어 있다 (모바일은 clamp 최소값만 작다)
    for cls, spec in front["typography"].items():
        if cls in ("display-xl", "caption-uppercase", "button", "nav-link"):
            continue
        m = re.search(rf"\.{cls}\s*\{{([^}}]+)\}}", css)
        assert m, f".{cls} missing"
        rule = m.group(1)
        assert spec["fontSize"].lower() in rule, (cls, "size")
        assert f"font-weight: {spec['fontWeight']}" in rule, (cls, "weight")
        assert f"line-height: {spec['lineHeight']}" in rule, (cls, "line-height")
        ls = spec["letterSpacing"]
        assert f"letter-spacing: {ls if ls != 0 else 0}" in rule, (cls, "letter-spacing")


def test_card_colors_and_text_contrast_rules():
    """app.css: 카드 6색 변형, 핑크·틸만 흰 글자, 포커스 링, reduced-motion, wrap 1280px."""
    css = (ASSETS / "app.css").read_text(encoding="utf-8")
    for c in ("pink", "teal", "lavender", "peach", "ochre", "cream"):
        assert f".card--{c}" in css
    assert re.search(r"\.card--pink,\s*\.card--teal\s*\{[^}]*color:\s*var\(--on-dark\)", css)
    assert ":focus-visible" in css and "prefers-reduced-motion" in css
    assert "max-width: 1280px" in css
    assert "box-shadow" not in css  # 그림자 없음 (DESIGN)


# ---------- app.js 상수가 파이썬과 같다 ----------

def test_teams_match_python():
    py = _py_literal(ROOT / "src" / "kbo_predict" / "teams.py", "TEAMS")
    expected = {}
    for info in py.values():  # 현재 구단명이 옛 이름보다 먼저 나온다
        expected.setdefault(info["code"], info["ko"])
    js = check_site.parse_js_const((ASSETS / "app.js").read_text(encoding="utf-8"), "TEAMS")
    assert {code: t["ko"] for code, t in js.items()} == expected
    palette = {"pink", "teal", "lavender", "peach", "ochre", "cream", "mint", "coral"}
    for code, t in js.items():
        assert t["color"] in palette, code
        assert t["short"] and t["full"], code


def test_factor_labels_match_python():
    py = _py_literal(ROOT / "src" / "kbo_predict" / "features.py", "FACTOR_LABELS")
    js = check_site.parse_js_const((ASSETS / "app.js").read_text(encoding="utf-8"), "FACTOR_LABELS")
    assert js == py
    assert len(js) == 27 and js["bias"] == "기본 홈 어드밴티지"


def test_type_colors_match_cluster_labels():
    """컨트롤러 결정: 타자 {0 핑크, 1 피치, 2 틸, 3 라벤더}, 투수 {0 틸, 1 오커, 2 핑크, 3 라벤더}. id는 cluster_labels.yaml."""
    labels = yaml.safe_load((ROOT / "config" / "cluster_labels.yaml").read_text(encoding="utf-8"))
    js = check_site.parse_js_const((ASSETS / "app.js").read_text(encoding="utf-8"), "TYPE_COLORS")
    assert js == {"batter": {"0": "pink", "1": "peach", "2": "teal", "3": "lavender"},
                  "pitcher": {"0": "teal", "1": "ochre", "2": "pink", "3": "lavender"}}
    for group in ("batter", "pitcher"):
        assert {int(k) for k in js[group]} == set(labels[group])
    players = json.loads((DATA / "players.json").read_text(encoding="utf-8"))
    for group, types in players["types"].items():
        assert {str(t["id"]) for t in types} == set(js[group])


# ---------- check_site.py ----------

def test_check_site_reports_missing_pages_until_tasks_2_to_5():
    """페이지가 없을 때는 'missing page'로 exit 1 — 페이지가 생기면 이 테스트는 통과 쪽으로 바뀐다."""
    missing = [p for p in check_site.PAGES if not (SITE / p).exists()]
    r = _run_check()
    if missing:
        assert r.returncode == 1
        assert r.stdout.count("missing page") == len(missing)
    else:
        assert r.returncode == 0, r.stdout


def test_check_site_passes_on_repo():
    r = _run_check("--allow-missing-pages")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not re.search(r"\| FAIL\s*\|", r.stdout)


def _skeleton(page: str) -> str:
    """검사용 최소 페이지 — Task 2~5가 쓰는 공통 뼈대와 같은 구조(정적 nav + #evidence + assets/ 모듈)."""
    links = "".join(
        f'<li><a href="{href}"{" aria-current=\"page\"" if href == page else ""}>{label}</a></li>'
        for href, label in check_site.NAV)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>KBO Predict</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css">
<link rel="stylesheet" href="assets/tokens.css"><link rel="stylesheet" href="assets/app.css"></head>
<body><header class="topnav"><a class="brand" href="index.html">KBO Predict</a>
<nav aria-label="주 메뉴"><ul>{links}</ul></nav>
<a class="btn" href="{check_site.REPO_URL}">GitHub에서 보기</a></header>
<main id="main"></main>
<footer class="footer"><p id="evidence"></p></footer>
<script type="module">import {{ renderNav }} from "./assets/app.js"; renderNav("{page}");</script>
<script type="module" src="assets/charts.js"></script>
</body></html>
"""


def _tmp_site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    shutil.copytree(SITE, site)
    for page in check_site.PAGES:
        if not (site / page).exists():
            (site / page).write_text(_skeleton(page), encoding="utf-8")
    return site


def test_check_site_rejects_external_script(tmp_path):
    site = _tmp_site(tmp_path)
    ok = _run_check("--site", str(site))
    assert ok.returncode == 0, ok.stdout
    page = site / "index.html"
    page.write_text(page.read_text(encoding="utf-8").replace("</body>", '<script src="https://x"></script></body>'),
                    encoding="utf-8")
    bad = _run_check("--site", str(site))
    assert bad.returncode == 1
    assert "https://x" in bad.stdout


def test_check_site_rejects_bad_nav_and_missing_evidence(tmp_path):
    site = _tmp_site(tmp_path)
    page = site / "teams.html"
    html = page.read_text(encoding="utf-8")
    html = html.replace('href="players.html"', 'href="PLAYERS.html"').replace('id="evidence"', 'id="ev"')
    page.write_text(html, encoding="utf-8")
    r = _run_check("--site", str(site))
    assert r.returncode == 1
    assert re.search(r"\| nav\s+\| teams\.html\s+\| FAIL", r.stdout), r.stdout
    assert re.search(r"\| #evidence\s+\| teams\.html\s+\| FAIL", r.stdout), r.stdout


def test_check_site_rejects_external_css_import(tmp_path):
    site = _tmp_site(tmp_path)
    css = site / "assets" / "app.css"
    css.write_text('@import url("https://evil.example/x.css");\n' + css.read_text(encoding="utf-8"), encoding="utf-8")
    r = _run_check("--site", str(site))
    assert r.returncode == 1 and "evil.example" in r.stdout


def test_contract_keys_exist_in_samples():
    rows = check_site.contract_rows((ROOT / "docs" / "site" / "data-contract.md").read_text(encoding="utf-8"))
    assert len(rows) >= 35
    pages = {r.page for r in rows}
    assert pages == {"홈", "팀", "선수", "성적표", "공통"}
    files = {r.file for r in rows}
    for f in ("latest.json", "status.json", "history.csv", "rewind/2026/index.json", "rewind/2026/{date}.json",
              "players.json", "teams.json", "model_report.json"):
        assert f in files, f
    results = check_site.check_contract_keys(rows, DATA)
    missing = [(r.file, k) for r, k, ok in results if not ok]
    assert not missing


def test_key_path_syntax():
    obj = {"games": [{"home": {"starter": None}}, {"home": {"starter": {"type": {"name": "선발형"}}}}],
           "teams": {"LG": {"p": 1}}, "vs": [{"m": {"a": 0.5}}]}
    assert check_site.key_exists(obj, "games[].home.starter.type.name")
    assert check_site.key_exists(obj, "teams{}.p")
    assert check_site.key_exists(obj, "vs[].m{}")
    assert not check_site.key_exists(obj, "games[].home.starter.era")
    assert not check_site.key_exists(obj, "teams{}.q")


# ---------- fixture (홈 방어용) ----------

def test_sample_json_edge_cases():
    """latest_edge.json = 취소 1 + 선발 미정 1 + 정상 1. 최상위 키·경기 키가 커밋본 latest.json과 같다."""
    latest = json.loads((DATA / "latest.json").read_text(encoding="utf-8"))
    edge = json.loads((FIX / "latest_edge.json").read_text(encoding="utf-8"))
    assert list(edge) == list(latest)
    games = edge["games"]
    assert len(games) == 3
    canceled = [g for g in games if g["status"] == "CANCELED"]
    assert len(canceled) == 1 and canceled[0]["home_win_prob"] is None and canceled[0]["factors"] == []
    assert set(canceled[0]["home"]) == {"code"}
    tba = [g for g in games if g["status"] != "CANCELED" and (g["home"]["starter"] is None or g["away"]["starter"] is None)]
    assert len(tba) == 1 and tba[0]["starter_known"] is False
    normal = [g for g in games if g["status"] == "SCHEDULED" and g not in tba]
    assert len(normal) == 1
    full_keys = set(latest["games"][0])
    for g in tba + normal:
        assert set(g) == full_keys
        assert len(g["factors"]) == 5
    # 정상 경기의 한쪽 선발 유형은 null (직전 시즌 자격 없음) — 카드가 둘 다 처리해야 한다
    assert any(s["type"] is None for g in normal for s in (g["home"]["starter"], g["away"]["starter"]))
    assert edge["outlook"]["type"] in ("series", "playoff_race", "next_game")
    rows = check_site.contract_rows((ROOT / "docs" / "site" / "data-contract.md").read_text(encoding="utf-8"))
    for r in rows:
        if r.file == "latest.json" and not r.keys[0].startswith("outlook"):
            for k in r.keys:
                assert check_site.key_exists(edge, k), k


def test_status_rewind_fixture():
    status = json.loads((DATA / "status.json").read_text(encoding="utf-8"))
    fx = json.loads((FIX / "status_rewind.json").read_text(encoding="utf-8"))
    assert list(fx) == list(status)
    assert fx["mode"] == "rewind" and fx["run_url"] is None and fx["games_today"] == 0
