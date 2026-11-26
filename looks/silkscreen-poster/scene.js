// Silkscreen poster in plain Canvas 2D: four opaque flat inks pulled one after another on cream stock. No gradients (skies are
// stepped bands), no outlines, no dots; each ink a little off-register, with a faint overprint ghost and a thin wet rim.
const W = c.w, Hh = c.h, PAPER = '#efe2c4', horizon = Y(640);
const hash = (i, j, k) => { const v = Math.sin(i * 127.1 + j * 311.7 + k * 74.7) * 43758.5453; return v - Math.floor(v); };
const poly = (x, pts) => { x.beginPath(); pts.forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b)); x.closePath(); };
const sheet = () => { const v = document.createElement('canvas'); v.width = W; v.height = Hh; return v; };
// stepped band: solid colour that breaks into stripes getting thinner, toward 'dir' (1 = down, -1 = up)
const bands = (x, y0, y1, dir) => { const span = Math.abs(y1 - y0), steps = 7; x.fillRect(0, Math.min(y0, y1) + (dir > 0 ? 0 : span * .45), W, span * .55);
  for (let i = 0; i < steps; i++) { const f = i / steps, gap = span * .45 / steps, th = gap * (1 - f) * .9; const y = dir > 0 ? y0 + span * .55 + i * gap : y1 - span * .55 - (i + 1) * gap + (gap - th); x.fillRect(0, y, W, th); } };
const sails = (x) => { poly(x, SAIL); x.fill(); poly(x, JIB); x.fill(); };
const sunCut = (x, r) => { x.beginPath(); x.arc(SUN.x, SUN.y, r, 0, Math.PI * 2); x.fill(); };
const bandTop = Hh - 150;
// the four pulls, in order: each draws its whole stencil, then what it leaves as bare paper
const pulls = [
  ['#e9b14c', (x) => { x.fillRect(0, 0, W, horizon); sunCut(x, SUN.r * 1.25); }, (x) => { sails(x); }],
  ['#d8642c', (x) => { bands(x, horizon - K(330), horizon, -1); x.save(); x.globalCompositeOperation = 'destination-out'; sunCut(x, SUN.r * 1.25); x.restore();
    x.beginPath(); x.arc(SUN.x, SUN.y, SUN.r * .95, 0, Math.PI * 2); x.arc(SUN.x, SUN.y, SUN.r * .72, 0, Math.PI * 2, true); x.fill(); poly(x, HULL); x.fill();
    poly(x, T([[0, 640], [0, 600], [700, 610], [1080, 590], [1080, 640]])); x.fill(); }, (x) => { sails(x); }],
  ['#2b7774', (x) => { bands(x, 0, Y(380), 1); x.save(); x.globalCompositeOperation = 'destination-out'; sunCut(x, SUN.r * 1.25); x.restore(); poly(x, HILL); x.fill(); }, (x) => { sails(x); }],
  ['#1d2943', (x) => { poly(x, T([[120, 420], [260, 455], [400, 540], [520, 600], [640, 640], [300, 640]])); x.fill(); x.fillRect(0, horizon, W, Hh - horizon);
    poly(x, T([[561, 296], [571, 296], [571, 702], [561, 702]])); x.fill(); },
    (x) => { sails(x); poly(x, HULL); x.fill();
      for (let row = 0; row < 7; row++) for (let u = (row % 2) * 90; u < 1080; u += 180) { const v = 690 + row * 52; if (v > 700 && v < 810 && u > 330 && u < 800) continue; x.fillRect(X(u), Y(v), K(110 - row * 6), K(5)); }
      for (let k = 0; k < 5; k++) x.fillRect(SUN.x - K(80 - k * 12), Y(680 + k * 30), K(160 - k * 24), K(6));
      x.font = `700 46px Bahnschrift, "Arial Narrow", Arial, sans-serif`; x.textAlign = 'center'; x.letterSpacing = '4px'; x.fillText(LABEL, W / 2, bandTop + 78);
      x.font = `600 16px Bahnschrift, Arial, sans-serif`; x.letterSpacing = '6px'; x.fillText('BY SAIL  ·  ALL SUMMER', W / 2, bandTop + 112); }],
];
const inks = pulls.map(([colour, stencil, bare], i) => { const v = sheet(), x = v.getContext('2d'); x.fillStyle = colour; stencil(x);
  x.globalCompositeOperation = 'destination-out'; x.fillStyle = '#000'; bare(x);
  if (i === 3) { x.globalCompositeOperation = 'source-over'; x.fillStyle = colour; x.fillRect(0, bandTop, W, Hh - bandTop); x.globalCompositeOperation = 'destination-out'; x.fillStyle = '#000'; bare(x); x.fillRect(0, bandTop - 6, W, 4);
    x.globalCompositeOperation = 'source-over'; x.fillStyle = colour; poly(x, T([[408, 770], [775, 770], [730, 800], [420, 800]])); x.fill(); }
  // paper mottle and pinholes, seen only where there is ink
  x.globalCompositeOperation = 'source-atop'; for (let k = 0; k < 900; k++) { x.fillStyle = `rgba(239,226,196,${.06 + hash(k, i, 3) * .12})`; x.beginPath(); x.arc(hash(k, i, 1) * W, hash(k, i, 2) * Hh, .6 + hash(k, i, 4) * 1.4, 0, Math.PI * 2); x.fill(); }
  // ink thickness: a light rim top-left and a dark rim bottom-right
  const edge = (dx, dy, col) => { const e = sheet(), y = e.getContext('2d'); y.drawImage(v, 0, 0); y.globalCompositeOperation = 'destination-out'; y.drawImage(v, dx, dy); y.globalCompositeOperation = 'source-in'; y.fillStyle = col; y.fillRect(0, 0, W, Hh); x.drawImage(e, 0, 0); };
  edge(1.2, 1.2, 'rgba(255,250,235,.22)'); edge(-1.2, -1.2, 'rgba(0,0,0,.18)'); x.globalCompositeOperation = 'source-over';
  return v; });
const reg = [[1.5, -1], [-2, 1.5], [1, 2], [-1, -1.5]];
return (t) => {
  g.fillStyle = PAPER; g.fillRect(0, 0, W, Hh);
  for (let k = 0; k < 1200; k++) { g.fillStyle = hash(k, 9, 9) > .5 ? 'rgba(150,120,80,.08)' : 'rgba(255,255,245,.25)'; g.fillRect(hash(k, 8, 1) * W, hash(k, 8, 2) * Hh, 2 + hash(k, 8, 3) * 6, .8); }
  // each pull arrives as a squeegee pass from left to right
  inks.forEach((v, i) => { const p = M.prog(t, .3 + i * 1.15, 1, 'inOut'); if (p <= 0) return; const [dx, dy] = reg[i];
    g.save(); g.beginPath(); g.rect(0, 0, W * p, Hh); g.clip();
    g.globalCompositeOperation = 'multiply'; g.globalAlpha = .18; g.drawImage(v, dx + 2.2, dy + 2.2); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
    g.drawImage(v, dx, dy); g.restore(); });
};
