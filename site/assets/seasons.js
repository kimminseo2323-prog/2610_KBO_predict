// KBO Predict — 지난 시즌: 연도별 우승 팀, 한국시리즈 경기별 결과, 우승까지의 길(가을야구 대진), 최종 순위, 그 시즌 모델 성적.
// 데이터: seasons/index.json(연도 목록·우승 팀), seasons/{season}.json (kbo_predict.season_archive), history.csv(2026 공개 예측).
// 주소: seasons.html?season=2024 로 바로 열 수 있다.

import {
  STADIUMS, el, fetchJSON, fetchCSV, settle, fmtDate, fmtDateShort, fmtPct, teamName, teamColors, teamChip, teamLogo,
  renderNav, renderFooter, showError,
} from "./app.js";

const REPORT_SEASON = 2026;   // 모델 성적표(report-2026)의 홀드아웃 시즌 — 다시 보기가 여러 시즌 시험과 다른 모델을 쓰는 유일한 시즌
const $ = (id) => document.getElementById(id);
const state = { index: null, status: null, history: null, cache: new Map(), season: null, errors: {} };

const where = (g) => STADIUMS[g.stadium] ?? g.stadium ?? "";
const score = (g) => `${g.away_score} : ${g.home_score}`;

/** 팀별 가을야구 결과 한 줄: 우승 / 준우승 / ○○ 탈락 / 진출 실패. */
function postseasonFate(rec) {
  const fate = new Map();
  for (const s of rec.postseason) {
    if (s.name === "순위 결정전") continue;
    const loser = s.teams.find((t) => t !== s.winner);
    fate.set(loser, s.name === "한국시리즈" ? "준우승" : `${s.name} 탈락`);
    if (s.name === "한국시리즈") fate.set(s.winner, "우승");
  }
  return (code) => fate.get(code) ?? "";
}

function renderYears() {
  const nav = $("years");
  nav.replaceChildren(el("ol", { class: "years__list" }, state.index.seasons.slice().reverse().map((y) =>
    el("li", {}, el("button", {
      class: "years__btn", type: "button", "aria-pressed": String(y.season === state.season),
      onclick: () => open(y.season, { push: true }),
    }, [el("span", { class: "years__y" }, String(y.season)), y.champion ? teamLogo(y.champion, { size: "sm" }) : null,
      el("span", { class: "years__c" }, y.champion ? teamName(y.champion) : "—")])))));
}

async function loadSeason(season) {
  if (!state.cache.has(season)) state.cache.set(season, fetchJSON(`seasons/${season}.json`));
  try { return await state.cache.get(season); } catch (e) { state.cache.delete(season); throw e; }
}

async function open(season, { push = false } = {}) {
  state.season = season;
  renderYears();
  if (push) history.replaceState(null, "", `?season=${season}`);
  const box = $("season");
  box.setAttribute("aria-busy", "true");
  let rec;
  try { rec = await loadSeason(season); } catch (e) { showError(box, e.message, () => open(season)); return; }
  box.removeAttribute("aria-busy");
  renderSeason(rec);
}

