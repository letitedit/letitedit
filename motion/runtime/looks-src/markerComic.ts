// letitedit hand: marker comic. M.look.markerComic.start(w, h, {scale}) gives alcohol-marker flats laid in chisel passes, a hard cel shadow and one heavy contour
// that thickens away from the light; the panel is written fresh by the AI. See motion\runtime\looks\markerComic.md.
//
// Uses anidoodle's koiDrawKit and gallery's inker's line and body-on-a-spine (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Changed by letitedit,
// 4 Nov 2026: the kit is imported as it is; the koi and its pond are left out; the mark list, parts and takes are ours (.\marksRoll.ts), the hard shadow
// rule and the balloon, burst and speed lines are written for this hand from koi.ts's description. That style's marks were in its hero and its draw kit.
import { rng, type Ctx, type P } from "./anidoodle/core";
import { blob, body, bounds, inkRibbon, mix, profile, smooth, trace, type InkOpts } from "./anidoodle/gallery";
import { cut, streakClip, streaks } from "./anidoodle/koiDrawKit";
import { glyph, measure, advance, type Face } from "./anidoodle/scrapbookKit";
import { Marks, Rolled } from "./marksRoll";
import { Hand, register } from "./shared";
import { PENCIL } from "./anidoodle/core";

const INK = "#15122a", LIGHT: P = [-0.62, -0.78], BLUE = "#7fb7e6", RANK = { pencil: 0, flat: 1, shade: 2, detail: 3, line: 4 };
export const C = { ink: INK, white: "#fdf8ee", whiteShade: "#c9d6e0", red: "#ec4a22", redShade: "#b72c1a", teal: "#137582", tealDark: "#0c5360", tealLight: "#3aa6ad", yellow: "#ffcf3f", yellowShade: "#d99a1e", blue: "#2f6fd0", blueShade: "#1f4c9a", green: "#35a853", greenShade: "#1f7a3b", pink: "#f06ba8", skin: "#f3c49b", skinShade: "#d4966c", purple: "#6c49c9" };
const LETTER: Face = { weight: 0.16, cap: "round", join: "round", slant: 0.1 };
type Line = { w?: number; light?: P; seed?: number; shadow?: number; color?: string; taper?: [number, number]; side?: 1 | -1 };
const fillRibbon = (c: Ctx, center: P[], color: string, o: InkOpts) => { const pts = inkRibbon(center, o); c.fillStyle = color; if (o.closed) { const n = center.length + 1; c.beginPath(); pts.slice(0, n).forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); pts.slice(n).forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); c.fill("evenodd"); } else { trace(c, pts); c.fill(); } };
const area = (s: P[]) => s.reduce((a, p, i) => { const q = s[(i + 1) % s.length]; return a + p[0] * q[1] - q[0] * p[1]; }, 0) / 2;

