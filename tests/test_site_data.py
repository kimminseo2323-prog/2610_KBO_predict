"""site_data: 합성 군집 묶음(test_cluster의 원형 4개 타자·투수)과 합성 경기로 players.json·teams.json 모양,
반올림·정렬·비중 합, 2026만 model_expected, 정규시즌 FINAL만 세기, CLI publish 파일 형식을 확인한다."""
import json

import numpy as np
import pandas as pd
import pytest

from kbo_predict import cluster
from kbo_predict.cluster import build_from, load_labels
from kbo_predict.features import FEATURE_NAMES, save_features
from kbo_predict.raw_store import upsert_games
from kbo_predict.site_data import players_payload, roster_types, team_model_expected, teams_payload
from kbo_predict.train_win import predict_proba, save_bundle
from tests.test_cluster import NAMES_KO, _batters, _pitchers

META = {"generated_at": "t", "commit_sha": None}
PLAYER_KEYS = {"player_id", "name", "name_ko", "group", "season", "team", "pos", "type", "prob", "membership",
               "x", "y", "stats", "similar"}
TEAM_KEYS = {"season", "code", "name", "games", "wins", "losses", "ties", "win_pct", "pyth_pct", "model_expected",
             "home_pct", "away_pct", "vs", "roster_types"}


@pytest.fixture(scope="module")
def synthetic_obj():
    """test_cluster의 합성 선수표. 팀을 선수 번호 홀짝으로 LG·HT에 나눠 로스터 비중이 두 팀 모두 생기게 한다."""
    bat, pit = _batters(np.random.default_rng(0)), _pitchers(np.random.default_rng(0))
    for df in (bat, pit):
        df["team"] = np.where(df["player_id"] % 2 == 0, "LG", "HT")
    return build_from(bat, pit, NAMES_KO)


@pytest.fixture
def labels(tmp_path):
    return load_labels(tmp_path / "missing.yaml")


def _g(gid, d, home, away, hs, as_, status="FINAL"):
    names = {"LG": "LG Twins", "HT": "Kia Tigers", "SK": "SK Wyverns"}
    return {"game_id": gid, "date": d, "season": int(d[:4]), "home": names[home], "away": names[away],
            "home_code": home, "away_code": away, "home_score": hs, "away_score": as_, "status": status,
            "status_note": None, "time_kst": None, "stadium": None}


# 2026 정규시즌(3/28~10/12): LG 홈 5-3 승, 2-2 무 / HT 홈 4-1 HT 승, 3-6 LG 승.
# 세지 않는 경기: 점수 없는 FINAL, 포스트시즌(10/20), 시범경기(3/20), 예정·취소 경기.
GAMES_2026 = [
    _g(1, "2026-04-01", "LG", "HT", 5, 3), _g(2, "2026-04-02", "LG", "HT", 2, 2),
    _g(3, "2026-04-03", "HT", "LG", 4, 1), _g(4, "2026-04-04", "HT", "LG", 3, 6),
    _g(5, "2026-04-05", "HT", "LG", None, None),
    _g(6, "2026-10-20", "LG", "HT", 9, 0), _g(7, "2026-03-20", "HT", "LG", 9, 0),
    _g(8, "2026-10-30", "LG", "HT", None, None, status="SCHEDULED"),
    _g(9, "2026-04-06", "LG", "HT", None, None, status="CANCELED"),
]
# 2025: SK가 LG를 두 번 이긴다 (옛 구단명 SK Wyverns -> 한글 "SK")
GAMES_2025 = [_g(101, "2025-05-01", "SK", "LG", 3, 1), _g(102, "2025-05-02", "LG", "SK", 0, 2)]


@pytest.fixture
def seeded(tmp_data_dir):
    upsert_games(2026, GAMES_2026)
    upsert_games(2025, GAMES_2025)
    return tmp_data_dir


def _features_df():
    """2025·2026 피처 행 (홈·원정 팀 코드 + 26개 피처). 값은 난수 — model_expected 계산 경로만 본다."""
    rng = np.random.default_rng(3)
    rows = []
    for i, (season, home, away) in enumerate([(2026, "LG", "HT"), (2026, "LG", "HT"), (2026, "HT", "LG"),
                                              (2026, "HT", "LG"), (2025, "SK", "LG"), (2025, "LG", "SK")]):
        rows.append({"game_id": i, "date": f"{season}-05-01", "season": season, "home_code": home, "away_code": away,
                     **dict(zip(FEATURE_NAMES, rng.normal(0, 0.3, len(FEATURE_NAMES)))), "y": i % 2})
    return pd.DataFrame(rows)


# ---------- players.json ----------

