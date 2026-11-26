// Checks for motion\runtime\motion-plus.js and draw.js on plain Node: no browser, no rendering (a recording stand-in for the
// canvas). Run by test_motion_runtime.py; prints one JSON line per check and exits 1 if any failed.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..', 'motion', 'runtime');
const results = [];
const check = (name, ok, detail) => results.push({ name, ok: !!ok, detail: detail === undefined ? '' : String(detail) });

function mockG(bad) {
  const calls = [];
  const target = { canvas: { width: 1920, height: 1080 }, calls };
  return new Proxy(target, {
    get(t, k) {
      if (k in t) return t[k];
      if (k === 'measureText') return (s) => ({ width: String(s).length * 10 });
      return (...args) => {
        calls.push(k);
        for (const a of args) if (typeof a === 'number' && !Number.isFinite(a)) bad.push(`${String(k)}(${args.join(', ')})`);
        return undefined;
      };
    },
    set(t, k, v) { if (typeof v === 'number' && !Number.isFinite(v)) bad.push(`set ${String(k)}=${v}`); t[k] = v; return true; },
  });
}

function load(files) {
  const bad = [];
  const doc = {
    fonts: { forEach() {}, ready: Promise.resolve() },
    createElement: () => ({ width: 0, height: 0, getContext: () => mockG(bad) }),
    getElementById: () => ({}),
  };
  const win = { addEventListener() {}, __hf: undefined };
  const ctx = vm.createContext({ window: win, document: doc, Math, console });
  for (const f of files) vm.runInContext(fs.readFileSync(path.join(root, f), 'utf8'), ctx, { filename: f });
  return { M: win.M, bad };
}

// 1. motion.js alone, then with the additions: every old name still does the same thing
const base = load(['motion.js']).M;
const oldNames = Object.keys(base.ease);
const before = {};
for (const n of oldNames) before[n] = [0, 0.1, 0.33, 0.5, 0.77, 1].map((x) => base.ease[n](x));
const { M, bad } = load(['motion.js', 'motion-plus.js', 'draw.js']);
check('old curves untouched', oldNames.every((n) => JSON.stringify(before[n]) === JSON.stringify([0, 0.1, 0.33, 0.5, 0.77, 1].map((x) => M.ease[n](x)))));
check('old names still there', ['prog', 'life', 'set', 'split', 'fit', 'num', 'rand', 'el', 'start', 'block'].every((n) => typeof M[n] === 'function'));

// 2. new curves
const names = ['sineInOut', 'quartOut', 'quintOut', 'quartIn', 'quartInOut', 'circOut', 'smooth', 'backOutSoft', 'anticipate'];
check('new curves start at 0 and end at 1', names.every((n) => Math.abs(M.ease[n](0)) < 1e-9 && Math.abs(M.ease[n](1) - 1) < 1e-9), names.map((n) => M.ease[n](0).toFixed(3)).join());
const mono = (f) => { let p = -1; for (let i = 0; i <= 200; i++) { const v = f(i / 200); if (v < p - 1e-9) return false; p = v; } return true; };
check('smooth, quart and sine curves never go backwards', ['sineInOut', 'quartOut', 'quintOut', 'quartIn', 'quartInOut', 'circOut', 'smooth'].every((n) => mono(M.ease[n])));
let mx = 0; for (let i = 0; i <= 1000; i++) mx = Math.max(mx, M.ease.backOutSoft(i / 1000));
check('backOutSoft overshoots about 3%', Math.abs(mx - 1.03) < 0.004, mx.toFixed(4));
let mn = 0; for (let i = 0; i <= 1000; i++) mn = Math.min(mn, M.ease.anticipate(i / 1000));
check('anticipate winds back first', mn < -0.05, mn.toFixed(4));
const ease = M.bezier(0.25, 0.1, 0.25, 1);
check('bezier matches the CSS ease', Math.abs(ease(0.5) - 0.8024) < 0.003 && ease(0) === 0 && ease(1) === 1, ease(0.5).toFixed(4));
check('bezier overshoots when y is above 1', M.bezier(0.34, 1.56, 0.64, 1)(0.6) > 1.0);
check('bezier is cached', M.bezier(0.2, 0, 0, 1) === M.bezier(0.2, 0, 0, 1));
check('M.prog takes a function as the curve', Math.abs(M.prog(0.5, 0, 1, M.springEase(0.1)) - M.springEase(0.1)(0.5)) < 1e-12);

