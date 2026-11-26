// letitedit hand: flat vector, editorial illustration. M.look.flatVector.start(w, h, {scale}) gives the marks; the AI writes the
// scene. See motion\runtime\looks\flatVector.md.
//
// Adapted from anidoodle's canvas-core/flatVector.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77).
// Changed by letitedit, 4 Nov 2026: its construction helpers, long shadow, grain brush and pen-tool picture are taken from that
// file; the regatta and its film timeline are left out; grain is baked into plates through the context's transform (.\shared.ts);
// fill(), colour steps, dashes() and figure() are ours.
import { fractal, oval, rng, type Ctx, type Layer, type P } from "./anidoodle/core";
import { bounds, clamp, mix, smooth } from "./anidoodle/gallery";
import { Hand, register } from "./shared";

const C = { sky: "#f6e5cf", cloud: "#fcf3e6", far: "#cdbbd6", farShade: "#b9a6c8", midLight: "#9fbdab", mid: "#86ad9d", midShade: "#6f9a8b", deep: "#2f6b63", deepShade: "#22524c", shore: "#4f8a72", shoreShade: "#3d7360", sand: "#ecc99a", bay: "#3a7ca1", bayHigh: "#6ea6c1", bayMid: "#4c8db1", bayFar: "#2f6a90", glint: "#f7dcaa", foam: "#d6e9ee", dash: "#8fc2d6", coral: "#ee7a58", mustard: "#f1b74a", navy: "#1f3a56", bone: "#fcf8ef", teal: "#3f9c8f" };
const NAVY_RGB = "31,58,86", UI = "#2b7bf6";

type Grain = { ang: number; k: number; from?: number; color?: string };
type Paint = string | ((c: Ctx) => CanvasGradient);
const rgbOf = (hex: string) => { const s = hex.replace("#", ""); return `${parseInt(s.slice(0, 2), 16)},${parseInt(s.slice(2, 4), 16)},${parseInt(s.slice(4, 6), 16)}`; };

// ---------------------------------------------------------------- construction
const sm = (a: P[], closed = true, per = 8) => smooth(a, closed, per);
const ridge = (top: P[], base: number): P[] => { const t = sm(top, false, 10); return [...t, [t[t.length - 1][0], base], [t[0][0], base]]; };
const cloud = (x: number, y: number, s: number): P[] => sm([[x - 110 * s, y], [x - 92 * s, y - 28 * s], [x - 52 * s, y - 38 * s], [x - 28 * s, y - 70 * s], [x + 22 * s, y - 76 * s], [x + 50 * s, y - 44 * s], [x + 88 * s, y - 40 * s], [x + 112 * s, y]], false, 10);
const rot = (pts: P[], o: P, ang: number, s = 1): P[] => { const c = Math.cos(ang), n = Math.sin(ang); return pts.map(([x, y]) => [o[0] + (x * c - y * n) * s, o[1] + (x * n + y * c) * s] as P); };
const capsule = (a: P, b: P, r: number): P[] => { const ang = Math.atan2(b[1] - a[1], b[0] - a[0]), out: P[] = []; for (let i = 0; i <= 6; i++) { const t = ang + Math.PI / 2 + (i / 6) * Math.PI; out.push([a[0] + Math.cos(t) * r, a[1] + Math.sin(t) * r]); } for (let i = 0; i <= 6; i++) { const t = ang - Math.PI / 2 + (i / 6) * Math.PI; out.push([b[0] + Math.cos(t) * r, b[1] + Math.sin(t) * r]); } return out; };
const band = (y0: number, y1: number, W: number, amp = 0, ph = 0, n = 9): P[] => { const top: P[] = Array.from({ length: n }, (_, i) => [(i * W) / (n - 1), y0 + Math.sin(i * 1.3 + ph) * amp] as P), t = sm(top, false, 10); return [...t, [W, y1], [0, y1]]; };
// the caster's points thrown along the ground by a low sun: dir 1 = to the right, -1 = to the left
const throwShadow = (pts: P[], y0: number, o: { len?: number; drop?: number; dir?: number } = {}): P[] => { const { len = 1.4, drop = 0.34, dir = 1 } = o; return pts.map(([x, y]) => [x + dir * Math.max(0, y0 - y) * len, y0 + Math.max(0, y0 - y) * drop]); };
const ramp = (a: P, b: P, alpha: number, rgb = NAVY_RGB) => (c: Ctx) => { const g = c.createLinearGradient(a[0], a[1], b[0], b[1]); g.addColorStop(0, `rgba(${rgb},${alpha})`); g.addColorStop(1, `rgba(${rgb},0)`); return g; };
const trace = (c: Ctx, ps: P[][]) => { c.beginPath(); ps.forEach((p) => { p.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); }); };
const list = (s: P[] | P[][]): P[][] => (typeof (s as P[][])[0][0] === "number" ? [s as P[]] : (s as P[][]));
/** A run of n colours from far to near, each a step of atmosphere: the depth of a flat picture. */
const steps = (far: string, near: string, n: number) => Array.from({ length: n }, (_, i) => mix(far, near, n < 2 ? 0 : i / (n - 1)));

