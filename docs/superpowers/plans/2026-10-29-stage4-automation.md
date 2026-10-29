# 4단계: 자동화 완성 + parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 저장소가 사람 손 없이 돌아가게 만든다 — PR·push마다 테스트와 parity 검사(`ci.yml`), 매주 재학습·군집 재계산(`weekly_retrain.yml`), 되감기 JSON(2026 시즌 날짜별 `latest.json` 형식 + 가을야구 진출 확률)과 라이브 `outlook` 블록(포스트시즌 시리즈 시뮬레이션), 그리고 노트북 05. 사이트(5단계)가 읽을 데이터 계약(§8)을 이 단계에서 완성한다.

**Architecture:** 선발 없는 팀 모델(2단계의 `ablation.no_starter`와 같은 절차)을 `models/team-2026.pkl`로 저장해 미래 경기 확률에 쓴다. `simulate.py`가 그 확률로 잔여 일정 1만 회 몬테카를로(가을야구 5위 이내 확률)와 시리즈 시뮬레이션(best-of-N)을 돌린다. `scripts/build_rewind.py`가 report-2026 모델로 2026 정규시즌을 날짜별로 다시 예측해 `data/public/rewind/2026/{date}.json`을 만든다(실제 선발·실제 결과 포함). `run_pipeline`은 오늘 상황에 맞는 `outlook`을 `latest.json`에 넣는다. `scripts/check_parity.py`가 커밋된 산출물(parquet 해시·군집 라벨·보고서·사이트 JSON·되감기)을 다시 만들어 비교하고 노트북 02~05를 실행한다. Actions는 `ci.yml`(push/PR: 테스트 + parity)과 `weekly_retrain.yml`(월요일 03:07 KST: 라이브 재학습 + 군집 재계산/비교 + 사이트 JSON + parity)을 추가한다.

**Tech Stack:** Python 3.12, numpy 1.26.4(2 전환 안 함), pandas, scikit-learn 1.6.1, lightgbm 4.7.0, PyYAML, nbclient, GitHub Actions(ubuntu-latest, pip cache).

**Spec:** `docs/superpowers/specs/2026-10-27-kbo-predict-design.md` §5.1(모델 두 벌), §6(`.py`↔`.ipynb` 동일성, `check_parity.py`), §7(자동화 표), §8(`outlook` 블록, `rewind/`), §12 item 4. 이월 항목: `docs/superpowers/plans/2026-10-27-stage0-deferred.md` "4단계(parity) 전에" + "3단계 리뷰에서 나온 항목".

## Global Constraints

