const N = M.look.halftone.start(c.w, c.h), u = K(1), ks = N.ks;
const path = (x, s) => { x.beginPath(); s.forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b)); x.closePath(); x.fill(); };
const pic = N.print('front', {margin: 40*u, paint: (x, w, h) => { const kx = w / c.w, ky = h / c.h; x.save(); x.scale(kx, ky);
  const sky = x.createLinearGradient(0, Y(0), 0, Y(640)); sky.addColorStop(0, ks(.4, 0)); sky.addColorStop(1, ks(.06, .5)); x.fillStyle = sky; x.fillRect(0, 0, c.w, c.h);
  x.fillStyle = ks(.05, .9); x.beginPath(); x.arc(SUN.x, SUN.y, SUN.r, 0, 7); x.fill();
  x.fillStyle = ks(.62, .1); path(x, HILL); const se = x.createLinearGradient(0, Y(640), 0, Y(1080)); se.addColorStop(0, ks(.3, 0)); se.addColorStop(1, ks(.75, 0)); x.fillStyle = se; path(x, SEA);
  x.fillStyle = ks(.05, 0); path(x, SAIL); x.fillStyle = ks(.3, .8); path(x, JIB); x.fillStyle = ks(1, 0); path(x, HULL); x.fillRect(X(562), Y(300), 8*u, K(400)); x.restore();
}, lineArt: (x) => { x.font = `bold ${70*u}px Georgia, serif`; x.textAlign = 'center'; x.fillText(LABEL, c.w / 2, Y(120)); x.fillRect(X(70), Y(140), K(940), 5*u); }});
return (t) => { N.begin(g); pic.draw(g, {p: Math.min(1, t / 5)}); };