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
                 ("mid ", "LIVE"), ("end ", "LIVE"),
                 ("delay", "LIVE"))  # 우천 지연: 끝난 경기 페이지에 'Delayed'가 남는 경우도 있음


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
    for tr in table.find("tbody").find_all("tr"):
        tds = tr.find_all("td")
        if not tds and any(re.search(r"bench|bullpen", th.get_text().lower()) for th in tr.find_all("th")):
            break  # Bench/Bullpen 구분 행: 이후는 출전하지 않은 선수라 읽지 않는다
        link = tds[0].find("a", href=re.compile(r"^/players/\d+")) if tds else None
        if len(tds) < len(headers):
            if link is not None:  # 출전 선수 행인데 셀이 모자람 -> 조용히 오분류하지 않고 실패
                raise ValueError(f"short {kind} row for player {_norm(link.get_text())}: {len(tds)}/{len(headers)} cells")
            continue  # 빈 행, <th>만 있는 행, 링크 없는 보조 행(spacer)은 건너뜀
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
            row = {"order": len(out) + 1, **row}  # 등판 순서 = 실제로 읽은 투수 행 번호
        for key, header in columns:
            cell = tds[idx[header]].get_text()
            row[key] = parse_innings(cell) if header == "IP" else _int(cell)
        out.append(row)
    return out


_BAT_COLS = [(h.lower(), h) for h in ("AB", "R", "H", "HR", "RBI", "BB", "SO", "HBP")]
_PIT_COLS = [("ip_outs", "IP")] + [(h.lower(), h) for h in ("NP", "R", "ER", "H", "HR", "SO", "BB")] + [("hbp", "HB")]


_COUNT_LABELS = {"2B": "doubles", "3B": "triples", "SB": "sb"}
_NAME_LABELS = {"HR", "E", "GIDP"}  # 세지는 않고 한글 이름에만 쓰는 행
_KO_TOKEN = re.compile(r"(\S+?)(\d+)?\((.*?)\)")


def _match_player(name: str, rows: list[dict], ko_names: dict[int, str] | None = None) -> int | None:
    """기록표 이름 -> player_id. 이름이 같으면 그 선수, 아니면 기록표 이름이 " " + 행 이름으로 끝나는 행
    ("Andy Van Hekken" <-> 행 "Van Hekken"), 그래도 없고 한글 이름이면 ko_names(다른 경기에서 알아낸 id -> 한글 이름)와 맞춘다.
    후보가 정확히 한 명일 때만 돌려주고, 없거나 여러 명이면 None."""
    key = name.casefold()
    exact = {r["player_id"] for r in rows if r["name"].casefold() == key}
    if len(exact) == 1:
        return exact.pop()
    if exact:
        return None
    suffix = {r["player_id"] for r in rows if r["name"] and key.endswith(" " + r["name"].casefold())}
    if suffix:
        return suffix.pop() if len(suffix) == 1 else None
    if ko_names and re.search("[가-힣]", name):
        ko = {r["player_id"] for r in rows if ko_names.get(r["player_id"]) == name}
        return ko.pop() if len(ko) == 1 else None
    return None


def _split_entries(text: str) -> list[str]:
    """'A (1st inning), B (2nd inning)' -> ['A (1st inning)', 'B (2nd inning)']"""
    parts = re.split(r"\),\s*", _norm(text))
    return [p if p.endswith(")") else p + ")" for p in parts if p]


