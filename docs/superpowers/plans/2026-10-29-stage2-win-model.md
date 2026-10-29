# 2단계: 피처 + 승패 모델 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2015~2026 정규시즌 데이터로 누수 없는 팀·선발투수 피처를 만들고, 로지스틱 회귀 + LightGBM 승패 모델을 시즌 분할로 검증·캘리브레이션해 `model_report.json`(report-2026)과 라이브 모델 v0.2를 만든다. 노트북 02·03이 같은 함수를 호출해 같은 숫자를 낸다.

**Architecture:** 로직은 `src/kbo_predict/`에만 쓴다. `features.LeagueState`가 경기·박스스코어를 날짜순으로 누적해 "그 경기 이전" 팀·투수 상태를 주고, `game_features`가 홈−원정 차이 피처를 만든다. 학습용 선발은 박스스코어 투수 1번, 라이브 선발은 예정 경기 페이지의 "Starting pitchers" 섹션(이번 계획에서 새로 파싱)에서 온다. `train_win`이 두 알고리즘을 같은 인터페이스(`fit_model`/`predict_proba`/`explain`)로 감싸고, 캘리브레이션은 2025 검증 시즌에서 고른다. 요인 분해는 LightGBM 내장 TreeSHAP(`pred_contrib`)과 LR 선형 기여로 계산해 `shap` 패키지 없이 간다. 피처 테이블은 `data/processed/features.parquet`(git 제외)로 저장하고 SHA256을 `models/manifest.json`에 적는다.

**Tech Stack:** Python 3.12, pandas, scikit-learn 1.6.1, lightgbm 4.7.0, pyarrow 26.0.0, joblib, beautifulsoup4, nbformat/nbclient, pytest.

**Spec:** `docs/superpowers/specs/2026-10-27-kbo-predict-design.md` (5.1 승패 예측, 5.3 재현성, 6절 노트북 규칙, 8절 데이터 계약, 12절 2단계). 이월 항목: `docs/superpowers/plans/2026-10-27-stage0-deferred.md` "2단계 전에" 절.

## Global Constraints

- 모든 피처는 **경기 당일 이전** 데이터만 쓴다. 같은 날짜의 다른 경기 결과도 쓰지 않는다 (`build_training_frame`: 날짜 그룹의 피처를 모두 만든 뒤 상태 갱신). 학습·평가는 정규시즌(`seasons.is_regular(season, date, game_id)`) FINAL 경기 중 무승부 제외.
- 재현성: `seed=42`, LightGBM `deterministic=True, num_threads=1, seed=42, bagging 없음`, LR `random_state=42`. 같은 입력으로 두 번 학습하면 확률이 비트 단위로 같아야 한다.
- 모델 두 벌: `report`(2015~2024 학습, 2025 검증, 2026 홀드아웃, `model_version="report-2026"`, 파일 `models/report-2026.pkl` + `data/public/model_report.json`)과 `live`(2015~2026 전체 학습, `model_version="v0.2"`, 파일 `models/win_model.pkl`). 주간 재학습(4단계)은 `report-2026` 파일을 덮어쓰지 않는다.
- `pred_contrib`/선형 기여 합 항등식: `Σ contrib + base == 캘리브레이션 전 로짓` (atol 1e-6).
- 공개 파일 계약(`latest.json`, `history.csv`, `status.json`)의 기존 키·모양은 바꾸지 않는다. 키 추가만 허용 (`home.starter` 블록 채우기, `factors`는 |pp| 상위 5개).
- 네트워크: 요청 간 5초, UA `Mozilla/5.0 (compatible; kbo-predict/0.1; +https://github.com/kimminseo2323-prog/2610_KBO_predict)`. 예정(SCHEDULED) 경기 페이지는 캐시하지 않는다. 우회 코드 금지.
- 노트북: 로직은 `src/`에 한 번만, 노트북은 호출만 한다. 맨 위 마크다운 셀에 "하는 일 / 왜 / 짝 `.py`". 코드 셀마다 바로 위에 한국어 설명(무엇을·왜·결과 읽는 법). 야구 용어 첫 등장 시 한 줄 설명(ERA, FIP, OBP, K/9, BB/9, 피타고리안 승률, log loss, Brier, 캘리브레이션, SHAP). 실행 결과 포함 커밋. 네트워크 없이 실행 가능. 문체는 `notebooks/01_데이터_수집과_살펴보기.ipynb`를 따른다.
- 의존성은 `requirements.txt`에 `==` 고정. `shap` 패키지는 추가하지 않는다.
- 모든 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Windows 콘솔은 `python -X utf8`.
- `data/processed/`는 `.gitignore`에 넣는다(재생성 가능). `models/*.pkl`, `models/manifest.json`, `data/public/model_report.json`은 커밋한다.

## 계획 시점의 판정 (스펙과 다른 부분)

