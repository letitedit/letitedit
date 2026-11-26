// letitedit: a picture made of recorded marks, for hands whose drawing is seen being made. Written for letitedit (GPL-3.0-or-later).
//
// A picture's marks are recorded once. progress 0..1 walks them in order: every finished mark is kept on one rolling canvas, and only
// the mark in hand is drawn again each frame. The canvas holds a pure function of how many marks are down (a backward seek starts it over),
// so frame N is the same whatever came before. Once done, a picture is one sprite, placed through the context's current transform.
import { Gfx, type Ctx, type Env, type Layer, type Medium } from "./anidoodle/core";
import type { Hand } from "./shared";

/** The pen smooths what it is given: a long straight side would round off its corners. Short steps beside each corner keep them. */
export const keepCorners = (s: [number, number][], at = 12): [number, number][] => { const out: [number, number][] = []; s.forEach((p, i) => { out.push(p); const q = s[i + 1]; if (!q) return; const d = Math.hypot(q[0] - p[0], q[1] - p[1]); if (d > at * 3) { const u = at / d; out.push([p[0] + (q[0] - p[0]) * u, p[1] + (q[1] - p[1]) * u], [q[0] - (q[0] - p[0]) * u, q[1] - (q[1] - p[1]) * u]); } }); return out; };

export type Mark = { cost: number; run: (G: Gfx, p: number) => void };
type Box = { x0: number; y0: number; x1: number; y1: number };

export class Rolled {
  private base?: Layer; private out?: Layer; private at = 0; private fin = new Map<number, Layer>(); private env: Env; private marks: Mark[][] = []; private bx: Box; private k: number; private win: number[] = []; private total = 0; takes: number;
  constructor(private hand: Hand, private record: (take: number) => Mark[], private medium: Medium, o: { box?: Box; takes?: number } = {}) {
    this.bx = o.box ?? { x0: 0, y0: 0, x1: hand.w, y1: hand.h }; this.k = hand.scale; this.takes = o.takes ?? 1;
    this.env = { ...hand.env, W: Math.ceil(this.bx.x1 - this.bx.x0), H: Math.ceil(this.bx.y1 - this.bx.y0) };
    const m = this.list(0); let t = 0; this.win = m.map((q) => { const a = t; t += q.cost; return a; }); this.total = t || 1; this.win.push(t);
  }
  private list(take: number) { return (this.marks[take] ??= this.record(take)); }
  /** How many seconds this picture "wants" at a steady hand, as a hint: the sum of its marks' costs. */
  get cost() { return this.total; }
  private gfx(c: Ctx, take: number) { const G = new Gfx(c, this.env, take * 4, this.medium); G.push(-this.bx.x0, -this.bx.y0, 1); return G; }
  private layer() { const L = this.env.canvas(Math.ceil(this.env.W * this.k), Math.ceil(this.env.H * this.k)); L.ctx.setTransform(1, 0, 0, 1, 0, 0); return L; }
  private wash(L: Layer) { const c = L.ctx; c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 1; c.globalCompositeOperation = "source-over"; c.clearRect(0, 0, L.canvas.width, L.canvas.height); }
  private done(take: number) { let L = this.fin.get(take); if (!L) { L = this.layer(); const G = this.gfx(L.ctx, take); this.list(take).forEach((m) => m.run(G, 1)); this.fin.set(take, L); } return L; }
  /** progress 0..1 walks the marks; take picks one of `takes` redrawings, for a line that boils. Also x, y, s, r, pivot, alpha. */
  draw(g: Ctx, o: { progress?: number; take?: number; x?: number; y?: number; s?: number; r?: number; pivot?: [number, number]; alpha?: number } = {}) {
    const p = o.progress ?? 1; if (p <= 0) return;
    const b = this.bx, take = (o.take ?? 0) % this.takes; let src: Layer;
    if (p >= 1) src = this.done(take);
    else {
      const t = p * this.total; let n = 0; while (n + 1 < this.win.length - 1 && this.win[n + 1] <= t) n++;
      const marks = this.list(0), base = (this.base ??= this.layer()), out = (this.out ??= this.layer());
      if (n < this.at) { this.wash(base); this.at = 0; }
      if (n > this.at) { const G = this.gfx(base.ctx, 0); for (let i = this.at; i < n; i++) marks[i].run(G, 1); this.at = n; }
      const q = (t - this.win[n]) / Math.max(1e-6, this.win[n + 1] - this.win[n]);
      this.wash(out); out.ctx.drawImage(base.canvas as CanvasImageSource, 0, 0);
      if (q > 0 && marks[n]) marks[n].run(this.gfx(out.ctx, 0), q);
      src = out;
    }
    g.save(); const piv = o.pivot ?? [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2], s = o.s ?? 1;
    if (o.x || o.y) g.translate(o.x ?? 0, o.y ?? 0);
    if (o.r || s !== 1) { g.translate(piv[0], piv[1]); if (o.r) g.rotate(o.r); if (s !== 1) g.scale(s, s); g.translate(-piv[0], -piv[1]); }
    if (o.alpha !== undefined) g.globalAlpha *= o.alpha;
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high"; g.drawImage(src.canvas as CanvasImageSource, b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); g.restore();
  }
}

/** Marks in parts: inside a part they sort by rank (the medium's order), and parts go down one after another, so nearer things stay on top. */
export class Marks {
  list: { part: number; rank: number; i: number; m: Mark }[] = []; private pt = 0;
  part() { this.pt++; return this; }
  add(rank: number, cost: number, run: (G: Gfx, p: number) => void) { this.list.push({ part: this.pt, rank, i: this.list.length, m: { cost, run } }); return this; }
  sorted(): Mark[] { return [...this.list].sort((a, b) => a.part - b.part || a.rank - b.rank || a.i - b.i).map((q) => q.m); }
}
