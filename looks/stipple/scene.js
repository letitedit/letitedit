const H = M.look.stipple.start(c.w, c.h), P = H.paper(), W = H.work('boat');
const sun = H.ball(SUN.x, SUN.y, SUN.r), hill = H.across(HILL, .3), sea = (x, y) => .08 + .55 * Math.pow((y - Y(640)) / K(440), 1.4);
const tone = (x, y) => { if (H.inside(HULL, x, y)) return .85; if (H.inside(SAIL, x, y)) return .03; if (H.inside(JIB, x, y)) return .28; if (Math.abs(x - X(566)) < K(4) && y > Y(300) && y < Y(700)) return 1; if (H.inside(HILL, x, y)) return .1 + .55 * hill(x, y); if (y > Y(640)) return sea(x, y); return Math.max(sun(x, y) * .8, .018 + .05 * (1 - y / c.h)); };
const made = H.dots(W, tone); H.write(W, LABEL, X(60), Y(60), {cap: K(26)});
return (t) => { H.begin(g); P.draw(g); W.draw(g, {p: Math.min(1, t / 5.6)}); H.begin(g); H.finish(g); };