def test_players_payload_shape(synthetic_obj, labels):
    p = players_payload(synthetic_obj, labels, meta=META)
    assert set(p) == {"generated_at", "commit_sha", "model_version", "fit_seasons", "types", "players"}
    assert p["model_version"] == "clusters-2026" and p["fit_seasons"] == cluster.FIT_SEASONS
    assert p["types"]["batter"][0] == {"id": 0, "name": "유형 0", "blurb": ""} and len(p["types"]["pitcher"]) == 4
    first = p["players"][0]
    assert set(first) == PLAYER_KEYS
    assert len(first["similar"]) == 5 and all(s["player_id"] != first["player_id"] for s in first["similar"])
    assert set(first["similar"][0]) == {"player_id", "name", "name_ko", "season", "team", "similarity"}
    assert abs(sum(first["membership"]) - 1) < 0.01
    assert first["type"]["id"] == int(np.argmax(first["membership"])) and first["prob"] == max(first["membership"])
    n = len(synthetic_obj["batter"]["assigned"]) + len(synthetic_obj["pitcher"]["assigned"])
    assert len(p["players"]) == n
    json.dumps(p)


def test_players_sorted_and_rounded(synthetic_obj, labels):
    players = players_payload(synthetic_obj, labels, meta=META)["players"]
    keys = [(-x["season"], cluster.GROUPS.index(x["group"]), x["player_id"]) for x in players]
    assert keys == sorted(keys) and players[0]["season"] == 2026 and players[0]["group"] == "batter"
    for x in players[:50] + players[-50:]:
        assert all(v == round(v, 3) for v in [x["prob"], x["x"], x["y"], *x["membership"]])
        assert all(s["similarity"] == round(s["similarity"], 3) for s in x["similar"])
        sims = [s["similarity"] for s in x["similar"]]
        assert sims == sorted(sims, reverse=True)


def test_player_stats_formulas_and_names(synthetic_obj, labels):
    players = players_payload(synthetic_obj, labels, meta=META)["players"]
    by_key = {(x["group"], x["season"], x["player_id"]): x for x in players}
    bat = synthetic_obj["batter"]["assigned"].set_index(["season", "player_id"]).loc[(2025, 1000)]
    b = by_key[("batter", 2025, 1000)]
    assert b["name_ko"] == "거포00" and b["name"] == "Bat 1000" and b["pos"] == "CF" and b["team"] == "LG"
    assert set(b["stats"]) == {"pa", "avg", "obp", "hr", "sb", "k_pct", "bb_pct", "iso", "babip"}
    assert b["stats"]["avg"] == round(bat["h"] / bat["ab"], 3)
    assert b["stats"]["obp"] == round((bat["h"] + bat["bb"] + bat["hbp"]) / bat["pa"], 3)
    assert b["stats"]["pa"] == bat["pa"] and b["stats"]["iso"] == round(bat["iso"], 3)
    assert by_key[("batter", 2025, 1100)]["name_ko"] is None             # 한글 이름을 모르면 null
    pit = synthetic_obj["pitcher"]["assigned"].set_index(["season", "player_id"]).loc[(2025, 5000)]
    q = by_key[("pitcher", 2025, 5000)]
    assert q["pos"] == "P" and q["name_ko"] == "박선발"
    assert set(q["stats"]) == {"games", "starts", "ip", "era", "k_pct", "bb_pct", "hr_pct", "babip"}
    assert q["stats"]["ip"] == round(pit["ip_outs"] / 3, 1)
    assert q["stats"]["era"] == round(pit["er"] / pit["ip_outs"] * 27, 2)
    # 비슷한 선수 칸의 이름·팀은 그 선수-시즌 행에서
    s = q["similar"][0]
    other = by_key[("pitcher", s["season"], s["player_id"])]
    assert (s["name"], s["name_ko"], s["team"]) == (other["name"], other["name_ko"], other["team"])


# ---------- teams.json ----------

def test_roster_types_shares_sum_to_one(synthetic_obj):
    a = synthetic_obj["batter"]["assigned"]
    shares = roster_types(a, "batter", 2025, "LG")
    rows = a[(a["season"] == 2025) & (a["team"] == "LG")]
    exact = rows.groupby("type")["pa"].sum() / rows["pa"].sum()
    assert set(shares) == {str(t) for t in exact.index}
    assert all(abs(shares[str(t)] - v) <= 0.001 for t, v in exact.items())
    assert sum(shares.values()) == pytest.approx(1, abs=1e-9)
    assert roster_types(a, "batter", 2025, "SK") == {}                   # 유형 있는 선수가 없는 팀


