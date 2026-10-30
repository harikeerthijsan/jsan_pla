// Session work (admins / super admins): several teams work on the same LiDAR in turns. Between sessions an admin
// downloads the session's work (points, measurements, pole assignments, pole verification — with who did what) as one
// signed archive, then clears exactly that work so the next session starts clean. An archive can be opened later as a
// read-only overlay: violet markers in the 3D view, a per-person summary and a list. Nothing current is changed by viewing.
import * as THREE from "../../potree/libs/three.js/build/three.module.js";
import { $, api, confirmAction, errorText, esc, httpErrorText, state, toast } from "./core.js?v=20261030-pla1-from-points";
import { loadProduction } from "./production-data.js?v=20261030-pla1-from-points";
import { loadProductionMeasurements } from "./production-measure.js?v=20261030-pla1-from-points";
import { can, currentProject } from "./workspace.js?v=20261030-pla1-from-points";

const ARCHIVE_COLOR = 0x8b5cf6;
let dialog = null, lastExport = null, overlay = { archive: null, markers: [] };

const when = value => { const d = value ? new Date(value) : null; return d && !Number.isNaN(d.getTime()) ? d.toLocaleString() : "—"; };
const person = (name, email) => esc(name && name !== email ? `${name} (${email})` : email || "—");

function build() {
  dialog = document.createElement("dialog");
  dialog.id = "sessionWorkDialog";
  dialog.className = "session-work-dialog";
  dialog.innerHTML = `<form method="dialog">
    <header><div><h3>Session work</h3><p id="sessionWorkDataset"></p></div><button value="close" class="map-dialog-close" aria-label="Close">×</button></header>
    <section class="sw-section"><h4>Current work on this dataset</h4><div id="sessionWorkCurrent"></div>
      <div class="sw-steps">
        <button type="button" id="sessionWorkExport" class="primary">1 · Download archive</button>
        <button type="button" id="sessionWorkClear" class="danger-solid" disabled title="Download the archive first">2 · Clear this work</button>
      </div>
      <p id="sessionWorkExportNote" class="sw-note" role="status"></p>
    </section>
    <section class="sw-section"><h4>View an archive</h4>
      <p class="sw-note">Open a downloaded archive to see that session's work, read-only, over the LiDAR. Nothing in the dataset changes.</p>
      <label class="sw-file" for="sessionWorkFile">Archive file (.json)</label>
      <div class="sw-file-row"><input id="sessionWorkFile" type="file" accept=".json,application/json" />
        <button type="button" id="sessionWorkRemove" class="sw-remove hidden" title="Remove this archive file and hide its work" aria-label="Remove the archive file">× Remove</button></div>
      <div id="sessionWorkArchive"></div>
    </section>
  </form>`;
  document.body.appendChild(dialog);
  $("sessionWorkExport").onclick = exportArchive;
  $("sessionWorkClear").onclick = clearWork;
  $("sessionWorkFile").onchange = viewArchive;
  $("sessionWorkRemove").onclick = removeArchive;
  dialog.addEventListener("click", event => {
    const go = event.target.closest("[data-sw-go]"); if (go) { flyTo(Number(go.dataset.swGo)); return; }
    if (event.target.closest("[data-sw-hide]")) { hideOverlay(); renderArchive(); }
    if (event.target.closest("[data-sw-show]")) { showOverlay(); renderArchive(); }
  });
}

// ---- Current work ---------------------------------------------------------------------------------------------------
async function renderCurrent() {
  const project = currentProject(), rows = state.productionAnnotations || [];
  $("sessionWorkDataset").textContent = `${project.name || project.id} · ${project.crs || ""}`;
  let measurements = [];
  try { measurements = await api(`/api/projects/${encodeURIComponent(project.id)}/measurements`); } catch {}
  const people = {};
  const add = (email, key) => { const p = people[email] ||= { email, points: 0, measurements: 0 }; p[key] += 1; };
  for (const row of rows) add(row.created_by || "—", "points");
  for (const m of measurements) add(m.created_by || "—", "measurements");
  const list = Object.values(people).sort((a, b) => b.points - a.points);
  $("sessionWorkCurrent").innerHTML = list.length
    ? `<table class="sw-table"><thead><tr><th>Person</th><th>Points</th><th>Measurements</th></tr></thead><tbody>${list.map(p => `<tr><td>${esc(p.email)}</td><td>${p.points}</td><td>${p.measurements}</td></tr>`).join("")}</tbody></table>
       <p class="sw-note">${rows.length} point${rows.length === 1 ? "" : "s"} · ${measurements.length} measurement${measurements.length === 1 ? "" : "s"}, plus pole assignments and pole verification.</p>`
    : '<p class="sw-note">No saved work on this dataset yet.</p>';
}

