// KBO Predict — 팀. teams.html 전용 모듈.
//
// 화면 순서: 머리(#teams-lead + 시즌 고르기 #season-select, ?season=으로도 열림) → 카드 4장 → 푸터 증거 바.
//   #standings(크림, 순위표) #roster-types(라벤더, 로스터 유형 구성) #head-to-head(피치, 상대 전적 10×10)
//   #playoff-rewind(오커, 가을야구 확률 되감기 — 경기일 다시 보기가 있는 시즌만(seasons/index.json의 rewind_seasons, 2018~), 없으면 숨김)
//
// 데이터: teams.json(팀-시즌 120줄)과 model_report.json(유형 이름: cluster_quality.{batter,pitcher}.types[])을
// 처음에 함께 받는다. players.json(1.77 MB)은 읽지 않는다. 시즌을 바꾸면 ①②③은 받아 둔 것으로 다시 그린다(다시 받지 않음).
// ④는 그 시즌을 처음 보여 줄 때 rewind/{시즌}/index.json과 날짜 파일 최대 25개(약 7일 간격 + 마지막 날)를 동시에 받는다(시즌별로 기억).
// 데이터 키는 docs/site/data-contract.md 매핑 표(페이지 "팀")에 적은 것만 쓴다.

import {
  TEAMS, el, fetchJSON, settle, fin, fmtPct, fmtRate3, fmtDate, teamNameFor, typeColor, renderNav, renderFooter, showError,
  teamColors, teamChip, fmtProb, teamLogo,
} from "./app.js";
import { lineChart, stackedBar, enableTips } from "./charts.js";

const $ = (id) => document.getElementById(id);

const FALLBACK_REWIND = [2026]; // seasons/index.json을 못 읽을 때 되감기가 있다고 보는 시즌
const PLAYOFF_SPOTS = 5;      // 가을야구: 정규시즌 5위까지 (2015년부터 와일드카드 포함)
const REWIND_STRIDE = 7;      // 되감기 날짜 표본 간격 (매 7번째 날 + 마지막 날 → 최대 25개 파일)
const LABEL_SHARE = 0.08;     // 로스터 막대 안에 %를 쓰는 최소 비중
const SVGNS = "http://www.w3.org/2000/svg";
// 정규시즌 승률이 같아 결정전(1위·5위)으로 순위를 정한 시즌: 시즌 → [이긴 팀, 진 팀].
// 결정전은 정규시즌 경기가 아니라 teams.json에 없으므로 실제 결과를 여기 적어 둔다 (JSON 문법 — tests/test_site.py가 읽는다).
export const TIEBREAK_GAMES = {"2021": ["KT", "SS"], "2024": ["KT", "SK"]};
// 비중은 유형이 붙은 선수끼리 나눈 값 (기록이 적어 유형이 없는 선수는 뺐다 — site_data.py)
const GROUPS = [["batter", "타자", "유형이 붙은 타자들의 타석 중 이 유형이 맡은 비율"], ["pitcher", "투수", "유형이 붙은 투수들의 이닝 중 이 유형이 던진 비율"]];

const state = {
  teams: null, report: null, status: null, errors: {},
  seasons: [],          // 내림차순
  season: null,
  rewindSeasons: FALLBACK_REWIND,   // 되감기 파일이 있는 시즌 (seasons/index.json의 rewind_seasons)
  rewinds: new Map(),               // 시즌 → { phase, index, days, failed, error }
};

/** 그 시즌의 되감기 상태 (처음이면 idle로 만든다). */
function rewindOf(season) {
  if (!state.rewinds.has(season)) state.rewinds.set(season, { phase: "idle", index: null, days: null, failed: 0, error: null });
  return state.rewinds.get(season);
}

// ---------- 작은 도우미 ----------

/** 반올림 전 승률 (동률 판정용). 승패가 갈린 경기가 없으면 -1. */
const exactPct = (t) => (t.wins + t.losses > 0 ? t.wins / (t.wins + t.losses) : -1);
const shortName = (code, season) => teamNameFor(code, season);
/** 받침에 따라 이/가: "두산이", "롯데가". 영문 이름(KT·SSG·KIA·LG·NC)은 모두 모음 소리로 끝나 "가". */
const iga = (w) => {
  const c = String(w).charCodeAt(String(w).length - 1);
  return `${w}${c >= 0xac00 && c <= 0xd7a3 && (c - 0xac00) % 28 ? "이" : "가"}`;
};
const fullName = (code, season) => teamNameFor(code, season, { full: true });

