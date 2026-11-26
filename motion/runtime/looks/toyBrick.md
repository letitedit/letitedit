# Toy brick: moulded plastic bricks in an orthographic view, real proportions and studs, assembled step by step like an instruction booklet

Playful building: a product or a project put together, a before and after, how something is made, a family or kids' channel, a maker's story, a grown-up's joke. It can run as a whole film, a cutaway or a model beside a speaker. Never name any brand of brick, on screen or in words. It's the AI's choice for this video.

`const T = M.look.toyBrick.start(c.w, c.h)` in your block, on one full-frame canvas: `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%'; const g = cv.getContext('2d');`. The block returns `(t) => {...}`, the frame at `t` seconds. You write the model; this is only the kit.

**How it stays fast and exact.** `T.model(id, (b) => {...}, {fps: c.fps, beat, fit})` builds a model once, at the top of the block, never inside `(t) => {}`. Parts already seated stay on one layer, so frame N is the same whatever came before. Start each frame with `T.begin(g)` and `T.backdrop(g, color)` or `g.clearRect`.

**The medium.** No hand at all: the look is manufactured. Each part has one flat colour and a tone per face (top lighter, lit side as it is, far side darker), a bevel highlight, a dark seam hairline and real studs. Only the ground shadow is soft. Proportions are built in: a stud pitch is 20 units, a brick 3 plates tall.

**The parts,** on `b`, in build order. x and z are in studs (x to the lower right, z to the lower left), y and h in plates.
- `b.base(x0, z0, x1, z1, color)` the baseplate, always first.
- `b.brick(x, z, w, d, {y, h, color, studs})`, `b.plate(x, z, w, d, {y, color})`, `b.tile(x, z, w, d, {y, color})` smooth, `b.round(x, z, {y, h, color})` a 1x1 round, `b.prism([[x, z], ...], {y, h, color, studs})` any convex footprint: a wedge, a bow, a cut corner.
- `b.wall(x, z, len, courses, {y, brick, color})` a wall in a running bond along x.
- `b.letters(TEXT, x, z, {y, color})` capitals built as 1x1 bricks standing along x, 7 plates tall.
- `b.color(c)` sets the colour from here on. `b.step()` starts the next booklet step. Colours in `T.COLOURS`.

**How it moves.** `model.draw(g, {frame, x, y, outline, alpha})`, with `frame` = frames since this model began: `Math.round((t - t0) * c.fps)`.
- Instruction-booklet grammar: each step starts on a beat (`beat`, in seconds), bottom up and back to front. Parts fall straight down, ghosted while they travel, and seat with a small press-fit. The current step wears a yellow outline (`outline: false` takes it off). A short settle, then it holds.
- `model.total` frames and `model.seconds(c.fps)` say how long the build takes. Rigid: no squash, no stretch, no bounce.
- Take apart: give it `frame: model.total - f`.
- `fit = {x0, y0, x1, y1}` the box the model fills. It draws through the canvas's current transform, so `g.scale` and `g.translate` make a camera. To move part of a model, build it as a second model and place it with `x` and `y`.

**What the kit can't do for you.** A model is many parts, and each frame of the build redraws what moves and what stands in front of it, so many small bricks cost more while it's building than once it's built. Real colours and a clear silhouette hold up at phone size. A view of 45 degrees is fixed.

**Behind a person.** Skip the backdrop and clear the frame: the model stands on the footage, with its own soft shadow. Measure the outline first. The person's face is never covered, dimmed or tinted.

Refused as everywhere: timers, clock reads, `Math.random`, the network. Write the name out as `M.look.toyBrick`, or it won't load.
