// letitedit: a picture that gets made in front of the viewer, for the paint and print hands.
//
// A Work is a surface, a ground and an ordered list of marks (a stroke, a dab, a pull of a block). draw(g, {p}) shows it p of the way
// through. Any p gives the same pixels whatever was asked for before: the surface after n marks is always the ground plus marks 0..n-1
// in order on one canvas, and going back restores a saved copy from fixed places in the list and lays the same marks again from there.
// Only the mark in hand is drawn at its progress, on a scratch copy; once p is 1 the finished picture is a sprite.
// Kept apart from shared.ts so that the hands already saved in scenes keep their text, and so their hash.
//
// Written for letitedit (GPL-3.0-or-later). The idea of a process list comes from anidoodle's sumiEKit (Apache-2.0, see .\anidoodle).
import { arc, displace, fractal, Gfx, heart, jitter, line, oval, poly, rng, sample, softBox, tube, turn, type Ctx, type Env, type Layer, type Medium, type P } from "./anidoodle/core";
import { bounds, clamp, inside, lerp, mix, profile, resample, smooth } from "./anidoodle/gallery";
import { Hand, makeEnv } from "./shared";

export type Draw = { p?: number; x?: number; y?: number; s?: number; r?: number; pivot?: P; alpha?: number; clip?: { x0: number; y0: number; x1: number; y1: number } };
type Mark = { t0: number; t1: number; draw: (G: Gfx, q: number) => void };
export type WorkOpts = { w?: number; h?: number; ground?: ((G: Gfx) => void) | null; finish?: ((G: Gfx) => void) | null; medium?: Medium };

const KEEP = 8;   // saved copies along the list: about 8 MB each at 1080x1920

