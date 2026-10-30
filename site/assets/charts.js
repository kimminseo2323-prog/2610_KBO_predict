// KBO Predict — 차트. 외부 라이브러리 없이 인라인 SVG를 그린다(토큰 색·글꼴을 그대로 쓰려고).
//
// 모든 함수는 (el, data, options) → el 안을 비우고 <svg role="img" aria-label=…>(+ 범례) + 화면 낭독기용
// <table class="sr-only">를 넣는다. 산점도에 onSelect를 주면 점을 고를 수 있어 svg가 role="group"이 된다.
// 그릴 값(유한한 숫자)이 하나도 없으면 <p class="empty">표시할 값이 없습니다</p>만 넣는다.
// 색은 토큰 이름("teal") 또는 CSS 값으로 받고 style="fill: var(--teal)"로 칠한다. 글자는 currentColor(카드 글자색),
// 축 글자는 var(--muted)(카드마다 대비가 맞게 다시 정의됨)를 따른다.
// 그릴 때 el의 실제 너비를 viewBox 너비로 써서 글자가 줄어들지 않게 하고, 너비가 바뀌면 다시 그린다(ResizeObserver).

const NS = "http://www.w3.org/2000/svg";
const DARK = new Set(["pink", "teal", "ink"]);
const MIN_W = 240;
const fin = (v) => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));
const pct = (v) => (fin(v) ? `${Math.round(Number(v) * 100)}%` : "—");

function svgEl(tag, attrs = {}, children = []) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined && v !== false) n.setAttribute(k, String(v));
  for (const c of [].concat(children)) if (c !== null && c !== undefined) n.append(typeof c === "string" ? document.createTextNode(c) : c);
  return n;
}

