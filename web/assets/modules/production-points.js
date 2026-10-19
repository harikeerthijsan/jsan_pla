// Point display for the Production viewer: size (− / + and a slider), shape (square or round) and detail level
// (how many points the viewer may draw at once). Settings are remembered per browser.
//
// Why detail matters: the viewer draws coarse overview points first and swaps them for finer ones as you zoom in,
// but only up to the point budget. With 1.4 billion points across many files, a small budget runs out close up
// and the coarse points stay on screen as large squares. A larger budget refines further; the adaptive square
// size is also capped so any leftover coarse points stay modest instead of growing to 50 px.
import { $, state } from "./core.js?v=20261019-register-alert";

const SIZES = [0.3, 0.4, 0.5, 0.6, 0.8, 1, 1.25, 1.5, 1.75, 2, 2.5, 3];
const DETAIL = { balanced: 3_000_000, high: 5_000_000, ultra: 8_000_000 };
const KEY = "pla_production_points";
const settings = { size: 1, shape: "square", detail: "high" };
try { Object.assign(settings, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch {}
if (!(settings.detail in DETAIL)) settings.detail = "high";
if (!["square", "round"].includes(settings.shape)) settings.shape = "square";
settings.size = Math.min(3, Math.max(0.3, Number(settings.size) || 1));

const save = () => { try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch {} };

function applyTo(pc) {
  const m = pc.material;
  m.size = settings.size;
  m.pointSizeType = Potree.PointSizeType.ADAPTIVE;
  m.shape = settings.shape === "round" ? Potree.PointShape.CIRCLE : Potree.PointShape.SQUARE;
  // Largest a single (coarse) point may grow on screen, in pixels.
  if (m.uniforms?.maxSize) m.uniforms.maxSize.value = Math.max(4, 12 * settings.size);
}

function applyDetail() {
  const viewer = state.productionViewer;
  if (!viewer) return;
  viewer.setPointBudget(DETAIL[settings.detail]);
  // Fetch more octree nodes in parallel so zooming in refines sooner.
  Potree.maxNodesLoading = 8;
}

export function applyProductionPointSettings() {
  applyDetail();
  for (const pc of state.productionPointclouds || []) applyTo(pc);
  render();
}

// Called for each point cloud as it loads.
export function styleProductionPointCloud(pc) { applyDetail(); applyTo(pc); }

function step(direction) {
  const index = SIZES.findIndex(s => s >= settings.size - 1e-6);
  const next = SIZES[Math.min(SIZES.length - 1, Math.max(0, (index < 0 ? SIZES.length - 1 : index) + direction))];
  setSize(next);
}

function setSize(value) {
  settings.size = Math.round(Math.min(3, Math.max(0.3, value)) * 100) / 100;
  save();
  applyProductionPointSettings();
}

function render() {
  const value = $("productionPointSizeValue");
  if (!value) return;
  value.textContent = `${Number(settings.size.toFixed(2))}×`;
  $("productionPointSmaller").disabled = settings.size <= 0.3;
  $("productionPointBigger").disabled = settings.size >= 3;
  $("productionPointSlider").value = String(settings.size);
  document.querySelectorAll("[data-point-shape]").forEach(b => { const on = b.dataset.pointShape === settings.shape; b.classList.toggle("active", on); b.setAttribute("aria-pressed", String(on)); });
  document.querySelectorAll("[data-point-detail]").forEach(b => { const on = b.dataset.pointDetail === settings.detail; b.classList.toggle("active", on); b.setAttribute("aria-pressed", String(on)); });
}

function openMenu(open) {
  const menu = $("productionPointMenu"), button = $("productionPointMenuBtn");
  menu.classList.toggle("hidden", !open);
  button.setAttribute("aria-expanded", String(open));
  if (open) menu.querySelector("input, button")?.focus({ preventScroll: true });
}

export function init() {
  if (!$("productionPointMenu")) return;
  $("productionPointSmaller").onclick = () => step(-1);
  $("productionPointBigger").onclick = () => step(1);
  $("productionPointMenuBtn").onclick = () => openMenu($("productionPointMenu").classList.contains("hidden"));
  $("productionPointSlider").addEventListener("input", event => setSize(Number(event.target.value)));
  $("productionPointMenu").addEventListener("click", event => {
    const shape = event.target.closest("[data-point-shape]")?.dataset.pointShape;
    const detail = event.target.closest("[data-point-detail]")?.dataset.pointDetail;
    if (shape) { settings.shape = shape; save(); applyProductionPointSettings(); }
    if (detail) { settings.detail = detail; save(); applyProductionPointSettings(); }
    if (event.target.closest("[data-point-reset]")) { Object.assign(settings, { size: 1, shape: "square", detail: "high" }); save(); applyProductionPointSettings(); }
  });
  document.addEventListener("mousedown", event => { if (!event.target.closest(".point-tools")) openMenu(false); });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && !$("productionPointMenu").classList.contains("hidden")) { event.stopPropagation(); openMenu(false); } }, true);
  // Keep the 3D view just below the toolbar, whatever its height (it wraps on narrow screens).
  const head = document.querySelector(".production-viewer-head"), viewer = document.querySelector(".production-viewer");
  if (head && viewer && window.ResizeObserver) new ResizeObserver(() => viewer.style.setProperty("--viewer-head-h", `${Math.round(head.offsetHeight)}px`)).observe(head);
  // Same for the profile bar (one or two rows), so the controls below it stack under it instead of overlapping.
  const profileBar = $("productionProfileBar");
  if (profileBar && viewer && window.ResizeObserver) new ResizeObserver(() => viewer.style.setProperty("--profile-bar-h", `${Math.round(profileBar.offsetHeight)}px`)).observe(profileBar);
  render();
}
