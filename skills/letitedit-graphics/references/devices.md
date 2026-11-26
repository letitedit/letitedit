# Graphics devices: calls and checks

Confirm current field names with `letitedit_guide('letitedit_annotate')`. Graphics go on a video track above the footage
(`{op: add_track, name: 'Graphics', kind: video}`; later video tracks draw over earlier ones). Place with
`{op: insert, track, at: <timeline s>, item: {...}}` and change later with `{op: set, id, ...}`.

## 1. Finding the proving shot
`letitedit_search` (picture and words), the footage log's `seen:` lines (`letitedit_footage(path, log=True)`),
`letitedit_ask_frames` for a yes/no on a frame, `letitedit_check_frames(shots=True)` for the storyboard. A proving shot
shows this event's own part, fault or result; note which in its `why:` marker (`evidence`).

## 2. Detail crop
- On the clip, keyed so it punches in only for the detail:
  `{op: set, id: <clip id>, effects: [<its other effects>, {zoom: {keys: [[0, 1.0], [2.0, 1.0], [2.4, 1.6, ease_in_out], [5.0, 1.6]]}, focus: [0.62, 0.40]}]}`
  (`focus` is the point it zooms toward, in fractions of the frame; key times are seconds into the clip; `effects`
  replaces the list, so restate the clip's other effects).
- Or a magnified inset that keeps the context: `letitedit_annotate(..., kind='magnify', target=[...])` (the detail comes
  from the source at full resolution, so it stays sharper than a timeline zoom of the same size).
- Limits [GEN]: about 1.25x on a 1080p source, about 2x on 4K in a 1080 timeline; past that the detail goes soft.
  Look at the frame at full size (`letitedit_check_frames(times_s=[...], width=<project width>)`).

## 3. Freeze and label
- One call: `letitedit_annotate(project, clip=<id>, kind='label', target=[x0, y0, x1, y1], at=<source s>, freeze=True,
  duration=2.5, text='Cracked blade')`: an overlay of the clip's own frame at `at` (rendered by the export engine,
  grade included) with the label; the sound runs on and the timeline keeps its length.
- By hand, when time should really stop: `{op: insert, track: <main track>, after: <id>, item: {freeze: {clip: <file>,
  at: <source s>}, len: 2.5}}` and a label graphic over it. This lengthens the timeline and has no sound of its own:
  keep the ambience bed running under it (letitedit-sound). Annotate refuses freeze items, so point with annotate's
  own `freeze=True` instead when the label must follow an object.
- Reading time [GEN]: words / 3.5 + 0.5 s, at least 1.5 s (the same rule letitedit-shorts uses for hook text).

