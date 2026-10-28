# 1단계: 2015~2025 백필 + 노트북 01 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2015~2025 정규시즌 경기·박스스코어를 MyKBOStats에서 백필해 커밋하고, 그 데이터를 친절하게 설명하는 노트북 01을 만든다.

**Architecture:** 0단계 파이프라인(`mykbo_client` → `mykbo_parse` → `raw_store` → `collect`)을 과거 시즌에도 돌 수 있게 보강한다(옛 구단명, 결측 None, 월별 박스스코어 파일, 경기 단위 실패 허용, 멈춘 LIVE 보정). 백필 자체는 컨트롤러가 로컬에서 시즌별로 실행해 커밋한다(요청 간 5초, 시즌당 약 1시간). 시즌 경계는 데이터로 검증해 `seasons.py` 상수로 적는다. 노트북 01은 `src/` 함수만 호출하고 커밋된 데이터만 읽는다(네트워크 없음).

**Tech Stack:** Python 3.12, requests, beautifulsoup4, pandas, matplotlib, nbformat/nbclient/nbconvert, pytest, GitHub Actions(`gh` CLI).

**Spec:** `docs/superpowers/specs/2026-10-27-kbo-predict-design.md` (4절 데이터, 6절 노트북 규칙, 12절 1단계, 14절 열린 위험). 이월 항목: `docs/superpowers/plans/2026-10-27-stage0-deferred.md` "1단계 전에" 절.

## Global Constraints

- 요청 간 `sleep 5초`(robots.txt Crawl-delay), UA `Mozilla/5.0 (compatible; kbo-predict/0.1; +https://github.com/kimminseo2323-prog/2610_KBO_predict)`, 실패 시 1회 재시도. 우회 코드 금지.
- 파싱 결과만 커밋, 원본 HTML은 `data/cache/html/`(gitignore)에만. 주간 페이지는 캐시를 쓰지 않는다(`use_cache=False`), 경기 페이지는 캐시 사용.
- 파서는 미인식 상태에서 **즉시 예외**(조용한 오분류 금지). 수집기는 경기 한 건의 실패로 전체를 멈추지 않는다(경기 단위로 기록하고 계속).
- 학습·서빙 범위는 **정규시즌만**(`seasons.is_regular`). 2015~2025는 모두 10구단 144경기 = 시즌당 **720경기**.
- 노트북: 로직은 `src/`에 한 번만, 노트북은 호출만 한다. 맨 위 마크다운 셀에 "하는 일 / 왜 / 짝 `.py`". 코드 셀마다 바로 위에 한국어 설명(무엇을·왜·결과 읽는 법). 야구 용어 첫 등장 시 한 줄 설명. 실행 결과 포함 상태로 커밋. 노트북 01은 네트워크 없이 실행 가능해야 한다.
- 의존성은 `requirements.txt`에 정확 버전(`==`)으로 고정.
- 모든 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Windows 콘솔 출력은 `python -X utf8` 또는 `PYTHONIOENCODING=utf-8`로 실행(cp949 오류 방지).
- 공개 파일 계약(`latest.json`, `history.csv`)의 기존 키·모양은 바꾸지 않는다. `status.json`에는 키 추가만 허용.

## Review Focus

1. 2015~2018 `Nexen Heroes`, 2015~2020 `SK Wyverns`가 각각 `WO`, `SK` 코드로 매핑되고, 박스스코어 짧은 이름 `Nexen`, `SK`도 같은 코드로 풀려야 한다 → Task 1 테스트.
2. 박스스코어 숫자 셀이 비었거나 `-`일 때 0이 아니라 `None`이어야 한다(선수 스탯 집계 오염 방지) → Task 1 테스트.
3. 월별 파일로 쪼갠 뒤에도 `load_boxscores(season)`은 시즌 전체를 한 dict로 돌려주고, 기존 2026 데이터가 하나도 빠지지 않아야 한다 → Task 2 테스트 + 마이그레이션 검증.
4. 경기 페이지 하나가 파싱 실패(챌린지 페이지, 미인식 상태)해도 나머지 경기 수집이 계속되고 실패 목록이 반환·기록되어야 한다 → Task 3 테스트.
5. 시즌 경계 안의 FINAL+LIVE 경기 수가 정확히 720이고, 경계 바로 다음 경기(포스트시즌)까지 2일 이상 공백이어야 한다 → Task 4 검증 스크립트 출력.

---

### Task 1: 옛 구단명 매핑 + 결측 셀 None + LIVE 페이지 상태 기호

