"""scripts/reparse_boxscores.py: 캐시 HTML이 없는 경기가 두 번째 패스(한글 이름 재파싱)에서 멈추지 않는다."""
from kbo_predict import raw_store
from scripts.reparse_boxscores import main


def _box(gid: int) -> dict:
    """records_unmatched가 남아 있는 (예전 파싱) 박스스코어 한 경기."""
    row = {"player_id": 5, "name": "Hong", "order": 1, "ab": 4, "h": 1, "doubles": None, "triples": None, "sb": None}
    return {"date": "2026-04-01", "game_id": gid, "status": "FINAL",
            "batting": {"away": [row], "home": []}, "pitching": {"away": [], "home": []},
            "names_ko": {}, "records_unmatched": ["2B: 홍길동"]}


def test_second_pass_skips_game_without_cache(tmp_data_dir, tmp_path, capsys):
    raw_store.append_boxscores(2026, {77: _box(77)})
    empty_cache = tmp_path / "html"
    empty_cache.mkdir()
    assert main(["--cache", str(empty_cache), "--seasons", "2026", "--dry-run"]) == 0  # 예전에는 IndexError
    out = capsys.readouterr().out
    assert "cache-missing game_ids: [77]" in out and "dry run: nothing written" in out
