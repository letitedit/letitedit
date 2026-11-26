// letitedit hand: toy-theatre paper collage. M.look.paperCraft.start(w, h, {scale}) gives the marks and the stage parts; the scene
// is written fresh by the AI. See motion\runtime\looks\paperCraft.md.
//
// Adapted from anidoodle's canvas-core/paperCraft.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77).
// Changed by letitedit, 4 Nov 2026: the paint, print, pose and stage functions are taken from that file; its seaside picture and
// film runner are left out; pieces are baked once and placed through the context's transform (.\shared.ts); the stage parts take
// their sizes as arguments instead of a fixed 1080 square; sign(), row() and piece stage walls are ours.
import { fractal, oval, rng, type Ctx, type P } from "./anidoodle/core";
import { bounds, mix, smooth } from "./anidoodle/gallery";
import { advance, clamp01, fibres, glyph, measure, path, rect, scissor, tear, type Face } from "./anidoodle/scrapbookKit";
import { Hand, REST, register, type Piece, type PieceOpts, type Pose } from "./shared";

const WHITE = "#fbf9f2";
type GouacheOpts = { dir?: number; len?: number; w?: number; vary?: number; dens?: number };
type Box = { x0: number; y0: number; x1: number; y1: number };

// ---------------------------------------------------------------- paint and print (all clipped to the piece)
const gouache = (c: Ctx, shape: P[], color: string, seed: number, o: GouacheOpts = {}) => {
  const { dir = 0, len = 44, w = 13, vary = 0.1, dens = 1 } = o, r = rng(seed), b = bounds(shape), area = (b.x1 - b.x0) * (b.y1 - b.y0);
  c.fillStyle = color; path(c, shape); c.fill();
  c.save(); path(c, shape); c.clip(); c.lineCap = "round";
  const n = Math.max(6, Math.round((area / (len * w)) * 1.6 * dens));
  for (let i = 0; i < n; i++) { const x = b.x0 + r() * (b.x1 - b.x0), y = b.y0 + r() * (b.y1 - b.y0), a = dir + (r() - 0.5) * 0.35, l = len * (0.6 + r() * 0.7), k = r(); c.strokeStyle = k < 0.5 ? mix(color, "#ffffff", vary * (0.5 + r())) : mix(color, "#1d2430", vary * (0.4 + r())); c.globalAlpha = 0.28 + r() * 0.25; c.lineWidth = w * (0.6 + r() * 0.6); c.beginPath(); c.moveTo(x - Math.cos(a) * l / 2, y - Math.sin(a) * l / 2); c.quadraticCurveTo(x + (r() - 0.5) * 6, y + (r() - 0.5) * 6, x + Math.cos(a) * l / 2, y + Math.sin(a) * l / 2); c.stroke(); }
  c.restore(); c.globalAlpha = 1;
};
const shadeSide = (c: Ctx, shape: P[], color: string, seed: number, side: P, depth: number, dir = Math.PI / 2) => {
  const b = bounds(shape), r = rng(seed); c.save(); path(c, shape); c.clip(); c.lineCap = "round";
  for (let i = 0; i < 16; i++) { const u = r(), x = side[0] > 0 ? b.x1 - r() * depth : side[0] < 0 ? b.x0 + r() * depth : b.x0 + u * (b.x1 - b.x0), y = side[1] > 0 ? b.y1 - r() * depth : side[1] < 0 ? b.y0 + r() * depth : b.y0 + u * (b.y1 - b.y0), l = 16 + r() * 26; c.strokeStyle = color; c.globalAlpha = 0.3 + r() * 0.25; c.lineWidth = 5 + r() * 7; c.beginPath(); c.moveTo(x - Math.cos(dir) * l / 2, y - Math.sin(dir) * l / 2); c.lineTo(x + Math.cos(dir) * l / 2, y + Math.sin(dir) * l / 2); c.stroke(); }
  c.restore(); c.globalAlpha = 1;
};
const print = (c: Ctx, shape: P[], fn: (b: Box) => void) => { c.save(); path(c, shape); c.clip(); fn(bounds(shape)); c.restore(); c.globalAlpha = 1; };
const wavePrint = (c: Ctx, shape: P[], col: string, gap = 22, sw = 2) => print(c, shape, (b) => { c.strokeStyle = col; c.lineWidth = sw; c.globalAlpha = 0.55; for (let y = b.y0 + 8, row = 0; y < b.y1 + 10; y += gap, row++) { c.beginPath(); for (let x = b.x0 - 30 + (row % 2) * 15; x < b.x1 + 30; x += 30) { c.moveTo(x, y); c.quadraticCurveTo(x + 7.5, y - 7, x + 15, y); } c.stroke(); } });
const dotPrint = (c: Ctx, shape: P[], col: string, gap = 14, rad = 2.2) => print(c, shape, (b) => { c.fillStyle = col; c.globalAlpha = 0.8; for (let y = b.y0, row = 0; y < b.y1 + gap; y += gap * 0.87, row++) for (let x = b.x0 + (row % 2) * gap * 0.5; x < b.x1 + gap; x += gap) { c.beginPath(); c.arc(x, y, rad, 0, 6.28); c.fill(); } });
const diamondPrint = (c: Ctx, shape: P[], col: string, gap = 26) => print(c, shape, (b) => { c.fillStyle = col; c.globalAlpha = 0.5; for (let y = b.y0, row = 0; y < b.y1 + gap; y += gap / 2, row++) for (let x = b.x0 + (row % 2) * gap / 2; x < b.x1 + gap; x += gap) { c.beginPath(); c.moveTo(x, y - 4); c.lineTo(x + 3, y); c.lineTo(x, y + 4); c.lineTo(x - 3, y); c.closePath(); c.fill(); } c.globalAlpha = 0.18; c.strokeStyle = col; c.lineWidth = 0.8; for (let d = b.x0 - (b.y1 - b.y0); d < b.x1; d += gap) { c.beginPath(); c.moveTo(d, b.y0); c.lineTo(d + (b.y1 - b.y0), b.y1); c.stroke(); c.beginPath(); c.moveTo(d + (b.y1 - b.y0), b.y0); c.lineTo(d, b.y1); c.stroke(); } });
const stonePrint = (c: Ctx, shape: P[], base: string, seed: number) => print(c, shape, (b) => { const r = rng(seed); for (let y = b.y0, row = 0; y < b.y1; y += 17, row++) for (let x = b.x0 - (row % 2) * 16; x < b.x1; ) { const w = 26 + r() * 16; c.fillStyle = mix(base, r() < 0.5 ? "#ffffff" : "#3b3226", 0.06 + r() * 0.14); c.globalAlpha = 1; c.beginPath(); c.roundRect(x + 1.5, y + 1.5, w - 3, 14, 4); c.fill(); x += w; } });
const newsPrint = (c: Ctx, shape: P[], seed: number) => print(c, shape, (b) => { const r = rng(seed); c.fillStyle = "#4a4640"; c.globalAlpha = 0.5; for (let col = b.x0 + 4; col < b.x1; col += 36) for (let y = b.y0 + 4; y < b.y1; y += 4.2) { if (r() < 0.06) { y += 6; continue; } const l = 20 + r() * 12; c.fillRect(col, y, l, 1.3); } c.globalAlpha = 0.7; c.fillRect(b.x0 + 16, b.y0 + 30, 60, 5); });
const woodPrint = (c: Ctx, shape: P[], col: string, seed: number) => print(c, shape, (b) => { const r = rng(seed); c.strokeStyle = col; c.lineWidth = 1; c.globalAlpha = 0.35; for (let y = b.y0; y < b.y1; y += 3 + r() * 4) { c.beginPath(); c.moveTo(b.x0, y); for (let x = b.x0; x <= b.x1; x += 40) c.lineTo(x, y + Math.sin(x * 0.013 + y) * 1.6); c.stroke(); } c.globalAlpha = 0.5; c.strokeStyle = mix(col, "#000000", 0.2); for (let x = b.x0 + 60 + r() * 60; x < b.x1; x += 90 + r() * 90) { c.beginPath(); c.moveTo(x, b.y0); c.lineTo(x, b.y1); c.stroke(); } });

