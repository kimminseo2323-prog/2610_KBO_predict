// KBO Predict — 모델 성적표. report.html 전용 모듈.
//
// 화면 순서: 머리(#model-badges: "어느 모델, 어느 기간" 배지 2개) → 벤토 6장 → 푸터 증거 바.
//   벤토 section id: #holdout(크림) #calibration(라벤더) #importance(피치) #variants(오커) #cluster-quality(틸) #live-record(크림)
//
// 숫자는 모두 실행할 때 model_report.json(report-2026, 고정 파일)과 history.csv(라이브 기록)에서 읽는다.
// 이 파일에 적힌 숫자는 설명 문구의 규칙값(유의수준 0.05, 설계 목표 +3%p, 표본 30경기)뿐이다.
// 데이터 키는 docs/site/data-contract.md 매핑 표(페이지 "성적표")에 적은 것만 쓴다.
// 피처 한글 이름은 app.js의 FACTOR_LABELS(파이썬 features.FACTOR_LABELS와 테스트로 고정)를 그대로 쓴다.

import {
  FACTOR_LABELS, el, fetchJSON, fetchCSV, settle, fin, fmtPct, fmtRate3, fmtInt, fmtRange, fmtDate, fmtKST,
  teamName, typeColor, verdictPill, winnerText, renderNav, renderFooter, showError,
} from "./app.js";
import { barChart, calibrationChart } from "./charts.js";

const $ = (id) => document.getElementById(id);

const state = { report: null, history: null, status: null, errors: {} };

// ---------- 작은 도우미 ----------

/** 소수 d자리. 값이 없으면 "—". */
const num = (v, d = 3) => (fin(v) ? Number(v).toFixed(d) : "—");
/** p값: 0.001 미만은 "< .001", 그 밖은 ".046". */
const pval = (p) => (!fin(p) ? "—" : Number(p) < 0.001 ? "< .001" : fmtRate3(p));
/** 정확도 차이(0~1 소수 두 개) → "+1.5%p". */
const pp = (a, b) => {
  if (!fin(a) || !fin(b)) return "—";
  const d = (Number(a) - Number(b)) * 100;
  return `${d > 0 ? "+" : d < 0 ? "−" : "±"}${Math.abs(d).toFixed(1)}%p`;
};
const ALPHA = 0.05;            // 유의수준
const GOAL_PP = 3;             // 설계 목표: 가장 강한 기준선 +3%p 이상, 통계적으로 유의
const SMALL_BIN = 30;          // 이보다 적은 경기가 든 신뢰도 구간은 "표본 적음"으로 적는다
/** 받침에 따라 을/를: "로지스틱 회귀를", "LightGBM을". 한글이 아니면 마지막 글자 소리로 어림한다. */
function eul(word) {
  const w = String(word ?? "");
  const c = w.at(-1) ?? "";
  const code = c.charCodeAt(0);
  if (code >= 0xac00 && code <= 0xd7a3) return `${w}${(code - 0xac00) % 28 ? "을" : "를"}`;
  return `${w}${/[0-9lmnLMN]$/.test(c) ? "을" : "를"}`; // LightGBM → 을 (엠)
}
const LIVE_SHORT = 30;         // 결과가 난 경기가 이보다 적으면 "아직 짧다"고 적는다
const signif = (p) => (fin(p) && Number(p) < ALPHA ? "통계적으로 유의함" : "통계적으로 유의하지 않음");

const ALGO = { lr: "로지스틱 회귀", lgbm: "LightGBM" };
const CALIB = { platt: "Platt", isotonic: "isotonic", none: "보정 없음" };
const BASELINES = [
  ["home_always", "항상 홈팀"],
  ["better_win_pct", "시즌 승률이 높은 팀"],
  ["lower_starter_era", "선발 ERA가 낮은 팀"],
];
const baseName = (key) => BASELINES.find(([k]) => k === key)?.[1] ?? key;
// starter_source 값(영문)을 화면 문구로. 모르는 값은 원문 그대로.
const STARTER_SOURCE = {
  "actual (boxscore pitching order 1)": "박스스코어의 실제 선발",
  "announced (schedule page)": "경기 전 예고 선발",
};
const starterText = (s) => STARTER_SOURCE[s] ?? s ?? "—";
const algoName = (key) => ALGO[key] ?? key ?? "—";
const GROUP = { batter: "타자", pitcher: "투수" };
const Z95 = 1.96;              // 95% 신뢰구간의 z값 (표본오차를 눈금에 함께 그리려고)

