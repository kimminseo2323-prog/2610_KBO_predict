# KBO 데이터 소스 조사

- 작성일: 2026-10-27
- 목적: 예측/분류 모델 포트폴리오 프로젝트의 데이터 소스 선정
- 표기 규칙
  - **[확인]** : 이 조사에서 실제로 URL을 열어(WebFetch / curl) 응답을 확인한 내용
  - **[검색]** : 웹 검색 결과·README 요약만 본 내용 (직접 응답은 확인하지 않음)
  - **[추정]** : 근거는 있으나 직접 확인하지 못한 추측

---

## 1. 요약

1. **"KBO API"는 공식 공개 API가 아니다.** koreabaseball.com에는 문서화된 REST API가 없고, 페이지가 jQuery AJAX로 호출하는 내부 웹서비스(`/ws/*.asmx/*`, JSON POST)만 존재한다. [확인] 게다가 KBO 이용약관은 "공식 API 또는 사전 서면 동의 없는 크롤러·스크래퍼·봇 사용"을 명시적으로 금지하고 있고(IP 제한·법적 조치 가능), robots.txt도 `User-agent: * Disallow: /` 이다. [확인]
2. **1순위 추천: 네이버 스포츠 내부 JSON API (`api-gw.sports.naver.com`)** — 로그인 없이 GET 한 번으로 경기 결과·구장·선발투수·승/패 투수·박스스코어(타자/투수별)·이닝별 득점·최근 맞대결까지 JSON으로 받을 수 있고, 최소 2010년 6월 시즌 데이터까지 반환됨을 확인했다. [확인] 단, 비공식 내부 엔드포인트라 언제든 바뀔 수 있고 네이버 약관상 자동 수집 허용 여부는 불명확하다. [추정]
3. **2순위 추천(선수-시즌 단위): koreabaseball.com 기록실 HTML 페이지(1982~현재) 또는 MyKBOStats(2014~현재, robots.txt에 Crawl-delay 5 명시, 로그인 불필요)**. 선수 단위 세부 스탯·구장/심판/날씨가 필요하면 MyKBOStats가 가장 리스크가 낮다. [확인]
4. **STATIZ는 사실상 사용 불가**: 기록실·일정 페이지 모두 "로그인 후 이용 가능" + Cloudflare 챌린지 + 약관 제20조(크롤링 금지). 도메인도 statiz.sporki.com → statiz.co.kr 로 바뀌었다(구 도메인은 DNS 미해석). [확인]
5. **GitHub Actions 일일 수집은 기술적으로 가능**하다. 실제로 `dentearl/kbo-data` 저장소가 ubuntu-latest 러너에서 매일 3회 cron으로 KBO `/ws/Schedule.asmx/GetScheduleList`를 호출해 2026-10-26까지 매일 커밋 중임을 확인했다. [확인] 다만 KBO 약관 위반이므로, 포트폴리오 공개용이라면 **네이버 API + MyKBOStats 조합**을 권한다.

---

## 2. 소스별 비교표

