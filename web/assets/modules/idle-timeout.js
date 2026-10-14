// Automatic sign-out after 5 minutes without activity. A warning with a countdown appears for the last minute
// ("Stay signed in" keeps the session). Activity is shared between tabs, so working in one tab keeps the others
// signed in, and a request still in progress (for example a large LiDAR upload) counts as activity.
import { $, logout, state } from "./core.js?v=20261014-rdbl-zoom";

export const IDLE_MINUTES = 5;
const IDLE_MS = IDLE_MINUTES * 60 * 1000;
const WARN_MS = 60 * 1000;
const SHARED_KEY = "pla_last_activity";
let lastActivity = Date.now(), lastShared = 0, inFlight = 0, warning = null;

const signedIn = () => Boolean(state.token) && !$("appView").classList.contains("hidden");

function touch() {
  lastActivity = Date.now();
  if (lastActivity - lastShared > 5000) {
    lastShared = lastActivity;
    try { localStorage.setItem(SHARED_KEY, String(lastActivity)); } catch {}
  }
  if (warning && !warning.classList.contains("hidden")) hideWarning();
}

function latestActivity() {
  let shared = 0;
  try { shared = Number(localStorage.getItem(SHARED_KEY)) || 0; } catch {}
  return Math.max(lastActivity, shared);
}

function buildWarning() {
  warning = document.createElement("div");
  warning.id = "idleWarning";
  warning.className = "idle-warning hidden";
  warning.setAttribute("role", "alertdialog");
  warning.setAttribute("aria-live", "assertive");
  warning.setAttribute("aria-labelledby", "idleWarningTitle");
  warning.innerHTML = `<div class="idle-ring"><svg viewBox="0 0 44 44" aria-hidden="true"><circle cx="22" cy="22" r="19" class="idle-track"/><circle cx="22" cy="22" r="19" id="idleArc" class="idle-arc"/></svg><b id="idleCount">60</b></div>
    <div class="idle-text"><b id="idleWarningTitle">Still there?</b><small>For security you'll be signed out after ${IDLE_MINUTES} minutes without activity.</small></div>
    <button type="button" id="idleStay" class="primary">Stay signed in</button>`;
  document.body.appendChild(warning);
  $("idleStay").onclick = () => touch();
}

function hideWarning() { warning.classList.add("hidden"); }

function showWarning(remainingMs) {
  const seconds = Math.max(0, Math.ceil(remainingMs / 1000));
  if (warning.classList.contains("hidden")) { warning.classList.remove("hidden"); $("idleStay").focus({ preventScroll: true }); }
  $("idleCount").textContent = String(seconds);
  $("idleArc").style.strokeDashoffset = String(119.4 * (1 - remainingMs / WARN_MS));
}

function tick() {
  if (!signedIn()) { if (warning && !warning.classList.contains("hidden")) hideWarning(); lastActivity = Date.now(); return; }
  if (inFlight > 0) { touch(); return; }
  const idle = Date.now() - latestActivity();
  if (idle >= IDLE_MS) {
    hideWarning();
    try { localStorage.removeItem(SHARED_KEY); } catch {}
    logout(`You were signed out after ${IDLE_MINUTES} minutes without activity. Sign in again to continue.`);
    lastActivity = Date.now();
    return;
  }
  if (idle >= IDLE_MS - WARN_MS) showWarning(IDLE_MS - idle);
  else if (!warning.classList.contains("hidden")) hideWarning();
}

export function init() {
  buildWarning();
  let lastMove = 0;
  for (const type of ["mousedown", "keydown", "wheel", "touchstart", "scroll", "pointerdown"]) document.addEventListener(type, touch, { capture: true, passive: true });
  document.addEventListener("mousemove", () => { const now = Date.now(); if (now - lastMove > 1000) { lastMove = now; touch(); } }, { capture: true, passive: true });
  // Requests in progress count as activity (large uploads can take longer than the idle limit).
  const fetch = window.fetch.bind(window);
  window.fetch = (...args) => { inFlight++; return fetch(...args).finally(() => { inFlight = Math.max(0, inFlight - 1); touch(); }); };
  setInterval(tick, 1000);
}
