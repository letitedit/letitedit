// letitedit hand: archival scrapbook. M.look.scrapbook.start(w, h, {scale}) gives the page, torn cards, tape, typewriter, cut letters,
// red pen, stamp and copperplate lines; the AI writes the scene. See motion\runtime\looks\scrapbook.md.
//
// Adapted from anidoodle's canvas-core/scrapbook.ts and scrapbookKit.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77).
// Changed by letitedit, 4 Nov 2026: the page, card, tape, typed strip, ransom tile, peg and stamp are taken from scrapbook.ts with
// their sizes as arguments; its honeybee pictures, charts and film runner are left out; everything is baked once and placed through
// the context's transform (.\shared.ts), so a camera can move over a page larger than the frame; lay(), print() and engraved() are ours.
import { fractal, oval, rng, type Ctx, type P } from "./anidoodle/core";
import { bounds, hatchRuns, inside, mix, smooth } from "./anidoodle/gallery";
import { GLYPHS, advance, burin, clamp01, cutLine, easeOut, fibres, glyph, measure, path, rect, scissor, tear, typed, TYPEWRITER, type Face } from "./anidoodle/scrapbookKit";
import { Hand, REST, register, type Piece, type Pose } from "./shared";

const INK = "#2a2019", NAVY = "#22335a", RED = "#b8322a", REDPEN = "#c23a2a", TEAL = "#4f8f8a", PINK = "#d9a5a0", MUSTARD = "#d6a13c", PARCH = "#e8d6b2";
type Box = { x0: number; y0: number; x1: number; y1: number };

const FACES: Face[] = [{ weight: 0.2 }, { weight: 0.15, serif: 0.9 }, { weight: 0.12, outline: "" }, { weight: 0.14, slant: 0.22 }, { weight: 0.075, serif: 0.7, wide: 0.78 }, { weight: 0.17, wide: 1.25 }, { weight: 0.16, cap: "round", join: "round" }, { weight: 0.11, serif: 1.0, slant: 0.12 }];
const PAIRS: [string, string][] = [[NAVY, "#f3ead6"], [TEAL, "#1c1a18"], ["#f1e9d8", "#1c1a18"], [PINK, NAVY], [RED, "#f6ecd9"], [MUSTARD, "#1c1a18"], ["#d8d2c4", "#1c1a18"], ["#1d1b19", "#efe6d0"], ["#e9c9b4", RED]];
const STRIKE: Face = { weight: 0.1, mono: 4.2, track: 0.9 };

/** A piece being laid down by hand: held high with a far shadow, then pressed. u 0..1, or use t, t0, dur. No jiggle: paper settles. */
const lay = (t: number, t0: number, dur: number, from: P = [0, -60]): Pose & { shown: boolean; alpha: number } => { if (t < t0) return { ...REST, shown: false, alpha: 0 }; const e = easeOut((t - t0) / dur); return { dx: from[0] * (1 - e), dy: from[1] * (1 - e), rot: 0.03 * (1 - e), lift: (1 - e) * (1 - e), shown: true, alpha: clamp01((t - t0) / 0.14) }; };

class ScrapHand extends Hand {
  fibres = fibres; tear = tear; scissor = scissor; smooth = smooth; path = path; rect = rect; bounds = bounds; mix = mix; rng = rng; oval = oval; fractal = fractal; inside = inside;
  typedLine = typed; glyph = glyph; measure = measure; advance = advance; burin = burin; cutLine = cutLine; hatchRuns = hatchRuns; lay = lay; TYPEWRITER = TYPEWRITER; clamp01 = clamp01;
  palette = { parchment: PARCH, ink: INK, teal: TEAL, pink: PINK, stamp: RED, redPen: REDPEN, navy: NAVY, mustard: MUSTARD, card: "#f2eadb", cardCool: "#c9d9d5", cardWarm: "#efe5cf", tape: "#efe0a8", twine: "#7a6446" };

