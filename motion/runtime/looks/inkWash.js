/* letitedit drawing hand: inkWash. Built from motion\runtime\looks-src (node build.mjs); don't edit this file.
 * Includes code from anidoodle (https://github.com/alexgreensh/anidoodle, commit 9c20e77), Copyright 2026 Alex Greenshpun, under the
 * Apache License 2.0: LICENSE-anidoodle.txt and NOTICE-anidoodle.txt beside this file. Changed by letitedit: see the headers in
 * looks-src. The rest is letitedit's own, GPL-3.0-or-later. Loaded into a code scene's page only when its script says M.look.inkWash. */
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
  var ribbon = (s0, width2, seed, taper, pressure, rough = 0) => {
    const s = rough ? densify(s0, 1.5) : s0;
    const a = seed % 17 * 0.37, b = seed % 11 * 0.53, L = [], R = [], r = rng(seed * 31 + 7);
    for (let i = 0; i < s.length; i++) {
      const t = i / (s.length - 1), p = s[i], q = s[Math.min(s.length - 1, i + 1)], o = s[Math.max(0, i - 1)], dx = q[0] - o[0], dy = q[1] - o[1], len = Math.hypot(dx, dy) || 1;
      const ends = Math.min(1, t / 0.14, (1 - t) / 0.2), tp = 1 - taper + taper * Math.pow(Math.max(0.04, ends), 0.7);
      const pr = Math.max(0.14, 1 - 0.26 * pressure + pressure * (0.3 * Math.sin(t * 5.5 + a) + 0.14 * Math.sin(t * 17 + b)));
      const w = width2 * tp * pr / 2, j1 = (r() - 0.5) * rough, j2 = (r() - 0.5) * rough;
      L.push([p[0] - dy / len * (w + j1), p[1] + dx / len * (w + j1)]);
      R.push([p[0] + dy / len * (w + j2), p[1] - dx / len * (w + j2)]);
    }
    return [...L, ...R.reverse()];
  };
  var oval = (cx, cy, rx, ry = rx, n = 10, a0 = -1.9) => Array.from({ length: n }, (_, i) => {
    const a = a0 + i / n * Math.PI * 2;
    return [cx + Math.cos(a) * rx, cy + Math.sin(a) * ry];
  });
  var softBox = (cx, cy, w, h, e = 3.2, n = 16) => Array.from({ length: n }, (_, i) => {
    const a = -2.2 + i / n * Math.PI * 2, c = Math.cos(a), s = Math.sin(a), k = 1 / (Math.abs(c) ** e + Math.abs(s) ** e) ** (1 / e);
    return [cx + c * k * w / 2, cy + s * k * h / 2];
  });
  var arc = (cx, cy, rx, ry, a0, a1, n = 6) => Array.from({ length: n }, (_, i) => {
    const a = a0 + i / (n - 1) * (a1 - a0);
    return [cx + Math.cos(a) * rx, cy + Math.sin(a) * ry];
  });
  var line = (a, b, bow = 0) => {
    const nx = -(b[1] - a[1]), ny = b[0] - a[0], l = Math.hypot(nx, ny) || 1;
    return [a, [(a[0] + b[0]) / 2 + nx / l * bow, (a[1] + b[1]) / 2 + ny / l * bow], b];
  };
  var turn = (pts, cx, cy, deg) => {
    const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    return pts.map(([x, y]) => [cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c]);
  };
  var poly = (corners, per = 3) => corners.flatMap((a, i) => {
    const b = corners[(i + 1) % corners.length];
    return Array.from({ length: per }, (_, k) => [a[0] + (b[0] - a[0]) * k / per, a[1] + (b[1] - a[1]) * k / per]);
  });
  var heart = (cx, cy, s) => Array.from({ length: 14 }, (_, i) => {
    const t = i / 14 * Math.PI * 2;
    return [cx + s * Math.sin(t) ** 3, cy - s * (13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t)) / 16];
  });
  var tube = (centre, r0, r1 = r0, cap = true) => {
    const c = sample(centre, false, 5), L = [], R = [];
    c.forEach((p, i) => {
      const q = c[Math.min(c.length - 1, i + 1)], o = c[Math.max(0, i - 1)], dx = q[0] - o[0], dy = q[1] - o[1], len = Math.hypot(dx, dy) || 1, r = r0 + (r1 - r0) * i / (c.length - 1);
      L.push([p[0] - dy / len * r, p[1] + dx / len * r]);
      R.push([p[0] + dy / len * r, p[1] - dx / len * r]);
    });
    const e = c[c.length - 1], e0 = c[c.length - 2], ex = e[0] - e0[0], ey = e[1] - e0[1], el = Math.hypot(ex, ey) || 1, tip = cap ? [[e[0] + ex / el * r1, e[1] + ey / el * r1]] : [], thin = (a) => a.filter((_, i) => i % 3 === 0 || i === a.length - 1);
    return [...thin(L), ...tip, ...thin(R).reverse()];
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
  var profile = (knots) => (t) => {
    if (t <= knots[0][0]) return knots[0][1];
    for (let i = 1; i < knots.length; i++) if (t <= knots[i][0]) {
      const [t0, v0] = knots[i - 1], [t1, v1] = knots[i], f = (t - t0) / (t1 - t0);
      return lerp(v0, v1, (1 - Math.cos(f * Math.PI)) / 2);
    }
    return knots[knots.length - 1][1];
  };
  var trace = (c, pts, closed = true) => {
    c.beginPath();
    pts.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
    if (closed) c.closePath();
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
  var fillShape = (g, pts, color, alpha = 1) => {
    const b = boxOf(pts);
    g.touch(b.x0 - 2, b.y0 - 2, b.x1 + 2, b.y1 + 2);
    const c = g.cur;
    c.globalAlpha = alpha;
    c.fillStyle = color;
    trace(c, pts);
    c.fill();
    c.globalAlpha = 1;
  };
  var clipped = (g, pts, fn) => {
    const b = boxOf(pts);
    g.touch(b.x0 - 2, b.y0 - 2, b.x1 + 2, b.y1 + 2);
    const c = g.cur;
    c.save();
    trace(c, pts);
    c.clip();
    fn();
    c.restore();
  };
  var blob = (cx, cy, rx, ry, seed, k = 0.18, n = 14, rot = 0) => {
    const r = rng(seed), ph = r() * 6.28, out = [];
    for (let i = 0; i < n; i++) {
      const a = i / n * Math.PI * 2, f = 1 + (fractal(seed, Math.cos(a) * 3 + 10, Math.sin(a) * 3 + 10, 0.6, 0.6, 2) - 0.5) * 2 * k + Math.sin(a * 3 + ph) * k * 0.3;
      const x = Math.cos(a) * rx * f, y = Math.sin(a) * ry * f;
      out.push([cx + x * Math.cos(rot) - y * Math.sin(rot), cy + x * Math.sin(rot) + y * Math.cos(rot)]);
    }
    return smooth(out, true, 6);
  };
  var inside = (pts, x, y) => {
    let k = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const a = pts[i], b = pts[j];
      if (a[1] > y !== b[1] > y && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) k = !k;
    }
    return k;
  };

  // motion/runtime/looks-src/anidoodle/drafting.ts
  var O = [[1.3, 0.1], [0.2, 1.3], [0.2, 4.7], [1.3, 5.9], [2.7, 5.9], [3.8, 4.7], [3.8, 1.3], [2.7, 0.1], [1.3, 0.1]];
  var G = {
    A: { l: [[[0, 6], [2, 0], [4, 6]], [[0.9, 3.9], [3.1, 3.9]]] },
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
    "(": { c: [[[2, -0.4], [0.8, 1.6], [0.8, 4.6], [2, 6.6]]], w: 2.4 },
    ")": { c: [[[0.4, -0.4], [1.6, 1.6], [1.6, 4.6], [0.4, 6.6]]], w: 2.4 },
    "&": { c: [[[3.8, 6], [0.9, 1.9], [1, 0.7], [2, 0.1], [2.9, 0.8], [2.7, 1.9], [0.5, 3.8], [0.4, 5], [1.4, 5.9], [2.6, 5.7], [3.9, 3.6]]], w: 4 },
    x: { l: [[[0.5, 1.8], [3.1, 4.8]], [[3.1, 1.8], [0.5, 4.8]]], w: 3.6 },
    o: { c: [[[1.2, -0.2], [0.4, 0.5], [0.5, 1.5], [1.3, 2], [2.1, 1.4], [2.1, 0.4], [1.2, -0.2]]], w: 2.8 },
    // x = times, o = degree
    "@": { c: [O], l: [[[0, 6.6], [4, -0.6]]] },
    // diameter
    " ": { w: 2.6 },
    // added for teaching captions (no existing plate spells these, so nothing already drawn changes)
    "'": { l: [[[0.9, 0], [0.7, 1.7]]], w: 1.6 },
    '"': { l: [[[0.6, 0], [0.5, 1.7]], [[1.8, 0], [1.7, 1.7]]], w: 2.4 },
    "?": { c: [[[0.3, 1.2], [1.1, 0.1], [2.6, 0.1], [3.4, 1], [3.4, 2], [1.9, 3.1], [1.8, 4.3]]], l: [[[1.7, 5.5], [1.9, 5.9]]], w: 3.6 },
    "!": { l: [[[1, 0], [0.9, 4.3]], [[0.8, 5.5], [1, 5.9]]], w: 1.9 },
    ";": { l: [[[0.7, 2], [0.9, 2.4]], [[0.9, 5.4], [0.5, 6.8]]], w: 1.8 },
    "+": { l: [[[0.3, 3.2], [3.3, 3.2]], [[1.8, 1.7], [1.8, 4.7]]], w: 3.6 },
    "=": { l: [[[0.4, 2.4], [3.2, 2.4]], [[0.4, 4], [3.2, 4]]], w: 3.6 },
    "%": { l: [[[3.4, 0.2], [0.2, 5.8]]], c: [[[0.9, 0.2], [0.3, 0.8], [0.9, 1.6], [1.5, 0.8], [0.9, 0.2]], [[2.8, 4.3], [2.2, 5], [2.8, 5.8], [3.4, 5], [2.8, 4.3]]], w: 3.6 }
  };
  var strokes = (ch) => {
    const g = G[ch] ?? G[ch.toUpperCase()] ?? G["-"];
    return (g.l ?? []).reduce((a, st) => a + st.length - 1, 0) + (g.c ?? []).length;
  };
  var strokeCount = (text) => [...text].reduce((a, ch) => a + strokes(ch), 0);
  var width = (text, cap = 12, track = 1.25) => {
    const s = cap / 6;
    return [...text].reduce((a, ch) => a + ((G[ch] ?? G[ch.toUpperCase()] ?? G["-"]).w ?? 4) * s + track * s, 0) - track * s;
  };
  var letter = (g, text, x, y, o = {}) => {
    const { cap = 12, color = "#eef6fb", seed = 1, align = "left", opacity = 0.95, track = 1.25, progress = 1, slant = 0.2 } = o, s = cap / 6, r = rng(seed * 131 + 7), W = width(text, cap, track);
    if (progress <= 0) return;
    let cx = align === "center" ? x - W / 2 : align === "right" ? x - W : x, written = progress >= 1 ? Infinity : progress * strokeCount(text);
    [...text].forEach((ch0, i) => {
      const gl = G[ch0] ?? G[ch0.toUpperCase()] ?? G["-"], dy = (r() - 0.5) * cap * 0.07, k = 1 + (r() - 0.5) * 0.06;
      const T = ([px, py]) => [cx + (px + (6 - py) * slant) * s * k, y + dy + py * s * k];
      const pen = (pts, j2) => {
        const p = written === Infinity ? 1 : Math.max(0, Math.min(1, written));
        written === Infinity || (written -= 1);
        if (p > 0) g.pen(pts.map(T), { w: o.w ?? Math.max(1.1, cap * 0.115), color, seed: seed + i * 37 + j2 * 11, wobble: 0.25, boil: 0, taper: 0.35, opacity, progress: p });
      };
      let j = 0;
      (gl.l ?? []).forEach((st) => {
        for (let q = 1; q < st.length; q++) pen([st[q - 1], st[q]], j++);
      });
      (gl.c ?? []).forEach((st) => pen(st, j++));
      cx += ((gl.w ?? 4) + track) * s;
    });
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
      const G2 = new Gfx(g, this.env, 0, THIN);
      if ((o.paper ?? 0.12) > 0) G2.paper(o.tile ?? "paper", o.paper ?? 0.12);
      if (o.vignette !== null) G2.vignette(o.vignette ?? "rgba(60,36,14,0.32)");
      g.restore();
    }
    /** Time held on twos: a stop-motion pose lasts two frames. */
    twos(t, fps = 30) {
      const f = Math.round(t * fps + 1e-6);
      return (f - f % 2) / fps;
    }
    /** An ink line drawn through the current transform, wobbling and tapering like a hand: pts are smoothed; progress 0..1 draws part of it. */
    pen(g, pts, o = {}) {
      const m = g.getTransform(), a = g.globalAlpha, G2 = new Gfx(g, this.env, 0, THIN);
      g.setTransform(m);
      G2.pen(pts, { w: o.w ?? 2.4, color: o.color ?? "#2a2019", seed: o.seed ?? 1, wobble: o.wobble ?? 0.5, boil: 0, taper: o.taper ?? 0.5, opacity: o.opacity ?? 0.95, retrace: false, progress: o.progress ?? 1 });
      g.globalAlpha = a;
    }
  };
  var register = (name, value) => {
    const M = window.M;
    (M.look = M.look || {})[name] = value;
  };

  // motion/runtime/looks-src/worked.ts
  var KEEP = 8;
  var Work = class {
    env;
    w;
    h;
    medium;
    marks = [];
    total = 0;
    ground;
    fin;
    live;
    saved = /* @__PURE__ */ new Map();
    scratch;
    done;
    constructor(hand, medium, o) {
      this.w = o.w ?? hand.w;
      this.h = o.h ?? hand.h;
      this.medium = o.medium ?? medium;
      this.ground = o.ground;
      this.fin = o.finish;
      this.env = makeEnv(this.w, this.h, hand.scale);
      this.env.cache = hand.env.cache;
    }
    get DW() {
      return Math.round(this.w * this.env.scale);
    }
    get DH() {
      return Math.round(this.h * this.env.scale);
    }
    /** Adds a mark that takes `weight` of the picture's time. draw(G, q): G is the core's drawing context on this surface, q goes up to exactly 1. */
    add(weight, draw) {
      if (this.live || this.done) throw new Error("add every mark before the first draw");
      const t0 = this.total;
      this.total += Math.max(1e-6, weight);
      this.marks.push({ t0, t1: this.total, draw });
      return this;
    }
    /** A breath between passes, with nothing moving. */
    pause(weight) {
      this.total += weight;
      return this;
    }
    get length() {
      return this.marks.length;
    }
    /** Where a mark's window ends, 0..1: to land a later pass on a word. */
    at(n) {
      const m = this.marks[Math.max(0, Math.min(this.marks.length - 1, n))];
      return m ? m.t1 / (this.total || 1) : 1;
    }
    on(L) {
      const c = L.ctx;
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.globalAlpha = 1;
      c.globalCompositeOperation = "source-over";
      return new Gfx(c, this.env, 0, this.medium);
    }
    copy(from, to) {
      const c = to.ctx;
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.globalAlpha = 1;
      c.globalCompositeOperation = "copy";
      c.imageSmoothingEnabled = false;
      c.drawImage(from.canvas, 0, 0);
      c.globalCompositeOperation = "source-over";
      c.imageSmoothingEnabled = true;
    }
    get every() {
      return Math.max(1, Math.ceil(this.marks.length / KEEP));
    }
    surface(n) {
      const every = this.every, mark = Math.floor(n / every) * every;
      let cur = this.live;
      if (!cur || cur.n > n || cur.n < mark) {
        let from = -1, L;
        for (const k of this.saved.keys()) if (k <= n && k > from) {
          from = k;
          L = this.saved.get(k);
        }
        if (cur && cur.n <= n && cur.n > from) {
          from = cur.n;
          L = void 0;
        }
        if (from < 0) {
          const fresh = cur?.L ?? this.env.canvas(this.DW, this.DH);
          fresh.ctx.setTransform(1, 0, 0, 1, 0, 0);
          fresh.ctx.clearRect(0, 0, this.DW, this.DH);
          if (this.ground) this.ground(this.on(fresh));
          cur = { n: 0, L: fresh };
          const s = this.env.canvas(this.DW, this.DH);
          this.copy(fresh, s);
          this.saved.set(0, s);
        } else if (L) {
          const t = cur?.L ?? this.env.canvas(this.DW, this.DH);
          this.copy(L, t);
          cur = { n: from, L: t };
        }
        this.live = cur;
      }
      if (cur.n < n) {
        const G2 = this.on(cur.L);
        for (let i = cur.n; i < n; i++) {
          const c = cur.L.ctx;
          c.save();
          this.marks[i].draw(G2, 1);
          c.restore();
          const k = i + 1;
          if (k % every === 0 && k < this.marks.length && !this.saved.has(k)) {
            const s = this.env.canvas(this.DW, this.DH);
            this.copy(cur.L, s);
            this.saved.set(k, s);
          }
        }
        cur.n = n;
      }
      return cur.L;
    }
    /** The picture at p as a layer (for a hand that needs to read it, say). */
    layer(p = 1) {
      const list = this.marks, t = clamp2(p) * this.total;
      if (p >= 1) {
        if (this.done) return this.done;
        const L2 = this.surface(list.length);
        if (!this.fin) return L2;
        const D = this.env.canvas(this.DW, this.DH);
        this.copy(L2, D);
        this.fin(this.on(D));
        this.done = D;
        return D;
      }
      let lo = 0, hi = list.length;
      while (lo < hi) {
        const m2 = lo + hi >> 1;
        if (list[m2].t1 <= t) lo = m2 + 1;
        else hi = m2;
      }
      const n = lo, L = this.surface(n), m = list[n], q = m && t > m.t0 ? (t - m.t0) / (m.t1 - m.t0) : 0;
      if (q <= 0 && !this.fin) return L;
      const S = this.scratch ?? (this.scratch = this.env.canvas(this.DW, this.DH));
      this.copy(L, S);
      const G2 = this.on(S);
      if (q > 0) {
        S.ctx.save();
        m.draw(G2, q);
        S.ctx.restore();
      }
      if (this.fin) this.fin(this.on(S));
      return S;
    }
    /** Places it through the context's current transform, so a camera moves it. p (default 1) is how far through its marks it is. */
    draw(g, o = {}) {
      const L = this.layer(o.p ?? 1), a = o.alpha ?? 1, s = o.s ?? 1, r = o.r ?? 0, pv = o.pivot ?? [this.w / 2, this.h / 2];
      g.save();
      if (o.clip) {
        g.beginPath();
        g.rect(o.clip.x0, o.clip.y0, o.clip.x1 - o.clip.x0, o.clip.y1 - o.clip.y0);
        g.clip();
      }
      g.translate(pv[0] + (o.x ?? 0), pv[1] + (o.y ?? 0));
      if (r) g.rotate(r);
      if (s !== 1) g.scale(s, s);
      g.translate(-pv[0], -pv[1]);
      g.globalAlpha *= a;
      g.drawImage(L.canvas, 0, 0, this.w, this.h);
      g.restore();
    }
  };
  var WorkHand = class extends Hand {
    works = /* @__PURE__ */ new Map();
    medium;
    rng = rng;
    fractal = fractal;
    mix = mix;
    lerp = lerp;
    clamp = clamp2;
    bounds = bounds;
    inside = inside;
    resample = resample;
    profile = profile;
    smooth = (pts, closed = false, per = 10) => smooth(pts, closed, per);
    oval = oval;
    softBox = softBox;
    arc = arc;
    line = line;
    turn = turn;
    poly = poly;
    heart = heart;
    tube = tube;
    displace = displace;
    jitter = jitter;
    sample = sample;
    constructor(w, h, o, medium) {
      super(w, h, o);
      this.medium = medium;
    }
    /** One picture: make it once at the top of the block, add its marks, then draw it every frame. */
    work(id, o = {}) {
      let W = this.works.get(id);
      if (!W) {
        W = new Work(this, this.medium, o);
        this.works.set(id, W);
      }
      return W;
    }
    /** Runs fn with the surface clipped to a shape, and optionally with other shapes cut out of it: strokes that must not cross an edge. */
    within(G2, shape, out, fn) {
      const c = G2.cur;
      c.save();
      c.beginPath();
      const tr = (s) => {
        s.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
        c.closePath();
      };
      if (shape) {
        tr(shape);
        if (out) out.forEach(tr);
        c.clip("evenodd");
      } else if (out) {
        c.rect(-1e5, -1e5, 2e5, 2e5);
        out.forEach(tr);
        c.clip("evenodd");
      }
      fn();
      c.restore();
    }
  };

  // motion/runtime/looks-src/marks.ts
  var plen = (s) => {
    let L = 0;
    for (let i = 1; i < s.length; i++) L += Math.hypot(s[i][0] - s[i - 1][0], s[i][1] - s[i - 1][1]);
    return L;
  };
  var cost = (len, each = 4) => each + Math.pow(Math.max(0, len), 0.85);
  var drawn = (G2, marks, total, q) => {
    let b = q >= 1 ? Infinity : q * total;
    for (const m of marks) {
      if (b <= 0) break;
      m.d(G2, b >= m.t ? 1 : b / m.t);
      b -= m.t;
    }
  };
  var run = (W, marks, tool = {}) => {
    const n = tool.chunk ?? 24;
    for (let i = 0; i < marks.length; i += n) {
      const part = marks.slice(i, i + n), total = part.reduce((a, m) => a + m.t, 0);
      W.add(total, (G2, q) => {
        const fn = () => drawn(G2, part, total, q);
        if (tool.halo) G2.inkGroup(fn, { blur: tool.halo.blur, alpha: tool.halo.alpha, textures: tool.halo.textures });
        else G2.group(tool.kind ?? "plain", fn, { textures: tool.textures, blur: tool.blur, blend: tool.blend, alpha: tool.alpha, off: tool.off });
      });
    }
    return W;
  };
  var lettering = (text, x, y, o) => ({
    t: strokeCount(text) * 5,
    d: (G2, p) => letter(G2, text, x, y, { ...o, progress: p })
  });
  var MarkHand = class extends WorkHand {
    /** A ball lit from one side: 0 on the lit side, 1 in the shade, 0 outside it. light is a direction, [-0.7, -0.7] is upper left. */
    ball(cx, cy, r, light = [-0.7, -0.7]) {
      const l = Math.hypot(light[0], light[1]) || 1, lx = light[0] / l, ly = light[1] / l;
      return (x, y) => {
        const nx = (x - cx) / r, ny = (y - cy) / r, d = nx * nx + ny * ny;
        if (d > 1) return 0;
        const nz = Math.sqrt(1 - d), lit = nx * lx * 0.75 + ny * ly * 0.75 + nz * 0.66;
        return clamp2(0.78 - lit * 0.62);
      };
    }
    /** Across a shape from one side to the other: 0 where the light comes from, 1 at the far side. */
    across(shape, angle = 0.8) {
      const c = Math.cos(angle), s = Math.sin(angle), v = shape.map(([x, y]) => x * c + y * s), lo = Math.min(...v), hi = Math.max(...v);
      return (x, y) => clamp2((x * c + y * s - lo) / (hi - lo || 1));
    }
    /** A tone everywhere inside a shape and nothing outside it. */
    inShape(shape, tone) {
      return (x, y) => inside(shape, x, y) ? typeof tone === "number" ? tone : tone(x, y) : 0;
    }
    /** Paper textures multiplied over a finished frame, in screen space. list: [[tile, strength], ...]. */
    grain(g, list) {
      g.save();
      const G2 = new Gfx(g, this.env, 0, this.medium);
      list.forEach(([t, a]) => {
        if (a > 0) G2.paper(t, a);
      });
      g.restore();
    }
    /** A plate painted through the core's drawing context, for grounds that use paper tiles. */
    ground(id, paint, box) {
      const b = box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h }, W = b.x1 - b.x0, H = b.y1 - b.y0;
      return this.plate(id, (c) => {
        const env = { ...this.env, W, H }, G2 = new Gfx(c, env, 0, this.medium);
        paint(G2, W, H);
      }, b);
    }
    /** A breath on the Work: time passes with nothing moving. */
    rest(W, t = 10) {
      W.pause(t);
      return W;
    }
  };

  // motion/runtime/looks-src/inkWash.ts
  var INK_M = { nib: 1.7, taper: 1, pressure: 1.75, retrace: false, wobble: 1.35, rough: 0.6 };
  var INK = "#16131f";
  var PAPER = "#fbf8f0";
  var PALETTE = { ink: INK, paper: PAPER, brown: "#a0693a", darkBrown: "#5e3a20", buff: "#e6c794", rufous: "#b8733a", umber: "#6e4a2c", sap: "#6f8f3e", red: "#c3262d", cool: "#9fb3c8", mist: "#b8c7d6", sand: "#d8b98a", sea: "#6f9aa8" };
  var hx = (a) => Math.round(255 * clamp2(a)).toString(16).padStart(2, "0");
  var wetBody = (G2, pts, color, o, settle, bloomK) => {
    const { alpha = 0.55, seed = 1, pool = 0.55, bloom = null, bloomR = 22 } = o, b = bounds(pts);
    G2.wash(pts, color, { alpha, seed, dx: 7, dy: 6, shrink: o.flood ?? 1.07, rim: true });
    if (settle > 0) clipped(G2, pts, () => {
      const c = G2.cur, top = 0.45 + 0.35 * (1 - settle), gr = c.createLinearGradient(0, b.y0 + (b.y1 - b.y0) * top, 0, b.y1 + 2), a = alpha * pool * settle;
      gr.addColorStop(0, color + "00");
      gr.addColorStop(0.75, color + hx(a * 0.6));
      gr.addColorStop(1, color + hx(a * 1.3));
      c.fillStyle = gr;
      c.fillRect(b.x0 - 20, b.y0, b.x1 - b.x0 + 40, b.y1 - b.y0 + 20);
    });
    if (bloom && bloomK > 0) {
      const k = Math.sqrt(bloomK), bl = blob(bloom[0], bloom[1], bloomR, bloomR * 0.8, seed + 7, 0.32, 18).map(([x, y]) => [bloom[0] + (x - bloom[0]) * k, bloom[1] + (y - bloom[1]) * k]);
      fillShape(G2, bl, PAPER, 0.42);
      const c = G2.cur;
      c.strokeStyle = mix(color, INK, 0.25);
      c.globalAlpha = alpha * 0.9;
      c.lineWidth = 1.6;
      c.beginPath();
      bl.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
      c.closePath();
      c.stroke();
      c.globalAlpha = 1;
    }
  };
  var beadFront = (b, t, seed) => {
    const y = b.y0 - 14 + (b.y1 - b.y0 + 40) * t, out = [];
    for (let x = b.x0 - 30; x <= b.x1 + 30; x += 8) out.push([x, y + 5 * Math.sin(x * 0.045 + seed) + 3 * Math.sin(x * 0.13 + seed * 2)]);
    return out;
  };
  var wetMark = (pts, color, o) => (G2, p) => {
    const seed = o.seed ?? 1, alpha = o.alpha ?? 0.55, b = bounds(pts);
    G2.group("paint", () => {
      if (p >= 1) return wetBody(G2, pts, color, o, 1, 1);
      const spread = clamp2(p / 0.55), settle = clamp2((p - 0.4) / 0.45), bloomK = clamp2((p - 0.7) / 0.3), c = G2.cur, front = beadFront(b, spread, seed);
      c.save();
      c.beginPath();
      c.moveTo(b.x0 - 40, b.y0 - 60);
      c.lineTo(b.x1 + 40, b.y0 - 60);
      for (let i = front.length - 1; i >= 0; i--) c.lineTo(front[i][0], front[i][1]);
      c.closePath();
      c.clip();
      wetBody(G2, pts, color, o, settle, bloomK);
      c.restore();
      if (spread < 1) clipped(G2, pts, () => {
        c.strokeStyle = color;
        c.globalAlpha = alpha * 0.55;
        c.lineWidth = 3.2;
        c.lineJoin = "round";
        c.beginPath();
        front.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
        c.stroke();
        c.globalAlpha = 1;
      });
    });
  };
  var InkWashHand = class extends MarkHand {
    palette = PALETTE;
    blob = blob;
    constructor(w, h, o) {
      super(w, h, o, INK_M);
    }
    /** The cold-press sheet: a plate. */
    paper(id = "paper", o = {}) {
      const b = o.box ?? { x0: 0, y0: 0, x1: this.w, y1: this.h };
      return this.plate(id, (c) => {
        c.fillStyle = o.color ?? PAPER;
        c.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
      }, b);
    }
    /** A wash laid as a bead pulled down the shape, floods a little past it (flood 1.07; 1 keeps to the shape), and settles darker along its bottom edge. bloom: [x, y] a backrun, a pale cauliflower where a wetter drop touched. */
    wash(W, shape, color, o = {}) {
      W.add(o.t ?? 100, wetMark(shape, color, o));
      return W;
    }
    /** A loose wash with no outline to keep to, top to bottom: for a sky or a background. Each part: {x, y, rx, ry, color, alpha}. */
    ground(W, parts, o = {}) {
      const seed = o.seed ?? 10, shapes = parts.map((q, i) => blob(q.x, q.y, q.rx, q.ry, seed + i, 0.3, 22, q.rot ?? 0)), b = bounds(shapes.flat());
      W.add(o.t ?? 120, (G2, p) => G2.group("paint", () => {
        const draw = () => shapes.forEach((s, i) => G2.wash(s, parts[i].color, { alpha: parts[i].alpha ?? 0.26, seed: seed + i, dx: 0, dy: 5, shrink: 1 }));
        if (p >= 1) return draw();
        const c = G2.cur, front = beadFront(b, p, 3);
        c.save();
        c.beginPath();
        c.moveTo(b.x0 - 60, b.y0 - 60);
        c.lineTo(b.x1 + 60, b.y0 - 60);
        for (let i = front.length - 1; i >= 0; i--) c.lineTo(front[i][0], front[i][1]);
        c.closePath();
        c.clip();
        draw();
        c.restore();
      }));
      return W;
    }
    /** A small shape lifted back toward the paper: a highlight. */
    lift(W, shape, o = {}) {
      W.add(6, (G2) => G2.group("plain", () => fillShape(G2, shape, PAPER, o.alpha ?? 0.8)));
      return W;
    }
    /** A dab of solid colour: an eye, a berry. */
    dab(W, shape, color, o = {}) {
      W.add(6, (G2, p) => {
        if (p > 0) G2.group("plain", () => fillShape(G2, shape, color, o.alpha ?? 1));
      });
      return W;
    }
    /** The nib: one loose stroke through a few points, thick where pressed, hair-thin at the lift. Pen work goes on after the washes have dried. */
    nib(W, pts, w = 2, o = {}) {
      return run(W, [{ t: cost(plen(pts)), d: (G2, p) => G2.pen(pts, { w, color: o.color ?? INK, seed: o.seed ?? 1, wobble: o.wob ?? 0.9, boil: 0, taper: 1, opacity: o.op ?? 0.95, retrace: false, closed: o.closed, progress: p }) }]);
    }
    /** The pen shaken: dots land one after another. */
    spatter(W, x, y, o = {}) {
      const { n = 30, spread = 60, seed = 9, size = 2.2, color = INK } = o, r = rng(seed);
      const dots = Array.from({ length: n }, () => {
        const a = r() * 6.283, d = spread * Math.sqrt(r()) * (r() < 0.2 ? 1.6 : 1);
        return [x + Math.cos(a) * d, y + Math.sin(a) * d, 0.4 + r() * r() * size];
      });
      return run(W, dots.map(([dx, dy, s]) => ({ t: 1, d: (G2, p) => {
        if (p <= 0) return;
        const c = G2.cur;
        G2.touch(dx - s, dy - s, dx + s, dy + s);
        c.fillStyle = color;
        c.globalAlpha = 0.9;
        c.beginPath();
        c.arc(dx, dy, s, 0, 6.283);
        c.fill();
        c.globalAlpha = 1;
      } })));
    }
    /** Capitals with the nib, stroke by stroke. */
    write(W, text, x, y, o = {}) {
      return run(W, [lettering(text, x, y, { cap: 24, slant: 0.14, opacity: 0.92, ...o, color: o.color ?? INK })]);
    }
    /** The sheet's tooth over the finished frame, in screen space: last thing in the frame. */
    finish(g, o = {}) {
      this.grain(g, [["coldpress", o.coldpress ?? 0.16], ["paper", o.paper ?? 0.08]]);
    }
  };
  register("inkWash", { start: (w, h, o) => new InkWashHand(w, h, o) });
})();
