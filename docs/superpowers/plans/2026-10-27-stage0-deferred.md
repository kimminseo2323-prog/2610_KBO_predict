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
- ✅ (39754b5, 53e7cdb) `latest.json`의 CANCELED 항목은 `home/away`에 `code`만 있고 `round`가 없음 → 사이트 구현 시 선택 필드로 처리하거나 정상 항목과 모양 통일. → 모양은 그대로 두고 사이트가 선택 필드로 처리한다: 취소 카드(`--surface-strong`, "취소" + `status_note`, 확률·요인 없음), 검증 fixture `tests/fixtures/site/latest_edge.json`(정상·선발 미정·취소)과 홈의 `?fixture=edge`.
- (유지) 재편성(같은 game_id로 날짜 변경) 시 history 행의 date 미갱신 — 현재 데이터상 재편성은 새 id를 받으므로 보류.
- (유지 → "6단계 전에"의 **필수 관문**) `seasons.REGULAR_SEASON`에 2027 시즌 범위 등록 (2027-03 개막 전; 미등록이면 폴백 + collect-failure 이슈로 알림)

## 3단계(클러스터링) 전에
- (유지) 2015~2018 일부 박스스코어에서 타자 득점 합/투수 실점 합이 팀 점수와 1 차이 (예: 2016 4292, 2017 5302, 2018 6069/6161/6605) — 사이트 원본 문제; 집계 전 검증 규칙 필요. → 3단계 유형 군집은 비율 지표(K%·BB%·HR%·ISO·BABIP·도루율 / 선발 비중)만 쓰고 득점·실점을 쓰지 않아 영향이 없다. 득점·실점을 쓰는 지표가 생기면 다시 본다.
- ✅ (0ea85de, 955b0d0, 202ced3, 3e8d3ee) 선수 한글 이름 소스: MyKBOStats는 이름을 로마자로만 준다(예: "Choi Won-tae"). `players.json`·사이트 표시에 한글 이름을 쓰려면 별도 매핑 소스가 필요하다. → 경기 페이지 기록표의 한글 `title` 속성을 영문 항목과 순서로 맞춰 모으고 시즌별 투표로 정한다(3표 이상인 가장 최근 시즌의 60% 다수 이름, 개명 선수는 최근 이름; 1,604명). 개명 선수 31명은 별칭(`data/raw/name_aliases.json`). `players.json` 2,918개 선수-시즌 중 2,906개에 `name_ko`가 있다.
- ✅ (7d79821, e8143d3, 5de4b57, f17d754) 유형 상성 피처 전후 비교: `model_report.json`의 `matchup_feature_ablation`이 아직 `null`. 3단계에서 같은 프로토콜(2015~2024 / 2025 / 2026)로 넣기 전·후를 채운다. → 채웠다. 검증 log loss .67711 → .67783, 시험 정확도 .594 → .591, McNemar p = .845로 `adopt: false`. 라이브 v0.2는 그대로다.
- (유지) 정규시즌 예정 경기 페이지에도 "Starting pitchers" 섹션이 있는지 2027 개막 전 확인. 파서 픽스처는 포스트시즌 페이지(14050) 하나뿐이다.
- (유지) 예고 선발 변경 이력 활용: `starters.jsonl`은 경기당 가장 최근 발표만 남긴다(덮어쓰기). 예고 변경·예고와 실제 불일치를 분석하려면 이력을 따로 쌓아야 한다.

## 4단계(parity) 전에

4단계 완료(2026-10-29, `docs/superpowers/plans/2026-10-29-stage4-automation.md`): 처리한 항목은 ✅와 커밋, 남은 항목은 (유지).

