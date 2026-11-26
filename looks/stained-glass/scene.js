// Stained glass in plain Canvas 2D: cut glass pieces in dark lead, lit from behind; a dark stone room around the window; the coloured light thrown on the floor.
const W = c.w, Hh = c.h, LEAD = '#120f0d';
const poly = (x, pts) => { x.beginPath(); pts.forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b)); x.closePath(); };
const hash = (i, j, k) => { const v = Math.sin(i * 127.1 + j * 311.7 + k * 74.7) * 43758.5453; return v - Math.floor(v); };
// the window: a pointed arch, two arcs meeting at the apex
const L = W * .085, R = W * .915, S = Hh * .33, B = Hh * .835, r = (R - L) * .67, apexA = Math.acos((L + r - (L + R) / 2) / r);
const arch = (x, grow = 0) => { x.beginPath(); x.moveTo(L - grow, B + grow); x.lineTo(L - grow, S); x.arc(L + r, S, r + grow, Math.PI, Math.PI + apexA); x.arc(R - r, S, r + grow, -apexA, 0); x.lineTo(R + grow, B + grow); x.closePath(); };
// every region is cut into a jittered lattice of pieces, each with its own small shift of hue and depth
const lattice = (x, pts, colour, o) => {
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const mx = (x0 + x1) / 2, my = (y0 + y1) / 2, ca = Math.cos(o.ang || 0), sa = Math.sin(o.ang || 0), ax = o.a, ay = o.a * (o.squash || 1);
  const n = Math.ceil(Math.hypot(x1 - x0, y1 - y0) / Math.min(ax, ay) / 2) + 2;
  const P = (i, j) => { const u = i * ax + (hash(i, j, o.seed) - .5) * ax * .4, v = j * ay + (hash(j, i, o.seed + 9) - .5) * ay * .4 + (o.wave ? Math.sin(i * .8) * ay * o.wave : 0);
    return [mx + u * ca - v * sa, my + u * sa + v * ca]; };
  x.save(); poly(x, pts); x.clip(); const cells = [];
  for (let i = -n; i < n; i++) for (let j = -n; j < n; j++) {
    const q = [P(i, j), P(i + 1, j), P(i + 1, j + 1), P(i, j + 1)], px = (q[0][0] + q[2][0]) / 2, py = (q[0][1] + q[2][1]) / 2;
    if (px < x0 - ax || px > x1 + ax || py < y0 - ay || py > y1 + ay) continue;
    const [h, s, l] = typeof colour === 'function' ? colour(px, py) : colour;
    poly(x, q); x.fillStyle = `hsl(${h + (hash(i, j, o.seed + 3) - .5) * 16},${s}%,${l + (hash(i, j, o.seed + 5) - .5) * 13}%)`; x.fill();
    // streaks inside the piece at its own angle
    const a = hash(i, j, o.seed + 7) * Math.PI; x.save(); poly(x, q); x.clip(); x.strokeStyle = 'rgba(255,255,255,.07)'; x.lineWidth = 1;
    for (let k = -3; k <= 3; k++) { x.beginPath(); x.moveTo(px - Math.cos(a) * ax + Math.sin(a) * k * 4, py - Math.sin(a) * ax - Math.cos(a) * k * 4); x.lineTo(px + Math.cos(a) * ax + Math.sin(a) * k * 4, py + Math.sin(a) * ax - Math.cos(a) * k * 4); x.stroke(); }
    x.restore(); cells.push(q); }
  x.strokeStyle = LEAD; x.lineJoin = 'round'; x.lineWidth = o.lead || 3.2; cells.forEach((q) => { poly(x, q); x.stroke(); }); x.restore();
  x.strokeStyle = LEAD; x.lineWidth = 5; poly(x, pts); x.stroke(); };
