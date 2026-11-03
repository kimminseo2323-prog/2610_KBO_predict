// KBO Predict — 모델 성적표. report.html 전용 모듈.
//
// 화면 순서: 머리(#model-badges: "어느 모델, 어느 기간" 배지 2개) → 벤토 6장 → 푸터 증거 바.
//   벤토 section id: #holdout(크림) #calibration(라벤더) #importance(피치) #variants(오커) #cluster-quality(틸) #live-record(크림)
//
// 숫자는 모두 실행할 때 model_report.json(report-2026, 고정 파일)과 history.csv(라이브 기록)에서 읽는다.
// 이 파일에 적힌 숫자는 설명 문구의 규칙값(유의수준 0.05, 설계 목표 +3%p, 표본 30경기)뿐이다.
// 데이터 키는 docs/site/data-contract.md 매핑 표(페이지 "성적표")에 적은 것만 쓴다.
// 요인 이름: 데이터의 키를 app.js의 FACTOR_LABELS(파이썬과 테스트로 고정)로 확인하고, 화면에는 FACTOR_DISPLAY의 쉬운 이름과 풀이를 쓴다.

import {
  FACTOR_LABELS, el, fetchJSON, fetchCSV, settle, fin, fmtPct, fmtRate3, fmtInt, fmtRange, fmtDate, fmtKST,
  teamName, typeColor, verdictPill, winnerText, renderNav, renderFooter, showError, factorLabel, factorHelp, membershipText,
} from "./app.js";
import { barChart, calibrationChart, enableTips, lineChart } from "./charts.js";

const $ = (id) => document.getElementById(id);

const state = { report: null, history: null, status: null, backtest: null, tuning: null, grid: null, automl: null, errors: {} };

// ---------- 작은 도우미 ----------

/** 소수 d자리. 값이 없으면 "—". */
const num = (v, d = 3) => (fin(v) ? Number(v).toFixed(d) : "—");
/** p값: 0.001 미만은 "< .001", 그 밖은 ".046". */
const pval = (p) => (!fin(p) ? "—" : Number(p) < 0.001 ? "<.001" : fmtRate3(p));
// 문장 속 p값: 0.001 미만이면 "p < .001", 아니면 "p = 0.xxx" 꼴 ("p = < .001"처럼 기호가 겹치지 않게).
const pText = (p) => (!fin(p) ? "p = —" : Number(p) < 0.001 ? "p < .001" : `p = ${fmtRate3(p)}`);
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
const isSig = (p) => fin(p) && Number(p) < ALPHA;
/** 짧은 판정 (표·칸용). 통계적으로 유의 = 우연으로 보기 어렵다. */
const signif = (p) => (isSig(p) ? "우연으로 보기 어려움" : "우연과 구분 안 됨");
/** 받침에 따라 로/으로 (숫자 끝 글자를 읽는 소리 기준: 0 영, 1 일, 3 삼, 6 육, 7 칠, 8 팔은 받침). */
const ro = (s) => `${s}${/[013678]$/.test(String(s)) ? "으로" : "로"}`;

