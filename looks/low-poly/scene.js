const L = M.look.lowPoly.start(c.w, c.h, {sun: [-.35, .45, -.82]}), W = c.w, H = c.h;
const sky = L.sky('sky', [[0, '#26528a'], [.4, '#7fb2d6'], [.6, '#f6d6a2'], [1, '#f6bf92']], {sun: [SUN.x, SUN.y]});
const height = (x, z) => { const d = Math.abs(x + 18) - 8 - z * .1; return (d < 0 ? (-d) * .7 + L.fractal(7, x, z, .11, .11, 3) * 3 : -1.2) + 11 * L.smoothstep(52, 80, z) * L.ridged(23, x + 40, z, .045); };
const land = L.mesh((m) => { m.terrain({z1: 110, cols: 38, height, floor: 0, color: (x, y, z, up) => y > 6 || up < .55 ? '#6a6275' : '#4f7a4c'}); });
const lake = L.mesh((m) => m.water({x0: -60, x1: 60, z0: -3, z1: 110, near: '#1f5a7a', far: '#8fc2d6'}));
const boat = L.mesh((m) => { const rings = []; for (let i = 0; i <= 8; i++) { const u = i / 8, w = .9 * Math.sin(u * Math.PI) + .04, yy = .9 + .3 * (2 * u - 1) ** 2, z = (u - .5) * 4.4; rings.push([[-w, yy, z], [-w * .7, .1, z], [0, 0, z], [w * .7, .1, z], [w, yy, z]]); } m.loft(rings, '#b3392b', {closed: false}); });
const rig = L.mesh(m => { m.box(-.035, .6, 0, .035, 4.4, .06, '#473b39'); m.tri([.08, 4.2, .04], [1.8, 1.1, .04], [.08, 1.1, .04], '#fff0cf'); m.tri([-.12, 3.6, .04], [-.12, 1.1, .04], [-1.4, 1.1, .04], '#e9a64a'); });
return (t) => { L.begin(g); g.clearRect(0, 0, W, H); const cam = {x: -.8 * (1 - M.prog(t, .1, 4.5)), y: 3.3, z: -4, pitch: .035}; sky.draw(g); L.draw(g, cam, [lake, land, {mesh: boat, x: .1, y: .02, z: 7, ry: 1.3}, {mesh: rig, x: .1, y: .02, z: 7, ry: 0}], {reflect: true, ripples: 60}); L.finish(g); };
