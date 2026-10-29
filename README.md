# KBO Predict

![daily](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/workflows/daily.yml/badge.svg)
![ci · parity](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/workflows/ci.yml/badge.svg)

KBO 경기의 승패 확률을 매일 예측하고, 예측과 실제 결과를 공개 파일로 기록하는 포트폴리오 프로젝트입니다. 선수 유형 클러스터링을 더해 한 저장소에서 예측과 분석을 함께 다룹니다.

**현재 버전: 승패 모델 v0.2 + 선수 유형 `clusters-2026` (3단계까지 완료)**. 2015~2026 12개 시즌으로 경기 전 피처 26개(팀 19 + 선발 7)를 만들고, 로지스틱 회귀와 LightGBM을 2015~2024로 학습해 2025로 고른 뒤, 학습·선택에 쓰지 않은 2026 시즌으로 평가했습니다(개발 중 2026 지표를 확인한 뒤 캘리브레이션 절차를 한 번 바꾼 경위는 아래 "해석할 때 주의할 점"에 있습니다). 매일 예측에는 그날 발표된 예고 선발투수를 넣습니다. 0단계의 v0.1(팀 피처 3개, 2026 시즌만 학습)은 v0.2로 교체되었습니다.

3단계에서는 박스스코어를 선수·시즌 단위로 합산해 타자 4유형, 투수 4유형을 K-means로 나누고(이름은 사람이 붙임), 유사 선수·2D 지도·소속 확률을 [`players.json`](data/public/players.json)으로, 팀별 요약을 [`teams.json`](data/public/teams.json)으로 내보냅니다. "직전 시즌 유형"으로 만든 상성 피처를 승패 모델에 넣어 보았지만 채택 기준에 못 미쳐, 라이브 모델은 v0.2 그대로입니다(아래 "선수 유형" 절).

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

    → 선수·시즌 집계 (박스스코어 + 경기 페이지 기록표의 2루타·3루타·도루·한글 이름)
      → 선수 유형 군집 clusters-2026  models/clusters.pkl (2015~2025로 맞추고 2026은 배정만)
          → data/public/players.json, teams.json (python -m kbo_predict.cluster publish, 수동 실행)
          → 상성 피처 전후 비교 → model_report.json의 matchup_feature_ablation (채택 안 함)
          → latest.json 선발 블록의 type (직전 시즌 투수 유형)

노트북 (notebooks/)  ← 같은 data/raw를 읽어 수집·피처·모델·유형을 설명 (01~04 완료, 05 예정)
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
| 팀 · 타선 (4) | `obp_diff`, `hr_rate_diff`, `k_rate_diff`, `bb_rate_diff` | 근사 출루율, 타석당 홈런·삼진·볼넷 비율 (2단계 당시 박스스코어에 2루타·3루타가 없어 OPS 대신 사용. 3단계에서 기록표로 보강했지만 v0.2의 피처는 그대로) |
| 팀 · 투수진 (4) | `era_diff`, `fip_diff`, `k9_diff`, `bb9_diff` | 팀 평균자책점, FIP 근사, 9이닝당 삼진·볼넷 |
| 팀 · 컨디션 (2) | `rest_diff`, `bullpen3_diff` | 휴식일, 최근 3일 불펜 투구수 |
| 팀 · 상황 (4) | `home_venue_pct`, `away_venue_pct`, `h2h_home_pct`, `season_progress` | 홈팀의 홈 승률, 원정팀의 원정 승률, 올 시즌 맞대결 승률, 시즌 진행도 |
| 선발 (7) | `starter_known`, `starter_era_diff`, `starter_fip_diff`, `starter_k9_diff`, `starter_bb9_diff`, `starter_ip_diff`, `starter_last3_runs_diff` | 양쪽 선발 기록 유무, 선발의 평균자책점·FIP·9이닝당 삼진·볼넷·누적 이닝·최근 3선발 실점 (당해 + 직전 시즌 합산) |

### 알고리즘과 검증 절차