- 스펙 5.1 "팀 OPS": 박스스코어에 2루타·3루타가 없어 SLG를 못 만든다 → 팀 타선은 **OBP, HR/PA, K%, BB%**로 대체. 노트북 02에 이유를 적는다.
- 스펙 5.1 "구장, 요일": 홈팀과 거의 1:1이라 홈 승률과 중복이고 LR에 범주형을 넣는 비용이 크다 → **제외**. 노트북 02에 한 줄 기록.
- 스펙 5.1 "선발의 상대팀 상대 성적": 시즌 초 대부분 결측이라 **제외**. 대신 선발 피처는 "당해 시즌 누적 + 직전 시즌 전체" 합산 비율(표본 부족 완화)로 만든다. 사이트 표시는 당해 시즌 숫자만.
- 베이스라인 3종: 홈팀 승 / 시즌 승률 높은 팀 승(동률·미정 → 홈) / **선발 ERA 낮은 팀 승**(둘 다 알 때만, 아니면 홈). 스펙 그대로.
- 선발 피처는 학습에서 "실제 선발(박스스코어 1번 투수)", 라이브에서 "예고 선발"을 쓴다. 예고가 없으면(TBA) 선발 피처 전부 NaN + `starter_known=0`. 이 불일치는 노트북 03과 README에 명시한다.
- 유형 상성 피처(5.2 연계)의 전후 비교는 3단계에서 한다. `model_report.json`의 해당 키는 `null`로 둔다.

## Review Focus

1. 미래 누수: 경기 D의 피처는 D 이후(같은 날 포함) 어떤 경기 점수·박스스코어를 바꿔도 변하지 않아야 한다 → Task 2 테스트 `test_future_games_do_not_change_features`.
2. 박스스코어가 없는 FINAL 경기(수집 창 밖)가 있어도 팀 승률·득실은 games.jsonl에서, 타격·투수 비율은 "박스스코어 있는 경기"로만 집계되어 예외 없이 돌아야 한다 → Task 2 테스트.
3. 예고 선발 섹션이 없거나 한쪽만 있는 페이지, 선수 링크가 없는 경우에 `parse_starters`가 None/부분 결과를 주고 예외를 내지 않아야 한다 → Task 1 테스트.
4. 캘리브레이션 후에도 요인 분해 합이 캘리브레이션 **전** 로짓과 일치하고, `factors` pp 부호가 확률 방향과 맞아야 한다 → Task 4·6 테스트.
5. 같은 피처 parquet으로 `train_win report`를 두 번 돌리면 `model_report.json`이 (생성 시각 제외) 바이트 단위로 같아야 한다 → Task 5 테스트.

---

### Task 1: 예고 선발 파서 + 수집 + 저장

**Files:**
- Modify: `src/kbo_predict/mykbo_parse.py` (`parse_starters` 추가)
- Modify: `src/kbo_predict/raw_store.py` (`starters_path`, `load_starters`, `upsert_starters`)
- Modify: `src/kbo_predict/collect.py` (`fetch_starters`)
- Create: `tests/fixtures/mykbo_game_14050_scheduled.html` (복사 원본: `C:\Users\user\AppData\Local\Temp\claude\C--Users-user-Desktop----workspace-ms-261027-KBO\f5bf1b72-67e7-4a35-af27-36d1ca34ec4d\scratchpad\mykbo_game_14050_scheduled.html`; 2026-10-29 SS@HT 포스트시즌 예정 경기 페이지, 84 KB)
- Test: `tests/test_mykbo_parse.py`, `tests/test_raw_store.py`, `tests/test_collect.py`

**Interfaces:**
- Consumes: `mykbo_client.fetch_html(path, *, session=None, sleep_s=..., cache_dir=None, use_cache=...)`, `raw_store.data_dir()`.
- Produces:
  - `parse_starters(html: str) -> dict | None` — `<section aria-label="Starting pitchers">` 안의 선수 링크 두 개를 읽어 `{"away": {"player_id": int, "name": str} | None, "home": {...} | None}`. 첫 번째 블록이 원정, 두 번째가 홈(페이지 제목 "Samsung Lions … vs … Kia Tigers"와 같은 순서). 섹션이 없으면 `None`. 링크의 `data-id`에서 id, 링크 텍스트에서 이름(사진 링크 말고 텍스트 링크).
  - `raw_store.starters_path(season) -> Path` = `data/raw/{season}/starters.jsonl`; `load_starters(season) -> dict[int, dict]`(game_id → 행); `upsert_starters(season, rows: list[dict]) -> int`(game_id 기준 덮어쓰기, 날짜·game_id 순 정렬, 바뀐 행 수 반환). 행 모양: `{"game_id", "date", "fetched_at", "home": {...}|None, "away": {...}|None}`.
  - `collect.fetch_starters(games: list[dict], *, fetched_at: str, session=None) -> dict` — `status == "SCHEDULED"`인 경기 페이지를 `use_cache=False`로 받아 파싱, `{"starters": {game_id: row}, "errors": [{"path","error"}]}` 반환. 섹션이 없으면 양쪽 None인 행을 만든다(TBA 기록). 예외는 경기 단위로 잡아 계속한다(`_fetch_box`와 같은 예외 튜플).

- [ ] **Step 1: 픽스처 복사 후 실패하는 파서 테스트 작성**

