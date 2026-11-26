---
name: letitedit-gate
description: Final quality gate for a letitedit export - reviews the whole rendered video (letitedit_review_bundle) against measured checks set by the kind of video and the deliverable, the project's checks, the brief's must-keep/must-avoid/claims/ending and a separate critic, and gives one verdict (blocked / revise / incomplete / ready). Quote the plain section of review.md to the person. Called by the letitedit router.
metadata:
  version: 0.3.0
---

# Quality gate

Weak declines of measured Look devices are not editorial exemptions: the receipt rows stay open until the decision
holds. Include opening rules,
punch-ins and sound accents. Require an actual tool refusal or an exact explicit person-rule conflict.
Keeping effects off the face does not forbid flashes on b-roll; a large difference in light between reference and footage does not forbid lighting matching.
Use the selected Look's caption policy. An inverted-then-white Look keeps its measured typography and motion, no edge
or box, choosing whole captions at 3:1 over fully-on frames after the picture is final.

A selected Look needs a current `letitedit_look_check` receipt before export. Inspect every requirement in its
returned source files, not just the category names. The check returns two kinds of rows: faults in the video
(kind picture, major: what the timeline or the measurements show) and the receipt's record of the decisions (severity
receipt: a missing, weak or stale decision, a missing export observation). With `video` it also measures the whole
export against the reference whatever the receipts say: `pace`, `camera`, `grade_likeness` (one grade across the
footage) and `sound_shape` (opening, level through the body, ending, rate of hits). These are faults in the video;
for a first cut they are fixed on the fine cut's export before the review rounds (letitedit-firstcut). Fix the faults; complete the receipt once,
with the forms in `receipt_forms`. A receipt row is never a reason to edit or export again, and never a fault to tell
the person about. Carry the pre-export faults into the finish review and tell the person.
Do not substitute a hand-encoded ffmpeg file or the editor's own playback for `letitedit_export`: only the export engine's renders
count (the editor's preview has disagreed with exports). Off-topic b-roll is not relevant coverage. After rendering,
measure every caption's ink contrast with `letitedit_caption_readability` (`video=` a full-size export only; on a preview leave
`video` out and it draws full-size frames itself), then update the Look receipt
with byte-bound device observations once, on a reviewed export (they carry to the final rendered from the same
items). Declarations are not independent picture
proof; inspect the export too.

## What a pass proves

Agents claimed full success in 93% of runs, including edits that failed [RES, Timeline-Bench]. A measured pass does not override a critic's findings. Review the rendered file end to end; use the actual evidence, not the editor's self-verdict.

## A song added when posting

A project with a 'Song (not in the export)' track (letitedit-sound section 13): review the upload (its preview, then the final upload),
never a render with the song in it. The bundle searches
its sound for the song ('song stays out' under coverage; the song in the file is critical) and measures cuts against the song's beats.

## The review, step by step

