"""simulate.py: 시리즈·가을야구 몬테카를로와 outlook_for."""
import numpy as np
import pytest
import yaml

from kbo_predict import simulate
from kbo_predict.features import LeagueState
from kbo_predict.simulate import TEAM_CODES, load_postseason, next_game_card, outlook_for, playoff_race, series


def g(date, gid, home, away, hs=None, as_=None, status="FINAL"):
    """경기 한 줄 (raw_store.load_games와 같은 모양에서 시뮬레이션이 읽는 칸만)."""
    return {"game_id": gid, "date": date, "season": int(date[:4]), "home_code": home, "away_code": away,
            "home_score": hs, "away_score": as_, "status": status}


# ---------- series ----------

def test_series_symmetric_half():
    # 5판 3선승, 1-1에서 남은 경기 모두 반반 → 승리 확률 반반.
    # 1-1에서 끝까지(남은 3경기 전부) 가려면 다음 두 경기가 1승 1패여야 하므로 정확히 0.5.
    res = series(5, (1, 1), ["team1", "team1", "team0"], [0.5] * 3)
    assert res["win_prob"][0] == pytest.approx(0.5, abs=0.02)
    assert res["win_prob"][1] == pytest.approx(0.5, abs=0.02)
    assert sum(res["win_prob"]) == pytest.approx(1.0)
    assert res["goes_distance_prob"] == pytest.approx(0.5, abs=0.02)
    assert res["games_remaining_max"] == 3
    # 0-0에서는 5차전까지 갈 확률이 C(4,2)/16 = 0.375
    res0 = series(5, (0, 0), ["team0", "team0", "team1", "team1", "team0"], [0.5] * 5)
    assert res0["goes_distance_prob"] == pytest.approx(0.375, abs=0.02)
    assert res0["win_prob"][0] == pytest.approx(0.5, abs=0.02)


def test_series_already_decided():
    res = series(5, (3, 1), [], [])
    assert res["win_prob"] == [1.0, 0.0]
    assert res["games_remaining_max"] == 0
    assert res["most_common_result"] == "3-1"
    assert res["goes_distance_prob"] == 0.0
    assert series(5, (0, 3), [], [])["win_prob"] == [0.0, 1.0]


def test_series_certain():
    res = series(5, (1, 1), ["team1", "team1", "team0"], [1.0] * 3)
    assert res["win_prob"] == [1.0, 0.0]
    assert res["most_common_result"] == "3-1"
    assert res["goes_distance_prob"] == 0.0


def test_series_length_contract():
    with pytest.raises(ValueError):
        series(5, (1, 1), ["team0"], [0.5])           # 남을 수 있는 최대 경기 수(3)와 길이가 다르다
    with pytest.raises(ValueError):
        series(4, (0, 0), ["team0"] * 4, [0.5] * 4)   # 짝수 best_of는 안 받는다


# ---------- playoff_race ----------

def _standings():
    # 승률이 모두 다른 10팀: 1위 90승 … 10위 45승 (모두 140경기)
    return {c: (90 - 5 * i, 50 + 5 * i) for i, c in enumerate(TEAM_CODES)}


def test_playoff_race_no_remaining_games():
    res = playoff_race(_standings(), [])
    for i, c in enumerate(TEAM_CODES):
        assert res[c]["playoff_prob"] == (1.0 if i < 5 else 0.0)
        assert res[c]["rank_now"] == i + 1
        assert res[c]["exp_wins"] == 90 - 5 * i


def test_playoff_race_tie_shares_remaining_spots():
    # 5·6위 2팀 동률 → 남은 1자리를 나눠 각 0.5
    st = _standings()
    st[TEAM_CODES[5]] = st[TEAM_CODES[4]]
    res = playoff_race(st, [])
    assert res[TEAM_CODES[4]]["playoff_prob"] == 0.5 and res[TEAM_CODES[5]]["playoff_prob"] == 0.5
    assert res[TEAM_CODES[4]]["rank_now"] == res[TEAM_CODES[5]]["rank_now"] == 5
    assert sum(v["playoff_prob"] for v in res.values()) == pytest.approx(5.0, abs=1e-9)
    # 4~6위 3팀 동률 → 남은 2자리를 셋이 나눠 각 2/3
    st = _standings()
    st[TEAM_CODES[4]] = st[TEAM_CODES[5]] = st[TEAM_CODES[3]]
    res = playoff_race(st, [])
    for c in TEAM_CODES[3:6]:
        assert res[c]["playoff_prob"] == pytest.approx(2 / 3)
        assert res[c]["rank_now"] == 4
    assert [res[c]["playoff_prob"] for c in TEAM_CODES[:3]] == [1.0, 1.0, 1.0]
    assert all(res[c]["playoff_prob"] == 0.0 for c in TEAM_CODES[6:])
    assert sum(v["playoff_prob"] for v in res.values()) == pytest.approx(5.0, abs=1e-9)


