"""여러 시즌 시험(walk-forward 백테스트): 한 시즌(약 700경기)으로는 작은 차이를 우연과 구분할 수 없어서, 시즌마다
"그 앞 시즌들로만 학습 → 그 시즌 예측"을 2018~2026 아홉 번 되풀이해 약 6,300경기로 성적을 잰다.

왜 필요한가
- 성적표(report-2026)의 2026 한 시즌 결과는 "선발 평균자책점 낮은 팀" 규칙보다 +2.7%p였지만 McNemar p = 0.215였다.
  702경기에서 p < 0.05가 되려면 대략 +4.4%p가 필요하다(서로 다르게 맞힌 경기 약 250개 기준). 야구 승패 예측에서는 아주 큰 차이다.
- 경기 수를 늘리는 정직한 방법은 "미래를 보지 않는" 예측을 여러 시즌에 걸쳐 모으는 것이다. 각 시즌의 예측은 그 시즌보다 앞선
  기록으로만 학습한 모델이 낸다(시험 누출 없음).

후보와 고르는 규칙 (결과를 보기 전에 정한 것 — 2026-11-03)
- current : 지금 라이브 모델과 같은 설정(로지스틱 회귀 L2, C=1, 피처 26개)
- l1      : 로지스틱 회귀 L1, C=0.03 (tune.py 랜덤 서치 추천, 오토머신러닝도 같은 답)
- l1_elo  : l1 + Elo 전력 점수 차이 피처 1개 (features.parquet의 elo_diff = features.Elo, 설정은 미리 고정한 값 — 튜닝하지 않음)
- ensemble: l1 + 그리드 1등 랜덤포레스트 + 그리드 1등 XGBoost의 확률 평균
- 개발 시즌 2018~2025의 합친 log loss가 가장 낮은 후보를 고른다. 2026은 고른 뒤 채점만 한다.
- 주의(정직하게 적는 것): l1·ensemble의 설정은 2021~2025 교차검증으로 골랐으므로, 그 시즌 성적은 조금 유리하다.
  그래서 설정 선택에 쓰지 않은 시즌(2018~2020, 2026)만 따로 모은 성적도 함께 적는다.
- 확률 보정(Platt 등)은 하지 않는다: 시즌마다 보정용 시즌을 따로 떼면 학습 기록이 줄어 비교가 흔들린다. 정확도는 50% 기준이라
  보정 영향이 작고, log loss 비교는 모든 후보가 같은 조건(보정 없음)이다.

검정
- 정확도: 같은 경기들에서 "한쪽만 맞힌" 경기 수로 McNemar 정확 검정(train_win.mcnemar_p).
- log loss: 경기별 log loss 차이의 대응표본 t 검정(경기 수가 커서 정규 근사) — 확률의 질까지 보므로 정확도보다 민감하다.

실행: python -m kbo_predict.backtest [--out data/public/backtest_report.json]
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import KST
from .features import ELO_BASE, ELO_CARRY, ELO_HOME, ELO_K, FEATURE_NAMES, load_features
from .train_win import _baseline_preds, _correct, mcnemar_p
from . import tune

SEASONS = list(range(2018, 2027))        # 예측하는 시즌 (각각 그 앞 시즌 전부로 학습, 최소 3시즌)
DEV_SEASONS = list(range(2018, 2026))    # 후보를 고르는 데 쓰는 시즌
TEST_SEASON = 2026                       # 고른 뒤 채점만
CLEAN_SEASONS = [2018, 2019, 2020, 2026]  # 어떤 설정 선택에도 쓰지 않은 시즌
RULES = ("home_always", "better_win_pct", "lower_starter_era")
EPS = 1e-6


RF_BEST = {"n_estimators": 300, "max_depth": 6, "min_samples_leaf": 20, "max_features": 0.3}
XGB_BEST = {"learning_rate": 0.03, "n_estimators": 100, "max_depth": 3, "min_child_weight": 1, "subsample": 0.7,
            "colsample_bytree": 1.0, "reg_lambda": 1.0}
CANDIDATES = {
    "current": {"label": "v0.2 설정 (로지스틱 L2, C=1)", "members": [("logreg", {"C": 1.0, "penalty": "l2"})], "elo": False},
    "l1": {"label": "로지스틱 L1, C=0.03", "members": [("logreg", {"C": 0.03, "penalty": "l1"})], "elo": False},
    "l1_elo": {"label": "로지스틱 L1 + Elo", "members": [("logreg", {"C": 0.03, "penalty": "l1"})], "elo": True},
    "ensemble": {"label": "앙상블 (L1 + 랜덤포레스트 + XGBoost 평균)",
                 "members": [("logreg", {"C": 0.03, "penalty": "l1"}), ("random_forest", RF_BEST), ("xgboost", XGB_BEST)], "elo": False},
}


def _fit_predict(cand: dict, train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> np.ndarray:
    ps = []
    for family, params in cand["members"]:
        m = tune.make_estimator(family, params).fit(train[cols].astype(float), train["y"].to_numpy())
        ps.append(m.predict_proba(test[cols].astype(float))[:, 1])
    return np.mean(ps, axis=0)


def _ll(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def paired_t_p(a: np.ndarray, b: np.ndarray) -> float:
    """경기별 손실 차이(a − b)의 평균이 0인가 — 양측 p (정규 근사, n이 수천이라 t ≈ 정규)."""
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    if len(d) < 2 or d.std(ddof=1) == 0:
        return 1.0
    z = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))
    return float(math.erfc(abs(z) / math.sqrt(2)))


def predictions(df: pd.DataFrame, *, seasons=SEASONS, candidates=CANDIDATES, log=print) -> pd.DataFrame:
    """시즌마다 그 앞 시즌들로 학습한 후보별 P(홈 승). 열: season, game_id, y, 규칙 3개(1=홈), 후보별 확률."""
    if "elo_diff" not in df.columns:
        raise ValueError("features.parquet에 elo_diff 열이 없습니다 — python -m kbo_predict.features --out ...로 다시 만드세요")
    rows = []
    for s in seasons:
        train, test = df[df["season"] < s], df[df["season"] == s]
        out = test[["season", "game_id", "y"]].copy()
        for name, pred in _baseline_preds(test).items():
            out[f"rule_{name}"] = pred
        for name, cand in candidates.items():
            cols = FEATURE_NAMES + (["elo_diff"] if cand["elo"] else [])
            out[name] = _fit_predict(cand, train, test, cols)
        rows.append(out)
        log(f"[backtest] {s}: 학습 {train['season'].min()}~{s - 1} {len(train):,}경기 → 예측 {len(test)}경기")
    return pd.concat(rows, ignore_index=True)


def _summ(pred: pd.DataFrame, names) -> dict:
    y = pred["y"].to_numpy()
    res = {"n": int(len(pred))}
    for n in names:
        p = pred[n].to_numpy()
        res[n] = {"accuracy": float(_correct(p, y).mean()), "log_loss": float(_ll(p, y).mean())}
    for r in RULES:
        res[f"rule_{r}"] = {"accuracy": float((pred[f"rule_{r}"].to_numpy() == y).mean())}
    return res


def _tests(pred: pd.DataFrame, name: str) -> dict:
    y = pred["y"].to_numpy()
    c = _correct(pred[name].to_numpy(), y)
    out = {f"mcnemar_p_vs_rule_{r}": mcnemar_p(c, pred[f"rule_{r}"].to_numpy() == y) for r in RULES}
    if name != "current":
        out["mcnemar_p_vs_current"] = mcnemar_p(c, _correct(pred["current"].to_numpy(), y))
        out["logloss_p_vs_current"] = paired_t_p(_ll(pred[name].to_numpy(), y), _ll(pred["current"].to_numpy(), y))
        out["logloss_gain_vs_current"] = float(_ll(pred["current"].to_numpy(), y).mean() - _ll(pred[name].to_numpy(), y).mean())
    return out


def run(df: pd.DataFrame, *, log=print) -> dict:
    t0 = time.time()
    pred = predictions(df, log=log)
    names = list(CANDIDATES)
    by_season = {int(s): _summ(g, names) for s, g in pred.groupby("season")}
    for s, g in pred.groupby("season"):
        by_season[int(s)]["tests"] = {n: _tests(g, n) for n in names}
    scopes = {"dev": DEV_SEASONS, "all": SEASONS, "clean": CLEAN_SEASONS, "test": [TEST_SEASON]}
    pooled = {}
    for k, ss in scopes.items():
        g = pred[pred["season"].isin(ss)]
        pooled[k] = {"seasons": ss, **_summ(g, names), "tests": {n: _tests(g, n) for n in names}}
    chosen = min(names, key=lambda n: pooled["dev"][n]["log_loss"])
    return {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "protocol": {
            "method": "walk-forward: each season predicted by a model trained only on earlier seasons",
            "seasons": SEASONS, "dev_seasons": DEV_SEASONS, "test_season": TEST_SEASON, "clean_seasons": CLEAN_SEASONS,
            "selection_rule": "lowest pooled log loss over dev seasons (decided 2026-11-03 before computing)",
            "calibration": "none (all candidates)",
            "elo": {"k": ELO_K, "home": ELO_HOME, "carry": ELO_CARRY, "base": ELO_BASE, "tuned": False},
            "note": "l1/ensemble hyperparameters were chosen with 2021-2025 CV, so their 2021-2025 results are slightly optimistic; see 'clean'.",
        },
        "candidates": {n: {"label": c["label"], "members": c["members"], "elo": c["elo"]} for n, c in CANDIDATES.items()},
        "rules": {"home_always": "항상 홈팀", "better_win_pct": "시즌 승률이 높은 팀", "lower_starter_era": "선발 평균자책점이 낮은 팀"},
        "by_season": by_season,
        "pooled": pooled,
        "chosen": chosen,
        "elapsed_sec": round(time.time() - t0, 1),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="여러 시즌 시험(walk-forward 백테스트)")
    ap.add_argument("--features", default="data/processed/features.parquet")
    ap.add_argument("--out", default="data/public/backtest_report.json")
    args = ap.parse_args(argv)
    rep = run(load_features(args.features))
    Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    a = rep["pooled"]["all"]
    print(f"[backtest] 고른 후보: {rep['chosen']} / 2018~2026 {a['n']:,}경기: " + ", ".join(
        f"{n} {a[n]['accuracy']:.1%}" for n in CANDIDATES) + f" / 규칙(선발 평균자책점) {a['rule_lower_starter_era']['accuracy']:.1%} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
