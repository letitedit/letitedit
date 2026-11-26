// letitedit hand: isometric cutaway. M.look.isometric.start(w, h) gives a true 2:1 grid and flat planes with three tones per material; the
// scene is written fresh by the AI. See motion\runtime\looks\isometric.md.
//
// Uses anidoodle's isometricKit (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Changed by letitedit, 4 Nov 2026: the kit is
// imported as it is and its material table taken from canvas-core/isometric.ts; the bakery picture and film runner are left out; plan(),
// the stage schedule, the warm light rule in bands, panel(), figure() and the dome and cylinder regions are written for this hand from
// that file's description.
import { clamp01, ease, Iso, span, ZK, type Mat, type P2, type P3 } from "./anidoodle/isometricKit";
import type { Ctx } from "./anidoodle/core";
import { mix } from "./anidoodle/gallery";
import { advance, glyph, measure, type Face } from "./anidoodle/scrapbookKit";
import { Hand, register } from "./shared";

const dim = (h: string, f: number) => "#" + [1, 3, 5].map((i) => Math.round(parseInt(h.slice(i, i + 2), 16) * f).toString(16).padStart(2, "0")).join("");
/** Three tones from one colour: top lightest, +y face middle, +x face darkest. */
export const material = (c: string, o: { top?: number; right?: number } = {}): Mat => ({ top: mix(c, "#ffffff", o.top ?? 0.16), left: c, right: dim(c, o.right ?? 0.78) });
export const MATERIALS: Record<string, Mat> = {
  plaster: { top: "#c9bba0", left: "#a99b82", right: "#8b806e" }, cut: { top: "#4d3b35", left: "#3f302b", right: "#332723" }, tile: { top: "#94593f", left: "#6f3f2c", right: "#5a3223" },
  wood: { top: "#9a7350", left: "#7a5839", right: "#624630" }, darkwood: { top: "#6a4f3e", left: "#533d31", right: "#422f27" }, brick: { top: "#a9573a", left: "#8a432a", right: "#6f3522" },
  stone: { top: "#bdb3a2", left: "#9a9080", right: "#7e7567" }, crust: { top: "#dc9d52", left: "#b87a33", right: "#935d24" }, sack: { top: "#cdbf9f", left: "#b09f7c", right: "#92835f" }, iron: { top: "#5d5f6b", left: "#474955", right: "#373843" },
};
const WORD: Face = { weight: 0.16, cap: "butt", join: "miter" };
type Item = { stage: number; make: (iso: Iso, p: number) => void; a?: number; b?: number; until?: number };
type Light = { x: number; y: number; z: number; color?: string; reach?: number; alpha?: number };

