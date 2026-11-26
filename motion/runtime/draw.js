/* letitedit scene drawing helpers: options for code scenes drawn on a canvas, never finished clips.
 *
 * Loaded after motion.js, and only into a page whose script mentions M.draw. Every function takes the 2D context `g`
 * and the time `t`; nothing keeps state between frames, so any frame renders on its own.
 * Ported and improved from the 3 Nov T55 proof (a 15 s explainer drawn in code); written for letitedit
 * (GPL-3.0-or-later). No third-party code.
 *
 *   M.draw.family = '"Montserrat", sans-serif'   the font typeText / popText use (c.font('heading').family works)
 *   shapes     rr fillRR disc poly tube limb shade hash
 *   camera     M.draw.camera(g, t, {t0, t1, z0, z1, px, py, ox, oy}, w, h)   a slow push or pan that never shows an edge
 *   text       typeText popText (a typed sign, a word that springs in)
 *   marks      redX splat (a white wipe: cover with it at the cut, then let it open)
 *   people     person (arms that reach, faces that blink and talk, walks whose feet do not slide)
 *   blur       blur(g, drawFn, t, {n, shutter, fps})   sub-frame motion blur by averaging n draws of the same scene
 */
(function () {
  'use strict';
  const M = window.M;
  const D = (M.draw = {});
  const clamp = M.clamp, lerp = M.lerp;
  const eo = (k) => M.ease.out(clamp(k));
  const eio = (k) => M.ease.inOut(clamp(k));
  D.family = '"Segoe UI", sans-serif';
  D.hash = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
  const hash = D.hash;

  // ------------------------------------------------------------------ shapes
  /** hex colour lightened (a > 0) or darkened (a < 0) by that fraction. */
  D.shade = (hex, a) => {
    const n = parseInt(hex.slice(1), 16);
    const f = (c) => Math.round(clamp(c + (a < 0 ? c * a : (255 - c) * a), 0, 255));
    return '#' + [n >> 16, (n >> 8) & 255, n & 255].map(f).map((v) => v.toString(16).padStart(2, '0')).join('');
  };
  const shade = D.shade;
  D.rr = (g, x, y, w, h, r) => {
    r = Math.min(r, w / 2, h / 2);
    g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
  };
  D.fillRR = (g, x, y, w, h, r, col) => { D.rr(g, x, y, w, h, r); g.fillStyle = col; g.fill(); };
  D.disc = (g, x, y, r, col) => { g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fillStyle = col; g.fill(); };
  D.poly = (g, pts, col) => {
    g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.closePath();
    g.fillStyle = col; g.fill();
  };
  /** A round-ended line of one width. */
  D.tube = (g, a, b, w, col) => {
    g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]);
    g.lineWidth = w; g.lineCap = 'round'; g.strokeStyle = col; g.stroke();
  };
  /** A limb that tapers from width w0 at a to w1 at b, with round ends. */
  D.limb = (g, a, b, w0, w1, col) => {
    const dx = b[0] - a[0], dy = b[1] - a[1], d = Math.hypot(dx, dy) || 1e-4, nx = -dy / d, ny = dx / d;
    D.poly(g, [[a[0] + nx * w0 / 2, a[1] + ny * w0 / 2], [b[0] + nx * w1 / 2, b[1] + ny * w1 / 2],
      [b[0] - nx * w1 / 2, b[1] - ny * w1 / 2], [a[0] - nx * w0 / 2, a[1] - ny * w0 / 2]], col);
    D.disc(g, a[0], a[1], w0 / 2, col); D.disc(g, b[0], b[1], w1 / 2, col);
  };
  const { rr, fillRR, disc, poly, tube, limb } = D;

  // ------------------------------------------------------------------ camera
  /** A slow push or pan on a w x h plate, clamped so the plate's edges never show. s: {t0, t1, z0, z1, ox, oy, px, py}
   *  (zoom z0 -> z1, view offset ox,oy -> px,py in px). Call once after g.save(), before drawing the plate. */
  D.camera = (g, t, s, w = 1920, h = 1080) => {
    const k = eio((t - s.t0) / Math.max(1e-6, s.t1 - s.t0));
    const z = lerp(s.z0 || 1.03, s.z1 || 1.06, k);
    const mx = (z - 1) * w / 2, my = (z - 1) * h / 2;
    const ox = clamp(lerp(s.ox || 0, s.px || 0, k), -mx, mx), oy = clamp(lerp(s.oy || 0, s.py || 0, k), -my, my);
    g.translate(w / 2 + ox, h / 2 + oy); g.scale(z, z); g.translate(-w / 2, -h / 2);
  };

  // ------------------------------------------------------------------ text
  /** Typed text: each letter arrives 1.45x big and 0.7 em to the right and settles in 0.18 s. Returns the end time.
   *  o: {rate letters/s (28), weight (800), align left|center|right, alpha, family} */
  D.typeText = (g, str, x, y, size, t, t0, col, o = {}) => {
    const rate = o.rate || 28, wt = o.weight || 800, al = o.align || 'left', fam = o.family || D.family;
    g.font = `${wt} ${size}px ${fam}`; g.textBaseline = 'alphabetic';
    const full = g.measureText(str).width;
    const x0 = al === 'center' ? x - full / 2 : al === 'right' ? x - full : x;
    for (let i = 0; i < str.length; i++) {
      const age = t - (t0 + i / rate);
      if (age < 0) continue;
      const k = eo(age / 0.18), lx = x0 + g.measureText(str.slice(0, i)).width, lw = g.measureText(str[i]).width;
      g.save(); g.globalAlpha = (o.alpha == null ? 1 : o.alpha) * clamp(age / 0.05);
      g.translate(lx + lw / 2 + lerp(0.7 * size, 0, k), y); g.scale(lerp(1.45, 1, k), lerp(1.45, 1, k));
      g.fillStyle = col; g.textAlign = 'center'; g.fillText(str[i], 0, 0); g.restore();
    }
    return t0 + Math.max(0, str.length - 1) / rate + 0.18;
  };
  /** A word or mark that springs in at t0 (overshoot 0.12, 0.5 s). o: {scale, rot (deg-less radians that unwind), weight, family, overshoot} */
  D.popText = (g, str, x, y, size, t, t0, col, o = {}) => {
    const k = t - t0;
    if (k < 0) return;
    const e = M.springEase(o.overshoot == null ? 0.12 : o.overshoot)(k / 0.5);
    g.save(); g.translate(x, y); g.scale(e * (o.scale || 1), e * (o.scale || 1)); g.rotate((o.rot || 0) * (1 - clamp(k / 0.5)));
    g.font = `${o.weight || 800} ${size}px ${o.family || D.family}`; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillStyle = col; g.fillText(str, 0, 0); g.restore();
  };

  // ------------------------------------------------------------------ marks
  /** A red X over a wrong idea: two round strokes of 0.11 s each. */
  D.redX = (g, cx, cy, w, h, t, t0, o = {}) => {
    if (t < t0) return;
    const a = clamp((t - t0) / 0.11), b = clamp((t - t0 - 0.11) / 0.11);
    g.save(); g.lineWidth = o.width || 30; g.lineCap = 'round'; g.strokeStyle = o.color || '#d62828';
    const x1 = cx - w / 2, x2 = cx + w / 2, y1 = cy - h / 2, y2 = cy + h / 2;
    g.beginPath(); g.moveTo(x1, y1); g.lineTo(lerp(x1, x2, a), lerp(y1, y2, a)); g.stroke();
    if (b > 0) { g.beginPath(); g.moveTo(x2, y1); g.lineTo(lerp(x2, x1, b), lerp(y1, y2, b)); g.stroke(); }
    g.restore();
  };
  const splatPath = (g, cx, cy, r, seed) => {
    g.beginPath();
    for (let i = 0; i <= 72; i++) {
      const a = i / 72 * Math.PI * 2, wob = 1 + 0.22 * Math.sin(5 * a + seed) + 0.12 * Math.sin(9 * a + seed * 2) + 0.07 * Math.sin(17 * a);
      const x = cx + Math.cos(a) * r * wob, y = cy + Math.sin(a) * r * wob * 0.8;
      if (i) g.lineTo(x, y); else g.moveTo(x, y);
    }
    g.closePath();
  };
  /** A splat wipe: 0.2 s in (covers the frame), cut your shot at t0 + 0.2, 0.2 s out (a hole opens). Draw it last.
   *  o: {color '#ffffff', w, h} */
  D.splat = (g, t, t0, o = {}) => {
    const k = t - t0, w = o.w || 1920, h = o.h || 1080;
    if (k < 0 || k > 0.4) return;
    const col = o.color || '#ffffff', reach = Math.hypot(w, h) * 0.78;
    g.save(); g.fillStyle = col;
    if (k < 0.2) {
      const r = eo(k / 0.2) * reach;
      splatPath(g, w / 2, h / 2, r, 1.3); g.fill();
      for (let i = 0; i < 14; i++) {
        const a = hash(i) * 6.28, d = r * (1.05 + hash(i + 9) * 0.3);
        disc(g, w / 2 + Math.cos(a) * d, h / 2 + Math.sin(a) * d * 0.8, 14 + hash(i + 3) * 30 * clamp(1 - k / 0.2 * 0.5), col);
      }
    } else {
      const r = eo((k - 0.2) / 0.2) * reach;
      g.beginPath(); g.rect(-50, -50, w + 100, h + 100);
      splatPath(g, w / 2, h / 2, r, 2.1); g.fill('evenodd');
    }
    g.restore();
  };

  // ------------------------------------------------------------------ motion blur
  /** Draws drawFn(g, ti) n times across a fraction `shutter` of one frame ending at t, and averages them into g.
   *  Costs n times the drawing. o: {n 3, shutter 0.5 (0.5 = a 180 degree shutter), fps (the page's c.fps)}.
   *  It clears the canvas first. Needs an offscreen canvas, so use it on the whole frame, not per object. */
  D.blur = (g, drawFn, t, o = {}) => {
    const n = Math.max(1, o.n || 3), fps = o.fps || 30, span = (o.shutter == null ? 0.5 : o.shutter) / fps;
    const c = g.canvas, tmp = document.createElement('canvas');
    tmp.width = c.width; tmp.height = c.height;
    const tg = tmp.getContext('2d');
    g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, c.width, c.height); g.restore();
    for (let i = 0; i < n; i++) {
      tg.setTransform(1, 0, 0, 1, 0, 0); tg.clearRect(0, 0, tmp.width, tmp.height);
      drawFn(tg, t - span * (n === 1 ? 0 : (n - 1 - i) / (n - 1)));
      g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1 / (i + 1); g.drawImage(tmp, 0, 0); g.restore();
    }
  };

  // ------------------------------------------------------------------ people
  /** Two-bone reach: where the elbow (or knee) goes when a limb of lengths l1, l2 from S must reach T. */
  D.ik = (S, T, l1, l2, bend) => {
    const dx = T[0] - S[0], dy = T[1] - S[1], raw = Math.hypot(dx, dy) || 1e-4, d = clamp(raw, 1e-3, (l1 + l2) * 0.999);
    const a = Math.atan2(dy, dx), b = Math.acos(clamp((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d), -1, 1)) * bend;
    return { e: [S[0] + l1 * Math.cos(a + b), S[1] + l1 * Math.sin(a + b)], f: [S[0] + dx / raw * d, S[1] + dy / raw * d] };
  };
  const ik = D.ik;
  D.blink = (t, seed) => { const per = 2.7 + hash(seed) * 1.5; return ((t + seed * 1.37) % per) < 0.14; };
  D.hand = (g, p, ang, kind, u, col) => {
    g.save(); g.translate(p[0], p[1]); g.rotate(ang);
    if (kind === 'fist') { disc(g, 2 * u, 0, 3.3 * u, col); tube(g, [2.5 * u, -1 * u], [4.6 * u, -1 * u], 1.3 * u, shade(col, -0.12)); }
    else if (kind === 'point') { disc(g, 2 * u, 0, 3.3 * u, col); tube(g, [3 * u, 0], [9 * u, -0.5 * u], 2 * u, col); }
    else {                     // open hand: palm, thumb, three fingers fanned a little
      disc(g, 2.4 * u, 0, 3.5 * u, col); limb(g, [2 * u, -2.6 * u], [4.6 * u, -5.4 * u], 2.1 * u, 1.7 * u, col);
      [-1.2, 0.4, 2].forEach((dy) => limb(g, [4 * u, dy * u], [8 * u, (dy * 1.5 + 0.2) * u], 1.9 * u, 1.5 * u, col));
    }
    g.restore();
  };

  /** A person, y = ground, x = middle, h = height in px. Returns {head, hand: [l, r], shoulder, feet: [[x, y, planted]]}.
   *  o: {x, y, h, t, dir 1|-1, view 'front'|'side', walk {phase 0..1 per stride; advance x yourself by 1.5 legs a stride},
   *      arms [[x,y],[x,y]] targets for the hands (px), hands ['open'|'fist'|'point', ...], armBend, look [x,y],
   *      speak (true: mouth moves), mouth 0..1, smile -1..1, brow -1..1, lean, tilt, hop, head (size, 1), seed,
   *      skin shirt pants shoe hair ('bald'|'bun'|undefined) hairCol collar} */
  D.person = (g, o) => {
    const u = o.h / 100, dir = o.dir || 1, side = o.view === 'side', t = o.t || 0;
    const skin = o.skin || '#f0a08e', skinSh = shade(skin, -0.12);
    const shirt = o.shirt || '#4f7d8a', shirtSh = shade(shirt, -0.16), pants = o.pants || '#26344f', pantsSh = shade(pants, -0.2);
    const INK = '#2b2d42', LIP = '#8c3b43';
    const L1 = 19 * u, L2 = 19 * u, LEG = L1 + L2, wk = o.walk;
    let hipH = 37.8 * u;
    const ground = o.y - (o.hop || 0);
    if (wk) hipH = 35 * u - 1.0 * u * Math.cos(4 * Math.PI * wk.phase);       // the hips dip as the weight comes over
    const hip = [o.x, ground - hipH], sh = [o.x + (o.lean || 0) * u, hip[1] - 22 * u];
    const feet = [];
    if (wk) {
      const Dd = 0.375 * LEG, ph = wk.phase;           // 4 steps = 1.5 leg lengths a stride; stance feet move back at body speed
      [0, 0.5].forEach((off) => {
        const p = (ph + off) % 1; let fx, fy = 0;
        if (p < 0.5) fx = Dd * (1 - 4 * p);
        else { const k = (p - 0.5) / 0.5; fx = lerp(-Dd, Dd, eio(k)); fy = Math.sin(Math.PI * k) * 5 * u; }
        feet.push([hip[0] + dir * fx, ground - fy]);
      });
    } else if (side) feet.push([hip[0] - dir * 3 * u, ground], [hip[0] + dir * 5 * u, ground]);
    else feet.push([hip[0] - 7 * u, ground], [hip[0] + 7 * u, ground]);
    const hipPts = side ? [[hip[0], hip[1]], [hip[0], hip[1]]] : [[hip[0] - 5 * u, hip[1]], [hip[0] + 5 * u, hip[1]]];
    const legs = feet.map((f, i) => ({ r: ik(hipPts[i], f, L1, L2, side ? -dir : (i ? -1 : 1)), f }));
    const drawLeg = (i) => {
      const r = legs[i].r, col = i ? pants : pantsSh;
      limb(g, hipPts[i], r.e, 11 * u, 8.4 * u, col); limb(g, r.e, r.f, 8.4 * u, 6.6 * u, col);
      g.save(); g.translate(r.f[0] + dir * (side ? 3 : 1.5) * u, r.f[1] - 1.4 * u);
      const sx = -5.5 * u + (dir > 0 ? 0 : -2.2 * u);
      fillRR(g, sx, -2.6 * u, 12.4 * u, 6 * u, 3 * u, o.shoe || INK);
      fillRR(g, sx + 1 * u, 1.6 * u, 10.4 * u, 1.6 * u, 0.8 * u, shade(o.shoe || INK, 0.18));   // the sole
      g.restore();
    };
    const socket = side ? [[sh[0] - dir * 1 * u, sh[1] + 3 * u], [sh[0] + dir * 1 * u, sh[1] + 3 * u]]
      : [[sh[0] - 12.8 * u, sh[1] + 3 * u], [sh[0] + 12.8 * u, sh[1] + 3 * u]];
    const arms = [0, 1].map((i) => {
      let T = o.arms && o.arms[i];
      if (!T) {
        const sw = wk ? Math.sin(2 * Math.PI * (wk.phase + i * 0.5)) * 9 * u * dir : Math.sin(t * 1.6 + i * 2) * 1.2 * u;
        T = [socket[i][0] + (side ? sw : (i ? 4 : -4) * u), socket[i][1] + 27 * u - Math.abs(sw) * 0.12];
      }
      let r;
      if (o.armBend && o.armBend[i]) r = ik(socket[i], T, 15 * u, 14 * u, -o.armBend[i]);
      else { const a = ik(socket[i], T, 15 * u, 14 * u, 1), b = ik(socket[i], T, 15 * u, 14 * u, -1); r = a.e[1] >= b.e[1] ? a : b; }   // the elbow hangs
      return { r, kind: (o.hands && o.hands[i]) || 'open' };
    });
    const drawArm = (i) => {
      const a = arms[i], r = a.r;
      limb(g, socket[i], r.e, 7 * u, 5.4 * u, shirt); limb(g, r.e, r.f, 5.2 * u, 4.2 * u, skin);
      D.hand(g, r.f, Math.atan2(r.f[1] - r.e[1], r.f[0] - r.e[0]), a.kind, u, skin);
    };
    const far = side ? (dir > 0 ? 0 : 1) : -1;                 // far limbs first
    if (side) drawArm(far);
    drawLeg(0); drawLeg(1);
    // torso: shoulders wider than the waist
    const tw = side ? 21 * u : 29 * u, wt = side ? 18 * u : 23 * u;
    g.save();
    g.beginPath();
    g.moveTo(sh[0] - tw / 2 + 5 * u, sh[1] - 1 * u); g.lineTo(sh[0] + tw / 2 - 5 * u, sh[1] - 1 * u);
    g.quadraticCurveTo(sh[0] + tw / 2, sh[1] - 1 * u, sh[0] + tw / 2, sh[1] + 5 * u);
    g.lineTo(sh[0] + wt / 2, hip[1] + 4 * u); g.quadraticCurveTo(sh[0] + wt / 2, hip[1] + 6 * u, sh[0] + wt / 2 - 3 * u, hip[1] + 6 * u);
    g.lineTo(sh[0] - wt / 2 + 3 * u, hip[1] + 6 * u); g.quadraticCurveTo(sh[0] - wt / 2, hip[1] + 6 * u, sh[0] - wt / 2, hip[1] + 4 * u);
    g.lineTo(sh[0] - tw / 2, sh[1] + 5 * u); g.quadraticCurveTo(sh[0] - tw / 2, sh[1] - 1 * u, sh[0] - tw / 2 + 5 * u, sh[1] - 1 * u);
    g.closePath(); g.fillStyle = shirt; g.fill(); g.clip();
    fillRR(g, sh[0] + (dir > 0 ? tw * 0.18 : -tw * 0.5), sh[1] - 2 * u, tw * 0.32, 40 * u, 0, shirtSh);
    fillRR(g, sh[0] - tw / 2, hip[1] + 1 * u, tw, 2.2 * u, 0, pantsSh);                  // belt line
    if (o.collar) disc(g, sh[0], sh[1] + 1 * u, 5 * u, o.collar);
    g.restore();
    limb(g, [sh[0], sh[1]], [sh[0], sh[1] - 6 * u], 6 * u, 5.4 * u, skinSh);          // neck
    // head
    const hk = o.head || 1, hr = 14.6 * u * hk, fs = hk * 14.6 / 17;                    // fs: face features scale with the head
    const nod = Math.sin(t * 1.9 + (o.seed || 0)) * 0.035, hcy = sh[1] - 5 * u - hr * 0.82;
    g.save(); g.translate(sh[0], sh[1] - 4 * u); g.rotate((o.tilt || 0) + nod); g.translate(0, hcy - (sh[1] - 4 * u));
    const fx = side ? dir * 3 * u : 0;
    if (side) disc(g, fx - dir * 2 * u, 1 * u, 2.6 * u * hk, skinSh);                   // ear
    g.save(); g.beginPath(); g.arc(fx, 0, hr, 0, 7); g.clip();
    disc(g, fx, 0, hr, skinSh); disc(g, fx - dir * (side ? 2.5 : 0) * u - 2 * u, -1.5 * u, hr, skin); g.restore();
    if (o.hair !== 'bald') {
      const hc2 = o.hairCol || '#3d3550';
      g.fillStyle = hc2; g.beginPath();
      g.arc(fx, 0, hr * 1.04, Math.PI * 1.02, Math.PI * 1.98);
      g.bezierCurveTo(fx + hr * 0.55, -hr * 0.05, fx - hr * 0.15, -hr * 0.72, fx - dir * (side ? 2 : 0) * u - hr * 0.98, -hr * 0.14); g.fill();
      if (o.hair === 'bun') disc(g, fx - dir * (side ? 9 : 0) * u, -hr * 1.03, 6 * u * hk, hc2);
      if (side) disc(g, fx - dir * 9 * u * hk, -2 * u, 7 * u * hk, hc2);
    }
    const ex = side ? [fx + dir * 8.5 * u * fs] : [-6.2 * u * fs, 6.2 * u * fs], look = o.look || [0, 0], ey = -0.5 * u;
    const bl = D.blink(t, (o.seed || 1) * 3.1);
    ex.forEach((x) => {
      g.save(); g.translate(x + look[0] * u, ey + look[1] * u); g.scale(1, bl ? 0.12 : 1);
      disc(g, 0, 0, 2.1 * u * fs, INK); disc(g, 0.7 * u * fs, -0.8 * u * fs, 0.7 * u * fs, '#ffffff'); g.restore();       // a glint keeps the eye alive
    });
    if (!side) { disc(g, -10 * u * fs, 5 * u, 2.4 * u * fs, shade(skin, -0.06)); disc(g, 10 * u * fs, 5 * u, 2.4 * u * fs, shade(skin, -0.06)); }
    else { disc(g, fx + dir * 14.6 * u * fs, 2.2 * u, 2.5 * u * fs, skin); disc(g, fx - dir * 3 * u, 2 * u, 2.6 * u, skinSh); }
    const br = o.brow || 0;
    ex.forEach((x, i) => {
      const bx = x + look[0] * u, inn = side ? dir : (i ? -1 : 1), yb = -7 * u - Math.max(0, br) * 2.5 * u, yi = yb + (br < 0 ? br * 2 * u : 0);
      tube(g, [bx - inn * 3 * u * fs, yb], [bx + inn * 3 * u * fs, yi], 1.2 * u, INK);
    });
    const talk = o.speak ? 0.4 + 0.6 * Math.abs(Math.sin(t * 15 + (o.seed || 0))) : 0, mo = o.mouth == null ? talk : o.mouth;
    const mx = side ? fx + dir * 10.5 * u * fs : 0, my = 7.2 * u, sm = o.smile == null ? 0.5 : o.smile;
    if (mo > 0.08) {
      g.save(); g.translate(mx, my); g.beginPath(); g.ellipse(0, 0, 3.2 * u * (o.mouthW || 1) * fs, 1.4 * u + mo * 3 * u, 0, 0, 7);
      g.fillStyle = LIP; g.fill(); g.restore();
    } else {                     // closed mouth: a smile (sm > 0) or a frown (sm < 0), flat at 0
      g.beginPath();
      g.moveTo(mx - 3.6 * u * fs, my - 1.6 * u); g.quadraticCurveTo(mx, my - 1.6 * u + 4.4 * u * sm, mx + 3.6 * u * fs, my - 1.6 * u);
      g.lineWidth = 1.3 * u; g.lineCap = 'round'; g.strokeStyle = LIP; g.stroke();
    }
    g.restore();
    if (side) drawArm(1 - far); else { drawArm(0); drawArm(1); }                         // near arms last
    return { head: [sh[0], hcy], hand: arms.map((a) => a.r.f), shoulder: sh,
      feet: legs.map((l) => [l.r.f[0], l.r.f[1], l.f[1] === ground]) };
  };
})();
