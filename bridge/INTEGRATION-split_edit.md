# Integrating split edits (J/L cuts) and the score's duet (`answer`)

Written 2026-10-28. Nothing here is committed. Measured results: section 7 (render results in
`C:\LetItEdit\cache\split-edit-tests\results\split-edit-renders-final.json` and `score-renders-final.json`, made by
the final code; the other files there are earlier runs, superseded).

## 1. Files

| File | What changed |
|---|---|
| `bridge/split_edit.py` (new) | The split-edit op: geometry at a cut (frame-exact, as the compiler places clips), validation (handles, words, shape), `apply_op`, `refresh` (rebuilds every split edit after any edit), `listing`, the `split_mute` envelope keys. |
| `bridge/edit_script.py` | `split_mute` effect (a keyframed Gain/Volume filter marked `letitedit_ai:split_mute`, read back as `{split_mute: {tail or head, fade}}`, length-sensitive); the `split_edit` item record stored on the moved-sound clip (`letitedit_ai:split_edit`); `{op: split_edit}` dispatch; `edit()` runs split ops after the resync and calls `split_edit.refresh` before and after the late ops; `apply_changes(script=...)` refreshes a whole script sent back. Nothing changes for a timeline without split edits (refresh returns at once). |
| `bridge/op_specs.py` | `split_edit` in `OPS` (docs and checks: `_split_problems`); score's `answer` field and per-zone `attack`/`release` (`ZONE_KEYS`, `_answer_problems`). `letitedit_guide('ops')`, `letitedit_guide('split_edit')` and `letitedit_guide('score')` show them (guide_v2 reads op_specs). |
| `bridge/music.py` | Word-timed speech (`clip_speech`, used by `speech`, `level_voice` and therefore `score`, `level` and soundtrack's speech map), `speech_gaps`, `answers` (the duet), per-zone ramps in `curve`, new result fields. Backward compatible: without transcripts and without `answer` the gain keys are identical to before (tested against a copy of the old module). |
| `bridge/split_edit_measure.py` (new) | Render-and-measure helpers for the tests (melt renders, those over 30 s of timeline under the PC render lock as fix_post does, with a scaled timeout and one retry; ffmpeg decodes, alignment, click measure, loudness, source-frame match). Not a tool. |
| `bridge/tests/timeline/test_split_edit.py`, `bridge/tests/timeline/test_score_answer.py` (new) | Unit tests (generated media, fast) and render tests on real footage (see section 7). |

Not edited: letitedit_mcp.py, letitedit_ai.py, tool_docs_v2.py, GUIDE.md, GUIDE_V2.md, skills/, soundtrack.py,
caption_layout.py, music_gen.py, edit_sync.py, timeline_speech.py, live_edit.py, any C++.

## 2. `{op: split_edit}`

```
{op: split_edit, id: <incoming clip>, lead: s}                    J cut: id's sound starts s before its picture
{op: split_edit, id: <incoming clip>, lag: s}                     L cut: the clip before id is heard s under id's picture
{op: split_edit, id, lead | lag, move: picture}                   keep the sound cut, move the picture cut instead
{op: split_edit, id, lead: 0}                                     back to a straight cut
optional: fade (s, crossfade at the sound cut, default 0.1, at least 1 frame), track (default 'J/L cuts'),
          drop_words (true: allowed to cover words)
```

Why one op named `split_edit` and not `split` or `j_cut`/`l_cut`: in Shotcut (and every NLE) "split" means cutting
a clip in two at the playhead, so `{op: split}` would be read as that; one op with `lead`/`lag` covers both kinds,
switching one into the other and removing it (`lead: 0`), and `split_edit` is the term the research and the skills
use for both. `lead`/`lag` follow the audit's `audio_lead`/`audio_lag` without the unit suffix, like every other op
field (seconds).

How it is built (one undo step):
- **The moved sound** is a clip of the same file on an audio track (`J/L cuts`, added at the end when missing): a J
  cut plays B's source `[B.in - lead, B.in]` ending on the frame B's picture starts, after one silent frame (the
  engine ramps a gain from the previous frame's value to the frame's own, and a clip's first frame has no previous
  value, so a fade-in that started on it would jump; the silent frame makes the crossfade start exactly at the sound
  cut); an L cut plays A's source `[A.out, A.out + lag]` from the frame A's picture ends. Frame-exact: positions are computed the way
  `compile_script` places clips (`split_edit.frame_layout`), lengths are whole frames. Same file, same source time:
  the sound stays locked to its own picture and joins the clip's own sound without a seam (measured, section 7).
  It is named `J cut sound: <file>` / `L cut sound: <file>`, carries the source clip's static gain and audio filters
  (speech levelling follows it), and has id `<B>.lead` / `<B>.lag`.
- **The covered sound** (A's last `lead` seconds for J, B's first `lag` seconds for L) gets `{split_mute: {tail|head:
  s, fade: s}}`: a keyframed Gain/Volume (`audioGain`) filter, silent (-100 dB) over the covered part.
- **The crossover** at the sound cut is `fade` seconds of equal-power keys, one per frame, on both sides (the
  engine ramps the gain linearly inside each frame, `filter_volume.c`), inside the split region: J `[sound cut,
  sound cut + fade]`, L `[sound cut - fade, sound cut]`. Handles needed: `lead` + 1 frame (J), `lag` (L).
- A fade-in on B (J) or a fade-out on A (L) at the cut would now dip the continuing sound, so it is removed, with a note.
- **The record** `split_edit: {into, out_of, lead|lag, fade[, drop_words]}` lives on the moved-sound clip.

Validation (nothing is written when refused; the message names the most possible):
- B must follow a clip directly on a picture track (no gap, not first), no transition into B, both clips at normal
  speed and not reversed; the clip giving the sound must have sound and not be muted.
- `lead` <= B's file before its in point less a frame, and <= A's length less a frame (minus an L cut already
  using A's head); `lag` <= A's file after its out point and <= B's length (minus a J cut using B's tail). Shortest:
  2 frames.
- `move: picture`: J needs A's file after its out point (stills, colours and graphics can simply be longer) and B
  at least a frame longer than the lead; L needs B's file before its in point. The message gives both maxima.
- Words: the covered sound may not contain words (cached transcript; voice detector when there is none; a word
  counts when most of it, or 0.1 s or more of it, is covered: heard cut off) unless `drop_words: true`; the refusal
  names the words and the longest lead/lag that keeps them. After a later edit (a trim, tighten) a split edit that
  now covers words is kept and the note names them. The result also says
  which words the moved sound brings in and warns when it starts (J) or ends (L) inside a word, with the leads that
  take all of it or none of it.

After later edits (`split_edit.refresh`, run by every `edit()` and every whole-script apply):
- trims, ripples, inserts elsewhere, tighten (follows `from:` pieces): the moved sound and the mute are rebuilt at
  the new cut; a split that no longer fits its handles or clip lengths is shortened to the most that fits, with a
  note ("J cut into b shortened from 0.500 to 0.267 s: b's file has 0.300 s before its in point ..."); one with no
  room left is removed, with a note.
- A or B deleted, B moved, a clip put between them, a transition added, speed changed: the split edit is removed
  with a note naming why; its mute goes with it.
- `move: picture` is a roll: the other tracks keep their times (split ops run after the resync, so nothing is moved
  on the other tracks and no caption is dropped).
- Hand edits in the Shotcut window are picked up at the next tool edit. Deleting the moved-sound clip by hand
  deletes the split edit, but until the next tool edit the covered part stays silent (the mute is on the other clip).
- Captions from speech and score see the moved sound (the `J/L cuts` name is not a music/sfx name). Covered words are
  refused by default, so captions never show words nobody hears; with `drop_words: true` the covered words still come
  from `timeline_speech.timeline_words` (it does not read `split_mute`): see 6.3.

Undo:
- File: `apply_changes` keeps the history copy as for every op; `letitedit_timeline_undo` restores the file byte for
  byte (tested on every render case and in the unit tests).
- Open window (described, not tested in a running window): `timeline_tools.apply_project` -> `live_edit.apply` ->
  `es.edit` (split op + refresh) -> compiled against the snapshot; when the `J/L cuts` track is new the change goes
  in through the app's `apply_transaction` (add_tracks: the new audio track, which `live_edit._shape` accepts after
  the existing audio tracks), otherwise `replace_tracks` with the main track (the mute) and the J/L track: one call,
  so one native undo step either way, labelled like other applies. Tested by running `live_edit.apply` with a
  stand-in for the app's bridge (`test_live_window_path_is_one_native_step`): the first split edit sent one
  `apply_transaction` (add_tracks `[{name: 'J/L cuts', kind: audio}]`, tracks V1 and J/L cuts, the label, the
  expected revision), the second one `replace_tracks` (V1 and J/L cuts). What the app then does with them is its
  existing code, not exercised here.
