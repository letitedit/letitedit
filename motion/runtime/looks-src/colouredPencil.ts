// letitedit hand: coloured pencil. M.look.colouredPencil.start(w, h, {scale}) gives the cream sheet, one-direction hatching punched by the
// sheet's tooth, contours and a lay-in; the AI writes the scene. See motion\runtime\looks\colouredPencil.md.
//
// Uses anidoodle's canvas-core/colouredPencilKit.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77) for the strokes.
// Changed by letitedit, 4 Nov 2026: the tooth is a repeating tile turned to the hatch's angle, not one field per sheet, so it costs the same
// on any frame; its tin, crow and film runner are left out; marks go on a Work (.\worked.ts, .\marks.ts).
import { PENCIL, fractal, type Ctx, type Env, type Gfx, type Layer, type P } from "./anidoodle/core";
import { Sheet, contour, cutMark, dot, edgeDist, ellipseR, fillMark, hatch, layLine, minus, poly, smoothstep, union, type Mark, type Region } from "./anidoodle/colouredPencilKit";
import { clamp } from "./anidoodle/gallery";
import { MarkHand, drawn, type Box, type Mk } from "./marks";
import { register } from "./shared";
import type { Work } from "./worked";

const ANG = -1.02, X2 = 0.22, LEVELS = [0.53, 0.575, 0.645], TILE = 512, PAPER = "#f3ecdc";
const PALETTE = { paper: PAPER, graphite: "#4a4346", sepia: "#4b3a30", indigo: "#34407e", dusk: "#6d78ad", violet: "#7f6aa8", rose: "#d98b94", sky: "#8fb2d6", teal: "#4c9a9b", grass: "#7f9f52", moss: "#566e3a", ochre: "#c9973f", wood: "#9c5f35", brick: "#b5432f", red: "#c5382f", yellow: "#efc53f", amber: "#e39a35", black: "#2a2628" };

