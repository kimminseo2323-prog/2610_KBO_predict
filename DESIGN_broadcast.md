---
name: KBO Predict Broadcast
description: 야구 중계 그래픽의 문법을 빌린 데이터 사이트 디자인 시스템. 흰 바탕과 잉크에 그날 경기 두 구단의 색만 면으로 쓰고, 각진 모서리·좁은 이탤릭 숫자·굵은 선으로 시작하는 섹션으로 짠다. 움직임은 데이터가 자라나는 것(경계가 승률로 밀림, 숫자 세어 올리기, 막대 성장, 선 그리기)만 쓴다.
colors:
  canvas: "#ffffff"
  surface-soft: "#f4f4f6"
  surface-card: "#f4f4f6"
  surface-strong: "#e7e8eb"
  ink: "#1c2127"
  brand: "#1c2127"
  brand-deep: "#0f1317"
  body: "#2b2d31"
  muted: "#5a5e66"
  hairline: "#e3e4e7"
  series-pink: "#e8336f"
  series-teal: "#1d4e4a"
  series-lavender: "#8f7ad6"
  series-peach: "#f08c4f"
  series-ochre: "#d9a521"
  series-mint: "#5fb39b"
  series-coral: "#e5483a"
  team-lg: "#c30452"
  team-ob: "#131230"
  team-ht: "#ea0029"
  team-ss: "#074ca1"
  team-lt: "#041e42"
  team-sk: "#ffb81c"
  team-kt: "#000000"
  team-nc: "#315288"
  team-hh: "#fc4e00"
  team-wo: "#570514"
  team-sk-ink: "#9a6a00"
  team-hh-ink: "#c43c00"
rounded:
  md: "2px"
  lg: "0"
  xl: "0"
rule: "4px"
typography:
  display-lg:
    fontSize: 52px
    fontWeight: 900
    lineHeight: 1.05
    letterSpacing: -2px
  display-md:
    fontSize: 40px
    fontWeight: 900
    lineHeight: 1.1
    letterSpacing: -1.2px
  display-sm:
    fontSize: 30px
    fontWeight: 900
    lineHeight: 1.15
    letterSpacing: -0.8px
  title-lg:
    fontSize: 22px
    fontWeight: 900
    lineHeight: 1.3
    letterSpacing: -0.6px
  title-md:
    fontSize: 18px
    fontWeight: 800
    lineHeight: 1.4
    letterSpacing: -0.3px
  title-sm:
    fontSize: 15px
    fontWeight: 800
    lineHeight: 1.4
    letterSpacing: 0
  body-md:
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0
  body-sm:
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0
  caption:
    fontSize: 12px
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: 0
  num-xl:
    fontSize: 150px
    fontWeight: 800
    lineHeight: 0.82
    letterSpacing: -3px
---

# KBO Predict — 중계 그래픽 디자인 시스템

2026-11 사용자 요청("AI가 만든 티가 난다", "글이 너무 많다")으로 크림 캔버스·파스텔 카드의 Clay 시스템([DESIGN_clay.md](DESIGN_clay.md), 기록용으로 남김)을 대체했다. 토큰 값은 위 머리말이 기준이고 `site/assets/tokens.css`가 그대로 옮긴다(`tests/test_site.py::test_tokens_match_design_md`).

## 원칙

- **우세한 팀은 그 팀 색으로.** 두 팀 중 확률이 더 높은 쪽(경기 승률, 시리즈 승리, 가을야구 진출, 요인이 민 쪽)의 이름·숫자는
  그 팀 색이다. 대표 숫자는 팀 칩(면 = 대표색, 글자 = 흰색과 잉크 중 대비가 높은 쪽), 문장 속 이름·작은 숫자는 팀 글자색
  (`--team-<코드>`, 밝은 SSG·한화는 `--team-<코드>-ink`, 검정 KT는 칩). 반올림해 50 대 50이면 어느 쪽도 칠하지 않는다.
  열세 쪽 큰 숫자는 흐리게 하지 않고 속이 빈 외곽선 숫자로 낮춘다(대비 유지). 적중·미적중 판정 칩은 팀 색과 겹치지 않게 무채색.
