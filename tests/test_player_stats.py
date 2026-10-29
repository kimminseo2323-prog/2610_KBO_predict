"""player_stats: 합성 박스스코어로 집계 규칙을 확인한다. (가짜 시즌은 2025 - 2030은 REGULAR_SEASON에 없다)"""
import pytest

from kbo_predict import raw_store
from kbo_predict.player_stats import batting_seasons, korean_names, pitching_seasons

S = 2025


def brow(pid, pos="CF", ab=4, bb=0, hbp=0, doubles=1, sb=0, name=None):
    return {"order": 1, "player_id": pid, "name": name or f"n{pid}", "pos": pos, "ab": ab, "r": 0, "h": 1, "hr": 0,
            "rbi": 0, "bb": bb, "so": 0, "hbp": hbp, "doubles": doubles, "triples": 0, "sb": sb}


def prow(pid, order=1, ip_outs=18):
    return {"order": order, "player_id": pid, "name": f"p{pid}", "ip_outs": ip_outs, "np": 90, "r": 2, "er": 2,
            "h": 5, "hr": 0, "so": 6, "bb": 2, "hbp": 1}


def box(gid, date, away, home, bat_away, bat_home, pit_away, pit_home, names):
    return {"game_id": gid, "date": date, "status": "FINAL",
            "away": {"code": away, "name": away, "score": 1}, "home": {"code": home, "name": home, "score": 2},
            "batting": {"away": bat_away, "home": bat_home}, "pitching": {"away": pit_away, "home": pit_home},
            "names_ko": names}


def install(monkeypatch, boxes):
    games = [{k: b[k] for k in ("game_id", "date", "status", "home", "away")} for b in boxes]
    monkeypatch.setattr(raw_store, "load_games", lambda season: games if season == S else [])
    monkeypatch.setattr(raw_store, "load_boxscores",
                        lambda season: {b["game_id"]: b for b in boxes} if season == S else {})


@pytest.fixture
def fake_raw(monkeypatch):
    boxes = [
        box(1, "2025-04-01", "LG", "HT", [brow(1, ab=4, bb=1, doubles=1, sb=1), brow(2, pos="LF")],
            [brow(5)], [prow(10)], [prow(11)], {"1": "김철수", "3": "박a"}),
        box(2, "2025-04-02", "LG", "HT", [brow(1, ab=3, bb=1, doubles=1, sb=0), brow(2, pos="LF")],
            [brow(5)], [prow(10, order=2, ip_outs=3)], [prow(11)], {"1": "김철수", "3": "박b"}),
        box(3, "2025-04-03", "HT", "LG", [brow(2, pos="1B", doubles=None, sb=None)], [brow(6)],
            [prow(12)], [prow(13)], {}),
        # 정규시즌 종료 후(포스트시즌): 타자 집계에서 제외
        box(4, "2025-11-20", "LG", "HT", [brow(1, ab=100)], [brow(5)], [prow(10)], [prow(11)], {}),
    ]
    install(monkeypatch, boxes)


def test_batting_sums_and_pa(fake_raw):
    df = batting_seasons([S]).set_index("player_id")
    assert df.loc[1, ["pa", "doubles", "sb", "games"]].tolist() == [9, 2, 1, 2]


def test_traded_player_team_is_majority(fake_raw):      # 선수 2: LG 2경기, HT 1경기 -> LG
    df = batting_seasons([S]).set_index("player_id")
    assert df.loc[2, "team"] == "LG"
    assert df.loc[2, "pos"] == "LF"
    assert (df.loc[2, "games"], df.loc[2, "games_with_records"]) == (3, 2)
    assert df.loc[2, "sb"] == 0                           # None은 0으로 더한다


def test_pitching_bf_and_starts(fake_raw):
    row = pitching_seasons([S]).set_index("player_id").loc[10]
    assert (row["bf"], row["starts"], row["games"]) == (row["ip_outs"] + row["h"] + row["bb"] + row["hbp"], 1, 2)


def test_korean_names_majority(fake_raw):               # 1: 두 경기 모두 "김철수" -> 채택; 3: "박a"/"박b" 반반 -> 제외 (2표뿐이라 전체 합 규칙)
    names = korean_names([S])
    assert names[1] == "김철수" and 3 not in names


def test_postseason_excluded(fake_raw):
    df = batting_seasons([S]).set_index("player_id")
    assert df.loc[1, "ab"] == 7 and df.loc[1, "games"] == 2
    assert 5 in df.index and df.loc[5, "games"] == 2      # 11월 경기 제외 확인


def test_name_is_last_games_row_and_pos_tie_first_seen(monkeypatch):
    # 선수 7: 1경기 "Old Name"/CF, 2경기 "New Name"/LF -> 이름은 마지막 경기 값, 포지션은 1:1 동률이라 먼저 나온 CF
    install(monkeypatch, [
        box(1, "2025-04-01", "LG", "HT", [brow(7, pos="CF", name="Old Name")], [], [], [], {}),
        box(2, "2025-04-02", "LG", "HT", [brow(7, pos="LF", name="New Name")], [], [], [], {}),
    ])
    row = batting_seasons([S]).set_index("player_id").loc[7]
    assert (row["name"], row["pos"]) == ("New Name", "CF")


