from datetime import date, timedelta

from kbo_predict.seasons import REGULAR_SEASON, is_regular


def test_2026_regular_season_bounds():
    start, end = REGULAR_SEASON[2026]
    assert is_regular(2026, start) and is_regular(2026, end)
    assert end == date(2026, 10, 12)
    assert not is_regular(2026, end + timedelta(days=1))  # 10-13
    assert not is_regular(2026, date(2026, 10, 14))  # 포스트시즌 시작
    assert not is_regular(2026, start - timedelta(days=1))
    assert not is_regular(2026, date(2026, 3, 20))  # 시범경기