| 소스 | 데이터 종류 | 접근 방식 | 기간 | 난이도 | 리스크 |
|---|---|---|---|---|---|
| KBO 공식 (koreabaseball.com) 내부 웹서비스 `/ws/*.asmx` | 일정/결과, 스코어보드(이닝별), 게임센터 | **JSON (POST form, 비공개)** | 2001~ (dentearl 저장소 기준 확인), 사이트 자체는 1982~ | 중 (파라미터는 공개 코드로 확인됨, Referer 등 브라우저 컨텍스트 필요) | **높음** — 약관에 크롤링 금지 명문화, robots `Disallow: /`, IP 제한 명시 |
| KBO 공식 기록실 `/Record/Player/*` | 선수-시즌 타자/투수/수비/주루 기본·세부 스탯 | HTML (ASP.NET WebForms, `__VIEWSTATE` 포스트백) | **1982~2026** 드롭다운 확인 | 중 (VIEWSTATE/EVENTVALIDATION 유지 필요) | **높음** (위와 동일 약관) |
| 네이버 스포츠 `api-gw.sports.naver.com` | 일정/결과, 구장, 선발/승/패/현재 투수, 박스스코어(타자/투수별), 이닝별 득점, 순위, 최근 맞대결, 프리뷰(핫콜드존) | **JSON GET, 로그인 불필요** | **2010~현재 확인** (2010·2016·2017·2019~2022·2025 모두 데이터 반환) | **낮음** | 중 — 비공식 내부 API(무통보 변경), `sports.news.naver.com` robots는 `Disallow: /`, api-gw에는 robots 없음(404) |
| 다음 스포츠 (sports.daum.net) | 일정/결과 (추정) | SvelteKit SPA, 내부 API `/prx/`, `/media-api/` | 미확인 | 중 | robots.txt가 `/prx/`, `/media-api/` 를 Disallow [확인] |
| STATIZ (statiz.co.kr) | WAR 등 세이버메트릭스, 경기별/타석별 기록, 구장, 연봉, 드래프트 | HTML, **로그인 필수** + Cloudflare 챌린지 | 1982~ (검색) | **매우 높음** | **매우 높음** — 약관 제20조 크롤링 금지, 저작권 고지, AI 봇 차단 robots |
| MyKBOStats (mykbostats.com) | 경기별 박스스코어(타자/투수), 구장, 심판, **날씨**, 선수 시즌 스탯, 구장별/팀별 스플릿, 순위 | HTML (서버 렌더링), 로그인 불필요 | **2014~현재** (stats 페이지 연도 목록 2014부터; 선수 페이지에서 2015~2026 확인) | 낮음~중 | 낮음 — robots.txt `Crawl-delay: 5`, `/stats/compare/`만 Disallow; 약관 페이지는 없음(privacy만) |
| KBReport (kbreport.com) | 세이버메트릭스 (검색) | - | - | - | **접속 불가** (연결 거부, 도메인 이전 추정) |
| FanGraphs KBO 리더보드 | 선수-시즌 타격/투구 (Standard/Advanced) | HTML, CSV Export는 유료 회원 전용 | 2002~2026 | 중 | 중 (FanGraphs 약관, 2019 이전 이적 선수 팀 미분리) |
| Kaggle (mattop) 팀-시즌 타격/투구 | 팀-시즌 집계 | CSV 다운로드 | 1982~2021 | 매우 낮음 | 낮음 (출처: Sports Reference) |
| Kaggle (clementmsika) 선수 성적 | 선수-시즌 타격 + 나이/신장/체중 등 | CSV | 2018~2024 (약 1,984행) | 매우 낮음 | 낮음 (출처: baseball-reference) |
| GitHub `choosunsick/KBO_data` (LOPES) | 경기 단위 결과 CSV | CSV | 2010~2018 올스타전 | 매우 낮음 | 낮음, 단 2019년 이후 업데이트 중단 |
| GitHub `dentearl/kbo-data` | 경기 단위 결과 JSON (점수, 승자, 무승부) | raw.githubusercontent 정적 JSON | **2001~2026** | 매우 낮음 | 낮음 (개인 저장소, 선발투수 없음) |
| 공공데이터포털 (data.go.kr) | 경기/선수 기록 **없음** (뉴스 메타데이터, 버즈, 검색량 등만) | - | - | - | - |
| 상용 API (Sportradar Global Baseball, SportsGameOdds, LSports, OpticOdds) | 경기/배당/선수 | REST, 유료 | - | 낮음 | 비용 |

---

## 3. 각 소스 상세

### 3.1 KBO 공식 사이트 (koreabaseball.com)

