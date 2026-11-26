// letitedit hand: toy brick. M.look.toyBrick.start(w, h) gives studded parts, an instruction-booklet assembly and a painter's order; the
// model is written fresh by the AI. See motion\runtime\looks\toyBrick.md.
//
// Adapted from anidoodle's canvas-core/toyBrick.ts and toyBrickKit.ts (Copyright 2026 Alex Greenshpun, Apache-2.0; commit 9c20e77). Changed by
// letitedit, 4 Nov 2026: the kit is imported as it is; the render (shadows, ghost, settled layer) is taken from toyBrick.ts with the frame
// made transparent and sizes as arguments; the tugboat and its film runner are left out; the model builder, step schedule, letters and
// draw-through-the-camera are ours.
import { aabb, Cam, drawPart, LIGHT, order, PLATE, STUD, STUD_H, shade, type Part } from "./anidoodle/toyBrickKit";
import type { Ctx, Layer } from "./anidoodle/core";
import { eachCell } from "./pixelFont";
import { Hand, register } from "./shared";

export const COLOURS = { red: "#B40000", blue: "#1E5AA8", yellow: "#FAC80A", green: "#00852B", lime: "#A5CA18", white: "#F4F4F4", black: "#1B2A34", lightGrey: "#969696", darkGrey: "#646464", brown: "#5F3109", tan: "#D7BA8C", orange: "#D67923", azure: "#68C3E2", pink: "#E4ADC8", purple: "#7B5AA6", darkBlue: "#19325A" };
const OUTLINE = "#FAC80A", HAIR = 0.7, FALL = 10, DROP = 190, SLOT = 5;
type At = { y?: number; h?: number; color?: string; studs?: boolean };
const rectFoot = (x0: number, z0: number, x1: number, z1: number): [number, number][] => [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
const ccw = (f: [number, number][]) => { let a = 0; f.forEach((p, i) => { const q = f[(i + 1) % f.length]; a += p[0] * q[1] - q[0] * p[1]; }); return a < 0 ? [...f].reverse() : f; };

/** A model under construction, in build order. Units: x and z in studs; y and h in plates (a brick is 3 plates tall). step() starts the next booklet step. */
class Builder {
  parts: Part[] = []; steps: number[] = []; private s = 0; private id = 0; private colour = COLOURS.red;
  private add(p: Omit<Part, "id" | "step">) { const part = { ...p, id: this.id++, step: this.s } as Part; this.parts.push(part); this.steps.push(this.s); return this; }
  color(c: string) { this.colour = c; return this; }
  /** The baseplate, always first: a thin studded plate under everything. */
  base(x0: number, z0: number, x1: number, z1: number, color: string = COLOURS.blue) { return this.add({ color, kind: "prism", foot: rectFoot(x0, z0, x1, z1), y0: -1, h: 1, studs: true }); }
  /** A brick w studs by d studs, 3 plates tall unless h says otherwise. */
  brick(x: number, z: number, w: number, d: number, o: At = {}) { return this.add({ color: o.color ?? this.colour, kind: "prism", foot: rectFoot(x, z, x + w, z + d), y0: o.y ?? 0, h: o.h ?? 3, studs: o.studs ?? true }); }
  /** A plate: one plate tall. */
  plate(x: number, z: number, w: number, d: number, o: At = {}) { return this.brick(x, z, w, d, { h: 1, ...o }); }
  /** A smooth tile: a plate with no studs. */
  tile(x: number, z: number, w: number, d: number, o: At = {}) { return this.brick(x, z, w, d, { h: 1, studs: false, ...o }); }
  /** A 1x1 round. */
  round(x: number, z: number, o: At = {}) { return this.add({ color: o.color ?? this.colour, kind: "round", foot: [[x, z]], y0: o.y ?? 0, h: o.h ?? 3, studs: o.studs ?? true }); }
  /** Any convex footprint, in studs: a wedge, a bow, a cut corner. */
  prism(foot: [number, number][], o: At = {}) { return this.add({ color: o.color ?? this.colour, kind: "prism", foot: ccw(foot), y0: o.y ?? 0, h: o.h ?? 3, studs: o.studs ?? true }); }
  /** A wall of bricks from (x, z), running along x, courses high, in a running bond with bricks of `len` studs. */
  wall(x: number, z: number, len: number, courses: number, o: At & { brick?: number } = {}) { const b = o.brick ?? 2; for (let c = 0; c < courses; c++) { let at = x + (c % 2 ? -b / 2 : 0); while (at < x + len) { const a = Math.max(x, at), e = Math.min(x + len, at + b); if (e > a) this.brick(a, z, e - a, 1, { ...o, y: (o.y ?? 0) + c * 3, h: 3 }); at += b; } } return this; }
  /** Words built as one-stud plates standing on the x axis: each letter cell is a 1x1 at (x, z), rows upward from y. Reads best from the lit side. */
  letters(text: string, x: number, z: number, o: At = {}) { const y0 = o.y ?? 0; eachCell(text, 0, 0, 1, (a, b) => { this.brick(x + a, z, 1, 1, { h: 1, studs: false, color: o.color ?? this.colour, y: y0 + (6 - b) }); }); return this; }
  step() { this.s++; return this; }
}

class Model {
  P: Part[]; land: number[] = []; first: number[] = []; settle = 0; total = 0; cam: Cam;
  private cache = new Map<string, unknown>(); private staticKey = ""; private L: Record<string, Layer> = {};
  constructor(private hand: BrickHand, b: Builder, o: { beat?: number; fps: number; fit?: { x0: number; y0: number; x1: number; y1: number } }) {
    this.P = b.parts; const beat = Math.round((o.beat ?? 0.5) * o.fps), W = hand.w, H = hand.h, f = o.fit ?? { x0: W * 0.07, y0: H * 0.1, x1: W * 0.93, y1: H * 0.9 };
    let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9; const probe = new Cam(1, 0, 0);
    this.P.forEach((p) => { const a = aabb(p); for (const X of [a.x0, a.x1]) for (const Y of [a.y0, a.y1]) for (const Z of [a.z0, a.z1]) { const q = probe.p(X, Y, Z); x0 = Math.min(x0, q[0]); x1 = Math.max(x1, q[0]); y0 = Math.min(y0, q[1]); y1 = Math.max(y1, q[1]); } });
    const s = Math.min((f.x1 - f.x0) / (x1 - x0), (f.y1 - f.y0) / (y1 - y0)); this.cam = new Cam(s, (f.x0 + f.x1) / 2 - ((x0 + x1) / 2) * s, (f.y0 + f.y1) / 2 - ((y0 + y1) / 2) * s);
    // each step starts on a beat; bottom up and back to front inside a step; at most four 5-frame slots
    const steps = [...new Set(this.P.map((p) => p.step))].sort((a, e) => a - e); let at = FALL;
    steps.forEach((st) => { const list = this.P.filter((p) => p.step === st).sort((a, e) => a.y0 - e.y0 || aabb(a).x0 + aabb(a).z0 - aabb(e).x0 - aabb(e).z0); const per = Math.max(1, Math.ceil(list.length / 4)); list.forEach((p, i) => { this.land[p.id] = at + Math.floor(i / per) * SLOT; this.first[p.id] = at; }); const end = at + (Math.ceil(list.length / per) - 1) * SLOT + FALL; at = Math.ceil(end / beat) * beat + beat * 0; if (at <= end) at += beat; });
    this.settle = Math.max(...this.land) + 3; this.total = this.settle + 6;
  }
  /** Seconds the whole build takes at this fps. */
  seconds(fps: number) { return this.total / fps; }
  private layer(k: string): Layer { let l = this.L[k]; if (!l) { l = this.L[k] = this.hand.env.canvas(this.hand.w, this.hand.h); } return l; }
  private shadowOf(c: Ctx, parts: { p: Part; dy: number }[], k: number) {
    const sx = -LIGHT[0] / LIGHT[1], sz = -LIGHT[2] / LIGHT[1], cam = this.cam; c.fillStyle = "#000";
    parts.forEach(({ p, dy }) => { const b = aabb(p, dy); if (b.y0 < -0.5) return; const pts: [number, number][] = []; for (const Y of [b.y0, b.y1 - (p.studs ? STUD_H : 0)]) for (const X of [b.x0, b.x1]) for (const Z of [b.z0, b.z1]) { const q = cam.p(X + sx * Y, 0, Z + sz * Y); pts.push([q[0] * k, q[1] * k]); } const h = hull(pts); c.beginPath(); h.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); c.fill(); });
  }
  private paintShadow(c: Ctx, parts: { p: Part; dy: number }[], a: number) {
    const k = 1 / 5, S = this.layer("soft"), w = Math.ceil(this.hand.w * k), h = Math.ceil(this.hand.h * k), s = S.ctx; s.setTransform(1, 0, 0, 1, 0, 0); s.clearRect(0, 0, w + 2, h + 2); this.shadowOf(s, parts, k);
    c.save(); c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = a; c.imageSmoothingEnabled = true; c.imageSmoothingQuality = "high"; c.drawImage(S.canvas, 0, 0, w, h, 0, 0, w / k, h / k); c.restore();
  }
  private ghost(c: Ctx, p: Part, dy: number, a: number) { if (a >= 1) { drawPart(c, this.cam, p, dy, HAIR); return; } const T = this.layer("ghost"), t = fresh(T.ctx); t.clearRect(0, 0, this.hand.w, this.hand.h); drawPart(t, this.cam, p, dy, HAIR); c.save(); c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = a; c.drawImage(T.canvas, 0, 0); c.restore(); }
  private paintBase(c: Ctx, p: Part, dy: number, a = 1) {
    const k = 1 / 6, S = this.layer("softBase"), w = Math.ceil(this.hand.w * k), h = Math.ceil(this.hand.h * k), s = S.ctx, cam = this.cam; s.setTransform(1, 0, 0, 1, 0, 0); s.clearRect(0, 0, w + 2, h + 2); s.setTransform(k, 0, 0, k, 0, 0); s.fillStyle = "#000";
    const b = aabb(p, dy), q = [cam.p(b.x0, b.y0 - 2, b.z0), cam.p(b.x1, b.y0 - 2, b.z0), cam.p(b.x1, b.y0 - 2, b.z1), cam.p(b.x0, b.y0 - 2, b.z1)]; s.beginPath(); q.forEach(([x, y], i) => (i ? s.lineTo(x + 10, y + 16) : s.moveTo(x + 10, y + 16))); s.closePath(); s.fill();
    c.save(); c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 0.22 * a; c.imageSmoothingEnabled = true; c.drawImage(S.canvas, 0, 0, w, h, 0, 0, w / k, h / k); c.restore();
    this.ghost(c, p, dy, a);
  }
  private outline(c: Ctx, parts: { p: Part; dy: number }[]) {
    const cam = this.cam; c.save(); c.strokeStyle = OUTLINE; c.lineWidth = Math.max(1.5, cam.s * 1.6); c.lineJoin = "round";
    parts.forEach(({ p, dy }) => { const b = aabb(p, dy), pts: [number, number][] = []; for (const X of [b.x0, b.x1]) for (const Y of [b.y0, b.y1 - (p.studs ? STUD_H : 0)]) for (const Z of [b.z0, b.z1]) pts.push(cam.p(X, Y, Z)); const h = hull(pts); c.beginPath(); h.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath(); c.stroke(); });
    c.restore();
  }
  /** frame = frames since this model began, a pure function; the finished model holds. outline: false leaves the booklet's yellow off. */
  private frame(c: Ctx, f: number, o: { outline?: boolean }) {
    const P = this.P, settle = f >= this.settle && f < this.settle + 6 ? [0, 0.6, 1, 1, 0.6, 0.25][f - this.settle] : 0;
    const state = P.map((p) => { const L = this.land[p.id]; if (f < L - FALL) return null; if (f >= L) return { p, dy: (f === L ? -0.5 : 0) - (p.id > 0 ? settle : 0), moving: false, t: 1 }; const t = (f - (L - FALL)) / FALL, e = 1 - (1 - t) ** 3; return { p, dy: DROP * (1 - e) * (p.id === 0 ? 2 : 1), moving: true, t }; });
    const live = state.filter((s): s is NonNullable<typeof s> => !!s); if (!live.length) return;
    const stat = live.filter((s) => !s.moving && s.dy === 0), key = stat.map((s) => s.p.id).join(","), base = stat.find((s) => s.p.id === 0), isBase = (p: Part) => p.id === 0 && p.y0 < 0, L = this.layer("static");
    if (this.staticKey !== key) { const s = fresh(L.ctx); s.clearRect(0, 0, this.hand.w, this.hand.h); if (base && isBase(base.p)) this.paintBase(s, base.p, 0); const rest = stat.filter((q) => !isBase(q.p)); if (rest.length) this.paintShadow(s, rest.map((q) => ({ p: q.p, dy: 0 })), 0.34); order(rest.map((q) => ({ p: q.p, dy: 0 })), this.cam).forEach((i) => drawPart(s, this.cam, rest[i].p, 0, HAIR)); this.staticKey = key; }
    c.drawImage(L.canvas, 0, 0);
    const dyn = live.filter((s) => s.moving || s.dy !== 0), ghostA = (t: number) => 0.35 + 0.65 * Math.min(1, t / 0.6);
    if (dyn.length) {
      const all = [...stat.filter((s) => !isBase(s.p)), ...dyn.filter((s) => !isBase(s.p))], ord = order(all.map((s) => ({ p: s.p, dy: s.dy })), this.cam), bd = dyn.find((s) => isBase(s.p)); if (bd) this.paintBase(c, bd.p, bd.dy, bd.moving ? ghostA(bd.t) : 1);
      dyn.forEach((s) => { if (isBase(s.p) || s.p.y0 > 0 || !base) return; this.paintShadow(c, [{ p: s.p, dy: s.dy }], 0.34 * Math.min(1, 0.25 + 0.75 * s.t)); });
      let seen = false; const firstDyn = ord.findIndex((i) => all[i].moving || all[i].dy !== 0);
      ord.forEach((i, k) => { const s = all[i]; if (k < firstDyn) return; if (s.moving || s.dy !== 0) { seen = true; this.ghost(c, s.p, s.dy, s.moving ? ghostA(s.t) : 1); return; } if (seen) drawPart(c, this.cam, s.p, 0, HAIR); });
    }
    if (o.outline !== false && f < this.settle) { const cur = live.filter((s) => { const stepNow = Math.max(...live.map((q) => q.p.step)); return s.p.step === stepNow && s.p.id !== 0; }); this.outline(c, cur.map((s) => ({ p: s.p, dy: s.dy }))); }
  }
  /** Assembled to `frame` (frames since the model began; a negative or 0 frame draws nothing). Take-apart: give it total - frame. x, y move the whole model. */
  draw(g: Ctx, o: { frame: number; x?: number; y?: number; outline?: boolean; alpha?: number }) {
    const F = this.layer("frame"), c = fresh(F.ctx); c.clearRect(0, 0, this.hand.w, this.hand.h);
    const f = Math.round(o.frame);
    if (f >= this.total) { const D = this.layer("done"); if (!this.cache.get("done")) { const d = fresh(D.ctx); this.frame(d, this.total, { outline: false }); this.cache.set("done", 1); } g.save(); if (o.alpha !== undefined) g.globalAlpha *= o.alpha; g.drawImage(D.canvas, o.x ?? 0, o.y ?? 0, this.hand.w, this.hand.h); g.restore(); return; }
    this.frame(c, f, o); g.save(); if (o.alpha !== undefined) g.globalAlpha *= o.alpha; g.drawImage(F.canvas, o.x ?? 0, o.y ?? 0, this.hand.w, this.hand.h); g.restore();
  }
}
// a canvas remembers its line settings and drawPart changes them part way through, so every pass starts from the same state: frame N must not depend on what came before
const fresh = (c: Ctx) => { c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 1; c.lineCap = "butt"; c.lineJoin = "miter"; c.miterLimit = 10; c.lineWidth = 1; return c; };
const hull = (pts: [number, number][]) => {
  const q = [...pts].sort((a, b) => a[0] - b[0] || a[1] - b[1]), cr = (o: number[], a: number[], b: number[]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo: [number, number][] = [], up: [number, number][] = [];
  for (const p of q) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
  for (let i = q.length - 1; i >= 0; i--) { const p = q[i]; while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
  return [...lo.slice(0, -1), ...up.slice(0, -1)];
};

class BrickHand extends Hand {
  COLOURS = COLOURS; STUD = STUD; PLATE = PLATE; shade = shade;
  constructor(w: number, h: number) { super(w, h, { scale: 1 }); }
  /** A model, built once, in build order. beat = seconds between booklet steps; fit = {x0,y0,x1,y1} the box it fills; fps = the project's. */
  model(_id: string, build: (b: Builder) => void, o: { fps: number; beat?: number; fit?: { x0: number; y0: number; x1: number; y1: number } }) { const b = new Builder(); build(b); return new Model(this, b, o); }
  /** One flat studio colour. */
  backdrop(g: Ctx, color = "#E7E4DE") { g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.fillStyle = color; g.fillRect(0, 0, this.w, this.h); g.restore(); }
  finish(_g: Ctx) { /* moulded plastic: no paper, no grain */ }
}

register("toyBrick", { start: (w: number, h: number) => new BrickHand(w, h), COLOURS });
