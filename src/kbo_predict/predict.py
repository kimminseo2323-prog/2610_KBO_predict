"""경기 1건 추론. I/O 없음.

predict_game이 돌려주는 항목(latest.json의 games[] 한 칸):
    game_id, date, time, stadium, round, status  경기 정보
                      round = "preseason"(개막일 전 시범경기) | "regular" | "postseason"(종료일 뒤, 결정전 등 제외 경기) — _round
    home / away       {code, name, starter, win_pct_season, last10, run_diff}
                      starter = {player_id, name, era, k9, bb9, ip, starts, type} (당해 시즌 기록) 또는 None(미발표)
                      type = {id, name} 직전 시즌 투수 유형 (clusters.pkl) 또는 None
    home_win_prob     캘리브레이션까지 적용한 최종 P(홈 승)
    factors           요인 상위 5개 [{name, contribution_pp}] — |pp| 큰 순서
    starter_known     두 선발 모두 기록이 있어 선발 피처를 쓸 수 있었는가 (피처 starter_known과 같은 값)

요인(pp) 계산: train_win.explain이 캘리브레이션 전 로짓을 '번들 피처 기여 + 기본값(bias)'으로 정확히 나눈다.
platt 캘리브레이션은 최종 로짓 = a · (캘리브레이션 전 로짓) + b 이므로, 캘리브레이션 전 로짓 1만큼의 변화는
최종 로짓 a만큼의 변화다. 최종 로짓 1만큼의 변화는 최종 확률 p 근처에서 약 p(1−p)만큼의 확률 변화이므로
    pp = 기여 × a × p(1−p) × 100 (퍼센트포인트)   — platt
    pp = 기여 × p(1−p) × 100                      — isotonic·none (기울기 보정 없음)
bias(평균적인 경기의 홈 어드밴티지)도 후보에 넣고 (번들 피처 수 + 1)개 중 |pp| 상위 5개를 고른다.
주의: 요인 pp는 캘리브레이션 후 확률에 대한 **1차 근사**다. 그래서 (번들 피처 수 + 1)개 pp의 합이 `home_win_prob − 0.5`와
정확히 같지 않을 수 있다 (platt 절편 b와 시그모이드의 곡률은 요인으로 나누지 않는다).
"""
from datetime import date as _date

import pandas as pd

from .features import FACTOR_LABELS, LeagueState, game_features
from .seasons import REGULAR_SEASON, is_regular
from .teams import TEAMS
from .train_win import explain, predict_proba

TOP_FACTORS = 5


def _r(v, nd: int):
    """반올림. 값이 없으면(None) None 그대로 — 개막일처럼 기록이 없는 팀도 죽지 않게 (R4)."""
    return None if v is None else round(v, nd)


def _starter(announced: dict | None, line: dict | None, starter_types: dict | None = None) -> dict | None:
    """예고 선발 블록. 발표가 없으면 None, 발표됐지만 아직 기록이 없으면 통계 칸만 None.
    type = starter_types[player_id] ({"id", "name"}: 직전 시즌 투수 유형) 또는 None(유형 없음). 키는 항상 있다."""
    if not announced or announced.get("player_id") is None:
        return None
    season = (line or {}).get("season") or {}
    return {
        "player_id": announced["player_id"],
        "name": announced.get("name"),
        "era": _r(season.get("era"), 2),
        "k9": _r(season.get("k9"), 2),
        "bb9": _r(season.get("bb9"), 2),
        "ip": _r(season.get("ip"), 1),
        "starts": season.get("starts"),
        "type": (starter_types or {}).get(announced["player_id"]),
    }


def _side(full_name: str, code: str, line: dict, starter: dict | None) -> dict:
    return {
        "code": code,
        "name": TEAMS[full_name]["ko"],
        "starter": starter,
        "win_pct_season": _r(line["win_pct"], 3),
        "last10": _r(line["last10"], 3),
        "run_diff": _r(line["run_diff"], 2),
    }