def test_team_tie_goes_to_most_recent_team(monkeypatch):
    # 선수 8: LG, HT, LG, HT, SS 순서 -> LG 2·HT 2 동률. 가장 최근 출전한 HT (마지막 팀 SS는 1경기라 후보 아님)
    order = ["LG", "HT", "LG", "HT", "SS"]
    install(monkeypatch, [box(i + 1, f"2025-04-0{i + 1}", t, "OB", [brow(8)], [], [], [], {})
                          for i, t in enumerate(order)])
    assert batting_seasons([S]).set_index("player_id").loc[8, "team"] == "HT"


def test_two_rows_in_one_game_count_one_game(monkeypatch):
    # 한 경기에 같은 선수 줄이 둘: 경기 수는 1, 기록은 둘 다 더한다
    install(monkeypatch, [
        box(1, "2025-04-01", "LG", "HT", [brow(9, ab=3), brow(9, ab=1)], [], [prow(20), prow(20, order=2)], [], {}),
    ])
    bat = batting_seasons([S]).set_index("player_id").loc[9]
    assert (bat["games"], bat["games_with_records"], bat["ab"]) == (1, 1, 4)
    pit = pitching_seasons([S]).set_index("player_id").loc[20]
    assert (pit["games"], pit["starts"], pit["ip_outs"]) == (1, 1, 36)


def test_korean_names_single_vote_accepted(monkeypatch):
    install(monkeypatch, [box(1, "2025-04-01", "LG", "HT", [brow(9)], [], [], [], {"9": "홍길동"})])
    assert korean_names([S]) == {9: "홍길동"}


def _install_seasons(monkeypatch, names_by_season, *, postseason=None):
    """names_by_season = {season: [names_ko 딕셔너리, ...]} -> 이름 하나마다 정규시즌(6월) FINAL 경기 + 박스스코어 한 개.
    postseason = {season: [names_ko, ...]} -> 같은 모양의 11월(포스트시즌) FINAL 경기 (이름 투표에서 빠져야 한다)."""
    games, data = {}, {}
    for kind, month, src in (("reg", 6, names_by_season), ("post", 11, postseason or {})):
        for s, lst in src.items():
            for n in lst:
                gid = len(data.setdefault(s, {})) + 1
                games.setdefault(s, []).append({"game_id": gid, "date": f"{s}-{month:02d}-{gid:02d}", "status": "FINAL"})
                data[s][gid] = {"game_id": gid, "names_ko": n}
    monkeypatch.setattr(raw_store, "load_games", lambda season: games.get(season, []))
    monkeypatch.setattr(raw_store, "load_boxscores", lambda season: data.get(season, {}))


def test_korean_names_ignore_postseason_boxscores(monkeypatch):
    # 정규시즌 "가" 3표, 포스트시즌 박스스코어 "나" 5표 -> 정규시즌 표만 센다 ("가"). 포스트시즌에만 나온 선수는 이름 없음.
    _install_seasons(monkeypatch, {2024: [{"8": "가"}] * 3}, postseason={2024: [{"8": "나", "99": "포"}] * 5})
    assert korean_names([2024]) == {8: "가"}


def test_korean_names_renamed_player_uses_latest_season(monkeypatch):
    # 선수 452: 2019·2020에 옛 이름 5표씩(합계 10), 2021에 새 이름 4표 -> 전체 합으로는 새 이름 29%지만
    # 3표 이상인 가장 최근 시즌(2021)의 다수 이름을 쓴다. 2022의 1표(옛 이름)는 3표 미만 시즌이라 보지 않는다.
    _install_seasons(monkeypatch, {
        2019: [{"452": "한동민"}] * 5, 2020: [{"452": "한동민"}] * 5,
        2021: [{"452": "한유섬"}] * 4, 2022: [{"452": "한동민"}],
    })
    assert korean_names([2019, 2020, 2021, 2022]) == {452: "한유섬"}


def test_korean_names_latest_season_split_is_none(monkeypatch):
    # 가장 최근 3표 이상 시즌이 반반(2:2)이면 60% 미만 -> 이름 없음 (앞 시즌의 다수 이름으로 돌아가지 않는다)
    _install_seasons(monkeypatch, {
        2019: [{"5": "가"}] * 5,
        2020: [{"5": "가"}, {"5": "가"}, {"5": "나"}, {"5": "나"}],
    })
    assert korean_names([2019, 2020]) == {}


def test_korean_names_pools_when_no_season_has_three_votes(monkeypatch):
    # 어느 시즌도 3표가 안 되면 모든 시즌을 합친다: "가" 3표 / "나" 1표 = 75% -> "가".
    _install_seasons(monkeypatch, {
        2019: [{"6": "가", "7": "다"}, {"6": "가", "7": "나"}], 2020: [{"6": "가"}, {"6": "나"}],
    })
    assert korean_names([2019, 2020]) == {6: "가"}
    _install_seasons(monkeypatch, {2019: [{"7": "다"}, {"7": "나"}], 2020: [{"7": "나"}, {"7": "다"}]})
    assert korean_names([2019, 2020]) == {}           # 2:2는 50% -> 제외
