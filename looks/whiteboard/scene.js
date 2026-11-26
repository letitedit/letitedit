// Whiteboard in plain Canvas 2D: dry-erase marker on one glossy board. Strokes are written in order, overshoot their corners and
// pool ink where the nib lands; ghosts of old lessons stay; a marker floats with its own shadow. No hands, no cursor.
const W = c.w, Hh = c.h, F = 14;
const hash = (i, j, k) => { const v = Math.sin(i * 127.1 + j * 311.7 + k * 74.7) * 43758.5453; return v - Math.floor(v); };
const len = (pts) => pts.reduce((a, p, i) => i ? a + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) : 0, 0);
const jitter = (pts, seed, amp = 1.3) => pts.map(([x, y], i) => [x + (hash(i, seed, 1) - .5) * amp, y + (hash(i, seed, 2) - .5) * amp]);
// one marker stroke, revealed to p (0-1): body, dry streaks along it, ink pooled at the ends
const stroke = (pts, colour, w, p, seed = 1) => { if (p <= 0) return; const q = jitter(pts, seed), L = len(q);
  g.save(); g.lineCap = 'round'; g.lineJoin = 'round'; g.setLineDash([L * p, L + 1]);
  g.beginPath(); q.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); g.strokeStyle = colour; g.globalAlpha = .9; g.lineWidth = w * 1.45; g.stroke();
  g.globalAlpha = .28; g.strokeStyle = '#f7f8f5'; g.lineWidth = w * .18; g.translate(w * .2, -w * .15); g.stroke(); g.restore();
  g.save(); g.fillStyle = colour; g.globalAlpha = .95; g.beginPath(); g.arc(q[0][0], q[0][1], w * .62, 0, Math.PI * 2); g.fill(); if (p >= 1) { const e = q[q.length - 1]; g.beginPath(); g.arc(e[0], e[1], w * .58, 0, Math.PI * 2); g.fill(); } g.restore(); };
// a polygon written edge by edge, each edge running a little past its corner
const edges = (pts, overshoot = 5) => pts.map((a, i) => { const b = pts[(i + 1) % pts.length], l = Math.hypot(b[0] - a[0], b[1] - a[1]), ux = (b[0] - a[0]) / l, uy = (b[1] - a[1]) / l;
  return [[a[0] - ux * overshoot * .4, a[1] - uy * overshoot * .4], [b[0] + ux * overshoot, b[1] + uy * overshoot]]; });
