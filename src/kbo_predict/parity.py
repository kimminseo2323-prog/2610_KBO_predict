"""parity 비교 규칙 — scripts/check_parity.py와 노트북 03·04가 같이 쓴다 (판정 기준을 한 곳에).

- first_diff / parity_compare: JSON(보고서·사이트 파일)을 키 경로까지 비교한다. 실수는 기본으로 정확히 같아야 하고,
  rel_tol을 주면 상대 오차만 허용한다 (REPORT_REL_TOL — BLAS 스레드 수·OS가 다르면 로지스틱 회귀의 마지막 자리가 바뀐다).
- same_predictions_close: 두 확률 배열이 np.allclose(rtol 0, atol PRED_ATOL)로 같은가 (번들 예측 비교).
- META_KEYS / REPORT_META_KEYS: 실행마다 달라지는 최상위 키 — 비교에서 뺀다.
같은 플랫폼이면 비트까지 같지만, 다른 OS(예: Actions의 Linux · OpenBLAS)에서도 통과하도록 노트북도 이 허용 오차를 쓴다.
"""
import json
import math
from pathlib import Path

import numpy as np

META_KEYS = ("generated_at", "commit_sha")          # 실행마다 달라지는 최상위 키 — 비교에서 뺀다
REPORT_META_KEYS = META_KEYS + ("run_url", "features_sha256")   # features_sha256 = 파일 바이트 (플랫폼 의존)
PRED_ATOL = 1e-9                                    # 번들 예측 비교 허용 오차 (cluster compare · live --skip-if-same과 같다)
REPORT_REL_TOL = 1e-9                               # 보고서 지표(실수) 비교 허용 오차 — first_diff 참조


def first_diff(a, b, path: str = "", *, rel_tol: float = 0.0) -> str | None:
    """a와 b가 처음 다른 곳의 '키 경로: 커밋본 != 재생성' 설명, 같으면 None.
    dict는 키 집합 → 키 이름 순으로, list는 길이 → 원소 순으로 내려간다. NaN끼리는 같다고 본다.
    숫자는 기본으로 정확히 같아야 한다 (같은 코드·같은 입력·같은 기계면 같은 비트). rel_tol > 0이면 실수는
    math.isclose(rel_tol=rel_tol, abs_tol=0)로 본다 (상대 오차만 — 0 근처 값을 절대 오차로 덮지 않는다) — BLAS 스레드 수·라이브러리가 다르면 로지스틱 회귀의
    마지막 자리(1e-16 수준)가 달라지므로 보고서 지표 비교에만 쓴다 (REPORT_REL_TOL)."""
    where = path or "(최상위)"
    if isinstance(a, dict) and isinstance(b, dict):
        only_a, only_b = sorted(set(a) - set(b), key=str), sorted(set(b) - set(a), key=str)
        if only_a or only_b:
            return f"{where}: 키가 다름 (커밋본에만 {only_a}, 재생성에만 {only_b})"
        for k in sorted(a, key=str):
            d = first_diff(a[k], b[k], f"{path}.{k}" if path else str(k), rel_tol=rel_tol)
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{where}: 길이 {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]", rel_tol=rel_tol)
            if d:
                return d
        return None
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return None
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))
                                       and not isinstance(a, bool) and not isinstance(b, bool)):
        return f"{where}: {a!r} ({type(a).__name__}) != {b!r} ({type(b).__name__})"
    if rel_tol and isinstance(a, float) and isinstance(b, float) and math.isclose(a, b, rel_tol=rel_tol, abs_tol=0.0):
        return None
    return None if a == b else f"{where}: {a!r} != {b!r}"


def strip_keys(obj, ignore) -> object:
    """최상위 dict에서 ignore 키를 뺀 사본 (실행 시각·커밋처럼 매번 달라지는 값)."""
    return {k: v for k, v in obj.items() if k not in ignore} if isinstance(obj, dict) else obj


def parity_compare(committed_dir, regen_dir, specs, *, rel_tol: float = 0.0) -> list[str]:
    """JSON 파일 쌍을 비교해 다른 것마다 '파일: 키 경로: 커밋본 != 재생성' 한 줄씩 돌려준다 (같으면 빈 목록).
    specs = [(커밋본 상대 경로, 재생성 상대 경로, 무시할 최상위 키들)] — 경로는 각각 committed_dir · regen_dir 기준.
    파일이 없거나 JSON으로 읽을 수 없으면 그것도 한 줄로 적는다. rel_tol은 first_diff와 같다."""
    committed_dir, regen_dir = Path(committed_dir), Path(regen_dir)
    out = []
    for c_rel, r_rel, ignore in specs:
        name = Path(c_rel).as_posix()
        try:
            a = json.loads((committed_dir / c_rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append(f"{name}: 커밋본을 읽을 수 없음 ({type(e).__name__}: {e})")
            continue
        try:
            b = json.loads((regen_dir / r_rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append(f"{name}: 재생성본을 읽을 수 없음 ({type(e).__name__}: {e})")
            continue
        d = first_diff(strip_keys(a, ignore), strip_keys(b, ignore), rel_tol=rel_tol)
        if d:
            out.append(f"{name}: {d}")
    return out


def same_predictions_close(a, b, atol: float = PRED_ATOL) -> bool:
    """두 확률 배열이 같은 모양이고 np.allclose(rtol=0, atol=atol)로 같은가 (atol 기본 1e-9 — 플랫폼 간 마지막 자리 차이만 허용)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.allclose(a, b, rtol=0.0, atol=atol))
