// letitedit hand: hand embroidery. M.look.embroidery.start(w, h, {scale}) gives stranded floss on plain-weave linen in a beech hoop, every stitch a length of twisted
// thread between two holes, made one by one; the design is written fresh by the AI. See motion\runtime\looks\embroidery.md.
//
// Uses anidoodle's embroideryKit (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Changed by letitedit, 4 Nov 2026: the kit is imported as it is; its
// flowers and bee are left out; the hoop, the needle, the rolling base, sway and stitched words are ours, written from canvas-core/embroidery.ts's description.
import { rng, type Ctx, type P } from "./anidoodle/core";
import { bounds, mix, smooth } from "./anidoodle/gallery";
import { drawShadows, drawThreads, fishbone, flat, headOf, knot, knots, linenLayer, longShort, runningStitch, satin, splitStitch, stemStitch, straight, type St } from "./anidoodle/embroideryKit";
import { GLYPHS } from "./anidoodle/scrapbookKit";
import { Hand, register } from "./shared";

export const FLOSS = { sage: "#8ea57d", olive: "#6d7f42", moss: "#4c6336", white: "#f8f4e8", shell: "#f0dcc8", butter: "#f2d26a", ochre: "#cd9a3a", cornflower: "#5f7fc4", lavender: "#a48bc9", plum: "#6e4f94", coral: "#e0603f", oxblood: "#8a2b24", gold: "#c9a24a", umber: "#5a3f28", silver: "#c8ccd4", ink: "#2a2a35", teal: "#2f7f83" };
const LINEN: [number, number, number] = [226, 212, 186], STEP = 40;
type Box = { x0: number; y0: number; x1: number; y1: number };

/** A run of stitches on its own transparent canvas: progress 0..1 makes them one by one. A pure function of how many are down: a backward seek starts again. */
class Work {
  private base?: HTMLCanvasElement; private b!: CanvasRenderingContext2D; private at = 0; private all?: HTMLCanvasElement;
  constructor(private hand: EmbHand, public sts: St[], private bx: Box) {}
  get count() { return this.sts.length; }
  private fresh() { const k = this.hand.scale, c = document.createElement("canvas"); c.width = Math.ceil((this.bx.x1 - this.bx.x0) * k); c.height = Math.ceil((this.bx.y1 - this.bx.y0) * k); return c; }
  private at0(c: CanvasRenderingContext2D) { const k = this.hand.scale; c.setTransform(k, 0, 0, k, -this.bx.x0 * k, -this.bx.y0 * k); }
  private lay(c: CanvasRenderingContext2D, list: St[], last = 1) { this.at0(c); drawShadows(c, list, last); drawThreads(c, list, last); }
  private roll(n: number) { if (!this.base) { this.base = this.fresh(); this.b = this.base.getContext("2d")!; this.at = 0; } if (n < this.at) { this.b.setTransform(1, 0, 0, 1, 0, 0); this.b.clearRect(0, 0, this.base.width, this.base.height); this.at = 0; } for (let i = this.at; i < n; i += STEP) this.lay(this.b, this.sts.slice(i, Math.min(n, i + STEP))); this.at = n; }
  private whole() { if (!this.all) { this.all = this.fresh(); const c = this.all.getContext("2d")!; for (let i = 0; i < this.sts.length; i += STEP) this.lay(c, this.sts.slice(i, i + STEP)); } return this.all; }
  /** Where the needle is at this progress, and the angle of the stitch in hand. */
  head(p: number): { x: number; y: number; a: number } { const f = Math.min(1, Math.max(0, p)) * this.sts.length, i = Math.min(this.sts.length - 1, Math.floor(f)), s = this.sts[i], q = headOf(s, f - i); return { x: q[0], y: q[1], a: Math.atan2(s.b[1] - s.a[1], s.b[0] - s.a[0]) }; }
  /** progress 0..1 makes the stitches in order. needle: true shows it at the stitch in hand. Also x, y, alpha. */
  draw(g: Ctx, o: { progress?: number; needle?: boolean; x?: number; y?: number; alpha?: number } = {}) {
    const p = o.progress ?? 1, B = this.bx, w = B.x1 - B.x0, h = B.y1 - B.y0; if (p <= 0) return; g.save(); if (o.x || o.y) g.translate(o.x ?? 0, o.y ?? 0); if (o.alpha !== undefined) g.globalAlpha *= o.alpha;
    if (p >= 1) g.drawImage(this.whole(), B.x0, B.y0, w, h);
    else {
      const f = p * this.sts.length, n = Math.floor(f), full = n - (n % STEP); this.roll(full); g.drawImage(this.base!, B.x0, B.y0, w, h);
      const rest = this.sts.slice(full, n + 1), q = f - n; drawShadows(g, rest, q); drawThreads(g, rest, q);
      if (o.needle !== false) { const H = this.head(p); this.hand.needle(g, H.x, H.y, H.a); }
    }
    g.restore();
  }
}