def test_playoff_race_clinched():
    # 1위 팀(90-50)이 남은 4경기를 다 져도 90-54(.625)로 6위 이하 최고(65-75 + 남은 경기 승) 보다 위
    st = _standings()
    a, b = TEAM_CODES[0], TEAM_CODES[9]
    remaining = [(a, b, 0.0)] * 4 + [(TEAM_CODES[5], TEAM_CODES[6], 0.5)] * 4
    res = playoff_race(st, remaining)
    assert res[a]["playoff_prob"] == 1.0
    assert res[a]["exp_wins"] == 90
    assert res[b]["exp_wins"] == 49


def test_playoff_race_deterministic():
    st = {c: (60 + i, 60 - i) for i, c in enumerate(TEAM_CODES)}
    remaining = [(TEAM_CODES[i % 10], TEAM_CODES[(i + 3) % 10], 0.3 + 0.04 * (i % 10)) for i in range(200)]
    a = playoff_race(st, remaining)
    b = playoff_race(st, remaining)
    assert a == b
    assert all(0.0 <= v["playoff_prob"] <= 1.0 for v in a.values())
    assert sum(v["playoff_prob"] for v in a.values()) == pytest.approx(5.0, abs=1e-9)  # 매번 정확히 5자리


def test_playoff_race_all_zero_standings_sum_to_five():
    # 개막 전: 모두 0승 0패 (승률 0.5로 동률) + 남은 경기 → 확률은 유한하고 합은 5
    st = {c: (0, 0) for c in TEAM_CODES}
    remaining = [(TEAM_CODES[i], TEAM_CODES[(i + k) % 10], 0.5) for k in (1, 3, 7) for i in range(10)]
    res = playoff_race(st, remaining, n_sims=500)
    probs = [v["playoff_prob"] for v in res.values()]
    assert all(np.isfinite(probs)) and all(0.0 <= x <= 1.0 for x in probs)
    assert sum(probs) == pytest.approx(5.0, abs=1e-9)
    assert all(v["rank_now"] == 1 for v in res.values())
    # 남은 경기도 없으면 10팀 동률 → 각 0.5
    assert all(v["playoff_prob"] == 0.5 for v in playoff_race(st, []).values())


def test_standings_ignore_draw():
    games = [g("2026-05-01", 1, "LG", "HH", 3, 3), g("2026-05-02", 2, "LG", "HH", 4, 2)]
    st = simulate._standings(games, 2026, "2026-05-03")
    assert st["LG"] == (1, 0) and st["HH"] == (0, 1)
    assert set(st) == set(TEAM_CODES)


# ---------- outlook_for ----------

# test_outlook_series_from_config의 결정적 출력 (conftest bundle, SEED 42, N_SIMS 10,000)
PINNED_1029 = {
    "type": "series", "as_of": "2026-10-29", "name": "플레이오프", "best_of": 5, "teams": ["SS", "HT"],
    "head_start": [0, 0], "wins": [1, 1], "win_prob": [0.8135, 0.1865], "most_common_result": "3-1",
    "goes_distance_prob": 0.3709, "games_remaining_max": 3, "today_game_prob_source": "team_model",
    "next_game_date": "2026-10-29",
}

@pytest.fixture
def tmp_yaml(tmp_path):
    p = tmp_path / "postseason.yaml"
    p.write_text(
        "2026:\n"
        "  - {name: 와일드카드, teams: [LG, OB], best_of: 3, head_start: [1, 0], start: 2026-10-14, homes: [LG, LG]}\n"
        "  - {name: 플레이오프, teams: [SS, HT], best_of: 5, start: 2026-10-25, homes: [SS, SS, HT, HT, SS]}\n"
        "  - {name: 한국시리즈, teams: [KT, null], best_of: 7, start: null, homes: [KT, KT, null, null, KT, null, KT]}\n",
        encoding="utf-8")
    return p


