// Art Deco in plain Canvas 2D: warm lacquer black, engraved gold line, airbrushed hard-edged volumes, a sunburst, counted bulbs.
const s = K(1), W = c.w, Hh = c.h, cx = W / 2;
const path = (pts, close = true) => { g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); if (close) g.closePath(); };
const goldFill = (x0, y0, x1, y1, sheen) => { const d = (x1 - x0) * sheen, e = (y1 - y0) * sheen, q = g.createLinearGradient(x0 + d, y0 + e, x1 + d, y1 + e);
  [[0, '#8a6020'], [.25, '#d6a443'], [.46, '#fae29a'], [.5, '#fff6d4'], [.6, '#e8bd5c'], [.82, '#b07f2c'], [1, '#8a6020']].forEach(([o, col]) => q.addColorStop(o, col)); return q; };
// the signature stroke: a dark engraved underline, the gold line, a hairline highlight on top
const gline = (draw, w, sheen = 0) => { g.save(); g.lineJoin = 'round'; g.lineCap = 'round';
  draw(); g.strokeStyle = '#0a0604'; g.lineWidth = w + 1.6 * s * 2; g.stroke();
  draw(); g.strokeStyle = goldFill(0, 0, W, Hh * .6, sheen); g.lineWidth = w; g.stroke();
  draw(); g.strokeStyle = 'rgba(255,246,214,.55)'; g.lineWidth = Math.max(.6, w * .22); g.stroke(); g.restore(); };
// airbrush: a hard edge with a directional gradient inside, light from the upper left
const airbrush = (pts, light, shade) => { const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const q = g.createLinearGradient(Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)); q.addColorStop(0, light); q.addColorStop(1, shade);
  path(pts); g.fillStyle = q; g.fill(); };