- **알고리즘 두 가지**: 로지스틱 회귀(결측 중앙값 대치 + `StandardScaler`, 해석용 기준 모델)와 LightGBM(`deterministic=True`, 스레드 1개). 같은 인터페이스로 감싸 학습·예측·요인 분해를 똑같이 부릅니다.
- **시즌 단위 분할**: 2015~2024 학습(7,065경기) → 2025 검증(698경기) → 2026 시험(702경기). 데이터셋은 정규시즌 종료 경기 8,465건이고, 무승부와 LIVE로 멈춘 경기는 뺍니다.
- **2025 검증에서 정하는 것**: LightGBM 트리 수(early stopping, `best_iteration` 52), 캘리브레이션 방법(없음 / Platt / isotonic), 알고리즘(검증 log loss가 낮은 쪽), 유의성 검정의 비교 대상 기준선(검증에서 가장 강했던 규칙). 2026은 어떤 학습·선택에도 쓰지 않습니다.
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

- **2026을 개발 중에 보았습니다.** 2026 시즌은 어떤 학습·선택에도 쓰지 않았습니다. 다만 개발 중에 2026 지표를 확인했고, 캘리브레이션 선택 절차를 한 번 바꿨습니다(R7: 2025 검증 시즌에서 보정기를 맞추고 같은 시즌으로 고르던 방식이 isotonic을 편애하는 표본 내 편향이라서). 이전 절차의 결과는 LightGBM + isotonic, 2026 정확도 .588 / log loss .679(선발 ERA 기준선 대비 McNemar p = .321)였습니다. 위 표는 바꾼 절차의 결과입니다.
- **캘리브레이션**: [`calibration_bins`](data/public/model_report.json)를 보면 예측 40~50% 구간 209경기는 예측 평균 46.2%인데 실제 홈 승률이 38.8%로, 약간 불리한 홈팀을 후하게 봅니다. 50~70% 구간(451경기)은 잘 맞고, 70% 이상 구간은 11경기뿐이라 판단하기 어렵습니다.
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

## 선수 유형

박스스코어를 선수·시즌 단위로 합산하고, 비율 지표로 타자와 투수를 각각 "유형"으로 묶습니다. 집계는 [`src/kbo_predict/player_stats.py`](src/kbo_predict/player_stats.py), 군집은 [`src/kbo_predict/cluster.py`](src/kbo_predict/cluster.py), 사이트 데이터는 [`src/kbo_predict/site_data.py`](src/kbo_predict/site_data.py)에 있고, 노트북 04가 같은 함수를 불러 과정을 설명합니다. 아래 숫자는 [`model_report.json`](data/public/model_report.json)의 `cluster_quality`·`matchup_feature_ablation`과 `models/manifest.json`에서 옮겼습니다.

### 데이터 보강: 2루타·3루타·도루와 한글 이름

박스스코어 표에는 2루타·3루타·도루가 없습니다. 그래서 같은 경기 페이지 아래쪽의 기록표(`2B`, `3B`, `SB`, `HR`, `E` 등, `이름 (1st, 9th inning)` 형식으로 이닝 수 = 개수)를 읽어 박스스코어 타자 행에 보탰습니다. 선수 페이지를 쓰면 선수마다 요청이 필요해(5초 간격으로 며칠) 기록표를 골랐습니다.

- 로컬 HTML 캐시로 **9,362경기**를 다시 파싱했습니다(네트워크 요청 없음). 기존 칸은 바뀌지 않았고, 그 증거로 `features.parquet`의 SHA256이 2단계 값과 같습니다. 캐시가 없는 18경기는 새 칸이 비어 있습니다(None).
- 기록표의 이름(로마자)은 그 경기 박스스코어의 선수와 이렇게 맞춥니다: 정확히 같은 이름 → 단어 접미어("Andy Van Hekken" ↔ 행 "Van Hekken") → 다른 경기에서 투표로 얻은 한글 이름 힌트. 후보가 0명이거나 2명 이상이면 아무에게도 세지 않고 `records_unmatched`에 남깁니다. 지표에 쓰는 라벨(2B/3B/SB/HR)의 미매칭은 127건(2B 65, 3B 5, SB 26, HR 31), 실책·피홈런 투수까지 합치면 457건입니다.
- **한글 이름**: 같은 기록표의 `title` 속성(`2루타: 신종길(1회) 필(1회)`)을 영문 항목과 순서로 맞춰 모으고, 시즌별로 투표해 3표 이상인 가장 최근 시즌에서 최빈 이름이 60% 이상이면 채택합니다(그런 시즌이 없으면 모든 시즌 표를 합쳐 같은 규칙). 그래서 개명한 선수는 최근 이름으로 잡힙니다(예: 한동민 → 한유섬; 1,604명). 개명한 선수 31명은 재파싱 스크립트가 보수적인 규칙으로 별칭을 찾아 [`data/raw/name_aliases.json`](data/raw/name_aliases.json)에 기록합니다(예: 한동민 → 한유섬). `players.json`의 2,918개 선수-시즌 중 2,906개에 한글 이름이 있습니다.

