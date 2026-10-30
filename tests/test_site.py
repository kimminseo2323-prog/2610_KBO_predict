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

import pytest
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
    # 포커스 링·선택 점은 문맥 색 --focus, 보조 글자는 카드별 단색 --muted (글자에 투명도 쓰지 않음)
    assert re.search(r":focus-visible\s*\{[^}]*var\(--focus\)", css)
    assert re.search(r"\.card--teal\s*\{\s*--focus:\s*var\(--on-dark\)", css)
    assert re.search(r"\.inset\s*\{[^}]*--focus:\s*var\(--ink\)", css)
    for sel in (".card__lead", ".card__foot", ".kpi small", ".chart .c-axis"):
        rule = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", css).group(1)
        assert "opacity" not in rule and "var(--muted)" in rule, sel


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
    # model_report.json의 feature_importance 이름이 모두 한글 표에 있고, 표의 한글은 JSON의 label과 같다
    report = json.loads((DATA / "model_report.json").read_text(encoding="utf-8"))
    for f in report["feature_importance"]:
        assert js[f["name"]] == f["label"], f["name"]
    # 성적표는 자기 사본 없이 app.js의 표를 import한다
    text = (ASSETS / "report.js").read_text(encoding="utf-8")
    assert re.search(r'import\s*\{[^}]*\bFACTOR_LABELS\b[^}]*\}\s*from\s*"\./app\.js"', text)
    assert not re.search(r"\b(?:const|let|var)\s+FACTOR_LABELS\b", text)


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
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
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


def test_check_site_rejects_other_jsdelivr_and_inline_style(tmp_path):
    """허용은 호스트 정확히 일치 + jsDelivr는 /gh/orioncactus/pretendard@ 경로만. 인라인 <style>·style=의 외부 url()도 금지."""
    site = _tmp_site(tmp_path)
    page = site / "players.html"
    html = page.read_text(encoding="utf-8")
    page.write_text(html.replace("</head>", '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/x"></head>'),
                    encoding="utf-8")
    r = _run_check("--site", str(site))
    assert r.returncode == 1 and "cdn.jsdelivr.net/npm/x" in r.stdout
    page.write_text(html.replace("</head>", '<link rel="stylesheet" href="https://fonts.googleapis.com.evil.example/x.css"></head>')
                    .replace('<main id="main"', '<main id="main" style="background:url(https://img.example/a.png)"', 1)
                    .replace("</head>", "<style>@import url('https://evil.example/s.css');</style></head>"),
                    encoding="utf-8")
    r = _run_check("--site", str(site))
    assert r.returncode == 1
    for bad in ("fonts.googleapis.com.evil.example", "img.example/a.png", "evil.example/s.css"):
        assert bad in r.stdout, bad


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
    for bad in ("games..home", "", ".teams", "teams{}."):
        with pytest.raises(ValueError):
            check_site.key_exists(obj, bad)


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


# ---------- 홈 (index.html) ----------

HOME_SECTIONS = ["factors", "accuracy", "starters", "outlook", "type-map", "recent"]  # 벤토 순서 고정


def _home_soup():
    from bs4 import BeautifulSoup
    return BeautifulSoup((SITE / "index.html").read_text(encoding="utf-8"), "html.parser")


def test_home_markup_has_sections():
    """벤토 6장(크림·라벤더·피치·오커·틸·크림 순), 매치업 컨테이너, 되감기 슬라이더 컨테이너, 푸터 #evidence가 정적으로 있다."""
    soup = _home_soup()
    cards = soup.select(".home-bento > section")
    assert [c["id"] for c in cards] == HOME_SECTIONS
    colors = [next(k for k in c["class"] if k.startswith("card--")) for c in cards]
    assert colors == ["card--cream", "card--lavender", "card--peach", "card--ochre", "card--teal", "card--cream"]
    for a, b in zip(colors, colors[1:]):
        assert a != b  # 같은 색 연속 금지
    for c in cards:
        assert c.find(["h2"]) and c.get("aria-labelledby")
    assert soup.find(id="matchups") is not None
    assert soup.find(id="rewind-bar") is not None
    assert soup.find(id="evidence") is not None
    # 매치업이 벤토보다 앞, 그 앞에 날짜 칩
    html = str(soup)
    assert html.index('id="date-bar"') < html.index('id="matchups"') < html.index('id="factors"')
    assert [s["src"] for s in soup.find_all("script", src=True)] == ["assets/home.js"]
    assert soup.find("script", src="assets/home.js").get("type") == "module"


