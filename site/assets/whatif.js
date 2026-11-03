// KBO Predict — 선발 바꿔 보기 계산. src/kbo_predict/whatif.py의 prob()와 한 줄씩 같은 계산이다
// (tests/test_whatif.py가 node로 이 함수를 실행해 파이썬·실제 예측과 1e-9 안에서 같은지 확인한다).
//
// model = whatif_model(index.json) 또는 whatif.json의 model: {features, median, mean, scale, coef, intercept, calibration}
// base  = 경기마다 선발과 상관없는 피처 값 {피처: 값 | null}
// home / away = 후보 선발의 기록 {era, fip, k9, bb9, ip, last3_runs} (값 null 가능) 또는 null(기록 없음)

const LINE_KEYS = ["era", "fip", "k9", "bb9", "ip", "last3_runs"];
const isNum = (v) => typeof v === "number" && Number.isFinite(v);

/** 두 선발 기록 → 선발 피처 7개 (features.game_features와 같은 규칙: 둘 다 기록이 있어야 선발 피처를 쓴다). */
export function starterFeatures(home, away) {
  const known = home != null && away != null;
  const out = { starter_known: known ? 1 : 0 };
  for (const k of LINE_KEYS) {
    const a = home?.[k], b = away?.[k];
    out[`starter_${k}_diff`] = known && isNum(a) && isNum(b) ? a - b : null;
  }
  return out;
}

/** P(홈 승). 결측은 학습 중앙값 → 표준화 → 계수 합 → 시그모이드 → 보정. */
export function whatifProb(model, base, home, away) {
  const x = { ...base, ...starterFeatures(home, away) };
  let logit = model.intercept;
  model.features.forEach((name, i) => {
    const v = isNum(x[name]) ? x[name] : model.median[i];
    logit += (model.coef[i] * (v - model.mean[i])) / model.scale[i];
  });
  let p = 1 / (1 + Math.exp(-logit));
  const cal = model.calibration ?? { method: "none" };
  if (cal.method === "platt") {
    const q = Math.min(Math.max(p, 1e-6), 1 - 1e-6);
    p = 1 / (1 + Math.exp(-(cal.a * Math.log(q / (1 - q)) + cal.b)));
  } else if (cal.method === "isotonic") {
    p = interp(p, cal.x, cal.y);
  }
  return p;
}

/** numpy.interp와 같은 선형 보간 (양 끝은 끝값). */
function interp(v, xs, ys) {
  if (v <= xs[0]) return ys[0];
  if (v >= xs[xs.length - 1]) return ys[ys.length - 1];
  let i = 1;
  while (xs[i] < v) i += 1;
  const t = (v - xs[i - 1]) / (xs[i] - xs[i - 1] || 1);
  return ys[i - 1] + t * (ys[i] - ys[i - 1]);
}
