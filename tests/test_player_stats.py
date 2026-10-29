"""player_stats: 합성 박스스코어로 집계 규칙을 확인한다. (가짜 시즌은 2025 - 2030은 REGULAR_SEASON에 없다)"""
import pytest

from kbo_predict import raw_store
from kbo_predict.player_stats import batting_seasons, korean_names, pitching_seasons

S = 2025


def brow(pid, pos="CF", ab=4, bb=0, hbp=0, doubles=1, sb=0):
    return {"order": 1, "player_id": pid, "name": f"n{pid}", "pos": pos, "ab": ab, "r": 0, "h": 1, "hr": 0,
            "rbi": 0, "bb": bb, "so": 0, "hbp": hbp, "doubles": doubles, "triples": 0, "sb": sb}


def prow(pid, order=1, ip_outs=18):
    return {"order": order, "player_id": pid, "name": f"p{pid}", "ip_outs": ip_outs, "np": 90, "r": 2, "er": 2,
            "h": 5, "hr": 0, "so": 6, "bb": 2, "hbp": 1}


def box(gid, date, away, home, bat_away, bat_home, pit_away, pit_home, names):
    return {"game_id": gid, "date": date, "status": "FINAL",
            "away": {"code": away, "name": away, "score": 1}, "home": {"code": home, "name": home, "score": 2},
            "batting": {"away": bat_away, "home": bat_home}, "pitching": {"away": pit_away, "home": pit_home},
            "names_ko": names}


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
    games = [{k: b[k] for k in ("game_id", "date", "status", "home", "away")} for b in boxes]
    monkeypatch.setattr(raw_store, "load_games", lambda season: games if season == S else [])
    monkeypatch.setattr(raw_store, "load_boxscores",
                        lambda season: {b["game_id"]: b for b in boxes} if season == S else {})


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


def test_korean_names_majority(fake_raw):               # 1: 두 경기 모두 "김철수" -> 채택; 3: "박a"/"박b" 반반 -> 제외
    names = korean_names([S])
    assert names[1] == "김철수" and 3 not in names


def test_postseason_excluded(fake_raw):
    df = batting_seasons([S]).set_index("player_id")
    assert df.loc[1, "ab"] == 7 and df.loc[1, "games"] == 2
    assert 5 in df.index and df.loc[5, "games"] == 2      # 11월 경기 제외 확인
