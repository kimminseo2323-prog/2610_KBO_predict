"""정적 사이트(site/) 검증. 네트워크 없음 — 커밋된 data/public/와 파이썬 원본만 읽는다.

검사 항목 (결과 표 + exit code: FAIL이 하나라도 있으면 1):
  (1) 페이지 4개(index/teams/players/report.html): 존재·기본 구조(doctype, lang, title, viewport),
      <nav> 안 내부 링크 4개가 정해진 순서·이름이고 자기 페이지에 aria-current="page", "GitHub에서 보기" 링크, #evidence,
      외부 리소스는 허용 목록(Google Fonts, jsDelivr의 Pretendard)만, <script src>는 assets/ 상대 경로만(파일 존재),
      인라인·assets JS의 import는 상대 경로만, assets CSS의 @import/url()도 외부 금지, 트래킹 스크립트 금지.
  (2) assets/app.js의 TEAMS(ko)·FACTOR_LABELS·TYPE_COLORS가 파이썬 원본(teams.py, features.py, cluster_labels.yaml)과 같다.
  (3) docs/site/data-contract.md 매핑 표(| 페이지 | 요소 | 파일 | 키 경로 |)의 키 경로가 샘플 파일에 실제로 있다.
      되감기 날짜 파일은 rewind/2026/index.json의 마지막 날짜 파일로 확인한다.
  (4) --strict: index.html(또는 그 페이지의 assets 스크립트)이 ?fixture=edge 를 지원하고 fixture 파일이 있다.

사용:
  python -X utf8 scripts/check_site.py [--site site] [--data data/public] [--contract docs/site/data-contract.md]
                                       [--strict] [--allow-missing-pages]
--allow-missing-pages: 아직 없는 페이지를 FAIL 대신 SKIP으로 센다 (페이지가 Task 2~5에서 생기기 전 단계용).
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/kimminseo2323-prog/2610_KBO_predict"
PAGES = ["index.html", "teams.html", "players.html", "report.html"]
NAV = [("index.html", "오늘의 경기"), ("teams.html", "팀"), ("players.html", "선수"), ("report.html", "모델 성적표")]
ALLOWED_PREFIXES = (
    "fonts.googleapis.com/",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net/gh/orioncactus/pretendard",
)
TRACKERS = re.compile(r"cloudflareinsights|googletagmanager|google-analytics|gtag\(|beacon\.min\.js|hotjar|clarity\.ms",
                      re.I)
ABSOLUTE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.I)
FIXTURE = ROOT / "tests" / "fixtures" / "site" / "latest_edge.json"
# 리소스를 불러오는 태그·속성 (<a href>는 이동 링크라 제외)
RESOURCE_ATTRS = [("script", "src"), ("link", "href"), ("img", "src"), ("img", "srcset"), ("iframe", "src"),
                  ("source", "src"), ("source", "srcset"), ("video", "src"), ("video", "poster"), ("audio", "src"),
                  ("embed", "src"), ("object", "data"), ("track", "src")]


@dataclass
class Row:
    check: str
    target: str
    result: str  # OK / FAIL / SKIP
    detail: str = ""


@dataclass
class ContractRow:
    page: str
    element: str
    file: str
    keys: list[str]


# ---------- 공용 도우미 ----------

def parse_js_const(js: str, name: str):
    """`export const NAME = { … };`의 객체 리터럴을 JSON으로 읽는다 (app.js는 이 상수들을 JSON 문법으로 쓴다)."""
    m = re.search(rf"export\s+const\s+{re.escape(name)}\s*=\s*", js)
    if not m:
        raise KeyError(name)
    i = js.index("{", m.end())
    depth, j, in_str = 0, i, False
    while j < len(js):
        ch = js[j]
        if in_str:
            if ch == "\\":
                j += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(js[i:j + 1])
        j += 1
    raise ValueError(f"unterminated object for {name}")


def py_literal(path: Path, name: str):
    """파이썬 파일을 import하지 않고 최상위 `name = …` 리터럴 값을 읽는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


_SEG = re.compile(r"^([A-Za-z0-9_]+)?((?:\[\]|\{\})*)$")


def key_exists(obj, path: str) -> bool:
    """점 경로가 obj 안에 하나라도 있는가. `[]` = 배열 각 원소, `{}` = 정해지지 않은 키의 각 값. 값이 null이어도 키가 있으면 참."""
    values = [obj]
    for seg in path.split("."):
        m = _SEG.match(seg)
        if not m:
            raise ValueError(f"bad key path segment {seg!r} in {path!r}")
        name, suffix = m.group(1), m.group(2)
        if name is not None:
            values = [v[name] for v in values if isinstance(v, dict) and name in v]
        for op in re.findall(r"\[\]|\{\}", suffix):
            if op == "[]":
                values = [x for v in values if isinstance(v, list) for x in v]
            else:
                values = [x for v in values if isinstance(v, dict) for x in v.values()]
        if not values:
            return False
    return True