- Media offline (a drive not mounted): `refresh` changes nothing and says so, instead of dropping split edits whose
  files it can't read; a new split edit on missing media is refused.

## 3. Score

- **Speech from words** (`music.clip_speech`): a file with a cached transcript talks where its words are (each word
  from 0.1 s before its start to 0.15 s after its end, joined across gaps under 0.25 s, a word's talk capped at
  1.5 s because the recogniser stretches words over the hesitation after them). A file without one falls back to
  the voice detector, and the result warns, naming the files (`speech_from: {words, voice_detector}`, `warning`).
  Used by score, `{op: level}` and soundtrack (soundtrack calls `music.speech`; its 31 tests still pass).
- **answer** (the duet): `answer: ['g4', 63.2, 'the phrase the pause follows', {after, near, gap, at, level,
  attack, release}]` or `'auto'` / `{auto: {min_pause 2, spacing 20, sentence true, max_per_minute 3}}`. The result
  always lists the pauses (`gaps: ['g2 0:12.8-0:14.3 (1.45 s up, pause 1.70 s) after "...holding this thing on."',
  ...]`, ids stable for a given timeline), so a dry run shows what can be answered. Each answered pause rises from
  0.15 s after the last word to 0.1 s before the next (the word pads), at `swell` by default, with its own ramps:
  rise `min(release, pause/3)`, fall `min(attack, pause/4)`, scaled down if they would overlap. Pauses under about
  1 s (0.75 s between the pads) are refused ("widen it with picture first"), unknown ids/phrases are refused with the
  pauses nearby, answers closer than 8 s get a pumping note.
