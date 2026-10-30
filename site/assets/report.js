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
  FACTOR_LABELS, el, fetchJSON, fetchCSV, fmtPct, fmtDate, fmtKST, teamName, typeColor,
  renderNav, renderFooter, showError,
} from "./app.js";
import { barChart, calibrationChart } from "./charts.js";

const $ = (id) => document.getElementById(id);

const state = { report: null, history: null, status: null, errors: {} };

// ---------- 작은 도우미 ----------

const fin = (v) => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));
/** 소수 d자리. 값이 없으면 "—". */
const num = (v, d = 3) => (fin(v) ? Number(v).toFixed(d) : "—");
/** 0.345 → ".345" (앞의 0을 뺀 야구·통계식 표기). */
const dot = (v, d = 3) => (fin(v) ? Number(v).toFixed(d).replace(/^(-?)0\./, "$1.") : "—");
/** p값: 0.001 미만은 "< .001", 그 밖은 ".046". */
const pval = (p) => (!fin(p) ? "—" : Number(p) < 0.001 ? "< .001" : dot(p, 3));
/** 정확도 차이(0~1 소수 두 개) → "+1.5%p". */
const pp = (a, b) => {
  if (!fin(a) || !fin(b)) return "—";
  const d = (Number(a) - Number(b)) * 100;
  return `${d > 0 ? "+" : d < 0 ? "−" : "±"}${Math.abs(d).toFixed(1)}%p`;
};
const ALPHA = 0.05;            // 유의수준
const GOAL_PP = 3;             // 설계 목표: 가장 강한 기준선 +3%p 이상, 통계적으로 유의
const SMALL_BIN = 30;          // 이보다 적은 경기가 든 신뢰도 구간은 "표본 적음"으로 적는다
const range = (a) => (a?.length ? (a[0] === a.at(-1) ? `${a[0]}` : `${a[0]}~${a.at(-1)}`) : "—");
const int = (v) => (fin(v) ? Number(v).toLocaleString("ko-KR") : "—");
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

function table(caption, cols, rows, cls = "") {
  return el("div", { class: "table-scroll" }, el("table", { class: `table ${cls}`.trim() }, [
    el("caption", { class: "sr-only" }, caption),
    el("thead", {}, el("tr", {}, cols.map(([t, c]) => el("th", { scope: "col", class: c ?? null }, t)))),
    el("tbody", {}, rows),
  ]));
}

// ---------- 읽기 ----------

async function settle(key, promise) {
  try {
    state[key] = await promise;
    delete state.errors[key];
  } catch (err) {
    state[key] = null;
    state.errors[key] = err.message;
  }
}

const loadReport = () => settle("report", fetchJSON("model_report.json"));
const loadHistory = () => settle("history", fetchCSV("history.csv"));

async function init() {
  renderNav("report.html");
  await Promise.all([loadReport(), loadHistory(), settle("status", fetchJSON("status.json"))]);
  renderFooter(state.status);
  renderReport();
  renderLive();
}

