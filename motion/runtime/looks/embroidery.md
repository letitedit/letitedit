# Hand embroidery: stranded cotton floss stitched through plain-weave linen in a beech hoop, every mark a length of twisted thread, made stitch by stitch with the needle in view

Warm and made by hand: craft, home, a family story, a quote, a logo, a gift, a calm loop or an opening title. It can run as a whole film, a card or a world behind a speaker. It's the AI's choice for this video.

`const E = M.look.embroidery.start(c.w, c.h, {scale})` in your block, on one full-frame canvas: `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%'; const g = cv.getContext('2d');`. The block returns `(t) => {...}`, the frame at `t` seconds. You write the design; this is only the kit. Everything is in frame coordinates; a stitch's `w` is the thread's width.

**How it stays fast and exact.** Build every run of stitches once at the top of the block with `E.work`, never inside `(t) => {}`. Finished stitches are kept on one canvas, and a frame redraws only the last few, so frame N is the same whatever came before; a backward seek starts over. The cloth is computed per pixel once: on a 1080p frame its first draw takes a moment. Start each frame with `E.begin(g)` and draw the cloth or clear the frame; end with `E.begin(g); E.finish(g)`.

**The medium.** Nothing is a flat piece. Every mark is a line with a direction, pinched where it dives into the two holes, with a lit side, a shade side, slanted grooves where the strands twist, a glint on each twist and a hair of shadow on the cloth. Sheen depends on the stitch's angle to the light (upper left), so stitch direction reads as form: turn the stitches with the shape. Outlines are thread too.

**The stitches.** Each generator returns a list; spread several into one `E.work`, in the order they are made.
- `E.stem(path, len, w, color, seed)` overlapping and slanted, like a rope: stems. Two rows for a main stem.
- `E.split(path, len, w, color, closed)` each stitch up through the last: edges, fine lines.
- `E.running(path, dash, gap, w, color)` a dashed flight line.
- `E.satin(axis, half(t), gap, w, color(t, side), {skew, split})` laid side by side across a form. Long spans split at the axis.
- `E.fishbone(mid, half(t), gap, w, color(side, t))` a leaf, from edge to midrib, its halves catching the light differently.
- `E.longShort(edge, target(p), rows, gap, w, ramp, seed)` rows from an edge toward a target, shading from one thread colour to another.
- `E.knots(cx, cy, rx, ry, r, color(u, v), seed)` a packed fill of French knots. `E.knot(p, r, color)` one. `E.straight(a, b, w, color)` one stitch.
- `E.words(TEXT, x, y, cap, color, {w, len, kind})` capitals, figures and common signs in split or stem stitch.

Thread colours in `E.c`. `E.smooth(pts, closed, per)` makes a path smooth; `E.mix`, `E.rng`, `E.bounds`.

**How it moves.** The film is the making: `work = E.work(id, () => [...])`, then `work.draw(g, {progress, needle, x, y, alpha})`. Progress 0..1 makes the stitches in order, each growing from the hole it came up through, with the needle at its head (`needle: false` hides it). A sensible order is stems and edges, then fills, then knots, then the finest things. `work.count` says how many; `work.head(p)` where the needle is. After that, a few stitches can stay alive: re-posed, never warped. `E.live(g, E.sway(list, t, {origin, amp, period, phase}))`.

**The cloth and the hoop.** `E.linen(id, {pitch, tint})` a plate of cloth. `E.hoop(id, cx, cy, rx, ry, {band, wood})` a plate with the ring, its brass screw and its shadows on the cloth: draw it after the stitches.

**What the kit can't do for you.** Thread makes small things rich and big things slow: a hoop full of satin can be many thousands of stitches. It reads at phone size only if the design is simple and large.

**Behind a person.** Draw no linen and clear the frame: the stitches stand alone on the footage. Measure the outline first. The person's face is never covered, dimmed or tinted.

Refused as everywhere: timers, clock reads, `Math.random` (`E.rng`), the network. Write the name out as `M.look.embroidery`, or it won't load.
