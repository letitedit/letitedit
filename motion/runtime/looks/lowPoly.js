/* letitedit drawing hand: lowPoly. Built from motion\runtime\looks-src (node build.mjs); don't edit this file.
 * Includes code from anidoodle (https://github.com/alexgreensh/anidoodle, commit 9c20e77), Copyright 2026 Alex Greenshpun, under the
 * Apache License 2.0: LICENSE-anidoodle.txt and NOTICE-anidoodle.txt beside this file. Changed by letitedit: see the headers in
 * looks-src. The rest is letitedit's own, GPL-3.0-or-later. Loaded into a code scene's page only when its script says M.look.lowPoly. */
(() => {
  // motion/runtime/looks-src/anidoodle/core.ts
  var rng = (seed) => {
    let a = seed >>> 0;
    return () => {
      a = a + 1831565813 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  };
  var noiseCache = /* @__PURE__ */ new Map();
  var table = (seed) => {
    let t = noiseCache.get(seed);
    if (!t) {
      const r = rng(seed * 7919 + 13), perm = new Uint16Array(512), gx = new Float32Array(256), gy = new Float32Array(256);
      const p = Array.from({ length: 256 }, (_, i) => i);
      for (let i = 255; i > 0; i--) {
        const j = Math.floor(r() * (i + 1));
        [p[i], p[j]] = [p[j], p[i]];
      }
      for (let i = 0; i < 512; i++) perm[i] = p[i & 255];
      for (let i = 0; i < 256; i++) {
        const a = r() * Math.PI * 2;
        gx[i] = Math.cos(a);
        gy[i] = Math.sin(a);
      }
      t = { perm, gx, gy };
      noiseCache.set(seed, t);
    }
    return t;
  };
  var noise2 = (seed, x, y, px = 0, py = 0) => {
    const { perm, gx, gy } = table(seed);
    const x0 = Math.floor(x), y0 = Math.floor(y), fx = x - x0, fy = y - y0;
    const w = (v, p) => (p > 0 ? (v % p + p) % p : v) & 255;
    const g = (ix, iy, dx, dy) => {
      const h = perm[perm[w(ix, px)] + w(iy, py)];
      return gx[h] * dx + gy[h] * dy;
    };
    const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
    const a = g(x0, y0, fx, fy), b = g(x0 + 1, y0, fx - 1, fy), c = g(x0, y0 + 1, fx, fy - 1), d = g(x0 + 1, y0 + 1, fx - 1, fy - 1);
    return a + sx * (b - a) + sy * (c + sx * (d - c) - (a + sx * (b - a)));
  };
  var fractal = (seed, x, y, fx, fy, oct, tile2 = 0) => {
    let sum = 0, amp = 1, px = tile2 ? Math.max(1, Math.round(fx * tile2)) : 0, py = tile2 ? Math.max(1, Math.round(fy * tile2)) : 0;
    let kx = tile2 ? px / tile2 : fx, ky = tile2 ? py / tile2 : fy;
    for (let o = 0; o < oct; o++) {
      sum += noise2(seed + o * 101, x * kx, y * ky, px, py) * amp;
      amp *= 0.5;
      kx *= 2;
      ky *= 2;
      px *= 2;
      py *= 2;
    }
    return (sum + 1) / 2;
  };
  var clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  var jitter = (pts, amt, seed) => {
    if (amt <= 0) return pts;
    const r = rng(seed);
    return pts.map(([x, y]) => [x + (r() - 0.5) * 2 * amt, y + (r() - 0.5) * 2 * amt]);
  };
  var sample = (pts, closed = false, per = 10) => {
    if (pts.length < 2) return pts;
    const n = pts.length, at = (i) => closed ? pts[(i % n + n) % n] : pts[Math.max(0, Math.min(n - 1, i))], out = [], segs = closed ? n : n - 1;
    for (let i = 0; i < segs; i++) {
      const [p0, p1, p2, p3] = [at(i - 1), at(i), at(i + 1), at(i + 2)];
      for (let k = 0; k < per; k++) {
        const t = k / per, t2 = t * t, t3 = t2 * t;
        out.push([0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3), 0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)]);
      }
    }
    out.push(closed ? out[0] : pts[n - 1]);
    return out;
  };
  var densify = (s, step) => {
    const out = [s[0]];
    for (let i = 1; i < s.length; i++) {
      const a = s[i - 1], b = s[i], n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / step));
      for (let k = 1; k <= n; k++) out.push([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n]);
    }
    return out;
  };
  var ribbon = (s0, width, seed, taper, pressure, rough = 0) => {
    const s = rough ? densify(s0, 1.5) : s0;
    const a = seed % 17 * 0.37, b = seed % 11 * 0.53, L = [], R = [], r = rng(seed * 31 + 7);
    for (let i = 0; i < s.length; i++) {
      const t = i / (s.length - 1), p = s[i], q = s[Math.min(s.length - 1, i + 1)], o = s[Math.max(0, i - 1)], dx = q[0] - o[0], dy = q[1] - o[1], len = Math.hypot(dx, dy) || 1;
      const ends = Math.min(1, t / 0.14, (1 - t) / 0.2), tp = 1 - taper + taper * Math.pow(Math.max(0.04, ends), 0.7);
      const pr = Math.max(0.14, 1 - 0.26 * pressure + pressure * (0.3 * Math.sin(t * 5.5 + a) + 0.14 * Math.sin(t * 17 + b)));
      const w = width * tp * pr / 2, j1 = (r() - 0.5) * rough, j2 = (r() - 0.5) * rough;
      L.push([p[0] - dy / len * (w + j1), p[1] + dx / len * (w + j1)]);
      R.push([p[0] + dy / len * (w + j2), p[1] - dx / len * (w + j2)]);
    }
    return [...L, ...R.reverse()];
  };
  var bbox = (s) => {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    s.forEach(([x, y]) => {
      x0 = Math.min(x0, x);
      y0 = Math.min(y0, y);
      x1 = Math.max(x1, x);
      y1 = Math.max(y1, y);
    });
    return { x0, y0, x1, y1, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 };
  };
  var scaled = (s, k, dx = 0, dy = 0) => {
    const b = bbox(s);
    return s.map(([x, y]) => [b.cx + (x - b.cx) * k + dx, b.cy + (y - b.cy) * k + dy]);
  };
  var displace = (pts, amp, freq, oct, seed) => pts.map(([x, y]) => [x + (fractal(seed, x, y, freq, freq, oct) - 0.5) * amp, y + (fractal(seed + 50, x, y, freq, freq, oct) - 0.5) * amp]);
  var TILE = 512;
  var TILES = {
    pencilTooth: { fx: 1.3, oct: 1, seed: 8, k: -2, o: 2.05 },
    // graphite skips the valleys of the sheet
    washGran: { fx: 0.09, oct: 2, seed: 11, k: -0.45, o: 1.2 },
    // granulating pigment
    risoSpeck: { fx: 1.15, oct: 2, seed: 18, k: -3, o: 2.35 },
    // pinholes where soy ink missed
    risoMottle: { fx: 0.012, fy: 0.05, oct: 3, seed: 22, k: -0.9, o: 1.38 },
    // the drum never inks evenly
    paper: { fx: 0.75, oct: 3, seed: 21, gray: true },
    coldpress: { fx: 0.16, oct: 4, seed: 23, gray: true },
    draftTooth: { fx: 0.95, oct: 2, seed: 33, k: -1.7, o: 1.95 },
    // ruling-pen ink breaking up on the tooth of the sheet
    blueMottle: { fx: 65e-4, oct: 4, seed: 37, gray: true }
    // a cyanotype never exposes evenly
  };
  var tile = (env, kind) => {
    const key = `tile:${kind}:${env.scale}`;
    let L = env.cache.get(key);
    if (L) return L;
    const sp = TILES[kind], n = Math.round(TILE * env.scale);
    L = env.canvas(n, n);
    const img = L.ctx.createImageData(n, n), d = img.data;
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const lx = x / env.scale, ly = y / env.scale, i = (y * n + x) * 4, v = fractal(sp.seed, lx, ly, sp.fx, sp.fy ?? sp.fx, sp.oct, TILE);
      if (sp.gray) {
        const lin = clamp((v + fractal(sp.seed + 7, lx, ly, sp.fx, sp.fy ?? sp.fx, sp.oct, TILE)) / 2), g = 255 * (lin <= 31308e-7 ? lin * 12.92 : 1.055 * Math.pow(lin, 1 / 2.4) - 0.055);
        d[i] = d[i + 1] = d[i + 2] = g;
        d[i + 3] = 255;
      } else {
        d[i] = d[i + 1] = d[i + 2] = 0;
        d[i + 3] = 255 * clamp(sp.k * v + sp.o);
      }
    }
    L.ctx.putImageData(img, 0, 0);
    env.cache.set(key, L);
    return L;
  };
  var GRAPHITE = "#3d3437";
  var Gfx = class {
    constructor(main, env, frame, medium) {
      this.main = main;
      this.env = env;
      this.frame = frame;
      this.medium = medium;
      this.cur = main;
      this.base(main);
      const key = `pool:${Math.round(env.W * env.scale)}x${Math.round(env.H * env.scale)}`;
      let pool = env.cache.get(key);
      if (!pool) {
        pool = [];
        env.cache.set(key, pool);
      }
      this.pool = pool;
    }
    main;
    env;
    frame;
    medium;
    // `drawn`: union of every device box composited onto `main` since construction. Read-only for the
    // art; the web profile (bake.ts) crops a part into a sprite by it. Setting it changes no pixel.
    drawn = null;
    cur;
    pool = [];
    stack = [[0, 0, 1, 0]];
    box = null;
    get m() {
      return this.stack[this.stack.length - 1];
    }
    get DW() {
      return Math.round(this.env.W * this.env.scale);
    }
    get DH() {
      return Math.round(this.env.H * this.env.scale);
    }
    base(c) {
      const [x, y, s, r] = this.m, k = this.env.scale;
      if (r === 0) {
        c.setTransform(k * s, 0, 0, k * s, k * x, k * y);
        return;
      }
      const co = Math.cos(r), si = Math.sin(r);
      c.setTransform(k * s * co, k * s * si, -k * s * si, k * s * co, k * x, k * y);
    }
    dev(c) {
      c.setTransform(1, 0, 0, 1, 0, 0);
    }
    clip(r, pad = 0) {
      return [Math.max(0, Math.floor(r[0] - pad)), Math.max(0, Math.floor(r[1] - pad)), Math.min(this.DW, Math.ceil(r[2] + pad)), Math.min(this.DH, Math.ceil(r[3] + pad))];
    }
    join(a, b) {
      return a ? [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])] : b;
    }
    // local points -> device box, with `pad` local units of slack (line weight, displacement, blur)
    boxOf(pts, pad) {
      const [tx, ty, s, r] = this.m, k = this.env.scale;
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const [x, y] of pts) {
        if (x < x0) x0 = x;
        if (y < y0) y0 = y;
        if (x > x1) x1 = x;
        if (y > y1) y1 = y;
      }
      x0 -= pad;
      y0 -= pad;
      x1 += pad;
      y1 += pad;
      if (r === 0) return this.clip([k * (tx + x0 * s), k * (ty + y0 * s), k * (tx + x1 * s), k * (ty + y1 * s)]);
      const co = Math.cos(r), si = Math.sin(r), cs = [[x0, y0], [x1, y0], [x0, y1], [x1, y1]];
      let a0 = 1e9, b0 = 1e9, a1 = -1e9, b1 = -1e9;
      for (const [x, y] of cs) {
        const ax = k * (tx + s * (co * x - si * y)), by = k * (ty + s * (si * x + co * y));
        if (ax < a0) a0 = ax;
        if (by < b0) b0 = by;
        if (ax > a1) a1 = ax;
        if (by > b1) b1 = by;
      }
      return this.clip([a0, b0, a1, b1]);
    }
    mark(pts, pad = 4) {
      this.box = this.join(this.box, this.boxOf(pts, pad));
    }
    touch(x0, y0, x1, y1) {
      this.mark([[x0, y0], [x1, y1]], 0);
    }
    // for raw ctx drawing inside a group
    layer() {
      let L = this.pool.pop();
      if (!L) {
        L = this.env.canvas(this.DW, this.DH);
        L.dirty = null;
      }
      this.dev(L.ctx);
      L.ctx.globalCompositeOperation = "source-over";
      L.ctx.globalAlpha = 1;
      if (L.dirty) {
        const d = L.dirty;
        L.ctx.clearRect(d[0], d[1], d[2] - d[0], d[3] - d[1]);
        L.dirty = null;
      }
      return L;
    }
    release(L, dirty) {
      L.dirty = dirty ? this.join(L.dirty ?? null, dirty) : L.dirty;
      this.pool.push(L);
    }
    push(x, y, s, r = 0) {
      const [px, py, ps, pr] = this.m;
      if (pr === 0) {
        this.stack.push([px + x * ps, py + y * ps, ps * s, r]);
        this.base(this.cur);
        return;
      }
      const co = Math.cos(pr), si = Math.sin(pr);
      this.stack.push([px + ps * (co * x - si * y), py + ps * (si * x + co * y), ps * s, pr + r]);
      this.base(this.cur);
    }
    pop() {
      this.stack.pop();
      this.base(this.cur);
    }
    path(c, pts) {
      c.beginPath();
      pts.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
      c.closePath();
    }
    // gaussian-ish blur without ctx.filter (Safari has none): halve the box N times, scale it back up
    soften(L, radius, r) {
      const rp = this.clip(r, radius * this.env.scale * 3), steps = Math.max(1, Math.round(Math.log2(Math.max(2, radius * this.env.scale * 1.6)))), T = this.layer(), U = this.layer();
      let w = rp[2] - rp[0], h = rp[3] - rp[1];
      if (w < 2 || h < 2) {
        this.release(T, null);
        this.release(U, null);
        return rp;
      }
      const sizes = [[w, h]];
      let src = L, sx = rp[0], sy = rp[1], a = T, b = U;
      for (let i = 0; i < steps; i++) {
        const nw = Math.max(1, Math.ceil(w / 2)), nh = Math.max(1, Math.ceil(h / 2));
        a.ctx.clearRect(0, 0, nw + 1, nh + 1);
        a.ctx.imageSmoothingEnabled = true;
        a.ctx.drawImage(src.canvas, sx, sy, w, h, 0, 0, nw, nh);
        sizes.push([nw, nh]);
        src = a;
        sx = 0;
        sy = 0;
        w = nw;
        h = nh;
        [a, b] = [b, a];
      }
      for (let i = steps - 1; i >= 1; i--) {
        const [dw, dh] = sizes[i];
        a.ctx.clearRect(0, 0, dw + 1, dh + 1);
        a.ctx.drawImage(src.canvas, 0, 0, w, h, 0, 0, dw, dh);
        src = a;
        w = dw;
        h = dh;
        [a, b] = [b, a];
      }
      this.dev(L.ctx);
      L.ctx.clearRect(rp[0], rp[1], rp[2] - rp[0], rp[3] - rp[1]);
      L.ctx.imageSmoothingEnabled = true;
      L.ctx.drawImage(src.canvas, 0, 0, w, h, rp[0], rp[1], rp[2] - rp[0], rp[3] - rp[1]);
      const used = [0, 0, sizes[1][0] + 1, sizes[1][1] + 1];
      this.release(T, used);
      this.release(U, used);
      return rp;
    }
    // multiply a layer's alpha by a texture tile, inside the box only (texK scales the tooth with the actor)
    tooth(L, kind, r, texK = 1) {
      const c = L.ctx, t = tile(this.env, kind);
      c.save();
      c.setTransform(texK, 0, 0, texK, 0, 0);
      c.globalCompositeOperation = "destination-in";
      c.fillStyle = c.createPattern(t.canvas, "repeat");
      c.beginPath();
      c.rect(r[0] / texK, r[1] / texK, (r[2] - r[0]) / texK, (r[3] - r[1]) / texK);
      c.clip();
      c.fillRect(r[0] / texK - 1, r[1] / texK - 1, (r[2] - r[0]) / texK + 2, (r[3] - r[1]) / texK + 2);
      c.restore();
    }
    // draw a group on its own layer, texture it once, composite only what was touched
    group(kind, fn, opts = {}) {
      const L = this.layer(), prev = this.cur, outer = this.box;
      this.cur = L.ctx;
      this.box = null;
      this.base(L.ctx);
      fn();
      this.cur = prev;
      if (prev !== this.main) this.base(prev);
      let r = this.box ?? [0, 0, this.DW, this.DH];
      this.box = outer;
      const k = this.m[2];
      if (kind === "paint") {
        r = this.soften(L, 0.9 * k, r);
        this.tooth(L, "washGran", r, k);
      }
      if (kind === "ink") this.tooth(L, "pencilTooth", r, k);
      if (opts.blur) r = this.soften(L, opts.blur, r);
      (opts.textures ?? []).forEach((t) => this.tooth(L, t, r));
      const m = this.main, w = r[2] - r[0], h = r[3] - r[1];
      if (w > 0 && h > 0) {
        const ox = Math.round((opts.off?.[0] ?? 0) * this.env.scale), oy = Math.round((opts.off?.[1] ?? 0) * this.env.scale);
        this.drawn = this.join(this.drawn, this.clip([r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy]));
      }
      if (w > 0 && h > 0) {
        m.save();
        this.dev(m);
        m.globalCompositeOperation = opts.blend ?? "source-over";
        m.globalAlpha = opts.alpha ?? 1;
        m.drawImage(L.canvas, r[0], r[1], w, h, r[0] + Math.round((opts.off?.[0] ?? 0) * this.env.scale), r[1] + Math.round((opts.off?.[1] ?? 0) * this.env.scale), w, h);
        m.restore();
      }
      this.release(L, r);
    }
    // INK IN ONE PASS. White ink on a blue ground blooms, so every line wants a soft halo under it.
    // Drawing the group twice (halo, then line) costs the strokes twice; this takes the halo from a
    // blurred COPY of the same ink instead, which is the same picture for half the stroke work.
    inkGroup(fn, o = {}) {
      const L = this.layer(), prev = this.cur, outer = this.box;
      this.cur = L.ctx;
      this.box = null;
      this.base(L.ctx);
      fn();
      this.cur = prev;
      if (prev !== this.main) this.base(prev);
      const r = this.box ?? [0, 0, this.DW, this.DH];
      this.box = outer;
      const w = r[2] - r[0], h = r[3] - r[1];
      if (w <= 0 || h <= 0) {
        this.release(L, r);
        return;
      }
      const H = this.layer(), pad = this.clip(r, (o.blur ?? 1.8) * this.env.scale * 3);
      this.dev(H.ctx);
      H.ctx.drawImage(L.canvas, r[0], r[1], w, h, r[0], r[1], w, h);
      const rh = this.soften(H, o.blur ?? 1.8, r);
      (o.textures ?? ["draftTooth"]).forEach((t) => this.tooth(L, t, r));
      this.drawn = this.join(this.drawn, this.join(rh, r));
      const m = this.main;
      m.save();
      this.dev(m);
      m.globalCompositeOperation = "source-over";
      m.globalAlpha = o.alpha ?? 0.28;
      m.drawImage(H.canvas, rh[0], rh[1], rh[2] - rh[0], rh[3] - rh[1], rh[0], rh[1], rh[2] - rh[0], rh[3] - rh[1]);
      m.globalAlpha = 1;
      m.drawImage(L.canvas, r[0], r[1], w, h, r[0], r[1], w, h);
      m.restore();
      this.base(m);
      this.release(L, r);
      this.release(H, pad);
    }
    // progress < 1 draws the first part of the stroke only, cut on the CENTRELINE so the travelling
    // tip keeps the taper of a lifting nib. progress 1 takes the old path, byte for byte.
    upTo(s, progress) {
      if (progress >= 1) return s;
      const n = (s.length - 1) * progress, i = Math.floor(n), f = n - i;
      const head = s.slice(0, i + 1);
      if (f > 1e-9 && i + 1 < s.length) head.push([s[i][0] + (s[i + 1][0] - s[i][0]) * f, s[i][1] + (s[i + 1][1] - s[i][1]) * f]);
      return head.length > 1 ? head : s.slice(0, 2);
    }
    pen(pts, o = {}) {
      const { w = 3.4, color = GRAPHITE, seed = 1, closed = false, wobble = 1.1, boil = 0.55, taper = 1, opacity = 0.96, retrace = true, progress = 1 } = o, M = this.medium, b = Math.floor(this.frame / 4), c = this.cur;
      if (progress <= 0) return;
      const ctrl = closed ? [...pts, pts[0], pts[1]] : pts, basePts = jitter(ctrl, wobble * M.wobble, seed), W = w * M.nib;
      const main = ribbon(this.upTo(sample(jitter(basePts, boil, seed * 911 + b)), progress), W, seed, taper * M.taper, M.pressure, M.rough);
      this.mark(main, 2);
      c.fillStyle = color;
      c.globalAlpha = opacity;
      this.path(c, main);
      c.fill();
      if (retrace && M.retrace) {
        const re = ribbon(this.upTo(sample(jitter(basePts, boil + 1.3 * M.wobble, seed * 577 + b)), progress), W * 0.5, seed + 5, 1, M.pressure, M.rough);
        this.mark(re, 2);
        c.globalAlpha = opacity * 0.4;
        this.path(c, re);
        c.fill();
      }
      c.globalAlpha = 1;
    }
    hatch(x, y, w, o = {}) {
      const { n = 8, len = 16, angle = -1.05, color = GRAPHITE, seed = 1, pw = 1.9, opacity = 0.55 } = o, r = rng(seed);
      for (let i = 0; i < n; i++) {
        const px = x + w * i / Math.max(1, n - 1) + (r() - 0.5) * 3, l = len * (0.7 + r() * 0.6), a = angle + (r() - 0.5) * 0.18;
        this.pen([[px, y], [px + Math.cos(a) * l * 0.5, y + Math.sin(a) * l * 0.5], [px + Math.cos(a) * l, y + Math.sin(a) * l]], { w: pw, color, seed: seed + i, wobble: 0.6, opacity, retrace: false });
      }
    }
    // a plain filled shape (for media that cut or print rather than paint)
    fill(pts, color, alpha = 1) {
      const c = this.cur;
      this.mark(pts, 2);
      c.globalAlpha = alpha;
      c.fillStyle = color;
      this.path(c, pts);
      c.fill();
      c.globalAlpha = 1;
    }
    // watercolour that never quite fills its outline; the wet edge is displaced GEOMETRY
    wash(pts, color, o = {}) {
      const { alpha = 0.62, seed = 1, dx = 3, dy = 2, shrink = 0.94, rim = true } = o, c = this.cur;
      const s = displace(scaled(sample(jitter(pts, 2.2, seed), true, 8), shrink, dx, dy), 13, 0.022, 3, 5);
      this.mark(s, 5);
      c.globalAlpha = alpha;
      c.fillStyle = color;
      this.path(c, s);
      c.fill();
      if (rim) {
        c.globalAlpha = alpha * 0.55;
        c.strokeStyle = color;
        c.lineWidth = 3.5;
        c.lineJoin = "round";
        c.stroke();
      }
      c.globalAlpha = 1;
    }
    // a shaded form: shadow colour underneath, the lit colour shifted toward the light (one soft pass, one crisp), a lifted highlight
    form(pts, color, shade, o = {}) {
      const { seed = 1, light = [-8, -9], alpha = 0.98, hi } = o, s = displace(sample(jitter(pts, 1.2, seed), true, 8), 13, 0.022, 3, 5), k = this.m[2];
      const r = this.boxOf(s, 3);
      this.box = this.join(this.box, r);
      const T = this.layer();
      this.base(T.ctx);
      T.ctx.fillStyle = shade;
      this.path(T.ctx, s);
      T.ctx.fill();
      const U = this.layer();
      this.base(U.ctx);
      U.ctx.fillStyle = color;
      U.ctx.translate(light[0], light[1]);
      this.path(U.ctx, s);
      U.ctx.fill();
      const ru = this.soften(U, 5 * k, this.boxOf(s.map(([x, y]) => [x + light[0], y + light[1]]), 2));
      const w = r[2] - r[0], h = r[3] - r[1];
      T.ctx.save();
      this.base(T.ctx);
      this.path(T.ctx, s);
      T.ctx.clip();
      this.dev(T.ctx);
      T.ctx.drawImage(U.canvas, r[0], r[1], w, h, r[0], r[1], w, h);
      this.base(T.ctx);
      T.ctx.translate(light[0] * 2.2, light[1] * 2.2);
      T.ctx.fillStyle = color;
      this.path(T.ctx, s);
      T.ctx.fill();
      if (hi) {
        const V = this.layer();
        this.base(V.ctx);
        V.ctx.fillStyle = "#ffffff";
        V.ctx.globalAlpha = 0.75;
        V.ctx.beginPath();
        V.ctx.ellipse(hi[0], hi[1], hi[2], hi[3], (hi[4] ?? -30) * Math.PI / 180, 0, Math.PI * 2);
        V.ctx.fill();
        const m = Math.max(hi[2], hi[3]);
        const rv = this.soften(V, 5 * k, this.boxOf([[hi[0] - m, hi[1] - m], [hi[0] + m, hi[1] + m]], 1));
        this.dev(T.ctx);
        T.ctx.drawImage(V.canvas, rv[0], rv[1], rv[2] - rv[0], rv[3] - rv[1], rv[0], rv[1], rv[2] - rv[0], rv[3] - rv[1]);
        this.release(V, rv);
      }
      T.ctx.restore();
      const c = this.cur;
      c.save();
      this.dev(c);
      c.globalAlpha = alpha;
      c.drawImage(T.canvas, r[0], r[1], w, h, r[0], r[1], w, h);
      c.restore();
      this.base(c);
      this.release(T, r);
      this.release(U, ru);
    }
    glow(cx, cy, r, color, opacity) {
      const c = this.cur, g = c.createRadialGradient(cx, cy, 0, cx, cy, r * 1.7), a = (v) => Math.round(255 * clamp(v * opacity)).toString(16).padStart(2, "0");
      [[0, 1], [0.35, 0.9], [0.6, 0.55], [0.8, 0.2], [1, 0]].forEach(([t, v]) => g.addColorStop(t, color + a(v)));
      this.touch(cx - r * 1.8, cy - r * 1.8, cx + r * 1.8, cy + r * 1.8);
      c.fillStyle = g;
      c.fillRect(cx - r * 2, cy - r * 2, r * 4, r * 4);
    }
    // the sheet itself, over everything
    paper(kind, opacity) {
      const m = this.main, t = tile(this.env, kind);
      m.save();
      this.dev(m);
      m.globalCompositeOperation = "multiply";
      m.globalAlpha = opacity;
      m.fillStyle = m.createPattern(t.canvas, "repeat");
      m.fillRect(0, 0, this.DW, this.DH);
      m.restore();
      this.base(m);
    }
    vignette(edge) {
      const m = this.main, W = this.env.W, H = this.env.H;
      m.save();
      this.base(m);
      m.translate(W / 2, H * 0.46);
      m.scale(1, H / W);
      const g = m.createRadialGradient(0, 0, 0, 0, 0, W * 0.72);
      g.addColorStop(0, "rgba(255,250,240,0.08)");
      g.addColorStop(0.45, "rgba(255,250,240,0)");
      g.addColorStop(1, edge);
      m.fillStyle = g;
      m.fillRect(-W, -H, W * 2, H * 2);
      m.restore();
    }
  };

  // motion/runtime/looks-src/anidoodle/gallery.ts
  var boxOf = (pts) => {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const [x, y] of pts) {
      x0 = Math.min(x0, x);
      y0 = Math.min(y0, y);
      x1 = Math.max(x1, x);
      y1 = Math.max(y1, y);
    }
    return { x0, y0, x1, y1 };
  };
  var bounds = boxOf;

  // motion/runtime/looks-src/shared.ts
  var makeEnv = (W, H, scale = 1) => ({
    W,
    H,
    scale,
    cache: /* @__PURE__ */ new Map(),
    canvas: (w, h) => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(w));
      canvas.height = Math.max(1, Math.round(h));
      return { canvas, ctx: canvas.getContext("2d") };
    }
  });
  var placed = (g, o, pivot, fn) => {
    g.save();
    if (o.clip) {
      g.beginPath();
      g.rect(o.clip.x0, o.clip.y0, o.clip.x1 - o.clip.x0, o.clip.y1 - o.clip.y0);
      g.clip();
    }
    const p = o.pivot ?? pivot ?? [0, 0], s = o.s ?? 1, r = o.r ?? 0;
    g.translate(p[0] + (o.x ?? 0), p[1] + (o.y ?? 0));
    if (r) g.rotate(r);
    if (s !== 1) g.scale(s, s);
    g.translate(-p[0], -p[1]);
    fn();
    g.restore();
  };
  var Plate = class {
    constructor(hand, paint, box, pivot) {
      this.hand = hand;
      this.paint = paint;
      this.box = box;
      this.pivot = pivot;
    }
    hand;
    paint;
    box;
    pivot;
    L = null;
    bake() {
      if (this.L) return this.L;
      const k = this.hand.scale, b = this.box, L = this.hand.env.canvas(Math.ceil((b.x1 - b.x0) * k), Math.ceil((b.y1 - b.y0) * k));
      L.ctx.setTransform(k, 0, 0, k, -b.x0 * k, -b.y0 * k);
      this.paint(L.ctx);
      this.L = L;
      return L;
    }
    draw(g, o = {}) {
      const L = this.bake(), b = this.box;
      placed(g, o, this.pivot, () => {
        g.globalAlpha *= o.alpha ?? 1;
        g.drawImage(L.canvas, b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
      });
    }
  };
  var softened = (env, src, w, h, radius) => {
    const steps = Math.max(1, Math.round(Math.log2(Math.max(2, radius * 1.6))));
    let cur = src, cw = w, ch = h;
    const down = [];
    for (let i = 0; i < steps; i++) {
      const nw = Math.max(1, Math.ceil(cw / 2)), nh = Math.max(1, Math.ceil(ch / 2)), n = env.canvas(nw, nh);
      n.ctx.imageSmoothingEnabled = true;
      n.ctx.imageSmoothingQuality = "high";
      n.ctx.drawImage(cur.canvas, 0, 0, cw, ch, 0, 0, nw, nh);
      down.push(n);
      cur = n;
      cw = nw;
      ch = nh;
    }
    for (let i = steps - 2; i >= -1; i--) {
      const tw = i < 0 ? w : Math.ceil(w / 2 ** (i + 1)), th = i < 0 ? h : Math.ceil(h / 2 ** (i + 1)), n = env.canvas(tw, th);
      n.ctx.imageSmoothingEnabled = true;
      n.ctx.imageSmoothingQuality = "high";
      n.ctx.drawImage(cur.canvas, 0, 0, cw, ch, 0, 0, tw, th);
      cur = n;
      cw = tw;
      ch = th;
    }
    return cur;
  };
  var REST = { dx: 0, dy: 0, rot: 0, lift: 0 };
  var asList = (cut) => typeof cut[0][0] === "number" ? [cut] : cut;
  var Piece = class {
    constructor(hand, o) {
      this.hand = hand;
      this.o = o;
      this.cuts = asList(o.cut);
      this.depth = o.depth ?? 6;
      const b = bounds(this.cuts.flat());
      this.pivot = o.pivot ?? [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2];
    }
    hand;
    o;
    face;
    shade;
    bx;
    pad = 0;
    depth;
    pivot;
    cuts;
    trace(c, dx, dy, grow) {
      c.save();
      c.translate(dx, dy);
      c.beginPath();
      this.cuts.forEach((s) => {
        s.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
        c.closePath();
      });
      c.fill(this.o.hole ? "evenodd" : "nonzero");
      if (grow > 0) {
        c.lineJoin = "round";
        c.lineWidth = 2 * grow;
        c.strokeStyle = c.fillStyle;
        c.stroke();
      }
      c.restore();
    }
    bake() {
      if (this.face) return;
      const k = this.hand.scale, env = this.hand.env, bd = this.o.border ?? 0, blur = 2 + this.depth * 0.5, b0 = bounds(this.cuts.flat());
      this.pad = bd + 4 + Math.ceil(blur * 3);
      const b = this.bx = { x0: b0.x0 - this.pad, y0: b0.y0 - this.pad, x1: b0.x1 + this.pad, y1: b0.y1 + this.pad };
      const W = Math.ceil((b.x1 - b.x0) * k), H = Math.ceil((b.y1 - b.y0) * k), at = (c2) => c2.setTransform(k, 0, 0, k, -b.x0 * k, -b.y0 * k);
      const F = env.canvas(W, H), c = F.ctx;
      at(c);
      if (this.o.edge) {
        c.fillStyle = this.o.edge;
        this.trace(c, 1.2, 1.9, bd);
      }
      if (bd) {
        c.fillStyle = this.o.borderColor ?? "#fbf9f2";
        this.trace(c, 0, 0, bd);
      }
      at(c);
      this.o.face(c);
      this.face = F;
      const S = env.canvas(W, H);
      at(S.ctx);
      S.ctx.fillStyle = this.o.shadow ?? "#2a1c10";
      this.trace(S.ctx, 0, 0, bd);
      this.shade = softened(env, S, W, H, blur * k);
    }
    /** pose (from land / lay), or x, y, s, r on top; alpha fades the whole piece; shadow false leaves the shadow off. */
    draw(g, o = {}) {
      this.bake();
      const q = o.pose ?? REST, b = this.bx, sd = this.depth * (1 + 2.2 * q.lift), w = b.x1 - b.x0, h = b.y1 - b.y0, a = o.alpha ?? 1;
      const stage = this.o.stage;
      placed(g, { ...o, clip: o.clip ?? stage, x: (o.x ?? 0) + q.dx, y: (o.y ?? 0) + q.dy, r: (o.r ?? 0) + q.rot }, this.pivot, () => {
        const base = g.globalAlpha;
        if (o.shadow !== false && this.depth > 0) {
          g.globalAlpha = base * a * Math.max(0, 0.36 - 0.1 * q.lift);
          g.drawImage(this.shade.canvas, b.x0 + sd * 0.6, b.y0 + sd, w, h);
        }
        g.globalAlpha = base * a;
        g.drawImage(this.face.canvas, b.x0, b.y0, w, h);
        g.globalAlpha = base;
      });
    }
  };
  var THIN = { nib: 1, taper: 0.3, pressure: 0.3, retrace: false, wobble: 0.4, rough: 0.3 };
  var Hand = class {
    env;
    scale;
    w;
    h;
    plates = /* @__PURE__ */ new Map();
    pieces = /* @__PURE__ */ new Map();
    constructor(w, h, o = {}) {
      this.w = w;
      this.h = h;
      this.scale = o.scale ?? 1;
      this.env = makeEnv(w, h, this.scale);
    }
    /** Puts the context back to a known state: call first in every frame. */
    begin(g) {
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.globalAlpha = 1;
      g.globalCompositeOperation = "source-over";
      g.imageSmoothingEnabled = true;
      g.imageSmoothingQuality = "high";
      g.filter = "none";
      return g;
    }
    /** paint(c) runs once, in world coordinates, the first time the plate is drawn. box = {x0, y0, x1, y1} (default the frame). */
    plate(id, paint, box, pivot) {
      let p = this.plates.get(id);
      if (!p) {
        p = new Plate(this, paint, box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, pivot);
        this.plates.set(id, p);
      }
      return p;
    }
    piece(id, o) {
      let p = this.pieces.get(id);
      if (!p) {
        p = new Piece(this, o);
        this.pieces.set(id, p);
      }
      return p;
    }
    /** Laid over a finished frame in screen space: a sheet's tooth multiplied in, and handled edges. */
    sheet(g, o = {}) {
      g.save();
      const G = new Gfx(g, this.env, 0, THIN);
      if ((o.paper ?? 0.12) > 0) G.paper(o.tile ?? "paper", o.paper ?? 0.12);
      if (o.vignette !== null) G.vignette(o.vignette ?? "rgba(60,36,14,0.32)");
      g.restore();
    }
    /** Time held on twos: a stop-motion pose lasts two frames. */
    twos(t, fps = 30) {
      const f = Math.round(t * fps + 1e-6);
      return (f - f % 2) / fps;
    }
    /** An ink line drawn through the current transform, wobbling and tapering like a hand: pts are smoothed; progress 0..1 draws part of it. */
    pen(g, pts, o = {}) {
      const m = g.getTransform(), a = g.globalAlpha, G = new Gfx(g, this.env, 0, THIN);
      g.setTransform(m);
      G.pen(pts, { w: o.w ?? 2.4, color: o.color ?? "#2a2019", seed: o.seed ?? 1, wobble: o.wobble ?? 0.5, boil: 0, taper: o.taper ?? 0.5, opacity: o.opacity ?? 0.95, retrace: false, progress: o.progress ?? 1 });
      g.globalAlpha = a;
    }
  };
  var smoothStep = (x) => {
    const v = x <= 0 ? 0 : x >= 1 ? 1 : x;
    return v * v * (3 - 2 * v);
  };
  var register = (name, value) => {
    const M = window.M;
    (M.look = M.look || {})[name] = value;
  };

  // motion/runtime/looks-src/lowPolyShared.ts
  var clamp01 = (v) => v <= 0 ? 0 : v >= 1 ? 1 : v;

  // motion/runtime/looks-src/lowPoly.ts
  var hex = (h) => [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255];
  var col = (c) => typeof c === "string" ? hex(c) : c;
  var rgb = (c) => `rgb(${Math.round(255 * clamp01(c[0]))},${Math.round(255 * clamp01(c[1]))},${Math.round(255 * clamp01(c[2]))})`;
  var mixV = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  var sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  var cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  var norm = (a) => {
    const l = Math.hypot(a[0], a[1], a[2]) || 1;
    return [a[0] / l, a[1] / l, a[2] / l];
  };
  var dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  var Mesh = class {
    faces = [];
    tri(a, b, c, color, o = {}) {
      this.faces.push({ v: [a, b, c], base: col(color), ...o });
      return this;
    }
    quad(a, b, c, d, color, o = {}) {
      this.tri(a, b, c, color, o);
      this.tri(a, c, d, color, o);
      return this;
    }
    box(x0, y0, z0, x1, y1, z1, color) {
      const A = [x0, y0, z0], B = [x1, y0, z0], C = [x1, y0, z1], D = [x0, y0, z1], E = [x0, y1, z0], F = [x1, y1, z0], G = [x1, y1, z1], H = [x0, y1, z1], o = { cull: true };
      this.quad(A, B, F, E, color, o).quad(B, C, G, F, color, o).quad(C, D, H, G, color, o).quad(D, A, E, H, color, o).quad(E, F, G, H, color, o).quad(D, C, B, A, color, o);
      return this;
    }
    /** A cone or a tapered column: `sides` flat sides from radius r at y to radius r2 at y + h. */
    cone(x, y, z, r, h, color, o = {}) {
      const n = o.sides ?? 6, rot = o.rot ?? 0, r2 = o.r2 ?? 0, q = rng(o.seed ?? 3), ring = (rad, yy) => Array.from({ length: n }, (_, i) => {
        const a = rot + i / n * 6.2832;
        return [x + Math.cos(a) * rad, yy, z + Math.sin(a) * rad];
      });
      const low = ring(r, y), top = [x, y + h, z], up = r2 > 0 ? ring(r2, y + h) : null;
      for (let i = 0; i < n; i++) {
        const a = low[i], b = low[(i + 1) % n], c = mixV(col(color), [q(), q(), q()], 0.03);
        if (up) this.quad(a, b, up[(i + 1) % n], up[i], c, { cull: true });
        else this.tri(a, b, top, c, { cull: true });
      }
      return this;
    }
    /** A pine: a trunk and three six-sided cone tiers. */
    pine(x, y, z, h, seed = 1, o = {}) {
      const r = rng(seed), rot = r() * 1.05, leaf = o.leaf ?? "#23463b";
      this.cone(x, y, z, h * 0.04, h * 0.25, o.trunk ?? "#4a3426", { sides: 4, r2: h * 0.03, rot });
      [[0.14, 0.42, 0.24], [0.36, 0.38, 0.18], [0.58, 0.42, 0.12]].forEach(([b, t, w], i) => this.cone(x, y + h * b, z, h * w, h * t, mixV(col(leaf), [0.6, 0.7, 0.55], i * 0.05), { rot: rot + i * 0.5, seed: seed + i }));
      return this;
    }
    /** A faceted ball, jittered by `rough`: a planet, a rock, a head, a bush. */
    ball(x, y, z, r, color, o = {}) {
      const lat = o.lat ?? 5, lon = o.lon ?? 8, q = rng(o.seed ?? 5), rough = o.rough ?? 0, sy = o.sy ?? 1, pts = [];
      for (let i = 0; i <= lat; i++) {
        const row = [], th = i / lat * Math.PI;
        for (let j = 0; j < lon; j++) {
          const ph = (j + i % 2 * 0.5) / lon * 6.2832, k = r * (1 + (i && i < lat ? (q() - 0.5) * rough : 0));
          row.push([x + Math.sin(th) * Math.cos(ph) * k, y + Math.cos(th) * k * sy, z + Math.sin(th) * Math.sin(ph) * k]);
        }
        pts.push(row);
      }
      for (let i = 0; i < lat; i++) for (let j = 0; j < lon; j++) {
        const a = pts[i][j], b = pts[i][(j + 1) % lon], c = pts[i + 1][(j + 1) % lon], d = pts[i + 1][j];
        if (i > 0) this.tri(a, b, c, color, { cull: true });
        if (i < lat - 1) this.tri(a, c, d, color, { cull: true });
      }
      return this;
    }
    /** Lofted through rings of points (each ring the same length): a hull, a bottle, a body. */
    loft(rings, color, o = {}) {
      const m = rings[0].length;
      for (let i = 0; i + 1 < rings.length; i++) for (let j = 0; j < (o.closed === false ? m - 1 : m); j++) {
        const k = (j + 1) % m;
        this.quad(rings[i][j], rings[i][k], rings[i + 1][k], rings[i + 1][j], color);
      }
      return this;
    }
    /** A heightfield on a perspective-friendly grid: columns widen with distance, rows grow about 12%, jittered, so facets stay about one size on screen. color(x, y, z, up) picks a colour; up is 1 on a flat face. floor clamps the land; faces wholly under it are left out, so water below shows through. */
    terrain(o) {
      const r = rng(o.seed ?? 77), z0 = o.z0 ?? 0, cols = o.cols ?? 40, near = o.near ?? 7, widen = o.widen ?? 0.66, floor = o.floor ?? -1e9, zs = [z0];
      while (zs[zs.length - 1] < o.z1) {
        const z = zs[zs.length - 1];
        zs.push(z + (o.first ?? 0.55) + (o.grow ?? 0.115) * (z - z0));
      }
      const grid = zs.map((z, i) => Array.from({ length: cols + 1 }, (_, j) => {
        const u = -1 + 2 * (j + (j > 0 && j < cols ? (r() - 0.5) * 0.6 : 0)) / cols, zz = i > 0 && i < zs.length - 1 ? z + (r() - 0.5) * 0.5 * (zs[i + 1] - zs[i - 1]) / 2 : z, x = u * (near + widen * (zz - z0));
        return [x, Math.max(floor, o.height(x, zz)), zz];
      }));
      for (let i = 0; i < zs.length - 1; i++) for (let j = 0; j < cols; j++) {
        const a = grid[i][j], b = grid[i][j + 1], c = grid[i + 1][j + 1], d = grid[i + 1][j], tris = r() < 0.5 ? [[a, b, c], [a, c, d]] : [[a, b, d], [b, c, d]];
        for (const t of tris) {
          if (t.every((q) => o.height(q[0], q[2]) <= floor)) continue;
          const n = norm(cross(sub(t[1], t[0]), sub(t[2], t[0]))), yc = (t[0][1] + t[1][1] + t[2][1]) / 3, xc = (t[0][0] + t[1][0] + t[2][0]) / 3, zc = (t[0][2] + t[1][2] + t[2][2]) / 3, k = 0.95 + r() * 0.1;
          this.tri(t[0], t[1], t[2], col(o.color(xc, yc, zc, Math.abs(n[1]))).map((v) => v * k));
        }
      }
      return this;
    }
    /** Water: a flat jittered grid at height y, coloured near to far, reflective. Not lit; only tinted by the distance. */
    water(o) {
      const y = o.y ?? 0, cols = o.cols ?? 18, rows = o.rows ?? 14, r = rng(o.seed ?? 9), near = col(o.near ?? "#2c3561"), far = col(o.far ?? "#d9a3a8"), P3 = (i, j) => [o.x0 + (o.x1 - o.x0) * (j + (j % cols ? (r() - 0.5) * 0.3 : 0)) / cols, y, o.z0 + (o.z1 - o.z0) * (i / rows) ** 1.7];
      const grid = Array.from({ length: rows + 1 }, (_, i) => Array.from({ length: cols + 1 }, (_2, j) => P3(i, j)));
      for (let i = 0; i < rows; i++) for (let j = 0; j < cols; j++) {
        const a = grid[i][j], b = grid[i][j + 1], c = grid[i + 1][j + 1], d = grid[i + 1][j], base = mixV(near, far, ((i + 0.5) / rows) ** 1.3), k = 0.96 + r() * 0.08;
        this.tri(a, b, c, base.map((v) => v * k), { water: true });
        this.tri(a, c, d, base.map((v) => v * (0.96 + r() * 0.08)), { water: true });
      }
      return this;
    }
  };
  var moved = (m) => {
    if (m instanceof Mesh) return m.faces;
    const { mesh, x = 0, y = 0, z = 0, ry = 0, rx = 0, s = 1 } = m, cy = Math.cos(ry), sy = Math.sin(ry), cx = Math.cos(rx), sx = Math.sin(rx);
    const T = ([a, b, c]) => {
      const a1 = a * s, b1 = b * s, c1 = c * s, b2 = b1 * cx - c1 * sx, c2 = b1 * sx + c1 * cx;
      return [x + a1 * cy + c2 * sy, y + b2, z - a1 * sy + c2 * cy];
    };
    return mesh.faces.map((f) => ({ ...f, v: f.v.map(T) }));
  };
  var LowPolyHand = class extends Hand {
    sunDir;
    amb;
    sunCol;
    hazeCol;
    hazeAt;
    hazeOver;
    hex = hex;
    rng = rng;
    fractal = fractal;
    smoothstep = (a, b, x) => smoothStep((x - a) / (b - a));
    ridged = (seed, x, z, f) => {
      const v = 1 - Math.abs(2 * fractal(seed, x, z, f, f, 4) - 1);
      return v * v;
    };
    constructor(w, h, o = {}) {
      super(w, h, { scale: 1 });
      this.sunDir = norm(o.sun ?? [-0.78, 0.11, 0.62]);
      this.amb = o.ambient ?? [0.5, 0.52, 0.8];
      this.sunCol = o.sunColour ?? [1.35, 0.82, 0.62];
      this.hazeCol = hex(o.haze ?? "#c79aa6");
      this.hazeAt = o.hazeAt ?? 8;
      this.hazeOver = o.hazeOver ?? 85;
    }
    mesh(build) {
      const m = new Mesh();
      build(m);
      return m;
    }
    proj(c) {
      const pitch = c.pitch ?? 0, yaw = c.yaw ?? 0, cp = Math.cos(pitch), sp = Math.sin(pitch), cy = Math.cos(yaw), sy = Math.sin(yaw), f = c.f ?? Math.max(this.w, this.h) * 0.82, ox = c.cx ?? this.w / 2, oy = c.cy ?? this.h / 2;
      const view = ([x, y, z]) => {
        const X0 = x - c.x, Y = y - c.y, Z0 = z - c.z, X = X0 * cy - Z0 * sy, Z = X0 * sy + Z0 * cy;
        return [X, Y * cp + Z * sp, Z * cp - Y * sp];
      };
      return { view, to: (v) => [ox + f * v[0] / v[2], oy - f * v[1] / v[2]] };
    }
    /** One colour for a face: its normal against the one sun plus a cool sky, hazed by distance. */
    shade(f, cam) {
      const [a, b, c] = f.v;
      let n = norm(cross(sub(b, a), sub(c, a)));
      const m = [(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3], to = [cam.x - m[0], cam.y - m[1], cam.z - m[2]];
      if (f.water) return { c: f.base, show: true };
      if (dot(n, to) < 0) {
        if (f.cull) return { c: f.base, show: false };
        n = [-n[0], -n[1], -n[2]];
      }
      const d = Math.max(0, dot(n, this.sunDir)), sky = 0.55 + 0.45 * Math.max(0, n[1]), base = f.base, lit = [base[0] * (this.amb[0] * sky + this.sunCol[0] * d), base[1] * (this.amb[1] * sky + this.sunCol[1] * d), base[2] * (this.amb[2] * sky + this.sunCol[2] * d)];
      return { c: mixV(lit, this.hazeCol, 1 - Math.exp(-Math.max(0, Math.hypot(to[0], to[1], to[2]) - this.hazeAt) / this.hazeOver)), show: true };
    }
    /** Draws meshes through a camera, far to near. faces = 0..1 of them shaded in painter's order, wire = 0..1 of the wireframe laid first (the modeller's order). reflect mirrors everything in the water; ripples = how many cuts break it; glitter = {x, color} a sun path. */
    draw(g, cam, list, o = {}) {
      const { view, to } = this.proj(cam), wy = o.waterY ?? 0;
      const water = [], solid = [];
      for (const m of list) for (const f of moved(m)) {
        const vs = f.v.map(view), z = (vs[0][2] + vs[1][2] + vs[2][2]) / 3;
        if (vs[0][2] < 0.2 || vs[1][2] < 0.2 || vs[2][2] < 0.2) continue;
        const q = this.shade(f, cam);
        if (!q.show) continue;
        const s = vs.map(to), it = { s, c: rgb(q.c), z }, off = (l) => l[0][0] < 0 && l[1][0] < 0 && l[2][0] < 0 || l[0][0] > this.w && l[1][0] > this.w && l[2][0] > this.w || l[0][1] < 0 && l[1][1] < 0 && l[2][1] < 0 || l[0][1] > this.h && l[1][1] > this.h && l[2][1] > this.h;
        if (off(s) && !o.reflect) continue;
        if (f.water) {
          water.push(it);
          continue;
        }
        if (o.reflect && f.v.some((p) => p[1] > wy + 0.01)) {
          const mv = f.v.map(([x, y, zz]) => view([x, wy * 2 - Math.max(wy, y), zz]));
          if (mv.every((p) => p[2] > 0.2) && !off(mv.map(to))) solid.push({ ...it, m: mv.map(to), mc: rgb(mixV(q.c, hex("#35406a"), 0.28).map((v) => v * 0.82)) });
          else if (!off(s)) solid.push(it);
        } else solid.push(it);
      }
      water.sort((a, b) => b.z - a.z);
      solid.sort((a, b) => b.z - a.z);
      const put = (s, c) => {
        g.fillStyle = c;
        g.strokeStyle = c;
        g.beginPath();
        g.moveTo(s[0][0], s[0][1]);
        g.lineTo(s[1][0], s[1][1]);
        g.lineTo(s[2][0], s[2][1]);
        g.closePath();
        g.fill();
        g.stroke();
      };
      g.save();
      g.lineWidth = 0.7;
      g.lineJoin = "round";
      const all = water.length + solid.length, wireP = o.wire ?? 0, faceP = o.faces ?? 1, shown = Math.floor(faceP * all);
      water.slice(0, shown).forEach((t) => put(t.s, t.c));
      if (faceP >= 1 && water.length) {
        g.save();
        g.beginPath();
        water.forEach((t) => {
          g.moveTo(t.s[0][0], t.s[0][1]);
          g.lineTo(t.s[1][0], t.s[1][1]);
          g.lineTo(t.s[2][0], t.s[2][1]);
          g.closePath();
        });
        g.clip();
        if (o.reflect) solid.forEach((t) => {
          if (t.m) put(t.m, t.mc);
        });
        const r = rng(o.seed ?? 41);
        let y0 = 1e9, y1 = -1e9;
        water.forEach((t) => t.s.forEach((p) => {
          y0 = Math.min(y0, p[1]);
          y1 = Math.max(y1, p[1]);
        }));
        for (let i = 0; i < (o.ripples ?? 0); i++) {
          const u = r(), y = y0 + (y1 - y0) * u * u, L = (20 + r() * 150) * (0.3 + u), x = r() * this.w, c = water[Math.floor(r() * water.length)].c;
          g.fillStyle = c;
          g.fillRect(x, y, L, 1 + u * 2.4);
        }
        if (o.glitter) {
          g.fillStyle = o.glitter.color ?? "#fff3d6";
          for (let y = y0; y < y1; y += 3 + r() * 5) {
            const u = (y - y0) / (y1 - y0 || 1), hw = (o.glitter.w ?? 26) + u * (o.glitter.w ?? 26) * 3, n = 1 + Math.floor(r() * 2);
            for (let i = 0; i < n; i++) g.fillRect(o.glitter.x + (r() - 0.5) * 2 * hw, y, 4 + r() * 16 * (0.3 + u), 1 + u);
          }
        }
        g.restore();
      }
      solid.slice(0, Math.max(0, shown - water.length)).forEach((t) => put(t.s, t.c));
      if (wireP > 0) {
        const seq = [...water, ...solid], n = Math.floor(wireP * seq.length);
        g.strokeStyle = o.wireColor ?? "#8fa3c8";
        g.lineWidth = 0.7;
        g.globalAlpha = 0.55;
        g.beginPath();
        for (let i = shown; i < n; i++) {
          const s = seq[i].s;
          g.moveTo(s[0][0], s[0][1]);
          g.lineTo(s[1][0], s[1][1]);
          g.lineTo(s[2][0], s[2][1]);
          g.closePath();
        }
        g.stroke();
      }
      g.restore();
    }
    /** Baked once: for a camera that doesn't move. paint gets a context; draw(g) places the picture. */
    still(id, paint) {
      return this.plate(id, paint);
    }
    /** A sky of 2D facets: a jittered grid coloured by height, with stops = [[0, "#top"], ..., [1, "#low"]] and a warmer glow near sun = [x, y]. */
    sky(id, stops, o = {}) {
      const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, cell = o.cell ?? Math.round(Math.max(this.w, this.h) / 14), reach = o.reach ?? Math.max(this.w, this.h) * 0.42, ramp = (u) => {
        let i = 0;
        while (i < stops.length - 2 && u > stops[i + 1][0]) i++;
        const [a, ca] = stops[i], [e, cb] = stops[i + 1];
        return mixV(hex(ca), hex(cb), clamp01((u - a) / (e - a || 1)));
      };
      return this.plate(id, (c) => {
        c.fillStyle = rgb(ramp(0.5));
        c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
        const r = rng(o.seed ?? 12), nx = Math.ceil((b.x1 - b.x0) / cell) + 2, ny = Math.ceil((b.y1 - b.y0) / cell) + 2;
        const pt = Array.from({ length: ny + 1 }, (_, j) => Array.from({ length: nx + 1 }, (_2, i) => [b.x0 + (i - 1 + (r() - 0.5) * 0.7) * cell, b.y0 + (j - 1 + (r() - 0.5) * 0.7) * cell]));
        const tri = (A, B, C) => {
          const mx = (A[0] + B[0] + C[0]) / 3, my = (A[1] + B[1] + C[1]) / 3;
          let v = ramp(clamp01((my - b.y0) / (b.y1 - b.y0)));
          if (o.sun) v = mixV(v, hex(o.glow ?? "#ffd9a8"), 0.85 * Math.exp(-((Math.hypot(mx - o.sun[0], my - o.sun[1]) / reach) ** 2) * 2));
          const k = 0.985 + r() * 0.03, s = rgb(v.map((q) => q * k));
          c.fillStyle = s;
          c.strokeStyle = s;
          c.lineWidth = 0.8;
          c.beginPath();
          c.moveTo(A[0], A[1]);
          c.lineTo(B[0], B[1]);
          c.lineTo(C[0], C[1]);
          c.closePath();
          c.fill();
          c.stroke();
        };
        for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
          const a = pt[j][i], e = pt[j][i + 1], d = pt[j + 1][i + 1], f = pt[j + 1][i];
          if (r() < 0.5) {
            tri(a, e, d);
            tri(a, d, f);
          } else {
            tri(a, e, f);
            tri(e, d, f);
          }
        }
      }, b);
    }
    /** A faceted flat cloud, lit from below when `under` is warmer than `over`. */
    cloud(c, cx, cy, w, h, o = {}) {
      const r = rng(o.seed ?? 7), n = o.n ?? 9, top = Array.from({ length: n + 1 }, (_, i) => {
        const u = i / n;
        return [cx - w / 2 + w * u, cy - h * Math.sin(u * Math.PI) * (0.55 + r() * 0.5)];
      }), low = Array.from({ length: n + 1 }, (_, i) => [cx - w / 2 + w * i / n, cy + (r() - 0.5) * h * 0.14]), a = hex(o.under ?? "#f4b49b"), b = hex(o.over ?? "#8f7fa8");
      for (let i = 0; i < n; i++) {
        [[low[i], low[i + 1], top[i + 1]], [low[i], top[i + 1], top[i]]].forEach((t, k) => {
          const s = rgb(mixV(a, b, (k ? 0.75 : 0.25) + (r() - 0.5) * 0.3));
          c.fillStyle = s;
          c.strokeStyle = s;
          c.lineWidth = 0.7;
          c.beginPath();
          c.moveTo(t[0][0], t[0][1]);
          c.lineTo(t[1][0], t[1][1]);
          c.lineTo(t[2][0], t[2][1]);
          c.closePath();
          c.fill();
          c.stroke();
        });
      }
    }
    /** The empty viewport: a dark ground and a grid, where a modeller starts. */
    viewport(g, o = {}) {
      const gap = o.gap ?? Math.round(this.w / 20);
      g.save();
      g.fillStyle = o.bg ?? "#14171f";
      g.fillRect(0, 0, this.w, this.h);
      g.strokeStyle = o.line ?? "#262c3a";
      g.lineWidth = 1;
      g.beginPath();
      for (let x = 0; x <= this.w; x += gap) {
        g.moveTo(x, 0);
        g.lineTo(x, this.h);
      }
      for (let y = 0; y <= this.h; y += gap) {
        g.moveTo(0, y);
        g.lineTo(this.w, y);
      }
      g.stroke();
      g.restore();
    }
    finish(_g) {
    }
  };
  register("lowPoly", { start: (w, h, o) => new LowPolyHand(w, h, o) });
})();