```python
def test_parse_starters_scheduled_page(fixtures):
    html = (fixtures / "mykbo_game_14050_scheduled.html").read_text(encoding="utf-8")
    s = parse_starters(html)
    assert s == {"away": {"player_id": 1096, "name": "Choi Won-tae"},
                 "home": {"player_id": 2730, "name": "Shirakawa Keisho"}}

def test_parse_starters_missing_section_returns_none(fixtures):
    html = (fixtures / "mykbo_game_9809_live.html").read_text(encoding="utf-8")
    assert parse_starters(html) is None

def test_parse_starters_one_side_missing():
    html = SCHEDULED_HTML.replace('<a  data-id="2730"', '<span data-id="2730"')  # 홈 쪽 링크만 제거한 변형
    s = parse_starters(html)
    assert s["away"]["player_id"] == 1096 and s["home"] is None
```
(세 번째 테스트는 픽스처에서 홈 선수 링크 두 개를 지운 문자열을 만들어 쓴다. `fixtures` 픽스처가 없으면 기존 테스트가 픽스처 경로를 여는 방식을 따른다.)

- [ ] **Step 2: 실패 확인** — `python -X utf8 -m pytest tests/test_mykbo_parse.py -k starters -v` → ImportError.
- [ ] **Step 3: `parse_starters` 구현** (BeautifulSoup, `section[aria-label="Starting pitchers"]`, 블록 순서 유지).
- [ ] **Step 4: 통과 확인.**
- [ ] **Step 5: raw_store 테스트 작성** — `tmp_path`에 `KBO_DATA_DIR`를 두고 `upsert_starters(2026, [row1, row2])` → 2, 같은 행 재삽입 → 0, 변경 행 → 1, `load_starters` 가 game_id 키 dict 반환, 파일은 date·game_id 순.
- [ ] **Step 6: raw_store 구현 → 통과.**
- [ ] **Step 7: collect 테스트 작성** — `fetch_html`을 monkeypatch해 `(path → html)` 매핑을 주고, SCHEDULED 2경기(하나는 섹션 있음, 하나는 없음) + FINAL 1경기 입력 → FINAL은 요청하지 않음, 결과 2행(하나는 양쪽 None), `use_cache=False`로 호출됐는지 확인, 한 페이지가 `requests.RequestException`을 내면 errors 1건·나머지는 저장.
- [ ] **Step 8: `fetch_starters` 구현 → 통과.**
- [ ] **Step 9: 전체 테스트 + 커밋** — `python -X utf8 -m pytest -q`; `git add tests/fixtures/mykbo_game_14050_scheduled.html src/kbo_predict/mykbo_parse.py src/kbo_predict/raw_store.py src/kbo_predict/collect.py tests/` ; `git commit -m "feat: 예고 선발투수 파싱·수집·저장 (starters.jsonl)"`.

---

### Task 2: 팀·선발 상태 확장과 피처 함수 (누수 테스트 포함)

**Files:**
- Modify: `src/kbo_predict/features.py` (전면 개정)
- Test: `tests/test_features.py` (기존 테스트는 새 피처명으로 갱신)

**Interfaces:**
- Consumes: `seasons.is_regular(season, date, game_id)`, 박스스코어 dict 모양(`batting[side][i]: ab,r,h,hr,rbi,bb,so,hbp,order,player_id,name,pos`; `pitching[side][i]: ip_outs,np,r,er,h,hr,so,bb,hbp,order,player_id,name`; `home/away: {code,name,score}`; `date`, `game_id`, `status`), Task 1의 starters 행.
- Produces (뒤 태스크·노트북·사이트가 의존):

```python
TEAM_FEATURES = [
    "win_pct_diff", "last10_diff", "run_diff_diff", "pyth_diff", "prev_season_diff",
    "obp_diff", "hr_rate_diff", "k_rate_diff", "bb_rate_diff",
    "era_diff", "fip_diff", "k9_diff", "bb9_diff",
    "rest_diff", "bullpen3_diff",
    "home_venue_pct", "away_venue_pct", "h2h_home_pct", "season_progress",
]
STARTER_FEATURES = [
    "starter_known", "starter_era_diff", "starter_fip_diff", "starter_k9_diff",
    "starter_bb9_diff", "starter_ip_diff", "starter_last3_runs_diff",
]
FEATURE_NAMES = TEAM_FEATURES + STARTER_FEATURES           # 26개, 이 순서 고정
FACTOR_LABELS: dict[str, str]                               # 26개 + "bias": "기본 홈 어드밴티지"

class LeagueState:
    def __init__(self) -> None: ...
    def start_season(self, season: int) -> None
        # 현재 시즌 누적(팀 승률, 투수 누적)을 '직전 시즌'으로 넘기고 현재 시즌을 비운다.
    def update(self, game: dict, box: dict | None = None) -> None
        # FINAL + 양 팀 점수 있을 때만. box가 None이면 승패·득실·휴식일·맞대결만 갱신.
    def team_line(self, code: str, on: str) -> dict
        # on = 'YYYY-MM-DD' (경기 날짜). 키: win_pct, last10, run_diff, pyth, games,
        # obp, hr_rate, k_rate, bb_rate, era, fip, k9, bb9 (분모 0이면 None),
        # home_pct, away_pct (해당 장소 경기 0이면 None), prev_win_pct (직전 시즌 없으면 None),
        # rest_days (직전 경기 없으면 None), bullpen3 (on-3 ~ on-1 날짜의 구원투수 투구수 합, int)
    def h2h_home_pct(self, home: str, away: str) -> float | None   # 당해 시즌 맞대결, 없으면 None
    def pitcher_line(self, player_id: int) -> dict | None
        # 당해 시즌 누적 + 직전 시즌 합산: era, fip, k9, bb9, ip (=ip_outs/3), last3_runs (최근 3선발 평균 실점, 선발 0회면 None)
        # 그리고 "season": 당해 시즌만의 {era, k9, bb9, ip, starts} (사이트 표시용). 기록이 전혀 없으면 None.

def starter_ids(box: dict | None) -> dict   # {"home": player_id|None, "away": player_id|None} — pitching[side]에서 order==1
def game_features(game: dict, state: LeagueState, starters: dict | None = None) -> dict
    # starters = {"home": {"player_id",...}|None, "away": ...|None} (Task 1 행 또는 starter_ids 결과).
    # 반환: FEATURE_NAMES 전부(결측은 float('nan')) + "home_line", "away_line", "home_starter", "away_starter"(pitcher_line 결과 또는 None)
def build_training_frame(games: list[dict], boxscores: dict[int, dict], *, season: int, state: LeagueState | None = None) -> pd.DataFrame
    # 열: game_id, date, season, home_code, away_code, *FEATURE_NAMES, y. state를 주면 그 상태에서 이어서 누적(시즌 연결은 Task 3).
```

