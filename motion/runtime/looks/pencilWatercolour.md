# Pencil & watercolour: graphite and pan washes on cold-press, paint that misses its outline

A drawing kit: marks and paper a canvas scene may call, for when that's what this video wants. Any scene can just as well be written from scratch in a look of its own. Can suit gentle nature, recipes, a soft explainer, a travel journal.

`const H = M.look.pencilWatercolour.start(c.w, c.h, {scale})`, then `const W = H.work('id')`, every mark added once at the top of the block, `W.draw(g, {p, x, y, s, r, alpha})` each frame, `p` 0..1. Start each frame with `H.begin(g)`, and call `H.begin(g); H.finish(g)` last. `W` is transparent. The same `p` gives the same pixels whatever came before.

**A whole scene.** The canvas is yours to make, and nothing shows unless you draw the paper:
```js
M.block('custom', (stage, p, c) => {
  const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%';
  const g = cv.getContext('2d'), H = M.look.pencilWatercolour.start(c.w, c.h), ground = H.paper(), W = H.work('picture');
  // add every mark to W here, once
  return (t) => { H.begin(g); ground.draw(g); W.draw(g, {p: Math.min(1, t / 5)}); H.begin(g); H.finish(g); };
});
```
Shapes and lines are lists of points, `[[x, y], [x, y], ...]`, in frame pixels. `H.oval(cx, cy, rx, ry, n)` gives one, `H.inside(shape, x, y)` tests one.

**Timing.** `p` runs through all the marks in the order you added them, and each takes a share by how much it has to draw, so long strokes and big passes take longer. To land a pass on a word, note where it ends as you add it: `const a = W.length` after the pass, then `W.at(a - 1)` is the `p` at which it's done; map the word's time to that `p`. Don't guess and re-render. `H.rest(W, t)` is a pause in the same units as the marks: 10 is about a short stroke, 200 a clear beat.

**The medium.** A pencil lay-in light enough to live under paint; first light washes, one per mass, each spreading from where the brush touched and stopping short of its outline; form toward one light; graphite over the paint, stopping where later paint sits on top.

**What it gives**
- `H.paper(id, {box, color})` the sheet, a plate.
- `H.layIn(W, pts, {closed, seed, w, opacity, wobble})`.
- `H.wash(W, shape, color, {alpha, at: [x, y], seed, shrink, dx, dy, rim, t})` a thin wash; `at` is where the brush touched; `t` its share of the time.
- `H.form(W, shape, color, shade, {at, seed, light: [dx, dy], alpha, hi: [x, y, rx, ry], t})` painted form with a soft edge and a lifted highlight.
- `H.graphite(W, pts, {closed, seed, w, opacity, wobble, hide: [shape, ...]})` a line over the paint; `hide` shapes stop it, as a hand doesn't draw what it can't see.
- `H.write(W, text, x, y, {cap, align, seed})` capitals in pencil.
- `H.palette` has a set of pans; any hex works. `H.rest(W, t)`, `W.at(n)`, tones `H.ball`, `H.across`, geometry `H.smooth`, `H.oval`, `H.poly(corners, n)`, `H.tube`, `H.rng`, `H.fractal`.

**Corners.** The wash and pen round what they're given, so a sharp shape goes in as `H.poly(corners, 8)`.

**What it can't do for you.** Each wash is soft-edged and textured: a big one costs about a frame's budget while it spreads. Keep the sheet showing: an evenly covered frame stops reading as watercolour. Pale by nature, so strong words over it need their own contrast.

Refused as everywhere: timers, clock reads, `Math.random` (`H.rng`), the network. Write the name out as `M.look.pencilWatercolour`, or it won't load.
