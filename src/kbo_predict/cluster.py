"""선수 유형 군집: 시즌 성적을 비율 지표로 바꿔 타자·투수를 '유형'으로 묶는다.

흐름 (타자·투수 그룹마다 따로):
    rates        누적 기록 -> 비율 지표 (K%, BB%, HR%, ISO, BABIP, 도루율 / 선발 비중)
    qualify      규정급 행만 남긴다 (타자 200타석, 투수 50이닝 또는 구원 30경기) + 지표에 NaN 있는 행 제외
    fit_group    맞춤 시즌(2015~2025) 행으로 표준화 -> K=4..7 K-means -> 점수(실루엣 + 유지율)로 K 선택
                 -> 유형 번호를 뜻이 있게 다시 매김 -> 소속 확률 방식 선택(아래) -> PCA 2D 좌표
    assign       자격 행 전부(2026 포함)에 유형·소속 확률·2D 좌표를 붙인다
    similar_players  표준화 공간 코사인 유사도로 '비슷한 선수-시즌' 상위 5개 (같은 선수의 다른 시즌은 제외)

용어:
    유지율(retention)  연속 두 시즌 모두 자격이 있는 선수 중 두 해의 유형이 같은 비율. 유형이 '그 선수다움'을
                       잡는지(한 해 운에 흔들리지 않는지) 보는 지표라 K 선택 점수에 실루엣과 함께 더한다.
    일치도(agreement)  소속 확률의 최댓값 성분 == K-means 유형인 행의 비율. 화면에 보이는 유형과 '가장 높은
                       소속 확률'이 어긋나면 안 되므로 소속 확률 방식을 이 값으로 고른다.
소속 확률(membership) 방식:
    1) K-means 중심에서 출발하는 GMM을 공분산 tied / diag / full 세 가지로 맞추고, 맞춤 행 일치도가 가장 높은 것
       (동률이면 이 순서)을 고른다 -> "gmm_tied" 등.
    2) 그 최고 일치도도 AGREEMENT_FLOOR(0.95) 미만이면 GMM을 버리고 거리 기반 소프트맥스를 쓴다 -> "kmeans_softmax":
       membership_t ∝ exp(-d_t² / (2·s²)), d_t = 표준화 공간에서 중심 t까지 거리,
       s² = 차원당 군집 내 분산 = (맞춤 행에서 자기 중심까지 제곱거리의 평균) / D, D = 피처 수.
       (d_t²는 D개 차원의 합이므로 s²도 차원당 값으로 맞춰야 확률이 지나치게 평평해지지 않는다.)
       가장 가까운 중심이 가장 큰 확률이므로 최댓값 성분 == 유형이 구조적으로 항상 성립한다.
    화면의 유형과 '가장 높은 소속 확률'이 어긋나면 안 되므로 기준을 0.95로 높게 둔다 (실데이터는 두 그룹 모두 2)).
    GMM 후보 세 개는 그래도 맞춰서 일치도(gmm_candidates, gmm_agreement = 최고 후보)를 'GMM vs K-means 비교'로 남긴다.
유형 번호: 타자는 표준화 HR% 중심이 큰 순서(0 = 가장 장타형), 투수는 선발 비중 큰 순서, 같으면 K% 큰 순서.

재현성: seed 42 고정, KMeans n_init=10, PCA svd_solver="full", 계산은 1스레드(_single_thread).
같은 입력이면 두 번 맞춰도 중심·라벨·확률·좌표가 비트 단위로 같다.
2026 행은 맞춤에 쓰지 않으므로 2026 경기가 쌓여도 유형 정의(중심)는 바뀌지 않는다.

CLI:
    python -m kbo_predict.cluster fit [--out models/clusters.pkl]
        -> models/clusters.pkl (build 결과 전체), data/processed/player_types.csv,
           models/manifest.json의 models.clusters 항목 갱신, 유형 프로파일 표를 표준 출력에 찍는다.
    python -m kbo_predict.cluster publish [--clusters models/clusters.pkl] [--report models/report-2026.pkl]
                                          [--features data/processed/features.parquet] [--out-dir data/public]
        -> data/public/players.json, data/public/teams.json (사이트 데이터, site_data 모듈 참조)
"""
import argparse
import functools
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from . import KST
from .player_stats import batting_seasons, korean_names, pitching_seasons
from .train_win import _commit_sha, _sha256, load_bundle, save_bundle, update_manifest

