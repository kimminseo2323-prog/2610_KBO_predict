// 이번 시즌 페이지 머리 띠의 글자 효과. `npm run build`(web/)가 site/assets/wordmark.js 한 파일로 묶는다.
//
// - 컴포넌트는 Originkit Vector Wordmark 3를 이 사이트용으로 수정한 것(components/originkit/vector-wordmark-03.tsx 맨 위 주석:
//   글자·글꼴·색 기본값, 최소 크기 바닥값 제거). React 대신 Preact로 묶는다(package.json의 alias) — 이 컴포넌트는 useEffect·useRef만 쓴다.
// - 이 묶음은 site/assets/wordmark-loader.js가 마우스가 있는 화면에서만, 페이지가 다 뜬 뒤에 불러온다.
import { createRoot } from "react-dom/client"
import VectorWordmark from "./components/originkit/vector-wordmark-03"

const mount = document.getElementById("wm-stage")
if (mount) {
  mount.textContent = ""
  document.getElementById("wm-band")?.classList.add("is-live")
  createRoot(mount).render(<VectorWordmark />)  // 글자·글꼴·색은 컴포넌트 기본값(사이트용으로 수정됨)
}
