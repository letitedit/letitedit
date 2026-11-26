---
name: letitedit-layers
description: What is in front of what in a letitedit edit, and what an effect touches - track order, text or a scene behind a person, an object lifted out of its shot, a title over everything, picture-in-picture, an overlay with a blend mode, a colour change on one clip, one track, a stretch or the whole video, everything but the person, a stretch of everything below a title (an adjustment layer), a blurred or tinted region (number plate, face, screen), what the engine can't do, and how to prove the result with frames. Use whenever an edit stacks things or aims an effect, or on notes like 'put this behind me', 'pull that part out', 'outline that', 'blur that', 'tint just this part', 'darken the room', 'warm up this section', 'it's covering me', 'the blend didn't do anything'.
metadata:
  version: 0.1.0
---

# Layers: what is in front, and what an effect touches

**The decision:** which layers this moment needs, in which order, and the narrowest thing an effect has to touch.
letitedit-graphics decides whether a device earns its place; this skill makes it stack correctly. Check the result through the export engine [OURS].
Setting names come from `letitedit_effects`; read an effect's settings there rather than from memory.

## 1. The stack
Back to front, as `letitedit_timeline_read` lists it:
1. Video tracks, in the order they are listed: **a later track draws over an earlier one.** The first video track is the
   main picture; it has nothing behind it, so opacity on it shows nothing.
2. On each track, a clip's picture goes through its own effects, then the track's effects, then lands on what is below.
3. An adjustment layer is a block on a track: its effects run on everything drawn so far, so it changes every track below it
   and none above it, only for as long as it lasts.
4. Whole-video (master) effects on the combined picture.
5. Burned-in captions, always last. They sit above every track wherever their track is listed, and a master effect does
   not touch them. A title on a track therefore goes under captions and is changed by master effects.

An upper track is see-through wherever it has no clip, and wherever its clip has alpha: a cut-out, `{ass}`, `{motion}`, a
scene, or `{color: '#00000000', len, effects: [{text: ...}]}`.

**Changing the order:**
- A new layer: `{op: add_track, name, kind: video}` goes on top; `after: <track>` puts it just above that track.
- Move a piece: `{op: move, id, track, at}`.
- Swap two upper tracks: reorder `tracks` in a whole script (`letitedit_timeline_apply(script_yaml=...)`). It renders right
  (saved-project behavior; open-window support is unverified).
- **The first video track stays first.** A script that puts another video track under it is refused. Change what is on
  the tracks instead.
- A track with the wrong blend order is repaired by the next edit; nothing to do.

## 2. Common jobs

| Job | Do | Know |
|---|---|---|
| Scene behind the person | `letitedit_code_scene(create, behind_person=true)` | One cut-out piece per clip under it, on a Person track, in one Undo. `revise` with `behind_person=true` adds it to a scene already there. Time: about 10 s per second of 60 fps footage the first time, however many pieces. A canvas or page elements both work: the live player keeps the person in front of either, and hides the scene with a note until its masks are drawn |
| Scene moved or trimmed later | Move or trim the Person pieces too | The cut-out does not follow the scene; `revise` touches only the scene. Mattes are kept per frame, so a trim, a re-cut piece or a re-order never runs the model again for frames it has seen: about 3-5 s per second of footage to write the piece |
| Text behind the person | Order: footage, title track, then `{vfx: {effect: cutout, source}}` over the same seconds on a track above | Title and person stay separate, movable pieces. `text_behind` is one baked clip with one text and no grow animation: fine for a small static word. Keep the letters clear of the head: they vanish behind it |
| Title over everything | A track on top | Captions still draw over it: keep them apart (`letitedit_caption_fit`) |
| Picture-in-picture | `{op: insert, track: V2, at: 2, item: {clip, in, out, effects: [{size_position: 'x y w h'}, mute]}}` (project pixels). Keep the width and height in the clip's own shape | Its sound plays unless it is muted (`mute` in `effects`, or `mute: true` on the item). Effects listed before `size_position` act on the clip's full picture |
| Overlay with a blend mode | A clip on an upper track with `{filter: cairoblend_mode, params: {mode: screen}}` (section 3) | `{opacity: 0.5}` for a plain see-through |
| Colour on one clip | `{op: effects, id, effects}` | **Replaces the clip's list**: send back what you keep. To even shots: `letitedit_match_shots` |
| Colour on one track | `{op: track, name, effects}` | Touches that track's picture only, wherever its clips are. Replaces the track's list |
| Colour on the whole video | `{op: master, effects}` | Every track, not captions. **Replaces the master list**, which may hold loudness and limiter: read it and send those back |
| Part of the timeline, every track | `{op: aim, effect, on: all, from, to}` | Every track, not captions. Any engine effect, no keys needed. It moves with its picture when the main track is cut, and goes if that picture is cut out |
| A stretch of everything below a title | `{op: adjust, effects: [...], below: Title, from, to}` or `words: 'quit'` for where it is said | **An adjustment layer:** one block on a track of its own, with any picture effects, a blur or vignette included, on the combined picture. The person can drag, trim, switch it off with the track's eye and change its effects in the Filters panel. See section 4 |
| Everything but the person | `{op: aim, effect, on: not_person, from, to}` | The effect on the footage, with a cut-out above it (reuses one already there). The person stays untouched. The first matte takes tens of seconds per second of footage. `{vfx: {effect: backdrop}}` is the baked one-clip version (blur, colour, picture, video) |
| Only the person | `{op: aim, effect, on: person, from, to}` | The effect on cut-out pieces; the room stays untouched |
| One solid thing out of its shot, over a new backdrop | `letitedit_object` to make it, then `{op: lift, object, from, to}` (section 6) | Its moves are keys on its track; re-time with `{op: lift, id, ...}`. A scene goes on a track below it. Rigid things only; it refuses the rest in plain words |
| One solid thing kept in front of what's added behind it, or outlined or recoloured in place | `{vfx: {effect: object, source: {clip, in, out}, params: {object, show}}}` on a track above | `show`: object, outline, glow, recolour. Rigid things only |
| Blur something that moves (plate, face, screen) | `{vfx: {effect: blur, source, params: {box, at}}}` in place of the clip, or `faces: true` | Tracks the box. One baked clip, cached; takes seconds to minutes |
| Tint or change one region | `{op: aim, effect, on: clip, id, region: {shape, box, soft}}` | A rectangle, ellipse, triangle or diamond in the clip's own picture. `invert: true` changes everything but the shape. `path:` takes `letitedit_track`'s rows to follow something. One clip at a time |