/** 팀 이름 칸: 넓은 화면은 정식 이름, 좁은 화면은 짧은 이름 (CSS가 하나만 보여 준다). 앞에 팀 색 점. */
function teamCell(code, season) {
  return [
    el("span", { class: "dot team-dot", style: { background: `var(--${TEAMS[code]?.color ?? "muted-soft"})` }, "aria-hidden": "true" }),
    teamLogo(code, { season, size: "sm" }),
    el("span", { class: "tn-full" }, fullName(code, season)),
    el("span", { class: "tn-short" }, shortName(code, season)),
  ];
}

// ---------- 읽기 ----------

const loadTeams = () => settle(state, "teams", fetchJSON("teams.json"));
const loadReport = () => settle(state, "report", fetchJSON("model_report.json"));

async function init() {
  renderNav("teams.html");
  const seasonsIndex = { errors: {} };   // 시즌 목록은 없어도 페이지는 그린다(되감기는 FALLBACK_REWIND만)
  await Promise.all([loadTeams(), loadReport(), settle(state, "status", fetchJSON("status.json", { fresh: true })),
    settle(seasonsIndex, "data", fetchJSON("seasons/index.json", { fresh: true }))]);
  if (Array.isArray(seasonsIndex.data?.rewind_seasons)) state.rewindSeasons = seasonsIndex.data.rewind_seasons;
  renderFooter(state.status);
  setupSeasons();
  renderAll();
}

// ---------- 시즌 고르기 ----------

function setupSeasons() {
  const select = $("season-select");
  if (!state.teams) return;
  state.seasons = [...new Set((state.teams.teams ?? []).map((t) => t.season).filter(fin))].sort((a, b) => b - a);
  const asked = Number(new URLSearchParams(location.search).get("season"));
  state.season = state.seasons.includes(asked) ? asked : state.seasons[0] ?? null;
  select.replaceChildren(...state.seasons.map((y) => el("option", { value: String(y) }, String(y))));
  select.value = String(state.season);
  select.disabled = false;
  if (!select.dataset.bound) {
    select.dataset.bound = "1";
    select.addEventListener("change", (e) => {
      state.season = Number(e.target.value);
      const url = new URL(location.href);
      url.searchParams.set("season", String(state.season));
      history.replaceState(null, "", url);
      renderAll();
      $("season-status").textContent = `${state.season} 시즌을 표시합니다.`;
    });
  }
}

const sameExact = (a, b) => Math.abs(exactPct(a) - exactPct(b)) < 1e-12;

/**
 * 승률이 같은 두 팀(a, b)의 순서와 그것을 정한 규칙. order < 0이면 a가 위.
 * 결정전(TIEBREAK_GAMES) → 상대 전적(5할이 아닐 때) → 코드순(임의, 데이터로 가릴 수 없음).
 */
function tieRule(a, b, season) {
  const game = TIEBREAK_GAMES[String(season)];
  if (game && game.includes(a.code) && game.includes(b.code)) {
    return { order: game[0] === a.code ? -1 : 1, rule: "결정전 승리(정규시즌 성적 미포함)" };
  }
  const h = a.vs?.[b.code];
  if (fin(h) && Number(h) !== 0.5) return { order: h > 0.5 ? -1 : 1, rule: "상대 전적", h2h: Number(h) };
  return { order: a.code.localeCompare(b.code), rule: "동률·코드순(임의)" };
}

/** 그 시즌 10팀을 순위 순서로. 승률(반올림 전) → 같으면 tieRule. tied = 승률이 같은 팀이 있는 줄. */
function standings(season) {
  const rows = (state.teams?.teams ?? []).filter((t) => t.season === season && TEAMS[t.code]);
  rows.sort((a, b) => {
    const d = exactPct(b) - exactPct(a);
    return Math.abs(d) > 1e-12 ? d : tieRule(a, b, season).order;
  });
  return rows.map((t, i) => ({ ...t, rank: i + 1, tied: rows.some((o) => o !== t && sameExact(o, t)) }));
}

