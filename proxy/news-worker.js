// KBO Predict — 소식 페이지용 뉴스 프록시 (Cloudflare Workers).
//
// 왜 필요한가: 사이트는 GitHub Pages(정적 파일)라 브라우저에서 네이버 검색 API를 바로 부르면 API 키가 그대로 드러난다.
// 이 Worker가 키를 비밀 변수로 들고 있다가, 소식 페이지가 부를 때마다 그 자리에서 네이버 검색 API(뉴스)를 불러 돌려준다.
//
// 네이버 검색 API 약관(특약 1.1~1.4)에 맞추는 점
// - 결과의 순서와 내용(제목·요약·링크·날짜)을 바꾸지 않고 그대로 돌려준다. 페이지는 "네이버 검색결과"와 원문 링크를 함께 보인다.
// - 서버에 저장·캐싱하지 않는다(Cloudflare 캐시 API를 쓰지 않음). 브라우저에만 10분 캐시(Cache-Control: private) — 기기 캐시는 24시간 안.
// - 이 결과를 저장소에 커밋하거나 예측 모델(AI)에 넣지 않는다. 광고를 붙이지 않는다.
// - 키는 민서 계정으로 발급한 것만 쓴다(키 공유 금지, 약관 7.2).
//
// 요청: GET /news?team=KT&display=3&start=1   (team = 사이트 팀 코드 또는 ALL(리그 전체), display = 1~10, start = 1~100 — "더 보기")
// 응답: { team, query, lastBuildDate, total, items: [{ title, originallink, link, description, pubDate }] }  ← 네이버 응답 그대로
// 비밀 변수(wrangler secret put): NAVER_KEY_ID, NAVER_KEY   /   일반 변수: ALLOWED_ORIGINS (쉼표로 구분, 선택)
// API 문서: https://api.ncloud-docs.com/docs/naver-api-hub-search-news (호출 주소·헤더가 바뀌면 아래 두 줄만 고친다)

const API = "https://naverapihub.apigw.ntruss.com/search/v1/news";
const HEADERS = (env) => ({ "X-NCP-APIGW-API-KEY-ID": env.NAVER_KEY_ID, "X-NCP-APIGW-API-KEY": env.NAVER_KEY });

// 사이트 팀 코드 → 검색어(구단 정식 이름). site/assets/app.js TEAMS의 full과 같다.
const TEAM_QUERY = {
  OB: "두산 베어스", LT: "롯데 자이언츠", KT: "KT 위즈", WO: "키움 히어로즈", SK: "SSG 랜더스",
  SS: "삼성 라이온즈", HH: "한화 이글스", HT: "KIA 타이거즈", LG: "LG 트윈스", NC: "NC 다이노스",
};
// 리그 전체 소식(소식 페이지 "전체" 탭 맨 위). 팀 코드가 아니라 따로 둔다.
const ALL_QUERY = "KBO 프로야구";
const DEFAULT_ORIGINS = ["https://kimminseo2323-prog.github.io", "http://127.0.0.1:8000", "http://localhost:8000"];

function corsHeaders(request, env) {
  const allowed = (env.ALLOWED_ORIGINS ? env.ALLOWED_ORIGINS.split(",").map((s) => s.trim()) : DEFAULT_ORIGINS);
  const origin = request.headers.get("Origin") ?? "";
  return allowed.includes(origin) ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" } : null;
}

function json(body, status, extra) {
  return new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json; charset=utf-8", ...extra },
  });
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request, env);
    if (!cors) return json({ error: "origin not allowed" }, 403, {});
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: { ...cors, "Access-Control-Allow-Methods": "GET", "Access-Control-Max-Age": "86400" } });
    }
    const url = new URL(request.url);
    if (request.method !== "GET" || url.pathname !== "/news") return json({ error: "not found" }, 404, cors);
    const team = url.searchParams.get("team") ?? "";
    const query = team === "ALL" ? ALL_QUERY : TEAM_QUERY[team];
    if (!query) return json({ error: "unknown team" }, 400, cors);
    const display = Math.min(10, Math.max(1, Number.parseInt(url.searchParams.get("display") ?? "3", 10) || 3));
    const start = Math.min(100, Math.max(1, Number.parseInt(url.searchParams.get("start") ?? "1", 10) || 1));
    if (!env.NAVER_KEY_ID || !env.NAVER_KEY) return json({ error: "api key not configured" }, 500, cors);

    const api = `${API}?${new URLSearchParams({ query, display: String(display), start: String(start), sort: "date" })}`;
    let res;
    try {
      res = await fetch(api, { headers: HEADERS(env) });
    } catch {
      return json({ error: "upstream unreachable" }, 502, cors);
    }
    if (!res.ok) return json({ error: `upstream ${res.status}` }, 502, cors);
    const data = await res.json();
    // 네이버가 준 값을 그대로 (순서·내용 변경 없음). 팀 코드와 검색어만 덧붙인다.
    return json({ team, query, lastBuildDate: data.lastBuildDate, total: data.total, items: data.items ?? [] }, 200,
      { ...cors, "Cache-Control": "private, max-age=600" });
  },
};
