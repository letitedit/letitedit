const H = M.look.inkWash.start(c.w, c.h), P = H.paper(), W = H.work('boat'), C = H.palette, s = K(1);
H.ground(W, [{x: X(420), y: Y(280), rx: K(460), ry: K(280), color: C.cool, alpha: .32}, {x: X(830), y: Y(210), rx: K(170), ry: K(140), color: C.sand, alpha: .35}], {seed: 10});
H.wash(W, HILL, C.sap, {flood: 1, alpha: .5, seed: 11, bloom: [X(180), Y(520)], bloomR: K(36)}); H.wash(W, SEA, C.sea, {alpha: .5, seed: 12, bloom: [X(760), Y(930)], bloomR: K(44)});
H.wash(W, H.poly(HULL, 8), C.rufous, {flood: 1, alpha: .75, seed: 13}); H.wash(W, H.poly(JIB, 8), C.buff, {flood: 1, alpha: .55, seed: 14});
H.dab(W, H.oval(SUN.x, SUN.y, SUN.r, SUN.r, 16), C.red, {alpha: .55});
H.nib(W, H.poly(HULL, 8).concat([HULL[0]]), 2.2*s, {seed: 20}); H.nib(W, MAST, 2.6*s, {seed: 21}); H.nib(W, H.poly(SAIL, 8).concat([SAIL[0]]), 1.6*s, {seed: 22}); H.nib(W, H.poly(JIB, 8).concat([JIB[0]]), 1.6*s, {seed: 23}); H.nib(W, HILL.slice(1, 7), 1.5*s, {seed: 24});
WAVES.forEach((w, i) => H.nib(W, w, 1.4*s, {seed: 30 + i})); H.spatter(W, X(900), Y(860), {n: 40, spread: K(90), size: 2.4*s}); H.write(W, LABEL, X(60), Y(60), {cap: K(28)});
return (t) => { H.begin(g); P.draw(g); W.draw(g, {p: Math.min(1, t / 5.6)}); H.begin(g); H.finish(g); };