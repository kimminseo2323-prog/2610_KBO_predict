// KBO Predict — 팀. teams.html 전용 모듈.
//
// 화면 순서: 머리(#teams-lead + 시즌 고르기 #season-select, ?season=으로도 열림) → 카드 4장 → 푸터 증거 바.
//   #standings(크림, 순위표) #roster-types(라벤더, 로스터 유형 구성) #head-to-head(피치, 상대 전적 10×10)
//   #playoff-rewind(오커, 가을야구 확률 되감기 — 2026만, 다른 시즌이면 숨김)
//
// 데이터: teams.json(팀-시즌 120줄)과 model_report.json(유형 이름: cluster_quality.{batter,pitcher}.types[])을
// 처음에 함께 받는다. players.json(1.77 MB)은 읽지 않는다. 시즌을 바꾸면 ①②③은 받아 둔 것으로 다시 그린다(다시 받지 않음).
// ④는 2026을 처음 보여 줄 때 rewind/2026/index.json과 날짜 파일 최대 25개(약 7일 간격 + 마지막 날)를 동시에 받는다.
// 데이터 키는 docs/site/data-contract.md 매핑 표(페이지 "팀")에 적은 것만 쓴다.

import {
  TEAMS, el, fetchJSON, settle, fin, fmtPct, fmtRate3, fmtDate, teamNameFor, typeColor, renderNav, renderFooter, showError,
} from "./app.js";
import { lineChart, stackedBar } from "./charts.js";

const $ = (id) => document.getElementById(id);

const REWIND_SEASON = 2026;   // 되감기 파일이 있는 유일한 시즌 (rewind/2026/)
const PLAYOFF_SPOTS = 5;      // 가을야구: 정규시즌 5위까지 (2015년부터 와일드카드 포함)
const REWIND_STRIDE = 7;      // 되감기 날짜 표본 간격 (매 7번째 날 + 마지막 날 → 최대 25개 파일)
const LABEL_SHARE = 0.08;     // 로스터 막대 안에 %를 쓰는 최소 비중
// 정규시즌 승률이 같아 결정전(1위·5위)으로 순위를 정한 시즌: 시즌 → [이긴 팀, 진 팀].
// 결정전은 정규시즌 경기가 아니라 teams.json에 없으므로 실제 결과를 여기 적어 둔다 (JSON 문법 — tests/test_site.py가 읽는다).
export const TIEBREAK_GAMES = {"2021": ["KT", "SS"], "2024": ["KT", "SK"]};
const GROUPS = [["batter", "타자", "팀 타석(PA) 중 그 유형 타자가 선 비중"], ["pitcher", "투수", "팀 이닝(IP) 중 그 유형 투수가 던진 비중"]];

const state = {
  teams: null, report: null, status: null, errors: {},
  seasons: [],          // 내림차순
  season: null,
  rewind: { phase: "idle", index: null, days: null, failed: 0, error: null },
};

// ---------- 작은 도우미 ----------

/** 반올림 전 승률 (동률 판정용). 승패가 갈린 경기가 없으면 -1. */
const exactPct = (t) => (t.wins + t.losses > 0 ? t.wins / (t.wins + t.losses) : -1);
const shortName = (code, season) => teamNameFor(code, season);
const fullName = (code, season) => teamNameFor(code, season, { full: true });

/** 팀 이름 칸: 넓은 화면은 정식 이름, 좁은 화면은 짧은 이름 (CSS가 하나만 보여 준다). 앞에 팀 색 점. */
function teamCell(code, season) {
  return [
    el("span", { class: "dot team-dot", style: { background: `var(--${TEAMS[code]?.color ?? "muted-soft"})` }, "aria-hidden": "true" }),
    el("span", { class: "tn-full" }, fullName(code, season)),
    el("span", { class: "tn-short" }, shortName(code, season)),
  ];
}

// ---------- 읽기 ----------

const loadTeams = () => settle(state, "teams", fetchJSON("teams.json"));
const loadReport = () => settle(state, "report", fetchJSON("model_report.json"));

