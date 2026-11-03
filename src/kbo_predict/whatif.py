"""선발 바꿔 보기(what-if): 사이트에서 두 팀 선발을 골라 보면 승리 확률을 브라우저에서 다시 계산할 수 있게 데이터를 내보낸다.

왜 이렇게 하나
- 사이트는 GitHub Pages(정적 파일)라 서버에서 모델을 돌릴 수 없다. 그런데 승패 모델 v0.3은 로지스틱 회귀라
  "결측은 학습 중앙값으로 채우기 → 표준화 → 계수를 곱해 더하기 → 시그모이드 → (보정)"이 전부다.
  그래서 계수·중앙값·평균·표준편차와, 경기마다 '선발과 상관없는 피처 값' + '후보 선발들의 기록'만 내보내면
  브라우저(site/assets/whatif.js)가 같은 확률을 낼 수 있다.
- 예고 선발 그대로 고르면 사이트에 공개한 확률과 같아야 한다 — tests/test_whatif.py가 파이썬 재현(prob)과
  실제 예측(predict.raw_prob), 그리고 브라우저 코드(node로 실행)의 숫자가 1e-9 안에서 같은지 확인한다.

선발 피처 (features.game_features와 같은 규칙)
- 선발 피처는 두 선발 모두 기록(직전 + 당해 시즌, LeagueState.pitcher_line)이 있을 때만 쓴다(starter_known = 1).
  하나라도 없으면 starter_known = 0이고 선발 차이 피처는 모두 결측 → 학습 중앙값.
- 차이는 홈 − 원정. 값 하나가 없으면(None) 그 차이만 결측.

후보 선발: 그 팀에서 그 시즌 그날 전까지 선발로 나온 투수(박스스코어 투구 순서 1번), 선발 수가 많은 순 최대 MAX_CANDIDATES명.
  예고 선발이 목록에 없으면 맨 앞에 넣는다. 기록은 그날 경기 직전 리그 상태의 값(그날 경기 결과는 보지 않음).
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np

from .features import MODEL_FEATURES, STARTER_FEATURES, game_features, regular_finals
from .seasons import is_regular
from datetime import date as _date

MAX_CANDIDATES = 8
SIG = 10  # 내보내는 실수의 유효숫자 — OS·BLAS마다 다른 마지막 자리(1e-16)를 없애 parity가 플랫폼과 무관하게 같게.
          # 확률 오차는 1e-10 수준이라 공개 확률(소수 4자리)과 비교에 영향이 없다.


def _f(v):
    """유효숫자 SIG자리로 반올림한 float (None·NaN은 None)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return float(f"{float(v):.{SIG}g}")
LINE_KEYS = ("era", "fip", "k9", "bb9", "ip", "last3_runs")   # 선발 차이 피처를 만드는 기록 (starter_<key>_diff)
STARTER_SET = set(STARTER_FEATURES)


def model_params(bundle: dict) -> dict | None:
    """로지스틱 회귀 번들 → 브라우저 계산용 숫자. LightGBM이면 None(브라우저에서 재현하지 않는다)."""
    if bundle.get("kind") != "lr":
        return None
    steps = bundle["model"].named_steps
    cal = bundle.get("calibration", "none")
    c = bundle.get("calibrator")
    if cal == "platt":
        calibration = {"method": "platt", "a": _f(c.coef_[0][0]), "b": _f(c.intercept_[0])}
    elif cal == "isotonic":
        calibration = {"method": "isotonic", "x": [_f(v) for v in c.X_thresholds_], "y": [_f(v) for v in c.y_thresholds_]}
    else:
        calibration = {"method": "none"}
    return {
        "version": bundle.get("version"),
        "features": list(bundle["features"]),
        "median": [_f(v) for v in steps["imputer"].statistics_],
        "mean": [_f(v) for v in steps["scaler"].mean_],
        "scale": [_f(v) for v in steps["scaler"].scale_],
        "coef": [_f(v) for v in steps["clf"].coef_[0]],
        "intercept": _f(steps["clf"].intercept_[0]),
        "calibration": calibration,
    }


