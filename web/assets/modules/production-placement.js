// Placing a point where there is no LiDAR return. A click in empty space has no depth, so the point goes where the
// cursor ray meets a working plane, chosen to match what the user is looking at:
//   • profile / section view  → the section plane itself (exact: the view is drawn on it);
//   • looking straight down   → a level plane at the pole's ground height (pole bases in gaps);
//   • any other 3D view       → an upright plane through the selected pole, facing the camera (attachments,
//                               crossarms and pole tops beside the pole), or through the view's pivot if no pole.
// Every point records how it was placed ("placement"), so QC can tell snapped points from free ones.
import * as THREE from "../../potree/libs/three.js/build/three.module.js";
import { $, state } from "./core.js?v=20261012-box-close-focus-1";
import { productionGeoGround, productionGeoPoleRange } from "./production-geo.js?v=20261012-box-close-focus-1";
import { productionProfileFrame } from "./production-profile.js?v=20261012-box-close-focus-1";

export const PLACEMENT_LABELS = {
  lidar: "Snapped to a LiDAR point",
  section_plane: "Open space · on the profile section",
  pole_plane: "Open space · on the pole's vertical plane",
  ground_plane: "Open space · at ground level",
  view_plane: "Open space · at the view centre's depth",
};
const MAX_REACH = 2000; // project units; anything further is a grazing-angle accident, not an intended point

const raycaster = new THREE.Raycaster();
const ndc = new THREE.Vector2();
const target = new THREE.Vector3();

// Where the selected pole stands: its saved base, else its GeoJSON location with the estimated ground height.
export function selectedPoleAnchor() {
  const id = $("annotationPoleId")?.value;
  if (!id) return null;
  const pole = state.productionPoles?.find(p => String(p.internal_id) === id);
  if (pole?.verified_x != null && pole?.verified_y != null) {
    return { x: Number(pole.verified_x), y: Number(pole.verified_y), z: Number(pole.verified_bottom_elevation ?? pole.verified_z ?? 0) };
  }
  const feature = (state.productionGeoFeatures || []).find(f => String(f.pole_internal_id) === id && f.x != null && f.y != null);
  if (feature) return { x: Number(feature.x), y: Number(feature.y), z: Number(productionGeoPoleRange(feature)[0]) };
  return null;
}

function groundZ(anchor, pivot) {
  if (anchor && Number.isFinite(anchor.z)) return anchor.z;
  const ground = Number(productionGeoGround?.());
  return Number.isFinite(ground) ? ground : pivot.z;
}

// px, py: position inside the viewer canvas (CSS pixels). Returns { location, placement } or { error }.
export function placeInOpenSpace(px, py) {
  const viewer = state.productionViewer;
  if (!viewer) return { error: "The 3D view is not ready" };
  const dom = viewer.renderer.domElement, camera = viewer.scene.getActiveCamera();
  ndc.set((px / dom.clientWidth) * 2 - 1, -(py / dom.clientHeight) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  const ray = raycaster.ray, pivot = viewer.scene.view.getPivot();
  const anchor = selectedPoleAnchor();
  const attempts = [];

  if (state.productionProfile) {
    const f = productionProfileFrame();
    attempts.push({ placement: "section_plane", plane: new THREE.Plane().setFromNormalAndCoplanarPoint(new THREE.Vector3(f.n.x, f.n.y, 0), new THREE.Vector3(f.cx, f.cy, f.cz)) });
  }
  const level = new THREE.Plane(new THREE.Vector3(0, 0, 1), -groundZ(anchor, pivot));
  const horizontal = new THREE.Vector3(ray.direction.x, ray.direction.y, 0);
  if (Math.abs(ray.direction.z) > 0.9 || horizontal.lengthSq() < 1e-6) {
    attempts.push({ placement: "ground_plane", plane: level });
  } else {
    const through = anchor || pivot;
    attempts.push({ placement: anchor ? "pole_plane" : "view_plane", plane: new THREE.Plane().setFromNormalAndCoplanarPoint(horizontal.normalize().negate(), new THREE.Vector3(through.x, through.y, through.z)) });
    attempts.push({ placement: "ground_plane", plane: level });
  }

  for (const { placement, plane } of attempts) {
    if (!ray.intersectPlane(plane, target)) continue;
    const from = anchor || pivot;
    if (Math.hypot(target.x - from.x, target.y - from.y) > MAX_REACH) continue;
    return { location: target.clone(), placement };
  }
  return { error: "Could not place a point there. Rotate the view towards the pole, use Top view, or click on the LiDAR." };
}

// Snap to LiDAR when a return is under the cursor; otherwise place in open space.
export function pickOrPlace(px, py) {
  const viewer = state.productionViewer;
  const hit = Potree.Utils.getMousePointCloudIntersection({ x: px, y: py }, viewer.scene.getActiveCamera(), viewer, viewer.scene.pointclouds);
  if (hit) return { location: hit.location, placement: "lidar" };
  return placeInOpenSpace(px, py);
}

export function init() {}
