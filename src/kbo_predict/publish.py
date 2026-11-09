"""발행 파일(latest.json / history.csv / status.json) 쓰기. 네트워크 없음.
모든 쓰기는 원자적이다: 같은 폴더의 .tmp에 다 쓴 뒤 os.replace로 바꿔치기한다 (_atomic_write).
쓰는 도중 실패해도(디스크·직렬화 오류, Actions 중단) 기존 파일은 그대로 남고 반쯤 쓴 파일이 커밋되지 않는다."""
import json
import os
from pathlib import Path

import pandas as pd

HISTORY_COLUMNS = [
    "date", "game_id", "home", "away", "home_win_prob",
    "model_version", "predicted_at", "status", "winner", "correct",
]


def _atomic_write(path, write) -> None:
    """write(tmp)로 path와 같은 폴더의 path.tmp에 쓴 뒤 os.replace(tmp, path).
    어디서 실패하든 .tmp는 지우고 예외를 다시 낸다 (바꿔치기 전이므로 기존 path는 그대로).
    raw_store.rewrite_boxscores · upsert_games와 같은 방식."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        write(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)  # 성공했으면 이미 바꿔치기돼 없다


def _write_json(path, obj, *, indent: int | None = 2, sort_keys: bool = False,
                separators: tuple[str, str] | None = None) -> None:
    """UTF-8 JSON(한글 그대로) + 끝 줄바꿈. 기본값(indent=2, 키 순서 유지)은 latest/status.json 형식 그대로.
    사이트 데이터는 sort_keys=True로 바이트를 결정적으로 만든다: teams.json은 indent=1,
    players.json은 크기를 줄이려고 indent=None + separators=(",", ":") (공백 없는 compact).
    직렬화를 먼저 끝낸 뒤 원자적으로 쓴다 (_atomic_write)."""
    text = json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=sort_keys, separators=separators)
    _atomic_write(path, lambda tmp: tmp.write_text(text + "\n", encoding="utf-8"))


def write_latest(path, *, date: str, games: list[dict], meta: dict, outlook: dict | None = None) -> None:
    """latest.json. outlook = 전망 카드(simulate.outlook_for의 series / playoff_race / next_game) 또는 None."""
    _write_json(path, {
        "generated_at": meta.get("generated_at"),
        "date": date,
        "mode": "live",
        "model_version": meta.get("model_version"),
        "commit_sha": meta.get("commit_sha"),
        "run_url": meta.get("run_url"),
        "games": games,
        "outlook": outlook,
    })


def write_status(path, *, mode: str, next_game_date: str | None, games_today: int, meta: dict,
                 collect_errors: list[str] | None = None, season_result: dict | None = None) -> None:
    """status.json. season_result = simulate.season_result (한국시리즈가 끝났으면 우승 팀·전적, 아니면 None)."""
    _write_json(path, {
        "generated_at": meta.get("generated_at"),
        "run_url": meta.get("run_url"),
        "commit_sha": meta.get("commit_sha"),
        "mode": mode,
        "next_game_date": next_game_date,
        "games_today": games_today,
        "model_version": meta.get("model_version"),
        "collect_errors": list(collect_errors or []),
        "season_result": season_result,
    })


HEARTBEAT_KEYS = ("generated_at", "run_url", "commit_sha")  # 실행할 때마다 바뀌는 칸 (내용이 아니라 "언제 돌았나")


def heartbeat_only(old: dict | None, new: dict) -> bool:
    """비시즌에 커밋을 건너뛸지: 바뀐 것이 실행 시각뿐이고, 오늘(KST) 이미 한 번 갱신했으면 True.

    비시즌에도 예약 실행은 하루 최대 12번 돈다(Cloudflare 6 + GitHub 예비 6). 매번 status.json의 시각만 바꾼 커밋을
    남기면 겨울 넉 달에 1,000개가 넘는 빈 커밋이 쌓인다 — 그래서 비시즌(mode "rewind", 다음 경기 없음)에는 하루 첫 실행만 남긴다.
    시즌 중, 다음 경기가 잡힌 뒤, 수집 오류가 있을 때, 시각 말고 다른 칸이 바뀌었을 때는 항상 커밋한다(False).
    generated_at은 KST(+09:00) ISO 문자열이라 앞 10자가 KST 날짜다."""
    if not old or new.get("mode") != "rewind" or new.get("next_game_date") or new.get("collect_errors"):
        return False
    body = lambda d: {k: v for k, v in d.items() if k not in HEARTBEAT_KEYS}  # noqa: E731
    return body(old) == body(new) and str(old.get("generated_at"))[:10] == str(new.get("generated_at"))[:10]


def _read_history(path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        df = pd.DataFrame(columns=HISTORY_COLUMNS)
    else:
        df = pd.read_csv(path, dtype={"game_id": str, "winner": str, "status": str}, keep_default_na=True)
        df = df.reindex(columns=HISTORY_COLUMNS)
    df["correct"] = df["correct"].astype("Int64")
    df["winner"] = df["winner"].astype(object)
    return df


def _write_history(path, df: pd.DataFrame) -> None:
    key = df["game_id"].astype(str)
    order = pd.DataFrame({"d": df["date"], "k": pd.to_numeric(key, errors="coerce"), "s": key})
    idx = order.sort_values(["d", "k", "s"], kind="stable").index
    out = df.loc[idx]
    _atomic_write(path, lambda tmp: out.to_csv(tmp, index=False, encoding="utf-8"))


def upsert_history(path, predictions: list[dict], *, predicted_at: str, model_version: str | None = None) -> None:
    """경기 전(SCHEDULED) 예측을 history.csv에 넣거나 갱신한다 (FINAL로 정산된 행은 건드리지 않는다).
    model_version: 실제로 예측한 번들의 버전(run_pipeline은 meta["model_version"] = bundle["version"]을 넘긴다).
    예측 항목에 model_version이 있으면 그것이 우선. 둘 다 없으면 ValueError — 패키지 상수로 짐작하지 않는다."""
    df = _read_history(path)
    for p in predictions:
        if p.get("status") != "SCHEDULED":  # 공개 기록은 경기 전 예측만
            continue
        version = p.get("model_version") or model_version
        if not version:
            raise ValueError(f"model_version missing for game {p['game_id']} (pass model_version=bundle version)")
        gid = str(p["game_id"])
        hit = df.index[df["game_id"] == gid]
        if len(hit):
            i = hit[0]
            if df.at[i, "status"] == "FINAL":
                continue
            df.at[i, "home_win_prob"] = p["home_win_prob"]
            df.at[i, "predicted_at"] = predicted_at
            df.at[i, "status"] = p["status"]
            df.at[i, "model_version"] = version
        else:
            row = {
                "date": p["date"], "game_id": gid,
                "home": p["home"]["code"], "away": p["away"]["code"],
                "home_win_prob": p["home_win_prob"],
                "model_version": version,
                "predicted_at": predicted_at, "status": p["status"],
                "winner": None, "correct": pd.NA,
            }
            df.loc[len(df)] = row
    df["correct"] = df["correct"].astype("Int64")
    _write_history(path, df)


def drop_history(path, game_ids: set[int]) -> int:
    """정산 전(SCHEDULED) 행 중 game_ids에 든 것(승부가 난 시리즈의 열리지 않을 경기)을 지운다. 지운 행 수."""
    df = _read_history(path)
    ids = {str(i) for i in game_ids}
    drop = df.index[df["game_id"].isin(ids) & (df["status"] == "SCHEDULED")]
    if len(drop):
        _write_history(path, df.drop(drop).reset_index(drop=True))
    return len(drop)


def settle_history(path, games: list[dict]) -> int:
    df = _read_history(path)
    by_id = {str(g["game_id"]): g for g in games}
    n = 0
    for i in df.index[df["winner"].isna()]:
        g = by_id.get(df.at[i, "game_id"])
        if g is None:
            continue
        if g["status"] == "FINAL" and g["home_score"] is not None and g["away_score"] is not None:
            hs, as_ = g["home_score"], g["away_score"]
            winner = "HOME" if hs > as_ else "AWAY" if as_ > hs else "DRAW"
            prob = float(df.at[i, "home_win_prob"])
            df.at[i, "winner"] = winner
            df.at[i, "status"] = "FINAL"
            if winner == "HOME":
                df.at[i, "correct"] = int(prob >= 0.5)
            elif winner == "AWAY":
                df.at[i, "correct"] = int(prob < 0.5)
            n += 1
        elif g["status"] == "CANCELED" and df.at[i, "status"] != "CANCELED":
            df.at[i, "status"] = "CANCELED"
            n += 1
    if n:
        _write_history(path, df)
    return n