def _line(state, player_id) -> dict | None:
    line = state.pitcher_line(player_id) if player_id is not None else None
    if line is None:
        return None
    return {k: _f(line.get(k)) for k in LINE_KEYS}


def starter_features(home: dict | None, away: dict | None) -> dict:
    """두 선발 기록(_line) → 선발 피처 7개 (game_features와 같은 규칙)."""
    known = home is not None and away is not None
    out = {"starter_known": int(known)}
    for k in LINE_KEYS:
        a, b = (home or {}).get(k), (away or {}).get(k)
        out[f"starter_{k}_diff"] = (a - b) if known and a is not None and b is not None else float("nan")
    return out


def prob(params: dict, base: dict, home: dict | None, away: dict | None) -> float:
    """파이썬 재현 — site/assets/whatif.js의 whatifProb와 한 줄씩 같은 계산."""
    x = {**base, **starter_features(home, away)}
    logit = params["intercept"]
    for i, name in enumerate(params["features"]):
        v = x.get(name)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            v = params["median"][i]
        logit += params["coef"][i] * (v - params["mean"][i]) / params["scale"][i]
    p = 1 / (1 + math.exp(-logit))
    cal = params["calibration"]
    if cal["method"] == "platt":
        q = min(max(p, 1e-6), 1 - 1e-6)
        p = 1 / (1 + math.exp(-(cal["a"] * math.log(q / (1 - q)) + cal["b"])))
    elif cal["method"] == "isotonic":
        p = float(np.interp(p, cal["x"], cal["y"]))
    return p


def candidate_starters(games: list[dict], boxscores: dict, season: int, on: str, team: str,
                       *, regular_only: bool) -> list[tuple[int, str, int]]:
    """그 팀에서 그날 전까지 선발로 나온 투수 [(player_id, 이름, 선발 수)] — 선발 수 많은 순, 같으면 이름 순."""
    cnt, names = Counter(), {}
    for g in games:
        if g.get("status") != "FINAL" or g["date"] >= on:
            continue
        if regular_only and not is_regular(season, _date.fromisoformat(g["date"]), g["game_id"]):
            continue
        box = boxscores.get(g["game_id"]) or {}
        for side in ("home", "away"):
            if g[f"{side}_code"] != team:
                continue
            for row in box.get("pitching", {}).get(side) or []:
                if row.get("order") == 1 and row.get("player_id") is not None:
                    cnt[row["player_id"]] += 1
                    names.setdefault(row["player_id"], row.get("name"))
                    break
    return sorted(((pid, names[pid], n) for pid, n in cnt.items()), key=lambda t: (-t[2], str(t[1])))


def game_block(game: dict, state, announced: dict | None, games: list[dict], boxscores: dict,
               *, regular_only: bool) -> dict:
    """경기 하나의 what-if 블록: 선발과 상관없는 피처 값(base), 예고(또는 실제) 선발, 팀별 후보 선발과 그 기록."""
    f = game_features(game, state, None)
    base = {n: _f(f[n]) for n in MODEL_FEATURES if n not in STARTER_SET}
    announced = announced or {}
    out = {"game_id": game["game_id"], "base": base, "announced": {}, "candidates": {}}
    for side in ("home", "away"):
        team = game[f"{side}_code"]
        ann = announced.get(side) or {}
        pid = ann.get("player_id")
        out["announced"][side] = pid
        cands = candidate_starters(games, boxscores, int(game["season"]), game["date"], team, regular_only=regular_only)
        if pid is not None:  # 예고(실제) 선발은 언제나 맨 앞 (그날 전 선발 기록이 없어도)
            first = next((c for c in cands if c[0] == pid), (pid, ann.get("name"), 0))
            cands = [first] + [c for c in cands if c[0] != pid]
        out["candidates"][side] = [{"player_id": c[0], "name": c[1], "starts": c[2], "line": _line(state, c[0])}
                                   for c in cands[:MAX_CANDIDATES]]
    return out
