// Sign-in page polish: live server status, Enter-to-submit, busy button, show/hide password,
// Caps Lock warning, error shake, a rotating feature line and a pointer spotlight on the card.
import { $, state } from "./core.js?v=20261009-login-premium";

const FEATURES = [
  "Synchronized Plan · Profile · Cross · 3D evidence",
  "Pole base and top picked straight from LiDAR",
  "Workbook QC with traceable rule findings",
  "Team progress, assignments and deliverables",
  "LAS / LAZ to COPC streaming for huge corridors",
];

const loginVisible = () => !$("loginView").classList.contains("hidden");

function serverStatus() {
  const dot = $("loginStatusDot"), text = $("loginServerStatus");
  let retry = null;
  const check = async () => {
    clearTimeout(retry);
    try {
      const response = await fetch(state.apiBase.replace(/\/$/, "") + "/api/system/info", { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      const info = await response.json();
      const where = info.app_env && info.app_env !== "production" ? ` · ${info.app_env}` : "";
      dot.className = "login-status-dot online";
      text.textContent = `Server online · v${String(info.version || "").split("-")[0] || "—"}${where}`;
    } catch {
      dot.className = "login-status-dot offline";
      text.textContent = "Server unreachable — retrying";
      retry = setTimeout(() => { if (loginVisible()) check(); }, 15000);
    }
  };
  check();
}

function busyButton() {
  const button = $("loginBtn"), original = button.onclick;
  if (!original) return;
  button.onclick = async event => {
    if (button.classList.contains("busy")) return;
    button.classList.add("busy"); button.disabled = true; button.setAttribute("aria-busy", "true");
    try { await original.call(button, event); }
    finally { button.classList.remove("busy"); button.disabled = false; button.removeAttribute("aria-busy"); }
  };
  $("email").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); $("password").focus(); } });
  $("password").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); button.click(); } });
}

function passwordTools() {
  const input = $("password"), toggle = $("passwordToggle"), caps = $("capsLockNote");
  toggle.onclick = () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    toggle.setAttribute("aria-pressed", String(show));
    toggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
    toggle.title = show ? "Hide password" : "Show password";
    toggle.classList.toggle("on", show);
    input.focus();
  };
  const capsCheck = event => { if (event.getModifierState) caps.classList.toggle("hidden", !event.getModifierState("CapsLock")); };
  input.addEventListener("keydown", capsCheck);
  input.addEventListener("keyup", capsCheck);
  input.addEventListener("blur", () => caps.classList.add("hidden"));
}

function errorShake() {
  const card = document.querySelector("#loginView .login-card"), error = $("loginError");
  new MutationObserver(() => {
    if (!error.textContent.trim()) return;
    card.classList.remove("shake"); void card.offsetWidth; card.classList.add("shake");
  }).observe(error, { childList: true, characterData: true, subtree: true });
  card.addEventListener("animationend", event => { if (event.animationName === "loginShake") card.classList.remove("shake"); });
}

function featureTicker() {
  const ticker = $("loginTicker");
  let index = 0;
  setInterval(() => {
    if (!loginVisible() || document.hidden) return;
    index = (index + 1) % FEATURES.length;
    ticker.classList.add("out");
    setTimeout(() => { ticker.textContent = FEATURES[index]; ticker.classList.remove("out"); }, 350);
  }, 4200);
}

function cardSpotlight() {
  const card = document.querySelector("#loginView .login-card");
  card.addEventListener("pointermove", event => {
    const box = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${event.clientX - box.left}px`);
    card.style.setProperty("--my", `${event.clientY - box.top}px`);
  }, { passive: true });
}

export function init() {
  if (!$("loginView")) return;
  serverStatus();
  busyButton();
  passwordTools();
  errorShake();
  featureTicker();
  cardSpotlight();
}
