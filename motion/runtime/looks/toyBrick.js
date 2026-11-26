/* letitedit drawing hand: toyBrick. Built from motion\runtime\looks-src (node build.mjs); don't edit this file.
 * Includes code from anidoodle (https://github.com/alexgreensh/anidoodle, commit 9c20e77), Copyright 2026 Alex Greenshpun, under the
 * Apache License 2.0: LICENSE-anidoodle.txt and NOTICE-anidoodle.txt beside this file. Changed by letitedit: see the headers in
 * looks-src. The rest is letitedit's own, GPL-3.0-or-later. Loaded into a code scene's page only when its script says M.look.toyBrick. */
(() => {
  // motion/runtime/looks-src/anidoodle/toyBrickKit.ts
  var STUD = 20;
  var PLATE = 8;
  var STUD_R = 6;
  var STUD_H = 4;
  var hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  var shade = (h, t) => {
    const c = hex(h).map((v) => Math.round(t >= 0 ? v + (255 - v) * t : v * (1 + t)));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  };
  var Cam = class {
    constructor(s, ox, oy) {
      this.s = s;
      this.ox = ox;
      this.oy = oy;
    }
    s;
    ox;
    oy;
    p(X, Y, Z) {
      return [this.ox + (X - Z) * 0.70711 * this.s, this.oy + (X + Z) * 0.35355 * this.s - Y * 0.86603 * this.s];
    }
  };
  var LIGHT = (() => {
    const v = [-0.25, 1, 0.55];
    const l = Math.hypot(...v);
    return v.map((c) => c / l);
  })();
  var aabb = (p, dy = 0) => {
    const xs = p.foot.map((q) => q[0] * STUD), zs = p.foot.map((q) => q[1] * STUD);
    return { x0: Math.min(...xs), x1: Math.max(...xs), z0: Math.min(...zs), z1: Math.max(...zs), y0: p.y0 * PLATE + dy, y1: (p.y0 + p.h) * PLATE + dy + (p.studs ? STUD_H : 0) };
  };
  var inside = (foot, x, z) => {
    for (let i = 0; i < foot.length; i++) {
      const [ax, az] = foot[i], [bx, bz] = foot[(i + 1) % foot.length];
      if ((bx - ax) * (z - az) - (bz - az) * (x - ax) < -1e-9) return false;
    }
    return true;
  };
  var studCells = (p) => {
    if (!p.studs) return [];
    if (p.kind === "round") {
      const [x, z] = p.foot[0];
      return [[x + 0.5, z + 0.5]];
    }
    const xs = p.foot.map((q) => q[0]), zs = p.foot.map((q) => q[1]), out = [];
    for (let x = Math.floor(Math.min(...xs)); x < Math.max(...xs); x++) for (let z = Math.floor(Math.min(...zs)); z < Math.max(...zs); z++)
      if ([[x, z], [x + 1, z], [x, z + 1], [x + 1, z + 1]].every(([a, b]) => inside(p.foot, a, b))) out.push([x + 0.5, z + 0.5]);
    return out.sort((a, b) => a[0] + a[1] - (b[0] + b[1]));
  };
  var polyPath = (c, pts) => {
    c.beginPath();
    pts.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
    c.closePath();
  };
  var ellipse = (c, x, y, rx, ry) => {
    c.beginPath();
    c.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
  };
  var sideTone = (nx, nz) => -0.11 - 0.11 * (nx - nz);
  var drawPart = (c, cam, p, dy, hair) => {
    const Y0 = p.y0 * PLATE + dy, Y1 = (p.y0 + p.h) * PLATE + dy, s = cam.s, col = p.color;
    if (p.kind === "round") {
      const [x, z] = p.foot[0];
      cylinder(c, cam, (x + 0.5) * STUD, Y0, Y1, (z + 0.5) * STUD, STUD * 0.48, col, hair);
      if (p.studs) stud(c, cam, (x + 0.5) * STUD, Y1, (z + 0.5) * STUD, col, hair);
      return;
    }
    const F = p.foot.map(([x, z]) => [x * STUD, z * STUD]), n = F.length;
    const seam = shade(col, -0.45), bev = shade(col, 0.32);
    const faces = [];
    for (let i = 0; i < n; i++) {
      const a = F[i], b = F[(i + 1) % n], ex = b[0] - a[0], ez = b[1] - a[1], l = Math.hypot(ex, ez), nx = ez / l, nz = -ex / l;
      if (nx + nz <= 1e-6) continue;
      faces.push({ pts: [cam.p(a[0], Y0, a[1]), cam.p(b[0], Y0, b[1]), cam.p(b[0], Y1, b[1]), cam.p(a[0], Y1, a[1])], t: sideTone(nx, nz), a, b });
    }
    faces.forEach((f) => {
      polyPath(c, f.pts);
      c.fillStyle = shade(col, f.t);
      c.fill();
      c.strokeStyle = shade(col, f.t);
      c.lineWidth = 0.6;
      c.stroke();
    });
    const top = F.map(([x, z]) => cam.p(x, Y1, z));
    polyPath(c, top);
    c.fillStyle = shade(col, 0.1);
    c.fill();
    c.lineCap = "round";
    faces.forEach((f) => {
      const a = cam.p(f.a[0], Y1, f.a[1]), b = cam.p(f.b[0], Y1, f.b[1]);
      c.strokeStyle = bev;
      c.lineWidth = Math.max(1, 0.9 * s);
      c.beginPath();
      c.moveTo(a[0], a[1] + 0.5 * s);
      c.lineTo(b[0], b[1] + 0.5 * s);
      c.stroke();
    });
    for (let i = 0; i < faces.length; i++) for (let j = 0; j < faces.length; j++) if (i !== j && faces[i].b === faces[j].a) {
      const q0 = cam.p(faces[i].b[0], Y0, faces[i].b[1]), q1 = cam.p(faces[i].b[0], Y1, faces[i].b[1]);
      c.strokeStyle = shade(col, faces[i].t + 0.16);
      c.lineWidth = Math.max(1, 0.7 * s);
      c.beginPath();
      c.moveTo(q0[0], q0[1]);
      c.lineTo(q1[0], q1[1]);
      c.stroke();
    }
    c.strokeStyle = seam;
    c.lineWidth = hair;
    faces.forEach((f) => {
      c.beginPath();
      c.moveTo(f.pts[0][0], f.pts[0][1]);
      c.lineTo(f.pts[1][0], f.pts[1][1]);
      c.moveTo(f.pts[3][0], f.pts[3][1]);
      c.lineTo(f.pts[2][0], f.pts[2][1]);
      c.stroke();
    });
    if (faces.length) {
      const fl = faces[0], la = faces[faces.length - 1];
      c.beginPath();
      c.moveTo(fl.pts[0][0], fl.pts[0][1]);
      c.lineTo(fl.pts[3][0], fl.pts[3][1]);
      c.moveTo(la.pts[1][0], la.pts[1][1]);
      c.lineTo(la.pts[2][0], la.pts[2][1]);
      c.stroke();
    }
    c.globalAlpha = 0.55;
    polyPath(c, top);
    c.stroke();
    c.globalAlpha = 1;
    studCells(p).forEach(([x, z]) => stud(c, cam, x * STUD, Y1, z * STUD, col, hair));
  };
  var stud = (c, cam, X, Y, Z, col, hair) => {
    const s = cam.s, r = STUD_R * s, b = cam.p(X, Y, Z), t = cam.p(X, Y + STUD_H, Z), hh = b[1] - t[1];
    c.fillStyle = shade(col, -0.2);
    c.globalAlpha = 0.55;
    ellipse(c, b[0] + r * 0.35, b[1] + r * 0.12, r * 1.02, r * 0.52);
    c.fill();
    c.globalAlpha = 1;
    c.fillStyle = shade(col, -0.12);
    c.beginPath();
    c.ellipse(b[0], b[1], r, r / 2, 0, 0, Math.PI);
    c.lineTo(t[0] - r, t[1]);
    c.ellipse(t[0], t[1], r, r / 2, 0, Math.PI, 0, true);
    c.closePath();
    c.fill();
    c.fillStyle = shade(col, 0.02);
    c.beginPath();
    c.ellipse(b[0], b[1], r, r / 2, 0, Math.PI * 0.55, Math.PI);
    c.lineTo(t[0] - r, t[1]);
    c.lineTo(t[0] - r * 0.3, t[1] + r * 0.48);
    c.closePath();
    c.fill();
    c.fillStyle = shade(col, -0.3);
    c.beginPath();
    c.ellipse(b[0], b[1], r, r / 2, 0, 0, Math.PI * 0.3);
    c.lineTo(t[0] + r * 0.62, t[1] + r * 0.4);
    c.lineTo(t[0] + r, t[1]);
    c.closePath();
    c.fill();
    c.fillStyle = shade(col, 0.14);
    ellipse(c, t[0], t[1], r, r / 2);
    c.fill();
    c.strokeStyle = shade(col, 0.5);
    c.lineWidth = Math.max(1, 0.8 * s);
    c.lineCap = "round";
    c.beginPath();
    c.ellipse(t[0], t[1], r * 0.82, r * 0.4, 0, Math.PI * 1.08, Math.PI * 1.62);
    c.stroke();
    c.strokeStyle = shade(col, -0.45);
    c.lineWidth = hair * 0.8;
    c.globalAlpha = 0.5;
    c.beginPath();
    c.ellipse(b[0], b[1], r, r / 2, 0, 0, Math.PI);
    c.stroke();
    c.globalAlpha = 1;
    void hh;
  };
  var cylinder = (c, cam, X, Y0, Y1, Z, R2, col, hair) => {
    const s = cam.s, r = R2 * s, b = cam.p(X, Y0, Z), t = cam.p(X, Y1, Z);
    c.fillStyle = shade(col, -0.11);
    c.beginPath();
    c.ellipse(b[0], b[1], r, r / 2, 0, 0, Math.PI);
    c.lineTo(t[0] - r, t[1]);
    c.ellipse(t[0], t[1], r, r / 2, 0, Math.PI, 0, true);
    c.closePath();
    c.fill();
    c.fillStyle = shade(col, 0);
    c.beginPath();
    c.ellipse(b[0], b[1], r, r / 2, 0, Math.PI * 0.6, Math.PI);
    c.lineTo(t[0] - r, t[1]);
    c.lineTo(t[0] - r * 0.35, t[1]);
    c.lineTo(b[0] - r * 0.35, b[1] + r * 0.47);
    c.closePath();
    c.fill();
    c.fillStyle = shade(col, -0.26);
    c.beginPath();
    c.ellipse(b[0], b[1], r, r / 2, 0, 0, Math.PI * 0.28);
    c.lineTo(t[0] + r * 0.6, t[1] + r * 0.4);
    c.lineTo(t[0] + r, t[1]);
    c.closePath();
    c.fill();
    c.strokeStyle = shade(col, 0.28);
    c.lineWidth = Math.max(1, 0.8 * s);
    c.beginPath();
    c.moveTo(b[0] - r * 0.62, b[1] + r * 0.39);
    c.lineTo(t[0] - r * 0.62, t[1] + r * 0.39);
    c.stroke();
    c.fillStyle = shade(col, 0.1);
    ellipse(c, t[0], t[1], r, r / 2);
    c.fill();
    c.strokeStyle = shade(col, 0.34);
    c.lineWidth = Math.max(1, 0.9 * s);
    c.beginPath();
    c.ellipse(t[0], t[1], r * 0.92, r * 0.44, 0, Math.PI * 0.95, Math.PI * 1.7);
    c.stroke();
    c.strokeStyle = shade(col, -0.45);
    c.lineWidth = hair;
    c.beginPath();
    c.ellipse(b[0], b[1], r, r / 2, 0, 0, Math.PI);
    c.stroke();
  };
  var order = (parts, cam) => {
    const n = parts.length, bb = parts.map(({ p, dy }) => aabb(p, dy));
    const sb = bb.map((b) => {
      const xs = [], ys = [];
      for (const X of [b.x0, b.x1]) for (const Y of [b.y0, b.y1]) for (const Z of [b.z0, b.z1]) {
        const q = cam.p(X, Y, Z);
        xs.push(q[0]);
        ys.push(q[1]);
      }
      return [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    });
    const after = Array.from({ length: n }, () => []), indeg = new Array(n).fill(0), E = 0.01;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const a = sb[i], b = sb[j];
      if (a[1] <= b[0] || b[1] <= a[0] || a[3] <= b[2] || b[3] <= a[2]) continue;
      const A = bb[i], B = bb[j];
      let front = -1;
      if (A.x1 <= B.x0 + E) front = j;
      else if (B.x1 <= A.x0 + E) front = i;
      else if (A.z1 <= B.z0 + E) front = j;
      else if (B.z1 <= A.z0 + E) front = i;
      else if (A.y1 - STUD_H * (parts[i].p.studs ? 1 : 0) <= B.y0 + E) front = j;
      else if (B.y1 - STUD_H * (parts[j].p.studs ? 1 : 0) <= A.y0 + E) front = i;
      if (front < 0) continue;
      const back = front === i ? j : i;
      after[back].push(front);
      indeg[front]++;
    }
    const out = [], ready = [];
    for (let i = 0; i < n; i++) if (!indeg[i]) ready.push(i);
    while (out.length < n) {
      if (!ready.length) {
        for (let i = 0; i < n; i++) if (indeg[i] > 0 && !out.includes(i)) {
          indeg[i] = 0;
          ready.push(i);
          break;
        }
      }
      ready.sort((a, b) => a - b);
      const k = ready.shift();
      out.push(k);
      for (const m of after[k]) if (--indeg[m] === 0) ready.push(m);
    }
    return out;
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
    form(pts, color, shade2, o = {}) {
      const { seed = 1, light = [-8, -9], alpha = 0.98, hi } = o, s = displace(sample(jitter(pts, 1.2, seed), true, 8), 13, 0.022, 3, 5), k = this.m[2];
      const r = this.boxOf(s, 3);
      this.box = this.join(this.box, r);
      const T = this.layer();
      this.base(T.ctx);
      T.ctx.fillStyle = shade2;
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
  var register = (name, value) => {
    const M = window.M;
    (M.look = M.look || {})[name] = value;
  };

  // motion/runtime/looks-src/toyBrick.ts
  var COLOURS = { red: "#B40000", blue: "#1E5AA8", yellow: "#FAC80A", green: "#00852B", lime: "#A5CA18", white: "#F4F4F4", black: "#1B2A34", lightGrey: "#969696", darkGrey: "#646464", brown: "#5F3109", tan: "#D7BA8C", orange: "#D67923", azure: "#68C3E2", pink: "#E4ADC8", purple: "#7B5AA6", darkBlue: "#19325A" };
  var OUTLINE = "#FAC80A";
  var HAIR = 0.7;
  var FALL = 10;
  var DROP = 190;
  var SLOT = 5;
  var rectFoot = (x0, z0, x1, z1) => [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
  var ccw = (f) => {
    let a = 0;
    f.forEach((p, i) => {
      const q = f[(i + 1) % f.length];
      a += p[0] * q[1] - q[0] * p[1];
    });
    return a < 0 ? [...f].reverse() : f;
  };
  var Builder = class {
    parts = [];
    steps = [];
    s = 0;
    id = 0;
    colour = COLOURS.red;
    add(p) {
      const part = { ...p, id: this.id++, step: this.s };
      this.parts.push(part);
      this.steps.push(this.s);
      return this;
    }
    color(c) {
      this.colour = c;
      return this;
    }
    /** The baseplate, always first: a thin studded plate under everything. */
    base(x0, z0, x1, z1, color = COLOURS.blue) {
      return this.add({ color, kind: "prism", foot: rectFoot(x0, z0, x1, z1), y0: -1, h: 1, studs: true });
    }
    /** A brick w studs by d studs, 3 plates tall unless h says otherwise. */
    brick(x, z, w, d, o = {}) {
      return this.add({ color: o.color ?? this.colour, kind: "prism", foot: rectFoot(x, z, x + w, z + d), y0: o.y ?? 0, h: o.h ?? 3, studs: o.studs ?? true });
    }
    /** A plate: one plate tall. */
    plate(x, z, w, d, o = {}) {
      return this.brick(x, z, w, d, { h: 1, ...o });
    }
    /** A smooth tile: a plate with no studs. */
    tile(x, z, w, d, o = {}) {
      return this.brick(x, z, w, d, { h: 1, studs: false, ...o });
    }
    /** A 1x1 round. */
    round(x, z, o = {}) {
      return this.add({ color: o.color ?? this.colour, kind: "round", foot: [[x, z]], y0: o.y ?? 0, h: o.h ?? 3, studs: o.studs ?? true });
    }
    /** Any convex footprint, in studs: a wedge, a bow, a cut corner. */
    prism(foot, o = {}) {
      return this.add({ color: o.color ?? this.colour, kind: "prism", foot: ccw(foot), y0: o.y ?? 0, h: o.h ?? 3, studs: o.studs ?? true });
    }
    /** A wall of bricks from (x, z), running along x, courses high, in a running bond with bricks of `len` studs. */
    wall(x, z, len, courses, o = {}) {
      const b = o.brick ?? 2;
      for (let c = 0; c < courses; c++) {
        let at = x + (c % 2 ? -b / 2 : 0);
        while (at < x + len) {
          const a = Math.max(x, at), e = Math.min(x + len, at + b);
          if (e > a) this.brick(a, z, e - a, 1, { ...o, y: (o.y ?? 0) + c * 3, h: 3 });
          at += b;
        }
      }
      return this;
    }
    /** Words built as one-stud plates standing on the x axis: each letter cell is a 1x1 at (x, z), rows upward from y. Reads best from the lit side. */
    letters(text, x, z, o = {}) {
      const y0 = o.y ?? 0;
      eachCell(text, 0, 0, 1, (a, b) => {
        this.brick(x + a, z, 1, 1, { h: 1, studs: false, color: o.color ?? this.colour, y: y0 + (6 - b) });
      });
      return this;
    }
    step() {
      this.s++;
      return this;
    }
  };
  var Model = class {
    constructor(hand, b, o) {
      this.hand = hand;
      this.P = b.parts;
      const beat = Math.round((o.beat ?? 0.5) * o.fps), W = hand.w, H = hand.h, f = o.fit ?? { x0: W * 0.07, y0: H * 0.1, x1: W * 0.93, y1: H * 0.9 };
      let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
      const probe = new Cam(1, 0, 0);
      this.P.forEach((p) => {
        const a = aabb(p);
        for (const X of [a.x0, a.x1]) for (const Y of [a.y0, a.y1]) for (const Z of [a.z0, a.z1]) {
          const q = probe.p(X, Y, Z);
          x0 = Math.min(x0, q[0]);
          x1 = Math.max(x1, q[0]);
          y0 = Math.min(y0, q[1]);
          y1 = Math.max(y1, q[1]);
        }
      });
      const s = Math.min((f.x1 - f.x0) / (x1 - x0), (f.y1 - f.y0) / (y1 - y0));
      this.cam = new Cam(s, (f.x0 + f.x1) / 2 - (x0 + x1) / 2 * s, (f.y0 + f.y1) / 2 - (y0 + y1) / 2 * s);
      const steps = [...new Set(this.P.map((p) => p.step))].sort((a, e) => a - e);
      let at = FALL;
      steps.forEach((st) => {
        const list = this.P.filter((p) => p.step === st).sort((a, e) => a.y0 - e.y0 || aabb(a).x0 + aabb(a).z0 - aabb(e).x0 - aabb(e).z0);
        const per = Math.max(1, Math.ceil(list.length / 4));
        list.forEach((p, i) => {
          this.land[p.id] = at + Math.floor(i / per) * SLOT;
          this.first[p.id] = at;
        });
        const end = at + (Math.ceil(list.length / per) - 1) * SLOT + FALL;
        at = Math.ceil(end / beat) * beat + beat * 0;
        if (at <= end) at += beat;
      });
      this.settle = Math.max(...this.land) + 3;
      this.total = this.settle + 6;
    }
    hand;
    P;
    land = [];
    first = [];
    settle = 0;
    total = 0;
    cam;
    cache = /* @__PURE__ */ new Map();
    staticKey = "";
    L = {};
    /** Seconds the whole build takes at this fps. */
    seconds(fps) {
      return this.total / fps;
    }
    layer(k) {
      let l = this.L[k];
      if (!l) {
        l = this.L[k] = this.hand.env.canvas(this.hand.w, this.hand.h);
      }
      return l;
    }
    shadowOf(c, parts, k) {
      const sx = -LIGHT[0] / LIGHT[1], sz = -LIGHT[2] / LIGHT[1], cam = this.cam;
      c.fillStyle = "#000";
      parts.forEach(({ p, dy }) => {
        const b = aabb(p, dy);
        if (b.y0 < -0.5) return;
        const pts = [];
        for (const Y of [b.y0, b.y1 - (p.studs ? STUD_H : 0)]) for (const X of [b.x0, b.x1]) for (const Z of [b.z0, b.z1]) {
          const q = cam.p(X + sx * Y, 0, Z + sz * Y);
          pts.push([q[0] * k, q[1] * k]);
        }
        const h = hull(pts);
        c.beginPath();
        h.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
        c.closePath();
        c.fill();
      });
    }
    paintShadow(c, parts, a) {
      const k = 1 / 5, S = this.layer("soft"), w = Math.ceil(this.hand.w * k), h = Math.ceil(this.hand.h * k), s = S.ctx;
      s.setTransform(1, 0, 0, 1, 0, 0);
      s.clearRect(0, 0, w + 2, h + 2);
      this.shadowOf(s, parts, k);
      c.save();
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.globalAlpha = a;
      c.imageSmoothingEnabled = true;
      c.imageSmoothingQuality = "high";
      c.drawImage(S.canvas, 0, 0, w, h, 0, 0, w / k, h / k);
      c.restore();
    }
    ghost(c, p, dy, a) {
      if (a >= 1) {
        drawPart(c, this.cam, p, dy, HAIR);
        return;
      }
      const T = this.layer("ghost"), t = fresh(T.ctx);
      t.clearRect(0, 0, this.hand.w, this.hand.h);
      drawPart(t, this.cam, p, dy, HAIR);
      c.save();
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.globalAlpha = a;
      c.drawImage(T.canvas, 0, 0);
      c.restore();
    }
    paintBase(c, p, dy, a = 1) {
      const k = 1 / 6, S = this.layer("softBase"), w = Math.ceil(this.hand.w * k), h = Math.ceil(this.hand.h * k), s = S.ctx, cam = this.cam;
      s.setTransform(1, 0, 0, 1, 0, 0);
      s.clearRect(0, 0, w + 2, h + 2);
      s.setTransform(k, 0, 0, k, 0, 0);
      s.fillStyle = "#000";
      const b = aabb(p, dy), q = [cam.p(b.x0, b.y0 - 2, b.z0), cam.p(b.x1, b.y0 - 2, b.z0), cam.p(b.x1, b.y0 - 2, b.z1), cam.p(b.x0, b.y0 - 2, b.z1)];
      s.beginPath();
      q.forEach(([x, y], i) => i ? s.lineTo(x + 10, y + 16) : s.moveTo(x + 10, y + 16));
      s.closePath();
      s.fill();
      c.save();
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.globalAlpha = 0.22 * a;
      c.imageSmoothingEnabled = true;
      c.drawImage(S.canvas, 0, 0, w, h, 0, 0, w / k, h / k);
      c.restore();
      this.ghost(c, p, dy, a);
    }
    outline(c, parts) {
      const cam = this.cam;
      c.save();
      c.strokeStyle = OUTLINE;
      c.lineWidth = Math.max(1.5, cam.s * 1.6);
      c.lineJoin = "round";
      parts.forEach(({ p, dy }) => {
        const b = aabb(p, dy), pts = [];
        for (const X of [b.x0, b.x1]) for (const Y of [b.y0, b.y1 - (p.studs ? STUD_H : 0)]) for (const Z of [b.z0, b.z1]) pts.push(cam.p(X, Y, Z));
        const h = hull(pts);
        c.beginPath();
        h.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
        c.closePath();
        c.stroke();
      });
      c.restore();
    }
    /** frame = frames since this model began, a pure function; the finished model holds. outline: false leaves the booklet's yellow off. */
    frame(c, f, o) {
      const P = this.P, settle = f >= this.settle && f < this.settle + 6 ? [0, 0.6, 1, 1, 0.6, 0.25][f - this.settle] : 0;
      const state = P.map((p) => {
        const L2 = this.land[p.id];
        if (f < L2 - FALL) return null;
        if (f >= L2) return { p, dy: (f === L2 ? -0.5 : 0) - (p.id > 0 ? settle : 0), moving: false, t: 1 };
        const t = (f - (L2 - FALL)) / FALL, e = 1 - (1 - t) ** 3;
        return { p, dy: DROP * (1 - e) * (p.id === 0 ? 2 : 1), moving: true, t };
      });
      const live = state.filter((s) => !!s);
      if (!live.length) return;
      const stat = live.filter((s) => !s.moving && s.dy === 0), key = stat.map((s) => s.p.id).join(","), base = stat.find((s) => s.p.id === 0), isBase = (p) => p.id === 0 && p.y0 < 0, L = this.layer("static");
      if (this.staticKey !== key) {
        const s = fresh(L.ctx);
        s.clearRect(0, 0, this.hand.w, this.hand.h);
        if (base && isBase(base.p)) this.paintBase(s, base.p, 0);
        const rest = stat.filter((q) => !isBase(q.p));
        if (rest.length) this.paintShadow(s, rest.map((q) => ({ p: q.p, dy: 0 })), 0.34);
        order(rest.map((q) => ({ p: q.p, dy: 0 })), this.cam).forEach((i) => drawPart(s, this.cam, rest[i].p, 0, HAIR));
        this.staticKey = key;
      }
      c.drawImage(L.canvas, 0, 0);
      const dyn = live.filter((s) => s.moving || s.dy !== 0), ghostA = (t) => 0.35 + 0.65 * Math.min(1, t / 0.6);
      if (dyn.length) {
        const all = [...stat.filter((s) => !isBase(s.p)), ...dyn.filter((s) => !isBase(s.p))], ord = order(all.map((s) => ({ p: s.p, dy: s.dy })), this.cam), bd = dyn.find((s) => isBase(s.p));
        if (bd) this.paintBase(c, bd.p, bd.dy, bd.moving ? ghostA(bd.t) : 1);
        dyn.forEach((s) => {
          if (isBase(s.p) || s.p.y0 > 0 || !base) return;
          this.paintShadow(c, [{ p: s.p, dy: s.dy }], 0.34 * Math.min(1, 0.25 + 0.75 * s.t));
        });
        let seen = false;
        const firstDyn = ord.findIndex((i) => all[i].moving || all[i].dy !== 0);
        ord.forEach((i, k) => {
          const s = all[i];
          if (k < firstDyn) return;
          if (s.moving || s.dy !== 0) {
            seen = true;
            this.ghost(c, s.p, s.dy, s.moving ? ghostA(s.t) : 1);
            return;
          }
          if (seen) drawPart(c, this.cam, s.p, 0, HAIR);
        });
      }
      if (o.outline !== false && f < this.settle) {
        const cur = live.filter((s) => {
          const stepNow = Math.max(...live.map((q) => q.p.step));
          return s.p.step === stepNow && s.p.id !== 0;
        });
        this.outline(c, cur.map((s) => ({ p: s.p, dy: s.dy })));
      }
    }
    /** Assembled to `frame` (frames since the model began; a negative or 0 frame draws nothing). Take-apart: give it total - frame. x, y move the whole model. */
    draw(g, o) {
      const F = this.layer("frame"), c = fresh(F.ctx);
      c.clearRect(0, 0, this.hand.w, this.hand.h);
      const f = Math.round(o.frame);
      if (f >= this.total) {
        const D = this.layer("done");
        if (!this.cache.get("done")) {
          const d = fresh(D.ctx);
          this.frame(d, this.total, { outline: false });
          this.cache.set("done", 1);
        }
        g.save();
        if (o.alpha !== void 0) g.globalAlpha *= o.alpha;
        g.drawImage(D.canvas, o.x ?? 0, o.y ?? 0, this.hand.w, this.hand.h);
        g.restore();
        return;
      }
      this.frame(c, f, o);
      g.save();
      if (o.alpha !== void 0) g.globalAlpha *= o.alpha;
      g.drawImage(F.canvas, o.x ?? 0, o.y ?? 0, this.hand.w, this.hand.h);
      g.restore();
    }
  };
  var fresh = (c) => {
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.globalAlpha = 1;
    c.lineCap = "butt";
    c.lineJoin = "miter";
    c.miterLimit = 10;
    c.lineWidth = 1;
    return c;
  };
  var hull = (pts) => {
    const q = [...pts].sort((a, b) => a[0] - b[0] || a[1] - b[1]), cr = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lo = [], up = [];
    for (const p of q) {
      while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop();
      lo.push(p);
    }
    for (let i = q.length - 1; i >= 0; i--) {
      const p = q[i];
      while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop();
      up.push(p);
    }
    return [...lo.slice(0, -1), ...up.slice(0, -1)];
  };
  var BrickHand = class extends Hand {
    COLOURS = COLOURS;
    STUD = STUD;
    PLATE = PLATE;
    shade = shade;
    constructor(w, h) {
      super(w, h, { scale: 1 });
    }
    /** A model, built once, in build order. beat = seconds between booklet steps; fit = {x0,y0,x1,y1} the box it fills; fps = the project's. */
    model(_id, build, o) {
      const b = new Builder();
      build(b);
      return new Model(this, b, o);
    }
    /** One flat studio colour. */
    backdrop(g, color = "#E7E4DE") {
      g.save();
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.fillStyle = color;
      g.fillRect(0, 0, this.w, this.h);
      g.restore();
    }
    finish(_g) {
    }
  };
  register("toyBrick", { start: (w, h) => new BrickHand(w, h), COLOURS });
})();
