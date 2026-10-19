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

// Light ("daylight") palette: points are deep teal / green / slate so they read on the pale sky.
const COLORS = {
  ground: "28, 118, 148",
  groundFar: "84, 150, 176",
  vegetation: "22, 138, 96",
  corridor: "6, 122, 166",
  infrastructure: "18, 58, 84",
  equipment: "204, 122, 12",
  building: "62, 112, 142",
  highlight: "0, 156, 210",
  scan: "0, 140, 190",
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

  // A sampled ground surface with a lightly cleared utility corridor (dense enough to read on the light sky).
  for (let z = 0; z < LOOP_DEPTH; z += 1.3) {
    for (let x = -50; x <= 50; x += 1.3) {
      if (random() < 0.08) continue;
      const jitterX = x + (random() - 0.5) * 1.1;
      const jitterZ = z + (random() - 0.5) * 1.1;
      const corridor = Math.abs(jitterX) < 9;
      points.push(point(jitterX, terrainHeight(jitterX, jitterZ) + random() * 0.12, jitterZ,
        corridor ? COLORS.corridor : COLORS.ground, corridor ? 1.7 : 1.35, corridor ? 0.95 : 0.78));
    }
  }

  // Road edges, centre line and kerbs: dense returns make the scan direction immediately legible.
  for (let z = 0; z < LOOP_DEPTH; z += 0.7) {
    for (const x of [-8.3, -8, -7.7, -0.15, 0.15, 7.7, 8, 8.3]) {
      points.push(point(x, terrainHeight(x, z) + 0.08, z, COLORS.corridor, 1.9, 1));
    }
    for (const x of [-9.4, 9.4]) points.push(point(x, terrainHeight(x, z) + 0.32, z, COLORS.infrastructure, 1.5, 0.8));
    if (Math.floor(z / 7) % 2 === 0) {
      for (let x = -7; x <= 7; x += 0.9) points.push(point(x, terrainHeight(x, z), z, COLORS.groundFar, 1.05, 0.55));
    }
  }

  // Low vegetation outside the clearance envelope.
  for (let cluster = 0; cluster < 150; cluster += 1) {
    const side = random() > 0.5 ? 1 : -1;
    const centerX = side * (12 + random() * 34);
    const centerZ = random() * LOOP_DEPTH;
    const radius = 1.2 + random() * 4.2;
    const height = 1.5 + random() * 7.5;
    const returns = 30 + Math.floor(random() * 46);
    for (let index = 0; index < returns; index += 1) {
      const angle = random() * TAU;
      const spread = Math.sqrt(random()) * radius;
      const x = centerX + Math.cos(angle) * spread;
      const z = centerZ + Math.sin(angle) * spread;
      const y = terrainHeight(x, z) + Math.pow(random(), 0.62) * height;
      points.push(point(x, y, z, COLORS.vegetation, 1.35 + random() * 0.7, 0.66 + random() * 0.3));
    }
  }

  // Recognisable trees: dense rounded crowns over clearly separated trunks.
  for (let treeIndex = 0; treeIndex < 40; treeIndex += 1) {
    const side = random() > 0.5 ? 1 : -1;
    const centerX = side * (17 + random() * 28);
    const centerZ = 8 + random() * (LOOP_DEPTH - 16);
    const base = terrainHeight(centerX, centerZ);
    const trunkHeight = 5.5 + random() * 5;
    const crownRadius = 2.4 + random() * 2.4;
    for (let y = 0; y < trunkHeight; y += 0.26) {
      for (let sample = 0; sample < 8; sample += 1) {
        const angle = sample * (TAU / 8);
        points.push(point(centerX + Math.cos(angle) * 0.32, base + y, centerZ + Math.sin(angle) * 0.32, COLORS.infrastructure, 1.45, 0.9));
      }
    }
    for (let sample = 0; sample < 170; sample += 1) {
      const azimuth = random() * TAU;
      const elevation = Math.acos(2 * random() - 1);
      const radius = crownRadius * Math.cbrt(random());
      const x = centerX + Math.sin(elevation) * Math.cos(azimuth) * radius;
      const y = base + trunkHeight + Math.cos(elevation) * radius * 0.82;
      const z = centerZ + Math.sin(elevation) * Math.sin(azimuth) * radius;
      points.push(point(x, y, z, COLORS.vegetation, 1.6, 0.92));
    }
  }

  // Point-cloud buildings: thick two-layer walls, window rows, roof edges, some with pitched roofs.
  const buildings = [
    { x: 31, z: 48, width: 16, depth: 18, height: 10, pitched: false },
    { x: -34, z: 92, width: 18, depth: 22, height: 13, pitched: true },
    { x: 33, z: 132, width: 14, depth: 16, height: 8, pitched: true },
    { x: -31, z: 168, width: 15, depth: 18, height: 9, pitched: false },
    { x: 35, z: 204, width: 15, depth: 19, height: 11, pitched: false },
    { x: -32, z: 248, width: 20, depth: 17, height: 12, pitched: true },
    { x: 30, z: 276, width: 13, depth: 14, height: 7, pitched: true },
  ];
  const wall = (x, y, z, bright) => points.push(point(x, y, z, COLORS.building, bright ? 1.55 : 1.4, bright ? 0.95 : 0.84));
  for (const building of buildings) {
    const xMin = building.x - building.width / 2, xMax = building.x + building.width / 2;
    const zMin = building.z - building.depth / 2, zMax = building.z + building.depth / 2;
    const base = terrainHeight(building.x, building.z);
    const step = 0.5;
    for (let y = 0; y <= building.height; y += step) {
      // Window band: every third storey-ish row leaves gaps, so the facade reads as a building.
      const windowRow = Math.floor(y / 1.6) % 2 === 1 && y > 1 && y < building.height - 0.8;
      for (let x = xMin; x <= xMax; x += step) {
        const gap = windowRow && Math.floor((x - xMin) / 1.4) % 2 === 1;
        if (gap) continue;
        for (const inset of [0, 0.32]) { wall(x, base + y, zMin + inset, inset === 0); wall(x, base + y, zMax - inset, inset === 0); }
      }
      for (let z = zMin; z <= zMax; z += step) {
        const gap = windowRow && Math.floor((z - zMin) / 1.4) % 2 === 1;
        if (gap) continue;
        for (const inset of [0, 0.32]) { wall(xMin + inset, base + y, z, inset === 0); wall(xMax - inset, base + y, z, inset === 0); }
      }
    }
    // Strong roof edges.
    for (let x = xMin; x <= xMax; x += 0.32) { wall(x, base + building.height, zMin, true); wall(x, base + building.height, zMax, true); }
    for (let z = zMin; z <= zMax; z += 0.32) { wall(xMin, base + building.height, z, true); wall(xMax, base + building.height, z, true); }
    if (building.pitched) {
      // Gable roof along x: ridge in the middle.
      const ridge = building.height + Math.min(building.width, building.depth) * 0.3;
      for (let x = xMin; x <= xMax; x += 0.55) {
        const rise = (1 - Math.abs((x - building.x) / (building.width / 2))) * (ridge - building.height);
        for (let z = zMin; z <= zMax; z += 0.55) wall(x, base + building.height + rise, z, Math.abs(x - building.x) < 0.3);
      }
    } else {
      for (let x = xMin; x <= xMax; x += 0.7) {
        for (let z = zMin; z <= zMax; z += 0.7) if (Math.floor((x + z) * 2) % 2 === 0) wall(x, base + building.height, z, false);
      }
    }
  }

  // Distribution poles: thick trunks, double crossarms with braces, insulators, risers, communication
  // attachments, street lights, guy wires to anchors and (every second pole) a transformer with cut-outs.
  let poleNumber = 0;
  for (let z = 12; z < LOOP_DEPTH; z += POLE_SPACING) {
    const x = -11.5 + Math.sin(z * 0.045) * 0.5;
    const base = terrainHeight(x, z);
    poles.push({ x, z, base, number: poleNumber + 1, hasTransformer: poleNumber % 2 === 0 });
    const infra = (px, py, pz, size = 1.85, alpha = 1) => points.push(point(px, py, pz, COLORS.infrastructure, size, alpha));
    for (let y = 0; y <= POLE_HEIGHT; y += 0.2) {
      const radius = 0.55 - (y / POLE_HEIGHT) * 0.12; // slight taper towards the top
      for (let sample = 0; sample < 14; sample += 1) {
        const angle = sample * (TAU / 14) + z;
        infra(x + Math.cos(angle) * radius, base + y, z + Math.sin(angle) * radius, 1.9, 1);
      }
    }
    // Two crossarms, each two rows thick.
    for (const level of [1.35, 2.75]) {
      for (let arm = -4.6; arm <= 4.6; arm += 0.18) {
        for (const thick of [0, 0.22]) infra(x + arm, base + POLE_HEIGHT - level - thick, z, 1.9, 1);
      }
    }
    // Diagonal braces under each crossarm.
    for (const level of [1.35, 2.75]) {
      for (const direction of [-1, 1]) {
        for (let step = 0; step <= 24; step += 1) {
          const t = step / 24;
          infra(x + direction * 3.4 * t, base + POLE_HEIGHT - level - 2.2 + 2.0 * t, z, 1.55, 0.95);
        }
      }
    }
    // Insulators on both crossarms.
    for (const level of [1.35, 2.75]) {
      for (const offset of [-4.1, -2.4, 2.4, 4.1]) {
        for (let drop = 0; drop < 1.15; drop += 0.14) {
          const flare = 0.16 + drop * 0.11;
          for (const side of [-1, 1]) points.push(point(x + offset + side * flare, base + POLE_HEIGHT - level - 0.1 - drop, z, COLORS.highlight, 1.85, 1));
        }
      }
    }
    // Pole-top pin insulator.
    for (let drop = 0; drop < 0.9; drop += 0.12) points.push(point(x, base + POLE_HEIGHT + 0.2 + drop * 0.6, z, COLORS.highlight, 1.85, 1));
    // Riser / conduit running down the pole.
    for (let y = 0.4; y <= POLE_HEIGHT - 3.4; y += 0.22) infra(x + 0.72, base + y, z + 0.25, 1.5, 0.92);
    // Communication attachments (bolted clamps) at two heights.
    for (const commY of [8.6, 9.6]) {
      for (let dx = -0.8; dx <= 0.8; dx += 0.12) infra(x + dx, base + commY, z, 1.7, 1);
    }
    // Street-light arm with luminaire on alternate poles (towards the road).
    if (poleNumber % 2 === 1) {
      for (let step = 0; step <= 30; step += 1) {
        const t = step / 30;
        infra(x + 0.6 + t * 4.2, base + 12.2 + Math.sin(t * Math.PI * 0.5) * 1.1, z, 1.7, 1);
      }
      for (let dx = 0; dx <= 1.4; dx += 0.12) {
        for (const dy of [0, 0.22]) points.push(point(x + 4.4 + dx, base + 13.2 - dy, z, COLORS.equipment, 1.9, 1));
      }
    }
    // Guy wire from below the crossarm to a ground anchor, away from the road.
    if (poleNumber % 3 === 0) {
      const anchorX = x - 7.5, anchorZ = z - 3.5, anchorBase = terrainHeight(anchorX, anchorZ);
      for (let step = 0; step <= 70; step += 1) {
        const t = step / 70;
        infra(x + (anchorX - x) * t, base + POLE_HEIGHT - 3.2 + (anchorBase - (base + POLE_HEIGHT - 3.2)) * t, z + (anchorZ - z) * t, 1.45, 0.9);
      }
      for (let r = 0; r < 10; r += 1) infra(anchorX + Math.cos(r) * 0.4, anchorBase + 0.1, anchorZ + Math.sin(r) * 0.4, 1.8, 1);
    }
    // Every second pole carries a cylindrical transformer, cut-outs and a service box.
    if (poleNumber % 2 === 0) {
      const equipmentY = base + 10.6;
      for (let y = 0; y <= 3.6; y += 0.22) {
        for (let sample = 0; sample < 18; sample += 1) {
          const angle = sample * (TAU / 18);
          points.push(point(x + 1.05 + Math.cos(angle) * 1.0, equipmentY + y, z + Math.sin(angle) * 1.0, COLORS.equipment, 1.9, 1));
        }
      }
      for (let sample = 0; sample < 18; sample += 1) {
        const angle = sample * (TAU / 18);
        for (const ring of [0.5, 0.85]) points.push(point(x + 1.05 + Math.cos(angle) * ring, equipmentY + 3.75, z + Math.sin(angle) * ring, COLORS.equipment, 1.8, 1));
      }
      for (const cut of [-1.6, -0.6]) {
        for (let drop = 0; drop < 1.0; drop += 0.12) points.push(point(x + cut, base + POLE_HEIGHT - 4.4 - drop, z, COLORS.equipment, 1.75, 1));
      }
      for (let boxY = 5.0; boxY <= 7.6; boxY += 0.2) {
        for (let side = -0.7; side <= 0.7; side += 0.35) points.push(point(x + side, base + boxY, z + 0.55, COLORS.equipment, 1.6, 0.95));
      }
    }
    poleNumber += 1;
  }

  // Conductors between successive poles: four power strands on the crossarms and two communication cables.
  for (let poleIndex = 0; poleIndex < poles.length - 1; poleIndex += 1) {
    const start = poles[poleIndex];
    const end = poles[poleIndex + 1];
    const strands = [
      ...[-4.1, -2.4, 2.4, 4.1].map(offset => ({ offset, height: POLE_HEIGHT - 2.6, sag: 2.15, size: 1.5 })),
      ...[-4.1, 4.1].map(offset => ({ offset, height: POLE_HEIGHT - 4.0, sag: 2.0, size: 1.4 })),
      { offset: -0.9, height: 9.6, sag: 1.4, size: 1.6 },
      { offset: 0.9, height: 8.6, sag: 1.3, size: 1.6 },
    ];
    for (const strand of strands) {
      for (let step = 0; step <= 90; step += 1) {
        const t = step / 90;
        const sag = Math.sin(Math.PI * t) * strand.sag;
        conductors.push(point(
          start.x + (end.x - start.x) * t + strand.offset,
          start.base + (end.base - start.base) * t + strand.height - sag,
          start.z + (end.z - start.z) * t,
          COLORS.infrastructure, strand.size, 0.95,
        ));
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
  gradient.addColorStop(0, "#f6fafd");
  gradient.addColorStop(0.42, "#e7f2f8");
  gradient.addColorStop(1, "#d3e6ef");
  context.fillStyle = gradient;
  context.fillRect(0, 0, width, height);

  const glow = context.createRadialGradient(width * viewFocus, height * 0.39, 0, width * viewFocus, height * 0.39, width * 0.58);
  glow.addColorStop(0, "rgba(120, 205, 235, 0.38)");
  glow.addColorStop(0.46, "rgba(170, 220, 238, 0.16)");
  glow.addColorStop(1, "rgba(255, 255, 255, 0)");
  context.fillStyle = glow;
  context.fillRect(0, 0, width, height);
}

function drawPerspectiveGrid(context, travel, width, height, pointer) {
  context.save();
  context.lineWidth = 1;
  context.strokeStyle = "rgba(30, 105, 140, 0.16)";
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
    const alpha = source.alpha * depthFade * nearFade * (highlighted ? 1.5 : 1.3);
    const size = Math.max(1.15, Math.min(4.6, source.size * projected.scale * 0.052));
    context.fillStyle = rgba(highlighted ? COLORS.highlight : source.color, alpha);
    context.fillRect(projected.x, projected.y, size, size);
  }
}

function drawInfrastructure(context, conductors, travel, width, height, pointer, scanDepth) {
  context.save();
  context.globalCompositeOperation = "source-over";
  drawPointCloud(context, conductors, travel, width, height, pointer, scanDepth, 1);
  context.restore();
}

function drawPoleGuides(context, poles, travel, width, height, pointer) {
  context.save();
  context.globalCompositeOperation = "source-over";
  context.strokeStyle = "rgba(22, 70, 96, 0.72)";
  context.shadowColor = "rgba(40, 140, 180, 0.22)";
  context.shadowBlur = 12;
  for (const pole of poles) {
    const base = projectPoint({ x: pole.x, y: pole.base, z: pole.z }, travel, width, height, pointer);
    const top = projectPoint({ x: pole.x, y: pole.base + POLE_HEIGHT, z: pole.z }, travel, width, height, pointer);
    const left = projectPoint({ x: pole.x - 4.5, y: pole.base + POLE_HEIGHT - 1.35, z: pole.z }, travel, width, height, pointer);
    const right = projectPoint({ x: pole.x + 4.5, y: pole.base + POLE_HEIGHT - 1.35, z: pole.z }, travel, width, height, pointer);
    if (!base || !top || !left || !right) continue;
    const alpha = Math.min(0.8, Math.max(0.16, (150 - top.depth) / 130));
    context.globalAlpha = alpha;
    context.lineWidth = Math.max(2, Math.min(6.5, top.scale * 0.11));
    context.beginPath();
    context.moveTo(base.x, base.y);
    context.lineTo(top.x, top.y);
    context.moveTo(left.x, left.y);
    context.lineTo(right.x, right.y);
    context.stroke();
  }
  context.restore();
}

// Mobile LiDAR mapping car, seen from a chase camera as it drives down the corridor: metallic body, glass with
// reflections, a full-width LED tail bar and a roof rack carrying a spinning LiDAR head that sweeps the road.
// On sign-in it accelerates away and is drawn into the entrance logo (logoTarget), leaving light trails.
let logoTarget = null;
const CAR_LEAVE = 0.62; // share of the entrance warp spent driving into the logo

function carPose(width, height, pointer, time, warp) {
  const carWidth = Math.max(200, Math.min(width < 720 ? width * 0.62 : width * 0.25, 430));
  const sway = Math.sin(time * 0.0011) * 3 + pointer.x * 6;
  const bob = Math.sin(time * 0.0042) * 1.1;
  const start = { x: width * viewFocus + sway, y: height - carWidth * 0.2 + bob };
  if (warp <= 0) return { ...start, scale: 1, carWidth, k: 0 };
  const k = Math.min(1, warp / CAR_LEAVE), e = k * k * (3 - 2 * k);
  const target = logoTarget || { x: width / 2, y: height * 0.36 };
  // A gentle arc: first a short dip as it launches, then straight up the road into the logo.
  const lift = Math.sin(Math.PI * e) * -height * 0.04;
  return { x: start.x + (target.x - start.x) * e, y: start.y + (target.y - start.y) * e + lift, scale: Math.max(0.02, 1 - e * 0.98), carWidth, k };
}

function drawStreetViewCar(context, width, height, pointer, time, warp) {
  const pose = carPose(width, height, pointer, time, warp);
  if (pose.k >= 1) { drawLogoPulse(context, width, height, warp); return; }
  const W = pose.carWidth, H = W * 0.62, s = pose.scale;

  // Light trails from the tail bar while it drives into the logo.
  if (pose.k > 0) {
    const from = carPose(width, height, pointer, time, 0);
    context.save();
    context.globalCompositeOperation = "source-over";
    for (const side of [-1, 1]) {
      const trail = context.createLinearGradient(from.x, from.y, pose.x, pose.y);
      trail.addColorStop(0, "rgba(255, 60, 80, 0)");
      trail.addColorStop(1, `rgba(255, 90, 110, ${0.55 * (1 - pose.k * 0.4)})`);
      context.strokeStyle = trail;
      context.lineWidth = Math.max(1.5, 7 * s);
      context.lineCap = "round";
      context.beginPath();
      context.moveTo(from.x + side * W * 0.36, from.y - H * 0.42);
      context.lineTo(pose.x + side * W * 0.36 * s, pose.y - H * 0.42 * s);
      context.stroke();
    }
    context.restore();
  }

  context.save();
  context.translate(pose.x, pose.y);
  context.scale(s, s);

  // Road contact shadow and headlight spill on the road ahead.
  const shadow = context.createRadialGradient(0, 0, 0, 0, 0, W * 0.62);
  shadow.addColorStop(0, "rgba(20, 45, 60, 0.32)");
  shadow.addColorStop(1, "rgba(0, 0, 0, 0)");
  context.fillStyle = shadow;
  context.beginPath(); context.ellipse(0, 2, W * 0.62, H * 0.13, 0, 0, TAU); context.fill();
  context.save();
  context.globalCompositeOperation = "source-over";
  const beam = context.createRadialGradient(0, -H * 0.55, 0, 0, -H * 0.55, W * 0.9);
  beam.addColorStop(0, "rgba(0, 150, 200, 0.08)");
  beam.addColorStop(1, "rgba(0, 150, 200, 0)");
  context.fillStyle = beam;
  context.beginPath(); context.ellipse(0, -H * 0.6, W * 0.75, H * 0.3, 0, 0, TAU); context.fill();
  context.restore();

  // Tyres peeking out under the body.
  context.fillStyle = "#1c2a33";
  for (const side of [-1, 1]) { context.beginPath(); context.roundRect(side * W * 0.43 - W * 0.06, -H * 0.13, W * 0.12, H * 0.15, W * 0.02); context.fill(); }

  // Lower body / bumper.
  const body = context.createLinearGradient(0, -H * 0.62, 0, 0);
  body.addColorStop(0, "#ffffff");
  body.addColorStop(0.18, "#eef4f7");
  body.addColorStop(0.62, "#cbdbe3");
  body.addColorStop(1, "#8fa8b5");
  context.fillStyle = body;
  context.shadowColor = "rgba(30, 60, 80, 0.28)"; context.shadowBlur = 16;
  context.beginPath();
  context.moveTo(-W * 0.5, -H * 0.1);
  context.bezierCurveTo(-W * 0.52, -H * 0.36, -W * 0.5, -H * 0.55, -W * 0.44, -H * 0.62);
  context.lineTo(W * 0.44, -H * 0.62);
  context.bezierCurveTo(W * 0.5, -H * 0.55, W * 0.52, -H * 0.36, W * 0.5, -H * 0.1);
  context.quadraticCurveTo(W * 0.5, -H * 0.02, W * 0.42, -H * 0.02);
  context.lineTo(-W * 0.42, -H * 0.02);
  context.quadraticCurveTo(-W * 0.5, -H * 0.02, -W * 0.5, -H * 0.1);
  context.closePath(); context.fill();
  context.shadowBlur = 0;
  context.strokeStyle = "rgba(60, 105, 128, 0.5)"; context.lineWidth = 1.2; context.stroke();

  // Cabin and rear glass with a sky reflection.
  const cabin = context.createLinearGradient(0, -H * 0.98, 0, -H * 0.6);
  cabin.addColorStop(0, "#e3edf2"); cabin.addColorStop(1, "#b5c9d4");
  context.fillStyle = cabin;
  context.beginPath();
  context.moveTo(-W * 0.42, -H * 0.6);
  context.quadraticCurveTo(-W * 0.38, -H * 0.9, -W * 0.3, -H * 0.97);
  context.lineTo(W * 0.3, -H * 0.97);
  context.quadraticCurveTo(W * 0.38, -H * 0.9, W * 0.42, -H * 0.6);
  context.closePath(); context.fill();
  const glass = context.createLinearGradient(0, -H * 0.93, 0, -H * 0.66);
  glass.addColorStop(0, "#1a2f3b"); glass.addColorStop(0.55, "#2c5164"); glass.addColorStop(1, "#6fa2b6");
  context.fillStyle = glass;
  context.beginPath();
  context.moveTo(-W * 0.35, -H * 0.66);
  context.quadraticCurveTo(-W * 0.32, -H * 0.86, -W * 0.26, -H * 0.92);
  context.lineTo(W * 0.26, -H * 0.92);
  context.quadraticCurveTo(W * 0.32, -H * 0.86, W * 0.35, -H * 0.66);
  context.closePath(); context.fill();
  context.save(); context.clip();
  const glint = context.createLinearGradient(-W * 0.3, -H * 0.92, W * 0.1, -H * 0.66);
  glint.addColorStop(0, "rgba(255, 255, 255, 0)"); glint.addColorStop(0.45, "rgba(255, 255, 255, 0.3)"); glint.addColorStop(0.55, "rgba(255, 255, 255, 0)");
  context.fillStyle = glint; context.fillRect(-W * 0.4, -H, W * 0.8, H * 0.4);
  context.restore();

  // Shoulder highlight along the body.
  context.strokeStyle = "rgba(255, 255, 255, 0.9)"; context.lineWidth = 1.4;
  context.beginPath(); context.moveTo(-W * 0.45, -H * 0.58); context.quadraticCurveTo(0, -H * 0.63, W * 0.45, -H * 0.58); context.stroke();

  // Full-width LED tail bar with glowing ends.
  context.save();
  context.shadowColor = "rgba(255, 40, 70, 0.55)"; context.shadowBlur = 12;
  const tail = context.createLinearGradient(-W * 0.46, 0, W * 0.46, 0);
  tail.addColorStop(0, "#ff4d5e"); tail.addColorStop(0.15, "#c3142e"); tail.addColorStop(0.5, "#ff3550"); tail.addColorStop(0.85, "#c3142e"); tail.addColorStop(1, "#ff4d5e");
  context.fillStyle = tail;
  context.beginPath(); context.roundRect(-W * 0.46, -H * 0.5, W * 0.92, H * 0.045, H * 0.02); context.fill();
  for (const side of [-1, 1]) { context.beginPath(); context.roundRect(side * W * 0.46 - (side > 0 ? W * 0.1 : 0), -H * 0.53, W * 0.1, H * 0.1, H * 0.03); context.fill(); }
  context.restore();

  // Plate.
  context.fillStyle = "rgba(255, 255, 255, 0.98)";
  context.beginPath(); context.roundRect(-W * 0.085, -H * 0.3, W * 0.17, H * 0.085, 3); context.fill();
  context.fillStyle = "#0b2a3a"; context.font = `800 ${Math.round(H * 0.06)}px ui-monospace, SFMono-Regular, Consolas, monospace`;
  context.textAlign = "center"; context.textBaseline = "middle"; context.fillText("JSAN", 0, -H * 0.255);

  // Roof rack, GNSS antennas and the spinning LiDAR head.
  context.fillStyle = "#2a3c47"; context.strokeStyle = "rgba(60, 105, 128, 0.5)"; context.lineWidth = 1;
  context.beginPath(); context.roundRect(-W * 0.3, -H * 1.03, W * 0.6, H * 0.05, 3); context.fill(); context.stroke();
  for (const side of [-1, 1]) { context.fillStyle = "#f4f8fa"; context.beginPath(); context.ellipse(side * W * 0.24, -H * 1.06, W * 0.03, H * 0.016, 0, 0, TAU); context.fill(); }
  context.fillStyle = "#2a3c47"; context.fillRect(-W * 0.012, -H * 1.16, W * 0.024, H * 0.13);
  const head = { y: -H * 1.21, r: W * 0.06, h: H * 0.1 };
  const can = context.createLinearGradient(-head.r, 0, head.r, 0);
  can.addColorStop(0, "#22374a"); can.addColorStop(0.45, "#7fb2c6"); can.addColorStop(1, "#22374a");
  context.fillStyle = can;
  context.beginPath(); context.roundRect(-head.r, head.y - head.h / 2, head.r * 2, head.h, head.r * 0.3); context.fill();
  // Rotating window band on the sensor.
  const spin = (time * 0.012) % TAU, band = Math.sin(spin);
  context.save();
  context.globalCompositeOperation = "source-over";
  context.fillStyle = "rgba(0, 170, 220, 0.9)";
  context.shadowColor = "rgba(0, 170, 220, 0.6)"; context.shadowBlur = 8;
  context.beginPath(); context.ellipse(band * head.r * 0.7, head.y, head.r * 0.22 * (1 - Math.abs(band) * 0.6), head.h * 0.18, 0, 0, TAU); context.fill();
  // The scan beam sweeping the road around the car.
  if (pose.k === 0) {
    const reach = W * 1.15, a = Math.PI / 2 + Math.sin(spin) * 1.15;
    const end = { x: Math.cos(a) * reach * Math.sign(Math.cos(spin) || 1), y: head.y + Math.sin(a) * reach * 0.35 };
    const ray = context.createLinearGradient(0, head.y, end.x, end.y);
    ray.addColorStop(0, "rgba(0, 150, 200, 0.55)"); ray.addColorStop(1, "rgba(0, 150, 200, 0)");
    context.strokeStyle = ray; context.lineWidth = 1.5; context.shadowBlur = 6;
    context.beginPath(); context.moveTo(0, head.y); context.lineTo(end.x, end.y); context.stroke();
  }
  context.restore();
  context.restore();
}

// After the car reaches the logo: a ring of light spreads from it.
function drawLogoPulse(context, width, height, warp) {
  const target = logoTarget || { x: width / 2, y: height * 0.36 };
  const t = Math.min(1, (warp - CAR_LEAVE) / 0.25);
  if (t >= 1) return;
  context.save();
  context.globalCompositeOperation = "source-over";
  for (const [r, a] of [[30 + t * 140, 0.7], [20 + t * 90, 0.45]]) {
    context.strokeStyle = `rgba(0, 150, 200, ${a * (1 - t)})`;
    context.lineWidth = 3 * (1 - t) + 1;
    context.beginPath(); context.arc(target.x, target.y, r, 0, TAU); context.stroke();
  }
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
  context.globalCompositeOperation = "source-over";
  context.strokeStyle = locked ? "rgba(12, 140, 92, 0.95)" : "rgba(0, 128, 176, 0.9)";
  context.fillStyle = locked ? "rgba(12, 140, 92, 0.96)" : "rgba(0, 128, 176, 0.92)";
  context.shadowColor = locked ? "rgba(12, 140, 92, 0.25)" : "rgba(0, 128, 176, 0.25)";
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
  context.fillStyle = locked ? "rgba(10, 128, 84, 1)" : "rgba(0, 116, 160, 1)";
  context.font = "800 12px Inter, system-ui, sans-serif";
  context.fillText(locked ? "AUTO POLE ANALYSIS · LOCKED" : "AUTO POLE ANALYSIS · SCANNING", panelX + 16, panelY + 26);
  context.strokeStyle = "rgba(30, 120, 160, 0.22)";
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
    context.fillStyle = "rgba(70, 105, 125, 0.95)";
    context.textAlign = "left";
    context.fillText(label, panelX + 16, rowY);
    context.fillStyle = index === 3 ? "rgba(10, 128, 84, 1)" : "rgba(13, 40, 56, 1)";
    context.textAlign = "right";
    context.fillText(value, panelX + panelWidth - 16, rowY);
  });
  context.textAlign = "left";
  context.fillStyle = "rgba(40, 96, 122, 0.95)";
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
  context.strokeStyle = "rgba(30, 120, 160, 0.32)";
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
  context.shadowColor = "rgba(20, 50, 70, 0.16)";
  context.shadowBlur = 18;
  context.fillStyle = "rgba(255, 255, 255, 0.9)";
  context.beginPath();
  context.roundRect(x, y, panelWidth, panelHeight, 10);
  context.fill();
  context.restore();
  context.strokeStyle = "rgba(30, 120, 160, 0.3)";
  context.lineWidth = 1;
  context.stroke();
  context.fillStyle = "rgba(0, 150, 200, 0.85)";
  context.fillRect(x + 14, y, 36, 2);
}

