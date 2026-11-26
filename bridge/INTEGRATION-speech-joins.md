# Integrating speech rhythm (`speech`) and sound across cuts (`joins`) — builder B3, 28 Oct 2026

Built to TIMING-SPEC.md. Nothing shared was edited except my own keys in `timing_thresholds.json` (`speech.*`,
`joins.*`, merged without touching other keys). Both modules register themselves: `timing_signals.load_plugins()`
imports them (they are listed in `timing_signals.PLUGINS`), so `letitedit_timing(view='speech')`
and `letitedit_timing(view='joins')` work through B1's tool with no extra lines. B2's cut inspector calls
`joins.measure(source, cuts=..., settings=...)` directly.

## Files (B3)
- `bridge/prosody.py` — the `speech` lane (version 5) and view.
- `bridge/joins.py` — the `joins` lane (version 6, depends on `edit`, `speech`) and view; `measure()` / `at_cut()`.
- `bridge/tests/timing/test_prosody.py` (18 tests), `bridge/tests/timing/test_joins.py` (16 tests): all 34 pass (28 Oct). `-k "not real"`:
  synthetic only, about 15 s; the `*_real` tests use the test footage and the A/B round projects (read only).
- `tests/fixtures/speech-joins/` — weak labels: `thought_end_labels.json` (8 clips, 3 sets), `stress_labels.json`
  (5 clips), `breath_labels.json` (3 clips, from spectrograms). Nobody listened: labels come from reading
  transcripts and looking at spectrograms; each file says how it was made.
- `bridge/timing_thresholds.json` — 54 keys (`speech.*` 36, `joins.*` 18), each `{value, unit, about}`.

## 1. Requirement (release env) — one line in `release/env/requirements-bridge.txt`
```
praat-parselmouth==0.4.7                # GPL-3.0 (bundles Praat): F0 for the speech lane; fits the GPL-3 release
```
Installed 28 Oct into the bridge interpreter (`...\Python314\python.exe -m pip install praat-parselmouth==0.4.7`,
cp314 wheel, 9 MB, numpy its only dependency). NOT installed in `envs\bridge-clean` (built from the requirement
files: rebuild it after adding the line). Without parselmouth the lane uses a numpy YIN pitch tracker and says so in
`method`. THIRD-PARTY-NOTICES.md section 2: add "praat-parselmouth 0.4.7 (GPL-3.0, includes Praat)".

