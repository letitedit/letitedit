// letitedit hand: cyanotype blueprint. M.look.blueprint.start(w, h, {scale}) gives the blue sheet, ruling pen, compass, chain lines, section lining, dimensions and gothic
// lettering; the AI writes the machine. See motion\runtime\looks\blueprint.md.
//
// Uses anidoodle's canvas-core/blueprintKit.ts and drafting.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Changed by letitedit, 4 Nov 2026: each drafting mark
// takes its share of the time on a Work (.\worked.ts), and the sheet is a plate of any size; the clock train and film are left out.
import { type Ctx, type Gfx, type P } from "./anidoodle/core";
import { CYAN, DIM, DRAFT, GROUND, WHITE, border, kit, sheet } from "./anidoodle/blueprintKit";
import { strokeCount, width } from "./anidoodle/drafting";
import { MarkHand, plen, type Box } from "./marks";
import { register } from "./shared";
import type { Work } from "./worked";

type Pen = { color?: string; seed?: number; opacity?: number; closed?: boolean; taper?: number; wobble?: number };
const longFast = (len: number) => 3 + len / 40;

class BlueprintHand extends MarkHand {
  palette = { ground: GROUND, white: WHITE, cyan: CYAN, dim: DIM }; textWidth = width;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, DRAFT); }
  private mark(W: Work, t: number, fn: (k: ReturnType<typeof kit>, q: number) => void) { W.add(t, (G: Gfx, q: number) => { const k = kit(G); k.ink(() => fn(k, q)); }); return W; }
  /** The stock: Prussian blue, unevenly exposed, mottled, two old folds, dust. A plate. */
  paper(id = "paper", o: { box?: Box } = {}) { return this.ground(id, (G) => sheet(kit(G)), o.box); }
  /** The ruled double border with its zone marks, stroke by stroke. */
  border(W: Work, o: { t?: number } = {}) { W.add(o.t ?? 40, (G, q) => border(kit(G), q)); return W; }
  /** A ruled line, never dead straight. Outlines heavy white (1.4-1.9), lining and dimensions thin cyan (0.75-1). */
  rule(W: Work, a: P, b: P, w = 1.6, o: Pen = {}) { return this.mark(W, longFast(plen([a, b])), (k, q) => k.ln(a, b, w, { ...o, progress: q })); }
  /** A ruled outline through points: each side a stroke. */
  outline(W: Work, pts: P[], w = 1.7, o: Pen = {}) { const list = o.closed === false ? pts : [...pts, pts[0]]; for (let i = 1; i < list.length; i++) this.rule(W, list[i - 1], list[i], w, { ...o, seed: (o.seed ?? 1) + i }); return W; }
  /** A freehand pen line through points, smoothed. */
  curve(W: Work, pts: P[], w = 1.5, o: Pen = {}) { return this.mark(W, longFast(plen(pts)), (k, q) => k.pen(pts, w, { ...o, progress: q })); }
  /** A compass circle: truly round, swung from where the needle-leg starts. */
  circle(W: Work, x: number, y: number, r: number, w = 1.6, o: Pen & { a0?: number } = {}) { return this.mark(W, longFast(r * 6.28), (k, q) => k.circle(x, y, r, w, { ...o, progress: q })); }
  /** A centre line: long dash, short dash. */
  chain(W: Work, a: P, b: P, w = 0.9, o: Pen = {}) { return this.mark(W, longFast(plen([a, b])), (k, q) => k.chain(a, b, w, { color: CYAN, ...o, progress: q })); }
  /** A pitch circle as a chain line. */
  chainRing(W: Work, x: number, y: number, r: number, w = 0.9, o: Pen = {}) { return this.mark(W, longFast(r * 6.28), (k, q) => k.chainRing(x, y, r, w, { ...o, progress: q })); }
  /** Dashes, for a hidden edge. */
  dash(W: Work, a: P, b: P, w = 1, o: Pen & { on?: number; off?: number } = {}) { return this.mark(W, longFast(plen([a, b])), (k, q) => k.dash(a, b, o.on ?? 12, o.off ?? 7, w, { color: CYAN, ...o, progress: q })); }
  /** Section lining at 45 degrees, starting and stopping just inside the part. Neighbouring parts go in opposing directions: the only tone a drawing has. */
  section(W: Work, shape: P[], o: { angle?: number; gap?: number; w?: number; seed?: number; color?: string; t?: number } = {}) { return this.mark(W, o.t ?? 30, (k, q) => k.hatch(shape, o.angle ?? 0.785, o.gap ?? 9, o.w ?? 0.9, o.seed ?? 1, { color: o.color, progress: q })); }
  /** A linear dimension between two points, set off by `off`: witness lines, dimension line, arrows, figure. */
  dim(W: Work, a: P, b: P, off: number, label: string, o: { seed?: number; cap?: number } = {}) { return this.mark(W, 8 + strokeCount(label) * 2, (k, q) => k.dim(a, b, off, label, o.seed ?? 1, q, { cap: o.cap })); }
  /** A note with its leader out to the part. */
  callout(W: Work, text: string, at: P, to: P, o: { seed?: number; align?: "left" | "right"; cap?: number } = {}) { return this.mark(W, 8 + strokeCount(text) * 2, (k, q) => k.callout(text, at, to, o.seed ?? 1, o.align ?? "left", q, o.cap ?? 12)); }
  /** A numbered balloon pointing at a part. */
  balloon(W: Work, n: string, at: P, to: P, o: { seed?: number } = {}) { return this.mark(W, 10, (k, q) => k.balloon(n, at, to, o.seed ?? 1, q)); }
  /** Inclined gothic capitals, stroke by stroke; lettering is slow. slant 0 is upright. */
  letter(W: Work, text: string, x: number, y: number, o: { cap?: number; color?: string; seed?: number; align?: "left" | "center" | "right"; w?: number; opacity?: number } = {}) { return this.mark(W, strokeCount(text) * 3, (k, q) => k.text(text, x, y, { ...o, progress: q })); }
  /** A filled arrowhead. */
  arrow(W: Work, tip: P, angle: number, o: { size?: number; color?: string } = {}) { return this.mark(W, 2, (k, q) => { if (q > 0) k.arrow(tip, angle, o.size ?? 11, o.color); }); }
  /** The sheet's tooth over the finished frame, in screen space: last thing in the frame. */
  finish(g: Ctx, o: { paper?: number; coldpress?: number } = {}) { this.grain(g, [["paper", o.paper ?? 0.34], ["coldpress", o.coldpress ?? 0.2]]); }
}

register("blueprint", { start: (w: number, h: number, o?: { scale?: number }) => new BlueprintHand(w, h, o) });