class EmbHand extends Hand {
  c = FLOSS; rng = rng; smooth = smooth; mix = mix; bounds = bounds;
  stem = stemStitch; split = splitStitch; running = runningStitch; satin = satin; fishbone = fishbone; longShort = longShort; knots = knots; knot = knot; straight = straight; flat = flat; threads = drawThreads; shadows = drawShadows;
  /** The cloth: plain weave computed per pixel once, with slubs, over and under crossings and pin-holes. pitch = thread spacing, tint = RGB. inside(x, y) 0..1 darkens it, for a folded edge. */
  linen(id = "linen", o: { pitch?: number; tint?: [number, number, number]; inside?: (x: number, y: number) => number } = {}) { const pitch = o.pitch ?? 3.4, tint = o.tint ?? LINEN, ins = o.inside ?? (() => 1); return this.plate(id, (c) => { const L = linenLayer(this.env, id, pitch, tint, ins); c.save(); c.setTransform(1, 0, 0, 1, 0, 0); c.drawImage(L.canvas as CanvasImageSource, 0, 0); c.restore(); }); }
  /** A beech hoop with a brass screw at the top, its shadow falling on the cloth inside at upper left and outside at lower right. Returns a plate: draw it over the stitches. rx, ry = inner radius. */
  hoop(id: string, cx: number, cy: number, rx: number, ry = rx, o: { band?: number; wood?: string } = {}) {
    const band = o.band ?? Math.min(rx, ry) * 0.075, wood = o.wood ?? "#c79f6d", pad = band * 3 + 30;
    return this.plate(id, (c) => {
      c.save(); c.beginPath(); c.ellipse(cx, cy, rx, ry, 0, 0, 6.2832); c.clip(); const g = c.createLinearGradient(cx - rx, cy - ry, cx - rx * 0.4, cy - ry * 0.4); g.addColorStop(0, "rgba(40,28,14,.34)"); g.addColorStop(1, "rgba(40,28,14,0)"); c.fillStyle = g; c.fillRect(cx - rx, cy - ry, rx * 2, ry * 2); c.restore();
      c.save(); c.globalAlpha = 0.28; c.strokeStyle = "#2a1c10"; c.lineWidth = band * 1.1; c.beginPath(); c.ellipse(cx + band * 0.5, cy + band * 0.8, rx + band * 0.9, ry + band * 0.9, 0, 0, 6.2832); c.stroke(); c.restore();
      const ring = c.createLinearGradient(cx - rx, cy - ry, cx + rx, cy + ry); ring.addColorStop(0, mix(wood, "#ffffff", 0.32)); ring.addColorStop(0.5, wood); ring.addColorStop(1, mix(wood, "#3a2410", 0.38)); c.strokeStyle = ring; c.lineWidth = band; c.beginPath(); c.ellipse(cx, cy, rx + band / 2, ry + band / 2, 0, 0, 6.2832); c.stroke();
      const r = rng(61); c.lineWidth = 0.7; for (let i = 0; i < 160; i++) { const a = r() * 6.2832, l = 0.02 + r() * 0.06, q = rx + band * (0.12 + r() * 0.76), qy = ry + band * (0.12 + r() * 0.76); c.strokeStyle = r() < 0.5 ? "rgba(90,60,28,.35)" : "rgba(255,235,200,.28)"; c.beginPath(); c.ellipse(cx, cy, q, qy, 0, a, a + l); c.stroke(); }
      const bw = band * 1.5, by = cy - ry - band * 1.5; c.fillStyle = "#a88a4a"; c.fillRect(cx - bw, by, bw * 2, band * 1.4); c.fillStyle = "#d9bd76"; c.fillRect(cx - bw, by, bw * 2, band * 0.4); c.fillStyle = "#6e5a2c"; c.fillRect(cx - bw * 1.4, by + band * 0.45, bw * 2.8, band * 0.5); c.fillStyle = "#cdb36f"; c.beginPath(); c.arc(cx + bw * 1.55, by + band * 0.7, band * 0.5, 0, 6.2832); c.fill();
    }, { x0: Math.max(0, cx - rx - pad), y0: Math.max(0, cy - ry - pad), x1: Math.min(this.w, cx + rx + pad), y1: Math.min(this.h, cy + ry + pad) });
  }
  /** A run of stitches, built once: build() returns a list (spread the lists of several generators, in the order they are made). box = {x0,y0,x1,y1} it stays inside, default the frame. */
  work(_id: string, build: () => St[], box?: Box) { return new Work(this, build(), box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }); }
  /** The steel needle with its thread trailing, at the stitch in hand. */
  needle(g: Ctx, x: number, y: number, a: number, thread = "#b9ad96") { const L = 46; g.save(); g.translate(x, y); g.rotate(a - 2.2); g.strokeStyle = thread; g.globalAlpha *= 0.8; g.lineWidth = 1; g.beginPath(); g.moveTo(L, 0); g.bezierCurveTo(L + 26, 16, L + 50, -6, L + 74, 18); g.stroke(); const l = g.createLinearGradient(0, -1.6, 0, 1.6); l.addColorStop(0, "#f0f2f5"); l.addColorStop(1, "#7f8690"); g.fillStyle = l; g.beginPath(); g.moveTo(0, 0); g.lineTo(L, -1.5); g.lineTo(L, 1.5); g.closePath(); g.fill(); g.restore(); }
  /** Words in stem or split stitch, along stroked capitals. (x, y) = top-left of the capitals, cap = their height; returns a list of stitches. */
  words(text: string, x: number, y: number, cap: number, color: string, o: { w?: number; len?: number; kind?: "split" | "stem"; track?: number } = {}): St[] { const s = cap / 6, out: St[] = [], w = o.w ?? Math.max(2, cap * 0.075), len = o.len ?? Math.max(5, cap * 0.16); let xx = x; for (const ch of text) { const g = GLYPHS[ch] ?? GLYPHS[ch.toUpperCase()] ?? GLYPHS["-"]; const strokes = [...(g.l ?? []), ...(g.c ?? []).map((st) => smooth(st, false, 6))]; strokes.forEach((st, i) => { const q = st.map(([a, b]) => [xx + a * s, y + b * s] as P); out.push(...(o.kind === "stem" ? stemStitch(q, len, w, color, i + 3) : splitStitch(q, len, w, color))); }); xx += ((g.w ?? 4) + (o.track ?? 1.5)) * s; } return out; }
  /** Stitches re-posed, not warped: each end moved around a pinned origin, more the further away. For a leaf that breathes. Returns a new list; draw it with E.live. */
  sway(sts: St[], t: number, o: { origin: P; amp?: number; period?: number; phase?: number }): St[] { const { origin: O, amp = 0.03, period = 8, phase = 0 } = o, a = amp * Math.sin((t / period) * 6.2832 + phase), c = Math.cos(a), si = Math.sin(a), T = ([x, y]: P): P => [O[0] + (x - O[0]) * c - (y - O[1]) * si, O[1] + (x - O[0]) * si + (y - O[1]) * c]; return sts.map((s) => ({ ...s, a: T(s.a), b: T(s.b) })); }
  /** Stitches drawn directly this frame, for a few that move. */
  live(g: Ctx, sts: St[]) { drawShadows(g, sts); drawThreads(g, sts); }
  /** A soft lamp on the cloth and its grain, last thing in the frame. */
  finish(g: Ctx, o: { vignette?: string | null } = {}) { this.sheet(g, { paper: 0, vignette: o.vignette === undefined ? "rgba(60,36,14,0.26)" : o.vignette }); }
}

register("embroidery", { start: (w: number, h: number, o?: { scale?: number }) => new EmbHand(w, h, o), floss: FLOSS });
