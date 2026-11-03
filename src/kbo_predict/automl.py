"""오토머신러닝(FLAML)으로 "튜닝한 로지스틱 회귀가 정말 최선인가" 확인하기.

tune.py(랜덤 서치·그리드 서치)는 우리가 정한 6계열·탐색 범위 안에서만 찾는다. 여기서는 FLAML이 알고리즘과
하이퍼파라미터를 함께, 비용을 아끼는 순서(가벼운 설정부터)로 스스로 찾는다.
- 후보 알고리즘: LightGBM, XGBoost, 랜덤포레스트, 엑스트라 트리, 로지스틱 회귀(L1·L2), k-최근접 이웃.
- 학습 2015~2024, FLAML이 고르는 기준은 2025 검증 log loss(보정 전). 2026 시험은 고르는 데 쓰지 않는다.
- FLAML이 고른 최선의 설정은 tune.py와 똑같은 결승 절차(학습 시즌 LOSO로 none/platt/isotonic 보정 → 2025 검증으로 방법 선택
  → 2026 채점)를 거쳐 지금 모델·튜닝 추천 모델과 나란히 비교한다.
- 결측은 2015~2024 중앙값으로 채운 뒤 넘긴다(k-최근접 이웃·로지스틱 회귀가 NaN을 못 받으므로, 모든 후보에 같은 입력).

재현: FLAML 탐색은 시간 예산으로 멈추므로 실행마다 탐색 경로가 조금 다를 수 있다. 그래서 결과 파일에 "고른 모델의 종류와
설정 전체"를 적고, 결승 점수는 그 설정으로 다시 만든 모델(단일 스레드, 고정 시드)로 계산한다 → 노트북에서 같은 숫자가 나온다.
실행: python -m kbo_predict.automl [--time-budget 1200] [--out data/public/automl_report.json]
     python -m kbo_predict.automl --from-report
       → 탐색은 다시 하지 않고, 결과 파일에 적힌 "고른 모델 설정"으로 결승·비교만 다시 계산한다(재현 확인용, 몇 초).
"""
from __future__ import annotations

import argparse
import importlib
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.impute import SimpleImputer
from sklearn.metrics import log_loss

from . import KST
from .features import FEATURE_NAMES, load_features
from .train_win import CALIBRATIONS, _correct, apply_calibrator, fit_calibrator, mcnemar_p
from . import tune

ESTIMATORS = ["lgbm", "xgboost", "rf", "extra_tree", "lrl1", "lrl2", "kneighbor"]
SEED = tune.SEED


def _split(df: pd.DataFrame):
    train = df[df["season"].isin(tune.TRAIN_SEASONS)]
    return train, df[df["season"] == tune.VAL_SEASON], df[df["season"] == tune.TEST_SEASON]


def _imputed(train: pd.DataFrame, *others: pd.DataFrame) -> list[pd.DataFrame]:
    """학습 구간 중앙값으로 결측을 채운 피처 행렬들 (열 순서 = FEATURE_NAMES)."""
    imp = SimpleImputer(strategy="median", keep_empty_features=True).fit(train[FEATURE_NAMES].astype(float))
    return [pd.DataFrame(imp.transform(d[FEATURE_NAMES].astype(float)), columns=FEATURE_NAMES, index=d.index)
            for d in (train, *others)]


def search(df: pd.DataFrame, *, time_budget: int = 1200, log_file: str | None = None):
    """FLAML 탐색. 반환: (AutoML 객체, 탐색 요약 dict)."""
    from flaml import AutoML
    train, val, _ = _split(df)
    Xtr, Xval = _imputed(train, val)
    automl = AutoML()
    automl.fit(X_train=Xtr, y_train=train["y"].to_numpy(), X_val=Xval, y_val=val["y"].to_numpy(),
               task="classification", metric="log_loss", estimator_list=ESTIMATORS, time_budget=time_budget,
               seed=SEED, retrain_full=False, eval_method="holdout", verbose=0,
               log_file_name=log_file or "", n_jobs=-1)
    summary = {
        "best_estimator": automl.best_estimator,
        "best_val_logloss_raw": float(automl.best_loss),
        "best_config": automl.best_config,
        "best_loss_per_estimator": {k: (float(v) if v is not None and np.isfinite(v) else None)
                                    for k, v in automl.best_loss_per_estimator.items()},
        "best_config_per_estimator": {k: v for k, v in automl.best_config_per_estimator.items()},
        "time_budget_sec": time_budget,
    }
    return automl, summary


def describe(estimator) -> dict:
    """모델 객체 → {"class": "모듈.클래스", "params": 설정}. 다시 만들 때 쓴다(스레드는 1로 고정, 시드가 비어 있으면 고정 시드).
    예: FLAML의 L1 로지스틱 회귀는 saga 풀이기를 쓰는데, random_state가 None이면 실행마다 결과가 조금씩 달라진다."""
    params = {k: v for k, v in estimator.get_params().items() if isinstance(v, (int, float, str, bool, type(None)))}
    for k in ("n_jobs", "num_threads", "nthread"):
        if k in params:
            params[k] = 1
    for k in ("random_state", "seed"):
        if k in params and params[k] is None:
            params[k] = SEED
    return {"class": f"{type(estimator).__module__}.{type(estimator).__name__}", "params": params}


def rebuild(desc: dict):
    mod, name = desc["class"].rsplit(".", 1)
    return getattr(importlib.import_module(mod), name)(**desc["params"])


def _metrics(p, y):
    return {"n": int(len(y)), "accuracy": float(_correct(p, y).mean()), "log_loss": float(log_loss(y, p, labels=[0, 1])),
            "brier": float(np.mean((p - y) ** 2))}


