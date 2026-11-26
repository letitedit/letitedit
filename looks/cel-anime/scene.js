// 80s cel anime in plain Canvas 2D: an airbrushed background painting, cels with flat fills, hard-edged shadow and highlight shapes
// and coloured (never black) outlines, light glowing through the frame, all played back like videotape on a CRT.
const W = c.w, Hh = c.h, horizon = Y(640), LINE = '#2a1438';
const hash = (i, j, k) => { const v = Math.sin(i * 127.1 + j * 311.7 + k * 74.7) * 43758.5453; return v - Math.floor(v); };
const sheet = () => { const v = document.createElement('canvas'); v.width = W; v.height = Hh; return v; };
const poly = (x, pts) => { x.beginPath(); pts.forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b)); x.closePath(); };
// the background painting, made once: soft airbrush everywhere, no outlines
const bg = sheet(); { const x = bg.getContext('2d'); let q = x.createLinearGradient(0, 0, 0, horizon);
  [[0, '#140f3d'], [.35, '#43226e'], [.65, '#b23f78'], [.88, '#f07a4a'], [1, '#ffb15e']].forEach(([o, col]) => q.addColorStop(o, col)); x.fillStyle = q; x.fillRect(0, 0, W, horizon);
  for (let i = 0; i < 70; i++) { x.fillStyle = `rgba(255,240,255,${.25 + hash(i, 1, 1) * .6})`; const s = hash(i, 4, 4) > .9 ? 2 : 1; x.fillRect(hash(i, 2, 2) * W, hash(i, 3, 3) * horizon * .45, s, s); }
  x.save(); x.filter = 'blur(10px)'; [[.15, .3, '#ff8fb3'], [.55, .36, '#ffa77a'], [.3, .44, '#ffc08a'], [.75, .26, '#c76bb0']].forEach(([fx, fy, col], i) => { x.fillStyle = col; x.globalAlpha = .55; x.beginPath(); x.ellipse(W * fx, horizon * fy + 40, W * (.32 + i * .04), 14 + i * 3, -.05, 0, Math.PI * 2); x.fill(); }); x.restore();
  q = x.createRadialGradient(SUN.x, SUN.y, SUN.r * .6, SUN.x, SUN.y, SUN.r * 4); q.addColorStop(0, 'rgba(255,220,170,.9)'); q.addColorStop(1, 'rgba(255,140,120,0)'); x.fillStyle = q; x.fillRect(0, 0, W, horizon);
  x.fillStyle = '#fff3d6'; x.beginPath(); x.arc(SUN.x, SUN.y, SUN.r, 0, Math.PI * 2); x.fill();
  q = x.createLinearGradient(0, Y(420), X(300), horizon); q.addColorStop(0, '#3b2459'); q.addColorStop(1, '#1d1236'); x.fillStyle = q; poly(x, HILL); x.fill();
  x.strokeStyle = 'rgba(255,160,140,.6)'; x.lineWidth = 2; x.beginPath(); HILL.slice(1, 6).forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b)); x.stroke();
  q = x.createLinearGradient(0, horizon, 0, Hh); q.addColorStop(0, '#5a2f6e'); q.addColorStop(.4, '#25204e'); q.addColorStop(1, '#0e0d26'); x.fillStyle = q; x.fillRect(0, horizon, W, Hh - horizon);
  // wet reflections: the sun broken into glints on the water
  for (let k = 0; k < 26; k++) { const y = horizon + 6 + k * k * .55, w = (70 - k * 2) * (.6 + hash(k, 2, 7) * .6); x.fillStyle = `rgba(255,${200 - k * 3},${150 + k},${.75 - k * .025})`; x.fillRect(SUN.x - w / 2 + (hash(k, 1, 7) - .5) * 30, y, w, 2 + k * .12); } }
