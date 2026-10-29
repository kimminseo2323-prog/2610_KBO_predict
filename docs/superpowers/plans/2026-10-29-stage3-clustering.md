# 3단계: 선수 유형 클러스터링 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2015~2026 박스스코어를 선수·시즌 단위로 집계해 타자·투수 유형을 K-means로 나누고(이름은 사람이 붙임), 유사 선수·2D 지도·소속 확률을 `players.json`, 팀별 요약을 `teams.json`으로 내보내며, "직전 시즌 유형"으로 만든 상성 피처를 승패 모델에 넣기 전·후를 `model_report.json`에 기록한다. 노트북 04가 같은 함수를 호출해 같은 라벨을 낸다.

**Architecture:** 경기 페이지 하단 기록표(`data-game-section="records"`)에서 2루타·3루타·도루를 읽어 박스스코어 타자 행에 보태고(로컬 HTML 캐시 9,860장 재파싱, 기존 칸은 바이트 단위 불변 검증), 같은 표의 한글 제목에서 선수 한글 이름을 뽑는다. `player_stats`가 정규시즌 FINAL 박스스코어를 선수·시즌으로 합산하고, `cluster`가 비율 지표 → 표준화 → K-means(K=4~7, 실루엣 + 연도 간 유지율) → GMM 소속 확률 → PCA 2D → 코사인 유사 선수를 만든다. 중심은 2015~2025로만 맞추고 2026은 배정만 한다(2026은 승패 모델 홀드아웃). `features.LeagueState`가 직전 시즌 유형으로 타선 구성·상대 선발 유형 피처를 만들고 `train_win.train_report`가 전·후 비교를 보고서에 넣는다. 라이브 모델(v0.2)은 이번 단계에서 바꾸지 않는다.

**Tech Stack:** Python 3.12, pandas 2.2.3, numpy 1.26.4, scikit-learn 1.6.1(KMeans, GaussianMixture, PCA, StandardScaler, silhouette_score), lightgbm 4.7.0, pyarrow 19.0.1, beautifulsoup4, PyYAML 6.0.2(신규), nbformat/nbclient, pytest.

**Spec:** `docs/superpowers/specs/2026-10-27-kbo-predict-design.md` (4.2 박스스코어 보완, 5.2 선수 유형, 5.3 재현성, 6절 노트북 규칙, 8절 `players.json`/`teams.json`/`model_report.json` 계약, 12절 3단계, 13절 2단계 규칙). 이월 항목: `docs/superpowers/plans/2026-10-27-stage0-deferred.md` "3단계(클러스터링) 전에" 절.

## Global Constraints

- 로직은 `src/kbo_predict/`에 한 번만. 노트북은 호출만 한다(함수·클래스 정의 금지, `tests/test_notebooks.py`가 검사).
- 재현성: `seed=42`. `KMeans(n_init=10, random_state=42)`, `GaussianMixture(random_state=42)`, `PCA(random_state=42, svd_solver="full")`. 같은 입력으로 두 번 맞추면 라벨·좌표·확률이 비트 단위로 같아야 한다.
- 누수: 승패 모델에 들어가는 유형은 **직전 시즌** 유형만. 군집 중심은 2015~2025 선수·시즌으로만 맞추고 2026은 `predict`로 배정만 한다. 승패 모델 분할(2015~2024 학습 / 2025 검증 / 2026 시험)과 R7 절차(캘리브레이터는 학습 LOSO OOF, 검증은 선택만)는 그대로.
- 기존 공개 파일 계약(`latest.json`, `history.csv`, `status.json`, `model_report.json`)의 기존 키·모양은 바꾸지 않는다. 키 추가와 `null` 자리 채우기(`matchup_feature_ablation`, `cluster_quality`, 선발 블록의 `type`)만 허용.
- 박스스코어 재파싱 뒤에도 `data/processed/features.parquet`의 SHA256은 `models/manifest.json`의 `47c1d961f080f250350a7b5ef084844b3c4e8ac07c4cab917c8a84eee2752e1e`와 같아야 한다(기존 칸 불변의 증거). 승패 모델 파일(`models/report-2026.pkl`, `models/win_model.pkl`)의 확률은 바뀌지 않는다.
- 네트워크 없이 모든 작업이 돌아야 한다. 재파싱은 로컬 캐시 `data/cache/html/games_{id}-*.html`만 읽는다(요청 금지). 캐시가 없는 경기는 건너뛰고 보고한다.
- 노트북 04: 맨 위 마크다운 셀에 "하는 일 / 왜 / 짝 `cluster.py`". 코드 셀마다 바로 위에 한국어 설명. 야구 용어 첫 등장 시 한 줄 설명(PA, K%, BB%, ISO, BABIP, 도루율, 선발 비중, 표준화, K-means, 실루엣, GMM, PCA, 코사인 유사도). 실행 결과 포함 커밋, stderr 없음. 문체는 `notebooks/03_승패_예측_모델.ipynb`를 따른다.
- 의존성은 `requirements.txt`에 `==` 고정. `umap-learn`, `shap`은 추가하지 않는다.
- 모든 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. 커밋 작성자는 저장소 로컬 설정(민서) 그대로. Windows 콘솔은 `python -X utf8`.
- `data/processed/`는 git 제외. `models/clusters.pkl`, `models/manifest.json`, `config/cluster_labels.yaml`, `data/public/players.json`, `data/public/teams.json`, 재파싱한 `data/raw/*/boxscores/*.jsonl.gz`는 커밋한다.

## 계획 시점의 판정 (스펙과 다른 부분, 스펙이 빌더에게 맡긴 부분)