피처 정의 (전부 홈 − 원정, 분모 0이면 NaN):
- `pyth` = RF^1.83 / (RF^1.83 + RA^1.83). `prev_season_diff` = 직전 시즌 최종 승률 차(없으면 NaN).
- 타선: OBP = (H+BB+HBP)/(AB+BB+HBP), HR/PA, K% = SO/PA, BB% = BB/PA (PA = AB+BB+HBP). 투수진: ERA = ER·27/IP_outs, FIP(상수 없음) = (13·HR + 3·(BB+HBP) − 2·SO)·3/IP_outs, K/9, BB/9. 박스스코어 있는 경기만 집계.
- `rest_diff` = 홈 휴식일 − 원정 휴식일(둘 중 None이면 NaN). `bullpen3_diff` = 최근 3일 구원 투구수(order>1의 np 합) 차.
- `home_venue_pct` = 홈팀의 홈 승률, `away_venue_pct` = 원정팀의 원정 승률, `season_progress` = 홈팀 games/144.
- 선발: `starter_known` = 양쪽 pitcher_line이 모두 있으면 1 아니면 0(이때 나머지 선발 피처는 NaN). 비율은 pitcher_line의 합산값, `starter_ip_diff` = ip 차, `starter_last3_runs_diff` = 최근 3선발 평균 실점 차.

- [ ] **Step 1: 실패하는 테스트 작성** (기존 `mk()` 헬퍼 확장: `mkbox(game, home_pitchers, away_pitchers, home_bat, away_bat)` 추가)

```python
def test_feature_names_are_26_and_labelled():
    assert len(FEATURE_NAMES) == 26 and set(FACTOR_LABELS) == set(FEATURE_NAMES) | {"bias"}

def test_team_rates_from_boxscore():
    # LG 홈 1경기: 타자 합 AB 30, H 9, BB 3, HBP 1, HR 2, SO 7 / 투수 ip_outs 27, ER 3, HR 1, BB 2, HBP 0, SO 9
    # → obp 13/34, hr_rate 2/34, k_rate 7/34, bb_rate 3/34, era 3.0, fip (13+6-18)*3/27, k9 9.0, bb9 2.0
def test_rates_are_nan_without_boxscore():  # FINAL인데 box None → win_pct는 갱신, obp 등은 None → 피처 NaN
def test_future_games_do_not_change_features():
    # D-1 경기 2개, D 경기 2개(같은 날), D+1 경기. D의 첫 경기 피처를 계산한 뒤 D의 둘째 경기·D+1 점수와 박스스코어를 바꿔도 build_training_frame 행이 동일.
def test_same_day_games_do_not_leak():  # D의 1경기 결과가 D의 2경기 피처에 안 들어감
def test_rest_days_and_bullpen3():
def test_h2h_and_venue_pct():
def test_prev_season_via_start_season():  # 2015 시즌 누적 후 start_season(2016) → prev_win_pct 유지, 당해 시즌 0경기
def test_starter_features_from_boxscore_order1():
    # 투수 두 시즌 누적 합산 확인: 2015 ip_outs 300, ER 40 / 2016 to date ip_outs 30, ER 10 → era = 50*27/330
def test_starter_unknown_sets_flag_zero_and_nan():
def test_training_frame_excludes_draws_and_non_regular():
```

- [ ] **Step 2: 실패 확인** — `python -X utf8 -m pytest tests/test_features.py -v`.
- [ ] **Step 3: `features.py` 구현.** 상태는 팀별 dict(승패·득실·장소별·results deque(10)·타격 합·투수 합·last_game_date·구원 투구수 `deque[(date, np)]`), 맞대결 dict, 투수별 `{season: totals}` + 선발 실점 deque(3). `start_season`은 팀 `prev_win_pct`를 당해 승률로, 투수 `prev`를 당해 합으로 넘긴다.
- [ ] **Step 4: 통과 확인 + 기존 테스트(`test_predict`, `test_pipeline`, `test_train_win`) 깨짐 목록 기록** — 이 태스크에서는 `features.py`와 `test_features.py`만 고치고, 깨진 다른 테스트는 Task 4·6에서 고친다. 보고서에 깨진 테스트 이름을 적는다.
- [ ] **Step 5: 커밋** — `git commit -m "feat: 팀 타격·투수·휴식·맞대결·선발 피처와 누수 테스트 (26개 피처)"`.

