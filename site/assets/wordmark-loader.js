// 이번 시즌 페이지 머리 띠: 글자 효과 묶음(wordmark.js, Preact 포함 약 31KB · 압축 약 13KB)을 필요한 화면에서만 불러온다.
// - 마우스가 있는 화면(hover + 정밀 포인터)이고 "동작 줄이기"를 켜지 않았을 때만, 페이지가 다 뜬 뒤(load + 한가할 때) 받는다.
//   예측·순위 같은 본문이 먼저 그려지게.
// - 그 밖(휴대폰·태블릿·동작 줄이기)은 받지 않고, 같은 글꼴의 정지된 윤곽 글자로 보인다(home.css .wm-band:not(.is-live)).
// 묶음 소스: web/src/wordmark.tsx (Originkit Vector Wordmark 3).
const WORD = "Baseball";
const mount = document.getElementById("wm-stage");
if (mount) {
  mount.textContent = WORD; // 묶음이 오기 전·오지 않는 화면의 모습
  const wantsEffect = window.matchMedia("(hover: hover) and (pointer: fine)").matches
    && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (wantsEffect) {
    const load = () => {
      const s = document.createElement("script");
      s.src = "assets/wordmark.js";
      document.head.append(s);
    };
    const idle = () => ("requestIdleCallback" in window ? requestIdleCallback(load, { timeout: 2000 }) : setTimeout(load, 300));
    if (document.readyState === "complete") idle(); else window.addEventListener("load", idle, { once: true });
  }
}