**공식 API 여부 — [확인]**
- 사이트 어디에도 개발자 문서/REST API 안내가 없다. 검색 결과에서도 공개 API는 확인되지 않았다. [검색]
- 공식 기록 업체는 스포츠투아이(Sports2i). 외부 개발자용 API 제공 여부는 검색으로 확인되지 않았고, 제휴 문의 창구만 있다. 에러 페이지에도 `marketing@sports2i.com` 연락처가 노출된다. [확인/검색]
- KBO 약관 자체가 "KBO가 제공하는 공식 API"를 언급하지만, 일반 공개된 API는 아니다(계약 기반으로 추정). [추정]

**robots.txt — [확인]** (`https://www.koreabaseball.com/robots.txt`)
```
User-agent: Googlebot / Yeti / Daumoa / Bingbot
Disallow: /ws/

User-agent: *
Disallow: /
```
→ 검색엔진 4종만 `/ws/`를 제외하고 허용, 그 외 모든 UA는 전체 금지.

**이용약관 — [확인]** (`https://www.koreabaseball.com/Member/Join/Accessterms.aspx`, 회원 의무 조항 "차. 크롤링 등 자동화 수집 행위의 금지")
> 1) 회원은 회사의 사전 서면 동의 또는 "KBO"가 제공하는 공식 API 없이 크롤러, 스크래퍼, 매크로, 봇 등 자동화 수단을 이용하여 서비스의 콘텐츠(경기 결과, 선수통계, 분석 데이터 등) 또는 데이터를 대량 반복적인 수집을 금지합니다.
> 2) 회원은 회사의 데이터 및 콘텐츠를 수집하여 재판매, 재배포, 타 플랫폼 연동 또는 2차가공하여 활용하는 것을 금지합니다.
> 3) 회사는 위 행위가 확인되는 경우 비정상 요청의 임시제한, 사후통지, 위반정도에 따른 계정 및 IP제한 및 관련 법령에 따른 법적 조치 등을 단계적으로 취할 수 있습니다.

**내부 XHR 엔드포인트 — [확인]** (페이지 HTML 내 인라인 jQuery 코드에서 추출)

| 엔드포인트 | 호출 페이지 | 파라미터 (form POST) |
|---|---|---|
| `POST /ws/Schedule.asmx/GetScheduleList` | `/Schedule/Schedule.aspx` | `leId=1, srIdList=<0,9,6 등 시리즈코드>, seasonId=<연도>, gameMonth=<MM>, teamId=<빈값 또는 팀코드>` |
| `POST /ws/Schedule.asmx/GetMonthSchedule` | 같은 페이지 (달력 뷰) | 미확인 |
| `POST /ws/Main.asmx/GetKboGameList` | `/Schedule/GameCenter/Main.aspx` | `leId=1, srId="0,1,3,4,5,6,7,8,9", date=YYYYMMDD` (2021년 이후 srId에 6 추가, 2024-10-26 이후 8 추가) |
| `POST /ws/Main.asmx/GetKboGameDate` | 게임센터 | 미확인 |
| `POST /ws/Schedule.asmx/GetScoreBoardScroll` | 게임센터 스코어보드 | `leId=1, srId, seasonId, gameId` (KBO-Data-Portal/collector 소스에서 확인) |
| `POST /ws/Controls.asmx/GetYearList`, `GetMonthList`, `GetSearchPlayer` | 공통 컨트롤 | 미확인 |

- 응답 구조 [확인, 공개 코드 기준]
  - `GetScheduleList`: `{ rows: [ { row: [ {Text: "<html 조각>"}, ... ] } ] }` 형태 — 셀 텍스트가 HTML 조각이라 `gameId=`, `<b>14:00</b>` 등을 정규식으로 파싱해야 함 (`dentearl/kbo-data/scripts/scrapeKBO.js`).
  - `GetKboGameList`: `{ code: "100", game: [ { G_ID, SR_ID, SEASON_ID, ... } ] }` (`KBO-Data-Portal/collector/scrapers/game.py`).
  - `GetScoreBoardScroll`: `{ code, maxInning, table1, table2, table3 (JSON 문자열, rows/row/Text), ... }` — table2/3에 이닝별 득점·R/H/E/B.
