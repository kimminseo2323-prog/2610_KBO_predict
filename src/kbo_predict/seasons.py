"""시즌 구분: 정규시즌 날짜 범위."""
from datetime import date

# 2026 백필 결과에서 도출. 3/20~3/24(25경기, 3/25~27 공백)는 시범경기라 개막일 3/28부터 시작.
# 10/9~10/12는 추가 편성(재편성) 경기라 하루 4경기 미만이어도 정규시즌. 포스트시즌은 10/14부터.
REGULAR_SEASON: dict[int, tuple[date, date]] = {
    2026: (date(2026, 3, 28), date(2026, 10, 12)),
}


def is_regular(season: int, d: date) -> bool:
    start, end = REGULAR_SEASON[season]
    return start <= d <= end
