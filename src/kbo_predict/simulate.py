"""몬테카를로 시뮬레이션: 가을야구(정규시즌 5위 안) 진출 확률과 포스트시즌 시리즈 승리 확률.

사이트의 '전망(outlook)' 카드(스펙 §8)에 들어갈 값을 만든다. outlook_for가 날짜를 보고 셋 중 하나를 고른다.
- 정규시즌 날짜 → playoff_race: 남은 정규시즌 경기를 N_SIMS번 굴려 10팀 각각의 5위 안 진출 확률.
- 포스트시즌 날짜이고 오늘 경기가 config/postseason.yaml의 시리즈면 → series: 그 시리즈의 승리 확률.
- 그 밖(시범경기 · 등록 안 된 대진 · 경기 없는 날) → next_game: 다음 경기 날짜만.

경기 하나의 홈 승률은 선발 없는 팀 모델(models/team-2026.pkl, 팀 피처 19개)로 낸다. 남은 경기들은 선발을 모르므로
이 모델이 맞다. 상태(state)는 '그날 경기 직전' 리그 상태 하나로 고정한다 — 시뮬레이션 안에서 결과에 따라
승률을 다시 계산하지 않는다(단순화). 그래서 미래 경기의 결과가 피처에 새지 않는다.

결정성: numpy.random.default_rng(seed)로 같은 입력이면 항상 같은 결과. 난수는 한 번에 행렬로 뽑는다(벡터화).
I/O는 load_postseason(설정 파일 읽기)뿐이다. 경기 목록·상태·모델은 호출하는 쪽이 넘긴다.
"""
from collections import Counter
from datetime import date as _date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import rankdata

from . import teams, train_win
from .features import game_features, regular_finals
from .seasons import is_regular

N_SIMS = 10_000      # 시뮬레이션 횟수
SEED = 42            # 난수 시드 (같은 날 같은 입력 → 같은 확률)
PLAYOFF_SPOTS = 5    # 가을야구에 나가는 정규시즌 순위 (1~5위)

POSTSEASON_YAML = Path(__file__).resolve().parents[2] / "config" / "postseason.yaml"   # 어디서 실행해도 같은 파일

# 10개 구단 코드 (옛 구단명은 같은 코드로 이어지므로 중복을 뺀다). 순서는 teams.TEAMS에 처음 나온 순서.
TEAM_CODES: list[str] = list(dict.fromkeys(info["code"] for info in teams.TEAMS.values()))


# ---------- 경기별 홈 승률 ----------

def game_probs(bundle: dict, games: list[dict], state) -> list[float]:
    """각 경기(home_code · away_code · date가 있는 dict)의 P(홈 승)을 팀 모델로 낸다.
    선발은 모르므로 starters=None (선발 피처는 NaN이지만 팀 모델은 bundle["features"]의 팀 피처만 읽는다)."""
    if not games:
        return []
    rows = [game_features(g, state, starters=None) for g in games]
    X = pd.DataFrame([{k: r[k] for k in bundle["features"]} for r in rows], columns=bundle["features"])
    return [float(p) for p in train_win.predict_proba(bundle, X)]


# ---------- 가을야구 진출 확률 ----------

def _win_pct(wins: np.ndarray, losses: np.ndarray) -> np.ndarray:
    """승률 = 승 / (승 + 패). 무승부는 빠진다. 승패가 갈린 경기가 없으면 0.5로 본다(순위 계산용)."""
    decided = wins + losses
    return np.where(decided > 0, wins / np.maximum(decided, 1), 0.5)


