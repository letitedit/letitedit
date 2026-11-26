# letitedit\timeline

A project's timeline: reading, editing and exporting it.

- `adjust`: Adjustment layers: a block on a track that changes everything below it in the stack and nothing above it.
- `aim`: {op: aim}: one effect on a chosen part of the video, made of pieces the engine already has (a clip's, a track's or the whole video's effects, a mask around an effect, cut-out clips).
- `chunk_cache`: Validation receipts for encoded chunks, tied to the bytes and render inputs.
- `cutpoints`: Cut points from words: find a spoken phrase in a source file and cut on the gaps around it.
- `declick`: a one-frame audio ramp on both sides of every straight sound cut, so the waveform can't jump.
- `edit_code`: Edits computed by the agent's own Python: letitedit_timeline_apply(code=...).
- `edit_effects`: Any engine effect in the edit script, with keyframes.
- `edit_import`: Edits written in other forms, in and out of Shotcut projects.
- `edit_script`: The edit script: Claude's readable view of a Shotcut timeline, and the compiler that writes it back.
- `edit_sync`: Word-level tightening and keeping other tracks/captions in sync with the main picture track.
- `effects_catalog`: Every effect Shotcut's engine (MLT 7) can apply: find it, read its settings, resolve it, preview it.
- `export_checks`: The project's own checks run on an export, kept beside the project as `<project>.export-checks.json`.
- `formats`: Linked versions of a project for other sizes and aspects (one project, every format).
- `letitedit_extras`: Helpers that need no running editor: new empty projects, a profile written into project XML, the export engine's path and its render presets.
- `loudness_finish`: Finish an exported video's sound the way letitedit_export does (render_queue.finish_audio): ONE measured, constant gain to the loudness target, then a true-peak limiter, so the balance inside the mix (voice over music, quiet pauses, a...
- `made`: Clips made from other clips, as timeline items: an ffmpeg filter graph, a reversed shot, a freeze frame, a shot effect (vfx), a narrated line (voice).
- `op_specs`: Every edit op letitedit_timeline_apply takes, in one place: its fields, which are needed, and what each does.
- `project_journal`: A project's own folder of edit records, beside its .mlt: <stem>.letitedit\ (named <stem>.shotcut\ before 30 Oct 2026: an old one is moved to the new name on first use, or merged into it when both exist; see folder())
- `render_queue`: Chunked, cached, resumable exports that survive crashes, reboots and closed AI sessions.
- `split_edit`: Split edits (J and L cuts) on any picture track, built from the timeline's ordinary pieces.
- `stack`: What is in front of what: a timeline's layers at a moment, back to front, from the script and the project's blends.
- `timeline_model`: Read a saved Shotcut/MLT project into a small model that tools can reason about without the editor.
- `timeline_speech`: What is said on the timeline, in timeline time: words for any range, and captions made from them.
- `edit_import_common`: The shared helpers: forms and file kinds, times, media files found and probed, the project written.  (no old name: imported as `letitedit.timeline.edit_import_common`)
- `edit_import_edl_otio`: CMX3600 EDLs and OpenTimelineIO JSON.  (no old name: imported as `letitedit.timeline.edit_import_edl_otio`)
- `edit_import_ffmpeg`: The ffmpeg form: command lines, their options and filter graphs rebuilt as tracks, the rest as made clips.  (no old name: imported as `letitedit.timeline.edit_import_ffmpeg`)
- `edit_import_lists`: Edit lists: a JSON or Python list of segments (or tracks of them), or a .py file that assigns one.  (no old name: imported as `letitedit.timeline.edit_import_lists`)
- `edit_import_scripts`: Scripts read as a shell would: .bat/.cmd/.ps1/.sh lines and .py files, their variables and calls.  (no old name: imported as `letitedit.timeline.edit_import_scripts`)
- `edit_script_base`: The settings and small helpers.  (no old name: imported as `letitedit.timeline.edit_script_base`)
- `edit_script_diff`: Two edit scripts compared, and the YAML form.  (no old name: imported as `letitedit.timeline.edit_script_diff`)
- `edit_script_project`: Project access: the document, its tracks and clips in friendly words.  (no old name: imported as `letitedit.timeline.edit_script_project`)
- `edit_script_reading`: Reading a project as an edit script with stable ids, with the track, master and caption readers it uses.  (no old name: imported as `letitedit.timeline.edit_script_reading`)
- `edit_script_transitions`: Transitions between clips.  (no old name: imported as `letitedit.timeline.edit_script_transitions`)
- `effects_catalog_build`: The index built and its categories.  (no old name: imported as `letitedit.timeline.effects_catalog_build`)
- `effects_catalog_qml`: A tiny QML/JS evaluator: what a filter's settings panel offers.  (no old name: imported as `letitedit.timeline.effects_catalog_qml`)
- `effects_catalog_services`: The engine's service metadata.  (no old name: imported as `letitedit.timeline.effects_catalog_services`)
- `effects_catalog_yaml`: The settings, and YAML read with PyYAML or a tolerant subset.  (no old name: imported as `letitedit.timeline.effects_catalog_yaml`)
- `episodes`: An old managed episode folder opened as a project: its timeline file, found through its episode.json.  (no old name: imported as `letitedit.timeline.episodes`)
- `multicam`: {op: multicam}: a camera-switched cut of several synced angles of one talk, as one change.
- `playback_preview`: Rendered playback previews: the timeline drawn once at a light size, in cached chunks, for smooth playback.

Each module here also answers to its old name in `bridge\` (a small alias file: one module object under both names); inside the package, import the real name. What the other jobs may use from here: `IMPORTS.md`. The whole map: `CODEMAP.md` at the top of the repository.
