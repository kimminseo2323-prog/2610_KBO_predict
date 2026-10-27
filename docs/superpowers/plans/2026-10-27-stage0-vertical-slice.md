# 0단계 수직 슬라이스 v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 네이버 스포츠 API에서 2026 KBO 경기를 수집하고, 최소 피처 로지스틱 회귀로 오늘 경기의 홈팀 승률을 예측해, GitHub Actions가 매일 `data/public/latest.json` · `history.csv` · `status.json`을 커밋하는 파이프라인을 공개 저장소에 올린다.

**Architecture:** `src/kbo_predict/` 패키지에 수집(collect) → 피처(features) → 학습(train_win) → 추론·발행(predict, publish) 모듈을 두고, `scripts/run_pipeline.py`가 날짜 하나를 받아 순서대로 호출한다. 원본 응답은 `data/raw/{season}/`에 그대로 보관하고, 피처는 날짜순으로 상태를 누적하는 `LeagueState`로 계산해 "경기 이전 데이터만 사용"을 구조적으로 보장한다. 모델은 로컬에서 한 번 학습해 커밋하고, Actions는 추론만 한다.

**Tech Stack:** Python 3.12, requests, pandas 2.2, scikit-learn 1.6 (LogisticRegression + StandardScaler), joblib, pytest 9, GitHub Actions (ubuntu-latest).

**Spec:** `docs/superpowers/specs/2026-10-27-kbo-predict-design.md` (특히 4절 데이터, 5.1 승패 모델, 7절 자동화, 8절 데이터 계약, 12절 0단계)

## Global Constraints

- 데이터 소스는 네이버 스포츠 내부 API `https://api-gw.sports.naver.com` 만 사용. koreabaseball.com 요청 금지 (스펙 2절 반목표).
- 요청 간 `sleep` 1초 이상, `User-Agent: Mozilla/5.0 (compatible; kbo-predict/0.1; +https://github.com/kimminseo2323-prog/2610_KBO_predict)`, 실패 시 1회 재시도 후 예외 (스펙 4.4).
- 피처는 해당 경기 날짜 **이전**(`gameDate < 대상 날짜`)의 `statusCode == "RESULT"` 경기만으로 계산 (스펙 2절 반목표 "누수").
- 무승부(`winner == "DRAW"`)는 학습에서 제외 (스펙 5.1).
- 난수 seed 42 (스펙 5.3). 모델 버전 문자열 `"v0.1"`.
- 시각은 모두 `Asia/Seoul`; JSON의 `generated_at`은 ISO 8601 with offset (예 `2026-10-28T09:02:11+09:00`).
- 모든 공개 JSON에 `generated_at`, `commit_sha`, `run_url`, `model_version`, `mode` 포함 (스펙 7절).
- 저장소: `https://github.com/kimminseo2323-prog/2610_KBO_predict`, 브랜치 `main`. 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- 노트북은 0단계 범위 밖 (스펙 12절 0단계).

## Review Focus

1. **선발투수 미발표** (`homeStarterName == ""` 또는 `None`): 예측은 리그 평균 ERA로 계산되고 `latest.json`의 `starter`는 `null`, `factors`의 "선발 ERA 차이"는 0.0이어야 한다 — Task 3·5 테스트.
2. **우천 취소/서스펜디드** (`cancel == true` 또는 `suspended == true`): 피처 상태에 반영되지 않고, `history.csv`에 `status: "CANCELED"`로 남되 `correct`는 빈칸 — Task 3·5 테스트.
3. **같은 날 두 번 실행** (09:00 예측 후 17:00 선발 변경 재실행): `history.csv`에 같은 `game_id` 행이 두 개 생기지 않고 확률만 갱신, 단 이미 `RESULT`인 행은 덮어쓰지 않는다 — Task 5 테스트.
4. **경기 없는 날**: `latest.json`은 건드리지 않고 `status.json`만 갱신, `next_game_date`에 다음 경기 날짜 — Task 6 테스트.
5. **시즌 첫 경기처럼 누적 데이터가 0일 때**: 승률 0.5, 최근 10경기 0.5, ERA 리그 평균(없으면 4.50) 기본값으로 예측이 나와야 하고 ZeroDivision이 없어야 한다 — Task 3 테스트.

---

## 파일 구조