def playoff_race(standings: dict[str, tuple[int, int]], remaining: list[tuple[str, str, float]], *,
                 n_sims: int = N_SIMS, seed: int = SEED) -> dict[str, dict]:
    """남은 경기를 n_sims번 굴려 팀별 5위 안 진출 확률을 낸다.
    standings[code] = (승, 패) — 지금까지의 정규시즌 성적. remaining = [(홈, 원정, P(홈 승))].
    순위는 승률 내림차순. 동률은 scipy.stats.rankdata(method="average")처럼 평균 순위를 준다
    (예: 5·6위 동률이면 둘 다 5.5위 → 둘 다 탈락). 순위 ≤ PLAYOFF_SPOTS이면 진출.
    반환: code -> {"playoff_prob": 진출 확률, "rank_now": 현재 순위(동률은 같은 최소 순위), "exp_wins": 기대 최종 승수}."""
    codes = list(standings)
    idx = {c: i for i, c in enumerate(codes)}
    w0 = np.array([standings[c][0] for c in codes], dtype=float)
    l0 = np.array([standings[c][1] for c in codes], dtype=float)

    # 현재 순위: 같은 승률 규칙, 동률은 같은 (가장 높은) 순위
    rank_now = rankdata(-_win_pct(w0, l0), method="min").astype(int)

    if remaining:
        rng = np.random.default_rng(seed)
        p = np.array([r[2] for r in remaining], dtype=float)
        home_win = rng.random((n_sims, len(remaining))) < p             # [sims, 경기] 홈팀이 이겼나
        # 경기 → 팀 지시 행렬: 홈 승이면 홈팀 +1승·원정팀 +1패, 홈 패면 그 반대
        H = np.zeros((len(remaining), len(codes)), dtype=np.float32)
        A = np.zeros_like(H)
        for g, (home, away, _) in enumerate(remaining):
            H[g, idx[home]] = 1
            A[g, idx[away]] = 1
        hw = home_win.astype(np.float32)
        hl = 1 - hw
        wins = w0 + hw @ H + hl @ A                                         # [sims, 팀] 최종 승
        losses = l0 + hl @ H + hw @ A                                       # [sims, 팀] 최종 패
    else:
        wins, losses = w0[None, :], l0[None, :]                            # 남은 경기 없음 → 지금 순위 그대로

    ranks = rankdata(-_win_pct(wins, losses), method="average", axis=1)    # 시뮬레이션마다 평균 순위
    made = (ranks <= PLAYOFF_SPOTS).mean(axis=0)
    exp_wins = wins.mean(axis=0)
    return {c: {"playoff_prob": float(made[i]), "rank_now": int(rank_now[i]), "exp_wins": float(exp_wins[i])}
            for i, c in enumerate(codes)}


# ---------- 시리즈 승리 확률 ----------

def series(best_of: int, wins: tuple[int, int], remaining_homes: list[str], p_home_for_team0: list[float], *,
           n_sims: int = N_SIMS, seed: int = SEED) -> dict:
    """best_of판 (best_of//2+1)선승 시리즈를 지금 전적 wins = (팀0 승, 팀1 승)에서 n_sims번 끝까지 굴린다.
    remaining_homes[i]: 남은 i번째 경기의 홈 ("team0"/"team1"), p_home_for_team0[i]: 그 경기에서 팀0이 이길 확률.
    두 목록의 길이는 '남을 수 있는 최대 경기 수' = best_of - w0 - w1 이어야 한다 (아니면 ValueError).
    반환: {"win_prob": [팀0, 팀1], "most_common_result": 가장 흔한 최종 전적 "w0-w1"(팀0 기준),
           "goes_distance_prob": 남은 경기를 전부 치르는 비율, "games_remaining_max": 최대 남은 경기 수}.
    이미 한 팀이 과반을 이겼으면 확률 1/0, 남은 경기 0, 최종 전적은 지금 전적."""
    if best_of < 1 or best_of % 2 == 0:
        raise ValueError(f"best_of must be a positive odd number, got {best_of}")
    need = best_of // 2 + 1
    w0, w1 = int(wins[0]), int(wins[1])
    if w0 >= need or w1 >= need:                                  # 이미 끝난 시리즈
        return {"win_prob": [1.0, 0.0] if w0 >= need else [0.0, 1.0], "most_common_result": f"{w0}-{w1}",
                "goes_distance_prob": 0.0, "games_remaining_max": 0}
    n_left = best_of - w0 - w1
    if len(remaining_homes) != n_left or len(p_home_for_team0) != n_left:
        raise ValueError(f"remaining_homes ({len(remaining_homes)}) and p_home_for_team0 ({len(p_home_for_team0)}) "
                         f"must both have best_of - w0 - w1 = {n_left} entries")
    bad = [h for h in remaining_homes if h not in ("team0", "team1")]
    if bad:
        raise ValueError(f"remaining_homes entries must be 'team0' or 'team1', got {bad}")

    rng = np.random.default_rng(seed)
    t0_win = rng.random((n_sims, n_left)) < np.asarray(p_home_for_team0, dtype=float)   # [sims, 경기]
    c0 = w0 + np.cumsum(t0_win, axis=1)                            # 경기마다 누적 팀0 승
    c1 = w1 + np.cumsum(~t0_win, axis=1)                           # 경기마다 누적 팀1 승
    done = (c0 >= need) | (c1 >= need)
    end = done.argmax(axis=1)                                      # 시리즈가 끝나는 경기 (홀수 best_of라 반드시 끝난다)
    rows = np.arange(n_sims)
    f0, f1 = c0[rows, end], c1[rows, end]                          # 최종 전적
    p0, p1 = float((f0 >= need).mean()), float((f1 >= need).mean())   # 1 - p0 대신 따로 세서 0.4721 꼴로 깔끔하게
    # 가장 흔한 최종 전적 (동수면 Counter가 먼저 본 것 — 시드가 같으면 항상 같다)
    common = Counter(zip(f0.tolist(), f1.tolist())).most_common(1)[0][0]
    return {"win_prob": [p0, p1], "most_common_result": f"{common[0]}-{common[1]}",
            "goes_distance_prob": float((end == n_left - 1).mean()), "games_remaining_max": int(n_left)}