1. Review rounds run on a preview. The export engine draws it smaller with a fast encode and the final's sound (same loudness
   finishing and true-peak limit), so the loudness, the mix, the words, the cuts and the timing are the final's, and its
   chunks are cached: after a fix only the changed chunks render again. Judge the rendered file, not the timeline. [OURS]
   A round renders its own preview with `letitedit_review_bundle(render='preview', ...)`, not a separate manual export.
   The critic runs again only on a changed video. A rendered round's video changed when its timeline did since that
   review: an edit applied (`letitedit_timeline_apply`, an undo, a fix, a caption layout or shot match applied) or
   hand edits in the person's window (`letitedit_editor` shows unsaved changes, `letitedit_timeline_read` shows them).
   A review of a file you made (`video=`) is of that file: the same path, size and time as `video` in that review's
   `review_bundle.json` is the same video. Unchanged, the last review stands: read the existing review instead of running
   the bundle again (its pages, details and `review.md`), unless the person asks for another round. Keep the round
   limits and targeted-review policy.
   A reply with `review_order` has put the measured checks before the reviewer. `held`: measured problems come first
   (`code_failures`: loudness, true peak, black frames, silences, words cut at clip edges, captions missing from the
   picture, caption text under an app's buttons, a project changed after its export); no reviewer ran and no round was
   used, so fix them, render again and run the bundle again. `reuse`: the last review stands, because the file is the
   same or the cut is unchanged after a review with no picture, story or sound problem; the measured checks ran on this
   export. `look`: only mechanical fixes (a caption's look or place, a level) followed that review, so a reviewer took
   one targeted look at the notes they answer instead of a full round, and says fixed or still open for each. `run`: a
   reviewer read this export. Follow its `next` line. A
   reviewer's round spent on a video that a measured fix will change is a round lost. [OURS]
2. Make it and review it in one call: `letitedit_review_bundle(project=<project.mlt>, render='preview', brief=<brief.json, or
   leave it to find brief.json / the journal brief>, critic='run')` renders the preview, waits for it and reviews it (a
   preview already made is reviewed with `video=<the preview>` instead of `render`). The tool picks the reviewer: a different AI when one is available,
   otherwise your own AI as a fresh session that never sees your reasoning. Either counts as the review. On a preview the
   size checks judge the project's own size, and what only shows at full size is checked on full-size frames from the
   export engine: the details page (small text, captions, thin lines), the Look kit check (graphics on faces) and the
   colour grade. Look at the details page for small text before you trust the pages. [OURS]
   Make the review a tool call. A long one answers "still working" with a call id: collect it with `letitedit_wait`. A
   background shell running it is collected from its finished notice, never a loop of sleeps, which keeps the run waiting
   past the moment the review is done. [OURS]
   It covers every part of the video (contact pages in time order, larger frames at the opening, the ending and
   every flagged moment, motion strips, 8 s excerpts, the complete transcript, a level graph) and merges:
   - the measured checks, with limits from the brief's `mode`, `driver`, deliverable and platforms (it passes them to
     the gate itself): length, size, loudness (web -14, podcast -16, broadcast -23 LUFS) and one true-peak ceiling
     (-1 dBTP), and the pace and opening checks (cuts per minute, longest static shot, a change in the first 3 s,
     first speech, silences). Pace checks are **advisory** (reported as minor, never blocking) unless the brief's
     `pace` limits or a `reference` set the tempo; each mode turns some **off** (montage and creative: all pace
     checks; documentary and travel: long-form openings; interview: cut rate and longest shot; first speech only
     when dialogue drives). TikTok's 57-60 s check only for TikTok deliverables. `hold:` markers waive the
     longest-shot check over their range;
   - the project's checks (words cut at clip edges, including a word's last sound; a last line the source carries straight on from (minor: it may sound cut off mid-thought; major in a long talk video, as is the source's own goodbye left out just after the cut); graphics over captions, a project changed after the export);
   - the brief (must-keep lines and moments, must-avoid material, exact claims and their caption spelling, the
     ending, narration, protected ranges, length);
   A specified `deliverables[].target_s` allows +/-5%, with a minimum of +/-2 seconds (90 s: 85.5-94.5 s).
   `deliverables[].tolerance` in seconds overrides that window, including zero; `tolerance_s` is also accepted.
   Outside the window is a major finding. A named platform's official maximum stays exact, regardless of the
   target's tolerance. Length findings state the actual length, target and window, not an instruction to cut.
   The gate also checks the last
   decoded picture for a black tail, including a single frame. An intentional black ending needs
   `ending: {allow_black_tail: true}` in the brief or Look, or a `waive:black_tail_s:<reason>` project marker.
   - the critic's findings (each with a time, evidence and severity), with the story plan and the mode's own
     questions (letitedit-modes, section 8 of each mode file).
   Wordless briefs can set `wordless: true` or `speech: "none"`. A picture/sound `ending` or `required_moments` entry uses `{"kind": "visual" | "sound" | "audiovisual", "description": "..."}`. These remain editorial checks, never transcript passes. Explicit `required_lines` and `{"line": "..."}` endings still require the words; `narration: "none"` alone does not rule out recorded dialogue.
3. Read `review.md` and look at the pages and `details.jpg` yourself. Quote its **For the person** section to the
   person; the technical section is for making the next fix. Keep a product name or other required claim in the
   brief when speech recognition writes it with different spaces or capitals. Check the source and captions,
   correct the spelling or mark genuine uncertainty; do not remove the claim just to clear a finding.
4. Verdict:
   - **blocked**: a critical problem (a required line or moment missing, forbidden material in, a claim changed, a
     reviewer block). Fix it; never deliver a blocked video.
   - **revise**: a major problem. Fix it, or waive a craft check with a marker `waive:<check>:<reason>`
     (`letitedit_bin`) when the brief or the kind of video calls for it (letitedit-modes lists the usual waivers).
   - **incomplete**: a first cut skipped a stage or a needed check did not run. Finish the missing stages and
     checks; the report still lists any quality problems found. A critical or major problem still sets blocked or
     revise, and `not_checked` lists the check whatever the verdict.
   - When `not_checked` has `speech` (the review couldn't hear the video, or a stretch of its talk: its `why` says
     which), a second review on the same PC hears no more. The brief's "to confirm by ear" findings say where the
     timeline's own words put each line: hear them yourself (`letitedit_words` on the export) and tell the person what
     the review couldn't hear and why. A line found only faintly under loud music may still be lost to a viewer:
     check the music's level there.
   - **ready**: all required checks ran clean. Listening is never done by code: say so.
   For each major, distinguish a fix possible in this cut (timing, crop, truthful illustration, caption position,
   wording of on-screen text) from evidence or a decision the person must provide (real product recording, account
   proof, verified signup route). Make the possible fixes first. A missing recording does not make a static picture
   or captions on a hat unfixable; an illustration can clarify a mechanism but must be labelled and cannot claim
   to be a real demonstration. If the measured picture count misses subtle zooms, judge the rendered frame sheet
   and the critic's finding, not the count alone.
   Each finding says who can fix it. **Only the AI's findings set the verdict**: what only the person can provide (a real recording
   of the software, proof of a number, the real link, a fact to verify) goes on the **For you** list in `review.md`, and the video can
   be `ready` with that list. A critic can't move a fixable finding there: the bundle checks, and a cut through a word or a caption
   over a face is never the person's. Tell the person the For you list; don't hide it and don't argue with it.
   These need the person's OK, not a waiver: the loudness and true-peak limits, the 1080x1920 delivery size when the
   brief asked for it, and the story blockers from letitedit-rough: FM3 (no visible change) only for the repair and
   before/after playbooks, FM4 (an open loop never paid) unless the brief or the mode chose an open ending, FM11 (a
   payoff without its setup), FM12 (a render nobody watched).
5. A reviewer asking for a shot ("cut in the clip of...", "b-roll of..."): look for it (`letitedit_search`,
   `letitedit_find_ranges`). If the folder doesn't have it, put it on the shots-to-film list (`pickups.md`, a line with the
   moment's time and what to film); the next bundle then lists that finding for the person instead of holding the verdict.
   Never invent or borrow a stand-in to clear it. [OURS]
   After fixes, run the bundle again with `render='preview'` (a new preview); it re-checks everything. **Two full review rounds per video**: the code counts them
   in the video's side folder (`review_memory.json`) and the reviewer reads what earlier rounds found. After that, `critic='run'` reuses
   the last review and the measured checks run again on the new export, so fix what is measurable and hand over with the list. Name what
   is left plainly. If the cut has changed since a reviewer last saw it, the next `critic='run'` also takes **one targeted look** at
   that cut (one per changed cut, three at most per edit), Turbo included: a reviewer sees the open items and the change since the
   last review, says fixed or still open for each, and may name one problem the change made (kept as one finding with the open item
   it repeats). `review.md`'s look line says what it closed and what it found. That bundle is the last review of the run: its reply has
   `rounds.final` and a `next` line. Run it on the final itself: `render='final'` renders the full-size final from the timeline
   as it stands and reviews that file, so the last review is of the file you deliver and nothing else checks it after. Don't
   edit after that bundle. [OURS]
   One exception: a critical or major finding that bundle still lists. While a reviewer look is left, its `next` line
   says to fix each one, check each fixed range on the export engine's frames (`letitedit_check_frames` at those
   moments beside their neighbours, or `letitedit_check_range` / `letitedit_look` on the range) and with the code
   check the fix touches (`letitedit_caption_readability` for text over a pale or busy background, `letitedit_timing`
   for joins), then run the bundle once more with `render='final'` for its targeted look. The round limit caps the
   critic, never the fixes: a critical or major is never handed over as it is while a look is left. One that truly
   can't be fixed with this footage is said plainly in the closing message: what it is, what was tried and why. [OURS]
   `critic='again'` is one more full round: only when the person asks for it.
