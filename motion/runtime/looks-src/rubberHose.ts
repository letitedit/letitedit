// letitedit hand: rubber hose, a 1930s studio cartoon. M.look.rubberHose.start(w, h) gives India ink at one pressure on a clear cel, flat greys on its back, noodle limbs and
// a black-and-white film print; the gag is written fresh by the AI. See motion\runtime\looks\rubberHose.md.
//
// Uses anidoodle's rubberHoseKit (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Changed by letitedit, 4 Nov 2026: the kit is imported as it is; the glove, the shoe and the pie-cut pupil are taken from canvas-core/rubberHose.ts;
// its coffee pot is left out; filmPrint comes here from the kit, the vignette and the gate measured for any shape of frame; cel(), hop(), part() and the grain-only finish for a scene over a person are ours.
import { fractal, rng, type Ctx, type Env, type Layer, type P } from "./anidoodle/core";
import { smooth } from "./anidoodle/gallery";
import { advance, glyph, measure, type Face } from "./anidoodle/scrapbookKit";
import { capsule, cb, ell, grainTile, inkCel, INK, noodle, paintFills, place, qb, rect, schedule, wob, type Fill, type Line, type Part } from "./anidoodle/rubberHoseKit";
import { Hand, register } from "./shared";

export const GREYS = { ink: INK, white: "#f3eee2", light: "#d9d3c4", mid: "#b3ad9f", grey: "#8c867a", dark: "#5e594f", shadow: "#3a362f", set: "#a29c8e" };
const GLOVE: P[][] = [smooth([[-17, -10], [-21, -28], [-15, -45], [0, -49], [15, -45], [20, -28], [17, -10]], true, 5), capsule([-12, -38], [-17, -72], 7.6), capsule([1, -40], [2, -81], 7.9), capsule([13, -38], [19, -69], 7.3), capsule([-15, -22], [-37, -40], 7.6), smooth([[-20, 4], [0, 7], [20, 4], [17, -13], [0, -10], [-17, -13]], true, 5)];
const STITCH: P[][] = [[[-7, -17], [-6, -33]], [[1, -17], [1, -35]], [[9, -17], [9, -32]]];
const SHOE: P[] = smooth([[-18, -10], [-4, -15], [20, -14], [42, -20], [62, -10], [66, 7], [52, 21], [0, 22], [-22, 18], [-27, 4]], true, 6);
// the print: the kit's filmPrint, with the lamp's vignette measured from the longer side and the gate's corner from the shorter, so a tall frame isn't darkened top and bottom.
const filmPrint = (c: Ctx, env: Env, seed: number) => {
  const { W, H } = env, r = rng(7000 + seed * 13), L = Math.max(W, H), S = Math.min(W, H); c.save();
  c.globalCompositeOperation = "multiply"; c.fillStyle = "#ecdfc6"; c.fillRect(0, 0, W, H);
  const g = grainTile(env), pat = c.createPattern(g.canvas as CanvasImageSource, "repeat")!; c.globalCompositeOperation = "overlay"; c.globalAlpha = 0.34; c.setTransform(1, 0, 0, 1, Math.floor(r() * 256), Math.floor(r() * 256)); c.fillStyle = pat; c.fillRect(-256, -256, W + 512, H + 512);
  c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 1; c.globalCompositeOperation = "source-over"; c.fillStyle = `rgba(20,14,8,${(0.02 + r() * 0.05).toFixed(3)})`; c.fillRect(0, 0, W, H);
  const nd = 5 + Math.floor(r() * 5); for (let i = 0; i < nd; i++) { const x = r() * W, y = r() * H, s = 1 + r() * 2.6, dark = r() < 0.6; c.fillStyle = dark ? "rgba(18,12,8,0.7)" : "rgba(255,250,236,0.75)"; c.beginPath(); ell(x, y, s, s * (0.5 + r()), r() * 3, 8).forEach(([px, py], k) => (k ? c.lineTo(px, py) : c.moveTo(px, py))); c.fill(); }
  if (r() < 0.55) { const x = r() * W, y = r() * H, a = r() * 6; c.strokeStyle = "rgba(20,14,8,0.55)"; c.lineWidth = 1; c.beginPath(); qb([x, y], [x + Math.cos(a) * 30, y + Math.sin(a) * 30 + 12], [x + Math.cos(a + 1) * 44, y + Math.sin(a + 1) * 40]).forEach(([px, py], k) => (k ? c.lineTo(px, py) : c.moveTo(px, py))); c.stroke(); }
  const sx = W * (0.62 + r() * 0.3); c.strokeStyle = "rgba(255,250,236,0.35)"; c.lineWidth = 1.2; c.beginPath(); c.moveTo(sx, 0); c.lineTo(sx + (r() - 0.5) * 6, H); c.stroke();
  c.save(); c.translate(W * 0.48, H * 0.44); c.scale(W / L, H / L); const vg = c.createRadialGradient(0, 0, L * 0.3, 0, 0, L * 0.72); vg.addColorStop(0, "rgba(0,0,0,0)"); vg.addColorStop(1, "rgba(22,14,6,0.5)"); c.fillStyle = vg; c.fillRect(-L, -L, L * 2, L * 2); c.restore();
  c.fillStyle = "#0b0907"; c.beginPath(); c.rect(0, 0, W, H); const m = S * 0.018, R = S * 0.05; c.moveTo(m + R, m); c.arcTo(m, m, m, m + R, R); c.arcTo(m, H - m, m + R, H - m, R); c.arcTo(W - m, H - m, W - m, H - m - R, R); c.arcTo(W - m, m, W - m - R, m, R); c.closePath(); c.fill("evenodd"); c.restore();
};
type PartIn = { fills?: (Omit<Fill, "rank"> & { rank?: number })[]; outline?: P[][]; ow?: number; details?: (Omit<Line, "rank"> & { rank?: number })[]; knock?: boolean; orank?: number };