- **2루타·3루타·도루 소스**: 스펙 4.2의 두 후보 중 **경기 페이지 기록표**를 쓴다(선수 페이지는 선수당 1요청 × 수천 명이라 robots 5초 간격으로 며칠이 걸림). 기록표는 조사한 150경기(2015~2026) 전부에 있고 형식은 `이름 (1st inning)`, `이름 (1st, 9th inning)`(이닝 수 = 개수)로 일정하다. 희생플라이·희생번트는 없으므로 PA = AB+BB+HBP 그대로.
- **선수 한글 이름**: 같은 기록표의 `title` 속성(`2루타: 신종길(1회) 필(1회)`)을 영문 항목과 순서로 맞춰 수집한다(한국 선수는 이름 전체, 외국인은 통용 표기 "필", "니퍼트"). 경기별 투표의 최빈값을 쓴다. 이월 항목 "선수 한글 이름 소스"의 해결.
- **2D 시각화는 PCA**(UMAP은 `umap-learn`+`numba` 의존성이 커서 제외). **GMM은 소속 확률 전용**: 라벨은 K-means로 고정하고, GMM(K-means 중심으로 초기화)의 사후 확률을 "소속 확률"로 쓰며 두 방법의 일치율을 `cluster_quality`에 적는다. 스펙 5.2의 "더 설명 잘 되는 쪽 채택"은 이렇게 결정론적으로 푼다.
- **K 선택 규칙**: K=4~7 각각 실루엣(맞춤 행)과 연도 간 유형 유지율(연속 두 시즌 모두 자격인 선수 중 같은 유형 비율)을 재고, `score = silhouette + retention`이 최대인 K(동률이면 작은 K). 타자·투수 따로.
- **유형 번호의 안정화**: K-means 라벨을 중심 프로파일로 다시 번호 매긴다 — 타자는 표준화 `hr_pct` 중심 내림차순, 투수는 `start_share` 내림차순 → 동률 시 `k_pct` 내림차순. 이름(`config/cluster_labels.yaml`)은 Task 4의 프로파일을 보고 **컨트롤러가 붙인다**(Task 4b).
- **피처**: 타자 `k_pct, bb_pct, hr_pct, iso, babip, sb_rate` (GB/FB 추정 불가, HR/FB 근사도 FB가 없어 제외). 투수 `k_pct, bb_pct, hr_pct, babip, start_share` (타자당 비율; `start_share`는 선발/구원 역할 비율로 "비율 지표만" 원칙 안). 정의는 Task 3.
- **자격**: 타자 PA ≥ 200, 투수 IP ≥ 50(아웃 150) 또는 구원 등판 ≥ 30. 스펙 값 그대로(분포를 노트북 04에 보여 주고, 바꿀 필요가 보이면 이월 항목으로).
- **상성 피처 모양**: 홈−원정 차이 꼴로 통일한다. `bat_type{t}_diff`(타선의 유형 t PA 비중 차이, K_b개), `starter_type{t}_diff`(상대 선발이 유형 t인지 one-hot의 차이 = 홈 선발 − 원정 선발, K_p개), `types_known`(양 팀 타선 PA의 유형 파악 비중이 모두 0.5 이상이고 양 선발 유형이 모두 있으면 1). 타선 구성은 "그 시즌 그 팀에서 지금까지 기록된 PA"를 직전 시즌 유형으로 가중한다(라인업은 경기 전에 모르므로). 별도 parquet `data/processed/matchup.parquet`(game_id + 상성 열)로 저장해 `features.parquet`와 보고서의 기존 숫자를 건드리지 않는다.
- **전후 비교 규약**: 선택된 알고리즘·캘리브레이션·트리 수 그대로, 피처만 26개 → 26 + 상성으로 늘려 같은 분할로 학습·평가. 채택 여부는 **2025 검증 log loss가 0.001 이상 좋아지면** `adopt: true`. 채택되더라도 라이브 모델 교체·일일 추론 배선은 4단계(주간 재학습과 함께)로 미룬다 — 이번 단계는 보고서 기록까지.
- **중심 적합 범위**: 2015~2025로 맞추고 2026 배정만. 학습 시즌(2015~2024) 경기의 직전 시즌 유형은 2025까지 본 중심에서 나오므로 "미래 시즌 통계가 경계에 영향"하지만 결과(승패)는 보지 않는 비지도 적합이다. 2026 시험 구간은 2026 통계를 전혀 보지 않은 중심이므로 깨끗하다. 보고서·노트북에 그대로 적는다.
- **`teams.json`의 모델 기대 승률**: 2026만(report-2026 모델의 홀드아웃 예측 평균). 2015~2025는 학습·검증 시즌이라 `null`로 두고 이유를 메타에 적는다.
- **포스트시즌 제외**: 선수 시즌 집계는 승패 모델과 같은 `regular_finals` 필터(정규시즌 FINAL, 박스스코어 있는 경기).

## Review Focus

1. 기록표 이름이 박스스코어의 두 선수와 맞거나 아무와도 안 맞으면 어느 선수에게도 세지 않고 `unmatched`에 남기며 예외를 내지 않는다 → Task 1 `test_records_ambiguous_name_goes_to_unmatched`.
2. 시즌 중 이적한 선수의 `team`은 출전 경기가 많은 팀, 동률이면 마지막 출전 팀 → Task 3 `test_traded_player_team_is_majority`.
3. 한 시즌만 자격인 선수도 유사 선수 5명을 받고, 같은 선수의 다른 시즌은 후보에서 빠진다 → Task 4 `test_similar_excludes_same_player`.
4. 2026 행을 넣고 맞추든 빼고 맞추든 중심·스케일러가 같다(2026은 배정만) → Task 4 `test_fit_ignores_seasons_outside_fit_seasons`.
5. 시즌 S 경기의 상성 피처는 S−1 유형만 쓰고, 개막전(PA 0)이나 유형 없는 선발이면 NaN/0으로 돌아가며 예외가 없다 → Task 5 `test_matchup_uses_previous_season_types_only`, `test_matchup_opening_day_is_nan`.

---

### Task 1: 기록표 파서 — 2루타·3루타·도루 + 한글 이름

**Files:**
- Modify: `src/kbo_predict/mykbo_parse.py` (`parse_game` 확장, `_records` 추가)
- Test: `tests/test_mykbo_parse.py`
- Fixtures(이미 있음): `tests/fixtures/mykbo_game_1189_final.html`(2015), `tests/fixtures/mykbo_game_14048_final.html`(2026)

