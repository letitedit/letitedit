// letitedit hand: folk-tale storybook, where depth is the medium. M.look.folkTale.start(w, h, {scale}) gives the marks; the AI writes the
// scene. See motion\runtime\looks\folkTale.md.
//
// Adapted from anidoodle's canvas-core/folkTale.ts and folkTaleKit.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77).
// Changed by letitedit, 4 Nov 2026: the kit is used as it stands; the garden and its film timeline are left out; page(), mark(), wash()
// and lines() are ours, on .\worked.ts.
import { type Ctx, type Medium, type P } from "./anidoodle/core";
import * as K from "./anidoodle/folkTaleKit";
import { register } from "./shared";
import { Work, WorkHand, type WorkOpts } from "./worked";

const FT: Medium = { nib: 1, taper: 0.8, pressure: 0.7, retrace: false, wobble: 0.7, rough: 0.6 };
const C = { paper: K.PAPER, haze: K.HAZE, graphite: K.GRAPH, sap: "#5f7a2c", olive: "#7c8b3a", leaf: "#3f5f28", ochre: "#c89a35", cadmium: "#eeb42a", orange: "#e2761c", vermilion: "#d6432a", violet: "#5d6fc4", umber: "#5a3d26", cream: "#f6ecd2", sky: "#cfe0d8" };

class FolkHand extends WorkHand {
  palette = C; LIGHT = K.LIGHT; lighten = K.lighten; darken = K.darken; far = K.far;
  bbox = K.bbox; cutAt = K.cutAt; ribbonOf = K.ribbonOf; at = K.at; rgba = K.rgba; trace = K.trace;
  pencil = K.pencil; sketch = K.sketch; gouache = K.gouache; reveal = K.reveal; faded = K.faded; ramp = K.ramp; radial = K.radial; glowBand = K.glowBand; stroke = K.stroke;
  leaf = K.leaf; lineLeaf = K.lineLeaf; leafGeom = K.leafGeom; petal = K.petal; sunflower = K.sunflower; daisy = K.daisy; bell = K.bell; dogRose = K.dogRose; umbel = K.umbel; grass = K.grass; limb = K.limb; lineLimb = K.lineLimb; pumpkin = K.pumpkin; gourdLeaf = K.gourdLeaf; tendril = K.tendril;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, FT); }
  /** The cream sheet with its slow glow: glow = [[x, y, radius, colour], ...]. paper: false leaves it bare, for a part on its own layer. */
  page(id: string, o: WorkOpts & { glow?: [number, number, number, string][]; paper?: boolean } = {}): Work {
    const bare = o.paper === false;
    return this.work(id, { ...o, ground: bare ? null : (G) => K.sheet(G, o.glow ?? [[(o.w ?? this.w) * 0.9, (o.h ?? this.h) * 0.5, (o.w ?? this.w) * 0.76, "#fbf3d6"]]), finish: bare ? null : (G) => { G.paper("paper", 0.14); G.paper("coldpress", 0.07); } });
  }
  /** Any kit mark on the list: fn(c, p) draws it at progress p, with c the page's surface. */
  mark(W: Work, per: number, fn: (c: Ctx, p: number) => void) { W.add(per, (G, q) => fn(G.cur, q)); return W; }
  /** A big area of paint: a wet front sweeps across it (noisy, never a fade), and it thins with depth d. */
  wash(W: Work, poly: P[], color: string, o: K.Gouache & { ang?: number; d?: number; per?: number }) {
    const box = K.bbox(poly), col = K.far(color, o.d ?? 0), a = (o.a ?? 1) * (1 - (o.d ?? 0) * 0.45);
    return this.mark(W, o.per ?? 3 + Math.sqrt((box[2] - box[0]) * (box[3] - box[1])) / 60, (c, p) => K.reveal(c, box, o.ang ?? 0.2, p, o.seed, () => K.gouache(c, poly, col, { ...o, a })));
  }
  /** Pencil lines drawn in order, paced by their length. */
  lines(W: Work, lines: K.Line[], o: { per?: number } = {}) { return this.mark(W, o.per ?? 2 + lines.reduce((a, l) => a + K.len(l.pts), 0) / 140, (c, p) => K.sketch(c, lines, p)); }
}

register("folkTale", { start: (w: number, h: number, o?: { scale?: number }) => new FolkHand(w, h, o) });