def test_home_rewind_mode_markup():
    """JS 없이 검사할 수 있는 것: 슬라이더(range)·전/후 버튼·라이브로 버튼·되감기 토글이 정적 마크업에 있다."""
    soup = _home_soup()
    bar = soup.find(id="rewind-bar")
    rng = bar.find("input", id="rewind-range")
    assert rng is not None and rng["type"] == "range"
    assert bar.find("label", attrs={"for": "rewind-range"}) is not None  # 이름 있는 슬라이더
    for bid in ("rewind-prev", "rewind-next", "to-live"):
        btn = bar.find("button", id=bid)
        assert btn is not None and btn.get("type") == "button", bid
    toggle = soup.find("button", id="rewind-toggle")
    assert toggle is not None and toggle.get("aria-controls") == "rewind-bar"
    js = (ASSETS / "home.js").read_text(encoding="utf-8")
    code = re.sub(r"(?m)^\s*//.*$|^\s*\*.*$|/\*\*?", "", js)  # 주석 줄은 빼고 코드만 본다
    # ?date= / ?fixture=edge(로컬에서만) 처리, 되감기는 index.json 날짜만 이동
    assert 'params.get("date")' in code
    assert 'FIXTURE === "edge"' in code and 'fetchJSON("latest_edge.json", FIXTURE_BASE)' in code
    assert 'IS_LOCAL ? params.get("fixture") : null' in code
    assert 'REWIND = "rewind/2026"' in code and '`${REWIND}/index.json`' in code


def test_check_site_strict_passes_with_home():
    r = _run_check("--strict", "--allow-missing-pages")
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"\| fixture-mode\s+\| index\.html\s+\| OK", r.stdout), r.stdout


# ---------- 모델 성적표 (report.html) ----------

REPORT_SECTIONS = ["holdout", "calibration", "importance", "variants", "cluster-quality", "live-record"]  # 순서 고정


def _report_soup():
    from bs4 import BeautifulSoup
    return BeautifulSoup((SITE / "report.html").read_text(encoding="utf-8"), "html.parser")


def test_report_markup():
    """배지 컨테이너(#model-badges)가 벤토보다 앞, 카드 6장(크림·라벤더·피치·오커·틸·크림 순, 같은 색 연속 없음), #evidence, report.js 모듈 하나."""
    soup = _report_soup()
    badges = soup.find(id="model-badges")
    assert badges is not None and badges.get("aria-label")
    cards = soup.select(".report-bento > section")
    assert [c["id"] for c in cards] == REPORT_SECTIONS
    colors = [next(k for k in c["class"] if k.startswith("card--")) for c in cards]
    assert colors == ["card--cream", "card--lavender", "card--peach", "card--ochre", "card--teal", "card--cream"]
    for a, b in zip(colors, colors[1:]):
        assert a != b
    for c in cards:
        h2 = c.find("h2")
        assert h2 is not None and c.get("aria-labelledby") == h2.get("id")
    html = str(soup)
    assert html.index('id="model-badges"') < html.index('id="holdout"')
    assert soup.find(id="evidence") is not None
    assert soup.find("a", attrs={"aria-current": "page"})["href"] == "report.html"
    assert [s["src"] for s in soup.find_all("script", src=True)] == ["assets/report.js"]
    assert soup.find("script", src="assets/report.js").get("type") == "module"
    # 선수 유형 품질 카드는 선수 페이지로 이어진다
    assert soup.find(id="cluster-quality").find("a", href="players.html") is not None


def test_report_js_uses_shared_constants_and_data():
    """report.js는 FACTOR_LABELS·TYPE_COLORS를 app.js에서 가져다 쓰고(자기 사본 없음), 숫자는 model_report.json·history.csv에서 읽는다."""
    js = (ASSETS / "report.js").read_text(encoding="utf-8")
    imports = re.search(r'import\s*\{([^}]*)\}\s*from\s*"\./app\.js"', js)
    assert imports and "FACTOR_LABELS" in imports.group(1) and "typeColor" in imports.group(1)
    assert not re.search(r"\b(?:const|let|var)\s+FACTOR_LABELS\b", js)
    assert '"pyth_diff"' not in js and "피타고리안" not in js  # 한글 이름 표를 복사하지 않음
    assert 'fetchJSON("model_report.json")' in js and 'fetchCSV("history.csv")' in js
    # 유의성 수치는 하드코딩하지 않는다 (+2.7%p, p = .215는 JSON에서 계산)
    code = re.sub(r"(?m)^\s*//.*$|^\s*\*.*$", "", js)
    for literal in ("2.7", ".215", "0.215", "0.594", "59.4", ".17", ".20"):
        assert literal not in code, literal
    for key in ("significance", "baselines", "calibration_bins", "feature_importance", "matchup_feature_ablation",
                "validation_scope", "membership_note", "starter_source", "ablation"):
        assert key in js, key


