"""승패 모델 후보 넓히기 + 하이퍼파라미터 튜닝.

지금 성적표 모델(report-2026)은 로지스틱 회귀와 LightGBM 두 개만 비교해 로지스틱 회귀를 골랐다.
여기서는 후보를 6계열로 넓히고, 계열마다 정해진 범위에서 설정을 고정 시드로 뽑아(랜덤 서치) 고른다.

데이터 나누기 (성적표와 같은 원칙 — 2026 시험 시즌은 고르는 데 한 번도 쓰지 않는다)
  1) 튜닝 점수: 2021~2025 다섯 시즌 "앞 시즌들로 학습 → 그 시즌 예측"(확장 창 교차검증)의 log loss 평균.
     한 시즌(약 700경기)만으로 고르면 설정 수십 개 중 운 좋은 것이 뽑히기 쉬워서, 약 3,500경기로 점수를 낸다.
     점수는 보정 전 확률로 매긴다(보정은 3단계에서 성적표와 똑같이 붙인다).
  2) 계열별 1등만 남긴다(결승 진출).
  3) 결승: 성적표와 같은 절차 — 2015~2024로 학습, 캘리브레이터(none/platt/isotonic)는 학습 시즌
     leave-one-season-out 예측으로 맞추고 2025 검증 log loss로 방법을 고른다. 결승 진출자 중 2025 검증
     log loss가 가장 낮은 것이 "추천 모델"이다.
  4) 2026 시험은 그 뒤에 채점한다. 모든 결승 진출자의 시험 점수를 함께 적지만, 고르는 데는 쓰지 않았다.
  5) 채택 기준: 추천 모델의 2025 검증 log loss가 지금 모델(로지스틱 회귀, C=1)보다 ADOPT_MARGIN 넘게
     낮아야 "바꿀 만하다"로 본다. 시험에서는 지금 모델과의 McNemar 검정도 함께 적는다.

결정성: 모든 모델에 고정 시드, 트리 부스팅은 단일 스레드 → 같은 데이터면 .py와 노트북의 결과가 같다.
실행: python -m kbo_predict.tune [--n-iter 40] [--out data/public/tuning_report.json]
     python -m kbo_predict.tune --grid [--jobs 20] [--out data/public/tuning_grid_report.json]
       → 그리드 서치: 탐색 범위의 "모든 조합"을 같은 교차검증으로 잰다(설정 약 3,600개, 프로세스 병렬).
         병렬로 돌려도 각 설정의 점수는 같다(설정마다 고정 시드·단일 스레드).
"""
from __future__ import annotations

import argparse
import itertools
import json
import time
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import KST
from .features import FEATURE_NAMES, load_features
from .train_win import CALIBRATIONS, LR_C, _correct, apply_calibrator, baselines, fit_calibrator, mcnemar_p

SEED = 42
TRAIN_SEASONS = list(range(2015, 2025))
VAL_SEASON, TEST_SEASON = 2025, 2026
CV_SEASONS = [2021, 2022, 2023, 2024, 2025]   # 확장 창 교차검증: 이 시즌 각각을 "그 앞 시즌 전부"로 학습해 예측
ADOPT_MARGIN = 0.002                          # 2025 검증 log loss가 이만큼 넘게 줄어야 "바꿀 만하다"
RF_JOBS = -1                                  # 랜덤포레스트·엑스트라 트리 코어 수 (그리드 병렬 실행 때는 프로세스마다 1)
FAMILIES = ("logreg", "random_forest", "extra_trees", "hist_gb", "lightgbm", "xgboost")
FAMILY_KO = {"logreg": "로지스틱 회귀", "random_forest": "랜덤포레스트", "extra_trees": "엑스트라 트리",
             "hist_gb": "히스토그램 부스팅(sklearn)", "lightgbm": "LightGBM", "xgboost": "XGBoost"}
