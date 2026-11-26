# letitedit\timing

The timing layer: frame-accurate lanes and views (letitedit_timing).

- `cut_inspect`: Cut inspector: what happens at each cut, measured, with the frames to look at (the timing layer's 'cuts' view).
- `joins`: Sound across every cut: the 'joins' view, the 'joins' lane and the per-cut measures the cut inspector shows (builder B3, TIMING-SPEC.md).
- `motion_meaning`: Motion meaning: what happens in each motion event and each shot of a video or an edit, read by the local vision model, every label type with its accuracy measured on a labelled set.
- `music_sync`: Music against picture for the timing layer: the 'music' lane and the 'sync' view (builder B4, TIMING-SPEC.md).
- `prosody`: Speech rhythm for the timing layer: the 'speech' lane and the 'speech' view (builder B3, TIMING-SPEC.md).
- `rhythm_map`: The rhythm map (timing view 'map'): one picture per page of an edit's timing, plus the numbers behind it.
- `timing_audio`: Sound lane of the timing store (timing_signals): `audio`, every 10 ms from t = 0.
- `timing_motion`: Picture lanes of the timing store (timing_signals): frame_features, motion, visual_beats, motion_events, attention, shots.
- `timing_render`: Preview renders of a project's timeline for the timing layer: what the viewer gets, at a small size, with sound, on the timeline's own frame grid.
- `timing_signals`: The timing signal store (TIMING-SPEC.md): one set of frame-accurate measurements of an edit's motion, rhythm and timing that every timing view and check reads.
- `timing_slow`: The 'slow' timing view: the AI's scrub.
- `timing_views`: View registry of the timing perception layer (TIMING-SPEC.md): modules plug a view into the one MCP tool (`letitedit_timing`, timing_tools.py) without editing it.
- `trajectory`: Energy over time against the story plan: the 'trajectory' view of the timing layer (builder B4, TIMING-SPEC.md).
- `cut_inspect_base`: The settings and thresholds, small helpers, the per-thread OpenCV objects and decoding.  (no old name: imported as `letitedit.timing.cut_inspect_base`)
- `cut_inspect_cuts`: Where the cuts are.  (no old name: imported as `letitedit.timing.cut_inspect_cuts`)
- `cut_inspect_draw`: The strips drawn.  (no old name: imported as `letitedit.timing.cut_inspect_draw`)
- `cut_inspect_frames`: The per-frame analysis, the action phase and a detected cut snapped to its frame.  (no old name: imported as `letitedit.timing.cut_inspect_frames`)
- `cut_inspect_join`: A join measured, its verdict, and the sound across it.  (no old name: imported as `letitedit.timing.cut_inspect_join`)
- `cut_inspect_validate`: The validation: real cuts against the same cuts moved.  (no old name: imported as `letitedit.timing.cut_inspect_validate`)
- `music_sync_base`: The settings, small helpers and the thresholds.  (no old name: imported as `letitedit.timing.music_sync_base`)
- `music_sync_draw`: The strips drawn.  (no old name: imported as `letitedit.timing.music_sync_draw`)
- `music_sync_measure`: Picture events, the measures, speech against music, song sections against story sections, SFX against impacts.  (no old name: imported as `letitedit.timing.music_sync_measure`)

Each module here also answers to its old name in `bridge\` (a small alias file: one module object under both names); inside the package, import the real name. What the other jobs may use from here: `IMPORTS.md`. The whole map: `CODEMAP.md` at the top of the repository.