def test_load_postseason(tmp_yaml):
    ps = load_postseason(2026, tmp_yaml)
    assert [s["name"] for s in ps] == ["와일드카드", "플레이오프", "한국시리즈"]
    assert ps[1]["start"] == "2026-10-25" and ps[1]["homes"] == ["SS", "SS", "HT", "HT", "SS"]
    assert ps[2]["teams"] == ["KT", None] and ps[2]["start"] is None
    assert ps[0]["head_start"] == [1, 0] and ps[1]["head_start"] == [0, 0]     # 없으면 [0, 0]
    assert load_postseason(2019, tmp_yaml) == []
    # 저장소의 실제 설정 파일도 읽힌다 — 와일드카드 = 4위 LG 1승 안고 2선승제, 두 경기 모두 LG 홈
    real = load_postseason(2026)
    assert [s["name"] for s in real] == ["와일드카드", "준플레이오프", "플레이오프", "한국시리즈"]
    wc = real[0]
    assert (wc["teams"], wc["best_of"], wc["head_start"]) == (["LG", "OB"], 3, [1, 0])
    assert simulate.homes(wc) == ["LG", "LG"] and simulate.max_games(wc) == 2


def test_head_start_validation():
    with pytest.raises(ValueError, match="head_start"):
        simulate._normalise({"name": "x", "teams": ["LG", "OB"], "best_of": 3, "head_start": [2, 0]})
    with pytest.raises(ValueError, match="head_start"):
        simulate._normalise({"name": "x", "teams": ["LG", "OB"], "best_of": 3, "head_start": [1]})
    # homes는 실제 경기 수(best_of − sum(head_start))만큼이어야 한다
    s = simulate._normalise({"name": "x", "teams": ["LG", "OB"], "best_of": 3, "head_start": [1, 0],
                             "homes": ["LG", "LG", "LG"]})
    with pytest.raises(ValueError, match="best_of - sum"):
        simulate.homes(s)


def test_outlook_accepts_raw_yaml_dict(bundle):
    # yaml.safe_load 결과(시즌 정수 키, 날짜 객체)를 그대로 넘겨도 load_postseason과 같은 결과
    raw = yaml.safe_load(simulate.POSTSEASON_YAML.read_text(encoding="utf-8"))
    games = _postseason_games()
    a = outlook_for(2026, "2026-10-29", games, state=LeagueState(), team_bundle=bundle, ps_config=raw)
    b = outlook_for(2026, "2026-10-29", games, state=LeagueState(), team_bundle=bundle,
                    ps_config=load_postseason(2026))
    assert a == b
    assert a["type"] == "series" and a["name"] == "플레이오프" and a["wins"] == [1, 1]


def _postseason_games():
    return [
        g("2026-10-12", 1, "SS", "HT", 3, 2),                     # 정규시즌 마지막 날 — 시리즈 전적 아님
        g("2026-10-14", 10, "LG", "OB", 4, 1),                    # 와일드카드 LG 승 → 끝
        g("2026-10-17", 11, "HT", "LG", 5, 1),                    # 준플레이오프 HT 3-0 → 끝
        g("2026-10-18", 12, "HT", "LG", 6, 3),
        g("2026-10-20", 13, "LG", "HT", 1, 13),
        g("2026-10-25", 2, "SS", "HT", status="CANCELED"),
        g("2026-10-26", 3, "SS", "HT", 1, 5),                     # HT 승
        g("2026-10-27", 4, "SS", "HT", 8, 3),                     # SS 승 → 1-1
        g("2026-10-29", 5, "HT", "SS", status="SCHEDULED"),
        g("2026-10-30", 6, "HT", "SS", status="SCHEDULED"),
    ]


