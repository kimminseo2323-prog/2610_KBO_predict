// KBO Predict — 소식. news.html 전용 모듈.
//
// 화면: 구단 탭(전체 · 즐겨찾기 · 10개 구단) → 구단 카드들 → "이 소식은 어디서 오나요" 접기 → 푸터.
// - 전체: 맨 위 리그 전체 최신 소식 10개(최신순), 그 아래 10개 구단 카드(즐겨찾기한 구단이 앞, 그 뒤는 2026 순위 순) — 카드마다 3개.
// - 구단 탭(?team=KT): 그 구단 카드 하나를 크게, 기사 10개 + "더 보기"(10개씩, 최대 100개).
// - 구단 기사는 네이버 "정확도순"(sort=sim)으로 받는다: "최신순"은 본문에 구단 이름이 한 번만 나와도 섞여 들어와
//   제목에 그 구단이 나오는 기사가 10개 중 2개뿐이었다(정확도순 9개, 2026-11-09 측정). 리그 전체 소식은 최신순.
// - 즐겨찾기: 별 버튼으로 켜고 끈다. 이 브라우저의 localStorage에만 둔다(없어도 페이지는 그대로 돈다).
//
// 기사 목록: NEWS_PROXY(app.js)가 비어 있지 않으면 `${NEWS_PROXY}/news?team=KT&display=n`을 볼 때마다 부른다.
//   프록시(proxy/news-worker.js)가 네이버 검색 API(뉴스)를 서버에서 불러 그대로 돌려준다 — API 키를 브라우저에 두지 않으려고.
//   네이버 검색 API 약관(특약 1.1~1.4)에 맞춰: 결과의 순서·내용을 바꾸지 않고, "네이버 검색결과"임과 원문 출처·링크를 함께 보이며,
//   저장소에 저장하지 않고(브라우저 캐시만), 예측 모델에 쓰지 않고, 광고를 붙이지 않는다.
// NEWS_PROXY가 비어 있으면(준비 전) 구단마다 네이버 뉴스 검색 결과로 가는 링크만 보여 준다(우리 쪽에서 결과를 받지 않음).

import { TEAMS, NEWS_PROXY, el, fetchJSON, settle, renderNav, renderFooter, teamColors, teamName, teamLogo } from "./app.js";

const $ = (id) => document.getElementById(id);
const FAV_KEY = "kbo-news-favorites";
const state = { status: null, teams: null, errors: {}, tab: "all", favs: new Set(), news: new Map() };
const PAGE = 10;        // 구단 탭에서 한 번에 받는 기사 수
const MAX_START = 91;   // 프록시가 허용하는 마지막 시작 위치(start ≤ 100) → 최대 100개

// ---------- 즐겨찾기 (이 브라우저에만) ----------

function loadFavs() {
  try {
    const raw = JSON.parse(localStorage.getItem(FAV_KEY) ?? "[]");
    return new Set((Array.isArray(raw) ? raw : []).filter((c) => TEAMS[c]));
  } catch {
    return new Set(); // 사생활 보호 모드 등에서 저장소를 못 쓰면 즐겨찾기 없이 시작
  }
}
function saveFavs() {
  try { localStorage.setItem(FAV_KEY, JSON.stringify([...state.favs])); } catch { /* 저장 못 해도 이번 화면에서는 유지 */ }
}
function toggleFav(code) {
  if (state.favs.has(code)) state.favs.delete(code); else state.favs.add(code);
  saveFavs();
  $("news-status").textContent = `${teamName(code)} 즐겨찾기 ${state.favs.has(code) ? "추가" : "해제"}`;
  render();
}

// ---------- 구단 순서: 즐겨찾기 먼저, 그다음 2026 순위 ----------

function order() {
  const rows = state.teams?.teams ?? [];
  const last = Math.max(0, ...rows.map((r) => Number(r.season) || 0));
  const ranked = rows.filter((r) => r.season === last).sort((a, b) => (b.win_pct ?? -1) - (a.win_pct ?? -1));
  const rank = new Map(ranked.map((r, i) => [r.code, i + 1]));
  const codes = Object.keys(TEAMS).sort((a, b) => (rank.get(a) ?? 99) - (rank.get(b) ?? 99) || teamName(a).localeCompare(teamName(b), "ko"));
  return [...codes.filter((c) => state.favs.has(c)), ...codes.filter((c) => !state.favs.has(c))];
}

// ---------- 기사 목록 (프록시가 있을 때만) ----------

const searchURL = (code) => `https://search.naver.com/search.naver?where=news&sort=1&query=${encodeURIComponent(TEAMS[code].full)}`;

