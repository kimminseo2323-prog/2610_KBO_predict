# KBO Predict

![daily](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/workflows/daily.yml/badge.svg)

KBO 경기의 승패 확률을 매일 예측하고, 예측과 실제 결과를 공개 파일로 기록하는 포트폴리오 프로젝트입니다. 이후 단계에서 선수 유형 클러스터링을 더해 한 저장소에서 예측과 분석을 함께 다룰 예정입니다.

**현재 버전: v0.2 (2단계: 피처 + 승패 모델)**. 2015~2026 12개 시즌으로 경기 전 피처 26개(팀 19 + 선발 7)를 만들고, 로지스틱 회귀와 LightGBM을 2015~2024로 학습해 2025로 고른 뒤, 한 번도 보지 않은 2026 시즌으로 평가했습니다. 매일 예측에는 그날 발표된 예고 선발투수를 넣습니다. 0단계의 v0.1(팀 피처 3개, 2026 시즌만 학습)은 v0.2로 교체되었습니다.

## 아키텍처

```
수집 (MyKBOStats: 주간 일정 · 박스스코어 · 예정 경기의 예고 선발)
  → data/raw/{season}/  games.jsonl, boxscores/{YYYY-MM}.jsonl.gz, starters.jsonl
    → 피처 26개 (경기 날짜 이전 기록만 사용)
        data/processed/features.parquet  (gitignore, SHA256은 models/manifest.json)
      → 모델 두 벌
          평가용 report-2026  models/report-2026.pkl  → data/public/model_report.json (한 번 생성해 고정)
          라이브 v0.2         models/win_model.pkl    (2015~2026 전체 학습)
        → GitHub Actions (매일 09:07, 17:07 KST, 수집 + 추론만)
          → data/public/*.json, *.csv
            → 사이트 (예정)

노트북 (notebooks/)  ← 같은 data/raw를 읽어 수집·피처·모델을 설명 (01~03 완료, 04~05 예정)
```

- 수집 결과는 `data/raw/{season}/`에 파싱된 형태로 커밋합니다 (2015~2026). 자세한 구조와 시즌별 경기 수는 아래 "데이터" 절에 있습니다.
- 예고 선발은 매 실행마다 예정 경기 페이지의 "Starting pitchers" 섹션에서 읽어 `data/raw/{season}/starters.jsonl`에 경기당 한 줄(가장 최근 발표)로 저장합니다.
- 포스트시즌(10-14 이후) 경기도 파이프라인이 실시간으로 예측합니다.

## 모델

### 피처 26개

모든 피처는 해당 경기 날짜 **전날까지** 끝난 경기로만 계산합니다(누수 방지 테스트 포함). `_diff`는 홈 − 원정입니다. 정의는 [`src/kbo_predict/features.py`](src/kbo_predict/features.py)와 노트북 02에 있습니다.

| 묶음 | 피처 | 의미 |
| --- | --- | --- |
| 팀 · 성적 (5) | `win_pct_diff`, `last10_diff`, `run_diff_diff`, `pyth_diff`, `prev_season_diff` | 시즌 승률, 최근 10경기, 경기당 득실차, 피타고리안 기대 승률, 지난 시즌 승률 |
| 팀 · 타선 (4) | `obp_diff`, `hr_rate_diff`, `k_rate_diff`, `bb_rate_diff` | 근사 출루율, 타석당 홈런·삼진·볼넷 비율 (박스스코어에 2루타·3루타가 없어 OPS 대신 사용) |
| 팀 · 투수진 (4) | `era_diff`, `fip_diff`, `k9_diff`, `bb9_diff` | 팀 평균자책점, FIP 근사, 9이닝당 삼진·볼넷 |
| 팀 · 컨디션 (2) | `rest_diff`, `bullpen3_diff` | 휴식일, 최근 3일 불펜 투구수 |
| 팀 · 상황 (4) | `home_venue_pct`, `away_venue_pct`, `h2h_home_pct`, `season_progress` | 홈팀의 홈 승률, 원정팀의 원정 승률, 올 시즌 맞대결 승률, 시즌 진행도 |
| 선발 (7) | `starter_known`, `starter_era_diff`, `starter_fip_diff`, `starter_k9_diff`, `starter_bb9_diff`, `starter_ip_diff`, `starter_last3_runs_diff` | 양쪽 선발 기록 유무, 선발의 평균자책점·FIP·9이닝당 삼진·볼넷·누적 이닝·최근 3선발 실점 (당해 + 직전 시즌 합산) |