// the first q of a polyline, by arc length (from anidoodle's koiDrawKit)
const cut = (s: P[], q: number): P[] => {
  if (q >= 1) return s;
  const cum = [0]; for (let i = 1; i < s.length; i++) cum.push(cum[i - 1] + Math.hypot(s[i][0] - s[i - 1][0], s[i][1] - s[i - 1][1]));
  const want = cum[cum.length - 1] * Math.max(0, q), out: P[] = [s[0]];
  for (let i = 1; i < s.length; i++) { if (cum[i] <= want) { out.push(s[i]); continue; } const f = (want - cum[i - 1]) / (cum[i] - cum[i - 1] || 1); out.push([s[i - 1][0] + (s[i][0] - s[i - 1][0]) * f, s[i - 1][1] + (s[i][1] - s[i - 1][1]) * f]); break; }
  return out.length > 1 ? out : [s[0], s[0]];
};

class FlatHand extends Hand {
  palette = C; UI = UI;
  sm = sm; smooth = smooth; ridge = ridge; cloud = cloud; rot = rot; capsule = capsule; throwShadow = throwShadow; ramp = ramp; steps = steps; mix = mix; rng = rng; fractal = fractal; oval = oval; bounds = bounds; clamp = clamp; trace = trace;
  band(y0: number, y1: number, amp = 0, ph = 0) { return band(y0, y1, this.w, amp, ph); }
  private tile(rgb: string): Layer {
    const key = `grain:${rgb}:${this.scale}`; let L = this.env.cache.get(key) as Layer | undefined; if (L) return L;
    const n = Math.round(240 * this.scale); L = this.env.canvas(n, n); const img = L.ctx.createImageData(n, n), d = img.data, r = rng(4242), [R, G, B] = rgb.split(",").map(Number);
    for (let i = 0; i < n * n; i++) { const v = r(); if (v < 0.34) { d[i * 4] = R; d[i * 4 + 1] = G; d[i * 4 + 2] = B; d[i * 4 + 3] = Math.round(90 + r() * 165); } }
    L.ctx.putImageData(img, 0, 0); this.env.cache.set(key, L); return L;
  }
  /** The grain brush: speckle clipped to the shape, nothing on the lit side and full on the shade side. ang = the direction the shade lies in (radians). */
  grain(c: Ctx, shape: P[] | P[][], g: Grain) {
    const ps = list(shape), b0 = bounds(ps.flat()), k = this.scale, b = { x0: b0.x0 - 2, y0: b0.y0 - 2, x1: b0.x1 + 2, y1: b0.y1 + 2 }, W = Math.ceil((b.x1 - b.x0) * k), H = Math.ceil((b.y1 - b.y0) * k);
    if (W < 1 || H < 1) return;
    const T = this.env.canvas(W, H), t = T.ctx; t.setTransform(k, 0, 0, k, -b.x0 * k, -b.y0 * k); t.save(); trace(t, ps); t.clip();
    t.setTransform(1, 0, 0, 1, 0, 0); t.fillStyle = t.createPattern(this.tile(rgbOf(g.color ?? C.navy)).canvas as CanvasImageSource, "repeat")!; t.fillRect(0, 0, W, H); t.restore();
    t.setTransform(k, 0, 0, k, -b.x0 * k, -b.y0 * k);
    const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2, R = Math.hypot(b.x1 - b.x0, b.y1 - b.y0) / 2, dx = Math.cos(g.ang), dy = Math.sin(g.ang), from = g.from ?? 0.15, gr = t.createLinearGradient(cx - dx * R, cy - dy * R, cx + dx * R, cy + dy * R);
    gr.addColorStop(0, "rgba(0,0,0,0)"); gr.addColorStop(from, "rgba(0,0,0,0)"); gr.addColorStop(1, "rgba(0,0,0,1)");
    t.globalCompositeOperation = "destination-in"; t.fillStyle = gr; t.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
    c.save(); c.globalAlpha *= g.k; c.drawImage(T.canvas as CanvasImageSource, b.x0, b.y0, W / k, H / k); c.restore();
  }
  /** One closed path, one flat colour, no line, and its grain if asked. Paint a plate with these (grain is too slow per frame). */
  fill(c: Ctx, shape: P[] | P[][], paint: Paint, o: { grain?: Grain; alpha?: number } = {}) {
    const ps = list(shape); c.save(); if (o.alpha !== undefined) c.globalAlpha *= o.alpha; c.fillStyle = typeof paint === "string" ? paint : paint(c); trace(c, ps); c.fill("nonzero"); c.restore();
    if (o.grain) this.grain(c, ps, o.grain);
  }
  /** A cast shadow: the caster's points thrown along the ground, fading to nothing. */
  longShadow(c: Ctx, pts: P[], y0: number, o: { len?: number; drop?: number; dir?: number; alpha?: number; color?: string } = {}) {
    const s = throwShadow(pts, y0, o), far = s.reduce((a, p) => (Math.abs(p[0] - pts[0][0]) > Math.abs(a[0] - pts[0][0]) ? p : a), s[0]), foot: P = [pts.reduce((a, p) => a + p[0], 0) / pts.length, y0];
    this.fill(c, s, ramp(foot, far, o.alpha ?? 0.45, rgbOf(o.color ?? C.navy)));
  }
  /** Short rounded dashes in a drift: water chop, wind, sparkle, a dotted texture on a plane. */
  dashes(c: Ctx, o: { cx: number; cy: number; n: number; spread: number; s?: number; color?: string; seed?: number; squash?: number }) {
    const r = rng(o.seed ?? 5), s = o.s ?? 1, out: P[][] = [];
    for (let i = 0; i < o.n; i++) { const a = r() * Math.PI * 2, d = Math.sqrt(r()) * o.spread, x = o.cx + Math.cos(a) * d * 1.8, y = o.cy + Math.sin(a) * d * (o.squash ?? 0.5), l = (14 + r() * 26) * s; out.push(capsule([x, y], [x + l, y], 2.4 * s)); }
    this.fill(c, out, o.color ?? C.dash);
  }
  /** The vector app at work over a shape being drawn: blue path, white anchors, the live anchor's handles. q 0..1; gone at 1. Optional. */
  penTool(g: Ctx, poly: P[], anchors: P[], q: number) {
    if (q <= 0 || q >= 1) return;
    g.save(); g.lineWidth = 1.4; g.strokeStyle = UI; g.lineJoin = "round";
    const drawn = cut([...poly, poly[0]], q); g.beginPath(); drawn.forEach(([x, y], j) => (j ? g.lineTo(x, y) : g.moveTo(x, y))); g.stroke();
    const na = Math.min(anchors.length, Math.ceil(q * anchors.length + 1e-9));
    for (let j = 0; j < na; j++) { const [x, y] = anchors[j]; g.fillStyle = j === na - 1 ? UI : "#ffffff"; g.fillRect(x - 3.5, y - 3.5, 7, 7); g.strokeRect(x - 3.5, y - 3.5, 7, 7); }
    if (na > 0) { const [x, y] = anchors[na - 1], nx = anchors[Math.min(anchors.length - 1, na)], px = anchors[Math.max(0, na - 2)], hx = (nx[0] - px[0]) * 0.18, hy = (nx[1] - px[1]) * 0.18; g.beginPath(); g.moveTo(x - hx, y - hy); g.lineTo(x + hx, y + hy); g.stroke(); [[x - hx, y - hy], [x + hx, y + hy]].forEach(([a, b]) => { g.beginPath(); g.arc(a, b, 3.2, 0, Math.PI * 2); g.fillStyle = "#ffffff"; g.fill(); g.stroke(); }); }
    g.restore();
  }
  /** Paper tooth over the finished frame, very light: vectors have none, the screen-print feel is optional. */
  finish(g: Ctx, o: { paper?: number; vignette?: string | null } = {}) { this.sheet(g, { paper: o.paper ?? 0, vignette: o.vignette === undefined ? null : o.vignette }); }
}

register("flatVector", { start: (w: number, h: number, o?: { scale?: number }) => new FlatHand(w, h, o) });
