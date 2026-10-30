"""Genspark(또는 다른 도구)에서 내보낸 사이트를 site/에 반영한다.

순서:
  1. 입력 읽기 — zip, 폴더, 단일 .html 하나. zip 안에 최상위 폴더 하나만 있으면 그 안을 루트로 본다.
     숨김 파일(.DS_Store, .nojekyll 등)과 __MACOSX/는 건너뛰고 알린다. zip 안의 절대 경로·'..'는 반영을 멈춘다(exit 2).
  2. 페이지 이름 정하기 — 파일 이름이 index/teams/players/report.html이면 그대로, 아니면 <title>의 낱말로
     (성적표 → report, 선수 → players, 오늘의 경기 → index, 팀 → teams). 단일 파일은 --as index.html 로 직접 정할 수 있다.
  3. 정리 — 허용 목록(check_site.ALLOWED: fonts.googleapis.com, fonts.gstatic.com, cdn.jsdelivr.net/gh/orioncactus/pretendard@…)
     밖의 외부 <script>·<link>를 지운다(예: Genspark 내보내기에 붙는 Cloudflare beacon). 트래킹 코드가 든 인라인 <script>도 지운다.
     src/href의 file:// 절대 경로와 "/"로 시작하는 루트 경로는 상대 경로로 바꾼다(Pages는 /2610_KBO_predict/ 아래에서 열린다).
  4. 반영 — 지금 site/를 artifacts/site-backup-<시각>/에 통째로 복사해 두고(gitignore), 정리한 파일을 site/ 위에 덮어쓴다.
     내보내기에 없는 기존 파일(assets/ 등)은 그대로 둔다.
  5. 검증 — check_site.run(--strict와 같음). 실패하면 백업으로 site/를 되돌리고(--keep이면 남겨 둠) exit 1.

사용:
  python -X utf8 scripts/import_site.py <zip|폴더|파일.html> [--as index.html] [--dry-run] [--keep]
                                        [--site site] [--backup-root artifacts]
--dry-run: site/를 건드리지 않고 임시 복사본에 반영·검증만 해서 보고한다(백업도 만들지 않음).
--keep: 검증이 실패해도 반영한 site/를 남겨 둔다(원인 확인용, 백업은 그대로 있음).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_site  # noqa: E402

PAGES = check_site.PAGES
# <title> 안의 낱말 → 페이지. 위에서부터 먼저 맞는 것 ("오늘의 경기 — 팀별 확률"이 teams로 가지 않게 index가 teams보다 앞).
TITLE_KEYS = [("성적표", "report.html"), ("선수", "players.html"), ("오늘의 경기", "index.html"), ("팀", "teams.html")]
# 파일 이름(영문) 낱말 → 페이지. 제목으로 못 정할 때만.
NAME_KEYS = [("report", "report.html"), ("player", "players.html"), ("team", "teams.html"),
             ("index", "index.html"), ("home", "index.html"), ("today", "index.html")]
# 사이트에 넣는 파일 종류. 그 밖(.json 데이터 사본 등)은 건너뛰고 알린다 — 데이터는 data/public/에서만 읽는다.
WEB_SUFFIXES = {".html", ".htm", ".css", ".js", ".mjs", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico",
                ".woff", ".woff2", ".txt"}

# 따옴표 안의 ">"까지 견디는 여는 태그 패턴
_ATTRS = r"""(?:[^>"']|"[^"]*"|'[^']*')*"""
SCRIPT_RE = re.compile(rf"<script\b({_ATTRS})>(.*?)</script\s*>", re.I | re.S)
LINK_RE = re.compile(rf"<link\b({_ATTRS})/?>", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.I | re.S)
# src="…", href='…', srcset 등 리소스 속성 값 (태그 안에서만 쓰이므로 이 정도면 충분)
URL_ATTR_RE = re.compile(r"""(\s(?:src|href|poster|data)\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
FILE_URL_RE = re.compile(r"""file:/{2,3}[^"')\s>]+""", re.I)
# <script>·<style> 본문 — 루트 경로 고치기는 이 본문(코드) 밖의 태그 속성에만 한다
RAW_BLOCK_RE = re.compile(rf"(<(script|style)\b{_ATTRS}>)(.*?)(</\2\s*>)", re.I | re.S)


@dataclass
class PageReport:
    source: str
    target: str
    removed: list[str] = field(default_factory=list)
    rewritten: list[str] = field(default_factory=list)


@dataclass
class ImportPlan:
    files: dict[str, bytes]                       # site/ 기준 상대 경로 → 내용
    pages: list[PageReport]
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------- 입력 읽기 ----------

def _safe_rel(name: str) -> PurePosixPath:
    """zip·폴더 안의 경로를 site/ 기준 상대 경로로. 절대 경로·드라이브 문자·'..'는 ValueError (site/ 밖에 쓰지 않는다)."""
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or re.match(r"^[A-Za-z]:", name) or ".." in p.parts:
        raise ValueError(f"zip 안의 경로를 받을 수 없음: {name!r} (절대 경로·'..')")
    return p


def _hidden(rel: PurePosixPath) -> bool:
    """숨김 파일·폴더(.DS_Store, .nojekyll 등)와 macOS 압축 부산물(__MACOSX/…)."""
    return any(part.startswith(".") or part == "__MACOSX" for part in rel.parts)


def _strip_single_top(files: dict[PurePosixPath, bytes]) -> dict[PurePosixPath, bytes]:
    """모든 파일이 최상위 폴더 하나 안에 있으면(zip에 흔함) 그 폴더를 벗긴다."""
    tops = {p.parts[0] for p in files}
    if len(tops) == 1 and all(len(p.parts) > 1 for p in files):
        return {PurePosixPath(*p.parts[1:]): b for p, b in files.items()}
    return files


def read_source(src: Path, skipped: list[str] | None = None) -> dict[PurePosixPath, bytes]:
    """입력의 파일들(site/ 기준 상대 경로 → 내용). 숨김 파일·__MACOSX는 건너뛰고 skipped에 적는다(반영 중단 아님).
    zip 안에 절대 경로나 '..'가 있으면 ValueError."""
    files: dict[PurePosixPath, bytes] = {}
    skipped = skipped if skipped is not None else []
    if src.is_dir():
        for path in sorted(src.rglob("*")):
            if path.is_file():
                rel = _safe_rel(path.relative_to(src).as_posix())
                if _hidden(rel):
                    skipped.append(f"{rel} (숨김 파일·__MACOSX)")
                else:
                    files[rel] = path.read_bytes()
    elif src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel = _safe_rel(info.filename)
                if _hidden(rel):
                    skipped.append(f"{rel} (숨김 파일·__MACOSX)")
                    continue
                files[rel] = zf.read(info)
    elif src.is_file():
        files[PurePosixPath(src.name)] = src.read_bytes()
    else:
        raise FileNotFoundError(src)
    return _strip_single_top(files)


# ---------- 페이지 이름 ----------

def page_for(rel: PurePosixPath, html: str) -> str | None:
    """내보낸 HTML 하나가 어느 페이지인가: 파일 이름 → <title> 낱말 → 파일 이름 낱말."""
    if rel.name in PAGES:
        return rel.name
    m = TITLE_RE.search(html)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    for word, page in TITLE_KEYS:
        if word in title:
            return page
    stem = rel.stem.lower()
    for word, page in NAME_KEYS:
        if word in stem:
            return page
    return None


# ---------- 정리 ----------

def _attr(attrs: str, name: str) -> str | None:
    m = re.search(rf"""\s{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", " " + attrs, re.I)
    return None if not m else next(g for g in m.groups() if g is not None)


def _external_not_allowed(url: str) -> bool:
    """외부(스킴 있는 주소·//)인데 허용 목록 밖인가. file://는 지우지 않고 아래에서 상대 경로로 고친다."""
    url = url.strip()
    if url.lower().startswith("file:"):
        return False
    return bool(check_site.ABSOLUTE.match(url)) and not check_site._allowed(url)


def _relative_from_file_url(url: str) -> str:
    """file:///C:/Users/x/Downloads/export/assets/app.css → assets/app.css, …/report.html → report.html."""
    path = re.sub(r"^file:/{2,3}", "", url, flags=re.I).replace("\\", "/")
    parts = [p for p in path.split("/") if p]
    if "assets" in parts:
        return "/".join(parts[len(parts) - 1 - parts[::-1].index("assets"):])
    return parts[-1] if parts else ""


def _outside_raw(html: str, fn) -> str:
    """fn을 <script>/<style> 본문 밖의 텍스트(여는 태그 포함)에만 적용한다."""
    out, pos = [], 0
    for m in RAW_BLOCK_RE.finditer(html):
        out += [fn(html[pos:m.start()]), fn(m.group(1)), m.group(3), m.group(4)]
        pos = m.end()
    out.append(fn(html[pos:]))
    return "".join(out)


def sanitize_html(html: str, report: PageReport) -> str:
    """허용 목록 밖의 외부 <script>/<link>와 트래킹 인라인 스크립트를 지우고, file://·루트 경로를 상대 경로로 바꾼다."""
    def drop_script(m: re.Match) -> str:
        attrs, body = m.group(1), m.group(2)
        src = _attr(attrs, "src")
        if src is not None and _external_not_allowed(src):
            report.removed.append(f"<script src={src}>")
            return ""
        if src is None and check_site.TRACKERS.search(body):
            report.removed.append(f"<script> 인라인 트래킹 코드 ({body.strip()[:40]}…)")
            return ""
        return m.group(0)

    def drop_link(m: re.Match) -> str:
        href = _attr(m.group(1), "href")
        if href is not None and _external_not_allowed(href):
            report.removed.append(f"<link href={href}>")
            return ""
        return m.group(0)

    html = SCRIPT_RE.sub(drop_script, html)
    html = LINK_RE.sub(drop_link, html)

    def fix_url(m: re.Match) -> str:
        prefix, quote, url = m.groups()
        new = url
        if url.lower().startswith("file:"):
            new = _relative_from_file_url(url)
        elif url.startswith("/") and not url.startswith("//"):
            new = url.lstrip("/") or "index.html"
        if new != url:
            report.rewritten.append(f"{url} → {new}")
        return f"{prefix}{quote}{new}{quote}"

    html = _outside_raw(html, lambda text: URL_ATTR_RE.sub(fix_url, text))

    def fix_inline_file(m: re.Match) -> str:  # <style>의 url(file:///…) 등 남은 file://
        new = _relative_from_file_url(m.group(0))
        report.rewritten.append(f"{m.group(0)} → {new}")
        return new

    return FILE_URL_RE.sub(fix_inline_file, html)


def plan_import(src: Path, as_page: str | None = None) -> ImportPlan:
    skipped: list[str] = []
    raw = read_source(src, skipped)
    html_files = {p: b for p, b in raw.items() if p.suffix.lower() in (".html", ".htm")}
    if as_page is not None:
        if as_page not in PAGES:
            raise ValueError(f"--as는 {PAGES} 중 하나")
        if len(html_files) != 1:
            raise ValueError(f"--as는 HTML이 하나일 때만 쓸 수 있음 (지금 {len(html_files)}개)")
    plan = ImportPlan(files={}, pages=[], skipped=skipped)
    for rel, data in sorted(raw.items()):
        suffix = rel.suffix.lower()
        if suffix not in WEB_SUFFIXES:
            plan.skipped.append(f"{rel} (사이트 파일 종류가 아님 — 데이터는 data/public/에서만 읽는다)")
            continue
        if rel in html_files:
            html = data.decode("utf-8-sig")
            target = as_page or page_for(rel, html)
            if target is None:
                plan.skipped.append(f"{rel} (어느 페이지인지 모름 — 파일 이름을 index/teams/players/report.html로 바꾸거나 --as)")
                continue
            if target in plan.files:
                raise ValueError(f"{rel}과 다른 파일이 둘 다 {target}로 정해짐 — 파일 이름을 페이지 이름으로 바꿔 주세요")
            rep = PageReport(str(rel), target)
            plan.files[target] = sanitize_html(html, rep).encode("utf-8")
            plan.pages.append(rep)
        else:
            plan.files[rel.as_posix()] = data
    if not plan.pages:
        raise ValueError("반영할 페이지(HTML)가 없음")
    missing = [p for p in PAGES if p not in plan.files]
    if missing:
        plan.warnings.append(f"이번 내보내기에 없는 페이지 {missing}는 지금 site/의 것을 그대로 둠")
    for rep in plan.pages:
        if any(not check_site.TRACKERS.search(r) and "트래킹" not in r for r in rep.removed):
            plan.warnings.append(f"{rep.target}: 트래킹이 아닌 외부 파일도 지웠음 — 스타일·동작이 깨졌는지 화면으로 확인")
    return plan


# ---------- 반영·검증 ----------

def apply_plan(plan: ImportPlan, site: Path) -> None:
    for rel, data in plan.files.items():
        dest = site / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


def _restore(site: Path, backup: Path) -> None:
    shutil.rmtree(site)
    shutil.copytree(backup, site)


def run_check(site: Path, data: Path, contract: Path) -> tuple[bool, str]:
    rows = check_site.run(site, data, contract, strict=True)
    n_fail = sum(r.result == "FAIL" for r in rows)
    summary = f"{'FAIL' if n_fail else 'PASS'}: OK {sum(r.result == 'OK' for r in rows)}, FAIL {n_fail}"
    return n_fail == 0, check_site.format_table(rows) + "\n\n" + summary


def print_plan(plan: ImportPlan) -> None:
    print("## 반영할 페이지")
    for rep in plan.pages:
        print(f"- {rep.source} → {rep.target}")
        for r in rep.removed:
            print(f"    지움: {r}")
        for r in rep.rewritten:
            print(f"    경로: {r}")
    others = sorted(k for k in plan.files if k not in PAGES)
    if others:
        print(f"## 함께 복사할 파일 {len(others)}개: {', '.join(others[:12])}{' …' if len(others) > 12 else ''}")
    for s in plan.skipped:
        print(f"건너뜀: {s}")
    for w in plan.warnings:
        print(f"주의: {w}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="내보낸 사이트(zip·폴더·html)를 site/에 반영하고 check_site로 검증")
    ap.add_argument("source", help="Genspark 내보내기 zip, 폴더, 또는 .html 하나")
    ap.add_argument("--as", dest="as_page", choices=PAGES, help="단일 .html을 이 페이지로 반영")
    ap.add_argument("--dry-run", action="store_true", help="site/를 건드리지 않고 임시 복사본에서 반영·검증만")
    ap.add_argument("--keep", action="store_true", help="검증이 실패해도 반영한 site/를 남김 (백업은 그대로)")
    ap.add_argument("--site", default=str(ROOT / "site"))
    ap.add_argument("--backup-root", default=str(ROOT / "artifacts"))
    ap.add_argument("--data", default=str(ROOT / "data" / "public"))
    ap.add_argument("--contract", default=str(ROOT / "docs" / "site" / "data-contract.md"))
    args = ap.parse_args(argv)
    site, data, contract = Path(args.site), Path(args.data), Path(args.contract)

    try:
        plan = plan_import(Path(args.source), args.as_page)
    except (ValueError, FileNotFoundError, zipfile.BadZipFile, UnicodeDecodeError) as e:
        print(f"반영하지 않음: {e}")
        return 2
    print_plan(plan)

    if args.dry_run:
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "site"
            shutil.copytree(site, staged)
            apply_plan(plan, staged)
            ok, table = run_check(staged, data, contract)
        print("\n## check_site (dry-run, site/는 그대로)\n" + table)
        return 0 if ok else 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path(args.backup_root) / f"site-backup-{stamp}"
    n = 1
    while backup.exists():
        n += 1
        backup = Path(args.backup_root) / f"site-backup-{stamp}-{n}"
    shutil.copytree(site, backup)
    print(f"\n백업: {backup}")
    apply_plan(plan, site)
    ok, table = run_check(site, data, contract)
    print("\n## check_site\n" + table)
    if ok:
        print(f"\n반영 완료: {site}. 화면(1280·360) 확인 뒤 커밋하세요. 되돌리려면 {backup}를 복사.")
        return 0
    if args.keep:
        print(f"\n검증 실패 — --keep이라 반영한 site/를 남김. 되돌리려면 {backup}를 복사.")
    else:
        _restore(site, backup)
        print(f"\n검증 실패 — site/를 백업({backup})으로 되돌림.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
