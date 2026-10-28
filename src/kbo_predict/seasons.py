"""시즌 구분: 정규시즌 날짜 범위."""
import warnings
from datetime import date

# 2015~2025: scripts/season_bounds.py로 도출. 개막일 이후 FINAL/LIVE를 (날짜, game_id) 순으로 세어
# 720번째 경기(10팀 x 144경기, 이 시점에 모든 팀이 정확히 144경기)의 날짜가 종료일.
# 개막일 이전은 시범경기, 종료일 다음 경기부터는 포스트시즌(와일드카드/준PO 등).
# 2020은 코로나로 5/5 개막, 2021은 올림픽 휴식으로 10/30 종료(10/31 SS-KT 1경기는 이미 팀당 144경기 완료 후라 정규시즌 밖(1위 결정전 추정)).
# 2026 백필 결과에서 도출. 3/20~3/24(25경기, 3/25~27 공백)는 시범경기라 개막일 3/28부터 시작.
# 10/9~10/12는 추가 편성(재편성) 경기라 하루 4경기 미만이어도 정규시즌. 포스트시즌은 10/14부터.
REGULAR_SEASON: dict[int, tuple[date, date]] = {
    2015: (date(2015, 3, 28), date(2015, 10, 6)),
    2016: (date(2016, 4, 1), date(2016, 10, 9)),
    2017: (date(2017, 3, 31), date(2017, 10, 3)),
    2018: (date(2018, 3, 24), date(2018, 10, 14)),
    2019: (date(2019, 3, 23), date(2019, 10, 1)),
    2020: (date(2020, 5, 5), date(2020, 10, 31)),
    2021: (date(2021, 4, 3), date(2021, 10, 30)),
    2022: (date(2022, 4, 2), date(2022, 10, 11)),
    2023: (date(2023, 4, 1), date(2023, 10, 17)),
    2024: (date(2024, 3, 23), date(2024, 10, 1)),
    2025: (date(2025, 3, 22), date(2025, 10, 4)),
    2026: (date(2026, 3, 28), date(2026, 10, 12)),
}


def is_regular(season: int, d: date) -> bool:
    if season not in REGULAR_SEASON:
        # 새 시즌이 아직 등록되기 전에도 파이프라인이 멈추지 않도록 보수적인 3/1~10/31로 대체
        warnings.warn(f"season {season} not in REGULAR_SEASON; using fallback 03-01..10-31")
        return date(season, 3, 1) <= d <= date(season, 10, 31)
    start, end = REGULAR_SEASON[season]
    return start <= d <= end