---

### Task 3: 시즌 연결 데이터셋 + parquet + manifest

**Files:**
- Modify: `src/kbo_predict/features.py` (`build_dataset`, `save_features`, `load_features`, `features_sha256`, `__main__`)
- Modify: `requirements.txt` (`pyarrow==19.0.1`), `.gitignore` (`data/processed/`)
- Test: `tests/test_features.py`, `tests/test_dataset_real.py` (신규, 커밋된 `data/raw` 사용)

**Interfaces:**
- Consumes: `raw_store.load_games/load_boxscores/available_seasons`, Task 2의 `LeagueState`, `build_training_frame`.
- Produces:
  - `build_dataset(seasons: list[int]) -> pd.DataFrame` — 오름차순 시즌마다 `state.start_season(s)` 후 `build_training_frame(..., state=state)`를 이어 붙인다. 열은 `build_training_frame`과 같고 `season` 열 포함. 행 순서 (date, game_id).
  - `save_features(df, path) -> None` / `load_features(path) -> pd.DataFrame` (parquet, pyarrow) / `features_sha256(path) -> str`.
  - CLI `python -m kbo_predict.features --out data/processed/features.parquet [--seasons 2015 2026]` → 파일 저장 후 행 수·시즌별 행 수·SHA256 출력.

- [ ] **Step 1: 실패 테스트** — 합성 2시즌으로 `build_dataset([2015, 2016])`: 2016 첫 경기의 `prev_season_diff`가 2015 최종 승률 차와 같고 `season` 열이 맞음; `save_features`→`load_features` 왕복 `assert_frame_equal`; `features_sha256`가 같은 df를 두 번 저장해도 같음(결정적 저장: `pq.write_table(..., compression="snappy")`에 pandas 메타데이터 포함 — 같은 입력이면 같은 바이트인지 테스트로 확인하고, 아니면 `store_schema=False` 등으로 고정).
- [ ] **Step 2: 실제 데이터 테스트** (`tests/test_dataset_real.py`, `data/raw/2015..2026` 읽기):

```python
EXPECTED_ROWS = {2015: 715, 2016: 713, 2017: 709, 2018: 714, 2019: 713, 2020: 707,
                 2021: 670, 2022: 707, 2023: 707, 2024: 710, 2025: 698, 2026: 702}
# = 정규 FINAL − 무승부 (1단계 표: 2015 720−5 … 2026 718−16). 숫자가 다르면 1단계 표와 대조해 테스트 쪽을 고친다.
def test_dataset_row_counts_per_season(): ...
def test_no_nan_in_team_core_after_first_week():   # 4월 15일 이후 행은 win_pct_diff, obp_diff, era_diff NaN 없음
def test_starter_known_rate_high():                # 전체 starter_known 평균 ≥ 0.98 (박스스코어 거의 전부 있음)
```
- [ ] **Step 3: 구현 + CLI → 통과.** `python -X utf8 -m kbo_predict.features --out data/processed/features.parquet` 실행 결과(행 수·SHA256)를 보고서에 적는다.
- [ ] **Step 4: 커밋** — `.gitignore`, `requirements.txt`, `features.py`, 테스트. `git commit -m "feat: 시즌 연결 피처 데이터셋(build_dataset) + parquet 저장·SHA256"`.

---

### Task 4: 모델 코어 — LR·LightGBM 공통 인터페이스, 캘리브레이션, 요인 분해

**Files:**
- Modify: `src/kbo_predict/train_win.py` (전면 개정; 기존 `main`은 Task 5에서 교체)
- Modify: `src/kbo_predict/__init__.py` (`MODEL_VERSION = "v0.2"`, `REPORT_VERSION = "report-2026"`)
- Modify: `requirements.txt` (`lightgbm==4.7.0`)
- Test: `tests/test_train_win.py` (기존 테스트 교체)

**Interfaces:**
- Consumes: `features.FEATURE_NAMES`.
- Produces:

```python
SEED = 42
LGBM_PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_child_samples=50,
                   colsample_bytree=0.8, reg_lambda=1.0, deterministic=True, num_threads=1,
                   seed=42, verbose=-1)
LR_C = 1.0

def fit_model(df: pd.DataFrame, *, kind: str, n_estimators: int = 300, calibration: str = "none",
              calib_df: pd.DataFrame | None = None, version: str, seasons: list[int]) -> dict
    # kind ∈ {"lr","lgbm"}. lr = Pipeline(SimpleImputer(median) → StandardScaler → LogisticRegression(C=LR_C, random_state=42, max_iter=2000)).
    # lgbm = lightgbm.LGBMClassifier(**LGBM_PARAMS, n_estimators=n_estimators) (NaN 그대로).
    # calibration ∈ {"none","platt","isotonic"}; "none"이 아니면 calib_df로 fit_calibrator.
    # 번들 키: kind, model, features, calibration, calibrator, version, trained_at, n_games, seasons, n_estimators
def predict_raw(bundle, X: pd.DataFrame) -> np.ndarray       # 캘리브레이션 전 P(홈승)
def predict_proba(bundle, X: pd.DataFrame) -> np.ndarray     # 캘리브레이션 후
def explain(bundle, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]
    # (contrib [n, 26] 로짓 단위, base [n]); lgbm은 booster.predict(pred_contrib=True), lr은 coef·z (결측은 대치값 기준) + intercept.
def fit_calibrator(method: str, p_raw: np.ndarray, y: np.ndarray)  # "platt": LogisticRegression on logit(p); "isotonic": IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
def apply_calibrator(calibrator, p_raw: np.ndarray) -> np.ndarray
def save_bundle(bundle, path) / load_bundle(path)
```

