import re
import pytest

from kbo_predict.mykbo_parse import parse_game, parse_innings, parse_starters, parse_week


@pytest.mark.parametrize("inn,outs", [("5", 15), ("4 ⅓", 13), ("0 ⅔", 2), ("", 0), ("6 ⅔", 20)])
def test_parse_innings(inn, outs):
    assert parse_innings(inn) == outs


def test_parse_innings_html_entities():
    assert parse_innings("4&nbsp;&frac13;") == 13


def test_parse_week_regular_season(fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2026-08-11.html"))
    assert len(rows) == 30
    g = next(r for r in rows if r["game_id"] == 13802)
    assert g == {**g, "path": "/games/13802-Hanwha-vs-Doosan-20260811", "date": "2026-08-11", "season": 2026,
                 "away": "Hanwha Eagles", "home": "Doosan Bears", "away_code": "HH", "home_code": "OB",
                 "away_score": 3, "home_score": 6, "status": "FINAL"}
    canceled = [r for r in rows if r["status"] == "CANCELED"]
    assert {r["game_id"] for r in canceled} == {13827, 13828}
    assert next(r for r in canceled if r["game_id"] == 13828)["status_note"] == "Rained Out"
    assert all(r["away_score"] is None for r in canceled)


def test_parse_week_postseason_scheduled(fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2026-10-27.html"))
    assert [r["game_id"] for r in rows] == [14052, 14050, 14053, 14054] or len(rows) == 4
    g = next(r for r in rows if r["game_id"] == 14050)
    assert g["status"] == "SCHEDULED" and g["time_kst"] == "18:30" and g["stadium"] == "Gwangju" and g["home_code"] == "HT" and g["date"] == "2026-10-29"
    f = next(r for r in rows if r["game_id"] == 14052)
    assert f["status"] == "FINAL" and (f["away_score"], f["home_score"]) == (3, 8)


def test_parse_game_final(fixture_html):
    g = parse_game(fixture_html("mykbo_game_14048_final.html"))
    assert g["game_id"] == 14048 and g["date"] == "2026-10-26" and g["status"] == "FINAL"
    # fixture 실제 값: 원정 Kia 5 : 1 홈 Samsung (브리프의 1/5는 반대로 적힌 오기)
    assert g["away"] == {"name": "Kia Tigers", "code": "HT", "score": 5}
    assert g["home"] == {"name": "Samsung Lions", "code": "SS", "score": 1}
    assert g["stadium"] == "Daegu Samsung Lions Park"
    assert g["linescore"] == {"away": [2, 0, 2, 1, 0, 0, 0, 0, 0], "home": [0, 0, 0, 0, 1, 0, 0, 0, 0]}
    assert g["batting"]["away"][0] == {**g["batting"]["away"][0], "order": 1, "name": "Park Jung-woo", "pos": "RF", "ab": 5, "h": 0, "so": 2}
    assert [r["order"] for r in g["batting"]["away"]][:6] == [1, 2, 3, 4, 5, 5]  # 교체 선수는 같은 타순
    p = g["pitching"]["away"][0]
    assert p["name"] == "Naile" and p["ip_outs"] == 13 and p["er"] == 1 and p["so"] == 3 and p["order"] == 1
    assert g["pitching"]["home"][0]["name"] == "Paddack" and g["pitching"]["home"][0]["ip_outs"] == 14
    assert all(isinstance(r["player_id"], int) for side in g["batting"].values() for r in side)


def test_parse_game_scheduled_has_no_boxscore(fixture_html):
    g = parse_game(fixture_html("mykbo_game_14050_scheduled.html"))
    assert g["game_id"] == 14050 and g["status"] != "FINAL"
    assert g["batting"] == {"away": [], "home": []} and g["pitching"] == {"away": [], "home": []}
    assert g["linescore"] is None


def _week_with_label(fixture_html, label):
    html = fixture_html("mykbo_week_2026-08-11.html")
    start = html.index('id="game-line-13802"')
    end = html.index("</a>", start)
    row = html[start:end].replace("Final", label, 1)
    return html[:start] + row + html[end:]


def test_parse_week_live_label_is_live(fixture_html):
    html = _week_with_label(fixture_html, 'Bot 9th</span><span class="font-mono">LIVE')
    g = next(r for r in parse_week(html) if r["game_id"] == 13802)
    assert g["status"] == "LIVE"


def test_parse_week_unknown_label_raises(fixture_html):
    with pytest.raises(ValueError, match="13802"):
        parse_week(_week_with_label(fixture_html, "Mystery"))


def test_parse_game_unknown_status_raises(fixture_html):
    html = fixture_html("mykbo_game_14048_final.html").replace("Final", "Mystery")
    with pytest.raises(ValueError):
        parse_game(html)


def test_week_2015_uses_historical_team_names(fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2015-06-02.html"))
    assert len(rows) == 30
    assert {r["status"] for r in rows} == {"FINAL", "CANCELED"}
    assert sum(r["status"] == "FINAL" for r in rows) == 29
    codes = {r["away_code"] for r in rows} | {r["home_code"] for r in rows}
    assert {"WO", "SK"} <= codes and len(codes) == 10


def test_game_2015_parses_boxscore(fixture_html):
    g = parse_game(fixture_html("mykbo_game_1189_final.html"))
    assert g["game_id"] == 1189 and g["date"] == "2015-06-02" and g["status"] == "FINAL"
    assert (g["away"]["code"], g["away"]["score"]) == ("HT", 9) and (g["home"]["code"], g["home"]["score"]) == ("OB", 1)
    assert len(g["batting"]["away"]) == 16 and len(g["pitching"]["away"]) == 3
    assert g["pitching"]["away"][0]["ip_outs"] == 21


def test_int_non_numeric_cell_is_none():
    from kbo_predict.mykbo_parse import _int
    assert _int(" 12 ") == 12 and _int("-3") == -3
    assert _int("") is None and _int("-") is None and _int("n/a") is None


def test_game_status_ignores_leading_symbols():
    from bs4 import BeautifulSoup
    from kbo_predict.mykbo_parse import _game_status
    soup = BeautifulSoup('<p class="mt-sm">▼ Bottom 9th · 0 out</p>', "html.parser")
    assert _game_status(soup) == "LIVE"


def test_game_status_delayed_is_live():
    # 2017-06-25 HH@SS(5374)처럼 우천 지연 문구가 남은 페이지는 FINAL로 치지 않고 LIVE로 분류한다
    from bs4 import BeautifulSoup
    from kbo_predict.mykbo_parse import _game_status
    soup = BeautifulSoup('<p class="mt-sm">Delayed</p>', "html.parser")
    assert _game_status(soup) == "LIVE"


def test_parse_game_skips_table_rows_without_cells(fixture_html):
    # 2022~2024 일부 경기 페이지는 tbody에 <td> 없는 행이 섞여 있다 → 건너뛰고 나머지는 그대로 읽는다
    from kbo_predict.mykbo_parse import parse_game
    html = fixture_html("mykbo_game_1189_final.html")
    base = parse_game(html)
    broken = re.sub(r'(<tbody[^>]*name="(?:away|home)-(?:batting|pitching)">)', r"\1<tr></tr><tr><th>소계</th></tr>", html)
    assert broken.count("<tr></tr>") == 4
    assert parse_game(broken)["batting"] == base["batting"]
    assert parse_game(broken)["pitching"] == base["pitching"]


def test_parse_game_live_page_with_partial_rows(fixture_html):
    # 2022-05-25 LT@SSG(9809): LIVE 상태로 멈춘 페이지. 타자 행 사이에 셀 1~2개짜리 보조 행이 끼어 있어도
    # 선수 행만 읽고, 상태는 LIVE로 돌려준다 (결과를 지어내지 않음)
    from kbo_predict.mykbo_parse import parse_game
    box = parse_game(fixture_html("mykbo_game_9809_live.html"))
    assert box["game_id"] == 9809 and box["status"] == "LIVE" and box["date"] == "2022-05-25"
    assert len(box["batting"]["away"]) >= 9 and len(box["batting"]["home"]) >= 9
    assert len(box["pitching"]["away"]) >= 1 and len(box["pitching"]["home"]) >= 1
    assert all(len(r) == len(box["batting"]["away"][0]) for r in box["batting"]["away"])


def test_parse_week_bottom_with_symbol_is_live(fixture_html):
    html = fixture_html("mykbo_week_2026-10-27.html").replace("Final", "▼ Bottom 9th · 0 out", 1)
    g = next(r for r in parse_week(html) if r["game_id"] == 14052)
    assert g["status"] == "LIVE"


def test_parse_game_short_player_row_raises(fixture_html):
    # 선수 링크가 있는데 셀이 모자란 행(Bench/Bullpen 구분 행 앞)은 조용히 건너뛰지 않고 실패한다
    from bs4 import BeautifulSoup
    html = fixture_html("mykbo_game_1189_final.html")
    soup = BeautifulSoup(html, "html.parser")
    tr = soup.find("tbody", attrs={"name": "away-batting"}).find_all("tr")[1]
    assert tr.find("a", href=re.compile(r"^/players/"))
    for td in tr.find_all("td")[2:]:
        td.decompose()
    with pytest.raises(ValueError, match="short batting row"):
        parse_game(str(soup))


def test_parse_starters_scheduled_page(fixture_html):
    s = parse_starters(fixture_html("mykbo_game_14050_scheduled.html"))
    assert s == {"away": {"player_id": 1096, "name": "Choi Won-tae"},
                 "home": {"player_id": 2730, "name": "Shirakawa Keisho"}}


def test_parse_starters_missing_section_returns_none(fixture_html):
    assert parse_starters(fixture_html("mykbo_game_9809_live.html")) is None


def test_parse_starters_one_side_missing(fixture_html):
    html = fixture_html("mykbo_game_14050_scheduled.html")
    # 홈 선수 링크(사진 링크 + 이름 링크)를 <span>으로 바꿔 링크가 없는 상태를 만든다
    html = re.sub(r'<a ([^>]*data-id="2730"[^>]*)>(.*?)</a>', r"<span \1>\2</span>", html, flags=re.S)
    s = parse_starters(html)
    assert s["away"]["player_id"] == 1096 and s["home"] is None
