# Lean stage handoffs (experimental)

Read this in full when the run explicitly says lean stage handoffs (letitedit-firstcut FIRST-1s). Without that
switch, FIRST-1s alone applies.

**Experimental lean handoffs (off unless the run explicitly says lean stage handoffs).** This is a separate switch,
`new_video_lean_stage_handoffs` / `LETITEDIT_LEAN_STAGE_HANDOFFS`, not FIRST-1s's `sessions: one per stage` review
hand-over. With it, each accepted log/story/rough/fine/finish boundary may start fresh, on Claude or Codex, without
measuring the old conversation. Batch the stage's final artifact writes, accepted done note and structured handover in
that order in the existing stage-completion tool step; stop the batch if a gate fails. No extra discovery step is needed
in the old conversation. After the done note use the existing `handover:` journal note to write a JSON object (no
Markdown fences) with exactly these keys: `decisions` (each has a unique `id`, `why`, and `ranges`: source-frame
`{source_id, in, out}` with exclusive `out`), `unresolved` (finding history with stable `id` and `what`, including the
person's fixes), `pending_jobs` (job ids, empty before transition), `next_step` (the exact next action), `skills`
(additional required full skill names), and `artifacts` (absolute paths to any evidence the next stage needs beyond its
standard inputs: word/join indices, checks and coverage, licenses, sound/graphics/caption plans, rendered export and
final `review.md` when present). Keep essential editorial decisions concise and carry forward earlier decision and
finding ids; mark superseded decisions and resolved findings explicitly rather than silently dropping their history.
Completed review rounds cannot decrease; link large plans and logs in `artifacts`, never discard or truncate them. The
code writes and validates the versioned 2–5 KB `stage-handoff.json`; do not write that manifest yourself. A fresh
session reads that manifest, its exact evidence and Look recipes/settings in one batch, then every required skill in
full in a second batch, including the router, craft, firstcut, the stage skill, the lead mode reference, Shorts when
applicable and any other skill its work needs. Section-loading switches do not shorten these reads. Start work without
rediscovering projects or repeating completed stages; missing evidence or an editorial disagreement still warrants the
original source. The handoff does not reset `review_memory.json`, alter round limits, omit fixes or skip the final
review; letitedit-firstcut section 4 and the final `review.md` remain authoritative. A missing, changed or oversized
handoff keeps the existing session for repair, never a guessed fresh restart. [OURS]
