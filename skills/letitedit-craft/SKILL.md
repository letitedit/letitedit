---
name: letitedit-craft
description: The editing fundamentals every letitedit edit and revision applies - selection and story spine (one subject, stakes, setup and payoff, but/therefore with lists allowed, reveals placed on purpose), pacing from the intended feeling (speed levers moved together, gears per section, slow for density and emotion, never over-tight), scene construction (purpose sentence, the first 10 seconds and the muted test, late in and early out, contrast, hand-offs, the opening cut last), dialogue (pull, cut down, re-arrange, retime line by line, keep the melody and breaths, meaning unchanged), reactions and body language, b-roll jobs and sequences, tension (open loops, withhold answers not the premise, ticking clocks), the repetition ledger, transitions and the passage of time, and the revision-levers table that turns plain notes ("less flashy", "it drags", "more breathing room") into concrete changes and tools. Load with every edit, every stage and every revision.
metadata:
  version: 0.2.0
---

# Craft: the fundamentals of every edit

Decides, for any edit: what stays, how each section feels and moves, how it opens, ends and hands on, how talk is
shaped, where the face stays, what b-roll is for, how tension holds, and which levers answer a note. Its decisions
land in the story plan, the timeline, `why:` markers and journal notes; it writes no file of its own.

- **Inputs:** the brief (`mode`, `driver`, `feel`, `reference`, `deliverables`, `must_keep`, `must_avoid`, `claims`,
  `ending`, `tone`), the story plan, words with times (`letitedit_words`), pictures (`letitedit_footage`,
  `letitedit_check_frames`), and for a revision the last render.