- 기존 공개 파일 계약(`latest.json`, `status.json`, `history.csv`, `model_report.json`, `players.json`, `teams.json`)은 키 추가만. `model_report.json`·`models/report-2026.pkl`·`models/clusters.pkl`은 이번 단계에서 바이트 불변(재학습 대상 아님). 라이브 `models/win_model.pkl`(v0.2)은 주간 재학습 워크플로가 Actions에서 갱신하되 로컬에서는 바꾸지 않는다.
- 누수: 되감기 날짜 D의 피처·예측은 D 이후(같은 날 포함) 경기 결과를 쓰지 않는다(`run_pipeline.build_state(season, upto=D)`와 같은 규칙). 되감기 모델은 report-2026(2015~2024 학습)과 team-2026(같은 분할)만.
- 재현성: 시뮬레이션은 `numpy.random.default_rng(42)`, 같은 입력이면 같은 JSON. 되감기 전체를 두 번 만들면 `generated_at`·`commit_sha`를 뺀 나머지가 같다.
- 네트워크: 되감기·parity·노트북 05는 요청 0회. `run_pipeline --no-fetch`로 모든 테스트가 오프라인.
- 노트북 05: 로직은 `src/`·`scripts/` 호출만, 맨 위에 "하는 일 / 왜 / 짝 `run_pipeline.py`", 코드 셀마다 한국어 설명, 용어 첫 등장 시 한 줄(outlook, 몬테카를로, 되감기, 적중률), 실행 결과 포함, stderr 없음, 네트워크 없음. 문체는 03·04번.
- 의존성 `==` 고정. `requirements.txt`(런타임: 일일·주간 Actions)와 `requirements-dev.txt`(`-r requirements.txt` + pytest, matplotlib, nbformat, nbclient, nbconvert, ipykernel)로 나눈다. numpy는 1.26.4 유지.
- 커밋 트레일러 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`, 작성자는 저장소 로컬 설정. Windows 콘솔 `python -X utf8`. `data/processed/`·`artifacts/`는 git 제외.
- Actions 권한은 `contents: write`(+ `issues: write`)만, 시크릿 없음. 워크플로의 커밋 작성자는 `github-actions[bot]`(기존 daily.yml과 같은 블록).

## 계획 시점의 판정 (스펙이 비워 둔 곳·바꾼 곳)

- **팀 모델 파일**: `models/team-2026.pkl`(`model_version: "team-2026"`, 19개 `TEAM_FEATURES`, 2015~2024 학습·2025로 트리 수·캘리브레이션은 report와 같은 방법·train LOSO OOF). 되감기와 라이브 outlook 둘 다 이 파일을 쓴다(라이브용 2015~2026 팀 모델은 2027 시즌 전 주간 재학습 항목으로 이월). `train_win report`가 만들던 `ablation.no_starter`와 같은 절차이므로 그 번들을 저장하는 `train_win team` 명령으로 만든다(보고서 숫자 불변).
- **시뮬레이션의 경기 확률**: 잔여 경기마다 "그 날짜 시점의 팀 상태"로 팀 모델 확률을 한 번 계산하고 시뮬레이션 중에는 상태를 갱신하지 않는다(한 경기 결과가 다음 경기 피처를 바꾸는 효과는 무시). 가을야구 = 정규시즌 5위 이내(승률, 동률은 상대 전적 없이 승률만 → 동률 시 평균 순위). 스펙 "1만 회" 그대로.
- **시리즈 시뮬레이션 입력**: 현재 시리즈(팀 2개, best_of, 지금까지 승수, 남은 경기의 홈팀)는 `config/postseason.yaml`의 시즌별 목록에서 읽는다(사람이 유지; 2026: 와일드카드 OB@LG 1경기(LG 통과), 준PO HT 3-0 LG, PO SS vs HT best_of 5 — 2-2-1, KS KT vs PO 승자 best_of 7 — 2-2-1-1-1). 오늘 경기가 그 시즌 목록의 어느 시리즈에도 없으면(예: 시범경기) outlook은 `next_game` 꼴. 지금까지 승수는 games.jsonl의 FINAL 결과로 센다.
- **`round` 표기**: 정규시즌 개막 전 경기(2026-03-20~24 시범경기)는 `preseason`, 정규시즌 종료 후는 `postseason`(기존 코드는 둘 다 `postseason`).
- **status.json `mode`**: 오늘 또는 14일 안에 그 시즌 일정이 있으면 `live`, 없으면 `rewind`(비시즌). `latest.json`은 경기 있는 날만 쓴다(기존대로).
- **되감기 범위**: 2026 정규시즌 165개 날짜(03-28~10-12) 전부, 날짜당 파일 1개 + `index.json`. 시범경기·포스트시즌은 넣지 않는다. 선발은 박스스코어 실제 선발(`starter_source: "actual"` 명시), 예고 선발 이력이 없기 때문.
- **check_parity의 비교 대상**: 스펙 §6의 "artifacts/py vs artifacts/nb"를 "커밋된 산출물 vs 다시 만든 산출물 + 노트북 내부 assert"로 구체화한다. 노트북 02~05는 각자 매니페스트 해시·보고서와 비교하는 assert를 이미 갖고 있으므로, `check_parity`는 (1) 다시 만든 `features.parquet`·`matchup.parquet`·군집 라벨 CSV 해시 vs `models/manifest.json`, (2) `train_report` 재계산 vs `model_report.json`(generated_at·commit_sha·run_url 제외), (3) `players.json`·`teams.json` 재생성 vs 커밋본(같은 제외), (4) 되감기 재생성 샘플 3일 vs 커밋본, (5) 노트북 02~05 실행(오류 0)을 표로 출력하고 하나라도 다르면 비정상 종료. `--quick`은 (5)를 건너뛴다.
- **군집 parity(Linux BLAS)**: `cluster compare --against models/clusters.pkl`이 새로 맞춘 번들과 커밋본의 중심(allclose atol 1e-9)·맞춤 시즌 라벨(동일)을 비교한다. 주간 워크플로는 compare가 통과할 때만 새 번들(새 시즌 배정 포함)을 커밋하고, 실패하면 `parity-failure` 이슈를 열고 커밋본을 유지한다.
- **주간 재학습 커밋 노이즈**: `win_model.pkl`은 `trained_at` 때문에 매주 바이트가 바뀐다. 워크플로는 `train_win live`로 만든 번들의 2026 예측 확률이 기존과 `atol 1e-9`로 같으면 커밋하지 않는다(`train_win live --skip-if-same`).
- **numpy 2 전환**: 하지 않는다(로컬 anaconda 1.26.4와 Actions 고정 일치가 더 중요). 이월 문서에 결정만 적는다.
- **이월 항목 중 이번에 처리**: requirements-dev 분리, 노트북 실행 테스트 `slow` 마커, 경기 없는 날 `fetch_starters` 생략, 현재 시즌 FINAL인데 박스스코어 없는 경기 재수집, 공개 파일 원자적 쓰기(`_write_json`·`_write_history`·`upsert_games`), `predict.py` docstring "피처 수 + 1". 나머지는 그대로 이월.

## Review Focus

1. 되감기 날짜 D의 JSON은 D 이후 경기 결과(같은 날 2차전 포함)를 바꿔도 변하지 않는다 → Task 4 `test_rewind_day_ignores_future_games`.
2. 잔여 일정이 0경기인 날(시즌 마지막 날 이후)과 개막 전 날에도 `playoff_race`가 예외 없이 돌아간다(순위 확정 → 확률 0/1) → Task 3 `test_playoff_race_no_remaining_games`.
3. 시리즈에서 한 팀이 이미 best_of 과반을 이겼으면 확률 1.0/0.0, 남은 경기 0 → Task 3 `test_series_already_decided`.
4. 오늘 경기가 시범경기·미등록 시리즈이면 outlook은 `next_game` 꼴이고 파이프라인은 실패하지 않는다 → Task 5 `test_outlook_fallback_for_unknown_series`.
5. `check_parity`는 커밋본을 한 바이트 바꾸면(예: `players.json`의 숫자 하나) 비정상 종료하고 어떤 파일·키가 다른지 출력한다 → Task 6 `test_check_parity_detects_tamper`.

---

### Task 1: CI 워크플로 + 의존성 분리 + slow 마커

**Files:**
- Create: `.github/workflows/ci.yml`, `requirements-dev.txt`
- Modify: `requirements.txt`(노트북·테스트 패키지 제거), `pyproject.toml`(`markers = ["slow: 노트북 실행 등 느린 테스트"]`), `tests/test_notebooks.py`(`test_notebook_executes_without_errors`에 `@pytest.mark.slow`), `.github/workflows/daily.yml`(변경 없음 — `requirements.txt`만 설치하므로 가벼워짐), `README.md`(배지 3개: daily, ci, parity는 Task 6에서 추가)

**Interfaces:**
- Produces: `ci.yml` — `on: [push, pull_request]`(브랜치 main), `pip install -r requirements-dev.txt && pip install -e .`, 단계 1 `python -m pytest -q -m "not slow"`, 단계 2 `python scripts/check_parity.py --quick`(Task 6 전까지는 `if: hashFiles('scripts/check_parity.py') != ''`로 건너뜀). `concurrency: ci-${{ github.ref }}`. Python 3.12, `cache: pip`.
- [ ] **Step 1: 분리** — `requirements.txt`에서 pytest, matplotlib, nbformat, nbclient, nbconvert, ipykernel을 `requirements-dev.txt`(첫 줄 `-r requirements.txt`)로 옮긴다. 버전은 그대로.
- [ ] **Step 2: 마커** — `pyproject.toml` `[tool.pytest.ini_options]`에 `markers` 추가, 실행 테스트에 마커. Run: `python -X utf8 -m pytest -q -m "not slow"` → 노트북 실행 4개 제외하고 PASS(수를 보고서에).
- [ ] **Step 3: ci.yml 작성** — 위 인터페이스대로. `daily.yml`은 그대로.
- [ ] **Step 4: README 배지** — 기존 daily 배지 옆에 `ci` 워크플로 배지.
- [ ] **Step 5: 커밋** — `chore: ci 워크플로, requirements-dev 분리, slow 마커`. **컨트롤러가 이 시점에 push해 Linux에서 ci가 도는지 확인한다**(3단계 코드의 첫 Linux 실행).

---

### Task 2: 팀 모델 저장 (`train_win team`)

**Files:**
- Modify: `src/kbo_predict/train_win.py`(`_no_starter_ablation` → 번들도 반환하는 `train_team(df, *, train_seasons, val_season, test_season, kind, calibration) -> tuple[dict, dict]`로 분리, CLI `team` 명령), `src/kbo_predict/__init__.py`(`TEAM_VERSION = "team-2026"`), `models/manifest.json`(`models.team` 항목), `models/team-2026.pkl`(생성)
- Test: `tests/test_train_win.py`

**Interfaces:**
- Consumes: `fit_model`, `_early_stopping_rounds`, `oof_predictions`, `fit_calibrator`, `evaluate`, `update_manifest`, `REPORT_JSON`(선택된 kind·calibration을 읽는다).
- Produces: `train_team(...) -> (summary: dict, bundle: dict)` — `summary`는 지금 `ablation.no_starter`에 들어가는 dict와 같은 모양, `bundle["version"] == "team-2026"`, `bundle["features"] == TEAM_FEATURES`. `_no_starter_ablation`은 `train_team`을 호출해 summary만 돌려준다(보고서 바이트 불변). CLI `python -m kbo_predict.train_win team [--features data/processed/features.parquet]` → `models/team-2026.pkl` + manifest `models.team = {path, sha256, version, features_sha256}`; `model_report.json`은 건드리지 않는다. `load_bundle`/`predict_proba`는 그대로 쓴다.
- [ ] **Step 1: 테스트**

```python
def test_train_team_matches_report_ablation(small_df):
    report, _ = train_report(small_df, meta={})
    summary, bundle = train_team(small_df, kind=report["selected"], calibration=report["models"][report["selected"]]["calibration"])
    assert summary == report["ablation"]["no_starter"]          # 같은 절차 → 같은 숫자
    assert bundle["version"] == "team-2026" and bundle["features"] == list(TEAM_FEATURES)

