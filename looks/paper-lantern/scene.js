// Paper lantern in plain Canvas 2D: a shallow box of cut paper sheets lit from behind. Back sheets pale and glowing, front sheets
// near black; every sheet has a warm rim on its top edges, a dark band on its bottom edges and casts a soft shadow on the sheet behind.
const W = c.w, Hh = c.h, F = 20;
const hash = (i, j, k) => { const v = Math.sin(i * 127.1 + j * 311.7 + k * 74.7) * 43758.5453; return v - Math.floor(v); };
const poly = (x, pts) => { x.beginPath(); pts.forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b)); x.closePath(); };
const sheet = () => { const v = document.createElement('canvas'); v.width = W; v.height = Hh; return v; };
// finish a cut sheet: fibre grain, translucency near the lamp, a warm top rim and a dark bottom band
const finish = (v, glow) => { const x = v.getContext('2d');
  x.globalCompositeOperation = 'source-atop';
  for (let i = 0; i < 2600; i++) { x.fillStyle = hash(i, 3, 1) > .5 ? 'rgba(255,240,210,.05)' : 'rgba(40,15,5,.06)'; x.fillRect(hash(i, 1, 7) * W, hash(i, 2, 7) * Hh, 1 + hash(i, 4, 4) * 5, 1); }
  if (glow) { const m = x.createRadialGradient(SUN.x, SUN.y, 0, SUN.x, SUN.y, W * 1.1); m.addColorStop(0, `rgba(255,214,150,${glow})`); m.addColorStop(1, 'rgba(255,190,120,0)'); x.fillStyle = m; x.fillRect(0, 0, W, Hh); }
  const edge = (dy, colour) => { const e = sheet(), y = e.getContext('2d'); y.drawImage(v, 0, 0); y.globalCompositeOperation = 'destination-out'; y.drawImage(v, 0, dy);
    y.globalCompositeOperation = 'source-in'; y.fillStyle = colour; y.fillRect(0, 0, W, Hh); x.drawImage(e, 0, 0); };
  edge(3, 'rgba(255,205,140,.75)'); edge(-4, 'rgba(10,3,0,.45)'); x.globalCompositeOperation = 'source-over'; return v; };
const cut = (v, draw) => { const x = v.getContext('2d'); x.globalCompositeOperation = 'destination-out'; x.fillStyle = '#000'; draw(x); x.globalCompositeOperation = 'source-over'; };
const crescent = (x, cx, cy, w, h) => { x.beginPath(); x.moveTo(cx - w / 2, cy); x.quadraticCurveTo(cx, cy + h, cx + w / 2, cy); x.quadraticCurveTo(cx, cy + h * .35, cx - w / 2, cy); x.fill(); };
// back: the lit sky sheet, pulp mottling, and the sun burning through
const back = sheet(); { const x = back.getContext('2d'), m = x.createRadialGradient(SUN.x, SUN.y, 0, SUN.x, SUN.y, Hh * .9);
  m.addColorStop(0, '#fff2cf'); m.addColorStop(.18, '#f8cf8a'); m.addColorStop(.6, '#e79a55'); m.addColorStop(1, '#b8603a'); x.fillStyle = m; x.fillRect(0, 0, W, Hh);
  for (let i = 0; i < 220; i++) { x.fillStyle = `rgba(${hash(i, 1, 1) > .5 ? '255,240,210' : '150,70,30'},.03)`; x.beginPath(); x.ellipse(hash(i, 2, 2) * W, hash(i, 3, 3) * Hh, 30 + hash(i, 4, 4) * 60, 12 + hash(i, 5, 4) * 30, hash(i, 6, 6) * 3, 0, Math.PI * 2); x.fill(); } }
const horizon = Y(640);
// far ridge
const far = sheet(); { const x = far.getContext('2d'), pts = [[0, horizon + 10]]; for (let u = 0; u <= 1080; u += 60) pts.push([X(u), Y(560 - 60 * Math.sin(u / 170) - 40 * hash(u, 1, 2))]); pts.push([W, horizon + 10]);
  poly(x, pts); x.fillStyle = '#d98a52'; x.fill(); finish(far, .35); }
// the hill
const hill = sheet(); { const x = hill.getContext('2d'); poly(x, HILL); x.fillStyle = '#a45631'; x.fill(); x.fillRect(0, horizon - 2, X(640), 4); finish(hill, .22); }
// the sea: a sheet with wave slits and a column of light under the sun
const sea = sheet(); { const x = sea.getContext('2d'); x.fillStyle = '#6e2f19'; x.fillRect(0, horizon, W, Hh);
  cut(sea, (y) => { for (let row = 0; row < 9; row++) for (let i = 0; i < 4; i++) { const u = 80 + i * 260 + (row % 2) * 130 + hash(row, i, 5) * 60, v = 700 + row * 80; if (Math.abs(u - 830) < 90) continue; crescent(y, X(u), Y(v), K(120 - row * 4), K(18)); }
    for (let k = 0; k < 7; k++) { const w = K(140 - k * 15); y.fillRect(SUN.x - w / 2 + (k % 2) * K(12), Y(690 + k * 52), w, K(9)); } }); finish(sea, .12); }
