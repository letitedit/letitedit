# footage: import boundary

Layer 5. Policy: `bridge/tests/server/module_boundaries.json`, enforced by
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

- `letitedit.footage.archive`
- `letitedit.footage.emotion_graph`
- `letitedit.footage.endings`
- `letitedit.footage.factlog`
- `letitedit.footage.fetch_link`
- `letitedit.footage.footage_notes`
- `letitedit.footage.geo`
- `letitedit.footage.hooks`
- `letitedit.footage.index_tools`
- `letitedit.footage.llm_log`
- `letitedit.footage.ocr`
- `letitedit.footage.perception`
- `letitedit.footage.playback_copies`
- `letitedit.footage.range_search`
- `letitedit.footage.reference`
- `letitedit.footage.shot_log`
- `letitedit.footage.shots`
- `letitedit.footage.speech`
- `letitedit.footage.speech_language`
- `letitedit.footage.takes`
- `letitedit.footage.views`
- `letitedit.footage.word_reheard`

Any new export or exception needs an explicit policy change and explanation.