# ---------- 포스트시즌 설정 ----------

def _iso(v) -> str | None:
    """YAML 날짜(datetime.date) 또는 문자열 → 'YYYY-MM-DD'. 없으면 None."""
    if v is None:
        return None
    return v.isoformat() if isinstance(v, _date) else str(v)


def load_postseason(season: int, path=POSTSEASON_YAML) -> list[dict]:
    """config/postseason.yaml에서 그 시즌의 시리즈 목록. 시즌이 없으면(또는 파일이 없으면) 빈 목록.
    각 시리즈: {"name", "teams": [코드|None, 코드|None], "best_of", "start": 'YYYY-MM-DD'|None, "homes": [...]|None}."""
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for s in data.get(season) or data.get(str(season)) or []:
        out.append({
            "name": s["name"],
            "teams": list(s.get("teams") or [None, None]),
            "best_of": int(s["best_of"]),
            "start": _iso(s.get("start")),
            "homes": list(s["homes"]) if s.get("homes") else None,
        })
    return out


def _series_list(season: int, ps_config) -> list[dict]:
    """ps_config: load_postseason 결과(list) 또는 시즌 → 목록 dict(YAML 전체 모양) 또는 None."""
    if ps_config is None:
        return []
    if isinstance(ps_config, dict):
        return list(ps_config.get(season) or ps_config.get(str(season)) or [])
    return list(ps_config)


def _homes(s: dict) -> list[str]:
    """시리즈 경기별 홈 팀 코드 (best_of 개). homes가 없으면 모두 팀0 홈.
    homes의 null 칸 = 대진이 정해지기 전 '미정 팀'의 홈 → 두 팀 중 homes에 이름이 안 나오는 팀으로 채운다."""
    t0, t1 = s["teams"]
    homes = list(s.get("homes") or [t0] * s["best_of"])
    if len(homes) != s["best_of"]:
        raise ValueError(f"{s['name']}: homes has {len(homes)} entries, best_of is {s['best_of']}")
    named = {h for h in homes if h is not None}
    if not named <= {t0, t1}:
        raise ValueError(f"{s['name']}: homes {homes} name a team outside {s['teams']}")
    if None in homes:
        missing = {t0, t1} - named
        if len(missing) != 1:
            raise ValueError(f"{s['name']}: cannot fill null homes {homes} for teams {s['teams']}")
        fill = missing.pop()
        homes = [fill if h is None else h for h in homes]
    return homes


# ---------- outlook ----------

def _standings(games: list[dict], season: int, on: str) -> dict[str, tuple[int, int]]:
    """on 전날까지의 정규시즌 성적 (승, 패). 무승부·점수 없는 경기는 승패에 안 들어간다. 10팀 모두 포함."""
    rec = {c: [0, 0] for c in TEAM_CODES}
    for g in regular_finals(games, season):
        if g["date"] >= on or g["home_score"] is None or g["away_score"] is None:
            continue
        if g["home_score"] == g["away_score"]:
            continue
        winner, loser = ((g["home_code"], g["away_code"]) if g["home_score"] > g["away_score"]
                         else (g["away_code"], g["home_code"]))
        rec.setdefault(winner, [0, 0])[0] += 1
        rec.setdefault(loser, [0, 0])[1] += 1
    return {c: (w, l) for c, (w, l) in rec.items()}


def _remaining_regular(games: list[dict], season: int, on: str) -> list[dict]:
    """on 시점에 아직 안 치른 정규시즌 경기: on 이후(당일 포함) 경기 전부 + on 전인데 FINAL이 아닌 경기
    (중단·미갱신 LIVE 등 — 결과를 모르므로 굴린다). 취소(CANCELED) 경기는 재편성 경기가 따로 있으므로 뺀다.
    on 이후에 실제로 끝난 경기도 '안 치른 경기'로 본다 (리와인드에서 미래를 엿보지 않게)."""
    out = []
    for g in sorted(games, key=lambda g: (g["date"], g["game_id"])):
        if g["status"] == "CANCELED" or not is_regular(season, _date.fromisoformat(g["date"]), g["game_id"]):
            continue
        if g["date"] >= on or g["status"] != "FINAL":
            out.append(g)
    return out


