from kbo_predict.raw_store import append_records, load_games, load_records, upsert_games


def test_upsert_games_dedupes_by_game_id_and_sorts(tmp_data_dir, fixture_json):
    games = fixture_json("schedule_2026-10-20_28.json")["result"]["games"]
    assert upsert_games(2026, games) == 4
    assert upsert_games(2026, games) == 0
    changed = dict(games[1], statusCode="RESULT")  # 10-25 경기 상태 변경
    assert upsert_games(2026, [changed]) == 1
    loaded = load_games(2026)
    assert len(loaded) == 4 and [g["gameDate"] for g in loaded] == sorted(g["gameDate"] for g in loaded)
    assert next(g for g in loaded if g["gameId"] == changed["gameId"])["statusCode"] == "RESULT"


def test_append_records_skips_existing(tmp_data_dir, fixture_json):
    rec = fixture_json("record_33331020HTLG02026.json")["result"]["recordData"]
    assert append_records(2026, {"33331020HTLG02026": rec}) == 1
    assert append_records(2026, {"33331020HTLG02026": rec}) == 0
    assert load_records(2026)["33331020HTLG02026"]["gameInfo"]["hCode"] == "LG"


def test_load_empty(tmp_data_dir):
    assert load_games(2026) == [] and load_records(2026) == {}
