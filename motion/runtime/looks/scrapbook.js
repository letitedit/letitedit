/* letitedit drawing hand: scrapbook. Built from motion\runtime\looks-src (node build.mjs); don't edit this file.
 * Includes code from anidoodle (https://github.com/alexgreensh/anidoodle, commit 9c20e77), Copyright 2026 Alex Greenshpun, under the
 * Apache License 2.0: LICENSE-anidoodle.txt and NOTICE-anidoodle.txt beside this file. Changed by letitedit: see the headers in
 * looks-src. The rest is letitedit's own, GPL-3.0-or-later. Loaded into a code scene's page only when its script says M.look.scrapbook. */
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
  var oval = (cx, cy, rx, ry = rx, n = 10, a0 = -1.9) => Array.from({ length: n }, (_, i) => {
    const a = a0 + i / n * Math.PI * 2;
    return [cx + Math.cos(a) * rx, cy + Math.sin(a) * ry];
  });
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
  var hatchRuns = (b, angle, gap, keep, step = 3, seed = 1) => {
    const c = Math.cos(angle), s = Math.sin(angle), cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2, R = Math.hypot(b.x1 - b.x0, b.y1 - b.y0) / 2 + gap, r = rng(seed), runs = [];
    for (let v = -R; v <= R; v += gap) {
      const off = (r() - 0.5) * gap * 0.35;
      let cur = [];
      for (let u = -R; u <= R; u += step) {
        const x = cx + u * c - (v + off) * s, y = cy + u * s + (v + off) * c;
        if (keep(x, y)) cur.push([x, y]);
        else if (cur.length) {
          if (cur.length > 1) runs.push(cur);
          cur = [];
        }
      }
      if (cur.length > 1) runs.push(cur);
    }
    return runs;
  };
  var inside = (pts, x, y) => {
    let k = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const a = pts[i], b = pts[j];
      if (a[1] > y !== b[1] > y && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) k = !k;
    }
    return k;
  };

  // motion/runtime/looks-src/anidoodle/scrapbookKit.ts
  var clamp01 = (v) => v <= 0 ? 0 : v >= 1 ? 1 : v;
  var easeOut = (t) => {
    const x = clamp01(t);
    return x >= 1 ? 1 : 1 - (1 - x) * (1 - x) * (1 - x);
  };
  var nrmC = (s) => s.map((_, i) => {
    const a = s[(i - 1 + s.length) % s.length], b = s[(i + 1) % s.length], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    return [dy / l, -dx / l];
  });
  var ring = (s) => s.reduce((a, p, i) => a + Math.hypot(p[0] - s[(i + 1) % s.length][0], p[1] - s[(i + 1) % s.length][1]), 0);
  var tear = (shape, amp, seed, grow = 0) => {
    const s = resample([...shape, shape[0]], Math.max(24, Math.round(ring(shape) / 2.4))).slice(0, -1), nr = nrmC(s), r = rng(seed);
    return s.map(([x, y], i) => {
      const d = (fractal(seed, x, y, 0.08, 0.08, 3) - 0.5) * amp * 2.2 + (r() - 0.5) * amp * 0.7 + grow;
      return [x + nr[i][0] * d, y + nr[i][1] * d];
    });
  };
  var scissor = (shape, seed, amt = 0.6) => {
    const s = resample([...shape, shape[0]], Math.max(16, Math.round(ring(shape) / 5))).slice(0, -1), r = rng(seed);
    return s.map(([x, y]) => [x + (r() - 0.5) * amt, y + (r() - 0.5) * amt]);
  };
  var path = (c, pts, close = true) => {
    c.beginPath();
    pts.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
    if (close) c.closePath();
  };
  var rect = (w, h, cx = 0, cy = 0) => [[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2], [cx + w / 2, cy + h / 2], [cx - w / 2, cy + h / 2]];
  var fibres = (c, shape, color, seed, density = 1, blotch = 0.22) => {
    const b = bounds(shape), r = rng(seed), area = (b.x1 - b.x0) * (b.y1 - b.y0);
    c.save();
    path(c, shape);
    c.clip();
    for (let i = 0; i < 6; i++) {
      const x = b.x0 + r() * (b.x1 - b.x0), y = b.y0 + r() * (b.y1 - b.y0), rx = 30 + r() * 110, g = c.createRadialGradient(x, y, 0, x, y, rx);
      const col = r() < 0.5 ? mix(color, "#ffffff", 0.25) : mix(color, "#6b4a22", 0.14);
      g.addColorStop(0, col);
      g.addColorStop(1, col + "00");
      c.globalAlpha = blotch;
      c.fillStyle = g;
      c.fillRect(x - rx, y - rx, rx * 2, rx * 2);
    }
    c.lineCap = "round";
    const n = Math.round(area / 1100 * density);
    for (let i = 0; i < n; i++) {
      const x = b.x0 + r() * (b.x1 - b.x0), y = b.y0 + r() * (b.y1 - b.y0), a = r() * Math.PI, l = 2 + r() * 7;
      c.strokeStyle = r() < 0.6 ? mix(color, "#fffdf4", 0.5) : mix(color, "#3a2410", 0.28);
      c.globalAlpha = 0.18 + r() * 0.25;
      c.lineWidth = 0.4 + r() * 0.5;
      c.beginPath();
      c.moveTo(x, y);
      c.quadraticCurveTo(x + Math.cos(a) * l * 0.5 + (r() - 0.5) * 2, y + Math.sin(a) * l * 0.5 + (r() - 0.5) * 2, x + Math.cos(a) * l, y + Math.sin(a) * l);
      c.stroke();
    }
    c.restore();
    c.globalAlpha = 1;
  };
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
  var glyphOf = (ch) => GLYPHS[ch] ?? GLYPHS[ch.toUpperCase()] ?? GLYPHS["-"];
  var advance = (ch, face) => (face.mono ?? glyphOf(ch).w ?? 4) * (face.wide ?? 1) + (face.track ?? 1.3);
  var measure = (text, cap, face) => [...text].reduce((a, ch) => a + advance(ch, face), 0) * (cap / 6) - (face.track ?? 1.3) * (cap / 6);
  var glyphStrokes = (ch, face) => {
    const gl = glyphOf(ch), out = [], sf = face.serif ?? 0;
    (gl.l ?? []).forEach((st) => {
      out.push(st);
      if (sf) [0, st.length - 1].forEach((e) => {
        const p = st[e], q = st[e === 0 ? 1 : st.length - 2];
        if ((p[1] <= 0.05 || p[1] >= 5.95) && Math.abs(q[0] - p[0]) < Math.abs(q[1] - p[1]) * 0.8) out.push([[p[0] - sf, p[1]], [p[0] + sf, p[1]]]);
      });
    });
    (gl.c ?? []).forEach((st) => out.push(sample(st, false, 6)));
    return out;
  };
  var glyph = (c, ch, x, y, cap, face, color, alpha = 1) => {
    const s = cap / 6, sl = face.slant ?? 0, wd = face.wide ?? 1, cx = face.mono ? (face.mono - (glyphOf(ch).w ?? 4)) / 2 : 0;
    const T = ([px, py]) => [x + ((px + cx) * wd + (6 - py) * sl) * s, y + py * s];
    const strokes = glyphStrokes(ch, face);
    c.lineCap = face.cap ?? "butt";
    c.lineJoin = face.join ?? "miter";
    c.miterLimit = 3;
    c.globalAlpha = alpha;
    const run = (w, col) => {
      c.lineWidth = w;
      c.strokeStyle = col;
      strokes.forEach((st) => {
        c.beginPath();
        st.forEach((p, i) => {
          const q = T(p);
          if (i) c.lineTo(q[0], q[1]);
          else c.moveTo(q[0], q[1]);
        });
        c.stroke();
      });
    };
    if (face.outline) {
      run(face.weight * cap + cap * 0.14, color);
      run(face.weight * cap, face.outline);
    } else run(face.weight * cap, color);
    c.globalAlpha = 1;
  };
  var TYPEWRITER = { weight: 0.1, serif: 0.55, mono: 4.2, track: 0.9, cap: "butt", join: "round" };
  var typed = (c, text, x, y, cap, color, seed, n = Infinity) => {
    const r = rng(seed), s = cap / 6;
    let cx = x;
    [...text].forEach((ch, i) => {
      const dens = 0.72 + r() * 0.28, dy = (r() - 0.5) * cap * 0.06, dx = (r() - 0.5) * cap * 0.03;
      if (i < n && ch !== " ") {
        glyph(c, ch, cx + dx + 0.35, y + dy + 0.25, cap, TYPEWRITER, color, dens * 0.3);
        glyph(c, ch, cx + dx, y + dy, cap, TYPEWRITER, color, dens);
      }
      cx += advance(ch, TYPEWRITER) * s;
    });
  };
  var ribbonFill = (c, s, w, tip = 3) => {
    const n = s.length, L = [], R = [];
    for (let i = 0; i < n; i++) {
      const a = s[Math.max(0, i - 1)], b = s[Math.min(n - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1, e = Math.min(1, (i + 0.6) / tip, (n - i - 0.4) / tip), h = w[i] * e / 2;
      L.push([s[i][0] - dy / l * h, s[i][1] + dx / l * h]);
      R.push([s[i][0] + dy / l * h, s[i][1] - dx / l * h]);
    }
    c.beginPath();
    L.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
    for (let i = n - 1; i >= 0; i--) c.lineTo(R[i][0], R[i][1]);
    c.closePath();
    c.fill();
  };
  var burin = (c, cut, min = 0.16, upto = 1) => {
    const m = upto >= 1 ? cut.pts.length : Math.max(0, Math.floor(cut.pts.length * upto));
    let run = [];
    const flush = () => {
      if (run.length >= 2) ribbonFill(c, run.map((i) => cut.pts[i]), run.map((i) => cut.w[i]));
      run = [];
    };
    for (let i = 0; i < m; i++) {
      if (cut.w[i] > min) run.push(i);
      else flush();
    }
    flush();
  };
  var dense = (pts, step = 2) => {
    let L = 0;
    for (let i = 1; i < pts.length; i++) L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    return resample(pts, Math.max(2, Math.round(L / step) + 1));
  };
  var inPoly = (pts, x, y) => {
    let k = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const a = pts[i], b = pts[j];
      if (a[1] > y !== b[1] > y && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) k = !k;
    }
    return k;
  };
  var hidden = (occ, x, y) => occ.some((o) => x >= o.b.x0 && x <= o.b.x1 && y >= o.b.y0 && y <= o.b.y1 && inPoly(o.pts, x, y));
  var cutLine = (pts, width, occ = [], step = 2) => {
    const d = dense(pts, step);
    return { pts: d, w: d.map(([x, y], i) => hidden(occ, x, y) ? 0 : width(x, y, i, d.length)) };
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

  // motion/runtime/looks-src/scrapbook.ts
  var INK = "#2a2019";
  var NAVY = "#22335a";
  var RED = "#b8322a";
  var REDPEN = "#c23a2a";
  var TEAL = "#4f8f8a";
  var PINK = "#d9a5a0";
  var MUSTARD = "#d6a13c";
  var PARCH = "#e8d6b2";
  var FACES = [{ weight: 0.2 }, { weight: 0.15, serif: 0.9 }, { weight: 0.12, outline: "" }, { weight: 0.14, slant: 0.22 }, { weight: 0.075, serif: 0.7, wide: 0.78 }, { weight: 0.17, wide: 1.25 }, { weight: 0.16, cap: "round", join: "round" }, { weight: 0.11, serif: 1, slant: 0.12 }];
  var PAIRS = [[NAVY, "#f3ead6"], [TEAL, "#1c1a18"], ["#f1e9d8", "#1c1a18"], [PINK, NAVY], [RED, "#f6ecd9"], [MUSTARD, "#1c1a18"], ["#d8d2c4", "#1c1a18"], ["#1d1b19", "#efe6d0"], ["#e9c9b4", RED]];
  var STRIKE = { weight: 0.1, mono: 4.2, track: 0.9 };
  var lay = (t, t0, dur, from = [0, -60]) => {
    if (t < t0) return { ...REST, shown: false, alpha: 0 };
    const e = easeOut((t - t0) / dur);
    return { dx: from[0] * (1 - e), dy: from[1] * (1 - e), rot: 0.03 * (1 - e), lift: (1 - e) * (1 - e), shown: true, alpha: clamp01((t - t0) / 0.14) };
  };
  var ScrapHand = class extends Hand {
    fibres = fibres;
    tear = tear;
    scissor = scissor;
    smooth = smooth;
    path = path;
    rect = rect;
    bounds = bounds;
    mix = mix;
    rng = rng;
    oval = oval;
    fractal = fractal;
    inside = inside;
    typedLine = typed;
    glyph = glyph;
    measure = measure;
    advance = advance;
    burin = burin;
    cutLine = cutLine;
    hatchRuns = hatchRuns;
    lay = lay;
    TYPEWRITER = TYPEWRITER;
    clamp01 = clamp01;
    palette = { parchment: PARCH, ink: INK, teal: TEAL, pink: PINK, stamp: RED, redPen: REDPEN, navy: NAVY, mustard: MUSTARD, card: "#f2eadb", cardCool: "#c9d9d5", cardWarm: "#efe5cf", tape: "#efe0a8", twine: "#7a6446" };
    /** The sheet everything lies on: parchment with broad age clouds, handled edges, a fold, a tide mark and drifts of foxing. box may be far larger than the frame, for a camera to travel over. */
    page(id = "page", o = {}) {
      const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, W = b.x1 - b.x0, H = b.y1 - b.y0, col = o.color ?? PARCH, seed = o.seed ?? 301, foldY = o.fold === null ? null : o.fold ?? b.y0 + H * 0.56;
      return this.plate(id, (c) => {
        const r = rng(seed);
        c.fillStyle = col;
        c.fillRect(b.x0, b.y0, W, H);
        const clouds = Math.max(14, Math.round(W * H / 15e4));
        for (let i = 0; i < clouds; i++) {
          const x = b.x0 + r() * W, y = b.y0 + r() * H, R = 120 + r() * 260, gr = c.createRadialGradient(x, y, 0, x, y, R), tone = r() < 0.55 ? "#f4e7c9" : "#caa874";
          gr.addColorStop(0, tone);
          gr.addColorStop(1, tone + "00");
          c.globalAlpha = 0.28;
          c.fillStyle = gr;
          c.fillRect(x - R, y - R, R * 2, R * 2);
        }
        const edge = (x0, y0, x1, y1) => {
          const gr = c.createLinearGradient(x0, y0, x1, y1);
          gr.addColorStop(0, "rgba(120,78,30,0.34)");
          gr.addColorStop(1, "rgba(120,78,30,0)");
          c.globalAlpha = 1;
          c.fillStyle = gr;
          c.fillRect(b.x0, b.y0, W, H);
        };
        edge(b.x0, b.y0, b.x0 + 60, b.y0);
        edge(b.x1, b.y0, b.x1 - 70, b.y0);
        edge(b.x0, b.y0, b.x0, b.y0 + 55);
        edge(b.x0, b.y1, b.x0, b.y1 - 80);
        const tx = b.x0 + W * 0.57, ty = b.y0 + H * 0.82;
        c.globalAlpha = 0.16;
        c.strokeStyle = "#9a6a30";
        c.lineWidth = 2.2;
        path(c, smooth(Array.from({ length: 16 }, (_, i) => {
          const a = i / 16 * 6.28, k = 1 + (fractal(9, Math.cos(a) * 2, Math.sin(a) * 2, 0.8, 0.8, 2) - 0.5) * 0.25;
          return [tx + Math.cos(a) * W * 0.17 * k, ty + Math.sin(a) * H * 0.1 * k];
        }), true, 6));
        c.stroke();
        if (foldY !== null) {
          c.globalAlpha = 0.22;
          c.strokeStyle = "#fff6df";
          c.lineWidth = 3;
          c.beginPath();
          c.moveTo(b.x0, foldY);
          c.bezierCurveTo(b.x0 + W * 0.28, foldY - 4, b.x0 + W * 0.65, foldY + 5, b.x1, foldY - 1);
          c.stroke();
          c.globalAlpha = 0.16;
          c.strokeStyle = "#7a5424";
          c.lineWidth = 1.2;
          c.beginPath();
          c.moveTo(b.x0, foldY + 2.5);
          c.bezierCurveTo(b.x0 + W * 0.28, foldY - 1.5, b.x0 + W * 0.65, foldY + 7.5, b.x1, foldY + 1.5);
          c.stroke();
        }
        const drift = (cx, cy, sx, sy, n, big) => {
          for (let i = 0; i < n; i++) {
            const x = cx + (r() + r() - 1) * sx, y = cy + (r() + r() - 1) * sy, s = (0.6 + r() * r() * big) * 2.2;
            c.globalAlpha = 0.18 + r() * 0.35;
            c.fillStyle = r() < 0.7 ? "#9a6a30" : "#7a4a1e";
            c.beginPath();
            c.arc(x, y, s, 0, 6.28);
            c.fill();
          }
        };
        const spots = Math.max(1, Math.round(W * H / 11e5));
        for (let i = 0; i < spots; i++) {
          drift(b.x0 + r() * W, b.y0 + r() * H, 40 + r() * 80, 40 + r() * 160, 18 + Math.round(r() * 20), 3);
        }
        drift(b.x1 - 35, b.y0 + H * 0.3, 30, 220, 38, 3);
        drift(b.x0 + 60, b.y1 - 70, 70, 60, 34, 4);
        c.globalAlpha = 1;
      }, b);
    }
    /** A card torn from other stock, centred at (x, y): deckle edge, fibres, darkened rim, and your own content in face(c), drawn in the card's local space (0, 0 is its centre). Lay it with S.lay. */
    card(id, o) {
      const { x, y, w, h, rot = 0, color = this.palette.card, torn = 2.4, depth = 5 } = o, seed = o.seed ?? (w * 7 + h * 3) % 997, cr = Math.cos(rot), sr = Math.sin(rot), s = tear(rect(w, h), torn, seed).map(([px, py]) => [x + px * cr - py * sr, y + px * sr + py * cr]);
      return this.piece(id, { cut: s, depth, shadow: "#3b2a14", pivot: [x, y], face: (c) => {
        c.fillStyle = color;
        path(c, s);
        c.fill();
        fibres(c, s, color, seed + 5, 0.8, 0.28);
        c.strokeStyle = mix(color, "#7a5a30", 0.35);
        c.globalAlpha = 0.35;
        c.lineWidth = 1.2;
        path(c, s);
        c.stroke();
        c.globalAlpha = 1;
        if (o.face) {
          c.save();
          c.translate(x, y);
          c.rotate(rot);
          o.face(c);
          c.restore();
          c.globalAlpha = 1;
        }
      } });
    }
    /** A photo print on the card: a white border, a little darkening at its edges, tape on top if you add it. image: a loaded Image or canvas (a scene loads its own, see the guide). fit: cover. */
    print(c, image, x, y, w, h, o = {}) {
      const b = o.border ?? Math.round(Math.min(w, h) * 0.05);
      c.save();
      c.fillStyle = "#f7f3ea";
      c.fillRect(x - w / 2, y - h / 2, w, h);
      const iw = w - b * 2, ih = h - b * 2, k = Math.max(iw / image.width, ih / image.height), sw = iw / k, sh = ih / k;
      c.drawImage(image, (image.width - sw) / 2, (image.height - sh) / 2, sw, sh, x - iw / 2, y - ih / 2, iw, ih);
      c.globalCompositeOperation = "multiply";
      c.globalAlpha = o.toneAlpha ?? 0.18;
      c.fillStyle = o.tone ?? "#b08a54";
      c.fillRect(x - iw / 2, y - ih / 2, iw, ih);
      c.restore();
    }
    /** Cellulose tape: yellowed, see-through, torn at each end, centred at `at`. draw(g, {reveal}) with reveal 0..1 lays it from one end. */
    tape(id, at, ang, len, seed = 1) {
      const h = 30, r = rng(seed), co = Math.cos(ang), si = Math.sin(ang), T = ([x, y]) => [at[0] + x * co - y * si, at[1] + x * si + y * co], top = [], bot = [];
      for (let k = 0; k <= 5; k++) top.push([-len / 2 + (r() - 0.5) * 3, -h / 2 + k * h / 5]);
      for (let k = 5; k >= 0; k--) bot.push([len / 2 + (k % 2 ? 3 : -2), -h / 2 + k * h / 5]);
      const sh = [...top, ...bot].map(T), piece = this.piece(id, { cut: sh, depth: 1.5, shadow: "#3b2a14", pivot: at, face: (c) => {
        c.globalAlpha = 0.5;
        c.fillStyle = "#efe0a8";
        path(c, sh);
        c.fill();
        c.globalAlpha = 0.28;
        c.fillStyle = "#fffbe8";
        path(c, [[-len / 2 + 4, -h / 2 + 4], [len / 2 - 4, -h / 2 + 4], [len / 2 - 4, -h / 2 + 8], [-len / 2 + 4, -h / 2 + 9]].map(T));
        c.fill();
        c.globalAlpha = 0.18;
        c.strokeStyle = "#8a6a2a";
        c.lineWidth = 0.7;
        for (let k = 0; k < 3; k++) {
          const x = -len / 2 + 12 + r() * (len - 20), a = T([x, -h / 2 + 2]), b = T([x + (r() - 0.5) * 10, h / 2 - 2]);
          c.beginPath();
          c.moveTo(a[0], a[1]);
          c.lineTo(b[0], b[1]);
          c.stroke();
        }
        c.globalAlpha = 1;
      } });
      return { piece, draw: (g, o = {}) => {
        const p = easeOut(o.reveal ?? 1);
        if (p <= 0) return;
        if (p >= 1) {
          piece.draw(g);
          return;
        }
        g.save();
        g.translate(at[0], at[1]);
        g.rotate(ang);
        g.beginPath();
        g.rect(-len / 2 - 6, -h, (len + 12) * p, h * 2);
        g.rotate(-ang);
        g.translate(-at[0], -at[1]);
        g.clip();
        piece.draw(g);
        g.restore();
      } };
    }
    /** A slip of paper with a typed line. draw(g, {pose, n}) with n = characters struck so far (M.typed gives it). Each strike its own density and a hair off the line. */
    strip(id, text, o) {
      const { x, y, cap = 20, rot = 0, color = "#f7f2e8", seed = text.length * 37 % 997, ink = "#221d1a" } = o, w = measure(text, cap, STRIKE), s = tear(rect(w + cap * 1.6, cap * 2.3), 1.2, seed), ca = Math.cos(rot), sa = Math.sin(rot), sh = s.map(([px, py]) => [x + px * ca - py * sa, y + px * sa + py * ca]);
      const paper = this.piece(id, { cut: sh, depth: 3, shadow: "#3b2a14", pivot: [x, y], face: (c) => {
        c.fillStyle = color;
        path(c, sh);
        c.fill();
        fibres(c, sh, color, seed, 0.6, 0.15);
      } });
      const full = this.plate(id + ":typed", (c) => {
        c.translate(x, y);
        c.rotate(rot);
        typed(c, text, -w / 2, -cap / 2, cap, ink, seed);
      }, { x0: x - w, y0: y - w - cap, x1: x + w, y1: y + w + cap });
      return { paper, width: w, draw: (g, d = {}) => {
        const q = d.pose ?? REST, n = d.n ?? Infinity;
        paper.draw(g, { pose: q });
        if (n <= 0) return;
        if (n >= text.length) {
          full.draw(g, { x: q.dx, y: q.dy });
          return;
        }
        g.save();
        g.translate(x + q.dx, y + q.dy);
        g.rotate(rot);
        typed(g, text, -w / 2, -cap / 2, cap, ink, seed, n);
        g.restore();
      } };
    }
    /** Each letter cut from a different printed page and pasted: a word as tiles. draw(g, t, t0, {each, dur}) pastes them one by one. */
    ransom(id, word, o) {
      if (o.cx !== void 0) {
        const { cx, ...rest } = o;
        return this.ransom(id, word, { ...rest, x: cx - this.ransom(`${id}:measure`, word, { ...rest, x: 0 }).width / 2 });
      }
      const ox = o.x ?? 0;
      const cap0 = o.cap ?? 50, seed = o.seed ?? 91, r = rng(seed), tiles = [];
      let x = ox, lastP = -1, lastF = -1, n = 0;
      [...word].forEach((ch, i) => {
        if (ch === " ") {
          x += cap0 * 0.6;
          return;
        }
        let pi = Math.floor(r() * PAIRS.length);
        if (pi === lastP) pi = (pi + 3) % PAIRS.length;
        let fi = Math.floor(r() * FACES.length);
        if (fi === lastF) fi = (fi + 2) % FACES.length;
        lastP = pi;
        lastF = fi;
        const [bg, fg] = PAIRS[pi], face = { ...FACES[fi] };
        if (face.outline !== void 0) face.outline = bg;
        const cap = cap0 * (0.84 + r() * 0.3), gw = ((GLYPHS[ch.toUpperCase()]?.w ?? 4) * (face.wide ?? 1) + 6 * (face.slant ?? 0)) * (cap / 6), w = gw + cap * (0.5 + r() * 0.25), cx = x + w / 2, cy = o.y + (r() - 0.5) * cap0 * 0.22, rot = (r() - 0.5) * 0.2, news = r() < 0.4, s0 = seed * 10 + i, q = rng(s0), hw = gw + cap * 0.55, hh = cap * (1.5 + q() * 0.2), base = [[-hw / 2 + (q() - 0.5) * 4, -hh / 2 + (q() - 0.5) * 4], [hw / 2 + (q() - 0.5) * 4, -hh / 2 + (q() - 0.5) * 4], [hw / 2 + (q() - 0.5) * 4, hh / 2 + (q() - 0.5) * 4], [-hw / 2 + (q() - 0.5) * 4, hh / 2 + (q() - 0.5) * 4]], local = scissor(base, s0, 0.8), ca = Math.cos(rot), sa = Math.sin(rot), sh = local.map(([a, b]) => [cx + a * ca - b * sa, cy + a * sa + b * ca]);
        const p = this.piece(`${id}:${i}`, { cut: sh, depth: 3, shadow: "#3b2a14", pivot: [cx, cy], face: (c) => {
          c.fillStyle = bg;
          path(c, sh);
          c.fill();
          fibres(c, sh, bg, s0, 0.6, 0.18);
          c.save();
          c.translate(cx, cy);
          c.rotate(rot);
          if (news) {
            const rr = rng(s0 + 9), b = bounds(local);
            c.save();
            path(c, local);
            c.clip();
            c.globalAlpha = 0.3;
            c.fillStyle = fg;
            for (let yy = b.y0 + 3; yy < b.y1; yy += 5) {
              let xx = b.x0 + 2;
              while (xx < b.x1) {
                const l = 3 + rr() * 14;
                c.fillRect(xx, yy, l, 1.4);
                xx += l + 3;
              }
            }
            c.restore();
            c.globalAlpha = 0.8;
            c.fillStyle = bg;
            c.fillRect(-gw / 2 - cap * 0.1, -cap / 2 - cap * 0.1, gw + cap * 0.2, cap * 1.2);
            c.globalAlpha = 1;
          }
          glyph(c, ch.toUpperCase(), -gw / 2, -cap / 2, cap, face, fg);
          c.restore();
          c.globalAlpha = 1;
        } });
        tiles.push({ p, ch });
        x += w + 3 + r() * 6;
        n++;
      });
      return { width: x - ox, tiles, draw: (g, t, t0, d = {}) => {
        const each = d.each ?? 0.07, dur = d.dur ?? 0.22;
        tiles.forEach((tl, i) => {
          const st = t0 + i * each;
          if (t < st) return;
          tl.p.draw(g, { pose: lay(t, st, dur, [-6, -22]) });
        });
      } };
    }
    /** Red pen or any ink: a wobbling, tapering line through pts. progress 0..1 is the nib travelling. */
    redPen(g, pts, o = {}) {
      this.pen(g, smooth(pts, false, 10), { w: o.w ?? 3, color: o.color ?? REDPEN, seed: o.seed ?? 3, wobble: o.wobble ?? 0.6, taper: 0.5, opacity: 0.92, progress: o.progress ?? 1 });
    }
    /** A ring drawn round something, overshooting where it closes. */
    ring(g, cx, cy, rx, ry, o = {}) {
      const pts = Array.from({ length: 15 }, (_, i) => {
        const a = -2.4 + i / 12.5 * Math.PI * 2, k = 1 + i * 8e-3;
        return [cx + Math.cos(a) * rx * k, cy + Math.sin(a) * ry * k];
      });
      this.redPen(g, pts, { w: o.w ?? 3.4, color: o.color, seed: o.seed, progress: o.progress });
    }
    /** Handwritten words in that pen, stroke by stroke; progress 0..1. */
    handWrite(g, text, x, y, cap, o = {}) {
      const s = cap / 6, slant = o.slant ?? 0.22, seed = o.seed ?? 5, r = rng(seed * 17 + 3), all = [];
      let cx = x;
      [...text.toUpperCase()].forEach((ch) => {
        const gl = GLYPHS[ch] ?? GLYPHS["-"], k = 1 + (r() - 0.5) * 0.12, dy = (r() - 0.5) * cap * 0.1, T = ([px, py]) => [cx + (px + (6 - py) * slant) * s * k, y + dy + py * s * k];
        (gl.l ?? []).forEach((st) => all.push(st.map(T)));
        (gl.c ?? []).forEach((st) => all.push(smooth(st, false, 6).map(T)));
        cx += ((gl.w ?? 4) * 0.92 + 1.1) * s;
      });
      let left = (o.progress ?? 1) >= 1 ? Infinity : (o.progress ?? 1) * all.length;
      all.forEach((st, i) => {
        const p = left === Infinity ? 1 : clamp01(left);
        if (left !== Infinity) left -= 1;
        if (p > 0) this.pen(g, st, { w: o.w ?? 2.2, color: o.color ?? REDPEN, seed: seed + i * 7, wobble: 0.45, taper: 0.5, opacity: 0.92, progress: p });
      });
      return cx - x;
    }
    /** A rubber stamp: a double border and words, the ink broken and multiplied. Stamps down with draw(g, {s, alpha}). */
    stamp(id, text, o) {
      const { x, y, cap = 26, rot = -0.14, color = RED, seed = 77 } = o, f = { weight: 0.15, serif: 0.5, wide: 1.1 }, w = measure(text, cap, f) + cap * 1.8, h = cap * 2.5, R = Math.hypot(w, h) / 2 + 8;
      return this.plate(id, (c) => {
        c.save();
        c.translate(x, y);
        c.rotate(rot);
        c.globalCompositeOperation = "source-over";
        c.strokeStyle = color;
        c.fillStyle = color;
        c.lineWidth = 4;
        c.strokeRect(-w / 2, -h / 2, w, h);
        c.lineWidth = 1.5;
        c.strokeRect(-w / 2 + 7, -h / 2 + 7, w - 14, h - 14);
        let px = -measure(text, cap, f) / 2;
        [...text].forEach((ch) => {
          glyph(c, ch, px, -cap / 2, cap, f, color);
          px += advance(ch, f) * (cap / 6);
        });
        c.restore();
        const r = rng(seed);
        c.globalCompositeOperation = "destination-out";
        for (let i = 0; i < w * h * 0.03; i++) {
          const a = r() * 6.28, d = Math.sqrt(r()) * R;
          c.globalAlpha = 0.25 + r() * 0.65;
          c.beginPath();
          c.arc(x + Math.cos(a) * d, y + Math.sin(a) * d, 0.5 + r() * r() * 2.4, 0, 6.28);
          c.fill();
        }
        c.globalCompositeOperation = "source-over";
        c.globalAlpha = 1;
      }, { x0: x - R, y0: y - R, x1: x + R, y1: y + R }, [x, y]);
    }
    /** Twine between points with a brass tack at the start: a plate. */
    twine(id, pts) {
      const s = smooth(pts, false, 12), b = bounds(s);
      return this.plate(id, (c) => {
        const G = this;
        c.save();
        c.globalAlpha = 0.3;
        G.pen(c, s.map(([x, y]) => [x + 1.5, y + 3]), { w: 2, color: "#3b2a14", seed: 3, wobble: 0, taper: 0, opacity: 1 });
        c.restore();
        G.pen(c, s, { w: 2.1, color: this.palette.twine, seed: 4, wobble: 0.3, taper: 0, opacity: 1 });
        c.strokeStyle = "#4c3a24";
        c.lineWidth = 0.7;
        c.globalAlpha = 0.6;
        for (let i = 2; i < s.length; i += 3) {
          const [x, y] = s[i];
          c.beginPath();
          c.moveTo(x - 1.2, y - 1.2);
          c.lineTo(x + 1.2, y + 1.2);
          c.stroke();
        }
        c.globalAlpha = 1;
        const [px, py] = pts[0], gr = c.createRadialGradient(px - 2, py - 2, 0.5, px, py, 6.5);
        gr.addColorStop(0, "#f3dc9a");
        gr.addColorStop(0.5, "#c49a45");
        gr.addColorStop(1, "#7a5a22");
        c.fillStyle = gr;
        c.beginPath();
        c.arc(px, py, 6.5, 0, 6.28);
        c.fill();
      }, { x0: b.x0 - 20, y0: b.y0 - 20, x1: b.x1 + 20, y1: b.y1 + 20 });
    }
    /** A wooden clothespin standing at (x, y), for a card hung on twine. */
    peg(id, x, y, a = 0.05) {
      const co = Math.cos(a), si = Math.sin(a), T = ([u, v]) => [x + u * co - v * si, y + u * si + v * co], half = (sg) => [[sg * 1, -40], [sg * 10, -40], [sg * 11, -30], [sg * 9, -6], [sg * 12, 14], [sg * 11, 40], [sg * 1, 40]].map(T);
      return this.piece(id, { cut: [half(-1), half(1)], depth: 4, shadow: "#3b2a14", pivot: [x, y], face: (c) => {
        [-1, 1].forEach((sg) => {
          const sh = half(sg);
          c.fillStyle = sg < 0 ? "#d9b88a" : "#c9a577";
          path(c, sh);
          c.fill();
          c.strokeStyle = "#8a6a44";
          c.lineWidth = 0.6;
          c.globalAlpha = 0.5;
          for (let k = 0; k < 3; k++) {
            const u = sg * (3 + k * 2.6), a1 = T([u, -38]), b1 = T([u + sg * 0.8, 38]);
            c.beginPath();
            c.moveTo(a1[0], a1[1]);
            c.lineTo(b1[0], b1[1]);
            c.stroke();
          }
          c.globalAlpha = 1;
        });
        c.strokeStyle = "#5b5f63";
        c.lineWidth = 1.6;
        for (let k = 0; k < 4; k++) {
          const a1 = T([-12, -4 + k * 2.6]), b1 = T([12, -2 + k * 2.6]);
          c.beginPath();
          c.moveTo(a1[0], a1[1]);
          c.lineTo(b1[0], b1[1]);
          c.stroke();
        }
      } });
    }
    /** Copperplate tone inside a shape: parallel burin lines that swell where tone(x, y) (0..1) is dark and lift to nothing where it's light. Paint it in a card's or plate's face. */
    engraved(c, shape, o) {
      const b = bounds(shape), w = o.w ?? 2.6, runs = hatchRuns(b, o.angle ?? -0.6, o.gap ?? 5, (x, y) => inside(shape, x, y), 3, o.seed ?? 1);
      c.fillStyle = o.color ?? INK;
      runs.forEach((run) => burin(c, cutLine(run, (x, y) => w * Math.min(1, Math.max(0, o.tone(x, y))), [], 2), o.min ?? 0.16));
    }
    /** A thin hand tint over an engraving: colour multiplied through the shape. */
    tint(c, shape, color, alpha = 0.45) {
      c.save();
      c.globalCompositeOperation = "multiply";
      c.globalAlpha = alpha;
      c.fillStyle = color;
      path(c, shape);
      c.fill();
      c.restore();
    }
    /** The sheet's tooth and handled edges over the finished frame, in screen space: last thing in the frame. */
    finish(g, o = {}) {
      this.sheet(g, { paper: o.paper ?? 0.1, vignette: o.vignette === void 0 ? "rgba(96,62,24,0.30)" : o.vignette });
    }
  };
  register("scrapbook", { start: (w, h, o) => new ScrapHand(w, h, o) });
})();
