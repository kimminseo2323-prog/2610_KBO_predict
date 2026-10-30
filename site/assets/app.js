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

/** 데이터 위치: 로컬이면 저장소의 data/public, 배포본(GitHub Pages 등)이면 raw.githubusercontent.com. */
export const DATA_BASE = IS_LOCAL ? "../data/public" : RAW_BASE;

/** 메뉴 4개 — 순서·이름 고정 (check_site.py의 NAV와 같다). */
export const NAV = [
  ["index.html", "오늘의 경기"],
  ["teams.html", "팀"],
  ["players.html", "선수"],
  ["report.html", "모델 성적표"],
];

// 10구단: 코드 → 한글 이름(ko, teams.py와 같음), 정식 이름(full), 차트 축용 짧은 이름(short), 강조색(color = 토큰 이름).
// 색은 팔레트 8색(카드 6색 + 민트·코랄) 안에서 구단 상징색에 가까운 것을 골랐다. 겹치는 색이 있으므로
// 색만으로 팀을 구분하지 말고 항상 이름을 함께 쓴다.
export const TEAMS = {
  "OB": {"ko": "두산", "full": "두산 베어스", "short": "두산", "color": "teal"},
  "LT": {"ko": "롯데", "full": "롯데 자이언츠", "short": "롯데", "color": "coral"},
  "KT": {"ko": "KT", "full": "KT 위즈", "short": "KT", "color": "mint"},
  "WO": {"ko": "키움", "full": "키움 히어로즈", "short": "키움", "color": "pink"},
  "SK": {"ko": "SSG", "full": "SSG 랜더스", "short": "SSG", "color": "ochre"},
  "SS": {"ko": "삼성", "full": "삼성 라이온즈", "short": "삼성", "color": "lavender"},
  "HH": {"ko": "한화", "full": "한화 이글스", "short": "한화", "color": "peach"},
  "HT": {"ko": "KIA", "full": "KIA 타이거즈", "short": "KIA", "color": "coral"},
  "LG": {"ko": "LG", "full": "LG 트윈스", "short": "LG", "color": "pink"},
  "NC": {"ko": "NC", "full": "NC 다이노스", "short": "NC", "color": "ochre"}
};

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
  "bias": "기본 홈 어드밴티지"
};

// 선수 유형 색 (유형 id는 config/cluster_labels.yaml). 타자: 파워형 핑크 · 장타 지향형 피치 · 컨택형 틸 · 주루형 라벤더.
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
    throw new Error(`${name}을(를) 받지 못했습니다 (네트워크 오류).`, { cause: err });
  }
  if (!res.ok) throw new Error(`${name}을(를) 받지 못했습니다 (HTTP ${res.status}).`);
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
    throw new Error(`${name}의 형식이 올바르지 않습니다.`, { cause: err });
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
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
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
  if (correct === false || correct === 0) return pill("coral", "미적중");
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
    header = el("header", { class: "topnav" }, el("div", { class: "topnav__inner wrap" }, [
      el("a", { class: "brand", href: "index.html" }, [el("i", { class: "brand__mark", "aria-hidden": "true" }), "KBO Predict"]),
      el("nav", { "aria-label": "주 메뉴" }, el("ul", {}, NAV.map(([href, label]) => el("li", {}, el("a", { href }, label))))),
      el("a", { class: "btn", href: REPO_URL }, "GitHub에서 보기"),
    ]));
    document.body.prepend(header);
  }
  header.querySelectorAll("nav a").forEach((a) => {
    if (a.getAttribute("href") === active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  return header;
}

function runId(url) {
  const m = /\/runs\/(\d+)/.exec(url ?? "");
  return m ? m[1] : null;
}

/**
 * 푸터 증거 바(#evidence)를 status.json으로 채운다:
 * "마지막 갱신 {KST} · Actions 실행 #{run} · 커밋 {sha7} · 모델 {version}" — 실행·커밋·모델은 링크.
 * run_url이 null이면 "로컬 실행"(링크 없음). status가 없으면(읽기 실패) 그 사실을 적는다. 채운 요소를 돌려준다.
 */
export function renderFooter(status, mount = document.getElementById("evidence")) {
  if (!mount) return null;
  if (!status) {
    mount.replaceChildren("갱신 정보(status.json)를 불러오지 못했습니다. 데이터는 아래 저장소에서 직접 확인할 수 있습니다.");
    return mount;
  }
  const sep = () => " · ";
  const link = (href, text, label) => el("a", { href, "aria-label": label }, text);
  const id = runId(status.run_url);
  const sha = status.commit_sha ?? null;
  const run = !status.run_url ? ["로컬 실행"]
    : id ? ["Actions 실행 ", link(status.run_url, `#${id}`, `GitHub Actions 실행 ${id} 기록 열기`)]
    : [link(status.run_url, "Actions 실행 기록", "GitHub Actions 실행 기록 열기")];
  const commit = sha
    ? ["커밋 ", link(`${REPO_URL}/commit/${sha}`, sha.slice(0, 7), `커밋 ${sha.slice(0, 7)} 보기`)]
    : ["커밋 —"];
  const model = status.model_version
    ? ["모델 ", link(`${REPO_URL}#모델`, status.model_version, `모델 ${status.model_version} 설명 (README) 열기`)]
    : ["모델 —"];
  mount.replaceChildren(`마지막 갱신 ${fmtKST(status.generated_at)}`, sep(), ...run, sep(), ...commit, sep(), ...model);
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
