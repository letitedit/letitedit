const P = M.look.paperCraft.start(c.w, c.h), s = K(1), open = {x0: X(70), y0: Y(80), x1: X(1010), y1: Y(1030)};
const table = P.table(), pros = P.proscenium('pros', open, {outer: {x0: X(14), y0: Y(10), x1: X(1066), y1: Y(1072)}}), sky = P.drop('sky', {box: open});
const sun = P.piece('sun', {cut: P.oval(SUN.x, SUN.y, SUN.r, SUN.r, 26), depth: 6, face: (x) => { x.fillStyle = '#f2b63c'; x.beginPath(); x.arc(SUN.x, SUN.y, SUN.r, 0, 7); x.fill(); }, stage: open});
const hill = P.piece('hill', {cut: HILL, depth: 7, face: (x) => { x.fillStyle = '#6f9a58'; P.path ? 0 : 0; x.beginPath(); HILL.forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b)); x.closePath(); x.fill(); }, stage: open});
const shape = (id, pts, col, d) => P.piece(id, {cut: pts, depth: d, face: (x) => { x.fillStyle = col; x.beginPath(); pts.forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b)); x.closePath(); x.fill(); }, stage: open});
const sea2 = P.row('sea2', {y: Y(800), color: '#3b7fa3', stage: open, decorate: (x, sh) => P.wavePrint(x, sh, '#cfe6f2')}), sea1 = P.row('sea1', {y: Y(650), color: P.palette.sea, stage: open, decorate: (x, sh) => P.wavePrint(x, sh, '#cfe6f2')});
const hull = shape('hull', HULL, '#c8452f', 9), sail = shape('sail', SAIL, '#f6efdf', 8), jib = shape('jib', JIB, '#eeb14d', 8), mast = shape('mast', T([[561,300],[571,300],[571,700],[561,700]]), '#3a2a1c', 6), cl = P.cloud('cl', X(280), Y(230), K(150), K(60), {stage: open});
const flats = [sky, sun, cl, hill, sea1, mast, sail, jib, hull, sea2];
return (t) => { P.begin(g); table.draw(g); flats.forEach((piece, index) => { const pose = P.land(t, index * .35, .7, [K(index % 2 ? 100 : -100), K(-80)], 'flat-' + index, 12); if (pose.shown) piece.draw(g, {pose}); }); pros.draw(g); P.finish(g); };
