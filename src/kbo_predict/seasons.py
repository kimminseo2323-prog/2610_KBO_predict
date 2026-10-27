"""시즌 구분: 정규시즌 날짜 범위."""
from datetime import date

# 값은 2026 백필(Step 13) 후 채운다.
REGULAR_SEASON: dict[int, tuple[date, date]] = {}


def is_regular(season: int, d: date) -> bool:
    start, end = REGULAR_SEASON[season]
    return start <= d <= end