**Files:**
- Modify: `src/kbo_predict/teams.py`
- Modify: `src/kbo_predict/mykbo_parse.py` (`_int`, `_table_rows`, `_game_status`)
- Create: `tests/fixtures/mykbo_week_2015-06-02.html` (복사 원본: `data/cache/html/schedule_week_of_2015-06-02.html`)
- Create: `tests/fixtures/mykbo_game_1189_final.html` (복사 원본: `data/cache/html/games_1189-Kia-vs-Doosan-20150602.html`)
- Test: `tests/test_mykbo_parse.py`, `tests/test_teams.py` (신규)

**Interfaces:**
- Consumes: 없음
- Produces: `teams.TEAMS`에 `"Nexen Heroes": {"code": "WO", "ko": "넥센"}`, `"SK Wyverns": {"code": "SK", "ko": "SK"}` 추가. `_SHORT`는 기존 규칙(풀네임 첫 단어)으로 자동 파생되어 `"Nexen" → "WO"`, `"SK" → "SK"`. `mykbo_parse._int(text) -> int | None`. 박스스코어 행의 숫자 필드는 `int | None`.

- [ ] **Step 1: fixture 복사**

`data/cache/html/`의 두 파일을 위 경로로 복사한다(내용 수정 없음).

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_teams.py`:
```python
from kbo_predict.teams import TEAMS, code_for, short_to_code

def test_historical_team_names_map_to_current_codes():
    assert code_for("Nexen Heroes") == "WO" and code_for("Kiwoom Heroes") == "WO"
    assert code_for("SK Wyverns") == "SK" and code_for("SSG Landers") == "SK"
    assert short_to_code("Nexen") == "WO" and short_to_code("SK") == "SK" and short_to_code("SSG") == "SK"

def test_ten_distinct_codes():
    assert len({v["code"] for v in TEAMS.values()}) == 10
```

`tests/test_mykbo_parse.py`에 추가:
```python
def test_week_2015_uses_historical_team_names(fixture_html):
    rows = parse_week(fixture_html("mykbo_week_2015-06-02.html"))
    assert len(rows) == 30
    assert {r["status"] for r in rows} == {"FINAL", "CANCELED"}
    assert sum(r["status"] == "FINAL" for r in rows) == 29
    codes = {r["away_code"] for r in rows} | {r["home_code"] for r in rows}
    assert {"WO", "SK"} <= codes and len(codes) == 10

def test_game_2015_parses_boxscore(fixture_html):
    g = parse_game(fixture_html("mykbo_game_1189_final.html"))
    assert g["game_id"] == 1189 and g["date"] == "2015-06-02" and g["status"] == "FINAL"
    assert (g["away"]["code"], g["away"]["score"]) == ("HT", 9) and (g["home"]["code"], g["home"]["score"]) == ("OB", 1)
    assert len(g["batting"]["away"]) == 16 and len(g["pitching"]["away"]) == 3
    assert g["pitching"]["away"][0]["ip_outs"] == 21

def test_int_non_numeric_cell_is_none():
    from kbo_predict.mykbo_parse import _int
    assert _int(" 12 ") == 12 and _int("-3") == -3
    assert _int("") is None and _int("-") is None and _int("n/a") is None

def test_game_status_ignores_leading_symbols():
    from bs4 import BeautifulSoup
    from kbo_predict.mykbo_parse import _game_status
    soup = BeautifulSoup('<p class="mt-sm">▼ Bottom 9th · 0 out</p>', "html.parser")
    assert _game_status(soup) == "LIVE"
