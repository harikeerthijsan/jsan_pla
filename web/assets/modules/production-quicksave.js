// Quick save: after a LiDAR point is picked (or a saved point is opened for editing), a small card appears next to
// that point in the viewer so it can be saved right there. The card drives the existing annotation form (same
// selects, same submit, same conflict handling); it only mirrors and forwards. It follows the point while the view
// moves and stays clamped inside the viewer when the point leaves the screen.
import * as THREE from "../../potree/libs/three.js/build/three.module.js";
import { $, esc, state } from "./core.js?v=20261012-box-close-focus-1";
import { PLACEMENT_LABELS } from "./production-placement.js?v=20261012-box-close-focus-1";
import { productionGroupLabels } from "./production-annotations.js?v=20261012-box-close-focus-1";

const MIRRORED = [["qsFamily", "annotationFamily"], ["qsFeature", "annotationFeature"], ["qsParent", "annotationParent"]];
let card = null, ring = null, shownKey = "", frame = 0;
const projected = new THREE.Vector3();

function build() {
  const area = $("production_render_area");
  ring = document.createElement("div");
  ring.className = "qs-ring hidden";
  ring.setAttribute("aria-hidden", "true");
  card = document.createElement("div");
  card.id = "productionQuickSave";
  card.className = "qs-card hidden";
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-label", "Save this point");
  card.innerHTML = `<header><span class="qs-dot"></span><div><b id="qsTitle">New point</b><small id="qsSub"></small></div><button type="button" class="qs-close" data-qs="clear" aria-label="Discard this point" title="Discard (Esc)">×</button></header>
    <label>Group<select id="qsFamily"></select></label>
    <label>Point / variable<select id="qsFeature"></select></label>
    <label id="qsParentField" class="hidden">Parent<select id="qsParent"></select></label>
    <div id="qsPlacement" class="qs-placement"></div>
    <div class="qs-readout"><span>Z <b id="qsZ">—</b></span><span id="qsGeo"></span></div>
    <p id="qsError" class="qs-error" role="alert"></p>
    <footer><button type="button" class="qs-link hidden" data-qs="history">History</button><button type="button" class="qs-danger hidden" data-qs="delete">Delete</button><span class="qs-spacer"></span><button type="button" class="qs-ghost" data-qs="clear">Clear</button><button type="button" class="qs-save" data-qs="save">Save point</button></footer>`;
  area.append(ring, card);
  card.addEventListener("change", event => {
    const pair = MIRRORED.find(([mine]) => mine === event.target.id);
    if (!pair) return;
    const real = $(pair[1]);
    real.value = event.target.value;
    real.dispatchEvent(new Event("change", { bubbles: true }));
    sync(true);
  });
  card.addEventListener("click", event => {
    const action = event.target.closest("[data-qs]")?.dataset.qs;
    if (action === "save") $("annotationForm").requestSubmit();
    else if (action === "clear") $("annotationCancelBtn").click();
    else if (action === "delete") $("annotationDeleteBtn").click();
    else if (action === "history") {
      $("annotationHistoryBtn").click();
      document.querySelector(".production-layout.is-fullscreen:not(.drawer-open)") && $("productionPanelToggleBtn").click();
      $("annotationHistory").scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  });
  // Keep pointer gestures on the card from rotating the view underneath it.
  for (const type of ["mousedown", "mouseup", "wheel", "dblclick"]) card.addEventListener(type, event => event.stopPropagation());
  card.addEventListener("keydown", event => {
    if (event.key === "Enter" && event.target.tagName !== "BUTTON" && event.target.tagName !== "SELECT") { event.preventDefault(); $("annotationForm").requestSubmit(); }
    if (event.key === "Escape") { event.stopPropagation(); $("annotationCancelBtn").click(); }
  });
}

function mirrorSelect(mine, real) {
  const signature = [...real.options].map(o => `${o.value}\u0001${o.text}\u0001${o.disabled}`).join("\u0002");
  if (mine.dataset.signature !== signature) {
    mine.innerHTML = [...real.options].map(o => `<option value="${esc(o.value)}"${o.disabled ? " disabled" : ""}>${esc(o.text)}</option>`).join("");
    mine.dataset.signature = signature;
  }
  if (mine.value !== real.value) mine.value = real.value;
  mine.disabled = real.disabled;
}

function sync(force = false) {
  if (!force && frame % 8) return;
  for (const [mine, real] of MIRRORED) mirrorSelect($(mine), $(real));
  const editing = Boolean($("annotationId").value), family = $("annotationFamily").value;
  $("qsParentField").classList.toggle("hidden", $("annotationParentField").classList.contains("hidden"));
  $("qsTitle").textContent = editing ? "Edit point" : "Save this point";
  const pole = state.productionPoles?.find(p => String(p.internal_id) === $("annotationPoleId").value);
  $("qsSub").textContent = `${pole ? pole.pole_number || `Pole ID ${pole.internal_id}` : "No pole selected"} · ${productionGroupLabels[family] || $("annotationFamily").selectedOptions[0]?.text || family || "—"}`;
  $("qsZ").textContent = state.productionDraft ? Number(state.productionDraft.z).toFixed(3) : "—";
  const placement = state.productionDraftPlacement || "lidar";
  $("qsPlacement").textContent = PLACEMENT_LABELS[placement] || placement;
  $("qsPlacement").classList.toggle("free", placement !== "lidar");
  card.querySelector(".qs-dot").classList.toggle("free", placement !== "lidar");
  const lat = $("annotationLat").textContent, lon = $("annotationLon").textContent;
  $("qsGeo").textContent = /^-?\d/.test(lat) ? `${Number(lat).toFixed(6)}, ${Number(lon).toFixed(6)}` : lat === "Calculating…" ? "Locating…" : "";
  $("qsError").textContent = $("annotationError").textContent;
  const save = card.querySelector('[data-qs="save"]');
  save.disabled = $("annotationSaveBtn").disabled;
  save.title = $("annotationSaveBtn").title;
  card.querySelector('[data-qs="delete"]').classList.toggle("hidden", $("annotationDeleteBtn").classList.contains("hidden"));
  card.querySelector('[data-qs="history"]').classList.toggle("hidden", $("annotationHistoryBtn").classList.contains("hidden"));
}

function hide() {
  if (!card || card.classList.contains("hidden")) return;
  card.classList.add("hidden");
  ring.classList.add("hidden");
  shownKey = "";
}

function place() {
  const viewer = state.productionViewer, draft = state.productionDraft, area = $("production_render_area");
  const active = draft && viewer && state.workspace === "PRODUCTION" && !state.productionPickTool && !$("productionWorkspace").classList.contains("hidden");
  if (!active) { hide(); return; }
  const key = `${$("annotationId").value}|${draft.x}|${draft.y}|${draft.z}`;
  const fresh = key !== shownKey;
  if (fresh) {
    shownKey = key;
    card.classList.remove("hidden");
    ring.classList.remove("hidden");
    card.classList.remove("qs-enter"); void card.offsetWidth; card.classList.add("qs-enter");
    sync(true);
    setTimeout(() => { if (card && !card.classList.contains("hidden") && !card.contains(document.activeElement)) card.querySelector(".qs-save")?.focus({ preventScroll: true }); }, 60);
  } else sync();
  const w = area.clientWidth, h = area.clientHeight;
  projected.set(draft.x, draft.y, draft.z).project(viewer.scene.getActiveCamera());
  const visible = projected.z < 1 && Math.abs(projected.x) <= 1 && Math.abs(projected.y) <= 1;
  const px = (projected.x + 1) / 2 * w, py = (1 - projected.y) / 2 * h;
  ring.classList.toggle("hidden", !visible);
  if (visible) ring.style.transform = `translate(${px - 14}px, ${py - 14}px)`;
  const cw = card.offsetWidth || 280, ch = card.offsetHeight || 220, gap = 26;
  let left = visible ? px + gap : w - cw - 16, top = visible ? py - ch / 2 : 16;
  let side = "right";
  if (visible && left + cw > w - 8) { left = px - gap - cw; side = "left"; }
  left = Math.max(8, Math.min(left, w - cw - 8));
  top = Math.max(8, Math.min(top, h - ch - 8));
  card.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
  card.dataset.side = visible ? side : "none";
  // Arrow points at the picked point while it is on screen.
  card.style.setProperty("--qs-arrow", `${Math.max(16, Math.min(ch - 16, py - top))}px`);
}

function loop() {
  frame++;
  if (!document.hidden) place();
  requestAnimationFrame(loop);
}

export function init() {
  if (!$("production_render_area")) return;
  build();
  requestAnimationFrame(loop);
}