async function init() {
  renderNav("teams.html");
  await Promise.all([loadTeams(), loadReport(), settle(state, "status", fetchJSON("status.json", { fresh: true }))]);
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

function renderStandings(rows) {
  const body = $("standings-body");
  const season = state.season;
  const hasModel = rows.some((r) => fin(r.model_expected));
  const version = state.teams.model_version ?? "report-2026";
  const games = [...new Set(rows.map((r) => r.games))];
  $("standings-lead").textContent =
    `${season} 정규시즌 ${rows.length}팀, 팀당 ${games.length === 1 ? games[0] : `${Math.min(...games)}~${Math.max(...games)}`}경기. 승률 순서이고, 무승부는 승률 계산에서 뺍니다.`;

  const cols = [
    ["순위", "num rank-col"], ["팀"], ["경기", "num"], ["승-패-무", "num"], ["승률", "num"], ["피타고리안", "num"],
    ...(hasModel ? [[[ "모델 기대 승률", el("span", { class: "th-note" }, `${version} 홀드아웃 예측 평균`)], "num model-col"]] : []),
    ["홈 승률", "num"], ["원정 승률", "num"],
  ];
  const tr = (r) => el("tr", { class: r.rank <= PLAYOFF_SPOTS ? "is-playoff" : null }, [
    el("td", { class: "num rank-col" }, [String(r.rank), r.tied ? el("span", { class: "tie-mark", title: "승률 동률" }, "†") : null]),
    el("th", { scope: "row", class: "team-col" }, [
      ...teamCell(r.code, season),
      r.rank <= PLAYOFF_SPOTS ? el("span", { class: "sr-only" }, " (가을야구 진출)") : null,
    ]),
    el("td", { class: "num" }, String(r.games ?? "—")),
    el("td", { class: "num nowrap" }, `${r.wins}-${r.losses}-${r.ties}`),
    el("td", { class: "num strong" }, fmtRate3(r.win_pct)),
    el("td", { class: "num" }, fmtRate3(r.pyth_pct)),
    hasModel ? el("td", { class: "num model-col" }, fmtRate3(r.model_expected)) : null,
    el("td", { class: "num" }, fmtRate3(r.home_pct)),
    el("td", { class: "num" }, fmtRate3(r.away_pct)),
  ]);
  const cut = el("tr", { class: "cutline", "aria-hidden": "true" },
    el("td", { colspan: String(cols.length) }, el("span", { class: "cutline__label" }, `가을야구 · 위 ${PLAYOFF_SPOTS}팀`)));
  const bodyRows = rows.flatMap((r) => (r.rank === PLAYOFF_SPOTS && rows.length > PLAYOFF_SPOTS ? [tr(r), cut] : [tr(r)]));

  const notes = [
    el("li", {}, "피타고리안: 득점과 실점만으로 계산한 기대 승률입니다. 실제 승률이 이보다 높으면 접전을 많이 이긴 팀입니다."),
    hasModel
      ? el("li", {}, `모델 기대 승률: ${version} 모델이 ${season} 경기마다 낸 그 팀의 승리 확률을 평균한 값으로, 승률과 다릅니다. 이 모델은 ${season} 시즌을 학습에 쓰지 않았고(홀드아웃), 확률이 50% 가까이에 모이므로 실제 승률보다 폭이 좁습니다.`)
      : el("li", {}, `모델 기대 승률은 학습에 쓰지 않은 ${REWIND_SEASON} 시즌에만 있습니다. ${season} 시즌은 모델이 학습하거나 검증할 때 본 시즌이라 열을 뺐습니다.`),
    ...tieNotes(rows, season).map((t) => el("li", {}, `†: ${t}`)),
    TIEBREAK_GAMES[String(season)] && rows.some((r) => r.tied)
      ? el("li", {}, "결정전은 정규시즌 경기가 아니라 데이터에 없으므로, 실제 결과를 따로 적어 넣었습니다(승패·승률에는 들어가지 않음).")
      : null,
  ];

  body.setAttribute("aria-busy", "false");
  body.replaceChildren(
    el("div", { class: "table-scroll standings-scroll", tabindex: "0", role: "region", "aria-label": `${season} 순위표 (가로로 넘겨 보기)` }, el("table", { class: "table standings" }, [
      el("caption", { class: "sr-only" }, `${season} 정규시즌 순위표 (위 ${PLAYOFF_SPOTS}팀 가을야구)`),
      el("thead", {}, el("tr", {}, cols.map(([t, c]) => el("th", { scope: "col", class: c ?? null }, t)))),
      el("tbody", {}, bodyRows),
    ])),
    el("ul", { class: "notes" }, notes),
  );
}

// ---------- ② 로스터 유형 구성 ----------

function renderRoster(rows) {
  const body = $("roster-body");
  body.setAttribute("aria-busy", "false");
  if (!state.report) {
    showError(body, `${state.errors.report ?? ""} 유형 이름을 읽지 못해 로스터 구성을 그리지 않았습니다.`, async () => {
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
      label: `${season} 팀별 ${title} 유형 구성 (${g === "batter" ? "타석" : "이닝"} 비중, 순위 순서)`,
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
      }, fmtRate3(v));
    }),
  ]));
  const grid = el("div", { class: "inset h2h__frame" }, el("div", { class: "table-scroll h2h__scroll", tabindex: "0", role: "region", "aria-label": `${season} 상대 전적 표 (가로로 넘겨 보기)` },
    el("table", { class: "h2h" }, [
      el("caption", { class: "sr-only" }, `${season} 상대 전적: 행 팀이 열 상대에게 거둔 승률 (무승부 제외)`),
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
      el("p", {}, `${shortName(top.a, season)}, ${shortName(top.b, season)} 상대 승률`),
    ]) : null,
    first ? el("div", { class: "inset h2h__fact" }, [
      el("p", { class: "h2h__fact-label" }, `1위 ${shortName(first.code, season)}의 5할 아래 상대`),
      weak.length
        ? el("ul", { class: "h2h__weak" }, weak.map(([c, v]) => el("li", {}, [el("span", {}, shortName(c, season)), el("b", { class: "num" }, fmtRate3(v))])))
        : el("p", {}, "없음. 모든 상대에게 5할 이상을 거뒀습니다."),
    ]) : null,
    el("div", { class: "h2h__scale", "aria-hidden": "true" }, [
      el("span", { class: "h2h__ramp" }),
      el("span", { class: "h2h__ramp-labels" }, [el("span", {}, ".200 적게 이김"), el("span", {}, ".500"), el("span", {}, "많이 이김 .800")]),
    ]),
  ]);
  body.setAttribute("aria-busy", "false");
  body.replaceChildren(el("div", { class: "h2h-layout" }, [grid, aside]));
}