// ---------------------------------------------------------------- how a hand moves a piece, on twos
const seedOf = (id: string) => { let s = 7; for (let i = 0; i < id.length; i++) s = (s * 31 + id.charCodeAt(i)) >>> 0; return s; };
/** t0 = when the hand picks it up, dur = until it is still, from = where it starts relative to its place. */
const land = (t: number, t0: number, dur: number, from: P, id: string, fps = 30): Pose & { shown: boolean } => {
  if (t < t0) return { ...REST, shown: false };
  if (t >= t0 + dur) return { ...REST, shown: true };
  const f = Math.round(t * fps + 1e-6), f2 = f - (f % 2), u = clamp01((f2 / fps - t0) / dur), seed = seedOf(id), r = rng(seed + f2);
  if (u < 0.62) { const v = u / 0.62, e = 1 - (1 - v) ** 2; return { dx: from[0] * (1 - e) + (r() - 0.5) * 1.4, dy: from[1] * (1 - e) + (r() - 0.5) * 1.4, rot: (seed % 2 ? 1 : -1) * 0.04 * (1 - e), lift: 1 - 0.6 * e, shown: true }; }
  const v = (u - 0.62) / 0.38, damp = Math.exp(-4 * v) * (1 - v);
  return { dx: 0, dy: -2.2 * Math.abs(Math.sin(v * 9)) * damp, rot: (seed % 2 ? 1 : -1) * 0.035 * Math.sin(v * 13 + 0.6) * damp, lift: 0.4 * (1 - v), shown: true };
};
/** A slow push and pull by hand: a row rocking in its groove, a cloud on its thread. Held on twos. Returns one number around 0. */
const rock = (t: number, amp: number, period: number, phase = 0, fps = 30) => { const f = Math.round(t * fps + 1e-6), f2 = f - (f % 2); return amp * Math.sin(((f2 / fps) / period) * Math.PI * 2 + phase); };

