# Clean explainer: the recipe

A 16:9 YouTube video (3-15 min) that teaches one thing well: how something works, why it broke, how to do it. Calm
and clear on screen: chapter cards, a label or a pointer wherever the viewer might not know what they are looking
at, one idea at a time, music only between parts. The tutorial rules in letitedit-modes (tutorial-explainer) and
letitedit-graphics come first: the step list is the structure, values exactly as recorded, nothing private on
screen, the result shown working. Evidence tags are explained in letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-clean-explainer}`; the look on the footage tracks (`{op: track, name: <track>, effects:
<look.effects>}`); `{op: fx}` with this pack's presets; `letitedit_annotate` for parts that move;
`letitedit_bin` for `chapter:` markers; `letitedit_hooks` + `{op: hook}`; `{op: score}` for the music.
Make the B-roll track right after the cut, before the captions (`{op: add_track, name: B-roll, kind: video}`): a B-roll track made later draws over the captions in a render.

## Structure
1. Cold open (0-5 s): the outcome or the problem, seen [CLU, JH]; then the promise and its shape ("why it grinds,
   and the fix in four steps").
2. Title card (2-3 s) - optional; never a long sequence.
3. Three to five parts [CLU], each a chapter: a `chapter` card over its first shot and a `chapter:<name>` marker
   (the first at 0:00, at least three, each at least 10 s [HED, YT]).
4. Inside a part: the why (on the face), then the how (on the hands or the screen), then the proof (the result).
5. The end: the result working and a one-line recap; an end card only if the brief asks.

## Pacing
- Something changes on screen every 10-20 s in the first three minutes, every 25-40 s after [AIR]: a cut, a label,
  a pointer, a small push-in. A talking head held past about 40 s with nothing changing loses people [AIR].
- Hold while the viewer must watch: no cutaway, push or label over a step being copied [modes].
- Trim pauses over about half a second (`editing.max_pause` 0.45) [HED, MON]; keep a beat after a hard idea [ITE].
- Steps of 30-40 s at most [CLU]; longer ones split into two.

## On screen (one fx batch per part)
- `chapter` at each part's start; `step_label` ("Step 2 of 4: ...") at each step's spoken start, numbered as
  promised [modes].
- `label` for a part, tool or value the viewer must recognise, six words at most, sentence case [CLU], 1.5-3 s
  [OVS], 250-400 ms after it appears [CLU]. `point_at` (or `letitedit_annotate` if it moves) for the exact part.
- `fact_number` for a figure the explanation turns on; `key_point` once per part at most.
- `gentle_push` every 25-45 s on long talking stretches [HED]; `section_dissolve` between parts only (0.3 s) [CLU].
- `cutaway` for proof and orientation, never over a step being copied or the why [modes].
- Draw what the camera can't show (a diagram with `letitedit_graphic` custom, a labelled freeze) [modes].

## Captions
- Deliver an SRT for YouTube. Burn captions in only when the brief asks: two lines of 42 characters at most [HED],
  Inter SemiBold on a soft dark box at the bottom.

## Sound and music
- The voice first, clean and level. Music light and without lyrics: up in the intro, between parts and on the
  result; out, or 28 dB under, while steps are explained [RES, AIR]. A paper swish on chapter cards, a soft chime
  on a key point; no click sounds and no whooshes on every cut [CLU] (`sfx.gain_db` -20).

## Look
- `look`: true to life, a touch of contrast; shots matched with `letitedit_match_shots`. Ink, paper, teal and amber
  for graphics; Plus Jakarta Sans for titles, Inter for text. Vertical phone footage sits on a blurred fill
  (`blur_pad`).

## Avoid
- Zooms on every click, flashy transitions, stock "subscribe" animations [AIR, CLU].
- Labels that repeat the narration word for word; a pointer and a label fighting for the same spot.
- Music under the instruction; a result that is only described, never shown.