export class Work {
  env: Env; w: number; h: number; medium: Medium;
  private marks: Mark[] = []; private total = 0; private ground: WorkOpts["ground"]; private fin: WorkOpts["finish"];
  private live?: { n: number; L: Layer }; private saved = new Map<number, Layer>(); private scratch?: Layer; private done?: Layer;
  constructor(hand: Hand, medium: Medium, o: WorkOpts) {
    this.w = o.w ?? hand.w; this.h = o.h ?? hand.h; this.medium = o.medium ?? medium; this.ground = o.ground; this.fin = o.finish;
    this.env = makeEnv(this.w, this.h, hand.scale); this.env.cache = hand.env.cache;
  }
  private get DW() { return Math.round(this.w * this.env.scale); }
  private get DH() { return Math.round(this.h * this.env.scale); }
  /** Adds a mark that takes `weight` of the picture's time. draw(G, q): G is the core's drawing context on this surface, q goes up to exactly 1. */
  add(weight: number, draw: (G: Gfx, q: number) => void) { if (this.live || this.done) throw new Error("add every mark before the first draw"); const t0 = this.total; this.total += Math.max(1e-6, weight); this.marks.push({ t0, t1: this.total, draw }); return this; }
  /** A breath between passes, with nothing moving. */
  pause(weight: number) { this.total += weight; return this; }
  get length() { return this.marks.length; }
  /** Where a mark's window ends, 0..1: to land a later pass on a word. */
  at(n: number) { const m = this.marks[Math.max(0, Math.min(this.marks.length - 1, n))]; return m ? m.t1 / (this.total || 1) : 1; }
  private on(L: Layer) { const c = L.ctx; c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 1; c.globalCompositeOperation = "source-over"; return new Gfx(c, this.env, 0, this.medium); }
  private copy(from: Layer, to: Layer) { const c = to.ctx; c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 1; c.globalCompositeOperation = "copy"; c.imageSmoothingEnabled = false; c.drawImage(from.canvas as CanvasImageSource, 0, 0); c.globalCompositeOperation = "source-over"; c.imageSmoothingEnabled = true; }
  private get every() { return Math.max(1, Math.ceil(this.marks.length / KEEP)); }
  private surface(n: number): Layer {
    const every = this.every, mark = Math.floor(n / every) * every;
    let cur = this.live;
    if (!cur || cur.n > n || cur.n < mark) {
      // back to the nearest saved copy at or before n; the copies themselves are only ever made on the way forward
      let from = -1, L: Layer | undefined;
      for (const k of this.saved.keys()) if (k <= n && k > from) { from = k; L = this.saved.get(k); }
      if (cur && cur.n <= n && cur.n > from) { from = cur.n; L = undefined; }
      if (from < 0) {
        const fresh = cur?.L ?? this.env.canvas(this.DW, this.DH); fresh.ctx.setTransform(1, 0, 0, 1, 0, 0); fresh.ctx.clearRect(0, 0, this.DW, this.DH);
        if (this.ground) this.ground(this.on(fresh));
        cur = { n: 0, L: fresh }; const s = this.env.canvas(this.DW, this.DH); this.copy(fresh, s); this.saved.set(0, s);
      } else if (L) { const t = cur?.L ?? this.env.canvas(this.DW, this.DH); this.copy(L, t); cur = { n: from, L: t }; }
      this.live = cur;
    }
    if (cur.n < n) {
      const G = this.on(cur.L);
      for (let i = cur.n; i < n; i++) {
        const c = cur.L.ctx; c.save(); this.marks[i].draw(G, 1); c.restore();   // what one mark sets (a line's cap, a clip) can't reach the next
        const k = i + 1; if (k % every === 0 && k < this.marks.length && !this.saved.has(k)) { const s = this.env.canvas(this.DW, this.DH); this.copy(cur.L, s); this.saved.set(k, s); }
      }
      cur.n = n;
    }
    return cur.L;
  }
  /** The picture at p as a layer (for a hand that needs to read it, say). */
  layer(p = 1): Layer {
    const list = this.marks, t = clamp(p) * this.total;
    if (p >= 1) {
      if (this.done) return this.done;
      const L = this.surface(list.length);
      if (!this.fin) return L;
      const D = this.env.canvas(this.DW, this.DH); this.copy(L, D); this.fin(this.on(D)); this.done = D; return D;
    }
    let lo = 0, hi = list.length; while (lo < hi) { const m = (lo + hi) >> 1; if (list[m].t1 <= t) lo = m + 1; else hi = m; }
    const n = lo, L = this.surface(n), m = list[n], q = m && t > m.t0 ? (t - m.t0) / (m.t1 - m.t0) : 0;
    if (q <= 0 && !this.fin) return L;
    const S = this.scratch ?? (this.scratch = this.env.canvas(this.DW, this.DH)); this.copy(L, S);
    const G = this.on(S); if (q > 0) { S.ctx.save(); m.draw(G, q); S.ctx.restore(); }
    if (this.fin) this.fin(this.on(S));
    return S;
  }
  /** Places it through the context's current transform, so a camera moves it. p (default 1) is how far through its marks it is. */
  draw(g: Ctx, o: Draw = {}) {
    const L = this.layer(o.p ?? 1), a = o.alpha ?? 1, s = o.s ?? 1, r = o.r ?? 0, pv = o.pivot ?? [this.w / 2, this.h / 2];
    g.save();
    if (o.clip) { g.beginPath(); g.rect(o.clip.x0, o.clip.y0, o.clip.x1 - o.clip.x0, o.clip.y1 - o.clip.y0); g.clip(); }
    g.translate(pv[0] + (o.x ?? 0), pv[1] + (o.y ?? 0)); if (r) g.rotate(r); if (s !== 1) g.scale(s, s); g.translate(-pv[0], -pv[1]);
    g.globalAlpha *= a; g.drawImage(L.canvas as CanvasImageSource, 0, 0, this.w, this.h);
    g.restore();
  }
}

/** What the paint and print hands share beyond a Hand: works, and the plain geometry every scene needs. */
export class WorkHand extends Hand {
  private works = new Map<string, Work>(); protected medium: Medium;
  rng = rng; fractal = fractal; mix = mix; lerp = lerp; clamp = clamp; bounds = bounds; inside = inside; resample = resample; profile = profile;
  smooth = (pts: P[], closed = false, per = 10): P[] => smooth(pts, closed, per);
  oval = oval; softBox = softBox; arc = arc; line = line; turn = turn; poly = poly; heart = heart; tube = tube; displace = displace; jitter = jitter; sample = sample;
  constructor(w: number, h: number, o: { scale?: number } | undefined, medium: Medium) { super(w, h, o); this.medium = medium; }
  /** One picture: make it once at the top of the block, add its marks, then draw it every frame. */
  work(id: string, o: WorkOpts = {}): Work { let W = this.works.get(id); if (!W) { W = new Work(this, this.medium, o); this.works.set(id, W); } return W; }
  /** Runs fn with the surface clipped to a shape, and optionally with other shapes cut out of it: strokes that must not cross an edge. */
  within(G: Gfx, shape: P[] | null, out: P[][] | null, fn: () => void) {
    const c = G.cur; c.save(); c.beginPath(); const tr = (s: P[]) => { s.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); };
    if (shape) { tr(shape); if (out) out.forEach(tr); c.clip("evenodd"); }
    else if (out) { c.rect(-1e5, -1e5, 2e5, 2e5); out.forEach(tr); c.clip("evenodd"); }
    fn(); c.restore();
  }
}