  /** The sheet everything lies on: parchment with broad age clouds, handled edges, a fold, a tide mark and drifts of foxing. box may be far larger than the frame, for a camera to travel over. */
  page(id = "page", o: { box?: Box; color?: string; seed?: number; fold?: number | null } = {}) {
    const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, W = b.x1 - b.x0, H = b.y1 - b.y0, col = o.color ?? PARCH, seed = o.seed ?? 301, foldY = o.fold === null ? null : o.fold ?? b.y0 + H * 0.56;
    return this.plate(id, (c) => {
      const r = rng(seed); c.fillStyle = col; c.fillRect(b.x0, b.y0, W, H);
      const clouds = Math.max(14, Math.round((W * H) / 150000));
      for (let i = 0; i < clouds; i++) { const x = b.x0 + r() * W, y = b.y0 + r() * H, R = 120 + r() * 260, gr = c.createRadialGradient(x, y, 0, x, y, R), tone = r() < 0.55 ? "#f4e7c9" : "#caa874"; gr.addColorStop(0, tone); gr.addColorStop(1, tone + "00"); c.globalAlpha = 0.28; c.fillStyle = gr; c.fillRect(x - R, y - R, R * 2, R * 2); }
      const edge = (x0: number, y0: number, x1: number, y1: number) => { const gr = c.createLinearGradient(x0, y0, x1, y1); gr.addColorStop(0, "rgba(120,78,30,0.34)"); gr.addColorStop(1, "rgba(120,78,30,0)"); c.globalAlpha = 1; c.fillStyle = gr; c.fillRect(b.x0, b.y0, W, H); };
      edge(b.x0, b.y0, b.x0 + 60, b.y0); edge(b.x1, b.y0, b.x1 - 70, b.y0); edge(b.x0, b.y0, b.x0, b.y0 + 55); edge(b.x0, b.y1, b.x0, b.y1 - 80);
      const tx = b.x0 + W * 0.57, ty = b.y0 + H * 0.82; c.globalAlpha = 0.16; c.strokeStyle = "#9a6a30"; c.lineWidth = 2.2; path(c, smooth(Array.from({ length: 16 }, (_, i) => { const a = (i / 16) * 6.28, k = 1 + (fractal(9, Math.cos(a) * 2, Math.sin(a) * 2, 0.8, 0.8, 2) - 0.5) * 0.25; return [tx + Math.cos(a) * W * 0.17 * k, ty + Math.sin(a) * H * 0.1 * k] as P; }), true, 6)); c.stroke();
      if (foldY !== null) { c.globalAlpha = 0.22; c.strokeStyle = "#fff6df"; c.lineWidth = 3; c.beginPath(); c.moveTo(b.x0, foldY); c.bezierCurveTo(b.x0 + W * 0.28, foldY - 4, b.x0 + W * 0.65, foldY + 5, b.x1, foldY - 1); c.stroke(); c.globalAlpha = 0.16; c.strokeStyle = "#7a5424"; c.lineWidth = 1.2; c.beginPath(); c.moveTo(b.x0, foldY + 2.5); c.bezierCurveTo(b.x0 + W * 0.28, foldY - 1.5, b.x0 + W * 0.65, foldY + 7.5, b.x1, foldY + 1.5); c.stroke(); }
      const drift = (cx: number, cy: number, sx: number, sy: number, n: number, big: number) => { for (let i = 0; i < n; i++) { const x = cx + (r() + r() - 1) * sx, y = cy + (r() + r() - 1) * sy, s = (0.6 + r() * r() * big) * 2.2; c.globalAlpha = 0.18 + r() * 0.35; c.fillStyle = r() < 0.7 ? "#9a6a30" : "#7a4a1e"; c.beginPath(); c.arc(x, y, s, 0, 6.28); c.fill(); } };
      const spots = Math.max(1, Math.round((W * H) / 1100000));
      for (let i = 0; i < spots; i++) { drift(b.x0 + r() * W, b.y0 + r() * H, 40 + r() * 80, 40 + r() * 160, 18 + Math.round(r() * 20), 3); }
      drift(b.x1 - 35, b.y0 + H * 0.3, 30, 220, 38, 3); drift(b.x0 + 60, b.y1 - 70, 70, 60, 34, 4);
      c.globalAlpha = 1;
    }, b);
  }
  /** A card torn from other stock, centred at (x, y): deckle edge, fibres, darkened rim, and your own content in face(c), drawn in the card's local space (0, 0 is its centre). Lay it with S.lay. */
  card(id: string, o: { x: number; y: number; w: number; h: number; rot?: number; color?: string; seed?: number; torn?: number; depth?: number; face?: (c: Ctx) => void }): Piece {
    const { x, y, w, h, rot = 0, color = this.palette.card, torn = 2.4, depth = 5 } = o, seed = o.seed ?? (w * 7 + h * 3) % 997, cr = Math.cos(rot), sr = Math.sin(rot), s = tear(rect(w, h), torn, seed).map(([px, py]) => [x + px * cr - py * sr, y + px * sr + py * cr] as P);
    return this.piece(id, { cut: s, depth, shadow: "#3b2a14", pivot: [x, y], face: (c) => { c.fillStyle = color; path(c, s); c.fill(); fibres(c, s, color, seed + 5, 0.8, 0.28); c.strokeStyle = mix(color, "#7a5a30", 0.35); c.globalAlpha = 0.35; c.lineWidth = 1.2; path(c, s); c.stroke(); c.globalAlpha = 1; if (o.face) { c.save(); c.translate(x, y); c.rotate(rot); o.face(c); c.restore(); c.globalAlpha = 1; } } });
  }
  /** A photo print on the card: a white border, a little darkening at its edges, tape on top if you add it. image: a loaded Image or canvas (a scene loads its own, see the guide). fit: cover. */
  print(c: Ctx, image: CanvasImageSource & { width: number; height: number }, x: number, y: number, w: number, h: number, o: { border?: number; tone?: string; toneAlpha?: number } = {}) {
    const b = o.border ?? Math.round(Math.min(w, h) * 0.05); c.save(); c.fillStyle = "#f7f3ea"; c.fillRect(x - w / 2, y - h / 2, w, h);
    const iw = w - b * 2, ih = h - b * 2, k = Math.max(iw / image.width, ih / image.height), sw = iw / k, sh = ih / k;
    c.drawImage(image, (image.width - sw) / 2, (image.height - sh) / 2, sw, sh, x - iw / 2, y - ih / 2, iw, ih);
    c.globalCompositeOperation = "multiply"; c.globalAlpha = o.toneAlpha ?? 0.18; c.fillStyle = o.tone ?? "#b08a54"; c.fillRect(x - iw / 2, y - ih / 2, iw, ih);
    c.restore();
  }
  /** Cellulose tape: yellowed, see-through, torn at each end, centred at `at`. draw(g, {reveal}) with reveal 0..1 lays it from one end. */
  tape(id: string, at: P, ang: number, len: number, seed = 1) {
    const h = 30, r = rng(seed), co = Math.cos(ang), si = Math.sin(ang), T = ([x, y]: P): P => [at[0] + x * co - y * si, at[1] + x * si + y * co], top: P[] = [], bot: P[] = [];
    for (let k = 0; k <= 5; k++) top.push([-len / 2 + (r() - 0.5) * 3, -h / 2 + (k * h) / 5]);
    for (let k = 5; k >= 0; k--) bot.push([len / 2 + (k % 2 ? 3 : -2), -h / 2 + (k * h) / 5]);
    const sh = [...top, ...bot].map(T), piece = this.piece(id, { cut: sh, depth: 1.5, shadow: "#3b2a14", pivot: at, face: (c) => { c.globalAlpha = 0.5; c.fillStyle = "#efe0a8"; path(c, sh); c.fill(); c.globalAlpha = 0.28; c.fillStyle = "#fffbe8"; path(c, ([[-len / 2 + 4, -h / 2 + 4], [len / 2 - 4, -h / 2 + 4], [len / 2 - 4, -h / 2 + 8], [-len / 2 + 4, -h / 2 + 9]] as P[]).map(T)); c.fill(); c.globalAlpha = 0.18; c.strokeStyle = "#8a6a2a"; c.lineWidth = 0.7; for (let k = 0; k < 3; k++) { const x = -len / 2 + 12 + r() * (len - 20), a = T([x, -h / 2 + 2]), b = T([x + (r() - 0.5) * 10, h / 2 - 2]); c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.stroke(); } c.globalAlpha = 1; } });
    return { piece, draw: (g: Ctx, o: { reveal?: number } = {}) => { const p = easeOut(o.reveal ?? 1); if (p <= 0) return; if (p >= 1) { piece.draw(g); return; } g.save(); g.translate(at[0], at[1]); g.rotate(ang); g.beginPath(); g.rect(-len / 2 - 6, -h, (len + 12) * p, h * 2); g.rotate(-ang); g.translate(-at[0], -at[1]); g.clip(); piece.draw(g); g.restore(); } };
  }
  /** A slip of paper with a typed line. draw(g, {pose, n}) with n = characters struck so far (M.typed gives it). Each strike its own density and a hair off the line. */
  strip(id: string, text: string, o: { x: number; y: number; cap?: number; rot?: number; color?: string; seed?: number; ink?: string }) {
    const { x, y, cap = 20, rot = 0, color = "#f7f2e8", seed = (text.length * 37) % 997, ink = "#221d1a" } = o, w = measure(text, cap, STRIKE), s = tear(rect(w + cap * 1.6, cap * 2.3), 1.2, seed), ca = Math.cos(rot), sa = Math.sin(rot), sh = s.map(([px, py]) => [x + px * ca - py * sa, y + px * sa + py * ca] as P);
    const paper = this.piece(id, { cut: sh, depth: 3, shadow: "#3b2a14", pivot: [x, y], face: (c) => { c.fillStyle = color; path(c, sh); c.fill(); fibres(c, sh, color, seed, 0.6, 0.15); } });
    const full = this.plate(id + ":typed", (c) => { c.translate(x, y); c.rotate(rot); typed(c, text, -w / 2, -cap / 2, cap, ink, seed); }, { x0: x - w, y0: y - w - cap, x1: x + w, y1: y + w + cap });
    return { paper, width: w, draw: (g: Ctx, d: { pose?: Pose; n?: number } = {}) => { const q = d.pose ?? REST, n = d.n ?? Infinity; paper.draw(g, { pose: q }); if (n <= 0) return; if (n >= text.length) { full.draw(g, { x: q.dx, y: q.dy }); return; } g.save(); g.translate(x + q.dx, y + q.dy); g.rotate(rot); typed(g, text, -w / 2, -cap / 2, cap, ink, seed, n); g.restore(); } };
  }
  /** Each letter cut from a different printed page and pasted: a word as tiles. draw(g, t, t0, {each, dur}) pastes them one by one. */
  ransom(id: string, word: string, o: { x?: number; cx?: number; y: number; cap?: number; seed?: number }): any {
    if (o.cx !== undefined) { const { cx, ...rest } = o; return this.ransom(id, word, { ...rest, x: cx - this.ransom(`${id}:measure`, word, { ...rest, x: 0 }).width / 2 }); }
    const ox = o.x ?? 0;
    const cap0 = o.cap ?? 50, seed = o.seed ?? 91, r = rng(seed), tiles: { p: Piece; ch: string }[] = []; let x = ox, lastP = -1, lastF = -1, n = 0;
    [...word].forEach((ch, i) => {
      if (ch === " ") { x += cap0 * 0.6; return; }
      let pi = Math.floor(r() * PAIRS.length); if (pi === lastP) pi = (pi + 3) % PAIRS.length; let fi = Math.floor(r() * FACES.length); if (fi === lastF) fi = (fi + 2) % FACES.length; lastP = pi; lastF = fi;
      const [bg, fg] = PAIRS[pi], face = { ...FACES[fi] }; if (face.outline !== undefined) face.outline = bg;
      const cap = cap0 * (0.84 + r() * 0.3), gw = ((GLYPHS[ch.toUpperCase()]?.w ?? 4) * (face.wide ?? 1) + 6 * (face.slant ?? 0)) * (cap / 6), w = gw + cap * (0.5 + r() * 0.25), cx = x + w / 2, cy = o.y + (r() - 0.5) * cap0 * 0.22, rot = (r() - 0.5) * 0.2, news = r() < 0.4, s0 = seed * 10 + i, q = rng(s0), hw = gw + cap * 0.55, hh = cap * (1.5 + q() * 0.2), base: P[] = [[-hw / 2 + (q() - 0.5) * 4, -hh / 2 + (q() - 0.5) * 4], [hw / 2 + (q() - 0.5) * 4, -hh / 2 + (q() - 0.5) * 4], [hw / 2 + (q() - 0.5) * 4, hh / 2 + (q() - 0.5) * 4], [-hw / 2 + (q() - 0.5) * 4, hh / 2 + (q() - 0.5) * 4]], local = scissor(base, s0, 0.8), ca = Math.cos(rot), sa = Math.sin(rot), sh = local.map(([a, b]) => [cx + a * ca - b * sa, cy + a * sa + b * ca] as P);
      const p = this.piece(`${id}:${i}`, { cut: sh, depth: 3, shadow: "#3b2a14", pivot: [cx, cy], face: (c) => { c.fillStyle = bg; path(c, sh); c.fill(); fibres(c, sh, bg, s0, 0.6, 0.18); c.save(); c.translate(cx, cy); c.rotate(rot); if (news) { const rr = rng(s0 + 9), b = bounds(local); c.save(); path(c, local); c.clip(); c.globalAlpha = 0.3; c.fillStyle = fg; for (let yy = b.y0 + 3; yy < b.y1; yy += 5) { let xx = b.x0 + 2; while (xx < b.x1) { const l = 3 + rr() * 14; c.fillRect(xx, yy, l, 1.4); xx += l + 3; } } c.restore(); c.globalAlpha = 0.8; c.fillStyle = bg; c.fillRect(-gw / 2 - cap * 0.1, -cap / 2 - cap * 0.1, gw + cap * 0.2, cap * 1.2); c.globalAlpha = 1; } glyph(c, ch.toUpperCase(), -gw / 2, -cap / 2, cap, face, fg); c.restore(); c.globalAlpha = 1; } });
      tiles.push({ p, ch }); x += w + 3 + r() * 6; n++;
    });
    return { width: x - ox, tiles, draw: (g: Ctx, t: number, t0: number, d: { each?: number; dur?: number } = {}) => { const each = d.each ?? 0.07, dur = d.dur ?? 0.22; tiles.forEach((tl, i) => { const st = t0 + i * each; if (t < st) return; tl.p.draw(g, { pose: lay(t, st, dur, [-6, -22]) }); }); } };
  }
  /** Red pen or any ink: a wobbling, tapering line through pts. progress 0..1 is the nib travelling. */
  redPen(g: Ctx, pts: P[], o: { w?: number; color?: string; seed?: number; wobble?: number; progress?: number } = {}) { this.pen(g, smooth(pts, false, 10), { w: o.w ?? 3, color: o.color ?? REDPEN, seed: o.seed ?? 3, wobble: o.wobble ?? 0.6, taper: 0.5, opacity: 0.92, progress: o.progress ?? 1 }); }
  /** A ring drawn round something, overshooting where it closes. */
  ring(g: Ctx, cx: number, cy: number, rx: number, ry: number, o: { w?: number; color?: string; seed?: number; progress?: number } = {}) { const pts = Array.from({ length: 15 }, (_, i) => { const a = -2.4 + (i / 12.5) * Math.PI * 2, k = 1 + i * 0.008; return [cx + Math.cos(a) * rx * k, cy + Math.sin(a) * ry * k] as P; }); this.redPen(g, pts, { w: o.w ?? 3.4, color: o.color, seed: o.seed, progress: o.progress }); }
  /** Handwritten words in that pen, stroke by stroke; progress 0..1. */
  handWrite(g: Ctx, text: string, x: number, y: number, cap: number, o: { color?: string; seed?: number; progress?: number; slant?: number; w?: number } = {}) {
    const s = cap / 6, slant = o.slant ?? 0.22, seed = o.seed ?? 5, r = rng(seed * 17 + 3), all: P[][] = []; let cx = x;
    [...text.toUpperCase()].forEach((ch) => { const gl = GLYPHS[ch] ?? GLYPHS["-"], k = 1 + (r() - 0.5) * 0.12, dy = (r() - 0.5) * cap * 0.1, T = ([px, py]: P): P => [cx + (px + (6 - py) * slant) * s * k, y + dy + py * s * k]; (gl.l ?? []).forEach((st) => all.push(st.map(T))); (gl.c ?? []).forEach((st) => all.push(smooth(st, false, 6).map(T))); cx += ((gl.w ?? 4) * 0.92 + 1.1) * s; });
    let left = (o.progress ?? 1) >= 1 ? Infinity : (o.progress ?? 1) * all.length;
    all.forEach((st, i) => { const p = left === Infinity ? 1 : clamp01(left); if (left !== Infinity) left -= 1; if (p > 0) this.pen(g, st, { w: o.w ?? 2.2, color: o.color ?? REDPEN, seed: seed + i * 7, wobble: 0.45, taper: 0.5, opacity: 0.92, progress: p }); });
    return cx - x;
  }
  /** A rubber stamp: a double border and words, the ink broken and multiplied. Stamps down with draw(g, {s, alpha}). */
  stamp(id: string, text: string, o: { x: number; y: number; cap?: number; rot?: number; color?: string; seed?: number }) {
    const { x, y, cap = 26, rot = -0.14, color = RED, seed = 77 } = o, f: Face = { weight: 0.15, serif: 0.5, wide: 1.1 }, w = measure(text, cap, f) + cap * 1.8, h = cap * 2.5, R = Math.hypot(w, h) / 2 + 8;
    return this.plate(id, (c) => {
      c.save(); c.translate(x, y); c.rotate(rot); c.globalCompositeOperation = "source-over"; c.strokeStyle = color; c.fillStyle = color; c.lineWidth = 4; c.strokeRect(-w / 2, -h / 2, w, h); c.lineWidth = 1.5; c.strokeRect(-w / 2 + 7, -h / 2 + 7, w - 14, h - 14);
      let px = -measure(text, cap, f) / 2; [...text].forEach((ch) => { glyph(c, ch, px, -cap / 2, cap, f, color); px += advance(ch, f) * (cap / 6); }); c.restore();
      const r = rng(seed); c.globalCompositeOperation = "destination-out"; for (let i = 0; i < w * h * 0.03; i++) { const a = r() * 6.28, d = Math.sqrt(r()) * R; c.globalAlpha = 0.25 + r() * 0.65; c.beginPath(); c.arc(x + Math.cos(a) * d, y + Math.sin(a) * d, 0.5 + r() * r() * 2.4, 0, 6.28); c.fill(); }
      c.globalCompositeOperation = "source-over"; c.globalAlpha = 1;
    }, { x0: x - R, y0: y - R, x1: x + R, y1: y + R }, [x, y]);
  }
  /** Twine between points with a brass tack at the start: a plate. */
  twine(id: string, pts: P[]) {
    const s = smooth(pts, false, 12), b = bounds(s);
    return this.plate(id, (c) => { const G = this; c.save(); c.globalAlpha = 0.3; G.pen(c, s.map(([x, y]) => [x + 1.5, y + 3] as P), { w: 2, color: "#3b2a14", seed: 3, wobble: 0, taper: 0, opacity: 1 }); c.restore(); G.pen(c, s, { w: 2.1, color: this.palette.twine, seed: 4, wobble: 0.3, taper: 0, opacity: 1 }); c.strokeStyle = "#4c3a24"; c.lineWidth = 0.7; c.globalAlpha = 0.6; for (let i = 2; i < s.length; i += 3) { const [x, y] = s[i]; c.beginPath(); c.moveTo(x - 1.2, y - 1.2); c.lineTo(x + 1.2, y + 1.2); c.stroke(); } c.globalAlpha = 1; const [px, py] = pts[0], gr = c.createRadialGradient(px - 2, py - 2, 0.5, px, py, 6.5); gr.addColorStop(0, "#f3dc9a"); gr.addColorStop(0.5, "#c49a45"); gr.addColorStop(1, "#7a5a22"); c.fillStyle = gr; c.beginPath(); c.arc(px, py, 6.5, 0, 6.28); c.fill(); }, { x0: b.x0 - 20, y0: b.y0 - 20, x1: b.x1 + 20, y1: b.y1 + 20 });
  }
  /** A wooden clothespin standing at (x, y), for a card hung on twine. */
  peg(id: string, x: number, y: number, a = 0.05) {
    const co = Math.cos(a), si = Math.sin(a), T = ([u, v]: P): P => [x + u * co - v * si, y + u * si + v * co], half = (sg: number): P[] => ([[sg * 1, -40], [sg * 10, -40], [sg * 11, -30], [sg * 9, -6], [sg * 12, 14], [sg * 11, 40], [sg * 1, 40]] as P[]).map(T);
    return this.piece(id, { cut: [half(-1), half(1)], depth: 4, shadow: "#3b2a14", pivot: [x, y], face: (c) => { ([-1, 1] as const).forEach((sg) => { const sh = half(sg); c.fillStyle = sg < 0 ? "#d9b88a" : "#c9a577"; path(c, sh); c.fill(); c.strokeStyle = "#8a6a44"; c.lineWidth = 0.6; c.globalAlpha = 0.5; for (let k = 0; k < 3; k++) { const u = sg * (3 + k * 2.6), a1 = T([u, -38]), b1 = T([u + sg * 0.8, 38]); c.beginPath(); c.moveTo(a1[0], a1[1]); c.lineTo(b1[0], b1[1]); c.stroke(); } c.globalAlpha = 1; }); c.strokeStyle = "#5b5f63"; c.lineWidth = 1.6; for (let k = 0; k < 4; k++) { const a1 = T([-12, -4 + k * 2.6]), b1 = T([12, -2 + k * 2.6]); c.beginPath(); c.moveTo(a1[0], a1[1]); c.lineTo(b1[0], b1[1]); c.stroke(); } } });
  }
  /** Copperplate tone inside a shape: parallel burin lines that swell where tone(x, y) (0..1) is dark and lift to nothing where it's light. Paint it in a card's or plate's face. */
  engraved(c: Ctx, shape: P[], o: { tone: (x: number, y: number) => number; angle?: number; gap?: number; w?: number; color?: string; seed?: number; min?: number }) {
    const b = bounds(shape), w = o.w ?? 2.6, runs = hatchRuns(b, o.angle ?? -0.6, o.gap ?? 5, (x, y) => inside(shape, x, y), 3, o.seed ?? 1);
    c.fillStyle = o.color ?? INK; runs.forEach((run) => burin(c, cutLine(run, (x, y) => w * Math.min(1, Math.max(0, o.tone(x, y))), [], 2), o.min ?? 0.16));
  }
  /** A thin hand tint over an engraving: colour multiplied through the shape. */
  tint(c: Ctx, shape: P[], color: string, alpha = 0.45) { c.save(); c.globalCompositeOperation = "multiply"; c.globalAlpha = alpha; c.fillStyle = color; path(c, shape); c.fill(); c.restore(); }
  /** The sheet's tooth and handled edges over the finished frame, in screen space: last thing in the frame. */
  finish(g: Ctx, o: { paper?: number; vignette?: string | null } = {}) { this.sheet(g, { paper: o.paper ?? 0.1, vignette: o.vignette === undefined ? "rgba(96,62,24,0.30)" : o.vignette }); }
}

register("scrapbook", { start: (w: number, h: number, o?: { scale?: number }) => new ScrapHand(w, h, o) });
