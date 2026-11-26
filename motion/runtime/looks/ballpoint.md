# Ballpoint sketch: one blue pen on cream paper, tone only from where the hatching sits

A drawing kit: marks and paper a canvas scene may call, for when that's what this video wants. Any scene can just as well be written from scratch in a look of its own. Can suit essays, explainers and technical notes, a notebook feel, how something works.

`const B = M.look.ballpoint.start(c.w, c.h, {scale})`. You write the scene and the subject; this is only the pen. `scale` (default 1) makes everything sharper for a camera that pushes in, 2 at most.

**How it stays fast and exact.** A Work is one picture being made: `const W = B.work('id')`, add every mark once at the top of the block, then `W.draw(g, {p, x, y, s, r, alpha})` each frame, where `p` 0..1 is how far through its marks it is. The same `p` gives the same pixels whatever came before. Never add marks inside `(t) => {}`. Start each frame with `B.begin(g)`, and call `B.begin(g); B.finish(g)` last. `W` is transparent, so it can sit on `B.paper()`, on another scene, or behind a person.

**A whole scene.** The canvas is yours to make, and nothing shows unless you draw the paper:
```js
M.block('custom', (stage, p, c) => {
  const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%';
  const g = cv.getContext('2d'), B = M.look.ballpoint.start(c.w, c.h), ground = B.paper(), W = B.work('picture');
  // add every mark to W here, once
  return (t) => { B.begin(g); ground.draw(g); W.draw(g, {p: Math.min(1, t / 5)}); B.begin(g); B.finish(g); };
});
```
Shapes and lines are lists of points, `[[x, y], [x, y], ...]`, in frame pixels. `B.oval(cx, cy, rx, ry, n)` gives one, `B.inside(shape, x, y)` tests one.

**Timing.** `p` runs through all the marks in the order you added them, and each takes a share by how much it has to draw, so long strokes and big passes take longer. To land a pass on a word, note where it ends as you add it: `const a = W.length` after the pass, then `W.at(a - 1)` is the `p` at which it's done; map the word's time to that `p`. Don't guess and re-render. `B.rest(W, t)` is a pause in the same units as the marks: 10 is about a short stroke, 200 a clear beat.

**The medium.** A steel ball rolling oil ink: the weight barely changes, it can't be thinned or lifted, nothing can be erased. Only lines. Every edge is a line. Tone is hatching: one direction, a cross layer, a third direction in the deepest darks. Glare is paper never hatched. The pen comes down in this order: construction, contours, detail, tone, solid blacks last; a pen can't take a mark back, so a sketcher commits to the contour first.

**What it gives**
- `B.paper(id, {box, color})` the sheet, a plate; `box` may be larger than the frame.
- `B.construct(W, pts, {seed})` a faint lay-in line.
- `B.stroke(W, pts, {w, op, seed, wob, bead, retrace, closed})` one line; `bead` is the blob a firm stroke leaves where it stops. `B.strokes(W, [pts, ...], o)` several.
- `B.hatch(W, shape, {angle, gap, keep(x, y), op, seed})` one direction of hatching.
- `B.tone(W, shape, tone(x, y), {angle, gap, seed, levels})` up to three layers from a tone you write, 0 lit to 1 dark.
- `B.solid(W, shape)` a solid black, growing as a band and never fading in.
- `B.write(W, text, x, y, {cap, align, seed})` capitals, figures and common signs, stroke by stroke.
- `B.rest(W, t)` a breath with nothing moving. `W.at(n)` says where mark n ends, to land a later pass on a word; `W.length` counts them.
- Tones: `B.ball(cx, cy, r, light)`, `B.across(shape, angle)`, `B.inShape(shape, tone)`. Geometry: `B.smooth`, `B.oval`, `B.poly(corners, n)`, `B.tube`, `B.inside`, `B.rng`, `B.fractal`.

**Corners.** The pen smooths what it's given, so a sharp shape goes in as `B.poly(corners, 8)`.

**What it can't do for you.** The subject is yours. Hatching a whole frame is thousands of strokes: keep large areas at a wide `gap`. It moves by being drawn; after that it needs a camera or another event.

Refused as everywhere: timers, clock reads, `Math.random` (`B.rng`), the network. Write the name out as `M.look.ballpoint`, or it won't load.
