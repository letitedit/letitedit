# timeline: import boundary

Layer 2. Policy: `bridge/tests/server/module_boundaries.json`, enforced by
`bridge/tests/server/test_module_boundaries.py`. Inside the package, modules import each other only by
their real names (`letitedit.<job>.<module>`); the old flat names are for callers outside it.

Other jobs may import the following modules and their public names. Names beginning
with `_` are private, including access through an imported module. Existing private
and upward dependencies are named individually in the policy; they are migration
debt, not permission for new callers. Same-job imports are unrestricted.

Cross-job dependencies go to lower numbered layers. The ordering minimizes upward
module edges with core first and server last; it does not remove existing cycles.
Above every job is the entry layer, real files in `bridge/` that outside callers name
(`letitedit_ai`, `letitedit_mcp`, `original_review_frame`, `review_speech`, `split_edit_measure`):
package code does not import them; existing imports are named exceptions.

## Modules available to other jobs

- `letitedit.timeline.adjust`
- `letitedit.timeline.aim`
- `letitedit.timeline.chunk_cache`
- `letitedit.timeline.cutpoints`
- `letitedit.timeline.edit_code`
- `letitedit.timeline.edit_effects`
- `letitedit.timeline.edit_import`
- `letitedit.timeline.edit_script`
- `letitedit.timeline.edit_sync`
- `letitedit.timeline.effects_catalog`
- `letitedit.timeline.episodes`
- `letitedit.timeline.export_checks`
- `letitedit.timeline.formats`
- `letitedit.timeline.letitedit_extras`
- `letitedit.timeline.made`
- `letitedit.timeline.op_specs`
- `letitedit.timeline.project_journal`
- `letitedit.timeline.render_queue`
- `letitedit.timeline.split_edit`
- `letitedit.timeline.stack`
- `letitedit.timeline.timeline_model`
- `letitedit.timeline.timeline_speech`

Any new export or exception needs an explicit policy change and explanation.