### 지표와 자격

누적 스탯(홈런 개수 등)은 출전 수에 끌려가므로 **비율 지표만** 씁니다. 땅볼/뜬공 기록이 없어 GB%·HR/FB는 뺐습니다.

| 그룹 | 지표 | 정의 |
| --- | --- | --- |
| 타자 (6) | `k_pct`, `bb_pct`, `hr_pct` | 타석당 삼진, 볼넷, 홈런 (타석 = 타수 + 볼넷 + 사구, 희생타 기록 없음) |
| | `iso` | 순수 장타율 = (2루타 + 2·3루타 + 3·홈런) / 타수 |
| | `babip` | 인플레이 타구 타율 = (안타 − 홈런) / (타수 − 삼진 − 홈런) |
| | `sb_rate` | 도루율 = 도루 / (단타 + 볼넷 + 사구), 1루에 나간 기회당 도루 |
| 투수 (5) | `k_pct`, `bb_pct`, `hr_pct` | 상대 타자당 삼진, 볼넷+사구, 피홈런 |
| | `babip` | (피안타 − 피홈런) / (상대 타자 − 삼진 − 볼넷 − 사구 − 피홈런) |
| | `start_share` | 선발 비중 = 선발 등판 / 전체 등판 |

- 투수의 "상대 타자"는 근사값 `bf = 아웃 + 피안타 + 볼넷 + 사구`(`ip_outs + h + bb + hbp`)입니다 — 실책·야수선택으로 나간 타자는 세지 않고, 병살·도루 실패·견제사로 잡은 아웃은 셉니다.

- **자격**: 타자 200타석 이상, 투수 50이닝 이상 또는 구원 등판 30경기 이상(설계 문서의 값 그대로). 정규시즌 FINAL 경기만 셉니다(포스트시즌 제외).
- 2015~2026 자격 선수-시즌은 타자 1,327개(맞춤에 쓴 2015~2025는 1,217개), 투수 1,591개(1,451개)입니다.

### 절차

- **표준화 → K-means**(K=4~7, `random_state=42`, `n_init=10`)를 타자·투수 따로 돌립니다. 중심은 **2015~2025로만 맞추고 2026은 배정만** 합니다(2026은 승패 모델의 홀드아웃이라서). 2026 경기가 쌓여도 유형 정의는 바뀌지 않습니다.
- **K 선택**: `score = 실루엣 + 연도 간 유지율`이 가장 큰 K(동률이면 작은 K). 유지율은 연속 두 시즌 모두 자격인 선수 중 두 해의 유형이 같은 비율로, 유형이 한 해의 운보다 "그 선수다움"을 잡는지 봅니다. 두 그룹 모두 K=4가 뽑혔습니다.

| K | 타자 실루엣 | 타자 유지율 | 타자 점수 | 투수 실루엣 | 투수 유지율 | 투수 점수 |
| --- | --- | --- | --- | --- | --- | --- |
| **4** | **0.1715** | **0.6536** | **0.8251** | **0.2045** | **0.5322** | **0.7367** |
| 5 | 0.1649 | 0.5622 | 0.7271 | 0.1983 | 0.5213 | 0.7196 |
| 6 | 0.1659 | 0.5431 | 0.7090 | 0.1833 | 0.4544 | 0.6378 |
| 7 | 0.1666 | 0.4987 | 0.6653 | 0.1836 | 0.4423 | 0.6259 |

- **유형 번호**: 실행마다 같은 번호가 나오도록 중심 프로파일로 다시 매깁니다(타자는 표준화 HR% 내림차순, 투수는 선발 비중 → K% 내림차순). **이름은 사람이 중심 프로파일을 보고 붙였고** [`config/cluster_labels.yaml`](config/cluster_labels.yaml)에 코드와 분리해 둡니다.
- **2D 지도**: 표준화 공간을 PCA로 2차원에 투영한 좌표(`x`, `y`)입니다. UMAP은 의존성(`umap-learn`, `numba`)이 커서 쓰지 않았습니다.
- **유사 선수**: 같은 표준화 공간에서 코사인 유사도 상위 5개 선수-시즌입니다(연도 무관, 같은 그룹 안, 같은 선수의 다른 시즌은 제외).
- **재현성**: 계산을 단일 스레드로 묶어(`threadpool_limits(1)`) 같은 입력이면 중심·라벨·확률·좌표가 비트 단위로 같습니다. 유형표의 SHA256은 `models/manifest.json`의 `clusters.types_sha256`에 있고, 노트북 04가 마지막에 같은지 확인합니다.

