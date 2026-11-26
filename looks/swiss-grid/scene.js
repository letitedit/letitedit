// Swiss grid in plain Canvas 2D: flat paper, black type and bars, one light grey and ONE signal colour; everything snaps to a
// six-column grid and lands on a beat, nothing bounces; extreme scale contrast between a giant numeral and tiny notes.
const W = c.w, Hh = c.h, INK = '#121212', GREY = '#d3d2cc', RED = '#e2321b', PAPER = '#f1f0eb';
const m = 30, gut = 12, col = (W - 2 * m - 5 * gut) / 6, cx = (i) => m + i * (col + gut), drop = 70;
const poly = (pts) => { g.beginPath(); pts.forEach(([a, b], i) => i ? g.lineTo(a, b + drop) : g.moveTo(a, b + drop)); g.closePath(); };
const type = (text, x, y, size, weight = 700, colour = INK, spacing = 0) => { g.font = `${weight} ${size}px "Helvetica Neue", Helvetica, Arial, sans-serif`; g.letterSpacing = `${spacing}px`; g.fillStyle = colour; g.textAlign = 'left'; g.textBaseline = 'alphabetic'; g.fillText(text, x, y); };
// a snap: 0 before its beat, 1 after, a short hard ease between (no overshoot)
const snap = (t, beat) => M.prog(t, beat * .42, .22, 'inOut');
return (t) => {
  g.fillStyle = PAPER; g.fillRect(0, 0, W, Hh);
  g.strokeStyle = 'rgba(0,0,0,.045)'; g.lineWidth = 1; for (let i = 0; i < 6; i++) { g.strokeRect(cx(i) + .5, .5, col, Hh - 1); }
  // the giant numeral and its rule
  const n = snap(t, 0); g.save(); g.beginPath(); g.rect(0, 0, W, 250 * n + 1); g.clip(); type('01', m - 8, 222, 250, 700, INK, -12); g.restore();
  g.fillStyle = INK; g.fillRect(m, 254, (W - 2 * m) * snap(t, 1), 4);
  // tiny technical notes, one per column
  const notes = [['Fig. 1', 'Sail plan'], ['45° 30′ N', '12° 20′ E'], ['Wind', '12 kn W'], ['Hull', '4.4 m']];
  notes.forEach(([a, b], i) => { if (t < (2 + i * .5) * .42) return; const at = cx([0, 2, 3, 5][i]); type(a, at, 278, 10, 700); type(b, at, 292, 10, 400); });
  // the picture, reduced to grid-aligned geometry
  const k = snap(t, 3);
  g.fillStyle = GREY; [[0, 3], [1, 2], [2, 1]].forEach(([i, steps]) => { const h = 40 + steps * 30; g.fillRect(cx(i) - (i === 0 ? m : 0), Y(640) + drop - h * k, col + gut + (i === 0 ? m : 0), h * k); });
  // the sea: black bars in column lengths, a left-aligned rhythm
  const lens = [6, 4, 5, 2, 6, 3, 5, 1, 4, 6, 2, 5];
  lens.forEach((n, row) => { const y = Y(640) + drop + 14 + row * 16, p = snap(t, 4 + row * .15); if (y > 818) return; g.fillStyle = INK; g.fillRect(m, y, ((n * (col + gut)) - gut) * p, 6); });
  // the boat: black hull and sail, grey jib, a hairline mast
  const b = snap(t, 6); g.save(); g.translate((1 - b) * -40, 0); g.globalAlpha = b;
  g.strokeStyle = PAPER; g.lineWidth = 10; g.lineJoin = 'miter'; poly(HULL); g.stroke(); g.fillStyle = INK; poly(HULL); g.fill(); poly(SAIL); g.fill(); g.fillStyle = '#9d9c96'; poly(JIB); g.fill(); g.fillStyle = INK; g.fillRect(X(564), Y(300) + drop, 3, Y(700) - Y(300)); g.restore();
  // the one exception: the red sun, the only colour in the frame
  const r = SUN.r * 1.5 * snap(t, 8); g.fillStyle = RED; g.beginPath(); g.arc(cx(4) + col + gut / 2, Y(220) + drop, r, 0, Math.PI * 2); g.fill();
  // title and folio
  g.fillStyle = INK; g.fillRect(m, 846, W - 2 * m, 2);
  if (t > 9 * .42) { type('The small boat.', m - 2, 904, 46, 700, INK, -1.5); type('A study in wind,', cx(4), 872, 10, 400); type('water and one sail.', cx(4), 886, 10, 400); type('01 / 06', W - m - 44, 940, 10, 700); type('Seefahrt · Voile · Sail', m, 940, 10, 400); }
};