// the boat: one dark sheet; slits in the sails and a lantern hole at the stern
const boat = sheet(); { const x = boat.getContext('2d'); x.fillStyle = '#220f08'; [HULL, SAIL, JIB, [[X(560), Y(300)], [X(572), Y(300)], [X(572), Y(705)], [X(560), Y(705)]]].forEach((pp) => { poly(x, pp); x.fill(); });
  cut(boat, (y) => { for (let k = 0; k < 4; k++) y.fillRect(X(600 + k * 36), Y(470 + k * 40), K(8), K(150 - k * 34)); for (let k = 0; k < 3; k++) y.fillRect(X(520 - k * 30), Y(520 + k * 40), K(7), K(110 - k * 30));
    y.beginPath(); y.arc(X(745), Y(684), K(15), 0, Math.PI * 2); y.fill(); }); finish(boat, .08); }
// the front sheet: near black; reeds along the bottom, a branch from the left, a scalloped cloud valance across the top
const front = sheet(); { const x = front.getContext('2d'); x.fillStyle = '#150905';
  x.beginPath(); x.moveTo(0, Hh); for (let u = 0; u <= W; u += 6) { const blade = Math.abs(Math.sin(u * .19)) * 55 + hash(u, 3, 3) * 40; x.lineTo(u, Hh - 70 - blade); x.lineTo(u + 3, Hh - 62); } x.lineTo(W, Hh); x.fill();
  x.beginPath(); x.moveTo(0, 0); for (let u = 0; u <= W + 60; u += 60) x.arc(u, 26, 34, Math.PI, 0, true); x.lineTo(W, 0); x.fill();
  x.lineWidth = 9; x.strokeStyle = '#150905'; x.lineCap = 'round'; x.beginPath(); x.moveTo(-10, 150); x.quadraticCurveTo(110, 170, 190, 250); x.stroke();
  for (let i = 0; i < 9; i++) { const a = .3 + i * .1, px = 20 + i * 19, py = 152 + i * 10; x.save(); x.translate(px, py + (i % 2 ? -10 : 12)); x.rotate(i % 2 ? -.7 : .8); x.beginPath(); x.ellipse(0, 0, 17, 6, 0, 0, Math.PI * 2); x.fill(); x.restore(); }
  cut(front, (y) => { for (let u = 30; u < W; u += 60) { y.beginPath(); y.arc(u, 22, 9, 0, Math.PI * 2); y.fill(); } }); finish(front, 0); }
const layers = [[far, 10, .5], [hill, 12, .55], [sea, 14, .6], [boat, 16, .65], [front, 22, .75]];
return (t) => {
  const on = M.prog(t, 0, 2.6, 'inOut'), flicker = .96 + .04 * Math.sin(t * 9) * Math.sin(t * 3.3);
  g.fillStyle = '#0c0603'; g.fillRect(0, 0, W, Hh);
  g.save(); g.globalAlpha = .25 + .75 * on * flicker; g.drawImage(back, 0, 0); g.restore();
  // each sheet throws a soft shadow onto the sheets behind it; a slow push-in parallaxes the stack
  layers.forEach(([v, blur, depth], i) => { const shift = (1 - M.prog(t, 0, 5.5, 'inOut')) * depth * 18; g.save(); g.shadowColor = 'rgba(25,8,0,.6)'; g.shadowBlur = blur; g.shadowOffsetY = 4 + i * 2;
    g.translate(-shift * (i - 2) * .3, 0); g.drawImage(v, 0, 0); g.restore(); });
  // the lamp: windows and the sun bloom
  g.save(); g.globalCompositeOperation = 'lighter'; let m = g.createRadialGradient(SUN.x, SUN.y, 0, SUN.x, SUN.y, SUN.r * 2.2); m.addColorStop(0, `rgba(255,236,190,${.85 * on})`); m.addColorStop(1, 'rgba(255,180,90,0)');
  g.fillStyle = m; g.fillRect(0, 0, W, Hh); m = g.createRadialGradient(X(745), Y(684), 0, X(745), Y(684), K(70)); m.addColorStop(0, `rgba(255,110,60,${.9 * on * flicker})`); m.addColorStop(1, 'rgba(255,80,40,0)');
  g.fillStyle = m; g.fillRect(0, 0, W, Hh); g.restore();
  // the box: a dark wooden frame with a little spill on its inner edge
  g.fillStyle = '#1b120c'; g.fillRect(0, 0, W, F); g.fillRect(0, Hh - F, W, F); g.fillRect(0, 0, F, Hh); g.fillRect(W - F, 0, F, Hh);
  g.strokeStyle = 'rgba(255,190,120,.18)'; g.lineWidth = 2; g.strokeRect(F + 1, F + 1, W - 2 * F - 2, Hh - 2 * F - 2);
  const v = g.createRadialGradient(W / 2, Hh * .45, Hh * .25, W / 2, Hh * .5, Hh * .75); v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, 'rgba(0,0,0,.5)'); g.fillStyle = v; g.fillRect(F, F, W - 2 * F, Hh - 2 * F);
};
