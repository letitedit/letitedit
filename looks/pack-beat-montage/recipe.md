# Beat-synced montage: the recipe

A vertical Short (10-30 s) with no talking: one song and a run of moving shots cut to it. The music decides every
length; the picture rises with the build, hits hardest on the drop, and ends on the song's last hit. Speed changes
(slow into a moment, fast through it) give the "velocity" feel. The montage rules in letitedit-modes
(montage-transformation) come first: build the track first, an arc that rises and releases, cuts on bars and some
held shots - not a cut on every beat - and a resolving end. Evidence tags are explained in letitedit's `looks\SOURCES.md` (optional reading).

## 1. The song first
- One song the person may publish (the CC0 library in `music-library\library.csv`: Electronic / Energetic,
  Hip Hop & R&B, Synthwave). `letitedit_soundtrack(song=..., mode='song')` gives its tempo, bars, phrase starts,
  drops and ending.
- Choose a stretch with a build and a drop that fits the length (10-30 s): start on a downbeat [EDS: from beat one],
  end on a bar line at a phrase end or the song's own ending [modes]. Put it on a `Music` track, full level; a fade
  only on the last half second if the song doesn't end there.

## 2. The cut
- Shots chosen by motion and energy: things moving through the frame, camera moves, light. Log each with its peak
  moment [modes].
- Lengths in beats (at 120 BPM a beat is 0.5 s): the intro holds 2-4 beats a shot, the build 1-2 beats, the drop 1
  beat or less for a burst, then a release - a held shot of 2-4 beats before the end [modes: rise and release].
  Mix the patterns: bar cuts, a few cuts on instrument hits, some held shots [ITE: not every cut on the beat].
- Velocity: split a moving shot into pieces with `speed` (slow 0.5x into the moment, 2-3x through it, back to
  0.5-1x) so the change lands on a beat [UNV/GEN: tune on references]. Each piece is a clip item with its own `in`,
  `out` and `speed`; nothing faster than 4x.
- Match motion across cuts (a pan left into a pan left) [modes].

## 3. Effects (one fx batch, on the beat grid)
- `title_slam`: one or two words (the place, the theme) on the first downbeat; maybe again on the last.
- The drop: `drop_shake` + `beat_flash` together, the hit sound half a frame early [AOTC].
- Big downbeats in the chorus: `beat_flash` or `glitch_cut` (rotate; never both on one cut); `zoom_pulse` inside a
  held shot on alternate beats in the build.
- `riser_build` only when the song's own build is weak; `whoosh_cut` between two shots moving the same way.
- At most three flashes in any second [RES]; leave the bar before the drop quieter so the drop lands [modes].

## 4. Sound
- The song is the soundtrack. Footage sound off, except one real sound worth hearing (a door, an engine) under a
  hit [modes: let real sounds punch through]. Effect sounds sit under the music (`sfx.gain_db` -8).

## 5. Look
- `look`: cool and contrasty, deeper blacks, a soft vignette [EDS music video]. Apply it to every footage track.

## 6. Hook and ending
- Frame 0 is the most striking moving shot, on beat one, with the title word [JH: a picture that works muted].
  With no speech, `letitedit_hooks` offers picture moments only when picture facts are cached; otherwise pick the
  opening shot yourself and say why.
- End on the song's last hit or a hard cut on a final beat [EDS, ITE]; never a fade from mid-phrase.

## Avoid
- A cut on every single beat; one speed the whole way; flashes on every cut.
- Captions or talking-head footage (this style is wordless); text beyond one or two title words.
- Music that ends mid-phrase.
