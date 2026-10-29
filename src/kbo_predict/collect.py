"""MyKBOStats 수집 CLI: 주간 일정 -> games.jsonl, FINAL 경기 박스스코어 -> 월별 boxscores/{YYYY-MM}.jsonl.gz."""
import argparse
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests

from kbo_predict import KST, raw_store
from kbo_predict.mykbo_client import SLEEP_S, drop_cache, fetch_html, week_path
from kbo_predict.mykbo_parse import parse_game, parse_starters, parse_week

PROGRESS_EVERY = 20
STALE_LIVE_DAYS = 2  # 이만큼 지난 LIVE 행은 경기 페이지로 확인한다 (경기 페이지가 하루쯤 늦을 수 있다)


def season_range(season: int) -> tuple[date, date]:
    return date(season, 3, 1), date(season, 11, 30)


def _fetch_box(row: dict, sleep_s: float, errors: list[dict]) -> dict | None:
    """경기 페이지 가져오기 + 파싱 + game_id 검사. 실패하면 errors에 기록하고 None.

    HTML 캐시에는 '파싱 성공 + FINAL' 페이지만 남긴다. 그 외(챌린지 페이지, 아직 LIVE 등)는
    캐시를 지워 다음 실행에서 다시 요청하게 한다.
    """
    try:
        box = parse_game(fetch_html(row["path"], sleep_s=sleep_s))
        if box["game_id"] != row["game_id"]:
            raise ValueError(f"game_id mismatch: week={row['game_id']} page={box['game_id']}")
        if box["status"] != "FINAL":
            drop_cache(row["path"])
        return box
    except (ValueError, KeyError, AttributeError, TypeError, IndexError, requests.RequestException) as e:
        drop_cache(row["path"])
        err = {"game_id": row["game_id"], "path": row["path"], "error": f"{type(e).__name__}: {e}"}
        errors.append(err)
        print(f"[collect] {err['path']}: {err['error']}", file=sys.stderr, flush=True)
        return None


def _same_score(box: dict, row: dict) -> bool:
    """경기 페이지가 FINAL이 아니어도(우천 단축 등) 주간 일정의 FINAL 점수와 양팀 점수가 같으면 받아들인다."""
    a, h = box["away"]["score"], box["home"]["score"]
    return None not in (a, h) and a == row["away_score"] and h == row["home_score"]


