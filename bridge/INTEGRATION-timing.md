# Integrating the timing perception layer (B1: store, render, picture/sound lanes, `map`, `slow`, the tool)

Built 2026-10-28 to TIMING-SPEC.md (plan: Claude Doc "Teaching letitedit's AI to see motion, rhythm and timing").
Nothing shared was edited; the lines to add are below. Other builders' modules (cut_inspect, prosody,
music_sync, trajectory, motion_meaning) are listed in `timing_signals.PLUGINS` and imported by `timing_signals.load_plugins()`.

## Files (B1)

| File | What |
|---|---|
| `bridge/timing_signals.py` | The store. `signals()`, `register_lane()`, `lanes()`, thresholds, cache, the `edit` lane, helpers (`array`, `clean`, `series`, `in_window`, `read_markers`, `fr`, `tsec`, `grid_fps`, `active_area`, `cropped_proxy`). CLI: `python timing_signals.py <source> [--lanes a,b] [--start s --end s] [--refresh]`. |
| `bridge/timing_render.py` | Chunk-cached melt preview renders of a project (`preview`, `use_existing`, `chunks_of`, `extract_audio`, `video_ok`, `audio_ok`). |
| `bridge/timing_motion.py` | Lanes `frame_features` (per-chunk cached), `motion`, `visual_beats`, `motion_events`, `attention`, `shots`; `load_features`, `camera_labels`, `cut_mask`. |
| `bridge/timing_audio.py` | Lane `audio` (`analyse(wav)`). |
| `bridge/timing_views.py` | View registry: `register_view`, `views`, `get`, `run`, `common_fields`, `result_id`, `CONTRACT`. |
| `bridge/rhythm_map.py` | View `map`. |
| `bridge/timing_slow.py` | View `slow`. |
| `bridge/timing_tools.py` | The one MCP tool `letitedit_timing` (`register(mcp, Image)`), Python `timing(...)`. |
| `bridge/timing_thresholds.json` | One key per measure `{value, unit, about}`; B1 keys: `store.*`, `frame_features.*`, `motion.*`, `visual_beats.*`, `motion_events.*`, `attention.*`, `shots.*` (others add theirs; write it back with `json.dumps(d, indent=1, sort_keys=True, ensure_ascii=False)`). |
| `bridge/tests/timing/test_timing_signals.py`, `bridge/tests/timing/test_rhythm_map.py` | pytest. Fast: 25 + 6 tests (synthetic ffmpeg video, synthetic colour projects; ~30 s warm, ~2 min cold). `LETITEDIT_TIMING_REAL=1` adds 5 + 3 real-footage tests. Run: `cd C:\LetItEdit\bridge && python -m pytest test_timing_signals.py test_rhythm_map.py -q`. |

## API as built

```python
timing_signals.signals(source, start=None, end=None, lanes=None, refresh=False, settings=None) -> dict
timing_signals.register_lane(name, compute, depends=(), version=1, optional=())   # compute(ctx) -> dict
timing_signals.lanes(load=True) -> {name: {depends, optional, version, module}}
timing_signals.threshold(name, default=None); timing_signals.thresholds(prefix) -> {key: value}
timing_signals.lane_settings(lane, defaults=None, given=None) -> dict   # defaults < json '<lane>.*' < given
timing_signals.array(sig, lane, key, sub=None) -> np.ndarray            # None -> NaN
timing_views.register_view(name, fn, summary)   # fn(source, start_s, end_s, items, cuts, options, detail) -> dict
timing_views.run(name, source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief')
timing_views.common_fields(source=None, sig=None, view=None, inputs=None, checked_ranges=None, unchecked_ranges=None,
                           warnings=None, unsupported=None, preview_artifacts=None) -> dict
timing_tools.timing(source, view='map', start_s=None, end_s=None, items=None, cuts=None, options=None,
                    detail='brief', refresh=False) -> dict      # adds result_file
letitedit_timing(source, view='map', start_s=None, end_s=None, items=None, cuts=None, options=None,
               detail='brief', images=2, refresh=False) -> [images..., result dict]
```

`signals()` result: `schema_version, source, kind, fps, frames, duration_s, size, analysed_size, render` (preview
.mp4, projects), `audio` (sample-exact .wav, projects), `render_info, key, project, project_revision` (edit-script
file hash, as other tools), `source_fingerprints, range, checked_ranges, unchecked_ranges, lanes, warnings,
unsupported, conventions, cache_dir, seconds`. Each lane carries `method, version, settings, warnings, unsupported,
seconds, identity` (+ `error`, `trace` when it failed: one lane failing never loses the others).