/** 이항 비율의 Wilson 95% 신뢰구간 [lo, hi] (p = 적중률 0~1, n = 경기 수). */
function wilson(p, n) {
  if (!fin(p) || !fin(n) || n <= 0) return null;
  const z2 = Z95 * Z95;
  const d = 1 + z2 / n;
  const c = (p + z2 / (2 * n)) / d;
  const h = (Z95 * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / d;
  return { lo: c - h, hi: c + h };
}
/** 퍼센트포인트 차이 숫자 → "+x.x" 꼴 (단위는 따로 붙인다). */
const signedPP = (d) => `${d > 0 ? "+" : d < 0 ? "−" : "±"}${Math.abs(d).toFixed(1)}`;

/** 홀드아웃 판정에 쓰는 값 묶음: 무대(장면)와 ① 카드가 같은 값을 쓴다. */
function holdoutFacts() {
  const r = state.report;
  const sel = r.selected;
  const m = r.models?.[sel]?.test ?? {};
  const base = r.baselines?.test ?? {};
  const sig = r.significance ?? {};
  const vsAcc = base[sig.vs];
  const diffNum = fin(m.accuracy) && fin(vsAcc) ? (m.accuracy - vsAcc) * 100 : null;
  const goalMet = diffNum !== null && diffNum >= GOAL_PP && fin(sig.mcnemar_p) && sig.mcnemar_p < ALPHA;
  return { r, sel, m, base, sig, vsAcc, diffNum, goalMet };
}

/** 라이브 기록 요약: 결과가 난 경기(FINAL + correct 0/1)만 센다. 취소·예정 경기는 뺀다. history를 못 읽었으면 null. */
function liveFacts() {
  const rows = state.history;
  if (!rows) return null;
  const decided = rows.filter((h) => h.status === "FINAL" && (h.correct === 0 || h.correct === 1));
  return { n: decided.length, c: decided.reduce((s, h) => s + h.correct, 0), all: rows.length };
}
const liveVersion = () => state.status?.model_version ?? state.history?.findLast?.((h) => h.model_version)?.model_version ?? "라이브";

function table(caption, cols, rows, cls = "") {
  return el("div", { class: "table-scroll" }, el("table", { class: `table ${cls}`.trim() }, [
    el("caption", { class: "sr-only" }, caption),
    el("thead", {}, el("tr", {}, cols.map(([t, c]) => el("th", { scope: "col", class: c ?? null }, t)))),
    el("tbody", {}, rows),
  ]));
}

// ---------- 읽기 ----------

const loadReport = () => settle(state, "report", fetchJSON("model_report.json"));
const loadHistory = () => settle(state, "history", fetchCSV("history.csv", { fresh: true }));

async function init() {
  renderNav("report.html");
  await Promise.all([loadReport(), loadHistory(), settle(state, "status", fetchJSON("status.json", { fresh: true }))]);
  renderFooter(state.status);
  renderReport();
  renderLive();
}

/** model_report.json으로 그리는 부분 전부(배지 + 카드 ①~⑤). 읽기 실패면 ①에 오류 상자 + 다시 불러오기. */
function renderReport() {
  renderBadges();
  renderStage();
  if (!state.report) {
    showError($("holdout-body"), state.errors.report, async () => { await loadReport(); renderReport(); renderLive(); });
    for (const id of ["calibration-body", "importance-body", "variants-body", "clusters-body"]) {
      $(id).replaceChildren(el("p", { class: "empty" }, "성적표 파일(model_report.json)을 불러오지 못해 비워 두었습니다."));
    }
    return;
  }
  renderHoldout();
  renderCalibration();
  renderImportance();
  renderVariants();
  renderClusters();
}

// ---------- 머리: "어느 모델, 어느 기간" 배지 ----------

/** 시즌 띠: 시즌마다 칸 하나, 역할(학습·검증·시험)에 따라 색. 글자 정보는 아래 범례가 담는다(띠는 aria-hidden). */
function seasonStrip(seasons, roleOf) {
  return el("ol", { class: "strip", "aria-hidden": "true" }, seasons.map((y) =>
    el("li", { class: `strip__cell strip__cell--${roleOf(y)}`, title: String(y) })));
}

function legendItem(role, text) {
  return el("li", {}, [el("span", { class: `dot strip-dot strip-dot--${role}`, "aria-hidden": "true" }), text]);
}

function renderBadges() {
  const box = $("model-badges");
  box.setAttribute("aria-busy", "false");
  const r = state.report ?? {};
  const train = r.train_seasons ?? [];
  const first = train[0];
  const all = [];
  if (fin(first) && fin(r.test_season)) for (let y = first; y <= r.test_season; y++) all.push(y);
  const role = (y) => (y === r.test_season ? "test" : y === r.val_season ? "val" : "train");
  const n = r.n ?? {};
  const report = !state.report ? el("div", { class: "badge" }, el("p", { class: "empty" }, "성적표 모델 정보(model_report.json)를 불러오지 못했습니다."))
  : el("div", { class: "badge" }, [
    el("div", { class: "badge__top" }, [
      el("span", { class: "pill pill--ink" }, r.model_version ?? "report"),
      el("span", { class: "badge__role" }, `이 성적표 · ${r.test_season ?? "시험 시즌"} 되감기`),
    ]),
    seasonStrip(all, role),
    el("ul", { class: "strip-legend" }, [
      legendItem("train", `학습 ${fmtRange(train)} (${fmtInt(n.train)}경기)`),
      legendItem("val", `검증 ${r.val_season ?? "—"} (${fmtInt(n.val)}경기)`),
      legendItem("test", `시험 ${r.test_season ?? "—"} (${fmtInt(n.test)}경기)`),
    ]),
    el("p", { class: "badge__note" }, `선발 피처: ${starterText(r.starter_source?.train_test)} · 만든 날 ${fmtKST(r.generated_at)}`),
  ]);
  // 라이브 모델: 같은 알고리즘·보정 방법을 첫 학습 시즌부터 시험 시즌까지 전부로 다시 학습한 모델
  const nLive = state.history?.length;
  const live = el("div", { class: "badge" }, [
    el("div", { class: "badge__top" }, [
      el("span", { class: "pill pill--ink" }, liveVersion()),
      el("span", { class: "badge__role" }, "매일 예측 · 라이브 기록"),
    ]),
    all.length ? seasonStrip([...all, "live"], (y) => (y === "live" ? "live" : "train")) : null,
    el("ul", { class: "strip-legend" }, [
      legendItem("train", all.length ? `학습 ${all[0]}~${all.at(-1)} (시험 시즌까지 전부)` : "학습 기간: 성적표 파일을 읽지 못해 표시하지 못함"),
      legendItem("live", `기록 history.csv ${fin(nLive) ? `${nLive}경기` : "—"}`),
    ]),
    state.report ? el("p", { class: "badge__note" }, `선발 피처: ${starterText(r.starter_source?.live)} · ${r.test_season}도 학습했으므로 아래 시험 성적은 ${r.model_version ?? "report"} 모델의 것입니다.`) : null,
  ]);
  box.replaceChildren(report, live);
}

// ---------- 판결 무대: 좋은 숫자(핑크) | 한계(틸) — 같은 크기로 마주 보게 ----------

/** 정확도 눈금: 모델과 기준선 3개의 정확도를 한 줄 눈금에 찍고, 모델의 95% 신뢰구간을 띠로 깐다.
 *  items = [{label, acc, kind: "model" | "base" | "primary"}]. 눈금은 값 범위만 확대한다(0%부터가 아님 — 위 글로 알린다). */
function accuracyRuler(host, items, ci, label) {
  host.classList.add("chart");
  host._chartRO?.disconnect();
  const lo = Math.floor((Math.min(...items.map((i) => i.acc), ci.lo) - 0.005) * 20) / 20;
  const hi = Math.ceil((Math.max(...items.map((i) => i.acc), ci.hi) + 0.005) * 20) / 20;
  const NS = "http://www.w3.org/2000/svg";
  const s = (tag, attrs = {}, text) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, String(v));
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const f = (v) => fmtPct(v, 1);
  let last = 0;
  const draw = () => {
    const W = Math.max(240, Math.round(host.clientWidth || 600));
    if (Math.abs(W - last) < 8) return;
    last = W;
    const x0 = 10, x1 = W - 10, T = 6, rowH = 54, AX = 30;
    const H = T + items.length * rowH + AX;
    const X = (v) => x0 + ((v - lo) / (hi - lo)) * (x1 - x0);
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", focusable: "false",
      "aria-label": `${label}: ${items.map((i) => `${i.label} ${f(i.acc)}`).join(", ")}. 모델의 95% 신뢰구간 ${f(ci.lo)}~${f(ci.hi)}` });
    for (let v = lo; v <= hi + 1e-9; v += 0.05) {
      const a = Math.abs(v - lo) < 1e-9 ? "start" : Math.abs(v - hi) < 1e-9 ? "end" : "middle";
      svg.append(s("line", { class: "c-grid", x1: X(v), x2: X(v), y1: T, y2: T + items.length * rowH }),
        s("text", { class: "c-axis", x: X(v), y: H - 8, "text-anchor": a }, fmtPct(v, 0)));
    }
    svg.append(s("rect", { x: X(ci.lo), y: T, width: X(ci.hi) - X(ci.lo), height: items.length * rowH, rx: 6,
      style: "fill: var(--ink)", "fill-opacity": 0.08 }));
    const model = items[0];
    svg.append(s("line", { class: "c-ref", x1: X(model.acc), x2: X(model.acc), y1: T, y2: T + items.length * rowH }));
    items.forEach((it, i) => {
      const y = T + i * rowH;
      const cy = y + 38;
      const tag = it.kind === "primary" ? (W >= 420 ? " · 비교 대상" : " *") : "";
      svg.append(
        s("text", { class: "c-label", x: x0, y: y + 18, style: it.kind === "model" ? "font-weight:600" : null }, `${it.label}${tag}`),
        s("text", { class: "c-value", x: x1, y: y + 18, "text-anchor": "end" }, f(it.acc)),
        s("line", { x1: x0, x2: x1, y1: cy, y2: cy, stroke: "currentColor", "stroke-opacity": 0.22, "stroke-width": 2 }),
      );
      if (it.kind === "model") {
        svg.append(s("line", { x1: X(ci.lo), x2: X(ci.hi), y1: cy, y2: cy, stroke: "var(--ink)", "stroke-width": 3 }),
          s("line", { x1: X(ci.lo), x2: X(ci.lo), y1: cy - 7, y2: cy + 7, stroke: "var(--ink)", "stroke-width": 3 }),
          s("line", { x1: X(ci.hi), x2: X(ci.hi), y1: cy - 7, y2: cy + 7, stroke: "var(--ink)", "stroke-width": 3 }),
          s("circle", { cx: X(it.acc), cy, r: 9, style: "fill: var(--ink)" }));
      } else {
        svg.append(s("circle", { cx: X(it.acc), cy, r: 7, "stroke-width": 2.5, stroke: "var(--ink)",
          style: `fill: ${it.kind === "primary" ? "var(--ochre)" : "var(--canvas)"}` }));
      }
    });
    const t = document.createElement("table");
    t.className = "sr-only";
    t.createCaption().textContent = `${label} (모델의 95% 신뢰구간 ${f(ci.lo)}~${f(ci.hi)})`;
    const hr = t.createTHead().insertRow();
    ["항목", "정확도"].forEach((h) => { const th = document.createElement("th"); th.scope = "col"; th.textContent = h; hr.append(th); });
    const tb = t.createTBody();
    items.forEach((it) => { const tr = tb.insertRow(); tr.insertCell().textContent = it.label; tr.insertCell().textContent = f(it.acc); });
    host.replaceChildren(svg, t);
  };
  draw();
  if (typeof ResizeObserver !== "undefined") {
    host._chartRO = new ResizeObserver(draw);
    host._chartRO.observe(host);
  }
  return { lo, hi };
}

