// letitedit hand: cut-paper collage. M.look.cutPaper.start(w, h, {scale}) gives torn and scissor-cut coloured papers, each lowered onto the stack with a shadow
// that pulls in; the picture is written fresh by the AI. There is no drawn line. See motion\runtime\looks\cutPaper.md.
//
// Adapted from anidoodle's canvas-core/fox.ts and foxDraw.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Changed by letitedit, 4 Nov 2026:
// the torn edge, the white core and how a piece is lowered are taken from those files; tear, scissor and fibres come from the scrapbook kit that shares them; its
// fox and meadow are left out; pieces are baked once through .\shared.ts; band, star, disc, tiers and word are ours. That style had no kit of its own.
import { oval, rng, type Ctx, type P } from "./anidoodle/core";
import { blob, bounds, mix, smooth } from "./anidoodle/gallery";
import { advance, fibres, glyph, measure, path, rect, scissor, tear, type Face } from "./anidoodle/scrapbookKit";
import { Hand, register, REST, type Piece, type PieceOpts, type Pose } from "./shared";

const CORE = "#fbf5e6", SHADOW = "#3c2814", WORD: Face = { weight: 0.24, cap: "butt", join: "miter" };
export const PAPERS = { board: "#e9dfc9", night: "#23485a", dusk: "#3d6b74", rose: "#b98276", peach: "#eab58e", moon: "#f3e3bd", gold: "#f2cf6e", fox: "#c9602a", cream: "#f0e2c6", ink: "#231c22", pine: "#2f5146", grass: "#6d8a3f", sky: "#7fb3d1", red: "#c23a30", blue: "#2c5d8a" };
const seedOf = (id: string) => { let s = 7; for (let i = 0; i < id.length; i++) s = (s * 31 + id.charCodeAt(i)) >>> 0; return s % 997; };
type Box = { x0: number; y0: number; x1: number; y1: number };
type Opts = Partial<PieceOpts> & { seed?: number; fibre?: number; lift?: number; blotch?: number; decorate?: (c: Ctx, s: P[]) => void };

