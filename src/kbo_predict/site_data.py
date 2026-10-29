"""사이트용 데이터 파일 만들기: data/public/players.json, data/public/teams.json. 네트워크 없음.

players.json  선수-시즌 한 칸씩(타자·투수 따로). 유형(이름·소속 확률), 2D 지도 좌표, 주요 기록, 비슷한 선수 5명.
              입력은 models/clusters.pkl(cluster.build 결과)과 유형 이름표(config/cluster_labels.yaml).
teams.json    팀-시즌 한 칸씩. 정규시즌 FINAL 경기(features.regular_finals)로 센 승·패·무, 승률, 피타고리안 승률,
              홈/원정 승률, 상대 팀별 승률, 그 시즌 로스터의 유형 비중, 그리고 2026(홀드아웃)만 모델 기대 승률.

반올림 규칙(사이트가 그대로 찍는 값):
    비율·확률·좌표·유사도 소수 3자리, 이닝(ip) 소수 1자리, ERA 소수 2자리. NaN은 null.
    -0.0은 0.0으로 바꾼다 (JSON에 "-0.0"이 나오지 않게).
정렬(같은 입력이면 같은 바이트가 나오도록 순서를 모두 정해 둔다):
    players  season 내림차순 → group(batter, pitcher) → player_id 오름차순
    similar  cluster.similar_players가 정한 순서 그대로 (유사도 내림차순, 동률은 (season, player_id) 순)
    teams    season 내림차순 → 승률 내림차순(반올림 전 값) → 팀 코드 오름차순 (승률이 없는 팀은 그 시즌 맨 뒤)
    dict 키는 파일에 쓸 때 정렬한다 (publish._write_json(sort_keys=True)).

용어:
    피타고리안 승률  득점^e / (득점^e + 실점^e), e = features.PYTH_EXP(1.83). 득실점으로 본 '실력만큼의' 승률.
    모델 기대 승률   평가용 모델(models/report-2026.pkl)이 그 팀 경기마다 낸 승리 확률의 평균.
                     홈 경기는 P(홈 승) = p, 원정 경기는 1 − p 를 모아 평균한다. features.parquet에는 승패가 갈린
                     경기만 있으므로(무승부 제외) 그 경기들 기준이다. 2015~2025는 모델이 학습·검증에 쓴 시즌이라
                     '맞힌 척'이 되므로 null로 둔다.
    로스터 유형 비중  그 시즌 유형이 있는 선수(규정급)만 모아, 타자는 타석(PA), 투수는 아웃카운트(ip_outs = 이닝 × 3)로
                     가중한 유형별 비중. 선수의 팀은 집계의 team 열(그 시즌 가장 많이 뛴 팀) 하나로 센다.
                     소수 3자리로 반올림하되 최대 나머지 방식으로 맞춰 합이 정확히 1이 되게 한다.
"""
import math

import pandas as pd

from . import raw_store
from .cluster import CLUSTER_VERSION, GROUPS
from .features import PYTH_EXP, regular_finals
from .teams import TEAMS
from .train_win import REPORT_VERSION, predict_proba

HOLDOUT_SEASON = 2026          # model_expected를 채우는 유일한 시즌 (report 모델이 보지 않은 평가 시즌)
N_SIMILAR = 5
TEAMS_NOTE = ("model_expected는 2026(홀드아웃)만; 2015~2025는 학습·검증 시즌이라 null"
              " (2026은 승패가 갈린 경기 기준, 무승부 제외)")
WEIGHT_COL = {"batter": "pa", "pitcher": "ip_outs"}   # 로스터 유형 비중의 가중치

__all__ = ["players_payload", "teams_payload", "team_model_expected", "roster_types", "HOLDOUT_SEASON"]


# ---------- 작은 도우미 ----------

def _r(v, nd: int = 3):
    """JSON용 반올림. None·NaN은 None, -0.0은 0.0."""
    if v is None:
        return None
    v = float(v)
    if math.isnan(v):
        return None
    return round(v, nd) + 0.0


def _ratio(num, den):
    """num / den. 분모가 0 이하면 None."""
    return float(num) / float(den) if den and den > 0 else None


def _str_or_none(v):
    """한글 이름 칸: 문자열이면 그대로, 없거나 NaN이면 None."""
    return v if isinstance(v, str) and v else None


# ---------- players.json ----------

def _batter_stats(r) -> dict:
    """타자 주요 기록. avg = 안타/타수, obp = (안타+볼넷+사구)/타석. 나머지 비율은 군집에 쓴 값 그대로."""
    return {
        "pa": int(r.pa), "hr": int(r.hr), "sb": int(r.sb),
        "avg": _r(_ratio(r.h, r.ab)),
        "obp": _r(_ratio(r.h + r.bb + r.hbp, r.pa)),
        "k_pct": _r(r.k_pct), "bb_pct": _r(r.bb_pct), "iso": _r(r.iso), "babip": _r(r.babip),
    }


