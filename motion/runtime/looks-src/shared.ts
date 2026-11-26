// letitedit: what every drawing hand shares. A hand is the marks and the paper of one medium; the AI writes the scene.
//
// The source of speed and of "frame N is the same whatever came before": anything expensive (paint strokes, prints, grain)
// is baked ONCE into a sprite, from seeds only, on first use, and every frame only places sprites. A sprite is a pure function
// of what was given to it, so seeking anywhere in any order gives the same pixels. Nothing here keeps state between frames
// except those sprites. Everything draws through the context's CURRENT transform, so a scene's camera moves it.
//
// Written for letitedit (GPL-3.0-or-later). Uses anidoodle's core (Apache-2.0, see .\anidoodle).
import { Gfx, rng, type Ctx, type Env, type Layer, type Medium, type P } from "./anidoodle/core";
import { bounds } from "./anidoodle/gallery";

export const makeEnv = (W: number, H: number, scale = 1): Env => ({
  W, H, scale, cache: new Map<string, unknown>(),
  canvas: (w: number, h: number): Layer => {
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(w)); canvas.height = Math.max(1, Math.round(h));
    return { canvas: canvas as Layer["canvas"], ctx: canvas.getContext("2d") as Ctx };
  },
});

type Box = { x0: number; y0: number; x1: number; y1: number };
export type Place = { x?: number; y?: number; s?: number; r?: number; pivot?: P; alpha?: number; clip?: Box };

const placed = (g: Ctx, o: Place, pivot: P | undefined, fn: () => void) => {
  g.save();
  if (o.clip) { g.beginPath(); g.rect(o.clip.x0, o.clip.y0, o.clip.x1 - o.clip.x0, o.clip.y1 - o.clip.y0); g.clip(); }
  const p = o.pivot ?? pivot ?? [0, 0], s = o.s ?? 1, r = o.r ?? 0;
  g.translate(p[0] + (o.x ?? 0), p[1] + (o.y ?? 0)); if (r) g.rotate(r); if (s !== 1) g.scale(s, s); g.translate(-p[0], -p[1]);
  fn();
  g.restore();
};

/** A baked picture at its own place in the world: draw(g, {x, y, s, r, pivot, alpha, clip}). */
export class Plate {
  private L: Layer | null = null;
  constructor(private hand: Hand, private paint: (c: Ctx) => void, public box: Box, public pivot?: P) {}
  bake() {
    if (this.L) return this.L;
    const k = this.hand.scale, b = this.box, L = this.hand.env.canvas(Math.ceil((b.x1 - b.x0) * k), Math.ceil((b.y1 - b.y0) * k));
    L.ctx.setTransform(k, 0, 0, k, -b.x0 * k, -b.y0 * k);
    this.paint(L.ctx);
    this.L = L; return L;
  }
  draw(g: Ctx, o: Place = {}) {
    const L = this.bake(), b = this.box;
    placed(g, o, this.pivot, () => { g.globalAlpha *= o.alpha ?? 1; g.drawImage(L.canvas as CanvasImageSource, b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); });
  }
}

// a soft copy of a layer without ctx.filter: halved N times, then scaled back up (the same idea as core's Gfx.soften)
const softened = (env: Env, src: Layer, w: number, h: number, radius: number): Layer => {
  const steps = Math.max(1, Math.round(Math.log2(Math.max(2, radius * 1.6))));
  let cur = src, cw = w, ch = h;
  const down: Layer[] = [];
  for (let i = 0; i < steps; i++) { const nw = Math.max(1, Math.ceil(cw / 2)), nh = Math.max(1, Math.ceil(ch / 2)), n = env.canvas(nw, nh); n.ctx.imageSmoothingEnabled = true; n.ctx.imageSmoothingQuality = "high"; n.ctx.drawImage(cur.canvas as CanvasImageSource, 0, 0, cw, ch, 0, 0, nw, nh); down.push(n); cur = n; cw = nw; ch = nh; }
  for (let i = steps - 2; i >= -1; i--) { const tw = i < 0 ? w : Math.ceil(w / 2 ** (i + 1)), th = i < 0 ? h : Math.ceil(h / 2 ** (i + 1)), n = env.canvas(tw, th); n.ctx.imageSmoothingEnabled = true; n.ctx.imageSmoothingQuality = "high"; n.ctx.drawImage(cur.canvas as CanvasImageSource, 0, 0, cw, ch, 0, 0, tw, th); cur = n; cw = tw; ch = th; }
  return cur;
};

