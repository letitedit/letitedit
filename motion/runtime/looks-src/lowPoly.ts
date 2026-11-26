// letitedit hand: low-poly. M.look.lowPoly.start(w, h, {sun, ...}) gives triangle meshes, a hand-made pinhole camera, one light and a
// painter's sort; the scene is written fresh by the AI. No 3D engine. See motion\runtime\looks\lowPoly.md.
//
// Adapted from anidoodle's canvas-core/lowPoly.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Changed by letitedit, 4 Nov
// 2026: its projection, shading and perspective-friendly grid are taken from that file, with the camera, sun and colours made arguments
// and a yaw added; its lake, mountains and canoe are left out; pine, rock, sphere, box, loft, sky, cloud, water and the reflection pass
// are written for this hand from that file's description.
import { fractal, rng, type Ctx, type P } from "./anidoodle/core";
import { clamp01, Hand, register, smoothStep } from "./lowPolyShared";

type V = [number, number, number];
type Face = { v: V[]; base: V; water?: boolean; cull?: boolean };
export type Cam = { x: number; y: number; z: number; pitch?: number; yaw?: number; f?: number; cx?: number; cy?: number };

const hex = (h: string): V => [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255];
const col = (c: V | string): V => (typeof c === "string" ? hex(c) : c);
const rgb = (c: V) => `rgb(${Math.round(255 * clamp01(c[0]))},${Math.round(255 * clamp01(c[1]))},${Math.round(255 * clamp01(c[2]))})`;
const mixV = (a: V, b: V, t: number): V => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
const sub = (a: V, b: V): V => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a: V, b: V): V => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a: V): V => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const dot = (a: V, b: V) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

