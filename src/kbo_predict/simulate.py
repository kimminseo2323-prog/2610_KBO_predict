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
OUTLOOK_DIGITS = 4   # outlook_for가 내보내는 playoff_prob · exp_wins의 소수 자리 (JSON 크기·가독성)

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


def _playoff_credit(win_pct: np.ndarray) -> np.ndarray:
    """[sims, 팀] 승률 → [sims, 팀] 진출 몫 (0~1). 행마다 몫의 합은 정확히 PLAYOFF_SPOTS (팀이 그보다 많을 때).
    같은 승률 묶음이 순위 lo..hi를 차지하면(lo = 최소 순위, hi = 최대 순위) 각 팀의 몫은
    clip((PLAYOFF_SPOTS - lo + 1) / (hi - lo + 1), 0, 1) — 묶음 안에 남은 진출 자리를 똑같이 나눈다.
    예: 4~6위 3팀 동률 → 2자리/3팀 = 각 2/3, 5·6위 2팀 동률 → 각 0.5, 단독 7위 → 0."""
    lo = rankdata(-win_pct, method="min", axis=-1)
    hi = rankdata(-win_pct, method="max", axis=-1)
    return np.clip((PLAYOFF_SPOTS - lo + 1) / (hi - lo + 1), 0.0, 1.0)


