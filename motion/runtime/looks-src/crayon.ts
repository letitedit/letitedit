// letitedit hand: crayon. M.look.crayon.start(w, h, {scale}) gives wax on toothy paper: scribble fills that skip the valleys, a darker crayon on
// the shade side, a white one burnishing the light, a fat wobbly line; the picture is written fresh by the AI. See motion\runtime\looks\crayon.md.
//
// Adapted from anidoodle's canvas-core/balloon.ts and balloonDraw.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Changed by
// letitedit, 4 Nov 2026: scribble(), line() and wax() are taken from balloon.ts, with the clock replaced by a progress argument; its balloon,
// sky and hills are left out; the mark list, parts and takes are ours (.\marksRoll.ts). That style had no kit of its own: these marks came
// out of its hero file.
import { Gfx, rng, type Ctx, type Medium, type P } from "./anidoodle/core";
import { blob, bounds, clipped, fillShape, hatchRuns, inside, mix, smooth } from "./anidoodle/gallery";
import { keepCorners, Marks, Rolled } from "./marksRoll";
import { Hand, register } from "./shared";

const CRAYON_M: Medium = { nib: 2.9, taper: 0.3, pressure: 0.8, retrace: true, wobble: 2.2, rough: 1.3 };
export const K = { red: "#e5392d", orange: "#f68b1f", yellow: "#ffd21f", green: "#3dae49", blue: "#2f7de1", sky: "#69c3f2", purple: "#8d4fc7", pink: "#ff78ae", brown: "#8b5a3c", white: "#fffdf4", black: "#262233", leaf: "#2f8a3b" };
const PAPER = "#fdf8ea", RANK = { lay: 0, fill: 1, shade: 2, burnish: 3, line: 4 };
const dark = (c: string) => mix(c, "#2a1d3a", 0.45);
type Keep = (x: number, y: number) => boolean;
type Sc = { angle?: number; gap?: number; w?: number; alpha?: number; seed?: number; keep?: Keep; over?: number };

// A scribble fill: hatch runs joined end to end into one back-and-forth stroke, in short passes so the pressure wanders the way a hand does.
const scribble = (g: Gfx, runs: P[][], color: string, o: Required<Pick<Sc, "gap" | "w" | "alpha" | "seed">>, p: number) => {
  const r = rng(o.seed), c = g.cur; c.save(); c.lineCap = "round"; c.lineJoin = "round"; c.strokeStyle = color; c.lineWidth = o.w;
  let prev: P | null = null; const lim = p * runs.length;
  runs.forEach((run, i) => {
    if (i >= lim) return;
    let pts = (i % 2 ? [...run].reverse() : run).filter((_, k, a) => k % 3 === 0 || k === a.length - 1).map(([x, y]) => [x + (r() - 0.5) * 1.6, y + (r() - 0.5) * 1.6] as P);
    if (lim - i < 1) pts = pts.slice(0, Math.max(2, Math.ceil(pts.length * (lim - i))));
    const jump = prev ? Math.hypot(pts[0][0] - prev[0], pts[0][1] - prev[1]) : 0;
    c.globalAlpha = o.alpha * (0.72 + r() * 0.4); c.beginPath();
    if (prev && jump < o.gap * 3.2) { c.moveTo(prev[0], prev[1]); pts.forEach(([x, y]) => c.lineTo(x, y)); } else pts.forEach(([x, y], k) => (k ? c.lineTo(x, y) : c.moveTo(x, y)));
    c.stroke(); prev = pts[pts.length - 1];
  });
  c.restore();
};
const wax = (g: Gfx, fn: () => void) => g.group("plain", fn, { textures: ["pencilTooth"] });