/** A mesh under construction; every method adds triangles and returns the mesh. Colours are "#rrggbb". */
export class Mesh {
  faces: Face[] = [];
  tri(a: V, b: V, c: V, color: string | V, o: { cull?: boolean; water?: boolean } = {}) { this.faces.push({ v: [a, b, c], base: col(color), ...o }); return this; }
  quad(a: V, b: V, c: V, d: V, color: string | V, o: { cull?: boolean } = {}) { this.tri(a, b, c, color, o); this.tri(a, c, d, color, o); return this; }
  box(x0: number, y0: number, z0: number, x1: number, y1: number, z1: number, color: string | V) {
    const A: V = [x0, y0, z0], B: V = [x1, y0, z0], C: V = [x1, y0, z1], D: V = [x0, y0, z1], E: V = [x0, y1, z0], F: V = [x1, y1, z0], G: V = [x1, y1, z1], H: V = [x0, y1, z1], o = { cull: true };
    this.quad(A, B, F, E, color, o).quad(B, C, G, F, color, o).quad(C, D, H, G, color, o).quad(D, A, E, H, color, o).quad(E, F, G, H, color, o).quad(D, C, B, A, color, o); return this;
  }
  /** A cone or a tapered column: `sides` flat sides from radius r at y to radius r2 at y + h. */
  cone(x: number, y: number, z: number, r: number, h: number, color: string | V, o: { sides?: number; r2?: number; rot?: number; seed?: number } = {}) {
    const n = o.sides ?? 6, rot = o.rot ?? 0, r2 = o.r2 ?? 0, q = rng(o.seed ?? 3), ring = (rad: number, yy: number): V[] => Array.from({ length: n }, (_, i) => { const a = rot + (i / n) * 6.2832; return [x + Math.cos(a) * rad, yy, z + Math.sin(a) * rad] as V; });
    const low = ring(r, y), top: V = [x, y + h, z], up = r2 > 0 ? ring(r2, y + h) : null;
    for (let i = 0; i < n; i++) { const a = low[i], b = low[(i + 1) % n], c = mixV(col(color), [q(), q(), q()], 0.03); if (up) this.quad(a, b, up[(i + 1) % n], up[i], c, { cull: true }); else this.tri(a, b, top, c, { cull: true }); }
    return this;
  }
  /** A pine: a trunk and three six-sided cone tiers. */
  pine(x: number, y: number, z: number, h: number, seed = 1, o: { leaf?: string; trunk?: string } = {}) {
    const r = rng(seed), rot = r() * 1.05, leaf = o.leaf ?? "#23463b"; this.cone(x, y, z, h * 0.04, h * 0.25, o.trunk ?? "#4a3426", { sides: 4, r2: h * 0.03, rot });
    [[0.14, 0.42, 0.24], [0.36, 0.38, 0.18], [0.58, 0.42, 0.12]].forEach(([b, t, w], i) => this.cone(x, y + h * b, z, h * w, h * t, mixV(col(leaf), [0.6, 0.7, 0.55], i * 0.05), { rot: rot + i * 0.5, seed: seed + i }));
    return this;
  }
  /** A faceted ball, jittered by `rough`: a planet, a rock, a head, a bush. */
  ball(x: number, y: number, z: number, r: number, color: string | V, o: { rough?: number; seed?: number; lat?: number; lon?: number; sy?: number } = {}) {
    const lat = o.lat ?? 5, lon = o.lon ?? 8, q = rng(o.seed ?? 5), rough = o.rough ?? 0, sy = o.sy ?? 1, pts: V[][] = [];
    for (let i = 0; i <= lat; i++) { const row: V[] = [], th = (i / lat) * Math.PI; for (let j = 0; j < lon; j++) { const ph = ((j + (i % 2) * 0.5) / lon) * 6.2832, k = r * (1 + (i && i < lat ? (q() - 0.5) * rough : 0)); row.push([x + Math.sin(th) * Math.cos(ph) * k, y + Math.cos(th) * k * sy, z + Math.sin(th) * Math.sin(ph) * k]); } pts.push(row); }
    for (let i = 0; i < lat; i++) for (let j = 0; j < lon; j++) { const a = pts[i][j], b = pts[i][(j + 1) % lon], c = pts[i + 1][(j + 1) % lon], d = pts[i + 1][j]; if (i > 0) this.tri(a, b, c, color, { cull: true }); if (i < lat - 1) this.tri(a, c, d, color, { cull: true }); }
    return this;
  }
  /** Lofted through rings of points (each ring the same length): a hull, a bottle, a body. */
  loft(rings: V[][], color: string | V, o: { closed?: boolean } = {}) {
    const m = rings[0].length; for (let i = 0; i + 1 < rings.length; i++) for (let j = 0; j < (o.closed === false ? m - 1 : m); j++) { const k = (j + 1) % m; this.quad(rings[i][j], rings[i][k], rings[i + 1][k], rings[i + 1][j], color); }
    return this;
  }
  /** A heightfield on a perspective-friendly grid: columns widen with distance, rows grow about 12%, jittered, so facets stay about one size on screen. color(x, y, z, up) picks a colour; up is 1 on a flat face. floor clamps the land; faces wholly under it are left out, so water below shows through. */
  terrain(o: { z0?: number; z1: number; cols?: number; near?: number; widen?: number; grow?: number; first?: number; height: (x: number, z: number) => number; color: (x: number, y: number, z: number, up: number) => string; seed?: number; floor?: number }) {
    const r = rng(o.seed ?? 77), z0 = o.z0 ?? 0, cols = o.cols ?? 40, near = o.near ?? 7, widen = o.widen ?? 0.66, floor = o.floor ?? -1e9, zs = [z0];
    while (zs[zs.length - 1] < o.z1) { const z = zs[zs.length - 1]; zs.push(z + (o.first ?? 0.55) + (o.grow ?? 0.115) * (z - z0)); }
    const grid: V[][] = zs.map((z, i) => Array.from({ length: cols + 1 }, (_, j) => { const u = -1 + (2 * (j + (j > 0 && j < cols ? (r() - 0.5) * 0.6 : 0))) / cols, zz = i > 0 && i < zs.length - 1 ? z + ((r() - 0.5) * 0.5 * (zs[i + 1] - zs[i - 1])) / 2 : z, x = u * (near + widen * (zz - z0)); return [x, Math.max(floor, o.height(x, zz)), zz] as V; }));
    for (let i = 0; i < zs.length - 1; i++) for (let j = 0; j < cols; j++) {
      const a = grid[i][j], b = grid[i][j + 1], c = grid[i + 1][j + 1], d = grid[i + 1][j], tris = r() < 0.5 ? [[a, b, c], [a, c, d]] : [[a, b, d], [b, c, d]];
      for (const t of tris) { if (t.every((q) => o.height(q[0], q[2]) <= floor)) continue; const n = norm(cross(sub(t[1], t[0]), sub(t[2], t[0]))), yc = (t[0][1] + t[1][1] + t[2][1]) / 3, xc = (t[0][0] + t[1][0] + t[2][0]) / 3, zc = (t[0][2] + t[1][2] + t[2][2]) / 3, k = 0.95 + r() * 0.1; this.tri(t[0], t[1], t[2], col(o.color(xc, yc, zc, Math.abs(n[1]))).map((v) => v * k) as V); }
    }
    return this;
  }
  /** Water: a flat jittered grid at height y, coloured near to far, reflective. Not lit; only tinted by the distance. */
  water(o: { y?: number; x0: number; x1: number; z0: number; z1: number; near?: string; far?: string; cols?: number; rows?: number; seed?: number }) {
    const y = o.y ?? 0, cols = o.cols ?? 18, rows = o.rows ?? 14, r = rng(o.seed ?? 9), near = col(o.near ?? "#2c3561"), far = col(o.far ?? "#d9a3a8"), P3 = (i: number, j: number): V => [o.x0 + ((o.x1 - o.x0) * (j + (j % cols ? (r() - 0.5) * 0.3 : 0))) / cols, y, o.z0 + (o.z1 - o.z0) * ((i / rows) ** 1.7)];
    const grid = Array.from({ length: rows + 1 }, (_, i) => Array.from({ length: cols + 1 }, (_, j) => P3(i, j)));
    for (let i = 0; i < rows; i++) for (let j = 0; j < cols; j++) { const a = grid[i][j], b = grid[i][j + 1], c = grid[i + 1][j + 1], d = grid[i + 1][j], base = mixV(near, far, ((i + 0.5) / rows) ** 1.3), k = 0.96 + r() * 0.08; this.tri(a, b, c, base.map((v) => v * k) as V, { water: true }); this.tri(a, c, d, base.map((v) => v * (0.96 + r() * 0.08)) as V, { water: true }); }
    return this;
  }
}
export type Placed = Mesh | { mesh: Mesh; x?: number; y?: number; z?: number; ry?: number; rx?: number; s?: number };
const moved = (m: Placed): Face[] => {
  if (m instanceof Mesh) return m.faces;
  const { mesh, x = 0, y = 0, z = 0, ry = 0, rx = 0, s = 1 } = m, cy = Math.cos(ry), sy = Math.sin(ry), cx = Math.cos(rx), sx = Math.sin(rx);
  const T = ([a, b, c]: V): V => { const a1 = a * s, b1 = b * s, c1 = c * s, b2 = b1 * cx - c1 * sx, c2 = b1 * sx + c1 * cx; return [x + a1 * cy + c2 * sy, y + b2, z - a1 * sy + c2 * cy]; };
  return mesh.faces.map((f) => ({ ...f, v: f.v.map(T) }));
};

