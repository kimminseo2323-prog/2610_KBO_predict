// KBO Predict — 선수 탐색. players.html 전용 모듈.
//
// 화면 순서: 머리(#players-lead) → 컨트롤(#controls: 타자/투수 토글 #group-toggle, #season-select, #team-select, #player-search)
//   → #type-map(크림, 유형 지도) · #player-card(핑크, 선수 카드) → #similar(라벤더, 비슷한 선수) → #type-model(틸, 유형 모델 요약) → 푸터.
//
// 데이터: players.json(1.77 MB)을 한 번만 받아 메모리 색인 Map("group-season-player_id" → 항목)을 만들고,
// 그룹·시즌·팀 필터와 검색은 모두 메모리에서 한다. 유형 모델 요약은 model_report.json의 cluster_quality.
// 데이터 키는 docs/site/data-contract.md 매핑 표(페이지 "선수")에 적은 것만 쓴다.
//
// 선택 규칙: 처음에는 URL 해시(#b-2026-451 = 타자·2026·player_id 451, 투수는 p)의 선수, 없으면 가장 최근 시즌 타자 중
// 소속 확신도(prob)가 가장 높은 선수. 그룹·시즌·팀을 바꾸면 같은 선수(player_id)가 새 화면에 있으면 그대로 두고,
// 없으면 새 화면에서 prob가 가장 높은 선수를 고른다. 선택이 바뀔 때마다 해시를 history.replaceState로 고친다.
// 팀 필터는 점을 지우지 않고 다른 팀 점을 흐리게만 한다(지도 모양 유지, charts.js scatter의 dim 옵션).

import {
  TEAMS, el, fetchJSON, settle, fin, fmtPct, fmtRate3, fmtInt, fmtRange, fmtInnings, teamName, teamNameFor,
  typeColor, colorVar, onColor, renderNav, renderFooter, showError,
} from "./app.js";
import { scatter } from "./charts.js";

const $ = (id) => document.getElementById(id);

const state = {
  data: null,            // players.json 전체
  index: new Map(),      // "batter-2026-451" → 항목
  views: new Map(),      // "batter-2026" → 그 그룹·시즌 항목 배열
  seasons: [],           // 오름차순
  group: "batter",
  season: null,
  team: "",              // "" = 전체
  sel: null,             // 선택된 항목
  report: null,
  errors: {},
};

// ---------- 작은 도우미 ----------

const pct1 = (v) => fmtPct(v, 1);
const dec2 = (v) => (fin(v) ? Number(v).toFixed(2) : "—");

const GROUP = { batter: "타자", pitcher: "투수" };
const LETTER = { batter: "b", pitcher: "p" };
const POS = {
  P: "투수", C: "포수", "1B": "1루수", "2B": "2루수", "3B": "3루수", SS: "유격수",
  LF: "좌익수", CF: "중견수", RF: "우익수", DH: "지명타자", PH: "대타",
};
// 선수 카드의 주요 기록: [키, 이름, 포맷]
const STATS = {
  batter: [["pa", "타석", fmtInt], ["avg", "타율", fmtRate3], ["obp", "출루율", fmtRate3], ["hr", "홈런", fmtInt], ["sb", "도루", fmtInt],
    ["k_pct", "K%", pct1], ["bb_pct", "BB%", pct1], ["iso", "ISO", fmtRate3], ["babip", "BABIP", fmtRate3]],
  pitcher: [["games", "경기", fmtInt], ["starts", "선발", fmtInt], ["ip", "이닝", fmtInnings], ["era", "ERA", dec2],
    ["k_pct", "K%", pct1], ["bb_pct", "BB%", pct1], ["hr_pct", "피홈런%", pct1], ["babip", "BABIP", fmtRate3]],
};
const SEARCH_MAX = 8;

const keyOf = (group, season, id) => `${group}-${season}-${id}`;
/** 화면 이름: 한글 이름, 없으면 로마자 이름. */
const nameOf = (p) => p?.name_ko || p?.name || "이름 없음";
const typesOf = (group) => state.data?.types?.[group] ?? [];
const typeName = (group, id) => typesOf(group).find((t) => t.id === id)?.name ?? "—";

/** 지금 그룹·시즌의 항목 전부(팀 필터와 상관없이 — 지도는 이 모양 그대로). */
const viewAll = () => state.views.get(`${state.group}-${state.season}`) ?? [];
/** 그중 팀 필터에 맞는 항목. */
const viewPool = () => viewAll().filter((p) => !state.team || p.team === state.team);
const topOf = (list) => list.reduce((best, p) => (!best || (p.prob ?? 0) > (best.prob ?? 0) ? p : best), null);