- **Defaults, not laws.** The brief and the person's words win; a `reference` sets tempo and style (`letitedit_measure`);
  where the kind of video changes a default, letitedit-modes says how. Never invent what the footage lacks (S6;
  letitedit-story lists what's missing). Tools do timing and layout maths: parameters in `letitedit_guide('<tool>')`.
- **Rules:** do, *when*, *not*, *check*, evidence tags (`[GEN]`: unsourced, a number to tune; every citation and why a
  rule holds: `references/sources.md`). Running the checks: `references/checks.md`; examples, numbers:
  `references/examples.md`; which stage uses which rule, and the full tag legend: `references/manual.md`.
- **Working in passes:** a stage that starts with `references/passes.md` attached groups its reads, edits and
  checks as that file says (PASS-1 to PASS-6), with every Check here still run.

## 1. Selection and spine
- **S1 One subject.** A piece is about one thing; a second subject is a second video (a list or a day can be the one
  thing); never merge stories to fill a length. *Check:* the critic says in one sentence what the render is about, and
  it matches `goal`. [ITE FOJhAl9IyPg 09:30] [AOTC porcelain]
- **S2 Select for feeling.** Every pass keeps experience, detail, emotion, personality and what pays off later, and
  cuts repeated information (keep the stronger telling), the same action twice, dead footage; not past where context
  collapses. *Check:* each kept line or shot has a `why:`. [ITE 5G2wGolpXxE 07:26] [AOTC pop] [OURS]
- **S3 Stakes first.** Always say what could be won or lost and why it matters to them; show what they love or normally
  do before the threat (a tutorial's stake: will it work and hold [GEN]); no invented danger. *Check:* a first-time
  viewer names the stake after the opening. [ITE D2iBdbNej78 03:12] [JH 1:18] [AOTC porcelain]
- **S4 Beats change things.** In story and tutorial modes link beats by "but" or "therefore" (so, turns out, a time
  jump); merge, cut or bridge "and then" beats; a list is fine (show the count, a beat and a picture per item);
  montages link by progression. *Check:* no three "and then" links in a row. [JH 22:07] [JH 15:51]
- **S5 Seed, pay off, place reveals.** Set up early what pays off late; carry every opened thread to its payoff or cut
  its setup; place each reveal against what the viewer knows, the strongest last; thread context in where needed; no
  seedless payoff. *Check:* setups and payoffs pair up. [AOTC pop] [ITE ZcIVl01h14Y 09:47] [OURS]
- **S6 Real, not made up.** Build from what happened and keep real complications; a missing beat gets an honest bridge
  (their own line, a short card, a montage, an approved voice-over) or a pickup; no invented setback, reaction,
  deadline or time jump. *Check:* time cards match recording times. [AOTC pop] [OURS]

## 2. Pacing
- **P1 Feeling first.** Name the feeling of the piece and each section (`feel`), then choose speed; format sets length
  and density, not gear (Shorts aren't frantic, documentaries aren't slow, by default); not from the platform alone.
  *Check:* levers (P2) match the feeling. [ITE CdyTIng0M8Q 04:59] [JH 29:13]
- **P2 Move the levers together.** Speed is cut rate and shots per action, action in the shot, shot scale, camera
  movement (locked-off, pan, whip), space around lines, music energy, stylised devices; they stack. Any tempo change
  moves several of them, never just longer clips. *Check:* 3+ levers moved. [ITE CdyTIng0M8Q 09:17] [ITE KAO0n3C0kAg 26:29]
- **P3 Gears, varied.** Long-form and multi-beat Shorts give each section a gear (1 reflective, 2 observational, 3
  progression, 4 tension, 5 urgency): no equal gears side by side, no repeating cycle, a change inside a section only
  on an event (a deliberate sustained gear is allowed). *Check:* the gear list. [ITE bCVeyUFGxi8 02:31] [AOTC pop]
- **P4 Slow for density and emotion.** In explanations, confessions and reveals: one idea at a time with a beat of
  picture or music after it; hold before and after a key line; let the reaction run longer than instinct says. Not:
  energy peaks whose meaning is clear (cut hard); holds that don't stay alive. *Check:* ~1.5 s after tagged lines in
  long-form [GEN]; `hold:<reason>` markers. [ITE pRpaqx_5jD8 09:36] [AOTC dune] [AOTC skeleton] [OURS]
- **P5 Never over-tight.** In every format cut dead time (search pauses, warm-up, tails after the payoff, setup
  chatter); keep meaningful time (breaths at thought ends, thought pauses, held reactions, laughs); over-tight reads as
  insecure and can feel longer; a Short's breather must still move the story; never strip every breath. *Check:* no
  30 s without a breath or reset [GEN]. [AOTC pop] [ITE xiJmwycUxTY 07:40] [JH 20:52]

## 3. Scenes and sections
- **C1 Purpose sentence.** Before cutting every section write "about X; the viewer ends up feeling Y"; let it pick
  lines, shots, music and pace; cut almost-right material; re-ask after each pass (it may change); never none.
  *Check:* the critic restates it from the render, feeling included. [ITE FOJhAl9IyPg 02:49, 07:57]
- **C2 Chains, not collections.** A section starts, develops and ends, and something changes; each shot or line leads
  to the next (this, therefore that); when pictures can't progress, the words carry it. A picture-state change is
  needed only in repair and before/after. *Check:* name it. [ITE eXUH3Z5ZntE 03:15, 16:18]
- **C3 The first 10 seconds.** At every video and section start pick the opening's feeling and make words, pictures
  and sound agree: urgent (time, place, stakes, consequence in one breath; tight, quick, percussive), poetic (a
  reflective line, long static takes, sound layered in), or another stated tone. No greeting or fact-stack opening; a
  Short reads muted from frame one (letitedit-shorts). *Check:* the muted 10-second test.
  [ITE esNXgCJh-yk 08:47, 14:08] [ITE gwyneGrX9Jw 02:20] [OURS]
- **C4 In late, out early.** Every section starts where it gets good and ends on a short line or image, cut soon
  after; one ending of several; a win before a title or chapter. Never open mid-sentence; long-form may end open, a
  Short on its payoff. *Check:* one conclusion. [ITE WOX-WdXSOOc 07:19] [ITE urCAMKTsc6o 09:12] [OURS]
- **C5 Contrast, then hand off.** At every boundary start the section at a different energy or shot scale from how the
  last ended, and end each on a reason to move on (a pictorial bridge, a verbal hand-off, a question answered next,
  tension released next, a sound bridge); carry energy through when one push is the story. *Check:* one sentence per
  boundary naming its reason. [ITE esNXgCJh-yk 12:36] [ITE hwecWg2IR18 01:02] [AOTC dune]
- **C6 Ending early, opening last.** In every edit fix the ending and what the opening promises early; finish the
  opening last, from what the story became (hook options come after the main version); never polish the opening
  first. *Check:* the opening was revisited after the ending settled. [AOTC pop] [AOTC mi] [JH 23:54]

## 4. Dialogue (when talk or narration drives)
- **D1 Pull, cut down, re-arrange, retime, then cover.** In talk-led sections pull every line on the subject
  (`letitedit_words`, `letitedit_search`); cut errors, repeats, tangents; re-arrange into sync islands in story order,
  one job each, with a chosen first line (question, poetic line, premise, stakes, doubt) and a short last line; retime
  (D3); then cover. Not dialogue first when sound, music or action carries the meaning: build that first instead
  (letitedit-rough). *Check:*
  the words stop changing before cover goes on. [ITE iAKUVUD7fG0 04:27, 11:12] [ITE urCAMKTsc6o 13:01]
- **D2 Errors out, best take in.** Unscripted speech gets two passes per speaker: false starts, restarts, repeats,
  hesitations and extra endings, then the detail; keep non-words with character (a laugh, a firm "yeah").
  `letitedit_find_takes` groups repeats (never picks): choose the spontaneous take whose face agrees (R1) and the
  ending that resolves. Not: scrubbing a fluent voice. *Check:* a reason per take. [ITE urCAMKTsc6o 10:07] [AOTC skeleton]
- **D3 Retime line by line.** In talk-led sections compress drag inside a thought (search pauses of a second or more),
  keep the breath where one thought ends and the next starts, open space after key lines (P4); the `tighten` op is a
  first pass only. Never one pause setting per person; leave good natural rhythm alone. *Check:* uneven sentence gaps;
  in-thought gaps over ~1 s are deliberate [GEN]. [ITE DcA-Jfa2fdw 04:35] [AOTC porcelain]
- **D4 Keep the melody; listen.** At every join, joined fragments sound like one thought: one emotional temperature,
  an unfinished contour into the join, the voice's arc kept; smooth joins with a short crossfade (~6-8 frames at a
  tonal jump, 2-3 at a stutter) and same-place room tone; never judged from text. *Check:* hear each join
  (`letitedit_check_range`) or log it as unheard. [ITE xiJmwycUxTY 08:27, 10:24, 14:19] [OURS]
- **D5 The meaning stays theirs.** Allowed: cleanup, retiming, reordering whole thoughts, choosing takes. Only
  with the person's OK, and never for third parties in documentary or interview modes: a sentence from different
  answers; a dropped negation, qualifier or condition; an answer moved to another question; a reaction from another
  moment; borrowed audio over visible lips. Scripted work may borrow words across takes. *Check:* each sentence maps to
  one answer; removed "not, never, unless, but, maybe" reviewed. [ITE KAO0n3C0kAg 12:09] [GEN]
- **D6 Visible jump cuts are a choice.** Hide face-on joins by default (cover, a reaction, a size change); leave one
  visible only where tone and audience suit it, with a reason (energy, comedy, a ramble compressed); break up runs; the
  budget is the mode's; calm, premium or documentary pieces cover most. *Check:* visible jumps per minute and the
  longest run. [ITE A2RYo1xNSA4 06:24, 08:58]

## 5. Faces and b-roll
- **R1 Cut for body language.** On every take and key line read eyes, swallows, breaths, posture and hands, and place
  them on purpose (a nervous smile, a gulp before going on); when words and face disagree, change take or cover, unless
  that is the story; never retime a voice against its face. *Check:* frames at each key line
  (`letitedit_check_frames`) agree with the words. [ITE mQT6QnsM2eI 07:00] [ITE DcA-Jfa2fdw 09:18] [AOTC skeleton]
- **R2 Reactions with a purpose.** For a real reaction to that moment, cut to a listener to show what they think,
  foreshadow, or show how a line landed, a few frames to ~0.5 s after the trigger; hold when the feeling matters; none
  borrowed (D5), none that cue a laugh. *Check:* a stated purpose each. [ITE D2iBdbNej78 04:49] [AOTC invite]
- **B1 A job and a link for every run.** Jobs: illustrate the words, hide joins, make space between islands, set mood
  and place, carry structure (progression, subtext, a hand-off). Links: literal, symbolic, mood, loose wallpaper;
  literal early (hooks, cold opens, Shorts), subtext later; pick by the section's tone before its topic. The amount is
  the mode's; never wallpaper under an emotional line. *Check:* each run's `why:` names its job and link.
  [ITE 9jRZIqPQHm8 00:19, 05:37] [ITE xZnHgyeZlsU 16:35] [AOTC pop]
- **B2 Sequences over single shots.** Show a process, journey or action as a chain: three or more shots that advance
  it, a size change between neighbours, a completion shot (a minute or two of action can need ~8 s); a list gets a
  picture per item. No run of pretty shots without progress, no three same-size shots in a row. *Check:* shots, sizes,
  completion per run. [ITE jN3TIBIQlac 01:48] [ITE zXHKcITf3x8 20:22]
- **B3 Anchors and timing.** In talk with cover mark anchor words (emotional peaks, key nouns, list items, tonal
  shifts); on an emotional anchor show the feeling (a stare, a breath, hands, a detail), not the topic. Enter cutaways
  on the word, a look or matching movement; choose tell-then-show or show-then-tell (tell-then-show everywhere gets
  dull); a new image the line comments on registers first (~0.5-1 s [GEN]). *Check:* each anchor is covered on purpose
  or left on the face. [ITE jN3TIBIQlac 04:43] [ITE WOX-WdXSOOc 47:27] [ITE 5G2wGolpXxE 24:22]
- **B4 The face for key and closing lines.** Stay on an on-camera speaker when eyes or voice add meaning (credibility
  lines, jokes, payoff reactions) and after a revealing line until the expression resolves; each speaker on their
  section's last line; cover information-only bites. A Short's first frame may lead with the recognisable thing.
  *Check:* key and last lines on camera, ~1 s held after [GEN]. [AOTC pop] [ITE pRpaqx_5jD8 09:36]

## 6. Tension
- **T1 Open loops.** Raise questions the viewer carries (will it work?), keep them open long enough to pull, close the
  main one late; small loops close sooner; mark `loop:open:<id>` / `loop:close:<id>`; each section has a stake (S3) or
  a loop. *Check:* no loop left dangling (a declared open ending may leave the main one open). [ITE D2iBdbNej78 04:14] [JH 16:18]
- **T2 Withhold answers, not the premise.** In openings and reveals the viewer must grasp what's happening and why it
  matters; hold back the outcome, details and twist; long-form may drip clues but names the core problem early; a
  foreshadow promises the payoff's shape, not its result. No "when is this?" cutaways or muddled non-linear openings.
  *Check:* first-time viewers are intrigued, not confused. [ITE esNXgCJh-yk 05:28] [AOTC mi] [JH 2:34]
- **T3 Clocks, escalation, complications.** In deadlines, attempts and jokes: a real deadline gets a visible clock (times, dates); each return to a
  thread raises the stakes; complications stay in; meet the expectation set, then twist if the footage twists; keep
  the line from setup to punchline clean; no invented clock or twist (S6). *Check:* time markers run in order; each
  return raises a stake. [AOTC pop] [JH 16:32] [AOTC invite]
- **T4 Slow into the moment; protect the build.** Before a critical moment (reveals, climaxes, punchlines) decelerate
  (longer shots, fewer cuts, perhaps no music); hold after the reveal; never break a build with an aside or a title,
  however good; a hold without contrast around it loses force. *Check:* shots before a tagged reveal run longer than
  the section's average. [ITE D2iBdbNej78 06:35] [AOTC invite] [AOTC skeleton]

## 7. Repetition, transitions, time
- **L1 The device ledger.** Always count devices as they go in (a `devices:` note in `letitedit_journal`):
  transitions, punch-ins and zooms, whips and glitches, sound hits, title moves, reveal treatments, reaction formulas,
  section openings and endings. Not twice within ~30 s [GEN]; a repeat escalates or changes; the strongest goes to the
  biggest moment; keep a quiet stretch. Series identity (a recurring first frame, bookends) is grammar. *Check:* counts
  and spacing (`letitedit_timeline_read`). [ITE 4s7WdcyV1H4 06:04, 11:04] [JH 10:00]
- **X1 Straight cuts; scarce styling.** Straight cut by default; any other transition carries its reason in a marker:
  a dissolve or card for time passing or a change of place; a superimposition for a head-space or vision; a wipe whose
  direction follows the on-screen motion; a cut to black as a chapter marker at a turning point (the same length each
  time); a cut, not a fade, to black on a beat to end a lively scene. Never a dissolve to hide an edit you couldn't
  solve. Not counted: the short audio crossfades at dialogue joins (letitedit-fine). Check: every non-cut transition
  has a reason; no dissolve inside continuous dialogue; black gaps equal [AOTC Dune; AOTC Skeleton Crew; AOTC Hamnet;
  ITE xZnHgyeZlsU 26:40; FEP 4D] [AOTC dune] [AOTC skeleton] [ITE A2RYo1xNSA4 04:25].
  - **Stylised devices** (glitch, whip, crash zoom, flash, punch-in, speed ramp, shake, light leak, text pop, VFX
    pop-ups, shock jump cuts, repeated whooshes) need a narrative reason matched to the audience: no high-speed jump
    style in a calm brand or gallery film. One use per video unless each use escalates (punch-ins for emphasis follow letitedit-fine FINE-9; a Look's measured
    rate sets its own count); the strongest saved for the
    biggest moment; no stylised move on consecutive beats, and never the same device on neighbouring beats. A scale change that only hides a jump cut is cutting
    grammar (letitedit-fine), not a device; a zoom for emphasis is one. Log each in the repetition ledger (L1). "Less flashy"
    removes these first and keeps the plain cuts. Check: device counts with their times, and a reason for each [ITE 4s7WdcyV1H4 11:04; ITE
    A2RYo1xNSA4 08:03; ITE art:why-repetition-in-editing-kills-impact; AOTC Skeleton Crew].
- **X2 Time: hide it in a moment, show it when it's the stakes.** Inside a moment compress invisibly (dead pockets
  out, steady shots, matched movement, covered joins); when effort or duration is the stakes (a repair, a build, days
  of travel) show it passing: a visible change, a card with the real elapsed time, a step montage, jump cuts in a
  locked-off shot; transit only with a purpose. *Check:* each big recording-time gap shows a change or a device.
  [ITE WOX-WdXSOOc 24:48] [ITE A2RYo1xNSA4 03:24] [FEP] [OURS]

## 8. Revision: notes into levers
A revision from the person's notes reads `references/levers.md` first, in full: **V1 Note to levers** (where the
note applies, every other choice kept but not its faults, a note's measurable target kept), **V2 Two destinations**
(a second version for an open note; an open brief may get one too, same structure, another feeling, compared with
`letitedit_try`), the short notes table and the full one. Through every later step of the revision: "Keep everything
else as it is" keeps the content and choices, not their faults: a clipped word, a cut through a sound or another
fault a review finds there is a repair, so fix it and say so. A note's measurable target (a length, "cut the last 2
seconds", a level, a size) is kept: fix joins within it, at the clean cut point nearest the target, and take any
time a repair needs from elsewhere, never from the note; say "partly" only when no clean cut point is near, and miss
by the least.

## 9. Before a render is shown
- Run the muted 10-second test (C3), the first-time-viewer pass (T2), the gear list and boundary reasons (P3, C5),
  the device ledger (L1), a listen to every join or a note of those not heard (D4), and the meaning map (D5). Note the
  results in `letitedit_journal` (`craft: ...`); the final word is still `review.md` (letitedit-gate).
- If `letitedit_guide` doesn't list a tool named here, do the step with existing tools (`references/checks.md`).