def _records(soup, batting: dict, pitching: dict, ko_names: dict[int, str] | None = None) -> tuple[dict[int, dict[str, int]] | None, dict[str, str], list[str]]:
    """기록표 -> (선수별 2루타/3루타/도루, 한글 이름, 못 붙인 항목). 기록표가 없으면 (None, {}, [])."""
    table = soup.find("table", attrs={"data-game-section": "records"})
    stats: dict[int, dict[str, int]] = {}
    names_ko: dict[str, str] = {}
    unmatched: list[str] = []
    if table is None:
        return None, names_ko, unmatched
    bat_rows = [r for s in ("away", "home") for r in batting[s]]
    pit_rows = [r for s in ("away", "home") for r in pitching[s]]
    for r in bat_rows:
        stats[r["player_id"]] = {"doubles": 0, "triples": 0, "sb": 0}

    def put_ko(pid, ko):
        names_ko.setdefault(str(pid), ko)

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        label = _norm(tds[0].get_text())
        if label not in _COUNT_LABELS and label not in _NAME_LABELS:
            continue
        text = tds[1].get_text()
        if label == "HR":
            # 한 타자가 두 번 이상 치면 영어 칸이 '), , 1 run; #3, 6th inning off X (#2, ...' 처럼 섞여 나온다.
            # '이름 (#' 꼴로 타자를 찾으면 한 타자가 항목 하나로 남는다 (항목 수 = 제목의 한글 타자 수)
            entries = [re.sub(r".*\boff\s+", "", m.group(1)).strip() + " (HR)"
                       for m in re.finditer(r"([^,;()#]+?)\s*\(#", _norm(text))]
        else:
            entries = _split_entries(text)
        title = tds[0].get("title", "")
        ko = [(re.sub(r"(?:\d+호)+$", "", m.group(1)), m.group(3))
              for m in _KO_TOKEN.finditer(title.split(":", 1)[1])] if ":" in title else []
        pair_ko = len(ko) == len(entries)
        pool = bat_rows + pit_rows if label == "E" else bat_rows
        for i, entry in enumerate(entries):
            name = entry.split(" (", 1)[0].strip()
            pid = _match_player(name, pool, ko_names)
            if pid is None:
                unmatched.append(f"{label}: {entry}")
                continue
            if label in _COUNT_LABELS:  # 이 라벨의 pool은 타자 행뿐이라 pid는 항상 stats에 있다
                inner = entry.split(" (", 1)[1].rstrip(")") if " (" in entry else ""
                stats[pid][_COUNT_LABELS[label]] += len([t for t in inner.split(",") if t.strip()])
            if pair_ko:
                put_ko(pid, ko[i][0])
        if label == "HR":  # 홈런을 맞은 투수: 영어(타자 이름 제외)와 한글 칸의 고유 투수를 순서대로 짝짓는다
            batters = {e.split(" (", 1)[0] for e in entries}
            en = list(dict.fromkeys(m.strip() for m in re.findall(r"\boff ([^,;()]+)", _norm(text))
                                    if m.strip() not in batters))
            kp = list(dict.fromkeys(t for _, inner in ko for t in inner.split() if not t.endswith(("회", "점"))))
            # 한계: 남은 짝짓기는 순서(위치)에만 의존해 영어·한글 칸 순서가 다르면 서로 바뀔 수 있다.
            # 그래서 먼저, 이미 아는 한글 이름(ko_names)과 같은 한글 토큰은 그 투수에게 바로 붙이고 나머지만 위치로 짝짓는다.
            if ko_names:
                for k in list(kp):
                    known = {r["player_id"] for r in pit_rows if ko_names.get(r["player_id"]) == k}
                    if len(known) == 1:
                        pid = known.pop()
                        put_ko(pid, k)
                        kp.remove(k)
                        for n in en:
                            if _match_player(n, pit_rows, ko_names) == pid:
                                en.remove(n)
                                break
            if en and len(en) == len(kp):
                for n, k in zip(en, kp):
                    pid = _match_player(n, pit_rows, ko_names)
                    if pid is None:
                        unmatched.append(f"HR off: {n}")
                    else:
                        put_ko(pid, k)
    return stats, names_ko, unmatched


def parse_game(html: str, ko_names: dict[int, str] | None = None) -> dict:
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

    stats, names_ko, records_unmatched = _records(soup, batting, pitching, ko_names)
    for side in ("away", "home"):
        for r in batting[side]:
            st = stats[r["player_id"]] if stats is not None else {}
            for k in ("doubles", "triples", "sb"):
                r[k] = st.get(k)

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
        "names_ko": names_ko,
        "records_unmatched": records_unmatched,
    }


def _page_game_id(soup: BeautifulSoup) -> int | None:
    """페이지가 어느 경기 페이지인지: og:url의 /games/{id}- 에서 읽는다 (parse_game과 같은 방법). 없으면 None."""
    og_tag = soup.find("meta", property="og:url")
    m = re.search(r"/games/(\d+)-", og_tag.get("content", "")) if og_tag is not None else None
    return int(m.group(1)) if m else None


def parse_starters(html: str, game_id: int | None = None) -> dict | None:
    """경기 페이지의 예고 선발투수. 섹션이 아예 없으면 None.

    game_id를 주면 먼저 '정말 그 경기 페이지인가'를 확인한다 — 섹션이 없다는 이유만으로 None(미정)을 돌려주면
    챌린지·인터스티셜 페이지나 엉뚱한 경기 페이지가 이미 알던 선발을 TBA로 덮어쓸 수 있기 때문이다.
      - 경기 식별 정보(og:url의 /games/{id}-)가 없으면 ValueError("not a game page")
      - 다른 경기 페이지면 ValueError("starters page mismatch: expected …, got …")
    원정/홈은 블록 클래스(starter-comparison__pitcher--away/--home)로 구분한다. 선수 링크가 없는 쪽은 None(미발표).
    섹션은 있는데 선수 블록을 알아볼 수 없으면 페이지 구조가 바뀐 것이므로 ValueError.
    같은 선수에 사진 링크와 이름 링크가 있으므로 텍스트가 있는 링크에서 이름을 읽는다.
    """
    soup = BeautifulSoup(html, "html.parser")
    if game_id is not None:
        found = _page_game_id(soup)
        if found is None:
            raise ValueError("not a game page")
        if found != game_id:
            raise ValueError(f"starters page mismatch: expected {game_id}, got {found}")
    section = soup.select_one('section[aria-label="Starting pitchers"]')
    if section is None:
        return None
    blocks = {side: section.select_one(f".starter-comparison__pitcher--{side}") for side in ("away", "home")}
    if not any(blocks.values()):
        raise ValueError("unrecognised starting pitchers section")
    out = {}
    for side, block in blocks.items():
        link = None
        if block is not None:
            link = next((a for a in block.find_all("a", attrs={"data-id": True}) if _norm(a.get_text())), None)
        out[side] = {"player_id": int(link["data-id"]), "name": _norm(link.get_text())} if link else None
    return out
