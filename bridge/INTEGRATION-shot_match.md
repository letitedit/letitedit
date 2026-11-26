# Integrating `letitedit_match_shots` (shot matching)

Built 2026-10-28 from the implementation plan, section 7 ("SHOT MATCHING"). New files only; nothing shared was edited:

| File | What |
|---|---|
| `bridge/shot_match.py` | The algorithm: measuring, deciding, previews, plans, apply, remove (`match()` is the entry point; `brief()` the short report) |
| `bridge/shot_match_tools.py` | Thin MCP wrapper: `register(mcp, Image)` exposes `letitedit_match_shots` (its docstring is the full contract) |
| `bridge/tests/review/test_shot_match.py` | 29 pytest tests (about 3 minutes; uses `test-footage` in place, writes only to `cache\shot-match-tests\pytest`) |

Run the tests: `cd C:\LetItEdit\bridge && python -m pytest test_shot_match.py -q`

## 1. `bridge/letitedit_mcp.py`

Register the tool next to the other measuring tools, right after `register_thumbs(mcp, Image)`:

```python
# Shot matching: exposure, white balance and gentle tone toward a reference clip, as editable Color Grading effects.
from shot_match_tools import register as register_shot_match
register_shot_match(mcp, Image)
```

Add the name to `V2_NEW` (it then also counts as `UNSCOPED`: it works on files and finds the user's window by project,
like `letitedit_timeline_apply`, so it needs no `instance_id`):

```python
V2_NEW = {
    ...
    'letitedit_match_shots',
}
```

Optional: add `'letitedit_match_shots'` to `CORE_TOOLS` too if the core set should offer it (then add the GUIDE.md row in
section 5). It is not a picture-only tool, so it does not belong in `LEAN_TOOLS`.

## 2. `bridge/letitedit_ai.py` (`_registry`)

Add the module to the imports and to the tuple of registered modules:

```python
    import shot_match_tools
    for mod in (check_tools, timeline_tools, kit_tools, core_tools, v2_tools, jobs_tools, journal_tools,
                platforms_tools, hardware_tools, reference_tools, thumbs_tools, geo_tools, formats_tools, archive_tools,
                editor_tools, fix_tools, render3d_tools, maps_tools, music_gen_tools, factlog_tools, review_tools,
                shot_match_tools):
        mod.register(_Collect(), _SavedImage)
```

Then `sa.tool('match_shots', project=..., reference=...)` works. Suggested addition to the module docstring's `sa.tool(...)`
list: `'match_shots'` (match clips' exposure/white balance/tone to a reference clip).

## 3. `bridge/tool_docs_v2.py` (`SHORT`)

```python
    'letitedit_match_shots': "Match clips to a reference clip's exposure, white balance and gentle tone (ids, its scene or "
                           "track): an editable Color Grading effect per clip, before/after frames and measured "
                           "differences; proposes first (apply=True or plan_id writes); leaves HDR/log, other scenes, "
                           "sunset/night looks and changing light alone, with the reason.",
```

## 4. `GUIDE_V2.md` (the `## Tools` list; suggested place: after `letitedit_fix`)

```markdown
- `letitedit_match_shots`: Match clips to a reference clip's exposure, white balance and gentle tone (ids, its scene or track): an editable Color Grading effect per clip, before/after frames and measured differences; proposes first (apply=True or plan_id writes); leaves HDR/log, other scenes, sunset/night looks and changing light alone, with the reason.
```

## 5. `GUIDE.md` (only if added to `CORE_TOOLS`): a row for the `## Tools` table

```markdown
| `letitedit_match_shots(project, reference, clips, apply, plan_id, limits, strength, neutral_regions, same_scene, keep_looks, remove)` | Make clips look shot with the same camera settings as a reference clip: bounded exposure, white-balance and gentle tone corrections measured on frames the export engine renders, written as an editable Color Grading effect on each clip (`{filter: color}`; take it off with `remove=True`). Proposes first with a reference/before/after sheet and measured differences; `apply=True` (or `plan_id` from the proposal) writes it as one undo step. SDR only; clips it should not touch (HDR/log, different scenes, sunset/night looks, light changing inside the clip, already matched) are left alone with the reason. |
```

## 6. Other places (described, not changed)

- **AGENTS.md / SHOTCUT-AI.md** (what exists today): one line under the editing tools, e.g. "Shot matching
  (`letitedit_match_shots`, `bridge\shot_match.py`): reference-based exposure/white-balance/tone matching as Color
  Grading effects; plans in `cache\shot-match\plans`, previews in `cache\shot-match\runs`."
- **Skills** (`letitedit-finish`, maybe `letitedit-fine`): a step "mixed phone/camera footage: run
  `letitedit_match_shots(project, reference=<the A-roll clip>)`, look at the sheet, apply the plan". The skill decides
  when; the tool only measures and corrects.
- **Cache housekeeping**: the tool writes `cache\shot-match\runs\<time>-<id>\` (variant projects and rendered frames,
  a few MB per run), `cache\shot-match\plans\<plan_id>.json` (+ `-applied.json`) and `cache\shot-match\probe\` (colour
  facts per source file). Nothing prunes them yet; the runs folder can go into whatever prunes `cache\frames`. A
  stored plan's `apply` compares the written frames with that run's previewed frames, so pruning a run only skips
  that comparison (it says so).
- **Native transaction (plan foundation)**: the tool writes through `timeline_tools.apply_project` (the shared path:
  one undo step in an open window, else the file with a history copy). Once the native transaction lands there,
  nothing here needs to change. It refuses to write while the open window has unsaved changes (it measured the saved
  file); the native transaction with revisions would let it check the window's revision instead.
- **Background jobs**: the work is synchronous and bounded (at most 60 clips a call; about 2 s per clip plus 2-4 s
  per call for melt). If long timelines become common, wrap `shot_match.match` in a `jobs.py` job type; the plan id
  already makes the result resumable (propose in the job, apply by plan id).
- **`checks.qc` (optional follow-up)**: a finding "adjacent main-track clips from different source files differ by
  more than X in exposure or white balance" could call `shot_match.differences` on cached measurements and suggest
  `letitedit_match_shots`.

## Contract summary (for reviewers)

- Effect written: Shotcut's **Color Grading** filter (`mlt_service` `lift_gamma_gain`, `shotcut:filter_version` 1),
  `lift_*` 0, one `gamma` for all channels, per-channel `gain_*` (kept inside the panel's 0.5-2 range), plus
  `letitedit_ai:role = shot_match` (hidden bookkeeping, how the tool finds and replaces its own effect) and
  `letitedit_ai:shot_match` (JSON: reference, mode, plan, numbers; shows with the effect's settings). It goes before any
  text effect on the clip; running again replaces it rather than stacking a second one.
- Report: `schema_version` 1, `project_revision` (hash of the .mlt), `source_fingerprints`, `plan_id`, `changes` (edit
  ops), `preview_artifacts`, `findings`, `checked_ranges`, `unchecked_ranges`, `warnings`, `unsupported`, per clip
  status/reason/why, `correction`, `measured_before`, `measured_after`, `headline`, `evidence`, `notes`.
- A stored plan is refused (StalePlan) when the project file or any source file changed since it was measured.