```

- [ ] **Step 3: 실패 확인**

Run: `python -X utf8 -m pytest tests/test_teams.py tests/test_mykbo_parse.py -q`
Expected: FAIL — `KeyError: 'Nexen Heroes'`, `_int("")` returns 0, `_game_status` raises on `▼`.

- [ ] **Step 4: 구현**

- `teams.py`: `TEAMS`에 두 항목 추가. `_SHORT` 파생 규칙은 그대로(첫 단어).
- `mykbo_parse._int(text: str) -> int | None`: 숫자(선행 `-` 허용)가 아니면 `None`.
- `_game_status`: 비교 전에 `t = t.lstrip("▲▼△▽ ").strip()` 적용(기호 제거 뒤 `startswith` 매칭).
- `parse_week`의 점수 파싱(`isdigit` 필터)은 그대로 둔다.

- [ ] **Step 5: 전체 테스트 통과 확인**

Run: `python -X utf8 -m pytest -q`
Expected: 모두 PASS(기존 51 + 신규 6).

- [ ] **Step 6: Commit**

```bash
git add src/kbo_predict/teams.py src/kbo_predict/mykbo_parse.py tests/test_teams.py tests/test_mykbo_parse.py tests/fixtures/mykbo_week_2015-06-02.html tests/fixtures/mykbo_game_1189_final.html
git commit -m "feat: 옛 구단명(Nexen/SK Wyverns) 매핑, 결측 셀 None, LIVE 페이지 상태 기호 처리"
```

---

### Task 2: 박스스코어 월별 파일 분할 + 시즌 목록 헬퍼

**Files:**
- Modify: `src/kbo_predict/raw_store.py`
- Modify: `data/raw/2026/` (단일 `boxscores.jsonl.gz` → `boxscores/2026-03.jsonl.gz` … 월별; 기존 파일 삭제)
- Test: `tests/test_raw_store.py`

**Interfaces:**
- Consumes: Task 1 파서 출력(`box["date"]` = `YYYY-MM-DD`).
- Produces: `raw_store.boxscores_dir(season) -> Path` (= `data/raw/{season}/boxscores/`), `raw_store.boxscores_month_path(season, yyyymm: str) -> Path` (= `boxscores/{YYYY-MM}.jsonl.gz`), `raw_store.load_boxscores(season) -> dict[int, dict]` (월별 파일을 파일명 순으로 모두 읽어 합침), `raw_store.append_boxscores(season, boxscores) -> int` (시그니처 유지, `box["date"][:7]`로 월 파일에 append), `raw_store.available_seasons() -> list[int]` (`data/raw/` 아래 `games.jsonl`이 있는 시즌을 오름차순). `boxscores_path(season)`는 **삭제**(호출처 없음을 `grep`으로 확인).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_raw_store.py`에 추가/수정:
```python
def test_append_boxscores_splits_files_by_month(tmp_data_dir, fixture_html):
    from kbo_predict.raw_store import boxscores_dir
    g = parse_game(fixture_html("mykbo_game_14048_final.html"))      # 2026-10-26
    g_old = parse_game(fixture_html("mykbo_game_1189_final.html"))   # 2015-06-02
    assert append_boxscores(2026, {14048: g}) == 1
    assert append_boxscores(2015, {1189: g_old}) == 1
    assert sorted(p.name for p in boxscores_dir(2026).iterdir()) == ["2026-10.jsonl.gz"]
    assert sorted(p.name for p in boxscores_dir(2015).iterdir()) == ["2015-06.jsonl.gz"]
    assert load_boxscores(2026)[14048]["home"]["code"] == "SS"
    assert load_boxscores(2015)[1189]["away"]["code"] == "HT"

def test_load_boxscores_merges_all_months(tmp_data_dir, fixture_html):
    g = parse_game(fixture_html("mykbo_game_14048_final.html"))
    g2 = dict(g, date="2026-09-01")
    assert append_boxscores(2026, {14048: g, 99999: g2}) == 2
    assert set(load_boxscores(2026)) == {14048, 99999}
    assert append_boxscores(2026, {14048: g}) == 0

def test_available_seasons_lists_dirs_with_games(tmp_data_dir, fixture_html):
    from kbo_predict.raw_store import available_seasons
    assert available_seasons() == []
    upsert_games(2026, parse_week(fixture_html("mykbo_week_2026-10-27.html")))
    upsert_games(2015, parse_week(fixture_html("mykbo_week_2015-06-02.html")))
    assert available_seasons() == [2015, 2026]
```

- [ ] **Step 2: 실패 확인**

Run: `python -X utf8 -m pytest tests/test_raw_store.py -q`
Expected: FAIL — `boxscores_dir`/`available_seasons` ImportError.

- [ ] **Step 3: 구현**

`raw_store.py`에 위 Interfaces대로 구현. `append_boxscores`는 월별로 묶어 각 파일에 `at` 모드로 append. `load_boxscores`는 `boxscores_dir(season).glob("*.jsonl.gz")`를 정렬해 순서대로 읽는다(디렉터리 없으면 `{}`).

- [ ] **Step 4: 기존 2026 데이터 마이그레이션**

일회성 스니펫(커밋하지 않음)으로 `data/raw/2026/boxscores.jsonl.gz`를 읽어 월별 파일로 다시 쓰고 기존 파일을 삭제한다. 검증:
```bash
python -X utf8 -c "from kbo_predict.raw_store import load_boxscores; b=load_boxscores(2026); print(len(b))"
```
Expected: `749`. `ls data/raw/2026/boxscores/` → `2026-03.jsonl.gz` … `2026-10.jsonl.gz`.

- [ ] **Step 5: 전체 테스트 통과 확인**