- ✅ (f9e6be8, 4d1c4f6) 수집 창(대상일 −7~+14일)을 벗어난 FINAL 경기의 박스스코어 누락은 재시도되지 않음 → run_pipeline에 '현재 시즌 FINAL인데 박스스코어 없음' 검사 추가 → `collect.collect_missing_boxscores(season, before=대상일−7일)`: 수집 창 이전의 정규시즌 FINAL 중 박스스코어 없는 경기를 최신순 최대 20개 다시 요청한다. 예고 선발 수집 뒤 별도 try에서 돌고 오류는 `collect_errors`에 남긴다(같은 실행에서 창 안의 경기를 두 번 요청하지 않음).
- ✅ (98bb49e) 노트북 패키지(matplotlib/nbconvert/ipykernel)를 `requirements-dev.txt`로 분리해 일일 Actions 설치 시간 단축 → `requirements-dev.txt` = `-r requirements.txt` + pytest·matplotlib·nbformat·nbclient·nbconvert·ipykernel. 일일은 `requirements.txt`, ci·주간은 dev.
- ✅ (98bb49e) `tests/test_notebooks.py` 실행 테스트에 slow 마커, ci.yml에서 선택 실행 → ci는 `pytest -m "not slow"`(최종 수정 뒤 337개) + `check_parity --quick`. slow 6개(노트북 01~05 실행 + 실데이터 parity)는 로컬에서. 노트북 02~05는 주간 재학습의 전체 `check_parity`가 Linux에서도 실행한다(최종 수정 라운드).
- (유지) `run_pipeline.run()`의 `data_dir`가 raw_store에 전달되지 않음(공개 파일에만 적용) → raw_store에 data_dir 주입하거나 문서화. CLI 상대경로는 cwd 의존. → 원본 위치는 지금 `KBO_DATA_DIR` 환경 변수로만 바뀐다(노트북 05의 parity 셀이 이 방법을 쓴다).
- ✅ (f9e6be8, 4d1c4f6) `upsert_games`, `_write_json`, `_write_history` 비원자적 쓰기 → 임시 파일 + replace. → `publish._atomic_write`(`*.tmp` → `os.replace`)를 공개 JSON·`history.csv`가, `raw_store._write_jsonl_atomic`을 `upsert_games`·`upsert_starters`가 쓴다. `*.tmp`는 gitignore.
- ✅ (2단계) `models/manifest.json`은 `report`/`live` 어느 쪽을 돌려도 두 pkl 모두에 새 `features_sha256` 하나를 붙인다 → 다시 학습하지 않은 pkl에도 새 해시가 붙으므로 모델별로 학습 당시 해시를 기록. → 모델별 항목(`report`·`live`·`team`·`clusters`)이고 각 명령은 자기 항목만 갱신한다. 4단계에서 플랫폼 독립 값 지문(`features_fingerprint`, `matchup_fingerprint`)과 `seasons`를 더했다(1146848, ace0de5).
- ✅ (39cb7bb) pkl 바이트는 번들의 `trained_at` 때문에 실행마다 달라진다(모델 파라미터와 예측은 재현됨) → parity는 pkl 해시가 아니라 예측·지표로 비교하거나 `trained_at`을 고정. → `check_parity`는 다시 학습한 번들과 커밋된 pkl의 예측(8,465행, atol 1e-9)을 비교하고, 주간 재학습은 `train_win live --skip-if-same`으로 예측이 같으면 pkl을 쓰지 않는다.
- (유지) `train_win.py`가 약 500줄(리뷰 시점 441줄, 3단계 497줄, 4단계 뒤 758줄 — `train_team`·`same_predictions`·값 지문 추가) → 평가 함수(지표·기준선·McNemar·캘리브레이션 표)를 `evaluate.py`로 분리 검토.
- (유지) `build_dataset`·`features` CLI가 빈 시즌 목록이나 `--seasons START END`에서 START > END일 때 조용히 빈 결과를 낸다 → 에러로.
- (유지) 노트북 03이 02가 만든 `data/processed/features.parquet`에 의존 → 없으면 03에서 생성하도록(노트북 단독 실행·parity 순서 문제 방지). → `check_parity`는 02 → 05 순서로 실행해 문제가 드러나지 않는다.
- ✅ (f9e6be8) 경기 없는 날에도 `fetch_starters`를 호출함 → 오늘 경기가 없으면 요청 생략(5초 절약, 불필요한 요청 줄이기). → 오늘 SCHEDULED 경기가 없으면 경기 페이지를 요청하지 않는다(`test_no_fetch_starters_when_no_games`).
- ✅ (f9e6be8) `predict.py` docstring의 요인 "27개"(피처 26 + 기본값)는 선발 없는 19피처 번들에는 맞지 않음 → "번들 피처 수 + 1"로 표현.
- (유지) 누수 가드 테스트 추가: 테스트 시즌(2026)의 `y`를 뒤집어도 검증 지표·트리 수·캘리브레이션·알고리즘·비교 대상 선택이 바뀌지 않음을 확인.

