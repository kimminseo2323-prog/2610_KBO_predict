import json
from datetime import date

import numpy as np
import pytest
import requests

from kbo_predict.features import FEATURE_NAMES, build_dataset, game_features, starter_ids
from kbo_predict.mykbo_parse import parse_starters, parse_week
from kbo_predict.publish import HISTORY_COLUMNS
from kbo_predict.raw_store import append_boxscores, load_boxscores, load_games, load_starters, upsert_games
from scripts.run_pipeline import build_state, run
import scripts.run_pipeline as rp

META = {"generated_at": "2026-10-29T09:00:00+09:00", "model_version": "v0.1", "commit_sha": None, "run_url": None}
LATEST_KEYS = {"generated_at", "date", "mode", "model_version", "commit_sha", "run_url", "games"}
STATUS_KEYS = {"generated_at", "run_url", "commit_sha", "mode", "next_game_date", "games_today", "model_version",
               "collect_errors"}
ENTRY_KEYS = {"game_id", "date", "time", "stadium", "round", "status", "home", "away", "home_win_prob", "factors",
              "starter_known", "status_note"}
SIDE_KEYS = {"code", "name", "starter", "win_pct_season", "last10", "run_diff"}


@pytest.fixture(autouse=True)
def fake_fetch_starters(monkeypatch, fixture_html):
    """네트워크 대신 14050 예정 경기 픽스처의 예고 선발을 돌려준다. 호출 기록(경기 id 목록, fetched_at)을 남긴다."""
    calls = []
    sched = parse_starters(fixture_html("mykbo_game_14050_scheduled.html"))

    def fake(games, *, fetched_at, session=None):
        calls.append(([g["game_id"] for g in games], fetched_at))
        return {"starters": {g["game_id"]: {"game_id": g["game_id"], "date": g["date"], "fetched_at": fetched_at, **sched}
                             for g in games if g["game_id"] == 14050},
                "errors": []}

    monkeypatch.setattr(rp, "fetch_starters", fake)
    return calls


def _no_collect(*a, **k):
    return {"weeks": 1, "games": 0, "boxscores": 0, "errors": []}


def _latest(d):
    return json.loads((d / "public/latest.json").read_text(encoding="utf-8"))


def test_run_writes_all_public_files_on_game_day(tmp_data_dir, bundle_path, fixture_html, fake_fetch_starters):
    upsert_games(2026, parse_week(fixture_html("mykbo_week_2026-10-27.html")))
    out = run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert out["games_today"] == 1
    assert fake_fetch_starters == []  # --no-fetch면 예고 선발도 받지 않는다
    latest = _latest(tmp_data_dir)
    assert latest["date"] == "2026-10-29" and latest["games"][0]["home"]["code"] == "HT" and latest["mode"] == "live"
    assert (tmp_data_dir / "public/status.json").exists() and (tmp_data_dir / "public/history.csv").exists()
    # 계약: 키 집합 유지 (경기 항목에는 starter_known만 추가), 선발 미저장 → starter None
    g = latest["games"][0]
    assert set(latest) == LATEST_KEYS and set(g) == ENTRY_KEYS
    assert set(g["home"]) == SIDE_KEYS and set(g["away"]) == SIDE_KEYS
    assert g["home"]["starter"] is None and g["starter_known"] is False and len(g["factors"]) == 5
    status = json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))
    assert set(status) == STATUS_KEYS
    header = (tmp_data_dir / "public/history.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == HISTORY_COLUMNS


def test_fetch_stores_starters_and_fills_latest(tmp_data_dir, bundle_path, fixture_html, monkeypatch,
                                                 fake_fetch_starters):
    _seed(fixture_html)
    monkeypatch.setattr(rp, "collect_range", _no_collect)
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    # 대상 날짜의 SCHEDULED 경기만, fetched_at = generated_at
    assert fake_fetch_starters == [([14050], META["generated_at"])]
    stored = load_starters(2026)
    assert set(stored) == {14050} and stored[14050]["fetched_at"] == META["generated_at"]
    g = next(g for g in _latest(tmp_data_dir)["games"] if g["game_id"] == 14050)
    assert g["home"]["starter"]["name"] == "Shirakawa Keisho" and g["home"]["starter"]["player_id"] == 2730
    assert g["away"]["starter"]["name"] == "Choi Won-tae"
    assert g["home"]["starter"]["era"] is None and g["starter_known"] is False  # 기록 없는 투수 → 통계 None
    # --no-fetch 재실행은 저장된 선발로 같은 결과
    before = _latest(tmp_data_dir)
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert _latest(tmp_data_dir) == before and len(fake_fetch_starters) == 1


def test_starter_fetch_errors_join_collect_errors(tmp_data_dir, bundle_path, fixture_html, monkeypatch):
    _seed(fixture_html)
    monkeypatch.setattr(rp, "collect_range", lambda *a, **k: {
        "weeks": 1, "games": 0, "boxscores": 0, "errors": [{"game_id": 1, "path": "/games/1", "error": "boom"}]})
    monkeypatch.setattr(rp, "fetch_starters", lambda games, **kw: {
        "starters": {}, "errors": [{"game_id": 14050, "path": "/games/14050-x", "error": "ConnectionError: down"}]})
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    status = json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))
    assert status["collect_errors"] == ["/games/1: boom", "/games/14050-x: ConnectionError: down"]
    g = _latest(tmp_data_dir)["games"][0]
    assert g["home"]["starter"] is None and g["starter_known"] is False