SEED = 42
K_RANGE = range(4, 8)
FIT_SEASONS = list(range(2015, 2026))
ALL_SEASONS = list(range(2015, 2027))       # CLI가 집계·배정하는 시즌 (2026은 배정만)
MIN_PA = 200
MIN_IP_OUTS = 150                           # 50이닝
MIN_RELIEF_APPS = 30                        # 구원 등판 = games - starts
BATTER_FEATURES = ["k_pct", "bb_pct", "hr_pct", "iso", "babip", "sb_rate"]
PITCHER_FEATURES = ["k_pct", "bb_pct", "hr_pct", "babip", "start_share"]
FEATURES = {"batter": BATTER_FEATURES, "pitcher": PITCHER_FEATURES}
GROUPS = ("batter", "pitcher")
CLUSTER_VERSION = "clusters-2026"
GMM_COVARIANCES = ("tied", "diag", "full")   # 소속 확률 GMM 후보 (일치도 동률이면 이 순서)
AGREEMENT_FLOOR = 0.95                      # GMM 최고 일치도가 이보다 낮으면 kmeans_softmax로 대체
EXAMPLE_SEASON = 2025                       # 유형 예시 선수를 고르는 시즌 (없으면 그 유형의 최근 시즌)

CLUSTERS_PKL = Path("models/clusters.pkl")
TYPES_CSV = Path("data/processed/player_types.csv")
MANIFEST = Path("models/manifest.json")
LABELS_YAML = Path(__file__).resolve().parents[2] / "config" / "cluster_labels.yaml"   # 어디서 실행해도 같은 파일
REPORT_PKL = Path("models/report-2026.pkl")             # publish: teams.json의 model_expected를 내는 평가 모델
FEATURES_PARQUET = Path("data/processed/features.parquet")
PUBLIC_DIR = Path("data/public")

__all__ = ["rates", "qualify", "fit_group", "assign", "similar_players", "retention", "gmm_agreement",
           "quality", "load_labels", "build", "build_from", "types_map", "save_bundle", "load_bundle"]


