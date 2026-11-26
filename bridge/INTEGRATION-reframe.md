# Integrating letitedit_reframe (reframing solver)

New files, plus one small backward-compatible change to `formats.py` (and a docstring paragraph in
`formats_tools.py`). No shared registration file was edited.

| File | What it is |
|---|---|
| `bridge/reframe.py` | The solver: subjects (faces, motion with the camera taken out, given boxes tracked with VitTrack and carried with the camera's motion when lost, saved tracker results, the camera's aim), the crop path (one sparse linear program per clip, HiGHS through scipy), fit analysis and can't-fit spans, keyframes checked with the engine's keyframe arithmetic, coverage and smoothness, split / inset offers as edit ops, the plan / preview / render-check / apply flow, and `version_item` for linked versions. |
| `bridge/reframe_tools.py` | Thin MCP wrapper: `register(mcp, Image)` exposes `letitedit_reframe` (its docstring is the manual). |
| `bridge/tests/pictures/test_reframe.py` | pytest suite (21 tests; under a minute with warm caches, a few minutes cold; synthetic clips plus the test footage when present; renders with melt). Outputs in `C:\LetItEdit\cache\reframe-tests\pytest`. |
| `bridge/formats.py` | `REFRAME_DEFAULTS` gains `mode` (`'follow'`, the old behaviour and still the default, or `'solve'`) and the solve options `keep`, `priorities`, `sources`, `platform`, `solver`; `reframe_item` hands `mode: 'solve'` to `reframe.version_item`; `_settings` validates `mode`; `_brief` also passes `coverage`, `cant_fit`, `offers`. test_formats.py: 8 passed before and after. |
| `bridge/formats_tools.py` | one paragraph in the `letitedit_versions` docstring describing `reframe={'mode': 'solve', ...}`. |

Evaluation material (not code): `C:\LetItEdit\cache\reframe-tests\` - `labels\labels.json` (hand labels),
`labels\sheets\*.png` (the grid sheets they were read from), `tools\` (evaluate.py, why.py, renders.py, cases.py,
sheets.py, detect_check.py, synth_solver.py, projects.py), `results\` (eval.json, renders, sheets).

## 1. letitedit_mcp.py

Add the name to `V2_NEW` (the v2 toolset; the module registry test requires it in the same change as the
`letitedit_ai.py` line below):

```python
    'letitedit_reframe',      # crops of another shape keeping several subjects in frame; split / inset offers
```

Register it with the other v2 modules (after `register_caption_fit(mcp, Image)` is a good place):

```python
# Reframing solver: crops of another shape that keep faces, hands and the shown part in frame; split / inset offers.
from reframe_tools import register as register_reframe
register_reframe(mcp, Image)
```

## 2. letitedit_ai.py, `_registry()`

```python
    import reframe_tools
    for mod in (check_tools, timeline_tools, kit_tools, core_tools, v2_tools, jobs_tools, journal_tools,
                platforms_tools, hardware_tools, reference_tools, thumbs_tools, geo_tools, formats_tools,
                archive_tools, editor_tools, fix_tools, render3d_tools, maps_tools, music_gen_tools, factlog_tools,
                review_tools, takes_tools, shot_match_tools, annotate_tools, soundtrack_tools, caption_layout_tools,
                reframe_tools):
        mod.register(_Collect(), _SavedImage)
```

Optional Python convenience beside the other wrappers there:

```python
def reframe(project=None, **params):
    """letitedit_reframe as a function: plan (and with apply=True apply) crops of another shape for a project's clips,
    or for file=..., source_range=..., target=... without a project."""
    return tool('letitedit_reframe', project=project, **params)
```

Module-level use without the tool layer: `reframe.plan(...)`, `reframe.apply_plan(plan_or_id, choose=...)`,
`reframe.solve_clip(file, a, b, (w, h), fps, keep=...)`, `reframe.load_plan(plan_id)`.

## 3. tool_docs_v2.py, `SHORT`

```python
    'letitedit_reframe': "Reframe clips to another shape (9:16, 4:5, 1:1, 16:9) keeping several things in frame at once "
                       "- faces, hands, the part being shown, boxes you name - on a smooth, mostly still crop path "
                       "(keyframed Size/Position); per subject how much of the time it is fully in the crop; where "
                       "the required ones can't share one crop it says when and which, and offers a split or an "
                       "inset as ready edits. apply=True writes (one undo step).",