`settings`: `{lane: {key: value}}` plus `store: {preview_px, max_whole_s, pad_s, video, refresh_render}`;
`store.video` = an existing full render of the project to analyse instead of a preview (checked: same fps, frame
count +-1, shape). `refresh`: True or a list of lanes.

ctx given to `compute(ctx)`: `source, kind, video` (analysis file), `audio` (project: the preview .wav; video: None,
use `timing_render.extract_audio(ctx['video'])`), `fps, frames, duration_s, size, analysed_size, project, script,
timeline` (timeline_model), `markers, lanes` (dependencies, plus optional ones already computed), `settings` (the
lane's effective settings, and the caller's raw overrides under `settings[<lane>]`), `all_settings, cache_dir,
range` [f0, f1), `render` (preview info with `chunks` for per-chunk caching), `source_fingerprint, key, lane,
probe` (videos). A partial preview (`range` not the whole) starts at timeline frame `render['f0']`.

Conventions (in every result): frames on the source grid, `t = f / fps`; ranges half-open `[f0, f1)`; per-frame
series of length `frames` (None = not measured); audio series every 10 ms from t = 0; boxes `[x0, y0, x1, y1]` in
0-1; angles 0 = right, 90 = up. Variable-frame-rate files (phones writing 120 fps for ~25 fps footage) use their
average rate as the grid; short gaps take the step measured across them (warned).

Lanes (all B1 lanes are cheap after `frame_features`):
- `edit` v3: `cuts [{f, t, kind cut|dissolve|fade, f0, f1, from_item, to_item, from_clip, to_clip, from_track,
  to_track, detail, transition, same_clip, source_jump_s}]` (dissolve/fade: `f` = middle, `f0/f1` its span),
  `items, pictures` (runs of the top picture), `graphics [{f0, f1, kind text|graphic|caption, text, visible}]`,
  `text_pops` (every word pop of word_captions, every graphic/caption start), `transitions, split_edits` (J/L with
  the cut they cross), `markers`. Videos: shots.detect; when bars (pillar/letterbox) are on >= 20% of frames, the
  picture part is checked too (`active_area`, a cropped analysis copy in `cache\timing\crops`).
- `frame_features` v2 (internal: where the per-chunk npz files are; `timing_motion.load_features(sig or ctx)`).
- `motion` v1: `energy, camera {dx, dy, zoom, rot}, camera_label, camera_speed, camera_jitter, camera_trust,
  direction, region, moving_share, energy_p90, raw_energy, in_transition, unmeasured, camera_moves, units`.
- `visual_beats` v2: `beats [{f, t, strength, drop, f_stop, t_stop, speed_before, speed_after}], envelope`.
- `motion_events` v2: `events [{f0, f_peak, f1, t0, t_peak, t1, strength, peak_energy, rest_energy, region,
  direction, duration_s}]`.
- `attention` v1: `x, y, spread` per frame, `faces [{f, t, boxes [[x0, y0, x1, y1, score]]}]` every 3rd frame.
- `shots` v1: `shots [{f0, f1, t0, t1, seconds, kind_in, size, size_basis, face_height, face_share, item, clip,
  black}]`; unknown sizes take the `meaning` lane's label after both ran (`size_from: 'meaning'`).
- `audio` v1: `loudness_db` (K-weighted, 0.4 s), `level_db` (30 ms), `flux`, `onsets [{t, f, strength, level_db}]`.

## 1. `bridge/letitedit_mcp.py`

Before `if __name__ == "__main__":`:

```python
# Timing, motion and rhythm of an edit or a video (one tool, one view per question: map, slow, cuts, speech, joins,
# sync, trajectory, meaning).
from timing_tools import register as register_timing
register_timing(mcp, Image)
```

In `V2_NEW` (works on files, so it is also UNSCOPED through V2_NEW):

```python
    'letitedit_timing',
```

Optionally also in `CORE_TOOLS` once the views settle (it returns pictures, so a candidate for `LEAN_TOOLS` too).

## 2. `bridge/letitedit_ai.py` (`_registry()`)

```python
    import timing_tools
```

