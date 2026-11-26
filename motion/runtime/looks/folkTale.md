# Folk-tale storybook: gouache over a pencil drawing, where depth is the medium: rich opaque paint up close thinning to a pale wash and then to bare pencil at the back

A long story with a place in it: a fairy tale, a family story, a garden, a village, a memory, a lesson told as a tale. Its kit has the most ready plant marks of any hand here, so it's quickest on growing things. It can run as a whole film, a scene behind a speaker or a storybook cutaway. It's the AI's choice for this video.

`const F = M.look.folkTale.start(c.w, c.h, {scale})` in your block, on one full-frame canvas. `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; const g = cv.getContext('2d');` gives you that canvas. You write the scene and the subject; this is only the kit.

**How it works.** A picture is a *work*: a surface, a ground and a list of marks in order. Make it once at the top of the block, add every mark there, then draw it each frame: `const pic = F.page('garden'); ...; return (t) => { F.begin(g); pic.draw(g, {p: M.prog(t, .5, 10)}); };`. `p` 0..1 is how far through it is, so the drawing makes itself; any p gives the same pixels in any order, and at 1 it's one sprite a frame. `pic.draw(g, {p, x, y, s, r, alpha})`; `g.translate` and `g.scale` are your camera. `pic.at(n)` says where mark n ends. A part that moves goes on its own work: `F.page('fox', {paper: false, w, h})`.

**The medium.** Warm cream cartridge paper, an HB pencil drawing first, then paint from back to front. Every mark takes a depth `d`, 0 at the viewer's feet, 1 at the horizon: depth mixes the colour towards haze, thins the paint and drops its texture, and past about 0.9 only the pencil is left. So the back of the picture is drawn and the front is painted, and the white sheet is the sky. Foreground paint is opaque, with dry-brush drags, sponge mottle and a darker settled rim. Big washes come on behind a noisy wet front, never a fade. One low sun at the upper left.

**The order that makes it read.** The pencil lay-in -> the far washes -> the middle -> the big near forms -> leaves, then their veins -> flowers, rays one by one before the disc -> grass clump by clump -> a few lines of pencil back over the paint.

**What it gives**
- `F.page(id, {w, h, glow, paper})` the work. `glow` `[[x, y, radius, colour], ...]` the paper's slow warmth.
- `F.lines(pic, [{pts, seed, w, a, closed, per, col, retrace}, ...], {per})` the pencil, paced by length.
- `F.wash(pic, poly, color, {seed, d, ang, a, tex, mottle, rim, rimW, rimA, wob, per})` a big area with a wet front. `tex: {cols, n, len, w, ang}` dry-brush drags; `mottle: {cols, n, r}` sponging.
- `F.mark(pic, per, (c, p) => ...)` any mark below at progress `p`, on the page's surface `c`:
  `F.leaf(c, {x, y, a, len, wid, col, seed, bend, d, serr, vein, stalk, round, cord, tri}, p)`, `F.lineLeaf`, `F.petal`, `F.sunflower(c, {x, y, r, rot, sq, seed, n, pl, pw, d, droop, pal}, p)`, `F.daisy(c, x, y, r, seed, d, sq, p)`, `F.bell(c, x, y, s, ang, seed, d, col, p)`, `F.dogRose(c, x, y, r, rot, sq, seed, d, p)`, `F.umbel(c, x, y, r, seed, col, p, a)`, `F.grass(c, {x0, x1, base(x), n, h, w, cols, lean, seed, d, tip, spread, a}, p)`, `F.limb(c, ctrl, w0, w1, col, seed, d, p, shade, grain)`, `F.lineLimb`, `F.pumpkin(c, x, y, rx, ry, seed, d, p, col)`, `F.gourdLeaf`, `F.tendril`, `F.stroke(c, ctrl, w0, w1, col, a, p)`, `F.gouache(c, poly, col, o)`, `F.reveal(c, box, ang, p, seed, fn)`, `F.pencil(c, line, p)`, `F.sketch(c, lines, p)`.
- `F.faded(G, box, mask, draw)` paint thinning to bare drawing through a mask (with `F.ramp`, `F.radial`); `F.glowBand`. These take `G` from `pic.add(weight, (G, q) => ...)`.
- `F.far(c, d)`, `F.lighten`, `F.darken`, `F.palette`, `F.bbox`, `F.at`, `F.rgba`, `F.ribbonOf`, `F.cutAt`; `pic.pause(weight)`.
- The plain parts: `F.plate`, `F.piece`, `F.smooth`, `F.oval`, `F.mix`, `F.rng`, `F.fractal`, `F.bounds`, `F.inside`.

**Shapes and helpers, on every paint and print kit.** Points are `[x, y]`. `F.smooth(pts, closed, per)` a curve through points, `F.oval(cx, cy, rx, ry, n, a0)` a closed loop of `n` points, `F.line(a, b, bow)`, `F.poly(corners, per)`, `F.turn(pts, cx, cy, degrees)`, `F.displace(pts, amp, freq, oct, seed)` a wobble baked into the points, `F.mix(a, b, t)` two `#rrggbb` colours, `F.rng(seed)` a function giving 0..1, `F.fractal(seed, x, y, fx, fy, oct)` smooth noise 0..1, `F.inside(shape, x, y)`, `F.bounds(pts)` `{x0, y0, x1, y1}`, `F.clamp(v, a, b)`. `pic.add` must be called before the first draw.

**What the kit can't do for you.** It has plants and a pumpkin, and no people, animals or houses: draw those from `F.gouache` shapes and pencil lines. The picture depends on real depth: keep `d` rising with distance and leave the back in pencil, or it turns into an ordinary flat illustration.

**Cost.** Measured on about 15 marks at full size, on a shared PC, headless: 19-22 ms a frame with a graphics card, 23-34 ms without, about 170 ms on its first frame. Finished, it's one sprite. A mark with `tex` or `mottle` is many small strokes. The hand's own texture (paper, weave, dots, grain) is a fixed size in pixels, so a frame drawn smaller than the project shows it coarser than the export: check texture at full size.

Refused as everywhere: timers, clock reads, `Math.random` (`F.rng`), the network. Write the name out as `M.look.folkTale`, or it won't load.
