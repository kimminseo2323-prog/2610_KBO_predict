"""5단계 사이트(site/)의 공통 레이어·데이터 계약·검증 도구 테스트. 네트워크 없음, 커밋된 data/public/만 읽는다.

- tokens.css가 DESIGN_clay.md의 색·라운드·타입 스케일을 그대로 옮겼는지
- app.js의 TEAMS / FACTOR_LABELS / TYPE_COLORS가 파이썬 원본(teams.py, features.py, cluster_labels.yaml)과 같은지
- scripts/check_site.py가 저장소에서 --strict로 통과하고, 금지된 외부 스크립트·CSS·JS 주소를 잡는지
- assets JS가 replaceChildren/append에 `조건 ? 노드 : null`을 넘기지 않는지(null이 "null" 글자로 찍힘), fresh 읽기 규칙
- docs/site/data-contract.md 매핑 표의 키 경로가 샘플 파일에 실제로 있는지
- 홈 화면 방어용 fixture(취소·선발 미정·정상 경기, 되감기 status)가 커밋본과 같은 모양인지
- scripts/import_site.py가 내보내기의 beacon을 지우고 file:// 경로를 고치며, 검증 실패면 site/를 되돌리는지
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
    """app.css: 카드 6색 변형, 틸만 흰 글자(핑크 위 작은 글자·알약은 잉크), 포커스 링, reduced-motion, wrap 1280px."""
    css = (ASSETS / "app.css").read_text(encoding="utf-8")
    for c in ("pink", "teal", "lavender", "peach", "ochre", "cream"):
        assert f".card--{c}" in css
    assert re.search(r"\.card--teal\s*\{[^}]*color:\s*var\(--on-dark\)", css)
    # 핑크 위 흰 글자는 3.1:1 — 핑크 카드·핑크 알약의 기본 글자색은 잉크, 큰 표시용 글자만 페이지 CSS가 흰색으로 되돌린다
    assert re.search(r"\.card--pink\s*\{[^}]*color:\s*var\(--ink\)", css)
    assert re.search(r"\.card--pink\s*\{[^}]*--muted:\s*var\(--ink\)", css)
    assert re.search(r"\.pill--pink\s*\{[^}]*color:\s*var\(--ink\)", css)
    assert not re.search(r"\.pill--pink\s*\{[^}]*--on-dark", css)
    home_css = (ASSETS / "home.css").read_text(encoding="utf-8")
    assert re.search(r"\.side--away\s*\{[^}]*color:\s*var\(--ink\)", home_css)
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
    tokens = (ASSETS / "tokens.css").read_text(encoding="utf-8")
    for code, t in js.items():
        assert t["color"] == f"team-{code.lower()}", code  # 구단 대표색 토큰
        assert re.search(rf"--team-{code.lower()}:\s*#[0-9a-f]{{6}};", tokens), code  # tokens.css에 정의
        assert t["short"] and t["full"], code
    assert len({re.search(rf"--team-{c.lower()}:\s*(#[0-9a-f]{{6}})", tokens).group(1) for c in js}) == len(js)  # 겹치는 색 없음


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

def _tmp_site(tmp_path: Path) -> Path:
    """site/ 사본 (검사 도구가 잡아야 할 것을 넣어 보는 용도)."""
    site = tmp_path / "site"
    shutil.copytree(SITE, site)
    return site


def test_check_site_missing_page(tmp_path):
    """페이지가 없으면 'missing page' FAIL(exit 1), --allow-missing-pages면 SKIP(exit 0)."""
    site = _tmp_site(tmp_path)
    (site / "teams.html").unlink()
    r = _run_check("--site", str(site))
    assert r.returncode == 1 and re.search(r"\| page\s+\| teams\.html\s+\| FAIL\s+\| missing page", r.stdout), r.stdout
    r = _run_check("--site", str(site), "--allow-missing-pages")
    assert r.returncode == 0 and re.search(r"\| page\s+\| teams\.html\s+\| SKIP", r.stdout), r.stdout


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


def test_check_site_scans_every_linked_stylesheet(tmp_path):
    """assets/ 밖에 있는 로컬 스타일시트도 페이지가 연결했으면 외부 @import·url()을 검사한다."""
    site = _tmp_site(tmp_path)
    (site / "css").mkdir()
    (site / "css" / "extra.css").write_text('.x { background: url("https://img.example/bg.png"); }\n'
                                            '@import "https://evil.example/extra.css";\n', encoding="utf-8")
    page = site / "report.html"
    page.write_text(page.read_text(encoding="utf-8").replace("</head>", '<link rel="stylesheet" href="css/extra.css"></head>'),
                    encoding="utf-8")
    r = _run_check("--site", str(site))
    assert r.returncode == 1
    assert re.search(r"\| resources\s+\| report\.html\s+\| FAIL", r.stdout), r.stdout
    assert "img.example/bg.png" in r.stdout and "evil.example/extra.css" in r.stdout


def test_check_site_flags_external_urls_in_js(tmp_path):
    """JS 문자열 속 https:// 주소: 허용 목록·RAW_BASE·REPO_URL(커밋 링크 포함) 밖이면 FAIL. 주석 속 주소는 세지 않는다."""
    allowed = ('const a = "https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/status.json";\n'
               'const b = "https://github.com/kimminseo2323-prog/2610_KBO_predict/commit/abc1234";\n'
               '// 참고: https://comment.example/only-in-comment\n')
    assert check_site.js_external_urls(allowed) == []
    # 저장소 아래(앵커·파일 경로)와 공개 사이트 주소도 허용 — 브리프대로 만든 Genspark 페이지가 쓰는 링크
    own = ['const m = "https://github.com/kimminseo2323-prog/2610_KBO_predict#모델";',
           'const f = "https://github.com/kimminseo2323-prog/2610_KBO_predict/blob/main/README.md";',
           'const s = "https://kimminseo2323-prog.github.io/2610_KBO_predict/";',
           'const t = "https://kimminseo2323-prog.github.io/2610_KBO_predict/teams.html?season=2025";']
    assert check_site.js_external_urls("\n".join(own)) == []
    others = ['const o = "https://github.com/other/repo";',
              'const p = "https://github.com/kimminseo2323-prog/2610_KBO_predict_fork";',
              'const q = "https://evil.github.io/2610_KBO_predict/";']
    assert check_site.js_external_urls("\n".join(others)) == [
        "https://github.com/other/repo", "https://github.com/kimminseo2323-prog/2610_KBO_predict_fork",
        "https://evil.github.io/2610_KBO_predict/"]
    # check_site의 저장소·데이터 주소는 app.js 상수와 같다
    app = (ASSETS / "app.js").read_text(encoding="utf-8")
    for name in ("REPO_URL", "RAW_BASE"):
        assert f'export const {name} = "{getattr(check_site, name)}";' in app, name
    site = _tmp_site(tmp_path)
    home = site / "assets" / "home.js"
    home.write_text(allowed + 'const beacon = "https://collect.example/p";\n' + home.read_text(encoding="utf-8"), encoding="utf-8")
    page = site / "teams.html"
    page.write_text(page.read_text(encoding="utf-8").replace(
        "</body>", '<script type="module">fetch(`https://tracker.example/t?d=${document.title}`);</script></body>'), encoding="utf-8")
    r = _run_check("--site", str(site))
    assert r.returncode == 1
    assert re.search(r"\| assets\s+\| assets/\s+\| FAIL .*collect\.example/p", r.stdout), r.stdout
    assert re.search(r"\| resources\s+\| teams\.html\s+\| FAIL .*tracker\.example/t", r.stdout), r.stdout
    assert "comment.example" not in r.stdout and "commit/abc1234" not in r.stdout


