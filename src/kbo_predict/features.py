"""누수 없는 경기 전 피처 26개. I/O 없음: dict 리스트(경기·박스스코어·예고 선발)만 입력으로 받는다.

핵심 규칙: 어떤 경기의 피처는 '그 경기 날짜 전날까지' 끝난 경기로만 만든다.
그래서 build_training_frame은 하루치 경기의 피처를 모두 계산한 뒤에야 상태를 갱신한다.
"""
from collections import defaultdict, deque
from datetime import date as _date, timedelta
from itertools import groupby

import pandas as pd

from .seasons import is_regular

TEAM_FEATURES = [
    "win_pct_diff", "last10_diff", "run_diff_diff", "pyth_diff", "prev_season_diff",
    "obp_diff", "hr_rate_diff", "k_rate_diff", "bb_rate_diff",
    "era_diff", "fip_diff", "k9_diff", "bb9_diff",
    "rest_diff", "bullpen3_diff",
    "home_venue_pct", "away_venue_pct", "h2h_home_pct", "season_progress",
]
STARTER_FEATURES = [
    "starter_known", "starter_era_diff", "starter_fip_diff", "starter_k9_diff",
    "starter_bb9_diff", "starter_ip_diff", "starter_last3_runs_diff",
]
FEATURE_NAMES = TEAM_FEATURES + STARTER_FEATURES  # 26개, 이 순서 고정 (모델·사이트가 의존)

FACTOR_LABELS = {
    "win_pct_diff": "팀 승률 차이",
    "last10_diff": "최근 10경기 흐름",
    "run_diff_diff": "경기당 득실차",
    "pyth_diff": "피타고리안 기대 승률 차이",
    "prev_season_diff": "지난 시즌 승률 차이",
    "obp_diff": "타선 출루율 차이",
    "hr_rate_diff": "타선 홈런 비율 차이",
    "k_rate_diff": "타선 삼진 비율 차이",
    "bb_rate_diff": "타선 볼넷 비율 차이",
    "era_diff": "투수진 평균자책점 차이",
    "fip_diff": "투수진 FIP 차이",
    "k9_diff": "투수진 9이닝당 삼진 차이",
    "bb9_diff": "투수진 9이닝당 볼넷 차이",
    "rest_diff": "휴식일 차이",
    "bullpen3_diff": "최근 3일 불펜 투구수 차이",
    "home_venue_pct": "홈팀의 홈 경기 승률",
    "away_venue_pct": "원정팀의 원정 경기 승률",
    "h2h_home_pct": "올 시즌 맞대결 승률",
    "season_progress": "시즌 진행도",
    "starter_known": "선발투수 기록 유무",
    "starter_era_diff": "선발 평균자책점 차이",
    "starter_fip_diff": "선발 FIP 차이",
    "starter_k9_diff": "선발 9이닝당 삼진 차이",
    "starter_bb9_diff": "선발 9이닝당 볼넷 차이",
    "starter_ip_diff": "선발 누적 이닝 차이",
    "starter_last3_runs_diff": "선발 최근 3경기 실점 차이",
    "bias": "기본 홈 어드밴티지",
}

SEASON_GAMES = 144  # 팀당 정규시즌 경기 수 (season_progress 분모)
PYTH_EXP = 1.83     # 피타고리안 승률 지수

# 박스스코어에서 합산하는 칸
BAT_KEYS = ("ab", "h", "bb", "hbp", "hr", "so")
PIT_KEYS = ("ip_outs", "er", "r", "hr", "bb", "hbp", "so")


# ---------- 작은 계산 도우미 ----------

def _num(v) -> int:
    """박스스코어 숫자 칸. None(기록 없음)은 0으로 본다."""
    return v or 0


def _add_rows(totals: dict, rows: list[dict], keys: tuple[str, ...]) -> None:
    """박스스코어 줄들의 keys 칸을 totals에 더한다."""
    for row in rows:
        for k in keys:
            totals[k] += _num(row.get(k))


def _ratio(num: float, den: float, scale: float = 1.0) -> float | None:
    """num/den*scale. 분모가 0이면 None (아직 기록 없음)."""
    return num * scale / den if den else None


