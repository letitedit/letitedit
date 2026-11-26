# Dream glaze: thin oil glazes with no visible stroke, every form turned by one low sun, every edge hard, an impossible picture painted as if it were real

Stillness with a strange idea in it: surprise, the unconscious, a metaphor made literal, an art piece, an objects-on-a-plain picture. Its drama is in the idea and the light, never in the paint. It suits a whole film, a world behind a speaker or a single reveal. It's the AI's choice for this video.

`const D = M.look.dreamGlaze.start(c.w, c.h, {scale})` in your block, on one full-frame canvas. `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; const g = cv.getContext('2d');` gives you that canvas. You write the scene and the subject; this is only the kit. The technique holds no subject of its own: invent one.

**How it works.** Unlike the other hands, this one computes **every pixel**: you describe the forms, and a height field lights them. It runs once, on first draw, and then the picture is a sprite. `const pic = D.picture('id', {back, objs, paint}); return (t) => { D.begin(g); pic.draw(g, {p: M.prog(t, .5, 8)}); };`. `p` 0..1: the back is laid in wavering rows, then each form in its shadow tone and worked up until the highlights arrive last. Nothing fades. Any p gives the same pixels in any order. `pic.draw(g, {p, x, y, s, r, alpha})`; a camera that moves it works, a form that moves needs its own picture.

**The medium.** Linear colour, one sun for the whole picture: everything lit and every shadow cast comes from the same `D.sunlight` call. Long shadows, a waxy turn on rounded forms, a wet highlight, hard silhouettes. A sky falling through turquoise to lemon at the horizon and an ochre plain are the classic set, not a rule. One saturated accent, once.

**What it gives**
- `D.picture(id, {w, h, back(x, y, out), objs(), paint(b, mat, x, y, h, nx, ny, nz, a1, a2, e), band, perBack, perForm})`. `back` writes a **linear** colour for that point into `out`: the sky and the ground, per pixel, and any cast shadow you work out. `objs` returns the standing things back to front. `paint` is called per pixel of a form with its surface normal: choose the albedo by `mat` and call `sun.light(albedo, nx, ny, nz, sun.sunAt(b, x, y, h), ao, spec, gloss)`, which leaves the colour in `D.OUT`.
- `const sun = D.sunlight([x, y, z] toward the sun, {sun, sky, bounce})` gives `sun.light`, `sun.sunAt`, `sun.LS`.
- Forms: `D.ball([x, y, r], mat)`, `D.tube(D.curve([[x, y, r], ...]), pad, mat)`, or your own `{box: [x0, y0, x1, y1], at: (x, y, o) => { o[0] = edge distance (+ inside); o[1] = height toward the eye; o[2], o[3] = your surface coordinates; o[4] = mat; }}`, with `D.near(curve, x, y)` and `D.NR` for the nearest point on a curve.
- Noise and colour: `D.fbm(x, y, oct, seed)`, `D.vnoise`, `D.hash2`, `D.G`, `D.sm(a, b, x)`, `D.cl`, `D.lin('#hex')` (linear), `D.hex`, `D.ramp(stops, t, out)`, `D.palette`.
- `pic.add(weight, (G, q) => ...)` your own mark afterwards, say handwriting along a line; `pic.pause(weight)`.
- The plain parts: `D.plate`, `D.piece`, `D.smooth`, `D.oval`, `D.mix`, `D.rng`, `D.bounds`, `D.inside`.

**Shapes and helpers, on every paint and print kit.** Points are `[x, y]`. `D.smooth(pts, closed, per)` a curve through points, `D.oval(cx, cy, rx, ry, n, a0)` a closed loop of `n` points, `D.line(a, b, bow)`, `D.poly(corners, per)`, `D.turn(pts, cx, cy, degrees)`, `D.displace(pts, amp, freq, oct, seed)` a wobble baked into the points, `D.mix(a, b, t)` two `#rrggbb` colours, `D.rng(seed)` a function giving 0..1, `D.fractal(seed, x, y, fx, fy, oct)` smooth noise 0..1, `D.inside(shape, x, y)`, `D.bounds(pts)` `{x0, y0, x1, y1}`, `D.clamp(v, a, b)`. `pic.add` must be called before the first draw.

**What the kit can't do for you.** It has no idea of its own. A ball on a plain is a demo: the picture needs an impossible thing that means something to this video. It's slow to change: an edit means computing the pixels again.

**Cost.** Measured on a small scene (a detailed back, three forms) at full size, on a shared PC, headless: about 400 ms on its first frame, then 24 ms a frame with a graphics card and 37 ms without. A busy `back`, many curve points or a big form cost more on the first frame, and that can hold up the start in a live player; the Export isn't affected. `sunAt` walks 70 steps a pixel, so keep `fbm` octaves low. The hand's own texture (paper, weave, dots, grain) is a fixed size in pixels, so a frame drawn smaller than the project shows it coarser than the export: check texture at full size.

Refused as everywhere: timers, clock reads, `Math.random` (`D.hash2`, `D.rng`), the network. Write the name out as `M.look.dreamGlaze`, or it won't load.