```
pyproject.toml                      # 패키지 메타 + pytest 설정
requirements.txt                    # 런타임 + 테스트 의존성 (Actions도 이 파일 사용)
src/kbo_predict/__init__.py
src/kbo_predict/naver_client.py     # HTTP 호출만 (UA, sleep, 재시도)
src/kbo_predict/raw_store.py        # data/raw 읽기/쓰기 (jsonl, jsonl.gz)
src/kbo_predict/collect.py          # 기간 수집 + 증분 수집 CLI
src/kbo_predict/features.py         # LeagueState, 이닝 파싱, 경기별 피처
src/kbo_predict/train_win.py        # 학습 + 지표 + 모델 저장 CLI
src/kbo_predict/predict.py          # 모델 로드, 확률·요인 계산
src/kbo_predict/publish.py          # latest.json / history.csv / status.json 쓰기
scripts/run_pipeline.py             # 날짜 하나에 대한 전체 실행
.github/workflows/daily.yml
data/raw/2026/games.jsonl           # 일정 행 (gameId당 1줄, 최신 상태)
data/raw/2026/records.jsonl.gz      # RESULT 경기의 recordData
data/public/{latest.json,history.csv,status.json}
models/win_model.pkl, models/metrics_v0.1.json
tests/fixtures/*.json               # 실제 API 응답 (이미 저장됨)
tests/test_*.py
README.md
```

---

### Task 1: 프로젝트 뼈대

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `src/kbo_predict/__init__.py`, `tests/test_smoke.py`, `README.md`
- Modify: `.gitignore` (`data/raw/**/*.tmp`, `*.pkl` 제외 안 함 — 모델은 커밋 대상)

**Interfaces:**
- Produces: import 가능한 패키지 `kbo_predict` (`__version__ = "0.1.0"`, `MODEL_VERSION = "v0.1"`, `KST = ZoneInfo("Asia/Seoul")`), `pytest` 실행 환경.

- [ ] **Step 1: `requirements.txt` 작성** — `requests>=2.32`, `pandas>=2.2`, `scikit-learn>=1.6`, `joblib>=1.4`, `pytest>=8`
- [ ] **Step 2: `pyproject.toml` 작성** — `[project] name="kbo-predict" version="0.1.0" requires-python=">=3.12"`, `[tool.setuptools.packages.find] where=["src"]`, `[tool.pytest.ini_options] testpaths=["tests"] pythonpath=["src"]`
- [ ] **Step 3: `src/kbo_predict/__init__.py`** — 위 세 상수 정의
- [ ] **Step 4: `tests/test_smoke.py` 작성**

```python
from kbo_predict import MODEL_VERSION, KST
def test_package_imports():
    assert MODEL_VERSION == "v0.1"
    assert KST.key == "Asia/Seoul"
```

- [ ] **Step 5: 설치 후 테스트** — Run: `pip install -r requirements.txt && pip install -e . && pytest -q` — Expected: `1 passed`
- [ ] **Step 6: `README.md` 초안** — 제목 `# KBO Predict`, 한 문단 설명, "v0.1 — 개선 중" 배지 텍스트, 설계 문서·데이터 조사 링크, "데이터 출처: 네이버 스포츠 (비공식 API), 개인 학습용" 고지
- [ ] **Step 7: Commit** — `git add -A && git commit -m "chore: 프로젝트 뼈대 (패키지, 테스트, README)"`

---

### Task 2: 네이버 클라이언트 + 원본 저장 + 수집 CLI

**Files:**
- Create: `src/kbo_predict/naver_client.py`, `src/kbo_predict/raw_store.py`, `src/kbo_predict/collect.py`
- Test: `tests/test_naver_client.py`, `tests/test_raw_store.py`, `tests/test_collect.py`
- Fixtures (이미 있음): `tests/fixtures/schedule_2026-08-15.json`, `tests/fixtures/schedule_2026-10-20_28.json`, `tests/fixtures/record_33331020HTLG02026.json`

**Interfaces:**
- Produces:
  - `naver_client.fetch_games(from_date: date, to_date: date, *, session=None, sleep_s: float = 1.0) -> list[dict]` — `result.games` 중 `categoryId == "kbo"`만 반환. URL: `/schedule/games?fields=basic,schedule,baseball&upperCategoryId=kbaseball&categoryId=kbo&fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD&size=500`
  - `naver_client.fetch_record(game_id: str, *, session=None, sleep_s: float = 1.0) -> dict` — `result.recordData` 반환
  - `raw_store.games_path(season: int) -> Path`, `records_path(season: int) -> Path` (`data/raw/{season}/games.jsonl`, `records.jsonl.gz`, 루트는 환경변수 `KBO_DATA_DIR` 또는 기본 `data`)
  - `raw_store.upsert_games(season: int, games: list[dict]) -> int` — gameId 기준 덮어쓰기, 저장 후 gameDate·gameId 정렬, 반환은 신규+갱신 수
  - `raw_store.load_games(season: int) -> list[dict]`
  - `raw_store.append_records(season: int, records: dict[str, dict]) -> int` — `{"gameId": ..., "recordData": ...}` 한 줄씩 gz append, 이미 있는 gameId는 건너뜀
  - `raw_store.load_records(season: int) -> dict[str, dict]` — gameId → recordData
  - `collect.collect_range(from_date: date, to_date: date, *, season: int | None = None) -> dict` — 일정 upsert + `statusCode == "RESULT"`이고 record가 없는 경기의 record 수집. 반환 `{"games": n, "records": n}`
  - CLI: `python -m kbo_predict.collect --from 2026-03-01 --to 2026-10-31`

