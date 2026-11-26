# Integrating letitedit_find_takes

New files (already in place, nothing else needs copying):

- `bridge/takes.py`: the algorithm (`takes.find`, `takes.compact`, `takes.audio_match`, the job kind `takes:job`)
- `bridge/takes_tools.py`: the MCP wrapper, `register(mcp, Image)` -> `letitedit_find_takes`
- `bridge/tests/footage/test_takes.py`: tests (`python -m pytest test_takes.py -q`, about 15 s, footage tests skip when the
  test footage is missing)

Also changed: `bridge/cutpoints.py`, `_tok` is now Unicode-aware (letters, digits and combining marks of any
script). English is unchanged: it was checked against the old regex on all 170,958 cached transcript words, and
`test_a8_fixes`, `test_a10_fixes`, `test_a18_fixes` and `test_native_tools` pass. The now-unused `import re` was
removed.

The shared files below were left untouched (other work edits them too). These are the lines to add.

## 1. `bridge/letitedit_mcp.py`: register the tool

Add after these lines, before `if __name__ == "__main__":`:

```python
from factlog_tools import register as register_factlog
register_factlog(mcp, Image)
```

Add these lines:

```python
# Repeated takes of one passage (retakes, false starts, restarts inside a line), compared and measured side by side.
from takes_tools import register as register_takes
register_takes(mcp, Image)
```

## 2. `bridge/letitedit_mcp.py`: add the name to `V2_NEW`

Add inside the `V2_NEW = { ... }` set, for example after `'letitedit_segments',`:

```python
    'letitedit_find_takes',
```

(It is not a core tool. Under `TOOLSET == 'core'` it stays a Python function reachable through `letitedit_ai.tool`.)

## 3. `bridge/letitedit_ai.py`: the Python registry (`_registry()`)

Add an import next to `import thumbs_tools`:

```python
    import takes_tools
```

Then add `takes_tools` to the module tuple of the `for mod in (...)` loop, for example right after `thumbs_tools`:

```python
    for mod in (check_tools, timeline_tools, kit_tools, core_tools, v2_tools, jobs_tools, journal_tools,
                platforms_tools, hardware_tools, reference_tools, thumbs_tools, takes_tools, geo_tools, ...):
```

After that, `letitedit_ai.tool('find_takes', files=..., previews='sheets')` works. The sheets come back as file paths
under `images`, as for the other tools.

## 4. `bridge/tool_docs_v2.py`: the short description (`SHORT` dict)

```python
    'letitedit_find_takes': "Repeated takes of one passage (retakes, false starts, restarts inside a line, lines said "
                          "again) from cached transcripts: groups, wording and claim differences (number, negation, "
                          "name), separate measurements per take, comparison sheets and clips. Never picks or deletes.",
```

## 5. Optional

- GUIDE.md, one line in the footage or search section: `letitedit_find_takes(files | archive, script | phrase)`. It
  shows takes of the same passage side by side. Choose one, then insert its `edit_item` with
  `letitedit_timeline_apply`.
- Background jobs need no registration. `jobs.py` resolves the kind `takes:job` as `module:function`. The tool's
  `background=True` calls `takes.submit(inputs)` and returns a `job_id` that `letitedit_jobs(action='status')` reads.
- Outputs go to `C:\LetItEdit\cache\takes\<result_id>\` (result.json, sheets, clips, reel) unless `out_dir` is
  given. A repeat call with the same inputs, settings and source fingerprints reuses the stored result.
