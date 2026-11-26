// letitedit hand: oil on canvas. M.look.paintedOil.start(w, h, {scale}) gives the marks; the AI writes the scene. See
// motion\runtime\looks\paintedOil.md.
//
// Adapted from anidoodle's canvas-core/paintedOil.ts and paintedOilKit.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77).
// Changed by letitedit, 4 Nov 2026: the kit is used as it stands; the pears, the pot and their film timeline are left out; canvas(),
// lay(), rub(), drawing() and the clipping are ours, on .\worked.ts.
import { type Gfx, type Medium, type P } from "./anidoodle/core";
import { mix } from "./anidoodle/gallery";
import { darken, fill, LIGHT, lighten, oilStroke, weave, type OStroke, type Pass } from "./anidoodle/paintedOilKit";
import { register } from "./shared";
import { Work, WorkHand, type WorkOpts } from "./worked";

const OIL: Medium = { nib: 1, taper: 0.5, pressure: 0.6, retrace: false, wobble: 0.8, rough: 0.5 };
const C = { priming: "#efe8da", tone: "#a06f46", umber: "#4a3020", sienna: "#8d4f2a", ochre: "#c49a4a", naples: "#ecd9a0", terreVerte: "#6d7a5a", white: "#f6efe0", ivory: "#1f1712", copper: "#b5622f", pear: "#b7a13c", wall: "#5b4a38" };
type Lay = { per?: number; clip?: P[]; out?: P[][] };

class OilHand extends WorkHand {
  palette = C; LIGHT = LIGHT; lighten = lighten; darken = darken; stroke = oilStroke;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, OIL); }
  /** Stretched linen, primed with lead white: weave in the ground, weave again over the paint. toned: false leaves out the warm rub. */
  canvas(id: string, o: WorkOpts & { priming?: string; toned?: boolean; tone?: string } = {}): Work {
    const W = this.work(id, { ...o, ground: (G) => { const c = G.cur, e = G.env; c.setTransform(e.scale, 0, 0, e.scale, 0, 0); c.fillStyle = o.priming ?? C.priming; c.fillRect(0, 0, e.W, e.H); weave(G, 0.55); }, finish: (G) => weave(G, 0.3) });
    if (o.toned !== false && W.length === 0) this.rub(W, o.tone ?? C.tone);
    return W;
  }
  /** The imprimatura: a thin scrubbed rub of one colour over the priming, the first thing on the canvas. */
  rub(W: Work, tone: string, o: { n?: number; per?: number; seed?: number } = {}) {
    const r = this.rng(o.seed ?? 3), n = o.n ?? Math.ceil(W.h / 76) + 2, out: OStroke[] = [];
    for (let i = 0; i < n; i++) { const y = -40 + i * (W.h + 80) / n + r() * 30, a = (i % 2 ? 0.12 : -0.1) + (r() - 0.5) * 0.1; out.push({ ctrl: [[-W.w * 0.2, y - a * W.w * 0.55], [W.w / 2, y + (r() - 0.5) * 40], [W.w * 1.2, y + a * W.w * 0.55]], w: 150, c0: mix(tone, "#7e5636", r() * 0.5), c1: mix(tone, "#a87a50", r() * 0.5), load: 1.3, dry: 0.3, impasto: 0, alpha: 0.82, jit: 0.06, seed: 10 + i }); }
    return this.lay(W, out, { per: o.per ?? 2.6 });
  }
  /** Strokes from a region: a pass of the brush. pass = {region, step, len, w, dir(x, y), color(x, y), seed, load, dry, impasto, bend, sweep, jit, soft, path}. */
  strokes(p: Pass) { return fill(p); }
  /** Puts strokes on the list in order. per = their weight each; clip keeps them inside a shape (a found edge), out keeps them off others. */
  lay(W: Work, strokes: OStroke[], o: Lay = {}) {
    strokes.forEach((s) => W.add(o.per ?? 1, (G: Gfx, q: number) => { if (o.clip || o.out) this.within(G, o.clip ?? null, o.out ?? null, () => oilStroke(G, s, q)); else oilStroke(G, s, q); }));
    return W;
  }
  /** The thin searching line in burnt umber, drawn with a small round brush before any body colour. */
  drawing(W: Work, ctrl: P[], o: { w?: number; alpha?: number; seed?: number; per?: number; color?: string } = {}) {
    return this.lay(W, [{ ctrl, w: o.w ?? 3.2, c0: o.color ?? C.umber, load: 1, dry: 0.15, impasto: 0, alpha: o.alpha ?? 0.78, seed: o.seed ?? 1 }], { per: o.per ?? 1.5 });
  }
}

register("paintedOil", { start: (w: number, h: number, o?: { scale?: number }) => new OilHand(w, h, o) });