// ---------- ④ 가을야구 확률 되감기 (2026만) ----------

function renderRewind() {
  const section = $("playoff-rewind");
  section.hidden = state.season !== REWIND_SEASON;
  if (section.hidden) return;
  const rw = state.rewind;
  if (rw.phase === "idle") { loadRewind(); return; }
  if (rw.phase === "done") drawRewind();
  else if (rw.phase === "error") showRewindError();
}

/** 되감기 실패 상자 (다른 시즌을 보는 사이에 실패했어도 2026으로 돌아오면 이것을 보여 준다). */
function showRewindError() {
  const rw = state.rewind;
  const body = $("rewind-body");
  body.setAttribute("aria-busy", "false");
  const box = showError(body, rw.error ?? "", () => { rw.phase = "idle"; renderRewind(); });
  box.querySelector("strong").textContent = "되감기 확률을 불러오지 못했습니다. ";
}

/** 표본 날짜: 매 STRIDE번째 날 + 마지막 날. */
function sampleDates(dates) {
  const picked = dates.filter((_, i) => i % REWIND_STRIDE === 0);
  if (dates.length && picked.at(-1) !== dates.at(-1)) picked.push(dates.at(-1));
  return picked;
}

async function loadRewind() {
  const rw = state.rewind;
  const body = $("rewind-body");
  rw.phase = "loading";
  body.setAttribute("aria-busy", "true");
  const progress = el("p", { class: "rewind__progress", role: "status" }, "되감기 날짜를 불러오는 중…");
  body.replaceChildren(el("div", { class: "inset" }, el("div", { class: "skeleton skel-line" })), progress);
  try {
    rw.index = await fetchJSON(`rewind/${REWIND_SEASON}/index.json`, { fresh: true });
    const dates = sampleDates((rw.index.dates ?? []).map((d) => d.date).filter(Boolean));
    let done = 0;
    progress.textContent = `날짜 ${dates.length}개 중 0개 불러옴…`;
    const results = await Promise.allSettled(dates.map((d) => fetchJSON(`rewind/${REWIND_SEASON}/${d}.json`).finally(() => {
      done += 1;
      progress.textContent = `날짜 ${dates.length}개 중 ${done}개 불러옴…`;
    })));
    rw.days = dates.map((d, i) => ({ date: d, outlook: results[i].status === "fulfilled" ? results[i].value?.outlook ?? null : null }));
    rw.failed = rw.days.filter((d) => !d.outlook?.teams).length;
    if (rw.days.length - rw.failed < 2) throw new Error(`날짜 파일 ${dates.length}개 중 ${rw.failed}개를 받지 못했습니다.`);
    rw.phase = "done";
  } catch (err) {
    rw.phase = "error";
    rw.error = err.message;
  }
  body.setAttribute("aria-busy", "false");
  if (state.season !== REWIND_SEASON) return; // 받는 사이 시즌을 바꿨으면 다음에 2026을 고를 때 그린다
  if (rw.phase === "done") drawRewind();
  else showRewindError();
}

