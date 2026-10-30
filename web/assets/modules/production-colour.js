// LiDAR colouring for the Production viewer: Intensity, RGB or Elevation, chosen from the toolbar dropdown.
// Ranges come from a sample of the points actually loaded (2nd–98th percentile), so a few outliers (birds,
// noise) don't wash the colours out, and every tile shares one range so the same height or return strength
// looks the same everywhere in the combined model.
import * as THREE from "../../potree/libs/three.js/build/three.module.js";
import { $, state, toast } from "./core.js?v=20261030-pla1-from-points";

const MODES = { intensity: "intensity", rgb: "rgba", elevation: "elevation" };
const KEY = "pla_production_colour";
let mode = "elevation", sampled = null, timer = null;
try { const saved = localStorage.getItem(KEY); if (saved in MODES) mode = saved; } catch {}

const percentile = (sorted, p) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(p * (sorted.length - 1))))];

// Read a spread of values from the nodes currently in memory (cheap: a few tens of thousands of points).
function sample() {
  const z = [], intensity = [];
  let rgbSeen = 0, rgbLit = 0;
  const v = new THREE.Vector3();
  for (const pc of state.productionPointclouds || []) {
    for (const node of pc.visibleNodes || []) {
      const scene = node.sceneNode, g = scene?.geometry;
      if (!g) continue;
      const pos = g.attributes.position, inten = g.attributes.intensity, rgba = g.attributes.rgba;
      const count = pos?.count || 0, step = Math.max(1, Math.floor(count / 400));
      for (let i = 0; i < count; i += step) {
        v.fromBufferAttribute(pos, i).applyMatrix4(scene.matrixWorld);
        z.push(v.z);
        if (inten) intensity.push(inten.array[i]);
        if (rgba) { rgbSeen++; if (rgba.array[i * 4] || rgba.array[i * 4 + 1] || rgba.array[i * 4 + 2]) rgbLit++; }
      }
    }
  }
  if (z.length < 200) return null;
  z.sort((a, b) => a - b);
  intensity.sort((a, b) => a - b);
  return {
    elevation: [percentile(z, 0.02), percentile(z, 0.98)],
    intensity: intensity.length > 200 ? [percentile(intensity, 0.01), percentile(intensity, 0.98)] : null,
    rgb: rgbSeen > 200 ? rgbLit / rgbSeen > 0.02 : null,
  };
}

function applyTo(pc) {
  const material = pc.material;
  material.activeAttributeName = MODES[mode];
  if (mode === "elevation" && sampled?.elevation) material.elevationRange = sampled.elevation;
  if (mode === "intensity" && sampled?.intensity && sampled.intensity[1] > sampled.intensity[0]) material.intensityRange = sampled.intensity;
}

function updateMenu() {
  const select = $("productionColourMode");
  if (!select) return;
  const rgb = select.querySelector('option[value="rgb"]');
  const missing = sampled?.rgb === false;
  rgb.disabled = missing && mode !== "rgb";
  rgb.textContent = missing ? "RGB view (not in this LiDAR)" : "RGB view";
  select.value = mode;
  select.disabled = !state.productionPointclouds?.length;
}

// Called for each point cloud as it loads, and again (debounced) once loading settles, to refine the ranges.
export function colourProductionPointCloud(pc) {
  applyTo(pc);
  clearTimeout(timer);
  timer = setTimeout(refreshProductionColours, 2500);
}

export function refreshProductionColours() {
  const next = sample();
  if (next) sampled = next;
  for (const pc of state.productionPointclouds || []) applyTo(pc);
  updateMenu();
}

export function setProductionColourMode(next) {
  if (!(next in MODES)) return;
  mode = next;
  try { localStorage.setItem(KEY, mode); } catch {}
  refreshProductionColours();
  if (mode === "rgb" && sampled?.rgb === false) toast("This LiDAR has no RGB colour values, so points show without colour. Try Intensity or Elevation.", "info", 6000);
}

export function init() {
  const select = $("productionColourMode");
  if (!select) return;
  select.value = mode;
  select.addEventListener("change", () => setProductionColourMode(select.value));
  // Refresh the RGB check when the menu is opened, since more of the cloud may have loaded.
  select.addEventListener("focus", () => { const next = sample(); if (next) { sampled = next; updateMenu(); } });
  updateMenu();
}
