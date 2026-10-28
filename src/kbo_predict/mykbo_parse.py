"""MyKBOStats HTML 파서 (주간 일정 페이지, 경기 페이지)."""
import html as htmllib
import re
from datetime import datetime

from bs4 import BeautifulSoup

from kbo_predict import KST
from kbo_predict.teams import code_for, short_to_code

_FRAC = {"⅓": 1, "⅔": 2}


def parse_innings(inn: str) -> int:
    """이닝 문자열 -> 아웃 수. '4 ⅓' -> 13, '' -> 0."""
    s = htmllib.unescape(inn).replace("\xa0", " ").strip()
    if not s:
        return 0
    outs = 0
    for ch, n in _FRAC.items():
        if ch in s:
            outs += n
            s = s.replace(ch, "")
    s = s.strip()
    return outs + (int(s) * 3 if s else 0)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _to_kst(datetime_utc: str) -> datetime:
    return datetime.fromisoformat(datetime_utc.replace("Z", "+00:00")).astimezone(KST)


def _int(text: str) -> int | None:
    """숫자 셀 -> int. 결측("-", 빈칸 등)은 0이 아니라 None."""
    text = text.strip()
    return int(text) if text.lstrip("-").isdigit() else None


_LIVE_RE = re.compile(r"\bLIVE\b|\b(?:Top|Bot(?:tom)?|Mid|End)\s+\d+(?:st|nd|rd|th)\b", re.IGNORECASE)