Run: `python -X utf8 -m pytest -q`
Expected: 모두 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/kbo_predict/raw_store.py tests/test_raw_store.py data/raw/2026
git commit -m "feat: 박스스코어를 월별 파일로 분할 저장, available_seasons 추가 (2026 마이그레이션)"
```

---

### Task 3: 수집기 보강 — 시즌 CLI, 경기 단위 실패 허용, 멈춘 LIVE 보정, status 기록

**Files:**
- Modify: `src/kbo_predict/collect.py`
- Modify: `src/kbo_predict/publish.py` (`write_status`)
- Modify: `scripts/run_pipeline.py`
- Test: `tests/test_collect.py`, `tests/test_publish.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 1 `_game_status`(LIVE 페이지 인식), Task 2 `append_boxscores`.
- Produces:
  - `collect.collect_range(from_date, to_date, *, season=None, sleep_s=SLEEP_S, today: date | None = None) -> dict` 반환 키 `{"weeks", "games", "boxscores", "errors": list[dict]}`; `errors` 원소는 `{"game_id": int, "path": str, "error": str}`.
  - `collect.season_range(season: int) -> tuple[date, date]` = `(date(season, 3, 1), date(season, 11, 30))`.
  - CLI: `python -m kbo_predict.collect --season 2015` (= `collect_range(*season_range(2015), season=2015)`), 기존 `--from/--to`도 유지(둘 중 하나 필수).
  - `publish.write_status(path, *, mode, next_game_date, games_today, meta, collect_errors: list[str] | None = None)` → status.json에 `"collect_errors": [...]` 키(없으면 `[]`).
  - `run_pipeline.run()`은 `collect_range` 반환의 `errors`를 `f"{e['path']}: {e['error']}"` 문자열로, 수집 전체 실패(`RequestException`) 시 `repr(e)` 한 줄로 `collect_errors`에 넣어 `write_status`에 전달.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_collect.py`에 추가:
```python
def test_collect_continues_after_one_bad_game_page(monkeypatch, tmp_data_dir, fixture_html):
    def fake_fetch(path, **kw):
        if path.startswith("/schedule/week_of/"):
            return fixture_html("mykbo_week_2015-06-02.html")
        game_id = path.split("/")[2].split("-")[0]
        if game_id == "1189":
            return "<html><body>Checking your browser</body></html>"   # 미인식 페이지
        return fixture_html("mykbo_game_1189_final.html").replace("/games/1189-", f"/games/{game_id}-")
    monkeypatch.setattr(collect, "fetch_html", fake_fetch)
    out = collect.collect_range(date(2015, 6, 2), date(2015, 6, 8), sleep_s=0)
    assert out["games"] == 30 and out["boxscores"] == 28
    assert [e["game_id"] for e in out["errors"]] == [1189]
    assert "unrecognised" in out["errors"][0]["error"] and out["errors"][0]["path"].startswith("/games/1189-")

def test_stale_live_row_is_finalised_from_game_page(monkeypatch, tmp_data_dir, fixture_html):
    week = fixture_html("mykbo_week_2026-10-27.html")
    # 14052(FINAL) 행을 LIVE처럼 보이게: 'Final' -> 'LIVE'
    week_live = week.replace("Final", "LIVE", 1)
    def fake_fetch(path, **kw):
        if path.startswith("/schedule/week_of/"):
            return week_live
        game_id = path.split("/")[2].split("-")[0]
        return fixture_html("mykbo_game_14048_final.html").replace("/games/14048-", f"/games/{game_id}-")
    monkeypatch.setattr(collect, "fetch_html", fake_fetch)
    out = collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0, today=date(2026, 11, 5))
    g = next(x for x in raw_store.load_games(2026) if x["game_id"] == 14052)
    assert g["status"] == "FINAL" and (g["away_score"], g["home_score"]) == (5, 1) and out["boxscores"] == 1

def test_recent_live_row_is_left_alone(monkeypatch, tmp_data_dir, fixture_html):
    # today가 경기 다음날이면 LIVE 그대로 두고 경기 페이지도 요청하지 않는다
    week_live = fixture_html("mykbo_week_2026-10-27.html").replace("Final", "LIVE", 1)
    fetched = []
    def fake_fetch(path, **kw):
        fetched.append(path)
        return week_live
    monkeypatch.setattr(collect, "fetch_html", fake_fetch)
    out = collect.collect_range(date(2026, 10, 27), date(2026, 11, 1), sleep_s=0, today=date(2026, 10, 28))
    g = next(x for x in raw_store.load_games(2026) if x["game_id"] == 14052)
    assert g["status"] == "LIVE" and out["boxscores"] == 0 and out["errors"] == []
    assert not [p for p in fetched if p.startswith("/games/")]

def test_season_cli_covers_march_to_november(monkeypatch):
    called = {}
    monkeypatch.setattr(collect, "collect_range", lambda f, t, **kw: called.update(f=f, t=t, **kw) or {})
    collect.main(["--season", "2015", "--sleep", "0"])
    assert (called["f"], called["t"], called["season"]) == (date(2015, 3, 1), date(2015, 11, 30), 2015)
