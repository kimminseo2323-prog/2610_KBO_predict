"""정적 사이트(site/) 검증. 네트워크 없음 — 커밋된 data/public/와 파이썬 원본만 읽는다.

검사 항목 (결과 표 + exit code: FAIL이 하나라도 있으면 1):
  (1) 페이지 4개(index/teams/players/report.html): 존재·기본 구조(doctype, lang, title, viewport),
      <nav> 안 내부 링크 4개가 정해진 순서·이름이고 자기 페이지에 aria-current="page", "GitHub에서 보기" 링크, #evidence,
      외부 리소스는 허용 목록(https, 호스트 정확히 일치: fonts.googleapis.com, fonts.gstatic.com, cdn.jsdelivr.net/gh/orioncactus/pretendard@…)만, <script src>는 assets/ 상대 경로만(파일 존재),
      인라인·assets JS의 import는 상대 경로만, JS 문자열 속 https:// 주소는 허용 목록·RAW_BASE(데이터)·REPO_URL(과 커밋 링크)만,
      페이지가 연결한 로컬 스타일시트(경로 무관)·assets CSS·인라인 <style>·style= 의 @import/url()도 외부 금지, 트래킹 스크립트 금지.
  (2) assets/app.js의 TEAMS(ko)·FACTOR_LABELS·TYPE_COLORS가 파이썬 원본(teams.py, features.py, cluster_labels.yaml)과 같다.
  (3) docs/site/data-contract.md 매핑 표(| 페이지 | 요소 | 파일 | 키 경로 |)의 키 경로가 샘플 파일에 실제로 있다.
      되감기 날짜 파일은 rewind/2026/index.json의 마지막 날짜 파일로 확인한다.
  (4) --strict: index.html의 스크립트(인라인, 또는 그 페이지가 불러오는 assets 스크립트)의 주석 아닌 코드에
      ?fixture=edge 처리(.get("fixture"), === "edge", fixture 폴더와 latest_edge.json 경로)가 있고 fixture 파일이 있다.

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
from urllib.parse import urlsplit
import sys
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/kimminseo2323-prog/2610_KBO_predict"
RAW_BASE = "https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public"
PAGES = ["index.html", "teams.html", "players.html", "report.html"]
NAV = [("index.html", "오늘의 경기"), ("teams.html", "팀"), ("players.html", "선수"), ("report.html", "모델 성적표")]
# 허용하는 외부 리소스: https + 호스트 정확히 일치 + (jsDelivr는) 경로 접두사. 그 밖의 외부 리소스는 모두 금지.
ALLOWED = {
    "fonts.googleapis.com": "/",                              # Inter 글꼴 CSS
    "fonts.gstatic.com": "",                                  # 글꼴 파일 (preconnect)
    "cdn.jsdelivr.net": "/gh/orioncactus/pretendard@",        # Pretendard 글꼴 CSS
}
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
        if not seg or not m:
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
            try:
                ok = k in sample if isinstance(sample, set) else key_exists(sample, k)
            except ValueError:  # 잘못 쓴 키 경로 (빈 칸 등)
                ok = False
            out.append((r, k, ok))
    return out


# ---------- (1) 페이지 ----------

def _allowed(url: str) -> bool:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() != "https" or parts.username or parts.password or parts.port:
        return False
    prefix = ALLOWED.get((parts.hostname or "").lower())
    return prefix is not None and parts.path.startswith(prefix)


_CSS_URL = re.compile(r"""(?:@import\s+(?:url\()?|url\()\s*["']?([^"')\s;]+)""", re.I)


def _css_external(text: str) -> list[str]:
    """CSS 텍스트 안의 @import·url() 중 허용 목록 밖의 외부 주소."""
    return [u for u in _CSS_URL.findall(text) if ABSOLUTE.match(u) and not _allowed(u)]


def _imports(js: str) -> list[str]:
    return re.findall(r"""(?:\bfrom\s*|\bimport\s*\(?\s*)["']([^"']+)["']""", js)


# ---------- JS 토큰 나누기 (주석·문자열·정규식 리터럴 구분, 외부 의존 없이 어림) ----------

_REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = {"return", "typeof", "case", "in", "of", "void", "delete", "instanceof", "new", "else", "do"}


@dataclass
class JsScan:
    code: str            # 주석만 뺀 코드 (문자열은 그대로)
    skeleton: str        # 주석을 빼고 문자열·템플릿·정규식 리터럴을 ""·/r/로 바꾼 코드 (괄호 짝 맞추기용)
    strings: list[str]   # 문자열 리터럴과 템플릿 리터럴의 글자 부분


def _skip_string(src: str, i: int) -> int:
    """src[i]가 따옴표일 때, 닫는 따옴표 다음 위치."""
    q, j = src[i], i + 1
    while j < len(src) and src[j] != q and src[j] != "\n":
        j += 2 if src[j] == "\\" else 1
    return j + 1


def _skip_template(src: str, i: int, parts: list[str]) -> int:
    """src[i]가 `일 때, 닫는 ` 다음 위치. ${…} 안의 중첩 템플릿까지 건너뛰고, 글자 부분은 parts에 모은다."""
    j, start = i + 1, i + 1
    while j < len(src):
        ch = src[j]
        if ch == "\\":
            j += 2
        elif ch == "`":
            parts.append(src[start:j])
            return j + 1
        elif src.startswith("${", j):
            parts.append(src[start:j])
            depth, j = 1, j + 2
            while j < len(src) and depth:
                c = src[j]
                if c in "\"'":
                    parts.append(src[j + 1:_skip_string(src, j) - 1])
                    j = _skip_string(src, j)
                    continue
                if c == "`":
                    j = _skip_template(src, j, parts)
                    continue
                depth += {"{": 1, "}": -1}.get(c, 0)
                j += 1
            start = j
        else:
            j += 1
    parts.append(src[start:])
    return len(src)


def scan_js(src: str) -> JsScan:
    """JS를 한 번 훑어 주석을 빼고 문자열·정규식 리터럴을 구분한다. 정규식은 앞 글자(연산자·여는 괄호·return 등)로 어림한다."""
    code, skel, strings = [], [], []
    i, n, prev, word = 0, len(src), "", ""
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in "\"'":
            j = _skip_string(src, i)
            strings.append(src[i + 1:j - 1])
            code.append(src[i:j]); skel.append('""')
            i, prev, word = j, '"', ""
            continue
        if c == "`":
            parts: list[str] = []
            j = _skip_template(src, i, parts)
            strings.append("".join(parts))
            code.append(src[i:j]); skel.append('""')
            i, prev, word = j, '"', ""
            continue
        if c == "/" and (prev == "" or prev in _REGEX_BEFORE or (prev.isalpha() and word in _REGEX_KEYWORDS)):
            j, in_class = i + 1, False
            while j < n and src[j] != "\n":
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    break
                j += 1
            j += 1
            while j < n and src[j].isalpha():
                j += 1
            code.append(src[i:j]); skel.append("/r/")
            i, prev, word = j, "/", ""
            continue
        code.append(c); skel.append(c)
        if c.isalnum() or c in "_$":
            word = word + c if i and (src[i - 1].isalnum() or src[i - 1] in "_$") else c
        elif not c.isspace():
            word = ""
        if not c.isspace():
            prev = c
        i += 1
    return JsScan("".join(code), "".join(skel), strings)


def js_external_urls(src: str) -> list[str]:
    """JS 문자열 리터럴 안의 https:// 주소 중 허용 밖인 것. 허용: 글꼴(ALLOWED), RAW_BASE 아래 데이터, REPO_URL과 그 커밋 링크."""
    bad = []
    for s in scan_js(src).strings:
        for url in re.findall(r"https://[^\s\"'`<>()]+", s):
            ok = (_allowed(url) or url.startswith(RAW_BASE) or url.rstrip("/") == REPO_URL
                  or url.startswith(f"{REPO_URL}/commit/"))
            if not ok:
                bad.append(url)
    return bad


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
            bad += [f"inline JS 주소 {u}" for u in js_external_urls(body)]
            if TRACKERS.search(body):
                bad.append("inline 트래킹 코드")
    for link in soup.find_all("link", href=True):
        href = link["href"]
        if not ABSOLUTE.match(href) and "stylesheet" in (link.get("rel") or []):
            css = site / href.split("?")[0].split("#")[0]
            if not css.is_file():
                bad.append(f"<link href={href}> 파일 없음")
            else:  # 경로와 상관없이 페이지가 연결한 로컬 스타일시트 전부
                bad += [f"{href}: {u}" for u in _css_external(css.read_text(encoding="utf-8"))]
    for style in soup.find_all("style"):
        bad += [f"<style> {u}" for u in _css_external(style.get_text())]
    for node in soup.find_all(style=True):
        bad += [f"style= {u}" for u in _css_external(node["style"])]
    if TRACKERS.search(html) and not any("트래킹" in b for b in bad):
        bad.append("트래킹 코드")
    rows.append(Row("resources", page, "FAIL" if bad else "OK", "; ".join(bad) if bad else "외부는 폰트 CSS만"))
    return rows


def check_assets(site: Path) -> list[Row]:
    """assets/*.js의 import는 상대 경로만, 문자열 속 https:// 주소는 허용 목록·데이터·저장소 링크만,
    assets/*.css의 @import·url()은 외부 금지, 트래킹 금지."""
    bad = []
    assets = site / "assets"
    for js in sorted(assets.glob("**/*.js")):
        text = js.read_text(encoding="utf-8")
        bad += [f"{js.name}: import {u}" for u in _imports(text) if not u.startswith(("./", "../"))]
        bad += [f"{js.name}: 주소 {u}" for u in js_external_urls(text)]
        if TRACKERS.search(text):
            bad.append(f"{js.name}: 트래킹 코드")
    for css in sorted(assets.glob("**/*.css")):
        text = css.read_text(encoding="utf-8")
        bad += [f"{css.name}: {u}" for u in _css_external(text)]
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
    for tag in soup.find_all("script", src=False):  # 인라인 스크립트
        texts.append(tag.string or "")
    joined = "\n".join(texts[1:])
    for path in sorted((site / "assets").glob("*.js")):  # 인라인 모듈이 import하는 스크립트까지
        if re.search(rf"""["']\.?/?(?:assets/)?{re.escape(path.name)}["']""", joined):
            joined += "\n" + path.read_text(encoding="utf-8")
    # 주석이 아닌 코드에 실제 처리 패턴이 있어야 한다: ?fixture 읽기, === "edge" 비교, fixture 폴더와 latest_edge.json 경로
    code = scan_js(joined).code
    need = {
        '.get("fixture")': r"""\.get\(\s*["']fixture["']\s*\)""",
        '=== "edge"': r"""===\s*["']edge["']""",
        '"latest_edge.json"': r"""["'`](?:[./\w-]*/)?latest_edge\.json["'`]""",
        '"…tests/fixtures/site"': r"""["'`][./]*tests/fixtures/site/?["'`]""",
    }
    missing = [name for name, pat in need.items() if not re.search(pat, code)]
    if not FIXTURE.exists():
        missing.append("tests/fixtures/site/latest_edge.json 파일")
    return [Row("fixture-mode", "index.html", "FAIL" if missing else "OK",
                f"?fixture=edge 처리 없음: {', '.join(missing)}" if missing else "?fixture=edge 지원")]


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
