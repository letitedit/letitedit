// letitedit hand: ukiyo-e woodblock. M.look.woodcut.start(w, h, {scale}) gives the marks; the AI writes the scene. See
// motion\runtime\looks\woodcut.md.
//
// Adapted from anidoodle's canvas-core/woodcut.ts and woodcutKit.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77).
// Changed by letitedit, 4 Nov 2026: the kit is used as it stands; the block layer, the pull through the baren and the kento marks are
// taken from woodcut.ts and now take a block's own box; the herons, the bridge and the film timeline are left out; print() and pull()
// are ours, on .\worked.ts.
import { fractal, type Gfx, type Ctx, type Env, type Layer, type Medium, type P } from "./anidoodle/core";
import { bokashi, carved, even, fillAll, gouged, grain, rubPath, smoothstep, WASHI, washi } from "./anidoodle/woodcutKit";
import { register } from "./shared";
import { Work, WorkHand, type WorkOpts } from "./worked";

const C = { sumi: "#1f1b18", usuzumi: "#c6c1b0", yellow: "#d49c3a", grey: "#9fa4a4", bank: "#adaf9c", wood: "#a77a4a", water: "#9ab5c4", reed: "#7d8a73", rain: "#8a8983", beroAi: "#2c4a78", indigo: "#3a4557", red: "#b8452f", pink: "#d9a08f", paper: WASHI };
const BLOCK: Medium = { nib: 1, taper: 0.3, pressure: 0.3, retrace: false, wobble: 0.2, rough: 0.2 };
type Box = { x0: number; y0: number; x1: number; y1: number };
type Block = { cut: (c: Ctx) => void; color?: string; alpha?: number; grain?: number; seed?: number; reg?: P; box?: Box; per?: number; pad?: number };

const kento = (c: Ctx, env: Env, I: Box) => {
  const s = env.scale; c.save(); c.setTransform(s, 0, 0, s, 0, 0); c.lineWidth = 1.2;
  const mark = (pts: P[]) => { c.strokeStyle = "rgba(255,252,240,0.8)"; c.beginPath(); pts.forEach(([x, y], i) => (i ? c.lineTo(x - 0.8, y - 0.8) : c.moveTo(x - 0.8, y - 0.8))); c.stroke(); c.strokeStyle = "rgba(120,100,70,0.35)"; c.beginPath(); pts.forEach(([x, y], i) => (i ? c.lineTo(x + 0.8, y + 0.8) : c.moveTo(x + 0.8, y + 0.8))); c.stroke(); };
  mark([[I.x1 - 30, I.y1 + 26], [I.x1, I.y1 + 26], [I.x1, I.y1 + 8]]); mark([[I.x0 + 150, I.y1 + 26], [I.x0 + 214, I.y1 + 26]]);
  c.restore();
};

