const I = M.look.isometric.start(c.w, c.h), Gd = I.fit(12, 10, 7), m = I.MATERIALS, sea = I.material('#2f7f92'), red = I.material('#c8452f'), cream = I.material('#f1e8d6'), wood = I.material('#7a4a2a');
const plan = I.plan('boat', Gd, (b) => { b.massing(1, 3, 0, 0, 0, 12, 10, 5); b.box(2, 0, 0, -.5, 12, 10, 0, sea); for (let k = 1; k < 12; k += 2) b.line(2, [k, 0, 0], [k, 10, 0], '#1f5f72', 1, .6);
  b.box(3, 3, 3.6, 0, 9, 6.4, .9, red); b.box(3, 4, 4, .9, 8, 6, 1.2, wood); b.box(3, 5.8, 4.9, 1.2, 6.2, 5.3, 6.2, wood); b.dome(3, 1.8, 8, 0, 1.1, I.material('#4d8b5d')); b.text(4, 'left', .9, .4, 4.6, 'BOAT', {cap: .62, color: '#27324a'});
  b.add(4, (iso, progress) => { iso.face([[6.25, 4.7, 6.1], [9.6, 4.7, 1.5], [6.25, 4.7, 1.5]], '#fff0ce', progress); iso.face([[5.7, 4.7, 5.2], [5.7, 4.7, 1.5], [3.2, 4.7, 1.5]], '#e9a64a', progress); }); });
return (t) => { I.begin(g); g.fillStyle = '#1b2030'; g.fillRect(0, 0, c.w, c.h); plan.draw(g, {progress: t / 3.6}); I.finish(g); };
