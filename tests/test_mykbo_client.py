import time

import pytest
import requests

from kbo_predict.mykbo_client import USER_AGENT, fetch_html, week_path
from datetime import date


class FakeResp:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def test_fetch_html_sleeps_sets_ua_and_caches(monkeypatch, tmp_path):
    calls, sleeps = [], []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    def fake_get(self, url, **kw):
        calls.append((url, self.headers.get("User-Agent"), kw.get("timeout")))
        return FakeResp("<html>ok</html>")

    monkeypatch.setattr(requests.Session, "get", fake_get)
    assert fetch_html("/schedule/week_of/2026-08-11", cache_dir=tmp_path) == "<html>ok</html>"
    assert calls[0][0] == "https://mykbostats.com/schedule/week_of/2026-08-11" and calls[0][1] == USER_AGENT and calls[0][2] == 20 and sleeps == [5.0]
    assert fetch_html("/schedule/week_of/2026-08-11", cache_dir=tmp_path) == "<html>ok</html>" and len(calls) == 1  # 캐시 적중, 요청 없음


def test_fetch_html_retries_once_then_raises(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def fake_get(self, url, **kw):
        calls.append(url)
        return FakeResp("", status_code=503)

    monkeypatch.setattr(requests.Session, "get", fake_get)
    with pytest.raises(requests.HTTPError):
        fetch_html("/games/1-A-vs-B-20260101", cache_dir=tmp_path)
    assert len(calls) == 2
    assert list(tmp_path.iterdir()) == []


def test_week_path():
    assert week_path(date(2026, 8, 11)) == "/schedule/week_of/2026-08-11"
