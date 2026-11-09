// KBO Predict — 홈(오늘의 경기). index.html 전용 모듈.
//
// 화면 순서: 날짜 칩(라이브 / 2026 되감기 슬라이더) → 매치업 카드 → 벤토 6장 → 푸터 증거 바.
//   벤토 section id: #factors(크림) #accuracy(라벤더) #starters(피치) #outlook(오커) #type-map(틸) #recent(크림)
//
// 모드
//   - 라이브: status.json의 mode가 "live"이고 latest.json에 경기가 있으면 latest.json을 그린다.
//   - 되감기: mode가 "rewind"(비시즌)이거나 latest.json에 경기가 없거나 ?date=YYYY-MM-DD가 있으면
//     rewind/2026/{date}.json을 그린다. 날짜는 rewind/2026/index.json의 dates만 오간다(없는 날짜는 그 앞 경기일로).
//   - ?fixture=edge (로컬 미리보기에서만): latest.json 대신 tests/fixtures/site/latest_edge.json
//     (정상 1 · 선발 미정 1 · 취소 1)을 읽는다. ?fixture=offseason은 status_rewind.json(비시즌 status)을 읽는다.
//     배포본(로컬이 아닌 곳)에서는 이 플래그를 무시한다.
// 데이터 키는 docs/site/data-contract.md 매핑 표(페이지 "홈")에 적은 것만 쓴다.

import {
  IS_LOCAL, TEAMS, TYPE_COLORS, el, fetchJSON, fetchCSV, settle, fin, fmtPct, fmtRate3, fmtInnings, fmtDate, fmtKST,
  teamName, typeColor, verdictPill, winnerText, renderNav, renderFooter, showError, ballSVG, countUp,
  STADIUMS, teamColors, teamChip, teamText, favState, typeSummaryTable, fmtProb, fmtDateShort, fmtScore, teamLogo, factorKey, factorLabel, factorHelp, typeBlurb,
} from "./app.js";
import { barChart, scatter } from "./charts.js";
import { whatifProb } from "./whatif.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const FIXTURE = IS_LOCAL ? params.get("fixture") : null;     // "edge" | "offseason" | null
const FIXTURE_BASE = "../tests/fixtures/site";
const REWIND = "rewind/2026";

const state = {
  status: null, latest: null, index: null, history: null, report: null, players: null,
  whatif: null,            // whatif.json (오늘 경기의 선발 바꿔 보기 데이터)
  schedules: new Map(),    // 시즌 → seasons/schedule_{시즌}.json 읽기(Promise) — 순위표·다가오는 경기
  wiPick: null,            // 선발 바꿔 보기에서 고른 선발 {gameId, home, away} (player_id)
  nameKo: null,            // player_id → 한글 이름 (players.json을 읽은 뒤에 채운다)
  errors: {},              // 파일별 읽기 실패 메시지
  mode: "live",            // "live" | "rewind"
  day: null,               // 지금 그리는 하루 (latest.json 또는 rewind/2026/{date}.json)
  dateIdx: 0,              // 되감기 슬라이더 위치 (index.dates의 번호)
  selected: 0,             // 요인·선발 카드가 보여 주는 경기 (취소 아닌 경기 중 번호)
  dayCache: new Map(),
};

// ---------- 작은 도우미 ----------

const num = (v, d = 2) => (fin(v) ? Number(v).toFixed(d) : "—");
/**
 * 최근 경기 흐름. last10 = 최근 최대 10경기의 승 ÷ (승+패) (무승부 제외, 시즌 초에는 10경기 미만).
 * ×10이 정수일 때만 "최근 10경기 7승 3패"로 쓰고, 아니면 "최근 승률 .667" (경기 수를 지어내지 않는다).
 * 시즌 승률과 같으면 아직 10경기가 안 됐을 수 있으므로(예: 4경기 2승 = 0.5) 승률로만 쓴다.
 */
