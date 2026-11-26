# Pixel art: cells laid one at a time on a grid, each exactly one of sixteen palette colours, a staircase for an edge and a dither for a tone

Games, retro, jokes, a tech or coding story, an old-computer feeling, a young audience or one that grew up with these. It can run as a whole film, a cutaway, a title or a world behind a speaker. It's the AI's choice for this video.

`const P = M.look.pixelArt.start(c.w, c.h, {cell, palette})` in your block, on one full-frame canvas: `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%'; const g = cv.getContext('2d');`. The block returns `(t) => {...}`, the frame at `t` seconds. You write the picture; this is only the kit. `cell` = screen pixels to a cell (default the longer side / 160). `palette` = `'night'`, `'day'`, `'dusk'`, `'mono'` or your own list of up to 16 colours. `P.G` and `P.H` are the grid's columns and rows: **everything below is in cells, not pixels.**

**How it stays fast and exact.** Every layer is painted once into a recorded list of cells at the top of the block, never inside `(t) => {}`. Each frame only places it, so frame N is the same whatever came before. Start each frame with `P.begin(g)`, then `P.clear(g, colourIndex)` or a full layer. There is no finish: no paper, no grain, no smoothing.

**The medium.** No anti-aliasing, taper, wobble or texture: machine crispness is the point. Colours are palette indexes. A half tint is a 2x2 ordered dither, never an alpha blend, so don't use `globalAlpha`. Keep edges clean: even run lengths along a curve, no orphan cells. A camera moves in whole cells and a zoom is a whole number: anything else breaks the grid.

**The order, for a layer's making.** Blocking in flat mid colours, a cleanup of the silhouette, shading clusters and dither bands, highlights and rim light, light sources last. `d.setPass(n)` starts a pass, and a beat of rest falls between passes.

**The marks,** on `d` in `P.layer(id, (d) => {...}, {size: [cols, rows], budgets, rest})`:
- `d.px(x, y, c)`, `d.line(x0, y0, x1, y1, c)`, `d.box(x, y, w, h, c)`, `d.disc(cx, cy, r, c, ry)`, `d.stroke(pts, c, closed)`.
- `d.fill(poly, c)` a bucket fill. `d.blob(poly, c)` the same with one-cell nubs and notches cleaned off, for a silhouette. `P.limb(pts, r0, r1)` a polygon for a tapering limb, stem or tail.
- `d.dither(poly, c, level)` level 0..4 of c over what's there. `d.bands(y0, y1, [c, ...], x0, x1)` a sky of colour rows with dither where they meet.
- `d.glow(cx, cy, r, [c, ...])` a light as a stamp: a core, a ring and a falloff that thins cell by cell.
- `d.sprite(rows, x, y, {char: c}, flip)` laid by hand from rows of characters: **faces, eyes and ears want this; a formula can't place an ear tip.** `d.rim(c, dx, dy, only)` rim light on cells next to empty space. `d.text(TEXT, x, y, c, k)` a 5x7 alphabet, k cells to a font cell; `P.width(TEXT, k)` measures it.

**How it moves.** `layer.draw(g, {x, y, flip, progress})` places it in whole cells; `progress` 0..1 lays it cel by cel in the order it was painted (`layer.cels` says how many). A cel lasts about a tenth of a second.
- `P.held(t, rate)` time held in cels. `P.pose(t, n, rate)` which of n poses: pose to pose, whole-cell teleports, never tweened. `P.hop(t, a, b, t0, t1, rate)` a position in whole cells.
- A sprite's poses are separate small layers. `P.rng(seed)` for scatter.

**What the kit can't do for you.** At this size a character is a handful of cells: put most of your care in hand-laid sprites, and a limited palette you hold to. Words need room: 5x7 at `k` 1 is about 84 pixels tall at the default cell on a 1080p frame.

**Behind a person.** Don't clear the frame or paint a sky: layers are transparent outside what you paint, and the footage shows. The grid stays crisp over it. Measure the outline first. The person's face is never covered, dimmed or tinted.

Refused as everywhere: timers, clock reads, `Math.random` (`P.rng`), the network. Write the name out as `M.look.pixelArt`, or it won't load.
