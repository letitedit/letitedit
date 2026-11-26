# Cinematic travel: the recipe

A vertical travel film (15-40 s) with no talking: moving shots of a place, cut to one song, inside letterbox bars,
with a filmic grade, a little slow motion, one title and small place names in a corner. It should feel like the
opening of a film about the place, not like a list of clips. The montage rules in letitedit-modes
(montage-transformation and travel-event) come first: build the music first, an arc that rises and settles, held
shots as well as quick ones, a resolving end. Evidence tags are explained in letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-cinematic-travel}`; the look on every footage track (`{op: track, name: <track>, effects:
<look.effects>}`); `letitedit_soundtrack` for the song's bars and lifts; one `{op: fx}` batch with `bars` first;
`letitedit_hooks` + `{op: hook}` when the footage has picture facts.

## 1. The song first
- One song the person may publish: the CC0 library (`music-library`: Cinematic / Adventure, Ambient / Dreamy,
  Acoustic / Calm). `letitedit_soundtrack(song=..., mode='song')` gives its bars, phrase starts and lifts.
- Choose a stretch that fits the length and has a lift (where the music opens up) about two-thirds in. Put it on a
  `Music` track; it ends with the last shot (on its own ending or a held chord, faded over the last second).

## 2. The cut (slow-fast-slow)
- Open on a held wide or a slow camera move (3-4 s); quicker moving shots in the middle (1-2 s); settle on one long
  final wide (3-5 s) [EDS cinematic: slow-fast-slow]. Most cuts land every 1-4 s [CHP]; nothing held past about 5 s
  except the first and last shots [POW].
- Cut on motion and on the music's bars, not on every beat. Match movement across cuts (a pan right into a pan right,
  a car leaving frame into a road) [modes].
- Slow motion: a moving shot played at 0.5x (`speed: 0.5`; shot at 60 fps or more where possible) for the moment the
  place opens up [POW]. Speed changes are steps: split the shot and give each piece its speed, gently - travel ramps go
  down to 35-50% speed, not lower, and two or three per 30-60 s at most [SHB].
- Wide (16:9) shots on a vertical frame: fill the frame (`{zoom: z, focus: [x, y]}` on the clip, onto the subject);
  never leave a 16:9 strip floating between black.
- Use footage without people's faces where you can; a person seen from behind or far away suits the style.

## 3. On screen (one fx batch, `bars` first)
- `bars`: at 0 for the whole picture (each bar a tenth of the frame height; ratio 2.39 on a wide frame) [POW, HOL].
- `title`: once, over the first striking shot - the place or the theme in two or three words, a small spaced line
  under it (the place, the season, the trip) [POW]. A quiet last line on the final wide is allowed.
- `place_tag`: where the place changes, in a top corner under the bar; real names only (from the person, the
  footage's GPS or the brief); no tag when the place is unknown [POW].
- `slow_push` on still wides and details; `air_cut` on two or three motion-matched cuts [SHB]; `time_dissolve` only
  where time or place changes; `light_leak` into the sunset or the best shot; `swell_reveal` ending on the reveal.
- Captions: none unless someone talks; a voice-over gets the small calm captions in `graphics.word_captions`.

## 4. Sound
- The song leads (full level). Keep the footage's own sound under it, 12-18 dB down, and bring up one real sound
  where it tells the place (waves, wind, a door, the engine) [AVE: the place's sound low under b-roll].
- Effect sounds are soft and few: a cinematic hit on the title, air whooshes on matched cuts, a reverse swell into the
  reveal (`sfx.gain_db` -12).

## 5. Look
- `look`: a little desaturated, cooler shadows and warmer highlights, light grain, a soft vignette [EDS, POW, HOL]. Apply
  it to every footage track; match shots first if their colour differs a lot (`letitedit_match_shots`).
- Bodoni Moda italic for the title, Josefin Sans spaced capitals for places; cream and sand on black.

## 6. Hook and ending
- Frame 0 is the most striking moving shot, the title fading in, the song's first hit under it [JH: a picture that
  works muted]. No logo, no black, no slow fade from black.
- End on a held wide with the music resolving; cut on the last chord or fade the last half second. No outro card.

## Avoid
- A cut on every beat; flashy transitions (spins, glitches, shakes); text in the middle of a view.
- Speed ramps faster or slower than the style's range; slow motion on shots that had no motion.
- Invented place names; faces of strangers as the main subject.
