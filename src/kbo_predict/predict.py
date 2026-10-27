"""경기 1건 추론. I/O 없음."""
from datetime import date as _date

import pandas as pd

from .features import FACTOR_LABELS, FEATURE_NAMES, LeagueState, game_features
from .seasons import is_regular
from .teams import TEAMS


def _side(full_name: str, code: str, line: dict) -> dict:
    return {
        "code": code,
        "name": TEAMS[full_name]["ko"],
        "starter": None,
        "win_pct_season": round(line["win_pct"], 3),
        "last10": round(line["last10"], 3),
        "run_diff": round(line["run_diff"], 2),
    }


def predict_game(bundle: dict, game: dict, state: LeagueState) -> dict:
    f = game_features(game, state)
    scaler, model = bundle["scaler"], bundle["model"]
    x = pd.DataFrame([[f[n] for n in FEATURE_NAMES]], columns=FEATURE_NAMES)
    z = scaler.transform(x)[0]
    p = float(model.predict_proba(scaler.transform(x))[0, 1])
    slope = p * (1 - p) * 100
    coef = model.coef_[0]
    # 피처 차이가 0인 "동률 매치업"을 기준선으로 삼는다: z0 = scaler(0) 의 기여분은 절편(홈 어드밴티지)에 합친다.
    # 이렇게 해야 두 팀이 같을 때 팀 요인이 0이 되고, 모든 요인의 합은 로짓 선형항과 일치한다.
    z0 = scaler.transform(pd.DataFrame([[0.0] * len(FEATURE_NAMES)], columns=FEATURE_NAMES))[0]
    factors = [
        {"name": FACTOR_LABELS[n], "contribution_pp": round(float(c * (zi - z0i) * slope), 1) + 0.0}
        for n, c, zi, z0i in zip(FEATURE_NAMES, coef, z, z0)
    ]
    home_adv = float(model.intercept_[0] + (coef * z0).sum())
    factors.append({"name": FACTOR_LABELS["intercept"], "contribution_pp": round(home_adv * slope, 1) + 0.0})
    factors.sort(key=lambda d: -abs(d["contribution_pp"]))
    season = int(game["season"])
    return {
        "game_id": game["game_id"],
        "date": game["date"],
        "time": game.get("time_kst"),
        "stadium": game.get("stadium"),
        "round": "regular" if is_regular(season, _date.fromisoformat(game["date"])) else "postseason",
        "status": game["status"],
        "home": _side(game["home"], game["home_code"], f["home_line"]),
        "away": _side(game["away"], game["away_code"], f["away_line"]),
        "home_win_prob": round(p, 4),
        "factors": factors,
    }
