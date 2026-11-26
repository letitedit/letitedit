# Marker comic: alcohol-marker cel fills laid in chisel passes, a hard shadow edge, and one heavy contour that thickens away from the light

Loud and bright: Shorts, reactions, gags, sport, a hero moment, a product with attitude, a young audience or an old comics fan. It can run as a whole film, a cutaway, a panel or a world behind a speaker. It's the AI's choice for this video.

`const C = M.look.markerComic.start(c.w, c.h, {scale})` in your block, on one full-frame canvas: `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%'; const g = cv.getContext('2d');`. The block returns `(t) => {...}`, the frame at `t` seconds. You write the panel; this is only the kit.

**How it stays fast and exact.** A panel is recorded once with `C.picture`, at the top of the block, never inside `(t) => {}`. Finished marks stay on one canvas and only the mark in hand is drawn again, so frame N is the same whatever came before; a backward seek starts over. Once finished it is one sprite, moved through the canvas's current transform. A picture is transparent, so start each frame with `C.begin(g)` and a ground or `g.clearRect`; end with `C.begin(g); C.finish(g)`.

**The medium.** Flat opaque colour, one hard shadow tone per colour, gel-pen whites, and a brush-pen contour with real thick and thin. Light from the upper left: the line is heavier on the side turned away from it. There are no gradients.

**The order.** Inside a part, marks go down non-photo-blue pencil, then flats, then hard shadows, then details, then the contour, last. **`k.part()` starts the next thing up the stack: anything that overlaps something else must be in a later part,** or a far thing's contour lands on a near thing's fill.

**The marks,** on `k` in `C.picture(id, (k) => {...}, {box, takes})`:
- `k.pencil(pts, {closed})` the lay-in, gone under the marker.
- `k.flat(shape, color, {width, angle, reach, seed})` chisel passes, back and forth, each starting past the edge. `reach` caps a pass: a wide area fills in blocks with a ragged leading edge, never a straight wipe.
- `k.shadow(shape, color, {k, light})` a hard shadow on the shape: its edge is the shape pushed toward the light by `k`. `k.shape(pts, color, alpha, 'shade' | 'detail')` a tone you draw yourself: spots, a floor shadow.
- `k.detail(pts, {w, shadow})` lighter ink: scales, folds, a smile. `k.gel(dots, {r, color})` gel-pen whites.
- `k.line(pts, {closed, w, shadow, light, taper, side})` the contour, growing along its centreline.
- `k.cel(shape, color, {shadow, k, w, width, angle})` flat, shadow and contour together. `shadow: null` for none.
- `k.words(TEXT, x, y, cap, {color})` hand capitals, figures and common signs. `k.balloon(TEXT, x, y, cap, tail)` a speech balloon, in a new part. `k.burst(x, y, R, color, {n, inner, shadow})` an action star. `k.speed(x, y, R0, R1, {n, w, color})` speed lines around a clear middle.

Colours in `C.c` (each main colour has a `...Shade`). Shapes: `C.smooth`, `C.blob(cx, cy, rx, ry, seed, k)`, `C.mix`, `C.bounds`, `C.rng`. **A creature on a spine:** `C.body(ctrl, C.profile([[t, halfWidth], ...]))` gives `.outline`, `.spine` and `.at(t, s)`, where `t` runs nose to tail and `s` edge to edge. Place markings and fins in `(t, s)` and they bend with the body; rebuild it with a moved spine for a swim.

**How it moves.** `pic.draw(g, {progress, take, x, y, s, r, pivot, alpha})`. Progress 0..1 walks the marks. `box` limits a picture to part of the frame, which bakes and draws faster: use one for each thing that moves. Poses are separate pictures, held on twos: `C.take(t, n, rate)` says which of n. `takes: 3` redraws a picture that many ways for a line that boils.

**What the kit can't do for you.** The medium rests on the drawing under it. A plain oval with a heavy line looks like a sticker: draw real anatomy and a strong silhouette, one dramatic curve for the whole figure.

**Behind a person.** Leave the ground out and clear the frame. Measure the outline first. The person's face is never covered, dimmed or tinted.

Refused as everywhere: timers, clock reads, `Math.random` (`C.rng`), the network. Write the name out as `M.look.markerComic`, or it won't load.