// 3. springs
const zOf = (o) => (o.damping) / (2 * Math.sqrt(o.stiffness * (o.mass || 1)));
const under = { stiffness: 200, damping: 10, mass: 1 };
let peak = 0; for (let t = 0; t < 5; t += 0.001) peak = Math.max(peak, M.spring(t, under));
const zu = zOf(under);
check('underdamped spring overshoots by exp(-pi z / sqrt(1-z^2))', Math.abs(peak - 1 - Math.exp(-Math.PI * zu / Math.sqrt(1 - zu * zu))) < 0.002, peak.toFixed(4));
let crit = 0; for (let t = 0; t < 5; t += 0.001) crit = Math.max(crit, M.spring(t, { stiffness: 100, damping: 20 }));
check('critically damped spring never passes 1', crit <= 1 + 1e-9, crit);
check('overdamped spring is monotone', mono((x) => M.spring(x * 5, { stiffness: 100, damping: 60 })));
check('a spring starts at its start value and honours from/to/delay', M.spring(0) === 0 && M.spring(0.2, { delay: 0.5 }) === 0 && Math.abs(M.spring(20, { from: 10, to: 30 }) - 30) < 1e-6);
check('no NaN for huge t on any damping', [5, 26, 40, 400].every((c) => Number.isFinite(M.spring(1e4, { stiffness: 170, damping: c }))));
const settle = M.springSettle(under);
check('springSettle is the time it stays within 0.2%', settle > 0.2 && settle < 3 && Math.abs(M.spring(settle + 0.05, under) - 1) < 0.002 && Math.abs(M.spring(settle - 0.05, under) - 1) > 0.0015, settle.toFixed(3));
for (const os of [0, 0.03, 0.08, 0.2, 0.4]) {
  const f = M.springEase(os); let top = 0; for (let i = 0; i <= 2000; i++) top = Math.max(top, f(i / 2000));
  check(`springEase(${os}) overshoots ${os}`, f(0) === 0 && f(1) === 1 && Math.abs(top - 1 - os) < 0.006 + os * 0.03, top.toFixed(4));
}
check('springEase is cached', M.springEase(0.08) === M.springEase(0.08));

// 4. stagger, typed, camera
const d = [0, 1, 2, 3, 4].map((i) => M.stagger(i, 5, { each: 0.1 }));
check('stagger runs in order', JSON.stringify(d.map((v) => +v.toFixed(3))) === '[0,0.1,0.2,0.3,0.4]', d);
const capped = [0, 9].map((i) => M.stagger(i, 10, { each: 0.2, total: 0.5 }));
check('stagger total caps the whole run', Math.abs(capped[1] - 0.5) < 1e-9, capped);
const c5 = [0, 1, 2, 3, 4].map((i) => M.stagger(i, 5, { each: 0.1, from: 'center' }));
check('stagger from the centre starts in the middle', c5[2] === 0 && c5[0] === c5[4] && c5[1] === c5[3], c5);
check('stagger random is repeatable', M.stagger(3, 8, { from: 'random', seed: 4 }) === M.stagger(3, 8, { from: 'random', seed: 4 }));
check('typed counts letters', M.typed('hello', -1) === 0 && M.typed('hello', 0, 0, 10) === 1 && M.typed('hello', 0.25, 0, 10) === 3 && M.typed('hello', 9, 0, 10) === 5);
const keys = [{ t: 0, z: 1 }, { t: 2, z: 4, ease: 'linear' }];
check('camera zoom runs in log space', Math.abs(M.camera(keys, 1).z - 2) < 1e-9 && M.camera(keys, -1).z === 1 && M.camera(keys, 9).z === 4);
const cam = { x: 100, y: -40, z: 2 };
const far = M.parallax(cam, 0.2), mid = M.parallax(cam, 0.6), near = M.parallax(cam, 1.4);
check('parallax: nearer layers move more', M.parallax(cam, 0).x === -0 && Math.abs(far.x) < Math.abs(mid.x) && Math.abs(mid.x) < Math.abs(near.x) && far.s < mid.s && mid.s < near.s);

