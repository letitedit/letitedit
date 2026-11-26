// letitedit hand: storybook pencil and watercolour. M.look.storybook.start(w, h, {scale}) gives soft graphite and pan watercolour on warm cold-press,
// laid in a picture-book illustrator's order; the page is written fresh by the AI. See motion\runtime\looks\storybook.md.
//
// Adapted from anidoodle's canvas-core/storybook.ts and storybookDraw.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Changed by
// letitedit, 4 Nov 2026: the shaded hand and the limb are taken from storybook.ts as functions of a recorded list; its character and page are
// left out; the mark list, parts and takes are ours (.\marksRoll.ts), written from storybookDraw's order. That style had no kit of its own:
// its marks are core's pen, wash and form, here in its own order.
import { GRAPHITE, PENCIL, TINT, line, oval, rng, tube, turn, type Ctx, type P } from "./anidoodle/core";
import { bounds, mix, smooth } from "./anidoodle/gallery";
import { keepCorners, Marks, Rolled } from "./marksRoll";
import { Hand, register } from "./shared";

export const SHADE: Record<string, string> = { white: "#c9d2e4", rose: "#cf8291", denim: "#52739f", butter: "#d9b24f", sage: "#7ea27b", sky: "#7fa4c9", peach: "#d99567", lilac: "#a18fbd", blush: "#d0667c", glow: "#e8c871" };
const BLUE = "#8d90a6", SHEET = "#fbf4e4", RANK = { construct: 0, sketch: 1, wash: 2, line: 3, flick: 4 };
type PenO = { w?: number; closed?: boolean; seed?: number; wobble?: number; boil?: number; taper?: number; opacity?: number; retrace?: boolean; color?: string };
type Pose = "open" | "rest";
const lenOf = (s: P[]) => s.reduce((a, q, i) => (i ? a + Math.hypot(q[0] - s[i - 1][0], q[1] - s[i - 1][1]) : 0), 0);
const spread = (c: Ctx, b: { x0: number; y0: number; x1: number; y1: number }, p: number, fn: () => void) => { if (p >= 1) return fn(); const R = Math.hypot(b.x1 - b.x0, b.y1 - b.y0) * (1 - (1 - p) ** 2) + 2, tx = b.x0 + (b.x1 - b.x0) * 0.25, ty = b.y0 + (b.y1 - b.y0) * 0.25; c.save(); c.beginPath(); for (let k = 0; k <= 36; k++) { const a = (k / 36) * 6.2832, rr = R * (1 + 0.05 * Math.sin(a * 5)); if (k) c.lineTo(tx + Math.cos(a) * rr, ty + Math.sin(a) * rr); else c.moveTo(tx + Math.cos(a) * rr, ty + Math.sin(a) * rr); } c.closePath(); c.clip(); fn(); c.restore(); };

// a hand in local units: wrist at the origin, pointing along +x; open or at rest (taken from storybook.ts)
const handShape = (pose: Pose, k: number) => {
  const R = 13 * k, c: P = [15 * k, 0], spec = pose === "open" ? { a: [-0.62, -0.04, 0.54], len: 17, w: 0.3, thumb: [-1.75, 13] } : { a: [-0.46, 0.0, 0.46], len: 10, w: 0.2, thumb: [-1.5, 10] };
  const on = (ang: number, r: number): P => [c[0] + Math.cos(ang) * r, c[1] + Math.sin(ang) * r], pts: P[] = [[0, -7.5 * k], [5 * k, -11 * k]], ta = spec.thumb[0], tl = spec.thumb[1] * k, valleys: P[] = [];
  pts.push(on(ta - 0.34, R), on(ta - 0.16, R + tl * 0.8), on(ta, R + tl), on(ta + 0.2, R + tl * 0.7), on(ta + 0.36, R * 0.98));
  spec.a.forEach((a, i) => { const L = spec.len * k * (i === 1 ? 1.08 : 1); pts.push(on(a - spec.w, R + L * 0.55), on(a - spec.w * 0.5, R + L * 0.95), on(a, R + L), on(a + spec.w * 0.5, R + L * 0.95), on(a + spec.w, R + L * 0.55)); if (i < 2) { const v = on((a + spec.a[i + 1]) / 2, pose === "open" ? R : R + L * 0.42); pts.push(v); valleys.push(v); } });
  pts.push(on(1.15, R), on(1.9, R * 0.98), [5 * k, 11 * k], [0, 7.5 * k]);
  return { pts, valleys, c };
};

