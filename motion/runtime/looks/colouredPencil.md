# Coloured pencil: wax pencils hatched in one diagonal on toothy cream paper, hues layered

A drawing kit: marks and paper a canvas scene may call, for when that's what this video wants. Any scene can just as well be written from scratch in a look of its own. Can suit cosy workshops, how-it-works with warmth, children's and school videos, family stories.

`const H = M.look.colouredPencil.start(c.w, c.h, {scale})`, then `const W = H.work('id')`, every mark added once at the top of the block, `W.draw(g, {p, x, y, s, r, alpha})` each frame, `p` 0..1. Start each frame with `H.begin(g)`, and call `H.begin(g); H.finish(g)` last. `W` is transparent. The same `p` gives the same pixels whatever came before.

**A whole scene.** The canvas is yours to make, and nothing shows unless you draw the paper:
```js
M.block('custom', (stage, p, c) => {
  const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%';
  const g = cv.getContext('2d'), H = M.look.colouredPencil.start(c.w, c.h), ground = H.paper(), W = H.work('picture');
  // add every mark to W here, once
  return (t) => { H.begin(g); ground.draw(g); W.draw(g, {p: Math.min(1, t / 5)}); H.begin(g); H.finish(g); };
});
```
Shapes and lines are lists of points, `[[x, y], [x, y], ...]`, in frame pixels. `H.oval(cx, cy, rx, ry, n)` gives one, `H.inside(shape, x, y)` tests one.

**Timing.** `p` runs through all the marks in the order you added them, and each takes a share by how much it has to draw, so long strokes and big passes take longer. To land a pass on a word, note where it ends as you add it: `const a = W.length` after the pass, then `W.at(a - 1)` is the `p` at which it's done; map the word's time to that `p`. Don't guess and re-render. `H.rest(W, t)` is a pause in the same units as the marks: 10 is about a short stroke, 200 a clear beat.

**The medium.** The lead lands only on the ridges of the sheet, so colour is speckled with cream; pressing harder fills more valleys. Tone comes from pressure and from stacking hues, never a flat fill. An edge is where the hatching stops. Thin broken contours go on last, heavier on the shade side and lost where the light is. Order: faint lay-in; local colour, light to dark; a second hue over the first; darks cross-hatched; contours; light left near-bare.

**What it gives**
- `H.paper(id, {box, color})` the sheet, a plate.
- `H.hatching(W, shape, {col, ang, gap, len, w, a, seed, dens(x, y), jit, strip, over, press})` a patch of flicked strokes; `shape` is points or a region; `dens` 0..1 is pressure and coverage; `press` 0 light, 1 medium, 2 burnished. Direction defaults to `H.ANG`, the sheet's one diagonal.
- `H.cross(W, shape, {col, gap, seed, dens})` darks in the second direction.
- `H.contour(W, pts, {col, w, a, seed, seg, keep(x, y), closed, skip, smooth})` overlapping pieces; `smooth: false` keeps corners; `keep` false loses the edge.
- `H.layIn(W, a, b, {col, seed})` a construction line past both ends. `H.dot(W, x, y, rad)` a twisted dot.
- Regions: `H.region(pts)`, `H.ellipse(cx, cy, rx, ry)`, `H.union(a, b)`, `H.minus(a, b)`. `H.edgeDist(pts)` for colour that thickens toward an edge. `H.palette` has a set of pencils; any hex works.
- `H.rest(W, t)`, `W.at(n)`, tones `H.ball`, `H.across`, `H.inShape`, geometry `H.smooth`, `H.oval`, `H.rng`, `H.fractal`.

**What it can't do for you.** Each patch at `gap` 3 is thousands of strokes; a full frame of several layers can take a second or two to make the first time through. Colour reads soft at phone size: use strong `a` and `press` for what must carry. No lettering: this kit leaves words to the scene.

Refused as everywhere: timers, clock reads, `Math.random` (`H.rng`), the network. Write the name out as `M.look.colouredPencil`, or it won't load.