5b. A final reviewed itself (`render='final'`) is done: hand it over. A final rendered on its own from the reviewed timeline
   (`final=True` on a preview round, which starts it while the reviewer reads, or `letitedit_export`): when its job is done, run
   `letitedit_review_bundle(video=<the final>, project=..., final_of=<the reviewed preview>)`. It is a short technical check, not
   a new review: length, loudness and true peak, black or frozen stretches, sound and picture in step, the picture the same as
   the preview's, and full-size frames (`final-frames.jpg`, look at them). It writes `<final> review/review.md`: the preview's
   review with the final as its video. A difference is a finding: export again from the reviewed timeline. Then hand the video
   over, with what is still open as what's left. Any edit after the confirming review means a new preview and its review
   first, not a final you didn't review. [OURS]
   Every edit after the last review needs a review of the new export before handover, even a small edit after a
   confirming final review or past the round limit: run `letitedit_review_bundle(project=..., render='final',
   critic='run')` once more. Past the limit that call starts no new critic (it reuses the last review, measures the new
   file and takes the targeted look if one is due), so it costs a render and the measured checks. The delivered file
   must have its own review after the last edit, never the earlier file's verdict.
6. Your final message: the path of each final video, then quote the **For the person** section of its `review.md`. Do not add
   "looks great" or quote technical tables.

## Older tools

The older `letitedit_quality_gate` (measurements only; takes `mode`, `driver`, `deliverable`, `platforms`, `limits`,
`reference`) and `letitedit_critic` (the critic only) still work; the bundle runs both and more.