class LowPolyHand extends Hand {
  sunDir: V; amb: V; sunCol: V; hazeCol: V; hazeAt: number; hazeOver: number; hex = hex; rng = rng; fractal = fractal; smoothstep = (a: number, b: number, x: number) => smoothStep((x - a) / (b - a));
  ridged = (seed: number, x: number, z: number, f: number) => { const v = 1 - Math.abs(2 * fractal(seed, x, z, f, f, 4) - 1); return v * v; };
  constructor(w: number, h: number, o: { sun?: V; ambient?: V; sunColour?: V; haze?: string; hazeAt?: number; hazeOver?: number } = {}) {
    super(w, h, { scale: 1 }); this.sunDir = norm(o.sun ?? [-0.78, 0.11, 0.62]); this.amb = o.ambient ?? [0.5, 0.52, 0.8]; this.sunCol = o.sunColour ?? [1.35, 0.82, 0.62]; this.hazeCol = hex(o.haze ?? "#c79aa6"); this.hazeAt = o.hazeAt ?? 8; this.hazeOver = o.hazeOver ?? 85;
  }
  mesh(build: (m: Mesh) => void) { const m = new Mesh(); build(m); return m; }
  private proj(c: Cam) {
    const pitch = c.pitch ?? 0, yaw = c.yaw ?? 0, cp = Math.cos(pitch), sp = Math.sin(pitch), cy = Math.cos(yaw), sy = Math.sin(yaw), f = c.f ?? Math.max(this.w, this.h) * 0.82, ox = c.cx ?? this.w / 2, oy = c.cy ?? this.h / 2;
    const view = ([x, y, z]: V): V => { const X0 = x - c.x, Y = y - c.y, Z0 = z - c.z, X = X0 * cy - Z0 * sy, Z = X0 * sy + Z0 * cy; return [X, Y * cp + Z * sp, Z * cp - Y * sp]; };
    return { view, to: (v: V): P => [ox + (f * v[0]) / v[2], oy - (f * v[1]) / v[2]] };
  }
  /** One colour for a face: its normal against the one sun plus a cool sky, hazed by distance. */
  private shade(f: Face, cam: Cam): { c: V; show: boolean } {
    const [a, b, c] = f.v; let n = norm(cross(sub(b, a), sub(c, a))); const m: V = [(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3], to: V = [cam.x - m[0], cam.y - m[1], cam.z - m[2]];
    if (f.water) return { c: f.base, show: true };
    if (dot(n, to) < 0) { if (f.cull) return { c: f.base, show: false }; n = [-n[0], -n[1], -n[2]]; }
    const d = Math.max(0, dot(n, this.sunDir)), sky = 0.55 + 0.45 * Math.max(0, n[1]), base = f.base, lit: V = [base[0] * (this.amb[0] * sky + this.sunCol[0] * d), base[1] * (this.amb[1] * sky + this.sunCol[1] * d), base[2] * (this.amb[2] * sky + this.sunCol[2] * d)];
    return { c: mixV(lit, this.hazeCol, 1 - Math.exp(-Math.max(0, Math.hypot(to[0], to[1], to[2]) - this.hazeAt) / this.hazeOver)), show: true };
  }
  /** Draws meshes through a camera, far to near. faces = 0..1 of them shaded in painter's order, wire = 0..1 of the wireframe laid first (the modeller's order). reflect mirrors everything in the water; ripples = how many cuts break it; glitter = {x, color} a sun path. */
  draw(g: Ctx, cam: Cam, list: Placed[], o: { faces?: number; wire?: number; wireColor?: string; reflect?: boolean; waterY?: number; ripples?: number; glitter?: { x: number; color?: string; w?: number }; seed?: number } = {}) {
    const { view, to } = this.proj(cam), wy = o.waterY ?? 0;
    const water: { s: P[]; c: string; z: number }[] = [], solid: { s: P[]; c: string; z: number; m?: P[]; mc?: string }[] = [];
    for (const m of list) for (const f of moved(m)) {
      const vs = f.v.map(view), z = (vs[0][2] + vs[1][2] + vs[2][2]) / 3; if (vs[0][2] < 0.2 || vs[1][2] < 0.2 || vs[2][2] < 0.2) continue;
      const q = this.shade(f, cam); if (!q.show) continue;
      const s = vs.map(to), it = { s, c: rgb(q.c), z }, off = (l: P[]) => (l[0][0] < 0 && l[1][0] < 0 && l[2][0] < 0) || (l[0][0] > this.w && l[1][0] > this.w && l[2][0] > this.w) || (l[0][1] < 0 && l[1][1] < 0 && l[2][1] < 0) || (l[0][1] > this.h && l[1][1] > this.h && l[2][1] > this.h);
      if (off(s) && !o.reflect) continue;
      if (f.water) { water.push(it); continue; }
      if (o.reflect && f.v.some((p) => p[1] > wy + 0.01)) { const mv = f.v.map(([x, y, zz]) => view([x, wy * 2 - Math.max(wy, y), zz])); if (mv.every((p) => p[2] > 0.2) && !off(mv.map(to))) solid.push({ ...it, m: mv.map(to), mc: rgb(mixV(q.c, hex("#35406a"), 0.28).map((v) => v * 0.82) as V) }); else if (!off(s)) solid.push(it); } else solid.push(it);
    }
    water.sort((a, b) => b.z - a.z); solid.sort((a, b) => b.z - a.z);
    const put = (s: P[], c: string) => { g.fillStyle = c; g.strokeStyle = c; g.beginPath(); g.moveTo(s[0][0], s[0][1]); g.lineTo(s[1][0], s[1][1]); g.lineTo(s[2][0], s[2][1]); g.closePath(); g.fill(); g.stroke(); };
    g.save(); g.lineWidth = 0.7; g.lineJoin = "round";
    const all = water.length + solid.length, wireP = o.wire ?? 0, faceP = o.faces ?? 1, shown = Math.floor(faceP * all);
    water.slice(0, shown).forEach((t) => put(t.s, t.c));
    if (faceP >= 1 && water.length) {
      g.save(); g.beginPath(); water.forEach((t) => { g.moveTo(t.s[0][0], t.s[0][1]); g.lineTo(t.s[1][0], t.s[1][1]); g.lineTo(t.s[2][0], t.s[2][1]); g.closePath(); }); g.clip();
      if (o.reflect) solid.forEach((t) => { if (t.m) put(t.m, t.mc!); });
      const r = rng(o.seed ?? 41); let y0 = 1e9, y1 = -1e9; water.forEach((t) => t.s.forEach((p) => { y0 = Math.min(y0, p[1]); y1 = Math.max(y1, p[1]); }));
      for (let i = 0; i < (o.ripples ?? 0); i++) { const u = r(), y = y0 + (y1 - y0) * u * u, L = (20 + r() * 150) * (0.3 + u), x = r() * this.w, c = water[Math.floor(r() * water.length)].c; g.fillStyle = c; g.fillRect(x, y, L, 1 + u * 2.4); }
      if (o.glitter) { g.fillStyle = o.glitter.color ?? "#fff3d6"; for (let y = y0; y < y1; y += 3 + r() * 5) { const u = (y - y0) / (y1 - y0 || 1), hw = (o.glitter.w ?? 26) + u * (o.glitter.w ?? 26) * 3, n = 1 + Math.floor(r() * 2); for (let i = 0; i < n; i++) g.fillRect(o.glitter.x + (r() - 0.5) * 2 * hw, y, 4 + r() * 16 * (0.3 + u), 1 + u); } }
      g.restore();
    }
    solid.slice(0, Math.max(0, shown - water.length)).forEach((t) => put(t.s, t.c));
    if (wireP > 0) {   // the modeller's wireframe over what isn't shaded yet
      const seq = [...water, ...solid], n = Math.floor(wireP * seq.length); g.strokeStyle = o.wireColor ?? "#8fa3c8"; g.lineWidth = 0.7; g.globalAlpha = 0.55; g.beginPath();
      for (let i = shown; i < n; i++) { const s = seq[i].s; g.moveTo(s[0][0], s[0][1]); g.lineTo(s[1][0], s[1][1]); g.lineTo(s[2][0], s[2][1]); g.closePath(); } g.stroke();
    }
    g.restore();
  }
  /** Baked once: for a camera that doesn't move. paint gets a context; draw(g) places the picture. */
  still(id: string, paint: (c: Ctx) => void) { return this.plate(id, paint); }
  /** A sky of 2D facets: a jittered grid coloured by height, with stops = [[0, "#top"], ..., [1, "#low"]] and a warmer glow near sun = [x, y]. */
  sky(id: string, stops: [number, string][], o: { sun?: P; glow?: string; reach?: number; cell?: number; seed?: number; box?: { x0: number; y0: number; x1: number; y1: number } } = {}) {
    const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, cell = o.cell ?? Math.round(Math.max(this.w, this.h) / 14), reach = o.reach ?? Math.max(this.w, this.h) * 0.42, ramp = (u: number): V => { let i = 0; while (i < stops.length - 2 && u > stops[i + 1][0]) i++; const [a, ca] = stops[i], [e, cb] = stops[i + 1]; return mixV(hex(ca), hex(cb), clamp01((u - a) / (e - a || 1))); };
    return this.plate(id, (c) => {
      c.fillStyle = rgb(ramp(0.5)); c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); const r = rng(o.seed ?? 12), nx = Math.ceil((b.x1 - b.x0) / cell) + 2, ny = Math.ceil((b.y1 - b.y0) / cell) + 2;
      const pt = Array.from({ length: ny + 1 }, (_, j) => Array.from({ length: nx + 1 }, (_, i) => [b.x0 + (i - 1 + (r() - 0.5) * 0.7) * cell, b.y0 + (j - 1 + (r() - 0.5) * 0.7) * cell] as P));
      const tri = (A: P, B: P, C: P) => { const mx = (A[0] + B[0] + C[0]) / 3, my = (A[1] + B[1] + C[1]) / 3; let v = ramp(clamp01((my - b.y0) / (b.y1 - b.y0))); if (o.sun) v = mixV(v, hex(o.glow ?? "#ffd9a8"), 0.85 * Math.exp(-((Math.hypot(mx - o.sun[0], my - o.sun[1]) / reach) ** 2) * 2)); const k = 0.985 + r() * 0.03, s = rgb(v.map((q) => q * k) as V); c.fillStyle = s; c.strokeStyle = s; c.lineWidth = 0.8; c.beginPath(); c.moveTo(A[0], A[1]); c.lineTo(B[0], B[1]); c.lineTo(C[0], C[1]); c.closePath(); c.fill(); c.stroke(); };
      for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) { const a = pt[j][i], e = pt[j][i + 1], d = pt[j + 1][i + 1], f = pt[j + 1][i]; if (r() < 0.5) { tri(a, e, d); tri(a, d, f); } else { tri(a, e, f); tri(e, d, f); } }
    }, b);
  }
  /** A faceted flat cloud, lit from below when `under` is warmer than `over`. */
  cloud(c: Ctx, cx: number, cy: number, w: number, h: number, o: { over?: string; under?: string; seed?: number; n?: number } = {}) {
    const r = rng(o.seed ?? 7), n = o.n ?? 9, top: P[] = Array.from({ length: n + 1 }, (_, i) => { const u = i / n; return [cx - w / 2 + w * u, cy - h * Math.sin(u * Math.PI) * (0.55 + r() * 0.5)]; }), low: P[] = Array.from({ length: n + 1 }, (_, i) => [cx - w / 2 + (w * i) / n, cy + (r() - 0.5) * h * 0.14] as P), a = hex(o.under ?? "#f4b49b"), b = hex(o.over ?? "#8f7fa8");
    for (let i = 0; i < n; i++) { [[low[i], low[i + 1], top[i + 1]], [low[i], top[i + 1], top[i]]].forEach((t, k) => { const s = rgb(mixV(a, b, (k ? 0.75 : 0.25) + (r() - 0.5) * 0.3)); c.fillStyle = s; c.strokeStyle = s; c.lineWidth = 0.7; c.beginPath(); c.moveTo(t[0][0], t[0][1]); c.lineTo(t[1][0], t[1][1]); c.lineTo(t[2][0], t[2][1]); c.closePath(); c.fill(); c.stroke(); }); }
  }
  /** The empty viewport: a dark ground and a grid, where a modeller starts. */
  viewport(g: Ctx, o: { bg?: string; line?: string; gap?: number } = {}) { const gap = o.gap ?? Math.round(this.w / 20); g.save(); g.fillStyle = o.bg ?? "#14171f"; g.fillRect(0, 0, this.w, this.h); g.strokeStyle = o.line ?? "#262c3a"; g.lineWidth = 1; g.beginPath(); for (let x = 0; x <= this.w; x += gap) { g.moveTo(x, 0); g.lineTo(x, this.h); } for (let y = 0; y <= this.h; y += gap) { g.moveTo(0, y); g.lineTo(this.w, y); } g.stroke(); g.restore(); }
  finish(_g: Ctx) { /* no paper, no grain: the triangulation is the only texture */ }
}

register("lowPoly", { start: (w: number, h: number, o?: ConstructorParameters<typeof LowPolyHand>[2]) => new LowPolyHand(w, h, o) });
