const H = M.look.toyBrick.start(c.w, c.h), C = H.COLOURS;
const mod = H.model('boat', (b) => { b.base(0, 0, 16, 12, C.blue); b.step(); b.color(C.red); b.brick(3, 3, 10, 6); b.prism([[13, 3], [13, 9], [15, 6]], {color: C.red}); b.step(); b.color(C.black); b.plate(3, 3, 12, 6, {y: 3}); b.step();
  b.color(C.tan); b.brick(7, 5, 1, 1, {y: 4, h: 28}); b.step(); b.color(C.white); for (let level = 0; level < 7; level++) b.brick(8, 5, 7 - level, 1, {y: 5 + level * 3, h: 3}); b.step(); b.color(C.yellow); for (let level = 0; level < 4; level++) b.brick(3 + level, 5, 4 - level, 1, {y: 5 + level * 3, h: 3}); }, {fps: c.fps, beat: .4});
return (t) => { H.begin(g); H.backdrop(g); mod.draw(g, {frame: Math.round(Math.min(1, t / 5) * mod.total)}); H.finish(g); };
