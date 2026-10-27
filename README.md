# KBO Predict

![daily](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/workflows/daily.yml/badge.svg)

KBO 경기의 승패 확률을 매일 예측하고, 예측과 실제 결과를 공개 파일로 기록하는 포트폴리오 프로젝트입니다. 이후 단계에서 선수 유형 클러스터링을 더해 한 저장소에서 예측과 분석을 함께 다룰 예정입니다.

**현재 버전: v0.1 (0단계 수직 슬라이스)**. 수집, 피처, 모델, 자동 실행, 공개 파일까지 끝에서 끝까지 한 번 이어 놓은 상태이고, 모델 성능은 아직 기준선 수준입니다.

## 아키텍처

```
수집 (MyKBOStats)
  → 피처 (경기 날짜 이전 기록만 사용)
    → 모델 (로지스틱 회귀)
      → GitHub Actions (매일 09:00, 17:00 KST)
        → data/public/*.json, *.csv
          → 사이트 (예정)
```

- 수집 결과는 `data/raw/2026/`에 파싱된 형태로 커밋합니다. 경기 829건(`games.jsonl`), 종료된 경기 749건의 박스스코어(`boxscores.jsonl.gz`)입니다. 원본 HTML은 로컬 캐시에만 둡니다.
- 시즌 데이터는 2026-03-28부터 2026-10-12까지의 정규시즌 종료 경기 718건을 사용합니다. 무승부 16건은 학습에서 제외해 학습 행은 702건입니다. 사이트에서 종료로 바뀌지 않고 진행 중으로 남은 2경기도 제외했습니다.
- 포스트시즌(10-14 이후) 경기도 파이프라인이 실시간으로 예측합니다.

## v0.1 모델

`StandardScaler` + `LogisticRegression`. 입력 피처는 세 가지입니다.

| 피처 | 의미 |
| --- | --- |
| `win_pct_diff` | 두 팀의 승률 차이 |
| `last10_diff` | 최근 10경기 흐름 차이 |
| `run_diff_diff` | 경기당 득실차 차이 |

절편이 홈 어드밴티지를 나타냅니다. 모든 피처는 해당 경기 날짜 이전 경기만으로 계산하며, 누수 방지 테스트가 있습니다.

**선발투수 피처는 아직 없습니다.** MyKBOStats에는 경기 전에 공개되는 예상 선발 정보가 없기 때문입니다. 로드맵에서 가장 먼저 해결할 항목입니다.

### 지표

시간순 분할로 평가했습니다. 학습은 2026-03-28~07-31(478경기), 테스트는 2026-08-01~10-12(224경기)입니다. 값은 `models/metrics_v0.1.json`에서 옮겼습니다.

| 지표 | 값 |
| --- | --- |
| 정확도 (accuracy) | 0.603 |
| 로그 손실 (log loss) | 0.682 |
| Brier score | 0.244 |
| 기준선: 홈팀이 항상 승리 | 0.536 |
| 기준선: 승률 높은 팀이 승리 | 0.594 |

해석할 때 주의할 점입니다.

- 승률 기준선 대비 정확도 차이는 약 0.9%p, 224경기 중 약 2경기 분량입니다. 통계적으로 의미 있는 우위라고 말하기 어렵습니다.
- 로그 손실 0.682는 동전 던지기 수준(0.693)에 가깝습니다. v0.1은 결과가 아니라 기준선입니다.
- JSON의 계수는 분할 학습 모델의 값입니다. 실제로 사용하는 `models/win_model.pkl`은 702경기 전체로 다시 학습한 모델입니다.

## 공개 파일

`data/public/`에 매 실행마다 갱신됩니다. 사이트에서는 아래 주소를 기준으로 읽을 수 있습니다.

`https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/`

| 파일 | 내용 |
| --- | --- |
| [`latest.json`](data/public/latest.json) | 오늘 경기 예측: 팀, 구장, 시간, 홈 승률, 기여도(`contribution_pp`) 상위 4개 요인, 메타(`generated_at`, `commit_sha`, `run_url`, `model_version`, `mode`) |
| [`history.csv`](data/public/history.csv) | 과거 예측과 결과 기록: date, game_id, home, away, home_win_prob, model_version, predicted_at, status, winner, correct |
| [`status.json`](data/public/status.json) | 파이프라인 상태: generated_at, run_url, commit_sha, mode, next_game_date, games_today, model_version (경기가 없는 날도 갱신) |

## 자동 실행

[`.github/workflows/daily.yml`](.github/workflows/daily.yml)이 매일 09:00, 17:00 KST(UTC `0 0`, `0 8`)와 수동 실행(`workflow_dispatch`)으로 [`scripts/run_pipeline.py`](scripts/run_pipeline.py)를 돌립니다. 결과는 `github-actions[bot]`이 `data/raw`, `data/public`을 `auto: predictions YYYY-MM-DD-HHMM` 메시지로 커밋합니다. 첫 실제 실행: [Actions run](https://github.com/kimminseo2323-prog/2610_KBO_predict/actions/runs/40533547898).

## 로컬 실행

```bash
pip install -r requirements.txt && pip install -e .
python -m kbo_predict.collect --from 2026-03-20 --to 2026-11-05   # 약 65분 (요청 간 5초)
python -m kbo_predict.train_win --season 2026 --split-date 2026-08-01
python scripts/run_pipeline.py [--date YYYY-MM-DD] [--no-fetch]
```

테스트는 `pytest -q`입니다 (43개).

## 데이터 출처

- 데이터 출처: [MyKBOStats](https://mykbostats.com) (비공식 팬 사이트). robots.txt의 `Crawl-delay: 5`를 지켜 요청 간 5초를 두고, 주간 일정 페이지와 경기 박스스코어 페이지를 파싱합니다. 개인 학습용입니다.
- KBO 공식 사이트는 약관상 크롤링이 금지되어 사용하지 않습니다.
- 네이버 스포츠의 내부 API는 Python 클라이언트를 차단해(TLS/UA 수준) 수집 대상에서 뺐습니다. 우회는 시도하지 않았습니다.

## 로드맵

1. 2015~2025 데이터 백필, 노트북 01
2. 선발투수 정보 소스 확보, LightGBM, 확률 보정, SHAP, report/live 두 모델 분리
3. 선수 유형 클러스터링
4. py와 ipynb 결과 동일성 검증(parity), 주간 재학습, 되감기 모드
5. Genspark + GitHub Pages 사이트
6. README 정리와 한 달 무인 운영

## 문서

- 설계 문서: [docs/superpowers/specs/2026-10-27-kbo-predict-design.md](docs/superpowers/specs/2026-10-27-kbo-predict-design.md)
- 구현 계획: [docs/superpowers/plans/2026-10-27-stage0-vertical-slice.md](docs/superpowers/plans/2026-10-27-stage0-vertical-slice.md)
- 데이터 조사: [docs/research/kbo-data-sources.md](docs/research/kbo-data-sources.md)
- 디자인 시스템: [DESIGN_clay.md](DESIGN_clay.md)

저장소: https://github.com/kimminseo2323-prog/2610_KBO_predict
