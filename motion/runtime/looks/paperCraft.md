# Toy-theatre paper collage: a cardboard stage, painted and printed flats with real gaps between them, moved by hand on twos

For stories behind a speaker, playful explainers, anything that wants a handmade world with depth.

`const P = M.look.paperCraft.start(c.w, c.h, {scale})` in your block, on one full-frame canvas. You write the scene and the subject; this is only the kit. `scale` (default 1) bakes everything larger, for a camera that pushes in: use the push's biggest zoom, 2 at most.

**How it stays fast and exact.** A flat is painted once, on first draw, from its seeds, and each frame only places the picture. So: make every piece once at the top of the block, never inside `(t) => {}`. Every id must be unique. Everything draws through the canvas's current transform, so `g.translate` and `g.scale` are your camera. Start each frame with `P.begin(g)`, and end it with `P.begin(g); P.finish(g)`, which lays the sheet's tooth and handled edges over the frame in screen space.

**The medium.** Three kinds of paper: coloured and printed sheets, cut or torn; gouache cut-outs with a white scissor margin, like a sticker; and card, which has thickness (a darker cut edge down and to the right). No drawn lines. Depth is real: each flat stands a finger's width in front of the one behind it, so it throws a soft shadow whose distance says how far apart they are. Light from the upper left. Draw back to front.

**How it moves.** Stop motion on twos: every pose holds for two frames. A piece travels held up above the stack, lands, jiggles a little and is still. Paint never moves; only the card does. A still theatre is dead, so keep things going: a row rocking in its groove, a cloud swinging on its thread, a sun climbing on its stick, a boat pushed along a wave, the whole stage drifting behind a gentle camera.
- `P.land(t, t0, dur, from, id, fps)` a pose (`from` = [dx, dy] where it starts relative to its place). Its `.shown` is false before `t0`: skip the draw then. `.draw(g, {pose, x, y, r, s, alpha})`.
- `P.rock(t, amp, period, phase, fps)` a number around 0, held on twos: give it to `x`, `y` or `r` (radians, about 0.03 for a cloud). A piece turns around its `pivot`.
- `P.twos(t, fps)` time held on twos, for your own moves. Pass the project's `fps` (`c.fps`) to all of these.

**The stage is what makes this medium read as a toy theatre.** On its first run behind a person, one AI left the stage parts out, and the result looked like stickers on a backdrop; with a thin proscenium, curtains and a plank floor it read as a theatre. One run each, so a lead rather than a rule. The drop's long strokes can look like a video fault on a tall frame: that AI painted its own sky in short, fat dabs instead.

**The stage parts** (`open` = `{x0, y0, x1, y1}`, the opening). Each returns a piece. Pass `stage: open` to a flat and it's hidden outside the opening wherever it moves, as if it slid in from behind the theatre's walls.
- `P.table(id, box)` the kraft table (a plate). `P.proscenium(id, open, {outer, color, pattern, trim, apron, crest(c, x, y)})` the patterned front with gold trim, an arch, a crest and an apron. Draw it last but one: curtains and valance hang inside it.
- `P.curtain(id, -1 | 1, open, {color, width})`, `P.valance(id, open, {color, n})`.
- `P.drop(id, {box, top, low, stage})` a flown sky. `P.sun(id, cx, cy, R, {topY, disc, ray, stage})` returns `{stick, sun}`. `P.cloud(id, cx, cy, w, h, {seed, stage})`.
- `P.row(id, {y, amp, per, color, depth, stage, decorate})` a scalloped row: sea, hills, a hedge. Use three or more with different `per`, colours and prints.

**Your own flats.** These are where the video's subject goes, and most of your code should be here.
- `P.cutout(id, shape, color, {border, dir, len, w, shade, depth, pivot, decorate(c, shape)})` a gouache cut-out. Paint details in `decorate`, with `P.gouache` on smaller shapes.
- `P.sheetPiece(id, shape, color, {depth, stage, decorate})` a sheet, torn (`P.tear(shape, 1.6, seed)`) or cut (`P.scissor`).
- `P.piece(id, {cut, face(c), border, edge, depth, pivot, hole, stage})` anything else: `cut` is one outline or a list. `P.plate(id, paint(c), box, pivot)` a baked picture with no card edge or shadow.
- `P.sign(id, TEXT, {x, y, cap, rot, card, ink, border})` words on a card, in stroked letters (capitals, figures, common signs).
- The marks, all clipped to the shape: `P.gouache(c, shape, color, seed, {dir, len, w, vary, dens})`, `P.shadeSide(c, shape, color, seed, [sx, sy], depth, dir)`, `P.wavePrint(c, shape, col, gap, sw)`, `P.dotPrint(c, shape, col, gap, rad)`, `P.diamondPrint(c, shape, col, gap)`, `P.stonePrint(c, shape, base, seed)`, `P.newsPrint(c, shape, seed)`, `P.woodPrint(c, shape, col, seed)`, `P.fibres(c, shape, color, seed, density, blotch)`, `P.foam(c, shape, seed)`.
- The plain parts: `P.smooth(pts, closed, per)`, `P.oval(cx, cy, rx, ry, n)`, `P.rays(cx, cy, R, n)`, `P.scallop`, `P.cloudShape`, `P.rect(w, h, cx, cy)`, `P.path`, `P.bounds`, `P.mix(a, b, t)`, `P.rng(seed)`, `P.fractal`, `P.palette`.

**What the kit can't do for you.** The stage alone is a template, and every scene with only the theatre will look the same. Cut out things that belong to this video's words, more of them than feels necessary, at several depths, with painted detail on each. A flat with a plain fill looks unfinished: give every sheet a print or painted strokes.

**Behind a person.** Measure the outline first. Lay the opening and the big flats to the space around them; don't put an event behind the head. The person's face is never covered, dimmed or tinted.

Refused as everywhere: timers, clock reads, `Math.random` (`P.rng`), the network. Write the name out as `M.look.paperCraft`, or it won't load.
