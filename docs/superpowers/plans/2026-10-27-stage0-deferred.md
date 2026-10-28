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
- 요인 분해 합 항등식 테스트 추가 (Σfactors ≈ logit(p)·p(1−p)·100) — SHAP로 교체 시 함께.
- `train_win` CLI·분할 경계 테스트, 빈 테스트 프레임에 친절한 에러.
- `latest.json`의 CANCELED 항목은 `home/away`에 `code`만 있고 `round`가 없음 → 사이트 구현 시 선택 필드로 처리하거나 정상 항목과 모양 통일.
- 재편성(같은 game_id로 날짜 변경) 시 history 행의 date 미갱신 — 현재 데이터상 재편성은 새 id를 받으므로 보류.

## 4단계(parity) 전에
- `run_pipeline.run()`의 `data_dir`가 raw_store에 전달되지 않음(공개 파일에만 적용) → raw_store에 data_dir 주입하거나 문서화. CLI 상대경로는 cwd 의존.
- `upsert_games`, `_write_json`, `_write_history` 비원자적 쓰기 → 임시 파일 + replace.

## 정리만 하면 되는 것
- `tests/test_mykbo_parse.py`의 `or len(rows) == 4` 무의미 단언, `test_collect` 중복 조건문, `test_features` unused import, `scaler.transform` 중복 호출, `publish.py` 인라인 import.
- `features.build_training_frame`: FINAL인데 점수 하나만 None이면 TypeError (파서는 만들지 않는 상태).
- 미인식 라벨 + `<time>` 있는 주간 행이 SCHEDULED로 통과 (raise 안 함).
- 4xx 응답도 1회 재시도 (5초 낭비).
- 푸시 시 다른 작성자와 data 파일 충돌하면 잡 실패 (rebase는 넣었음).