def _batting_rates(b: dict) -> dict:
    """타선 비율: OBP, HR/PA, K%, BB% (PA = AB+BB+HBP)."""
    pa = b["ab"] + b["bb"] + b["hbp"]
    return {
        "obp": _ratio(b["h"] + b["bb"] + b["hbp"], pa),
        "hr_rate": _ratio(b["hr"], pa),
        "k_rate": _ratio(b["so"], pa),
        "bb_rate": _ratio(b["bb"], pa),
    }


def _pitching_rates(p: dict) -> dict:
    """투수 비율: ERA, FIP(리그 상수 없음), K/9, BB/9. 이닝은 아웃카운트(ip_outs)로 계산. 팀·개인 공용."""
    outs = p["ip_outs"]
    return {
        "era": _ratio(p["er"], outs, 27),
        "fip": _ratio(13 * p["hr"] + 3 * (p["bb"] + p["hbp"]) - 2 * p["so"], outs, 3),
        "k9": _ratio(p["so"], outs, 27),
        "bb9": _ratio(p["bb"], outs, 27),
    }


def _pct(won: int, lost: int) -> float | None:
    """승률. 승패가 갈린 경기가 없으면 None (무승부는 분모에서 제외)."""
    return _ratio(won, won + lost)


def _diff(a, b) -> float:
    """홈 − 원정. 어느 한쪽이라도 없으면 NaN."""
    return float("nan") if a is None or b is None else a - b


def _or_nan(v) -> float:
    return float("nan") if v is None else v


# ---------- 상태 ----------

def _new_team() -> dict:
    return {
        "wins": 0, "losses": 0, "games": 0, "runs_for": 0, "runs_against": 0,
        "results": deque(maxlen=10),                      # 최근 10경기 승(1)/패(0)
        "venue": {"home": [0, 0], "away": [0, 0]},        # 장소별 [승, 패]
        "bat": dict.fromkeys(BAT_KEYS, 0),                # 타격 합 (박스스코어 있는 경기만)
        "pit": dict.fromkeys(PIT_KEYS, 0),                # 투수진 합 (박스스코어 있는 경기만)
        "last_game_date": None,                           # 마지막 FINAL 경기 날짜 (date)
        "relief": deque(),                                # (date, 구원 투구수) — 최근 며칠만 남긴다
        "prev_win_pct": None,                             # 직전 시즌 최종 승률
    }


def _new_pitcher_totals() -> dict:
    return dict.fromkeys(PIT_KEYS, 0) | {"apps": 0, "starts": 0}


def _new_pitcher() -> dict:
    return {"cur": _new_pitcher_totals(), "prev": _new_pitcher_totals(), "last3": deque(maxlen=3)}