const horizon = Y(640);
return (t) => {
  const grow = M.prog(t, 0, 3.2, 'inOut'), sheen = ((t * .18) % 1) - .5;
  // lacquer ground: warm black, drifting to deep emerald at the horizon; dark water below
  let q = g.createLinearGradient(0, 0, 0, horizon); q.addColorStop(0, '#120c08'); q.addColorStop(.75, '#13201a'); q.addColorStop(1, '#173a2e');
  g.fillStyle = q; g.fillRect(0, 0, W, horizon);
  q = g.createLinearGradient(0, horizon, 0, Hh); q.addColorStop(0, '#0f1813'); q.addColorStop(1, '#0a0705'); g.fillStyle = q; g.fillRect(0, horizon, W, Hh - horizon);
  // sunburst: alternate wedges a shade lighter, gold hairlines between them, all from the sun
  g.save(); g.beginPath(); g.rect(0, 0, W, horizon); g.clip();
  const rays = 28, reach = Hh * 1.2;
  for (let i = 0; i < rays; i++) { const a0 = i / rays * Math.PI * 2, a1 = (i + 1) / rays * Math.PI * 2;
    if (i % 2 === 0) { g.beginPath(); g.moveTo(SUN.x, SUN.y); g.arc(SUN.x, SUN.y, reach * grow, a0, a1); g.closePath(); g.fillStyle = 'rgba(214,170,82,.075)'; g.fill(); }
    const r1 = SUN.r * 2.5, r2 = reach * grow; g.beginPath(); g.moveTo(SUN.x + Math.cos(a0) * r1, SUN.y + Math.sin(a0) * r1); g.lineTo(SUN.x + Math.cos(a0) * r2, SUN.y + Math.sin(a0) * r2);
    g.strokeStyle = 'rgba(232,190,92,.38)'; g.lineWidth = 1; g.stroke(); }
  g.restore();
  // the sun: stepped gold rings around an airbrushed disc
  [2.15, 1.75, 1.38].forEach((m, i) => gline(() => { g.beginPath(); g.arc(SUN.x, SUN.y, SUN.r * m * (0.6 + .4 * grow), 0, Math.PI * 2); }, (i === 0 ? 2.4 : 1.6) * s * 2, sheen));
  q = g.createRadialGradient(SUN.x - SUN.r * .35, SUN.y - SUN.r * .35, SUN.r * .1, SUN.x, SUN.y, SUN.r);
  q.addColorStop(0, '#fff6dc'); q.addColorStop(.55, '#f1c96a'); q.addColorStop(1, '#a8701f'); g.beginPath(); g.arc(SUN.x, SUN.y, SUN.r, 0, Math.PI * 2); g.fillStyle = q; g.fill();
  // counted light: a ring of bulbs that switch on one by one
  const bulbs = 20;
  for (let i = 0; i < bulbs; i++) { const a = -Math.PI / 2 + i / bulbs * Math.PI * 2, bx = SUN.x + Math.cos(a) * SUN.r * 2.55, by = SUN.y + Math.sin(a) * SUN.r * 2.55, on = t > .4 + i * .16;
    if (on) { const glow = g.createRadialGradient(bx, by, 0, bx, by, 9 * s * 2); glow.addColorStop(0, 'rgba(255,240,200,.95)'); glow.addColorStop(.35, 'rgba(255,210,120,.5)'); glow.addColorStop(1, 'rgba(255,190,90,0)');
      g.fillStyle = glow; g.beginPath(); g.arc(bx, by, 9 * s * 2, 0, Math.PI * 2); g.fill(); }
    g.beginPath(); g.arc(bx, by, 2.6 * s * 2, 0, Math.PI * 2); g.fillStyle = on ? '#fff8e4' : '#5a4220'; g.fill(); }
  // hills: an airbrushed jewel volume with a gold rim on the lit edge
  airbrush(HILL, '#2f8466', '#0a241b');
  gline(() => path(HILL.slice(1, 6), false), 1.8 * s * 2, sheen);
  // water: fish-scale rows in faint gold, then speed lines
  g.save(); g.beginPath(); g.rect(0, horizon, W, Hh - horizon); g.clip(); g.strokeStyle = 'rgba(214,170,82,.22)'; g.lineWidth = .8;
  const sc = K(54);
  for (let row = 0, y = horizon + sc * .5; y < Hh + sc; row++, y += sc * .5) for (let x = (row % 2) * sc / 2 - sc; x < W + sc; x += sc) { g.beginPath(); g.arc(x, y, sc / 2, 0, Math.PI); g.stroke(); }
  g.restore();
  [[120, 720, 300], [420, 860, 380], [80, 960, 260], [560, 1010, 420], [200, 1180, 520], [620, 1300, 360]].forEach(([x, y, w], i) =>
    gline(() => { g.beginPath(); g.moveTo(X(x), Y(y)); g.lineTo(X(x + w * Math.min(1, grow * 1.4 - i * .08)), Y(y)); }, 1.4 * s * 2, sheen));
  gline(() => { g.beginPath(); g.moveTo(cx - cx * grow, horizon); g.lineTo(cx + cx * grow, horizon); }, 1.6 * s * 2, sheen);
  // the boat: the one saturated accent (burgundy), ivory sails, gold mast and keylines
  airbrush(HULL, '#d8455a', '#4a0a18'); gline(() => path(HULL), 1.8 * s * 2, sheen);
  airbrush(SAIL, '#fff8e6', '#a8916a'); gline(() => path(SAIL), 1.6 * s * 2, sheen);
  airbrush(JIB, '#f3ead2', '#7d6c50'); gline(() => path(JIB), 1.6 * s * 2, sheen);
  gline(() => path(MAST, false), 3.2 * s * 2, sheen);
  // a double gold frame with stepped corners, unfolding from the centre axis
  const m = 16, st = 22;
  const frame = (o) => [[cx, o], [W - o - st, o], [W - o - st, o + st], [W - o, o + st], [W - o, Hh - o - st], [W - o - st, Hh - o - st], [W - o - st, Hh - o], [o + st, Hh - o], [o + st, Hh - o - st], [o, Hh - o - st], [o, o + st], [o + st, o + st], [o + st, o], [cx, o]];
  g.save(); g.beginPath(); g.rect(cx - cx * grow, 0, W * grow, Hh); g.clip();
  gline(() => path(frame(m), false), 1.8, sheen); gline(() => path(frame(m + 7), false), 1, sheen); g.restore();
  // a stepped title plaque on the axis
  const pw = 330, ph = 54, py = Hh - 118, steps = [[cx - pw / 2, py], [cx + pw / 2, py], [cx + pw / 2, py + ph * .25], [cx + pw / 2 + 14, py + ph * .25], [cx + pw / 2 + 14, py + ph * .75], [cx + pw / 2, py + ph * .75], [cx + pw / 2, py + ph], [cx - pw / 2, py + ph], [cx - pw / 2, py + ph * .75], [cx - pw / 2 - 14, py + ph * .75], [cx - pw / 2 - 14, py + ph * .25], [cx - pw / 2, py + ph * .25]];
  const open = M.prog(t, 2.2, 1.4, 'inOut');
  g.save(); g.beginPath(); g.rect(cx - (pw / 2 + 20) * open, 0, (pw + 40) * open, Hh); g.clip();
  path(steps); g.fillStyle = 'rgba(14,9,6,.92)'; g.fill(); gline(() => path(steps), 1.6, sheen);
  g.font = '600 25px "Century Gothic", "Segoe UI", sans-serif'; g.letterSpacing = '7px'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillStyle = '#f6ecd2'; g.fillText(LABEL, cx + 3, py + ph / 2 + 1); g.restore();
};