- [ ] **Step 1: `tests/test_naver_client.py` 작성** — `requests.Session.get`을 monkeypatch해 fixture를 돌려주는 가짜 응답(`status_code`, `.json()`, `raise_for_status()`)을 쓴다.

```python
def test_fetch_games_filters_kbo_and_builds_url(monkeypatch, fixture_json):  # fixture_json: conftest helper
    captured = {}
    def fake_get(self, url, **kw):
        captured["url"] = url
        return FakeResp(fixture_json("schedule_2026-08-15.json"))
    monkeypatch.setattr(requests.Session, "get", fake_get)
    games = fetch_games(date(2026, 8, 15), date(2026, 8, 15), sleep_s=0)
    assert len(games) == 5 and all(g["categoryId"] == "kbo" for g in games)
    assert "fromDate=2026-08-15" in captured["url"] and "categoryId=kbo" in captured["url"]

def test_fetch_record_returns_record_data(monkeypatch, fixture_json):
    ...  # fake_get → record fixture; assert "battersBoxscore" in result and result["gameInfo"]["hCode"] == "LG"

def test_retries_once_then_raises(monkeypatch):
    ...  # fake_get가 항상 503 → raise_for_status에서 HTTPError; 호출 횟수 == 2 확인 후 HTTPError 전파
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_naver_client.py -q` — Expected: ImportError
- [ ] **Step 3: `naver_client.py` 구현** — `BASE_URL`, `USER_AGENT` 상수(Global Constraints 값), 모듈 함수 `_get(session, url, sleep_s)`가 `time.sleep(sleep_s)` 후 요청, 실패 시 1회 재시도.
- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_naver_client.py -q` — Expected: `3 passed`
- [ ] **Step 5: `tests/test_raw_store.py` 작성** — `tmp_path`를 `KBO_DATA_DIR`로 monkeypatch.

```python
def test_upsert_games_dedupes_by_game_id_and_sorts(tmp_data_dir, fixture_json):
    games = fixture_json("schedule_2026-10-20_28.json")["result"]["games"]
    assert upsert_games(2026, games) == 4
    changed = dict(games[1], statusCode="RESULT")       # 10-25 경기 상태 변경
    assert upsert_games(2026, [changed]) == 1
    loaded = load_games(2026)
    assert len(loaded) == 4 and [g["gameDate"] for g in loaded] == sorted(g["gameDate"] for g in loaded)
    assert next(g for g in loaded if g["gameId"] == changed["gameId"])["statusCode"] == "RESULT"

def test_append_records_skips_existing(tmp_data_dir, fixture_json):
    rec = fixture_json("record_33331020HTLG02026.json")["result"]["recordData"]
    assert append_records(2026, {"33331020HTLG02026": rec}) == 1
    assert append_records(2026, {"33331020HTLG02026": rec}) == 0
    assert load_records(2026)["33331020HTLG02026"]["gameInfo"]["hCode"] == "LG"
```

- [ ] **Step 6: 실패 확인** — Run: `pytest tests/test_raw_store.py -q` — Expected: ImportError
- [ ] **Step 7: `raw_store.py` 구현** — jsonl은 `ensure_ascii=False`, gz는 `gzip.open(..., "at", encoding="utf-8")`.
- [ ] **Step 8: 통과 확인** — Run: `pytest tests/test_raw_store.py -q` — Expected: `2 passed`
- [ ] **Step 9: `tests/test_collect.py` 작성**

```python
def test_collect_range_fetches_records_only_for_new_results(monkeypatch, tmp_data_dir, fixture_json):
    sched = fixture_json("schedule_2026-10-20_28.json")["result"]["games"]   # RESULT 2개, BEFORE 1, STARTED 1
    monkeypatch.setattr(collect, "fetch_games", lambda *a, **k: sched)
    called = []
    monkeypatch.setattr(collect, "fetch_record", lambda gid, **k: called.append(gid) or {"gameInfo": {}})
    out = collect.collect_range(date(2026, 10, 20), date(2026, 10, 28))
    assert out == {"games": 4, "records": 2} and sorted(called) == ["33331020HTLG02026", "55551026HTSS02026"]
    called.clear()
    assert collect.collect_range(date(2026, 10, 20), date(2026, 10, 28))["records"] == 0 and called == []