def test_team_cli_writes_manifest_entry_only(tmp_paths):          # report/live/clusters 항목과 model_report.json 불변
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과** — `python -X utf8 -m pytest tests/test_train_win.py -v`
- [ ] **Step 3: 실데이터** — `python -X utf8 -m kbo_predict.train_win team` → `models/team-2026.pkl`, manifest. `python -X utf8 -c "import json;print(json.load(open('data/public/model_report.json'))['ablation']['no_starter'])"`가 번들의 `evaluate` 결과(2026)와 같은지 보고서에.
- [ ] **Step 4: 커밋** — `feat: 선발 없는 팀 모델 team-2026 저장`

---

### Task 3: 시뮬레이션 (`simulate.py`) — 가을야구 진출 확률, 시리즈 확률

**Files:**
- Create: `src/kbo_predict/simulate.py`, `config/postseason.yaml`
- Test: `tests/test_simulate.py`

**Interfaces:**
- Consumes: `features.LeagueState.team_line(code, on)`, `features.game_features`(팀 피처만 쓰려면 `starters=None` → 선발 피처 NaN, 팀 모델은 19개만 읽음), `train_win.predict_proba(bundle, X)`, `raw_store.load_games`, `seasons.REGULAR_SEASON`, `teams.TEAMS`.
- Produces:
  - `N_SIMS = 10_000`, `SEED = 42`, `PLAYOFF_SPOTS = 5`.
  - `game_probs(bundle, games: list[dict], state) -> list[float]` — 각 경기(홈·원정 코드·날짜)의 홈 승률을 팀 모델로. `starters=None`로 `game_features`를 부르고 `bundle["features"]` 열만 쓴다.
  - `playoff_race(standings: dict[str, tuple[int, int]], remaining: list[tuple[str, str, float]], *, n_sims=N_SIMS, seed=SEED) -> dict[str, dict]` — `standings[code] = (wins, losses)`, `remaining = [(home, away, p_home)]`. 반환 `code -> {"playoff_prob": float, "rank_now": int, "exp_wins": float}`. 벡터화: `rng.random((n_sims, len(remaining))) < p` → 팀별 승수 합 → 승률 순위(동률은 `scipy.stats.rankdata(method="average")`와 같은 평균 순위 → 5위 이내 = 순위 ≤ 5). 잔여 0경기면 현재 승률 순위로 0/1(동률이 5위에 걸치면 평균 순위 기준 ≤ 5).
  - `series(best_of: int, wins: tuple[int, int], remaining_homes: list[str], p_home_for_team0: list[float], *, n_sims, seed) -> dict` — `wins = (팀0 승, 팀1 승)`, `remaining_homes[i]`는 남은 i번째 경기의 홈이 `"team0"`/`"team1"`, `p_home_for_team0[i]`는 그 경기에서 팀0이 이길 확률. 반환 `{"win_prob": [p0, p1], "most_common_result": "4-2" 꼴(팀0 기준), "goes_distance_prob": float, "games_remaining_max": int}`. 이미 과반이면 `win_prob` 1/0, 나머지 0.
  - `outlook_for(season: int, on: str, games: list[dict], *, state, team_bundle, ps_config: dict | None) -> dict` — §8 꼴: 정규시즌 날짜 → `{"type": "playoff_race", "as_of": on, "teams": {code: {...}}}`(오늘 경기 양 팀만이 아니라 10팀 전부, 사이트가 고름); 포스트시즌 날짜이고 `ps_config`의 시리즈에 오늘 경기 양 팀이 있으면 `{"type": "series", "name", "best_of", "teams": [code0, code1], "wins": [w0, w1], "win_prob": [...], "most_common_result", "goes_distance_prob"}`; 그 외(시범경기·미등록·경기 없음) → `{"type": "next_game", "next_game_date": str | None}`.
  - `config/postseason.yaml` 모양: `2026: [{name: "와일드카드", teams: [LG, OB], best_of: 1, start: 2026-10-14}, {name: "준플레이오프", teams: [HT, LG], best_of: 5, start: 2026-10-17, homes: [HT, HT, LG, LG, HT]}, {name: "플레이오프", teams: [SS, HT], best_of: 5, start: 2026-10-25, homes: [SS, SS, HT, HT, SS]}, {name: "한국시리즈", teams: [KT, null], best_of: 7, start: null, homes: [KT, KT, null, null, KT, null, KT]}]` — `null` 팀은 미정(그 시리즈는 건너뜀). `load_postseason(season) -> list[dict]`.
