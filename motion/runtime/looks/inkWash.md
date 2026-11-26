# Ink & line-wash: wet washes that settle and backrun, then a flexible nib over them

A drawing kit: marks and paper a canvas scene may call, for when that's what this video wants. Any scene can just as well be written from scratch in a look of its own. Can suit field notes, nature journals, a travel sketchbook, a loose confident feel.

`const H = M.look.inkWash.start(c.w, c.h, {scale})`, then `const W = H.work('id')`, every mark added once at the top of the block, `W.draw(g, {p, x, y, s, r, alpha})` each frame, `p` 0..1. Start each frame with `H.begin(g)`, and call `H.begin(g); H.finish(g)` last. `W` is transparent. The same `p` gives the same pixels whatever came before.

**A whole scene.** The canvas is yours to make, and nothing shows unless you draw the paper:
```js
M.block('custom', (stage, p, c) => {
  const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%';
  const g = cv.getContext('2d'), H = M.look.inkWash.start(c.w, c.h), ground = H.paper(), W = H.work('picture');
  // add every mark to W here, once
  return (t) => { H.begin(g); ground.draw(g); W.draw(g, {p: Math.min(1, t / 5)}); H.begin(g); H.finish(g); };
});
```
Shapes and lines are lists of points, `[[x, y], [x, y], ...]`, in frame pixels. `H.oval(cx, cy, rx, ry, n)` gives one, `H.inside(shape, x, y)` tests one.

**Timing.** `p` runs through all the marks in the order you added them, and each takes a share by how much it has to draw, so long strokes and big passes take longer. To land a pass on a word, note where it ends as you add it: `const a = W.length` after the pass, then `W.at(a - 1)` is the `p` at which it's done; map the word's time to that `p`. Don't guess and re-render. `H.rest(W, t)` is a pause in the same units as the marks: 10 is about a short stroke, 200 a clear beat.

**The medium.** Every wash goes down first, then all the pen work, then the spatter. A wash is a bead of wet paint pulled down the shape with a darker line on its wavering front; the pigment then slides down and pools along the bottom edge; a backrun opens a pale cauliflower with a crinkled rim where a wetter drop touched. The nib is thick on the press, hair-thin on the lift. Washes and line don't have to agree: that looseness is the style.

**What it gives**
- `H.paper(id, {box, color})` the sheet, a plate.
- `H.ground(W, [{x, y, rx, ry, color, alpha, rot}, ...], {seed, t})` a loose background wash laid top to bottom as one bead.
- `H.wash(W, shape, color, {flood, alpha, seed, pool, bloom: [x, y], bloomR, t})`; `flood` 1.07 goes a little past the shape, 1 keeps to it; `bloom` is a backrun.
- `H.lift(W, shape)` a highlight lifted toward the paper. `H.dab(W, shape, color)` a dab of solid colour.
- `H.nib(W, pts, w, {seed, op, wob, closed})` one loose stroke.
- `H.spatter(W, x, y, {n, spread, seed, size})` dots landing one after another.
- `H.write(W, text, x, y, {cap, align, seed})` capitals with the nib.
- `H.palette`, `H.rest(W, t)`, `W.at(n)`, tones `H.ball`, `H.across`, geometry `H.blob`, `H.smooth`, `H.oval`, `H.poly(corners, n)`, `H.tube`, `H.rng`, `H.fractal`.

**Corners.** The nib rounds what it's given, so a sharp shape goes in as `H.poly(corners, 8)`.

**What it can't do for you.** The bead moves top to bottom, so it never starts from a side. Soft large washes are the costly marks: many at once slow the first pass.

Refused as everywhere: timers, clock reads, `Math.random` (`H.rng`), the network. Write the name out as `M.look.inkWash`, or it won't load.