def test_check_site_strict_passes_with_report():
    r = _run_check("--strict", "--allow-missing-pages")
    assert r.returncode == 0, r.stdout + r.stderr
    for check in ("nav", "#evidence", "resources"):
        assert re.search(rf"\| {re.escape(check)}\s+\| report\.html\s+\| OK", r.stdout), (check, r.stdout)
    assert "report.html | SKIP" not in r.stdout.replace("  ", " ")


# ---------- 선수 탐색 (players.html) ----------

PLAYERS_SECTIONS = ["type-map", "player-card", "similar", "type-model"]  # 순서 고정: 크림 → 핑크 → 크림 → 틸


def _players_soup():
    from bs4 import BeautifulSoup
    return BeautifulSoup((SITE / "players.html").read_text(encoding="utf-8"), "html.parser")


def test_players_markup():
    """컨트롤(토글·시즌·팀·검색) → 지도·선수 카드 → 비슷한 선수 → 유형 모델, #evidence, players.js 모듈 하나."""
    soup = _players_soup()
    for cid in ("controls", "group-toggle", "season-select", "team-select", "player-search", "search-results",
                "map-body", "card-body", "similar-body", "model-body", "players-lead", "evidence"):
        assert soup.find(id=cid) is not None, cid
    toggle = soup.find(id="group-toggle")
    assert [b["data-group"] for b in toggle.find_all("button")] == ["batter", "pitcher"]
    assert all(b.get("aria-pressed") in ("true", "false") for b in toggle.find_all("button"))
    assert soup.find(id="season-select").name == "select" and soup.find(id="team-select").name == "select"
    assert soup.find(id="player-search").get("type") == "search"
    for cid in ("season-select", "team-select", "player-search"):  # 보이는 이름표
        assert soup.find("label", attrs={"for": cid}) is not None, cid
    cards = soup.select(".explore > section")
    assert [c["id"] for c in cards] == PLAYERS_SECTIONS
    colors = [next(k for k in c["class"] if k.startswith("card--")) for c in cards]
    assert colors == ["card--cream", "card--pink", "card--cream", "card--teal"]
    for c in cards:
        h2 = c.find("h2")
        assert h2 is not None and c.get("aria-labelledby") == h2.get("id")
    html = str(soup)
    assert html.index('id="controls"') < html.index('id="type-map"')
    assert soup.find("a", attrs={"aria-current": "page"})["href"] == "players.html"
    assert [s["src"] for s in soup.find_all("script", src=True)] == ["assets/players.js"]
    assert soup.find("script", src="assets/players.js").get("type") == "module"
    assert soup.find(id="type-model").find("a", href="report.html") is not None
    js = (ASSETS / "players.js").read_text(encoding="utf-8")
    assert 'fetchJSON("players.json")' in js and 'fetchJSON("model_report.json")' in js
    assert "history.replaceState" in js and "hashchange" in js
    assert re.search(r'import\s*\{[^}]*\btypeColor\b[^}]*\}\s*from\s*"\./app\.js"', js)
    assert not re.search(r"\b(?:const|let|var)\s+TYPE_COLORS\b", js)  # 유형 색은 app.js 하나뿐


def test_type_colors_cover_all_types():
    """players.json types의 모든 유형 id(그리고 각 선수의 type.id)에 TYPE_COLORS 색이 있고, 색은 팔레트 토큰이다."""
    colors = check_site.parse_js_const((ASSETS / "app.js").read_text(encoding="utf-8"), "TYPE_COLORS")
    players = json.loads((DATA / "players.json").read_text(encoding="utf-8"))
    tokens = set(re.findall(r"--([a-z-]+):", (ASSETS / "tokens.css").read_text(encoding="utf-8")))
    for group, types in players["types"].items():
        assert group in colors, group
        for t in types:
            assert str(t["id"]) in colors[group], (group, t)
            assert colors[group][str(t["id"])] in tokens, (group, t)
    used = {(p["group"], str(p["type"]["id"])) for p in players["players"]}
    assert all(tid in colors[g] for g, tid in used)


def test_check_site_strict_passes_with_players():
    r = _run_check("--strict", "--allow-missing-pages")
    assert r.returncode == 0, r.stdout + r.stderr
    for check in ("nav", "#evidence", "resources"):
        assert re.search(rf"\| {re.escape(check)}\s+\| players\.html\s+\| OK", r.stdout), (check, r.stdout)
    skipped = re.findall(r"\| page\s+\| (\S+)\s+\| SKIP", r.stdout)
    assert skipped in ([], ["teams.html"]), skipped


