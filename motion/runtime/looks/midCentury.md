# Mid-century gouache: opaque matte flats on warm board, a dry brush dragged across them and a loose ink line printed off register, like a 1950s picture book

Warm, optimistic and graphic: a travel poster, a town, a family story, a how-we-got-here, a childhood memory. It can run as a whole film, a scene behind a speaker or a card. It's the AI's choice for this video.

`const K = M.look.midCentury.start(c.w, c.h, {scale})` in your block, on one full-frame canvas. `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; const g = cv.getContext('2d');` gives you that canvas. You write the scene and the subject; this is only the kit. In the source this style had no kit of its own: its marks were pulled out of one picture.

**How it works.** A picture is a *work*: a surface, a ground and a list of marks in order. Make it once at the top of the block, add every mark there, then draw it each frame: `const pic = K.board('town'); ...; return (t) => { K.begin(g); pic.draw(g, {p: M.prog(t, .5, 9)}); };`. `p` 0..1 is how far through it is, so it paints itself; any p gives the same pixels in any order, and at 1 it's one sprite a frame. `pic.draw(g, {p, x, y, s, r, alpha})`; `g.translate` and `g.scale` are your camera. For a piece that moves, paint it on its own work with `K.board('kite', {color: null, w, h})`.

**The medium.** Gouache is opaque and matte: a lighter colour goes straight over a darker one. Shapes go down **big to small**, each flat with a slightly ragged edge and no outline. Then the nearly dry brush, whose bristles skip the board's tooth. **Don't skip it**: without the dry brush and the line, this looks like flat vector. Last the ink line, thin, thick-thin and loose. It sits **off register**: it wanders past the shape's edge and leaves out edges the colour already says. A limited palette with one key; one sun high on the left, so each form shows a darker right side and a flat shadow.

**What it gives**
- `K.board(id, {w, h, color})` the work. `color: null` leaves it bare.
- `K.flat(pic, pts, color, {ang, seed, per})` one opaque flat, laid by the loaded brush in passes at angle `ang`. Keep corners on a house (give corner points), smooth a hill (`K.sm`, `K.ridge`).
- `K.dry(pic, [a, b], {w, color, seed, per})` the dry brush dragged straight from a to b, breaking up as it runs out. Use many: grass, cloud edges, weather on walls.
- `K.line(pic, pts, {w, color, seed, per, reg})` the ink line on its own plate, at `K.REG` off the colour unless you say.
- `K.sm(pts, closed, per)`, `K.ridge(top, base)`, `K.ell(cx, cy, rx, ry, rot)`, `K.limb(centre, radii, bulge)` for shapes; `K.edge(pts, seed)` the ragged edge alone, and `K.shape(g, edge, color)` for a flat redrawn every frame.
- `K.palette` (`board, cloud, far, far2, olive, oliveDark, green, greenDark, cream, pink, ochre, turquoise, white, tomato, teal, brown, dark, cypress, skin, hair, blush, red, mustard, ink`).
- `pic.add(weight, (G, q) => ...)` your own mark; `pic.pause(weight)` a beat between passes.
- The plain parts: `K.plate`, `K.piece`, `K.oval`, `K.mix`, `K.rng`, `K.fractal`, `K.bounds`, `K.inside`, `K.within(G, shape, out, fn)`.

**Shapes and helpers, on every paint and print kit.** Points are `[x, y]`. `K.smooth(pts, closed, per)` a curve through points, `K.oval(cx, cy, rx, ry, n, a0)` a closed loop of `n` points, `K.line(a, b, bow)`, `K.poly(corners, per)`, `K.turn(pts, cx, cy, degrees)`, `K.displace(pts, amp, freq, oct, seed)` a wobble baked into the points, `K.mix(a, b, t)` two `#rrggbb` colours, `K.rng(seed)` a function giving 0..1, `K.fractal(seed, x, y, fx, fy, oct)` smooth noise 0..1, `K.inside(shape, x, y)`, `K.bounds(pts)` `{x0, y0, x1, y1}`, `K.clamp(v, a, b)`. `pic.add` must be called before the first draw.

**What the kit can't do for you.** It has no people or houses ready: draw them from flats. Design carries it: strong silhouettes and big simple shapes that overlap, with a tall narrow thing against a low wide one. A figure is a few flats and a line, not a detailed drawing.

**Cost.** Measured on a small town of about 35 marks at full size, on a shared PC, headless: 17-19 ms a frame with a graphics card, 16-31 ms without, about 150 ms on its first frame. Finished, it's one sprite. A long dry stroke of many bristles is the heaviest mark. The hand's own texture (paper, weave, dots, grain) is a fixed size in pixels, so a frame drawn smaller than the project shows it coarser than the export: check texture at full size.

Refused as everywhere: timers, clock reads, `Math.random` (`K.rng`), the network. Write the name out as `M.look.midCentury`, or it won't load.