### 알고리즘과 검증 절차

- **알고리즘 두 가지**: 로지스틱 회귀(결측 중앙값 대치 + `StandardScaler`, 해석용 기준 모델)와 LightGBM(`deterministic=True`, 스레드 1개). 같은 인터페이스로 감싸 학습·예측·요인 분해를 똑같이 부릅니다.
- **시즌 단위 분할**: 2015~2024 학습(7,065경기) → 2025 검증(698경기) → 2026 시험(702경기). 데이터셋은 정규시즌 종료 경기 8,465건이고, 무승부와 LIVE로 멈춘 경기는 뺍니다.
- **2025 검증에서 정하는 것**: LightGBM 트리 수(early stopping, `best_iteration` 52), 캘리브레이션 방법(없음 / Platt / isotonic), 알고리즘(검증 log loss가 낮은 쪽), 유의성 검정의 비교 대상 기준선(검증에서 가장 강했던 규칙). 2026은 마지막 평가에 **한 번만** 씁니다.
- **캘리브레이션**: 보정기는 학습 시즌들의 leave-one-season-out 예측(각 시즌을 빼고 학습한 모델로 그 시즌을 예측)으로 맞추고, 2025는 세 방법의 log loss 점수만 매깁니다. 두 알고리즘 모두 Platt이 뽑혔습니다(로지스틱 회귀 검증 log loss: 없음 0.6772, Platt 0.6771, isotonic 0.6782).
- **모델 두 벌**: 평가용 `report-2026`(2015~2024 학습)이 [`model_report.json`](data/public/model_report.json)을 한 번 만들고 고정합니다. 매일 쓰는 라이브 v0.2는 같은 알고리즘·보정 방법을 2015~2026 전체로 다시 학습하고, 보정기는 전체 시즌의 leave-one-season-out 예측으로 맞춥니다.

### 2026 시즌 성적 (702경기, 학습에 쓰지 않은 홀드아웃)

값은 [`data/public/model_report.json`](data/public/model_report.json)에서 옮겼습니다.

| 모델 / 규칙 | 정확도 | log loss | Brier |
| --- | --- | --- | --- |
| **로지스틱 회귀 + Platt (선택)** | **0.594** | **0.671** | **0.239** |
| LightGBM + Platt | 0.591 | 0.673 | 0.240 |
| 선발 피처 제외 (팀 19개, 로지스틱 회귀 + Platt) | 0.547 | 0.687 | 0.247 |
| 기준선: 홈팀이 항상 승리 | 0.514 | | |
| 기준선: 시즌 승률 높은 팀이 승리 | 0.554 | | |
| 기준선: 선발 ERA 낮은 팀이 승리 | 0.567 | | |

선택 모델이 기준선보다 나은 것이 우연인지 McNemar 검정으로 확인했습니다 (모델 417경기 적중).

| 비교 대상 | 기준선 적중 | McNemar p |
| --- | --- | --- |
| 선발 ERA 낮은 팀 (2025 검증에서 미리 정한 비교 대상) | 398 | 0.215 |
| 시즌 승률 높은 팀 | 389 | 0.079 |
| 홈팀이 항상 승리 | 361 | < 0.001 |

해석할 때 주의할 점입니다.

