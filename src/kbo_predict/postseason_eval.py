"""가을야구 성적: 포스트시즌 경기만 따로 모아, 정규시즌용으로 만든 모델이 가을에도 통하는지 잰다 (2018~2026).

왜 따로 보나
- 2026 가을야구에서 승패 모델 v0.3은 14경기 중 5경기만 맞혔고(한국시리즈 2~5차전 4연속 실패),
  같은 날 사이트의 시리즈 전망(팀 모델)은 한국시리즈 시작 전 삼성 우승을 51~52%로 더 높게 봤다 — 두 계산이 엇갈렸다.
- 학습 데이터는 정규시즌 경기뿐이고, 리그 상태(팀 성적·최근 10경기·Elo·투수 기록)도 정규시즌 FINAL만 쌓는다.
  그래서 가을야구에서는 정규시즌 마지막 날의 전력이 그대로 쓰이고, 가을야구 경기 결과는 반영되지 않는다.

비교하는 것 (모두 "그 시즌보다 앞선 시즌들로만 학습" — backtest.py와 같은 walk-forward)
- frozen  : 지금 방식. v0.3 설정(L1 C=0.03 + Elo, 피처 27개), 상태는 정규시즌 끝에 고정, 실제 선발 기록 사용.
- in_state: 같은 모델, 가을야구 경기 결과를 그날그날 상태에 넣어 가며 예측(팀 성적·최근 10경기·Elo·투수 기록이 가을 경기로도 바뀐다).
            단 휴식일 차이(rest_diff)는 frozen과 같은 값을 쓴다: 가을에 상태를 갱신하면 기다린 팀(한국시리즈 직행 팀)의 휴식일이
            20일을 넘어, 정규시즌 학습 범위(차이 대부분 −2~+2일)를 크게 벗어난 값이 확률을 끌고 간다(예비 계산에서 한국시리즈 직행 팀
            우세가 79%까지 커졌다). 이건 가을 흐름이 아니라 학습 범위 밖 외삽이라 뺀다.
- team    : 시리즈 전망에 쓰는 팀 모델 설정(L2 C=1, 팀 피처 19개, 선발·Elo 없음), 상태는 정규시즌 끝에 고정.
- 규칙    : 항상 홈팀, 정규시즌 승률이 높은 팀.
경기 단위(적중률·log loss)와 시리즈 단위(시리즈 시작 전 더 높게 본 팀이 실제로 이겼나)로 잰다.
시리즈 단위의 확률은 선발을 모르는 상태로, 두 팀 홈 경기 확률의 평균(어느 구장이든 같은 비중)으로 정한다.

채택 규칙 (2026-11-09에 정함 — 정직하게 적는 것: 2026 가을야구 결과와 in_state의 예비 계산을 본 뒤에 정했다)
- in_state를 라이브 가을야구 예측에 쓰려면 개발 시즌 2018~2025 포스트시즌의 log loss가 frozen보다 낮고,
  경기별 log loss 차이의 대응표본 t 검정 p < 0.05여야 한다. 아니면 지금 방식(frozen)을 유지하고 결과만 공개한다.
- 포스트시즌은 한 해 12~16경기라 8시즌을 합쳐도 약 115경기다. 작은 차이는 우연과 구분되지 않을 수 있다.

실행: python -m kbo_predict.postseason_eval [--out data/public/postseason_report.json]
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from datetime import date, datetime
from itertools import groupby
from pathlib import Path

import numpy as np
import pandas as pd

from . import KST, raw_store
from .backtest import _ll, paired_t_p
from .features import TEAM_FEATURES, game_features, load_features, starter_ids
from .predict import raw_prob
from .rewind import state_before
from .seasons import is_regular
from .simulate import load_postseason
from .train_win import TEAM_LR, WIN_LR, _correct, fit_model, mcnemar_p, predict_proba
from .teams import TEAMS

CODES = {t["code"] for t in TEAMS.values()}  # 10구단 코드 (올스타전 등 다른 팀 경기를 빼려고)

SEASONS = list(range(2018, 2027))
DEV_SEASONS = list(range(2018, 2026))
TEST_SEASON = 2026
ALPHA = 0.05
MODELS = ("frozen", "in_state", "team")
CANDIDATES = {
    "frozen": "지금 방식 (v0.3, 정규시즌 끝 전력으로 고정)",
    "in_state": "가을야구 결과 반영 (v0.3, 가을 경기로 전력 갱신)",
    "team": "예전 시리즈 전망 모델 (팀 기록만, 선발·Elo 없음)",
}
RULES = {"home": "항상 홈팀", "better_record": "정규시즌 승률이 높은 팀"}


def postseason_games(season: int, games: list[dict] | None = None) -> list[dict]:
    """정규시즌 마지막 경기일 뒤의 FINAL 경기(무승부·점수 없음 제외), (날짜, game_id) 순."""
    games = raw_store.load_games(season) if games is None else games
    reg = [g["date"] for g in games
           if g["status"] == "FINAL" and is_regular(season, date.fromisoformat(g["date"]), g["game_id"])]
    if not reg:
        return []
    last = max(reg)
    out = [g for g in games if g["status"] == "FINAL" and g["date"] > last
           and g["home_code"] in CODES and g["away_code"] in CODES
           and g.get("home_score") is not None and g.get("away_score") is not None and g["home_score"] != g["away_score"]]
    return sorted(out, key=lambda g: (g["date"], g["game_id"]))


def regular_win_pct(season: int, games: list[dict]) -> dict[str, float]:
    """정규시즌 승률 (무승부 제외)."""
    rec: dict[str, list[int]] = {}
    for g in games:
        if g["status"] != "FINAL" or not is_regular(season, date.fromisoformat(g["date"]), g["game_id"]):
            continue
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs is None or as_ is None or hs == as_:
            continue
        for t, won in ((g["home_code"], hs > as_), (g["away_code"], as_ > hs)):
            r = rec.setdefault(t, [0, 0])
            r[0] += int(won)
            r[1] += 1
    return {t: w / n for t, (w, n) in rec.items()}


def _team_p(bundle: dict, g: dict, state) -> float:
    f = game_features(g, state, None)
    X = pd.DataFrame([{k: f[k] for k in bundle["features"]}], columns=bundle["features"])
    return float(predict_proba(bundle, X)[0])


def _in_state_p(bundle: dict, g: dict, live, frozen, starters) -> float:
    """in_state 확률: 가을 경기까지 쌓은 상태(live)의 피처, 단 휴식일 차이는 정규시즌 끝 상태(frozen) 값."""
    f = game_features(g, live, starters)
    f["rest_diff"] = game_features(g, frozen, starters)["rest_diff"]
    return raw_prob(bundle, g, live, starters, features=f)


def _neutral(p_fn, a: str, b: str, on: str, season: int) -> float:
    """선발 모름, 두 구장 평균: P(a가 b를 이김) = (P(a 홈 승) + 1 − P(b 홈 승)) / 2."""
    g_a = {"home_code": a, "away_code": b, "date": on, "season": season, "game_id": 0}
    g_b = {"home_code": b, "away_code": a, "date": on, "season": season, "game_id": 0}
    return (p_fn(g_a) + 1.0 - p_fn(g_b)) / 2.0


def season_rows(season: int, df: pd.DataFrame, *, series_names: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """한 시즌 포스트시즌의 (경기 행, 시리즈 행). 모델은 season보다 앞선 시즌들로 학습한다."""
    games = raw_store.load_games(season)
    boxes = raw_store.load_boxscores(season)
    post = postseason_games(season, games)
    if not post:
        return [], []
    train = df[df["season"] < season]
    win = fit_model(train, kind="lr", lr_params=WIN_LR, version="ps-win", seasons=sorted(train["season"].unique().tolist()))
    team = fit_model(train, kind="lr", lr_params=TEAM_LR, features=TEAM_FEATURES, version="ps-team",
                     seasons=sorted(train["season"].unique().tolist()))
    frozen = state_before(season, post[0]["date"], games=games, boxscores=boxes)  # 정규시즌 FINAL만 → 가을 내내 같은 상태
    live = copy.deepcopy(frozen)
    wpct = regular_win_pct(season, games)

    # 시리즈 = 같은 두 팀의 연속 맞대결 (한 가을에 같은 두 팀은 한 번만 만난다)
    order: list[frozenset] = []
    for g in post:
        pair = frozenset((g["home_code"], g["away_code"]))
        if pair not in order:
            order.append(pair)
    series = []
    for i, pair in enumerate(order):
        gs = [g for g in post if frozenset((g["home_code"], g["away_code"])) == pair]
        a, b = sorted(pair, key=lambda t: (-wpct.get(t, 0), t))  # a = 정규시즌 승률이 높은 팀 (같으면 코드 순 — 실행마다 같게)
        wins = {a: 0, b: 0}
        for g in gs:
            wins[g["home_code"] if g["home_score"] > g["away_score"] else g["away_code"]] += 1
        name = series_names[i] if series_names and i < len(series_names) else f"{i + 1}번째 시리즈"
        series.append({"season": season, "name": name, "teams": [a, b], "first_date": gs[0]["date"],
                       "wins": [wins[a], wins[b]], "winner": a if wins[a] > wins[b] else b, "_pair": pair})

    rows = []
    for d, grp in groupby(post, key=lambda g: g["date"]):
        grp = list(grp)
        for s in series:  # 시리즈 첫날: 그 시점 상태로 '시리즈 전 우세 팀'을 정한다 (선발 모름)
            if s["first_date"] == d:
                a, b = s["teams"]
                s["p_first"] = {
                    "frozen": _neutral(lambda g: raw_prob(win, g, frozen, None), a, b, d, season),
                    "in_state": _neutral(lambda g: _in_state_p(win, g, live, frozen, None), a, b, d, season),
                    "team": _neutral(lambda g: _team_p(team, g, frozen), a, b, d, season),
                }
        for g in grp:
            sp = starter_ids(boxes.get(g["game_id"]))
            name = next(s["name"] for s in series if s["_pair"] == frozenset((g["home_code"], g["away_code"])))
            rows.append({
                "season": season, "date": d, "game_id": g["game_id"], "series": name,
                "home": g["home_code"], "away": g["away_code"],
                "score": [g["away_score"], g["home_score"]], "y": int(g["home_score"] > g["away_score"]),
                "frozen": raw_prob(win, g, frozen, sp), "in_state": _in_state_p(win, g, live, frozen, sp),
                "team": _team_p(team, g, frozen),
                "rule_home": 1, "rule_better_record": int(wpct.get(g["home_code"], 0) >= wpct.get(g["away_code"], 0)),
            })
        for g in grp:  # 그날 경기를 다 예측한 뒤에 in_state 상태에 넣는다 (그날 결과가 그날 예측에 새지 않게)
            live.update(g, boxes.get(g["game_id"]))
    for s in series:
        s.pop("_pair")
    return rows, series


def _summ(q: pd.DataFrame) -> dict:
    y = q["y"].to_numpy()
    out = {"n": int(len(q)), "home_win_rate": float(y.mean()) if len(q) else None}
    for m in MODELS:
        p = q[m].to_numpy()
        out[m] = {"accuracy": float(_correct(p, y).mean()), "log_loss": float(_ll(p, y).mean())}
    for r in RULES:
        out[f"rule_{r}"] = {"accuracy": float((q[f"rule_{r}"].to_numpy() == y).mean())}
    return out


def _tests(q: pd.DataFrame) -> dict:
    y = q["y"].to_numpy()
    c = {m: _correct(q[m].to_numpy(), y) for m in MODELS}
    ll = {m: _ll(q[m].to_numpy(), y) for m in MODELS}
    return {
        "in_state_vs_frozen": {"logloss_gain": float(ll["frozen"].mean() - ll["in_state"].mean()),
                               "logloss_p": paired_t_p(ll["in_state"], ll["frozen"]),
                               "mcnemar_p": mcnemar_p(c["in_state"], c["frozen"])},
        "team_vs_frozen": {"logloss_gain": float(ll["frozen"].mean() - ll["team"].mean()),
                           "logloss_p": paired_t_p(ll["team"], ll["frozen"]),
                           "mcnemar_p": mcnemar_p(c["team"], c["frozen"])},
        "frozen_vs_rule_better_record": {"mcnemar_p": mcnemar_p(c["frozen"], q["rule_better_record"].to_numpy() == y)},
    }


def _r(x, nd=4):
    """JSON용 반올림 (dict·list 안까지)."""
    if isinstance(x, float):
        return round(x, nd)
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, list):
        return [_r(v, nd) for v in x]
    return x


def live_record(history_path) -> dict:
    """사이트에 실제로 공개한 2026 가을야구 예측(history.csv)의 적중 — 이 시험의 재계산과 별개인 '그때 그 기록'."""
    h = pd.read_csv(history_path, dtype={"game_id": str})
    h = h[(h["status"] == "FINAL") & h["correct"].notna()]
    games = raw_store.load_games(TEST_SEASON)
    post_ids = {str(g["game_id"]) for g in postseason_games(TEST_SEASON, games)}
    q = h[h["game_id"].isin(post_ids)]
    return {"n": int(len(q)), "correct": int(q["correct"].sum()), "first_date": q["date"].min() if len(q) else None}


def run(df: pd.DataFrame, *, history_path="data/public/history.csv", log=print) -> dict:
    t0 = time.time()
    rows, series = [], []
    for s in SEASONS:
        names = None
        try:
            names = [x["name"] for x in load_postseason(s)]
        except Exception:
            pass
        r, sr = season_rows(s, df, series_names=names)
        rows += r
        series += sr
        log(f"[postseason] {s}: 포스트시즌 {len(r)}경기, 시리즈 {len(sr)}개")
    q = pd.DataFrame(rows)
    dev, test = q[q["season"].isin(DEV_SEASONS)], q[q["season"] == TEST_SEASON]
    tests_dev = _tests(dev)
    t = tests_dev["in_state_vs_frozen"]
    adopt = t["logloss_gain"] > 0 and t["logloss_p"] < ALPHA
    for s in series:
        s["picks"] = {m: (s["teams"][0] if s["p_first"][m] >= 0.5 else s["teams"][1]) for m in MODELS}
        s["picks"]["rule_better_record"] = s["teams"][0]
    ser = pd.DataFrame(series)
    series_summary = {}
    for lab, part in (("dev", ser[ser["season"].isin(DEV_SEASONS)]), ("test", ser[ser["season"] == TEST_SEASON]), ("all", ser)):
        series_summary[lab] = {"n": int(len(part)), **{
            k: int(sum(p[k] == w for p, w in zip(part["picks"], part["winner"])))
            for k in (*MODELS, "rule_better_record")}}
    return _r({
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "seasons": SEASONS,
        "protocol": {"dev_seasons": DEV_SEASONS, "test_season": TEST_SEASON, "alpha": ALPHA,
                     "adopt_rule": "in_state를 쓰려면 2018~2025 포스트시즌 log loss가 frozen보다 낮고 대응표본 t 검정 p < 0.05",
                     "rule_declared": "2026-11-09 (2026 가을야구 결과와 예비 계산을 본 뒤)"},
        "candidates": CANDIDATES,
        "rules": RULES,
        "by_season": {str(s): _summ(g) for s, g in q.groupby("season")},
        "pooled": {"dev": {**_summ(dev), "tests": tests_dev}, "test": {**_summ(test), "tests": _tests(test)},
                   "all": {**_summ(q), "tests": _tests(q)}},
        "decision": {"adopt_in_state": bool(adopt),
                     "reason": ("개발 시즌 log loss가 낮고 차이가 우연으로 보기 어렵다" if adopt else
                                "개발 시즌 차이가 우연과 구분되지 않는다(p ≥ 0.05) — 지금 방식을 유지" if t["logloss_gain"] > 0 else
                                "개발 시즌 log loss가 낮아지지 않았다 — 지금 방식을 유지")},
        "games_2026": test.drop(columns=["season"]).to_dict("records"),
        "series": [{k: v for k, v in s.items()} for s in series],
        "series_summary": series_summary,
        "live_2026": live_record(history_path),
        "elapsed_sec": round(time.time() - t0, 1),
    })


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="가을야구 성적 (포스트시즌 walk-forward)")
    ap.add_argument("--features", default="data/processed/features.parquet")
    ap.add_argument("--out", default="data/public/postseason_report.json")
    args = ap.parse_args(argv)
    rep = run(load_features(args.features))
    Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    d = rep["pooled"]["dev"]
    print(f"[postseason] 2018~2025 {d['n']}경기: frozen {d['frozen']['accuracy']:.1%} / in_state {d['in_state']['accuracy']:.1%}"
          f" / team {d['team']['accuracy']:.1%} / 채택 {rep['decision']['adopt_in_state']} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
