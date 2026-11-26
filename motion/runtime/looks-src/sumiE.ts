// letitedit hand: sumi-e, one loaded brush on absorbent paper. M.look.sumiE.start(w, h, {scale}) gives the marks; the AI writes the scene.
// See motion\runtime\looks\sumiE.md.
//
// Adapted from anidoodle's canvas-core/sumiE.ts and sumiEKit.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77).
// Changed by letitedit, 4 Nov 2026: the kit's brush is used as it stands; the paper and the seal are taken from the bamboo picture, the
// paper's fibres now scale with the sheet's area and the seal takes a place and a size; the bamboo and sparrow and their film timeline
// are left out; sheet(), stroke() and wash() are ours, on .\worked.ts.
import { fractal, rng, type Gfx, type Medium, type P } from "./anidoodle/core";
import { clamp } from "./anidoodle/gallery";
import { brush, brushPath, DAN, JIAO, NONG, QING, strokeDraw, tone, ZHONG, type Brush } from "./anidoodle/sumiEKit";
import { register } from "./shared";
import { Work, WorkHand, type WorkOpts } from "./worked";

const SUMI: Medium = { nib: 1, taper: 1, pressure: 1, retrace: false, wobble: 0.6, rough: 0.5 };
const PAPER = "#f3ede0", CINNABAR = "#b8352b";

const ground = (G: Gfx, color: string) => {
  const c = G.cur, e = G.env; c.setTransform(e.scale, 0, 0, e.scale, 0, 0); c.fillStyle = color; c.fillRect(0, 0, e.W, e.H);
  const area = (e.W * e.H) / (1080 * 1080);
  G.group("plain", () => {
    const k = G.cur, r = rng(501); k.lineCap = "round";
    for (let i = 0; i < 340 * area; i++) {
      const x = r() * e.W, y = r() * e.H, a = (fractal(502, x, y, 0.004, 0.004, 2) - 0.5) * 5, L = 18 + r() * 70, bend = (r() - 0.5) * 0.5;
      k.strokeStyle = r() < 0.5 ? "#d9cfbc" : "#fbf7ee"; k.globalAlpha = 0.35 + r() * 0.35; k.lineWidth = 0.4 + r() * 0.6;
      k.beginPath(); k.moveTo(x, y); k.quadraticCurveTo(x + Math.cos(a + bend) * L * 0.5, y + Math.sin(a + bend) * L * 0.5, x + Math.cos(a) * L, y + Math.sin(a) * L); k.stroke();
    }
    for (let i = 0; i < 26 * area; i++) { const x = r() * e.W, y = r() * e.H, a = r() * 6.28, L = 1.5 + r() * 4; k.strokeStyle = "#8f806b"; k.globalAlpha = 0.25 + r() * 0.3; k.lineWidth = 0.6 + r() * 0.5; k.beginPath(); k.moveTo(x, y); k.lineTo(x + Math.cos(a) * L, y + Math.sin(a) * L); k.stroke(); }
    k.globalAlpha = 1; G.touch(0, 0, e.W, e.H);
  });
};