// the glass itself, drawn once on its own canvas
const glass = document.createElement('canvas'); glass.width = W; glass.height = Hh; const q = glass.getContext('2d');
const horizon = Y(640), sky = [[0, 0], [W, 0], [W, horizon], [0, horizon]], sea = [[0, horizon], [W, horizon], [W, Hh], [0, Hh]];
lattice(q, sky, (x, y) => { const d = Math.hypot(x - SUN.x, y - SUN.y) / (W * .9); return [222 - 20 * Math.max(0, .5 - d), 68, 30 + 22 * Math.max(0, .55 - d)]; }, {a: W * .1, squash: 1.45, ang: Math.PI / 4, seed: 1});
// the sun: wedges of gold around a pale centre
const wedges = 12; for (let i = 0; i < wedges; i++) { const a0 = i / wedges * Math.PI * 2, a1 = (i + 1) / wedges * Math.PI * 2;
  q.beginPath(); q.moveTo(SUN.x, SUN.y); q.arc(SUN.x, SUN.y, SUN.r * 1.35, a0, a1); q.closePath(); q.fillStyle = `hsl(${40 + (i % 2) * 8},90%,${55 + (i % 3) * 5}%)`; q.fill(); q.strokeStyle = LEAD; q.lineWidth = 3; q.stroke(); }
q.beginPath(); q.arc(SUN.x, SUN.y, SUN.r * .55, 0, Math.PI * 2); q.fillStyle = '#fff1c4'; q.fill(); q.lineWidth = 4; q.stroke();
lattice(q, HILL, [138, 52, 30], {a: W * .085, seed: 4, ang: .5});
lattice(q, sea, (x, y) => [198, 70, 32 - 10 * (y - horizon) / (Hh - horizon)], {a: W * .12, squash: .42, wave: .45, seed: 6});
lattice(q, HULL, [350, 78, 34], {a: W * .1, squash: 1.6, seed: 8});
lattice(q, SAIL, [75, 30, 84], {a: W * .085, squash: 1.2, ang: -.5, seed: 10});
lattice(q, JIB, [44, 70, 66], {a: W * .085, ang: .5, seed: 12});
q.strokeStyle = LEAD; q.lineWidth = 7; poly(q, MAST); q.stroke();
// grisaille: a few painted trace lines in translucent brown (seams on the sails, planks on the hull)
q.strokeStyle = 'rgba(70,40,20,.55)'; q.lineWidth = 1.6;
for (let k = 1; k < 4; k++) { q.beginPath(); q.moveTo(X(580), Y(320 + k * 85)); q.lineTo(X(580 + k * 47), Y(660)); q.stroke(); }
q.beginPath(); q.moveTo(X(380), Y(735)); q.lineTo(X(765), Y(735)); q.moveTo(X(400), Y(765)); q.lineTo(X(748), Y(765)); q.stroke();
// fine bubbles and specks in the glass
for (let i = 0; i < 900; i++) { q.fillStyle = `rgba(255,255,255,${.05 + hash(i, 2, 3) * .1})`; q.fillRect(hash(i, 1, 1) * W, hash(i, 1, 2) * Hh, 1.2, 1.2); }
// the stone room
const room = document.createElement('canvas'); room.width = W; room.height = Hh; const s = room.getContext('2d');
s.fillStyle = '#17130f'; s.fillRect(0, 0, W, Hh);
for (let row = 0, y = 0; y < Hh * .88; row++, y += 44) for (let x = -(row % 2) * 50; x < W; ) { const w = 70 + hash(row, x, 4) * 70, l = 13 + hash(row, x, 5) * 7;
  s.fillStyle = `hsl(30,9%,${l}%)`; s.fillRect(x + 2, y + 2, w - 4, 40); x += w; }
