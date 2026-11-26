// letitedit hand: mid-century gouache. M.look.midCentury.start(w, h, {scale}) gives the marks; the AI writes the scene. See
// motion\runtime\looks\midCentury.md.
//
// Adapted from anidoodle's canvas-core/midCentury.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). That style has no kit
// of its own, so its marks are pulled out of the picture here: the ragged edge, the dry brush and the off-register line are taken from
// that file, and the brush laying a flat comes from its koiDrawKit. Changed by letitedit, 4 Nov 2026: the hill village, the girl, the
// kite and the film timeline are left out; board(), flat(), dry(), line() and shape() are ours, on .\worked.ts.
import { displace, fractal, rng, type Ctx, type Gfx, type Medium, type P } from "./anidoodle/core";
import { clamp, lerp, smooth } from "./anidoodle/gallery";
import { streakClip, streaks } from "./anidoodle/koiDrawKit";
import { register } from "./shared";
import { Work, WorkHand, type WorkOpts } from "./worked";

const C = { board: "#f1e1b8", cloud: "#fbf2dc", far2: "#98c1ad", far: "#4f8f86", olive: "#a6a340", oliveDark: "#8b8a32", green: "#4c8c52", greenDark: "#356a3e", cream: "#f5e8c8", pink: "#e8a296", ochre: "#e2a73a", turquoise: "#56aba2", white: "#f7efdc", tomato: "#d2462a", teal: "#244e4a", brown: "#7a4a33", dark: "#2b2724", cypress: "#2d5a40", skin: "#eab28c", hair: "#2a201b", blush: "#e78578", red: "#cf3f27", mustard: "#e9ae34", ink: "#1d1a17" };
const BRUSH: Medium = { nib: 1.15, taper: 1, pressure: 0.85, retrace: false, wobble: 1.4, rough: 0.35 };
const REG: P = [5, -4];   // the line plate's misregistration against the colour

const area = (s: P[]) => Math.abs(s.reduce((a, p, i) => { const q = s[(i + 1) % s.length]; return a + p[0] * q[1] - q[0] * p[1]; }, 0) / 2);
const plen = (s: P[]) => s.reduce((a, p, i) => (i ? a + Math.hypot(p[0] - s[i - 1][0], p[1] - s[i - 1][1]) : 0), 0);
const dens = (s: P[]): P[] => s.flatMap((a, i) => { const b = s[(i + 1) % s.length], n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 4)); return Array.from({ length: n }, (_, k) => [a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n] as P); });
/** The flat brush's slightly ragged boundary, sized to the shape; a polygon keeps its corners. */
const edge = (pts: P[], seed: number): P[] => { const a = Math.sqrt(area(pts)), amp = clamp(a * 0.011, 0.3, 2.6); return displace(dens(pts), amp, 0.11, 2, 40 + seed); };
const trace = (c: Ctx, pts: P[]) => { c.beginPath(); pts.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); };
type Dry = { path: P[]; w: number; col: string; seed: number };
const dryBrush = (c: Ctx, d: Dry, q: number) => {
  const [a, b] = [d.path[0], d.path[d.path.length - 1]], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1, nx = -dy / l, ny = dx / l, nb = Math.max(5, Math.round(d.w / 2.2)), steps = Math.max(6, Math.round(l / 3)), r = rng(d.seed);
  c.strokeStyle = d.col; c.lineWidth = 1.7; c.lineCap = "round"; c.globalAlpha = 0.85; c.beginPath();
  for (let k = 0; k < nb; k++) {
    const v = (k / (nb - 1) - 0.5) * d.w + (r() - 0.5) * 1.2, start = r() * 0.08, den = 0.2 + r() * 0.14; let on = false;
    for (let j = 0; j <= steps * q; j++) {
      const t = j / steps; if (t < start) continue;
      const skip = fractal(d.seed + k, t * l * 0.35, k * 3.1, 1, 1, 2) < den + t * 0.35, x = a[0] + dx * t + nx * v, y = a[1] + dy * t + ny * v;
      if (skip) { on = false; continue; } if (!on) { c.moveTo(x, y); on = true; } else c.lineTo(x, y);
    }
  }
  c.stroke(); c.globalAlpha = 1;
};