function statRows(rows) {
  return el("ul", { class: "stat" }, rows.map(([k, v, w, tag]) => el("li", {}, [
    el("span", { class: "stat__k" }, [k, tag ? el("em", { class: "stat__tag" }, tag) : null]),
    el("span", { class: "stat__v num" }, v),
    w ? el("span", { class: "stat__w" }, w) : null,
  ])));
}

function renderStage() {
  const box = $("stage");
  box.setAttribute("aria-busy", "false");
  if (!state.report) {
    showError(box, state.errors.report, async () => { await loadReport(); renderReport(); renderLive(); });
    return;
  }
  const { r, sel, m, base, sig, diffNum, goalMet } = holdoutFacts();
  const season = r.test_season ?? "시험";
  const ok = fin(sig.mcnemar_p) && sig.mcnemar_p < ALPHA;
  const live = liveFacts();
  const calib = CALIB[r.models?.[sel]?.calibration] ?? r.models?.[sel]?.calibration;

  const top = el("div", { class: "stage__top" }, el("div", { class: "pills" }, [
    el("span", { class: "pill pill--ink" }, r.model_version ?? "report"),
    el("span", { class: "pill pill--white" }, `시험 ${season} 정규시즌 ${fmtInt(m.n)}경기`),
    el("span", { class: "pill pill--white" }, `${algoName(sel)}${calib ? ` + ${calib}` : ""}`),
    el("span", { class: "pill pill--white" }, `학습 ${fmtRange(r.train_seasons)} · 검증 ${r.val_season ?? "—"}`),
  ]));

  // 왼쪽(핑크): 좋은 숫자
  const goodHead = diffNum === null ? "비교하지 못했습니다" : diffNum > 0 ? "기준선보다 높습니다" : diffNum < 0 ? "기준선보다 낮습니다" : "기준선과 같습니다";
  const good = el("div", { class: "side side--good" }, [
    el("div", { class: "side__head" }, [
      el("p", { class: "side__role" }, "좋은 숫자"),
      el("h3", { class: "side__team" }, goodHead),
    ]),
    el("p", { class: "side__prob" }, [
      el("span", { class: "side__num" }, diffNum === null ? "—" : [signedPP(diffNum), el("small", {}, "%p")]),
      el("span", { class: "side__who" }, `${baseName(sig.vs)} 규칙보다`),
    ]),
    el("div", { class: "side__details" }, el("div", { class: "side__chip" }, [
      el("p", { class: "chip__row" }, [el("span", {}, ["선택 모델 정확도 ", el("b", { class: "num" }, fmtPct(m.accuracy, 1))]),
        el("span", { class: "chip__sub num" }, `적중 ${fmtInt(sig.model_correct)} / ${fmtInt(m.n)}경기`)]),
      statRows(BASELINES.map(([key, label]) => [label, `${pp(m.accuracy, base[key])}`, `규칙 정확도 ${fmtPct(base[key], 1)}`, key === sig.vs ? "미리 정한 비교 대상" : null])),
    ])),
  ]);

  // 오른쪽(틸): 한계
  const limitHead = signif(sig.mcnemar_p);
  const liveRow = !live ? ["라이브 기록", "—", "기록을 못 읽음"]
    : [`라이브 ${liveVersion()}`, `${fmtInt(live.c)} / ${fmtInt(live.n)}경기 적중`, live.n < LIVE_SHORT ? "표본 너무 적음" : "표본 쌓이는 중"];
  const limit = el("div", { class: "side side--limit" }, [
    el("div", { class: "side__head" }, [
      el("p", { class: "side__role" }, "한계"),
      el("h3", { class: "side__team" }, limitHead),
    ]),
    el("p", { class: "side__prob" }, [
      el("span", { class: "side__num" }, [el("small", { class: "num__pre" }, "p ="), pval(sig.mcnemar_p)]),
      el("span", { class: "side__who" }, "McNemar 검정, 같은 경기를 견줌"),
    ]),
    el("div", { class: "side__details" }, el("div", { class: "side__chip" }, [
      el("p", { class: "chip__row" }, [el("span", {}, ["유의수준 ", el("b", { class: "num" }, fmtRate3(ALPHA, 2))]),
        el("span", { class: "chip__sub" }, ok ? "비교 대상 기준 유의함" : "비교 대상 기준 우연과 구분 안 됨")]),
      statRows([
        ...BASELINES.map(([key, label]) => [label, `p = ${pval(sig.all?.[key]?.mcnemar_p)}`, signif(sig.all?.[key]?.mcnemar_p), key === sig.vs ? "미리 정한 비교 대상" : null]),
        liveRow,
      ]),
    ])),
  ]);

  // 아래 띠: 눈금 + 신뢰구간 + 설계 목표
  const ci = wilson(m.accuracy, m.n);
  const rulerHost = el("div");
  const ruler = el("div", { class: "stage__ruler" });
  if (ci && fin(m.accuracy)) {
    const items = [
      { label: `선택 모델 · ${algoName(sel)}`, acc: m.accuracy, kind: "model" },
      ...BASELINES.filter(([k]) => fin(base[k])).map(([k, label]) => ({ label, acc: base[k], kind: k === sig.vs ? "primary" : "base" })),
    ];
    const inside = BASELINES.filter(([k]) => fin(base[k]) && base[k] >= ci.lo && base[k] <= ci.hi).map(([, l]) => l);
    const outside = BASELINES.filter(([k]) => fin(base[k]) && (base[k] < ci.lo || base[k] > ci.hi)).map(([, l]) => l);
    ruler.append(
      el("div", { class: "ruler__main" }, [
        el("div", { class: "ruler__head" }, [
          el("p", { class: "ruler__title" }, `${season} 정확도 눈금`),
          el("p", { class: "ruler__sub" }, "눈금은 값이 모인 범위만 확대했습니다(0%부터가 아닙니다)."),
        ]),
        rulerHost,
        el("ul", { class: "ruler__legend" }, [
          el("li", {}, [el("span", { class: "key key--model", "aria-hidden": "true" }), "굵은 점과 선 = 모델 정확도와 95% 신뢰구간 ", el("b", { class: "num" }, `${fmtPct(ci.lo, 1)}~${fmtPct(ci.hi, 1)}`), ` (${fmtInt(m.n)}경기 기준)`]),
          el("li", {}, [el("span", { class: "key key--base", "aria-hidden": "true" }), "빈 점 = 규칙의 정확도, 노란 점(*) = 미리 정한 비교 대상"]),
        ]),
      ]),
      el("div", { class: "ruler__notes" }, [
        el("p", { class: "ruler__note" }, [
          el("b", {}, "이 구간 안의 규칙: "), inside.join(", ") || "없음",
          outside.length ? [el("b", {}, " · 밖의 규칙: "), outside.join(", ")] : null,
          inside.length ? ". 안에 든 규칙과의 차이는 표본오차 범위 안이라 모델이 낫다고 단정할 수 없습니다." : ". 모든 규칙이 구간 밖입니다.",
        ]),
        el("p", { class: "ruler__note" }, [
          el("b", {}, "설계 목표 "), `${baseName(sig.vs)} 규칙보다 +${GOAL_PP}%p 이상, 통계적으로 유의. `,
          goalMet ? "넘었습니다." : `아직 못 미칩니다.${fin(sig.mcnemar_p) && sig.mcnemar_p >= ALPHA ? ` 한 시즌 ${fmtInt(m.n)}경기로는 이 차이를 우연과 구분할 수 없습니다.` : ""}`,
          ` 비교 대상은 ${sig.selected_on === "val" ? `${r.val_season} 검증에서` : "미리"} 가장 강했던 규칙으로 정했습니다.`,
        ]),
        el("p", { class: "ruler__note" }, [
          el("b", {}, "라이브는 별개 "), live
            ? `라이브 ${liveVersion()} 모델은 결과가 난 ${fmtInt(live.n)}경기 중 ${fmtInt(live.c)}경기 적중. 표본이 너무 적어 위 ${season} 성적과 견줄 수 없습니다.`
            : "라이브 기록(history.csv)을 읽지 못해 적지 못했습니다.",
        ]),
      ]),
    );
  } else {
    ruler.append(el("p", { class: "empty" }, "정확도 눈금을 그릴 값이 없습니다."));
  }

  box.replaceChildren(el("article", { class: "stage", "aria-label": `${season} 홀드아웃: ${baseName(sig.vs)} 규칙보다 ${diffNum === null ? "—" : signedPP(diffNum)}%p, ${limitHead}` }, [
    top, good, limit, el("span", { class: "stage__vs", "aria-hidden": "true" }, "그러나"), ruler,
  ]));
  if (ci && fin(m.accuracy)) {
    accuracyRuler(rulerHost, [
      { label: `선택 모델 · ${algoName(sel)}`, acc: m.accuracy, kind: "model" },
      ...BASELINES.filter(([k]) => fin(base[k])).map(([k, label]) => ({ label, acc: base[k], kind: k === sig.vs ? "primary" : "base" })),
    ], ci, `${season} 시험 정확도`);
  }
}