```
`tests/test_publish.py`: `write_status(..., collect_errors=["/games/1: boom"])` → JSON에 `collect_errors` 리스트; 생략 시 `[]`.
`tests/test_pipeline.py`: `collect_range`를 `{"weeks":1,"games":0,"boxscores":0,"errors":[{"game_id":1,"path":"/games/1","error":"boom"}]}` 반환으로 monkeypatch → `status.json["collect_errors"] == ["/games/1: boom"]`. 기존 "collect 실패 시 저장 데이터로 계속" 테스트에 `collect_errors` 길이 1 단언 추가.

- [ ] **Step 2: 실패 확인**

Run: `python -X utf8 -m pytest tests/test_collect.py tests/test_publish.py tests/test_pipeline.py -q`
Expected: FAIL — `today` 인자 없음, `errors` 키 없음, `collect_errors` 없음.

- [ ] **Step 3: 구현**

- `collect_range`: `today = today or datetime.now(KST).date()`. 주간 행이 `LIVE`이고 `date.fromisoformat(r["date"]) <= today - timedelta(days=2)`이면 경기 페이지를 가져와 `parse_game` 결과가 `FINAL`이고 양 팀 점수가 모두 있으면 행의 `status="FINAL"`, `away_score/home_score`를 페이지 점수로 바꾼 뒤 저장·박스스코어 추가. 페이지가 FINAL이 아니면 행을 그대로 둔다(결과를 지어내지 않는다).
- `mykbo_parse.parse_game`: `og:url` meta가 없으면 `ValueError("unrecognised game page: no og:url")`를 던진다(챌린지·인터스티셜 페이지가 `TypeError`로 새지 않게).
- 경기 페이지 처리(`fetch_html` + `parse_game` + game_id 일치 검사)를 `try/except (ValueError, KeyError, requests.RequestException)`로 감싸 `errors`에 `{"game_id", "path", "error": f"{type(e).__name__}: {e}"}`를 기록하고 `print(..., file=sys.stderr)` 후 계속. 주간 페이지 실패는 그대로 예외(기존 동작).
- `main`: `--season` 추가, `--from/--to`와 상호 배타(`argparse` mutually exclusive group, required).
- `publish.write_status`, `run_pipeline.run`: Interfaces대로.

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `python -X utf8 -m pytest -q`
Expected: 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/kbo_predict/collect.py src/kbo_predict/publish.py scripts/run_pipeline.py tests/test_collect.py tests/test_publish.py tests/test_pipeline.py
git commit -m "feat: 시즌 단위 수집 CLI, 경기 단위 실패 허용, 멈춘 LIVE 보정, status.json collect_errors"
```

---

### (컨트롤러 실행) 백필: 2015~2025

Task 3 리뷰 통과 후 컨트롤러가 로컬에서 순차 실행한다(서브에이전트 아님). 시즌마다:

```bash
python -X utf8 -m kbo_predict.collect --season 2015 2> logs/backfill_2015.log
git add data/raw/2015 && git commit -m "data: 2015 시즌 백필 (MyKBOStats)"
```

완료 기준: 시즌별 `games.jsonl` 존재, `errors`가 비어 있거나 로그에 사유가 남아 있음. 오류가 있는 경기는 재실행(`--season` 재실행은 캐시·중복 제거로 빠르다).

---

### Task 4: 시즌 경계 검증 스크립트 + `seasons.py` 2015~2025 + 미등록 시즌 폴백

**Files:**
- Create: `scripts/season_bounds.py`
- Modify: `src/kbo_predict/seasons.py`
- Test: `tests/test_seasons.py`, `tests/test_season_bounds.py` (신규)

**Interfaces:**
- Consumes: 백필된 `data/raw/{season}/games.jsonl`, `raw_store.load_games`.
- Produces:
  - `season_bounds.find_end(games: list[dict], opening: date, total: int = 720) -> dict` → `{"end": date, "count": int, "next_game": date | None, "gap_days": int | None, "per_day": dict[str, int]}`. `opening` 이후 `status in ("FINAL","LIVE")` 행을 `(date, game_id)` 순으로 세어 `total`번째 경기의 날짜가 `end`(행이 `total`개 미만이면 마지막 행의 날짜). `count`는 opening 이후 FINAL/LIVE 행 **전체** 수(포스트시즌 포함 — 실제 시즌이면 720 + 포스트시즌 경기 수가 나와야 정상). `next_game`은 `end`보다 뒤인 첫 경기 날짜, `gap_days = (next_game - end).days`. `per_day`는 `end` 전후 5일의 날짜별 경기 수(`YYYY-MM-DD` → int).
  - CLI: `python -X utf8 scripts/season_bounds.py --season 2015 --opening 2015-03-28` → 위 dict를 보기 좋게 출력. `count < total`이면 경고.
  - `seasons.REGULAR_SEASON`에 2015~2025 항목. `seasons.is_regular(season, d)`는 미등록 시즌이면 `warnings.warn(f"season {season} not in REGULAR_SEASON; using fallback 03-01..10-31")` 후 `date(season,3,1) <= d <= date(season,10,31)`.

