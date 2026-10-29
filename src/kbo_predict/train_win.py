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

그 위에 평가(정확도·로그 손실·브라이어, 베이스라인 3종, 캘리브레이션 표, McNemar 검정, 피처 중요도)와
학습 CLI를 얹는다:
    python -m kbo_predict.train_win report  → data/public/model_report.json + models/report-2026.pkl
        2015~2024 학습 / 2025 검증(트리 수·캘리브레이션·알고리즘 선택) / 2026 홀드아웃 평가
    python -m kbo_predict.train_win live    → models/win_model.pkl (v0.2, 2015~2026 전체 학습)
        보고서가 고른 알고리즘·캘리브레이션·트리 수를 그대로 쓴다 → report를 먼저 돌린다.
두 명령 모두 models/manifest.json(피처·모델 파일 SHA256)을 갱신한다.
"""
import argparse
import hashlib
import json
import math
import os
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

from . import KST, MODEL_VERSION, REPORT_VERSION
from .features import FACTOR_LABELS, FEATURE_NAMES, load_features

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
    if calibration != "none" and len(calib_df) == 0:  # 비싼 학습 전에 확인
        raise ValueError("no calibration rows")
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


def oof_predictions(df: pd.DataFrame, *, kind: str, n_estimators: int) -> np.ndarray:
    """시즌 leave-one-out 예측: 시즌 s의 행은 's를 뺀 나머지 시즌'으로 학습한 모델이 예측한 확률(캘리브레이션 전).
    모든 행이 '학습에 안 쓴 데이터' 예측이 되므로, 전체 학습 모델의 캘리브레이터를 맞추는 데 쓴다. 행 순서 유지."""
    seasons = sorted(int(s) for s in df["season"].unique())
    if len(seasons) < 2:
        raise ValueError(f"leave-one-season-out needs >= 2 seasons, got {seasons}")
    out = np.empty(len(df), dtype=float)
    season_col = df["season"].to_numpy()
    for s in seasons:
        held = season_col == s
        rest = [x for x in seasons if x != s]
        m = fit_model(df[~held], kind=kind, n_estimators=n_estimators, version="oof", seasons=rest)
        out[held] = predict_raw(m, df[held])
    return out


# ---------- 보고서(report-2026) · 라이브(v0.2) 학습 ----------

def _early_stopping_rounds(train: pd.DataFrame, val: pd.DataFrame, max_rounds: int = 2000) -> int:
    """LightGBM 트리 개수 결정: val 로그 손실이 50라운드 연속 나아지지 않으면 멈추고, 가장 좋았던 라운드를 쓴다."""
    m = _new_estimator("lgbm", max_rounds)
    m.fit(_matrix(FEATURE_NAMES, train), train["y"].to_numpy(),
          eval_X=(_matrix(FEATURE_NAMES, val),), eval_y=(val["y"].to_numpy(),), eval_metric="binary_logloss",
          callbacks=[lgb.early_stopping(50, verbose=False)])
    return int(m.best_iteration_ or max_rounds)


def _choose_calibration(bundle: dict, val: pd.DataFrame) -> dict:
    """캘리브레이션 3종(none/platt/isotonic) 중 val 로그 손실이 가장 낮은 것을 붙인 번들을 돌려준다.
    주의(낙관 편향): 캘리브레이터를 val에서 맞추고 같은 val에서 평가하므로 val 지표는 약간 좋게 나온다
    (특히 자유도가 큰 isotonic). 그래서 최종 성능은 손대지 않은 test 시즌으로만 말한다."""
    raw, y = predict_raw(bundle, val), val["y"].to_numpy()
    best = None
    for method in CALIBRATIONS:  # 동률이면 앞의 것(단순한 쪽)
        cal = None if method == "none" else fit_calibrator(method, raw, y)
        loss = log_loss(y, apply_calibrator(cal, raw), labels=[0, 1])
        if best is None or loss < best[0]:
            best = (loss, method, cal)
    return {**bundle, "calibration": best[1], "calibrator": best[2]}


def train_report(df: pd.DataFrame, *, train_seasons=range(2015, 2025), val_season: int = 2025,
                 test_season: int = 2026, meta: dict) -> tuple[dict, dict]:
    """보고서용 모델: train 시즌으로 학습 → val 시즌으로 트리 수·캘리브레이션·알고리즘 선택 → test 시즌은 마지막에 한 번만 평가.
    반환: (model_report.json 내용, 선택된 번들 version=REPORT_VERSION)."""
    train_seasons = [int(s) for s in train_seasons]
    parts = {"train": df[df["season"].isin(train_seasons)], "val": df[df["season"] == val_season],
             "test": df[df["season"] == test_season]}
    for name, part in parts.items():
        if len(part) == 0:
            wanted = train_seasons if name == "train" else (val_season if name == "val" else test_season)
            raise ValueError(f"no {name} rows for season(s) {wanted}")
    train, val, test = parts["train"], parts["val"], parts["test"]

    best_iteration = _early_stopping_rounds(train, val)
    bundles = {
        kind: _choose_calibration(fit_model(train, kind=kind, n_estimators=best_iteration,
                                            version=REPORT_VERSION, seasons=train_seasons), val)
        for kind in KINDS
    }
    models = {kind: {"calibration": b["calibration"], "val": evaluate(b, val), "test": evaluate(b, test)}
              for kind, b in bundles.items()}
    models["lgbm"]["best_iteration"] = best_iteration
    selected = min(KINDS, key=lambda k: models[k]["val"]["log_loss"])  # 동률이면 lr(KINDS 순서)
    bundle = bundles[selected]
    if meta.get("generated_at"):
        bundle["trained_at"] = meta["generated_at"]

    # 유의성: 선택 모델 vs test에서 가장 잘한 베이스라인, 같은 경기들 위의 McNemar 검정
    y_test = test["y"].to_numpy()
    p_test = predict_proba(bundle, test)
    base_test = baselines(test)
    vs = max(base_test, key=base_test.get)  # 동률이면 앞의 것
    model_ok, base_ok = _correct(p_test, y_test), _baseline_preds(test)[vs] == y_test

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
        "baselines": {"val": baselines(val), "test": base_test},
        "significance": {"vs": vs, "mcnemar_p": mcnemar_p(model_ok, base_ok),
                         "model_correct": int(model_ok.sum()), "baseline_correct": int(base_ok.sum())},
        "calibration_bins": calibration_table(p_test, y_test),
        "feature_importance": feature_importance(bundle),
        "matchup_feature_ablation": None,  # 3단계(맞대결 피처) 자리
        "cluster_quality": None,           # 3단계(선수 유형 군집) 자리
    }
    return report, bundle


def train_live(df: pd.DataFrame, *, kind: str, calibration: str, n_estimators: int, meta: dict) -> dict:
    """사이트용 라이브 모델: 있는 시즌 전부로 학습 (알고리즘·캘리브레이션 방법·트리 수는 보고서에서 고른 값).
    전체를 학습에 쓰면 캘리브레이터를 맞출 '안 본 데이터'가 없으므로, 시즌 leave-one-out 예측(oof_predictions)으로 맞춘다."""
    seasons = sorted(int(s) for s in df["season"].unique())
    bundle = fit_model(df, kind=kind, n_estimators=n_estimators, version=MODEL_VERSION, seasons=seasons)
    if calibration != "none":
        oof = oof_predictions(df, kind=kind, n_estimators=n_estimators)
        bundle.update(calibration=calibration, calibrator=fit_calibrator(calibration, oof, df["y"].to_numpy()))
    if meta.get("generated_at"):
        bundle["trained_at"] = meta["generated_at"]
    return bundle


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_manifest(path: Path, *, features_path: Path, bundles: dict[str, Path], meta: dict) -> None:
    """models/manifest.json: 어떤 피처 파일(SHA256)로 어떤 모델 파일(SHA256·버전)을 만들었는지 기록."""
    models = {name: {"path": Path(p).as_posix(), "sha256": _sha256(p), "version": load_bundle(p).get("version")}
              for name, p in bundles.items()}
    _write_json(path, {"generated_at": meta.get("generated_at"), "commit_sha": meta.get("commit_sha"),
                       "features_sha256": _sha256(features_path), "features_path": Path(features_path).as_posix(),
                       "models": models})


# ---------- CLI ----------

REPORT_JSON = Path("data/public/model_report.json")
REPORT_PKL = Path(f"models/{REPORT_VERSION}.pkl")
LIVE_PKL = Path("models/win_model.pkl")
MANIFEST = Path("models/manifest.json")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="승패 모델 학습: report(2015~2024 학습/2025 검증/2026 평가) 또는 live(전 시즌)")
    ap.add_argument("command", choices=["report", "live"])
    ap.add_argument("--features", default="data/processed/features.parquet", help="피처 parquet 경로")
    args = ap.parse_args(argv)
    features_path = Path(args.features)
    meta = {"generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "commit_sha": os.environ.get("GITHUB_SHA"), "run_url": os.environ.get("RUN_URL"),
            "features_sha256": _sha256(features_path)}
    df = load_features(features_path)
    t0 = time.time()
    if args.command == "report":
        report, bundle = train_report(df, meta=meta)
        _write_json(REPORT_JSON, report)
        save_bundle(bundle, REPORT_PKL)
        sel = report["models"][report["selected"]]
        print(f"selected: {report['selected']} (calibration={sel['calibration']}, "
              f"best_iteration={report['models']['lgbm']['best_iteration']})")
        print(f"test {report['test_season']}: acc={sel['test']['accuracy']:.4f} "
              f"log_loss={sel['test']['log_loss']:.4f} brier={sel['test']['brier']:.4f}")
        print(f"vs {report['significance']['vs']}: McNemar p={report['significance']['mcnemar_p']:.4f}")
    else:
        if not REPORT_JSON.exists():
            raise SystemExit(f"{REPORT_JSON} not found — run `python -m kbo_predict.train_win report` first")
        report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        if report.get("features_sha256") != meta["features_sha256"]:
            raise SystemExit("features parquet differs from the one model_report.json was built on — rerun `report`")
        kind = report["selected"]
        bundle = train_live(df, kind=kind, calibration=report["models"][kind]["calibration"],
                            n_estimators=report["models"]["lgbm"]["best_iteration"], meta=meta)
        save_bundle(bundle, LIVE_PKL)
        print(f"live {bundle['version']}: {kind} calibration={bundle['calibration']} "
              f"seasons={bundle['seasons'][0]}~{bundle['seasons'][-1]} n={bundle['n_games']}")
    print(f"done in {time.time() - t0:.1f}s")
    write_manifest(MANIFEST, features_path=features_path,
                   bundles={name: p for name, p in (("report", REPORT_PKL), ("live", LIVE_PKL)) if p.exists()},
                   meta=meta)


if __name__ == "__main__":
    main()
