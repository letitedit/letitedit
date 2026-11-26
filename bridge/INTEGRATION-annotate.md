# Integrating letitedit_annotate

New files only; no existing module was edited.

| File | What it is |
|---|---|
| `bridge/annotate.py` | The algorithm: the clip's picture chain read from the project file and evaluated per frame (engine arithmetic), time mapping, tracking with loss rules, label/inset layout (`place_box`, shared geometry helpers), the drawing (runs inside the graphics sandbox), the plan/apply/refresh flow, and the render-based checks. |
| `bridge/annotate_tools.py` | Thin MCP wrapper: `register(mcp, Image)` exposes `letitedit_annotate` (full contract in its docstring). |
| `bridge/tests/pictures/test_annotate.py` | pytest suite (35 tests, about 4 minutes; renders with melt). Outputs in `C:\LetItEdit\cache\annotate-tests\pytest`. |

## Registration lines

**`letitedit_mcp.py`** - next to the thumbnail tools (after `register_thumbs(mcp, Image)`):

```python
# Pointing at something in a clip (ring, arrow, box, label, magnifier, freeze, tracked) from its own source picture.
from annotate_tools import register as register_annotate
register_annotate(mcp, Image)
```

and add the name to `V2_NEW`:

```python
    'letitedit_annotate',
```

**`letitedit_ai.py`** - in `_registry()`: add `import annotate_tools` beside `import thumbs_tools`, and `annotate_tools`
to the tuple of modules that are registered (`for mod in (check_tools, ..., thumbs_tools, annotate_tools, ...)`).
Optional Python convenience, like the other wrappers there:

```python
def annotate(project, clip, target, **params):
    """letitedit_annotate as a function: plan (and with apply=True apply) a pointer at `target` in clip `clip`."""
    return tool('letitedit_annotate', project=project, clip=clip, target=target, **params)
```

**`tool_docs_v2.py`** - in `SHORT`:

```python
    'letitedit_annotate': "Point at something in a clip (ring, arrow, box, label, magnifier; freeze or tracking optional) "
                        "from a box in the clip's own source picture, mapped by the software through rotation, crop, "
                        "zoom, trims and position: edit ops, a rendered preview with measured checks; refresh after "
                        "the clip changes.",
```

**`GUIDE.md`** (suggested lines, under graphics/effects):

> To show what moved or what was tightened, use `letitedit_annotate(project, clip, target=[x0, y0, x1, y1], kind=ring|arrow|box|label|magnify, text=..., source_range=[a, b])`
> with the box in the clip's own picture (as frame tools show the file, 0-1 fractions). Never compute frame positions
> yourself. `follow='track'` follows a moving object; `freeze=True` holds the frame. It returns a preview and the ops;
> `apply=True` (or `plan_id` + `apply=True`) writes them. After trimming/moving/cropping that clip:
> `letitedit_annotate(project, refresh=True, apply=True)`.

## How it plugs into what exists

- **Graphics**: an annotation is an ordinary graphic item `{graphic: {template: 'custom', code: annotate.CODE, params}}`.
  The code is a two-line stub (`import annotate; annotate.draw(ctx)`); `graphics_runner.py` already puts `bridge` on
  `sys.path` in the sandbox. Rendering, caching (digest of the recipe), re-rendering on `{op: set, graphic: {params}}`
  and the `.mov` with alpha are the existing graphics system's. `params['annotate'] = annotate.ENGINE` marks the
  recipe; bumping `ENGINE` re-renders.
- **Edits**: proposals are the existing vocabulary (`add_track`, `insert ... at, overlap: next_track`, `set`, `move`,
  `delete`) applied through `timeline_tools.apply_project` (file apply with history and journal; a live window gets
  one undo step). Plans are stored in `cache/annotate/plans/<plan_id>.json` and refused when the project file hash or
  a source fingerprint changed (`edit_script.Conflict`).
- **Main-track edits** made through `letitedit_timeline_apply` already move the annotation with its picture
  (`edit_sync.resync`); `refresh` then re-solves the geometry (crop/zoom changes) and the range.
- **Tracking** uses `av_tools.track` (VitTrack) forwards and the same model backwards from `at`; extra loss rules
  (score, jump, growth, recovery) decide where the pointer is hidden.
- **Checks** use `checks.render_frames` (melt), `checks.faces_in` (labels avoid faces), `checks._graphic_bbox`
  (labels avoid other graphics), burnt-in caption geometry, and `platforms.load(...)['safe_zones']`.

## Notes for a later pass (not required for this tool)

- `edit_script.diff` names the item "custom '<text>'"; a friendlier "annotation '<text>'" would need a one-line case
  there for recipes with `params['annotate']`.
- A shared geometry module: `annotate.py`'s box/matrix helpers, `place_box` and `chain_at` (source pixels -> output
  pixels for any clip) are written to be imported by the caption-layout solver; moving them to e.g. `geometry.py` is
  a mechanical change once a second user exists.
