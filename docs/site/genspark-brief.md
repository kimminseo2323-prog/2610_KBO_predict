# Genspark 제작 브리프 — KBO Predict 사이트

이 문서는 Genspark로 사이트 4페이지(오늘의 경기 / 팀 / 선수 / 모델 성적표)를 다시 만들 때 **그대로 복사해 붙여 넣는** 입력물입니다. 지금 공개된 사이트(`site/`, GitHub Pages `https://kimminseo2323-prog.github.io/2610_KBO_predict/`)가 참조 구현이고, Genspark 제작본은 아래 [수락 체크리스트](#3-수락-체크리스트)를 통과하고 화면이 더 마음에 들 때만 `site/`를 교체합니다. 교체하지 않아도 사이트는 이미 동작합니다.

**쓰는 순서**

1. Genspark에 새 프로젝트를 열고 [1. 공통 규칙](#1-공통-규칙)의 상자 전체를 먼저 붙여 넣습니다.
2. 페이지마다 [2. 페이지별 프롬프트](#2-페이지별-프롬프트)의 상자 하나를 붙여 넣고, 상자에 적힌 참조 파일(`site/*.html` + `site/assets/*`)을 첨부합니다. 순서는 스펙 §9의 우선순위대로 **홈 → 모델 성적표 → 선수 → 팀**.
3. 결과를 [3. 수락 체크리스트](#3-수락-체크리스트)로 확인하고, 고칠 점을 Genspark에 다시 요청합니다.
4. 4페이지가 모두 마음에 들면 [4. 내보내기·전달](#4-내보내기전달)대로 내보내서 전달합니다.

참고 자료(필요하면 함께 첨부): 디자인 시스템 [`DESIGN_clay.md`](../../DESIGN_clay.md), 확정 목업 [`docs/design/clay-hybrid.html`](../design/clay-hybrid.html), 데이터 계약 [`docs/site/data-contract.md`](data-contract.md)(파일별 키·null 규칙·페이지 요소별 키 매핑 표).

---

## 1. 공통 규칙

아래 상자를 그대로 붙여 넣습니다(모든 페이지에 적용).

````text
[공통 규칙 — KBO Predict 사이트]

이 사이트는 KBO 경기 승패 예측 포트폴리오다. 4페이지짜리 정적 사이트(HTML + CSS + 바닐라 JS, 빌드 도구 없음)이고,
모든 숫자는 GitHub 저장소의 공개 JSON/CSV를 브라우저에서 fetch해 그린다. 첨부한 site/ 파일이 참조 구현이다.

■ 디자인 시스템 (DESIGN_clay.md 토큰 그대로)
- 캔버스(페이지 배경): #fffaf0 크림. 회색 캔버스 금지.
- 서피스: surface-soft #faf5e8(푸터·상단 메뉴), surface-card #f5f0e0(크림 카드), surface-strong #ebe6d6(취소 경기 카드 등 비활성).
- 글자: ink #0a0a0a, body #3a3a3a, muted #6a6a6a. 선 hairline #e5e5e5.
- 피처 카드 6색: 핑크 #ff4d8b, 틸 #1a3a3a, 라벤더 #b8a4ed, 피치 #ffb084, 오커 #e8b94a, 크림 #f5f0e0.
  · 한 페이지 안에서 카드 색을 순환시킨다(핑크 → 틸 → 라벤더 → 피치 → 오커 → 크림 순서 권장). 같은 색 카드가 연달아 오면 안 된다.
  · 7번째 색 카드 금지(민트 #a4d4c5·코랄 #ff6b5a는 차트 계열색으로만).
  · 핑크·틸 카드는 흰 글자. 핑크 위의 작은 글자(14px 이하)는 대비가 모자라므로 흰 글자 대신 ink 글자 + 크림 안쪽 상자(inset)를 쓴다.
  · 라벤더·피치·오커·크림 카드는 ink 글자.
- 라운드: 피처 카드 24px, 내용 카드 16px, 버튼·입력 12px, 작은 배지 6~8px, pill 9999px.
- 그림자 없음. 깊이는 크림 캔버스와 포화색 카드의 대비로만. 시스템에 없는 호버 효과를 새로 만들지 않는다.
- 글꼴: Inter(영문·숫자) + Pretendard(한글). 디스플레이 제목은 Inter weight 500 + 음수 자간
  (display-lg 56px/-2px, display-md 40px/-1px, display-sm 32px/-0.5px; 모바일은 clamp로 줄임). 700 굵기 제목 금지.
  본문 16px/1.55, 작은 글씨 14px, 캡션 13px weight 500.
- 간격: 4/8/12/16/24/32/48/96px. 최대 폭 1280px, 좌우 여백 20px.
- 푸터는 크림(#faf5e8). 다크 푸터 금지.

■ 외부 리소스 — 허용은 이 셋뿐
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
- 그 밖의 외부 스크립트·스타일·이미지·아이콘 폰트 금지: 차트 라이브러리(Chart.js, D3 등), Tailwind CDN, jQuery, 이미지 CDN,
  분석·트래킹(Google Analytics, Cloudflare beacon 등) 모두 금지. 차트는 인라인 SVG를 JS로 직접 그린다(참조 구현의 assets/charts.js).
- 스크립트는 인라인이거나 assets/ 아래 상대 경로(<script type="module" src="assets/xxx.js">)만. 모든 링크·경로는 상대 경로
  (앞에 "/"를 붙이지 않는다 — 사이트는 /2610_KBO_predict/ 하위 경로에서 열린다). file:// 경로 금지.

■ 데이터 — 8개 파일, 기준 주소 + 파일 이름
  기준 주소: https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public/
  1. status.json            파이프라인 상태(푸터 증거 바, 라이브/되감기 결정)
  2. latest.json            오늘 경기 예측(라이브)
  3. history.csv            라이브 예측 기록(따옴표 없는 CSV)
  4. rewind/2026/index.json 2026 되감기 목차(165개 날짜)
  5. rewind/2026/{date}.json 그날의 되감기(예: rewind/2026/2026-09-01.json)
  6. players.json           선수-시즌 2,918개(1.77 MB — 로딩 상태 필수)
  7. teams.json             팀-시즌 120개
  8. model_report.json      모델 성적표(고정 파일) — 성적표·홈·선수·팀이 함께 읽음
- 매일 바뀌는 1~4번(status.json, latest.json, history.csv, rewind/2026/index.json)만 끝에 캐시 버스트 ?v=<Date.now()>를 붙이고
  cache: "no-store"로 읽는다(참조 구현 fetchJSON(name, { fresh: true })). 5~8번은 많아야 주 1회 바뀌므로 브라우저 기본 캐시.
  raw CDN 캐시가 최대 5분이라 갱신 직후 파일끼리 시각이 잠깐 어긋날 수 있다.
- 로컬 미리보기(location.hostname이 localhost 또는 127.0.0.1)에서는 기준 주소 대신 ../data/public/을 쓴다
  (참조 구현 assets/app.js의 DATA_BASE 규칙을 그대로 유지).
- 숫자를 HTML에 직접 쓰지 않는다. 적중률·경기 수·확률·연도·선수 수 등 모든 값은 JSON에서 읽는다.
  팀 한글 이름·색(TEAMS), 요인 이름(FACTOR_LABELS), 유형 색(TYPE_COLORS)은 assets/app.js의 상수를 그대로 쓴다
  (파이썬 원본과 같은지 검사함). 옛 팀 이름: 시즌 ≤2020의 SK는 "SK 와이번스", ≤2018의 WO는 "넥센".
- 읽기에 실패하면 빈 화면 대신 오류 문구 + "다시 불러오기" 버튼. 읽는 동안에는 자리를 잡은 로딩 표시(스켈레톤).
- 확률·비율은 0~1 소수로 오므로 화면에서 %로 바꾼다. 시각은 KST.

■ 공통 머리·메뉴
- 상단 메뉴(크림, 높이 64px): 왼쪽 로고 "KBO Predict"(index.html 링크, <nav> 밖),
  <nav> 안에는 정확히 이 4개 링크만 이 순서·이 글자로: 오늘의 경기(index.html) / 팀(teams.html) / 선수(players.html) / 모델 성적표(report.html).
  지금 페이지 링크에 aria-current="page".
- 오른쪽 버튼 "GitHub에서 보기" → https://github.com/kimminseo2323-prog/2610_KBO_predict
- 모바일(<768px)에서는 메뉴가 접히거나 가로로 줄어들되 4개 모두 닿을 수 있어야 한다.

■ 푸터 증거 바 (모든 페이지, id="evidence")
  "마지막 갱신 {status.generated_at, KST} · Actions 실행 #{run 번호} · 커밋 {commit_sha 앞 7자리} · 모델 {model_version}"
- 링크: 실행 번호 → status.run_url, 커밋 → https://github.com/kimminseo2323-prog/2610_KBO_predict/commit/{commit_sha},
  모델 → 저장소 README의 "모델" 절(https://github.com/kimminseo2323-prog/2610_KBO_predict#모델).
- run_url이 null이면 "로컬 실행"(링크 없음), commit_sha가 null이면 "커밋 —". status.json을 못 읽으면 그 사실을 적는다.
- 증거 바 아래에 출처 고지: "데이터: MyKBOStats(비공식 팬 사이트)의 박스스코어를 집계했습니다. 개인 학습용 프로젝트이며 베팅 조언이 아닙니다."

■ 모바일·접근성
- 폭 360px에서 가로 스크롤이 생기면 안 된다(표는 카드 안에서만 가로 스크롤). 벤토 그리드는 데스크톱 3열 → 태블릿 2열 → 모바일 1열.
- <html lang="ko">, <title>, viewport meta, "본문으로 건너뛰기" 링크, 키보드 포커스가 보이는 포커스 링, 버튼·입력 44px 이상.
- 모든 차트에 텍스트 대체(role="img" + aria-label, 또는 화면 낭독기용 표). 색만으로 뜻을 전하지 않는다(적중/미적중은 글자도 함께).
- prefers-reduced-motion이면 애니메이션을 끈다.
````

---

## 2. 페이지별 프롬프트

각 상자를 붙여 넣고 **상자 위에 적힌 참조 파일을 함께 첨부**합니다. 키 경로 표기: `a.b`는 객체 안, `[]`는 배열의 각 원소, `{}`는 팀 코드·유형 번호처럼 정해지지 않은 키(자세한 뜻과 null 규칙은 `docs/site/data-contract.md`).

### 2-1. 오늘의 경기 (홈, `index.html`)

첨부: `site/index.html`, `site/assets/tokens.css`, `app.css`, `home.css`, `app.js`, `charts.js`, `home.js`, `docs/design/clay-hybrid.html`(목업)

````text
[페이지 1/4 — 오늘의 경기 (index.html)]

목적: 오늘 KBO 경기의 홈팀 승리 확률과 그 이유를 한눈에. 경기가 없는 비시즌에는 2026 시즌을 날짜별로 "되감아"
"이날 모델은 이렇게 예측했고 결과는 이랬다"를 보여 준다.

요소(이 순서):
0. 머리: 제목 "오늘의 경기" + 날짜 칩.
   - 라이브: latest.json의 date + "라이브" pill + "2026 시즌 되감기" 토글 버튼. 작은 글씨로 latest.json의 generated_at.
   - 되감기: 2026 날짜 슬라이더(<input type="range">) + 이전/다음 버튼 + "라이브로" 버튼.
     날짜는 rewind/2026/index.json의 dates[].date만 이동(dates[].games, decided, correct로 그날 적중 표시).
     index.json의 accuracy, n_decided, note(적중 규칙)를 슬라이더 옆에.
1. 매치업 카드(첫 줄, 핑크/틸 양분): 원정 = 왼쪽 핑크, 홈 = 오른쪽 틸.
   - 키: games[].away/home.code·name, games[].home_win_prob(홈 승률, 원정은 1 − 값), games[].time, stadium, round, status, status_note.
   - 팀 기록: home/away.win_pct_season, last10, run_diff. 선발: home/away.starter.name, era, k9, bb9, starter.type.name(pill).
   - 가운데 큰 숫자 두 개(원정·홈 승률). 경기가 여러 개면 첫 경기만 크게, 나머지는 반 높이로 세로 반복.
   - 되감기에서는 결과도: games[].result.home_score, away_score, winner, pick, correct("적중"/"미적중" pill).
2. 벤토 그리드(데스크톱 3열), 카드 색 순서 고정:
   ① 크림 "승률을 가른 요인": games[].factors[].name, contribution_pp 5개 가로 막대(양수 = 홈 쪽 틸, 음수 = 원정 쪽 핑크, 단위 %p).
      여러 경기면 탭으로 경기 선택.
   ② 라벤더 "모델은 얼마나 맞나": model_report.json의 models.lr.test.accuracy·log_loss·n, 기준선 baselines.test.home_always /
      better_win_pct / lower_starter_era, 기간(train_seasons, val_season, test_season)을 작은 글씨로.
      history.csv(model_version, status, correct)로 라이브 적중 "n경기 중 c경기"를 버전별로.
   ③ 피치 "오늘 선발, 어떤 유형?": home/away.starter.type.id·name, k9, bb9, ip, starts. 유형 설명은 players.json의 types.pitcher[].blurb
      (players.json을 읽은 뒤 채움).
   ④ 오커 "전망"(outlook.type에 따라 세 꼴):
      - series: outlook.name, best_of, teams[], wins[], head_start[], win_prob[](두 팀 막대), most_common_result, goes_distance_prob,
        today_game_prob_source, next_game_date.
      - playoff_race(되감기): outlook.teams{}.wins, losses, rank_now, exp_wins, playoff_prob — 오늘 경기 두 팀 + 10팀 표(접기).
      - next_game: "다음 경기까지" + next_game_date.
   ⑤ 틸 "선수 유형 지도": players.json 최신 시즌 타자의 x, y 산점도(미니), types.batter[].id·name, 유형별 인원, 선수 페이지 링크.
      players.json은 1.77 MB이므로 나머지를 다 그린 뒤 마지막에 한 번만 읽는다.
   ⑥ 크림 "최근 예측": history.csv 최근 8행(date, home, away, home_win_prob, status, winner, correct). 되감기에서는 그날 경기 결과.
3. 푸터 증거 바.

상태 규칙:
- 라이브/되감기: status.json의 mode가 "rewind"이면 되감기로 시작(index.json의 마지막 날짜). "live"면 latest.json을 보여 주되
  되감기 토글을 둔다. 주소 ?date=YYYY-MM-DD 이면 그 날짜 되감기로 바로 연다(history.replaceState로 주소 갱신).
- 비시즌(경기 없음): 빈 화면 금지 — 되감기로 자연스럽게 연다. 전망 카드는 "다음 경기까지".
- 취소 경기(status "CANCELED"): home/away에 code만 있고 home_win_prob null, factors []. 카드를 surface-strong(#ebe6d6)으로,
  "취소"와 status_note를 보여 주고 확률·요인은 그리지 않는다. 하루 전부 취소면 요인 카드에 "이날은 모두 취소돼 요인이 없습니다."
- 선발 미정(starter null): "선발 미정"으로 표시. 선발 유형 null: "직전 시즌 자격 없음". starter_known false면 선발 피처 미사용을 작게 알림.
- 최근 10경기(last10)는 승 ÷ (승+패) 소수다(무승부 제외, 시즌 초에는 10경기 미만). 0.1 단위로 딱 떨어지고 시즌 승률과 같지 않을 때만
  "최근 10경기 7승 3패", 아니면 "최근 승률 .xxx"로 쓴다(승-패를 추측해 만들지 않는다).
- 검증용 주소 ?fixture=edge(로컬에서만): tests/fixtures/site/latest_edge.json(정상·선발 미정·취소 경기)을 그린다. 이 기능을 지우지 않는다.

참조 구현(첨부한 site/index.html + assets/*)의 이 구조와 데이터 연결을 그대로 유지하고 완성도를 높여 줘.
요소 id(matchups, factors, accuracy, starters, outlook, type-map, recent, evidence)와 위의 데이터 키는 바꾸지 마.
````

### 2-2. 모델 성적표 (`report.html`)

첨부: `site/report.html`, `site/assets/tokens.css`, `app.css`, `report.css`, `app.js`, `charts.js`, `report.js`

````text
[페이지 2/4 — 모델 성적표 (report.html)]

목적: "이 예측을 얼마나 믿어도 되나"에 정직하게 답한다. 어느 모델, 어느 기간의 숫자인지 항상 함께 적는다.
평가용 모델 report-2026(2015~2024 학습, 2025 검증, 2026 홀드아웃)과 매일 쓰는 라이브 모델(v0.2, history.csv)을 나눠 보여 준다.

요소(이 순서):
0. 머리: 제목 "모델 성적표" + 모델·기간 배지(model_report.json의 model_version, generated_at, train_seasons[], val_season, test_season,
   n.train, n.val, n.test, starter_source.train_test·live) + 라이브 모델 배지(status.json의 model_version).
1. 크림 "2026 홀드아웃 성적": selected(선택 알고리즘 강조), models.lr/lgbm.test.accuracy·log_loss·brier·n, models.lr/lgbm.calibration,
   기준선 baselines.test.home_always / better_win_pct / lower_starter_era.
   기준선 유의성: significance.vs, mcnemar_p, model_correct, baseline_correct, selected_on, significance.all.{기준선}.mcnemar_p
   — p값이 0.05보다 크면 "통계적으로 유의하지 않음"을 숨기지 말고 그대로 쓴다.
2. 라벤더 "확률은 믿을 만한가": calibration_bins[].lo, hi, n, pred_mean, actual_rate 신뢰도 곡선(막대 + 대각선). n 0인 구간은 null.
3. 피치 "모델이 크게 본 것": feature_importance[].label, importance 가로 막대(selected 모델 기준).
4. 오커 "빼고 더해 본 모델": ablation.no_starter.n_features, val·test.accuracy, test.log_loss(선발 피처를 뺀 모델),
   matchup_feature_ablation.adopt, with/without.val·test.accuracy, with/without.test.log_loss, mcnemar_p_test, validation_scope,
   features_added[] — "채택하지 않음"과 이유를 그대로.
5. 틸 "선수 유형은 얼마나 뚜렷한가": cluster_quality.version, fit_seasons[], membership_note,
   batter/pitcher.k, retention, n_fit, n_all, gmm_agreement, membership_method, k_table[](k, silhouette, retention, score),
   types[](id, name, n, examples[]).
6. 크림 "라이브 기록": history.csv 전체(date, game_id, home, away, home_win_prob, model_version, predicted_at, status, winner, correct),
   model_version별 적중률. 행이 적을 때는 "라이브 기록은 2026 포스트시즌부터 쌓여 아직 표본이 적습니다"를 명시.
7. 푸터 증거 바.

상태 규칙:
- 숫자·연도·문구는 전부 JSON에서(예: "2026"도 test_season에서). 취소된 라이브 경기 행은 적중률 계산에서 빼고 "취소"로 표시.
- 차트마다 텍스트 대체(표 또는 aria-label). 모바일 360px에서 신뢰도 곡선 캡션이 넘치지 않게.

참조 구현(첨부한 site/report.html + assets/*)의 이 구조와 데이터 연결을 그대로 유지하고 완성도를 높여 줘.
요소 id(model-badges, holdout, calibration, importance, variants, cluster-quality, live-record, evidence)와 데이터 키는 바꾸지 마.
````

### 2-3. 선수 (`players.html`)

첨부: `site/players.html`, `site/assets/tokens.css`, `app.css`, `players.css`, `app.js`, `charts.js`, `players.js`, `docs/design/clay-hybrid.html`(목업의 선수 탐색 부분)

````text
[페이지 3/4 — 선수 탐색 (players.html)]

목적: 2015~2026 타자·투수를 박스스코어 기록으로 나눈 "유형"(K-means 군집) 지도에서 선수를 찾고, 그 선수의 유형·기록과
가장 비슷한 선수 5명을 본다.

요소(이 순서):
0. 머리: 제목 "선수 탐색" + 한 줄 설명(시즌 범위·선수-시즌 수·유형 수를 players.json의 players[].season, types.batter[],
   types.pitcher[], fit_seasons[]에서 계산).
   컨트롤: 타자/투수 토글(players[].group), 시즌 선택(기본 가장 최근 시즌), 팀 선택(기본 전체, players[].team), 이름 검색(name_ko 또는 name).
1. 크림 "선수 유형 지도": players[].x, y 산점도(2D 지도는 PCA 좌표 — "UMAP"이라고 쓰지 않는다), 점 색 = players[].type.id
   (assets/app.js의 TYPE_COLORS), 범례 types.{batter|pitcher}[].id·name·blurb. 점을 누르면 그 선수 선택, 선택한 점 강조, 나머지는 흐리게.
2. 핑크 "선수 카드": name_ko(없으면 name), team(시즌 당시 팀 이름), pos, season, type.name, prob(소속 확신도), membership[](유형별 막대).
   - 타자 기록: stats.pa, avg, obp, hr, sb, k_pct, bb_pct, iso, babip
   - 투수 기록: stats.games, starts, ip, era, k_pct, bb_pct, hr_pct, babip
   핑크 위 작은 글씨는 ink 글자 + 크림 안쪽 상자.
3. 라벤더 "비슷한 선수": players[].similar[](player_id, season, similarity) 5명 — 이름·팀·유형은 같은 group의 players에서 찾아 표로.
   행을 누르면 그 선수로 이동.
4. 틸 "유형 모델": model_report.json의 cluster_quality.version, fit_seasons[], membership_note, batter/pitcher.k, retention,
   k_table[].k·silhouette + players.json의 model_version, fit_seasons[], generated_at.
5. 푸터 증거 바.

상태 규칙:
- players.json은 1.77 MB: 받는 동안 "선수 데이터(1.8 MB)를 불러오는 중…" 로딩 상태, 실패하면 오류 문구 + 다시 불러오기. 한 번만 받는다.
- 선택한 선수는 주소 해시로 공유(#b-2026-2949 = 타자·시즌·player_id, 투수는 #p-…). 해시로 열면 그 선수를 선택.
- 화면 크기를 바꿔도 선택이 유지된다. 검색 결과는 마우스·키보드·터치 모두로 고를 수 있다.
- 소속 확률은 "보정된 확률이 아니라 상대적 확신도"라고 작게 적는다(membership_note).

참조 구현(첨부한 site/players.html + assets/*)의 이 구조와 데이터 연결을 그대로 유지하고 완성도를 높여 줘.
요소 id(type-map, player-card, similar, type-model, evidence)와 데이터 키는 바꾸지 마.
````

### 2-4. 팀 (`teams.html`)

첨부: `site/teams.html`, `site/assets/tokens.css`, `app.css`, `teams.css`, `app.js`, `charts.js`, `teams.js`

````text
[페이지 4/4 — 팀 (teams.html)]

목적: 시즌별 팀 성적을 실제 승률·피타고리안 기대 승률·모델 기대 승률로 비교하고, 로스터의 유형 구성과 상대 전적,
2026 시즌 동안 가을야구(5위 이내) 확률이 어떻게 움직였는지 본다.

요소(이 순서):
0. 머리: 제목 "팀" + 시즌 선택(기본 2026, teams.json의 teams[].season).
1. 크림 "순위표": teams[].code(시즌 당시 팀 이름), games, wins, losses, ties, win_pct, pyth_pct, model_expected, home_pct, away_pct.
   - model_expected는 2026만 값이 있다 → 2015~2025는 그 열을 "—"로(2026에만 모델 기대 열 표시).
   - 동률 순서: 순위 결정전이 있었던 시즌은 결정전 결과(2021 KT > 삼성, 2024 KT > SSG — 정규시즌 성적에는 미포함),
     그 밖에는 상대 전적(vs, .500이 아닐 때), 그래도 같으면 코드순(임의)이고, 어느 규칙으로 정했는지 표 아래 메모로 적는다.
2. 라벤더 "로스터 유형 구성": teams[].roster_types.batter{} / pitcher{}(유형 id → 비중) 누적 막대, 유형 이름은
   model_report.json의 cluster_quality.batter/pitcher.types[].id·name, 색은 TYPE_COLORS. 없는 유형 키는 0.
3. 피치 "상대 전적": teams[].vs{}(상대 코드 → 승률) 10×10 격자. 색은 .500을 기준으로 나눈다(위·아래 두 계열 + 글자 값).
4. 오커 "가을야구 확률 되감기": rewind/2026/index.json의 dates[].date 가운데 7일 간격(파일 25개 이하)으로 날짜를 골라
   각 rewind/2026/{date}.json의 outlook.as_of, outlook.teams{}.playoff_prob를 읽어 10팀 선 그래프. 선 끝 팀 이름이 겹치지 않게.
5. 푸터 증거 바.

상태 규칙:
- 옛 팀 이름: SK는 2020 시즌까지 "SK 와이번스", WO는 2018 시즌까지 "넥센"(assets/app.js의 teamNameFor(code, season)).
- 되감기 날짜 파일 일부를 못 읽어도 페이지 전체가 깨지지 않게(그 카드에만 오류 + 다시 불러오기). 목차가 비어 있으면 오류 문구.
- 표는 모바일에서 카드 안에서만 가로 스크롤.

참조 구현(첨부한 site/teams.html + assets/*)의 이 구조와 데이터 연결을 그대로 유지하고 완성도를 높여 줘.
요소 id(standings, roster-types, head-to-head, playoff-rewind, evidence)와 데이터 키는 바꾸지 마.
````

---

## 3. 수락 체크리스트

제작본을 받아들이기 전에 아래를 모두 확인합니다. 앞의 묶음은 `scripts/check_site.py --strict`가 자동으로 보는 항목(반영 스크립트가 실행함), 뒤의 묶음은 눈으로 보는 항목입니다.

**자동 검사 (`check_site.py --strict`와 같은 규칙)**

- [ ] 페이지 4개(`index.html`, `teams.html`, `players.html`, `report.html`)가 있고, 각각 `<!doctype html>`로 시작하며 `<html lang>`, 비어 있지 않은 `<title>`, viewport meta가 있다.
- [ ] `<nav>` 안의 내부 링크가 정확히 4개 — 오늘의 경기 / 팀 / 선수 / 모델 성적표 — 이 순서·이 글자이고, 지금 페이지에 `aria-current="page"`.
- [ ] 각 페이지에 "GitHub에서 보기" → `https://github.com/kimminseo2323-prog/2610_KBO_predict` 링크가 있다.
- [ ] 각 페이지에 푸터 증거 바 `id="evidence"`가 있다.
- [ ] 외부 리소스는 Inter(fonts.googleapis.com·fonts.gstatic.com)와 Pretendard(cdn.jsdelivr.net/gh/orioncactus/pretendard@…)뿐이다. 외부 `<script>`는 하나도 없고, `<script src>`는 `assets/` 상대 경로(파일이 실제로 있음)뿐이다. 인라인 스크립트의 import도 `./assets/`만.
- [ ] CSS(`<style>`, `style=`, `assets/*.css`)의 `@import`·`url()`에 외부 주소가 없다. `file://` 경로가 없다.
- [ ] 트래킹 코드(Cloudflare beacon, Google Analytics/Tag Manager, Hotjar, Clarity 등)가 없다.
- [ ] `assets/app.js`의 `TEAMS`(한글 팀 이름), `FACTOR_LABELS`(요인 이름 27개), `TYPE_COLORS`(유형 번호)가 파이썬 원본과 같다.
- [ ] 데이터 계약의 키 경로가 실제 JSON에 있다(페이지가 계약에 없는 키를 새로 쓰면 `docs/site/data-contract.md` 매핑 표에도 추가해야 한다).
- [ ] 홈이 `?fixture=edge` 검증 화면을 지원한다.

**눈으로 확인 (데스크톱 1280px · 모바일 360px)**

- [ ] 360px에서 어느 페이지도 가로 스크롤이 생기지 않는다(표는 카드 안에서만 스크롤). 매치업 카드의 두 팀·확률이 겹치지 않는다.
- [ ] 모든 페이지 맨 아래에 증거 바가 실제 값(갱신 시각·실행 번호·커밋·모델)으로 채워지고 링크가 열린다.
- [ ] 상단 메뉴 4개가 모든 페이지에서 보이고(모바일 포함) 지금 페이지가 표시된다.
- [ ] 카드 색이 순환하고 같은 색이 연달아 오지 않는다. 캔버스는 크림, 푸터도 크림, 그림자가 없다.
- [ ] 제목은 Inter 500(굵지 않게) + 좁은 자간, 한글은 Pretendard로 보인다.
- [ ] 화면의 숫자가 JSON과 같다(예: 성적표 2026 정확도 59.4%, 702경기). HTML에 숫자를 직접 쓴 곳이 없다.
- [ ] 홈: `?date=2026-09-01`이 되감기로 열리고, `?fixture=edge`에서 취소·선발 미정 카드가 깨지지 않는다.
- [ ] 선수: 로딩 표시가 보인 뒤 지도가 그려지고, 점·검색·비슷한 선수로 선택이 바뀌며 주소 해시가 따라간다.
- [ ] 키보드(Tab)로 모든 메뉴·버튼·입력에 닿고 포커스가 보인다.

---

## 4. 내보내기·전달

1. Genspark에서 **페이지마다** HTML로 내보냅니다(내보내기 파일은 CSS·JS가 안에 들어간 파일 하나여도 됩니다).
2. 파일 이름을 정확히 `index.html`, `teams.html`, `players.html`, `report.html`로 바꿉니다(이름이 다르면 반영 스크립트가 `<title>`로 페이지를 추측합니다).
3. 네 파일(그리고 `assets/` 폴더가 함께 나왔다면 그 폴더)을 zip 하나로 묶어 어시스턴트에게 전달합니다. 데이터 JSON 사본은 넣지 않아도 됩니다(넣어도 반영하지 않음).

**그다음 일어나는 일 (어시스턴트)**

1. `python -X utf8 scripts/import_site.py genspark.zip --dry-run` — `site/`를 건드리지 않고 임시 복사본에서 반영·검증해 보고합니다.
2. `python -X utf8 scripts/import_site.py genspark.zip` — 지금 `site/`를 `artifacts/site-backup-<시각>/`에 백업하고, 내보내기 파일을 `site/`에 덮어씁니다. 이때 Genspark가 붙이는 Cloudflare beacon 같은 허용 밖 외부 `<script>`·`<link>`를 지우고, `file://`·`/`로 시작하는 경로를 상대 경로로 고칩니다. 내보내기에 없는 파일(`assets/` 등)은 그대로 둡니다.
3. 스크립트가 `check_site.py --strict`를 돌려 결과 표를 출력합니다. 실패하면 `site/`를 백업으로 되돌리고 무엇이 문제인지 알려 줍니다 → 그 내용을 Genspark에 고쳐 달라고 요청합니다.
4. 통과하면 로컬 미리보기(`python -m http.server 8000` → `http://localhost:8000/site/`)에서 1280px·360px 스크린샷을 찍어 위 "눈으로 확인" 항목을 봅니다. 트래킹이 아닌 외부 파일(예: Tailwind)을 지웠다는 "주의"가 나왔다면 스타일이 깨졌는지 특히 봅니다.
5. 사용자가 지금 Pages 버전과 비교해 교체를 정하면 `site/`를 커밋·push합니다. `pages.yml`이 `site/**` 변경을 받아 GitHub Pages에 다시 배포합니다.
