"""원천 데이터를 사람이 보는 엑셀 파일로 내보낸다.

사용: python -X utf8 scripts/export_excel.py [--out 폴더] [--seasons 2026 2025 ...]

만드는 파일 (기본 폴더 artifacts/excel/, gitignore):
  kbo_games_2015-2026.xlsx      전 시즌 경기 일정·결과 한 시트 (약 1만 행) + 시즌별 팀 성적 + 선수-시즌 집계·유형
  kbo_boxscores_<시즌>.xlsx     시즌별 박스스코어 — 경기 요약·이닝별 점수·타자 경기별 기록·투수 경기별 기록·예고 선발

원본은 data/raw/<시즌>/games.jsonl, boxscores/<YYYY-MM>.jsonl.gz, starters.jsonl 이고 숫자를 바꾸지 않고 그대로 옮긴다.
선수 한글 이름은 박스스코어의 names_ko(기록표 한글 표기)에서, 없으면 data/raw/name_aliases.json 과 data/public/players.json 에서 찾는다.
"""
from __future__ import annotations

import argparse
import gzip
import json
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PUBLIC = ROOT / "data" / "public"

GAME_COLS = [("season", "시즌"), ("date", "날짜"), ("time_kst", "시각(KST)"), ("game_id", "경기 id"), ("status", "상태"),
             ("status_note", "비고"), ("away_code", "원정 코드"), ("away", "원정"), ("away_score", "원정 점수"),
             ("home_code", "홈 코드"), ("home", "홈"), ("home_score", "홈 점수"), ("stadium", "구장")]
BAT_COLS = [("order", "타순"), ("pos", "포지션"), ("player_id", "선수 id"), ("name", "이름(로마자)"), ("name_ko", "이름(한글)"),
            ("ab", "타수"), ("r", "득점"), ("h", "안타"), ("doubles", "2루타"), ("triples", "3루타"), ("hr", "홈런"),
            ("rbi", "타점"), ("bb", "볼넷"), ("hbp", "사구"), ("so", "삼진"), ("sb", "도루")]
PIT_COLS = [("order", "등판 순서"), ("player_id", "선수 id"), ("name", "이름(로마자)"), ("name_ko", "이름(한글)"),
            ("ip_outs", "아웃 수(이닝×3)"), ("ip", "이닝"), ("np", "투구 수"), ("h", "피안타"), ("r", "실점"), ("er", "자책"),
            ("bb", "볼넷"), ("hbp", "사구"), ("so", "삼진"), ("hr", "피홈런")]


def _seasons() -> list[int]:
    return sorted(int(p.name) for p in RAW.iterdir() if p.is_dir() and p.name.isdigit())


