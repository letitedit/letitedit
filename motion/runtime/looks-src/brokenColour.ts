// letitedit hand: broken colour, plein-air dabs of unmixed paint. M.look.brokenColour.start(w, h, {scale}) gives the marks; the AI writes
// the scene. See motion\runtime\looks\brokenColour.md.
//
// Adapted from anidoodle's canvas-core/brokenColour.ts and brokenColourKit.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77).
// Changed by letitedit, 4 Nov 2026: the kit is used as it stands; broken() and the sweep's order are taken from the harbour picture,
// which is left out with its light field and film timeline; canvas(), dabs() and lay() are ours, on .\worked.ts.
import { fractal, type Medium, type P } from "./anidoodle/core";
import { brush, css, fromHsl, linen, mixC, smoothstep, toHsl, type Mark, type RGB } from "./anidoodle/brokenColourKit";
import { register } from "./shared";
import { Work, WorkHand, type WorkOpts } from "./worked";

const M0: Medium = { nib: 1, taper: 0.6, pressure: 0.6, retrace: false, wobble: 0.8, rough: 0.5 };
const C: Record<string, RGB> = { white: [247, 240, 224], orange: [232, 130, 50], red: [212, 66, 48], yellow: [244, 196, 60], rose: [214, 92, 118], violet: [120, 92, 168], ultramarine: [52, 66, 150], cobalt: [76, 112, 186], viridian: [46, 128, 110], dark: [46, 40, 96], ground: [226, 198, 168] };

/** A colour's neighbours, not a blend: hue, value and saturation thrown a little, dab by dab. */
const broken = (c: RGB, r: () => number, hj = 0.03, lj = 0.05, sat: [number, number] = [0.95, 1.25]): RGB => { const [h, s, l] = toHsl(c); return fromHsl([h + (r() - 0.5) * 2 * hj, Math.min(1, s * (sat[0] + r() * (sat[1] - sat[0]))), Math.max(0.04, Math.min(0.97, l + (r() - 0.5) * 2 * lj))]); };

type Dabs = { x0?: number; y0?: number; x1?: number; y1?: number; step: number; color: (x: number, y: number) => RGB | null; ang?: (x: number, y: number) => number; len?: number; w?: number; kind?: 0 | 1 | 2; alpha?: number; seed?: number; patch?: number; order?: (x: number, y: number) => number; hj?: number; lj?: number; sat?: [number, number]; per?: number };

class BrokenHand extends WorkHand {
  palette = C; css = css; mixC = mixC; toHsl = toHsl; fromHsl = fromHsl; smoothstep = smoothstep; broken = broken;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, M0); }
  /** Primed linen in the ground colour. The weave goes over the paint, every frame until it's done. */
  canvas(id: string, o: WorkOpts & { color?: RGB } = {}): Work {
    return this.work(id, { ...o, ground: (G) => { const c = G.cur, e = G.env; c.setTransform(1, 0, 0, 1, 0, 0); c.fillStyle = css(o.color ?? C.ground); c.fillRect(0, 0, Math.round(e.W * e.scale), Math.round(e.H * e.scale)); }, finish: (G) => linen(G.main, G.env, 0.26) });
  }
  /** One mark: {a, b, bend, w, rgb, alpha, seed, kind}; kind 0 a loaded dab, 1 a liner line tapered at both ends, 2 a thin scrubbed lay-in. */
  mark(a: P, b: P, rgb: RGB, o: { w?: number; bend?: number; alpha?: number; seed?: number; kind?: 0 | 1 | 2 } = {}): Mark { return { a, b, rgb, w: o.w ?? 10, bend: o.bend ?? 0, alpha: o.alpha ?? 0.95, seed: o.seed ?? 1, kind: o.kind ?? 0 }; }
  lay(W: Work, marks: Mark[], o: { per?: number; clip?: P[]; out?: P[][] } = {}) {
    marks.forEach((m) => W.add(o.per ?? 1, (G, q) => { if (o.clip || o.out) this.within(G, o.clip ?? null, o.out ?? null, () => brush(G.cur, G.env, m, q)); else brush(G.cur, G.env, m, q); }));
    return W;
  }
  /** A pass over an area: a jittered grid of dabs, visited patch by patch the way a hand moves round a canvas, never as a scanline. */
  dabs(W: Work, o: Dabs) {
    const seed = o.seed ?? 11, r = this.rng(seed), step = o.step, patch = o.patch ?? 220, x0 = o.x0 ?? 0, y0 = o.y0 ?? 0, x1 = o.x1 ?? W.w, y1 = o.y1 ?? W.h, list: { x: number; y: number; k: number; c: RGB }[] = [];
    for (let y = y0 - step / 2; y < y1 + step; y += step) for (let x = x0 - step / 2; x < x1 + step; x += step) {
      const px = x + (r() - 0.5) * step * 1.3, py = y + (r() - 0.5) * step * 1.3, jig = r(), c = o.color(px, py); if (!c) continue;
      list.push({ x: px, y: py, c, k: (o.order ? o.order(px, py) * patch * 4 : py * 0.3) + fractal(seed + 2, px, py, 1 / patch, 1 / patch, 2) * patch * 1.4 + jig * patch * 0.25 });
    }
    list.sort((a, b) => a.k - b.k);
    list.forEach((d, i) => { const a = (o.ang ? o.ang(d.x, d.y) : 0) + (r() - 0.5) * 0.3, L = (o.len ?? step * 1.5) * (0.75 + r() * 0.5), dx = Math.cos(a) * L / 2, dy = Math.sin(a) * L / 2; this.lay(W, [{ a: [d.x - dx, d.y - dy], b: [d.x + dx, d.y + dy], bend: (r() - 0.5) * L * 0.1, w: (o.w ?? step * 0.6) * (0.8 + r() * 0.4), rgb: broken(d.c, r, o.hj, o.lj, o.sat), alpha: o.alpha ?? 0.95, seed: seed * 100 + i, kind: o.kind ?? 0 }], { per: o.per ?? 1 }); });
    return W;
  }
}

register("brokenColour", { start: (w: number, h: number, o?: { scale?: number }) => new BrokenHand(w, h, o) });
