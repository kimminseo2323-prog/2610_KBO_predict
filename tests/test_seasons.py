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


def test_regular_season_covers_2015_to_2026():
    assert set(REGULAR_SEASON) == set(range(2015, 2027))
    for s, (start, end) in REGULAR_SEASON.items():
        assert start.year == s == end.year and start < end


def test_unknown_season_falls_back_with_warning():
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert is_regular(2027, date(2027, 5, 1)) and not is_regular(2027, date(2027, 11, 1))
    assert w and "fallback" in str(w[0].message)