def _games(season: int) -> list[dict]:
    path = RAW / str(season) / "games.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def _boxscores(season: int):
    for f in sorted((RAW / str(season) / "boxscores").glob("*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def _starters(season: int) -> list[dict]:
    path = RAW / str(season) / "starters.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def _ko_names() -> dict[int, str]:
    """player_id → 한글 이름 (players.json이 있으면). 박스스코어의 names_ko가 우선이고 이건 보조."""
    out: dict[int, str] = {}
    pj = PUBLIC / "players.json"
    if pj.exists():
        for p in json.loads(pj.read_text(encoding="utf-8")).get("players", []):
            if p.get("name_ko") and p.get("player_id") is not None:
                out.setdefault(int(p["player_id"]), p["name_ko"])
    return out


def _ip(outs) -> str | None:
    if outs is None:
        return None
    outs = int(outs)
    return f"{outs // 3}" + {0: "", 1: "⅓", 2: "⅔"}[outs % 3]


def _sheet(wb: Workbook, title: str, cols: list[tuple[str, str]], rows, freeze=True):
    ws = wb.create_sheet(title=title)
    ws.append([ko for _, ko in cols])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="F5F0E0")
    n = 0
    for r in rows:
        ws.append([r.get(k) for k, _ in cols])
        n += 1
    for i, (_, ko) in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = max(8, min(28, len(ko) * 2 + 2))
    if freeze:
        ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return n


def export_games(seasons: list[int], out: Path) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    games = [g for s in seasons for g in _games(s)]
    n = _sheet(wb, "경기", GAME_COLS, games)
    tj = PUBLIC / "teams.json"
    if tj.exists():
        teams = json.loads(tj.read_text(encoding="utf-8")).get("teams", [])
        cols = [("season", "시즌"), ("code", "팀 코드"), ("name", "팀"), ("games", "경기"), ("wins", "승"), ("losses", "패"),
                ("ties", "무"), ("win_pct", "승률"), ("pyth_pct", "피타고리안 기대 승률"), ("model_expected", "모델 기대 승률"),
                ("home_pct", "홈 승률"), ("away_pct", "원정 승률")]
        _sheet(wb, "팀 시즌 성적", cols, sorted(teams, key=lambda t: (-t["season"], -t["win_pct"])))
    pj = PUBLIC / "players.json"
    if pj.exists():
        data = json.loads(pj.read_text(encoding="utf-8"))
        rows = []
        for p in data.get("players", []):
            st = p.get("stats") or {}
            rows.append({"season": p["season"], "group": "타자" if p["group"] == "batter" else "투수", "team": p.get("team"),
                         "player_id": p["player_id"], "name": p.get("name"), "name_ko": p.get("name_ko"), "pos": p.get("pos"),
                         "type": (p.get("type") or {}).get("name"), "prob": p.get("prob"), **{f"s_{k}": v for k, v in st.items()}})
        stat_keys = sorted({k for r in rows for k in r if k.startswith("s_")})
        cols = [("season", "시즌"), ("group", "구분"), ("team", "팀"), ("player_id", "선수 id"), ("name", "이름(로마자)"),
                ("name_ko", "이름(한글)"), ("pos", "포지션"), ("type", "유형"), ("prob", "유형 소속 확신도")] + \
               [(k, k[2:].upper()) for k in stat_keys]
        _sheet(wb, "선수 시즌 집계·유형", cols, sorted(rows, key=lambda r: (-r["season"], r["group"], r["team"] or "")))
    meta = wb.create_sheet("설명", 0)
    for line in [
        "KBO Predict 원천 데이터 — 경기 일정·결과 (MyKBOStats 박스스코어 수집본을 그대로 옮김)",
        f"시즌: {seasons[0]}~{seasons[-1]}, 경기 {n}행. 만든 시각: {datetime.now():%Y-%m-%d %H:%M}",
        "상태: FINAL 종료 · SCHEDULED 예정 · CANCELED 취소 · LIVE 중단(결과 미확정). 정규시즌·시범경기·포스트시즌이 모두 들어 있다.",
        "팀 시즌 성적·선수 시즌 집계 시트는 data/public/teams.json, players.json(정규시즌만 집계)에서 가져왔다.",
        "시즌별 박스스코어(타자·투수 경기별 기록)는 kbo_boxscores_<시즌>.xlsx 에 있다.",
        "개인 학습용 프로젝트 자료이며 베팅 조언이 아니다.",
    ]:
        meta.append([line])
    meta.column_dimensions["A"].width = 110
    path = out / f"kbo_games_{seasons[0]}-{seasons[-1]}.xlsx"
    wb.save(path)
    return path


def export_boxscores(season: int, out: Path, ko_fallback: dict[int, str]) -> tuple[Path, int]:
    wb = Workbook()
    wb.remove(wb.active)
    summary, lines, bats, pits = [], [], [], []
    ngames = 0
    for b in _boxscores(season):
        ngames += 1
        ko = {int(k): v for k, v in (b.get("names_ko") or {}).items()}
        base = {"date": b["date"], "game_id": b["game_id"], "away_code": b["away"]["code"], "home_code": b["home"]["code"]}
        summary.append({**base, "status": b.get("status"), "stadium": b.get("stadium"),
                        "away": b["away"].get("name"), "away_score": b["away"].get("score"),
                        "home": b["home"].get("name"), "home_score": b["home"].get("score"),
                        "unmatched": len(b.get("records_unmatched") or [])})
        ls = b.get("linescore") or {}
        for side in ("away", "home"):
            inn = ls.get(side) or []
            lines.append({**base, "side": "원정" if side == "away" else "홈", "team": b[side]["code"],
                          **{f"i{i}": v for i, v in enumerate(inn, 1)}, "total": b[side].get("score")})
        for side in ("away", "home"):
            team = b[side]["code"]
            for r in (b.get("batting") or {}).get(side) or []:
                bats.append({**base, "team": team, **r, "name_ko": ko.get(r.get("player_id")) or ko_fallback.get(r.get("player_id"))})
            for r in (b.get("pitching") or {}).get(side) or []:
                pits.append({**base, "team": team, **r, "ip": _ip(r.get("ip_outs")),
                             "name_ko": ko.get(r.get("player_id")) or ko_fallback.get(r.get("player_id"))})
    basecols = [("date", "날짜"), ("game_id", "경기 id"), ("away_code", "원정"), ("home_code", "홈")]
    _sheet(wb, "경기 요약", basecols + [("status", "상태"), ("stadium", "구장"), ("away", "원정 팀"), ("away_score", "원정 점수"),
                                     ("home", "홈 팀"), ("home_score", "홈 점수"), ("unmatched", "미매칭 기록 수")], summary)
    max_inn = max((len([k for k in r if k.startswith("i")]) for r in lines), default=9)
    _sheet(wb, "이닝별 점수", basecols + [("side", "구분"), ("team", "팀")] +
           [(f"i{i}", f"{i}회") for i in range(1, max_inn + 1)] + [("total", "합계")], lines)
    _sheet(wb, "타자 경기별", basecols + [("team", "팀")] + BAT_COLS, bats)
    _sheet(wb, "투수 경기별", basecols + [("team", "팀")] + PIT_COLS, pits)
    st = [{"date": s["date"], "game_id": s["game_id"], "fetched_at": s.get("fetched_at"),
           "away_id": (s.get("away") or {}).get("player_id"), "away_name": (s.get("away") or {}).get("name"),
           "away_ko": ko_fallback.get((s.get("away") or {}).get("player_id")),
           "home_id": (s.get("home") or {}).get("player_id"), "home_name": (s.get("home") or {}).get("name"),
           "home_ko": ko_fallback.get((s.get("home") or {}).get("player_id"))} for s in _starters(season)]
    _sheet(wb, "예고 선발", [("date", "날짜"), ("game_id", "경기 id"), ("fetched_at", "수집 시각"),
                          ("away_id", "원정 선발 id"), ("away_name", "원정 선발(로마자)"), ("away_ko", "원정 선발(한글)"),
                          ("home_id", "홈 선발 id"), ("home_name", "홈 선발(로마자)"), ("home_ko", "홈 선발(한글)")], st)
    meta = wb.create_sheet("설명", 0)
    for line in [
        f"KBO Predict 원천 데이터 — {season} 시즌 박스스코어 (MyKBOStats 경기 페이지 수집본, 숫자 그대로)",
        f"경기 {ngames}개 · 타자 기록 {len(bats)}행 · 투수 기록 {len(pits)}행 · 예고 선발 {len(st)}행. 만든 시각: {datetime.now():%Y-%m-%d %H:%M}",
        "타자: 타수·득점·안타·2루타·3루타·홈런·타점·볼넷·사구·삼진·도루. 투수: 아웃 수(이닝×3)·투구 수·피안타·실점·자책·볼넷·사구·삼진·피홈런.",
        "이름(한글)은 경기 페이지 기록표의 한글 표기이고, 없으면 players.json의 이름. 둘 다 없으면 빈칸.",
        "미매칭 기록 수 = 기록표 행 중 선수 이름과 짝을 못 지은 수(모델에는 영향 없음).",
    ]:
        meta.append([line])
    meta.column_dimensions["A"].width = 110
    path = out / f"kbo_boxscores_{season}.xlsx"
    wb.save(path)
    return path, ngames


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "excel"), help="저장 폴더 (기본 artifacts/excel)")
    ap.add_argument("--seasons", nargs="*", type=int, help="박스스코어 파일을 만들 시즌 (기본 전체)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    seasons = _seasons()
    ko = _ko_names()
    path = export_games(seasons, out)
    print(f"경기 전체 → {path}")
    for s in (args.seasons or seasons):
        path, n = export_boxscores(s, out, ko)
        print(f"{s} 박스스코어 {n}경기 → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
