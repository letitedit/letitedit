# An object as a layer: the steps (letitedit-layers section 6)

Read in full before `letitedit_object` or `{op: lift}` makes or places an object layer.

**When:** letitedit-graphics section 1 and its scenes section decide. This section is how.

**1. Look and choose.** `letitedit_object(action='frame', clip, at)` gives a sharp frame with a grid in the clip's pixels. Pick a moment when the object is whole, sharp and not much covered.
Put 3-6 `this` points well inside it, on different parts, thin parts too (a shaft, a stem), and 3-6 `not_this` on whatever touches it or looks like it: the neighbour, the surface it rests on, its
own shadow, wires you don't want. Points on the object alone often take the surface as well [OURS]. If a hand comes near it, put `in_front` points on the hand.

**2. Check the mask.** `letitedit_object(action='try', clip, at, this, not_this, in_front)`. Look at the close-up: is all of it pink, thin parts included, and nothing else? Add points and try again; it
takes a second or two. A mask that takes the surface needs more `not_this`. `pieces` above 1 means a part is cut off or something else is in.

**3. Make it.** `action='make'` with `start`, `end` a little wider than the moment you need, and the same points. If the reply is `made: false`, read `why`: use `checks.holds` as the new range if it's there
and long enough, otherwise this object can't be a layer here, so use a pointer, a freeze or a drawn version. Don't keep retrying the same range.

**4. Check the outline, and fix it yourself.** Look at both pictures. On the first, the cut-out on dark and on bright: is the edge clean with no background along it, and are the thin parts there? On the second,
the numbered outline on the plate. Automatic outlines go wrong where the object meets something the same colour (a pale cap on a pale towel), around small parts, and at corners [OURS]. Fix what's wrong
with `action='outline'`: `move: {"12": [x, y]}`, `drop: [..]`, `add: [[after, x, y]]`, reading x and y from the grid, which is in plate pixels. A point on a real corner stays a corner, the curve is smooth between points, and
each stretch settles on the nearest clear edge, so a point only has to be close. Look again at the new pictures. Two rounds usually do it; a viewer sees wobble on a machined edge at once, so straight sides should be
straight. The reply is a new id: use the newest one.

**5. Place it.** Make the scene first, then the lift: its tracks go on top of what's there, and the scene has to be below them. Give the scene the reply's stretch; a scene that starts before it shows over the footage for those frames, and the edit's reply says so. A re-time moves the lift and not the scene, so move the scene with it.
- `{op: lift, object, from, to, size?, at?, rotate?, arrive?, leave?, background?}`, or `words:` for the stretch. `from` is where the move starts, so land the arrival on the word: start about `arrive` before it,
  and prefer a moment in `clear` for both ends, when nothing is in front of the object.
- `size` is its height as a share of the frame; a bit over 1.5x the shot's own pixels starts to look soft, and the reply says so. `rotate` by minus `axis_deg` stands it upright.
- `background: fall` tips the room back and drops it, `fade` fades it, `none` leaves whatever is below showing (a scene that makes its own way in, or a darkened room with `{op: adjust}`).
- A scene with a label on the object has to know where the object is during the hold: use `at`, `size` and the plate's numbers, or simply look at the frames. Leave its bottom and top clear if the labels go there.
- Change it later with `{op: lift, id: <any piece>, ...}`: same moves rebuilt, one Undo; `remove: true` takes it away. A trim, a move or a cut on the footage under it rebuilds the moves by itself, and the reply says so. A trim the
  person makes by hand in the app shows in your next read, and your next edit rebuilds the moves for it; the read's `stack_at` shows the layers either way.
- A cut in the footage under it is fine: one piece per clip with one move.

**6. Prove it.** `letitedit_check_frames` around both ends, one frame apart if you can: the object should sit exactly where the shot has it as the layer fades in and out, with no jump, and the footage should take over cleanly. Then the
middle at full size. A scene behind it also shows in `letitedit_code_scene look`. In the live player the scene stays hidden until its masks are drawn, with the shot showing and a percent note; the object and background still show and the export is always right.

**Cost:** about 15 s of work per second of footage to make it (more with `in_front`), the same again for each lift's movie (cached), a few minutes in all for a moment of a few seconds. Don't make one for a line a pointer would explain.
