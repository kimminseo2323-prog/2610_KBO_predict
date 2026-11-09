# 소식 페이지 뉴스 프록시 (Cloudflare Workers)

소식 페이지(`site/news.html`)가 구단별 최신 기사를 보여 주려면 이 프록시가 필요합니다. 프록시가 없으면 소식 페이지는 구단별 네이버 뉴스 검색 링크만 보여 줍니다.

## 왜 프록시인가

- 사이트는 GitHub Pages(정적 파일)라 브라우저에서 네이버 검색 API를 바로 부르면 API 키가 드러납니다.
- 프록시는 키를 비밀 변수로 들고, 페이지가 부를 때마다 네이버 검색 API(뉴스)를 불러 결과를 그대로 돌려줍니다.

## 약관에 맞추는 점 (네이버 검색 API 특약 1.1~1.4)

- 결과의 순서와 내용을 바꾸지 않습니다. 페이지는 "네이버 검색결과"와 원문 링크를 함께 보여 줍니다.
- 서버에 저장·캐싱하지 않습니다. 브라우저에만 10분 캐시합니다.
- 결과를 저장소에 커밋하거나 예측 모델에 쓰지 않습니다. 광고를 붙이지 않습니다.
- 사이트 이름·로고에 "네이버"를 넣지 않습니다.
- 키는 본인(민서) 계정으로 발급한 것만 씁니다. 다른 사람의 키를 공유받아 쓰면 안 됩니다(약관 7.2).

## 켜는 순서 (사람이 할 일)

1. **NAVER API HUB (네이버 클라우드, 민서 계정)**: 네이버 개발자 센터의 검색 API는 2026-07-31부터 신규 신청이 막혀 API HUB에서만 신청할 수 있다(개발자 센터 공지 32530). https://www.ncloud.com → 회원가입·로그인 → 콘솔 → AI·NAVER API → NAVER API HUB → 이용 신청 → Application 만들기 → "검색(뉴스)" 선택 → 인증 정보에서 Client ID(`X-NCP-APIGW-API-KEY-ID`)와 Client Secret(`X-NCP-APIGW-API-KEY`) 확인. 개인 계정은 결제 수단 등록이 필요할 수 있다. 지금은 무료 요금제만 있고(추후 유료 요금제 예정), 콘솔에서 호출량 임계치·비용 알림을 설정해 둔다.
2. **Cloudflare 계정**: https://dash.cloudflare.com 가입(무료). 처음 한 번 workers.dev 하위 이름을 정한다(이 계정: `kimminseo2323` → 주소 `https://kbo-news.kimminseo2323.workers.dev`. 대시보드에서 이 이름을 바꾸면 주소도 바뀌므로 `site/assets/app.js`의 `NEWS_PROXY`도 같이 바꾼다).
3. **배포** (이 폴더에서):
   ```bash
   npm install -g wrangler
   wrangler login
   wrangler deploy news-worker.js --name kbo-news --compatibility-date 2026-11-01
   wrangler secret put NAVER_KEY_ID --name kbo-news
   wrangler secret put NAVER_KEY --name kbo-news
   ```
   배포가 끝나면 `https://kbo-news.<계정>.workers.dev` 주소가 나옵니다.
4. **사이트에 연결**: `site/assets/app.js`의 `NEWS_PROXY`에 그 주소를 넣고 커밋합니다(끝에 `/` 없이).
5. **확인**: 소식 페이지에서 구단 카드마다 기사 3개가 보이면 됩니다. 문제가 있으면 `https://kbo-news.<계정>.workers.dev/news?team=KT`를 브라우저에서 직접 열어 오류 메시지를 봅니다(브라우저 주소창에서는 Origin이 없어 403이 나오는 것이 정상입니다 — 사이트에서 확인하세요).

## 요청 형식

`GET /news?team=KT&display=3` → `{ team, query, lastBuildDate, total, items: [{ title, originallink, link, description, pubDate }] }`

- `team`: 사이트 팀 코드(OB, LT, KT, WO, SK, SS, HH, HT, LG, NC). 검색어는 구단 정식 이름입니다.
- `display`: 1~10. 전체 탭은 3개, 구단 탭은 10개를 부릅니다.
- 허용 출처(CORS): `https://kimminseo2323-prog.github.io`와 로컬 미리보기만. 바꾸려면 Worker 변수 `ALLOWED_ORIGINS`에 쉼표로 적습니다.


## 매일 예측 실행 예약 (`cron/`, Worker `kbo-cron`)

GitHub Actions의 예약 실행은 몰리는 날 몇 시간씩 늦거나 빠집니다(2026-11-03: 17:07·17:55 실행이 6~8시간 늦음). 그래서 Cloudflare Cron Triggers가 정해진 시각에 GitHub API로 `daily.yml`을 수동 실행(workflow_dispatch)합니다. GitHub 쪽 예약은 대비용으로 그대로 둡니다.

- 시각: `7 0,3,5,7,8 * * *`, `55 8 * * *` (UTC) = 09:07 · 12:07 · 14:07 · 16:07 · 17:07 · 17:55 KST. 무료 플랜은 계정당 예약 5개.
- 토큰: GitHub **fine-grained personal access token** — Repository access: `2610_KBO_predict`만, Permissions → Repository → **Actions: Read and write**만. 만료일을 정해 두고, 만료 전에 새로 발급해 다시 등록합니다.
- 등록: `cd proxy/cron` → `npx wrangler secret put GH_TOKEN`(값은 채팅·파일에 적지 않음).
- 확인: `npx wrangler tail kbo-cron` — 예약 시각에 `{"ok":true,"status":204}` 로그가 남고, GitHub Actions에 `workflow_dispatch` 실행이 생깁니다.
- 주소로 직접 불러도 실행되지 않습니다(404, `workers_dev = false`).