// ---------- 읽기 ----------

function buildIndex() {
  state.index.clear();
  state.views.clear();
  for (const p of state.data.players ?? []) {
    if (!p || !GROUP[p.group] || !fin(p.season)) continue;
    state.index.set(keyOf(p.group, p.season, p.player_id), p);
    const v = `${p.group}-${p.season}`;
    if (!state.views.has(v)) state.views.set(v, []);
    state.views.get(v).push(p);
  }
  state.seasons = [...new Set([...state.index.values()].map((p) => p.season))].sort((a, b) => a - b);
}

let playersReq = null; // players.json은 한 번만 받는다(실패하면 비워 다시 시도)
async function loadPlayers() {
  setControlsEnabled(false);
  $("map-body").setAttribute("aria-busy", "true");
  $("map-body").replaceChildren(
    el("div", { class: "inset map__frame" }, el("div", { class: "skeleton map-skeleton" })),
    el("p", { class: "map__loading" }, "선수-시즌 기록 불러오는 중…"),
  );
  playersReq ??= fetchJSON("players.json");
  try {
    state.data = await playersReq;
    delete state.errors.players;
  } catch (err) {
    playersReq = null;
    state.errors.players = err.message;
    $("map-body").setAttribute("aria-busy", "false");
    showError($("map-body"), err.message, loadPlayers);
    const note = () => el("div", { class: "inset" }, el("p", { class: "empty" }, "선수 데이터(players.json)를 불러오지 못해 비워 두었습니다."));
    $("card-body").replaceChildren(note());
    $("card-body").setAttribute("aria-busy", "false");
    $("similar-body").replaceChildren(el("p", { class: "empty" }, "선수 데이터(players.json)를 불러오지 못해 비워 두었습니다."));
    return;
  }
  buildIndex();
  if (!state.index.size) {
    $("map-body").setAttribute("aria-busy", "false");
    $("map-body").replaceChildren(el("p", { class: "empty" }, "선수 데이터에 표시할 선수가 없습니다."));
    return;
  }
  renderLead();
  buildMapShell();
  fillControls();
  setControlsEnabled(true);
  if (!applyHash()) {
    // 기본: 가장 최근 시즌 타자 중 prob가 가장 높은 선수 (페이지가 비어서 열리지 않게)
    state.group = state.views.has(`batter-${state.seasons.at(-1)}`) ? "batter" : "pitcher";
    state.season = state.seasons.at(-1);
    state.sel = topOf(viewPool());
    refresh({ map: true, hash: false });
  }
  renderModelMeta();
}

const loadReport = async () => {
  await settle(state, "report", fetchJSON("model_report.json"));
  renderModel();
};

async function init() {
  renderNav("players.html");
  bindControls();
  fetchJSON("status.json", { fresh: true }).then(renderFooter, () => renderFooter(null));
  loadReport();
  await loadPlayers();
}

// ---------- 머리 ----------

function renderLead() {
  const d = state.data;
  const nB = typesOf("batter").length, nP = typesOf("pitcher").length;
  $("players-lead").textContent =
    `${fmtRange(state.seasons)} 시즌 선수-시즌 ${fmtInt(state.index.size)}개를 스탯만으로 타자 ${nB}유형·투수 ${nP}유형으로 나눴습니다. ` +
    "지도는 여러 스탯을 PCA로 두 축에 눌러 담은 것이라, 가까운 점일수록 기록이 비슷합니다." +
    (d.fit_seasons?.length && d.fit_seasons.at(-1) < state.seasons.at(-1)
      ? ` 유형은 ${fmtRange(d.fit_seasons)} 기록으로 정했고 ${state.seasons.at(-1)} 선수는 가장 가까운 유형에 넣었습니다.` : "");
}

// ---------- 컨트롤 ----------

function setControlsEnabled(on) {
  document.querySelectorAll("#controls button, #controls select, #controls input").forEach((n) => { n.disabled = !on; });
}

function fillControls() {
  const season = $("season-select");
  season.replaceChildren(...[...state.seasons].reverse().map((y) => el("option", { value: String(y) }, String(y))));
  const team = $("team-select");
  const codes = Object.keys(TEAMS).sort((a, b) => teamName(a).localeCompare(teamName(b), "ko"));
  team.replaceChildren(el("option", { value: "" }, "전체"), ...codes.map((c) => el("option", { value: c }, teamName(c))));
}