def test_teams_payload_model_expected_only_2026(synthetic_obj, labels, seeded, bundle):
    fdf = _features_df()
    out = teams_payload([2025, 2026], obj=synthetic_obj, labels=labels, features_df=fdf, report_bundle=bundle,
                        meta=META)
    assert out["model_version"] == bundle["version"] and out["note"].startswith(
        "model_expected는 2026(홀드아웃)만; 2015~2025는 학습·검증 시즌이라 null")
    teams = out["teams"]
    assert all(set(t) == TEAM_KEYS for t in teams)
    assert all(t["model_expected"] is None for t in teams if t["season"] != 2026)
    assert all(0 < t["model_expected"] < 1 for t in teams if t["season"] == 2026)
    assert all(abs(sum(t["roster_types"]["batter"].values()) - 1) < 1e-6 for t in teams if t["roster_types"]["batter"])
    assert all(abs(sum(t["roster_types"]["pitcher"].values()) - 1) < 1e-6 for t in teams if t["roster_types"]["pitcher"])
    # 모델 기대 승률 = 홈 경기 p + 원정 경기 (1 − p) 평균 (2026 행만)
    f26 = fdf[fdf["season"] == 2026]
    p = predict_proba(bundle, f26[bundle["features"]])
    home = f26["home_code"].to_numpy() == "LG"
    lg_exp = np.concatenate([p[home], 1 - p[~home]]).mean()
    lg = next(t for t in teams if (t["season"], t["code"]) == (2026, "LG"))
    assert lg["model_expected"] == round(lg_exp, 3)
    assert team_model_expected(fdf, bundle)["LG"] == pytest.approx(lg_exp)


def test_teams_counts_regular_finals_only(synthetic_obj, labels, seeded, bundle):
    teams = teams_payload([2025, 2026], obj=synthetic_obj, labels=labels, features_df=None, report_bundle=None,
                          meta=META)["teams"]
    assert [(t["season"], t["code"]) for t in teams] == [(2026, "LG"), (2026, "HT"), (2025, "SK"), (2025, "LG")]
    lg, ht, sk = teams[0], teams[1], teams[2]
    assert (lg["games"], lg["wins"], lg["losses"], lg["ties"]) == (4, 2, 1, 1)
    assert lg["name"] == "LG" and ht["name"] == "KIA" and sk["name"] == "SK"
    assert lg["win_pct"] == 0.667 and ht["win_pct"] == 0.333
    assert lg["home_pct"] == 1.0 and lg["away_pct"] == 0.5 and lg["vs"] == {"HT": 0.667}
    rs, ra = 5 + 2 + 1 + 6, 3 + 2 + 4 + 3
    assert lg["pyth_pct"] == round(rs ** 1.83 / (rs ** 1.83 + ra ** 1.83), 3)
    assert lg["model_expected"] is None                                   # 피처·모델을 안 주면 2026도 null
    assert sk["win_pct"] == 1.0 and sk["home_pct"] == 1.0 and sk["away_pct"] == 1.0 and sk["vs"] == {"LG": 1.0}
    assert sk["roster_types"] == {"batter": {}, "pitcher": {}}
    assert set(lg["roster_types"]["batter"]) and set(lg["roster_types"]["pitcher"])


# ---------- CLI publish ----------

def test_cli_publish_writes_sorted_deterministic_json(synthetic_obj, seeded, bundle, tmp_path):
    cpk, rpk, fpq = tmp_path / "c.pkl", tmp_path / "r.pkl", tmp_path / "f.parquet"
    cluster.save_bundle(synthetic_obj, cpk)
    save_bundle(bundle, rpk)
    save_features(_features_df(), fpq)
    out_dir = tmp_path / "public"
    args = ["publish", "--clusters", str(cpk), "--report", str(rpk), "--features", str(fpq), "--out-dir", str(out_dir)]
    cluster.main(args)
    texts = {n: (out_dir / n).read_text(encoding="utf-8") for n in ("players.json", "teams.json")}
    for n, text in texts.items():
        obj = json.loads(text)
        # _write_json(indent=1, sort_keys=True): 같은 내용을 그 설정으로 다시 쓰면 같은 글자
        assert text == json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        assert obj["generated_at"] and "commit_sha" in obj
    assert len(json.loads(texts["teams.json"])["teams"]) == 4
    cluster.main(args)                                                    # 다시 돌려도 generated_at 말고는 같다
    for n, text in texts.items():
        a, b = json.loads(text), json.loads((out_dir / n).read_text(encoding="utf-8"))
        a.pop("generated_at"), b.pop("generated_at")
        assert a == b


def test_cli_publish_missing_features_exits(tmp_path):
    with pytest.raises(SystemExit, match="features"):
        cluster.main(["publish", "--features", str(tmp_path / "none.parquet"), "--out-dir", str(tmp_path)])