def _pitcher_stats(r) -> dict:
    """투수 주요 기록. ip = 아웃카운트/3 (소수 1자리, 58.333 -> 58.3), era = 자책점/아웃카운트 × 27 (소수 2자리)."""
    return {
        "games": int(r.games), "starts": int(r.starts),
        "ip": _r(r.ip_outs / 3, 1),
        "era": _r(_ratio(r.er * 27, r.ip_outs), 2),
        "k_pct": _r(r.k_pct), "bb_pct": _r(r.bb_pct), "hr_pct": _r(r.hr_pct), "babip": _r(r.babip),
    }


def players_payload(obj: dict, labels: dict, meta: dict) -> dict:
    """players.json 내용. obj = cluster.load_bundle 결과, labels = cluster.load_labels(), meta = {generated_at, commit_sha}.
    선수-시즌 하나에 한 칸 (투타 겸업이면 batter·pitcher 두 칸). 비슷한 선수는 같은 그룹 안에서 찾은 5명이다."""
    types = {}
    players = []
    for g in GROUPS:
        b, a = obj[g]["bundle"], obj[g]["assigned"]
        types[g] = [{"id": t, "name": labels[g][t]["name"], "blurb": labels[g][t]["blurb"]} for t in range(b["k"])]
        # 비슷한 선수 칸에 이름·팀을 붙이려고 (season, player_id) -> 행 사전을 만든다
        rows = {(int(r.season), int(r.player_id)): r for r in a.itertuples(index=False)}
        stats_fn = _batter_stats if g == "batter" else _pitcher_stats
        for key, r in rows.items():
            t = int(r.type)
            similar = []
            for s in obj[g]["similar"].get(key, [])[:N_SIMILAR]:
                o = rows[(s["season"], s["player_id"])]
                similar.append({"player_id": int(o.player_id), "name": o.name, "name_ko": _str_or_none(o.name_ko),
                                "season": int(o.season), "team": o.team, "similarity": _r(s["similarity"])})
            players.append({
                "player_id": int(r.player_id), "name": r.name, "name_ko": _str_or_none(r.name_ko),
                "group": g, "season": int(r.season), "team": r.team,
                "pos": r.pos if g == "batter" else "P",
                "type": {"id": t, "name": labels[g][t]["name"]},
                "prob": _r(r.prob),
                "membership": [_r(m) for m in r.membership],
                "x": _r(r.x), "y": _r(r.y),
                "stats": stats_fn(r),
                "similar": similar,
            })
    players.sort(key=lambda p: (-p["season"], GROUPS.index(p["group"]), p["player_id"]))
    return {
        "generated_at": meta.get("generated_at"), "commit_sha": meta.get("commit_sha"),
        "model_version": obj.get("version", CLUSTER_VERSION),
        "fit_seasons": [int(s) for s in obj["fit_seasons"]],
        "types": types, "players": players,
    }


# ---------- teams.json ----------

def roster_types(assigned: pd.DataFrame, group: str, season: int, team: str) -> dict[str, float]:
    """그 시즌·팀의 유형 비중 {유형 id(문자열): 비중}. 타자는 타석, 투수는 아웃카운트로 가중.
    소수 3자리(1000분의 1 단위)로 내림한 뒤 남는 몫을 나머지가 큰 유형부터(동률은 유형 번호 순) 1씩 더해
    합이 정확히 1이 되게 한다 (최대 나머지 방식). 유형 있는 선수가 없으면 빈 사전."""
    rows = assigned[(assigned["season"] == season) & (assigned["team"] == team)]
    weights = rows.groupby("type")[WEIGHT_COL[group]].sum()
    total = float(weights.sum())
    if total <= 0:
        return {}
    exact = {int(t): float(w) / total * 1000 for t, w in weights.items()}
    units = {t: math.floor(v) for t, v in exact.items()}
    rest = 1000 - sum(units.values())
    for t in sorted(exact, key=lambda t: (-(exact[t] - units[t]), t))[:rest]:
        units[t] += 1
    return {str(t): units[t] / 1000 for t in sorted(units)}


def team_model_expected(features_df: pd.DataFrame, report_bundle: dict, season: int = HOLDOUT_SEASON) -> dict[str, float]:
    """팀 코드 -> 모델 기대 승률(반올림 전). features_df의 그 시즌 행(정규시즌, 승패가 갈린 경기)에
    평가 모델을 돌려 P(홈 승) = p를 얻고, 홈 경기는 p, 원정 경기는 1 − p 를 팀별로 모아 평균한다."""
    df = features_df[features_df["season"] == season]
    if df.empty:
        return {}
    p = predict_proba(report_bundle, df[report_bundle["features"]])
    per_team = pd.concat([
        pd.DataFrame({"code": df["home_code"].to_numpy(), "p": p}),
        pd.DataFrame({"code": df["away_code"].to_numpy(), "p": 1.0 - p}),
    ])
    return {str(c): float(v) for c, v in per_team.groupby("code")["p"].mean().items()}


