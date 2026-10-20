// Distance measurement in the Production 3D view: click two LiDAR points; the line and its length appear in the
// view and the values (3D, horizontal, vertical) are listed in the side panel. Measurements are saved with the dataset
// (and who measured), so they are part of a session's work: admins export and clear them with "Session work".
import * as THREE from "../../potree/libs/three.js/build/three.module.js";
import { $, api, esc, state, toast } from "./core.js?v=20261020-drag-card";
import { annotationUnits } from "./production-annotations.js?v=20261020-drag-card";
import { pickOrPlace } from "./production-placement.js?v=20261020-drag-card";
import { cancelProductionPick } from "./production-pick.js?v=20261020-drag-card";
import { cancelProductionProfileLine } from "./production-profile.js?v=20261020-drag-card";
import { cancelProductionBox } from "./production-view.js?v=20261020-drag-card";

const COLOR = 0x3fe0ff, DRAFT_COLOR = 0xffd24a;
const tapes = [];
const UNIT_FACTORS = Object.freeze({ ft: 0.3048, m: 1, cm: 0.01, mm: 0.001 });
const UNIT_PRECISION = Object.freeze({ ft: 2, m: 3, cm: 1, mm: 0 });
let tool = null, counter = 0, selectedId = null, draftTag = null, draftDistance = null, displayUnit = null;
const mid = new THREE.Vector3();

function tag(text, cls = "") {
  const el = document.createElement("div");
  el.className = `measure-label ${cls}`;
  el.setAttribute("aria-hidden", "true");
  el.textContent = text;
  $("production_render_area").appendChild(el);
  return el;
}

function placeTag(el, a, b) {
  const viewer = state.productionViewer, area = $("production_render_area");
  if (!el || !viewer) return;
  mid.copy(a).add(b).multiplyScalar(0.5).project(viewer.scene.getActiveCamera());
  const visible = mid.z < 1 && Math.abs(mid.x) <= 1.02 && Math.abs(mid.y) <= 1.02 && state.workspace === "PRODUCTION";
  el.classList.toggle("hidden", !visible);
  if (visible) el.style.transform = `translate(${Math.round((mid.x + 1) / 2 * area.clientWidth)}px, ${Math.round((1 - mid.y) / 2 * area.clientHeight)}px) translate(-50%, -50%)`;
}

function tagLoop() {
  if (!document.hidden) for (const t of tapes) { placeTag(t.tag, t.a, t.b); t.tag.classList.toggle("active", t.id === selectedId); }
  requestAnimationFrame(tagLoop);
}

const sourceUnitLabel = () => { const u = annotationUnits().toLowerCase(); return u.includes("foot") || u.includes("feet") ? "ft" : "m"; };
const measurementUnit = () => displayUnit && UNIT_FACTORS[displayUnit] ? displayUnit : sourceUnitLabel();
export function convertMeasurementValue(value, fromUnit = sourceUnitLabel(), toUnit = measurementUnit()) {
  return Number(value) * UNIT_FACTORS[fromUnit] / UNIT_FACTORS[toUnit];
}
const fmt = value => { const unit = measurementUnit(); return `${convertMeasurementValue(value).toFixed(UNIT_PRECISION[unit])} ${unit}`; };

function refreshMeasurementLabels() {
  for (const tape of tapes) if (tape.tag) tape.tag.textContent = `${tape.name} · ${fmt(tape.distance)}`;
  if (draftTag && draftDistance != null) draftTag.textContent = fmt(draftDistance);
}

function makeMeasure(points, { name, color, label }) {
  const viewer = state.productionViewer;
  viewer.setLengthUnit(sourceUnitLabel());
  const measure = new Potree.Measure();
  measure.name = name;
  measure.color = new THREE.Color(color);
  measure.closed = false;
  measure.showDistances = false;
  measure.showHeight = false;
  measure.showCoordinates = false;
  measure.showEdges = true;
  measure.maxMarkers = 2;
  measure.lengthUnit = viewer.lengthUnit;
  measure.lengthUnitDisplay = viewer.lengthUnitDisplay;
  for (const point of points) measure.addMarker(point.clone());
  for (const edge of measure.edges) edge.material.color.set(color);
  // Markers are display only; dragging them would silently change a recorded measurement.
  for (const sphere of measure.spheres) sphere._listeners = {};
  viewer.scene.addMeasurement(measure);
  return measure;
}