def test_check_site_fixture_mode_needs_real_code(tmp_path):
    """--strict의 fixture 검사는 주석이 아닌 코드의 === "edge" 비교를 찾는다 (낱말이 주석에만 있으면 FAIL)."""
    site = _tmp_site(tmp_path)
    home = site / "assets" / "home.js"
    text = home.read_text(encoding="utf-8")
    assert 'FIXTURE === "edge"' in text
    home.write_text(text.replace('FIXTURE === "edge"', 'FIXTURE === "edgy"'), encoding="utf-8")
    r = _run_check("--site", str(site), "--strict")
    assert r.returncode == 1
    assert re.search(r'\| fixture-mode\s+\| index\.html\s+\| FAIL .*=== "edge"', r.stdout), r.stdout


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


# ---------- assets JS 공통 규칙 ----------

def _null_child_args(js: str) -> list[str]:
    """replaceChildren/append/prepend/before/after/replaceWith(…)의 인자 가운데 `조건 ? x : null` 꼴인 것.
    DOM 메서드는 null을 "null" 글자로 넣는다(app.js의 el()은 null을 건너뛰므로 el(…) 안은 괜찮다). 중첩 괄호 안은 보지 않는다."""
    skel = check_site.scan_js(js).skeleton
    found = []
    for m in re.finditer(r"\.(?:replaceChildren|append|prepend|before|after|replaceWith)\(", skel):
        i, depth, args, cur = m.end(), 0, [], []
        while i < len(skel):
            c = skel[i]
            if c in "([{":
                depth += 1
                if depth == 1:
                    cur.append(c + "…")
            elif c in ")]}":
                if depth == 0:
                    break
                depth -= 1
                if depth == 0:
                    cur.append(c)
            elif depth == 0:
                if c == ",":
                    args.append("".join(cur))
                    cur = []
                else:
                    cur.append(c)
            i += 1
        args.append("".join(cur))
        found += [a.strip() for a in args if re.search(r"\?[^?:]*:\s*null\b", a)]
    return found


