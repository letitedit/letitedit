# Ukiyo-e woodblock: a carved black keyblock and flat colour blocks printed by hand onto soft washi, with the wood's grain in the colour and graded wipes in sky and water

Quiet and designed: travel, Japan or history, rain and water, seasons, a landscape, a story told in flat planes. Strong diagonals and big empty flats leave room for words or a speaker. It can run as a whole film, a backdrop or a card. It's the AI's choice for this video.

`const K = M.look.woodcut.start(c.w, c.h, {scale})` in your block, on one full-frame canvas. `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; const g = cv.getContext('2d');` gives you that canvas. You write the scene and the subject; this is only the kit.

**How it works.** A picture is a *work*: a sheet and a list of pulls in order. Make it once at the top of the block, add every pull there, then draw it each frame: `const pic = K.print('wave'); K.pull(pic, {cut: (c) => {...}, color: K.palette.sumi}); ...; return (t) => { K.begin(g); pic.draw(g, {p: M.prog(t, .5, 8)}); };`. `p` 0..1 is how far through the printing it is: each block's colour comes through where the baren has rubbed, in zig-zag rows over its own area. Any p gives the same pixels in any order, and at 1 it's one sprite a frame. `pic.draw(g, {p, x, y, s, r, alpha})`; `g.translate` and `g.scale` are your camera. `pic.at(n)` says where pull n ends.

**The medium.** Warm kozo washi with long soft fibres and a bare margin. The key block goes first: a black line **as the knife leaves it**, two separate cuts either side of a ridge, so its width steps and wanders instead of swelling like a brush, and every end is a flat oblique chisel cut, never round. Then flat colour blocks, one colour each, **multiplied**, with the plank's grain printing as streaks in the flat. Highlights are uncut wood, so bare paper, never a pale ink. Grading is a *bokashi*: full at one edge and gone a hand's width away, with the damp cloth's wavering edge, usually in the top of the sky and the bottom of the water. There's no cast shadow and little modelling: planes, pattern and line.

**What it gives**
- `K.print(id, {w, h, margin})` the work. `K.box(pic)` the picture's box inside the margin.
- `K.pull(pic, {cut(c), color, alpha, grain, seed, reg, box, per, pad})` one block. `cut(c)` paints where this block carries pigment, with `c.fillStyle` already set to `color`. `grain` 0..1 how much the plank shows; `reg` `[x, y]` where it landed; `box` the area the baren rubs, so a small block is a quick pull. **The first pull draws the kento marks**, so make it the key block.
- In `cut`: `K.carved(ctrl, w, seed, {step, wander, tail, smooth})` a polygon for one knife line, `K.gouged(ctrl, seed, closed, amp)` a solid area with a knife edge, `K.fillAll(c, polys, color)`, `K.bokashi(c, x0, x1, yFull, yGone, color, seed, clip)`.
- `K.ink(pic, weight)` a breath between pulls while the next block is inked.
- `K.palette` (`sumi, usuzumi, yellow, grey, bank, wood, water, reed, rain, beroAi, indigo, red, pink, paper`), `K.even(pts, step)`, `K.smoothstep`.
- `pic.add(weight, (G, q) => ...)` your own mark.
- The plain parts: `K.plate`, `K.piece`, `K.smooth`, `K.oval`, `K.mix`, `K.rng`, `K.fractal`, `K.bounds`, `K.inside`.

**Shapes and helpers, on every paint and print kit.** Points are `[x, y]`. `K.smooth(pts, closed, per)` a curve through points, `K.oval(cx, cy, rx, ry, n, a0)` a closed loop of `n` points, `K.line(a, b, bow)`, `K.poly(corners, per)`, `K.turn(pts, cx, cy, degrees)`, `K.displace(pts, amp, freq, oct, seed)` a wobble baked into the points, `K.mix(a, b, t)` two `#rrggbb` colours, `K.rng(seed)` a function giving 0..1, `K.fractal(seed, x, y, fx, fy, oct)` smooth noise 0..1, `K.inside(shape, x, y)`, `K.bounds(pts)` `{x0, y0, x1, y1}`, `K.clamp(v, a, b)`. `pic.add` must be called before the first draw.

**What the kit can't do for you.** The design: the print's power is in a big diagonal, repeated pattern (rain as many thin cuts, waves as rows of knife lines) and a few well-placed flats. A key line round everything with plain colours inside looks like a colouring book, so vary the line's width and let colours stand alone in places. Keep parts of a shape the same between blocks by building them once from the same points. Rain or snow that moves goes on top in `(t) => {}` with `K.fillAll`, or on a work of its own.

**Cost.** Measured on five pulls at full size, on a shared PC, headless: 20-29 ms a frame with a graphics card, 16-27 ms without, about 300 ms on its first frame (the paper is worked out per pixel). Finished, it's one sprite. The hand's own texture (paper, weave, dots, grain) is a fixed size in pixels, so a frame drawn smaller than the project shows it coarser than the export: check texture at full size.

Refused as everywhere: timers, clock reads, `Math.random` (`K.rng`), the network. Write the name out as `M.look.woodcut`, or it won't load.