/** A cutaway under construction. Every method adds items to the plan, drawn in the order written; `stage` says when it is made. */
class Build {
  items: Item[] = [];
  constructor(private light?: Light) {}
  add(stage: number, make: (iso: Iso, p: number) => void) { this.items.push({ stage, make }); return this; }
  /** The iso grid ruled across the ground, x0..x1 by y0..y1, drawn line by line. */
  grid(stage: number, x0: number, y0: number, x1: number, y1: number, color = "#333d57", z = 0) { return this.add(stage, (iso, p) => { const n = x1 - x0 + (y1 - y0) + 2, m = Math.floor(n * p); let k = 0; for (let x = x0; x <= x1 && k < m; x++, k++) iso.line(iso.p(x, y0, z), iso.p(x, y1, z), color, 1); for (let y = y0; y <= y1 && k < m; y++, k++) iso.line(iso.p(x0, y, z), iso.p(x1, y, z), color, 1); }); }
  /** A box: pen-traced, then filled. Light reaches it if the plan has one, unless unlit. */
  box(stage: number, x0: number, y0: number, z0: number, x1: number, y1: number, z1: number, m: Mat, o: { unlit?: boolean } = {}) {
    this.add(stage, (iso, p) => iso.make(iso.boxFaces(x0, y0, z0, x1, y1, z1, m), p, m.right));
    if (this.light && !o.unlit) this.warm(x0, y0, z0, x1, y1, z1);
    return this;
  }
  /** One flat plane through world points. */
  face(stage: number, pts: P3[], color: string, alpha = 1) { return this.add(stage, (iso, p) => { if (alpha < 1) iso.ctx.globalAlpha = 1; if (alpha < 1) { if (p > 0) iso.face(pts, color, alpha * ease(p)); return; } iso.make([{ pts: pts.map((q) => iso.p(...q)), fill: color }], p, color); }); }
  /** A translucent construction block, gone once the walls are up: stage = when it shows, until = when it has gone. */
  massing(stage: number, until: number, x0: number, y0: number, z0: number, x1: number, y1: number, z1: number, color = "#6f8cc4") { this.items.push({ stage, make: (iso, p) => { const q = p * (p < 0.5 ? 2 : 2 - 2 * p); if (q <= 0) return; iso.boxFaces(x0, y0, z0, x1, y1, z1, { top: color, left: color, right: color }).forEach((f) => iso.poly(f.pts, f.fill, 0.28 * q)); }, until }); return this; }
  /** A flat 2:1 hairline: tile joints, brick courses, plank lines. */
  line(stage: number, a: P3, b: P3, color: string, w = 1, alpha = 1) { return this.add(stage, (iso, p) => { const A = iso.p(...a), B = iso.p(...b); iso.line(A, [A[0] + (B[0] - A[0]) * p, A[1] + (B[1] - A[1]) * p], color, w, alpha); }); }
  /** A cast shadow: one flat shape, one alpha. */
  shadow(stage: number, pts: P3[], alpha = 0.38, color = "#0e1119") { return this.add(stage, (iso, p) => iso.face(pts, color, alpha * ease(p))); }
  /** A pool of light on a floor: flat ellipses stepped in bands, no gradient. */
  pool(stage: number, cx: number, cy: number, z: number, r: number, color = "#ffb04a", bands = 3, alpha = 0.32) { return this.add(stage, (iso, p) => { for (let i = 0; i < bands; i++) { const R = r * (1 - i / bands) * ease(p), pts: P3[] = Array.from({ length: 28 }, (_, k) => { const a = (k / 28) * 6.2832; return [cx + Math.cos(a) * R, cy + Math.sin(a) * R, z] as P3; }); iso.face(pts, color, alpha); } }); }
  /** An upright cylinder by the cube rule: three flat regions, split where the curve turns, and a top. */
  cylinder(stage: number, cx: number, cy: number, z0: number, z1: number, r: number, m: Mat) { return this.add(stage, (iso, p) => { const pz = z0 + (z1 - z0) * ease(p), ring = (z: number, a0: number, a1: number): P3[] => Array.from({ length: 17 }, (_, k) => { const a = a0 + ((a1 - a0) * k) / 16; return [cx + Math.cos(a) * r, cy + Math.sin(a) * r, z] as P3; }); const side = (a0: number, a1: number, c: string) => iso.face([...ring(z0, a0, a1), ...ring(pz, a0, a1).reverse()], c); side(-0.785, 0.785, m.right); side(0.785, 2.356, m.left); iso.face(ring(pz, 0, 6.2832), m.top); }); }
  /** A dome on a ring: three flat regions by the cube rule and an up-facing cap. */
  dome(stage: number, cx: number, cy: number, z: number, r: number, m: Mat) { return this.add(stage, (iso, p) => { const lat = (e: number, a0: number, a1: number): P3[] => Array.from({ length: 13 }, (_, k) => { const a = a0 + ((a1 - a0) * k) / 12; return [cx + Math.cos(a) * r * Math.cos(e), cy + Math.sin(a) * r * Math.cos(e), z + r * Math.sin(e) * ease(p)] as P3; }); const reg = (a0: number, a1: number, c: string) => iso.face([...lat(0, a0, a1), ...lat(0.95, a0, a1).reverse()], c); reg(-0.785, 0.785, m.right); reg(0.785, 2.356, m.left); iso.face(lat(0.95, 0, 6.2832), m.top); }); }
  /** Paint flat on a plane: side = "top", "left" (+y face) or "right" (+x face), (x, y, z) its top-left corner, w and h in world units; paint(c) works in world units with y running down the plane. For a screen, a sign, a poster, tiles. */
  panel(stage: number, side: "top" | "left" | "right", x: number, y: number, z: number, w: number, h: number, paint: (c: Ctx, w: number, h: number) => void) { return this.add(stage, (iso, p) => { if (p <= 0) return; const c = iso.ctx; c.save(); onPlane(iso, side, x, y, z); c.beginPath(); c.rect(0, 0, w, h * p); c.clip(); paint(c, w, h); c.restore(); c.globalAlpha = 1; }); }
  /** Words laid flat on a plane, stroked letters. cap in world units; origin as panel. */
  text(stage: number, side: "top" | "left" | "right", x: number, y: number, z: number, text: string, o: { cap?: number; color?: string; face?: Face } = {}) { const cap = o.cap ?? 0.5, f = o.face ?? WORD; return this.add(stage, (iso, p) => { if (p <= 0) return; const c = iso.ctx; c.save(); onPlane(iso, side, x, y, z); let xx = 0; const n = Math.ceil([...text].length * p); [...text].slice(0, n).forEach((ch) => { glyph(c, ch, xx, 0, cap, f, o.color ?? "#1b2030"); xx += advance(ch, f) * (cap / 6); }); c.restore(); c.globalAlpha = 1; }); }
  /** A person at a foot point: 7.5 heads, three tones per garment, authored in screen space over the projected point. height in world z units. */
  figure(stage: number, x: number, y: number, z: number, o: { height?: number; skin?: string; top?: string; legs?: string; hair?: string; face?: -1 | 1; reach?: number } = {}) { return this.add(stage, (iso, p) => { if (p <= 0) return; const [fx, fy] = iso.p(x, y, z), H = (o.height ?? 2.2) * ZK * iso.u, U = H / 7.5, dir = o.face ?? 1, c = iso.ctx, top = material(o.top ?? "#3f6c8e"), legs = material(o.legs ?? "#2e3442"), skin = material(o.skin ?? "#d9a07a"), hair = o.hair ?? "#2b211c"; const q = (pts: number[][], col: string) => iso.poly(pts.map(([a, b]) => [fx + a * U * dir, fy - b * U] as P2), col); c.save(); c.globalAlpha = clamp01(p * 3);
    iso.poly(Array.from({ length: 14 }, (_, k) => { const a = (k / 14) * 6.2832; return [fx + 0.32 * U + Math.cos(a) * U * 0.9, fy + Math.sin(a) * U * 0.42] as P2; }), "#0e1119", 0.25);
    q([[-0.55, 0], [-0.08, 0], [-0.02, 3.6], [-0.62, 3.6]], legs.right); q([[0.08, 0], [0.55, 0], [0.62, 3.6], [0.02, 3.6]], legs.left); q([[-0.62, 3.5], [0.62, 3.5], [0.85, 6.3], [-0.85, 6.3]], top.left); q([[0.1, 3.5], [0.62, 3.5], [0.85, 6.3], [0.1, 6.3]], top.right); q([[-0.85, 6.25], [0.85, 6.25], [0.7, 6.55], [-0.7, 6.55]], top.top);
    const r = o.reach ?? 0; q([[0.72, 6.2], [1.05, 6.1], [1.05 + 0.4 * r + 0.15, 4.2 + r * 1.2], [0.75 + 0.4 * r, 4.1 + r * 1.2]], top.right); q([[-0.72, 6.2], [-1.0, 6.1], [-1.05, 4.1], [-0.72, 4.05]], top.left);
    q([[-0.2, 6.5], [0.2, 6.5], [0.2, 6.75], [-0.2, 6.75]], skin.right); iso.poly(Array.from({ length: 18 }, (_, k) => { const a = (k / 18) * 6.2832; return [fx + Math.cos(a) * U * 0.48 * dir, fy - 7.0 * U + Math.sin(a) * U * 0.55] as P2; }), skin.left); iso.poly(Array.from({ length: 12 }, (_, k) => { const a = -0.3 - (k / 11) * 2.54; return [fx + Math.cos(a) * U * 0.52 * dir, fy - 7.0 * U + Math.sin(a) * U * 0.6] as P2; }), hair); c.restore(); }); }
  /** Faces of a box that can see the plan's light take one flat tint, stepped in three distance bands. Added by box() unless unlit. */
  private warm(x0: number, y0: number, z0: number, x1: number, y1: number, z1: number) {
    const L = this.light!, reach = L.reach ?? 6, band = (cx: number, cy: number, cz: number) => { const d = Math.hypot(cx - L.x, cy - L.y, cz - L.z) / reach; return d > 1 ? 0 : d > 0.66 ? 1 : d > 0.33 ? 2 : 3; }, A = (L.alpha ?? 0.16), col = L.color ?? "#ffb04a", cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, cz = (z0 + z1) / 2;
    this.items.push({ stage: 1e6, make: (iso, p) => { const q = ease(p); if (q <= 0) return; const f = iso.boxFaces(x0, y0, z0, x1, y1, z1, { top: col, left: col, right: col }), see = [L.y > y1, L.x > x1, L.z > z1], at: [number, number, number][] = [[cx, y1, cz], [x1, cy, cz], [cx, cy, z1]]; f.forEach((face, i) => { if (!see[i]) return; const b = band(...at[i]); if (b) iso.poly(face.pts, face.fill, A * b * q); }); } });
  }
}
const onPlane = (iso: Iso, side: "top" | "left" | "right", x: number, y: number, z: number) => {
  const c = iso.ctx, [px, py] = iso.p(x, y, z), u = iso.u;
  if (side === "top") c.transform(u, u / 2, -u, u / 2, px, py); else if (side === "left") c.transform(u, u / 2, 0, ZK * u, px, py); else c.transform(u, -u / 2, 0, ZK * u, px, py);
};