def contract_rows(md: str) -> list[ContractRow]:
    """data-contract.md에서 머리글이 `| 페이지 | 요소 | 파일 | 키 경로 |`인 표의 행을 읽는다. 셀 안의 `백틱` 토큰이 파일·키."""
    rows, in_table = [], False
    for line in md.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells[:4] == ["페이지", "요소", "파일", "키 경로"]:
            in_table = True
            continue
        if not in_table or set("".join(cells)) <= set("-: "):
            continue
        files = re.findall(r"`([^`]+)`", cells[2])
        keys = re.findall(r"`([^`]+)`", cells[3])
        if len(files) != 1 or not keys:
            raise ValueError(f"bad contract row: {line}")
        rows.append(ContractRow(cells[0], cells[1], files[0], keys))
    return rows


def _sample(data: Path, file: str, cache: dict):
    """매핑 표의 파일 이름 → 샘플 데이터(JSON 객체 또는 CSV 머리글 집합)."""
    if file in cache:
        return cache[file]
    if file == "rewind/2026/{date}.json":
        index = json.loads((data / "rewind" / "2026" / "index.json").read_text(encoding="utf-8"))
        path = data / "rewind" / "2026" / f"{index['dates'][-1]['date']}.json"
    else:
        path = data / file
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as f:
            value = set(next(csv.reader(f)))
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
    cache[file] = value
    return value


def check_contract_keys(rows: list[ContractRow], data: Path):
    """[(row, key, 있음?)]. 파일이 없으면 그 행의 키는 모두 없음."""
    out, cache = [], {}
    for r in rows:
        try:
            sample = _sample(data, r.file, cache)
        except (OSError, ValueError, KeyError, IndexError, StopIteration):
            out.extend((r, k, False) for k in r.keys)
            continue
        for k in r.keys:
            ok = k in sample if isinstance(sample, set) else key_exists(sample, k)
            out.append((r, k, ok))
    return out


# ---------- (1) 페이지 ----------

def _allowed(url: str) -> bool:
    bare = re.sub(r"^(?:https?:)?//", "", url, flags=re.I)
    return url.lower().startswith(("https:", "//")) and bare.startswith(ALLOWED_PREFIXES)


def _imports(js: str) -> list[str]:
    return re.findall(r"""(?:\bfrom\s*|\bimport\s*\(?\s*)["']([^"']+)["']""", js)


def check_page(site: Path, page: str) -> list[Row]:
    rows: list[Row] = []
    path = site / page
    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    fail = lambda check, detail: rows.append(Row(check, page, "FAIL", detail))  # noqa: E731

    problems = []
    if not re.match(r"\s*<!doctype html>", html, re.I):
        problems.append("<!doctype html> 없음")
    if not (soup.html and soup.html.get("lang")):
        problems.append("<html lang> 없음")
    if not (soup.title and soup.title.get_text(strip=True)):
        problems.append("<title> 비어 있음")
    if not soup.find("meta", attrs={"name": "viewport"}):
        problems.append("viewport meta 없음")
    rows.append(Row("parse", page, "FAIL" if problems else "OK", "; ".join(problems)))

    nav = soup.find("nav")
    if not nav:
        fail("nav", "<nav> 없음")
    else:
        links = [a for a in nav.find_all("a", href=True) if not ABSOLUTE.match(a["href"])]
        got = [(a["href"], a.get_text(strip=True)) for a in links]
        current = [a["href"] for a in links if a.get("aria-current") == "page"]
        if got != NAV:
            fail("nav", f"내부 링크 {got} != {NAV}")
        elif current != [page]:
            fail("nav", f'aria-current="page"가 {current} (기대: {page})')
        else:
            rows.append(Row("nav", page, "OK", "링크 4개 순서·aria-current"))
    gh = [a for a in soup.find_all("a", href=True) if a["href"].rstrip("/") == REPO_URL]
    if not any("GitHub에서 보기" in a.get_text(strip=True) for a in gh):
        fail("github-link", f'"GitHub에서 보기" → {REPO_URL} 링크 없음')
    if soup.find(id="evidence") is None:
        fail("#evidence", "푸터 증거 바 #evidence 없음")
    else:
        rows.append(Row("#evidence", page, "OK"))

    bad = []
    for tag, attr in RESOURCE_ATTRS:
        for node in soup.find_all(tag):
            val = node.get(attr)
            if not val:
                continue
            for url in [u.strip().split(" ")[0] for u in val.split(",")] if attr == "srcset" else [val.strip()]:
                if url.lower().startswith(("file:", "data:text/html", "javascript:")):
                    bad.append(f"<{tag} {attr}={url}>")
                elif ABSOLUTE.match(url) and not (tag != "script" and _allowed(url)):
                    bad.append(f"<{tag} {attr}={url}>")
    for script in soup.find_all("script"):
        src = script.get("src")
        if src is not None and not ABSOLUTE.match(src):
            clean = src.split("?")[0].removeprefix("./")
            if not clean.startswith("assets/") or ".." in clean:
                bad.append(f"<script src={src}> (assets/ 상대 경로만)")
            elif not (site / clean).exists():
                bad.append(f"<script src={src}> 파일 없음")
        if src is None:
            body = script.string or ""
            bad += [f"inline import {u}" for u in _imports(body) if not u.startswith(("./assets/", "assets/"))]
            if TRACKERS.search(body):
                bad.append("inline 트래킹 코드")
    for link in soup.find_all("link", href=True):
        href = link["href"]
        if not ABSOLUTE.match(href) and "stylesheet" in (link.get("rel") or []):
            if not (site / href.split("?")[0]).exists():
                bad.append(f"<link href={href}> 파일 없음")
    if TRACKERS.search(html) and not any("트래킹" in b for b in bad):
        bad.append("트래킹 코드")
    rows.append(Row("resources", page, "FAIL" if bad else "OK", "; ".join(bad) if bad else "외부는 폰트 CSS만"))
    return rows