- [ ] **Step 1: 실패 테스트** (합성 데이터: `rng = np.random.default_rng(0)`, 2000행, 로짓 = 2·win_pct_diff + 1·starter_era_diff·(−1) + 잡음, 일부 NaN)

```python
def test_lr_and_lgbm_fit_predict_shape_and_range()
def test_explain_identity_lr():    # Σcontrib + base == logit(predict_raw) atol 1e-6
def test_explain_identity_lgbm()
def test_determinism_same_bits(): # 같은 df로 두 번 fit → predict_proba 결과 np.array_equal
def test_calibration_platt_and_isotonic_change_probs_but_keep_order()
def test_fit_model_rejects_empty_frame():  # ValueError("no training rows")
def test_bundle_roundtrip(tmp_path)
```
- [ ] **Step 2: 실패 확인 → 구현 → 통과.** `pip install lightgbm==4.7.0` 먼저.
- [ ] **Step 3: 커밋** — `git commit -m "feat: LR·LightGBM 공통 모델 인터페이스, 캘리브레이션, 요인 분해(pred_contrib)"`.

---

### Task 5: 평가·보고서·학습 CLI (report-2026, live v0.2)

**Files:**
- Modify: `src/kbo_predict/train_win.py`
- Create: `data/public/model_report.json`, `models/report-2026.pkl`, `models/win_model.pkl`(교체), `models/manifest.json`; 삭제: `models/metrics_v0.1.json`
- Test: `tests/test_train_win.py`

**Interfaces:**
- Consumes: Task 3 parquet, Task 4 함수.
- Produces:

```python
def evaluate(bundle, df) -> dict          # n, accuracy, log_loss, brier
def baselines(df) -> dict                 # {"home_always","better_win_pct","lower_starter_era"} 각 accuracy
def calibration_table(p, y, bins=10) -> list[dict]   # {lo, hi, n, pred_mean, actual_rate}
def mcnemar_p(correct_a: np.ndarray, correct_b: np.ndarray) -> float   # 불일치 쌍 정확 이항검정(양측), scipy 없이 math.comb
def feature_importance(bundle) -> list[dict]  # [{name, label, importance}] 합 1로 정규화 (lgbm gain, lr |coef|)
def oof_predictions(df, *, kind, n_estimators) -> np.ndarray   # 시즌 leave-one-out, 행 순서 유지
def train_report(df, *, train_seasons=range(2015, 2025), val_season=2025, test_season=2026, meta) -> tuple[dict, dict]
    # 1) lr·lgbm을 train으로 학습(lgbm은 val early stopping, stopping_rounds=50 → best_iteration)
    # 2) val에서 캘리브레이션 3종 log loss 비교 → 알고리즘별 최적 방법 선택
    # 3) selected = val log loss가 낮은 알고리즘
    # 4) test(2026) 지표·베이스라인·캘리브레이션 표·McNemar(selected vs best baseline)·중요도
    # 반환 (report dict, selected report 번들 version="report-2026")
def train_live(df, *, kind, calibration, n_estimators, meta) -> dict
    # 2015~2026 전체 학습, 캘리브레이터는 oof_predictions로 적합, version="v0.2"
def write_manifest(path, *, features_path, bundles: dict[str, Path], meta)  # features sha256, 각 pkl sha256, generated_at
CLI: python -m kbo_predict.train_win report|live [--features data/processed/features.parquet]
```
`model_report.json` 키(정렬 저장 `sort_keys=True`): `model_version, generated_at, commit_sha, run_url, features_sha256, train_seasons, val_season, test_season, n: {train,val,test}, models: {lr: {calibration, val: {...}, test: {...}}, lgbm: {calibration, best_iteration, val, test}}, selected, baselines: {val: {...}, test: {...}}, significance: {vs, mcnemar_p, model_correct, baseline_correct}, calibration_bins (test, selected), feature_importance (selected), matchup_feature_ablation: null, cluster_quality: null`.

