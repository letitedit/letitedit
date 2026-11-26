# Aesthetic day-in-the-life: the recipe

A vertical diary of one day (30-60 s): small moments in time order - waking up, coffee, the drive, a job, the
evening - mostly b-roll, with short lowercase notes, the time of day, the day's own sounds and a soft bed of music. It
should feel calm and lived-in, never busy. The vlog and travel-event playbooks in letitedit-modes come first (one day,
real order, the person's real life; nothing staged or invented). Evidence tags are explained in letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-day-in-the-life}`; the look on every footage track; `{op: add_track, name: B-roll, kind:
video}` before any captions; one `{op: fx}` batch per part of the day; `{op: popups}` for the cosy words;
`{op: score}` for the music.

## Structure
1. The opening (0-3 s): the prettiest moving moment with one lowercase line that says what this is ("a slow morning
   at home"). No greeting.
2. The day in parts, in time order: each part opens with a time stamp and holds two to four shots of 2-4 s [HOL].
   A part may carry one short line of talk or voice-over; the rest is pictures and their sound (about 70% b-roll
   [HOL]).
3. The end: the evening or goodnight shot held a little longer, a last note, the music resolving.

## Pacing
- Shots of 2-4 s; never cut every half second (it reads anxious, not calm) [HOL]. The whole thing 30-60 s; 90 s at
  most [HOL].
- Either a gentle push-in (`soft_push`) or a still frame - hold still when a move adds nothing [HOL].
- Talk keeps its pauses (`editing.max_pause` 0.6); this style is about breathing room.

## On screen
- `time_stamp` when the hour or the place changes: the camera's recorded time when the footage has one (lowercase,
  "7:40 am"), else a word ("morning"). Never invent a time.
- `note`: one short lowercase line per moment at most, five words or fewer, written like a diary; it adds a feeling or
  a fact the picture doesn't show and never repeats the voice.
- `tiny_sticker` and the pop-ups: a small emoji for a cosy detail, one at a time, soft.
- Captions for a voice-over only: calm sentence captions (two short lines, no outline, a soft shadow) [BLZ].
- `soft_cut` (0.4 s dissolve) only where time passes; hard cuts inside a part.

## Sound
- The day's own sounds first: the kettle, the dog, the road, a door - keep them audible under the music. Effect
  sounds are rare and soft (`sfx.gain_db` -18): a soft pop for a sticker, a shutter on a held frame, a sparkle at the
  end.
- Music: one soft bed (lo-fi, acoustic or dreamy) at about 60-70% under a voice or the day's sounds [HOL], up in the
  wordless parts; it fades out with the last shot.

## Look
- `look`: soft and warm - lifted shadows, gently desaturated, a little golden, a faint grain [HOL]. Cream, peach and
  sage for anything drawn; Instrument Serif italic for notes, DM Mono for times, Quicksand for captions.

## Avoid
- Loud sounds, flashes, shakes, whooshes on every cut, big text.
- Invented times or moments; a note on every shot.
- Strangers' faces as the subject; a face where a note or sticker sits.