/** 동률 메모: 이웃한 동률 두 팀마다 "KT > 삼성 (승률 .563 동률): 결정전 승리(정규시즌 성적 미포함)". */
function tieNotes(rows, season) {
  const out = [];
  rows.forEach((r, i) => {
    const next = rows[i + 1];
    if (!next || !sameExact(r, next)) return;
    const t = tieRule(r, next, season);
    const why = t.rule === "상대 전적" ? `상대 전적 ${fmtRate3(t.h2h)}` : t.rule;
    out.push(`${shortName(r.code, season)} > ${shortName(next.code, season)} (승률 ${fmtRate3(r.win_pct)} 동률): ${why}`);
  });
  return out;
}

function renderAll() {
  if (!state.teams) {
    const retry = async () => { await loadTeams(); setupSeasons(); renderAll(); };
    for (const id of ["standings-body", "roster-body", "h2h-body"]) {
      $(id).setAttribute("aria-busy", "false");
      showError($(id), state.errors.teams, retry);
    }
    $("playoff-rewind").hidden = true;
    return;
  }
  const rows = standings(state.season);
  renderStandings(rows);
  renderRoster(rows);
  renderH2H(rows);
  renderRewind();
}

// ---------- ① 순위표 ----------

/** 인라인 SVG 노드 만들기 (순위표 눈금 열 전용). */
function svg(tag, attrs = {}, children = []) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, String(v));
  for (const c of [].concat(children)) n.append(typeof c === "string" ? document.createTextNode(c) : c);
  return n;
}

/** 눈금 범위: 실제·피타고리안·모델 값과 .500을 모두 담는 0.05 단위 구간(양쪽에 0.03 여유). */
function rulerDomain(rows) {
  const vals = rows.flatMap((r) => [r.win_pct, r.pyth_pct, r.model_expected]).filter(fin).map(Number).concat(0.5);
  const lo = Math.floor((Math.min(...vals) - 0.03) * 20) / 20;
  const hi = Math.ceil((Math.max(...vals) + 0.03) * 20) / 20;
  return [lo, hi];
}
const pctPos = (v, [lo, hi]) => `${(((Number(v) - lo) / (hi - lo || 1)) * 100).toFixed(2)}%`;

/** 머리글 눈금: 0.10 간격 숫자, .500은 굵게. */
function rulerHead(dom) {
  const [lo, hi] = dom;
  const ticks = [];
  for (let v = Math.ceil(lo * 10) / 10; v <= hi + 1e-9; v = Math.round((v + 0.1) * 10) / 10) ticks.push(v);
  return svg("svg", { class: "ruler__head", width: "100%", height: 26, "aria-hidden": "true", focusable: "false" },
    ticks.map((v) => svg("text", {
      x: pctPos(v, dom), y: 18, "text-anchor": "middle", class: Math.abs(v - 0.5) < 1e-9 ? "ruler__tick is-half" : "ruler__tick",
    }, fmtRate3(v))));
}

/** 한 줄 눈금: 실제(● 잉크) · 피타고리안(○ 고리) · 모델 기대(◆ 핑크). 실제↔피타고리안 사이는 잉크 선. */
function rulerRow(r, dom) {
  const [lo, hi] = dom;
  const ticks = [];
  for (let v = Math.ceil(lo * 10) / 10; v <= hi + 1e-9; v = Math.round((v + 0.1) * 10) / 10) ticks.push(v);
  const has = (v) => fin(v);
  const mid = 20;
  const kids = [
    ...ticks.map((v) => svg("line", { class: Math.abs(v - 0.5) < 1e-9 ? "ruler__half" : "ruler__grid", x1: pctPos(v, dom), x2: pctPos(v, dom), y1: 0, y2: 40 })),
    svg("line", { class: "ruler__track", x1: 0, x2: "100%", y1: mid, y2: mid }),
  ];
  if (has(r.win_pct) && has(r.pyth_pct)) kids.push(svg("line", { class: "ruler__gap", x1: pctPos(r.win_pct, dom), x2: pctPos(r.pyth_pct, dom), y1: mid, y2: mid }));
  if (has(r.pyth_pct)) kids.push(svg("circle", { class: "ruler__pyth", cx: pctPos(r.pyth_pct, dom), cy: mid, r: 6 }));
  if (has(r.model_expected)) {
    const x = pctPos(r.model_expected, dom);
    // 퍼센트 위치에 마름모를 놓으려고 안쪽 svg의 x를 퍼센트로 준다 (그 안에서 45도 돌린 정사각형)
    kids.push(svg("svg", { x, y: mid, width: 1, height: 1, overflow: "visible" },
      svg("rect", { class: "ruler__model", x: -6, y: -6, width: 12, height: 12, transform: "rotate(45)" })));
  }
  if (has(r.win_pct)) kids.push(svg("circle", { class: "ruler__act", cx: pctPos(r.win_pct, dom), cy: mid, r: 7 }));
  const say = [`실제 ${fmtRate3(r.win_pct)}`, `득실 기대 ${fmtRate3(r.pyth_pct)}`, has(r.model_expected) ? `모델 예상 ${fmtRate3(r.model_expected)}` : null].filter(Boolean).join(", ");
  // 툴팁: 행 전체를 덮는 투명 칸 (마우스·탭) — 값 세 개를 줄 단위로
  kids.push(svg("rect", { x: 0, y: 0, width: "100%", height: 40, fill: "transparent", "data-tip": `${shortName(r.code, state.season)}
${say.replaceAll(", ", "\n")}` }));
  const node = svg("svg", { class: "ruler__row", width: "100%", height: 40, role: "img", "aria-label": `${shortName(r.code, state.season)} ${say}`, focusable: "false" }, kids);
  enableTips(node);
  return node;
}

