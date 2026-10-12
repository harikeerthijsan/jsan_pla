// Distance measurement in the Production 3D view: click two LiDAR points; the line and its length appear in the
// view and the values (3D, horizontal, vertical) are listed in the side panel. Measurements are for this session
// and dataset only; they are not saved.
import * as THREE from "../../potree/libs/three.js/build/three.module.js";
import { $, esc, state, toast } from "./core.js?v=20261012-box-close-focus-1";
import { annotationUnits } from "./production-annotations.js?v=20261012-box-close-focus-1";
import { pickOrPlace } from "./production-placement.js?v=20261012-box-close-focus-1";
import { cancelProductionPick } from "./production-pick.js?v=20261012-box-close-focus-1";
import { cancelProductionProfileLine } from "./production-profile.js?v=20261012-box-close-focus-1";
import { cancelProductionBox } from "./production-view.js?v=20261012-box-close-focus-1";

const COLOR = 0x3fe0ff, DRAFT_COLOR = 0xffd24a;
const tapes = [];
let tool = null, counter = 0, selectedId = null, draftTag = null;
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

const unitLabel = () => { const u = annotationUnits().toLowerCase(); return u.includes("foot") || u.includes("feet") ? "ft" : "m"; };
const fmt = value => `${value.toFixed(2)} ${unitLabel()}`;

function makeMeasure(points, { name, color, label }) {
  const viewer = state.productionViewer;
  viewer.setLengthUnit(unitLabel());
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
      draftTag = tag("0.00", "draft");
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
      draftTag.textContent = fmt(values(picked[0], point).distance);
      placeTag(draftTag, picked[0], point);
      hint(`<b>${fmt(values(picked[0], point).distance)}</b> · click the second point · Esc to cancel`);
    });
  };
  const finish = (a, b) => {
    const v = values(a, b);
    counter += 1;
    const id = `m${Date.now()}${counter}`;
    const tape = { id, name: `M${counter}`, a, b, ...v, projectId: state.projectId, measure: null };
    tape.measure = makeMeasure([a, b], { name: tape.name, color: COLOR, label: true });
    tape.tag = tag(`${tape.name} · ${fmt(v.distance)}`);
    tapes.push(tape);
    selectedId = id;
    cancelProductionMeasure();
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
      draftTag?.remove(); draftTag = null;
    },
  };
  hint(`<b>Measure distance</b> · click the first point on the point cloud · Esc to cancel`);
  renderMeasurePanel();
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
      <span class="measure-values"><b>${fmt(t.distance)}</b><small>H ${fmt(t.horizontal)} · V ${fmt(t.vertical)} · ${t.slope.toFixed(1)}°</small></span>
      <button type="button" class="check-remove" data-measure-remove="${esc(t.id)}" title="Remove ${esc(t.name)}" aria-label="Remove ${esc(t.name)}">×</button>
    </div>`).join("");
  root.innerHTML = `<div class="checklist-title measure-title"><span>Measurements</span>${mine.length ? '<button type="button" class="measure-clear" data-measure-clear>Clear all</button>' : ""}</div>
    <div class="check-row measure-start${tool ? " measuring" : ""}"><span class="check-mark measure-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" d="M2 17.6 17.6 2 22 6.4 6.4 22 2 17.6Zm3.2-.1 1.4 1.4 1.2-1.2-1.4-1.4 1.1-1.1 2.1 2.1 1.1-1.1-2.1-2.1 1.1-1.1 1.4 1.4 1.1-1.1-1.4-1.4 1.1-1.1 2.1 2.1 1.1-1.1-2.1-2.1 1.1-1.1 1.4 1.4 1.2-1.2-1.4-1.4-1.6 1.6L5.2 17.5Z"/></svg></span>
      <span class="check-label">Distance<small>${tool ? "Click two points in the 3D view" : `Two points · result in ${unitLabel()}`}</small></span>
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
    else if (target.matches("[data-measure-clear]")) { for (const t of tapes.filter(x => x.projectId === state.projectId)) removeTape(t.id); renderMeasurePanel(); }
    else if (target.matches("[data-measure-remove]")) { removeTape(target.dataset.measureRemove); renderMeasurePanel(); }
    else if (target.matches(".measure-row")) { const tape = tapes.find(t => t.id === target.dataset.measure); if (tape) focusTape(tape); }
  });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && tool) { event.stopPropagation(); cancelProductionMeasure(); } }, true);
  requestAnimationFrame(tagLoop);
  renderMeasurePanel();
}