- 직접 테스트 [확인]: 브라우저 헤더 없이 `curl -X POST ... -d "leId=1&srIdList=0,9,6&seasonId=2025&gameMonth=06"` 로 호출하면 **JSON이 아니라 "에러 | KBO홈페이지" HTML 에러 페이지**가 돌아온다. 공개 코드(dentearl, KBO-Data-Portal)는 `Referer: https://www.koreabaseball.com/Schedule/Schedule.aspx` + 브라우저 UA + `application/x-www-form-urlencoded`로 호출해 JSON을 받고 있다. (본 조사에서는 봇 차단 우회 성격의 헤더 위조 호출은 수행하지 않았다.)

**기록실 페이지 — [확인]** (`/Record/Player/HitterBasic/Basic1.aspx` 등)
- ASP.NET WebForms: `__VIEWSTATE` 존재, 연도 드롭다운 `ddlSeason` 변경 시 `__doPostBack` 발생, 페이저도 포스트백.
- 연도 선택 범위 **1982~2026 + 전체**.
- 테이블 `<table class="tData01 tt">` 에 순위/선수명/팀명/AVG/G/PA/AB/R/H/2B/3B/HR/TB/RBI/SAC/SF.
- KBO-Data-Portal/collector가 긁는 페이지 목록: `HitterBasic/Basic1,Basic2,Detail1`, `PitcherBasic/Basic1,Basic2,Detail1,Detail2`, `Defense/Basic`, `Runner/Basic`, 선수별 `HitterDetail/{type}.aspx?playerId=`, `PitcherDetail/{type}.aspx?playerId=`.

### 3.2 네이버 스포츠 (api-gw.sports.naver.com) — 1순위 후보

- WebFetch 도구로는 네이버 도메인 접근이 차단되어 **curl로 직접 확인**했다. 모든 호출은 쿠키/로그인 없이 성공. [확인]

| 엔드포인트 (GET) | 내용 |
|---|---|
| `/schedule/games?fields=basic,schedule,baseball&upperCategoryId=kbaseball&fromDate=2025-06-01&toDate=2025-06-01&size=500` | 날짜 범위 경기 목록. `categoryId=kbo`로 KBO리그만 필터 필요(퓨처스·기타 콘텐츠 섞임) |
| `/schedule/games/{gameId}` | 단일 경기 기본 정보 (`seasonYear`, `roundCode` 등 추가) |
| `/schedule/games/{gameId}/record` | 박스스코어 전체 |
| `/schedule/games/{gameId}/preview` | 경기 전 프리뷰 (핫/콜드존 등) |

- `games[]` 항목 필드 [확인]:
  `gameId("20250601OBWO02025"), categoryId("kbo"), gameDate, gameDateTime, stadium("고척"), homeTeamCode/Name, awayTeamCode/Name, homeTeamScore, awayTeamScore, winner("HOME"/"AWAY"/"DRAW"), statusCode("RESULT"/...), statusInfo, cancel, suspended, roundCode("kbo_r"), homeStarterName, awayStarterName, winPitcherName, losePitcherName, homeCurrentPitcherName, awayCurrentPitcherName, seriesGameNo, broadChannel`
- `/record` 응답 `result.recordData` 최상위 키 [확인]:
  `gameInfo(구장, 날짜, 시간, 팀코드, round, statusCode), scoreBoard{rheb{away/home: r,h,e,b}, inn{away[], home[]}}, battersBoxscore{away[],home[]}, pitchersBoxscore{away[],home[]}, teamPitchingBoxscore, pitchingResult[], etcRecords[](결승타/2루타/실책/심판 등), homeStandings/awayStandings, recentVsGames[], homeTeamNextGames/awayTeamNextGames, todayKeyStats, seriesOutcome`