def test_resolve_undecided_fills_korean_series_from_playoff_winner(tmp_yaml):
    """한국시리즈 [KT, null]·start null: 플레이오프 승자가 나오고 두 팀 맞대결 일정이 잡히면 데이터에서 채운다."""
    games = _postseason_games()[:8] + [
        g("2026-10-29", 5, "HT", "SS", 2, 7),                     # SS 승 → 2-1
        g("2026-10-30", 6, "HT", "SS", 1, 4),                     # SS 승 → 3-1, 플레이오프 끝
        g("2026-11-04", 20, "KT", "SS", status="SCHEDULED"),     # 한국시리즈 1차전 (KT 홈)
        g("2026-11-05", 21, "KT", "SS", status="SCHEDULED"),
    ]
    ps = load_postseason(2026, tmp_yaml)
    ks = simulate.resolve_undecided(ps, games)[2]
    assert ks["teams"] == ["KT", "SS"] and ks["start"] == "2026-11-04"
    assert simulate.homes(ks) == ["KT", "KT", "SS", "SS", "KT", "SS", "KT"]
    assert ps[2]["teams"] == ["KT", None] and ps[2]["start"] is None      # 입력은 그대로
    # 플레이오프가 끝난 뒤 한국시리즈 전까지는 진행 중 시리즈 없음, 1차전 날부터 한국시리즈
    assert simulate.active_series(2026, "2026-11-02", games, ps) is None
    assert simulate.active_series(2026, "2026-11-04", games, ps)["name"] == "한국시리즈"
    assert simulate.active_series(2026, "2026-10-30", games, ps)["name"] == "플레이오프"   # 그날 경기 전엔 2-1


def test_resolve_undecided_waits_for_decision(tmp_yaml):
    """플레이오프가 아직 안 끝났으면(2-1) 한국시리즈는 미정 그대로 — 일정이 미리 잡혀 있어도 팀을 지어내지 않는다."""
    games = _postseason_games() + [g("2026-11-04", 20, "KT", "SS", status="SCHEDULED")]
    ks = simulate.resolve_undecided(load_postseason(2026, tmp_yaml), games)[2]
    assert ks["teams"] == ["KT", None] and ks["start"] is None


def test_outlook_series_from_config(tmp_yaml, bundle):
    games = _postseason_games()
    state = LeagueState()
    state.start_season(2026)
    state.update(games[0])
    out = outlook_for(2026, "2026-10-29", games, state=state, team_bundle=bundle,
                      ps_config=load_postseason(2026, tmp_yaml))
    assert out == PINNED_1029


def test_outlook_series_today_uses_win_model_prob(tmp_yaml, bundle):
    """스펙 §8: 오늘(10-29) 경기는 승패 모델 확률(today_probs, 예고 선발 포함)로, 4·5차전은 팀 모델로 굴린다.
    오늘 경기는 HT 홈 → P(홈 승) 0.9 = 팀0(SS) 0.1. 카드는 SS 승리 확률이 팀 모델만 쓸 때보다 내려간다."""
    games = _postseason_games()
    ps = load_postseason(2026, tmp_yaml)
    s = simulate.active_series(2026, "2026-10-29", games, ps)
    left, p_team, src = simulate.series_probs(s, "2026-10-29", games, LeagueState(), bundle)
    assert left == ["HT", "HT", "SS"] and src == "team_model"
    left2, p_win, src2 = simulate.series_probs(s, "2026-10-29", games, LeagueState(), bundle, {5: 0.9})
    assert left2 == left and src2 == "win_model (starter-inclusive)"
    assert p_win == [pytest.approx(0.1), *p_team[1:]]                        # 첫 칸만 바뀐다 (팀0 기준으로 뒤집어서)

    base = outlook_for(2026, "2026-10-29", games, state=LeagueState(), team_bundle=bundle, ps_config=ps)
    out = outlook_for(2026, "2026-10-29", games, state=LeagueState(), team_bundle=bundle, ps_config=ps,
                      today_probs={5: 0.9})
    assert base["today_game_prob_source"] == "team_model"
    assert out["today_game_prob_source"] == "win_model (starter-inclusive)"
    want = series(5, (1, 1), ["team1", "team1", "team0"], p_win)
    assert out["win_prob"] == want["win_prob"] and out["most_common_result"] == want["most_common_result"]
    assert out["win_prob"][0] < base["win_prob"][0] - 0.1                   # SS가 오늘 질 확률 0.9 → 시리즈 확률 크게 하락
    assert {k: v for k, v in out.items() if k not in ("win_prob", "most_common_result", "goes_distance_prob",
                                                     "today_game_prob_source")} == \
        {k: v for k, v in base.items() if k not in ("win_prob", "most_common_result", "goes_distance_prob",
                                                    "today_game_prob_source")}


