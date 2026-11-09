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

1. **네이버 개발자 센터(민서 계정)** — 결제 등록 없이 무료, 하루 25,000회: https://developers.naver.com → 로그인 → Application → 애플리케이션 등록 → 이용약관 동의 → (처음 한 번) 휴대폰 인증·이름 입력 → 애플리케이션 이름(예: `kbo-news`) → **사용 API: 검색** → **비로그인 오픈 API 서비스 환경: WEB 설정**, 웹 서비스 URL `https://kimminseo2323-prog.github.io` → 등록. 내 애플리케이션 → 개요에서 **Client ID**와 **Client Secret** 확인. (NAVER API HUB를 써도 되지만 개인 계정은 결제 카드 등록이 필요하다 — `news-worker.js` 위쪽 주석대로 두 줄만 바꾼다.)
2. **Cloudflare 계정**: https://dash.cloudflare.com 가입(무료). 처음 한 번 workers.dev 하위 이름을 정한다(이 프로젝트: `kbo-predict` → 주소 `https://kbo-news.kbo-predict.workers.dev`).
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