**Interfaces:**
- Consumes: 기존 `parse_game(html) -> dict`(`batting[side]` 행: `order, player_id, name, pos, ab, r, h, hr, rbi, bb, so, hbp`; `pitching[side]` 행).
- Produces:
  - `parse_game` 반환의 타자 행에 정수 칸 `doubles`, `triples`, `sb` 추가(기록표가 있으면 0 이상, 기록표 `<table data-game-section="records">`가 없으면 셋 다 `None`).
  - 최상위 키 `names_ko: dict[str, str]`(문자열 player_id → 한글 이름; 기록표가 없거나 맞춘 이름이 없으면 `{}`)과 `records_unmatched: list[str]`(어느 선수에게도 못 붙인 항목의 영문 텍스트, 예 `"2B: Kim Min-su (3rd inning)"`).
  - 이름 맞추기 규칙(`_match_player(name, rows) -> int | None`): 기록표 이름과 행 `name`이 같으면 그 선수. 아니면 행 이름에 공백이 없고 기록표 이름의 **마지막 단어**와 같으면 그 선수(외국인: 기록표 "Brett Pill" ↔ 행 "Pill"). 후보가 0명 또는 2명 이상이면 `None`. 비교는 대소문자 무시, 악센트는 그대로(`Díaz`).
  - 개수 규칙: 항목 `이름 (1st, 9th inning)`의 괄호 안 쉼표 구분 토큰 수가 개수. 항목 구분은 `\),\s*`. 2B/3B/SB 행만 센다. HR/E/GIDP 행은 세지 않고 한글 이름에만 쓴다.
  - 한글 이름 규칙: `title`의 콜론 뒤를 `(\S+?)(\d+)?\((.*?)\)` 패턴으로 토큰화(`문우람2(1 9회)` → 이름 `문우람`). 영문 항목 수와 한글 토큰 수가 같을 때만 순서대로 짝지어 `names_ko`에 넣는다(다르면 그 행은 건너뜀). HR 행은 괄호 안에서 `회`·`점`으로 끝나지 않는 토큰을 투수 한글 이름으로 보고, 영문의 `off X` 투수(세미콜론으로 나뉜 홈런별)와 수가 같을 때 `pitching` 행에 같은 규칙으로 맞춰 넣는다.
  - 이름 충돌: 한 경기 안에서 같은 player_id에 다른 한글이 붙으면 먼저 본 것을 유지한다.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_mykbo_parse.py`)

```python
def test_parse_game_records_2015():
    g = parse_game(fixture("mykbo_game_1189_final.html"))
    bat = {r["player_id"]: r for s in ("away", "home") for r in g["batting"][s]}
    assert (bat[293]["doubles"], bat[273]["doubles"], bat[825]["doubles"], bat[13]["doubles"]) == (1, 1, 1, 1)
    assert bat[909]["triples"] == 1
    assert sum(r["sb"] for r in bat.values()) == 0 and sum(r["doubles"] for r in bat.values()) == 4
    assert all(r["triples"] == 0 for pid, r in bat.items() if pid != 909)
    assert g["names_ko"]["293"] == "신종길" and g["names_ko"]["825"] == "필" and g["names_ko"]["909"] == "최용규"
    assert g["names_ko"]["930"] == "정진호" and g["names_ko"]["30"] == "양의지"      # HR, GIDP 행에서
    assert g["names_ko"]["288"] == "서재응" and g["names_ko"]["18"] == "니퍼트"      # HR을 맞은 투수
    assert g["records_unmatched"] == []

def test_parse_game_records_2026():
    g = parse_game(fixture("mykbo_game_14048_final.html"))
    bat = {r["player_id"]: r for s in ("away", "home") for r in g["batting"][s]}
    assert bat[532]["doubles"] == 1 and bat[2281]["doubles"] == 1
    assert bat[2281]["sb"] == 1 and bat[1879]["sb"] == 1 and sum(r["sb"] for r in bat.values()) == 2
    assert g["names_ko"]["2949"] == "카스트로" and g["names_ko"]["3097"] == "페덱" and g["names_ko"]["1964"] == "박민"

def test_records_multi_inning_counts_two():
    # 기록표 조각을 1189 픽스처의 기록표 자리에 끼워 넣는다: "Shin Jong-gil (1st, 9th inning)" / title "2루타: 신종길2(1 9회)"
    ...
    assert bat[293]["doubles"] == 2 and g["names_ko"]["293"] == "신종길"

def test_records_ambiguous_name_goes_to_unmatched():
    # 두 타자 행 이름을 모두 "Kim"으로 바꾼 HTML에서 "2B | Kim (3rd inning)"은 아무에게도 안 붙고 unmatched에 남는다
    ...
    assert g["records_unmatched"] == ["2B: Kim (3rd inning)"]

def test_records_table_absent_gives_none():
    html = fixture("mykbo_game_1189_final.html").replace('data-game-section="records"', 'data-game-section="x"')
    g = parse_game(html)
    assert all(r["doubles"] is None and r["triples"] is None and r["sb"] is None
               for s in ("away", "home") for r in g["batting"][s])
    assert g["names_ko"] == {} and g["records_unmatched"] == []