class GouacheHand extends WorkHand {
  palette = C; REG = REG; edge = edge; area = area; len = plen; trace = trace;
  private serial = 0;
  sm = (a: P[], closed = true, per = 6) => smooth(a, closed, per);
  ell = (cx: number, cy: number, rx: number, ry: number, rot = 0, n = 18): P[] => Array.from({ length: n }, (_, i) => { const a = (i / n) * Math.PI * 2, x = Math.cos(a) * rx, y = Math.sin(a) * ry; return [cx + x * Math.cos(rot) - y * Math.sin(rot), cy + x * Math.sin(rot) + y * Math.cos(rot)] as P; });
  ridge = (top: P[], base: number): P[] => { const t = smooth(top, false, 8); return [...t, [t[t.length - 1][0], base], [t[0][0], base]]; };
  /** A jointed limb: centreline, a radius per joint. Returns a polygon for flat(). */
  limb = (c: P[], r: number[], bulge = 0): P[] => { const s = smooth(c, false, 10), n = s.length, A: P[] = [], B: P[] = []; s.forEach((p, i) => { const t = i / (n - 1), seg = Math.min(r.length - 2, Math.floor(t * (r.length - 1))), f = t * (r.length - 1) - seg, rr = lerp(r[seg], r[seg + 1], f) + bulge * Math.sin(Math.PI * clamp((t - 0.5) * 2)), q = s[Math.min(n - 1, i + 1)], o = s[Math.max(0, i - 1)], dx = q[0] - o[0], dy = q[1] - o[1], l = Math.hypot(dx, dy) || 1; A.push([p[0] - (dy / l) * rr, p[1] + (dx / l) * rr]); B.push([p[0] + (dy / l) * rr, p[1] - (dx / l) * rr]); }); return [...A, ...B.reverse()]; };
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, BRUSH); }
  /** Warm illustration board. board: null leaves it bare, for a part that moves on its own layer. */
  board(id: string, o: WorkOpts & { color?: string | null } = {}): Work {
    const bare = o.color === null;
    return this.work(id, { ...o, ground: bare ? null : (G) => { const c = G.cur, e = G.env; c.setTransform(e.scale, 0, 0, e.scale, 0, 0); c.fillStyle = o.color ?? C.board; c.fillRect(0, 0, e.W, e.H); }, finish: bare ? null : (G) => G.paper("coldpress", 0.16) });
  }
  /** One opaque flat, laid by the loaded brush in passes at angle ang, and finished with a brushed edge. */
  flat(W: Work, pts: P[], color: string, o: { ang?: number; seed?: number; per?: number } = {}) {
    const seed = o.seed ?? ++this.serial, e = edge(pts, seed), a = Math.sqrt(area(pts)), ang = o.ang ?? 0; let st: ReturnType<typeof streaks> | null = null;
    W.add(o.per ?? 1.4 + a / 22, (G: Gfx, q: number) => { const c = G.cur; c.save(); c.fillStyle = color; if (q < 1) { st = st ?? streaks([e], clamp(a / 5, 5, 58), ang, 60 + seed, clamp(a * 0.9, 60, 340)); streakClip(c, st, q); } trace(c, e); c.fill(); c.restore(); });
    return W;
  }
  /** A nearly dry brush dragged straight along path (its two ends): broken parallel streaks over the flats. */
  dry(W: Work, path: P[], o: { w?: number; color?: string; seed?: number; per?: number } = {}) {
    const d: Dry = { path, w: o.w ?? 40, col: o.color ?? C.cream, seed: 700 + (o.seed ?? ++this.serial) };
    W.add(o.per ?? 1 + plen(path) / 70, (G: Gfx, q: number) => dryBrush(G.cur, d, q));
    return W;
  }
  /** The loose ink line on its own plate, off register from the colour: let it wander past an edge and leave some out. */
  line(W: Work, pts: P[], o: { w?: number; color?: string; seed?: number; per?: number; reg?: P } = {}) {
    const seed = 300 + (o.seed ?? ++this.serial), reg = o.reg ?? REG;
    W.add(o.per ?? 1.6 + plen(pts) / 60, (G: Gfx, q: number) => { G.push(reg[0], reg[1], 1); G.group("plain", () => G.pen(pts, { w: o.w ?? 2.6, color: o.color ?? C.ink, seed, wobble: 0.9, opacity: 0.92, boil: 0, progress: q })); G.pop(); });
    return W;
  }
  /** The same flat with no timing, for a piece redrawn every frame: pts are its already ragged edge from S.edge. */
  shape(g: Ctx, e: P[], color: string) { g.fillStyle = color; trace(g, e); g.fill(); }
}

register("midCentury", { start: (w: number, h: number, o?: { scale?: number }) => new GouacheHand(w, h, o) });
