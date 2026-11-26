# Newsprint halftone: black on a 45-degree dot screen plus one spot colour, ink gaining into grey groundwood paper, a press coming up to colour

A front page: news, history, a protest, a hard fact, a then-and-now, a loud claim. It's the one kit here that can take a **real photo** straight in. It can run as a whole film, a cutaway or a backdrop. It's the AI's choice for this video.

`const N = M.look.halftone.start(c.w, c.h, {scale})` in your block, on one full-frame canvas. `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; const g = cv.getContext('2d');` gives you that canvas. You write the scene and the subject; this is only the kit.

**How it works.** You paint an original as two separations, black and spot, and the press does the rest: on first draw it's screened into dots and inked. `const pic = N.print('front', {paint: (x, w, h) => {...}, lineArt: (x) => {...}}); return (t) => { N.begin(g); pic.draw(g, {p: M.prog(t, .5, 6)}); };`. `p` 0..1 is the press running: the spot comes up to colour, thin and streaked where the rollers starve, then it's nudged into register, then the black comes up the same way. It moves in steps, a sheet at a time. Any p gives the same pixels in any order; at 1 it's one sprite a frame. `pic.draw(g, {p, x, y, s, r, alpha})`; `g.translate` and `g.scale` are your camera. Slide a finished sheet on from the top with `y` for a thrown sheet landing on a pile, with a shadow you draw below it.

**The medium.** Two plates on grey-cream newsprint with short dark fibres. Black at 45 degrees, spot (orange by default) at 15, about 5 px between dots. On this paper the finest highlight dots don't hold and every dot gains, so shadows plug towards solid with pinholes. There's no white: the brightest thing is bare paper, so leave paper for highlights. The spot sits a little off the black. One spot colour, used for what matters.

**What it gives**
- `N.print(id, {w, h, paint(x, w, h), lineArt(x), spot, black, pitch, angK, angS, gainK, gainS, fan, reg, regFrom, margin, res, perSpot, perBlack})`. Paint with `x.fillStyle = N.ks(black, spot)`, each 0..1, on a half-size surface in the picture's own coordinates: gradients, shapes and text all work. **No colours other than `ks`**: red means black density and green means spot density. `margin` leaves bare paper round the picture.
- `lineArt(x)` goes straight on the black plate unscreened, for headlines, rules and small type (`x.fillText`, `x.fillRect`).
- `N.photo(x, image, x0, y0, w, h, {k, s, gamma})` inside `paint`: a real photo, its dark becoming black density, `s` adding spot. **Use a `data:` picture**, since the hand must read its pixels, and it must have finished loading before the first draw.
- `N.ks`, `N.BLACK`, `N.SPOT`, `N.PAPER`, `N.smoothstep`, and `N.screenDots`, `N.inkDots`, `N.toneAt` for your own plate through `pic.add(weight, (G, q) => ...)`; `pic.pause(weight)`.
- The plain parts: `N.plate`, `N.piece`, `N.smooth`, `N.oval`, `N.mix`, `N.rng`, `N.fractal`, `N.bounds`, `N.inside`.

**Shapes and helpers, on every paint and print kit.** Points are `[x, y]`. `N.smooth(pts, closed, per)` a curve through points, `N.oval(cx, cy, rx, ry, n, a0)` a closed loop of `n` points, `N.line(a, b, bow)`, `N.poly(corners, per)`, `N.turn(pts, cx, cy, degrees)`, `N.displace(pts, amp, freq, oct, seed)` a wobble baked into the points, `N.mix(a, b, t)` two `#rrggbb` colours, `N.rng(seed)` a function giving 0..1, `N.fractal(seed, x, y, fx, fy, oct)` smooth noise 0..1, `N.inside(shape, x, y)`, `N.bounds(pts)` `{x0, y0, x1, y1}`, `N.clamp(v, a, b)`. `pic.add` must be called before the first draw.

**What the kit can't do for you.** Painted tones are the picture, so give it a real range from paper to near-solid. Screened type under about 40 px breaks into dots: use `lineArt`. A photo needs contrast to survive the screen. Facts on a front page read as claims, so they must be true.

**Cost.** Measured on one sheet at full size, on a shared PC, headless: about 1 s on its first frame (the paper, and about 150,000 dots), then 19 ms a frame with a graphics card and 6-9 ms without. That first second can hold up the start in a live player; the Export isn't affected. Each step of the press is worked out once, and only the latest is kept. Finished, it's one sprite. The hand's own texture (paper, weave, dots, grain) is a fixed size in pixels, so a frame drawn smaller than the project shows it coarser than the export: check texture at full size. In a small live player the dots alias into a coarse pattern; the export is right, so judge dots from a full-size frame.

Refused as everywhere: timers, clock reads, `Math.random` (`N.rng`), the network. Write the name out as `M.look.halftone`, or it won't load.