async function loadNews(code, display, { start = 1, sort = "sim" } = {}) {
  const key = `${code}:${display}:${start}:${sort}`;
  if (state.news.has(key)) return state.news.get(key);
  const q = new URLSearchParams({ team: code, display: String(display), start: String(start), sort });
  const p = fetch(`${NEWS_PROXY}/news?${q}`)
    .then((res) => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); });
  state.news.set(key, p);
  p.catch(() => state.news.delete(key)); // 실패하면 다음에 다시 시도
  return p;
}

/** 네이버가 준 제목·요약의 <b> 강조를 그대로 살리고(내용은 바꾸지 않음), 그 밖의 태그는 글자로 다루지 않는다. */
function richText(s) {
  const decode = (t) => { const d = document.createElement("textarea"); d.innerHTML = t; return d.value; };
  const parts = String(s ?? "").split(/(<\/?b>)/i);
  let bold = false;
  const out = [];
  for (const part of parts) {
    if (/^<b>$/i.test(part)) { bold = true; continue; }
    if (/^<\/b>$/i.test(part)) { bold = false; continue; }
    const text = decode(part.replace(/<[^>]*>/g, ""));
    if (text) out.push(bold ? el("b", {}, text) : text);
  }
  return out;
}

function ago(pubDate) {
  const t = Date.parse(pubDate);
  if (!Number.isFinite(t)) return "";
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (m < 60) return `${m}분 전`;
  if (m < 60 * 24) return `${Math.round(m / 60)}시간 전`;
  return `${Math.round(m / 1440)}일 전`;
}
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; } };

function newsItem(it) {
  const href = it.originallink || it.link;
  return el("li", { class: "news-item" }, [
    el("a", { class: "news-item__title", href, target: "_blank", rel: "noopener" }, richText(it.title)),
    ...(it.description ? [el("p", { class: "news-item__desc" }, richText(it.description))] : []),
    el("p", { class: "news-item__meta" }, [host(href) || "원문", " ", ago(it.pubDate)]),
  ]);
}

function newsList(code, data) {
  const items = data?.items ?? [];
  if (!items.length) return el("p", { class: "empty" }, "지금은 이 구단 기사가 검색되지 않습니다.");
  return el("ol", { class: "news-list" }, items.map(newsItem));
}

/** 구단 탭: 10개씩 더 받아 같은 목록 뒤에 잇는다(네이버가 준 순서 그대로). */
function moreButton(code, list, next) {
  const btn = el("button", { class: "btn btn--secondary news-more", type: "button" }, "기사 더 보기");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "불러오는 중…";
    try {
      const data = await loadNews(code, PAGE, { start: next });
      const items = data?.items ?? [];
      list.append(...items.map(newsItem));
      if (items.length < PAGE || next + PAGE > MAX_START) btn.remove();
      else { btn.replaceWith(moreButton(code, list, next + PAGE)); }
    } catch {
      btn.disabled = false;
      btn.textContent = "다시 시도";
    }
  });
  return btn;
}

/** 전체 탭 맨 위: KBO 리그 전체 최신 소식(최신순). */
function leagueSection() {
  const body = el("div", { class: "league-news__body" }, el("div", { class: "skeleton", style: "height:160px" }));
  loadNews("ALL", 10, { sort: "date" })
    .then((data) => body.replaceChildren(newsList("ALL", data)))
    .catch(() => body.replaceChildren(el("p", { class: "empty" }, "리그 소식을 불러오지 못했습니다.")));
  return el("section", { class: "league-news", "aria-labelledby": "league-news-title" }, [
    el("h3", { class: "league-news__title", id: "league-news-title" }, "KBO 리그 최신 소식"),
    body,
    el("p", { class: "news-card__src" }, "네이버 검색결과 · 최신순"),
  ]);
}

// ---------- 카드 ----------