class CutHand extends Hand {
  c = PAPERS; rng = rng; smooth = smooth; oval = oval; blob = blob; mix = mix; bounds = bounds; rect = rect; path = path; tear = tear; scissor = scissor;
  /** A TORN piece: the outline bitten by noise, the sheet's white fibrous core showing past its dyed face. amp = how rough. */
  torn(id: string, shape: P[], color: string, o: Opts & { amp?: number } = {}): Piece {
    const seed = o.seed ?? seedOf(id), amp = o.amp ?? 3, dyed = tear(shape, amp, seed), white = tear(shape, amp * 0.8, seed + 1, amp * 0.7);
    return this.piece(id, { cut: white, edge: undefined, depth: (o.lift ?? 1) * 6, stage: o.stage, pivot: o.pivot, shadow: SHADOW, face: (c) => { c.fillStyle = CORE; path(c, white); c.fill(); c.fillStyle = color; path(c, dyed); c.fill(); fibres(c, dyed, color, seed + 2, o.fibre ?? 1, o.blotch ?? 0.22); o.decorate?.(c, dyed); } });
  }
  /** A SCISSOR piece: crisp, a very slight hand in the edge. */
  cut(id: string, shape: P[], color: string, o: Opts = {}): Piece {
    const seed = o.seed ?? seedOf(id), s = scissor(shape, seed, 0.7);
    return this.piece(id, { cut: s, depth: (o.lift ?? 1) * 6, stage: o.stage, pivot: o.pivot, shadow: SHADOW, face: (c) => { c.fillStyle = color; path(c, s); c.fill(); fibres(c, s, color, seed + 2, o.fibre ?? 1, o.blotch ?? 0.22); o.decorate?.(c, s); } });
  }
  /** A torn band from edge to edge: sky above, ground below. y = its top line, wander = how much the top moves, runs to the bottom of the frame. */
  band(id: string, y: number, color: string, o: Opts & { amp?: number; wander?: number; bottom?: number } = {}) { const r = rng(o.seed ?? seedOf(id)), W = this.w + 60, n = 5, w = o.wander ?? 22, top: P[] = Array.from({ length: n + 1 }, (_, i) => [-30 + (W * i) / n, y + (r() - 0.5) * w * 2]); return this.torn(id, smooth([...top, [W - 30, o.bottom ?? this.h + 40], [-30, o.bottom ?? this.h + 40]], true, 6), color, { amp: 3, fibre: 0.5, ...o }); }
  /** A round scissor piece. */
  disc(id: string, x: number, y: number, r: number, color: string, o: Opts = {}) { return this.cut(id, Array.from({ length: 40 }, (_, i) => [x + Math.cos((i / 40) * 6.2832) * r, y + Math.sin((i / 40) * 6.2832) * r] as P), color, { lift: 0.6, ...o }); }
  /** A star punched from a sheet. */
  star(id: string, x: number, y: number, r: number, color: string = PAPERS.gold, o: Opts = {}) { return this.cut(id, Array.from({ length: 10 }, (_, k) => { const a = -Math.PI / 2 + (k / 10) * 6.2832, q = k % 2 ? r * 0.42 : r; return [x + Math.cos(a) * q, y + Math.sin(a) * q] as P; }), color, { lift: 0.3, ...o }); }
  /** The shape of a tree of paper tiers: a list of shapes, widest at the bottom. Lay each as its own piece. */
  tiers(x: number, base: number, w: number, h: number, n = 3): P[][] { return Array.from({ length: n }, (_, i) => { const k = 1 - i / n, y = base - (h * i) / n * 0.8, W = (w * k) / 2; return [[x - W, y], [x + W, y], [x + W * 0.3, y - (h / n) * 1.4], [x - W * 0.3, y - (h / n) * 1.4]] as P[]; }); }
  /** Words cut from one sheet and laid on a strip of torn paper. (x, y) = centre, cap = letter height. */
  word(id: string, text: string, o: { x: number; y: number; cap?: number; rot?: number; paper?: string; ink?: string; amp?: number; seed?: number; face?: Face; lift?: number }): Piece {
    const cap = o.cap ?? 44, f = o.face ?? WORD, W = measure(text, cap, f) + cap * 1.5, H = cap * 2.1, rot = o.rot ?? 0, ca = Math.cos(rot), sa = Math.sin(rot), T = ([x, y]: P): P => [o.x + x * ca - y * sa, o.y + x * sa + y * ca], seed = o.seed ?? seedOf(id), shape = rect(W, H).map(T), col = o.paper ?? PAPERS.cream, dyed = tear(shape, o.amp ?? 2.4, seed), white = tear(shape, (o.amp ?? 2.4) * 0.8, seed + 1, (o.amp ?? 2.4) * 0.7);
    return this.piece(id, { cut: white, depth: (o.lift ?? 1) * 6, pivot: [o.x, o.y], shadow: SHADOW, face: (c) => { c.fillStyle = CORE; path(c, white); c.fill(); c.fillStyle = col; path(c, dyed); c.fill(); fibres(c, dyed, col, seed + 2, 0.8, 0.15); c.save(); c.translate(o.x, o.y); c.rotate(rot); let x = -measure(text, cap, f) / 2; [...text].forEach((ch) => { glyph(c, ch, x, -cap / 2, cap, f, o.ink ?? PAPERS.ink); x += advance(ch, f) * (cap / 6); }); c.restore(); c.globalAlpha = 1; } });
  }
  /** The bare backing board: a plate that fills the frame. */
  board(id = "board", color: string = PAPERS.board, box?: Box) { const b = box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, s: P[] = [[b.x0, b.y0], [b.x1, b.y0], [b.x1, b.y1], [b.x0, b.y1]]; return this.plate(id, (c) => { c.fillStyle = color; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); fibres(c, s, color, 201, 0.5, 0.18); }, b); }
  /** Lowering a piece: t0 = when the hand brings it, dur = until it is pressed down, from = [dx, dy] where it starts. Held above the sheet it throws a wide far shadow, which pulls in tight as it lands. Its .shown is false before t0. */
  lay(t: number, t0: number, dur: number, from: P = [0, -30]): Pose & { shown: boolean } { if (t < t0) return { ...REST, shown: false }; if (t >= t0 + dur) return { ...REST, shown: true }; const u = (t - t0) / dur, e = 1 - (1 - u) ** 3, h = (1 - e) * (1 - e); return { dx: from[0] * (1 - e), dy: from[1] * (1 - e), rot: 0, lift: h * 2.3, shown: true }; }
  /** A slow push on a piece: a number around 0, for x, y or r. */
  sway(t: number, amp: number, period: number, phase = 0) { return amp * Math.sin((t / period) * 6.2832 + phase); }
  /** The sheet's tooth over the finished frame, in screen space: last thing in the frame. */
  finish(g: Ctx, o: { paper?: number; vignette?: string | null } = {}) { this.sheet(g, { paper: o.paper ?? 0.1, vignette: o.vignette === undefined ? null : o.vignette, tile: "paper" }); }
}

register("cutPaper", { start: (w: number, h: number, o?: { scale?: number }) => new CutHand(w, h, o), papers: PAPERS });