- **Zones** may carry their own `attack`/`release`.
- **merge_gap**: kept at 4 s. Evidence in section 7.4.

## 4. Hits half a frame early (not edited: described)

Where music hits are placed on picture cuts:
1. **soundtrack.py** (another agent): `hits[].at` is a timeline time the model gives; there is no `on_cut`. Add
   `hits[].on_cut: true` in `_parse_hits` meaning "this hit sits on a picture cut": `at -= 0.5 / fps` before
   planning (the plan knows `ctx['fps']`), keep `name`, and report `cut_s` and `lands_at - cut_s` (should be about
   -0.5 frame) per hit, so the skill can write `{at: <cut>, kind: drop, on_cut: true}` instead of subtracting.
2. **music_gen.py** (`letitedit_music_make`, `cuts=` / `cuts='project'`): `hits += [[c, cuts_on] for c in cuts]` puts
   the downbeat on the cut. Change to
   ```python
   cut_fps = float(proj['fps']) if proj else 30.0
   early = 0.5 / cut_fps          # a hard hit on a cut lands half a frame early so it reads as on the cut (AOTC Dune L82)
   if cuts and cuts_on != 'none':
       hits += [[round(c - early, 4), cuts_on] for c in cuts]
   ```
   and add `'cut_hits_early_s': early` to `settings`; the `alignment` rows then show `downbeat_offset_s` of about
   -0.017 (30 fps). Not made here: music_gen is outside this change's files and its end-to-end test needs the
   generative model.
3. `av_tools.fit_music` takes hits at explicit output times (it does not know about cuts): no change.

## 5. Registration and docs (lines to add; I did not edit these files)

`letitedit_guide('ops')`, `('split_edit')`, `('score')` already show the new fields (op_specs). Proposed text for the
hand-written guides:

- **GUIDE.md and GUIDE_V2.md**, edits section, after the `{op: captions ...}` line:
  ```
  - `{op: split_edit, id, lead | lag, move, fade, track, drop_words}`: a J cut (`lead`: id's sound starts that many
    seconds before its picture) or an L cut (`lag`: the clip before id is heard that long under id's picture). The
    moved sound is the same file on a `J/L cuts` audio track, in sync with its picture; the covered sound is
    silenced (`split_mute`), the two cross over 0.1 s (`fade`). `move: picture` keeps the sound cut and moves the
    picture cut instead (the classic dialogue J cut: hold the listener while the next line starts). `lead: 0` removes
    it. Later edits rebuild it; refused past the source handles (the message gives the most possible) or over words.
  ```
