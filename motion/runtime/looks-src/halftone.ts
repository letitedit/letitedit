// letitedit hand: newsprint halftone. M.look.halftone.start(w, h, {scale}) gives the marks; the AI writes the scene. See
// motion\runtime\looks\halftone.md.
//
// Adapted from anidoodle's canvas-core/halftone.ts and halftoneKit.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77).
// Changed by letitedit, 4 Nov 2026: the kit is used as it stands; the press values and the way a plate is starved in strips are taken
// from halftone.ts, now in set levels and filled strip by strip for speed; the viaduct, the train and the delivery-pile film are left out; print(), photo(), line art and spot()/black() are
// ours, on .\worked.ts. The picture is painted once as two separations at half size, then screened.
import { type Ctx, type Env, type Gfx, type Layer, type Medium, type P } from "./anidoodle/core";
import { clamp, inkDots, ks, mottleTile, NEWSPRINT, newsprint, newTone, over, screenDots, smoothstep, toneAt, type Dot, type Tone } from "./anidoodle/halftoneKit";
import { register } from "./shared";
import { Work, WorkHand, type WorkOpts } from "./worked";

const BLACK = "#1d1a17", SPOT = "#e86a2c", KEYS = 12, STRIPS = 54;
const PRESS: Medium = { nib: 1, taper: 0.3, pressure: 0.3, retrace: false, wobble: 0.3, rough: 0.2 };
const hash = (a: number, b: number) => Math.abs(Math.sin(a * 12.9898 + b * 78.233) * 43758.5453) % 1;
const across = (level: number, seed: number) => (x: number) => {
  if (level >= 1) return 1; if (level <= 0) return 0;
  const f = x * (KEYS - 1), i = Math.floor(f), t = f - i, e = (1 - Math.cos(t * Math.PI)) / 2, key = (z: number) => clamp(level * 1.5 - hash(z, seed) * 0.6 - 0.1);
  return key(i) * (1 - e) + key(Math.min(KEYS - 1, i + 1)) * e;
};

// The kit's plateLayer, with the dots inked in small batches: one path of 180,000 dots takes half a minute to fill with no graphics card.
const plate = (env: Env, w: number, h: number, dots: Dot[], color: string, spread: number, seed: number): Layer => {
  const k = env.scale, DW = Math.round(w * k), DH = Math.round(h * k), L = env.canvas(DW, DH), c = L.ctx; c.setTransform(k, 0, 0, k, 0, 0); c.fillStyle = color;
  for (let i = 0; i < dots.length; i += 300) inkDots(c, dots.slice(i, i + 300), seed);
  const q = Math.max(1, Math.round(DW / (spread * k * 2.2))), qh = Math.max(1, Math.round((q * DH) / DW)), S = env.canvas(q, qh);
  S.ctx.imageSmoothingEnabled = true; S.ctx.drawImage(L.canvas as CanvasImageSource, 0, 0, q, qh);
  c.setTransform(1, 0, 0, 1, 0, 0); c.globalCompositeOperation = "destination-over"; c.globalAlpha = 0.5; c.imageSmoothingEnabled = true; c.drawImage(S.canvas as CanvasImageSource, 0, 0, DW, DH); c.globalAlpha = 1; c.globalCompositeOperation = "source-over";
  return L;
};

type Print = WorkOpts & { paint: (c: Ctx, W: number, H: number) => void; lineArt?: (c: Ctx) => void; spot?: string; black?: string; pitch?: number; angK?: number; angS?: number; gainK?: number; gainS?: number; fan?: number; reg?: P; regFrom?: P; margin?: number; res?: number; perSpot?: number; perBlack?: number };