## 3. Details that fail quietly

**Blend modes do nothing on the wrong kind of track**; the edit's reply and `stack_at` say so. Tracks in projects these tools write
blend with cairoblend: `{filter: cairoblend_mode, params: {mode}}`, modes `normal add saturate multiply screen overlay
darken colordodge colorburn hardlight softlight difference exclusion`. A track in a project started by hand in the app can
blend with Qt: `{filter: qtblend_mode, params: {mode: N}}`, numbers 12 plus, 13 multiply, 14 screen, 15 overlay, 16 darken,
17 lighten, 18 colour dodge, 19 colour burn, 20 hard light, 21 soft light, 22 difference, 23 exclusion. A Qt `mode: multiply`
also does nothing. Don't test on a mid-grey overlay: `overlay` over 50% grey is correctly no change.

A person can also set a blend on a whole track in the app. Edits keep it, and `stack_at` shows it, though the YAML
read doesn't. If a track looks blended and its clips have no blend effect, that is why.

**`aim` adds; `{op: effects}`, `{op: track}` and `{op: master}` replace.** `{op: effects, ids | track, add}` adds the same
effects to many clips in one op (a gain, a filter, a `{fix}` on every speaker clip); one op per clip is slower and costs
a step each. Prefer `aim` for one more effect. Its filters are
tagged `letitedit_ai:aim` in the read; a time range is `in`/`out` in frames. To remove one, send back the list without it, or Undo.
A region shows in the read as three effects in a row, `mask_start`, the effect and `mask_apply`, placed first so the shape is in the
clip's full picture and shrinks with it under a later `size_position`. A blur on something that moves is simpler as
`{vfx: blur}`, which tracks it.

**`on: clip` takes no time range**, since a clip's effects run on its own clock; use `all`, or `{op: adjust}`, or cut the clip. `on: below` makes an adjustment layer under that track, the same as `{op: adjust, below}`; older projects' per-track `below` effects keep working as they are.

**In an open window:** a new track in the middle of the stack (`person` or `not_person` with titles above) needs a saved project: with
unsaved changes the edit asks for a save, otherwise the window reloads. A block's new track is the exception: it goes straight in, one Undo.

## 4. Which one, and what isn't possible
**Pick the narrowest thing that does the job.** An effect in the wrong place is the commonest way a stack goes wrong.

| What should change | Use | Why not an adjustment layer |
|---|---|---|
| One clip | `{op: effects, id}` or `aim on: clip` | It moves and is cut with that clip; a block would stay behind or need moving too |
| One track, all its length | `{op: track}` | Nothing to line up |
| The whole video, start to end | `{op: master}` | Also changes titles; a block would leave anything above it out |
| **Several tracks together, for a stretch, with something staying clean above** | **`{op: adjust}`** | This is the job it exists for: a section's look over footage and b-roll under a title; a blur or darkening behind a title or a cut-out |
| Only the person, or everything but the person | `aim on: person`, `not_person` | The block can't tell the person from the room, unless a cut-out sits above it |
| A shape (plate, face, screen) | `aim` with a `region`, or `{vfx: blur}` | A block covers the whole frame |