/** model_report.json으로 그리는 부분 전부(배지 + 카드 ①~⑤). 읽기 실패면 ①에 오류 상자 + 다시 불러오기. */
function renderReport() {
  renderBadges();
  if (!state.report) {
    showError($("holdout-body"), state.errors.report, async () => { await loadReport(); renderReport(); });
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
  const r = state.report;
  if (!r) {
    box.replaceChildren(el("p", { class: "empty" }, "모델 정보를 불러오지 못했습니다."));
    return;
  }
  const train = r.train_seasons ?? [];
  const first = train[0];
  const all = [];
  if (fin(first) && fin(r.test_season)) for (let y = first; y <= r.test_season; y++) all.push(y);
  const role = (y) => (y === r.test_season ? "test" : y === r.val_season ? "val" : "train");
  const n = r.n ?? {};
  const report = el("article", { class: "badge" }, [
    el("div", { class: "badge__top" }, [
      el("span", { class: "pill pill--ink" }, r.model_version ?? "report"),
      el("span", { class: "badge__role" }, "이 성적표 · 2026 되감기"),
    ]),
    seasonStrip(all, role),
    el("ul", { class: "strip-legend" }, [
      legendItem("train", `학습 ${range(train)} (${int(n.train)}경기)`),
      legendItem("val", `검증 ${r.val_season ?? "—"} (${int(n.val)}경기)`),
      legendItem("test", `시험 ${r.test_season ?? "—"} (${int(n.test)}경기)`),
    ]),
    el("p", { class: "badge__note" }, `선발 피처: ${starterText(r.starter_source?.train_test)} · 만든 날 ${fmtKST(r.generated_at)}`),
  ]);
  // 라이브 모델: 같은 알고리즘·보정 방법을 첫 학습 시즌부터 시험 시즌까지 전부로 다시 학습한 모델
  const liveVersion = state.status?.model_version ?? state.history?.findLast?.((h) => h.model_version)?.model_version ?? "라이브";
  const nLive = state.history?.length;
  const live = el("article", { class: "badge" }, [
    el("div", { class: "badge__top" }, [
      el("span", { class: "pill pill--ink" }, liveVersion),
      el("span", { class: "badge__role" }, "매일 예측 · 라이브 기록"),
    ]),
    seasonStrip([...all, "live"], (y) => (y === "live" ? "live" : "train")),
    el("ul", { class: "strip-legend" }, [
      legendItem("train", `학습 ${all.length ? `${all[0]}~${all.at(-1)}` : "—"} (시험 시즌까지 전부)`),
      legendItem("live", `기록 history.csv ${fin(nLive) ? `${nLive}경기` : "—"}`),
    ]),
    el("p", { class: "badge__note" }, `선발 피처: ${starterText(r.starter_source?.live)} · ${r.test_season}도 학습했으므로 아래 시험 성적은 ${r.model_version ?? "report"} 모델의 것입니다.`),
  ]);
  box.replaceChildren(report, live);
}

// ---------- ① 2026 홀드아웃 표 ----------

function renderHoldout() {
  const r = state.report;
  const body = $("holdout-body");
  const sel = r.selected;
  const m = r.models?.[sel]?.test ?? {};
  const base = r.baselines?.test ?? {};
  const sig = r.significance ?? {};
  const vsAcc = base[sig.vs];
  const diff = pp(m.accuracy, vsAcc);
  const diffNum = fin(m.accuracy) && fin(vsAcc) ? (m.accuracy - vsAcc) * 100 : null;
  const goalMet = diffNum !== null && diffNum >= GOAL_PP && fin(sig.mcnemar_p) && sig.mcnemar_p < ALPHA;

  $("holdout-lead").textContent =
    `${r.test_season ?? "시험"} 정규시즌 ${int(m.n)}경기, 학습과 모델 선택에 쓰지 않은 시즌의 성적`;

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
    el("div", { class: "holdout__top" }, [
      el("p", { class: "kpi holdout__kpi" }, [
        diff,
        el("small", {}, `${baseName(sig.vs)} 규칙보다 (적중 ${int(sig.model_correct)} 대 ${int(sig.baseline_correct)}경기)`),
      ]),
      el("div", { class: "holdout__verdict" }, [
        el("p", { class: "verdict" }, [
          el("span", { class: "verdict__p num" }, `McNemar p = ${pval(sig.mcnemar_p)}`),
          el("span", { class: "verdict__word" }, signif(sig.mcnemar_p)),
        ]),
        el("p", { class: "holdout__goal" },
          `비교 대상은 ${sig.selected_on === "val" ? `${r.val_season} 검증에서` : "미리"} 가장 강했던 규칙으로 정했습니다. ` +
          (goalMet ? `설계 목표(+${GOAL_PP}%p, 통계적으로 유의)를 넘었습니다.`
            : `설계 목표(+${GOAL_PP}%p 이상, 통계적으로 유의)에는 아직 못 미칩니다. 한 시즌 ${int(m.n)}경기로는 이 차이를 우연과 구분할 수 없습니다.`)),
      ]),
    ]),
    el("div", { class: "inset" }, table(
      `${r.test_season} 시험 성적: 모델 ${order.length}개와 규칙 3개`,
      [["모델 / 규칙"], ["정확도", "num"], ["log loss", "num"], ["Brier", "num"], ["p값", "num"]],
      [...order.map(modelRow), ...BASELINES.map(baseRow)],
      "holdout-table",
    )),
    el("ul", { class: "notes" }, [
      el("li", {}, `log loss와 Brier는 낮을수록 좋습니다. 알고리즘은 ${r.val_season} 검증 log loss가 낮은 ${algoName(sel)}를 골랐습니다. p값은 선택 모델과 각 규칙의 경기별 적중을 견준 McNemar 검정입니다.`),
      el("li", {}, `${r.test_season} 시즌은 어떤 학습·선택에도 쓰지 않았지만, 개발 중에 ${r.test_season} 지표를 한 번 확인했고 그 뒤 캘리브레이션 선택 절차를 바꿨습니다(R7).`),
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
      el("b", {}, `${label(focus)} 구간 ${int(focus.n)}경기`),
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
  const chart = el("div", { class: "inset importance__chart" });
  const starters = top.filter((f) => f.name.startsWith("starter_")).length;
  body.replaceChildren(
    chart,
    el("p", { class: "card__foot" },
      `상위 10개 중 ${starters}개가 선발투수 피처입니다. 비중은 크기만 뜻하고 방향(홈에 유리·불리)은 경기마다 다릅니다. 경기별 방향은 홈의 "승률을 가른 요인"에서 볼 수 있습니다.`),
  );
  barChart(chart, top, {
    valueKey: "importance", labelKey: "label", color: (f) => (f.name.startsWith("starter_") ? "pink" : "teal"),
    format: (v) => fmtPct(v, 1), label: "피처 중요도 상위 10개 (비중)",
  });
  chart.append(el("ul", { class: "chart-legend" }, [
    el("li", {}, [el("span", { class: "dot", style: { background: "var(--pink)" }, "aria-hidden": "true" }), "선발투수 피처"]),
    el("li", {}, [el("span", { class: "dot", style: { background: "var(--teal)" }, "aria-hidden": "true" }), "팀 피처"]),
  ]));
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
        `시험 정확도가 ${pp(sel.test?.accuracy, ns.test?.accuracy).replace(/^[+−±]/, "")} 낮아져 ` +
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
    el("td", { class: "num" }, dot(row.silhouette)),
    el("td", { class: "num" }, dot(row.retention)),
    el("td", { class: "num" }, dot(row.score)),
  ]));
  const chosen = (q.k_table ?? []).find((row) => row.k === q.k);
  const types = (q.types ?? []).map((t) => el("li", { class: "type" }, [
    el("span", { class: "pill type__pill" }, [
      el("span", { class: "dot", style: { background: `var(--${typeColor(group, t.id)})` }, "aria-hidden": "true" }),
      t.name, el("b", { class: "num" }, int(t.n)),
    ]),
    el("span", { class: "type__ex" }, (t.examples ?? []).join(", ") || "—"),
  ]));
  return el("div", { class: "inset cluster" }, [
    el("h3", { class: "cluster__title" }, [
      `${GROUP[group]} · K = ${q.k ?? "—"}`,
      el("span", { class: "cluster__sub" }, ` ${int(q.n_fit)}명으로 맞춤 (전체 ${int(q.n_all)}명)`),
    ]),
    table(`${GROUP[group]} K별 실루엣·유지율·점수`, [["K"], ["실루엣", "num"], ["유지율", "num"], ["점수", "num"]], kRows, "k-table"),
    el("p", { class: "cluster__stats" }, [
      `실루엣 ${dot(chosen?.silhouette, 2)} · 유지율 ${fmtPct(q.retention)} · GMM 일치율 ${dot(q.gmm_agreement)}`,
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
    `${cq.version ?? "유형 모델"}: ${range(cq.fit_seasons)} 선수-시즌 기록으로 맞춘 K-means. 점수 = 실루엣 + 연도 간 유지율이 가장 큰 K를 골랐습니다.`;
  const sil = ["batter", "pitcher"].map((g) => cq[g]?.k_table?.find((row) => row.k === cq[g]?.k)?.silhouette);
  body.replaceChildren(
    el("div", { class: "clusters" }, ["batter", "pitcher"].filter((g) => cq[g]).map((g) => clusterGroup(g, cq[g]))),
    el("ul", { class: "notes notes--on-dark" }, [
      el("li", {}, `실루엣이 타자 ${dot(sil[0], 2)}, 투수 ${dot(sil[1], 2)}로 낮습니다. 선수 분포는 연속적이고, 유형은 그 분포를 부드럽게 나눈 구분입니다. 유지율은 연속 두 시즌 모두 자격인 선수의 유형이 그대로인 비율입니다.`),
      cq.membership_note ? el("li", {}, cq.membership_note) : null,
    ]),
  );
}

// ---------- ⑥ 라이브 기록 ----------

function verdictPill(h) {
  if (h.winner === "DRAW") return el("span", { class: "pill pill--sm pill--muted" }, "무승부");
  if (h.correct === 1 || h.correct === true) return el("span", { class: "pill pill--sm pill--ink" }, "적중");
  if (h.correct === 0 || h.correct === false) return el("span", { class: "pill pill--sm pill--coral" }, "미적중");
  return el("span", { class: "pill pill--sm pill--muted" }, "결과 대기");
}

function winnerText(h) {
  if (h.winner === "HOME") return `${teamName(h.home)} 승`;
  if (h.winner === "AWAY") return `${teamName(h.away)} 승`;
  if (h.winner === "DRAW") return "무승부";
  return h.status === "FINAL" ? "—" : "경기 전";
}

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
      el("td", { class: "num" }, int(mine.length)),
      el("td", { class: "num" }, int(decided.length)),
      el("td", { class: "num" }, int(correct)),
      el("td", { class: "num" }, decided.length ? fmtPct(correct / decided.length, 1) : "—"),
    ]);
  });
  const first = rows.map((h) => h.date).filter(Boolean).sort()[0];
  const nDecided = rows.filter((h) => h.status === "FINAL" && (h.correct === 0 || h.correct === 1)).length;
  const full = [...rows].reverse().map((h) => el("tr", {}, [
    el("td", { class: "nowrap" }, fmtDate(h.date)),
    el("td", { class: "nowrap" }, `${teamName(h.away)} @ ${teamName(h.home)}`),
    el("td", { class: "num" }, fmtPct(h.home_win_prob, 1)),
    el("td", {}, h.model_version ?? "—"),
    el("td", { class: "nowrap" }, fmtKST(h.predicted_at)),
    el("td", { class: "nowrap" }, winnerText(h)),
    el("td", { class: "r" }, verdictPill(h)),
  ]));
  body.replaceChildren(
    el("div", { class: "live" }, [
      el("div", { class: "live__copy" }, [
        el("p", {}, `라이브 기록은 ${fmtDate(first)}, 2026 포스트시즌부터 쌓기 시작했습니다. 결과가 난 경기가 아직 ${int(nDecided)}경기라 위의 ${state.report?.test_season ?? "시험"} 성적과 견주기에는 너무 짧습니다.`),
        el("p", { class: "card__foot" }, "모델 버전이 바뀌면 줄을 나눠 셉니다. '결과'는 결과가 나온 경기 수(무승부 제외)이고, 확률 50% 이상인 쪽을 고른 것으로 봅니다. 표본이 작아 정확도만 적고 log loss는 적지 않습니다."),
      ]),
      el("div", { class: "inset live__summary" }, table("모델 버전별 라이브 기록",
        [["모델"], ["예측", "num"], ["결과", "num"], ["적중", "num"], ["정확도", "num"]], summary, "live-table")),
    ]),
    el("details", { class: "live__all" }, [
      el("summary", {}, `전체 기록 보기 (${int(rows.length)}경기)`),
      el("div", { class: "inset" }, table("라이브 예측 전체 기록 (최근 순)",
        [["날짜"], ["대진 (원정 @ 홈)"], ["홈 승률", "num"], ["모델"], ["예측 시각"], ["결과"], ["적중", "r"]], full, "live-full")),
    ]),
  );
}

init();
