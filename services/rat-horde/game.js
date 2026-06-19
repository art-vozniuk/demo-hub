// КРЫСИНАЯ ОРДА — top-down 3D rogue-like shooter.
// Style: neon-noir low-poly — flat-faceted meshes on a dark steel-blue arena,
// one hot accent (toxic-green muzzle/score VFX), glowing red rat eyes.
import * as THREE from "./vendor/three.module.min.js";
import { STR } from "./strings.js";

// ---------------------------------------------------------------- constants
const ARENA = 26;                 // half-extent of the play field
const MAX_ENEMIES = 120;
const MAX_BULLETS = 260;
const MAX_PARTICLES = 600;
const STEP = 1000 / 60;           // fixed simulation step (ms)

const COL = {
  bg: 0x080b12, floor: 0x161d2b, grid: 0x24405a,
  hero: 0x4fd0e0, heroDark: 0x2a8f9e, gun: 0x101820,
};
const RAT_BODY = 0x6c6358, RAT_LIMB = 0x554d44, RAT_SNOUT = 0x8a7d6e;
const ACCENT = 0x9dff3c;          // toxic green — the one hot accent
const EYE = 0xff3b30;

// ---------------------------------------------------------------- seeded RNG
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
let rng = mulberry32(1337);
const rand = (a, b) => a + (b - a) * rng();

// ---------------------------------------------------------------- renderer / scene
const canvas = document.getElementById("c");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
renderer.setClearColor(COL.bg, 1);
const DPR_CAP = 1.75;

const scene = new THREE.Scene();
scene.background = new THREE.Color(COL.bg);
scene.fog = new THREE.Fog(COL.bg, 30, 72);

const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 240);
const camOffset = new THREE.Vector3(0, 28, 21);   // angled top-down
const camTarget = new THREE.Vector3();
const camPos = new THREE.Vector3();

function resize() {
  const dpr = Math.min(devicePixelRatio || 1, DPR_CAP);
  renderer.setPixelRatio(dpr);
  renderer.setSize(innerWidth, innerHeight, false);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
addEventListener("orientationchange", resize);

// ---------------------------------------------------------------- lights
scene.add(new THREE.HemisphereLight(0x9fb5d6, 0x0a0e16, 0.85));
const key = new THREE.DirectionalLight(0xdfe9ff, 1.05);
key.position.set(12, 26, 8);
scene.add(key);
const rim = new THREE.DirectionalLight(ACCENT, 0.25);
rim.position.set(-14, 10, -16);
scene.add(rim);

// ---------------------------------------------------------------- arena
const floorMat = new THREE.MeshLambertMaterial({ color: COL.floor });
const floor = new THREE.Mesh(new THREE.PlaneGeometry(ARENA * 2, ARENA * 2), floorMat);
floor.rotation.x = -Math.PI / 2;
scene.add(floor);

const grid = new THREE.GridHelper(ARENA * 2, ARENA, COL.grid, COL.grid);
grid.position.y = 0.02;
grid.material.transparent = true;
grid.material.opacity = 0.5;
scene.add(grid);

// neon border walls (the hot accent frames the arena)
const wallMat = new THREE.MeshBasicMaterial({ color: ACCENT });
const wallGeoH = new THREE.BoxGeometry(ARENA * 2 + 1.2, 0.6, 0.5);
const wallGeoV = new THREE.BoxGeometry(0.5, 0.6, ARENA * 2 + 1.2);
for (const [g, x, z] of [[wallGeoH, 0, -ARENA], [wallGeoH, 0, ARENA], [wallGeoV, -ARENA, 0], [wallGeoV, ARENA, 0]]) {
  const w = new THREE.Mesh(g, wallMat);
  w.position.set(x, 0.3, z);
  scene.add(w);
}

// ---------------------------------------------------------------- fake shadows (cheap grounding)
const shadowGeo = new THREE.CircleGeometry(0.55, 12).rotateX(-Math.PI / 2);
const shadowMat = new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.32, depthWrite: false });
const enemyShadows = new THREE.InstancedMesh(shadowGeo, shadowMat, MAX_ENEMIES);
enemyShadows.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
scene.add(enemyShadows);

