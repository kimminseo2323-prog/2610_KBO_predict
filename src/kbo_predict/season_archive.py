"""시즌 기록실: 사이트 "지난 시즌"(연도별 우승·한국시리즈·가을야구·최종 순위)과 "이번 시즌"(일정·순위표)이 읽는 데이터.

만드는 파일 (data/public/seasons/)
- index.json: 시즌 목록과 시즌마다 우승 팀·준우승 팀·한국시리즈 전적 (연도 고르는 칩에 쓴다).
- {season}.json: 그 시즌의 최종 순위(정규시즌), 가을야구 시리즈(이름·두 팀·전적·승자·경기별 점수), 우승 팀,
  그 시즌 모델 성적(여러 시즌 시험 backtest_report.json의 시즌별 적중률 — 그 시즌보다 앞선 시즌으로만 학습한 예측).
- schedule_{season}.json: 그 시즌 모든 경기(일정·결과)의 가벼운 목록 — 사이트가 날짜를 골라 순위표·다가오는 경기를 계산한다.

가을야구 시리즈 이름: postseason.yaml에 그 시즌이 있으면 앞에서부터 그 이름을 쓰고(진행 중인 시즌도 맞게), 없으면(지난 시즌)
뒤에서부터 한국시리즈 → 플레이오프 → 준플레이오프 → 와일드카드로 붙이고, 그보다 앞의 단판 경기는 "순위 결정전"(2021 KT-삼성
1위 결정전)으로 본다. 와일드카드는 정규시즌 4위가 1승을 안고 시작한다(2015~): 1승 1패로 끝나면 4위가 올라간다.
우승 팀은 한국시리즈에서 4승을 먼저 한 팀이다 — 아직이면 champion = None이고, index.json(지난 시즌 목록)에 넣지 않는다.

갱신: 지난 시즌 파일은 이 모듈을 직접 돌려 만든다. 매일 실행(scripts/run_pipeline.py)은 그 시즌 파일·일정·목록만 다시 쓴다(update).
실행: python -m kbo_predict.season_archive [--out data/public/seasons]
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from . import raw_store
from .postseason_eval import CODES, postseason_games
from .seasons import is_regular
from .simulate import load_postseason

SEASONS = list(range(2015, 2027))
KS_WINS = 4  # 한국시리즈 7전 4선승
ROUND_NAMES = ["한국시리즈", "플레이오프", "준플레이오프", "와일드카드"]  # 뒤에서부터


def standings(season: int, games: list[dict], upto: str | None = None) -> list[dict]:
    """정규시즌 순위 (upto 'YYYY-MM-DD' 전날까지, 없으면 시즌 끝까지). KBO 방식 승률 = 승 / (승 + 패), 무승부 제외.
    같은 승률이면 승수 많은 순, 그다음 코드 순(표시용 — 실제 KBO 동률 규정은 상대 전적이지만 여기선 단순화)."""
    rec: dict[str, dict] = {}
    for g in games:
        if g["status"] != "FINAL" or not is_regular(season, date.fromisoformat(g["date"]), g["game_id"]):
            continue
        if upto and g["date"] >= upto:
            continue
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs is None or as_ is None:
            continue
        for team, mine, theirs, home in ((g["home_code"], hs, as_, True), (g["away_code"], as_, hs, False)):
            r = rec.setdefault(team, {"code": team, "w": 0, "l": 0, "d": 0, "rs": 0, "ra": 0, "last": []})
            r["rs"] += mine
            r["ra"] += theirs
            res = "W" if mine > theirs else "L" if mine < theirs else "D"
            r["w" if res == "W" else "l" if res == "L" else "d"] += 1
            r["last"].append(res)
    rows = sorted(rec.values(), key=lambda r: (-(r["w"] / max(r["w"] + r["l"], 1)), -r["w"], r["code"]))
    top = rows[0] if rows else None
    out = []
    for i, r in enumerate(rows):
        last10 = r["last"][-10:]
        streak, s = 0, r["last"][-1] if r["last"] else None
        for x in reversed(r["last"]):
            if x != s:
                break
            streak += 1
        out.append({"rank": i + 1, "code": r["code"], "w": r["w"], "l": r["l"], "d": r["d"],
                    "pct": round(r["w"] / max(r["w"] + r["l"], 1), 3),
                    "gb": round(((top["w"] - r["w"]) + (r["l"] - top["l"])) / 2, 1),
                    "run_diff": r["rs"] - r["ra"],
                    "last10": [last10.count("W"), last10.count("L"), last10.count("D")],
                    "streak": f"{streak}{'연승' if s == 'W' else '연패' if s == 'L' else '무'}" if s else None})
    return out


def postseason_series(season: int, games: list[dict], final_table: list[dict]) -> list[dict]:
    """가을야구 시리즈 (날짜 순). 두 팀 = [정규시즌 순위 높은 팀, 낮은 팀]."""
    post = postseason_games(season, games)
    rank = {r["code"]: r["rank"] for r in final_table}
    pairs: list[frozenset] = []
    for g in post:
        p = frozenset((g["home_code"], g["away_code"]))
        if p not in pairs:
            pairs.append(p)
    try:
        names = [s["name"] for s in load_postseason(season)]
    except Exception:
        names = []
    if names and len(pairs) <= len(names):  # 대진표가 있으면 앞에서부터 (진행 중인 시즌은 아직 뒤 시리즈가 없다)
        names = names[:len(pairs)]
    else:  # 대진표가 없으면(지난 시즌) 뒤에서부터 이름을 붙인다
        names = [ROUND_NAMES[len(pairs) - 1 - i] if len(pairs) - 1 - i < len(ROUND_NAMES) else "순위 결정전"
                 for i in range(len(pairs))]
    all_by_pair = {}
    for g in games:  # 취소 경기도 보여 준다 (점수 없음)
        if g["status"] == "CANCELED" and g["date"] >= (post[0]["date"] if post else "9999"):
            all_by_pair.setdefault(frozenset((g["home_code"], g["away_code"])), []).append(g)
    out = []
    for name, p in zip(names, pairs):
        a, b = sorted(p, key=lambda t: (rank.get(t, 99), t))
        played = [g for g in post if frozenset((g["home_code"], g["away_code"])) == p]
        # 취소 경기는 시리즈 마지막 경기 전의 것만 (우천 취소). 승부가 난 뒤 취소로 남은 경기(열리지 않은 6·7차전)는 뺀다.
        rained = [g for g in all_by_pair.get(p, []) if played and g["date"] <= played[-1]["date"]]
        gs = sorted(played + rained, key=lambda g: (g["date"], g["game_id"]))
        head = [1, 0] if name == "와일드카드" else [0, 0]
        wins = list(head)
        rows = []
        for g in gs:
            done = g["status"] == "FINAL"
            w = (g["home_code"] if g["home_score"] > g["away_score"] else g["away_code"]) if done else None
            if w:
                wins[0 if w == a else 1] += 1
            rows.append({"game_id": g["game_id"], "date": g["date"], "time": g.get("time_kst"), "stadium": g.get("stadium"),
                         "home": g["home_code"], "away": g["away_code"], "status": g["status"],
                         "home_score": g["home_score"] if done else None, "away_score": g["away_score"] if done else None,
                         "winner": w})
        out.append({"name": name, "teams": [a, b], "head_start": head, "wins": wins,
                    "winner": a if wins[0] >= wins[1] else b, "games": rows})
    return out


def season_record(season: int, backtest: dict | None = None) -> dict:
    games = raw_store.load_games(season)
    table = standings(season, games)
    series = postseason_series(season, games, table)
    ks = series[-1] if series and series[-1]["name"] == "한국시리즈" else None
    champ = ks["winner"] if ks and max(ks["wins"]) >= KS_WINS else None
    model = None
    if backtest and str(season) in backtest.get("by_season", {}):
        bs = backtest["by_season"][str(season)]
        model = {"accuracy": bs[backtest["chosen"]]["accuracy"], "n": bs["n"],
                 "rule_accuracy": bs["rule_lower_starter_era"]["accuracy"],
                 "note": "그 시즌보다 앞선 시즌으로만 학습한 v0.3 설정의 정규시즌 예측 (여러 시즌 시험)"}
    return {"season": season, "champion": champ,
            "runner_up": (ks["teams"][1] if champ == ks["teams"][0] else ks["teams"][0]) if champ else None,
            "standings": table, "postseason": series, "model": model,
            "rewind": season == 2026}  # 경기일 다시 보기(예측 + 결과)가 있는 시즌


def schedule(season: int) -> list[dict]:
    return [{"game_id": g["game_id"], "date": g["date"], "time": g.get("time_kst"), "stadium": g.get("stadium"),
             "home": g["home_code"], "away": g["away_code"], "status": g["status"],
             "home_score": g.get("home_score"), "away_score": g.get("away_score"),
             "regular": is_regular(season, date.fromisoformat(g["date"]), g["game_id"])}
            for g in sorted(raw_store.load_games(season), key=lambda g: (g["date"], g["game_id"]))
            if g["home_code"] in CODES and g["away_code"] in CODES]


def _write(path: Path, obj, *, compact: bool = True) -> None:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(obj, ensure_ascii=False, indent=1)
    path.write_text(text + "\n", encoding="utf-8")


def write_index(out: Path) -> list[dict]:
    """out의 {season}.json을 읽어 우승 팀이 정해진 시즌만 index.json에 (지난 시즌 페이지의 연도 버튼)."""
    rows = []
    for p in sorted(out.glob("[0-9][0-9][0-9][0-9].json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        if not rec.get("champion"):
            continue
        ks = rec["postseason"][-1]
        rows.append({"season": rec["season"], "champion": rec["champion"], "runner_up": rec["runner_up"],
                     "final_wins": ks["wins"], "final_teams": ks["teams"]})
    _write(out / "index.json", {"seasons": rows}, compact=False)
    return rows


def update(out, season: int, *, backtest_path=None) -> dict:
    """매일 실행용: 그 시즌의 {season}.json · schedule_{season}.json을 다시 쓰고 index.json을 다시 만든다."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    bt = json.loads(Path(backtest_path).read_text(encoding="utf-8")) if backtest_path and Path(backtest_path).exists() else None
    rec = season_record(season, bt)
    _write(out / f"{season}.json", rec)
    _write(out / f"schedule_{season}.json", schedule(season))
    write_index(out)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="시즌 기록실 (지난 시즌·이번 시즌 페이지 데이터)")
    ap.add_argument("--out", default="data/public/seasons")
    ap.add_argument("--backtest", default="data/public/backtest_report.json")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    bt = json.loads(Path(args.backtest).read_text(encoding="utf-8")) if Path(args.backtest).exists() else None
    for s in SEASONS:
        _write(out / f"{s}.json", season_record(s, bt))
    _write(out / f"schedule_{SEASONS[-1]}.json", schedule(SEASONS[-1]))
    index = write_index(out)
    print(f"[season_archive] {len(index)} seasons → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