// ---------- ① 2026 홀드아웃 표 ----------

function renderHoldout() {
  const { r, sel, m, base, sig } = holdoutFacts();
  const body = $("holdout-body");

  $("holdout-lead").textContent =
    `${r.test_season ?? "시험"} 정규시즌 ${fmtInt(m.n)}경기, 학습과 모델 선택에 쓰지 않은 시즌의 성적`;

  const modelRow = (key) => {
    const t = r.models?.[key]?.test ?? {};
    const on = key === sel;
    return el("tr", { class: on ? "is-selected" : null }, [
      el("th", { scope: "row" }, [
        `${algoName(key)} + ${CALIB[r.models?.[key]?.calibration] ?? r.models?.[key]?.calibration ?? "—"}`,
        on ? el("span", { class: "pill pill--sm pill--ink holdout__tag" }, "선택") : null,
      ]),
      el("td", { class: "num" }, fmtPct(t.accuracy, 1)),
      el("td", { class: "num" }, num(t.log_loss)),
      el("td", { class: "num" }, num(t.brier)),
      el("td", { class: "num" }, ""),
    ]);
  };
  const baseRow = ([key, label]) => el("tr", { class: "is-baseline" }, [
    el("th", { scope: "row" }, [
      `규칙: ${label}`,
      key === sig.vs ? el("span", { class: "pill pill--sm pill--ochre holdout__tag" }, "미리 정한 비교 대상") : null,
    ]),
    el("td", { class: "num" }, fmtPct(base[key], 1)),
    el("td", { class: "num muted" }, "—"),
    el("td", { class: "num muted" }, "—"),
    el("td", { class: "num" }, pval(sig.all?.[key]?.mcnemar_p)),
  ]);
  const order = [sel, ...Object.keys(r.models ?? {}).filter((k) => k !== sel)];

  body.replaceChildren(
    el("p", { class: "holdout__pointer" }, `선택 모델과 규칙의 차이·유의성은 위 판결 무대에 크게 있고, 아래 표는 같은 값을 log loss·Brier까지 함께 적은 것입니다. 비교 대상 규칙(${baseName(sig.vs)})은 ${sig.selected_on === "val" ? `${r.val_season} 검증에서` : "미리"} 가장 강했던 규칙으로 정했습니다.`),
    el("div", { class: "inset" }, table(
      `${r.test_season} 시험 성적: 모델 ${order.length}개와 규칙 3개`,
      [["모델 / 규칙"], ["정확도", "num"], ["log loss", "num"], ["Brier", "num"], ["p값", "num"]],
      [...order.map(modelRow), ...BASELINES.map(baseRow)],
      "holdout-table",
    )),
    el("ul", { class: "notes" }, [
      el("li", {}, `log loss와 Brier는 낮을수록 좋습니다. 알고리즘은 ${r.val_season} 검증 log loss가 낮은 ${eul(algoName(sel))} 골랐습니다. p값은 선택 모델과 각 규칙의 경기별 적중을 견준 McNemar 검정입니다.`),
      el("li", {}, `${r.test_season} 시즌은 어떤 학습·선택에도 쓰지 않았지만, 개발 중에 ${r.test_season} 지표를 한 번 확인했고 그 뒤 캘리브레이션 선택 절차를 바꿨습니다. 검증 시즌 안에서 보정기를 맞추고 같은 시즌으로 고르면 isotonic이 유리하게 편향되기 때문입니다.`),
      el("li", {}, `백테스트의 선발 피처는 ${starterText(r.starter_source?.train_test)}로 만들었습니다. 라이브는 ${starterText(r.starter_source?.live)}을 쓰므로, 예고와 실제가 다르면 라이브 성적은 이보다 낮을 수 있습니다.`),
    ]),
  );
}