### 유형

인원은 2015~2026 전체 선수-시즌, 대표 선수는 2025 시즌에서 소속 확률이 높은 선수, 지표는 유형 중심(원래 단위)입니다.

| 타자 유형 | 인원 | 대표 선수 | K% | BB% | HR% | ISO | BABIP | 도루율 | 특징 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 파워형 | 299 | 디아즈, 오스틴, 데이비슨 | .190 | .110 | .049 | .229 | .330 | .035 | 홈런·ISO가 가장 높고 볼넷도 가장 많이 고르는 중심 타자 |
| 장타 지향형 | 368 | 김건희, 양석환, 고명준 | .221 | .078 | .026 | .138 | .320 | .035 | 삼진이 가장 많고 볼넷은 적지만 장타를 노리는 타자 |
| 컨택형 | 456 | 허경민, 최재훈, 문성주 | .135 | .097 | .013 | .098 | .320 | .043 | 삼진이 가장 적고 홈런은 드문, 공을 맞히는 타자 |
| 주루형 | 204 | 오태곤, 이원석, 황성빈 | .184 | .081 | .012 | .098 | .330 | .186 | 도루율이 다른 유형의 4배 이상인 발 빠른 타자, 장타는 적음 |

| 투수 유형 | 인원 | 대표 선수 | K% | BB% | HR% | BABIP | 선발 비중 | 특징 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 선발형 | 512 | 후라도, 알칸타라, 임찬규 | .185 | .086 | .020 | .299 | .958 | 등판 대부분이 선발, 볼넷이 가장 적은 긴 이닝형 |
| 스윙맨형 | 301 | 이승현, 김연주, 박주성 | .154 | .097 | .036 | .307 | .285 | 선발과 롱릴리프를 오가며, 삼진이 가장 적고 피홈런이 가장 많음 |
| 제구 불안 불펜형 | 368 | 함덕주, 송재영, 최지민 | .186 | .129 | .019 | .265 | .085 | 거의 구원 등판, 볼넷이 가장 많지만 피BABIP가 가장 낮아 정타는 가장 덜 맞는 불펜 |
| 삼진 불펜형 | 410 | 정해영, 최지강, 윤성빈 | .200 | .101 | .017 | .326 | .043 | 구원 전담, 삼진이 가장 높은 짧은 이닝형 |

### 소속 확률

선수 카드의 "소속 확률"(`membership`, `prob`)은 **상대적 확신도**이지, 실제 빈도에 맞춰 보정된 확률이 아닙니다.

- 먼저 K-means 중심에서 출발하는 GMM(공분산 tied / diag / full)을 맞춰, 가장 높은 GMM 확률의 유형이 K-means 유형과 같은 비율(일치율)을 잽니다. 결과는 타자 tied .843 · diag .527 · full .581, 투수 tied .750 · diag .509 · full .508입니다(`cluster_quality.gmm_candidates`).
- 화면에 보이는 유형과 "가장 높은 소속 확률"이 어긋나면 안 되므로, 일치율이 0.95 미만이면 GMM을 쓰지 않고 중심까지 거리로 만든 소프트맥스 `exp(-d²/(2·s²/D))`를 씁니다(d = 표준화 공간에서 중심까지 거리, s² = 맞춤 행의 군집 내 평균 제곱거리, D = 지표 수). 두 그룹 모두 이 방식(`kmeans_softmax`)이고, 가장 높은 확률의 유형이 항상 표시 유형과 같습니다(`argmax_consistent: true`).

### 유형 상성 피처를 넣으면?

"직전 시즌 유형"으로 상성 피처 9개를 만들어 기존 26개에 더하고, 2단계에서 고른 알고리즘(로지스틱 회귀 + Platt)·분할(2015~2024 / 2025 / 2026)을 그대로 둔 채 피처만 바꿔 비교했습니다. 결과는 `model_report.json`의 `matchup_feature_ablation`입니다.