def playoff_race(standings: dict[str, tuple[int, int]], remaining: list[tuple[str, str, float]], *,
                 n_sims: int = N_SIMS, seed: int = SEED) -> dict[str, dict]:
    """남은 경기를 n_sims번 굴려 팀별 5위 안 진출 확률을 낸다.
    standings[code] = (승, 패) — 지금까지의 정규시즌 성적. remaining = [(홈, 원정, P(홈 승))].
    순위는 승률 내림차순. 동률이 진출선(5위)에 걸치면 남은 자리를 동률 팀끼리 나눠 갖는다(_playoff_credit) —
    그래서 시뮬레이션마다 정확히 PLAYOFF_SPOTS 자리가 배분되고, 진출 확률의 합은 항상 5다.
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

    made = _playoff_credit(_win_pct(wins, losses)).mean(axis=0)
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


def _normalise(entry: dict) -> dict:
    """YAML 시리즈 한 줄 → {"name", "teams": [코드|None, 코드|None], "best_of", "start": 'YYYY-MM-DD'|None,
    "homes": [...]|None}. 날짜 객체는 문자열로 바꾼다. 이미 정리된 줄을 다시 넣어도 그대로 나온다."""
    return {
        "name": entry["name"],
        "teams": list(entry.get("teams") or [None, None]),
        "best_of": int(entry["best_of"]),
        "start": _iso(entry.get("start")),
        "homes": list(entry["homes"]) if entry.get("homes") else None,
    }


def _season_entries(data: dict, season: int) -> list:
    """YAML 전체 dict(시즌 → 목록)에서 그 시즌 목록. 키가 정수든 문자열이든 받는다."""
    return list(data.get(season) or data.get(str(season)) or [])


def load_postseason(season: int, path=POSTSEASON_YAML) -> list[dict]:
    """config/postseason.yaml에서 그 시즌의 시리즈 목록(_normalise 모양). 시즌이 없으면(또는 파일이 없으면) 빈 목록."""
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [_normalise(e) for e in _season_entries(data, season)]


def _series_list(season: int, ps_config) -> list[dict]:
    """ps_config: load_postseason 결과(list) 또는 시즌 → 목록 dict(yaml.safe_load 그대로) 또는 None.
    어느 쪽이든 줄마다 _normalise를 거친다 (YAML 날짜 객체와 문자열 날짜를 비교하다 깨지지 않게)."""
    if ps_config is None:
        return []
    entries = _season_entries(ps_config, season) if isinstance(ps_config, dict) else list(ps_config)
    return [_normalise(e) for e in entries]


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


def _pair_games(games: list[dict], s: dict) -> list[dict]:
    """시리즈 두 팀의 start 이후 맞대결 (날짜·game_id 순)."""
    pair = {s["teams"][0], s["teams"][1]}
    return sorted((g for g in games if g["date"] >= s["start"] and {g["home_code"], g["away_code"]} == pair),
                  key=lambda g: (g["date"], g["game_id"]))


def _series_record(games: list[dict], s: dict, on: str) -> tuple[int, int, int]:
    """시리즈 전적: start ≤ 날짜 < on인 두 팀 맞대결 FINAL의 (팀0 승, 팀1 승, 무승부).
    on 당일 경기는 이미 FINAL이어도 세지 않는다 — 전망은 '그날 경기 전' 카드다 (playoff_race와 같은 기준,
    리와인드에서 그날 결과가 그날 전망에 새지 않게). 점수 없는 FINAL은 세지 않는다."""
    t0 = s["teams"][0]
    w0 = w1 = draws = 0
    for g in _pair_games(games, s):
        if g["status"] != "FINAL" or g["date"] >= on:
            continue
        hs, as_ = g["home_score"], g["away_score"]
        if hs is None or as_ is None:
            continue
        if hs == as_:
            draws += 1
            continue
        if (g["home_code"] if hs > as_ else g["away_code"]) == t0:
            w0 += 1
        else:
            w1 += 1
    return w0, w1, draws


def _decided(s: dict, w0: int, w1: int) -> bool:
    need = s["best_of"] // 2 + 1
    return w0 >= need or w1 >= need


def _active_series(season: int, on: str, games: list[dict], ps_config) -> dict | None:
    """on 시점에 진행 중인 등록 시리즈: 두 팀이 정해졌고 start ≤ on이며 on 전날까지 아직 승부가 안 난 것.
    그날 경기가 없어도(이동일·휴식일) 진행 중이면 고른다. 여럿이면 가장 늦게 시작한 것."""
    found = None
    for s in _series_list(season, ps_config):
        t0, t1 = s["teams"]
        if t0 is None or t1 is None or s["start"] is None or s["start"] > on:
            continue
        w0, w1, _ = _series_record(games, s, on)
        if _decided(s, w0, w1):
            continue
        if found is None or s["start"] >= found["start"]:
            found = s
    return found


def _series_outlook(s: dict, on: str, games: list[dict], state, team_bundle, n_sims: int, seed: int) -> dict:
    t0, t1 = s["teams"]
    w0, w1, draws = _series_record(games, s, on)
    n_left = 0 if _decided(s, w0, w1) else s["best_of"] - w0 - w1
    # 홈 순서: 이미 치른 경기(승패 + 무승부) 수만큼 앞을 건너뛴다. 무승부로 경기가 늘어 homes가 모자라면
    # 마지막 경기의 홈(최종전 홈)이 이어서 홈을 맡는다고 본다.
    all_homes = _homes(s)
    left_homes = (all_homes[w0 + w1 + draws:] + [all_homes[-1]] * n_left)[:n_left]
    # 남은 경기 각각의 P(팀0 승): 홈팀 기준 모델 확률을 팀0 기준으로 뒤집는다. 날짜는 모두 오늘(on)로 둔다.
    pairs = [{"home_code": h, "away_code": t1 if h == t0 else t0, "date": on} for h in left_homes]
    p_home = game_probs(team_bundle, pairs, state)
    p_t0 = [p if h == t0 else 1.0 - p for h, p in zip(left_homes, p_home)]
    res = series(s["best_of"], (w0, w1), ["team0" if h == t0 else "team1" for h in left_homes], p_t0,
                 n_sims=n_sims, seed=seed)
    upcoming = [g["date"] for g in _pair_games(games, s) if g["date"] >= on and g["status"] != "CANCELED"]
    return {"type": "series", "as_of": on, "name": s["name"], "best_of": s["best_of"], "teams": [t0, t1],
            "wins": [w0, w1], "win_prob": res["win_prob"], "most_common_result": res["most_common_result"],
            "goes_distance_prob": res["goes_distance_prob"], "games_remaining_max": res["games_remaining_max"],
            "next_game_date": upcoming[0] if upcoming else None}


def outlook_for(season: int, on: str, games: list[dict], *, state, team_bundle: dict, ps_config,
                n_sims: int = N_SIMS, seed: int = SEED) -> dict:
    """on('YYYY-MM-DD') 날짜의 전망 카드 데이터 — 모든 종류가 '그날 경기 전' 기준이다.
    games = 그 시즌 경기 전부(raw_store.load_games(season)).
    state = on 경기 직전 리그 상태(run_pipeline.build_state(season, on)), team_bundle = 선발 없는 팀 모델 번들,
    ps_config = load_postseason(season) 결과, 시즌 → 목록 dict(yaml.safe_load 그대로), 또는 None.
    남은 경기의 확률은 정규시즌·시리즈 모두 on에 고정한 상태로, 경기 날짜도 on으로 바꿔 낸다
    (미래 날짜를 넣으면 휴식일 같은 피처가 날짜만으로 커진다).
    - 정규시즌 날짜: {"type": "playoff_race", "as_of", "teams": {code: {"playoff_prob", "rank_now", "exp_wins",
      "wins", "losses"}}} — 10팀 전부 (사이트가 오늘 경기 팀을 고른다). playoff_prob·exp_wins는 소수 4자리
      (그래서 10팀 playoff_prob의 합은 5에서 반올림 오차만큼 벗어날 수 있다).
    - 진행 중인(아직 승부 안 난) 등록 시리즈가 있으면 — 그날 경기가 없어도: {"type": "series", "as_of", "name",
      "best_of", "teams", "wins", "win_prob", "most_common_result", "goes_distance_prob", "games_remaining_max",
      "next_game_date"}.
    - 그 밖: {"type": "next_game", "as_of", "next_game_date": on 다음 경기 날짜(취소 제외) 또는 None}."""
    if is_regular(season, _date.fromisoformat(on)):
        standings = _standings(games, season, on)
        left = _remaining_regular(games, season, on)
        probs = game_probs(team_bundle, [{**g, "date": on} for g in left], state)
        race = playoff_race(standings, [(g["home_code"], g["away_code"], p) for g, p in zip(left, probs)],
                            n_sims=n_sims, seed=seed)
        # 발행 경계에서만 소수 4자리로 줄인다 (playoff_race 자체는 반올림하지 않는다 — 합 5 검증 등)
        return {"type": "playoff_race", "as_of": on,
                "teams": {c: {**race[c], "playoff_prob": round(race[c]["playoff_prob"], OUTLOOK_DIGITS),
                              "exp_wins": round(race[c]["exp_wins"], OUTLOOK_DIGITS),
                              "wins": standings[c][0], "losses": standings[c][1]} for c in standings}}
    s = _active_series(season, on, games, ps_config)
    if s is not None:
        return _series_outlook(s, on, games, state, team_bundle, n_sims, seed)
    later = sorted(g["date"] for g in games if g["date"] > on and g["status"] != "CANCELED")
    return {"type": "next_game", "as_of": on, "next_game_date": later[0] if later else None}