```

- [ ] **Step 10: 실패 확인** — Run: `pytest tests/test_collect.py -q` — Expected: AttributeError/ImportError
- [ ] **Step 11: `collect.py` 구현** — season 기본값은 `from_date.year`; `argparse`로 `--from`, `--to` (ISO 날짜), `--sleep` (기본 1.0).
- [ ] **Step 12: 통과 확인** — Run: `pytest -q` — Expected: 모두 PASS
- [ ] **Step 13: 2026 시즌 백필 (실제 API, 로컬 1회)** — Run: `python -m kbo_predict.collect --from 2026-03-01 --to 2026-10-31` — Expected: 출력에 `games` ≥ 720, `records` ≥ 720; 소요 약 15분. 완료 후 `python -c "from kbo_predict.raw_store import *; g=load_games(2026); print(len(g), sum(x['roundCode']=='kbo_r' and x['statusCode']=='RESULT' for x in g))"` — Expected: 정규시즌 RESULT 720 (무승부 포함)
- [ ] **Step 14: Commit** — `git add src tests data/raw && git commit -m "feat: 네이버 스포츠 수집기 + 2026 시즌 원본 데이터"` (records.jsonl.gz 크기가 50MB를 넘으면 중단하고 보고)

---

### Task 3: 피처 (LeagueState)

**Files:**
- Create: `src/kbo_predict/features.py`
- Test: `tests/test_features.py`

**Interfaces:**
- Consumes: `raw_store.load_games`, `load_records` 형식 (Task 2)
- Produces:
  - `features.parse_innings(inn: str) -> int` — 아웃 수. `"5"→15`, `"1 ⅓"→4`, `"0 ⅔"→2`, `""→0` (⅓=U+2153, ⅔=U+2154)
  - `features.FEATURE_NAMES = ["win_pct_diff", "last10_diff", "starter_era_diff"]` (홈 − 원정)
  - `features.FACTOR_LABELS = {"win_pct_diff": "팀 승률 차이", "last10_diff": "최근 10경기 흐름", "starter_era_diff": "선발 ERA 차이", "intercept": "홈 어드밴티지"}`
  - `class features.LeagueState` — `update(game: dict, record: dict | None) -> None` (RESULT이고 cancel/suspended 아닐 때만 반영; record가 있으면 투수 누적도 반영), `team_win_pct(code) -> float` (경기 0이면 0.5), `team_last10(code) -> float`, `starter_era(team_code, name) -> float | None` (아웃 0이면 None), `league_era() -> float` (누적 없으면 4.5), `starter_line(team_code, name) -> dict | None` — `{"name", "era", "k9", "bb9", "ip"}` (ip는 `"62.1"` 형식 문자열)
  - `features.game_features(game: dict, state: LeagueState) -> dict` — `FEATURE_NAMES` 키 + `home_starter`, `away_starter`(starter_line 또는 None) + `home_win_pct`, `away_win_pct`, `home_last10`, `away_last10`
  - `features.build_training_frame(games: list[dict], records: dict[str, dict], *, round_code: str = "kbo_r") -> pandas.DataFrame` — 날짜순으로 상태를 누적하며 각 RESULT·비무승부 경기의 피처와 `y`(홈 승=1), `game_id`, `game_date` 열 생성
  - 투수 누적 키는 `(team_code, name)`. 투수 박스스코어 `inn` 합산 아웃, `er`, `kk`, `bb` 합산. ERA = er×27/outs, k9 = kk×27/outs, bb9 = bb×27/outs.

- [ ] **Step 1: `tests/test_features.py` 작성**

```python
@pytest.mark.parametrize("inn,outs", [("5", 15), ("1 ⅓", 4), ("0 ⅔", 2), ("", 0), ("6 ⅔", 20)])
def test_parse_innings(inn, outs): assert parse_innings(inn) == outs

def test_state_defaults_when_empty():
    s = LeagueState()
    assert s.team_win_pct("LG") == 0.5 and s.team_last10("LG") == 0.5
    assert s.starter_era("LG", "아무개") is None and s.league_era() == 4.5

