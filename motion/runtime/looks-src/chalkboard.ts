// letitedit hand: chalkboard. M.look.chalkboard.start(w, h, {scale}) gives the slate with its ghosts of old lessons and wooden frame, chalk lines with their dust,
// scumble with the side of the chalk and lettering; the AI writes the scene. See motion\runtime\looks\chalkboard.md.
//
// Adapted from anidoodle's canvas-core/moonPhases.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). That file has no kit: its chalk, line, scumble, board and
// frame are taken out here. Changed by letitedit, 4 Nov 2026: the board and frame take any size; dust is laid from the same marks in one go; the lesson and moons are left out;
// marks go on a Work (.\worked.ts, .\marks.ts).
import { rng, type Ctx, type Gfx, type Medium, type P } from "./anidoodle/core";
import { letter, strokeCount } from "./anidoodle/drafting";
import { blob, bounds, fillShape, hatchRuns, inside } from "./anidoodle/gallery";
import { MarkHand, cost, plen, type Box } from "./marks";
import { register } from "./shared";
import type { Work } from "./worked";

const CHALK_M: Medium = { nib: 2.1, taper: 0.55, pressure: 0.95, retrace: true, wobble: 1.4, rough: 1.2 };
const CHALK = "#f4f0e6", YEL = "#f6e6a4", BLUE = "#a9d3e8", PINK = "#f3c1cf";
type CMark = { t: number; d: (G: Gfx, p: number, dust: boolean) => void };

// chalk: one pass of dust (wide, soft, faint), then the stroke itself broken by the board's tooth
const addChalk = (W: Work, marks: CMark[], dustAlpha = 0.2, chunk = 8) => {
  for (let i = 0; i < marks.length; i += chunk) { const part = marks.slice(i, i + chunk), total = part.reduce((a, m) => a + m.t, 0);
    const paint = (G: Gfx, q: number, dust: boolean) => { let b = q >= 1 ? Infinity : q * total; for (const m of part) { if (b <= 0) break; m.d(G, b >= m.t ? 1 : b / m.t, dust); b -= m.t; } };
    W.add(total, (G, q) => { G.group("plain", () => paint(G, q, true), { blur: 3.2, alpha: dustAlpha }); G.group("plain", () => paint(G, q, false), { textures: ["pencilTooth", "risoSpeck"] }); }); }
  return W;
};
const scumbleMark = (region: P[], color: string, o: { angle: number; gap: number; w: number; alpha: number; seed: number; keep?: (x: number, y: number) => boolean }): CMark => {
  const b = bounds(region), runs = hatchRuns(b, o.angle, o.gap, (x, y) => inside(region, x, y) && (o.keep ? o.keep(x, y) : true), 4, o.seed).map((run) => run.filter((_, k, a) => k % 2 === 0 || k === a.length - 1));
  return { t: 8 + runs.length * 1.5, d: (G, p, dust) => {
    if (p <= 0) return; const r = rng(o.seed), c = G.cur; G.touch(b.x0 - 12, b.y0 - 12, b.x1 + 12, b.y1 + 12);
    c.save(); c.lineCap = "round"; c.lineJoin = "round"; c.strokeStyle = color; c.lineWidth = dust ? o.w * 2.2 : o.w; const upto = p >= 1 ? Infinity : p * runs.length;
    runs.forEach((pts, i) => { const a = o.alpha * (0.86 + r() * 0.2), shown = i > upto ? 0 : i + 1 > upto ? Math.max(2, Math.ceil(pts.length * (upto - i))) : pts.length; c.beginPath(); pts.forEach(([x, y], k) => { const jx = (r() - 0.5) * 1.5, jy = (r() - 0.5) * 1.5; if (k < shown) { if (k) c.lineTo(x + jx, y + jy); else c.moveTo(x, y); } }); if (shown) { c.globalAlpha = a; c.stroke(); } });
    c.restore();
  } };
};