class WoodHand extends WorkHand {
  palette = C; carved = carved; gouged = gouged; fillAll = fillAll; bokashi = bokashi; even = even; smoothstep = smoothstep;
  private margins = new Map<Work, Box>(); private pulls = new Map<Work, number>();
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, BLOCK); }
  /** A sheet of kozo washi with a bare margin round the picture; I is the picture's box. margin: 0 runs it to the edge. */
  print(id: string, o: WorkOpts & { margin?: number } = {}): Work {
    const W = this.work(id, { ...o, ground: (G) => { const c = G.main; c.setTransform(1, 0, 0, 1, 0, 0); c.drawImage(washi(G.env).canvas as CanvasImageSource, 0, 0); }, finish: null }), m = o.margin ?? Math.round(Math.min(W.w, W.h) * 0.05);
    this.margins.set(W, { x0: m, y0: m, x1: W.w - m, y1: W.h - m });
    return W;
  }
  /** The picture's box inside the margin. */
  box(W: Work) { return this.margins.get(W) ?? { x0: 0, y0: 0, x1: W.w, y1: W.h }; }
  /** One block, printed: cut(c) paints where this block carries pigment (uncut wood prints as bare paper), in its one colour. Comes through where the baren has rubbed, in zig-zag rows over the block's own box. The first pull should be the key block, then the colours, in print order. */
  pull(W: Work, b: Block) {
    const I = this.box(W), seed = b.seed ?? 3 + (this.pulls.get(W) ?? 0) * 7, nth = this.pulls.get(W) ?? 0, reg = b.reg ?? [0, 0], box = b.box ?? I, pad = b.pad ?? Math.min(250, Math.max(60, (box.x1 - box.x0) * 0.24));
    this.pulls.set(W, nth + 1);
    let L: Layer | null = null, mask: Layer | null = null, track: P[] | null = null;
    // the kit's rubMask with its points kept and spaced wider: a pad this big doesn't need one every 3 px, and it's drawn every frame of a pull
    const rub = (c: Ctx, u: number) => { const s = track ?? (track = even(rubPath(box, pad), Math.max(3, pad * 0.1))), n = Math.max(1, Math.round((s.length - 1) * u)); c.fillStyle = "#000"; c.beginPath(); for (let i = 0; i <= n && i < s.length; i++) { const [x, y] = s[i], rr = (pad / 2) * (0.9 + 0.2 * fractal(seed * 7, x, y, 0.05, 0.05, 1)); c.moveTo(x + rr, y); c.arc(x, y, rr, 0, Math.PI * 2); } c.fill(); };
    const block = (env: Env): Layer => {
      if (L) return L; const k = env.scale; L = env.canvas(Math.round(W.w * k), Math.round(W.h * k)); const c = L.ctx;
      c.setTransform(k, 0, 0, k, reg[0] * k, reg[1] * k); c.save(); c.beginPath(); c.rect(I.x0 - 2 - reg[0], I.y0 - 2 - reg[1], I.x1 - I.x0 + 4, I.y1 - I.y0 + 4); c.clip(); if (b.color) { c.fillStyle = b.color; c.strokeStyle = b.color; } b.cut(c); c.restore();
      grain(c, env, b.grain ?? 0.2, [seed * 97 % 512, seed * 211 % 512], ((seed % 3) - 1) * 0.004);
      return L;
    };
    W.add(b.per ?? 8 + Math.sqrt((box.x1 - box.x0) * (box.y1 - box.y0)) / 30, (G: Gfx, q: number) => {
      const env = G.env, m = G.main, k = env.scale, DW = Math.round(W.w * k), DH = Math.round(W.h * k), a = b.alpha ?? 1, B = block(env); m.save(); m.setTransform(1, 0, 0, 1, 0, 0);
      if (q >= 1) { m.globalCompositeOperation = "multiply"; m.globalAlpha = a; m.drawImage(B.canvas as CanvasImageSource, 0, 0); m.restore(); if (nth === 0) kento(m, env, I); return; }
      const T = mask ?? (mask = env.canvas(DW, DH)), c = T.ctx;
      c.setTransform(1, 0, 0, 1, 0, 0); c.globalCompositeOperation = "source-over"; c.clearRect(0, 0, DW, DH); c.setTransform(k, 0, 0, k, 0, 0); rub(c, q);
      c.setTransform(1, 0, 0, 1, 0, 0); c.globalCompositeOperation = "source-in"; c.drawImage(B.canvas as CanvasImageSource, 0, 0); c.globalCompositeOperation = "source-over";
      m.globalCompositeOperation = "multiply"; m.globalAlpha = a; m.drawImage(T.canvas as CanvasImageSource, 0, 0); m.restore();
    });
    return W;
  }
  /** A pause while the next block is inked. */
  ink(W: Work, per = 5) { return W.pause(per); }
}

register("woodcut", { start: (w: number, h: number, o?: { scale?: number }) => new WoodHand(w, h, o) });