// ---------- ② 신뢰도 곡선 ----------

function renderCalibration() {
  const bins = state.report.calibration_bins ?? [];
  const body = $("calibration-body");
  const chart = el("div", { class: "calibration__chart" });
  const label = (b) => `${Math.round(b.lo * 100)}~${Math.round(b.hi * 100)}%`;
  const notes = [];
  const focus = bins.find((b) => fin(b.lo) && Math.abs(b.lo - 0.4) < 1e-9 && fin(b.n) && b.n > 0 && fin(b.actual_rate));
  if (focus) {
    const gap = (focus.actual_rate - focus.pred_mean) * 100;
    const verdict = Math.abs(gap) < 3 ? "잘 맞습니다"
      : gap < 0 ? "약간 불리한 홈팀을 실제보다 후하게 봅니다" : "약간 불리한 홈팀을 실제보다 박하게 봅니다";
    notes.push(el("p", { class: "calibration__focus" }, [
      el("b", {}, `${label(focus)} 구간 ${fmtInt(focus.n)}경기`),
      `는 예측 평균 ${fmtPct(focus.pred_mean)}인데 실제 홈 승률은 ${fmtPct(focus.actual_rate)}입니다. ${verdict}.`,
    ]));
  }
  const small = bins.filter((b) => fin(b.n) && b.n > 0 && b.n < SMALL_BIN);
  if (small.length) {
    notes.push(el("p", { class: "card__foot" },
      `경기가 ${SMALL_BIN}경기 미만인 구간(${small.map((b) => `${label(b)} ${b.n}경기`).join(", ")})은 막대가 크게 흔들리므로 판단하기 어렵습니다.`));
  }
  body.replaceChildren(chart, ...notes);
  calibrationChart(chart, bins, { color: "ink" });
}

