# Low-poly: triangle meshes projected by hand through a pinhole camera, each facet one flat colour from one low sun, sorted far to near, the triangulation the only texture

Landscapes, travel, calm science, tech and games, a place to fly through, a planet, a simple product. Real perspective, and a camera that can truly move. It can run as a whole film, a cutaway or a world behind a speaker. It's the AI's choice for this video.

`const L = M.look.lowPoly.start(c.w, c.h, {sun, ambient, sunColour, haze, hazeAt, hazeOver})` in your block, on one full-frame canvas: `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%'; const g = cv.getContext('2d');`. The block returns `(t) => {...}`, the frame at `t` seconds. You write the world; this is only the kit. `sun` = a direction toward the sun, `[x, y, z]`; `haze` the colour distance fades to. There is no 3D engine and no depth buffer.

**How it stays fast and exact.** Build every mesh once at the top of the block, never inside `(t) => {}`; each frame re-projects and re-sorts them. Time per frame grows with the number of triangles. Measured on a landscape with about 60 pines and a moving camera, with a graphics card on a 1080x1080 frame: about 40 ms a frame, and about 75 ms with reflections. That exports well and stutters in the live player, so a live preview may look rougher than the export. A camera that stays still can bake its whole picture: `L.still(id, (x) => L.draw(x, cam, list))`, then `.draw(g)`. Start each frame with `L.begin(g)`, then a sky or `g.clearRect`.

**The medium.** The facet: a hard-edged triangle, one colour. No line, no gradient, no texture. Colour comes from a face's normal against the one sun plus a cool sky, hazed by distance. So facets turned to the sun warm, and the rest go blue-violet. Keep facets about one size on screen. Coordinates: x right, y up, z away from the camera; a unit is about a metre if you want it to be.

**The meshes.** `L.mesh((m) => {...})` returns a mesh; every method adds triangles.
- `m.terrain({z1, z0, cols, near, widen, grow, height(x, z), color(x, y, z, up), seed, floor})` a heightfield on a grid that widens with distance. `L.fractal(seed, x, z, fx, fz, octaves)`, `L.ridged(seed, x, z, f)` and `L.smoothstep(a, b, x)` make a height. `floor` clamps it, and faces wholly below are left out, so a `m.water` shows through.
- `m.water({y, x0, x1, z0, z1, near, far, cols, rows})` a flat jittered plane, coloured near to far.
- `m.pine(x, y, z, h, seed, {leaf, trunk})`, `m.cone(x, y, z, r, h, color, {sides, r2, rot})` a cone or tapered column, `m.ball(x, y, z, r, color, {rough, lat, lon, sy, seed})` a planet, rock or head, `m.box(x0, y0, z0, x1, y1, z1, color)`, `m.loft(rings, color, {closed})` a hull or bottle through rings of points, `m.quad(a, b, c, d, color)`, `m.tri(a, b, c, color)`.

**Drawing.** `L.draw(g, cam, list, {faces, wire, wireColor, reflect, waterY, ripples, glitter, seed})`.
- `cam = {x, y, z, pitch, yaw, f, cx, cy}`. Compute it from `t`: a real move, re-projected each frame. Never scale the bitmap.
- `list` holds meshes, or `{mesh, x, y, z, ry, rx, s}` for one placed or moving.
- `reflect: true` mirrors everything in the water; `ripples: n` breaks it with horizontal cuts; `glitter: {x, color, w}` lays a sun path. Reflections show only once `faces` is 1.
- `L.sky(id, [[0, '#top'], ..., [1, '#low']], {sun: [x, y], glow, reach, cell, seed})` a plate of 2D facets. `L.cloud(c, cx, cy, w, h, {over, under, seed, n})` faceted, drawn inside a plate's paint. `L.hex`, `L.rng`.

**How it moves.** A modeller's order is one way in: `L.viewport(g)` an empty dark grid; `wire` 0..1 lays the wireframe far to near; `faces` 0..1 shades them in that same order. Nothing slides: a flight, a slow orbit, a moving object, a sun that travels. Objects may overlap in a painter's sort, so keep things that cross each other from being very large.

**What the kit can't do for you.** Shape and colour rest on the sun's direction: place it low and to one side, and check your subject isn't all in shade. A face toward the camera with the sun behind it comes out dark.

**Behind a person.** Clear the frame and leave out the sky: mountains stand behind them. Measure the outline first. The person's face is never covered, dimmed or tinted.

Refused as everywhere: timers, clock reads, `Math.random` (`L.rng`), the network. Write the name out as `M.look.lowPoly`, or it won't load.
