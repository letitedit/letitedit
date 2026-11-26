# Working in passes

A pass is look once, edit once, check once. Every step of an AI session (one response, whatever it holds) re-reads
the whole conversation so far: in a Short's fine cut that is 200-400k tokens a step, the same for a step with one
call as for one with five. The same reads, edits and checks gathered into fewer steps cost a fraction and lose
nothing; the same checks spread over one change at a time cost several times more [OURS]. These rules change
how the work is grouped, never what is looked at, changed or checked: every rule's *Check* in the stage skills still
runs.

**PASS-1 Independent reads in one step.** Do: when reads or checks don't need each other's result, make them in the
same step, as several tool calls in one response or one call that takes a list: the cut's words and its frames, looks
at two places (`letitedit_look` items), a `letitedit_check_range` and a `letitedit_timing` view, caption readability
and a frame sheet, a footage sheet and `letitedit_find_takes`, the notes a stage writes (`letitedit_journal`
entries). When: always. Not: a read whose answer decides the next read waits for it. Check: no step holds one read
that the step before or after it could have held. [OURS]

**PASS-2 One apply per pass.** Do: plan the pass from the look and from everything the last check found, then make
every change of it in one `letitedit_timeline_apply`: the retime, the covers, the fixes of each flagged join,
`{op: declick}` once the cut is final, the captions with their fit (when the captions op takes `fit`). The changes run
in order, each on what the ones before it left, ids stay the same, and the list is one undo step. When: each pass of
the rough, fine and finish, and the fixes after each review round. Not: no apply for one trim and another for the
next; no dry run before an apply or a `try` (the apply checks every change before anything lands); a change that has
to see the result of another (a cover timed to a line that the same pass retimes, when its new time can't be worked
out from the apply's ops) goes in the next pass. Check: the stage's applies are about one per pass. [OURS]

**PASS-3 One whole-cut check per pass.** Do: after the pass's apply, check the whole cut in one step:
`letitedit_check_range` over the whole cut with `joins` (with `heard`, the words heard on its own render with every
join and clip edge marked: that is the listen) together with the measures the pass's rules call for (the `timing`
view, `letitedit_caption_readability`, frames on the platform's covered areas). Fix everything it found in the next
pass's one apply, then check the whole cut again. When: every pass. Not: no partial check of a join just changed and
then another; no `letitedit_words` on a render whose check already gave `heard`; never end a stage on a fix that no
whole-cut check has seen. Check: each pass's apply is followed by one whole-cut check, and the stage's last apply by
one too. [OURS]

**PASS-4 A narrow look only at what the whole check flagged and couldn't settle.** Do: a flagged join or word whose
words or sound the whole check can't settle gets one narrow look (a short `letitedit_check_range`, `letitedit_look`
with waveform, loudness or words lanes, `letitedit_hear`), and all of a pass's narrow looks go in one step. When:
before the fix of a finding the check can't explain. Not: no narrow look in place of the next whole-cut check. Check:
each narrow look names the finding it settles. [OURS]

**PASS-5 What a pass never drops.** A pass groups the checks; it never skips one. Always kept: the watched render at
the end of each stage (the rough's watched export, the whole-cut listen of the fine cut and the finish), every review
round with its look and fix (letitedit-gate: a round is the bundle, the look at its findings in one step, one apply of
the round's fixes, the checks those fixes touch in one step, then the next bundle), and a check of everything a check
found, after its fix: a word clipped at its start, a cut through a word or a sound, a pointing line over a pan or
shake, an overlay over the video's own text, captions too fast to read. A finding is fixed when a check of the new
render says so, never when the apply went through. Check: every finding has a later check that reads it fixed or
names it open. [OURS]

**PASS-6 A step budget per stage: a guide with its reason, never a cap.** A stage worked in passes usually takes about:
log 5-7 steps, story 1-2, rough 6-8, fine 8-12, finish 6-9, the review 3-4 a round plus the hooks and the closing
notes; about 40-50 for a Short. The reason is the cost above: steps times the context is what a video costs the
person's AI allowance. Do: plan each stage to fit it, and write the stage's step count in its pass note (`fine_pass:`,
`finish_pass:`, the review's answers). When: every stage. Not: never skip, merge away or shorten a check to stay
inside it; a stage that needs more steps for a real problem takes them and its pass note says why. Check: each pass
note gives its stage's steps, and past the budget the reason. [OURS]
