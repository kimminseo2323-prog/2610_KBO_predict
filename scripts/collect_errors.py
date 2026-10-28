"""status.json의 collect_errors를 GitHub 이슈 본문(마크다운)으로 요약한다.

오류가 없거나 파일이 없으면 빈 문자열을 돌려준다.
CLI: python scripts/collect_errors.py data/public/status.json
"""
import json
import sys
from pathlib import Path


def summarize(status_path: Path) -> str:
    try:
        status = json.loads(Path(status_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    errors = status.get("collect_errors") or []
    if not errors:
        return ""
    lines = [f"수집 중 오류가 발생했습니다 ({status.get('generated_at', '시각 미상')})", ""]
    lines += [f"- {e}" for e in errors]
    if status.get("run_url"):
        lines += ["", f"로그: {status['run_url']}"]
    return "\n".join(lines)


if __name__ == "__main__":
    print(summarize(Path(sys.argv[1])))