def factor_pp(bundle: dict, X: pd.DataFrame, p: float) -> list[tuple[str, float]]:
    """X 첫 행의 요인 전부(피처 순서 + 마지막에 bias)를 (이름, pp)로. 반올림·자르기 전 값.
    p = 최종(캘리브레이션 후) P(홈 승). platt이면 기울기 a(calibrator.coef_[0][0])를 곱한다 (모듈 docstring)."""
    contrib, base = explain(bundle, X)
    a = float(bundle["calibrator"].coef_[0][0]) if bundle["calibration"] == "platt" else 1.0
    slope = a * p * (1 - p) * 100
    items = [(FACTOR_LABELS[n], float(c) * slope) for n, c in zip(bundle["features"], contrib[0])]
    items.append((FACTOR_LABELS["bias"], float(base[0]) * slope))
    return items


def _factors(bundle: dict, X: pd.DataFrame, p: float) -> list[dict]:
    """요인 (번들 피처 수 + 1)개(bundle["features"] + bias)를 pp로 바꿔 |pp| 상위 TOP_FACTORS개. 순서는 반올림 전 |pp| 기준 (동률은 피처 순서)."""
    items = sorted(factor_pp(bundle, X, p), key=lambda kv: -abs(kv[1]))
    # + 0.0: 반올림 결과가 -0.0이면 0.0으로 (JSON에 "-0.0"이 나오지 않게)
    return [{"name": name, "contribution_pp": round(v, 1) + 0.0} for name, v in items[:TOP_FACTORS]]


def _round(season: int, d: _date, game_id) -> str:
    """경기 구분. 등록된 시즌(seasons.REGULAR_SEASON)이면 개막일 전 = "preseason"(시범경기).
    그 밖에는 is_regular로 "regular" / "postseason" — 종료일 뒤 경기와, 날짜로는 정규시즌이지만 따로 뺀 경기
    (seasons.EXCLUDED_GAMES, 예: 2024-10-01 5위 결정전 12234)는 "postseason".
    등록 전 시즌은 is_regular의 3/1~10/31 대체 범위를 쓰고 시범경기를 따로 가리지 않는다."""
    if season in REGULAR_SEASON and d < REGULAR_SEASON[season][0]:
        return "preseason"
    return "regular" if is_regular(season, d, game_id) else "postseason"


def predict_game(bundle: dict, game: dict, state: LeagueState, starters: dict | None = None,
                 starter_types: dict[int, dict] | None = None) -> dict:
    """경기 하나 예측. starters = 예고 선발 행(raw_store.load_starters의 값) 또는 None(미발표).
    starter_types = 투수 player_id -> {"id", "name"} (직전 시즌 유형, run_pipeline이 clusters.pkl에서 만든다).
    없거나 그 투수가 없으면 선발 블록의 type은 None. 예측 확률·요인에는 영향이 없다 (표시용)."""
    f = game_features(game, state, starters)
    X = pd.DataFrame([{n: f[n] for n in bundle["features"]}])
    p = float(predict_proba(bundle, X)[0])
    announced = starters or {}
    season = int(game["season"])
    return {
        "game_id": game["game_id"],
        "date": game["date"],
        "time": game.get("time_kst"),
        "stadium": game.get("stadium"),
        "round": _round(season, _date.fromisoformat(game["date"]), game["game_id"]),
        "status": game["status"],
        "home": _side(game["home"], game["home_code"], f["home_line"],
                      _starter(announced.get("home"), f["home_starter"], starter_types)),
        "away": _side(game["away"], game["away_code"], f["away_line"],
                      _starter(announced.get("away"), f["away_starter"], starter_types)),
        "home_win_prob": round(p, 4),
        "factors": _factors(bundle, X, p),
        "starter_known": bool(f["starter_known"]),
    }


def canceled_entry(game: dict) -> dict:
    """취소(CANCELED) 경기의 표시용 항목 — 예측 없이 경기 정보만 (latest.json · 되감기 파일이 같은 모양을 쓴다)."""
    return {
        "game_id": game["game_id"], "date": game["date"], "time": game.get("time_kst"),
        "stadium": game.get("stadium"), "status": "CANCELED", "status_note": game.get("status_note"),
        "home_win_prob": None, "factors": [],
        "home": {"code": game["home_code"]}, "away": {"code": game["away_code"]},
    }