- **목표에는 아직 못 미칩니다.** 설계 목표는 "가장 강한 기준선 +3%p 이상, 통계적으로 유의"입니다. 선발 ERA 기준선 대비 +2.7%p(19경기)이고 p = 0.215라서, 702경기 한 시즌으로는 우연과 구분되지 않습니다. 홈팀 기준선은 확실히 넘고(p < 0.001), 승률 기준선 대비는 경계선(p = 0.079)입니다.
- **선발 가정**: 백테스트(학습·검증·시험)의 선발 피처는 박스스코어의 **실제 선발**(투수 순서 1번)로 만듭니다. 즉 위 숫자는 "경기 전에 선발을 정확히 안다"는 가정 위의 값입니다. 라이브 예측은 MyKBOStats 예정 경기 페이지의 **예고 선발**을 쓰므로, 예고와 실제가 다른 경기에서는 백테스트보다 성적이 낮을 수 있습니다.
- 하한선으로 선발 피처를 뺀 모델(팀 피처 19개, 같은 절차)도 함께 적었습니다. 정확도 0.547로 승률·선발 ERA 규칙보다 약합니다(홈팀 기준선 0.514보다는 높음). 선발 피처가 성적에 크게 기여한다는 뜻입니다.
- log loss 0.671은 동전 던지기(0.693)보다 낫지만 큰 차이는 아닙니다. 야구 승패 예측의 현실적 상한은 60% 초반으로 보고 있습니다(설계 문서의 가정).
- LightGBM은 로지스틱 회귀와 거의 같은 성적이라, 해석이 쉬운 로지스틱 회귀가 검증 log loss(0.6771 대 0.6796)로 뽑혔습니다.

### 요인 분해

사이트의 "승률을 가른 요인" 카드용으로, 경기마다 확률을 피처별 기여로 나눕니다.

- 로지스틱 회귀는 (표준화 값 × 계수), LightGBM은 내장 TreeSHAP(`pred_contrib=True`, `shap` 패키지 없이)로 보정 전 로그 오즈를 피처별 기여 + 기본값으로 **정확히** 나눕니다. 기본값은 "기본 홈 어드밴티지"로 표시합니다.
- 퍼센트포인트로 바꿀 때는 `기여(로그 오즈) × Platt 기울기 × p(1−p) × 100`을 씁니다. 1차 근사라서 요인 합이 확률 차이와 정확히 같지는 않습니다.
- 기본값을 포함해 절댓값이 큰 5개를 `latest.json`의 `factors`에 넣습니다. 예: 2026-10-29 포스트시즌 KIA(홈) 대 삼성, 홈 승률 44.6% — 선발 누적 이닝 차이 −2.9pp, 기본 홈 어드밴티지 +2.4pp, 타선 삼진 비율 차이 −1.5pp, 선발 9이닝당 볼넷 차이 −1.2pp, 지난 시즌 승률 차이 −1.1pp.

## 공개 파일

`data/public/`에 매 실행마다 갱신됩니다. 사이트에서는 아래 주소를 기준으로 읽을 수 있습니다.

`https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/`

| 파일 | 내용 |
| --- | --- |
| [`latest.json`](data/public/latest.json) | 오늘 경기 예측: 팀, 구장, 시간, 팀별 예고 선발(`starter`: 이름·ERA·K/9·BB/9·이닝·선발 등판 수), 홈 승률, 기여도(`contribution_pp`) 상위 5개 요인, 메타(`generated_at`, `commit_sha`, `run_url`, `model_version`, `mode`) |
| [`model_report.json`](data/public/model_report.json) | 모델 성적표(`report-2026`): 두 알고리즘의 검증·시험 지표, 기준선 3종, McNemar 검정, 캘리브레이션 구간표, 피처 중요도, 선발 피처 제외 비교, 선발 소스 표기. 한 번 생성해 고정 |
| [`history.csv`](data/public/history.csv) | 과거 예측과 결과 기록: date, game_id, home, away, home_win_prob, model_version, predicted_at, status, winner, correct |
| [`status.json`](data/public/status.json) | 파이프라인 상태: generated_at, run_url, commit_sha, mode, next_game_date, games_today, model_version (경기가 없는 날도 갱신) |

## 자동 실행

[`.github/workflows/daily.yml`](.github/workflows/daily.yml)이 매일 09:07, 17:07 KST(UTC `7 0`, `7 8`)와 수동 실행(`workflow_dispatch`)으로 [`scripts/run_pipeline.py`](scripts/run_pipeline.py)를 돌립니다. 결과는 `github-actions[bot]`이 `data/raw`, `data/public`을 `auto: predictions YYYY-MM-DD-HHMM` 메시지로 커밋합니다. 수집에 실패한 경기가 있으면(`collect_errors`가 비어 있지 않으면) `collect-failure` 라벨의 GitHub 이슈를 새로 열거나 기존 이슈에 코멘트합니다 ([`scripts/collect_errors.py`](scripts/collect_errors.py)). 첫 실제 실행: [Actions run](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/runs/40533547898).

## 데이터