// ---------------------------------------------------------------- geometry
const scallop = (x0: number, x1: number, y: number, amp: number, per: number, ph: number, bottom: number, seed: number): P[] => { const r = rng(seed), top: P[] = []; for (let x = x0; x <= x1 + 1; x += per / 8) top.push([x, y - amp * Math.abs(Math.sin(((x - x0) / per) * Math.PI + ph)) + (r() - 0.5) * 1.2]); return [...top, [x1, bottom], [x0, bottom]]; };
const cloudShape = (cx: number, cy: number, w: number, h: number, seed: number): P[] => { const r = rng(seed), pts: P[] = [[cx + w / 2, cy]], n = 4 + Math.floor(r() * 2); for (let i = 0; i <= n; i++) { const x = cx + w / 2 - (w * i) / n, hh = h * (0.45 + 0.55 * Math.sin((Math.PI * (i + 0.5)) / (n + 1))) * (0.8 + r() * 0.3); for (let k = 0; k <= 6; k++) { const a = (k / 6) * Math.PI, rr = w / n / 2; pts.push([x - rr + Math.cos(a) * rr, cy - hh * 0.5 - Math.sin(a) * hh * 0.55]); } } pts.push([cx - w / 2, cy]); return pts; };
const rays = (cx: number, cy: number, R: number, n = 24): P[] => Array.from({ length: n }, (_, i) => { const a = (i / n) * Math.PI * 2 - Math.PI / 2, rr = i % 2 ? R * 0.66 : R - (i % 4 === 0 ? 0 : R * 0.1); return [cx + Math.cos(a) * rr, cy + Math.sin(a) * rr] as P; });

const SIGN: Face = { weight: 0.15, serif: 0.5, cap: "round", join: "round" };