/** One panel being recorded. Inside a part, marks go down pencil, flats, hard shadows, details, contour. k.part() starts the next thing up the stack. */
class Draw extends Marks {
  /** The non-photo-blue lay-in: gesture and masses, gone once the marker covers them. */
  pencil(pts: P[], o: { closed?: boolean; seed?: number } = {}) { const s = o.closed ? [...pts, pts[0]] : pts, b = bounds(s), seed = o.seed ?? this.list.length + 2; return this.add(RANK.pencil, 4, (G, p) => G.group("plain", () => { G.touch(b.x0 - 6, b.y0 - 6, b.x1 + 6, b.y1 + 6); G.pen(s, { w: 1.3, color: BLUE, seed, wobble: 0.6, boil: 0, opacity: 0.7, retrace: false, progress: p }); })); }
  /** A flat cel fill laid in back-and-forth chisel passes. width = the nib, angle = its slant, reach = how far a wrist goes (a wide area fills in blocks with a ragged leading edge). */
  flat(shape: P[], color: string, o: { width?: number; angle?: number; reach?: number; seed?: number } = {}) { const b = bounds(shape), seed = o.seed ?? this.list.length + 3, st = streaks([shape], o.width ?? 30, o.angle ?? -0.5, seed, o.reach ?? 1e9); return this.add(RANK.flat, Math.sqrt((b.x1 - b.x0) * (b.y1 - b.y0)) * 0.5 + 6, (G, p) => { const c = G.cur; G.touch(b.x0 - 4, b.y0 - 4, b.x1 + 4, b.y1 + 4); c.save(); if (p < 1) streakClip(c, st, p); c.fillStyle = color; trace(c, shape); c.fill(); c.restore(); }); }
  /** A hard shadow on the shape: a flat tone, its edge the shape itself pushed towards the light by k, no blur. */
  shadow(shape: P[], color: string, o: { k?: number; light?: P; base?: string } = {}) { const L = o.light ?? LIGHT, b = bounds(shape), k = o.k ?? Math.min(b.x1 - b.x0, b.y1 - b.y0) * 0.16, moved = shape.map(([x, y]) => [x + L[0] * k, y + L[1] * k] as P); return this.add(RANK.shade, 5, (G, p) => { if (p <= 0) return; const c = G.cur; G.touch(b.x0 - 2, b.y0 - 2, b.x1 + 2, b.y1 + 2); c.save(); trace(c, shape); c.clip(); c.globalAlpha = p < 1 ? p : 1; c.fillStyle = color; c.beginPath(); c.rect(b.x0 - 2, b.y0 - 2, b.x1 - b.x0 + 4, b.y1 - b.y0 + 4); moved.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); c.fill("evenodd"); c.restore(); }); }
  /** A hard shadow shape you draw yourself: floor shadows, under a chin. */
  shape(pts: P[], color: string, alpha = 1, rank: "shade" | "detail" = "shade") { const b = bounds(pts); return this.add(RANK[rank], 3, (G, p) => { if (p <= 0) return; const c = G.cur; G.touch(b.x0 - 2, b.y0 - 2, b.x1 + 2, b.y1 + 2); c.save(); c.globalAlpha = alpha * Math.min(1, p * 2); c.fillStyle = color; trace(c, pts); c.fill(); c.restore(); }); }
  /** Gel-pen whites: small opaque dots and dashes put on near the end. */
  gel(dots: P[], o: { r?: number; color?: string } = {}) { const r = o.r ?? 3.5, b = bounds(dots); return this.add(RANK.detail, 3, (G, p) => { const c = G.cur; G.touch(b.x0 - r - 2, b.y0 - r - 2, b.x1 + r + 2, b.y1 + r + 2); c.fillStyle = o.color ?? "#ffffff"; dots.slice(0, Math.ceil(dots.length * p)).forEach(([x, y], i) => { c.beginPath(); c.ellipse(x, y, r * (i % 3 === 0 ? 1.3 : 0.8), r * (i % 3 === 0 ? 0.9 : 0.8), 0.4, 0, 6.2832); c.fill(); }); }); }
  /** A detail stroke with the same inker's line, lighter: scales, folds, hair, a smile. */
  detail(pts: P[], o: Line = {}) { return this.stroke(pts, { w: 4, shadow: 0.4, ...o }, RANK.detail); }
  /** The heavy brush-pen contour, heavier on the side away from the light, grown along its centreline. closed joins it up. Last in its part. */
  line(pts: P[], o: Line & { closed?: boolean } = {}) { return this.stroke(pts, o, RANK.line, o.closed); }
  private stroke(pts: P[], o: Line, rank: number, closed = false) { const b = bounds(pts), w = o.w ?? 9, color = o.color ?? INK, seed = o.seed ?? this.list.length + 5, io: InkOpts = { w, light: o.light ?? LIGHT, shadow: o.shadow ?? 0.8, seed, closed, taper: o.taper, side: o.side }, path = closed ? [...pts, pts[0]] : pts; return this.add(rank, Math.pow(pts.length * 6, 0.6) + 3, (G, p) => { if (p <= 0) return; G.touch(b.x0 - w - 3, b.y0 - w - 3, b.x1 + w + 3, b.y1 + w + 3); const c = G.cur; c.save(); if (p >= 1) fillRibbon(c, pts, color, io); else fillRibbon(c, cut(path, p), color, { ...io, closed: false, side: closed ? (area(pts) > 0 ? -1 : 1) : o.side, taper: [closed ? 0.04 : 0.12, 0.08] }); c.restore(); }); }
  /** One whole cel: flat, hard shadow, contour; the short way to draw a thing. */
  cel(shape: P[], color: string, o: { shadow?: string | null; k?: number; w?: number; width?: number; angle?: number } = {}) { this.flat(shape, color, { width: o.width, angle: o.angle }); if (o.shadow !== null) this.shadow(shape, o.shadow ?? mix(color, "#1c1540", 0.32), { k: o.k }); return this.line(shape, { closed: true, w: o.w }); }
  /** Words in stroked letters, set in the current part, drawn with the contour. (x, y) = centre, cap = letter height. */
  words(text: string, x: number, y: number, cap: number, o: { color?: string; face?: Face } = {}) { const f = o.face ?? LETTER, W = measure(text, cap, f); return this.add(RANK.line, text.length * 2 + 3, (G, p) => { if (p <= 0) return; const c = G.cur; G.touch(x - W / 2 - cap, y - cap, x + W / 2 + cap, y + cap); let xx = x - W / 2; [...text].slice(0, Math.ceil(text.length * p)).forEach((ch) => { glyph(c, ch, xx, y - cap / 2, cap, f, o.color ?? INK); xx += advance(ch, f) * (cap / 6); }); c.globalAlpha = 1; }); }
  /** A speech balloon: white, heavy line, a tail to (tx, ty), its words in stroked letters. */
  balloon(text: string, x: number, y: number, cap: number, tail: P, o: { pad?: number } = {}) { const pad = o.pad ?? cap * 0.9, w = measure(text, cap, LETTER) / 2 + pad, h = cap / 2 + pad, a = Math.atan2(tail[1] - y, tail[0] - x), n = 28, pts: P[] = []; for (let i = 0; i < n; i++) { const t = a + 0.3 + (i / (n - 1)) * (6.2832 - 0.6); pts.push([x + Math.cos(t) * w, y + Math.sin(t) * h * 1.15]); } pts.push(tail); this.part(); this.flat(pts, "#ffffff", { width: 26 }); this.line(pts, { closed: true, w: 7, shadow: 0.5 }); return this.words(text, x, y, cap); }
  /** An action burst: a jagged star, as a cel. */
  burst(x: number, y: number, R: number, color: string, o: { n?: number; inner?: number; seed?: number; shadow?: string | null } = {}) { const n = o.n ?? 12, r = rng(o.seed ?? this.list.length + 7), pts: P[] = Array.from({ length: n * 2 }, (_, i) => { const a = (i / (n * 2)) * 6.2832, k = i % 2 ? (o.inner ?? 0.62) : 0.9 + r() * 0.2; return [x + Math.cos(a) * R * k, y + Math.sin(a) * R * k]; }); return this.cel(pts, color, { shadow: o.shadow, w: 8 }); }
  /** Speed lines towards a point: tapered ink strokes with a clear middle. */
  speed(x: number, y: number, R0: number, R1: number, o: { n?: number; w?: number; seed?: number; color?: string } = {}) { const r = rng(o.seed ?? this.list.length + 9), n = o.n ?? 40; for (let i = 0; i < n; i++) { const a = (i / n) * 6.2832 + (r() - 0.5) * 0.1, k = R0 * (1 + r() * 0.3); this.stroke([[x + Math.cos(a) * k, y + Math.sin(a) * k], [x + Math.cos(a) * ((k + R1) / 2), y + Math.sin(a) * ((k + R1) / 2)], [x + Math.cos(a) * R1, y + Math.sin(a) * R1]], { w: (o.w ?? 5) * (0.6 + r() * 0.8), color: o.color, shadow: 0, taper: [0.8, 0.05], seed: i + 3 }, RANK.detail); } return this; }
}