def parse_week(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for a in soup.find_all("a", id=re.compile(r"^game-line-\d+$")):
        game_id = int(a["id"].rsplit("-", 1)[1])
        dt_utc = a["data-game-datetime"]
        kst = _to_kst(dt_utc)
        names = [_norm(s.get_text()) for s in a.find_all("span", class_="font-semibold")]
        away, home = names[0], names[1]
        scores = [
            int(s.get_text())
            for s in a.find_all("span", class_="font-mono")
            if "font-bold" in s["class"] and s.get_text(strip=True).isdigit()
        ]
        text = _norm(a.get_text(" "))
        has_time = a.find("time") is not None
        note = stadium = None
        if "Canceled" in text:
            status = "CANCELED"
            note_span = a.find("span", class_="font-sans")
            note = _norm(note_span.get_text()) if note_span else None
        elif re.search(r"\bFinal\b", text):
            status = "FINAL"
        elif _LIVE_RE.search(text):
            status = "LIVE"
        elif has_time:
            status = "SCHEDULED"
            st = a.find("span", class_="font-sans", string=True)
            stadium = _norm(st.get_text()) if st else None
        else:
            raise ValueError(f"unrecognised game status in week row {game_id}: {text!r}")
        final = status in ("FINAL", "LIVE") and len(scores) == 2
        rows.append({
            "game_id": game_id,
            "path": a["href"],
            "datetime_utc": dt_utc,
            "date": kst.date().isoformat(),
            "season": kst.year,
            "away": away,
            "home": home,
            "away_code": code_for(away),
            "home_code": code_for(home),
            "away_score": scores[0] if final else None,
            "home_score": scores[1] if final else None,
            "status": status,
            "status_note": note,
            "time_kst": kst.strftime("%H:%M") if status == "SCHEDULED" else None,
            "stadium": stadium,
        })
    return rows


_STATUS_WORDS = (("final", "FINAL"), ("scheduled", "SCHEDULED"), ("cancel", "CANCELED"),
                 ("postpone", "CANCELED"), ("live", "LIVE"), ("top ", "LIVE"), ("bot ", "LIVE"), ("bottom ", "LIVE"),
                 ("mid ", "LIVE"), ("end ", "LIVE"))


def _game_status(soup: BeautifulSoup) -> str:
    for p in soup.find_all("p", class_="mt-sm"):
        # LIVE 페이지는 이닝 앞에 ▲▼ 같은 기호가 붙는다
        t = _norm(p.get_text()).lower().lstrip("▲▼△▽ ").strip()
        for word, status in _STATUS_WORDS:
            if t.startswith(word):
                return status
    raise ValueError("unrecognised game status on game page")


def _linescore(soup: BeautifulSoup, away_name: str, home_name: str):
    board = soup.find("div", class_="scoreboard")
    if board is None:
        return None, {}
    lines: dict[str, list[int]] = {}
    runs: dict[str, int] = {}
    for team in board.find_all("div", class_="team", recursive=False):
        name = _norm(team.find("span", class_="team-name").get_text())
        inn = []
        for sib in team.find_next_siblings("div"):
            cls = sib.get("class") or []
            if not cls and not sib.get_text(strip=True):  # 이닝 영역 끝 (빈 spacer)
                break
            if "team" in cls:
                break
            if sib.get_text(strip=True).isdigit():
                inn.append(int(sib.get_text()))
        lines[name] = inn
        r = team.find_next_sibling("div", class_="runs")
        if r is not None:
            runs[name] = int(r.get_text())
    if away_name not in lines or home_name not in lines:
        return None, {}
    return {"away": lines[away_name], "home": lines[home_name]}, runs


def _table_rows(table, columns: list[tuple[str, str]], kind: str) -> list[dict]:
    headers = [_norm(th.get_text()) for th in table.find("thead").find_all("th")]
    idx = {h: i for i, h in enumerate(headers)}
    out, order = [], 0
    for n, tr in enumerate(table.find("tbody").find_all("tr"), start=1):
        tds = tr.find_all("td")
        link = tds[0].find("a", href=re.compile(r"^/players/\d+"))
        if link is None:
            continue
        row = {"player_id": int(re.match(r"/players/(\d+)", link["href"]).group(1)), "name": _norm(link.get_text())}
        if kind == "batting":
            first = tds[0].find("span")
            num = _norm(first.get_text()) if first else ""
            if num.isdigit():  # 교체 선수(↳)는 앞 선발의 타순을 이어받는다
                order = int(num)
            row = {"order": order, **row, "pos": _norm(tds[idx["Pos"]].get_text())}
        else:
            row = {"order": n, **row}
        for key, header in columns:
            cell = tds[idx[header]].get_text()
            row[key] = parse_innings(cell) if header == "IP" else _int(cell)
        out.append(row)
    return out


_BAT_COLS = [(h.lower(), h) for h in ("AB", "R", "H", "HR", "RBI", "BB", "SO", "HBP")]
_PIT_COLS = [("ip_outs", "IP")] + [(h.lower(), h) for h in ("NP", "R", "ER", "H", "HR", "SO", "BB")] + [("hbp", "HB")]


def parse_game(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    og_tag = soup.find("meta", property="og:url")
    if og_tag is None:
        raise ValueError("unrecognised game page: no og:url")
    og = og_tag["content"]
    game_id = int(re.search(r"/games/(\d+)-", og).group(1))
    away_name, home_name = (_norm(x) for x in soup.title.get_text().split(" - ")[0].split(" vs. "))
    away_code, home_code = code_for(away_name), code_for(home_name)
    t = soup.find("time", attrs={"datetime": True})
    date = _to_kst(t["datetime"]).date().isoformat()
    loc = soup.find(attrs={"itemprop": "location"})
    status = _game_status(soup)
    linescore, runs = _linescore(soup, away_name, home_name)

    batting = {"away": [], "home": []}
    pitching = {"away": [], "home": []}
    for table in soup.find_all("table", class_="live-players"):
        side = {away_code: "away", home_code: "home"}[
            short_to_code(_norm(table.find("thead").find("th").get_text()))]
        heads = {_norm(th.get_text()) for th in table.find("thead").find_all("th")}
        if "Pos" in heads:
            batting[side] = _table_rows(table, _BAT_COLS, "batting")
        elif "ERA" in heads:
            pitching[side] = _table_rows(table, _PIT_COLS, "pitching")

    def side_info(name, code):
        return {"name": name, "code": code, "score": runs.get(name)}

    return {
        "game_id": game_id,
        "date": date,
        "stadium": _norm(loc.get_text()) if loc else None,
        "status": status,
        "away": side_info(away_name, away_code),
        "home": side_info(home_name, home_code),
        "batting": batting,
        "pitching": pitching,
        "linescore": linescore,
    }
