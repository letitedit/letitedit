// letitedit hand: ballpoint sketch. M.look.ballpoint.start(w, h, {scale}) gives the sheet and the pen; the AI writes the scene.
// See motion\runtime\looks\ballpoint.md.
//
// Adapted from anidoodle's canvas-core/pocketWatch.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). That file has no kit:
// its stroke, bead and hatch are taken out here with their sizes as arguments, and its watch and film clock are left out.
// Changed by letitedit, 4 Nov 2026: tone(), solid() and write() are ours; marks go on a Work (.\worked.ts, .\marks.ts).
import { rng, type Ctx, type Gfx, type Medium, type P } from "./anidoodle/core";
import { bounds, fillShape, lerpP } from "./anidoodle/gallery";
import { MarkHand, cost, hatchPieces, lettering, plen, ragged, run, type Box, type Mk, type ToneFn } from "./marks";
import { register } from "./shared";
import type { Work } from "./worked";

const BIRO = "#23379f", PAPER = "#f6f2e6";
const BIRO_M: Medium = { nib: 0.98, taper: 0.12, pressure: 0.1, retrace: true, wobble: 1.15, rough: 0.3 };
type LineO = { w?: number; op?: number; seed?: number; wob?: number; bead?: boolean; retrace?: boolean; color?: string; closed?: boolean };

const stroke = (pts: P[], o: LineO): Mk => {
  const { w = 1.1, op = 0.86, seed = 1, wob = 0.35, retrace = false, bead = false, color = BIRO, closed = false } = o;
  return { t: cost(plen(pts)), d: (G, p) => {
    if (p <= 0) return;
    G.pen(pts, { w, color, seed, wobble: wob, boil: 0, taper: 1, opacity: op, retrace, closed, progress: p });
    if (bead && p >= 1) { const e = pts[pts.length - 1], s0 = pts[0], c = G.cur, r = rng(seed * 7); G.touch(e[0] - 4, e[1] - 4, e[0] + 4, e[1] + 4); G.touch(s0[0] - 3, s0[1] - 3, s0[0] + 3, s0[1] + 3); c.fillStyle = color; c.globalAlpha = 0.8; c.beginPath(); c.arc(e[0] + (r() - 0.5), e[1] + (r() - 0.5), 1.2 + r() * 0.8, 0, Math.PI * 2); c.fill(); c.globalAlpha = 0.5; c.beginPath(); c.arc(s0[0], s0[1], 0.8 + r() * 0.5, 0, Math.PI * 2); c.fill(); c.globalAlpha = 1; }
  } };
};

class BallpointHand extends MarkHand {
  palette = { ink: BIRO, paper: PAPER };
  ragged = ragged;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, BIRO_M); }
  /** The cream sheet: a plate. box may be larger than the frame, for a camera. */
  paper(id = "paper", o: { box?: Box; color?: string } = {}) { const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }; return this.plate(id, (c) => { c.fillStyle = o.color ?? PAPER; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); }, b); }
  /** One line of the pen. bead: the blob a firm stroke leaves where the ball stops. pts are smoothed. */
  stroke(W: Work, pts: P[], o: LineO = {}) { return run(W, [stroke(pts, o)]); }
  /** Several lines as one pass, in order. */
  strokes(W: Work, list: P[][], o: LineO = {}) { return run(W, list.map((pts, i) => stroke(pts, { ...o, seed: (o.seed ?? 1) + i * 11 }))); }
  /** The faint lay-in: centre lines and a loose shape before the contour. */
  construct(W: Work, pts: P[], o: LineO = {}) { return run(W, [stroke(pts, { w: 0.8, op: 0.3, wob: 1, ...o })]); }
  /** One direction of hatching across a shape, where keep says. Tone is where the hatching sits. */
  hatch(W: Work, shape: P[], o: { angle?: number; gap?: number; keep?: (x: number, y: number) => boolean; op?: number; seed?: number; color?: string } = {}) {
    const { angle = -0.85, gap = 7, keep = () => true, op = 0.62, seed = 1, color = BIRO } = o, r = rng(seed);
    const marks = hatchPieces(shape, angle, gap, keep, seed, [8, 22], r).filter((s) => s.length > 1).map((seg, i) => { const a = seg[0], z = seg[seg.length - 1], m = lerpP(a, z, 0.5), bow = (r() - 0.5) * 1.6; return stroke([a, [m[0] + bow, m[1] - bow], z], { w: 0.82, op: op * (0.75 + r() * 0.35), seed: seed * 1000 + i, wob: 0.25, color }); });
    return run(W, marks);
  }
  /** A shape's tone in the medium's order: one direction where tone passes 0.2, a cross layer past 0.5, a third past 0.75. tone(x, y) is 0 lit to 1 dark. */
  tone(W: Work, shape: P[], tone: ToneFn, o: { angle?: number; gap?: number; seed?: number; levels?: [number, number, number] } = {}) {
    const { angle = -0.85, gap = 7, seed = 1, levels = [0.2, 0.5, 0.75] } = o;
    [[0, 1], [0.95, 0.85], [-0.62, 0.75]].forEach(([da, g], i) => this.hatch(W, shape, { angle: angle + da, gap: gap * g, seed: seed + i * 13, op: 0.6 + i * 0.05, keep: (x, y) => tone(x, y) + ragged(x, y, 0.24, seed + i) > levels[i] }));
    return W;
  }
  /** A solid black scribbled in: it grows as a band across the shape and never fades in. */
  solid(W: Work, shape: P[], o: { color?: string; t?: number } = {}) {
    const b = bounds(shape), wide = b.x1 - b.x0 >= b.y1 - b.y0, color = o.color ?? BIRO;
    return run(W, [{ t: o.t ?? 18, d: (G: Gfx, p: number) => { const c = G.cur; if (p >= 1) return fillShape(G, shape, color, 1); G.touch(b.x0 - 2, b.y0 - 2, b.x1 + 2, b.y1 + 2); c.save(); c.beginPath(); if (wide) c.rect(b.x0 - 2, b.y0 - 2, (b.x1 - b.x0 + 4) * p, b.y1 - b.y0 + 4); else c.rect(b.x0 - 2, b.y0 - 2, b.x1 - b.x0 + 4, (b.y1 - b.y0 + 4) * p); c.clip(); fillShape(G, shape, color, 1); c.restore(); } }]);
  }
  /** Capitals written with the pen, stroke by stroke. */
  write(W: Work, text: string, x: number, y: number, o: { cap?: number; seed?: number; align?: "left" | "center" | "right"; w?: number; color?: string } = {}) { return run(W, [lettering(text, x, y, { cap: 24, slant: 0.08, opacity: 0.88, ...o, color: o.color ?? BIRO })]); }
  /** The sheet's tooth over the finished frame, in screen space: last thing in the frame. */
  finish(g: Ctx, o: { paper?: number } = {}) { this.grain(g, [["paper", o.paper ?? 0.07]]); }
}

register("ballpoint", { start: (w: number, h: number, o?: { scale?: number }) => new BallpointHand(w, h, o) });