def test_outlook_series_today_prob_ignored_when_not_applicable(tmp_yaml, bundle):
    """오늘 두 팀 경기가 today_probs에 없거나(다른 경기 id), 실제 홈이 대진표의 다음 칸 홈과 다르면 팀 모델 그대로."""
    games = _postseason_games()
    ps = load_postseason(2026, tmp_yaml)
    base = outlook_for(2026, "2026-10-29", games, state=LeagueState(), team_bundle=bundle, ps_config=ps)
    other = outlook_for(2026, "2026-10-29", games, state=LeagueState(), team_bundle=bundle, ps_config=ps,
                        today_probs={999: 0.9})
    assert other == base
    flipped = [dict(x) for x in games]
    flipped[8] |= {"home_code": "SS", "away_code": "HT"}                     # 10-29를 SS 홈으로 (대진표는 HT 홈)
    out = outlook_for(2026, "2026-10-29", flipped, state=LeagueState(), team_bundle=bundle, ps_config=ps,
                      today_probs={5: 0.9})
    assert out["today_game_prob_source"] == "team_model" and out["win_prob"] == base["win_prob"]
    # 휴식일(10-28): 오늘 경기가 없으니 팀 모델
    off = outlook_for(2026, "2026-10-28", games, state=LeagueState(), team_bundle=bundle, ps_config=ps,
                      today_probs={5: 0.9})
    assert off["today_game_prob_source"] == "team_model"


def _wild_card_games(game1=(4, 1), game2=None):
    """와일드카드 LG(4위 · 1승 안고 시작, 홈)-OB. game1/game2 = (LG 점수, OB 점수), None이면 예정."""
    rows = [g("2026-10-12", 1, "SS", "HT", 3, 2)]
    for d, gid, score in (("2026-10-14", 10, game1), ("2026-10-15", 9, game2)):
        rows.append(g(d, gid, "LG", "OB", *score) if score else g(d, gid, "LG", "OB", status="SCHEDULED"))
    return rows + [g("2026-10-17", 11, "HT", "LG", status="SCHEDULED")]


def test_wild_card_head_start(tmp_yaml, bundle, monkeypatch):
    ps = load_postseason(2026, tmp_yaml)
    wc = ps[0]
    # 1차전 전: 전적 1-0 (LG의 1승 어드밴티지), 남은 경기 최대 2, 두 경기 모두 LG 홈
    games = _wild_card_games(game1=None)
    assert simulate.series_record(games, wc, "2026-10-14") == (1, 0, 0)
    assert simulate.left_homes(wc, 1, 0, 0) == ["LG", "LG"]
    # 경기마다 LG 승 확률 p = 0.5773 → LG 시리즈 승리 = 1 − (1 − p)² ≈ 0.821 (두산은 두 경기를 모두 이겨야 한다)
    monkeypatch.setattr(simulate, "game_probs", lambda bundle, pairs, state: [0.5773] * len(pairs))
    out = outlook_for(2026, "2026-10-14", games, state=LeagueState(), team_bundle=bundle, ps_config=ps)
    assert out["type"] == "series" and out["name"] == "와일드카드" and out["best_of"] == 3
    assert out["head_start"] == [1, 0] and out["wins"] == [1, 0] and out["games_remaining_max"] == 2
    assert out["win_prob"][0] == pytest.approx(1 - (1 - 0.5773) ** 2, abs=0.01)
    assert out["most_common_result"] == "2-0"


def test_wild_card_fifth_seed_wins_game_one(tmp_yaml, bundle):
    ps = load_postseason(2026, tmp_yaml)
    # 5위 OB가 1차전 승 → 1-1, 시리즈는 끝나지 않았다 (단판이면 여기서 OB가 올라가 버린다)
    games = _wild_card_games(game1=(1, 4))
    out = outlook_for(2026, "2026-10-15", games, state=LeagueState(), team_bundle=bundle, ps_config=ps)
    assert out["type"] == "series" and out["name"] == "와일드카드"
    assert out["wins"] == [1, 1] and out["games_remaining_max"] == 1 and out["next_game_date"] == "2026-10-15"
    assert simulate.left_homes(ps[0], 1, 1, 0) == ["LG"]                      # 2차전도 LG 홈
    # 2차전 결과가 나오면(10-16 기준) 승부가 났다: LG 승 → 2-1, OB 승 → 1-2. 어느 쪽이든 진행 중 시리즈가 아니다
    for score, rec in (((5, 2), (2, 1, 0)), ((0, 3), (1, 2, 0))):
        done = _wild_card_games(game1=(1, 4), game2=score)
        assert simulate.series_record(done, ps[0], "2026-10-16") == rec
        assert simulate.active_series(2026, "2026-10-16", done, ps) is None
        assert outlook_for(2026, "2026-10-16", done, state=LeagueState(), team_bundle=bundle,
                           ps_config=ps)["type"] == "next_game"
    # LG가 1차전을 이기면 2-0으로 바로 끝난다 (2차전 없음)
    won = _wild_card_games(game1=(4, 1))
    assert simulate.series_record(won, ps[0], "2026-10-15") == (2, 0, 0)
    assert simulate.active_series(2026, "2026-10-15", won, ps) is None