// ---------- ③ 피처 중요도 ----------

function renderImportance() {
  const r = state.report;
  const all = r.feature_importance ?? [];
  const top = all.slice(0, 10).map((f) => ({ ...f, label: FACTOR_LABELS[f.name] ?? f.label ?? f.name }));
  const how = r.selected === "lgbm" ? "LightGBM 분기 이득(gain)" : "로지스틱 회귀 표준화 계수의 크기";
  $("importance-lead").textContent = `${how}를 피처 ${all.length}개의 합이 100%가 되게 나눈 비중, 상위 10개`;
  const body = $("importance-body");
  // 차트는 패딩 없는 안쪽 div에 그린다(ResizeObserver가 이 div만 다시 그리므로 범례가 지워지지 않고, viewBox = 실제 너비)
  const chart = el("div");
  const legend = el("ul", { class: "chart-legend" }, [
    el("li", {}, [el("span", { class: "dot", style: { background: "var(--pink)" }, "aria-hidden": "true" }), "선발투수 피처"]),
    el("li", {}, [el("span", { class: "dot", style: { background: "var(--teal)" }, "aria-hidden": "true" }), "팀 피처"]),
  ]);
  legend.setAttribute("aria-hidden", "true"); // 막대 색의 뜻 — 표(sr-only)에는 이름이 그대로 있다
  const starters = top.filter((f) => f.name.startsWith("starter_")).length;
  body.replaceChildren(
    el("div", { class: "inset importance__chart" }, [chart, legend]),
    el("p", { class: "card__foot" },
      `상위 10개 중 ${starters}개가 선발투수 피처입니다. 비중은 크기만 뜻하고 방향(홈에 유리·불리)은 경기마다 다릅니다. 경기별 방향은 홈의 "승률을 가른 요인"에서 볼 수 있습니다.`),
  );
  barChart(chart, top, {
    valueKey: "importance", labelKey: "label", color: (f) => (f.name.startsWith("starter_") ? "pink" : "teal"),
    format: (v) => fmtPct(v, 1), label: "피처 중요도 상위 10개 (비중)",
  });
}

// ---------- ④ 변형 비교 ----------

