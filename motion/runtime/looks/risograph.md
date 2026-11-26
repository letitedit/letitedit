# Risograph: soy ink, one drum per colour, each ink multiplied through its own slightly wrong registration, tone made of halftone dots, white is bare paper

Loud and printed: posters, launches, zines, music, an indie shop, a bold fact. Two or three inks do everything, since every other colour is an overprint. It can run as a whole film, a backdrop behind a speaker or a single card. It's the AI's choice for this video.

`const R = M.look.risograph.start(c.w, c.h, {scale})` in your block, on one full-frame canvas. `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; const g = cv.getContext('2d');` gives you that canvas. You write the scene and the subject; this is only the kit.

**How it works.** A picture is a *work*: a sheet and a list of pulls in order. Make it once at the top of the block, add every pull there, then draw it each frame: `const pic = R.sheet('poster'); R.pull(pic, (G) => {...}, {off: R.REG.yellow}); ...; return (t) => { R.begin(g); pic.draw(g, {p: M.prog(t, .5, 6)}); };`. `p` 0..1 is how far through the press it is: the ink comes in at the nip, a straight front running down the sheet with the drum's shadow just ahead. Any p gives the same pixels in any order, and at 1 it's one sprite a frame. `pic.draw(g, {p, x, y, s, r, alpha})`; `g.translate` and `g.scale` are your camera. `pic.at(n)` says where pull n ends, to land an ink on a word.

**The medium.** Each drum is one flat ink through a stencil: `R.INK` `pink, blue, yellow, teal, red`. Each `R.pull` is one ink only, and it **multiplies** over what's there, so yellow and pink make orange, pink and blue make a dark violet, and the darkest thing is every drum at once. Lightest first is the usual order: yellow, pink, blue. Every drum lands a little off (`R.REG`), which gives slivers of bare colour at edges: that's the look, so leave it in. Volume comes from the **tone function**: dots grow with a value you write for the form (a lit dome, a cylinder, distance to a fold). Each ink screens at its own angle (`R.ANG`). Ink has pinholes and an uneven roll; the hand adds them. Nothing is white except bare paper, so a highlight is a place with no dots.

**What it gives**
- `R.sheet(id, {w, h, paper})` the work, on off-white stock with its tooth over the top.
- `R.pull(pic, (G) => {...}, {off, per})` one pass of one ink. Inside it:
- `R.screen(G, box, ink, tone(x, y), {pitch, ang, clip})` a halftone in `{x0, y0, x1, y1}`. `tone` 0..1, `pitch` the dot spacing (`R.PITCH` 7.4 by default), `clip` a shape.
- `R.solid(G, pts, ink, {raw})` a solid area with the stencil's wobble.
- `G.pen(pts, {w, color, seed})` a litho-crayon line that swells and thins, and `G.fill(pts, color)`.
- For tone functions: `R.across(shape, 'x')` how far across a form a point is, 0..1 (a cylinder lit from one side); `R.nearField(lines)` the distance to a set of lines, cheap at 30,000 dots; `R.wander(pts, amp, wl, seed)` a fold that wanders; `R.twigs(line, every, seed)`; `R.inside(shape, x, y)`, `R.bounds(pts)`.
- `R.cut(pts)`, `R.cutSmooth(pts, per)`, `R.straight(pts)` a stencil's edge on your points. `R.trim(G, inks)` crop marks and swatches, if it should show its trade.
- `pic.add(weight, (G, q) => ...)` your own mark, `pic.pause(weight)` a beat while the drum is changed.
- The plain parts: `R.plate`, `R.piece`, `R.smooth`, `R.oval`, `R.mix`, `R.rng`, `R.fractal`, `R.within(G, shape, out, fn)`.

**Shapes and helpers, on every paint and print kit.** Points are `[x, y]`. `R.smooth(pts, closed, per)` a curve through points, `R.oval(cx, cy, rx, ry, n, a0)` a closed loop of `n` points, `R.line(a, b, bow)`, `R.poly(corners, per)`, `R.turn(pts, cx, cy, degrees)`, `R.displace(pts, amp, freq, oct, seed)` a wobble baked into the points, `R.mix(a, b, t)` two `#rrggbb` colours, `R.rng(seed)` a function giving 0..1, `R.fractal(seed, x, y, fx, fy, oct)` smooth noise 0..1, `R.inside(shape, x, y)`, `R.bounds(pts)` `{x0, y0, x1, y1}`, `R.clamp(v, a, b)`. `pic.add` must be called before the first draw.

**What the kit can't do for you.** The image is your shapes and tone functions; solid shapes alone look like a sticker, and it's the dots that make it print. Bleed a screen past the frame by a little more than the drum's offset, or the sheet's edge shows a sliver. Small type needs to be big or solid: dots break it up.

**Cost.** Measured on three full-frame pulls at full size, on a shared PC, headless: 25 ms a frame with a graphics card and 22-42 ms without, with about 450 ms when a pull first starts (its ink is worked out once). A full-frame screen at the default pitch is about 40,000 dots. Finished, it's one sprite. The hand's own texture (paper, weave, dots, grain) is a fixed size in pixels, so a frame drawn smaller than the project shows it coarser than the export: check texture at full size. In a small live player the dots alias into a coarse pattern; the export is right, so judge dots from a full-size frame.

Refused as everywhere: timers, clock reads, `Math.random` (`R.rng`), the network. Write the name out as `M.look.risograph`, or it won't load.
