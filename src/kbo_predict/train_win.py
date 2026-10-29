"""승패 모델 코어: 로지스틱 회귀(LR)와 LightGBM을 같은 인터페이스로 감싼다.

모델 하나는 "번들"(dict) 하나로 다닌다. 번들 키:
    kind          "lr" 또는 "lgbm"
    model         학습된 sklearn 호환 추정기 (LR은 Pipeline, LightGBM은 LGBMClassifier)
    features      입력 피처 이름 목록 (features.FEATURE_NAMES, 26개, 순서 고정)
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
평가·리포트·CLI는 Task 5에서 이 함수들 위에 얹는다.
"""
from datetime import datetime
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import KST
from .features import FEATURE_NAMES

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
        # keep_empty_features=True: 학습 구간에 값이 하나도 없는 피처도 버리지 않아 계수가 항상 26개로 정렬된다.
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
              calib_df: pd.DataFrame | None = None, version: str, seasons: list[int]) -> dict:
    """df(피처 26개 + y)로 모델을 학습해 번들을 돌려준다.
    calibration이 "none"이 아니면 calib_df(학습에 안 쓴 구간)의 예측으로 캘리브레이터를 따로 맞춘다."""
    if calibration not in CALIBRATIONS:
        raise ValueError(f"unknown calibration: {calibration!r} (expected one of {CALIBRATIONS})")
    if calibration != "none" and calib_df is None:
        raise ValueError(f"calibration={calibration!r} needs calib_df")
    if len(df) == 0:
        raise ValueError("no training rows")

    model = _new_estimator(kind, n_estimators)
    model.fit(_matrix(FEATURE_NAMES, df), df["y"].to_numpy())
    bundle = {
        "kind": kind,
        "model": model,
        "features": list(FEATURE_NAMES),
        "calibration": calibration,
        "calibrator": None,
        "version": version,
        "trained_at": datetime.now(KST).isoformat(timespec="seconds"),
        "n_games": int(len(df)),
        "seasons": [int(s) for s in seasons],
        "n_estimators": int(n_estimators) if kind == "lgbm" else None,
    }
    if calibration != "none":
        if len(calib_df) == 0:
            raise ValueError("no calibration rows")
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
    - "isotonic": 단조 계단 함수. 극단값이 0·1로 붙지 않게 [0.01, 0.99]로 제한."""
    p_raw, y = np.asarray(p_raw, dtype=float), np.asarray(y)
    if method == "platt":
        return LogisticRegression().fit(_logit(p_raw).reshape(-1, 1), y)
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
