# app: import boundary

Layer 3. Policy: `bridge/tests/server/module_boundaries.json`, enforced by
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

- `letitedit.app.ai_clis`
- `letitedit.app.bookkeeping` (T331 P8: New video's bookkeeping in code; the why-marker writer in
  `letitedit.server.journal_tools` reads the cut through it, and the session runner in `studio/` calls `after_phase`)
- `letitedit.app.claude_session` (T331 P9: Claude Code as a session nobody watches, the Studio session runner's
  transport)
- `letitedit.app.letitedit_client`
- `letitedit.app.letitedit_instances`
- `letitedit.app.live_edit`
- `letitedit.app.live_review`
- `letitedit.app.new_video_carry` (T331 P9: the session runner waits for the video's exports still running,
  `pending_exports`, and reads a blocker the AI states, `plain_blocker`)
- `letitedit.app.new_video_request` (T331 P4: the typed New video request; the Studio's windowless resolver makes
  one, so it is exported to the jobs above)
- `letitedit.app.new_video_stages`
- `letitedit.app.phases` (T331 P9: the session runner drives the phase table and its done tests)
- `letitedit.app.progress_feed`
- `letitedit.app.run_cost`
- `letitedit.app.stage_start` (T331 P9: the session runner starts each phase with its complete, checked first
  message, `build` and `verify`)
- `letitedit.app.substeps` (T354: New video's phases in sub-steps, a session each; the session runner in `studio/`
  drives the table and its done tests, and the sub-step hand-off reads it)
- `letitedit.app.what_was_filmed`
- `letitedit.app.work_in_passes` (T353: work in passes; the tool server's compact timing reply and the
  Studio's final copy read its switch and helpers)

Any new export or exception needs an explicit policy change and explanation.
