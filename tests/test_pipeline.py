import json
from datetime import date

import pytest
import requests

from kbo_predict.mykbo_parse import parse_week
from kbo_predict.raw_store import upsert_games
from scripts.run_pipeline import run
import scripts.run_pipeline as rp

META = {"generated_at": "2026-10-29T09:00:00+09:00", "model_version": "v0.1", "commit_sha": None, "run_url": None}


def test_run_writes_all_public_files_on_game_day(tmp_data_dir, bundle_path, fixture_html):
    upsert_games(2026, parse_week(fixture_html("mykbo_week_2026-10-27.html")))
    out = run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert out["games_today"] == 1
    latest = json.loads((tmp_data_dir / "public/latest.json").read_text(encoding="utf-8"))
    assert latest["date"] == "2026-10-29" and latest["games"][0]["home"]["code"] == "HT" and latest["mode"] == "live"
    assert (tmp_data_dir / "public/status.json").exists() and (tmp_data_dir / "public/history.csv").exists()


def test_run_on_empty_day_touches_only_status(tmp_data_dir, bundle_path, fixture_html):
    upsert_games(2026, parse_week(fixture_html("mykbo_week_2026-10-27.html")))
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    before = (tmp_data_dir / "public/latest.json").read_bytes()
    hist_before = (tmp_data_dir / "public/history.csv").read_bytes()
    run(date(2026, 10, 28), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert (tmp_data_dir / "public/latest.json").read_bytes() == before
    assert (tmp_data_dir / "public/history.csv").read_bytes() == hist_before
    assert json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))["next_game_date"] == "2026-10-29"


def _row(gid, d, status="FINAL", hs=9, as_=0, home=("Kia Tigers", "HT"), away=("Samsung Lions", "SS"), **kw):
    r = {"game_id": gid, "date": d, "season": 2026, "home": home[0], "away": away[0], "home_code": home[1],
         "away_code": away[1], "home_score": hs, "away_score": as_, "status": status, "status_note": None,
         "time_kst": None, "stadium": None}
    r.update(kw)
    return r


def _prob(tmp_data_dir, bundle_path):
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    latest = json.loads((tmp_data_dir / "public/latest.json").read_text(encoding="utf-8"))
    return next(g for g in latest["games"] if g["game_id"] == 14050)["home_win_prob"]


def _seed(fixture_html, *extra):
    upsert_games(2026, parse_week(fixture_html("mykbo_week_2026-10-27.html")) + list(extra))


def test_same_day_final_not_in_state_and_not_in_history(tmp_path, monkeypatch, bundle_path, fixture_html):
    base = _row(9001, "2026-09-01")  # 정규시즌 기준 경기: 상태에 반영되어야 함
    d1, d2 = tmp_path / "a" / "data", tmp_path / "b" / "data"
    monkeypatch.setenv("KBO_DATA_DIR", str(d1))
    _seed(fixture_html, base)
    p_without = _prob(d1, bundle_path)
    monkeypatch.setenv("KBO_DATA_DIR", str(d2))
    extra = _row(9002, "2026-10-29", hs=0, as_=15, time_kst="17:00", stadium="Gwangju")
    _seed(fixture_html, base, extra)
    p_with = _prob(d2, bundle_path)
    assert p_with == p_without
    import pandas as pd
    hist = pd.read_csv(d2 / "public/history.csv", dtype={"game_id": str})
    assert hist.game_id.tolist() == ["14050"]
    latest = json.loads((d2 / "public/latest.json").read_text(encoding="utf-8"))
    fin = next(g for g in latest["games"] if g["game_id"] == 9002)
    assert fin["status"] == "FINAL" and fin["time"] == "17:00" and fin["stadium"] == "Gwangju"


def test_exhibition_and_baseline_state(tmp_path, monkeypatch, bundle_path, fixture_html):
    base = _row(9001, "2026-09-01")
    exh = _row(9003, "2026-03-21", hs=0, as_=15)
    probs = {}
    for name, extras in (("none", ()), ("base", (base,)), ("exh", (base, exh))):
        d = tmp_path / name / "data"
        monkeypatch.setenv("KBO_DATA_DIR", str(d))
        _seed(fixture_html, *extras)
        probs[name] = _prob(d, bundle_path)
    assert probs["base"] != probs["none"]
    assert probs["exh"] == probs["base"]


def test_canceled_game_shown_but_not_in_history(tmp_data_dir, bundle_path, fixture_html):
    canc = _row(9004, "2026-10-29", status="CANCELED", hs=None, as_=None, status_note="우천 취소")
    _seed(fixture_html, canc)
    out = run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert out["games_today"] == 1
    latest = json.loads((tmp_data_dir / "public/latest.json").read_text(encoding="utf-8"))
    g = next(g for g in latest["games"] if g["game_id"] == 9004)
    assert g["status"] == "CANCELED" and g["home_win_prob"] is None and g["factors"] == []
    assert g["status_note"] == "우천 취소"
    assert "status_note" in next(g for g in latest["games"] if g["game_id"] == 14050)
    hist = (tmp_data_dir / "public/history.csv").read_text(encoding="utf-8")
    assert "9004" not in hist and "14050" in hist
    assert json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))["games_today"] == 1


def test_only_canceled_day_still_writes_latest(tmp_data_dir, bundle_path, fixture_html):
    _seed(fixture_html, _row(9004, "2026-10-28", status="CANCELED", hs=None, as_=None))
    out = run(date(2026, 10, 28), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert out["games_today"] == 0
    latest = json.loads((tmp_data_dir / "public/latest.json").read_text(encoding="utf-8"))
    assert latest["date"] == "2026-10-28" and latest["games"][0]["status"] == "CANCELED"


def _boom(*a, **k):
    raise requests.ConnectionError("down")


def test_fetch_failure_with_stored_games_continues(tmp_data_dir, bundle_path, fixture_html, monkeypatch):
    _seed(fixture_html)
    monkeypatch.setattr(rp, "collect_range", _boom)
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    assert (tmp_data_dir / "public/status.json").exists()


def test_fetch_failure_with_empty_store_raises(tmp_data_dir, bundle_path, monkeypatch):
    monkeypatch.setattr(rp, "collect_range", _boom)
    with pytest.raises(requests.ConnectionError):
        run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