- [ ] **Step 1: 실패 테스트** — `baselines` 손계산 케이스, `calibration_table` 경계, `mcnemar_p` 알려진 값(불일치 5:1 → p=0.21875), `oof_predictions` 각 행이 자기 시즌을 제외한 모델로 예측됐는지(시즌 2개 합성), `train_report` 합성 3시즌에서 키 존재 + `selected ∈ {lr,lgbm}`; 리뷰 포커스 5: 합성 parquet으로 `train_report` 두 번 → `generated_at` 제외 JSON 동일.
- [ ] **Step 2: 구현 → 통과.**
- [ ] **Step 3: 실제 실행** — `python -X utf8 -m kbo_predict.features --out data/processed/features.parquet` 후 `python -X utf8 -m kbo_predict.train_win report` → `data/public/model_report.json` + `models/report-2026.pkl`; `python -X utf8 -m kbo_predict.train_win live` → `models/win_model.pkl`; `models/manifest.json`. 보고서에 test 지표·베이스라인·selected·캘리브레이션 방법·McNemar p를 적는다. `models/metrics_v0.1.json` 삭제.
- [ ] **Step 4: 커밋** — 코드·테스트·산출물. `git commit -m "feat: 승패 모델 보고서(report-2026)·라이브 모델 v0.2 학습 CLI + 산출물"`.

---

### Task 6: 추론·파이프라인 통합 (선발 포함, 요인 상위 5, 이전 시즌 상태)

**Files:**
- Modify: `src/kbo_predict/predict.py`, `scripts/run_pipeline.py`
- Test: `tests/test_predict.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 1 `fetch_starters/load_starters/upsert_starters`, Task 2 `LeagueState/game_features/starter_ids`, Task 4 `predict_proba/explain`.
- Produces:
  - `predict_game(bundle, game, state, starters=None) -> dict` — 기존 키 유지. `home_win_prob` = 캘리브레이션 후. `factors` = `explain` 결과를 `pp = contrib × p(1−p) × 100`으로 바꿔 |pp| 상위 5개(`{"name": FACTOR_LABELS[...], "contribution_pp"}`), 마지막에 bias 항은 포함 후보로 같이 정렬. `home.starter`/`away.starter` = `{"player_id","name","era","k9","bb9","ip","starts"}`(pitcher_line["season"]) 또는 None. 추가 키 `starter_known: bool`.
  - `build_state(season, upto: str) -> LeagueState` (run_pipeline 내부): 직전 시즌 games+boxscores 전체 → `start_season(season)` → 당해 `date < upto` 정규 FINAL 경기 (date, game_id) 순.
  - run_pipeline: `fetch=True`면 수집 후 `fetch_starters(오늘 SCHEDULED 경기)` → `upsert_starters`, 오류는 `collect_errors`에 합친다. 예측 시 `load_starters(season).get(game_id)`.

- [ ] **Step 1: 실패 테스트** — `test_predict`: 합성 번들(Task 4 `fit_model` lr)로 `predict_game` → `factors` 길이 ≤ 5, pp 부호 합의 방향이 `home_win_prob − 0.5`와 같음(단, 상위 5개만이므로 전체 합으로 검사하려면 `explain` 직접 호출), 선발 블록 모양, starters None → `starter_known False`; `test_pipeline`: 기존 픽스처 흐름에 `fetch_starters` monkeypatch 추가, `latest.json`에 `home.starter` 채워짐, `history.csv` 키 불변, 이전 시즌 데이터가 없을 때도(2015처럼) 동작.
- [ ] **Step 2: 구현 → 전체 테스트 통과** (Task 2에서 깨진 테스트 포함 모두 녹색).
- [ ] **Step 3: 실제 실행** — `python -X utf8 scripts/run_pipeline.py --date 2026-10-29`(네트워크 사용, 예정 경기 페이지 포함) → `data/public/latest.json`에 10-29 경기가 선발·요인과 함께 들어가는지 확인하고 보고서에 요약(홈 승률, 선발 이름, 상위 요인 3개). `--no-fetch`로 다시 돌려 같은 결과인지 확인.
- [ ] **Step 4: 커밋** — `git commit -m "feat: 선발·26피처 모델로 일일 추론 통합, 요인 상위 5 (v0.2)"`.

---

### Task 7: 노트북 02 피처 만들기

**Files:**
- Create: `notebooks/02_피처_만들기.ipynb` (실행 결과 포함)
- Modify: `tests/test_notebooks.py` (02 구조·실행 테스트 추가)

**Interfaces:**
- Consumes: `features.LeagueState/game_features/build_dataset/save_features/features_sha256`, `raw_store`.

- [ ] **Step 1: 구성** (마크다운 → 코드 쌍, 01 문체):
  0. 준비(경로·`sys.path`·한글 폰트 설정은 01과 같은 셀 재사용)
  1. 이 노트북이 하는 일 / 왜 / 짝 `.py`(`features.py`)
  2. "경기 전 정보만"의 뜻 — 누수 예시 그림(한 경기의 타임라인)
  3. 팀 상태 누적 보기: 2025 LG 한 팀의 4월 10경기 동안 `team_line` 변화 표
  4. 피처 26개 사전 (표: 이름·뜻·계산식·왜 넣었나) — OPS 대신 OBP를 쓴 이유, 구장·요일을 뺀 이유
  5. 선발투수: 박스스코어 1번 투수 = 실제 선발, 라이브는 예고 선발 — 한 경기 예시로 `pitcher_line` 보기
  6. `build_dataset(2015..2026)` 실행 → 시즌별 행 수 표(무승부·LIVE 제외 설명), 결측 비율 표
  7. 피처와 승패의 관계: 피처별 홈승률 10분위 그림 3개(승률 차, 선발 ERA 차, 휴식일 차)
  8. parquet 저장 + SHA256 출력 → "이 값이 `models/manifest.json`과 같아야 한다"
- [ ] **Step 2: 실행** — `python -X utf8 -m nbconvert --to notebook --execute --inplace notebooks/02_피처_만들기.ipynb` (타임아웃 600초).
- [ ] **Step 3: 테스트** — `test_notebooks.py`에 02 구조 테스트(코드 셀마다 바로 위 마크다운, `src` 로직 복붙 금지: `def ` 가 있는 코드 셀 0개 허용 예외 없이) + 실행 테스트 추가 → 통과.
- [ ] **Step 4: 커밋** — `git commit -m "docs: 노트북 02 피처 만들기 (실행 결과 포함)"`.

---

### Task 8: 노트북 03 승패 예측 모델

**Files:**
- Create: `notebooks/03_승패_예측_모델.ipynb` (실행 결과 포함)
- Modify: `tests/test_notebooks.py`

**Interfaces:**
- Consumes: `train_win.train_report/train_live/evaluate/baselines/calibration_table/mcnemar_p/feature_importance/explain/load_bundle`, `features.load_features`.

- [ ] **Step 1: 구성**:
  1. 하는 일 / 왜 / 짝 `.py`(`train_win.py`); 모델 두 벌(report·live)이 왜 필요한지
  2. parquet 읽기 + 시즌 분할 그림(2015~2024 / 2025 / 2026)
  3. 베이스라인 3종 — 표
  4. 로지스틱 회귀: 계수 표(표준화 계수) + 해석 한 줄씩
  5. LightGBM: early stopping 곡선(iteration vs val log loss)
  6. 캘리브레이션: 3종 비교 표 + 신뢰도 곡선(reliability diagram) 그림
  7. 최종 2026 성적표: `train_report()` 호출 → 표 (정확도·log loss·Brier, 베이스라인, McNemar p) — "통계적으로 유의" 해석
  8. 피처 중요도 그림 + 한 경기 요인 분해(SHAP) 예시 막대 그림
  9. 라이브 모델: `train_live()` → 번들 요약
  10. 동일성 확인: 노트북에서 만든 report dict(`generated_at` 제외)를 `data/public/model_report.json`과 비교해 **같다**고 출력 (4단계 parity의 예고)
- [ ] **Step 2: 실행 + 테스트 추가(02와 같은 규칙) → 통과.** 실행 시간은 보고서에 적는다.
- [ ] **Step 3: 커밋** — `git commit -m "docs: 노트북 03 승패 예측 모델 (실행 결과 포함)"`.

---

### Task 9: 문서 갱신

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-27-kbo-predict-design.md`, `docs/superpowers/plans/2026-10-27-stage0-deferred.md`