// Text on the HUD gets a soft dark halo so it stays legible over bright returns.
function hudText(context, text, x, y) {
  context.save();
  context.shadowColor = "rgba(255, 255, 255, 0.9)";
  context.shadowBlur = 4;
  context.fillText(text, x, y);
  context.restore();
}

function drawViewerChrome(context, width, height, scanDepth, time, pointCount, inspection) {
  if (width < 720) return;
  context.save();
  drawCornerFrame(context, width, height);

  context.font = "800 13px Inter, system-ui, sans-serif";
  context.fillStyle = "rgba(13, 45, 70, 0.96)";
  hudText(context, "LIDAR CORRIDOR SCAN", 30, 110);
  context.font = "600 11px ui-monospace, SFMono-Regular, Consolas, monospace";
  context.fillStyle = "rgba(50, 108, 136, 0.92)";
  hudText(context, "UTILITY ASSET CLASSIFICATION / QC", 30, 126);

  // Live scan status.
  drawPanel(context, 28, 138, 236, 82);
  const statusColor = inspection.locked ? "214, 132, 10" : "12, 150, 98";
  context.fillStyle = `rgba(${statusColor}, 1)`;
  context.shadowColor = `rgba(${statusColor}, 0.35)`;
  context.shadowBlur = 8;
  context.beginPath();
  context.arc(46, 160, 4.5, 0, TAU);
  context.fill();
  context.shadowBlur = 0;
  context.font = "800 12px Inter, system-ui, sans-serif";
  context.fillStyle = "rgba(13, 40, 56, 1)";
  context.fillText(inspection.locked ? "POLE MEASUREMENT LOCK" : "LIVE POINT CLOUD", 58, 164);
  context.font = "600 11px ui-monospace, SFMono-Regular, Consolas, monospace";
  context.fillStyle = "rgba(58, 108, 132, 0.95)";
  context.fillText(`FRAME  ${String(Math.floor(time / 33) % 10000).padStart(4, "0")}`, 44, 187);
  context.fillText(`SCAN   ${scanDepth.toFixed(1).padStart(5, "0")} m`, 44, 205);

  // Point-cloud telemetry stacks under the scan status, on the side away from the sign-in card.
  if (width >= 1080 && height >= 560) {
    const panelX = 28;
    const top = 232;
    drawPanel(context, panelX, top, 236, 164);
    context.font = "800 12px Inter, system-ui, sans-serif";
    context.fillStyle = "rgba(13, 40, 56, 1)";
    context.fillText("VIEWER TELEMETRY", panelX + 16, top + 26);
    context.strokeStyle = "rgba(30, 120, 160, 0.22)";
    context.beginPath();
    context.moveTo(panelX + 16, top + 38);
    context.lineTo(panelX + 220, top + 38);
    context.stroke();
    context.font = "600 11px ui-monospace, SFMono-Regular, Consolas, monospace";
    context.fillStyle = "rgba(70, 105, 125, 0.95)";
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
      context.fillStyle = index === 4 || (index === 3 && inspection.locked) ? "rgba(10, 128, 84, 1)" : "rgba(13, 40, 56, 1)";
      context.fillText(value, panelX + 220, rowY);
      context.textAlign = "left";
      context.fillStyle = "rgba(70, 105, 125, 0.95)";
    });
  }

  // View-mode rail mirrors the engineering evidence viewer without becoming interactive.
  const modes = ["PLAN", "PROFILE", "CROSS", "3D"];
  let modeX = 28;
  const modeY = height - 62;
  context.font = "800 11px Inter, system-ui, sans-serif";
  for (const mode of modes) {
    const tabWidth = mode === "PROFILE" ? 84 : 60;
    context.fillStyle = mode === "3D" ? "rgba(0, 140, 190, 0.92)" : "rgba(255, 255, 255, 0.88)";
    context.strokeStyle = mode === "3D" ? "rgba(0, 110, 155, 0.95)" : "rgba(30, 120, 160, 0.35)";
    context.beginPath();
    context.roundRect(modeX, modeY - 4, tabWidth, 31, 7);
    context.fill();
    context.stroke();
    context.fillStyle = mode === "3D" ? "rgba(255, 255, 255, 1)" : "rgba(30, 78, 102, 0.95)";
    context.fillText(mode, modeX + 12, modeY + 16);
    modeX += tabWidth + 8;
  }
  context.font = "600 11px ui-monospace, SFMono-Regular, Consolas, monospace";
  context.textAlign = "right";
  context.fillStyle = "rgba(58, 108, 132, 0.9)";
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
  context.globalCompositeOperation = "source-over";
  context.lineCap = "round";
  for (const streak of WARP_STREAKS) {
    const t = (streak.offset + warp * streak.speed * 1.6) % 1;
    const start = Math.pow(t, 2) * reach;
    const length = 12 + warp * warp * 260 * streak.speed;
    const dx = Math.cos(streak.angle);
    const dy = Math.sin(streak.angle);
    context.strokeStyle = `rgba(0, 140, 190, ${Math.min(0.75, warp * 0.9) * (0.35 + t * 0.65)})`;
    context.lineWidth = streak.width * (0.6 + t * 1.4);
    context.beginPath();
    context.moveTo(cx + dx * start, cy + dy * start);
    context.lineTo(cx + dx * (start + length), cy + dy * (start + length));
    context.stroke();
  }
  const core = context.createRadialGradient(cx, cy, 0, cx, cy, reach * (0.15 + warp * 0.5));
  core.addColorStop(0, `rgba(255, 255, 255, ${0.7 * warp})`);
  core.addColorStop(1, "rgba(160, 220, 240, 0)");
  context.fillStyle = core;
  context.fillRect(0, 0, width, height);
  context.restore();
  const flash = smoothStep((warp - 0.82) / 0.18);
  if (flash > 0) {
    context.fillStyle = `rgba(255, 255, 255, ${flash * 0.9})`;
    context.fillRect(0, 0, width, height);
  }
}