s.save(); arch(s, 24); s.clip(); let gr = s.createLinearGradient(L - 24, 0, R + 24, 0); gr.addColorStop(0, '#5d5247'); gr.addColorStop(.5, '#3a322b'); gr.addColorStop(1, '#6b5f52');
s.fillStyle = gr; s.fillRect(0, 0, W, Hh); s.restore();
s.fillStyle = '#4d443b'; s.fillRect(L - 30, B, R - L + 60, 16); s.fillStyle = '#2a241f'; s.fillRect(L - 30, B + 16, R - L + 60, 8);
const floorTop = B + 24; s.fillStyle = '#100d0b'; s.fillRect(0, floorTop, W, Hh - floorTop);
for (let i = 0; i < 9; i++) { const fx = (i % 3) * W / 3 + hash(i, 1, 9) * 30 - 15, fy = floorTop + Math.floor(i / 3) * (Hh - floorTop) / 3; s.strokeStyle = '#060504'; s.lineWidth = 3; s.strokeRect(fx, fy, W / 3, (Hh - floorTop) / 3); }
return (t) => {
  const lit = M.prog(t, 0, 4, 'inOut'), lx = -W * .6 + (SUN.x + W * .6) * lit;
  g.drawImage(room, 0, 0);
  // light from behind: brightest round the sun; unlit glass stays dark and milky
  g.save(); arch(g); g.clip(); g.drawImage(glass, 0, 0);
  g.globalCompositeOperation = 'multiply'; let m = g.createRadialGradient(lx, SUN.y, 0, lx, SUN.y, W * 1.25);
  m.addColorStop(0, '#ffffff'); m.addColorStop(.45, '#cfcfd8'); m.addColorStop(1, '#5d5d6c'); g.fillStyle = m; g.fillRect(0, 0, W, Hh);
  g.globalCompositeOperation = 'screen'; g.fillStyle = `rgba(150,160,175,${.18 * (1 - lit)})`; g.fillRect(0, 0, W, Hh);
  g.globalCompositeOperation = 'lighter'; m = g.createRadialGradient(SUN.x, SUN.y, 0, SUN.x, SUN.y, SUN.r * 2.4); m.addColorStop(0, `rgba(255,236,190,${.8 * lit})`); m.addColorStop(1, 'rgba(255,200,120,0)');
  g.fillStyle = m; g.fillRect(0, 0, W, Hh); g.restore();
  // iron saddle bars across the window
  g.strokeStyle = '#0b0908'; g.lineWidth = 5; for (let y = S - r * .45; y < B; y += (B - S) / 4) { g.beginPath(); g.moveTo(L - 4, y); g.lineTo(R + 4, y); g.stroke(); }
  // bloom: bright glass eats into the lead
  g.save(); g.globalCompositeOperation = 'lighter'; g.globalAlpha = .28 * lit; g.filter = 'blur(9px)'; arch(g, 6); g.clip(); g.drawImage(glass, 0, 0); g.restore();
  // the window's coloured copy on the floor, mirrored, blurred and softened; a faint shaft of light with dust
  g.save(); g.beginPath(); g.rect(0, floorTop, W, Hh - floorTop); g.clip(); g.globalCompositeOperation = 'screen'; g.globalAlpha = .38 * lit; g.filter = 'blur(13px) saturate(.8)';
  const k = (Hh - floorTop) / (B - S * .1); g.translate(W / 2, floorTop + B * k); g.scale(1.15, -k); g.drawImage(glass, -W / 2, 0); g.restore();
  g.save(); g.globalCompositeOperation = 'lighter'; const sh = g.createLinearGradient(0, S, 0, Hh); sh.addColorStop(0, 'rgba(255,230,190,0)'); sh.addColorStop(.55, `rgba(255,226,180,${.07 * lit})`); sh.addColorStop(1, 'rgba(255,220,170,0)');
  g.fillStyle = sh; poly(g, [[SUN.x - 30, S], [SUN.x + 40, S], [W * .7, Hh], [W * .25, Hh]]); g.fill();
  for (let i = 0; i < 40; i++) { const dx = W * .3 + hash(i, 4, 4) * W * .4, dy = S + hash(i, 5, 5) * (Hh - S) + Math.sin(t + i) * 4; g.fillStyle = `rgba(255,236,200,${.25 * lit})`; g.fillRect(dx, dy, 1.4, 1.4); }
  g.restore();
};