// ---------------------------------------------------------------- player
const player = new THREE.Group();
function box(w, h, d, color, flat = true) {
  return new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshLambertMaterial({ color, flatShading: flat }));
}
const pBody = box(0.5, 0.6, 0.36, COL.hero); pBody.position.y = 0.62; player.add(pBody);
const pHead = box(0.32, 0.3, 0.32, COL.hero); pHead.position.y = 1.05; player.add(pHead);
const pVisor = box(0.26, 0.09, 0.06, ACCENT); pVisor.position.set(0, 1.07, 0.16); player.add(pVisor);
// arms + gun, extending forward (+Z local)
const pArmL = box(0.13, 0.13, 0.5, COL.heroDark); pArmL.position.set(0.2, 0.78, 0.2); player.add(pArmL);
const pArmR = box(0.13, 0.13, 0.5, COL.heroDark); pArmR.position.set(-0.2, 0.78, 0.2); player.add(pArmR);
const pGun = box(0.16, 0.16, 0.62, COL.gun); pGun.position.set(0.0, 0.78, 0.5); player.add(pGun);
const pMuzzle = new THREE.Mesh(new THREE.SphereGeometry(0.14, 8, 6), new THREE.MeshBasicMaterial({ color: ACCENT }));
pMuzzle.position.set(0, 0.78, 0.86); pMuzzle.visible = false; player.add(pMuzzle);
const pLegL = box(0.16, 0.45, 0.18, COL.heroDark); pLegL.geometry.translate(0, -0.225, 0); pLegL.position.set(0.13, 0.45, 0); player.add(pLegL);
const pLegR = box(0.16, 0.45, 0.18, COL.heroDark); pLegR.geometry.translate(0, -0.225, 0); pLegR.position.set(-0.13, 0.45, 0); player.add(pLegR);
const pShadow = new THREE.Mesh(shadowGeo, new THREE.MeshBasicMaterial({ color: 0, transparent: true, opacity: 0.4, depthWrite: false }));
pShadow.scale.setScalar(1.05); pShadow.position.y = 0.03; player.add(pShadow);
scene.add(player);

// ---------------------------------------------------------------- rat parts (instanced — whole swarm in a handful of draw calls)
function lambert(color, opts = {}) { return new THREE.MeshLambertMaterial({ color, flatShading: true, ...opts }); }
function basic(color) { return new THREE.MeshBasicMaterial({ color }); }

// geometry origin baked to its pivot so animated parts rotate correctly
const partDefs = {
  body:  { geo: new THREE.BoxGeometry(0.44, 0.5, 0.34), mat: lambert(RAT_BODY) },
  head:  { geo: new THREE.BoxGeometry(0.32, 0.3, 0.32), mat: lambert(RAT_BODY) },
  snout: { geo: new THREE.ConeGeometry(0.11, 0.26, 6).rotateX(Math.PI / 2).translate(0, 0, 0.13), mat: lambert(RAT_SNOUT) },
  earL:  { geo: new THREE.ConeGeometry(0.08, 0.2, 5), mat: lambert(RAT_SNOUT) },
  earR:  { geo: new THREE.ConeGeometry(0.08, 0.2, 5), mat: lambert(RAT_SNOUT) },
  eyeL:  { geo: new THREE.SphereGeometry(0.055, 6, 5), mat: basic(EYE) },
  eyeR:  { geo: new THREE.SphereGeometry(0.055, 6, 5), mat: basic(EYE) },
  legL:  { geo: new THREE.BoxGeometry(0.14, 0.42, 0.16).translate(0, -0.21, 0), mat: lambert(RAT_LIMB) },
  legR:  { geo: new THREE.BoxGeometry(0.14, 0.42, 0.16).translate(0, -0.21, 0), mat: lambert(RAT_LIMB) },
  armL:  { geo: new THREE.BoxGeometry(0.1, 0.34, 0.1).translate(0, -0.17, 0), mat: lambert(RAT_LIMB) },
  armR:  { geo: new THREE.BoxGeometry(0.1, 0.34, 0.1).translate(0, -0.17, 0), mat: lambert(RAT_LIMB) },
  tail:  { geo: new THREE.BoxGeometry(0.08, 0.08, 0.55).translate(0, 0, -0.27), mat: lambert(RAT_SNOUT) },
};
const partMeshes = {};
for (const k in partDefs) {
  const m = new THREE.InstancedMesh(partDefs[k].geo, partDefs[k].mat, MAX_ENEMIES);
  m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  m.frustumCulled = false;
  partMeshes[k] = m;
  scene.add(m);
}
// per-instance tint for hit-flash on body+head
for (const k of ["body", "head"]) {
  const m = partMeshes[k];
  const base = new THREE.Color(RAT_BODY);
  for (let i = 0; i < MAX_ENEMIES; i++) m.setColorAt(i, base);
  m.instanceColor.needsUpdate = true;
}

// ---------------------------------------------------------------- bullets (instanced glowing tracers)
const bulletGeo = new THREE.BoxGeometry(0.12, 0.12, 0.7);
const bulletMat = new THREE.MeshBasicMaterial({ color: ACCENT });
const bulletMesh = new THREE.InstancedMesh(bulletGeo, bulletMat, MAX_BULLETS);
bulletMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
bulletMesh.frustumCulled = false;
scene.add(bulletMesh);

// ---------------------------------------------------------------- particles (impacts + muzzle bits)
const partGeo = new THREE.BoxGeometry(0.12, 0.12, 0.12);
const partMat = new THREE.MeshBasicMaterial({ color: ACCENT });
const partMesh = new THREE.InstancedMesh(partGeo, partMat, MAX_PARTICLES);
partMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
partMesh.frustumCulled = false;
scene.add(partMesh);