def check_assets(site: Path) -> list[Row]:
    """assets/*.js의 import는 상대 경로만, assets/*.css의 @import·url()은 외부 금지, 트래킹 금지."""
    bad = []
    assets = site / "assets"
    for js in sorted(assets.glob("**/*.js")):
        text = js.read_text(encoding="utf-8")
        bad += [f"{js.name}: import {u}" for u in _imports(text) if not u.startswith(("./", "../"))]
        if TRACKERS.search(text):
            bad.append(f"{js.name}: 트래킹 코드")
    for css in sorted(assets.glob("**/*.css")):
        text = css.read_text(encoding="utf-8")
        for url in re.findall(r"""(?:@import\s+(?:url\()?|url\()\s*["']?([^"')\s;]+)""", text):
            if ABSOLUTE.match(url) and not _allowed(url):
                bad.append(f"{css.name}: {url}")
    return [Row("assets", "assets/", "FAIL" if bad else "OK", "; ".join(bad) if bad else "JS import·CSS url 모두 로컬")]


# ---------- (2) 파이썬 원본과 같은 상수 ----------

def check_constants(site: Path) -> list[Row]:
    rows = []
    app = site / "assets" / "app.js"
    if not app.exists():
        return [Row("constants", "assets/app.js", "FAIL", "app.js 없음")]
    js = app.read_text(encoding="utf-8")
    py_teams = py_literal(ROOT / "src" / "kbo_predict" / "teams.py", "TEAMS")
    expected = {}
    for info in py_teams.values():
        expected.setdefault(info["code"], info["ko"])
    try:
        got = {code: t.get("ko") for code, t in parse_js_const(js, "TEAMS").items()}
        rows.append(Row("TEAMS", "assets/app.js", "OK" if got == expected else "FAIL",
                        "teams.py와 같음" if got == expected else f"{got} != {expected}"))
    except (KeyError, ValueError) as e:
        rows.append(Row("TEAMS", "assets/app.js", "FAIL", f"읽기 실패: {e}"))
    try:
        labels = parse_js_const(js, "FACTOR_LABELS")
        py_labels = py_literal(ROOT / "src" / "kbo_predict" / "features.py", "FACTOR_LABELS")
        rows.append(Row("FACTOR_LABELS", "assets/app.js", "OK" if labels == py_labels else "FAIL",
                        f"{len(labels)}개, features.py와 같음" if labels == py_labels else "features.py와 다름"))
    except (KeyError, ValueError) as e:
        rows.append(Row("FACTOR_LABELS", "assets/app.js", "FAIL", f"읽기 실패: {e}"))
    try:
        import yaml
        colors = parse_js_const(js, "TYPE_COLORS")
        labels_yaml = yaml.safe_load((ROOT / "config" / "cluster_labels.yaml").read_text(encoding="utf-8"))
        ok = all({int(k) for k in colors.get(g, {})} == set(labels_yaml[g]) for g in ("batter", "pitcher"))
        rows.append(Row("TYPE_COLORS", "assets/app.js", "OK" if ok else "FAIL",
                        "유형 id가 cluster_labels.yaml과 같음" if ok else "유형 id가 cluster_labels.yaml과 다름"))
    except (KeyError, ValueError) as e:
        rows.append(Row("TYPE_COLORS", "assets/app.js", "FAIL", f"읽기 실패: {e}"))
    return rows