def final_round(desc: dict, df: pd.DataFrame) -> dict:
    """tune.final_round와 같은 결승 절차를 '설정으로 다시 만든 모델'에 적용한다."""
    train, val, test = _split(df)
    Xtr, Xval, Xte = _imputed(train, val, test)
    y_tr, y_val, y_te = train["y"].to_numpy(), val["y"].to_numpy(), test["y"].to_numpy()
    model = rebuild(desc).fit(Xtr, y_tr)
    raw_val, raw_te = model.predict_proba(Xval)[:, 1], model.predict_proba(Xte)[:, 1]
    # 학습 시즌 leave-one-season-out 예측(보정 전) → 캘리브레이터 (결측 채우기도 빠진 시즌 없이 다시 맞춘다)
    oof = np.empty(len(train))
    season = train["season"].to_numpy()
    for s in sorted(set(season)):
        held = season == s
        a, b = _imputed(train[~held], train[held])
        oof[held] = clone(model).fit(a, y_tr[~held]).predict_proba(b)[:, 1]
    cal_loss, cals = {}, {}
    for m in CALIBRATIONS:
        cals[m] = None if m == "none" else fit_calibrator(m, oof, y_tr)
        cal_loss[m] = float(log_loss(y_val, apply_calibrator(cals[m], raw_val), labels=[0, 1]))
    best = min(CALIBRATIONS, key=cal_loss.get)
    p_val, p_te = apply_calibrator(cals[best], raw_val), apply_calibrator(cals[best], raw_te)
    return {"model": desc, "calibration": best, "calibration_val_logloss": cal_loss,
            "val": _metrics(p_val, y_val), "test": _metrics(p_te, y_te), "correct_test": _correct(p_te, y_te)}


def run(df: pd.DataFrame, *, time_budget: int = 1200, compare: dict | None = None, log=print, previous: dict | None = None) -> dict:
    """FLAML 탐색 → 고른 모델 결승 → 지금 모델·튜닝 추천과 비교. compare = tuning(그리드) 보고서.
    previous(이전 결과 파일)를 주면 탐색을 건너뛰고 그 파일의 탐색 요약·고른 모델 설정을 그대로 쓴다."""
    t0 = time.time()
    if previous:
        summary = previous["search"]
        desc = previous["automl_final"]["model"]
        for k in ("random_state", "seed"):
            if k in desc["params"] and desc["params"][k] is None:
                desc["params"][k] = SEED
    else:
        automl, summary = search(df, time_budget=time_budget)
        log(f"[automl] 탐색 끝: {summary['best_estimator']} raw val log loss {summary['best_val_logloss_raw']:.5f} ({time.time() - t0:.0f}s)")
        desc = describe(automl.model.estimator)
    fin = final_round(desc, df)
    cur = tune.final_round(*tune.CURRENT, df)
    fin["mcnemar_p_vs_current"] = mcnemar_p(fin["correct_test"], cur["correct_test"])
    rec = None
    if compare and compare.get("recommended"):
        r = compare["recommended"]
        rec_f = tune.final_round(r["family"], r["params"], df)
        rec = {"family": r["family"], "params": r["params"], "calibration": rec_f["calibration"],
               "val": rec_f["val"], "test": rec_f["test"],
               "mcnemar_p_vs_automl": mcnemar_p(rec_f["correct_test"], fin["correct_test"])}
    strip = lambda f: {k: v for k, v in f.items() if k != "correct_test"}
    best_val = min([fin["val"]["log_loss"]] + ([rec["val"]["log_loss"]] if rec else []))
    return {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "protocol": {"tool": "FLAML AutoML", "estimators": ESTIMATORS, "metric": "log_loss",
                     "train_seasons": tune.TRAIN_SEASONS, "val_season": tune.VAL_SEASON, "test_season": tune.TEST_SEASON,
                     "imputation": "train median (all candidates)", "seed": SEED, "test_used_for_selection": False},
        "search": summary,
        "automl_final": strip(fin),
        "current": strip(cur),
        "tuning_recommended": rec,
        "verdict": {"automl_beats_tuning_on_val": bool(rec is not None and fin["val"]["log_loss"] < rec["val"]["log_loss"]),
                    "best_val_logloss": best_val},
        "elapsed_sec": round(time.time() - t0, 1) if not previous else previous.get("elapsed_sec"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FLAML AutoML로 승패 모델 최선 확인")
    ap.add_argument("--features", default="data/processed/features.parquet")
    ap.add_argument("--time-budget", type=int, default=1200)
    ap.add_argument("--compare", default="data/public/tuning_grid_report.json")
    ap.add_argument("--out", default="data/public/automl_report.json")
    ap.add_argument("--from-report", action="store_true", help="탐색 없이 결과 파일의 모델 설정으로 결승만 다시")
    args = ap.parse_args(argv)
    df = load_features(args.features)
    cmp_path = Path(args.compare)
    prev = json.loads(Path(args.out).read_text(encoding="utf-8")) if args.from_report else None
    report = run(df, time_budget=args.time_budget, previous=prev,
                 compare=json.loads(cmp_path.read_text(encoding="utf-8")) if cmp_path.exists() else None)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    f = report["automl_final"]
    print(f"[automl] FLAML 최선: {report['search']['best_estimator']} → 결승 검증 log loss {f['val']['log_loss']:.5f}, "
          f"시험 정확도 {f['test']['accuracy']:.4f}, 튜닝 추천보다 {'좋음' if report['verdict']['automl_beats_tuning_on_val'] else '좋지 않음'} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