- same files, the `{op: score ...}` paragraph: after "evens out the speech clip by clip", add "Speech is where the
  words are (cached transcripts; the voice detector for files without one, with a warning)." and after the
  `merge_gap` default: "`answer` [none]: pauses the music comes up in (gap ids from the result's `gaps`, times, the
  phrase a pause follows, or 'auto'), with ramps scaled to the pause; zones may carry their own `attack`/`release`."
- **tool_docs_v2.py** `letitedit_timeline_apply`: optional "(edit ops include split edits: J and L cuts)".

## 6. Other changes to mirror

### 6.1 C++ Add music (musicpicker.cpp) - for you to make

- `kMergeGap 4.0` (line 95): keep (section 7.4).
- Speech: Add music already ducks by word times (`PauseRemover::phrases`, line ~888), so nothing to change there;
  the Python score now matches it in spirit (word spans, not voice detection).
- **"Let the music answer between sentences"** (CHANGELOG-presentation 4.14), a checkbox next to "duck":
  `bool answer = false;` in `struct Options` (musicpicker.h:43), saved as `music/answer` next to `music/duck`
  (musicpicker.cpp ~1256 and ~1422) and kept on the clip like `kDuckProperty` (`letitedit:music_answer`, read back
  at ~1092) so a refit keeps it. With it on, in `apply()`:
  1. In the talk step (~888-930), keep the spoken spans before the kMergeGap merge (`loud` after the word step) and
     the phrase ends (`Phrase::to` of `heard`; phrases carry no text, so a phrase end stands for a line end).
  2. Choose answer pauses like the Python `auto` rule: a pause between spoken spans of at least `kAnswerPause = 2.0`
     s that starts within 0.6 s of a phrase end, at least `kAnswerSpacing = 20.0` s after the previous answer, at
     most 3 per minute, and only pauses shorter than `kMergeGap` (longer ones are up already).
  3. When merging into `talk` (line ~924), do not merge across a chosen pause, so `levelCurve` gets a gap segment.
  4. `levelCurve` (~421): give those gap segments their own ramps: release `qMin(kRelease, pause / 3)` and attack
     `qMin(kAttack, pause / 4)`, keeping `kHold` (0.3) after the last word and `kPreroll` (0.1) before the next word
     (scale both ramps down when hold + release + attack + preroll is more than 90% of the pause), so the music is
     back down before the next word. Level: `levels.inGaps + 3` (the Python `swell` is 3 dB over `montage`), or
     `levels.inGaps` for restraint. Mark them so `rideLevels` (~967), which rides the music under talk, leaves them.
  5. The status line: "answers N pauses".
- Remove pauses / refit: nothing new (the refit re-runs the curve).

### 6.2 Skills (lines to update; skills/ not edited)

- **letitedit-sound/SKILL.md** section 4, bullet "The shipped defaults keep music dipped through every gap under 4 s":
  replace the second half with "For each chosen gap use `{op: score, answer: [...]}`: a pause id from the score's
  result (`gaps`), a time, or the line it follows (`{after: 'and then it quit on me'}`); it rises after the last word
  and is back down before the next, with ramps scaled to the pause. `answer: 'auto'` picks pauses of 2 s+ after
  sentences, 20 s apart. On a soundtrack-built track, use its sections and hits instead. Keep `merge_gap` at 4 s:
  lower values swell in every ordinary pause [OURS: 70 s of dialogue, 1 swell at 4 s, 6 at 1.5 s, 8 at 1 s]."
  Also its "Depth" check can cite the measured duet: answered pauses rise about 15 dB and are back down before the
  next word; music under the words stays flat [OURS].
- **letitedit-sound/SKILL.md** section 7, bullet "`score` finds speech by voice activity: a loud machine on the
  picture track can count as talk and duck the music. Read its `speech_seconds` and fix with zones." -> "`score`
  finds speech by word times (cached transcripts; the voice detector only for files with none, and its result says
  which: `speech_from`, `warning`), so transcribe the footage first (`letitedit_words`); the detector also missed quiet
  narration under work noise, leaving music up under it [OURS: 0.7-1.35 s of words per 30 s; with words, 0]." Keep
  the track-naming sentence.
- **letitedit-sound/SKILL.md** section 8, last sentence of "Bridge scenes with sound": "No op makes split edits yet:
  references/tool-recipes.md has the two-track recipe" -> "`{op: split_edit, id: <incoming>, lead: 0.5}` (J) or
  `lag` (L); see references/tool-recipes.md 5."