/** One picture being recorded. Inside a part, marks go down lay-in, fill, shade, burnish, line. k.part() starts the next thing up the stack. */
class Draw extends Marks {
  constructor(private seed0: number) { super(); }
  private sc(region: P[], color: string, rank: number, d: Required<Pick<Sc, "angle" | "gap" | "w" | "alpha">>, o: Sc) {
    const angle = o.angle ?? d.angle, gap = o.gap ?? d.gap, w = o.w ?? d.w, alpha = o.alpha ?? d.alpha, seed = (o.seed ?? this.list.length + 3) + this.seed0, over = o.over ?? 1.035, keep = o.keep ?? (() => true), b = bounds(region), cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2, grown = region.map(([x, y]) => [cx + (x - cx) * over, cy + (y - cy) * over] as P);
    let runs: P[][] | undefined; const get = () => (runs ??= hatchRuns({ x0: b.x0 - 8, y0: b.y0 - 8, x1: b.x1 + 8, y1: b.y1 + 8 }, angle, gap, (x, y) => inside(grown, x, y) && keep(x, y), 5, seed));
    return this.add(rank, Math.sqrt((b.x1 - b.x0) * (b.y1 - b.y0)) * 0.9 + 14, (G, p) => { const R = get(); G.touch(b.x0 - 14, b.y0 - 14, b.x1 + 14, b.y1 + 14); wax(G, () => { G.touch(b.x0 - 14, b.y0 - 14, b.x1 + 14, b.y1 + 14); scribble(G, R, color, { gap, w, alpha, seed }, p); }); });
  }
  /** A scribble fill: back and forth, at angle, gap apart. keep(x, y) false leaves paper showing; see K.around. */
  fill(region: P[], color: string, o: Sc = {}) { return this.sc(region, color, RANK.fill, { angle: 1.15, gap: 5.5, w: 7, alpha: 0.85 }, o); }
  /** A second, darker crayon worked across the side away from the light. By default the colour's own dark. */
  shade(region: P[], color: string, o: Sc = {}) { return this.sc(region, dark(color), RANK.shade, { angle: 0.75, gap: 8, w: 6, alpha: 0.55 }, o); }
  /** White crayon pressed hard into the highlight. */
  burnish(region: P[], o: Sc = {}) { return this.sc(region, K.white, RANK.burnish, { angle: -0.6, gap: 4.5, w: 5.5, alpha: 0.85 }, o); }
  /** Bare paper over what's there: use it under a thing that overlaps, since wax on wax mixes. */
  paper(region: P[], color = PAPER) { return this.add(RANK.fill, 3, (G, p) => { if (p < 1) return; G.group("plain", () => fillShape(G, region, color)); }); }
  /** The contour: laid in thin first, gone over fat at the end. closed joins the ends; lay: false skips the lay-in, for tiny flicks. */
  line(pts: P[], color: string = K.black, w = 5, o: { seed?: number; closed?: boolean; wobble?: number; opacity?: number; lay?: boolean } = {}) {
    const seed = (o.seed ?? this.list.length + 5) + this.seed0, s = keepCorners(o.closed ? [...pts, pts[0]] : pts), wob = o.wobble ?? 1, op = o.opacity ?? 0.92, L = s.reduce((a, q, i) => (i ? a + Math.hypot(q[0] - s[i - 1][0], q[1] - s[i - 1][1]) : 0), 0), box = bounds(s);
    if (o.lay !== false && L >= 25) this.add(RANK.lay, Math.pow(L, 0.75) * 0.5 + 3, (G, p) => wax(G, () => { G.touch(box.x0 - 12, box.y0 - 12, box.x1 + 12, box.y1 + 12); G.pen(s, { w: w * 0.45, color, seed, wobble: wob, boil: 0, opacity: op * 0.6, retrace: false, taper: 1, progress: p }); }));
    return this.add(RANK.line, Math.pow(L, 0.75) + 6, (G, p) => wax(G, () => { G.touch(box.x0 - 12, box.y0 - 12, box.x1 + 12, box.y1 + 12); G.pen(s, { w, color, seed, wobble: wob, boil: 0.5, opacity: op, retrace: true, taper: 1, progress: p }); }));
  }
  /** Any mark of your own, in a group that takes the wax's tooth. paint(c, p) draws on c; box it with the area you touch. */
  mark(rank: "fill" | "shade" | "burnish" | "line", area: { x0: number; y0: number; x1: number; y1: number }, paint: (c: Ctx, p: number) => void) { return this.add(RANK[rank], 10, (G, p) => wax(G, () => { G.touch(area.x0, area.y0, area.x1, area.y1); paint(G.cur, p); })); }
}

class CrayonHand extends Hand {
  c = K; PAPER = PAPER; rng = rng; smooth = smooth; blob = blob; bounds = bounds; mix = mix; dark = dark; inside = inside; clipped = clipped;
  /** A keep rule for k.fill: scribble everywhere except inside these shapes. */
  around(shapes: P[][]) { return (x: number, y: number) => !shapes.some((s) => inside(s, x, y)); }
  /** A drawing, recorded once. paint(k) records its marks. box limits it to a part of the frame (smaller, faster to bake). takes = how many redrawings for a line that boils. */
  picture(_id: string, paint: (k: Draw) => void, o: { box?: { x0: number; y0: number; x1: number; y1: number }; takes?: number } = {}) { return new Rolled(this, (take) => { const k = new Draw(take * 101); paint(k); return k.sorted(); }, CRAYON_M, o); }
  /** The bare sheet, as a plate. */
  sheetPlate(id = "sheet", color = PAPER, box?: { x0: number; y0: number; x1: number; y1: number }) { return this.plate(id, (c) => { const b = box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }; c.fillStyle = color; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); }, box); }
  /** Line boil: which of n takes at time t, held for rate frames a second. */
  take(t: number, n = 3, rate = 6) { return Math.floor(t * rate + 1e-6) % n; }
  /** The sheet's tooth over the finished frame, last thing in the frame. */
  finish(g: Ctx, o: { paper?: number; vignette?: string | null } = {}) { this.sheet(g, { paper: o.paper ?? 0.1, vignette: o.vignette === undefined ? null : o.vignette, tile: "paper" }); }
}

register("crayon", { start: (w: number, h: number, o?: { scale?: number }) => new CrayonHand(w, h, o), colours: K });
