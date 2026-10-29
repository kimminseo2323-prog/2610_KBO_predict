"""박스스코어 -> 선수·시즌 집계표 (선수 유형 군집화의 입력). 정규시즌 FINAL + 박스스코어 있는 경기만 센다."""
from collections import Counter

import pandas as pd

from . import raw_store
from .features import _num, regular_finals

BATTING_SUM = ("ab", "r", "h", "hr", "rbi", "bb", "so", "hbp", "doubles", "triples", "sb")
PITCHING_SUM = ("ip_outs", "np", "r", "er", "h", "hr", "so", "bb", "hbp")
NAME_MIN_SHARE = 0.6
NAME_RECENT_MIN_VOTES = 3                # 이 이상 표가 있는 가장 최근 시즌의 이름을 쓴다


def _season_boxes(season: int):
    """정규시즌 FINAL 경기의 (game_id, 박스스코어)를 (date, game_id) 순으로 낸다. 박스스코어 없는 경기는 건너뛴다."""
    boxes = raw_store.load_boxscores(season)
    for g in regular_finals(raw_store.load_games(season), season):
        box = boxes.get(g["game_id"])
        if box is not None:
            yield g["game_id"], box


def _team_of(teams: dict[str, list[int]]) -> str:
    """teams: 팀 -> [출전 경기 수, 마지막 출전 경기 순번]. 출전 경기가 가장 많은 팀, 동률이면 가장 최근에 출전한 팀."""
    return max(teams, key=lambda t: (teams[t][0], teams[t][1]))


def _aggregate(seasons, side_key: str, keys: tuple[str, ...]) -> list[dict]:
    """(시즌, 선수)별로 줄을 모은다. 날짜순으로 훑으므로 name은 마지막 출전 경기의 이름이 된다.
    경기 수(games·games_with_records·starts·팀별 출전)는 game_id 단위로 센다 — 한 경기에 같은 선수 줄이
    둘 있어도 1경기다. 기록 합계(sums)는 줄마다 더한다."""
    acc: dict[tuple[int, int], dict] = {}
    idx = 0                                  # 전체 경기 순번 (팀 동률 때 '가장 최근' 판정용)
    for season in seasons:
        for gid, box in _season_boxes(season):
            idx += 1
            for side in ("away", "home"):
                team = box[side]["code"]
                for row in box[side_key][side]:
                    a = acc.setdefault((season, row["player_id"]), {
                        "season": season, "player_id": row["player_id"], "games": set(), "teams": {},
                        "pos": Counter(), "sums": dict.fromkeys(keys, 0), "rec": set(), "starts": set()})
                    new_game = gid not in a["games"]
                    a["games"].add(gid)
                    a["name"] = row["name"]
                    t = a["teams"].setdefault(team, [0, 0])
                    t[0] += new_game
                    t[1] = idx
                    if row.get("pos"):
                        a["pos"][row["pos"]] += 1
                    if row.get("doubles") is not None:
                        a["rec"].add(gid)
                    if row.get("order") == 1:
                        a["starts"].add(gid)
                    for k in keys:
                        a["sums"][k] += _num(row.get(k))
    return [acc[k] for k in sorted(acc)]


def batting_seasons(seasons: list[int]) -> pd.DataFrame:
    """타자 시즌표. pa = ab + bb + hbp. games_with_records = doubles 기록이 있는 경기 수."""
    rows = []
    for a in _aggregate(seasons, "batting", BATTING_SUM):
        s = a["sums"]
        rows.append({"season": a["season"], "player_id": a["player_id"], "name": a["name"],
                     "team": _team_of(a["teams"]),
                     "pos": max(a["pos"], key=a["pos"].get) if a["pos"] else None,   # 동률이면 먼저 나온 포지션
                     "games": len(a["games"]), "games_with_records": len(a["rec"]),
                     "pa": s["ab"] + s["bb"] + s["hbp"], **s})
    cols = ["season", "player_id", "name", "team", "pos", "games", "games_with_records", "pa", *BATTING_SUM]
    return pd.DataFrame(rows, columns=cols)


def pitching_seasons(seasons: list[int]) -> pd.DataFrame:
    """투수 시즌표. bf = ip_outs + h + bb + hbp, starts = 선발(order 1) 등판 수."""
    rows = []
    for a in _aggregate(seasons, "pitching", PITCHING_SUM):
        s = a["sums"]
        rows.append({"season": a["season"], "player_id": a["player_id"], "name": a["name"],
                     "team": _team_of(a["teams"]),
                     "games": len(a["games"]), "starts": len(a["starts"]),
                     "bf": s["ip_outs"] + s["h"] + s["bb"] + s["hbp"], **s})
    cols = ["season", "player_id", "name", "team", "games", "starts", "bf", *PITCHING_SUM]
    return pd.DataFrame(rows, columns=cols)


def _majority(c: Counter) -> str | None:
    """최빈 이름이 득표의 NAME_MIN_SHARE(60%) 이상이면 그 이름, 아니면 None. 동률은 가나다 순 첫 값."""
    top = max(c.values())
    if top / sum(c.values()) < NAME_MIN_SHARE:
        return None
    return min(n for n, v in c.items() if v == top)


def korean_names(seasons: list[int]) -> dict[int, str]:
    """선수 player_id -> 한글 이름. 박스스코어의 names_ko를 시즌별로 투표한다.
    규칙: 득표가 NAME_RECENT_MIN_VOTES(3) 이상인 시즌 중 가장 최근 시즌의 최빈 이름이 그 시즌 득표의 60% 이상이면 채택.
        (개명한 선수 — 예: 한동민 -> 한유섬 — 는 옛 이름 표가 많이 쌓여 전체 합으로는 60%를 못 넘으므로
        최근 시즌 이름을 쓴다.) 3표 이상인 시즌이 하나도 없으면 모든 시즌 표를 합쳐 같은 60% 규칙을 쓴다.
    동률은 가나다 순 첫 값. 60%를 못 넘으면 이름 없음(그 선수는 목록에서 빠진다)."""
    votes: dict[int, dict[int, Counter]] = {}
    for season in seasons:
        for box in raw_store.load_boxscores(season).values():
            for pid, name in (box.get("names_ko") or {}).items():
                votes.setdefault(int(pid), {}).setdefault(season, Counter())[name] += 1
    out = {}
    for pid, by_season in votes.items():
        recent = [s for s, c in by_season.items() if sum(c.values()) >= NAME_RECENT_MIN_VOTES]
        if recent:
            name = _majority(by_season[max(recent)])
        else:
            name = _majority(sum(by_season.values(), Counter()))
        if name is not None:
            out[pid] = name
    return out
