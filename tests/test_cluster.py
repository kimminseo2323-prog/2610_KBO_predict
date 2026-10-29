"""cluster: 합성 선수 시즌표(타자·투수 모두 뚜렷한 원형 4개)로 비율 지표·자격·K 선택·재번호·결정론·유사 선수를 확인한다."""
import json

import numpy as np
import pandas as pd
import pytest

from kbo_predict import cluster
from kbo_predict.cluster import (assign, build_from, fit_group, gmm_agreement, load_labels, qualify, quality,
                                 rates, retention, similar_players, types_map)

SEASONS = list(range(2015, 2027))

# 타자 원형 4개: (k, bb, hr, 2루타 비율(인플레이 안타 중), 3루타, babip, 도루) — 표준화 공간에서 서로 멀리
BAT_TYPES = [
    (0.28, 0.12, 0.065, 0.25, 0.01, 0.30, 0.03),   # 거포
    (0.12, 0.06, 0.010, 0.15, 0.05, 0.34, 0.30),   # 준족 교타
    (0.20, 0.15, 0.020, 0.20, 0.01, 0.29, 0.05),   # 선구안
    (0.10, 0.05, 0.020, 0.30, 0.01, 0.27, 0.02),   # 컨택
]
# 투수 원형 4개: (선발 여부, k, bb+hbp, hr, babip) — 선발 2(삼진형·맞혀 잡기), 구원 2(파워·제구)
PIT_TYPES = [(True, 0.13, 0.06, 0.030, 0.32), (False, 0.15, 0.05, 0.020, 0.33),
             (True, 0.25, 0.09, 0.020, 0.29), (False, 0.30, 0.13, 0.015, 0.28)]


def _batters(rng, n_per=15):
    rows = []
    for t, (k, bb, hr, d, tr, babip, sbr) in enumerate(BAT_TYPES):
        for j in range(n_per):
            pid = 1000 + t * 100 + j
            for s in SEASONS:
                pa = int(rng.integers(350, 650))
                bbn, hbp = rng.binomial(pa, bb), rng.binomial(pa, 0.01)
                ab = pa - bbn - hbp
                so, hrn = rng.binomial(ab, k), rng.binomial(ab, hr)
                hits_bip = rng.binomial(ab - so - hrn, babip)
                doubles = rng.binomial(hits_bip, d)
                triples = rng.binomial(hits_bip - doubles, tr)
                h = hits_bip + hrn
                sb = rng.binomial(h - hrn - doubles - triples + bbn + hbp, sbr)
                rows.append({"season": s, "player_id": pid, "name": f"Bat {pid}", "team": "LG", "pos": "CF",
                             "games": 120, "games_with_records": 120, "pa": pa, "ab": ab, "r": 50, "h": h,
                             "hr": hrn, "rbi": 50, "bb": bbn, "so": so, "hbp": hbp, "doubles": doubles,
                             "triples": triples, "sb": sb})
    return pd.DataFrame(rows)


def _pitchers(rng, n_per=15):
    rows = []
    for t, (starter, k, bb, hr, babip) in enumerate(PIT_TYPES):
        for j in range(n_per):
            pid = 5000 + t * 100 + j
            for s in SEASONS:
                games = int(rng.integers(25, 30)) if starter else int(rng.integers(40, 70))
                starts = games if starter else 0
                bf = int(rng.integers(550, 750)) if starter else int(rng.integers(180, 300))
                so, bbh, hrn = rng.binomial(bf, k), rng.binomial(bf, bb), rng.binomial(bf, hr)
                hbp = bbh // 8
                bip = bf - so - bbh - hrn
                hits_bip = rng.binomial(bip, babip)
                h = hits_bip + hrn
                rows.append({"season": s, "player_id": pid, "name": f"Pit {pid}", "team": "HT", "games": games,
                             "starts": starts, "bf": bf, "ip_outs": bf - h - bbh, "np": bf * 4, "r": 30,
                             "er": 28, "h": h, "hr": hrn, "so": so, "bb": bbh - hbp, "hbp": hbp})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def synthetic():
    return _batters(np.random.default_rng(0))