def _single_thread(fn):
    """BLAS(MKL)·OpenMP를 1스레드로 묶어 실행한다. 여러 스레드면 부분합을 더하는 순서가 실행마다 달라져
    K-means 중심이 마지막 자리(1 ulp)에서 흔들린다 — 비트 단위 재현성을 위해 맞춤·배정·유사도 계산을 감싼다."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with threadpool_limits(limits=1):
            return fn(*args, **kwargs)
    return wrapper


# ---------- 비율 지표 · 자격 ----------

def _div(num: pd.Series, den: pd.Series) -> pd.Series:
    """num / den. 분모가 0 이하인 행은 NaN (분모 0이면 지표가 정의되지 않는다)."""
    return num / den.where(den > 0)


def rates(df: pd.DataFrame, group: str) -> pd.DataFrame:
    """비율 지표 열을 더한 사본을 돌려준다.
    타자: K% = 삼진/타석, BB% = 볼넷/타석, HR% = 홈런/타석, ISO = (2루타 + 2·3루타 + 3·홈런)/타수,
          BABIP = (안타-홈런)/(타수-삼진-홈런), 도루율 = 도루/(단타+볼넷+사구) — 1루에 나간 기회당 도루.
    투수: K% = 삼진/상대 타자, BB% = (볼넷+사구)/상대 타자, HR% = 피홈런/상대 타자,
          BABIP = (피안타-피홈런)/(상대 타자-삼진-볼넷-사구-피홈런), 선발 비중 = 선발/등판."""
    out = df.copy()
    if group == "batter":
        singles = out["h"] - out["hr"] - out["doubles"] - out["triples"]
        out["k_pct"] = _div(out["so"], out["pa"])
        out["bb_pct"] = _div(out["bb"], out["pa"])
        out["hr_pct"] = _div(out["hr"], out["pa"])
        out["iso"] = _div(out["doubles"] + 2 * out["triples"] + 3 * out["hr"], out["ab"])
        out["babip"] = _div(out["h"] - out["hr"], out["ab"] - out["so"] - out["hr"])
        out["sb_rate"] = _div(out["sb"], singles + out["bb"] + out["hbp"])
    elif group == "pitcher":
        bf = out["bf"]
        out["k_pct"] = _div(out["so"], bf)
        out["bb_pct"] = _div(out["bb"] + out["hbp"], bf)
        out["hr_pct"] = _div(out["hr"], bf)
        out["babip"] = _div(out["h"] - out["hr"], bf - out["so"] - out["bb"] - out["hbp"] - out["hr"])
        out["start_share"] = _div(out["starts"], out["games"])
    else:
        raise ValueError(f"unknown group {group!r}")
    return out


def qualify(df: pd.DataFrame, group: str) -> pd.DataFrame:
    """규정급 행만 (season, player_id) 순으로. 비율 지표가 없으면 먼저 계산한다. 지표에 NaN이 있는 행은 뺀다."""
    feats = FEATURES[group]
    if not set(feats) <= set(df.columns):
        df = rates(df, group)
    if group == "batter":
        ok = df["pa"] >= MIN_PA
    else:
        ok = (df["ip_outs"] >= MIN_IP_OUTS) | (df["games"] - df["starts"] >= MIN_RELIEF_APPS)
    q = df[ok & df[feats].notna().all(axis=1)]
    return q.sort_values(["season", "player_id"], kind="stable").reset_index(drop=True)


# ---------- 맞춤 ----------

def retention(assigned: pd.DataFrame) -> float:
    """연속 두 시즌(s, s+1)에 모두 행이 있는 선수 중 유형이 같은 비율. 그런 쌍이 없으면 NaN."""
    cur = assigned[["season", "player_id", "type"]]
    nxt = cur.assign(season=cur["season"] - 1)            # 다음 시즌 행을 한 해 당겨서 같은 키로 붙인다
    m = cur.merge(nxt, on=["season", "player_id"], suffixes=("", "_next"))
    return float((m["type"] == m["type_next"]).mean()) if len(m) else float("nan")


def _relabel_order(group: str, centers_z: np.ndarray, feats: list[str]) -> np.ndarray:
    """새 유형 번호 순서대로 늘어놓은 옛 클러스터 번호. 타자: HR% 내림차순. 투수: 선발 비중 내림차순, 다음 K% 내림차순.
    중심은 소수 6자리로 반올림해 비교한다 — 구원만 모인 군집들의 선발 비중(모두 0)이 부동소수 잡음으로 갈리지 않게."""
    centers_z = np.round(centers_z, 6)
    if group == "batter":
        return np.argsort(-centers_z[:, feats.index("hr_pct")], kind="stable")
    # np.lexsort는 마지막 키가 1순위
    return np.lexsort((-centers_z[:, feats.index("k_pct")], -centers_z[:, feats.index("start_share")]))


@_single_thread
def fit_group(df: pd.DataFrame, group: str, *, fit_seasons=FIT_SEASONS, k: int | None = None,
              agreement_floor: float = AGREEMENT_FLOOR) -> dict:
    """한 그룹(타자 또는 투수)의 군집 번들을 만든다. 맞춤에는 fit_seasons 자격 행만 쓴다.
    k를 주면 그 K로, 안 주면 K_RANGE에서 score(= 실루엣 + 유지율)가 가장 큰 K (동률이면 작은 K).
    소속 확률은 GMM 후보 중 일치도 최고(agreement_floor 이상일 때) 또는 kmeans_softmax (모듈 설명 참조)."""
    feats = FEATURES[group]
    fit_seasons = [int(s) for s in fit_seasons]
    q = qualify(df, group)
    fit = q[q["season"].isin(fit_seasons)].reset_index(drop=True)
    scaler = StandardScaler().fit(fit[feats])
    Z = scaler.transform(fit[feats])

    k_table, models = [], {}
    for kk in K_RANGE:
        km = KMeans(n_clusters=kk, n_init=10, random_state=SEED).fit(Z)
        sil = float(silhouette_score(Z, km.labels_))
        ret = retention(fit[["season", "player_id"]].assign(type=km.labels_))
        k_table.append({"k": kk, "silhouette": sil, "retention": ret, "score": sil + ret})
        models[kk] = km
    if k is None:
        k = max(k_table, key=lambda r: (r["score"], -r["k"]))["k"]
    elif k not in models:
        models[k] = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(Z)
    km = models[k]

    # 유형 번호 다시 매기기: K-means 번호는 임의라 뜻 있는 순서로 바꾼다. predict는 cluster_centers_만 보므로
    # 중심 행 순서를 바꾸고 labels_를 같은 치환으로 옮기면 된다. GMM은 바뀐 중심에서 출발해 맞추므로 성분 번호 = 유형.
    order = _relabel_order(group, km.cluster_centers_, feats)
    new_id = np.empty(k, dtype=int)
    new_id[order] = np.arange(k)
    km.cluster_centers_ = km.cluster_centers_[order].copy()
    km.labels_ = new_id[km.labels_].astype(km.labels_.dtype)

    # 소속 확률 방식 고르기: GMM 후보별 맞춤 행 일치도(최댓값 성분 == K-means 라벨)
    candidates, best = {}, None
    for cov in GMM_COVARIANCES:
        g = GaussianMixture(n_components=k, covariance_type=cov, means_init=km.cluster_centers_,
                            random_state=SEED).fit(Z)
        agr = float(np.mean(g.predict_proba(Z).argmax(axis=1) == km.labels_))
        candidates[cov] = agr
        if best is None or agr > best[1]:                 # 동률이면 먼저 나온 후보 유지
            best = (cov, agr, g)
    # kmeans_softmax의 s²: 차원당 군집 내 분산 = 각 맞춤 행에서 자기 중심까지 제곱거리의 평균 / 피처 수
    s2 = float(np.mean(((Z - km.cluster_centers_[km.labels_]) ** 2).sum(axis=1))) / len(feats)
    if best[1] >= agreement_floor:
        method, gmm = f"gmm_{best[0]}", best[2]
        member_agreement = best[1]
    else:
        method, gmm = "kmeans_softmax", None
        member_agreement = float(np.mean(
            _softmax_membership(Z, km.cluster_centers_, s2).argmax(axis=1) == km.labels_))
    pca = PCA(n_components=2, random_state=SEED, svd_solver="full").fit(Z)
    index = pd.RangeIndex(k, name="type")
    return {
        "group": group, "features": list(feats), "fit_seasons": fit_seasons, "k": int(k), "k_table": k_table,
        "scaler": scaler, "kmeans": km, "gmm": gmm, "pca": pca, "version": CLUSTER_VERSION, "n_fit": len(fit),
        # gmm_agreement = 최고 GMM 후보의 맞춤 행 일치도(비교용), membership_agreement = 선택된 방식의 일치도
        "membership_method": method, "membership_agreement": member_agreement, "gmm_agreement": best[1],
        "gmm_candidates": candidates, "softmax_s2": s2,
        "centers": pd.DataFrame(scaler.inverse_transform(km.cluster_centers_), columns=feats, index=index),
        "centers_z": pd.DataFrame(km.cluster_centers_, columns=feats, index=index),
    }


def _sq_dist(Z: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """행 x 중심 제곱 유클리드 거리 (차이를 직접 제곱해 더한다)."""
    return ((Z[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)


def _softmax_membership(Z: np.ndarray, centers: np.ndarray, s2: float) -> np.ndarray:
    """membership_t ∝ exp(-d_t² / (2·s2)), s2 = 차원당 분산(번들의 softmax_s2). 가장 큰 지수를 빼고 계산해
    넘침(underflow)을 막는다."""
    logits = -_sq_dist(Z, centers) / (2.0 * s2)
    w = np.exp(logits - logits.max(axis=1, keepdims=True))
    return w / w.sum(axis=1, keepdims=True)


@_single_thread
def assign(bundle: dict, df_rates: pd.DataFrame) -> pd.DataFrame:
    """자격 행 전부에 유형(type: K-means 가장 가까운 중심), 소속 확률(membership: 선택된 방식의 확률 리스트),
    prob(= membership[type]), 2D 좌표(x, y: PCA)를 붙인다. 맞춤 시즌 밖(2026) 행도 같은 표준화·모델로 배정한다.
    kmeans_softmax일 때 유형은 소속 확률과 같은 거리 계산의 argmin으로 정한다 — K-means predict와 같은 규칙이지만
    거리 계산식이 달라 거의 같은 거리(부동소수 동률)에서 갈릴 수 있으므로, 최댓값 성분 == 유형을 항상 지키기 위해서다."""
    feats = bundle["features"]
    out = qualify(df_rates, bundle["group"])
    Z = bundle["scaler"].transform(out[feats])
    centers = bundle["kmeans"].cluster_centers_
    if bundle.get("membership_method", "gmm_full") == "kmeans_softmax":
        mem = _softmax_membership(Z, centers, bundle["softmax_s2"])
        types = mem.argmax(axis=1).astype(int)
    else:
        types = bundle["kmeans"].predict(Z).astype(int)
        mem = bundle["gmm"].predict_proba(Z)
    xy = bundle["pca"].transform(Z)
    out["type"] = types
    out["membership"] = [row.tolist() for row in mem]
    out["prob"] = mem[np.arange(len(out)), types]
    out["x"], out["y"] = xy[:, 0], xy[:, 1]
    return out


def gmm_agreement(assigned: pd.DataFrame) -> float:
    """소속 확률(membership) 최댓값 성분이 유형과 같은 행의 비율 (배정된 행 기준). kmeans_softmax면 항상 1."""
    mem = np.array(assigned["membership"].tolist())
    return float(np.mean(mem.argmax(axis=1) == assigned["type"].to_numpy()))


@_single_thread
def similar_players(bundle: dict, assigned: pd.DataFrame, n: int = 5) -> dict[tuple[int, int], list[dict]]:
    """(season, player_id) -> 비슷한 선수-시즌 상위 n개 [{"season", "player_id", "similarity"}].
    표준화 공간의 코사인 유사도(소수 6자리로 반올림해 순위를 매긴다), 같은 player_id의 행은 모두 제외,
    동률이면 (season, player_id) 오름차순. 정규화한 행렬끼리 곱 한 번으로 모든 쌍을 계산한다."""
    a = assigned.sort_values(["season", "player_id"], kind="stable").reset_index(drop=True)
    Z = bundle["scaler"].transform(a[bundle["features"]])
    norm = np.linalg.norm(Z, axis=1, keepdims=True)
    U = Z / np.where(norm > 0, norm, 1.0)
    S = np.round(U @ U.T, 6)
    pid = a["player_id"].to_numpy()
    S[pid[:, None] == pid[None, :]] = -np.inf             # 자기 자신과 같은 선수의 다른 시즌
    # 안정 정렬: 유사도가 같으면 원래 행 순서 = (season, player_id) 오름차순
    order = np.argsort(-S, axis=1, kind="stable")[:, :n]
    seasons = a["season"].to_numpy()
    out = {}
    for i in range(len(a)):
        out[(int(seasons[i]), int(pid[i]))] = [
            {"season": int(seasons[j]), "player_id": int(pid[j]), "similarity": float(S[i, j])}
            for j in order[i] if np.isfinite(S[i, j])]
    return out


# ---------- 이름 · 품질 요약 ----------

def load_labels(path=LABELS_YAML) -> dict[str, dict[int, dict]]:
    """유형 이름표 {group: {type: {"name", "blurb"}}}. 파일이 없거나 비어 있는 유형은 "유형 {t}"/빈 설명."""
    out = {g: {t: {"name": f"유형 {t}", "blurb": ""} for t in range(max(K_RANGE))} for g in GROUPS}
    path = Path(path)
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for g in GROUPS:
            for t, v in (data.get(g) or {}).items():
                v = v or {}
                out[g][int(t)] = {"name": str(v.get("name", f"유형 {t}")), "blurb": str(v.get("blurb", ""))}
    return out


def _display_name(row: pd.Series) -> str:
    """한글 이름을 알면 한글, 아니면 박스스코어의 로마자 이름."""
    ko = row.get("name_ko")
    return ko if isinstance(ko, str) and ko else row["name"]


def _examples(assigned: pd.DataFrame, t: int, n: int) -> pd.DataFrame:
    """유형 t의 예시 행: EXAMPLE_SEASON(없으면 그 유형의 최근 시즌)에서 prob 높은 순 n개 (동률은 player_id 순)."""
    rows = assigned[assigned["type"] == t]
    if rows.empty:
        return rows
    season = EXAMPLE_SEASON if (rows["season"] == EXAMPLE_SEASON).any() else int(rows["season"].max())
    rows = rows[rows["season"] == season]
    return rows.sort_values(["prob", "player_id"], ascending=[False, True], kind="stable").head(n)


def _num(v, nd: int = 4):
    """JSON용 반올림. NaN은 None."""
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), nd)


MEMBERSHIP_NOTE = ("kmeans_softmax 소속 확률은 표준화 공간에서 각 유형 중심까지의 거리로 만든 상대적 확신도이며, "
                   "실제 빈도에 맞춰 보정(calibration)된 확률이 아니다.")


def quality(bundles: dict, assigned: dict, names_cfg: dict) -> dict:
    """model_report.json의 cluster_quality 값. bundles·assigned는 {group: 번들 / assign 결과}.
    argmax_consistent: 소속 확률 최댓값 성분 == 유형이 배정된 전체 행(2026 포함)에서 모두 성립하는가 (true/false).
        kmeans_softmax는 같은 거리 계산의 argmax로 유형을 정하므로 구조적으로 항상 true다 — 그래서 그 경우의 일치도
        숫자(항상 1.0)는 정보가 없어 적지 않는다. GMM이 선택된 경우에만 실측 일치도를 membership_agreement로 함께 적는다.
    retention도 배정된 전체 행 기준이고, k_table의 유지율과 gmm_agreement(최고 GMM 후보)·gmm_candidates(GMM vs
    K-means 비교)는 맞춤 시즌 행 기준이다. membership_note: 소속 확률을 어떻게 읽어야 하는지 (MEMBERSHIP_NOTE).
    유형의 n은 배정된 전체 행 수, n_fit은 그중 맞춤 시즌 행 수. examples는 한글 이름(name_ko 열이 있으면) 3명."""
    first = bundles[GROUPS[0]]
    out = {"version": first.get("version", CLUSTER_VERSION), "fit_seasons": list(first["fit_seasons"]),
           "membership_note": MEMBERSHIP_NOTE}
    for g in GROUPS:
        b, a = bundles[g], assigned[g]
        in_fit = a["season"].isin(b["fit_seasons"])
        labels = names_cfg.get(g, {})
        types = []
        for t in range(b["k"]):
            ex = _examples(a, t, 3)
            types.append({
                "id": t, "name": labels.get(t, {}).get("name", f"유형 {t}"),
                "n": int((a["type"] == t).sum()), "n_fit": int(((a["type"] == t) & in_fit).sum()),
                "center": {f: round(float(b["centers"].loc[t, f]), 3) for f in b["features"]},
                "examples": [_display_name(r) for _, r in ex.iterrows()],
            })
        agreement = gmm_agreement(a)
        out[g] = {
            "k": b["k"], "k_table": [{"k": r["k"], "silhouette": _num(r["silhouette"]),
                                      "retention": _num(r["retention"]), "score": _num(r["score"])}
                                     for r in b["k_table"]],
            "n_fit": int(in_fit.sum()), "n_all": len(a), "membership_method": b["membership_method"],
            "argmax_consistent": bool(agreement == 1.0), "gmm_agreement": _num(b["gmm_agreement"]),
            "gmm_candidates": {c: _num(v) for c, v in b["gmm_candidates"].items()},
            "retention": _num(retention(a)), "types": types,
        }
        if b["membership_method"] != "kmeans_softmax":
            out[g]["membership_agreement"] = _num(agreement)
    return out


# ---------- 전체 묶음 ----------

def build_from(bat: pd.DataFrame, pit: pd.DataFrame, names_ko: dict[int, str], *,
               fit_seasons=FIT_SEASONS) -> dict:
    """타자·투수 시즌표에서 전체 묶음을 만든다: {"batter": {"bundle", "assigned", "similar"}, "pitcher": {...},
    "names_ko", "version", "fit_seasons"}. assigned에는 한글 이름 열 name_ko(모르면 None)를 붙인다."""
    obj = {"version": CLUSTER_VERSION, "fit_seasons": [int(s) for s in fit_seasons], "names_ko": dict(names_ko)}
    for g, df in (("batter", bat), ("pitcher", pit)):
        r = rates(df, g)
        bundle = fit_group(r, g, fit_seasons=fit_seasons)
        a = assign(bundle, r)
        a["name_ko"] = [names_ko.get(int(p)) for p in a["player_id"]]
        obj[g] = {"bundle": bundle, "assigned": a, "similar": similar_players(bundle, a)}
    return obj


def build(seasons: list[int]) -> dict:
    """커밋된 박스스코어(seasons)에서 집계 -> 군집 -> 배정 -> 유사 선수까지 전체 묶음."""
    return build_from(batting_seasons(seasons), pitching_seasons(seasons), korean_names(seasons))


def types_map(obj: dict) -> dict[tuple[int, int], dict[str, int]]:
    """(season, player_id) -> {"batter": 유형} / {"pitcher": 유형} / 둘 다 (투타 겸업)."""
    out: dict[tuple[int, int], dict[str, int]] = {}
    for g in GROUPS:
        for s, p, t in obj[g]["assigned"][["season", "player_id", "type"]].itertuples(index=False):
            out.setdefault((int(s), int(p)), {})[g] = int(t)
    return out


def types_table(obj: dict) -> pd.DataFrame:
    """player_types.csv 내용: season, player_id, group, type, prob, x, y — (group, season, player_id) 순."""
    cols = ["season", "player_id", "group", "type", "prob", "x", "y"]
    frames = [obj[g]["assigned"].assign(group=g)[cols] for g in GROUPS]
    return pd.concat(frames).sort_values(["group", "season", "player_id"], kind="stable").reset_index(drop=True)


def profile_table(obj: dict) -> str:
    """유형 이름 붙이기(Task 4b)용 마크다운 표: K 표, 유형별 인원·원 단위 중심, 예시 선수 5명."""
    lines = []
    for g in GROUPS:
        b, a = obj[g]["bundle"], obj[g]["assigned"]
        feats = b["features"]
        in_fit = a["season"].isin(b["fit_seasons"])
        lines += [f"## {g} (K={b['k']}, n_fit={int(in_fit.sum())}, n_all={len(a)}, "
                  f"retention_all={retention(a):.3f})", "",
                  f"membership: {b['membership_method']} — agreement fit={b['membership_agreement']:.3f}, "
                  f"all={gmm_agreement(a):.3f}; softmax_s2={b['softmax_s2']:.4f}; GMM candidates (fit) "
                  + ", ".join(f"{c}={v:.3f}" for c, v in b["gmm_candidates"].items()), "",
                  "| k | silhouette | retention | score |", "|---|---|---|---|"]
        lines += [f"| {r['k']} | {r['silhouette']:.4f} | {r['retention']:.4f} | {r['score']:.4f} |"
                  for r in b["k_table"]]
        lines += ["", "| type | n_fit | n_all | " + " | ".join(feats) + " |", "|---" * (3 + len(feats)) + "|"]
        for t in range(b["k"]):
            c = b["centers"].loc[t]
            lines.append(f"| {t} | {int(((a['type'] == t) & in_fit).sum())} | {int((a['type'] == t).sum())} | "
                         + " | ".join(f"{c[f]:.3f}" for f in feats) + " |")
        lines.append("")
        for t in range(b["k"]):
            ex = _examples(a, t, 5)
            items = [f"{_display_name(r)} ({r['name']}, {r['team']}, {int(r['season'])}, p={r['prob']:.3f})"
                     for _, r in ex.iterrows()]
            lines.append(f"- type {t}: " + "; ".join(items))
        lines.append("")
    return "\n".join(lines)


# ---------- CLI ----------

def publish_site(clusters_path: Path, report_path: Path, features_path: Path, out_dir: Path,
                 seasons=ALL_SEASONS) -> dict:
    """사이트 데이터 players.json·teams.json을 out_dir에 쓴다 (site_data 참조). 두 payload를 돌려준다.
    teams.json의 model_expected(2026)에 평가 모델(report_path)과 피처 parquet(features_path)을 쓴다."""
    from . import site_data                      # site_data가 cluster를 import하므로 순환을 피해 여기서 읽는다
    from .features import load_features
    from .publish import _write_json

    if not features_path.exists():
        raise SystemExit(f"{features_path} not found — run "
                         f"`python -m kbo_predict.features --out {features_path.as_posix()}` first")
    obj, labels = load_bundle(clusters_path), load_labels()
    meta = {"generated_at": datetime.now(KST).isoformat(timespec="seconds"), "commit_sha": _commit_sha()}
    players = site_data.players_payload(obj, labels, meta)
    teams = site_data.teams_payload(seasons, obj=obj, labels=labels, features_df=load_features(features_path),
                                    report_bundle=load_bundle(report_path), meta=meta)
    _write_json(out_dir / "players.json", players, indent=None, sort_keys=True, separators=(",", ":"))  # compact
    _write_json(out_dir / "teams.json", teams, indent=1, sort_keys=True)
    return {"players": players, "teams": teams}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="선수 유형 군집: fit = 2015~2025 맞춤·2015~2026 배정, "
                                             "publish = 사이트 데이터 players.json·teams.json 발행")
    ap.add_argument("command", choices=["fit", "publish"])
    ap.add_argument("--out", default=str(CLUSTERS_PKL), help="fit: 군집 묶음 pkl 경로")
    ap.add_argument("--types", default=str(TYPES_CSV), help="fit: 선수-시즌 유형 csv 경로")
    ap.add_argument("--manifest", default=str(MANIFEST), help="fit: models/manifest.json 경로")
    ap.add_argument("--clusters", default=str(CLUSTERS_PKL), help="publish: 군집 묶음 pkl 경로")
    ap.add_argument("--report", default=str(REPORT_PKL), help="publish: 평가 모델 pkl (model_expected용)")
    ap.add_argument("--features", default=str(FEATURES_PARQUET), help="publish: 피처 parquet (model_expected용)")
    ap.add_argument("--out-dir", default=str(PUBLIC_DIR), help="publish: players.json·teams.json을 쓸 폴더")
    args = ap.parse_args(argv)
    t0 = time.time()
    if args.command == "publish":
        out = publish_site(Path(args.clusters), Path(args.report), Path(args.features), Path(args.out_dir))
        n_teams = len(out["teams"]["teams"])
        n_seasons = len({t["season"] for t in out["teams"]["teams"]})
        print(f"players.json: {len(out['players']['players'])} player-seasons; "
              f"teams.json: {n_teams} team-seasons over {n_seasons} seasons")
        print(f"done in {time.time() - t0:.1f}s")
        return
    obj = build(ALL_SEASONS)
    out, types_csv = Path(args.out), Path(args.types)
    save_bundle(obj, out)
    types_csv.parent.mkdir(parents=True, exist_ok=True)
    types_table(obj).to_csv(types_csv, index=False, float_format="%.6f", lineterminator="\n")
    meta = {"generated_at": datetime.now(KST).isoformat(timespec="seconds"), "commit_sha": _commit_sha()}
    update_manifest(Path(args.manifest), name="clusters", meta=meta, entry={
        "path": out.as_posix(), "sha256": _sha256(out), "version": CLUSTER_VERSION,
        "fit_seasons": obj["fit_seasons"], "types_sha256": _sha256(types_csv)})
    print(profile_table(obj))
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
