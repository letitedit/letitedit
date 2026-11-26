# review: import boundary

Layer 6. Policy: `bridge/tests/server/module_boundaries.json`, enforced by
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

- `letitedit.review.brief_check`
- `letitedit.review.checks`
- `letitedit.review.dense`
- `letitedit.review.fix_post`
- `letitedit.review.overlay_clash` (T352: the Studio writes its overlay boxes beside the project for the review and
  measures its delivered files' boxes against the video's own text, `enabled`, `write_boxes`, `plain_box`, `measure`;
  T357: `plain_overlaps`, the words a person reads, with no coordinates or paths)
- `letitedit.review.picture_words` (T349: the fine phase's self-checks state the same picture facts as the review,
  `enabled`, `cut`)
- `letitedit.review.review_bundle`
- `letitedit.review.review_order` (T345 C3: the session runner runs the code checks before the review phase only
  while the review order is on, `enabled`)
- `letitedit.review.shot_match`
- `letitedit.review.turbo_check`

Any new export or exception needs an explicit policy change and explanation.
