from datetime import date

from kbo_predict import collect


def test_collect_range_fetches_boxscores_only_for_new_finals(monkeypatch, tmp_data_dir, fixture_html):
    fetched = []

    def fake_fetch(path, **kw):
        fetched.append(path)
        if path.startswith("/schedule/week_of/"):
            return fixture_html("mykbo_week_2026-10-27.html")
        # 어떤 경기 페이지든 이 fixture. 요청한 경기 id로 바꿔 collect의 game_id 일치 검사를 통과시킨다.
        game_id = path.split("/")[2].split("-")[0]
        return fixture_html("mykbo_game_14048_final.html").replace("/games/14048-", f"/games/{game_id}-")

    monkeypatch.setattr(collect, "fetch_html", fake_fetch)
    out = collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0)
    assert out["games"] == 4 and out["boxscores"] == 1  # FINAL은 14052 하나
    assert [p for p in fetched if p.startswith("/games/")] == ["/games/14052-Kia-vs-Samsung-20261027"]
    fetched.clear()
    assert collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0)["boxscores"] == 0
    assert not [p for p in fetched if p.startswith("/games/")]
