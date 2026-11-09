// KBO Predict — 공통 데이터·포맷·내비·푸터 계층 (ES 모듈, 빌드 없음).
//
// 모든 페이지가 이 파일만 통해 data/public/ 파일을 읽는다 (docs/site/data-contract.md).
// 페이지 뼈대(Task 2~5 공통): 정적 <header class="topnav">(아래 NAV 4개 + GitHub 링크, 현재 페이지 aria-current="page"),
// <main id="main">, <footer class="footer">…<p id="evidence" class="evidence"></p>…</footer>.
// 내비는 HTML에 정적으로 있어야 한다(JS 없이도 이동 가능, scripts/check_site.py가 검사). renderNav는 그것을 정리만 한다.
//
// 아래 TEAMS · FACTOR_LABELS · TYPE_COLORS 객체 리터럴은 JSON 문법(따옴표 키, 끝 쉼표 없음)으로 쓴다:
// tests/test_site.py와 check_site.py가 그대로 JSON으로 읽어 파이썬 원본과 비교한다.

export const REPO_URL = "https://github.com/kimminseo2323-prog/2610_KBO_predict";
export const RAW_BASE = "https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public";

/** 로컬 미리보기(python -m http.server, 저장소 루트에서 /site/를 연다)면 true. */
export const IS_LOCAL = ["localhost", "127.0.0.1"].includes(globalThis.location?.hostname ?? "");
// 소식 페이지의 기사 목록 프록시(proxy/news-worker.js를 Cloudflare Workers에 올린 주소, 끝에 / 없이).
// 비어 있으면 소식 페이지는 구단별 네이버 뉴스 검색 링크만 보여 준다. 예: "https://kbo-news.<계정>.workers.dev"
export const NEWS_PROXY = "https://kbo-news.kbo-predict.workers.dev";

/** 데이터 위치: 로컬이면 저장소의 data/public, 배포본(GitHub Pages 등)이면 raw.githubusercontent.com. */
export const DATA_BASE = IS_LOCAL ? "../data/public" : RAW_BASE;

/** 메뉴 5개 — 순서·이름 고정 (check_site.py의 NAV와 같다). */
export const NAV = [
  ["index.html", "오늘의 경기"],
  ["teams.html", "팀"],
  ["players.html", "선수"],
  ["report.html", "모델 성적표"],,
  ["news.html", "소식"]
];

// 10구단: 코드 → 한글 이름(ko, teams.py와 같음), 정식 이름(full), 차트 축용 짧은 이름(short), 강조색(color = 토큰 이름).
// 색은 팔레트 8색(카드 6색 + 민트·코랄) 안에서 구단 상징색에 가까운 것을 골랐다. 겹치는 색이 있으므로
// 색만으로 팀을 구분하지 말고 항상 이름을 함께 쓴다.
export const TEAMS = {
  "OB": {"ko": "두산", "full": "두산 베어스", "short": "두산", "color": "team-ob"},
  "LT": {"ko": "롯데", "full": "롯데 자이언츠", "short": "롯데", "color": "team-lt"},
  "KT": {"ko": "KT", "full": "KT 위즈", "short": "KT", "color": "team-kt"},
  "WO": {"ko": "키움", "full": "키움 히어로즈", "short": "키움", "color": "team-wo"},
  "SK": {"ko": "SSG", "full": "SSG 랜더스", "short": "SSG", "color": "team-sk"},
  "SS": {"ko": "삼성", "full": "삼성 라이온즈", "short": "삼성", "color": "team-ss"},
  "HH": {"ko": "한화", "full": "한화 이글스", "short": "한화", "color": "team-hh"},
  "HT": {"ko": "KIA", "full": "KIA 타이거즈", "short": "KIA", "color": "team-ht"},
  "LG": {"ko": "LG", "full": "LG 트윈스", "short": "LG", "color": "team-lg"},
  "NC": {"ko": "NC", "full": "NC 다이노스", "short": "NC", "color": "team-nc"}
};

// ---------- 팀 색 (DESIGN_broadcast.md "우세한 팀은 그 팀 색으로") ----------

