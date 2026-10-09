// Full-page LiDAR utility-corridor scene generated locally with Canvas 2D.
// The reduced-motion experience renders the same scene as a still frame.

const TAU = Math.PI * 2;
const LOOP_DEPTH = 294;
const NEAR_DEPTH = 7;
const CAMERA_HEIGHT = 10.5;
const POLE_HEIGHT = 18;
const POLE_SPACING = 42;
const INSPECTION_CYCLE_MS = 18000;
const DPR_CAP = 1.75;
const TARGET_FRAME_MS = 1000 / 30;
const WARP_MS = 3000;

const COLORS = {
  ground: "55, 164, 184",
  groundFar: "40, 108, 135",
  vegetation: "72, 199, 159",
  corridor: "101, 224, 238",
  infrastructure: "205, 246, 250",
  equipment: "255, 190, 92",
  building: "105, 177, 205",
  highlight: "96, 239, 255",
  scan: "51, 220, 255",
};

function mulberry32(seed) {
  return function random() {
    let value = (seed += 0x6d2b79f5);
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function hash(x, z) {
  const value = Math.sin(x * 12.9898 + z * 78.233) * 43758.5453;
  return value - Math.floor(value);
}

function terrainHeight(x, z) {
  return (
    Math.sin(z * 0.055) * 0.55 +
    Math.sin(x * 0.24 + z * 0.025) * 0.38 +
    (hash(Math.floor(x * 1.3), Math.floor(z * 0.4)) - 0.5) * 0.22
  );
}

function point(x, y, z, color, size = 1, alpha = 0.7) {
  return { x, y, z, color, size, alpha };
}

function buildLidarScene() {
  const random = mulberry32(0x51a7c0de);
  const points = [];
  const poles = [];
  const conductors = [];

  // A sampled ground surface with a lightly cleared utility corridor.
  for (let z = 0; z < LOOP_DEPTH; z += 1.8) {
    for (let x = -48; x <= 48; x += 1.8) {
      if (random() < 0.1) continue;
      const jitterX = x + (random() - 0.5) * 1.5;
      const jitterZ = z + (random() - 0.5) * 1.5;
      const corridor = Math.abs(jitterX) < 9;
      points.push(
        point(
          jitterX,
          terrainHeight(jitterX, jitterZ) + random() * 0.12,
          jitterZ,
          corridor ? COLORS.corridor : COLORS.ground,
          corridor ? 1.55 : 1.2,
          corridor ? 0.9 : 0.7,
        ),
      );
    }
  }

  // Denser road returns make the scan direction immediately legible.
  for (let z = 0; z < LOOP_DEPTH; z += 1.05) {
    for (const x of [-8, -7.7, 0, 7.7, 8]) {
      points.push(point(x, terrainHeight(x, z) + 0.08, z, COLORS.corridor, 1.7, 0.96));
    }
    if (Math.floor(z / 7) % 2 === 0) {
      for (let x = -7; x <= 7; x += 1.1) {
        points.push(point(x, terrainHeight(x, z), z, COLORS.groundFar, 0.9, 0.46));
      }
    }
  }

  // Low vegetation outside the clearance envelope.
  for (let cluster = 0; cluster < 96; cluster += 1) {
    const side = random() > 0.5 ? 1 : -1;
    const centerX = side * (12 + random() * 33);
    const centerZ = random() * LOOP_DEPTH;
    const radius = 1.2 + random() * 4.2;
    const height = 1.5 + random() * 7.5;
    const returns = 18 + Math.floor(random() * 34);
    for (let index = 0; index < returns; index += 1) {
      const angle = random() * TAU;
      const spread = Math.sqrt(random()) * radius;
      const x = centerX + Math.cos(angle) * spread;
      const z = centerZ + Math.sin(angle) * spread;
      const y = terrainHeight(x, z) + Math.pow(random(), 0.62) * height;
      points.push(point(x, y, z, COLORS.vegetation, 1.2 + random() * 0.65, 0.58 + random() * 0.32));
    }
  }

  // Recognisable trees: dense rounded crowns over clearly separated trunks.
  for (let treeIndex = 0; treeIndex < 26; treeIndex += 1) {
    const side = random() > 0.5 ? 1 : -1;
    const centerX = side * (17 + random() * 27);
    const centerZ = 8 + random() * (LOOP_DEPTH - 16);
    const base = terrainHeight(centerX, centerZ);
    const trunkHeight = 5.5 + random() * 5;
    const crownRadius = 2.3 + random() * 2.2;
    for (let y = 0; y < trunkHeight; y += 0.34) {
      for (let sample = 0; sample < 5; sample += 1) {
        const angle = sample * (TAU / 5);
        points.push(point(centerX + Math.cos(angle) * 0.2, base + y, centerZ + Math.sin(angle) * 0.2, COLORS.infrastructure, 1.25, 0.78));
      }
    }
    for (let sample = 0; sample < 92; sample += 1) {
      const azimuth = random() * TAU;
      const elevation = Math.acos(2 * random() - 1);
      const radius = crownRadius * Math.cbrt(random());
      const x = centerX + Math.sin(elevation) * Math.cos(azimuth) * radius;
      const y = base + trunkHeight + Math.cos(elevation) * radius * 0.82;
      const z = centerZ + Math.sin(elevation) * Math.sin(azimuth) * radius;
      points.push(point(x, y, z, COLORS.vegetation, 1.45, 0.86));
    }
  }

  // Sparse point-cloud building shells give the corridor an engineered context.
  const buildings = [
    { x: 31, z: 48, width: 16, depth: 18, height: 10 },
    { x: -34, z: 112, width: 18, depth: 22, height: 13 },
    { x: 35, z: 184, width: 15, depth: 19, height: 9 },
    { x: -32, z: 238, width: 20, depth: 17, height: 12 },
  ];
  for (const building of buildings) {
    const xMin = building.x - building.width / 2;
    const xMax = building.x + building.width / 2;
    const zMin = building.z - building.depth / 2;
    const zMax = building.z + building.depth / 2;
    const base = terrainHeight(building.x, building.z);
    for (let y = 0; y <= building.height; y += 0.72) {
      for (let x = xMin; x <= xMax; x += 0.72) {
        points.push(point(x, base + y, zMin, COLORS.building, 1.25, 0.75));
        points.push(point(x, base + y, zMax, COLORS.building, 1.25, 0.75));
      }
      for (let z = zMin; z <= zMax; z += 0.72) {
        points.push(point(xMin, base + y, z, COLORS.building, 1.25, 0.75));
        points.push(point(xMax, base + y, z, COLORS.building, 1.25, 0.75));
      }
    }
    for (let x = xMin; x <= xMax; x += 0.85) {
      for (let z = zMin; z <= zMax; z += 0.85) {
        if (Math.floor((x + z) * 2) % 3 === 0) points.push(point(x, base + building.height, z, COLORS.building, 1.2, 0.72));
      }
    }
  }

  // Distribution poles, crossarms and insulators.
  let poleNumber = 0;
  for (let z = 12; z < LOOP_DEPTH; z += POLE_SPACING) {
    const x = -11.5 + Math.sin(z * 0.045) * 0.5;
    const base = terrainHeight(x, z);
    poles.push({ x, z, base, number: poleNumber + 1, hasTransformer: poleNumber % 2 === 0 });
    for (let y = 0; y <= POLE_HEIGHT; y += 0.32) {
      for (let sample = 0; sample < 8; sample += 1) {
        const angle = sample * (TAU / 8) + z;
        points.push(point(x + Math.cos(angle) * 0.3, base + y, z + Math.sin(angle) * 0.3, COLORS.infrastructure, 1.65, 0.96));
      }
    }
    for (let arm = -4.5; arm <= 4.5; arm += 0.28) {
      points.push(point(x + arm, base + POLE_HEIGHT - 1.35, z, COLORS.infrastructure, 1.65, 0.96));
      points.push(point(x + arm, base + POLE_HEIGHT - 2.15, z, COLORS.infrastructure, 1.35, 0.88));
    }
    // Diagonal steel braces make the crossarm silhouette read clearly.
    for (const direction of [-1, 1]) {
      for (let step = 0; step <= 18; step += 1) {
        const t = step / 18;
        points.push(point(x + direction * 3.5 * t, base + POLE_HEIGHT - 3.8 + 2.45 * t, z, COLORS.infrastructure, 1.35, 0.9));
      }
    }
    for (const offset of [-3.2, 0, 3.2]) {
      for (let drop = 0; drop < 1.05; drop += 0.18) {
        const flare = 0.13 + drop * 0.09;
        points.push(point(x + offset - flare, base + POLE_HEIGHT - 1.4 - drop, z, COLORS.highlight, 1.65, 1));
        points.push(point(x + offset + flare, base + POLE_HEIGHT - 1.4 - drop, z, COLORS.highlight, 1.65, 1));
      }
    }
    // Every second pole carries a cylindrical transformer and a small service box.
    if (poleNumber % 2 === 0) {
      const equipmentY = base + 10.8;
      for (let y = 0; y <= 3.2; y += 0.3) {
        for (let sample = 0; sample < 12; sample += 1) {
          const angle = sample * (TAU / 12);
          points.push(point(x + 0.75 + Math.cos(angle) * 0.86, equipmentY + y, z + Math.sin(angle) * 0.86, COLORS.equipment, 1.7, 0.96));
        }
      }
      for (let boxY = 5.2; boxY <= 7.4; boxY += 0.28) {
        for (const side of [-0.62, 0.62]) {
          points.push(point(x + side, base + boxY, z + 0.5, COLORS.equipment, 1.45, 0.9));
        }
      }
    }
    poleNumber += 1;
  }

  // Three catenary conductor strands between successive poles.
  for (let poleIndex = 0; poleIndex < poles.length - 1; poleIndex += 1) {
    const start = poles[poleIndex];
    const end = poles[poleIndex + 1];
    for (const offset of [-3.2, 0, 3.2]) {
      for (let step = 0; step <= 48; step += 1) {
        const t = step / 48;
        const sag = Math.sin(Math.PI * t) * 2.15;
        conductors.push(
          point(
            start.x + (end.x - start.x) * t + offset,
            start.base + (end.base - start.base) * t + POLE_HEIGHT - 2.2 - sag,
            start.z + (end.z - start.z) * t,
            COLORS.infrastructure,
            1.05,
            0.82,
          ),
        );
      }
    }
  }

  return { points, poles, conductors };
}

function wrappedDepth(z, travel) {
  return ((z - travel) % LOOP_DEPTH + LOOP_DEPTH) % LOOP_DEPTH;
}

function smoothStep(value) {
  const t = Math.max(0, Math.min(1, value));
  return t * t * (3 - 2 * t);
}

function cameraInspectionState(time, poles) {
  const cycleIndex = Math.floor(time / INSPECTION_CYCLE_MS);
  const phase = time % INSPECTION_CYCLE_MS;
  const targetTravel = cycleIndex * POLE_SPACING - 22;
  let travel;
  if (phase < 6000) {
    travel = targetTravel - 21 + smoothStep(phase / 6000) * 21;
  } else if (phase < 12500) {
    travel = targetTravel;
  } else {
    travel = targetTravel + smoothStep((phase - 12500) / 5500) * 21;
  }
  const fadeIn = smoothStep((phase - 4700) / 1300);
  const fadeOut = 1 - smoothStep((phase - 13500) / 1400);
  return {
    travel,
    pole: poles[cycleIndex % poles.length],
    active: phase >= 4700 && phase <= 14900,
    locked: phase >= 6000 && phase < 12500,
    progress: Math.max(0, Math.min(fadeIn, fadeOut)),
    phase,
  };
}

// On wide screens the sign-in card sits on the right, so the corridor's vanishing point moves left
// and overlay panels stay clear of the card.
let viewFocus = 0.5;
function cardClearX(width) {
  return width >= 1100 ? width - Math.min(150, Math.max(48, width * 0.07)) - 440 - 28 : width - 28;
}

function projectPoint(source, travel, width, height, pointer) {
  const depth = wrappedDepth(source.z, travel);
  if (depth < NEAR_DEPTH || depth > LOOP_DEPTH - 2) return null;
  const focal = Math.min(width, height) * 1.08;
  const horizon = height * (0.39 + pointer.y * 0.02);
  const parallax = pointer.x * Math.min(4.5, depth * 0.025);
  const scale = focal / depth;
  const x = width * viewFocus + (source.x - parallax) * scale;
  const y = horizon + (CAMERA_HEIGHT - source.y) * scale;
  if (x < -20 || x > width + 20 || y < -20 || y > height + 28) return null;
  return { x, y, depth, scale };
}

function rgba(rgb, alpha) {
  return `rgba(${rgb}, ${Math.max(0, Math.min(1, alpha))})`;
}

function drawBackdrop(context, width, height) {
  const gradient = context.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "#082331");
  gradient.addColorStop(0.42, "#061923");
  gradient.addColorStop(1, "#020b10");
  context.fillStyle = gradient;
  context.fillRect(0, 0, width, height);

  const glow = context.createRadialGradient(width * viewFocus, height * 0.39, 0, width * viewFocus, height * 0.39, width * 0.58);
  glow.addColorStop(0, "rgba(47, 184, 216, 0.3)");
  glow.addColorStop(0.46, "rgba(16, 91, 116, 0.13)");
  glow.addColorStop(1, "rgba(0, 0, 0, 0)");
  context.fillStyle = glow;
  context.fillRect(0, 0, width, height);
}

function drawPerspectiveGrid(context, travel, width, height, pointer) {
  context.save();
  context.lineWidth = 1;
  context.strokeStyle = "rgba(87, 218, 235, 0.16)";
  const nearZ = (travel + NEAR_DEPTH + 1) % LOOP_DEPTH;
  const farZ = (travel + LOOP_DEPTH - 3) % LOOP_DEPTH;
  for (const x of [-32, -24, -16, -8, 0, 8, 16, 24, 32]) {
    const near = projectPoint({ x, y: terrainHeight(x, nearZ), z: nearZ }, travel, width, height, pointer);
    const far = projectPoint({ x, y: terrainHeight(x, farZ), z: farZ }, travel, width, height, pointer);
    if (!near || !far) continue;
    context.beginPath();
    context.moveTo(near.x, near.y);
    context.lineTo(far.x, far.y);
    context.stroke();
  }
  for (let depth = 20; depth < 190; depth += 18) {
    const z = (travel + depth) % LOOP_DEPTH;
    const left = projectPoint({ x: -38, y: terrainHeight(-38, z), z }, travel, width, height, pointer);
    const right = projectPoint({ x: 38, y: terrainHeight(38, z), z }, travel, width, height, pointer);
    if (!left || !right) continue;
    context.globalAlpha = Math.max(0.18, 1 - depth / 210);
    context.beginPath();
    context.moveTo(left.x, left.y);
    context.lineTo(right.x, right.y);
    context.stroke();
  }
  context.restore();
}

function drawPointCloud(context, sourcePoints, travel, width, height, pointer, scanDepth, density) {
  for (let index = 0; index < sourcePoints.length; index += density) {
    const source = sourcePoints[index];
    const projected = projectPoint(source, travel, width, height, pointer);
    if (!projected) continue;
    const scanDistance = Math.abs(projected.depth - scanDepth);
    const highlighted = scanDistance < 2.3;
    const depthFade = Math.min(1, (LOOP_DEPTH - projected.depth) / 125);
    const nearFade = Math.min(1, (projected.depth - NEAR_DEPTH) / 13);
    const alpha = source.alpha * depthFade * nearFade * (highlighted ? 1.45 : 1.15);
    const size = Math.max(0.9, Math.min(3.8, source.size * projected.scale * 0.043));
    context.fillStyle = rgba(highlighted ? COLORS.highlight : source.color, alpha);
    context.fillRect(projected.x, projected.y, size, size);
  }
}

function drawInfrastructure(context, conductors, travel, width, height, pointer, scanDepth) {
  context.save();
  context.globalCompositeOperation = "lighter";
  drawPointCloud(context, conductors, travel, width, height, pointer, scanDepth, 1);
  context.restore();
}

function drawPoleGuides(context, poles, travel, width, height, pointer) {
  context.save();
  context.globalCompositeOperation = "lighter";
  context.strokeStyle = "rgba(171, 245, 251, 0.68)";
  context.shadowColor = "rgba(65, 220, 248, 0.56)";
  context.shadowBlur = 12;
  for (const pole of poles) {
    const base = projectPoint({ x: pole.x, y: pole.base, z: pole.z }, travel, width, height, pointer);
    const top = projectPoint({ x: pole.x, y: pole.base + POLE_HEIGHT, z: pole.z }, travel, width, height, pointer);
    const left = projectPoint({ x: pole.x - 4.5, y: pole.base + POLE_HEIGHT - 1.35, z: pole.z }, travel, width, height, pointer);
    const right = projectPoint({ x: pole.x + 4.5, y: pole.base + POLE_HEIGHT - 1.35, z: pole.z }, travel, width, height, pointer);
    if (!base || !top || !left || !right) continue;
    const alpha = Math.min(0.8, Math.max(0.16, (150 - top.depth) / 130));
    context.globalAlpha = alpha;
    context.lineWidth = Math.max(1.35, Math.min(4.5, top.scale * 0.075));
    context.beginPath();
    context.moveTo(base.x, base.y);
    context.lineTo(top.x, top.y);
    context.moveTo(left.x, left.y);
    context.lineTo(right.x, right.y);
    context.stroke();
  }
  context.restore();
}

// Airborne scanner: a glowing sensor head sweeps a laser swath across the ground at the scan line.
function drawLaserSwath(context, travel, width, height, pointer, scanDepth, time) {
  const z = (travel + scanDepth) % LOOP_DEPTH;
  // The sensor flies ahead of the scan line; it is pinned high in the frame so it is always visible.
  const sensorZ = (travel + Math.max(scanDepth, 30) + 30) % LOOP_DEPTH;
  const anchor = projectPoint({ x: Math.sin(time * 0.00031) * 5, y: 0, z: sensorZ }, travel, width, height, pointer);
  if (!anchor) return;
  const sensor = { x: anchor.x, y: Math.max(52, height * 0.14) + Math.sin(time * 0.0011) * 6 };
  const sweep = Math.sin(time * 0.0042);
  context.save();
  context.globalCompositeOperation = "lighter";

  // Faint fan of returns.
  context.lineWidth = 1;
  for (let x = -40; x <= 40; x += 5) {
    const hit = projectPoint({ x, y: terrainHeight(x, z) + 0.1, z }, travel, width, height, pointer);
    if (!hit) continue;
    const near = 1 - Math.min(1, Math.abs(x / 40 - sweep) * 2.2);
    context.strokeStyle = `rgba(94, 232, 255, ${0.035 + near * 0.16})`;
    context.beginPath();
    context.moveTo(sensor.x, sensor.y);
    context.lineTo(hit.x, hit.y);
    context.stroke();
  }

  // The live beam and its ground footprint.
  const beamX = sweep * 40;
  const beamHit = projectPoint({ x: beamX, y: terrainHeight(beamX, z) + 0.1, z }, travel, width, height, pointer);
  if (beamHit) {
    const beam = context.createLinearGradient(sensor.x, sensor.y, beamHit.x, beamHit.y);
    beam.addColorStop(0, "rgba(160, 248, 255, 0.85)");
    beam.addColorStop(1, "rgba(94, 232, 255, 0.25)");
    context.strokeStyle = beam;
    context.lineWidth = 1.6;
    context.shadowColor = "rgba(94, 232, 255, 0.9)";
    context.shadowBlur = 12;
    context.beginPath();
    context.moveTo(sensor.x, sensor.y);
    context.lineTo(beamHit.x, beamHit.y);
    context.stroke();
    const footprint = context.createRadialGradient(beamHit.x, beamHit.y, 0, beamHit.x, beamHit.y, 16);
    footprint.addColorStop(0, "rgba(190, 252, 255, 0.85)");
    footprint.addColorStop(1, "rgba(94, 232, 255, 0)");
    context.shadowBlur = 0;
    context.fillStyle = footprint;
    context.fillRect(beamHit.x - 16, beamHit.y - 16, 32, 32);
  }

  // Sensor head with a pulsing halo.
  const pulse = 0.5 + 0.5 * Math.sin(time * 0.006);
  const halo = context.createRadialGradient(sensor.x, sensor.y, 0, sensor.x, sensor.y, 18 + pulse * 8);
  halo.addColorStop(0, "rgba(200, 252, 255, 0.95)");
  halo.addColorStop(0.25, "rgba(94, 232, 255, 0.5)");
  halo.addColorStop(1, "rgba(94, 232, 255, 0)");
  context.fillStyle = halo;
  context.beginPath();
  context.arc(sensor.x, sensor.y, 18 + pulse * 8, 0, TAU);
  context.fill();
  context.strokeStyle = "rgba(170, 246, 255, 0.7)";
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(sensor.x - 14, sensor.y);
  context.lineTo(sensor.x - 5, sensor.y);
  context.moveTo(sensor.x + 5, sensor.y);
  context.lineTo(sensor.x + 14, sensor.y);
  context.stroke();
  context.restore();
}

function drawPoleMeasurement(context, inspection, width, height, pointer) {
  if (!inspection.active || !inspection.pole || inspection.progress <= 0) return;
  const { pole, travel, progress, locked, phase } = inspection;
  const basePoint = { x: pole.x, y: pole.base, z: pole.z };
  const topPoint = { x: pole.x, y: pole.base + POLE_HEIGHT, z: pole.z };
  const dimensionBase = projectPoint({ ...basePoint, x: pole.x - 5.2 }, travel, width, height, pointer);
  const dimensionTop = projectPoint({ ...topPoint, x: pole.x - 5.2 }, travel, width, height, pointer);
  const poleBase = projectPoint(basePoint, travel, width, height, pointer);
  const poleTop = projectPoint(topPoint, travel, width, height, pointer);
  const crossarm = projectPoint({ x: pole.x, y: pole.base + POLE_HEIGHT - 1.35, z: pole.z }, travel, width, height, pointer);
  const transformer = pole.hasTransformer
    ? projectPoint({ x: pole.x + 0.75, y: pole.base + 12.4, z: pole.z }, travel, width, height, pointer)
    : null;
  if (!dimensionBase || !dimensionTop || !poleBase || !poleTop) return;

  const measuredHeight = topPoint.y - basePoint.y;
  const calculationProgress = locked ? 1 : smoothStep(Math.min(1, (phase - 4700) / 1300));
  const displayedHeight = measuredHeight * calculationProgress;
  context.save();
  context.globalAlpha = progress;
  context.globalCompositeOperation = "lighter";
  context.strokeStyle = locked ? "rgba(98, 244, 184, 0.94)" : "rgba(108, 232, 250, 0.8)";
  context.fillStyle = locked ? "rgba(98, 244, 184, 0.96)" : "rgba(108, 232, 250, 0.92)";
  context.shadowColor = locked ? "rgba(68, 239, 169, 0.75)" : "rgba(65, 224, 255, 0.7)";
  context.shadowBlur = 10;
  context.lineWidth = 1.4;
  context.setLineDash([5, 4]);
  context.beginPath();
  context.moveTo(dimensionTop.x, dimensionTop.y);
  context.lineTo(dimensionBase.x, dimensionBase.y);
  context.moveTo(dimensionTop.x - 7, dimensionTop.y);
  context.lineTo(poleTop.x + 4, poleTop.y);
  context.moveTo(dimensionBase.x - 7, dimensionBase.y);
  context.lineTo(poleBase.x + 4, poleBase.y);
  context.stroke();
  context.setLineDash([]);
  for (const marker of [dimensionTop, dimensionBase, crossarm, transformer].filter(Boolean)) {
    context.beginPath();
    context.arc(marker.x, marker.y, marker === crossarm || marker === transformer ? 3.2 : 4.3, 0, TAU);
    context.fill();
  }
  context.restore();

  if (width < 860) return;
  const panelWidth = 262;
  const panelHeight = pole.hasTransformer ? 190 : 172;
  // Prefer the left of the pole; flip to its right when the left edge (status panels) is too close.
  const leftOfPole = poleTop.x - panelWidth - 62;
  const panelX = Math.min(cardClearX(width) - panelWidth, leftOfPole >= 280 ? leftOfPole : poleTop.x + 62);
  const panelY = Math.max(224, Math.min(height - panelHeight - 90, poleTop.y - 18));
  context.save();
  context.globalAlpha = progress;
  drawPanel(context, panelX, panelY, panelWidth, panelHeight);
  context.fillStyle = locked ? "rgba(98, 247, 186, 1)" : "rgba(140, 238, 252, 1)";
  context.font = "800 12px Inter, system-ui, sans-serif";
  context.fillText(locked ? "AUTO POLE ANALYSIS · LOCKED" : "AUTO POLE ANALYSIS · SCANNING", panelX + 16, panelY + 26);
  context.strokeStyle = "rgba(110, 230, 248, 0.28)";
  context.beginPath();
  context.moveTo(panelX + 16, panelY + 38);
  context.lineTo(panelX + panelWidth - 16, panelY + 38);
  context.stroke();
  context.font = "600 11px ui-monospace, SFMono-Regular, Consolas, monospace";
  const rows = [
    ["ASSET", `POLE ${String(pole.number).padStart(2, "0")}`],
    ["BASE Z", `${pole.base.toFixed(2)} m`],
    ["TOP Z", `${topPoint.y.toFixed(2)} m`],
    ["HEIGHT", `${displayedHeight.toFixed(2)} m`],
    ["FEATURES", pole.hasTransformer ? "5 DETECTED" : "4 DETECTED"],
  ];
  rows.forEach(([label, value], index) => {
    const rowY = panelY + 60 + index * 21;
    context.fillStyle = "rgba(150, 226, 240, 0.9)";
    context.textAlign = "left";
    context.fillText(label, panelX + 16, rowY);
    context.fillStyle = index === 3 ? "rgba(98, 247, 186, 1)" : "rgba(240, 253, 255, 1)";
    context.textAlign = "right";
    context.fillText(value, panelX + panelWidth - 16, rowY);
  });
  context.textAlign = "left";
  context.fillStyle = "rgba(160, 232, 245, 0.85)";
  context.font = "700 10px Inter, system-ui, sans-serif";
  context.fillText(
    pole.hasTransformer ? "BASE · TOP · ARM · INSULATOR · TX" : "BASE · TOP · ARM · INSULATOR",
    panelX + 16,
    panelY + panelHeight - 15,
  );
  context.restore();
}

function drawCornerFrame(context, width, height) {
  const inset = 22;
  const length = 34;
  context.save();
  context.strokeStyle = "rgba(113, 227, 243, 0.34)";
  context.lineWidth = 1;
  for (const [x, y, sx, sy] of [
    [inset, inset, 1, 1],
    [width - inset, inset, -1, 1],
    [inset, height - inset, 1, -1],
    [width - inset, height - inset, -1, -1],
  ]) {
    context.beginPath();
    context.moveTo(x + sx * length, y);
    context.lineTo(x, y);
    context.lineTo(x, y + sy * length);
    context.stroke();
  }
  context.restore();
}

function drawPanel(context, x, y, panelWidth, panelHeight) {
  context.save();
  context.shadowColor = "rgba(0, 0, 0, 0.55)";
  context.shadowBlur = 18;
  context.fillStyle = "rgba(3, 18, 27, 0.86)";
  context.beginPath();
  context.roundRect(x, y, panelWidth, panelHeight, 10);
  context.fill();
  context.restore();
  context.strokeStyle = "rgba(110, 230, 248, 0.42)";
  context.lineWidth = 1;
  context.stroke();
  context.fillStyle = "rgba(94, 230, 245, 0.75)";
  context.fillRect(x + 14, y, 36, 2);
}

// Text on the HUD gets a soft dark halo so it stays legible over bright returns.
function hudText(context, text, x, y) {
  context.save();
  context.shadowColor = "rgba(0, 0, 0, 0.85)";
  context.shadowBlur = 4;
  context.fillText(text, x, y);
  context.restore();
}

function drawViewerChrome(context, width, height, scanDepth, time, pointCount, inspection) {
  if (width < 720) return;
  context.save();
  drawCornerFrame(context, width, height);

  context.font = "800 13px Inter, system-ui, sans-serif";
  context.fillStyle = "rgba(225, 251, 255, 0.96)";
  hudText(context, "LIDAR CORRIDOR SCAN", 30, 110);
  context.font = "600 11px ui-monospace, SFMono-Regular, Consolas, monospace";
  context.fillStyle = "rgba(140, 228, 242, 0.85)";
  hudText(context, "UTILITY ASSET CLASSIFICATION / QC", 30, 126);

  // Live scan status.
  drawPanel(context, 28, 138, 236, 82);
  const statusColor = inspection.locked ? "255, 192, 89" : "76, 239, 181";
  context.fillStyle = `rgba(${statusColor}, 1)`;
  context.shadowColor = `rgba(${statusColor}, 0.9)`;
  context.shadowBlur = 8;
  context.beginPath();
  context.arc(46, 160, 4.5, 0, TAU);
  context.fill();
  context.shadowBlur = 0;
  context.font = "800 12px Inter, system-ui, sans-serif";
  context.fillStyle = "rgba(235, 252, 255, 1)";
  context.fillText(inspection.locked ? "POLE MEASUREMENT LOCK" : "LIVE POINT CLOUD", 58, 164);
  context.font = "600 11px ui-monospace, SFMono-Regular, Consolas, monospace";
  context.fillStyle = "rgba(170, 236, 247, 0.92)";
  context.fillText(`FRAME  ${String(Math.floor(time / 33) % 10000).padStart(4, "0")}`, 44, 187);
  context.fillText(`SCAN   ${scanDepth.toFixed(1).padStart(5, "0")} m`, 44, 205);

  // Point-cloud telemetry stacks under the scan status, on the side away from the sign-in card.
  if (width >= 1080 && height >= 560) {
    const panelX = 28;
    const top = 232;
    drawPanel(context, panelX, top, 236, 164);
    context.font = "800 12px Inter, system-ui, sans-serif";
    context.fillStyle = "rgba(235, 252, 255, 1)";
    context.fillText("VIEWER TELEMETRY", panelX + 16, top + 26);
    context.strokeStyle = "rgba(110, 230, 248, 0.28)";
    context.beginPath();
    context.moveTo(panelX + 16, top + 38);
    context.lineTo(panelX + 220, top + 38);
    context.stroke();
    context.font = "600 11px ui-monospace, SFMono-Regular, Consolas, monospace";
    context.fillStyle = "rgba(150, 226, 240, 0.9)";
    const rows = [
      ["VISIBLE RETURNS", pointCount.toLocaleString("en-US")],
      ["DISPLAY", "RGB / HEIGHT"],
      ["DENSITY", "HIGH"],
      ["AUTO HEIGHT", inspection.locked ? `${POLE_HEIGHT.toFixed(2)} m` : "SEARCHING"],
      ["SYNC", "4 VIEWS"],
    ];
    rows.forEach(([label, value], index) => {
      const rowY = top + 60 + index * 21;
      context.fillText(label, panelX + 16, rowY);
      context.textAlign = "right";
      context.fillStyle = index === 4 || (index === 3 && inspection.locked) ? "rgba(96, 245, 190, 1)" : "rgba(240, 253, 255, 1)";
      context.fillText(value, panelX + 220, rowY);
      context.textAlign = "left";
      context.fillStyle = "rgba(150, 226, 240, 0.9)";
    });
  }

  // View-mode rail mirrors the engineering evidence viewer without becoming interactive.
  const modes = ["PLAN", "PROFILE", "CROSS", "3D"];
  let modeX = 28;
  const modeY = height - 62;
  context.font = "800 11px Inter, system-ui, sans-serif";
  for (const mode of modes) {
    const tabWidth = mode === "PROFILE" ? 84 : 60;
    context.fillStyle = mode === "3D" ? "rgba(40, 190, 228, 0.55)" : "rgba(3, 18, 27, 0.84)";
    context.strokeStyle = mode === "3D" ? "rgba(140, 244, 255, 0.95)" : "rgba(110, 230, 248, 0.4)";
    context.beginPath();
    context.roundRect(modeX, modeY - 4, tabWidth, 31, 7);
    context.fill();
    context.stroke();
    context.fillStyle = mode === "3D" ? "rgba(255, 255, 255, 1)" : "rgba(180, 238, 248, 0.92)";
    context.fillText(mode, modeX + 12, modeY + 16);
    modeX += tabWidth + 8;
  }
  context.font = "600 11px ui-monospace, SFMono-Regular, Consolas, monospace";
  context.textAlign = "right";
  context.fillStyle = "rgba(170, 236, 247, 0.85)";
  hudText(context, `EVIDENCE ${String(Math.floor(scanDepth * 47 + time * 0.012) % 9999).padStart(4, "0")}  •  CRS VERIFIED`, width - 30, height - 44);
  context.restore();
}

// Entrance after sign-in: the camera accelerates down the corridor while light streaks
// stream out of the vanishing point, ending in a soft cyan flash.
const WARP_STREAKS = (() => {
  const random = mulberry32(0x7e57a11);
  return Array.from({ length: 140 }, () => ({ angle: random() * TAU, offset: random(), speed: 0.6 + random() * 0.9, width: 0.6 + random() * 1.6 }));
})();

function drawWarp(context, width, height, warp) {
  if (warp <= 0) return;
  const cx = width * viewFocus;
  const cy = height * 0.39;
  const reach = Math.hypot(Math.max(cx, width - cx), Math.max(cy, height - cy));
  context.save();
  context.globalCompositeOperation = "lighter";
  context.lineCap = "round";
  for (const streak of WARP_STREAKS) {
    const t = (streak.offset + warp * streak.speed * 1.6) % 1;
    const start = Math.pow(t, 2) * reach;
    const length = 12 + warp * warp * 260 * streak.speed;
    const dx = Math.cos(streak.angle);
    const dy = Math.sin(streak.angle);
    context.strokeStyle = `rgba(150, 240, 255, ${Math.min(0.75, warp * 0.9) * (0.35 + t * 0.65)})`;
    context.lineWidth = streak.width * (0.6 + t * 1.4);
    context.beginPath();
    context.moveTo(cx + dx * start, cy + dy * start);
    context.lineTo(cx + dx * (start + length), cy + dy * (start + length));
    context.stroke();
  }
  const core = context.createRadialGradient(cx, cy, 0, cx, cy, reach * (0.15 + warp * 0.5));
  core.addColorStop(0, `rgba(200, 250, 255, ${0.5 * warp})`);
  core.addColorStop(1, "rgba(94, 230, 245, 0)");
  context.fillStyle = core;
  context.fillRect(0, 0, width, height);
  context.restore();
  const flash = smoothStep((warp - 0.82) / 0.18);
  if (flash > 0) {
    context.fillStyle = `rgba(214, 250, 255, ${flash * 0.9})`;
    context.fillRect(0, 0, width, height);
  }
}

export function startLidarLoginBackground(canvas) {
  if (!(canvas instanceof HTMLCanvasElement)) return () => {};

  const context = canvas.getContext("2d", { alpha: false });
  if (!context) return () => {};

  const scene = buildLidarScene();
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  const pointer = { x: 0, y: 0 };
  let width = 1;
  let height = 1;
  let frameId = 0;
  let lastFrame = 0;
  let stopped = false;
  let warpStart = null;

  function resize() {
    const bounds = canvas.getBoundingClientRect();
    width = Math.max(1, Math.round(bounds.width));
    height = Math.max(1, Math.round(bounds.height));
    viewFocus = width >= 1100 ? 0.4 : 0.5;
    const dpr = Math.min(window.devicePixelRatio || 1, DPR_CAP);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function render(time = 0) {
    const sceneTime = reducedMotion ? 8000 : time;
    const inspection = cameraInspectionState(sceneTime, scene.poles);
    const warp = warpStart === null ? 0 : Math.min(1, Math.max(0, (time - warpStart) / WARP_MS));
    const travel = inspection.travel + Math.pow(warp, 3) * 230;
    const scanDepth = inspection.active
      ? wrappedDepth(inspection.pole.z, travel)
      : 22 + ((sceneTime * 0.047) % 150);
    const density = width < 680 ? 2 : 1;
    drawBackdrop(context, width, height);
    drawPerspectiveGrid(context, travel, width, height, pointer);
    drawPointCloud(context, scene.points, travel, width, height, pointer, scanDepth, density);
    drawInfrastructure(context, scene.conductors, travel, width, height, pointer, scanDepth);
    drawPoleGuides(context, scene.poles, travel, width, height, pointer);
    drawLaserSwath(context, travel, width, height, pointer, scanDepth, sceneTime);
    // The HUD dims away as the entrance starts.
    context.save();
    context.globalAlpha = 1 - smoothStep(warp * 3);
    if (warp < 0.34) {
      drawPoleMeasurement(context, inspection, width, height, pointer);
      drawViewerChrome(context, width, height, scanDepth, sceneTime, scene.points.length + scene.conductors.length, inspection);
    }
    context.restore();
    drawWarp(context, width, height, warp);
  }

  function animate(time) {
    if (stopped) return;
    if (time - lastFrame >= (warpStart === null ? TARGET_FRAME_MS : 0)) {
      render(time);
      lastFrame = time;
    }
    frameId = requestAnimationFrame(animate);
  }

  function handlePointer(event) {
    pointer.x = (event.clientX / Math.max(1, window.innerWidth) - 0.5) * 2;
    pointer.y = (event.clientY / Math.max(1, window.innerHeight) - 0.5) * 2;
  }

  resize();
  render(0);
  const resizeObserver = new ResizeObserver(() => {
    resize();
    if (reducedMotion) render(0);
  });
  resizeObserver.observe(canvas);

  if (reducedMotion) {
    canvas.dataset.ready = "static";
  } else {
    window.addEventListener("pointermove", handlePointer, { passive: true });
    canvas.dataset.ready = "animated";
    frameId = requestAnimationFrame(animate);
  }

  function stop() {
    stopped = true;
    cancelAnimationFrame(frameId);
    resizeObserver.disconnect();
    window.removeEventListener("pointermove", handlePointer);
    canvas.removeAttribute("data-ready");
    context.clearRect(0, 0, width, height);
  }
  // Starts the sign-in entrance; resolves when the warp has finished (at once with reduced motion).
  stop.enter = () => new Promise(resolve => {
    if (reducedMotion || stopped) { resolve(); return; }
    warpStart = performance.now();
    setTimeout(resolve, WARP_MS);
  });
  // Signed out again mid-entrance: return to the normal fly-through.
  stop.leave = () => { warpStart = null; };
  return stop;
}
