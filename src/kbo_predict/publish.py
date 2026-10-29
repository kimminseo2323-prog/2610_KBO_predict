"""발행 파일(latest.json / history.csv / status.json) 쓰기. 네트워크 없음."""
import json
from pathlib import Path

import pandas as pd

HISTORY_COLUMNS = [
    "date", "game_id", "home", "away", "home_win_prob",
    "model_version", "predicted_at", "status", "winner", "correct",
]


def _write_json(path, obj, *, indent: int | None = 2, sort_keys: bool = False,
                separators: tuple[str, str] | None = None) -> None:
    """UTF-8 JSON(한글 그대로) + 끝 줄바꿈. 기본값(indent=2, 키 순서 유지)은 latest/status.json 형식 그대로.
    사이트 데이터는 sort_keys=True로 바이트를 결정적으로 만든다: teams.json은 indent=1,
    players.json은 크기를 줄이려고 indent=None + separators=(",", ":") (공백 없는 compact)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=sort_keys, separators=separators)
    path.write_text(text + "\n", encoding="utf-8")


def write_latest(path, *, date: str, games: list[dict], meta: dict) -> None:
    _write_json(path, {
        "generated_at": meta.get("generated_at"),
        "date": date,
        "mode": "live",
        "model_version": meta.get("model_version"),
        "commit_sha": meta.get("commit_sha"),
        "run_url": meta.get("run_url"),
        "games": games,
    })


def write_status(path, *, mode: str, next_game_date: str | None, games_today: int, meta: dict,
                 collect_errors: list[str] | None = None) -> None:
    _write_json(path, {
        "generated_at": meta.get("generated_at"),
        "run_url": meta.get("run_url"),
        "commit_sha": meta.get("commit_sha"),
        "mode": mode,
        "next_game_date": next_game_date,
        "games_today": games_today,
        "model_version": meta.get("model_version"),
        "collect_errors": list(collect_errors or []),
    })


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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = df["game_id"].astype(str)
    order = pd.DataFrame({"d": df["date"], "k": pd.to_numeric(key, errors="coerce"), "s": key})
    idx = order.sort_values(["d", "k", "s"], kind="stable").index
    df.loc[idx].to_csv(path, index=False, encoding="utf-8")


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
