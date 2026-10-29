"""승패 모델 코어: 로지스틱 회귀(LR)와 LightGBM을 같은 인터페이스로 감싼다.

모델 하나는 "번들"(dict) 하나로 다닌다. 번들 키:
    kind          "lr" 또는 "lgbm"
    model         학습된 sklearn 호환 추정기 (LR은 Pipeline, LightGBM은 LGBMClassifier)
    features      입력 피처 이름 목록 (기본 features.FEATURE_NAMES 26개, 순서 고정.
                  선발 없는 변형(ablation)은 features.TEAM_FEATURES 19개) — 예측·요인 분해는 이 목록의 열만 쓴다
    calibration   "none" / "platt" / "isotonic"
    calibrator    캘리브레이션 객체 (없으면 None)
    version       모델 버전 문자열 (예: MODEL_VERSION)
    trained_at    학습 시각 (KST, ISO 형식)
    n_games       학습에 쓴 경기 수
    seasons       학습에 쓴 시즌 목록
    n_estimators  LightGBM 트리 개수 (LR은 해당 없음 → None)

흐름: predict_raw(캘리브레이션 전 확률) → apply_calibrator → predict_proba(최종 확률).
explain은 캘리브레이션 전 로짓(log-odds)을 피처별 기여 + 기본값(base)으로 정확히 나눈다:
    contrib.sum(axis=1) + base == logit(predict_raw)

그 위에 평가(정확도·로그 손실·브라이어, 베이스라인 3종, 캘리브레이션 표, McNemar 검정, 피처 중요도)와
학습 CLI를 얹는다:
    python -m kbo_predict.train_win report [--force]  → data/public/model_report.json + models/report-2026.pkl
        보고서는 한 번 만든 뒤 얼려 둔다: 파일이 이미 있으면 --force 없이는 거부한다.
        2015~2024 학습 / 2025 검증(트리 수·캘리브레이션·알고리즘·유의성 비교 대상 선택) / 2026 홀드아웃 평가
        캘리브레이터는 train 시즌 leave-one-out 예측으로 맞추고, 방법 선택만 2025로 한다.
        선발 가정: 학습·평가 행의 선발 피처는 박스스코어의 '실제' 선발(투수 순서 1)로 만든다 — 지표는
        "경기 전에 선발을 안다"는 가정 위의 값이다 (라이브는 예고 선발). 그래서 선발 피처를 뺀
        팀 피처 19개 모델(ablation.no_starter)도 같은 절차로 학습해 함께 적는다.
    python -m kbo_predict.train_win report --force --matchup data/processed/matchup.parquet --clusters models/clusters.pkl
        ← 커밋된 model_report.json을 만드는 정식(전체) 명령. 위와 같고, 상성 피처(직전 시즌 선수 유형) 전후
        비교(matchup_feature_ablation)와 군집 품질(cluster_quality)을 보고서에 더한다. 본 모델·선택·지표는
        상성 피처 없이 만든 것 그대로다 (상성은 비교로만 기록, 라이브 반영은 4단계).
        주의: 기존 보고서에 그 두 블록이 있는데 해당 옵션 없이 `report --force`를 돌리면 블록이 null로 되돌아가므로
        거부한다 (정식 명령을 알려 준다). 일부러 지우려면 --reset-blocks를 더한다.
        상성 parquet는 먼저 `python -m kbo_predict.features --matchup-out data/processed/matchup.parquet
        --clusters models/clusters.pkl`로 만든다.
    python -m kbo_predict.train_win live    → models/win_model.pkl (v0.2, 2015~2026 전체 학습)
        보고서에서 selected·캘리브레이션 방법·LightGBM 트리 수만 읽는다 → report를 먼저 돌린다.
        parquet가 보고서 때와 달라도(새 경기가 쌓여도) 다시 학습할 수 있다 (해시 일치를 요구하지 않음).
    python -m kbo_predict.train_win live --skip-if-same   ← 주간 재학습(weekly_retrain.yml)
        위와 같이 학습한 뒤, 새 번들의 예측이 parquet 전 행에서 기존 win_model.pkl과 같으면(atol 1e-9)
        "unchanged"만 찍고 pkl·manifest를 쓰지 않는다 (새 경기가 없는 주에 trained_at만 바뀐 커밋이 생기지 않게).
models/manifest.json에는 모델별로 (파일 SHA256, 버전, 그 모델을 만든 parquet SHA256)을 적는다.
각 명령은 자기 모델 항목만 갱신하고 다른 항목은 기존 manifest 그대로 둔다.
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import KST, MODEL_VERSION, REPORT_VERSION, TEAM_VERSION
from .features import FACTOR_LABELS, FEATURE_NAMES, TEAM_FEATURES, load_features

SEED = 42
# 결정성: deterministic + 단일 스레드 + 고정 seed, 배깅(행 샘플링) 없음 → 같은 데이터면 같은 비트.
# force_row_wise는 LightGBM이 행/열 방식을 자동으로 고르며 내는 안내 메시지를 없애고 결과도 고정한다.
LGBM_PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_child_samples=50,
                   colsample_bytree=0.8, reg_lambda=1.0, deterministic=True, num_threads=1,
                   seed=SEED, verbose=-1, force_row_wise=True)
LR_C = 1.0

KINDS = ("lr", "lgbm")
CALIBRATIONS = ("none", "platt", "isotonic")
_EPS = 1e-6  # 확률을 로짓으로 바꿀 때 0·1에서 무한대가 나오지 않게 자르는 폭


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), _EPS, 1 - _EPS)
    return np.log(p / (1 - p))


def _matrix(features: list[str], X: pd.DataFrame) -> pd.DataFrame:
    """모델 입력 행렬: 정해진 피처만, 정해진 순서로, 실수형으로 (결측은 NaN 그대로)."""
    return X[features].astype(float)


def _new_estimator(kind: str, n_estimators: int):
    if kind == "lr":
        # 결측은 학습 데이터 중앙값으로 채운 뒤 표준화 → 계수가 "표준편차 1만큼 차이날 때의 로짓 변화"가 된다.
        # keep_empty_features=True: 학습 구간에 값이 하나도 없는 피처도 버리지 않아 계수가 항상 피처 수만큼 정렬된다.
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=LR_C, random_state=SEED, max_iter=2000)),
        ])
    if kind == "lgbm":
        # LightGBM은 NaN을 스스로 처리(분기마다 결측이 갈 방향을 학습)하므로 대치하지 않는다.
        return lgb.LGBMClassifier(**LGBM_PARAMS, n_estimators=n_estimators)
    raise ValueError(f"unknown kind: {kind!r} (expected one of {KINDS})")


def fit_model(df: pd.DataFrame, *, kind: str, n_estimators: int = 300, calibration: str = "none",
              calib_df: pd.DataFrame | None = None, version: str, seasons: list[int],
              features: list[str] | None = None) -> dict:
    """df(피처 + y)로 모델을 학습해 번들을 돌려준다. features: 쓸 피처 목록 (기본 FEATURE_NAMES 26개).
    calibration이 "none"이 아니면 calib_df(학습에 안 쓴 구간)의 예측으로 캘리브레이터를 따로 맞춘다."""
    features = list(FEATURE_NAMES if features is None else features)
    if calibration not in CALIBRATIONS:
        raise ValueError(f"unknown calibration: {calibration!r} (expected one of {CALIBRATIONS})")
    if calibration != "none" and calib_df is None:
        raise ValueError(f"calibration={calibration!r} needs calib_df")
    if calibration != "none" and len(calib_df) == 0:  # 비싼 학습 전에 확인
        raise ValueError("no calibration rows")
    if len(df) == 0:
        raise ValueError("no training rows")

    model = _new_estimator(kind, n_estimators)
    model.fit(_matrix(features, df), df["y"].to_numpy())
    bundle = {
        "kind": kind,
        "model": model,
        "features": features,
        "calibration": calibration,
        "calibrator": None,
        "version": version,
        "trained_at": datetime.now(KST).isoformat(timespec="seconds"),
        "n_games": int(len(df)),
        "seasons": [int(s) for s in seasons],
        "n_estimators": int(n_estimators) if kind == "lgbm" else None,
    }
    if calibration != "none":
        bundle["calibrator"] = fit_calibrator(calibration, predict_raw(bundle, calib_df), calib_df["y"].to_numpy())
    return bundle


def predict_raw(bundle: dict, X: pd.DataFrame) -> np.ndarray:
    """캘리브레이션 전 P(홈 승). 두 모델 모두 sklearn의 predict_proba를 그대로 쓴다."""
    return bundle["model"].predict_proba(_matrix(bundle["features"], X))[:, 1]


def predict_proba(bundle: dict, X: pd.DataFrame) -> np.ndarray:
    """최종 P(홈 승) = 캘리브레이션까지 적용한 확률."""
    return apply_calibrator(bundle["calibrator"], predict_raw(bundle, X))


def explain(bundle: dict, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """요인 분해. (contrib [n, 피처수], base [n]) — 모두 로짓 단위, 캘리브레이션 전.
    항등식: contrib.sum(axis=1) + base == logit(predict_raw(bundle, X)).
    - lgbm: LightGBM 내장 TreeSHAP(pred_contrib=True). 마지막 열이 기본값(bias).
    - lr  : 기여 = 계수 × 표준화 값 z (결측은 학습 중앙값으로 채운 뒤 기준), 기본값 = 절편.
            z=0은 "학습 평균과 같은 경기"이므로 base는 평균적인 경기의 로짓이다."""
    M = _matrix(bundle["features"], X)
    model = bundle["model"]
    if bundle["kind"] == "lgbm":
        out = model.booster_.predict(M, pred_contrib=True)
        return out[:, :-1], out[:, -1]
    steps = model.named_steps
    z = steps["scaler"].transform(steps["imputer"].transform(M))
    clf = steps["clf"]
    return z * clf.coef_[0], np.full(len(M), clf.intercept_[0])


def fit_calibrator(method: str, p_raw: np.ndarray, y: np.ndarray):
    """캘리브레이터 학습.
    - "platt"   : logit(p)를 입력 하나로 받는 로지스틱 회귀 (단조 증가 → 순위 보존).
                  교과서 Platt처럼 정규화(축소) 없이 맞춘다 — 기울기·절편 2개뿐이라 과적합 걱정이 없다.
    - "isotonic": 단조 계단 함수. 극단값이 0·1로 붙지 않게 [0.01, 0.99]로 제한."""
    p_raw, y = np.asarray(p_raw, dtype=float), np.asarray(y)
    if method == "platt":
        return LogisticRegression(penalty=None, max_iter=1000).fit(_logit(p_raw).reshape(-1, 1), y)
    if method == "isotonic":
        return IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99).fit(p_raw, y)
    raise ValueError(f"unknown calibration method: {method!r} (expected 'platt' or 'isotonic')")


def apply_calibrator(calibrator, p_raw: np.ndarray) -> np.ndarray:
    """캘리브레이터 적용. None이면 확률을 그대로 돌려준다."""
    if calibrator is None:
        return p_raw
    p_raw = np.asarray(p_raw, dtype=float)
    if isinstance(calibrator, LogisticRegression):
        return calibrator.predict_proba(_logit(p_raw).reshape(-1, 1))[:, 1]
    return calibrator.predict(p_raw)


def save_bundle(bundle: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def load_bundle(path: Path) -> dict:
    return joblib.load(Path(path))


# ---------- 평가 · 베이스라인 · 통계 ----------

def _correct(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    """경기별 정답 여부. P(홈 승) ≥ 0.5면 홈 승으로 예측 (정확히 반반이면 홈 — 베이스라인과 같은 규칙)."""
    return (np.asarray(p) >= 0.5).astype(int) == np.asarray(y)


def evaluate(bundle: dict, df: pd.DataFrame) -> dict:
    """최종 확률(캘리브레이션 포함)로 정확도·로그 손실·브라이어 점수를 잰다. 값은 JSON용 파이썬 숫자."""
    p, y = predict_proba(bundle, df), df["y"].to_numpy()
    return {
        "n": int(len(df)),
        "accuracy": float(_correct(p, y).mean()),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "brier": float(np.mean((p - y) ** 2)),
    }


def _baseline_preds(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """모델 없이 쓰는 단순 규칙 3가지의 경기별 예측 (1=홈 승). 값이 0이거나 없으면(NaN) 홈으로 찍는다."""
    wp, era = df["win_pct_diff"].to_numpy(dtype=float), df["starter_era_diff"].to_numpy(dtype=float)
    return {
        "home_always": np.ones(len(df), dtype=int),
        "better_win_pct": np.where(wp < 0, 0, 1),      # 승률이 높은 팀 (NaN < 0은 False → 홈)
        "lower_starter_era": np.where(era > 0, 0, 1),  # 선발 ERA가 낮은 팀 (홈−원정 > 0이면 원정이 낮음)
    }


def baselines(df: pd.DataFrame) -> dict:
    y = df["y"].to_numpy()
    return {name: float((pred == y).mean()) for name, pred in _baseline_preds(df).items()}


def calibration_table(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    """[0,1]을 같은 폭으로 나눈 칸마다 '예측 확률 평균'과 '실제 홈 승률'. 칸은 [lo, hi), 1.0은 마지막 칸.
    잘 맞춘(캘리브레이션된) 모델이면 두 값이 비슷하다. 빈 칸은 n=0, 평균은 None."""
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    idx = np.clip(np.floor(p * bins).astype(int), 0, bins - 1)
    table = []
    for i in range(bins):
        m = idx == i
        n = int(m.sum())
        table.append({"lo": i / bins, "hi": (i + 1) / bins, "n": n,
                      "pred_mean": float(p[m].mean()) if n else None,
                      "actual_rate": float(y[m].mean()) if n else None})
    return table


def mcnemar_p(correct_a: np.ndarray, correct_b: np.ndarray) -> float:
    """McNemar 정확 검정(양측): 두 예측기가 같은 경기들에서 정확도가 같은가?
    둘 다 맞히거나 둘 다 틀린 경기는 정보가 없으므로 '한쪽만 맞힌' 경기 수 b, c만 본다.
    정확도가 같다면 b ~ 이항(b+c, 0.5) → p = 2 × P(X ≤ min(b, c)), 1을 넘으면 1."""
    a, b_ = np.asarray(correct_a, dtype=bool), np.asarray(correct_b, dtype=bool)
    b, c = int((a & ~b_).sum()), int((~a & b_).sum())
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    return min(1.0, 2 * tail / 2 ** n)


def feature_importance(bundle: dict) -> list[dict]:
    """피처 중요도 (합 1로 정규화, 큰 순서). lgbm = 분기 이득(gain) 합, lr = 표준화 계수의 절댓값."""
    if bundle["kind"] == "lgbm":
        raw = bundle["model"].booster_.feature_importance(importance_type="gain")
    else:
        raw = np.abs(bundle["model"].named_steps["clf"].coef_[0])
    raw = np.asarray(raw, dtype=float)
    share = raw / raw.sum() if raw.sum() > 0 else raw
    order = sorted(range(len(raw)), key=lambda i: -share[i])  # 안정 정렬 → 동률은 피처 순서대로
    return [{"name": bundle["features"][i], "label": FACTOR_LABELS[bundle["features"][i]],
             "importance": float(share[i])} for i in order]


def oof_predictions(df: pd.DataFrame, *, kind: str, n_estimators: int,
                    features: list[str] | None = None) -> np.ndarray:
    """시즌 leave-one-out 예측: 시즌 s의 행은 's를 뺀 나머지 시즌'으로 학습한 모델이 예측한 확률(캘리브레이션 전).
    모든 행이 '학습에 안 쓴 데이터' 예측이 되므로, 전체 학습 모델의 캘리브레이터를 맞추는 데 쓴다. 행 순서 유지.
    features는 fit_model과 같다 (기본 FEATURE_NAMES) — 캘리브레이터를 붙일 모델과 같은 피처로 맞춰야 한다."""
    seasons = sorted(int(s) for s in df["season"].unique())
    if len(seasons) < 2:
        raise ValueError(f"leave-one-season-out needs >= 2 seasons, got {seasons}")
    out = np.empty(len(df), dtype=float)
    season_col = df["season"].to_numpy()
    for s in seasons:
        held = season_col == s
        rest = [x for x in seasons if x != s]
        m = fit_model(df[~held], kind=kind, n_estimators=n_estimators, version="oof", seasons=rest,
                      features=features)
        out[held] = predict_raw(m, df[held])
    return out


# ---------- 보고서(report-2026) · 라이브(v0.2) 학습 ----------

def _early_stopping_rounds(train: pd.DataFrame, val: pd.DataFrame, max_rounds: int = 2000,
                           features: list[str] | None = None) -> int:
    """LightGBM 트리 개수 결정: val 로그 손실이 50라운드 연속 나아지지 않으면 멈추고, 가장 좋았던 라운드를 쓴다.
    features: 쓸 피처 목록 (기본 FEATURE_NAMES)."""
    features = list(FEATURE_NAMES if features is None else features)
    m = _new_estimator("lgbm", max_rounds)
    m.fit(_matrix(features, train), train["y"].to_numpy(),
          eval_X=(_matrix(features, val),), eval_y=(val["y"].to_numpy(),), eval_metric="binary_logloss",
          callbacks=[lgb.early_stopping(50, verbose=False)])
    return int(m.best_iteration_ or max_rounds)


CALIBRATION_FIT = "loso_oof_train"  # 보고서에 적는 '캘리브레이터를 무엇으로 맞췄나'


def _choose_calibration(bundle: dict, train: pd.DataFrame, val: pd.DataFrame) -> tuple[dict, dict]:
    """캘리브레이션 3종(none/platt/isotonic)을 표본 밖(out-of-sample)에서 고른다.
    - 맞추기: train 시즌 leave-one-out 예측(oof_predictions) + train y → platt·isotonic 캘리브레이터.
    - 고르기: val 시즌의 (캘리브레이션 전) 예측에 각 캘리브레이터를 씌운 로그 손실이 가장 낮은 방법.
    val은 캘리브레이터 학습에 한 번도 쓰지 않는다 — val에서 맞추고 val에서 재면 자유도가 큰
    isotonic이 늘 이겨 버린다(낙관 편향). 라이브 모델(train_live)도 같은 방식(OOF)으로 맞춘다.
    반환: (선택된 캘리브레이터를 붙인 번들, {방법: val 로그 손실})."""
    oof = oof_predictions(train, kind=bundle["kind"], n_estimators=bundle["n_estimators"] or 300,
                          features=bundle["features"])
    raw_val, y_val = predict_raw(bundle, val), val["y"].to_numpy()
    losses, calibrators = {}, {}
    for method in CALIBRATIONS:
        calibrators[method] = None if method == "none" else fit_calibrator(method, oof, train["y"].to_numpy())
        losses[method] = float(log_loss(y_val, apply_calibrator(calibrators[method], raw_val), labels=[0, 1]))
    best = min(CALIBRATIONS, key=losses.get)  # 동률이면 앞의 것(단순한 쪽)
    return {**bundle, "calibration": best, "calibrator": calibrators[best]}, losses


# 학습·평가와 라이브가 선발 정보를 어디서 가져오는가 (보고서에 그대로 적는다)
STARTER_SOURCE = {"train_test": "actual (boxscore pitching order 1)", "live": "announced (schedule page)"}
BASELINE_ORDER = ("home_always", "better_win_pct", "lower_starter_era")  # _baseline_preds 순서 = 동률 순서


def _split(df: pd.DataFrame, train_seasons: list[int], val_season: int, test_season: int) -> dict:
    """시즌으로 train/val/test를 나눈다 (비어 있으면 ValueError). train_report와 train_team이 함께 쓴다."""
    parts = {"train": df[df["season"].isin(train_seasons)], "val": df[df["season"] == val_season],
             "test": df[df["season"] == test_season]}
    for name, part in parts.items():
        if len(part) == 0:
            wanted = train_seasons if name == "train" else (val_season if name == "val" else test_season)
            raise ValueError(f"no {name} rows for season(s) {wanted}")
    return parts


def _fit_team(kind: str, calibration: str, train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame,
              train_seasons: list[int], meta: dict | None = None) -> tuple[dict, dict]:
    """train_team의 본체: 이미 나눈 train/val/test로 (요약 dict, 번들)을 만든다."""
    best_iteration = _early_stopping_rounds(train, val, features=TEAM_FEATURES) if kind == "lgbm" else None
    n_est = best_iteration or 300
    b = fit_model(train, kind=kind, n_estimators=n_est, version=TEAM_VERSION, seasons=train_seasons,
                  features=TEAM_FEATURES)
    if calibration != "none":
        oof = oof_predictions(train, kind=kind, n_estimators=n_est, features=TEAM_FEATURES)
        b.update(calibration=calibration, calibrator=fit_calibrator(calibration, oof, train["y"].to_numpy()))
    if meta and meta.get("generated_at"):
        b["trained_at"] = meta["generated_at"]
    summary = {"kind": kind, "calibration": calibration, "best_iteration": best_iteration,
               "features": list(TEAM_FEATURES), "n_features": len(TEAM_FEATURES),
               "val": evaluate(b, val), "test": evaluate(b, test)}
    return summary, b


def train_team(df: pd.DataFrame, *, train_seasons=range(2015, 2025), val_season: int = 2025,
               test_season: int = 2026, kind: str, calibration: str,
               meta: dict | None = None) -> tuple[dict, dict]:
    """선발 없는 팀 모델: 선택된 알고리즘(kind)을 팀 피처 19개(TEAM_FEATURES)만으로 보고서와 같은 절차로 학습한다.
    - 트리 수: lgbm이면 19개 피처로 val early stopping을 다시 돌린다 (lr은 해당 없음 → None).
    - 캘리브레이션: 보고서에서 고른 방법을, train 시즌 LOSO OOF 예측으로 맞춘다 (val로 맞추지 않음).
    반환: (ablation.no_starter에 들어가는 요약 dict, 번들 version=TEAM_VERSION)."""
    train_seasons = [int(s) for s in train_seasons]
    parts = _split(df, train_seasons, val_season, test_season)
    return _fit_team(kind, calibration, parts["train"], parts["val"], parts["test"], train_seasons, meta)


def _no_starter_ablation(kind: str, calibration: str, train: pd.DataFrame, val: pd.DataFrame,
                         test: pd.DataFrame, train_seasons: list[int]) -> dict:
    """선발 없는 변형의 요약 dict (ablation.no_starter) — train_team과 같은 절차, 번들은 버린다.
    학습·평가의 선발은 '실제' 선발이므로, 이 변형과의 차이가 '선발을 안다'는 가정이 지표에 얼마나 보태는지 보여 준다."""
    return _fit_team(kind, calibration, train, val, test, train_seasons)[0]


MATCHUP_ADOPT_MARGIN = 0.001  # 상성 피처 채택 기준: val 로그 손실이 이만큼보다 더 줄어야 한다
MATCHUP_NOTE = "선택된 알고리즘·캘리브레이션·트리 수 고정, 피처만 추가. 라이브 반영은 4단계."


def _fit_fixed(kind: str, calibration: str, n_estimators: int | None, train: pd.DataFrame,
               train_seasons: list[int], features: list[str]) -> dict:
    """정해 둔 알고리즘·트리 수·캘리브레이션 방법으로 학습. 캘리브레이터는 본 모델과 똑같이 train 시즌
    LOSO OOF 예측으로 맞춘다 (n_estimators가 None이면 300 — lr에서는 쓰이지 않는다, _choose_calibration과 같음)."""
    n_est = n_estimators or 300
    b = fit_model(train, kind=kind, n_estimators=n_est, version=REPORT_VERSION, seasons=train_seasons,
                  features=features)
    if calibration != "none":
        oof = oof_predictions(train, kind=kind, n_estimators=n_est, features=features)
        b.update(calibration=calibration, calibrator=fit_calibrator(calibration, oof, train["y"].to_numpy()))
    return b


def _validation_scope(fit_seasons: list[int] | None, val_season: int, test_season: int) -> str:
    """검증·test 비교가 시간상 얼마나 엄밀한지 한 문장으로. 비교에 쓰는 유형은 직전 시즌(season-1) 유형이지만,
    그 유형을 매기는 중심은 fit_seasons 성적으로 맞췄으므로 중심이 그 평가 시즌의 성적을 봤는지가 기준이다."""
    if not fit_seasons:
        return "군집 맞춤 시즌 정보가 없어 검증·test 비교가 시간 외(out-of-time) 비교인지 판정하지 않았다."
    span, last = f"{min(fit_seasons)}~{max(fit_seasons)}", max(fit_seasons)
    if last >= test_season:
        return (f"검증({val_season})·test({test_season}) 비교 모두 {span} 성적으로 맞춘 중심(평가 시즌 성적도 본 중심)으로 "
                "유형을 매겼으므로 엄밀한 시간 외(out-of-time) 비교가 아닌 전이적(transductive) 비교다.")
    if last >= val_season:
        return (f"검증({val_season}) 비교의 직전 시즌({val_season - 1}) 유형은 {val_season} 성적까지 본 {span} 맞춤 "
                f"중심으로 매겨져 엄밀한 시간 외(out-of-time) 비교가 아닌 전이적(transductive) 비교이고, "
                f"test({test_season}) 비교만 엄밀한 시간 외 비교다.")
    return f"군집 중심({span})이 검증({val_season})·test({test_season}) 성적을 보지 않았으므로 두 비교 모두 시간 외 비교다."


def _matchup_note(fit_seasons: list[int] | None, val_season: int, test_season: int) -> str:
    """전후 비교의 단서: 군집 중심이 어떤 시즌 성적으로 맞춰졌는지 (승패 결과는 쓰지 않은 비지도 군집),
    검증·test 비교의 시간 범위(_validation_scope), 선발 유형을 어느 선발로 만드는지."""
    span = f"{min(fit_seasons)}~{max(fit_seasons)}" if fit_seasons else "맞춤 시즌"
    return (f"{MATCHUP_NOTE} 유형 군집 중심은 {span} 선수-시즌 성적으로만 맞췄다(비지도, 경기 승패는 쓰지 않음). "
            "피처는 직전 시즌 유형이라 그 경기 시즌의 성적으로 매긴 유형은 쓰지 않지만, 중심 자체는 맞춤 시즌 전체 "
            "성적을 봤으므로 학습 시즌 경기의 직전 시즌 유형도 그 뒤 시즌 성적까지 본 중심으로 매겨졌다. "
            f"{_validation_scope(fit_seasons, val_season, test_season)} "
            "starter_type 차이는 다른 선발 피처처럼 박스스코어의 실제 선발(투수 순서 1)로 만든다 (라이브는 예고 선발).")


def _matchup_ablation(selected: str, calibration: str, best_iteration: int, train: pd.DataFrame,
                      val: pd.DataFrame, test: pd.DataFrame, train_seasons: list[int], names: list[str], *,
                      fit_seasons: list[int] | None = None, cluster_version: str | None = None) -> dict:
    """상성 피처 전후 비교: 선택된 알고리즘(selected)·캘리브레이션 방법·트리 수(best_iteration)를 고정하고
    피처만 FEATURE_NAMES → FEATURE_NAMES + names로 늘려 같은 절차(캘리브레이터는 train LOSO OOF)로 학습한다.
    without은 본 모델과 같은 절차이므로 본 모델의 val·test 지표와 똑같다.
    mcnemar_p_test: test 경기에서 with와 without의 적중 차이 검정. adopt: with의 val 로그 손실이
    without보다 MATCHUP_ADOPT_MARGIN보다 더 낮을 때만 True (test는 채택 판단에 쓰지 않는다).
    validation_scope: 검증·test 비교가 시간 외(out-of-time) 비교인지 한 문장 (_validation_scope)."""
    val_season, test_season = int(val["season"].iloc[0]), int(test["season"].iloc[0])
    n_est = best_iteration if selected == "lgbm" else None
    out, correct = {}, {}
    for key, feats in (("without", list(FEATURE_NAMES)), ("with", list(FEATURE_NAMES) + list(names))):
        b = _fit_fixed(selected, calibration, n_est, train, train_seasons, feats)
        out[key] = {"val": evaluate(b, val), "test": evaluate(b, test)}
        correct[key] = _correct(predict_proba(b, test), test["y"].to_numpy())
    return {
        "features_added": list(names),
        "without": out["without"], "with": out["with"],
        "mcnemar_p_test": mcnemar_p(correct["with"], correct["without"]),
        "adopt": bool(out["with"]["val"]["log_loss"] < out["without"]["val"]["log_loss"] - MATCHUP_ADOPT_MARGIN),
        "note": _matchup_note(fit_seasons, val_season, test_season),
        "validation_scope": _validation_scope(fit_seasons, val_season, test_season),
        "fit_seasons": [int(s) for s in fit_seasons] if fit_seasons else None,
        "cluster_version": cluster_version,
    }


def _with_matchup(df: pd.DataFrame, matchup: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """df에 상성 열을 game_id로 붙인다 (행 순서 유지). 상성 표에 없는 경기가 있으면 데이터가 어긋난 것이므로 거부."""
    names = [c for c in matchup.columns if c != "game_id"]
    merged = df.merge(matchup, on="game_id", how="left", validate="one_to_one", indicator=True)
    missing = int((merged["_merge"] != "both").sum())
    if missing:
        raise ValueError(f"matchup table is missing {missing} game_id(s) present in the feature frame")
    return merged.drop(columns="_merge"), names


def _significance(bundle: dict, val: pd.DataFrame, test: pd.DataFrame) -> dict:
    """유의성: 선택 모델 vs 베이스라인, test 경기들 위의 McNemar 검정.
    비교 대상(vs)은 val 정확도가 가장 높은 베이스라인으로 '미리' 정한다 — test에서 가장 잘한 것을 고르면
    비교 대상 선택 자체가 test를 본 셈이 된다. 동률이면 BASELINE_ORDER의 앞. 세 베이스라인 모두 all에 적는다."""
    base_val = baselines(val)
    vs = next(name for name in BASELINE_ORDER if base_val[name] == max(base_val.values()))
    y_test = test["y"].to_numpy()
    model_ok = _correct(predict_proba(bundle, test), y_test)
    preds = _baseline_preds(test)
    every = {}
    for name in BASELINE_ORDER:
        base_ok = preds[name] == y_test
        every[name] = {"mcnemar_p": mcnemar_p(model_ok, base_ok), "model_correct": int(model_ok.sum()),
                       "baseline_correct": int(base_ok.sum())}
    return {"vs": vs, "selected_on": "val", **every[vs], "all": every}


def train_report(df: pd.DataFrame, *, train_seasons=range(2015, 2025), val_season: int = 2025,
                 test_season: int = 2026, meta: dict, matchup: pd.DataFrame | None = None,
                 cluster_quality: dict | None = None) -> tuple[dict, dict]:
    """보고서용 모델: train 시즌으로 학습(캘리브레이터는 train OOF로) → val 시즌으로 트리 수·캘리브레이션 방법·
    알고리즘·유의성 비교 대상 선택 → test 시즌은 마지막에 한 번만 평가. 선발 없는 변형(ablation.no_starter)도 함께.
    matchup(game_id + 상성 열)을 주면 상성 피처 전후 비교(matchup_feature_ablation)를, cluster_quality를 주면
    그 dict를 그대로 보고서에 넣는다. 둘 다 본 모델·선택·나머지 지표에는 영향이 없다 (없으면 None).
    반환: (model_report.json 내용, 선택된 번들 version=REPORT_VERSION)."""
    train_seasons = [int(s) for s in train_seasons]
    parts = _split(df, train_seasons, val_season, test_season)
    train, val, test = parts["train"], parts["val"], parts["test"]

    best_iteration = _early_stopping_rounds(train, val)
    bundles, models = {}, {}
    for kind in KINDS:
        raw_bundle = fit_model(train, kind=kind, n_estimators=best_iteration, version=REPORT_VERSION,
                               seasons=train_seasons)
        b, cal_losses = _choose_calibration(raw_bundle, train, val)
        bundles[kind] = b
        models[kind] = {"calibration": b["calibration"], "calibration_fit": CALIBRATION_FIT,
                        "calibration_val_logloss": cal_losses, "val": evaluate(b, val), "test": evaluate(b, test)}
    models["lgbm"]["best_iteration"] = best_iteration
    selected = min(KINDS, key=lambda k: models[k]["val"]["log_loss"])  # 동률이면 lr(KINDS 순서)
    bundle = bundles[selected]
    if meta.get("generated_at"):
        bundle["trained_at"] = meta["generated_at"]

    y_test = test["y"].to_numpy()
    p_test = predict_proba(bundle, test)

    report = {
        "model_version": REPORT_VERSION,
        "generated_at": meta.get("generated_at"),
        "commit_sha": meta.get("commit_sha"),
        "run_url": meta.get("run_url"),
        "features_sha256": meta.get("features_sha256"),
        "train_seasons": train_seasons,
        "val_season": int(val_season),
        "test_season": int(test_season),
        "n": {name: int(len(part)) for name, part in parts.items()},
        "models": models,
        "selected": selected,
        "starter_source": dict(STARTER_SOURCE),
        "baselines": {"val": baselines(val), "test": baselines(test)},
        "significance": _significance(bundle, val, test),
        "calibration_bins": calibration_table(p_test, y_test),
        "feature_importance": feature_importance(bundle),
        "ablation": {"no_starter": _no_starter_ablation(selected, bundle["calibration"], train, val, test,
                                                        train_seasons)},
        "matchup_feature_ablation": None,  # 상성 피처 전후 비교 (matchup을 줄 때만)
        "cluster_quality": cluster_quality,  # 선수 유형 군집 품질 (cluster.quality)
    }
    if matchup is not None:
        merged, names = _with_matchup(df, matchup)
        m_parts = [merged[merged["season"].isin(train_seasons)], merged[merged["season"] == val_season],
                   merged[merged["season"] == test_season]]
        cq = cluster_quality or {}
        report["matchup_feature_ablation"] = _matchup_ablation(
            selected, bundle["calibration"], best_iteration, *m_parts, train_seasons, names,
            fit_seasons=cq.get("fit_seasons"), cluster_version=cq.get("version"))
    return report, bundle


def train_live(df: pd.DataFrame, *, kind: str, calibration: str, n_estimators: int, meta: dict,
               features: list[str] | None = None) -> dict:
    """사이트용 라이브 모델: 있는 시즌 전부로 학습 (알고리즘·캘리브레이션 방법·트리 수는 보고서에서 고른 값).
    전체를 학습에 쓰면 캘리브레이터를 맞출 '안 본 데이터'가 없으므로, 시즌 leave-one-out 예측(oof_predictions)으로 맞춘다.
    features: 쓸 피처 목록 (기본 FEATURE_NAMES 26개). CLI는 기본값을 쓴다."""
    seasons = sorted(int(s) for s in df["season"].unique())
    bundle = fit_model(df, kind=kind, n_estimators=n_estimators, version=MODEL_VERSION, seasons=seasons,
                       features=features)
    if calibration != "none":
        oof = oof_predictions(df, kind=kind, n_estimators=n_estimators, features=features)
        bundle.update(calibration=calibration, calibrator=fit_calibrator(calibration, oof, df["y"].to_numpy()))
    if meta.get("generated_at"):
        bundle["trained_at"] = meta["generated_at"]
    return bundle


SKIP_ATOL = 1e-9  # live --skip-if-same: 이 차이 안이면 '같은 모델'로 본다


def same_predictions(bundle: dict, old_path: Path, df: pd.DataFrame, atol: float = SKIP_ATOL) -> bool:
    """bundle과 old_path의 번들이 df 전 행에서 같은 최종 확률(predict_proba)을 내는가 (np.allclose, rtol 0, atol).
    old_path가 없거나, 읽을 수 없거나, 피처가 달라 예측할 수 없으면 False (= 새 번들을 써야 한다)."""
    old_path = Path(old_path)
    if not old_path.exists():
        return False
    try:
        old = load_bundle(old_path)
        if old.get("features") != bundle["features"]:
            return False
        return bool(np.allclose(predict_proba(bundle, df), predict_proba(old, df), rtol=0.0, atol=atol))
    except Exception:  # 깨진 pkl, 예전 형식 번들 등 → 새로 쓴다
        return False


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_manifest(path: Path, *, name: str, bundle_path: Path, features_path: Path, meta: dict,
                   matchup_path: Path | None = None) -> None:
    """models/manifest.json의 모델 하나(name) 항목만 갱신한다: 모델 파일 SHA256·버전 + 그 모델을 만든 parquet SHA256.
    다른 모델 항목은 기존 manifest에서 그대로 둔다 — 이번에 다시 학습하지 않은 모델 파일에 새 parquet 해시를
    붙이지 않기 위해서다. generated_at·commit_sha는 마지막으로 manifest를 쓴 실행의 값.
    matchup_path를 주면(보고서의 상성 전후 비교에 쓴 parquet) 그 SHA256도 matchup_sha256으로 적는다."""
    entry = {"path": Path(bundle_path).as_posix(), "sha256": _sha256(bundle_path),
             "version": load_bundle(bundle_path).get("version"), "features_sha256": _sha256(features_path)}
    if matchup_path is not None:
        entry["matchup_sha256"] = _sha256(matchup_path)
    update_manifest(path, name=name, meta=meta, entry=entry)


def update_manifest(path: Path, *, name: str, entry: dict, meta: dict) -> None:
    """manifest의 models[name]만 entry로 바꾸고 다른 항목은 그대로 둔다 (승패 모델·군집 번들이 함께 쓴다)."""
    path = Path(path)
    models = json.loads(path.read_text(encoding="utf-8")).get("models", {}) if path.exists() else {}
    models[name] = entry
    _write_json(path, {"generated_at": meta.get("generated_at"), "commit_sha": meta.get("commit_sha"),
                       "models": models})


def _commit_sha() -> str | None:
    """지금 코드의 커밋: GitHub Actions면 GITHUB_SHA, 아니면 `git rev-parse HEAD`. 둘 다 안 되면 None."""
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = (out.stdout or "").strip()
    return sha if out.returncode == 0 and sha else None


# ---------- CLI ----------

REPORT_JSON = Path("data/public/model_report.json")
REPORT_PKL = Path(f"models/{REPORT_VERSION}.pkl")
LIVE_PKL = Path("models/win_model.pkl")
TEAM_PKL = Path(f"models/{TEAM_VERSION}.pkl")
MANIFEST = Path("models/manifest.json")


CANONICAL_REPORT_CMD = ("python -m kbo_predict.train_win report --force "
                       "--matchup data/processed/matchup.parquet --clusters models/clusters.pkl")


def _guard_report_blocks(path: Path, *, matchup, clusters, reset: bool) -> None:
    """report --force가 기존 보고서의 상성 비교·군집 품질 블록을 모르게 null로 지우지 않게 막는다.
    기존 파일에 matchup_feature_ablation(또는 cluster_quality)이 있는데 --matchup(또는 --clusters)이 없으면
    정식 명령(CANONICAL_REPORT_CMD)을 알려 주며 거부한다. --reset-blocks면 그대로 진행한다.
    기존 파일을 JSON으로 읽을 수 없으면 지킬 블록도 없으므로 진행한다."""
    if reset:
        return
    try:
        old = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(old, dict):
        return
    lost = [key for key, opt, given in (("matchup_feature_ablation", "--matchup", matchup),
                                        ("cluster_quality", "--clusters", clusters))
            if old.get(key) is not None and not given]
    if lost:
        raise SystemExit(f"{Path(path).name} has non-null {', '.join(lost)}; running without the matching option "
                         f"would reset it to null. Run the canonical command:\n  {CANONICAL_REPORT_CMD}\n"
                         "(or add --reset-blocks to drop those blocks on purpose)")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="승패 모델 학습: report(2015~2024 학습/2025 검증/2026 평가) · "
                                             "live(전 시즌) · team(선발 없는 팀 모델 저장)")
    ap.add_argument("command", choices=["report", "live", "team"])
    ap.add_argument("--features", default="data/processed/features.parquet", help="피처 parquet 경로")
    ap.add_argument("--force", action="store_true", help="report: 이미 있는(얼려 둔) model_report.json을 덮어쓴다")
    ap.add_argument("--matchup", help="report: 상성 피처 parquet (features --matchup-out) → matchup_feature_ablation")
    ap.add_argument("--clusters", help="report: 군집 묶음 pkl (models/clusters.pkl) → cluster_quality")
    ap.add_argument("--reset-blocks", action="store_true",
                    help="report --force: 기존 보고서의 matchup_feature_ablation·cluster_quality를 null로 되돌려도 된다")
    ap.add_argument("--skip-if-same", action="store_true",
                    help="live: 새 번들의 예측이 기존 win_model.pkl과 같으면(전 행, atol 1e-9) 아무것도 쓰지 않는다")
    args = ap.parse_args(argv)
    if args.skip_if_same and args.command != "live":
        ap.error("--skip-if-same is only for the live command")
    if args.command == "report" and REPORT_JSON.exists():
        if not args.force:
            raise SystemExit(f"{REPORT_JSON.name} exists; use --force to overwrite the frozen report")
        _guard_report_blocks(REPORT_JSON, matchup=args.matchup, clusters=args.clusters, reset=args.reset_blocks)
    if args.command in ("live", "team") and not REPORT_JSON.exists():
        raise SystemExit(f"{REPORT_JSON} not found — run `python -m kbo_predict.train_win report` first")
    features_path = Path(args.features)
    meta = {"generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "commit_sha": _commit_sha(), "run_url": os.environ.get("RUN_URL"),
            "features_sha256": _sha256(features_path)}
    df = load_features(features_path)
    t0 = time.time()
    if args.command == "report":
        cluster_quality = None
        if args.clusters:
            from . import cluster  # cluster가 train_win을 import하므로 순환을 피해 여기서 읽는다

            obj = cluster.load_bundle(Path(args.clusters))
            cluster_quality = cluster.quality(bundles={g: obj[g]["bundle"] for g in cluster.GROUPS},
                                              assigned={g: obj[g]["assigned"] for g in cluster.GROUPS},
                                              names_cfg=cluster.load_labels())
        matchup = load_features(Path(args.matchup)) if args.matchup else None
        report, bundle = train_report(df, meta=meta, matchup=matchup, cluster_quality=cluster_quality)
        _write_json(REPORT_JSON, report)
        save_bundle(bundle, REPORT_PKL)
        sel = report["models"][report["selected"]]
        print(f"selected: {report['selected']} (calibration={sel['calibration']}, "
              f"best_iteration={report['models']['lgbm']['best_iteration']})")
        print(f"test {report['test_season']}: acc={sel['test']['accuracy']:.4f} "
              f"log_loss={sel['test']['log_loss']:.4f} brier={sel['test']['brier']:.4f}")
        ns = report["ablation"]["no_starter"]
        print(f"no_starter (team 19): acc={ns['test']['accuracy']:.4f} log_loss={ns['test']['log_loss']:.4f} "
              f"brier={ns['test']['brier']:.4f}")
        sig = report["significance"]
        print(f"vs {sig['vs']} (chosen on {sig['selected_on']}): McNemar p={sig['mcnemar_p']:.4f}  "
              + "  ".join(f"{k}={v['mcnemar_p']:.4f}" for k, v in sig["all"].items()))
        mf = report["matchup_feature_ablation"]
        if mf is not None:
            for part in ("val", "test"):
                w, o = mf["with"][part], mf["without"][part]
                print(f"matchup {part}: acc {o['accuracy']:.4f} -> {w['accuracy']:.4f}  "
                      f"log_loss {o['log_loss']:.4f} -> {w['log_loss']:.4f}  brier {o['brier']:.4f} -> {w['brier']:.4f}")
            print(f"matchup McNemar p(test)={mf['mcnemar_p_test']:.4f}  adopt={mf['adopt']}")
    elif args.command == "team":
        # 보고서의 selected·calibration만 읽는다. model_report.json은 건드리지 않는다.
        report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        kind = report["selected"]
        summary, bundle = train_team(df, kind=kind, calibration=report["models"][kind]["calibration"], meta=meta)
        save_bundle(bundle, TEAM_PKL)
        print(f"team {bundle['version']}: {kind} calibration={bundle['calibration']} "
              f"n_features={summary['n_features']} best_iteration={summary['best_iteration']}")
        print(f"test: acc={summary['test']['accuracy']:.4f} log_loss={summary['test']['log_loss']:.4f} "
              f"brier={summary['test']['brier']:.4f}")
    else:
        # 보고서에서는 선택 결과 세 가지만 읽는다. parquet 해시는 맞춰 보지 않는다 — 라이브는 새 경기가 쌓인
        # parquet로 다시 학습하는 것이 정상이고, 어떤 parquet로 만들었는지는 manifest의 live 항목에 남는다.
        report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        kind = report["selected"]
        bundle = train_live(df, kind=kind, calibration=report["models"][kind]["calibration"],
                            n_estimators=report["models"]["lgbm"]["best_iteration"], meta=meta)
        if args.skip_if_same and same_predictions(bundle, LIVE_PKL, df):
            # 주간 재학습: 새 경기가 없어 예측이 그대로면 pkl·manifest를 다시 쓰지 않는다 (trained_at만 바뀐 커밋 방지)
            print(f"unchanged: {LIVE_PKL.as_posix()} predicts the same on all {len(df)} rows "
                  f"(atol {SKIP_ATOL:g}); nothing written")
            print(f"done in {time.time() - t0:.1f}s")
            return
        save_bundle(bundle, LIVE_PKL)
        print(f"live {bundle['version']}: {kind} calibration={bundle['calibration']} "
              f"seasons={bundle['seasons'][0]}~{bundle['seasons'][-1]} n={bundle['n_games']}")
    print(f"done in {time.time() - t0:.1f}s")
    name, bundle_path = {"report": ("report", REPORT_PKL), "live": ("live", LIVE_PKL),
                         "team": ("team", TEAM_PKL)}[args.command]
    write_manifest(MANIFEST, name=name, bundle_path=bundle_path, features_path=features_path, meta=meta,
                   matchup_path=Path(args.matchup) if args.command == "report" and args.matchup else None)


if __name__ == "__main__":
    main()