@pytest.fixture(scope="module")
def synthetic_pit():
    return _pitchers(np.random.default_rng(0))


# 한글 이름: 거포 원형(유형 0이 될 선수 1000~1014) 전원과 투수 하나. 나머지는 로마자 이름으로 남는다
NAMES_KO = {**{1000 + j: f"거포{j:02d}" for j in range(15)}, 5000: "박선발"}


@pytest.fixture(scope="module")
def obj(synthetic, synthetic_pit):
    return build_from(synthetic, synthetic_pit, NAMES_KO)


def test_rates_formulas():
    row = pd.DataFrame([{"pa": 100, "ab": 90, "h": 27, "hr": 5, "doubles": 6, "triples": 1, "so": 20, "bb": 8,
                         "hbp": 2, "sb": 4}])
    r = rates(row, "batter").iloc[0]
    assert r.k_pct == 0.2 and r.bb_pct == 0.08 and r.hr_pct == 0.05
    assert r.iso == pytest.approx((6 + 2 + 15) / 90) and r.babip == pytest.approx(22 / 65)
    assert r.sb_rate == pytest.approx(4 / (27 - 5 - 6 - 1 + 8 + 2))


def test_rates_pitcher_and_zero_denominator():
    rows = pd.DataFrame([{"bf": 100, "so": 25, "bb": 8, "hbp": 2, "hr": 3, "h": 20, "starts": 5, "games": 20},
                         {"bf": 0, "so": 0, "bb": 0, "hbp": 0, "hr": 0, "h": 0, "starts": 0, "games": 0}])
    r = rates(rows, "pitcher")
    assert r.loc[0, "k_pct"] == 0.25 and r.loc[0, "bb_pct"] == 0.1 and r.loc[0, "hr_pct"] == 0.03
    assert r.loc[0, "babip"] == pytest.approx(17 / 62) and r.loc[0, "start_share"] == 0.25
    assert r.loc[1, cluster.PITCHER_FEATURES].isna().all()          # 분모 0 -> NaN


def test_qualify_thresholds(synthetic, synthetic_pit):
    bat = synthetic.head(3).copy()
    bat["pa"] = [199, 200, 400]
    bat.loc[bat.index[2], ["ab", "so", "hr"]] = [10, 5, 5]            # babip 분모 0 -> NaN -> 제외
    assert qualify(bat, "batter").pa.tolist() == [200]
    pit = synthetic_pit.head(4).copy()
    pit[["ip_outs", "games", "starts"]] = [[150, 10, 10], [149, 40, 10], [100, 30, 0], [149, 29, 0]]
    assert qualify(pit, "pitcher")[["ip_outs", "games"]].values.tolist() == [[150, 10], [149, 40], [100, 30]]


def test_fit_is_deterministic(synthetic):
    a, b = fit_group(synthetic, "batter"), fit_group(synthetic, "batter")
    assert a["k"] == b["k"] and (a["kmeans"].cluster_centers_ == b["kmeans"].cluster_centers_).all()
    assert a["membership_method"] == b["membership_method"] and a["gmm_candidates"] == b["gmm_candidates"]
    assert (a["pca"].components_ == b["pca"].components_).all()
    assert assign(a, synthetic).equals(assign(b, synthetic))


def test_fit_ignores_seasons_outside_fit_seasons(synthetic):
    with26, without26 = fit_group(synthetic, "batter"), fit_group(synthetic[synthetic.season < 2026], "batter")
    assert (with26["kmeans"].cluster_centers_ == without26["kmeans"].cluster_centers_).all()
    assert (with26["scaler"].mean_ == without26["scaler"].mean_).all()
    assert assign(with26, synthetic).season.max() == 2026            # 2026은 맞춤엔 빠지고 배정은 된다


def _fake_by_k(table):
    """K(라벨 종류 수)별로 정해 둔 값을 돌려주는 가짜 지표 — K 선택 규칙만 따로 시험한다.
    silhouette_score(Z, labels)와 retention(df[type])을 모두 흉내 낸다."""
    def fake(*args):
        labels = args[1] if len(args) > 1 else args[0]["type"]
        return table[len(np.unique(labels))]
    return fake