3단계(클러스터링) 리뷰에서 나온 항목:
- (유지) 상성 피처는 라이브에 반영하지 않았다(`adopt: false`). 나중에 채택한다면 `bat_type{t}_diff` 열은 합이 0이라 공선성이 있으므로 하나를 빼고, 2015 행은 직전 시즌(2014) 유형이 없어 상성 정보가 전혀 없으므로 결측 플래그를 두거나 2016부터 쓴다.
- ✅ (f62a40a, 388d371; 최종 수정에서 바꿈) 주간 재학습 워크플로에 `python -m kbo_predict.cluster fit`과 `cluster publish`를 포함한다. 지금은 일일 Actions가 `players.json`·`teams.json`을 다시 만들지 않는다(수동 실행). → `weekly_retrain.yml`이 군집 후보를 맞춰 `cluster compare --types`로 커밋본과 비교한다. 처음에는 유형표 해시가 바뀌면(`types_changed=1`) 정식 `cluster fit` + `publish`까지 자동으로 했지만, clusters-2026은 report-2026·되감기·`players.json`이 함께 기대는 **얼린** 산출물이라 최종 수정 라운드에서 "`types_changed=1` = 명시적 실패(frozen cluster inputs changed — refreeze by hand)"로 바꾸고 자동 fit·publish 단계를 뺐다. compare가 실패하면 커밋본을 유지하고 `parity-failure` 이슈.
- (유지 → 2027 시즌 전) 2027 유형 재적합 범위: 2027 시즌에는 중심을 2015~2026으로 맞추고 2027은 배정만 한다(스펙 §5.1 "2027 시즌이 끝나면 `report` 모델을 … 한 번 옮긴다"는 시점과 같다). 버전 이름(`clusters-2026`)과 `cluster_labels.yaml`의 이름도 다시 본다.
- ✅ (39cb7bb, 1146848) Linux BLAS parity: 군집은 단일 스레드로 같은 기계에서는 비트 단위로 재현되지만 Actions(Linux OpenBLAS)에서는 마지막 자리가 다를 수 있다. `models/manifest.json`의 `clusters.types_sha256`으로 비교하고, 다르면 커밋된 `models/clusters.pkl`을 기준으로 둔다. → `cluster compare`(중심 atol 1e-9, 맞춤 시즌 라벨 동일) + 유형표 해시 비교. Linux ci(실행 40882643905)에서 유형표 해시·군집이 같았고, 다른 것은 `features.parquet` 파일 바이트뿐이라 parquet 판정을 값 지문으로 바꿨다.
- (유지) `run_pipeline`이 매 실행 `models/clusters.pkl` 전체(약 1.4 MB)를 unpickle해 선발 유형만 꺼낸다 → `(season, player_id) → 투수 유형`만 담은 작은 types JSON 캐시를 검토.
- (유지) `players.json`(1.77 MB, gzip -9 기준 약 270 KB)이 시즌이 쌓여 더 커지면 시즌별 분할을 검토.
- 주의: `train_win report`를 `--matchup`·`--clusters` 없이 돌리면 `model_report.json`의 `matchup_feature_ablation`·`cluster_quality` 두 블록이 null로 초기화된다. 보고서를 다시 만들 때는 두 옵션을 함께 준다(README "로컬 실행"). → 이제 기존 보고서에 두 블록이 있으면 `report --force`가 옵션 없이는 정식 명령을 알려 주며 거부한다(일부러 지우려면 `--reset-blocks`).
- (유지) 일일 수집(`collect.py`)은 `parse_game`을 한글 이름 힌트(`ko_names`)·별칭 없이 부른다 → 새 경기의 기록표 미매칭이 재파싱보다 조금 많을 수 있다. 주간 작업에서 재파싱 스크립트를 돌리거나 힌트를 넘기는 것을 검토.
- (유지) 테스트 소소:
  - `test_pipeline`의 선발 유형 라벨 이름 assert가 tmp 폴더 chdir 때문에 기본 이름("유형 n")으로 떨어질 수 있다 → 기대 이름을 리터럴로 단언.
  - `site_data.teams_payload`의 쓰이지 않는 `labels` 인자 정리.
  - 재파싱 스크립트의 `infer_aliases`(5경기·로스터 교집합 1명·다수결 이름 보호) 단위 테스트 추가.
  - 기록표 HR-off(피홈런 투수) 칸에서 이미 아는 한글 이름을 먼저 붙이는 패스가 토큰을 떨어뜨리는 경우가 있다 → 확인·테스트.
  - 재파싱 스크립트가 박스스코어가 없는 시즌을 만나면 중단된다 → 건너뛰고 보고.
