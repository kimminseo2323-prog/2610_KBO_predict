import json

import pandas as pd
import pytest

from kbo_predict.publish import settle_history, upsert_history, write_latest, write_status

COLS = ["date", "game_id", "home", "away", "home_win_prob", "model_version", "predicted_at", "status", "winner", "correct"]


def pred(game_id, prob, date="2026-10-29", home="HT", away="SS"):
    return {"game_id": game_id, "date": date, "status": "SCHEDULED", "home": {"code": home}, "away": {"code": away}, "home_win_prob": prob}


def game(game_id, status, winner=None):
    scores = {"HOME": (4, 2), "AWAY": (2, 4), "DRAW": (3, 3)}
    hs, as_ = scores.get(winner, (None, None)) if status != "CANCELED" else (None, None)
    return {"game_id": game_id, "status": status, "home_score": hs, "away_score": as_}


def test_upsert_then_rerun_updates_prob_without_duplicate(tmp_path):
    p = tmp_path / "history.csv"
    upsert_history(p, [pred("g1", 0.55)], predicted_at="2026-10-28T09:00:00+09:00", model_version="v0.2")
    upsert_history(p, [pred("g1", 0.60)], predicted_at="2026-10-28T17:00:00+09:00", model_version="v0.2")
    df = pd.read_csv(p)
    assert len(df) == 1 and df.home_win_prob.item() == 0.60
    assert list(df.columns) == COLS and df.predicted_at.item() == "2026-10-28T17:00:00+09:00"


def test_settle_marks_correct_and_protects_final_rows(tmp_path):
    p = tmp_path / "history.csv"
    upsert_history(p, [pred("g1", 0.55), pred("g2", 0.40)], predicted_at="t", model_version="v0.2")
    n = settle_history(p, [game("g1", "FINAL", "HOME"), game("g2", "FINAL", "AWAY")])
    df = pd.read_csv(p)
    assert n == 2 and df.correct.tolist() == [1, 1] and df.winner.tolist() == ["HOME", "AWAY"]
    upsert_history(p, [pred("g1", 0.99)], predicted_at="t2", model_version="v0.2")
    assert pd.read_csv(p).home_win_prob.tolist()[0] == 0.55


def test_settle_wrong_prediction(tmp_path):
    p = tmp_path / "history.csv"
    upsert_history(p, [pred("g1", 0.55)], predicted_at="t", model_version="v0.2")
    settle_history(p, [game("g1", "FINAL", "AWAY")])
    assert pd.read_csv(p).correct.tolist() == [0]


def test_settle_canceled_and_draw(tmp_path):
    p = tmp_path / "history.csv"
    upsert_history(p, [pred("g1", 0.55), pred("g2", 0.40)], predicted_at="t", model_version="v0.2")
    n = settle_history(p, [game("g1", "CANCELED"), game("g2", "FINAL", "DRAW")])
    df = pd.read_csv(p)
    assert n == 2
    assert df.status.tolist() == ["CANCELED", "FINAL"]
    assert df.correct.isna().all() and df.winner.tolist()[1] == "DRAW"


def test_rows_sorted_by_date_then_game_id(tmp_path):
    p = tmp_path / "history.csv"
    upsert_history(p, [pred(5, 0.5, date="2026-10-30"), pred(2, 0.5), pred(1, 0.5)], predicted_at="t",
                   model_version="v0.2")
    assert pd.read_csv(p).game_id.tolist() == [1, 2, 5]


def test_write_latest_and_status_contain_meta(tmp_path):
    meta = {"generated_at": "2026-10-28T09:00:00+09:00", "model_version": "v0.1", "commit_sha": None, "run_url": "http://x/1"}
    write_latest(tmp_path / "latest.json", date="2026-10-29", games=[{"game_id": 1}], meta=meta)
    d = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert d == {**meta, "date": "2026-10-29", "mode": "live", "games": [{"game_id": 1}]}
    write_status(tmp_path / "status.json", mode="live", next_game_date="2026-10-29", games_today=1, meta=meta)
    s = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert s["next_game_date"] == "2026-10-29" and s["games_today"] == 1 and s["mode"] == "live"
    assert s["commit_sha"] is None and s["run_url"] == "http://x/1" and s["model_version"] == "v0.1"
    assert set(s) == {"generated_at", "run_url", "commit_sha", "mode", "next_game_date", "games_today", "model_version",
                    "collect_errors"}
    assert s["collect_errors"] == []
    write_status(tmp_path / "status.json", mode="live", next_game_date=None, games_today=0, meta=meta,
                 collect_errors=["/games/1: boom"])
    assert json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))["collect_errors"] == ["/games/1: boom"]


def test_upsert_ignores_live_and_final_predictions(tmp_path):
    p = tmp_path / "history.csv"
    upsert_history(p, [pred("g1", 0.55)], predicted_at="t1", model_version="v0.2")
    before = p.read_bytes()
    upsert_history(p, [dict(pred("g1", 0.90), status="LIVE"), dict(pred("g1", 0.95), status="FINAL"),
                       dict(pred("g2", 0.70), status="LIVE"), dict(pred("g3", 0.70), status="FINAL")],
                   predicted_at="t2", model_version="v0.2")
    assert p.read_bytes() == before
    assert pd.read_csv(p).game_id.tolist() == ["g1"]


def test_upsert_history_model_version_from_entry_or_bundle(tmp_path):
    """model_version은 패키지 상수가 아니라 예측 항목(또는 meta의 번들 버전)에서 온다."""
    p = tmp_path / "history.csv"
    upsert_history(p, [pred("g1", 0.55)], predicted_at="t", model_version="v9.9")
    upsert_history(p, [dict(pred("g2", 0.40), model_version="v-entry")], predicted_at="t", model_version="v9.9")
    df = pd.read_csv(p, dtype={"game_id": str})
    assert dict(zip(df.game_id, df.model_version)) == {"g1": "v9.9", "g2": "v-entry"}
    upsert_history(p, [pred("g1", 0.60)], predicted_at="t2", model_version="v10")  # 재예측이면 버전도 갱신
    assert pd.read_csv(p, dtype={"game_id": str}).set_index("game_id").model_version["g1"] == "v10"


def test_upsert_history_requires_a_model_version(tmp_path):
    with pytest.raises(ValueError, match="model_version"):
        upsert_history(tmp_path / "history.csv", [pred("g1", 0.55)], predicted_at="t")