# ---------- 직전 시즌을 포함한 상태 (build_state) ----------

HOME_SP, AWAY_SP = 2730, 1096


def _pitch(pid, er):
    """선발(order 1) 6이닝 + 구원(order 2) 3이닝."""
    return [{"player_id": pid, "name": f"P{pid}", "order": 1, "ip_outs": 18, "er": er, "r": er, "hr": 1,
             "bb": 2, "hbp": 0, "so": 6, "np": 95},
            {"player_id": pid + 100000, "name": "RP", "order": 2, "ip_outs": 9, "er": 0, "r": 0, "hr": 0,
             "bb": 1, "hbp": 0, "so": 3, "np": 40}]


def _box(g, hp, ap, her, aer):
    bat = [{"ab": 34, "h": 9, "bb": 3, "hbp": 1, "hr": 1, "so": 7}]
    return {"game_id": g["game_id"], "date": g["date"], "batting": {"home": bat, "away": bat},
            "pitching": {"home": _pitch(hp, her), "away": _pitch(ap, aer)}}


def _seed_two_seasons(fixture_html):
    """2025: 정규시즌 FINAL 3경기(무승부 1, 박스 포함) + 포스트시즌 1경기. 2026: 시범 1 + 정규 2경기(박스 포함) + 픽스처 주간.
    원정 예고 선발 AWAY_SP는 2025 기록만, 홈 예고 선발 HOME_SP는 2026에 한 번 선발 등판."""
    prev = [_row(9101, "2025-05-01", hs=5, as_=1, season=2025), _row(9102, "2025-05-02", hs=2, as_=8, season=2025),
            _row(9103, "2025-05-02", hs=3, as_=3, season=2025),   # 무승부: 학습 행은 없지만 상태에는 반영
            _row(9104, "2025-10-20", hs=0, as_=12, season=2025)]  # 포스트시즌 → 제외
    upsert_games(2025, prev)
    append_boxscores(2025, {9101: _box(prev[0], 1, AWAY_SP, 1, 4), 9102: _box(prev[1], 2, AWAY_SP + 1, 6, 2),
                            9103: _box(prev[2], 3, AWAY_SP, 3, 3), 9104: _box(prev[3], 4, AWAY_SP, 9, 0)})
    cur = [_row(9201, "2026-03-21", hs=0, as_=15),  # 시범경기 → 제외
           _row(9202, "2026-09-01", hs=4, as_=2), _row(9203, "2026-09-02", hs=1, as_=6)]
    _seed(fixture_html, *cur)
    append_boxscores(2026, {9201: _box(cur[0], 5, 6, 9, 0), 9202: _box(cur[1], HOME_SP, 7, 2, 4),
                            9203: _box(cur[2], 8, 9, 6, 1)})