/** pp 표기: +4.1%p / −2.3%p */
const pp = (d) => `${d >= 0 ? "+" : "−"}${Math.abs(d * 100).toFixed(1)}%p`;

function renderStandings(rows) {
  const body = $("standings-body");
  const season = state.season;
  const hasModel = rows.some((r) => fin(r.model_expected));
  const games = [...new Set(rows.map((r) => r.games))];
  $("standings-lead").textContent =
    `${season} 정규시즌 ${rows.length}팀, 팀당 ${games.length === 1 ? games[0] : `${Math.min(...games)}~${Math.max(...games)}`}경기. 승률 순서이고, 무승부는 승률 계산에서 뺍니다.`;

  const dom = rulerDomain(rows);
  const cols = [
    ["순위", "num rank-col"], ["팀", "team-col"], ["승-패-무", "num wlt-col"], ["승률", "num win-col"],
    [[el("span", { class: "tn-full", title: "득점과 실점만으로 계산한 '이만큼은 이겼어야 할' 승률(피타고리안 승률)입니다." }, "득실 기대 승률"), el("span", { class: "tn-short" }, "기대")], "num pyth-col"],
    ...(hasModel ? [[[el("span", { class: "tn-full" }, "모델 예상 승률"), el("span", { class: "tn-short" }, "모델"), el("span", { class: "th-note" }, `${season} 경기별 예측 확률 평균`)], "num model-col"]] : []),
    [[el("span", { class: "sr-only" }, "한눈에 비교 (눈금)"), rulerHead(dom)], "ruler-col"],
    ["경기", "num hide-sm"], ["홈 승률", "num hide-sm"], ["원정 승률", "num hide-sm"],
  ];
  const tr = (r) => el("tr", { class: r.rank <= PLAYOFF_SPOTS ? "is-playoff" : null }, [
    el("td", { class: "num rank-col" }, [String(r.rank), r.tied ? el("span", { class: "tie-mark", title: "승률 동률" }, "†") : null]),
    el("th", { scope: "row", class: "team-col" }, [
      ...teamCell(r.code, season),
      r.rank <= PLAYOFF_SPOTS ? el("span", { class: "sr-only" }, " (가을야구 진출)") : null,
    ]),
    el("td", { class: "num nowrap wlt-col" }, `${r.wins}-${r.losses}-${r.ties}`),
    el("td", { class: "num win-col" }, fmtRate3(r.win_pct)),
    el("td", { class: "num pyth-col" }, fmtRate3(r.pyth_pct)),
    hasModel ? el("td", { class: "num model-col" }, fmtRate3(r.model_expected)) : null,
    el("td", { class: "ruler-col" }, rulerRow(r, dom)),
    el("td", { class: "num hide-sm" }, String(r.games ?? "—")),
    el("td", { class: "num hide-sm" }, fmtRate3(r.home_pct)),
    el("td", { class: "num hide-sm" }, fmtRate3(r.away_pct)),
  ]);

  // 무대 위 한 줄: 눈금 범례 + 실제 승률이 피타고리안과 가장 크게 어긋난 두 팀 (접전 운)
  const gaps = rows.filter((r) => fin(r.win_pct) && fin(r.pyth_pct)).map((r) => ({ r, d: Number(r.win_pct) - Number(r.pyth_pct) }));
  const up = gaps.reduce((b, g) => (!b || g.d > b.d ? g : b), null);
  const down = gaps.reduce((b, g) => (!b || g.d < b.d ? g : b), null);
  const chip = (label, g) => g ? el("li", { class: "fact" }, [el("span", { class: "fact__label" }, label), teamChip(g.r.code, shortName(g.r.code, season), "tchip--sm"), el("span", { class: "fact__num num" }, pp(g.d))]) : null;
  const legend = el("ul", { class: "ruler__legend", "aria-label": "눈금 보는 법" }, [
    el("li", {}, [el("i", { class: "mk mk--act", "aria-hidden": "true" }), "실제 승률"]),
    el("li", {}, [el("i", { class: "mk mk--pyth", "aria-hidden": "true" }), "득실 기대 승률"]),
    hasModel ? el("li", {}, [el("i", { class: "mk mk--model", "aria-hidden": "true" }), "모델 예상"]) : null,
    el("li", {}, [el("i", { class: "mk mk--half", "aria-hidden": "true" }), "5할(.500) 선"]),
  ]);
  const facts = gaps.length > 1 ? el("ul", { class: "facts", "aria-label": "실제 승률과 득실 기대 승률의 차이" }, [
    chip("득실에 비해 가장 많이 이긴 팀", up), chip("득실에 비해 가장 덜 이긴 팀", down),
  ]) : null;
  const cut = el("tr", { class: "cutline", "aria-hidden": "true" },
    el("td", { colspan: String(cols.length) }, el("span", { class: "cutline__label" }, `여기까지 가을야구 (${PLAYOFF_SPOTS}위까지)`)));
  const bodyRows = rows.flatMap((r) => (r.rank === PLAYOFF_SPOTS && rows.length > PLAYOFF_SPOTS ? [tr(r), cut] : [tr(r)]));

  const notes = [
    el("li", {}, "득실 기대 승률(피타고리안): 득점과 실점만으로 계산한 '이만큼은 이겼어야 할' 승률입니다. 실제 승률이 이보다 높으면 접전에서 많이 이긴 편입니다."),
    hasModel
      ? el("li", {}, `모델 예상 승률: 모델이 ${season} 경기마다 낸 이 팀의 승리 확률을 평균한 값입니다. 실제 승률과는 다른 숫자입니다. 모델은 ${season} 시즌을 배우지 않았습니다. 확률이 50% 근처에 모이는 편이라 팀 사이 차이가 실제 승률보다 작게 나옵니다.`)
      : el("li", {}, `모델 예상 승률은 모델이 배우지 않은 시즌(${modelSeasons().join("·") || "없음"})에만 있습니다. ${season} 시즌은 모델이 이미 본 시즌이라 뺐습니다.`),
    ...tieNotes(rows, season).map((t) => el("li", {}, `†: ${t}`)),
    TIEBREAK_GAMES[String(season)] && rows.some((r) => r.tied)
      ? el("li", {}, "결정전은 정규시즌 경기가 아니라 데이터에 없어서 실제 결과를 따로 적었습니다. 승패와 승률에는 넣지 않았습니다.")
      : null,
  ];

  body.setAttribute("aria-busy", "false");
  body.replaceChildren(
    el("div", { class: "stage__bar" }, [legend, facts]),
    el("div", { class: "table-scroll standings-scroll", tabindex: "0", role: "region", "aria-label": `${season} 순위표 (가로로 넘겨 보기)` }, el("table", { class: "table standings" }, [
      // 눈금 열 머리글은 위에서 만든 SVG를 함께 담는다
      el("caption", { class: "sr-only" }, `${season} 정규시즌 순위표 (위 ${PLAYOFF_SPOTS}팀 가을야구)`),
      el("thead", {}, el("tr", {}, cols.map(([t, c]) => el("th", { scope: "col", class: c ?? null }, t)))),
      el("tbody", {}, bodyRows),
    ])),
    el("details", { class: "more" }, [el("summary", {}, "표 읽는 법"), el("ul", {}, notes)]),
  );
}

