const H = M.look.midCentury.start(c.w, c.h), C = H.palette, u = K(1);
const pic = H.board('boat');
H.flat(pic, H.ell(SUN.x, SUN.y, SUN.r, SUN.r), C.mustard); H.flat(pic, HILL, C.green, {ang: -.1}); H.flat(pic, SEA, C.teal, {ang: .1});
H.flat(pic, HULL, C.tomato, {ang: .1}); H.flat(pic, SAIL, C.cream, {ang: 1.2}); H.flat(pic, JIB, C.ochre, {ang: 1.2});
for (let i = 0; i < 5; i++) H.dry(pic, [[X(40 + i*30), Y(760 + i*60)], [X(560 + i*80), Y(750 + i*60)]], {w: 36*u, color: C.oliveDark, per: 1.5});
H.dry(pic, [[X(100), Y(170)], [X(560), Y(150)]], {w: 50*u, color: C.cloud, per: 2});
H.line(pic, HULL.concat([HULL[0]]), {w: 2.4*u}); H.line(pic, MAST, {w: 3*u}); H.line(pic, SAIL.concat([SAIL[0]]), {w: 2*u}); H.line(pic, JIB.concat([JIB[0]]), {w: 2*u}); H.line(pic, HILL.slice(1, 7), {w: 2*u});
return (t) => { H.begin(g); pic.draw(g, {p: Math.min(1, t / 5)}); };