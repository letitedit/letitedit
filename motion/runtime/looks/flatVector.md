# Flat vector: modern editorial illustration, crisp filled paths with no lines, atmospheric planes, long shadows and a grain brush on the shade side

For clean explainers, product stories and news graphics, when flat should still feel like a picture and not clip art.

`const F = M.look.flatVector.start(c.w, c.h, {scale})` in your block, on one full-frame canvas. You write the scene and the subject; this is only the kit. `scale` (default 1) bakes everything larger, for a camera that pushes in: use the push's biggest zoom, 2 at most.

**How it stays fast and exact.** A plate is painted once, on first draw, from its seeds, and each frame only places the picture. So: make plates once at the top of the block, never inside `(t) => {}`. Every id must be unique. Grain is slow, so it belongs in plates, and a thing that moves is a plate of its own. Everything draws through the canvas's current transform, so `g.translate` and `g.scale` are your camera. Start each frame with `F.begin(g)`. A plate that moves needs a `box` wider than the frame, or its edge shows.

**The medium.** The pen tool: every shape is a closed path filled with one colour. There are no strokes anywhere; an edge is only where two fills meet. So what lifts it above clip art:
- **Depth from colour, in many planes.** Far things are pale and cool, near things are deep. `F.steps(far, near, n)` gives the run of colours. Four to six planes per place, each moving at its own speed.
- **One low sun, off the frame on one side.** Every slope turned away from it is in shade, every shape has a shade facet (a second, darker shape), and every shadow falls the same way and fades out.
- **Grain on the shade side only,** in broad passes, clipped to the shape.
- **Incidental detail.** Windows, railings, cables, birds, signs, glitter on water, tiny far-off people. Plain rectangles in a row are what makes it read as clip art.

**What it gives**
- `F.plate(id, paint(c), box, pivot)` a baked picture; `.draw(g, {x, y, s, r, pivot, alpha, clip})`. `box` = `{x0, y0, x1, y1}`, default the frame.
- `F.fill(c, shape, paint, {grain: {ang, k, from, color}, alpha})` one path (or a list), one colour. `ang` = the direction the shade lies in, radians; `k` = 0.15-0.5; `from` = where along that direction grain starts, 0..1.
- `F.grain(c, shape, {ang, k, from, color})` only the brush, for a shape already filled.
- `F.longShadow(c, pts, groundY, {len, drop, dir, alpha, color})` the caster's points thrown along the ground, fading. `F.throwShadow` and `F.ramp(a, b, alpha, 'r,g,b')` are the parts of it.
- `F.ridge(topPts, base)` a smooth hill line closed down to `base`. `F.band(y0, y1, amp, phase)` a band across the frame. `F.cloud(x, y, s)` a flat-bottomed cloud. `F.capsule(a, b, r)` a rounded bar. `F.rot(pts, origin, angle, scale)`. `F.sm(pts, closed, per)` smooth anchors.
- `F.dashes(c, {cx, cy, n, spread, s, color, seed, squash})` short rounded dashes in a drift: chop, wind, sparkle.
- `F.penTool(g, poly, anchors, q)` the vector app's blue path and handles over a shape being drawn, drawn every frame, for scenes that are about being made. Optional.
- `F.finish(g, {paper, vignette})` a light paper tooth over the frame: off by default, since vectors have none.
- `F.palette` thirteen swatches in one key: `sky cloud far farShade midLight mid midShade deep deepShade shore shoreShade sand bay bayHigh bayMid bayFar glint foam dash coral mustard navy bone teal`. Change them to suit the video, in one key. `F.mix(a, b, t)`, `F.rng(seed)`, `F.fractal`, `F.oval`, `F.bounds`, `F.clamp`, `F.trace`.

**People.** The kit has none. `M.draw.person` works in the same page; its proportions are a bean head on stick legs, which reads as clip art beside these plates. If a person matters, draw them in this medium: small head, long simple limbs, one flat colour per garment, a shade facet down one side, a long shadow, grain.

**Words.** Fonts as for any canvas scene: a param named `font` or ending in `font` loads a bundled family; `M.draw.typeText` types them. Bake nothing with text in it until first draw, which a plate already does.

**What the kit can't do for you.** The kit gives the finish, not the picture. If the places are a few plain shapes, grain on them is still clip art. Make each place specific to this video's words, and busy in its far planes.

Refused as everywhere: timers, clock reads, `Math.random` (`F.rng`), the network. Write the name out as `M.look.flatVector`, or it won't load.
