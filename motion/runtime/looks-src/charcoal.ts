// letitedit hand: charcoal, erased and redrawn. M.look.charcoal.start(w, h, {scale}) gives the rag sheet, vine and compressed sticks, the side of the stick, the
// stump and the kneaded eraser; the AI writes the scene. See motion\runtime\looks\charcoal.md.
//
// Uses anidoodle's canvas-core/charcoalErasureKit.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77) as it stands. Changed by letitedit, 4 Nov 2026: the tools
// are given sizes as arguments and hold marks on a Work (.\worked.ts, .\marks.ts); its oak, seasons and film clock are left out.
import { type Ctx, type Gfx, type Medium, type P } from "./anidoodle/core";
import { COMP, ERASE, INK, STUMP, VINE, dab, dur, noiseAt, rubMark, sideMarks, spiral, stick, zigzag } from "./anidoodle/charcoalErasureKit";
import { bounds, polyLen } from "./anidoodle/gallery";
import { MarkHand, lettering, run, type Box, type Mk } from "./marks";
import { register } from "./shared";
import type { Work } from "./worked";

const CHAR_M: Medium = { nib: 1, taper: 1, pressure: 0.6, retrace: false, wobble: 1, rough: 1 }, PAPER = "#ece5d5";
type Stick = { w0?: number; w1?: number; alpha?: number; seed?: number; rough?: number; ends?: number };
const line = (pts: P[], o: Stick, d: { w0: number; w1: number; alpha: number }): Mk => ({ t: dur(polyLen(pts)), d: (G: Gfx, p: number) => stick(G, pts, o.w0 ?? d.w0, o.w1 ?? d.w1, o.alpha ?? d.alpha, o.seed ?? 1, p, { rough: o.rough, ends: o.ends }) });

class CharcoalHand extends MarkHand {
  palette = { ink: INK, paper: PAPER }; noise = noiseAt;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, CHAR_M); }
  /** The felt-marked rag sheet: a plate. It's never erased: the charcoal lives on the Work above it. */
  paper(id = "paper", o: { box?: Box; color?: string } = {}) { return this.ground(id, (G, W, H) => { const c = G.main; c.save(); c.setTransform(this.scale, 0, 0, this.scale, 0, 0); c.fillStyle = o.color ?? PAPER; c.fillRect(0, 0, W, H); c.restore(); G.paper("ce_sheet", 0.22); }, o.box); }
  /** Vine: the soft grey stick, light and broken by the tooth, for laying a subject in. pts aren't smoothed: use H.smooth first for a curve. */
  vine(W: Work, pts: P[], o: Stick = {}) { return run(W, [line(pts, o, { w0: 3.4, w1: 1.8, alpha: 0.55 })], VINE); }
  /** Compressed: black, crisp, barely erases. For the accents, last. */
  compressed(W: Work, pts: P[], o: Stick = {}) { return run(W, [line(pts, o, { w0: 4.4, w1: 2, alpha: 0.95 })], COMP); }
  /** Several vine or compressed lines as one pass. */
  sticks(W: Work, list: P[][], o: Stick & { hard?: boolean } = {}) { return run(W, list.map((pts, i) => line(pts, { ...o, seed: (o.seed ?? 1) + i * 7 }, o.hard ? { w0: 4.4, w1: 2, alpha: 0.95 } : { w0: 3.4, w1: 1.8, alpha: 0.55 })), o.hard ? COMP : VINE); }
  /** The side of the stick: broad parallel drags clipped to a shape, for tone. keep(x, y) steers where. */
  side(W: Work, shape: P[], o: { angle?: number; gap?: number; w?: number; alpha?: number; seed?: number; keep?: (x: number, y: number) => boolean; hard?: boolean; per?: number } = {}) { return run(W, sideMarks(shape, { angle: o.angle ?? -0.22, gap: o.gap ?? 7, w: o.w ?? 14, alpha: o.alpha ?? 0.14, seed: o.seed ?? 11, keep: o.keep, per: o.per ?? 900 }), o.hard ? COMP : VINE); }
  /** The stump: a wide soft rub that pushes tone into the sheet, for atmosphere with no edge. */
  stump(W: Work, shape: P[], o: { gap?: number; amp?: number; w?: number; alpha?: number; blur?: number; seed?: number } = {}) { return run(W, zigzag(bounds(shape), o.gap ?? 22, o.amp ?? 24, o.seed ?? 3).map((row) => rubMark(row, o.w ?? 40, o.alpha ?? 0.06, INK, shape)), { ...STUMP(o.blur ?? 8), chunk: 60 }); }
  /** The kneaded eraser, rubbed across a shape. It lifts charcoal, streaky, and never all of it: raise alpha toward 0.9 for a firm lift. */
  erase(W: Work, shape: P[], o: { gap?: number; amp?: number; w?: number; alpha?: number; blur?: number; seed?: number } = {}) { return run(W, zigzag(bounds(shape), o.gap ?? 14, o.amp ?? 14, o.seed ?? 5).map((row) => rubMark(row, o.w ?? 18, 1, INK, shape)), { ...ERASE(o.alpha ?? 0.7, o.blur ?? 2.6), chunk: 60 }); }
  /** A light lifted by pressing and turning the eraser: a soft glow, then the disc. For a sun, a lamp. */
  lift(W: Work, x: number, y: number, r: number, o: { glow?: number; alpha?: number; seed?: number } = {}) {
    const seed = o.seed ?? 21;
    run(W, [rubMark(spiral(x, y, 4, r * 1.4, 3, seed + 1), 22, 1)], ERASE(o.glow ?? 0.18, 10));
    return run(W, [rubMark(spiral(x, y, 2, Math.max(3, r - 6), Math.max(3.6, r / 8), seed), 13, 1, INK, undefined, 3000)], ERASE(o.alpha ?? 0.88, 2.2));
  }
  /** Small bitten dabs, a leaf, a bud: list of [x, y, rx, ry, rot]. */
  dabs(W: Work, list: [number, number, number, number, number?][], o: { alpha?: number; seed?: number; hard?: boolean } = {}) { return run(W, list.map(([x, y, rx, ry, rot], i) => ({ t: 0.08, d: (G: Gfx, p: number) => { if (p > 0) dab(G, x, y, rx, ry, rot ?? 0, o.alpha ?? 0.5, (o.seed ?? 31) + i); } })), o.hard ? COMP : VINE); }
  /** Capitals in compressed charcoal, stroke by stroke. */
  write(W: Work, text: string, x: number, y: number, o: { cap?: number; seed?: number; align?: "left" | "center" | "right"; w?: number } = {}) { return run(W, [lettering(text, x, y, { cap: 24, slant: 0.1, opacity: 0.9, ...o, color: INK })], COMP); }
  /** The sheet's tooth over the frame, so the grain shows through the blacks: last thing in the frame. */
  finish(g: Ctx, o: { paper?: number } = {}) { this.grain(g, [["paper", o.paper ?? 0.16]]); }
}

register("charcoal", { start: (w: number, h: number, o?: { scale?: number }) => new CharcoalHand(w, h, o) });
