# Isometric cutaway: flat vector planes on a true 2:1 grid, three tones per material, crisp edges, built up in a construction order

Software, systems, how a thing works, a place with rooms, a factory, a process, a business explained. It can run as a whole film, a cutaway, a diagram or a world behind a speaker. It's the AI's choice for this video.

`const I = M.look.isometric.start(c.w, c.h)` in your block, on one full-frame canvas: `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%'; const g = cv.getContext('2d');`. The block returns `(t) => {...}`, the frame at `t` seconds. You write the building; this is only the kit.

**The grid.** World x runs to the lower right on screen, y to the lower left, z straight up. Every horizontal edge is a 2:1 line, and a cube reads as a cube. `const grid = I.fit(x, y, z, {margin, cx, cy})` gives `{u, ox, oy}` so a world that size fills the frame, wide or tall.

**How it stays fast and exact.** `I.plan(id, grid, (b) => {...}, {light})` records a cutaway at the top of the block, never inside `(t) => {}`. Items are painted **in the order you write them**, whatever their stage, so write back to front, floor before what stands on it. Stage only says when each is made. Finished, it is one sprite. Start each frame with `I.begin(g)` and a ground or `g.clearRect`.

**The medium.** Tone meets tone: no contour line, no blur, no gradient. Each material has exactly three tones: top lightest, +y face middle, +x face darkest. Curved things obey the same rule, split into flat regions. Texture is sparse: tile joints, brick courses, plank lines, laid as more planes and hairlines. One light; everything that faces it takes one flat tint, stepped in bands.

**Materials.** `I.material('#hex', {top, right})` makes three tones from one colour. `I.MATERIALS` has plaster, cut, tile, wood, darkwood, brick, stone, crust, sack, iron. A face's fill is any `{top, left, right}`.

**The items,** on `b`, each with a stage number first:
- `b.grid(stage, x0, y0, x1, y1, color, z)` the iso grid ruled across the ground.
- `b.massing(stage, until, x0, y0, z0, x1, y1, z1, color)` a translucent construction block, gone by stage `until`.
- `b.box(stage, x0, y0, z0, x1, y1, z1, mat, {unlit})` pen-traced, then filled. Boxes take the plan's light unless `unlit`.
- `b.face(stage, [[x, y, z], ...], color, alpha)` one plane. `b.line(stage, a, b, color, w, alpha)` a hairline. `b.shadow(stage, pts, alpha, color)` a cast shadow, one flat shape thrown away from the light. `b.pool(stage, cx, cy, z, r, color, bands, alpha)` a pool of light in flat bands: write it just after the floor.
- `b.cylinder(stage, cx, cy, z0, z1, r, mat)`, `b.dome(stage, cx, cy, z, r, mat)`.
- `b.panel(stage, 'top' | 'left' | 'right', x, y, z, w, h, paint(c, w, h))` paints flat on a plane: a screen, a poster, a sign. In `paint`, a unit is one world unit and y runs down the plane. (x, y, z) is the plane's top-left corner on screen.
- `b.text(stage, side, x, y, z, TEXT, {cap, color, face})` capitals, figures and common signs laid flat on a plane.
- `b.figure(stage, x, y, z, {height, skin, top, legs, hair, face, reach})` a person of 7.5 heads, three tones per garment, about 2.2 high by default.
- `b.add(stage, (iso, p) => {...})` anything else, on the raw `Iso`.

`light = {x, y, z, color, reach, alpha}` pours the one light in a last stage of its own.

**How it moves.** `plan.draw(g, {progress, x, y, alpha})`. Progress 0..1 is a construction time-lapse: a plane is traced, then filled from the top, and the light comes last. A good order of stages: grid, massing, walls and floors, interiors, props, light and shadow, details. For something moving afterwards, draw over the plan each frame: `const j = I.iso(g, grid); j.make(j.boxFaces(x0, y0, z0, x1, y1, z1, mat), 1, mat.right)`, also `j.face`, `j.line`, `j.p`. The grid doesn't turn; a whole move is `x`, `y` or a slow `g.scale`.

**What the kit can't do for you.** A nearer thing that crosses a farther one must be written after it; nothing sorts for you. Empty boxes read as a diagram: small props, labels and lit panels make it a place.

**Behind a person.** Leave the ground out and clear the frame, and the building stands in the footage. Measure the outline first. The person's face is never covered, dimmed or tinted.

Refused as everywhere: timers, clock reads, `Math.random`, the network. Write the name out as `M.look.isometric`, or it won't load.
