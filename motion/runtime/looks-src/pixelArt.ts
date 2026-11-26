// letitedit hand: pixel art. M.look.pixelArt.start(w, h, {cell, palette}) gives a grid of cells and the pixel artist's marks; the scene
// is written fresh by the AI. See motion\runtime\looks\pixelArt.md.
//
// Uses anidoodle's pixelArtKit (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Changed by letitedit, 4 Nov 2026: the kit is
// imported as it is; this file's Layer, disc, bands, glow, sprite, rim, text, the transparent ground and the palettes other than `night`
// are ours; the cat-and-fireflies picture and its film runner are left out; a layer is baked to one canvas pixel a cell and placed in
// whole cells through the context's transform.
import { celPlan, cleanMask, limb, PixelDraft } from "./anidoodle/pixelArtKit";
import { rng } from "./anidoodle/core";
import { eachCell, textWidth } from "./pixelFont";
import { Hand, register } from "./shared";

type Pt = [number, number];
const CLEAR = 255;   // the ground of a layer: no cell here
export const PALETTES: Record<string, string[]> = {
  night: ["#07080f", "#10152b", "#1a2446", "#283a66", "#3f5b8c", "#8ea9d0", "#e8eef5", "#0c1a17", "#16302a", "#255040", "#5b8f47", "#1c1626", "#3a2c3e", "#7a4a2e", "#e39b3a", "#ffe9a8"],
  day: ["#101820", "#2b3a55", "#4a6fa5", "#7fb2dc", "#c6e3f2", "#f7f4e6", "#2f5233", "#4f8a3f", "#94c95a", "#6b4226", "#a9713f", "#e3b27a", "#c23b3b", "#ee7f3a", "#f6cf4a", "#ffffff"],
  dusk: ["#120d1f", "#2a1b3d", "#44318d", "#7b3f8c", "#c0507f", "#f0806a", "#fcb76b", "#fdf0c4", "#14343b", "#1f6161", "#3fa58a", "#8ad6a4", "#3a2a22", "#7d5235", "#c79a62", "#ffffff"],
  mono: ["#0f1a0f", "#1f331f", "#2f4d2f", "#3f663f", "#548054", "#6e9a6e", "#8ab58a", "#a8cfa8", "#c6e8c6", "#e4ffe4", "#101010", "#2a2a2a", "#555555", "#888888", "#bbbbbb", "#ffffff"],
};