CURRENT = ("logreg", {"C": LR_C, "penalty": "l2"})   # 지금 성적표·라이브 모델과 같은 설정

# ---------- 탐색 범위: 계열마다 "값 후보 목록" (랜덤 서치가 여기서 하나씩 고른다) ----------
SPACE = {
    "logreg": {"C": [0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0], "penalty": ["l2", "l1"]},
    "random_forest": {"n_estimators": [300, 600], "max_depth": [4, 6, 8, 12, None], "min_samples_leaf": [10, 20, 50, 100],
                      "max_features": ["sqrt", 0.3, 0.5]},
    "extra_trees": {"n_estimators": [300, 600], "max_depth": [4, 6, 8, 12, None], "min_samples_leaf": [10, 20, 50, 100],
                    "max_features": ["sqrt", 0.3, 0.5]},
    "hist_gb": {"learning_rate": [0.02, 0.05, 0.1], "max_iter": [100, 200, 400], "max_depth": [2, 3, 4, None],
                "min_samples_leaf": [20, 50, 100], "l2_regularization": [0.0, 1.0, 10.0]},
    "lightgbm": {"learning_rate": [0.01, 0.03, 0.05], "n_estimators": [100, 200, 400, 800], "num_leaves": [4, 7, 15, 31],
                 "min_child_samples": [20, 50, 100], "colsample_bytree": [0.5, 0.8, 1.0], "reg_lambda": [0.0, 1.0, 10.0]},
    "xgboost": {"learning_rate": [0.01, 0.03, 0.05], "n_estimators": [100, 200, 400, 800], "max_depth": [2, 3, 4, 6],
                "min_child_weight": [1, 5, 20], "subsample": [0.7, 1.0], "colsample_bytree": [0.5, 0.8, 1.0],
                "reg_lambda": [1.0, 10.0]},
}


