/* letitedit motion runtime: the small, GSAP-free animation layer every letitedit motion block is written in.
 *
 * Every frame is a pure function of time: HyperFrames seeks the page (hf-seek events) and the block's render(t)
 * sets styles from t alone, so any frame renders on its own, in any order, the same way every time.
 *
 * A block file calls M.block(name, build). build(stage, p, ctx) lays the block out once (after fonts load) and
 * returns render(t). ctx: {w, h, len, fps, u (px per 1080p px), kit, color(ref), font(ref) -> {family, weight}}.
 * The page sets window.LIM_SPEC = {block, params, kit, w, h, len, fps} before this file loads.
 *
 * Written for letitedit (GPL-3.0-or-later). No third-party code.
 */
(function () {
  'use strict';
  const M = {};
  window.M = M;

  // ------------------------------------------------------------------ maths and easing
  M.clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  M.lerp = (a, b, u) => a + (b - a) * u;
  const back = 1.70158;
  M.ease = {
    linear: (x) => x,
    in: (x) => x * x * x,
    out: (x) => 1 - Math.pow(1 - x, 3),
    inOut: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
    expoOut: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
    expoIn: (x) => (x <= 0 ? 0 : Math.pow(2, 10 * x - 10)),
    backOut: (x) => 1 + (back + 1) * Math.pow(x - 1, 3) + back * Math.pow(x - 1, 2),
    backIn: (x) => (back + 1) * x * x * x - back * x * x,
    elasticOut: (x) => (x <= 0 ? 0 : x >= 1 ? 1 : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * (2 * Math.PI / 3)) + 1),
    bounceOut: (x) => {
      const n = 7.5625, d = 2.75;
      if (x < 1 / d) return n * x * x;
      if (x < 2 / d) return n * (x -= 1.5 / d) * x + 0.75;
      if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + 0.9375;
      return n * (x -= 2.625 / d) * x + 0.984375;
    },
  };
  /** 0..1 progress of a phase starting at `start` lasting `dur`, eased. */
  M.prog = (t, start, dur, ease = 'out') => {
    const x = dur <= 0 ? (t >= start ? 1 : 0) : M.clamp((t - start) / dur);
    return (typeof ease === 'function' ? ease : M.ease[ease] || M.ease.out)(x);
  };
  /** Entrance x exit: 0 before `inStart`, 1 while held, back to 0 over the last `outDur` s of `len`. */
  M.life = (t, len, inDur = 0.5, outDur = 0.4, inStart = 0, easeIn = 'out', easeOut = 'in') =>
    Math.min(M.prog(t, inStart, inDur, easeIn), 1 - M.prog(t, len - outDur, outDur, easeOut));
  /** Seeded random numbers (mulberry32): same seed, same sequence. */
  M.rand = (seed = 1) => {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0;
      let r = Math.imul(a ^ (a >>> 15), 1 | a);
      r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  };

  // ------------------------------------------------------------------ DOM helpers
  /** Create an element: M.el('div', {class, style:{...}, text}, parent). */
  M.el = (tag, opts = {}, parent = null) => {
    const e = document.createElement(tag);
    if (opts.class) e.className = opts.class;
    if (opts.text != null) e.textContent = String(opts.text);
    if (opts.html != null) e.innerHTML = String(opts.html);
    if (opts.style) Object.assign(e.style, opts.style);
    if (parent) parent.appendChild(e);
    return e;
  };
  /** Set the animated look of an element in one call. Missing keys are left alone.
   *  {o: opacity, x, y (px), s (scale), sx, sy, r (deg), clip: [top, right, bottom, left] (0-1 inset), blur (px)} */
  M.set = (e, v) => {
    if (!e) return;
    if (v.o != null) e.style.opacity = String(M.clamp(v.o));
    const tf = [];
    if (v.x != null || v.y != null) tf.push(`translate(${(v.x || 0).toFixed(2)}px, ${(v.y || 0).toFixed(2)}px)`);
    if (v.r != null) tf.push(`rotate(${v.r.toFixed(3)}deg)`);
    if (v.s != null) tf.push(`scale(${v.s.toFixed(4)})`);
    if (v.sx != null || v.sy != null) tf.push(`scale(${(v.sx ?? 1).toFixed(4)}, ${(v.sy ?? 1).toFixed(4)})`);
    if (tf.length) e.style.transform = tf.join(' ');
    if (v.clip) {
      const [a, b, c, d] = v.clip.map((q) => (M.clamp(q) * 100).toFixed(3) + '%');
      e.style.clipPath = `inset(${a} ${b} ${c} ${d})`;
    }
    if (v.blur != null) e.style.filter = v.blur > 0.05 ? `blur(${v.blur.toFixed(2)}px)` : 'none';
  };
  /** Split an element's text into word (or 'chars') spans, inline-block so they can move. Returns the spans. */
  M.split = (e, mode = 'words') => {
    const text = e.textContent;
    e.textContent = '';
    const parts = mode === 'chars' ? Array.from(text) : text.split(/(\s+)/);
    const spans = [];
    for (const part of parts) {
      if (/^\s+$/.test(part)) { e.appendChild(document.createTextNode(part)); continue; }
      if (!part) continue;
      const s = M.el('span', { text: part, style: { display: 'inline-block', whiteSpace: 'pre' } }, e);
      spans.push(s);
    }
    return spans;
  };
  /** Shrink an element's font size until it fits `maxW` px wide (and `maxH` if given). Measures once at build time. */
  M.fit = (e, size, maxW, maxH = Infinity, min = 12) => {
    let s = size;
    e.style.fontSize = s + 'px';
    while (s > min && (e.scrollWidth > maxW + 0.5 || e.scrollHeight > maxH + 0.5)) {
      s = Math.max(min, s * 0.94);
      e.style.fontSize = s.toFixed(1) + 'px';
    }
    return s;
  };
  /** Text for a number: decimals, thousands separators, prefix/suffix. */
  M.num = (v, decimals = 0, sep = ',', prefix = '', suffix = '') => {
    const fixed = Math.abs(v).toFixed(decimals);
    let [whole, frac] = fixed.split('.');
    if (sep) whole = whole.replace(/\B(?=(\d{3})+(?!\d))/g, sep);
    return (v < 0 ? '-' : '') + prefix + whole + (frac ? '.' + frac : '') + suffix;
  };

  // ------------------------------------------------------------------ blocks and the seek hookup
  const blocks = {};
  M.block = (name, build) => { blocks[name] = build; };

  M.start = () => {
    const spec = window.LIM_SPEC;
    const stage = document.getElementById('stage');
    const kit = spec.kit || { colors: {}, fonts: {} };
    const ctx = {
      w: spec.w, h: spec.h, len: spec.len, fps: spec.fps, kit,
      u: Math.min(spec.w, spec.h) / 1080,
      portrait: spec.h > spec.w,
      color(ref, fallback = '#FFFFFF') {
        let v = ref == null ? fallback : ref;
        for (let i = 0; i < 5 && typeof v === 'string' && !v.startsWith('#') && kit.colors[v]; i++) v = kit.colors[v];
        return typeof v === 'string' && v.startsWith('#') ? v : fallback;
      },
      font(ref, fallback = 'body') {
        let f = ref == null ? fallback : ref;
        if (typeof f === 'string' && kit.fonts[f]) f = kit.fonts[f];
        if (typeof f === 'string') f = { family: f, weight: 700 };
        return { family: `"${f.family}", "Segoe UI", sans-serif`, weight: f.weight || 400, italic: !!f.italic };
      },
      style(e, fontRef, size, colorRef) {
        const f = ctx.font(fontRef);
        e.style.fontFamily = f.family;
        e.style.fontWeight = String(f.weight);
        if (f.italic) e.style.fontStyle = 'italic';
        if (size != null) e.style.fontSize = size + 'px';
        if (colorRef != null) e.style.color = ctx.color(colorRef);
        return e;
      },
    };
    let render = null;
    const ready = (document.fonts ? document.fonts.ready : Promise.resolve()).then(() => {
      const build = blocks[spec.block];
      if (!build) throw new Error('unknown motion block ' + spec.block);
      render = build(stage, spec.params || {}, ctx);
      render(0);
    });
    window.__hf = window.__hf || {};
    window.__hf.buildReady = window.__hf.buildReady || {};
    window.__hf.buildReady.letitedit = ready;
    window.addEventListener('hf-seek', (e) => {
      if (render) render(Math.max(0, Math.min(spec.len, e.detail.time)));
      else e.detail.waitUntil && e.detail.waitUntil(ready.then(() => render(e.detail.time)));
    });
  };
})();
