// Top-bar brand line: "ENGINEERING" decodes like a robot terminal, letter by letter,
// on load and again every few seconds while the app is visible.
import { $ } from "./core.js?v=20261009-warp-centred";

const WORD = "ENGINEERING";
const GLYPHS = "01#<>/\\[]{}=+*%$&ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const FRAME_MS = 55;
const REPLAY_MS = 9000;

function decode(element) {
  let frame = 0;
  const total = WORD.length * 2 + 6;
  element.classList.add("decoding");
  const timer = setInterval(() => {
    const locked = Math.floor((frame - 4) / 2);
    element.textContent = [...WORD].map((letter, index) =>
      index <= locked ? letter : GLYPHS[Math.floor(Math.random() * GLYPHS.length)]).join("");
    frame += 1;
    if (frame > total) {
      clearInterval(timer);
      element.textContent = WORD;
      element.classList.remove("decoding");
    }
  }, FRAME_MS);
}

export function init() {
  const element = $("brandEngineering");
  if (!element) return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  const visible = () => !document.hidden && !$("appView").classList.contains("hidden") && element.offsetParent !== null;
  // First decode as soon as the app is shown, then on a gentle loop.
  const waitForApp = setInterval(() => { if (visible()) { clearInterval(waitForApp); decode(element); } }, 400);
  setInterval(() => { if (visible() && !element.classList.contains("decoding")) decode(element); }, REPLAY_MS);
}
