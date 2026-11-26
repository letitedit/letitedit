# Crayon: wax on toothy paper, back-and-forth scribble fills that skip the valleys, a darker crayon on the shade side, a white one burnishing the light, a fat wobbly contour gone over twice

Bright and unfussy: school, family, a charity, a teacher's or a parent's video, a child's own story, an upbeat explainer, a joke that wants to look drawn at a kitchen table. It can run as a whole film, a cutaway or a world behind a speaker. It's the AI's choice for this video.

`const K = M.look.crayon.start(c.w, c.h, {scale})` in your block, on one full-frame canvas: `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%'; const g = cv.getContext('2d');`. The block returns `(t) => {...}`, the frame at `t` seconds. You write the picture; this is only the kit.

**How it stays fast and exact.** A picture is recorded once with `K.picture`, at the top of the block, never inside `(t) => {}`. Finished marks stay on one canvas and only the mark in hand is drawn again, so frame N is the same whatever came before; a backward seek starts over. Once finished it is one sprite, moved through the canvas's current transform. Start each frame with `K.begin(g)` and the sheet or `g.clearRect`; end with `K.begin(g); K.finish(g)`.

**The medium.** Wax skips the valleys of the sheet, so paper shows through every stroke. A fill is a visible scribble whose pressure wanders. Wax on wax mixes: a colour laid over another comes out as both, which is why overlapping things sit on a patch of bare paper.

**The order.** Inside a part, marks go down thin lay-in, scribble fills, shade, burnish, then the fat line. **`k.part()` starts the next thing up the stack: anything that overlaps something else must be in a later part,** and `k.paper(shape)` first if its colours shouldn't mix with what's under it. Everything in one part goes in that order at once, so a scene with no overlaps can stay in one part.

**The marks,** on `k` in `K.picture(id, (k) => {...}, {box, takes})`:
- `k.fill(region, color, {angle, gap, w, alpha, seed, keep, over})` a scribble. Bigger `gap` shows more paper. `keep(x, y)` false leaves paper; `K.around([shape, ...])` is a keep rule that scribbles round those shapes, for a sky coloured around everything. Lay such a sky in its own early part, or it lies over the lines.
- `k.shade(region, color, o)` the second crayon, on the side away from the light. Give the colour the area is; it takes that colour's dark.
- `k.burnish(region, o)` white pressed hard into the highlight.
- `k.line(pts, color, w, {closed, seed, wobble, opacity, lay})` the contour. `lay: false` skips the lay-in for tiny flicks. Straight sides keep their corners.
- `k.paper(region, color)` bare paper. `k.mark('fill' | 'shade' | 'burnish' | 'line', area, paint(c, p))` a mark of your own that takes the wax's tooth.

Colours in `K.c`. Shapes: `K.smooth(pts, closed, per)`, `K.blob(cx, cy, rx, ry, seed, k)`, `K.bounds`, `K.mix`, `K.dark(color)`, `K.inside(shape, x, y)`, `K.rng`. `K.sheetPlate(id, color, box)` the bare sheet, a plate.

**How it moves.** `pic.draw(g, {progress, take, x, y, s, r, pivot, alpha})`. Progress 0..1 walks the marks: seen being drawn is the charm of it. `box` limits a picture to part of the frame, which bakes and draws faster: use one for each thing that moves. `takes: 3` redraws a picture that many ways, and `K.take(t, n, rate)` picks one, so the line boils. For poses, make one picture per pose and hold each a few frames. A big full-frame fill is the slowest mark, and it runs longest at the first draw.

**What the kit can't do for you.** Crayon forgives wobble, not vague shapes. Give things structure: curved stripes that follow a form, a shade on one consistent side, and many small marks that belong to this video.

**Behind a person.** Skip the sheet and clear the frame, and the scribbles stand on the footage. Measure the outline first. The person's face is never covered, dimmed or tinted.

Refused as everywhere: timers, clock reads, `Math.random` (`K.rng`), the network. Write the name out as `M.look.crayon`, or it won't load.