- [ ] **Step 1: 테스트** (`tests/test_simulate.py`)

```python
def test_series_symmetric_half():   # best_of 5, 1-1, 모두 p=0.5 → win_prob ≈ [0.5, 0.5] (±0.02), goes_distance_prob ≈ 0.375
def test_series_already_decided():  # best_of 5, wins (3,1) → win_prob == [1.0, 0.0], games_remaining_max == 0
def test_series_certain():          # p=1.0 전부 → [1.0, 0.0], most_common_result "3-1" (1-1에서 시작)
def test_playoff_race_no_remaining_games():  # 10팀 승패만 → 상위 5팀 1.0, 나머지 0.0
def test_playoff_race_clinched():   # 한 팀이 남은 경기 다 져도 5위 안 → 1.0
def test_playoff_race_deterministic():  # 같은 입력 두 번 → 같은 dict
def test_outlook_series_from_config(tmp_yaml): # PO SS vs HT, FINAL 1-1 → type series, wins [1,1]
def test_outlook_fallback_for_unknown_series(): # 2026-03-20 시범경기 → type next_game
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과** — `python -X utf8 -m pytest tests/test_simulate.py -v`
- [ ] **Step 3: 실데이터 확인** — 2026-10-29 PO(SS vs HT 1-1): `outlook_for` 출력(승률·가장 흔한 결말)을 보고서에. 2026-09-01 정규시즌: 10팀 `playoff_prob` 표. 실행 시간(< 5초/날짜).
- [ ] **Step 4: 커밋** — `feat: 가을야구·시리즈 몬테카를로 시뮬레이션과 outlook`

---

### Task 4: 되감기 JSON 생성 (`scripts/build_rewind.py`)

**Files:**
- Create: `scripts/build_rewind.py`, `src/kbo_predict/rewind.py`
- Create: `data/public/rewind/2026/{YYYY-MM-DD}.json` ×165, `data/public/rewind/2026/index.json`
- Test: `tests/test_rewind.py`

**Interfaces:**
- Consumes: `run_pipeline.build_state(season, upto)`(→ `rewind.state_before(season, on)`로 옮기고 `run_pipeline`은 그것을 부른다), `features.starter_ids(box)`, `predict.predict_game(bundle, game, state, starters)`, `simulate.outlook_for`, `train_win.load_bundle`, `publish._write_json`, `raw_store.load_games/load_boxscores`.
- Produces:
  - `rewind.day_payload(season, on, *, games, boxscores, bundle, team_bundle, starter_types=None, meta) -> dict` — `latest.json`과 같은 키 + `mode: "rewind"`, `model_version: "report-2026"`, `starter_source: "actual (boxscore pitching order 1)"`, `outlook`(playoff_race), 경기마다 `result: {"home_score", "away_score", "winner": "HOME"|"AWAY"|"DRAW"|None, "correct": bool|None}` 추가. 정규시즌 FINAL 경기만, `(game_id)` 순.
  - `rewind.build_season(season, *, out_dir, bundle, team_bundle, meta, dates=None) -> dict` — 날짜 전부(또는 `dates`) 생성, `index.json = {"season", "model_version", "generated_at", "commit_sha", "dates": [{"date", "games", "correct", "decided"}], "accuracy": float, "n_decided": int}`.
  - CLI `python -X utf8 scripts/build_rewind.py --season 2026 [--dates 2026-05-01,2026-05-02]`.
- [ ] **Step 1: 테스트**

```python
def test_rewind_day_ignores_future_games(real_small):   # 2026-05-01 payload를 만들고, 05-01·05-02 결과를 바꾼 복사본으로 다시 만들어 home_win_prob 동일
def test_rewind_day_has_results_and_outlook(real_small): # result.correct == (p>0.5) == (winner=="HOME"); outlook.type == "playoff_race"; 10팀
def test_rewind_matches_report_model(real_small):        # 2026-05-01의 home_win_prob == report-2026으로 features.parquet 행을 예측한 값(소수 4자리)
def test_rewind_deterministic(tmp_path):                 # 같은 날짜 두 번 → generated_at 제외 동일
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과**
- [ ] **Step 3: 전체 생성** — `python -X utf8 scripts/build_rewind.py --season 2026` → 165 파일 + index. 총 크기(MB)·정확도(`index.accuracy`는 `model_report.json`의 lr test accuracy .5940과 같아야 함 — 다르면 멈추고 보고)·실행 시간을 보고서에.
- [ ] **Step 4: 커밋** — `feat: 2026 시즌 되감기 JSON(report-2026, 가을야구 확률 포함)` (데이터 포함)