- `pitchersBoxscore` 선수 항목 예 [확인]: `name, pcode, inn("6 ⅓"), bf, pa, ab, hit, hr, bb, bbhp, kk, r, er, era, w, l, s, seasonWin, seasonLose, gameCount, wls("패"), tb`
- 과거 커버리지 [확인]: 6월 1~3일 샘플 조회 시 2010(12경기), 2016(15), 2017(15), 2019(10), 2020(13), 2021(19), 2022(17) 모두 반환. 2015-06-01 단일일은 0건(해당일 경기 없음이거나 결측 — 미확인). 2010 이전은 미확인.
- robots/약관: `sports.news.naver.com/robots.txt`는 `User-agent: * Disallow: /` (Yeti만 허용). `api-gw.sports.naver.com/robots.txt`는 404. 네이버 서비스 약관의 자동 수집 조항은 이번에 확인하지 못함 → 공개 포트폴리오에서는 "비공식 API, 개인 학습용" 명시 권장. [추정]
- 과거 LOPES 그룹은 "네이버 자료는 결측·부정확이 많다"는 이유로 KBO 공식 사이트를 선택했다(2018년 기준 README). 현재 API 품질은 별도 검증 필요. [검색]

### 3.3 다음 스포츠 (sports.daum.net)

- 메인은 SvelteKit SPA. `/prx/hermes/api/...` 추정 경로로 curl 하면 SPA 셸 HTML만 반환(JSON 아님). [확인]
- robots.txt: `Disallow: /media-api/`, `Disallow: /prx/` → 내부 API 경로가 명시적으로 크롤링 금지. [확인]
- 네이버와 중복 정보이므로 **우선순위 낮음**.

### 3.4 STATIZ (statiz.co.kr, 구 statiz.sporki.com)

- `statiz.sporki.com`은 DNS 미해석(Non-existent domain). `statiz.co.kr` 200 OK, `www.statiz.co.kr` → `statiz.co.kr` 301. [확인]
- 메뉴 [확인]: `/stats/?m=main|team|total|const|special`, `/schedule/?m=preview|summary`, `/player/?m=playerinfo&p_no=`, `/add/?m=stadium|salary|draft|coach|awards`, `/prediction/`.
- `/stats/?m=main&m2=batting...` 및 `/schedule/?year=2025&month=6` 호출 결과: **본문 없이 `alert('로그인 후 이용 가능합니다.'); location.href='/member/?m=login...'` + Cloudflare 챌린지 스크립트**. 즉 비로그인 자동 요청에는 데이터가 전혀 노출되지 않는다. [확인]
- robots.txt [확인]: `User-agent: * / Content-Signal: search=yes,ai-train=no / Allow: /` 이지만 GPTBot, ClaudeBot, CCBot, Bytespider 등 AI 크롤러는 전부 Disallow.
- 이용약관 제20조 [확인]: "사전 서면 동의 또는 공식 API 없이 크롤러·스크래퍼·매크로·봇 등으로 콘텐츠를 대량·반복적으로 수집해서는 안 됩니다", "수집하여 재판매·재배포·타 플랫폼 연동·2차 가공 금지". 푸터에 저작권 고지.
- 결론: 세이버메트릭스(WAR 등)가 꼭 필요하면 FanGraphs KBO 리더보드(2002~)나 직접 계산으로 대체.

### 3.5 MyKBOStats (mykbostats.com) — 선수/경기 세부 스탯 2순위

- 로그인 불필요, 서버 렌더링 HTML(Phoenix 추정). [확인]
- robots.txt [확인]:
  ```
  Sitemap: https://mykbostats.com/sitemaps/sitemap.xml.gz
  User-agent: *
  Crawl-delay: 5
  Disallow: /stats/compare/
  ```
- 경기 페이지 예 `/games/14040-Doosan-vs-LG-20261014` [확인]: Batting/Pitching 박스스코어, 구장(Jamsil Baseball Stadium), Umpires, **Weather(Apple Weather 제공)**.
- `/stats` 하위 [확인]: `/stats/top/{ba,era,hr,k,ops,rbi,sb,sv,w}`, `/stats/park_splits/{year}`, `/stats/team_splits/{year}`, `/stats/matrix/{year}`, 연도 목록 2014부터.
- 선수 페이지 `/players/964` (구자욱) [확인]: 시즌 2015~2026 행 존재.
- 약관 페이지 없음(privacy만). 사이트맵 제공 + Crawl-delay 명시 → 5초 간격을 지키는 크롤링은 사이트 운영자 의사에 부합한다고 볼 수 있음. [추정]
- 커뮤니티 데이터 수정 시스템 운영 → 공식 기록과 미세 차이 가능. [추정]

