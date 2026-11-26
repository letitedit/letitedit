/* letitedit drawing hand: embroidery. Built from motion\runtime\looks-src (node build.mjs); don't edit this file.
 * Includes code from anidoodle (https://github.com/alexgreensh/anidoodle, commit 9c20e77), Copyright 2026 Alex Greenshpun, under the
 * Apache License 2.0: LICENSE-anidoodle.txt and NOTICE-anidoodle.txt beside this file. Changed by letitedit: see the headers in
 * looks-src. The rest is letitedit's own, GPL-3.0-or-later. Loaded into a code scene's page only when its script says M.look.embroidery. */
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
  var clamp2 = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  var lerp = (a, b, t) => a + (b - a) * t;
  var lerpP = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t)];
  var smooth = (pts, closed = false, per = 12) => sample(pts, closed, per);
  var hex = (h) => {
    const s = h.replace("#", "");
    return [0, 2, 4].map((i) => parseInt(s.slice(i, i + 2), 16));
  };
  var mix = (a, b, t) => {
    const x = hex(a), y = hex(b);
    return "#" + x.map((v, i) => Math.round(lerp(v, y[i], t)).toString(16).padStart(2, "0")).join("");
  };
  var polyLen = (s) => s.reduce((a, p, i) => i ? a + Math.hypot(p[0] - s[i - 1][0], p[1] - s[i - 1][1]) : 0, 0);
  var resample = (s, n) => {
    const cum = [0];
    for (let i = 1; i < s.length; i++) cum.push(cum[i - 1] + Math.hypot(s[i][0] - s[i - 1][0], s[i][1] - s[i - 1][1]));
    const L = cum[cum.length - 1], out = [];
    let j = 1;
    for (let k = 0; k < n; k++) {
      const d = L * k / (n - 1);
      while (j < s.length - 1 && cum[j] < d) j++;
      const f = (d - cum[j - 1]) / (cum[j] - cum[j - 1] || 1);
      out.push(lerpP(s[j - 1], s[j], clamp2(f)));
    }
    return out;
  };
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

  // motion/runtime/looks-src/anidoodle/embroideryKit.ts
  var LIGHT = [-0.6, -0.8];
  var linenLayer = (env, key, pitch, base, inside) => {
    const k = `emb:linen:${key}:${env.scale}:${env.W}x${env.H}:${pitch}`, hit = env.cache.get(k);
    if (hit) return hit;
    const DW = Math.round(env.W * env.scale), DH = Math.round(env.H * env.scale), L = env.canvas(DW, DH), img = L.ctx.createImageData(DW, DH), d = img.data;
    const nT = Math.ceil(Math.max(env.W, env.H) / pitch) + 2, r = rng(4411), thick = Array.from({ length: nT * 2 }, () => 0.8 + r() * 0.22), tint = Array.from({ length: nT * 2 }, () => (r() < 0.08 ? 0.95 : 1) * (0.975 + r() * 0.05));
    const SEG = 9, slub = Array.from({ length: nT * 2 }, () => Array.from({ length: Math.ceil(Math.max(env.W, env.H) / SEG) + 2 }, () => (r() < 0.04 ? 0.28 : 0) + (r() - 0.5) * 0.12));
    const sl = (th, along) => {
      const s = along / SEG, i = Math.floor(s), f = s - i, row = slub[th];
      return row[i] + (row[i + 1] - row[i]) * f;
    };
    for (let j = 0; j < DH; j++) {
      const y = j / env.scale, v = y / pitch, iv = Math.floor(v), fv = v - iv;
      for (let i = 0; i < DW; i++) {
        const x = i / env.scale, u = x / pitch, iu = Math.floor(u), fu = u - iu;
        const warpHW = 0.5 * clamp2(thick[iu] + sl(iu, y), 0.5, 1.15) * 0.94, weftHW = 0.5 * clamp2(thick[nT + iv] + sl(nT + iv, x), 0.5, 1.15) * 0.9;
        const dw = Math.abs(fu - 0.5), df = Math.abs(fv - 0.5), inWarp = dw < warpHW, inWeft = df < weftHW, warpTop = (iu + iv & 1) === 0;
        let b, t;
        if (inWarp && (warpTop || !inWeft)) {
          const cr = Math.cos(dw / warpHW * Math.PI * 0.5), rise = warpTop ? 0.82 + 0.18 * Math.sin(Math.PI * fv) : 0.74;
          b = (0.62 + 0.42 * Math.pow(cr, 0.7)) * rise + 0.06 * ((fv * 7 + iu * 0.37) % 1);
          t = tint[iu];
        } else if (inWeft) {
          const cr = Math.cos(df / weftHW * Math.PI * 0.5), rise = !warpTop ? 0.84 + 0.16 * Math.sin(Math.PI * fu) : 0.74;
          b = (0.6 + 0.42 * Math.pow(cr, 0.7)) * rise + 0.05 * ((fu * 6 + iv * 0.53) % 1);
          t = tint[nT + iv];
        } else {
          b = 0.5;
          t = 1;
        }
        const m = inside(x, y) * b * t, o = (j * DW + i) * 4;
        d[o] = clamp2(base[0] * m, 0, 255);
        d[o + 1] = clamp2(base[1] * m, 0, 255);
        d[o + 2] = clamp2(base[2] * m, 0, 255);
        d[o + 3] = 255;
      }
    }
    L.ctx.putImageData(img, 0, 0);
    env.cache.set(k, L);
    return L;
  };
  var tone = (c) => ({ base: c, hi: mix(c, "#ffffff", 0.5), lo: mix(c, "#1a120c", 0.38) });
  var headOf = (s, p) => s.k === "knot" ? s.a : p >= 1 ? s.b : lerpP(s.a, s.b, p);
  var drawShadows = (c, sts, lastP = 1) => {
    c.save();
    c.lineCap = "round";
    c.strokeStyle = "#3b2c1c";
    c.fillStyle = "#3b2c1c";
    sts.forEach((s, i) => {
      const p = i === sts.length - 1 ? lastP : 1;
      if (p <= 0) return;
      if (s.k === "knot") {
        if (p < 0.5) return;
        c.globalAlpha = 0.42;
        c.beginPath();
        c.arc(s.a[0] + s.w * 0.4, s.a[1] + s.w * 0.55, s.w * 1.05, 0, Math.PI * 2);
        c.fill();
        return;
      }
      const b = headOf(s, p);
      c.globalAlpha = 0.34;
      c.lineWidth = s.w * 1.1;
      c.beginPath();
      c.moveTo(s.a[0] + 0.9, s.a[1] + 1.3);
      c.lineTo(b[0] + 0.9, b[1] + 1.3);
      c.stroke();
    });
    c.restore();
  };
  var drawThreads = (c, sts, lastP = 1) => {
    c.save();
    c.lineCap = "round";
    c.lineJoin = "round";
    sts.forEach((s, i) => {
      const p = i === sts.length - 1 ? lastP : 1;
      if (p <= 0) return;
      const T = tone(s.c);
      if (s.k === "knot") {
        if (p < 0.5) {
          c.globalAlpha = 1;
          c.strokeStyle = T.base;
          c.lineWidth = s.w * 0.7;
          c.beginPath();
          c.arc(s.a[0], s.a[1], s.w * 0.55, 0, Math.PI * 2 * (p * 2));
          c.stroke();
          return;
        }
        const [x, y] = s.a, r = s.w;
        c.globalAlpha = 1;
        c.fillStyle = T.lo;
        c.beginPath();
        c.arc(x + r * 0.12, y + r * 0.16, r, 0, Math.PI * 2);
        c.fill();
        c.fillStyle = T.base;
        c.beginPath();
        c.arc(x - r * 0.1, y - r * 0.12, r * 0.8, 0, Math.PI * 2);
        c.fill();
        c.strokeStyle = T.lo;
        c.globalAlpha = 0.55;
        c.lineWidth = Math.max(0.5, r * 0.22);
        const ph = (x * 0.37 + y * 0.61) % Math.PI;
        c.beginPath();
        c.arc(x, y, r * 0.5, ph, ph + 2.2);
        c.stroke();
        c.beginPath();
        c.arc(x, y, r * 0.78, ph + 3, ph + 4.8);
        c.stroke();
        c.fillStyle = T.hi;
        c.globalAlpha = 0.8;
        c.beginPath();
        c.arc(x - r * 0.38, y - r * 0.42, r * 0.26, 0, Math.PI * 2);
        c.fill();
        return;
      }
      const a = s.a, b = headOf(s, p), dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L;
      let nx = -uy, ny = ux;
      if (nx * LIGHT[0] + ny * LIGHT[1] < 0) {
        nx = -nx;
        ny = -ny;
      }
      const w = s.w, sheen = 0.35 + 0.65 * Math.abs(ux * LIGHT[1] - uy * LIGHT[0]);
      const inset = Math.min(L * 0.3, w * 0.25), a1 = [a[0] + ux * inset, a[1] + uy * inset], b1 = [b[0] - ux * inset, b[1] - uy * inset];
      c.globalAlpha = 1;
      c.strokeStyle = T.base;
      c.lineWidth = w;
      c.beginPath();
      c.moveTo(a1[0], a1[1]);
      c.lineTo(b1[0], b1[1]);
      c.stroke();
      c.strokeStyle = T.base;
      c.lineWidth = w * 0.55;
      c.beginPath();
      c.moveTo(a[0], a[1]);
      c.lineTo(b[0], b[1]);
      c.stroke();
      c.strokeStyle = T.lo;
      c.globalAlpha = 0.6;
      c.lineWidth = w * 0.32;
      c.beginPath();
      c.moveTo(a1[0] - nx * w * 0.32, a1[1] - ny * w * 0.32);
      c.lineTo(b1[0] - nx * w * 0.32, b1[1] - ny * w * 0.32);
      c.stroke();
      const step = Math.max(1.6, w * 1.05), n = Math.floor(L / step);
      if (n > 0) {
        c.globalAlpha = 0.42;
        c.strokeStyle = T.lo;
        c.lineWidth = Math.max(0.45, w * 0.16);
        c.beginPath();
        for (let k = 1; k <= n; k++) {
          const m = k * step - step * 0.3, cx = a[0] + ux * m, cy = a[1] + uy * m, sx = (nx - ux * 0.7) * w * 0.42, sy = (ny - uy * 0.7) * w * 0.42;
          c.moveTo(cx - sx, cy - sy);
          c.lineTo(cx + sx, cy + sy);
        }
        c.stroke();
        c.globalAlpha = 0.28 + 0.5 * sheen;
        c.strokeStyle = T.hi;
        c.lineWidth = Math.max(0.45, w * 0.22);
        c.beginPath();
        for (let k = 0; k < n; k++) {
          const m = k * step + step * 0.25, cx = a[0] + ux * m + nx * w * 0.16, cy = a[1] + uy * m + ny * w * 0.16;
          c.moveTo(cx - ux * step * 0.22, cy - uy * step * 0.22);
          c.lineTo(cx + ux * step * 0.22, cy + uy * step * 0.22);
        }
        c.stroke();
      } else {
        c.globalAlpha = 0.3 + 0.5 * sheen;
        c.strokeStyle = T.hi;
        c.lineWidth = w * 0.25;
        c.beginPath();
        c.moveTo(a1[0] + nx * w * 0.16, a1[1] + ny * w * 0.16);
        c.lineTo(b1[0] + nx * w * 0.16, b1[1] + ny * w * 0.16);
        c.stroke();
      }
    });
    c.restore();
  };
  var flat = (a, b, w, c, t = 1) => ({ k: "flat", a, b, w, c, t });
  var knot = (a, r, c) => ({ k: "knot", a, b: a, w: r, c, t: 2.2 });
  var stemStitch = (path, len, w, c, seed) => {
    const L = polyLen(path), n = Math.max(2, Math.round(L / (len * 0.5))), s = resample(path, n + 2), r = rng(seed), out = [];
    for (let i = 0; i + 2 < s.length; i++) {
      const a = s[i], b = s[i + 2], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1, o = w * 0.28;
      out.push(flat([a[0] - dy / l * o, a[1] + dx / l * o], [b[0] + dy / l * o * 0.6 + (r() - 0.5) * 0.4, b[1] - dx / l * o * 0.6 + (r() - 0.5) * 0.4], w, c, 0.9));
    }
    return out;
  };
  var splitStitch = (path, len, w, c, closed = false) => {
    const pts = closed ? [...path, path[0]] : path, L = polyLen(pts), n = Math.max(2, Math.round(L / (len * 0.7))), s = resample(pts, n + 1), out = [];
    for (let i = 0; i + 1 < s.length; i++) {
      const a = i ? lerpP(s[i - 1], s[i], 0.62) : s[0];
      out.push(flat(a, s[i + 1], w, c, 0.9));
    }
    return out;
  };
  var runningStitch = (path, dash, gap, w, c) => {
    const L = polyLen(path), n = Math.max(2, Math.round(L / 1.5)), s = resample(path, n), out = [];
    let acc = 0, on = true, start = s[0];
    for (let i = 1; i < s.length; i++) {
      acc += Math.hypot(s[i][0] - s[i - 1][0], s[i][1] - s[i - 1][1]);
      if (on && acc >= dash) {
        out.push(flat(start, s[i], w, c, 0.8));
        on = false;
        acc = 0;
      } else if (!on && acc >= gap) {
        start = s[i];
        on = true;
        acc = 0;
      }
    }
    return out;
  };
  var straight = (a, b, w, c) => flat(a, b, w, c, 1);
  var satin = (axis, half, gap, w, colour, o = {}) => {
    const { skew = 0, split = 26 } = o, L = polyLen(axis), n = Math.max(2, Math.round(L / gap)), s = resample(axis, n), out = [];
    for (let i = 0; i < n; i++) {
      const t = i / (n - 1), p = s[i], q = s[Math.min(n - 1, i + 1)], pr = s[Math.max(0, i - 1)], dx = q[0] - pr[0], dy = q[1] - pr[1], l = Math.hypot(dx, dy) || 1, ux = dx / l, uy = dy / l, h = half(t);
      if (h < 0.6) continue;
      const e1 = [p[0] - uy * h + ux * skew * h, p[1] + ux * h + uy * skew * h], e2 = [p[0] + uy * h - ux * skew * h, p[1] - ux * h - uy * skew * h];
      if (2 * h > split) {
        out.push(flat(e1, lerpP(e1, e2, 0.5 + (i % 2 ? 0.04 : -0.04)), w, colour(t, -1)));
        out.push(flat(lerpP(e1, e2, 0.5 + (i % 2 ? 0.04 : -0.04)), e2, w, colour(t, 1)));
      } else out.push(flat(e1, e2, w, colour(t, 0)));
    }
    return out;
  };
  var fishbone = (mid, half, gap, w, colour) => {
    const L = polyLen(mid), n = Math.max(4, Math.round(L / gap)), s = resample(mid, n + 1), out = [];
    const edge = (i, side) => {
      const j = Math.min(n, i), p = s[j], q = s[Math.min(n, j + 1)], pr = s[Math.max(0, j - 1)], dx = q[0] - pr[0], dy = q[1] - pr[1], l = Math.hypot(dx, dy) || 1, h = half(j / n);
      return [p[0] - dy / l * h * side, p[1] + dx / l * h * side];
    };
    for (let i = 0; i < n; i++) for (const side of [-1, 1]) {
      const t = i / n, a = edge(i + Math.max(1, Math.round(n * 0.14)), side);
      if (half(Math.min(1, t + 0.14)) < 0.8) continue;
      out.push(flat(a, s[i], w, colour(side, t)));
    }
    return out;
  };
  var longShort = (edge, target, rows, gap, w, ramp, seed) => {
    const L = polyLen(edge), n = Math.max(3, Math.round(L / gap)), s = resample(edge, n), r = rng(seed), out = [];
    for (let row = 0; row < rows; row++) for (let i = 0; i < n; i++) {
      const e = s[i], tgt = target(e), jitter2 = (r() - 0.5) * 0.12, longOne = (i + row) % 2 === 0;
      const f0 = row === 0 ? 0 : (row - (longOne ? 0.35 : 0.1)) / rows + jitter2 * 0.3, f1 = row === rows - 1 ? 1 : (row + 1 + (longOne ? 0.2 : -0.15)) / rows + jitter2;
      const pick = clamp2((row + (r() - 0.5) * 1.1) / Math.max(1, rows - 1), 0, 1), c = ramp[Math.round(pick * (ramp.length - 1))];
      out.push(flat(lerpP(e, tgt, clamp2(f0)), lerpP(e, tgt, clamp2(f1)), w, c));
    }
    return out;
  };
  var knots = (cx, cy, rx, ry, r0, colour, seed) => {
    const r = rng(seed), out = [], step = r0 * 1.7;
    for (let y = -ry; y <= ry; y += step * 0.87) for (let x = -rx; x <= rx; x += step) {
      const px = x + Math.round((y + ry) / (step * 0.87)) % 2 * step / 2 + (r() - 0.5) * r0 * 0.5, py = y + (r() - 0.5) * r0 * 0.5;
      if ((px / rx) ** 2 + (py / ry) ** 2 > 1) continue;
      out.push(knot([cx + px, cy + py], r0 * (0.9 + r() * 0.2), colour(px / rx, py / ry)));
    }
    return out;
  };

  // motion/runtime/looks-src/anidoodle/scrapbookKit.ts
  var O = [[1.3, 0.1], [0.2, 1.3], [0.2, 4.7], [1.3, 5.9], [2.7, 5.9], [3.8, 4.7], [3.8, 1.3], [2.7, 0.1], [1.3, 0.1]];
  var GLYPHS = {
    A: { l: [[[0, 6], [2, 0], [4, 6]], [[0.8, 3.9], [3.2, 3.9]]] },
    B: { l: [[[0, 0], [0, 6]]], c: [[[0, 0], [2.6, 0], [3.5, 0.8], [3.5, 2.2], [2.6, 3], [0, 3]], [[2.6, 3], [3.8, 3.8], [3.8, 5.1], [2.8, 6], [0, 6]]] },
    C: { c: [[[3.8, 1.2], [2.8, 0.1], [1.3, 0.1], [0.2, 1.3], [0.2, 4.7], [1.3, 5.9], [2.8, 5.9], [3.8, 4.8]]] },
    D: { l: [[[0, 0], [0, 6]]], c: [[[0, 0], [2.3, 0], [3.8, 1.5], [3.8, 4.5], [2.3, 6], [0, 6]]] },
    E: { l: [[[3.6, 0], [0, 0], [0, 6], [3.7, 6]], [[0, 3], [2.8, 3]]] },
    F: { l: [[[3.6, 0], [0, 0], [0, 6]], [[0, 3], [2.8, 3]]] },
    G: { c: [[[3.8, 1.2], [2.8, 0.1], [1.3, 0.1], [0.2, 1.3], [0.2, 4.7], [1.3, 5.9], [2.8, 5.9], [3.8, 4.8]]], l: [[[3.8, 4.9], [3.8, 3.2], [2.2, 3.2]]] },
    H: { l: [[[0, 0], [0, 6]], [[4, 0], [4, 6]], [[0, 3], [4, 3]]] },
    I: { l: [[[1, 0], [1, 6]]], w: 2 },
    J: { c: [[[3.4, 0], [3.4, 4.8], [2.4, 5.9], [1.2, 5.9], [0.2, 4.8]]] },
    K: { l: [[[0, 0], [0, 6]], [[3.8, 0], [0, 3.7]], [[1.4, 2.5], [3.9, 6]]] },
    L: { l: [[[0, 0], [0, 6], [3.6, 6]]] },
    M: { l: [[[0, 6], [0, 0], [2.3, 3.8], [4.6, 0], [4.6, 6]]], w: 4.6 },
    N: { l: [[[0, 6], [0, 0], [4, 6], [4, 0]]] },
    O: { c: [O] },
    P: { l: [[[0, 0], [0, 6]]], c: [[[0, 0], [2.7, 0], [3.7, 0.9], [3.7, 2.4], [2.7, 3.3], [0, 3.3]]] },
    Q: { c: [O], l: [[[2.4, 4.2], [4.1, 6.3]]] },
    R: { l: [[[0, 0], [0, 6]], [[2, 3.3], [3.9, 6]]], c: [[[0, 0], [2.7, 0], [3.7, 0.9], [3.7, 2.4], [2.7, 3.3], [0, 3.3]]] },
    S: { c: [[[3.7, 1], [2.7, 0.1], [1.2, 0.1], [0.3, 1], [0.3, 2.1], [1.2, 2.9], [2.8, 3.2], [3.7, 4], [3.7, 5], [2.8, 5.9], [1.2, 5.9], [0.2, 5]]] },
    T: { l: [[[0, 0], [4, 0]], [[2, 0], [2, 6]]] },
    U: { c: [[[0, 0], [0, 4.7], [1.2, 5.9], [2.8, 5.9], [4, 4.7], [4, 0]]] },
    V: { l: [[[0, 0], [2, 6], [4, 0]]] },
    W: { l: [[[0, 0], [1.2, 6], [2.5, 2], [3.8, 6], [5, 0]]], w: 5 },
    X: { l: [[[0, 0], [4, 6]], [[4, 0], [0, 6]]] },
    Y: { l: [[[0, 0], [2, 3.1], [4, 0]], [[2, 3.1], [2, 6]]] },
    Z: { l: [[[0, 0], [4, 0], [0, 6], [4, 6]]] },
    "0": { c: [[[1.3, 0.1], [0.4, 1.2], [0.4, 4.8], [1.3, 5.9], [2.5, 5.9], [3.4, 4.8], [3.4, 1.2], [2.5, 0.1], [1.3, 0.1]]], w: 3.6 },
    "1": { l: [[[0.6, 1.2], [1.8, 0], [1.8, 6]]], w: 2.6 },
    "2": { c: [[[0.3, 1.3], [1.1, 0.2], [2.7, 0.2], [3.5, 1.1], [3.5, 2.2], [0.3, 6]]], l: [[[0.3, 6], [3.7, 6]]], w: 3.7 },
    "3": { c: [[[0.4, 0.9], [1.3, 0.1], [2.8, 0.1], [3.5, 1], [3.5, 2.1], [2.6, 3], [1.7, 3]], [[2.6, 3], [3.7, 3.8], [3.7, 5.1], [2.8, 5.9], [1.2, 5.9], [0.3, 5.1]]], w: 3.7 },
    "4": { l: [[[2.8, 6], [2.8, 0], [0.1, 4.3], [3.9, 4.3]]], w: 3.9 },
    "5": { l: [[[3.5, 0], [0.7, 0], [0.4, 2.8]]], c: [[[0.4, 2.8], [2.5, 2.5], [3.6, 3.6], [3.6, 5], [2.7, 5.9], [1, 5.9], [0.2, 5.1]]], w: 3.7 },
    "6": { c: [[[3.2, 0.4], [1.5, 0.2], [0.4, 1.4], [0.3, 4.7], [1.2, 5.9], [2.6, 5.9], [3.5, 5], [3.5, 3.8], [2.6, 2.9], [1.2, 2.9], [0.3, 3.8]]], w: 3.7 },
    "7": { l: [[[0.3, 0], [3.6, 0], [1.5, 6]]], w: 3.6 },
    "8": { c: [[[1.9, 0.1], [3, 0.4], [3.5, 1.3], [3.3, 2.2], [1.9, 3], [0.5, 2.2], [0.3, 1.3], [0.8, 0.4], [1.9, 0.1]], [[1.9, 3], [3.4, 3.7], [3.7, 4.6], [3.3, 5.5], [1.9, 5.9], [0.5, 5.5], [0.1, 4.6], [0.4, 3.7], [1.9, 3]]], w: 3.8 },
    "9": { c: [[[3.5, 2.5], [2.6, 3.2], [1.2, 3.2], [0.3, 2.3], [0.3, 1.1], [1.2, 0.1], [2.6, 0.1], [3.5, 1.1], [3.5, 4.6], [2.5, 5.8], [0.7, 5.8]]], w: 3.7 },
    "-": { l: [[[0.6, 3.2], [3, 3.2]]], w: 3.4 },
    ".": { l: [[[0.7, 5.5], [0.9, 5.9]]], w: 1.8 },
    ",": { l: [[[0.9, 5.4], [0.5, 6.8]]], w: 1.8 },
    ":": { l: [[[0.7, 2], [0.9, 2.4]], [[0.7, 5.4], [0.9, 5.8]]], w: 1.8 },
    "/": { l: [[[0.2, 6.4], [3.2, -0.2]]], w: 3.4 },
    "=": { l: [[[0.4, 2.3], [3.4, 2.3]], [[0.4, 4.1], [3.4, 4.1]]], w: 3.8 },
    "~": { c: [[[0.2, 3.6], [0.9, 2.7], [1.7, 3.1], [2.4, 3.6], [3.1, 3.4], [3.7, 2.6]]], w: 3.9 },
    "°": { c: [[[1, -0.1], [0.3, 0.5], [0.4, 1.4], [1.1, 1.8], [1.8, 1.3], [1.8, 0.4], [1, -0.1]]], w: 2.4 },
    "·": { l: [[[0.7, 3], [0.9, 3.35]]], w: 1.8 },
    "§": { c: [[[3.1, 0.7], [2.4, 0.05], [1.3, 0.1], [0.6, 0.8], [0.9, 1.7], [2.5, 2.4], [3.3, 3.3], [3, 4.2], [2.1, 4.5]], [[1.8, 1.55], [0.8, 2.1], [0.6, 3], [1.4, 3.7], [2.9, 4.4], [3.3, 5.2], [2.7, 5.9], [1.5, 5.95], [0.8, 5.3]]], w: 3.8 },
    "(": { c: [[[2, -0.4], [0.8, 1.6], [0.8, 4.6], [2, 6.6]]], w: 2.4 },
    ")": { c: [[[0.4, -0.4], [1.6, 1.6], [1.6, 4.6], [0.4, 6.6]]], w: 2.4 },
    "'": { l: [[[0.9, -0.2], [0.7, 1.6]]], w: 1.8 },
    "+": { l: [[[0.4, 3.2], [3.4, 3.2]], [[1.9, 1.7], [1.9, 4.7]]], w: 3.8 },
    " ": { w: 2.6 }
  };

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
  var register = (name, value) => {
    const M = window.M;
    (M.look = M.look || {})[name] = value;
  };

  // motion/runtime/looks-src/embroidery.ts
  var FLOSS = { sage: "#8ea57d", olive: "#6d7f42", moss: "#4c6336", white: "#f8f4e8", shell: "#f0dcc8", butter: "#f2d26a", ochre: "#cd9a3a", cornflower: "#5f7fc4", lavender: "#a48bc9", plum: "#6e4f94", coral: "#e0603f", oxblood: "#8a2b24", gold: "#c9a24a", umber: "#5a3f28", silver: "#c8ccd4", ink: "#2a2a35", teal: "#2f7f83" };
  var LINEN = [226, 212, 186];
  var STEP = 40;
  var Work = class {
    constructor(hand, sts, bx) {
      this.hand = hand;
      this.sts = sts;
      this.bx = bx;
    }
    hand;
    sts;
    bx;
    base;
    b;
    at = 0;
    all;
    get count() {
      return this.sts.length;
    }
    fresh() {
      const k = this.hand.scale, c = document.createElement("canvas");
      c.width = Math.ceil((this.bx.x1 - this.bx.x0) * k);
      c.height = Math.ceil((this.bx.y1 - this.bx.y0) * k);
      return c;
    }
    at0(c) {
      const k = this.hand.scale;
      c.setTransform(k, 0, 0, k, -this.bx.x0 * k, -this.bx.y0 * k);
    }
    lay(c, list, last = 1) {
      this.at0(c);
      drawShadows(c, list, last);
      drawThreads(c, list, last);
    }
    roll(n) {
      if (!this.base) {
        this.base = this.fresh();
        this.b = this.base.getContext("2d");
        this.at = 0;
      }
      if (n < this.at) {
        this.b.setTransform(1, 0, 0, 1, 0, 0);
        this.b.clearRect(0, 0, this.base.width, this.base.height);
        this.at = 0;
      }
      for (let i = this.at; i < n; i += STEP) this.lay(this.b, this.sts.slice(i, Math.min(n, i + STEP)));
      this.at = n;
    }
    whole() {
      if (!this.all) {
        this.all = this.fresh();
        const c = this.all.getContext("2d");
        for (let i = 0; i < this.sts.length; i += STEP) this.lay(c, this.sts.slice(i, i + STEP));
      }
      return this.all;
    }
    /** Where the needle is at this progress, and the angle of the stitch in hand. */
    head(p) {
      const f = Math.min(1, Math.max(0, p)) * this.sts.length, i = Math.min(this.sts.length - 1, Math.floor(f)), s = this.sts[i], q = headOf(s, f - i);
      return { x: q[0], y: q[1], a: Math.atan2(s.b[1] - s.a[1], s.b[0] - s.a[0]) };
    }
    /** progress 0..1 makes the stitches in order. needle: true shows it at the stitch in hand. Also x, y, alpha. */
    draw(g, o = {}) {
      const p = o.progress ?? 1, B = this.bx, w = B.x1 - B.x0, h = B.y1 - B.y0;
      if (p <= 0) return;
      g.save();
      if (o.x || o.y) g.translate(o.x ?? 0, o.y ?? 0);
      if (o.alpha !== void 0) g.globalAlpha *= o.alpha;
      if (p >= 1) g.drawImage(this.whole(), B.x0, B.y0, w, h);
      else {
        const f = p * this.sts.length, n = Math.floor(f), full = n - n % STEP;
        this.roll(full);
        g.drawImage(this.base, B.x0, B.y0, w, h);
        const rest = this.sts.slice(full, n + 1), q = f - n;
        drawShadows(g, rest, q);
        drawThreads(g, rest, q);
        if (o.needle !== false) {
          const H = this.head(p);
          this.hand.needle(g, H.x, H.y, H.a);
        }
      }
      g.restore();
    }
  };
  var EmbHand = class extends Hand {
    c = FLOSS;
    rng = rng;
    smooth = smooth;
    mix = mix;
    bounds = bounds;
    stem = stemStitch;
    split = splitStitch;
    running = runningStitch;
    satin = satin;
    fishbone = fishbone;
    longShort = longShort;
    knots = knots;
    knot = knot;
    straight = straight;
    flat = flat;
    threads = drawThreads;
    shadows = drawShadows;
    /** The cloth: plain weave computed per pixel once, with slubs, over and under crossings and pin-holes. pitch = thread spacing, tint = RGB. inside(x, y) 0..1 darkens it, for a folded edge. */
    linen(id = "linen", o = {}) {
      const pitch = o.pitch ?? 3.4, tint = o.tint ?? LINEN, ins = o.inside ?? (() => 1);
      return this.plate(id, (c) => {
        const L = linenLayer(this.env, id, pitch, tint, ins);
        c.save();
        c.setTransform(1, 0, 0, 1, 0, 0);
        c.drawImage(L.canvas, 0, 0);
        c.restore();
      });
    }
    /** A beech hoop with a brass screw at the top, its shadow falling on the cloth inside at upper left and outside at lower right. Returns a plate: draw it over the stitches. rx, ry = inner radius. */
    hoop(id, cx, cy, rx, ry = rx, o = {}) {
      const band = o.band ?? Math.min(rx, ry) * 0.075, wood = o.wood ?? "#c79f6d", pad = band * 3 + 30;
      return this.plate(id, (c) => {
        c.save();
        c.beginPath();
        c.ellipse(cx, cy, rx, ry, 0, 0, 6.2832);
        c.clip();
        const g = c.createLinearGradient(cx - rx, cy - ry, cx - rx * 0.4, cy - ry * 0.4);
        g.addColorStop(0, "rgba(40,28,14,.34)");
        g.addColorStop(1, "rgba(40,28,14,0)");
        c.fillStyle = g;
        c.fillRect(cx - rx, cy - ry, rx * 2, ry * 2);
        c.restore();
        c.save();
        c.globalAlpha = 0.28;
        c.strokeStyle = "#2a1c10";
        c.lineWidth = band * 1.1;
        c.beginPath();
        c.ellipse(cx + band * 0.5, cy + band * 0.8, rx + band * 0.9, ry + band * 0.9, 0, 0, 6.2832);
        c.stroke();
        c.restore();
        const ring = c.createLinearGradient(cx - rx, cy - ry, cx + rx, cy + ry);
        ring.addColorStop(0, mix(wood, "#ffffff", 0.32));
        ring.addColorStop(0.5, wood);
        ring.addColorStop(1, mix(wood, "#3a2410", 0.38));
        c.strokeStyle = ring;
        c.lineWidth = band;
        c.beginPath();
        c.ellipse(cx, cy, rx + band / 2, ry + band / 2, 0, 0, 6.2832);
        c.stroke();
        const r = rng(61);
        c.lineWidth = 0.7;
        for (let i = 0; i < 160; i++) {
          const a = r() * 6.2832, l = 0.02 + r() * 0.06, q = rx + band * (0.12 + r() * 0.76), qy = ry + band * (0.12 + r() * 0.76);
          c.strokeStyle = r() < 0.5 ? "rgba(90,60,28,.35)" : "rgba(255,235,200,.28)";
          c.beginPath();
          c.ellipse(cx, cy, q, qy, 0, a, a + l);
          c.stroke();
        }
        const bw = band * 1.5, by = cy - ry - band * 1.5;
        c.fillStyle = "#a88a4a";
        c.fillRect(cx - bw, by, bw * 2, band * 1.4);
        c.fillStyle = "#d9bd76";
        c.fillRect(cx - bw, by, bw * 2, band * 0.4);
        c.fillStyle = "#6e5a2c";
        c.fillRect(cx - bw * 1.4, by + band * 0.45, bw * 2.8, band * 0.5);
        c.fillStyle = "#cdb36f";
        c.beginPath();
        c.arc(cx + bw * 1.55, by + band * 0.7, band * 0.5, 0, 6.2832);
        c.fill();
      }, { x0: Math.max(0, cx - rx - pad), y0: Math.max(0, cy - ry - pad), x1: Math.min(this.w, cx + rx + pad), y1: Math.min(this.h, cy + ry + pad) });
    }
    /** A run of stitches, built once: build() returns a list (spread the lists of several generators, in the order they are made). box = {x0,y0,x1,y1} it stays inside, default the frame. */
    work(_id, build, box) {
      return new Work(this, build(), box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h });
    }
    /** The steel needle with its thread trailing, at the stitch in hand. */
    needle(g, x, y, a, thread = "#b9ad96") {
      const L = 46;
      g.save();
      g.translate(x, y);
      g.rotate(a - 2.2);
      g.strokeStyle = thread;
      g.globalAlpha *= 0.8;
      g.lineWidth = 1;
      g.beginPath();
      g.moveTo(L, 0);
      g.bezierCurveTo(L + 26, 16, L + 50, -6, L + 74, 18);
      g.stroke();
      const l = g.createLinearGradient(0, -1.6, 0, 1.6);
      l.addColorStop(0, "#f0f2f5");
      l.addColorStop(1, "#7f8690");
      g.fillStyle = l;
      g.beginPath();
      g.moveTo(0, 0);
      g.lineTo(L, -1.5);
      g.lineTo(L, 1.5);
      g.closePath();
      g.fill();
      g.restore();
    }
    /** Words in stem or split stitch, along stroked capitals. (x, y) = top-left of the capitals, cap = their height; returns a list of stitches. */
    words(text, x, y, cap, color, o = {}) {
      const s = cap / 6, out = [], w = o.w ?? Math.max(2, cap * 0.075), len = o.len ?? Math.max(5, cap * 0.16);
      let xx = x;
      for (const ch of text) {
        const g = GLYPHS[ch] ?? GLYPHS[ch.toUpperCase()] ?? GLYPHS["-"];
        const strokes = [...g.l ?? [], ...(g.c ?? []).map((st) => smooth(st, false, 6))];
        strokes.forEach((st, i) => {
          const q = st.map(([a, b]) => [xx + a * s, y + b * s]);
          out.push(...o.kind === "stem" ? stemStitch(q, len, w, color, i + 3) : splitStitch(q, len, w, color));
        });
        xx += ((g.w ?? 4) + (o.track ?? 1.5)) * s;
      }
      return out;
    }
    /** Stitches re-posed, not warped: each end moved around a pinned origin, more the further away. For a leaf that breathes. Returns a new list; draw it with E.live. */
    sway(sts, t, o) {
      const { origin: O2, amp = 0.03, period = 8, phase = 0 } = o, a = amp * Math.sin(t / period * 6.2832 + phase), c = Math.cos(a), si = Math.sin(a), T = ([x, y]) => [O2[0] + (x - O2[0]) * c - (y - O2[1]) * si, O2[1] + (x - O2[0]) * si + (y - O2[1]) * c];
      return sts.map((s) => ({ ...s, a: T(s.a), b: T(s.b) }));
    }
    /** Stitches drawn directly this frame, for a few that move. */
    live(g, sts) {
      drawShadows(g, sts);
      drawThreads(g, sts);
    }
    /** A soft lamp on the cloth and its grain, last thing in the frame. */
    finish(g, o = {}) {
      this.sheet(g, { paper: 0, vignette: o.vignette === void 0 ? "rgba(60,36,14,0.26)" : o.vignette });
    }
  };
  register("embroidery", { start: (w, h, o) => new EmbHand(w, h, o), floss: FLOSS });
})();