---

### Task 5: 파이프라인 — outlook·round·mode, 이월 항목

**Files:**
- Modify: `scripts/run_pipeline.py`, `src/kbo_predict/predict.py`(`round`: `preseason`/`regular`/`postseason`; docstring "피처 수 + 1"), `src/kbo_predict/publish.py`(`write_latest(..., outlook=None)`, `_write_json`·`_write_history` 원자적 쓰기: `.tmp` + `os.replace`), `src/kbo_predict/raw_store.py`(`upsert_games` 원자적), `src/kbo_predict/collect.py`(현재 시즌 FINAL인데 박스스코어 없는 경기 재수집: `collect_missing_boxscores(season, *, session=None, limit=20) -> dict`)
- Test: `tests/test_pipeline.py`, `tests/test_predict.py`, `tests/test_publish.py`, `tests/test_collect.py`

**Interfaces:**
- Consumes: Task 3 `simulate.outlook_for`, `load_postseason`; Task 2 `models/team-2026.pkl`(`TEAM_PKL = Path("models/team-2026.pkl")`, 없으면 outlook `next_game` + 경고).
- Produces: `latest.json`에 `outlook` 키(§8). `status.json`의 `mode`: 오늘 또는 14일 내 일정이 있으면 `live`, 없으면 `rewind`. 오늘 경기가 없으면 `fetch_starters` 호출 생략. `collect_missing_boxscores`는 `run()`의 ① 수집 단계에서 fetch=True일 때 호출(최대 20경기/실행, 5초 간격 준수).
- [ ] **Step 1: 테스트**

