"""MyKBOStats HTTP 클라이언트. robots.txt Crawl-delay(5초)를 지키고 HTML을 로컬에 캐시한다."""
import re
import time
from datetime import date
from pathlib import Path

import requests

from kbo_predict import raw_store

BASE_URL = "https://mykbostats.com"
USER_AGENT = "Mozilla/5.0 (compatible; kbo-predict/0.1; +https://github.com/kimminseo2323-prog/2610_KBO_predict)"
SLEEP_S = 5.0
TIMEOUT_S = 20


def week_path(d: date) -> str:
    return f"/schedule/week_of/{d.isoformat()}"


def _cache_file(cache_dir: Path, path: str) -> Path:
    return cache_dir / (re.sub(r"[^A-Za-z0-9._-]+", "_", path.strip("/")) + ".html")


def drop_cache(path: str, cache_dir: Path | None = None) -> None:
    """해당 경로의 캐시 파일 삭제 (없으면 무시)."""
    if cache_dir is None:
        cache_dir = raw_store.data_dir() / "cache" / "html"
    _cache_file(cache_dir, path).unlink(missing_ok=True)


def fetch_html(path: str, *, session=None, sleep_s: float = SLEEP_S, cache_dir: Path | None = None,
               use_cache: bool = True) -> str:
    if cache_dir is None:
        cache_dir = raw_store.data_dir() / "cache" / "html"
    cached = _cache_file(cache_dir, path)
    if use_cache and cached.exists():
        return cached.read_text(encoding="utf-8")

    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    last_exc: Exception | None = None
    for _ in range(2):  # 1회 시도 + 1회 재시도
        time.sleep(sleep_s)
        try:
            resp = session.get(BASE_URL + path, timeout=TIMEOUT_S)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            last_exc = e
    else:
        raise last_exc
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_text(resp.text, encoding="utf-8")
    return resp.text