def test_k_selection_score_not_silhouette_alone(synthetic, monkeypatch):
    # 실루엣만 보면 K=5(0.35)지만 실루엣+유지율은 K=4(0.30+0.60 > 0.35+0.50)
    monkeypatch.setattr(cluster, "silhouette_score", _fake_by_k({4: 0.30, 5: 0.35, 6: 0.10, 7: 0.10}))
    monkeypatch.setattr(cluster, "retention", _fake_by_k({4: 0.60, 5: 0.50, 6: 0.50, 7: 0.50}))
    b = fit_group(synthetic, "batter")
    assert b["k"] == 4 and [r["score"] for r in b["k_table"]] == pytest.approx([0.90, 0.85, 0.60, 0.60])


def test_k_selection_exact_tie_picks_smaller_k(synthetic, monkeypatch):
    # 2진수로 정확한 값: K=5와 K=6이 0.75로 정확히 동률 -> 작은 K=5
    monkeypatch.setattr(cluster, "silhouette_score", _fake_by_k({4: 0.0, 5: 0.5, 6: 0.25, 7: 0.0}))
    monkeypatch.setattr(cluster, "retention", _fake_by_k({4: 0.5, 5: 0.25, 6: 0.5, 7: 0.0}))
    b = fit_group(synthetic, "batter")
    assert [r["score"] for r in b["k_table"]] == [0.5, 0.75, 0.75, 0.0] and b["k"] == 5


def test_retention_exact():
    # 선수 1: 2015·2017 (연속 아님 -> 쌍 없음), 선수 2: 2015·2016 같은 유형, 선수 3: 2015·2016 다른 유형
    a = pd.DataFrame([(2015, 1, 0), (2017, 1, 0), (2015, 2, 1), (2016, 2, 1), (2015, 3, 0), (2016, 3, 1)],
                     columns=["season", "player_id", "type"])
    assert retention(a) == 0.5
    assert retention(a[a.player_id <= 2]) == 1.0
    assert np.isnan(retention(a[a.player_id == 1]))                  # 연속 시즌 쌍이 없으면 NaN


def test_k_selection_uses_score_and_relabels(synthetic, synthetic_pit):
    b = fit_group(synthetic, "batter")
    assert b["k"] == 4
    assert [r["k"] for r in b["k_table"]] == list(cluster.K_RANGE)
    best = max(b["k_table"], key=lambda r: (r["score"], -r["k"]))
    assert best["k"] == b["k"]
    for r in b["k_table"]:
        assert r["score"] == pytest.approx(r["silhouette"] + r["retention"])
    hr = b["centers_z"]["hr_pct"].to_numpy()
    assert (np.diff(hr) < 0).all()                                    # 유형 0의 hr_pct 중심이 가장 큼 (내림차순)
    assert b["centers"].loc[0, "hr_pct"] > 0.05                       # 원 단위 중심 = 거포 원형
    p = fit_group(synthetic_pit, "pitcher")
    c = p["centers"]
    assert p["k"] == 4 and (c.start_share[:2] > 0.9).all() and (c.start_share[2:] < 0.1).all()
    assert c.start_share.round(6).is_monotonic_decreasing              # 선발 비중 내림차순
    assert c.loc[2:, "start_share"].round(6).tolist() == [0, 0] and c.loc[2, "k_pct"] > c.loc[3, "k_pct"]  # 동률 -> K%
    forced = fit_group(synthetic, "batter", k=5)
    assert forced["k"] == 5 and len(forced["centers"]) == 5


def test_assign_columns_and_gmm(synthetic):
    b = fit_group(synthetic, "batter")
    a = assign(b, synthetic)
    assert {"type", "membership", "prob", "x", "y"} <= set(a.columns)
    m = np.array(a.membership.tolist())
    assert m.shape == (len(a), b["k"]) and np.allclose(m.sum(axis=1), 1)
    assert np.allclose(a.prob, m[np.arange(len(a)), a.type])
    assert retention(a) > 0.9