function values(a, b) {
  const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z, horizontal = Math.hypot(dx, dy);
  return { distance: Math.hypot(dx, dy, dz), horizontal, vertical: Math.abs(dz), slope: horizontal > 1e-9 ? Math.atan2(Math.abs(dz), horizontal) * 180 / Math.PI : 90 };
}

function hint(text) {
  let el = $("productionMeasureHint");
  if (!text) { el?.remove(); return; }
  if (!el) {
    el = document.createElement("div");
    el.id = "productionMeasureHint";
    el.className = "measure-hint";
    el.setAttribute("role", "status");
    $("production_render_area").appendChild(el);
  }
  el.innerHTML = text;
}

export function cancelProductionMeasure() {
  if (!tool) return;
  const t = tool;
  tool = null;
  t.stop();
  hint("");
  renderMeasurePanel();
}

export function startProductionMeasure() {
  const viewer = state.productionViewer;
  if (!viewer || !state.productionPointclouds.length) { toast("Load the LiDAR first", "error"); return; }
  cancelProductionPick(); cancelProductionBox(); cancelProductionProfileLine(); cancelProductionMeasure();
  const dom = viewer.renderer.domElement, picked = [];
  let draft = null, down = null, pending = false, last = null;
  const hitAt = event => {
    const r = dom.getBoundingClientRect();
    return pickOrPlace(event.clientX - r.left, event.clientY - r.top).location || null;
  };
  const onDown = e => { down = e.button === 0 ? { x: e.clientX, y: e.clientY } : null; };
  const onUp = e => {
    const start = down; down = null;
    if (!start || e.button !== 0 || Math.hypot(e.clientX - start.x, e.clientY - start.y) > 4) return;
    if (state.productionBoxTool || state.productionProfileLine) { cancelProductionMeasure(); return; }
    const point = hitAt(e);
    if (!point) { toast("Could not place a point there. Rotate the view or click on the LiDAR.", "error", 3000); return; }
    picked.push(point.clone());
    if (picked.length === 1) {
      draft = makeMeasure([picked[0], picked[0]], { name: "Measuring", color: DRAFT_COLOR, label: true });
      draftDistance = 0;
      draftTag = tag(fmt(draftDistance), "draft");
      placeTag(draftTag, picked[0], picked[0]);
      hint(`<b>Point 1 placed</b> · click the second point · Esc to cancel`);
      return;
    }
    finish(picked[0], picked[1]);
  };
  // Live preview: the second end follows the cursor (throttled, since point picking walks the octree).
  const onMove = e => {
    if (!draft || pending) return;
    last = e; pending = true;
    requestAnimationFrame(() => {
      pending = false;
      const point = last && hitAt(last);
      if (!point || !draft) return;
      draft.setPosition(1, point);
      draftDistance = values(picked[0], point).distance;
      draftTag.textContent = fmt(draftDistance);
      placeTag(draftTag, picked[0], point);
      hint(`<b>${fmt(values(picked[0], point).distance)}</b> · click the second point · Esc to cancel`);
    });
  };
  const finish = async (a, b) => {
    const v = values(a, b), projectId = state.projectId;
    cancelProductionMeasure();
    let saved;
    try {
      saved = await api(`/api/projects/${encodeURIComponent(projectId)}/measurements`, { method: "POST",
        body: JSON.stringify({ a: { x: a.x, y: a.y, z: a.z }, b: { x: b.x, y: b.y, z: b.z }, pole_internal_id: Number($("annotationPoleId")?.value) || null }) });
    } catch (e) { toast(`Measurement not saved: ${e.message}`, "error", 6000); return; }
    if (projectId !== state.projectId) return;
    const tape = addTape(saved, projectId);
    selectedId = tape.id;
    renderMeasurePanel();
    toast(`${tape.name}: ${fmt(v.distance)} (horizontal ${fmt(v.horizontal)}, vertical ${fmt(v.vertical)})`, "success", 5000);
  };
  dom.addEventListener("mousedown", onDown);
  dom.addEventListener("mouseup", onUp);
  dom.addEventListener("mousemove", onMove);
  dom.classList.add("production-picking");
  state.productionPicking = true;
  tool = {
    stop: () => {
      dom.removeEventListener("mousedown", onDown);
      dom.removeEventListener("mouseup", onUp);
      dom.removeEventListener("mousemove", onMove);
      dom.classList.remove("production-picking");
      state.productionPicking = false;
      if (draft) { viewer.scene.removeMeasurement(draft); draft = null; }
      draftTag?.remove(); draftTag = null; draftDistance = null;
    },
  };
  hint(`<b>Measure distance</b> · click the first point on the point cloud · Esc to cancel`);
  renderMeasurePanel();
}