- **틀은 흰 바탕 + 짙은 회청색 잉크(#1c2127), 색은 팀에게만.** 맨 위 띠는 흰 바탕(브랜드 + 시리즈 전적 칩), 메뉴 밑줄·섹션 굵은 선·상태 칩은
  잉크. 예전에는 틀이 순검정이었는데 KT 구단색이 순검정이라 사이트 전체가 KT처럼 보였고(2026-11 사용자 지적), 잔디 녹색 띠는
  한 줄만 따로 놀아 어색했다. MLB·Savant처럼 틀은 중립으로 두고, 팀은 구단색과 로고로만 구분한다. 순검정(#000)은 KT 요소에만 남는다.
- **면 색은 두 팀 색뿐.** 오늘 경기 슬랩, 스코어 버그의 전적 칸, 순위표 행의 띠, 선수 카드의 띠처럼 "그 팀"을 가리키는 곳에만 구단 대표색(`--team-<코드>`)을 쓴다. 나머지는 흰 바탕(`canvas`), 잉크, 옅은 회색(`surface-card`)이다. 파스텔 카드 면은 쓰지 않는다.
- **선수 유형 계열색**(`series-*`, CSS 변수 `--pink` 등)은 점·막대·태그 같은 데이터 표시에만 쓴다.
- **섹션은 굵은 선으로 시작한다.** `.card` = 위 4px 잉크 선 + 900 굵기 제목 + 한 줄 리드. 둥근 카드·그림자·테두리 상자를 쓰지 않는다.
- **각진 모서리.** 면과 패널은 0, 작은 태그와 버튼만 2px. 사선(clip-path, 각도 그레이디언트)으로 두 면을 맞붙인다.
- **숫자는 좁은 이탤릭(Barlow Condensed 700~800).** 확률·순위·기록처럼 읽을 숫자가 화면의 주인공이다. 한글은 Pretendard 800~900으로 짧게.
- **글은 줄인다.** 리드는 한 줄. 표 읽는 법·주의할 점처럼 긴 설명은 `details.more`("표 읽는 법") 안에 접어 둔다. 값의 세부는 마우스를 올리거나 탭하면 뜨는 툴팁으로.

## 컴포넌트

- **스코어 버그(`.bugbar`)**: 맨 위 검정 띠. 왼쪽 야구공 그림 + "KBO PREDICT", 홈 라이브 시리즈 중에는 오른쪽에 두 팀 전적 칸(팀 색 면). 그 아래 흰 메뉴 줄, 현재 페이지에 4px 잉크 밑줄.
- **매치업 슬랩**: 원정·홈 구단 색 면이 사선으로 맞붙고, 경계는 원정 승률 위치(38~62%로 제한)로 밀린다. 가운데 회전하는 야구공 VS, 양쪽 큰 이탤릭 승률, 아래 흰 자막 띠("가장 크게 움직인 요인"). 글자색은 면 색 밝기로 정한다(어두우면 흰색, 밝으면 잉크).
- **테일 오브 더 테이프(`.tape`)**: 가운데 항목 이름, 양쪽 값과 팀 색 막대. 더 나은 쪽 값은 잉크·굵게.
- **판결 무대(성적표)**: 왼쪽 잉크 "좋은 숫자"와 오른쪽 회색 "한계"를 같은 크기로 사선 경계에 맞붙인다.
- **선수 카드**: 중계 선수 소개 자막처럼 잉크 면 + 왼쪽 구단 색 띠 + 큰 흰 이름.
- **핍(`.pips`, `.live__pips`)**: 시리즈 승수·라이브 적중을 기울어진 칸으로 센다.

## 움직임

데이터가 자라나는 움직임만 쓴다. 섹션 전체가 페이드·슬라이드로 들어오는 효과는 쓰지 않는다.

- 슬랩 경계가 50%에서 승률 쪽으로 밀리고, 큰 숫자가 50에서 세어 올라간다(`countUp`).
- 차트는 화면에 들어올 때 한 번: 막대는 0에서 값까지(`.c-bar`, `.c-col`), 선은 왼쪽에서 오른쪽으로 그려지고(`.c-lines`), 점은 튀어나온다(`.c-point`).
- 순위표 행은 위에서부터 차례로 밀려 들어오고, 선수 카드는 고를 때마다 이름이 밀려 들어온다.
- `prefers-reduced-motion`이면 모두 끈다(app.css 마지막 절).
