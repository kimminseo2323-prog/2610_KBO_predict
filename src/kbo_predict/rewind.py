"""되감기(rewind): 지난 정규시즌을 하루씩 다시 돌려 보는 사이트 모드의 데이터.

하루치 파일(data/public/rewind/{season}/{YYYY-MM-DD}.json) = "이 날 모델은 이렇게 예측했고, 결과는 이랬다".
- games[]: 그날 정규시즌 FINAL·CANCELED 경기 (game_id 순). 중단된 채 남은 LIVE 등은 결과가 없으니 뺀다.
  FINAL = latest.json의 경기 항목(predict.predict_game)과 같은 모양 + result {home_score, away_score, winner, pick, correct}
  (pick = 모델이 고른 쪽 "HOME"|"AWAY", 반올림 전 확률 기준).
  CANCELED = latest.json의 취소 항목(predict.canceled_entry: home_win_prob null, factors []) + result null.
  그래서 경기가 모두 취소된 날도 파일이 있다 (전망 카드는 그대로 보인다).
  예측 모델은 평가용 고정 모델 report-2026(2015~2024 학습)이다 — 2026은 학습에 안 쓴 시험 시즌이라
  되감기 정확도가 model_report.json의 시험 정확도와 같아야 한다.
- 선발은 박스스코어의 실제 선발(투구 순서 1번)을 쓴다. 학습 피처(features.build_training_frame)도 같은 선발을 쓴다.
- outlook: 그날 경기 전 기준 가을야구 확률 카드(simulate.outlook_for — 팀 모델 team-2026).

적중(correct) 판정: 반올림 전 P(홈 승) ≥ 0.5면 홈 승 예측 — 학습 평가(train_win._correct)와 같은 규칙.
공개 칸 home_win_prob(소수 4자리)로 판정하지 않는다: 0.49997(원정 예측)이 0.5000으로 보이는 경기가 있다(13572).
무승부·점수 없는 경기는 correct = None. 시즌 정확도(index.json) = correct 합 / 승패 난 경기 수
= model_report.json의 lr 시험 정확도 (같은 702경기).

누수 방지: 그날의 상태(LeagueState)에는 그날 **전날까지** 끝난 정규시즌 경기만 들어간다. 그날·그 뒤 경기의 결과는
result 칸에만 쓰이고, 예측 확률·전망에는 들어가지 않는다 (tests/test_rewind.py가 결과를 바꿔 넣어 확인한다).

속도: 날짜마다 상태를 처음부터 쌓으면(직전 시즌 전체 포함) 느리다. build_season은 상태를 한 번 만들고
날짜순으로 이어 쌓는다 — 하루치 피처를 모두 계산한 뒤 그날 경기를 반영한다 (build_training_frame과 같은 방식).
하루만 필요하면 state_before(season, on)로 그날 직전 상태를 바로 만든다. 두 방식의 결과는 같다 (테스트).
"""
import json
from datetime import date as _date
from itertools import groupby
from pathlib import Path

import pandas as pd

from . import raw_store
from .features import LeagueState, game_features, regular_finals, starter_ids
from .predict import canceled_entry, predict_game
from .publish import _write_json
from .seasons import is_regular
from .simulate import outlook_for
from .train_win import predict_proba

MODE = "rewind"
STARTER_SOURCE = "actual (boxscore pitching order 1)"
INDEX_NOTE = ("correct = (unrounded P(home win) >= 0.5) == home won, same rule as train_win._correct; "
              "draws and canceled games are not decided")


# ---------- 상태 ----------

def _opening_state(season: int) -> LeagueState:
    """season 개막 직전 상태: 직전 시즌 정규 FINAL 전체(박스스코어 포함) → start_season(season).
    직전 시즌 데이터가 없으면(2015 등) 직전 시즌 없이 시작한다."""
    state = LeagueState()
    prev_games = raw_store.load_games(season - 1)
    if prev_games:
        state.start_season(season - 1)
        prev_boxes = raw_store.load_boxscores(season - 1)
        for g in regular_finals(prev_games, season - 1):
            state.update(g, prev_boxes.get(g["game_id"]))
    state.start_season(season)
    return state


def state_before(season: int, on: str, *, games: list[dict] | None = None,
                 boxscores: dict[int, dict] | None = None) -> LeagueState:
    """on('YYYY-MM-DD') 경기 직전 시점의 리그 상태.
    직전 시즌 정규 FINAL 전체(박스스코어 포함) → start_season(season) → 당해 시즌 on 전날까지의 정규 FINAL.
    학습(features.build_dataset)이 시즌을 이어 붙이는 방식과 같다. 직전 시즌 데이터가 없으면(2015 등) 건너뛴다.
    당해 시즌 경기·박스스코어는 games/boxscores로 넘길 수 있다 (없으면 raw_store에서 읽는다).
    on 당일 경기는 넣지 않는다 — 당일 경기 결과가 당일 예측에 새지 않게.
    점수가 없거나 무승부인 경기는 LeagueState.update가 알아서 처리한다 (학습 때와 동일)."""
    state = _opening_state(season)
    games = raw_store.load_games(season) if games is None else games
    boxes = raw_store.load_boxscores(season) if boxscores is None else boxscores
    for g in regular_finals(games, season):
        if g["date"] >= on:
            break  # regular_finals는 (date, game_id) 순
        state.update(g, boxes.get(g["game_id"]))
    return state


