import json
import shutil
from datetime import date
from pathlib import Path

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
LATEST_KEYS = {"generated_at", "date", "mode", "model_version", "commit_sha", "run_url", "games", "outlook"}
ROOT = Path(__file__).resolve().parents[1]
REAL_TEAM_PKL = ROOT / "models" / "team-2026.pkl"      # 커밋된 팀 모델 (전망용)
REAL_CLUSTERS_PKL = ROOT / "models" / "clusters.pkl"
FIXTURES = ROOT / "tests" / "fixtures"
OUTLOOK_WARNING = "outlook unavailable"
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


@pytest.fixture(autouse=True)
def fake_missing_boxscores(monkeypatch):
    """빠진 박스스코어 재수집(collect_missing_boxscores)은 네트워크를 쓰므로 가짜로 바꾼다. 호출된 시즌을 기록한다."""
    calls = []

    def fake(season, *, before=None, session=None, limit=20):
        calls.append(season)
        return {"fetched": 0, "errors": []}

    monkeypatch.setattr(rp, "collect_missing_boxscores", fake)
    return calls


def _errors(status):
    """collect_errors 중 전망 경고를 뺀 것. 작업 폴더가 빈 tmp라 기본 팀 모델(models/team-2026.pkl)이 없어
    대부분의 테스트에서 'outlook unavailable' 경고가 붙는다 — 그 경고 자체는 따로 테스트한다."""
    return [e for e in status["collect_errors"] if not e.startswith(OUTLOOK_WARNING)]


def _status(d):
    return json.loads((d / "public/status.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_repo_clusters(tmp_path, monkeypatch):
    """run의 clusters_path 기본값(models/clusters.pkl)은 작업 폴더 기준이다. 실제 저장소의 군집 파일에 따라
    결과가 달라지지 않도록 빈 tmp 폴더로 옮긴다 (그 기본 경로에 파일이 없는 상태 = 군집 없이 도는 기존 동작)."""
    monkeypatch.chdir(tmp_path)


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
    assert _errors(status) == ["/games/1: boom", "/games/14050-x: ConnectionError: down"]
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


def test_build_state_uses_shared_regular_finals(tmp_data_dir, fixture_html, monkeypatch):
    """build_state는 features.regular_finals(학습과 같은 필터)를 쓰고, upto 컷만 따로 적용한다."""
    from kbo_predict import features, rewind

    _seed_two_seasons(fixture_html)
    calls = []
    real = features.regular_finals
    monkeypatch.setattr(rewind, "regular_finals", lambda games, season: calls.append(season) or real(games, season))
    st = build_state(2026, "2026-10-29")
    assert calls == [2025, 2026]
    assert st.team_line("HT", "2026-10-29")["games"] == 2


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
                  "ip": 6.0, "starts": 1, "type": None}
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
    assert len(_errors(status)) == 1


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
    assert _errors(status) == ["/games/1: boom"]


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
    assert _errors(status) == []


def test_non_request_exception_from_collect_still_writes_status(tmp_data_dir, bundle_path, fixture_html, monkeypatch):
    _seed(fixture_html)

    def boom(*a, **k):
        raise ValueError("unrecognised week row")

    monkeypatch.setattr(rp, "collect_range", boom)
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    status = json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))
    assert _errors(status) == [repr(ValueError("unrecognised week row"))]


def test_history_model_version_is_bundle_version(tmp_data_dir, bundle_path, fixture_html):
    """history.csv의 model_version은 패키지 상수가 아니라 실제로 불러온 번들의 버전(meta["model_version"])."""
    upsert_games(2026, parse_week(fixture_html("mykbo_week_2026-10-27.html")))
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    import pandas as pd
    hist = pd.read_csv(tmp_data_dir / "public/history.csv")
    assert hist.model_version.tolist() == ["v-test"]


# ---------- 선발 유형 (clusters.pkl) ----------

def _clusters_pkl(path, rows):
    """types_map이 읽는 최소 군집 묶음: assigned에 (season, player_id, type)만. rows = [(group, season, pid, type)]."""
    import pandas as pd

    from kbo_predict.cluster import save_bundle

    obj = {g: {"assigned": pd.DataFrame([r[1:] for r in rows if r[0] == g],
                                        columns=["season", "player_id", "type"])}
           for g in ("batter", "pitcher")}
    save_bundle(obj, path)
    return path


def test_pipeline_runs_without_clusters_pkl(tmp_data_dir, bundle_path, fixture_html, monkeypatch):
    """clusters.pkl이 없어도 기존과 같이 돌고, 선발 블록의 type 키는 null로 있다."""
    _seed(fixture_html)
    monkeypatch.setattr(rp, "collect_range", _no_collect)
    out = run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True,
              clusters_path=tmp_data_dir / "missing.pkl")
    assert out["games_today"] == 1
    g = next(g for g in _latest(tmp_data_dir)["games"] if g["game_id"] == 14050)
    assert g["home"]["starter"]["type"] is None and g["away"]["starter"]["type"] is None


