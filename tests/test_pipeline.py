import json
from datetime import date

from kbo_predict.mykbo_parse import parse_week
from kbo_predict.raw_store import upsert_games
from scripts.run_pipeline import run

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
    run(date(2026, 10, 28), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert (tmp_data_dir / "public/latest.json").read_bytes() == before
    assert json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))["next_game_date"] == "2026-10-29"
