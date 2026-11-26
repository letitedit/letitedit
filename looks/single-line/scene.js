const H = M.look.singleLine.start(c.w, c.h), P = H.paper(), W = H.work('boat');
const sun = H.ball(SUN.x, SUN.y, SUN.r), hill = H.across(HILL, .3);
const tone = (x, y) => { if (H.inside(HULL, x, y)) return .95; if (H.inside(SAIL, x, y)) return .02; if (H.inside(JIB, x, y)) return .4; if (Math.abs(x - X(566)) < K(5) && y > Y(300) && y < Y(700)) return 1; if (H.inside(HILL, x, y)) return .3 + .5 * hill(x, y); if (y > Y(640)) return .25 + .55 * (y - Y(640)) / K(440); return Math.max(sun(x, y) * .85, .08); };
H.spiral(W, tone, {cx: X(566), cy: Y(560)});
return (t) => { H.begin(g); P.draw(g); W.draw(g, {p: Math.min(1, t / 5.6)}); H.begin(g); H.finish(g); };