개막일(컨트롤러 결정, 스크립트 출력으로 검증): 2015-03-28, 2016-04-01, 2017-03-31, 2018-03-24, 2019-03-23, 2020-05-05, 2021-04-03, 2022-04-02, 2023-04-01, 2024-03-23, 2025-03-22.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_season_bounds.py`:
```python
from datetime import date
from scripts.season_bounds import find_end

def _g(gid, d, status="FINAL"):
    return {"game_id": gid, "date": d, "status": status}

def test_find_end_counts_final_and_live_from_opening():
    games = [_g(1, "2020-03-01"), *(_g(10 + i, f"2020-05-{5 + i // 2:02d}") for i in range(6)),
             _g(99, "2020-05-08", "LIVE"), _g(100, "2020-05-12")]
    out = find_end(games, date(2020, 5, 5), total=7)
    assert out["end"] == date(2020, 5, 8) and out["count"] == 8
    assert out["next_game"] == date(2020, 5, 12) and out["gap_days"] == 4

def test_find_end_short_season_reports_last_date():
    games = [_g(1, "2020-05-05"), _g(2, "2020-05-06")]
    out = find_end(games, date(2020, 5, 5), total=720)
    assert out["count"] == 2 and out["end"] == date(2020, 5, 6) and out["next_game"] is None
```
`tests/test_seasons.py`에 추가:
```python
def test_regular_season_covers_2015_to_2026():
    assert set(REGULAR_SEASON) == set(range(2015, 2027))
    for s, (start, end) in REGULAR_SEASON.items():
        assert start.year == s == end.year and start < end

def test_unknown_season_falls_back_with_warning():
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert is_regular(2027, date(2027, 5, 1)) and not is_regular(2027, date(2027, 11, 1))
    assert w and "fallback" in str(w[0].message)
```

- [ ] **Step 2: 실패 확인**

Run: `python -X utf8 -m pytest tests/test_season_bounds.py tests/test_seasons.py -q`
Expected: FAIL — 모듈 없음, 2015 KeyError.

- [ ] **Step 3: 구현 + 11개 시즌 실행**

스크립트 구현 후 시즌마다 CLI를 실행해 출력(`end`, `count`, `gap_days`, `per_day`)을 보고서에 그대로 붙인다. `gap_days >= 2`이고 `per_day`에서 `end` 직후가 비어 있으면 `(opening, end)`를 `REGULAR_SEASON`에 적는다. `count < 720`(포스트시즌이 아예 없을 만큼 적음)이거나 `gap_days < 2`이면 `per_day`를 보고 하루 1경기(포스트시즌 패턴)가 시작되기 직전 날짜를 `end`로 잡되, 근거를 보고서에 남긴다. 어느 시즌이든 판단이 서지 않으면 DONE_WITH_CONCERNS로 보고한다(추측으로 적지 않는다). 2026 항목(`2026-03-28 ~ 2026-10-12`)은 바꾸지 않는다.

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `python -X utf8 -m pytest -q`
Expected: 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/season_bounds.py src/kbo_predict/seasons.py tests/test_seasons.py tests/test_season_bounds.py
git commit -m "feat: 시즌 경계 검증 스크립트, 2015~2025 정규시즌 범위, 미등록 시즌 폴백"
```

---

### Task 5: 수집 실패 시 GitHub 이슈 자동 생성 (daily.yml)

**Files:**
- Create: `scripts/collect_errors.py`
- Modify: `.github/workflows/daily.yml`
- Test: `tests/test_collect_errors.py` (신규)

**Interfaces:**
- Consumes: Task 3 `status.json["collect_errors"]`.
- Produces: `collect_errors.summarize(status_path: Path) -> str` — 오류가 없으면 `""`, 있으면 이슈 본문(마크다운: 날짜, 오류 줄 목록, `run_url`). CLI `python scripts/collect_errors.py data/public/status.json`은 본문을 stdout에 출력(없으면 빈 출력). 워크플로:
  - `permissions: { contents: write, issues: write }`
  - run 단계 뒤 `collect-failure issue` 단계: `if: always()`; `BODY=$(python scripts/collect_errors.py data/public/status.json)`; 파이프라인 단계가 실패(`steps.run.outcome == 'failure'`)했으면 본문을 `"파이프라인 실패 — 로그: $RUN_URL"`로. 본문이 비어 있지 않으면 `gh issue list --label collect-failure --state open --json number --jq '.[0].number'`로 열린 이슈를 찾아 있으면 `gh issue comment`, 없으면 `gh issue create --title "수집 실패 $(TZ=Asia/Seoul date +%F)" --label collect-failure --body "$BODY"`. 라벨은 `gh label create collect-failure --color d73a4a --description "MyKBOStats 수집 실패" --force`로 먼저 보장. `env: GH_TOKEN: ${{ github.token }}`.
  - run 단계에 `id: run`과 `continue-on-error: false` 유지. 이슈 단계는 커밋 단계 **앞**이 아니라 **뒤**에 둔다(커밋은 기존대로).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import json