def test_state_updates_from_fixture(fixture_json):
    game = next(g for g in fixture_json("schedule_2026-10-20_28.json")["result"]["games"] if g["gameId"] == "33331020HTLG02026")
    rec = fixture_json("record_33331020HTLG02026.json")["result"]["recordData"]
    s = LeagueState(); s.update(game, rec)
    assert s.team_win_pct("HT") == 1.0 and s.team_win_pct("LG") == 0.0
    away_starter = rec["pitchersBoxscore"]["away"][0]["name"]      # 5이닝 1자책
    assert s.starter_era("HT", away_starter) == pytest.approx(1.8)
    assert s.starter_line("HT", away_starter)["ip"] == "5.0"

def test_canceled_game_not_counted(fixture_json):
    game = dict(fixture_json("schedule_2026-08-15.json")["result"]["games"][0], cancel=True)
    s = LeagueState(); s.update(game, None)
    assert s.team_win_pct(game["homeTeamCode"]) == 0.5

def test_game_features_unknown_starter_uses_league_avg(fixture_json):
    game = dict(fixture_json("schedule_2026-08-15.json")["result"]["games"][0], homeStarterName="", awayStarterName="")
    f = game_features(game, LeagueState())
    assert f["starter_era_diff"] == 0.0 and f["home_starter"] is None and f["away_starter"] is None

def test_build_training_frame_has_no_leakage(fixture_json):
    # 같은 두 팀의 경기 3개를 날짜 d1<d2<d3로 만든다. d3 경기의 피처는 d1,d2 결과로만 결정된다.
    base = fixture_json("schedule_2026-08-15.json")["result"]["games"][0]
    def mk(d, gid, winner): return dict(base, gameDate=d, gameId=gid, winner=winner, statusCode="RESULT", cancel=False, suspended=False)
    games = [mk("2026-04-01", "g1", "HOME"), mk("2026-04-02", "g2", "HOME"), mk("2026-04-03", "g3", "AWAY")]
    df_a = build_training_frame(games, {})
    games_b = games[:2] + [mk("2026-04-03", "g3", "HOME")]        # d3 결과만 바꿈
    df_b = build_training_frame(games_b, {})
    assert df_a.loc[df_a.game_id == "g3", FEATURE_NAMES].values.tolist() == df_b.loc[df_b.game_id == "g3", FEATURE_NAMES].values.tolist()
    assert df_a.loc[df_a.game_id == "g1", "win_pct_diff"].item() == 0.0      # 첫 경기는 기본값
    assert df_a.loc[df_a.game_id == "g3", "win_pct_diff"].item() == pytest.approx(1.0)

def test_build_training_frame_excludes_draws_and_postseason(fixture_json):
    ...  # winner="DRAW" 행과 roundCode="kbo_ps_po" 행이 결과 DataFrame에 없음을 확인
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_features.py -q` — Expected: ImportError
- [ ] **Step 3: `features.py` 구현** — `LeagueState`는 팀별 `wins/losses/results(deque maxlen 10)`, 투수별 `outs/er/kk/bb` 딕셔너리. `build_training_frame`은 `sorted(games, key=(gameDate, gameId))`로 순회하며 같은 날짜의 경기는 **모두 피처를 먼저 계산한 뒤** 상태를 갱신한다 (더블헤더 누수 방지).
- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_features.py -q` — Expected: 모두 PASS
- [ ] **Step 5: Commit** — `git add src/kbo_predict/features.py tests/test_features.py && git commit -m "feat: 누수 없는 경기 피처 (LeagueState)"`

---

### Task 4: 학습 + 지표 + 모델 저장

**Files:**
- Create: `src/kbo_predict/train_win.py`
- Test: `tests/test_train_win.py`
- Output: `models/win_model.pkl`, `models/metrics_v0.1.json`

**Interfaces:**
- Consumes: `features.build_training_frame`, `FEATURE_NAMES`
- Produces:
  - `train_win.fit_model(df: DataFrame) -> dict` — `{"model": LogisticRegression(random_state=42), "scaler": StandardScaler, "features": FEATURE_NAMES, "version": "v0.1", "trained_at": iso, "n_games": int}`
  - `train_win.evaluate(bundle: dict, df_test: DataFrame) -> dict` — `{"n": int, "accuracy", "log_loss", "brier", "baseline_home_always", "baseline_better_win_pct"}` (베이스라인 둘은 정확도)
  - `train_win.save_bundle(bundle, path: Path)`, `train_win.load_bundle(path) -> dict` (joblib)
  - CLI: `python -m kbo_predict.train_win --season 2026 --split-date 2026-08-01` → 분할 평가 지표를 `models/metrics_v0.1.json`에 쓰고, 전체 데이터로 재학습한 번들을 `models/win_model.pkl`에 저장. 지표 JSON에는 `split_date`, `train_n`, `test_n`, 위 evaluate 결과, `coefficients` (피처명→계수, `intercept`)를 넣는다.

