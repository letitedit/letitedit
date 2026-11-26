const H = M.look.scratchboard.start(c.w, c.h), B = H.board(), W = H.work('boat'), s = K(1), S = H.oval(SUN.x, SUN.y, SUN.r, SUN.r, 24);
H.knife(W, T([[0,640],[1080,640]]), {w: 1.6*s}); H.rim(W, HILL, {flow: .4, len: 12*s}); [HULL, SAIL, JIB].forEach((o, i) => H.knife(W, H.poly(o, 8), {closed: true, w: 2*s}));
H.fur(W, SKY, {tone: (x, y) => { const d = Math.hypot(x - SUN.x, y - SUN.y) / K(520); return Math.max(0, .34 - .32 * d); }, flow: (x, y) => Math.atan2(y - SUN.y, x - SUN.x), len: 26*s, seed: 2});
H.fur(W, S, {tone: () => .9, flow: 1.2, len: 16*s, seed: 3, cross: false});
H.fur(W, HILL, {tone: (x, y) => .12 + .32 * (1 - H.across(HILL, .3)(x, y)), flow: -.6, len: 16*s, seed: 4});
H.cuts(W, SEA, {angle: .02, gap: 7*s, w: 2*s, seed: 5, tone: (x, y) => .25 + .5 * (1 - (y - Y(640)) / K(440))});
H.fur(W, SAIL, {tone: () => .85, flow: 1.2, len: 22*s, seed: 6}); H.fur(W, JIB, {tone: () => .45, flow: 1.6, len: 20*s, seed: 7}); H.cuts(W, HULL, {angle: .1, gap: 5*s, w: 1.7*s, seed: 8, tone: (x, y) => .75 - .6 * (y - Y(700)) / K(100)});
H.knife(W, MAST, {w: 3*s}); H.scrape(W, H.oval(X(800), Y(180), K(16), K(10), 8)); H.write(W, LABEL, X(60), Y(60), {cap: K(28)});
return (t) => { H.begin(g); B.draw(g); W.draw(g, {p: Math.min(1, t / 5.6)}); H.begin(g); H.finish(g); };