// ---------------------------------------------------------------- pools / state
const enemies = Array.from({ length: MAX_ENEMIES }, () => ({
  alive: false, x: 0, z: 0, hp: 0, maxhp: 0, yaw: 0, phase: 0, speed: 0,
  cd: 0, hit: 0, spawn: 0,
}));
const bullets = Array.from({ length: MAX_BULLETS }, () => ({ alive: false, x: 0, z: 0, vx: 0, vz: 0, life: 0, dmg: 0, pierce: 0, yaw: 0 }));
const particles = Array.from({ length: MAX_PARTICLES }, () => ({ alive: false, x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0, life: 0, max: 0, size: 1 }));

const G = {
  state: "menu",          // menu | playing | upgrade | over
  px: 0, pz: 0, pyaw: 0, walk: 0,
  hp: 100, maxhp: 100,
  score: 0, kills: 0, wave: 0,
  fireCd: 0, shake: 0, hurt: 0,
  // run stats (upgradable)
  dmg: 1, fireRate: 0.2, moveSpd: 8.5, bulletSpd: 42, bullets: 1, pierce: 0, lifesteal: 0,
  // wave control
  toSpawn: 0, spawnTimer: 0, enemyHpBase: 3, enemySpd: 2.6,
};

// dummies reused every frame (zero per-frame allocation)
const dm = new THREE.Object3D();
const root = new THREE.Object3D();
const mRoot = new THREE.Matrix4();
const mPart = new THREE.Matrix4();
const mOut = new THREE.Matrix4();
const ZERO = new THREE.Matrix4().makeScale(0, 0, 0);
const flashCol = new THREE.Color();
const baseRatCol = new THREE.Color(RAT_BODY);

// ---------------------------------------------------------------- helpers
function spawnEnemy() {
  let e = null;
  for (const en of enemies) if (!en.alive) { e = en; break; }
  if (!e) return;
  // spawn at a random arena edge
  const side = (rng() * 4) | 0, t = rand(-ARENA + 2, ARENA - 2);
  if (side === 0) { e.x = -ARENA + 2; e.z = t; }
  else if (side === 1) { e.x = ARENA - 2; e.z = t; }
  else if (side === 2) { e.x = t; e.z = -ARENA + 2; }
  else { e.x = t; e.z = ARENA - 2; }
  e.alive = true;
  e.maxhp = e.hp = G.enemyHpBase + Math.floor(G.wave * 0.6);
  e.speed = G.enemySpd + rand(-0.4, 0.6) + G.wave * 0.07;
  e.yaw = 0; e.phase = rand(0, 6.28); e.cd = 0; e.hit = 0; e.spawn = 0.0;
}

function fireParticles(x, y, z, n, spread, color) {
  for (let i = 0; i < n; i++) {
    let p = null;
    for (const q of particles) if (!q.alive) { p = q; break; }
    if (!p) break;
    p.alive = true; p.x = x; p.y = y; p.z = z;
    const a = rng() * 6.283, sp = rand(spread * 0.3, spread);
    p.vx = Math.cos(a) * sp; p.vz = Math.sin(a) * sp; p.vy = rand(1.5, 5);
    p.life = p.max = rand(0.25, 0.55); p.size = rand(0.6, 1.4);
  }
}

// score popups via DOM overlay pool
const popLayer = document.getElementById("pops");
const pops = Array.from({ length: 30 }, () => {
  const el = document.createElement("div");
  el.className = "pop";
  popLayer.appendChild(el);
  return { el, alive: false, x: 0, y: 0, z: 0, life: 0, max: 0 };
});
function popup(text, x, y, z, big) {
  let p = null;
  for (const q of pops) if (!q.alive) { p = q; break; }
  if (!p) return;
  p.alive = true; p.x = x; p.y = y; p.z = z; p.life = p.max = big ? 1.0 : 0.7;
  p.el.textContent = text;
  p.el.style.color = big ? "#ffffff" : "#9dff3c";
  p.el.style.fontSize = big ? "30px" : "20px";
  p.el.style.opacity = "1";
}
const proj = new THREE.Vector3();
function projectPops(dt) {
  for (const p of pops) {
    if (!p.alive) continue;
    p.life -= dt; p.y += dt * 1.4;
    if (p.life <= 0) { p.alive = false; p.el.style.opacity = "0"; continue; }
    proj.set(p.x, p.y, p.z).project(camera);
    const sx = (proj.x * 0.5 + 0.5) * innerWidth;
    const sy = (-proj.y * 0.5 + 0.5) * innerHeight;
    const k = p.life / p.max;
    p.el.style.transform = `translate(-50%,-50%) translate(${sx}px,${sy}px) scale(${0.8 + 0.4 * k})`;
    p.el.style.opacity = (proj.z < 1 ? Math.min(1, k * 1.6) : 0).toString();
  }
}