# ---------- 하루치 ----------

def day_rows(games: list[dict], season: int) -> list[dict]:
    """되감기 파일에 넣을 경기: 정규시즌 FINAL·CANCELED, (date, game_id) 순.
    FINAL 쪽은 features.regular_finals와 같은 경기들이다 (상태에 넣는 경기와 같은 필터)."""
    return [g for g in sorted(games, key=lambda g: (g["date"], g["game_id"]))
            if g["status"] in ("FINAL", "CANCELED")
            and is_regular(season, _date.fromisoformat(g["date"]), g["game_id"])]


def _raw_prob(bundle: dict, game: dict, state: LeagueState, starters: dict) -> float:
    """반올림 전 P(홈 승) — predict_game과 같은 피처·모델. 적중 판정에만 쓴다.
    home_win_prob(소수 4자리)로 판정하면 0.49997 같은 경기가 0.5000으로 반올림돼 '홈 승 예측'으로 뒤집힌다."""
    f = game_features(game, state, starters)
    return float(predict_proba(bundle, pd.DataFrame([{n: f[n] for n in bundle["features"]}]))[0])


def _result(game: dict, p_raw: float) -> dict:
    """경기 결과와 예측 적중 여부. 예측 규칙은 학습 평가(train_win._correct)와 같다:
    반올림 전 P(홈 승) ≥ 0.5면 홈 승으로 예측 → pick = "HOME", 아니면 "AWAY".
    사이트는 pick을 그대로 보여 준다 (home_win_prob 0.5000처럼 반올림된 값으로 다시 판정하지 않게).
    그래서 시즌 정확도가 model_report.json의 시험 정확도와 같다.
    무승부·점수 없는 경기는 correct = None (정확도 계산에서 빠진다). 취소 경기는 result 자체가 None."""
    hs, as_ = game.get("home_score"), game.get("away_score")
    if hs is None or as_ is None:
        winner = None
    else:
        winner = "HOME" if hs > as_ else "AWAY" if as_ > hs else "DRAW"
    pick = "HOME" if p_raw >= 0.5 else "AWAY"
    correct = None if winner not in ("HOME", "AWAY") else pick == winner
    return {"home_score": hs, "away_score": as_, "winner": winner, "pick": pick, "correct": correct}


def day_payload(season: int, on: str, *, games: list[dict], boxscores: dict[int, dict], bundle: dict,
                team_bundle: dict, starter_types: dict[int, dict] | None = None, meta: dict,
                state: LeagueState | None = None, ps_config=None) -> dict:
    """on 날짜의 되감기 파일 내용.
    games = 그 시즌 경기 전부(raw_store.load_games), boxscores = 그 시즌 박스스코어(raw_store.load_boxscores).
    bundle = 예측 모델(report-2026), team_bundle = 선발 없는 팀 모델(team-2026, 전망용).
    starter_types = 투수 id -> 직전 시즌 유형 {"id", "name"} (표시용, 없으면 None).
    meta = {"generated_at", "commit_sha", "run_url"(선택)}.
    state = on 경기 직전 상태. 없으면 state_before(season, on, games=games, boxscores=boxscores)로 만든다.
    정규시즌 FINAL·CANCELED 경기를 game_id 순으로 담는다 (day_rows). 취소 경기는 result = None."""
    if state is None:
        state = state_before(season, on, games=games, boxscores=boxscores)
    entries = []
    for g in sorted((g for g in day_rows(games, season) if g["date"] == on), key=lambda g: g["game_id"]):
        if g["status"] == "CANCELED":
            entries.append({**canceled_entry(g), "result": None})
            continue
        starters = starter_ids(boxscores.get(g["game_id"]))  # 실제 선발 — predict_game이 바라는 예고 선발 모양
        e = predict_game(bundle, g, state, starters, starter_types=starter_types)
        e["status_note"] = g.get("status_note")
        e["result"] = _result(g, _raw_prob(bundle, g, state, starters))
        entries.append(e)
    outlook = outlook_for(season, on, games, state=state, team_bundle=team_bundle, ps_config=ps_config)
    return {
        "generated_at": meta.get("generated_at"),
        "date": on,
        "mode": MODE,
        "model_version": bundle["version"],
        "team_model_version": team_bundle["version"],
        "starter_source": STARTER_SOURCE,
        "commit_sha": meta.get("commit_sha"),
        "run_url": meta.get("run_url"),
        "games": entries,
        "outlook": outlook,
    }


