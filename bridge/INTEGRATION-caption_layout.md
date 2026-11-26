# Integrating letitedit_caption_fit (caption layout solver)

New files (no shared file was edited):

- `bridge/caption_layout.py`: the solver (`fit`, `apply_plan`, `load_plan`, `stale_reasons`, measuring, grouping,
  placement, render check).
- `bridge/caption_layout_tools.py`: the MCP wrapper, `register(mcp, Image)` -> `letitedit_caption_fit`.
- `bridge/tests/pictures/test_caption_layout.py`: 20 pytest tests (about 60 s; the integration ones need `app\melt.exe`; their
  projects, plans and renders go to `cache\caption-fit-tests\pytest`).

Fixture projects, the fixture runner and their outputs are in `C:\LetItEdit\cache\caption-fit-tests\`
(`build_fixtures.py`, `run_fixtures.py`, `results.json`, `runs\<fixture>\caption-fit-preview.png`).

## 1. letitedit_mcp.py

Add the tool to the v2 set (it works on files and finds an open window by project, like the other v2 tools):

```python
V2_NEW = {
    ...
    'letitedit_import_srt',   # captions back from the AI (translations) into a caption track of the open window
    'letitedit_caption_fit',  # caption layout: line breaks, grouping, size, place against faces/text/overlays
}
```

Register it next to the other v2 modules (after `register_thumbs(mcp, Image)` is a good place):

```python
# Caption layout: line breaks, grouping, size and place of captions against faces, other text and platform overlays.
from caption_layout_tools import register as register_caption_fit
register_caption_fit(mcp, Image)
```

## 2. letitedit_ai.py, `_registry()`

`test_a10_fixes.py::LeanSet::test_module_reaches_every_core_tool` requires the module registry to equal
`CORE_TOOLS | V2_NEW`, so this must land in the same change as the `V2_NEW` line:

```python
    import review_tools
    import caption_layout_tools
    for mod in (check_tools, timeline_tools, kit_tools, core_tools, v2_tools, jobs_tools, journal_tools,
                platforms_tools, hardware_tools, reference_tools, thumbs_tools, geo_tools, formats_tools, archive_tools,
                editor_tools, fix_tools, render3d_tools, maps_tools, music_gen_tools, factlog_tools, review_tools,
                caption_layout_tools):
        mod.register(_Collect(), _SavedImage)
```

(`_SavedImage(data=..., format='png')` matches what the wrapper passes to `Image`.) Python callers then get
`letitedit_ai.tool('letitedit_caption_fit', project=..., ...)`; `caption_layout.fit(...)` /
`caption_layout.apply_plan(...)` are the module functions underneath.

## 3. tool_docs_v2.py, `SHORT`

```python
    'letitedit_caption_fit': "Lay out a project's captions so every word reads: line breaks, grouping, size and a place "
                           "clear of faces, other text, platform buttons and protected regions; finds words that run "
                           "together (outline, shadow, pop peak). Returns editable changes, violations with times, "
                           "before|after crops from the export engine and what it could not solve; apply=True writes.",
```

## 4. GUIDE_V2.md (the index `letitedit_guide()` returns)

One index line, e.g. after `letitedit_platforms`:

```
- `letitedit_caption_fit`: Lay out captions (native caption tracks and word captions) against the picture: line breaks, grouping, size and a place clear of faces, other text, platform overlays and protected regions, words that run together found and fixed; editable changes, violations with times, before|after crops, unresolved constraints; apply=True writes.
```

The full description comes from the tool's docstring (`LONG_DOCS`, `letitedit_guide('caption_fit')`). The letitedit
finish skill (captions step) could call it after `{op: captions, ...}` and before export; that is a skill change,
not made here.

## 5. Changes needed elsewhere (described, not made)

1. **Caption style in an open window (done, T367).** `live_edit.apply` used to send caption cue text and times
   only, so a `{op: captions, style: ...}` change was dropped in an open window and `caption_layout.apply_plan` refused
   it. Now `apply_transaction` takes `caption_styles` (a caption track's burn-in filters: the text and its shadow
   copy), set in the same undo step as the cues (`AiSetCaptionStyleCommand`). A window whose build doesn't report
   `caption_styles` in its state gets the old behaviour: a saved project goes through the file, unsaved changes are
   refused. A caption track created by the same edit still gets its burn-in only from the file.
2. **Per-cue place for native captions.** Shotcut's Subtitle Burn In draws every cue of a feed in one rect, so one
   caption track has one place. The MLT `qtext` filter does evaluate `geometry` as an animation (hold keyframes per cue
   would render in melt), but `edit_script._offset_geom` (the shadow copy) and `checks.graphic_caption_collisions`
   parse geometry as four plain numbers and would break or skip, and the app's burn-in panel is not known to keep
   keyframes. The solver therefore uses one place per caption track (`native_mode='track'`) or puts cues that need
   another place on a caption track of their own (`native_mode='tracks'`, `<track> (top)`); word captions are placed
   per cue. Supporting keyframed burn-in geometry would need those two parsers fixed and the burn-in panel checked.
3. **Percent geometry elsewhere.** `edit_script._offset_geom` raises IndexError on legacy geometry such as
   `8%/50%:84%x20%` when the track has a shadow copy, and `checks.graphic_caption_collisions` silently skips such a
   track. `caption_layout.parse_geometry` reads every form (pixels, `%`, `x%/y%:w%xh%`); both could use it. (The solver
   always writes plain pixel geometry `x y w h 1`.)
4. **word_captions spacing.** The template reserves 40% of a word's pop growth and ignores the outline and the
   'back' ease overshoot (about 4.5% even at `pop_scale` 1.0), so heavy outlines plus pop make neighbours touch at the
   peak (the round-2 `it Without`: -7 px). The solver works within the template's params (lower `pop_scale`, thinner
   `outline_width`, regrouping), as little as needed. A template fix would add the stroke width and the full peak growth
   to the space between words (or a `word_gap` param); `graphics._digest` would then re-render every caption once.
5. **Quality gate.** `checks.qc` / the review bundle could add a caption pass from `caption_layout.fit(...,
   render_check_frames=False)` (violations only, no changes), so fused words, overlay collisions and shrunk cues block
   delivery like other findings.
6. **Long jobs.** `fit` runs synchronously: about 15 s of layout for a 45 s short with 37 animated cues, plus 15-40 s of
   melt rendering for faces and the render check (`max_frames`, default 40). For long videos it could run through
   `jobs.py` (the result is already a stored plan with `plan_id`).
7. **`valign: center`.** qtext only knows `t/m/b` by first letter, so the AI-written `valign: center` in round-2's
   talk short draws as top-aligned. The solver models it as qtext does; `edit_script.friendly_text_style` could map
   `center` to `middle` when writing.

## 6. Contract notes

- Proposal and mutation are separate: `fit` never writes the project (renders and previews go to
  `cache\caption-fit\<run>`, the plan to `cache\caption-fit\plans\<plan_id>.json`). `apply=True` or a later call with
  `plan_id` + `apply=True` applies through `timeline_tools.apply_project` (the shared path: one undo step in an open
  window, else the file with an undo copy), refusing a plan whose project revision, fonts, text engine or template
  changed (`stale_reasons`).
- Every proposal is checked before it is returned: `op_specs.check`, `edit_script.edit` on the current script, and
  the layer's words in order equal to the approved words (a space restored between two transcript words is the only
  allowed token change); `apply_plan` checks the same on the written file (`words_kept`).
- Native captions take word times from cached transcripts only (`speech.cached_words`); nothing is transcribed by
  this tool. Cues without word times keep their grouping and are listed in `unchecked_ranges`.