def test_membership_agrees_with_type_default(synthetic, synthetic_pit):
    for df, group in ((synthetic, "batter"), (synthetic_pit, "pitcher")):
        b = fit_group(df, group)
        assert set(b["gmm_candidates"]) == set(cluster.GMM_COVARIANCES)
        assert b["gmm_agreement"] == max(b["gmm_candidates"].values())  # GMM vs K-means 비교 값은 늘 남긴다
        assert b["membership_agreement"] >= cluster.AGREEMENT_FLOOR
        if b["membership_method"] == "kmeans_softmax":
            assert b["gmm"] is None and b["gmm_agreement"] < cluster.AGREEMENT_FLOOR
        else:
            assert b["membership_method"] == "gmm_" + b["gmm"].covariance_type
        assert gmm_agreement(assign(b, df)) >= cluster.AGREEMENT_FLOOR


def test_gmm_selected_path(synthetic):
    b = fit_group(synthetic, "batter", agreement_floor=0.5)           # 낮은 기준 -> 최고 GMM 후보가 선택된다
    best = max(cluster.GMM_COVARIANCES, key=lambda c: b["gmm_candidates"][c])   # 동률이면 앞 순서 (max는 첫 값)
    assert b["gmm_agreement"] >= 0.5 and b["membership_method"] == f"gmm_{best}"
    assert b["gmm"].covariance_type == best and b["membership_agreement"] == b["gmm_agreement"]
    a = assign(b, synthetic)
    m = np.array(a.membership.tolist())
    assert np.allclose(m, b["gmm"].predict_proba(b["scaler"].transform(a[b["features"]])))
    assert np.allclose(m.sum(axis=1), 1) and np.allclose(a.prob, m[np.arange(len(a)), a.type])


def test_softmax_fallback_argmax_is_type(synthetic):
    b = fit_group(synthetic, "batter", agreement_floor=1.01)          # 어떤 GMM도 넘을 수 없는 기준 -> 대체
    assert b["membership_method"] == "kmeans_softmax" and b["gmm"] is None and b["membership_agreement"] == 1.0
    a = assign(b, synthetic)
    m = np.array(a.membership.tolist())
    assert (m.argmax(axis=1) == a.type.to_numpy()).all() and gmm_agreement(a) == 1.0
    assert np.allclose(m.sum(axis=1), 1) and np.allclose(a.prob, m[np.arange(len(a)), a.type])
    Z = b["scaler"].transform(a[b["features"]])
    assert (a.type.to_numpy() == b["kmeans"].predict(Z)).all()        # 유형 = K-means 가장 가까운 중심
    d2 = ((Z[:, None, :] - b["kmeans"].cluster_centers_[None]) ** 2).sum(axis=2)
    w = np.exp(-d2 / (2 * b["softmax_s2"]))
    assert np.allclose(m, w / w.sum(axis=1, keepdims=True))           # membership ∝ exp(-d²/(2s²))
    assert assign(b, synthetic).equals(a)


def test_softmax_formula_by_hand(synthetic):
    """membership_t ∝ exp(-d_t² / (2·s²/D)) 를 두 행에 대해 손으로 계산해 맞춰 본다."""
    b = fit_group(synthetic, "batter", agreement_floor=1.01)
    feats, C, D = b["features"], b["kmeans"].cluster_centers_, len(b["features"])
    # s²: 맞춤 행에서 자기 중심까지 제곱거리의 평균 (D개 차원 합) -> 번들에는 차원당 값 s²/D
    q = qualify(synthetic, "batter")
    Zfit = b["scaler"].transform(q[q.season.isin(cluster.FIT_SEASONS)][feats])
    s2_total = np.mean(((Zfit - C[b["kmeans"].labels_]) ** 2).sum(axis=1))
    assert b["softmax_s2"] == pytest.approx(s2_total / D)
    rows = q.iloc[[0, 500]]
    a = assign(b, rows)
    Z = b["scaler"].transform(rows[feats])
    for i in range(2):
        w = [np.exp(-sum((Z[i][f] - C[t][f]) ** 2 for f in range(D)) / (2 * s2_total / D)) for t in range(len(C))]
        assert a.membership.iloc[i] == pytest.approx([v / sum(w) for v in w], rel=1e-9)
        assert a.type.iloc[i] == int(np.argmax(w))