# ---------- (3) 데이터 계약 ----------

def check_contract(contract: Path, data: Path) -> list[Row]:
    if not contract.exists():
        return [Row("contract", str(contract), "FAIL", "데이터 계약 문서 없음")]
    try:
        rows = contract_rows(contract.read_text(encoding="utf-8"))
    except ValueError as e:
        return [Row("contract", contract.name, "FAIL", str(e))]
    if not rows:
        return [Row("contract", contract.name, "FAIL", "매핑 표(| 페이지 | 요소 | 파일 | 키 경로 |)를 찾지 못함")]
    results = check_contract_keys(rows, data)
    out = []
    by_file: dict[str, list] = {}
    for r, k, ok in results:
        by_file.setdefault(r.file, []).append((r, k, ok))
    for file, items in by_file.items():
        missing = [f"{r.page}/{r.element}: {k}" for r, k, ok in items if not ok]
        out.append(Row("contract-keys", file, "FAIL" if missing else "OK",
                       "; ".join(missing) if missing else f"키 {len(items)}개 모두 있음"))
    return out


# ---------- (4) --strict ----------

def check_fixture_mode(site: Path) -> list[Row]:
    index = site / "index.html"
    if not index.exists():
        return [Row("fixture-mode", "index.html", "FAIL", "index.html 없음")]
    soup = BeautifulSoup(index.read_text(encoding="utf-8"), "html.parser")
    texts = [index.read_text(encoding="utf-8")]
    for s in soup.find_all("script", src=True):
        p = site / s["src"].split("?")[0].removeprefix("./")
        if p.exists():
            texts.append(p.read_text(encoding="utf-8"))
    joined = "\n".join(texts)
    for path in sorted((site / "assets").glob("*.js")):  # 인라인 모듈이 import하는 스크립트까지
        if re.search(rf"""["']\.?/?(?:assets/)?{re.escape(path.name)}["']""", joined):
            joined += "\n" + path.read_text(encoding="utf-8")
    ok = "fixture" in joined and "latest_edge" in joined and FIXTURE.exists()
    return [Row("fixture-mode", "index.html", "OK" if ok else "FAIL",
                "?fixture=edge 지원" if ok else "?fixture=edge 처리 또는 tests/fixtures/site/latest_edge.json 없음")]


# ---------- 실행 ----------

def run(site: Path, data: Path, contract: Path, *, strict: bool = False, allow_missing_pages: bool = False) -> list[Row]:
    rows: list[Row] = []
    for page in PAGES:
        if not (site / page).exists():
            rows.append(Row("page", page, "SKIP" if allow_missing_pages else "FAIL", "missing page"))
            continue
        rows.extend(check_page(site, page))
    rows.extend(check_assets(site))
    rows.extend(check_constants(site))
    rows.extend(check_contract(contract, data))
    if strict:
        rows.extend(check_fixture_mode(site))
    else:
        rows.append(Row("fixture-mode", "index.html", "SKIP", "--strict일 때만"))
    return rows


def format_table(rows: list[Row]) -> str:
    head = ("검사", "대상", "결과", "내용")
    w = [max(len(head[i]), *(len(getattr(r, f)) for r in rows)) for i, f in enumerate(("check", "target", "result"))]
    lines = [f"| {head[0]:<{w[0]}} | {head[1]:<{w[1]}} | {head[2]:<{w[2]}} | {head[3]}",
             f"|-{'-' * w[0]}-|-{'-' * w[1]}-|-{'-' * w[2]}-|-----"]
    lines += [f"| {r.check:<{w[0]}} | {r.target:<{w[1]}} | {r.result:<{w[2]}} | {r.detail}" for r in rows]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="정적 사이트(site/) 검증")
    ap.add_argument("--site", default=str(ROOT / "site"))
    ap.add_argument("--data", default=str(ROOT / "data" / "public"))
    ap.add_argument("--contract", default=str(ROOT / "docs" / "site" / "data-contract.md"))
    ap.add_argument("--strict", action="store_true", help="index.html의 ?fixture=edge 지원까지 확인")
    ap.add_argument("--allow-missing-pages", action="store_true", help="없는 페이지를 FAIL 대신 SKIP으로")
    args = ap.parse_args(argv)
    rows = run(Path(args.site), Path(args.data), Path(args.contract),
               strict=args.strict, allow_missing_pages=args.allow_missing_pages)
    print(format_table(rows))
    n_fail = sum(r.result == "FAIL" for r in rows)
    n_skip = sum(r.result == "SKIP" for r in rows)
    print(f"\n{'FAIL' if n_fail else 'PASS'}: OK {sum(r.result == 'OK' for r in rows)}, FAIL {n_fail}, SKIP {n_skip}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