- **letitedit-sound/SKILL.md** section 11, the score line: add `answer` to the field list.
- **letitedit-sound/references/tool-recipes.md** section 2: replace "Computing zones from the words, in
  `letitedit_timeline_apply(code=...)`" and its code block with `{op: score, answer: [{after: 'and then it quit on
  me'}, {after: "that's the sound I wanted"}]}` and "dry run first to read `gaps`"; drop "`release` is global".
  Change "it finds speech by voice activity" to "it finds speech by word times (voice activity only for files with
  no transcript, with a warning)".
- **tool-recipes.md** section 5 "Split edits (J and L cuts): no op makes them yet": replace the two recipes with the
  op (fields, `move: picture` for the dialogue J cut, the refusals, `J/L cuts` track, how later edits treat it);
  keep the audio-crossfade-at-a-hard-cut bullet.
- **letitedit-fine/SKILL.md** FINE-5: "No op makes split edits yet; build them with the current ops ... J cut: put
  the incoming sound's head on an audio track ..." -> "`{op: split_edit, id: <incoming>, lead: s}` (J) /
  `lag: s` (L); `move: picture` keeps the words where they are and moves the picture cut (the usual dialogue J cut:
  the listener holds while the next line starts). The op refuses to cover words and names the most possible lead."
  Keep the "Not" and "Check" parts.
- **letitedit-craft** references only point to letitedit-sound for J/L cuts: no change.

### 6.3 Follow-ups in other files (not made)