// ---------------------------------------------------------------- input
const held = new Set();
const BIND = { KeyW: "up", KeyS: "down", KeyA: "left", KeyD: "right", ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
addEventListener("keydown", (e) => {
  if (BIND[e.code]) { held.add(BIND[e.code]); e.preventDefault(); }
  if (e.code === "Space") { held.add("fire"); e.preventDefault(); }
  if (G.state === "upgrade" && (e.code === "Digit1" || e.code === "Digit2" || e.code === "Digit3"))
    chooseUpgrade(+e.code.slice(5) - 1);
});
addEventListener("keyup", (e) => { if (BIND[e.code]) held.delete(BIND[e.code]); if (e.code === "Space") held.delete("fire"); });
addEventListener("blur", () => held.clear());

// mouse aim -> ground point
const ndc = new THREE.Vector2();
const ray = new THREE.Raycaster();
const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
const aimWorld = new THREE.Vector3(0, 0, 1);
let mouseFire = false;
function updateMouse(e) {
  ndc.x = (e.clientX / innerWidth) * 2 - 1;
  ndc.y = -(e.clientY / innerHeight) * 2 + 1;
  ray.setFromCamera(ndc, camera);
  ray.ray.intersectPlane(groundPlane, aimWorld);
}
addEventListener("mousemove", updateMouse);
addEventListener("mousedown", (e) => { if (e.button === 0) { mouseFire = true; updateMouse(e); } });
addEventListener("mouseup", (e) => { if (e.button === 0) mouseFire = false; });

// touch twin-stick
let moveStick = null, aimStick = null;
function touchStart(e) {
  for (const t of e.changedTouches) {
    if (t.clientX < innerWidth / 2 && !moveStick) moveStick = { id: t.identifier, ox: t.clientX, oy: t.clientY, dx: 0, dy: 0 };
    else if (t.clientX >= innerWidth / 2 && !aimStick) aimStick = { id: t.identifier, ox: t.clientX, oy: t.clientY, dx: 0, dy: 0 };
  }
  e.preventDefault();
}
function touchMove(e) {
  for (const t of e.changedTouches) {
    if (moveStick && t.identifier === moveStick.id) { moveStick.dx = t.clientX - moveStick.ox; moveStick.dy = t.clientY - moveStick.oy; }
    if (aimStick && t.identifier === aimStick.id) { aimStick.dx = t.clientX - aimStick.ox; aimStick.dy = t.clientY - aimStick.oy; }
  }
  e.preventDefault();
}
function touchEnd(e) {
  for (const t of e.changedTouches) {
    if (moveStick && t.identifier === moveStick.id) moveStick = null;
    if (aimStick && t.identifier === aimStick.id) aimStick = null;
  }
  e.preventDefault();
}
addEventListener("touchstart", touchStart, { passive: false });
addEventListener("touchmove", touchMove, { passive: false });
addEventListener("touchend", touchEnd, { passive: false });
addEventListener("touchcancel", touchEnd, { passive: false });

function gamepad() {
  const out = { mx: 0, mz: 0, ax: 0, az: 0, fire: false };
  const pads = navigator.getGamepads ? navigator.getGamepads() : [];
  for (const gp of pads) {
    if (!gp) continue;
    const dz = (v) => (Math.abs(v) > 0.2 ? v : 0);
    out.mx = dz(gp.axes[0] || 0); out.mz = dz(gp.axes[1] || 0);
    out.ax = dz(gp.axes[2] || 0); out.az = dz(gp.axes[3] || 0);
    if (Math.hypot(out.ax, out.az) > 0.4) out.fire = true;
    if (gp.buttons[7] && gp.buttons[7].pressed) out.fire = true;
    if (G.state === "upgrade") {
      if (gp.buttons[2] && gp.buttons[2].pressed) chooseUpgrade(0);
      if (gp.buttons[0] && gp.buttons[0].pressed) chooseUpgrade(1);
      if (gp.buttons[1] && gp.buttons[1].pressed) chooseUpgrade(2);
    }
    break;
  }
  return out;
}

// ---------------------------------------------------------------- simulation
function update(dtMs) {
  const dt = dtMs / 1000;
  if (G.state !== "playing") { decayTimers(dt); return; }

  const gp = gamepad();
  // movement vector (screen-aligned: up = -Z)
  let mx = 0, mz = 0;
  if (held.has("left")) mx -= 1; if (held.has("right")) mx += 1;
  if (held.has("up")) mz -= 1; if (held.has("down")) mz += 1;
  if (moveStick) { mx += clamp(moveStick.dx / 60, -1, 1); mz += clamp(moveStick.dy / 60, -1, 1); }
  mx += gp.mx; mz += gp.mz;
  const ml = Math.hypot(mx, mz);
  if (ml > 1) { mx /= ml; mz /= ml; }
  G.px = clamp(G.px + mx * G.moveSpd * dt, -ARENA + 1, ARENA - 1);
  G.pz = clamp(G.pz + mz * G.moveSpd * dt, -ARENA + 1, ARENA - 1);
  G.walk += ml * dt * 12;

  // aim
  let firing = held.has("fire") || mouseFire;
  let adx, adz;
  if (aimStick && Math.hypot(aimStick.dx, aimStick.dy) > 14) { adx = aimStick.dx; adz = aimStick.dy; firing = true; }
  else if (Math.hypot(gp.ax, gp.az) > 0.4) { adx = gp.ax; adz = gp.az; firing = true; }
  else { adx = aimWorld.x - G.px; adz = aimWorld.z - G.pz; }
  if (Math.hypot(adx, adz) > 0.001) G.pyaw = Math.atan2(adx, adz);

  // fire
  G.fireCd -= dt;
  if (firing && G.fireCd <= 0) {
    G.fireCd = G.fireRate;
    const n = G.bullets, spreadStep = 0.12;
    for (let i = 0; i < n; i++) {
      const off = (i - (n - 1) / 2) * spreadStep;
      shoot(G.pyaw + off);
    }
    pMuzzle.visible = true; pMuzzleT = 0.05;
    const mw = muzzleWorld();
    fireParticles(mw.x, mw.y, mw.z, 4, 5, ACCENT);
    G.shake = Math.min(G.shake + 0.12, 0.5);
  }

  updateBullets(dt);
  updateEnemies(dt);
  updateParticles(dt);
  spawnControl(dt);
  decayTimers(dt);

  // wave clear?
  if (G.toSpawn <= 0 && countAlive() === 0) startUpgrade();
}

let pMuzzleT = 0;
function muzzleWorld() {
  player.updateMatrixWorld();
  return pMuzzle.getWorldPosition(new THREE.Vector3());
}
function shoot(yaw) {
  let b = null;
  for (const q of bullets) if (!q.alive) { b = q; break; }
  if (!b) return;
  const mw = muzzleWorld();
  b.alive = true; b.x = mw.x; b.z = mw.z; b.yaw = yaw;
  b.vx = Math.sin(yaw) * G.bulletSpd; b.vz = Math.cos(yaw) * G.bulletSpd;
  b.life = 1.4; b.dmg = G.dmg; b.pierce = G.pierce;
}

const HIT_R2 = 0.55 * 0.55;
function segDist2(px, pz, ax, az, bx, bz) {
  const dx = bx - ax, dz = bz - az, l2 = dx * dx + dz * dz;
  let t = l2 > 0 ? ((px - ax) * dx + (pz - az) * dz) / l2 : 0;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  const cx = ax + dx * t, cz = az + dz * t, ex = px - cx, ez = pz - cz;
  return ex * ex + ez * ez;
}
function updateBullets(dt) {
  for (const b of bullets) {
    if (!b.alive) continue;
    const x0 = b.x, z0 = b.z;
    b.x += b.vx * dt; b.z += b.vz * dt; b.life -= dt;
    if (b.life <= 0 || Math.abs(b.x) > ARENA || Math.abs(b.z) > ARENA) { b.alive = false; continue; }
    for (const e of enemies) {
      if (!e.alive || e.spawn < 0.25) continue;
      // swept test along the bullet's travel this step (no tunnelling past fast rounds)
      if (segDist2(e.x, e.z, x0, z0, b.x, b.z) < HIT_R2) {
        e.hp -= b.dmg; e.hit = 0.12;
        fireParticles(b.x, 0.7, b.z, 6, 6, ACCENT);
        // knockback
        const il = 1 / (Math.hypot(b.vx, b.vz) || 1);
        e.x += b.vx * il * 0.25; e.z += b.vz * il * 0.25;
        if (e.hp <= 0) killEnemy(e); else popup("+10", e.x, 1.4, e.z, false), G.score += 10;
        if (b.pierce-- <= 0) { b.alive = false; break; }
      }
    }
  }
}

function killEnemy(e) {
  e.alive = false;
  G.kills++; G.score += 50;
  G.hp = Math.min(G.maxhp, G.hp + G.lifesteal);
  popup("+50", e.x, 1.6, e.z, true);
  fireParticles(e.x, 0.8, e.z, 14, 9, ACCENT);
}

function updateEnemies(dt) {
  for (let i = 0; i < enemies.length; i++) {
    const e = enemies[i];
    if (!e.alive) continue;
    if (e.spawn < 1) e.spawn = Math.min(1, e.spawn + dt * 3);
    let dx = G.px - e.x, dz = G.pz - e.z;
    const d = Math.hypot(dx, dz) || 1;
    dx /= d; dz /= d;
    // light separation so the swarm doesn't fully stack
    let sx = 0, sz = 0;
    for (let j = 0; j < enemies.length; j++) {
      if (j === i) continue; const o = enemies[j]; if (!o.alive) continue;
      const ox = e.x - o.x, oz = e.z - o.z, od = ox * ox + oz * oz;
      if (od < 1.1 && od > 0.0001) { const inv = 1 / Math.sqrt(od); sx += ox * inv; sz += oz * inv; }
    }
    const sp = e.speed * e.spawn;
    e.x += (dx + sx * 0.5) * sp * dt;
    e.z += (dz + sz * 0.5) * sp * dt;
    e.x = clamp(e.x, -ARENA + 1, ARENA - 1); e.z = clamp(e.z, -ARENA + 1, ARENA - 1);
    e.yaw = Math.atan2(dx, dz);
    e.phase += sp * dt * 3.2;
    if (e.hit > 0) e.hit -= dt;
    if (e.cd > 0) e.cd -= dt;
    // contact damage
    if (d < 1.05 && e.cd <= 0) {
      e.cd = 0.7; G.hp -= 8; G.hurt = 0.4; G.shake = Math.min(G.shake + 0.35, 0.7);
      if (G.hp <= 0) { G.hp = 0; gameOver(); }
    }
  }
}

function updateParticles(dt) {
  for (const p of particles) {
    if (!p.alive) continue;
    p.life -= dt; if (p.life <= 0) { p.alive = false; continue; }
    p.vy -= 14 * dt;
    p.x += p.vx * dt; p.y += p.vy * dt; p.z += p.vz * dt;
    if (p.y < 0.05) { p.y = 0.05; p.vy *= -0.4; p.vx *= 0.6; p.vz *= 0.6; }
  }
}

function spawnControl(dt) {
  if (G.toSpawn <= 0) return;
  G.spawnTimer -= dt;
  if (G.spawnTimer <= 0 && countAlive() < MAX_ENEMIES - 2) {
    spawnEnemy(); G.toSpawn--;
    G.spawnTimer = Math.max(0.12, 0.6 - G.wave * 0.02);
  }
}

function decayTimers(dt) {
  if (G.shake > 0) G.shake = Math.max(0, G.shake - dt * 1.6);
  if (G.hurt > 0) G.hurt = Math.max(0, G.hurt - dt);
  if (pMuzzleT > 0) { pMuzzleT -= dt; if (pMuzzleT <= 0) pMuzzle.visible = false; }
}

function countAlive() { let n = 0; for (const e of enemies) if (e.alive) n++; return n; }
function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }

// ---------------------------------------------------------------- render sync (write instance matrices)
function syncRender() {
  // player
  player.position.set(G.px, 0, G.pz);
  player.rotation.y = G.pyaw;
  const legSwing = Math.sin(G.walk) * 0.5;
  pLegL.rotation.x = legSwing; pLegR.rotation.x = -legSwing;

  // enemies -> instanced parts
  for (let i = 0; i < enemies.length; i++) {
    const e = enemies[i];
    if (!e.alive) {
      for (const k in partMeshes) partMeshes[k].setMatrixAt(i, ZERO);
      enemyShadows.setMatrixAt(i, ZERO);
      continue;
    }
    const s = 0.4 + 0.6 * e.spawn;              // scale-in on spawn
    root.position.set(e.x, 0, e.z); root.rotation.set(0, e.yaw, 0); root.scale.setScalar(s);
    root.updateMatrix(); mRoot.copy(root.matrix);

    const bob = Math.sin(e.phase * 2) * 0.04;
    const swing = Math.sin(e.phase) * 0.6;
    setPart("body", i, 0, 0.62 + bob, 0, 0.16, 0, 0);
    setPart("head", i, 0, 1.0 + bob, 0.16, -0.1, 0, 0);
    setPart("snout", i, 0, 0.98 + bob, 0.34, 0, 0, 0);
    setPart("earL", i, 0.12, 1.18 + bob, 0.08, -0.3, 0, 0.2);
    setPart("earR", i, -0.12, 1.18 + bob, 0.08, -0.3, 0, -0.2);
    setPart("eyeL", i, 0.09, 1.02 + bob, 0.32, 0, 0, 0);
    setPart("eyeR", i, -0.09, 1.02 + bob, 0.32, 0, 0, 0);
    setPart("legL", i, 0.12, 0.44, 0.02, swing, 0, 0);
    setPart("legR", i, -0.12, 0.44, 0.02, -swing, 0, 0);
    setPart("armL", i, 0.26, 0.8, 0.04, -swing, 0, 0);
    setPart("armR", i, -0.26, 0.8, 0.04, swing, 0, 0);
    setPart("tail", i, 0, 0.55, -0.2, -0.5, Math.sin(e.phase) * 0.3, 0);

    dm.position.set(e.x, 0.03, e.z); dm.rotation.set(-Math.PI / 2, 0, 0); dm.scale.setScalar(s);
    dm.updateMatrix(); enemyShadows.setMatrixAt(i, dm.matrix);

    // hit flash tint
    const tint = e.hit > 0 ? flashCol.setRGB(1, 0.4, 0.3) : baseRatCol;
    partMeshes.body.setColorAt(i, tint); partMeshes.head.setColorAt(i, tint);
  }
  for (const k in partMeshes) partMeshes[k].instanceMatrix.needsUpdate = true;
  partMeshes.body.instanceColor.needsUpdate = true;
  partMeshes.head.instanceColor.needsUpdate = true;
  enemyShadows.instanceMatrix.needsUpdate = true;

  // bullets
  for (let i = 0; i < bullets.length; i++) {
    const b = bullets[i];
    if (!b.alive) { bulletMesh.setMatrixAt(i, ZERO); continue; }
    dm.position.set(b.x, 0.7, b.z); dm.rotation.set(0, b.yaw, 0); dm.scale.setScalar(1);
    dm.updateMatrix(); bulletMesh.setMatrixAt(i, dm.matrix);
  }
  bulletMesh.instanceMatrix.needsUpdate = true;

  // particles
  for (let i = 0; i < particles.length; i++) {
    const p = particles[i];
    if (!p.alive) { partMesh.setMatrixAt(i, ZERO); continue; }
    const k = (p.life / p.max) * p.size;
    dm.position.set(p.x, p.y, p.z); dm.rotation.set(0, 0, 0); dm.scale.setScalar(k);
    dm.updateMatrix(); partMesh.setMatrixAt(i, dm.matrix);
  }
  partMesh.instanceMatrix.needsUpdate = true;
}