```python
def test_latest_has_outlook_series(tmp_data_dir_postseason):   # 2026-10-29 → outlook.type == "series", wins [1,1]
def test_outlook_fallback_for_unknown_series(tmp_data_dir):    # 시범경기 날짜 → next_game, 파이프라인 성공
def test_status_mode_rewind_when_no_schedule(tmp_data_dir):    # 2026-12-01 → mode "rewind", latest.json 불변
def test_round_preseason():                                    # 2026-03-20 → "preseason"; 2026-10-29 → "postseason"; 2026-05-01 → "regular"
def test_no_fetch_starters_when_no_games(monkeypatch):         # fetch_starters가 호출되지 않음
def test_collect_missing_boxscores_refetches_final_without_box(monkeypatch):
def test_write_json_atomic(tmp_path):                          # 쓰는 도중 예외 → 기존 파일 유지, .tmp 없음
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과** — `python -X utf8 -m pytest tests/test_pipeline.py tests/test_predict.py tests/test_publish.py tests/test_collect.py tests/test_raw_store.py -v`
- [ ] **Step 3: 오프라인 실행** — `python -X utf8 scripts/run_pipeline.py --no-fetch` → `latest.json`에 outlook(series) 확인 후 **`git checkout -- data/public/latest.json data/public/status.json data/public/history.csv`** (Actions 소유).
- [ ] **Step 4: 커밋** — `feat: latest.json outlook 블록, 시범경기 round, 비시즌 mode, 원자적 쓰기, 박스스코어 재수집`

---

### Task 6: parity 검사 + 주간 재학습 워크플로

**Files:**
- Create: `scripts/check_parity.py`, `.github/workflows/weekly_retrain.yml`
- Modify: `src/kbo_predict/cluster.py`(CLI `compare --against models/clusters.pkl [--new models/clusters.new.pkl]`), `src/kbo_predict/train_win.py`(CLI `live --skip-if-same`), `.github/workflows/ci.yml`(parity 단계 활성), `README.md`(parity 배지 = ci 워크플로 배지, "parity" 잡 이름)
- Test: `tests/test_check_parity.py`, `tests/test_cluster.py`, `tests/test_train_win.py`

**Interfaces:**
- Produces:
  - `scripts/check_parity.py [--quick] [--rewind-dates 2026-04-01,2026-07-01,2026-10-12]` — 판정 항목 (1)~(5) 표(`항목 | 커밋본 | 재생성 | 결과`)를 stdout에, 모두 같으면 exit 0, 아니면 exit 1과 다른 파일·키 목록. 재생성 산출물은 `artifacts/parity/`(gitignore)에만 쓴다. `features.parquet`·`matchup.parquet`가 없으면 먼저 만든다(`artifacts/parity/`).
  - `cluster compare` — 중심 `np.allclose(atol=1e-9)` + 맞춤 시즌(2015~2025) 라벨 동일 → exit 0; 아니면 exit 1 + 최대 차이 출력.
  - `train_win live --skip-if-same` — 새 번들의 `features.parquet` 전 행 `predict_proba`가 기존 `win_model.pkl`과 `atol 1e-9`로 같으면 파일·manifest를 쓰지 않고 "unchanged" 출력(exit 0).
  - `weekly_retrain.yml` — `cron: "7 18 * * 0"`(월요일 03:07 KST) + `workflow_dispatch`, `concurrency: weekly`, 단계: `pip install -r requirements-dev.txt && pip install -e .` → `python -m kbo_predict.features --out data/processed/features.parquet --matchup-out data/processed/matchup.parquet --clusters models/clusters.pkl` → `python -m kbo_predict.train_win live --skip-if-same` → `python -m kbo_predict.cluster fit --out models/clusters.new.pkl --types artifacts/parity/types.csv --manifest artifacts/parity/manifest.json` → `python -m kbo_predict.cluster compare --against models/clusters.pkl --new models/clusters.new.pkl && mv models/clusters.new.pkl models/clusters.pkl && python -m kbo_predict.cluster fit`(통과 시에만 정식 fit으로 manifest 갱신) → `python -m kbo_predict.cluster publish` → `python scripts/check_parity.py --quick` → `git add models data/public && commit "auto: weekly retrain $(date +%F)"`(변경 있을 때만) → 실패 시 `parity-failure` 라벨 이슈(기존 daily.yml의 이슈 블록 재사용, 열린 이슈 있으면 코멘트).
- [ ] **Step 1: 테스트**

```python
def test_check_parity_passes_on_committed(tmp_copy_of_repo_data):     # --quick, exit 0 (실데이터, 약 1~2분)
def test_check_parity_detects_tamper(tmp_copy):                       # players.json의 x 하나를 바꾸면 exit 1, 출력에 "players.json" 포함
def test_cluster_compare_same_and_different(synthetic):               # 같은 번들 0, 중심 하나 +1e-6 → 1
def test_live_skip_if_same(tmp_paths):                                # 두 번째 실행 "unchanged", 파일 mtime 불변
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과**
- [ ] **Step 3: 전체 실행** — `python -X utf8 scripts/check_parity.py`(노트북 포함, 시간 보고) → exit 0. `ci.yml`의 parity 단계 활성(`--quick`).
- [ ] **Step 4: 커밋** — `feat: check_parity, 주간 재학습 워크플로, cluster compare, live --skip-if-same`. **컨트롤러가 push해 ci(parity 포함)가 Linux에서 통과하는지 확인한다.** 통과하지 않으면(예: BLAS 차이로 `types_sha256` 불일치) 그 결과를 보고 판정한다.

