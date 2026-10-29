from kbo_predict.mykbo_parse import parse_game, parse_week
from kbo_predict.raw_store import append_boxscores, boxscores_dir, rewrite_boxscores, load_boxscores, load_games, upsert_games


def test_upsert_games_dedupes_and_sorts(tmp_data_dir, fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2026-10-27.html"))
    assert upsert_games(2026, rows) == 4
    changed = dict(next(r for r in rows if r["game_id"] == 14050), status="FINAL", away_score=2, home_score=4)
    assert upsert_games(2026, [changed]) == 1 and upsert_games(2026, [changed]) == 0
    loaded = load_games(2026)
    assert len(loaded) == 4 and [(g["date"], g["game_id"]) for g in loaded] == sorted((g["date"], g["game_id"]) for g in loaded)
    assert next(g for g in loaded if g["game_id"] == 14050)["status"] == "FINAL"


def test_append_boxscores_skips_existing(tmp_data_dir, fixture_html):
    g = parse_game(fixture_html("mykbo_game_14048_final.html"))
    assert append_boxscores(2026, {14048: g}) == 1 and append_boxscores(2026, {14048: g}) == 0
    assert load_boxscores(2026)[14048]["home"]["code"] == "SS"


def test_upsert_keeps_stored_time_and_stadium_when_new_is_none(tmp_data_dir, fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2026-10-27.html"))
    upsert_games(2026, rows)
    live = dict(next(r for r in rows if r["game_id"] == 14050), status="LIVE", time_kst=None, stadium=None, home_score=1, away_score=0)
    assert upsert_games(2026, [live]) == 1
    g = next(g for g in load_games(2026) if g["game_id"] == 14050)
    assert g["status"] == "LIVE" and g["time_kst"] == "18:30" and g["stadium"] == "Gwangju"


def test_append_boxscores_splits_files_by_month(tmp_data_dir, fixture_html):
    from kbo_predict.raw_store import boxscores_dir
    g = parse_game(fixture_html("mykbo_game_14048_final.html"))      # 2026-10-26
    g_old = parse_game(fixture_html("mykbo_game_1189_final.html"))   # 2015-06-02
    assert append_boxscores(2026, {14048: g}) == 1
    assert append_boxscores(2015, {1189: g_old}) == 1
    assert sorted(p.name for p in boxscores_dir(2026).iterdir()) == ["2026-10.jsonl.gz"]
    assert sorted(p.name for p in boxscores_dir(2015).iterdir()) == ["2015-06.jsonl.gz"]
    assert load_boxscores(2026)[14048]["home"]["code"] == "SS"
    assert load_boxscores(2015)[1189]["away"]["code"] == "HT"


def test_load_boxscores_merges_all_months(tmp_data_dir, fixture_html):
    g = parse_game(fixture_html("mykbo_game_14048_final.html"))
    g2 = dict(g, date="2026-09-01")
    assert append_boxscores(2026, {14048: g, 99999: g2}) == 2
    assert set(load_boxscores(2026)) == {14048, 99999}
    assert append_boxscores(2026, {14048: g}) == 0


def test_available_seasons_lists_dirs_with_games(tmp_data_dir, fixture_html):
    from kbo_predict.raw_store import available_seasons
    assert available_seasons() == []
    upsert_games(2026, parse_week(fixture_html("mykbo_week_2026-10-27.html")))
    upsert_games(2015, parse_week(fixture_html("mykbo_week_2015-06-02.html")))
    assert available_seasons() == [2015, 2026]


def test_upsert_starters_dedupes_and_sorts(tmp_data_dir):
    from kbo_predict.raw_store import load_starters, starters_path, upsert_starters

    p = {"player_id": 1, "name": "A"}
    r1 = {"game_id": 20, "date": "2026-10-29", "fetched_at": "t1", "home": p, "away": None}
    r2 = {"game_id": 10, "date": "2026-10-30", "fetched_at": "t1", "home": None, "away": p}
    r0 = {"game_id": 30, "date": "2026-10-28", "fetched_at": "t1", "home": None, "away": None}
    assert upsert_starters(2026, [r1, r2]) == 2
    assert upsert_starters(2026, [r1]) == 0
    before = starters_path(2026).read_bytes()
    assert upsert_starters(2026, [dict(r1, fetched_at="t2")]) == 0  # 선발이 같으면 fetched_at만 달라도 변경 아님
    assert starters_path(2026).read_bytes() == before and load_starters(2026)[20]["fetched_at"] == "t1"
    assert upsert_starters(2026, [dict(r1, home={"player_id": 2, "name": "B"}), r0]) == 2
    loaded = load_starters(2026)
    assert set(loaded) == {10, 20, 30} and loaded[20]["home"]["player_id"] == 2
    import json
    lines = [json.loads(x) for x in starters_path(2026).read_text(encoding="utf-8").splitlines()]
    assert [(x["date"], x["game_id"]) for x in lines] == [("2026-10-28", 30), ("2026-10-29", 20), ("2026-10-30", 10)]
    assert load_starters(2025) == {}


def test_upsert_starters_never_downgrades_known_starter(tmp_data_dir):
    """(a) 섹션 없는 재수집(양쪽 None)은 저장된 선발을 지우지 않는다 — 변경 0, 파일 그대로.
    (b) 홈만 새로 발표되면 홈만 바뀌고 이미 알던 원정은 유지된다."""
    from kbo_predict.raw_store import load_starters, starters_path, upsert_starters

    a, h = {"player_id": 1, "name": "A"}, {"player_id": 2, "name": "H"}
    assert upsert_starters(2026, [{"game_id": 7, "date": "2026-10-29", "fetched_at": "t1", "away": a, "home": None}]) == 1
    before = starters_path(2026).read_bytes()
    tba = {"game_id": 7, "date": "2026-10-29", "fetched_at": "t2", "away": None, "home": None}
    assert upsert_starters(2026, [tba]) == 0
    assert starters_path(2026).read_bytes() == before
    assert upsert_starters(2026, [dict(tba, fetched_at="t3", home=h)]) == 1
    assert load_starters(2026)[7] == {"game_id": 7, "date": "2026-10-29", "fetched_at": "t3", "away": a, "home": h}
    assert upsert_starters(2026, [dict(tba, fetched_at="t4")]) == 0  # 둘 다 알려진 뒤의 TBA 재수집도 변경 0
    assert load_starters(2026)[7]["away"] == a and load_starters(2026)[7]["home"] == h


def test_rewrite_boxscores_replaces_month_files(tmp_data_dir):
    append_boxscores(2030, {1: {"game_id": 1, "date": "2030-04-01"}, 2: {"game_id": 2, "date": "2030-05-01"}})
    assert rewrite_boxscores(2030, {2: {"game_id": 2, "date": "2030-05-01", "x": 1}}) == 1
    assert load_boxscores(2030) == {2: {"game_id": 2, "date": "2030-05-01", "x": 1}}
    assert not (boxscores_dir(2030) / "2030-04.jsonl.gz").exists()


def test_rewrite_boxscores_empty_raises_and_keeps_files(tmp_data_dir):
    import pytest
    append_boxscores(2030, {1: {"game_id": 1, "date": "2030-04-01"}})
    with pytest.raises(ValueError):
        rewrite_boxscores(2030, {})
    assert load_boxscores(2030) == {1: {"game_id": 1, "date": "2030-04-01"}}


def test_rewrite_boxscores_leaves_no_tmp_files(tmp_data_dir):
    append_boxscores(2030, {1: {"game_id": 1, "date": "2030-04-01"}})
    rewrite_boxscores(2030, {1: {"game_id": 1, "date": "2030-04-01", "x": 2}})
    assert sorted(p.name for p in boxscores_dir(2030).iterdir()) == ["2030-04.jsonl.gz"]


def test_upsert_games_atomic(tmp_data_dir, fixture_html, monkeypatch):
    """games.jsonl 바꿔치기(os.replace)가 실패해도 기존 파일은 그대로, .tmp는 남지 않는다."""
    import pytest

    from kbo_predict import raw_store

    rows = parse_week(fixture_html("mykbo_week_2026-10-27.html"))
    upsert_games(2026, rows[:2])
    path = raw_store.games_path(2026)
    before = path.read_bytes()

    def boom(src, dst):
        raise OSError("disk full")

    with monkeypatch.context() as m:  # undo()는 KBO_DATA_DIR까지 되돌리므로 이 블록만 바꾼다
        m.setattr(raw_store.os, "replace", boom)
        with pytest.raises(OSError, match="disk full"):
            upsert_games(2026, rows)
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["games.jsonl"]
    assert upsert_games(2026, rows) == len(rows) - 2 and len(load_games(2026)) == len(rows)
    assert sorted(p.name for p in path.parent.iterdir()) == ["games.jsonl"]
