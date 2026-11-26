// letitedit hand: risograph, one drum per ink. M.look.risograph.start(w, h, {scale}) gives the marks; the AI writes the scene. See
// motion\runtime\looks\risograph.md.
//
// Adapted from anidoodle's canvas-core/riso.ts and lighthouseDraw.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77).
// Changed by letitedit, 4 Nov 2026: the kit is used as it stands; the feed curve and the drum's shadow are taken from lighthouseDraw; the
// lighthouse and the film timeline are left out; sheet(), pull() and solid() are ours, on .\worked.ts.
import { type Gfx, Gfx as GfxClass, halftone, type Layer, type P } from "./anidoodle/core";
import { across, cut, drum, INK, inside, LITHO, nearField, PAPER, plateMarks, REG, smooth, straight, twigs, wander } from "./anidoodle/riso";
import { register } from "./shared";
import { Work, WorkHand, type WorkOpts } from "./worked";

const feed = (u: number) => { const a = 0.08; if (u <= 0) return 0; if (u >= 1) return 1; const v = u < a ? (u * u) / (2 * a) : u > 1 - a ? 1 - ((1 - u) * (1 - u)) / (2 * a) : u - a / 2; return v / (1 - a / 2); };
const ANG: Record<string, number> = { yellow: 0, pink: 75, blue: 15, teal: 45, red: 30 };

class RisoHand extends WorkHand {
  INK = INK; PAPER = PAPER; REG = REG; ANG = ANG; PITCH = 7.4;
  cut = cut; cutSmooth = smooth; straight = straight; across = across; nearField = nearField; wander = wander; twigs = twigs; inside = inside;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, LITHO); }
  /** A bare sheet of off-white stock. paper: null leaves it bare, though inks only multiply properly over paper. */
  sheet(id: string, o: WorkOpts & { paper?: string | null } = {}): Work {
    const bare = o.paper === null;
    return this.work(id, { ...o, ground: bare ? null : (G) => { const c = G.cur, e = G.env; c.setTransform(e.scale, 0, 0, e.scale, 0, 0); c.fillStyle = o.paper ?? PAPER; c.fillRect(0, 0, e.W, e.H); }, finish: bare ? null : (G) => { G.paper("paper", 0.26); G.paper("coldpress", 0.22); } });
  }
  /** One pass through the press with one drum: plate(G) puts down this ink, in this ink's colour only. off = where this drum landed. The ink comes in at the nip, a front running down the sheet with the drum's shadow ahead of it. */
  pull(W: Work, plate: (G: Gfx) => void, o: { off?: P; per?: number } = {}) {
    const off = o.off ?? [0, 0]; let after: Layer | null = null;
    W.add(o.per ?? 30, (G: Gfx, q: number) => {
      const lay = (g: Gfx) => drum(g, off, () => plate(g));
      if (q >= 1) { lay(G); after = null; return; }
      const e = G.env, DW = Math.round(e.W * e.scale), DH = Math.round(e.H * e.scale), m = G.main;
      if (!after) { const A = e.canvas(DW, DH); A.ctx.setTransform(1, 0, 0, 1, 0, 0); A.ctx.drawImage(m.canvas as CanvasImageSource, 0, 0); lay(new GfxClass(A.ctx, e, 0, G.medium)); after = A; }
      const y = Math.round(feed(q) * DH), shade = 46 * e.scale;
      m.save(); m.setTransform(1, 0, 0, 1, 0, 0); if (y > 0) m.drawImage(after.canvas as CanvasImageSource, 0, 0, DW, y, 0, 0, DW, y);
      const gr = m.createLinearGradient(0, y, 0, y + shade); gr.addColorStop(0, "rgba(40,30,40,0.2)"); gr.addColorStop(0.25, "rgba(40,30,40,0.09)"); gr.addColorStop(1, "rgba(40,30,40,0)"); m.fillStyle = gr; m.fillRect(0, y, DW, shade); m.restore();
    });
    return W;
  }
  /** A halftone: dots on a grid at this ink's angle, sized by tone(x, y) 0..1. box = {x0, y0, x1, y1}; clip keeps it inside a shape. */
  screen(G: Gfx, box: { x0: number; y0: number; x1: number; y1: number }, ink: string, tone: (x: number, y: number) => number, o: { pitch?: number; ang?: number; clip?: P[] } = {}) {
    const name = Object.keys(INK).find((k) => (INK as Record<string, string>)[k] === ink) ?? "blue";
    // the kit's screen, with the dots filled in small batches: one huge path is very slow to fill with no graphics card
    const c = G.cur, dots = halftone(box, o.pitch ?? this.PITCH, o.ang ?? ANG[name] ?? 15, tone); G.touch(box.x0 - 10, box.y0 - 10, box.x1 + 10, box.y1 + 10); c.save(); if (o.clip) { G.path(c, o.clip); c.clip(); } c.fillStyle = ink;
    for (let i = 0; i < dots.length; i += 400) { c.beginPath(); for (let j = i; j < Math.min(dots.length, i + 400); j++) { const [x, y, r] = dots[j]; c.moveTo(x + r, y); c.arc(x, y, r, 0, Math.PI * 2); } c.fill(); }
    c.restore();
  }
  /** A solid area of ink with the cut wobble of a stencil. Overprints with what's already on the sheet. */
  solid(G: Gfx, pts: P[], ink: string, o: { raw?: boolean } = {}) { G.fill(o.raw ? pts : cut(pts), ink); }
  /** Crop marks and ink swatches, if the print should show its trade. */
  trim(G: Gfx, inks: string[]) { plateMarks(G, G.env.W, G.env.H, inks); }
}

register("risograph", { start: (w: number, h: number, o?: { scale?: number }) => new RisoHand(w, h, o) });
