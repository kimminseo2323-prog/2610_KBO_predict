"""네이버 스포츠 비공식 JSON API 클라이언트 (개인 학습용)."""
import time
from datetime import date

import requests

BASE_URL = "https://api-gw.sports.naver.com"
USER_AGENT = (
    "Mozilla/5.0 (compatible; kbo-predict/0.1; "
    "+https://github.com/kimminseo2323-prog/2610_KBO_predict)"
)


def _get(session: requests.Session, url: str, sleep_s: float) -> dict:
    """요청 전 sleep, 실패 시 1회 재시도 후 예외 전파."""
    last_exc: Exception | None = None
    for _ in range(2):
        time.sleep(sleep_s)
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
    raise last_exc


def _session(session: requests.Session | None) -> requests.Session:
    if session is None:
        session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def fetch_games(
    from_date: date,
    to_date: date,
    *,
    session: requests.Session | None = None,
    sleep_s: float = 1.0,
) -> list[dict]:
    url = (
        f"{BASE_URL}/schedule/games?fields=basic,schedule,baseball"
        f"&upperCategoryId=kbaseball&categoryId=kbo"
        f"&fromDate={from_date.isoformat()}&toDate={to_date.isoformat()}&size=500"
    )
    data = _get(_session(session), url, sleep_s)
    return [g for g in data["result"]["games"] if g.get("categoryId") == "kbo"]


def fetch_record(
    game_id: str,
    *,
    session: requests.Session | None = None,
    sleep_s: float = 1.0,
) -> dict:
    url = f"{BASE_URL}/schedule/games/{game_id}/record"
    return _get(_session(session), url, sleep_s)["result"]["recordData"]