// ---------- ② 로스터 유형 구성 ----------

function renderRoster(rows) {
  const body = $("roster-body");
  body.setAttribute("aria-busy", "false");
  if (!state.report) {
    showError(body, `${state.errors.report ?? ""} 유형 이름을 불러오지 못해 팀 선수 구성을 그리지 못했습니다.`, async () => {
      await loadReport();
      if (state.teams) renderRoster(standings(state.season));
    });
    return;
  }
  const season = state.season;
  const blocks = GROUPS.map(([g, title, sub]) => {
    const types = state.report.cluster_quality?.[g]?.types ?? [];
    const keys = types.map((t) => String(t.id));
    const chart = el("div", { class: "roster__chart" });
    const block = el("div", { class: "inset roster__block" }, [
      el("h3", { class: "roster__title" }, [title, el("span", { class: "roster__sub" }, sub)]),
      chart,
    ]);
    // 그리기는 붙인 뒤에 (너비를 재야 하므로)
    block._draw = () => stackedBar(chart, rows.map((r) => ({ label: shortName(r.code, season), ...(r.roster_types?.[g] ?? {}) })), {
      keys,
      colors: Object.fromEntries(keys.map((k) => [k, typeColor(g, k)])),
      labels: Object.fromEntries(types.map((t) => [String(t.id), t.name])),
      minShare: LABEL_SHARE,
      label: `${season} 팀별 ${title} 유형 구성 (${g === "batter" ? "타석" : "이닝"} 비율, 순위 순서)`,
    });
    return block;
  });
  body.replaceChildren(el("div", { class: "roster" }, blocks));
  blocks.forEach((b) => b._draw());
}