def test_no_null_children_in_dom_calls():
    """조건부 자식은 `...(cond ? [x] : [])`로 펼친다 — `cond ? x : null`을 replaceChildren/append에 넘기면 "null"이 찍힌다."""
    assert _null_child_args('box.replaceChildren(a, big.length ? el("div") : null, c);')
    assert _null_child_args('box.append(ok ? x : null)')
    assert not _null_child_args('box.replaceChildren(a, ...(big.length ? [el("div")] : []), el("p", {}, b ? c : null));')
    for js in sorted(ASSETS.glob("*.js")):
        assert _null_child_args(js.read_text(encoding="utf-8")) == [], js.name


# 브라우저 캐시를 피할(fresh) 파일: 매일 바뀌는 4개뿐. 되감기 날짜 파일·players·teams·model_report는 기본 캐시.
FRESH = {"status.json", "latest.json", "history.csv", "index.json", "latest_edge.json", "status_rewind.json"}


def test_fresh_fetch_only_for_daily_files():
    """fetchJSON/fetchCSV에 { fresh: true }를 주는 것은 status·latest·history·rewind 목차(+ 그 검증용 fixture)뿐."""
    app = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "fresh" in app and 'cache: "no-store"' in app
    calls = 0
    for js in sorted(ASSETS.glob("*.js")):
        code = check_site.scan_js(js.read_text(encoding="utf-8")).code
        for m in re.finditer(r"\bfetch(?:JSON|CSV)\(\s*([\"'`])(.*?)\1([^()]*(?:\([^()]*\)[^()]*)*)\)", code):
            calls += 1
            name = m.group(2).rsplit("/", 1)[-1]
            fresh = re.search(r"\bfresh:\s*true\b", m.group(3)) is not None
            assert fresh == (name in FRESH), (js.name, m.group(0))
    assert calls >= 15


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
    assert 'FIXTURE === "edge"' in code and 'fetchJSON("latest_edge.json", { base: FIXTURE_BASE, fresh: true })' in code
    assert 'IS_LOCAL ? params.get("fixture") : null' in code
    # 선발 이름은 players.json을 읽은 뒤 player_id → 한글 이름으로 바꿔 다시 그린다(매치업·선발 카드)
    assert "koreanNames(state.players)" in code and code.count("starterName(s)") >= 2
    assert 'REWIND = "rewind/2026"' in code and '`${REWIND}/index.json`' in code


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
    assert 'fetchJSON("model_report.json")' in js and 'fetchCSV("history.csv", { fresh: true })' in js
    # 유의성 수치는 하드코딩하지 않는다 (+2.7%p, p = .215는 JSON에서 계산)
    code = re.sub(r"(?m)^\s*//.*$|^\s*\*.*$", "", js)
    for literal in ("2.7", ".215", "0.215", "0.594", "59.4", ".17", ".20"):
        assert literal not in code, literal
    for key in ("significance", "baselines", "calibration_bins", "feature_importance", "matchup_feature_ablation",
                "validation_scope", "membership_note", "starter_source", "ablation"):
        assert key in js, key


# ---------- 선수 탐색 (players.html) ----------