---

### Task 7: 노트북 05 오늘 경기 예측

**Files:**
- Create: `notebooks/05_오늘_경기_예측.ipynb`
- Modify: `tests/test_notebooks.py`(`NOTEBOOKS["05_오늘_경기_예측.ipynb"] = "run_pipeline.py"`)

- 구성(마크다운 → 코드 쌍): 1 준비(03·04와 같은 설정, `scripts/`도 경로에) · 2 "오늘"을 고정한다: `TARGET = 2026-10-29`(저장된 예고 선발이 있는 날) — 라이브와 노트북의 차이(예고 vs 실제 선발, 네트워크 없음) 설명 · 3 상태 만들기 `rewind.state_before` → 양 팀 요약 표 · 4 선발 블록과 유형(`starter_types`) · 5 예측 `predict_game` → 확률·요인 top 5 막대 · 6 outlook: 시리즈 시뮬레이션(`simulate.series`) 결과와 "가장 흔한 결말" 분포 그래프, 몬테카를로 설명 · 7 되감기: `rewind/2026/2026-09-01.json`을 읽어 그 날 예측·결과·가을야구 확률 표 + `index.json`의 누적 적중률 곡선 · 8 history.csv: 라이브 기록의 적중률(모델 버전별) · 9 패리티: 노트북이 만든 2026-10-29 예측 dict == `run_pipeline.run(..., fetch=False)`를 임시 폴더에 돌린 `latest.json`의 같은 경기(generated_at 제외) `assert`; 되감기 2026-09-01 재생성 == 커밋본(generated_at·commit_sha 제외) `assert` · 10 마무리(한계: 예고 선발 변경, 시뮬레이션의 상태 고정 가정, 포스트시즌 보정 없음).
- [ ] **Step 1: 테스트 등록 → 실패** — `python -X utf8 -m pytest tests/test_notebooks.py -k 05 -v`
- [ ] **Step 2: 작성 + 실행**(커널 cwd `notebooks/`) → 통과 확인(구조·실행·stderr 없음)
- [ ] **Step 3: 커밋** — `docs: 노트북 05 오늘 경기 예측(실행 결과 포함)`

