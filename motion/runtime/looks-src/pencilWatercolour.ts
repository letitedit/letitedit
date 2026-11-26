// letitedit hand: pencil and watercolour. M.look.pencilWatercolour.start(w, h, {scale}) gives the cold-press sheet, a light lay-in, washes that
// spread from where the brush touched, painted form and graphite over the paint; the AI writes the scene. See motion\runtime\looks\pencilWatercolour.md.
//
// Adapted from anidoodle's canvas-core/ranunculus.ts and ranunculusDraw.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Those files
// have no kit: the wet front and the graphite that stops under later paint are taken out here; the core's wash and form do the paint. The flower is left out.
// Changed by letitedit, 4 Nov 2026: sizes and places are arguments; marks go on a Work (.\worked.ts, .\marks.ts).
import { GRAPHITE, PENCIL, fractal, type Ctx, type Gfx, type P } from "./anidoodle/core";
import { bounds } from "./anidoodle/gallery";
import { MarkHand, cost, lettering, plen, run, type Box } from "./marks";
import { register } from "./shared";
import type { Work } from "./worked";

const PAPER = "#fffaf3", LAY = "#8a7f86";
const PALETTE = { paper: PAPER, graphite: GRAPHITE, lay: LAY, blush: "#f6d6c6", coral: "#efb3a0", rose: "#df907f", brick: "#c77364", sage: "#c9d2aa", leaf: "#a6b48b", leafShade: "#708776", sky: "#b9d2e6", skyShade: "#86a8c8", sea: "#8fb8c9", seaShade: "#5f8ea6", butter: "#f3d577", ochre: "#d9a95a", earth: "#b08a66", earthShade: "#86664e" };

// a wet front: the brush touched at `at` and the pigment runs outward along a ragged edge
const spread = (G: Gfx, at: P, shape: P[], p: number, seed: number, fn: () => void) => {
  if (p >= 1) return fn();
  const reach = (Math.max(...shape.map(([x, y]) => Math.hypot(x - at[0], y - at[1]))) + 10) / 0.75, c = G.cur, R = reach * Math.pow(p, 0.75);
  c.save(); c.beginPath(); for (let i = 0; i < 28; i++) { const a = (i / 28) * Math.PI * 2, k = 0.75 + 0.5 * fractal(seed, Math.cos(a) * 40 + 100, Math.sin(a) * 40 + 100, 0.05, 0.05, 2), x = at[0] + Math.cos(a) * R * k, y = at[1] + Math.sin(a) * R * k; if (i) c.lineTo(x, y); else c.moveTo(x, y); } c.closePath(); c.clip(); fn(); c.restore();
};
const touchOf = (shape: P[]): P => { const b = bounds(shape); return [b.x0 + (b.x1 - b.x0) * 0.3, b.y0 + (b.y1 - b.y0) * 0.25]; };

class WatercolourHand extends MarkHand {
  palette = PALETTE;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, PENCIL); }
  /** The cold-press sheet: a plate. */
  paper(id = "paper", o: { box?: Box; color?: string } = {}) { const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }; return this.plate(id, (c) => { c.fillStyle = o.color ?? PAPER; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); }, b); }
  /** A pencil line light enough to live under paint. */
  layIn(W: Work, pts: P[], o: { closed?: boolean; seed?: number; w?: number; opacity?: number; wobble?: number } = {}) { return run(W, [{ t: cost(plen(pts)) * 0.4, d: (G, p) => G.pen(pts, { closed: o.closed, w: o.w ?? 0.85, color: LAY, opacity: o.opacity ?? 0.42, seed: o.seed ?? 3, wobble: o.wobble ?? 2, boil: 0, retrace: false, progress: p }) }], { kind: "ink" }); }
  /** A thin wash that never quite fills its outline. It spreads from `at`, where the brush touched, along a ragged wet front. */
  wash(W: Work, shape: P[], color: string, o: { alpha?: number; at?: P; seed?: number; shrink?: number; dx?: number; dy?: number; rim?: boolean; t?: number } = {}) {
    const seed = o.seed ?? 301, at = o.at ?? touchOf(shape);
    W.add(o.t ?? 90, (G, q) => G.group("paint", () => spread(G, at, shape, q, seed, () => G.wash(shape, color, { alpha: o.alpha ?? 0.4, seed, dx: o.dx ?? -2, dy: o.dy ?? -2, shrink: o.shrink ?? 0.97, rim: o.rim }))));
    return W;
  }
  /** Painted form: the shadow colour under, the lit colour pushed toward the light, one soft edge. light is an offset, [-8, -9] for upper left. hi: [x, y, rx, ry] a lifted highlight. */
  form(W: Work, shape: P[], color: string, shade: string, o: { at?: P; seed?: number; light?: P; alpha?: number; hi?: number[]; t?: number } = {}) {
    const seed = o.seed ?? 21, at = o.at ?? touchOf(shape);
    W.add(o.t ?? 60, (G, q) => G.group("paint", () => spread(G, at, shape, q, seed, () => G.form(shape, color, shade, { seed, light: o.light, alpha: o.alpha, hi: o.hi }))));
    return W;
  }
  /** Graphite over the paint. hide: shapes painted later that sit over this line: it stops under them, as a hand doesn't draw what it can't see. */
  graphite(W: Work, pts: P[], o: { closed?: boolean; seed?: number; w?: number; opacity?: number; wobble?: number; hide?: P[][] } = {}) {
    return run(W, [{ t: cost(plen(pts)) * 0.5, d: (G, p) => {
      G.pen(pts, { closed: o.closed, w: o.w ?? 1, color: GRAPHITE, opacity: o.opacity ?? 0.6, seed: o.seed ?? 22, wobble: o.wobble ?? 0.6, boil: 0, progress: p });
      if (o.hide) { const c = G.cur; c.save(); c.globalCompositeOperation = "destination-out"; c.globalAlpha = 0.94; c.fillStyle = "#000"; o.hide.forEach((e) => { c.beginPath(); e.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); c.fill(); }); c.restore(); }
    } }], { kind: "ink", chunk: 1 });
  }
  /** Capitals in pencil, stroke by stroke. */
  write(W: Work, text: string, x: number, y: number, o: { cap?: number; seed?: number; align?: "left" | "center" | "right"; w?: number; color?: string } = {}) { return run(W, [lettering(text, x, y, { cap: 24, slant: 0.1, opacity: 0.75, ...o, color: o.color ?? GRAPHITE })], { kind: "ink" }); }
  /** The sheet's tooth over the finished frame, in screen space: last thing in the frame. */
  finish(g: Ctx, o: { paper?: number; coldpress?: number } = {}) { this.grain(g, [["paper", o.paper ?? 0.12], ["coldpress", o.coldpress ?? 0.18]]); }
}

register("pencilWatercolour", { start: (w: number, h: number, o?: { scale?: number }) => new WatercolourHand(w, h, o) });
