const S = M.look.scrapbook.start(c.w, c.h), page = S.page('page'), s = K(1), hx = X(540), hy = Y(520);
const L = (pts) => pts.map(([a, b]) => [a - hx, b - hy]);
const card = S.card('card', {x: hx, y: hy, w: K(860), h: K(760), rot: -.02, color: S.palette.card, face: (x) => {
  const tone = (a, b, d) => (a, q) => d;
  S.engraved(x, L(SKY), {tone: (a, b) => .12 + .3 * (b + hy - Y(0)) / K(640), angle: 0, gap: 7*s, w: 2.4*s});
  S.engraved(x, L(S.oval(SUN.x, SUN.y, SUN.r, SUN.r, 24)), {tone: (a, b) => .55, angle: -.6, gap: 5*s, w: 2.6*s});
  S.engraved(x, L(HILL), {tone: () => .75, angle: -.7, gap: 5*s, w: 2.8*s, seed: 3}); S.tint(x, L(HILL), '#7f9f62');
  S.engraved(x, L(SEA), {tone: (a, b) => .3 + .5 * (b + hy - Y(640)) / K(440), angle: .03, gap: 6*s, w: 2.8*s, seed: 4}); S.tint(x, L(SEA), '#4f8f8a', .35);
  S.engraved(x, L(HULL), {tone: () => 1, angle: -.2, gap: 4*s, w: 3.4*s, seed: 5}); S.engraved(x, L(JIB), {tone: () => .55, angle: 1, gap: 5*s, w: 2.6*s, seed: 6}); S.tint(x, L(JIB), '#d6a13c', .5);
  x.fillStyle = '#2a2019'; x.fillRect(X(562) - hx, Y(300) - hy, 7*s, K(400)); }});
const tape = S.tape('tape', [hx, hy - K(378)], -.05, K(160), 3), strip = S.strip('strip', LABEL, {x: X(540), y: Y(960), cap: K(26)}), stamp = S.stamp('stamp', 'FILED', {x: X(860), y: Y(900), cap: K(34)});
return (t) => { S.begin(g); page.draw(g); const pose = S.lay(t, .1, 1.2, [K(-100), K(-180)]); if (pose.shown) card.draw(g, {pose, alpha: pose.alpha}); tape.draw(g, {reveal: M.prog(t, 1.3, 2.1)}); strip.draw(g, {n: M.typed(LABEL, t, 2.2, 12)}); const stampProgress = M.prog(t, 3.8, 4.1); if (stampProgress > 0) stamp.draw(g, {s: 1 + .5 * (1 - stampProgress), alpha: stampProgress}); S.ring(g, X(570), Y(750), K(270), K(90), {progress: M.prog(t, 4.2, 5.5)}); S.begin(g); S.finish(g); };