/** A cutaway: every item, painter's order as written, each made when its stage comes up. progress 0..1. */
class Plan {
  private items: Item[]; private fin?: HTMLCanvasElement;
  constructor(private hand: IsoHand, build: Build, public o: { u: number; ox: number; oy: number }) {
    this.items = build.items; const stages = [...new Set(this.items.filter((i) => i.until === undefined).map((i) => i.stage))].sort((x, y) => x - y), n = stages.length || 1, at = (st: number) => { const i = stages.findIndex((v) => v >= st); return (i < 0 ? n : i) / n; };
    stages.forEach((st, k) => { const list = this.items.filter((i) => i.stage === st && i.until === undefined), m = list.length, w = 1 / n, d = Math.max(0.7 / Math.max(1, m), 0.25) * w; list.forEach((it, j) => { it.a = (k + (j / Math.max(1, m)) * 0.75) * w; it.b = it.a + d; }); });
    this.items.forEach((it) => { if (it.until !== undefined) { it.a = at(it.stage); it.b = Math.max(it.a + 0.01, at(it.until)); } });
  }
  private paint(c: Ctx, p: number) { const iso = new Iso(c, this.o.u, this.o.ox, this.o.oy); for (const it of this.items) { const q = p >= 1 ? 1 : span(p, it.a!, it.b!); if (q > 0) it.make(iso, q); } }
  draw(g: Ctx, o: { progress?: number; x?: number; y?: number; alpha?: number } = {}) {
    const p = o.progress ?? 1; if (p <= 0) return; g.save(); if (o.x || o.y) g.translate(o.x ?? 0, o.y ?? 0); if (o.alpha !== undefined) g.globalAlpha *= o.alpha;
    if (p >= 1) { if (!this.fin) { this.fin = document.createElement("canvas"); this.fin.width = this.hand.w; this.fin.height = this.hand.h; this.paint(this.fin.getContext("2d")!, 1); } g.drawImage(this.fin, 0, 0, this.hand.w, this.hand.h); }
    else this.paint(g, p);
    g.restore();
  }
}

