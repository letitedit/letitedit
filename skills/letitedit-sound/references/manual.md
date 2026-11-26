# letitedit-sound: the evidence and the tools' details behind the checklist

Read the part you need. Every rule is in SKILL.md; this file holds the reasons, the evidence and the
tools' details behind some of them.

## The evidence

Evidence: the music craft is mostly one teacher (Inside The Edit, one voice) plus feature editors (Art of the Cut);
every number is a default to tune.

## 2. Where the music comes from

- **No howls or whistles under speech.** A held, pure, narrow tone (a whistle-like or theremin-like lead, a whine, a feedback
  howl) sits where the ear is most sensitive and cuts through talk even when the music is quiet. The library search leaves out
  songs that carry long stretches of one (`whistle_tones_hidden` counts them; `with_whistle_tones=True` lists them, each line says
  how much), and a section picked from any other song can still hold one. `letitedit_check_audio` and the export's checks name the
  stretches (`tones`: seconds, pitch, how far the tone stands above what is around it). When one is named, pick another section
  or song, unless the Look or the person asks for that sound. Ordinary played or sung notes carry harmonics and do not trip it.
  [Acoustic feedback detection: van Waterschoot and Moonen, Proc. IEEE 2011; the narrow-peak, no-harmonics, persistent tests]

## 4. Duet: music and speech take turns