## 4. `letitedit_annotate`: a pointer that points at the right thing
| Field | Meaning (defaults) |
|---|---|
| `clip` | the clip's id on the timeline (`letitedit_timeline_read` lists ids) |
| `kind` | `ring` (default), `arrow`, `box`, `label` (a dot, a leader and text; needs `text`), `magnify` (a ring and a round inset of the detail taken from the source at full resolution) |
| `target` | a box `[x0, y0, x1, y1]` or point `[x, y]` in the clip's own upright picture, as frame tools show the file: fractions 0-1 (`units='px'` for source pixels; `space='coded'` before the orientation flag) |
| `at` | the source time at which the target box is right (default: the range start) |
| when | `source_range` [a, b] (seconds in the clip's file), `timeline_range` [a, b], or `at` + `duration` (3 s) |
| `follow` | `static` (the object stays put in the source; a tracker warns if it moves away) or `track` (follow it; needs a box); `track_result` reuses a `letitedit_track` result |
| `lost` | where tracking fails: `hide` (default: fades out, never drawn on lost frames), `hold` (the last sure place, dimmed, up to 0.5 s), `stop` |
| `freeze` | true: hold the picture at `at` as an overlay; the sound runs on |
| `text`, `style` | `style`: `color` (secondary), `outline`, `label_fill`, `label_text`, `font` (heading), `size` 44, `stroke` 7, `arrow` 150, `inset` 0.36, `zoom`, `dim` (0-1 spotlight), `fade_in` 0.3, `fade_out` 0.25, `pop` true, `label_side`, `margin` |
| `protect`, `platform` | regions the label or inset must avoid (`[x0, y0, x1, y1]` or `{box, start_s?, end_s?, name?}`); the app's covered areas. Burnt-in captions, other graphics and faces are avoided anyway |
| `track` | `Annotations` (the next free `Annotations 2`... if busy) |
| `apply`, `plan_id`, `refresh`, `list_only` | plan and apply in one call; apply an earlier plan; re-plan existing annotations (`refresh=True` or `[ids]`) after the clip changed; list the project's annotations |

It maps the box through everything the timeline does to the clip (orientation, Crop: Source, Size/Position/Rotate and
zoom, static or keyframed, fit, mirror, trims, position) with the export engine's arithmetic; places the label inside
the frame away from captions, other graphics, faces and app zones; renders preview frames and measures where the
object really is (`object_in_render`: matched, weak, ambiguous, not found) and where the pointer was drawn. The result
lists `hidden_ranges` (lost, cropped away, out of frame, covered) and warnings (`unresolved: ...` when a label can't
avoid something). It refuses (nothing changed, the reason given): clips at another speed, reversed or time-remapped
clips, made clips (ffmpeg graphs, freezes), graphics, effects that warp or shake the picture (stabilise, lens
correction, corner pin, distort, 360), two Size/Position or two Crop: Source effects on one clip, whole-track picture
effects, mirrored orientation flags, EXIF-rotated photos, and a range where the clip isn't seen. Edit the wording or
style later with `{op: set, id, graphic: {params: {text, style}}}`. One pointer on screen at a time; a pointer on an
obvious, still object is noise.

## 5. Labels, step counters, lower thirds and cards: designed for this video
Ready-made design templates are no longer offered to agents (graphics made for the video beat filled-in ones in every
comparison we ran). Use the Look's own saved templates first (`letitedit_graphic()` lists what is offered),
otherwise draw with `template: 'custom'`. Sizes in the helpers are pixels at 1080p, scaled to the project; colours and
fonts can be kit names (`primary`, `accent`, `secondary`, `dark`, `light`; `heading`, `body`, `captions`).

Helpers in `draw(ctx)`: `ctx.w`, `ctx.h`, `ctx.p` (params), `ctx.s(px)`, `ctx.x(frac)`, `ctx.y(frac)`, `ctx.t`,
`ctx.anim_in(dur)`, `ctx.anim_out(dur)`, `ctx.visible(in, out)`, `ctx.color(ref, alpha)`, `ctx.font(ref, size)`,
`ctx.measure(text, font, size)`, `ctx.fit_size(...)`, `ctx.wrap(...)`, `ctx.text(xy, text, font, size, fill, anchor,
outline, outline_width, shadow, opacity)`, `ctx.rect(box, fill, radius, outline, width)`, `ctx.line`, `ctx.circle`,
`ctx.image(path or picture, box, fit)`, `ctx.place(w, h, position, margin_x, margin_y)`, `ctx.still(clip, t, size)`,
`ctx.src` (the recipe's `source` clip frame).

A step label (one look for every step; preview it with `letitedit_graphic(template='custom', code=..., params=...)`):
```python
def draw(ctx):
    p, v = ctx.p, ctx.visible(0.3, 0.3)
    kicker, title = f"STEP {p['n']} OF {p['of']}", p['title']
    pad = ctx.s(24)
    w1, h1 = ctx.measure(kicker, 'body', 34)
    w2, h2 = ctx.measure(title, 'heading', 64)
    bw, bh = max(w1, w2) + 2 * pad, h1 + h2 + 3 * pad
    x, y = ctx.place(bw, bh, 'top-left', margin_y=p.get('margin_y', 0.16))
    ctx.rect([x, y, x + bw, y + bh], fill=ctx.color('dark', 0.82 * v), radius=18)
    ctx.text((x + pad, y + pad), kicker, 'body', 34, fill='accent', opacity=v)
    ctx.text((x + pad, y + 2 * pad + h1), title, 'heading', 64, fill='light', opacity=v)
```
`{op: insert, track: 'Graphics', at: 31.2, item: {graphic: {template: 'custom', code: <above>, params: {n: 2, of: 3,
title: 'Pull the old fan'}}, len: 3.5}}`. Keep `margin_y` clear of the app's top overlay (Reels covers the top 14%).
A lower third is the same idea at the bottom-left (name in `heading`, role in `body`), 3-5 s, once per person; a
chapter card the same design at every turn; a counter reads its numbers from params, never invented.

A text-only label can also be an `{ass: "<script>", len}` layer (libass: styles, `\pos`, `\fad`, `\move`):
```
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Label,<the pack's heading font>,72,&H00FFFFFF,&H00FFFFFF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,5,0,8,60,60,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:03.00,Label,,0,0,0,,{\pos(540,330)\fad(150,150)}STEP 2: PULL THE OLD FAN
```
Fonts must be installed (`letitedit_fonts`).

## 6. Matched before/after
- Match first: the same angle and framing; `letitedit_match_shots` evens exposure and white balance between the two.
- Side by side with a `source` graphic (`ctx.src` is the after clip, `ctx.still` the before frame):
```python
def draw(ctx):
    W, H = ctx.w, ctx.h
    before = ctx.still(ctx.p['before_clip'], ctx.p['before_at'], (W // 2, H))
    ctx.image(before, [0, 0, W // 2, H], fit='contain')
    ctx.image(ctx.src, [W // 2, 0, W, H], fit='contain')
    ctx.rect([W // 2 - ctx.s(3), 0, W // 2 + ctx.s(3), H], fill='light')
    for x, word in ((ctx.s(40), 'BEFORE'), (W // 2 + ctx.s(40), 'AFTER')):
        ctx.text((x, ctx.y(0.08)), word, 'heading', 56, fill='light', outline='dark', outline_width=4)
```
  `item: {graphic: {template: 'custom', code: <above>, params: {before_clip: <file>, before_at: 12.0},
  source: {clip: <after file>, in: 40.0, out: 44.0}}, len: 4}` (graphics with a source are opaque unless
  `params.alpha` is true). On a vertical frame stack them top and bottom instead.
- Or a straight cut between the matched shots with BEFORE / AFTER labels.

## 7. Diagrams and maps
- A diagram: a `custom` graphic built up one element at a time (`ctx.anim_in(dur, delay)` per element), labelled as a
  diagram, with few parts and the same colours as the other graphics.
- A map: `{map: {clips | points, ...}, len}` from clips' GPS or coordinates (`letitedit_map` lists the settings).

## 8. Transitions and time devices
| Device | Its job | How |
|---|---|---|
| Straight cut | the default | nothing |
| Dissolve | time passing, a change of place | `transition: 0.5` (seconds) on the incoming clip |
| Superimposition | a head-space, a vision, a memory | an upper-track clip with `{opacity: 0.5}` (keys to fade it) |
| Wipe | time or place, following the motion's direction | `transition: {type: bar_horizontal, len: 0.6, invert: false}`; other types in GUIDE.md |
| Cut to black | a chapter marker at a turning point | `{color: '#000000', len: 1.0}` on the main track, the same length every time |
| Fade to black | the end of a quiet section | `{fade_out: 1.0}` and `{fade_out_audio: 1.0}` on the clip |
| Time card or date | elapsed time, a countdown | a card or badge designed for the video; dates only move forward |
| Audio crossfade at a hard cut | smoothing a dialogue join (not a storytelling transition) | `transition: {type: cut, len: 0.25}` (letitedit-fine) |

A lively scene ends on a cut to black on a beat, not a fade (letitedit-sound places the beat).

## 9. Device inventory (for the repetition ledger)
Count from `letitedit_timeline_read`: transitions by type; emphasis zooms and punch-ins (not the scale changes that only
hide a jump cut: those are cutting grammar, letitedit-fine); speed ramps and `vfx` items
(arrows, spotlights, 3D pop-ups, light leaks); SFX files; text animations and entrance styles; freezes; black gaps and
their lengths. Record each use with its time and reason in the ledger letitedit-craft keeps (or a
`device:<kind>:<reason>` marker with `letitedit_bin`). A device used twice needs the second use to escalate; three uses
of one device without escalation is a flag; "less flashy" removes them first.