---

### Task 8: 문서

**Files:**
- Modify: `README.md`(자동화 절: 워크플로 3개 표·배지, 되감기·outlook 데이터 계약, 노트북 05, 테스트 수, 로컬 실행 명령 갱신), `docs/superpowers/specs/2026-10-27-kbo-predict-design.md`(§6 check_parity 구체화, §7 표에 cron 분 단위·실제 동작, §8 `rewind`·`outlook` 확정 모양, §12 item 4 완료, §13 "구현하며 확정한 규칙(4단계)" = 위 판정 목록 + 실행 중 ruling, §14 numpy 2 결정), `docs/superpowers/plans/2026-10-27-stage0-deferred.md`(4단계 항목 완료/이월 정리, "5단계 전에": 2027 라이브 팀 모델, 시뮬레이션 상태 갱신, 예고 선발 이력, Genspark 확인 등)
- [ ] **Step 1: 수정** — 숫자는 `models/manifest.json`, `rewind/2026/index.json`, 태스크 보고서에서.
- [ ] **Step 2: 전체 테스트** — `python -X utf8 -m pytest -q`(slow 포함) → 수를 README에
- [ ] **Step 3: 커밋** — `docs: 4단계 완료 — README·스펙·이월 항목 갱신`

---

## 컨트롤러 절차

1. Task 1 → push → Actions ci 결과 확인(실패 시 ruling) → 2 → 3 → 4 → 5 → 6 → push → ci 확인 → 7 → 8. 순차.
2. Task 6 뒤 Codex 교차 검토 1회(시뮬레이션 통계·되감기 누수·parity 범위).
3. 최종 전체 리뷰(opus) → 수정 1회 → 재리뷰 → push → 메모리 갱신.