// ---------- ③ 상대 전적 ----------

/**
 * 승률 → 잉크 투명도. 5할에서 끊는다: 5할 아래는 0.04~0.42(잉크 글자), 5할 이상은 0.62~0.90(흰 글자).
 * 그래서 진한 칸 = 이긴 전적이고, 두 글자색 모두 대비 4.5:1 이상이다.
 */
const clamp01 = (v) => Math.min(1, Math.max(0, v));
const winning = (p) => p >= 0.5;
const inkAlpha = (p) => (winning(p) ? 0.62 + 0.28 * clamp01((p - 0.5) / 0.3) : 0.04 + 0.38 * clamp01((p - 0.2) / 0.3));

function renderH2H(rows) {
  const body = $("h2h-body");
  const season = state.season;
  const codes = rows.map((r) => r.code);
  const head = el("tr", {}, [
    el("th", { scope: "col", class: "h2h__corner" }, el("span", { class: "sr-only" }, "팀 \\ 상대")),
    ...codes.map((c) => el("th", { scope: "col", class: "h2h__col" }, el("abbr", { title: fullName(c, season) }, shortName(c, season)))),
  ]);
  const bodyRows = rows.map((r) => el("tr", {}, [
    el("th", { scope: "row", class: "h2h__row" }, shortName(r.code, season)),
    ...codes.map((c) => {
      if (c === r.code) return el("td", { class: "h2h__cell h2h__self" }, el("span", { "aria-label": "같은 팀" }, "—"));
      const v = r.vs?.[c];
      if (!fin(v)) return el("td", { class: "h2h__cell" }, "—");
      const a = inkAlpha(Number(v));
      const dark = winning(Number(v));
      return el("td", {
        class: `h2h__cell num${dark ? " is-dark" : ""}`,
        style: { background: `rgba(10, 10, 10, ${a.toFixed(2)})` },
        "data-tip": `${shortName(r.code, season)}의 ${shortName(c, season)}전 승률
${fmtRate3(v)}`,
      }, fmtRate3(v));
    }),
  ]));
  const grid = el("div", { class: "inset h2h__frame" }, el("div", { class: "table-scroll h2h__scroll", tabindex: "0", role: "region", "aria-label": `${season} 상대 전적 표 (가로로 넘겨 보기)` },
    el("table", { class: "h2h" }, [
      el("caption", { class: "sr-only" }, `${season} 상대 전적: 왼쪽 팀이 위쪽 팀을 상대로 거둔 승률 (무승부 제외)`),
      el("thead", {}, head),
      el("tbody", {}, bodyRows),
    ])));

  // 숫자 두 개만 따로 꺼내 둔다: 가장 일방적인 맞대결, 1위 팀이 5할 아래였던 상대
  let top = null;
  rows.forEach((r) => Object.entries(r.vs ?? {}).forEach(([c, v]) => {
    if (fin(v) && codes.includes(c) && (!top || v > top.v)) top = { a: r.code, b: c, v: Number(v) };
  }));
  const first = rows[0];
  const weak = first ? Object.entries(first.vs ?? {}).filter(([c, v]) => fin(v) && v < 0.5 && codes.includes(c)).sort((x, y) => x[1] - y[1]) : [];
  const aside = el("div", { class: "h2h__aside" }, [
    top ? el("div", { class: "inset h2h__fact" }, [
      el("p", { class: "h2h__fact-label" }, "가장 한쪽으로 기운 맞대결"),
      el("p", { class: "h2h__fact-big num" }, fmtRate3(top.v)),
      el("p", {}, `${shortName(top.a, season)}의 ${shortName(top.b, season)}전 승률`),
    ]) : null,
    first ? el("div", { class: "inset h2h__fact" }, [
      el("p", { class: "h2h__fact-label" }, `1위 ${iga(shortName(first.code, season))} 5할을 못 넘긴 상대`),
      weak.length
        ? el("ul", { class: "h2h__weak" }, weak.map(([c, v]) => el("li", {}, [el("span", {}, shortName(c, season)), el("b", { class: "num" }, fmtRate3(v))])))
        : el("p", {}, "없습니다. 모든 상대에게 5할 이상을 거뒀습니다."),
    ]) : null,
    el("div", { class: "h2h__scale", "aria-hidden": "true" }, [
      el("span", { class: "h2h__ramp" }),
      el("span", { class: "h2h__ramp-labels" }, [el("span", {}, ".200 적게 이김"), el("span", {}, ".500"), el("span", {}, "많이 이김 .800")]),
    ]),
  ]);
  body.setAttribute("aria-busy", "false");
  body.replaceChildren(el("div", { class: "h2h-layout" }, [grid, aside]));
  enableTips(grid);
}

