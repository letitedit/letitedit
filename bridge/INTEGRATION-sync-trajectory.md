# Integrating the music lane and the `sync` / `trajectory` views (timing layer, builder B4)

Contract: `bridge/TIMING-SPEC.md`. Nothing outside these files was edited:

| File | What it is |
|---|---|
| `bridge/music_sync.py` | The `music` lane (registered with `timing_signals.register_lane`), the `sync` view (registered with `timing_views.register_view`), the per-song beat grid (`song_grid`), the Beat This! worker (runs in the models environment), the measures and the images. |
| `bridge/trajectory.py` | The `trajectory` view: energy series against the story plan's sections, gears and peaks. |
| `bridge/tests/timing/test_music_sync.py`, `bridge/tests/timing/test_trajectory.py` | pytest: 32 fast unit tests (`-m "not real"`, ~2 s) and 14 real-material tests (synthetic songs and edits, the soundtrack test project, an A/B round project). |
| `bridge/timing_thresholds.json` | Keys `sync.*` (15) and `trajectory.*` (11) merged in (missing keys only, never overwriting another key; re-read before an atomic write). |
| `envs/beat-this/` (new folder) | Beat This! 1.1.0 + rotary-embedding-torch 0.9.1 + soxr 1.1.0, installed `--no-deps --target` for the models Python (torch, torchaudio, einops, numpy come from `envs\models`; the shared env was not changed). 0.9 MB. |
| `models/torch/hub/checkpoints/beat_this-final0.ckpt` | The checkpoint (77 MB) from cloud.cp.jku.at (the package's own download URL). |

Test material and outputs: `C:\LetItEdit\cache\timing-tests\b4\` (songs, projects, eval, results, scripts).

## 1. Registration: nothing to edit

`timing_signals.load_plugins()` imports the modules listed in `timing_signals.PLUGINS`; both modules are listed, and
`register()` runs at import (safe to call again). After
`load_plugins()`:

```
timing_signals.lanes()['music']   -> {'depends': [], 'version': 1, 'module': 'music_sync'}
timing_views.views()              -> {..., 'sync': '...', 'trajectory': '...'}
```

So `letitedit_timing(source, view='sync')` and `letitedit_timing(source, view='trajectory')` work through B1's tool with no
change to `timing_tools.py`, `letitedit_mcp.py`, `letitedit_ai.py` or `tool_docs_v2.py` (the tool's description lists
registered views itself).

Optional convenience functions for `letitedit_ai.py` (not added):

```python
def music_lane(source, settings=None, refresh=False):
    """sa.music_lane(project_or_video) -> beats, bars, phrases, drops, tempo, sections, music level (no render)"""
    import music_sync
    return music_sync.music(source, settings=settings, refresh=refresh)


def song_grid(path, **settings):
    """sa.song_grid(song) -> one audio file's beat grid (Beat This! + DP), bars, phrases, drops, energy"""
    import music_sync
    return music_sync.song_grid(path, settings=settings or None)
```

## 2. Python API

```python
music_sync.song_grid(path, settings=None, refresh=False)        # any audio/video file; cached by content
music_sync.music(source, settings=None, refresh=False)          # the lane without the store (project: no render)
music_sync.lane(ctx)                                            # the store's compute (lane.defaults = DEFAULTS)
music_sync.sync(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief')
trajectory.trajectory(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief')
trajectory.plan_sections(sig, options) -> (sections, where_from, notes)
trajectory.find_story_plan(source, explicit=None, project=None) -> (plan, where)
music_sync.beat_this_status() -> {'available', 'why', 'python', 'package', 'checkpoint'}
```

Options of `sync`: `kinds` (default cuts, motion_peaks, visual_beats, text_pops, sfx; `caption_pops` on request),
`thresholds` ({key or short key: value}), `settings` ({lane: {...}}; music: `tracker` auto|beat_this|soundtrack,
`stem` auto|separate|mix, `beats_per_bar`, `device`), `story_plan`, `deliverable` (long/short), `strip_s`, `pages`,
`speech_lane` (videos only, default false: the prosody lane transcribes the video, ~6 min the first time for 30 s),
`refresh`. Options of `trajectory`: `story_plan`, `deliverable`, `project` (map a render's plan through its project),
`thresholds`, `settings`, `speech_lane`, `refresh`. Both return `options_available`.

## 3. The `music` lane (TIMING-SPEC keys + extras)

`beats` [{t, f, downbeat, pos (1 = downbeat), bar (the song's bar number), phrase, drop, strength (0-1 onset strength),
prob (Beat This! beat probability), level_db (music as heard there), audible, piece, song_t}], `tempo_bpm`,
`beat_confidence` (mean Beat This! probability at the beats), `beat_quality` (clear/weak/none from
`sync.beat_clear_min` / `sync.beat_weak_min`), `sections` [{t0, t1, f0, f1, label, energy (dB vs the song's
loudest), piece}], `energy` every 0.5 s (dB of the music as heard, power mean) and `intensity` (0-1 song energy by bar),
`level_db` every 0.1 s, `stem` (how the music was isolated), plus `bars`, `phrases`, `drops`, `pieces` (each music
clip: in/out, speed, crossfades, the span it owns), `songs` (per file: tracker, bpm, confidence, cross-check with the
older tracker), `music_spans` (where music is audible), `tracker`, `warnings`, `unsupported`.

Where the music is analysed: a project's music clips' own files (tracks named music/song/score/bed, or audio-only files
of 8 s+ on other non-effects tracks; said per piece), mapped through in/out, speed, crossfades (each piece owns its beats
to the middle of the crossfade, which Shotcut stores as whole frames: 0.5 s at 25 fps is 12 frames), clip and track
gain (static and keyframes) and audio fades. A video: its own sound, or Demucs' music stem (`model_tools.separate`,
drums + bass + other) when speech covers 10%+ of it (cached words or the voice detector); `stem` says which.

## 4. The beat tracker (why it changed, what it costs)

Evaluated before choosing (scripts and pictures in `cache\timing-tests\b4\eval`):

| synthetic song (exact beats) | older tracker (soundtrack.analyze) beat F / downbeat F | Beat This! alone | used here (Beat This! + DP + refine + bar HMM) beat F / downbeat F / median error |
|---|---|---|---|
| drums 128 | 0.99 / 0.98 | 0.99 / 1.00 | 0.99 / 1.00 / 0.6 ms |
| half-time 80 | 0.28 / 0.00 | 0.99 / 1.00 | 0.99 / 1.00 / 0.8 ms |
| acoustic 96 (no drums) | 0.98 / 0.96 | 0.99 / 1.00 | 0.99 / 1.00 / 0.3 ms |
| waltz 132 (3/4) | 0.99 / 0.29 | 0.51 / 0.81 | 0.99 / 1.00 / 1.2 ms |
| swing 110 | 0.99 / 0.00 | 1.00 / 0.75 | 1.00 / 1.00 / 0.4 ms |
| rubato piano 84 (+-7%) | 0.98 / 0.95 | 1.00 / 1.00 | 0.99 / 1.00 / 1.8 ms |
| syncopated 100 | 0.40 / 0.39 | 0.99 / 1.00 | 0.99 / 1.00 / 1.0 ms |
| tempo change 100->125 | 0.63 / 0.00 | 0.99 / 0.56 | 0.97 / 0.00 (kick on 1 and 3, only a bass note marks 1) / 0.3 ms |
| soft pad 72 | 0.66 (double tempo) / 0.68 | 0.99 / 1.00 | 0.99 / 1.00 / 4.6 ms |

Real library songs (no ground truth): on clear songs the two agree (A Typical Ride Out beats 1.00 / bars 0.99; The
Wind 1.00 / 0.99); where they differ, the band-envelope pictures side with the new grid (Free To Use 6: the older
grid sits on the off-beat 8ths, bass entries fall on the new downbeats; The calling 136-144 s: the older bar lines are
one beat before the real downbeat). Songs without a steady beat (Easy nostalgia with melodica, Dressed in Black) get
beat_confidence ~0.52-0.57 (weak) and a warning; clear songs 0.75-1.0.

Cost: Beat This! on the CPU (models Python, `-I`, from `envs\beat-this`): ~3-5 s per 3-minute song + model load ~2 s;
`song_grid` total ~10-25 s per song the first time (it also runs `soundtrack.analyze` for sections and the
cross-check), cached by content in `cache\music-sync\songs` and `cache\music-sync\beat-this`. Without the models
Python, the package or the checkpoint, the older tracker is used and every result says so (`tracker`,
`tracker_note`).

Licence: Beat This! code MIT (CPJKU, JKU Linz; `envs\beat-this\beat_this-1.1.0.dist-info\licenses\LICENSE`);
rotary-embedding-torch MIT; soxr LGPL-2.1+ (python-soxr; already present in `envs\voice`). The package README states
no separate licence for the checkpoints (trained on public beat datasets, GTZAN excluded for `final*`): check with the
authors before shipping the weights in an installer (add a row to `LICENSES-REVIEW.md`; not edited here).
Citation: Foscarin, Schlueter, Widmer, "Beat This! Accurate Beat Tracking Without DBN Postprocessing", ISMIR 2024.

Reinstall (models Python, nothing else touched):
```
uv pip install --no-deps --python C:\LetItEdit\envs\models\Scripts\python.exe --target C:\LetItEdit\envs\beat-this beat-this==1.1.0 rotary-embedding-torch==0.9.1 soxr==1.1.0
```
The checkpoint downloads on first use only when missing; the worker is given the local path, so no download happens
while it exists.

## 5. Measures (all in frames on the edit's grid; event - beat, + = the picture after the beat)

`sync`: per event kind: shares within `sync.on_beat_frames` (1) and `sync.near_beat_frames` (2) of a beat and a
downbeat, each with its chance level (2 x threshold / beat period: what random placement gives), median and
median-absolute offset, phase locking (vector strength + Rayleigh p), share on the half-beat; per event: offsets to
the nearest beat/downbeat, the previous and next beat, the half-beat, the bar position, phrase/drop flags, music
audible. Monotony: on-beat share against `sync.monotony_share`, longest run of on-beat cuts against `sync.monotony_run`,
shot lengths in beats (cv, the most common whole number). Hard hits: cuts within 2 frames of a drop, a phrase start or a
strong downbeat, with the sound lead in frames against the AOTC Dune reference (`sync.hard_hit_sound_lead_frames` 0.5,
a reference, not a rule). Speech against music: each speech gap of `sync.gap_min_s`+ (music.speech_gaps on music.py's
word spans) with the music level in it against under the words beside it, swell = `sync.swell_rise_db`+; music under
speech and under the dialogue loudness. Song sections against story sections: each story boundary (chapter markers, or
the story plan mapped by trajectory.plan_sections) to the nearest song boundary (section, phrase start, drop, join) in
bars, aligned within `sync.section_match_bars`; music intensity per story section and its rank correlation with the
gears. SFX against impacts: each SFX onset (project: clips on effects tracks + the clip's first strong onset; video: the
audio lane's strongest onsets off the beat grid and outside words) against the nearest motion peak or cut within
`sync.sfx_window_frames`.

`trajectory`: every `trajectory.step_s` over `trajectory.window_s`: cut rate (/min), motion (motion lane energy,
camera removed), music level (dB), words per minute, speech share, and an index (robust z-scores within the edit,
weighted by `trajectory.weights`); plan sections mapped (markers > beats' selects matched to picture items >
target_s shares, said which); per section: cuts/min, median shot, motion, music dB, words/min, index and its slope;
gear check (Spearman of gear vs index, neighbours whose change disagrees); per planned peak (gear above its
neighbours): rise into it, a breath just before it, release after it, each lever before/in/after, where the music's
high point is.

## 6. Validation (numbers measured; details in `cache\timing-tests\b4\results`)

Synthetic edits (`build_synthetic.py`: b-roll footage cut at planned offsets from synthetic songs whose every beat is
known to the sample; `validate.py`). Error = measured offset - true offset, in frames:

| edit | what it tests | cuts | beat offset error median / max | downbeat error max | SFX offsets (planned) |
|---|---|---|---|---|---|
| syn-cuts-30 | 30 fps, drums 128 bpm, offsets 0 to +-4 and half a beat | 15/15 | 0.014 / 0.025 | 0.025 | 0, -2, +3, 0 measured exactly |
| syn-map-25 | 25 fps, two songs (in point 3.0 s; 0.5 s crossfade stored as 12 frames) | 15/15 | 0.011 / 0.14 | 0.032 | -1, 0 exact |
| syn-waltz-2997 | 29.97 fps, 3/4 waltz, every cut on a downbeat but two | 19/19 | 0.043 / 0.055 | 0.055 (3/4 bars found) | - |
| syn-vert-30 | 30 fps vertical, acoustic 96 bpm (no drums) | 14/14 | 0.013 / 0.023 | 0.031 | 0, -2 exact |
| syn-vert-30 render (video path) | melt render: cuts by shots.detect, beats from the mix | 14/14 found | 0.018 / 0.73 (an SFX click 0.7 frame before a beat pulled that beat's refinement) | 0.078 | not found (onsets on the grid are taken as music) |
| syn-cuts-30 render (video path) | landscape frame, vertical clips pillarboxed | 5/15 found (detector) | 0.06 / 0.10 on the 5 | - | - |

The waltz grid is right (beats and 3/4 bars) but reads beat_quality 'none' (confidence 0.35): Beat This! gives the
weak beats of the bar low probability; the label is conservative there.

Soundtrack test cases (`cache\soundtrack-tests`, hits placed by `letitedit_soundtrack`):
- montage: the drop cut (frame 870, 29.029 s) measures +1.01 frames after its downbeat; that downbeat is within
  0.25 frame of the soundtrack's own bar line. The "phrase" cut (frame 1358) lies 0.2 frame from this grid's half-beat;
  the soundtrack's bar line there is one 160-bpm beat before the real downbeat (eval\calling_136.png). The tool
  reported -4.8 / -1.2 ms because it measured against the requested times (29.0 / 45.3 s), not the real cut frames.
- speech (story-mini footage, 3:38): music under the dialogue 18.4 dB from the clip mapping; the soundtrack measured
  18.6 LU from rendered stems. 8 speech gaps of 1 s+ checked, 2 with a music swell (the score holds music down in
  pauses under 4 s).

A/B round projects and their renders (`run_real.py`, `compare_paths.py`):
- ab4 montage old (Monplaisir 151 bpm, clear): cuts on the beat 0.167 against chance 0.167; the notes say the cuts
  were not placed on beats. Project against render: 12 cuts, median difference 0.015 frame, 10 within 0.2 frame; one
  cut 6 frames apart (the render's grid finds an extra beat at a 0.1 s music join).
- ab4 montage new (Komiku "Easy nostalgia", weak beat 0.52, older tracker: no steady beat): the cut into "Rolling out"
  sits 0.07 bars from a phrase start (the notes: a phrase start was landed on that cut, -3.5 ms). Trajectory: plan
  sections mapped from the beats' selects exactly onto the notes' shot table (0-16.6 / 16.6-31.1 / 31.1-34.3), gears
  1-3-1 against the index: Spearman 0.87; the "Rolling out" peak rises 0.68 and releases 0.70 (index units).
  Project against render: 6 cuts, median difference 0.095 frame (max 0.82).
- ab5 story long (2:48, speech-led, "A Typical Ride Out" 83 bpm clear): cuts on the beat 0.077 against chance 0.092
  (cut by the words); 6 chapter markers, 4 within a bar of a song boundary; music 19.2 dB under the dialogue; 3 gaps
  of 1 s+, none with a swell. Trajectory: 7 plan sections mapped from the selects; gears against the index Spearman
  0.26, three neighbours disagree (e.g. "LATER: the grind is back", gear 4, has the highest cut rate, 19.7/min, but the
  ducked music and slower talk keep its index low).
- ab5 story long, its render through the video path (music separated with Demucs since someone talks): the stem
  holds the fan grind and machine noise as well as the bed (ducked ~40 dB under the words), so the render's grid is weak
  (confidence 0.52 against 0.96 from the music file) and its "music level" counts machine noise. Project against
  render: 12 of 13 cuts compared, median difference 1.19 frames, 25% within half a frame. Lesson, written into the
  lane's `beat_quality`/`stem`: measure a project from its music files; a render of a speech-led edit with a ducked bed
  is not a reliable source of beats.

Runtimes (first run, this PC): a 30 s project ~40 s (preview render + motion lanes + music), a 3:38 project ~10 min
(render lock + motion lanes), later calls seconds (cached).

## 7. Changes described, not made

- **soundtrack.py (owner of `letitedit_soundtrack`)**:
  - Its beat grid could come from `music_sync.song_grid` (table above: the older tracker's downbeat failed swing,
    3/4, half-time, syncopation and a tempo change, and in The calling 136-144 s its bar lines sit one beat before the
    real downbeat, where it then landed a "phrase" hit). Until then, `sync` warns when the two grids disagree
    (`songs[...].cross_check`).
  - Hit times should be snapped to the picture's real cut frames. The montage case asks for a drop at 29.0 s; at 29.97
    fps the cut is frame 870 = 29.029 s, so the music lands one frame (34 ms) before the cut while the tool reports
    -4.8 ms against the requested 29.0.
- **B1 (timing_signals / shots.detect)**: in a landscape preview, cuts between two pillarboxed vertical clips were
  missed (10 of 15 in `syn-cuts-30`'s render): most cells are black bars that never change. Projects are not affected
  (their cuts come from the edit script). On `ab4-montage-old\renders\short.mp4` the motion, visual_beats and
  motion_events lanes failed ("shape mismatch: value array of shape (9,) could not be broadcast to indexing result of
  shape (2,)"); `sync` then used its own fallback (shots.features residual difference) and said so in `events_from`.
  The speech lane (prosody) took 359 s on a 34 s render the first time, so `sync` / `trajectory` ask for it on videos
  only with `options.speech_lane`.
- **Skills** (described for the skill owners):
  - letitedit-sound: after the score, `letitedit_timing(project, view='sync')`: cuts on bars/phrases against chance,
    hard hits' sound lead (reference half a frame), music rising in the pauses (share of gaps with a swell), music under
    the dialogue; "vary the cut patterns" -> the monotony numbers.
  - letitedit-fine FINE-11 ("measure each section against its gear") and letitedit-craft's gear list:
    `view='trajectory'` gives the per-section numbers, the gear order check and the rise/release around planned peaks.
  - letitedit-modes montage-transformation ("the render's energy curve matches the planned one"; "release before the
    peak"; "cuts are not nearly all on beats"): `trajectory` peaks (rises / breathes / releases) and `sync` monotony.
  - letitedit-gate / review bundle: the bundle could add both views' numbers to its measurements for the critic.
- **GUIDE.md** (timing tool section): one line each: `sync`: "music beats against picture events in frames, with
  chance levels; swells in speech gaps; song vs story sections; SFX vs impacts" and `trajectory`: "energy over time
  against the plan's gears: per-section numbers, peaks rising and releasing".

## 8. Caches and files

- `cache\music-sync\songs\<content key>-<settings>.json`: song grids; `cache\music-sync\beat-this\<key>-final0.json`:
  Beat This! probabilities; `cache\music-sync\work\`: transient.
- The lane's cache is the store's (`cache\timing\<key>\music-v1-<identity>.json`).
- Images: `cache\timing\views\sync\<time>\sync-overview.png`, `sync-strips-<n>.png`;
  `cache\timing\views\trajectory\<time>\trajectory.png`.

## 9. Tests

```
cd C:\LetItEdit\bridge
python -m pytest test_music_sync.py test_trajectory.py -q -m "not real"     # 32 unit tests, ~2 s
python -m pytest test_music_sync.py test_trajectory.py -q                   # + 14 real-material tests
cd C:\LetItEdit\cache\timing-tests\b4
python make_songs.py; python build_synthetic.py; python validate.py syn-cuts-30 syn-map-25 syn-waltz-2997 syn-vert-30
python run_real.py                                                           # A/B projects and renders
```

## 10. Limits (said in the results too)

- The level as heard is the songs' loudness + clip/track gain and fades; Shotcut's track auto-duck and the master chain
  are not modelled (`unsupported` says so when a track ducks).
- Tempo level: one level per song is chosen (Beat This!'s, checked against a tempo preference); a song felt at half or
  double speed is measured on the chosen level (warned when two levels score close); the half-beat offset covers 8ths.
- A video's sound onsets are not SFX (no effects stem): music notes off the beat can remain among them.
- Story sections from target_s shares are estimates (said: `mapped_by`).
- The index is relative to the edit; gears are judged by the skills, not computed.