from scripts.collect_errors import summarize

def test_summarize_empty_when_no_errors(tmp_path):
    p = tmp_path / "status.json"; p.write_text(json.dumps({"collect_errors": [], "generated_at": "x"}), encoding="utf-8")
    assert summarize(p) == ""

def test_summarize_lists_errors_and_run_url(tmp_path):
    p = tmp_path / "status.json"
    p.write_text(json.dumps({"collect_errors": ["/games/1: boom", "/games/2: bad"], "generated_at": "2026-10-29T09:07:00+09:00", "run_url": "https://x/run/1"}), encoding="utf-8")
    body = summarize(p)
    assert "/games/1: boom" in body and "/games/2: bad" in body and "https://x/run/1" in body and "2026-10-29" in body

def test_summarize_missing_file_is_empty(tmp_path):
    assert summarize(tmp_path / "nope.json") == ""
```

- [ ] **Step 2: 실패 확인** — Run: `python -X utf8 -m pytest tests/test_collect_errors.py -q` → ImportError.

- [ ] **Step 3: 구현** — 스크립트와 워크플로를 Interfaces대로. YAML은 `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/daily.yml'))"`로 문법 확인(`pyyaml`이 없으면 `pip install pyyaml` 후 실행하되 requirements에는 넣지 않는다).

- [ ] **Step 4: 전체 테스트 통과 확인** — `python -X utf8 -m pytest -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/collect_errors.py .github/workflows/daily.yml tests/test_collect_errors.py
git commit -m "feat: 수집 실패 시 GitHub 이슈 자동 생성/코멘트"
```

---

### Task 6: 노트북 01 — 데이터 수집과 살펴보기

**Files:**
- Create: `notebooks/01_데이터_수집과_살펴보기.ipynb` (실행 결과 포함)
- Create: `tests/test_notebooks.py`
- Modify: `requirements.txt` (`matplotlib==3.10.0`, `nbformat==5.10.4`, `nbclient==0.10.2`, `nbconvert==7.16.6`, `ipykernel==6.29.5` 추가)

**Interfaces:**
- Consumes: `raw_store.available_seasons/load_games/load_boxscores`, `seasons.REGULAR_SEASON`, `mykbo_parse.parse_week/parse_game/parse_innings`, `tests/fixtures/*.html`, `collect.season_range`.
- Produces: 노트북 파일. 노트북은 `notebooks/`를 cwd로 실행하며 첫 코드 셀에서 `ROOT = Path.cwd().parent`, `sys.path.insert(0, str(ROOT / "src"))`, `os.environ.setdefault("KBO_DATA_DIR", str(ROOT / "data"))`를 설정한다.

노트북 구성(마크다운 → 코드 순, 각 코드 셀 바로 위에 한국어 설명. 야구 용어는 첫 등장 시 한 줄 설명. 그래프는 matplotlib, 한글 폰트 `plt.rcParams["font.family"] = ["Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans"]`, `axes.unicode_minus=False`):

1. 제목 + "이 노트북이 하는 일 / 왜 필요한지 / 짝이 되는 `.py`(`collect.py`, `mykbo_parse.py`, `raw_store.py`)" + 읽는 순서 안내.
2. 데이터 출처 이야기: 공개 KBO API가 없다는 점, 네이버는 봇을 막고 우회는 하지 않기로 한 점, MyKBOStats와 robots.txt 5초 규칙, 원본 HTML은 커밋하지 않는 이유(4~5문장).
3. 주간 일정 페이지 한 장 파싱: `tests/fixtures/mykbo_week_2026-10-27.html` → `parse_week` → `pd.DataFrame` display. 컬럼 뜻 표(game_id, date, home/away, *_code, status, time_kst, stadium).
4. 경기 페이지 한 장 파싱: `mykbo_game_14048_final.html` → `parse_game` → 타자/투수 표 display. `parse_innings("4 ⅓") == 13` 설명(이닝을 아웃 수로 저장하는 이유), 결측 셀은 `None`.
5. (실행하지 않는 예시) `DO_FETCH = False` 가드 안에서 `collect_range(*season_range(2015), season=2015)` 호출 모양을 보여주고, 시즌당 약 1시간이 걸리는 이유(요청 수 × 5초)를 설명.
6. 전체 시즌 불러오기: `available_seasons()` 순회 → 하나의 DataFrame. 시즌별 행 수·상태(FINAL/CANCELED/LIVE/SCHEDULED) 교차표 display.
7. 정규시즌 범위: `REGULAR_SEASON` 표 + 시즌별 정규시즌 FINAL 경기 수(모두 720이어야 함을 설명; 2026은 718 + LIVE 2) display.
8. 살펴보기 그래프 3개: 시즌별 홈팀 승률(무승부 제외) 막대, 시즌별 무승부 수 막대, 경기당 총득점 분포 히스토그램(2015~2026 합산). 각 그래프 아래 해석 한 줄.
9. 데이터 품질 메모: LIVE로 멈춘 경기 목록(`status == "LIVE"` 전체 시즌), 취소 경기 월별 수, 결측 처리 규칙(점수 None, 숫자 셀 None), 재편성 시 새 game_id를 받는다는 관찰.
10. 요약 + 다음 노트북(02 피처 만들기) 예고.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_notebooks.py`:
```python
from pathlib import Path
import nbformat
from nbclient import NotebookClient