function cv(token) {
  return /^(#|var\(|rgb|hsl|currentColor)/.test(token) ? token : `var(--${token})`;
}

function textOn(token) {
  return DARK.has(token) ? "var(--on-dark)" : "var(--ink)";
}

function srTable(caption, headers, rows) {
  const t = document.createElement("table");
  t.className = "sr-only";
  t.createCaption().textContent = caption;
  const hr = t.createTHead().insertRow();
  headers.forEach((h) => { const th = document.createElement("th"); th.scope = "col"; th.textContent = h; hr.append(th); });
  const body = t.createTBody();
  rows.forEach((r) => { const tr = body.insertRow(); r.forEach((c) => { tr.insertCell().textContent = c; }); });
  return t;
}

function legendList(items) {
  const ul = document.createElement("ul");
  ul.className = "chart-legend";
  ul.setAttribute("aria-hidden", "true"); // 같은 내용이 표에 있다
  items.forEach(([label, token]) => {
    const li = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = cv(token);
    li.append(dot, label);
    ul.append(li);
  });
  return ul;
}

/** 그릴 값이 없을 때: 차트 대신 짧은 안내 문구. */
function empty(el) {
  el.classList.add("chart");
  el._chartRO?.disconnect();
  const p = document.createElement("p");
  p.className = "empty";
  p.textContent = "표시할 값이 없습니다";
  el.replaceChildren(p);
  return el;
}

/** el을 차트 상자로 만들고 draw(width) → [노드…]를 그린다. 너비가 8px 넘게 바뀌면 다시 그린다. */
function mount(el, draw) {
  el.classList.add("chart");
  el._chartRO?.disconnect();
  let last = 0;
  const render = () => {
    const w = Math.max(MIN_W, Math.round(el.clientWidth || 600));
    if (Math.abs(w - last) < 8) return;
    last = w;
    el.replaceChildren(...draw(w));
  };
  render();
  if (typeof ResizeObserver !== "undefined") {
    el._chartRO = new ResizeObserver(render);
    el._chartRO.observe(el);
  }
  return el;
}

function svgRoot(w, h, label, role = "img") {
  return svgEl("svg", { viewBox: `0 0 ${w} ${h}`, width: w, height: h, role, "aria-label": label, focusable: "false" });
}

/**
 * 가로 막대. rows = [{label, value}], 음수가 있으면 0을 가운데 둔 양방향 막대(요인 pp 등). 값이 없는 행은 막대 없이 "—".
 * options: valueKey="value", labelKey="label", color="teal"(또는 row → 토큰 함수), negativeColor="pink",
 *          format(v)=v, label(aria), max(눈금 최대 |값|). 좁은 화면(<480px)에서는 이름을 막대 위에 쓴다.
 */
export function barChart(el, rows, { valueKey = "value", labelKey = "label", color = "teal", negativeColor = "pink",
  format = (v) => String(v), label = "막대 그래프", max } = {}) {
  const vals = (rows ?? []).map((r) => (fin(r[valueKey]) ? Number(r[valueKey]) : null));
  const finite = vals.filter((v) => v !== null);
  if (!finite.length) return empty(el);
  const m = fin(max) ? Number(max) : Math.max(1e-9, ...finite.map(Math.abs));
  const diverging = finite.some((v) => v < 0);
  const fill = (r, v) => (typeof color === "function" ? color(r) : v < 0 ? negativeColor : color);
  const fmt = (v) => (v === null ? "—" : format(v));
  return mount(el, (W) => {
    const narrow = W < 480;
    const rowH = narrow ? 46 : 34;
    const labelW = narrow ? 0 : Math.min(220, W * 0.38);
    const valW = 56;
    const x0 = labelW + (diverging ? valW : 0);
    const x1 = W - valW;
    const zero = diverging ? (x0 + x1) / 2 : x0;
    const scale = (diverging ? (x1 - x0) / 2 : x1 - x0) / m;
    const H = rows.length * rowH + 4;
    const svg = svgRoot(W, H, label);
    if (diverging) svg.append(svgEl("line", { class: "c-zero", x1: zero, x2: zero, y1: 0, y2: H }));
    rows.forEach((r, i) => {
      const v = vals[i];
      const top = i * rowH + (narrow ? 20 : 6);
      const barH = narrow ? 18 : 22;
      const len = v === null ? 0 : Math.min(Math.abs(v), m) * scale;
      const x = v !== null && v < 0 ? zero - len : zero;
      svg.append(svgEl("text", { class: "c-label", x: narrow ? 0 : labelW - 12, y: narrow ? top - 6 : top + barH / 2 + 4,
        "text-anchor": narrow ? "start" : "end" }, String(r[labelKey] ?? "")));
      if (v !== null) svg.append(svgEl("rect", { x, y: top, width: Math.max(len, 1), height: barH, rx: 4, style: `fill:${cv(fill(r, v))}` }));
      svg.append(svgEl("text", { class: v === null ? "c-axis" : "c-value", x: v !== null && v < 0 ? x - 6 : x + len + 6,
        y: top + barH / 2 + 4, "text-anchor": v !== null && v < 0 ? "end" : "start" }, fmt(v)));
    });
    const table = srTable(label, ["항목", "값"], rows.map((r, i) => [String(r[labelKey] ?? ""), fmt(vals[i])]));
    return [svg, table];
  });
}

/**
 * 꺾은선. points = [{x, y}] 한 줄, 또는 [{name, color, points: [{x, y}]}] 여러 줄(모든 줄의 x가 같다고 본다).
 * y가 숫자가 아니면 선을 끊는다. options: color="ink", yFormat=pct, yDomain=[lo, hi], label, height=240,
 * refY(점선 기준값 — yDomain이 없으면 범위에 넣고, yDomain 밖이면 그리지 않는다).
 */
export function lineChart(el, points, { color = "ink", yFormat = pct, yDomain, label = "꺾은선 그래프", height = 240, refY } = {}) {
  const series = points?.length && points[0].points ? points : [{ name: label, color, points: points ?? [] }];
  const xs = series[0].points.map((p) => p.x);
  const ys = series.flatMap((s) => s.points.map((p) => p.y)).filter(fin).map(Number);
  if (!ys.length) return empty(el);
  const hasRef = fin(refY);
  let [lo, hi] = yDomain ?? [Math.min(...ys, ...(hasRef ? [refY] : [])), Math.max(...ys, ...(hasRef ? [refY] : []))];
  if (!yDomain) { const pad = (hi - lo) * 0.1 || 0.05; lo -= pad; hi += pad; }
  const drawRef = hasRef && refY >= lo && refY <= hi;
  return mount(el, (W) => {
    const L = 48, R = series.length > 1 ? 12 : 56, T = 10, B = 26, H = height;
    const X = (i) => L + (xs.length > 1 ? (i / (xs.length - 1)) * (W - L - R) : (W - L - R) / 2);
    const Y = (v) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
    const svg = svgRoot(W, H, label);
    for (let k = 0; k <= 4; k++) {
      const v = lo + ((hi - lo) * k) / 4;
      svg.append(svgEl("line", { class: "c-grid", x1: L, x2: W - R, y1: Y(v), y2: Y(v) }),
        svgEl("text", { class: "c-axis", x: L - 8, y: Y(v) + 4, "text-anchor": "end" }, yFormat(v)));
    }
    const ticks = Math.min(xs.length, W < 480 ? 3 : 6);
    for (let k = 0; k < ticks; k++) {
      const i = ticks === 1 ? 0 : Math.round((k * (xs.length - 1)) / (ticks - 1));
      svg.append(svgEl("text", { class: "c-axis", x: X(i), y: H - 6, "text-anchor": k === 0 ? "start" : k === ticks - 1 ? "end" : "middle" }, String(xs[i])));
    }
    if (drawRef) svg.append(svgEl("line", { class: "c-ref", x1: L, x2: W - R, y1: Y(refY), y2: Y(refY) }));
    series.forEach((s) => {
      let d = "";
      s.points.forEach((p, i) => {
        if (!fin(p.y)) { d += " "; return; }
        d += `${d === "" || d.endsWith(" ") ? "M" : "L"}${X(i).toFixed(1)},${Y(Number(p.y)).toFixed(1)}`;
      });
      svg.append(svgEl("path", { d: d.trim(), fill: "none", style: `stroke:${cv(s.color ?? color)}`, "stroke-width": 2.5, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    });
    if (series.length === 1) {
      const pts = series[0].points;
      const i = pts.map((p) => p.y).findLastIndex(fin);
      if (i >= 0) svg.append(svgEl("circle", { cx: X(i), cy: Y(Number(pts[i].y)), r: 4.5, style: `fill:${cv(series[0].color ?? color)}` }),
        svgEl("text", { class: "c-value", x: X(i) + 8, y: Y(Number(pts[i].y)) + 4 }, yFormat(Number(pts[i].y))));
    }
    const cell = (v) => (fin(v) ? yFormat(Number(v)) : "—");
    const table = srTable(label, ["x", ...series.map((s) => s.name)], xs.map((x, i) => [String(x), ...series.map((s) => cell(s.points[i]?.y))]));
    return series.length > 1 ? [svg, legendList(series.map((s) => [s.name, s.color])), table] : [svg, table];
  });
}

/**
 * 산점도(선수 유형 지도). points = [{id, x, y, label, …}] — x·y가 숫자가 아닌 점은 뺀다.
 * options: colorKey(키 이름 또는 p → 토큰 함수, 기본 "color"), onSelect(p)(주면 점을 클릭·키보드로 고를 수 있다:
 * 화살표로 이동, Enter/Space로 선택), selectedId, label, legend([[이름, 토큰]]), typeLabel(p)(표의 "유형" 칸;
 * 없으면 legend에서 점 색으로 찾음), height,
 * dim(p)(true인 점은 흐리게만 그린다: 지도 모양은 그대로 두고 고를 수 없으며 표·키보드 이동에서도 빠진다 — 선수 페이지의 팀 필터).
 */
export function scatter(el, points, { colorKey = "color", onSelect, selectedId, label = "산점도", legend, typeLabel, height, dim } = {}) {
  const pts = (points ?? []).filter((p) => p && fin(p.x) && fin(p.y));
  if (!pts.length) return empty(el);
  const isDim = (p) => (dim ? Boolean(dim(p)) : false);
  const colorOf = (p) => (typeof colorKey === "function" ? colorKey(p) : p[colorKey]) ?? "muted-soft";
  const typeOf = (p) => (typeLabel ? typeLabel(p) : legend?.find(([, tok]) => tok === colorOf(p))?.[0]) ?? "—";
  const xv = pts.map((p) => +p.x), yv = pts.map((p) => +p.y);
  const [xl, xh, yl, yh] = [Math.min(...xv), Math.max(...xv), Math.min(...yv), Math.max(...yv)];
  const live = pts.filter((p) => !isDim(p)); // 고를 수 있는 점 (dim이 없으면 전부)
  const order = [...live].sort((a, b) => a.x - b.x || a.y - b.y);
  return mount(el, (W) => {
    const H = height ?? Math.round(Math.min(480, Math.max(260, W * 0.72)));
    const P = 14;
    const X = (v) => P + ((v - xl) / (xh - xl || 1)) * (W - 2 * P);
    const Y = (v) => P + (1 - (v - yl) / (yh - yl || 1)) * (H - 2 * P);
    const svg = svgRoot(W, H, label, onSelect ? "group" : "img");
    const nodes = new Map();
    const select = (p) => {
      nodes.forEach((c, id) => {
        const on = id === p.id;
        c.classList.toggle("is-selected", on);
        Object.entries({ r: on ? 9 : 6, "aria-pressed": on, tabindex: on ? 0 : -1 }).forEach(([k, v]) => c.setAttribute(k, v));
      });
      const c = nodes.get(p.id);
      const hadFocus = document.activeElement === c;
      c.parentNode.append(c); // 맨 위로 (DOM 이동은 포커스를 잃으므로 되돌린다)
      if (hadFocus) c.focus();
      onSelect(p);
    };
    const focusAt = (from, step) => {
      const i = order.findIndex((p) => p.id === from.id);
      const next = order[(i + step + order.length) % order.length];
      nodes.get(from.id).setAttribute("tabindex", -1);
      const c = nodes.get(next.id);
      c.setAttribute("tabindex", 0);
      c.focus();
    };
    const first = live.find((p) => p.id === selectedId) ?? order[0];
    // 그리는 순서: 흐린 점 → 보통 점 → 선택된 점 (위에 그린 것이 보인다)
    const rank = (p) => (isDim(p) ? 0 : p.id === selectedId ? 2 : 1);
    [...pts].sort((a, b) => rank(a) - rank(b)).forEach((p) => {
      if (isDim(p)) {
        svg.append(svgEl("circle", { class: "c-point c-point--dim", cx: X(+p.x).toFixed(1), cy: Y(+p.y).toFixed(1), r: 5,
          style: `fill:${cv(colorOf(p))}`, "fill-opacity": 0.22, "aria-hidden": "true" }));
        return;
      }
      const on = p.id === selectedId;
      const c = svgEl("circle", { class: `c-point${on ? " is-selected" : ""}`, cx: X(+p.x).toFixed(1), cy: Y(+p.y).toFixed(1), r: on ? 9 : 6,
        style: `fill:${cv(colorOf(p))}`, "fill-opacity": 0.9 }, svgEl("title", {}, p.label ?? String(p.id)));
      if (onSelect) {
        Object.entries({ role: "button", tabindex: p === first ? 0 : -1, "aria-label": p.label ?? String(p.id), "aria-pressed": on })
          .forEach(([k, v]) => c.setAttribute(k, v));
        c.addEventListener("click", () => select(p));
        c.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(p); }
          else if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); focusAt(p, 1); }
          else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); focusAt(p, -1); }
        });
      }
      nodes.set(p.id, c);
      svg.append(c);
    });
    const table = srTable(label, ["이름", "유형", "x", "y"], live.map((p) => [p.label ?? String(p.id), typeOf(p), (+p.x).toFixed(2), (+p.y).toFixed(2)]));
    return legend ? [svg, legendList(legend), table] : [svg, table];
  });
}