function variantTable(caption, rows) {
  const cols = [["모델"], ["검증 정확도", "num"], ["시험 정확도", "num"], ["시험 log loss", "num"]];
  return el("div", { class: "inset" }, table(caption, cols, rows.map(([name, m, on]) => el("tr", { class: on ? "is-selected" : null }, [
    el("th", { scope: "row" }, name),
    el("td", { class: "num" }, fmtPct(m?.val?.accuracy, 1)),
    el("td", { class: "num" }, fmtPct(m?.test?.accuracy, 1)),
    el("td", { class: "num" }, num(m?.test?.log_loss)),
  ])), "variant-table"));
}

function renderVariants() {
  const r = state.report;
  const sel = r.models?.[r.selected] ?? {};
  const nAll = (r.feature_importance ?? []).length;
  const ns = r.ablation?.no_starter;
  const mf = r.matchup_feature_ablation;
  const blocks = [];
  if (ns) {
    blocks.push(el("div", { class: "variant" }, [
      el("h3", { class: "variant__title" }, "선발투수 피처를 빼면"),
      variantTable("선발 피처를 뺀 모델과 비교", [
        [`지금 모델 (피처 ${nAll}개)`, sel, true],
        [`선발 피처 제외 (${ns.n_features ?? "—"}개)`, ns, false],
      ]),
      el("p", { class: "variant__note" },
        `시험 정확도가 ${pp(sel.test?.accuracy, ns.test?.accuracy).replace(/^[+−±]/, "")} ${sel.test?.accuracy >= ns.test?.accuracy ? "낮아져" : "높아져"} ` +
        `${fmtPct(ns.test?.accuracy, 1)}가 됩니다.` +
        (fin(ns.test?.accuracy) && ns.test.accuracy < r.baselines?.test?.better_win_pct
          ? ` 시즌 승률 규칙(${fmtPct(r.baselines.test.better_win_pct, 1)})보다도 낮아, 성적의 큰 몫이 선발 정보에서 나옵니다.` : "")),
    ]));
  }
  if (mf) {
    const adopt = mf.adopt === true;
    blocks.push(el("div", { class: "variant" }, [
      el("div", { class: "variant__head" }, [
        el("h3", { class: "variant__title" }, "선수 유형 상성 피처를 더하면"),
        el("span", { class: `pill pill--sm ${adopt ? "pill--ink" : "pill--white"}` }, adopt ? "채택" : "채택 안 함"),
      ]),
      variantTable("유형 상성 피처를 더한 모델과 비교", [
        ["상성 피처 없이 (지금)", mf.without, !adopt],
        [`상성 피처 +${(mf.features_added ?? []).length}개`, mf.with, adopt],
      ]),
      el("p", { class: "variant__note" },
        `${adopt ? "검증 log loss가 좋아져 채택했습니다." : "검증 log loss가 좋아지지 않아 라이브 모델에 넣지 않았습니다."} ` +
        `시험에서 두 모델의 적중 차이는 McNemar p = ${pval(mf.mcnemar_p_test)}로 ${fin(mf.mcnemar_p_test) && mf.mcnemar_p_test < ALPHA ? "유의합니다" : "유의하지 않습니다"}.`),
      mf.validation_scope ? el("p", { class: "variant__scope" }, [el("b", {}, "비교 범위 "), mf.validation_scope]) : null,
    ]));
  }
  $("variants-body").replaceChildren(blocks.length ? el("div", { class: "variants" }, blocks)
    : el("p", { class: "empty" }, "변형 비교 결과가 없습니다."));
}

// ---------- ⑤ 선수 유형 품질 ----------

function clusterGroup(group, q) {
  const kRows = (q.k_table ?? []).map((row) => el("tr", { class: row.k === q.k ? "is-selected" : null }, [
    el("th", { scope: "row" }, [`K = ${row.k}`, row.k === q.k ? el("span", { class: "pill pill--sm pill--ink holdout__tag" }, "선택") : null]),
    el("td", { class: "num" }, fmtRate3(row.silhouette)),
    el("td", { class: "num" }, fmtRate3(row.retention)),
    el("td", { class: "num" }, fmtRate3(row.score)),
  ]));
  const chosen = (q.k_table ?? []).find((row) => row.k === q.k);
  const types = (q.types ?? []).map((t) => el("li", { class: "type" }, [
    el("span", { class: "pill type__pill" }, [
      el("span", { class: "dot", style: { background: `var(--${typeColor(group, t.id)})` }, "aria-hidden": "true" }),
      t.name, el("b", { class: "num" }, fmtInt(t.n)),
    ]),
    el("span", { class: "type__ex" }, (t.examples ?? []).join(", ") || "—"),
  ]));
  return el("div", { class: "inset cluster" }, [
    el("h3", { class: "cluster__title" }, [
      `${GROUP[group]} · K = ${q.k ?? "—"}`,
      el("span", { class: "cluster__sub" }, ` ${fmtInt(q.n_fit)}명으로 맞춤 (전체 ${fmtInt(q.n_all)}명)`),
    ]),
    table(`${GROUP[group]} K별 실루엣·유지율·점수`, [["K"], ["실루엣", "num"], ["유지율", "num"], ["점수", "num"]], kRows, "k-table"),
    el("p", { class: "cluster__stats" }, [
      `실루엣 ${fmtRate3(chosen?.silhouette)} · 유지율(전체 ${fmtInt(q.n_all)}명 기준) ${fmtRate3(q.retention)} · GMM 일치율 ${fmtRate3(q.gmm_agreement)}`,
      q.membership_method === "kmeans_softmax" ? " · 소속 확률은 GMM 대신 중심까지 거리로 계산" : "",
    ]),
    el("p", { class: "cluster__cap" }, "유형별 인원과 대표 선수"),
    el("ul", { class: "types" }, types),
  ]);
}