const loop = (cx, cy, r, turn = 1.08, n = 40) => Array.from({length: n + 1}, (_, i) => { const a = -2.2 + i / n * Math.PI * 2 * turn, rr = r * (1 + .05 * Math.sin(i * .7)); return [cx + Math.cos(a) * rr, cy + Math.sin(a) * rr]; });
const wave = (x0, x1, y, amp, n = 24) => Array.from({length: n + 1}, (_, i) => [x0 + (x1 - x0) * i / n, y + Math.sin(i / n * Math.PI * 4) * amp]);
const BLACK = '#1d1f24', BLUE = '#1f56b8', RED = '#d4322a', GREEN = '#22803f';
// everything written, in writing order: [points, colour, width]
const plan = [];
edges(HULL).forEach((e, i) => plan.push([e, BLACK, 4.5, 10 + i]));
edges(SAIL).forEach((e, i) => plan.push([e, BLACK, 4, 20 + i]));
edges(JIB).forEach((e, i) => plan.push([e, BLACK, 4, 30 + i]));
plan.push([[[X(566), Y(296)], [X(566), Y(704)]], BLACK, 4.5, 40]);
plan.push([loop(SUN.x, SUN.y, SUN.r), RED, 4.5, 41]);
for (let i = 0; i < 9; i++) { const a = i / 9 * Math.PI * 2; plan.push([[[SUN.x + Math.cos(a) * SUN.r * 1.35, SUN.y + Math.sin(a) * SUN.r * 1.35], [SUN.x + Math.cos(a) * SUN.r * 1.75, SUN.y + Math.sin(a) * SUN.r * 1.75]], RED, 3.5, 50 + i]); }
plan.push([HILL.slice(1, 6), GREEN, 4, 60]);
for (let i = 0; i < 7; i++) plan.push([[[X(30 + i * 70), Y(620)], [X(80 + i * 70), Y(520 + Math.abs(i - 2) * 22)]], GREEN, 2.5, 61 + i]);
[[640, 30, 1050, 6], [700, 30, 320, 5], [700, 830, 1050, 5], [770, 60, 330, 5], [770, 820, 1040, 5], [840, 160, 900, 5], [905, 60, 600, 4]].forEach(([y, a, b, amp], i) => plan.push([wave(X(a), X(b), Y(y), K(amp * 2)), BLUE, 3.5, 70 + i]));
plan.push([[[X(80), Y(-150)], [X(80) + 3, Y(-150) + 1], [X(560), Y(-152)]], BLACK, 3, 80]);
plan.push([[[X(330), Y(-90)], [X(380), Y(40)], [X(450), Y(180)], [X(500), Y(300)]], BLACK, 3, 81]);
plan.push([[[X(470), Y(275)], [X(500), Y(300)], [X(512), Y(262)]], BLACK, 3, 82]);
plan.push([[[X(820), Y(420)], [X(980), Y(420)]], BLUE, 3, 83], [[[X(950), Y(400)], [X(982), Y(420)], [X(950), Y(440)]], BLUE, 3, 84]);
const total = plan.reduce((a, s) => a + len(s[0]), 0);
return (t) => {
  // the board: gloss, ghosts of an older lesson, an aluminium frame and tray
  let q = g.createLinearGradient(0, 0, W, Hh); q.addColorStop(0, '#f4f5f2'); q.addColorStop(.45, '#fbfcfa'); q.addColorStop(1, '#eceeea'); g.fillStyle = q; g.fillRect(0, 0, W, Hh);
  g.save(); g.globalAlpha = .04; g.strokeStyle = '#6b7280'; g.lineWidth = 26; g.lineCap = 'round'; for (let i = 0; i < 5; i++) { g.beginPath(); g.moveTo(60 + hash(i, 1, 1) * 300, 120 + i * 170); g.bezierCurveTo(200, 80 + i * 170, 300, 160 + i * 170, 480, 110 + i * 170 + hash(i, 2, 2) * 40); g.stroke(); }
  g.globalAlpha = .07; g.lineWidth = 2; g.strokeStyle = '#4b5563'; g.beginPath(); g.moveTo(330, 820); g.lineTo(470, 790); g.moveTo(350, 850); g.lineTo(440, 838); g.stroke(); g.restore();
  const sx = ((t * .05) % 1.4 - .2) * W; q = g.createLinearGradient(sx - 120, 0, sx + 120, Hh * .4); q.addColorStop(0, 'rgba(255,255,255,0)'); q.addColorStop(.5, 'rgba(255,255,255,.55)'); q.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = q; g.fillRect(0, 0, W, Hh);
  // writing: the strokes in order, at the speed of a hand
  let budget = total * M.prog(t, .2, 5.2, 'linear');
  for (const [pts, colour, w, seed] of plan) { const l = len(pts); stroke(pts, colour, w, Math.min(1, budget / l), seed); budget -= l; if (budget <= 0) break; }
  g.save(); g.globalAlpha = M.prog(t, 1.2, .6); g.font = '600 38px "Ink Free", "Segoe Print", "Comic Sans MS", cursive'; g.fillStyle = BLACK; g.textBaseline = 'alphabetic'; g.fillText('the small boat', X(80), Y(-175));
  g.font = '600 24px "Ink Free", "Segoe Print", cursive'; g.fillStyle = BLUE; g.fillText('wind', X(830), Y(390)); g.restore();
  // magnets, and a marker floating with its cast shadow (no hand)
  [[F + 26, F + 26, '#e04b3c'], [W - F - 26, F + 26, '#f2c230']].forEach(([x, y, col]) => { g.fillStyle = 'rgba(0,0,0,.15)'; g.beginPath(); g.arc(x + 3, y + 4, 13, 0, Math.PI * 2); g.fill(); g.fillStyle = col; g.beginPath(); g.arc(x, y, 13, 0, Math.PI * 2); g.fill(); g.fillStyle = 'rgba(255,255,255,.45)'; g.beginPath(); g.arc(x - 4, y - 4, 4, 0, Math.PI * 2); g.fill(); });
  const mx = W - 110, my = Hh - 190 + Math.sin(t * 1.3) * 4;
  g.save(); g.filter = 'blur(5px)'; g.fillStyle = 'rgba(0,0,0,.18)'; g.translate(mx + 16, my + 22); g.rotate(-.6); g.fillRect(-48, -9, 96, 18); g.restore();
  g.save(); g.translate(mx, my); g.rotate(-.6); g.fillStyle = '#2a2d33'; g.fillRect(-50, -9, 30, 18); g.fillStyle = BLUE; g.fillRect(-20, -9, 62, 18); g.fillStyle = '#f2f3f5'; g.fillRect(-2, -9, 26, 18);
  g.fillStyle = '#1b1d22'; g.beginPath(); g.moveTo(42, -6); g.lineTo(56, -2); g.lineTo(56, 2); g.lineTo(42, 6); g.fill(); g.restore();
  // frame and tray
  q = g.createLinearGradient(0, 0, W, 0); q.addColorStop(0, '#b9bdc2'); q.addColorStop(.5, '#e3e6e9'); q.addColorStop(1, '#a9aeb4'); g.fillStyle = q;
  g.fillRect(0, 0, W, F); g.fillRect(0, 0, F, Hh); g.fillRect(W - F, 0, F, Hh); g.fillRect(0, Hh - F - 14, W, F + 14); g.fillStyle = 'rgba(0,0,0,.12)'; g.fillRect(F, F, W - 2 * F, 2); g.fillRect(F, F, 2, Hh - 2 * F);
};
