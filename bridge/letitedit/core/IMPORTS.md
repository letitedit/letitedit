# core: import boundary

Layer 0. Policy: `bridge/tests/server/module_boundaries.json`, enforced by
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

- `letitedit.core.cache_budget`
- `letitedit.core.first_use`
- `letitedit.core.font_env`
- `letitedit.core.hardware`
- `letitedit.core.jobs`
- `letitedit.core.long_paths`
- `letitedit.core.media`
- `letitedit.core.memory_room`
- `letitedit.core.model_fetch`
- `letitedit.core.paths`
- `letitedit.core.pipe_input`
- `letitedit.core.quiet_subprocess`
- `letitedit.core.render_lock`
- `letitedit.core.store`

Any new export or exception needs an explicit policy change and explanation.