function recentForm(v, season) {
  if (!fin(v)) return "최근 10경기 —";
  const x = Number(v) * 10;
  const maybeShort = fin(season) && Math.abs(Number(season) - Number(v)) < 0.0005;
  if (!maybeShort && Math.abs(x - Math.round(x)) < 0.01) return `최근 10경기 ${Math.round(x)}승 ${10 - Math.round(x)}패`;
  return `최근 승률 ${fmtRate3(v)}`;
}
/** 확률 → "%". 0%·100%로 반올림되는 극단값은 "<1%"·">99%"로 (정확히 0·1이면 0%·100%). */
const prob = fmtProb; // 시뮬레이션 확률 표기는 app.js 하나로 (팀 페이지와 같은 "<1%" / ">99%")
const sign = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%p`;
const matchLabel = (g) => `${teamName(g.away.code)} vs ${teamName(g.home.code)}`;
/** 선발 이름: players.json을 읽었으면 한글 이름(player_id로 찾음), 그 전이나 없으면 데이터의 로마자 이름. */
const starterName = (s) => state.nameKo?.get(s.player_id) ?? s.name;

/** KST 오늘 날짜 "YYYY-MM-DD". */
const todayKST = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" }).format(new Date());

// 취소 사유는 원본이 영문이라 아는 것만 한글로 바꾼다(모르는 값은 그대로). 구장 이름은 app.js의 STADIUMS.
const NOTES = { "Rained Out": "우천 취소", "Extreme Heat": "폭염 취소", "Poor Field Conditions": "그라운드 사정으로 취소" };

function playable(day) {
  return (day?.games ?? []).filter((g) => g.status !== "CANCELED");
}
function ordered(day) {
  const games = day?.games ?? [];
  return [...games.filter((g) => g.status !== "CANCELED"), ...games.filter((g) => g.status === "CANCELED")];
}
function selectedGame() {
  const games = playable(state.day);
  return games[Math.min(state.selected, games.length - 1)] ?? null;
}

// ---------- 읽기 ----------

// 매일 바뀌는 파일(status·latest·history·되감기 목차)만 fresh로 읽는다 — 나머지는 브라우저 캐시 (app.js fetchOK 주석).
const loadIndex = () => settle(state, "index", fetchJSON(`${REWIND}/index.json`, { fresh: true }));
const loadHistory = () => settle(state, "history", fetchCSV("history.csv", { fresh: true }));
const loadReport = () => settle(state, "report", fetchJSON("model_report.json"));

function loadCore() {
  const latest = FIXTURE === "edge"
    ? fetchJSON("latest_edge.json", { base: FIXTURE_BASE, fresh: true }) : fetchJSON("latest.json", { fresh: true });
  const status = FIXTURE === "offseason"
    ? fetchJSON("status_rewind.json", { base: FIXTURE_BASE, fresh: true }) : fetchJSON("status.json", { fresh: true });
  return Promise.all([
    settle(state, "status", status), settle(state, "latest", latest), loadIndex(), loadHistory(), loadReport(),
    settle(state, "whatif", fetchJSON("whatif.json", { fresh: true })),
  ]);
}

async function loadDay(i) {
  const date = state.index.dates[i].date;
  if (!state.dayCache.has(date)) state.dayCache.set(date, fetchJSON(`${REWIND}/${date}.json`));
  try {
    return await state.dayCache.get(date);
  } catch (err) {
    state.dayCache.delete(date); // 다음 시도에서 다시 받는다
    throw err;
  }
}

const liveAvailable = () => state.status?.mode !== "rewind" && (state.latest?.games?.length ?? 0) > 0;

// ---------- 시작 ----------

async function init() {
  renderNav("index.html");
  $("matchups").setAttribute("aria-busy", "true");
  await loadCore();
  if (state.index && !state.index.dates?.length) { // 목차가 비었으면 되감기를 쓸 수 없다
    state.errors.index = "지난 경기 목록에 날짜가 없습니다.";
    state.index = null;
  }
  renderFooter(state.status);
  if (FIXTURE) {
    const note = $("fixture-note");
    note.hidden = false;
    note.textContent = FIXTURE === "edge"
      ? "검증용 화면: tests/fixtures/site/latest_edge.json(정상 · 선발 미정 · 취소 경기)을 그리고 있습니다. 실제 예측이 아닙니다."
      : "검증용 화면: 비시즌 status(status_rewind.json)를 쓰고 있습니다.";
  }
  renderAccuracy();
  renderRecent();

  if (!state.latest && !state.index) {
    showError($("matchups"), `${state.errors.latest ?? ""} ${state.errors.index ?? ""}`.trim(), init);
    $("matchups").setAttribute("aria-busy", "false");
    for (const id of ["factors-body", "starters-body", "outlook-body"]) {
      $(id).replaceChildren(el("p", { class: "empty" }, "경기 데이터를 불러오지 못해 비워 두었습니다."));
    }
    bindControls(); // 되감기 버튼은 목차 오류와 다시 불러오기를 보여 준다
    loadPlayersLater();
    return;
  }

  const want = params.get("date");
  if (want && state.index) {
    const i = dateIndexFor(want);
    if (state.index.dates[i].date !== want) state.snappedFrom = want; // 경기 없는 날 → 그 앞(없으면 첫) 경기일
    await openRewind(i);
  }
  // 비시즌 자동 되감기는 주소를 바꾸지 않는다(사용자가 고르거나 ?date=로 열었을 때만 ?date=를 쓴다)
  else if (!liveAvailable() && state.index) await openRewind(state.index.dates.length - 1, { writeURL: false });
  else showLive();
  bindControls();
  loadPlayersLater();
}

/** ?date= 값 → index.dates 번호. 없는 날짜면 그 앞의 가장 가까운 경기일(처음보다 앞이면 첫날). */
function dateIndexFor(iso) {
  const dates = state.index.dates;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return dates.length - 1;
  let best = 0;
  dates.forEach((d, i) => { if (d.date <= iso) best = i; });
  return best;
}

function setURL(date) {
  const p = new URLSearchParams(location.search);
  if (date) p.set("date", date); else p.delete("date");
  const q = p.toString();
  history.replaceState(null, "", `${location.pathname}${q ? `?${q}` : ""}`);
}

function showLive() {
  if (!state.latest) {
    showError($("matchups"), state.errors.latest, init);
    return;
  }
  state.mode = "live";
  state.day = state.latest;
  state.selected = 0;
  setURL(null);
  renderDay();
}

let loadToken = 0;
/** 되감기 날짜 열기. mode·dateIdx는 그날 파일을 받은 뒤에만 바꾼다(실패하면 직전 화면의 날짜 막대를 그대로 둔다). */
async function openRewind(i, { writeURL = true } = {}) {
  if (!state.index) {
    $("rewind-error").hidden = false;
    showError($("rewind-error"), state.errors.index ?? "지난 경기 목록을 불러오지 못했습니다.", retryIndex);
    return;
  }
  const idx = Math.max(0, Math.min(i, state.index.dates.length - 1));
  syncRewindBar(idx);
  const token = ++loadToken;
  $("matchups").setAttribute("aria-busy", "true");
  try {
    const day = await loadDay(idx);
    if (token !== loadToken) return; // 그사이 다른 날짜를 골랐다
    state.mode = "rewind";
    state.rewindVisited = true;
    state.dateIdx = idx;
    state.day = day;
    state.selected = 0;
    if (writeURL) setURL(day.date);
    renderDay();
  } catch (err) {
    if (token !== loadToken) return;
    if (!state.day) { state.mode = "rewind"; state.dateIdx = idx; } // 처음 연 날짜부터 실패: 슬라이더는 그 날짜로
    $("matchups").setAttribute("aria-busy", "false");
    renderDateBar();
    showError($("matchups"), err.message, () => openRewind(idx));
    for (const id of ["factors-body", "starters-body", "outlook-body"]) {
      $(id).replaceChildren(el("p", { class: "empty" }, "이 날짜의 경기 데이터를 불러오지 못했습니다. 위에서 다시 불러오기를 눌러 주세요."));
    }
    $("factor-tabs").hidden = true;
  }
}

/** 되감기 목차를 다시 받아 보고, 되면 마지막 날짜를 연다. */
async function retryIndex() {
  await loadIndex();
  if (state.index && !state.index.dates?.length) {
    state.errors.index = "지난 경기 목록에 날짜가 없습니다.";
    state.index = null;
  }
  if (!state.index) {
    showError($("rewind-error"), state.errors.index, retryIndex);
    return;
  }
  $("rewind-error").hidden = true;
  $("rewind-error").replaceChildren();
  renderAccuracy(); // 월별 막대
  await openRewind(state.index.dates.length - 1);
}

// ---------- 날짜 칩·되감기 슬라이더 ----------

function bindControls() {
  if (bindControls.done) return;
  bindControls.done = true;
  const range = $("rewind-range");
  let timer = 0;
  range.addEventListener("input", () => {
    const i = Number(range.value);
    syncRewindBar(i);
    clearTimeout(timer);
    timer = setTimeout(() => openRewind(i), 180); // 끌고 있는 동안은 글자만 바꾸고 멈추면 읽는다
  });
  range.addEventListener("change", () => { clearTimeout(timer); openRewind(Number(range.value)); });
  $("rewind-prev").addEventListener("click", () => openRewind(state.dateIdx - 1));
  $("rewind-next").addEventListener("click", () => openRewind(state.dateIdx + 1));
  $("rewind-toggle").addEventListener("click", async () => {
    if (!state.index) return openRewind(0); // 목차가 없으면 그 이유와 다시 불러오기를 보여 준다
    await openRewind(state.rewindVisited ? state.dateIdx : state.index.dates.length - 1);
    if (state.mode === "rewind") $("rewind-range").focus();
  });
  $("to-live").addEventListener("click", () => { showLive(); $("rewind-toggle").focus(); });
}

/** 슬라이더·날짜 글자·전/후 버튼을 idx(기본: 지금 보이는 날짜)에 맞춘다. */
function syncRewindBar(idx = state.dateIdx) {
  const dates = state.index?.dates ?? [];
  const range = $("rewind-range");
  range.max = String(Math.max(0, dates.length - 1));
  range.value = String(idx);
  const d = dates[idx];
  const label = d ? fmtDate(d.date) : "—";
  $("rewind-date").textContent = label;
  range.setAttribute("aria-valuetext", label);
  $("rewind-prev").disabled = idx <= 0;
  $("rewind-next").disabled = idx >= dates.length - 1;
}

function renderDateBar() {
  const rewind = state.mode === "rewind";
  $("live-chip").hidden = rewind;
  $("rewind-bar").hidden = !rewind;
  $("rewind-toggle").setAttribute("aria-expanded", String(rewind));
  $("to-live").hidden = !liveAvailable();
  const hint = $("rewind-hint");
  if (rewind && !liveAvailable()) {
    const next = state.status?.next_game_date;
    const r = state.status?.season_result; // 한국시리즈가 끝났으면 우승 팀과 전적
    const won = r ? r.wins[r.teams.indexOf(r.champion)] : null;
    hint.textContent = next && next >= todayKST()
      ? `지금은 오늘 예측이 없습니다. 다음 경기는 ${fmtDate(next)}입니다.`
      : r ? `${endedSeason() ?? ""} 시즌이 끝났습니다(${r.name} 우승 ${teamName(r.champion)}). 정규시즌 경기일을 골라 그날의 예측과 결과를 다시 볼 수 있습니다.`.trim()
        : "지금은 비시즌이라 오늘 예측이 없습니다. 2026 시즌 경기일을 골라 보세요.";
  } else {
    hint.textContent = "2026 시즌 경기일만 이동합니다. 화살표 키로도 움직일 수 있습니다.";
  }
  if (!rewind && state.day) {
    const fresh = state.day.date === todayKST();
    const pill = $("live-pill");
    pill.className = fresh ? "pill pill--ink" : "pill pill--muted";
    pill.replaceChildren(...(fresh ? [el("span", { class: "dot live-dot", "aria-hidden": "true" }), "라이브"] : ["가장 최근 예측"]));
  } else if (rewind) {
    syncRewindBar();
  }
}

function renderHead() {
  const day = state.day;
  const games = day.games ?? [];
  if (state.mode === "live") {
    const series = day.outlook?.type === "series" ? ` ${day.outlook.name}` : "";
    $("day-title").textContent = `${fmtDate(day.date)}${series}`;
    const canceled = games.filter((g) => g.status === "CANCELED").length;
    $("day-lead").replaceChildren(`${fmtKST(day.generated_at)} 예측`, canceled ? `, 취소 ${canceled}경기` : "");
  } else {
    const d = state.index.dates[state.dateIdx];
    const snapped = state.snappedFrom && /^\d{4}-\d{2}-\d{2}$/.test(state.snappedFrom)
      ? `${fmtDate(state.snappedFrom)}에는 경기가 없어 가장 가까운 경기일을 보여 줍니다. ` : "";
    state.snappedFrom = null; // 처음 한 번만 알린다
    $("day-title").textContent = `${fmtDate(day.date)} 다시 보기`;
    $("day-lead").textContent = snapped + (d && d.decided
      ? `이날 ${d.decided}경기 중 ${d.correct}경기를 적중했습니다. 2026 시즌 전체 적중률은 ${fmtPct(state.index.accuracy, 1)}입니다.`
      : "이날은 적중을 따질 경기가 없습니다.");
  }
  renderBug();
}

/** 시리즈 두 팀을 그릴 순서(o.teams 인덱스). 오늘 경기에 두 팀이 있으면 [원정, 홈] — 매치업 슬랩과 색의 좌우를 맞춘다. */
function seriesOrder(o) {
  const g = (state.day?.games ?? []).find((x) => o.teams?.includes(x.home.code) && o.teams?.includes(x.away.code));
  return g ? [o.teams.indexOf(g.away.code), o.teams.indexOf(g.home.code)] : [0, 1];
}

/** 맨 위 검정 띠(스코어 버그)에 진행 중인 시리즈 전적. 라이브 시리즈가 아니면 비운다. */
function renderBug() {
  const slot = $("bug-slot");
  if (!slot) return;
  const o = state.day?.outlook;
  const champ = state.status?.season_result?.champion;
  if (state.mode !== "live" && champ) { // 시즌이 끝났으면 맨 위 띠에 우승 팀
    const tc = teamColors(champ);
    const yr = endedSeason() ?? "";
    slot.replaceChildren(el("span", { class: "bug__lbl" }, `${yr} 우승`.trim()),
      el("span", { class: "bug__team", style: { background: tc.bg, color: tc.fg }, "aria-label": `${yr} 우승 ${teamName(champ)}`.trim() },
        [teamLogo(champ, { size: "sm" }), teamName(champ), el("b", {}, "우승")]));
    return;
  }
  if (state.mode !== "live" || o?.type !== "series") { slot.replaceChildren(); return; }
  slot.replaceChildren(el("span", { class: "bug__lbl" }, o.name), ...seriesOrder(o).map((i) => {
    const c = o.teams[i];
    const tc = teamColors(c);
    return el("span", { class: "bug__team", style: { background: tc.bg, color: tc.fg }, "aria-label": `${teamName(c)} ${o.wins[i]}승` },
      [teamLogo(c, { size: "sm" }), teamName(c), el("b", {}, String(o.wins[i]))]);
  }));
}

// ---------- 시즌 종료 카드 (이번 시즌 페이지, 비시즌) ----------
// 한국시리즈 승부가 나면(status.season_result) 맨 위에 짧게 알리고, 자세한 결과는 지난 시즌 페이지로 보낸다.

/** 끝난 시즌(우승 팀이 정해진 시즌)의 연도 — 마지막으로 예측을 낸 날(latest.json)의 연도. */
const endedSeason = () => Number(String(state.latest?.date ?? "").slice(0, 4)) || null;

function renderSeason() {
  const box = $("season");
  const r = state.status?.season_result;
  const yr = endedSeason();
  if (!r || !yr) { box.hidden = true; return; }
  box.hidden = false;
  const champ = r.champion, loser = r.teams.find((t) => t !== champ);
  const cw = r.wins[r.teams.indexOf(champ)], cl = r.wins[r.teams.indexOf(loser)];
  const tc = teamColors(champ);
  $("season-body").replaceChildren(el("div", { class: "season-end" }, [
    el("div", { class: "season-end__champ", style: { background: tc.bg, color: tc.fg } }, [
      teamLogo(champ, { size: "md" }),
      el("div", {}, [el("p", { class: "season-end__k" }, `${yr} ${r.name} 우승`), el("p", { class: "season-end__t" }, teamName(champ)),
        el("p", { class: "season-end__s" }, `${teamName(loser)}에 ${cw}승 ${cl}패`)]),
    ]),
    el("div", { class: "season-end__text" }, [
      el("p", { class: "season-end__h" }, `${yr} 시즌이 끝났습니다`),
      el("p", {}, `${yr + 1} 시즌 일정이 나오면 이 페이지에서 매일 경기 예측과 일정, 순위표를 보여 줍니다. 그전까지는 지난 시즌에서 ${yr} 한국시리즈와 가을야구, 최종 순위를 다시 볼 수 있습니다.`),
      el("a", { class: "btn", href: `seasons.html?season=${yr}` }, `지난 시즌에서 ${yr} 다시 보기`),
    ]),
  ]));
}

// ---------- 순위표 · 다가오는 경기 (이번 시즌) ----------
// seasons/schedule_{시즌}.json(그 시즌 모든 경기)으로 보고 있는 날짜 기준 순위와 앞으로 7일 일정을 계산한다.

function standingsAt(schedule, on) {
  const rec = new Map();
  for (const g of schedule) {
    if (!g.regular || g.status !== "FINAL" || g.date >= on || g.home_score == null) continue;
    for (const [t, me, op] of [[g.home, g.home_score, g.away_score], [g.away, g.away_score, g.home_score]]) {
      const r = rec.get(t) ?? { code: t, w: 0, l: 0, d: 0, last: [] };
      const x = me > op ? "W" : me < op ? "L" : "D";
      r[x === "W" ? "w" : x === "L" ? "l" : "d"] += 1;
      r.last.push(x);
      rec.set(t, r);
    }
  }
  const pct = (r) => r.w / Math.max(r.w + r.l, 1);
  const rows = [...rec.values()].sort((a, b) => pct(b) - pct(a) || b.w - a.w || a.code.localeCompare(b.code));
  const top = rows[0];
  return rows.map((r, i) => ({ ...r, rank: i + 1, pct: pct(r), gb: top ? ((top.w - r.w) + (r.l - top.l)) / 2 : 0,
    l10: r.last.slice(-10).filter((x) => x === "W").length }));
}

/** 보고 있는 날짜의 시즌 일정(그 시즌 모든 경기). 처음이면 받아 오고, 다 받으면 순위표·다가오는 경기를 다시 그린다. */
function scheduleFor(on) {
  const season = Number(String(on ?? "").slice(0, 4));
  if (!season) return { status: "none" };
  if (!state.schedules.has(season)) {
    const p = fetchJSON(`seasons/schedule_${season}.json`, { fresh: true })
      .then((data) => { entry.data = data; entry.status = "ok"; })
      .catch((err) => { entry.status = "error"; entry.error = err.message; })
      .finally(() => { if (state.day?.date?.startsWith(String(season))) { renderStandings(); renderSchedule(); } });
    const entry = { status: "loading", promise: p };
    state.schedules.set(season, entry);
  }
  return state.schedules.get(season);
}

function renderStandings() {
  const body = $("standings-body");
  const on = state.day?.date;
  const sc = scheduleFor(on);
  if (sc.status === "loading") return; // 받는 중: 뼈대 그대로, 다 받으면 다시 그린다
  const sched = sc.data;
  if (!sched || !on) { body.replaceChildren(el("p", { class: "empty" }, "순위표를 불러오지 못했습니다.")); return; }
  const rows = standingsAt(sched, on);
  const today = new Set((state.day.games ?? []).flatMap((g) => [g.home.code, g.away.code]));
  $("standings-lead").textContent = `${fmtDate(on)} 경기 전 기준 정규시즌 순위입니다. 5위까지 가을야구에 나갑니다.`;
  body.replaceChildren(el("div", { class: "table-scroll" }, el("table", { class: "table stand" }, [
    el("caption", { class: "sr-only" }, "정규시즌 순위"),
    el("thead", {}, el("tr", {}, [["순위"], ["팀"], ["승-패-무", "num"], ["승률", "num"], ["게임차", "num"], ["최근 10", "num"]].map(([t, c]) => el("th", { scope: "col", class: c ?? null }, t)))),
    el("tbody", {}, rows.map((r) => el("tr", { class: `${r.rank === 5 ? "is-cut " : ""}${today.has(r.code) ? "is-today" : ""}`.trim() || null }, [
      el("td", { class: "num" }, String(r.rank)),
      el("td", {}, el("span", { class: "stand__team" }, [teamLogo(r.code, { size: "sm" }), teamName(r.code)])),
      el("td", { class: "num" }, `${r.w}-${r.l}-${r.d}`),
      el("td", { class: "num" }, r.pct.toFixed(3).replace(/^0/, "")),
      el("td", { class: "num" }, r.gb ? r.gb.toFixed(1) : "—"),
      el("td", { class: "num" }, `${r.l10}승`),
    ]))),
  ])), el("p", { class: "card__foot" }, "굵은 선 위 = 가을야구 진출권(5위 안), 표시된 팀 = 오늘 경기가 있는 팀."));
}

function renderSchedule() {
  const body = $("schedule-body");
  const on = state.day?.date;
  const sc = scheduleFor(on);
  if (sc.status === "loading") return;
  const sched = sc.data;
  if (!sched || !on) { body.replaceChildren(el("p", { class: "empty" }, "일정을 불러오지 못했습니다.")); return; }
  const end = new Date(`${on}T00:00:00+09:00`); end.setDate(end.getDate() + 7);
  const lim = end.toISOString().slice(0, 10);
  const up = sched.filter((g) => g.date > on && g.date <= lim && g.status !== "CANCELED");
  if (!up.length) { body.replaceChildren(el("p", { class: "empty" }, "앞으로 7일 안에 잡힌 경기가 없습니다.")); return; }
  const days = [...new Set(up.map((g) => g.date))];
  body.replaceChildren(el("ol", { class: "sched" }, days.map((d) => el("li", { class: "sched__day" }, [
    el("p", { class: "sched__date" }, fmtDate(d)),
    el("ul", { class: "sched__games" }, up.filter((g) => g.date === d).map((g) => el("li", {}, [
      el("span", { class: "sched__time num" }, g.time ?? ""),
      el("span", { class: "sched__match" }, [teamLogo(g.away, { size: "sm" }), teamName(g.away), el("span", { class: "sched__at" }, "@"), teamLogo(g.home, { size: "sm" }), teamName(g.home)]),
      el("span", { class: "sched__where" }, STADIUMS[g.stadium] ?? g.stadium ?? ""),
    ]))),
  ]))), el("p", { class: "card__foot" }, "예측은 경기 당일 아침부터 올라오고, 예고 선발이 발표되면 다시 계산합니다."));
}

// ---------- 매치업 카드 ----------

const NO_TYPE_TIP = "작년에 50이닝 이상이나 구원 30경기 이상 던진 투수만 유형을 붙입니다.";
function typePill(type, onCard) {
  if (!type) return el("span", { class: `pill pill--sm ${onCard ? "pill--white" : "pill--muted"}`, title: NO_TYPE_TIP }, onCard ? "유형 없음" : "작년 기록 부족");
  const tok = typeColor("pitcher", type.id);
  return el("span", { class: `pill pill--sm ${onCard ? "pill--white" : `pill--${tok}`}` }, [
    onCard ? el("span", { class: "dot", style: { background: `var(--${tok})` }, "aria-hidden": "true" }) : null, type.name,
  ]);
}

/**
 * 한쪽 진영(원정 = 왼쪽 핑크, 홈 = 오른쪽 틸). 이름은 크게(한 줄 정식 이름은 그 아래 작게), 숫자는 가장 크게.
 * 선발·기록은 전부 하나의 크림 칩(하단 자막)에 담는다 — 핑크·틸 위 작은 글자의 대비 문제를 없애고 두 진영을 같은 모양으로.
 */
/** 팀 면의 [바탕색, 글자색] (app.js teamColors — 글자색은 흰색과 잉크 중 대비가 높은 쪽). */
function teamSideColors(code) {
  const c = teamColors(code);
  return [c.bg, c.fg];
}

function sideBlock(g, side, prob, large, animate = false) {
  const t = g[side];
  const s = t.starter;
  const role = side === "home" ? "홈" : "원정";
  const head = el("div", { class: "side__head" }, [
    el("p", { class: "side__role" }, role),
    el("h3", { class: "side__team" }, [teamLogo(t.code, { size: large ? "lg" : "md" }), el("span", {}, teamName(t.code))]),
    large ? el("p", { class: "side__full" }, teamName(t.code, { full: true })) : null,
  ]);
  const n = el("span", { class: "side__n" }, String(prob));
  if (animate && prob !== "—") countUp(n, prob, { from: 50, dur: 1100 });
  const probEl = el("p", { class: "side__prob" }, [
    el("span", { class: "side__num" }, prob === "—" ? "—" : [n, el("small", {}, "%")]),
    // 우세 쪽 이름표는 모델의 한 마디("KT 근소 우세"), 열세 쪽은 "삼성 승리" — 같은 판정(favState)만 쓴다
    el("span", { class: "side__who" }, favState(g.home_win_prob) === side ? lean(g) : `${teamName(t.code)} 승리`),
  ]);
  const stats = !s ? null
    : fin(s.era) || fin(s.k9) || fin(s.bb9) ? `올해 평균자책점 ${num(s.era)}, 9이닝당 삼진 ${num(s.k9)}, 볼넷 ${num(s.bb9)}` : "선발이 올해 아직 등판하지 않았습니다";
  const chip = el("div", { class: "side__chip" }, [
    s ? el("p", { class: "chip__row" }, [el("span", {}, ["선발 ", el("b", {}, starterName(s))]), typePill(s.type, false)])
      : el("p", { class: "chip__row" }, el("b", {}, "선발 미정")),
    null, // 기록 숫자는 "오늘 선발, 어떤 유형?" 카드 한 곳에만 (같은 숫자 두 번 → 글이 많아 보임)
  ]);
  // 확률이 더 높은 쪽은 is-fav(우세), 낮은 쪽은 is-under(속이 빈 숫자). 반올림해 50 대 50이면 둘 다 표시 없음
  const fav = favState(g.home_win_prob);
  const favCls = !fav || fav === "tie" ? "" : fav === side ? " is-fav" : " is-under";
  return el("div", { class: `side side--${side}${favCls}` }, [head, probEl, el("div", { class: "side__details" }, chip)]);
}

/** 모델이 어느 쪽으로 얼마나 기우는지 한 마디. 확률이 없으면 null, 반올림해 50 대 50이면 "사실상 반반" (favState와 같은 기준). */
function lean(g) {
  const fav = favState(g.home_win_prob);
  if (!fav) return null;
  if (fav === "tie") return "사실상 반반";
  const a = Math.abs(Number(g.home_win_prob) - 0.5);
  return `${teamName(g[fav].code)} ${a < 0.1 ? "근소 우세" : a < 0.2 ? "우세" : "크게 우세"}`;
}

/** 승률을 가장 크게 움직인 요인 한 줄 + 선발 요인 미사용 알림 (하단 자막 띠). */
function ticker(g) {
  const f = (g.factors ?? []).filter((x) => fin(x.contribution_pp))
    .reduce((best, x) => (!best || Math.abs(x.contribution_pp) > Math.abs(best.contribution_pp) ? x : best), null);
  const parts = [];
  if (f) {
    const v = Number(f.contribution_pp);
    const toward = v > 0 ? g.home.code : v < 0 ? g.away.code : null; // + = 홈 승률을 올림, − = 원정 쪽으로 민 것
    parts.push(el("span", { class: "ticker__item" }, [
      el("span", { class: "ticker__tag" }, "가장 크게 움직인 요인"),
      el("b", { title: factorHelp(f.name) || null }, factorLabel(f.name)),
      toward ? teamChip(toward, `${teamName(toward)} +${Math.abs(v).toFixed(1)}%p`, "tchip--sm num") : el("span", { class: "num" }, sign(v)),
    ]));
  }
  if (g.starter_known === false) {
    parts.push(el("span", { class: "ticker__item ticker__note" }, "선발 기록이 없어 선발 요인을 빼고 예측했습니다"));
  }
  return parts.length ? el("div", { class: "stage__ticker" }, parts) : null;
}

/** 상단 띠: 왼쪽 = 어디서·무슨 경기·모델의 한 마디, 오른쪽 = (되감기) 결과. */
function metaPills(g, large) {
  const left = [];
  const where = [STADIUMS[g.stadium] ?? g.stadium, g.time].filter(Boolean).join(" ");
  if (where) left.push(el("span", { class: "pill pill--white" }, where));
  // H12: 선발 정보 없이 낸 예측은 작은 띠에서도 바로 보이게 (확률을 정상 예측과 같은 무게로 읽지 않도록)
  if (g.starter_known === false) left.push(el("span", { class: "pill pill--ink pill--nostarter" }, "선발 미반영"));
  // 우세 쪽은 그 면의 이름표가 "KT 근소 우세"를 말하므로 상단 칩은 반반일 때만 (우세 칩이 상대 팀 면 위에 놓이지 않게)
  if (large && favState(g.home_win_prob) === "tie") left.push(el("span", { class: "pill pill--white pill--lean" }, "사실상 반반"));
  const right = [];
  const r = g.result;
  if (r) {
    right.push(el("span", { class: "pill pill--white num" }, fmtScore(r.away_score, r.home_score)));
    right.push(verdictPill(r));
  }
  return [left.length ? el("div", { class: "pills" }, left) : null, right.length ? el("div", { class: "pills" }, right) : null];
}

function matchupCard(g, large, settled = false) {
  if (g.status === "CANCELED") {
    // 빗금 = 경기 없음. 양 끝 팀 색 띠로 어느 경기인지, 도장 하나로 이유만 (같은 말 두 번·설명 문장은 뺀다)
    const ca = teamColors(g.away.code).bg, chm = teamColors(g.home.code).bg;
    return el("article", {
      class: `matchup matchup--canceled card${large ? " matchup--lg" : ""}`, "aria-label": `${matchLabel(g)} 취소`,
      style: `--c-away: ${ca}; --c-home: ${chm}`,
    }, [
      el("h3", { class: "matchup__canceled-title" }, [teamText(g.away.code, teamName(g.away.code)), el("span", { class: "vs" }, " vs "), teamText(g.home.code, teamName(g.home.code))]),
      el("span", { class: "pill pill--ink" }, g.status_note ? (NOTES[g.status_note] ?? g.status_note) : "취소"),
    ]);
  }
  const p = g.home_win_prob;
  const home = fin(p) ? Math.round(p * 100) : "—";
  const away = fin(p) ? 100 - home : "—";
  const pctText = (v) => (v === "—" ? "—" : `${v}%`);
  const label = `${matchLabel(g)}: ${teamName(g.home.code)} 홈 승리 확률 ${pctText(home)}, ${teamName(g.away.code)} ${pctText(away)}`;
  // 핑크|틸 경계가 원정 승률 위치로 움직인다(너무 치우치면 글자 자리가 모자라 38~62%로 제한 — 숫자는 실제 값 그대로).
  // 작은 경기 띠는 경계를 가운데에 둔다(좁은 화면에서 이름 자리가 모자라서).
  const share = fin(p) ? (1 - Number(p)) * 100 : 50;
  const cut = large ? Math.min(62, Math.max(38, share)) : 50;
  const meta = metaPills(g, large);
  const [cAway, tAway] = teamSideColors(g.away.code);
  const [cHome, tHome] = teamSideColors(g.home.code);
  return el("article", {
    class: `matchup ${large ? "matchup--lg" : "matchup--sm"}${settled ? " is-settled" : ""}`,
    style: `--cut-to: ${cut.toFixed(1)}%; --c-away: ${cAway}; --t-away: ${tAway}; --c-home: ${cHome}; --t-home: ${tHome}`, "aria-label": label,
  }, [
    meta.some(Boolean) ? el("div", { class: "stage__top" }, meta) : null,
    sideBlock(g, "away", away, large, large && !settled),
    sideBlock(g, "home", home, large, large && !settled),
    large ? el("span", { class: "stage__vs", "aria-hidden": "true" }, [ballSVG({ spin: true }), el("b", {}, "VS")]) : null,
    // 좁은 화면에서는 경계가 사라지므로 같은 비율의 가로 막대로 긴장감을 대신한다
    el("div", { class: "stage__meter", "aria-hidden": "true" }, [
      el("span", { class: "meter__away", style: { flexGrow: String(fin(p) ? share : 50) } }),
      el("span", { class: "meter__home", style: { flexGrow: String(fin(p) ? 100 - share : 50) } }),
    ]),
    large ? ticker(g) : null,
  ]);
}

/** 두 팀 비교(중계의 "테일 오브 더 테이프"): 가운데 항목, 양쪽 값 + 팀 색 막대. 더 나은 쪽은 굵게. */
function tape(g) {
  const last10 = (v, season) => recentForm(v, season).replace("최근 10경기 ", "").replace("최근 승률 ", "");
  const signed = (v) => (fin(v) ? `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}` : "—");
  const rows = [
    ["시즌 승률", g.away.win_pct_season, g.home.win_pct_season, (v) => fmtRate3(v)],
    ["최근 10경기", g.away.last10, g.home.last10, (v, side) => last10(v, g[side].win_pct_season)],
    ["경기당 득실차", g.away.run_diff, g.home.run_diff, signed],
  ];
  const [cA] = teamSideColors(g.away.code);
  const [cH] = teamSideColors(g.home.code);
  const ink = { away: teamColors(g.away.code).ink, home: teamColors(g.home.code).ink };
  return el("div", { class: "tape", role: "table", "aria-label": `${matchLabel(g)} 두 팀 비교` }, rows.map(([k, a, h, fmt], i) => {
    const lo = k === "경기당 득실차" ? Math.min(0, Number(a) || 0, Number(h) || 0) - 0.5 : 0;
    const hi = Math.max(Number(a) || 0, Number(h) || 0);
    const share = (v) => (fin(v) ? Math.max(0.06, (Number(v) - lo) / (hi - lo || 1)) : 0);
    const win = fin(a) && fin(h) && Number(a) !== Number(h) ? (Number(a) > Number(h) ? "away" : "home") : null;
    const side = (who, v, c) => el("div", { class: `tape__v tape__v--${who}${win === who ? " is-win" : ""}`, role: "cell" }, [
      el("span", { class: "tape__n", style: win === who ? { color: ink[who] } : null }, fmt(v, who)), // 더 나은 값 = 그 팀 글자색
      el("span", { class: "tape__bar" }, el("i", { style: { width: `${(share(v) * 100).toFixed(1)}%`, background: c, "--i": String(i) } })),
    ]);
    return el("div", { class: "tape__row", role: "row" }, [side("away", a, cA), el("div", { class: "tape__k", role: "rowheader" }, k), side("home", h, cH)]);
  }));
}

function renderMatchups() {
  const box = $("matchups");
  const games = ordered(state.day);
  box.setAttribute("aria-busy", "false");
  if (!games.length) {
    box.replaceChildren(el("div", { class: "card" }, [
      el("p", { class: "card__title" }, "이날은 경기가 없습니다."),
      el("p", { class: "card__lead" }, "위에서 2026 시즌의 다른 날짜를 골라 보세요."),
    ]));
    return;
  }
  const [first, ...rest] = games;
  // 같은 날을 다시 그릴 때(players.json 뒤 선발 이름 갱신 등)는 경계가 다시 움직이지 않게 한다
  const key = `${state.mode}:${state.day.date}`;
  const settled = state.stageKey === key;
  state.stageKey = key;
  const cards = [matchupCard(first, true, settled)];
  if (first.status !== "CANCELED") cards.push(tape(first));
  if (rest.length) cards.push(el("div", { class: "matchups__rest" }, rest.map((g) => matchupCard(g, false, settled))));
  box.replaceChildren(...cards); // replaceChildren은 null을 "null" 글자로 넣으므로 배열로 모은다
}

// ---------- ① 승률을 가른 요인 ----------

const FACTORS_LEAD = "홈팀 승리 확률을 올린 요인(+)과 내린 요인(−)입니다. 단위는 %p(퍼센트포인트)입니다.";

function renderTabs() {
  const games = playable(state.day);
  const tabs = $("factor-tabs");
  const body = $("factors-body");
  tabs.hidden = games.length < 2;
  if (games.length < 2) { // 탭이 없으면 tabpanel도 아니다
    tabs.replaceChildren();
    delete tabs.dataset.key;
    body.removeAttribute("role");
    body.removeAttribute("aria-labelledby");
    return;
  }
  body.setAttribute("role", "tabpanel");
  body.setAttribute("aria-labelledby", `tab-${state.selected}`);
  const key = `${state.mode}:${state.day.date}:${games.length}`;
  if (tabs.dataset.key === key) { // 같은 날의 탭이면 속성만 바꾼다(누른 버튼의 포커스를 지킨다)
    [...tabs.children].forEach((b, i) => {
      const on = i === state.selected;
      b.classList.toggle("pill--ink", on);
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
    });
    return;
  }
  tabs.dataset.key = key;
  const buttons = games.map((g, i) => el("button", {
    class: `pill tab${i === state.selected ? " pill--ink" : ""}`, type: "button", role: "tab", id: `tab-${i}`,
    "aria-selected": String(i === state.selected), "aria-controls": "factors-body", tabindex: i === state.selected ? 0 : -1,
    onclick: () => selectGame(i),
    onkeydown: (e) => {
      const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      e.preventDefault();
      selectGame((i + step + games.length) % games.length);
      $(`tab-${state.selected}`)?.focus();
    },
  }, matchLabel(g)));
  tabs.replaceChildren(...buttons);
}

function selectGame(i) {
  state.selected = i;
  renderTabs();
  renderFactors();
  renderStarters();
  renderWhatif();
  renderOutlook();
}

function renderFactors() {
  const body = $("factors-body");
  const foot = $("factors-foot");
  const g = selectedGame();
  if (!g) {
    $("factors-lead").textContent = FACTORS_LEAD;
    body.replaceChildren(el("p", { class: "empty" }, "이날은 모두 취소돼 요인이 없습니다."));
    foot.textContent = "";
    return;
  }
  $("factors-lead").textContent = "반반(50%)에서 출발해 각 요인이 홈팀 승리 확률을 몇 %p 밀었는지 보여 줍니다. 막대를 가리키거나 누르면 요인 풀이가 나옵니다.";
  const rows = (g.factors ?? []).map((f) => ({ key: factorKey(f.name), label: factorLabel(f.name), help: factorHelp(f.name), value: f.contribution_pp }));
  if (!rows.length) {
    body.replaceChildren(el("p", { class: "empty" }, "이 경기는 요인 정보가 없습니다."));
    foot.textContent = "";
    return;
  }
  barChart(body, rows, {
    color: TEAMS[g.home.code]?.color ?? "teal", negativeColor: TEAMS[g.away.code]?.color ?? "pink", format: sign,
    label: `${matchLabel(g)} 승률을 가른 요인 (%p)`,
    sides: { neg: { text: `← ${teamName(g.away.code)}`, ink: teamColors(g.away.code).ink }, pos: { text: `${teamName(g.home.code)} →`, ink: teamColors(g.home.code).ink } },
  });
  const hasBias = rows.some((r) => r.key === "bias");
  // 요인 값은 1차 근사(predict.py)라 더해도 최종 확률과 조금 다를 수 있다
  foot.textContent = `${hasBias ? "" : `${factorLabel("bias")}은 이 경기에서 상위 5개 요인에 들지 않았습니다. `}요인 값은 근사치라 더해도 최종 확률과 조금 다를 수 있습니다.`;
}

// ---------- ② 모델은 얼마나 맞나 ----------

function monthBars(index) {
  const months = new Map();
  for (const d of index?.dates ?? []) {
    const m = Number(d.date.slice(5, 7));
    const cur = months.get(m) ?? { decided: 0, correct: 0 };
    cur.decided += d.decided; cur.correct += d.correct;
    months.set(m, cur);
  }
  const rows = [...months].filter(([, v]) => v.decided > 0).map(([m, v]) => ({ m, acc: v.correct / v.decided, n: v.decided }));
  if (!rows.length) return null;
  const lo = 0, hi = 1; // 막대 높이 = 적중률 그대로(0~100%, 축을 자르지 않는다)
  return el("figure", { class: "months" }, [
    el("ol", { class: "months__bars", "aria-hidden": "true" }, rows.map((r) => el("li", {}, [
      el("span", { class: "months__track" }, [
        el("span", { class: "months__val num" }, fmtPct(r.acc)),
        el("span", { class: "months__bar",
          style: { height: `${Math.max(4, ((Math.min(hi, Math.max(lo, r.acc)) - lo) / (hi - lo)) * 100)}%` } }),
      ]),
      el("span", { class: "months__m" }, `${r.m}월`),
    ]))),
    el("figcaption", { class: "months__cap" }, "2026 월별 적중률"),
    el("table", { class: "sr-only" }, [
      el("caption", {}, "2026 월별 적중률"),
      el("tr", {}, [el("th", { scope: "col" }, "월"), el("th", { scope: "col" }, "적중률"), el("th", { scope: "col" }, "경기 수")]),
      ...rows.map((r) => el("tr", {}, [el("td", {}, `${r.m}월`), el("td", {}, fmtPct(r.acc, 1)), el("td", {}, String(r.n))])),
    ]),
  ]);
}

function liveRecord() {
  if (!state.history) return el("p", { class: "live live--err" }, "매일 예측 기록을 불러오지 못했습니다.");
  const decided = state.history.filter((h) => h.status === "FINAL" && (h.correct === 0 || h.correct === 1));
  const c = decided.reduce((a, h) => a + h.correct, 0);
  if (!decided.length) return el("p", { class: "live" }, [el("b", {}, "매일 예측"), " 아직 결과가 나온 경기가 없습니다"]);
  // 경기 하나 = 칸 하나(적중은 채움, 미적중은 빈 칸), 오른쪽에 "적중 / 경기"
  return el("div", { class: "live", role: "img", "aria-label": `매일 예측 ${decided.length}경기 중 ${c}경기 적중` }, [
    el("b", {}, "매일 예측"),
    el("span", { class: "live__pips" }, decided.slice(-20).map((h, i) => el("i", { class: h.correct ? "is-hit" : null, style: { "--i": String(i) }, title: `${h.date} ${h.correct ? "적중" : "미적중"}` }))),
    el("span", { class: "live__n" }, `${c} / ${decided.length}`),
  ]);
}

function renderAccuracy() {
  const body = $("accuracy-body");
  const r = state.report;
  if (!r) {
    showError(body, state.errors.report, async () => { await loadReport(); renderAccuracy(); });
    return;
  }
  const t = r.models?.[r.selected]?.test ?? r.models?.lr?.test ?? {};
  const b = r.baselines?.test ?? {};
  const seasons = r.train_seasons ?? [];
  const rows = [["이 모델", t.accuracy, true], ["선발 평균자책점 낮은 팀", b.lower_starter_era], ["시즌 승률 높은 팀", b.better_win_pct], ["무조건 홈팀", b.home_always]]
    .filter(([, v]) => fin(v));
  const top = Math.max(...rows.map(([, v]) => Number(v)));
  const kpi = el("span", {}, fmtPct(t.accuracy, 1));
  countUp(kpi, Number(t.accuracy) * 100, { from: 50, dur: 1100, fmt: (v) => `${v.toFixed(1)}%` });
  const p = r.significance?.mcnemar_p;
  const sig = fin(p) && Number(p) < 0.05;
  const pNote = fin(p) ? `(p = ${Number(p).toFixed(3)})` : "";
  body.replaceChildren(
    el("p", { class: "kpi" }, [kpi, el("small", {}, `모델이 배우지 않은 ${r.test_season ?? "시험"} 정규시즌 ${t.n ?? "—"}경기 적중률`)]),
    el("div", { class: "rank" }, rows.map(([label, v, me], i) => el("div", { class: `rank__row${me ? " is-me" : ""}` }, [
      el("span", { class: "rank__label" }, label),
      el("span", { class: "rank__track" }, el("i", { style: { width: `${((Number(v) / top) * 100).toFixed(1)}%`, "--i": String(i) } })),
      el("span", { class: "rank__n" }, fmtPct(v, 1)),
    ]))),
    liveRecord(),
    el("details", { class: "more" }, [
      el("summary", {}, "이 숫자, 믿어도 될까요?"),
      el("p", {}, (sig
        ? `미리 정한 비교 상대 규칙보다 높고, ${t.n ?? ""}경기로 봐도 우연으로 보기 어려운 차이입니다${pNote}. 다만 한 시즌 결과이므로 성적표의 여러 시즌 시험도 함께 보세요. `
        : `가장 잘 맞힌 간단한 규칙보다 높지만, ${t.n ?? ""}경기로는 우연과 구분할 만큼 큰 차이가 아닙니다${pNote}. `)
        + (seasons.length ? `${seasons[0]}–${seasons.at(-1)} 시즌으로 배우고, ${r.val_season} 시즌으로 모델을 고르고, ${r.test_season} 시즌으로 시험했습니다.` : "")),
      el("p", {}, "간단한 규칙은 모델 없이 한 가지 기준으로만 이길 팀을 고르는 방법입니다. 선발 평균자책점은 작년과 올해 기록을 합친 값입니다."),
      el("a", { href: "report.html" }, "모델 성적표에서 자세히 보기"),
    ]),
  );
}

// ---------- ③ 오늘 선발, 어떤 유형? ----------

function blurbFor(type) {
  if (!type || !state.players) return null;
  return typeBlurb("pitcher", state.players.types?.pitcher?.find((t) => t.id === type.id));
}

function starterBlock(g, side) {
  const s = g[side].starter;
  const team = teamName(g[side].code);
  const role = side === "home" ? "홈" : "원정";
  if (!s) {
    return el("div", { class: "starter", style: { "--c": teamSideColors(g[side].code)[0] } }, [
      el("div", { class: "starter__top" }, [el("b", {}, "선발 미정"), el("span", { class: "starter__team" }, `${team} ${role}`)]),
    ]);
  }
  const stat = (k, v) => el("span", { class: "starter__stat" }, [el("small", {}, k), el("b", {}, v)]);
  // 카드 숫자는 올해 기록만 (모델의 선발 요인은 작년 + 올해를 합쳐 본다)
  const stats = fin(s.ip) || fin(s.era)
    ? el("div", { class: "starter__stats", title: "올해 기록만입니다. 모델은 작년 기록까지 합쳐 봅니다." }, [
      el("p", { class: "starter__cap" }, "올해 기록"),
      stat("평균자책점", num(s.era)), stat("9이닝당 삼진", num(s.k9)), stat("9이닝당 볼넷", num(s.bb9)), stat("이닝", fmtInnings(s.ip)), stat("선발 등판", fin(s.starts) ? String(s.starts) : "—")])
    : el("p", { class: "starter__note" }, "올해 등판 기록이 없습니다.");
  const blurb = blurbFor(s.type);
  return el("div", { class: "starter", style: { "--c": teamSideColors(g[side].code)[0] } }, [
    el("div", { class: "starter__top" }, [el("b", {}, starterName(s)), el("span", { class: "starter__team" }, `${team} ${role}`), typePill(s.type, false)]),
    stats,
    // 유형 설명은 players.json을 읽은 뒤에 채운다 — 자리를 미리 잡아 두어 화면이 밀리지 않게
    s.type && (blurb || !state.players) ? el("p", { class: "starter__note starter__blurb" }, blurb ?? "") : null,
    !s.type ? el("p", { class: "starter__note", title: NO_TYPE_TIP }, "작년 등판이 적어(또는 작년 기록이 없어) 유형을 붙이지 않았습니다.") : null,
  ]);
}

function renderStarters() {
  const body = $("starters-body");
  const g = selectedGame();
  $("starters-title").textContent = state.mode === "live" ? "오늘 선발, 어떤 유형?" : "이날 선발, 어떤 유형?";
  if (!g) {
    body.replaceChildren(el("p", { class: "empty" }, "이날은 선발이 나선 경기가 없습니다."));
    return;
  }
  $("starters-lead").textContent = `작년 기록으로 붙인 투수 유형입니다.${state.mode === "rewind" ? " 이날 실제로 나온 선발입니다." : ""}`;
  if (!g.away.starter && !g.home.starter) {
    body.replaceChildren(el("div", { class: "starter starter--none" }, [
      ballSVG({ cls: "starter__ball" }),
      el("div", {}, [el("b", {}, "양 팀 선발 발표 전"), el("p", { class: "starter__note" }, "발표되면 다음 갱신 때 선발 기록을 넣어 다시 계산합니다.")]),
    ]));
    return;
  }
  body.replaceChildren(starterBlock(g, "away"), starterBlock(g, "home"));
}

// ---------- 선발 바꿔 보기 ----------
// 모델 숫자(로지스틱 회귀 계수·중앙값·평균·표준편차)와 경기별 후보 선발 기록으로 브라우저에서 확률을 다시 계산한다(whatif.js).
// 라이브: whatif.json (오늘 경기), 되감기: 그날 파일의 whatif + index.json의 whatif_model. 예고(실제) 선발이 기본값이고,
// 그때의 확률은 위 매치업 카드의 공개 확률과 같다(tests/test_whatif.py).

function whatifData(g) {
  if (!g) return null;
  if (state.mode === "rewind") {
    const model = state.index?.whatif_model, block = state.day?.whatif?.find((b) => b.game_id === g.game_id);
    return model && block ? { model, block } : null;
  }
  const w = state.whatif;
  if (!w?.model || w.date !== state.day?.date) return null;
  const block = w.games?.find((b) => b.game_id === g.game_id);
  return block ? { model: w.model, block } : null;
}

function renderWhatif() {
  const body = $("whatif-body");
  const g = selectedGame();
  const data = whatifData(g);
  if (!data) {
    body.replaceChildren(el("p", { class: "empty" }, g ? "이 경기는 선발을 바꿔 볼 데이터가 없습니다." : "이날은 바꿔 볼 경기가 없습니다."));
    return;
  }
  const { model, block } = data;
  const sides = ["away", "home"];
  const ann = block.announced ?? {};
  if (state.wiPick?.gameId !== g.game_id) state.wiPick = { gameId: g.game_id, away: ann.away, home: ann.home };
  const cand = (side, pid) => block.candidates[side].find((c) => c.player_id === pid) ?? null;
  const nameOf = (c) => state.nameKo?.get(c.player_id) ?? c.name ?? "이름 없음";
  const word = state.mode === "live" ? "예고" : "실제";
  const pickNow = () => ({ home: cand("home", state.wiPick.home), away: cand("away", state.wiPick.away) });

  const result = el("div", { class: "wi-result", "aria-live": "polite" });
  const draw = () => {
    const now = pickNow();
    const p = whatifProb(model, block.base, now.home?.line ?? null, now.away?.line ?? null);
    const p0 = whatifProb(model, block.base, cand("home", ann.home)?.line ?? null, cand("away", ann.away)?.line ?? null);
    const same = state.wiPick.home === ann.home && state.wiPick.away === ann.away;
    const noAnn = ann.home == null || ann.away == null; // 선발 발표 전 (한쪽이라도)
    // 모델은 두 팀 선발 기록이 모두 있을 때만 선발 요인을 쓴다 — 한쪽만 고르면 확률이 그대로라 이유를 알려 준다
    const missing = ["away", "home"].filter((s) => state.wiPick[s] == null);
    const noLine = ["away", "home"].filter((s) => state.wiPick[s] != null && !now[s]?.line);
    const fav = favState(p);
    const pct = (v) => `${Math.round(v * 1000) / 10}%`;
    const d = (p - p0) * 100;
    const side = (code, v) => el("div", { class: `wi-side${fav && fav !== "tie" && ((fav === "home") === (code === g.home.code)) ? " is-fav" : ""}` }, [
      teamLogo(code, { size: "md" }), el("span", { class: "wi-side__name" }, teamName(code)),
      fav && fav !== "tie" && ((fav === "home") === (code === g.home.code)) ? teamChip(code, pct(v), "wi-side__num") : el("b", { class: "wi-side__num" }, pct(v)),
    ]);
    result.replaceChildren(
      el("div", { class: "wi-sides" }, [side(g.away.code, 1 - p), el("span", { class: "wi-vs", "aria-hidden": "true" }, "vs"), side(g.home.code, p)]),
      el("div", { class: "split wi-split", role: "img", "aria-label": `${teamName(g.away.code)} ${pct(1 - p)}, ${teamName(g.home.code)} ${pct(p)}` }, [
        el("i", { style: { flexGrow: String(Math.max(0.02, 1 - p)), background: teamColors(g.away.code).bg } }),
        el("i", { style: { flexGrow: String(Math.max(0.02, p)), background: teamColors(g.home.code).bg } }),
      ]),
      el("p", { class: "wi-delta" }, same
        ? (noAnn ? "아직 선발 발표 전이라 선발 기록 없이 계산한 확률입니다. 위 경기 카드의 확률과 같습니다."
          : `${word} 선발 그대로입니다. 위 경기 카드의 확률과 같습니다.`)
        : Math.abs(d) < 0.05
          ? `${noAnn ? "발표 전" : `${word} 선발`} 확률과 같습니다.`
          : [`${noAnn ? "선발 발표 전" : `${word} 선발일 때`}보다 ${teamName(g.home.code)} 승리 확률이 `, el("b", {}, `${d >= 0 ? "+" : "−"}${Math.abs(d).toFixed(1)}%p`), ` ${d >= 0 ? "올라갑니다" : "내려갑니다"}.`]),
      // replaceChildren은 null을 "null" 글자로 넣으므로 펼친다
      ...(missing.length === 1
        ? [el("p", { class: "wi-note wi-note--ask" }, `모델은 두 팀 선발을 모두 알 때만 선발 기록을 씁니다. ${teamName(g[missing[0]].code)} 선발도 골라 보세요.`)]
        : noLine.length
          ? [el("p", { class: "wi-note" }, `${noLine.map((s) => nameOf(now[s])).join(", ")}은(는) 작년·올해 기록이 없어 선발 기록 없이 계산했습니다.`)] : []),
    );
  };

  const picker = (side) => {
    const code = g[side].code;
    const onchange = (e) => { state.wiPick[side] = e.target.value === "" ? null : Number(e.target.value); draw(); };
    // 선발 발표 전이면 맨 위에 "발표 전" 칸을 두고 기본으로 고른다 (그래야 화면의 선택과 계산이 같다)
    const none = ann[side] == null
      ? [el("option", { value: "", selected: state.wiPick[side] == null ? "" : null }, "발표 전 (선발 모름)")] : [];
    const sel = el("select", { class: "wi-select", id: `wi-${side}`, onchange }, [...none,
      ...block.candidates[side].map((c) => {
        const tag = c.player_id === ann[side] ? ` (${word} 선발)` : c.starts ? ` (선발 ${c.starts}경기)` : "";
        return el("option", { value: String(c.player_id), selected: c.player_id === state.wiPick[side] ? "" : null }, `${nameOf(c)}${tag}`);
      })]);
    return el("label", { class: "wi-pick" }, [
      el("span", { class: "wi-pick__label" }, [teamLogo(code, { size: "sm" }), `${teamName(code)} ${side === "home" ? "홈" : "원정"} 선발`]), sel]);
  };
  const reset = el("button", { class: "btn btn--secondary wi-reset", type: "button", onclick: () => {
    state.wiPick = { gameId: g.game_id, away: ann.away, home: ann.home };
    renderWhatif();
  } }, ann.home == null || ann.away == null ? "처음 상태로 되돌리기" : `${word} 선발로 되돌리기`);

  $("whatif-lead").textContent = `${matchLabel(g)}. 두 팀 선발을 이 시즌 선발로 나온 다른 투수로 골라 보면 모델이 승리 확률을 다시 계산합니다.`;
  body.replaceChildren(
    el("div", { class: "wi-picks" }, sides.map(picker)),
    result,
    el("div", { class: "wi-foot" }, [reset]),
    el("details", { class: "more" }, [el("summary", {}, "어떻게 계산하나요"), el("ul", {}, [
      el("li", {}, "실제 예측에 쓰는 모델 그대로, 선발과 관련된 요인만 바꿔 다시 계산합니다. 팀 성적·Elo 같은 나머지 요인은 그대로입니다."),
      el("li", {}, "선발 요인은 그 투수의 작년+올해 기록(평균자책점·FIP·9이닝당 삼진·볼넷·던진 이닝·최근 3경기 실점)으로 만듭니다. 이 경기 전날까지의 기록만 씁니다."),
      el("li", {}, "후보는 이 시즌 그날 전까지 그 팀 선발로 나온 투수 중 선발 수가 많은 순입니다. 계산은 이 브라우저에서 바로 하며, 실제 예측 기록은 바뀌지 않습니다."),
    ])]),
  );
  draw();
}

// ---------- ④ 전망 ----------

function renderOutlook() {
  const body = $("outlook-body");
  const title = $("outlook-title");
  const o = state.day?.outlook;
  if (!o) {
    title.textContent = "전망";
    body.replaceChildren(el("p", { class: "empty" }, "이날은 전망을 계산하지 못했습니다."));
    return;
  }
  if (o.type === "series") return outlookSeries(o, title, body);
  if (o.type === "playoff_race") return outlookRace(o, title, body);
  title.textContent = "다음 경기";
  const next = o.next_game_date ?? state.status?.next_game_date;
  const days = next ? Math.round((Date.parse(next) - Date.parse(todayKST())) / 864e5) : null;
  body.replaceChildren(
    el("p", { class: "card__lead" }, "다음 경기까지"),
    !next ? el("p", { class: "empty" }, "다음 경기 일정이 아직 없습니다.")
      : days < 0 ? el("p", { class: "empty" }, `마지막으로 알려진 경기일(${fmtDate(next)})이 지났습니다. 다음 갱신 때 새 일정으로 바뀝니다.`)
      : el("p", { class: "kpi" }, [days > 0 ? `D-${days}` : "오늘", el("small", {}, fmtDate(next))]),
  );
}

function outlookSeries(o, title, body) {
  title.textContent = `${o.name} 전망`;
  const need = Math.floor(o.best_of / 2) + 1;
  const [t0, t1] = o.teams;
  const lead = Number(o.win_prob[0]) >= Number(o.win_prob[1]) ? 0 : 1;
  const order = seriesOrder(o);                     // 오늘 경기의 원정 → 홈 순서
  const isLead = (i) => i === lead && Number(o.win_prob[0]) !== Number(o.win_prob[1]);
  const [w0, w1] = (o.most_common_result ?? "").split("-").map(Number);
  const last = o.best_of - (o.head_start ?? [0, 0]).reduce((a, b) => a + b, 0);
  const big = el("span", {}, prob(o.win_prob[lead]));
  countUp(big, Number(o.win_prob[lead]) * 100, { from: 50, dur: 1100, fmt: (v) => `${Math.round(v)}%` });
  // 승수 칸: 우승에 필요한 승수만큼 칸, 이긴 만큼 팀 색으로 채운다 (와일드카드 1승 어드밴티지도 칸 하나)
  const pips = (i) => el("div", { class: "pips__row" }, [
    el("span", { class: "pips__team" }, isLead(i) ? teamText(o.teams[i], teamName(o.teams[i])) : teamName(o.teams[i])),
    el("span", { class: "pips__dots", role: "img", "aria-label": `${teamName(o.teams[i])} ${o.wins[i]}승 (${need}승이면 시리즈 승리)` },
      Array.from({ length: need }, (_, k) => el("i", { class: k < o.wins[i] ? "is-on" : null, style: { background: k < o.wins[i] ? teamSideColors(o.teams[i])[0] : null } }))),
    el("span", { class: "pips__n", style: isLead(i) && !teamColors(o.teams[i]).chipOnly ? { color: teamColors(o.teams[i]).ink } : null }, `${o.wins[i]}승`),
  ]);
  body.replaceChildren(
    el("p", { class: "card__lead", title: "모델 확률로 남은 경기를 컴퓨터로 여러 번 가상으로 치러 보고 결과를 세는 방법(시뮬레이션)입니다." }, `${o.best_of}전 ${need}선승. 남은 경기를 가상으로 1만 번 치러 본 결과입니다.`),
    el("div", { class: "pips" }, order.map(pips)),
    el("p", { class: "kpi kpi--team" }, [teamChip(o.teams[lead], big, "tchip--kpi"), el("small", {}, `${teamName(o.teams[lead])} 시리즈 승리 확률`)]),
    el("div", { class: "split", role: "img", "aria-label": `${teamName(t0)} ${prob(o.win_prob[0])}, ${teamName(t1)} ${prob(o.win_prob[1])}` }, order.map((i) =>
      el("i", { style: { flexGrow: String(Math.max(0.02, Number(o.win_prob[i]))), background: teamSideColors(o.teams[i])[0] } }))),
    el("div", { class: "split__cap" }, order.map((i) => (isLead(i) ? teamText(o.teams[i], `${teamName(o.teams[i])} ${prob(o.win_prob[i])}`)
      : el("span", {}, `${teamName(o.teams[i])} ${prob(o.win_prob[i])}`)))),
    el("dl", { class: "facts" }, [
      Number.isFinite(w0) ? el("div", {}, [el("dt", {}, "가장 자주 나온 결과"), el("dd", {}, w0 > w1 ? teamChip(t0, `${teamName(t0)} ${w0}승 ${w1}패`, "tchip--sm")
        : teamChip(t1, `${teamName(t1)} ${w1}승 ${w0}패`, "tchip--sm"))]) : null,
      el("div", {}, [el("dt", {}, `${last}차전까지 갈 확률`), el("dd", {}, fmtPct(o.goes_distance_prob))]),
    ]),
  );
}

function outlookRace(o, title, body) {
  title.textContent = "가을야구 진출 확률";
  const g = selectedGame();
  const teams = Object.entries(o.teams ?? {}).sort((a, b) => b[1].playoff_prob - a[1].playoff_prob);
  const pa = Number(o.teams?.[g?.away.code]?.playoff_prob), ph = Number(o.teams?.[g?.home.code]?.playoff_prob);
  const top = g && Number.isFinite(pa) && Number.isFinite(ph) && pa !== ph ? (pa > ph ? g.away.code : g.home.code) : null;
  const big = g ? ["away", "home"].map((side) => {
    const code = g[side].code;
    const t = o.teams?.[code];
    return el("div", { class: "race__team" }, [
      el("p", { class: "race__num num" }, code === top ? teamChip(code, prob(t?.playoff_prob), "tchip--kpi") : prob(t?.playoff_prob)),
      el("p", { class: "race__name" }, code === top ? teamText(code, teamName(code)) : teamName(code)),
      el("p", { class: "race__sub num" }, t ? `지금 ${t.rank_now}위, ${t.wins}승 ${t.losses}패` : "—"),
    ]);
  }) : [];
  const table = el("div", { class: "table-scroll" }, el("table", { class: "table" }, [
    el("caption", { class: "sr-only" }, "10개 구단 가을야구 진출 확률"),
    el("thead", {}, el("tr", {}, [el("th", { scope: "col" }, "팀"), el("th", { scope: "col", class: "num" }, "순위"),
      el("th", { scope: "col", class: "num" }, "승-패"),
      el("th", { scope: "col", class: "num", title: "1만 번 가상 시즌에서 나온 최종 승수의 평균입니다." }, "예상 최종 승수"),
      el("th", { scope: "col", class: "num" }, "진출 확률")])),
    el("tbody", {}, teams.map(([code, t]) => el("tr", { class: g && (code === g.home.code || code === g.away.code) ? "is-today" : null }, [
      el("td", {}, teamName(code)), el("td", { class: "num" }, `${t.rank_now}위`), el("td", { class: "num" }, `${t.wins}-${t.losses}`),
      el("td", { class: "num" }, num(t.exp_wins, 1)), el("td", { class: "num" }, prob(t.playoff_prob)),
    ]))),
  ]));
  body.replaceChildren(
    el("p", { class: "card__lead" }, g ? `${matchLabel(g)} 두 팀이 5위 안에 들 확률` : "5위 안에 들 확률"),
    ...(big.length ? [el("div", { class: "race" }, big)] : []), // replaceChildren은 null을 "null" 글자로 넣으므로 펼친다
    el("details", { class: "more race__all" }, [el("summary", {}, "10팀 모두 보기"), el("div", { class: "inset" }, table)]),
    el("p", { class: "card__foot" }, `${fmtDate(o.as_of)} 기준으로 남은 경기를 가상으로 1만 번 치러 봤습니다.`),
  );
}

// ---------- ⑥ 최근 예측 ----------

function renderRecent() {
  const body = $("recent-body");
  const item = (date, match, sub, tag) => el("li", {}, [el("span", { class: "log__d" }, date), el("span", { class: "log__m" }, [el("b", {}, match), el("small", {}, sub)]), tag]);
  const pickChip = (p, home, away) => {
    const fav = favState(p);
    if (!fav) return "—";
    if (fav === "tie") return el("span", { class: "pill pill--sm pill--muted" }, "반반 50%");
    const code = fav === "home" ? home : away;
    return teamChip(code, `${teamName(code)} ${fmtPct(fav === "home" ? p : 1 - p)}`, "tchip--sm");
  };
  // 결과 글자: "KT 승"이면 이긴 팀 글자색, 무승부·취소 등은 그대로
  const result = (g) => {
    const text = winnerText(g);
    const code = g.winner === "HOME" ? g.home : g.winner === "AWAY" ? g.away : null;
    return code ? teamText(code, text) : text;
  };
  if (state.mode === "rewind" && state.day) {
    $("recent-title").textContent = "이날의 결과";
    $("recent-lead").textContent = "예측과 실제 결과";
    body.replaceChildren(el("ul", { class: "log" }, ordered(state.day).map((g) => {
      const r = g.result;
      return item(r ? fmtScore(r.away_score, r.home_score) : "—", matchLabel(g),
        r ? ["예측 ", pickChip(g.home_win_prob, g.home.code, g.away.code), " → ", result({ winner: r.winner, home: g.home.code, away: g.away.code, status: "FINAL" })] : NOTES[g.status_note] ?? "취소",
        r ? verdictPill(r) : verdictPill({ status: "CANCELED" }));
    })));
    return;
  }
  $("recent-title").textContent = "최근 예측";
  $("recent-lead").textContent = "경기 전 마지막 예측";
  if (!state.history) {
    showError(body, state.errors.history, async () => { await loadHistory(); renderRecent(); renderAccuracy(); });
    return;
  }
  const rows = state.history.slice(-8).reverse();
  if (!rows.length) {
    body.replaceChildren(el("p", { class: "empty" }, "아직 매일 예측 기록이 없습니다."));
    return;
  }
  body.replaceChildren(el("ul", { class: "log" }, rows.map((h) => {
    const res = winnerText(h);
    const pick = pickChip(h.home_win_prob, h.home, h.away);
    return item(fmtDateShort(h.date), `${teamName(h.away)} vs ${teamName(h.home)}`, res === "경기 전" ? ["예측 ", pick] : ["예측 ", pick, " → ", result(h)], verdictPill(h));
  })));
}

// ---------- ⑤ 선수 유형 지도 (players.json 1.77 MB — 나머지를 다 그린 뒤에 읽는다) ----------

function loadPlayersLater() {
  const go = () => loadPlayers();
  if ("requestIdleCallback" in window) requestIdleCallback(go, { timeout: 1500 });
  else setTimeout(go, 300);
}

let playersReq = null; // players.json은 한 번만 받는다(init 재시도 때도 다시 받지 않음, 실패하면 비워 다시 시도)
async function loadPlayers() {
  const body = $("typemap-body");
  if (!state.players) {
    body.replaceChildren(
      el("div", { class: "inset" }, el("div", { class: "skeleton", style: { height: "210px" } })),
      el("div", { class: "typemap__counts" }, el("p", { class: "small" }, "선수 데이터를 불러오는 중…")),
    );
    playersReq ??= fetchJSON("players.json");
    try {
      state.players = await playersReq;
      delete state.errors.players;
    } catch (err) {
      playersReq = null;
      state.errors.players = err.message;
      showError(body, err.message, loadPlayers);
      return;
    }
  }
  state.nameKo ??= koreanNames(state.players);
  renderTypeMap();
  if (state.day) { // 선발 이름을 한글로 바꾸고(매치업·선발 카드·선발 바꿔 보기) 유형 설명(blurb)을 덧붙인다
    renderMatchups();
    renderStarters();
    renderWhatif();
  }
}

/** players.json → player_id → 한글 이름. 가장 최근 시즌 행을 먼저 쓰고, 그 시즌에 없는 선수는 다른 시즌 행으로 채운다. */
function koreanNames(data) {
  const rows = (data?.players ?? []).filter((p) => p?.name_ko && fin(p.season));
  rows.sort((a, b) => b.season - a.season);
  const map = new Map();
  for (const p of rows) if (!map.has(p.player_id)) map.set(p.player_id, p.name_ko);
  return map;
}

function renderTypeMap() {
  const body = $("typemap-body");
  const all = (state.players.players ?? []).filter((p) => p.group === "batter" && fin(p.season));
  if (!all.length) {
    $("typemap-lead").textContent = "비슷한 기록의 타자끼리 가깝게 놓은 지도입니다.";
    body.replaceChildren(el("p", { class: "empty" }, "선수 데이터에 타자가 없습니다. 선수 페이지에서 다른 그룹을 볼 수 있습니다."));
    return;
  }
  const season = Math.max(...all.map((p) => p.season));
  const bat = all.filter((p) => p.season === season);
  const types = state.players.types?.batter ?? [];
  $("typemap-lead").textContent = `${season} 타자 ${bat.length}명입니다. 기록이 비슷할수록 가까이 놓았습니다.`;
  // 범례 알약 대신 유형별 요약 표: 선수 수·평균 기록·대표 선수 (지도 색과 같은 점)
  const counts = typeSummaryTable(bat, "batter", types, { caption: `${season} 타자 유형별 선수 수와 평균 기록` });
  const chart = el("div");
  body.replaceChildren(el("div", { class: "inset" }, chart), counts);
  scatter(chart, bat.map((p) => ({ id: p.player_id, x: p.x, y: p.y, label: `${p.name_ko ?? p.name}, ${teamName(p.team)}`, type: p.type })), {
    colorKey: (p) => typeColor("batter", p.type?.id), typeLabel: (p) => p.type?.name ?? "—", height: "fill",
    label: `${season} 타자 유형 지도 (점 하나가 한 선수)`,
  });
}

// ---------- 하루 그리기 ----------

/** 화면 낭독기용 한 줄 요약(aria-live는 이 줄에만). */
function announce() {
  const games = state.day?.games ?? [];
  const what = state.mode === "live" ? "예측" : "다시 보기";
  $("day-status").textContent = `${fmtDate(state.day?.date)} ${what}, ${games.length}경기를 표시했습니다.`;
}

function renderDay() {
  renderSeason();
  renderDateBar();
  renderHead();
  renderMatchups();
  renderTabs();
  renderFactors();
  renderStarters();
  renderWhatif();
  renderStandings();
  renderSchedule();
  renderOutlook();
  renderRecent();
  announce();
}

init();