const _teamColorCache = new Map();
/** sRGB "#rrggbb" → WCAG 상대 휘도. 형식이 다르면 null. */
function relLum(hex) {
  const m = /^#([0-9a-f]{6})$/i.exec(String(hex).trim());
  if (!m) return null;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
/**
 * 팀 색 세 가지: bg = 팀 면 바탕(대표색), fg = 그 면 위 글자색(흰색과 잉크 중 대비가 높은 쪽),
 * ink = 흰 바탕 위 글자색(대표색, 밝은 팀은 --team-<코드>-ink), chipOnly = 글자색으로는 구분이 안 되는 팀(검정 KT).
 * 토큰 값은 tokens.css에서 읽는다. 모르는 팀이면 잉크.
 */
export function teamColors(code) {
  const token = TEAMS[code]?.color;
  if (!token) return { bg: "var(--ink)", fg: "var(--on-dark)", ink: "var(--ink)", chipOnly: false };
  if (_teamColorCache.has(token)) return _teamColorCache.get(token);
  const css = getComputedStyle(document.documentElement);
  const L = relLum(css.getPropertyValue(`--${token}`));
  const inkL = relLum(css.getPropertyValue("--ink")) ?? 0.0042;
  // 흰 글자 대비 1.05/(L+0.05), 잉크 글자 대비 (L+0.05)/(inkL+0.05) — 큰 쪽을 고른다 (한화 주황은 잉크 5.8:1 > 흰색 3.4:1)
  const fg = L === null || 1.05 / (L + 0.05) >= (L + 0.05) / (inkL + 0.05) ? "var(--on-dark)" : "var(--ink)";
  const hasInk = css.getPropertyValue(`--${token}-ink`).trim() !== "";
  const out = { bg: `var(--${token})`, fg, ink: hasInk ? `var(--${token}-ink)` : `var(--${token})`, chipOnly: L !== null && L < 0.01 };
  _teamColorCache.set(token, out);
  return out;
}

/** 팀 색 칩(면): 대표 숫자·이름표. text는 글자나 노드. */
export function teamChip(code, text, cls = "") {
  const c = teamColors(code);
  return el("span", { class: `tchip ${cls}`.trim(), style: { background: c.bg, color: c.fg } }, text);
}

/** 문장 속 팀 글자(이름·작은 숫자)를 그 팀 글자색으로. 검정 KT처럼 글자색으로 구분이 안 되면 작은 칩. */
export function teamText(code, text, cls = "") {
  const c = teamColors(code);
  if (c.chipOnly) return teamChip(code, text, `tchip--sm ${cls}`.trim());
  return el("span", { class: `tteam ${cls}`.trim(), style: { color: c.ink } }, text);
}

/**
 * 우세 판정 하나로 통일: P(홈 승) → "home" | "away" | "tie"(반올림해 50 대 50) | null(확률 없음).
 * 매치업 슬랩·상단 칩·최근 예측·요인 자막이 모두 이 함수만 쓴다 (같은 경기에서 말이 엇갈리지 않게).
 */
export function favState(p) {
  if (!fin(p)) return null;
  const pct = Math.round(Number(p) * 100);
  return pct === 50 ? "tie" : pct > 50 ? "home" : "away";
}

// 승패 모델 피처 26개 + bias의 한글 이름 (src/kbo_predict/features.py FACTOR_LABELS와 같음 — 테스트로 고정).
// model_report.json의 feature_importance[].name을 한글로 바꿀 때 쓴다.
export const FACTOR_LABELS = {
  "win_pct_diff": "팀 승률 차이",
  "last10_diff": "최근 10경기 흐름",
  "run_diff_diff": "경기당 득실차",
  "pyth_diff": "피타고리안 기대 승률 차이",
  "prev_season_diff": "지난 시즌 승률 차이",
  "obp_diff": "타선 출루율 차이",
  "hr_rate_diff": "타선 홈런 비율 차이",
  "k_rate_diff": "타선 삼진 비율 차이",
  "bb_rate_diff": "타선 볼넷 비율 차이",
  "era_diff": "투수진 평균자책점 차이",
  "fip_diff": "투수진 FIP 차이",
  "k9_diff": "투수진 9이닝당 삼진 차이",
  "bb9_diff": "투수진 9이닝당 볼넷 차이",
  "rest_diff": "휴식일 차이",
  "bullpen3_diff": "최근 3일 불펜 투구수 차이",
  "home_venue_pct": "홈팀의 홈 경기 승률",
  "away_venue_pct": "원정팀의 원정 경기 승률",
  "h2h_home_pct": "올 시즌 맞대결 승률",
  "season_progress": "시즌 진행도",
  "starter_known": "선발투수 기록 유무",
  "starter_era_diff": "선발 평균자책점 차이",
  "starter_fip_diff": "선발 FIP 차이",
  "starter_k9_diff": "선발 9이닝당 삼진 차이",
  "starter_bb9_diff": "선발 9이닝당 볼넷 차이",
  "starter_ip_diff": "선발 누적 이닝 차이",
  "starter_last3_runs_diff": "선발 최근 3경기 실점 차이",
  "elo_diff": "Elo 전력 점수 차이",
  "bias": "기본 홈 어드밴티지"
};

// 화면용 요인 이름과 한 줄 풀이 (키 → {label, help}). FACTOR_LABELS는 파이썬·얼린 데이터와 같아야 하므로 그대로 두고,
// 화면에는 이 표의 쉬운 이름을 쓴다. 데이터(latest.json·되감기 JSON)에는 FACTOR_LABELS의 옛 이름이 들어 있으므로
// factorKey()가 그 이름을 키로 바꾼다. 모든 "차이"는 홈팀 값 − 원정팀 값이다.
export const FACTOR_DISPLAY = {
  win_pct_diff: { label: "올 시즌 승률 차이", help: "두 팀의 올 시즌 승률(무승부 제외) 차이입니다." },
  last10_diff: { label: "최근 10경기 승률 차이", help: "최근 10경기 승률 차이입니다. 시즌 초에는 10경기보다 적을 수 있습니다." },
  run_diff_diff: { label: "경기당 득실차 비교", help: "경기당 (득점 − 실점)을 두 팀끼리 뺀 값입니다." },
  pyth_diff: { label: "득실로 본 기대 승률 차이", help: "득점과 실점만으로 계산한 '이만큼은 이겼어야 할' 승률(피타고리안 승률)의 차이입니다." },
  prev_season_diff: { label: "지난 시즌 승률 차이", help: "두 팀의 지난 시즌 승률 차이입니다." },
  obp_diff: { label: "타선 출루율 차이", help: "올 시즌 팀 타선 출루율 차이입니다." },
  hr_rate_diff: { label: "타석당 홈런 차이", help: "홈런 ÷ 타석입니다. 올 시즌 팀 타선 기준입니다." },
  k_rate_diff: { label: "타석당 삼진 차이", help: "삼진 ÷ 타석입니다. 올 시즌 팀 타선 기준입니다. 많을수록 타선에 불리합니다." },
  bb_rate_diff: { label: "타석당 볼넷 차이", help: "볼넷 ÷ 타석입니다. 올 시즌 팀 타선 기준입니다." },
  era_diff: { label: "팀 평균자책점 차이", help: "선발과 불펜을 합친 올 시즌 팀 평균자책점 차이입니다. 낮을수록 좋습니다." },
  fip_diff: { label: "팀 투구 내용 차이 (FIP)", help: "FIP는 홈런, 볼넷과 몸에 맞는 공, 삼진만으로 매긴 투수 점수입니다. 수비와 운을 덜 탑니다. 이 사이트는 리그 보정 상수를 더하지 않아 평균자책점과 숫자 크기가 다릅니다. 낮을수록 좋습니다." },
  k9_diff: { label: "팀 투수 9이닝당 삼진 차이", help: "올 시즌 팀 투수진이 9이닝마다 잡은 삼진 수 차이입니다." },
  bb9_diff: { label: "팀 투수 9이닝당 볼넷 차이", help: "올 시즌 팀 투수진이 9이닝마다 내준 볼넷 수 차이입니다." },
  rest_diff: { label: "직전 경기 뒤 지난 날 수 차이", help: "마지막 경기부터 오늘까지 지난 날 수의 차이입니다. 어제 경기했으면 1일입니다." },
  bullpen3_diff: { label: "최근 3일 불펜이 던진 공 수 차이", help: "최근 3일 동안 구원 투수들이 던진 공 수의 차이입니다. 많을수록 불펜이 지쳤을 수 있습니다." },
  home_venue_pct: { label: "홈팀의 올 시즌 홈 승률", help: "홈팀이 올 시즌 자기 구장에서 거둔 승률입니다. 차이가 아니라 홈팀 값 하나입니다." },
  away_venue_pct: { label: "원정팀의 올 시즌 원정 승률", help: "원정팀이 올 시즌 원정에서 거둔 승률입니다. 차이가 아니라 원정팀 값 하나입니다." },
  h2h_home_pct: { label: "올 시즌 맞대결 홈팀 승률", help: "구장과 상관없이 올 시즌 두 팀 맞대결에서 홈팀이 거둔 승률입니다." },
  season_progress: { label: "시즌 진행 정도", help: "홈팀이 치른 경기 수 ÷ 144입니다. 시즌 초반인지 후반인지 모델에 알려 줍니다." },
  starter_known: { label: "두 선발 기록이 있는지", help: "두 선발 모두 작년이나 올해 1군 등판 기록이 있으면 선발 요인을 씁니다. 하나라도 없거나 선발 발표 전이면 쓰지 않습니다." },
  starter_era_diff: { label: "선발 평균자책점 차이 (작년+올해)", help: "두 선발의 지난 시즌과 올 시즌을 합친 평균자책점 차이입니다. 경기 카드의 평균자책점은 올해 기록만이라 다를 수 있습니다." },
  starter_fip_diff: { label: "선발 투구 내용 차이 (FIP)", help: "두 선발의 작년+올해 FIP 차이입니다. FIP는 홈런, 볼넷과 몸에 맞는 공, 삼진만으로 매긴 투수 점수입니다. 리그 보정 상수를 더하지 않아 평균자책점과 숫자 크기가 다릅니다." },
  starter_k9_diff: { label: "선발 9이닝당 삼진 차이", help: "두 선발이 작년+올해 9이닝마다 잡은 삼진 수 차이입니다." },
  starter_bb9_diff: { label: "선발 9이닝당 볼넷 차이", help: "두 선발이 작년+올해 9이닝마다 내준 볼넷 수 차이입니다." },
  starter_ip_diff: { label: "선발이 작년부터 던진 이닝 차이", help: "두 선발이 지난 시즌과 올 시즌에 던진 이닝 합계(구원 등판 포함)의 차이입니다." },
  starter_last3_runs_diff: { label: "선발 최근 3번 등판 평균 실점 차이", help: "각 선발이 최근 3번 선발 등판에서 내준 실점(비자책 포함)의 평균 차이입니다. 작년 등판이 섞일 수 있습니다." },
  elo_diff: { label: "Elo 전력 점수 차이", help: "경기 결과로 매 경기 고치는 팀 전력 점수(Elo)의 차이입니다. 홈 이점 20점을 넣었습니다. 2015년부터 이어서 계산합니다." },
  bias: { label: "홈 경기 기본 이점", help: "다른 요인이 모두 평균인 경기에서도 모델이 홈팀에 주는 기본 몫입니다." },
};

const FACTOR_KEY_OF_LABEL = new Map(Object.entries(FACTOR_LABELS).map(([k, v]) => [v, k]));
/** 요인 키("pyth_diff") 또는 데이터 속 옛 한글 이름("피타고리안 기대 승률 차이") → 키. 모르면 null. */
export function factorKey(nameOrKey) {
  if (nameOrKey in FACTOR_DISPLAY) return nameOrKey;
  return FACTOR_KEY_OF_LABEL.get(nameOrKey) ?? null;
}
/** 화면용 요인 이름. 모르는 이름은 그대로. */
export function factorLabel(nameOrKey) {
  const k = factorKey(nameOrKey);
  return k ? FACTOR_DISPLAY[k].label : String(nameOrKey ?? "");
}
/** 요인 한 줄 풀이(툴팁용). 모르면 "". */
export function factorHelp(nameOrKey) {
  const k = factorKey(nameOrKey);
  return k ? FACTOR_DISPLAY[k].help : "";
}

// 선수 유형 설명(화면용). players.json의 blurb는 얼린 파일이라 여기서 쉬운 말로 덮어쓴다.
// [유형 이름, 설명] — 유형 이름이 데이터와 같을 때만 쓴다(유형을 다시 나눠 id 뜻이 바뀌면 데이터의 blurb로 돌아간다).
const TYPE_BLURBS = {
  batter: {
    0: ["파워형", "순수 장타력(ISO) .213, 타석당 홈런 4.4%로 장타가 가장 많고, 볼넷(11.5%)도 가장 잘 골라 출루율(.384)이 가장 높은 중심 타자입니다."],
    1: ["하위 타선형", "타율 .241, 출루율 .317로 네 유형 중 가장 낮습니다. 맞힌 공이 안타가 되는 비율도 가장 낮고, 장타는 중간입니다. 출전이 적은 선수가 많습니다."],
    2: ["컨택형", "삼진이 13%로 가장 적고 타율(.301)이 가장 높습니다. 홈런은 드뭅니다. 공을 잘 맞히는 테이블세터나 교타자입니다."],
    3: ["주루형", "1루에 나갈 때마다 도루를 .162개씩 하는, 가장 발 빠른 유형입니다. 장타는 가장 적습니다."],
  },
  pitcher: {
    0: ["선발형", "등판의 96%가 선발입니다. 볼넷+사구 비율 8.6%로 제구가 안정적이고 긴 이닝을 맡습니다."],
    1: ["스윙맨형", "선발 비율 29%로 선발과 긴 구원을 오갑니다. 삼진은 적고 피홈런(3.6%)이 많은 편입니다."],
    2: ["제구 불안 불펜형", "거의 구원으로 나옵니다(선발 8.5%). 볼넷+사구 비율이 12.9%로 가장 높지만, 맞은 공이 안타가 되는 비율은 .265로 가장 낮습니다."],
    3: ["삼진 불펜형", "거의 구원만 나오고(선발 4.3%) 삼진 비율이 20%로 가장 높습니다. 짧은 이닝을 삼진으로 막는 필승조형입니다."],
  },
};
/** 유형 설명: 이름이 맞으면 화면용 문장, 아니면 데이터의 blurb. t = {id, name, blurb}. */
export function typeBlurb(group, t) {
  if (!t) return null;
  const [name, text] = TYPE_BLURBS[group]?.[t.id] ?? [];
  return name && name === t.name ? text : t.blurb ?? null;
}

/** 유형 닮은 정도(소속 확신도) 설명. 얼린 model_report.json의 membership_note 대신 쓴다(모르는 방법이면 원문). */
export function membershipText(method, raw) {
  if (method === "kmeans_softmax") {
    return "유형 닮은 정도(선수 카드의 %)는 각 유형 대표점까지의 거리로 계산한 상대 점수입니다. 실제로 그 유형일 확률로 맞춘 값은 아닙니다.";
  }
  return raw ?? null;
}

// 선수 유형 색 (유형 id는 config/cluster_labels.yaml). 타자: 파워형 핑크 · 하위 타선형 피치 · 컨택형 틸 · 주루형 라벤더.
// 투수: 선발형 틸 · 스윙맨형 오커 · 제구 불안 불펜형 핑크 · 삼진 불펜형 라벤더. 홈·선수·팀 페이지가 모두 이것을 쓴다.
export const TYPE_COLORS = {
  "batter": {"0": "pink", "1": "peach", "2": "teal", "3": "lavender"},
  "pitcher": {"0": "teal", "1": "ochre", "2": "pink", "3": "lavender"}
};

const DARK_TOKENS = new Set(["pink", "teal"]);

/** 토큰 이름("pink") → CSS 값("var(--pink)"). 이미 CSS 값이면 그대로. */
export function colorVar(token) {
  return /^(#|var\(|rgb|hsl)/.test(token) ? token : `var(--${token})`;
}

/** 그 색 위에 올릴 글자색: 핑크·틸은 흰색, 나머지는 잉크 (DESIGN_clay.md). */
export function onColor(token) {
  return DARK_TOKENS.has(token) ? "var(--on-dark)" : "var(--ink)";
}

/** 유형 색 토큰. 모르는 유형(null 등)은 "muted-soft". */
/**
 * 유형별 요약 표: 유형마다 선수 수, 선수 평균 기록, 한 줄 설명, 대표 선수(소속 확신이 큰 순 2명).
 * 열마다 가장 두드러진 유형(타자: 가장 높은 값, 평균자책점은 가장 낮은 값)을 굵게 — 표만 보고 "이 유형은 무엇이 다른지" 읽히게.
 * players = 같은 group·season의 선수 목록, types = players.json types[group], nameOf(p) = 표시 이름.
 */
const TYPE_TABLE_COLS = {
  batter: [
    ["타율", (s) => s.avg, (v) => fmtRate3(v), "max"],
    ["출루율", (s) => s.obp, (v) => fmtRate3(v), "max", "sm-hide"],
    ["홈런", (s) => s.hr, (v) => v.toFixed(1), "max"],
    ["삼진 비율", (s) => s.k_pct, (v) => fmtPct(v, 1), "max"],
    ["볼넷 비율", (s) => s.bb_pct, (v) => fmtPct(v, 1), "max"],
    ["도루", (s) => s.sb, (v) => v.toFixed(1), "max"],
  ],
  pitcher: [
    ["평균자책점", (s) => s.era, (v) => v.toFixed(2), "min"],
    ["선발 비율", (s) => (fin(s.games) && s.games > 0 ? s.starts / s.games : null), (v) => fmtPct(v, 0), "max"],
    ["이닝", (s) => s.ip, (v) => v.toFixed(0), "max", "sm-hide"],
    ["삼진 비율", (s) => s.k_pct, (v) => fmtPct(v, 1), "max"],
    ["볼넷+사구 비율", (s) => s.bb_pct, (v) => fmtPct(v, 1), "max"],
  ],
};
export function typeSummaryTable(players, group, types, { nameOf = (p) => p.name_ko ?? p.name, caption } = {}) {
  const cols = TYPE_TABLE_COLS[group] ?? [];
  const mean = (xs) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null);
  const rows = types.map((t) => {
    const mine = players.filter((p) => p.type?.id === t.id);
    const vals = cols.map(([, get]) => mean(mine.map((p) => get(p.stats ?? {})).filter(fin).map(Number)));
    const top = [...mine].sort((a, b) => (b.prob ?? 0) - (a.prob ?? 0)).slice(0, 2).map(nameOf);
    return { t, n: mine.length, vals, top };
  });
  const best = cols.map(([, , , dir], j) => {
    const xs = rows.map((r) => r.vals[j]).filter(fin);
    return xs.length ? (dir === "min" ? Math.min(...xs) : Math.max(...xs)) : null;
  });
  const head = el("tr", {}, [el("th", { scope: "col" }, "유형"), el("th", { scope: "col", class: "num" }, "선수"),
    ...cols.map(([label, , , , hide]) => el("th", { scope: "col", class: `num${hide ? ` ${hide}` : ""}` }, label)), el("th", { scope: "col", class: "type-table__top" }, "대표 선수")]);
  const body = rows.map(({ t, n, vals, top }) => el("tr", {}, [
    el("th", { scope: "row" }, [
      el("span", { class: "type-table__name" }, [el("span", { class: "dot", style: { background: colorVar(typeColor(group, t.id)) }, "aria-hidden": "true" }), t.name]),
      typeBlurb(group, t) ? el("span", { class: "type-table__blurb" }, typeBlurb(group, t)) : null,
    ]),
    el("td", { class: "num" }, `${n}명`),
    ...vals.map((v, j) => el("td", { class: `num${fin(v) && v === best[j] ? " is-best" : ""}${cols[j][4] ? ` ${cols[j][4]}` : ""}` }, fin(v) ? cols[j][2](v) : "—")),
    el("td", { class: "type-table__top" }, top.join(", ") || "—"),
  ]));
  return el("div", { class: "type-table-wrap" }, [
    el("div", { class: "table-scroll" }, el("table", { class: "table type-table" }, [
      el("caption", { class: "sr-only" }, caption ?? "유형별 선수 수와 평균 기록"),
      el("thead", {}, head), el("tbody", {}, body),
    ])),
    el("p", { class: "type-table__note" }, "숫자 칸은 그 유형 선수들의 평균입니다. 열마다 가장 두드러진 값을 굵게 칠했습니다."),
  ]);
}

export function typeColor(group, typeId) {
  return TYPE_COLORS[group]?.[String(typeId)] ?? "muted-soft";
}

/** 팀 한글 이름. 모르는 코드는 코드 그대로. */
export function teamName(code, { full = false } = {}) {
  const t = TEAMS[code];
  return t ? (full ? t.full : t.ko) : (code ?? "—");
}

// 시즌에 따라 이름이 달랐던 구단 (코드는 그대로): SK = SK 와이번스(~2020) → SSG, WO = 넥센 히어로즈(~2018) → 키움.
export const OLD_TEAM_NAMES = {
  "SK": {"until": 2020, "ko": "SK", "full": "SK 와이번스"},
  "WO": {"until": 2018, "ko": "넥센", "full": "넥센 히어로즈"}
};

/** 그 시즌 당시의 팀 이름(옛 이름이 있으면 옛 이름). 시즌이 없으면 teamName과 같다. */
// ---------- 구단 로고 ----------
// site/assets/logos/<코드>.svg (출처·라이선스: logos/SOURCES.md). 구단 상표이고 위키백과의 "공정 이용" 파일이라
// 비상업 포트폴리오에서 팀을 알아보게 하는 용도로만 쓴다. 문제가 되면 SHOW_LOGOS = false 한 줄로 모두 끈다(글자 배지로 바뀜).
export const SHOW_LOGOS = true;
const LOGO_FILES = new Set(["OB", "LT", "KT", "WO", "SS", "HH", "HT", "LG", "NC", "SK"]);
// SSG는 현재 로고의 SVG가 어디에도 없어 구단 공식 엠블럼 페이지의 PNG(개인 목적 사용 허용)를 쓴다 (나머지는 SVG)
const LOGO_EXT = { SK: "png" };

/**
 * 구단 로고(배경 없는 SVG, SSG만 PNG). 로고 파일이 없거나, 옛 구단명 시즌(SK 와이번스·넥센 등)이거나,
 * SHOW_LOGOS가 꺼져 있으면 구단색 글자 배지. 장식이므로 alt는 비우고(이름은 옆 글자가 말한다) title만 단다.
 */
export function teamLogo(code, { season, size = "md" } = {}) {
  const old = OLD_TEAM_NAMES[code];
  const isOld = old && Number.isFinite(Number(season)) && Number(season) <= old.until;
  const cls = `tlogo tlogo--${size}`;
  if (SHOW_LOGOS && LOGO_FILES.has(code) && !isOld) {
    return el("span", { class: cls, title: teamNameFor(code, season, { full: true }) },
      el("img", { src: `assets/logos/${code}.${LOGO_EXT[code] ?? "svg"}`, alt: "", loading: "lazy", decoding: "async", width: "40", height: "40" }));
  }
  const c = teamColors(code);
  return el("span", { class: `${cls} tlogo--text`, style: { background: c.bg, color: c.fg }, title: teamNameFor(code, season, { full: true }), "aria-hidden": "true" },
    teamNameFor(code, season));
}

export function teamNameFor(code, season, { full = false } = {}) {
  const old = OLD_TEAM_NAMES[code];
  if (old && Number.isFinite(Number(season)) && Number(season) <= old.until) return full ? old.full : old.ko;
  return teamName(code, { full });
}

// ---------- 데이터 읽기 ----------

function bust(url) {
  return `${url}${url.includes("?") ? "&" : "?"}v=${Date.now()}`;
}

// 캐시 규칙: 매일(하루 두 번) 바뀌는 status.json · latest.json · history.csv · rewind/2026/index.json만 fresh로 읽는다
// (?v=시각 + cache: "no-store"). 되감기 날짜 파일·players.json·teams.json·model_report.json은 많아야 주 1회 바뀌므로
// 브라우저 기본 캐시를 쓴다(되감기 슬라이더를 오갈 때 같은 날짜를 다시 받지 않게).
async function fetchOK(name, { base = DATA_BASE, fresh = false } = {}) {
  const url = fresh ? bust(`${base}/${name}`) : `${base}/${name}`;
  let res;
  try {
    res = await fetch(url, fresh ? { cache: "no-store" } : {});
  } catch (err) {
    console.warn(`[KBO] ${name}: 네트워크 오류`, err); // 파일 이름은 개발자용으로 콘솔에만 남긴다
    throw new Error("인터넷 연결을 확인하고 다시 불러오기를 눌러 주세요.", { cause: err });
  }
  if (!res.ok) {
    console.warn(`[KBO] ${name}: HTTP ${res.status}`);
    throw new Error(`데이터를 받지 못했습니다 (HTTP ${res.status}). 잠시 뒤 다시 불러오기를 눌러 주세요.`);
  }
  return res;
}

/**
 * data/public/{name}을 JSON으로 읽는다. 실패하면 throw.
 * 옵션: fresh(true면 캐시 버스트 ?v=시각 + no-store — 매일 바뀌는 파일만), base(다른 폴더, 예: 로컬 fixture).
 */
export async function fetchJSON(name, opts = {}) {
  const res = await fetchOK(name, opts);
  try {
    return await res.json();
  } catch (err) {
    console.warn(`[KBO] ${name}: JSON 형식 오류`, err);
    throw new Error("데이터 파일이 손상돼 읽지 못했습니다.", { cause: err });
  }
}

/** 따옴표 없는 CSV(history.csv) → 객체 배열. 빈 칸은 null, 숫자처럼 보이는 칸은 숫자로 바꾼다. */
export function parseCSV(text) {
  const lines = text.replace(/\r/g, "").split("\n").filter((l) => l.trim() !== "");
  if (!lines.length) return [];
  const head = lines[0].split(",");
  return lines.slice(1).map((line) => {
    const cells = line.split(",");
    const row = {};
    head.forEach((h, i) => {
      const v = cells[i] ?? "";
      row[h] = v.trim() === "" ? null : Number.isFinite(+v) ? +v : v;
    });
    return row;
  });
}

/** data/public/{name}(CSV)을 객체 배열로 읽는다. 옵션은 fetchJSON과 같다. 실패하면 throw. */
export async function fetchCSV(name, opts = {}) {
  const res = await fetchOK(name, opts);
  return parseCSV(await res.text());
}

/**
 * 읽기 결과를 state[key]에 넣는다: 성공하면 값(그리고 state.errors[key] 삭제), 실패하면 null + state.errors[key] = 오류 문구.
 * 던지지 않으므로 Promise.all로 여러 파일을 함께 기다릴 수 있다. state에는 errors 객체가 있어야 한다.
 */
export async function settle(state, key, promise) {
  try {
    state[key] = await promise;
    delete state.errors[key];
  } catch (err) {
    state[key] = null;
    state.errors[key] = err.message;
  }
}

// ---------- 숫자·날짜 포맷 ----------

/** 유한한 숫자(또는 숫자 문자열)인가. null·undefined·""는 아니다. */
export const fin = (v) => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));

