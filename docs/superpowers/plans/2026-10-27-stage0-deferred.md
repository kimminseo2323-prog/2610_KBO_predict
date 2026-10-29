# 0단계 이월 항목 (리뷰에서 나온 Minor, 다음 단계에서 처리)

0단계 수직 슬라이스 v0.1 리뷰(태스크별 + 최종 전체)에서 "지금 고치지 않아도 되지만 잊으면 안 되는" 항목. 처리 시점 기준으로 묶음.

## 1단계(백필·노트북 01) 전에
- ✅ (7ba1961, 8dd9e57) `seasons.REGULAR_SEASON`에 2027 시즌 추가 — 없으면 2027년 3월 일일 실행이 `KeyError`로 실패. 2015~2025 백필 시 각 시즌 범위도 함께 기입. → 2015~2026 범위를 데이터에서 도출해 기입했고, 2027 항목 대신 미등록 시즌은 03-01~10-31 폴백 + 경고로 처리해 `KeyError`가 나지 않게 했다.
- ✅ (feaa21c) `mykbo_parse._int`가 비숫자 셀을 0으로 바꿈 → 선수 스탯 집계 전에 결측(None) 처리로 변경 (3단계 클러스터링 오염 방지).
- ✅ (c35ad46) `boxscores.jsonl.gz`가 시즌 단위 단일 blob으로 매일 재커밋됨 → 월별 분할 또는 주기적 압축 검토. → `data/raw/{season}/boxscores/{YYYY-MM}.jsonl.gz` 월별 분할.
- ✅ (5522a19, b1fcc66) 수집 실패 시 Actions가 이슈를 자동 생성 (`issues: write`, 스펙 14절). → `collect-failure` 라벨 이슈 생성/코멘트 (`scripts/collect_errors.py`).
- ✅ (babbbae, a9601c4) 사이트에 LIVE로 멈춘 2경기(13352 04-22 HH@LG, 13606 06-19 SS@HH): 경기 페이지 상태로 보정하는 규칙 검토. → 페이지가 FINAL이고 양 팀 점수가 있을 때만 보정, 아니면 LIVE 유지·학습 제외. 두 경기는 보정되지 않고 LIVE로 남는다.
- ✅ (babbbae, a9601c4; 파서 보강 2a3ca76, b2219ec, 61288f6) 미인식 경기 페이지(챌린지·인터스티셜 200 응답) 하나가 전체 실행을 중단시킴 → 경기 단위로 잡아서 status.json은 갱신되게. → 경기 단위 실패는 `status.json`의 `collect_errors`에 기록하고 실행을 계속한다. Delayed·빈 행·LIVE 보조 행 파서 보강 포함.

## 2단계(모델 고도화) 전에
- ✅ (5435ed1, f3210bf) 요인 분해 합 항등식 테스트 추가 (Σfactors ≈ logit(p)·p(1−p)·100) — SHAP로 교체 시 함께. → `explain`이 보정 전 로그 오즈를 정확히 나누는지(`contrib.sum + base == logit(p_raw)`) LR·LightGBM 각각 검사하고(`test_explain_identity_lr/lgbm`), pp 변환이 Platt 기울기를 반영하는지도 검사한다(`test_factor_pp_applies_platt_slope_exactly`).
- ✅ (5435ed1, 24aff45) `train_win` CLI·분할 경계 테스트, 빈 테스트 프레임에 친절한 에러. → CLI는 `python -m kbo_predict.train_win report|live`로 바뀌었고 `test_cli_report_then_live`가 돌린다. 빈 학습·보정 프레임과 빠진 시즌은 `ValueError`로 거절한다.
- (유지 → 5단계 사이트) `latest.json`의 CANCELED 항목은 `home/away`에 `code`만 있고 `round`가 없음 → 사이트 구현 시 선택 필드로 처리하거나 정상 항목과 모양 통일.
- (유지) 재편성(같은 game_id로 날짜 변경) 시 history 행의 date 미갱신 — 현재 데이터상 재편성은 새 id를 받으므로 보류.
- (유지) `seasons.REGULAR_SEASON`에 2027 시즌 범위 등록 (2027-03 개막 전; 미등록이면 폴백 + collect-failure 이슈로 알림)

