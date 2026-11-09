"""가을야구 성적(postseason_eval): 가을 경기 모으기, 휴식일 고정, 커밋된 결과 파일의 일관성, 다시 계산하면 같은 값."""
import json
from pathlib import Path

import pytest

from kbo_predict import postseason_eval as pe
from kbo_predict import raw_store

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "public" / "postseason_report.json"


def test_postseason_games_2026_are_the_14_autumn_games():
    post = pe.postseason_games(2026)
    assert len(post) == 14 and post[0]["game_id"] == 14040 and post[-1]["game_id"] == 14060
    assert all(g["status"] == "FINAL" and g["home_score"] != g["away_score"] for g in post)
    assert [g["date"] for g in post] == sorted(g["date"] for g in post)


def test_in_state_keeps_frozen_rest_days():
    """가을 경기로 상태를 갱신해도 휴식일 차이는 정규시즌 끝 값 — 직행 팀의 20일 넘는 휴식이 확률을 끌지 않게."""
    import copy
    from kbo_predict.features import game_features
    from kbo_predict.rewind import state_before
    from kbo_predict.train_win import load_bundle
    games, boxes = raw_store.load_games(2026), raw_store.load_boxscores(2026)
    frozen = state_before(2026, "2026-11-03", games=games, boxscores=boxes)
    live = copy.deepcopy(frozen)
    for g in pe.postseason_games(2026, games):
        if g["date"] < "2026-11-03":
            live.update(g, boxes.get(g["game_id"]))
    g = {"home_code": "KT", "away_code": "SS", "date": "2026-11-03", "season": 2026, "game_id": 0}
    assert game_features(g, live, None)["rest_diff"] >= 10 and game_features(g, frozen, None)["rest_diff"] == 0
    win = load_bundle(ROOT / "models" / "win_model.pkl")
    p = pe._in_state_p(win, g, live, frozen, None)
    assert 0.4 < p < 0.65   # 휴식일을 그대로 넣으면 0.77까지 튄다


def test_committed_report_is_consistent():
    r = json.loads(REPORT.read_text(encoding="utf-8"))
    assert r["pooled"]["dev"]["n"] == sum(r["by_season"][str(s)]["n"] for s in r["protocol"]["dev_seasons"])
    assert r["pooled"]["test"]["n"] == len(r["games_2026"]) == 14
    hits = sum(int((g["frozen"] >= 0.5) == (g["y"] == 1)) for g in r["games_2026"])
    assert hits == round(r["pooled"]["test"]["frozen"]["accuracy"] * 14)
    ks = [s for s in r["series"] if s["season"] == 2026][-1]
    assert ks["name"] == "한국시리즈" and ks["winner"] == "SS" and sorted(ks["wins"]) == [1, 4]
    t = r["pooled"]["dev"]["tests"]["in_state_vs_frozen"]
    assert r["decision"]["adopt_in_state"] == (t["logloss_gain"] > 0 and t["logloss_p"] < pe.ALPHA)
    assert r["series_summary"]["all"]["n"] == len(r["series"])


@pytest.mark.slow
def test_rerun_matches_committed_report():
    from kbo_predict.features import load_features
    r = json.loads(REPORT.read_text(encoding="utf-8"))
    n = json.loads(json.dumps(pe.run(load_features(ROOT / "data" / "processed" / "features.parquet"),
                                     history_path=ROOT / "data" / "public" / "history.csv", log=lambda *_: None),
                              ensure_ascii=False))
    for k in ("by_season", "pooled", "series", "series_summary", "games_2026", "decision", "live_2026"):
        assert n[k] == r[k], k