### 3.6 KBReport

- `kbreport.com`, `kbreport.sbs` 모두 연결 실패(HTTP 000). [확인] 나무위키는 2014년 개설 세이버메트릭스 사이트로 소개. [검색] 현재 운영 여부 불명 → 제외.

### 3.7 FanGraphs KBO 리더보드

- `https://www.fangraphs.com/leaders/international/kbo` [확인]: 2002~2026 시즌 선택, Batting/Pitching, Standard/Advanced 탭. **Data Export는 회원 전용**. 2019년 이전은 이적 선수의 팀별 구분 없음.

### 3.8 오픈소스 라이브러리 / 크롤러

| 이름 | 위치 | 대상 | 방식 | 최근 활동 | 비고 |
|---|---|---|---|---|---|
| **kbodata** (PyPI) | `pypi.org/project/kbodata`, GitHub `dev-bearabbit/kbo-data` | koreabaseball.com 게임센터 | **Selenium + ChromeDriver** | v0.2.3 2024-07-08, 마지막 push 2024-07-08 [확인] | `get_daily/monthly/yearly_schedule`, `get_game_data` → `{scoreboard, ETC_info, away/home_batter, away/home_pitcher}`; pandas 변환 함수. 2008~2021 일부 결측 명시. Python ≥3.9. GitHub Actions에서는 크롬 설치 필요 |
| **KBO-Data-Portal/collector** | GitHub (MIT) | `/ws/Main.asmx/GetKboGameList`, `/ws/Schedule.asmx/GetScoreBoardScroll`, 기록실 `Record/Player/*` | requests + BeautifulSoup (VIEWSTATE 포스트백 처리) | 마지막 push 2025-09-02 [확인] | `game/schedule/player` 커맨드, 1982~현재. 자매 저장소 `pipeline`(Airflow), `api-server`(Flask). Python 3.12+ |
| **dentearl/kbo-data** | GitHub | `/ws/Schedule.asmx/GetScheduleList` | Node fetch (브라우저 UA + Referer, 400ms 지연) | **GitHub Actions 매일 3회, 2026-10-26 커밋 확인** | 정적 JSON `data/kbo/{2001..2026}.json` (점수·승자·무승부만, 선발투수 없음) |
| LOPES-HUFS/Data_Wrangling_for_KBO | GitHub | 게임센터 | Selenium | 마지막 커밋 2021-01-28 [확인] | 박스스코어 + ETC(도루/실책/심판/구장/관중). Parquet 예제 |
| choosunsick/KBO_data | GitHub | 완성 CSV | - | 마지막 커밋 2019-07-24 [확인] | 2010~2018 경기 단위 |
| kbo-game (npm) | npm | 특정 날짜 경기 결과 | - | - | `getGame(Date)` 하나만 export [검색] |
| pykbo, kbo-crawler | - | - | - | - | **PyPI에서 실존 확인 못함** (검색 결과 없음) |

### 3.9 정리된 데이터셋

