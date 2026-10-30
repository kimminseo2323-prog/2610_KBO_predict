# KBO Predict

![daily](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/workflows/daily.yml/badge.svg)
![ci · parity](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/workflows/ci.yml/badge.svg)
![weekly retrain](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/workflows/weekly_retrain.yml/badge.svg)
![pages](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/workflows/pages.yml/badge.svg)

KBO 경기의 승패 확률을 매일 예측하고, 예측과 실제 결과를 공개 파일로 기록하는 포트폴리오 프로젝트입니다. 선수 유형 클러스터링을 더해 한 저장소에서 예측과 분석을 함께 다룹니다.

**현재 버전: 승패 모델 v0.2 + 선수 유형 `clusters-2026` + 팀 모델 `team-2026` + 사이트 (5단계까지 완료)**. 2015~2026 12개 시즌으로 경기 전 피처 26개(팀 19 + 선발 7)를 만들고, 로지스틱 회귀와 LightGBM을 2015~2024로 학습해 2025로 고른 뒤, 학습·선택에 쓰지 않은 2026 시즌으로 평가했습니다(개발 중 2026 지표를 확인한 뒤 캘리브레이션 절차를 한 번 바꾼 경위는 아래 "해석할 때 주의할 점"에 있습니다). 매일 예측에는 그날 발표된 예고 선발투수를 넣습니다. 0단계의 v0.1(팀 피처 3개, 2026 시즌만 학습)은 v0.2로 교체되었습니다.

3단계에서는 박스스코어를 선수·시즌 단위로 합산해 타자 4유형, 투수 4유형을 K-means로 나누고(이름은 사람이 붙임), 유사 선수·2D 지도·소속 확률을 [`players.json`](data/public/players.json)으로, 팀별 요약을 [`teams.json`](data/public/teams.json)으로 내보냅니다. "직전 시즌 유형"으로 만든 상성 피처를 승패 모델에 넣어 보았지만 채택 기준에 못 미쳐, 라이브 모델은 v0.2 그대로입니다(아래 "선수 유형" 절).

4단계에서는 저장소가 사람 손 없이 돌아가게 했습니다. GitHub Actions 워크플로 3개가 매일 수집·추론, 매주 재학습·군집 재계산, push·PR마다 테스트와 parity 검사(커밋된 산출물을 원본 데이터로 다시 만들어 값이 같은지)를 맡습니다. 2026 정규시즌 165일을 날짜별로 다시 예측한 되감기 JSON([`rewind/2026/`](data/public/rewind/2026/index.json))과, 가을야구 진출·포스트시즌 시리즈 확률을 몬테카를로로 계산하는 `outlook` 블록도 만들었습니다(아래 "자동화와 되감기" 절). 노트북 05가 오늘 경기 하나를 처음부터 끝까지 따라갑니다.

5단계에서는 이 공개 파일을 읽는 정적 사이트 4페이지를 만들어 GitHub Pages로 띄웠습니다(아래 "사이트" 절).

## 사이트

**https://kimminseo2323-prog.github.io/2610_KBO_predict/**

