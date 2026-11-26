/* letitedit drawing hand: folkTale. Built from motion\runtime\looks-src (node build.mjs); don't edit this file.
 * Includes code from anidoodle (https://github.com/alexgreensh/anidoodle, commit 9c20e77), Copyright 2026 Alex Greenshpun, under the
 * Apache License 2.0: LICENSE-anidoodle.txt and NOTICE-anidoodle.txt beside this file. Changed by letitedit: see the headers in
 * looks-src. The rest is letitedit's own, GPL-3.0-or-later. Loaded into a code scene's page only when its script says M.look.folkTale. */
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
      const q = c[Math.min(c.length - 1, i + 1)], o = c[Math.max(0, i - 1)], dx = q[0] - o[0], dy = q[1] - o[1], len2 = Math.hypot(dx, dy) || 1, r = r0 + (r1 - r0) * i / (c.length - 1);
      L.push([p[0] - dy / len2 * r, p[1] + dx / len2 * r]);
      R.push([p[0] + dy / len2 * r, p[1] - dx / len2 * r]);
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
  var inside = (pts, x, y) => {
    let k = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const a = pts[i], b = pts[j];
      if (a[1] > y !== b[1] > y && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) k = !k;
    }
    return k;
  };

  // motion/runtime/looks-src/anidoodle/folkTaleKit.ts
  var PAPER = "#f4edda";
  var HAZE = "#f2e9c9";
  var GRAPH = "#6f665a";
  var LIGHT = [-0.6, -0.8];
  var lighten = (c, k) => mix(c, "#fffbe8", clamp2(k));
  var darken = (c, k) => mix(c, "#17170d", clamp2(k));
  var far = (c, d) => mix(c, HAZE, clamp2(d) * 0.85);
  var bbox2 = (pts) => {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const [x, y] of pts) {
      if (x < x0) x0 = x;
      if (y < y0) y0 = y;
      if (x > x1) x1 = x;
      if (y > y1) y1 = y;
    }
    return [x0, y0, x1, y1];
  };
  var trace = (c, pts, closed = true) => {
    c.beginPath();
    pts.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
    if (closed) c.closePath();
  };
  var len = (s) => {
    let l = 0;
    for (let i = 1; i < s.length; i++) l += Math.hypot(s[i][0] - s[i - 1][0], s[i][1] - s[i - 1][1]);
    return l;
  };
  var cutAt = (s, p) => {
    if (p >= 1) return s;
    if (p <= 0) return s.slice(0, 1);
    const n = (s.length - 1) * p, i = Math.floor(n), f = n - i, out = s.slice(0, i + 1);
    if (f > 1e-9 && i + 1 < s.length) out.push([s[i][0] + (s[i + 1][0] - s[i][0]) * f, s[i][1] + (s[i + 1][1] - s[i][1]) * f]);
    return out;
  };
  var tan = (s, i) => {
    const a = s[Math.max(0, i - 1)], b = s[Math.min(s.length - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    return [dx / l, dy / l];
  };
  var ribbonOf = (s, hw) => {
    const L = [], R = [], n = s.length;
    for (let i = 0; i < n; i++) {
      const t = i / Math.max(1, n - 1), [dx, dy] = tan(s, i), w = hw(t);
      L.push([s[i][0] - dy * w, s[i][1] + dx * w]);
      R.push([s[i][0] + dy * w, s[i][1] - dx * w]);
    }
    return [...L, ...R.reverse()];
  };
  var smooth2 = (pts, per = 8, closed = false) => sample(pts, closed, per);
  var at = (x, y, a, r) => [x + Math.cos(a) * r, y + Math.sin(a) * r];
  var pencil = (c, L, p = 1) => {
    if (p <= 0 || L.pts.length < 2) return;
    const { w = 1.1, a = 0.72, seed, closed = false, per = 6, col = GRAPH, retrace = true } = L, r = rng(seed * 13 + 1);
    const ctrl = closed ? [...L.pts, L.pts[0]] : L.pts;
    const pass = (jit, alpha, wk, sd) => {
      const j = ctrl.map(([x, y]) => [x + (r() - 0.5) * jit, y + (r() - 0.5) * jit]), s = sample(j, false, per), n = s.length, m = p >= 1 ? n : Math.max(2, Math.ceil(n * p));
      c.strokeStyle = col;
      c.lineCap = "round";
      c.lineJoin = "round";
      for (let i = 0; i < m - 1; i += 3) {
        const t = i / Math.max(1, n - 1), nz = fractal(sd, i * 0.19, 3.7, 1, 1, 2), end = Math.min(1, t / 0.07 + 0.4, (1 - t) / 0.09 + 0.35);
        c.globalAlpha = alpha * clamp2(0.4 + 0.85 * nz) * end;
        c.lineWidth = w * wk * (0.7 + 0.6 * nz);
        c.beginPath();
        c.moveTo(s[i][0], s[i][1]);
        for (let k = i + 1; k <= Math.min(m - 1, i + 3); k++) c.lineTo(s[k][0], s[k][1]);
        c.stroke();
      }
    };
    pass(0.9, a, 1, seed);
    if (retrace) pass(1.8, a * 0.3, 0.6, seed + 77);
    c.globalAlpha = 1;
  };
  var sketch = (c, lines, p) => {
    if (p <= 0) return;
    if (p >= 1) {
      lines.forEach((l) => pencil(c, l, 1));
      return;
    }
    const ls = lines.map((l) => len(l.pts) + 12), tot = ls.reduce((a, b) => a + b, 0);
    let acc = 0;
    const at2 = p * tot;
    for (let i = 0; i < lines.length; i++) {
      if (acc >= at2) break;
      pencil(c, lines[i], clamp2((at2 - acc) / ls[i]));
      acc += ls[i];
    }
  };
  var drag = (c, x, y, ang, l, w, a, r) => {
    const dx = Math.cos(ang), dy = Math.sin(ang), nx = -dy, ny = dx, k = 3 + Math.floor(r() * 2), bow = (r() - 0.5) * l * 0.18;
    for (let b = 0; b < k; b++) {
      const off = (b - (k - 1) / 2) * w * 0.5 + (r() - 0.5) * w * 0.3, l0 = l * r() * 0.3, l1 = l * (0.6 + r() * 0.4);
      c.globalAlpha = a * (0.3 + 0.7 * r());
      c.lineWidth = w * (0.22 + 0.3 * r());
      const x0 = x + dx * l0 + nx * off, y0 = y + dy * l0 + ny * off, x1 = x + dx * l1 + nx * off, y1 = y + dy * l1 + ny * off;
      c.beginPath();
      c.moveTo(x0, y0);
      c.quadraticCurveTo((x0 + x1) / 2 + nx * bow, (y0 + y1) / 2 + ny * bow, x1, y1);
      c.stroke();
    }
  };
  var gouache = (c, poly2, col, o) => {
    const { seed, a = 1, wob = 0 } = o, r = rng(seed * 7 + 5);
    const s = wob ? poly2.map(([x, y]) => [x + (fractal(seed, x * 0.05, y * 0.05, 1, 1, 2) - 0.5) * wob, y + (fractal(seed + 3, x * 0.05, y * 0.05, 1, 1, 2) - 0.5) * wob]) : poly2;
    c.globalAlpha = a;
    c.fillStyle = col;
    trace(c, s);
    c.fill();
    if (!o.tex && !o.mottle && !o.rim) {
      c.globalAlpha = 1;
      return;
    }
    c.save();
    trace(c, s);
    c.clip();
    const [x0, y0, x1, y1] = bbox2(s), bw = x1 - x0, bh = y1 - y0;
    if (o.tex) {
      const t = o.tex;
      c.lineCap = "round";
      for (let i = 0; i < t.n; i++) {
        c.strokeStyle = t.cols[i % t.cols.length];
        drag(c, x0 + r() * bw, y0 + r() * bh, t.ang + (r() - 0.5) * (t.jit ?? 0.3), t.len * (0.5 + r() * 0.7), t.w, (t.a ?? 0.35) * a, r);
      }
    }
    if (o.mottle) {
      const m = o.mottle, fq = m.freq ?? 0.06;
      for (let i = 0, tries = 0; i < m.n && tries < m.n * 4; tries++) {
        const x = x0 + r() * bw, y = y0 + r() * bh;
        if (fractal(seed + 11, x * fq, y * fq, 1, 1, 2) < 0.47 + r() * 0.12) continue;
        i++;
        const rr = m.r * (0.35 + r() * 0.8);
        c.globalAlpha = (m.a ?? 0.4) * (0.4 + 0.6 * r()) * a;
        c.fillStyle = m.cols[i % m.cols.length];
        c.beginPath();
        c.ellipse(x, y, rr, rr * (0.55 + r() * 0.4), r() * 3, 0, Math.PI * 2);
        c.fill();
      }
    }
    if (o.rim) {
      c.globalAlpha = (o.rimA ?? 0.4) * a;
      c.strokeStyle = o.rim;
      c.lineWidth = (o.rimW ?? 2) * 2;
      c.lineJoin = "round";
      trace(c, s);
      c.stroke();
    }
    c.restore();
    c.globalAlpha = 1;
  };
  var reveal = (c, box, ang, p, seed, fn) => {
    if (p >= 1) {
      fn();
      return;
    }
    if (p <= 0) return;
    const dx = Math.cos(ang), dy = Math.sin(ang), cs = [[box[0], box[1]], [box[2], box[1]], [box[0], box[3]], [box[2], box[3]]];
    let u0 = 1e9, u1 = -1e9, v0 = 1e9, v1 = -1e9;
    cs.forEach(([x, y]) => {
      const u = x * dx + y * dy, v = -x * dy + y * dx;
      u0 = Math.min(u0, u);
      u1 = Math.max(u1, u);
      v0 = Math.min(v0, v);
      v1 = Math.max(v1, v);
    });
    const amp = Math.min(60, (u1 - u0) * 0.12 + 6), thr = u0 - amp + (u1 - u0 + 2 * amp) * p, pts = [], toXY = (u, v) => [u * dx - v * dy, u * dy + v * dx];
    pts.push(toXY(u0 - 50, v0 - 50));
    for (let v = v0 - 50; v <= v1 + 50; v += 8) pts.push(toXY(thr + (fractal(seed, v * 0.018, p * 2, 1, 1, 2) - 0.5) * amp * 2, v));
    pts.push(toXY(thr, v1 + 50), toXY(u0 - 50, v1 + 50));
    c.save();
    trace(c, pts);
    c.clip();
    fn();
    c.restore();
  };
  var faded = (g, box, mask, draw) => {
    const e = g.env, k = e.scale, DW = Math.round(e.W * k), DH = Math.round(e.H * k), key = `ftk:scratch:${DW}x${DH}`;
    let L = e.cache.get(key);
    if (!L) {
      L = e.canvas(DW, DH);
      e.cache.set(key, L);
    }
    const x0 = Math.max(0, Math.floor(box[0] * k) - 2), y0 = Math.max(0, Math.floor(box[1] * k) - 2), x1 = Math.min(DW, Math.ceil(box[2] * k) + 2), y1 = Math.min(DH, Math.ceil(box[3] * k) + 2);
    if (x1 <= x0 || y1 <= y0) return;
    const s = L.ctx;
    s.save();
    s.setTransform(1, 0, 0, 1, 0, 0);
    s.globalAlpha = 1;
    s.globalCompositeOperation = "source-over";
    s.clearRect(x0, y0, x1 - x0, y1 - y0);
    s.beginPath();
    s.rect(x0, y0, x1 - x0, y1 - y0);
    s.clip();
    s.setTransform(k, 0, 0, k, 0, 0);
    draw(s);
    s.globalAlpha = 1;
    s.globalCompositeOperation = "destination-in";
    mask(s);
    s.restore();
    const c = g.cur;
    c.save();
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.globalAlpha = 1;
    c.globalCompositeOperation = "source-over";
    c.drawImage(L.canvas, x0, y0, x1 - x0, y1 - y0, x0, y0, x1 - x0, y1 - y0);
    c.restore();
  };
  var ramp = (m, box, a, b, stops) => {
    const gr = m.createLinearGradient(a[0], a[1], b[0], b[1]);
    stops.forEach(([t, v]) => gr.addColorStop(t, `rgba(0,0,0,${clamp2(v)})`));
    m.fillStyle = gr;
    m.fillRect(box[0] - 4, box[1] - 4, box[2] - box[0] + 8, box[3] - box[1] + 8);
  };
  var radial = (m, box, cx, cy, r0, r1, stops, sy = 1) => {
    m.save();
    m.translate(cx, cy);
    m.scale(1, sy);
    const gr = m.createRadialGradient(0, 0, r0, 0, 0, r1);
    stops.forEach(([t, v]) => gr.addColorStop(t, `rgba(0,0,0,${clamp2(v)})`));
    m.fillStyle = gr;
    m.fillRect(-1e4, -1e4, 2e4, 2e4);
    m.restore();
    void box;
  };
  var glowBand = (c, box, col, stops, vertical = true) => {
    const gr = vertical ? c.createLinearGradient(0, box[1], 0, box[3]) : c.createLinearGradient(box[0], 0, box[2], 0);
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(col.slice(i, i + 2), 16));
    stops.forEach(([t, v]) => gr.addColorStop(t, `rgba(${r},${g},${b},${clamp2(v)})`));
    c.globalAlpha = 1;
    c.fillStyle = gr;
    c.fillRect(box[0], box[1], box[2] - box[0], box[3] - box[1]);
  };
  var rgba = (col, a) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(col.slice(i, i + 2), 16));
    return `rgba(${r},${g},${b},${clamp2(a)})`;
  };
  var stroke = (c, ctrl, w0, w1, col, a = 1, p = 1, per = 6) => {
    if (p <= 0) return;
    const s = cutAt(smooth2(ctrl, per), p), full = p >= 1;
    const poly2 = ribbonOf(s, (t) => {
      const tt = full ? t : t * p;
      return Math.max(0.15, (w0 + (w1 - w0) * tt) / 2);
    });
    c.globalAlpha = a;
    c.fillStyle = col;
    trace(c, poly2);
    c.fill();
    c.globalAlpha = 1;
  };
  var leafGeom = (L) => {
    const n = L.serr ? 30 : 16, ux = Math.cos(L.a), uy = Math.sin(L.a), vx = -uy, vy = ux, st = L.stalk ?? 0, bend = L.bend ?? 0, round = L.round ?? 0.78, cord = L.cord ?? 0;
    const c = [], ts = [];
    for (let i = 0; i < n; i++) {
      const t = -cord + (1 + cord) * i / (n - 1), u = st + L.len * t, v = bend * L.len * Math.max(0, t) ** 2;
      c.push([L.x + ux * u + vx * v, L.y + uy * u + vy * v]);
      ts.push(t);
    }
    const hw = (i) => {
      const uu = (ts[i] + cord) / (1 + cord), b = L.wid / 2 * Math.pow(Math.sin(Math.PI * Math.pow(Math.min(1, uu), round)), cord ? 0.5 : 0.85);
      return L.serr ? b * (1 + (i % 2 ? L.serr : -L.serr * 0.4)) : b;
    };
    const left = [], right = [];
    c.forEach((p, i) => {
      const [dx, dy] = tan(c, i), w = hw(i);
      left.push([p[0] - dy * w, p[1] + dx * w]);
      right.push([p[0] + dy * w, p[1] - dx * w]);
    });
    const ia = Math.round(cord / (1 + cord) * (n - 1)), idx = (t) => Math.max(0, Math.min(n - 1, Math.round((t + cord) / (1 + cord) * (n - 1))));
    return { c, left, right, outline: [...left, ...right.slice().reverse()], n, ia, idx };
  };
  var litLeft = (L) => {
    const vx = -Math.sin(L.a), vy = Math.cos(L.a);
    return vx * LIGHT[0] + vy * LIGHT[1] > 0;
  };
  var lerpP2 = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  var leaf = (c, L, p = 1) => {
    if (p <= 0) return;
    const d = L.d ?? 0;
    if (d >= 0.93) {
      lineLeaf(c, L, p);
      return;
    }
    const G = leafGeom(L), grow = clamp2(p / 0.6), det = clamp2((p - 0.6) / 0.4), r = rng(L.seed), a = 1 - 0.5 * d;
    const lit = far(lighten(L.col, 0.16), d), shd = far(darken(L.col, 0.2), d), k = Math.max(2, Math.ceil(G.n * grow));
    const halfL = [...G.c.slice(0, k), ...G.left.slice(0, k).reverse()], halfR = [...G.c.slice(0, k), ...G.right.slice(0, k).reverse()], ll = litLeft(L);
    if (L.stalk) stroke(c, [[L.x, L.y], G.c[G.ia]], Math.max(1.6, L.wid * 0.05), Math.max(1.2, L.wid * 0.04), far(darken(L.col, 0.2), d), a);
    const mid = far(L.col, d);
    gouache(c, halfL, ll ? mix(mid, lit, 0.55) : mix(mid, shd, 0.55), { seed: L.seed, a });
    gouache(c, halfR, ll ? mix(mid, shd, 0.55) : mix(mid, lit, 0.55), { seed: L.seed + 1, a });
    if (grow >= 1 && d < 0.85) for (const [half, side, isLit] of [[halfL, G.left, ll], [halfR, G.right, !ll]]) {
      c.save();
      trace(c, half);
      c.clip();
      const ns = Math.round(Math.max(5, L.len / 4.5) * (1 - d * 0.5));
      for (let i = 0; i < ns; i++) {
        const t = 0.02 + r() * 0.95, bi = G.idx(t), base = G.c[bi], e = side[G.idx(Math.min(1, t + 0.1))], from = lerpP2(base, e, r() * 0.25), to = lerpP2(base, e, 0.65 + r() * 0.45), col = isLit ? mix(lit, lighten(L.col, 0.35), r() * 0.6) : mix(shd, darken(L.col, 0.4), r() * 0.6);
        stroke(c, [from, lerpP2(from, to, 0.5), to], Math.max(1.4, L.wid * (0.07 + r() * 0.08)), Math.max(0.6, L.wid * 0.03), far(col, d), (0.3 + r() * 0.35) * a, 1, 3);
      }
      c.restore();
    }
    if (det <= 0) return;
    const O = G.outline, area = L.len * L.wid * 0.6, tex = 1 - d, [bx0, by0, bx1, by1] = bbox2(O);
    c.save();
    trace(c, O);
    c.clip();
    c.lineCap = "round";
    const nd = Math.round(area / 90 * det * tex);
    for (let i = 0; i < nd; i++) {
      c.strokeStyle = r() < 0.5 ? darken(L.col, 0.3) : lighten(L.col, 0.08);
      const x = bx0 + r() * (bx1 - bx0), y = by0 + r() * (by1 - by0);
      c.globalAlpha = (0.1 + r() * 0.16) * a;
      c.lineWidth = 1 + r() * Math.max(1, L.wid * 0.04);
      const an = L.a + (r() < 0.5 ? 0.7 : -0.7) + (r() - 0.5) * 0.5, l = L.wid * (0.08 + r() * 0.18);
      c.beginPath();
      c.moveTo(x, y);
      c.lineTo(x + Math.cos(an) * l, y + Math.sin(an) * l);
      c.stroke();
    }
    const nm = Math.round(area / 22 * det * tex);
    for (let i = 0, t = 0; i < nm && t < nm * 4; t++) {
      const x = bx0 + r() * (bx1 - bx0), y = by0 + r() * (by1 - by0);
      if (fractal(L.seed, x * 0.08, y * 0.08, 1, 1, 2) < 0.52) continue;
      i++;
      const l = 0.8 + r() * Math.max(1.2, L.wid * 0.05), an = r() * 3.14;
      c.globalAlpha = (0.14 + r() * 0.24) * a;
      c.strokeStyle = r() < 0.7 ? lighten(L.col, 0.45) : darken(L.col, 0.4);
      c.lineWidth = 0.6 + r() * Math.max(0.6, L.wid * 0.022);
      c.beginPath();
      c.moveTo(x, y);
      c.lineTo(x + Math.cos(an) * l, y + Math.sin(an) * l);
      c.stroke();
    }
    const vcol = far(L.vein ?? lighten(L.col, 0.42), d), nv = Math.max(3, Math.min(8, Math.round(L.len / 20))), shown = Math.round(nv * det), vw = Math.max(0.55, L.wid * 0.022);
    stroke(c, G.c.slice(G.ia, Math.max(G.ia + 2, G.idx(0.94))), Math.max(0.9, L.wid * 0.045), 0.3, vcol, 0.75 * a, det);
    if (L.tri) for (const side of [G.left, G.right]) stroke(c, [G.c[G.ia], lerpP2(G.c[G.idx(0.1)], side[G.idx(0.12)], 0.6), lerpP2(G.c[G.idx(0.45)], side[G.idx(0.5)], 0.72)], vw * 1.4, 0.3, vcol, 0.6 * a, det);
    for (let i = 0; i < shown; i++) {
      const t = 0.1 + 0.72 * (i + 0.5) / nv, bi = G.idx(t), base = G.c[bi], fwd = G.idx(Math.min(1, t + 0.16));
      for (const side of [G.left, G.right]) stroke(c, [base, lerpP2(base, side[bi], 0.5), lerpP2(base, side[fwd], 0.8)], vw, 0.2, vcol, (0.28 + r() * 0.18) * a);
    }
    c.globalAlpha = 0.3 * a * det;
    c.strokeStyle = far(darken(L.col, 0.5), d);
    c.lineWidth = Math.max(1.2, L.wid * 0.03);
    trace(c, O);
    c.stroke();
    c.restore();
    c.globalAlpha = 1;
  };
  var lineLeaf = (c, L, p = 1, wash) => {
    const G = leafGeom(L);
    if (wash && p >= 0.5) {
      c.globalAlpha = 0.35;
      c.fillStyle = wash;
      trace(c, G.outline);
      c.fill();
      c.globalAlpha = 1;
    }
    pencil(c, { pts: G.outline.filter((_, i) => i % 2 === 0), seed: L.seed, w: 0.8, a: 0.55, closed: true, per: 4, retrace: false }, clamp2(p / 0.8));
    if (p > 0.8) pencil(c, { pts: G.c.filter((_, i) => i % 3 === 0).slice(0, -1), seed: L.seed + 3, w: 0.6, a: 0.4, per: 4, retrace: false }, clamp2((p - 0.8) / 0.2));
  };
  var petal = (c, cx, cy, ang, r0, l, w, lit, shd, seed, grow = 1, a = 1) => {
    const r = rng(seed), bend = (r() - 0.5) * 0.35, ll = l * grow, n = 9, s = [];
    for (let i = 0; i < n; i++) {
      const t = i / (n - 1), rr = r0 + ll * t, aa = ang + bend * t * t * (l / Math.max(1, rr)) * 0.6;
      s.push([cx + Math.cos(aa) * rr, cy + Math.sin(aa) * rr]);
    }
    const hw = (t) => w / 2 * Math.pow(Math.sin(Math.PI * Math.pow(Math.min(1, t * 0.97 + 0.03), 0.62)), 0.8);
    const L = [], R = [];
    s.forEach((p, i) => {
      const [dx, dy] = tan(s, i), h = hw(i / (n - 1));
      L.push([p[0] - dy * h, p[1] + dx * h]);
      R.push([p[0] + dy * h, p[1] - dx * h]);
    });
    const lft = Math.cos(ang + Math.PI / 2) * LIGHT[0] + Math.sin(ang + Math.PI / 2) * LIGHT[1] > 0;
    c.globalAlpha = a;
    c.fillStyle = lft ? lit : shd;
    trace(c, [...s, ...L.slice().reverse()]);
    c.fill();
    c.fillStyle = lft ? shd : lit;
    trace(c, [...s, ...R.slice().reverse()]);
    c.fill();
    c.strokeStyle = darken(shd, 0.25);
    c.lineCap = "round";
    for (let k = 0; k < 5; k++) {
      const off = (k - 2) * 0.17, from = 1 + Math.floor(r() * 2), to = n - 2 - Math.floor(r() * 3);
      c.globalAlpha = a * (0.18 + r() * 0.2);
      c.lineWidth = Math.max(0.5, w * 0.06);
      c.beginPath();
      for (let i = from; i <= to; i++) {
        const [dx, dy] = tan(s, i), h = hw(i / (n - 1)) * off * 2;
        const x = s[i][0] - dy * h, y = s[i][1] + dx * h;
        i === from ? c.moveTo(x, y) : c.lineTo(x, y);
      }
      c.stroke();
    }
    c.globalAlpha = a * 0.35;
    c.strokeStyle = darken(shd, 0.3);
    c.lineWidth = Math.max(0.6, w * 0.07);
    trace(c, [...L, ...R.slice().reverse()]);
    c.stroke();
    c.globalAlpha = a * 0.3;
    c.strokeStyle = lighten(lit, 0.5);
    c.lineWidth = Math.max(0.5, w * 0.08);
    c.beginPath();
    c.moveTo(s[2][0], s[2][1]);
    for (let i = 3; i < n - 1; i++) c.lineTo(s[i][0], s[i][1]);
    c.stroke();
    c.globalAlpha = 1;
  };
  var sunflower = (c, S, p = 1) => {
    if (p <= 0) return;
    const d = S.d ?? 0, n = S.n ?? 21, pl = S.pl ?? S.r * 1.25, pw = S.pw ?? S.r * 0.42, r = rng(S.seed), a = 1 - 0.45 * d;
    const units = 2 * n + 6, u = p * units;
    c.save();
    c.translate(S.x, S.y);
    c.rotate(S.rot);
    c.scale(1, S.sq);
    const [Y, YD, YB, YBd] = S.pal ?? ["#f6c72b", "#dd9314", "#c98612", "#9c5f0e"];
    for (let ring = 0; ring < 2; ring++) for (let i = 0; i < n; i++) {
      const idx = ring * n + i;
      if (idx >= u) break;
      const g = clamp2(u - idx), ang = (i + (ring ? 0 : 0.5)) / n * Math.PI * 2 + (r() - 0.5) * 0.12, ln = pl * (ring ? 0.78 + r() * 0.42 : 0.7 + r() * 0.35), wd = pw * (0.75 + r() * 0.5);
      petal(c, 0, 0, ang, S.r * (ring ? 0.9 : 0.95), ln, wd, far(ring ? Y : YB, d), far(ring ? YD : YBd, d), S.seed * 100 + idx, g, a);
    }
    const dp = clamp2((u - 2 * n) / 6);
    if (dp > 0) {
      c.globalAlpha = a * clamp2(dp * 3);
      c.fillStyle = far("#3f2a12", d);
      c.beginPath();
      c.arc(0, 0, S.r * 1.02, 0, Math.PI * 2);
      c.fill();
      if (dp > 0.3) {
        c.fillStyle = far("#6d5220", d);
        c.beginPath();
        c.arc(0, 0, S.r * 0.8, 0, Math.PI * 2);
        c.fill();
        c.fillStyle = far("#8a6c2c", d);
        c.beginPath();
        c.arc(-S.r * 0.05, -S.r * 0.05, S.r * 0.66, 0, Math.PI * 2);
        c.fill();
      }
      if (dp > 0.5) {
        c.fillStyle = far("#4a3214", d);
        c.beginPath();
        c.arc(0, 0, S.r * 0.52, 0, Math.PI * 2);
        c.fill();
        c.fillStyle = far("#2d1d0b", d);
        c.beginPath();
        c.arc(S.r * 0.03, S.r * 0.03, S.r * 0.34, 0, Math.PI * 2);
        c.fill();
      }
      if (dp > 0.7 && d < 0.7) {
        const q = clamp2((dp - 0.7) / 0.3), rr = rng(S.seed + 9), R = S.r;
        c.lineCap = "round";
        const ring = (r0, r1, n2, cols, w, al) => {
          const rr2 = rng(S.seed + Math.round(r0 * 7));
          for (let i = 0; i < Math.round(n2 * q); i++) {
            const th = rr2() * Math.PI * 2, rad = r0 + (r1 - r0) * rr2(), l = w * (1.2 + rr2() * 1.5);
            c.globalAlpha = a * al * (0.5 + rr2() * 0.5);
            c.strokeStyle = cols[i % cols.length];
            c.lineWidth = w * (0.6 + rr2() * 0.5);
            c.beginPath();
            c.arc(0, 0, rad, th, th + l / rad);
            c.stroke();
          }
        };
        ring(R * 0.84, R * 1, R * 3, ["#2a1a08", "#5a3c16", "#1e1206"], R * 0.07, 0.8);
        ring(R * 0.56, R * 0.82, R * 3.4, ["#b09048", "#7a5a22", "#c8a85a", "#5a4018"], R * 0.07, 0.75);
        ring(R * 0.36, R * 0.56, R * 2, ["#3a2610", "#6a4a1e"], R * 0.06, 0.7);
        const Nn = Math.round(R * R * 0.05 * q);
        for (let i = 0; i < Nn; i++) {
          const rad = Math.sqrt((i + 0.5) / Math.max(1, R * R * 0.05)) * R * 0.36, th = i * 2.39996;
          c.globalAlpha = a * 0.6;
          c.fillStyle = i % 3 ? "#1a1006" : "#4a3214";
          c.beginPath();
          c.arc(Math.cos(th) * rad, Math.sin(th) * rad, R * 0.028, 0, Math.PI * 2);
          c.fill();
        }
        c.globalAlpha = a * 0.3;
        c.strokeStyle = "#f0d078";
        c.lineWidth = R * 0.07;
        c.beginPath();
        c.arc(0, 0, R * 0.7, Math.PI * 1.05, Math.PI * 1.6);
        c.stroke();
        c.globalAlpha = a * 0.4;
        c.strokeStyle = "#140b04";
        c.lineWidth = R * 0.1;
        c.beginPath();
        c.arc(0, 0, R * 0.95, Math.PI * 0.05, Math.PI * 0.75);
        c.stroke();
      }
    }
    c.restore();
    c.globalAlpha = 1;
  };
  var daisy = (c, x, y, r, seed, d = 0, sq = 0.62, p = 1) => {
    if (p <= 0) return;
    const rr = rng(seed), n = 13, a = (1 - 0.5 * d) * clamp2(p * 1.5);
    c.save();
    c.translate(x, y);
    c.rotate((rr() - 0.5) * 0.5);
    c.scale(1, sq);
    for (let i = 0; i < n; i++) {
      const th = i / n * Math.PI * 2 + rr() * 0.2, l = r * (0.85 + rr() * 0.3);
      c.globalAlpha = a;
      c.fillStyle = far(Math.sin(th) > 0.3 ? "#ddd8cc" : "#fbf8ef", d);
      c.beginPath();
      c.ellipse(Math.cos(th) * l * 0.55, Math.sin(th) * l * 0.55, l * 0.5, r * 0.19, th, 0, Math.PI * 2);
      c.fill();
    }
    c.globalAlpha = a;
    c.fillStyle = far("#e8b62a", d);
    c.beginPath();
    c.arc(0, 0, r * 0.3, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = far("#b9791a", d);
    c.beginPath();
    c.arc(r * 0.07, r * 0.08, r * 0.17, 0, Math.PI * 2);
    c.fill();
    c.restore();
    c.globalAlpha = 1;
  };
  var bell = (c, x, y, s, ang, seed, d = 0, col = "#5d6fc4", p = 1) => {
    if (p <= 0) return;
    const r = rng(seed), a = (1 - 0.45 * d) * clamp2(p * 1.4), L = s, Wd = s * 0.78;
    c.save();
    c.translate(x, y);
    c.rotate(ang);
    const ctrl = [[-Wd * 0.1, 0], [-Wd * 0.26, L * 0.35], [-Wd * 0.33, L * 0.7], [-Wd * 0.42, L * 0.88], [-Wd * 0.62, L * 0.98], [-Wd * 0.4, L * 0.97], [-Wd * 0.24, L * 1], [0, L * 1.1], [Wd * 0.24, L * 1], [Wd * 0.4, L * 0.97], [Wd * 0.62, L * 0.98], [Wd * 0.42, L * 0.88], [Wd * 0.33, L * 0.7], [Wd * 0.26, L * 0.35], [Wd * 0.1, 0]];
    const body = sample(ctrl.map(([px, py]) => [px + (r() - 0.5) * s * 0.03, py]), true, 5);
    c.globalAlpha = a;
    c.fillStyle = far(col, d);
    trace(c, body);
    c.fill();
    c.save();
    trace(c, body);
    c.clip();
    c.fillStyle = far(darken(col, 0.32), d);
    c.beginPath();
    c.moveTo(Wd * 0.04, 0);
    c.quadraticCurveTo(Wd * 0.22, L * 0.6, Wd * 0.2, L * 1.1);
    c.lineTo(Wd, L * 1.1);
    c.lineTo(Wd, 0);
    c.fill();
    c.globalAlpha = a * 0.75;
    c.fillStyle = far(lighten(col, 0.4), d);
    c.beginPath();
    c.moveTo(-Wd * 0.12, L * 0.08);
    c.quadraticCurveTo(-Wd * 0.3, L * 0.55, -Wd * 0.26, L * 0.92);
    c.lineTo(-Wd * 0.14, L * 0.9);
    c.quadraticCurveTo(-Wd * 0.16, L * 0.5, -Wd * 0.04, L * 0.1);
    c.fill();
    c.globalAlpha = a * 0.9;
    c.fillStyle = far("#2a2a5a", d);
    c.beginPath();
    c.ellipse(0, L * 0.97, Wd * 0.26, L * 0.06, 0, 0, Math.PI * 2);
    c.fill();
    c.globalAlpha = a * 0.45;
    c.strokeStyle = far(darken(col, 0.45), d);
    c.lineWidth = Math.max(0.6, s * 0.025);
    for (const [tx2, ty2] of [[-Wd * 0.55, L * 0.97], [0, L * 1.08], [Wd * 0.55, L * 0.97]]) {
      c.beginPath();
      c.moveTo(tx2 * 0.15, L * 0.08);
      c.quadraticCurveTo(tx2 * 0.5, L * 0.6, tx2, ty2);
      c.stroke();
    }
    c.restore();
    c.globalAlpha = a;
    c.fillStyle = far("#3c5a2a", d);
    for (const sg of [-1, 1]) {
      c.beginPath();
      c.moveTo(0, -1);
      c.quadraticCurveTo(sg * Wd * 0.3, L * 0.02, sg * Wd * 0.34, -L * 0.14);
      c.quadraticCurveTo(sg * Wd * 0.12, L * 0, 0, L * 0.12);
      c.fill();
    }
    c.restore();
    c.globalAlpha = 1;
  };
  var dogRose = (c, x, y, r, rot, sq, seed, d = 0, p = 1) => {
    if (p <= 0) return;
    const rr = rng(seed), a = (1 - 0.45 * d) * clamp2(p * 1.4);
    c.save();
    c.translate(x, y);
    c.rotate(rot);
    c.scale(1, sq);
    for (let i = 0; i < 5; i++) {
      const th = i / 5 * Math.PI * 2 + rr() * 0.15, pts = [];
      for (let k = 0; k <= 12; k++) {
        const t = k / 12, phi = th + (t - 0.5) * 1.25, rad = r * (0.2 + 0.8 * Math.sin(Math.PI * t) ** 0.35) * (1 - 0.12 * Math.exp(-(((t - 0.5) * 9) ** 2)));
        pts.push([Math.cos(phi) * rad, Math.sin(phi) * rad]);
      }
      pts.push([0, 0]);
      c.globalAlpha = a;
      c.fillStyle = far(Math.sin(th) > 0.2 ? "#e48aa0" : "#f3b3c0", d);
      trace(c, pts);
      c.fill();
      c.globalAlpha = a * 0.6;
      c.fillStyle = far("#fde9e6", d);
      c.beginPath();
      c.ellipse(Math.cos(th) * r * 0.32, Math.sin(th) * r * 0.32, r * 0.2, r * 0.13, th, 0, Math.PI * 2);
      c.fill();
    }
    c.globalAlpha = a;
    c.fillStyle = far("#c9a33a", d);
    c.beginPath();
    c.arc(0, 0, r * 0.2, 0, Math.PI * 2);
    c.fill();
    for (let i = 0; i < 16; i++) {
      const th = i / 16 * Math.PI * 2, q = r * (0.24 + rr() * 0.06);
      c.fillStyle = far("#f2c936", d);
      c.beginPath();
      c.arc(Math.cos(th) * q, Math.sin(th) * q, r * 0.045, 0, Math.PI * 2);
      c.fill();
    }
    c.restore();
    c.globalAlpha = 1;
  };
  var umbel = (c, x, y, r, seed, col = "#2f3320", p = 1, a = 0.85) => {
    if (p <= 0) return;
    const rr = rng(seed), n = 11;
    c.strokeStyle = col;
    c.fillStyle = col;
    c.lineCap = "round";
    for (let i = 0; i < n; i++) {
      if (i / n > p) break;
      const th = -Math.PI / 2 + (i / (n - 1) - 0.5) * 2.4 + (rr() - 0.5) * 0.15, l = r * (0.75 + rr() * 0.35), ex = x + Math.cos(th) * l, ey = y + Math.sin(th) * l * 0.75;
      c.globalAlpha = a * 0.8;
      c.lineWidth = Math.max(1, r * 0.028);
      c.beginPath();
      c.moveTo(x, y);
      c.quadraticCurveTo((x + ex) / 2, (y + ey) / 2 - l * 0.12, ex, ey);
      c.stroke();
      for (let k = 0; k < 7; k++) {
        const t2 = -Math.PI / 2 + (k / 6 - 0.5) * 2.2, l2 = r * 0.22 * (0.7 + rr() * 0.5), fx = ex + Math.cos(t2) * l2, fy = ey + Math.sin(t2) * l2 * 0.8;
        c.globalAlpha = a * 0.7;
        c.lineWidth = Math.max(0.6, r * 0.015);
        c.beginPath();
        c.moveTo(ex, ey);
        c.lineTo(fx, fy);
        c.stroke();
        c.globalAlpha = a;
        c.beginPath();
        c.arc(fx, fy, Math.max(1.3, r * 0.03), 0, Math.PI * 2);
        c.fill();
      }
    }
    c.globalAlpha = 1;
  };
  var grass = (c, G, p = 1) => {
    if (p <= 0) return;
    const r = rng(G.seed), d = G.d ?? 0, a0 = (G.a ?? 1) * (1 - 0.45 * d), spread = G.spread ?? 14, cols = G.cols.map((k) => far(k, d)), tip = G.tip ? far(G.tip, d) : null, dry = G.dry ? far(G.dry, d) : null, per = G.clump ?? 1;
    const clumps = Math.ceil(G.n / per), m = p >= 1 ? clumps : Math.floor(clumps * p);
    c.lineCap = "round";
    for (let i = 0; i < m; i++) {
      const x = G.x0 + r() * (G.x1 - G.x0), y = G.base(x) + r() * spread, H0 = G.h[0] + (G.h[1] - G.h[0]) * r() ** 1.3, lean0 = (G.lean ?? 0.2) + (r() - 0.5) * 0.5, k = per === 1 ? 1 : Math.max(2, Math.round(per * (0.6 + r() * 0.8))), skip = G.skip?.(x, y) ?? false;
      for (let b = 0; b < k; b++) {
        const fan = k === 1 ? 0 : (b / (k - 1) - 0.5) * 1.3, h = H0 * (0.55 + r() * 0.5) * (1 - Math.abs(fan) * 0.3), lean = lean0 + fan * 0.55 + (r() - 0.5) * 0.25, w = G.w * (0.6 + r() * 0.7);
        const col = dry && r() < 0.08 ? dry : cols[Math.floor(r() * cols.length)], al = a0 * (0.6 + r() * 0.4), bx = x + (r() - 0.5) * 4;
        if (skip) continue;
        const tx = bx + lean * h, ty = y - h * (1 - Math.abs(lean) * 0.15), mx = bx + lean * h * 0.3 + (r() - 0.5) * h * 0.08, my = y - h * 0.55;
        c.globalAlpha = al;
        c.fillStyle = col;
        c.beginPath();
        c.moveTo(bx - w / 2, y);
        c.quadraticCurveTo(mx - w * 0.35, my, tx, ty);
        c.quadraticCurveTo(mx + w * 0.35, my, bx + w / 2, y);
        c.closePath();
        c.fill();
        if (tip && r() < 0.5) {
          c.globalAlpha = al * 0.7;
          c.strokeStyle = tip;
          c.lineWidth = Math.max(0.5, w * 0.28);
          c.beginPath();
          c.moveTo(bx + (mx - bx) * 0.9 - w * 0.15, my);
          c.quadraticCurveTo(mx + (tx - mx) * 0.55, my - h * 0.22, tx, ty);
          c.stroke();
        }
      }
    }
    c.globalAlpha = 1;
  };
  var limb = (c, ctrl, w0, w1, col, seed, d = 0, p = 1, shade = 0.3, grain = 1) => {
    if (p <= 0) return;
    const s = cutAt(smooth2(ctrl, 8), p), a = 1 - 0.5 * d, r = rng(seed);
    if (s.length < 2) return;
    const hw = (t) => (w0 + (w1 - w0) * t * (p >= 1 ? 1 : p)) / 2;
    const body = ribbonOf(s, hw);
    c.globalAlpha = a;
    c.fillStyle = far(col, d);
    trace(c, body);
    c.fill();
    const [tx, ty] = tan(s, Math.floor(s.length / 2)), rightLit = ty * LIGHT[0] - tx * LIGHT[1] > 0;
    const shadeSide = [];
    const n = s.length;
    for (let i = 0; i < n; i++) {
      const [dx, dy] = tan(s, i), w = hw(i / Math.max(1, n - 1)), sg = rightLit ? -1 : 1;
      shadeSide.push([s[i][0] - dy * w * sg, s[i][1] + dx * w * sg]);
    }
    const mid = s.map((q, i) => {
      const [dx, dy] = tan(s, i), w = hw(i / Math.max(1, n - 1)) * 0.15, sg = rightLit ? -1 : 1;
      return [q[0] - dy * w * sg, q[1] + dx * w * sg];
    });
    c.globalAlpha = a * 0.85;
    c.fillStyle = far(darken(col, shade), d);
    trace(c, [...mid, ...shadeSide.reverse()]);
    c.fill();
    if (grain > 0 && d < 0.8) {
      c.save();
      trace(c, body);
      c.clip();
      c.lineCap = "round";
      const L = len(s), k = Math.round(L * (w0 + w1) / 2 / 40 * grain);
      for (let i = 0; i < k; i++) {
        const t = r(), idx = Math.min(n - 2, Math.floor(t * (n - 1))), [dx, dy] = tan(s, idx), off = (r() - 0.5) * 2 * hw(t) * 0.95, x = s[idx][0] - dy * off, y = s[idx][1] + dx * off, l = 6 + r() * Math.max(10, w0 * 1.2);
        c.strokeStyle = far(r() < 0.5 ? darken(col, 0.45) : lighten(col, 0.3), d);
        drag(c, x, y, Math.atan2(dy, dx) + (r() - 0.5) * 0.15, l, Math.max(1.5, w0 * 0.12), 0.45 * a, r);
      }
      c.restore();
    }
    c.globalAlpha = 1;
  };
  var lineLimb = (w0, w1, ctrl, seed, a = 0.6) => {
    const s = smooth2(ctrl, 3), n = s.length, L = [], R = [];
    s.forEach((q, i) => {
      const [dx, dy] = tan(s, i), w = (w0 + (w1 - w0) * (i / Math.max(1, n - 1))) / 2;
      L.push([q[0] - dy * w, q[1] + dx * w]);
      R.push([q[0] + dy * w, q[1] - dx * w]);
    });
    const out = [{ pts: L, seed, a, w: 0.95, per: 3 }, { pts: R, seed: seed + 1, a: a * 0.85, w: 0.9, per: 3 }];
    if (w0 > 10) {
      const r = rng(seed);
      for (let k = 0; k < Math.round(w0 / 5); k++) {
        const i = Math.floor(r() * (n - 3)), [dx, dy] = tan(s, i), off = (r() - 0.5) * (w0 + (w1 - w0) * (i / n)) * 0.7, x = s[i][0] - dy * off, y = s[i][1] + dx * off, l = 8 + r() * 20;
        out.push({ pts: [[x, y], [x + dx * l * 0.5 + (r() - 0.5) * 2, y + dy * l * 0.5], [x + dx * l, y + dy * l]], seed: seed + 10 + k, a: a * 0.5, w: 0.7, retrace: false });
      }
    }
    return out;
  };
  var pumpkin = (c, x, y, rx, ry, seed, d = 0, p = 1, col = "#e2761c") => {
    if (p <= 0) return;
    const r = rng(seed), a = 1 - 0.45 * d, k = 9, ph = clamp2(p / 0.7), det = clamp2((p - 0.7) / 0.3);
    c.save();
    c.globalAlpha = 0.35 * a * ph;
    c.fillStyle = far("#2e3e16", d);
    c.beginPath();
    c.ellipse(x + rx * 0.28, y + ry * 0.86, rx * 1.1, ry * 0.26, 0, 0, Math.PI * 2);
    c.fill();
    const phi = Array.from({ length: k + 1 }, (_, i) => -Math.PI / 2 + Math.PI * i / k + (i && i < k ? (r() - 0.5) * 0.08 : 0));
    const mer = (f, t) => {
      const w = Math.pow(Math.sin(Math.PI * t), 0.42), yy = -ry + 2 * ry * t;
      return [x + Math.sin(f) * rx * w, y + yy * (0.82 + 0.18 * w) + Math.cos(f) * ry * 0.06];
    };
    const lobe = (f0, f1) => {
      const A = [], B = [];
      for (let s = 0; s <= 14; s++) {
        const t = s / 14;
        A.push(mer(f0, t));
        B.push(mer(f1, t));
      }
      return [...A, ...B.reverse()];
    };
    const order = Array.from({ length: k }, (_, i) => i).sort((i, j) => Math.abs(i + 0.5 - k / 2) < Math.abs(j + 0.5 - k / 2) ? 1 : -1);
    order.forEach((i, o) => {
      if (o / k > ph) return;
      const m = (i + 0.5) / k, lit = clamp2(1 - m * 0.95), base = mix(darken(col, 0.42), lighten(col, 0.1), lit), f0 = phi[i], f1 = phi[i + 1];
      gouache(c, lobe(f0, f1), far(base, d), { seed: seed + i, a, rim: far(darken(col, 0.55), d), rimW: 1.6, rimA: 0.6 });
      gouache(c, lobe(f0 + (f1 - f0) * 0.18, f1 - (f1 - f0) * 0.45).map(([px, py]) => [px, py - ry * 0.06]), far(mix(base, "#ffd070", 0.35 * lit + 0.1), d), { seed: seed + 30 + i, a: a * 0.55 });
      if (det > 0) {
        c.save();
        trace(c, lobe(f0, f1));
        c.clip();
        for (let q = 1; q < 4; q++) {
          const f = f0 + (f1 - f0) * q / 4;
          c.globalAlpha = 0.18 * a * det;
          c.strokeStyle = far(q % 2 ? darken(col, 0.4) : lighten(col, 0.35), d);
          c.lineWidth = 1.2;
          c.beginPath();
          for (let s = 1; s < 14; s++) {
            const P0 = mer(f, s / 14);
            s === 1 ? c.moveTo(P0[0], P0[1]) : c.lineTo(P0[0], P0[1]);
          }
          c.stroke();
        }
        const gr = c.createLinearGradient(0, y + ry * 0.2, 0, y + ry);
        gr.addColorStop(0, rgba("#3a1a06", 0));
        gr.addColorStop(1, rgba("#3a1a06", 0.45 * det));
        c.globalAlpha = a;
        c.fillStyle = gr;
        c.fillRect(x - rx - 2, y - ry, rx * 2 + 4, ry * 2 + 4);
        c.restore();
      }
    });
    if (det > 0) {
      c.globalAlpha = a * det;
      c.fillStyle = far(darken(col, 0.5), d);
      c.beginPath();
      c.ellipse(x, y - ry * 0.8, rx * 0.16, ry * 0.07, 0, 0, Math.PI * 2);
      c.fill();
      const sx = x + (r() - 0.5) * rx * 0.06, top = [sx + rx * 0.12, y - ry * 1.18];
      gouache(c, [[sx - rx * 0.08, y - ry * 0.8], [sx - rx * 0.07, y - ry * 1.02], [top[0] - 4, top[1] - 2], [top[0] + 4, top[1] + 3], [sx + rx * 0.07, y - ry * 1], [sx + rx * 0.09, y - ry * 0.8]], far("#6a6a2c", d), { seed: seed + 50, a, rim: far("#2e2e10", d), rimA: 0.6, rimW: 1.2 });
      stroke(c, [[sx - rx * 0.03, y - ry * 0.82], [sx - rx * 0.02, y - ry * 1], [top[0] - 2, top[1]]], 2, 1, far("#a8a45a", d), 0.7 * a);
    }
    c.restore();
    c.globalAlpha = 1;
  };
  var gourdLeaf = (c, x, y, s, rot, sq, col, seed, d = 0, p = 1) => {
    if (p <= 0) return;
    const r = rng(seed), a = 1 - 0.45 * d, g = clamp2(p / 0.6), det = clamp2((p - 0.6) / 0.4);
    c.save();
    c.translate(x, y);
    c.rotate(rot);
    c.scale(1, sq);
    const tips = [-1.75, -0.9, 0, 0.9, 1.75].map((t) => t + (r() - 0.5) * 0.15), lens = tips.map(() => 0.85 + r() * 0.2);
    const rad = (th) => {
      let m = 0;
      tips.forEach((t, k) => {
        m = Math.max(m, lens[k] * Math.exp(-(((th - t) / 0.36) ** 2)));
      });
      return s * g * (0.62 + 0.38 * m) * (1 - 0.3 * (Math.abs(th) / Math.PI) ** 2) * (1 + 0.025 * Math.sin(th * 46 + seed));
    };
    const out = [];
    for (let i = 0; i <= 90; i++) {
      const th = -Math.PI * 0.9 + i / 90 * Math.PI * 1.8;
      out.push([Math.sin(th) * rad(th), -Math.cos(th) * rad(th) * 0.95]);
    }
    const lft = out.filter(([px]) => px <= 0), rgt = out.filter(([px]) => px >= 0);
    gouache(c, [[0, 0], ...lft], far(lighten(col, 0.08), d), { seed, a });
    gouache(c, [[0, 0], ...rgt], far(darken(col, 0.15), d), { seed: seed + 1, a });
    if (det > 0) {
      c.save();
      trace(c, [[0, 0], ...out]);
      c.clip();
      c.lineCap = "round";
      for (let i = 0; i < Math.round(s * 0.9 * det); i++) {
        const th = (r() - 0.5) * 3.2, q = r() * rad(th) * 0.95, px = Math.sin(th) * q, py = -Math.cos(th) * q, l = 3 + r() * s * 0.12, an = th - Math.PI / 2 + (r() - 0.5) * 0.6;
        c.globalAlpha = (0.12 + r() * 0.16) * a;
        c.strokeStyle = far(r() < 0.5 ? darken(col, 0.35) : lighten(col, 0.3), d);
        c.lineWidth = 1 + r() * s * 0.025;
        c.beginPath();
        c.moveTo(px, py);
        c.lineTo(px + Math.cos(an) * l, py + Math.sin(an) * l);
        c.stroke();
      }
      tips.forEach((th, v) => {
        const R = rad(th) * 0.9, ex = Math.sin(th) * R, ey = -Math.cos(th) * R * 0.95;
        stroke(c, [[0, 0], [ex * 0.5 + (r() - 0.5) * 3, ey * 0.5], [ex, ey]], s * 0.035, 0.6, far(lighten(col, 0.45), d), 0.65 * a, det);
        for (let q = 1; q <= 3; q++) {
          const t = q / 4.2, bx = ex * t, by = ey * t;
          for (const sg of [-1, 1]) {
            const th2 = th + sg * 0.7, l = R * 0.28 * (1 - t * 0.4);
            stroke(c, [[bx, by], [bx + Math.sin(th2) * l * 0.6, by - Math.cos(th2) * l * 0.6], [bx + Math.sin(th2 - sg * 0.3) * l, by - Math.cos(th2 - sg * 0.3) * l]], s * 0.014, 0.3, far(lighten(col, 0.35), d), 0.4 * a, det);
          }
        }
        void v;
      });
      c.restore();
      c.globalAlpha = 0.45 * a;
      c.strokeStyle = far(darken(col, 0.55), d);
      c.lineWidth = 1.6;
      trace(c, [[0, 0], ...out]);
      c.stroke();
    }
    c.restore();
    c.globalAlpha = 1;
  };
  var tendril = (c, x, y, s, dir, seed, col, d = 0, p = 1) => {
    if (p <= 0) return;
    const r = rng(seed), pts = [[x, y]];
    let a = dir, cx = x, cy = y, k = 0.05;
    for (let i = 0; i < 40; i++) {
      a += k;
      k *= 1.07;
      const st = s * 0.05 * (1 - i / 60);
      cx += Math.cos(a) * st;
      cy += Math.sin(a) * st;
      pts.push([cx, cy]);
    }
    void r;
    stroke(c, pts, 1.6, 0.5, far(col, d), 0.9 * (1 - 0.4 * d), p, 2);
  };
  var sheet = (g, glow) => {
    const c = g.cur, e = g.env;
    c.save();
    c.setTransform(e.scale, 0, 0, e.scale, 0, 0);
    c.globalAlpha = 1;
    c.fillStyle = PAPER;
    c.fillRect(0, 0, e.W, e.H);
    glow.forEach(([x, y, rad, col]) => {
      const gr = c.createRadialGradient(x, y, 0, x, y, rad);
      gr.addColorStop(0, rgba(col, 0.55));
      gr.addColorStop(1, rgba(col, 0));
      c.fillStyle = gr;
      c.fillRect(0, 0, e.W, e.H);
    });
    c.restore();
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
        const G = this.on(cur.L);
        for (let i = cur.n; i < n; i++) {
          const c = cur.L.ctx;
          c.save();
          this.marks[i].draw(G, 1);
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
      const G = this.on(S);
      if (q > 0) {
        S.ctx.save();
        m.draw(G, q);
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
    within(G, shape, out, fn) {
      const c = G.cur;
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

  // motion/runtime/looks-src/folkTale.ts
  var FT = { nib: 1, taper: 0.8, pressure: 0.7, retrace: false, wobble: 0.7, rough: 0.6 };
  var C = { paper: PAPER, haze: HAZE, graphite: GRAPH, sap: "#5f7a2c", olive: "#7c8b3a", leaf: "#3f5f28", ochre: "#c89a35", cadmium: "#eeb42a", orange: "#e2761c", vermilion: "#d6432a", violet: "#5d6fc4", umber: "#5a3d26", cream: "#f6ecd2", sky: "#cfe0d8" };
  var FolkHand = class extends WorkHand {
    palette = C;
    LIGHT = LIGHT;
    lighten = lighten;
    darken = darken;
    far = far;
    bbox = bbox2;
    cutAt = cutAt;
    ribbonOf = ribbonOf;
    at = at;
    rgba = rgba;
    trace = trace;
    pencil = pencil;
    sketch = sketch;
    gouache = gouache;
    reveal = reveal;
    faded = faded;
    ramp = ramp;
    radial = radial;
    glowBand = glowBand;
    stroke = stroke;
    leaf = leaf;
    lineLeaf = lineLeaf;
    leafGeom = leafGeom;
    petal = petal;
    sunflower = sunflower;
    daisy = daisy;
    bell = bell;
    dogRose = dogRose;
    umbel = umbel;
    grass = grass;
    limb = limb;
    lineLimb = lineLimb;
    pumpkin = pumpkin;
    gourdLeaf = gourdLeaf;
    tendril = tendril;
    constructor(w, h, o) {
      super(w, h, o, FT);
    }
    /** The cream sheet with its slow glow: glow = [[x, y, radius, colour], ...]. paper: false leaves it bare, for a part on its own layer. */
    page(id, o = {}) {
      const bare = o.paper === false;
      return this.work(id, { ...o, ground: bare ? null : (G) => sheet(G, o.glow ?? [[(o.w ?? this.w) * 0.9, (o.h ?? this.h) * 0.5, (o.w ?? this.w) * 0.76, "#fbf3d6"]]), finish: bare ? null : (G) => {
        G.paper("paper", 0.14);
        G.paper("coldpress", 0.07);
      } });
    }
    /** Any kit mark on the list: fn(c, p) draws it at progress p, with c the page's surface. */
    mark(W, per, fn) {
      W.add(per, (G, q) => fn(G.cur, q));
      return W;
    }
    /** A big area of paint: a wet front sweeps across it (noisy, never a fade), and it thins with depth d. */
    wash(W, poly2, color, o) {
      const box = bbox2(poly2), col = far(color, o.d ?? 0), a = (o.a ?? 1) * (1 - (o.d ?? 0) * 0.45);
      return this.mark(W, o.per ?? 3 + Math.sqrt((box[2] - box[0]) * (box[3] - box[1])) / 60, (c, p) => reveal(c, box, o.ang ?? 0.2, p, o.seed, () => gouache(c, poly2, col, { ...o, a })));
    }
    /** Pencil lines drawn in order, paced by their length. */
    lines(W, lines, o = {}) {
      return this.mark(W, o.per ?? 2 + lines.reduce((a, l) => a + len(l.pts), 0) / 140, (c, p) => sketch(c, lines, p));
    }
  };
  register("folkTale", { start: (w, h, o) => new FolkHand(w, h, o) });
})();