| 데이터셋 | 범위 | 단위 | 컬럼 수준 | 출처/비고 |
|---|---|---|---|---|
| Kaggle `mattop/korean-baseball-pitching-data-1982-2021` | 1982~2021 | 팀-시즌 | W, L, ERA, IP, SO, SV, WHIP, per-9 등 | Sports Reference 수집 [검색; Kaggle 페이지는 제목만 확인] |
| Kaggle `mattop/baseball-kbo-batting-data-1982-2021` | 1982~2021 | 팀-시즌 | G, PA, H, HR, RBI, SB, AVG/OBP/SLG/OPS | 동일 [검색] |
| Kaggle `clementmsika/kbo-player-performance-dataset-2018-2024` | 2018~2024 | 선수-시즌 (약 1,984행) | 타격 스탯 + 나이/투타/신장/체중 | baseball-reference 크롤링 [검색; 직접 URL은 404] |
| GitHub `dentearl/kbo-data` | 2001~2026 | 경기 | 날짜, 홈/원정, 점수, 승자, 무승부, 상태 | KBO 공식 일정 API [확인] |
| GitHub `choosunsick/KBO_data` KBO_light.csv | 2010~2018 | 경기 | 날짜, 홈/원정팀, 점수, 비고(정규/시범) | KBO 공식 사이트 수작업 검증 [확인] |
| 공공데이터포털 | - | - | 경기/선수 기록 데이터셋 **없음** (뉴스 메타데이터·버즈·DPI만) | [확인] |
| 타석 단위(play-by-play) 공개 데이터셋 | **없음** | - | STATIZ만 보유(로그인·약관 제한) | [확인/추정] |

---

## 4. GitHub Actions 자동 수집 가능성 평가

| 항목 | KBO 공식 `/ws` | 네이버 api-gw | MyKBOStats | STATIZ |
|---|---|---|---|---|
| 로그인 필요 | 아니오 | 아니오 | 아니오 | **예** |
| GitHub-hosted 러너(해외 IP)에서 접근 | **가능 — 실증** (`dentearl/kbo-data`가 ubuntu-latest에서 매일 성공, cron `0 9 * * *`, `45 13 * * *`, `30 15 * * *` UTC) [확인] | 이번 조사의 국내 curl은 성공. 해외 IP 차단 여부는 **미확인** [추정: 네이버 스포츠 API는 해외에서도 열리는 사례가 많음] | 미확인 (미국 운영 영문 사이트 → 해외 IP 문제 없을 것으로 추정) | 불가 (Cloudflare 챌린지 + 로그인) |
| IP 차단 가능성 | 약관에 "비정상 요청 임시제한, IP 제한" 명시 | 비공식, 레이트리밋 미공개 | Crawl-delay 5 준수 시 낮음 | - |
| 하루 요청량 (일일 수집 기준) | 일정 1회 + 경기당 1회(스코어보드) ≈ 10회 미만 | 일정 1회 + 경기당 record 1회 ≈ 6~10회 | 경기당 1페이지 ≈ 5~6회 (5초 간격 → 30초) | - |
| 백필(2010~2025 전체) | 경기 약 11,000건 × 1~2 요청 | 동일, 날짜 범위 조회로 일정은 월 단위 묶음 가능 | 약 11,000페이지 × 5초 ≈ 15시간 (Actions job 6시간 제한 → 분할 필요) | - |
| 약관 리스크 | **높음 (명시적 금지)** | 중 (미확인) | 낮음 | 매우 높음 |

권장 운영 패턴
- 러너: `ubuntu-latest`, `schedule: cron` (KST 야간 경기 종료 후 UTC 14:00~16:00 사이 1~2회).
- 요청 간 `sleep` 1~5초, 브라우저 UA 명시, 실패 시 재시도 1회 후 종료(차단 유발 방지).
- 결과는 `data/{season}.json|parquet`로 커밋(dentearl 방식)하거나 Release 아티팩트로 저장. `GITHUB_TOKEN`에 `contents: write` 만 부여.
- 비밀 정보 불필요(로그인 없음).

---

## 5. 예측/분류 주제별 필요 소스 매핑

