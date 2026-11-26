# looks: import boundary

Layer 9. Policy: `bridge/tests/server/module_boundaries.json`, enforced by
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

- `letitedit.looks.caption_colour`
- `letitedit.looks.caption_timing`
- `letitedit.looks.fx`
- `letitedit.looks.graphic_kit`
- `letitedit.looks.kinetic_type`
- `letitedit.looks.learned_looks`
- `letitedit.looks.learned_sound`
- `letitedit.looks.lighting`
- `letitedit.looks.look_check`
- `letitedit.looks.look_inputs`
- `letitedit.looks.look_library`
- `letitedit.looks.learn_measure`
- `letitedit.looks.look_match`
- `letitedit.looks.look_place`
- `letitedit.looks.looks`
- `letitedit.looks.popups`
- `letitedit.looks.project_look`
- `letitedit.looks.sound_targets`
- `letitedit.looks.style_import`
- `letitedit.looks.style_import_marks`
- `letitedit.looks.style_import_sources`
- `letitedit.looks.style_import_visual`
- `letitedit.looks.style_pack`

Any new export or exception needs an explicit policy change and explanation.

T292 grants timeline edit_script and edit_script_reading a narrow upward edge to
look_library for canonical project Look identity and resolved preferences. The
library delegates old metadata exclusively to look_migration; it never migrates
or writes a project while resolving its defaults.