and add `timing_tools` to the `for mod in (...)` tuple (e.g. after `reframe_tools`). Then
`sa.tool('timing', source=r'C:\...\edit.mlt', view='map')` returns the dict with page images under `images`.

## 3. `bridge/tool_docs_v2.py` (`SHORT`)

```python
    'letitedit_timing': "Timing, motion and rhythm as pictures and numbers, frame-accurate: view='map' (the rhythm "
                      "map: shots and sizes, motion with the camera's own move removed, camera labels, speech, "
                      "music beats, captions, loudness; every cut flagged by its offset from the beat and whether it "
                      "lands on action; numbers per section), 'slow' (1-3 s frame by frame with motion arrows and "
                      "the likely eye position), 'cuts', 'speech', 'joins', 'sync', 'trajectory', 'meaning'. Works "
                      "on a project (a cached small render of it) or a video file; nothing is edited.",
```

## 4. `tools/integrate_tools.py` (`TOOLS`), if used

```python
    'timing': dict(
        module='timing_tools', register='register_timing', tool='letitedit_timing',
        comment='# Timing, motion and rhythm of an edit or a video (one tool, one view per question).',
        short=<the SHORT text above>),
```

## 5. Guide

- `tools/build_guide_v2.py` `ORDER`: `'letitedit_timing'` after `'letitedit_check_range'` (or after `'letitedit_find_ranges'`).
- GUIDE.md (checks section), one line: "`letitedit_timing(project, view='map')`: the rhythm map of an edit (cuts on
  beats and action, motion, speech, music, sections); `view='slow', start_s=...` to scrub 1-3 s frame by frame."
- Skills (letitedit-fine, -sound, -gate, -review): read the map before judging pace; quote its numbers (cut rate,
  median shot, cuts on action/beat) rather than impressions. Wording is the skill owners' call.

## 6. Load and caches

- Load (after two hard crashes on 28 Oct under combined load): melt renders one chunk at a time
  (`LETITEDIT_TIMING_RENDER_PARALLEL`, default 1; melt `threads=4`), ffmpeg `-threads 4`, frame analysis 3 worker
  threads with OpenCV at 1 thread each (`frame_features.workers`), no GPU. Renders over 30 s of timeline hold the PC
  render lock.
- Crash safety: every cache file is flushed (fsync) before it is renamed into place, and cached chunks, previews
  and feature files are checked before reuse (frame count, sound length, loadable); a bad one is redone. (Before
  this, the 10:43 crash left 12 torn cache files; they were found and removed.)
- `cache\timing\<key>\<lane>-v<version>-<identity>.json` lanes; `cache\timing\chunks\` render chunks (`v-<fp>-...mp4`,
  `a-<fp>-...wav`); `cache\timing\previews\` joined previews; `cache\timing\features\` per-chunk npz;
  `cache\timing\audio\` extracted sound of videos; `cache\timing\areas\`, `crops\` bar detection;
  `cache\timing\maps\`, `slow\`, `results\` view outputs. Chunks + previews are pruned at 6 GB (LRU); the rest is not.
- A lane's cache identity = its version + settings + its dependencies' identities. Bump `version` in
  `register_lane` whenever the computation changes (a stale result is otherwise reused: seen during calibration).

## 7. Measured (2026-10-28) — see the final report for the full list

- Cut frames vs the render: 192/192 hard cuts of 11 A/B round projects land where the rendered picture changes (3
  apparent 1-3 frame offsets were neighbouring real cuts: a 2-frame item, two 1-frame flashes in
  ab3-tutorial-old/fan-swap.mlt at 31.83 s and 32.37 s, an overlay ending 3 frames before a jump cut).
- Pillarboxed cuts (B4's syn-cuts-30 render): 15/15 exact (5/15 before). Vertical montage render: all lanes run.
- Camera labels vs 221 hand-labelled 0.5 s bins (8 raw clips): 60% exact (thresholds tuned on these labels; 50%
  leave-one-clip-out), 77% at still / moving / zoom level.
- Motion events vs 25 labelled silent actions: 23 found; onsets a median 0.74 s off (events start early: they
  include the approach), ends 0.37 s.
- Cost, 3:16 1080p edit: cold 208 s with 4 renders side by side (render 165 s, features 35 s, sound 6.5 s, the rest
  < 2 s, map 5 s); one render at a time is slower. After a 1 s trim near the end: 2 of 10 chunks re-rendered and
  re-analysed, 75 s.
