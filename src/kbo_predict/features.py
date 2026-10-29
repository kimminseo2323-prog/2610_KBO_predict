"""누수 없는 경기 전 피처 26개. I/O 없음: dict 리스트(경기·박스스코어·예고 선발)만 입력으로 받는다.

핵심 규칙: 어떤 경기의 피처는 '그 경기 날짜 전날까지' 끝난 경기로만 만든다.
그래서 build_training_frame은 하루치 경기의 피처를 모두 계산한 뒤에야 상태를 갱신한다.

상성(유형) 피처 (3단계, 선택): LeagueState(types=...)로 선수 유형표를 넘길 때만 붙는다 (라이브는 넘기지 않는다).
    유형은 '직전 시즌' 유형만 쓴다 — 2026 경기에는 (2025, 선수) 유형. 당해 시즌 유형은 그 시즌이 끝나야 정해지므로
    쓰면 누수다. 타선 구성은 당해 시즌 지금까지 팀 타석(PA)을 선수 유형별로 나눈 비중, 선발은 유형 원-핫.
    matchup_feature_names(kb, kp) 순서: bat_type{t}_diff(K_b개), starter_type{t}_diff(K_p개), types_known.
    기본 피처 26개(FEATURE_NAMES)와 features.parquet는 그대로 두고, 상성 열은 별도 parquet(--matchup-out)에 저장한다.
"""
import argparse
import hashlib
import time
from collections import Counter, defaultdict, deque
from datetime import date as _date, timedelta
from itertools import groupby
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import raw_store
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


def matchup_feature_names(kb: int, kp: int) -> list[str]:
    """상성 피처 이름: 타선 유형 비중 차이 K_b개 + 선발 유형 원-핫 차이 K_p개 + 유형 정보 충분 여부."""
    return [f"bat_type{t}_diff" for t in range(kb)] + [f"starter_type{t}_diff" for t in range(kp)] + ["types_known"]


TYPES_KNOWN_MIN_SHARE = 0.5  # types_known: 양 팀 모두 타석의 이 비율 이상이 유형 있는 타자여야 한다

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
        "pa_by_player": Counter(),                        # 당해 시즌 타자별 타석(PA = AB+BB+HBP) — 상성 피처용
    }


def _new_pitcher_totals() -> dict:
    return dict.fromkeys(PIT_KEYS, 0) | {"apps": 0, "starts": 0}


def _new_pitcher() -> dict:
    # last3: 최근 선발 3경기의 (시즌, 실점). 시즌을 같이 적어 두어야 start_season에서 오래된 기록을 버릴 수 있다.
    return {"cur": _new_pitcher_totals(), "prev": _new_pitcher_totals(), "last3": deque(maxlen=3)}


