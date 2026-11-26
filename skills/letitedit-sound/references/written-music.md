# Writing a score for `letitedit_music_write`

Adapted from anidoodle's `references/music/compose.md` by Alex Greenshpun (Apache-2.0; changed for letitedit:
a score is JSON and goes through one tool; the recorded-instrument and film parts are out, the word and cut parts are ours).

Evidence tags: **[ANI]** the author's own rules, some citing music psychology, not proved by us. **[OURS]** local practice.
Numerical checks cannot settle musical quality; only
an ear says it's right.

A style gives you sound, groove families, a harmony language, melody rules and an arrangement grammar. It never gives notes.
You write every note: voicings, bass lines, motifs, the form. Missing material is an error that says what to write. [ANI]

**Never copy the engine's own pieces.** The novelty check fails a score too close to one, or a quoted 6-note fragment or
8-note melody shape in any key. Idioms are fine (a ii-V-I, a two-chord vamp). If it fails, change what it points at (the lead's
rhythm, contour, groove, form); changing the key fixes nothing. [ANI]

## The score

```json
{
  "style": "lofiElectronic", "title": "for this video", "seed": 7, "mood": "hopeful",
  "bpm": 89.2, "key": "G", "mode": "major", "meter": "4/4",
  "moodControls": {"energy": 0.45, "warmth": 0.6, "brightness": 0.6, "tension": 0.3, "space": 0.7},
  "swing": 0.53, "dyn": [0.55, 0.65], "tail": 0,
  "voices": {"lead": "mallet"},
  "levels": {"lead": 3, "chords": -4},
  "chords": {
    "G": {"voicing": "[A3 B3 D4 F#4]", "bass": "G2:1 r:.5 D3:.5 G2:.5 r:.5 B2:1"},
    "C": {"voicing": "[E3 G3 B3 D4]", "bass": "C3:1.5 G2:.5 r:.5 C3:.5 E3:1"}
  },
  "motifs": {"rest": "r:4", "m1": "r:2.6 B4:.35 D5:.35 r:.7", "m2": "r:.7 D5:.35 E5:.35 r:2.6"},
  "grooves": {"main": {"family": "pulse", "density": 0.4, "variation": 0.3}, "half": {"family": "halfTime", "density": 0.3}},
  "sections": [
    {"kind": "intro", "bars": 2, "harmony": ["G", "C"], "lead": ["rest", "m1"], "chordVel": 0.8, "energy": 0.5},
    {"kind": "groove", "bars": 2, "harmony": ["G", "C"], "lead": ["m2", "m1"], "groove": "main", "energy": 0.5},
    {"kind": "outro", "bars": 1, "harmony": ["G"], "lead": ["rest"], "energy": 0.4}
  ]
}
```

- **Mood controls** (0-1, 0.5 = as calibrated) change the sound only: `energy` density and drums, `warmth` darker filters and
  tape, `brightness` open filters and hats, `tension` pad detune and shorter decays, `space` reverb.
- **Section kinds** decide which layers may sound (`mode='vocab'` lists them); lines sound only where you write them.
- **`energy`** per section (0-1, 0.5 = as written) scales every part, about -5 to +3 dB, and generated groove density.
- **`harmony`**: chord names per bar, cycled. `"A B"` splits a bar on the meter's strong division, `"A:1 B:3"` by beats, `"~"` holds
  the chord over the bar line with no restrike. `comp` gives the chords a rhythm: `"x:1 r:.5 x:.5 r:2"`.
- **Lines play once** from the section's first bar; `loopLines: true` repeats them; `repeat: n` replays the section; `stretch: true`
  marks the section `fit` repeats or drops. A section can set its own `key` and `mode`.
- **Notation:** `NOTE:BEATS[@VEL]`, `[NOTE NOTE]:BEATS`, `r:BEATS`, bars separated by `|` or given as list items; every bar must
  add up, the last one too. In 6/8, 9/8 and 12/8 a beat is a dotted quarter, so an eighth is `1/3`.
- **Voices:** `voices: {lead: "<alternate>"}` swaps a slot for one the style lists, or `{inst, role, gainDb}` is your own (roles:
  chords and arp `accomp`, lead `melody`, counter `color`, bass `bass`, drum lanes `drum`). `levels` and `gainDb` are dB offsets
  from the slot's calibrated level, so leave them out until `stems` says otherwise.
- **Written drums:** a groove can be notation per lane (`kick`, `snare`, `ghost`, `hat`, `perc`; write the pitch as `C4`) instead of a
  family.

## The order of work

1. **Numbers from the brief.** Length, the feeling in the person's words, and the 2-4 moments that matter from the sound map: the
   line the music answers, the lift, the last word.
2. **One style, one mood.** `mode='vocab'`, then `mode='vocab', style=<id>` for its language. Tempo and mode are the strongest mood
   cues; several cues pointing the same way make it unmistakable. [ANI]
3. **The grid.** `mode='grid', project=..., anchors=[the moments], bpm_range=[the style's tempos], meter=...`. It gives the tempo and,
   per bar, what is said and which beats are free of words. Use the returned bar grid rather than reconstructing it by hand. [OURS]
4. **The arc before any chord.** One number per section: it rises, dips just before the peak, peaks on the key moment, releases.
   Decide the climax's bar and highest note, and the motif's rhythm and contour. [ANI]
5. **Harmony.** Write a progression for this video, in the style's language. Voices move by step and hold common tones, the bass
   owns the root, spread low and close high (no close intervals below about C3). Put home on the key moment; end inner sections
   open and save the full close for the end. [ANI]