- [ ] **Step 1: `tests/test_train_win.py` 작성** — 합성 데이터: seed 42로 `win_pct_diff ~ N(0, .1)`, `y = (win_pct_diff + noise > 0)` 400행.

```python
def test_fit_and_evaluate_beats_home_always(synthetic_df):
    bundle = fit_model(synthetic_df.iloc[:300])
    m = evaluate(bundle, synthetic_df.iloc[300:])
    assert bundle["version"] == "v0.1" and set(m) >= {"accuracy", "log_loss", "brier", "baseline_home_always"}
    assert m["accuracy"] > m["baseline_home_always"]

def test_save_and_load_roundtrip(tmp_path, synthetic_df):
    bundle = fit_model(synthetic_df); p = tmp_path / "m.pkl"; save_bundle(bundle, p)
    loaded = load_bundle(p)
    x = synthetic_df[FEATURE_NAMES].iloc[:5]
    assert loaded["model"].predict_proba(loaded["scaler"].transform(x)).tolist() == bundle["model"].predict_proba(bundle["scaler"].transform(x)).tolist()
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_train_win.py -q` — Expected: ImportError
- [ ] **Step 3: `train_win.py` 구현**
- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_train_win.py -q` — Expected: `2 passed`
- [ ] **Step 5: 실제 학습** — Run: `python -m kbo_predict.train_win --season 2026 --split-date 2026-08-01` — Expected: `models/metrics_v0.1.json` 생성, 테스트 구간 `accuracy`가 `baseline_home_always`보다 높음. 낮으면 중단하고 지표를 보고 (피처 버그 가능성).
- [ ] **Step 6: Commit** — `git add src/kbo_predict/train_win.py tests/test_train_win.py models && git commit -m "feat: 로지스틱 회귀 승패 모델 v0.1 + 지표"`

---

### Task 5: 추론 + 발행 (latest.json / history.csv / status.json)

**Files:**
- Create: `src/kbo_predict/predict.py`, `src/kbo_predict/publish.py`
- Test: `tests/test_predict.py`, `tests/test_publish.py`

**Interfaces:**
- Consumes: `train_win.load_bundle`, `features.game_features`, `LeagueState`, `FACTOR_LABELS`
- Produces:
  - `predict.predict_game(bundle, game: dict, state: LeagueState) -> dict` — `{"game_id", "date", "time" ("18:30"), "stadium", "round" (roundCode), "series_game_no", "status", "home": {"code","name","starter","win_pct_season","last10"}, "away": {...}, "home_win_prob": float(소수 4자리), "factors": [{"name", "contribution_pp"}, ...]}`. 요인: 표준화 피처 z에 대해 `coef_i * z_i * p*(1-p) * 100`, 절편은 `intercept * p*(1-p) * 100` ("홈 어드밴티지"); 절대값 내림차순.
  - `publish.write_latest(path, *, date, games: list[dict], meta: dict) -> None` — `{"generated_at", "date", "mode": "live", "model_version", "commit_sha", "run_url", "games": [...]}`
  - `publish.upsert_history(path, predictions: list[dict], *, predicted_at: str) -> None` — CSV 열 `date,game_id,home,away,home_win_prob,model_version,predicted_at,status,winner,correct`. 같은 `game_id` 행이 있으면: 기존 `status == "RESULT"`면 건드리지 않음, 아니면 확률·predicted_at·status 갱신.
  - `publish.settle_history(path, games: list[dict]) -> int` — `winner`가 빈 행에 대해 games에서 `statusCode == "RESULT"`면 `winner`(HOME/AWAY/DRAW)·`status`·`correct`(HOME이면 prob≥.5, AWAY면 prob<.5, DRAW면 빈칸) 채움; `cancel`이면 `status="CANCELED"`. 반환은 갱신 행 수.
  - `publish.write_status(path, *, mode, next_game_date: str | None, games_today: int, meta: dict) -> None`

- [ ] **Step 1: `tests/test_predict.py` 작성** — Task 4의 합성 번들 fixture 재사용.

```python
def test_predict_game_shape_and_factor_sum(bundle, fixture_json):
    game = fixture_json("schedule_2026-08-15.json")["result"]["games"][0]
    out = predict_game(bundle, game, LeagueState())
    assert 0 < out["home_win_prob"] < 1 and out["time"] == "18:30" and out["home"]["code"] == game["homeTeamCode"]
    assert [f["name"] for f in out["factors"]][0] in FACTOR_LABELS.values()
    assert out["home"]["starter"] is None or {"name", "era", "k9", "bb9", "ip"} <= set(out["home"]["starter"])

