# Timing perception layer: the shared spec (28 Oct 2026)

Plan (approved by the owner): Claude Doc "Teaching letitedit's AI to see motion, rhythm and timing"
(https://claude.ai/artifact/W5JUNB374PrcRxMzsU5QMa). The AI editor can't watch or hear; this layer turns an edit's motion,
rhythm and timing into frame-accurate signals and views it can read, so editing, the review, the critic and the blind
judge can all see timing. Several builders work in parallel: each owns its own files (below) and codes to this spec.

## Principles
- One shared signal store; every view and check reads the same numbers. Judgment stays in the skills; tools measure.
- Frame-accurate on the edit's own frame grid. Times in seconds AND frames everywhere.
- Analyse what the viewer gets: for a project (.mlt), a preview render of the timeline (same fps, small size, with
  sound) made by melt; for a video file, the file itself. Cache by content so a small edit doesn't redo everything.
- Every measure exposes its raw value, unit, method and the threshold used; thresholds live in
  `bridge/timing_thresholds.json` (one key per measure) so calibration against human choices can retune them without
  code changes. Nothing is reported as good/bad without its number.
- State what isn't supported or wasn't checked (`unsupported`, `unchecked_ranges`, `warnings`), never guess.
- Common contract fields on every tool result: schema_version, result_id, project_revision (when a project),
  source_fingerprints, checked_ranges, unchecked_ranges, warnings, unsupported, preview_artifacts, changes: [].
- Works for Claude and Codex through MCP and the Python module (`letitedit_ai`). CPU-first where possible; GPU work goes
  through model_tools' GPU turn (it now shares memory across processes). Renders take the PC render lock
  (render_lock.slot) when longer than 30 s of timeline.
- Never copy, move or delete footage. Test outputs under `C:\LetItEdit\cache\timing-tests\<area>\`.

## The store (owner: B1, `timing_signals.py`)
```python
signals(source, start=None, end=None, lanes=None, refresh=False, settings=None) -> dict
```
`source`: a project path (.mlt) or a video path. `lanes`: list of lane names (default: all registered). Returns:
```
{'schema_version': 1, 'source': str, 'kind': 'project'|'video', 'fps': float, 'frames': int, 'duration_s': float,
 'size': [w, h], 'analysed_size': [w, h], 'render': <preview path or None>, 'key': <cache key>,
 'lanes': {<lane>: {'method': str, 'version': int, 'settings': {...}, 'warnings': [...], 'unsupported': [...], ...data}},
 'warnings': [...], 'unsupported': [...], 'seconds': float}
```
Per-frame series are lists aligned to frame index 0..frames-1 (or numpy arrays inside Python; JSON in the cache).
Lanes (data keys):
- `edit` (B1): `cuts` [{f, t, kind: cut|dissolve|fade, from_item, to_item, from_clip, to_clip}] from the edit script
  (project) or from shots.detect (video); `items` [{id, track, f0, f1, clip, in_s, out_s}]; `graphics`
  [{f0, f1, kind: text|graphic|caption, text}]; `transitions`; `split_edits`.
- `motion` (B1): per frame `energy` (mean flow magnitude after removing the camera's own move, px/frame at the
  analysed size), `camera` {dx, dy, zoom, rot} per frame, `camera_label` per frame (static|pan|tilt|zoom|handheld|
  whip), `direction` per frame (dominant subject-motion angle in degrees or None), `region` per frame (box of the
  strongest moving region, 0-1 coords, or None).
- `visual_beats` (B1): [{f, t, strength}] where motion decelerates sharply (Davis & Agrawala 2018: local minima of
  motion speed after a peak).
- `motion_events` (B1): [{f0, f_peak, f1, t0, t_peak, t1, strength, region}] onset, peak and end of each burst of
  subject motion.
- `attention` (B1): per sampled frame (every frame or every 2nd) {x, y, spread} of a saliency estimate, plus `faces`
  [{f, boxes: [[x0, y0, x1, y1, score]]}]. A still-image saliency model is acceptable (Tangemann et al.).
- `shots` (B1): [{f0, f1, kind_in, size: closeup|medium|wide|unknown, size_basis}] (size from face height or the
  `meaning` lane when present).
- `audio` (B1): every 10 ms `loudness_db` (short-term), `flux` (spectral flux); `onsets` [{t, strength}].
- `speech` (B3, `prosody.py` registers it): `words` [{t0, t1, w, stress: 0-1}], `pauses` [{t0, t1}], `f0` and
  `energy` every 10 ms (Hz or None; dB), `thought_ends` [{t, strength, cues: [pause, slowing, pitch_reset]}],
  `breaths` [{t0, t1}], `speech_rate` per word.
- `music` (B4, `music_sync.py` registers it): `beats` [{t, f, downbeat: bool, bar, phrase}], `tempo_bpm`,
  `beat_confidence`, `sections` [{t0, t1, label, energy}], `energy` every 0.5 s, `stem`: how music was isolated.
- `meaning` (B6, `motion_meaning.py` registers it): [{f0, f1, label, completes: bool|None, confidence,
  accuracy_basis}] what happens in motion events and shots, from the local vision model, each label type with its
  measured accuracy.

Lane registry (B1 implements in `timing_signals.py`; others call it at import):
```python
register_lane(name, compute, depends=(), version=1)   # compute(ctx) -> dict for that lane
# ctx: {'source', 'kind', 'video' (analysis file path), 'fps', 'frames', 'duration_s', 'project' (path or None),
#       'script' (edit script dict or None), 'lanes' (already computed dependencies), 'settings', 'cache_dir'}
```
Cache: `C:\LetItEdit\cache\timing\<key>\<lane>.json` with key = hash(source content fingerprint or edit-script hash
+ preview settings) and the lane's version + settings in its file name, so a lane recomputes alone when its code or
settings change.

## The views and the one tool (owner of the tool: B1, `timing_tools.py`)
One MCP tool keeps the tool list short:
```python
letitedit_timing(source, view='map', start_s=None, end_s=None, items=None, cuts=None, options=None,
               detail='brief', images=2, refresh=False) -> [images..., result dict]
```
Views register themselves (`timing_views.py`, created by B1; API below) so modules plug in without editing the tool:
```python
# timing_views.py
register_view(name, fn, summary)   # fn(source, start_s, end_s, items, cuts, options, detail) -> dict with
                                   # 'images': [paths], plus the common contract fields and the view's data
```
| view | owner | what |
| --- | --- | --- |
| `map` | B1 | the rhythm map: lanes for shots, motion, camera, speech and pauses, music beats and sections, graphics, loudness; every cut marked by its offset from the nearest beat and whether it lands on action; numbers per section (sections: story plan / chapter markers, else pace changes) |
| `slow` | B1 | 1-3 s at 10-15 fps (or every frame) with motion arrows and attention dots: the AI's "scrub" |
| `cuts` | B2 | cut inspector: frames around each cut at full rate with motion and attention drawn; per cut: action phase at the cut, motion continuity, eye-trace jump, screen direction, jump cut / size change, sound across the join (from `joins`) |
| `speech` | B3 | words with pitch and energy curves, thought ends, stressed words, breaths, the space after key lines |
| `joins` | B3 | per cut: click (sample discontinuity), level jump, room-tone gap, spectral jump |
| `sync` | B4 | picture events (cuts, motion peaks, visual beats, text pops, SFX onsets) against the beat grid: offsets in frames, on-beat share, monotony; speech gaps against music swells; song sections against story sections; SFX against the impacts they belong to |
| `trajectory` | B4 | energy over time (cut rate, motion, music, speech) against each plan section's intended gear and feel |
| `meaning` | B6 | the labelled motion events and shots (what happens, does the step complete), with accuracy |

## Test material
- Our A/B renders and projects: `C:\LetItEdit\loops\rounds\20261028-*-ab3-*`, `*-ab4-*`, `*-ab5-*` (`renders\*.mp4`
  plus the `.mlt` projects): story long and Short, montage, how-to.
- Raw footage: `C:\LetItEdit\test-footage\{quick, story-mini, story-rear-ac, broll}` (read-only).
- Professional edits (if downloaded): `C:\LetItEdit\test-footage\pro-edits\` (Blender open movies, CC-BY).
- Labelled cuts: `C:\LetItEdit\tests\fixtures\range-search\cuts_edits.json` (167 true boundaries).

## Rules for every builder
- Own only your files. Don't edit shared registration files (letitedit_mcp.py, letitedit_ai.py, tool_docs_v2.py, GUIDE*.md,
  skills/); write `bridge\INTEGRATION-<area>.md` with exact lines. B1 owns timing_tools.py and timing_views.py.
- Don't touch running editor windows; never stop processes you didn't start; never copy footage. Don't commit.
- Tests: `bridge\test_<area>.py` (pytest), fast unit tests plus real-footage tests on at least 3 sets; measure
  against labels you make by looking at frames (Read tool) or listening via measurements; report numbers honestly.
- Write scripts with the Write tool (Git Bash heredocs mangle backslashes).