/** 0.5195 → "52%". 값이 없으면 "—". */
/** 시뮬레이션 확률: 0·1 근처는 "<1%" / ">99%" (1만 번 가상 시즌의 0%·100%를 "확정"처럼 보이지 않게). */
export function fmtProb(v) {
  if (!fin(v)) return "—";
  const x = Number(v);
  if (x < 0.005) return "<1%";
  if (x > 0.995) return ">99%";
  return fmtPct(x);
}
/** 짧은 날짜 "YYYY-MM-DD" → "11.3" (앞자리 0 없이). 형식이 다르면 그대로. */
export function fmtDateShort(iso) {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(String(iso ?? ""));
  return m ? `${+m[1]}.${+m[2]}` : String(iso ?? "—");
}
/** 점수 "원정 : 홈" — 사이트 전체 같은 모양. */
export const fmtScore = (away, home) => `${away ?? "—"} : ${home ?? "—"}`;

export function fmtPct(p, digits = 0) {
  if (!fin(p)) return "—";
  return `${(Number(p) * 100).toFixed(digits)}%`;
}

/** 야구·통계식 소수: 0.589 → ".589", 1 → "1.000", −0.12 → "-.120" (앞의 0을 뺌, 기본 3자리). 값이 없으면 "—". */
export const fmtRate3 = (v, digits = 3) => (fin(v) ? Number(v).toFixed(digits).replace(/^(-?)0\./, "$1.") : "—");