def test_predict_game_no_starter_has_zero_era_factor(bundle, fixture_json):
    game = dict(fixture_json("schedule_2026-08-15.json")["result"]["games"][0], homeStarterName="", awayStarterName="")
    out = predict_game(bundle, game, LeagueState())
    assert next(f for f in out["factors"] if f["name"] == "선발 ERA 차이")["contribution_pp"] == 0.0
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_predict.py -q` — Expected: ImportError
- [ ] **Step 3: `predict.py` 구현**
- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_predict.py -q` — Expected: `2 passed`
- [ ] **Step 5: `tests/test_publish.py` 작성**

```python
def test_upsert_then_rerun_updates_prob_without_duplicate(tmp_path):
    p = tmp_path / "history.csv"
    upsert_history(p, [pred("g1", 0.55)], predicted_at="2026-10-28T09:00:00+09:00")
    upsert_history(p, [pred("g1", 0.60)], predicted_at="2026-10-28T17:00:00+09:00")
    df = pd.read_csv(p); assert len(df) == 1 and df.home_win_prob.item() == 0.60

def test_settle_marks_correct_and_protects_result_rows(tmp_path):
    p = tmp_path / "history.csv"
    upsert_history(p, [pred("g1", 0.55), pred("g2", 0.40)], predicted_at="t")
    n = settle_history(p, [game("g1", "RESULT", "HOME"), game("g2", "RESULT", "AWAY")])
    df = pd.read_csv(p); assert n == 2 and df.correct.tolist() == [1, 1]
    upsert_history(p, [pred("g1", 0.99)], predicted_at="t2")
    assert pd.read_csv(p).home_win_prob.tolist()[0] == 0.55

def test_settle_canceled_and_draw(tmp_path):
    ...  # cancel=True → status CANCELED, correct 빈칸; winner DRAW → correct 빈칸

def test_write_latest_and_status_contain_meta(tmp_path):
    ...  # generated_at, commit_sha, run_url, model_version, mode 키 존재; status.json에 next_game_date
```

- [ ] **Step 6: 실패 확인** — Run: `pytest tests/test_publish.py -q` — Expected: ImportError
- [ ] **Step 7: `publish.py` 구현** — CSV는 `index=False`, `correct`는 Int64(nullable).
- [ ] **Step 8: 통과 확인** — Run: `pytest -q` — Expected: 모두 PASS
- [ ] **Step 9: Commit** — `git add src/kbo_predict/predict.py src/kbo_predict/publish.py tests/test_predict.py tests/test_publish.py && git commit -m "feat: 추론 + latest.json/history.csv/status.json 발행"`

---

### Task 6: 파이프라인 스크립트 + GitHub Actions

**Files:**
- Create: `scripts/run_pipeline.py`, `.github/workflows/daily.yml`
- Test: `tests/test_pipeline.py`
- Output: `data/public/latest.json`, `history.csv`, `status.json`

**Interfaces:**
- Consumes: Task 2~5 전부
- Produces:
  - `run_pipeline.run(target: date, *, data_dir: Path, model_path: Path, meta: dict, fetch=True) -> dict` — 순서: ① `collect_range(target-3일, target+14일)` (fetch=False면 생략) ② `settle_history` ③ 모든 시즌 games/records로 `LeagueState`를 `gameDate < target`까지 누적 ④ target 날짜 경기(취소 아님) 예측 ⑤ 경기 있으면 `write_latest` + `upsert_history`, 없으면 latest 생략 ⑥ `write_status` (next_game_date = target 이후 첫 경기 날짜 또는 None). 반환 `{"games_today": n, "settled": n}`
  - CLI: `python scripts/run_pipeline.py [--date YYYY-MM-DD] [--no-fetch]` — 기본 날짜는 KST 오늘. meta는 환경변수 `GITHUB_SHA`, `RUN_URL`에서 읽고 없으면 `null`.

- [ ] **Step 1: `tests/test_pipeline.py` 작성** — fixture 일정을 `tmp_data_dir`의 games.jsonl에 넣고 `fetch=False`, 합성 번들 저장 후 실행.

