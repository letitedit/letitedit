// letitedit hand: dream glaze, thin oil glazes with no visible stroke, every edge hard, one low sun. M.look.dreamGlaze.start(w, h, {scale})
// gives the technique; the AI writes the scene. See motion\runtime\looks\dreamGlaze.md.
//
// Adapted from anidoodle's canvas-core/dreamGlaze.ts and dreamGlazeKit.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77).
// Changed by letitedit, 4 Nov 2026: the kit is used as it stands; its own picture and film timeline are left out; picture(), the sheet of
// the back and the marks that lay it in rows and work each form up are ours, on .\worked.ts.
import { type Medium } from "./anidoodle/core";
import { ball, cl, curve, fbm, G as gauss, hash2, hex, laid, lin, near, NR, OUT, paintForms, raise, ramp, rows, sm, sunlight, surface, tube, vnoise, workPlan, workUp, type C3, type Obj, type Painter } from "./anidoodle/dreamGlazeKit";
import { PENCIL } from "./anidoodle/core";
import { register } from "./shared";
import { Work, WorkHand, type WorkOpts } from "./worked";

const GLAZE: Medium = PENCIL;
const C = { ultramarine: "#1f3f8f", turquoise: "#3e9bb0", lemon: "#f2e9a0", ochre: "#b68a45", umber: "#5a3f2a", flesh: "#d9b08c", violet: "#40304f", orange: "#e8701f", white: "#f5efe0" };

type Picture = WorkOpts & {
  back?: (x: number, y: number, out: C3) => void;                                 // the sky and ground: a LINEAR colour for this point, into out
  objs?: () => Obj[];                                                             // the standing things, back to front
  paint?: Painter;                                                                // their albedo and light: leave a linear colour in D.OUT
  band?: number;                                                                  // the rows the back is laid in, px
  perBack?: number; perForm?: number; hold?: number;
};

class GlazeHand extends WorkHand {
  palette = C; OUT = OUT; cl = cl; sm = sm; G = gauss; hash2 = hash2; vnoise = vnoise; fbm = fbm; hex = hex; lin = lin; ramp = ramp; sunlight = sunlight; curve = curve; near = near; NR = NR; tube = tube; ball = ball; rows = rows; laid = laid;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, GLAZE); }
  /** One picture: back(x, y, out), per pixel, for the sky and ground, and objs/paint for the forms that stand on it. Everything is computed once per pixel on first use, which is the cost of this hand. It paints itself: the back in wavering rows, then each form in its shadow tone and worked up to the light. */
  picture(id: string, o: Picture): Work {
    const W = this.work(id, { ...o, ground: (G) => { const c = G.cur; c.setTransform(1, 0, 0, 1, 0, 0); c.fillStyle = "#f5efe0"; c.fillRect(0, 0, Math.round(G.env.W * G.env.scale), Math.round(G.env.H * G.env.scale)); }, finish: (G) => surface(G.main, G.env, W0(), H0()) }), W0 = () => W.w, H0 = () => W.h;
    if (W.length) return W;
    const GAM = new Uint8ClampedArray(4097); for (let i = 0; i <= 4096; i++) GAM[i] = Math.round(255 * Math.pow(i / 4096, 1 / 2.2));
    const tone = (v: number) => GAM[Math.round(4096 * (1 - Math.exp(-1.35 * Math.max(0, v))))];
    type F = { R: ReturnType<typeof raise>; objL: ReturnType<typeof paintForms>["objL"]; px: Uint8ClampedArray; oid: Uint8Array; boxes: number[][] };
    let f: F | null = null, backL: ReturnType<WorkHand["env"]["canvas"]> | null = null;
    const n = o.objs ? o.objs().length : 0, objs = o.objs;
    const forms = (env: WorkHand["env"]): F => {
      if (f) return f; const list = objs ? objs() : [], R = raise(env, W.w, W.h, list), P = paintForms(env, R, o.paint ?? (() => { OUT[0] = OUT[1] = OUT[2] = 0.5; }));
      f = { R, objL: P.objL, px: P.px, oid: P.oid, boxes: list.map((ob) => ob.box) }; return f;
    };
    const back = (env: WorkHand["env"]) => {
      if (backL) return backL; const s = env.scale, DW = Math.round(W.w * s), DH = Math.round(W.h * s), L = env.canvas(DW, DH), img = L.ctx.createImageData(DW, DH), d = img.data, c: C3 = [0, 0, 0];
      for (let j = 0; j < DH; j++) for (let i = 0; i < DW; i++) { o.back!((i + 0.5) / s, (j + 0.5) / s, c); const p = (j * DW + i) * 4; d[p] = tone(c[0]); d[p + 1] = tone(c[1]); d[p + 2] = tone(c[2]); d[p + 3] = 255; }
      L.ctx.putImageData(img, 0, 0); backL = L; return L;
    };
    if (o.back) W.add(o.perBack ?? 40, (G, q) => { const c = G.main, s = G.env.scale; c.save(); if (q >= 1) { c.setTransform(1, 0, 0, 1, 0, 0); c.drawImage(back(G.env).canvas as CanvasImageSource, 0, 0); } else laid(c, s, back(G.env), q, [0, 1], [0, 0, W.w, W.h], o.band ?? 60, 1); c.restore(); });
    for (let li = 0; li < n; li++) {
      W.add(o.perForm ?? 24, (G, q) => {
        const F = forms(G.env), c = G.main, DW = F.R.DW, DH = F.R.DH, plan = workPlan(G.env, `glaze:${id}`, DW, DH, F.px, (g) => F.oid[g], (i) => F.boxes[i - 1], () => 30);
        c.save(); c.setTransform(1, 0, 0, 1, 0, 0); workUp(c, plan, F.px, q >= 1 ? 2 : q, (i) => (i === li + 1 ? [0, 0.5, 0.4, 1] : undefined)); c.restore();
      });
    }
    return W;
  }
}

register("dreamGlaze", { start: (w: number, h: number, o?: { scale?: number }) => new GlazeHand(w, h, o) });
