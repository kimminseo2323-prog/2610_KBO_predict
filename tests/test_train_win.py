from kbo_predict.features import FEATURE_NAMES
from kbo_predict.train_win import evaluate, fit_model, load_bundle, save_bundle


def test_fit_and_evaluate_beats_home_always(synthetic_df):
    bundle = fit_model(synthetic_df.iloc[:300])
    m = evaluate(bundle, synthetic_df.iloc[300:])
    assert bundle["version"] == "v0.1" and set(m) >= {"accuracy", "log_loss", "brier", "baseline_home_always"}
    assert m["accuracy"] > m["baseline_home_always"]


def test_save_and_load_roundtrip(tmp_path, synthetic_df):
    bundle = fit_model(synthetic_df)
    p = tmp_path / "m.pkl"
    save_bundle(bundle, p)
    loaded = load_bundle(p)
    x = synthetic_df[FEATURE_NAMES].iloc[:5]
    assert loaded["model"].predict_proba(loaded["scaler"].transform(x)).tolist() == bundle["model"].predict_proba(bundle["scaler"].transform(x)).tolist()