**The room behind a person, with the person clean:** footage, then a block, then a `{vfx: {effect: cutout}}` on a track above it: `{op: adjust, effects, below: Person}`. Same picture as `aim on: not_person`, and the person can trim it by hand. A blur still has them in the footage below, so a soft halo of their colours stays around them, wider with a bigger radius; keep the radius modest, or use `{vfx: {effect: backdrop}}` where the halo shows.

**Details:**
- Captions always stay clean (they are drawn last). A title stays clean if its track is above the block; to change it too, put the block above it (`above: Title`) or use master.
- It starts and ends on exact frames, with a hard edge. To ease it in, key the effect's own setting: `{filter: brightness, params: {level: {keys: [[0, 1], [0.5, .5]]}}}`, keys counted from the block's start.
- **`fade_in`, `fade_out` and `opacity` on a block act on the whole picture below it, not on the effect's strength:** a fade comes up from black, and opacity darkens. To ease the effect, key its setting.
- Cuts on the main picture carry it: it stays on its picture, shortens when part of that is cut, and goes if all of that is cut.
- Blend modes, crop and stabilise don't work on a block and are refused: they act on one clip's own picture.
- A hidden track's block changes nothing; a gap or a hidden track below it is fine.
- **A code scene under a block:** the export and `letitedit_code_scene look` show the effect. The live player draws the scene over the picture, so it shows the scene without it; `stack_at` warns. Say so when it matters.

**Not possible; say so plainly, don't imply these exist:**
- **No effect aimed by an object's outline as such.** An object layer can be recoloured or outlined (`show`), and anything can go behind it. For another effect, put the object on a
  track above the footage and the effect on the footage or on a block under it, so everything but the object changes.
- **Object layers can't do floppy things or a thing turning in the hand:** a cable, cloth, a plant, a door opening, a part spun round to show its other side. One outline serves the whole
  shot, so the tool refuses these rather than making a bad layer, and says which range would work if there is one. Not a limit of the footage: a limit of this tool today.
- **No track matte** (footage showing through letters) on the timeline. A made clip can do it, baked:
  `{ffmpeg: {inputs, video}}` or a graphic with `source`.
- **No groups or nesting** of tracks.
- **A scene can only cover** what is under it; it can't blur or tint the room. Use an effect on the footage or a block for that.
- No op sets a whole track's blend mode; use the clip effect on each clip.

## 5. Prove it
A successful call is not a correct stack. Look at each new layer where it starts, in the middle and where it ends.
- **Before working anything out from the tracks,** read the moment: `letitedit_timeline_read(project, stack_at=3.5)`, or
  `stack_at=[2, 5]` for a block per change. It lists the layers back to front with size, alpha, blend and effects, and warns
  about a blend that does nothing, a scene with no cut-out above it and a cut-out out of step with the footage. It reads
  the project, not the picture: frames still prove it. `check_frames(stack=True)` puts the same text beside each frame.
- `letitedit_check_frames(project, times_s=[...])` renders with the export engine and shows scenes. By saved path it reads
  the saved file, so an AI working in an open window with unsaved edits sees the old state: use `project='live'` for the
  person's default window.
- Scenes: `letitedit_code_scene(look)`, with everyone in place, in seconds. `letitedit_check_range` for movement.
- An `aim` or `adjust` reply has before and after frames and how much changed inside the target and outside its stretch; a `warning` there means
  look again. It can't tell a title from the footage in the same frame, so look at the frames. For anything else, take your own
  frames before and after, and check the part it must not touch as well as the part it must.
- A person in front: the face and cap in front and unchanged by the scene (a face dimmed or tinted there means the scene
  is over them, not behind), the scene or title behind them, and the plain shot back outside those seconds.
- A frame labelled "NOT drawn" has a scene that could not be drawn; that isn't an empty background.
- Finish with `letitedit_review_bundle` as always (letitedit-gate).

## 6. An object as a layer
**When:** letitedit-graphics section 1, its device 4b and its references/object-in-scene.md decide. **Do:** read references/object-layer.md in full before
`letitedit_object` (look and choose with `this`, `not_this` and `in_front` points; check the mask; make it; check and fix the
outline yourself; place it with `{op: lift}` after the scene; prove it at both ends). **Cost:** about 15 s of work per second
of footage to make it, more with `in_front`, and a few minutes in all for a moment of a few seconds: don't make one for a line
a pointer would explain.