function setPart(name, i, px, py, pz, rx, ry, rz) {
  dm.position.set(px, py, pz); dm.rotation.set(rx, ry, rz); dm.scale.setScalar(1);
  dm.updateMatrix(); mPart.copy(dm.matrix);
  mOut.multiplyMatrices(mRoot, mPart);
  partMeshes[name].setMatrixAt(i, mOut);
}

// ---------------------------------------------------------------- camera
function updateCamera(dt) {
  camTarget.lerp(new THREE.Vector3(G.px, 0, G.pz), Math.min(1, dt * 6));
  camPos.copy(camTarget).add(camOffset);
  if (G.shake > 0) {
    camPos.x += rand(-1, 1) * G.shake; camPos.z += rand(-1, 1) * G.shake; camPos.y += rand(-1, 1) * G.shake * 0.5;
  }
  camera.position.copy(camPos);
  camera.lookAt(camTarget.x, 0.5, camTarget.z);
}

// ---------------------------------------------------------------- HUD / screens
const hud = {
  hpfill: document.getElementById("hpfill"),
  wave: document.getElementById("wave"),
  score: document.getElementById("score"),
  kills: document.getElementById("kills"),
  hurt: document.getElementById("hurt"),
};
function syncHud() {
  hud.hpfill.style.width = Math.max(0, (G.hp / G.maxhp) * 100) + "%";
  hud.wave.textContent = STR.waveLabel + " " + G.wave;
  hud.score.textContent = STR.scoreLabel + " " + G.score;
  hud.kills.textContent = STR.killsLabel + " " + G.kills;
  hud.hurt.style.opacity = (G.hurt * 1.4).toFixed(2);
}

