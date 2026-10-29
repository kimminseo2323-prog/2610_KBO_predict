"""라이브·학습 피처 일치 (R8): run_pipeline.build_state로 만든 상태의 피처가
학습 데이터셋(build_dataset, 2015~2026 전 시즌 연결)의 같은 경기 피처와 26개 모두 똑같아야 한다.
커밋된 data/raw를 쓰고, 데이터셋은 모듈당 한 번만 만든다."""
from datetime import date

import numpy as np
import pytest

from kbo_predict import raw_store
from kbo_predict.features import FEATURE_NAMES, build_dataset, game_features, starter_ids
from kbo_predict.seasons import is_regular
from scripts.run_pipeline import build_state

DATES = ("2026-04-15", "2026-06-19", "2026-09-10")


@pytest.fixture(scope="module")
def real_df():
    return build_dataset(list(range(2015, 2027))).set_index("game_id")


@pytest.mark.parametrize("day", DATES)
def test_live_features_equal_training_features(real_df, day):
    games = [g for g in raw_store.load_games(2026)
             if g["date"] == day and g["status"] == "FINAL" and is_regular(2026, date.fromisoformat(day), g["game_id"])
             and g["home_score"] is not None and g["away_score"] is not None and g["home_score"] != g["away_score"]]
    assert games, day  # 그날 학습 행이 되는 경기가 있어야 의미 있는 비교
    assert sorted(g["game_id"] for g in games) == sorted(real_df.index[real_df["date"] == day])
    boxes = raw_store.load_boxscores(2026)
    state = build_state(2026, day)
    for g in games:
        f = game_features(g, state, starter_ids(boxes.get(g["game_id"])))
        live = np.array([f[n] for n in FEATURE_NAMES], dtype=float)
        train = real_df.loc[g["game_id"], FEATURE_NAMES].to_numpy(dtype=float)
        np.testing.assert_array_equal(live, train, err_msg=f"game {g['game_id']} on {day}")
