# 0단계 수직 슬라이스 v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MyKBOStats에서 2026 KBO 경기 일정·결과·박스스코어를 수집하고, 최소 피처 로지스틱 회귀로 오늘 경기의 홈팀 승률을 예측해, GitHub Actions가 매일 `data/public/latest.json` · `history.csv` · `status.json`을 커밋하는 파이프라인을 공개 저장소에 올린다.

> **2026-10-27 개정:** 데이터 소스를 네이버 스포츠 API에서 **MyKBOStats**(HTML)로 바꿨다. 네이버는 Python 클라이언트를 TLS 지문·UA 수준에서 차단해(로컬·Actions 모두 확인) 사용할 수 없고, 우회는 하지 않는다. Task 2·3이 그에 맞게 다시 쓰였고, v0.1은 **경기 전 예상 선발 소스가 없어 선발 ERA 피처 없이** 간다 (스펙 4.1·5.1).

**Architecture:** `src/kbo_predict/` 패키지에 수집(mykbo_client, mykbo_parse, raw_store, collect) → 피처(features) → 학습(train_win) → 추론·발행(predict, publish) 모듈을 두고, `scripts/run_pipeline.py`가 날짜 하나를 받아 순서대로 호출한다. 파싱한 일정·박스스코어는 `data/raw/{season}/`에 커밋하고 원본 HTML은 로컬 캐시에만 둔다. 피처는 날짜순으로 상태를 누적하는 `LeagueState`로 계산해 "경기 이전 데이터만 사용"을 구조적으로 보장한다. 모델은 로컬에서 한 번 학습해 커밋하고, Actions는 추론만 한다.

**Tech Stack:** Python 3.12, requests, beautifulsoup4 (html.parser), pandas 2.2, scikit-learn 1.6 (LogisticRegression + StandardScaler), joblib, pytest 9, GitHub Actions (ubuntu-latest).

**Spec:** `docs/superpowers/specs/2026-10-27-kbo-predict-design.md` (특히 4절 데이터, 5.1 승패 모델, 7절 자동화, 8절 데이터 계약, 12절 0단계)

## Global Constraints

- 데이터 소스는 `https://mykbostats.com` 만 사용. koreabaseball.com·네이버 요청 금지, 봇 차단 우회(UA·TLS 지문 위조) 금지 (스펙 2절 반목표, 4.1).
- 요청 간 `sleep` **5초**(robots.txt Crawl-delay), `User-Agent: Mozilla/5.0 (compatible; kbo-predict/0.1; +https://github.com/kimminseo2323-prog/2610_KBO_predict)`, `timeout=20`, 실패 시 1회 재시도 후 예외 (스펙 4.4). `/stats/compare/` 접근 금지.
- 피처는 해당 경기 날짜 **이전**(`date < 대상 날짜`)의 `status == "FINAL"` 경기만으로 계산 (스펙 2절 반목표 "누수").
- 무승부(홈·원정 점수 동일)는 학습에서 제외 (스펙 5.1).
- 원본 HTML은 커밋하지 않는다 (`data/cache/` gitignore). 파싱 결과(`games.jsonl`, `boxscores.jsonl.gz`)만 커밋 (스펙 4.2).
- 난수 seed 42 (스펙 5.3). 모델 버전 문자열 `"v0.1"`.
- 시각은 모두 `Asia/Seoul`; JSON의 `generated_at`은 ISO 8601 with offset (예 `2026-10-28T09:02:11+09:00`).
- 모든 공개 JSON에 `generated_at`, `commit_sha`, `run_url`, `model_version`, `mode` 포함 (스펙 7절).
- 저장소: `https://github.com/kimminseo2323-prog/2610_KBO_predict`, 브랜치 `main`. 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- 노트북은 0단계 범위 밖 (스펙 12절 0단계).

## Review Focus

1. **경기 페이지에 박스스코어가 없음** (취소된 경기, 아직 안 치른 경기): `parse_game`이 빈 `pitching`/`batting`을 돌려주고 수집기는 `status != "FINAL"`이면 경기 페이지를 아예 가져오지 않는다 — Task 2 테스트.
2. **우천 취소** (게임 라인에 `Canceled`): 피처 상태에 반영되지 않고, `history.csv`에 `status: "CANCELED"`로 남되 `correct`는 빈칸 — Task 3·5 테스트.
3. **같은 날 두 번 실행** (09:00 예측 후 17:00 재실행): `history.csv`에 같은 `game_id` 행이 두 개 생기지 않고 확률만 갱신, 단 이미 `FINAL`인 행은 덮어쓰지 않는다 — Task 5 테스트.
4. **경기 없는 날**: `latest.json`은 건드리지 않고 `status.json`만 갱신, `next_game_date`에 다음 경기 날짜 — Task 6 테스트.
5. **시즌 첫 경기처럼 누적 데이터가 0일 때**: 승률 0.5, 최근 10경기 0.5, 득실차 0.0 기본값으로 예측이 나와야 하고 ZeroDivision이 없어야 한다 — Task 3 테스트.