def test_pipeline_fills_starter_type_from_previous_season(tmp_data_dir, bundle_path, fixture_html, monkeypatch,
                                                          tmp_path):
    """clusters.pkl이 있으면 직전 시즌(2025) 투수 유형만 쓴다. 2026 유형·타자 유형은 무시. 확률은 그대로."""
    _seed(fixture_html)
    monkeypatch.setattr(rp, "collect_range", _no_collect)
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)  # 예고 선발 저장
    base = next(g for g in _latest(tmp_data_dir)["games"] if g["game_id"] == 14050)["home_win_prob"]
    pkl = _clusters_pkl(tmp_path / "clusters.pkl", [
        ("pitcher", 2025, HOME_SP, 1), ("pitcher", 2026, HOME_SP, 3),   # 2026 유형은 쓰지 않는다
        ("batter", 2025, AWAY_SP, 2), ("pitcher", 2024, AWAY_SP, 0),    # 타자 유형·2년 전 유형도 아니다
    ])
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False, clusters_path=pkl)
    g = next(g for g in _latest(tmp_data_dir)["games"] if g["game_id"] == 14050)
    assert g["home"]["starter"]["type"] == {"id": 1, "name": "스윙맨형"}      # config/cluster_labels.yaml 투수 1
    assert g["away"]["starter"]["type"] is None
    assert g["home_win_prob"] == base


def test_pipeline_survives_corrupt_clusters_pkl(tmp_data_dir, bundle_path, fixture_html, monkeypatch, tmp_path,
                                                capsys):
    """clusters.pkl이 깨져 있어도 예측·발행은 유형 없이 계속하고, status.json collect_errors와 stderr에 경고를 남긴다."""
    _seed(fixture_html)
    monkeypatch.setattr(rp, "collect_range", _no_collect)
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)  # 예고 선발 저장
    base = next(g for g in _latest(tmp_data_dir)["games"] if g["game_id"] == 14050)["home_win_prob"]
    bad = tmp_path / "clusters.pkl"
    bad.write_bytes(b"not a pickle")
    out = run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False,
              clusters_path=bad)
    assert out["games_today"] == 1
    g = next(g for g in _latest(tmp_data_dir)["games"] if g["game_id"] == 14050)
    assert g["home"]["starter"]["type"] is None and g["away"]["starter"]["type"] is None
    assert g["home_win_prob"] == base
    status = json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))
    assert len(_errors(status)) == 1 and _errors(status)[0].startswith("starter types unavailable")
    assert "starter types unavailable" in capsys.readouterr().err


# ---------- 전망(outlook) · status mode · 수집 생략 ----------

@pytest.fixture
def tmp_data_dir_postseason(tmp_data_dir):
    """2026 포스트시즌 경기(14040~14055)와 14050 예고 선발을 10-29 아침 그대로 떠 둔 스냅숏
    (tests/fixtures/games_2026_postseason.jsonl · starters_2026_postseason.jsonl)을 넣은 tmp 데이터 폴더.
    실제 data/raw/2026은 매일 바뀌므로(14050이 FINAL이 되는 등) 쓰지 않는다. 정규시즌 경기·박스스코어는 없다
    (전망·시리즈 전적에는 필요 없고, 상태·선발 통계만 비게 된다)."""
    dst = tmp_data_dir / "raw" / "2026"
    dst.mkdir(parents=True)
    for src, name in (("games_2026_postseason.jsonl", "games.jsonl"), ("starters_2026_postseason.jsonl", "starters.jsonl")):
        shutil.copy(FIXTURES / src, dst / name)
    return tmp_data_dir


