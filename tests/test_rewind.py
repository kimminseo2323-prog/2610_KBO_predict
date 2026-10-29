"""되감기(rewind) JSON: 누수 없음 · 결과/전망 · 평가 모델과 일치 · 결정성 · 이어 쌓은 상태 == 처음부터 만든 상태.
커밋된 data/raw(2025·2026)와 models/report-2026.pkl · team-2026.pkl을 쓴다."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from kbo_predict import raw_store
from kbo_predict.features import FEATURE_NAMES, load_features
from kbo_predict.rewind import STARTER_SOURCE, build_season, day_payload, state_before
from kbo_predict.simulate import TEAM_CODES
from kbo_predict.train_win import load_bundle, predict_proba
from scripts.run_pipeline import CLUSTERS_PKL, build_state, starter_types

SEASON = 2026
DAY = "2026-05-01"
META = {"generated_at": "2026-10-29T12:00:00+09:00", "commit_sha": "abc123", "run_url": None}
FEATURES_PARQUET = Path("data/processed/features.parquet")
PUBLISHED_INDEX = Path("data/public/rewind/2026/index.json")
MODEL_REPORT = Path("data/public/model_report.json")


@pytest.fixture(scope="module")
def real_small():
    """2026 시즌 경기·박스스코어와 평가 모델·팀 모델·선발 유형 (모듈당 한 번)."""
    return {
        "games": raw_store.load_games(SEASON),
        "boxscores": raw_store.load_boxscores(SEASON),
        "bundle": load_bundle(Path("models/report-2026.pkl")),
        "team_bundle": load_bundle(Path("models/team-2026.pkl")),
        "starter_types": starter_types(CLUSTERS_PKL, SEASON),
    }


def _payload(real, on, games=None, **kw):
    return day_payload(SEASON, on, games=real["games"] if games is None else games, boxscores=real["boxscores"],
                       bundle=real["bundle"], team_bundle=real["team_bundle"],
                       starter_types=real["starter_types"], meta=META, **kw)


@pytest.fixture(scope="module")
def day(real_small):
    return _payload(real_small, DAY)


def test_build_state_is_state_before():
    """run_pipeline.build_state는 rewind.state_before의 별칭 (라이브와 되감기가 같은 상태 함수를 쓴다)."""
    assert build_state is state_before


def test_rewind_day_ignores_future_games(real_small, day):
    """그날(05-01)과 다음 날(05-02) 점수를 바꿔 넣어도 예측 확률·요인·전망은 그대로 — 결과 칸만 바뀐다."""
    altered = copy.deepcopy(real_small["games"])
    n = 0
    for g in altered:
        if g["date"] in (DAY, "2026-05-02") and g["status"] == "FINAL":
            g["home_score"], g["away_score"] = (g["away_score"] or 0) + 7, g["home_score"]  # 점수를 바꾼다 (홈 = 원정+7)
            n += 1
    assert n >= 5
    other = _payload(real_small, DAY, games=altered)
    assert [g["home_win_prob"] for g in other["games"]] == [g["home_win_prob"] for g in day["games"]]
    assert [g["factors"] for g in other["games"]] == [g["factors"] for g in day["games"]]
    assert other["outlook"] == day["outlook"]  # 전망은 미래 경기를 굴리지만 그 결과를 보지 않는다
    assert [g["result"] for g in other["games"]] != [g["result"] for g in day["games"]]


def test_rewind_day_has_results_and_outlook(day):
    assert day["mode"] == "rewind" and day["date"] == DAY
    assert day["model_version"] == "report-2026" and day["team_model_version"] == "team-2026"
    assert day["starter_source"] == STARTER_SOURCE
    assert day["generated_at"] == META["generated_at"] and day["commit_sha"] == META["commit_sha"]
    ids = [g["game_id"] for g in day["games"]]
    assert ids == sorted(ids) and len(ids) == 5
    for g in day["games"]:
        assert g["status"] == "FINAL" and g["round"] == "regular" and g["date"] == DAY
        assert g["home"]["starter"] is not None and g["away"]["starter"] is not None  # 박스스코어 실제 선발
        r = g["result"]
        assert set(r) == {"home_score", "away_score", "winner", "pick", "correct"}
        assert r["winner"] == ("HOME" if r["home_score"] > r["away_score"] else "AWAY")
        # 적중 = 반올림 전 확률로 고른 쪽(pick)이 이긴 쪽인가 — 공개 칸 home_win_prob(4자리)로 다시 판정하지 않는다
        assert r["pick"] in ("HOME", "AWAY") and r["correct"] == (r["pick"] == r["winner"])
        if abs(g["home_win_prob"] - 0.5) > 1e-4:  # 반올림 경계가 아니면 pick은 공개 확률과도 맞는다
            assert r["pick"] == ("HOME" if g["home_win_prob"] > 0.5 else "AWAY")
    o = day["outlook"]
    assert o["type"] == "playoff_race" and o["as_of"] == DAY
    assert set(o["teams"]) == set(TEAM_CODES) and len(o["teams"]) == 10
    assert sum(t["playoff_prob"] for t in o["teams"].values()) == pytest.approx(5.0, abs=1e-3)  # 소수 4자리 반올림
    assert all(t["playoff_prob"] == round(t["playoff_prob"], 4) and t["exp_wins"] == round(t["exp_wins"], 4)
               for t in o["teams"].values())


@pytest.mark.skipif(not FEATURES_PARQUET.exists(), reason="data/processed/features.parquet 없음 (features CLI로 생성)")
def test_rewind_matches_report_model(real_small, day):
    """되감기 확률 == report-2026으로 학습 데이터셋(features.parquet)의 같은 경기 행을 예측한 값 (소수 4자리)."""
    df = load_features(FEATURES_PARQUET)
    rows = df[df["date"] == DAY].set_index("game_id")
    p = predict_proba(real_small["bundle"], rows[FEATURE_NAMES])
    expected = {gid: round(float(v), 4) for gid, v in zip(rows.index, p)}
    got = {g["game_id"]: g["home_win_prob"] for g in day["games"] if g["result"]["winner"] != "DRAW"}
    assert got == expected


def _read_day(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj.pop("generated_at")
    return obj


def test_rewind_deterministic(tmp_path, real_small):
    """같은 날짜를 두 번 만들면 generated_at만 다르고 나머지는 같다 (compact · 키 정렬 한 줄 파일)."""
    kw = dict(bundle=real_small["bundle"], team_bundle=real_small["team_bundle"],
              starter_types=real_small["starter_types"], dates=[DAY])
    a = build_season(SEASON, out_dir=tmp_path / "a", meta=META, **kw)
    b = build_season(SEASON, out_dir=tmp_path / "b", meta={**META, "generated_at": "2026-10-30T00:00:00+09:00"}, **kw)
    fa, fb = tmp_path / "a" / "2026" / f"{DAY}.json", tmp_path / "b" / "2026" / f"{DAY}.json"
    assert _read_day(fa) == _read_day(fb)
    assert fa.read_text(encoding="utf-8") == fa.read_text(encoding="utf-8").strip() + "\n"
    assert "\n" not in fa.read_text(encoding="utf-8").strip()  # compact: 한 줄
    a.pop("generated_at"), b.pop("generated_at")
    assert a == b
    assert [d["date"] for d in a["dates"]] == [DAY]
    d = a["dates"][0]
    assert d["games"] == 5 and d["decided"] == 5 and a["n_decided"] == 5
    assert a["accuracy"] == round(d["correct"] / d["decided"], 4)


def test_incremental_state_equals_state_before(tmp_path, real_small):
    """build_season(상태를 날짜순으로 이어 쌓음)의 파일 == day_payload(state_before로 처음부터 만든 상태).
    06-19에는 LIVE로 멈춘 정규시즌 경기(13606)가 있다 — 파일에 들어가지 않아야 한다."""
    dates = ["2026-04-15", "2026-06-19", "2026-09-10"]
    build_season(SEASON, out_dir=tmp_path, bundle=real_small["bundle"], team_bundle=real_small["team_bundle"],
                 meta=META, dates=dates, starter_types=real_small["starter_types"])
    for on in dates:
        got = json.loads((tmp_path / "2026" / f"{on}.json").read_text(encoding="utf-8"))
        expected = json.loads(json.dumps(_payload(real_small, on)))  # JSON을 한 번 거쳐 같은 모양으로
        assert got == expected, on
    june = json.loads((tmp_path / "2026" / "2026-06-19.json").read_text(encoding="utf-8"))
    assert 13606 not in [g["game_id"] for g in june["games"]]


def test_partial_rebuild_keeps_other_index_dates(tmp_path, real_small):
    """--dates로 일부만 다시 만들면 index.json의 다른 날짜 칸은 남는다."""
    kw = dict(out_dir=tmp_path, bundle=real_small["bundle"], team_bundle=real_small["team_bundle"], meta=META,
              starter_types=real_small["starter_types"])
    build_season(SEASON, dates=["2026-04-15"], **kw)
    idx = build_season(SEASON, dates=["2026-04-16"], **kw)
    assert [d["date"] for d in idx["dates"]] == ["2026-04-15", "2026-04-16"]
    assert idx["n_decided"] == sum(d["decided"] for d in idx["dates"])
    with pytest.raises(ValueError, match="2026-12-25"):  # 정규시즌 경기가 없는 날
        build_season(SEASON, dates=["2026-12-25"], **kw)


def test_partial_rebuild_validates_before_writing(tmp_path, real_small):
    """--dates 검사는 파일을 쓰기 전에 모두: 없는 날짜가 하나라도 섞이면 아무 파일도 안 쓴다, 빈 목록 거절,
    기존 index.json의 model_version이 다르면 합치지 않는다."""
    kw = dict(out_dir=tmp_path, bundle=real_small["bundle"], team_bundle=real_small["team_bundle"], meta=META,
              starter_types=real_small["starter_types"])
    with pytest.raises(ValueError, match="2026-12-25"):
        build_season(SEASON, dates=["2026-04-15", "2026-12-25"], **kw)
    assert not (tmp_path / "2026").exists() or not list((tmp_path / "2026").iterdir())
    with pytest.raises(ValueError, match="empty"):
        build_season(SEASON, dates=[], **kw)
    build_season(SEASON, dates=["2026-04-15"], **kw)
    idx_path = tmp_path / "2026" / "index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    idx_path.write_text(json.dumps({**idx, "model_version": "other-model"}), encoding="utf-8")
    before = idx_path.read_bytes()
    with pytest.raises(ValueError, match="other-model"):
        build_season(SEASON, dates=["2026-04-16"], **kw)
    assert not (tmp_path / "2026" / "2026-04-16.json").exists() and idx_path.read_bytes() == before


def test_build_rewind_cli_fails_on_broken_clusters(tmp_path):
    """clusters.pkl이 있는데 못 읽으면 유형을 null로 조용히 바꾸지 않고 exit 1 (되감기 재현성). 아무 파일도 안 쓴다."""
    from scripts import build_rewind

    bad = tmp_path / "clusters.pkl"
    bad.write_bytes(b"not a pickle")
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        build_rewind.main(["--season", "2026", "--dates", DAY, "--out-dir", str(out), "--clusters", str(bad)])
    assert exc.value.code not in (0, None) and not out.exists()


def test_build_rewind_cli_rejects_empty_dates(tmp_path):
    """--dates ""(빈 목록)는 시즌 전체로 바뀌지 않고 거절된다."""
    from scripts import build_rewind

    with pytest.raises(ValueError, match="empty"):
        build_rewind.main(["--season", "2026", "--dates", "", "--out-dir", str(tmp_path / "out")])
    assert not (tmp_path / "out").exists()


def test_canceled_games_are_listed(tmp_path, real_small):
    """취소 경기도 latest.json처럼 담긴다 (예측·결과 없음). 경기가 모두 취소된 날(08-06)도 파일과 전망이 있다."""
    idx = build_season(SEASON, out_dir=tmp_path, bundle=real_small["bundle"], team_bundle=real_small["team_bundle"],
                       meta=META, dates=["2026-08-06"], starter_types=real_small["starter_types"])
    day = json.loads((tmp_path / "2026" / "2026-08-06.json").read_text(encoding="utf-8"))
    assert day["games"] and all(g["status"] == "CANCELED" for g in day["games"])
    for g in day["games"]:
        assert g["home_win_prob"] is None and g["factors"] == [] and g["result"] is None and "status_note" in g
    assert day["outlook"]["type"] == "playoff_race" and len(day["outlook"]["teams"]) == 10
    assert idx["dates"] == [{"date": "2026-08-06", "games": len(day["games"]), "correct": 0, "decided": 0}]
    assert idx["accuracy"] is None and idx["n_decided"] == 0 and "train_win._correct" in idx["note"]
    # 같은 날짜를 state_before로 만든 것과도 같다 (취소 경기는 상태에 안 들어간다)
    assert day == json.loads(json.dumps(_payload(real_small, "2026-08-06")))


@pytest.mark.skipif(not PUBLISHED_INDEX.exists(), reason="data/public/rewind/2026 아직 생성 전")
def test_published_rewind_accuracy_equals_report():
    """발행된 되감기 시즌 정확도 == model_report.json의 lr(report-2026) 시험 정확도 (같은 702경기)."""
    idx = json.loads(PUBLISHED_INDEX.read_text(encoding="utf-8"))
    test = json.loads(MODEL_REPORT.read_text(encoding="utf-8"))["models"]["lr"]["test"]
    assert idx["model_version"] == "report-2026"
    assert idx["n_decided"] == test["n"]
    assert idx["accuracy"] == round(test["accuracy"], 4)
    assert np.isclose(sum(d["correct"] for d in idx["dates"]) / idx["n_decided"], test["accuracy"])
    files = sorted(p.stem for p in PUBLISHED_INDEX.parent.glob("2026-*.json"))
    assert files == [d["date"] for d in idx["dates"]] and len(files) == 165  # 정규시즌 경기(FINAL·취소)가 있는 날 전부