6. **Motif.** 2-5 notes with their own rhythm: which beats does it avoid, where is the long note? One leap, then steps back.
   Develop it instead of copying it: sequence it a step higher, change the last interval, fragment it in a build, stretch it at
   the climax. The phrase's high point goes in its second half; phrases come in 2s and 4s; questions end open, answers land home.
   Chord tones on strong beats. [ANI]
7. **`mode='craft'`** reads the notes in about a second. Fix what you didn't choose; keep what you chose and say so. Then render.

| `craft` says | Usual fix [ANI] |
|---|---|
| leaps keep going the same way | turn back by step after a leap |
| nothing comes back, or exact copies | develop one motif |
| phrases don't end on chord tones | land answers on 1, 3 or 5; keep one open question |
| the melody peaks early | move the highest note to the second half, on the key moment |
| close intervals below their limit | spread the voicing |
| melody under the chords | voice the chords lower, or the melody higher |
| flat tension curve, no release | change layers, `energy`, register and harmony by section |
| mood cues | move the cue toward the mood, or declare the mood you wrote |

| `check` fails on | What to change [ANI] |
|---|---|
| masking (the melody isn't heard) | raise the lead (up to the headroom it reports), or lower or thin what sits in its register; this wins over stems |
| stems (a part over 3 dB off) | `levels` for that part, by the dB it prints |
| ghost (formless, sustained, too few notes) | a rhythmic layer or motif, shorter tails, a cadence |
| reverb | less `space`, or lower sends |
| key | the bass on the tonic at section starts and cadences; state the mode's colour note |
| master short of target | stagger the bass under that downbeat, roll the chord, soften the one loudest hit, at the bar it names |

## Writing for the cut (letitedit-sound section 2a)
Read this whole file before the first score: these rules, then the format, the order of work, what to do about each check.
- **The grid first, before any note** (dialogue-led, about a second): `mode='grid'` with the moments that matter gives the tempo and, per
  bar, the beats free of words. Line up the 2-4 moments that matter, not every cut (section 4). A montage goes the other way: write
  the score, then cut picture to the `bars` the reply gives; there the music leads, and the lead may play throughout. Check: the
  lead's rests and notes come from `free_beats`, not from a guess. [OURS; heuristic]
- **Keep a melody, in the gaps.** Short phrases of 2-4 notes in `free_beats`, with pad and bass carrying the line under words. Where the speaker
  talks almost without a pause, use fewer notes and longer ones, and the seconds before the first word and after the last: fewer, not none.
  A failed masking check or notes over words is never a reason to delete the lead: move the notes, raise `levels.lead`, thin what sits
  in its register. Keep a melodic line in the gaps rather than reducing the score to chords and drums alone. Check: `melody_vs_words.lead_notes` above 0 and `over_words` small; a note over a word is a choice you can name.
  [OURS]
- **A lift that really lifts.** Take parts away in the bar or two before it (a `half` or `breath` kind, lower `energy`), then bring
  them back with `energy` near 0.75 and the highest note on it. Pass `payoff`; aim for `lift.over_two_bars_before_db` of 4 or more.
  Move the arrangement, not `levels`: raising levels can break the balance and move the loudest section.
- **Something sounds in the first bar, or the music starts later.** Do not leave the opening bar inaudible.  `first_bar_vs_median_db` no lower than about -8. [OURS; heuristic]
- **End on the last word.** Home chord on the downbeat where the last word falls, the motif's last word after it, then ring. The film
  needs about a second after the word for that. The tool fades what rings after the last note, so the ending needs space after the last note: a bass line of eighths running to the end leaves no room, so hold the outro's `bass`
  or stop it on beat 1. Check: `end.fade_s` near 1 (or a button you meant), `end.notes_past_end` 0, `end.silent_after_s` near 0. [ANI; OURS]
- **Level: start `{op: score, levels: {talk: -14}}`.** For a written score, start about 14 LU under the voice; it occupies more of the speech band than a library bed. If words get harder to follow, go to -16 and lower `chords` before touching the lead. Check:
  `letitedit_check_audio(stems=True)`. [OURS]
- **Rounds.** Draft, `craft`, render; at most two revisions after that. A score goes on the timeline once its check passes; if a note or the
  round limit leaves one failing, say so in your message, with which check. [OURS] Stop once the check passes and the lift, opening and ending
  read as above. Advisory findings you chose stay. If a revision makes a passing score fail, go back to the passing one (`base`).
- **Plain notes.** Act on the note and don't ask back: take the likeliest reading, change it, say what you did; Undo and another note are
  there if it's wrong. Change only what the note asks, with `base: 'last'` and `changes`; the reply's `revision.parts_same` proves the rest
  stayed note for note. Replace the clip with `delete` and `place` in one `timeline_apply` (one Undo). Say what changed.

  | Note | Lines to change |
  |---|---|
  | "less piano", "less of that lead" | `levels.<slot>` down 3-6 dB, or that part's line to rests in some sections, or `voices.<slot>` to an alternate |
  | "more hopeful" | `moodControls.brightness` and `energy` up, the lead higher, major or lydian colour in the chords; `mode` if that isn't enough |
  | "end it sooner" | fewer bars in the sections before the outro, and the `length` |
  | "too busy" | groove `density` down, drop `counter` or `arp` in the talk sections |
  | "too sleepy", "more energy" | `bpm` (re-run the grid), section `energy`, a groove family with more drive |
  | "wrong feel" | a different style; that is a new score, not a revision |

- **When the picture changes,** the bars no longer fit: re-run the grid and change `bpm` and `length`, or the sections' bars.
- **Say plainly that you can't hear it.** Report the checks and that nobody has listened. Nothing is owed per video; note the reply's
  `licence` on the file like any other track.