## 3단계(클러스터링) 전에
- 2015~2018 일부 박스스코어에서 타자 득점 합/투수 실점 합이 팀 점수와 1 차이 (예: 2016 4292, 2017 5302, 2018 6069/6161/6605) — 사이트 원본 문제; 집계 전 검증 규칙 필요
- 선수 한글 이름 소스: MyKBOStats는 이름을 로마자로만 준다(예: "Choi Won-tae"). `players.json`·사이트 표시에 한글 이름을 쓰려면 별도 매핑 소스가 필요하다.
- 유형 상성 피처 전후 비교: `model_report.json`의 `matchup_feature_ablation`이 아직 `null`. 3단계에서 같은 프로토콜(2015~2024 / 2025 / 2026)로 넣기 전·후를 채운다.
- 정규시즌 예정 경기 페이지에도 "Starting pitchers" 섹션이 있는지 2027 개막 전 확인. 파서 픽스처는 포스트시즌 페이지(14050) 하나뿐이다.
- 예고 선발 변경 이력 활용: `starters.jsonl`은 경기당 가장 최근 발표만 남긴다(덮어쓰기). 예고 변경·예고와 실제 불일치를 분석하려면 이력을 따로 쌓아야 한다.

## 4단계(parity) 전에
- 수집 창(대상일 −7~+14일)을 벗어난 FINAL 경기의 박스스코어 누락은 재시도되지 않음 → run_pipeline에 '현재 시즌 FINAL인데 박스스코어 없음' 검사 추가
- 노트북 패키지(matplotlib/nbconvert/ipykernel)를 `requirements-dev.txt`로 분리해 일일 Actions 설치 시간 단축
- `tests/test_notebooks.py` 실행 테스트에 slow 마커, ci.yml에서 선택 실행
- `run_pipeline.run()`의 `data_dir`가 raw_store에 전달되지 않음(공개 파일에만 적용) → raw_store에 data_dir 주입하거나 문서화. CLI 상대경로는 cwd 의존.
- `upsert_games`, `_write_json`, `_write_history` 비원자적 쓰기 → 임시 파일 + replace.
- `models/manifest.json`은 `report`/`live` 어느 쪽을 돌려도 두 pkl 모두에 새 `features_sha256` 하나를 붙인다 → 다시 학습하지 않은 pkl에도 새 해시가 붙으므로 모델별로 학습 당시 해시를 기록.
- pkl 바이트는 번들의 `trained_at` 때문에 실행마다 달라진다(모델 파라미터와 예측은 재현됨) → parity는 pkl 해시가 아니라 예측·지표로 비교하거나 `trained_at`을 고정.
- `train_win.py`가 약 500줄(리뷰 시점 441줄, 현재 497줄) → 평가 함수(지표·기준선·McNemar·캘리브레이션 표)를 `evaluate.py`로 분리 검토.
- `build_dataset`·`features` CLI가 빈 시즌 목록이나 `--seasons START END`에서 START > END일 때 조용히 빈 결과를 낸다 → 에러로.
- 노트북 03이 02가 만든 `data/processed/features.parquet`에 의존 → 없으면 03에서 생성하도록(노트북 단독 실행·parity 순서 문제 방지).
- 경기 없는 날에도 `fetch_starters`를 호출함 → 오늘 경기가 없으면 요청 생략(5초 절약, 불필요한 요청 줄이기).
- `predict.py` docstring의 요인 "27개"(피처 26 + 기본값)는 선발 없는 19피처 번들에는 맞지 않음 → "번들 피처 수 + 1"로 표현.
- 누수 가드 테스트 추가: 테스트 시즌(2026)의 `y`를 뒤집어도 검증 지표·트리 수·캘리브레이션·알고리즘·비교 대상 선택이 바뀌지 않음을 확인.

## 정리만 하면 되는 것
- `tests/test_mykbo_parse.py`의 `or len(rows) == 4` 무의미 단언, `test_collect` 중복 조건문, `test_features` unused import, `scaler.transform` 중복 호출, `publish.py` 인라인 import.
- `features.build_training_frame`: FINAL인데 점수 하나만 None이면 TypeError (파서는 만들지 않는 상태).
- 미인식 라벨 + `<time>` 있는 주간 행이 SCHEDULED로 통과 (raise 안 함).
- 4xx 응답도 1회 재시도 (5초 낭비).
- 푸시 시 다른 작성자와 data 파일 충돌하면 잡 실패 (rebase는 넣었음).
- `apply_calibrator`가 캘리브레이터 종류를 `isinstance(…, LogisticRegression)`로 분기 → 번들의 `calibration` 이름으로 분기하거나 캘리브레이터에 방법을 함께 저장.
- `apply_calibrator(None, p)`가 입력을 `np.asarray`로 바꾸기 전에 그대로 돌려줌 → 반환 형식 통일.
- `tests/test_train_win.py`가 `scipy`를 쓰지만 `requirements.txt`에 고정되어 있지 않음(scikit-learn 의존성으로 설치됨) → 명시적 고정.
- 커밋된 `latest.json`·`status.json`의 `commit_sha`·`run_url`이 로컬 생성이라 `null` → 다음 Actions 실행이 덮어쓴다. 로컬에서 학습한 `model_report.json`·`models/manifest.json`도 `commit_sha: null`이므로 재학습을 Actions로 옮길 때(4단계) 채워지는지 확인.
