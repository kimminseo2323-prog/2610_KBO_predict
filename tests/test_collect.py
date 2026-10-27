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


def test_collect_range_splits_long_range_into_chunks(monkeypatch, tmp_data_dir):
    calls = []
    monkeypatch.setattr(collect, "fetch_games", lambda a, b, **k: calls.append((a, b)) or [])
    collect.collect_range(date(2026, 3, 1), date(2026, 10, 31))
    assert calls[0][0] == date(2026, 3, 1) and calls[-1][1] == date(2026, 10, 31)
    assert all((b - a).days < 31 for a, b in calls)
    assert all(calls[i][1].toordinal() + 1 == calls[i + 1][0].toordinal() for i in range(len(calls) - 1))