def test_outlook_series_ignores_final_on_same_day(tmp_yaml, bundle):
    # 전망은 경기 전 카드: on(10-30) 당일 경기가 이미 FINAL이어도 전적에 넣지 않는다
    games = _postseason_games()
    games[8] |= {"status": "FINAL", "home_score": 6, "away_score": 0}       # 10-29 HT 승 → SS 1-2
    games[9] |= {"status": "FINAL", "home_score": 4, "away_score": 3}       # 10-30 HT 승 (당일 — 안 센다)
    out = outlook_for(2026, "2026-10-30", games, state=LeagueState(), team_bundle=bundle,
                      ps_config=load_postseason(2026, tmp_yaml))
    assert out["type"] == "series" and out["wins"] == [1, 2]
    assert out["games_remaining_max"] == 2 and 0.0 < out["win_prob"][1] < 1.0


def test_outlook_series_off_day_shows_series(tmp_yaml, bundle):
    # 10-28은 경기 없는 날(이동일)이지만 플레이오프가 1-1로 진행 중 → series 카드, 다음 경기 10-29
    out = outlook_for(2026, "2026-10-28", _postseason_games(), state=LeagueState(), team_bundle=bundle,
                      ps_config=load_postseason(2026, tmp_yaml))
    assert out["type"] == "series" and out["name"] == "플레이오프" and out["wins"] == [1, 1]
    assert out["next_game_date"] == "2026-10-29"
    # 와일드카드 끝 · 다음 등록 시리즈(플레이오프) 시작 전(10-15) → 진행 중인 시리즈 없음 → next_game
    out = outlook_for(2026, "2026-10-15", _postseason_games(), state=LeagueState(), team_bundle=bundle,
                      ps_config=load_postseason(2026, tmp_yaml))
    assert out == {"type": "next_game", "as_of": "2026-10-15", "next_game_date": "2026-10-17"}


def test_outlook_series_draw_shifts_home_order(tmp_yaml, bundle, monkeypatch):
    # 10-27 무승부: 전적은 0-1 그대로지만 홈 순서는 2경기를 치른 것으로 넘어가고, 모자란 칸은 최종전 홈(SS)
    games = _postseason_games()
    games[7] |= {"home_score": 3, "away_score": 3}                          # 10-27 SS-HT 3-3
    seen = {}
    real = simulate.series

    def spy(best_of, wins, remaining_homes, p, **kw):
        seen["homes"] = list(remaining_homes)
        return real(best_of, wins, remaining_homes, p, **kw)

    monkeypatch.setattr(simulate, "series", spy)
    out = outlook_for(2026, "2026-10-29", games, state=LeagueState(), team_bundle=bundle,
                      ps_config=load_postseason(2026, tmp_yaml))
    assert out["wins"] == [0, 1] and out["games_remaining_max"] == 4
    assert seen["homes"] == ["team1", "team1", "team0", "team0"]            # HT, HT, SS, SS(최종전 홈 반복)


def test_outlook_series_finished_falls_back_to_next_game(tmp_yaml, bundle):
    # 시리즈가 전날까지 끝났으면 그날 두 팀 경기(취소된 예비 일정 등)가 있어도 진행 중 시리즈가 아니다
    games = _postseason_games() + [g("2026-10-31", 7, "SS", "HT", status="CANCELED"),
                                   g("2026-11-02", 8, "KT", "HT", status="SCHEDULED")]
    games[8] |= {"status": "FINAL", "home_score": 6, "away_score": 0}       # 10-29 HT 승
    games[9] |= {"status": "FINAL", "home_score": 4, "away_score": 3}       # 10-30 HT 승 → HT 3-1
    out = outlook_for(2026, "2026-10-31", games, state=LeagueState(), team_bundle=bundle,
                      ps_config=load_postseason(2026, tmp_yaml))
    assert out == {"type": "next_game", "as_of": "2026-10-31", "next_game_date": "2026-11-02"}


