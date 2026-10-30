# 사이트 데이터 계약

사이트(`site/`)는 `data/public/` 아래 파일만 읽습니다. 이 문서는 **커밋된 파일**(2026-10-30 기준)을 기준으로 각 파일의 키, 타입, 예시, null 규칙, 만드는 모듈을 적고, 페이지의 각 요소가 어느 키를 쓰는지 매핑 표로 고정합니다. 파일 모양은 바꾸지 않습니다(키 추가만 가능하고, 5단계에서는 추가하지 않음).

`scripts/check_site.py`는 맨 아래 [매핑 표](#매핑-표)를 읽어서, 표에 적힌 키 경로가 샘플 파일에 실제로 있는지 확인합니다. 표를 고치면 검사도 함께 바뀝니다.

## 읽는 법

- 위치: 로컬 미리보기(`localhost`, `127.0.0.1`)에서는 `../data/public/…`, 배포본에서는 아래 raw URL을 씁니다(`site/assets/app.js`의 `DATA_BASE`).
- 모든 요청에 `?v=<Date.now()>`를 붙여 브라우저 캐시를 피합니다. raw.githubusercontent.com의 CDN 캐시는 최대 5분이라, 갱신 직후에는 파일끼리 `generated_at`이 잠깐 어긋날 수 있습니다. 푸터는 `status.json`을 기준으로 씁니다.
- 읽기에 실패하면 빈 화면 대신 오류 문구와 "다시 불러오기" 버튼을 보여 줍니다(`showError`).
- 시각은 모두 KST(`+09:00`) ISO 문자열이고, 날짜는 `YYYY-MM-DD`입니다. 확률과 비율은 0~1 소수입니다(화면에서 %로 바꿈).
- 팀 코드: `OB` 두산, `LT` 롯데, `KT` KT, `WO` 키움, `SK` SSG, `SS` 삼성, `HH` 한화, `HT` KIA, `LG` LG, `NC` NC(`src/kbo_predict/teams.py`, 사이트 `TEAMS`).

### raw URL

| 파일 | URL |
| --- | --- |
| latest.json | https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/latest.json |
| status.json | https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/status.json |
| history.csv | https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/history.csv |
| rewind/2026/index.json | https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/rewind/2026/index.json |
| rewind/2026/{date}.json | https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/rewind/2026/2026-09-01.json (날짜 바꿔 씀) |
| players.json | https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/players.json |
| teams.json | https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/teams.json |
| model_report.json | https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/model_report.json |

### 키 경로 표기

매핑 표의 키 경로는 점으로 잇습니다. `[]`는 배열의 각 원소, `{}`는 키가 팀 코드나 유형 번호처럼 정해지지 않은 객체의 각 값입니다. 예: `games[].home.starter.type.name`, `outlook.teams{}.playoff_prob`, `teams[].vs{}`. CSV는 열 이름이 키입니다.

## 파일별 키

### status.json — 매 실행 갱신, 푸터 증거 바 전용

만드는 곳: `kbo_predict.publish.write_status` (`scripts/run_pipeline.py`, GitHub Actions 일일 실행). 경기가 없는 날에도 갱신됩니다.

| 키 | 타입 | 예시 | null 규칙 |
| --- | --- | --- | --- |
| `generated_at` | 문자열(ISO) | `"2026-10-30T00:11:32+09:00"` | 항상 있음 |
| `run_url` | 문자열 \| null | `".../actions/runs/40898946083"` | 로컬 실행이면 null → 푸터에 "로컬 실행" |
| `commit_sha` | 문자열 \| null | `"934464b6…"`(40자) | 실행한 커밋. git이 없으면 null → "커밋 —" |
| `mode` | `"live"` \| `"rewind"` | `"live"` | 오늘부터 14일 안에 취소되지 않은 경기가 있으면 live, 없으면 rewind(비시즌) |
| `next_game_date` | 문자열 \| null | `"2026-11-01"` | 다음 경기 날짜. 일정에 없으면 null |
| `games_today` | 정수 | `1` | 오늘 예측한 경기 수(0 가능) |
| `model_version` | 문자열 \| null | `"v0.2"` | 라이브 승패 모델 버전 |
| `collect_errors` | 문자열 배열 | `[]` | 수집 실패 메시지. 비어 있으면 정상 |

### latest.json — 오늘(또는 가장 최근) 경기 예측

만드는 곳: `kbo_predict.publish.write_latest` ← `predict.predict_game` / `predict.canceled_entry`, 전망은 `simulate.outlook_for`. 승패 모델 `v0.2`(2015~2026 학습, 라이브), 전망은 팀 모델 `team-2026` + 몬테카를로 1만 회.

| 키 | 타입 | 예시 | null 규칙 |
| --- | --- | --- | --- |
| `generated_at`, `commit_sha`, `run_url`, `model_version` | 메타 | status.json과 같은 값 | status.json과 같음 |
| `date` | 문자열 | `"2026-10-30"` | 예측한 날짜 |
| `mode` | 문자열 | `"live"` | latest.json은 항상 live |
| `games[]` | 배열 | 1~5개 | 경기가 없는 날은 파일이 갱신되지 않음(전날 그대로) |
| `games[].game_id` | 정수 | `14053` | |
| `games[].date`, `.time`, `.stadium` | 문자열 | `"18:30"`, `"Gwangju"` | 시간·구장은 모르면 null |
| `games[].round` | 문자열 | `"regular"` \| `"postseason"` \| `"preseason"` | 취소 경기에는 없음 |
| `games[].status` | 문자열 | `"SCHEDULED"` \| `"CANCELED"` | |
| `games[].status_note` | 문자열 \| null | `"Rained Out"` | 보통 null |
| `games[].home` / `.away` | 객체 | `{code, name, starter, win_pct_season, last10, run_diff}` | **취소 경기는 `{code}`만** |
| `….code`, `….name` | 문자열 | `"HT"`, `"KIA"` | |
| `….win_pct_season`, `….last10` | 소수 | `0.556`, `0.7` | 시즌 첫 경기 등 기록이 없으면 null |
| `….run_diff` | 소수 | `0.73`(경기당 득실차) | 기록이 없으면 null |
| `….starter` | 객체 \| null | `{player_id, name, era, k9, bb9, ip, starts, type}` | **선발 미발표면 null**. 발표됐지만 올해 기록이 없으면 통계 칸만 null |
| `….starter.type` | 객체 \| null | `{"id": 0, "name": "선발형"}` | 직전 시즌 투수 유형. 직전 시즌 자격이 없으면 null → "직전 시즌 자격 없음" |
| `games[].home_win_prob` | 소수 \| null | `0.5195` | 캘리브레이션 후 P(홈 승), 소수 4자리. **취소 경기는 null** |
| `games[].factors[]` | 배열 | `[{name, contribution_pp}]` 5개 | 기여 절댓값이 큰 순서. **취소 경기는 `[]`**. `name`은 한글(`FACTOR_LABELS`), `contribution_pp`는 %p(양수 = 홈 쪽) |
| `games[].starter_known` | 불리언 | `true` | 두 선발 모두 기록이 있어 선발 피처를 썼는가. 취소 경기에는 없음 |
| `outlook` | 객체 \| null | 아래 세 꼴 중 하나 | 계산 못 하면 null |

`outlook` — 모든 꼴에 `type`, `as_of`.

- `series`(포스트시즌): `name`("플레이오프"), `best_of`, `teams`([코드 2개]), `head_start`, `wins`, `win_prob`(두 팀 시리즈 승리 확률), `most_common_result`("3-1"), `goes_distance_prob`, `games_remaining_max`, `today_game_prob_source`(`"win_model (starter-inclusive)"` \| `"team_model"`), `next_game_date`.
- `playoff_race`(정규시즌): `teams{코드: {wins, losses, rank_now, exp_wins, playoff_prob}}`. `playoff_prob` 합계 5.
- `next_game`(그 밖): `next_game_date`.

### history.csv — 라이브 예측 기록

만드는 곳: `kbo_predict.publish.upsert_history`(경기 전 예측) / `settle_history`(결과 정산). 따옴표 없는 CSV, 날짜·game_id 순.

| 열 | 타입 | 예시 | null 규칙 |
| --- | --- | --- | --- |
| `date` | 날짜 | `2026-10-29` | |
| `game_id` | 정수 | `14050` | |
| `home`, `away` | 팀 코드 | `HT`, `SS` | |
| `home_win_prob` | 소수 | `0.4464` | 경기 전 마지막 예측 |
| `model_version` | 문자열 | `v0.2` | 예측한 모델 버전 — 적중률은 버전별로 나눠 셈 |
| `predicted_at` | ISO 시각 | `2026-10-29T14:40:20+09:00` | |
| `status` | 문자열 | `FINAL` \| `SCHEDULED` \| `CANCELED` | 예측 뒤 취소된 경기는 `CANCELED`(winner·correct 빈 칸) |
| `winner` | `HOME` \| `AWAY` \| `DRAW` | `AWAY` | 정산 전이면 빈 칸(→ null) |
| `correct` | 0 \| 1 | `1` | 정산 전·무승부면 빈 칸(→ null). 규칙: P(홈) ≥ 0.5면 홈을 고른 것으로 봄 |

### rewind/2026/index.json — 되감기 목차

만드는 곳: `kbo_predict.rewind`(`scripts/build_rewind.py`). 모델 `report-2026`(2015~2024 학습·2025 검증, 2026은 홀드아웃). 고정 파일.

| 키 | 타입 | 예시 | null 규칙 |
| --- | --- | --- | --- |
| `season` | 정수 | `2026` | |
| `model_version` | 문자열 | `"report-2026"` | |
| `generated_at`, `commit_sha` | 메타 | | |
| `dates[]` | 배열 | 165개, 03-28~10-12 | 날짜 오름차순 |
| `dates[].date` | 문자열 | `"2026-03-28"` | |
| `dates[].games` | 정수 | `5` | 취소 포함 경기 수 |
| `dates[].decided` | 정수 | `5` | 적중을 따질 수 있는 경기 수(취소·무승부 제외) |
| `dates[].correct` | 정수 | `3` | |
| `accuracy` | 소수 | `0.594` | = 417/702 = model_report 2026 시험 정확도 |
| `n_decided` | 정수 | `702` | |
| `note` | 문자열 | 적중 규칙 한 줄(영문) | |

### rewind/2026/{date}.json — 그날의 되감기

만드는 곳: `kbo_predict.rewind`. latest.json과 같은 모양에 결과가 붙습니다. 검사 샘플은 `index.json`의 마지막 날짜 파일입니다.

| 키 | 타입 | 예시 | null 규칙 |
| --- | --- | --- | --- |
| `date`, `generated_at`, `commit_sha` | 메타 | | `run_url`은 항상 null |
| `mode` | 문자열 | `"rewind"` | |
| `model_version` / `team_model_version` | 문자열 | `"report-2026"` / `"team-2026"` | |
| `starter_source` | 문자열 | `"actual (boxscore pitching order 1)"` | 되감기 선발은 실제 선발(예고 아님) |
| `games[]` | 배열 | latest.json 경기 항목과 같은 키 + `result` | FINAL과 CANCELED만. 시간·구장은 null인 경우가 많음 |
| `games[].result` | 객체 \| null | `{home_score, away_score, winner, pick, correct}` | **취소 경기는 null** |
| `games[].result.winner` | 문자열 | `"HOME"` \| `"AWAY"` \| `"DRAW"` | |
| `games[].result.pick` | 문자열 | `"HOME"` \| `"AWAY"` | 반올림 전 P(홈) ≥ 0.5면 HOME(표시값 50%여도 AWAY일 수 있음) |
| `games[].result.correct` | 불리언 \| null | `true` | 무승부면 null |
| `outlook` | 객체 | `playoff_race` 꼴 | 그날 기준 가을야구 확률 |

### players.json — 선수-시즌 2,918개 (1.77 MB)

만드는 곳: `kbo_predict.cluster publish` → `kbo_predict.site_data.players_payload`. 군집 모델 `clusters-2026`(2015~2025 선수-시즌으로 맞춤). 사람이 publish를 돌릴 때만 바뀝니다. 크기가 크므로 로딩 상태를 보여 줍니다.

| 키 | 타입 | 예시 | null 규칙 |
| --- | --- | --- | --- |
| `generated_at`, `commit_sha`, `model_version` | 메타 | `"clusters-2026"` | |
| `fit_seasons[]` | 정수 배열 | `[2015, …, 2025]` | |
| `note` | 문자열 | `similar` 이름 찾는 법 | |
| `types.batter[]`, `types.pitcher[]` | 배열 | `{id, name, blurb}` 4개씩 | 이름은 `config/cluster_labels.yaml` |
| `players[].group` | 문자열 | `"batter"` \| `"pitcher"` | |
| `players[].season`, `.player_id` | 정수 | `2026`, `14` | (group, season, player_id)가 키 |
| `players[].name` / `.name_ko` | 문자열 / 문자열 \| null | `"Kim Jae-hwan"` / `"김재환"` | 한글 이름이 없으면 null → 로마자 이름 |
| `players[].team`, `.pos` | 문자열 | `"SK"`, `"DH"` | |
| `players[].type` | 객체 | `{"id": 0, "name": "파워형"}` | |
| `players[].prob` | 소수 | `0.904` | 자기 유형 소속 확률(거리 기반 상대 확신도, 보정된 확률 아님) |
| `players[].membership[]` | 소수 배열 | `[0.904, 0.096, 0, 0]` | 유형 id 순서 |
| `players[].x`, `.y` | 소수 | `2.276`, `-0.958` | PCA 2D 좌표(그룹별) |
| `players[].stats` | 객체 | 타자: `pa, avg, obp, hr, sb, k_pct, bb_pct, iso, babip` / 투수: `games, starts, ip, era, k_pct, bb_pct, hr_pct, babip` | 그룹에 따라 키가 다름 |
| `players[].similar[]` | 배열 | `{player_id, season, similarity}` 5개 | 이름·팀은 같은 group의 `players`에서 찾음 |

### teams.json — 팀-시즌 120개

만드는 곳: `kbo_predict.site_data.teams_payload`. `model_expected`는 `report-2026` 모델.

| 키 | 타입 | 예시 | null 규칙 |
| --- | --- | --- | --- |
| `generated_at`, `commit_sha`, `model_version`, `note` | 메타 | | |
| `teams[].season`, `.code`, `.name` | | `2026`, `"KT"`, `"KT"` | |
| `teams[].games`, `.wins`, `.losses`, `.ties` | 정수 | `144`, `90`, `49`, `5` | 정규시즌 FINAL만 |
| `teams[].win_pct`, `.pyth_pct`, `.home_pct`, `.away_pct` | 소수 | `0.647` | 무승부 제외 |
| `teams[].model_expected` | 소수 \| null | `0.528` | **2026만** 값, 2015~2025는 null → "—" |
| `teams[].roster_types.batter{}` / `.pitcher{}` | `{유형 id: 비중}` | `{"0": 0.267, "1": 0.165, "2": 0.568}` | 그 팀에 없는 유형은 키가 빠짐(→ 0) |
| `teams[].vs{}` | `{상대 코드: 승률}` | `{"HH": 0.8, …}` | 9개 |

### model_report.json — 모델 성적표 (`report-2026`, 고정)

만드는 곳: `kbo_predict.train_win`(승패 모델 평가) + `kbo_predict.cluster`(`cluster_quality`). 평가 기간: 학습 2015~2024, 검증 2025, 시험(홀드아웃) 2026.

| 키 | 타입 | 예시 | null 규칙 |
| --- | --- | --- | --- |
| `model_version`, `generated_at`, `commit_sha` | 메타 | `"report-2026"` | `run_url` null |
| `train_seasons[]`, `val_season`, `test_season` | 정수 | `[2015…2024]`, `2025`, `2026` | |
| `n.train`, `n.val`, `n.test` | 정수 | `7065`, `698`, `702` | |
| `selected` | 문자열 | `"lr"` | 검증 log loss로 고른 알고리즘 |
| `models.{lr,lgbm}.{val,test}.{accuracy,log_loss,brier,n}` | 소수·정수 | `models.lr.test.accuracy` 0.594 | `models.lr`에는 `best_iteration` 없음 |
| `models.{lr,lgbm}.calibration` | 문자열 | `"platt"` | |
| `baselines.{val,test}.{home_always,better_win_pct,lower_starter_era}` | 소수 | `0.514`, `0.554`, `0.567` | 기준선 3종 정확도 |
| `significance.{vs,mcnemar_p,model_correct,baseline_correct,selected_on}` | | `"lower_starter_era"`, `0.215` | 가장 강한 기준선과의 McNemar 검정(2026) — 유의하지 않음 |
| `significance.all.{기준선}.{mcnemar_p,model_correct,baseline_correct}` | | | 기준선별 |
| `calibration_bins[]` | 배열 10개 | `{lo, hi, n, pred_mean, actual_rate}` | `n` 0인 구간은 `pred_mean`·`actual_rate` null |
| `feature_importance[]` | 배열 26개 | `{name, label, importance}` | 큰 순서. `label`은 한글 |
| `ablation.no_starter.{kind,n_features,val,test}` | | `n_features` 19 | 선발 피처 뺀 모델 |
| `matchup_feature_ablation.{with,without}.{val,test}.{accuracy,log_loss,brier,n}` | | | 유형 상성 피처 넣기 전후 |
| `matchup_feature_ablation.{adopt,mcnemar_p_test,validation_scope,note,features_added[]}` | | `adopt: false` | 문구 그대로 표시 |
| `cluster_quality.{version,fit_seasons[],membership_note}` | | `"clusters-2026"` | |
| `cluster_quality.{batter,pitcher}.{k,retention,n_all,n_fit,membership_method}` | | `k` 4, `retention` 0.656 | |
| `cluster_quality.{batter,pitcher}.k_table[]` | 배열 | `{k, silhouette, retention, score}` | |
| `cluster_quality.{batter,pitcher}.types[]` | 배열 | `{id, name, n, n_fit, examples[], center{}}` | `examples`는 한글 이름 3명 |
| `starter_source.{train_test,live}` | 문자열 | | 학습은 실제 선발, 라이브는 예고 선발 |

## 매핑 표

페이지 이름: 공통(모든 페이지), 홈(`index.html`), 팀(`teams.html`), 선수(`players.html`), 성적표(`report.html`).

| 페이지 | 요소 | 파일 | 키 경로 |
| --- | --- | --- | --- |
| 공통 | 푸터 증거 바 | `status.json` | `generated_at`, `run_url`, `commit_sha`, `model_version` |
| 홈 | 라이브/되감기 결정 | `status.json` | `mode`, `games_today`, `next_game_date` |
| 홈 | 날짜 칩(라이브) | `latest.json` | `date`, `generated_at`, `mode`, `model_version` |
| 홈 | 매치업 카드: 경기 정보 | `latest.json` | `games[].game_id`, `games[].date`, `games[].time`, `games[].stadium`, `games[].round`, `games[].status`, `games[].status_note` |
| 홈 | 매치업 카드: 팀·확률 | `latest.json` | `games[].home.code`, `games[].away.code`, `games[].home.name`, `games[].away.name`, `games[].home_win_prob` |
| 홈 | 매치업 카드: 팀 기록 | `latest.json` | `games[].home.win_pct_season`, `games[].home.last10`, `games[].home.run_diff`, `games[].away.win_pct_season`, `games[].away.last10`, `games[].away.run_diff` |
| 홈 | 매치업 카드: 선발 | `latest.json` | `games[].home.starter.name`, `games[].home.starter.era`, `games[].home.starter.k9`, `games[].home.starter.bb9`, `games[].home.starter.type.name`, `games[].away.starter.name`, `games[].away.starter.era`, `games[].away.starter.k9`, `games[].away.starter.bb9`, `games[].away.starter.type`, `games[].starter_known` |
| 홈 | 승률을 가른 요인 | `latest.json` | `games[].factors[].name`, `games[].factors[].contribution_pp` |
| 홈 | 오늘 선발, 어떤 유형? | `latest.json` | `games[].home.starter.type.id`, `games[].home.starter.type.name`, `games[].home.starter.k9`, `games[].home.starter.bb9`, `games[].home.starter.ip`, `games[].home.starter.starts`, `games[].away.starter.type`, `games[].away.starter.k9`, `games[].away.starter.bb9`, `games[].away.starter.ip`, `games[].away.starter.starts` |
| 홈 | 전망(시리즈) | `latest.json` | `outlook.type`, `outlook.as_of`, `outlook.name`, `outlook.best_of`, `outlook.teams[]`, `outlook.head_start[]`, `outlook.wins[]`, `outlook.win_prob[]`, `outlook.most_common_result`, `outlook.goes_distance_prob`, `outlook.today_game_prob_source`, `outlook.next_game_date` |
| 홈 | 전망(가을야구 경쟁) | `rewind/2026/{date}.json` | `outlook.type`, `outlook.as_of`, `outlook.teams{}.wins`, `outlook.teams{}.losses`, `outlook.teams{}.rank_now`, `outlook.teams{}.exp_wins`, `outlook.teams{}.playoff_prob` |
| 홈 | 되감기 슬라이더 | `rewind/2026/index.json` | `season`, `model_version`, `dates[].date`, `dates[].games`, `dates[].decided`, `dates[].correct`, `accuracy`, `n_decided`, `note` |
| 홈 | 되감기 날짜의 매치업·선발 | `rewind/2026/{date}.json` | `games[].time`, `games[].stadium`, `games[].round`, `games[].status_note`, `games[].home.last10`, `games[].home.win_pct_season`, `games[].away.last10`, `games[].away.win_pct_season`, `games[].home.starter.name`, `games[].home.starter.era`, `games[].home.starter.k9`, `games[].home.starter.bb9`, `games[].home.starter.ip`, `games[].home.starter.starts`, `games[].away.starter.name`, `games[].away.starter.era`, `games[].away.starter.k9`, `games[].away.starter.bb9`, `games[].away.starter.ip`, `games[].away.starter.starts`, `games[].away.starter.type`, `games[].home.starter.type.id`, `games[].away.starter.type.id`, `games[].factors[].contribution_pp`, `outlook.teams{}.playoff_prob` |
| 홈 | 되감기 날짜의 경기·결과 | `rewind/2026/{date}.json` | `date`, `mode`, `model_version`, `starter_source`, `games[].game_id`, `games[].status`, `games[].home.code`, `games[].away.code`, `games[].home_win_prob`, `games[].factors[].name`, `games[].home.starter.type.name`, `games[].result.home_score`, `games[].result.away_score`, `games[].result.winner`, `games[].result.pick`, `games[].result.correct` |
| 홈 | 모델은 얼마나 맞나 | `model_report.json` | `model_version`, `train_seasons[]`, `val_season`, `test_season`, `selected`, `models.lr.test.accuracy`, `models.lr.test.log_loss`, `models.lr.test.n`, `baselines.test.home_always`, `baselines.test.better_win_pct`, `baselines.test.lower_starter_era` |
| 홈 | 모델은 얼마나 맞나(라이브) | `history.csv` | `model_version`, `status`, `correct` |
| 홈 | 선수 유형 지도(미니) | `players.json` | `players[].group`, `players[].season`, `players[].player_id`, `players[].name`, `players[].name_ko`, `players[].team`, `players[].x`, `players[].y`, `players[].type.id`, `players[].type.name`, `types.batter[].id`, `types.batter[].name` |
| 홈 | 오늘 선발 유형 설명(players.json을 읽은 뒤) | `players.json` | `types.pitcher[].id`, `types.pitcher[].blurb` |
| 홈 | 최근 예측 | `history.csv` | `date`, `game_id`, `home`, `away`, `home_win_prob`, `status`, `winner`, `correct` |
| 성적표 | 모델·기간 배지 | `model_report.json` | `model_version`, `generated_at`, `train_seasons[]`, `val_season`, `test_season`, `n.train`, `n.val`, `n.test`, `starter_source.train_test`, `starter_source.live` |
| 성적표 | 라이브 모델 배지 | `status.json` | `model_version` |
| 성적표 | 2026 홀드아웃 표 | `model_report.json` | `selected`, `models.lr.test.accuracy`, `models.lr.test.log_loss`, `models.lr.test.brier`, `models.lr.test.n`, `models.lgbm.test.accuracy`, `models.lgbm.test.log_loss`, `models.lgbm.test.brier`, `models.lr.calibration`, `baselines.test.home_always`, `baselines.test.better_win_pct`, `baselines.test.lower_starter_era`, `models.lgbm.calibration`, `val_season`, `test_season` |
| 성적표 | 기준선 유의성 | `model_report.json` | `significance.vs`, `significance.mcnemar_p`, `significance.model_correct`, `significance.baseline_correct`, `significance.all.home_always.mcnemar_p`, `significance.all.better_win_pct.mcnemar_p`, `significance.all.lower_starter_era.mcnemar_p`, `significance.selected_on` |
| 성적표 | 신뢰도 곡선 | `model_report.json` | `calibration_bins[].lo`, `calibration_bins[].hi`, `calibration_bins[].n`, `calibration_bins[].pred_mean`, `calibration_bins[].actual_rate` |
| 성적표 | 피처 중요도 | `model_report.json` | `feature_importance[].name`, `feature_importance[].label`, `feature_importance[].importance`, `selected` |
| 성적표 | 변형 비교 | `model_report.json` | `ablation.no_starter.n_features`, `ablation.no_starter.test.accuracy`, `ablation.no_starter.test.log_loss`, `matchup_feature_ablation.adopt`, `matchup_feature_ablation.with.test.accuracy`, `matchup_feature_ablation.without.test.accuracy`, `matchup_feature_ablation.with.test.log_loss`, `matchup_feature_ablation.without.test.log_loss`, `matchup_feature_ablation.mcnemar_p_test`, `matchup_feature_ablation.validation_scope`, `matchup_feature_ablation.features_added[]`, `models.lr.val.accuracy`, `ablation.no_starter.val.accuracy`, `matchup_feature_ablation.with.val.accuracy`, `matchup_feature_ablation.without.val.accuracy`, `baselines.test.better_win_pct` |
| 성적표 | 선수 유형 품질 | `model_report.json` | `cluster_quality.version`, `cluster_quality.membership_note`, `cluster_quality.batter.k`, `cluster_quality.batter.retention`, `cluster_quality.batter.k_table[].k`, `cluster_quality.batter.k_table[].silhouette`, `cluster_quality.batter.k_table[].retention`, `cluster_quality.batter.types[].name`, `cluster_quality.batter.types[].n`, `cluster_quality.batter.types[].examples[]`, `cluster_quality.pitcher.k`, `cluster_quality.pitcher.retention`, `cluster_quality.pitcher.k_table[].silhouette`, `cluster_quality.pitcher.types[].name`, `cluster_quality.pitcher.types[].n`, `cluster_quality.pitcher.types[].examples[]`, `cluster_quality.fit_seasons[]`, `cluster_quality.batter.n_fit`, `cluster_quality.batter.n_all`, `cluster_quality.batter.gmm_agreement`, `cluster_quality.batter.membership_method`, `cluster_quality.batter.k_table[].score`, `cluster_quality.batter.types[].id`, `cluster_quality.pitcher.n_fit`, `cluster_quality.pitcher.n_all`, `cluster_quality.pitcher.gmm_agreement`, `cluster_quality.pitcher.membership_method`, `cluster_quality.pitcher.k_table[].k`, `cluster_quality.pitcher.k_table[].retention`, `cluster_quality.pitcher.k_table[].score`, `cluster_quality.pitcher.types[].id` |
| 성적표 | 라이브 기록 | `history.csv` | `date`, `game_id`, `home`, `away`, `home_win_prob`, `model_version`, `predicted_at`, `status`, `winner`, `correct` |
| 선수 | 머리 문구(시즌 범위·개수·유형 수) | `players.json` | `players[].season`, `types.batter[]`, `types.pitcher[]`, `fit_seasons[]` |
| 선수 | 컨트롤(그룹·시즌·팀·검색) | `players.json` | `players[].group`, `players[].season`, `players[].player_id`, `players[].team`, `players[].name`, `players[].name_ko`, `players[].type.id`, `players[].prob` |
| 선수 | 유형 지도 | `players.json` | `players[].player_id`, `players[].x`, `players[].y`, `players[].team`, `players[].type.id`, `players[].type.name`, `types.batter[].id`, `types.batter[].name`, `types.batter[].blurb`, `types.pitcher[].id`, `types.pitcher[].name`, `types.pitcher[].blurb` |
| 선수 | 선수 카드 | `players.json` | `players[].name`, `players[].name_ko`, `players[].team`, `players[].pos`, `players[].season`, `players[].type.id`, `players[].type.name`, `players[].prob`, `players[].membership[]` |
| 선수 | 선수 카드: 타자 기록 | `players.json` | `players[].stats.pa`, `players[].stats.avg`, `players[].stats.obp`, `players[].stats.hr`, `players[].stats.sb`, `players[].stats.k_pct`, `players[].stats.bb_pct`, `players[].stats.iso`, `players[].stats.babip` |
| 선수 | 선수 카드: 투수 기록 | `players.json` | `players[].stats.games`, `players[].stats.starts`, `players[].stats.ip`, `players[].stats.era`, `players[].stats.k_pct`, `players[].stats.bb_pct`, `players[].stats.hr_pct`, `players[].stats.babip` |
| 선수 | 비슷한 선수 | `players.json` | `players[].similar[].player_id`, `players[].similar[].season`, `players[].similar[].similarity`, `players[].group`, `players[].name`, `players[].name_ko`, `players[].team`, `players[].type.id`, `players[].type.name` |
| 선수 | 유형 모델 요약 | `model_report.json` | `cluster_quality.version`, `cluster_quality.fit_seasons[]`, `cluster_quality.membership_note`, `cluster_quality.batter.k`, `cluster_quality.batter.retention`, `cluster_quality.batter.k_table[].k`, `cluster_quality.batter.k_table[].silhouette`, `cluster_quality.pitcher.k`, `cluster_quality.pitcher.retention`, `cluster_quality.pitcher.k_table[].k`, `cluster_quality.pitcher.k_table[].silhouette` |
| 선수 | 유형 모델 요약: 메타 | `players.json` | `model_version`, `fit_seasons[]`, `generated_at` |
| 팀 | 시즌 선택·순위표 | `teams.json` | `note`, `teams[].season`, `teams[].code`, `teams[].games`, `teams[].wins`, `teams[].losses`, `teams[].ties`, `teams[].win_pct`, `teams[].pyth_pct`, `teams[].model_expected`, `teams[].home_pct`, `teams[].away_pct` |
| 팀 | 로스터 유형 구성 | `teams.json` | `teams[].roster_types.batter{}`, `teams[].roster_types.pitcher{}` |
| 팀 | 로스터 유형 이름 | `players.json` | `types.batter[].name`, `types.pitcher[].name` |
| 팀 | 상대 전적 | `teams.json` | `teams[].vs{}` |
| 팀 | 가을야구 확률 되감기: 날짜 | `rewind/2026/index.json` | `dates[].date` |
| 팀 | 가을야구 확률 되감기: 값 | `rewind/2026/{date}.json` | `outlook.as_of`, `outlook.teams{}.playoff_prob`, `outlook.teams{}.rank_now` |
