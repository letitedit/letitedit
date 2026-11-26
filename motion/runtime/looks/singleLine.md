# Single-line engraving: one unbroken line spiralling out, its width carrying the whole picture

A drawing kit: marks and paper a canvas scene may call, for when that's what this video wants. Any scene can just as well be written from scratch in a look of its own. Can suit one big image: a logo, a planet, a coin, a portrait-like form, a title moment.

`const H = M.look.singleLine.start(c.w, c.h, {scale})`, then `const W = H.work('id')`, `H.spiral(W, tone, {...})` once at the top of the block, `W.draw(g, {p, x, y, s, r, alpha})` each frame, `p` 0..1. Start each frame with `H.begin(g)`, and call `H.begin(g); H.finish(g)` last. The same `p` gives the same pixels whatever came before.

**A whole scene.** The canvas is yours to make, and nothing shows unless you draw the paper:
```js
M.block('custom', (stage, p, c) => {
  const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%';
  const g = cv.getContext('2d'), H = M.look.singleLine.start(c.w, c.h), ground = H.paper(), W = H.work('picture');
  // add every mark to W here, once
  return (t) => { H.begin(g); ground.draw(g); W.draw(g, {p: Math.min(1, t / 5)}); H.begin(g); H.finish(g); };
});
```
Shapes and lines are lists of points, `[[x, y], [x, y], ...]`, in frame pixels. `H.oval(cx, cy, rx, ry, n)` gives one, `H.inside(shape, x, y)` tests one.

**Timing.** `p` runs through all the marks in the order you added them, and each takes a share by how much it has to draw, so long strokes and big passes take longer. To land a pass on a word, note where it ends as you add it: `const a = W.length` after the pass, then `W.at(a - 1)` is the `p` at which it's done; map the word's time to that `p`. Don't guess and re-render. `H.rest(W, t)` is a pause in the same units as the marks: one unit is about a pixel of ink, so size it from `W.at`.

**The medium.** A burin cutting one line from the centre outward, swelling where the picture is dark and thinning to a hair where it's light. Nothing else is on the plate: no outline, no second line. The line races through the lights and slows where it cuts deep, because time here is ink.

**What it gives**
- `H.paper(id, {box, plate, color})` the paper with the copper's bevel pressed in, a plate. `plate: null` leaves out the mark. `H.plateBox(margin)` is the usual box.
- `H.spiral(W, tone(x, y), {cx, cy, pitch, plate, color, pieces})`: `tone` 0 hairline to 1 as wide as the gap between turns; `cx, cy` the centre, which sits at your subject's focus; `pitch` px between turns.
- `H.darkest(a, b, ...)` joins tones. Tones `H.ball`, `H.across`, `H.inShape`, `H.inside(shape, x, y)`, `H.fractal`.

**What it can't do for you.** Small detail: anything finer than a few turns is lost, so one bold shape reads and a busy scene doesn't. The centre shows as a bullseye if a light area sits on it. No lettering: words come from elsewhere. The line runs once from centre to edge, so the picture can only appear from the middle out.

Refused as everywhere: timers, clock reads, `Math.random` (`H.rng`), the network. Write the name out as `M.look.singleLine`, or it won't load.