```

## 4. GUIDE_V2.md (the index) and GUIDE.md

Index line, after `letitedit_versions`:

```
- `letitedit_reframe`: Reframe clips to another shape keeping several things in frame (faces, hands, the shown part, named boxes) on a smooth crop path; coverage per subject; where required subjects can't share one crop: when, which, and split / inset offers as ready edits; apply=True writes.
```

GUIDE.md (suggested, under formats / vertical versions):

> `letitedit_reframe(project, keep=[...])` crops the project's clips to its frame keeping the named things in view:
> `keep` in rank order, each a name ('face', 'hands') or `{label, box: [x0, y0, x1, y1], at}` in the clip's own
> upright picture (0-1). It returns a preview sheet, per-subject coverage, the moments where they can't share
> one crop, and split / inset offers (`choose={clip id: 'split'}` with `apply=True`). For a new size,
> `letitedit_versions(project, 'make', target='9:16', reframe={'mode': 'solve', 'keep': [...]})`.

## 5. Skills (not edited)

`letitedit-shorts` says "reframed to 9:16 with letitedit_versions": it could name `reframe={'mode': 'solve', 'keep':
[...]}` and `letitedit_reframe` for clips where a face and the shown part both matter. A skill change, not made here.

## 6. Contract notes

- Proposal and mutation are separate: `plan` never writes the project; previews and plans go to
  `cache\reframe\<plan_id>\` and `cache\reframe\plans\<plan_id>.json`. `apply=True` or `plan_id` + `apply=True`
  applies through `timeline_tools.apply_project` (an open window gets one native undo step; else the file with a
  history copy, `letitedit_timeline_undo` restores it), refused when the project revision or a source fingerprint
  changed (`edit_script.Conflict`). `choose` swaps a clip's crop for its split / inset ops.
- Result fields: `schema_version` (`letitedit-reframe/1`), `plan_id` (= `result_id`), `project_revision`,
  `source_fingerprints`, `changes`, `offers`, `cant_fit`, per-item `coverage` and `smoothness`, `render_check`,
  `checked_ranges` / `unchecked_ranges`, `warnings`, `unsupported`, `preview_artifacts`.
- Coverage is computed on every frame of the keyframes as the engine interpolates them (annotate.anim_values),
  against the subjects' boxes as the finders/tracker saw them; the render check compares melt frames with the
  planned crop of the source frame (phase correlation + mean difference), at the preview frames only.
- Caches: subject finders cache per file content and range in `cache\reframe\subjects` (faces, motion, tracking);
  re-planning with other priorities costs only the solve (well under a second for a minute of clip).
- GPU: none. Faces (YuNet), motion (OpenCV) and tracking (VitTrack) run on the CPU; HiGHS solves the paths.

## 7. Evaluation (2026-10-28, `C:\LetItEdit\cache\reframe-tests\`)

17 clips from three sets (quick 4, story-rear-ac 9, broll 4), 41 clip x target cases (1:1, 4:5, 9:16, 16:9), 264
required-subject labels drawn by hand at 5-6 times per clip (`labels\labels.json`). Old = `formats.reframe_item`
(one point; 'old-hint' gets the same subject track as a focus point). New = `reframe.solve_clip` (final defaults).
Share of labelled frames with each required subject fully inside the crop (`results\eval-final.json`; the small
script that summed it into this table was not kept):

| set | old centre | old action | old + hint | new auto | new + 1 box | new + boxes (held-out times) |
|---|---|---|---|---|---|---|
| broll | 61% | 61% | 64% | 78% | 79% | 74% |
| quick | 48% | 50% | 75% | 54% | 77% | 72% |
| story-rear-ac | 39% | 33% | 45% | 46% | 52% | 39% |
| all | 47% | 44% | 56% | 56% | 64% | 54% |

The demonstrated object/tool where it alone fits the crop (`results\object-when-fits.json`): new + box 114/148
(77%), old + hint 98/148 (66%), old centre 95/148 (64%). Smoothness of the new path (output px, median | worst over
cases): max speed 357 | 908 px/s, max acceleration over 0.2 s 1224 | 1741 px/s2, held still 38% of the time. MP4
renders by melt (`results\renders\`, `renders-recheck.json`): 28 of 29 checked frames match the planned crop of the
exact source frame (shift <= 2.4 px; one fast-motion frame 8.2 px); the split and inset renders show both groups.