## 2. API (Python; also reachable as `letitedit_timing` views)
```python
import prosody, joins
prosody.analyse(source, start=None, end=None, settings=None, refresh=False, transcribe=True, basis='auto')
    # -> contract fields + 'lane' (standalone, cached under cache\timing-audio\<key>\; no store needed)
prosody.lane(ctx)            # the store's 'speech' lane; lane.defaults = short-key defaults (cache identity)
prosody.view(source, start_s, end_s, items, cuts, options, detail)   # view 'speech'
    # options: row_s (10), rows_per_image (3), max_images (4), images (0 = numbers only), key_lines
    #          (phrases or {t}), basis ('auto'|'mix'|'dialogue'), settings, refresh, out_dir
prosody.analyse_audio(x16, words, start_s=0, settings=None, cuts=None, walls=None)  # pure: 16 kHz mono + words
prosody.boundary_strength(measures, incomplete, breath, settings) -> (strength, cues)
joins.measure(source, cuts=None, start_s=None, end_s=None, settings=None, ctx_lanes=None, sources=True,
              scan=False, audio=None, script=None, use_store=True)     # -> contract fields + 'joins' + 'summary'
joins.at_cut(source, cut, settings=None, lanes=None)   # one cut ({t} | {f} | seconds) for an inspector
joins.measure_audio(y48, t, settings=None, words=None, speech=None, span=None, lossy=False)  # pure
joins.scan_clicks(y48)       # sample discontinuities anywhere (audio edits away from picture cuts)
joins.project_edit_points(project)   # picture cuts, sound joins (split edits, split_mute, cross-track), items
joins.view(source, start_s, end_s, items, cuts, options, detail)     # view 'joins'
    # options: images (0 = numbers only), per_image (12), max_images (3), flagged_only, sources, scan, settings
```
Speech lane data (spec keys plus): `words` [{t0, t1, f0, f1, w, stress, stress_acoustic, syll, rate, v0, v1 (voiced
extent), asr_t0, asr_t1, measures}], `pauses` [{t0, t1, dur, after_word, cut?, breath?, breath_check}], `f0`/`energy`
every 10 ms from `t0`, `active` (10 ms speech activity, '0'/'1'), `thought_ends` and all `boundaries` [{t, f,
strength, cues, measures: pause_s, lengthening, rate_ratio, reset_st, fall_st, end_pct...}, text_end,
incomplete_syntax, space_after_s, cut?, breath?], `breaths`, `speech_rate`, `stressed`, `speaker`, `stats`
(thought-end gap mean/sd/cv, long pauses inside a thought, longest stretch without an end or breath), `timings`.
Joins entry: `click`, `click_level`, `click_d2`, `level_jump`, `speech_level_jump`, `floor_jump`, `silence_gap`,
`spectral_jump`, `room_spectral_jump`, `pitch_jump` (each {value, unit, threshold, over, method}); `words` (last/next
word, gaps, word cut, thought end, breath in the pause); projects: `sound_at_cut` (cut | J cut | L cut | starts |
ends | continuous) and `source` {out, in, edited_pause_s}: both recordings at the cut (clipped word ms, natural
pause, breath and whether the cut kept it, thought end); `fine_cut` (word_clipped, thought_end_tightened,
breath_removed — letitedit-fine FINE-1/3); `flags`; `problems` [{kind, text, value, unit, threshold}] most important
first (what B2 reads).

## 3. Guide / skills (suggested lines; skills are not mine to edit)
- GUIDE (timing section): "`letitedit_timing(view='speech')`: words with pitch and energy, thought ends (strength and
  cues), stressed words, breaths and the space after each thought end; `options.key_lines` marks your key lines.
  `view='joins'`: per cut, clicks, level and room-tone jumps, holes, voice/room colour, pitch jumps, and on a project
  the recordings at both sides: clipped words, the natural pause, breaths cut away."
- letitedit-fine FINE-1 Check: "`letitedit_timing(view='joins', options={'images': 0})`: no `thought_end_tightened` or
  `breath_removed` left unexplained; `view='speech'` stats: thought-end gaps vary (cv), no long pause inside a thought".
- letitedit-fine FINE-3/FINE-4 Check: "`joins` flags `click`, `word_clipped`, `speech_level_jump`, `room_tone_jump`,
  `pitch_jump`: give a 6-8 frame centred crossfade or fix the edit; every number is in `problems`."

