# Cyanotype blueprint: ruling pen and compass in white ink on Prussian-blue stock

A drawing kit: marks and paper a canvas scene may call, for when that's what this video wants. Any scene can just as well be written from scratch in a look of its own. Can suit machines, engineering, how-it's-made, plans for a build, a mock-technical joke.

`const H = M.look.blueprint.start(c.w, c.h, {scale})`, then `const W = H.work('id')`, every mark added once at the top of the block, `W.draw(g, {p, x, y, s, r, alpha})` each frame, `p` 0..1. Start each frame with `H.begin(g)`, and call `H.begin(g); H.finish(g)` last. `W` is transparent. The same `p` gives the same pixels whatever came before.

**A whole scene.** The canvas is yours to make, and nothing shows unless you draw the paper:
```js
M.block('custom', (stage, p, c) => {
  const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%';
  const g = cv.getContext('2d'), H = M.look.blueprint.start(c.w, c.h), ground = H.paper(), W = H.work('picture');
  // add every mark to W here, once
  return (t) => { H.begin(g); ground.draw(g); W.draw(g, {p: Math.min(1, t / 5)}); H.begin(g); H.finish(g); };
});
```
Shapes and lines are lists of points, `[[x, y], [x, y], ...]`, in frame pixels. `H.oval(cx, cy, rx, ry, n)` gives one, `H.inside(shape, x, y)` tests one.

**Timing.** `p` runs through all the marks in the order you added them, and each takes a share by how much it has to draw, so long strokes and big passes take longer. To land a pass on a word, note where it ends as you add it: `const a = W.length` after the pass, then `W.at(a - 1)` is the `p` at which it's done; map the word's time to that `p`. Don't guess and re-render. `H.rest(W, t)` is a pause in the same units as the marks: `3` is about a short ruled line and `30` a clear beat.

**The medium.** Lines that are ruled and never dead straight, circles that are truly round, chain lines for centres, section lining at 45 degrees that starts and stops inside the part. Every line has a faint halo. No light and no cast shadow: an orthographic drawing has none. Hierarchy: outlines heavy white (1.4 to 1.9), lining and dimensions thin cyan (0.75 to 1), construction thinner and dim. Order: border; centre lines and construction; outlines; section lining; dimensions and notes; the title last. Long ruled strokes are fast, lettering is slow, and nothing fades.

**What it gives**
- `H.paper(id, {box})` the stock, a plate. `H.border(W, {t})` the ruled double border with zone marks.
- `H.rule(W, a, b, w, {color, seed})`, `H.outline(W, pts, w, {closed, seed})` each side a stroke, `H.curve(W, pts, w)` a freehand curve.
- `H.circle(W, x, y, r, w, {a0})`, `H.chain(W, a, b, w)`, `H.chainRing(W, x, y, r, w)`, `H.dash(W, a, b, w, {on, off})`.
- `H.section(W, shape, {angle, gap, w, seed})` section lining; neighbouring parts in opposing directions.
- `H.dim(W, a, b, off, label, {cap, seed})`, `H.callout(W, text, at, to, {align, cap, seed})`, `H.balloon(W, n, at, to, {seed})`, `H.arrow(W, tip, angle, {size})`.
- `H.letter(W, text, x, y, {cap, color, align, w, seed})` inclined gothic capitals, stroke by stroke. `H.textWidth(text, cap)`.
- `H.palette`: ground, white, cyan, dim. `H.rest(W, t)`, `W.at(n)`, geometry `H.oval`, `H.smooth`, `H.poly`, `H.rng`.

**What it can't do for you.** The drawing is yours and its numbers should be true: a real mechanism's proportions, a label the video can stand behind. Each mark has its own halo, so hundreds of marks make a slow first pass. It has no tone, so faces and soft things don't suit it.

Refused as everywhere: timers, clock reads, `Math.random` (`H.rng`), the network. Write the name out as `M.look.blueprint`, or it won't load.
