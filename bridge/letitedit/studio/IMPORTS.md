# studio: import boundary

Layer 11. Policy: `bridge/tests/server/module_boundaries.json`, enforced by
`bridge/tests/server/test_module_boundaries.py`. Inside the package, modules import each other only by
their real names (`letitedit.<job>.<module>`); the old flat names are for callers outside it.

The Studio is letitedit's front door for other programs (jobs from a written spec, `contract/CONTRACT.md`). It sits
above every other job because it drives them; nothing in the package imports it. Its command line is the entry file
`bridge/letitedit_studio.py`; `core/jobs.py` runs its jobs by the name `letitedit.studio.runner:run`.

`files.py`, `contract_schemas.py`, `validate.py`, `state.py`, `estimates.py` and `licences.py` import nothing from other
jobs when they load (`licences.py` reads the asset library and the picture records only when it is asked about a file),
so the reference fake (`fake.py`) runs on them alone.

Cross-job dependencies go to lower numbered layers. The ordering minimizes upward
module edges with core first and server last; it does not remove existing cycles.
Above every job is the entry layer, real files in `bridge/` that outside callers name
(`letitedit_ai`, `letitedit_mcp`, `original_review_frame`, `review_speech`, `split_edit_measure`):
package code does not import them; existing imports are named exceptions.

## Modules available to other jobs

None.

Any new export or exception needs an explicit policy change and explanation.