| 주제 | 필요한 데이터 | 1순위 소스 | 보조/대체 | 비고 |
|---|---|---|---|---|
| **경기 승패 예측** (분류) | 경기 결과, 홈/원정, 구장, 선발투수, 양 팀 최근 성적/순위, 맞대결 | 네이버 `/schedule/games` (선발·승/패 투수·구장) + `/record` (순위·최근 맞대결) | dentearl JSON(2001~, 결과만), KBO `/ws`(약관 리스크) | 선발투수 시즌 성적은 MyKBOStats 또는 KBO 기록실 조인 |
| **경기 득점/총점(오버·언더) 회귀** | 이닝별 득점, 타자/투수 박스스코어, 구장 | 네이버 `/record` (`scoreBoard.inn`, 박스스코어) | MyKBOStats 경기 페이지 (+날씨), `/stats/park_splits` | 날씨는 MyKBOStats만 확인됨 |
| **선수 시즌 성적 예측** (회귀) | 선수-시즌 스탯 다년치, 나이/포지션 | KBO 기록실 (1982~, 약관 리스크) 또는 MyKBOStats (2014~) | Kaggle clementmsika(2018~24, 신체정보 포함), FanGraphs(2002~, Advanced) | WAR 필요 시 FanGraphs 또는 직접 계산 |
| **선수 유형 분류 / 클러스터링** | 세부 타격·투구 지표(2B/3B/SAC/SF, 볼넷/삼진 등) | MyKBOStats | KBO 기록실 Detail 페이지 | STATIZ 불가 |
| **팀 순위/포스트시즌 진출 예측** | 팀-시즌 집계, 일별 순위 | Kaggle mattop(1982~2021 팀-시즌) + 네이버 `/record` standings | dentearl JSON으로 일별 승패 재구성 | 무료 CSV만으로도 가능 |
| **관중 수 예측** | 경기별 관중, 요일, 구장, 날씨 | LOPES Data_Wrangling(ETC_info에 관중, 2010~2020 샘플) / KBO 게임센터 | MyKBOStats(날씨) | 관중 수 현행 수집은 KBO 게임센터 의존 → 약관 리스크 |
| **타석 단위(투구 결과) 예측** | play-by-play | **공개 소스 없음** | STATIZ(로그인·약관 금지) | 주제에서 제외 권장 |

---

## 6. 확인한 URL 목록

- https://www.koreabaseball.com/robots.txt [확인]
- https://www.koreabaseball.com/Member/Join/Accessterms.aspx [확인]
- https://www.koreabaseball.com/Schedule/Schedule.aspx (인라인 JS에서 `/ws/` 엔드포인트 추출) [확인]
- https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx [확인]
- https://www.koreabaseball.com/Record/Player/HitterBasic/Basic1.aspx [확인]
- https://www.koreabaseball.com/ws/Schedule.asmx/GetScheduleList, /ws/Main.asmx/GetKboGameList (헤더 없는 POST → 에러 페이지) [확인]
- https://api-gw.sports.naver.com/schedule/games?... , /schedule/games/{id}, /record, /preview [확인]
- https://sports.news.naver.com/robots.txt, https://api-gw.sports.naver.com/robots.txt(404) [확인]
- https://sports.daum.net/robots.txt, /prx/hermes/api/game/schedule (SPA 셸) [확인]
- https://statiz.co.kr/ , /robots.txt, /policy/?m=terms, /stats/?m=main..., /schedule/?year=2025&month=6 [확인]; statiz.sporki.com DNS 실패 [확인]
- https://mykbostats.com/ , /robots.txt, /stats, /players/964, /games/14040-Doosan-vs-LG-20261014 [확인]
- https://www.fangraphs.com/leaders/international/kbo [확인]
- https://pypi.org/project/kbodata/ [확인]; GitHub API: dev-bearabbit/kbo-data, KBO-Data-Portal/collector(+ raw scrapers/game.py, player.py, utils/request.py), dentearl/kbo-data(+ update.yml, scrapeKBO.js, data/kbo/2025.json), LOPES-HUFS/Data_Wrangling_for_KBO, choosunsick/KBO_data [확인]
- https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=프로야구 [확인]
- Kaggle 데이터셋 3종: 검색 결과 및 Kaggle 제목 페이지만 확인 [검색]; kbreport.com / kbreport.sbs 접속 실패 [확인]