let slowFrames = 0;
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
  let baseFocus = 0.5;

  function resize() {
    const bounds = canvas.getBoundingClientRect();
    width = Math.max(1, Math.round(bounds.width));
    height = Math.max(1, Math.round(bounds.height));
    baseFocus = width >= 1100 ? 0.4 : 0.5;
    viewFocus = baseFocus;
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
    // The entrance is centred on screen, so the camera glides back to centre as it starts.
    viewFocus = baseFocus + (0.5 - baseFocus) * smoothStep(warp * 3);
    const scanDepth = inspection.active
      ? wrappedDepth(inspection.pole.z, travel)
      : 22 + ((sceneTime * 0.047) % 150);
    const density = Math.max(width < 680 ? 2 : 1, slowFrames > 20 ? 3 : slowFrames > 8 ? 2 : 1);
    drawBackdrop(context, width, height);
    drawPerspectiveGrid(context, travel, width, height, pointer);
    drawPointCloud(context, scene.points, travel, width, height, pointer, scanDepth, density);
    drawInfrastructure(context, scene.conductors, travel, width, height, pointer, scanDepth);
    drawPoleGuides(context, scene.poles, travel, width, height, pointer);
    drawStreetViewCar(context, width, height, pointer, sceneTime, warp);
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
      const started = performance.now();
      render(time);
      // Frames slower than ~26 ms push the scene to draw fewer points; quick frames slowly bring the detail back.
      const cost = performance.now() - started;
      slowFrames = Math.max(0, Math.min(40, slowFrames + (cost > 26 ? 1 : cost < 14 ? -0.25 : 0)));
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
  stop.enter = (target = null) => new Promise(resolve => {
    if (reducedMotion || stopped) { resolve(); return; }
    // Where the car flies to: the entrance logo, in canvas coordinates.
    if (target) { const box = canvas.getBoundingClientRect(); logoTarget = { x: target.x - box.left, y: target.y - box.top }; }
    warpStart = performance.now();
    setTimeout(resolve, WARP_MS);
  });
  // Signed out again mid-entrance: return to the normal fly-through.
  stop.leave = () => { warpStart = null; viewFocus = baseFocus; logoTarget = null; };
  return stop;
}
