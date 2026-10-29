"""박스스코어 -> 선수·시즌 집계표 (선수 유형 군집화의 입력). 정규시즌 FINAL + 박스스코어 있는 경기만 센다."""
from collections import Counter

import pandas as pd

from . import raw_store
from .features import _num, regular_finals

BATTING_SUM = ("ab", "r", "h", "hr", "rbi", "bb", "so", "hbp", "doubles", "triples", "sb")
PITCHING_SUM = ("ip_outs", "np", "r", "er", "h", "hr", "so", "bb", "hbp")
NAME_MIN_SHARE = 0.6


def _season_boxes(season: int):
    """정규시즌 FINAL 경기의 박스스코어를 (date, game_id) 순으로 낸다. 박스스코어 없는 경기는 건너뛴다."""
    boxes = raw_store.load_boxscores(season)
    for g in regular_finals(raw_store.load_games(season), season):
        box = boxes.get(g["game_id"])
        if box is not None:
            yield box


def _team_of(teams: Counter, last_team: str) -> str:
    """출전 경기가 가장 많은 팀. 동률이면 마지막 출전 팀."""
    top = max(teams.values())
    return last_team if teams[last_team] == top else max(teams, key=teams.get)


def _aggregate(seasons, side_key: str, keys: tuple[str, ...]) -> list[dict]:
    """(시즌, 선수)별로 줄을 모은다. 날짜순으로 훑으므로 name/last_team은 마지막 출전 값이 된다."""
    acc: dict[tuple[int, int], dict] = {}
    for season in seasons:
        for box in _season_boxes(season):
            for side in ("away", "home"):
                team = box[side]["code"]
                for row in box[side_key][side]:
                    a = acc.setdefault((season, row["player_id"]), {
                        "season": season, "player_id": row["player_id"], "games": 0, "teams": Counter(),
                        "pos": Counter(), "sums": dict.fromkeys(keys, 0), "rec": 0, "starts": 0})
                    a["games"] += 1
                    a["name"], a["last_team"] = row["name"], team
                    a["teams"][team] += 1
                    if row.get("pos"):
                        a["pos"][row["pos"]] += 1
                    if row.get("doubles") is not None:
                        a["rec"] += 1
                    if row.get("order") == 1:
                        a["starts"] += 1
                    for k in keys:
                        a["sums"][k] += _num(row.get(k))
    return [acc[k] for k in sorted(acc)]


def batting_seasons(seasons: list[int]) -> pd.DataFrame:
    """타자 시즌표. pa = ab + bb + hbp. games_with_records = doubles 기록이 있는 경기 수."""
    rows = []
    for a in _aggregate(seasons, "batting", BATTING_SUM):
        s = a["sums"]
        rows.append({"season": a["season"], "player_id": a["player_id"], "name": a["name"],
                     "team": _team_of(a["teams"], a["last_team"]),
                     "pos": max(a["pos"], key=a["pos"].get) if a["pos"] else None,   # 동률이면 먼저 나온 포지션
                     "games": a["games"], "games_with_records": a["rec"],
                     "pa": s["ab"] + s["bb"] + s["hbp"], **s})
    cols = ["season", "player_id", "name", "team", "pos", "games", "games_with_records", "pa", *BATTING_SUM]
    return pd.DataFrame(rows, columns=cols)


def pitching_seasons(seasons: list[int]) -> pd.DataFrame:
    """투수 시즌표. bf = ip_outs + h + bb + hbp, starts = 선발(order 1) 등판 수."""
    rows = []
    for a in _aggregate(seasons, "pitching", PITCHING_SUM):
        s = a["sums"]
        rows.append({"season": a["season"], "player_id": a["player_id"], "name": a["name"],
                     "team": _team_of(a["teams"], a["last_team"]),
                     "games": a["games"], "starts": a["starts"],
                     "bf": s["ip_outs"] + s["h"] + s["bb"] + s["hbp"], **s})
    cols = ["season", "player_id", "name", "team", "games", "starts", "bf", *PITCHING_SUM]
    return pd.DataFrame(rows, columns=cols)


def korean_names(seasons: list[int]) -> dict[int, str]:
    """모든 박스스코어의 names_ko 투표. 최빈 이름이 득표의 60% 이상이면 채택, 동률은 가나다 순 첫 값."""
    votes: dict[int, Counter] = {}
    for season in seasons:
        for box in raw_store.load_boxscores(season).values():
            for pid, name in (box.get("names_ko") or {}).items():
                votes.setdefault(int(pid), Counter())[name] += 1
    out = {}
    for pid, c in votes.items():
        top = max(c.values())
        if top / sum(c.values()) >= NAME_MIN_SHARE:
            out[pid] = min(n for n, v in c.items() if v == top)
    return out
