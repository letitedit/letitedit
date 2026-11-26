# Sumi-e: one loaded brush of black ink on absorbent paper, a few strokes that go from wet to dry-brush, mostly empty sheet, and a cinnabar seal

Calm and economical: reflection, travel, nature, one idea, something said with very little. It leaves a lot of quiet space, so it works behind words or a speaker as well as on its own. It's the AI's choice for this video.

`const S = M.look.sumiE.start(c.w, c.h, {scale})` in your block, on one full-frame canvas. `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; const g = cv.getContext('2d');` gives you that canvas. You write the scene and the subject; this is only the kit.

**How it works.** A picture is a *work*: a surface, a ground and a list of marks in order. Make it once at the top of the block, add every mark there, then draw it each frame: `const pic = S.sheet('bamboo'); ...; return (t) => { S.begin(g); pic.draw(g, {p: M.prog(t, .5, 8)}); };`. `p` 0..1 is how far through it is; a stroke grows along its path at a hand's pace. Any p gives the same pixels in any order, and at 1 it's one sprite a frame. `pic.draw(g, {p, x, y, s, r, alpha})`; `g.translate` and `g.scale` are your camera. `pic.at(n)` says where stroke n ends, to land one on a word. With `S.sheet('crane', {paper: null})` a part stays on its own layer and can move.

**The medium.** One stick of ink at five dilutions: `S.JIAO` scorched, `S.NONG` thick, `S.ZHONG` heavy, `S.DAN` light, `S.QING` clear. The paper drinks ink at once, so nothing can be corrected: each form is few strokes, in one go. A brush has real hairs: each carries its own ink, spends it with travel, and skips the paper once it runs low, so a stroke turns from wet to dry brush along its length, with streaks of bare paper running with it. Where the brush slows (touch-down, a pause at a node, the lift) ink bleeds into the fibres in a soft halo with fine feathers. That halo is what says absorbent paper. Light comes from leaving paper, not from shadow. **The empty sheet is most of the picture.** The seal goes last and small, off to one side.

**What it gives**
- `S.sheet(id, {w, h, paper})` the work, on warm unbleached paper with long fibres.
- `S.stroke(pic, {ctrl, w, press, ink, load, dry, edge, split, bleed, wet, streak, slow, hairs, seed}, {per, clip})` one stroke. `ctrl` its centreline; `w` its full-press width; `press` `[[t, 0..1.1], ...]` the pressure along it; `ink` the dilution; `load` the ink at touch-down; `dry` spent per 100 px; `edge` >0 a side-laid brush, <0 the tip carries it; `split` how far dry hairs splay; `bleed` the feathering; `wet` 0 a dry sheet, 1 a damp one whose edge goes soft; `streak` a half-loaded brush that breaks early; `slow` `[[t, strength], ...]` where it pauses and bleeds. It's timed by its length unless `per` is given.
- `S.wash(pic, ctrl, w, {ink, wet, seed, per})` a wide pale wash into a damp sheet.
- `S.seal(pic, x, y, size)` the seal, with its characters cut in so they print as paper. The glyphs are an invented mark, not writing.
- `S.tone(v)`, `S.brush(G, b, travel, soak)` for your own mark through `pic.add(weight, (G, q) => ...)`; `pic.pause(weight)` a breath between passes.
- The plain parts: `S.plate`, `S.piece`, `S.smooth`, `S.oval`, `S.mix`, `S.rng`, `S.fractal`, `S.bounds`, `S.inside`, `S.within(G, shape, out, fn)`.

**Shapes and helpers, on every paint and print kit.** Points are `[x, y]`. `S.smooth(pts, closed, per)` a curve through points, `S.oval(cx, cy, rx, ry, n, a0)` a closed loop of `n` points, `S.line(a, b, bow)`, `S.poly(corners, per)`, `S.turn(pts, cx, cy, degrees)`, `S.displace(pts, amp, freq, oct, seed)` a wobble baked into the points, `S.mix(a, b, t)` two `#rrggbb` colours, `S.rng(seed)` a function giving 0..1, `S.fractal(seed, x, y, fx, fy, oct)` smooth noise 0..1, `S.inside(shape, x, y)`, `S.bounds(pts)` `{x0, y0, x1, y1}`, `S.clamp(v, a, b)`. `pic.add` must be called before the first draw.

**What the kit can't do for you.** The strokes are the drawing: a bamboo node is two strokes with a gap, a leaf one stroke from point to belly to point, a bird a few pressed marks. Place them, weigh them and leave things out. Filling the frame goes against the medium. Lettering is drawn strokes or a scene's own text, not this brush.

**Cost.** Measured on about 15 strokes at full size, on a shared PC, headless: 22-35 ms a frame with a graphics card and 30-51 ms without, about 200 ms at its peak, because each stroke is drawn hair by hair every frame until it's laid. So a live player may drop frames while a stroke travels, more on a tall frame. Finished, it's one sprite. The hand's own texture (paper, weave, dots, grain) is a fixed size in pixels, so a frame drawn smaller than the project shows it coarser than the export: check texture at full size.

Refused as everywhere: timers, clock reads, `Math.random` (`S.rng`), the network. Write the name out as `M.look.sumiE`, or it won't load.