- **Depth:** music about 18 LU under the voice (`talk` -18; Add music's Medium measured 18.4-18.8 LU), the dip done
  before the first word, back up only in the gaps it answers; taste moves it a few LU. The library has no number
  (its one figure: ambience about -18 under lines in one rough mix). Check: `letitedit_check_audio(stems=True)` and a
  listen [OURS; ITE gwyneGrX9Jw 16:28].
- **The shipped defaults keep music dipped through every gap under 4 s** (`merge_gap`, in score, soundtrack and Add
  music), so a line isn't answered unless you choose it. For each chosen gap use `{op: score, answer: [...]}`: a pause
  id from the score's result (`gaps`; a dry run lists them), a time, or the line it follows (`{after: 'and then it
  quit on me'}`); the music rises after the last word and is back down before the next, with ramps scaled to the
  pause. `answer: 'auto'` picks pauses of 2 s or more after a sentence, 20 s apart. On a soundtrack-built track, use
  its sections and hits instead. Keep `merge_gap` at 4 s: lower values swell in every ordinary pause [OURS]. Answer sparingly: keep answers to the few gaps after key lines and prefer a smaller rise (`levels: {swell: -8}`, about 10 dB
  over `talk`) unless the scene is music-forward. Check: answered pauses rise and are back down before the next word
  (`letitedit_timing(project, view='sync')` lists each gap's rise in dB); music under the words stays flat [OURS; GEN].

## 6. Hits and stingers

- **Measure sync, don't guess it:** `letitedit_timing(project, view='sync')` gives every cut's, motion peak's and
  text pop's offset in frames from the nearest beat and downbeat, the on-beat share against chance, monotony, and
  song sections against story sections. In music-led stretches aim most picture events within about a frame after
  the beat (a viewer preferred on-beat cuts 3 to 1) [OURS]; read `beat_confidence` first (weak on
  ambient or busy tracks). Take the easy sync points: where the music returns after a gap or a break, cut to the next
  shot on that return [OURS].

## 7. Natural and protected sound

- **Protect what carries meaning:** the brief's `protected` ranges, `must_keep` sound moments, a punchline and the
  laugh after it, a proving sound. Pass each as a timeline range to soundtrack `protect` (`duck_deep`: music 20 dB
  under the natural sound; `drop_out`: the music leaves and returns), or a `score` zone at `quiet` (-24). Never a
  music peak on it. Check: soundtrack's measure gives the level in each protected range; listen to each one
  [ITE KAO0n3C0kAg 11:33; AOTC Porcelain].
  The voice clean-up (`letitedit_fix` voice) decides per clip from the gaps between its words: its default,
  `separate: auto`, uses `separate: true` where a sound plays there (the sound keeps its level) and the whole mix, which takes
  every sound but speech 11-18 dB down, where only talk and room do. Nobody asks the person and no one setting serves all
  clips. You override (`separate: true` or `false`, which always wins) when the story says otherwise: a steady hum or fan
  the story is about, or ambience the brief protects, stays; a sound that is only noise goes. The result states what `auto`
  chose and the numbers; a clip that only talks about a machine isn't a clip where the machine plays. Say which clips were
  protected (details, numbers and the limit: letitedit-finish FINISH-2).
- **Montage with nobody talking:** the shots' own sound stays under the music, up for key actions (Add music plays the
  music 4/8/12 dB over it at Low/Medium/High). In action, close shots favour detail sound, wides let the score swell.
  Check: listen to the key actions; each is heard over the music [OURS; AOTC MI].
- **`score` finds speech by word times** (cached transcripts; the voice detector only for files with none, and the
  result says which: `speech_from`, a warning), so transcribe the footage first (`letitedit_words`); the detector
  missed quiet narration under work noise and left music up under it [OURS]. Tracks named sfx, sound, foley or ambience (and music, song,
  score, bed), and clips from the sound-effect or music library on any track, are never treated as speech by score
  or captions: name tracks for what they carry [OURS].

## Choose the function before the timbre

| An object or graphic appears | Short pop at its arrival | Editorial heuristic, weak; action/mood matching is published practice [SFX5] |
| Waiting or time passing | Clock ticking rather than an alarm | Editorial heuristic, weak; source identity supported [SFX6] |
These sources document editorial conventions and available categories, not a statistical ranking or proof of
audience impact. Start with the few events that need a cue; leave speech intelligible and check the sound against
the actual action. A generated flash effect is a designed cue, not evidence of an authentic historical recording.

## Every effect sound, on its purpose

**Keep every effect sound on its purpose.** Name the visible arrival, caption word, cut, transition midpoint or story
moment it belongs to. Keep the `sound_target` record the tools supply (kind, item id or word, intended timeline time);
an explicit target can be passed in an `fx` item. The reply gives each sound's offset; correct an `off_target` result
before export. A source's loudest 10 ms window, mapped through its trim and speed, must be within **125 ms either
way** of that target. Aim for the target frame, not the tolerance edge. A caption's arrival is its first visible
export frame: fade/reveal, source offset, trim and grouped captions can make it different from a word's speech time.
After moving the picture, check again: the recorded identity is resolved on the current timeline; it does not move
the sound itself. A missing or unreadable target is not a pass. Older unrecorded sounds try their own `-sfx` graphic,
then a picture/caption event within half a second; confirm what that inferred target actually is.
For a **whoosh or riser**, put the build-up before its target so its **peak** lands on the cut, transition midpoint
or reveal. The tail can continue beyond it: neither the file start nor the end of the decay is the hit. This uses
Zero-G's *Whoosh Designer User Manual*, "PEAK TIME controls" (p. 6), which times the attack to land the peak on a beat,
and Deus.Video's *How to sync sound effects with video*, "Choose a visible sync point", which describes whoosh
midpoints and rising sounds ending at reveals. Sources: https://zg-product-materials.s3.amazonaws.com/timespace-store/pdf/Whoosh_Designer_Manual-1488815361189.pdf
and https://deus.video/resources/sync-sound-effects-with-video/ . The tool's peak measurement is a repeatable timing
check, not an ear judgment of the effect's character. Listen to the rendered cue and its tail as well.

## 9. Loudness by deliverable (the one table)

- **Even the speech first** (`score` levels it clip by clip, and inside a clip a phrase 6 dB or more off the rest, such
  as a second voice or a line said much more softly, gets its own level with the gain moving in the gap before it;
  `{op: level}` does only that). Don't ride levels line by line with range measurements after it: read its
  `speech_levelled` changes, and set a phrase back by hand only where the softness is the performance (a whisper, an
  aside), saying so in `finish_pass.md` [OURS]. **Master once**, on the
  whole mix, at export: `letitedit_export(..., loudness=<target>, true_peak=-1)`; never per clip, and no dynamic
  normaliser on the master (it lifts quiet stretches and flattens the music's shape; a limiter is fine) [OURS; GEN].
- Check before export: `letitedit_check_audio` (speech clips near their typical level, no music spike in wordless
  stretches, no sudden dips). It keeps its measurement with the cut's sound: asked again on an unchanged cut, it returns
  the same numbers with no new render. An export of a cut it hasn't measured as a whole measures the mix itself from
  its own sound (`result.mix_check`), so the measurement the review reads is of the cut handed over; there is no need
  to measure again after the last export unless the cut changed after it. After: `letitedit_measure(<file>)` loudness within tolerance, true peak <= -1 on the
  encoded file. Avoid speech swings, music spikes and unintended dips [OURS].

## 11. Tools

- `letitedit_music_write(mode, score | base + changes, project, length, start, payoff, anchors, ...)`: a score as JSON, every
  check, the file at the film's exact length and a ready insert (section 2a, references/written-music.md).
- `letitedit_soundtrack(project, song, sections, hits, protect, ending, entry, mode, plan_id, ...)`: one song arranged
  around the edit (cut on bar lines so hits land, section energy, dips under speech, protected ranges). `mode='song'`
  analyses; `'plan'` proposes (pieces, joins, each hit's error, a preview mp3: listen); `'apply'` with `plan_id`
  writes it as one undo step; `'measure'` renders stems (music under speech, protected levels, where hits landed).
  It plans from the saved file (save first) and replaces the clips on its track, Add music's included.
- `{op: score, zones, answer, levels, merge_gap, attack, release, end, level_voice}`: evens speech, then levels every Music
  track under it (defaults in section 4); it turns off a track's auto-duck. Score and soundtrack both write the
  music's gain keys: one of them per music track (score after soundtrack erases it); `{op: level}` suits either.

## 13. A song added when posting

A trending song gets its reach and its licence from the phone app's sound picker, so the video is cut to the song, the file
uploaded has none of it, and the person adds it when posting. A song from outside a platform's tools can draw a Content ID
claim or a removal [YT]. Tool: `letitedit_song`.
