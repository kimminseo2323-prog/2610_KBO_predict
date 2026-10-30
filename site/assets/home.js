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
  teamName, typeColor, verdictPill, winnerText, renderNav, renderFooter, showError,
} from "./app.js";
import { barChart, scatter } from "./charts.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const FIXTURE = IS_LOCAL ? params.get("fixture") : null;     // "edge" | "offseason" | null
const FIXTURE_BASE = "../tests/fixtures/site";
const REWIND = "rewind/2026";

const state = {
  status: null, latest: null, index: null, history: null, report: null, players: null,
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
const prob = (v) => {
  if (!fin(v)) return "—";
  const x = Number(v);
  if (x > 0 && x < 0.005) return "<1%";
  if (x < 1 && x > 0.995) return ">99%";
  return fmtPct(x);
};
const sign = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%p`;
const matchLabel = (g) => `${teamName(g.away.code)} vs ${teamName(g.home.code)}`;
/** 선발 이름: players.json을 읽었으면 한글 이름(player_id로 찾음), 그 전이나 없으면 데이터의 로마자 이름. */
const starterName = (s) => state.nameKo?.get(s.player_id) ?? s.name;

/** KST 오늘 날짜 "YYYY-MM-DD". */
const todayKST = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" }).format(new Date());

// 구장·취소 사유는 원본이 영문이라 아는 것만 한글로 바꾼다(모르는 값은 그대로).
const STADIUMS = {
  Jamsil: "잠실", Gocheok: "고척", Munhak: "문학", Incheon: "인천", Suwon: "수원", Daejeon: "대전",
  Daegu: "대구", Gwangju: "광주", Sajik: "사직", Busan: "부산", Changwon: "창원", Pohang: "포항",
  Ulsan: "울산", Cheongju: "청주",
};
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
    state.errors.index = "되감기 목차(rewind/2026/index.json)에 날짜가 없습니다.";
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
    showError($("rewind-error"), state.errors.index ?? "되감기 목차를 불러오지 못했습니다.", retryIndex);
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
      $(id).replaceChildren(el("p", { class: "empty" }, "이 날짜의 경기 데이터를 불러오지 못했습니다. 위에서 다시 불러오기를 눌러 보세요."));
    }
    $("factor-tabs").hidden = true;
  }
}

/** 되감기 목차를 다시 받아 보고, 되면 마지막 날짜를 연다. */
async function retryIndex() {
  await loadIndex();
  if (state.index && !state.index.dates?.length) {
    state.errors.index = "되감기 목차(rewind/2026/index.json)에 날짜가 없습니다.";
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
    hint.textContent = next && next >= todayKST()
      ? `지금은 라이브 예측이 없습니다. 다음 경기는 ${fmtDate(next)}입니다.`
      : "지금은 비시즌이라 라이브 예측이 없습니다. 2026 시즌 경기일을 골라 보세요.";
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
    $("day-lead").replaceChildren(
      `예측 시각 ${fmtKST(day.generated_at)} · 승패 모델 ${day.model_version ?? "—"} · ${games.length}경기`,
      canceled ? ` (취소 ${canceled})` : "",
    );
  } else {
    const d = state.index.dates[state.dateIdx];
    const snapped = state.snappedFrom && /^\d{4}-\d{2}-\d{2}$/.test(state.snappedFrom)
      ? `${fmtDate(state.snappedFrom)}에는 경기가 없어 가장 가까운 경기일을 보여 줍니다. ` : "";
    state.snappedFrom = null; // 처음 한 번만 알린다
    $("day-title").textContent = `${fmtDate(day.date)} 되감기`;
    $("day-lead").textContent = snapped + (d && d.decided
      ? `이날 ${d.decided}경기 중 ${d.correct}경기 적중 · 2026 시즌 전체 ${fmtPct(state.index.accuracy, 1)}. 2026 경기를 학습에 쓰지 않은 ${day.model_version ?? "되감기"} 모델로 다시 예측했습니다.`
      : `이날은 적중을 따질 경기가 없습니다(취소·무승부). ${day.model_version ?? "되감기"} 모델 기준.`);
  }
}

// ---------- 매치업 카드 ----------

function typePill(type, onCard) {
  if (!type) return el("span", { class: `pill pill--sm ${onCard ? "pill--white" : "pill--muted"}` }, onCard ? "유형 없음" : "직전 시즌 자격 없음");
  const tok = typeColor("pitcher", type.id);
  return el("span", { class: `pill pill--sm ${onCard ? "pill--white" : `pill--${tok}`}` }, [
    onCard ? el("span", { class: "dot", style: { background: `var(--${tok})` }, "aria-hidden": "true" }) : null, type.name,
  ]);
}

/**
 * 한쪽 진영(원정 = 왼쪽 핑크, 홈 = 오른쪽 틸). 이름은 크게(한 줄 정식 이름은 그 아래 작게), 숫자는 가장 크게.
 * 선발·기록은 전부 하나의 크림 칩(하단 자막)에 담는다 — 핑크·틸 위 작은 글자의 대비 문제를 없애고 두 진영을 같은 모양으로.
 */
function sideBlock(g, side, prob, large) {
  const t = g[side];
  const s = t.starter;
  const role = side === "home" ? "홈" : "원정";
  const head = el("div", { class: "side__head" }, [
    el("p", { class: "side__role" }, role),
    el("h3", { class: "side__team" }, teamName(t.code)),
    large ? el("p", { class: "side__full" }, teamName(t.code, { full: true })) : null,
  ]);
  const probEl = el("p", { class: "side__prob" }, [
    el("span", { class: "side__num" }, prob === "—" ? "—" : [String(prob), el("small", {}, "%")]),
    el("span", { class: "side__who" }, `${teamName(t.code)} 승리`),
  ]);
  const stats = !s ? null
    : fin(s.era) || fin(s.k9) || fin(s.bb9) ? `ERA ${num(s.era)} · K/9 ${num(s.k9)} · BB/9 ${num(s.bb9)}` : "선발 올해 등판 기록 없음";
  const chip = el("div", { class: "side__chip" }, [
    s ? el("p", { class: "chip__row" }, [el("span", {}, ["선발 ", el("b", {}, starterName(s))]), typePill(s.type, false)])
      : el("p", { class: "chip__row" }, el("b", {}, "선발 미정")),
    large && stats ? el("p", { class: "chip__stats num" }, stats) : null,
    large ? el("p", { class: "chip__stats num" }, `${recentForm(t.last10, t.win_pct_season)} · 시즌 승률 ${fmtRate3(t.win_pct_season)}`) : null,
  ]);
  return el("div", { class: `side side--${side}` }, [head, probEl, el("div", { class: "side__details" }, chip)]);
}

/** 모델이 어느 쪽으로 얼마나 기우는지 한 마디 (잡지 표지의 헤드라인 칸). 확률이 없으면 null. */
function lean(g) {
  if (!fin(g.home_win_prob)) return null;
  const d = Number(g.home_win_prob) - 0.5;
  const a = Math.abs(d);
  if (a < 0.03) return "사실상 반반";
  const who = teamName(g[d > 0 ? "home" : "away"].code);
  return `${who} ${a < 0.1 ? "근소 우세" : a < 0.2 ? "우세" : "크게 우세"}`;
}

/** 승률을 가장 크게 움직인 요인 한 줄 + 선발 피처 미사용 알림 (하단 자막 띠). */
function ticker(g) {
  const f = (g.factors ?? []).filter((x) => fin(x.contribution_pp))
    .reduce((best, x) => (!best || Math.abs(x.contribution_pp) > Math.abs(best.contribution_pp) ? x : best), null);
  const parts = [];
  if (f) {
    const v = Number(f.contribution_pp);
    parts.push(el("span", { class: "ticker__item" }, [
      el("span", { class: "ticker__tag" }, "가장 크게 움직인 요인"),
      el("b", {}, f.name),
      el("span", { class: "num" }, `${sign(v)}${v > 0 ? " · 홈 쪽" : v < 0 ? " · 원정 쪽" : ""}`),
    ]));
  }
  if (g.starter_known === false) {
    parts.push(el("span", { class: "ticker__item ticker__note" }, "선발 정보 없이 예측했습니다 (선발 피처 미사용)"));
  }
  return parts.length ? el("div", { class: "stage__ticker" }, parts) : null;
}

/** 상단 띠: 왼쪽 = 어디서·무슨 경기·모델의 한 마디, 오른쪽 = (되감기) 결과. */
function metaPills(g, large) {
  const left = [];
  const where = [STADIUMS[g.stadium] ?? g.stadium, g.time].filter(Boolean).join(" ");
  if (where) left.push(el("span", { class: "pill pill--white" }, where));
  const o = state.day.outlook;
  if (large && o?.type === "series" && o.teams?.includes(g.home.code) && o.teams?.includes(g.away.code)) {
    left.push(el("span", { class: "pill pill--white" },
      `${o.name} ${teamName(o.teams[0])} ${o.wins[0]}승 · ${teamName(o.teams[1])} ${o.wins[1]}승`));
  }
  const say = large ? lean(g) : null;
  if (say) left.push(el("span", { class: "pill pill--white pill--lean" }, `모델 전망 · ${say}`));
  const right = [];
  const r = g.result;
  if (r) {
    if (large && r.pick) right.push(el("span", { class: "pill pill--white" }, `모델 선택 ${r.pick === "HOME" ? teamName(g.home.code) : r.pick === "AWAY" ? teamName(g.away.code) : "—"}`));
    right.push(el("span", { class: "pill pill--white num" }, `최종 ${r.away_score} : ${r.home_score}`));
    right.push(verdictPill(r));
  }
  return [left.length ? el("div", { class: "pills" }, left) : null, right.length ? el("div", { class: "pills" }, right) : null];
}

function matchupCard(g, large, settled = false) {
  if (g.status === "CANCELED") {
    return el("article", { class: `matchup matchup--canceled card${large ? " matchup--lg" : ""}`, "aria-label": `${matchLabel(g)} 취소` }, [
      el("div", { class: "pills" }, [el("span", { class: "pill pill--ink" }, "취소"),
        g.status_note ? el("span", { class: "pill pill--white" }, NOTES[g.status_note] ?? g.status_note) : null]),
      el("h3", { class: "matchup__canceled-title" }, matchLabel(g)),
      el("p", { class: "card__lead" }, "경기가 열리지 않아 예측하지 않았습니다."),
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
  return el("article", {
    class: `matchup ${large ? "matchup--lg" : "matchup--sm"}${settled ? " is-settled" : ""}`,
    style: `--cut-to: ${cut.toFixed(1)}%`, "aria-label": label,
  }, [
    meta.some(Boolean) ? el("div", { class: "stage__top" }, meta) : null,
    sideBlock(g, "away", away, large),
    sideBlock(g, "home", home, large),
    large ? el("span", { class: "stage__vs", "aria-hidden": "true" }, "VS") : null,
    // 좁은 화면에서는 경계가 사라지므로 같은 비율의 가로 막대로 긴장감을 대신한다
    el("div", { class: "stage__meter", "aria-hidden": "true" }, [
      el("span", { class: "meter__away", style: { flexGrow: String(fin(p) ? share : 50) } }),
      el("span", { class: "meter__home", style: { flexGrow: String(fin(p) ? 100 - share : 50) } }),
    ]),
    large ? ticker(g) : null,
  ]);
}

function renderMatchups() {
  const box = $("matchups");
  const games = ordered(state.day);
  box.setAttribute("aria-busy", "false");
  if (!games.length) {
    box.replaceChildren(el("div", { class: "card card--cream" }, [
      el("p", { class: "card__title" }, "이날은 경기가 없습니다."),
      el("p", { class: "card__lead" }, "위 되감기에서 2026 시즌 다른 날짜를 골라 보세요."),
    ]));
    return;
  }
  const [first, ...rest] = games;
  // 같은 날을 다시 그릴 때(players.json 뒤 선발 이름 갱신 등)는 경계가 다시 움직이지 않게 한다
  const key = `${state.mode}:${state.day.date}`;
  const settled = state.stageKey === key;
  state.stageKey = key;
  const cards = [matchupCard(first, true, settled)];
  if (rest.length) cards.push(el("div", { class: "matchups__rest" }, rest.map((g) => matchupCard(g, false, settled))));
  box.replaceChildren(...cards); // replaceChildren은 null을 "null" 글자로 넣으므로 배열로 모은다
}

// ---------- ① 승률을 가른 요인 ----------

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
  renderOutlook();
}

function renderFactors() {
  const body = $("factors-body");
  const foot = $("factors-foot");
  const g = selectedGame();
  if (!g) {
    $("factors-lead").textContent = "홈팀 승률을 올린 요인(+)과 내린 요인(−), 단위 %p";
    body.replaceChildren(el("p", { class: "empty" }, "이날은 모두 취소돼 요인이 없습니다."));
    foot.textContent = "";
    return;
  }
  $("factors-lead").textContent = `${teamName(g.home.code)}(홈) 쪽으로 기울게 한 요인은 +, ${teamName(g.away.code)}(원정) 쪽은 −. 단위 %p`;
  const rows = (g.factors ?? []).map((f) => ({ label: f.name, value: f.contribution_pp }));
  if (!rows.length) {
    body.replaceChildren(el("p", { class: "empty" }, "이 경기는 요인 분해가 없습니다."));
    foot.textContent = "";
    return;
  }
  barChart(body, rows, { color: "teal", negativeColor: "pink", format: sign, label: `${matchLabel(g)} 승률을 가른 요인 (%p)` });
  const hasBias = rows.some((r) => r.label === "기본 홈 어드밴티지");
  foot.textContent = `기여가 큰 5개만 보여 줍니다.${hasBias ? "" : " 기본 홈 어드밴티지는 이 경기에서 5위 밖입니다."}`;
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
    el("figcaption", { class: "months__cap" }, "2026 월별 적중률 (되감기)"),
    el("table", { class: "sr-only" }, [
      el("caption", {}, "2026 월별 적중률"),
      el("tr", {}, [el("th", { scope: "col" }, "월"), el("th", { scope: "col" }, "적중률"), el("th", { scope: "col" }, "경기 수")]),
      ...rows.map((r) => el("tr", {}, [el("td", {}, `${r.m}월`), el("td", {}, fmtPct(r.acc, 1)), el("td", {}, String(r.n))])),
    ]),
  ]);
}

function liveRecord() {
  if (!state.history) return el("p", { class: "acc__live" }, "라이브 기록(history.csv)을 불러오지 못했습니다.");
  const decided = state.history.filter((h) => h.status === "FINAL" && (h.correct === 0 || h.correct === 1));
  const n = decided.length;
  // 모델 버전이 바뀌면 따로 센다(성적표 ⑥과 같은 규칙): "v0.2 모델 12경기 중 7경기 적중 (58%) · v0.3 모델 …"
  const versions = [...new Set(decided.map((h) => h.model_version ?? "—"))];
  const parts = versions.map((v) => {
    const mine = decided.filter((h) => (h.model_version ?? "—") === v);
    const c = mine.reduce((s, h) => s + h.correct, 0);
    return `${v} 모델 ${mine.length}경기 중 ${c}경기 적중 (${fmtPct(c / mine.length)})`;
  });
  return el("p", { class: "acc__live" }, [
    el("b", {}, "라이브 "), n ? parts.join(" · ") : "아직 결과가 난 경기가 없습니다",
    n < 10 ? ". 라이브 기록은 2026 포스트시즌부터 쌓여 아직 표본이 적습니다." : ".",
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
  const period = seasons.length ? `학습 ${seasons[0]}–${seasons.at(-1)} · 검증 ${r.val_season} · 시험 ${r.test_season}` : "";
  const base = (label, v) => el("li", {}, [el("span", {}, label), el("b", { class: "num" }, fmtPct(v, 1))]);
  body.replaceChildren(
    el("p", { class: "card__lead" }, `${r.test_season ?? "시험"} 시즌 ${t.n ?? "—"}경기를 경기 전 정보로만 예측`),
    el("div", { class: "acc__top" }, [
      el("p", { class: "kpi" }, [fmtPct(t.accuracy, 1), el("small", {}, `${r.model_version ?? "성적표"} 모델 적중률 · log loss ${num(t.log_loss, 3)}`)]),
      monthBars(state.index),
    ]),
    el("div", { class: "inset" }, [
      el("p", { class: "acc__cap" }, "같은 경기를 단순한 규칙으로 고르면"),
      el("ul", { class: "acc__rows" }, [
        base("항상 홈팀", b.home_always), base("시즌 승률이 높은 팀", b.better_win_pct), base("선발 ERA가 낮은 팀", b.lower_starter_era),
      ]),
    ]),
    liveRecord(),
    el("p", { class: "card__foot" }, [period, period ? " · " : "", el("a", { href: "report.html" }, "모델 성적표 보기")]),
  );
}

// ---------- ③ 오늘 선발, 어떤 유형? ----------

function blurbFor(type) {
  if (!type || !state.players) return null;
  return state.players.types?.pitcher?.find((t) => t.id === type.id)?.blurb ?? null;
}

function starterBlock(g, side) {
  const s = g[side].starter;
  const team = teamName(g[side].code);
  const role = side === "home" ? "홈" : "원정";
  if (!s) {
    return el("div", { class: "inset starter" }, [
      el("div", { class: "starter__top" }, [el("b", {}, `선발 미정 · ${team}`), el("span", { class: "pill pill--sm pill--muted" }, role)]),
      el("p", { class: "starter__note" }, "선발이 발표되면 다음 갱신 때 채워집니다. 그때까지는 선발 기록 없이 예측합니다."),
    ]);
  }
  const stats = fin(s.ip) || fin(s.era)
    ? `ERA ${num(s.era)} · K/9 ${num(s.k9)} · BB/9 ${num(s.bb9)} · ${fmtInnings(s.ip)}이닝 · ${fin(s.starts) ? s.starts : "—"}경기 선발`
    : "올해 등판 기록이 없습니다.";
  const blurb = blurbFor(s.type);
  return el("div", { class: "inset starter" }, [
    el("div", { class: "starter__top" }, [el("b", {}, [starterName(s), el("span", { class: "starter__team" }, ` · ${team} ${role}`)]), typePill(s.type, false)]),
    el("p", { class: "starter__stats num" }, stats),
    // 유형 설명은 players.json을 읽은 뒤에 채운다 — 자리를 미리 잡아 두어 화면이 밀리지 않게
    s.type && (blurb || !state.players) ? el("p", { class: "starter__note starter__blurb" }, blurb ?? "") : null,
    !s.type ? el("p", { class: "starter__note" }, "직전 시즌 등판이 적어 유형을 붙이지 않았습니다.") : null,
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
  $("starters-lead").textContent = `${matchLabel(g)} · 선수 유형 모델이 직전 시즌 기록으로 붙인 유형${state.mode === "rewind" ? " (실제 선발)" : ""}`;
  body.replaceChildren(starterBlock(g, "away"), starterBlock(g, "home"));
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
  const head = (o.head_start ?? []).some((h) => h > 0)
    ? ` (${o.teams.filter((_, i) => o.head_start[i] > 0).map(teamName).join(", ")} 1승 안고 시작)` : "";
  const chart = el("div");
  const [w0, w1] = (o.most_common_result ?? "").split("-").map(Number);
  const last = o.best_of - (o.head_start ?? [0, 0]).reduce((a, b) => a + b, 0);
  const sourceNote = o.today_game_prob_source?.startsWith("win_model")
    ? "오늘 경기는 선발까지 넣은 승패 모델 확률, 남은 경기는 팀 모델 확률을 썼습니다."
    : "모든 경기에 팀 모델 확률을 썼습니다.";
  body.replaceChildren(
    el("p", { class: "card__lead" }, `${o.best_of}전 ${need}선승 · 지금 ${teamName(t0)} ${o.wins[0]}승, ${teamName(t1)} ${o.wins[1]}승${head}`),
    el("div", { class: "inset" }, [
      el("p", { class: "acc__cap" }, "시리즈를 이길 확률"),
      chart,
      el("ul", { class: "acc__rows" }, [
        Number.isFinite(w0) ? el("li", {}, [el("span", {}, "가장 흔한 결말"),
          el("b", {}, w0 > w1 ? `${teamName(t0)} ${w0}승 ${w1}패` : `${teamName(t1)} ${w1}승 ${w0}패`)]) : null,
        el("li", {}, [el("span", {}, `${last}차전까지 갈 확률`), el("b", { class: "num" }, fmtPct(o.goes_distance_prob))]),
      ]),
    ]),
    el("p", { class: "card__foot" }, `${fmtDate(o.as_of)} 기준, 남은 경기를 1만 번 시뮬레이션했습니다. ${sourceNote}`),
  );
  barChart(chart, [0, 1].map((i) => ({ label: teamName(o.teams[i]), value: o.win_prob[i], code: o.teams[i] })), {
    color: (r) => TEAMS[r.code]?.color ?? "ink", max: 1, format: prob, label: `${o.name} 시리즈 승리 확률`,
  });
}

function outlookRace(o, title, body) {
  title.textContent = "가을야구 진출 확률";
  const g = selectedGame();
  const teams = Object.entries(o.teams ?? {}).sort((a, b) => b[1].playoff_prob - a[1].playoff_prob);
  const big = g ? ["away", "home"].map((side) => {
    const code = g[side].code;
    const t = o.teams?.[code];
    return el("div", { class: "race__team" }, [
      el("p", { class: "race__num num" }, prob(t?.playoff_prob)),
      el("p", { class: "race__name" }, teamName(code)),
      el("p", { class: "race__sub num" }, t ? `현재 ${t.rank_now}위 · ${t.wins}승 ${t.losses}패` : "—"),
    ]);
  }) : [];
  const table = el("div", { class: "table-scroll" }, el("table", { class: "table" }, [
    el("caption", { class: "sr-only" }, "10개 구단 가을야구 진출 확률"),
    el("thead", {}, el("tr", {}, [el("th", { scope: "col" }, "팀"), el("th", { scope: "col", class: "num" }, "순위"),
      el("th", { scope: "col", class: "num" }, "승-패"), el("th", { scope: "col", class: "num" }, "기대 승수"), el("th", { scope: "col", class: "num" }, "진출")])),
    el("tbody", {}, teams.map(([code, t]) => el("tr", { class: g && (code === g.home.code || code === g.away.code) ? "is-today" : null }, [
      el("td", {}, teamName(code)), el("td", { class: "num" }, `${t.rank_now}위`), el("td", { class: "num" }, `${t.wins}-${t.losses}`),
      el("td", { class: "num" }, num(t.exp_wins, 1)), el("td", { class: "num" }, prob(t.playoff_prob)),
    ]))),
  ]));
  body.replaceChildren(
    el("p", { class: "card__lead" }, g ? `${matchLabel(g)} 두 팀이 5위 안에 들 확률` : "5위 안에 들 확률"),
    ...(big.length ? [el("div", { class: "race" }, big)] : []), // replaceChildren은 null을 "null" 글자로 넣으므로 펼친다
    el("details", { class: "inset race__all" }, [el("summary", {}, "10팀 모두 보기"), table]),
    el("p", { class: "card__foot" }, `${fmtDate(o.as_of)} 기준, 남은 경기를 1만 번 시뮬레이션했습니다.`),
  );
}

// ---------- ⑥ 최근 예측 ----------

function renderRecent() {
  const body = $("recent-body");
  const head = (cols) => el("thead", {}, el("tr", {}, cols.map(([t, cls]) => el("th", { scope: "col", class: cls ?? null }, t))));
  if (state.mode === "rewind" && state.day) {
    $("recent-title").textContent = "이날의 결과";
    $("recent-lead").textContent = `${fmtDate(state.day.date)} 경기, 예측과 실제 결과`;
    const rows = ordered(state.day).map((g) => {
      const r = g.result;
      return el("tr", {}, [
        el("td", {}, matchLabel(g)),
        el("td", { class: "num" }, fmtPct(g.home_win_prob)),
        el("td", { class: "num" }, r ? `${r.away_score} : ${r.home_score}` : "취소"),
        el("td", { class: "hide-sm" }, r ? winnerText({ winner: r.winner, home: g.home.code, away: g.away.code, status: "FINAL" })
          : NOTES[g.status_note] ?? "취소"),
        el("td", { class: "r" }, r ? verdictPill(r) : "—"),
      ]);
    });
    body.replaceChildren(el("div", { class: "table-scroll" }, el("table", { class: "table recent" }, [
      el("caption", { class: "sr-only" }, "이날 경기 예측과 결과"),
      head([["대진"], ["홈 승률", "num"], ["점수", "num"], ["결과", "hide-sm"], ["적중", "r"]]), el("tbody", {}, rows),
    ])));
    return;
  }
  $("recent-title").textContent = "최근 예측";
  $("recent-lead").textContent = "경기 전 마지막 예측과 실제 결과 (라이브 기록)";
  if (!state.history) {
    showError(body, state.errors.history, async () => { await loadHistory(); renderRecent(); renderAccuracy(); });
    return;
  }
  const rows = state.history.slice(-8).reverse();
  if (!rows.length) {
    body.replaceChildren(el("p", { class: "empty" }, "아직 라이브 예측 기록이 없습니다. 첫 예측은 경기 날 아침에 올라옵니다."));
    return;
  }
  body.replaceChildren(el("div", { class: "table-scroll" }, el("table", { class: "table recent" }, [
    el("caption", { class: "sr-only" }, "최근 라이브 예측 8경기"),
    head([["날짜"], ["대진"], ["홈 승률", "num"], ["결과", "hide-sm"], ["적중", "r"]]),
    el("tbody", {}, rows.map((h) => el("tr", {}, [
      el("td", { class: "nowrap" }, fmtDate(h.date).replace(/ \(.\)$/, "")), // 요일은 빼서 좁은 화면에 맞춘다
      el("td", {}, `${teamName(h.away)} vs ${teamName(h.home)}`),
      el("td", { class: "num" }, fmtPct(h.home_win_prob)),
      el("td", { class: "hide-sm" }, winnerText(h)),
      el("td", { class: "r" }, verdictPill(h)),
    ]))),
  ])));
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
      el("div", { class: "typemap__counts" }, el("p", { class: "small" }, "선수 데이터(1.8 MB)를 불러오는 중…")),
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
  if (state.day) { // 선발 이름을 한글로 바꾸고(매치업·선발 카드) 유형 설명(blurb)을 덧붙인다
    renderMatchups();
    renderStarters();
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
    $("typemap-lead").textContent = "비슷한 기록의 타자끼리 가깝게 놓은 지도";
    body.replaceChildren(el("p", { class: "empty" }, "선수 데이터에 타자가 없습니다. 선수 페이지에서 다른 그룹을 볼 수 있습니다."));
    return;
  }
  const season = Math.max(...all.map((p) => p.season));
  const bat = all.filter((p) => p.season === season);
  const types = state.players.types?.batter ?? [];
  $("typemap-lead").textContent = `${season} 타자 ${bat.length}명을 기록이 비슷할수록 가깝게 놓은 지도`;
  const counts = el("ul", { class: "typemap__counts" }, types.map((t) => el("li", { class: "pill pill--white" }, [
    el("span", { class: "dot", style: { background: `var(--${TYPE_COLORS.batter[t.id]})` }, "aria-hidden": "true" }),
    t.name, el("b", { class: "num" }, String(bat.filter((p) => p.type?.id === t.id).length)),
  ])));
  const chart = el("div");
  body.replaceChildren(el("div", { class: "inset" }, chart), counts);
  scatter(chart, bat.map((p) => ({ id: p.player_id, x: p.x, y: p.y, label: `${p.name_ko ?? p.name} · ${teamName(p.team)}`, type: p.type })), {
    colorKey: (p) => typeColor("batter", p.type?.id), typeLabel: (p) => p.type?.name ?? "—", height: "fill",
    label: `${season} 타자 유형 지도 (점 하나가 한 선수)`,
  });
}

// ---------- 하루 그리기 ----------

/** 화면 낭독기용 한 줄 요약(aria-live는 이 줄에만). */
function announce() {
  const games = state.day?.games ?? [];
  const what = state.mode === "live" ? "예측" : "되감기";
  $("day-status").textContent = `${fmtDate(state.day?.date)} ${what}, ${games.length}경기를 표시했습니다.`;
}

function renderDay() {
  renderDateBar();
  renderHead();
  renderMatchups();
  renderTabs();
  renderFactors();
  renderStarters();
  renderOutlook();
  renderRecent();
  announce();
}

init();