class PaperHand extends Hand {
  // the marks and the shapes, as they are
  gouache = gouache; shadeSide = shadeSide; print = print; wavePrint = wavePrint; dotPrint = dotPrint; diamondPrint = diamondPrint; stonePrint = stonePrint; newsPrint = newsPrint; woodPrint = woodPrint;
  fibres = fibres; tear = tear; scissor = scissor; smooth = smooth; path = path; rect = rect; bounds = bounds; mix = mix; rng = rng; oval = oval; fractal = fractal; scallop = scallop; cloudShape = cloudShape; rays = rays;
  land = land; rock = rock; glyph = glyph; measure = measure; advance = advance;
  WHITE = WHITE;
  palette = { kraft: "#b8905f", teal: "#2f6f73", gold: "#e1b54a", red: "#b8302c", redDark: "#7c1c1a", deepSea: "#2c5d8a", sea: "#3d7db0", shallows: "#4ba2a3", sand: "#e1c996", grass: "#7fa25a", grassDark: "#5c8546", skyTop: "#5f9dc4", skyLow: "#cfe3e6", sun: "#f7c343", sunRay: "#f29a2e", wood: "#b07a45", stone: "#b5a791", ink: "#2c2c30" };

  /** Sugar paper, printed or painted: a coloured sheet with fibres and an uneven dye. decorate(c, shape) adds its print. */
  sheetPiece(id: string, shape: P[], color: string, o: Partial<PieceOpts> & { seed?: number; decorate?: (c: Ctx, s: P[]) => void } = {}): Piece {
    const seed = o.seed ?? seedOf(id) % 997;
    return this.piece(id, { cut: shape, edge: o.edge ?? mix(color, "#0b1a2a", 0.45), depth: o.depth ?? 8, stage: o.stage, pivot: o.pivot, face: (c) => { c.fillStyle = color; path(c, shape); c.fill(); fibres(c, shape, color, seed + 1, 0.7, 0.18); o.decorate?.(c, shape); } });
  }
  /** A gouache cut-out: painted strokes on white card, a white scissor margin round it, a card edge. */
  cutout(id: string, shape: P[], color: string, o: Partial<PieceOpts> & GouacheOpts & { seed?: number; shade?: string; light?: P; decorate?: (c: Ctx, s: P[]) => void } = {}): Piece {
    const seed = o.seed ?? seedOf(id) % 997, b = bounds(shape);
    return this.piece(id, { cut: shape, border: o.border ?? 5, edge: o.edge ?? "#bdb29a", depth: o.depth ?? 6, stage: o.stage, pivot: o.pivot, face: (c) => { gouache(c, shape, color, seed, o); shadeSide(c, shape, o.shade ?? mix(color, "#2b2a40", 0.35), seed + 1, o.light ? [-o.light[0], -o.light[1]] : [1, 1], Math.min(b.x1 - b.x0, b.y1 - b.y0) * 0.22, o.dir ?? Math.PI / 2); o.decorate?.(c, shape); } });
  }
  /** A row with a scalloped top from x0 to x1 (sea, hills, a hedge): y = top line, amp and per = the bumps, down to bottom. */
  row(id: string, o: { y: number; amp?: number; per?: number; color: string; x0?: number; x1?: number; bottom?: number; depth?: number; seed?: number; stage?: Box; decorate?: (c: Ctx, s: P[]) => void }): Piece {
    const seed = o.seed ?? seedOf(id) % 997, s = scissor(scallop(o.x0 ?? -40, o.x1 ?? this.w + 40, o.y, o.amp ?? 10, o.per ?? 80, seed * 0.7, o.bottom ?? this.h + 8, seed), seed, 0.5);
    return this.sheetPiece(id, s, o.color, { depth: o.depth ?? 8, seed, stage: o.stage, decorate: o.decorate });
  }
  /** Foam dabs along the top of a row, as gouache on the row's shape. */
  foam(c: Ctx, shape: P[], seed = 58, color = WHITE) { const r = rng(seed); c.save(); path(c, shape); c.clip(); c.lineCap = "round"; const top = shape.slice(0, -2); for (let i = 0; i < top.length; i++) { const [x, y] = top[i]; if (r() > 0.42) continue; const k = 1 + Math.floor(r() * 3); for (let j = 0; j < k; j++) { const ox = (r() - 0.5) * 14, oy = 3 + r() * 9, l = 4 + r() * 10; c.strokeStyle = color; c.globalAlpha = 0.55 + r() * 0.35; c.lineWidth = 3 + r() * 4; c.beginPath(); c.moveTo(x + ox, y + oy); c.lineTo(x + ox + l, y + oy + (r() - 0.5) * 3); c.stroke(); } } c.restore(); c.globalAlpha = 1; }
  /** A cut cloud: a flat underside, rounded bumps on top, painted in soft strokes. */
  cloud(id: string, cx: number, cy: number, w: number, h: number, o: { seed?: number; color?: string; shade?: string; depth?: number; stage?: Box } = {}): Piece {
    const seed = o.seed ?? seedOf(id) % 997, s = scissor(cloudShape(cx, cy, w, h, seed), seed, 0.7), col = o.color ?? "#f6f4ec";
    return this.piece(id, { cut: s, edge: "#b9c4c8", depth: o.depth ?? 7, stage: o.stage, pivot: [cx, cy - h], face: (c) => { gouache(c, s, col, seed, { len: 30, w: 10, vary: 0.05 }); shadeSide(c, s, o.shade ?? "#b9c7d3", seed + 1, [0, 1], h * 0.28, 0.1); } });
  }
  /** A flown drop: the sky painted in long soft strokes between two colours. */
  drop(id: string, o: { box: Box; top?: string; low?: string; lowAt?: number; seed?: number; depth?: number; stage?: Box; strokes?: number }): Piece {
    const { box: b, top = this.palette.skyTop, low = this.palette.skyLow, seed = 5, depth = 3, strokes = 0 } = o, s = rect(b.x1 - b.x0, b.y1 - b.y0, (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2), lowAt = o.lowAt ?? b.y0 + (b.y1 - b.y0) * 0.6;
    return this.piece(id, { cut: s, edge: "#3f6f86", depth, stage: o.stage, face: (c) => { const gr = c.createLinearGradient(0, b.y0, 0, lowAt); gr.addColorStop(0, top); gr.addColorStop(1, low); c.fillStyle = gr; path(c, s); c.fill(); const r = rng(seed); c.save(); path(c, s); c.clip(); c.lineCap = "round"; const n = strokes || Math.round(((b.x1 - b.x0) * (lowAt - b.y0)) / 2000); for (let i = 0; i < n; i++) { const y = b.y0 + r() * (lowAt - b.y0), x = b.x0 + r() * (b.x1 - b.x0), u = clamp01((y - b.y0) / (lowAt - b.y0)); c.strokeStyle = mix(mix(top, low, u), r() < 0.5 ? "#ffffff" : "#2d5f86", 0.12 + r() * 0.1); c.globalAlpha = 0.35; c.lineWidth = 8 + r() * 12; const L = 110 + r() * 190; c.beginPath(); c.moveTo(x - L, y + (r() - 0.5) * 6); c.quadraticCurveTo(x, y + (r() - 0.5) * 14, x + L, y + (r() - 0.5) * 6); c.stroke(); } c.restore(); c.globalAlpha = 1; } });
  }
  /** A sun on a stick from above (the stick's top at topY), with rays and a painted highlight. Two pieces, stick first. */
  sun(id: string, cx: number, cy: number, R: number, o: { topY?: number; disc?: string; ray?: string; stage?: Box } = {}): { stick: Piece; sun: Piece } {
    const disc = o.disc ?? this.palette.sun, ray = o.ray ?? this.palette.sunRay, top = o.topY ?? -20, stickCut: P[] = [[cx - 4, top], [cx + 4, top], [cx + 4, cy - R * 0.5], [cx - 4, cy - R * 0.5]], ring = rays(cx, cy, R);
    const stick = this.piece(id + ":stick", { cut: stickCut, edge: "#8a6a40", depth: 6, stage: o.stage, pivot: [cx, top], face: (c) => { c.fillStyle = "#d8b37a"; path(c, stickCut); c.fill(); c.fillStyle = "#b88c52"; c.fillRect(cx + 1, top, 3, cy - R * 0.5 - top); } });
    const sun = this.piece(id, { cut: ring, border: 7, edge: "#c9b99a", depth: 6, stage: o.stage, pivot: [cx, cy], face: (c) => { gouache(c, ring, ray, 11, { dir: 0.3, len: 30, w: 10, vary: 0.14 }); const dsc = oval(cx, cy, R * 0.6, R * 0.6, 40); gouache(c, dsc, disc, 12, { dir: -0.6, len: 26, w: 9, vary: 0.12 }); gouache(c, oval(cx - R * 0.18, cy - R * 0.18, R * 0.21, R * 0.16, 20), mix(disc, "#ffffff", 0.5), 13, { dir: -0.6, len: 14, w: 6, vary: 0.05 }); shadeSide(c, dsc, mix(ray, "#b0501a", 0.3), 14, [1, 1], R * 0.21, -0.6); } });
    return { stick, sun };
  }
  /** One side of a pair of curtains, on the inside of the opening `open`; side -1 is left, 1 is right. */
  curtain(id: string, side: -1 | 1, open: Box, o: { color?: string; width?: number; tie?: string; stage?: Box; depth?: number } = {}): Piece {
    const col = o.color ?? this.palette.red, W = o.width ?? 104, x0 = side < 0 ? open.x0 - 6 : open.x1 + 6, k = side < 0 ? 1 : -1, H = open.y1 - open.y0, Y = (f: number) => open.y0 + f * H;
    const s = smooth([[x0, open.y0 - 6], [x0 + k * W, open.y0 - 6], [x0 + k * W * 0.81, Y(0.276)], [x0 + k * W * 0.44, Y(0.552)], [x0 + k * W * 0.21, Y(0.629)], [x0 + k * W * 0.38, Y(0.767)], [x0 + k * W * 0.6, open.y1 + 4], [x0, open.y1 + 4]], false, 6);
    const edgeX = side < 0 ? open.x0 : open.x1, tieY = Y(0.621), gold = o.tie ?? this.palette.gold;
    return this.piece(id, { cut: s, edge: "#6b1a18", depth: o.depth ?? 10, stage: o.stage, pivot: [edgeX, Y(0.3)], face: (c) => { gouache(c, s, col, side < 0 ? 151 : 152, { dir: Math.PI / 2, len: 70, w: 10, vary: 0.18, dens: 1.4 }); c.save(); path(c, s); c.clip(); const r = rng(153 + side); for (let i = 0; i < 5; i++) { const u = W * 0.12 + (i * W) / 6; c.strokeStyle = i % 2 ? mix(col, "#000000", 0.35) : mix(col, "#ffffff", 0.2); c.globalAlpha = 0.45; c.lineWidth = 6 + r() * 4; c.beginPath(); c.moveTo(edgeX - side * u, open.y0); c.quadraticCurveTo(edgeX - side * (u - 18 - i * 6), Y(0.46), edgeX - side * (W * 0.29 + i * 4), Y(0.629)); c.lineTo(edgeX - side * (W * 0.35 + i * 8), open.y1); c.stroke(); } c.restore(); c.globalAlpha = 1; const tx = edgeX - side * W * 0.35; c.strokeStyle = gold; c.lineWidth = 6; c.lineCap = "round"; c.beginPath(); c.moveTo(tx - W * 0.25, tieY - 8); c.quadraticCurveTo(tx, tieY + 10, tx + W * 0.27, tieY - 6); c.stroke(); c.fillStyle = gold; c.beginPath(); c.arc(tx + side * 6, tieY + 14, 6, 0, 6.28); c.fill(); } });
  }
  /** The scalloped pelmet across the top of the opening. */
  valance(id: string, open: Box, o: { color?: string; trim?: string; n?: number; drop?: number; stage?: Box } = {}): Piece {
    const col = o.color ?? this.palette.red, trim = o.trim ?? this.palette.gold, n = o.n ?? 9, drop = o.drop ?? 44, w = (open.x1 - open.x0 + 20) / n, pts: P[] = [[open.x0 - 10, open.y0 - 30], [open.x1 + 10, open.y0 - 30]];
    for (let i = n; i >= 1; i--) { const x1 = open.x0 - 10 + i * w; for (let k = 0; k <= 8; k++) { const a = (k / 8) * Math.PI; pts.push([x1 - w / 2 + (Math.cos(a) * w) / 2, open.y0 + drop + Math.sin(a) * 18]); } }
    return this.piece(id, { cut: pts, edge: "#6b1a18", depth: 10, stage: o.stage, pivot: [(open.x0 + open.x1) / 2, open.y0], face: (c) => { gouache(c, pts, col, 161, { dir: 0, len: 60, w: 10, vary: 0.16, dens: 1.2 }); c.save(); path(c, pts); c.clip(); c.strokeStyle = trim; c.lineWidth = 5; path(c, pts.map(([x, y]) => [x, y - 5] as P), true); c.stroke(); c.restore(); c.fillStyle = trim; for (let i = 0; i < n - 1; i++) { const x = open.x0 - 10 + (i + 1) * w; c.beginPath(); c.arc(x, open.y0 + drop + 4, 6, 0, 6.28); c.fill(); } } });
  }
  /** The theatre's front: patterned card round the opening, gold trim, a crest, a stage-front apron if there's room. outer defaults to the frame less a margin; crest(c, x, y) paints your own crest on a cream oval (none = a plain oval). */
  proscenium(id: string, open: Box, o: { outer?: Box; color?: string; pattern?: string; trim?: string; apron?: string; crest?: (c: Ctx, x: number, y: number) => void; stage?: Box } = {}): Piece {
    const O = o.outer ?? { x0: open.x0 - 40, y0: Math.max(10, open.y0 - 90), x1: open.x1 + 40, y1: Math.min(this.h - 10, open.y1 + 90) }, col = o.color ?? this.palette.teal, gold = o.trim ?? "#d9ae4a", apronCol = o.apron ?? this.palette.red, cx = (O.x0 + O.x1) / 2, cw = O.x1 - O.x0;
    const outer: P[] = [[O.x0, O.y1], [O.x0, O.y0 + 80], ...smooth([[cx - cw * 0.2, O.y0 + 80], [cx - cw * 0.1, O.y0 + 66], [cx - cw * 0.045, O.y0 + 20], [cx, O.y0], [cx + cw * 0.045, O.y0 + 20], [cx + cw * 0.1, O.y0 + 66], [cx + cw * 0.2, O.y0 + 80]], false, 6), [O.x1, O.y0 + 80], [O.x1, O.y1]];
    const inner: P[] = [[open.x0, open.y1], [open.x0, open.y0 + 30], ...smooth([[open.x0, open.y0 + 30], [cx, open.y0 - 6], [open.x1, open.y0 + 30]], false, 10).slice(1, -1), [open.x1, open.y0 + 30], [open.x1, open.y1]];
    const ring = (c: Ctx) => { c.beginPath(); [outer, inner].forEach((s) => { s.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); }); };
    return this.piece(id, { hole: true, cut: [outer, inner], edge: "#173b3e", depth: 5, stage: o.stage, pivot: [cx, O.y1], face: (c) => {
      c.save(); path(c, inner); c.clip(); c.fillStyle = "rgba(20,14,8,0.28)"; c.beginPath(); c.rect(open.x0 - 40, open.y0 - 60, open.x1 - open.x0 + 80, open.y1 - open.y0 + 100); path(c, inner.map(([x, y]) => [x + 16, y + 22] as P)); c.fill("evenodd"); c.restore();
      c.fillStyle = col; ring(c); c.fill("evenodd");
      c.save(); ring(c); c.clip("evenodd"); diamondPrint(c, outer, o.pattern ?? "#e6c56a", 26); c.restore();
      c.save(); ring(c); c.clip("evenodd"); fibres(c, outer, col, 171, 0.5, 0.15); c.restore();
      const off = (d: number) => inner.map(([x, y]) => [x + (x < cx ? -d : d), y + (y > (open.y0 + open.y1) / 2 ? d : -d)] as P);
      c.strokeStyle = gold; c.lineWidth = 14; c.lineJoin = "round"; path(c, off(7), false); c.stroke();
      c.strokeStyle = "#f2d78a"; c.lineWidth = 3; path(c, off(10), false); c.stroke();
      const r = rng(172); c.fillStyle = "#9c6f22"; for (let y = open.y0 + 40; y < open.y1; y += 22) [open.x0 - 7, open.x1 + 7].forEach((x) => { c.beginPath(); c.arc(x + (r() - 0.5), y, 2.4, 0, 6.28); c.fill(); });
      if (O.y1 - open.y1 > 36) { const a: P[] = [[open.x0 - 30, open.y1 + 18], [open.x1 + 30, open.y1 + 18], [open.x1 + 30, O.y1 - 10], [open.x0 - 30, O.y1 - 10]]; c.fillStyle = apronCol; path(c, a); c.fill(); fibres(c, a, apronCol, 173, 0.5, 0.2); print(c, a, (b) => { c.fillStyle = "#f0dcb0"; c.globalAlpha = 0.5; for (let x = b.x0 + 8; x < b.x1; x += 16) c.fillRect(x, b.y0 + 8, 3, b.y1 - b.y0 - 16); }); c.fillStyle = this.palette.gold; c.fillRect(open.x0 - 30, open.y1 + 18, open.x1 - open.x0 + 60, 5); }
      if (O.y0 + 42 < open.y0) { const y = O.y0 + 42, cart = oval(cx, y, 62, 38, 30); c.fillStyle = WHITE; path(c, cart); c.lineWidth = 10; c.strokeStyle = WHITE; c.stroke(); c.fill(); gouache(c, cart, "#f1e2c2", 174, { len: 16, w: 6, vary: 0.06 }); o.crest?.(c, cx, y); }
    } });
  }
  /** The bare kraft table the theatre stands on: a plate that fills the frame (or box). */
  table(id = "table", box?: Box, color?: string) {
    const col = color ?? this.palette.kraft, b = box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, s: P[] = [[b.x0, b.y0], [b.x1, b.y0], [b.x1, b.y1], [b.x0, b.y1]];
    return this.plate(id, (c) => { c.fillStyle = col; c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0); fibres(c, s, col, 201, 1.2, 0.3); }, b);
  }
  /** Words on a slip of card: stroked letters (capitals, figures, a few signs), never a font. Centred at (x, y), cap = letter height. */
  sign(id: string, text: string, o: { x: number; y: number; cap?: number; rot?: number; card?: string; ink?: string; border?: number; depth?: number; seed?: number; face?: Face; stage?: Box }): Piece {
    const cap = o.cap ?? 40, f = o.face ?? SIGN, w = measure(text, cap, f) + cap * 1.3, h = cap * 2, seed = o.seed ?? seedOf(id) % 997, rot = o.rot ?? 0, ca = Math.cos(rot), sa = Math.sin(rot), T = ([x, y]: P): P => [o.x + x * ca - y * sa, o.y + x * sa + y * ca], s = scissor(rect(w, h), seed, 0.8).map(T), card = o.card ?? "#f1e7d0";
    return this.piece(id, { cut: s, border: o.border ?? 0, edge: mix(card, "#3b2a14", 0.4), depth: o.depth ?? 6, stage: o.stage, pivot: [o.x, o.y], face: (c) => { c.fillStyle = card; path(c, s); c.fill(); fibres(c, s, card, seed, 0.6, 0.15); c.save(); c.translate(o.x, o.y); c.rotate(rot); let x = -measure(text, cap, f) / 2; [...text].forEach((ch) => { glyph(c, ch, x, -cap / 2, cap, f, o.ink ?? "#221d1a"); x += advance(ch, f) * (cap / 6); }); c.restore(); c.globalAlpha = 1; } });
  }
  /** The sheet's tooth over the finished frame, in screen space: last thing in the frame. */
  finish(g: Ctx, o: { paper?: number; vignette?: string | null } = {}) { this.sheet(g, { paper: o.paper ?? 0.12, vignette: o.vignette === undefined ? "rgba(60,36,14,0.32)" : o.vignette }); }
}

register("paperCraft", { start: (w: number, h: number, o?: { scale?: number }) => new PaperHand(w, h, o) });