def sample_configs(family: str, n_iter: int, seed: int = SEED) -> list[dict]:
    """탐색 범위에서 설정 n_iter개를 고정 시드로 뽑는다(중복 제거, 순서 고정). 로지스틱 회귀는 조합이 14개라 전부.
    지금 모델 설정(CURRENT)은 로지스틱 회귀 목록에 반드시 들어간다."""
    space = SPACE[family]
    keys = list(space)
    rng = np.random.default_rng([seed, FAMILIES.index(family)])
    total = int(np.prod([len(space[k]) for k in keys]))
    seen, out = set(), []
    if family == "logreg":
        import itertools
        return [dict(zip(keys, combo)) for combo in itertools.product(*(space[k] for k in keys))]
    while len(out) < min(n_iter, total):
        cfg = {k: space[k][int(rng.integers(len(space[k])))] for k in keys}
        key = json.dumps(cfg, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            out.append(cfg)
    return out


def grid_configs(family: str) -> list[dict]:
    """탐색 범위의 모든 조합(그리드). 순서 고정(값 목록 순서의 곱)."""
    space = SPACE[family]
    keys = list(space)
    return [dict(zip(keys, combo)) for combo in itertools.product(*(space[k] for k in keys))]


def make_estimator(family: str, params: dict):
    """설정 하나 → 학습 전 모델. 결측(NaN)은 선형·배깅 모델에서 학습 데이터 중앙값으로 채우고,
    부스팅(sklearn·LightGBM·XGBoost)은 결측을 스스로 처리하게 둔다."""
    impute = SimpleImputer(strategy="median", keep_empty_features=True)
    if family == "logreg":
        solver = "liblinear" if params["penalty"] == "l1" else "lbfgs"
        return Pipeline([("imputer", impute), ("scaler", StandardScaler()),
                         ("clf", LogisticRegression(C=params["C"], penalty=params["penalty"], solver=solver,
                                                    random_state=SEED, max_iter=5000))])
    if family == "random_forest":
        return Pipeline([("imputer", impute), ("clf", RandomForestClassifier(**params, random_state=SEED, n_jobs=RF_JOBS))])
    if family == "extra_trees":
        return Pipeline([("imputer", impute), ("clf", ExtraTreesClassifier(**params, random_state=SEED, n_jobs=RF_JOBS))])
    if family == "hist_gb":
        return HistGradientBoostingClassifier(**params, random_state=SEED, early_stopping=False)
    if family == "lightgbm":
        return lgb.LGBMClassifier(objective="binary", **params, deterministic=True, num_threads=1, seed=SEED,
                                  verbose=-1, force_row_wise=True)
    if family == "xgboost":
        import xgboost as xgb
        return xgb.XGBClassifier(objective="binary:logistic", eval_metric="logloss", tree_method="hist", **params,
                                 random_state=SEED, n_jobs=1)
    raise ValueError(f"unknown family {family!r}")


def _X(df: pd.DataFrame) -> pd.DataFrame:
    return df[FEATURE_NAMES].astype(float)


def fit_predict(family: str, params: dict, train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """train으로 학습하고 test의 P(홈 승)(보정 전)을 돌려준다."""
    m = make_estimator(family, params)
    m.fit(_X(train), train["y"].to_numpy())
    return m.predict_proba(_X(test))[:, 1]


def cv_score(family: str, params: dict, df: pd.DataFrame, seasons=CV_SEASONS) -> dict:
    """확장 창 교차검증: 시즌 s마다 's 이전 시즌 전부'로 학습해 s를 예측. 시즌별·전체 log loss와 정확도."""
    per, ys, ps = {}, [], []
    for s in seasons:
        train, test = df[df["season"] < s], df[df["season"] == s]
        p = fit_predict(family, params, train, test)
        y = test["y"].to_numpy()
        per[int(s)] = float(log_loss(y, p, labels=[0, 1]))
        ys.append(y)
        ps.append(p)
    y, p = np.concatenate(ys), np.concatenate(ps)
    return {"log_loss": float(log_loss(y, p, labels=[0, 1])), "accuracy": float(_correct(p, y).mean()),
            "per_season_log_loss": per, "n": int(len(y))}


def loso_oof(family: str, params: dict, train: pd.DataFrame) -> np.ndarray:
    """학습 시즌 leave-one-season-out 예측(보정 전) — 캘리브레이터를 맞추는 데 쓴다(성적표와 같은 방식)."""
    out = np.empty(len(train))
    season = train["season"].to_numpy()
    for s in sorted(set(season)):
        held = season == s
        out[held] = fit_predict(family, params, train[~held], train[held])
    return out


def _metrics(p: np.ndarray, y: np.ndarray) -> dict:
    return {"n": int(len(y)), "accuracy": float(_correct(p, y).mean()), "log_loss": float(log_loss(y, p, labels=[0, 1])),
            "brier": float(np.mean((p - y) ** 2))}


def final_round(family: str, params: dict, df: pd.DataFrame) -> dict:
    """결승: 2015~2024 학습 → 캘리브레이션 3종을 학습 시즌 LOSO로 맞추고 2025 검증으로 고름 → 2025·2026 점수.
    반환에 2026 경기별 정답 여부(correct_test)를 넣어 McNemar 비교에 쓴다(JSON에는 빼고 저장)."""
    train = df[df["season"].isin(TRAIN_SEASONS)]
    val, test = df[df["season"] == VAL_SEASON], df[df["season"] == TEST_SEASON]
    model = make_estimator(family, params).fit(_X(train), train["y"].to_numpy())
    raw_val, raw_test = model.predict_proba(_X(val))[:, 1], model.predict_proba(_X(test))[:, 1]
    oof = loso_oof(family, params, train)
    y_tr, y_val, y_test = train["y"].to_numpy(), val["y"].to_numpy(), test["y"].to_numpy()
    cal_loss, calibrators = {}, {}
    for method in CALIBRATIONS:
        calibrators[method] = None if method == "none" else fit_calibrator(method, oof, y_tr)
        cal_loss[method] = float(log_loss(y_val, apply_calibrator(calibrators[method], raw_val), labels=[0, 1]))
    best = min(CALIBRATIONS, key=cal_loss.get)
    p_val, p_test = apply_calibrator(calibrators[best], raw_val), apply_calibrator(calibrators[best], raw_test)
    return {"family": family, "params": params, "calibration": best, "calibration_val_logloss": cal_loss,
            "val": _metrics(p_val, y_val), "test": _metrics(p_test, y_test),
            "correct_test": _correct(p_test, y_test)}


def run(df: pd.DataFrame, *, n_iter: int = 40, families=FAMILIES, log=print) -> dict:
    """튜닝 전체: 계열별 랜덤 서치(교차검증) → 계열별 1등 결승 → 추천·채택 판단. 결과 dict(JSON용)."""
    t0 = time.time()
    search, finalists = {}, []
    for fam in families:
        rows = []
        for i, params in enumerate(sample_configs(fam, n_iter)):
            sc = cv_score(fam, params, df)
            rows.append({"params": params, **sc})
        rows.sort(key=lambda r: r["log_loss"])
        search[fam] = rows
        log(f"[tune] {fam}: {len(rows)}개 설정, CV log loss 최고 {rows[0]['log_loss']:.5f}, 걸린 시간 {time.time() - t0:.0f}s")
    current = final_round(*CURRENT, df)
    for fam in families:
        finalists.append(final_round(fam, search[fam][0]["params"], df))
    best = min(finalists, key=lambda f: f["val"]["log_loss"])
    gain = current["val"]["log_loss"] - best["val"]["log_loss"]
    test_df = df[df["season"] == TEST_SEASON]
    for f in finalists + [current]:
        f["mcnemar_p_vs_current"] = mcnemar_p(f["correct_test"], current["correct_test"])
    strip = lambda f: {k: v for k, v in f.items() if k != "correct_test"}
    return {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "protocol": {"cv_seasons": CV_SEASONS, "cv": "expanding window (train on all seasons before s)",
                     "train_seasons": TRAIN_SEASONS, "val_season": VAL_SEASON, "test_season": TEST_SEASON,
                     "selection": "per-family best by CV log loss (raw), then finalist with lowest 2025 val log loss after calibration",
                     "calibration": "none/platt/isotonic fit on train leave-one-season-out predictions, chosen by val",
                     "adopt_margin": ADOPT_MARGIN, "n_iter": n_iter, "seed": SEED,
                     "test_used_for_selection": False},
        "search_space": SPACE,
        "search": {fam: rows[:10] for fam, rows in search.items()},   # 계열별 상위 10개만 저장
        "n_configs": {fam: len(rows) for fam, rows in search.items()},
        "current": strip(current),
        "finalists": [strip(f) for f in sorted(finalists, key=lambda f: f["val"]["log_loss"])],
        "recommended": {"family": best["family"], "params": best["params"], "calibration": best["calibration"],
                        "val_logloss_gain_vs_current": float(gain), "adopt": bool(gain > ADOPT_MARGIN)},
        "baselines_test": baselines(test_df),
        "elapsed_sec": round(time.time() - t0, 1),
    }


def _cv_task(family: str, params: dict, df: pd.DataFrame) -> dict:
    """그리드 병렬 작업 하나: 프로세스 안에서 랜덤포레스트 코어를 1개로 묶고 교차검증 점수를 낸다."""
    global RF_JOBS
    RF_JOBS = 1
    return {"params": params, **cv_score(family, params, df)}


def run_grid(df: pd.DataFrame, *, families=FAMILIES, jobs: int = 20, random_report: dict | None = None, log=print) -> dict:
    """그리드 서치: 계열마다 모든 조합을 교차검증 → 계열별 1등 결승(final_round) → 추천.
    random_report(랜덤 서치 결과)를 주면 계열별로 "그리드 1등이 랜덤 1등보다 나은가"를 함께 적는다."""
    from joblib import Parallel, delayed
    t0 = time.time()
    search = {}
    for fam in families:
        cfgs = grid_configs(fam)
        rows = Parallel(n_jobs=jobs, prefer="processes")(delayed(_cv_task)(fam, c, df) for c in cfgs)
        rows.sort(key=lambda r: (r["log_loss"], json.dumps(r["params"], sort_keys=True, default=str)))
        search[fam] = rows
        log(f"[grid] {fam}: {len(rows)}개 조합, CV log loss 최고 {rows[0]['log_loss']:.5f}, 누적 {time.time() - t0:.0f}s")
    current = final_round(*CURRENT, df)
    finalists = [final_round(fam, search[fam][0]["params"], df) for fam in families]
    for f in finalists + [current]:
        f["mcnemar_p_vs_current"] = mcnemar_p(f["correct_test"], current["correct_test"])
    best = min(finalists, key=lambda f: f["val"]["log_loss"])
    gain = current["val"]["log_loss"] - best["val"]["log_loss"]
    strip = lambda f: {k: v for k, v in f.items() if k != "correct_test"}
    vs_random = None
    if random_report:
        vs_random = {}
        for fam in families:
            r_best = random_report["search"][fam][0]
            vs_random[fam] = {"random_best_cv": r_best["log_loss"], "grid_best_cv": search[fam][0]["log_loss"],
                              "random_params": r_best["params"], "grid_params": search[fam][0]["params"],
                              "same_config": r_best["params"] == search[fam][0]["params"],
                              "grid_rank_of_random_best": next((i + 1 for i, row in enumerate(search[fam])
                                                                if row["params"] == r_best["params"]), None)}
    return {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "protocol": {"method": "grid search (all combinations of search_space)", "cv_seasons": CV_SEASONS,
                     "train_seasons": TRAIN_SEASONS, "val_season": VAL_SEASON, "test_season": TEST_SEASON,
                     "adopt_margin": ADOPT_MARGIN, "seed": SEED, "test_used_for_selection": False},
        "search_space": SPACE,
        "n_configs": {fam: len(rows) for fam, rows in search.items()},
        "search": {fam: rows[:10] for fam, rows in search.items()},
        "current": strip(current),
        "finalists": [strip(f) for f in sorted(finalists, key=lambda f: f["val"]["log_loss"])],
        "recommended": {"family": best["family"], "params": best["params"], "calibration": best["calibration"],
                        "val_logloss_gain_vs_current": float(gain), "adopt": bool(gain > ADOPT_MARGIN)},
        "vs_random_search": vs_random,
        "elapsed_sec": round(time.time() - t0, 1),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="승패 모델 후보 6계열 랜덤 서치 튜닝")
    ap.add_argument("--features", default="data/processed/features.parquet")
    ap.add_argument("--n-iter", type=int, default=40)
    ap.add_argument("--out", default=None)
    ap.add_argument("--grid", action="store_true", help="그리드 서치(모든 조합)")
    ap.add_argument("--jobs", type=int, default=20, help="그리드 병렬 프로세스 수")
    args = ap.parse_args(argv)
    df = load_features(args.features)
    if args.grid:
        out = args.out or "data/public/tuning_grid_report.json"
        rnd = Path("data/public/tuning_report.json")
        report = run_grid(df, jobs=args.jobs, random_report=json.loads(rnd.read_text(encoding="utf-8")) if rnd.exists() else None)
        args.out = out
    else:
        args.out = args.out or "data/public/tuning_report.json"
        report = run(df, n_iter=args.n_iter)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    r = report["recommended"]
    print(f"[tune] 추천: {r['family']} {r['params']} ({r['calibration']}), 검증 log loss 개선 {r['val_logloss_gain_vs_current']:+.5f}, "
          f"채택 {'예' if r['adopt'] else '아니오'} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