function teamCard(code, big) {
  const c = teamColors(code);
  const fav = state.favs.has(code);
  const body = el("div", { class: "news-card__body" });
  const card = el("article", { class: `news-card${big ? " news-card--big" : ""}${fav ? " is-fav" : ""}`, style: { "--tc": c.bg, "--tc-fg": c.fg }, "aria-label": `${teamName(code, { full: true })} 소식` }, [
    el("header", { class: "news-card__head" }, [
      el("button", { class: "news-card__team", type: "button", onclick: () => selectTab(code) }, [
        teamLogo(code, { size: big ? "xl" : "lg" }), el("b", {}, teamName(code)), el("span", {}, TEAMS[code].full)]),
      el("button", {
        class: `fav${fav ? " is-on" : ""}`, type: "button", "aria-pressed": String(fav),
        "aria-label": `${teamName(code)} 즐겨찾기 ${fav ? "해제" : "추가"}`, title: fav ? "즐겨찾기 해제" : "즐겨찾기",
        onclick: () => toggleFav(code),
      }, fav ? "★" : "☆"),
    ]),
    body,
    el("footer", { class: "news-card__foot" }, [
      NEWS_PROXY ? el("span", { class: "news-card__src" }, "네이버 검색결과") : null,
      el("a", { class: "news-card__more", href: searchURL(code), target: "_blank", rel: "noopener" }, "네이버 뉴스에서 더 보기"),
    ]),
  ]);
  if (!NEWS_PROXY) {
    body.append(el("p", { class: "news-card__note" }, "기사 목록 연결을 준비하고 있습니다. 아래 링크로 최신 기사를 볼 수 있습니다."));
  } else {
    body.append(el("div", { class: "skeleton", style: "height:96px" }));
    loadNews(code, big ? PAGE : 3)
      .then((data) => {
        const list = newsList(code, data);
        body.replaceChildren(list);
        if (big && list.tagName === "OL" && (data?.items?.length ?? 0) === PAGE) body.append(moreButton(code, list, PAGE + 1));
      })
      .catch(() => body.replaceChildren(el("p", { class: "empty" }, "기사 목록을 불러오지 못했습니다. 아래 링크로 볼 수 있습니다.")));
  }
  return card;
}

// ---------- 탭 ----------

function renderTabs() {
  const tab = (key, label, extra = {}) => el("button", {
    class: `news-tab${state.tab === key ? " is-on" : ""}`, type: "button", role: "tab", "aria-selected": String(state.tab === key),
    onclick: () => selectTab(key), ...extra,
  }, label);
  const teamTab = (code) => {
    const c = teamColors(code);
    return tab(code, [teamLogo(code, { size: "sm" }), state.favs.has(code) ? el("span", { class: "news-tab__star", "aria-hidden": "true" }, "★") : null, teamName(code)],
      { style: { "--tc": c.bg, "--tc-fg": c.fg }, "data-team": code });
  };
  $("news-tabs").replaceChildren(tab("all", "전체"), tab("fav", ["★ 즐겨찾기", el("b", { class: "num" }, String(state.favs.size))]), ...order().map(teamTab));
}

function selectTab(key) {
  state.tab = key;
  const url = new URL(location.href);
  if (TEAMS[key]) url.searchParams.set("team", key); else if (key === "fav") url.searchParams.set("team", "fav"); else url.searchParams.delete("team");
  history.replaceState(null, "", url);
  render();
  $("news").scrollIntoView({ block: "start", behavior: "smooth" });
}

function render() {
  renderTabs();
  const body = $("news-body");
  body.setAttribute("aria-busy", "false");
  const title = $("news-title"), lead = $("news-board-lead");
  if (TEAMS[state.tab]) {
    title.textContent = `${teamName(state.tab, { full: true })} 소식`;
    lead.textContent = NEWS_PROXY ? "이 구단과 관련이 큰 기사부터 네이버 검색 결과 그대로 보여 줍니다(정확도순). 아래에서 10개씩 더 볼 수 있습니다." : "";
    body.replaceChildren(el("div", { class: "news-grid news-grid--one" }, teamCard(state.tab, true)));
    return;
  }
  if (state.tab === "fav") {
    title.textContent = "즐겨찾기 구단";
    const favs = order().filter((c) => state.favs.has(c));
    lead.textContent = favs.length ? `${favs.length}개 구단을 즐겨찾기했습니다.` : "";
    body.replaceChildren(favs.length ? el("div", { class: "news-grid" }, favs.map((c) => teamCard(c, false)))
      : el("p", { class: "empty" }, "아직 즐겨찾기한 구단이 없습니다. 구단 카드의 ☆을 눌러 추가해 보세요."));
    return;
  }
  title.textContent = "전체 구단";
  lead.textContent = state.favs.size ? "즐겨찾기한 구단이 앞에 옵니다. 그다음은 2026 정규시즌 순위 순입니다." : "2026 정규시즌 순위 순입니다. ☆을 누르면 그 구단이 맨 앞에 옵니다.";
  body.replaceChildren(...(NEWS_PROXY ? [leagueSection()] : []), el("div", { class: "news-grid" }, order().map((c) => teamCard(c, false))));
}

async function init() {
  renderNav("news.html");
  state.favs = loadFavs();
  const q = new URLSearchParams(location.search).get("team");
  state.tab = TEAMS[q] ? q : q === "fav" ? "fav" : "all";
  await Promise.all([settle(state, "status", fetchJSON("status.json", { fresh: true })), settle(state, "teams", fetchJSON("teams.json"))]);
  renderFooter(state.status);
  render();
}

init();
