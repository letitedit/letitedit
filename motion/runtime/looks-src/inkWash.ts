// letitedit hand: ink and line-wash. M.look.inkWash.start(w, h, {scale}) gives the sheet, washes laid as a travelling bead that settle and backrun,
// a flexible nib and spatter; the AI writes the scene. See motion\runtime\looks\inkWash.md.
//
// Adapted from anidoodle's canvas-core/wren.ts and wrenDraw.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Those files have no kit:
// the wet wash, the bead and the pen are taken out here with their places as arguments; the wren and its process timeline are left out.
// Changed by letitedit, 4 Nov 2026: lift(), spatter() and write() are ours; marks go on a Work (.\worked.ts, .\marks.ts).
import { rng, type Ctx, type Gfx, type Medium, type P } from "./anidoodle/core";
import { blob, bounds, clamp, clipped, fillShape, mix } from "./anidoodle/gallery";
import { MarkHand, cost, lettering, plen, run, type Box } from "./marks";
import { register } from "./shared";
import type { Work } from "./worked";

const INK_M: Medium = { nib: 1.7, taper: 1, pressure: 1.75, retrace: false, wobble: 1.35, rough: 0.6 };
const INK = "#16131f", PAPER = "#fbf8f0";
const PALETTE = { ink: INK, paper: PAPER, brown: "#a0693a", darkBrown: "#5e3a20", buff: "#e6c794", rufous: "#b8733a", umber: "#6e4a2c", sap: "#6f8f3e", red: "#c3262d", cool: "#9fb3c8", mist: "#b8c7d6", sand: "#d8b98a", sea: "#6f9aa8" };
type WetO = { flood?: number; alpha?: number; seed?: number; pool?: number; bloom?: P | null; bloomR?: number; t?: number };
const hx = (a: number) => Math.round(255 * clamp(a)).toString(16).padStart(2, "0");

const wetBody = (G: Gfx, pts: P[], color: string, o: WetO, settle: number, bloomK: number) => {
  const { alpha = 0.55, seed = 1, pool = 0.55, bloom = null, bloomR = 22 } = o, b = bounds(pts);
  G.wash(pts, color, { alpha, seed, dx: 7, dy: 6, shrink: o.flood ?? 1.07, rim: true });
  if (settle > 0) clipped(G, pts, () => { const c = G.cur, top = 0.45 + 0.35 * (1 - settle), gr = c.createLinearGradient(0, b.y0 + (b.y1 - b.y0) * top, 0, b.y1 + 2), a = alpha * pool * settle; gr.addColorStop(0, color + "00"); gr.addColorStop(0.75, color + hx(a * 0.6)); gr.addColorStop(1, color + hx(a * 1.3)); c.fillStyle = gr; c.fillRect(b.x0 - 20, b.y0, b.x1 - b.x0 + 40, b.y1 - b.y0 + 20); });
  if (bloom && bloomK > 0) {
    const k = Math.sqrt(bloomK), bl = blob(bloom[0], bloom[1], bloomR, bloomR * 0.8, seed + 7, 0.32, 18).map(([x, y]) => [bloom[0] + (x - bloom[0]) * k, bloom[1] + (y - bloom[1]) * k] as P);
    fillShape(G, bl, PAPER, 0.42); const c = G.cur; c.strokeStyle = mix(color, INK, 0.25); c.globalAlpha = alpha * 0.9; c.lineWidth = 1.6; c.beginPath(); bl.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); c.stroke(); c.globalAlpha = 1;
  }
};
const beadFront = (b: Box, t: number, seed: number): P[] => { const y = b.y0 - 14 + (b.y1 - b.y0 + 40) * t, out: P[] = []; for (let x = b.x0 - 30; x <= b.x1 + 30; x += 8) out.push([x, y + 5 * Math.sin(x * 0.045 + seed) + 3 * Math.sin(x * 0.13 + seed * 2)]); return out; };
const wetMark = (pts: P[], color: string, o: WetO) => (G: Gfx, p: number) => {
  const seed = o.seed ?? 1, alpha = o.alpha ?? 0.55, b = bounds(pts);
  G.group("paint", () => {
    if (p >= 1) return wetBody(G, pts, color, o, 1, 1);
    const spread = clamp(p / 0.55), settle = clamp((p - 0.4) / 0.45), bloomK = clamp((p - 0.7) / 0.3), c = G.cur, front = beadFront(b, spread, seed);
    c.save(); c.beginPath(); c.moveTo(b.x0 - 40, b.y0 - 60); c.lineTo(b.x1 + 40, b.y0 - 60); for (let i = front.length - 1; i >= 0; i--) c.lineTo(front[i][0], front[i][1]); c.closePath(); c.clip();
    wetBody(G, pts, color, o, settle, bloomK); c.restore();
    if (spread < 1) clipped(G, pts, () => { c.strokeStyle = color; c.globalAlpha = alpha * 0.55; c.lineWidth = 3.2; c.lineJoin = "round"; c.beginPath(); front.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.stroke(); c.globalAlpha = 1; });
  });
};