- **`checks.cut_words`** (QC and the review bundle's "words cut at clip edges") can report false cuts at split
  edits: with `move: picture` the incoming clip's in point (J) or the outgoing clip's out point (L) may land inside
  a word on purpose, while the sound runs on through the moved-sound clip. (On the quick J-by-picture case, with
  B's in point inside "yeah", it reported nothing, because its voiced-part test let it pass; that is luck, not
  design.) Skip the edges a split edit covers:
  ```python
  import split_edit
  skip = set()                                    # (item id, 'in' | 'out') edges the sound runs through
  for t_, br, r in split_edit.records_of(script):
      if 'lead' in r:                             # J: B's in joins its moved sound; A's out is silenced
          skip |= {(r['into'], 'in'), (r.get('out_of'), 'out'), (br.get('id'), 'out')}
      else:                                       # L: A's out joins its moved sound; B's in is silenced
          skip |= {(r.get('out_of'), 'out'), (r['into'], 'in'), (br.get('id'), 'in')}
  # ... then `if (it.get('id'), 'out') not in skip:` before the 'out' check and the same for 'in'
  ```
  The moved sound's far edge (J: its in, at the sound cut; L: its out) stays checked: that is the real sound cut
  (the op already warns when it falls inside a word).
- `timeline_speech.timeline_words` (captions) and `music.speech` could skip words inside a clip's `split_mute`
  range (only matters with `drop_words: true`).
- `edit_sync.resync` counts the moved-sound clips among "N item(s) on other tracks moved" before `refresh` rebuilds
  them; harmless, but the count can include them.
- A `split_edit` listing in `letitedit_timeline_read` (today the record shows on the moved-sound clip).

## 7. Measured results

### 7.1 Split edits: 12 cases on 3 footage sets, rendered by melt (all pass)

`test_split_edit.RenderTests`, results in `cache\split-edit-tests\results\split-edit-renders-final.json`, projects
and WAVs in `cache\split-edit-tests\renders-final\`. Each case: two clips butted on V1, the op applied, the mix and two stems
(V1 alone, `J/L cuts` alone) rendered by melt at 48 kHz float, measured against ffmpeg decodes of the sources; the
mix around the cut transcribed by the local whisper; then `undo` and the file compared byte for byte.

| set (project fps; footage fps) | case | length | moved sound vs its own source (lag samples / corr) | covered sound left on the clip | clicks: sound cut / crossfade end / picture-cut join (source itself) | word heard (vs the picture cut) |
|---|---|---|---|---|---|---|
| quick (29.97; 29.97) | J by sound | 0.634 s | 0 / 0.99992 | -147.5 dBFS (source -47.5) | 0.27 / 0.22 / 1.06 (1.06) | "It" -0.45 s |
| | J by picture | 0.801 s | 1 / 0.99996 | -146.5 (-46.5) | 0.16 / 2.93 / 0.45 (0.45) | "yeah" -0.62 s |
| | L by sound | 0.834 s | 1 / 0.99998 | -130.6 (-30.6) | 0.83 / 0.34 / 2.90 (2.90) | "see" +0.54 s |
| | L by picture | 0.601 s | 2 / 0.99998 | -147.5 (-47.5) | 0.50 / 1.17 / 0.11 (0.11) | "see" +0.24 s |
| story-mini (59.94; 59.94) | J by sound | 0.701 s | 1 / 1.0 | -137.5 (-37.5) | 1.55 / 0.69 / 2.91 (2.91) | "So" -0.74 s |
| | J by picture | 0.701 s | -2 / 0.99999 | -133.1 (-33.1) | 1.03 / 0.12 / 2.43 (2.43) | "And" -0.60 s |
| | L by sound | 0.751 s | 0 / 0.99998 | -145.5 (-45.5) | 0.66 / 0.99 / 1.29 (1.20) | "here" +0.28 s |
| | L by picture | 0.751 s | 0 / 0.99998 | -145.5 (-45.5) | 0.66 / 0.99 / 1.29 (1.20) | "here" +0.28 s |
| story-rear-ac (30; 59.94) | J by sound | 0.733 s | 2 / 1.0 | -143.1 (-43.1) | 0.59 / 0.39 / 5.42 (5.42) | "That's" -0.81 s |
| | J by picture | 0.600 s | 0 / 1.0 | -143.4 (-43.4) | 0.28 / 1.46 / 0.92 (0.92) | "But" -0.12 s |
| | L by sound | 0.667 s | 0 / 0.99993 | -147.6 (-47.6) | 0.62 / 0.35 / 16.85 (16.43) | "folk(s)" +0.30 s |
| | L by picture | 0.667 s | -2 / 0.99988 | -147.6 (-47.6) | 0.61 / 0.29 / 0.15 (0.17) | "folks" +0.46 s |

- **Sync**: the moved sound, and the mix in the split region, line up with their own source within 2 samples
  (0.04 ms) everywhere; the sound after and before the sound cut too (|lag| <= 2). A frame is 33 ms.
- **Covered sound**: 100 dB down (the -100 dB key) in every case.
- **Clicks**: the measure is the largest second difference within 3 ms of a point over the median of the same in
  6 ms windows around it (about 1-2 where nothing happens). Controls, a straight cut in mid-word on the same footage:
  6.0, 115.5 and 33.0. At the sound cut and crossfade end: 0.12-2.93. At the picture cut, where the moved sound joins
  the clip's own, the value equals the source's own at that point (the join adds nothing).
- **Heard**: the transcript of the render has the incoming line's first word 0.12-0.81 s before the picture cut (J)
  and the outgoing line's last words 0.24-0.54 s after it (L). (Whisper's word times are about +-0.1 s.)
- **move: picture**: outside the 0.1 s crossfade the mix is the same as before the edit: momentary loudness differs
  by 0.00 dB, every 100 ms correlates 0.98-1.0 at a lag within 2 samples (the engine's mix can hold a track back a
  sample at 29.97 / 59.94 fps, where frames carry 1601/1602 or 800/801 samples: inaudible). The frame on the first
  changed frame matches the shot the new layout puts there (mean grey distance 1.0-1.3) and not the old one (38-92).
- **Undo**: the file is restored byte for byte in all 12 cases (and in the unit tests).
- Note: L by sound and L by picture on story-mini end in the same timeline (by construction), and measure the same.

Found and fixed on the way: the engine ramps a gain from the previous frame's value, and a clip's first frame has no
previous value, so a J moved sound now starts one silent frame earlier and the outgoing clip's fall is keyed from the
frame before the sound cut; before that, the J crossfade ended a frame late (measured: -78 dBFS of the covered
sound in the first 13 ms of the split region on story-rear-ac).

### 7.2 Score: the duet (`answer`), rendered by melt

`test_score_answer.ScoreRenders`; projects and WAVs in `cache\split-edit-tests\score-final\`.
Footage: story-rear-ac IMG_0468 (narration with pauses) in three segments of under 30 s, 30 fps; music: Komiku "Walk
in the forest" (CC0). The gain the score applied is measured from the render: the music stem's least-squares gain
against the same music rendered flat, every 50 ms, against the timeline's word times.

| segment | answered pause (silence between the words) | rise in it (dB over the talk level) | 0.1 s before the next word |
|---|---|---|---|
| 0:00-0:29.5 | after "...holding this thing on." (1.70 s) | +15.0 | +0.7 |
| | after "...just enough space." (1.48 s) | +12.8 | (the song's own fade-out) |
| 0:32.5-1:00.5 | after "Water goes everywhere." (3.88 s) | +15.0 | 0.0 |
| | after "This is a tricky one folks." (3.34 s) | +15.0 | +0.6 |
| 0:56.5-1:26 | after "...the only way to access this." (1.76 s) | +15.0 | +1.2 |

- Under the words the music is steady: 95th percentile and maximum 0.0 dB over the talk level in every segment, with
  and without answers. Pauses not answered (under merge_gap) stay at 0.0 dB; the 5.1 s pause (over merge_gap)
  rises to montage, +12 dB, as before. Music stem loudness: about -42 to -49 LUFS under speech, -18.5 to -29 LUFS
  (momentary maximum) in the answered pauses.
- `answer: 'auto'` picked the 4.0 s pause in the first segment (+15 dB, +2.1 dB in the last 0.1 s before the next
  word: that 50 ms window catches the end of the fall) and the 3.9 s pause in the second; none in the third (no
  pause of 2 s after a sentence).
- The score as it was (voice detector, no answer) on the same segments: the music stood +12 dB over the dip under
  some words in all three (maximum +12 dB; 95th percentile +12 dB in the second segment), and after the 4.0 s pause
  in the first it was still up when the next sentence began.

### 7.3 Score: speech from words against the voice detector

Seconds of spoken words (transcript) during which the rendered music stood 6 dB or more over the dip:

| footage (29.5 s each) | words | voice detector (before) | words (now) | music ducked 4.5 s or more from any word (before / now) |
|---|---|---|---|---|
| story-mini IMG_0519 (narration over work noise) | 9.6 s | 1.10 s | 0.00 s | 0 / 0 s |
| story-rear-ac IMG_0469 (narration over work noise) | 4.8 s | 1.35 s | 0.00 s | 0 / 0 s |
| story-rear-ac IMG_0468 (clean narration) | 17.1 s | 0.70 s | 0.00 s | 0 / 0 s |

On this footage the detector's error is missing quiet speech under work noise (whole-file measure on IMG_0469: 6 s of
voice found against 39 s of word spans), not counting machines as talk; word timing fixes both. (Speech seconds
the score reports, merged: 16.7 -> 23.2, 7.8 -> 10.2, 24.1 -> 28.7.)

### 7.4 merge_gap: kept at 4 s

The same three IMG_0468 segments (70.5 s of dialogue, away from the song's fades), scored with only merge_gap changed:

| merge_gap | music rises of 6 dB+ | per minute | seconds up | seconds the gain is moving | words with music 3 dB+ over the dip |
|---|---|---|---|---|---|
| 4 (default) | 1 | 0.9 | 4.3 | 1.2 | 0 |
| 2.5 | 5 | 4.3 | 12.6 | 4.5 | 0 |
| 1.5 | 6 | 5.1 | 13.5 | 5.7 | 0 |
| 1.0 | 8 | 6.8 | 15.0 | 8.1 | 0 |

Every lower value turns ordinary pauses into 12 dB swells (4-7 a minute) whether or not a line wants an answer; the
research asks for 3-4 deliberate events per scene in the pauses after key lines (ITE-DUET, CHANGELOG 4.1) and calls
the 4 s bed "the right default (no pumping)". None of the settings let music up under words (the pads and the
pre-roll work), so the cost of a low merge_gap is pumping, not masking. Decision: keep 4 s; `answer` opens the
chosen pauses.

## 8. What to retest after integrating

- `python -m unittest test_split_edit test_score_answer` (renders included; `LETITEDIT_SKIP_RENDERS=1` for the fast
  part), plus the suites run before and after: test_edit_script test_native_tools test_a*_fixes test_timing_fixes
  test_speech_fixes test_music test_audio_mix_defaults, `python -m pytest test_soundtrack.py`.
- In a real Shotcut window (not tested here): a split edit applied live (with and without an existing `J/L cuts`
  track) lands as one undo step, Ctrl+Z restores both clips and removes the track content; the `split_mute` filter
  shows as Gain/Volume with keyframes; playback has no click at either sound cut.
- After registration: `letitedit_guide('split_edit')` and `letitedit_guide('score')`.
- Add music after the C++ change: Medium with "answer" on a dialogue project; the measured dB in the answered pauses.