NB = Path(__file__).parent.parent / "notebooks" / "01_데이터_수집과_살펴보기.ipynb"

def test_notebook_01_executes_without_errors():
    nb = nbformat.read(NB, as_version=4)
    NotebookClient(nb, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(NB.parent)}}).execute()
    assert all(o.get("output_type") != "error" for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", []))

def test_notebook_01_has_intro_and_explanations():
    nb = nbformat.read(NB, as_version=4)
    assert nb.cells[0].cell_type == "markdown" and "collect.py" in nb.cells[0].source
    for i, c in enumerate(nb.cells):
        if c.cell_type == "code":
            assert nb.cells[i - 1].cell_type == "markdown", f"code cell {i} has no explanation above"
    assert all(c.get("outputs") for c in nb.cells if c.cell_type == "code"), "committed notebook must contain outputs"
```
(출력이 없는 코드 셀이 생기면 `print`로라도 결과를 남긴다.)

- [ ] **Step 2: 실패 확인** — Run: `python -X utf8 -m pytest tests/test_notebooks.py -q` → 파일 없음.

- [ ] **Step 3: 노트북 작성**

`nbformat`으로 셀을 만드는 일회성 빌드 스크립트를 스크래치 디렉터리에 두고(커밋하지 않음) `.ipynb`를 생성한 뒤, `python -X utf8 -m jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=300 "notebooks/01_데이터_수집과_살펴보기.ipynb"`로 실행 결과를 채운다(cwd는 `notebooks/`가 되도록 `--ExecutePreprocessor.cwd` 또는 `cd`). 생성된 노트북은 GitHub에서 그대로 읽히도록 출력 포함 상태로 둔다.

- [ ] **Step 4: 테스트 통과 확인** — `python -X utf8 -m pytest tests/test_notebooks.py -q` → PASS. 전체 `python -X utf8 -m pytest -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add notebooks/01_데이터_수집과_살펴보기.ipynb tests/test_notebooks.py requirements.txt
git commit -m "docs: 노트북 01 데이터 수집과 살펴보기 (실행 결과 포함)"
```

---

### Task 7: 문서 갱신 (README, 스펙, 이월 항목)

**Files:**
- Modify: `README.md` (데이터 절: 2015~2026 범위, 시즌별 경기 수 표, `data/raw/{season}/boxscores/{YYYY-MM}.jsonl.gz` 구조, 노트북 목차 절 추가, 아키텍처 그림에 노트북 줄)
- Modify: `docs/superpowers/specs/2026-10-27-kbo-predict-design.md` (4.2 저장 방식 월별로, 12절 "1. 데이터" 완료 표기 + 날짜, 13절 LIVE 멈춤 보정 규칙 기록)
- Modify: `docs/superpowers/plans/2026-10-27-stage0-deferred.md` ("1단계 전에" 항목 중 처리된 것을 ✅로 표시하고 처리 커밋 언급)

- [ ] **Step 1: 시즌별 경기 수 표 생성**

```bash
python -X utf8 -c "from kbo_predict import raw_store, seasons; from datetime import date
for s in raw_store.available_seasons():
    gs=raw_store.load_games(s); reg=[g for g in gs if g['status']=='FINAL' and seasons.is_regular(s, date.fromisoformat(g['date']))]
    print(s, len(gs), len(reg), sum(g['home_score']==g['away_score'] for g in reg), len(raw_store.load_boxscores(s)))"
```
출력(시즌, 전체 행, 정규시즌 FINAL, 무승부, 박스스코어 수)을 README 표로 옮긴다.

- [ ] **Step 2: 문서 수정** — 위 Files대로. README의 "v0.1 모델" 절은 바꾸지 않는다(모델은 2단계에서 재학습).

- [ ] **Step 3: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-27-kbo-predict-design.md docs/superpowers/plans/2026-10-27-stage0-deferred.md
git commit -m "docs: 1단계 완료 — README 데이터 절·노트북 목차, 스펙·이월 항목 갱신"
```
