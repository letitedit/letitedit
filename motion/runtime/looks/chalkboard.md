# Chalkboard: chalk with its dust on a slate carrying the ghosts of old lessons

A drawing kit: marks and paper a canvas scene may call, for when that's what this video wants. Any scene can just as well be written from scratch in a look of its own. Can suit lessons and explainers, teachers and classrooms, a step-by-step worked on screen.

`const H = M.look.chalkboard.start(c.w, c.h, {scale})`, then `const W = H.work('id')`, every mark added once at the top of the block, `W.draw(g, {p, x, y, s, r, alpha})` each frame, `p` 0..1. Start each frame with `H.begin(g)`, and call `H.begin(g); H.finish(g)` last. `W` is transparent. The same `p` gives the same pixels whatever came before.

**A whole scene.** The canvas is yours to make, and nothing shows unless you draw the board:
```js
M.block('custom', (stage, p, c) => {
  const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%';
  const g = cv.getContext('2d'), H = M.look.chalkboard.start(c.w, c.h), ground = H.board(), W = H.work('picture');
  // add every mark to W here, once
  return (t) => { H.begin(g); ground.draw(g); W.draw(g, {p: Math.min(1, t / 5)}); H.begin(g); H.finish(g); };
});
```
Shapes and lines are lists of points, `[[x, y], [x, y], ...]`, in frame pixels. `H.oval(cx, cy, rx, ry, n)` gives one, `H.inside(shape, x, y)` tests one.

**Timing.** `p` runs through all the marks in the order you added them, and each takes a share by how much it has to draw, so long strokes and big passes take longer. To land a pass on a word, note where it ends as you add it: `const a = W.length` after the pass, then `W.at(a - 1)` is the `p` at which it's done; map the word's time to that `p`. Don't guess and re-render. `H.rest(W, t)` is a pause in the same units as the marks: 10 is about a short stroke, 200 a clear beat.

**The medium.** Every stroke has two parts: a wide faint dust either side, and the line itself broken by the board's tooth. Tone is the side of the chalk dragged back and forth; dark places are just less chalk. A teacher writes a thing, underlines it, and moves on: letters arrive stroke by stroke, drags one by one, nothing fades.

**What it gives**
- `H.board(id, {frame, ghosts: ['OLD WORDS'], box, seed})` the slate, a plate. `frame: false` leaves out the wooden frame and ledge; `H.inner()` says where the slate is inside the frame.
- `H.chalk(W, pts, {w, color, seed, op, wob, closed})` a line with its dust.
- `H.scumble(W, shape, {color, angle, gap, w, alpha, seed, keep(x, y)})` the side of the chalk, drag by drag.
- `H.write(W, text, x, y, {cap, color, seed, align, w, opacity})` capitals, stroke by stroke.
- `H.dots(W, [[x, y, r], ...], {color})` tapped in. `H.smudge(W, shape, {color, alpha, blur})` a finger's smudge.
- `H.palette`: chalk, yellow, blue, pink. `H.rest(W, t)`, `W.at(n)`, tones `H.ball`, `H.across`, geometry `H.smooth`, `H.oval`, `H.poly(corners, n)`, `H.inside`, `H.rng`.

**Corners.** Chalk rounds what it's given, so a sharp shape goes in as `H.poly(corners, 8)`.

**What it can't do for you.** The frame is furniture: it says "classroom" before anything is drawn, and the board alone says little. The board has its own framing, so it fills the frame rather than sitting behind a person without a cut-out of the wall.

Refused as everywhere: timers, clock reads, `Math.random` (`H.rng`), the network. Write the name out as `M.look.chalkboard`, or it won't load.