def _new_line() -> dict:
    return {"w": 0, "l": 0, "t": 0, "rs": 0, "ra": 0, "home": [0, 0], "away": [0, 0], "vs": {}, "name": None}


def _season_lines(season: int) -> dict[str, dict]:
    """팀 코드 -> 그 시즌 정규시즌 FINAL 누적(승·패·무, 득실점, 홈/원정 승패, 상대별 승패, 한글 팀 이름).
    점수가 없는 FINAL은 건너뛴다. 팀 이름은 그 팀의 시즌 마지막 경기 구단명(TEAMS의 ko)."""
    lines: dict[str, dict] = {}
    for g in regular_finals(raw_store.load_games(season), season):
        hs, as_ = g["home_score"], g["away_score"]
        if hs is None or as_ is None:
            continue
        for side, code, opp, full, scored, allowed in (("home", g["home_code"], g["away_code"], g["home"], hs, as_),
                                                        ("away", g["away_code"], g["home_code"], g["away"], as_, hs)):
            ln = lines.setdefault(code, _new_line())
            ln["name"] = TEAMS[full]["ko"]          # predict._side와 같은 방식 (경기의 구단 풀네임 -> 한글)
            ln["rs"] += scored
            ln["ra"] += allowed
            vs = ln["vs"].setdefault(opp, [0, 0])
            if scored > allowed:
                ln["w"] += 1
                ln[side][0] += 1
                vs[0] += 1
            elif scored < allowed:
                ln["l"] += 1
                ln[side][1] += 1
                vs[1] += 1
            else:
                ln["t"] += 1                         # 무승부: 승률 분모에서 뺀다 (KBO 방식)
    return lines


def _pct(won: int, lost: int):
    """승률 = 승 / (승 + 패). 승패가 갈린 경기가 없으면 None."""
    return _ratio(won, won + lost)


def _pyth(rs: int, ra: int):
    """피타고리안 승률 득점^e / (득점^e + 실점^e). 득실점이 모두 0이면 None."""
    if rs + ra <= 0:
        return None
    return rs ** PYTH_EXP / (rs ** PYTH_EXP + ra ** PYTH_EXP)


def teams_payload(seasons, *, obj: dict, labels: dict, features_df: pd.DataFrame | None,
                  report_bundle: dict | None, meta: dict) -> dict:
    """teams.json 내용. seasons의 정규시즌 FINAL 경기를 raw_store에서 읽어 팀-시즌 줄을 만든다.
    model_expected는 HOLDOUT_SEASON(2026)에만, features_df와 report_bundle이 있을 때 채운다 (나머지 시즌은 null).
    labels는 받기만 한다 — 유형 이름은 players.json의 types에 있고 여기서는 유형 id로만 적는다."""
    del labels  # 인터페이스를 players_payload와 맞추려고 받는다 (현재 쓰지 않음)
    expected = {}
    if features_df is not None and report_bundle is not None:
        expected = team_model_expected(features_df, report_bundle, HOLDOUT_SEASON)
    teams = []
    for season in sorted({int(s) for s in seasons}, reverse=True):
        for code, ln in _season_lines(season).items():
            win_pct = _pct(ln["w"], ln["l"])
            teams.append({
                "season": season, "code": code, "name": ln["name"],
                "games": ln["w"] + ln["l"] + ln["t"], "wins": ln["w"], "losses": ln["l"], "ties": ln["t"],
                "win_pct": _r(win_pct), "pyth_pct": _r(_pyth(ln["rs"], ln["ra"])),
                "model_expected": _r(expected.get(code)) if season == HOLDOUT_SEASON else None,
                "home_pct": _r(_pct(*ln["home"])), "away_pct": _r(_pct(*ln["away"])),
                "vs": {opp: _r(_pct(*wl)) for opp, wl in ln["vs"].items()},
                "roster_types": {g: roster_types(obj[g]["assigned"], g, season, code) for g in GROUPS},
                "_sort": -1.0 if win_pct is None else win_pct,
            })
    teams.sort(key=lambda t: (-t["season"], -t["_sort"], t["code"]))
    for t in teams:
        del t["_sort"]
    return {
        "generated_at": meta.get("generated_at"), "commit_sha": meta.get("commit_sha"),
        "model_version": (report_bundle or {}).get("version", REPORT_VERSION),
        "note": TEAMS_NOTE, "teams": teams,
    }
