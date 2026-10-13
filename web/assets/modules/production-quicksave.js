// Quick save: after a LiDAR point is picked (or a saved point is opened for editing), a small card appears next to
// that point in the viewer so it can be saved right there. The card drives the existing annotation form (same
// selects, same submit, same conflict handling); it only mirrors and forwards. It follows the point while the view
// moves and stays clamped inside the viewer when the point leaves the screen.
import * as THREE from "../../potree/libs/three.js/build/three.module.js";
import { $, esc, state, toast } from "./core.js?v=20261013-no-line-nav";
import { PLACEMENT_LABELS } from "./production-placement.js?v=20261013-no-line-nav";
import { openProductionMapPicker } from "./production-map.js?v=20261013-no-line-nav";
import { productionAnnotationGroups, productionGroupLabels } from "./production-annotations.js?v=20261013-no-line-nav";

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
    <div id="qsFields" class="qs-fields" aria-label="Attributes"></div>
    <div id="qsPlacement" class="qs-placement"></div>
    <div class="qs-coords" role="group" aria-label="Coordinates (click a value to copy it)">
      <button type="button" class="qs-coord wide" data-qs-copy="X" title="Copy X" aria-label="Copy X"><span>X</span><b id="qsX">—</b><i class="qs-copy-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="13" height="13"><path fill="currentColor" d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1Zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2Zm0 16H8V7h11v14Z"/></svg></i></button>
      <button type="button" class="qs-coord wide" data-qs-copy="Y" title="Copy Y" aria-label="Copy Y"><span>Y</span><b id="qsY">—</b><i class="qs-copy-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="13" height="13"><path fill="currentColor" d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1Zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2Zm0 16H8V7h11v14Z"/></svg></i></button>
      <button type="button" class="qs-coord wide" data-qs-copy="Z" title="Copy Z (elevation)" aria-label="Copy Z (elevation)"><span>Z</span><b id="qsZ">—</b><i class="qs-copy-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="13" height="13"><path fill="currentColor" d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1Zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2Zm0 16H8V7h11v14Z"/></svg></i></button>
      <button type="button" class="qs-coord wide" data-qs-copy="Lat" title="Copy latitude" aria-label="Copy latitude"><span>Lat</span><b id="qsLat">—</b><i class="qs-copy-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="13" height="13"><path fill="currentColor" d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1Zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2Zm0 16H8V7h11v14Z"/></svg></i></button>
      <button type="button" class="qs-coord wide" data-qs-copy="Lon" title="Copy longitude" aria-label="Copy longitude"><span>Lon</span><b id="qsLon">—</b><i class="qs-copy-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="13" height="13"><path fill="currentColor" d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1Zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2Zm0 16H8V7h11v14Z"/></svg></i></button>
    </div>
    <div class="qs-coord-actions"><button type="button" class="qs-ghost qs-map" data-qs="map" title="Adjust X/Y on OpenStreetMap while preserving this LiDAR elevation">Map location</button><button type="button" class="qs-ghost qs-sv" data-qs="streetview" title="Open this location in Google Street View">Street View</button></div>
    <p id="qsError" class="qs-error" role="alert"></p>
    <footer><button type="button" class="qs-link hidden" data-qs="history">History</button><button type="button" class="qs-danger hidden" data-qs="delete">Delete</button><span class="qs-spacer"></span><button type="button" class="qs-ghost" data-qs="clear">Clear</button><button type="button" class="qs-save" data-qs="save">Save point</button></footer>`;
  area.append(ring, card);
  // Attribute fields: a dropdown (with "Other (type a value)") or a typed value, kept on the draft.
  card.addEventListener("change", event => {
    const select = event.target.closest("[data-attr-select]");
    if (!select) return;
    const key = select.dataset.attrSelect, other = card.querySelector(`[data-attr-other="${CSS.escape(key)}"]`);
    const isOther = select.value === OTHER;
    other.classList.toggle("hidden", !isOther);
    setAttr(key, isOther ? other.value : select.value);
    if (isOther) other.focus();
  });
  card.addEventListener("input", event => {
    const input = event.target.closest("[data-attr-other], [data-attr-text]");
    if (input) setAttr(input.dataset.attrOther || input.dataset.attrText, input.value);
  });
  card.addEventListener("change", event => {
    const pair = MIRRORED.find(([mine]) => mine === event.target.id);
    if (!pair) return;
    const real = $(pair[1]);
    real.value = event.target.value;
    real.dispatchEvent(new Event("change", { bubbles: true }));
    sync(true);
  });
  card.addEventListener("click", event => {
    const copy = event.target.closest("[data-qs-copy]");
    if (copy) { const k = copy.dataset.qsCopy; copyValue(copy, k === "Lat" ? "Latitude" : k === "Lon" ? "Longitude" : k, $(`qs${k}`).textContent); return; }
    const action = event.target.closest("[data-qs]")?.dataset.qs;
    if (action === "save") $("annotationForm").requestSubmit();
    else if (action === "clear") $("annotationCancelBtn").click();
    else if (action === "delete") $("annotationDeleteBtn").click();
    else if (action === "map") openProductionMapPicker();
    else if (action === "streetview") $("annotationStreetView").click();

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

async function copyValue(button, label, text) {
  if (!text || text === "—" || /Calculating|Unavailable/.test(text)) { toast(`${label} is not available yet`, "info", 1800); return; }
  try { await navigator.clipboard.writeText(text); }
  catch {
    const area = Object.assign(document.createElement("textarea"), { value: text });
    document.body.append(area); area.select(); document.execCommand("copy"); area.remove();
  }
  button.classList.add("copied");
  setTimeout(() => button.classList.remove("copied"), 1100);
  toast(`${label} copied`, "success", 1400);
}

const OTHER = "__other__";
let fieldsKey = "";

function setAttr(key, value) {
  state.productionDraftAttributes = state.productionDraftAttributes || {};
  if (value == null || String(value).trim() === "") delete state.productionDraftAttributes[key];
  else state.productionDraftAttributes[key] = value;
}

// Anchor points already saved for the selected pole (anc_1, anc_2, ...), for fields such as guy_anchor_no.
function poleAnchors() {
  const poleId = $("annotationPoleId").value;
  return (state.productionAnnotations || [])
    .filter(row => row.family === "anchors" && String(row.pole_internal_id ?? row.attributes?.pole_internal_id) === poleId)
    .map(row => row.feature_type)
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

// The fields of the chosen group / point type, from the attribute workbook (served in the catalogue).
function renderFields() {
  const family = $("annotationFamily").value, feature = $("annotationFeature").value;
  const anchors = poleAnchors();
  const key = `${family}|${feature}|${$("annotationId").value}|${state.productionDraft ? `${state.productionDraft.x}|${state.productionDraft.y}` : ""}|${$("annotationPoleId").value}|${anchors.join(",")}`;
  if (key === fieldsKey) return;
  fieldsKey = key;
  const group = productionAnnotationGroups().find(g => g.id === family);
  const fields = (group?.fields || []).filter(f => !f.features || f.features.includes(feature));
  const values = state.productionDraftAttributes || {};
  $("qsFields").innerHTML = fields.map(f => {
    const value = values[f.key] ?? "";
    if (f.manual) return `<label class="qs-field">${esc(f.label)}<input data-attr-text="${esc(f.key)}" maxlength="200" value="${esc(value)}" placeholder="Type ${esc(f.label.toLowerCase())}" autocomplete="off"></label>`;
    const options = f.source === "anchors" ? anchors : f.options;
    const known = value === "" || options.includes(value);
    const empty = f.source === "anchors" && !anchors.length ? '<option value="" disabled>No anchors saved for this pole yet</option>' : "";
    return `<label class="qs-field">${esc(f.label)}<select data-attr-select="${esc(f.key)}"><option value="">—</option>${empty}${options.map(o => `<option value="${esc(o)}"${o === value ? " selected" : ""}>${esc(o)}</option>`).join("")}<option value="${OTHER}"${known ? "" : " selected"}>Other (type a value)</option></select><input class="qs-other${known ? " hidden" : ""}" data-attr-other="${esc(f.key)}" maxlength="200" value="${known ? "" : esc(value)}" placeholder="Type ${esc(f.label.toLowerCase())}" autocomplete="off"></label>`;
  }).join("");
  $("qsFields").classList.toggle("hidden", !fields.length);
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
  renderFields();
  for (const [mine, real] of MIRRORED) mirrorSelect($(mine), $(real));
  const editing = Boolean($("annotationId").value), family = $("annotationFamily").value;
  $("qsParentField").classList.toggle("hidden", $("annotationParentField").classList.contains("hidden"));
  $("qsTitle").textContent = editing ? "Edit point" : "Save this point";
  const pole = state.productionPoles?.find(p => String(p.internal_id) === $("annotationPoleId").value);
  $("qsSub").textContent = `${pole ? pole.pole_number || `Pole ID ${pole.internal_id}` : "No pole selected"} · ${productionGroupLabels[family] || $("annotationFamily").selectedOptions[0]?.text || family || "—"}`;
  for (const k of ["X", "Y", "Z"]) $(`qs${k}`).textContent = $(`annotation${k}`).textContent;
  const placement = state.productionDraftPlacement || "lidar";
  $("qsPlacement").textContent = PLACEMENT_LABELS[placement] || placement;
  $("qsPlacement").classList.toggle("free", placement !== "lidar");
  card.querySelector(".qs-dot").classList.toggle("free", placement !== "lidar");
  $("qsLat").textContent = $("annotationLat").textContent;
  $("qsLon").textContent = $("annotationLon").textContent;
  const sv = card.querySelector('[data-qs="streetview"]');
  sv.disabled = $("annotationStreetView").disabled;
  card.querySelector('[data-qs="map"]').disabled = !state.productionDraft || !state.projectId;
  $("qsError").textContent = $("annotationError").textContent;
  const save = card.querySelector('[data-qs="save"]');
  save.disabled = $("annotationSaveBtn").disabled;
  save.title = $("annotationSaveBtn").title;
  card.querySelector('[data-qs="delete"]').classList.toggle("hidden", $("annotationDeleteBtn").classList.contains("hidden"));
  card.querySelector('[data-qs="history"]').classList.toggle("hidden", $("annotationHistoryBtn").classList.contains("hidden"));
}

function hide() {
  if (!card || card.classList.contains("hidden")) return;
  fieldsKey = "";
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
