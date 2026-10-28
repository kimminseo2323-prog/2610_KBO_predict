from datetime import date

import re
import time

import requests

from kbo_predict import collect, mykbo_client, raw_store
from kbo_predict.mykbo_parse import parse_week


def test_collect_range_fetches_boxscores_only_for_new_finals(monkeypatch, tmp_data_dir, fixture_html):
    fetched, week_kw = [], []

    def fake_fetch(path, **kw):
        fetched.append(path)
        if path.startswith("/schedule/week_of/"):
            week_kw.append(kw.get("use_cache"))
        if path.startswith("/schedule/week_of/"):
            return fixture_html("mykbo_week_2026-10-27.html")
        # 어떤 경기 페이지든 이 fixture. 요청한 경기 id로 바꿔 collect의 game_id 일치 검사를 통과시킨다.
        game_id = path.split("/")[2].split("-")[0]
        return fixture_html("mykbo_game_14048_final.html").replace("/games/14048-", f"/games/{game_id}-")

    monkeypatch.setattr(collect, "fetch_html", fake_fetch)
    out = collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0)
    assert out["games"] == 4 and out["boxscores"] == 1  # FINAL은 14052 하나
    assert [p for p in fetched if p.startswith("/games/")] == ["/games/14052-Kia-vs-Samsung-20261027"]
    fetched.clear()
    assert collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0)["boxscores"] == 0
    assert not [p for p in fetched if p.startswith("/games/")]
    assert week_kw == [False, False]  # 주간 페이지는 캐시를 쓰지 않는다


def test_collect_continues_after_one_bad_game_page(monkeypatch, tmp_data_dir, fixture_html):
    def fake_fetch(path, **kw):
        if path.startswith("/schedule/week_of/"):
            return fixture_html("mykbo_week_2015-06-02.html")
        game_id = path.split("/")[2].split("-")[0]
        if game_id == "1189":
            return "<html><body>Checking your browser</body></html>"   # 미인식 페이지
        return fixture_html("mykbo_game_1189_final.html").replace("/games/1189-", f"/games/{game_id}-")
    monkeypatch.setattr(collect, "fetch_html", fake_fetch)
    out = collect.collect_range(date(2015, 6, 2), date(2015, 6, 8), sleep_s=0)
    assert out["games"] == 30 and out["boxscores"] == 28
    assert [e["game_id"] for e in out["errors"]] == [1189]
    assert "unrecognised" in out["errors"][0]["error"] and out["errors"][0]["path"].startswith("/games/1189-")


def test_stale_live_row_is_finalised_from_game_page(monkeypatch, tmp_data_dir, fixture_html):
    week = fixture_html("mykbo_week_2026-10-27.html")
    # 14052(FINAL) 행을 LIVE처럼 보이게: 'Final' -> 'LIVE'
    week_live = week.replace("Final", "LIVE", 1)
    def fake_fetch(path, **kw):
        if path.startswith("/schedule/week_of/"):
            return week_live
        game_id = path.split("/")[2].split("-")[0]
        return fixture_html("mykbo_game_14048_final.html").replace("/games/14048-", f"/games/{game_id}-")
    monkeypatch.setattr(collect, "fetch_html", fake_fetch)
    out = collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0, today=date(2026, 11, 5))
    g = next(x for x in raw_store.load_games(2026) if x["game_id"] == 14052)
    assert g["status"] == "FINAL" and (g["away_score"], g["home_score"]) == (5, 1) and out["boxscores"] == 1


def test_recent_live_row_is_left_alone(monkeypatch, tmp_data_dir, fixture_html):
    # today가 경기 다음날이면 LIVE 그대로 두고 경기 페이지도 요청하지 않는다
    week_live = fixture_html("mykbo_week_2026-10-27.html").replace("Final", "LIVE", 1)
    fetched = []
    def fake_fetch(path, **kw):
        fetched.append(path)
        return week_live
    monkeypatch.setattr(collect, "fetch_html", fake_fetch)
    out = collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0, today=date(2026, 10, 28))
    g = next(x for x in raw_store.load_games(2026) if x["game_id"] == 14052)
    assert g["status"] == "LIVE" and out["boxscores"] == 0 and out["errors"] == []
    assert not [p for p in fetched if p.startswith("/games/")]


def test_season_cli_covers_march_to_november(monkeypatch):
    called = {}
    monkeypatch.setattr(collect, "collect_range", lambda f, t, **kw: called.update(f=f, t=t, **kw) or {})
    collect.main(["--season", "2015", "--sleep", "0"])
    assert (called["f"], called["t"], called["season"]) == (date(2015, 3, 1), date(2015, 11, 30), 2015)


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _real_fetch_env(monkeypatch, handler):
    """진짜 fetch_html(캐시 포함)을 쓰고 HTTP 계층만 가짜로 바꾼다. handler(path) -> html."""
    gets = []
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def fake_get(self, url, **kw):
        path = url.removeprefix(mykbo_client.BASE_URL)
        gets.append(path)
        return _Resp(handler(path))

    monkeypatch.setattr(requests.Session, "get", fake_get)
    return gets


def test_rerun_after_challenge_page_refetches_game(monkeypatch, tmp_data_dir, fixture_html):
    week = fixture_html("mykbo_week_2026-10-27.html")
    state = {"challenge": True}

    def handler(path):
        if path.startswith("/schedule/week_of/"):
            return week
        game_id = path.split("/")[2].split("-")[0]
        if state["challenge"] and game_id == "14052":
            return "<html><body>Checking your browser</body></html>"
        return fixture_html("mykbo_game_14048_final.html").replace("/games/14048-", f"/games/{game_id}-")

    gets = _real_fetch_env(monkeypatch, handler)
    first = collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0, today=date(2026, 10, 28))
    assert [e["game_id"] for e in first["errors"]] == [14052]
    state["challenge"] = False
    gets.clear()
    second = collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0, today=date(2026, 10, 28))
    assert second["errors"] == [] and second["boxscores"] == 1
    assert [g for g in gets if g.startswith("/games/14052-")]


def test_stale_live_page_still_live_is_not_cached(monkeypatch, tmp_data_dir, fixture_html):
    week_live = fixture_html("mykbo_week_2026-10-27.html").replace("Final", "LIVE", 1)
    game = fixture_html("mykbo_game_14048_final.html")
    live_game = re.sub(r"(text-ink-2\">\s*)Final", lambda m: m.group(1) + "▼ Bottom 9th · 0 out", game, count=1)
    assert live_game != game

    def handler(path):
        if path.startswith("/schedule/week_of/"):
            return week_live
        game_id = path.split("/")[2].split("-")[0]
        return live_game.replace("/games/14048-", f"/games/{game_id}-")

    gets = _real_fetch_env(monkeypatch, handler)
    cache_dir = tmp_data_dir / "cache" / "html"
    kw = dict(sleep_s=0, today=date(2026, 11, 5))
    row_path = next(r for r in parse_week(week_live) if r["game_id"] == 14052)["path"]
    out = collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), **kw)
    g = next(x for x in raw_store.load_games(2026) if x["game_id"] == 14052)
    assert g["status"] == "LIVE" and out["errors"] == []
    assert not mykbo_client._cache_file(cache_dir, row_path).exists()
    n = len([p for p in gets if p == row_path])
    collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), **kw)
    assert len([p for p in gets if p == row_path]) == n + 1
