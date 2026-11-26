# Charcoal, erased and redrawn: vine and compressed sticks, a stump and a kneaded eraser that never lifts it all

A drawing kit: marks and paper a canvas scene may call, for when that's what this video wants. Any scene can just as well be written from scratch in a look of its own. Can suit change over time, memory, before and after, a heavy or reflective subject.

`const H = M.look.charcoal.start(c.w, c.h, {scale})`, then `const W = H.work('id')`, every mark added once at the top of the block, `W.draw(g, {p, x, y, s, r, alpha})` each frame, `p` 0..1. Start each frame with `H.begin(g)`, and call `H.begin(g); H.finish(g)` last. The charcoal lives on `W`, above the paper, so the eraser takes charcoal and leaves the sheet. The same `p` gives the same pixels whatever came before.

**A whole scene.** The canvas is yours to make, and nothing shows unless you draw the paper:
```js
M.block('custom', (stage, p, c) => {
  const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%';
  const g = cv.getContext('2d'), H = M.look.charcoal.start(c.w, c.h), ground = H.paper(), W = H.work('picture');
  // add every mark to W here, once
  return (t) => { H.begin(g); ground.draw(g); W.draw(g, {p: Math.min(1, t / 5)}); H.begin(g); H.finish(g); };
});
```
Shapes and lines are lists of points, `[[x, y], [x, y], ...]`, in frame pixels. `H.oval(cx, cy, rx, ry, n)` gives one, `H.inside(shape, x, y)` tests one.

**Timing.** `p` runs through all the marks in the order you added them, and each takes a share by how much it has to draw, so long strokes and big passes take longer. To land a pass on a word, note where it ends as you add it: `const a = W.length` after the pass, then `W.at(a - 1)` is the `p` at which it's done; map the word's time to that `p`. Don't guess and re-render. `H.rest(W, t)` is a pause in the same units as the marks: `0.5` is about a short stroke and `5` a clear beat.

**The medium.** Vine skates over the tooth, soft and grey; compressed is black, crisp and barely erases. Tone is rubbed and lifted, never hatched. **The eraser is a drawing tool, and it's this medium's own move: a change is rubbed out, partly, and redrawn on its own residue, so the sheet keeps its history.** Value only: one warm black on cream. Order: tone the sheet, lift the light, lay in with vine, build the structure, compressed accents, lift highlights; then erase and redraw.

**What it gives**
- `H.paper(id, {box, color})` the rag sheet, a plate.
- `H.vine(W, pts, {w0, w1, alpha, seed, rough, ends})`, `H.compressed(W, pts, o)`, `H.sticks(W, [pts, ...], {hard, ...})`. Lines aren't smoothed: `H.smooth(pts, false, 8)` first for a curve.
- `H.side(W, shape, {angle, gap, w, alpha, seed, keep(x, y), hard, per})` broad drags with the side of the stick.
- `H.stump(W, shape, {gap, amp, w, alpha, blur, seed})` a soft rub, for atmosphere with no edge.
- `H.erase(W, shape, {gap, amp, w, alpha, blur, seed})` the eraser across a shape; `alpha` toward 0.9 is a firm lift.
- `H.lift(W, x, y, r, {glow, alpha, seed})` a glow and a pressed disc, for a sun or a lamp.
- `H.dabs(W, [[x, y, rx, ry, rot], ...], {alpha, seed, hard})` bitten dabs, `H.write(W, text, x, y, {cap, align, seed})` capitals.
- `H.rest(W, t)` a breath between states, `W.at(n)`, tones `H.ball`, `H.across`, `H.noise(seed, x, y, f)`, geometry `H.oval`, `H.poly`, `H.inside`, `H.rng`.

**Strengths.** The default alphas are low on purpose: side about 0.14, stump about 0.06, so a tone builds over several passes. A rub keeps to the shape it's given, so a rectangle leaves a box with hard edges: rub an oval or a loose shape, or keep alpha very low. "Partly" erased means `alpha`: about 0.4 leaves a clear ghost, 0.9 nearly clears it; `gap` only sets how tightly the rub covers the shape.

**What it can't do for you.** Soft rubs over big shapes are the slow marks while they run. An erase over bare paper does nothing: it needs charcoal under it.

Refused as everywhere: timers, clock reads, `Math.random` (`H.rng`), the network. Write the name out as `M.look.charcoal`, or it won't load.
