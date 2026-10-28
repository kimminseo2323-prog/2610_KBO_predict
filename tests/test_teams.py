from kbo_predict.teams import TEAMS, code_for, short_to_code


def test_historical_team_names_map_to_current_codes():
    assert code_for("Nexen Heroes") == "WO" and code_for("Kiwoom Heroes") == "WO"
    assert code_for("SK Wyverns") == "SK" and code_for("SSG Landers") == "SK"
    assert short_to_code("Nexen") == "WO" and short_to_code("SK") == "SK" and short_to_code("SSG") == "SK"


def test_ten_distinct_codes():
    assert len({v["code"] for v in TEAMS.values()}) == 10