def test_latest_has_outlook_series(tmp_data_dir_postseason, bundle_path, monkeypatch):
    """2026-10-29 = 플레이오프(SS-HT) 진행 중, 10-26 · 10-27 한 판씩 → outlook series, wins [1, 1]. 선발 블록에 type.
    시리즈 시뮬레이션의 첫 남은 경기(= 오늘 14050, HT 홈)는 승패 모델의 확률(latest.json의 home_win_prob)을 쓴다 (스펙 §8)."""
    from kbo_predict import simulate

    seen = {}
    real_series = simulate.series

    def spy(best_of, wins, remaining_homes, p, **kw):
        seen.update(homes=list(remaining_homes), p=list(p))
        return real_series(best_of, wins, remaining_homes, p, **kw)

    monkeypatch.setattr(simulate, "series", spy)
    d = tmp_data_dir_postseason
    out = run(date(2026, 10, 29), data_dir=d, model_path=bundle_path, meta=META, fetch=False,
              team_path=REAL_TEAM_PKL, clusters_path=REAL_CLUSTERS_PKL)
    assert out["games_today"] == 1
    latest = _latest(d)
    assert set(latest) == LATEST_KEYS and latest["mode"] == "live"
    o = latest["outlook"]
    assert o["type"] == "series" and o["as_of"] == "2026-10-29" and o["name"] == "플레이오프"
    assert o["teams"] == ["SS", "HT"] and o["wins"] == [1, 1] and o["best_of"] == 5
    assert o["next_game_date"] == "2026-10-29" and sum(o["win_prob"]) == pytest.approx(1.0)
    g = latest["games"][0]
    assert g["game_id"] == 14050 and g["round"] == "postseason"
    assert "type" in g["home"]["starter"] and "type" in g["away"]["starter"]
    # 오늘 경기: 팀0(SS)은 원정 → 첫 칸 P(SS 승) = 1 − P(HT 홈 승) (반올림 전 값이라 소수 4자리 안에서 같다)
    assert o["today_game_prob_source"] == "win_model (starter-inclusive)" and o["head_start"] == [0, 0]
    assert seen["homes"] == ["team1", "team1", "team0"] and len(seen["p"]) == o["games_remaining_max"] == 3
    assert seen["p"][0] == pytest.approx(1 - g["home_win_prob"], abs=5e-5)
    assert seen["p"][1] != pytest.approx(seen["p"][0], abs=1e-6)           # 4차전은 팀 모델 (다른 값)
    status = _status(d)
    assert status["mode"] == "live" and status["collect_errors"] == []  # 팀 모델이 있으면 전망 경고 없음


def test_outlook_fallback_for_unknown_series(tmp_data_dir, bundle_path, fixture_html):
    """시범경기 날짜(03-21): 정규시즌도 등록 시리즈도 아니다 → outlook next_game, 파이프라인은 그대로 성공."""
    _seed(fixture_html, _row(9201, "2026-03-21", status="SCHEDULED", hs=None, as_=None))
    out = run(date(2026, 3, 21), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False,
              team_path=REAL_TEAM_PKL)
    assert out["games_today"] == 1
    latest = _latest(tmp_data_dir)
    assert latest["games"][0]["round"] == "preseason"
    assert latest["outlook"] == {"type": "next_game", "as_of": "2026-03-21", "next_game_date": "2026-10-27"}
    assert _status(tmp_data_dir)["collect_errors"] == []


def test_outlook_without_team_model_warns(tmp_data_dir, bundle_path, fixture_html, tmp_path, capsys):
    """팀 모델이 없거나 깨졌으면 outlook = next_game(오늘 다음 경기 날짜) + collect_errors 경고. 예측 발행은 계속."""
    _seed(fixture_html)
    bad = tmp_path / "team.pkl"
    bad.write_bytes(b"not a pickle")
    for team_path in (tmp_path / "missing.pkl", bad):
        out = run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False,
                  team_path=team_path)
        assert out["games_today"] == 1
        outlook = _latest(tmp_data_dir)["outlook"]
        assert outlook == {"type": "next_game", "next_game_date": "2026-10-30", "as_of": "2026-10-29"}
        assert list(outlook) == ["type", "as_of", "next_game_date"]  # outlook_for의 next_game과 같은 키 순서
        errs = _status(tmp_data_dir)["collect_errors"]
        assert len(errs) == 1 and errs[0].startswith(f"{OUTLOOK_WARNING} ({team_path})")
    assert OUTLOOK_WARNING in capsys.readouterr().err


