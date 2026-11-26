# Cut-paper collage: torn and scissor-cut coloured papers on a backing board, not one drawn line, each piece lowered onto the stack with a shadow that pulls in

Playful and warm: folk stories, a children's or family video, a travel memory, a craft channel, a bright explainer. It can run as a whole film, a world behind a speaker, a title or a single card. It's the AI's choice for this video.

`const P = M.look.cutPaper.start(c.w, c.h, {scale})` in your block, on one full-frame canvas: `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%'; const g = cv.getContext('2d');`. The block returns `(t) => {...}`, the frame at `t` seconds. You write the picture; this is only the kit. `scale` (default 1) bakes larger, for a camera that pushes in: use the push's biggest zoom, 2 at most.

**How it stays fast and exact.** A piece is painted once, on first draw, from its seeds; each frame only places it. So make every piece once at the top of the block, never inside `(t) => {}`, and give every one its own id. Everything draws through the canvas's current transform, so `g.translate` and `g.scale` are your camera. Start each frame with `P.begin(g)`, then paint something that covers the frame or `g.clearRect`; end it with `P.begin(g); P.finish(g)`, which lays the sheet's tooth over the frame.

**The medium.** Coloured paper only. A torn piece shows the sheet's white fibrous core along its edge; a scissor piece is crisp. Every piece has its own fibres and uneven dye, and lifts a little off whatever is under it, throwing a soft shadow down and to the right. There are no lines: form comes from laying a darker paper into the shade and a lighter one where the light lands, and fur, grass and water come from the torn edge itself. Draw back to front, one light from the upper left.

**How it moves.** A picture is laid from the bottom of the stack up: big sheets slide in from their edge and go down fast; small pieces are fiddly and slower. Paint never moves; only the paper does.
- `P.lay(t, t0, dur, from)` a pose for a piece being lowered (`from` = [dx, dy] where it starts). Held up, it throws a wide far shadow that pulls in tight as it lands. `.shown` is false before `t0`: skip the draw then. `piece.draw(g, {pose})`.
- `P.sway(t, amp, period, phase)` a number around 0, to give to a piece's `x`, `y` or `r` (a piece turns around its `pivot`). `piece.draw(g, {x, y, r, s, alpha, shadow: false})`.

**The pieces.**
- `P.torn(id, shape, color, {amp, seed, lift, fibre, blotch, pivot, stage, decorate(c, shape)})`, `P.cut(id, shape, color, {seed, lift, fibre, pivot, stage, decorate})`. `amp` = how rough the tear, `lift` = how high it stands (0.3 a scrap, 1.5 a foreground sheet).
- `P.band(id, y, color, {wander, amp, lift, bottom})` a torn band edge to edge, for sky, hills and ground. Three or four make a dusk.
- `P.disc(id, x, y, r, color)`, `P.star(id, x, y, r, color)`, `P.tiers(x, base, w, h, n)` gives a tree's tier shapes: lay each as its own piece, darker at the bottom.
- `P.word(id, TEXT, {x, y, cap, rot, paper, ink, amp})` words on a torn strip, in cut capitals, figures and common signs.
- `P.board(id, color)` the bare backing board, a plate. `P.plate(id, paint(c), box)` any other baked picture, with no shadow. `P.piece(id, {cut, face(c), depth, ...})` anything else.
- Shapes: `P.smooth(pts, closed, per)`, `P.blob(cx, cy, rx, ry, seed, k)`, `P.oval(cx, cy, rx, ry, n)`, `P.rect(w, h, cx, cy)`, `P.tear(shape, amp, seed, grow)`, `P.scissor(shape, seed)`, `P.path`, `P.bounds`, `P.mix(a, b, t)`, `P.rng(seed)`. Colours in `P.c`.

**What the kit can't do for you.** Plain shapes in flat papers read as clip art. A subject needs many pieces at several depths: a shade paper and a light paper on each big form, scraps laid on scraps.

**Behind a person.** Leave out the board and clear the frame, so the footage shows between pieces. Measure the outline first and lay big sheets to the space around it. The person's face is never covered, dimmed or tinted.

Refused as everywhere: timers, clock reads, `Math.random` (`P.rng`), the network. Write the name out as `M.look.cutPaper`, or it won't load.