def test_build_state_matches_training_features(tmp_data_dir, fixture_html):
    """라이브 상태(build_state)로 만든 피처 == 학습 데이터셋(build_dataset)의 같은 경기 피처
    (정규시즌·FINAL 필터, (date, game_id) 순서, 박스스코어, 직전 시즌 연결이 모두 같아야 한다)."""
    _seed_two_seasons(fixture_html)
    df = build_dataset([2025, 2026]).set_index("game_id")
    games, boxes = {g["game_id"]: g for g in load_games(2026)}, load_boxscores(2026)
    for gid in (9202, 9203):
        g = games[gid]
        f = game_features(g, build_state(2026, g["date"]), starter_ids(boxes.get(gid)))
        np.testing.assert_array_equal(np.array([f[n] for n in FEATURE_NAMES], dtype=float),
                                      df.loc[gid, FEATURE_NAMES].to_numpy(dtype=float))
    st = build_state(2026, "2026-10-29")
    assert st.season == 2026
    assert st.team_line("HT", "2026-10-29")["prev_win_pct"] == 0.5  # 2025 정규 1승 1패(+무), 포스트시즌 제외
    assert st.team_line("HT", "2026-10-29")["games"] == 2              # 2026 시범경기 제외
    assert st.pitcher_line(AWAY_SP)["season"]["starts"] == 0            # 2025 기록만 있음
    assert st.pitcher_line(AWAY_SP)["ip"] == 12.0                       # 2025 정규 2선발 (포스트시즌 제외)
    assert st.pitcher_line(HOME_SP)["season"]["starts"] == 1


def test_build_state_without_previous_season(tmp_data_dir, fixture_html):
    """직전 시즌 데이터가 없으면(2015처럼) 이전 시즌 값 없이 당해 시즌만으로 동작."""
    _seed(fixture_html, _row(9202, "2026-09-01", hs=4, as_=2))
    st = build_state(2026, "2026-10-29")
    line = st.team_line("HT", "2026-10-29")
    assert line["prev_win_pct"] is None and line["win_pct"] == 1.0 and st.season == 2026


def test_run_uses_previous_season_and_starter_stats(tmp_data_dir, bundle_path, fixture_html, monkeypatch):
    _seed_two_seasons(fixture_html)
    monkeypatch.setattr(rp, "collect_range", _no_collect)
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    g = next(g for g in _latest(tmp_data_dir)["games"] if g["game_id"] == 14050)
    hs, as_ = g["home"]["starter"], g["away"]["starter"]
    assert hs == {"player_id": HOME_SP, "name": "Shirakawa Keisho", "era": 3.0, "k9": 9.0, "bb9": 3.0,
                  "ip": 6.0, "starts": 1}
    assert as_["player_id"] == AWAY_SP and as_["starts"] == 0 and as_["ip"] == 0.0 and as_["era"] is None
    assert g["starter_known"] is True  # 두 선발 모두 (직전 시즌 포함) 기록이 있음
    assert g["home"]["win_pct_season"] == 0.5 and g["round"] == "postseason"


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
    status = json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))
    assert len(status["collect_errors"]) == 1


def test_fetch_failure_with_empty_store_raises(tmp_data_dir, bundle_path, monkeypatch):
    monkeypatch.setattr(rp, "collect_range", _boom)
    with pytest.raises(requests.ConnectionError):
        run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)


def test_collect_errors_are_recorded_in_status(tmp_data_dir, bundle_path, fixture_html, monkeypatch):
    _seed(fixture_html)
    monkeypatch.setattr(rp, "collect_range", lambda *a, **k: {
        "weeks": 1, "games": 0, "boxscores": 0,
        "errors": [{"game_id": 1, "path": "/games/1", "error": "boom"}]})
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    status = json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))
    assert status["collect_errors"] == ["/games/1: boom"]


def test_unregistered_season_fallback_is_recorded_in_status(tmp_data_dir, bundle_path, fixture_html, monkeypatch):
    _seed(fixture_html)
    monkeypatch.setattr(rp, "collect_range", lambda *a, **k: {"weeks": 1, "games": 0, "boxscores": 0, "errors": []})
    run(date(2027, 4, 1), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    status = json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))
    assert "season 2027 not registered in REGULAR_SEASON; using 03-01..10-31 fallback" in status["collect_errors"]


def test_registered_season_adds_no_fallback_error(tmp_data_dir, bundle_path, fixture_html, monkeypatch):
    _seed(fixture_html)
    monkeypatch.setattr(rp, "collect_range", lambda *a, **k: {"weeks": 1, "games": 0, "boxscores": 0, "errors": []})
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    status = json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))
    assert status["collect_errors"] == []


def test_non_request_exception_from_collect_still_writes_status(tmp_data_dir, bundle_path, fixture_html, monkeypatch):
    _seed(fixture_html)

    def boom(*a, **k):
        raise ValueError("unrecognised week row")

    monkeypatch.setattr(rp, "collect_range", boom)
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    status = json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))
    assert status["collect_errors"] == [repr(ValueError("unrecognised week row"))]