/**
 * 100% 누적 가로 막대(팀 로스터 유형 구성). rows = [{label, [key]: 비중}] (빠지거나 숫자가 아닌 값은 0).
 * options: keys(순서), colors({key: 토큰}), labels({key: 이름}), labelKey="label", format=pct, label.
 */
export function stackedBar(el, rows, { keys, colors, labels = {}, labelKey = "label", format = pct, label = "누적 막대 그래프" } = {}) {
  const val = (r, k) => { const v = r[k] ?? r.values?.[k]; return fin(v) ? Math.max(0, Number(v)) : 0; };
  const shown = (rows ?? []).filter((r) => keys.some((k) => val(r, k) > 0));
  if (!shown.length) return empty(el);
  return mount(el, (W) => {
    const narrow = W < 480;
    const rowH = narrow ? 44 : 32;
    const labelW = narrow ? 0 : Math.min(120, W * 0.2);
    const barW = W - labelW;
    const svg = svgRoot(W, shown.length * rowH + 2, label);
    shown.forEach((r, i) => {
      const top = i * rowH + (narrow ? 18 : 4);
      const barH = narrow ? 22 : 24;
      const total = keys.reduce((s, k) => s + val(r, k), 0);
      svg.append(svgEl("text", { class: "c-label", x: narrow ? 0 : labelW - 12, y: narrow ? top - 5 : top + barH / 2 + 4,
        "text-anchor": narrow ? "start" : "end" }, String(r[labelKey] ?? "")));
      let x = labelW;
      keys.forEach((k) => {
        const w = (val(r, k) / total) * barW;
        if (w <= 0) return;
        const tok = colors[k];
        svg.append(svgEl("rect", { x: x.toFixed(1), y: top, width: Math.max(w - 1.5, 0.5).toFixed(1), height: barH, style: `fill:${cv(tok)}` }));
        if (w > 38) svg.append(svgEl("text", { class: "c-value", x: (x + w / 2).toFixed(1), y: top + barH / 2 + 4, "text-anchor": "middle", style: `fill:${textOn(tok)}` }, format(val(r, k))));
        x += w;
      });
    });
    const legend = legendList(keys.map((k) => [labels[k] ?? k, colors[k]]));
    const table = srTable(label, ["이름", ...keys.map((k) => labels[k] ?? k)], shown.map((r) => [String(r[labelKey] ?? ""), ...keys.map((k) => format(val(r, k)))]));
    return [svg, legend, table];
  });
}

