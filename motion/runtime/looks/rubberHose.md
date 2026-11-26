# Rubber hose: a 1930s studio cartoon, India ink at one pressure on a clear cel, flat greys on its back, noodle limbs, printed on black-and-white film

Comic and old: gags, mascots, a talking object, a jingle, a nostalgic joke, children's or grown-ups' humour. It can run as a whole film, a cutaway or a character beside a speaker. It's the AI's choice for this video.

`const R = M.look.rubberHose.start(c.w, c.h)` in your block, on one full-frame canvas: `const cv = M.el('canvas', {}, stage); cv.width = c.w; cv.height = c.h; cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%'; const g = cv.getContext('2d');`. The block returns `(t) => {...}`, the frame at `t` seconds. You write the gag and the character; this is only the kit.

**How it stays fast and exact.** Each drawing is a list of parts, redrawn fresh for each pose: `R.cel(g, parts, {key})` keeps a finished pose under `key`, so hold the same key for a held pose. A drawing number from `R.drawing(t)` decides everything that varies, so frame N is the same whatever came before. Start each frame with `R.begin(g)` and a paper or set; end with `R.begin(g); R.finish(g, {t, fps})`.

**The medium.** One line weight, no thick and thin, with a slight hand wobble that is new on each drawing. Contours stop where a nearer shape starts: each part knocks its own interior out of the ink beneath it, and an outline of several shapes reads as one silhouette. Paint is flat and never modelled. Greys only, and the print tones them warm: `R.G` has `ink`, `white`, `light`, `mid`, `grey`, `dark`, `shadow`, `set`. Cast shadows are flat, translucent and uninked.

**The parts,** back to front in the list:
- `R.part({fills: [{pts, col, alpha, touch}], outline: [shape, ...], ow, details: [{pts, w, closed, col}], knock})` any piece. `touch` is where the paint brush starts. `knock: false` lets the ink behind show through.
Points are `[x, y]` in frame pixels. Angles are radians, clockwise on screen.
- `R.limb(a, b, bend, w)` the solid black noodle: one arc from shoulder to wrist, no elbow. `bend` = pixels it bows off the straight line; a positive bend bows to the right of the way from a to b, as seen on screen.
- `R.glove(wrist, angle, mirror, {k, boil})` the white four-digit glove with three stitch lines and a flared cuff, about 90 px long at `k` 1. Angle 0 points the digits straight up; `mirror` puts the thumb on the other side. `R.shoe(ankle, angle, mirror, {k, boil, color})` the big oval shoe with one shine, about 90 px long at `k` 1, toe to the right unless `mirror`. `R.eye(x, y, rx, ry, [dx, dy], {boil})` the big eye with a pie-cut pupil; `dx`, `dy` are how far it looks, as fractions of the eye's radii: stay within about 0.4, or the pupil leaves the eye.
- `R.shadow(pts, alpha)` a cast shadow.
- `R.title(g, TEXT, x, y, cap, {color, outline, w})` stroked capitals, figures and common signs centred at (x, y), `cap` tall, drawn straight on this frame: a title card or a balloon's words. Drawn letters suit the medium where a modern font would not.
- Shapes: `R.ell(cx, cy, rx, ry, rot, n)`, `R.capsule(a, b, r)`, `R.rect(x0, y0, x1, y1)`, `R.cb(a, c1, c2, b, n)` and `R.qb(a, c, b, n)` curves, `R.noodle(a, b, bend)`, `R.smooth(pts, closed, per)`. `R.place(pts, origin, angle, sx, sy, mirror)` squashes and places local points. `R.wob(pts, amp, seed)` is the inker's wobble: give outlines a new seed per drawing, with `boil` from the drawing number.

**How it moves.** On twos, with key poses on the beat.
- `R.cel(g, parts, {ink, paint, key, x, y, s, pivot, alpha})` `ink` 0..1 lays the line, longest fastest; `paint` 0..1 floods the greys, each from where the brush touched. Leave both at 1 for a finished drawing. `R.rough(g, pts, {closed})` is the blue-pencil line of action under them.
- `R.hop(t, beat, height, fps)` gives `{y, sx, sy, beat, u}`: a hop between key poses, stretched in the air, squashed on landing. Feed `sx`, `sy` to `R.place`.
- `R.drawing(t, fps)` a whole number, the drawing on twos. `R.behind(u, by)` a number 0..1: the hop's `u` a little earlier, since limbs follow the body a couple of frames late on the same arc.
- `R.weave(t, fps, on)` `[x, y]`, the gate's small shift: put it on the whole picture while things move, and off on a hold.

**The print.** `R.finish(g, {t, fps})` warm tone, per-frame grain, flicker, dust, a hair, a scratch, the lamp's vignette and the rounded gate: it covers the whole frame. `{still: true}` freezes the grain on a hold.

**What the kit can't do for you.** The kit gives gloves, shoes, eyes and the film; the character and the timing are yours. A gag needs a clear pose on each beat, and a real anticipation before the big move.

**Behind a person.** Use `R.finish(g, {t, grainOnly: true})`: the full print would paint over the footage. The drawing keeps its grain and the footage stays as it is. The person's face is never covered, dimmed or tinted.

Refused as everywhere: timers, clock reads, `Math.random` (`R.rng`), the network. Write the name out as `M.look.rubberHose`, or it won't load.
