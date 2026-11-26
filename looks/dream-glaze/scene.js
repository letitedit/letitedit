const D = M.look.dreamGlaze.start(c.w, c.h), u = K(1), hz = Y(640);
const sun = D.sunlight([-.7, .32, -.25]), TT = [D.lin('#1f3f8f'), D.lin('#3e9bb0'), D.lin('#f2e9a0'), D.lin('#2d5f7a'), D.lin('#0f2438')];
const skyR = [[0, TT[0]], [.72, TT[1]], [1, TT[2]]], gndR = [[0, TT[3]], [1, TT[4]]];
const raisedPolygon = (points, material) => ({box: [Math.min(...points.map(point => point[0])) - 2, Math.min(...points.map(point => point[1])) - 2, Math.max(...points.map(point => point[0])) + 2, Math.max(...points.map(point => point[1])) + 2], at: (x, y, out) => {
  let inside = false, distance = 1e9;
  points.forEach((point, index) => { const next = points[(index + 1) % points.length], dx = next[0] - point[0], dy = next[1] - point[1], along = Math.max(0, Math.min(1, ((x - point[0]) * dx + (y - point[1]) * dy) / (dx * dx + dy * dy))); distance = Math.min(distance, Math.hypot(x - point[0] - along * dx, y - point[1] - along * dy)); if ((point[1] > y) !== (next[1] > y) && x < point[0] + (y - point[1]) * dx / dy) inside = !inside; });
  out[0] = inside ? distance : -distance; out[1] = inside ? K(18) * (1 - Math.exp(-distance / K(14))) : 0; out[2] = x; out[3] = y; out[4] = material;
}});
const objs = () => [D.ball([SUN.x, SUN.y, SUN.r], 1), raisedPolygon(HULL, 2), D.tube(D.curve([[X(566), Y(700), K(11)], [X(566), Y(500), K(9)], [X(566), Y(300), K(6)]]), 6*u, 3), raisedPolygon(SAIL, 4), raisedPolygon(JIB, 5)];
const al = {1: D.lin('#f2c14e'), 2: D.lin('#c9452f'), 3: D.lin('#40304f'), 4: D.lin('#f1e8d6'), 5: D.lin('#e8701f')};
const pic = D.picture('dream', {
  back: (x, y, o) => { if (y < hz) { D.ramp(skyR, (y - Y(0)) / K(640), o); const f = D.fbm(x * .004, y * .012, 3, 7); o[0] += f * .04; o[1] += f * .04; o[2] += f * .03; } else { D.ramp(gndR, (y - hz) / K(440), o); const n = D.fbm(x * .02, y * .05, 3, 9) * .25 + .85; o[0] *= n; o[1] *= n; o[2] *= n; } },
  objs, paint: (b, m, x, y, h, nx, ny, nz) => { sun.light(al[m], nx, ny, nz, sun.sunAt(b, x, y, h), .9, .35, 40); }, perBack: 3, perForm: 1 });
return (t) => { D.begin(g); pic.draw(g, {p: Math.min(1, t / 5)}); };
