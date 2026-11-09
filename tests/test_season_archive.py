"""시즌 기록실(season_archive): 우승 판정, 시리즈 이름, 우천 취소만 남기기, 지난 시즌 목록, 매일 갱신."""
import json
from pathlib import Path

import pytest

from kbo_predict import raw_store
from kbo_predict import season_archive as sa

ROOT = Path(__file__).resolve().parents[1]
CHAMPIONS = {2015: "OB", 2016: "OB", 2017: "HT", 2018: "SK", 2019: "OB", 2020: "NC", 2021: "KT", 2022: "SK",
             2023: "LG", 2024: "HT", 2025: "LG", 2026: "SS"}  # 실제 한국시리즈 우승 팀


def test_committed_index_matches_real_champions():
    idx = json.loads((ROOT / "data" / "public" / "seasons" / "index.json").read_text(encoding="utf-8"))
    assert {r["season"]: r["champion"] for r in idx["seasons"]} == CHAMPIONS


@pytest.mark.parametrize("season", [2021, 2026])
def test_series_names_and_wildcard_head_start(season):
    rec = sa.season_record(season)
    names = [s["name"] for s in rec["postseason"]]
    assert names[-4:] == ["와일드카드", "준플레이오프", "플레이오프", "한국시리즈"]
    if season == 2021:
        assert names[0] == "순위 결정전"                               # KT-삼성 1위 결정전 단판
    wc = rec["postseason"][names.index("와일드카드")]
    assert wc["head_start"] == [1, 0] and wc["teams"][0] == next(r["code"] for r in rec["standings"] if r["rank"] == 4)


def test_only_rainouts_before_the_last_game_are_kept():
    rec = sa.season_record(2021)                                       # 6·7차전은 열리지 않아 취소로 남았다
    ks = rec["postseason"][-1]
    assert all(g["status"] == "FINAL" for g in ks["games"]) and ks["wins"] == [4, 0]
    rec = sa.season_record(2026)                                       # 플레이오프 1차전 우천 취소(10-25)는 남긴다
    po = next(s for s in rec["postseason"] if s["name"] == "플레이오프")
    assert [g["date"] for g in po["games"] if g["status"] == "CANCELED"] == ["2026-10-25"]


def test_no_champion_while_korean_series_is_running(monkeypatch):
    real = raw_store.load_games
    monkeypatch.setattr(raw_store, "load_games", lambda s: [g for g in real(s) if g["date"] <= "2026-11-06"])
    rec = sa.season_record(2026)
    assert rec["postseason"][-1]["name"] == "한국시리즈" and rec["postseason"][-1]["wins"] == [1, 2]
    assert rec["champion"] is None and rec["runner_up"] is None
    monkeypatch.setattr(raw_store, "load_games", lambda s: [g for g in real(s) if g["date"] <= "2026-10-17"])
    assert [s["name"] for s in sa.season_record(2026)["postseason"]] == ["와일드카드", "준플레이오프"]  # 대진표 이름은 앞에서부터


def test_update_writes_season_schedule_and_finished_index(tmp_path, monkeypatch):
    real = raw_store.load_games
    rec = sa.update(tmp_path, 2026)
    assert (tmp_path / "2026.json").exists() and (tmp_path / "schedule_2026.json").exists()
    sched = json.loads((tmp_path / "schedule_2026.json").read_text(encoding="utf-8"))
    assert len(sched) > 700 and {"game_id", "date", "home", "away", "status", "regular"} <= set(sched[0])
    assert [r["season"] for r in json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))["seasons"]] == [2026]
    monkeypatch.setattr(raw_store, "load_games", lambda s: [g for g in real(s) if g["date"] <= "2026-11-06"])
    sa.update(tmp_path, 2026)                                          # 진행 중이면 목록에서 빠진다
    assert json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))["seasons"] == []
    assert rec["champion"] == "SS"


def test_standings_tiebreak_and_games_back():
    table = sa.standings(2026, raw_store.load_games(2026))
    assert [r["rank"] for r in table] == list(range(1, 11)) and table[0]["gb"] == 0.0
    assert table[0]["code"] == "KT" and table[1]["code"] == "SS" and table[1]["gb"] == 8.0
