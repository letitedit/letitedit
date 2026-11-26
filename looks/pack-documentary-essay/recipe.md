# Documentary: the recipe

A 16:9 YouTube film (4-30 min) about something that really happened, told like a short documentary or a video essay:
a quiet cold open, a serif title, dates and places as typewriter cards, names at first appearance, long holds and
slow pushes, a muted filmic look, music that changes scene by scene and one real silence. The documentary playbook in
letitedit-modes is the strongest-evidenced mode and comes first: find the story in the footage, care before
jeopardy, keep the complications, never change what a real person meant. Evidence tags are explained in
letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-documentary-essay}`; the look on the footage tracks (`{op: track, name: <track>,
effects: <look.effects>}`); `{op: fx}`; `letitedit_soundtrack` per act (protect `drop_out` for the silence);
`letitedit_hooks` + `{op: hook}`; `letitedit_bin` for `chapter:` markers.
Make the B-roll track right after the cut, before the captions (`{op: add_track, name: B-roll, kind: video}`): a B-roll track made later draws over the captions in a render.

## Structure
1. Cold open (10-60 s): pick the template for the feel [modes] -
   contemplative: three to five wordless shots of 3-5 s, natural sound first, music later, the first line only once
   the place is set; or urgent: time, place and stakes in one breath. Withhold the outcome, never the premise.
2. Title: `act_title` on black with one low hit (or in silence).
3. Acts, each a scene with one purpose [modes]: the life before the trouble, the trouble, the attempts (keep the
   real complications), the turn, the outcome. A date or place card where time or place changes; an act title for
   a long jump.
4. The end: a short line or an image that lands, the music resolving, out. An open ending is allowed when life is
   unresolved [modes].

## Pacing
- Mostly slow gears: holds after a line that lands and on faces [modes]; `slow_push` (106% over 4 s) on held shots,
  stills and wides. Faster only toward a revelation [EDU], then a held beat after it.
- Keep the speaker's rhythm and breaths (`editing.max_pause` 0.7); a cut on every sentence makes it anxious [UMB].
- Early on, the picture still changes every 10-20 s [AIR] - new shots, not effects.

## On screen (sparse)
- `date_card` (typewriter type, lower left) where the viewer needs to know when or where; always in time order.
- `name_tag` (a lower third) at each person's first appearance [modes].
- `key_phrase` two or three times a film at most, the speaker's exact words, in serif italic [EDU, modes].
- `act_title` for the title and long jumps; `time_dissolve` (0.8 s) where time passes, hard cuts elsewhere [modes].
- Source cards (a document, a photo, an archive clip) name where they come from and the year [UMB]; `photo_click`
  only on a still.

## Sound and music
- Natural sound first, layered in at the start [modes]; sound effects punctuate real actions (a door, a tool)
  rather than decorating cuts [EDU].
- Music per scene: a different piece per act, low under talk (-22 dB), up where pictures carry the scene; off for
  a scene that carries itself; one real silence before the turn (`tension_bed` under it at most) [modes, UMB].

## Look
- `look`: muted (saturation x0.8), cooler shadows and warmer highlights, light grain, a soft vignette [EDU].
  Cormorant Garamond for titles, IBM Plex Mono for dates and places, bone and gold on black.
- Captions as an SRT; burned in only when the brief asks (small, bottom).

## Avoid
- Wall-to-wall music, the same reveal treatment twice in a row, hits on every card [modes].
- A fact-dump or "Hi, my name is" opening [ITE]; the ending shown first.
- Any cheat (audio from another moment, a reaction moved) without the person's OK [modes].