## 4. Load and caches
- One process, no pools. ffmpeg decodes use `-threads 4`. Projects: the mix comes from the store's preview WAV
  (B1); standalone, a melt audio-only render (render lock when > 30 s), cached in `cache\timing-audio\<key>\`
  (24 most recent kept). A dialogue stem (music/sfx tracks off) is rendered only when a music track is heard AND the
  timeline has words.
- Transcription is the costly part. Videos without a cached transcript are transcribed (speech.words: GPU worker
  through model_tools' GPU turn, else CPU) ONLY when Silero VAD (cached per file) hears >= max(1 s, 3% of the file)
  of voice; otherwise the lane says so and gives pitch/energy only (`settings: {speech: {transcribe: 'force'}}`
  overrides). The 34 s music-only montage render that took 149-359 s (B1/B4) now takes 1.8 s.
- Lane results: the store's cache (version + settings); standalone `prosody.analyse` also keys on the module's code.
- Joins on a project measure both recordings at every dialogue cut (about 0.8 s per cut).

## 5. Measured (28 Oct 2026) — weak labels, nobody listened
- Thought ends (held-out story-mini + story-rear-ac, 5 clips; tuned on the 3 quick clips): F1 0.574 (P 0.65,
  R 0.52) vs best pause-only threshold 0.44-0.45 (0.3 s: 0.442). Acoustic cues alone 0.47. Pitch reset / final
  lowering / breath carried no signal on this footage (AUC 0.49-0.53; weights 0). 41% of labelled thought ends have
  no pause at all, which caps recall.
- Stress (5 clips, 41 clear stressed, 99 clear unstressed): AUC 0.84 acoustic (0.90 with the function-word prior),
  0.65 against other content words; at 0.5: recall 0.39, precision 0.84, 12.6% of words flagged.
- Breaths (3 clips, spectrogram labels, 43 matched pauses): P 0.67 R 0.88 in sample; leave-one-clip-out P 0.56 R 0.63.
- Pitch: Praat via parselmouth vs YIN both within 3 Hz on test tones (unit tests).
- Joins, synthetic in real speech (3 clips, 12 positions each, WAV): clicks 97% recall / 1% false alarms at 6;
  holes 100% with 0 ms error; level-matched EQ change 100%; +10 dB speech step 97%, +-6 dB 58-69% (natural
  phrase-to-phrase variation: untouched p95 5.1 LU); untouched speech: no flags except speech level 6%.
  Through AAC 128k: clicks 73% at 6, 79% at 3.5 (the lossy threshold), other measures robust.
- Real cuts: see section 6.

## 6. Real cuts (A/B rounds ab3/ab4/ab5: 11 projects, 161 joins; C:\LetItEdit\cache\timing-tests\b3\real_joins.json)
- 130 straight dialogue sound cuts (no crossfade in any of them): 100 (77%) flagged `click`. Control: 0 of the 22
  picture-only cuts (b-roll over continuous sound) flagged; the one J cut (split edit with its 0.1 s crossfade): no
  click. ab5 Short: all 12 cuts show a visible waveform step (joins view).
- Eye labels of +-3 ms waveforms at 33 straight cuts (3 projects; 3 more unsure): the click flag agrees P 0.76,
  R 0.79; misses had ratios 3.6-5.9 (just under 6); some "false" flags may be slope kinks I can't judge by eye.
- Project WAV vs the delivered render (AAC, loudness-normalised, lossy threshold): same click flag at 146 of 161
  joins; 15 flagged only on the render; none only on the project.
- letitedit-fine checks across the 11 projects: thought_end_tightened 50, word_clipped 36, breath_removed 22.
  Source spectrograms of 7 ab5 cuts (cache\timing-tests\b3\edge_check_ab5_short.png): cut 1 starts inside "so."
  (flagged, true), cut 11 ends on "yeah" still voiced (flagged, plausible), cuts 3 and 7 sit in quiet (not flagged
  after the sound-at-edge rule), cut 5 starts on the final "s" of "this" (unvoiced fragment: missed).
  thought_end_tightened inherits the thought-end detector's precision (~0.65).
- Music-only montages: no speech measures (no words); flags only level/spectral changes at music edits.
- Speed: a 3-minute project 34-57 s standalone (melt mix render + both recordings at every cut, ~0.8 s/cut); on a
  cached store preview the speech lane takes ~1 s and joins ~4 s for the 49 s ab5 Short.

## 7. Limits
- Cannot listen: flags are numbers over thresholds. Thought ends follow syntax-based labels only to F1 ~0.57; the
  detector is mostly pause + lengthening + "can't end here" words; hesitation pauses after content words still pass.
- Breath detection is weak in loud backgrounds (fans, A/C): few labels, leave-one-out P/R ~0.6.
- Word edges: turbo-whisper word times run over pauses; edges are moved onto voiced/active sound. In noisy sources
  edges can still be off by ~0.1 s; words whose transcript span is implausibly long are marked `timing:
  unreliable` and not checked for clipping. Unvoiced fragments (a final "s") are not caught as clipped words.
- A project's speech lane uses a dialogue stem when music is heard; a video's (e.g. a render with music) uses the
  mix, where music biases pitch and energy.
- Speech level natural variation overlaps edits of +-6 dB; the level flag is a prompt to listen, not a verdict.
- Multi-speaker: one pitch range for the whole source.