// the tooth: a repeating field streaked along the hatch, at three pressures. Light pressure lands on few ridges, burnished on most.
const toothTile = (env: Env, level: number): Layer => {
  const key = `cp:tile:${level}:${env.scale}`; let L = env.cache.get(key) as Layer | undefined; if (L) return L;
  const n = Math.round(TILE * env.scale); L = env.canvas(n, n);
  const img = L.ctx.createImageData(n, n), d = img.data, T = LEVELS[level];
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) { const lx = x / env.scale, ly = y / env.scale, f = 0.62 * fractal(71, lx, ly, 0.12, 0.62, 2, TILE) + 0.38 * fractal(73, lx, ly, 0.8, 0.8, 1, TILE); d[(y * n + x) * 4 + 3] = 255 * clamp((T - f) * 11 + 0.5); }
  L.ctx.putImageData(img, 0, 0); env.cache.set(key, L); return L;
};
// marks on their own layer, punched by the tooth, then laid on the sheet: one field under every pass is what makes it read as pencil
const punched = (G: Gfx, marks: Mk[], total: number, q: number, box: Box, level: number, ang: number) => {
  const k = G.env.scale, L = G.layer(), c = L.ctx, pad = 6, r: [number, number, number, number] = [Math.max(0, Math.floor((box.x0 - pad) * k)), Math.max(0, Math.floor((box.y0 - pad) * k)), Math.min(c.canvas.width, Math.ceil((box.x1 + pad) * k)), Math.min(c.canvas.height, Math.ceil((box.y1 + pad) * k))];
  if (r[2] <= r[0] || r[3] <= r[1]) { G.release(L, null); return; }
  c.setTransform(k, 0, 0, k, 0, 0); const prev = G.cur; G.cur = c; drawn(G, marks, total, q); G.cur = prev;
  c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 1; c.globalCompositeOperation = "destination-in";
  const pat = c.createPattern(toothTile(G.env, level).canvas as CanvasImageSource, "repeat")!; pat.setTransform(new DOMMatrix().rotate((ang * 180) / Math.PI)); c.fillStyle = pat;
  c.save(); c.beginPath(); c.rect(r[0], r[1], r[2] - r[0], r[3] - r[1]); c.clip(); c.fillRect(0, 0, c.canvas.width, c.canvas.height); c.restore(); c.globalCompositeOperation = "source-over";
  const m = G.main; m.save(); m.setTransform(1, 0, 0, 1, 0, 0); m.drawImage(L.canvas as CanvasImageSource, r[0], r[1], r[2] - r[0], r[3] - r[1], r[0], r[1], r[2] - r[0], r[3] - r[1]); m.restore();
  G.release(L, r);
};
const toMk = (m: Mark): Mk => ({ t: m.len + 7, d: (G, p) => { if (p > 0) fillMark(G.cur, m, p >= 1 ? m.poly : cutMark(m, p)); } });
const addMarks = (W: Work, list: Mark[], level: number, ang: number) => {
  for (let i = 0; i < list.length; i += 40) {
    const part = list.slice(i, i + 40), marks = part.map(toMk), total = marks.reduce((a, m) => a + m.t, 0); let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    part.forEach((m) => m.c.forEach(([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }));
    W.add(total, (G, q) => punched(G, marks, total, q, { x0, y0, x1, y1 }, level, ang));
  }
  return W;
};
const asRegion = (s: P[] | Region): Region => (Array.isArray(s) ? poly(s) : s);

class PencilHand extends MarkHand {
  palette = PALETTE; ANG = ANG; X2 = X2; edgeDist = edgeDist; smoothstep = smoothstep;
  region = poly; union = union; minus = minus; ellipse = ellipseR;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, PENCIL); }
  /** The cream cartridge sheet: a plate. */
  paper(id = "paper", o: { box?: Box; color?: string } = {}) { const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }; return this.plate(id, (c) => { c.fillStyle = o.color ?? PAPER; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); }, b); }
  /** A patch of hatching: short flicked strokes side by side at one angle, stopping where the shape stops. dens(x, y) 0..1 is pressure and coverage. press 0 light, 1 medium, 2 burnished. */
  hatching(W: Work, shape: P[] | Region, o: { col: string; ang?: number; gap?: number; len?: number; w?: number; a?: number; seed?: number; dens?: (x: number, y: number) => number; jit?: number; strip?: number; over?: number; press?: 0 | 1 | 2 }) {
    const S = new Sheet().pass("x", o.press ?? 1), ang = o.ang ?? ANG;
    hatch(S, asRegion(shape), { ang, gap: o.gap ?? 3, len: o.len ?? 34, w: o.w ?? 1.5, col: o.col, a: o.a ?? 0.72, seed: o.seed ?? 1, dens: o.dens, jit: o.jit, strip: o.strip, over: o.over });
    return addMarks(W, S.passes[0].marks, o.press ?? 1, ang);
  }
  /** Darks: the same hatching in the second direction. Never a fill. */
  cross(W: Work, shape: P[] | Region, o: { col: string; gap?: number; len?: number; w?: number; a?: number; seed?: number; dens?: (x: number, y: number) => number; press?: 0 | 1 | 2 }) { return this.hatching(W, shape, { press: 2, ...o, ang: X2 }); }
  /** A thin broken contour, drawn last: overlapping pieces. keep(x, y) false loses the edge where the light eats it. */
  contour(W: Work, pts: P[], o: { col?: string; w?: number; a?: number; seed?: number; seg?: number; keep?: (x: number, y: number) => boolean; closed?: boolean; skip?: number; smooth?: boolean } = {}) {
    const S = new Sheet().pass("x", 2); contour(S, pts, { w: o.w ?? 1.2, col: o.col ?? PALETTE.sepia, a: o.a ?? 0.8, seed: o.seed ?? 1, seg: o.seg, keep: o.keep, closed: o.closed, skip: o.skip, smooth: o.smooth });
    return addMarks(W, S.passes[0].marks, 2, ANG);
  }
  /** Faint construction lines ruled freehand, running past both ends. */
  layIn(W: Work, a: P, b: P, o: { col?: string; seed?: number; w?: number; alpha?: number } = {}) { const S = new Sheet().pass("x", 0); layLine(S, a, b, o.col ?? PALETTE.graphite, o.seed ?? 1, o.w, o.alpha); return addMarks(W, S.passes[0].marks, 0, ANG); }
  /** A tiny dark dot, the pencil twisted: a rivet, a pupil. */
  dot(W: Work, x: number, y: number, rad: number, o: { col?: string; a?: number } = {}) { const S = new Sheet().pass("x", 2); dot(S, x, y, rad, o.col ?? PALETTE.black, o.a ?? 0.9); return addMarks(W, S.passes[0].marks, 2, ANG); }
  /** The sheet's grain over the finished frame, in screen space: last thing in the frame. */
  finish(g: Ctx, o: { paper?: number } = {}) { this.grain(g, [["paper", o.paper ?? 0.07]]); }
}

register("colouredPencil", { start: (w: number, h: number, o?: { scale?: number }) => new PencilHand(w, h, o) });