| 페이지 | 보여 주는 것 |
| --- | --- |
| [오늘의 경기](https://kimminseo2323-prog.github.io/2610_KBO_predict/) (`site/index.html`) | 오늘 경기의 홈팀 승리 확률(원정 핑크 / 홈 틸 매치업 카드), 확률을 가른 요인 5개, 모델 적중률, 두 선발의 유형, 시리즈·가을야구 전망, 선수 유형 지도, 최근 예측. 경기가 없는 날(비시즌)에는 2026 시즌 되감기 슬라이더로 열려 "그날 모델의 예측과 실제 결과"를 보여 줍니다 |
| [팀](https://kimminseo2323-prog.github.io/2610_KBO_predict/teams.html) (`site/teams.html`) | 시즌별 순위표(실제·피타고리안·모델 기대 승률), 로스터 유형 구성, 상대 전적 격자, 2026 가을야구 확률 되감기 |
| [선수](https://kimminseo2323-prog.github.io/2610_KBO_predict/players.html) (`site/players.html`) | 2015~2026 타자·투수 유형 지도(PCA 2D), 선수 카드(유형·소속 확신도·기록), 비슷한 선수 5명 |
| [모델 성적표](https://kimminseo2323-prog.github.io/2610_KBO_predict/report.html) (`site/report.html`) | report-2026의 2026 홀드아웃 성적과 기준선·유의성, 신뢰도 곡선, 피처 중요도, 빼고 더해 본 모델, 선수 유형 품질, 라이브 기록 |

- **데이터는 저장소 JSON을 바로 읽습니다.** 페이지는 `https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/`의 파일을 `fetch`하므로(raw는 `Access-Control-Allow-Origin: *`), 일일 Actions가 JSON을 커밋하면 사이트를 다시 배포하지 않아도 바뀝니다. raw CDN 캐시 때문에 갱신이 최대 5분 늦게 보일 수 있습니다. 숫자는 HTML에 직접 쓰지 않습니다.
- 빌드 없는 HTML + CSS + 바닐라 ES 모듈, 차트는 인라인 SVG(외부 라이브러리 없음), 외부 리소스는 글꼴 CSS(Inter, Pretendard)뿐이고 트래킹은 없습니다. 디자인은 [`DESIGN_clay.md`](DESIGN_clay.md)(크림 캔버스, 카드 6색 순환), 확정 목업은 [`docs/design/clay-hybrid.html`](docs/design/clay-hybrid.html).
- 모든 페이지 아래의 **증거 바**가 `status.json`으로 "마지막 갱신 · Actions 실행 번호 · 커밋 · 모델"을 링크와 함께 보여 줍니다.
- 페이지 요소별로 어느 파일의 어느 키를 읽는지는 [데이터 계약](docs/site/data-contract.md)에 표로 고정했고, [`scripts/check_site.py`](scripts/check_site.py)가 메뉴·증거 바·외부 리소스·상수·키 경로를 검사합니다.
- 배포: [`.github/workflows/pages.yml`](.github/workflows/pages.yml)이 main의 `site/**` 변경(또는 수동 실행) 때 `site/`를 GitHub Pages에 올립니다.

### 로컬 미리보기

저장소 루트에서 `python -m http.server 8000`을 실행하고 `http://localhost:8000/site/`를 엽니다. localhost에서는 raw URL 대신 저장소의 `data/public/`을 읽습니다. `http://localhost:8000/site/?fixture=edge`는 취소·선발 미정 경기를 그리는 검증 화면, `?date=2026-09-01`은 그 날짜의 되감기입니다.

### Genspark 제작본 반영

지금 사이트는 Genspark로 다시 만들 수 있는 참조 구현이기도 합니다. 제작본은 검증을 통과하고 더 마음에 들 때만 `site/`를 교체합니다.

1. [Genspark 브리프](docs/site/genspark-brief.md)의 공통 규칙과 페이지별 프롬프트를 붙여 넣고, 해당 `site/*.html` + `site/assets/*`를 참조로 첨부해 페이지를 만듭니다(홈 → 성적표 → 선수 → 팀).
2. 페이지마다 HTML로 내보내 `index.html`·`teams.html`·`players.html`·`report.html`로 이름을 맞추고 zip으로 묶습니다.
3. `python -X utf8 scripts/import_site.py genspark.zip --dry-run`으로 미리 확인한 뒤 `python -X utf8 scripts/import_site.py genspark.zip`. 지금 `site/`를 `artifacts/site-backup-<시각>/`에 백업하고, Cloudflare beacon 같은 허용 밖 외부 스크립트를 지우고 `file://` 경로를 상대 경로로 고친 뒤 `site/`에 덮어씁니다.
4. 스크립트가 `scripts/check_site.py --strict`를 실행합니다(실패하면 백업으로 되돌림, `--keep`이면 남김). 통과하면 로컬 미리보기에서 1280px·360px 화면을 확인합니다.
5. `site/`를 커밋·push하면 `pages.yml`이 다시 배포합니다.

## 아키텍처

```
수집 (MyKBOStats: 주간 일정 · 박스스코어 · 예정 경기의 예고 선발)
  → data/raw/{season}/  games.jsonl, boxscores/{YYYY-MM}.jsonl.gz, starters.jsonl
    → 피처 26개 (경기 날짜 이전 기록만 사용)
        data/processed/features.parquet  (gitignore, SHA256은 models/manifest.json)
      → 모델 두 벌
          평가용 report-2026  models/report-2026.pkl  → data/public/model_report.json (한 번 생성해 고정)
                              → data/public/rewind/2026/{date}.json, index.json (되감기, 한 번 생성해 고정)
          라이브 v0.2         models/win_model.pkl    (2015~2026 전체 학습, 주간 재학습)
          팀 모델 team-2026   models/team-2026.pkl    (선발 피처 없는 19개, 2015~2024 학습)
                              → 가을야구·시리즈 몬테카를로 1만 회 → outlook 블록 (latest.json, 되감기)
                                (시리즈의 오늘 경기만 라이브 v0.2의 선발 포함 확률)
        → GitHub Actions
            daily.yml           매일 09:07, 17:07 KST  수집 + 추론 + outlook
            weekly_retrain.yml  월요일 03:07 KST       라이브 재학습 + 군집 확인(바뀌면 실패) + 전체 parity(노트북 포함)
            ci.yml              push · PR             테스트 + parity (--quick)
          → data/public/*.json, *.csv
            → 사이트 site/ (GitHub Pages, pages.yml) — raw.githubusercontent.com의 JSON을 브라우저에서 fetch

    → 선수·시즌 집계 (박스스코어 + 경기 페이지 기록표의 2루타·3루타·도루·한글 이름)
      → 선수 유형 군집 clusters-2026  models/clusters.pkl (2015~2025로 맞추고 2026은 배정만)
          → data/public/players.json, teams.json (python -m kbo_predict.cluster publish, 수동 실행)
          → 상성 피처 전후 비교 → model_report.json의 matchup_feature_ablation (채택 안 함)
          → latest.json 선발 블록의 type (직전 시즌 투수 유형)

노트북 (notebooks/)  ← 같은 data/raw를 읽어 수집·피처·모델·유형·오늘 경기 예측을 설명 (01~05 완료)
scripts/check_parity.py  ← 커밋된 산출물을 원본 데이터만으로 다시 만들어 값 비교 + 노트북 02~05 실행
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

## 자동화와 되감기

GitHub Actions 워크플로 3개가 저장소를 돌리고, 사이트가 읽을 되감기 JSON과 `outlook` 블록을 만듭니다. 시뮬레이션은 [`src/kbo_predict/simulate.py`](src/kbo_predict/simulate.py), 되감기는 [`src/kbo_predict/rewind.py`](src/kbo_predict/rewind.py)와 [`scripts/build_rewind.py`](scripts/build_rewind.py), parity 검사는 [`scripts/check_parity.py`](scripts/check_parity.py)에 있고, 노트북 05가 같은 함수를 불러 오늘 경기 하나를 따라갑니다. 아래 숫자는 [`rewind/2026/index.json`](data/public/rewind/2026/index.json), `models/manifest.json`, Actions 실행 기록에서 옮겼습니다.

### 워크플로

| 워크플로 | 언제 (KST) | 하는 일 | 결과 |
| --- | --- | --- | --- |
| [`daily.yml`](.github/workflows/daily.yml) | 매일 09:07, 17:07 (UTC `7 0`, `7 8`) + 수동 | [`run_pipeline.py`](scripts/run_pipeline.py): 대상일 −7~+14일 일정·박스스코어 수집 → 오늘 경기가 있으면 예고 선발 → 수집 창 이전인데 박스스코어가 없는 정규시즌 FINAL 재수집(최신순 20개 — 얼린 시즌 2015~2026은 하지 않음, 위 수집이 예외로 멈춘 실행도 건너뜀) → `history.csv` 적중 기록 갱신 → 라이브 v0.2 추론 + `outlook` → `latest.json`(경기 있는 날만)·`status.json` (30분 제한) | `github-actions[bot]`이 `data/raw`·`data/public`을 `auto: predictions YYYY-MM-DD-HHMM`으로 커밋, 수집 실패 시 `collect-failure` 이슈 |
| [`weekly_retrain.yml`](.github/workflows/weekly_retrain.yml) | 매주 월요일 03:07 (UTC 일요일 `7 18`) + 수동 | 피처 재생성 → `train_win live --skip-if-same`(예측과 manifest의 `live.features_fingerprint`가 모두 그대로면 쓰지 않음) → 군집 후보 fit → `cluster compare --types`(유형 정의가 같은지, 유형표 해시가 바뀌었는지) → 유형표가 바뀌었으면(`types_changed=1`) **실패**("frozen cluster inputs changed — refreeze by hand", 자동 fit·publish 없음) → 전체 `check_parity --require-live`(노트북 02~05 포함) | main에서만 `auto: weekly retrain YYYY-MM-DD`로 커밋(바뀐 것이 없으면 커밋 없음), 실패 시 `parity-failure` 이슈 |
| [`ci.yml`](.github/workflows/ci.yml) | main push, PR | `pytest -m "not slow"` + `check_parity --quick` (ubuntu, 30분 제한, 같은 브랜치의 이전 실행 취소) | 위 `ci · parity` 배지 |

- 권한은 `daily`·`weekly`가 `contents: write` + `issues: write`, `ci`가 `contents: read`입니다. 시크릿은 쓰지 않습니다.
- 의존성은 런타임 [`requirements.txt`](requirements.txt)(일일·주간)와 개발용 [`requirements-dev.txt`](requirements-dev.txt)(`-r requirements.txt` + pytest·matplotlib·nbformat·nbclient·nbconvert·ipykernel, ci·주간)로 나눴습니다. 모두 `==` 고정이고 numpy는 1.26.4를 유지합니다.
- `model_report.json`, `models/report-2026.pkl`, `models/team-2026.pkl`, `models/clusters.pkl`, `players.json`·`teams.json`, 되감기 JSON은 주간 재학습이 덮어쓰지 않습니다(고정). 주간 재학습이 바꾸는 것은 `models/win_model.pkl`과 manifest의 `live` 항목뿐입니다. 군집 유형표가 커밋본과 달라지면(얼린 2015~2026 박스스코어가 바뀐 것) 주간 재학습은 실패하고 `parity-failure` 이슈를 엽니다 — 원인을 확인한 뒤 `cluster fit`·`publish`·`train_win report --force`로 사람이 다시 얼립니다.
- 얼린 시즌(2015~2026)의 박스스코어는 일일 작업이 다시 받지 않습니다(빠진 박스스코어 재수집은 얼리지 않은 시즌만). 그래서 얼린 산출물의 parity가 매일 수집 때문에 깨지지 않습니다.
- 첫 일일 실행: [Actions run](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/runs/40533547898). Linux(ubuntu)에서 테스트와 parity가 모두 통과한 첫 ci 실행: [Actions run](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/runs/40882643905). 주간 재학습의 첫 정기 실행은 2026-11-02(월)입니다.

### 전망 카드 (`outlook`)

`latest.json`과 되감기 파일마다 `outlook` 블록이 하나 있고, 시기에 따라 `type`이 셋 중 하나입니다. 모두 `as_of`(기준 날짜)를 가집니다.

| `type` | 언제 | 내용 |
| --- | --- | --- |
| `series` | 등록된 포스트시즌 시리즈가 진행 중일 때 (경기가 없는 날 포함) | `name`, `best_of`, `teams`, `head_start`(시작할 때 안고 들어간 승수, 보통 `[0, 0]`), `wins`(경기 전 기준 전적 — `head_start` 포함), `win_prob`(양 팀 시리즈 승리 확률), `most_common_result`(가장 흔한 최종 전적), `goes_distance_prob`(최종전까지 갈 확률), `games_remaining_max`, `today_game_prob_source`(오늘 경기 확률의 출처: `"win_model (starter-inclusive)"` 또는 `"team_model"`), `next_game_date` |
| `playoff_race` | 정규시즌 날짜 (되감기의 모든 날짜) | `teams`: 팀 코드별 `wins`, `losses`, `rank_now`(현재 순위), `exp_wins`(시즌 종료 기대 승수), `playoff_prob`(가을야구 = 정규시즌 5위 이내 확률) |
| `next_game` | 그 밖 (시범경기, 등록되지 않은 시리즈, 비시즌) | `next_game_date` (취소 제외 다음 경기 날짜 또는 null) |

- **확률 모델**: 미래 경기 확률은 선발 없는 팀 모델 `team-2026`([`models/team-2026.pkl`](models/team-2026.pkl), 팀 피처 19개, report-2026과 같은 2015~2024 학습·2025 선택 절차 — `model_report.json`의 `ablation.no_starter`와 같은 모델, 2026 정확도 0.547)로 냅니다. 미래 경기의 선발은 아직 모르기 때문입니다. 단, 시리즈 카드에서 **오늘 경기**는 예고 선발을 아는 라이브 승패 모델의 확률(같은 날 `latest.json` 경기 항목의 `home_win_prob`, 반올림 전 값)을 씁니다 — 오늘 경기의 실제 홈이 대진표의 다음 순번 홈과 같을 때만이고, 그러면 `today_game_prob_source`가 `"win_model (starter-inclusive)"`입니다(시리즈 도중 경기 없는 날 등은 `"team_model"`).
- **몬테카를로**: 남은 경기의 결과를 그 확률로 무작위로 1만 번 뽑아 결과를 셉니다(`numpy.random.default_rng(42)`, 같은 입력이면 같은 JSON). 각 경기 확률은 기준 날짜의 팀 상태로 한 번 계산하고, 시뮬레이션 안에서는 상태를 갱신하지 않습니다.
- **가을야구 동률**: 승률(무승부 제외)이 같은 팀들이 걸친 순위 [lo, hi]에 대해 각 팀에 `clip((5−lo+1)/(hi−lo+1), 0, 1)`만큼 진출 몫을 나눠 줍니다. 그래서 시뮬레이션마다 정확히 5자리가 배분됩니다. `rank_now`는 동률이면 높은 순위(정수)입니다.
- **시리즈 입력**: 대진(팀, `best_of`, 1차전 날짜, 경기별 홈팀, 선택 `head_start`)은 사람이 유지하는 [`config/postseason.yaml`](config/postseason.yaml)에서 읽고, 지금까지의 전적은 `head_start` + `games.jsonl`에서 기준 날짜 **전**에 끝난 경기(`date < on`)로 셉니다. 취소 경기는 다음 경기가 같은 순번(같은 홈)으로 치러지고, 포스트시즌 무승부는 경기 순번(홈 슬롯)을 하나 씁니다.
- **와일드카드 1승 어드밴티지**: 4위 팀이 1승을 안고 시작하는 2선승제는 `best_of: 3`, `head_start: [1, 0]`(팀0 = 4위)으로 적습니다. `homes`는 실제 경기 수(`best_of − sum(head_start)` = 2)만큼이고, 4위는 1승, 5위는 2승이 더 필요합니다. 2026: LG(4위, 두 경기 모두 홈) 대 두산 — 1차전 전 카드는 전적 1-0, LG 0.8194(경기당 LG 승 확률이 p면 1 − (1 − p)²). 실제로는 LG가 1차전을 이겨 2-0으로 끝났습니다. 5위가 1차전을 이기면 1-1로 2차전이 남습니다.
- 출력 확률(`playoff_prob`, `exp_wins`, `win_prob` 등)은 소수 4자리입니다.
- **예 (2026-10-29)**: 플레이오프 삼성(SS) 대 KIA(HT) 1승 1패, 오늘 3차전(KIA 홈)은 예고 선발 포함 확률 SS 0.5536, 4차전은 팀 모델 SS 0.4974, 5차전(삼성 홈) SS 0.5629 → 시리즈 승리 확률 SS 0.5579 / HT 0.4421, 가장 흔한 결말 3-2, 5차전까지 갈 확률 0.5083(`today_game_prob_source: "win_model (starter-inclusive)"`). 오늘 경기도 팀 모델로 굴리면 SS 0.5279였습니다. 커밋된 `latest.json`(10-29 14:40 실행)은 이 기능 전에 만들어져 `outlook`이 아직 없고, 다음 일일 실행부터 들어갑니다.

### 되감기 (`rewind/2026/`)

비시즌에 사이트가 "이 날 모델은 이렇게 예측했고 결과는 이랬다"를 보여 주도록, 2026 정규시즌 날짜마다 `latest.json`과 같은 모양의 파일을 미리 만들었습니다(`python -X utf8 scripts/build_rewind.py --season 2026`, 요청 없음, 약 15초).

- **모델**: 평가용 `report-2026`(2015~2024 학습, 2026은 홀드아웃)과 `team-2026`만 씁니다. 날짜 D의 피처와 `outlook`은 D 전날까지 끝난 경기로만 만들고(`rewind.state_before`, `date < D`), D 이후(같은 날 2차전 포함) 결과를 바꿔도 D의 파일이 바뀌지 않는다는 테스트가 있습니다.
- **선발**: 과거 예고 선발 이력이 없으므로 박스스코어의 **실제 선발**을 씁니다(`starter_source: "actual (boxscore pitching order 1)"`). 백테스트와 같은 가정입니다.
- **범위**: 정규시즌 165일(03-28~10-12) 전부, 날짜당 파일 1개 + `index.json` = 166개, 933,712바이트(약 0.93 MB). 취소 경기도 `latest.json`과 같은 모양(`home_win_prob: null`, `factors: []`, `result: null`)으로 넣어 모든 날짜에 파일이 있습니다(790행 = FINAL 718 + 취소 72). LIVE로 멈춘 2경기(13352, 13606)는 넣지 않습니다. 시범경기·포스트시즌도 넣지 않습니다.
- **결과 블록** `result`: `home_score`, `away_score`, `winner`(`HOME`/`AWAY`/`DRAW`), `pick`, `correct`. `pick`은 반올림 **전** 확률이 0.5 이상이면 `HOME`이고(`train_win._correct`와 같은 규칙), `correct = pick == winner`, 무승부는 `correct: null`입니다. 예: 13572(06-12)는 표시 확률이 0.5000이지만 반올림 전 값이 0.5보다 조금 작아 `pick`이 `AWAY`입니다.
- **적중률**: `index.json`의 날짜별 `games`·`decided`·`correct`를 합하면 **417/702 = 0.594**로, `model_report.json`의 2026 시험 정확도와 같습니다(테스트로 확인).

2026-09-01 파일의 `outlook` (그날 경기 전 기준)은 이렇습니다. 실제 2026 포스트시즌 진출 5팀(LG, 두산, KIA, 삼성, KT)이 상위 5팀과 같습니다.

| 팀 | 현재 순위 | 승-패 | 기대 승수 | 가을야구 확률 |
| --- | --- | --- | --- | --- |
| 삼성 (SS) | 1 | 68-44 | 84.06 | 1.0000 |
| KT | 2 | 66-43 | 82.77 | 1.0000 |
| KIA (HT) | 3 | 63-50 | 77.64 | 0.9947 |
| LG | 4 | 63-51 | 78.54 | 0.9965 |
| 두산 (OB) | 5 | 61-52 | 73.98 | 0.9657 |
| NC | 6 | 51-58 | 66.90 | 0.0301 |
| 롯데 (LT) | 7 | 50-61 | 65.58 | 0.0078 |
| 한화 (HH) | 8 | 49-61 | 64.94 | 0.0049 |
| SSG (SK) | 9 | 48-65 | 61.36 | 0.0004 |
| 키움 (WO) | 10 | 42-76 | 51.23 | 0.0000 |

### parity 검사

설계 목표인 "`.py`와 `.ipynb`가 같은 숫자"를 이렇게 검증합니다: [`scripts/check_parity.py`](scripts/check_parity.py)가 커밋된 산출물을 저장소의 원본 데이터(`data/raw`)와 코드만으로 다시 만들어 비교하고, 노트북 02~05를 실행합니다(노트북마다 마지막에 매니페스트 지문·보고서·사이트 JSON과 같은지 assert). 재생성본은 `artifacts/parity/`(gitignore)에만 쓰고, 네트워크 요청은 없습니다.

| 비교 | 기준 | 판정 |
| --- | --- | --- |
| 다시 만든 `features.parquet`·`matchup.parquet` | `models/manifest.json`의 `features_fingerprint`·`matchup_fingerprint` | 값 지문 일치 (파일 SHA256은 정보로만 표시) |
| 선수 유형표 CSV, 다시 맞춘 군집 | `clusters.types_sha256`, 커밋된 `models/clusters.pkl` | 해시 일치, 중심 차이 1e-9 이내·맞춤 시즌 라벨 동일 (`cluster compare`) |
| `train_report` 재계산, `train_team` 요약 | `model_report.json`, 그 안의 `ablation.no_starter` | 실수 상대 오차 1e-9 이내 (`generated_at`·`commit_sha`·`run_url` 제외) |
| 다시 학습한 report-2026·team-2026·라이브 번들의 예측 | 커밋된 pkl의 예측 (8,465행) | 차이 1e-9 이내 (pkl 바이트는 `trained_at` 때문에 비교하지 않음) |
| `players.json`·`teams.json` 재생성 | 커밋본 | 정확히 같음 (메타 제외) |
| 되감기 시즌 전체 재생성 | `rewind/2026/`의 166개 파일 (파일 목록 포함) | 정확히 같음 (`generated_at`·`commit_sha` 제외) |
| 노트북 02~05 실행 (넷 다 필수 — 없으면 실패) | 노트북 안의 assert (값 지문, 보고서 실수 상대 1e-9, 예측 차이 1e-9 — `kbo_predict.parity`, 위와 같은 규칙) | 오류 출력 0 (`--quick`이면 건너뜀) |

- **바이트가 아니라 값으로**: 같은 코드로도 Linux(OpenBLAS)와 Windows(MKL)는 `features.parquet`의 마지막 비트가 달라 파일 SHA256이 다릅니다. 실제로 처음 Linux ci([40879259726](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/runs/40879259726))는 이 한 줄만 달라 실패했고(예측 차이 7e-14 이하, 나머지는 모두 같음), 그 뒤 parquet 판정을 값 지문으로 바꿔 통과했습니다([40882643905](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/runs/40882643905)). 값 지문 = 실수 열을 소수 6자리로 반올림한 CSV의 SHA256(`features.features_fingerprint`)이고, 현재 값은 `752b4319…`(피처), `3419c8c1…`(상성)입니다.
- **얼린 시즌**: report-2026·team-2026·clusters-2026과 그 하류(사이트 JSON, 되감기)는 2015~2026(`FROZEN_SEASONS`)만으로 다시 만들어 비교하므로, 2027 경기가 쌓여도 이 비교는 깨지지 않습니다. 라이브 모델은 manifest의 `live.features_fingerprint`가 지금 parquet와 같을 때만 비교하고(다르면 건너뜀), 주간 재학습은 `--require-live`로 건너뜀도 실패로 봅니다.
- **실행 순서**: 군집 단계는 맨 마지막에 돕니다. 군집 계산의 단일 스레드 제한이 끝난 뒤에도 MKL이 1스레드로 남는 일이 있어, 같은 프로세스에서 이어 학습하면 로지스틱 회귀의 마지막 자리가 달라지기 때문입니다.
- **노트북도 플랫폼 간으로**: 노트북 03·04의 동일성 셀은 `check_parity`와 같은 함수(`kbo_predict.parity.first_diff`, `same_predictions_close`)와 값 지문(`matchup_fingerprint`)으로 판정하고, 파일 바이트 SHA256은 정보로만 찍습니다. 그래서 Linux에서 도는 주간 재학습의 전체 parity(노트북 포함)도 Windows와 같은 기준으로 통과해야 합니다.
- **명령과 시간** (Windows 기준): `python -X utf8 scripts/check_parity.py --quick` 약 37초(ci), 노트북까지 포함한 전체 실행 약 100초(주간 재학습, `--require-live`). 어느 폴더에서 실행해도 스크립트가 있는 저장소를 검사합니다(`--repo` 기본값). 결과는 항목별 표로 찍고, 하나라도 다르면 어떤 파일·키가 다른지 출력하며 exit 1입니다.

### 해석할 때 주의할 점 (한계)

- **시리즈 시뮬레이션에서 선발을 아는 건 오늘 경기뿐입니다.** 오늘 경기는 예측 카드와 같은 선발 포함 확률(10-29 3차전 SS 55.4%)로, 그 뒤 경기는 선발 없는 팀 모델로 굴립니다(해결: 예전에는 오늘 경기도 팀 모델 SS 49.7%로 굴려 카드와 숫자가 어긋났습니다). 선발 로테이션은 반영하지 않습니다.
- **라이브 전망의 팀 모델은 2015~2024 학습**입니다(`team-2026`). 2015~2026으로 다시 학습한 라이브 팀 모델은 2027 시즌 전으로 미뤘습니다.
- **시뮬레이션 안에서 팀 상태가 바뀌지 않습니다.** 한 경기 결과가 다음 경기의 승률·최근 10경기 같은 피처를 바꾸는 효과를 무시하고, 남은 경기를 모두 기준 날짜 상태로 계산합니다(불펜 피로 피처도 고정).
- **가을야구 동률 배분은 실제 KBO 규정과 다릅니다.** 실제로는 상대 전적이나 순위 결정전으로 가르지만, 여기서는 승률만 보고 진출 몫을 나눕니다.
- **포스트시즌 대진은 사람이 갱신합니다.** `config/postseason.yaml`에 없는 시리즈는 `next_game` 카드가 되고, 2026 한국시리즈는 상대가 정해지면 채워야 합니다. 데이터에서 끝나지 않은 채 남은 등록 시리즈는 다음 시리즈가 시작될 때까지 "진행 중"으로 보입니다.
- **되감기는 실제 선발 가정입니다.** 백테스트와 같이 "경기 전에 선발을 정확히 안다"는 가정 위의 예측입니다. 예고 선발 이력은 따로 쌓지 않습니다(`starters.jsonl`은 경기당 가장 최근 발표만).
- **값 지문의 경계**: 어떤 값이 소수 6자리 반올림 경계에 정확히 걸리면 플랫폼에 따라 지문이 달라질 수 있습니다(지금 데이터에서는 Linux·Windows가 같음).
- **주간 재학습은 얼린 군집을 스스로 다시 얼리지 않습니다.** 유형표가 바뀌면(`types_changed=1`) 실패로 멈추고 사람이 다시 얼립니다. 이 실패 경로는 Actions에서 아직 돈 적이 없습니다(지금 데이터로는 유형표가 그대로).
- **`history.csv`는 아직 1행입니다**: 2026-10-29 14050(v0.2, 정산 전). 라이브 적중률은 기록이 쌓여야 말할 수 있습니다.

## 공개 파일

`data/public/`에 있습니다. `latest.json`, `history.csv`, `status.json`은 매 실행마다 갱신되고(`latest.json`은 경기가 있는 날만), `model_report.json`과 `rewind/`는 고정, `players.json`·`teams.json`은 사람이 `python -m kbo_predict.cluster publish`를 돌릴 때만 바뀝니다(주간 재학습은 바꾸지 않음). 사이트에서는 아래 주소를 기준으로 읽을 수 있습니다.

`https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/`

| 파일 | 내용 |
| --- | --- |
| [`latest.json`](data/public/latest.json) | 오늘 경기 예측: 팀, 구장, 시간, 팀별 예고 선발(`starter`: 이름·ERA·K/9·BB/9·이닝·선발 등판 수, `type`: 직전 시즌 투수 유형 `{id, name}` 또는 직전 시즌 자격이 없으면 null), 홈 승률, 기여도(`contribution_pp`) 상위 5개 요인, `round`(`preseason`/`regular`/`postseason`), 메타(`generated_at`, `commit_sha`, `run_url`, `model_version`, `mode`). 취소 경기는 `status: "CANCELED"`, `home_win_prob: null`, `factors: []` |
| `latest.json`의 `outlook` | 전망 카드 하나: `type`이 `series`(진행 중인 포스트시즌 시리즈: 전적·시리즈 승리 확률·가장 흔한 결말·최종전 확률·오늘 경기 확률 출처·`next_game_date` — 오늘 경기는 선발 포함 확률), `playoff_race`(정규시즌: 팀별 승·패·현재 순위·기대 승수·가을야구 확률), `next_game`(그 밖: `next_game_date`) 중 하나, 모두 `as_of`. 팀 모델 `team-2026` + 몬테카를로 1만 회, 확률 소수 4자리 (위 "전망 카드" 절). 팀 모델을 읽지 못하면 `next_game` 꼴로 대신하고 `collect_errors`에 남김 |
| [`rewind/{season}/{date}.json`](data/public/rewind/2026/2026-09-01.json) | 되감기: 그날의 `latest.json`과 같은 모양 + 경기별 `result`(`home_score`, `away_score`, `winner`, `pick`, `correct`; 취소 경기는 null)와 `outlook`(`playoff_race`). 메타는 `mode: "rewind"`, `model_version: "report-2026"`, `team_model_version: "team-2026"`, `starter_source: "actual (boxscore pitching order 1)"`. 2026 정규시즌 165일, 압축 JSON 합계 933,712바이트(`index.json` 포함, 약 0.93 MB) |
| [`rewind/{season}/index.json`](data/public/rewind/2026/index.json) | 되감기 목차: `season`, `model_version`, `dates`(날짜별 `date`, `games`, `decided`, `correct`), `accuracy`(0.594), `n_decided`(702), `note`(적중 규칙). 날짜별 `correct` 합 417 |
| [`model_report.json`](data/public/model_report.json) | 모델 성적표(`report-2026`): 두 알고리즘의 검증·시험 지표, 기준선 3종, McNemar 검정, 캘리브레이션 구간표, 피처 중요도, 선발 피처 제외 비교, 선발 소스 표기, 유형 상성 피처 전후 비교(`matchup_feature_ablation`), 군집 품질(`cluster_quality`: K별 실루엣·유지율, 유형별 인원·대표 선수·중심 지표, 소속 확률 방식). 한 번 생성해 고정 (3단계에서 두 블록을 채우려고 다시 만들었고 기존 키의 값은 그대로) |
| [`players.json`](data/public/players.json) | 선수-시즌 2,918개(타자 1,327 + 투수 1,591, 2015~2026). 메타(`generated_at`, `commit_sha`, `model_version: "clusters-2026"`, `fit_seasons`, `note`)와 `types`(그룹별 유형 `id`·`name`·`blurb`), `players[]`: `group`, `season`, `player_id`, `name`(로마자), `name_ko`, `team`, `pos`, `type {id, name}`, `prob`, `membership`(유형별 소속 확률), `x`·`y`(PCA 2D 좌표), `stats`(타자: 타석·타율·출루율·홈런·도루·K%·BB%·ISO·BABIP / 투수: 등판·선발·이닝·ERA·K%·BB%·HR%·BABIP), `similar`(유사 선수 5명 — 서로 다른 선수, 선수마다 가장 비슷한 시즌 하나; `player_id`·`season`·`similarity`만 — 이름은 같은 파일에서 찾음). 압축 JSON 1.77 MB (gzip -9 기준 약 270 KB) |
| [`teams.json`](data/public/teams.json) | 팀-시즌 120개(10구단 × 2015~2026). `season`, `code`, `name`, `games`, `wins`·`losses`·`ties`, `win_pct`(무승부 제외), `home_pct`, `away_pct`, `pyth_pct`(피타고리안), `model_expected`(report-2026 모델의 홀드아웃 예측 평균, 2026만 — 2015~2025는 학습·검증 시즌이라 null), `roster_types`(타자는 타석, 투수는 아웃 수로 가중한 유형 비중), `vs`(상대 팀별 승률) |
| [`history.csv`](data/public/history.csv) | 과거 예측과 결과 기록: date, game_id, home, away, home_win_prob, model_version, predicted_at, status, winner, correct. 지금은 1행(2026-10-29 14050, v0.2, 아직 정산 전) |
| [`status.json`](data/public/status.json) | 파이프라인 상태: generated_at, run_url, commit_sha, mode, next_game_date, games_today, model_version, collect_errors (경기가 없는 날도 갱신). `mode`는 오늘부터 14일 안에 취소되지 않은 경기가 있으면 `live`, 없으면 `rewind`(비시즌 — 사이트가 되감기를 보여 줌) |

수집에 실패한 경기가 있으면(`collect_errors`가 비어 있지 않으면) 일일 워크플로가 `collect-failure` 라벨의 GitHub 이슈를 새로 열거나 기존 이슈에 코멘트합니다([`scripts/collect_errors.py`](scripts/collect_errors.py)). 공개 파일·`games.jsonl`·`starters.jsonl`은 임시 파일에 쓴 뒤 바꿔 넣으므로(원자적 쓰기), 실행이 중간에 죽어도 반쯤 쓴 파일이 남지 않습니다.

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
models/team-2026.pkl                             선발 없는 팀 모델 team-2026 (커밋, 시뮬레이션용)
config/postseason.yaml                           포스트시즌 대진표 (사람이 갱신, 시리즈 시뮬레이션 입력)
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

`notebooks/`에 단계별 설명 노트북을 둡니다. 01~05는 실행 결과를 포함하고 네트워크 없이 실행되며, `tests/test_notebooks.py`(slow)가 실행을 검증하고 `scripts/check_parity.py`가 02~05를 다시 실행합니다(넷 다 필수, 주간 재학습에서 Linux로도 실행). 노트북은 로직을 복사하지 않고 `src/kbo_predict/`·`scripts/`의 같은 함수를 부르며, 마지막에 결과가 커밋된 산출물과 같은지 확인합니다: 02는 만든 parquet의 값 지문이 `models/manifest.json`의 `features_fingerprint`와, 03은 결과가 `data/public/model_report.json`과(상성 parquet는 `matchup_fingerprint`와), 04는 유형표가 `types_sha256`과, 05는 노트북에서 계산한 오늘 경기 예측·`outlook`이 `run_pipeline`을 임시 폴더에 실행한 `latest.json`과, 다시 만든 2026-09-01 되감기가 커밋된 `rewind/2026/2026-09-01.json`과 같은지 봅니다. 03은 02가 저장한 `data/processed/features.parquet`를 읽으므로 02를 먼저 실행합니다.

05는 "오늘"을 2026-10-29로 고정합니다(저장된 예고 선발이 있는 날). 그날 포스트시즌 경기 하나를 상태 → 선발 블록 → 예측과 요인 → 시리즈 몬테카를로(정확한 경우의 수 계산과 비교, 시뮬레이션 횟수별 수렴) → 되감기와 누적 적중률 → `history.csv` → parity 순서로 따라갑니다(41셀, 약 5초).

| 번호 | 노트북 | 짝 `.py` | 상태 |
| --- | --- | --- | --- |
| 01 | [데이터 수집과 살펴보기](notebooks/01_데이터_수집과_살펴보기.ipynb) | `collect.py` | 완료 |
| 02 | [피처 만들기](notebooks/02_피처_만들기.ipynb) | `features.py` | 완료 |
| 03 | [승패 예측 모델](notebooks/03_승패_예측_모델.ipynb) | `train_win.py` | 완료 |
| 04 | [선수 유형 클러스터링](notebooks/04_선수_유형_클러스터링.ipynb) | `cluster.py` | 완료 |
| 05 | [오늘 경기 예측](notebooks/05_오늘_경기_예측.ipynb) | `run_pipeline.py` | 완료 |

## 로컬 실행

```bash
pip install -r requirements-dev.txt && pip install -e .   # 일일 파이프라인만이면 requirements.txt
python -m kbo_predict.collect --from 2026-03-20 --to 2026-11-05   # 약 65분 (요청 간 5초)
python -m kbo_predict.features --out data/processed/features.parquet   # 2015~2026 피처 데이터셋
python -m kbo_predict.cluster fit       # 선수 유형 군집 → models/clusters.pkl, manifest의 clusters 항목
python -m kbo_predict.features --matchup-out data/processed/matchup.parquet   # 직전 시즌 유형 상성 피처
python -m kbo_predict.train_win report --force --matchup data/processed/matchup.parquet --clusters models/clusters.pkl   # report-2026 학습·평가 → model_report.json, models/report-2026.pkl (고정된 보고서를 다시 만들 때만)
python -m kbo_predict.train_win team     # 선발 없는 팀 모델 → models/team-2026.pkl (보고서 숫자 불변)
python -m kbo_predict.train_win live [--skip-if-same]   # 라이브 v0.2 → models/win_model.pkl (report를 먼저 실행; 예측이 같으면 쓰지 않음)
python -m kbo_predict.cluster publish   # players.json, teams.json (report-2026.pkl과 features.parquet 필요)
python -m kbo_predict.cluster compare --against models/clusters.pkl --new <새 pkl> [--types <유형 CSV>]   # 군집 재계산이 커밋본과 같은지
python scripts/build_rewind.py --season 2026 [--dates YYYY-MM-DD,YYYY-MM-DD]   # 되감기 JSON → data/public/rewind/2026/ (약 15초)
python scripts/run_pipeline.py [--date YYYY-MM-DD] [--no-fetch]
python scripts/check_parity.py [--quick] [--require-live] [--out artifacts/parity]   # parity 검사 (약 37초 / 노트북 포함 약 100초)
python -m http.server 8000             # 사이트 미리보기 → http://localhost:8000/site/
python scripts/check_site.py --strict  # 사이트 검사 (메뉴·증거 바·외부 리소스·상수·데이터 계약 키)
python scripts/import_site.py <zip|폴더|html> [--as index.html] [--dry-run] [--keep]   # Genspark 제작본 반영
```

- Windows에서는 한글 출력 때문에 `python -X utf8 …`로 실행합니다.
- `model_report.json`은 한 번 만든 뒤 고정합니다. 이미 있으면 `report`는 `--force` 없이 거부합니다. `live`는 보고서에서 선택된 알고리즘·보정 방법·LightGBM 트리 수만 읽으므로, 경기가 쌓여 parquet가 바뀌어도 다시 학습할 수 있습니다.
- `train_win`의 두 명령은 `models/manifest.json`에 **모델별로** 모델 파일 SHA256·버전과 그 모델을 만든 parquet의 SHA256을 기록합니다(각 명령은 자기 항목만 갱신). parquet는 커밋하지 않으므로 이 해시로 같은 데이터인지 확인합니다.
- 모델 의존성은 `lightgbm==4.7.0`, `pyarrow==19.0.1`(numpy 1.x와 호환되는 버전)입니다. 요인 분해는 LightGBM 내장 TreeSHAP을 쓰므로 `shap` 패키지는 필요 없습니다.
- `train_win report`를 `--matchup`·`--clusters` 없이 돌리면 `model_report.json`의 `matchup_feature_ablation`·`cluster_quality`가 null로 돌아갑니다. 보고서를 다시 만들 때는 위처럼 두 옵션을 함께 줍니다.
- 박스스코어의 2루타·3루타·도루·한글 이름은 로컬 HTML 캐시를 다시 파싱해 채웠습니다: `python -X utf8 scripts/reparse_boxscores.py --cache data/cache/html --seasons 2015-2026 [--dry-run] [--infer-aliases]` (요청 없음, 기존 칸 불변 검사). 일일 수집도 새 경기의 기록표를 같은 파서로 읽지만, 한글 이름 힌트와 별칭 없이 읽습니다.
- `config/cluster_labels.yaml`(유형 이름)은 패키지 위치 기준으로 찾으므로 어느 폴더에서 실행해도 같은 이름이 나옵니다. 군집은 단일 스레드로 계산해 같은 기계에서는 비트 단위로 재현되지만, 다른 BLAS(예: Linux의 Actions)에서는 마지막 자리가 다를 수 있어 커밋된 `models/clusters.pkl`이 기준입니다. `cluster compare`가 다시 맞춘 군집을 커밋본과 비교하고(중심 차이 1e-9 이내, 맞춤 시즌 라벨 동일), Linux ci에서도 유형표 해시(`types_sha256`)가 같았습니다.
- `check_parity`는 재생성본을 `--out`(기본 `artifacts/parity/`, gitignore)에만 쓰고 `data/public`·`models` 아래로의 출력은 거부합니다. 노트북 02는 스스로 `data/processed/features.parquet`를 씁니다(gitignore).

테스트는 `python -X utf8 -m pytest -q -m "not slow"`(367개, ci와 같음 — 사이트 30개 포함)이고, `-m slow`로 6개를 더 돌립니다(노트북 01~05 실행 5개 + 실데이터 `check_parity --quick` 1개). 전부 돌리려면 `python -X utf8 -m pytest -q`입니다.

## 데이터 출처

- 데이터 출처: [MyKBOStats](https://mykbostats.com) (비공식 팬 사이트). robots.txt의 `Crawl-delay: 5`를 지켜 요청 간 5초를 두고, 주간 일정 페이지, 경기 박스스코어 페이지(하단 기록표 포함), 예정 경기 페이지의 예고 선발("Starting pitchers" 섹션)을 파싱합니다. 선수 이름은 사이트 표기대로 로마자이고, 한글 이름(`name_ko`)은 같은 사이트 기록표의 한글 제목에서 모았습니다(정규시즌 FINAL 경기의 기록표만 투표 — 계속 쌓이는 포스트시즌·시범경기 기록표가 얼린 이름표를 바꾸지 않게). 개인 학습용입니다.
- KBO 공식 사이트는 약관상 크롤링이 금지되어 사용하지 않습니다.
- 네이버 스포츠의 내부 API는 Python 클라이언트를 차단해(TLS/UA 수준) 수집 대상에서 뺐습니다. 우회는 시도하지 않았습니다.

## 로드맵

1. ~~2015~2025 데이터 백필, 노트북 01~~ (완료)
2. ~~선발투수 정보 소스 확보, 피처 26개, LightGBM, 확률 보정, 요인 분해(SHAP), report/live 두 모델 분리, 노트북 02·03~~ (완료)
3. ~~선수 유형 클러스터링, 유형 상성 피처 전후 비교, `players.json`·`teams.json`, 노트북 04~~ (완료)
4. ~~py와 ipynb 결과 동일성 검증(parity), 주간 재학습, 되감기 JSON, 가을야구·시리즈 시뮬레이션(`outlook`), 노트북 05~~ (완료)
5. ~~정적 사이트 4페이지 + GitHub Pages, Genspark 브리프와 제작본 반영 스크립트~~ (완료)
6. README 정리와 한 달 무인 운영

## 문서

- 설계 문서: [docs/superpowers/specs/2026-10-27-kbo-predict-design.md](docs/superpowers/specs/2026-10-27-kbo-predict-design.md)
- 구현 계획: [0단계 수직 슬라이스](docs/superpowers/plans/2026-10-27-stage0-vertical-slice.md), [1단계 백필·노트북 01](docs/superpowers/plans/2026-10-28-stage1-backfill-notebook01.md), [2단계 피처 + 승패 모델](docs/superpowers/plans/2026-10-29-stage2-win-model.md), [3단계 선수 유형 클러스터링](docs/superpowers/plans/2026-10-29-stage3-clustering.md), [4단계 자동화 + parity](docs/superpowers/plans/2026-10-29-stage4-automation.md), [5단계 사이트](docs/superpowers/plans/2026-10-30-stage5-site.md)
- 사이트: [데이터 계약](docs/site/data-contract.md), [Genspark 브리프](docs/site/genspark-brief.md), [확정 목업](docs/design/clay-hybrid.html)
- 이월 항목: [docs/superpowers/plans/2026-10-27-stage0-deferred.md](docs/superpowers/plans/2026-10-27-stage0-deferred.md)
- 데이터 조사: [docs/research/kbo-data-sources.md](docs/research/kbo-data-sources.md)
- 디자인 시스템: [DESIGN_clay.md](DESIGN_clay.md)

저장소: https://github.com/kimminseo2323-prog/2610_KBO_predict