PLAYERS_SECTIONS = ["type-map", "player-card", "similar", "type-model"]  # 순서 고정: 크림 → 핑크 → 라벤더 → 틸


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
    cards = soup.select("main section.card")  # 지도·선수 카드는 .stage 래퍼 안에 있어도 문서 순서로 센다
    assert [c["id"] for c in cards] == PLAYERS_SECTIONS
    colors = [next(k for k in c["class"] if k.startswith("card--")) for c in cards]
    assert colors == ["card--cream", "card--pink", "card--lavender", "card--teal"]
    # 넓은 화면에서는 지도(크림)·선수 카드(핑크)가 한 줄, 그 아래 비슷한 선수가 오므로 크림이 세로로 겹치지 않게 라벤더
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
    cards = soup.select("main section.card")  # 순위표는 무대(.stage) 안, 나머지는 .teams-stack 안 — 문서 순서로 센다
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
    assert re.search(r'fetchJSON\((?:"rewind/2026/index\.json"|`rewind/\$\{REWIND_SEASON\}/index\.json`), \{ fresh: true \}\)', js)
    assert "const REWIND_SEASON = 2026;" in js
    assert "history.replaceState" in js and "teamNameFor" in js
    assert re.search(r'import\s*\{[^}]*\btypeColor\b[^}]*\}\s*from\s*"\./app\.js"', js)
    assert not re.search(r"\b(?:const|let|var)\s+(?:TYPE_COLORS|TEAMS)\b", js)  # 색·팀은 app.js 하나뿐
    assert 'fetchJSON("players.json")' not in js  # 1.77 MB — 유형 이름은 model_report.json에서


def test_check_site_strict_passes_all_pages():
    """저장소 site/는 --strict로 통과한다: 페이지 4개 모두 nav·#evidence·resources OK, 홈 ?fixture=edge OK, SKIP·FAIL 없음."""
    r = _run_check("--strict")
    assert r.returncode == 0, r.stdout + r.stderr
    for page in check_site.PAGES:
        for check in ("parse", "nav", "#evidence", "resources"):
            assert re.search(rf"\| {re.escape(check)}\s+\| {re.escape(page)}\s+\| OK", r.stdout), (check, page, r.stdout)
    assert re.search(r"\| fixture-mode\s+\| index\.html\s+\| OK", r.stdout), r.stdout
    assert re.search(r"\| assets\s+\| assets/\s+\| OK", r.stdout), r.stdout
    assert "| SKIP" not in r.stdout and not re.search(r"\| FAIL\s*\|", r.stdout), r.stdout


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


# ---------- Genspark 내보내기 반영 (scripts/import_site.py) ----------

BEACON = ('<script defer src="https://static.cloudflareinsights.com/beacon.min.js/vcd15cbe7772f49c399c6a5babf22c1241717689176015"'
          ' integrity="sha512-ZpsOmlRQV6y907TI0dKBHq9Md29nnaEIPlkf84rnaERnq6zvWvPUqr2ft8M1aS28oN72PdrCzSjY4U6VaAw1EQ=="'
          ' data-cf-beacon=\'{"rayId":"9a1b2c3d","version":"2025.9.1","token":"abc>def"}\' crossorigin="anonymous"></script>')


def _export_dir(tmp_path: Path) -> Path:
    """가짜 Genspark 내보내기: 저장소 index.html에 beacon + file:// 경로를 넣고, 성적표는 제목만 맞는 다른 이름의 단일 파일."""
    export = tmp_path / "export" / "genspark-kbo"   # zip 안 최상위 폴더 하나
    export.mkdir(parents=True)
    index = (SITE / "index.html").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" in index and "cdn.jsdelivr.net/gh/orioncactus/pretendard@" in index  # 허용 폰트 링크
    index = index.replace("</body>", BEACON + "\n</body>")
    index = index.replace('href="assets/home.css"', 'href="file:///C:/Users/me/Downloads/genspark-kbo/assets/home.css"')
    (export / "index.html").write_text(index, encoding="utf-8")
    report = (SITE / "report.html").read_text(encoding="utf-8").replace("</head>", BEACON + "\n</head>")
    (export / "KBO Predict export (2).html").write_text(report, encoding="utf-8")
    (export / "data-snapshot.json").write_text("{}", encoding="utf-8")  # 데이터 사본은 반영하지 않음
    return export


def _zip(folder: Path, dest: Path) -> Path:
    import zipfile
    with zipfile.ZipFile(dest, "w") as zf:
        for p in folder.rglob("*"):
            zf.write(p, p.relative_to(folder.parent).as_posix())
    return dest