- (유지) `models/manifest.json` 상단의 `commit_sha`는 마지막으로 쓴 명령(train_win/cluster) 기준이라 모델마다 만든 커밋이 다를 수 있다 → 항목별 커밋 기록 검토.
- (유지) 시즌 중 이적한 선수는 `roster_types`에서 그 시즌 주팀(출전 경기가 가장 많은 팀)에 전부 귀속된다 → 팀별 PA·아웃으로 나누는 것을 검토.
- (유지) 직전 시즌 유형만 쓰는 규칙 때문에 한 시즌을 쉬고 돌아온 선발은 유형이 표시되지 않는다(예: Shirakawa, 2024·2026만 자격) → 가장 최근 자격 시즌으로 대체할지 검토(상성 피처에도 같은 규칙을 써야 누수 규칙이 같아진다).


## 5단계(사이트) 전에

4단계 실행·리뷰에서 나온 항목. 사이트가 읽는 데이터 계약(스펙 §8)과 무인 운영에 걸리는 것부터.

5단계 완료(2026-10-30, `docs/superpowers/plans/2026-10-30-stage5-site.md`, 20d5e78 … 8a03e8b): 처리한 항목은 ✅, 남은 항목은 (유지) — 6단계에 걸리는 것은 아래 "6단계 전에"로 옮겼다.

- (유지 → "6단계 전에") **필수 관문 — 2027-03 전에 `seasons.REGULAR_SEASON[2027]` 등록(미등록이면 10월 포스트시즌이 정규시즌으로 집계됨).** 미등록 시즌은 03-01~10-31 폴백이라 개막 전 시범경기와 10월 포스트시즌 경기가 정규시즌으로 들어가 상태·학습·`playoff_race`·한글 이름 투표가 오염된다. 개막일·종료일이 정해지면 바로 넣고, `round`(시범경기 `preseason`)도 함께 확인한다.
  - 2027 시즌 행이 `teams.json`에 생기면 `site/assets/teams.js`의 순위표 메모 "`${season}` 시즌은 모델이 학습하거나 검증할 때 본 시즌이라 열을 뺐습니다"(학습·검증 시즌 문구)를 고친다 — 2027은 report-2026이 학습·검증에 쓰지 않은 시즌이라 이 문구가 틀린다.
