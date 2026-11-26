# Broken colour: plein-air dabs of unmixed oil on primed linen, side by side for the eye to mix, high key and full of light

Bright, moving light without a hard outline: sunrise and sunset, water, a market, travel, a place or a mood more than a fact. It suits a full painted film, a world behind a speaker or a single cutaway. It's the AI's choice for this video.

`const B = M.look.brokenColour.start(c.w, c.h, {scale})` in your block, on one full-frame canvas. `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; const g = cv.getContext('2d');` gives you that canvas. You write the scene and the subject; this is only the kit.

**How it works.** A picture is a *work*: a surface, a ground and a list of marks in order. Make it once at the top of the block, add every mark there, then draw it each frame: `const pic = B.canvas('harbour'); ...; return (t) => { B.begin(g); pic.draw(g, {p: M.prog(t, .5, 10)}); };`. `p` 0..1 is how far through it is, so it paints itself; any p gives the same pixels in any order, and at 1 it's one sprite a frame. `pic.draw(g, {p, x, y, s, r, alpha})`; `g.translate` and `g.scale` are your camera. `pic.at(n)` says where mark n ends, to land a pass on a word.

**The medium.** No black: the darkest dark is ultramarine and rose. Colours sit beside each other unmixed, and the hue, value and saturation of each dab are thrown a little, so a sky is many colours. Shadows are coloured (violet, blue), never grey. Light comes from one low sun, often behind the subject, with warm rims on its side. Dabs lie along the form: flat on water, across a sail, loose in the sky. Edges come from where dabs change colour, not from a line.

**The order that makes it read.** A thin scrubbed lay-in with big strokes, ground showing (`kind: 2`) -> the masses in big dabs -> small broken dabs over everything -> a few liner strokes and the brightest touches last. The painting advances in an irregular front, patch by patch.

**What it gives**
- `B.canvas(id, {w, h, color})` the work: linen in the ground colour, with its weave over the paint. `color` is `[r, g, b]`.
- `B.dabs(pic, {step, color(x, y), ang(x, y), len, w, kind, alpha, seed, patch, order(x, y), hj, lj, sat, per, x0, y0, x1, y1})` a whole pass over an area. `color` returns `[r, g, b]`, or null to leave a spot alone; the hand breaks it per dab by `hj` (hue), `lj` (value) and `sat`. `kind`: 0 a loaded dab, 1 a liner line tapered at both ends, 2 a thin scrubbed lay-in. `patch` is the size of the wandering front in px; `order` (0..1) makes one part come before another. `per` is each dab's share of the time.
- `B.mark(a, b, rgb, {w, bend, alpha, seed, kind})` one by hand, then `B.lay(pic, marks, {per, clip, out})`.
- `B.palette` (`white, orange, red, yellow, rose, violet, ultramarine, cobalt, viridian, dark, ground`, each `[r, g, b]`), `B.broken(rgb, r, hj, lj, sat)`, `B.mixC(a, b, t)`, `B.css`, `B.toHsl`, `B.fromHsl`, `B.smoothstep`.
- `pic.add(weight, (G, q) => ...)` your own mark; `pic.pause(weight)` a beat between passes.
- The plain parts: `B.plate`, `B.piece`, `B.smooth`, `B.oval`, `B.rng`, `B.fractal`, `B.bounds`, `B.inside`, `B.within(G, shape, out, fn)`.

**Shapes and helpers, on every paint and print kit.** Points are `[x, y]`. `B.smooth(pts, closed, per)` a curve through points, `B.oval(cx, cy, rx, ry, n, a0)` a closed loop of `n` points, `B.line(a, b, bow)`, `B.poly(corners, per)`, `B.turn(pts, cx, cy, degrees)`, `B.displace(pts, amp, freq, oct, seed)` a wobble baked into the points, `B.mix(a, b, t)` two `#rrggbb` colours, `B.rng(seed)` a function giving 0..1, `B.fractal(seed, x, y, fx, fy, oct)` smooth noise 0..1, `B.inside(shape, x, y)`, `B.bounds(pts)` `{x0, y0, x1, y1}`, `B.clamp(v, a, b)`. `pic.add` must be called before the first draw.

**What the kit can't do for you.** The picture is the `color` field you write: where the light is, what's in it. Small details don't survive: think in masses and silhouettes at this dab size, and put a person or a word on top rather than painting them in. On a phone, dabs under about 10 px at 1080 wide turn to grain.

**Cost.** Measured on a scene of about 3,000 dabs at full size, on a shared PC, headless: 21 ms a frame with a graphics card, 13-22 ms without, about 150 ms on its first frame. Finished, it's one sprite. The hand's own texture (paper, weave, dots, grain) is a fixed size in pixels, so a frame drawn smaller than the project shows it coarser than the export: check texture at full size.

Refused as everywhere: timers, clock reads, `Math.random` (`B.rng`), the network. Write the name out as `M.look.brokenColour`, or it won't load.