class MarkerHand extends Hand {
  c = C; rng = rng; smooth = smooth; blob = blob; body = body; profile = profile; mix = mix; bounds = bounds;
  /** A panel or a character, recorded once. paint(k) records its marks. box limits it to a part of the frame. takes = how many redrawings. */
  picture(_id: string, paint: (k: Draw) => void, o: { box?: { x0: number; y0: number; x1: number; y1: number }; takes?: number } = {}) { return new Rolled(this, () => { const k = new Draw(); paint(k); return k.sorted(); }, PENCIL, o); }
  /** The whole frame as one flat, for a ground; a plate. */
  ground(id: string, color: string, box?: { x0: number; y0: number; x1: number; y1: number }) { return this.plate(id, (c) => { const b = box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }; c.fillStyle = color; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); }, box); }
  /** Which of n poses at time t, on twos at 12 a second by default. */
  take(t: number, n = 2, rate = 12) { return Math.floor(t * rate + 1e-6) % n; }
  /** A light paper tooth over the frame, last thing in the frame. */
  finish(g: Ctx, o: { paper?: number; vignette?: string | null } = {}) { this.sheet(g, { paper: o.paper ?? 0.05, vignette: o.vignette === undefined ? null : o.vignette, tile: "paper" }); }
}

register("markerComic", { start: (w: number, h: number, o?: { scale?: number }) => new MarkerHand(w, h, o), colours: C });