/** One page being recorded. Inside a part, marks go down construction, light pencil, washes, final line, flicks; k.part() starts the next thing up the stack. */
class Draw extends Marks {
  /** The barely-there blue-grey construction lines: ovals, a gesture line. They stay in the finished page, as they do in real picture books. */
  construct(pts: P[], o: PenO = {}) { const s = keepCorners(o.closed ? [...pts, pts[0]] : pts), seed = o.seed ?? this.list.length + 2, b = bounds(s); return this.add(RANK.construct, Math.pow(lenOf(s), 0.7) * 0.4 + 2, (G, p) => G.group("ink", () => { G.touch(b.x0 - 8, b.y0 - 8, b.x1 + 8, b.y1 + 8); G.pen(s, { w: 1.1, color: BLUE, seed, wobble: 0.7, boil: 0, opacity: 0.5, retrace: false, progress: p }); })); }
  /** A graphite line: drawn twice, once lightly before the paint and again at full weight over the dry paint. */
  pen(pts: P[], o: PenO = {}) {
    const seed = o.seed ?? this.list.length + 3, s = keepCorners(o.closed ? [...pts, pts[0]] : pts), b = bounds(s), L = lenOf(s), w = o.w ?? 3.2, color = o.color ?? GRAPHITE;
    this.add(RANK.sketch, Math.pow(L, 0.7) * 0.5 + 2, (G, p) => G.group("ink", () => { G.touch(b.x0 - 8, b.y0 - 8, b.x1 + 8, b.y1 + 8); G.pen(s, { w: w * 0.62, color, seed, wobble: o.wobble ?? 0.8, boil: 0, opacity: 0.36, retrace: false, taper: o.taper ?? 1, progress: p }); }));
    return this.add(RANK.line, Math.pow(L, 0.7) * 0.7 + 3, (G, p) => G.group("ink", () => { G.touch(b.x0 - 8, b.y0 - 8, b.x1 + 8, b.y1 + 8); G.pen(s, { w, color, seed, wobble: o.wobble ?? 0.8, boil: o.boil ?? 0.35, opacity: o.opacity ?? 0.96, retrace: o.retrace ?? true, taper: o.taper ?? 1, progress: p }); }));
  }
  /** A flat watercolour wash that never quite fills its outline; the pigment settles at the edge. */
  wash(pts: P[], color: string, o: { alpha?: number; seed?: number; dx?: number; dy?: number; shrink?: number; rim?: boolean } = {}) { const b = bounds(pts), seed = o.seed ?? this.list.length + 7; return this.add(RANK.wash, Math.sqrt((b.x1 - b.x0) * (b.y1 - b.y0)) * 0.3 + 5, (G, p) => G.group("paint", () => { G.touch(b.x0 - 20, b.y0 - 20, b.x1 + 20, b.y1 + 20); spread(G.cur, b, p, () => G.wash(pts, color, { ...o, seed })); })); }
  /** A wash with form: the colour shifted toward the light (up and left by default) over its shade, wet in wet. hi = [x, y, rx, ry, angle] lifts a highlight. */
  form(pts: P[], color: string, shade?: string, o: { seed?: number; light?: P; alpha?: number; hi?: number[] } = {}) { const b = bounds(pts), seed = o.seed ?? this.list.length + 9, sh = shade ?? mix(color, "#4a5170", 0.38); return this.add(RANK.wash, Math.sqrt((b.x1 - b.x0) * (b.y1 - b.y0)) * 0.3 + 5, (G, p) => G.group("paint", () => { G.touch(b.x0 - 20, b.y0 - 20, b.x1 + 20, b.y1 + 20); spread(G.cur, b, p, () => G.form(pts, color, sh, { ...o, seed })); })); }
  /** Pencil hatching: short parallel marks along width w at (x, y), a cast shadow or the side of a form. */
  hatch(x: number, y: number, w: number, o: { n?: number; len?: number; angle?: number; color?: string; seed?: number; pw?: number; opacity?: number } = {}) { const seed = o.seed ?? this.list.length + 11; return this.add(RANK.line, 4, (G, p) => { if (p < 1) return; G.group("ink", () => { G.touch(x - 24, y - 24 - (o.len ?? 16), x + w + 24, y + 24 + (o.len ?? 16)); G.hatch(x, y, w, { ...o, seed }); }); }); }
  /** Paint flicked off the brush: small dots over the area, the last thing on the page. */
  flick(area: { x0: number; y0: number; x1: number; y1: number }, color: string, o: { n?: number; seed?: number; alpha?: number } = {}) { const seed = o.seed ?? this.list.length + 13; return this.add(RANK.flick, 3, (G, p) => { if (p <= 0) return; const r = rng(seed), n = Math.floor((o.n ?? 14) * p); G.group("paint", () => { G.touch(area.x0, area.y0, area.x1, area.y1); const c = G.cur; c.fillStyle = color; c.globalAlpha = o.alpha ?? 0.5; for (let i = 0; i < n; i++) { c.beginPath(); c.arc(area.x0 + r() * (area.x1 - area.x0), area.y0 + r() * (area.y1 - area.y0), 0.8 + r() * 2.4, 0, 6.2832); c.fill(); } c.globalAlpha = 1; }); }); }
  /** A soft arm or leg: from to to, bent by bend, radius r, with its wash and its line and the small creases of a sleeve. */
  limb(from: P, to: P, bend: number, r: number, color: string, o: { seed?: number; shade?: string; creases?: boolean } = {}) {
    const seed = o.seed ?? this.list.length + 17, mid = line(from, to, bend)[1], shape = tube([from, mid, to], r, r * 0.86, false), along = (t: number): P => { const a = t < 0.5 ? from : mid, b = t < 0.5 ? mid : to, u = t < 0.5 ? t * 2 : (t - 0.5) * 2; return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u]; };
    this.form(shape, color, o.shade, { seed, light: [-3, -3] }); this.pen(shape, { closed: true, w: 2.8, seed: seed + 1, wobble: 0.5, taper: 0.4 });
    if (o.creases) [0.2, 0.36, 0.52, 0.68, 0.84].forEach((t, i) => { const p = along(t), q = along(t + 0.04), a = Math.atan2(q[1] - p[1], q[0] - p[0]) + Math.PI / 2; this.pen(line([p[0] - Math.cos(a) * r * 0.85, p[1] - Math.sin(a) * r * 0.85], [p[0] + Math.cos(a) * r * 0.85, p[1] + Math.sin(a) * r * 0.85], 2.2), { w: 1.7, seed: seed + 2 + i, wobble: 0.2, opacity: 0.6, retrace: false }); });
    return this;
  }
  /** A hand at the wrist, pointing along angle: "open" or "rest", with k its size. */
  hand(wrist: P, angle: number, pose: Pose = "open", o: { k?: number; color?: string; shade?: string; seed?: number } = {}) {
    const seed = o.seed ?? this.list.length + 19, k = o.k ?? 1, flip = Math.cos(angle) < 0 ? -1 : 1, place = (pts: P[]): P[] => turn(pts.map(([x, y]) => [wrist[0] + x, wrist[1] + y * flip] as P), wrist[0], wrist[1], (angle * 180) / Math.PI), h = handShape(pose, k), shape = place(h.pts);
    this.form(shape, o.color ?? TINT.white, o.shade ?? SHADE.white, { seed, light: [-3, -4] }); this.pen(shape, { closed: true, w: 2.9, seed: seed + 2, wobble: 0.5, taper: 0.5 });
    if (pose === "open") h.valleys.forEach((v, i) => { const inner: P = [v[0] + (h.c[0] - v[0]) * 0.32, v[1] + (h.c[1] - v[1]) * 0.32]; this.pen(place(line(v, inner, 0.5)), { w: 1.5, seed: seed + 3 + i, wobble: 0.3, opacity: 0.75, retrace: false }); });
    return this;
  }
}