const ALGO = { lr: "로지스틱 회귀", lgbm: "LightGBM" };
const CALIB = { platt: "Platt", isotonic: "계단식(isotonic)", none: "없음" };
/** 표의 모델 이름: "로지스틱 회귀 (보정 없음)", "LightGBM (보정: Platt)". */
const modelName = (key, calib) => `${algoName(key)} (${!calib || calib === "none" ? "보정 없음" : `보정: ${CALIB[calib] ?? calib}`})`;
// 간단한 규칙 3개 (홈 화면 "모델은 얼마나 맞나"와 같은 이름). 선발 평균자책점은 작년 + 올해 합산(starter_era_diff).
const BASELINES = [
  ["home_always", "무조건 홈팀"],
  ["better_win_pct", "시즌 승률이 높은 팀"],
  ["lower_starter_era", "선발 평균자책점이 낮은 팀"],
];
const baseName = (key) => BASELINES.find(([k]) => k === key)?.[1] ?? key;
// starter_source 값(영문)을 화면 문구로. 모르는 값은 원문 그대로.
const STARTER_SOURCE = {
  "actual (boxscore pitching order 1)": "그 경기에 실제로 던진 선발",
  "announced (schedule page)": "경기 전에 발표된 예고 선발",
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
const liveVersion = () => state.status?.model_version ?? state.history?.findLast?.((h) => h.model_version)?.model_version ?? "—";

// ---------- 여러 시즌 시험 (backtest_report.json) ----------

const BT_RULE = "lower_starter_era";  // 2026 성적표와 같은 비교 대상 규칙 (선발 평균자책점이 낮은 팀)

function renderBacktest() {
  const body = $("backtest-body");
  const b = state.backtest;
  if (!b) {
    showError(body, state.errors.backtest, async () => { await settle(state, "backtest", fetchJSON("backtest_report.json")); renderBacktest(); });
    return;
  }
  const all = b.pooled.all, clean = b.pooled.clean, pick = b.chosen;
  const ruleAll = all[`rule_${BT_RULE}`].accuracy;
  const t = all.tests[pick];
  const seasons = Object.keys(b.by_season).sort();
  $("backtest-lead").textContent = `한 시즌(약 700경기)만으로는 작은 차이를 가려내기 어렵습니다. 그래서 시즌마다 그보다 앞선 시즌들로만 배운 모델로 ${seasons[0]}~${seasons.at(-1)} 시즌 ${fmtInt(all.n)}경기를 예측했습니다.`;
  const kpi = (big, small, lead = false) => el("div", { class: `bt-kpi${lead ? " bt-kpi--lead" : ""}` }, [el("b", {}, big), el("span", {}, small)]);
  const diff = (all[pick].accuracy - ruleAll) * 100;
  const head = el("div", { class: "bt-head" }, [
    kpi(fmtPct(all[pick].accuracy, 1), `지금 모델(${b.candidates[pick].label})의 적중률`, true),
    kpi(`+${diff.toFixed(1)}%p`, `'${baseName(BT_RULE)}' 규칙(${fmtPct(ruleAll, 1)})보다`),
    kpi(pText(t[`mcnemar_p_vs_rule_${BT_RULE}`]), Number(t[`mcnemar_p_vs_rule_${BT_RULE}`]) < ALPHA ? "우연으로 보기 어려운 차이입니다" : "우연과 구분되지 않습니다"),
  ]);
  // 시즌별 적중률: 지금 모델(잉크), 예전 모델(회색 점선), 규칙(노랑)
  const chart = el("div", { class: "bt-chart" });
  const pts = (key) => seasons.map((s) => ({ x: s, y: key.startsWith("rule_") ? b.by_season[s][key].accuracy : b.by_season[s][key]?.accuracy }));
  const series = [
    { name: b.candidates[pick].label, short: "지금 모델", legend: `지금 모델: ${b.candidates[pick].label}`, color: "ink", points: pts(pick) },
    { name: b.candidates.current.label, short: "예전 모델", legend: `예전 모델: ${b.candidates.current.label}`, color: "#8d929a", dash: true, points: pts("current") },
    { name: baseName(BT_RULE), short: "규칙", legend: `규칙: ${baseName(BT_RULE)}`, color: "ochre", points: pts(`rule_${BT_RULE}`) },
  ];
  const rows = Object.keys(b.candidates).map((n) => {
    const tt = all.tests[n];
    return el("tr", { class: n === pick ? "is-chosen" : null }, [
      el("th", { scope: "row" }, [b.candidates[n].label, n === pick ? el("span", { class: "pill pill--sm pill--ink holdout__tag" }, "지금 모델") : n === "current" ? el("span", { class: "pill pill--sm pill--muted holdout__tag" }, "예전 v0.2") : null]),
      el("td", { class: "num" }, fmtPct(all[n].accuracy, 1)),
      el("td", { class: "num" }, fmtPct(clean[n].accuracy, 1)),
      el("td", { class: "num" }, fmtPct(b.pooled.test[n].accuracy, 1)),
      el("td", { class: "num" }, n === "current" ? "—" : pval(tt.mcnemar_p_vs_current)),
    ]);
  });
  rows.push(el("tr", { class: "is-baseline" }, [el("th", { scope: "row" }, `규칙: ${baseName(BT_RULE)}`),
    el("td", { class: "num" }, fmtPct(ruleAll, 1)), el("td", { class: "num" }, fmtPct(clean[`rule_${BT_RULE}`].accuracy, 1)),
    el("td", { class: "num" }, fmtPct(b.pooled.test[`rule_${BT_RULE}`].accuracy, 1)), el("td", { class: "num muted" }, "—")]));
  body.replaceChildren(
    head, chart,
    el("div", { class: "inset bt-table" }, table(`여러 시즌 시험: 후보 ${Object.keys(b.candidates).length}개와 규칙`,
      [["후보"], [`${seasons[0]}~${seasons.at(-1)}`, "num"], ["설정 고를 때 안 쓴 시즌", "num"], [`${b.pooled.test.seasons[0]}만`, "num"], ["예전 모델과 비교한 p값", "num"]],
      rows, "holdout-table")),
    el("details", { class: "more" }, [el("summary", {}, "이 시험, 믿어도 될까요?"), el("ul", {}, [
      el("li", {}, `각 시즌은 그 시즌보다 앞선 기록으로만 배운 모델이 예측했습니다. 미래 경기를 본 모델은 없습니다.`),
      el("li", {}, `어느 후보를 쓸지는 계산하기 전에 정한 규칙으로 골랐습니다. ${b.protocol.dev_seasons[0]}~${b.protocol.dev_seasons.at(-1)} 시즌의 확률 오차(log loss)가 가장 작은 후보를 씁니다. ${b.pooled.test.seasons[0]} 시즌은 고른 뒤 채점만 했습니다.`),
      el("li", {}, `L1 모델과 앙상블의 설정은 2021~2025 시즌으로 골랐습니다. 그래서 그 시즌 성적은 조금 유리합니다. 어떤 설정을 고를 때도 쓰지 않은 시즌(${clean.seasons.join(", ")})만 모은 열을 따로 적었습니다.`),
      el("li", {}, `이 시험은 예전 모델의 ${b.pooled.test.seasons[0]} 한 시즌 결과(그때는 통계적으로 유의하지 않음)를 본 뒤에 더한 것입니다. 숨기지 않으려고 성적표 맨 위의 한 시즌 결과도 그대로 보여 줍니다.`),
      el("li", {}, `Elo 전력 점수: 경기 결과로 팀 점수를 매 경기 고칩니다(한 경기 ${b.protocol.elo.k}점 비중, 홈 +${b.protocol.elo.home}점, 새 시즌엔 평균 쪽으로 1/3 되돌림). 이 값들은 미리 정했고 성적을 보며 바꾸지 않았습니다.`),
    ])]),
  );
  lineChart(chart, series, { yFormat: (v) => fmtPct(v, 0), height: 260, endLabels: true, label: "시즌별 적중률: 지금 모델, 예전 모델, 규칙" });
}

// ---------- 더 나은 모델은 없었나 (tuning_report · tuning_grid_report · automl_report) ----------

const FAMILY_KO = { logreg: "로지스틱 회귀", random_forest: "랜덤포레스트", extra_trees: "엑스트라 트리", hist_gb: "히스토그램 부스팅",
  lightgbm: "LightGBM", xgboost: "XGBoost", lrl1: "로지스틱 회귀 L1", lrl2: "로지스틱 회귀 L2", rf: "랜덤포레스트", lgbm: "LightGBM",
  extra_tree: "엑스트라 트리", kneighbor: "k-최근접 이웃" };
const famName = (f, params) => `${FAMILY_KO[f] ?? f}${f === "logreg" && params?.penalty ? ` ${String(params.penalty).toUpperCase()}` : ""}`;

function renderSearch() {
  const body = $("search-body");
  const { tuning: rnd, grid, automl: auto } = state;
  if (!rnd || !grid || !auto) {
    body.replaceChildren(el("p", { class: "empty" }, "모델 찾기 결과를 불러오지 못했습니다."));
    return;
  }
  const sum = (o) => Object.values(o ?? {}).reduce((s, v) => s + Number(v), 0);
  const step = (big, name, pickText) => el("li", {}, [el("b", {}, big), el("span", { class: "step__name" }, name), el("span", { class: "step__pick" }, pickText)]);
  const rr = rnd.recommended, gr = grid.recommended;
  const steps = el("ul", { class: "search-steps" }, [
    step(`${fmtInt(sum(rnd.n_configs))}개`, "랜덤 서치 (알고리즘 6가지)", `고른 것: ${famName(rr.family, rr.params)}${rr.params?.C ? ` C=${rr.params.C}` : ""}`),
    step(`${fmtInt(sum(grid.n_configs))}개`, "그리드 서치 (같은 범위 전부)", `고른 것: ${famName(gr.family, gr.params)}`),
    step(`${Math.round(auto.search.time_budget_sec / 60)}분`, `오토머신러닝 (알고리즘 ${auto.protocol.estimators.length}가지)`, `고른 것: ${famName(auto.search.best_estimator)}${auto.search.best_config?.C ? ` C=${Number(auto.search.best_config.C).toFixed(3)}` : ""}`),
  ]);
  const row = (name, f) => el("tr", {}, [el("th", { scope: "row" }, name), el("td", { class: "num" }, fmtPct(f.test.accuracy, 1)), el("td", { class: "num" }, num(f.test.log_loss))]);
  const sub = (main, s) => [main, el("span", { class: "th-sub" }, s)];
  body.replaceChildren(
    steps,
    el("div", { class: "inset search-table" }, table("세 가지 방법이 고른 모델의 2026 시험 성적 (요인 26개, Elo 없음)",
      [["방법과 고른 모델"], ["2026 적중률", "num"], [sub("확률 오차", "log loss"), "num"]],
      [row(`랜덤 서치: ${famName(rr.family, rr.params)}`, rnd.finalists[0]), row(`그리드 서치: ${famName(gr.family, gr.params)}`, grid.finalists[0]),
        row(`오토머신러닝: ${famName(auto.search.best_estimator)}`, auto.automl_final), row("예전 모델 v0.2", grid.current)], "holdout-table")),
    el("p", { class: "search__verdict" }, "세 방법의 성적은 서로 비슷했고, 랜덤 서치와 오토머신러닝이 따로 같은 답(L1 로지스틱 회귀, C 약 0.03)을 골랐습니다. 그 설정에 Elo 전력 점수를 더한 것이 지금 모델(v0.3)입니다."),
    el("details", { class: "more" }, [el("summary", {}, "세 방법의 차이"), el("ul", {}, [
      el("li", {}, "랜덤 서치: 정해 둔 값 범위에서 알고리즘마다 설정 40개를 무작위로 뽑아 2021~2025 시즌으로 채점했습니다(로지스틱 회귀는 14개 전부)."),
      el("li", {}, "그리드 서치: 같은 범위의 조합을 하나도 빼지 않고 모두 채점했습니다. 랜덤 서치가 놓친 더 좋은 설정이 있는지 확인하려는 것입니다."),
      el("li", {}, "오토머신러닝(FLAML): 사람이 정한 범위 밖까지 알고리즘과 설정을 스스로 찾게 했습니다. 2025 시즌 점수를 직접 보며 골랐기 때문에 그 점수는 실제보다 좋게 나오기 쉬워, 비교는 2026 시험 점수로 합니다."),
      el("li", {}, "세 방법 모두 2026 시즌은 고르는 데 쓰지 않았습니다. 이 표는 Elo를 넣기 전(요인 26개) 결과입니다."),
    ])]),
  );
}

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
  await Promise.all([loadReport(), loadHistory(), settle(state, "status", fetchJSON("status.json", { fresh: true })),
    settle(state, "backtest", fetchJSON("backtest_report.json")), settle(state, "tuning", fetchJSON("tuning_report.json")),
    settle(state, "grid", fetchJSON("tuning_grid_report.json")), settle(state, "automl", fetchJSON("automl_report.json"))]);
  renderFooter(state.status);
  renderReport();
  renderLive();
  renderBacktest();
  renderSearch();
  bindGlossary();
}

