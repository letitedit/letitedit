# Archival scrapbook: a page from an old field album, with torn cards, tape, a typewriter, cut letters, a red pen and copperplate lines

For documentary, research and "found evidence" videos, where the picture should feel collected rather than designed.

`const S = M.look.scrapbook.start(c.w, c.h, {scale})` in your block, on one full-frame canvas. You write the scene and the subject; this is only the kit. `scale` (default 1) bakes everything larger, for a camera that pushes in: use the push's biggest zoom, 2 at most.

**How it stays fast and exact.** A card, a tape, a page is painted once, on first draw, from its seeds, and each frame only places the picture. So: make them all once at the top of the block, never inside `(t) => {}`. Every id must be unique. Everything draws through the canvas's current transform, so `g.translate` and `g.scale` are your camera. Start each frame with `S.begin(g)`, and call `S.begin(g); S.finish(g)` last, which lays the sheet's tooth and handled edges over the frame in screen space.

**The medium.** Rag paper gone to parchment. Paper never has a drawn outline; it's torn, lifts a little and throws a soft shadow down and to the right, from one lamp at the upper left. Pictures are copperplate: tone comes from lines that swell and lift, not from fills. Words come from three hands: the typewriter, cut letters and the red pen. Colour is rare and earned: teal, dusty pink, mustard, navy, stamp red (`S.palette`).

**What it gives**
- `S.page(id, {box, color, seed, fold})` the parchment plate. `box` can be far larger than the frame, for one continuous camera over one page. `fold: null` leaves out the fold.
- `S.card(id, {x, y, w, h, rot, color, seed, torn, depth, face})` a torn card. `face(c)` paints your content with (0, 0) at its centre. `.draw(g, {pose})`.
- `S.lay(t, t0, dur, from)` a pose: held up with a far shadow, then pressed down. Its `.shown` is false before `t0`: skip the draw then. Its `.alpha` rises over 0.14 s, so `.draw(g, {pose: q, alpha: q.alpha})` fades a piece in rather than popping it.
- `S.tape(id, [x, y], angle, len, seed)` then `.draw(g, {reveal})`, 0..1 laying it from one end. Tape goes on after its card lands.
- `S.strip(id, text, {x, y, cap, rot, color, seed})` a slip with a typed line, then `.draw(g, {pose, n})`, `n` = letters struck (`M.typed(text, t, t0, 22)`). Capitals, figures and common signs only.
- `S.ransom(id, word, {x, y, cap, seed})` (or `cx` in place of `x`, to centre it) a word of cut letters, each from a different page, then `.draw(g, t, t0, {each, dur})` pastes them one by one. `.width` says how long it came out.
- `S.handWrite(g, text, x, y, cap, {color, seed, progress})`, `S.redPen(g, pts, {w, progress})`, `S.ring(g, cx, cy, rx, ry, {progress})` the pen, each drawn every frame; `progress` is the nib travelling.
- `S.stamp(id, text, {x, y, cap, rot, color})` then `.draw(g, {s, alpha})`: it's a plate, so stamp it down with `s` falling from about 1.5 to 1 in 3 frames.
- `S.twine(id, pts)` a plate, and `S.peg(id, x, y)` a clothespin piece, to hang a card.
- `S.engraved(c, shape, {tone(x, y), angle, gap, w, color, seed})` inside a `face` or a plate: burin lines across `shape`, swelling where `tone` is near 1 and lifting to bare paper near 0. Write `tone` from a light at the upper left. Two passes at different angles make a cross-hatch in the darks. `S.tint(c, shape, color, alpha)` is a thin hand wash over it.
- `S.print(c, image, x, y, w, h, {border, tone, toneAlpha})` inside a `face`: a real photo as a print with a white border. The scene loads the image itself, and a card's `face` runs on its first draw, so the image must have finished loading by then.
- The plain parts: `S.plate(id, paint(c), box, pivot)` for your own baked picture, `S.piece(id, {cut, face, depth, border, edge, pivot})` for your own flat, `S.typedLine(c, text, x, y, cap, color, seed, n)`, `S.tear`, `S.scissor`, `S.smooth`, `S.rect`, `S.path`, `S.bounds`, `S.fibres(c, shape, color, seed)`, `S.mix(a, b, t)`, `S.rng(seed)`, `S.oval`, `S.fractal`.

**What the kit can't do for you.** Each card still needs a real picture on it: an engraved object drawn for this video, a chart, a map, a photo. A page of empty cards looks like a template. It reads as a still page until you move it: lay things on the spoken word, keep a slow camera travelling across the page, and let the pen move.

Refused as everywhere: timers, clock reads, `Math.random` (`S.rng`), the network. Write the name out as `M.look.scrapbook`, or it won't load.
