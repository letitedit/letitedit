# Filmed camera moves and transitions

Adapted in our own words from sarpstar/cinecode's camera-moves reference (MIT;
Copyright (c) 2026 Sarp Yildiz, @sarpstar). See THIRD-PARTY-NOTICES.md.
These timings are starting points, not a preset. A selected Look's measured
shot lengths, speeds and permitted media take precedence. Name the intention,
move, direction, duration and start/end framing before placing it. One primary
move per shot; at most one quiet secondary move. Image motion is not proof of
a moving camera: a subject or editorial crop can move too.

## Supported image moves

| Name | Feeling and occasion | Starting timing/ease | Actual method |
|---|---|---|---|
| Digital push in | Attention or increasing pressure on an earned thought | 1-3 s; linear during a sequence, ease-out to land | Keyframe clip `zoom`; keep `focus` stable. Flat enlargement, not a dolly. |
| Digital pull out | Release or wider context | 1-3 s; ease-in-out | Reverse scale keys, with crop headroom from the start. |
| Pan / image drift | Follow a gesture or link visible details | 3-6 s; linear across cuts, ease-in-out for a reveal | Keyframe Size/Position (`size_position`) or crop centre; keep output covered. Digital pan, not physical tracking. |
| Tilt / vertical drift | Discover height or a detail below | 2-4 s; ease-in-out | Vertical position/crop-centre keys with source beyond both endpoints. |
| Push to detail | Make a real small piece important | 2-4 s; ease-out | Position/scale keys toward the detail; do not invent resolution. |
| Pull to reveal | Give a tight image context | 3-6 s; ease-in-out | Start cropped and keyframe out within the available source. |
| Slow motion | Let action or reaction register | Whole action, often 0.25-0.5x; constant | Clip `speed` scalar. Low frame rates repeat frames, not optical flow; sound changes too. |
| Time-lapse | Compress a process | 2-6 s result, often 8-100x; constant | Clip `speed` scalar, when the recorded process supports it. |
| Freeze | Pause for detail or thought | 0.5-2 s; hold | `{freeze: {clip, at}, len}`; distinguish deliberate holds from failed motion. |

Use keys `[[seconds, value], [seconds, value, ease]]` and supported eases
`linear`, `smooth`, `ease_in`, `ease_out`, `ease_in_out`. Read the effect's
parameters before writing filters. Measure displacement divided by frame
width/height and seconds; scale as log(scale ratio)/second. Report both axes.
Continuous sequence movement should already be underway on the first shown
frame; a controlled stop can ease out. Never impose a long default on a Look
measured at shorter shot lengths.

## Choosing and varying moves on cutaways

`{op: fx, camera_moves: true}` does the choosing for a project's cutaways; the rules are these. Names are the film
terms: the camera pans right when the picture slides left, tilts up when the picture slides down.

1. **Measure the clip's own image motion first** (direction, speed in frame widths per second, zoom per second). A clip
   that already moves enough gets nothing: adding a second move fights the first. A static shot or a still always gets a
   chosen move; one that moves a little gets a move that does not oppose it (or, following the scene, its own direction
   topped up).
2. **Vary.** Choose from the Look's measured spread of moves, pans and tilts included; without one, spread across pan,
   tilt, push and pull. Never the same move twice in a row in any mode, a move used before is less likely, and keep the
   speeds the Look measured.
3. **Follow the scene only when the Look asks.** A Look whose reference pans with the scene's motion says so; then a
   shot that already moves is continued in its own direction, never against it. Static shots still get the whole
   vocabulary. It is not a default.
4. **Keep the frame filled.** The move is keyed size and position over the cover fit; a wide stock clip in a tall frame pans
   without scaling, a tilt scales up for room (about 1.22 at most).

## Source physical moves in filmed footage

| Name | Feeling / fit | Starting timing/ease | Availability |
|---|---|---|---|
| Dolly in / out | Intimacy or tension / release and isolation | 3-6 s; flowing in, gentler out | Select filmed travel with perspective change. Digital scale cannot reproduce parallax. |
| Truck / tracking | Companionship with a moving subject, depth | 3-8 s; even travel | Filmed lateral move; a flat slide is only image drift. |
| Orbit | Discover spatial surroundings | 4-8 s, modest arc; even | Filmed orbit; no supported flat-footage depth reconstruction. |
| Crane / jib | Scale, elevation, discovery | 3-6 s; ease-in-out | Filmed rise/fall with perspective, not a vertical crop. |
| Dolly zoom | Disorientation or a singular realization | 2-4 s, once; coordinated travel/focal change | Select filmed stock. Opposing flat scales cancel instead of changing perspective. |
| Handheld | Human proximity, uncertainty, urgency | Whole shot; low-frequency irregularity | Prefer real restrained handheld. Do not label every measured shake handheld. |
| FPV / fly-through | Velocity and immersion | 2-6 s; continuous trajectory | Filmed movement with readable entries/exits; no invented 3D path from flat footage. |
| Rack focus | Transfer attention between depth planes | 0.5-1.5 s; ease-in-out | Filmed focus transfer; uniform blur is not a rack focus. |
| Focus pull during travel | Hold a subject as distance changes | Throughout travel | Filmed focus control; no supported depth-aware refocusing of flat footage. |
| Whip pan | Urgent handoff with matching direction | 0.2-0.35 s; fast sweep | Prefer filmed whip handles. No native named whip transition; do not invent one. |
| Speed ramp | Accelerate action then land a detail | 0.3-0.6 s ramp | No verified continuous ramp on source video: `speed` is scalar. Use suitable footage or decline; stepped speeds are not a smooth ramp. |

## Editorial transitions

| Name | Feeling / fit | Starting timing/ease | Actual method |
|---|---|---|---|
| Cut / smash cut | Clarity / deliberate contrast or surprise | Zero overlap | Choose content, scale and sound to earn the contrast. |
| Match cut | Link an idea by shape, action, direction or colour | Zero overlap | Choose matching source frames and cut; no special effect proves a match. Match target position and movement speed. |
| J-cut | Anticipate the next place or speaker | Audio leads 0.3-1.5 s | `{op: split_edit, id: incoming, lead: seconds}` with handles. Never overlap intelligible voices. |
| L-cut | Voice continues under reaction or explanation | Audio trails 0.5-2 s | `{op: split_edit, id: incoming, lag: seconds}`; `move: picture` keeps words fixed. Inspect returned handle limits. |
| Dissolve | Time passing, softness, connected handoff | 0.2-0.6 s | Clip `transition: seconds` or `{type: dissolve, len: seconds}`. Avoid muddy double faces. |
| Directional wipe | Reveal, traversal, graphic division | 0.2-0.5 s; even | Native `bar_horizontal`/`bar_vertical`, barn-door or iris types in `transition_spec`; inspect orientation. Not a named whip. |
| Negative flash | Brief punctuation at a justified cutaway edge | Look's native frame count; abrupt | `op: fx` transition item targeting b-roll with `type: cutaway_negative`, `edge: in` or `out`, `len`. Two 60 fps frames means exactly 2/60 s. `fx cut_flashes` also inverts the speaker's picture for the same frames (the face too, for those frames only); never flash every cut. |

Check first/middle/last native frames, crop coverage and the handoff. For dialogue
joins render `letitedit_check_range`, then read timeline words with
`letitedit_words(project)`; neither operation is a listening verdict. Unsupported
moves stay limitations or stock-search intentions, never passing claims. A
filmed-only Look does not authorize made scenes just to obtain a move.
