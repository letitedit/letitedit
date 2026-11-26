// ASCII terminal in plain Canvas 2D: every image is real characters on a monospace grid, picked by ink density, glowing in amber
// phosphor on dark curved glass with scanlines. The picture is first drawn in grey on a hidden canvas, then read cell by cell.
const W = c.w, Hh = c.h, CW = 9, CH = 16, X0 = 22, Y0 = 42, cols = Math.floor((W - 2 * X0) / CW), rows = Math.floor((Hh - Y0 - 100) / CH);
const AMBER = [255, 176, 64], RAMP = ' .,:;-~=+*o#%@';
const hash = (i, j, k) => { const v = Math.sin(i * 127.1 + j * 311.7 + k * 74.7) * 43758.5453; return v - Math.floor(v); };
// 1. the picture in grey levels (brightness = how much ink)
const pic = document.createElement('canvas'); pic.width = W; pic.height = Hh; const pc = pic.getContext('2d');
const poly = (pts) => { pc.beginPath(); pts.forEach(([a, b], i) => i ? pc.lineTo(a, b) : pc.moveTo(a, b)); pc.closePath(); };
let q = pc.createLinearGradient(0, 0, 0, Y(640)); q.addColorStop(0, '#000000'); q.addColorStop(.55, '#0a0a0a'); q.addColorStop(1, '#2a2a2a'); pc.fillStyle = q; pc.fillRect(0, 0, W, Y(640));
q = pc.createRadialGradient(SUN.x, SUN.y, SUN.r * .8, SUN.x, SUN.y, SUN.r * 3); q.addColorStop(0, 'rgba(150,150,150,1)'); q.addColorStop(1, 'rgba(0,0,0,0)'); pc.fillStyle = q; pc.fillRect(0, 0, W, Hh);
pc.fillStyle = '#fff'; pc.beginPath(); pc.arc(SUN.x, SUN.y, SUN.r, 0, Math.PI * 2); pc.fill();
pc.fillStyle = '#6e6e6e'; poly(HILL); pc.fill(); pc.fillStyle = '#050505'; pc.fillRect(0, Y(640), W, Hh);
pc.strokeStyle = '#7a7a7a'; pc.lineWidth = 5; WAVES.forEach((w) => { pc.beginPath(); w.forEach(([a, b], i) => i ? pc.lineTo(a, b) : pc.moveTo(a, b)); pc.stroke(); });
for (let k = 0; k < 6; k++) { pc.fillStyle = `rgb(${200 - k * 25},${200 - k * 25},${200 - k * 25})`; pc.fillRect(SUN.x - 50 + k * 6, Y(680 + k * 40), 100 - k * 12, 6); }
pc.fillStyle = '#9c9c9c'; poly(HULL); pc.fill(); pc.fillStyle = '#e8e8e8'; poly(SAIL); pc.fill(); pc.fillStyle = '#c4c4c4'; poly(JIB); pc.fill(); pc.fillStyle = '#b0b0b0'; pc.fillRect(X(562), Y(300), 6, Y(700) - Y(300));
// 2. read it one cell at a time
const small = document.createElement('canvas'); small.width = cols; small.height = rows; const sm = small.getContext('2d'); sm.imageSmoothingQuality = 'high';
sm.drawImage(pic, X0, Y0 + 2 * CH, cols * CW, rows * CH, 0, 0, cols, rows);
const data = sm.getImageData(0, 0, cols, rows).data, grid = [];
for (let r = 0; r < rows; r++) { let line = ''; for (let k = 0; k < cols; k++) { const v = Math.max(0, data[(r * cols + k) * 4] / 255 - .05) / .95; line += RAMP[Math.min(RAMP.length - 1, Math.floor(Math.pow(v, .85) * RAMP.length))]; } grid.push(line); }
const text = (x, s, r, col, a = 1) => { x.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},${a})`; x.fillText(s, X0, Y0 + r * CH); };
const glyphs = document.createElement('canvas'); glyphs.width = W; glyphs.height = Hh; const gl = glyphs.getContext('2d');
return (t) => {
  // the glass
  q = g.createRadialGradient(W / 2, Hh / 2, 50, W / 2, Hh / 2, Hh * .7); q.addColorStop(0, '#1a1209'); q.addColorStop(1, '#070503'); g.fillStyle = q; g.fillRect(0, 0, W, Hh);
  // the grid is typed row by row; the prompt and status line are characters too
  gl.clearRect(0, 0, W, Hh); gl.font = '600 15px Consolas, "Cascadia Mono", "Courier New", monospace'; gl.textBaseline = 'top';
  text(gl, '> draw small_boat --phosphor amber', 0, AMBER, .95);
  const shown = Math.floor(rows * M.prog(t, .4, 4.2, 'linear'));
  for (let r = 0; r < shown; r++) text(gl, grid[r], r + 2, AMBER, .88 + .12 * hash(r, 1, 1));
  const title = '[ THE SMALL BOAT ]', pad = Math.floor((cols - title.length) / 2);
  if (t > 4.8) text(gl, ' '.repeat(pad) + title, rows + 2.4, AMBER, 1);
  const cursor = Math.floor(t * 2.2) % 2 === 0 ? '█' : ' ';
  text(gl, `${cols}x${rows} cells  ready ${cursor}`, rows + 3.6, AMBER, .7);
  // phosphor glow: the glyphs again, blurred and added
  g.drawImage(glyphs, 0, 0); g.save(); g.globalCompositeOperation = 'lighter'; g.filter = 'blur(4px)'; g.globalAlpha = .8; g.drawImage(glyphs, 0, 0); g.filter = 'blur(14px)'; g.globalAlpha = .5; g.drawImage(glyphs, 0, 0); g.restore();
  // scanlines, a faint rolling band, dark curved corners and the bezel
  g.fillStyle = 'rgba(0,0,0,.28)'; for (let y = 0; y < Hh; y += 3) g.fillRect(0, y, W, 1);
  const band = ((t * 60) % (Hh + 200)) - 100; q = g.createLinearGradient(0, band - 60, 0, band + 60); q.addColorStop(0, 'rgba(255,190,90,0)'); q.addColorStop(.5, 'rgba(255,190,90,.035)'); q.addColorStop(1, 'rgba(255,190,90,0)'); g.fillStyle = q; g.fillRect(0, band - 60, W, 120);
  q = g.createRadialGradient(W / 2, Hh / 2, Hh * .38, W / 2, Hh / 2, Hh * .62); q.addColorStop(0, 'rgba(0,0,0,0)'); q.addColorStop(1, 'rgba(0,0,0,.7)'); g.fillStyle = q; g.fillRect(0, 0, W, Hh);
  g.save(); g.fillStyle = '#16140f'; g.beginPath(); g.rect(0, 0, W, Hh); g.roundRect(10, 10, W - 20, Hh - 20, 38); g.fill('evenodd'); g.restore();
  g.strokeStyle = 'rgba(255,200,120,.08)'; g.lineWidth = 2; g.beginPath(); g.roundRect(10, 10, W - 20, Hh - 20, 38); g.stroke();
};