- [ ] **Step 1: README** — "모델" 절: 피처 26개 요약(팀 19 + 선발 7), 두 알고리즘, 분할, 캘리브레이션, `model_report.json` 핵심 숫자 표(정확도·log loss·Brier vs 베이스라인 3종, McNemar p), 요인 분해 설명, "학습은 실제 선발, 라이브는 예고 선발" 주의. 노트북 목차 02·03 완료. 테스트 수 갱신(`python -X utf8 -m pytest -q` 결과). 아키텍처 그림에 `starters.jsonl`, `report-2026.pkl`. 로드맵 2단계 취소선.
- [ ] **Step 2: 스펙** — §12 항목 2를 "완료 (2026-10-29)"로 바꾸고 결과 한 단락; §5.1 선발 항목에 "MyKBOStats 예정 경기 페이지의 Starting pitchers 섹션을 소스로 확보(2026-10-29)" 추가; §13 아래 "구현하며 확정한 규칙(2단계)"에 이 계획의 판정 목록(OBP 대체, 구장·요일 제외, 상대 성적 제외, 실제/예고 선발 불일치, 캘리브레이션 선택 절차, 라이브 캘리브레이터는 시즌 LOO OOF).
- [ ] **Step 3: 이월 문서** — "2단계 전에" 항목 처리 표시(요인 항등식 ✅, train_win CLI·빈 프레임 ✅, CANCELED 모양·재편성·2027은 유지), "3단계 전에"에 추가: 선수 한글 이름 소스(MyKBOStats는 로마자), 유형 상성 피처 전후 비교(`matchup_feature_ablation`), 정규시즌 예정 경기 페이지에도 Starting pitchers 섹션이 있는지 2027 개막 전 확인(픽스처는 포스트시즌 페이지), 예고 선발 변경 이력 활용.
- [ ] **Step 4: 커밋** — `git commit -m "docs: 2단계 완료 — README 모델 절, 스펙·이월 항목 갱신"`.

---

### 컨트롤러 단계 (태스크 아님)

- Task 6 완료 후, 최종 전체 리뷰 전에 **Codex 교차 검토**: `codex exec --sandbox read-only`로 `features.py`, `train_win.py`, `predict.py`를 누수·재현성·통계적 오류 관점에서 검토하게 하고, 결과를 리뷰 발견과 같은 기준으로 분류해 수정 라운드에 포함한다(사용자 결정: Codex는 모델 코드 교차 검토용).
- 푸시는 Task 6 완료 후(모델·파이프라인이 일관된 상태) 한 번, 전체 완료 후 한 번. 그 사이 일일 Actions가 돌아도 v0.1 번들과 코드가 함께 있어 깨지지 않는다.