def _index_entry(payload: dict) -> dict:
    """index.json의 날짜 칸: games = 파일의 경기 수(취소 포함), decided = 적중을 따질 수 있는 경기 수."""
    decided = [g["result"]["correct"] for g in payload["games"]
               if g["result"] is not None and g["result"]["correct"] is not None]
    return {"date": payload["date"], "games": len(payload["games"]), "correct": sum(decided), "decided": len(decided)}


# ---------- 시즌 전체 ----------

def write_day(path: Path, payload: dict) -> None:
    """하루치 파일: 한 시즌 165개쯤 되므로 공백 없는 compact JSON, 키 정렬(같은 입력 → 같은 바이트)."""
    _write_json(path, payload, indent=None, sort_keys=True, separators=(",", ":"))


def build_season(season: int, *, out_dir, bundle: dict, team_bundle: dict, meta: dict,
                 dates: list[str] | None = None, starter_types: dict[int, dict] | None = None,
                 ps_config=None) -> dict:
    """season의 되감기 파일을 out_dir/{season}/{date}.json으로 쓰고 out_dir/{season}/index.json을 돌려준다.
    대상 날짜 = 정규시즌 FINAL·CANCELED 경기가 하나라도 있는 날 전부 (dates를 주면 그중 그 날짜만).
    상태는 개막 직전 상태 하나를 날짜순으로 이어 쌓는다: 그날 피처·전망을 모두 계산한 뒤 그날 경기를 반영.
    dates를 주면 기존 index.json의 나머지 날짜는 그대로 두고 그 날짜 칸만 바꾼다 (일부만 다시 만들 때).
    dates의 검사는 파일을 하나라도 쓰기 전에 모두 한다 (ValueError) — 빈 목록, 시즌에 없는 날짜,
    기존 index.json의 model_version이 이번 번들과 다름(다른 모델의 날짜와 섞인 정확도가 나오지 않게).
    index.json = {"season", "model_version", "generated_at", "commit_sha",
                  "dates": [{"date", "games", "correct", "decided"}], "accuracy", "n_decided", "note"}."""
    season_dir = Path(out_dir) / str(season)
    index_path = season_dir / "index.json"
    games = raw_store.load_games(season)
    boxes = raw_store.load_boxscores(season)
    wanted = None if dates is None else set(dates)
    old_index = None
    if wanted is not None:  # 쓰기 전에 모두 검사한다
        if not wanted:
            raise ValueError("dates is empty (pass None to rebuild the whole season)")
        missing = sorted(wanted - {g["date"] for g in day_rows(games, season)})
        if missing:
            raise ValueError(f"no regular-season FINAL/CANCELED games on {missing} in season {season}")
        if index_path.exists():
            old_index = json.loads(index_path.read_text(encoding="utf-8"))
            if old_index.get("model_version") != bundle["version"]:
                raise ValueError(f"{index_path} was built with model_version {old_index.get('model_version')!r}, "
                                 f"not {bundle['version']!r}; rebuild the whole season instead of merging dates")
    state = _opening_state(season)
    entries: dict[str, dict] = {}
    for on, grp in groupby(day_rows(games, season), key=lambda g: g["date"]):
        day_games = list(grp)
        if wanted is None or on in wanted:
            payload = day_payload(season, on, games=games, boxscores=boxes, bundle=bundle, team_bundle=team_bundle,
                                  starter_types=starter_types, meta=meta, state=state, ps_config=ps_config)
            write_day(season_dir / f"{on}.json", payload)
            entries[on] = _index_entry(payload)
            if wanted is not None and wanted <= entries.keys():
                break  # 요청한 날짜를 다 만들었으면 나머지 시즌은 쌓지 않는다
        for g in day_games:
            if g["status"] == "FINAL":  # 취소 경기는 상태에 넣지 않는다 (= regular_finals만 쌓는 state_before와 같다)
                state.update(g, boxes.get(g["game_id"]))
    if old_index is not None:
        entries = {**{d["date"]: d for d in old_index.get("dates", [])}, **entries}
    rows = [entries[d] for d in sorted(entries)]
    n_decided = sum(r["decided"] for r in rows)
    n_correct = sum(r["correct"] for r in rows)
    index = {
        "season": season,
        "model_version": bundle["version"],
        "generated_at": meta.get("generated_at"),
        "commit_sha": meta.get("commit_sha"),
        "dates": rows,
        "accuracy": round(n_correct / n_decided, 4) if n_decided else None,
        "n_decided": n_decided,
        "note": INDEX_NOTE,
    }
    _write_json(index_path, index, indent=1)
    return index