// A saved measurement as an on-screen tape (line + label).
function addTape(saved, projectId) {
  counter += 1;
  const a = new THREE.Vector3(saved.a.x, saved.a.y, saved.a.z), b = new THREE.Vector3(saved.b.x, saved.b.y, saved.b.z);
  const tape = { id: saved.id, name: `M${counter}`, a, b, ...values(a, b), projectId, by: saved.created_by_name || saved.created_by || "", measure: null };
  tape.measure = makeMeasure([a, b], { name: tape.name, color: COLOR, label: true });
  tape.tag = tag(`${tape.name} · ${fmt(tape.distance)}`);
  tapes.push(tape);
  return tape;
}

// Load the dataset's saved measurements once the viewer has it (also after "Session work" cleared them).
let loadedFor = null;
export async function loadProductionMeasurements(force = false) {
  const projectId = state.projectId;
  if (!projectId || !state.productionViewer || (!force && loadedFor === projectId)) return;
  loadedFor = projectId;
  for (const tape of tapes.filter(t => t.projectId === projectId)) removeTape(tape.id);
  try {
    const rows = await api(`/api/projects/${encodeURIComponent(projectId)}/measurements`);
    if (projectId !== state.projectId) return;
    counter = 0;
    for (const row of rows) addTape(row, projectId);
  } catch { loadedFor = null; }
  renderMeasurePanel();
}

async function deleteTape(id) {
  const tape = tapes.find(t => t.id === id);
  if (!tape) return;
  try { await api(`/api/projects/${encodeURIComponent(tape.projectId)}/measurements/${encodeURIComponent(id)}`, { method: "DELETE" }); }
  catch (e) { toast(`${tape.name} not removed: ${e.message}`, "error"); return; }
  removeTape(id);
}

function removeTape(id) {
  const index = tapes.findIndex(t => t.id === id);
  if (index < 0) return;
  const [tape] = tapes.splice(index, 1);
  state.productionViewer?.scene.removeMeasurement(tape.measure);
  tape.tag?.remove();
  if (selectedId === id) selectedId = null;
}

function focusTape(tape) {
  selectedId = tape.id;
  const viewer = state.productionViewer;
  if (viewer) {
    const view = viewer.scene.view, centre = tape.a.clone().add(tape.b).multiplyScalar(0.5);
    const back = view.direction.clone().multiplyScalar(-Math.max(tape.distance, 4) * 2.2);
    view.setView(centre.clone().add(back), centre, 600);
  }
  renderMeasurePanel();
}

