from datetime import date

import pytest
import requests

from kbo_predict import naver_client
from kbo_predict.naver_client import fetch_games, fetch_record


class FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def test_fetch_games_filters_kbo_and_builds_url(monkeypatch, fixture_json):
    captured = {}

    def fake_get(self, url, **kw):
        captured["url"] = url
        return FakeResp(fixture_json("schedule_2026-08-15.json"))

    monkeypatch.setattr(requests.Session, "get", fake_get)
    games = fetch_games(date(2026, 8, 15), date(2026, 8, 15), sleep_s=0)
    assert len(games) == 5 and all(g["categoryId"] == "kbo" for g in games)
    assert "fromDate=2026-08-15" in captured["url"] and "categoryId=kbo" in captured["url"]


def test_fetch_games_drops_non_kbo(monkeypatch, fixture_json):
    payload = fixture_json("schedule_2026-08-15.json")
    payload["result"]["games"][0] = dict(payload["result"]["games"][0], categoryId="kbo2")
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: FakeResp(payload))
    assert len(fetch_games(date(2026, 8, 15), date(2026, 8, 15), sleep_s=0)) == 4


def test_fetch_record_returns_record_data(monkeypatch, fixture_json):
    captured = {}

    def fake_get(self, url, **kw):
        captured["url"] = url
        captured["headers"] = self.headers
        return FakeResp(fixture_json("record_33331020HTLG02026.json"))

    monkeypatch.setattr(requests.Session, "get", fake_get)
    result = fetch_record("33331020HTLG02026", sleep_s=0)
    assert "battersBoxscore" in result and result["gameInfo"]["hCode"] == "LG"
    assert captured["url"].startswith(naver_client.BASE_URL)
    assert "33331020HTLG02026" in captured["url"]
    assert captured["headers"]["User-Agent"] == naver_client.USER_AGENT


def test_retries_once_then_raises(monkeypatch):
    calls = []

    def fake_get(self, url, **kw):
        calls.append(url)
        return FakeResp({}, status_code=503)

    monkeypatch.setattr(requests.Session, "get", fake_get)
    with pytest.raises(requests.HTTPError):
        fetch_record("X", sleep_s=0)
    assert len(calls) == 2
