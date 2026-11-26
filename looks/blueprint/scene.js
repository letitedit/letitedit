const H = M.look.blueprint.start(c.w, c.h), P = H.paper(), W = H.work('boat'), C = H.palette, s = K(1);
H.border(W); H.chain(W, T([[40,700]])[0], T([[1040,700]])[0]); H.chain(W, T([[566,240]])[0], T([[566,840]])[0]); H.chainRing(W, SUN.x, SUN.y, SUN.r * 1.2);
H.circle(W, SUN.x, SUN.y, SUN.r); H.rule(W, T([[60,640]])[0], T([[1020,640]])[0], .9*s, {color: C.dim});
H.outline(W, HULL, 5*s, {seed: 2}); H.outline(W, SAIL, 4.5*s, {seed: 8}); H.outline(W, JIB, 4.5*s, {seed: 12}); H.rule(W, MAST[0], MAST[1], 5*s, {seed: 16});
H.section(W, HULL, {gap: 11*s, seed: 3}); H.section(W, JIB, {angle: -.785, gap: 14*s, seed: 4});
H.curve(W, HILL.slice(1, 7), 1.3*s, {color: C.cyan, seed: 5});
H.dim(W, HULL[3], HULL[2], -46*s, '3.10 M', {cap: 14*s, seed: 6}); H.callout(W, 'MAINSAIL', T([[800,420]])[0], T([[680,540]])[0], {cap: 15*s, seed: 7}); H.balloon(W, '1', T([[300,590]])[0], T([[420,720]])[0], {seed: 9});
H.letter(W, LABEL, X(70), Y(70), {cap: K(30), seed: 10});
return (t) => { H.begin(g); P.draw(g); W.draw(g, {p: Math.min(1, t / 5.6)}); H.begin(g); H.finish(g); };
