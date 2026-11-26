/* letitedit drawing hand: pixelArt. Built from motion\runtime\looks-src (node build.mjs); don't edit this file.
 * Includes code from anidoodle (https://github.com/alexgreensh/anidoodle, commit 9c20e77), Copyright 2026 Alex Greenshpun, under the
 * Apache License 2.0: LICENSE-anidoodle.txt and NOTICE-anidoodle.txt beside this file. Changed by letitedit: see the headers in
 * looks-src. The rest is letitedit's own, GPL-3.0-or-later. Loaded into a code scene's page only when its script says M.look.pixelArt. */
(() => {
  // motion/runtime/looks-src/anidoodle/pixelArtKit.ts
  var PixelDraft = class _PixelDraft {
    constructor(G, H, ground) {
      this.G = G;
      this.H = H;
      this.buf = new Uint8Array(G * H).fill(ground);
    }
    G;
    H;
    buf;
    ops = [];
    strokes = [];
    pass = 0;
    open = null;
    // ---- recording
    setPass(p) {
      this.end();
      this.pass = p;
    }
    begin(kind) {
      this.end();
      this.open = { pass: this.pass, kind, a: this.ops.length, b: this.ops.length };
    }
    end() {
      if (this.open) {
        this.open.b = this.ops.length;
        if (this.open.b > this.open.a) this.strokes.push(this.open);
        this.open = null;
      }
    }
    get(x, y) {
      return x < 0 || y < 0 || x >= this.G || y >= this.H ? -1 : this.buf[y * this.G + x];
    }
    px(x, y, c) {
      x = Math.round(x);
      y = Math.round(y);
      if (x < 0 || y < 0 || x >= this.G || y >= this.H) return;
      const i = y * this.G + x;
      if (this.buf[i] === c) return;
      this.buf[i] = c;
      this.ops.push(i * 16 + c);
    }
    // ---- marks, all palette-only
    rect(x0, y0, w, h, c) {
      for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) this.px(x, y, c);
    }
    // Bresenham: one pixel per step on the major axis, never a double
    line(x0, y0, x1, y1, c) {
      x0 = Math.round(x0);
      y0 = Math.round(y0);
      x1 = Math.round(x1);
      y1 = Math.round(y1);
      const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
      let e = dx + dy;
      for (; ; ) {
        this.px(x0, y0, c);
        if (x0 === x1 && y0 === y1) break;
        const e2 = 2 * e;
        if (e2 >= dy) {
          e += dy;
          x0 += sx;
        }
        if (e2 <= dx) {
          e += dx;
          y0 += sy;
        }
      }
    }
    // cells whose centre is inside the polygon (even-odd), row by row
    static cover(pts, G, H) {
      const out = [];
      for (let y = 0; y < H; y++) {
        const yc = y + 0.5, xs = [];
        for (let i = 0; i < pts.length; i++) {
          const [x0, y0] = pts[i], [x1, y1] = pts[(i + 1) % pts.length];
          if (y0 <= yc !== y1 <= yc) xs.push(x0 + (yc - y0) / (y1 - y0) * (x1 - x0));
        }
        xs.sort((a, b) => a - b);
        for (let k = 0; k + 1 < xs.length; k += 2) for (let x = Math.max(0, Math.ceil(xs[k] - 0.5)); x <= Math.min(G - 1, Math.floor(xs[k + 1] - 0.5)); x++) out.push(y * G + x);
      }
      return out;
    }
    // 2x2 ordered dither: level 0..4 of colour b over the cell's colour a (2 = the checker half tint)
    static bayer = [[0, 2], [3, 1]];
    static dith(x, y, level) {
      return _PixelDraft.bayer[y & 1][x & 1] < level;
    }
  };
  var limb = (pts, r0, r1) => {
    const L = [], R2 = [];
    pts.forEach((p, i) => {
      const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1, r = r0 + (r1 - r0) * i / (pts.length - 1);
      L.push([p[0] - dy / l * r, p[1] + dx / l * r]);
      R2.push([p[0] + dy / l * r, p[1] - dx / l * r]);
    });
    return [...L, ...R2.reverse()];
  };
  var cleanMask = (m, G, H) => {
    const o = m.slice();
    const at = (x, y) => x < 0 || y < 0 || x >= G || y >= H ? 0 : o[y * G + x];
    for (let pass = 0, changed = true; changed && pass < 6; pass++) {
      changed = false;
      for (let y = 0; y < H; y++) for (let x = 0; x < G; x++) {
        const n = at(x - 1, y) + at(x + 1, y) + at(x, y - 1) + at(x, y + 1), i = y * G + x;
        if (o[i] && n <= 1) {
          o[i] = 0;
          changed = true;
        } else if (!o[i] && n >= 3) {
          o[i] = 1;
          changed = true;
        }
      }
    }
    return o;
  };
  var celPlan = (d, budgets, rest) => {
    const plan = [0];
    budgets.forEach((budget, p) => {
      const ss = d.strokes.filter((s) => s.pass === p);
      if (!ss.length) return;
      const w = ss.map((s) => s.kind === "fill" ? 1 : s.kind === "cluster" ? 1 + Math.sqrt(s.b - s.a) * 0.35 : 1 + Math.sqrt(s.b - s.a) * 0.8);
      const sw = w.reduce((a, b) => a + b, 0);
      ss.forEach((s, k) => {
        const cels = Math.max(1, Math.round(budget * w[k] / sw));
        for (let c = 1; c <= cels; c++) plan.push(s.a + Math.round((s.b - s.a) * c / cels));
      });
      for (let r = 0; r < rest; r++) plan.push(plan[plan.length - 1]);
    });
    return plan;
  };

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
    const a = seed % 17 * 0.37, b = seed % 11 * 0.53, L = [], R2 = [], r = rng(seed * 31 + 7);
    for (let i = 0; i < s.length; i++) {
      const t = i / (s.length - 1), p = s[i], q = s[Math.min(s.length - 1, i + 1)], o = s[Math.max(0, i - 1)], dx = q[0] - o[0], dy = q[1] - o[1], len = Math.hypot(dx, dy) || 1;
      const ends = Math.min(1, t / 0.14, (1 - t) / 0.2), tp = 1 - taper + taper * Math.pow(Math.max(0.04, ends), 0.7);
      const pr = Math.max(0.14, 1 - 0.26 * pressure + pressure * (0.3 * Math.sin(t * 5.5 + a) + 0.14 * Math.sin(t * 17 + b)));
      const w = width * tp * pr / 2, j1 = (r() - 0.5) * rough, j2 = (r() - 0.5) * rough;
      L.push([p[0] - dy / len * (w + j1), p[1] + dx / len * (w + j1)]);
      R2.push([p[0] + dy / len * (w + j2), p[1] - dx / len * (w + j2)]);
    }
    return [...L, ...R2.reverse()];
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

  // motion/runtime/looks-src/pixelFont.ts
  var R = (s) => s.split("/");
  var FONT = {
    A: R(".###./#...#/#...#/#####/#...#/#...#/#...#"),
    B: R("####./#...#/#...#/####./#...#/#...#/####."),
    C: R(".###./#...#/#..../#..../#..../#...#/.###."),
    D: R("###../#..#./#...#/#...#/#...#/#..#./###.."),
    E: R("#####/#..../#..../####./#..../#..../#####"),
    F: R("#####/#..../#..../####./#..../#..../#...."),
    G: R(".###./#...#/#..../#.###/#...#/#...#/.###."),
    H: R("#...#/#...#/#...#/#####/#...#/#...#/#...#"),
    I: R("###/.#./.#./.#./.#./.#./###"),
    J: R("..###/...#./...#./...#./...#./#..#./.##.."),
    K: R("#...#/#..#./#.#../##.../#.#../#..#./#...#"),
    L: R("#..../#..../#..../#..../#..../#..../#####"),
    M: R("#...#/##.##/#.#.#/#.#.#/#...#/#...#/#...#"),
    N: R("#...#/##..#/#.#.#/#.#.#/#..##/#...#/#...#"),
    O: R(".###./#...#/#...#/#...#/#...#/#...#/.###."),
    P: R("####./#...#/#...#/####./#..../#..../#...."),
    Q: R(".###./#...#/#...#/#...#/#.#.#/#..#./.##.#"),
    R: R("####./#...#/#...#/####./#.#../#..#./#...#"),
    S: R(".####/#..../#..../.###./....#/....#/####."),
    T: R("#####/..#../..#../..#../..#../..#../..#.."),
    U: R("#...#/#...#/#...#/#...#/#...#/#...#/.###."),
    V: R("#...#/#...#/#...#/#...#/#...#/.#.#./..#.."),
    W: R("#...#/#...#/#...#/#.#.#/#.#.#/##.##/#...#"),
    X: R("#...#/#...#/.#.#./..#../.#.#./#...#/#...#"),
    Y: R("#...#/#...#/.#.#./..#../..#../..#../..#.."),
    Z: R("#####/....#/...#./..#../.#.../#..../#####"),
    "0": R(".###./#...#/#..##/#.#.#/##..#/#...#/.###."),
    "1": R(".#./##./.#./.#./.#./.#./###"),
    "2": R(".###./#...#/....#/...#./..#../.#.../#####"),
    "3": R("####./....#/....#/.###./....#/....#/####."),
    "4": R("...#./..##./.#.#./#..#./#####/...#./...#."),
    "5": R("#####/#..../####./....#/....#/#...#/.###."),
    "6": R(".###./#..../#..../####./#...#/#...#/.###."),
    "7": R("#####/....#/...#./..#../..#../..#../..#.."),
    "8": R(".###./#...#/#...#/.###./#...#/#...#/.###."),
    "9": R(".###./#...#/#...#/.####/....#/....#/.###."),
    " ": R("..../..../..../..../..../..../...."),
    ".": R("./././././#/#"),
    ",": R("../../../../.#/.#/#."),
    "!": R("#/#/#/#/#/./#"),
    "?": R(".###./#...#/....#/...#./..#../...../..#.."),
    "-": R("..../..../..../####/..../..../...."),
    "+": R("...../..#../..#../#####/..#../..#../....."),
    ":": R("./#/#/./#/#/."),
    "/": R("....#/....#/...#./..#../.#.../#..../#...."),
    "'": R("#/#/./././././"),
    "$": R("..#../.####/#.#../.###./..#.#/####./..#.."),
    "%": R("##..#/##.#./...#./..#../.#.../.#.##/#..##")
  };
  var textWidth = (s, k = 1) => [...s.toUpperCase()].reduce((a, ch) => a + ((FONT[ch] ?? FONT["-"])[0].length + 1) * k, 0) - k;
  var eachCell = (s, x0, y0, k, cell) => {
    let x = x0;
    for (const ch of s.toUpperCase()) {
      const g = FONT[ch] ?? FONT["-"];
      g.forEach((row, j) => [...row].forEach((v, i) => {
        if (v === "#") for (let a = 0; a < k; a++) for (let b = 0; b < k; b++) cell(x + i * k + a, y0 + j * k + b);
      }));
      x += (g[0].length + 1) * k;
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
  var register = (name, value) => {
    const M = window.M;
    (M.look = M.look || {})[name] = value;
  };

  // motion/runtime/looks-src/pixelArt.ts
  var CLEAR = 255;
  var PALETTES = {
    night: ["#07080f", "#10152b", "#1a2446", "#283a66", "#3f5b8c", "#8ea9d0", "#e8eef5", "#0c1a17", "#16302a", "#255040", "#5b8f47", "#1c1626", "#3a2c3e", "#7a4a2e", "#e39b3a", "#ffe9a8"],
    day: ["#101820", "#2b3a55", "#4a6fa5", "#7fb2dc", "#c6e3f2", "#f7f4e6", "#2f5233", "#4f8a3f", "#94c95a", "#6b4226", "#a9713f", "#e3b27a", "#c23b3b", "#ee7f3a", "#f6cf4a", "#ffffff"],
    dusk: ["#120d1f", "#2a1b3d", "#44318d", "#7b3f8c", "#c0507f", "#f0806a", "#fcb76b", "#fdf0c4", "#14343b", "#1f6161", "#3fa58a", "#8ad6a4", "#3a2a22", "#7d5235", "#c79a62", "#ffffff"],
    mono: ["#0f1a0f", "#1f331f", "#2f4d2f", "#3f663f", "#548054", "#6e9a6e", "#8ab58a", "#a8cfa8", "#c6e8c6", "#e4ffe4", "#101010", "#2a2a2a", "#555555", "#888888", "#bbbbbb", "#ffffff"]
  };
  var Draft = class extends PixelDraft {
    constructor(G, H) {
      super(G, H, CLEAR);
    }
    /** Bucket fill of a polygon, whole cells whose centre is inside. */
    fill(poly, c) {
      this.begin("fill");
      PixelDraft.cover(poly, this.G, this.H).forEach((i) => this.px(i % this.G, Math.floor(i / this.G), c));
      this.end();
      return this;
    }
    /** A polygon with its one-cell nubs and notches cleaned off: the pixel artist's pass over a silhouette. */
    blob(poly, c) {
      const m = new Uint8Array(this.G * this.H);
      PixelDraft.cover(poly, this.G, this.H).forEach((i) => m[i] = 1);
      const o = cleanMask(m, this.G, this.H);
      this.begin("fill");
      for (let y = 0; y < this.H; y++) for (let x = 0; x < this.G; x++) if (o[y * this.G + x]) this.px(x, y, c);
      this.end();
      return this;
    }
    /** A half tint: level 0..4 of colour c over what's there, only inside the polygon. Never an alpha blend. */
    dither(poly, c, level = 2) {
      this.begin("cluster");
      PixelDraft.cover(poly, this.G, this.H).forEach((i) => {
        const x = i % this.G, y = Math.floor(i / this.G);
        if (PixelDraft.dith(x, y, level)) this.px(x, y, c);
      });
      this.end();
      return this;
    }
    disc(cx, cy, r, c, ry = r) {
      this.begin("fill");
      for (let y = Math.floor(cy - ry); y <= cy + ry; y++) for (let x = Math.floor(cx - r); x <= cx + r; x++) {
        const u = (x + 0.5 - cx) / r, v = (y + 0.5 - cy) / ry;
        if (u * u + v * v <= 1) this.px(x, y, c);
      }
      this.end();
      return this;
    }
    box(x, y, w, h, c) {
      this.begin("fill");
      this.rect(Math.round(x), Math.round(y), Math.round(w), Math.round(h), c);
      this.end();
      return this;
    }
    stroke(pts, c, closed = false) {
      this.begin("pencil");
      const n = pts.length;
      for (let i = 0; i + 1 < n + (closed ? 1 : 0); i++) {
        const a = pts[i], b = pts[(i + 1) % n];
        this.line(a[0], a[1], b[0], b[1], c);
      }
      this.end();
      return this;
    }
    /** Sky by rows: colours[] from y0 to y1, a 2x2 dither where one meets the next. */
    bands(y0, y1, colours, x0 = 0, x1 = this.G) {
      const n = colours.length - 1, h = (y1 - y0) / Math.max(1, n);
      this.begin("fill");
      for (let y = y0; y < y1; y++) {
        const u = (y - y0) / h, k = Math.min(n - 1, Math.floor(u)), lv = Math.floor((u - k) * 5);
        for (let x = x0; x < x1; x++) this.px(x, y, PixelDraft.dith(x, y, lv) ? colours[k + 1] : colours[k]);
      }
      this.end();
      return this;
    }
    /** A light as an authored stamp: a core, a lit ring and a falloff that thins out cell by cell, colours[] from the inside out. */
    glow(cx, cy, r, colours) {
      this.begin("cluster");
      const n = colours.length;
      for (let y = Math.floor(cy - r); y <= cy + r; y++) for (let x = Math.floor(cx - r); x <= cx + r; x++) {
        const d = Math.hypot(x + 0.5 - cx, y + 0.5 - cy) / r;
        if (d > 1) continue;
        const u = d * n, k = Math.min(n - 1, Math.floor(u)), lv = 4 - Math.floor((u - k) * 5);
        if (k === 0 || PixelDraft.dith(x, y, lv)) this.px(x, y, colours[k]);
      }
      this.end();
      return this;
    }
    /** Laid by hand: rows of characters, map = {character: palette index}; anything else leaves the cell alone. */
    sprite(rows, x, y, map, flip = false) {
      this.begin("pencil");
      rows.forEach((row, j) => {
        const w = row.length;
        [...row].forEach((ch, i) => {
          const c = map[ch];
          if (c !== void 0) this.px(x + (flip ? w - 1 - i : i), y + j, c);
        });
      });
      this.end();
      return this;
    }
    /** Rim light: every painted cell whose neighbour at (dx, dy) is empty takes colour c. `only` limits it to these palette indexes. */
    rim(c, dx = -1, dy = -1, only) {
      this.begin("cluster");
      const hits = [];
      for (let y = 0; y < this.H; y++) for (let x = 0; x < this.G; x++) {
        const v = this.get(x, y);
        if (v === CLEAR || only && !only.includes(v)) continue;
        const n = this.get(x + dx, y + dy);
        if (n === CLEAR || n === -1) hits.push([x, y]);
      }
      hits.forEach(([x, y]) => this.px(x, y, c));
      this.end();
      return this;
    }
    /** Words in a 5 x 7 cell alphabet, k cells to a font cell. */
    text(s, x, y, c, k = 1) {
      this.begin("pencil");
      eachCell(s, Math.round(x), Math.round(y), k, (a, b) => this.px(a, b, c));
      this.end();
      return this;
    }
  };
  var Layer = class {
    constructor(hand, G, H, paint, budgets, rest = 2) {
      this.hand = hand;
      const d = this.d = new Draft(G, H);
      paint(d);
      d.end();
      const passes = d.strokes.reduce((a, s) => Math.max(a, s.pass), 0) + 1;
      this.plan = celPlan(d, budgets ?? Array.from({ length: passes }, () => 24), rest);
      if (this.plan[this.plan.length - 1] !== d.ops.length) this.plan.push(d.ops.length);
    }
    hand;
    d;
    plan;
    cv;
    ctx;
    at = -1;
    fin;
    get G() {
      return this.d.G;
    }
    get H() {
      return this.d.H;
    }
    /** How many cels this layer's making has, at 10 a second by default: seconds = cels / 10. */
    get cels() {
      return this.plan.length;
    }
    canvas() {
      if (!this.cv) {
        this.cv = document.createElement("canvas");
        this.cv.width = this.G;
        this.cv.height = this.H;
        this.ctx = this.cv.getContext("2d");
        this.at = -1;
      }
      return this.ctx;
    }
    rollTo(n) {
      const c = this.canvas(), pal = this.hand.palette, G = this.G, ops = this.d.ops;
      if (n < this.at || this.at < 0) {
        c.clearRect(0, 0, G, this.H);
        this.at = 0;
      }
      for (let k = this.at; k < n; k++) {
        const op = ops[k], i = Math.floor(op / 16);
        c.fillStyle = pal[op % 16];
        c.fillRect(i % G, Math.floor(i / G), 1, 1);
      }
      this.at = n;
    }
    whole() {
      if (!this.fin) {
        const was = this.at;
        this.rollTo(this.d.ops.length);
        this.fin = document.createElement("canvas");
        this.fin.width = this.G;
        this.fin.height = this.H;
        this.fin.getContext("2d").drawImage(this.cv, 0, 0);
        void was;
      }
      return this.fin;
    }
    /** x, y in cells, rounded to whole cells; flip mirrors it; progress 0..1 lays it cel by cel in the order it was painted. */
    draw(g, o = {}) {
      const p = o.progress ?? 1, k = this.hand.cell, x = Math.round(o.x ?? 0), y = Math.round(o.y ?? 0);
      if (p <= 0) return;
      let src;
      if (p >= 1) src = this.whole();
      else {
        this.rollTo(this.plan[Math.min(this.plan.length - 1, Math.floor(p * this.plan.length))]);
        src = this.cv;
      }
      g.imageSmoothingEnabled = false;
      if (o.flip) {
        g.save();
        g.translate((x + this.G) * k, y * k);
        g.scale(-1, 1);
        g.drawImage(src, 0, 0, this.G * k, this.H * k);
        g.restore();
      } else g.drawImage(src, x * k, y * k, this.G * k, this.H * k);
    }
  };
  var PixelHand = class extends Hand {
    cell;
    G;
    H;
    palette;
    palettes = PALETTES;
    limb = limb;
    rng = rng;
    layers = /* @__PURE__ */ new Map();
    constructor(w, h, o = {}) {
      super(w, h, { scale: 1 });
      this.cell = Math.max(1, Math.round(o.cell ?? Math.max(2, Math.round(Math.max(w, h) / 160))));
      this.G = Math.ceil(w / this.cell);
      this.H = Math.ceil(h / this.cell);
      const pal = typeof o.palette === "string" ? PALETTES[o.palette] : o.palette ?? PALETTES.night;
      if (!pal || pal.length > 16) throw new Error("pixelArt: a palette is at most 16 colours");
      this.palette = pal;
    }
    /** A layer of cells. size = [columns, rows] (default the whole grid). budgets = cels per pass; rest = cels of rest between passes. */
    layer(id, paint, o = {}) {
      let L = this.layers.get(id);
      if (!L) {
        L = new Layer(this, o.size?.[0] ?? this.G, o.size?.[1] ?? this.H, paint, o.budgets, o.rest);
        this.layers.set(id, L);
      }
      return L;
    }
    begin(g) {
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.globalAlpha = 1;
      g.globalCompositeOperation = "source-over";
      g.imageSmoothingEnabled = false;
      return g;
    }
    /** Fills the frame with a palette colour. */
    clear(g, c) {
      g.save();
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.fillStyle = this.palette[c];
      g.fillRect(0, 0, this.w, this.h);
      g.restore();
    }
    /** Time held in cels: rate a second, 10 by default. */
    held(t, rate = 10) {
      return Math.floor(t * rate + 1e-6) / rate;
    }
    /** Which pose of n: pose-to-pose, whole-cell teleports, never tweened. */
    pose(t, n, rate = 6) {
      return Math.floor(t * rate + 1e-6) % n;
    }
    /** A move in whole cells between a and b, over t0..t1, held in cels. */
    hop(t, a, b, t0, t1, rate = 10) {
      const h = this.held(t, rate), u = h <= t0 ? 0 : h >= t1 ? 1 : (h - t0) / (t1 - t0);
      return Math.round(a + (b - a) * u);
    }
    width(s, k = 1) {
      return textWidth(s, k);
    }
    finish(_g) {
    }
  };
  register("pixelArt", { start: (w, h, o) => new PixelHand(w, h, o), palettes: PALETTES });
})();