// lamps on the hill and a lantern at the masthead: light glowing through the frame
const lamps = [[90, 520], [130, 505], [150, 540], [210, 520], [60, 560], [250, 560], [300, 585]].map(([u, v]) => [X(u), Y(v)]);
// the cel: flat base colours, hard shadow and highlight shapes, coloured outlines
const cel = sheet(); { const x = cel.getContext('2d'); x.lineJoin = 'round';
  const fill = (pts, col) => { poly(x, pts); x.fillStyle = col; x.fill(); }, line = (pts) => { poly(x, pts); x.strokeStyle = LINE; x.lineWidth = 2.6; x.stroke(); };
  fill(HULL, '#3b6ea0'); fill(T([[372, 752], [775, 752], [730, 800], [420, 800]]), '#22436e'); fill(T([[358, 712], [782, 712], [778, 722], [362, 722]]), '#9cc8ec'); line(HULL);
  fill(SAIL, '#fbe6ef'); fill(T([[580, 470], [690, 660], [580, 660]]), '#c88db7'); fill(T([[590, 345], [610, 380], [590, 380]]), '#ffffff'); line(SAIL);
  fill(JIB, '#f6d2df'); fill(T([[552, 520], [552, 660], [470, 660]]), '#a46fa0'); line(JIB);
  fill(T([[561, 300], [571, 300], [571, 704], [561, 704]]), '#4a3150'); line(T([[561, 300], [571, 300], [571, 704], [561, 704]])); }
const frame = sheet(), fx = frame.getContext('2d'), red = sheet(), rx = red.getContext('2d'), rest = sheet(), bx = rest.getContext('2d');
return (t) => {
  const step = Math.floor(t * 12) / 12, slide = (1 - M.prog(t, 0, 5.5, 'out')) * 26;
  fx.clearRect(0, 0, W, Hh); fx.drawImage(bg, -slide * .4, 0, W + slide, Hh);
  fx.save(); fx.globalCompositeOperation = 'lighter'; [...lamps, [X(566), Y(298)]].forEach(([lx, ly], i) => { const on = .7 + .3 * Math.sin(step * 4 + i); const q = fx.createRadialGradient(lx, ly, 0, lx, ly, 16 + (i === lamps.length ? 10 : 0));
    q.addColorStop(0, i === lamps.length ? `rgba(255,120,190,${on})` : `rgba(255,214,140,${on})`); q.addColorStop(1, 'rgba(255,120,120,0)'); fx.fillStyle = q; fx.beginPath(); fx.arc(lx, ly, 26, 0, Math.PI * 2); fx.fill(); fx.fillStyle = '#fff6e0'; fx.fillRect(lx - 1, ly - 1, 2.5, 2.5); }); fx.restore();
  fx.drawImage(cel, slide * .2, Math.sin(step * 2) * 1.5);
  // videotape playback: red shifted against green-blue, bloom, scanlines, noise, darkened corners, a tracking line
  rx.globalCompositeOperation = 'source-over'; rx.clearRect(0, 0, W, Hh); rx.drawImage(frame, 0, 0); rx.globalCompositeOperation = 'multiply'; rx.fillStyle = '#ff0000'; rx.fillRect(0, 0, W, Hh);
  bx.globalCompositeOperation = 'source-over'; bx.clearRect(0, 0, W, Hh); bx.drawImage(frame, 0, 0); bx.globalCompositeOperation = 'multiply'; bx.fillStyle = '#00ffff'; bx.fillRect(0, 0, W, Hh);
  g.fillStyle = '#000'; g.fillRect(0, 0, W, Hh); g.drawImage(rest, 0, 0); g.save(); g.globalCompositeOperation = 'lighter'; g.drawImage(red, 2.5, 0);
  g.filter = 'blur(8px)'; g.globalAlpha = .28; g.drawImage(frame, 0, 0); g.restore();
  g.fillStyle = 'rgba(0,0,0,.22)'; for (let y = 0; y < Hh; y += 3) g.fillRect(0, y, W, 1);
  for (let i = 0; i < 500; i++) { g.fillStyle = `rgba(255,255,255,${hash(i, Math.floor(t * 30), 3) * .06})`; g.fillRect(hash(i, Math.floor(t * 30), 1) * W, hash(i, Math.floor(t * 30), 2) * Hh, 2, 1); }
  const ty = Hh - 70 + Math.sin(t * .7) * 10; g.fillStyle = 'rgba(255,255,255,.05)'; g.fillRect(0, ty, W, 3);
  const v = g.createRadialGradient(W / 2, Hh / 2, Hh * .35, W / 2, Hh / 2, Hh * .66); v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, 'rgba(0,0,0,.6)'); g.fillStyle = v; g.fillRect(0, 0, W, Hh);
};