const GLYPHS: [number, number][][][] = [
  [[[0.12, 0.16], [0.88, 0.16]], [[0.5, 0.16], [0.5, 0.88]], [[0.16, 0.46], [0.84, 0.46]], [[0.2, 0.62], [0.2, 0.86], [0.8, 0.86], [0.8, 0.62]]],
  [[[0.16, 0.1], [0.16, 0.9]], [[0.16, 0.3], [0.86, 0.3], [0.86, 0.9]], [[0.44, 0.3], [0.44, 0.7], [0.68, 0.7]], [[0.16, 0.9], [0.62, 0.9]]],
  [[[0.1, 0.2], [0.9, 0.2]], [[0.3, 0.2], [0.3, 0.55], [0.7, 0.55], [0.7, 0.2]], [[0.5, 0.55], [0.5, 0.9]], [[0.14, 0.76], [0.86, 0.76]]],
  [[[0.18, 0.14], [0.82, 0.14], [0.82, 0.86], [0.18, 0.86], [0.18, 0.4], [0.6, 0.4], [0.6, 0.64], [0.4, 0.64]]],
];
const sealMark = (G: Gfx, x: number, y: number, s: number, press: number) => {
  if (press <= 0) return;
  const r = rng(900);
  G.group("plain", () => {
    const k = G.cur; G.touch(x - 4, y - 4, x + s + 4, y + s + 4);
    k.fillStyle = CINNABAR; k.globalAlpha = 0.92; k.beginPath();
    const edge: P[] = []; for (let i = 0; i < 40; i++) { const t = i / 10, side = Math.floor(t), f = t - side, j = (fractal(901, i, 0, 0.7, 0.7, 2) - 0.5) * 2.2; edge.push(side === 0 ? [x + s * f, y + j] : side === 1 ? [x + s + j, y + s * f] : side === 2 ? [x + s * (1 - f), y + s + j] : [x + j, y + s * (1 - f)]); }
    edge.forEach(([a, b], i) => (i ? k.lineTo(a, b) : k.moveTo(a, b))); k.closePath(); k.fill();
    k.globalCompositeOperation = "destination-out"; k.globalAlpha = 1; k.lineCap = "square"; k.lineJoin = "miter";
    const cell = (s - 12) / 2, order = [[1, 0], [1, 1], [0, 0], [0, 1]];
    GLYPHS.forEach((gl, gi) => { const [cx, cy] = order[gi], ox = x + 6 + cx * cell, oy = y + 6 + cy * cell; gl.forEach((line) => { k.lineWidth = cell * 0.13 * (0.9 + r() * 0.25); k.beginPath(); line.forEach(([u, v], i) => { const px = ox + cell * (0.08 + u * 0.84) + (r() - 0.5) * 0.8, py = oy + cell * (0.08 + v * 0.84) + (r() - 0.5) * 0.8; i ? k.lineTo(px, py) : k.moveTo(px, py); }); k.stroke(); }); });
    k.lineWidth = 1.6; k.strokeRect(x + 3.2, y + 3.2, s - 6.4, s - 6.4);
    k.lineWidth = 1; for (let i = 0; i < 3; i++) { const a = r() * 4, px = a < 1 ? x + a * s : a < 2 ? x + s : a < 3 ? x + (a - 2) * s : x, py = a < 1 ? y : a < 2 ? y + (a - 1) * s : a < 3 ? y + s : y + (a - 3) * s; k.beginPath(); k.arc(px, py, 1.6 + r() * 2.2, 0, 6.28); k.fill(); }
    for (let i = 0; i < 90; i++) { const px = x + r() * s, py = y + r() * s, lighter = fractal(902, px, py, 0.06, 0.06, 2); if (lighter < 0.52) continue; k.globalAlpha = (lighter - 0.5) * 1.4; k.beginPath(); k.arc(px, py, 0.5 + r() * 1.3, 0, 6.28); k.fill(); }
    k.globalCompositeOperation = "source-over"; k.globalAlpha = 1;
  }, { blend: "multiply", alpha: clamp(0.35 + 0.65 * press), textures: ["risoSpeck"] });
};

class SumiHand extends WorkHand {
  CINNABAR = CINNABAR; PAPER = PAPER; JIAO = JIAO; NONG = NONG; ZHONG = ZHONG; DAN = DAN; QING = QING; tone = tone; brush = brush;
  constructor(w: number, h: number, o?: { scale?: number }) { super(w, h, o, SUMI); }
  /** A sheet of unsized xuan paper. paper: null leaves the sheet out, for ink floating on its own layer. */
  sheet(id: string, o: WorkOpts & { paper?: string | null } = {}): Work {
    const bare = o.paper === null;
    return this.work(id, { ...o, ground: bare ? null : (G) => ground(G, o.paper ?? PAPER), finish: bare ? null : (G) => { G.paper("paper", 0.1); G.paper("coldpress", 0.045); } });
  }
  /** One stroke of the brush, timed by its length at a hand's pace unless per is given. b = {ctrl, w, press, ink, load, dry, edge, split, bleed, wet, streak, slow, hairs, seed}. */
  stroke(W: Work, b: Brush, o: { per?: number; clip?: P[] } = {}) {
    const d = strokeDraw(b), per = o.per ?? 2 + brushPath(b).len / 120;
    W.add(per, (G, q) => { if (o.clip) this.within(G, o.clip, null, () => d(G, q)); else d(G, q); });
    return W;
  }
  /** A wide pale wash laid into the damp sheet: its edge goes soft all round. */
  wash(W: Work, ctrl: P[], w: number, o: { ink?: number; wet?: number; seed?: number; per?: number } = {}) {
    return this.stroke(W, { ctrl, w, press: [[0, 0.6], [0.2, 1], [0.8, 1], [1, 0.5]], ink: o.ink ?? QING, wet: o.wet ?? 1, load: 1.2, dry: 0.05, edge: 0.3, bleed: 0.9, seed: o.seed ?? 5 }, { per: o.per });
  }
  /** The cinnabar seal pressed at the end, its characters cut in so they print as paper. The glyphs are an invented mark, not writing. */
  seal(W: Work, x: number, y: number, s = 70, o: { per?: number } = {}) { W.add(o.per ?? 2, (G, q) => sealMark(G, x, y, s, q)); return W; }
}

register("sumiE", { start: (w: number, h: number, o?: { scale?: number }) => new SumiHand(w, h, o) });