def test_similar_for_new_single_season_player(synthetic):
    b = fit_group(synthetic, "batter")
    a = assign(b, synthetic)
    src = a.iloc[[10]]
    new = pd.concat([a, src.assign(season=2026, player_id=999999)], ignore_index=True)   # 한 시즌뿐인 새 선수
    lst = similar_players(b, new)[(2026, 999999)]
    assert len(lst) == 5 and all(s["player_id"] != 999999 for s in lst)
    assert (lst[0]["season"], lst[0]["player_id"]) == (int(src.season.iloc[0]), int(src.player_id.iloc[0]))
    assert lst[0]["similarity"] == pytest.approx(1.0)                 # 같은 스탯의 원본 행이 1위


def test_similar_excludes_same_player(synthetic):
    b = fit_group(synthetic, "batter")
    a = assign(b, synthetic)
    sim = similar_players(b, a)
    assert len(sim) == len(a)
    for (season, pid), lst in sim.items():
        assert len(lst) == 5 and all(s["player_id"] != pid for s in lst)
        assert [s["similarity"] for s in lst] == sorted((s["similarity"] for s in lst), reverse=True)
    # 동률: 같은 스탯 행을 다른 선수·시즌으로 복제하면 유사도 1.0끼리 (season, player_id) 오름차순
    base = a.iloc[[0]]
    dup = pd.concat([base.assign(season=s, player_id=p) for s, p in [(2020, 9), (2018, 7), (2018, 3), (2019, 1)]]
                    + [a.iloc[[1]]], ignore_index=True)
    lst = similar_players(b, dup.sort_values(["season", "player_id"]), n=3)[(2019, 1)]
    assert [(s["season"], s["player_id"]) for s in lst] == [(2018, 3), (2018, 7), (2020, 9)]
    assert lst[0]["similarity"] == pytest.approx(1.0)


def test_types_map_and_quality_shape(obj):
    tm = types_map(obj)
    assert set(obj) >= {"batter", "pitcher", "names_ko"}
    key = (2025, 1000)
    assert tm[key] == {"batter": int(obj["batter"]["assigned"].set_index(["season", "player_id"]).loc[key, "type"])}
    assert len(tm) == len(obj["batter"]["assigned"]) + len(obj["pitcher"]["assigned"])
    q = quality({g: obj[g]["bundle"] for g in cluster.GROUPS}, {g: obj[g]["assigned"] for g in cluster.GROUPS},
                load_labels("does/not/exist.yaml"))
    assert q["version"] == cluster.CLUSTER_VERSION and q["fit_seasons"] == cluster.FIT_SEASONS
    bq = q["batter"]
    assert bq["k"] == 4 and bq["n_fit"] < bq["n_all"] and len(bq["types"]) == 4
    assert bq["membership_method"] == obj["batter"]["bundle"]["membership_method"]
    assert bq["argmax_consistent"] is (gmm_agreement(obj["batter"]["assigned"]) == 1.0)
    if bq["membership_method"] == "kmeans_softmax":
        assert bq["argmax_consistent"] is True and "membership_agreement" not in bq  # 구조적으로 1.0 → 적지 않는다
    else:
        assert bq["membership_agreement"] >= cluster.AGREEMENT_FLOOR
    assert "보정" in q["membership_note"] and "거리" in q["membership_note"]
    assert bq["gmm_agreement"] == pytest.approx(obj["batter"]["bundle"]["gmm_agreement"], abs=1e-4)
    assert set(bq["gmm_candidates"]) == set(cluster.GMM_COVARIANCES)
    t0 = bq["types"][0]
    assert t0["id"] == 0 and t0["name"] == "유형 0" and set(t0["center"]) == set(cluster.BATTER_FEATURES)
    assert len(t0["examples"]) == 3 and sum(t["n"] for t in bq["types"]) == bq["n_all"]
    assert all(e in NAMES_KO.values() for e in t0["examples"])         # 한글 이름을 아는 선수 -> 한글
    assert all(e.startswith("Bat ") for t in bq["types"][1:] for e in t["examples"])   # 모르면 로마자
    json.dumps(q)                                                    # JSON으로 쓸 수 있어야 한다
    assert q["pitcher"]["k"] == 4 and q["pitcher"]["types"][0]["center"]["start_share"] > 0.9


