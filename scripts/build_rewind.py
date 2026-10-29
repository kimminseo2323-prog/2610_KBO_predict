"""되감기(rewind) JSON 만들기: data/public/rewind/{season}/{YYYY-MM-DD}.json + index.json.

    python -X utf8 scripts/build_rewind.py --season 2026
    python -X utf8 scripts/build_rewind.py --season 2026 --dates 2026-05-01,2026-05-02   # 일부 날짜만 다시

예측 모델 = 평가용 고정 모델 models/report-2026.pkl (2015~2024 학습, 2026은 시험 시즌),
전망(가을야구 확률) = 선발 없는 팀 모델 models/team-2026.pkl. 선발 유형 표시는 models/clusters.pkl(없으면 생략).
끝나면 날짜 수 · 정확도 · 총 크기 · 걸린 시간을 출력한다.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT):  # `python scripts/build_rewind.py`로 실행해도 kbo_predict·scripts를 찾게
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from kbo_predict import KST  # noqa: E402
from kbo_predict.rewind import build_season  # noqa: E402
from kbo_predict.simulate import load_postseason  # noqa: E402
from kbo_predict.train_win import _commit_sha, load_bundle  # noqa: E402
from scripts.run_pipeline import CLUSTERS_PKL, starter_types  # noqa: E402

OUT_DIR = Path("data/public/rewind")
REPORT_PKL = Path("models/report-2026.pkl")
TEAM_PKL = Path("models/team-2026.pkl")


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="정규시즌 되감기 JSON 생성")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--dates", help="쉼표로 구분한 YYYY-MM-DD 목록 (기본: 정규시즌 경기가 있는 날 전부)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--model", type=Path, default=REPORT_PKL)
    ap.add_argument("--team-model", type=Path, default=TEAM_PKL)
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    meta = {"generated_at": datetime.now(KST).isoformat(timespec="seconds"), "commit_sha": _commit_sha(),
            "run_url": None}
    try:  # 선발 유형은 표시용 — 없거나 깨졌으면 유형 없이 만든다
        sp_types = starter_types(CLUSTERS_PKL, args.season)
    except Exception as e:
        sp_types = None
        print(f"[rewind] starter types unavailable, continuing without them: {e!r}", file=sys.stderr)
    dates = [d.strip() for d in args.dates.split(",") if d.strip()] if args.dates else None
    index = build_season(args.season, out_dir=args.out_dir, bundle=load_bundle(args.model),
                         team_bundle=load_bundle(args.team_model), meta=meta, dates=dates,
                         starter_types=sp_types, ps_config=load_postseason(args.season))
    season_dir = args.out_dir / str(args.season)
    size = sum(p.stat().st_size for p in season_dir.glob("*.json"))
    n_correct = sum(d["correct"] for d in index["dates"])
    print(f"[rewind] {args.season}: {len(index['dates'])} dates, accuracy {index['accuracy']} "
          f"({n_correct}/{index['n_decided']}), {size / 1e6:.2f} MB, {time.perf_counter() - t0:.1f} s")
    return index


if __name__ == "__main__":
    main()