class PressHand extends WorkHand {
  BLACK = BLACK; SPOT = SPOT; PAPER = NEWSPRINT; ks = ks; inkDots = inkDots; screenDots = screenDots; toneAt = toneAt; smoothstep = smoothstep;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, PRESS); }
  /** A sheet off the press. paint(c, W, H) paints the original with ks(black, spot) colours on a half-size surface, in this picture's own coordinates; it's screened on first use: black at 45 degrees, the spot at 15. lineArt(c) goes straight on the black plate unscreened, for headlines and rules. The spot comes up to colour first, then the black, then the spot is nudged into register. */
  print(id: string, o: Print): Work {
    const W = this.work(id, { ...o, ground: (G) => { const c = G.main; c.setTransform(1, 0, 0, 1, 0, 0); c.drawImage(newsprint(G.env, `halftone:paper:${G.env.W}x${G.env.H}@${G.env.scale}`).canvas as CanvasImageSource, 0, 0); }, finish: null });
    if (W.length) return W;
    let P: { k: Layer; s: Layer } | null = null, T: Tone | null = null; const last = new Map<string, { key: string; L: Layer }>();
    const pitch = o.pitch ?? 5.2, angK = o.angK ?? 45, angS = o.angS ?? 15, gK = o.gainK ?? 0.42, gS = o.gainS ?? 0.3, fan = o.fan ?? 0.0016, reg = o.reg ?? [1.2, 1.6], regFrom = o.regFrom ?? [9, -7], res = o.res ?? 0.5, margin = o.margin ?? 0, spot = o.spot ?? SPOT, black = o.black ?? BLACK;
    const b = { x0: margin, y0: margin, x1: W.w - margin, y1: W.h - margin }, inn = (x: number, y: number) => x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1;
    const plates = (G: Gfx) => {
      if (P) return P;
      const env = G.env, tw = Math.round(W.w * res), th = Math.round(W.h * res), Tn = (T = newTone(tw, th, W.w, W.h)), S = env.canvas(tw, th), c = S.ctx;
      c.setTransform(res, 0, 0, res, 0, 0); o.paint(c, W.w, W.h); over(Tn, S);
      const kd = screenDots(b, pitch, angK, (x, y) => (inn(x, y) ? toneAt(Tn, Tn.k, x, y) : 0), gK), sd = screenDots(b, pitch, angS, (x, y) => (inn(x, y) ? toneAt(Tn, Tn.s, x, y) : 0), gS, fan);
      const K = plate(env, W.w, W.h, kd, black, 0.9, 7), Sp = plate(env, W.w, W.h, sd, spot, 0.8, 11);
      if (o.lineArt) { const x = K.ctx; x.save(); x.setTransform(env.scale, 0, 0, env.scale, 0, 0); x.fillStyle = black; x.strokeStyle = black; o.lineArt(x); x.restore(); }
      P = { k: K, s: Sp }; return P;
    };
    // A press comes up to colour sheet by sheet, so a plate has a few set levels, not one for every frame: each is worked out once and the
    // last is kept, and any frame at that level is the same pixels.
    const inked = (G: Gfx, name: string, plate: Layer, level: number, off: P, seed: number): Layer => {
      const key = `${name}:${level}:${off[0]}:${off[1]}`, env = G.env, k = env.scale, DW = Math.round(W.w * k), DH = Math.round(W.h * k), have = last.get(name); if (have && have.key === key) return have.L;
      const L = have?.L ?? env.canvas(DW, DH), t = L.ctx, dens = across(level, seed), sw = W.w / STRIPS, sft: P = [hash(seed, 1) * 256, hash(seed, 2) * 256], tile = mottleTile(env);
      t.setTransform(1, 0, 0, 1, 0, 0); t.globalAlpha = 1; t.globalCompositeOperation = "copy"; t.drawImage(plate.canvas as CanvasImageSource, Math.round(off[0] * k), Math.round(off[1] * k)); t.globalCompositeOperation = "source-over";
      const pat = t.createPattern(tile.canvas as CanvasImageSource, "repeat")!; pat.setTransform(new DOMMatrix([k * 1.6, 0, 0, k * 1.6, sft[0] * k, sft[1] * k]));
      for (let z = 0; z < STRIPS; z++) { const v = dens((z + 0.5) / STRIPS); const x0 = Math.floor(z * sw * k), x1 = z === STRIPS - 1 ? DW : Math.floor((z + 1) * sw * k); if (v <= 0) { t.clearRect(x0, 0, x1 - x0, DH); continue; } if (v < 1) { t.globalCompositeOperation = "destination-out"; t.globalAlpha = clamp(1 - v * 0.9); t.fillStyle = pat; t.fillRect(x0, 0, x1 - x0, DH); t.globalAlpha = 1 - (0.3 + 0.7 * v); { t.globalCompositeOperation = "destination-out"; t.fillStyle = "#000"; t.fillRect(x0, 0, x1 - x0, DH); } t.globalCompositeOperation = "source-over"; t.globalAlpha = 1; } }
      last.set(name, { key, L }); return L;
    };
    const lay = (G: Gfx, L: Layer) => { const m = G.main; m.save(); m.setTransform(1, 0, 0, 1, 0, 0); m.globalCompositeOperation = "multiply"; m.drawImage(L.canvas as CanvasImageSource, 0, 0); m.restore(); };
    const step = (q: number, n: number) => (q >= 1 ? 1 : Math.floor(q * n) / n);
    // The spot is one mark and the black the next: the spot comes up to colour, then is nudged into register, and it is final by the time the black starts.
    W.add(o.perSpot ?? 40, (G, q) => { const P2 = plates(G), lvl = q >= 1 ? 1 : Math.min(1, step(q / 0.6, 8)), nudge = q >= 1 ? 1 : step(clamp((q - 0.6) / 0.4), 4), off: P = [regFrom[0] + (reg[0] - regFrom[0]) * nudge, regFrom[1] + (reg[1] - regFrom[1]) * nudge]; lay(G, inked(G, "s", P2.s, lvl, off, 11)); });
    W.add(o.perBlack ?? 40, (G, q) => { const P2 = plates(G); lay(G, inked(G, "k", P2.k, step(q, 10), [0, 0], 12)); });
    return W;
  }
  /** A real photo on the original: its dark becomes black density. Inside paint(c, ...). Needs a picture whose pixels can be read, so a data: picture; the scene loads it itself, and it must have finished loading by the first draw. k and s scale the separations. */
  photo(c: Ctx, image: CanvasImageSource, x: number, y: number, w: number, h: number, o: { k?: number; s?: number; gamma?: number } = {}) {
    const m = c.getTransform(), rw = Math.max(1, Math.round(w * m.a)), rh = Math.max(1, Math.round(h * m.d)), L = this.env.canvas(rw, rh); L.ctx.drawImage(image, 0, 0, rw, rh);
    const img = L.ctx.getImageData(0, 0, rw, rh), d = img.data, kk = o.k ?? 1, ss = o.s ?? 0, g = o.gamma ?? 1;
    for (let i = 0; i < d.length; i += 4) { const v = Math.pow(1 - (0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) / 255, g); d[i] = Math.round(255 * clamp(v * kk)); d[i + 1] = Math.round(255 * clamp(v * ss)); d[i + 2] = 0; }
    L.ctx.putImageData(img, 0, 0); c.drawImage(L.canvas as CanvasImageSource, x, y, w, h);
  }
}

register("halftone", { start: (w: number, h: number, o?: { scale?: number }) => new PressHand(w, h, o) });