/** teams.json에 모델 예상 승률(model_expected)이 있는 시즌 — 모델이 배우지 않은 시즌. */
function modelSeasons() {
  return [...new Set((state.teams?.teams ?? []).filter((t) => fin(t.model_expected)).map((t) => t.season))].sort();
}

// ---------- ④ 가을야구 확률 되감기 (다시 보기가 있는 시즌) ----------

function renderRewind() {
  const section = $("playoff-rewind");
  const season = state.season;
  section.hidden = !state.rewindSeasons.includes(season);
  if (section.hidden) return;
  $("rewind-title").textContent = `${season} 가을야구 확률 변화`;
  $("rewind-lead").textContent = `${season} 시즌 동안 날짜별로 계산한 5위 안에 들 확률입니다.` +
    (modelSeasons().includes(season) ? "" : ` 그 시즌보다 앞선 시즌들로만 학습한 모델로 계산했습니다.`);
  const rw = rewindOf(season);
  if (rw.phase === "idle") { loadRewind(); return; }
  if (rw.phase === "done") drawRewind();
  else if (rw.phase === "error") showRewindError();
  else $("rewind-body").replaceChildren(el("div", { class: "inset" }, el("div", { class: "skeleton skel-line" })),
    el("p", { class: "rewind__progress", role: "status" }, "날짜별 확률을 불러오는 중…")); // 다른 시즌을 보다 돌아왔는데 아직 받는 중
}

/** 되감기 실패 상자 (다른 시즌을 보는 사이에 실패했어도 그 시즌으로 돌아오면 이것을 보여 준다). */
function showRewindError() {
  const rw = rewindOf(state.season);
  const body = $("rewind-body");
  body.setAttribute("aria-busy", "false");
  const box = showError(body, rw.error ?? "", () => { rw.phase = "idle"; renderRewind(); });
  box.querySelector("strong").textContent = "날짜별 확률을 불러오지 못했습니다. ";
}

/** 표본 날짜: 매 STRIDE번째 날 + 마지막 날. */
function sampleDates(dates) {
  const picked = dates.filter((_, i) => i % REWIND_STRIDE === 0);
  if (dates.length && picked.at(-1) !== dates.at(-1)) picked.push(dates.at(-1));
  return picked;
}