/** 1234 → "1,234". 값이 없으면 "—". */
export const fmtInt = (v) => (fin(v) ? Number(v).toLocaleString("ko-KR") : "—");

/** 시즌 목록 → "2015~2024" (하나면 "2026", 비면 "—"). */
export const fmtRange = (a) => (a?.length ? (a[0] === a.at(-1) ? `${a[0]}` : `${a[0]}~${a.at(-1)}`) : "—");

/**
 * 이닝. 데이터는 아웃카운트를 3분의 1 소수로 반올림해 저장한다(103⅓ → 103.3, 47⅔ → 47.7, 정수 이닝은 .0).
 * 소수 부분 × 3을 반올림한 아웃 수(0·1·2, 3이면 다음 이닝)로 ⅓ 표기를 만든다: 103.3 → "103⅓", 47.7 → "47⅔", 6 → "6".
 */
export function fmtInnings(v) {
  if (!fin(v)) return "—";
  const x = Number(v);
  const whole = Math.floor(x + 1e-6);
  const outs = Math.round((x - whole) * 3);
  return outs === 3 ? String(whole + 1) : `${whole}${["", "⅓", "⅔"][outs]}`;
}

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
const KST = "Asia/Seoul";

function kstParts(date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: KST, year: "numeric", month: "numeric", day: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23", weekday: "short",
  }).formatToParts(date);
  const get = (t) => parts.find((p) => p.type === t)?.value;
  const wd = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(get("weekday"));
  return { y: +get("year"), m: +get("month"), d: +get("day"), hh: get("hour"), mm: get("minute"), wd };
}