class InkWashHand extends MarkHand {
  palette = PALETTE; blob = blob;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, INK_M); }
  /** The cold-press sheet: a plate. */
  paper(id = "paper", o: { box?: Box; color?: string } = {}) { const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }; return this.plate(id, (c) => { c.fillStyle = o.color ?? PAPER; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); }, b); }
  /** A wash laid as a bead pulled down the shape, floods a little past it (flood 1.07; 1 keeps to the shape), and settles darker along its bottom edge. bloom: [x, y] a backrun, a pale cauliflower where a wetter drop touched. */
  wash(W: Work, shape: P[], color: string, o: WetO = {}) { W.add(o.t ?? 100, wetMark(shape, color, o)); return W; }
  /** A loose wash with no outline to keep to, top to bottom: for a sky or a background. Each part: {x, y, rx, ry, color, alpha}. */
  ground(W: Work, parts: { x: number; y: number; rx: number; ry: number; color: string; alpha?: number; rot?: number }[], o: { seed?: number; t?: number } = {}) {
    const seed = o.seed ?? 10, shapes = parts.map((q, i) => blob(q.x, q.y, q.rx, q.ry, seed + i, 0.3, 22, q.rot ?? 0)), b = bounds(shapes.flat());
    W.add(o.t ?? 120, (G, p) => G.group("paint", () => {
      const draw = () => shapes.forEach((s, i) => G.wash(s, parts[i].color, { alpha: parts[i].alpha ?? 0.26, seed: seed + i, dx: 0, dy: 5, shrink: 1 }));
      if (p >= 1) return draw();
      const c = G.cur, front = beadFront(b, p, 3); c.save(); c.beginPath(); c.moveTo(b.x0 - 60, b.y0 - 60); c.lineTo(b.x1 + 60, b.y0 - 60); for (let i = front.length - 1; i >= 0; i--) c.lineTo(front[i][0], front[i][1]); c.closePath(); c.clip(); draw(); c.restore();
    }));
    return W;
  }
  /** A small shape lifted back toward the paper: a highlight. */
  lift(W: Work, shape: P[], o: { alpha?: number } = {}) { W.add(6, (G) => G.group("plain", () => fillShape(G, shape, PAPER, o.alpha ?? 0.8))); return W; }
  /** A dab of solid colour: an eye, a berry. */
  dab(W: Work, shape: P[], color: string, o: { alpha?: number } = {}) { W.add(6, (G, p) => { if (p > 0) G.group("plain", () => fillShape(G, shape, color, o.alpha ?? 1)); }); return W; }
  /** The nib: one loose stroke through a few points, thick where pressed, hair-thin at the lift. Pen work goes on after the washes have dried. */
  nib(W: Work, pts: P[], w = 2, o: { seed?: number; op?: number; wob?: number; closed?: boolean; color?: string } = {}) { return run(W, [{ t: cost(plen(pts)), d: (G, p) => G.pen(pts, { w, color: o.color ?? INK, seed: o.seed ?? 1, wobble: o.wob ?? 0.9, boil: 0, taper: 1, opacity: o.op ?? 0.95, retrace: false, closed: o.closed, progress: p }) }]); }
  /** The pen shaken: dots land one after another. */
  spatter(W: Work, x: number, y: number, o: { n?: number; spread?: number; seed?: number; size?: number; color?: string } = {}) {
    const { n = 30, spread = 60, seed = 9, size = 2.2, color = INK } = o, r = rng(seed);
    const dots = Array.from({ length: n }, () => { const a = r() * 6.283, d = spread * Math.sqrt(r()) * (r() < 0.2 ? 1.6 : 1); return [x + Math.cos(a) * d, y + Math.sin(a) * d, 0.4 + r() * r() * size] as const; });
    return run(W, dots.map(([dx, dy, s]) => ({ t: 1, d: (G: Gfx, p: number) => { if (p <= 0) return; const c = G.cur; G.touch(dx - s, dy - s, dx + s, dy + s); c.fillStyle = color; c.globalAlpha = 0.9; c.beginPath(); c.arc(dx, dy, s, 0, 6.283); c.fill(); c.globalAlpha = 1; } })));
  }
  /** Capitals with the nib, stroke by stroke. */
  write(W: Work, text: string, x: number, y: number, o: { cap?: number; seed?: number; align?: "left" | "center" | "right"; w?: number; color?: string } = {}) { return run(W, [lettering(text, x, y, { cap: 24, slant: 0.14, opacity: 0.92, ...o, color: o.color ?? INK })]); }
  /** The sheet's tooth over the finished frame, in screen space: last thing in the frame. */
  finish(g: Ctx, o: { paper?: number; coldpress?: number } = {}) { this.grain(g, [["coldpress", o.coldpress ?? 0.16], ["paper", o.paper ?? 0.08]]); }
}

register("inkWash", { start: (w: number, h: number, o?: { scale?: number }) => new InkWashHand(w, h, o) });
