# letitedit\app

The editor's side: its client and windows, New video's helpers, the chat panel's AIs, Live Review.

- `acp_client`: A small client for the Agent Client Protocol, the way letitedit reaches a connector AI (ai_list.json, protocol "acp").
- `acp_host`: Runs a connector AI (ai_list.json, protocol "acp") for the chat panel, so the panel needs no protocol code of its own.
- `ai_antigravity`: Google's Antigravity connector: what differs from any other connector AI.
- `ai_clis`: The person's AI programs (Claude Code, Codex, a connector AI; the list is ai_list.json): which are on this PC, whether they are signed in, how a failed run failed, and a clean environment for a separate run.
- `app_tools`: Command lines the letitedit app runs for its own buttons: one JSON object per line, then the answer.
- `first_cut_result`: Which project did a New video run make? The window asks when a run ends and nothing has been opened.
- `learn_job`: The progress file of "Learn from a video" (Home, and New video's "Match a video I like").
- `letitedit_client`: Client for the bridge inside letitedit (the custom Shotcut build).
- `letitedit_instances`: Explicit per-call editor routing and crash-recoverable AI ownership (local PC only).
- `live_edit`: Apply edit-script changes straight into an open letitedit window as one native, undoable step.
- `live_review`: Live Review's helpers: the app's Review window keeps the AI's work on a copy of the project while the person watches, and brings the changes into the open window when they are ready, one Undo step per note.
- `look_adjust`: Save a Look the person adjusted with New video's "Adjust..." sliders as their own Look, "<Look> (yours)".
- `new_video_carry`: New video carrying on by itself: whether a run ended with a finished export in the video's folder, stopped on a blocker the AI named, or is unfinished.
- `new_video_custom`: Save a Custom mix as a private personal Look in the shared revision store.
- `new_video_media`: Stream a folder's media facts to New video without blocking the editor window.
- `progress_feed`: Small, local progress feed for AI editing jobs.
- `voice_chat`: Push-to-talk for the editor's chat panel: local speech-to-text of a short recording and a local spoken reply.
- `bookkeeping`: New video's bookkeeping in code: the stage and phase done marks, each main-track clip's `why:` marker and the hand-over between phases are written by code from the files on disk by default.  (no old name: imported as `letitedit.app.bookkeeping`)
- `claude_session`: Claude Code as an editing session that nobody watches: the session runner's transport.  (no old name: imported as `letitedit.app.claude_session`)
- `new_video_request`: One typed New video request: what the person chose in New video, resolved, as data.  (no old name: imported as `letitedit.app.new_video_request`)
- `new_video_stages`: New video with a fresh conversation for the review: when the finish is done and handed over while the conversation is big, the app starts the review rounds in a fresh conversation that carries the work on disk instead of the whole...
- `phases`: New video in three AI phases after a code-only prepare by default.  (no old name: imported as `letitedit.app.phases`)
- `run_cost`: What a New video run took from the AI: tokens and steps per stage, read from the AI's own session logs.
- `skill_scope`: Which `##` sections of each letitedit skill a New video sub-step's copy carries: the data of stage_start's `substep_scoped_skills` switch (on by default; letitedit.app.stage_start reads it, on sub-step starts only).  (no old name: imported as `letitedit.app.skill_scope`)
- `skill_sections`: The letitedit skills by section: an index of each skill (its sections, each with its job and size) and any sections read in one call, from the skills' own SKILL.md files, unchanged (tests/t194/sections-plan.md).
- `stage_handoff`: Opt-in, provider-neutral stage state.  (no old name: imported as `letitedit.app.stage_handoff`)
- `stage_start`: Complete, provider-neutral first messages.  (no old name: imported as `letitedit.app.stage_start`)
- `start_project`: Start a project for the person to edit with the AI themselves: New video's "Edit with the AI myself" and Home's "Start with an empty timeline".
- `substeps`: New video's phases in sub-steps, each in a fresh session that carries only its own skills.  (no old name: imported as `letitedit.app.substeps`)
- `usage_limit`: Was a turn of the AI stopped by its plan's usage limit, and when does the limit reset?
- `what_was_filmed`: What was filmed: the kind of video a set of clips is, worked out on this PC in a few seconds, for New video's Style tabs.
- `work_in_passes`: Work in passes: look once, edit once, check once per pass.  (no old name: imported as `letitedit.app.work_in_passes`)

Each module here also answers to its old name in `bridge\` (a small alias file: one module object under both names); inside the package, import the real name. What the other jobs may use from here: `IMPORTS.md`. The whole map: `CODEMAP.md` at the top of the repository.
