// Red paper-cut in plain Canvas 2D: opaque red paper cut with scissors and laid on a pale paper ground. No painting, no gradients,
// no outlines: every detail is a hole. Each piece has a hand-cut wobble, paper grain, and a tight shadow on the sheet below.
const W = c.w, Hh = c.h, RED = '#d2201f', DEEP = '#a8141b', PALE = '#e9968a';
const hash = (i, j, k) => { const v = Math.sin(i * 127.1 + j * 311.7 + k * 74.7) * 43758.5453; return v - Math.floor(v); };
const wob = (pts, amp = 1.2) => pts.map(([x, y], i) => [x + Math.sin(i * 1.7 + y * .05) * amp, y + Math.cos(i * 2.3 + x * .05) * amp]);
const poly = (x, pts) => { x.beginPath(); wob(pts).forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b)); x.closePath(); };
const sheet = () => { const v = document.createElement('canvas'); v.width = W; v.height = Hh; return v; };
const centre = (pts) => [pts.reduce((a, p) => a + p[0], 0) / pts.length, pts.reduce((a, p) => a + p[1], 0) / pts.length];
const inset = (pts, d) => { const [cx, cy] = centre(pts); return pts.map(([x, y]) => { const l = Math.hypot(x - cx, y - cy) || 1; return [x - (x - cx) / l * d, y - (y - cy) / l * d]; }); };
// one paper piece: fill, cut the holes, grain inside the paper only
const piece = (shape, colour, holes, contour) => { const v = sheet(), x = v.getContext('2d'); x.fillStyle = colour; shape(x);
  x.globalCompositeOperation = 'destination-out'; x.fillStyle = '#000'; x.strokeStyle = '#000';
  if (contour) { x.lineWidth = K(6); x.lineJoin = 'round'; contour.forEach((pts) => { poly(x, inset(pts, K(16))); x.stroke(); }); }
  if (holes) holes(x);
  x.globalCompositeOperation = 'source-atop'; for (let i = 0; i < 1800; i++) { x.fillStyle = hash(i, 1, 9) > .5 ? 'rgba(255,220,200,.08)' : 'rgba(80,0,0,.09)'; x.fillRect(hash(i, 2, 9) * W, hash(i, 3, 9) * Hh, 1 + hash(i, 4, 9) * 4, 1); }
  return v; };
const crescent = (x, cx, cy, w, h, a = 0) => { x.save(); x.translate(cx, cy); x.rotate(a); x.beginPath(); x.moveTo(-w / 2, 0); x.quadraticCurveTo(0, h, w / 2, 0); x.quadraticCurveTo(0, h * .4, -w / 2, 0); x.fill(); x.restore(); };
const teeth = (x, x0, x1, y, n, h) => { x.beginPath(); x.moveTo(x0, y); for (let i = 0; i < n; i++) { const a = x0 + (x1 - x0) * i / n, b = x0 + (x1 - x0) * (i + 1) / n; x.lineTo((a + b) / 2, y - h); x.lineTo(b, y); } x.lineTo(x1, y + h * 2); x.lineTo(x0, y + h * 2); x.closePath(); x.fill(); };
const plum = (x, cx, cy, r) => { for (let i = 0; i < 5; i++) { const a = i / 5 * Math.PI * 2 - Math.PI / 2; x.beginPath(); x.arc(cx + Math.cos(a) * r * .55, cy + Math.sin(a) * r * .55, r * .42, 0, Math.PI * 2); x.fill(); } };
const horizon = Y(640);
// the sun: a fold-symmetric rosette, one wedge designed and turned eight times
const sun = piece((x) => { x.beginPath(); const n = 48, R = SUN.r * 1.55; for (let i = 0; i <= n * 2; i++) { const a = i / (n * 2) * Math.PI * 2, rr = i % 2 ? R : R * .93; x.lineTo(SUN.x + Math.cos(a) * rr, SUN.y + Math.sin(a) * rr); } x.fill(); }, RED, (x) => {
  for (let i = 0; i < 16; i++) { const a = i / 16 * Math.PI * 2; crescent(x, SUN.x + Math.cos(a) * SUN.r * 1.18, SUN.y + Math.sin(a) * SUN.r * 1.18, SUN.r * .42, SUN.r * .16, a + Math.PI / 2); }
  for (let i = 0; i < 8; i++) { const a = i / 8 * Math.PI * 2; x.save(); x.translate(SUN.x, SUN.y); x.rotate(a); x.beginPath(); x.moveTo(SUN.r * .3, 0); x.quadraticCurveTo(SUN.r * .62, -SUN.r * .2, SUN.r * .86, 0); x.quadraticCurveTo(SUN.r * .62, SUN.r * .2, SUN.r * .3, 0); x.fill(); x.restore(); }
  plum(x, SUN.x, SUN.y, SUN.r * .2); });
