// letitedit hand: pen-and-ink stipple. M.look.stipple.start(w, h, {scale}) turns a tone you write into thousands of dots from one pen; the AI writes
// the scene and its tones. See motion\runtime\looks\stipple.md.
//
// Adapted from anidoodle's canvas-core/stipple.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77): the variable-radius dot field, the order
// by passes and patches and the dot's shape are taken from it. Changed by letitedit, 4 Nov 2026: the tone comes from the scene and not a raster of its
// nautilus, a field covers a box of any size, spacing and nib scale with the frame; the nautilus (stippleKit) and film clock are left out; marks go on a Work (.\worked.ts).
import { rng, type Ctx, type P } from "./anidoodle/core";
import { clamp } from "./anidoodle/gallery";
import { MarkHand, lettering, run, type Box, type ToneFn } from "./marks";
import { register } from "./shared";
import type { Work } from "./worked";

const INK = "#15120e", PAPER = "#fbfaf5", PASSES = 6, V = 7;

class StippleHand extends MarkHand {
  palette = { ink: INK, paper: PAPER };
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, { nib: 1, taper: 0.3, pressure: 0.3, retrace: false, wobble: 0.4, rough: 0.3 }); }
  /** The bright bristol: a plate. */
  paper(id = "paper", o: { box?: Box; color?: string } = {}) { const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }; return this.plate(id, (c) => { c.fillStyle = o.color ?? PAPER; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); }, b); }
  /** Dots following a tone: tone(x, y) 0 is bare paper, 1 is nearly solid. Dark masses go in first, then the mid tones, then a few over the lights, patch by patch. There is no outline: an edge is where the density changes. Say how many dots with .count. */
  dots(W: Work, tone: ToneFn, o: { box?: Box; seed?: number; size?: number; color?: string; chunk?: number } = {}) {
    const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, size = o.size ?? Math.max(0.75, Math.min(this.w, this.h) / 1080), color = o.color ?? INK, DOT = 1.22 * size, chunk = o.chunk ?? 500, r = rng(o.seed ?? 20260925);
    const MIN_T = 0.022, at = (x: number, y: number) => clamp(tone(x, y)), spacing = (t: number) => (1.5 * size) / Math.pow(Math.max(t, MIN_T), 0.64);
    const cell = 1.35 * size, gw = Math.ceil((b.x1 - b.x0) / cell), gh = Math.ceil((b.y1 - b.y0) / cell), grid = new Int32Array(gw * gh).fill(-1), xs: number[] = [], ys: number[] = [], rs: number[] = [];
    const ok = (x: number, y: number, d: number) => { const reach = Math.ceil((d * 1.25) / cell), gx = Math.floor((x - b.x0) / cell), gy = Math.floor((y - b.y0) / cell); for (let j = Math.max(0, gy - reach); j <= Math.min(gh - 1, gy + reach); j++) for (let i = Math.max(0, gx - reach); i <= Math.min(gw - 1, gx + reach); i++) { const k = grid[j * gw + i]; if (k < 0) continue; const dx = xs[k] - x, dy = ys[k] - y, m = 0.5 * (d + rs[k]); if (dx * dx + dy * dy < m * m) return false; } return true; };
    const add = (x: number, y: number, d: number) => { const k = xs.length; xs.push(x); ys.push(y); rs.push(d); grid[Math.floor((y - b.y0) / cell) * gw + Math.floor((x - b.x0) / cell)] = k; return k; };
    const grow = (k0: number) => { const active = [k0]; while (active.length) { const ai = Math.floor(r() * active.length), k = active[ai]; let found = false; for (let n = 0; n < 18; n++) { const a = r() * Math.PI * 2, rr = rs[k] * (1 + r()), x = xs[k] + Math.cos(a) * rr, y = ys[k] + Math.sin(a) * rr; if (x < b.x0 + 1 || y < b.y0 + 1 || x >= b.x1 - 1 || y >= b.y1 - 1) continue; const t = at(x, y); if (t < MIN_T) continue; const d = spacing(t); if (!ok(x, y, d)) continue; active.push(add(x, y, d)); found = true; } if (!found) { active[ai] = active[active.length - 1]; active.pop(); } } };
    const lat = 7 * size; for (let y = b.y0 + 3; y < b.y1 - 1; y += lat) for (let x = b.x0 + 3; x < b.x1 - 1; x += lat) { const px = Math.max(b.x0 + 1, x + (r() - 0.5) * 5), py = Math.max(b.y0 + 1, y + (r() - 0.5) * 5); if (px >= b.x1 - 1 || py >= b.y1 - 1) continue; const t = at(px, py); if (t < MIN_T) continue; const d = spacing(t); if (ok(px, py, d)) grow(add(px, py, d)); }
    // order: darkest first, with a random rank so later passes also deepen what's dark; within a pass, a snake of patches
    const PATCH = 84 * size, keyed = xs.map((x, i) => ({ x, y: ys[i], key: 1 - at(x, ys[i]) + 0.42 * r(), pass: 0 })); let lo = 1e9, hi = -1e9; keyed.forEach((d) => { lo = Math.min(lo, d.key); hi = Math.max(hi, d.key); });
    keyed.forEach((d) => { d.pass = Math.min(PASSES - 1, Math.floor(Math.pow((d.key - lo) / (hi - lo + 1e-9), 1.25) * PASSES)); });
    const patchOf = (d: { x: number; y: number }) => { const py = Math.floor((d.y - b.y0) / PATCH), px0 = Math.floor((d.x - b.x0) / PATCH); return py * 1024 + (py % 2 ? 512 - px0 : px0); };
    keyed.sort((p, q) => p.pass - q.pass || patchOf(p) - patchOf(q) || p.key - q.key);
    const n = keyed.length, shape = new Float32Array(n * V * 2), alpha = new Uint8Array(n), tilt = -0.62;
    keyed.forEach((d, i) => { const s = rng(i * 7919 + 17), rad = DOT * (0.9 + s() * 0.24), el = 1.06 + s() * 0.12, ph = s() * 6.283, h2 = s() * 0.1, h3 = s() * 0.08, tail = s() < 0.035; alpha[i] = s() < 0.04 ? 150 : 236; for (let v = 0; v < V; v++) { const a = (v / V) * Math.PI * 2, k = 1 + h2 * Math.sin(2 * a + ph) + h3 * Math.sin(3 * a + ph * 1.7); let ex = Math.cos(a) * rad * k * el; const ey = Math.sin(a) * rad * k; if (tail && v === 0) ex += rad * 1.3; shape[(i * V + v) * 2] = d.x + ex * Math.cos(tilt) - ey * Math.sin(tilt); shape[(i * V + v) * 2 + 1] = d.y + ex * Math.sin(tilt) + ey * Math.cos(tilt); } });
    for (let a = 0; a < n; a += chunk) { const e = Math.min(n, a + chunk);
      W.add(e - a, (G, q) => { const c = G.cur, m = q >= 1 ? e : a + Math.floor((e - a) * q); if (m <= a) return; c.fillStyle = color; [0, 1].forEach((cls) => { const path = new Path2D(); for (let i = a; i < m; i++) { if ((alpha[i] < 200 ? 1 : 0) !== cls) continue; const o0 = i * V * 2; path.moveTo(shape[o0], shape[o0 + 1]); for (let v = 1; v < V; v++) path.lineTo(shape[o0 + v * 2], shape[o0 + v * 2 + 1]); path.closePath(); } c.globalAlpha = cls ? 0.6 : 0.95; c.fill(path); }); c.globalAlpha = 1; }); }
    return { count: n };
  }
  /** Capitals: the one concession to line, in the same pen. */
  write(W: Work, text: string, x: number, y: number, o: { cap?: number; seed?: number; align?: "left" | "center" | "right"; w?: number; color?: string } = {}) { return run(W, [lettering(text, x, y, { cap: 24, slant: 0, opacity: 0.95, w: 1.3, ...o, color: o.color ?? INK })]); }
  /** The sheet's faint tooth over the finished frame, in screen space: last thing in the frame. */
  finish(g: Ctx, o: { paper?: number } = {}) { this.grain(g, [["paper", o.paper ?? 0.05]]); }
}
export type { P };

register("stipple", { start: (w: number, h: number, o?: { scale?: number }) => new StippleHand(w, h, o) });
