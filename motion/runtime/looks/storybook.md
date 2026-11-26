# Storybook pencil and watercolour: soft graphite and gentle pan washes on warm cold-press paper, with a recurring character drawn in a picture-book illustrator's order

Gentle and story-led: a bedtime tale, a family or memory video, a charity's appeal, a teacher's lesson, a story with one character who keeps coming back. It can run as a whole film, a cutaway or a world behind a speaker. It's the AI's choice for this video.

`const S = M.look.storybook.start(c.w, c.h, {scale})` in your block, on one full-frame canvas: `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%'; const g = cv.getContext('2d');`. The block returns `(t) => {...}`, the frame at `t` seconds. You write the page and the character; this is only the kit.

**How it stays fast and exact.** A page is recorded once with `S.picture`, at the top of the block, never inside `(t) => {}`. Finished marks stay on one canvas and only the mark in hand is drawn again, so frame N is the same whatever came before; a backward seek starts over. Once finished it is one sprite, moved through the canvas's current transform. Start each frame with `S.begin(g)` and the sheet or `g.clearRect`; end with `S.begin(g); S.finish(g)`.

**The medium.** Washes never quite fill their outline, and pigment settles at the edge. A form is its colour shifted toward the light over its own shade, wet in wet. The pencil is soft and tapered, drawn twice: lightly first, then at full weight over the dry paint. The blue-grey construction lines stay in the finished page, as they do in real picture books. Light from the upper left. Paper shows everywhere.

**The order.** Inside a part, marks go down construction, light pencil, washes, final line, flicks. **`k.part()` starts the next thing up the stack: anything that overlaps something else must be in a later part.** Washes are transparent, so a thing over a thing lets the back one through: leave paper for it or paint a pale `k.form` first.

**The marks,** on `k` in `S.picture(id, (k) => {...}, {box, takes})`:
- `k.construct(pts, {closed})` ovals, a gesture line, a cross on the face.
- `k.pen(pts, {closed, w, seed, wobble, taper, opacity, retrace, color})` graphite, appearing in both pencil passes. Straight sides keep their corners.
- `k.wash(pts, color, {alpha, seed, dx, dy, shrink, rim})` a flat wash; `k.form(pts, color, shade, {seed, light, alpha, hi})` a wash with form, `hi` = [x, y, rx, ry, angle] lifting a highlight.
- `k.hatch(x, y, w, {n, len, angle, color, seed, pw, opacity})` pencil hatching: a cast shadow, grass. `k.flick(area, color, {n, seed, alpha})` paint flicked off the brush, the last thing on a page.
- **A character.** `k.limb(from, to, bend, r, color, {seed, shade, creases})` a soft arm or leg, wash and line. `k.hand(wrist, angle, 'open' | 'rest', {k, color, shade, seed})` a shaded hand.

Colours: `S.TINT` and its matching `S.SHADE`. Shapes: `S.oval(cx, cy, rx, ry, n)`, `S.smooth(pts, closed, per)`, `S.line(a, b, bow)`, `S.tube(pts, r0, r1, cap)`, `S.turn(pts, cx, cy, deg)`, `S.mix`, `S.bounds`, `S.rng`. `S.sheetPlate(id, color, box)` the warm sheet, a plate.

**How it moves.** `pic.draw(g, {progress, take, x, y, s, r, pivot, alpha})`. Progress 0..1 walks the marks, and being made is half the film. Then gently: a slow camera over the page, a character in a few held drawings. `box` limits a picture to part of the frame, which bakes and draws faster: use one per character. For a walk or a wave, make one picture per pose and hold each: `S.take(t, n, rate)` says which of n, about 6 drawings a second. `takes: 3` redraws a picture that many ways for a line that breathes.

**What the kit can't do for you.** The kit gives the medium, not a character: its parts are limbs and hands, and head, face, clothes and walk are yours. Keep the character's shapes in one function, so it comes back the same in every scene. A big wash on a full frame takes a moment at first draw.

**Behind a person.** Skip the sheet and clear the frame: thin washes over footage nearly vanish, so use `k.form` at full strength. Measure the outline first. The person's face is never covered, dimmed or tinted.

Refused as everywhere: timers, clock reads, `Math.random` (`S.rng`), the network. Write the name out as `M.look.storybook`, or it won't load.
