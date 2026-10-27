from datetime import date

from kbo_predict import collect


def test_collect_range_fetches_records_only_for_new_results(monkeypatch, tmp_data_dir, fixture_json):
    sched = fixture_json("schedule_2026-10-20_28.json")["result"]["games"]  # RESULT 2개, BEFORE 1, STARTED 1
    monkeypatch.setattr(collect, "fetch_games", lambda *a, **k: sched)
    called = []
    monkeypatch.setattr(collect, "fetch_record", lambda gid, **k: called.append(gid) or {"gameInfo": {}})
    out = collect.collect_range(date(2026, 10, 20), date(2026, 10, 28))
    assert out == {"games": 4, "records": 2} and sorted(called) == ["33331020HTLG02026", "55551026HTSS02026"]
    called.clear()
    assert collect.collect_range(date(2026, 10, 20), date(2026, 10, 28))["records"] == 0 and called == []
