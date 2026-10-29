"""커밋된 data/raw(2015~2026)로 전체 데이터셋을 만들어 보는 테스트. 모듈당 한 번만 만든다."""
import pytest

from kbo_predict.features import build_dataset, starter_ids

# = 정규 FINAL − 무승부 (data/raw/{season}/games.jsonl 기준)
EXPECTED_ROWS = {2015: 715, 2016: 713, 2017: 709, 2018: 714, 2019: 713, 2020: 707,
                 2021: 670, 2022: 707, 2023: 707, 2024: 710, 2025: 698, 2026: 702}


@pytest.fixture(scope="module")
def real_df():
    return build_dataset(sorted(EXPECTED_ROWS))


def test_dataset_row_counts_per_season(real_df):
    assert real_df.groupby("season").size().to_dict() == EXPECTED_ROWS


def test_no_nan_in_team_core_after_first_week(real_df):
    # 2020년은 5월 5일 개막이라 날짜(4/15) 대신 '팀이 10경기 이상 치른 뒤'로 자른다 (season_progress = 경기수/144)
    late = real_df[real_df.season_progress * 144 >= 10]
    assert len(late) > 7000
    assert not late[["win_pct_diff", "obp_diff", "era_diff"]].isna().any().any()


def test_starter_known_rate_high(real_df):
    # starter_known=0은 박스스코어가 없어서가 아니라 '기록 없는 신인 선발'이 나온 경기다
    # (박스스코어·선발은 전 경기에 있음: 아래 test_every_game_has_two_starters). 실측 0.963.
    assert real_df.starter_known.mean() >= 0.95


def test_every_game_has_two_starters(real_df):
    from kbo_predict import raw_store

    for season in sorted(EXPECTED_ROWS):
        boxes = raw_store.load_boxscores(season)
        ids = real_df.loc[real_df.season == season, "game_id"]
        assert all(None not in starter_ids(boxes[g]).values() for g in ids), season


def test_records_coverage():
    # 재파싱 뒤: 정규시즌 FINAL 박스스코어의 99% 이상에 기록표 칸이 있고, 전체 unmatched 항목은 200개 미만
    from kbo_predict import raw_store
    missing = unmatched = total = 0
    for season in sorted(EXPECTED_ROWS):
        for b in raw_store.load_boxscores(season).values():
            total += 1
            rows = b["batting"]["away"] + b["batting"]["home"]
            missing += rows[0]["doubles"] is None if rows else 1
            unmatched += len(b.get("records_unmatched", []))
    print(f"missing={missing} total={total} unmatched={unmatched}")
    assert missing / total < 0.01 and unmatched < 200
