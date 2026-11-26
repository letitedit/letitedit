// letitedit: what the pencil, ink and board hands share on top of .\worked.ts. A run of marks made with one tool: many strokes
// are one entry on the Work, drawn together on one layer and textured once, which is how the medium's tooth or dust stays cheap.
// Written for letitedit (GPL-3.0-or-later). The tool-and-marks idea comes from anidoodle's charcoalErasureKit (Apache-2.0, see .\anidoodle).
import { Gfx, fractal, type P } from "./anidoodle/core";
import { letter, strokeCount } from "./anidoodle/drafting";
import { bounds, clamp, hatchRuns, inside } from "./anidoodle/gallery";
import { Work, WorkHand } from "./worked";

export type Mk = { t: number; d: (G: Gfx, p: number) => void };
export type Tool = { kind?: "ink" | "paint" | "plain"; textures?: string[]; blur?: number; blend?: GlobalCompositeOperation; alpha?: number; off?: P; halo?: { blur: number; alpha: number; textures?: string[] }; chunk?: number };
export type Box = { x0: number; y0: number; x1: number; y1: number };

export const plen = (s: P[]) => { let L = 0; for (let i = 1; i < s.length; i++) L += Math.hypot(s[i][0] - s[i - 1][0], s[i][1] - s[i - 1][1]); return L; };
/** Time for a stroke: fiddly short ones take longer per pixel than long ones. */
export const cost = (len: number, each = 4) => each + Math.pow(Math.max(0, len), 0.85);

export const drawn = (G: Gfx, marks: Mk[], total: number, q: number) => { let b = q >= 1 ? Infinity : q * total; for (const m of marks) { if (b <= 0) break; m.d(G, b >= m.t ? 1 : b / m.t); b -= m.t; } };

/** Adds marks to a Work with one tool, split so that seeking stays quick. A mark's own t is its share of the time. */
export const run = (W: Work, marks: Mk[], tool: Tool = {}) => {
  const n = tool.chunk ?? 24;
  for (let i = 0; i < marks.length; i += n) {
    const part = marks.slice(i, i + n), total = part.reduce((a, m) => a + m.t, 0);
    W.add(total, (G, q) => {
      const fn = () => drawn(G, part, total, q);
      if (tool.halo) G.inkGroup(fn, { blur: tool.halo.blur, alpha: tool.halo.alpha, textures: tool.halo.textures });
      else G.group(tool.kind ?? "plain", fn, { textures: tool.textures, blur: tool.blur, blend: tool.blend, alpha: tool.alpha, off: tool.off });
    });
  }
  return W;
};

export type ToneFn = (x: number, y: number) => number;

/** Strokes cut from hatch runs: lines at one angle across a shape, where keep says. Each run is broken into hand-length pieces. */
export const hatchPieces = (shape: P[], angle: number, gap: number, keep: (x: number, y: number) => boolean, seed: number, pieces: [number, number], rnd: () => number): P[][] => {
  const out: P[][] = [], b = bounds(shape);
  hatchRuns(b, angle, gap, (x, y) => inside(shape, x, y) && keep(x, y), 2.5, seed).forEach((run) => {
    let i = 0;
    while (i < run.length - 1) { const n = Math.min(run.length - 1 - i, pieces[0] + Math.floor(rnd() * pieces[1])); out.push(run.slice(i, i + n + 1)); i += n + (rnd() < 0.25 ? 1 : 0); }
  });
  return out;
};
/** A hand stops its hatching at a slightly different place every stroke. */
export const ragged = (x: number, y: number, k: number, seed = 5) => (fractal(seed, x, y, 0.035, 0.035, 2) - 0.5) * k;

/** A line of single-stroke capitals as a mark, written stroke by stroke. */
export const lettering = (text: string, x: number, y: number, o: { cap?: number; color: string; seed?: number; align?: "left" | "center" | "right"; w?: number; opacity?: number; slant?: number; track?: number }): Mk => ({
  t: strokeCount(text) * 5, d: (G, p) => letter(G, text, x, y, { ...o, progress: p }),
});

/** A hand of this family: tones a scene can use, the same in every hand. All give 0..1. */
export class MarkHand extends WorkHand {
  /** A ball lit from one side: 0 on the lit side, 1 in the shade, 0 outside it. light is a direction, [-0.7, -0.7] is upper left. */
  ball(cx: number, cy: number, r: number, light: P = [-0.7, -0.7]): ToneFn { const l = Math.hypot(light[0], light[1]) || 1, lx = light[0] / l, ly = light[1] / l; return (x, y) => { const nx = (x - cx) / r, ny = (y - cy) / r, d = nx * nx + ny * ny; if (d > 1) return 0; const nz = Math.sqrt(1 - d), lit = nx * lx * 0.75 + ny * ly * 0.75 + nz * 0.66; return clamp(0.78 - lit * 0.62); }; }
  /** Across a shape from one side to the other: 0 where the light comes from, 1 at the far side. */
  across(shape: P[], angle = 0.8): ToneFn { const c = Math.cos(angle), s = Math.sin(angle), v = shape.map(([x, y]) => x * c + y * s), lo = Math.min(...v), hi = Math.max(...v); return (x, y) => clamp((x * c + y * s - lo) / (hi - lo || 1)); }
  /** A tone everywhere inside a shape and nothing outside it. */
  inShape(shape: P[], tone: ToneFn | number): ToneFn { return (x, y) => (inside(shape, x, y) ? (typeof tone === "number" ? tone : tone(x, y)) : 0); }
  /** Paper textures multiplied over a finished frame, in screen space. list: [[tile, strength], ...]. */
  grain(g: CanvasRenderingContext2D, list: [string, number][]) { g.save(); const G = new Gfx(g, this.env, 0, this.medium); list.forEach(([t, a]) => { if (a > 0) G.paper(t, a); }); g.restore(); }
  /** A plate painted through the core's drawing context, for grounds that use paper tiles. */
  ground(id: string, paint: (G: Gfx, W: number, H: number) => void, box?: Box) { const b = box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, W = b.x1 - b.x0, H = b.y1 - b.y0; return this.plate(id, (c) => { const env = { ...this.env, W, H }, G = new Gfx(c, env, 0, this.medium); paint(G, W, H); }, b); }
  /** A breath on the Work: time passes with nothing moving. */
  rest(W: Work, t = 10) { W.pause(t); return W; }
}