function renderClusters() {
  const cq = state.report.cluster_quality;
  const body = $("clusters-body");
  if (!cq) {
    body.replaceChildren(el("p", { class: "empty" }, "유형 모델 품질 정보가 없습니다."));
    return;
  }
  $("clusters-lead").textContent =
    `${cq.version ?? "유형 모델"}: ${fmtRange(cq.fit_seasons)} 선수-시즌 기록으로 맞춘 K-means. 점수 = 실루엣 + 연도 간 유지율이 가장 큰 K를 골랐습니다.`;
  const sil = ["batter", "pitcher"].map((g) => cq[g]?.k_table?.find((row) => row.k === cq[g]?.k)?.silhouette);
  body.replaceChildren(
    el("div", { class: "clusters" }, ["batter", "pitcher"].filter((g) => cq[g]).map((g) => clusterGroup(g, cq[g]))),
    el("ul", { class: "notes notes--on-dark" }, [
      el("li", {}, `실루엣이 타자 ${fmtRate3(sil[0], 2)}, 투수 ${fmtRate3(sil[1], 2)}로 낮습니다. 선수 분포는 연속적이고, 유형은 그 분포를 부드럽게 나눈 구분입니다. 유지율은 연속 두 시즌 모두 자격인 선수의 유형이 그대로인 비율입니다.`),
      cq.membership_note ? el("li", {}, cq.membership_note) : null,
    ]),
  );
}

// ---------- ⑥ 라이브 기록 ----------

function renderLive() {
  const body = $("live-body");
  const rows = state.history;
  if (!rows) {
    showError(body, state.errors.history, async () => { await loadHistory(); renderLive(); renderBadges(); });
    return;
  }
  if (!rows.length) {
    body.replaceChildren(el("p", { class: "empty" }, "아직 라이브 예측 기록이 없습니다. 첫 예측은 경기 날 아침에 올라옵니다."));
    return;
  }
  // 모델 버전별: 예측 경기 수, 결과가 난 경기(FINAL + correct 0/1), 적중, 정확도. log loss는 표본이 작아 적지 않는다.
  const versions = [...new Set(rows.map((h) => h.model_version ?? "—"))];
  const summary = versions.map((v) => {
    const mine = rows.filter((h) => (h.model_version ?? "—") === v);
    const decided = mine.filter((h) => h.status === "FINAL" && (h.correct === 0 || h.correct === 1));
    const correct = decided.reduce((s, h) => s + h.correct, 0);
    return el("tr", {}, [
      el("th", { scope: "row" }, v),
      el("td", { class: "num" }, fmtInt(mine.length)),
      el("td", { class: "num" }, fmtInt(decided.length)),
      el("td", { class: "num" }, fmtInt(correct)),
      el("td", { class: "num" }, decided.length ? fmtPct(correct / decided.length, 1) : "—"),
    ]);
  });
  const first = rows.map((h) => h.date).filter(Boolean).sort()[0];
  const nDecided = rows.filter((h) => h.status === "FINAL" && (h.correct === 0 || h.correct === 1)).length;
  const full = [...rows].reverse().map((h) => el("tr", {}, [
    el("td", { class: "nowrap" }, fmtDate(h.date)),
    el("td", { class: "nowrap" }, `${teamName(h.away)} vs ${teamName(h.home)}`),
    el("td", { class: "num" }, fmtPct(h.home_win_prob, 1)),
    el("td", {}, h.model_version ?? "—"),
    el("td", { class: "nowrap" }, fmtKST(h.predicted_at)),
    el("td", { class: "nowrap" }, winnerText(h)),
    el("td", { class: "r" }, verdictPill(h)),
  ]));
  body.replaceChildren(
    el("div", { class: "live" }, [
      el("div", { class: "live__copy" }, [
        el("p", {}, `라이브 기록은 ${fmtDate(first)}, ${first ? first.slice(0, 4) : ""} 포스트시즌부터 쌓기 시작했습니다. ` +
          (nDecided < LIVE_SHORT
            ? `결과가 난 경기가 아직 ${fmtInt(nDecided)}경기라 위의 ${state.report?.test_season ?? "시험"} 성적과 견주기에는 너무 짧습니다.`
            : `지금까지 결과가 난 경기는 ${fmtInt(nDecided)}경기입니다.`)),
        el("p", { class: "card__foot" }, "모델 버전이 바뀌면 줄을 나눠 셉니다. '결과'는 결과가 나온 경기 수(무승부 제외)이고, 확률 50% 이상인 쪽을 고른 것으로 봅니다. 표본이 작아 정확도만 적고 log loss는 적지 않습니다."),
      ]),
      el("div", { class: "inset live__summary" }, table("모델 버전별 라이브 기록",
        [["모델"], ["예측", "num"], ["결과", "num"], ["적중", "num"], ["정확도", "num"]], summary, "live-table")),
    ]),
    el("details", { class: "live__all" }, [
      el("summary", {}, `전체 기록 보기 (${fmtInt(rows.length)}경기)`),
      el("div", { class: "inset" }, table("라이브 예측 전체 기록 (최근 순)",
        [["날짜"], ["대진 (원정 vs 홈)"], ["홈 승률", "num"], ["모델"], ["예측 시각"], ["결과"], ["적중", "r"]], full, "live-full")),
    ]),
  );
}

init();
