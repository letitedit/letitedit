# Scratchboard: every mark is ink scraped off a black board, white on black

A drawing kit: marks and paper a canvas scene may call, for when that's what this video wants. Any scene can just as well be written from scratch in a look of its own. Can suit animals, night scenes, thrillers, folk and old-book moods.

`const H = M.look.scratchboard.start(c.w, c.h, {scale})`, then `const W = H.work('id')`, every mark added once at the top of the block, `W.draw(g, {p, x, y, s, r, alpha})` each frame, `p` 0..1. Start each frame with `H.begin(g)`, and call `H.begin(g); H.finish(g)` last. `W` is transparent, so its cuts can sit on any dark ground. The same `p` gives the same pixels whatever came before.

**A whole scene.** The canvas is yours to make, and nothing shows unless you draw the board:
```js
M.block('custom', (stage, p, c) => {
  const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%';
  const g = cv.getContext('2d'), H = M.look.scratchboard.start(c.w, c.h), ground = H.board(), W = H.work('picture');
  // add every mark to W here, once
  return (t) => { H.begin(g); ground.draw(g); W.draw(g, {p: Math.min(1, t / 5)}); H.begin(g); H.finish(g); };
});
```
Shapes and lines are lists of points, `[[x, y], [x, y], ...]`, in frame pixels. `H.oval(cx, cy, rx, ry, n)` gives one, `H.inside(shape, x, y)` tests one.

**Timing.** `p` runs through all the marks in the order you added them, and each takes a share by how much it has to draw, so long strokes and big passes take longer. To land a pass on a word, note where it ends as you add it: `const a = W.length` after the pass, then `W.at(a - 1)` is the `p` at which it's done; map the word's time to that `p`. Don't guess and re-render. `H.rest(W, t)` is a pause in the same units as the marks: one unit is about one flick, so `200` is a clear beat.

**The medium.** White clay under black ink. Nothing is added: the picture is found by removing the dark. A cut is widest where the blade bites and tapers as it lifts, and the clay chips a hair at its edges. Grey is only how close together the white cuts are. Lit edges are rows of short flicks; shadow-side edges are lost into the board. Order: contour highlights, a sparse coat to set the lie, mids and a crossing set, the lights until they close up, details, catchlights last.

**What it gives**
- `H.board(id, {box, color})` the inked board, a plate.
- `H.fur(W, shape | null, {tone(x, y), flow, len, seed, cross, box})` a coat of flicks: `tone` 0 uncut to 1 cut until it closes; `flow` an angle in radians or a function of (x, y), the way the hair lies; `len` hair length, a number or function.
- `H.knife(W, pts, {w, alpha, closed, tail})` one long line, watched being cut. `H.cuts(W, shape, {tone, angle, gap, w, seed})` parallel cuts for hairless surfaces.
- `H.rim(W, outline, {light, flow, len, seed, minFace})` short bright flicks just inside an edge facing the light.
- `H.scrape(W, shape)` a light scraped flat. `H.write(W, text, x, y, {cap, align, seed})` capitals.
- `H.rest(W, t)`, `W.at(n)`, tones `H.ball`, `H.across`, `H.inShape`, geometry `H.smooth`, `H.oval`, `H.poly(corners, n)`, `H.inside`, `H.rng`, `H.fractal`.

**Corners.** The knife rounds what it's given, so a sharp shape goes in as `H.poly(corners, 8)`.

**What it can't do for you.** A coat over a large area is tens of thousands of cuts, made once at the top of the block. Nothing fades; nothing is ever re-inked. A cut can't be taken back in this medium, so any "undo" is a cut to a new board.

Refused as everywhere: timers, clock reads, `Math.random` (`H.rng`), the network. Write the name out as `M.look.scratchboard`, or it won't load.
