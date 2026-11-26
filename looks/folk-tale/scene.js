const F = M.look.folkTale.start(c.w, c.h), C = F.palette, u = K(1);
const pic = F.page('boat');
F.lines(pic, [{pts: HILL.slice(1, 7), seed: 3, w: 1.6}, {pts: F.oval(SUN.x, SUN.y, SUN.r, SUN.r, 16), seed: 4, w: 1.4}], {per: 4});
F.wash(pic, F.oval(SUN.x, SUN.y, SUN.r, SUN.r, 16), '#e2b24a', {seed: 2, d: .3, per: 4});
F.wash(pic, HILL, C.olive, {seed: 5, d: .6, tex: {cols: ['#a3a65a'], n: 60, len: 60*u, w: 7*u, ang: .1}, per: 6});
F.wash(pic, SEA, '#4f7f8f', {seed: 7, d: .2, tex: {cols: ['#3b6a7a', '#6f9aa2'], n: 180, len: 90*u, w: 7*u, ang: 0}, mottle: {cols: ['#2f5a6a'], n: 60, r: 18*u}, per: 6});
F.wash(pic, HULL, C.umber, {seed: 8, d: .05, per: 3}); F.wash(pic, SAIL, '#efe5cf', {seed: 9, d: .1, per: 3}); F.wash(pic, JIB, '#c98a3f', {seed: 10, d: .1, per: 3});
F.mark(pic, 3, (x, p) => F.limb(x, [[X(566), Y(700)], [X(566), Y(500)], [X(566), Y(300)]], 12*u, 7*u, C.umber, 9, 0, p));
return (t) => { F.begin(g); pic.draw(g, {p: Math.min(1, t / 5)}); };