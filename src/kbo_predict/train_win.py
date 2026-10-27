"""로지스틱 회귀 승패 모델 학습 / 평가 / 저장."""
import argparse
import json
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler

from . import KST, MODEL_VERSION
from .features import FEATURE_NAMES, build_training_frame
from .raw_store import load_games

MODELS_DIR = Path("models")


def fit_model(df: pd.DataFrame) -> dict:
    scaler = StandardScaler()
    X = scaler.fit_transform(df[FEATURE_NAMES])
    model = LogisticRegression(random_state=42, max_iter=1000)
    model.fit(X, df["y"])
    return {
        "model": model,
        "scaler": scaler,
        "features": FEATURE_NAMES,
        "version": MODEL_VERSION,
        "trained_at": datetime.now(KST).isoformat(timespec="seconds"),
        "n_games": int(len(df)),
    }


def evaluate(bundle: dict, df_test: pd.DataFrame) -> dict:
    X = bundle["scaler"].transform(df_test[bundle["features"]])
    y = df_test["y"].to_numpy()
    proba = bundle["model"].predict_proba(X)[:, 1]
    pred = (proba >= 0.5).astype(int)
    better = (df_test["win_pct_diff"].to_numpy() >= 0).astype(int)
    return {
        "n": int(len(df_test)),
        "accuracy": float(accuracy_score(y, pred)),
        "log_loss": float(log_loss(y, proba, labels=[0, 1])),
        "brier": float(brier_score_loss(y, proba)),
        "baseline_home_always": float(accuracy_score(y, [1] * len(y))),
        "baseline_better_win_pct": float(accuracy_score(y, better)),
    }


def save_bundle(bundle: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def load_bundle(path: Path) -> dict:
    return joblib.load(Path(path))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--split-date", required=True)
    args = ap.parse_args(argv)

    df = build_training_frame(load_games(args.season), season=args.season)
    train = df[df["date"] < args.split_date]
    test = df[df["date"] >= args.split_date]
    split_bundle = fit_model(train)
    metrics = {
        "model_version": MODEL_VERSION,
        "trained_at": split_bundle["trained_at"],
        "split_date": args.split_date,
        "train_n": int(len(train)),
        "test_n": int(len(test)),
        **evaluate(split_bundle, test),
        "coefficients": {
            **dict(zip(FEATURE_NAMES, map(float, split_bundle["model"].coef_[0]))),
            "intercept": float(split_bundle["model"].intercept_[0]),
        },
    }
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    (MODELS_DIR / f"metrics_{MODEL_VERSION}.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_bundle(fit_model(df), MODELS_DIR / "win_model.pkl")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