/** The draft a layer is painted on: the kit's recording grid, with marks that know about strokes and passes. */
class Draft extends PixelDraft {
  constructor(G: number, H: number) { super(G, H, CLEAR); }
  /** Bucket fill of a polygon, whole cells whose centre is inside. */
  fill(poly: Pt[], c: number) { this.begin("fill"); PixelDraft.cover(poly, this.G, this.H).forEach((i) => this.px(i % this.G, Math.floor(i / this.G), c)); this.end(); return this; }
  /** A polygon with its one-cell nubs and notches cleaned off: the pixel artist's pass over a silhouette. */
  blob(poly: Pt[], c: number) { const m = new Uint8Array(this.G * this.H); PixelDraft.cover(poly, this.G, this.H).forEach((i) => (m[i] = 1)); const o = cleanMask(m, this.G, this.H); this.begin("fill"); for (let y = 0; y < this.H; y++) for (let x = 0; x < this.G; x++) if (o[y * this.G + x]) this.px(x, y, c); this.end(); return this; }
  /** A half tint: level 0..4 of colour c over what's there, only inside the polygon. Never an alpha blend. */
  dither(poly: Pt[], c: number, level = 2) { this.begin("cluster"); PixelDraft.cover(poly, this.G, this.H).forEach((i) => { const x = i % this.G, y = Math.floor(i / this.G); if (PixelDraft.dith(x, y, level)) this.px(x, y, c); }); this.end(); return this; }
  disc(cx: number, cy: number, r: number, c: number, ry = r) { this.begin("fill"); for (let y = Math.floor(cy - ry); y <= cy + ry; y++) for (let x = Math.floor(cx - r); x <= cx + r; x++) { const u = (x + 0.5 - cx) / r, v = (y + 0.5 - cy) / ry; if (u * u + v * v <= 1) this.px(x, y, c); } this.end(); return this; }
  box(x: number, y: number, w: number, h: number, c: number) { this.begin("fill"); this.rect(Math.round(x), Math.round(y), Math.round(w), Math.round(h), c); this.end(); return this; }
  stroke(pts: Pt[], c: number, closed = false) { this.begin("pencil"); const n = pts.length; for (let i = 0; i + 1 < n + (closed ? 1 : 0); i++) { const a = pts[i], b = pts[(i + 1) % n]; this.line(a[0], a[1], b[0], b[1], c); } this.end(); return this; }
  /** Sky by rows: colours[] from y0 to y1, a 2x2 dither where one meets the next. */
  bands(y0: number, y1: number, colours: number[], x0 = 0, x1 = this.G) { const n = colours.length - 1, h = (y1 - y0) / Math.max(1, n); this.begin("fill"); for (let y = y0; y < y1; y++) { const u = (y - y0) / h, k = Math.min(n - 1, Math.floor(u)), lv = Math.floor((u - k) * 5); for (let x = x0; x < x1; x++) this.px(x, y, PixelDraft.dith(x, y, lv) ? colours[k + 1] : colours[k]); } this.end(); return this; }
  /** A light as an authored stamp: a core, a lit ring and a falloff that thins out cell by cell, colours[] from the inside out. */
  glow(cx: number, cy: number, r: number, colours: number[]) { this.begin("cluster"); const n = colours.length; for (let y = Math.floor(cy - r); y <= cy + r; y++) for (let x = Math.floor(cx - r); x <= cx + r; x++) { const d = Math.hypot(x + 0.5 - cx, y + 0.5 - cy) / r; if (d > 1) continue; const u = d * n, k = Math.min(n - 1, Math.floor(u)), lv = 4 - Math.floor((u - k) * 5); if (k === 0 || PixelDraft.dith(x, y, lv)) this.px(x, y, colours[k]); } this.end(); return this; }
  /** Laid by hand: rows of characters, map = {character: palette index}; anything else leaves the cell alone. */
  sprite(rows: string[], x: number, y: number, map: Record<string, number>, flip = false) { this.begin("pencil"); rows.forEach((row, j) => { const w = row.length; [...row].forEach((ch, i) => { const c = map[ch]; if (c !== undefined) this.px(x + (flip ? w - 1 - i : i), y + j, c); }); }); this.end(); return this; }
  /** Rim light: every painted cell whose neighbour at (dx, dy) is empty takes colour c. `only` limits it to these palette indexes. */
  rim(c: number, dx = -1, dy = -1, only?: number[]) { this.begin("cluster"); const hits: [number, number][] = []; for (let y = 0; y < this.H; y++) for (let x = 0; x < this.G; x++) { const v = this.get(x, y); if (v === CLEAR || (only && !only.includes(v))) continue; const n = this.get(x + dx, y + dy); if (n === CLEAR || n === -1) hits.push([x, y]); } hits.forEach(([x, y]) => this.px(x, y, c)); this.end(); return this; }
  /** Words in a 5 x 7 cell alphabet, k cells to a font cell. */
  text(s: string, x: number, y: number, c: number, k = 1) { this.begin("pencil"); eachCell(s, Math.round(x), Math.round(y), k, (a, b) => this.px(a, b, c)); this.end(); return this; }
}