class LeagueState:
    """FINAL 경기만 누적하는 리그 상태: 팀별 기록, 맞대결, 투수별 기록(당해 + 직전 시즌).
    types: (season, player_id) -> {"batter": 유형} / {"pitcher": 유형} (cluster.types_map). 주면 game_features가
    상성 피처를 붙인다. kb·kp는 타자·투수 유형 수(K). 없으면(None) 상성 피처를 만들지 않는다 (라이브 기본값)."""

    def __init__(self, types: dict[tuple[int, int], dict] | None = None, kb: int = 0, kp: int = 0) -> None:
        self.types = types
        self.kb, self.kp = int(kb), int(kp)
        self.season: int | None = None
        self._t: dict[str, dict] = defaultdict(_new_team)
        self._h2h: dict[tuple[str, str], int] = defaultdict(int)  # (승팀, 패팀) -> 당해 시즌 승수
        self._p: dict[int, dict] = defaultdict(_new_pitcher)

    def start_season(self, season: int) -> None:
        """현재 시즌 누적을 '직전 시즌'으로 넘기고 현재 시즌을 비운다.
        팀은 최종 승률만, 투수는 시즌 합계를 넘긴다 (두 시즌 전 기록은 버린다).
        투수의 최근 3선발 실점도 같은 창(직전 시즌 + 당해 시즌)만 남긴다 — season-1보다 오래된 선발은 버린다.
        그래야 직전 시즌부터만 읽는 라이브 상태(run_pipeline.build_state)와 학습 피처가 똑같아진다.
        (start_season 전에 쌓인 선발은 시즌을 모르므로(None) 그대로 둔다.)
        같은 시즌으로 두 번 불러도 아무 일 없다 (직전 시즌 기록이 지워지지 않게)."""
        if season == self.season:
            return
        self.season = season
        old = self._t
        self._t = defaultdict(_new_team)
        for code, t in old.items():
            self._t[code]["prev_win_pct"] = _pct(t["wins"], t["losses"])
        self._h2h = defaultdict(int)
        for p in self._p.values():
            p["prev"], p["cur"] = p["cur"], _new_pitcher_totals()
            p["last3"] = deque(((s, r) for s, r in p["last3"] if s is None or s >= season - 1), maxlen=3)

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
        # 타자별 타석: 팀 타선의 유형 구성(lineup_shares)에 쓴다. 팀 dict 안이라 start_season에서 함께 비워진다
        for row in batting:
            if row.get("player_id") is not None:
                t["pa_by_player"][row["player_id"]] += _num(row.get("ab")) + _num(row.get("bb")) + _num(row.get("hbp"))
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
                p["last3"].append((self.season, _num(row.get("r"))))

    def team_line(self, code: str, on: str) -> dict:
        """on('YYYY-MM-DD') 경기 직전 시점의 팀 요약. 저장된 상태를 바꾸지 않는다."""
        t = self._t.get(code) or _new_team()
        day = _date.fromisoformat(on)
        rf, ra = t["runs_for"], t["runs_against"]
        last = t["last_game_date"]
        # 분모가 0인 값(아직 경기 없음 등)은 전부 None → game_features에서 NaN
        return {
            "win_pct": _pct(t["wins"], t["losses"]),
            "last10": _ratio(sum(t["results"]), len(t["results"])),
            "run_diff": _ratio(rf - ra, t["games"]),
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

    def _prev_type(self, player_id, group: str) -> int | None:
        """직전 시즌(season-1) 유형. 유형표가 없거나 시즌이 정해지지 않았거나 그 선수-시즌 유형이 없으면 None."""
        if self.types is None or self.season is None or player_id is None:
            return None
        return self.types.get((self.season - 1, player_id), {}).get(group)

    def lineup_shares(self, code: str) -> tuple[list[float] | None, float]:
        """팀 타선의 유형 구성: (유형별 비중 K_b개, 유형이 있는 타석 비중).
        유형별 비중 = '직전 시즌 유형이 있는 타자'의 당해 시즌 타석 중 유형 t 타자의 몫 (합 1).
        두 번째 값 = 당해 시즌 팀 전체 타석 중 유형이 있는 타자의 몫. 유형 있는 타석이 0이면 (None, 0.0)."""
        t = self._t.get(code)
        counts, known, total = [0] * self.kb, 0, 0
        for pid, pa in (t["pa_by_player"].items() if t else ()):
            total += pa
            ty = self._prev_type(pid, "batter")
            if ty is not None and pa:
                if not 0 <= ty < self.kb:  # 유형표와 K(kb)가 어긋나면 조용히 틀리지 말고 바로 알린다
                    raise ValueError(f"batter type {ty} of player {pid} (season {self.season - 1}) is outside "
                                     f"0..{self.kb - 1} — kb={self.kb} does not match the types table")
                counts[ty] += pa
                known += pa
        if known == 0:
            return None, 0.0
        return [c / known for c in counts], known / total

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
            "last3_runs": sum(r for _, r in p["last3"]) / len(p["last3"]) if p["last3"] else None,
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


def starter_type(state: LeagueState, player_id) -> int | None:
    """선발 투수의 직전 시즌 투수 유형 (없으면 None)."""
    return state._prev_type(player_id, "pitcher")


def _matchup_features(state: LeagueState, home: str, away: str, starters: dict | None) -> dict:
    """상성 피처 (matchup_feature_names 순서). 모두 홈 − 원정.
    - bat_type{t}_diff: 타선 유형 비중 차이. 어느 팀이라도 유형 있는 타석이 없으면 NaN (개막일 등).
    - starter_type{t}_diff: 선발 유형 원-핫 차이 (-1/0/1). 유형 없는 선발(신인·첫해 외국인 등)은 0 벡터.
    - types_known: 양 팀 모두 타석의 절반 이상이 유형 있는 타자이고, 양 선발 모두 유형이 있으면 1."""
    (h_share, h_known), (a_share, a_known) = state.lineup_shares(home), state.lineup_shares(away)
    f = {}
    for t in range(state.kb):
        f[f"bat_type{t}_diff"] = float("nan") if h_share is None or a_share is None else h_share[t] - a_share[t]
    st = {}
    for side in ("home", "away"):
        s = (starters or {}).get(side)
        st[side] = starter_type(state, s.get("player_id")) if s else None
        if st[side] is not None and not 0 <= st[side] < state.kp:  # 원-핫 밖 유형은 0 벡터로 숨지 않게
            raise ValueError(f"pitcher type {st[side]} of starter {s.get('player_id')} is outside "
                             f"0..{state.kp - 1} — kp={state.kp} does not match the types table")
    for t in range(state.kp):
        f[f"starter_type{t}_diff"] = int(st["home"] == t) - int(st["away"] == t)
    f["types_known"] = int(h_known >= TYPES_KNOWN_MIN_SHARE and a_known >= TYPES_KNOWN_MIN_SHARE
                           and st["home"] is not None and st["away"] is not None)
    return f


def _starter_line(state: LeagueState, starters: dict | None, side: str) -> dict | None:
    s = (starters or {}).get(side)
    return state.pitcher_line(s["player_id"]) if s and s.get("player_id") is not None else None


def game_features(game: dict, state: LeagueState, starters: dict | None = None) -> dict:
    """경기 하나의 피처 26개(결측은 NaN)와 사이트 표시용 팀·선발 요약.
    state.types가 있으면 상성 피처(matchup_feature_names(state.kb, state.kp))도 붙인다 — 없으면 그 키 자체가 없다."""
    home, away, on = game["home_code"], game["away_code"], game["date"]
    h, a = state.team_line(home, on), state.team_line(away, on)
    f = {
        "win_pct_diff": _diff(h["win_pct"], a["win_pct"]),
        "last10_diff": _diff(h["last10"], a["last10"]),
        "run_diff_diff": _diff(h["run_diff"], a["run_diff"]),
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
    out = {
        **{n: f[n] for n in FEATURE_NAMES},
        "home_line": h, "away_line": a, "home_starter": hs, "away_starter": as_,
    }
    if state.types is not None:
        out.update(_matchup_features(state, home, away, starters))
    return out


def regular_finals(games: list[dict], season: int) -> list[dict]:
    """상태에 넣을 경기: 정규시즌 FINAL만, (date, game_id) 순.
    학습(build_training_frame)과 라이브(scripts/run_pipeline.build_state)가 같은 필터·순서를 쓰도록 한 곳에 둔다.
    무승부·점수 없는 FINAL도 남긴다 — 행을 만들지 말지는 build_training_frame이, 상태 반영은 LeagueState.update가 정한다."""
    return [g for g in sorted(games, key=lambda g: (g["date"], g["game_id"]))
            if g["status"] == "FINAL" and is_regular(season, _date.fromisoformat(g["date"]), g["game_id"])]


def build_training_frame(
    games: list[dict], boxscores: dict[int, dict], *, season: int, state: LeagueState | None = None
) -> pd.DataFrame:
    """정규시즌 FINAL 경기를 날짜순으로 훑으며 학습 행을 만든다.
    같은 날짜 경기는 피처를 모두 계산한 뒤 상태를 갱신한다 (더블헤더 1차전 결과가 2차전에 새지 않게).
    선발은 박스스코어의 실제 선발(order==1)을 쓴다. 무승부는 행을 만들지 않지만 상태에는 반영한다.
    state를 넘기면 그 상태에 이어서 누적한다 (시즌 연결은 호출하는 쪽에서 start_season으로).
    state에 유형표(types)가 있으면 상성 열(matchup_feature_names)이 FEATURE_NAMES 뒤, y 앞에 붙는다."""
    state = state if state is not None else LeagueState()
    extra = matchup_feature_names(state.kb, state.kp) if state.types is not None else []
    rows = []
    for _, grp in groupby(regular_finals(games, season), key=lambda g: g["date"]):
        day_games = list(grp)
        for g in day_games:
            if g["home_score"] is None or g["away_score"] is None or g["home_score"] == g["away_score"]:
                continue
            f = game_features(g, state, starter_ids(boxscores.get(g["game_id"])))
            rows.append({
                "game_id": g["game_id"], "date": g["date"], "season": season,
                "home_code": g["home_code"], "away_code": g["away_code"],
                **{k: f[k] for k in FEATURE_NAMES},
                **{k: f[k] for k in extra},
                "y": int(g["home_score"] > g["away_score"]),
            })
        for g in day_games:
            state.update(g, boxscores.get(g["game_id"]))
    return pd.DataFrame(rows, columns=["game_id", "date", "season", "home_code", "away_code", *FEATURE_NAMES,
                                       *extra, "y"])


# ---------- 시즌 연결 데이터셋 + 저장 ----------

BASE_COLUMNS = ["game_id", "date", "season", "home_code", "away_code", *FEATURE_NAMES, "y"]  # features.parquet 열


def build_dataset(seasons: list[int], *, types: dict | None = None, kb: int = 0, kp: int = 0) -> pd.DataFrame:
    """시즌을 오름차순으로 이어 붙인 학습 데이터. 시즌마다 start_season으로 '직전 시즌' 기록을 넘긴다.
    행 순서는 시즌 → (date, game_id). 저장된 원본(raw_store)을 읽는다.
    types(cluster.types_map)·kb·kp를 주면 상성 열도 붙는다 (기본 26개 피처 값은 types가 있든 없든 같다)."""
    state = LeagueState(types=types, kb=kb, kp=kp)
    frames = []
    for season in sorted(set(seasons)):
        state.start_season(season)
        frames.append(build_training_frame(
            raw_store.load_games(season), raw_store.load_boxscores(season), season=season, state=state))
    return pd.concat(frames, ignore_index=True) if frames else build_training_frame([], {}, season=0, state=state)


def save_features(df: pd.DataFrame, path) -> None:
    """parquet(snappy)로 저장. 같은 DataFrame이면 같은 바이트가 나온다 (SHA256 비교용)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), path, compression="snappy")


def load_features(path) -> pd.DataFrame:
    return pq.read_table(Path(path)).to_pandas()


def features_sha256(path) -> str:
    """parquet 파일 바이트의 SHA256. 같은 플랫폼에서만 재현된다 — 다른 OS·libm에서는 pow 같은 실수 계산의
    마지막 비트가 달라 파일 바이트가 달라질 수 있다 (값 비교는 features_fingerprint)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


FINGERPRINT_DIGITS = 6


def features_fingerprint(df: pd.DataFrame) -> str:
    """플랫폼과 무관한 피처 표의 지문: 실수 열을 소수 6자리로 반올림(-0.0은 0.0으로)해
    to_csv(index=False, lineterminator="\\n", float_format="%.6f")로 쓴 텍스트의 SHA256.
    OS·BLAS·libm에 따라 1e-16 수준으로 다른 값도 같은 지문이 된다 (바이트 동일성은 같은 플랫폼에서만, 값 동일성은 플랫폼 간).
    주의(반올림 경계): 어떤 값이 소수 6자리 반올림의 경계(…5)에 1e-16만큼 붙어 있으면 플랫폼마다 반대쪽으로 반올림돼
    지문이 달라질 수 있다 — 드물지만 0은 아니다. 그때는 parity가 실패하고 그 열을 직접 비교해 봐야 한다.
    열 순서·행 순서·결측(빈 칸)·정수 값은 그대로 지문에 들어간다."""
    out = df.copy()
    floats = out.select_dtypes(include="floating").columns
    out[floats] = out[floats].round(FINGERPRINT_DIGITS) + 0.0   # + 0.0: -0.0 → 0.0
    text = out.to_csv(index=False, lineterminator="\n", float_format=f"%.{FINGERPRINT_DIGITS}f")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parquet_fingerprint(path) -> str:
    """parquet 파일을 읽어 features_fingerprint (manifest의 features_fingerprint · matchup_fingerprint)."""
    return features_fingerprint(load_features(path))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="전 시즌 피처 데이터셋을 만들어 parquet로 저장")
    ap.add_argument("--out", help="기본 피처(26개) parquet 경로 (예: data/processed/features.parquet)")
    ap.add_argument("--matchup-out", help="상성 피처 parquet 경로 (game_id + 상성 열만). --clusters의 유형을 쓴다")
    ap.add_argument("--clusters", default="models/clusters.pkl", help="--matchup-out에 쓸 군집 묶음 pkl")
    ap.add_argument("--seasons", nargs=2, type=int, metavar=("START", "END"), help="시즌 범위 (기본: 있는 시즌 전부)")
    args = ap.parse_args(argv)
    if not args.out and not args.matchup_out:
        ap.error("--out 또는 --matchup-out 중 하나는 있어야 합니다")
    seasons = raw_store.available_seasons()
    if args.seasons:
        seasons = [s for s in seasons if args.seasons[0] <= s <= args.seasons[1]]
    t0 = time.time()
    kb = kp = 0
    if args.matchup_out:
        from . import cluster  # cluster → train_win → features 순환 import를 피하려고 여기서 읽는다

        obj = cluster.load_bundle(args.clusters)
        kb, kp = obj["batter"]["bundle"]["k"], obj["pitcher"]["bundle"]["k"]
        df = build_dataset(seasons, types=cluster.types_map(obj), kb=kb, kp=kp)
    else:
        df = build_dataset(seasons)
    print(f"rows: {len(df)}  ({time.time() - t0:.1f}s)")
    for season, n in df.groupby("season").size().items():
        print(f"  {season}: {n}")
    if args.out:
        save_features(df[BASE_COLUMNS], args.out)  # 상성 열은 빼고 기존 열만 → 유형 유무와 관계없이 같은 바이트
        print(f"sha256: {features_sha256(args.out)}  fingerprint: {parquet_fingerprint(args.out)}")
    if args.matchup_out:
        names = matchup_feature_names(kb, kp)
        save_features(df[["game_id", *names]], args.matchup_out)
        print(f"matchup: {len(names)} cols, types_known mean={df['types_known'].mean():.3f}  "
              f"sha256: {features_sha256(args.matchup_out)}  fingerprint: {parquet_fingerprint(args.matchup_out)}")


if __name__ == "__main__":
    main()
