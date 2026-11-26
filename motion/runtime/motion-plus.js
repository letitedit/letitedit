/* letitedit motion runtime, part 2 (3 Nov 2026): springs, more curves, a camera and the font preload.
 *
 * Loaded after motion.js into every motion and code-scene page. motion.js itself is untouched on purpose: a saved code
 * scene is pinned by a hash of its source and the runtime, so changing motion.js would orphan every scene already made.
 * This file only adds names (M.spring, M.bezier, M.camera, ...) and joins the hash of a page that uses one of them
 * (bridge\motion.py uses_plus), so pages that don't use them keep the hash they had.
 *
 * Written for letitedit (GPL-3.0-or-later). No third-party code.
 */
(function () {
  'use strict';
  const M = window.M;
  // More curves (3 Nov 2026). The names above are unchanged, so every existing block draws the same frames.
  M.ease.sineInOut = (x) => -(Math.cos(Math.PI * x) - 1) / 2;
  M.ease.quartOut = (x) => 1 - Math.pow(1 - x, 4);
  M.ease.quintOut = (x) => 1 - Math.pow(1 - x, 5);
  M.ease.quartIn = (x) => x * x * x * x;
  M.ease.quartInOut = (x) => (x < 0.5 ? 8 * x * x * x * x : 1 - Math.pow(-2 * x + 2, 4) / 2);
  M.ease.circOut = (x) => Math.sqrt(Math.max(0, 1 - Math.pow(x - 1, 2)));
  /** Zero speed and zero acceleration at both ends: the calmest way to move a camera or a big shape. */
  M.ease.smooth = (x) => x * x * x * (x * (6 * x - 15) + 10);
  /** Arrives with a 3% overshoot (backOut overshoots about 10%). */
  M.ease.backOutSoft = (x) => { const s = 0.9; return 1 + (s + 1) * Math.pow(x - 1, 3) + s * Math.pow(x - 1, 2); };
  /** Winds back a little, then goes: anticipation before a big move. */
  M.ease.anticipate = (x) => {
    const s = 1.70158 * 1.525;
    return x < 0.5 ? (Math.pow(2 * x, 2) * ((s + 1) * 2 * x - s)) / 2
      : (Math.pow(2 * x - 2, 2) * ((s + 1) * (x * 2 - 2) + s) + 2) / 2;
  };
  const bez = {};
  /** CSS-style cubic-bezier(x1, y1, x2, y2) as an easing function (y outside 0..1 overshoots). */
  M.bezier = (x1, y1, x2, y2) => {
    const key = [x1, y1, x2, y2].join();
    if (bez[key]) return bez[key];
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const X = (u) => ((ax * u + bx) * u + cx) * u, Y = (u) => ((ay * u + by) * u + cy) * u;
    return (bez[key] = (x) => {
      if (x <= 0) return 0;
      if (x >= 1) return 1;                  // exact ends: a solver that returns 1e-9 at 0 fires early guards
      let lo = 0, hi = 1, u = x;
      for (let i = 0; i < 40; i++) { const v = X(u); if (Math.abs(v - x) < 1e-7) break; if (v < x) lo = u; else hi = u; u = (lo + hi) / 2; }
      return Y(u);
    });
  };
  // A spring step response, closed form (no stepping, so any frame renders on its own). 0 -> 1 from rest.
  const springStep = (t, w0, z) => {
    if (t <= 0) return 0;
    if (Math.abs(z - 1) < 1e-6) return 1 - Math.exp(-w0 * t) * (1 + w0 * t);
    if (z < 1) {
      const wd = w0 * Math.sqrt(1 - z * z);
      return 1 - Math.exp(-z * w0 * t) * (Math.cos(wd * t) + (z * w0 / wd) * Math.sin(wd * t));
    }
    const a = z * w0, r = w0 * Math.sqrt(z * z - 1);   // overdamped: written so large t cannot overflow
    return 1 - (Math.exp(-(a - r) * t) * (1 + a / r) + Math.exp(-(a + r) * t) * (1 - a / r)) / 2;
  };
  /** The value `t` seconds after a spring is let go: {stiffness 170, damping 26, mass 1, from 0, to 1}.
   *  damping ratio = damping / (2 sqrt(stiffness mass)); under 1 it overshoots, 1 is the fastest without overshoot. */
  M.spring = (t, o = {}) => {
    const k = o.stiffness == null ? 170 : o.stiffness, c = o.damping == null ? 26 : o.damping, m = o.mass == null ? 1 : o.mass;
    const from = o.from == null ? 0 : o.from, to = o.to == null ? 1 : o.to;
    return from + (to - from) * springStep(t - (o.delay || 0), Math.sqrt(k / m), c / (2 * Math.sqrt(k * m)));
  };
  /** Seconds until M.spring is within `eps` of its target for good. */
  M.springSettle = (o = {}, eps = 0.002) => {
    const k = o.stiffness == null ? 170 : o.stiffness, c = o.damping == null ? 26 : o.damping, m = o.mass == null ? 1 : o.mass;
    const w0 = Math.sqrt(k / m), z = c / (2 * Math.sqrt(k * m));
    let last = 0;
    for (let t = 0; t < 30; t += 1 / 240) if (Math.abs(springStep(t, w0, z) - 1) > eps) last = t;
    return last + 1 / 240;
  };
  const springs = {};
  /** An easing function that arrives with the given overshoot (0.08 = goes 8% past, then settles by x = 1):
   *  0 is the fastest approach with none; 0.03 paper, 0.05-0.10 a button or card, 0.15-0.25 rubber, 0.4+ a toy. */
  M.springEase = (overshoot = 0.08) => {
    const os = M.clamp(overshoot, 0, 0.7), key = os.toFixed(4);
    if (springs[key]) return springs[key];
    const ln = Math.log(Math.max(os, 1e-9));
    const z = os <= 0.0005 ? 1 : -ln / Math.sqrt(Math.PI * Math.PI + ln * ln);
    let settle = 0;
    for (let t = 0; t < 400; t += 0.02) if (Math.abs(springStep(t, 1, z) - 1) > 0.002) settle = t;
    settle += 0.02;
    return (springs[key] = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : springStep(x * settle, 1, z)));
  };
  /** Delay (s) of item i of n in a stagger. each: seconds between neighbours; total: cap on the whole stagger (the
   *  gap shrinks to fit); from: 'start' | 'end' | 'center' | 'edges' | 'random' (seed). */
  M.stagger = (i, n, o = {}) => {
    if (n <= 1) return 0;
    let each = o.each == null ? 0.06 : o.each;
    if (o.total != null && each * (n - 1) > o.total) each = o.total / (n - 1);
    const from = o.from || 'start';
    let rank = i;
    if (from === 'end') rank = n - 1 - i;
    else if (from === 'center') rank = Math.abs(i - (n - 1) / 2);
    else if (from === 'edges') rank = (n - 1) / 2 - Math.abs(i - (n - 1) / 2);
    else if (from === 'random') { const r = M.rand((o.seed || 1) * 7919 + i * 104729); rank = r() * (n - 1); }
    return Math.max(0, rank) * each;
  };
  /** How many characters of `str` are typed `t - start` seconds in, at `rate` letters a second. */
  M.typed = (str, t, start = 0, rate = 28) => M.clamp(Math.floor((t - start) * rate) + 1, 0, String(str).length);
  /** A camera through one world. keys: [{t, z (zoom), x, y (px the view centre moved), ease}] sorted by t; zoom is
   *  interpolated in log space, so a 1x -> 2x move looks as even as 2x -> 4x. Returns {x, y, z}. */
  M.camera = (keys, t) => {
    if (!keys.length) return { x: 0, y: 0, z: 1 };
    const at = (k) => ({ x: k.x || 0, y: k.y || 0, z: k.z || 1 });
    if (t <= keys[0].t) return at(keys[0]);
    for (let i = 1; i < keys.length; i++) {
      if (t <= keys[i].t) {
        const a = at(keys[i - 1]), b = at(keys[i]);
        const u = M.prog(t, keys[i - 1].t, keys[i].t - keys[i - 1].t, keys[i].ease || 'smooth');
        return { x: M.lerp(a.x, b.x, u), y: M.lerp(a.y, b.y, u), z: Math.exp(M.lerp(Math.log(a.z), Math.log(b.z), u)) };
      }
    }
    return at(keys[keys.length - 1]);
  };
  /** Where a layer at `depth` sits for camera `cam` (from M.camera): 0 = infinitely far (does not move), 1 = the
   *  focal plane (moves with the camera), above 1 = in front of it. Returns {x, y, s} for M.set or a canvas transform. */
  M.parallax = (cam, depth) => ({ x: -cam.x * depth, y: -cam.y * depth, s: 1 + (cam.z - 1) * depth });

  // Canvas-only fonts are never requested by the page, so ask for every declared face before the first frame.
  const start = M.start;
  M.start = () => {
    const loads = [];
    try { if (document.fonts && document.fonts.forEach) document.fonts.forEach((f) => loads.push(f.load().catch(() => null))); } catch (e) { /* no fonts to load */ }
    start();
    const hf = window.__hf && window.__hf.buildReady;
    if (hf && hf.letitedit) { const built = hf.letitedit; hf.letitedit = Promise.all(loads).then(() => built); }
  };
})();
