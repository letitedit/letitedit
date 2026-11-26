# Pen-and-ink stipple: thousands of dots from one pen, tone only from how many

A drawing kit: marks and paper a canvas scene may call, for when that's what this video wants. Any scene can just as well be written from scratch in a look of its own. Can suit science, anatomy, natural history, serious detail, an old-textbook feel.

`const H = M.look.stipple.start(c.w, c.h, {scale})`, then `const W = H.work('id')`, marks added once at the top of the block, `W.draw(g, {p, x, y, s, r, alpha})` each frame, `p` 0..1. Start each frame with `H.begin(g)`, and call `H.begin(g); H.finish(g)` last. `W` is transparent. The same `p` gives the same pixels whatever came before.

**A whole scene.** The canvas is yours to make, and nothing shows unless you draw the paper:
```js
M.block('custom', (stage, p, c) => {
  const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%';
  const g = cv.getContext('2d'), H = M.look.stipple.start(c.w, c.h), ground = H.paper(), W = H.work('picture');
  // add every mark to W here, once
  return (t) => { H.begin(g); ground.draw(g); W.draw(g, {p: Math.min(1, t / 5)}); H.begin(g); H.finish(g); };
});
```
Shapes and lines are lists of points, `[[x, y], [x, y], ...]`, in frame pixels. `H.oval(cx, cy, rx, ry, n)` gives one, `H.inside(shape, x, y)` tests one.

**Timing.** `p` runs through all the marks in the order you added them, and each takes a share by how much it has to draw, so long strokes and big passes take longer. To land a pass on a word, note where it ends as you add it: `const a = W.length` after the pass, then `W.at(a - 1)` is the `p` at which it's done; map the word's time to that `p`. Don't guess and re-render. `H.rest(W, t)` is a pause in the same units as the marks: one unit is one dot, so `2000` is a clear beat.

**The medium.** One technical pen touched straight down onto smooth bristol. No line, no hatch, no wash. A dot of one size, slightly oval, now and then with a hair of tail, now and then from a nib running dry. There are no contours: an edge is where the density changes, and in full light it's simply lost. Dark masses go in first, then mid tones, then a few sparse passes over the lights, patch by patch.

**What it gives**
- `H.paper(id, {box, color})` the sheet, a plate.
- `H.dots(W, tone(x, y), {box, seed, size, color, chunk})` the dots: you write a tone, 0 bare paper to 1 nearly solid, and it returns `{count}`. Write the tone as a plain function over your subject: `H.inside(shape, x, y)`, `H.ball(cx, cy, r, light)`, `H.across(shape, angle)`, `H.inShape(shape, tone)`, `H.fractal` for texture.
- `H.write(W, text, x, y, {cap, align, seed})` capitals in the same pen.
- `H.rest(W, t)`, `W.at(n)`. Geometry `H.oval`, `H.poly`, `H.smooth`, `H.rng`.

**What it can't do for you.** Make the field once at the top of the block: a full 1080 frame is tens of thousands of dots and the tone runs for each of them. Marks arrive; nothing moves; a dot never fades. A very light tone (below about 0.02) gets none. The picture is all in your tone function: a flat tone gives a flat grey.

Refused as everywhere: timers, clock reads, `Math.random` (`H.rng`), the network. Write the name out as `M.look.stipple`, or it won't load.