---

## 파일 구조

```
pyproject.toml                      # 패키지 메타 + pytest 설정
requirements.txt                    # 런타임 + 테스트 의존성 (Actions도 이 파일 사용)
src/kbo_predict/__init__.py
src/kbo_predict/mykbo_client.py     # HTTP 호출만 (UA, 5초 sleep, 재시도, HTML 캐시)
src/kbo_predict/mykbo_parse.py      # 주간 일정 HTML → 경기 행, 경기 HTML → 박스스코어
src/kbo_predict/teams.py            # 팀 풀네임 ↔ 코드 ↔ 한국어 표시명
src/kbo_predict/seasons.py          # 시즌별 정규시즌 시작/종료 날짜
src/kbo_predict/raw_store.py        # data/raw 읽기/쓰기 (jsonl, jsonl.gz)
src/kbo_predict/collect.py          # 기간 수집 + 증분 수집 CLI
src/kbo_predict/features.py         # LeagueState, 경기별 피처
src/kbo_predict/train_win.py        # 학습 + 지표 + 모델 저장 CLI
src/kbo_predict/predict.py          # 모델 로드, 확률·요인 계산
src/kbo_predict/publish.py          # latest.json / history.csv / status.json 쓰기
scripts/run_pipeline.py             # 날짜 하나에 대한 전체 실행
.github/workflows/daily.yml
data/raw/2026/games.jsonl           # 일정 행 (game_id당 1줄, 최신 상태)
data/raw/2026/boxscores.jsonl.gz    # FINAL 경기의 파싱된 박스스코어
data/cache/html/                    # 원본 HTML 캐시 (gitignore)
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

### Task 2: MyKBOStats 클라이언트 + 파서 + 원본 저장 + 수집 CLI (개정)

**Files:**
- Create: `src/kbo_predict/mykbo_client.py`, `src/kbo_predict/mykbo_parse.py`, `src/kbo_predict/teams.py`, `src/kbo_predict/seasons.py`, `src/kbo_predict/raw_store.py`, `src/kbo_predict/collect.py`, `tests/conftest.py`
- Delete: `src/kbo_predict/naver_client.py`, 기존 `src/kbo_predict/collect.py`·`raw_store.py`(네이버용), `tests/test_naver_client.py`, `tests/test_raw_store.py`, `tests/test_collect.py`, `tests/fixtures/*.json`(네이버 응답 3개), `.github/workflows/probe-naver.yml`
- Modify: `requirements.txt` (+`beautifulsoup4>=4.12`), `.gitignore` (+`data/cache/`)
- Test: `tests/test_mykbo_parse.py`, `tests/test_mykbo_client.py`, `tests/test_raw_store.py`, `tests/test_collect.py`
- Fixtures (이미 있음): `tests/fixtures/mykbo_week_2026-08-11.html` (정규시즌 30경기, `Canceled` 2개 포함), `tests/fixtures/mykbo_week_2026-10-27.html` (포스트시즌: Final 1, 예정 3), `tests/fixtures/mykbo_game_14048_final.html` (Kia @ Samsung 10-26, Final 5:1 삼성 승), `tests/fixtures/mykbo_game_14050_scheduled.html` (예정 경기, 박스스코어 없음)

**Interfaces:**
- Produces:
  - `teams.TEAMS: dict[str, dict]` — 풀네임 키: `{"Doosan Bears": {"code": "OB", "ko": "두산"}, "Lotte Giants": {"code": "LT", "ko": "롯데"}, "KT Wiz": {"code": "KT", "ko": "KT"}, "Kiwoom Heroes": {"code": "WO", "ko": "키움"}, "SSG Landers": {"code": "SK", "ko": "SSG"}, "Samsung Lions": {"code": "SS", "ko": "삼성"}, "Hanwha Eagles": {"code": "HH", "ko": "한화"}, "Kia Tigers": {"code": "HT", "ko": "KIA"}, "LG Twins": {"code": "LG", "ko": "LG"}, "NC Dinos": {"code": "NC", "ko": "NC"}}`; `teams.code_for(full_name: str) -> str` (모르는 이름이면 `KeyError`); `teams.short_to_code(short: str) -> str` — 박스스코어 표 헤더의 짧은 이름(`"Kia"`, `"Samsung"`, `"KT"`, `"SSG"`, `"LG"`, `"NC"`, `"Doosan"`, `"Lotte"`, `"Kiwoom"`, `"Hanwha"`) → 코드
  - `seasons.REGULAR_SEASON: dict[int, tuple[date, date]]` — `{2026: (start, end)}`. 값은 Step 13 백필 후 주간 일정에서 확인해 채운다: start = 3월 이후 하루에 ≥4경기가 처음 열린 날, end = 하루 ≥4경기가 마지막으로 열린 날. `seasons.is_regular(season: int, d: date) -> bool`
  - `mykbo_client.USER_AGENT`, `BASE_URL = "https://mykbostats.com"`, `SLEEP_S = 5.0`
  - `mykbo_client.fetch_html(path: str, *, session=None, sleep_s: float = SLEEP_S, cache_dir: Path | None = None) -> str` — `time.sleep(sleep_s)` 후 GET(`timeout=20`), 실패 1회 재시도 후 예외. `cache_dir`가 주어지고 `cache_dir/<path를 파일명으로 안전하게 바꾼 것>.html`이 있으면 요청 없이 그 내용을 반환, 없으면 요청 후 저장. 기본 cache_dir은 `raw_store.data_dir()/"cache"/"html"`.
  - `mykbo_client.week_path(d: date) -> str` — `/schedule/week_of/YYYY-MM-DD`
  - `mykbo_parse.parse_week(html: str) -> list[dict]` — 각 `<a id="game-line-{id}" href data-game-datetime>`에서 `{"game_id": int, "path": str, "datetime_utc": str, "date": "YYYY-MM-DD"(KST 기준), "season": int, "away": full_name, "home": full_name, "away_code", "home_code", "away_score": int | None, "home_score": int | None, "status": "FINAL" | "LIVE" | "SCHEDULED" | "CANCELED", "status_note": str | None (예: "Rained Out"), "time_kst": "18:30" | None, "stadium": str | None}`. 홈/원정은 href의 `{Away}-vs-{Home}` 순서 = 게임 라인에 나오는 순서(첫 팀 원정, 둘째 팀 홈). 텍스트에 `Canceled`→CANCELED, `Final`→FINAL, `Live`→LIVE, 그 외 시간 표기(`6:30pm`)→SCHEDULED.
  - `mykbo_parse.parse_game(html: str) -> dict` — `{"game_id": int, "date", "stadium": str, "status": "FINAL" | "SCHEDULED" | ..., "away": {"name", "code", "score"}, "home": {...}, "batting": {"away": [row], "home": [row]}, "pitching": {"away": [row], "home": [row]}, "linescore": {"away": [int...], "home": [int...]} | None}`. 타자 row: `{"order": int, "player_id": int, "name", "pos", "ab", "r", "h", "hr", "rbi", "bb", "so", "hbp"}` (`<th>`가 `Pos, BA, AB, …`인 표; 첫 열 `"1 Park Jung-woo #1"`에서 타순·이름, `/players/{id}` 링크에서 id). 투수 row: `{"order": int, "player_id", "name", "ip_outs": int, "np", "r", "er", "h", "hr", "so", "bb", "hbp"}` (`<th>`가 `ERA, IP, NP, …`인 표; IP `"4&nbsp;&frac13;"`은 `html.unescape` 후 `parse_innings`). 표의 팀은 첫 `<th>` 텍스트(`"Kia"`)를 `teams.short_to_code`로 바꿔 `<title>`의 `"{Away} vs. {Home} - …"`에서 얻은 홈/원정에 배정. 박스스코어 표가 없으면 `batting`/`pitching`은 빈 리스트.
  - `mykbo_parse.parse_innings(inn: str) -> int` — 아웃 수. `"5"→15`, `"4 ⅓"→13`, `"0 ⅔"→2`, `""→0` (⅓=U+2153, ⅔=U+2154, `&frac13;`/`&nbsp;`는 unescape 후)
  - `raw_store.data_dir() -> Path` (환경변수 `KBO_DATA_DIR` 또는 `data`), `games_path(season) -> Path` (`data/raw/{season}/games.jsonl`), `boxscores_path(season)` (`boxscores.jsonl.gz`)
  - `raw_store.upsert_games(season: int, games: list[dict]) -> int` — `game_id` 기준 덮어쓰기, 저장 시 `(date, game_id)` 정렬, 반환은 신규+내용 변경 수
  - `raw_store.load_games(season: int) -> list[dict]`
  - `raw_store.append_boxscores(season: int, boxscores: dict[int, dict]) -> int` — 한 줄 = `parse_game` 결과 dict (game_id 포함), 이미 있는 game_id는 건너뜀
  - `raw_store.load_boxscores(season: int) -> dict[int, dict]`
  - `collect.collect_range(from_date: date, to_date: date, *, season: int | None = None, sleep_s: float = SLEEP_S) -> dict` — `from_date`부터 7일 간격으로 `to_date`까지 주간 페이지를 가져와 `parse_week` → 범위 밖 날짜 행은 버리고 upsert → `status == "FINAL"`이고 boxscore가 없는 경기만 경기 페이지를 가져와 `parse_game` → append. 반환 `{"weeks": n, "games": n, "boxscores": n}`. 진행 상황은 경기 20개마다 stderr에 출력, boxscore는 20개마다 flush.
  - CLI: `python -m kbo_predict.collect --from 2026-03-20 --to 2026-11-05 [--sleep 5]`

- [ ] **Step 0: 네이버용 파일 삭제** — 위 Delete 목록을 `git rm`, `requirements.txt`에 `beautifulsoup4>=4.12` 추가, `.gitignore`에 `data/cache/` 추가, `README.md`의 데이터 출처 고지를 "데이터 출처: MyKBOStats (mykbostats.com, 비공식 팬 사이트, robots.txt Crawl-delay 5초 준수), 개인 학습용"으로 교체. `pip install -r requirements.txt`.
- [ ] **Step 1: `tests/conftest.py`** — fixture `fixture_html(name) -> str` (`tests/fixtures/<name>` UTF-8 읽기), `tmp_data_dir` (`tmp_path/"data"`를 `KBO_DATA_DIR`로 monkeypatch, Path 반환)
- [ ] **Step 2: `tests/test_mykbo_parse.py` 작성**

```python
@pytest.mark.parametrize("inn,outs", [("5", 15), ("4 ⅓", 13), ("0 ⅔", 2), ("", 0), ("6 ⅔", 20)])
def test_parse_innings(inn, outs): assert parse_innings(inn) == outs

def test_parse_week_regular_season(fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2026-08-11.html"))
    assert len(rows) == 30
    g = next(r for r in rows if r["game_id"] == 13802)
    assert g == {**g, "path": "/games/13802-Hanwha-vs-Doosan-20260811", "date": "2026-08-11", "season": 2026,
                 "away": "Hanwha Eagles", "home": "Doosan Bears", "away_code": "HH", "home_code": "OB",
                 "away_score": 3, "home_score": 6, "status": "FINAL"}
    canceled = [r for r in rows if r["status"] == "CANCELED"]
    assert {r["game_id"] for r in canceled} == {13827, 13828}
    assert next(r for r in canceled if r["game_id"] == 13828)["status_note"] == "Rained Out"
    assert all(r["away_score"] is None for r in canceled)

def test_parse_week_postseason_scheduled(fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2026-10-27.html"))
    assert [r["game_id"] for r in rows] == [14052, 14050, 14053, 14054] or len(rows) == 4
    g = next(r for r in rows if r["game_id"] == 14050)
    assert g["status"] == "SCHEDULED" and g["time_kst"] == "18:30" and g["stadium"] == "Gwangju" and g["home_code"] == "HT" and g["date"] == "2026-10-29"
    f = next(r for r in rows if r["game_id"] == 14052)
    assert f["status"] == "FINAL" and (f["away_score"], f["home_score"]) == (3, 8)

def test_parse_game_final(fixture_html):
    g = parse_game(fixture_html("mykbo_game_14048_final.html"))
    assert g["game_id"] == 14048 and g["date"] == "2026-10-26" and g["status"] == "FINAL"
    assert g["away"] == {"name": "Kia Tigers", "code": "HT", "score": 1} and g["home"]["code"] == "SS" and g["home"]["score"] == 5
    assert g["batting"]["away"][0] == {**g["batting"]["away"][0], "order": 1, "name": "Park Jung-woo", "pos": "RF", "ab": 5, "h": 0, "so": 2}
    p = g["pitching"]["away"][0]
    assert p["name"] == "Naile" and p["ip_outs"] == 13 and p["er"] == 1 and p["so"] == 3 and p["order"] == 1
    assert g["pitching"]["home"][0]["name"] == "Paddack" and g["pitching"]["home"][0]["ip_outs"] == 14
    assert all(isinstance(r["player_id"], int) for side in g["batting"].values() for r in side)

def test_parse_game_scheduled_has_no_boxscore(fixture_html):
    g = parse_game(fixture_html("mykbo_game_14050_scheduled.html"))
    assert g["game_id"] == 14050 and g["status"] != "FINAL"
    assert g["batting"] == {"away": [], "home": []} and g["pitching"] == {"away": [], "home": []}
```

- [ ] **Step 3: 실패 확인** — Run: `pytest tests/test_mykbo_parse.py -q` — Expected: ImportError
- [ ] **Step 4: `teams.py`, `mykbo_parse.py` 구현** — BeautifulSoup `html.parser`. `date`는 `datetime_utc`를 `Asia/Seoul`로 변환한 날짜. 점수는 게임 라인의 `font-mono … font-bold` span 두 개(원정, 홈 순). 예정 경기는 점수 span 대신 시간·구장 텍스트.
- [ ] **Step 5: 통과 확인** — Run: `pytest tests/test_mykbo_parse.py -q` — Expected: 모두 PASS
- [ ] **Step 6: `tests/test_mykbo_client.py` 작성** — `requests.Session.get` monkeypatch (FakeResp: `.status_code`, `.text`, `.raise_for_status()`), `time.sleep` monkeypatch로 호출 인자 기록.

```python
def test_fetch_html_sleeps_sets_ua_and_caches(monkeypatch, tmp_path):
    calls, sleeps = [], []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    def fake_get(self, url, **kw): calls.append((url, self.headers.get("User-Agent"), kw.get("timeout"))); return FakeResp("<html>ok</html>")
    monkeypatch.setattr(requests.Session, "get", fake_get)
    assert fetch_html("/schedule/week_of/2026-08-11", cache_dir=tmp_path) == "<html>ok</html>"
    assert calls[0][0] == "https://mykbostats.com/schedule/week_of/2026-08-11" and calls[0][1] == USER_AGENT and calls[0][2] == 20 and sleeps == [5.0]
    assert fetch_html("/schedule/week_of/2026-08-11", cache_dir=tmp_path) == "<html>ok</html>" and len(calls) == 1   # 캐시 적중, 요청 없음

def test_fetch_html_retries_once_then_raises(monkeypatch, tmp_path):
    ...  # 항상 503 → HTTPError, 호출 횟수 == 2, 캐시 파일 없음
```

- [ ] **Step 7: 실패 확인 → `mykbo_client.py` 구현 → 통과 확인** — Run: `pytest tests/test_mykbo_client.py -q` — Expected: `2 passed`
- [ ] **Step 8: `tests/test_raw_store.py` 작성**

```python
def test_upsert_games_dedupes_and_sorts(tmp_data_dir, fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2026-10-27.html"))
    assert upsert_games(2026, rows) == 4
    changed = dict(next(r for r in rows if r["game_id"] == 14050), status="FINAL", away_score=2, home_score=4)
    assert upsert_games(2026, [changed]) == 1 and upsert_games(2026, [changed]) == 0
    loaded = load_games(2026)
    assert len(loaded) == 4 and [(g["date"], g["game_id"]) for g in loaded] == sorted((g["date"], g["game_id"]) for g in loaded)
    assert next(g for g in loaded if g["game_id"] == 14050)["status"] == "FINAL"

def test_append_boxscores_skips_existing(tmp_data_dir, fixture_html):
    g = parse_game(fixture_html("mykbo_game_14048_final.html"))
    assert append_boxscores(2026, {14048: g}) == 1 and append_boxscores(2026, {14048: g}) == 0
    assert load_boxscores(2026)[14048]["home"]["code"] == "SS"
```

- [ ] **Step 9: 실패 확인 → `raw_store.py` 구현 → 통과 확인** — jsonl `ensure_ascii=False`, gz `gzip.open(..., "at", encoding="utf-8")`. Run: `pytest tests/test_raw_store.py -q` — Expected: `2 passed`
- [ ] **Step 10: `tests/test_collect.py` 작성**

```python
def test_collect_range_fetches_boxscores_only_for_new_finals(monkeypatch, tmp_data_dir, fixture_html):
    fetched = []
    def fake_fetch(path, **kw):
        fetched.append(path)
        if path.startswith("/schedule/week_of/"): return fixture_html("mykbo_week_2026-10-27.html")
        return fixture_html("mykbo_game_14048_final.html")      # 어떤 경기 페이지든 이 fixture
    monkeypatch.setattr(collect, "fetch_html", fake_fetch)
    out = collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0)
    assert out["games"] == 4 and out["boxscores"] == 1                 # FINAL은 14052 하나
    assert [p for p in fetched if p.startswith("/games/")] == ["/games/14052-Kia-vs-Samsung-20261027"]
    fetched.clear()
    assert collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0)["boxscores"] == 0
    assert not [p for p in fetched if p.startswith("/games/")]
```

- [ ] **Step 11: 실패 확인 → `collect.py` 구현 → 통과 확인** — `collect_range`는 `parse_game` 결과에 `game_id`가 주간 행과 일치하는지 확인하고 다르면 예외. 주간 페이지는 `from_date`, `from_date+7`, … 로 요청하고 중복 행은 upsert가 흡수. Run: `pytest -q` — Expected: 모두 PASS
- [ ] **Step 12: Commit** — `git add -A src tests requirements.txt .gitignore .github && git commit -m "feat: MyKBOStats 수집기 (클라이언트, 파서, 원본 저장, CLI); 네이버 수집기 제거"`
- [ ] **Step 13: 2026 시즌 백필 (실제 사이트, 로컬)** — Run: `python -m kbo_predict.collect --from 2026-03-20 --to 2026-11-05` — 약 750요청 × 5초 ≈ 65분이므로 `run_in_background`로 실행하고 진행 로그를 확인. 중단되면 같은 명령으로 재개(캐시·skip 덕분에 빠름). 완료 후 Run: `python -c "from kbo_predict.raw_store import *; from collections import Counter; g=load_games(2026); c=Counter(x['date'] for x in g if x['status']=='FINAL'); days=sorted(d for d,n in c.items() if n>=4); print(len(g), sum(x['status']=='FINAL' for x in g), days[0], days[-1], len(load_boxscores(2026)))"` — Expected: FINAL 경기 수 ≥ 720+포스트시즌, 정규시즌 시작/종료일 출력, boxscores 수 == FINAL 수.
- [ ] **Step 14: `seasons.py`에 2026 값 기입** — Step 13 출력의 시작/종료일로 `REGULAR_SEASON[2026]` 채우고, `tests/test_seasons.py`에 `is_regular(2026, start) and is_regular(2026, end) and not is_regular(2026, end + 1일)` 테스트. Run: `pytest -q` — Expected: 모두 PASS
- [ ] **Step 15: Commit** — `git add src tests data/raw && git commit -m "feat: 2026 시즌 일정·박스스코어 데이터 + 정규시즌 범위"` (`boxscores.jsonl.gz`가 20MB를 넘으면 중단하고 보고)

---

### Task 3: 피처 (LeagueState)

**Files:**
- Create: `src/kbo_predict/features.py`
- Test: `tests/test_features.py`

**Interfaces:**
- Consumes: `raw_store.load_games` 행 형식(`parse_week` dict), `seasons.is_regular` (Task 2)
- Produces:
  - `features.FEATURE_NAMES = ["win_pct_diff", "last10_diff", "run_diff_diff"]` (홈 − 원정)
  - `features.FACTOR_LABELS = {"win_pct_diff": "팀 승률 차이", "last10_diff": "최근 10경기 흐름", "run_diff_diff": "경기당 득실차", "intercept": "홈 어드밴티지"}`
  - `class features.LeagueState` — `update(game: dict) -> None` (`status == "FINAL"`일 때만 반영; 점수 동일(무승부)은 승패 집계·last10에서 제외하되 득실에는 반영), `team_win_pct(code) -> float` (경기 0이면 0.5), `team_last10(code) -> float` (결과 0개면 0.5), `team_run_diff(code) -> float` ((득점−실점)/경기 수, 경기 0이면 0.0), `team_line(code) -> dict` — `{"win_pct", "last10", "run_diff", "games"}`
  - `features.game_features(game: dict, state: LeagueState) -> dict` — `FEATURE_NAMES` 키 + `home_line`, `away_line`(team_line)
  - `features.build_training_frame(games: list[dict], *, season: int) -> pandas.DataFrame` — 날짜순으로 상태를 누적하며 `is_regular(season, date)`이고 FINAL이며 무승부가 아닌 경기의 피처와 `y`(홈 승=1), `game_id`, `date` 열 생성. 정규시즌 밖(포스트시즌) 경기는 행을 만들지 않지만 상태 갱신에는 포함하지 않는다(정규시즌 끝 이후라 영향 없음).

- [ ] **Step 1: `tests/test_features.py` 작성** — 보조: `mk(date, gid, home="LG Twins", away="Hanwha Eagles", hs=None, as_=None, status="FINAL")`가 `parse_week` 형식 dict를 만든다 (코드는 `teams.code_for`).

```python
def test_state_defaults_when_empty():
    s = LeagueState()
    assert s.team_win_pct("LG") == 0.5 and s.team_last10("LG") == 0.5 and s.team_run_diff("LG") == 0.0

def test_state_updates_from_week_fixture(fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2026-08-11.html"))
    s = LeagueState()
    for r in rows: s.update(r)
    hh = [r for r in rows if r["status"] == "FINAL" and "HH" in (r["home_code"], r["away_code"])]
    wins = sum((r["home_score"] > r["away_score"]) == (r["home_code"] == "HH") for r in hh if r["home_score"] != r["away_score"])
    assert s.team_win_pct("HH") == pytest.approx(wins / len([r for r in hh if r["home_score"] != r["away_score"]]))
    assert s.team_line("HH")["games"] == len(hh)

def test_canceled_and_scheduled_not_counted():
    s = LeagueState()
    s.update(mk("2026-08-16", 1, hs=None, as_=None, status="CANCELED")); s.update(mk("2026-08-17", 2, status="SCHEDULED"))
    assert s.team_win_pct("LG") == 0.5 and s.team_line("LG")["games"] == 0

def test_draw_counts_runs_but_not_wins():
    s = LeagueState(); s.update(mk("2026-08-16", 1, hs=3, as_=3))
    assert s.team_win_pct("LG") == 0.5 and s.team_last10("LG") == 0.5 and s.team_line("LG")["games"] == 1 and s.team_run_diff("LG") == 0.0

def test_build_training_frame_has_no_leakage():
    games = [mk("2026-04-01", 1, hs=5, as_=2), mk("2026-04-02", 2, hs=4, as_=1), mk("2026-04-03", 3, hs=0, as_=1)]
    df_a = build_training_frame(games, season=2026)
    df_b = build_training_frame(games[:2] + [mk("2026-04-03", 3, hs=9, as_=1)], season=2026)   # d3 결과만 바꿈
    assert df_a.loc[df_a.game_id == 3, FEATURE_NAMES].values.tolist() == df_b.loc[df_b.game_id == 3, FEATURE_NAMES].values.tolist()
    assert df_a.loc[df_a.game_id == 1, FEATURE_NAMES].values.tolist() == [[0.0, 0.0, 0.0]]       # 첫 경기는 기본값
    assert df_a.loc[df_a.game_id == 3, "win_pct_diff"].item() == pytest.approx(1.0)
    assert df_a.loc[df_a.game_id == 3, "run_diff_diff"].item() == pytest.approx(6.0)             # LG +3, HH −3
    assert df_a.y.tolist() == [1, 1, 0]

def test_build_training_frame_excludes_draws_and_postseason():
    games = [mk("2026-04-01", 1, hs=2, as_=2), mk("2026-04-02", 2, hs=3, as_=1), mk("2026-10-20", 3, hs=1, as_=0)]   # 10-20은 포스트시즌
    df = build_training_frame(games, season=2026)
    assert df.game_id.tolist() == [2]

def test_same_day_games_do_not_leak_into_each_other():
    games = [mk("2026-04-01", 1, hs=5, as_=2), mk("2026-04-01", 2, hs=5, as_=2)]          # 더블헤더
    df = build_training_frame(games, season=2026)
    assert df[FEATURE_NAMES].values.tolist() == [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_features.py -q` — Expected: ImportError
- [ ] **Step 3: `features.py` 구현** — `LeagueState`는 팀별 `wins/losses/games/runs_for/runs_against/results(deque maxlen 10)` 딕셔너리. `build_training_frame`은 `sorted(games, key=(date, game_id))`로 순회하며 같은 날짜의 경기는 **모두 피처를 먼저 계산한 뒤** 상태를 갱신한다 (더블헤더 누수 방지). `test_build_training_frame_excludes_draws_and_postseason`은 `seasons.REGULAR_SEASON[2026]`이 10-20을 포함하지 않는 것에 의존 — Task 2에서 기입된 값 사용.
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
- Consumes: `train_win.load_bundle`, `features.game_features`, `LeagueState`, `FACTOR_LABELS`, `teams.TEAMS`, `seasons.is_regular`
- Produces:
  - `predict.predict_game(bundle, game: dict, state: LeagueState) -> dict` — `{"game_id", "date", "time" (time_kst, 예 "18:30"), "stadium", "round": "regular" | "postseason", "status", "home": {"code", "name" (한국어 표시명 `teams.TEAMS[...]["ko"]`), "starter": null, "win_pct_season", "last10", "run_diff"}, "away": {...}, "home_win_prob": float(소수 4자리), "factors": [{"name", "contribution_pp"}, ...]}`. 요인: 표준화 피처 z에 대해 `coef_i * z_i * p*(1-p) * 100`, 절편은 `intercept * p*(1-p) * 100` ("홈 어드밴티지"); 절대값 내림차순. `starter`는 v0.1에서 항상 `null` (경기 전 선발 소스 없음).
  - `publish.write_latest(path, *, date, games: list[dict], meta: dict) -> None` — `{"generated_at", "date", "mode": "live", "model_version", "commit_sha", "run_url", "games": [...]}`
  - `publish.upsert_history(path, predictions: list[dict], *, predicted_at: str) -> None` — CSV 열 `date,game_id,home,away,home_win_prob,model_version,predicted_at,status,winner,correct`. 같은 `game_id` 행이 있으면: 기존 `status == "RESULT"`면 건드리지 않음, 아니면 확률·predicted_at·status 갱신.
  - `publish.settle_history(path, games: list[dict]) -> int` — `winner`가 빈 행에 대해 games(`parse_week` 행)에서 `status == "FINAL"`이면 `winner`(HOME/AWAY/DRAW, 점수 비교)·`status="FINAL"`·`correct`(HOME이면 prob≥.5, AWAY면 prob<.5, DRAW면 빈칸) 채움; `status == "CANCELED"`면 `status="CANCELED"`. 반환은 갱신 행 수.
  - `publish.write_status(path, *, mode, next_game_date: str | None, games_today: int, meta: dict) -> None`

- [ ] **Step 1: `tests/test_predict.py` 작성** — Task 4의 합성 번들 fixture 재사용.

```python
def test_predict_game_shape(bundle, fixture_html):
    game = next(r for r in parse_week(fixture_html("mykbo_week_2026-10-27.html")) if r["game_id"] == 14050)
    out = predict_game(bundle, game, LeagueState())
    assert 0 < out["home_win_prob"] < 1 and out["time"] == "18:30" and out["home"]["code"] == "HT" and out["home"]["name"] == "KIA"
    assert out["round"] == "postseason" and out["home"]["starter"] is None
    assert {f["name"] for f in out["factors"]} == set(FACTOR_LABELS.values())
    assert out["factors"] == sorted(out["factors"], key=lambda f: -abs(f["contribution_pp"]))

def test_predict_game_empty_state_only_home_advantage(bundle, fixture_html):
    game = next(r for r in parse_week(fixture_html("mykbo_week_2026-10-27.html")) if r["game_id"] == 14050)
    out = predict_game(bundle, game, LeagueState())
    assert all(f["contribution_pp"] == 0.0 for f in out["factors"] if f["name"] != "홈 어드밴티지")
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
  - `run_pipeline.run(target: date, *, data_dir: Path, model_path: Path, meta: dict, fetch=True) -> dict` — 순서: ① `collect_range(target-7일, target+14일)` (fetch=False면 생략; 주간 페이지 3~4개 + 새 FINAL 경기 페이지) ② `settle_history` ③ 해당 시즌 games로 `LeagueState`를 `date < target`까지 누적 ④ target 날짜 경기(`status != "CANCELED"`) 예측 ⑤ 경기 있으면 `write_latest` + `upsert_history`, 없으면 latest 생략 ⑥ `write_status` (next_game_date = target 이후 첫 경기 날짜 또는 None). 반환 `{"games_today": n, "settled": n}`
  - CLI: `python scripts/run_pipeline.py [--date YYYY-MM-DD] [--no-fetch]` — 기본 날짜는 KST 오늘. meta는 환경변수 `GITHUB_SHA`, `RUN_URL`에서 읽고 없으면 `null`.

- [ ] **Step 1: `tests/test_pipeline.py` 작성** — fixture 일정을 `tmp_data_dir`의 games.jsonl에 넣고 `fetch=False`, 합성 번들 저장 후 실행.

```python
def test_run_writes_all_public_files_on_game_day(tmp_data_dir, bundle_path, fixture_html):
    upsert_games(2026, parse_week(fixture_html("mykbo_week_2026-10-27.html")))   # 10-27 FINAL 1, 10-29/30, 11-01 예정
    out = run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    assert out["games_today"] == 1
    latest = json.loads((tmp_data_dir / "public/latest.json").read_text(encoding="utf-8"))
    assert latest["date"] == "2026-10-29" and latest["games"][0]["home"]["code"] == "HT" and latest["mode"] == "live"
    assert (tmp_data_dir / "public/status.json").exists() and (tmp_data_dir / "public/history.csv").exists()

def test_run_on_empty_day_touches_only_status(tmp_data_dir, bundle_path, fixture_html):
    upsert_games(2026, parse_week(fixture_html("mykbo_week_2026-10-27.html")))
    run(date(2026, 10, 29), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)
    before = (tmp_data_dir / "public/latest.json").read_bytes()
    run(date(2026, 10, 28), data_dir=tmp_data_dir, model_path=bundle_path, meta=META, fetch=False)   # 10-28 경기 없음
    assert (tmp_data_dir / "public/latest.json").read_bytes() == before
    assert json.loads((tmp_data_dir / "public/status.json").read_text(encoding="utf-8"))["next_game_date"] == "2026-10-29"
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
