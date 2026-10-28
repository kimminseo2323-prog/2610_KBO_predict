"""KBO 구단 코드 매핑 (MyKBOStats 풀네임 / 박스스코어 짧은 이름 -> KBO 팀 코드)."""

TEAMS: dict[str, dict] = {
    "Doosan Bears": {"code": "OB", "ko": "두산"},
    "Lotte Giants": {"code": "LT", "ko": "롯데"},
    "KT Wiz": {"code": "KT", "ko": "KT"},
    "Kiwoom Heroes": {"code": "WO", "ko": "키움"},
    "SSG Landers": {"code": "SK", "ko": "SSG"},
    "Samsung Lions": {"code": "SS", "ko": "삼성"},
    "Hanwha Eagles": {"code": "HH", "ko": "한화"},
    "Kia Tigers": {"code": "HT", "ko": "KIA"},
    "LG Twins": {"code": "LG", "ko": "LG"},
    "NC Dinos": {"code": "NC", "ko": "NC"},
    # 옛 구단명 (현재 코드로 연결)
    "Nexen Heroes": {"code": "WO", "ko": "넥센"},  # 2015~2018, 이후 키움
    "SK Wyverns": {"code": "SK", "ko": "SK"},  # 2015~2020, 이후 SSG
}

# 짧은 이름 = 풀네임의 첫 단어 (예: "Kia Tigers" -> "Kia")
_SHORT = {name.split()[0]: info["code"] for name, info in TEAMS.items()}


def code_for(full_name: str) -> str:
    return TEAMS[full_name]["code"]


def short_to_code(short: str) -> str:
    return _SHORT[short]
