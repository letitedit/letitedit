// letitedit hand: single-line engraving. M.look.singleLine.start(w, h, {scale}) cuts one unbroken spiral whose width follows a tone you write; the AI
// writes the tone. See motion\runtime\looks\singleLine.md.
//
// Adapted from anidoodle's canvas-core/mellan.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77): the walk along the spiral, the width from
// the tone, time measured in ink and the plate mark are taken from it. Changed by letitedit, 4 Nov 2026: the tone, centre, plate and pitch are arguments;
// the ribbon is cut into pieces on a Work (.\worked.ts) so a frame costs little; its moon is left out.
import { type Ctx, type P } from "./anidoodle/core";
import { clamp } from "./anidoodle/gallery";
import { MarkHand, type Box, type ToneFn } from "./marks";
import { register } from "./shared";
import type { Work } from "./worked";

const INK = "#17130f", PAPER = "#f2ead8";

class SingleLineHand extends MarkHand {
  palette = { ink: INK, paper: PAPER };
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, { nib: 1, taper: 0, pressure: 0, retrace: false, wobble: 0, rough: 0 }); }
  /** The damp paper with the copper's bevel pressed into it, a plate. plate: the box the line prints inside. */
  paper(id = "paper", o: { box?: Box; plate?: Box | null; color?: string } = {}) {
    const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, pl = o.plate === undefined ? this.plateBox() : o.plate;
    return this.plate(id, (c) => { c.fillStyle = o.color ?? PAPER; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); if (pl) { const d = 6; c.strokeStyle = "rgba(60,45,30,0.28)"; c.lineWidth = 2; c.strokeRect(pl.x0 - d, pl.y0 - d, pl.x1 - pl.x0 + d * 2, pl.y1 - pl.y0 + d * 2); c.strokeStyle = "rgba(255,252,240,0.7)"; c.lineWidth = 1.2; c.strokeRect(pl.x0 - d - 1.5, pl.y0 - d - 1.5, pl.x1 - pl.x0 + d * 2, pl.y1 - pl.y0 + d * 2); } }, b);
  }
  /** The usual plate: the frame less a margin. */
  plateBox(m = Math.round(Math.min(this.w, this.h) * 0.043)): Box { return { x0: m, y0: m, x1: this.w - m, y1: this.h - m }; }
  /** The one line, from (cx, cy) outward until it has left the plate. tone(x, y): 0 hairline, 1 as wide as the gap between turns. It races through the lights and slows where it cuts deep: time is ink. pitch: px between turns. */
  spiral(W: Work, tone: ToneFn, o: { cx?: number; cy?: number; pitch?: number; plate?: Box; color?: string; pieces?: number } = {}) {
    const pl = o.plate ?? this.plateBox(), cx = o.cx ?? (pl.x0 + pl.x1) / 2, cy = o.cy ?? (pl.y0 + pl.y1) / 2, PITCH = o.pitch ?? Math.max(3.5, Math.min(this.w, this.h) * 0.0057), color = o.color ?? INK, a = PITCH / (Math.PI * 2);
    const rMax = Math.max(...([[pl.x0, pl.y0], [pl.x1, pl.y0], [pl.x0, pl.y1], [pl.x1, pl.y1]] as P[]).map(([x, y]) => Math.hypot(x - cx, y - cy))) + PITCH, thMax = rMax / a;
    const Lx: number[] = [], Ly: number[] = [], Rx: number[] = [], Ry: number[] = [], ink: number[] = []; let laid = 0, th = 0.6;
    while (th < thMax) {
      const step = 1.4 / Math.max(a * th, 1.4), r = a * th, x = cx + Math.cos(th) * r, y = cy + Math.sin(th) * r, on = x > pl.x0 && x < pl.x1 && y > pl.y0 && y < pl.y1, dark = on ? clamp(tone(x, y)) : 0, grow = Math.min(1, r / 40), w = (PITCH * (0.05 + 0.86 * dark) * grow) / 2;
      const tx = -Math.sin(th) * r + Math.cos(th) * a, ty = Math.cos(th) * r + Math.sin(th) * a, tl = Math.hypot(tx, ty), nx = ty / tl, ny = -tx / tl;
      Lx.push(x + nx * w); Ly.push(y + ny * w); Rx.push(x - nx * w); Ry.push(y - ny * w); if (on) laid += 2 * w * 1.4; ink.push(laid); th += step;
    }
    const n = ink.length, pieces = o.pieces ?? 90, ends: number[] = [0]; for (let i = 1; i <= pieces; i++) { const want = (laid * i) / pieces; let lo = ends[i - 1], hi = n - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (ink[m] < want) lo = m + 1; else hi = m; } ends.push(i === pieces ? n - 1 : lo); }
    for (let i = 0; i < pieces; i++) { const s = Math.max(0, ends[i] - 1), e = ends[i + 1]; if (e <= s) continue;
      W.add(Math.max(1e-3, ink[e] - ink[s]), (G, q) => {
        const c = G.cur, want = ink[s] + (ink[e] - ink[s]) * q; let m = e; if (q < 1) { let lo = s, hi = e; while (lo < hi) { const k = (lo + hi) >> 1; if (ink[k] < want) lo = k + 1; else hi = k; } m = lo; } if (m <= s) return;
        c.save(); c.beginPath(); c.rect(pl.x0, pl.y0, pl.x1 - pl.x0, pl.y1 - pl.y0); c.clip(); c.fillStyle = color; c.beginPath(); c.moveTo(Lx[s], Ly[s]); for (let k = s + 1; k <= m; k++) c.lineTo(Lx[k], Ly[k]); for (let k = m; k >= s; k--) c.lineTo(Rx[k], Ry[k]); c.closePath(); c.fill(); c.restore();
      }); }
    return W;
  }
  /** Tones joined: the darkest of several at each point. */
  darkest(...tones: ToneFn[]): ToneFn { return (x, y) => tones.reduce((m, t) => Math.max(m, t(x, y)), 0); }
  /** Nothing over the print; here so a scene ends the same way in every hand. */
  finish(g: Ctx, o: { paper?: number } = {}) { this.grain(g, [["paper", o.paper ?? 0.05]]); }
}

register("singleLine", { start: (w: number, h: number, o?: { scale?: number }) => new SingleLineHand(w, h, o) });