/** "2026-10-30"(또는 시각이 붙은 ISO) → "10월 30일 (금)". 날짜만 있으면 그 날짜 그대로(시간대 변환 없음). */
export function fmtDate(iso) {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (m) {
    const wd = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay();
    return `${+m[2]}월 ${+m[3]}일 (${WEEKDAYS[wd]})`;
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = kstParts(d);
  return `${p.m}월 ${p.d}일 (${WEEKDAYS[p.wd]})`;
}

/** "2026-10-30T00:11:32+09:00" → "10월 30일 00:11 KST" (보는 사람의 시간대와 상관없이 한국 시각). */
export function fmtKST(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = kstParts(d);
  return `${p.m}월 ${p.d}일 ${p.hh}:${p.mm} KST`;
}

// ---------- DOM ----------

/**
 * 요소 만들기. attrs: class, text, style(객체), dataset(객체), on* 함수, 불리언(true면 빈 속성, false/null이면 생략), 그 밖은 setAttribute.
 * children: 문자열·Node·배열(중첩 가능), null/false는 건너뜀. innerHTML은 쓰지 않는다(데이터 문자열을 그대로 글자로).
 */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "style" && typeof v === "object") {
      for (const [sk, sv] of Object.entries(v)) {
        if (sv === null || sv === undefined) continue;
        if (sk.startsWith("--")) node.style.setProperty(sk, String(sv)); else node.style[sk] = sv;
      }
    }
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  const add = (c) => {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) c.forEach(add);
    else node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  };
  add(children);
  return node;
}

