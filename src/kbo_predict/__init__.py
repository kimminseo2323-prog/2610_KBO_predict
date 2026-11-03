from zoneinfo import ZoneInfo

__version__ = "0.1.0"
MODEL_VERSION = "v0.3"  # v0.3 (2026-11): 로지스틱 L1 C=0.03 + Elo 피처 (v0.2: L2 C=1, 피처 26개)
REPORT_VERSION = "report-2026"
TEAM_VERSION = "team-2026"
# report-2026 · team-2026 · clusters-2026이 얼려 둔 시즌 (scripts/check_parity.py는 이 시즌만으로 다시 만들어 비교한다 —
# 2027 경기가 쌓여도 얼린 산출물의 parity가 깨지지 않게)
FROZEN_SEASONS = list(range(2015, 2027))
KST = ZoneInfo("Asia/Seoul")
