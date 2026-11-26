const P = M.look.cutPaper.start(c.w, c.h), Q = P.c, board = P.board();
const sky = P.cut('sky', FRAME, Q.sky, {fibre: .6}), sun = P.disc('sun', SUN.x, SUN.y, SUN.r, Q.gold), hill = P.torn('hill', HILL, Q.pine, {amp: 3, lift: 1}), sea = P.torn('sea', SEA, Q.dusk, {amp: 3, lift: 1});
const hull = P.cut('hull', HULL, Q.red, {lift: 1.3}), sail = P.cut('sail', SAIL, Q.cream, {lift: 1.1}), jib = P.cut('jib', JIB, Q.peach, {lift: 1.1}), mast = P.cut('mast', T([[561,300],[571,300],[571,700],[561,700]]), Q.ink, {lift: .6});
const waves = WAVES.slice(0, 5).map((w, i) => P.torn('w' + i, [w[0], w[2], w[4], [w[4][0], w[4][1] + K(10)], [w[0][0], w[0][1] + K(10)]], Q.grass, {amp: 1.4, lift: .3})), word = P.word('w', LABEL, {x: X(300), y: Y(90), cap: K(36), rot: -.015});
const layers = [sky, sun, hill, mast, sail, jib, sea, hull, ...waves, word];
return (t) => { P.begin(g); board.draw(g); layers.forEach((piece, index) => { const pose = P.lay(t, index * .28, .65, [K(index % 2 ? 90 : -90), K(-65)]); if (pose.shown) piece.draw(g, {pose}); }); P.begin(g); P.finish(g); };