def _series_wins(games: list[dict], s: dict, on: str) -> tuple[int, int]:
    """시리즈 전적: start ≤ 날짜 < on인 두 팀 맞대결 FINAL의 (팀0 승, 팀1 승). 무승부는 세지 않는다.
    on 당일 경기는 이미 FINAL이어도 세지 않는다 — 전망은 '그날 경기 전' 카드다 (playoff_race와 같은 기준,
    리와인드에서 그날 결과가 그날 전망에 새지 않게)."""
    t0, t1 = s["teams"]
    w = [0, 0]
    for g in games:
        if g["status"] != "FINAL" or not s["start"] <= g["date"] < on:
            continue
        if {g["home_code"], g["away_code"]} != {t0, t1}:
            continue
        hs, as_ = g["home_score"], g["away_score"]
        if hs is None or as_ is None or hs == as_:
            continue
        winner = g["home_code"] if hs > as_ else g["away_code"]
        w[0 if winner == t0 else 1] += 1
    return w[0], w[1]


def _active_series(season: int, on: str, games: list[dict], ps_config) -> dict | None:
    """오늘(on) 경기의 두 팀이 맞붙는, 이미 시작한(start ≤ on) 등록 시리즈. 여럿이면 가장 늦게 시작한 것."""
    today = {frozenset((g["home_code"], g["away_code"])) for g in games if g["date"] == on}
    found = None
    for s in _series_list(season, ps_config):
        t0, t1 = s["teams"]
        if t0 is None or t1 is None or s.get("start") is None or s["start"] > on:
            continue
        if frozenset((t0, t1)) in today and (found is None or s["start"] >= found["start"]):
            found = s
    return found


def _series_outlook(s: dict, on: str, games: list[dict], state, team_bundle, n_sims: int, seed: int) -> dict:
    t0, t1 = s["teams"]
    w0, w1 = _series_wins(games, s, on)
    homes = _homes(s)
    need = s["best_of"] // 2 + 1
    if w0 >= need or w1 >= need:
        left_homes = []
    else:
        left_homes = homes[w0 + w1:]          # 이미 치른 경기 수만큼 앞의 홈 순서를 건너뛴다
    # 남은 경기 각각의 P(팀0 승): 홈팀 기준 모델 확률을 팀0 기준으로 뒤집는다. 날짜는 모두 오늘(on)로 둔다.
    pairs = [{"home_code": h, "away_code": t1 if h == t0 else t0, "date": on} for h in left_homes]
    p_home = game_probs(team_bundle, pairs, state)
    p_t0 = [p if h == t0 else 1.0 - p for h, p in zip(left_homes, p_home)]
    res = series(s["best_of"], (w0, w1), ["team0" if h == t0 else "team1" for h in left_homes], p_t0,
                 n_sims=n_sims, seed=seed)
    return {"type": "series", "as_of": on, "name": s["name"], "best_of": s["best_of"], "teams": [t0, t1],
            "wins": [w0, w1], "win_prob": res["win_prob"], "most_common_result": res["most_common_result"],
            "goes_distance_prob": res["goes_distance_prob"], "games_remaining_max": res["games_remaining_max"]}


def outlook_for(season: int, on: str, games: list[dict], *, state, team_bundle: dict, ps_config,
                n_sims: int = N_SIMS, seed: int = SEED) -> dict:
    """on('YYYY-MM-DD') 날짜의 전망 카드 데이터. games = 그 시즌 경기 전부(raw_store.load_games(season)).
    state = on 경기 직전 리그 상태(run_pipeline.build_state(season, on)), team_bundle = 선발 없는 팀 모델 번들,
    ps_config = load_postseason(season) 결과(또는 시즌 → 목록 dict, 또는 None).
    - 정규시즌 날짜: {"type": "playoff_race", "as_of", "teams": {code: {"playoff_prob", "rank_now", "exp_wins",
      "wins", "losses"}}} — 10팀 전부 (사이트가 오늘 경기 팀을 고른다).
    - 포스트시즌에 오늘 두 팀이 등록 시리즈면: {"type": "series", "as_of", "name", "best_of", "teams", "wins",
      "win_prob", "most_common_result", "goes_distance_prob", "games_remaining_max"}.
    - 그 밖: {"type": "next_game", "as_of", "next_game_date": on 다음 경기 날짜(취소 제외) 또는 None}."""
    if is_regular(season, _date.fromisoformat(on)):
        standings = _standings(games, season, on)
        left = _remaining_regular(games, season, on)
        probs = game_probs(team_bundle, left, state)
        race = playoff_race(standings, [(g["home_code"], g["away_code"], p) for g, p in zip(left, probs)],
                            n_sims=n_sims, seed=seed)
        return {"type": "playoff_race", "as_of": on,
                "teams": {c: {**race[c], "wins": standings[c][0], "losses": standings[c][1]} for c in standings}}
    s = _active_series(season, on, games, ps_config)
    if s is not None:
        return _series_outlook(s, on, games, state, team_bundle, n_sims, seed)
    later = sorted(g["date"] for g in games if g["date"] > on and g["status"] != "CANCELED")
    return {"type": "next_game", "as_of": on, "next_game_date": later[0] if later else None}