/** One painted layer: a recorded list of cells. draw places it in whole cells; progress replays the list. */
class Layer {
  d: Draft; plan: number[]; private cv?: HTMLCanvasElement; private ctx?: CanvasRenderingContext2D; private at = -1; private fin?: HTMLCanvasElement;
  constructor(private hand: PixelHand, G: number, H: number, paint: (d: Draft) => void, budgets?: number[], rest = 2) {
    const d = (this.d = new Draft(G, H)); paint(d); d.end();
    const passes = d.strokes.reduce((a, s) => Math.max(a, s.pass), 0) + 1;
    this.plan = celPlan(d, budgets ?? Array.from({ length: passes }, () => 24), rest);
    if (this.plan[this.plan.length - 1] !== d.ops.length) this.plan.push(d.ops.length);
  }
  get G() { return this.d.G; } get H() { return this.d.H; }
  /** How many cels this layer's making has, at 10 a second by default: seconds = cels / 10. */
  get cels() { return this.plan.length; }
  private canvas() { if (!this.cv) { this.cv = document.createElement("canvas"); this.cv.width = this.G; this.cv.height = this.H; this.ctx = this.cv.getContext("2d")!; this.at = -1; } return this.ctx!; }
  private rollTo(n: number) {
    const c = this.canvas(), pal = this.hand.palette, G = this.G, ops = this.d.ops;
    if (n < this.at || this.at < 0) { c.clearRect(0, 0, G, this.H); this.at = 0; }
    for (let k = this.at; k < n; k++) { const op = ops[k], i = Math.floor(op / 16); c.fillStyle = pal[op % 16]; c.fillRect(i % G, Math.floor(i / G), 1, 1); }
    this.at = n;
  }
  private whole() { if (!this.fin) { const was = this.at; this.rollTo(this.d.ops.length); this.fin = document.createElement("canvas"); this.fin.width = this.G; this.fin.height = this.H; this.fin.getContext("2d")!.drawImage(this.cv!, 0, 0); void was; } return this.fin; }
  /** x, y in cells, rounded to whole cells; flip mirrors it; progress 0..1 lays it cel by cel in the order it was painted. */
  draw(g: CanvasRenderingContext2D, o: { x?: number; y?: number; flip?: boolean; progress?: number } = {}) {
    const p = o.progress ?? 1, k = this.hand.cell, x = Math.round(o.x ?? 0), y = Math.round(o.y ?? 0); if (p <= 0) return;
    let src: HTMLCanvasElement;
    if (p >= 1) src = this.whole();
    else { this.rollTo(this.plan[Math.min(this.plan.length - 1, Math.floor(p * this.plan.length))]); src = this.cv!; }
    g.imageSmoothingEnabled = false;
    if (o.flip) { g.save(); g.translate((x + this.G) * k, y * k); g.scale(-1, 1); g.drawImage(src, 0, 0, this.G * k, this.H * k); g.restore(); }
    else g.drawImage(src, x * k, y * k, this.G * k, this.H * k);
  }
}

class PixelHand extends Hand {
  cell: number; G: number; H: number; palette: string[]; palettes = PALETTES; limb = limb; rng = rng;
  private layers = new Map<string, Layer>();
  constructor(w: number, h: number, o: { cell?: number; palette?: string | string[] } = {}) {
    super(w, h, { scale: 1 });
    this.cell = Math.max(1, Math.round(o.cell ?? Math.max(2, Math.round(Math.max(w, h) / 160))));
    this.G = Math.ceil(w / this.cell); this.H = Math.ceil(h / this.cell);
    const pal = typeof o.palette === "string" ? PALETTES[o.palette] : o.palette ?? PALETTES.night;
    if (!pal || pal.length > 16) throw new Error("pixelArt: a palette is at most 16 colours");
    this.palette = pal;
  }
  /** A layer of cells. size = [columns, rows] (default the whole grid). budgets = cels per pass; rest = cels of rest between passes. */
  layer(id: string, paint: (d: Draft) => void, o: { size?: [number, number]; budgets?: number[]; rest?: number } = {}) {
    let L = this.layers.get(id); if (!L) { L = new Layer(this, o.size?.[0] ?? this.G, o.size?.[1] ?? this.H, paint, o.budgets, o.rest); this.layers.set(id, L); } return L;
  }
  begin(g: CanvasRenderingContext2D) { g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = "source-over"; g.imageSmoothingEnabled = false; return g; }
  /** Fills the frame with a palette colour. */
  clear(g: CanvasRenderingContext2D, c: number) { g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.fillStyle = this.palette[c]; g.fillRect(0, 0, this.w, this.h); g.restore(); }
  /** Time held in cels: rate a second, 10 by default. */
  held(t: number, rate = 10) { return Math.floor(t * rate + 1e-6) / rate; }
  /** Which pose of n: pose-to-pose, whole-cell teleports, never tweened. */
  pose(t: number, n: number, rate = 6) { return Math.floor(t * rate + 1e-6) % n; }
  /** A move in whole cells between a and b, over t0..t1, held in cels. */
  hop(t: number, a: number, b: number, t0: number, t1: number, rate = 10) { const h = this.held(t, rate), u = h <= t0 ? 0 : h >= t1 ? 1 : (h - t0) / (t1 - t0); return Math.round(a + (b - a) * u); }
  width(s: string, k = 1) { return textWidth(s, k); }
  finish(_g: CanvasRenderingContext2D) { /* no paper: machine crispness is the medium */ }
}

register("pixelArt", { start: (w: number, h: number, o?: { cell?: number; palette?: string | string[] }) => new PixelHand(w, h, o), palettes: PALETTES });
