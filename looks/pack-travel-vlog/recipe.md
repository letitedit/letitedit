# Travel vlog: the recipe

A 16:9 YouTube vlog (5-20 min) of a trip or a few days on the road, told as a story: the world and its problem, the
pursuit, the resolution and a moment of reflection [VLP]. Talking parts (to camera, in the car, at the table)
alternate with montages cut to music that let the place breathe; day cards and place tags keep the viewer oriented.
The story and travel-event playbooks in letitedit-modes come first: one subject, real stakes, real order, nothing
staged. Evidence tags are explained in letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-travel-vlog}`; the look on every footage track; `blur_pad` on each vertical phone clip (a
clip effect: on a whole track it squeezes wide shots into the tall panel too); `{op: add_track, name: B-roll, kind:
video}` right after the cut; `{op: fx}` per part; `{op: split_edit}` for J and L cuts; `letitedit_soundtrack` per
montage; `{op: score}`; `letitedit_bin` for `chapter:` markers; `letitedit_hooks` + `{op: hook}`; `letitedit_map` for
a route.

## Structure (three acts) [VLP]
1. Cold open (a few seconds to 30 s): the trip's problem or its best moment, before any introduction [AVE]; the first
   5 s must be worth staying for [VLP]. Then `title`.
2. Act 1, the world and the problem: where we are (`place_tag`, an `establishing_push` on a wide), what's wrong or
   what we want.
3. Act 2, the pursuit: each day opens on a `day_card` (true dates from the footage) and a chapter marker; talking
   parts carry the story, montages carry the place and the passing of time.
4. Act 3, the resolution and a reflection: the outcome, then a quiet line or a view. The end screen, if any, in the
   last 5-20 s [AVE].

## Pacing
- Events set the pace, not a clock [AVE]; jump cuts on a breath or a phrase break [VLP] (`editing.max_pause` 0.5).
- Something visually new at least every 30 s [VLP]; early on every 10-20 s [AIR] - new shots, not effects.
- B-roll in sequences of 3-5 shots of one action or place [AVE]; establishing wides held long enough to read where we
  are [AVE].
- J and L cuts carry a voice or the place's sound across a change of place [AVE] (`{op: split_edit}`).

## Montages (music first) [VLP]
- Pick the song first (`letitedit_soundtrack`), then cut the montage to its bars; music leads (montage level), the
  place's own sound stays under it [AVE]. Use `whip` (a whoosh on a fast cut) or `time_dissolve` between places.
- Speed-ups of a drive or a setup (`speed` 4-8x) compress dead time [VLP time-lapse].

## On screen
- `title` once after the cold open; `day_card` per day; `place_tag` per new place (real names only); `name_tag` at
  each person's first appearance; `aside` (a handwritten line) two or three times a video at most.
- `map` only for a long move between places, from the clips' GPS, and never an exact home or camp location the
  person hasn't chosen to share.
- Captions as an SRT; burned in only when the brief asks (bottom, two lines of 42 characters) [HED].

## Sound
- Voices first; music about 22 dB under talk and ducked [AVE], up in montages. The place's sound (wind, waves, the
  engine, a market) low under b-roll and up where it tells the place [AVE]. Effect sounds rare: a soft whoosh on
  whips and titles, a pin on place tags (`sfx.gain_db` -18).

## Look
- `look`: warm and natural, a little more colour than the camera gave [EDS casual vlog]. Outfit for titles and
  tags, Caveat for day cards and asides.

## Avoid
- A channel intro or "hey guys" before the cold open; a long title sequence.
- Montages without a song picked first; music wall to wall under talk.
- Invented places, dates or GPS; exact private locations.
