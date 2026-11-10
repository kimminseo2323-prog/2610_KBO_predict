// 이번 시즌 페이지 머리 띠의 글자 효과. `npm run build`(web/)가 site/assets/wordmark.js 한 파일로 묶는다.
//
// - 컴포넌트는 Originkit Vector Wordmark 3 원본 그대로(components/originkit/vector-wordmark-03.tsx).
//   React 대신 Preact로 묶는다(package.json의 alias) — 쓰는 법이 같고, 이 컴포넌트는 useEffect·useRef만 써서 그대로 돈다.
// - 사이트에 맞춘 것은 넘겨주는 값뿐: 글꼴 = 사이트 숫자 글꼴(Barlow Condensed 굵은 기울임), 바탕 = 잉크(--ink),
//   강조색 = 로고 공의 실밥 빨강, 최소 크기(컴포넌트 기본 1200×800) 해제 — 띠 높이에 맞춘다.
// - 이 묶음은 site/assets/wordmark-loader.js가 마우스가 있는 화면에서만, 페이지가 다 뜬 뒤에 불러온다.
import { createRoot } from "react-dom/client"
import VectorWordmark from "./components/originkit/vector-wordmark-03"

const WORD = "Baseball"

const mount = document.getElementById("wm-stage")
if (mount) {
  mount.textContent = ""
  document.getElementById("wm-band")?.classList.add("is-live")
  createRoot(mount).render(
    <VectorWordmark
      text={WORD}
      font={{ fontFamily: "Barlow Condensed", fontWeight: 800, fontStyle: "italic", fontSize: 210, letterSpacing: "0em", lineHeight: "1em" }}
      background="#1c2127"
      textColor="#f4f4f6"
      shade="#2b313a"
      accent="rgba(216, 35, 42, 0.9)"
      style={{ minWidth: 0, minHeight: 0 }}
    />,
  )
}