- ✅ (최종 수정 라운드) 오늘 경기의 선발 포함 확률을 시리즈 시뮬레이션에 반영 → `predict.raw_prob`(예측 항목·되감기 판정과 같은 함수)를 `run_pipeline`이 `outlook_for(today_probs=…)`로 넘기고, 첫 남은 경기(홈 일치 확인)만 그 확률로 굴린다. 카드에 `today_game_prob_source`. 10-29: 시리즈 SS .5279 → .5579(오늘 3차전 SS .5536).
- ✅ (최종 수정 라운드) 와일드카드 1승 어드밴티지 → `postseason.yaml`의 `head_start: [h0, h1]`(전적에 더하고 `homes`는 실제 경기만). 2026 와일드카드 = `best_of: 3, head_start: [1, 0], homes: [LG, LG]`. 처음 설정(`best_of: 1`)은 5위가 1차전을 이기면 바로 끝나 틀렸다.
- ✅ (최종 수정 라운드) 노트북 05 다듬기: 셀 40 "작성 시점에는", 셀 6 "우천"·"대구" → "취소 사유는 데이터에 없음"·"삼성 홈", 셀 33 "59~61%", 셀 20은 공개 함수(`simulate.active_series`·`series_record`·`left_homes`·`series_probs`)만 쓴다. `check_parity.REQUIRED_NOTEBOOKS = ("02", "03", "04", "05")`.
- ✅ (최종 수정 라운드) 노트북 03·04의 동일성 assert가 비트 비교(Windows에서만 통과)였고 ci `--quick`은 노트북을 돌리지 않았다 → 03·04는 `kbo_predict.parity`(값 지문, 실수 상대 1e-9, 예측 `atol 1e-9`)로 판정하고, `weekly_retrain.yml`이 전체 parity(노트북 포함, `--require-live`)를 돌린다.
- ✅ (최종 수정 라운드) `live --skip-if-same`은 예측이 같아도 manifest의 `live.features_fingerprint`가 다르면 다시 쓴다. `train_win._write_json`은 원자적(`publish._write_json`, 바이트 동일). `check_parity --repo`·`build_rewind` 기본 경로는 저장소 루트 기준. `test_rewind_matches_report_model`은 `build_dataset([2025, 2026])`으로 ci에서도 돈다.
- 주간 재학습 첫 실행 확인(2026-11-02 월 03:07 KST): 전체 parity(노트북 02~05, Linux)가 처음으로 Actions에서 돈다 — 노트북 실행 시간·한글 폰트 경고와 통과 여부를 본다. `types_changed=1`(이제 명시적 실패) 경로는 Actions에서 아직 돈 적이 없다(지금 데이터로는 유형표가 그대로). `workflow_dispatch`로 한 번 돌려 보고, Actions에서 만든 manifest·pkl의 `commit_sha`가 채워지는지도 본다.
- (유지) `history.csv`는 지금 1행(2026-10-29 14050, v0.2, 정산 전)뿐이다 → 라이브 적중률은 포스트시즌·2027 기록이 쌓인 뒤에 사이트에 보인다. 사이트(홈 적중률 카드·성적표 라이브 기록)는 행이 적으면 "라이브 기록은 2026 포스트시즌부터 쌓여 아직 표본이 적습니다"를 적는다.
- ✅ (91f78bd) 커밋된 `latest.json`(10-29 14:40 Actions 실행)에는 아직 `outlook`이 없다 → 다음 일일 실행(10-30 09:07)에서 `outlook` 블록이 들어가는지 확인. → 10-30 00:12 실행의 `latest.json`에 `outlook`(`type: "series"`)이 있고 홈 전망 카드가 그린다.
- ✅ Genspark 내보내기·외부 `fetch()` 가능 여부 확인(사용자, 스펙 §9). 안 되면 `site/`를 직접 만들어 GitHub Pages로. → 둘 다 된다(내보내기는 CSS·JS가 들어간 단일 HTML + Cloudflare beacon 스크립트 1개, 캐시 버스트 `fetch`). 그래도 `site/`를 먼저 직접 만들어 Pages로 공개했고, Genspark는 브리프(`docs/site/genspark-brief.md`) + 반영 스크립트(`scripts/import_site.py`)로 선택적 교체.
- 2027 라이브 팀 모델: 라이브 `outlook`도 `team-2026`(2015~2024 학습)을 쓴다. 2027 시즌 전에 2015~2026으로 학습한 라이브 팀 모델을 주간 재학습에 넣는다(되감기는 `team-2026` 그대로).
- (유지) 시뮬레이션 상태 갱신 없음: 남은 경기를 모두 기준 날짜 상태로 계산한다(한 경기 결과가 다음 경기의 승률·최근 10경기·불펜 피로 피처를 바꾸는 효과 무시). 시즌 초 가을야구 확률이 너무 확신에 차 보이는지 사이트에서 보고 필요하면 주 단위 상태 갱신을 검토. → 팀 페이지 "가을야구 확률 되감기"(7일 간격)에서 볼 수 있게 됐다. 판단은 6단계에서.
- 예고 선발 이력: `starters.jsonl`은 경기당 가장 최근 발표만 남긴다(3단계 항목과 같음). 되감기는 그래서 실제 선발을 쓴다. 2027부터 예고 발표 이력을 따로 쌓으면 "예고 vs 실제" 차이와 라이브 성적 차이를 설명할 수 있다.
- 6자리 지문 경계 위험: `features_fingerprint`는 실수를 소수 6자리로 반올림하므로, 어떤 값이 반올림 경계에 정확히 걸리면 플랫폼에 따라 지문이 달라져 ci가 실패할 수 있다(지금은 Linux·Windows 같음). 그런 실패가 나면 `assert_frame_equal(rtol=1e-9)` 값 비교로 판정을 옮기는 것을 검토.
- 박스스코어 재수집 반복 요청: 같은 실행 안의 2중 요청은 수집 창 이전(`before`)으로 잘라 없앴지만(4d1c4f6), 끝내 받을 수 없는 옛 FINAL 경기는 하루 두 번 실행마다 다시 요청된다(최대 20개 × 5초). 실패 횟수 기록·포기 규칙 검토(지금 2026에는 박스스코어 없는 정규시즌 FINAL 0경기). 최종 수정 라운드부터 얼린 시즌(2015~2026)은 재수집하지 않고(얼린 산출물 parity 보호), 수집이 예외로 멈춘 실행도 재수집을 건너뛴다 — 그래서 이 문제는 2027부터 다시 생긴다. 한글 이름 투표는 정규시즌 FINAL 기록표만 센다(`korean_names`).
- 등록된 포스트시즌 시리즈가 데이터에서 끝나지 않은 채 남으면(예: 마지막 경기가 LIVE로 멈춤) 다음 시리즈가 시작될 때까지 "진행 중" 카드로 보인다.
- `config/postseason.yaml`은 사람이 갱신한다: 2026 한국시리즈 상대(`teams: [KT, null]`, `start: null`)를 플레이오프가 끝나면 채운다. 2027부터 대진을 데이터에서 도출할 수 있는지 검토.
- 테스트 소소: 같은 날 2경기(더블헤더) 합성 되감기 테스트, `rewind._raw_prob`와 `predict`의 확률 계산 중복, 쓰기 도중 실패하는 원자적 쓰기 테스트, 등록되지 않은 시즌의 `round` 폴백 테스트.

