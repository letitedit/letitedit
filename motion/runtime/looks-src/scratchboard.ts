// letitedit hand: scratchboard. M.look.scratchboard.start(w, h, {scale}) gives the black board and the knife: fur flicks along a flow you write, knife lines,
// hatching and scraped lights; the AI writes the scene. See motion\runtime\looks\scratchboard.md.
//
// Adapted from anidoodle's canvas-core/scratchboard.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77): the cut's ribbon, the flick along a flow,
// the density of the flicks, the order of phases and the clay chipping at a cut's edge are taken from it. Changed by letitedit, 4 Nov 2026: tone, flow and hair
// length come from the scene and not its lynx (scratchboardKit is left out); rim() is ours; marks go on a Work (.\worked.ts, .\marks.ts).
import { rng, sample, type Ctx, type Gfx, type P } from "./anidoodle/core";
import { bounds, clamp, inside } from "./anidoodle/gallery";
import { MarkHand, drawn, hatchPieces, lettering, plen, run, type Box, type Mk, type ToneFn } from "./marks";
import { register } from "./shared";
import type { Work } from "./worked";

const BOARD = "#0c0b0a", CLAY = "#ebe5d8", TAU = Math.PI * 2;
type Cut = { pts: P[]; w: number[]; alpha: number; fill?: boolean };