/** "용어 풀이" 링크(#glossary)를 누르거나 주소에 #glossary가 있으면 접힌 용어 풀이를 연다. */
function bindGlossary() {
  const box = $("glossary");
  if (!box) return;
  const open = () => { if (location.hash === "#glossary") box.open = true; };
  window.addEventListener("hashchange", open);
  document.querySelectorAll('a[href="#glossary"]').forEach((a) => a.addEventListener("click", () => { box.open = true; }));
  open();
}

/** model_report.json으로 그리는 부분 전부(배지 + 카드 ①~⑤). 읽기 실패면 ①에 오류 상자 + 다시 불러오기. */
function renderReport() {
  renderBadges();
  renderStage();
  if (!state.report) {
    showError($("holdout-body"), state.errors.report, async () => { await loadReport(); renderReport(); renderLive(); });
    for (const id of ["calibration-body", "importance-body", "variants-body", "clusters-body"]) {
      $(id).replaceChildren(el("p", { class: "empty" }, "성적표 데이터를 불러오지 못해 비워 두었습니다."));
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
  const report = !state.report ? el("div", { class: "badge" }, el("p", { class: "empty" }, "성적표 모델 정보를 불러오지 못했습니다."))
  : el("div", { class: "badge" }, [
    el("div", { class: "badge__top" }, [
      el("span", { class: "pill pill--ink", title: "이 성적표를 만든 모델의 버전 이름입니다" }, r.model_version ?? "report"),
      el("span", { class: "badge__role" }, `성적표용 모델, ${r.test_season ?? "시험"} 시즌으로 시험`),
    ]),
    seasonStrip(all, role),
    el("ul", { class: "strip-legend" }, [
      legendItem("train", `학습 ${fmtRange(train)} (${fmtInt(n.train)}경기)`),
      legendItem("val", `모델 고르기 ${r.val_season ?? "—"} (${fmtInt(n.val)}경기)`),
      legendItem("test", `시험 ${r.test_season ?? "—"} (${fmtInt(n.test)}경기)`),
    ]),
    el("p", { class: "badge__note" }, `선발 정보: ${starterText(r.starter_source?.train_test)} 기준입니다. ${fmtKST(r.generated_at)}에 만들었습니다.`),
  ]);
  // 라이브 모델: 같은 알고리즘·보정 방법을 첫 학습 시즌부터 시험 시즌까지 전부로 다시 학습한 모델
  const nLive = state.history?.length;
  const live = el("div", { class: "badge" }, [
    el("div", { class: "badge__top" }, [
      el("span", { class: "pill pill--ink", title: "매일 예측하는 모델의 버전 이름입니다" }, liveVersion()),
      el("span", { class: "badge__role" }, "매일 예측 모델, 매일 경기 전에 올리는 예측"),
    ]),
    all.length ? seasonStrip([...all, "live"], (y) => (y === "live" ? "live" : "train")) : null,
    el("ul", { class: "strip-legend" }, [
      legendItem("train", all.length ? `학습 ${all[0]}~${all.at(-1)} (시험 시즌까지 모두)` : "학습 기간: 성적표 데이터를 읽지 못해 표시하지 못했습니다"),
      legendItem("live", `지금까지 예측 ${fin(nLive) ? `${nLive}경기` : "—"}`),
    ]),
    state.report ? el("p", { class: "badge__note" }, `선발 정보: ${starterText(r.starter_source?.live)} 기준입니다. 이 모델은 ${r.test_season} 시즌도 배웠기 때문에, 아래 시험 성적은 성적표용 모델(${r.model_version ?? "report"})의 성적입니다.`) : null,
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
      "aria-label": `${label}: ${items.map((i) => `${i.label} ${f(i.acc)}`).join(", ")}. 모델의 오차 범위(95% 신뢰구간) ${f(ci.lo)}~${f(ci.hi)}` });
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
      const tag = it.kind === "primary" ? (W >= 420 ? " (비교 상대)" : " *") : "";
      svg.append(
        s("rect", { x: 0, y, width: W, height: rowH, fill: "transparent", "data-tip": `${it.label}
적중률 ${f(it.acc)}${it.kind === "model" ? `
오차 범위 ${f(ci.lo)}~${f(ci.hi)}` : ""}` }),
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
    t.createCaption().textContent = `${label} (모델의 오차 범위 ${f(ci.lo)}~${f(ci.hi)})`;
    const hr = t.createTHead().insertRow();
    ["항목", "적중률"].forEach((h) => { const th = document.createElement("th"); th.scope = "col"; th.textContent = h; hr.append(th); });
    const tb = t.createTBody();
    items.forEach((it) => { const tr = tb.insertRow(); tr.insertCell().textContent = it.label; tr.insertCell().textContent = f(it.acc); });
    host.replaceChildren(svg, t);
    enableTips(svg);
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

  const calibOn = calib && r.models?.[sel]?.calibration !== "none";
  const top = el("p", { class: "stage__top stage__caption" }, [
    `${season} 정규시즌 ${fmtInt(m.n)}경기로 시험했습니다. ${fmtRange(r.train_seasons)} 시즌으로 배우고, ${r.val_season ?? "—"} 시즌으로 모델을 골랐습니다. `,
    `모델은 ${algoName(sel)}${calibOn ? `이고, 확률 보정(${calib})을 한 번 더 거쳤습니다.` : "입니다."}`,
  ]);

  // 왼쪽(핑크): 잘한 점
  const goodHead = diffNum === null ? "비교하지 못했습니다" : diffNum > 0 ? "간단한 규칙보다 높습니다" : diffNum < 0 ? "간단한 규칙보다 낮습니다" : "간단한 규칙과 같습니다";
  const good = el("div", { class: "side side--good" }, [
    el("div", { class: "side__head" }, [
      el("p", { class: "side__role" }, "잘한 점"),
      el("h3", { class: "side__team" }, goodHead),
    ]),
    el("p", { class: "side__prob" }, [
      el("span", { class: "side__num" }, diffNum === null ? "—" : [signedPP(diffNum), el("small", {}, "%p")]),
      el("span", { class: "side__who" }, `'${baseName(sig.vs)}' 규칙보다`),
    ]),
    el("div", { class: "side__details" }, el("div", { class: "side__chip" }, [
      el("p", { class: "chip__row" }, [el("span", {}, ["이 모델 적중률 ", el("b", { class: "num" }, fmtPct(m.accuracy, 1))]),
        el("span", { class: "chip__sub num" }, `${fmtInt(m.n)}경기 중 ${fmtInt(sig.model_correct)}경기 적중`)]),
      statRows(BASELINES.map(([key, label]) => [label, `${pp(m.accuracy, base[key])}`, `규칙 적중률 ${fmtPct(base[key], 1)}`, key === sig.vs ? "미리 정한 비교 상대" : null])),
    ])),
  ]);

  // 오른쪽(틸): 한계 (유의하면 검증 결과)
  const limitHead = ok ? "우연으로 보기 어렵습니다" : "아직 우연과 구분되지 않습니다";
  const liveRow = !live ? ["매일 예측 기록", "—", "기록을 읽지 못함"]
    : [`매일 예측 ${liveVersion()}`, `${fmtInt(live.n)}경기 중 ${fmtInt(live.c)}경기 적중`, live.n < LIVE_SHORT ? "경기 수가 너무 적음" : "경기 수를 쌓는 중"];
  const limit = el("div", { class: "side side--limit" }, [
    el("div", { class: "side__head" }, [
      el("p", { class: "side__role" }, ok ? "검증" : "한계"),  // 유의하면 "한계"가 아니라 검증 결과
      el("h3", { class: "side__team" }, limitHead),
    ]),
    el("p", { class: "side__prob" }, [
      el("span", { class: "side__num" }, [el("small", { class: "num__pre" }, fin(sig.mcnemar_p) && sig.mcnemar_p < 0.001 ? "p <" : "p ="),
        fin(sig.mcnemar_p) && sig.mcnemar_p < 0.001 ? ".001" : pval(sig.mcnemar_p)]),
      el("span", { class: "side__who" }, `같은 ${fmtInt(m.n)}경기에서 짝지어 비교 (McNemar 검정)`),
    ]),
    el("div", { class: "side__details" }, el("div", { class: "side__chip" }, [
      el("p", { class: "chip__row" }, [el("span", {}, ["판정 기준 p < ", el("b", { class: "num" }, fmtRate3(ALPHA, 2))]),
        el("span", { class: "chip__sub" }, ok ? "비교 상대와의 차이는 우연이 아닙니다 (통계적으로 유의함)" : "비교 상대와의 차이는 아직 우연과 구분되지 않습니다 (통계적으로 유의하지 않음)")]),
      statRows([
        ...BASELINES.map(([key, label]) => [label, pText(sig.all?.[key]?.mcnemar_p), signif(sig.all?.[key]?.mcnemar_p), key === sig.vs ? "미리 정한 비교 상대" : null]),
        liveRow,
      ]),
    ])),
  ]);

  // 아래 띠: 눈금 + 오차 범위(신뢰구간) + 처음 세운 목표
  const ci = wilson(m.accuracy, m.n);
  const rulerHost = el("div");
  const ruler = el("div", { class: "stage__ruler" });
  if (ci && fin(m.accuracy)) {
    const items = [
      { label: `이 모델 (${algoName(sel)})`, acc: m.accuracy, kind: "model" },
      ...BASELINES.filter(([k]) => fin(base[k])).map(([k, label]) => ({ label, acc: base[k], kind: k === sig.vs ? "primary" : "base" })),
    ];
    const inside = BASELINES.filter(([k]) => fin(base[k]) && base[k] >= ci.lo && base[k] <= ci.hi).map(([, l]) => l);
    const outside = BASELINES.filter(([k]) => fin(base[k]) && (base[k] < ci.lo || base[k] > ci.hi)).map(([, l]) => l);
    ruler.append(
      el("div", { class: "ruler__main" }, [
        el("div", { class: "ruler__head" }, [
          el("p", { class: "ruler__title" }, `${season} 적중률 비교`),
          el("p", { class: "ruler__sub" }, "눈금은 값이 모인 범위만 확대했습니다(0%부터가 아닙니다)."),
        ]),
        rulerHost,
        el("ul", { class: "ruler__legend" }, [
          el("li", {}, [el("span", { class: "key key--model", "aria-hidden": "true" }), "굵은 점과 선: 모델 적중률과 오차 범위 ", el("b", { class: "num" }, `${fmtPct(ci.lo, 1)}~${fmtPct(ci.hi, 1)}`), ` (${fmtInt(m.n)}경기 기준)`]),
          el("li", {}, [el("span", { class: "key key--base", "aria-hidden": "true" }), "빈 점: 규칙의 적중률입니다. 노란 점(*): 미리 정한 비교 상대입니다."]),
        ]),
      ]),
      el("details", { class: "more ruler__notes" }, [el("summary", {}, "이 눈금 읽는 법"),
        // 오차 범위 밖이라고 "확실히 낫다"는 뜻은 아니다: 우연과 구분되는지는 p값으로 따로 본다 (예: 범위 밖인데 p ≥ 0.05인 규칙)
        el("p", { class: "ruler__note" }, inside.length ? [
          el("b", {}, "오차 범위 안에 든 규칙: "), `${inside.join(", ")}. 이 규칙과의 차이는 경기 수가 적어 생기는 흔들림 안이라, 모델이 더 낫다고 단정할 수 없습니다.`,
          ...(outside.length ? [" ", el("b", {}, "범위 밖 규칙: "), `${outside.join(", ")}. 범위 밖이어도 우연과 구분되는지는 위 p값으로 따로 봐야 합니다.`] : []),
        ] : [
          el("b", {}, "모든 규칙이 오차 범위 밖입니다. "), "다만 범위 밖이라고 바로 확실히 낫다는 뜻은 아닙니다. 우연과 구분되는지는 위 p값으로 따로 봐야 합니다.",
        ]),
        el("p", { class: "ruler__note" }, [
          el("b", {}, "처음 세운 목표: "), `'${baseName(sig.vs)}' 규칙보다 ${GOAL_PP}%p 이상 높고, 그 차이가 우연이 아닐 것. `,
          goalMet ? "넘었습니다." : `아직 못 미칩니다.${fin(sig.mcnemar_p) && sig.mcnemar_p >= ALPHA ? ` 한 시즌 ${fmtInt(m.n)}경기로는 이 차이를 우연과 구분할 수 없습니다.` : ""}`,
          ` 비교 상대는 ${sig.selected_on === "val" ? `${r.val_season} 시즌에서 가장 잘 맞힌 규칙으로 미리` : "미리"} 정했습니다.`,
        ]),
        el("p", { class: "ruler__note" }, [
          el("b", {}, "매일 예측은 따로 봅니다. "), live
            ? `매일 예측 모델(${liveVersion()})은 결과가 나온 ${fmtInt(live.n)}경기 중 ${fmtInt(live.c)}경기를 적중했습니다. ` +
              (live.n < LIVE_SHORT ? `경기 수가 너무 적어 위 ${season} 성적과 견줄 수 없습니다.` : `모델과 선발 정보가 달라 위 ${season} 성적과 바로 견주지는 않습니다.`)
            : "매일 예측 기록을 읽지 못해 적지 못했습니다.",
        ]),
      ]),
    );
  } else {
    ruler.append(el("p", { class: "empty" }, "적중률 비교를 그릴 값이 없습니다."));
  }

  box.replaceChildren(el("article", { class: "stage", "aria-label": `${season} 시험: '${baseName(sig.vs)}' 규칙보다 ${diffNum === null ? "—" : signedPP(diffNum)}%p, ${limitHead}` }, [
    top, good, limit, el("span", { class: "stage__vs", "aria-hidden": "true" }, ok ? "그리고" : "그러나"), ruler,
  ]));
  if (ci && fin(m.accuracy)) {
    accuracyRuler(rulerHost, [
      { label: `이 모델 (${algoName(sel)})`, acc: m.accuracy, kind: "model" },
      ...BASELINES.filter(([k]) => fin(base[k])).map(([k, label]) => ({ label, acc: base[k], kind: k === sig.vs ? "primary" : "base" })),
    ], ci, `${season} 시험 적중률`);
  }
}

// ---------- ① 2026 시험 성적 표 ----------

function renderHoldout() {
  const { r, sel, m, base, sig } = holdoutFacts();
  const body = $("holdout-body");

  $("holdout-lead").textContent =
    `${r.test_season ?? "시험"} 정규시즌 ${fmtInt(m.n)}경기입니다. 모델을 만들고 고르는 데 쓰지 않은 시즌입니다.`;

  const modelRow = (key) => {
    const t = r.models?.[key]?.test ?? {};
    const on = key === sel;
    return el("tr", { class: on ? "is-selected" : null }, [
      el("th", { scope: "row" }, [
        modelName(key, r.models?.[key]?.calibration),
        on ? el("span", { class: "pill pill--sm pill--ink holdout__tag" }, "선택") : null,
      ]),
      el("td", { class: "num" }, fmtPct(t.accuracy, 1)),
      el("td", { class: "num" }, num(t.log_loss)),
      el("td", { class: "num col-brier" }, num(t.brier)),
      el("td", { class: "num muted" }, "—"),
    ]);
  };
  const baseRow = ([key, label]) => el("tr", { class: "is-baseline" }, [
    el("th", { scope: "row" }, [
      `규칙: ${label}`,
      key === sig.vs ? el("span", { class: "pill pill--sm pill--ochre holdout__tag" }, "미리 정한 비교 상대") : null,
    ]),
    el("td", { class: "num" }, fmtPct(base[key], 1)),
    el("td", { class: "num muted" }, "—"),
    el("td", { class: "num muted col-brier" }, "—"),
    el("td", { class: "num" }, pval(sig.all?.[key]?.mcnemar_p)),
  ]);
  const order = [sel, ...Object.keys(r.models ?? {}).filter((k) => k !== sel)];

  body.replaceChildren(
    el("p", { class: "holdout__pointer" }, sig.selected_on === "val"
      ? `비교 상대 규칙('${baseName(sig.vs)}')은 ${r.val_season} 시즌에서 가장 잘 맞힌 규칙이라 시험 전에 골라 두었습니다.`
      : `비교 상대 규칙('${baseName(sig.vs)}')은 시험 전에 미리 골라 두었습니다.`),
    el("div", { class: "inset" }, table(
      `${r.test_season} 시험 성적: 모델 ${order.length}개와 규칙 3개`,
      [["모델과 규칙"], ["적중률", "num"], [[ "확률 오차", el("span", { class: "th-sub" }, "log loss")], "num"],
        [["제곱 오차", el("span", { class: "th-sub" }, "Brier")], "num col-brier"], ["p값", "num"]],
      [...order.map(modelRow), ...BASELINES.map(baseRow)],
      "holdout-table",
    )),
    el("details", { class: "more" }, [el("summary", {}, "표 읽는 법과 주의할 점"), el("ul", {}, [
      el("li", {}, `확률 오차(log loss)와 제곱 오차(Brier)는 낮을수록 좋습니다. ${order.length}개 모델 가운데 ${r.val_season} 시즌 확률 오차가 더 낮은 ${eul(algoName(sel))} 골랐습니다. p값은 같은 경기마다 이 모델과 각 규칙이 적중했는지를 짝지어 비교한 결과(McNemar 검정)입니다.`),
      el("li", {}, `${r.test_season} 시즌은 모델을 만들고 고르는 데 쓰지 않았습니다. 다만 개발 중에 ${r.test_season} 성적을 한 번 본 뒤, 확률 보정 방법을 고르는 절차를 바꿨습니다. 같은 ${r.val_season} 시즌으로 보정도 하고 평가도 하면 계단식 보정(isotonic)이 실제보다 좋아 보이기 때문입니다.`),
      el("li", {}, `지난 시즌으로 시험할 때는 ${starterText(r.starter_source?.train_test)} 기록을 썼습니다. 매일 예측은 ${starterText(r.starter_source?.live)}을 쓰므로, 예고와 실제 선발이 다르면 성적이 이보다 낮을 수 있습니다.`),
    ])]),
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
      : gap < 0 ? "조금 불리한 홈팀을 실제보다 좋게 봤습니다" : "조금 불리한 홈팀을 실제보다 나쁘게 봤습니다";
    notes.push(el("p", { class: "calibration__focus" }, [
      "모델이 홈팀 승리 확률을 ", el("b", {}, `${label(focus)}로 본 ${fmtInt(focus.n)}경기`),
      `에서, 예측 평균은 ${fmtPct(focus.pred_mean)}였지만 실제로 홈팀이 이긴 비율은 ${fmtPct(focus.actual_rate)}였습니다. ${verdict}.`,
    ]));
  }
  const small = bins.filter((b) => fin(b.n) && b.n > 0 && b.n < SMALL_BIN);
  if (small.length) {
    notes.push(el("p", { class: "card__foot" },
      `경기가 ${SMALL_BIN}경기보다 적은 구간(${small.map((b) => `${label(b)} ${b.n}경기`).join(", ")})은 우연에 크게 흔들려 판단하기 어렵습니다.`));
  }
  body.replaceChildren(chart, ...notes);
  calibrationChart(chart, bins, { color: "ink" });
}

// ---------- ③ 모델이 크게 본 요인 (피처 중요도) ----------

function renderImportance() {
  const r = state.report;
  const all = r.feature_importance ?? [];
  // 이름: 키가 FACTOR_LABELS에 있으면 키로, 없으면 JSON의 label로 화면용 이름과 풀이를 찾는다
  const top = all.slice(0, 10).map((f) => {
    const id = FACTOR_LABELS[f.name] ? f.name : f.label ?? f.name;
    return { ...f, label: factorLabel(id), help: factorHelp(id) };
  });
  const how = r.selected === "lgbm" ? "결정 나무가 요인으로 경기를 갈라 얻은 개선량(gain)" : "모델이 요인마다 둔 무게(표준화 계수의 크기)";
  $("importance-lead").textContent = `${how}를 ${all.length}개 합이 100%가 되게 나눈 비율입니다. 위에서부터 10개입니다.`;
  const body = $("importance-body");
  // 차트는 패딩 없는 안쪽 div에 그린다(ResizeObserver가 이 div만 다시 그리므로 범례가 지워지지 않고, viewBox = 실제 너비)
  const chart = el("div");
  const legend = el("ul", { class: "chart-legend" }, [
    el("li", {}, [el("span", { class: "dot", style: { background: "var(--pink)" }, "aria-hidden": "true" }), "선발투수 요인"]),
    el("li", {}, [el("span", { class: "dot", style: { background: "var(--teal)" }, "aria-hidden": "true" }), "팀 요인"]),
  ]);
  legend.setAttribute("aria-hidden", "true"); // 막대 색의 뜻 — 표(sr-only)에는 이름이 그대로 있다
  const starters = top.filter((f) => f.name.startsWith("starter_")).length;
  body.replaceChildren(
    el("div", { class: "inset importance__chart" }, [chart, legend]),
    el("p", { class: "card__foot" },
      `10개 중 ${starters}개가 선발투수 요인입니다. 이 비율은 얼마나 크게 보는지만 뜻합니다. 홈팀에 유리한지 불리한지는 경기마다 다르며, '오늘의 경기'의 "승률을 가른 요인"에서 볼 수 있습니다. 막대를 가리키거나 누르면 요인 풀이가 나옵니다.`),
  );
  barChart(chart, top, {
    valueKey: "importance", labelKey: "label", color: (f) => (f.name.startsWith("starter_") ? "pink" : "teal"),
    format: (v) => fmtPct(v, 1), label: "모델이 무게를 많이 둔 요인 10개 (비율)",
  });
}

// ---------- ④ 변형 비교 ----------

function variantTable(caption, rows) {
  const r = state.report ?? {};
  const sub = (main, s) => [main, el("span", { class: "th-sub" }, s)];
  const cols = [["모델"], [sub(`${r.val_season ?? "검증"} 적중률`, "고르기용"), "num"], [sub(`${r.test_season ?? "시험"} 적중률`, "시험"), "num"],
    [sub(`${r.test_season ?? "시험"} 확률 오차`, "log loss"), "num"]];
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
      el("h3", { class: "variant__title" }, "선발투수 정보를 빼면"),
      variantTable("선발 요인을 뺀 모델과 비교", [
        [`지금 모델 (요인 ${nAll}개)`, sel, true],
        [`선발 요인을 뺀 모델 (${ns.n_features ?? "—"}개)`, ns, false],
      ]),
      el("p", { class: "variant__note" },
        `선발 정보를 빼면 ${r.test_season} 적중률이 ${pp(sel.test?.accuracy, ns.test?.accuracy).replace(/^[+−±]/, "")} ${sel.test?.accuracy >= ns.test?.accuracy ? "떨어져" : "올라"} ` +
        `${fmtPct(ns.test?.accuracy, 1)}가 됩니다.` +
        (fin(ns.test?.accuracy) && ns.test.accuracy < r.baselines?.test?.better_win_pct
          ? ` '${baseName("better_win_pct")}' 규칙(${fmtPct(r.baselines.test.better_win_pct, 1)})보다도 낮습니다. 성적의 큰 몫이 선발 정보에서 나온다는 뜻입니다.` : "")),
    ]));
  }
  if (mf) {
    const adopt = mf.adopt === true;
    blocks.push(el("div", { class: "variant" }, [
      el("div", { class: "variant__head" }, [
        el("h3", { class: "variant__title", title: "두 팀 타선의 유형 구성(예: 파워형 비율)과 두 선발의 유형을 비교한 값입니다." }, "선수 유형 궁합 정보를 더하면"),
        el("span", { class: `pill pill--sm ${adopt ? "pill--ink" : "pill--muted"}` }, adopt ? "넣음" : "넣지 않음"),
      ]),
      variantTable("유형 궁합 정보를 더한 모델과 비교", [
        ["궁합 정보 없이 (지금 모델)", mf.without, !adopt],
        [`궁합 정보 ${(mf.features_added ?? []).length}개 추가`, mf.with, adopt],
      ]),
      el("p", { class: "variant__note" },
        `${adopt ? `${r.val_season} 시즌 확률 오차가 줄어 넣었습니다.` : `${r.val_season} 시즌 확률 오차가 줄지 않아 매일 예측 모델에 넣지 않았습니다.`} ` +
        `${r.test_season} 시험에서 두 모델의 적중 차이는 ${isSig(mf.mcnemar_p_test) ? "우연으로 보기 어렵습니다" : "우연과 구분되지 않습니다"}(${pText(mf.mcnemar_p_test)}).`),
      // 얼린 model_report.json의 validation_scope(개발자 문장)는 title로 남기고, 같은 규칙(train_win._validation_scope)을 쉬운 말로 다시 쓴다
      mf.validation_scope ? el("p", { class: "variant__scope", title: mf.validation_scope }, [el("b", {}, "비교의 한계 "), scopeText(mf.fit_seasons, r.val_season, r.test_season) ?? mf.validation_scope]) : null,
    ]));
  }
  $("variants-body").replaceChildren(blocks.length ? el("div", { class: "variants" }, blocks)
    : el("p", { class: "empty" }, "변형 비교 결과가 없습니다."));
}