- `bat_type{0..3}_diff`: 그 시즌 그 팀이 지금까지 쓴 타석을 직전 시즌 유형으로 나눈 비중의 홈 − 원정 차이 (라인업은 경기 전에 모르므로)
- `starter_type{0..3}_diff`: 선발의 직전 시즌 유형 one-hot의 홈 − 원정 차이 (백테스트는 실제 선발, 다른 선발 피처와 같음)
- `types_known`: 양 팀 타석의 절반 이상과 양 선발의 유형을 모두 알면 1

| 비교 | 검증 2025 정확도 | 검증 log loss | 검증 Brier | 시험 2026 정확도 | 시험 log loss | 시험 Brier |
| --- | --- | --- | --- | --- | --- | --- |
| 상성 피처 없음 (26개) | 0.573 | 0.6771 | 0.2421 | 0.594 | 0.6712 | 0.2393 |
| 상성 피처 포함 (35개) | 0.569 | 0.6778 | 0.2424 | 0.591 | 0.6713 | 0.2393 |

- **채택하지 않았습니다(`adopt: false`).** 채택 기준은 "2025 검증 log loss가 0.001 이상 좋아짐"이었는데 오히려 조금 나빠졌습니다. 2026 시험에서 두 모델의 적중 차이도 McNemar p = 0.845로 우연과 구분되지 않습니다. 라이브 모델 v0.2는 바뀌지 않습니다.
- 이유로 보이는 것은 **커버리지**입니다. `types_known`이 1인 경기가 전체의 26.9%, 2026은 15.5%뿐입니다. 2015는 2014 유형이 없어 0%이고, 2026 선발 중 2025 자격 시즌이 있는 투수가 절반 정도입니다.
- 비교 범위: 군집 중심은 2015~2025 선수 성적으로 맞췄으므로(경기 승패는 쓰지 않는 비지도 적합) 2025 검증 비교는 중심이 2025 성적을 이미 본 **전이적(transductive)** 비교이고, 2026 시험 비교만 엄밀한 시간 외 비교입니다(`validation_scope`).

### 해석할 때 주의할 점 (한계)

- **군집 경계가 뚜렷하지 않습니다.** 실루엣이 타자 .17, 투수 .20으로 낮습니다. 선수 분포는 연속적이고, 유형은 그 분포를 나눈 "부드러운" 구분입니다. K=4는 주로 유지율 덕에 뽑혔습니다.
- **ISO는 2루타·3루타·홈런만으로 계산합니다.** 2루타·3루타는 기록표에서 읽으므로, 이름 미매칭(지표 라벨 127건)과 캐시 없는 18경기만큼 조금 낮게 잡힐 수 있습니다.
- **수비·주루 지표가 없습니다.** 박스스코어·기록표에 수비 지표가 없어 "수비형", "공수겸장" 같은 유형은 만들 수 없고, 주루는 도루 개수뿐입니다.
- **2026 유형은 시즌 종료 기준입니다.** 2026 행은 시즌 전체 성적으로 배정했으므로, 시즌 중에 보았다면 유형이 달랐을 수 있습니다.
- **유형 이름은 사람의 판단입니다.** 중심 프로파일을 보고 붙인 이름이라, 같은 숫자를 보고 다른 이름을 붙일 수도 있습니다.
- **라이브 선발 유형은 직전 시즌 자격자만 표시합니다.** 예: 2026-10-29 KIA 선발 Shirakawa는 2024·2026만 자격이고 2025 시즌이 없어 `type`이 null입니다.
- 이적한 선수는 그 시즌 출전 경기가 가장 많은 팀으로 셉니다(`teams.json`의 `roster_types`도 같음).

## 공개 파일

`data/public/`에 있습니다. `latest.json`, `history.csv`, `status.json`은 매 실행마다 갱신되고, `model_report.json`은 고정, `players.json`·`teams.json`은 `python -m kbo_predict.cluster publish`를 돌릴 때만 바뀝니다. 사이트에서는 아래 주소를 기준으로 읽을 수 있습니다.

`https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/`