const taper = (n: number, w: number, tail = 0.2, bite = 0.5) => Array.from({ length: n }, (_, i) => { const t = i / Math.max(1, n - 1); return w * (t < 0.12 * bite ? 0.55 + (0.45 * t) / (0.12 * bite) : Math.max(tail, Math.pow(1 - t, 0.7))); });
const ribbon = (c0: Cut, prog = 1): P[] => {
  let c = c0;
  if (prog < 1) { const n0 = c0.pts.length, u = (n0 - 1) * prog, i = Math.floor(u), f = u - i, a = c0.pts[i], b = c0.pts[Math.min(n0 - 1, i + 1)]; c = { ...c0, pts: [...c0.pts.slice(0, i + 1), [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]], w: [...c0.w.slice(0, i + 1), c0.w[Math.min(n0 - 1, i + 1)] ?? 0.5] }; }
  const n = c.pts.length, L: P[] = [], R: P[] = [];
  for (let i = 0; i < n; i++) { const a = c.pts[Math.max(0, i - 1)], b = c.pts[Math.min(n - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1, w = (c.w[i] ?? 0.5) / 2; L.push([c.pts[i][0] - (dy / l) * w, c.pts[i][1] + (dx / l) * w]); R.push([c.pts[i][0] + (dy / l) * w, c.pts[i][1] - (dx / l) * w]); }
  return [...L, ...R.reverse()];
};
const cutMark = (c: Cut, t: number): Mk => ({ t, d: (G, p) => { if (p <= 0) return; const s = c.fill ? c.pts : ribbon(c, p), k = G.cur; G.mark(s, 2); k.fillStyle = CLAY; k.globalAlpha = c.alpha; k.beginPath(); s.forEach(([x, y], i) => (i ? k.lineTo(x, y) : k.moveTo(x, y))); k.closePath(); k.fill(); k.globalAlpha = 1; } });
// the cut clean and faint, then the same cuts with the clay chipping at their edges, so a cut is never a vector line
const addCuts = (W: Work, marks: Mk[], chunk: number) => {
  for (let i = 0; i < marks.length; i += chunk) { const part = marks.slice(i, i + chunk), total = part.reduce((a, m) => a + m.t, 0);
    W.add(total, (G: Gfx, q: number) => { G.group("plain", () => drawn(G, part, total, q), { alpha: 0.55 }); G.group("plain", () => drawn(G, part, total, q), { textures: ["draftTooth"] }); }); }
  return W;
};

class ScratchHand extends MarkHand {
  palette = { board: BOARD, clay: CLAY };
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, { nib: 1, taper: 1, pressure: 0.5, retrace: false, wobble: 0.6, rough: 0.4 }); }
  /** The inked board: a plate. */
  board(id = "board", o: { box?: Box; color?: string } = {}) { const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }; return this.plate(id, (c) => { c.fillStyle = o.color ?? BOARD; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); }, b); }
  /** A coat of flicks over a shape, white on black. tone(x, y): 0 uncut to 1 cut until it closes up. flow(x, y): the angle the hair lies, radians, or one number. len: hair length, a number or (x, y). Cut in the medium's order: a sparse coat to set the lie, the mids with a crossing set, then the lights. */
  fur(W: Work, shape: P[] | null, o: { tone: ToneFn; flow?: number | ToneFn; len?: number | ToneFn; seed?: number; cross?: boolean; box?: Box; chunk?: number }) {
    const b = o.box ?? (shape ? bounds(shape) : { x0: 0, y0: 0, x1: this.w, y1: this.h }), r = rng(o.seed ?? 4711), inS = shape ? (x: number, y: number) => inside(shape, x, y) : () => true, size = Math.min(this.w, this.h) / 1080;
    const tone = (x: number, y: number) => (inS(x, y) ? clamp(o.tone(x, y)) : 0), angle = typeof o.flow === "function" ? o.flow : () => (o.flow as number) ?? -1.2, lenAt = typeof o.len === "function" ? o.len : () => (o.len as number) ?? 18 * size;
    const wOf = (t: number) => (t < 0.03 ? 0 : 0.34 + 2.3 * Math.pow(t, 1.6)), spacing = (x: number, y: number) => { const t = tone(x, y); if (t < 0.06) return 0; const L = Math.max(4, lenAt(x, y)), cov = Math.pow(t, 1.15) * (0.85 + 0.5 * t * t); return clamp(Math.sqrt((0.9 * L * wOf(t) * 0.5) / cov), 1.9, 26); };
    const cell = 1.3, gw = Math.ceil((b.x1 - b.x0) / cell) + 1, gh = Math.ceil((b.y1 - b.y0) / cell) + 1, grid = new Int32Array(gw * gh).fill(-1), xs: number[] = [], ys: number[] = [], ds: number[] = [];
    const gi = (x: number, y: number) => Math.floor((y - b.y0) / cell) * gw + Math.floor((x - b.x0) / cell);
    const ok = (x: number, y: number, d: number) => { const reach = Math.ceil((d * 1.2) / cell), gx = Math.floor((x - b.x0) / cell), gy = Math.floor((y - b.y0) / cell); for (let j = Math.max(0, gy - reach); j <= Math.min(gh - 1, gy + reach); j++) for (let i = Math.max(0, gx - reach); i <= Math.min(gw - 1, gx + reach); i++) { const q = grid[j * gw + i]; if (q < 0) continue; const dx = xs[q] - x, dy = ys[q] - y, m = 0.5 * (d + ds[q]); if (dx * dx + dy * dy < m * m) return false; } return true; };
    const add = (x: number, y: number, d: number) => { const q = xs.length; xs.push(x); ys.push(y); ds.push(d); grid[gi(x, y)] = q; return q; };
    const grow = (q0: number) => { const act = [q0]; while (act.length) { const ai = Math.floor(r() * act.length), q = act[ai]; let found = false; for (let t = 0; t < 16; t++) { const a = r() * TAU, rr = ds[q] * (1 + r()), x = xs[q] + Math.cos(a) * rr, y = ys[q] + Math.sin(a) * rr; if (x < b.x0 + 1 || y < b.y0 + 1 || x >= b.x1 - 1 || y >= b.y1 - 1) continue; const d = spacing(x, y); if (!d || !ok(x, y, d)) continue; act.push(add(x, y, d)); found = true; } if (!found) { act[ai] = act[act.length - 1]; act.pop(); } } };
    for (let y = b.y0 + 4; y < b.y1 - 1; y += 9) for (let x = b.x0 + 4; x < b.x1 - 1; x += 9) { const px = Math.max(b.x0 + 1, x + (r() - 0.5) * 6), py = Math.max(b.y0 + 1, y + (r() - 0.5) * 6); if (px >= b.x1 - 1 || py >= b.y1 - 1) continue; const d = spacing(px, py); if (d && ok(px, py, d)) grow(add(px, py, d)); }
    const phases: Mk[][] = [[], [], [], []];
    xs.forEach((x, i) => {
      const y = ys[i], t = tone(x, y), L = Math.max(4, lenAt(x, y)) * (0.7 + r() * 0.6), rank = r(), bend = (r() - 0.5) * 0.5, dev = (r() - 0.5) * 0.24, step = Math.max(1.2, L / 14), pts: P[] = [[x, y]]; let px = x, py = y, s = 0;
      while (s < L) { const a = angle(px, py) + dev + bend * (s / L); px += Math.cos(a) * step; py += Math.sin(a) * step; s += step; pts.push([px, py]); }
      const tp = taper(pts.length, 1), w = pts.map((p, j) => tp[j] * wOf(tone(p[0], p[1])));
      phases[rank < 0.34 ? 0 : t < 0.5 ? 1 : 3].push(cutMark({ pts, w, alpha: 0.9 + 0.08 * r() }, 1));
      const mid = clamp(1 - Math.abs(t - 0.38) / 0.22);
      if (o.cross !== false && mid > 0 && r() < 0.6 * mid) { const a = angle(x, y) + (r() < 0.5 ? 0.62 : -0.62), l = L * 0.5, mx = x + Math.cos(angle(x, y)) * L * 0.3, my = y + Math.sin(angle(x, y)) * L * 0.3; phases[2].push(cutMark({ pts: [[mx - (Math.cos(a) * l) / 2, my - (Math.sin(a) * l) / 2], [mx, my], [mx + (Math.cos(a) * l) / 2, my + (Math.sin(a) * l) / 2]], w: taper(3, 0.75 * wOf(t), 0.2, 0.6), alpha: 0.85 }, 0.5)); }
    });
    return addCuts(W, phases.flat(), o.chunk ?? 300);
  }
  /** One long knife line, watched being cut: widest where the blade bites, tapering as it lifts. */
  knife(W: Work, pts: P[], o: { w?: number; alpha?: number; closed?: boolean; tail?: number } = {}) { const s = sample(pts, !!o.closed, 8); return addCuts(W, [cutMark({ pts: s, w: taper(s.length, o.w ?? 2, o.tail ?? 0.2, 0.6), alpha: o.alpha ?? 0.97 }, 6 + plen(s) * 0.25)], 1); }
  /** Parallel cuts across a hairless surface. Each cut's width follows tone(x, y). */
  cuts(W: Work, shape: P[], o: { tone?: ToneFn; angle?: number; gap?: number; w?: number; seed?: number } = {}) {
    const { tone = () => 0.6, angle = 0.3, gap = 4, w = 1.6, seed = 7 } = o, r = rng(seed);
    return addCuts(W, hatchPieces(shape, angle, gap, (x, y) => tone(x, y) > 0.04, seed, [6, 18], r).filter((s) => s.length > 1).map((seg) => cutMark({ pts: seg, w: seg.map((p, i) => w * clamp(tone(p[0], p[1])) * Math.max(0.2, Math.pow(1 - i / seg.length, 0.5))), alpha: 0.95 }, 2)), 120);
  }
  /** A row of short bright flicks just inside an edge that faces the light: how a lit contour reads on fur. light is a direction. Say flow to lay them with the hair. */
  rim(W: Work, outline: P[], o: { light?: P; flow?: number | ToneFn; len?: number; seed?: number; minFace?: number } = {}) {
    const light = o.light ?? [0.75, -0.65], l = Math.hypot(light[0], light[1]) || 1, ux = light[0] / l, uy = light[1] / l, r = rng(o.seed ?? 5), s = sample(outline, true, 24), n = s.length, area = s.reduce((a, p, i) => a + p[0] * s[(i + 1) % n][1] - s[(i + 1) % n][0] * p[1], 0), out = area > 0 ? 1 : -1, ang = typeof o.flow === "function" ? o.flow : () => (o.flow as number) ?? -1.2, L0 = o.len ?? 14 * (Math.min(this.w, this.h) / 1080), marks: Mk[] = [];
    s.forEach((p, i) => { const a = s[(i - 1 + n) % n], b = s[(i + 1) % n], tx = b[0] - a[0], ty = b[1] - a[1], m = Math.hypot(tx, ty) || 1, nx = (ty / m) * out, ny = (-tx / m) * out, f = nx * ux + ny * uy; if (f < (o.minFace ?? 0.2) || r() > 0.85) return; const d = 2 + r() * 7, x = p[0] - nx * d, y = p[1] - ny * d, L = L0 * (0.5 + 0.7 * r()), an = ang(x, y) + (r() - 0.5) * 0.3, pts: P[] = []; for (let q = 0; q <= 6; q++) pts.push([x + (Math.cos(an) * L * q) / 6 + (r() - 0.5) * 0.4, y + (Math.sin(an) * L * q) / 6 + (r() - 0.5) * 0.4]); marks.push(cutMark({ pts, w: taper(7, 1.1 + 1.1 * f, 0.15, 0.8), alpha: 0.97 }, 1)); });
    return addCuts(W, marks, 120);
  }
  /** A light scraped flat with the blade: a catchlight. */
  scrape(W: Work, shape: P[], o: { alpha?: number } = {}) { return addCuts(W, [cutMark({ pts: shape, w: [], alpha: o.alpha ?? 0.97, fill: true }, 4)], 1); }
  /** Capitals cut with the nib, stroke by stroke. */
  write(W: Work, text: string, x: number, y: number, o: { cap?: number; seed?: number; align?: "left" | "center" | "right"; w?: number; color?: string } = {}) { return run(W, [lettering(text, x, y, { cap: 24, slant: 0.12, opacity: 0.95, ...o, color: o.color ?? CLAY })], { textures: ["draftTooth"] }); }
  /** Kept so a scene ends the same way in every hand: the board has no grain of its own. */
  finish(_g: Ctx) { /* nothing */ }
}

register("scratchboard", { start: (w: number, h: number, o?: { scale?: number }) => new ScratchHand(w, h, o) });