```python
def test_run_writes_all_public_files_on_game_day(tmp_data_dir, bundle_path):
    seed_games(2026, fixture_json("schedule_2026-10-20_28.json"))     # 10-27에 STARTED 1경기, 10-26 RESULT
    out = run(date(2026, 10, 27), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert out["games_today"] == 1
    latest = json.loads((tmp_data_dir / "public/latest.json").read_text(encoding="utf-8"))
    assert latest["date"] == "2026-10-27" and latest["games"][0]["home"]["code"] == "SS"
    assert (tmp_data_dir / "public/status.json").exists() and (tmp_data_dir / "public/history.csv").exists()

def test_run_on_empty_day_touches_only_status(tmp_data_dir, bundle_path):
    seed_games(2026, fixture_json("schedule_2026-10-20_28.json"))
    run(date(2026, 10, 27), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    before = (tmp_data_dir / "public/latest.json").read_bytes()
    run(date(2026, 10, 24), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)   # 10-24 경기 없음
    assert (tmp_data_dir / "public/latest.json").read_bytes() == before
    assert json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))["next_game_date"] == "2026-10-25"
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_pipeline.py -q` — Expected: ImportError
- [ ] **Step 3: `scripts/run_pipeline.py` 구현** — `sys.path`에 `src` 추가 없이 `pip install -e .` 전제.
- [ ] **Step 4: 통과 확인** — Run: `pytest -q` — Expected: 모두 PASS
- [ ] **Step 5: 실제 실행 (로컬)** — Run: `python scripts/run_pipeline.py` — Expected: `data/public/latest.json`에 오늘(KST) 경기, `status.json` 생성. 경기가 없는 날이면 `status.json`만. 출력 JSON을 눈으로 확인: 선발 이름·ERA가 실제 값인지.
- [ ] **Step 6: `.github/workflows/daily.yml` 작성**

```yaml
name: daily predictions
on:
  schedule:
    - cron: "0 0 * * *"    # 09:00 KST
    - cron: "0 8 * * *"    # 17:00 KST
  workflow_dispatch:
permissions:
  contents: write
concurrency: daily
jobs:
  predict:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -r requirements.txt && pip install -e .
      - run: python scripts/run_pipeline.py
        env:
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
      - name: commit results
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/raw data/public
          git diff --cached --quiet && echo "no changes" || git commit -m "auto: predictions $(TZ=Asia/Seoul date +%F-%H%M)"
          git push
```

- [ ] **Step 7: Commit + push** — `git add scripts .github data/public && git commit -m "feat: 일일 파이프라인 + GitHub Actions daily.yml" && git push`
- [ ] **Step 8: Actions 수동 실행 확인** — 저장소 Actions 탭에서 `daily predictions` → Run workflow (ego-browser Profile 3 또는 사용자). Expected: 녹색 완료, `github-actions[bot]` 커밋 `auto: predictions ...` 생성, `data/public/status.json`의 `run_url`이 해당 실행을 가리킴. 실패 시 로그를 읽고 수정 후 재실행.

---

### Task 7: README v0.1 마무리

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README 내용** — 섹션: 무엇을 하는가(2문장) / 아키텍처 텍스트 다이어그램 (Actions → data/public → 사이트 예정) / Actions 상태 배지 `![daily](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/workflows/daily.yml/badge.svg)` / v0.1 모델 지표 표(`models/metrics_v0.1.json`에서 accuracy·log_loss·baseline 2종 옮겨 적기, 테스트 구간 명시) / 공개 파일 설명(`latest.json`, `history.csv`, `status.json` 각 1줄) / 로컬 실행법 3줄 / 데이터 출처 고지 / 로드맵(설계 문서 12절의 1~6단계 한 줄씩).
- [ ] **Step 2: 링크 확인** — Run: `grep -o "https://[^ )]*" README.md` — 각 링크가 실제 경로인지 눈으로 확인.
- [ ] **Step 3: Commit + push** — `git add README.md && git commit -m "docs: README v0.1" && git push`

---

## Self-Review 기록

- 스펙 12절 0단계 항목(저장소, 수집기, 최소 피처 LR, daily.yml, 세 공개 파일, README) → Task 1~7에 전부 대응. 스펙 8절의 `status.json` 필드·7절 메타 필드 → Task 5·6. 스펙 2절 누수 반목표 → Task 3 테스트.
- 타입 일치: `LeagueState`, `FEATURE_NAMES`, `FACTOR_LABELS`, `load_bundle`, `predict_game`, `upsert_history`, `settle_history` 이름이 Task 3→6에서 동일하게 쓰임.
- Review Focus 5개 → 각각 Task 3·5·5·6·3의 테스트에 반영됨.