| 파일 | 내용 |
| --- | --- |
| [`latest.json`](data/public/latest.json) | 오늘 경기 예측: 팀, 구장, 시간, 팀별 예고 선발(`starter`: 이름·ERA·K/9·BB/9·이닝·선발 등판 수, `type`: 직전 시즌 투수 유형 `{id, name}` 또는 직전 시즌 자격이 없으면 null), 홈 승률, 기여도(`contribution_pp`) 상위 5개 요인, 메타(`generated_at`, `commit_sha`, `run_url`, `model_version`, `mode`) |
| [`model_report.json`](data/public/model_report.json) | 모델 성적표(`report-2026`): 두 알고리즘의 검증·시험 지표, 기준선 3종, McNemar 검정, 캘리브레이션 구간표, 피처 중요도, 선발 피처 제외 비교, 선발 소스 표기, 유형 상성 피처 전후 비교(`matchup_feature_ablation`), 군집 품질(`cluster_quality`: K별 실루엣·유지율, 유형별 인원·대표 선수·중심 지표, 소속 확률 방식). 한 번 생성해 고정 (3단계에서 두 블록을 채우려고 다시 만들었고 기존 키의 값은 그대로) |
| [`players.json`](data/public/players.json) | 선수-시즌 2,918개(타자 1,327 + 투수 1,591, 2015~2026). 메타(`generated_at`, `commit_sha`, `model_version: "clusters-2026"`, `fit_seasons`, `note`)와 `types`(그룹별 유형 `id`·`name`·`blurb`), `players[]`: `group`, `season`, `player_id`, `name`(로마자), `name_ko`, `team`, `pos`, `type {id, name}`, `prob`, `membership`(유형별 소속 확률), `x`·`y`(PCA 2D 좌표), `stats`(타자: 타석·타율·출루율·홈런·도루·K%·BB%·ISO·BABIP / 투수: 등판·선발·이닝·ERA·K%·BB%·HR%·BABIP), `similar`(유사 선수 5명 — 서로 다른 선수, 선수마다 가장 비슷한 시즌 하나; `player_id`·`season`·`similarity`만 — 이름은 같은 파일에서 찾음). 압축 JSON 1.77 MB (gzip -9 기준 약 270 KB) |
| [`teams.json`](data/public/teams.json) | 팀-시즌 120개(10구단 × 2015~2026). `season`, `code`, `name`, `games`, `wins`·`losses`·`ties`, `win_pct`(무승부 제외), `home_pct`, `away_pct`, `pyth_pct`(피타고리안), `model_expected`(report-2026 모델의 홀드아웃 예측 평균, 2026만 — 2015~2025는 학습·검증 시즌이라 null), `roster_types`(타자는 타석, 투수는 아웃 수로 가중한 유형 비중), `vs`(상대 팀별 승률) |
| [`history.csv`](data/public/history.csv) | 과거 예측과 결과 기록: date, game_id, home, away, home_win_prob, model_version, predicted_at, status, winner, correct |
| [`status.json`](data/public/status.json) | 파이프라인 상태: generated_at, run_url, commit_sha, mode, next_game_date, games_today, model_version (경기가 없는 날도 갱신) |

## 자동 실행

[`.github/workflows/daily.yml`](.github/workflows/daily.yml)이 매일 09:07, 17:07 KST(UTC `7 0`, `7 8`)와 수동 실행(`workflow_dispatch`)으로 [`scripts/run_pipeline.py`](scripts/run_pipeline.py)를 돌립니다. 결과는 `github-actions[bot]`이 `data/raw`, `data/public`을 `auto: predictions YYYY-MM-DD-HHMM` 메시지로 커밋합니다. 수집에 실패한 경기가 있으면(`collect_errors`가 비어 있지 않으면) `collect-failure` 라벨의 GitHub 이슈를 새로 열거나 기존 이슈에 코멘트합니다 ([`scripts/collect_errors.py`](scripts/collect_errors.py)). 첫 실제 실행: [Actions run](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/runs/40533547898).

[`.github/workflows/ci.yml`](.github/workflows/ci.yml)은 push·PR마다 빠른 테스트(`pytest -m "not slow"`)와 parity 검사 [`scripts/check_parity.py --quick`](scripts/check_parity.py)를 돌립니다(위 `ci · parity` 배지). parity 검사는 커밋된 산출물(피처 parquet·유형 CSV 해시, `model_report.json`, 모델 pkl의 예측, `players.json`·`teams.json`, 되감기 3일)을 원본 데이터만으로 다시 만들어 같은지 표로 보여 주고, 다르면 실패합니다(`--quick` 없이 돌리면 노트북 02~05 실행까지). [`.github/workflows/weekly_retrain.yml`](.github/workflows/weekly_retrain.yml)은 매주 월요일 03:07 KST에 라이브 모델 재학습(`train_win live --skip-if-same`: 예측이 그대로면 쓰지 않음)·군집 재계산(`cluster compare`로 커밋본과 같은 유형 정의일 때만 반영)·사이트 JSON 재발행·parity를 돌려 `auto: weekly retrain YYYY-MM-DD`로 커밋하고, 실패하면 `parity-failure` 이슈를 엽니다.