// two cloud scrolls in pale red
const cloud = (cx, cy, s) => (x) => { x.beginPath(); x.arc(cx, cy, 30 * s, Math.PI, 0); x.arc(cx + 44 * s, cy - 6 * s, 26 * s, Math.PI, 0); x.arc(cx + 88 * s, cy, 30 * s, Math.PI, 0); x.lineTo(cx + 118 * s, cy + 14 * s); x.lineTo(cx - 30 * s, cy + 14 * s); x.closePath(); x.fill(); };
const clouds = piece((x) => { cloud(X(80), Y(170), 1.1)(x); cloud(X(420), Y(70), .85)(x); }, PALE, (x) => {
  [[X(80), Y(170), 1.1], [X(420), Y(70), .85]].forEach(([cx, cy, s]) => [0, 44, 88].forEach((dx, i) => { x.lineWidth = 3.5; x.beginPath(); x.arc(cx + dx * s, cy - (i === 1 ? 6 : 0) * s, 13 * s, Math.PI * .9, Math.PI * 2.3); x.stroke(); })); });
// the hill: a pale red sheet with a sawtooth grass edge and rows of crescents
const hill = piece((x) => { x.beginPath(); wob(HILL).forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b)); x.closePath(); x.fill(); }, '#de7a6d', (x) => {
  const ridge = [[0, 470], [120, 420], [260, 455], [400, 540], [520, 600], [640, 640]], top = (u) => { for (let i = 1; i < ridge.length; i++) if (u <= ridge[i][0]) { const [a0, b0] = ridge[i - 1], [a1, b1] = ridge[i]; return b0 + (b1 - b0) * (u - a0) / (a1 - a0); } return 640; };
  for (let row = 0; row < 4; row++) for (let u = 30; u < 600; u += 64) { const uu = u + (row % 2) * 32, v = 615 - row * 34; if (v < top(uu - 24) + 34 || v < top(uu + 24) + 34) continue; crescent(x, X(uu), Y(v), K(40), K(14)); } });
// the sea: a deep red sheet with rows of wave crescents cut out
const sea = piece((x) => { x.fillRect(0, horizon, W, Hh - horizon); teeth(x, 0, W, horizon, 34, 5); }, '#efb1a6', (x) => {
  for (let row = 0; row < 14; row++) for (let u = -40; u < 1140; u += 110) crescent(x, X(u + (row % 2) * 55), Y(700 + row * 58), K(84), K(26)); }, null);
// the boat: China red with an inset contour slit (the double outline), sawtooth rows and plum holes in the sails, coins along the hull
const MASTR = [[X(560), Y(300)], [X(574), Y(300)], [X(574), Y(704)], [X(560), Y(704)]];
const boat = piece((x) => { [HULL, SAIL, JIB, MASTR].forEach((pp) => { poly(x, pp); x.fill(); }); }, RED, (x) => {
  for (let k = 0; k < 5; k++) for (let u = 604; u < 580 + (430 + k * 44 - 320) * .56 - 26; u += 34) crescent(x, X(u + 14), Y(430 + k * 44), K(26), K(10));
  for (let k = 0; k < 3; k++) crescent(x, X(536 - k * 14), Y(470 + k * 50), K(22), K(9), Math.PI / 2);
  plum(x, X(650), Y(600), K(22)); plum(x, X(500), Y(600), K(18));
  for (let k = 0; k < 6; k++) { x.beginPath(); x.arc(X(455 + k * 52), Y(752), K(13), 0, Math.PI * 2); x.fill(); } }, [HULL, SAIL, JIB]);
// a window-flower border: red paper with a sawtooth inner edge and swirls in the corners
const frame = piece((x) => { const m = 24; x.fillRect(0, 0, W, Hh); x.globalCompositeOperation = 'destination-out'; x.beginPath(); x.rect(m, m, W - 2 * m, Hh - 2 * m); x.fill(); x.globalCompositeOperation = 'source-over'; }, RED, (x) => {
  const m = 24; for (let u = m; u < W - m; u += 12) { x.beginPath(); x.moveTo(u, m - 1); x.lineTo(u + 6, m - 8); x.lineTo(u + 12, m - 1); x.fill(); x.beginPath(); x.moveTo(u, Hh - m + 1); x.lineTo(u + 6, Hh - m + 8); x.lineTo(u + 12, Hh - m + 1); x.fill(); }
  [[12, 12], [W - 12, 12], [12, Hh - 12], [W - 12, Hh - 12]].forEach(([cx, cy]) => { x.beginPath(); x.arc(cx, cy, 6, 0, Math.PI * 2); x.fill(); }); });
const order = [clouds, sun, hill, sea, boat, frame];
return (t) => {
  g.fillStyle = '#f2e7d2'; g.fillRect(0, 0, W, Hh);
  for (let i = 0; i < 1400; i++) { g.fillStyle = hash(i, 5, 5) > .5 ? 'rgba(160,130,90,.07)' : 'rgba(255,255,250,.2)'; g.fillRect(hash(i, 6, 6) * W, hash(i, 7, 7) * Hh, 1 + hash(i, 8, 8) * 6, 1); }
  // pieces laid down one after another, in hard 12 fps steps
  const step = Math.floor(t * 12) / 12;
  order.forEach((v, i) => { const p = M.prog(step, i * .55, .5, 'out'); if (p <= 0) return; g.save(); g.shadowColor = 'rgba(70,10,0,.38)'; g.shadowBlur = 3; g.shadowOffsetX = 2; g.shadowOffsetY = 3;
    g.globalAlpha = Math.min(1, p * 1.5); g.translate(0, (1 - p) * -14); g.drawImage(v, 0, 0); g.restore(); });
};
