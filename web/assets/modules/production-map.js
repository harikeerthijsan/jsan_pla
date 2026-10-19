// Real-map horizontal adjustment for a point already placed in LiDAR/profile. The map supplies WGS84 X/Y only;
// elevation remains the value selected in the engineering view. The API performs both CRS transformations using
// the project's declared CRS, so arbitrary EPSG definitions are never guessed in the browser.
import * as THREE from "../../potree/libs/three.js/build/three.module.js";
import { $, api, cfg, state, toast } from "./core.js?v=20261019-register-alert";
import { setAnnotationDraft } from "./production-annotations.js?v=20261019-register-alert";
import { PLACEMENT_LABELS } from "./production-placement.js?v=20261019-register-alert";

let dialog = null, map = null, markerSource = null;
const MAX_OVERLAY_TILES = 64;

function fieldNumber(id) {
  const value = Number($(id).value);
  return Number.isFinite(value) ? value : null;
}

function buildDialog() {
  dialog = document.createElement("dialog");
  dialog.id = "productionMapDialog";
  dialog.className = "production-map-dialog";
  dialog.innerHTML = `<form method="dialog">
    <header><div><h3>Adjust point on map</h3><p>Click the street map to refine X/Y and latitude/longitude. Elevation Z stays fixed to the LiDAR/profile selection.</p></div><button value="cancel" class="map-dialog-close" aria-label="Close map">×</button></header>
    <div id="productionMapCanvas" class="production-map-canvas" aria-label="OpenStreetMap point picker"></div>
    <div class="production-map-fields">
      <label>Latitude<input id="productionMapLatitude" type="number" min="-90" max="90" step="0.00000001" inputmode="decimal"></label>
      <label>Longitude<input id="productionMapLongitude" type="number" min="-180" max="180" step="0.00000001" inputmode="decimal"></label>
      <span>Preserved elevation <b id="productionMapElevation">—</b></span>
    </div>
    <p class="production-map-privacy">Map tiles are loaded from OpenStreetMap. Only the area currently viewed is requested.</p>
    <div id="productionMapError" class="error" role="alert"></div>
    <footer><button value="cancel">Cancel</button><button type="button" id="productionMapUseBtn" class="primary">Use map position</button></footer>
  </form>`;
  document.body.appendChild(dialog);
  $("productionMapUseBtn").onclick = applyMapPosition;
  for (const id of ["productionMapLatitude", "productionMapLongitude"]) $(id).addEventListener("change", updateMarkerFromFields);
}

function setMapPosition(latitude, longitude, centre = false) {
  $("productionMapLatitude").value = latitude.toFixed(8);
  $("productionMapLongitude").value = longitude.toFixed(8);
  const coordinate = ol.proj.fromLonLat([longitude, latitude]);
  markerSource.clear();
  markerSource.addFeature(new ol.Feature(new ol.geom.Point(coordinate)));
  if (centre) map.getView().setCenter(coordinate);
}

function updateMarkerFromFields() {
  if (!map) return;
  const latitude = fieldNumber("productionMapLatitude"), longitude = fieldNumber("productionMapLongitude");
  if (latitude != null && longitude != null && latitude >= -90 && latitude <= 90 && longitude >= -180 && longitude <= 180) setMapPosition(latitude, longitude, true);
}

