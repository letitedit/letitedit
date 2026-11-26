# Integrating range search (`letitedit_find_ranges`) and the camera-move-proof cut detector (`shots.py`)

Built 2026-10-28 for the plan item "Range search: search returns exact start and end times with previews and stable
IDs; camera moves don't count as cuts". Nothing shared was registered: the lines to add are below.

## Files

| File | What |
|---|---|
| `bridge/shots.py` (new) | Cut detector. `detect(video, start=None, end=None, settings=None, kinds=None)` -> cuts (kind cut / punch / dissolve / fade, frame-accurate), shots, camera_moves, rejected (with the reason), settings, unsupported. `features(...)` per-frame measurements (cached), `scene_scores(...)` the old method's exact ffmpeg score (cached), `cut_times(video)`, `ffmpeg_cuts(video, cut_above)` (the old method, for comparison), `evaluate(found, truth, fps, tol_frames)`. |
| `bridge/range_search.py` (new) | Range search. `find(query \| example \| around \| range_ids, files, ranges, count, settings, previews, pad_s, out_dir)` -> result (contract below); `compact(result, detail)`; background job kind `range_search:job` (`submit(inputs)`). |
| `bridge/range_search_tools.py` (new) | MCP wrapper: `register(mcp, Image)` -> `letitedit_find_ranges` (its docstring is the manual). |
| `bridge/tests/footage/test_range_search.py` (new) | pytest, 19 tests (all pass, ~60 s): 15 fast (a synthetic video with a pan, cuts, a zoom and a fade; the range pipeline with faked model stages) and 4 footage/GPU tests (labelled edit cuts, raw camera moves, a labelled silent action with stable ids, `around`), skipped when footage or the model env is missing. |
| `bridge/index_worker.py` (changed, additive) | One new op `clip_window` (decode a short window once, embed every step-th frame with the index's own views) and its line in the module docstring. Nothing existing changed. `range_search` adds `'clip_window': ['clip-vit-b-32']` to `index_tools.INDEX_OP_MODELS` at run time, and restarts a worker started before the op existed (once). |

No other existing module was edited (not `index_tools.py`, `v2_tools.py`, `reference.py`, `checks.py`).
`test_index_tools.py` (real models, GPU) passes 10/10 with the committed `index_worker.py` and 10/10 with the
changed one. Run: `cd C:\LetItEdit\bridge && python -m pytest test_range_search.py -q` and
`python -m unittest test_index_tools`.

## 1. `bridge/letitedit_mcp.py`

Before `if __name__ == "__main__":`:

```python
# Exact ranges (first and last frame) of what is looked for in footage, with previews, stable ids and edit items.
from range_search_tools import register as register_find_ranges
register_find_ranges(mcp, Image)
```

In `V2_NEW`, e.g. after `'letitedit_search',` or before `'letitedit_import_srt',`:

```python
    'letitedit_find_ranges',
```

It works on files (no instance), so it is also `UNSCOPED` through `V2_NEW`. Not a core tool.

## 2. `bridge/letitedit_ai.py` (`_registry()`)

```python
    import range_search_tools
```

and add `range_search_tools` to the `for mod in (...)` tuple (e.g. after `takes_tools`). Then
`sa.tool('find_ranges', query='a hand turns the knob', files=r'C:\...\folder')` works; strip/overview images come
back as paths under `images`.

## 3. `bridge/tool_docs_v2.py` (`SHORT`)

```python
    'letitedit_find_ranges': "Exact ranges of what you describe in footage (picture first, so silent moments too): "
                           "first and last frame, peak, a before/start/peak/end/after strip, an edit_item for "
                           "letitedit_timeline_apply and an id that stays the same on every call; refines moments you "
                           "give (around=) or returns stored ones (range_ids=). Camera moves are not cuts.",
```

## 4. `tools/integrate_tools.py` (`TOOLS`), if that script is used

```python
    'find_ranges': dict(
        module='range_search_tools', register='register_find_ranges', tool='letitedit_find_ranges',
        comment='# Exact ranges (first and last frame) of what is looked for in footage, with previews, stable ids and edit items.',
        short="Exact ranges of what you describe in footage (picture first, so silent moments too): first and last "
              "frame, peak, a before/start/peak/end/after strip, an edit_item for letitedit_timeline_apply and an id "
              "that stays the same on every call; refines moments you give (around=) or returns stored ones "
              "(range_ids=). Camera moves are not cuts."),
```

`python tools/integrate_tools.py find_ranges` then does steps 1-3 and the GUIDE_V2.md index line.

## 5. Guide

- `tools/build_guide_v2.py` `ORDER`: add `'letitedit_find_ranges'` right after `'letitedit_search'`.
- `GUIDE_V2.md` tool list (the line integrate_tools writes):
  `- \`letitedit_find_ranges\`: <the SHORT text above>`
- Optional `GUIDE.md` line (search section): "`letitedit_find_ranges(query | example | around | range_ids, files)`:
  exact first/last frame of a moment, with a strip and an `edit_item`; ids are stable, so ask for a range again
  with `range_ids`."

## 6. Using the new cut detector elsewhere (not done; how to switch)

All of these use ffmpeg's scene score (`select gt(scene, X)`), which counts pans, whips, hands near the lens and
flashes as cuts. `shots.detect` is the drop-in: `[c['t'] for c in shots.detect(video, start, end)['cuts']]` (or
`shots.cut_times(video)`), kinds cut/punch/dissolve/fade (pass `kinds=['cut']` for hard cuts only).

| Where | Today | Switch | Tests to rerun |
|---|---|---|---|
| `reference.scene_cuts` / `reference._shots` (`letitedit_measure` shots, cuts per minute) | ffmpeg scene > 0.15 at 320 px | keep the `cut_above` parameter for callers that set it; when it is left at its default use `shots.detect(video, start_s, end_s)`; put `method: 'shots.detect'` and its settings in `settings` | `test_reference.py` |
| `checks.picture_change` shots (export job `picture_change`, gate's longest-static-shot) | ffmpeg scene > 0.15 on the full frame | replace the second ffmpeg pass with `shots.detect(video, start_s, end_s)`; keep `cut_above=None` = skip | `test_checks.py`, `test_r5_picture_change.py`, `test_a10_fixes.py` |
| `skills/letitedit-gate/scripts/gate.py` `shot_changes()` (cut rate, longest shot) | ffmpeg scene > 0.3 on the frame and its centre thirds | `shots.detect(path)`; its layout rule already handles footage in one part of the frame | `test_gate_modes.py` |
| `shot_log._cuts` / `segments` (footage log stretches) | ffmpeg scene > 0.3 at 160 px on raw footage | optional (raw footage: both are close; see the numbers below) | `test_shot_log.py` |
| `perception.picture_analysis` `cuts` (footage scan) | 10 fps phase-correlation rule | optional | `test_perception.py` |

`letitedit_check_frames(shots=True)` uses the project's clips, not detection: nothing to change.
`checks.picture_change`'s cost goes up (one more decode at 192 px plus corner tracking: about 150-400 analysed
frames per second per process on this PC, cached per file); long exports can call it with `settings={'workers': 6}`.

## 7. Caches and outputs

- `cache\range-search\shots\` per-frame features (npz, per file content + settings + range), `cache\range-search\scene\`
  ffmpeg scene scores, `cache\range-search\verify\` (the optional look-away check), `cache\range-search\dense\` dense
  picture embeddings around hits, `cache\range-search\ranges\<range_id>.json` every range returned (what
  `range_ids=` reads), `cache\range-search\<result_id>\` result.json, overview.jpg, previews\ strips and clips.
  Nothing prunes them; `dense` and `shots` window files grow with use (tens of KB each).
- The coarse pass writes the shared picture index (`cache\index\picture\...-e0p5-v1.npz` at every_s 0.5): it is
  also what `letitedit_search(every_s=0.5, frames='exact')` reads.
- Background: `letitedit_find_ranges(background=True)` -> jobs.py kind `range_search:job` (module:function, no
  registration).

## 8. Measured (2026-10-28)

Cut detector, 17 labelled edits (167 true boundaries incl. 6 punch-ins and 2 wipes; tolerance 2 frames), 51 raw
phone clips (57.7 min, no cuts: any cut is false) and a hold-out of 17 raw clips from another shoot (6.9 min, never
used for tuning). All thresholds were tuned on the edits and the 51 raw clips.

| Method | Edits precision | Recall | F1 | False cuts/min, raw | False cuts/min, hold-out |
|---|---|---|---|---|---|
| `shots.detect` defaults | 0.955 | 0.892 | 0.923 | 0.26 | 0.43 |
| same without the scene-score agreement | 0.933 | 0.910 | 0.921 | 0.35 | 2.31 |
| old: ffmpeg scene > 0.15 (what the tools use now) | 0.599 | 0.964 | 0.739 | 3.31 | 4.77 |
| old > 0.15, duplicates within 0.1 s merged | 0.750 | 0.952 | 0.839 | 2.11 | 3.61 |
| old > 0.25, merged (best old F1) | 0.916 | 0.850 | 0.882 | 0.66 | 0.29 |
| old > 0.30 | 0.928 | 0.772 | 0.843 | 0.55 | 0.29 |

Range search, 25 labelled short silent actions (0.5-3 s) in 21 picture queries over quick, broll and story-mini
(each query searches its whole folder; 14 of the actions contain at most one of the old index's sample frames):

| | old `letitedit_search` (picture, defaults) | `letitedit_find_ranges` (defaults) |
|---|---|---|
| found in top 1 / 3 / 5 / 10 (any overlap) | 9 / 12 / 15 / 16 | 8 / 13 / 17 / 22 |
| found in top 10 with overlap (tIoU) >= 0.3 | 11 | 14 |
| result's own moment inside the action +-0.25 s, top 10 | 11 | 16 |
| actions between old samples found, top 10 | 8 of 14 | 12 of 14 |
| median start / end error of the found range | 0.50 s / 0.65 s | 0.30 s / 0.40 s |
| start within 0.25 s / end within 0.25 s | 5 of 16 / 2 of 14 | 10 of 22 / 7 of 20 |
| median tIoU of found ranges | 0.49 | 0.50 |
| time per query | ~1 s (index cached) | 8 s warm, 25 s first time (median) |

`settings={'edges': 'motion'}` on the same set: 15 of 25 in the top 10, tIoU >= 0.3 for 5, start error 0.17 s, end
error 0.62 s: better starts, worse ends and fewer hits, so it is an option, not the default.

## 9. Labels and calibration (keep them)

`C:\LetItEdit\cache\range-search-tests\labels\cuts_edits.json` (167 true boundaries in 17 edits, with skips and
not-cuts), `actions.json` (25 short silent actions, 21 picture queries, 3 footage sets) and the scripts that made
and scored them (`calib\`, `eval\`, `labels\`). The cache is not in git: copy `labels\` to a tracked place (e.g.
`C:\LetItEdit\tests\fixtures\range-search\`) and point `LABELS` in `test_range_search.py` there.