```

- [ ] **Step 2: 실패 확인** — Run: `python -X utf8 -m pytest tests/test_mykbo_parse.py -k records -v` → FAIL(KeyError `doubles`)
- [ ] **Step 3: 구현** — `mykbo_parse._records(soup, batting, pitching) -> tuple[dict[int, dict[str, int]], dict[str, str], list[str]]`를 만들고 `parse_game`이 호출해 타자 행에 칸을 붙인다. 기존 반환 키·값은 그대로.
- [ ] **Step 4: 통과 확인** — Run: `python -X utf8 -m pytest tests/test_mykbo_parse.py -v` → PASS (기존 테스트 포함)
- [ ] **Step 5: 커밋** — `git commit -m "feat: 경기 기록표에서 2루타·3루타·도루와 한글 이름 파싱"`

---

### Task 2: 박스스코어 재파싱 (로컬 캐시, 기존 칸 불변 검증)

**Files:**
- Create: `scripts/reparse_boxscores.py`
- Modify: `src/kbo_predict/raw_store.py` (`rewrite_boxscores` 추가)
- Modify: `data/raw/{2015..2026}/boxscores/*.jsonl.gz` (재생성)
- Test: `tests/test_raw_store.py`, `tests/test_dataset_real.py`

**Interfaces:**
- Consumes: Task 1 `parse_game`, `raw_store.load_boxscores(season)`, `raw_store._dumps`.
- Produces:
  - `raw_store.rewrite_boxscores(season: int, boxscores: dict[int, dict]) -> int` — 시즌의 월 파일을 전부 지우고 `(date, game_id)` 순으로 다시 쓴다(`append_boxscores`와 같은 `_dumps`, gzip, `\n`). 쓴 행 수 반환.
  - `scripts/reparse_boxscores.py --cache data/cache/html --seasons 2015-2026 [--dry-run]` — 시즌별로 박스스코어를 읽고, `games_{game_id}-*.html` 캐시를 찾아 `parse_game`으로 다시 파싱한 뒤 **새 키(`doubles`, `triples`, `sb`, `names_ko`, `records_unmatched`)를 뺀 나머지가 기존과 완전히 같은지** 비교한다(다르면 그 game_id를 출력하고 비정상 종료, 아무 파일도 쓰지 않음). 요약을 표준 출력에 찍는다: 시즌, 경기 수, 재파싱 수, 캐시 없음 수, 기록표 없음 수, unmatched 항목 수. 네트워크 요청 금지.
- [ ] **Step 1: 테스트** (`tests/test_raw_store.py`)

```python
def test_rewrite_boxscores_replaces_month_files(tmp_data_dir):
    append_boxscores(2030, {1: {"game_id": 1, "date": "2030-04-01"}, 2: {"game_id": 2, "date": "2030-05-01"}})
    assert rewrite_boxscores(2030, {2: {"game_id": 2, "date": "2030-05-01", "x": 1}}) == 1
    assert load_boxscores(2030) == {2: {"game_id": 2, "date": "2030-05-01", "x": 1}}
    assert not (boxscores_dir(2030) / "2030-04.jsonl.gz").exists()
```

- [ ] **Step 2: 실패 확인** → ImportError
- [ ] **Step 3: `rewrite_boxscores` 구현 + 스크립트 작성**
- [ ] **Step 4: 드라이런** — Run: `python -X utf8 scripts/reparse_boxscores.py --seasons 2026 --dry-run` → 요약 출력, 불일치 0
- [ ] **Step 5: 전체 재파싱 실행** — Run: `python -X utf8 scripts/reparse_boxscores.py --seasons 2015-2026 > reparse.log` (약 30~60분, 백그라운드 허용). 요약을 보고서에 옮긴다. 캐시 없음 경기가 있으면 game_id 목록을 보고서에 적는다(기록표 칸은 `None`으로 남음).
- [ ] **Step 6: 불변 검증** — Run: `python -X utf8 -m kbo_predict.features --out data/processed/features.parquet` 후 `python -X utf8 -c "from kbo_predict.features import features_sha256; print(features_sha256('data/processed/features.parquet'))"` → `47c1d961f080f250350a7b5ef084844b3c4e8ac07c4cab917c8a84eee2752e1e`
- [ ] **Step 7: 실데이터 테스트 추가** (`tests/test_dataset_real.py`)

```python
def test_records_coverage():
    # 재파싱 뒤: 정규시즌 FINAL 박스스코어의 99% 이상에 기록표 칸이 있고, 전체 unmatched 항목은 200개 미만
    missing = unmatched = total = 0
    for season in sorted(EXPECTED_ROWS):
        for b in raw_store.load_boxscores(season).values():
            total += 1
            rows = b["batting"]["away"] + b["batting"]["home"]
            missing += rows[0]["doubles"] is None if rows else 1
            unmatched += len(b.get("records_unmatched", []))
    assert missing / total < 0.01 and unmatched < 200
```

- [ ] **Step 8: 전체 테스트** — Run: `python -X utf8 -m pytest -q` → 모두 PASS
- [ ] **Step 9: 커밋** (데이터 포함) — `git commit -m "data: 박스스코어에 2루타·3루타·도루·한글 이름 보강(로컬 캐시 재파싱, 기존 칸 불변)"`

---

### Task 3: 선수·시즌 집계 (`player_stats.py`)

**Files:**
- Create: `src/kbo_predict/player_stats.py`
- Test: `tests/test_player_stats.py`, `tests/test_dataset_real.py`

**Interfaces:**
- Consumes: `raw_store.load_games/load_boxscores`, `features.regular_finals(games, season)`, `features._add_rows`.
- Produces:
  - `BATTING_SUM = ("ab", "r", "h", "hr", "rbi", "bb", "so", "hbp", "doubles", "triples", "sb")`, `PITCHING_SUM = ("ip_outs", "np", "r", "er", "h", "hr", "so", "bb", "hbp")`.
  - `batting_seasons(seasons: list[int]) -> pd.DataFrame` 열: `season, player_id, name, team, pos, games, games_with_records, pa, *BATTING_SUM`. `pa = ab + bb + hbp`. `team` = 그 시즌 출전 경기 수가 가장 많은 팀 코드(동률이면 마지막 출전 팀), `pos` = 가장 많이 적힌 포지션 문자열(동률이면 먼저 나온 것). `games_with_records` = `doubles`가 `None`이 아닌 경기 수. 정규시즌 FINAL + 박스스코어 있는 경기만. 행 순서 `(season, player_id)`.
  - `pitching_seasons(seasons) -> pd.DataFrame` 열: `season, player_id, name, team, games, starts, bf, *PITCHING_SUM`. `bf = ip_outs + h + bb + hbp`, `starts` = `order == 1`인 등판 수.
  - `korean_names(seasons) -> dict[int, str]` — 모든 박스스코어의 `names_ko` 투표. 최빈값의 득표 비중이 0.6 이상이면 채택, 아니면 제외. 동률은 가나다 순 첫 값.
  - `name` = 그 시즌 마지막 출전 경기 행의 `name`.
- [ ] **Step 1: 테스트** (`tests/test_player_stats.py`, 작은 합성 박스스코어 2~3경기를 `monkeypatch`로 `raw_store.load_games/load_boxscores`에 주입)

```python
def test_batting_sums_and_pa(fake_raw):
    df = batting_seasons([2030]).set_index("player_id")
    assert df.loc[1, ["pa", "doubles", "sb", "games"]].tolist() == [9, 2, 1, 2]

def test_traded_player_team_is_majority(fake_raw):      # 선수 2: LG 2경기, HT 1경기 → LG
    assert batting_seasons([2030]).set_index("player_id").loc[2, "team"] == "LG"

def test_pitching_bf_and_starts(fake_raw):
    row = pitching_seasons([2030]).set_index("player_id").loc[10]
    assert (row["bf"], row["starts"], row["games"]) == (row["ip_outs"] + row["h"] + row["bb"] + row["hbp"], 1, 2)

def test_korean_names_majority(fake_raw):               # 1: 두 경기 모두 "김철수" → 채택; 3: "박a"/"박b" 반반 → 제외
    names = korean_names([2030])
    assert names[1] == "김철수" and 3 not in names

def test_postseason_excluded(fake_raw):                 # is_regular가 False인 날짜의 경기는 집계되지 않는다
    ...
```

- [ ] **Step 2: 실패 확인** → ModuleNotFoundError
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** + 실데이터 검사 추가 (`tests/test_dataset_real.py`)

```python
def test_player_seasons_real():
    bat, pit = batting_seasons(sorted(EXPECTED_ROWS)), pitching_seasons(sorted(EXPECTED_ROWS))
    assert (bat.pa >= 200).groupby(bat.season).sum().between(120, 200).all()        # 시즌당 규정급 타자 수 상식 범위
    assert ((pit.ip_outs >= 150) | (pit.games - pit.starts >= 30)).groupby(pit.season).sum().between(100, 200).all()
    assert len(korean_names(sorted(EXPECTED_ROWS))) > 1500
```

- [ ] **Step 5: 커밋** — `git commit -m "feat: 박스스코어 선수·시즌 집계와 한글 이름 투표"`

---

### Task 4: 군집 코어 (`cluster.py`) — 비율 지표, K 선택, GMM 확률, PCA, 유사 선수, CLI

**Files:**
- Create: `src/kbo_predict/cluster.py`
- Modify: `requirements.txt` (`pyyaml==6.0.2`), `models/manifest.json`(CLI가 갱신), `.gitignore` 확인(`data/processed/` 이미 제외)
- Test: `tests/test_cluster.py`

**Interfaces:**
- Consumes: Task 3 `batting_seasons`, `pitching_seasons`, `korean_names`; `train_win.write_manifest` 패턴(`_sha256`, `_commit_sha`).
- Produces:
  - 상수: `SEED = 42`, `K_RANGE = range(4, 8)`, `FIT_SEASONS = list(range(2015, 2026))`, `MIN_PA = 200`, `MIN_IP_OUTS = 150`, `MIN_RELIEF_APPS = 30`, `BATTER_FEATURES = ["k_pct", "bb_pct", "hr_pct", "iso", "babip", "sb_rate"]`, `PITCHER_FEATURES = ["k_pct", "bb_pct", "hr_pct", "babip", "start_share"]`, `GROUPS = ("batter", "pitcher")`, `CLUSTER_VERSION = "clusters-2026"`.
  - `rates(df: pd.DataFrame, group: str) -> pd.DataFrame` — 열 추가. 타자: `k_pct = so/pa`, `bb_pct = bb/pa`, `hr_pct = hr/pa`, `iso = (doubles + 2*triples + 3*hr)/ab`, `babip = (h-hr)/(ab-so-hr)`, `sb_rate = sb/(h-hr-doubles-triples+bb+hbp)`(1루 도달 기회당 도루). 투수: `k_pct = so/bf`, `bb_pct = (bb+hbp)/bf`, `hr_pct = hr/bf`, `babip = (h-hr)/(bf-so-bb-hbp-hr)`, `start_share = starts/games`. 분모 0 → NaN.
  - `qualify(df, group) -> pd.DataFrame` — 타자 `pa >= 200`; 투수 `ip_outs >= 150 or games - starts >= 30`. 피처에 NaN이 있는 행 제외.
  - `fit_group(df: pd.DataFrame, group: str, *, fit_seasons=FIT_SEASONS, k: int | None = None) -> dict` — 자격 행 중 `season ∈ fit_seasons`로 `StandardScaler` → K마다 `KMeans(n_clusters=k, n_init=10, random_state=42)` → `k_table = [{"k", "silhouette", "retention", "score"}]`(retention = 연속 두 시즌 모두 자격·맞춤 행인 선수 중 같은 라벨 비율) → `k` 미지정이면 `score` 최대(동률 작은 K) → 라벨 재번호(판정 참조) → `GaussianMixture(n_components=k, covariance_type="full", means_init=중심, random_state=42)` → `PCA(2, random_state=42, svd_solver="full")`. 반환 번들: `{"group", "features", "fit_seasons", "k", "k_table", "scaler", "kmeans", "gmm", "pca", "centers": DataFrame(원 단위, index=type), "centers_z": DataFrame(표준화)}`.
  - `assign(bundle, df_rates: pd.DataFrame) -> pd.DataFrame` — 자격 행 전부(2026 포함)에 `type`(int), `membership`(list[float], GMM 사후 확률), `prob`(= membership[type]), `x`, `y` 추가. 결정론.
  - `similar_players(bundle, assigned: pd.DataFrame, n: int = 5) -> dict[tuple[int, int], list[dict]]` — 표준화 공간 코사인 유사도, 같은 `player_id`의 모든 시즌 제외, 상위 n `{"season", "player_id", "similarity"}`. 동률은 `(season, player_id)` 오름차순.
  - `retention(assigned) -> float`, `gmm_agreement(assigned) -> float`.
  - `quality(bundles, assigned, names_cfg) -> dict` = `model_report.json`의 `cluster_quality` 값: `{"version", "fit_seasons", "batter": {"k", "k_table", "n_fit", "n_all", "gmm_agreement", "retention", "types": [{"id", "name", "n", "center": {feat: round(v, 3)}, "examples": [name 3개 — 2025 시즌 prob 상위]}]}, "pitcher": {...}}`.
  - `load_labels(path="config/cluster_labels.yaml") -> dict[str, dict[int, dict]]` — YAML 모양: `batter: {0: {name: "...", blurb: "..."}, ...}`, `pitcher: {...}`. 파일이 없으면 모든 이름이 `"유형 {t}"`인 기본값(Task 4b 전 테스트용).
  - `build(seasons: list[int]) -> dict` — `{"batter": {"bundle", "assigned", "similar"}, "pitcher": {...}, "names_ko": dict}` 전체 묶음; `save_bundle(obj, path)`/`load_bundle(path)`(joblib).
  - `types_map(obj) -> dict[tuple[int, int], dict[str, int]]` — `(season, player_id) → {"batter": t}` 또는 `{"pitcher": t}`(둘 다일 수도).
  - CLI `python -m kbo_predict.cluster fit [--out models/clusters.pkl]` — `build(2015..2026)` → pkl 저장, `data/processed/player_types.csv`(`season, player_id, group, type, prob, x, y`; 정렬 `(group, season, player_id)`; float은 소수 6자리) 저장, `models/manifest.json`의 `models.clusters` 항목 `{"path", "sha256", "version": "clusters-2026", "fit_seasons", "types_sha256"(csv의 SHA256)}` 갱신(다른 항목 유지). 프로파일 표(유형별 n, 원 단위 중심, 예시 선수 5명과 한글 이름)를 표준 출력에 찍는다 — Task 4b 입력.
- [ ] **Step 1: 테스트** (`tests/test_cluster.py`, 합성 데이터: 뚜렷한 군집 3~4개를 `numpy.random.default_rng(0)`으로 생성, 시즌 2015~2026 부여)

```python
def test_rates_formulas():
    row = pd.DataFrame([{"pa": 100, "ab": 90, "h": 27, "hr": 5, "doubles": 6, "triples": 1, "so": 20, "bb": 8, "hbp": 2, "sb": 4}])
    r = rates(row, "batter").iloc[0]
    assert r.k_pct == 0.2 and r.bb_pct == 0.08 and r.hr_pct == 0.05
    assert r.iso == pytest.approx((6 + 2 + 15) / 90) and r.babip == pytest.approx(22 / 65)
    assert r.sb_rate == pytest.approx(4 / (27 - 5 - 6 - 1 + 8 + 2))

def test_qualify_thresholds():
    # pa 199 제외·200 포함; 투수 ip_outs 150 포함, 구원 30경기 포함, 둘 다 미달 제외

def test_fit_is_deterministic(synthetic):
    a, b = fit_group(synthetic, "batter"), fit_group(synthetic, "batter")
    assert a["k"] == b["k"] and (a["kmeans"].cluster_centers_ == b["kmeans"].cluster_centers_).all()
    assert assign(a, synthetic).equals(assign(b, synthetic))

def test_fit_ignores_seasons_outside_fit_seasons(synthetic):
    with26, without26 = fit_group(synthetic, "batter"), fit_group(synthetic[synthetic.season < 2026], "batter")
    assert (with26["kmeans"].cluster_centers_ == without26["kmeans"].cluster_centers_).all()
    assert (with26["scaler"].mean_ == without26["scaler"].mean_).all()

def test_k_selection_uses_score_and_relabels(synthetic):   # 합성 군집 수 = 4 → k == 4; 유형 0의 hr_pct 중심이 가장 큼
def test_similar_excludes_same_player(synthetic):
def test_types_map_and_quality_shape(synthetic):
def test_load_labels_default_when_missing(tmp_path):
```

- [ ] **Step 2: 실패 확인** → ModuleNotFoundError
- [ ] **Step 3: 구현** (`pip install pyyaml==6.0.2`, requirements 고정)
- [ ] **Step 4: 통과 확인** — Run: `python -X utf8 -m pytest tests/test_cluster.py -v`
- [ ] **Step 5: 실데이터 실행** — Run: `python -X utf8 -m kbo_predict.cluster fit` → 프로파일 표를 보고서 파일에 그대로 옮긴다(K 표, 유형별 중심·인원·예시 선수). `models/clusters.pkl`, `models/manifest.json` 커밋. 두 번 실행해 `types_sha256`이 같은지 확인.
- [ ] **Step 6: 커밋** — `git commit -m "feat: 선수 유형 군집(K-means+GMM+PCA), 유사 선수, clusters-2026"`

### Task 4b (컨트롤러): 유형 이름 붙이기

- 컨트롤러가 Task 4 보고서의 프로파일을 보고 `config/cluster_labels.yaml`을 쓴다(유형마다 `name` 2~5자 한국어, `blurb` 한 문장). 이름은 스탯 프로파일이 근거(예: K%↓·BB%↑ → "출루형"). 커밋 `docs: 선수 유형 이름 붙이기`. Task 6·8은 이 파일을 읽는다.

---

### Task 5: 상성 피처 + 전후 비교 보고서

**Files:**
- Modify: `src/kbo_predict/features.py` (`LeagueState(types=)`, 상성 피처, `build_dataset(..., types=)`, CLI `--matchup-out`)
- Modify: `src/kbo_predict/train_win.py` (`train_report(..., matchup=, cluster_quality=)`, `_matchup_ablation`, CLI 옵션)
- Modify: `data/public/model_report.json`, `models/report-2026.pkl`, `models/manifest.json` (재생성)
- Test: `tests/test_features.py`, `tests/test_train_win.py`

**Interfaces:**
- Consumes: Task 4 `load_bundle`, `types_map`, `quality`, `load_labels`; 기존 `LeagueState`, `game_features`, `build_training_frame`, `train_report`.
- Produces:
  - `features.matchup_feature_names(kb: int, kp: int) -> list[str]` = `[f"bat_type{t}_diff" for t in range(kb)] + [f"starter_type{t}_diff" for t in range(kp)] + ["types_known"]`.
  - `LeagueState(types: dict[tuple[int, int], dict] | None = None, kb: int = 0, kp: int = 0)` — `_add_box_side`가 팀별 `pa_by_player: Counter`(당해 시즌)를 쌓는다(`start_season`에서 비움). `lineup_shares(code) -> tuple[list[float] | None, float]` = (유형별 PA 비중 K_b개, 유형이 있는 PA 비중); 유형은 `types.get((self.season - 1, pid), {}).get("batter")`. 유형 있는 PA가 0이면 `(None, 0.0)`.
  - `starter_type(state, player_id) -> int | None` = `types.get((season - 1, pid), {}).get("pitcher")`.
  - `game_features`가 `state.types is not None`일 때 상성 키를 추가: `bat_type{t}_diff = home_share[t] − away_share[t]`(한쪽이라도 None이면 NaN), `starter_type{t}_diff = onehot(home 선발 유형)[t] − onehot(away 선발 유형)[t]`(유형 없는 선발은 0 벡터), `types_known = 1 if (양 팀 known 비중 ≥ 0.5 and 양 선발 유형 모두 있음) else 0`.
  - `build_dataset(seasons, *, types=None, kb=0, kp=0)`; `main --matchup-out data/processed/matchup.parquet --clusters models/clusters.pkl` → `game_id` + 상성 열만 저장(`features.parquet`는 건드리지 않음).
  - `train_win.train_report(df, *, matchup: pd.DataFrame | None = None, cluster_quality: dict | None = None, ...)` — `matchup`이 있으면 `game_id`로 병합해 `_matchup_ablation(selected, calibration, best_iteration, train, val, test, train_seasons, names) -> dict` = `{"features_added": names, "without": {"val": evaluate, "test": evaluate}, "with": {...}, "mcnemar_p_test": p(with vs without 적중), "adopt": bool(with.val.log_loss < without.val.log_loss - 0.001), "note": "선택된 알고리즘·캘리브레이션·트리 수 고정, 피처만 추가. 라이브 반영은 4단계."}`를 `report["matchup_feature_ablation"]`에, `cluster_quality`를 `report["cluster_quality"]`에 넣는다. 없으면 `None` 그대로.
  - CLI `python -m kbo_predict.train_win report --force --matchup data/processed/matchup.parquet --clusters models/clusters.pkl` — `cluster_quality`는 `cluster.quality(...)`와 `load_labels()`로 만든다.
- [ ] **Step 1: 테스트** (`tests/test_features.py`)

```python
def test_matchup_uses_previous_season_types_only(two_season_games):
    # 유형: (2025, 타자 A) → batter 1, (2026, 타자 A) → batter 0 ; 2026 경기에서 A의 PA는 유형 1로 세어야 한다
    types = {(2025, 1): {"batter": 1}, (2026, 1): {"batter": 0}, (2025, 10): {"pitcher": 2}}
    df = build_dataset_from(two_season_games, types=types, kb=2, kp=3)
    row = df[df.season == 2026].iloc[-1]
    assert row["bat_type1_diff"] > 0 and row["starter_type2_diff"] != 0

def test_matchup_opening_day_is_nan(two_season_games):
    first = df[df.season == 2026].iloc[0]
    assert np.isnan(first["bat_type0_diff"]) and first["types_known"] == 0

def test_matchup_columns_absent_without_types():
    assert set(build_training_frame(...).columns) == {..., *FEATURE_NAMES, "y"}   # 기존 26개 그대로
```

(`tests/test_train_win.py`)

```python
def test_report_matchup_ablation_keys(small_df, small_matchup):
    report, _ = train_report(small_df, matchup=small_matchup, cluster_quality={"version": "x"}, meta={})
    ab = report["matchup_feature_ablation"]
    assert set(ab) == {"features_added", "without", "with", "mcnemar_p_test", "adopt", "note"}
    assert report["cluster_quality"] == {"version": "x"}
    assert ab["without"]["test"] == report["models"][report["selected"]]["test"]   # 전 = 본 모델과 동일

def test_report_without_matchup_unchanged(small_df):
    a, _ = train_report(small_df, meta={}); b, _ = train_report(small_df, matchup=None, meta={})
    assert a == b and a["matchup_feature_ablation"] is None
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — Run: `python -X utf8 -m pytest tests/test_features.py tests/test_train_win.py -v`
- [ ] **Step 5: 실데이터 생성** — Run: `python -X utf8 -m kbo_predict.features --matchup-out data/processed/matchup.parquet --clusters models/clusters.pkl` 후 `python -X utf8 -m kbo_predict.train_win report --force --matchup data/processed/matchup.parquet --clusters models/clusters.pkl`. 확인: 새 `model_report.json`에서 `matchup_feature_ablation`·`cluster_quality`·`generated_at`·`commit_sha`를 뺀 나머지가 커밋된 이전 파일과 **완전히 같다**(파이썬으로 dict 비교해 보고서에 결과 기록). `models/report-2026.pkl`의 2026 확률이 이전 pkl과 같다(`np.allclose(..., atol=0)`).
- [ ] **Step 6: 전체 테스트** — `python -X utf8 -m pytest -q` (노트북 03 실행 테스트는 Task 9에서 고치므로 이 시점의 실패는 `test_notebook_executes_without_errors[03]`만 허용. 보고서에 적는다.)
- [ ] **Step 7: 커밋** — `git commit -m "feat: 직전 시즌 유형 상성 피처와 전후 비교, cluster_quality를 보고서에 기록"`

---

### Task 6: 사이트 데이터 — `players.json`, `teams.json`, 선발 유형 표시

**Files:**
- Create: `src/kbo_predict/site_data.py`
- Modify: `src/kbo_predict/cluster.py` (CLI `publish`), `src/kbo_predict/predict.py` (`starter_types`), `scripts/run_pipeline.py`
- Create: `data/public/players.json`, `data/public/teams.json`
- Test: `tests/test_site_data.py`, `tests/test_predict.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 4 번들·`similar`·`names_ko`·`load_labels`; Task 3 집계; `features.load_features`, `train_win.load_bundle/predict_proba`, `publish._write_json`, `teams.TEAMS`.
- Produces:
  - `site_data.players_payload(obj, labels, meta) -> dict` = `{"generated_at", "commit_sha", "model_version": "clusters-2026", "fit_seasons", "types": {"batter": [{"id", "name", "blurb"}], "pitcher": [...]}, "players": [...]}`. 선수 항목(선수·시즌당 1개, 정렬 `season` 내림차순 → `group` → `player_id`): `{"player_id", "name", "name_ko"(없으면 null), "group", "season", "team", "pos"(투수는 "P"), "type": {"id", "name"}, "prob"(소수 3), "membership"(소수 3 리스트), "x", "y"(소수 3), "stats": 타자 `{"pa", "avg"(h/ab), "obp", "hr", "sb", "k_pct", "bb_pct", "iso", "babip"}` / 투수 `{"games", "starts", "ip"(소수 1), "era", "k_pct", "bb_pct", "hr_pct", "babip"}`(비율은 소수 3), "similar": [{"player_id", "name", "name_ko", "season", "team", "similarity"(소수 3)} ×5]}`.
  - `site_data.teams_payload(seasons, *, obj, labels, features_df, report_bundle, meta) -> dict` = `{"generated_at", "commit_sha", "model_version": "report-2026", "note": "model_expected는 2026(홀드아웃)만; 2015~2025는 학습·검증 시즌이라 null", "teams": [{"season", "code", "name"(TEAMS ko), "games", "wins", "losses", "ties", "win_pct", "pyth_pct"(지수 1.83), "model_expected"(2026만: 홈 경기 p + 원정 경기 (1−p) 평균, 아니면 null), "home_pct", "away_pct", "vs": {상대코드: win_pct}, "roster_types": {"batter": {유형 id: PA 비중}, "pitcher": {유형 id: IP 비중}}(그 시즌 유형)} ...]}` 정렬 `(season desc, win_pct desc)`. 정규시즌 FINAL만(`regular_finals`).
  - CLI `python -m kbo_predict.cluster publish [--clusters models/clusters.pkl] [--report models/report-2026.pkl]` → 두 JSON 생성(`_write_json`: `ensure_ascii=False, indent=1, sort_keys=True`).
  - `predict.predict_game(bundle, game, state, starters=None, starter_types: dict[int, dict] | None = None)` — 선발 블록에 `"type": {"id", "name"} | None` 추가(`starter_types[player_id]`가 있을 때). `run_pipeline.run`이 `models/clusters.pkl`이 있으면 `types_map`에서 `(season-1, pid)`의 투수 유형을 모아 넘긴다(없으면 `None`, 키는 `null`).
- [ ] **Step 1: 테스트** (`tests/test_site_data.py` 합성 번들, `tests/test_predict.py`, `tests/test_pipeline.py`)

```python
def test_players_payload_shape(synthetic_obj):
    p = players_payload(synthetic_obj, load_labels(missing_path), meta={"generated_at": "t", "commit_sha": None})
    first = p["players"][0]
    assert set(first) == {"player_id", "name", "name_ko", "group", "season", "team", "pos", "type", "prob", "membership", "x", "y", "stats", "similar"}
    assert len(first["similar"]) == 5 and all(s["player_id"] != first["player_id"] for s in first["similar"])
    assert abs(sum(first["membership"]) - 1) < 0.01

def test_teams_payload_model_expected_only_2026(...):
    assert all(t["model_expected"] is None for t in teams if t["season"] != 2026)
    assert all(0 < t["model_expected"] < 1 for t in teams if t["season"] == 2026)
    assert all(abs(sum(t["roster_types"]["batter"].values()) - 1) < 1e-6 for t in teams if t["roster_types"]["batter"])

def test_predict_game_adds_starter_type(...):      # starter_types 주면 type 블록, 안 주면 None
def test_pipeline_runs_without_clusters_pkl(...):  # 파일이 없어도 기존과 같이 돈다
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** + 실데이터 생성 — Run: `python -X utf8 -m kbo_predict.cluster publish` → `players.json` 크기와 선수 수, `teams.json` 팀·시즌 수를 보고서에 적는다. `python -X utf8 scripts/run_pipeline.py --no-fetch`(기존 옵션명 확인)로 `latest.json`의 선발 블록에 `type`이 생기는지 확인하되, **`latest.json`·`status.json`·`history.csv`는 커밋하지 않는다**(Actions 소유).
- [ ] **Step 5: 커밋** — `git commit -m "feat: players.json·teams.json 발행, 오늘 경기 선발 유형 표시"`

---

### Task 7: 노트북 04 선수 유형 클러스터링

**Files:**
- Create: `notebooks/04_선수_유형_클러스터링.ipynb`
- Modify: `tests/test_notebooks.py` (`NOTEBOOKS["04_선수_유형_클러스터링.ipynb"] = "cluster.py"`)

**Interfaces:**
- Consumes: Task 3·4·6 함수, `config/cluster_labels.yaml`, `models/manifest.json`, `data/public/model_report.json`, `data/public/players.json`.
- 구성(마크다운 → 코드 쌍, 03번 문체):
  1. 준비(경로, 폰트, 색) — 03번 셀과 같은 설정.
  2. 박스스코어 → 선수·시즌 집계: `batting_seasons`/`pitching_seasons` 호출, 한 선수의 행을 `display`. 기록표에서 보강한 칸(2루타·3루타·도루)과 한글 이름 설명.
  3. 자격 기준: PA·IP·구원 등판 히스토그램과 임계값 선, 시즌별 자격 인원 표.
  4. 비율 지표: 각 지표 정의와 "왜 누적 스탯이 아닌 비율인가". `rates` 호출, 상관 행렬 히트맵.
  5. 표준화 + K 고르기: `fit_group`의 `k_table`을 표·그래프(실루엣·유지율·score)로. 선택된 K 해석.
  6. 유형 프로파일: 원 단위 중심 표 + `cluster_labels.yaml` 이름·설명 나란히. 유형별 인원.
  7. 2D 지도(PCA): 유형별 색 산점도, 2025 대표 선수 몇 명 라벨. PCA 축 설명.
  8. 소속 확률(GMM): `prob` 분포, "경계에 있는 선수" 예시 표, K-means 일치율.
  9. 유사 선수: 2025 홈런 1위 타자와 선발 1명의 유사 선수 5명 표(한글 이름 포함).
  10. 연도 간 유지율: 유형 전이 행렬(2024→2025).
  11. 팀 로스터 구성: 2026 팀별 타선 유형 비중 누적 막대(`teams.json`에서).
  12. 상성 피처 전후 비교: `model_report.json`의 `matchup_feature_ablation` 표와 솔직한 해석(adopt 여부, 2026은 2026 통계를 보지 않은 중심).
  13. 패리티: 노트북에서 만든 라벨 DataFrame을 `data/processed/player_types.csv`와 같은 형식으로 만들어 SHA256이 `manifest.models.clusters.types_sha256`과 같은지 `assert`; `quality(...)`가 `model_report.json["cluster_quality"]`와 같은지 `assert`.
  14. 마무리: 배운 점·한계(ISO에 2루타·3루타만 반영, 수비·주루 지표 부재, 2026 유형은 시즌 종료 기준).
- [ ] **Step 1: 테스트 등록 후 실패 확인** — `python -X utf8 -m pytest tests/test_notebooks.py -k 04 -v` → FAIL(파일 없음)
- [ ] **Step 2: 노트북 작성 + 실행** — `jupyter nbconvert --to notebook --execute --inplace notebooks/04_선수_유형_클러스터링.ipynb` (실행 시간 보고서에)
- [ ] **Step 3: 통과 확인** — `python -X utf8 -m pytest tests/test_notebooks.py -k 04 -v` (구조 + 실행 + stderr 없음)
- [ ] **Step 4: 커밋** — `git commit -m "docs: 노트북 04 선수 유형 클러스터링(실행 결과 포함)"`

---

### Task 8: 노트북 03 갱신 (상성 전후 비교 절 + 패리티)

**Files:**
- Modify: `notebooks/03_승패_예측_모델.ipynb`

- 패리티 셀이 `train_report(df, matchup=load(matchup.parquet), cluster_quality=quality(...), meta=...)`를 호출해 `generated_at`·`commit_sha`를 뺀 전체 dict가 커밋된 `model_report.json`과 같은지 `assert`. 마지막 절 앞에 "유형 상성 피처를 넣으면?" 절 추가(전·후 표, adopt 결과, 왜 라이브는 아직 안 바꾸는지, 중심 적합 범위 주의). 03번의 다른 숫자는 바뀌지 않아야 한다(보고서에 전·후 비교 결과 기록).
- [ ] **Step 1: 수정 + 실행** — `jupyter nbconvert --to notebook --execute --inplace notebooks/03_승패_예측_모델.ipynb`
- [ ] **Step 2: 통과 확인** — `python -X utf8 -m pytest tests/test_notebooks.py -v` (01~04 전부)
- [ ] **Step 3: 커밋** — `git commit -m "docs: 노트북 03에 상성 피처 전후 비교와 cluster_quality 패리티 추가"`

---

### Task 9: 문서 갱신

**Files:**
- Modify: `README.md` (선수 유형 절: 지표·K·유형 이름 표·유사 선수·`players.json`/`teams.json` 계약·상성 전후 결과·한계; 노트북 목차에 04; 테스트 수), `docs/superpowers/specs/2026-10-27-kbo-predict-design.md` (§4.2 보완 방법 확정, §12 item 3 완료 요약, §13 "구현하며 확정한 규칙(3단계)" — 위 판정 목록, §14 "2B/3B/SB 없음" 해결 표기), `docs/superpowers/plans/2026-10-27-stage0-deferred.md` ("3단계 전에" 항목 완료/이월 표시; 새 "4단계 전에" 항목: 상성 피처 라이브 반영 여부, 주간 재학습에 `cluster fit`·`publish` 포함, 2027 유형 재적합 범위, `players.json` 크기가 커지면 시즌별 분할).
- [ ] **Step 1: 수정** — 숫자는 `model_report.json`·`manifest.json`·Task 4 보고서에서 가져온다(지어내지 않는다).
- [ ] **Step 2: 전체 테스트** — `python -X utf8 -m pytest -q` → 모두 PASS, 수를 README에 반영
- [ ] **Step 3: 커밋** — `git commit -m "docs: 3단계 완료 — README·스펙·이월 항목 갱신"`

---

## 컨트롤러 절차

1. Task 1 → 2(재파싱은 백그라운드, 완료 후 리뷰) → 3 → 4 → **4b(컨트롤러 직접)** → 5 → 6 → 7 → 8 → 9. 순차.
2. Task 5 완료 후 Codex 교차 검토 1회(`codex exec --sandbox read-only`): 상성 피처 누수(직전 시즌만·중심 적합 범위), 군집 재현성, 전후 비교 규약, 기록표 매칭 규칙. 반영 항목은 ledger ruling.
3. 최종 전체 리뷰(opus) → 1회 수정 → 재리뷰 → push.