class HoseHand extends Hand {
  G = GREYS; rng = rng; smooth = smooth; cb = cb; qb = qb; ell = ell; capsule = capsule; rect = rect; noodle = noodle; place = place; wob = wob; fractal = fractal;
  private layers = new Map<string, Layer>(); private sprites = new Map<string, Layer>();
  constructor(w: number, h: number) { super(w, h, { scale: 1 }); }
  /** One piece of a drawing: painted fills on the back of the cel, one outline made of several shapes (stroked as one silhouette), ink details. Nearer parts stop the ink of those behind. */
  part(o: PartIn): Part { return { fills: (o.fills ?? []).map((f) => ({ rank: 1, ...f })), outline: o.outline ?? [], ow: o.ow ?? 4, orank: o.orank ?? 1, details: (o.details ?? []).map((d) => ({ rank: 1, ...d })), knock: o.knock }; }
  /** The solid black noodle limb: one arc from shoulder to wrist, no elbow. bend = how far it bows; w its width. */
  limb(a: P, b: P, bend: number, w = 12): Part { const pts = noodle(a, b, bend); return this.part({ details: [{ pts, w, col: INK }], knock: false }); }
  /** The white four-digit glove, wrist at h, digits along angle a (0 = up), mirrored if m. Three stitch lines, flared cuff. k sizes it. */
  glove(h: P, a = 0, m = false, o: { k?: number; boil?: number } = {}): Part { const k = o.k ?? 1, b = o.boil ?? 0, G = GLOVE.map((s) => wob(place(s, h, a, k, k, m), 1.8, b * 31 + 3)); return this.part({ fills: G.map((s) => ({ pts: s, col: GREYS.white })), outline: G, ow: 3.4, details: STITCH.map((s) => ({ pts: wob(place(s, h, a, k, k, m), 1.2, b * 31 + 7), w: 2.4 })) }); }
  /** The big oval shoe with one shine, ankle at f, toe along +x, mirrored if m. */
  shoe(f: P, a = 0, m = false, o: { k?: number; boil?: number; color?: string } = {}): Part { const k = o.k ?? 1, b = o.boil ?? 0, s = wob(place(SHOE, f, m ? -a : a, k, k, m), 1.8, b * 31 + 9), hi = place([[34, -3], [42, -7], [52, -3], [44, 1]], f, m ? -a : a, k, k, m); return this.part({ fills: [{ pts: s, col: o.color ?? INK }, { pts: hi, col: GREYS.white }], outline: [s], ow: 3 }); }
  /** A big oval eye with a pie-cut pupil: a wedge missing at the upper left, where the shine would be. dir = [dx, dy] of the look. */
  eye(x: number, y: number, rx: number, ry: number, dir: P = [0.25, 0.15], o: { boil?: number } = {}): Part { const b = o.boil ?? 0, e = wob(ell(x, y, rx, ry, 0, 26), 1.2, b * 31 + 11), cx = x + dir[0] * rx, cy = y + dir[1] * ry, pu: P[] = [[cx, cy]]; for (let i = 0; i <= 22; i++) { const a = -1.85 + (i / 22) * (Math.PI * 2 - 0.8); pu.push([cx + Math.cos(a) * rx * 0.54, cy + Math.sin(a) * ry * 0.62]); } return this.part({ fills: [{ pts: e, col: GREYS.white }, { pts: pu, col: INK }], outline: [e], ow: 3.2 }); }
  /** A translucent flat cast shadow with no ink. */
  shadow(pts: P[], alpha = 0.35): Part { return this.part({ fills: [{ pts, col: GREYS.shadow, alpha }], knock: false }); }
  private layer(k: string) { let L = this.layers.get(k); if (!L) { L = this.env.canvas(this.w, this.h); this.layers.set(k, L); } return L; }
  /** A drawing: parts back to front. ink = 0..1 the inker's line goes down; paint = 0..1 the greys flood in, each from where the brush touched. key = a name for this pose, so a held pose isn't drawn again. Also x, y, s, pivot, alpha. */
  cel(g: Ctx, parts: Part[], o: { ink?: number; paint?: number; key?: string; x?: number; y?: number; s?: number; pivot?: P; alpha?: number } = {}) {
    const ip = o.ink ?? 1, fp = o.paint ?? 1, w = this.w, h = this.h; let src: Layer | undefined = ip >= 1 && fp >= 1 && o.key ? this.sprites.get(o.key) : undefined;
    if (!src) {
      const sch = schedule(parts), cl = this.layer("ink"), c = cl.ctx, out = ip >= 1 && fp >= 1 && o.key ? this.env.canvas(w, h) : this.layer("out"), oc = out.ctx;
      c.setTransform(1, 0, 0, 1, 0, 0); c.globalCompositeOperation = "source-over"; c.clearRect(0, 0, w, h); inkCel(c, parts, sch.ink, ip);
      oc.setTransform(1, 0, 0, 1, 0, 0); oc.globalAlpha = 1; oc.globalCompositeOperation = "source-over"; oc.clearRect(0, 0, w, h); paintFills(oc, parts, sch.fill, fp); oc.drawImage(cl.canvas as CanvasImageSource, 0, 0);
      if (ip >= 1 && fp >= 1 && o.key) { if (this.sprites.size > 64) this.sprites.clear(); this.sprites.set(o.key, out); }
      src = out;
    }
    g.save(); const s = o.s ?? 1, pv = o.pivot ?? [w / 2, h / 2]; if (o.x || o.y) g.translate(o.x ?? 0, o.y ?? 0); if (s !== 1) { g.translate(pv[0], pv[1]); g.scale(s, s); g.translate(-pv[0], -pv[1]); } if (o.alpha !== undefined) g.globalAlpha *= o.alpha; g.drawImage(src.canvas as CanvasImageSource, 0, 0, w, h); g.restore();
  }
  /** Stroked capitals centred at (x, y), cap tall, on this frame: a title card, a balloon's words. outline = a white letter inside the ink. */
  title(g: Ctx, text: string, x: number, y: number, cap: number, o: { color?: string; outline?: string; w?: number } = {}) { const f: Face = { weight: o.w ?? 0.2, cap: "round", join: "round", outline: o.outline }; let xx = x - measure(text, cap, f) / 2; g.save(); [...text].forEach((ch) => { glyph(g, ch, xx, y - cap / 2, cap, f, o.color ?? INK); xx += advance(ch, f) * (cap / 6); }); g.restore(); }
  /** The blue-pencil rough: line of action and masses, on the paper before the ink. */
  rough(g: Ctx, pts: P[], o: { closed?: boolean; color?: string; w?: number } = {}) { g.save(); g.strokeStyle = o.color ?? "#8aa2c8"; g.lineWidth = o.w ?? 2; g.globalAlpha *= 0.7; g.lineCap = "round"; g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); if (o.closed) g.closePath(); g.stroke(); g.restore(); }
  /** On twos at the project's fps: which drawing, a whole number. */
  drawing(t: number, fps = 24) { return Math.floor((t * fps) / 2 + 1e-6); }
  /** The dance: key poses on the beat, the body hops between them. Returns {y, sx, sy, beat, u}: the hop's height, stretch in the air and squash on landing; held on twos. */
  hop(t: number, beat = 0.5, height = 26, fps = 24) { const h = (this.drawing(t, fps) * 2) / fps, f = h / beat, i = Math.floor(f), u = f - i, up = Math.sin(u * Math.PI), land = u < 0.16 ? 1 - u / 0.16 : 0, sq = 1 - 0.16 * land + 0.1 * up; return { y: -height * up, sy: sq, sx: 1 / Math.sqrt(sq), beat: i, u }; }
  /** Limbs follow the body by about two frames: the hop's u a little earlier. */
  behind(u: number, by = 0.2) { return ((u - by) % 1 + 1) % 1; }
  /** The gate's weave for this drawing: a small x, y shift to put on the whole picture while it moves; [0, 0] on a hold. */
  weave(t: number, fps = 24, on = true): P { if (!on) return [0, 0]; const r = rng(4100 + this.drawing(t, fps)); return [(r() - 0.5) * 3.4, (r() - 0.5) * 3.4]; }
  /** The print, last thing in the frame: warm tone, grain, flicker, dust, a hair, a scratch, the lamp's vignette and the rounded gate. A pure function of the drawing number. Over a person or footage, use grainOnly: the tone and the gate would paint the whole frame. */
  finish(g: Ctx, o: { t?: number; fps?: number; grainOnly?: boolean; still?: boolean } = {}) {
    const seed = o.still ? 0 : this.drawing(o.t ?? 0, o.fps ?? 24); g.save(); g.setTransform(1, 0, 0, 1, 0, 0);
    if (o.grainOnly) { const r = rng(7000 + seed * 13), T = grainTile(this.env), pat = g.createPattern(T.canvas as CanvasImageSource, "repeat")!, ox = Math.floor(r() * 256), oy = Math.floor(r() * 256); g.globalCompositeOperation = "source-atop"; g.globalAlpha = 0.16; g.translate(ox, oy); g.fillStyle = pat; g.fillRect(-ox, -oy, this.w, this.h); }
    else filmPrint(g, this.env, seed);
    g.restore();
  }
}

register("rubberHose", { start: (w: number, h: number) => new HoseHand(w, h), greys: GREYS });