async function exportArchive() {
  const project = currentProject(), button = $("sessionWorkExport");
  button.disabled = true;
  try {
    const response = await fetch(`${state.apiBase}/api/projects/${encodeURIComponent(project.id)}/work-archive`, { method: "POST", headers: { Authorization: `Bearer ${state.token}` } });
    if (!response.ok) { let detail; try { detail = (await response.json()).detail; } catch {} throw new Error(errorText(detail) || httpErrorText(response.status)); }
    const blob = await response.blob(), name = (response.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "session-work.json";
    const url = URL.createObjectURL(blob), link = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1500);
    const summary = JSON.parse(await blob.text()).summary || {};
    lastExport = { id: response.headers.get("X-Work-Archive-Id"), projectId: project.id, name, summary };
    $("sessionWorkClear").disabled = !lastExport.id;
    $("sessionWorkClear").title = "Delete exactly the work in the archive you just downloaded";
    $("sessionWorkExportNote").textContent = `Downloaded ${name}: ${summary.points ?? 0} points, ${summary.measurements ?? 0} measurements, ${summary.assignments ?? 0} pole assignments, ${summary.verified_poles ?? 0} verified poles. Keep this file — it is the record of this session's work.`;
    toast("Session work archive downloaded.", "success");
  } catch (e) { toast(`Archive not downloaded: ${e.message}`, "error", 7000); } finally { button.disabled = false; }
}

async function clearWork() {
  const project = currentProject();
  if (!lastExport || lastExport.projectId !== project.id) { toast("Download the archive first.", "error"); return; }
  const s = lastExport.summary;
  const ok = await confirmAction(`Delete this session's work? ${s.points ?? 0} points, ${s.measurements ?? 0} measurements and ${s.assignments ?? 0} pole assignments in ${lastExport.name} will be removed from the dataset, and pole verification from those points is reset. Anything changed after the download is kept.`, { confirmLabel: "Clear this work" });
  if (!ok) return;
  const button = $("sessionWorkClear"); button.disabled = true;
  try {
    const r = await api(`/api/projects/${encodeURIComponent(project.id)}/work-archive/${encodeURIComponent(lastExport.id)}/clear`, { method: "POST" });
    const skipped = r.skipped?.length ? ` ${r.skipped.length} kept: ${r.skipped.slice(0, 5).map(x => `${x.feature_type} (${x.reason})`).join(", ")}${r.skipped.length > 5 ? " …" : ""}.` : "";
    $("sessionWorkExportNote").textContent = `Cleared: ${r.points_deleted} points, ${r.measurements_deleted} measurements, ${r.assignments_deleted} assignments.${skipped}`;
    lastExport = null;
    toast(`Session work cleared (${r.points_deleted} points). The next session starts clean.`, "success", 6000);
    await loadProduction();
    await loadProductionMeasurements(true);
    renderCurrent();
  } catch (e) { toast(`Work not cleared: ${e.message}`, "error", 7000); button.disabled = false; }
}

// ---- Viewing an archive -------------------------------------------------------------------------------------------
// Remove the chosen archive: clear the file box, the archive view and its markers in the 3D view.
function removeArchive() {
  hideOverlay();
  overlay.archive = null;
  $("sessionWorkFile").value = "";
  $("sessionWorkRemove").classList.add("hidden");
  renderArchive();
  $("sessionWorkFile").focus();
}

async function viewArchive() {
  const file = $("sessionWorkFile").files[0];
  $("sessionWorkRemove").classList.toggle("hidden", !file);
  if (!file) { removeArchive(); return; }
  const form = new FormData(); form.append("file", file);
  $("sessionWorkArchive").innerHTML = '<p class="sw-note">Reading the archive…</p>';
  try {
    hideOverlay();
    overlay.archive = await api(`/api/projects/${encodeURIComponent(currentProject().id)}/work-archive/view`, { method: "POST", body: form });
    overlay.archive.fileName = file.name;
    showOverlay();
    renderArchive();
  } catch (e) { $("sessionWorkArchive").innerHTML = `<div class="login-alert">${esc(e.message)}</div>`; }
}

