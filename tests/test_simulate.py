"""simulate.py: 시리즈·가을야구 몬테카를로와 outlook_for."""
import numpy as np
import pytest
import yaml

from kbo_predict import simulate
from kbo_predict.features import LeagueState
from kbo_predict.simulate import TEAM_CODES, load_postseason, outlook_for, playoff_race, series


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
    "wins": [1, 1], "win_prob": [0.8135, 0.1865], "most_common_result": "3-1", "goes_distance_prob": 0.3709,
    "games_remaining_max": 3, "next_game_date": "2026-10-29",
}

@pytest.fixture
def tmp_yaml(tmp_path):
    p = tmp_path / "postseason.yaml"
    p.write_text(
        "2026:\n"
        "  - {name: 와일드카드, teams: [LG, OB], best_of: 1, start: 2026-10-14}\n"
        "  - {name: 플레이오프, teams: [SS, HT], best_of: 5, start: 2026-10-25, homes: [SS, SS, HT, HT, SS]}\n"
        "  - {name: 한국시리즈, teams: [KT, null], best_of: 7, start: null, homes: [KT, KT, null, null, KT, null, KT]}\n",
        encoding="utf-8")
    return p


def test_load_postseason(tmp_yaml):
    ps = load_postseason(2026, tmp_yaml)
    assert [s["name"] for s in ps] == ["와일드카드", "플레이오프", "한국시리즈"]
    assert ps[1]["start"] == "2026-10-25" and ps[1]["homes"] == ["SS", "SS", "HT", "HT", "SS"]
    assert ps[2]["teams"] == ["KT", None] and ps[2]["start"] is None
    assert load_postseason(2019, tmp_yaml) == []
    # 저장소의 실제 설정 파일도 읽힌다
    names = [s["name"] for s in load_postseason(2026)]
    assert names == ["와일드카드", "준플레이오프", "플레이오프", "한국시리즈"]


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


def test_outlook_series_from_config(tmp_yaml, bundle):
    games = _postseason_games()
    state = LeagueState()
    state.start_season(2026)
    state.update(games[0])
    out = outlook_for(2026, "2026-10-29", games, state=state, team_bundle=bundle,
                      ps_config=load_postseason(2026, tmp_yaml))
    assert out == PINNED_1029


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