function drawRewind() {
  const rw = state.rewind;
  const body = $("rewind-body");
  const days = rw.days;
  const x = (d) => { const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(d.outlook?.as_of ?? d.date); return m ? `${+m[1]}/${+m[2]}` : d.date; };
  const lastDay = days.findLast((d) => d.outlook?.teams);
  const final = (code) => lastDay?.outlook?.teams?.[code]?.playoff_prob;
  const codes = Object.keys(TEAMS).filter((c) => days.some((d) => fin(d.outlook?.teams?.[c]?.playoff_prob)));
  // 색이 같은 두 팀(롯데·KIA, 키움·LG, SSG·NC)은 TEAMS 순서에서 뒤에 오는 팀을 점선으로
  const seen = new Set();
  const dashed = new Set(codes.filter((c) => { const col = TEAMS[c].color; const dup = seen.has(col); seen.add(col); return dup; }));
  const series = codes
    .sort((a, b) => (final(b) ?? -1) - (final(a) ?? -1) || a.localeCompare(b))
    .map((c) => ({
      name: shortName(c, REWIND_SEASON),
      short: shortName(c, REWIND_SEASON),
      legend: `${shortName(c, REWIND_SEASON)} ${fmtPct(final(c))}`,
      color: TEAMS[c].color,
      dash: dashed.has(c),
      points: days.map((d) => ({ x: x(d), y: d.outlook?.teams?.[c]?.playoff_prob ?? null })),
    }));
  const chart = el("div", { class: "rewind__chart" });
  const first = days.find((d) => d.outlook?.teams);
  body.replaceChildren(
    el("div", { class: "inset rewind__frame" }, chart),
    el("p", { class: "card__foot rewind__note" },
      `${fmtDate(first?.outlook?.as_of ?? first?.date)}부터 ${fmtDate(lastDay?.outlook?.as_of ?? lastDay?.date)}까지 약 일주일 간격 ${days.length - rw.failed}개 날짜. ` +
      "각 점은 그날 경기 전 성적으로 남은 경기를 1만 번 시뮬레이션해 5위 안에 든 비율입니다. 범례 숫자는 마지막 날짜의 확률이고, 색이 같은 두 팀은 한쪽을 점선으로 그렸습니다." +
      (rw.failed ? ` 날짜 ${rw.failed}개는 받지 못해 선을 끊었습니다.` : "")),
  );
  lineChart(chart, series, {
    yDomain: [0, 1], yFormat: (v) => fmtPct(v), height: 300, endLabels: true,
    label: `${REWIND_SEASON} 팀별 가을야구 진출 확률 추이`,
  });
}

init();