export function renderMeasurePanel() {
  const root = $("productionMeasurePanel");
  if (!root) return;
  // Measurements belong to the dataset they were taken on.
  for (const tape of [...tapes]) if (tape.projectId !== state.projectId) removeTape(tape.id);
  const ready = Boolean(state.productionViewer && state.productionPointclouds?.length);
  const mine = tapes.filter(t => t.projectId === state.projectId);
  const rows = mine.map(t => `<div class="measure-row${t.id === selectedId ? " active" : ""}" data-measure="${esc(t.id)}">
      <span class="measure-tag">${esc(t.name)}</span>
      <span class="measure-values"><b>${fmt(t.distance)}</b><small>H ${fmt(t.horizontal)} · V ${fmt(t.vertical)} · ${t.slope.toFixed(1)}°${t.by ? ` · ${esc(t.by)}` : ""}</small></span>
      <button type="button" class="check-remove" data-measure-remove="${esc(t.id)}" title="Remove ${esc(t.name)}" aria-label="Remove ${esc(t.name)}">×</button>
    </div>`).join("");
  const unit = measurementUnit();
  const unitOptions = [["ft", "Feet"], ["mm", "Millimetres"], ["cm", "Centimetres"], ["m", "Metres"]]
    .map(([value, label]) => `<option value="${value}"${value === unit ? " selected" : ""}>${value} · ${label}</option>`).join("");
  root.innerHTML = `<div class="checklist-title measure-title"><span>Measurements</span><span class="measure-title-actions"><select class="measure-unit" data-measure-unit aria-label="Measurement display unit" title="Display measurements in feet, millimetres, centimetres or metres">${unitOptions}</select>${mine.length ? '<button type="button" class="measure-clear" data-measure-clear>Clear all</button>' : ""}</span></div>
    <div class="check-row measure-start${tool ? " measuring" : ""}"><span class="check-mark measure-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" d="M2 17.6 17.6 2 22 6.4 6.4 22 2 17.6Zm3.2-.1 1.4 1.4 1.2-1.2-1.4-1.4 1.1-1.1 2.1 2.1 1.1-1.1-2.1-2.1 1.1-1.1 1.4 1.4 1.1-1.1-1.4-1.4 1.1-1.1 2.1 2.1 1.1-1.1-2.1-2.1 1.1-1.1 1.4 1.4 1.2-1.2-1.4-1.4-1.6 1.6L5.2 17.5Z"/></svg></span>
      <span class="check-label">Distance<small>${tool ? "Click two points in the 3D view" : `Two points · displayed in ${unit}`}</small></span>
      ${tool ? '<button type="button" class="compact-btn danger" data-measure-cancel>Cancel</button>' : `<button type="button" class="primary-small" data-measure-start ${ready ? "" : "disabled"} title="${ready ? "Click two LiDAR points to measure between them" : "Wait for the LiDAR to load"}">Measure</button>`}
    </div>${rows || '<div class="measure-empty">No measurements yet</div>'}`;
}

export function init() {
  const panel = $("productionMeasurePanel");
  if (!panel) return;
  panel.addEventListener("click", event => {
    const target = event.target.closest("button, .measure-row");
    if (!target) return;
    if (target.matches("[data-measure-start]")) startProductionMeasure();
    else if (target.matches("[data-measure-cancel]")) cancelProductionMeasure();
    else if (target.matches("[data-measure-clear]")) { Promise.all(tapes.filter(x => x.projectId === state.projectId).map(t => deleteTape(t.id))).then(renderMeasurePanel); }
    else if (target.matches("[data-measure-remove]")) { deleteTape(target.dataset.measureRemove).then(renderMeasurePanel); }
    else if (target.matches(".measure-row")) { const tape = tapes.find(t => t.id === target.dataset.measure); if (tape) focusTape(tape); }
  });
  panel.addEventListener("change", event => {
    const select = event.target.closest("[data-measure-unit]");
    if (!select || !UNIT_FACTORS[select.value]) return;
    displayUnit = select.value;
    refreshMeasurementLabels();
    renderMeasurePanel();
  });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && tool) { event.stopPropagation(); cancelProductionMeasure(); } }, true);
  requestAnimationFrame(tagLoop);
  document.addEventListener("production-route-data-changed", () => loadProductionMeasurements());
  renderMeasurePanel();
}