class LeagueState:
    """FINAL 경기만 누적하는 리그 상태: 팀별 기록, 맞대결, 투수별 기록(당해 + 직전 시즌)."""

    def __init__(self) -> None:
        self.season: int | None = None
        self._t: dict[str, dict] = defaultdict(_new_team)
        self._h2h: dict[tuple[str, str], int] = defaultdict(int)  # (승팀, 패팀) -> 당해 시즌 승수
        self._p: dict[int, dict] = defaultdict(_new_pitcher)

    def start_season(self, season: int) -> None:
        """현재 시즌 누적을 '직전 시즌'으로 넘기고 현재 시즌을 비운다.
        팀은 최종 승률만, 투수는 시즌 합계를 넘긴다 (두 시즌 전 기록은 버린다).
        투수의 최근 3선발 실점은 시즌을 넘어 그대로 이어진다."""
        self.season = season
        old = self._t
        self._t = defaultdict(_new_team)
        for code, t in old.items():
            self._t[code]["prev_win_pct"] = _pct(t["wins"], t["losses"])
        self._h2h = defaultdict(int)
        for p in self._p.values():
            p["prev"], p["cur"] = p["cur"], _new_pitcher_totals()

    def update(self, game: dict, box: dict | None = None) -> None:
        """끝난(FINAL, 양 팀 점수 있음) 경기 하나를 반영. box가 없으면 승패·득실·휴식일·맞대결만 갱신한다."""
        if game.get("status") != "FINAL":
            return
        hs, as_ = game["home_score"], game["away_score"]
        if hs is None or as_ is None:
            return
        day = _date.fromisoformat(game["date"])
        home, away = game["home_code"], game["away_code"]
        for side, code, rf, ra in (("home", home, hs, as_), ("away", away, as_, hs)):
            t = self._t[code]
            t["games"] += 1
            t["runs_for"] += rf
            t["runs_against"] += ra
            t["last_game_date"] = day
            if rf != ra:
                won = rf > ra
                t["wins" if won else "losses"] += 1
                t["results"].append(1 if won else 0)
                t["venue"][side][0 if won else 1] += 1
            if box is not None:
                self._add_box_side(t, box, side, day)
        if hs != as_:
            winner, loser = (home, away) if hs > as_ else (away, home)
            self._h2h[(winner, loser)] += 1

    def _add_box_side(self, t: dict, box: dict, side: str, day: _date) -> None:
        """박스스코어 한쪽 팀(side)의 타격·투수 기록을 팀과 투수 개인 상태에 더한다."""
        batting = box.get("batting", {}).get(side) or []
        pitching = box.get("pitching", {}).get(side) or []
        _add_rows(t["bat"], batting, BAT_KEYS)
        _add_rows(t["pit"], pitching, PIT_KEYS)
        # 구원 투구수: 최근 3일 창만 쓰므로 그보다 오래된 기록은 버린다 (갱신은 날짜순이라 안전)
        t["relief"].append((day, sum(_num(r.get("np")) for r in pitching if _num(r.get("order")) > 1)))
        while t["relief"] and t["relief"][0][0] < day - timedelta(days=3):
            t["relief"].popleft()
        for row in pitching:
            if row.get("player_id") is None:
                continue
            p = self._p[row["player_id"]]
            _add_rows(p["cur"], [row], PIT_KEYS)
            p["cur"]["apps"] += 1
            if row.get("order") == 1:
                p["cur"]["starts"] += 1
                p["last3"].append(_num(row.get("r")))

    def team_line(self, code: str, on: str) -> dict:
        """on('YYYY-MM-DD') 경기 직전 시점의 팀 요약. 저장된 상태를 바꾸지 않는다."""
        t = self._t.get(code) or _new_team()
        day = _date.fromisoformat(on)
        rf, ra = t["runs_for"], t["runs_against"]
        win_pct = _pct(t["wins"], t["losses"])
        last = t["last_game_date"]
        return {
            "win_pct": 0.5 if win_pct is None else win_pct,
            "last10": sum(t["results"]) / len(t["results"]) if t["results"] else 0.5,
            "run_diff": (rf - ra) / t["games"] if t["games"] else 0.0,
            "pyth": _ratio(rf**PYTH_EXP, rf**PYTH_EXP + ra**PYTH_EXP),
            "games": t["games"],
            **_batting_rates(t["bat"]),
            **_pitching_rates(t["pit"]),
            "home_pct": _pct(*t["venue"]["home"]),
            "away_pct": _pct(*t["venue"]["away"]),
            "prev_win_pct": t["prev_win_pct"],
            "rest_days": (day - last).days if last else None,
            "bullpen3": sum(n for d, n in t["relief"] if day - timedelta(days=3) <= d < day),
        }

    def h2h_home_pct(self, home: str, away: str) -> float | None:
        """올 시즌 맞대결에서 home 팀의 승률 (장소 무관). 승패 난 맞대결이 없으면 None."""
        return _pct(self._h2h.get((home, away), 0), self._h2h.get((away, home), 0))

    def pitcher_line(self, player_id: int) -> dict | None:
        """투수 요약: 당해 + 직전 시즌 합산 비율과 당해 시즌만의 기록("season"). 기록이 전혀 없으면 None."""
        p = self._p.get(player_id)
        if p is None or p["cur"]["apps"] + p["prev"]["apps"] == 0:
            return None
        both = {k: p["cur"][k] + p["prev"][k] for k in PIT_KEYS}
        cur = _pitching_rates(p["cur"])
        return {
            **_pitching_rates(both),
            "ip": both["ip_outs"] / 3,
            "last3_runs": sum(p["last3"]) / len(p["last3"]) if p["last3"] else None,
            "season": {"era": cur["era"], "k9": cur["k9"], "bb9": cur["bb9"],
                       "ip": p["cur"]["ip_outs"] / 3, "starts": p["cur"]["starts"]},
        }


# ---------- 피처 ----------

