"""누수 없는 경기 피처. I/O 없음: dict 리스트만 입력으로 받는다."""
from collections import defaultdict, deque
from datetime import date as _date
from itertools import groupby

import pandas as pd

from .seasons import is_regular

FEATURE_NAMES = ["win_pct_diff", "last10_diff", "run_diff_diff"]
FACTOR_LABELS = {
    "win_pct_diff": "팀 승률 차이",
    "last10_diff": "최근 10경기 흐름",
    "run_diff_diff": "경기당 득실차",
    "intercept": "홈 어드밴티지",
}


def _new_team() -> dict:
    return {"wins": 0, "losses": 0, "games": 0, "runs_for": 0, "runs_against": 0, "results": deque(maxlen=10)}


class LeagueState:
    """FINAL 경기만 누적하는 팀별 상태."""

    def __init__(self) -> None:
        self._t: dict[str, dict] = defaultdict(_new_team)

    def update(self, game: dict) -> None:
        if game.get("status") != "FINAL":
            return
        hs, as_ = game["home_score"], game["away_score"]
        if hs is None or as_ is None:
            return
        for code, rf, ra in ((game["home_code"], hs, as_), (game["away_code"], as_, hs)):
            t = self._t[code]
            t["games"] += 1
            t["runs_for"] += rf
            t["runs_against"] += ra
            if rf != ra:
                won = rf > ra
                t["wins" if won else "losses"] += 1
                t["results"].append(1 if won else 0)

    def team_win_pct(self, code: str) -> float:
        t = self._t.get(code)
        if not t or t["wins"] + t["losses"] == 0:
            return 0.5
        return t["wins"] / (t["wins"] + t["losses"])

    def team_last10(self, code: str) -> float:
        t = self._t.get(code)
        if not t or not t["results"]:
            return 0.5
        return sum(t["results"]) / len(t["results"])

    def team_run_diff(self, code: str) -> float:
        t = self._t.get(code)
        if not t or t["games"] == 0:
            return 0.0
        return (t["runs_for"] - t["runs_against"]) / t["games"]

    def team_line(self, code: str) -> dict:
        t = self._t.get(code)
        return {
            "win_pct": self.team_win_pct(code),
            "last10": self.team_last10(code),
            "run_diff": self.team_run_diff(code),
            "games": t["games"] if t else 0,
        }


def game_features(game: dict, state: LeagueState) -> dict:
    home, away = game["home_code"], game["away_code"]
    h, a = state.team_line(home), state.team_line(away)
    return {
        "win_pct_diff": h["win_pct"] - a["win_pct"],
        "last10_diff": h["last10"] - a["last10"],
        "run_diff_diff": h["run_diff"] - a["run_diff"],
        "home_line": h,
        "away_line": a,
    }


def build_training_frame(games: list[dict], *, season: int) -> pd.DataFrame:
    """날짜순으로 상태를 누적. 같은 날짜 경기는 피처를 모두 계산한 뒤 상태를 갱신한다."""
    ordered = sorted(games, key=lambda g: (g["date"], g["game_id"]))
    state = LeagueState()
    rows = []
    for day, grp in groupby(ordered, key=lambda g: g["date"]):
        day_games = [
            g for g in grp
            if g["status"] == "FINAL" and is_regular(season, _date.fromisoformat(g["date"]))
        ]
        for g in day_games:
            if g["home_score"] == g["away_score"]:
                continue
            f = game_features(g, state)
            rows.append({
                "game_id": g["game_id"],
                "date": g["date"],
                **{k: f[k] for k in FEATURE_NAMES},
                "y": int(g["home_score"] > g["away_score"]),
            })
        for g in day_games:
            state.update(g)
    return pd.DataFrame(rows, columns=["game_id", "date", *FEATURE_NAMES, "y"])