class ChalkHand extends MarkHand {
  palette = { chalk: CHALK, yellow: YEL, blue: BLUE, pink: PINK, slate: "#27352f" };
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, CHALK_M); }
  /** The slate: a lit middle, tooth, wide swipes of old erasing and old words not quite gone. frame: the wooden frame and ledge with a chalk stub and felt eraser. ghosts: words of a lesson wiped off. inner() says where the slate is. */
  board(id = "board", o: { frame?: boolean; ghosts?: string[]; box?: Box; seed?: number } = {}) {
    const frame = o.frame ?? true, seed = o.seed ?? 5, ghosts = o.ghosts ?? [];
    return this.ground(id, (G, W, H) => {
      const c = G.main, k = Math.min(W, H) / 1080; c.save(); c.setTransform(this.scale, 0, 0, this.scale, 0, 0);
      const gr = c.createRadialGradient(W / 2, H * 0.44, 60 * k, W / 2, H * 0.44, Math.max(W, H) * 0.67); gr.addColorStop(0, "#35493f"); gr.addColorStop(0.62, "#27352f"); gr.addColorStop(1, "#1b2622"); c.fillStyle = gr; c.fillRect(0, 0, W, H); c.restore();
      G.paper("coldpress", 0.3);
      G.group("plain", () => { const r = rng(seed); for (let i = 0; i < 9 * Math.max(1, (W * H) / (1080 * 1080)); i++) { const cx = W * 0.1 + r() * W * 0.8, cy = H * 0.1 + r() * H * 0.7, rr = (120 + r() * 160) * k, a0 = r() * 6, pts: P[] = []; for (let q = 0; q <= 12; q++) { const a = a0 + (q / 12) * 2.2; pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr * 0.55]); } G.pen(pts, { w: (40 + r() * 30) * k, color: CHALK, seed: 6 + i, wobble: 3, boil: 0, opacity: 0.05, retrace: false, taper: 0.4 }); } }, { blur: 9 });
      if (ghosts.length) G.group("plain", () => { const r = rng(seed + 1); ghosts.forEach((t, i) => letter(G, t, W * (0.1 + r() * 0.3), H * (0.15 + 0.7 * r()), { cap: 28 * k, color: CHALK, seed: 40 + i, opacity: 0.12 })); }, { blur: 2.4 });
      if (!frame) return;
      const B = 34 * k, R = W - B, LE = H - 122 * k, wood = "#7b5231", dark = "#553620";
      G.group("plain", () => { const r = rng(70); fillShape(G, [[0, 0], [W, 0], [W, B], [0, B]], wood); fillShape(G, [[0, 0], [B, 0], [B, H], [0, H]], wood); fillShape(G, [[R, 0], [W, 0], [W, H], [R, H]], wood); fillShape(G, [[0, LE], [W, LE], [W, H], [0, H]], "#6a4526"); fillShape(G, [[B - 8 * k, LE - 4 * k], [R + 8 * k, LE - 4 * k], [R + 20 * k, LE + 24 * k], [B - 20 * k, LE + 24 * k]], "#8c6139");
        for (let i = 0; i < 26; i++) { const y = r() * H, x = r() < 0.5 ? r() * B : R + r() * B; G.pen([[x, y], [x + (r() - 0.5) * 3, y + (40 + r() * 60) * k]], { w: 0.9, color: dark, seed: 71 + i, wobble: 0.6, boil: 0, opacity: 0.45, retrace: false }); }
        fillShape(G, [[B, B], [R, B], [R - 6 * k, B + 8 * k], [B + 8 * k, B + 8 * k], [B + 8 * k, LE - 4 * k], [B, LE - 4 * k]], "#0e1512", 0.55);
        for (let i = 0; i < 140; i++) { const x = B + r() * (R - B), y = LE + (2 + r() * 20) * k; fillShape(G, blob(x, y, (0.8 + r() * 1.8) * k, (0.6 + r()) * k, 110 + i, 0.3, 6), CHALK, 0.25 + r() * 0.45); }
        const sx = W * 0.64, st: P[] = [[sx, LE + 2 * k], [sx + 100 * k, LE - 6 * k], [sx + 104 * k, LE + 10 * k], [sx + 4 * k, LE + 18 * k]]; fillShape(G, [[sx + 6 * k, LE + 20 * k], [sx + 106 * k, LE + 12 * k], [sx + 110 * k, LE + 20 * k], [sx + 10 * k, LE + 26 * k]], "#3a2616", 0.6); fillShape(G, st, CHALK);
        const ex = W * 0.23, er: P[] = [[ex, LE - 16 * k], [ex + 140 * k, LE - 22 * k], [ex + 146 * k, LE + 14 * k], [ex + 6 * k, LE + 20 * k]]; fillShape(G, er, "#a0714a"); fillShape(G, [[ex + 2 * k, LE + 4 * k], [ex + 144 * k, LE - 2 * k], [ex + 146 * k, LE + 14 * k], [ex + 6 * k, LE + 20 * k]], "#8e8a86");
      });
    }, o.box);
  }
  /** Where the slate is inside the frame, for your layout. */
  inner(): Box { const k = Math.min(this.w, this.h) / 1080; return { x0: 42 * k, y0: 42 * k, x1: this.w - 42 * k, y1: this.h - 126 * k }; }
  /** A chalk line with its dust either side, growing along the stroke. */
  chalk(W: Work, pts: P[], o: { w?: number; color?: string; seed?: number; op?: number; wob?: number; closed?: boolean } = {}) { const { w = 2.6, color = CHALK, seed = 1, op = 0.92, wob = 1, closed = false } = o; return addChalk(W, [{ t: cost(plen(pts)), d: (G, p, dust) => G.pen(pts, { w: dust ? w * 2.6 : w, color, seed, wobble: wob, boil: 0, opacity: op, retrace: !dust, taper: 1, closed, progress: p }) }]); }
  /** The side of the chalk dragged back and forth in a shape, drag by drag. keep(x, y) thins it. Dark places are just less chalk. */
  scumble(W: Work, shape: P[], o: { color?: string; angle?: number; gap?: number; w?: number; alpha?: number; seed?: number; keep?: (x: number, y: number) => boolean } = {}) { const { color = CHALK, angle = -0.5, gap = 6, w = 7, alpha = 0.55, seed = 1 } = o; return addChalk(W, [scumbleMark(shape, color, { angle, gap, w, alpha, seed, keep: o.keep })], 0.2, 1); }
  /** A finger's smudge: a soft cloud of chalk round something. */
  smudge(W: Work, shape: P[], o: { color?: string; alpha?: number; blur?: number } = {}) { W.add(8, (G, p) => { if (p > 0) G.group("plain", () => fillShape(G, shape, o.color ?? CHALK, (o.alpha ?? 0.12) * Math.min(1, p * 1.5)), { blur: o.blur ?? 14 }); }); return W; }
  /** Tapped-in dots: stars, points on a chart. list: [x, y, r]. */
  dots(W: Work, list: [number, number, number][], o: { color?: string; seed?: number } = {}) { return addChalk(W, list.map(([x, y, r], i) => ({ t: 3, d: (G: Gfx, p: number, dust: boolean) => { if (p > 0) fillShape(G, blob(x, y, r * (dust ? 2 : 1), r * (dust ? 2 : 1), (o.seed ?? 3) + i, 0.3, 8), o.color ?? CHALK, 0.95); } })), 0.2, 16); }
  /** A teacher's capitals, stroke by stroke, with their dust. */
  write(W: Work, text: string, x: number, y: number, o: { cap?: number; color?: string; seed?: number; align?: "left" | "center" | "right"; w?: number; opacity?: number } = {}) { const cap = o.cap ?? 34, w = o.w ?? Math.max(1.6, cap * 0.09), base = { cap, color: o.color ?? CHALK, seed: o.seed ?? 1, align: o.align, opacity: o.opacity ?? 0.92, slant: 0.1 }; return addChalk(W, [{ t: strokeCount(text) * 6, d: (G, p, dust) => letter(G, text, x, y, { ...base, w: dust ? w * 2.4 : w, progress: p }) }], 0.2, 1); }
  /** Over the frame: nothing, the slate carries its own tooth. Kept so a scene ends the same way in every kit. */
  finish(_g: Ctx) { /* nothing */ }
}

register("chalkboard", { start: (w: number, h: number, o?: { scale?: number }) => new ChalkHand(w, h, o) });