// a hand-moved piece's pose: {dx, dy, rot, lift}; lift 0 = at rest on the flat behind, 1 = held up off it
export type Pose = { dx: number; dy: number; rot: number; lift: number };
export const REST: Pose = { dx: 0, dy: 0, rot: 0, lift: 0 };

export type PieceOpts = {
  cut: P[] | P[][];                 // the outline(s) of the card
  face: (c: Ctx) => void;           // paints it at rest
  hole?: boolean;                   // cut[1..] are holes in cut[0]
  border?: number;                  // a sticker's white margin, px
  borderColor?: string;
  edge?: string;                    // the card's cut edge, shown down-right; none if omitted
  depth?: number;                   // the gap to the flat behind: sets the shadow's distance
  pivot?: P;
  shadow?: string;
  stage?: Box;                      // walls in world space: the piece is hidden outside this box wherever it moves
};

const asList = (cut: P[] | P[][]): P[][] => (typeof (cut as P[][])[0][0] === "number" ? [cut as P[]] : (cut as P[][]));

/** One flat: a face sprite plus a soft shadow sprite. draw(g, {pose, x, y, s, r, alpha}) moves it; paint never moves. */
export class Piece {
  private face?: Layer; private shade?: Layer; private bx!: Box; private pad = 0;
  depth: number; pivot: P; cuts: P[][];
  constructor(private hand: Hand, public o: PieceOpts) {
    this.cuts = asList(o.cut); this.depth = o.depth ?? 6;
    const b = bounds(this.cuts.flat()); this.pivot = o.pivot ?? [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2];
  }
  private trace(c: Ctx, dx: number, dy: number, grow: number) {
    c.save(); c.translate(dx, dy); c.beginPath();
    this.cuts.forEach((s) => { s.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); });
    c.fill(this.o.hole ? "evenodd" : "nonzero");
    if (grow > 0) { c.lineJoin = "round"; c.lineWidth = 2 * grow; c.strokeStyle = c.fillStyle; c.stroke(); }
    c.restore();
  }
  bake() {
    if (this.face) return;
    const k = this.hand.scale, env = this.hand.env, bd = this.o.border ?? 0, blur = 2 + this.depth * 0.5, b0 = bounds(this.cuts.flat());
    this.pad = bd + 4 + Math.ceil(blur * 3);
    const b = (this.bx = { x0: b0.x0 - this.pad, y0: b0.y0 - this.pad, x1: b0.x1 + this.pad, y1: b0.y1 + this.pad });
    const W = Math.ceil((b.x1 - b.x0) * k), H = Math.ceil((b.y1 - b.y0) * k), at = (c: Ctx) => c.setTransform(k, 0, 0, k, -b.x0 * k, -b.y0 * k);
    const F = env.canvas(W, H), c = F.ctx; at(c);
    if (this.o.edge) { c.fillStyle = this.o.edge; this.trace(c, 1.2, 1.9, bd); }
    if (bd) { c.fillStyle = this.o.borderColor ?? "#fbf9f2"; this.trace(c, 0, 0, bd); }
    at(c); this.o.face(c); this.face = F;
    const S = env.canvas(W, H); at(S.ctx); S.ctx.fillStyle = this.o.shadow ?? "#2a1c10"; this.trace(S.ctx, 0, 0, bd);
    this.shade = softened(env, S, W, H, blur * k);
  }
  /** pose (from land / lay), or x, y, s, r on top; alpha fades the whole piece; shadow false leaves the shadow off. */
  draw(g: Ctx, o: Place & { pose?: Pose; shadow?: boolean } = {}) {
    this.bake();
    const q = o.pose ?? REST, b = this.bx, sd = this.depth * (1 + 2.2 * q.lift), w = b.x1 - b.x0, h = b.y1 - b.y0, a = o.alpha ?? 1;
    const stage = this.o.stage;
    placed(g, { ...o, clip: o.clip ?? stage, x: (o.x ?? 0) + q.dx, y: (o.y ?? 0) + q.dy, r: (o.r ?? 0) + q.rot }, this.pivot, () => {
      const base = g.globalAlpha;
      if (o.shadow !== false && this.depth > 0) { g.globalAlpha = base * a * Math.max(0, 0.36 - 0.1 * q.lift); g.drawImage(this.shade!.canvas as CanvasImageSource, b.x0 + sd * 0.6, b.y0 + sd, w, h); }
      g.globalAlpha = base * a; g.drawImage(this.face!.canvas as CanvasImageSource, b.x0, b.y0, w, h);
      g.globalAlpha = base;
    });
  }
}

