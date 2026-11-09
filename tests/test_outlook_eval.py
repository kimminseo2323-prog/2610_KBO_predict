"""두 모델 합치기 시험(outlook_eval): 선발 가리기, 고르는 규칙, 커밋된 결과 파일, 라이브 전망과 같은 입력."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kbo_predict import outlook_eval as oe
from kbo_predict.features import MODEL_FEATURES, STARTER_FEATURES, game_features
from kbo_predict.rewind import state_before
from kbo_predict.train_win import load_bundle, predict_proba

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "public" / "outlook_model_report.json"


def test_mask_starters_matches_unannounced_game_features():
    """시험에서 선발을 가린 입력 = 라이브에서 선발 미발표 경기의 game_features (전망이 실제로 넣는 값)."""
    st = state_before(2026, "2026-09-01")
    g = {"home_code": "KT", "away_code": "SS", "date": "2026-09-01", "season": 2026, "game_id": 0}
    f = game_features(g, st, None)
    row = pd.DataFrame([{k: f[k] for k in MODEL_FEATURES}])
    known = row.copy()
    known["starter_known"], known["starter_era_diff"] = 1, 1.5      # 선발이 있던 행이라도
    masked = oe.mask_starters(known)
    assert masked["starter_known"].iloc[0] == 0
    assert all(np.isnan(masked[c].iloc[0]) for c in STARTER_FEATURES if c != "starter_known")
    win = load_bundle(ROOT / "models" / "win_model.pkl")
    assert predict_proba(win, masked)[0] == pytest.approx(predict_proba(win, row)[0], abs=1e-12)


def test_committed_report_follows_rule():
    r = json.loads(REPORT.read_text(encoding="utf-8"))
    dev = r["pooled"]["dev"]
    best = min(r["candidates"], key=lambda n: dev[n]["log_loss"])
    assert r["best_dev"] == best
    p = r["unified_vs_best"]["logloss_p"]
    assert r["chosen"] == (oe.UNIFIED if best == oe.UNIFIED or p >= oe.ALPHA else best)
    assert r["chosen"] == "win_masked"                     # 2026-11-09 결과: 하나로 합침
    assert dev["win_masked"]["log_loss"] < dev["team"]["log_loss"] and r["tests_dev"]["win_masked"]["logloss_p"] < 0.05
    assert r["series_summary"]["all"]["n"] == len(r["series"]) == 37
    assert [k["date"] for k in r["ks_2026"]] == oe.KS_DATES


def test_live_pipeline_outlook_uses_prediction_model():
    """run_pipeline의 전망은 팀 모델 파일이 아니라 예측에 쓴 번들을 받는다 (하나로 합친 뒤)."""
    import inspect
    import scripts.run_pipeline as rp
    assert "team_path" not in inspect.signature(rp.run).parameters
    assert list(inspect.signature(rp.latest_outlook).parameters)[0] == "bundle"


@pytest.mark.slow
def test_rerun_matches_committed_report():
    from kbo_predict.features import load_features
    r = json.loads(REPORT.read_text(encoding="utf-8"))
    n = json.loads(json.dumps(oe.run(load_features(ROOT / "data" / "processed" / "features.parquet"), log=lambda *_: None),
                              ensure_ascii=False))
    for k in ("pooled", "by_season", "tests_dev", "best_dev", "unified_vs_best", "chosen", "series", "series_summary", "ks_2026"):
        assert n[k] == r[k], k