def starter_ids(box: dict | None) -> dict:
    """박스스코어에서 양 팀 선발(order == 1)을 찾는다. 예고 선발(starters.jsonl)과 같은 모양으로 돌려준다."""
    out = {"home": None, "away": None}
    if box is None:
        return out
    for side in out:
        for row in box.get("pitching", {}).get(side) or []:
            if row.get("order") == 1 and row.get("player_id") is not None:
                out[side] = {"player_id": row["player_id"], "name": row.get("name")}
                break
    return out


def _starter_line(state: LeagueState, starters: dict | None, side: str) -> dict | None:
    s = (starters or {}).get(side)
    return state.pitcher_line(s["player_id"]) if s and s.get("player_id") is not None else None


def game_features(game: dict, state: LeagueState, starters: dict | None = None) -> dict:
    """경기 하나의 피처 26개(결측은 NaN)와 사이트 표시용 팀·선발 요약."""
    home, away, on = game["home_code"], game["away_code"], game["date"]
    h, a = state.team_line(home, on), state.team_line(away, on)
    f = {
        "win_pct_diff": h["win_pct"] - a["win_pct"],
        "last10_diff": h["last10"] - a["last10"],
        "run_diff_diff": h["run_diff"] - a["run_diff"],
        "pyth_diff": _diff(h["pyth"], a["pyth"]),
        "prev_season_diff": _diff(h["prev_win_pct"], a["prev_win_pct"]),
    }
    for key in ("obp", "hr_rate", "k_rate", "bb_rate", "era", "fip", "k9", "bb9"):
        f[f"{key}_diff"] = _diff(h[key], a[key])
    f["rest_diff"] = _diff(h["rest_days"], a["rest_days"])
    f["bullpen3_diff"] = h["bullpen3"] - a["bullpen3"]
    f["home_venue_pct"] = _or_nan(h["home_pct"])
    f["away_venue_pct"] = _or_nan(a["away_pct"])
    f["h2h_home_pct"] = _or_nan(state.h2h_home_pct(home, away))
    f["season_progress"] = h["games"] / SEASON_GAMES

    hs, as_ = _starter_line(state, starters, "home"), _starter_line(state, starters, "away")
    known = hs is not None and as_ is not None
    f["starter_known"] = int(known)
    for key in ("era", "fip", "k9", "bb9", "ip", "last3_runs"):
        f[f"starter_{key}_diff"] = _diff(hs[key], as_[key]) if known else float("nan")
    return {
        **{n: f[n] for n in FEATURE_NAMES},
        "home_line": h, "away_line": a, "home_starter": hs, "away_starter": as_,
    }


def build_training_frame(
    games: list[dict], boxscores: dict[int, dict], *, season: int, state: LeagueState | None = None
) -> pd.DataFrame:
    """정규시즌 FINAL 경기를 날짜순으로 훑으며 학습 행을 만든다.
    같은 날짜 경기는 피처를 모두 계산한 뒤 상태를 갱신한다 (더블헤더 1차전 결과가 2차전에 새지 않게).
    선발은 박스스코어의 실제 선발(order==1)을 쓴다. 무승부는 행을 만들지 않지만 상태에는 반영한다.
    state를 넘기면 그 상태에 이어서 누적한다 (시즌 연결은 호출하는 쪽에서 start_season으로)."""
    state = state if state is not None else LeagueState()
    ordered = sorted(games, key=lambda g: (g["date"], g["game_id"]))
    rows = []
    for _, grp in groupby(ordered, key=lambda g: g["date"]):
        day_games = [
            g for g in grp
            if g["status"] == "FINAL" and is_regular(season, _date.fromisoformat(g["date"]), g["game_id"])
        ]
        for g in day_games:
            if g["home_score"] is None or g["away_score"] is None or g["home_score"] == g["away_score"]:
                continue
            f = game_features(g, state, starter_ids(boxscores.get(g["game_id"])))
            rows.append({
                "game_id": g["game_id"], "date": g["date"], "season": season,
                "home_code": g["home_code"], "away_code": g["away_code"],
                **{k: f[k] for k in FEATURE_NAMES},
                "y": int(g["home_score"] > g["away_score"]),
            })
        for g in day_games:
            state.update(g, boxscores.get(g["game_id"]))
    return pd.DataFrame(rows, columns=["game_id", "date", "season", "home_code", "away_code", *FEATURE_NAMES, "y"])