const THIN: Medium = { nib: 1, taper: 0.3, pressure: 0.3, retrace: false, wobble: 0.4, rough: 0.3 };

/** The part of a hand every style has: a size, a sprite store, a clean start to a frame and the sheet laid over the end of one. */
export class Hand {
  env: Env; scale: number; w: number; h: number;
  private plates = new Map<string, Plate>(); private pieces = new Map<string, Piece>();
  constructor(w: number, h: number, o: { scale?: number } = {}) { this.w = w; this.h = h; this.scale = o.scale ?? 1; this.env = makeEnv(w, h, this.scale); }
  /** Puts the context back to a known state: call first in every frame. */
  begin(g: Ctx) { g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = "source-over"; g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high"; g.filter = "none"; return g; }
  /** paint(c) runs once, in world coordinates, the first time the plate is drawn. box = {x0, y0, x1, y1} (default the frame). */
  plate(id: string, paint: (c: Ctx) => void, box?: Box, pivot?: P): Plate {
    let p = this.plates.get(id); if (!p) { p = new Plate(this, paint, box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, pivot); this.plates.set(id, p); } return p;
  }
  piece(id: string, o: PieceOpts): Piece { let p = this.pieces.get(id); if (!p) { p = new Piece(this, o); this.pieces.set(id, p); } return p; }
  /** Laid over a finished frame in screen space: a sheet's tooth multiplied in, and handled edges. */
  sheet(g: Ctx, o: { paper?: number; vignette?: string | null; tile?: string } = {}) {
    g.save(); const G = new Gfx(g, this.env, 0, THIN);
    if ((o.paper ?? 0.12) > 0) G.paper(o.tile ?? "paper", o.paper ?? 0.12);
    if (o.vignette !== null) G.vignette(o.vignette ?? "rgba(60,36,14,0.32)");
    g.restore();
  }
  /** Time held on twos: a stop-motion pose lasts two frames. */
  twos(t: number, fps = 30) { const f = Math.round(t * fps + 1e-6); return (f - f % 2) / fps; }
  /** An ink line drawn through the current transform, wobbling and tapering like a hand: pts are smoothed; progress 0..1 draws part of it. */
  pen(g: Ctx, pts: P[], o: { w?: number; color?: string; seed?: number; wobble?: number; taper?: number; opacity?: number; progress?: number } = {}) {
    const m = g.getTransform(), a = g.globalAlpha, G = new Gfx(g, this.env, 0, THIN); g.setTransform(m);
    G.pen(pts, { w: o.w ?? 2.4, color: o.color ?? "#2a2019", seed: o.seed ?? 1, wobble: o.wobble ?? 0.5, boil: 0, taper: o.taper ?? 0.5, opacity: o.opacity ?? 0.95, retrace: false, progress: o.progress ?? 1 });
    g.globalAlpha = a;
  }
}

export const smoothStep = (x: number) => { const v = x <= 0 ? 0 : x >= 1 ? 1 : x; return v * v * (3 - 2 * v); };
export const seeded = rng;
export const register = (name: string, value: unknown) => {
  const M = (window as unknown as { M: { look?: Record<string, unknown> } }).M;
  (M.look = M.look || {})[name] = value;
};