/** 컨트롤 표시를 state에 맞춘다. */
function syncControls() {
  document.querySelectorAll("#group-toggle .seg__btn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.group === state.group)));
  $("season-select").value = String(state.season);
  $("team-select").value = state.team;
}

function bindControls() {
  $("controls").addEventListener("submit", (e) => e.preventDefault());
  document.querySelectorAll("#group-toggle .seg__btn").forEach((b) => b.addEventListener("click", () => {
    if (state.data && b.dataset.group !== state.group) setFilter({ group: b.dataset.group });
  }));
  $("season-select").addEventListener("change", (e) => state.data && setFilter({ season: Number(e.target.value) }));
  $("team-select").addEventListener("change", (e) => state.data && setFilter({ team: e.target.value }));
  bindSearch();
  window.addEventListener("hashchange", () => state.data && applyHash());
}

/** 그룹·시즌·팀을 바꾼다. 같은 선수(player_id)가 새 화면에 있으면 유지, 없으면 prob 1위. */
function setFilter(patch) {
  Object.assign(state, patch);
  if (!state.views.has(`${state.group}-${state.season}`)) {
    // 그 그룹에 그 시즌이 없으면 가장 가까운 시즌으로
    const have = state.seasons.filter((y) => state.views.has(`${state.group}-${y}`));
    state.season = have.reduce((a, y) => (Math.abs(y - state.season) < Math.abs(a - state.season) ? y : a), have.at(-1));
  }
  const same = state.sel ? state.index.get(keyOf(state.group, state.season, state.sel.player_id)) : null;
  state.sel = same && (!state.team || same.team === state.team) ? same : topOf(viewPool());
  refresh({ map: true });
}

/** p를 고른다. 다른 그룹·시즌이면 그 화면으로 옮기고, 팀 필터에 안 맞으면 팀을 "전체"로 푼다. */
function select(p, { from = "code", focus = false } = {}) {
  if (!p) return;
  const moved = p.group !== state.group || p.season !== state.season || (state.team && p.team !== state.team);
  if (moved) {
    state.group = p.group;
    state.season = p.season;
    if (state.team && p.team !== state.team) state.team = "";
  }
  state.sel = p;
  // 지도에서 누른 것이면 지도가 이미 강조를 바꿨다. 그 밖(검색·비슷한 선수·해시)은 강조를 옮기려고 다시 그린다(점 150개 이하).
  refresh({ map: moved || from !== "map" });
  if (focus) $("card-name")?.focus();
}

function refresh({ map = false, hash = true } = {}) {
  syncControls();
  if (map) renderMap();
  renderPicked();
  renderCard();
  renderSimilar();
  if (hash) writeHash();
  const p = state.sel;
  $("selection-status").textContent = p
    ? `${nameOf(p)}, ${p.season} ${GROUP[p.group]}, ${p.type?.name ?? "유형 없음"} 선수를 표시합니다.`
    : "조건에 맞는 선수가 없습니다.";
}

// ---------- URL 해시 ----------

function writeHash() {
  const p = state.sel;
  if (!p) return;
  const h = `#${LETTER[p.group]}-${p.season}-${p.player_id}`;
  if (location.hash !== h) history.replaceState(null, "", h);
}

/** #b-2026-451 / #p-2025-1096 → 그 선수를 고른다. 고쳤으면 true. */
function applyHash() {
  const m = /^#([bp])-(\d{4})-(\d+)$/.exec(location.hash);
  const p = m && state.index.get(keyOf(m[1] === "b" ? "batter" : "pitcher", Number(m[2]), Number(m[3])));
  if (!p) return false;
  state.group = p.group;
  state.season = p.season;
  state.team = "";
  state.sel = p;
  refresh({ map: true });
  return true;
}

// ---------- 검색 ----------

const norm = (s) => String(s ?? "").toLowerCase().replace(/[\s\-.'·]/g, "");

function bindSearch() {
  const input = $("player-search");
  const list = $("search-results");
  const box = input.closest(".search");
  input.addEventListener("input", runSearch);
  input.addEventListener("focus", () => { if (input.value.trim()) runSearch(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      const first = list.querySelector("button");
      if (first) { e.preventDefault(); first.focus(); }
    } else if (e.key === "Escape") {
      closeSearch();
    } else if (e.key === "Enter") {
      e.preventDefault();
      list.querySelector("button")?.click(); // Enter = 첫 결과
    }
  });
  list.addEventListener("keydown", (e) => {
    const hits = [...list.querySelectorAll("button")];
    const i = hits.indexOf(document.activeElement);
    if (i < 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); hits[Math.min(i + 1, hits.length - 1)].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); (i === 0 ? input : hits[i - 1]).focus(); }
    else if (e.key === "Escape") { e.preventDefault(); closeSearch(); input.focus(); }
  });
  // Safari/WebKit은 버튼을 눌러도 포커스를 주지 않아 focusout이 클릭보다 먼저 목록을 닫는다 → 목록 위 pointerdown은 포커스 이동을 막는다
  list.addEventListener("pointerdown", (e) => e.preventDefault());
  box.addEventListener("focusout", (e) => { if (!box.contains(e.relatedTarget)) closeSearch(); });
  document.addEventListener("pointerdown", (e) => { if (!box.contains(e.target)) closeSearch(); });
}

function closeSearch() {
  $("search-results").hidden = true;
}

function runSearch() {
  const input = $("player-search");
  const list = $("search-results");
  const q = norm(input.value);
  if (!q || !state.data) {
    list.replaceChildren();
    closeSearch();
    $("search-status").textContent = "";
    return;
  }
  const hits = [];
  for (const p of state.index.values()) {
    const ko = norm(p.name_ko), en = norm(p.name);
    const rank = ko.startsWith(q) || en.startsWith(q) ? 0 : ko.includes(q) || en.includes(q) ? 1 : -1;
    if (rank >= 0) hits.push([rank, p]);
  }
  // 이름 앞부분이 맞는 것 → 지금 보는 구분(타자/투수) → 최근 시즌 → 이름순
  const other = (p) => (p.group === state.group ? 0 : 1);
  hits.sort((a, b) => a[0] - b[0] || other(a[1]) - other(b[1]) || b[1].season - a[1].season
    || nameOf(a[1]).localeCompare(nameOf(b[1]), "ko"));
  const shown = hits.slice(0, SEARCH_MAX).map(([, p]) => p);
  list.replaceChildren(...(shown.length
    ? shown.map((p) => el("li", {}, el("button", {
      class: "search__hit", type: "button",
      onclick: () => {
        input.value = "";
        closeSearch();
        $("search-status").textContent = "";
        select(p, { from: "search", focus: true });
      },
    }, [
      el("span", { class: "dot", style: { background: colorVar(typeColor(p.group, p.type?.id)) }, "aria-hidden": "true" }),
      el("span", { class: "search__name" }, nameOf(p)),
      el("span", { class: "search__meta" }, `${teamNameFor(p.team, p.season)} · ${p.season} ${GROUP[p.group]}`),
    ])))
    : [el("li", { class: "search__none" }, "일치하는 선수가 없습니다. 한글 이름이나 영문 이름 일부로 찾아 보세요.")]));
  list.hidden = false;
  $("search-status").textContent = hits.length
    ? `${hits.length}개 찾음${hits.length > SEARCH_MAX ? `, 앞의 ${SEARCH_MAX}개를 표시` : ""}. 아래 화살표로 결과로 이동합니다.`
    : "일치하는 선수가 없습니다.";
}

// ---------- 유형 지도 ----------

/** 지도 틀(축 이름 · 차트 자리 · 범례 · 유형 설명)은 한 번만 만들고, 필터가 바뀌면 안만 다시 채운다. */
function buildMapShell() {
  const body = $("map-body");
  body.setAttribute("aria-busy", "false");
  body.replaceChildren(
    el("div", { class: "inset map__frame" }, [
      el("p", { class: "map__axis map__axis--y" }, [el("span", { "aria-hidden": "true" }, "↑ "), "PCA 2"]),
      el("div", { class: "map__chart", id: "map-chart" }),
      el("div", { class: "map__foot" }, [
        el("p", { class: "map__hint" }, "가까울수록 비슷한 스탯"),
        el("p", { class: "map__axis map__axis--x" }, ["PCA 1", el("span", { "aria-hidden": "true" }, " →")]),
      ]),
    ]),
    // 지금 고른 선수 이름표 (+ 좁은 화면: 선수 카드로 건너뛰는 버튼). 점을 누르면 바로 아래에서 무엇이 골라졌는지 보인다.
    el("div", { class: "map__picked" }, [
      el("p", { class: "picked__chip", id: "map-picked" }),
      el("button", { class: "btn map__jump", type: "button", onclick: jumpToCard }, "선수 카드 보기 ↓"),
    ]),
    el("ul", { class: "type-legend", id: "map-legend", "aria-label": "유형별 선수 수" }),
    el("details", { class: "type-notes", id: "map-details" }, [
      el("summary", {}, "유형 설명 보기"),
      el("dl", { class: "type-notes__list", id: "map-notes" }),
    ]),
  );
  // 넓은 화면(2열)에서는 유형 설명을 펼쳐 둔다 — 지도 카드가 선수 카드 높이만큼 내려오고, 처음 보는 사람이 유형 뜻을 바로 읽는다.
  // 좁은 화면(1열)에서는 접어 둔다. 화면 폭이 기준을 넘나들 때만 다시 맞춘다.
  const wide = window.matchMedia?.("(min-width: 901px)");
  if (wide) {
    $("map-details").open = wide.matches;
    wide.addEventListener?.("change", (e) => { const d = $("map-details"); if (d) d.open = e.matches; });
  }
}

function jumpToCard() {
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  $("player-card").scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  $("card-name")?.focus({ preventScroll: true });
}

/** 지도 아래 "지금 고른 선수" 이름표. */
function renderPicked() {
  const chip = $("map-picked");
  if (!chip) return;
  const p = state.sel;
  if (!p) { chip.replaceChildren("고른 선수 없음"); return; }
  chip.replaceChildren(
    el("span", { class: "dot", style: { background: colorVar(typeColor(p.group, p.type?.id)) }, "aria-hidden": "true" }),
    el("span", {}, [el("span", { class: "sr-only" }, "지금 고른 선수: "), nameOf(p)]),
    el("small", {}, `${teamNameFor(p.team, p.season)} · ${p.season}`),
  );
}

function renderMap() {
  const g = state.group;
  const all = viewAll();
  const pool = viewPool();
  const types = typesOf(g);
  const team = state.team;
  $("map-lead").textContent = `${state.season} ${GROUP[g]} ${fmtInt(all.length)}명` +
    (team ? ` 중 ${teamNameFor(team, state.season)} ${fmtInt(pool.length)}명을 진하게 표시했습니다.` : "을 기록이 비슷할수록 가깝게 놓았습니다.") +
    " 점을 누르면 선수 카드가 바뀝니다.";
  $("map-legend").replaceChildren(...types.map((t) => el("li", { class: "type-legend__item" }, [
    el("span", { class: "dot", style: { background: colorVar(typeColor(g, t.id)) }, "aria-hidden": "true" }),
    t.name,
    el("b", { class: "num" }, `${fmtInt(pool.filter((p) => p.type?.id === t.id).length)}명`),
  ])));
  $("map-notes").replaceChildren(...types.flatMap((t) => [
    el("dt", {}, [el("span", { class: "dot", style: { background: colorVar(typeColor(g, t.id)) }, "aria-hidden": "true" }), t.name]),
    el("dd", {}, t.blurb ?? "—"),
  ]));
  const chart = $("map-chart");
  if (!pool.length) {
    chart.replaceChildren(el("p", { class: "empty map__empty" }, `${teamNameFor(team, state.season)}에는 ${state.season} ${GROUP[g]} 기록이 없습니다. 팀을 '전체'로 바꿔 보세요.`));
    chart._chartRO?.disconnect();
    return;
  }
  scatter(chart, all.map((p) => ({
    id: p.player_id, x: p.x, y: p.y, entry: p,
    label: `${nameOf(p)} · ${teamNameFor(p.team, p.season)} · ${p.type?.name ?? "—"}`,
  })), {
    colorKey: (pt) => typeColor(g, pt.entry.type?.id),
    typeLabel: (pt) => pt.entry.type?.name ?? "—",
    selectedId: state.sel?.player_id,
    height: "fill", // 지도 높이는 CSS(.map__chart)가 정한다
    dim: team ? (pt) => pt.entry.team !== team : undefined,
    onSelect: (pt) => select(pt.entry, { from: "map" }),
    label: `${state.season} ${GROUP[g]} 유형 지도${team ? ` (${teamNameFor(team, state.season)})` : ""}: 점 하나가 한 선수, 화살표 키로 이동하고 Enter로 고릅니다`,
  });
}

// ---------- 선수 카드 ----------

function renderCard() {
  const body = $("card-body");
  body.setAttribute("aria-busy", "false");
  const p = state.sel;
  if (!p) {
    body.replaceChildren(el("div", { class: "inset" }, el("p", { class: "empty" },
      `${teamNameFor(state.team, state.season)}에는 ${state.season} ${GROUP[state.group]} 기록이 없습니다. 팀을 '전체'로 바꿔 보세요.`)));
    return;
  }
  const tok = typeColor(p.group, p.type?.id);
  const types = typesOf(p.group);
  const members = types.map((t) => {
    const v = p.membership?.[t.id]; // membership[i]의 i는 유형 id (데이터 계약: "유형 id 순서")
    const on = t.id === p.type?.id;
    return el("li", { class: `member${on ? " is-own" : ""}` }, [
      el("span", { class: "member__name" }, [
        el("span", { class: "dot", style: { background: colorVar(typeColor(p.group, t.id)) }, "aria-hidden": "true" }), t.name,
      ]),
      el("span", { class: "member__track", "aria-hidden": "true" },
        el("span", { class: "member__fill", style: { width: `${fin(v) ? Math.max(0, Math.min(1, v)) * 100 : 0}%`, background: colorVar(typeColor(p.group, t.id)) } })),
      el("span", { class: "member__pct num" }, fmtPct(v)),
    ]);
  });
  const stats = (STATS[p.group] ?? []).map(([k, label, f]) => el("div", { class: "stat" }, [
    el("dt", {}, label),
    el("dd", { class: "num" }, f(p.stats?.[k])),
  ]));
  body.replaceChildren(
    el("p", { class: "pcard__type" }, el("span", {
      class: "pill pcard__pill", style: { background: colorVar(tok), color: onColor(tok) },
    }, [el("span", { class: "sr-only" }, "유형 "), p.type?.name ?? "유형 없음"])),
    el("h3", { class: "pcard__name", id: "card-name", tabindex: "-1" }, nameOf(p)),
    el("div", { class: "inset pcard__meta" }, [
      p.name_ko ? el("span", { class: "pcard__roman", lang: "en" }, p.name) : null,
      el("span", { class: "pcard__facts" }, `${teamNameFor(p.team, p.season, { full: true })} · ${POS[p.pos] ?? p.pos ?? "—"} · ${p.season} 시즌`),
    ]),
    el("div", { class: "inset pcard__fit" }, [
      el("div", { class: "pcard__prob" }, [
        el("p", { class: "pcard__prob-label" }, "소속 확신도"),
        el("p", { class: "pcard__prob-num num" }, fmtPct(p.prob)),
      ]),
      el("p", { class: "pcard__note" }, "중심까지 거리 기반 상대 확신도입니다. 실제 빈도로 맞춘 확률은 아닙니다."),
      el("ul", { class: "members", "aria-label": "유형별 소속 확신도" }, members),
    ]),
    el("div", { class: "inset pcard__stats" }, [
      el("p", { class: "pcard__cap" }, `${p.season} 시즌 주요 기록`),
      el("dl", { class: "stats-grid" }, stats),
    ]),
  );
}

// ---------- 비슷한 선수 ----------

function renderSimilar() {
  const body = $("similar-body");
  const p = state.sel;
  if (!p) {
    $("similar-lead").textContent = "선수를 고르면 스탯이 가장 가까운 선수-시즌 5개를 보여 줍니다.";
    body.replaceChildren(el("p", { class: "empty" }, "고른 선수가 없습니다."));
    return;
  }
  $("similar-lead").textContent =
    `기준: ${nameOf(p)}(${p.season}). 스탯이 가장 가까운 ${GROUP[p.group]} 선수-시즌 ${(p.similar ?? []).length}개입니다. 행을 누르면 그 선수로 옮겨 갑니다.`;
  const rows = (p.similar ?? []).map((s) => {
    const e = state.index.get(keyOf(p.group, s.season, s.player_id));
    if (!e) {
      return el("tr", { class: "sim-row is-missing" }, [
        el("td", {}, "기록을 찾지 못함"), el("td", {}, "—"), el("td", { class: "num" }, String(s.season ?? "—")),
        el("td", {}, "—"), el("td", { class: "num" }, fmtRate3(s.similarity)),
      ]);
    }
    const go = () => select(e, { from: "similar", focus: true });
    return el("tr", { class: "sim-row", onclick: go }, [
      el("td", { class: "sim__name" }, el("button", { class: "linkbtn", type: "button",
        "aria-label": `${nameOf(e)} ${e.season} 시즌 보기` }, [
        nameOf(e), e.name_ko ? el("span", { class: "sim__roman", lang: "en" }, e.name) : null,
      ])),
      el("td", {}, teamNameFor(e.team, e.season)),
      el("td", { class: "num" }, String(e.season)),
      el("td", {}, el("span", { class: "sim__type" }, [
        el("span", { class: "dot", style: { background: colorVar(typeColor(e.group, e.type?.id)) }, "aria-hidden": "true" }),
        e.type?.name ?? typeName(e.group, e.type?.id),
      ])),
      el("td", { class: "num" }, fmtRate3(s.similarity)),
    ]);
  });
  body.replaceChildren(rows.length
    ? el("div", { class: "table-scroll" }, el("table", { class: "table sim-table" }, [
      el("caption", { class: "sr-only" }, `비슷한 선수, 기준 ${nameOf(p)} ${p.season} 시즌 (유사도 높은 순)`),
      el("thead", {}, el("tr", {}, [
        el("th", { scope: "col" }, "이름"), el("th", { scope: "col" }, "팀"), el("th", { scope: "col", class: "num" }, "시즌"),
        el("th", { scope: "col" }, "유형"), el("th", { scope: "col", class: "num" }, "유사도"),
      ])),
      el("tbody", {}, rows),
    ]))
    : el("p", { class: "empty" }, "비슷한 선수 기록이 없습니다."));
}

// ---------- 유형 모델 요약 ----------

function renderModel() {
  const body = $("model-body");
  if (!state.report) {
    showError(body, state.errors.report, loadReport);
    return;
  }
  const cq = state.report.cluster_quality;
  if (!cq) {
    body.replaceChildren(el("p", { class: "empty" }, "유형 모델 정보가 없습니다."));
    return;
  }
  const silOf = (g) => (cq[g]?.k_table ?? []).find((row) => row.k === cq[g]?.k)?.silhouette;
  const LOW_SIL = 0.25; // 이보다 낮으면 "유형 경계가 흐리다"고 적는다
  const sils = ["batter", "pitcher"].map(silOf).filter(fin);
  const low = sils.length > 0 && sils.every((v) => v < LOW_SIL);
  const block = (g) => {
    const q = cq[g];
    if (!q) return null;
    const sil = silOf(g);
    return el("div", { class: "inset model__group" }, [
      el("h3", { class: "model__title" }, GROUP[g]),
      el("dl", { class: "model__stats" }, [
        el("div", {}, [el("dt", {}, "유형 수 K"), el("dd", { class: "num" }, String(q.k ?? "—"))]),
        el("div", {}, [el("dt", {}, "실루엣"), el("dd", { class: "num" }, fmtRate3(sil))]),
        el("div", {}, [el("dt", {}, "유지율"), el("dd", { class: "num" }, fmtRate3(q.retention))]),
      ]),
    ]);
  };
  body.replaceChildren(
    el("div", { class: "model__groups" }, ["batter", "pitcher"].map(block)),
    el("ul", { class: "model__notes" }, [
      el("li", {}, "실루엣은 유형끼리 얼마나 또렷이 갈리는지(1에 가까울수록 또렷), 유지율은 연속 두 시즌 모두 자격인 선수의 유형이 그대로인 비율입니다." +
        (low ? " 실루엣이 낮아 유형은 연속적인 분포를 부드럽게 나눈 구분으로 보는 것이 맞습니다." : "")),
      cq.membership_note ? el("li", {}, cq.membership_note) : null,
    ]),
  );
  renderModelMeta();
}

/** 유형 모델 카드 리드: 모델 버전과 맞춘 시즌 (players.json과 model_report.json 둘 다 있으면 players.json 기준). */
function renderModelMeta() {
  const d = state.data;
  const cq = state.report?.cluster_quality;
  const version = d?.model_version ?? cq?.version;
  const fit = d?.fit_seasons ?? cq?.fit_seasons;
  if (!version && !fit) return;
  $("model-lead").textContent = `${version ?? "유형 모델"}: ${fmtRange(fit)} 시즌 선수-시즌 기록으로 맞춘 K-means` +
    (d?.generated_at ? ` · 선수 파일 ${String(d.generated_at).slice(0, 10)} 생성` : "");
}

init();
