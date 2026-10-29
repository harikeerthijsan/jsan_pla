// Source CRS: read from the chosen GeoJSON ("crs" member) and LiDAR headers (first bytes only, no upload) in the import
// dialog, pre-fill Source CRS unless the user typed one, and block the import when the files and Source CRS disagree.
// Admins can also correct the CRS of an existing dataset from the header (the server checks it against the LiDAR).
import { $, api, confirmAction, toast } from "./core.js?v=20261029-saved-point-magenta";
import { can, currentProject } from "./workspace.js?v=20261029-saved-point-magenta";

// ---- Reading the CRS of a file ------------------------------------------------------------------------------------
function epsgFromName(name) {
  const text = String(name || "").trim();
  if (/CRS84$/i.test(text)) return 4326;
  const match = text.match(/EPSG:+(\d+)$/i);
  return match ? Number(match[1]) : null;
}

async function geojsonEpsg(file) {
  try {
    const doc = JSON.parse(await file.text());
    return doc?.crs?.properties?.name ? epsgFromName(doc.crs.properties.name) : 4326;  // no "crs" member = WGS84
  } catch { return null; }
}

// The projected CRS's own EPSG id inside a WKT1 PROJCS[...] / WKT2 PROJCRS[...] block (last authority in the block).
function wktEpsg(wkt) {
  const start = Math.max(wkt.indexOf("PROJCS["), wkt.indexOf("PROJCRS["));
  const from = start >= 0 ? start : 0;
  let depth = 0, end = wkt.length;
  for (let i = from; i < wkt.length; i++) {
    if (wkt[i] === "[") depth++;
    else if (wkt[i] === "]" && --depth === 0) { end = i; break; }
  }
  // Only an id that is a direct child of the PROJCS block identifies it (nested ones belong to the datum, units …).
  const block = wkt.slice(from, end + 1);
  let level = 0;
  for (let i = 0; i < block.length; i++) {
    if (block[i] === "[") level++;
    else if (block[i] === "]") level--;
    else if (level === 1 && /^(?:AUTHORITY|ID)\[/.test(block.slice(i, i + 10))) {
      const match = block.slice(i).match(/^(?:AUTHORITY|ID)\[\s*"EPSG"\s*,\s*"?(\d+)"?/);
      if (match) return Number(match[1]);
    }
  }
  return null;
}

// LAS/LAZ/COPC header + VLRs: WKT (LASF_Projection 2112) or GeoTIFF keys (34735, ProjectedCSTypeGeoKey 3072).
async function lidarEpsg(file) {
  const head = new DataView(await file.slice(0, 375).arrayBuffer());
  if (head.byteLength < 227 || String.fromCharCode(head.getUint8(0), head.getUint8(1), head.getUint8(2), head.getUint8(3)) !== "LASF") return null;
  const headerSize = head.getUint16(94, true), pointOffset = head.getUint32(96, true), vlrCount = head.getUint32(100, true);
  const view = new DataView(await file.slice(0, Math.min(pointOffset, 4 * 1024 * 1024)).arrayBuffer());
  const text = (offset, length) => new TextDecoder().decode(new Uint8Array(view.buffer, offset, length)).split("\0")[0];
  let offset = headerSize, geokey = null;
  for (let n = 0; n < vlrCount && offset + 54 <= view.byteLength; n++) {
    const user = text(offset + 2, 16), record = view.getUint16(offset + 18, true), length = view.getUint16(offset + 20, true), data = offset + 54;
    if (user === "LASF_Projection" && record === 2112 && data + length <= view.byteLength) {
      // Identify the WKT on the server (same library as the processing check): many LiDAR WKTs name the projection
      // without an EPSG id, and the ids inside it (datum, units) are not the projected CRS.
      const wkt = text(data, length);
      try { const found = await api("/api/crs/identify", { method: "POST", body: JSON.stringify({ wkt }) }); if (found?.epsg) return found.epsg; } catch {}
      const code = wktEpsg(wkt);
      if (code) return code;
    }
    if (user === "LASF_Projection" && record === 34735 && data + 8 <= view.byteLength) {
      const keys = view.getUint16(data + 6, true);
      for (let k = 0; k < keys; k++) {
        const at = data + 8 + k * 8;
        if (at + 8 <= view.byteLength && view.getUint16(at, true) === 3072 && view.getUint16(at + 2, true) === 0) geokey = view.getUint16(at + 6, true);
      }
    }
    offset = data + length;
  }
  return geokey;
}

const names = {};
async function crsName(code) {
  if (!code) return "";
  if (!(code in names)) { try { names[code] = (await api(`/api/crs/${code}`)).name || ""; } catch { names[code] = ""; } }
  return names[code];
}
const label = async code => { const name = await crsName(code); return `EPSG:${code}${name ? ` (${name})` : ""}`; };

// ---- Import dialog --------------------------------------------------------------------------------------------------
let detected = { geojson: null, lidar: [], key: "" };

async function detect() {
  const geo = $("productionGeojsonFile").files[0], lidar = [...$("productionLidarFiles").files];
  const key = `${geo?.name}|${geo?.size}|${lidar.map(f => `${f.name}:${f.size}`).join(",")}`;
  if (key === detected.key) return detected;
  const lidarCodes = [];
  for (const file of lidar.slice(0, 60)) { const code = await lidarEpsg(file); if (code) lidarCodes.push({ name: file.name, code }); }
  detected = { geojson: geo ? await geojsonEpsg(geo) : null, lidar: lidarCodes, key };
  return detected;
}

// Problems between the files and the Source CRS; also pre-fills Source CRS when the user hasn't typed one.
export async function checkSourceCrs({ fill = true } = {}) {
  const input = $("productionCrs"), note = $("productionCrsNote");
  const found = await detect(), problems = [];
  const lidarSet = [...new Set(found.lidar.map(l => l.code))];
  if (lidarSet.length > 1) problems.push(`The LiDAR files are in different coordinate systems (${lidarSet.map(c => `EPSG:${c}`).join(", ")}). Upload one coordinate system per dataset.`);
  const projectedGeo = found.geojson && found.geojson !== 4326 ? found.geojson : null;
  if (lidarSet.length === 1 && projectedGeo && projectedGeo !== lidarSet[0]) problems.push(`The GeoJSON is EPSG:${projectedGeo} but the LiDAR is EPSG:${lidarSet[0]}.`);
  const fileCode = lidarSet.length === 1 ? lidarSet[0] : projectedGeo;
  let filled = "";
  if (fill && fileCode && !input.dataset.userSet && epsgFromName(input.value) !== fileCode) {
    input.value = `EPSG:${fileCode}`;
    filled = lidarSet.length === 1 ? "the LiDAR files" : "the GeoJSON";
  }
  const chosen = epsgFromName(input.value);
  if (fileCode && chosen && chosen !== fileCode && !problems.length) {
    problems.push(`The ${lidarSet.length === 1 ? "LiDAR files are" : "GeoJSON is"} in ${await label(fileCode)}, but Source CRS is EPSG:${chosen}. Change Source CRS to EPSG:${fileCode}.`);
  }
  note.className = "format-hint" + (problems.length ? " is-error" : fileCode ? " is-ok" : "");
  note.textContent = problems.length ? problems.join(" ") : filled ? `Set from ${filled}: ${await label(fileCode)}.` : fileCode ? `Matches the files: ${await label(fileCode)}.` : "";
  return problems;
}

// ---- Admin: correct the CRS of an existing dataset --------------------------------------------------------------------
function renderCrsControl() {
  const control = $("productionCrsControl"); if (!control) return;
  const project = currentProject();
  control.classList.toggle("hidden", !project.id || !can("project.create"));
  $("productionCrsCurrent").textContent = project.crs || "—";
  $("productionCrsEdit").classList.add("hidden");
}

async function applyCrs() {
  const project = currentProject(), value = $("productionCrsInput").value.trim(), code = epsgFromName(value) || (/^\d+$/.test(value) ? Number(value) : null);
  if (!code) { toast("Enter the coordinate system as an EPSG code, e.g. EPSG:6426.", "error"); return; }
  const ok = await confirmAction(`Change this dataset's CRS from ${project.crs} to EPSG:${code}? Saved points' latitude/longitude are recalculated, and the poles and GeoJSON are re-imported with the new CRS. The LiDAR itself is not changed.`, { confirmLabel: "Change CRS" });
  if (!ok) return;
  const button = $("productionCrsApply"); button.disabled = true;
  try {
    const saved = await api(`/api/projects/${encodeURIComponent(project.id)}/crs`, { method: "PUT", body: JSON.stringify({ crs: `EPSG:${code}` }) });
    project.crs = saved.crs; renderCrsControl();
    toast(`CRS changed to ${saved.crs}${saved.crs_name ? ` (${saved.crs_name})` : ""}. ${saved.recomputed_points} saved point${saved.recomputed_points === 1 ? "" : "s"} recalculated${saved.reprocess_job_id ? "; poles and GeoJSON are being re-imported and will move into place when it finishes" : ""}.`, "success", 9000);
  } catch (e) { toast(`CRS not changed: ${e.message}`, "error", 9000); } finally { button.disabled = false; }
}

export function init() {
  const input = $("productionCrs");
  if (!input) return;
  input.addEventListener("input", () => { input.dataset.userSet = "1"; checkSourceCrs({ fill: false }); });
  for (const id of ["productionGeojsonFile", "productionLidarFiles"]) $(id).addEventListener("change", () => checkSourceCrs());
  $("productionUploadForm").addEventListener("reset", () => { delete input.dataset.userSet; detected = { geojson: null, lidar: [], key: "" }; $("productionCrsNote").textContent = ""; });
  $("productionCrsChange")?.addEventListener("click", () => { $("productionCrsEdit").classList.remove("hidden"); $("productionCrsInput").value = currentProject().crs || ""; $("productionCrsInput").focus(); });
  $("productionCrsApply")?.addEventListener("click", applyCrs);
  $("productionCrsCancel")?.addEventListener("click", () => $("productionCrsEdit").classList.add("hidden"));
  document.addEventListener("production-route-data-changed", renderCrsControl);
  $("projectSelect")?.addEventListener("change", () => setTimeout(renderCrsControl, 0));
  renderCrsControl();
}
export { renderCrsControl };
