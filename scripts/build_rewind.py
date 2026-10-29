"""되감기(rewind) JSON 만들기: data/public/rewind/{season}/{YYYY-MM-DD}.json + index.json.

    python -X utf8 scripts/build_rewind.py --season 2026
    python -X utf8 scripts/build_rewind.py --season 2026 --dates 2026-05-01,2026-05-02   # 일부 날짜만 다시

예측 모델 = 평가용 고정 모델 models/report-2026.pkl (2015~2024 학습, 2026은 시험 시즌),
전망(가을야구 확률) = 선발 없는 팀 모델 models/team-2026.pkl. 선발 유형 표시는 models/clusters.pkl(없으면 생략).
clusters.pkl이 있는데 읽지 못하면(깨짐, 이름표 없음 등) 유형 없이 만들지 않고 멈춘다 (exit 1) —
되감기 파일은 커밋되는 결과물이라 같은 입력이면 같은 파일이 나와야 한다 (조용히 type이 null로 바뀌지 않게).
--dates는 파일을 쓰기 전에 모두 검사한다: 빈 목록, 정규시즌 경기가 없는 날짜, 기존 index.json의 모델 버전이 다르면 exit 1.
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

# 기본 경로는 저장소 루트(ROOT) 기준 — 어느 폴더에서 실행해도 같은 파일을 읽고 쓴다 (데이터 폴더는 KBO_DATA_DIR, 기본 data/)
OUT_DIR = ROOT / "data" / "public" / "rewind"
REPORT_PKL = ROOT / "models" / "report-2026.pkl"
TEAM_PKL = ROOT / "models" / "team-2026.pkl"
CLUSTERS_DEFAULT = ROOT / CLUSTERS_PKL                   # run_pipeline.CLUSTERS_PKL(작업 폴더 기준)을 루트 기준으로


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="정규시즌 되감기 JSON 생성")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--dates", help="쉼표로 구분한 YYYY-MM-DD 목록 (기본: 정규시즌 경기가 있는 날 전부)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--model", type=Path, default=REPORT_PKL)
    ap.add_argument("--team-model", type=Path, default=TEAM_PKL)
    ap.add_argument("--clusters", type=Path, default=CLUSTERS_DEFAULT, help="선발 유형 군집 파일 (없으면 유형 생략)")
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    meta = {"generated_at": datetime.now(KST).isoformat(timespec="seconds"), "commit_sha": _commit_sha(),
            "run_url": None}
    # 선발 유형: 파일이 없으면 None(유형 생략). 있는데 못 읽으면 멈춘다 (재현성 — 모듈 docstring)
    try:
        sp_types = starter_types(args.clusters, args.season)
    except Exception as e:
        raise SystemExit(f"[rewind] {args.clusters} exists but cannot be used for starter types: {e!r}") from e
    if sp_types is None:
        print(f"[rewind] {args.clusters} not found; starter types will be null", file=sys.stderr)
    # --dates ""처럼 비어 있어도 시즌 전체로 바뀌지 않게: 옵션을 줬으면 목록(빈 목록이면 build_season이 거절)
    dates = [d.strip() for d in args.dates.split(",") if d.strip()] if args.dates is not None else None
    # 날짜 검사에 걸리면 build_season이 아무것도 쓰기 전에 ValueError를 낸다 (그대로 올라가 exit 1)
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