async function loadRewind() {
  const season = state.season;
  const rw = rewindOf(season);
  const body = $("rewind-body");
  rw.phase = "loading";
  body.setAttribute("aria-busy", "true");
  const progress = el("p", { class: "rewind__progress", role: "status" }, "날짜별 확률을 불러오는 중…");
  body.replaceChildren(el("div", { class: "inset" }, el("div", { class: "skeleton skel-line" })), progress);
  try {
    rw.index = await fetchJSON(`rewind/${season}/index.json`, { fresh: true });
    const dates = sampleDates((rw.index.dates ?? []).map((d) => d.date).filter(Boolean));
    let done = 0;
    progress.textContent = `날짜 ${dates.length}개 중 0개 불러옴…`;
    const results = await Promise.allSettled(dates.map((d) => fetchJSON(`rewind/${season}/${d}.json`).finally(() => {
      done += 1;
      progress.textContent = `날짜 ${dates.length}개 중 ${done}개 불러옴…`;
    })));
    rw.days = dates.map((d, i) => ({ date: d, outlook: results[i].status === "fulfilled" ? results[i].value?.outlook ?? null : null }));
    rw.failed = rw.days.filter((d) => !d.outlook?.teams).length;
    if (rw.days.length - rw.failed < 2) throw new Error(`날짜 ${dates.length}개 중 ${rw.failed}개를 불러오지 못했습니다.`);
    rw.phase = "done";
  } catch (err) {
    rw.phase = "error";
    rw.error = err.message;
  }
  if (state.season !== season) return; // 받는 사이 시즌을 바꿨으면 그 시즌을 다시 고를 때 그린다
  body.setAttribute("aria-busy", "false");
  if (rw.phase === "done") drawRewind();
  else showRewindError();
}

/** 되감기 선 모양: 두산(실선)·KT·롯데가 모두 남색·검정 계열이라 KT는 점선, 롯데는 점점선. 나머지 팀은 색만으로 구분된다. */
const LINE_DASH = { KT: "7 5", LT: "2 4" };

function drawRewind() {
  const season = state.season;
  const rw = rewindOf(season);
  const body = $("rewind-body");
  const days = rw.days;
  const x = (d) => { const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(d.outlook?.as_of ?? d.date); return m ? `${+m[1]}.${+m[2]}` : d.date; }; // 짧은 날짜는 사이트 전체 "11.3"
  const lastDay = days.findLast((d) => d.outlook?.teams);
  const final = (code) => lastDay?.outlook?.teams?.[code]?.playoff_prob;
  const codes = Object.keys(TEAMS).filter((c) => days.some((d) => fin(d.outlook?.teams?.[c]?.playoff_prob)));
  // 팀마다 구단 대표색(tokens.css --team-*)을 쓴다. 두산·KT·롯데는 셋 다 남색·검정 계열이라 선 모양으로 가른다(LINE_DASH).
  const series = codes
    .sort((a, b) => (final(b) ?? -1) - (final(a) ?? -1) || a.localeCompare(b))
    .map((c) => ({
      name: shortName(c, season),
      short: shortName(c, season),
      legend: `${shortName(c, season)} ${fmtProb(final(c))}`,
      color: TEAMS[c].color,
      ink: teamColors(c).ink,                       // 오른쪽 끝 이름표 = 그 팀 글자색 (어느 선이 어느 팀인지 범례 없이)
      dash: LINE_DASH[c] ?? false,
      points: days.map((d) => ({ x: x(d), y: d.outlook?.teams?.[c]?.playoff_prob ?? null })),
    }));
  const chart = el("div", { class: "rewind__chart" });
  const first = days.find((d) => d.outlook?.teams);
  body.replaceChildren(
    el("div", { class: "inset rewind__frame" }, chart),
    el("details", { class: "more rewind__note" }, [el("summary", {}, "그래프 읽는 법"), el("p", {},
      `${fmtDate(first?.outlook?.as_of ?? first?.date)}부터 ${fmtDate(lastDay?.outlook?.as_of ?? lastDay?.date)}까지 약 일주일 간격으로 ${days.length - rw.failed}개 날짜를 골랐습니다. ` +
      "각 점은 그날 경기 전 성적으로 남은 경기를 가상으로 1만 번 치러 5위 안에 든 비율입니다. 이름 옆 숫자는 마지막 날짜의 확률입니다. 선 색은 구단 대표색이고, 색이 비슷한 KT는 점선, 롯데는 점점선입니다." +
      (rw.failed ? ` 날짜 ${rw.failed}개는 불러오지 못해 선을 끊었습니다.` : ""))]),
  );
  lineChart(chart, series, {
    yDomain: [0, 1], yFormat: (v) => fmtPct(v), height: 300, endLabels: true,
    label: `${season} 팀별 가을야구 진출 확률 추이`,
  });
}

init();