class IsoHand extends Hand {
  Iso = Iso; MATERIALS = MATERIALS; material = material; mix = mix; dim = dim; ZK = ZK; measure = measure;
  constructor(w: number, h: number, o: { scale?: number } = {}) { super(w, h, { scale: 1, ...o }); }
  /** Where the grid's origin sits, for a world this many units across and tall. */
  fit(x: number, y: number, z = 0, o: { margin?: number; cx?: number; cy?: number } = {}) { const m = o.margin ?? 0.88, wide = x + y, tall = (x + y) / 2 + z * ZK, u = Math.min((this.w * m) / wide, (this.h * m) / tall), ox = (o.cx ?? this.w / 2) - ((x - y) * u) / 2, oy = (o.cy ?? this.h / 2) - ((x + y) * u) / 4 + (z * ZK * u) / 2; return { u, ox, oy }; }
  /** A cutaway, built once. grid = {u, ox, oy} (see fit). light = {x, y, z, color, reach, alpha}: the one light, poured last. */
  plan(_id: string, grid: { u: number; ox: number; oy: number }, build: (b: Build) => void, o: { light?: Light } = {}) { const b = new Build(o.light); build(b); return new Plan(this, b, grid); }
  /** A direct Iso on this frame's context, for something moving: iso.make(iso.boxFaces(...), 1, edge), iso.face, iso.line, iso.p. */
  iso(g: Ctx, grid: { u: number; ox: number; oy: number }) { return new Iso(g, grid.u, grid.ox, grid.oy); }
  finish(_g: Ctx) { /* vector-crisp: no paper, no grain */ }
}

register("isometric", { start: (w: number, h: number, o?: { scale?: number }) => new IsoHand(w, h, o), MATERIALS, material });