/**
 * 한 경기의 적중 배지. g = { status, winner, correct } (history.csv 행이나 되감기 result — 없는 키는 무시).
 * 취소 → "취소", 무승부 → "무승부", correct 1/true → "적중", 0/false → "미적중", 그 밖(정산 전) → "결과 대기".
 */
export function verdictPill({ status, winner, correct } = {}) {
  const pill = (tone, text) => el("span", { class: `pill pill--sm pill--${tone}` }, text);
  if (status === "CANCELED") return pill("muted", "취소");
  if (winner === "DRAW") return pill("muted", "무승부");
  if (correct === true || correct === 1) return pill("ink", "적중");
  if (correct === false || correct === 0) return pill("miss", "미적중"); // 무채색 테두리 칩 (KIA 빨강 같은 팀 칩과 섞이지 않게)
  return pill("muted", "결과 대기");
}

/**
 * 한 경기의 결과 글자. g = { winner, home, away, status } (home·away = 팀 코드).
 * "KIA 승" / "무승부", 승자가 없으면 status로: FINAL "—", CANCELED "취소", 그 밖 "경기 전".
 */
export function winnerText({ winner, home, away, status } = {}) {
  if (winner === "HOME") return `${teamName(home)} 승`;
  if (winner === "AWAY") return `${teamName(away)} 승`;
  if (winner === "DRAW") return "무승부";
  return status === "FINAL" ? "—" : status === "CANCELED" ? "취소" : "경기 전";
}