def collect_range(from_date: date, to_date: date, *, season: int | None = None, sleep_s: float = SLEEP_S,
                  today: date | None = None) -> dict:
    today = today or datetime.now(KST).date()
    stale_cutoff = (today - timedelta(days=STALE_LIVE_DAYS)).isoformat()
    errors: list[dict] = []
    lo, hi = from_date.isoformat(), to_date.isoformat()
    weeks = games = boxscores = 0
    done = {}  # season -> 이미 저장된 박스스코어 game_id 집합 (캐시)
    pending: dict[int, dict[int, dict]] = defaultdict(dict)

    def flush():
        nonlocal boxscores
        for s, batch in pending.items():
            boxscores += raw_store.append_boxscores(s, batch)
        pending.clear()

    fetched_games = 0
    d = from_date
    try:
        while d <= to_date:
            rows = [r for r in parse_week(fetch_html(week_path(d), sleep_s=sleep_s, use_cache=False))
                    if lo <= r["date"] <= hi and (season is None or r["season"] == season)]
            weeks += 1
            by_season = defaultdict(list)
            for r in rows:
                by_season[r["season"]].append(r)
            for s, s_rows in by_season.items():
                # 주간 일정에서 멈춘 LIVE 행: 경기 페이지가 FINAL+양팀 점수일 때만 확정 (결과를 지어내지 않는다)
                boxes = {}
                for r in s_rows:
                    if r["status"] == "LIVE" and r["date"] <= stale_cutoff:
                        box = _fetch_box(r, sleep_s, errors)
                        if box and box["status"] == "FINAL" and None not in (box["away"]["score"], box["home"]["score"]):
                            r.update(status="FINAL", away_score=box["away"]["score"], home_score=box["home"]["score"])
                            boxes[r["game_id"]] = box
                        elif box:
                            drop_cache(r["path"])  # FINAL이어도 점수가 없어 확정하지 못함 -> 다음 실행에서 다시 요청
                raw_store.upsert_games(s, s_rows)
                games += len(s_rows)
                if s not in done:
                    done[s] = set(raw_store.load_boxscores(s))
                have = done[s]
                for r in s_rows:
                    if r["status"] != "FINAL" or r["game_id"] in have:
                        continue
                    box = boxes.get(r["game_id"]) or _fetch_box(r, sleep_s, errors)
                    if box is None:
                        continue
                    if box["status"] != "FINAL" and not _same_score(box, r):
                        # 진행 중 박스스코어를 영구 저장하지 않는다. 캐시는 _fetch_box가 이미 지웠고, 다음 실행에서 다시 받는다.
                        err = {"game_id": r["game_id"], "path": r["path"],
                               "error": (f"page not final: {box['status']} {box['away']['score']}-{box['home']['score']}"
                                         f" vs week {r['away_score']}-{r['home_score']}")}
                        errors.append(err)
                        print(f"[collect] {err['path']}: {err['error']}", file=sys.stderr, flush=True)
                        continue
                    pending[s][r["game_id"]] = box
                    have.add(r["game_id"])
                    fetched_games += 1
                    if fetched_games % PROGRESS_EVERY == 0:
                        flush()
                        print(f"[collect] {fetched_games} boxscores fetched (week of {d})", file=sys.stderr, flush=True)
            d += timedelta(days=7)
    finally:
        flush()
    return {"weeks": weeks, "games": games, "boxscores": boxscores, "errors": errors}


def fetch_starters(games: list[dict], *, fetched_at: str, session=None) -> dict:
    """SCHEDULED 경기 페이지에서 예고 선발을 읽는다 (캐시 없이). 섹션이 없으면 양쪽 None(미정)으로 기록.
    받은 페이지가 그 경기 페이지가 아니면(챌린지 페이지, 다른 경기) parse_starters가 ValueError를 내고,
    여기서는 경기 단위 오류로만 남긴다 — TBA 행을 만들지 않는다."""
    starters: dict[int, dict] = {}
    errors: list[dict] = []
    for g in games:
        if g["status"] != "SCHEDULED":
            continue
        try:
            html = fetch_html(g["path"], session=session, use_cache=False)
            s = parse_starters(html, game_id=g["game_id"]) or {"away": None, "home": None}
        except (ValueError, KeyError, AttributeError, TypeError, IndexError, requests.RequestException) as e:
            err = {"game_id": g["game_id"], "path": g["path"], "error": f"{type(e).__name__}: {e}"}
            errors.append(err)
            print(f"[collect] {err['path']}: {err['error']}", file=sys.stderr, flush=True)
            continue
        starters[g["game_id"]] = {"game_id": g["game_id"], "date": g["date"], "fetched_at": fetched_at,
                                  "away": s["away"], "home": s["home"]}
    return {"starters": starters, "errors": errors}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="MyKBOStats 일정/박스스코어 수집")
    ap.add_argument("--sleep", type=float, default=SLEEP_S)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--season", type=int, help="시즌 전체 (3/1~11/30)")
    grp.add_argument("--from", dest="from_date", type=date.fromisoformat)
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat)
    args = ap.parse_args(argv)
    if args.season:
        out = collect_range(*season_range(args.season), season=args.season, sleep_s=args.sleep)
    else:
        if not args.to_date:
            ap.error("--from requires --to")
        out = collect_range(args.from_date, args.to_date, sleep_s=args.sleep)
    print(out)


if __name__ == "__main__":
    main()