/**
 * 신뢰도 곡선(캘리브레이션). bins = model_report.json calibration_bins [{lo, hi, n, pred_mean, actual_rate}].
 * 막대 = 그 구간에 든 경기의 실제 홈 승률, 점선 = 완벽한 보정(예측 = 실제). 경기가 없는 구간(n = 0)은 비운다.
 * options: color="ink", label.
 */
export function calibrationChart(el, bins, { color = "ink", label = "신뢰도 곡선: 예측 홈 승률 구간별 실제 홈 승률" } = {}) {
  const all = (bins ?? []).filter((b) => b && fin(b.lo) && fin(b.hi));
  const has = (b) => fin(b.n) && b.n > 0 && fin(b.actual_rate);
  if (!all.some(has)) return empty(el);
  return mount(el, (W) => {
    const L = 44, R = 8, T = 18, B = 40;
    const H = Math.round(Math.min(380, Math.max(240, W * 0.62)));
    const X = (v) => L + v * (W - L - R);
    const Y = (v) => T + (1 - v) * (H - T - B);
    const svg = svgRoot(W, H, label);
    [0, 0.25, 0.5, 0.75, 1].forEach((v) => {
      svg.append(svgEl("line", { class: "c-grid", x1: L, x2: W - R, y1: Y(v), y2: Y(v) }),
        svgEl("text", { class: "c-axis", x: L - 8, y: Y(v) + 4, "text-anchor": "end" }, pct(v)),
        svgEl("text", { class: "c-axis", x: X(v), y: H - 22, "text-anchor": v === 0 ? "start" : v === 1 ? "end" : "middle" }, pct(v)));
    });
    all.filter(has).forEach((b) => {
      const x = X(b.lo) + 2, w = X(b.hi) - X(b.lo) - 4;
      svg.append(svgEl("rect", { x, y: Y(b.actual_rate), width: Math.max(w, 1), height: Y(0) - Y(b.actual_rate), rx: 3, style: `fill:${cv(color)}`, "fill-opacity": 0.82 }));
      if (w > 22) svg.append(svgEl("text", { class: "c-axis", x: x + w / 2, y: Y(b.actual_rate) - 5, "text-anchor": "middle" }, String(b.n)));
    });
    svg.append(svgEl("line", { class: "c-ref", x1: X(0), y1: Y(0), x2: X(1), y2: Y(1) }));
    svg.append(svgEl("text", { class: "c-axis", x: (L + W - R) / 2, y: H - 4, "text-anchor": "middle" }, "예측 홈 승률 (막대 위 숫자 = 경기 수)"));
    const table = srTable(label, ["예측 구간", "경기 수", "예측 평균", "실제 홈 승률"],
      all.map((b) => [`${pct(b.lo)}–${pct(b.hi)}`, String(b.n ?? "—"), pct(b.pred_mean), has(b) ? pct(b.actual_rate) : "표본 없음"]));
    return [svg, table];
  });
}