const UPGRADE_KEYS = ["damage", "firerate", "speed", "multishot", "pierce", "health", "bulletspd", "lifesteal"];
let upgradeChoices = [];
function startUpgrade() {
  G.state = "upgrade";
  const pool = UPGRADE_KEYS.slice();
  upgradeChoices = [];
  for (let i = 0; i < 3 && pool.length; i++) upgradeChoices.push(pool.splice((rng() * pool.length) | 0, 1)[0]);
  const cards = document.getElementById("cards");
  cards.innerHTML = "";
  upgradeChoices.forEach((key, idx) => {
    const u = STR.upgrades[key];
    const c = document.createElement("button");
    c.className = "card";
    c.innerHTML = `<div class="ck">${idx + 1}</div><div class="cn">${u.name}</div><div class="cd">${u.desc}</div>`;
    c.onclick = () => chooseUpgrade(idx);
    cards.appendChild(c);
  });
  show("upgradeScreen");
}
function chooseUpgrade(idx) {
  if (G.state !== "upgrade" || idx < 0 || idx >= upgradeChoices.length) return;
  applyUpgrade(upgradeChoices[idx]);
  hide("upgradeScreen");
  nextWave();
}
function applyUpgrade(key) {
  switch (key) {
    case "damage": G.dmg += 1; break;
    case "firerate": G.fireRate = Math.max(0.06, G.fireRate * 0.82); break;
    case "speed": G.moveSpd *= 1.12; break;
    case "multishot": G.bullets += 1; break;
    case "pierce": G.pierce += 1; break;
    case "health": G.maxhp += 25; G.hp = Math.min(G.maxhp, G.hp + 40); break;
    case "bulletspd": G.bulletSpd *= 1.25; break;
    case "lifesteal": G.lifesteal += 2; break;
  }
}