function createMap(latitude, longitude) {
  markerSource = new ol.source.Vector();
  const markerLayer = new ol.layer.Vector({
    source: markerSource,
    style: new ol.style.Style({
      image: new ol.style.Circle({
        radius: 8,
        fill: new ol.style.Fill({ color: "#13b9e6" }),
        stroke: new ol.style.Stroke({ color: "#ffffff", width: 3 }),
      }),
    }),
  });
  const attributionText = String(cfg.MAP_ATTRIBUTION || "© OpenStreetMap contributors").replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
  const source = new ol.source.XYZ({
    url: String(cfg.MAP_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
    crossOrigin: "anonymous",
    maxZoom: 19,
    attributions: [new ol.Attribution({ html: `${attributionText} · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">Copyright</a>` })],
  });
  map = new ol.Map({
    target: "productionMapCanvas",
    layers: [new ol.layer.Tile({ source }), markerLayer],
    view: new ol.View({ center: ol.proj.fromLonLat([longitude, latitude]), zoom: 19, minZoom: 2, maxZoom: 19 }),
  });
  map.on("singleclick", event => {
    const [longitudeAtClick, latitudeAtClick] = ol.proj.toLonLat(event.coordinate);
    setMapPosition(latitudeAtClick, longitudeAtClick);
  });
}

async function currentGeographic() {
  const draft = state.productionDraft;
  if (!draft || !state.projectId) return null;
  const cached = state.productionDraftGeographic;
  if (cached?.latitude != null && cached?.longitude != null) return cached;
  return api(`/api/projects/${state.projectId}/coordinates/to-wgs84`, { method: "POST", body: JSON.stringify(draft) });
}

export async function openProductionMapPicker() {
  if (!state.productionDraft) { toast("Pick a LiDAR or profile position first so its elevation is known.", "info", 4200); return; }
  if (typeof ol === "undefined") { toast("The map library is unavailable.", "error", 4200); return; }
  const trigger = document.querySelector('[data-qs="map"]');
  if (trigger) trigger.disabled = true;
  try {
    const geographic = await currentGeographic();
    const latitude = Number(geographic?.latitude), longitude = Number(geographic?.longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) throw new Error("The project CRS could not produce a valid map location");
    $("productionMapError").textContent = "";
    $("productionMapElevation").textContent = Number(state.productionDraft.z).toFixed(3);
    dialog.showModal();
    if (!map) createMap(latitude, longitude);
    setMapPosition(latitude, longitude, true);
    setTimeout(() => map.updateSize(), 0);
  } catch (error) {
    toast(error.message, "error", 5200);
  } finally {
    if (trigger) trigger.disabled = false;
  }
}

async function applyMapPosition() {
  const latitude = fieldNumber("productionMapLatitude"), longitude = fieldNumber("productionMapLongitude");
  if (latitude == null || longitude == null || latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
    $("productionMapError").textContent = "Enter valid latitude and longitude values, or click the map.";
    return;
  }
  if (!state.productionDraft) { dialog.close(); return; }
  const button = $("productionMapUseBtn"), z = state.productionDraft.z;
  button.disabled = true;
  $("productionMapError").textContent = "";
  try {
    const result = await api(`/api/projects/${state.projectId}/coordinates/from-wgs84`, {
      method: "POST",
      body: JSON.stringify({ latitude, longitude, z }),
    });
    state.productionDraftPlacement = "map";
    setAnnotationDraft({ x: result.x, y: result.y, z });
    $("annotationMode").textContent = `New point · ${PLACEMENT_LABELS.map} · elevation preserved from LiDAR`;
    dialog.close();
    toast("Map position applied. The LiDAR/profile elevation was preserved.", "success", 3600);
  } catch (error) {
    $("productionMapError").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function overlayBounds() {
  const rows = (state.productionBlocks || []).map(block => block.bounds).filter(Boolean);
  if (!rows.length) return null;
  const bounds = {
    xMin: Math.min(...rows.map(row => Number(row.x_min))),
    yMin: Math.min(...rows.map(row => Number(row.y_min))),
    zMin: Math.min(...rows.map(row => Number(row.z_min))),
    xMax: Math.max(...rows.map(row => Number(row.x_max))),
    yMax: Math.max(...rows.map(row => Number(row.y_max))),
    zMax: Math.max(...rows.map(row => Number(row.z_max))),
  };
  return Object.values(bounds).every(Number.isFinite) && bounds.xMax > bounds.xMin && bounds.yMax > bounds.yMin ? bounds : null;
}

const clampLatitude = latitude => Math.max(-85.05112878, Math.min(85.05112878, latitude));
const tileX = (longitude, zoom) => Math.floor((longitude + 180) / 360 * 2 ** zoom);
const tileY = (latitude, zoom) => Math.floor((1 - Math.asinh(Math.tan(clampLatitude(latitude) * Math.PI / 180)) / Math.PI) / 2 * 2 ** zoom);
const tileLongitude = (x, zoom) => x / 2 ** zoom * 360 - 180;
const tileLatitude = (y, zoom) => Math.atan(Math.sinh(Math.PI * (1 - 2 * y / 2 ** zoom))) * 180 / Math.PI;

function tileRange(wgs, zoom) {
  const size = 2 ** zoom;
  const x0 = Math.max(0, Math.min(size - 1, tileX(wgs.west, zoom)));
  const x1 = Math.max(0, Math.min(size - 1, tileX(wgs.east, zoom)));
  const y0 = Math.max(0, Math.min(size - 1, tileY(wgs.north, zoom)));
  const y1 = Math.max(0, Math.min(size - 1, tileY(wgs.south, zoom)));
  return { x0: Math.min(x0, x1), x1: Math.max(x0, x1), y0: Math.min(y0, y1), y1: Math.max(y0, y1), count: (Math.abs(x1 - x0) + 1) * (Math.abs(y1 - y0) + 1) };
}

function overlayKey(bounds) {
  return `${state.projectId}|${bounds.xMin}|${bounds.yMin}|${bounds.xMax}|${bounds.yMax}`;
}

function overlayGroup() {
  const viewer = state.productionViewer;
  if (!viewer) return null;
  if (!state.productionMapOverlayGroup) {
    state.productionMapOverlayGroup = new THREE.Group();
    state.productionMapOverlayGroup.name = "OpenStreetMap ground overlay";
    viewer.scene.scene.add(state.productionMapOverlayGroup);
  }
  return state.productionMapOverlayGroup;
}

function clearOverlayGroup() {
  const group = state.productionMapOverlayGroup;
  if (!group) return;
  while (group.children.length) {
    const child = group.children.pop();
    child.geometry?.dispose?.();
    child.material?.map?.dispose?.();
    child.material?.dispose?.();
  }
  state.productionMapOverlayKey = null;
}

function applyOverlayIntensity() {
  const value = Math.max(.05, Math.min(1, Number(state.productionMapOverlayIntensity) || .42));
  for (const child of state.productionMapOverlayGroup?.children || []) {
    child.material.opacity = value;
    child.material.needsUpdate = true;
  }
  const output = $("productionMapIntensityValue");
  if (output) output.textContent = `${Math.round(value * 100)}%`;
}

function overlayTileUrl(zoom, x, y) {
  return String(cfg.MAP_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    .replace("{z}", String(zoom)).replace("{x}", String(x)).replace("{y}", String(y));
}

async function projectCornersToWgs84(bounds) {
  const corners = [
    { x: bounds.xMin, y: bounds.yMin, z: bounds.zMin },
    { x: bounds.xMin, y: bounds.yMax, z: bounds.zMin },
    { x: bounds.xMax, y: bounds.yMin, z: bounds.zMin },
    { x: bounds.xMax, y: bounds.yMax, z: bounds.zMin },
  ];
  const converted = await Promise.all(corners.map(point => api(`/api/projects/${state.projectId}/coordinates/to-wgs84`, { method: "POST", body: JSON.stringify(point) })));
  const latitudes = converted.map(point => Number(point.latitude)), longitudes = converted.map(point => Number(point.longitude));
  if (![...latitudes, ...longitudes].every(Number.isFinite)) throw new Error("The project bounds could not be transformed to a map area");
  const wgs = { south: Math.min(...latitudes), north: Math.max(...latitudes), west: Math.min(...longitudes), east: Math.max(...longitudes) };
  if (wgs.east - wgs.west > 180) throw new Error("Map overlay is not available for a dataset crossing the antimeridian");
  return wgs;
}

async function overlayGridInProject(range, zoom) {
  const points = [];
  for (let y = range.y0; y <= range.y1 + 1; y++) for (let x = range.x0; x <= range.x1 + 1; x++) {
    points.push({ longitude: tileLongitude(x, zoom), latitude: tileLatitude(y, zoom), gridX: x, gridY: y });
  }
  const result = await api(`/api/projects/${state.projectId}/coordinates/from-wgs84/batch`, {
    method: "POST",
    body: JSON.stringify({ points: points.map(({ latitude, longitude }) => ({ latitude, longitude })) }),
  });
  const grid = new Map();
  points.forEach((point, index) => grid.set(`${point.gridX}/${point.gridY}`, result.points[index]));
  return grid;
}

function addOverlayTile(group, loader, grid, zoom, x, y, z, origin) {
  const nw = grid.get(`${x}/${y}`), ne = grid.get(`${x + 1}/${y}`), sw = grid.get(`${x}/${y + 1}`), se = grid.get(`${x + 1}/${y + 1}`);
  if (![nw, ne, sw, se].every(Boolean)) return;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute([
    nw.x - origin.x, nw.y - origin.y, z, ne.x - origin.x, ne.y - origin.y, z, sw.x - origin.x, sw.y - origin.y, z,
    ne.x - origin.x, ne.y - origin.y, z, se.x - origin.x, se.y - origin.y, z, sw.x - origin.x, sw.y - origin.y, z,
  ], 3));
  geometry.setAttribute("uv", new THREE.Float32BufferAttribute([0, 1, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0], 2));
  const texture = loader.load(overlayTileUrl(zoom, x, y));
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  const material = new THREE.MeshBasicMaterial({ map: texture, transparent: true, opacity: state.productionMapOverlayIntensity, side: THREE.DoubleSide, depthTest: true, depthWrite: false });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = `OSM ${zoom}/${x}/${y}`;
  mesh.renderOrder = -10;
  mesh.frustumCulled = false;
  group.add(mesh);
}

async function ensureMapOverlay() {
  if (!state.productionMapOverlayVisible) return;
  const bounds = overlayBounds(), group = overlayGroup(), button = $("productionMapOverlayBtn");
  if (!bounds || !group) return;
  const key = overlayKey(bounds);
  if (state.productionMapOverlayKey === key && group.children.length) { group.visible = true; return; }
  const generation = ++state.productionMapOverlayGeneration, projectId = state.projectId;
  group.visible = false;
  button.disabled = true;
  button.textContent = "Map…";
  try {
    const wgs = await projectCornersToWgs84(bounds);
    let zoom = 19, range = tileRange(wgs, zoom);
    while (zoom > 2 && range.count > MAX_OVERLAY_TILES) range = tileRange(wgs, --zoom);
    if (range.count > MAX_OVERLAY_TILES) throw new Error("The dataset is too large for the interactive map overlay");
    const grid = await overlayGridInProject(range, zoom);
    if (generation !== state.productionMapOverlayGeneration || projectId !== state.projectId) return;
    clearOverlayGroup();
    const clearance = Math.max((bounds.zMax - bounds.zMin) * .003, .05), z = bounds.zMin - clearance;
    const origin = { x: bounds.xMin, y: bounds.yMin };
    group.position.set(origin.x, origin.y, 0);
    group.updateMatrixWorld(true);
    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin("anonymous");
    for (let y = range.y0; y <= range.y1; y++) for (let x = range.x0; x <= range.x1; x++) addOverlayTile(group, loader, grid, zoom, x, y, z, origin);
    state.productionMapOverlayKey = key;
    group.visible = state.productionMapOverlayVisible;
    applyOverlayIntensity();
    toast(`3D map overlay loaded (${range.count} tile${range.count === 1 ? "" : "s"}).`, "success", 3200);
  } catch (error) {
    state.productionMapOverlayVisible = false;
    group.visible = false;
    toast(`Map overlay could not load: ${error.message}`, "error", 6000);
  } finally {
    if (generation === state.productionMapOverlayGeneration) {
      button.disabled = !state.productionBlocks?.length;
      button.textContent = "Map";
      button.classList.toggle("active", state.productionMapOverlayVisible);
      $("productionMapIntensityControl").classList.toggle("hidden", !state.productionMapOverlayVisible);
      $("productionMapAttribution").classList.toggle("hidden", !state.productionMapOverlayVisible);
    }
  }
}

function syncOverlayAvailability() {
  const available = Boolean(state.productionViewer && state.projectId && state.productionBlocks?.length), button = $("productionMapOverlayBtn");
  if (!button) return;
  button.disabled = !available;
  if (!available && state.productionMapOverlayGroup) state.productionMapOverlayGroup.visible = false;
  if (!available) $("productionMapAttribution")?.classList.add("hidden");
  if (available && state.productionMapOverlayVisible) ensureMapOverlay();
}

function buildOverlayControls() {
  const button = document.createElement("button");
  button.id = "productionMapOverlayBtn";
  button.type = "button";
  button.className = "compact-btn";
  button.textContent = "Map";
  button.title = "Overlay OpenStreetMap beneath the LiDAR point cloud";
  button.disabled = true;
  // Hidden for now at the user's request; the overlay code stays so it can be shown again by removing this line.
  button.hidden = true;
  $("productionGeoToggleBtn").after(button);
  const control = document.createElement("div");
  control.id = "productionMapIntensityControl";
  control.className = "production-map-intensity hidden";
  control.innerHTML = `<label><span>Map intensity</span><input id="productionMapIntensity" type="range" min="5" max="100" step="1" value="42" aria-label="Map overlay intensity"><b id="productionMapIntensityValue">42%</b></label>`;
  const attribution = document.createElement("a");
  attribution.id = "productionMapAttribution";
  attribution.className = "production-map-attribution hidden";
  attribution.href = "https://www.openstreetmap.org/copyright";
  attribution.target = "_blank";
  attribution.rel = "noopener noreferrer";
  attribution.textContent = "© OpenStreetMap";
  const viewer = document.querySelector(".production-viewer");
  viewer.append(control, attribution);
  button.onclick = () => {
    state.productionMapOverlayVisible = !state.productionMapOverlayVisible;
    button.classList.toggle("active", state.productionMapOverlayVisible);
    control.classList.toggle("hidden", !state.productionMapOverlayVisible);
    attribution.classList.toggle("hidden", !state.productionMapOverlayVisible);
    if (state.productionMapOverlayGroup) state.productionMapOverlayGroup.visible = state.productionMapOverlayVisible;
    if (state.productionMapOverlayVisible) ensureMapOverlay();
  };
  $("productionMapIntensity").oninput = event => {
    state.productionMapOverlayIntensity = Number(event.target.value) / 100;
    applyOverlayIntensity();
  };
  document.addEventListener("production-route-data-changed", syncOverlayAvailability);
  syncOverlayAvailability();
}

export function init() {
  buildDialog();
  buildOverlayControls();
}