def test_import_site_strips_beacon(tmp_path, capsys):
    """zip을 반영하면 beacon은 지워지고 허용 폰트 링크는 남으며, file:// 경로는 상대 경로가 되고, 제목으로 페이지를 찾는다.
    반영 전 site/는 백업되고 check_site(--strict)를 통과한다. dry-run은 site/를 건드리지 않는다."""
    from scripts import import_site
    site = _tmp_site(tmp_path)
    before = (site / "index.html").read_text(encoding="utf-8")
    archive = _zip(_export_dir(tmp_path), tmp_path / "genspark.zip")
    backups = tmp_path / "backups"

    assert import_site.main([str(archive), "--site", str(site), "--backup-root", str(backups), "--dry-run"]) == 0
    assert (site / "index.html").read_text(encoding="utf-8") == before and not backups.exists()

    assert import_site.main([str(archive), "--site", str(site), "--backup-root", str(backups)]) == 0
    out = capsys.readouterr().out
    for page in ("index.html", "report.html"):
        html = (site / page).read_text(encoding="utf-8")
        assert "cloudflareinsights" not in html and "data-cf-beacon" not in html, page
        assert "https://fonts.googleapis.com/css2?family=Inter" in html, page
        assert "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@" in html, page
    assert 'href="assets/home.css"' in (site / "index.html").read_text(encoding="utf-8")
    assert "file:" not in (site / "index.html").read_text(encoding="utf-8")
    assert "KBO Predict export (2).html → report.html" in out and "PASS" in out
    assert not (site / "data-snapshot.json").exists() and "data-snapshot.json" in out
    [backup] = list(backups.iterdir())
    assert backup.name.startswith("site-backup-")
    assert (backup / "index.html").read_text(encoding="utf-8") == before
    rows = check_site.run(site, DATA, ROOT / "docs" / "site" / "data-contract.md", strict=True)
    assert not [r for r in rows if r.result == "FAIL"]


def test_import_site_restores_on_failure(tmp_path):
    """반영본이 검증에 실패하면(허용 밖 외부 이미지) exit 1이고 site/는 백업으로 되돌아간다. --keep이면 남긴다."""
    from scripts import import_site
    site = _tmp_site(tmp_path)
    before = (site / "teams.html").read_text(encoding="utf-8")
    bad = tmp_path / "teams-export.html"
    bad.write_text(before.replace("</main>", '<img src="https://images.genspark.ai/x.png" alt=""></main>'),
                   encoding="utf-8")
    args = [str(bad), "--as", "teams.html", "--site", str(site), "--backup-root", str(tmp_path / "bk")]
    assert import_site.main(args) == 1
    assert (site / "teams.html").read_text(encoding="utf-8") == before
    assert import_site.main([*args, "--keep"]) == 1
    assert "images.genspark.ai" in (site / "teams.html").read_text(encoding="utf-8")


def test_import_site_skips_hidden_zip_entries(tmp_path, capsys):
    """macOS zip의 __MACOSX/._index.html·.DS_Store 같은 숨김 항목은 건너뛰고 알린다(반영은 계속). 절대 경로·'..'만 멈춘다(exit 2)."""
    import zipfile
    from scripts import import_site
    site = _tmp_site(tmp_path)
    archive = _zip(_export_dir(tmp_path), tmp_path / "mac.zip")
    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr("__MACOSX/genspark-kbo/._index.html", b"\x00\x05\x16\x07 AppleDouble")
        zf.writestr("genspark-kbo/.DS_Store", b"\x00\x00\x00\x01Bud1")
    args = [str(archive), "--site", str(site), "--backup-root", str(tmp_path / "bk")]
    assert import_site.main(args) == 0
    out = capsys.readouterr().out
    assert "건너뜀: __MACOSX/genspark-kbo/._index.html" in out and "건너뜀: genspark-kbo/.DS_Store" in out
    assert "KBO Predict export (2).html → report.html" in out  # 최상위 폴더 하나를 벗기는 규칙도 그대로
    assert not (site / "__MACOSX").exists() and not (site / ".DS_Store").exists()
    assert "cloudflareinsights" not in (site / "index.html").read_text(encoding="utf-8")

    for bad in ("../evil.html", "/abs/index.html"):
        evil = tmp_path / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("index.html", "<!doctype html><title>x</title>")
            zf.writestr(bad, "x")
        assert import_site.main([str(evil), "--site", str(site), "--backup-root", str(tmp_path / "bk2")]) == 2, bad
        assert "받을 수 없음" in capsys.readouterr().out
