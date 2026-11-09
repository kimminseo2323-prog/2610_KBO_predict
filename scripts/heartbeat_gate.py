"""비시즌 빈 커밋 거르기: 커밋할 변경이 status.json뿐일 때 일일 워크플로가 부른다.

직전 커밋의 status.json(git show HEAD:…)과 지금 파일을 publish.heartbeat_only로 비교해,
건너뛰어도 되면(비시즌·오늘 이미 갱신·시각만 바뀜) 종료 코드 0, 커밋해야 하면 1.
CLI: python scripts/heartbeat_gate.py [data/public/status.json]
"""
import json
import subprocess
import sys
from pathlib import Path

from kbo_predict.publish import heartbeat_only


def main(argv=None) -> int:
    path = Path((argv or sys.argv[1:] or ["data/public/status.json"])[0])
    new = json.loads(path.read_text(encoding="utf-8"))
    try:
        old = json.loads(subprocess.run(["git", "show", f"HEAD:{path.as_posix()}"], capture_output=True, check=True,
                                        text=True, encoding="utf-8").stdout)
    except (subprocess.CalledProcessError, ValueError):
        old = None  # 처음 만드는 파일이거나 읽을 수 없으면 커밋한다
    skip = heartbeat_only(old, new)
    print("skip: status.json만 바뀌었고 오늘(KST) 이미 갱신함 (비시즌)" if skip else "commit")
    return 0 if skip else 1


if __name__ == "__main__":
    sys.exit(main())