def test_outlook_fallback_for_unknown_series(tmp_yaml, bundle):
    games = [g("2026-03-20", 1, "HH", "HT", 13, 8), g("2026-03-21", 2, "LG", "SS", status="CANCELED"),
             g("2026-03-22", 3, "LG", "SS", 1, 0), g("2026-03-28", 4, "LG", "KT", status="SCHEDULED")]
    out = outlook_for(2026, "2026-03-20", games, state=LeagueState(), team_bundle=bundle,
                      ps_config=load_postseason(2026, tmp_yaml))
    assert out == {"type": "next_game", "as_of": "2026-03-20", "next_game_date": "2026-03-22"}
    # 포스트시즌 날짜인데 등록 시리즈가 아직 시작 전(10-13) → next_game
    out = outlook_for(2026, "2026-10-13", _postseason_games(), state=LeagueState(), team_bundle=bundle,
                      ps_config=load_postseason(2026, tmp_yaml))
    assert out == {"type": "next_game", "as_of": "2026-10-13", "next_game_date": "2026-10-14"}
    # 설정이 없으면(None) 포스트시즌 날짜도 next_game
    out = outlook_for(2026, "2026-10-29", _postseason_games(), state=LeagueState(), team_bundle=bundle,
                      ps_config=None)
    assert out == {"type": "next_game", "as_of": "2026-10-29", "next_game_date": "2026-10-30"}


def test_outlook_playoff_race_counts_only_games_before_on(bundle):
    # 정규시즌 날짜: 당일·이후 경기는 (이미 FINAL이어도) 남은 경기로 굴린다
    games = [g("2026-09-01", 1, "LG", "HH", 5, 1), g("2026-09-02", 2, "LG", "HH", 0, 9),
             g("2026-09-03", 3, "KT", "SS", status="SCHEDULED"), g("2026-09-04", 4, "KT", "SS", status="CANCELED")]
    state = LeagueState()
    state.start_season(2026)
    state.update(games[0])
    out = outlook_for(2026, "2026-09-02", games, state=state, team_bundle=bundle, ps_config=None,
                      n_sims=2000)
    assert out["type"] == "playoff_race" and out["as_of"] == "2026-09-02"
    assert set(out["teams"]) == set(TEAM_CODES)
    assert (out["teams"]["LG"]["wins"], out["teams"]["LG"]["losses"]) == (1, 0)
    assert (out["teams"]["HH"]["wins"], out["teams"]["HH"]["losses"]) == (0, 1)
    # 남은 경기 2개(9/2 LG-HH, 9/3 KT-SS; 9/4는 취소) → LG 기대 승은 1~2 사이
    assert 1.0 < out["teams"]["LG"]["exp_wins"] < 2.0
    assert set(out["teams"]["KT"]) == {"playoff_prob", "rank_now", "exp_wins", "wins", "losses"}


def test_game_probs_uses_team_features_only(bundle):
    state = LeagueState()
    p = simulate.game_probs(bundle, [g("2026-05-01", 1, "LG", "HH"), g("2026-05-01", 2, "HH", "LG")], state)
    assert len(p) == 2 and all(0.0 < x < 1.0 for x in p)
    assert simulate.game_probs(bundle, [], state) == []


def test_next_game_card_shape_and_key_order():
    """next_game 카드: 키 순서 (type, as_of, next_game_date), 취소 경기는 다음 경기로 치지 않는다, 없으면 None.
    outlook_for와 run_pipeline의 대체 카드가 이 함수 하나를 쓴다."""
    games = [{"date": "2026-10-30", "status": "CANCELED"}, {"date": "2026-11-01", "status": "SCHEDULED"},
             {"date": "2026-10-29", "status": "SCHEDULED"}]
    card = next_game_card("2026-10-29", games)
    assert list(card) == ["type", "as_of", "next_game_date"]
    assert card == {"type": "next_game", "as_of": "2026-10-29", "next_game_date": "2026-11-01"}
    assert next_game_card("2026-11-01", games)["next_game_date"] is None