## 6단계(마무리·무인 운영) 전에

5단계 실행·리뷰에서 나온 항목과 5단계에서 넘어온 관문.

- **필수 관문 — 2027-03 전에 `seasons.REGULAR_SEASON[2027]` 등록**(위 "5단계 전에"의 첫 항목 그대로). 미등록이면 2027 시범경기·10월 포스트시즌이 정규시즌으로 집계된다. 사이트는 되감기 시즌을 코드에 고정했다(홈 `home.js`의 `REWIND = "rewind/2026"`, 팀 `teams.js`의 `REWIND_SEASON = 2026` — 되감기 파일이 2026만 있음). 2027 되감기를 만들면 함께 바꾼다.
- **Genspark 제작본 도착 시 교체 판단**: 사용자가 브리프로 만든 zip을 주면 `import_site.py --dry-run` → 반영 → `check_site.py --strict` → 1280px·360px 스크린샷으로 지금 Pages 버전과 비교해 사용자가 정한다. 반영 스크립트는 기존 `site/assets/`를 남겨 두므로(단일 파일 내보내기면 쓰이지 않는 파일이 남음) 교체가 확정되면 안 쓰는 assets 정리와 `check_site`의 상수 검사(`assets/app.js` 기준)가 새 페이지에도 의미가 있는지 다시 본다.
- **한 달 무인 운영 확인**(스펙 §12 item 6): 일일 2회·주간 재학습·ci·pages 워크플로가 사람 손 없이 도는지, `collect-failure`·`parity-failure` 이슈, 사이트 증거 바의 갱신 시각·실행 번호가 매일 바뀌는지 본다. 주간 재학습 첫 실행은 2026-11-02(위 항목).
- **Pages 첫 배포**: `pages.yml`의 `enablement: true`가 첫 실행에서 Pages를 켠다. 첫 실행 전에는 URL이 404이고, 실패하면 저장소 Settings → Pages의 source를 "GitHub Actions"로 직접 켠다.
- **팀 페이지 되감기 차트 끝 이름 겹침**: 가을야구 확률 되감기 선 그래프의 오른쪽 끝 팀 이름이 확률이 비슷한 팀끼리(특히 0%·100% 근처) 겹친다 → 이름 위치를 겹치지 않게 밀거나 범례로.
- **홈 틸 "선수 유형 지도" 카드의 빈 공간**: 데스크톱 벤토에서 틸 카드 아래쪽이 비어 보인다 → 미니 지도 높이·유형별 인원 배치 조정.
- **성적표 신뢰도 곡선 캡션(360px)**: 모바일 폭에서 캡션이 길어 줄바꿈이 어색하다 → 짧은 문구 또는 차트 아래 표로.
- **흰 글자 + 핑크 pill 대비를 시스템 규칙으로**: 핑크(#ff4d8b) 위 흰 작은 글자는 대비가 모자라 페이지마다 ink + 크림 inset으로 피해 갔다(스펙 13절 5단계) → `DESIGN_clay.md`·`tokens.css`·`app.css`에 "핑크 위 14px 이하 글자는 ink" 규칙을 하나로 적고 `test_card_colors_and_text_contrast_rules`에 pill까지 넣는다.
- **`site/_preview.html` 정리**: Task 1의 로컬 미리보기 전용 페이지(gitignore라 배포되지 않음). 사이트가 완성됐으니 지우거나 `scripts/`로 옮긴다.

## 정리만 하면 되는 것
- `tests/test_mykbo_parse.py`의 `or len(rows) == 4` 무의미 단언, `test_collect` 중복 조건문, `test_features` unused import, `scaler.transform` 중복 호출, `publish.py` 인라인 import.
- `features.build_training_frame`: FINAL인데 점수 하나만 None이면 TypeError (파서는 만들지 않는 상태).
- 미인식 라벨 + `<time>` 있는 주간 행이 SCHEDULED로 통과 (raise 안 함).
- 4xx 응답도 1회 재시도 (5초 낭비).
- 푸시 시 다른 작성자와 data 파일 충돌하면 잡 실패 (rebase는 넣었음).
- `apply_calibrator`가 캘리브레이터 종류를 `isinstance(…, LogisticRegression)`로 분기 → 번들의 `calibration` 이름으로 분기하거나 캘리브레이터에 방법을 함께 저장.
- `apply_calibrator(None, p)`가 입력을 `np.asarray`로 바꾸기 전에 그대로 돌려줌 → 반환 형식 통일.
- `tests/test_train_win.py`가 `scipy`를 쓰지만 `requirements.txt`에 고정되어 있지 않음(scikit-learn 의존성으로 설치됨) → 명시적 고정.
- 커밋된 `latest.json`·`status.json`의 `commit_sha`·`run_url`이 로컬 생성이라 `null` → 다음 Actions 실행이 덮어쓴다. 로컬에서 학습한 `model_report.json`·`models/manifest.json`도 `commit_sha: null`이므로 재학습을 Actions로 옮길 때(4단계) 채워지는지 확인. → (유지) 주간 재학습은 Actions에서 돌지만 첫 정기 실행(2026-11-02 월 03:07 KST) 전이라 아직 확인하지 못했다("5단계 전에").