/** 유형 궁합 비교가 앞날 기록을 봤는지 (train_win._validation_scope와 같은 세 갈래). 맞춤 시즌 정보가 없으면 null. */
function scopeText(fit, val, test) {
  if (!fit?.length || !fin(val) || !fin(test)) return null;
  const span = fmtRange(fit), last = Math.max(...fit);
  if (last >= test) return `${val} 비교와 ${test} 비교 모두 그 시즌 기록까지 보고 만든 기준(${span})으로 유형을 매겼습니다. 그래서 둘 다 답을 조금 미리 본 비교(전이적 비교)입니다.`;
  if (last >= val) return `${val} 비교에 쓴 유형은 ${val} 기록까지 보고 만든 기준(${span})으로 매겼습니다. 그래서 답을 조금 미리 본 비교(전이적 비교)입니다. ${test} 시험 비교만 앞날 기록을 보지 않은 깨끗한 비교(시간 외 비교)입니다.`;
  return `유형 기준(${span})이 ${val}, ${test} 시즌 기록을 보지 않았으므로 두 비교 모두 깨끗한 비교(시간 외 비교)입니다.`;
}

// ---------- ⑤ 선수 유형 품질 ----------

function clusterGroup(group, q) {
  const kRows = (q.k_table ?? []).map((row) => el("tr", { class: row.k === q.k ? "is-selected" : null }, [
    el("th", { scope: "row" }, [`${row.k}개`, row.k === q.k ? el("span", { class: "pill pill--sm pill--ink holdout__tag" }, "선택") : null]),
    el("td", { class: "num" }, fmtRate3(row.silhouette)),
    el("td", { class: "num" }, fmtRate3(row.retention)),
    el("td", { class: "num" }, fmtRate3(row.score)),
  ]));
  const chosen = (q.k_table ?? []).find((row) => row.k === q.k);
  const types = (q.types ?? []).map((t) => el("li", { class: "type" }, [
    el("span", { class: "pill type__pill" }, [
      el("span", { class: "dot", style: { background: `var(--${typeColor(group, t.id)})` }, "aria-hidden": "true" }),
      t.name, el("b", { class: "num" }, `${fmtInt(t.n)}개`),
    ]),
    el("span", { class: "type__ex" }, (t.examples ?? []).join(", ") || "—"),
  ]));
  return el("div", { class: "inset cluster" }, [
    el("h3", { class: "cluster__title" }, [
      `${GROUP[group]}, 유형 ${q.k ?? "—"}개`,
      // n_fit·n_all은 사람 수가 아니라 선수-시즌 기록 수 (cluster.py 행 수)
      el("span", { class: "cluster__sub" }, ` 시즌 기록 ${fmtInt(q.n_fit)}개로 만듦 (전체 ${fmtInt(q.n_all)}개)`),
    ]),
    table(`${GROUP[group]} 유형 수별 경계 뚜렷함, 유지율, 합산 점수`,
      [["유형 수"], [["경계 뚜렷함", el("span", { class: "th-sub" }, "실루엣")], "num"], [["다음 해 같은 유형", el("span", { class: "th-sub" }, "유지율")], "num"], ["합산 점수", "num"]], kRows, "k-table"),
    el("p", { class: "cluster__stats" }, [
      `다른 묶기 방법(GMM)으로 묶어도 같은 유형이 나온 비율은 ${fmtRate3(q.gmm_agreement)}입니다.`,
      q.membership_method === "kmeans_softmax" ? " 유형 닮은 정도는 GMM 대신 각 유형 대표점까지 거리로 계산했습니다." : "",
    ]),
    el("p", { class: "cluster__cap" }, "유형별 시즌 기록 수와 대표 선수"),
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
    `${fmtRange(cq.fit_seasons)} 시즌 기록으로 비슷한 선수끼리 묶었습니다(K-means, ${cq.version ?? "유형 모델"}). 유형 수 4는 사람이 정한 값입니다. 아래 합산 점수는 유형 수가 적을수록 높게 나오는 성질이 있어(다음 해에도 같은 유형일 확률이 원래 높아짐) 유형 수를 고르는 근거가 되지 못합니다. 그래서 유형을 구분해 읽을 수 있는 가장 작은 수인 4로 정했고, 점수는 참고로만 보여 줍니다.`;
  const sil = ["batter", "pitcher"].map((g) => cq[g]?.k_table?.find((row) => row.k === cq[g]?.k)?.silhouette);
  body.replaceChildren(
    el("div", { class: "clusters" }, ["batter", "pitcher"].filter((g) => cq[g]).map((g) => clusterGroup(g, cq[g]))),
    el("details", { class: "more" }, [el("summary", {}, "숫자 읽는 법"), el("ul", {}, [
      el("li", {}, `경계 뚜렷함(실루엣)이 타자 ${fmtRate3(sil[0], 2)}, 투수 ${ro(fmtRate3(sil[1], 2))} 낮습니다. 선수 기록은 뚝뚝 끊기지 않고 이어져 있어서, 유형은 비슷한 선수끼리 대략 나눈 구분입니다. 유지율은 두 시즌 연속 기록이 충분한 선수가 다음 해에도 같은 유형인 비율입니다.`),
      // 얼린 membership_note(개발자 문장)는 title로 남기고 화면에는 쉬운 말
      cq.membership_note ? el("li", { title: cq.membership_note }, membershipText(cq.batter?.membership_method, cq.membership_note)) : null,
      // 2D 지도(PCA 두 축)가 담는 정보와, 지도 위에서 유형이 그대로 구분되는 비율 — 지도가 겹쳐 보이는 이유
      fin(cq.batter?.map_agreement) ? el("li", {}, `선수 지도는 여러 기록을 두 축으로 줄인 그림이라 정보의 일부만 담습니다(타자 ${fmtPct(sum(cq.batter.pca_explained), 0)}, 투수 ${fmtPct(sum(cq.pitcher?.pca_explained), 0)}). 지도 위에서 유형이 그대로 구분되는 선수는 타자 ${fmtPct(cq.batter.map_agreement, 0)}, 투수 ${fmtPct(cq.pitcher?.map_agreement, 0)}이고, 나머지는 다른 유형 쪽에 겹쳐 보입니다. 유형은 지도가 아니라 모든 기록으로 정합니다.`) : null,
      cq.version === "clusters-2026b" ? el("li", {}, "2026년 11월에 타자 유형을 다시 만들었습니다. 홈런 비율은 순수 장타력(ISO)과 거의 같은 정보라 장타가 두 번 세어지지 않게 뺐고, 도루는 소수 선수에게 몰린 값이라 로그로 펴서 썼습니다. 투수 유형은 그대로입니다.") : null,
    ])]),
  );
}

// ---------- ⑥ 매일 예측 기록 (history.csv) ----------

function renderLive() {
  const body = $("live-body");
  const rows = state.history;
  if (!rows) {
    showError(body, state.errors.history, async () => { await loadHistory(); renderLive(); renderBadges(); });
    return;
  }
  if (!rows.length) {
    body.replaceChildren(el("p", { class: "empty" }, "아직 매일 예측 기록이 없습니다. 첫 예측은 경기 날 아침에 올라옵니다."));
    return;
  }
  // 모델 버전별: 예측 경기 수, 결과가 난 경기(FINAL + correct 0/1), 적중, 적중률. log loss는 표본이 작아 적지 않는다.
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
      // 결과가 난 경기가 LIVE_SHORT 미만이면 %로 쓰지 않는다 (3경기의 "100.0%"는 과장)
      el("td", { class: "num" }, !decided.length ? "—" : decided.length < LIVE_SHORT ? `${correct}/${decided.length}` : fmtPct(correct / decided.length, 1)),
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
        el("p", {}, `매일 예측 기록은 ${first ? first.slice(0, 4) : ""} 포스트시즌인 ${fmtDate(first)}부터 쌓기 시작했습니다. ` +
          (nDecided < LIVE_SHORT
            ? `결과가 나온 경기가 아직 ${fmtInt(nDecided)}경기라 위 ${state.report?.test_season ?? "시험"} 성적과 견주기에는 너무 적습니다.`
            : `지금까지 결과가 나온 경기는 ${fmtInt(nDecided)}경기입니다.`)),
        el("p", { class: "card__foot" }, "모델 버전이 바뀌면 줄을 나눠 셉니다. '결과 나옴'은 결과가 나온 경기 수(무승부 제외)입니다. 확률이 50% 이상인 팀을 모델이 고른 팀으로 봅니다. 경기 수가 적어 적중만 적고 확률 오차는 적지 않습니다."),
      ]),
      el("div", { class: "inset live__summary" }, table("모델 버전별 매일 예측 기록",
        [["모델"], ["예측", "num"], ["결과 나옴", "num"], ["적중", "num"], ["적중률", "num"]], summary, "live-table")),
    ]),
    el("details", { class: "more live__all" }, [
      el("summary", {}, `전체 기록 보기 (${fmtInt(rows.length)}경기)`),
      el("div", { class: "inset" }, table("매일 예측 전체 기록 (최근 순)",
        [["날짜"], ["대진 (원정 vs 홈)"], ["홈팀 승리 예측", "num"], ["모델"], ["예측 시각"], ["결과"], ["적중", "r"]], full, "live-full")),
    ]),
  );
}

init();