function renderSeason(rec) {
  const box = $("season");
  const ks = rec.postseason.at(-1);
  const champ = rec.champion, runner = rec.runner_up;
  const played = ks.games.filter((g) => g.status === "FINAL");
  const last = played.at(-1);
  const cw = ks.wins[ks.teams.indexOf(champ)], cl = ks.wins[ks.teams.indexOf(runner)];
  const tc = teamColors(champ);
  // 2026은 경기 전에 공개한 예측이 있다 (history.csv)
  const pub = new Map((state.history ?? []).filter((h) => String(h.date).startsWith(String(rec.season))).map((h) => [Number(h.game_id), h]));

  const hero = el("div", { class: "season__hero", style: { background: tc.bg, color: tc.fg } }, [
    teamLogo(champ, { season: rec.season, size: "lg" }),
    el("div", { class: "season__hero-text" }, [
      el("p", { class: "season__kicker" }, `${rec.season} 한국시리즈 우승`),
      el("p", { class: "season__champ" }, teamName(champ)),
      el("p", { class: "season__line" }, `${teamName(runner)}에 ${cw}승 ${cl}패. ${fmtDate(last.date)} ${where(last)} ${played.length}차전 ${teamName(last.away)} ${score(last)} ${teamName(last.home)}로 확정.`),
    ]),
  ]);

  let n = 0;
  const tile = (g) => {
    if (g.status !== "FINAL") return el("li", { class: "ks-game is-canceled" }, [el("span", { class: "ks-game__no" }, "취소"), el("span", { class: "ks-game__meta" }, fmtDateShort(g.date))]);
    n += 1;
    const p = pub.get(g.game_id);
    const prob = p ? Number(p.home_win_prob) : null;
    const pick = p ? (prob >= 0.5 ? g.home : g.away) : null;
    return el("li", { class: "ks-game" }, [
      el("span", { class: "ks-game__no" }, `${n}차전`),
      el("span", { class: "ks-game__meta" }, `${fmtDateShort(g.date)} ${where(g)}`),
      el("span", { class: "ks-game__score" }, [
        el("span", { class: g.winner === g.away ? "is-win" : null }, teamName(g.away)), el("b", { class: "num" }, score(g)),
        el("span", { class: g.winner === g.home ? "is-win" : null }, teamName(g.home)),
      ]),
      teamChip(g.winner, `${teamName(g.winner)} 승`, "tchip--sm"),
      ...(p ? [el("span", { class: "ks-game__pred" }, [`예측 ${teamName(pick)} ${Math.round(Math.max(prob, 1 - prob) * 100)}% `,
        el("b", { class: Number(p.correct) ? "is-hit" : "is-miss" }, Number(p.correct) ? "적중" : "미적중")])] : []),
    ]);
  };

  const headNote = (s) => s.head_start.some(Boolean) ? `${teamName(s.teams[0])} 1승 안고 시작` : s.name === "순위 결정전" ? "정규시즌 1위 결정 단판" : "";
  const road = el("ol", { class: "road" }, rec.postseason.map((s) => {
    const w = s.winner, l = s.teams.find((t) => t !== w);
    return el("li", { class: "road__row" }, [
      el("span", { class: "road__name" }, s.name),
      el("span", { class: "road__match" }, [teamChip(w, `${teamName(w)} ${s.wins[s.teams.indexOf(w)]}`, "tchip--sm"), el("span", { class: "road__vs" }, ":"),
        el("span", { class: "road__loser" }, `${s.wins[s.teams.indexOf(l)]} ${teamName(l)}`)]),
      el("span", { class: "road__note" }, headNote(s)),
      el("span", { class: "road__dots", "aria-hidden": "true" }, s.games.filter((g) => g.status === "FINAL").map((g) =>
        el("i", { style: { background: teamColors(g.winner).bg }, title: `${fmtDateShort(g.date)} ${teamName(g.away)} ${score(g)} ${teamName(g.home)}` }))),
    ]);
  }));

  const fate = postseasonFate(rec);
  const table = el("div", { class: "table-scroll" }, el("table", { class: "table st-table" }, [
    el("caption", { class: "sr-only" }, `${rec.season} 정규시즌 최종 순위`),
    el("thead", {}, el("tr", {}, [["순위"], ["팀"], ["승", "num"], ["패", "num"], ["무", "num"], ["승률", "num"], ["게임차", "num"], ["득실차", "num col-rd"], ["가을야구"]]
      .map(([t, c]) => el("th", { scope: "col", class: c ?? null }, t)))),
    el("tbody", {}, rec.standings.map((r) => el("tr", { class: r.code === champ ? "is-champ" : null }, [
      el("td", { class: "num" }, String(r.rank)),
      el("td", {}, el("span", { class: "st-team" }, [teamLogo(r.code, { season: rec.season, size: "sm" }), teamName(r.code)])),
      el("td", { class: "num" }, String(r.w)), el("td", { class: "num" }, String(r.l)), el("td", { class: "num" }, String(r.d)),
      el("td", { class: "num" }, r.pct.toFixed(3).replace(/^0/, "")), el("td", { class: "num" }, r.gb ? r.gb.toFixed(1) : "—"),
      el("td", { class: "num col-rd" }, `${r.run_diff > 0 ? "+" : ""}${r.run_diff}`),
      el("td", { class: "st-fate" }, fate(r.code) === "우승" ? teamChip(r.code, "우승", "tchip--sm") : fate(r.code)),
    ]))),
  ]));

  const m = rec.model;
  const modelCard = el("div", { class: "season__model" }, [
    el("h3", { class: "season__h" }, "이 시즌, 모델은 얼마나 맞혔나"),
    m ? el("p", { class: "season__model-num" }, [el("b", { class: "num" }, fmtPct(m.accuracy, 1)), ` 정규시즌 ${m.n}경기 적중 (단순 규칙 ${fmtPct(m.rule_accuracy, 1)})`])
      : el("p", { class: "season__model-num muted" }, "이 시즌은 앞선 학습 시즌이 부족해 시험하지 않았습니다(시험은 2018년부터)."),
    el("p", { class: "season__model-note" }, rec.season === REPORT_SEASON
      ? `그 시즌보다 앞선 시즌(2025까지)으로 학습한 지금 모델(v0.3) 설정의 성적입니다. 경기일 다시 보기는 모델 성적표의 고정 모델(2024까지 학습·2025 검증)로 예측해 적중률이 조금 다릅니다.${rec.rewind ? " 경기일마다 그날의 예측과 결과를 다시 볼 수 있습니다." : ""}`
      : `그 시즌보다 앞선 시즌들로만 학습한 지금 모델(v0.3) 설정으로 그 시즌을 미리 예측했다면의 성적입니다.${rec.rewind ? " 경기일마다 그날의 예측과 결과를 다시 볼 수 있습니다." : ""}`),
    ...(rec.rewind ? [el("a", { class: "btn", href: `replay.html?season=${rec.season}` }, `${rec.season} 경기일 다시 보기`)] : []),
  ]);

  box.replaceChildren(
    hero,
    el("div", { class: "season__grid" }, [
      el("div", {}, [el("h3", { class: "season__h" }, "한국시리즈 경기별 결과"), el("ol", { class: "ks-games" }, ks.games.map(tile))]),
      el("div", {}, [el("h3", { class: "season__h" }, "우승까지의 길"), road, modelCard]),
    ]),
    el("div", { class: "season__table" }, [el("h3", { class: "season__h" }, `${rec.season} 정규시즌 최종 순위`), table]),
  );
}

async function init() {
  renderNav("seasons.html");
  await Promise.all([settle(state, "index", fetchJSON("seasons/index.json", { fresh: true })), settle(state, "status", fetchJSON("status.json", { fresh: true })),
    settle(state, "history", fetchCSV("history.csv", { fresh: true }))]);
  renderFooter(state.status);
  if (!state.index) { showError($("season"), state.errors.index, init); return; }
  const seasons = state.index.seasons.map((s) => s.season);
  const want = Number(new URLSearchParams(location.search).get("season"));
  $("seasons-lead").textContent = `${seasons[0]}~${seasons.at(-1)} 시즌을 고르면 그해 우승 팀과 한국시리즈 경기, 가을야구 대진, 최종 순위를 봅니다.`;
  open(seasons.includes(want) ? want : seasons.at(-1));
}

init();