class StorybookHand extends Hand {
  TINT = TINT; SHADE = SHADE; GRAPHITE = GRAPHITE; SHEET = SHEET; rng = rng; oval = oval; smooth = smooth; line = line; tube = tube; turn = turn; mix = mix; bounds = bounds;
  /** A page or a character, recorded once. paint(k) records its marks. box limits it to a part of the frame. takes = how many redrawings for a line that boils: one take per pose or per hold. */
  picture(_id: string, paint: (k: Draw) => void, o: { box?: { x0: number; y0: number; x1: number; y1: number }; takes?: number } = {}) { return new Rolled(this, () => { const k = new Draw(); paint(k); return k.sorted(); }, PENCIL, o); }
  /** Warm cold-press paper, as a plate. */
  sheetPlate(id = "sheet", color = SHEET, box?: { x0: number; y0: number; x1: number; y1: number }) { return this.plate(id, (c) => { const b = box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }; c.fillStyle = color; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); }, box); }
  /** A walk or a wave holds each drawing: which of n at time t, at rate drawings a second. */
  take(t: number, n = 4, rate = 6) { return Math.floor(t * rate + 1e-6) % n; }
  /** The sheet's grain over the finished frame, last thing in the frame. */
  finish(g: Ctx, o: { paper?: number; vignette?: string | null } = {}) { this.sheet(g, { paper: o.paper ?? 0.14, vignette: o.vignette === undefined ? null : o.vignette, tile: "coldpress" }); }
}

register("storybook", { start: (w: number, h: number, o?: { scale?: number }) => new StorybookHand(w, h, o), TINT, SHADE });