2015~2026 시즌을 수집해 `data/raw/`에 파싱된 JSON으로 커밋합니다. 원본 HTML은 git에 넣지 않고 로컬 캐시 `data/cache/html/`(gitignore)에만 둡니다.

```
data/raw/{season}/games.jsonl                    주간 일정 행 (경기당 한 줄)
data/raw/{season}/boxscores/{YYYY-MM}.jsonl.gz   월별 박스스코어 (종료된 경기)
data/raw/{season}/starters.jsonl                 예고 선발 (경기당 한 줄, 가장 최근 발표; 2026 포스트시즌부터)
data/processed/features.parquet                  피처 데이터셋 (gitignore, 아래 "로컬 실행"으로 다시 만듦)
```

박스스코어를 월별로 나눈 이유는 매일 실행에서 이번 달 파일만 바뀌게 해 저장소가 커지는 속도를 줄이기 위해서입니다.

기준일: 2026-10-29. 2026 행의 수치는 매일 실행으로 늘어나므로 이 날짜 기준입니다.

| 시즌 | 전체 행 | 정규시즌 FINAL | 정규시즌 LIVE(멈춤) | 무승부 | 박스스코어 |
| --- | --- | --- | --- | --- | --- |
| 2015 | 886 | 720 | 0 | 5 | 795 |
| 2016 | 887 | 720 | 0 | 7 | 815 |
| 2017 | 836 | 720 | 0 | 11 | 793 |
| 2018 | 818 | 720 | 0 | 6 | 767 |
| 2019 | 838 | 720 | 0 | 7 | 769 |
| 2020 | 836 | 720 | 0 | 13 | 763 |
| 2021 | 921 | 720 | 0 | 50 | 767 |
| 2022 | 868 | 719 | 1 | 12 | 801 |
| 2023 | 902 | 719 | 1 | 12 | 800 |
| 2024 | 868 | 720 | 0 | 10 | 783 |
| 2025 | 893 | 720 | 0 | 22 | 778 |
| 2026 | 829 | 718 | 2 | 16 | 749 |

- 전체 행은 시범경기·취소·포스트시즌 행을 포함합니다. 박스스코어는 포스트시즌을 포함한 종료 경기 전체입니다.
- 정규시즌 FINAL + LIVE(멈춤) = 720경기입니다 (10구단 × 144경기 ÷ 2). LIVE(멈춤)는 사이트가 끝내 종료로 바꾸지 않은 경기로, 점수를 추측해 채우지 않고 그대로 두며 학습에서 제외합니다. 2024-10-01 5위 결정전은 정규시즌에서 뺍니다.
- 2021년은 후반기 연장전이 폐지되어 무승부가 50건으로 많습니다.
- 2025년부터는 연장이 11회까지로 줄어 무승부가 다시 늘었습니다 (22건).
- 시즌별 정규시즌 날짜 범위는 [`src/kbo_predict/seasons.py`](src/kbo_predict/seasons.py)에 있고, [`scripts/season_bounds.py`](scripts/season_bounds.py)로 데이터에서 도출했습니다. 등록되지 않은 시즌은 03-01~10-31로 보고 경고를 남깁니다.
- 옛 구단명은 현재 코드로 매핑합니다: Nexen Heroes → WO (2015~2018), SK Wyverns → SK (2015~2020).

수집이 불안정한 경우도 다룹니다. 경기 단위 실패는 `status.json`의 `collect_errors`에 기록하고 실행을 이어 가며, 오래 LIVE로 멈춘 경기는 경기 페이지가 종료이고 양 팀 점수가 있을 때만 보정합니다.

## 노트북

`notebooks/`에 단계별 설명 노트북을 둡니다. 01~03은 실행 결과를 포함하고 네트워크 없이 실행되며, `tests/test_notebooks.py`가 실행을 검증합니다. 노트북은 로직을 복사하지 않고 `src/kbo_predict/`의 같은 함수를 부르며, 02는 만든 parquet가 모델 학습에 쓴 파일과 SHA256까지 같은지, 03은 결과가 `data/public/model_report.json`과 같은지 마지막에 확인합니다. 03은 02가 저장한 `data/processed/features.parquet`를 읽으므로 02를 먼저 실행합니다.

