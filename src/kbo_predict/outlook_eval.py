"""두 모델 합치기 시험: 선발을 모를 때(시리즈 전망·가을야구 확률의 미래 경기) 어떤 모델을 쓸 것인가.

배경
- 사이트는 확률을 두 모델로 낸다. 경기 예측 = 승패 모델 v0.3(L1 + Elo, 선발 포함 27개), 시리즈 전망·가을야구 확률의
  미래 경기 = 팀 모델 team-2026(L2 C=1, 팀 피처 19개, 선발·Elo 없음). 미래 경기는 선발을 모르니 선발 없는 모델을 따로 둔 것이다.
- 2026 한국시리즈 전 두 모델이 다른 팀을 골랐다(경기 예측 KT, 시리즈 전망 삼성 51~52%). 한 화면에서 두 숫자가 엇갈리면
  읽는 사람이 헷갈린다. 하나로 합칠 수 있는지, 합친다면 무엇으로 합치는 게 가장 나은지 잰다.

후보 (모두 "선발 모름" 확률 — 선발 피처는 starter_known = 0, 나머지 선발 피처는 결측 → 학습 중앙값)
- team        : 지금 전망 모델. L2 C=1, 팀 피처 19개.
- team_elo    : team + Elo 차이 (L2 C=1, 20개).
- team_l1_elo : L1 C=0.03 + Elo, 팀 피처 19개 + Elo (= v0.3 설정에서 선발 피처만 뺀 모델을 따로 학습).
- win_masked  : v0.3 그 자체(선발 포함으로 학습)에 선발을 '모름'으로 넣은 확률 → 경기 예측과 전망이 **한 모델**이 된다.
- avg         : win_masked와 team의 확률 평균.

채점 (backtest.py와 같은 walk-forward: 시즌마다 그 앞 시즌들로만 학습)
- 경기: 2018~2026 정규시즌 전 경기(선발을 가린 채로) + 가을야구 경기(정규시즌 끝 상태, 선발 모름). 적중률·log loss.
- 시리즈: 가을야구 시리즈 37개의 시작 전 우세 팀(두 구장 평균, postseason_eval과 같은 방식)이 실제 승자인가.
- 엇갈림: 선발을 아는 경기 예측(v0.3)과 고른 팀이 다른 경기 비율 — 한 화면 안의 일관성.

고르는 규칙 (계산 전에 정함 — 2026-11-09)
1. 개발 시즌(2018~2025, 정규시즌 + 가을야구) 경기 log loss가 가장 낮은 후보 = best.
2. win_masked의 log loss가 best보다 나쁘지 않거나, 나빠도 경기별 log loss 대응 t 검정 p ≥ 0.05(우연과 구분 안 됨)이면
   **win_masked를 고른다** — 한 모델로 합쳐 엇갈림이 없어지고 관리할 모델이 하나 준다(단순함·일관성을 같은 성적이면 우선).
3. 아니면 best를 고른다. 2026 시즌은 고른 뒤 채점만 한다.

실행: python -m kbo_predict.outlook_eval [--out data/public/outlook_model_report.json]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import KST, raw_store
from .backtest import _ll, paired_t_p
from .features import FEATURE_NAMES, MODEL_FEATURES, STARTER_FEATURES, TEAM_FEATURES, game_features, load_features, starter_ids
from .postseason_eval import postseason_games
from .rewind import state_before
from .predict import raw_prob
from .simulate import load_postseason, outlook_for
from .train_win import TEAM_LR, WIN_LR, _correct, fit_model, mcnemar_p, predict_proba

SEASONS = list(range(2018, 2027))
DEV_SEASONS = list(range(2018, 2026))
TEST_SEASON = 2026
ALPHA = 0.05
UNIFIED = "win_masked"
CANDIDATES = {
    "team": {"label": "예전 전망 모델 (팀 기록만, L2)", "features": TEAM_FEATURES, "lr": TEAM_LR},
    "team_elo": {"label": "팀 기록 + Elo (L2)", "features": TEAM_FEATURES + ["elo_diff"], "lr": TEAM_LR},
    "team_l1_elo": {"label": "팀 기록 + Elo (L1, v0.3에서 선발만 뺌)", "features": TEAM_FEATURES + ["elo_diff"], "lr": WIN_LR},
    "win_masked": {"label": "v0.3 하나로 합치기 (선발 모름으로 넣음)", "features": MODEL_FEATURES, "lr": WIN_LR},
    "avg": {"label": "v0.3(선발 모름)과 팀 모델의 평균", "features": None, "lr": None},
}
NAMES = list(CANDIDATES)


def mask_starters(X: pd.DataFrame) -> pd.DataFrame:
    """선발을 모르는 상태로: starter_known = 0, 나머지 선발 피처는 결측(→ 학습 중앙값). 라이브 미발표 경기와 같은 입력."""
    X = X.copy()
    X["starter_known"] = 0
    for c in STARTER_FEATURES:
        if c != "starter_known":
            X[c] = np.nan
    return X


def _models(train: pd.DataFrame) -> dict:
    seasons = sorted(train["season"].unique().tolist())
    return {n: fit_model(train, kind="lr", lr_params=c["lr"], features=c["features"], version=f"oe-{n}", seasons=seasons)
            for n, c in CANDIDATES.items() if c["features"] is not None}


def _probs(models: dict, X: pd.DataFrame) -> dict[str, np.ndarray]:
    Xm = mask_starters(X)
    out = {n: predict_proba(b, Xm[b["features"]]) for n, b in models.items()}
    out["avg"] = (out["win_masked"] + out["team"]) / 2
    return out


def _row_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=MODEL_FEATURES)


def season_predictions(season: int, df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """한 시즌의 경기별 후보 확률(정규시즌 + 가을야구)과 가을야구 시리즈 시작 전 확률."""
    train, test = df[df["season"] < season], df[df["season"] == season]
    models = _models(train)
    win_full = models["win_masked"]  # 같은 번들로 선발을 아는 경기 예측(일관성 비교용)
    reg = test[["season", "game_id", "y"]].copy()
    reg["part"] = "regular"
    for n, p in _probs(models, test).items():
        reg[n] = p
    reg["game_model"] = predict_proba(win_full, test[MODEL_FEATURES])

    games = raw_store.load_games(season)
    boxes = raw_store.load_boxscores(season)
    post = postseason_games(season, games)
    series = []
    if not post:
        return reg, series
    frozen = state_before(season, post[0]["date"], games=games, boxscores=boxes)
    feats = [game_features(g, frozen, None) for g in post]
    known = [game_features(g, frozen, starter_ids(boxes.get(g["game_id"]))) for g in post]
    ps = pd.DataFrame({"season": season, "game_id": [g["game_id"] for g in post],
                       "y": [int(g["home_score"] > g["away_score"]) for g in post], "part": "postseason"})
    for n, p in _probs(models, _row_frame(feats)).items():
        ps[n] = p
    ps["game_model"] = predict_proba(win_full, _row_frame(known)[MODEL_FEATURES])

    # 시리즈: 같은 두 팀의 맞대결 묶음, 시작 전 우세 팀(두 구장 평균, 선발 모름)
    seen = []
    for g in post:
        pair = frozenset((g["home_code"], g["away_code"]))
        if pair in seen:
            continue
        seen.append(pair)
        gs = [x for x in post if frozenset((x["home_code"], x["away_code"])) == pair]
        a, b = sorted(pair)
        wins = {a: 0, b: 0}
        for x in gs:
            wins[x["home_code"] if x["home_score"] > x["away_score"] else x["away_code"]] += 1
        both = [{"home_code": a, "away_code": b, "date": gs[0]["date"], "season": season, "game_id": 0},
                {"home_code": b, "away_code": a, "date": gs[0]["date"], "season": season, "game_id": 0}]
        pr = _probs(models, _row_frame([game_features(x, frozen, None) for x in both]))
        p_a = {n: float((v[0] + 1 - v[1]) / 2) for n, v in pr.items()}  # P(a가 이김), 두 구장 평균
        series.append({"season": season, "teams": [a, b], "winner": a if wins[a] > wins[b] else b, "p_a": p_a})
    return pd.concat([reg, ps], ignore_index=True), series


KS_DATES = ["2026-11-03", "2026-11-04", "2026-11-06", "2026-11-07", "2026-11-08"]


def ks_2026(df: pd.DataFrame) -> list[dict]:
    """2026 한국시리즈 날마다 사이트 시리즈 전망(1만 번 시뮬레이션)이 합친 모델과 예전 팀 모델에서 각각 어떻게 나왔을지.
    모델은 2015~2025로 학습(이 시험의 2026 walk-forward와 같은 모델), 오늘 경기는 둘 다 예고 선발 포함 승패 모델 확률."""
    train = df[df["season"] < TEST_SEASON]
    models = _models(train)
    games = raw_store.load_games(TEST_SEASON)
    boxes = raw_store.load_boxscores(TEST_SEASON)
    ps = load_postseason(TEST_SEASON)
    out = []
    for on in KS_DATES:
        st = state_before(TEST_SEASON, on, games=games, boxscores=boxes)
        tp = {g["game_id"]: raw_prob(models[UNIFIED], g, st, starter_ids(boxes.get(g["game_id"])))
              for g in games if g["date"] == on and g["status"] == "FINAL"}
        o = {n: outlook_for(TEST_SEASON, on, games, state=st, team_bundle=models[n], ps_config=ps, today_probs=tp)
             for n in (UNIFIED, "team")}
        out.append({"date": on, "teams": o[UNIFIED]["teams"], "wins": o[UNIFIED]["wins"],
                    "unified": o[UNIFIED]["win_prob"], "old_team": o["team"]["win_prob"]})
    return out


def _summ(q: pd.DataFrame) -> dict:
    y = q["y"].to_numpy()
    out = {"n": int(len(q))}
    for n in NAMES:
        p = q[n].to_numpy()
        out[n] = {"accuracy": float(_correct(p, y).mean()), "log_loss": float(_ll(p, y).mean()),
                  "disagree_with_game_model": float(((p >= 0.5) != (q["game_model"].to_numpy() >= 0.5)).mean())}
    out["game_model"] = {"accuracy": float(_correct(q["game_model"].to_numpy(), y).mean())}
    return out


def _vs(q: pd.DataFrame, a: str, b: str) -> dict:
    y = q["y"].to_numpy()
    la, lb = _ll(q[a].to_numpy(), y), _ll(q[b].to_numpy(), y)
    return {"logloss_gain": float(lb.mean() - la.mean()), "logloss_p": paired_t_p(la, lb),
            "mcnemar_p": mcnemar_p(_correct(q[a].to_numpy(), y), _correct(q[b].to_numpy(), y))}


def _r(x, nd=4):
    if isinstance(x, float):
        return round(x, nd)
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, list):
        return [_r(v, nd) for v in x]
    return x


def run(df: pd.DataFrame, *, log=print) -> dict:
    t0 = time.time()
    parts, series = [], []
    for s in SEASONS:
        q, sr = season_predictions(s, df)
        parts.append(q)
        series += sr
        log(f"[outlook_eval] {s}: 경기 {len(q):,} (가을 {int((q['part'] == 'postseason').sum())}), 시리즈 {len(sr)}")
    q = pd.concat(parts, ignore_index=True)
    dev, test = q[q["season"].isin(DEV_SEASONS)], q[q["season"] == TEST_SEASON]
    dev_ll = {n: float(_ll(dev[n].to_numpy(), dev["y"].to_numpy()).mean()) for n in NAMES}
    best = min(dev_ll, key=dev_ll.get)
    vs_best = _vs(dev, UNIFIED, best) if best != UNIFIED else {"logloss_gain": 0.0, "logloss_p": 1.0, "mcnemar_p": 1.0}
    chosen = UNIFIED if (best == UNIFIED or vs_best["logloss_p"] >= ALPHA) else best
    ser_rows = []
    for s in series:
        a, b = s["teams"]
        picks = {n: (a if s["p_a"][n] >= 0.5 else b) for n in NAMES}
        ser_rows.append({**s, "picks": picks, "hit": {n: int(picks[n] == s["winner"]) for n in NAMES}})
    ser_sum = {}
    for lab, keep in (("dev", DEV_SEASONS), ("test", [TEST_SEASON]), ("all", SEASONS)):
        part = [r for r in ser_rows if r["season"] in keep]
        ser_sum[lab] = {"n": len(part), **{n: sum(r["hit"][n] for r in part) for n in NAMES}}
    scopes = {
        "dev": dev, "dev_regular": dev[dev["part"] == "regular"], "dev_postseason": dev[dev["part"] == "postseason"],
        "test": test, "test_regular": test[test["part"] == "regular"], "test_postseason": test[test["part"] == "postseason"],
    }
    return _r({
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "seasons": SEASONS,
        "protocol": {"dev_seasons": DEV_SEASONS, "test_season": TEST_SEASON, "alpha": ALPHA, "unified": UNIFIED,
                     "rule": "개발 시즌 log loss 최저(best). win_masked가 best이거나 best와의 차이가 p ≥ 0.05면 win_masked(한 모델), 아니면 best",
                     "rule_declared": "2026-11-09 (계산 전)"},
        "candidates": {n: c["label"] for n, c in CANDIDATES.items()},
        "pooled": {k: _summ(v) for k, v in scopes.items()},
        "by_season": {str(s): _summ(g) for s, g in q.groupby("season")},
        "tests_dev": {n: _vs(dev, n, "team") for n in NAMES if n != "team"},
        "best_dev": best,
        "unified_vs_best": vs_best,
        "chosen": chosen,
        "series": ser_rows,
        "series_summary": ser_sum,
        "ks_2026": ks_2026(df),
        "elapsed_sec": round(time.time() - t0, 1),
    })


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="두 모델 합치기 시험 (선발 모를 때 쓸 모델 고르기)")
    ap.add_argument("--features", default="data/processed/features.parquet")
    ap.add_argument("--out", default="data/public/outlook_model_report.json")
    args = ap.parse_args(argv)
    rep = run(load_features(args.features))
    Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    d = rep["pooled"]["dev"]
    print("[outlook_eval] 2018~2025 " + ", ".join(f"{n} {d[n]['accuracy']:.1%}/{d[n]['log_loss']:.4f}" for n in NAMES)
          + f" → best {rep['best_dev']}, 고른 것 {rep['chosen']} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