def test_team_name_for_old_names():
    """시즌 당시 이름: SK는 2020까지 SK 와이번스, WO는 2018까지 넥센 히어로즈 (그 뒤는 TEAMS의 지금 이름)."""
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    old = check_site.parse_js_const(js, "OLD_TEAM_NAMES")
    assert old == {"SK": {"until": 2020, "ko": "SK", "full": "SK 와이번스"},
                   "WO": {"until": 2018, "ko": "넥센", "full": "넥센 히어로즈"}}
    assert "export function teamNameFor" in js
    players = (ASSETS / "players.js").read_text(encoding="utf-8")
    assert "teamNameFor(p.team, p.season, { full: true })" in players and "teamNameFor(e.team, e.season)" in players


# ---------- 팀 (teams.html) ----------

TEAMS_SECTIONS = ["standings", "roster-types", "head-to-head", "playoff-rewind"]  # 순서 고정: 크림 → 라벤더 → 피치 → 오커


def _teams_soup():
    from bs4 import BeautifulSoup
    return BeautifulSoup((SITE / "teams.html").read_text(encoding="utf-8"), "html.parser")


def test_teams_markup():
    """머리 + 시즌 select(#season-select, 보이는 이름표) → 카드 4장(①~④, 색 순서 고정) → #evidence, teams.js 모듈 하나."""
    soup = _teams_soup()
    for cid in ("season-select", "standings-body", "roster-body", "h2h-body", "rewind-body", "teams-lead", "evidence"):
        assert soup.find(id=cid) is not None, cid
    assert soup.find(id="season-select").name == "select"
    assert soup.find("label", attrs={"for": "season-select"}) is not None
    cards = soup.select(".teams-stack > section")
    assert [c["id"] for c in cards] == TEAMS_SECTIONS
    colors = [next(k for k in c["class"] if k.startswith("card--")) for c in cards]
    assert colors == ["card--cream", "card--lavender", "card--peach", "card--ochre"]
    for c in cards:
        h2 = c.find("h2")
        assert h2 is not None and c.get("aria-labelledby") == h2.get("id")
    html = str(soup)
    assert html.index('id="season-select"') < html.index('id="standings"')
    assert soup.find("a", attrs={"aria-current": "page"})["href"] == "teams.html"
    assert [s["src"] for s in soup.find_all("script", src=True)] == ["assets/teams.js"]
    assert soup.find("script", src="assets/teams.js").get("type") == "module"
    js = (ASSETS / "teams.js").read_text(encoding="utf-8")
    assert 'fetchJSON("teams.json")' in js and 'fetchJSON("model_report.json")' in js
    assert re.search(r'fetchJSON\((?:"rewind/2026/index\.json"|`rewind/\$\{REWIND_SEASON\}/index\.json`)\)', js)
    assert "const REWIND_SEASON = 2026;" in js
    assert "history.replaceState" in js and "teamNameFor" in js
    assert re.search(r'import\s*\{[^}]*\btypeColor\b[^}]*\}\s*from\s*"\./app\.js"', js)
    assert not re.search(r"\b(?:const|let|var)\s+(?:TYPE_COLORS|TEAMS)\b", js)  # 색·팀은 app.js 하나뿐
    assert 'fetchJSON("players.json")' not in js  # 1.77 MB — 유형 이름은 model_report.json에서


def test_check_site_strict_passes_all_pages():
    """페이지 4개가 모두 있으므로 --allow-missing-pages 없이 통과한다."""
    r = _run_check("--strict")
    assert r.returncode == 0, r.stdout + r.stderr
    for check in ("nav", "#evidence", "resources"):
        assert re.search(rf"\| {re.escape(check)}\s+\| teams\.html\s+\| OK", r.stdout), (check, r.stdout)
    assert "| SKIP" not in r.stdout, r.stdout


def test_teams_tiebreak_games_are_real_ties():
    """결정전 표(TIEBREAK_GAMES)의 두 팀은 그 시즌 정규시즌 승률이 정확히 같다 (2021 1위 KT>삼성, 2024 5위 KT>SSG).
    동률 메모는 순서를 정한 규칙을 그대로 적는다: 결정전 / 상대 전적 / 코드순(임의)."""
    js = (ASSETS / "teams.js").read_text(encoding="utf-8")
    games = check_site.parse_js_const(js, "TIEBREAK_GAMES")
    assert games == {"2021": ["KT", "SS"], "2024": ["KT", "SK"]}
    teams = json.loads((DATA / "teams.json").read_text(encoding="utf-8"))["teams"]
    for season, (winner, loser) in games.items():
        rec = {t["code"]: t for t in teams if t["season"] == int(season)}
        w, l = rec[winner], rec[loser]
        assert w["wins"] * (l["wins"] + l["losses"]) == l["wins"] * (w["wins"] + w["losses"]), season
    for rule in ("결정전 승리(정규시즌 성적 미포함)", "상대 전적", "동률·코드순(임의)"):
        assert rule in js, rule