def test_quality_argmax_consistency_by_membership_method(obj):
    """kmeans_softmax면 argmax_consistent는 구조적으로 true이고 일치도 숫자는 적지 않는다.
    GMM 경로에서는 실측 일치도를 membership_agreement로 적고, 한 행이라도 어긋나면 argmax_consistent가 false."""
    bundles = {g: dict(obj[g]["bundle"]) for g in cluster.GROUPS}
    assigned = {g: obj[g]["assigned"].copy() for g in cluster.GROUPS}
    bundles["batter"]["membership_method"] = "kmeans_softmax"
    bundles["pitcher"]["membership_method"] = "gmm_tied"
    kb = bundles["batter"]["k"]                                  # softmax 경로: 최댓값 성분 == 유형 (구조적으로 성립)
    assigned["batter"]["membership"] = [[float(t == ty) for t in range(kb)] for ty in assigned["batter"]["type"]]
    a = assigned["pitcher"]
    k = bundles["pitcher"]["k"]
    wrong = (int(a["type"].iloc[0]) + 1) % k                      # 첫 행만 최댓값 성분이 유형과 다르게
    a["membership"] = [[1.0 if t == (wrong if i == 0 else ty) else 0.0 for t in range(k)]
                       for i, ty in enumerate(a["type"])]
    q = quality(bundles, assigned, load_labels("does/not/exist.yaml"))
    assert q["batter"]["argmax_consistent"] is True and "membership_agreement" not in q["batter"]
    assert q["pitcher"]["argmax_consistent"] is False
    assert q["pitcher"]["membership_agreement"] == round(1 - 1 / len(a), 4)


def test_load_labels_default_when_missing(tmp_path):
    d = load_labels(tmp_path / "none.yaml")
    assert set(d) == set(cluster.GROUPS) and d["batter"][0]["name"] == "유형 0" and d["pitcher"][3]["name"] == "유형 3"
    f = tmp_path / "labels.yaml"
    f.write_text("batter:\n  0: {name: 거포형, blurb: 멀리 친다}\npitcher: {}\n", encoding="utf-8")
    d = load_labels(f)
    assert d["batter"][0] == {"name": "거포형", "blurb": "멀리 친다"} and d["batter"][1]["name"] == "유형 1"


def test_cli_writes_bundle_csv_and_manifest(tmp_path, monkeypatch, obj):
    monkeypatch.setattr(cluster, "build", lambda seasons: obj)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"models": {"live": {"path": "x"}}}), encoding="utf-8")
    args = ["fit", "--out", str(tmp_path / "c.pkl"), "--types", str(tmp_path / "t.csv"), "--manifest", str(manifest)]
    cluster.main(args)
    csv = pd.read_csv(tmp_path / "t.csv")
    assert csv.columns.tolist() == ["season", "player_id", "group", "type", "prob", "x", "y"]
    assert csv.equals(csv.sort_values(["group", "season", "player_id"]).reset_index(drop=True))
    m = json.loads(manifest.read_text(encoding="utf-8"))["models"]
    assert m["live"] == {"path": "x"} and m["clusters"]["version"] == "clusters-2026"
    assert set(m["clusters"]) == {"path", "sha256", "version", "fit_seasons", "types_sha256"}
    first = m["clusters"]["types_sha256"]
    cluster.main(args)
    assert json.loads(manifest.read_text(encoding="utf-8"))["models"]["clusters"]["types_sha256"] == first
    assert cluster.load_bundle(tmp_path / "c.pkl")["batter"]["bundle"]["k"] == 4