| 번호 | 노트북 | 짝 `.py` | 상태 |
| --- | --- | --- | --- |
| 01 | [데이터 수집과 살펴보기](notebooks/01_데이터_수집과_살펴보기.ipynb) | `collect.py` | 완료 |
| 02 | [피처 만들기](notebooks/02_피처_만들기.ipynb) | `features.py` | 완료 |
| 03 | [승패 예측 모델](notebooks/03_승패_예측_모델.ipynb) | `train_win.py` | 완료 |
| 04 | 선수 유형 | | 예정 |
| 05 | 자동화와 parity 검증 | | 예정 |

04~05의 이름은 바뀔 수 있습니다.

## 로컬 실행

```bash
pip install -r requirements.txt && pip install -e .
python -m kbo_predict.collect --from 2026-03-20 --to 2026-11-05   # 약 65분 (요청 간 5초)
python -m kbo_predict.features --out data/processed/features.parquet   # 2015~2026 피처 데이터셋
python -m kbo_predict.train_win report   # report-2026 학습·평가 → model_report.json, models/report-2026.pkl
python -m kbo_predict.train_win live     # 라이브 v0.2 → models/win_model.pkl (report를 먼저 실행)
python scripts/run_pipeline.py [--date YYYY-MM-DD] [--no-fetch]
```

- Windows에서는 한글 출력 때문에 `python -X utf8 …`로 실행합니다.
- `train_win`의 두 명령은 `models/manifest.json`에 피처 parquet와 모델 파일의 SHA256을 기록합니다. parquet는 커밋하지 않으므로 이 해시로 같은 데이터인지 확인합니다.
- 모델 의존성은 `lightgbm==4.7.0`, `pyarrow==19.0.1`(numpy 1.x와 호환되는 버전)입니다. 요인 분해는 LightGBM 내장 TreeSHAP을 쓰므로 `shap` 패키지는 필요 없습니다.

테스트는 `python -X utf8 -m pytest -q`입니다 (168개, 노트북 실행 포함 약 1분).

## 데이터 출처

- 데이터 출처: [MyKBOStats](https://mykbostats.com) (비공식 팬 사이트). robots.txt의 `Crawl-delay: 5`를 지켜 요청 간 5초를 두고, 주간 일정 페이지, 경기 박스스코어 페이지, 예정 경기 페이지의 예고 선발("Starting pitchers" 섹션)을 파싱합니다. 선수 이름은 사이트 표기대로 로마자입니다. 개인 학습용입니다.
- KBO 공식 사이트는 약관상 크롤링이 금지되어 사용하지 않습니다.
- 네이버 스포츠의 내부 API는 Python 클라이언트를 차단해(TLS/UA 수준) 수집 대상에서 뺐습니다. 우회는 시도하지 않았습니다.

## 로드맵

1. ~~2015~2025 데이터 백필, 노트북 01~~ (완료)
2. ~~선발투수 정보 소스 확보, 피처 26개, LightGBM, 확률 보정, 요인 분해(SHAP), report/live 두 모델 분리, 노트북 02·03~~ (완료)
3. 선수 유형 클러스터링, 유형 상성 피처 전후 비교
4. py와 ipynb 결과 동일성 검증(parity), 주간 재학습, 되감기 모드
5. Genspark + GitHub Pages 사이트
6. README 정리와 한 달 무인 운영

## 문서

- 설계 문서: [docs/superpowers/specs/2026-10-27-kbo-predict-design.md](docs/superpowers/specs/2026-10-27-kbo-predict-design.md)
- 구현 계획: [0단계 수직 슬라이스](docs/superpowers/plans/2026-10-27-stage0-vertical-slice.md), [1단계 백필·노트북 01](docs/superpowers/plans/2026-10-28-stage1-backfill-notebook01.md), [2단계 피처 + 승패 모델](docs/superpowers/plans/2026-10-29-stage2-win-model.md)
- 이월 항목: [docs/superpowers/plans/2026-10-27-stage0-deferred.md](docs/superpowers/plans/2026-10-27-stage0-deferred.md)
- 데이터 조사: [docs/research/kbo-data-sources.md](docs/research/kbo-data-sources.md)
- 디자인 시스템: [DESIGN_clay.md](DESIGN_clay.md)

저장소: https://github.com/kimminseo2323-prog/2610_KBO_predict
