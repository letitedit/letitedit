const H = M.look.charcoal.start(c.w, c.h), P = H.paper(), W = H.work('boat'), s = K(1);
H.side(W, SKY, {angle: -.22, gap: 7*s, w: 18*s, alpha: .14, seed: 11}); H.stump(W, SKY, {gap: 40*s, amp: 40*s, w: 60*s, alpha: .08, blur: 9, seed: 12});
H.lift(W, SUN.x, SUN.y, SUN.r, {seed: 13}); H.side(W, HILL, {angle: -1, gap: 5*s, w: 9*s, alpha: .34, seed: 14}); H.stump(W, HILL, {gap: 24*s, amp: 24*s, w: 26*s, alpha: .22, blur: 5, seed: 15});
H.side(W, SEA, {angle: .03, gap: 9*s, w: 11*s, alpha: .2, seed: 16}); H.erase(W, T([[300,820],[800,820],[800,880],[300,880]]), {alpha: .4, seed: 18, gap: 14*s, amp: 18*s, w: 22*s});
H.sticks(W, [H.smooth(HILL.slice(1, 7), false, 8), T([[0,640],[1080,640]])], {seed: 20}); H.sticks(W, [SAIL.concat([SAIL[0]]), JIB.concat([JIB[0]])], {seed: 22, w0: 3*s, w1: 2*s});
H.side(W, JIB, {angle: 1.2, gap: 4*s, w: 6*s, alpha: .32, seed: 23}); H.side(W, HULL, {angle: .1, gap: 3*s, w: 8*s, alpha: .9, seed: 24, hard: true}); H.compressed(W, MAST, {w0: 6*s, w1: 3.4*s, seed: 25}); H.compressed(W, HULL.concat([HULL[0]]), {seed: 26});
WAVES.forEach((w, i) => H.vine(W, H.smooth(w, false, 6), {seed: 30 + i, w0: 3*s, w1: 1.2*s})); H.write(W, LABEL, X(60), Y(60), {cap: K(28)});
return (t) => { H.begin(g); P.draw(g); W.draw(g, {p: Math.min(1, t / 5.6)}); H.begin(g); H.finish(g); };