function nextWave() {
  G.wave++;
  G.toSpawn = 6 + G.wave * 3;
  G.spawnTimer = 0.2;
  G.state = "playing";
  banner(STR.waveLabel + " " + G.wave);
}

function startGame() {
  rng = mulberry32((Math.random() * 1e9) | 0);
  for (const e of enemies) e.alive = false;
  for (const b of bullets) b.alive = false;
  for (const p of particles) p.alive = false;
  Object.assign(G, {
    state: "playing", px: 0, pz: 0, pyaw: 0, walk: 0, hp: 100, maxhp: 100,
    score: 0, kills: 0, wave: 0, fireCd: 0, shake: 0, hurt: 0,
    dmg: 1, fireRate: 0.2, moveSpd: 8.5, bulletSpd: 42, bullets: 1, pierce: 0, lifesteal: 0,
    toSpawn: 0, spawnTimer: 0, enemyHpBase: 3, enemySpd: 2.6,
  });
  camTarget.set(0, 0, 0);
  hide("menuScreen"); hide("overScreen"); hide("upgradeScreen");
  nextWave();
}

function gameOver() {
  G.state = "over";
  document.getElementById("overScore").textContent = STR.finalScore + ": " + G.score;
  document.getElementById("overWave").textContent = STR.finalWave + " " + G.wave + " · " + STR.killsLabel + " " + G.kills;
  show("overScreen");
}

function show(id) { document.getElementById(id).classList.add("on"); }
function hide(id) { document.getElementById(id).classList.remove("on"); }

const bannerEl = document.getElementById("banner");
let bannerT = 0;
function banner(text) { bannerEl.textContent = text; bannerEl.style.opacity = "1"; bannerT = 1.6; }

// ---------------------------------------------------------------- loop
let acc = 0, last = performance.now();
const dev = new URLSearchParams(location.search).has("dev");
if (dev) {
  document.getElementById("dev").style.display = "block";
  window.__dbg = () => ({
    st: G.state, score: G.score, kills: G.kills, alive: countAlive(),
    bullets: bullets.reduce((n, b) => n + (b.alive ? 1 : 0), 0), hp: Math.round(G.hp),
  });
  window.__clear = () => { G.toSpawn = 0; for (const e of enemies) e.alive = false; };
  window.__nearest = () => {
    let best = null, bd = 1e9;
    for (const e of enemies) { if (!e.alive) continue; const d = (e.x - G.px) ** 2 + (e.z - G.pz) ** 2; if (d < bd) { bd = d; best = e; } }
    if (!best) return null;
    const v = new THREE.Vector3(best.x, 1, best.z).project(camera);
    return { sx: (v.x * 0.5 + 0.5) * innerWidth, sy: (-v.y * 0.5 + 0.5) * innerHeight };
  };
}
let frames = 0, fpsAt = last, fpsTxt = "";

function frame(now) {
  requestAnimationFrame(frame);
  let elapsed = now - last; last = now;
  if (elapsed > 200) elapsed = 200;          // clamp after tab-switch
  acc += elapsed;
  while (acc >= STEP) { update(STEP); acc -= STEP; }

  const dt = elapsed / 1000;
  if (bannerT > 0) { bannerT -= dt; bannerEl.style.opacity = Math.min(1, bannerT).toFixed(2); }
  updateCamera(dt);
  syncRender();
  projectPops(dt);
  syncHud();
  renderer.render(scene, camera);

  if (dev) {
    frames++;
    if (now - fpsAt >= 500) { fpsTxt = Math.round(frames * 1000 / (now - fpsAt)) + " fps · " + countAlive() + " rats"; frames = 0; fpsAt = now; }
    document.getElementById("dev").textContent = fpsTxt;
  }
}

// ---------------------------------------------------------------- boot
document.getElementById("startBtn").onclick = startGame;
document.getElementById("restartBtn").onclick = startGame;
// fill menu text
document.getElementById("ttl").textContent = STR.title;
document.getElementById("sub").textContent = STR.subtitle;
document.getElementById("startBtn").textContent = STR.start;
document.getElementById("howK").textContent = STR.howKbd;
document.getElementById("howP").textContent = STR.howPad;
document.getElementById("howT").textContent = STR.howTouch;
document.getElementById("restartBtn").textContent = STR.restart;
document.getElementById("ovrTtl").textContent = STR.gameOver;
document.getElementById("upTtl").textContent = STR.chooseUpgrade;
document.getElementById("upHint").textContent = STR.pickHint;

resize();
show("menuScreen");
requestAnimationFrame(frame);