def test_status_mode_rewind_when_no_schedule(tmp_data_dir, bundle_path, fixture_html):
    """오늘~14일 안에 취소 아닌 경기가 없으면(12-01) mode "rewind", latest.json은 그대로. 경계: 14일째 경기면 live."""
    _seed(fixture_html)  # 경기 날짜: 10-27(FINAL) ~ 11-01
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert _status(tmp_data_dir)["mode"] == "live"
    before = (tmp_data_dir / "public/latest.json").read_bytes()
    run(date(2026, 12, 1), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    status = _status(tmp_data_dir)
    assert status["mode"] == "rewind" and status["next_game_date"] is None and status["games_today"] == 0
    assert (tmp_data_dir / "public/latest.json").read_bytes() == before
    run(date(2026, 10, 13), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert _status(tmp_data_dir)["mode"] == "live"      # 10-27 = 10-13 + 14일
    run(date(2026, 10, 12), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert _status(tmp_data_dir)["mode"] == "rewind"    # 10-27은 15일 뒤


def test_status_mode_ignores_canceled_games(tmp_data_dir, bundle_path):
    """14일 안의 경기가 모두 취소면 rewind."""
    upsert_games(2026, [_row(9301, "2026-11-20", status="CANCELED", hs=None, as_=None)])
    run(date(2026, 11, 15), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert _status(tmp_data_dir)["mode"] == "rewind"


def test_no_fetch_starters_when_no_games(monkeypatch, tmp_data_dir, bundle_path, fixture_html, fake_fetch_starters,
                                         fake_missing_boxscores):
    """오늘(10-28) 예정 경기가 없으면 fetch_starters를 부르지 않는다. 빠진 박스스코어 재수집은 그래도 돈다
    (얼리지 않은 시즌일 때 — 2026은 얼린 시즌이라 여기서는 FROZEN_SEASONS를 비워 둔다)."""
    _seed(fixture_html)
    monkeypatch.setattr(rp, "FROZEN_SEASONS", [])
    monkeypatch.setattr(rp, "collect_range", _no_collect)
    run(date(2026, 10, 28), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    assert fake_fetch_starters == []
    assert fake_missing_boxscores == [2026]
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    assert fake_fetch_starters == [([14050], META["generated_at"])]  # 경기가 있는 날은 그대로 부른다


def test_missing_boxscore_errors_join_collect_errors(monkeypatch, tmp_data_dir, bundle_path, fixture_html):
    """collect_missing_boxscores는 collect_range · fetch_starters 다음에 현재 시즌, before = 수집 창 시작(오늘 −7일)으로
    불리고, 그 오류는 collect_errors에 붙는다. --no-fetch면 부르지 않는다. (얼리지 않은 시즌으로 보도록 FROZEN_SEASONS를 비운다)"""
    _seed(fixture_html)
    monkeypatch.setattr(rp, "FROZEN_SEASONS", [])
    order = []
    real_starters = rp.fetch_starters  # autouse 가짜(14050 예고 선발)
    monkeypatch.setattr(rp, "collect_range", lambda *a, **k: order.append("range") or _no_collect())
    monkeypatch.setattr(rp, "fetch_starters", lambda games, **kw: order.append("starters") or real_starters(games, **kw))
    monkeypatch.setattr(rp, "collect_missing_boxscores", lambda season, **kw: order.append(("missing", season, kw)) or {
        "fetched": 0, "errors": [{"game_id": 9, "path": "/games/9-x", "error": "ValueError: unrecognised"}]})
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    assert order == ["range", "starters", ("missing", 2026, {"before": "2026-10-22"})]
    assert _errors(_status(tmp_data_dir)) == ["/games/9-x: ValueError: unrecognised"]
    order.clear()
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert order == []


def test_missing_boxscore_crash_is_isolated(monkeypatch, tmp_data_dir, bundle_path, fixture_html):
    """빠진 박스스코어 재수집이 예외를 내도 예고 선발은 이미 저장됐고, 예외는 collect_errors에 남고 발행은 계속된다."""
    _seed(fixture_html)
    monkeypatch.setattr(rp, "FROZEN_SEASONS", [])
    monkeypatch.setattr(rp, "collect_range", _no_collect)

    def boom(season, **kw):
        raise RuntimeError("box down")

    monkeypatch.setattr(rp, "collect_missing_boxscores", boom)
    out = run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    assert out["games_today"] == 1 and set(load_starters(2026)) == {14050}
    assert _errors(_status(tmp_data_dir)) == ["missing boxscores: RuntimeError('box down')"]


def test_missing_boxscores_skipped_for_frozen_season(monkeypatch, tmp_data_dir, bundle_path, fixture_html,
                                                    fake_missing_boxscores):
    """얼린 시즌(FROZEN_SEASONS, 2026 포함)은 매일 작업이 빠진 박스스코어를 다시 받지 않는다 — 얼린 산출물의 parity를
    지키기 위해. 수집 창(collect_range)과 예고 선발은 그대로 돈다."""
    from kbo_predict import FROZEN_SEASONS

    assert 2026 in FROZEN_SEASONS and rp.FROZEN_SEASONS is FROZEN_SEASONS
    _seed(fixture_html)
    calls = []
    monkeypatch.setattr(rp, "collect_range", lambda *a, **k: calls.append("range") or _no_collect())
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    assert calls == ["range"] and fake_missing_boxscores == []


def test_missing_boxscores_skipped_when_collect_failed(monkeypatch, tmp_data_dir, bundle_path, fixture_html,
                                                       fake_missing_boxscores):
    """collect_range가 예외로 멈췄으면(사이트 다운 등) 빠진 박스스코어 재수집도 하지 않는다 (20경기 × 5초를 더 기다리지 않게)."""
    _seed(fixture_html)
    monkeypatch.setattr(rp, "FROZEN_SEASONS", [])
    monkeypatch.setattr(rp, "collect_range", _boom)
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=True)
    assert fake_missing_boxscores == []
    assert _errors(_status(tmp_data_dir)) == [repr(requests.ConnectionError("down"))]