/**
 * 상단 내비 정리. 페이지 HTML의 정적 <header class="topnav">를 찾아 현재 페이지(active = "index.html" 등)에
 * aria-current="page"를 붙인다. 정적 내비가 없으면(미리보기 등) 같은 구조로 만들어 <body> 맨 앞에 넣는다. 그 header를 돌려준다.
 */
export function renderNav(active) {
  let header = document.querySelector("header.topnav");
  if (!header) {
    header = el("header", { class: "topnav" }, [
      el("div", { class: "bugbar" }, el("div", { class: "bugbar__inner wrap" }, [
        el("a", { class: "brand", href: "index.html" }, [ballSVG({ cls: "brand__ball" }), "KBO PREDICT"]),
        el("div", { class: "bug-slot", id: "bug-slot" }),
        el("a", { class: "btn btn--bug", href: REPO_URL }, "GitHub에서 보기"),
      ])),
      el("nav", { class: "menubar", "aria-label": "주 메뉴" }, el("ul", { class: "wrap" }, NAV.map(([href, label]) => el("li", {}, el("a", { href }, label))))),
    ]);
    document.body.prepend(header);
  }
  header.querySelectorAll("nav a").forEach((a) => {
    if (a.getAttribute("href") === active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  return header;
}

// ---------- 그림·움직임 ----------

const SVGNS = "http://www.w3.org/2000/svg";
const svgNode = (tag, attrs = {}) => {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  return n;
};

/** 야구공 그림(흰 공 + 빨간 실밥). spin이면 천천히 돈다(움직임 줄이기 설정이면 멈춤). 장식이라 aria-hidden. */
export function ballSVG({ cls = "", spin = false } = {}) {
  const svg = svgNode("svg", { viewBox: "0 0 24 24", class: `ball ${cls}${spin ? " ball--spin" : ""}`.trim(), "aria-hidden": "true", focusable: "false" });
  const seam = "M6.6 3.6c2.6 2.6 2.6 14.2 0 16.8M17.4 3.6c-2.6 2.6-2.6 14.2 0 16.8";
  svg.append(
    svgNode("circle", { cx: 12, cy: 12, r: 10.5, fill: "#fff", stroke: "rgba(0,0,0,.12)", "stroke-width": 0.6 }),
    svgNode("path", { d: seam, fill: "none", stroke: "#d8232a", "stroke-width": 1.3 }),
    svgNode("path", { d: seam, fill: "none", stroke: "#d8232a", "stroke-width": 3, "stroke-dasharray": "0.9 1.6" }),
  );
  return svg;
}

export const REDUCED_MOTION = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

/** node가 화면에 들어오면 fn을 한 번 부른다(IntersectionObserver가 없으면 바로). */
export function whenVisible(node, fn) {
  if (!node || typeof IntersectionObserver === "undefined") { fn(); return; }
  const io = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { io.disconnect(); fn(); }
  }, { threshold: 0.2 });
  io.observe(node);
}

/**
 * 숫자 세어 올리기: node의 글자를 from → to로 dur ms 동안 바꾼다(끝값은 정확히 fmt(to)). 화면에 들어올 때 시작.
 * 움직임 줄이기 설정이면 바로 끝값. 같은 node에 다시 부르면 이전 것은 멈춘다.
 */
export function countUp(node, to, { from = 0, dur = 900, fmt = (v) => String(Math.round(v)) } = {}) {
  if (!node || !fin(to)) return;
  const end = Number(to);
  node._countToken = (node._countToken ?? 0) + 1;
  const token = node._countToken;
  if (REDUCED_MOTION) { node.textContent = fmt(end); return; }
  node.textContent = fmt(from);
  whenVisible(node, () => {
    const t0 = performance.now();
    const step = (t) => {
      if (node._countToken !== token) return;
      const k = Math.min(1, (t - t0) / dur);
      const e = 1 - (1 - k) ** 3;
      node.textContent = fmt(k < 1 ? from + (end - from) * e : end);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

function runId(url) {
  const m = /\/runs\/(\d+)/.exec(url ?? "");
  return m ? m[1] : null;
}

/**
 * 푸터 증거 바(#evidence)를 status.json으로 채운다:
 * "마지막 갱신 {KST}. 자동 실행 기록 #{run}, 코드 버전 {sha7}, 예측 모델 {version}" — 실행·커밋·모델은 링크.
 * run_url이 null이면 "내 컴퓨터에서 실행"(링크 없음). status가 없으면(읽기 실패) 그 사실을 적는다. 채운 요소를 돌려준다.
 */
export function renderFooter(status, mount = document.getElementById("evidence")) {
  if (!mount) return null;
  if (!status) {
    mount.replaceChildren("갱신 정보를 불러오지 못했습니다. 데이터는 GitHub 저장소에서 직접 볼 수 있습니다.");
    return mount;
  }
  const sep = () => ", ";
  const link = (href, text, label) => el("a", { href, "aria-label": label }, text);
  const id = runId(status.run_url);
  const sha = status.commit_sha ?? null;
  // 자동 실행 기록 = GitHub Actions가 매일 데이터를 모으고 예측을 올린 실행
  const run = !status.run_url ? ["내 컴퓨터에서 실행"]
    : id ? [el("span", { title: "GitHub Actions가 매일 데이터를 모으고 예측을 올린 실행입니다" }, "자동 실행 기록 "), link(status.run_url, `#${id}`, `GitHub Actions 실행 ${id} 기록 열기`)]
    : [link(status.run_url, "자동 실행 기록", "GitHub Actions 실행 기록 열기")];
  const commit = sha
    ? ["코드 버전 ", link(`${REPO_URL}/commit/${sha}`, sha.slice(0, 7), `커밋 ${sha.slice(0, 7)} 보기`)]
    : ["코드 버전 —"];
  const model = status.model_version
    ? ["예측 모델 ", link(`${REPO_URL}#모델`, status.model_version, `모델 ${status.model_version} 설명 (README) 열기`)]
    : ["예측 모델 —"];
  mount.replaceChildren(`마지막 갱신 ${fmtKST(status.generated_at)}. `, ...run, sep(), ...commit, sep(), ...model);
  return mount;
}

/**
 * 읽기 실패 화면: 무엇이 안 됐는지 + "다시 불러오기" 버튼(retryFn이 있을 때). 빈 화면 대신 쓴다.
 * el 안을 이 상자로 바꾸고 상자를 돌려준다.
 */
export function showError(target, message, retryFn) {
  const box = el("div", { class: "error-box", role: "alert" }, [
    el("p", {}, [el("strong", {}, "데이터를 불러오지 못했습니다. "), message ?? ""]),
    retryFn ? el("button", { class: "btn btn--secondary", type: "button", onclick: () => retryFn() }, "다시 불러오기") : null,
  ]);
  target.replaceChildren(box);
  return box;
}
