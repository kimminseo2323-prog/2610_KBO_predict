from kbo_predict.mykbo_parse import parse_game, parse_week
from kbo_predict.raw_store import append_boxscores, load_boxscores, load_games, upsert_games


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
