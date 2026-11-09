// KBO Predict — 매일 예측 실행 예약(Cloudflare Workers Cron Triggers).
//
// 왜: GitHub Actions의 예약 실행(schedule)은 몰리는 날 몇 시간씩 늦거나 빠진다(2026-11-03: 17:07·17:55 실행이 6~8시간 늦게 돌았다).
// 그래서 Cloudflare가 정해진 시각에 GitHub API로 "daily predictions" 워크플로를 수동 실행(workflow_dispatch)한다.
// GitHub 쪽 예약(daily.yml의 schedule)은 그대로 두어 이쪽이 실패해도 대비가 된다 — 같은 날 여러 번 돌아도
// history.csv는 경기 전 행만 갱신하고 시작한 경기는 고정되므로 기록이 섞이지 않는다.
//
// 시각(UTC → KST): wrangler.toml의 crons. 무료 플랜은 계정당 예약 5개라 두 줄로 묶었다.
//   "7 0,3,5,7,8 * * *" → 09:07 · 12:07 · 14:07 · 16:07 · 17:07 KST,  "55 8 * * *" → 17:55 KST
// 비밀 변수(wrangler secret put GH_TOKEN): GitHub fine-grained 토큰 — 저장소 2610_KBO_predict 하나, 권한 Actions: Read and write만.

const REPO = "kimminseo2323-prog/2610_KBO_predict";
const WORKFLOW = "daily.yml";

export async function dispatch(env, reason) {
  if (!env.GH_TOKEN) return { ok: false, status: 0, error: "GH_TOKEN not configured" };
  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "kbo-predict-cron",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  const out = { ok: res.status === 204, status: res.status, reason };
  if (!out.ok) out.error = (await res.text()).slice(0, 300);
  return out;
}

export default {
  // 예약 시각마다 실행 — 결과는 Cloudflare 로그(wrangler tail)에 남는다.
  async scheduled(event, env, ctx) {
    const r = await dispatch(env, `cron ${event.cron}`);
    console.log(JSON.stringify({ at: new Date(event.scheduledTime).toISOString(), cron: event.cron, ...r }));
    if (!r.ok) throw new Error(`dispatch failed: ${r.status} ${r.error ?? ""}`);
  },
  // 주소로 직접 부르면 아무것도 하지 않는다(누구나 실행시키지 못하게).
  async fetch() {
    return new Response("kbo-predict cron: scheduled only\n", { status: 404 });
  },
};
