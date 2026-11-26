/* letitedit drawing hand: rubberHose. Built from motion\runtime\looks-src (node build.mjs); don't edit this file.
 * Includes code from anidoodle (https://github.com/alexgreensh/anidoodle, commit 9c20e77), Copyright 2026 Alex Greenshpun, under the
 * Apache License 2.0: LICENSE-anidoodle.txt and NOTICE-anidoodle.txt beside this file. Changed by letitedit: see the headers in
 * looks-src. The rest is letitedit's own, GPL-3.0-or-later. Loaded into a code scene's page only when its script says M.look.rubberHose. */
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
    const n = pts.length, at2 = (i) => closed ? pts[(i % n + n) % n] : pts[Math.max(0, Math.min(n - 1, i))], out = [], segs = closed ? n : n - 1;
    for (let i = 0; i < segs; i++) {
      const [p0, p1, p2, p3] = [at2(i - 1), at2(i), at2(i + 1), at2(i + 2)];
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
      const t = i / (s.length - 1), p = s[i], q = s[Math.min(s.length - 1, i + 1)], o = s[Math.max(0, i - 1)], dx = q[0] - o[0], dy = q[1] - o[1], len2 = Math.hypot(dx, dy) || 1;
      const ends = Math.min(1, t / 0.14, (1 - t) / 0.2), tp = 1 - taper + taper * Math.pow(Math.max(0.04, ends), 0.7);
      const pr = Math.max(0.14, 1 - 0.26 * pressure + pressure * (0.3 * Math.sin(t * 5.5 + a) + 0.14 * Math.sin(t * 17 + b)));
      const w = width * tp * pr / 2, j1 = (r() - 0.5) * rough, j2 = (r() - 0.5) * rough;
      L.push([p[0] - dy / len2 * (w + j1), p[1] + dx / len2 * (w + j1)]);
      R.push([p[0] + dy / len2 * (w + j2), p[1] - dx / len2 * (w + j2)]);
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
      const { n = 8, len: len2 = 16, angle = -1.05, color = GRAPHITE, seed = 1, pw = 1.9, opacity = 0.55 } = o, r = rng(seed);
      for (let i = 0; i < n; i++) {
        const px = x + w * i / Math.max(1, n - 1) + (r() - 0.5) * 3, l = len2 * (0.7 + r() * 0.6), a = angle + (r() - 0.5) * 0.18;
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
  var smooth = (pts, closed = false, per = 12) => sample(pts, closed, per);
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

  // motion/runtime/looks-src/anidoodle/koiDrawKit.ts
  var cut = (s, q) => {
    if (q >= 1) return s;
    const cum = [0];
    for (let i = 1; i < s.length; i++) cum.push(cum[i - 1] + Math.hypot(s[i][0] - s[i - 1][0], s[i][1] - s[i - 1][1]));
    const want = cum[cum.length - 1] * Math.max(0, q), out = [s[0]];
    for (let i = 1; i < s.length; i++) {
      if (cum[i] <= want) {
        out.push(s[i]);
        continue;
      }
      const f = (want - cum[i - 1]) / (cum[i] - cum[i - 1] || 1);
      out.push([s[i - 1][0] + (s[i][0] - s[i - 1][0]) * f, s[i - 1][1] + (s[i][1] - s[i - 1][1]) * f]);
      break;
    }
    return out.length > 1 ? out : [s[0], s[0]];
  };

  // motion/runtime/looks-src/anidoodle/rubberHoseKit.ts
  var cb = (a, c1, c2, b, n = 16) => Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, u = 1 - t;
    return [u * u * u * a[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t * t * t * b[0], u * u * u * a[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t * t * t * b[1]];
  });
  var qb = (a, c, b, n = 16) => Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, u = 1 - t;
    return [u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]];
  });
  var ell = (cx, cy, rx, ry, rot = 0, n = 28) => Array.from({ length: n }, (_, i) => {
    const a = i / n * Math.PI * 2, x = Math.cos(a) * rx, y = Math.sin(a) * ry;
    return [cx + x * Math.cos(rot) - y * Math.sin(rot), cy + x * Math.sin(rot) + y * Math.cos(rot)];
  });
  var capsule = (a, b, r, n = 10) => {
    const ang = Math.atan2(b[1] - a[1], b[0] - a[0]), out = [];
    for (let i = 0; i <= n; i++) {
      const t = ang + Math.PI / 2 + i / n * Math.PI;
      out.push([a[0] + Math.cos(t) * r, a[1] + Math.sin(t) * r]);
    }
    for (let i = 0; i <= n; i++) {
      const t = ang - Math.PI / 2 + i / n * Math.PI;
      out.push([b[0] + Math.cos(t) * r, b[1] + Math.sin(t) * r]);
    }
    return out;
  };
  var rect = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  var noodle = (a, b, bend, n = 18) => {
    const dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    return qb(a, [(a[0] + b[0]) / 2 - dy / l * bend, (a[1] + b[1]) / 2 + dx / l * bend], b, n);
  };
  var place = (pts, o, ang = 0, sx = 1, sy = 1, mirror = false) => {
    const c = Math.cos(ang), s = Math.sin(ang);
    return pts.map(([x0, y0]) => {
      const x = (mirror ? -x0 : x0) * sx, y = y0 * sy;
      return [o[0] + x * c - y * s, o[1] + x * s + y * c];
    });
  };
  var wob = (pts, amp, seed) => {
    const ox = seed * 97.31 % 5e3, oy = seed * 57.17 % 5e3;
    return pts.map(([x, y]) => [x + (fractal(1930, x + ox, y + oy, 0.035, 0.035, 2) - 0.5) * amp, y + (fractal(1931, x + oy, y + ox, 0.035, 0.035, 2) - 0.5) * amp]);
  };
  var len = (s) => s.reduce((a, p, i) => i ? a + Math.hypot(p[0] - s[i - 1][0], p[1] - s[i - 1][1]) : a, 0);
  var polyArea = (s) => Math.abs(s.reduce((a, p, i) => {
    const q = s[(i + 1) % s.length];
    return a + p[0] * q[1] - q[0] * p[1];
  }, 0) / 2);
  var schedule = (parts) => {
    const inkItems = [], fillItems = [];
    parts.forEach((pt, z) => {
      pt.outline.forEach((o, i) => inkItems.push([`${z}:o${i}`, pt.orank, z * 100 + i, 5 + len(o) / 55]));
      pt.details.forEach((d, i) => inkItems.push([`${z}:d${i}`, d.rank, z * 100 + 50 + i, 4 + len(d.pts) / 55]));
      pt.fills.forEach((f, i) => fillItems.push([`${z}:f${i}`, f.rank, z * 100 + i, 0.8 + Math.sqrt(polyArea(f.pts)) / 30]));
    });
    const lay = (items) => {
      items.sort((a, b) => a[1] - b[1] || a[2] - b[2]);
      const tot = items.reduce((a, b) => a + b[3], 0), m = /* @__PURE__ */ new Map();
      let t = 0;
      items.forEach(([k, , , w]) => {
        m.set(k, [t / tot, (t + w) / tot]);
        t += w;
      });
      return m;
    };
    return { ink: lay(inkItems), fill: lay(fillItems) };
  };
  var at = (m, k, p) => {
    if (p >= 1) return 1;
    const w = m.get(k);
    return clamp2((p - w[0]) / (w[1] - w[0]));
  };
  var trace = (c, pts, close = true) => {
    c.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) c.lineTo(pts[i][0], pts[i][1]);
    if (close) c.closePath();
  };
  var INK = "#16130f";
  var paintFills = (c, parts, sch, p) => {
    parts.forEach((pt, z) => pt.fills.forEach((f, i) => {
      const q = at(sch, `${z}:f${i}`, p);
      if (q <= 0) return;
      c.save();
      c.globalAlpha = f.alpha ?? 1;
      c.fillStyle = f.col;
      if (q < 1) {
        const t = f.touch ?? f.pts.reduce((a, b) => [a[0] + b[0] / f.pts.length, a[1] + b[1] / f.pts.length], [0, 0]);
        const R = Math.max(...f.pts.map(([x, y]) => Math.hypot(x - t[0], y - t[1]))) * (1 - (1 - q) ** 2) + 2;
        c.beginPath();
        for (let k = 0; k <= 40; k++) {
          const a = k / 40 * Math.PI * 2, rr = R * (1 + 0.06 * Math.sin(a * 5 + z));
          k ? c.lineTo(t[0] + Math.cos(a) * rr, t[1] + Math.sin(a) * rr) : c.moveTo(t[0] + Math.cos(a) * rr, t[1] + Math.sin(a) * rr);
        }
        c.clip();
      }
      c.beginPath();
      trace(c, f.pts);
      c.fill();
      c.restore();
    }));
  };
  var inkCel = (c, parts, sch, p) => {
    c.lineCap = "round";
    c.lineJoin = "round";
    parts.forEach((pt, z) => {
      const knock = () => {
        if (pt.knock === false) return;
        c.save();
        c.globalCompositeOperation = "destination-out";
        c.fillStyle = "#000";
        c.beginPath();
        (pt.outline.length ? pt.outline : pt.fills.filter((f) => (f.alpha ?? 1) >= 1).map((f) => f.pts)).forEach((o) => trace(c, o));
        c.fill("nonzero");
        c.restore();
      };
      knock();
      if (pt.outline.length) {
        c.strokeStyle = INK;
        pt.outline.forEach((o, i) => {
          const q = at(sch, `${z}:o${i}`, p);
          if (q <= 0) return;
          c.lineWidth = pt.ow * 2;
          c.beginPath();
          trace(c, q >= 1 ? o : cut([...o, o[0]], q), q >= 1);
          c.stroke();
        });
        knock();
      }
      pt.details.forEach((d, i) => {
        const q = at(sch, `${z}:d${i}`, p);
        if (q <= 0) return;
        c.strokeStyle = d.col ?? INK;
        c.lineWidth = d.w;
        c.beginPath();
        trace(c, q >= 1 ? d.pts : cut(d.closed ? [...d.pts, d.pts[0]] : d.pts, q), !!d.closed && q >= 1);
        c.stroke();
      });
    });
  };
  var grainTile = (env) => {
    const key = `rubberHose:grain:${env.scale}`;
    let L = env.cache.get(key);
    if (L) return L;
    const n = Math.round(256 * env.scale);
    L = env.canvas(n, n);
    const img = L.ctx.createImageData(n, n), d = img.data, r = rng(1931);
    for (let i = 0; i < n * n; i++) {
      const v = (r() + r() + r()) / 3, g = Math.round(clamp2(0.5 + (v - 0.5) * 2.2) * 255);
      d[i * 4] = d[i * 4 + 1] = d[i * 4 + 2] = g;
      d[i * 4 + 3] = 255;
    }
    L.ctx.putImageData(img, 0, 0);
    env.cache.set(key, L);
    return L;
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
  var asList = (cut2) => typeof cut2[0][0] === "number" ? [cut2] : cut2;
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
      const W = Math.ceil((b.x1 - b.x0) * k), H = Math.ceil((b.y1 - b.y0) * k), at2 = (c2) => c2.setTransform(k, 0, 0, k, -b.x0 * k, -b.y0 * k);
      const F = env.canvas(W, H), c = F.ctx;
      at2(c);
      if (this.o.edge) {
        c.fillStyle = this.o.edge;
        this.trace(c, 1.2, 1.9, bd);
      }
      if (bd) {
        c.fillStyle = this.o.borderColor ?? "#fbf9f2";
        this.trace(c, 0, 0, bd);
      }
      at2(c);
      this.o.face(c);
      this.face = F;
      const S = env.canvas(W, H);
      at2(S.ctx);
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

  // motion/runtime/looks-src/rubberHose.ts
  var GREYS = { ink: INK, white: "#f3eee2", light: "#d9d3c4", mid: "#b3ad9f", grey: "#8c867a", dark: "#5e594f", shadow: "#3a362f", set: "#a29c8e" };
  var GLOVE = [smooth([[-17, -10], [-21, -28], [-15, -45], [0, -49], [15, -45], [20, -28], [17, -10]], true, 5), capsule([-12, -38], [-17, -72], 7.6), capsule([1, -40], [2, -81], 7.9), capsule([13, -38], [19, -69], 7.3), capsule([-15, -22], [-37, -40], 7.6), smooth([[-20, 4], [0, 7], [20, 4], [17, -13], [0, -10], [-17, -13]], true, 5)];
  var STITCH = [[[-7, -17], [-6, -33]], [[1, -17], [1, -35]], [[9, -17], [9, -32]]];
  var SHOE = smooth([[-18, -10], [-4, -15], [20, -14], [42, -20], [62, -10], [66, 7], [52, 21], [0, 22], [-22, 18], [-27, 4]], true, 6);
  var filmPrint = (c, env, seed) => {
    const { W, H } = env, r = rng(7e3 + seed * 13), L = Math.max(W, H), S = Math.min(W, H);
    c.save();
    c.globalCompositeOperation = "multiply";
    c.fillStyle = "#ecdfc6";
    c.fillRect(0, 0, W, H);
    const g = grainTile(env), pat = c.createPattern(g.canvas, "repeat");
    c.globalCompositeOperation = "overlay";
    c.globalAlpha = 0.34;
    c.setTransform(1, 0, 0, 1, Math.floor(r() * 256), Math.floor(r() * 256));
    c.fillStyle = pat;
    c.fillRect(-256, -256, W + 512, H + 512);
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.globalAlpha = 1;
    c.globalCompositeOperation = "source-over";
    c.fillStyle = `rgba(20,14,8,${(0.02 + r() * 0.05).toFixed(3)})`;
    c.fillRect(0, 0, W, H);
    const nd = 5 + Math.floor(r() * 5);
    for (let i = 0; i < nd; i++) {
      const x = r() * W, y = r() * H, s = 1 + r() * 2.6, dark = r() < 0.6;
      c.fillStyle = dark ? "rgba(18,12,8,0.7)" : "rgba(255,250,236,0.75)";
      c.beginPath();
      ell(x, y, s, s * (0.5 + r()), r() * 3, 8).forEach(([px, py], k) => k ? c.lineTo(px, py) : c.moveTo(px, py));
      c.fill();
    }
    if (r() < 0.55) {
      const x = r() * W, y = r() * H, a = r() * 6;
      c.strokeStyle = "rgba(20,14,8,0.55)";
      c.lineWidth = 1;
      c.beginPath();
      qb([x, y], [x + Math.cos(a) * 30, y + Math.sin(a) * 30 + 12], [x + Math.cos(a + 1) * 44, y + Math.sin(a + 1) * 40]).forEach(([px, py], k) => k ? c.lineTo(px, py) : c.moveTo(px, py));
      c.stroke();
    }
    const sx = W * (0.62 + r() * 0.3);
    c.strokeStyle = "rgba(255,250,236,0.35)";
    c.lineWidth = 1.2;
    c.beginPath();
    c.moveTo(sx, 0);
    c.lineTo(sx + (r() - 0.5) * 6, H);
    c.stroke();
    c.save();
    c.translate(W * 0.48, H * 0.44);
    c.scale(W / L, H / L);
    const vg = c.createRadialGradient(0, 0, L * 0.3, 0, 0, L * 0.72);
    vg.addColorStop(0, "rgba(0,0,0,0)");
    vg.addColorStop(1, "rgba(22,14,6,0.5)");
    c.fillStyle = vg;
    c.fillRect(-L, -L, L * 2, L * 2);
    c.restore();
    c.fillStyle = "#0b0907";
    c.beginPath();
    c.rect(0, 0, W, H);
    const m = S * 0.018, R = S * 0.05;
    c.moveTo(m + R, m);
    c.arcTo(m, m, m, m + R, R);
    c.arcTo(m, H - m, m + R, H - m, R);
    c.arcTo(W - m, H - m, W - m, H - m - R, R);
    c.arcTo(W - m, m, W - m - R, m, R);
    c.closePath();
    c.fill("evenodd");
    c.restore();
  };
  var HoseHand = class extends Hand {
    G = GREYS;
    rng = rng;
    smooth = smooth;
    cb = cb;
    qb = qb;
    ell = ell;
    capsule = capsule;
    rect = rect;
    noodle = noodle;
    place = place;
    wob = wob;
    fractal = fractal;
    layers = /* @__PURE__ */ new Map();
    sprites = /* @__PURE__ */ new Map();
    constructor(w, h) {
      super(w, h, { scale: 1 });
    }
    /** One piece of a drawing: painted fills on the back of the cel, one outline made of several shapes (stroked as one silhouette), ink details. Nearer parts stop the ink of those behind. */
    part(o) {
      return { fills: (o.fills ?? []).map((f) => ({ rank: 1, ...f })), outline: o.outline ?? [], ow: o.ow ?? 4, orank: o.orank ?? 1, details: (o.details ?? []).map((d) => ({ rank: 1, ...d })), knock: o.knock };
    }
    /** The solid black noodle limb: one arc from shoulder to wrist, no elbow. bend = how far it bows; w its width. */
    limb(a, b, bend, w = 12) {
      const pts = noodle(a, b, bend);
      return this.part({ details: [{ pts, w, col: INK }], knock: false });
    }
    /** The white four-digit glove, wrist at h, digits along angle a (0 = up), mirrored if m. Three stitch lines, flared cuff. k sizes it. */
    glove(h, a = 0, m = false, o = {}) {
      const k = o.k ?? 1, b = o.boil ?? 0, G = GLOVE.map((s) => wob(place(s, h, a, k, k, m), 1.8, b * 31 + 3));
      return this.part({ fills: G.map((s) => ({ pts: s, col: GREYS.white })), outline: G, ow: 3.4, details: STITCH.map((s) => ({ pts: wob(place(s, h, a, k, k, m), 1.2, b * 31 + 7), w: 2.4 })) });
    }
    /** The big oval shoe with one shine, ankle at f, toe along +x, mirrored if m. */
    shoe(f, a = 0, m = false, o = {}) {
      const k = o.k ?? 1, b = o.boil ?? 0, s = wob(place(SHOE, f, m ? -a : a, k, k, m), 1.8, b * 31 + 9), hi = place([[34, -3], [42, -7], [52, -3], [44, 1]], f, m ? -a : a, k, k, m);
      return this.part({ fills: [{ pts: s, col: o.color ?? INK }, { pts: hi, col: GREYS.white }], outline: [s], ow: 3 });
    }
    /** A big oval eye with a pie-cut pupil: a wedge missing at the upper left, where the shine would be. dir = [dx, dy] of the look. */
    eye(x, y, rx, ry, dir = [0.25, 0.15], o = {}) {
      const b = o.boil ?? 0, e = wob(ell(x, y, rx, ry, 0, 26), 1.2, b * 31 + 11), cx = x + dir[0] * rx, cy = y + dir[1] * ry, pu = [[cx, cy]];
      for (let i = 0; i <= 22; i++) {
        const a = -1.85 + i / 22 * (Math.PI * 2 - 0.8);
        pu.push([cx + Math.cos(a) * rx * 0.54, cy + Math.sin(a) * ry * 0.62]);
      }
      return this.part({ fills: [{ pts: e, col: GREYS.white }, { pts: pu, col: INK }], outline: [e], ow: 3.2 });
    }
    /** A translucent flat cast shadow with no ink. */
    shadow(pts, alpha = 0.35) {
      return this.part({ fills: [{ pts, col: GREYS.shadow, alpha }], knock: false });
    }
    layer(k) {
      let L = this.layers.get(k);
      if (!L) {
        L = this.env.canvas(this.w, this.h);
        this.layers.set(k, L);
      }
      return L;
    }
    /** A drawing: parts back to front. ink = 0..1 the inker's line goes down; paint = 0..1 the greys flood in, each from where the brush touched. key = a name for this pose, so a held pose isn't drawn again. Also x, y, s, pivot, alpha. */
    cel(g, parts, o = {}) {
      const ip = o.ink ?? 1, fp = o.paint ?? 1, w = this.w, h = this.h;
      let src = ip >= 1 && fp >= 1 && o.key ? this.sprites.get(o.key) : void 0;
      if (!src) {
        const sch = schedule(parts), cl = this.layer("ink"), c = cl.ctx, out = ip >= 1 && fp >= 1 && o.key ? this.env.canvas(w, h) : this.layer("out"), oc = out.ctx;
        c.setTransform(1, 0, 0, 1, 0, 0);
        c.globalCompositeOperation = "source-over";
        c.clearRect(0, 0, w, h);
        inkCel(c, parts, sch.ink, ip);
        oc.setTransform(1, 0, 0, 1, 0, 0);
        oc.globalAlpha = 1;
        oc.globalCompositeOperation = "source-over";
        oc.clearRect(0, 0, w, h);
        paintFills(oc, parts, sch.fill, fp);
        oc.drawImage(cl.canvas, 0, 0);
        if (ip >= 1 && fp >= 1 && o.key) {
          if (this.sprites.size > 64) this.sprites.clear();
          this.sprites.set(o.key, out);
        }
        src = out;
      }
      g.save();
      const s = o.s ?? 1, pv = o.pivot ?? [w / 2, h / 2];
      if (o.x || o.y) g.translate(o.x ?? 0, o.y ?? 0);
      if (s !== 1) {
        g.translate(pv[0], pv[1]);
        g.scale(s, s);
        g.translate(-pv[0], -pv[1]);
      }
      if (o.alpha !== void 0) g.globalAlpha *= o.alpha;
      g.drawImage(src.canvas, 0, 0, w, h);
      g.restore();
    }
    /** Stroked capitals centred at (x, y), cap tall, on this frame: a title card, a balloon's words. outline = a white letter inside the ink. */
    title(g, text, x, y, cap, o = {}) {
      const f = { weight: o.w ?? 0.2, cap: "round", join: "round", outline: o.outline };
      let xx = x - measure(text, cap, f) / 2;
      g.save();
      [...text].forEach((ch) => {
        glyph(g, ch, xx, y - cap / 2, cap, f, o.color ?? INK);
        xx += advance(ch, f) * (cap / 6);
      });
      g.restore();
    }
    /** The blue-pencil rough: line of action and masses, on the paper before the ink. */
    rough(g, pts, o = {}) {
      g.save();
      g.strokeStyle = o.color ?? "#8aa2c8";
      g.lineWidth = o.w ?? 2;
      g.globalAlpha *= 0.7;
      g.lineCap = "round";
      g.beginPath();
      pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y));
      if (o.closed) g.closePath();
      g.stroke();
      g.restore();
    }
    /** On twos at the project's fps: which drawing, a whole number. */
    drawing(t, fps = 24) {
      return Math.floor(t * fps / 2 + 1e-6);
    }
    /** The dance: key poses on the beat, the body hops between them. Returns {y, sx, sy, beat, u}: the hop's height, stretch in the air and squash on landing; held on twos. */
    hop(t, beat = 0.5, height = 26, fps = 24) {
      const h = this.drawing(t, fps) * 2 / fps, f = h / beat, i = Math.floor(f), u = f - i, up = Math.sin(u * Math.PI), land = u < 0.16 ? 1 - u / 0.16 : 0, sq = 1 - 0.16 * land + 0.1 * up;
      return { y: -height * up, sy: sq, sx: 1 / Math.sqrt(sq), beat: i, u };
    }
    /** Limbs follow the body by about two frames: the hop's u a little earlier. */
    behind(u, by = 0.2) {
      return ((u - by) % 1 + 1) % 1;
    }
    /** The gate's weave for this drawing: a small x, y shift to put on the whole picture while it moves; [0, 0] on a hold. */
    weave(t, fps = 24, on = true) {
      if (!on) return [0, 0];
      const r = rng(4100 + this.drawing(t, fps));
      return [(r() - 0.5) * 3.4, (r() - 0.5) * 3.4];
    }
    /** The print, last thing in the frame: warm tone, grain, flicker, dust, a hair, a scratch, the lamp's vignette and the rounded gate. A pure function of the drawing number. Over a person or footage, use grainOnly: the tone and the gate would paint the whole frame. */
    finish(g, o = {}) {
      const seed = o.still ? 0 : this.drawing(o.t ?? 0, o.fps ?? 24);
      g.save();
      g.setTransform(1, 0, 0, 1, 0, 0);
      if (o.grainOnly) {
        const r = rng(7e3 + seed * 13), T = grainTile(this.env), pat = g.createPattern(T.canvas, "repeat"), ox = Math.floor(r() * 256), oy = Math.floor(r() * 256);
        g.globalCompositeOperation = "source-atop";
        g.globalAlpha = 0.16;
        g.translate(ox, oy);
        g.fillStyle = pat;
        g.fillRect(-ox, -oy, this.w, this.h);
      } else filmPrint(g, this.env, seed);
      g.restore();
    }
  };
  register("rubberHose", { start: (w, h) => new HoseHand(w, h), greys: GREYS });
})();