function renderArchive() {
  const a = overlay.archive, root = $("sessionWorkArchive");
  if (!a) { root.innerHTML = ""; return; }
  const badge = a.verified ? '<span class="sw-badge ok">Verified — unmodified export of JSAN PoleGrid</span>' : '<span class="sw-badge warn">Not verified — the file was changed, or comes from another installation</span>';
  const other = a.same_project ? "" : `<p class="sw-note warn">This archive is from another dataset (${esc(a.project?.name || a.project?.id || "unknown")}); markers may not line up with this LiDAR.</p>`;
  const people = (a.summary.people || []).map(p => `<tr><td>${person(p.name, p.email)}</td><td>${p.points_created}</td><td>${p.points_modified}</td><td>${p.measurements}</td></tr>`).join("");
  const rows = a.points.slice(0, 300).map((p, i) => `<tr><td>${esc(p.feature_type)}</td><td>${esc(p.pole_number || "—")}</td><td>${person(p.created_by_name, p.created_by)}</td><td>${esc(when(p.created_at))}</td><td>${p.modified_by && p.modified_by !== p.created_by ? person(p.modified_by_name, p.modified_by) : "—"}</td><td><button type="button" class="compact-btn" data-sw-go="${i}">Go</button></td></tr>`).join("");
  const showing = overlay.markers.length > 0;
  root.innerHTML = `<div class="sw-archive-head">${badge}<span>${esc(a.fileName || "")}</span></div>${other}
    <p class="sw-note">Exported ${esc(when(a.exported_at))} by ${person(a.exported_by?.name, a.exported_by?.email)} · ${a.summary.points} points · ${a.summary.measurements} measurements · ${a.summary.assignments} assignments · ${a.summary.verified_poles} verified poles</p>
    <div class="sw-steps">${showing ? '<button type="button" class="compact-btn" data-sw-hide>Hide archive in 3D view</button>' : '<button type="button" class="compact-btn" data-sw-show>Show archive in 3D view</button>'}<span class="sw-legend"><i></i>archived points (read-only)</span></div>
    <h5>Who did the work</h5><table class="sw-table"><thead><tr><th>Person</th><th>Points created</th><th>Points changed</th><th>Measurements</th></tr></thead><tbody>${people || '<tr><td colspan="4">—</td></tr>'}</tbody></table>
    <h5>Points${a.points.length > 300 ? " (first 300)" : ""}</h5><div class="sw-scroll"><table class="sw-table"><thead><tr><th>Point</th><th>Pole</th><th>Created by</th><th>When</th><th>Last changed by</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="6">—</td></tr>'}</tbody></table></div>
    ${a.assignments.length ? `<h5>Pole assignments</h5><table class="sw-table"><thead><tr><th>Pole</th><th>Assigned to</th><th>By</th><th>When</th></tr></thead><tbody>${a.assignments.slice(0, 300).map(x => `<tr><td>${esc(x.pole_number || "—")}</td><td>${person(x.user_name, x.user_email)}</td><td>${esc(x.assigned_by || "—")}</td><td>${esc(when(x.assigned_at))}</td></tr>`).join("")}</tbody></table>` : ""}`;
}

function marker(points, name) {
  const viewer = state.productionViewer, measure = new Potree.Measure();
  measure.name = name; measure.color = new THREE.Color(ARCHIVE_COLOR); measure.closed = false;
  measure.showDistances = points.length > 1; measure.showHeight = false; measure.showCoordinates = false; measure.showEdges = points.length > 1;
  measure.maxMarkers = points.length;
  for (const p of points) measure.addMarker(new THREE.Vector3(p.x, p.y, p.z));
  for (const sphere of measure.spheres) sphere._listeners = {};  // read-only: markers can't be dragged
  viewer.scene.addMeasurement(measure);
  return measure;
}

function showOverlay() {
  const a = overlay.archive, viewer = state.productionViewer;
  if (!a || !viewer || overlay.markers.length) return;
  for (const p of a.points.slice(0, 5000)) overlay.markers.push(marker([p.coordinates], `${p.feature_type} · ${p.created_by_name || p.created_by || ""}`));
  for (const m of a.measurements.slice(0, 2000)) overlay.markers.push(marker([m.a, m.b], `Archived measurement · ${m.created_by_name || ""}`));
  $("productionArchiveBadge")?.classList.remove("hidden");
}

function hideOverlay() {
  for (const m of overlay.markers) state.productionViewer?.scene.removeMeasurement(m);
  overlay.markers = [];
  $("productionArchiveBadge")?.classList.add("hidden");
}

function flyTo(index) {
  const p = overlay.archive?.points?.[index], viewer = state.productionViewer;
  if (!p || !viewer) return;
  if (!overlay.markers.length) { showOverlay(); renderArchive(); }
  const target = new THREE.Vector3(p.coordinates.x, p.coordinates.y, p.coordinates.z), view = viewer.scene.view;
  view.setView(target.clone().add(view.direction.clone().multiplyScalar(-25)), target, 600);
  dialog.close();
}

export function init() {
  const button = $("sessionWorkBtn");
  if (!button) return;
  const sync = () => button.classList.toggle("hidden", !can("project.create") || !state.projectId);
  button.onclick = async () => { if (!dialog) build(); $("sessionWorkExportNote").textContent = ""; $("sessionWorkClear").disabled = !(lastExport && lastExport.projectId === state.projectId); await renderCurrent(); renderArchive(); dialog.showModal(); };
  $("productionArchiveHide")?.addEventListener("click", () => { hideOverlay(); if (dialog?.open) renderArchive(); });
  document.addEventListener("production-route-data-changed", sync);
  $("projectSelect")?.addEventListener("change", () => { hideOverlay(); overlay.archive = null; lastExport = null; });
  sync();
}
