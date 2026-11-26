/* letitedit drawing hand: paperCraft. Built from motion\runtime\looks-src (node build.mjs); don't edit this file.
 * Includes code from anidoodle (https://github.com/alexgreensh/anidoodle, commit 9c20e77), Copyright 2026 Alex Greenshpun, under the
 * Apache License 2.0: LICENSE-anidoodle.txt and NOTICE-anidoodle.txt beside this file. Changed by letitedit: see the headers in
 * looks-src. The rest is letitedit's own, GPL-3.0-or-later. Loaded into a code scene's page only when its script says M.look.paperCraft. */
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

  // motion/runtime/looks-src/anidoodle/scrapbookKit.ts
  var clamp01 = (v) => v <= 0 ? 0 : v >= 1 ? 1 : v;
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

  // motion/runtime/looks-src/paperCraft.ts
  var WHITE = "#fbf9f2";
  var gouache = (c, shape, color, seed, o = {}) => {
    const { dir = 0, len = 44, w = 13, vary = 0.1, dens = 1 } = o, r = rng(seed), b = bounds(shape), area = (b.x1 - b.x0) * (b.y1 - b.y0);
    c.fillStyle = color;
    path(c, shape);
    c.fill();
    c.save();
    path(c, shape);
    c.clip();
    c.lineCap = "round";
    const n = Math.max(6, Math.round(area / (len * w) * 1.6 * dens));
    for (let i = 0; i < n; i++) {
      const x = b.x0 + r() * (b.x1 - b.x0), y = b.y0 + r() * (b.y1 - b.y0), a = dir + (r() - 0.5) * 0.35, l = len * (0.6 + r() * 0.7), k = r();
      c.strokeStyle = k < 0.5 ? mix(color, "#ffffff", vary * (0.5 + r())) : mix(color, "#1d2430", vary * (0.4 + r()));
      c.globalAlpha = 0.28 + r() * 0.25;
      c.lineWidth = w * (0.6 + r() * 0.6);
      c.beginPath();
      c.moveTo(x - Math.cos(a) * l / 2, y - Math.sin(a) * l / 2);
      c.quadraticCurveTo(x + (r() - 0.5) * 6, y + (r() - 0.5) * 6, x + Math.cos(a) * l / 2, y + Math.sin(a) * l / 2);
      c.stroke();
    }
    c.restore();
    c.globalAlpha = 1;
  };
  var shadeSide = (c, shape, color, seed, side, depth, dir = Math.PI / 2) => {
    const b = bounds(shape), r = rng(seed);
    c.save();
    path(c, shape);
    c.clip();
    c.lineCap = "round";
    for (let i = 0; i < 16; i++) {
      const u = r(), x = side[0] > 0 ? b.x1 - r() * depth : side[0] < 0 ? b.x0 + r() * depth : b.x0 + u * (b.x1 - b.x0), y = side[1] > 0 ? b.y1 - r() * depth : side[1] < 0 ? b.y0 + r() * depth : b.y0 + u * (b.y1 - b.y0), l = 16 + r() * 26;
      c.strokeStyle = color;
      c.globalAlpha = 0.3 + r() * 0.25;
      c.lineWidth = 5 + r() * 7;
      c.beginPath();
      c.moveTo(x - Math.cos(dir) * l / 2, y - Math.sin(dir) * l / 2);
      c.lineTo(x + Math.cos(dir) * l / 2, y + Math.sin(dir) * l / 2);
      c.stroke();
    }
    c.restore();
    c.globalAlpha = 1;
  };
  var print = (c, shape, fn) => {
    c.save();
    path(c, shape);
    c.clip();
    fn(bounds(shape));
    c.restore();
    c.globalAlpha = 1;
  };
  var wavePrint = (c, shape, col, gap = 22, sw = 2) => print(c, shape, (b) => {
    c.strokeStyle = col;
    c.lineWidth = sw;
    c.globalAlpha = 0.55;
    for (let y = b.y0 + 8, row = 0; y < b.y1 + 10; y += gap, row++) {
      c.beginPath();
      for (let x = b.x0 - 30 + row % 2 * 15; x < b.x1 + 30; x += 30) {
        c.moveTo(x, y);
        c.quadraticCurveTo(x + 7.5, y - 7, x + 15, y);
      }
      c.stroke();
    }
  });
  var dotPrint = (c, shape, col, gap = 14, rad = 2.2) => print(c, shape, (b) => {
    c.fillStyle = col;
    c.globalAlpha = 0.8;
    for (let y = b.y0, row = 0; y < b.y1 + gap; y += gap * 0.87, row++) for (let x = b.x0 + row % 2 * gap * 0.5; x < b.x1 + gap; x += gap) {
      c.beginPath();
      c.arc(x, y, rad, 0, 6.28);
      c.fill();
    }
  });
  var diamondPrint = (c, shape, col, gap = 26) => print(c, shape, (b) => {
    c.fillStyle = col;
    c.globalAlpha = 0.5;
    for (let y = b.y0, row = 0; y < b.y1 + gap; y += gap / 2, row++) for (let x = b.x0 + row % 2 * gap / 2; x < b.x1 + gap; x += gap) {
      c.beginPath();
      c.moveTo(x, y - 4);
      c.lineTo(x + 3, y);
      c.lineTo(x, y + 4);
      c.lineTo(x - 3, y);
      c.closePath();
      c.fill();
    }
    c.globalAlpha = 0.18;
    c.strokeStyle = col;
    c.lineWidth = 0.8;
    for (let d = b.x0 - (b.y1 - b.y0); d < b.x1; d += gap) {
      c.beginPath();
      c.moveTo(d, b.y0);
      c.lineTo(d + (b.y1 - b.y0), b.y1);
      c.stroke();
      c.beginPath();
      c.moveTo(d + (b.y1 - b.y0), b.y0);
      c.lineTo(d, b.y1);
      c.stroke();
    }
  });
  var stonePrint = (c, shape, base, seed) => print(c, shape, (b) => {
    const r = rng(seed);
    for (let y = b.y0, row = 0; y < b.y1; y += 17, row++) for (let x = b.x0 - row % 2 * 16; x < b.x1; ) {
      const w = 26 + r() * 16;
      c.fillStyle = mix(base, r() < 0.5 ? "#ffffff" : "#3b3226", 0.06 + r() * 0.14);
      c.globalAlpha = 1;
      c.beginPath();
      c.roundRect(x + 1.5, y + 1.5, w - 3, 14, 4);
      c.fill();
      x += w;
    }
  });
  var newsPrint = (c, shape, seed) => print(c, shape, (b) => {
    const r = rng(seed);
    c.fillStyle = "#4a4640";
    c.globalAlpha = 0.5;
    for (let col = b.x0 + 4; col < b.x1; col += 36) for (let y = b.y0 + 4; y < b.y1; y += 4.2) {
      if (r() < 0.06) {
        y += 6;
        continue;
      }
      const l = 20 + r() * 12;
      c.fillRect(col, y, l, 1.3);
    }
    c.globalAlpha = 0.7;
    c.fillRect(b.x0 + 16, b.y0 + 30, 60, 5);
  });
  var woodPrint = (c, shape, col, seed) => print(c, shape, (b) => {
    const r = rng(seed);
    c.strokeStyle = col;
    c.lineWidth = 1;
    c.globalAlpha = 0.35;
    for (let y = b.y0; y < b.y1; y += 3 + r() * 4) {
      c.beginPath();
      c.moveTo(b.x0, y);
      for (let x = b.x0; x <= b.x1; x += 40) c.lineTo(x, y + Math.sin(x * 0.013 + y) * 1.6);
      c.stroke();
    }
    c.globalAlpha = 0.5;
    c.strokeStyle = mix(col, "#000000", 0.2);
    for (let x = b.x0 + 60 + r() * 60; x < b.x1; x += 90 + r() * 90) {
      c.beginPath();
      c.moveTo(x, b.y0);
      c.lineTo(x, b.y1);
      c.stroke();
    }
  });
  var seedOf = (id) => {
    let s = 7;
    for (let i = 0; i < id.length; i++) s = s * 31 + id.charCodeAt(i) >>> 0;
    return s;
  };
  var land = (t, t0, dur, from, id, fps = 30) => {
    if (t < t0) return { ...REST, shown: false };
    if (t >= t0 + dur) return { ...REST, shown: true };
    const f = Math.round(t * fps + 1e-6), f2 = f - f % 2, u = clamp01((f2 / fps - t0) / dur), seed = seedOf(id), r = rng(seed + f2);
    if (u < 0.62) {
      const v2 = u / 0.62, e = 1 - (1 - v2) ** 2;
      return { dx: from[0] * (1 - e) + (r() - 0.5) * 1.4, dy: from[1] * (1 - e) + (r() - 0.5) * 1.4, rot: (seed % 2 ? 1 : -1) * 0.04 * (1 - e), lift: 1 - 0.6 * e, shown: true };
    }
    const v = (u - 0.62) / 0.38, damp = Math.exp(-4 * v) * (1 - v);
    return { dx: 0, dy: -2.2 * Math.abs(Math.sin(v * 9)) * damp, rot: (seed % 2 ? 1 : -1) * 0.035 * Math.sin(v * 13 + 0.6) * damp, lift: 0.4 * (1 - v), shown: true };
  };
  var rock = (t, amp, period, phase = 0, fps = 30) => {
    const f = Math.round(t * fps + 1e-6), f2 = f - f % 2;
    return amp * Math.sin(f2 / fps / period * Math.PI * 2 + phase);
  };
  var scallop = (x0, x1, y, amp, per, ph, bottom, seed) => {
    const r = rng(seed), top = [];
    for (let x = x0; x <= x1 + 1; x += per / 8) top.push([x, y - amp * Math.abs(Math.sin((x - x0) / per * Math.PI + ph)) + (r() - 0.5) * 1.2]);
    return [...top, [x1, bottom], [x0, bottom]];
  };
  var cloudShape = (cx, cy, w, h, seed) => {
    const r = rng(seed), pts = [[cx + w / 2, cy]], n = 4 + Math.floor(r() * 2);
    for (let i = 0; i <= n; i++) {
      const x = cx + w / 2 - w * i / n, hh = h * (0.45 + 0.55 * Math.sin(Math.PI * (i + 0.5) / (n + 1))) * (0.8 + r() * 0.3);
      for (let k = 0; k <= 6; k++) {
        const a = k / 6 * Math.PI, rr = w / n / 2;
        pts.push([x - rr + Math.cos(a) * rr, cy - hh * 0.5 - Math.sin(a) * hh * 0.55]);
      }
    }
    pts.push([cx - w / 2, cy]);
    return pts;
  };
  var rays = (cx, cy, R, n = 24) => Array.from({ length: n }, (_, i) => {
    const a = i / n * Math.PI * 2 - Math.PI / 2, rr = i % 2 ? R * 0.66 : R - (i % 4 === 0 ? 0 : R * 0.1);
    return [cx + Math.cos(a) * rr, cy + Math.sin(a) * rr];
  });
  var SIGN = { weight: 0.15, serif: 0.5, cap: "round", join: "round" };
  var PaperHand = class extends Hand {
    // the marks and the shapes, as they are
    gouache = gouache;
    shadeSide = shadeSide;
    print = print;
    wavePrint = wavePrint;
    dotPrint = dotPrint;
    diamondPrint = diamondPrint;
    stonePrint = stonePrint;
    newsPrint = newsPrint;
    woodPrint = woodPrint;
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
    scallop = scallop;
    cloudShape = cloudShape;
    rays = rays;
    land = land;
    rock = rock;
    glyph = glyph;
    measure = measure;
    advance = advance;
    WHITE = WHITE;
    palette = { kraft: "#b8905f", teal: "#2f6f73", gold: "#e1b54a", red: "#b8302c", redDark: "#7c1c1a", deepSea: "#2c5d8a", sea: "#3d7db0", shallows: "#4ba2a3", sand: "#e1c996", grass: "#7fa25a", grassDark: "#5c8546", skyTop: "#5f9dc4", skyLow: "#cfe3e6", sun: "#f7c343", sunRay: "#f29a2e", wood: "#b07a45", stone: "#b5a791", ink: "#2c2c30" };
    /** Sugar paper, printed or painted: a coloured sheet with fibres and an uneven dye. decorate(c, shape) adds its print. */
    sheetPiece(id, shape, color, o = {}) {
      const seed = o.seed ?? seedOf(id) % 997;
      return this.piece(id, { cut: shape, edge: o.edge ?? mix(color, "#0b1a2a", 0.45), depth: o.depth ?? 8, stage: o.stage, pivot: o.pivot, face: (c) => {
        c.fillStyle = color;
        path(c, shape);
        c.fill();
        fibres(c, shape, color, seed + 1, 0.7, 0.18);
        o.decorate?.(c, shape);
      } });
    }
    /** A gouache cut-out: painted strokes on white card, a white scissor margin round it, a card edge. */
    cutout(id, shape, color, o = {}) {
      const seed = o.seed ?? seedOf(id) % 997, b = bounds(shape);
      return this.piece(id, { cut: shape, border: o.border ?? 5, edge: o.edge ?? "#bdb29a", depth: o.depth ?? 6, stage: o.stage, pivot: o.pivot, face: (c) => {
        gouache(c, shape, color, seed, o);
        shadeSide(c, shape, o.shade ?? mix(color, "#2b2a40", 0.35), seed + 1, o.light ? [-o.light[0], -o.light[1]] : [1, 1], Math.min(b.x1 - b.x0, b.y1 - b.y0) * 0.22, o.dir ?? Math.PI / 2);
        o.decorate?.(c, shape);
      } });
    }
    /** A row with a scalloped top from x0 to x1 (sea, hills, a hedge): y = top line, amp and per = the bumps, down to bottom. */
    row(id, o) {
      const seed = o.seed ?? seedOf(id) % 997, s = scissor(scallop(o.x0 ?? -40, o.x1 ?? this.w + 40, o.y, o.amp ?? 10, o.per ?? 80, seed * 0.7, o.bottom ?? this.h + 8, seed), seed, 0.5);
      return this.sheetPiece(id, s, o.color, { depth: o.depth ?? 8, seed, stage: o.stage, decorate: o.decorate });
    }
    /** Foam dabs along the top of a row, as gouache on the row's shape. */
    foam(c, shape, seed = 58, color = WHITE) {
      const r = rng(seed);
      c.save();
      path(c, shape);
      c.clip();
      c.lineCap = "round";
      const top = shape.slice(0, -2);
      for (let i = 0; i < top.length; i++) {
        const [x, y] = top[i];
        if (r() > 0.42) continue;
        const k = 1 + Math.floor(r() * 3);
        for (let j = 0; j < k; j++) {
          const ox = (r() - 0.5) * 14, oy = 3 + r() * 9, l = 4 + r() * 10;
          c.strokeStyle = color;
          c.globalAlpha = 0.55 + r() * 0.35;
          c.lineWidth = 3 + r() * 4;
          c.beginPath();
          c.moveTo(x + ox, y + oy);
          c.lineTo(x + ox + l, y + oy + (r() - 0.5) * 3);
          c.stroke();
        }
      }
      c.restore();
      c.globalAlpha = 1;
    }
    /** A cut cloud: a flat underside, rounded bumps on top, painted in soft strokes. */
    cloud(id, cx, cy, w, h, o = {}) {
      const seed = o.seed ?? seedOf(id) % 997, s = scissor(cloudShape(cx, cy, w, h, seed), seed, 0.7), col = o.color ?? "#f6f4ec";
      return this.piece(id, { cut: s, edge: "#b9c4c8", depth: o.depth ?? 7, stage: o.stage, pivot: [cx, cy - h], face: (c) => {
        gouache(c, s, col, seed, { len: 30, w: 10, vary: 0.05 });
        shadeSide(c, s, o.shade ?? "#b9c7d3", seed + 1, [0, 1], h * 0.28, 0.1);
      } });
    }
    /** A flown drop: the sky painted in long soft strokes between two colours. */
    drop(id, o) {
      const { box: b, top = this.palette.skyTop, low = this.palette.skyLow, seed = 5, depth = 3, strokes = 0 } = o, s = rect(b.x1 - b.x0, b.y1 - b.y0, (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2), lowAt = o.lowAt ?? b.y0 + (b.y1 - b.y0) * 0.6;
      return this.piece(id, { cut: s, edge: "#3f6f86", depth, stage: o.stage, face: (c) => {
        const gr = c.createLinearGradient(0, b.y0, 0, lowAt);
        gr.addColorStop(0, top);
        gr.addColorStop(1, low);
        c.fillStyle = gr;
        path(c, s);
        c.fill();
        const r = rng(seed);
        c.save();
        path(c, s);
        c.clip();
        c.lineCap = "round";
        const n = strokes || Math.round((b.x1 - b.x0) * (lowAt - b.y0) / 2e3);
        for (let i = 0; i < n; i++) {
          const y = b.y0 + r() * (lowAt - b.y0), x = b.x0 + r() * (b.x1 - b.x0), u = clamp01((y - b.y0) / (lowAt - b.y0));
          c.strokeStyle = mix(mix(top, low, u), r() < 0.5 ? "#ffffff" : "#2d5f86", 0.12 + r() * 0.1);
          c.globalAlpha = 0.35;
          c.lineWidth = 8 + r() * 12;
          const L = 110 + r() * 190;
          c.beginPath();
          c.moveTo(x - L, y + (r() - 0.5) * 6);
          c.quadraticCurveTo(x, y + (r() - 0.5) * 14, x + L, y + (r() - 0.5) * 6);
          c.stroke();
        }
        c.restore();
        c.globalAlpha = 1;
      } });
    }
    /** A sun on a stick from above (the stick's top at topY), with rays and a painted highlight. Two pieces, stick first. */
    sun(id, cx, cy, R, o = {}) {
      const disc = o.disc ?? this.palette.sun, ray = o.ray ?? this.palette.sunRay, top = o.topY ?? -20, stickCut = [[cx - 4, top], [cx + 4, top], [cx + 4, cy - R * 0.5], [cx - 4, cy - R * 0.5]], ring2 = rays(cx, cy, R);
      const stick = this.piece(id + ":stick", { cut: stickCut, edge: "#8a6a40", depth: 6, stage: o.stage, pivot: [cx, top], face: (c) => {
        c.fillStyle = "#d8b37a";
        path(c, stickCut);
        c.fill();
        c.fillStyle = "#b88c52";
        c.fillRect(cx + 1, top, 3, cy - R * 0.5 - top);
      } });
      const sun = this.piece(id, { cut: ring2, border: 7, edge: "#c9b99a", depth: 6, stage: o.stage, pivot: [cx, cy], face: (c) => {
        gouache(c, ring2, ray, 11, { dir: 0.3, len: 30, w: 10, vary: 0.14 });
        const dsc = oval(cx, cy, R * 0.6, R * 0.6, 40);
        gouache(c, dsc, disc, 12, { dir: -0.6, len: 26, w: 9, vary: 0.12 });
        gouache(c, oval(cx - R * 0.18, cy - R * 0.18, R * 0.21, R * 0.16, 20), mix(disc, "#ffffff", 0.5), 13, { dir: -0.6, len: 14, w: 6, vary: 0.05 });
        shadeSide(c, dsc, mix(ray, "#b0501a", 0.3), 14, [1, 1], R * 0.21, -0.6);
      } });
      return { stick, sun };
    }
    /** One side of a pair of curtains, on the inside of the opening `open`; side -1 is left, 1 is right. */
    curtain(id, side, open, o = {}) {
      const col = o.color ?? this.palette.red, W = o.width ?? 104, x0 = side < 0 ? open.x0 - 6 : open.x1 + 6, k = side < 0 ? 1 : -1, H = open.y1 - open.y0, Y = (f) => open.y0 + f * H;
      const s = smooth([[x0, open.y0 - 6], [x0 + k * W, open.y0 - 6], [x0 + k * W * 0.81, Y(0.276)], [x0 + k * W * 0.44, Y(0.552)], [x0 + k * W * 0.21, Y(0.629)], [x0 + k * W * 0.38, Y(0.767)], [x0 + k * W * 0.6, open.y1 + 4], [x0, open.y1 + 4]], false, 6);
      const edgeX = side < 0 ? open.x0 : open.x1, tieY = Y(0.621), gold = o.tie ?? this.palette.gold;
      return this.piece(id, { cut: s, edge: "#6b1a18", depth: o.depth ?? 10, stage: o.stage, pivot: [edgeX, Y(0.3)], face: (c) => {
        gouache(c, s, col, side < 0 ? 151 : 152, { dir: Math.PI / 2, len: 70, w: 10, vary: 0.18, dens: 1.4 });
        c.save();
        path(c, s);
        c.clip();
        const r = rng(153 + side);
        for (let i = 0; i < 5; i++) {
          const u = W * 0.12 + i * W / 6;
          c.strokeStyle = i % 2 ? mix(col, "#000000", 0.35) : mix(col, "#ffffff", 0.2);
          c.globalAlpha = 0.45;
          c.lineWidth = 6 + r() * 4;
          c.beginPath();
          c.moveTo(edgeX - side * u, open.y0);
          c.quadraticCurveTo(edgeX - side * (u - 18 - i * 6), Y(0.46), edgeX - side * (W * 0.29 + i * 4), Y(0.629));
          c.lineTo(edgeX - side * (W * 0.35 + i * 8), open.y1);
          c.stroke();
        }
        c.restore();
        c.globalAlpha = 1;
        const tx = edgeX - side * W * 0.35;
        c.strokeStyle = gold;
        c.lineWidth = 6;
        c.lineCap = "round";
        c.beginPath();
        c.moveTo(tx - W * 0.25, tieY - 8);
        c.quadraticCurveTo(tx, tieY + 10, tx + W * 0.27, tieY - 6);
        c.stroke();
        c.fillStyle = gold;
        c.beginPath();
        c.arc(tx + side * 6, tieY + 14, 6, 0, 6.28);
        c.fill();
      } });
    }
    /** The scalloped pelmet across the top of the opening. */
    valance(id, open, o = {}) {
      const col = o.color ?? this.palette.red, trim = o.trim ?? this.palette.gold, n = o.n ?? 9, drop = o.drop ?? 44, w = (open.x1 - open.x0 + 20) / n, pts = [[open.x0 - 10, open.y0 - 30], [open.x1 + 10, open.y0 - 30]];
      for (let i = n; i >= 1; i--) {
        const x1 = open.x0 - 10 + i * w;
        for (let k = 0; k <= 8; k++) {
          const a = k / 8 * Math.PI;
          pts.push([x1 - w / 2 + Math.cos(a) * w / 2, open.y0 + drop + Math.sin(a) * 18]);
        }
      }
      return this.piece(id, { cut: pts, edge: "#6b1a18", depth: 10, stage: o.stage, pivot: [(open.x0 + open.x1) / 2, open.y0], face: (c) => {
        gouache(c, pts, col, 161, { dir: 0, len: 60, w: 10, vary: 0.16, dens: 1.2 });
        c.save();
        path(c, pts);
        c.clip();
        c.strokeStyle = trim;
        c.lineWidth = 5;
        path(c, pts.map(([x, y]) => [x, y - 5]), true);
        c.stroke();
        c.restore();
        c.fillStyle = trim;
        for (let i = 0; i < n - 1; i++) {
          const x = open.x0 - 10 + (i + 1) * w;
          c.beginPath();
          c.arc(x, open.y0 + drop + 4, 6, 0, 6.28);
          c.fill();
        }
      } });
    }
    /** The theatre's front: patterned card round the opening, gold trim, a crest, a stage-front apron if there's room. outer defaults to the frame less a margin; crest(c, x, y) paints your own crest on a cream oval (none = a plain oval). */
    proscenium(id, open, o = {}) {
      const O2 = o.outer ?? { x0: open.x0 - 40, y0: Math.max(10, open.y0 - 90), x1: open.x1 + 40, y1: Math.min(this.h - 10, open.y1 + 90) }, col = o.color ?? this.palette.teal, gold = o.trim ?? "#d9ae4a", apronCol = o.apron ?? this.palette.red, cx = (O2.x0 + O2.x1) / 2, cw = O2.x1 - O2.x0;
      const outer = [[O2.x0, O2.y1], [O2.x0, O2.y0 + 80], ...smooth([[cx - cw * 0.2, O2.y0 + 80], [cx - cw * 0.1, O2.y0 + 66], [cx - cw * 0.045, O2.y0 + 20], [cx, O2.y0], [cx + cw * 0.045, O2.y0 + 20], [cx + cw * 0.1, O2.y0 + 66], [cx + cw * 0.2, O2.y0 + 80]], false, 6), [O2.x1, O2.y0 + 80], [O2.x1, O2.y1]];
      const inner = [[open.x0, open.y1], [open.x0, open.y0 + 30], ...smooth([[open.x0, open.y0 + 30], [cx, open.y0 - 6], [open.x1, open.y0 + 30]], false, 10).slice(1, -1), [open.x1, open.y0 + 30], [open.x1, open.y1]];
      const ring2 = (c) => {
        c.beginPath();
        [outer, inner].forEach((s) => {
          s.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
          c.closePath();
        });
      };
      return this.piece(id, { hole: true, cut: [outer, inner], edge: "#173b3e", depth: 5, stage: o.stage, pivot: [cx, O2.y1], face: (c) => {
        c.save();
        path(c, inner);
        c.clip();
        c.fillStyle = "rgba(20,14,8,0.28)";
        c.beginPath();
        c.rect(open.x0 - 40, open.y0 - 60, open.x1 - open.x0 + 80, open.y1 - open.y0 + 100);
        path(c, inner.map(([x, y]) => [x + 16, y + 22]));
        c.fill("evenodd");
        c.restore();
        c.fillStyle = col;
        ring2(c);
        c.fill("evenodd");
        c.save();
        ring2(c);
        c.clip("evenodd");
        diamondPrint(c, outer, o.pattern ?? "#e6c56a", 26);
        c.restore();
        c.save();
        ring2(c);
        c.clip("evenodd");
        fibres(c, outer, col, 171, 0.5, 0.15);
        c.restore();
        const off = (d) => inner.map(([x, y]) => [x + (x < cx ? -d : d), y + (y > (open.y0 + open.y1) / 2 ? d : -d)]);
        c.strokeStyle = gold;
        c.lineWidth = 14;
        c.lineJoin = "round";
        path(c, off(7), false);
        c.stroke();
        c.strokeStyle = "#f2d78a";
        c.lineWidth = 3;
        path(c, off(10), false);
        c.stroke();
        const r = rng(172);
        c.fillStyle = "#9c6f22";
        for (let y = open.y0 + 40; y < open.y1; y += 22) [open.x0 - 7, open.x1 + 7].forEach((x) => {
          c.beginPath();
          c.arc(x + (r() - 0.5), y, 2.4, 0, 6.28);
          c.fill();
        });
        if (O2.y1 - open.y1 > 36) {
          const a = [[open.x0 - 30, open.y1 + 18], [open.x1 + 30, open.y1 + 18], [open.x1 + 30, O2.y1 - 10], [open.x0 - 30, O2.y1 - 10]];
          c.fillStyle = apronCol;
          path(c, a);
          c.fill();
          fibres(c, a, apronCol, 173, 0.5, 0.2);
          print(c, a, (b) => {
            c.fillStyle = "#f0dcb0";
            c.globalAlpha = 0.5;
            for (let x = b.x0 + 8; x < b.x1; x += 16) c.fillRect(x, b.y0 + 8, 3, b.y1 - b.y0 - 16);
          });
          c.fillStyle = this.palette.gold;
          c.fillRect(open.x0 - 30, open.y1 + 18, open.x1 - open.x0 + 60, 5);
        }
        if (O2.y0 + 42 < open.y0) {
          const y = O2.y0 + 42, cart = oval(cx, y, 62, 38, 30);
          c.fillStyle = WHITE;
          path(c, cart);
          c.lineWidth = 10;
          c.strokeStyle = WHITE;
          c.stroke();
          c.fill();
          gouache(c, cart, "#f1e2c2", 174, { len: 16, w: 6, vary: 0.06 });
          o.crest?.(c, cx, y);
        }
      } });
    }
    /** The bare kraft table the theatre stands on: a plate that fills the frame (or box). */
    table(id = "table", box, color) {
      const col = color ?? this.palette.kraft, b = box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, s = [[b.x0, b.y0], [b.x1, b.y0], [b.x1, b.y1], [b.x0, b.y1]];
      return this.plate(id, (c) => {
        c.fillStyle = col;
        c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
        fibres(c, s, col, 201, 1.2, 0.3);
      }, b);
    }
    /** Words on a slip of card: stroked letters (capitals, figures, a few signs), never a font. Centred at (x, y), cap = letter height. */
    sign(id, text, o) {
      const cap = o.cap ?? 40, f = o.face ?? SIGN, w = measure(text, cap, f) + cap * 1.3, h = cap * 2, seed = o.seed ?? seedOf(id) % 997, rot = o.rot ?? 0, ca = Math.cos(rot), sa = Math.sin(rot), T = ([x, y]) => [o.x + x * ca - y * sa, o.y + x * sa + y * ca], s = scissor(rect(w, h), seed, 0.8).map(T), card = o.card ?? "#f1e7d0";
      return this.piece(id, { cut: s, border: o.border ?? 0, edge: mix(card, "#3b2a14", 0.4), depth: o.depth ?? 6, stage: o.stage, pivot: [o.x, o.y], face: (c) => {
        c.fillStyle = card;
        path(c, s);
        c.fill();
        fibres(c, s, card, seed, 0.6, 0.15);
        c.save();
        c.translate(o.x, o.y);
        c.rotate(rot);
        let x = -measure(text, cap, f) / 2;
        [...text].forEach((ch) => {
          glyph(c, ch, x, -cap / 2, cap, f, o.ink ?? "#221d1a");
          x += advance(ch, f) * (cap / 6);
        });
        c.restore();
        c.globalAlpha = 1;
      } });
    }
    /** The sheet's tooth over the finished frame, in screen space: last thing in the frame. */
    finish(g, o = {}) {
      this.sheet(g, { paper: o.paper ?? 0.12, vignette: o.vignette === void 0 ? "rgba(60,36,14,0.32)" : o.vignette });
    }
  };
  register("paperCraft", { start: (w, h, o) => new PaperHand(w, h, o) });
})();