// 5. drawing helpers: every number handed to the canvas is finite, and a walker's planted feet stay put
const D = M.draw;
const g = mockG(bad);
D.family = '"Montserrat", sans-serif';
for (let i = 0; i <= 90; i++) {
  const t = i / 30;
  D.camera(g, t, { t0: 0, t1: 3, z0: 1.03, z1: 1.08, px: 40, py: -20 });
  D.typeText(g, 'ALWAYS THE SAME', 200, 300, 80, t, 0.2, '#222', { align: 'center' });
  D.popText(g, '!', 900, 400, 120, t, 0.5, '#d62828', { rot: 0.3 });
  D.redX(g, 800, 500, 300, 200, t, 1);
  D.splat(g, t, 1.2); D.splat(g, t, 1.2, { color: '#000', w: 1080, h: 1920 });
  const walk = { phase: (t * 0.9) % 1 };
  for (const v of ['front', 'side']) {
    D.person(g, { x: 300 + t * 20, y: 900, h: 420, t, view: v, dir: 1, walk, speak: i % 2, hands: ['point', 'fist'], arms: [[500, 600], null], look: [1, 0] });
    D.person(g, { x: 1200, y: 900, h: 300, t, view: v, dir: -1, hair: 'bun', head: 1.2, smile: -0.5, brow: -1, mouth: 0.6 });
  }
  D.blur(g, (gg, ti) => D.person(gg, { x: 300, y: 900, h: 420, t: ti }), t, { n: 3, shutter: 0.5, fps: 30 });
}
check('every number given to the canvas is finite', bad.length === 0, bad.slice(0, 3).join(' | '));
check('the helpers draw something', g.calls.length > 2000, g.calls.length);

const LEG = 38 * 4.2;     // person h 420: u = 4.2, leg = 2 x 19u
let slide = 0, pairs = 0, prev = null;
for (let i = 0; i <= 240; i++) {
  const phi = i / 60 * 0.8, x0 = 200, dir = 1;
  const r = D.person(mockG([]), { x: x0 + dir * 1.5 * LEG * phi, y: 900, h: 420, t: 0, view: 'side', dir, walk: { phase: phi % 1 } });
  if (prev) r.feet.forEach((f, k) => { if (f[2] && prev[k][2]) { slide = Math.max(slide, Math.abs(f[0] - prev[k][0])); pairs++; } });
  prev = r.feet;
}
check('a walker\'s planted foot does not slide (side view)', pairs > 100 && slide < 1e-6, `${pairs} pairs, largest move ${slide.toExponential(2)} px`);
const lift = D.person(mockG([]), { x: 500, y: 900, h: 420, t: 0, view: 'side', walk: { phase: 0.75 } });
check('a swinging foot is off the ground', lift.feet.some((f) => !f[2] && f[1] < 900 - 1), JSON.stringify(lift.feet));
const pt = D.person(mockG([]), { x: 500, y: 900, h: 420, t: 0, arms: [[400, 620], [600, 620]] });
check('arms reach their targets', Math.hypot(pt.hand[0][0] - 400, pt.hand[0][1] - 620) < 1 && Math.hypot(pt.hand[1][0] - 600, pt.hand[1][1] - 620) < 1);

// 6. nothing in the additions breaks the scene rules (no timers, rAF, random, network)
for (const f of ['motion-plus.js', 'draw.js']) {
  const src = fs.readFileSync(path.join(root, f), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
  check(`${f} has no timers, clocks, random or network`, !/Math\.random|requestAnimationFrame|setTimeout|setInterval|Date\.now|performance\.now|fetch\(|gsap/i.test(src));
}

for (const r of results) console.log(JSON.stringify(r));
process.exit(results.every((r) => r.ok) ? 0 : 1);