## 데이터

2015~2026 시즌을 수집해 `data/raw/`에 파싱된 JSON으로 커밋합니다. 원본 HTML은 git에 넣지 않고 로컬 캐시 `data/cache/html/`(gitignore)에만 둡니다.

```
data/raw/{season}/games.jsonl                    주간 일정 행 (경기당 한 줄)
data/raw/{season}/boxscores/{YYYY-MM}.jsonl.gz   월별 박스스코어 (종료된 경기; 기록표의 2루타·3루타·도루, names_ko, records_unmatched 포함)
data/raw/{season}/starters.jsonl                 예고 선발 (경기당 한 줄, 가장 최근 발표; 2026 포스트시즌부터)
data/raw/name_aliases.json                       개명 선수 한글 이름 별칭 (31명)
data/processed/features.parquet                  피처 데이터셋 (gitignore, 아래 "로컬 실행"으로 다시 만듦)
data/processed/matchup.parquet                   상성 피처 (gitignore, SHA256은 models/manifest.json의 report.matchup_sha256)
models/clusters.pkl                              선수 유형 군집 묶음 clusters-2026 (커밋)
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

`notebooks/`에 단계별 설명 노트북을 둡니다. 01~04는 실행 결과를 포함하고 네트워크 없이 실행되며, `tests/test_notebooks.py`가 실행을 검증합니다. 노트북은 로직을 복사하지 않고 `src/kbo_predict/`의 같은 함수를 부르며, 02는 만든 parquet가 모델 학습에 쓴 파일과 SHA256까지 같은지, 03은 결과가 `data/public/model_report.json`과 같은지, 04는 유형표가 `models/manifest.json`의 `types_sha256`과, 다시 만든 상성 피처가 `matchup_sha256`과 같은지 마지막에 확인합니다. 03은 02가 저장한 `data/processed/features.parquet`를 읽으므로 02를 먼저 실행합니다.

| 번호 | 노트북 | 짝 `.py` | 상태 |
| --- | --- | --- | --- |
| 01 | [데이터 수집과 살펴보기](notebooks/01_데이터_수집과_살펴보기.ipynb) | `collect.py` | 완료 |
| 02 | [피처 만들기](notebooks/02_피처_만들기.ipynb) | `features.py` | 완료 |
| 03 | [승패 예측 모델](notebooks/03_승패_예측_모델.ipynb) | `train_win.py` | 완료 |
| 04 | [선수 유형 클러스터링](notebooks/04_선수_유형_클러스터링.ipynb) | `cluster.py` | 완료 |
| 05 | 자동화와 parity 검증 | | 예정 |

05의 이름은 바뀔 수 있습니다.

## 로컬 실행

```bash
pip install -r requirements.txt && pip install -e .
python -m kbo_predict.collect --from 2026-03-20 --to 2026-11-05   # 약 65분 (요청 간 5초)
python -m kbo_predict.features --out data/processed/features.parquet   # 2015~2026 피처 데이터셋
python -m kbo_predict.cluster fit       # 선수 유형 군집 → models/clusters.pkl, manifest의 clusters 항목
python -m kbo_predict.features --matchup-out data/processed/matchup.parquet   # 직전 시즌 유형 상성 피처
python -m kbo_predict.train_win report --force --matchup data/processed/matchup.parquet --clusters models/clusters.pkl   # report-2026 학습·평가 → model_report.json, models/report-2026.pkl (고정된 보고서를 다시 만들 때만)
python -m kbo_predict.train_win live     # 라이브 v0.2 → models/win_model.pkl (report를 먼저 실행)
python -m kbo_predict.cluster publish   # players.json, teams.json (report-2026.pkl과 features.parquet 필요)
python scripts/run_pipeline.py [--date YYYY-MM-DD] [--no-fetch]
```

- Windows에서는 한글 출력 때문에 `python -X utf8 …`로 실행합니다.
- `model_report.json`은 한 번 만든 뒤 고정합니다. 이미 있으면 `report`는 `--force` 없이 거부합니다. `live`는 보고서에서 선택된 알고리즘·보정 방법·LightGBM 트리 수만 읽으므로, 경기가 쌓여 parquet가 바뀌어도 다시 학습할 수 있습니다.
- `train_win`의 두 명령은 `models/manifest.json`에 **모델별로** 모델 파일 SHA256·버전과 그 모델을 만든 parquet의 SHA256을 기록합니다(각 명령은 자기 항목만 갱신). parquet는 커밋하지 않으므로 이 해시로 같은 데이터인지 확인합니다.
- 모델 의존성은 `lightgbm==4.7.0`, `pyarrow==19.0.1`(numpy 1.x와 호환되는 버전)입니다. 요인 분해는 LightGBM 내장 TreeSHAP을 쓰므로 `shap` 패키지는 필요 없습니다.
- `train_win report`를 `--matchup`·`--clusters` 없이 돌리면 `model_report.json`의 `matchup_feature_ablation`·`cluster_quality`가 null로 돌아갑니다. 보고서를 다시 만들 때는 위처럼 두 옵션을 함께 줍니다.
- 박스스코어의 2루타·3루타·도루·한글 이름은 로컬 HTML 캐시를 다시 파싱해 채웠습니다: `python -X utf8 scripts/reparse_boxscores.py --cache data/cache/html --seasons 2015-2026 [--dry-run] [--infer-aliases]` (요청 없음, 기존 칸 불변 검사). 일일 수집도 새 경기의 기록표를 같은 파서로 읽지만, 한글 이름 힌트와 별칭 없이 읽습니다.
- `config/cluster_labels.yaml`(유형 이름)은 패키지 위치 기준으로 찾으므로 어느 폴더에서 실행해도 같은 이름이 나옵니다. 군집은 단일 스레드로 계산해 같은 기계에서는 비트 단위로 재현되지만, 다른 BLAS(예: Linux의 Actions)에서는 마지막 자리가 다를 수 있어 커밋된 `models/clusters.pkl`이 기준입니다.

테스트는 `python -X utf8 -m pytest -q`입니다 (261개, 노트북 실행 포함 약 2분).

## 데이터 출처

- 데이터 출처: [MyKBOStats](https://mykbostats.com) (비공식 팬 사이트). robots.txt의 `Crawl-delay: 5`를 지켜 요청 간 5초를 두고, 주간 일정 페이지, 경기 박스스코어 페이지(하단 기록표 포함), 예정 경기 페이지의 예고 선발("Starting pitchers" 섹션)을 파싱합니다. 선수 이름은 사이트 표기대로 로마자이고, 한글 이름(`name_ko`)은 같은 사이트 기록표의 한글 제목에서 모았습니다. 개인 학습용입니다.
- KBO 공식 사이트는 약관상 크롤링이 금지되어 사용하지 않습니다.
- 네이버 스포츠의 내부 API는 Python 클라이언트를 차단해(TLS/UA 수준) 수집 대상에서 뺐습니다. 우회는 시도하지 않았습니다.

## 로드맵

1. ~~2015~2025 데이터 백필, 노트북 01~~ (완료)
2. ~~선발투수 정보 소스 확보, 피처 26개, LightGBM, 확률 보정, 요인 분해(SHAP), report/live 두 모델 분리, 노트북 02·03~~ (완료)
3. ~~선수 유형 클러스터링, 유형 상성 피처 전후 비교, `players.json`·`teams.json`, 노트북 04~~ (완료)
4. py와 ipynb 결과 동일성 검증(parity), 주간 재학습, 되감기 모드
5. Genspark + GitHub Pages 사이트
6. README 정리와 한 달 무인 운영

## 문서

- 설계 문서: [docs/superpowers/specs/2026-10-27-kbo-predict-design.md](docs/superpowers/specs/2026-10-27-kbo-predict-design.md)
- 구현 계획: [0단계 수직 슬라이스](docs/superpowers/plans/2026-10-27-stage0-vertical-slice.md), [1단계 백필·노트북 01](docs/superpowers/plans/2026-10-28-stage1-backfill-notebook01.md), [2단계 피처 + 승패 모델](docs/superpowers/plans/2026-10-29-stage2-win-model.md), [3단계 선수 유형 클러스터링](docs/superpowers/plans/2026-10-29-stage3-clustering.md)
- 이월 항목: [docs/superpowers/plans/2026-10-27-stage0-deferred.md](docs/superpowers/plans/2026-10-27-stage0-deferred.md)
- 데이터 조사: [docs/research/kbo-data-sources.md](docs/research/kbo-data-sources.md)
- 디자인 시스템: [DESIGN_clay.md](DESIGN_clay.md)

저장소: https://github.com/kimminseo2323-prog/2610_KBO_predict
