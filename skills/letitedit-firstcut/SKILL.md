---
name: letitedit-firstcut
description: Make a first cut for the person from a folder of raw footage (letitedit's New video button, formerly "Make a first cut", or "make me a video from this folder") - run the letitedit stage skills one at a time on the footage in place, put a one-line "why" on every clip, put the strongest opening in and leave others that differ in approach as hook candidates for the app's New hook button (no project copies), review the export with letitedit_review_bundle before presenting it (review.md is the final word), then take plain-language fixes. Use with the letitedit router.
metadata:
  version: 0.6.0
---

# First cut from a folder, then fixes in plain words

**Decision:** the whole first version of the person's video. They approve and correct; you decide.

**Inputs:** the footage folder(s) and what they said they want. The router writes `brief.json` (`mode`, `driver`,
`feel`, deliverables, `must_keep`, `claims`, `ending`, `narration`, and the rest): ask only what you can't infer; infer
the mode and driver from the footage (letitedit-log's `driver_note`) and say which you chose. New video's request
fields (`Style:`, `Look:`, `Theme:`, `Format:`, `References I added`, `Captions & pace:`, `Music:`, `Music file:`) mean
what the router's "New video choice fields" says. Evidence tags as in the skills README; documents in
`references/sources.md`.

**On every first cut:**
- **Check every dialogue join before the first export, with the tools rather than by ear.** Word timestamps aren't
  sound boundaries. Leave source handles, so the first and last sounds of the words either side of the cut stay in,
  especially where a pause was removed; `letitedit_words` marks where the sound starts and stops. Then render the join
  (`letitedit_check_range`) and read the words the render says there (`letitedit_words(project)`). A word that comes
  out clipped, missing or said twice means the join isn't done: move the cut to a clean boundary or widen the handles.
  Audio fades don't restore a missing sound. You can always run this check, so never stop because you can't hear the
  audio yourself.
- Spell the spoken product name **letitedit** in captions.
- **A measured Look.** When the chosen Look's card (`letitedit_looks(action='get', id=<id>)`) lists `measured` files
  (Learn saves them beside a Look's recipe; a library Look has none), load **letitedit-learned-look** before the story
  and follow it to the export: placing and proving every measured device, its lighting, graphic kit, format, sources
  and b-roll, and the checks on the export.
- Before export, call `letitedit_look_check(project)` for the chosen Look. A library Look (nothing measured beside its
  recipe) returns `measured: false`: its recipe is followed as written and needs no receipts. For a measured Look,
  letitedit-learned-look says what the check needs.
- Do not change the person's Image generator setting; use stock and available allowed image routes as needed.
- The final file is always a normal `letitedit_export`, followed through `letitedit_export_job`. Never deliver a
  `letitedit_check_range` preview or a file made by hand with ffmpeg instead.

## 1. Build it, one stage at a time
**FIRST-1 Run the stages in order.** Do: letitedit-log (by mode; pictures first for files without talk; takes with
`letitedit_find_takes`; every requirement mapped; the emotion graph read when it is built) -> letitedit-story (purpose,
sections with driver, gear and feel, loops, reveals, opening and ending, `pickups.md`) -> letitedit-rough (built in the
driver's order, rendered early, story QA) -> letitedit-fine -> letitedit-finish -> letitedit-gate. Use the footage in
place. While building: section 1a; to the export: section 1c.
- **No footage.** The request says so: there is no folder to log, so the story stage works from the person's
  description and the `show` files.

**FIRST-1m Several angles of one talk.** When the clips are cameras that filmed the same conversation (long clips of
the same length or so, the same voices; New video's request may say so), it is one talk, not separate takes: sync them
(`letitedit_sync`), find who speaks when (`letitedit_speakers` on the clearest-sounding angle), then cut the camera
switching with `{op: multicam}` (interview mode, its multicam section) and do the story work on the main track as for
any talk. [OURS]

**FIRST-3a Choose a complete story before its length.** When New video says "Let the AI choose", select the best
complete thought in the source: setup, development and payoff, with a source range for each.
- Put the chosen Short length and why it needs that room in `story_plan.json` as
  `deliverables.short.selected_story_s` and `length_reason`; put the exact closing words in `payoff_line` for a spoken
  payoff. For a picture or sound ending, use `payoff: {"kind": "visual" | "sound" | "audiovisual", "description": "the
  closing action and release"}` instead, with its logged source range. The critic checks that moment in the export;
  silence never proves it.
- A Short from several minutes of useful talking footage will rarely be under roughly 20 seconds; a self-contained
  short moment may be. Ending on a complete thought: section 1c.
- Watch the rough cut for the *story* before spending time polishing captions.
- Its target and its check: section 1c.

## 1a. Building the cut
**FIRST-1, while building:**
- **Skills.** Keep letitedit-craft and the mode's playbook loaded throughout, add letitedit-shorts for a short, and
  load each stage skill **before** that stage. Read sound, captions and graphics skills when those finishing tasks are
  present, even when a style was chosen. How to read them (what is attached in full, the rest in one step, a clipped
  read) is the router's section 2.
- **The Look.** When the request names a Look (`look:` line), read its recipe in full with
  `letitedit_looks(action='get', id=<id>)` before letitedit-story, again before the fine cut and the finish, and before
  the review, and keep the brief's `look` so the critic judges the video against it. For `look: auto`, choose one
  first (router, `look` field) and tell the person which and why in your first progress message. For `look:
  freestyle`, read no Look recipe and choose the mode from the footage (router, `look` field).
- **Inputs.** When the request lists inputs the person gave the Look (a block that starts "What the person gave this
  Look"), keep the record beside the project as soon as it exists (`letitedit_looks(action='inputs', project=<.mlt>,
  inputs=<the record path in the request>)`), work from the roles as the router's `inputs` field says (`show` may
  appear, `style` is for looking at only and never appears), record a `show` file you leave out with `unused={path:
  reason}`, and ask nothing: the run has no one to answer. On a revision or a fresh chat, read the record back with
  `inputs='read'` before changing anything.

**FIRST-1s A fresh conversation for the review.** Only when the request has the line `sessions: one per stage` AND the
reply to your `stage:<name>:done` note has `hand_over`, the app moves the work to a fresh conversation at that point:
after `stage:finish:done`, for the review rounds and the final export (section 4), when this conversation has grown
big. The fresh conversation reads the same files; nothing is lost that is on disk.
- When the reply asks for it: (1) add the hand-over, `letitedit_journal(action='add', text='handover: ...')` (it writes
  `handover.md`), (2) end your turn with one line, `Stage <name> done; next: <stage>`, and start nothing more.
- The hand-over holds what the files don't: the person's words that matter for the rest (quoted), each decision with
  its reason, what was tried and dropped and why, open problems and loops, numbers the next stage needs (target and
  current length, the chosen Look and Theme, the music plan), the clip ids or times of anything fragile, and the exact
  next step. Write it so someone who saw none of this conversation can go on without asking.
- Without the line, or when the stage note's reply has no `hand_over`, the whole run is one conversation: go straight
  on to the next stage.
- Reading a hand-over, phases with bookkeeping in code and lean stage handoffs: section 1c, FIRST-1s.
[OURS]

**FIRST-3b Give a default talking-head Short visual rhythm.** With "Let the AI decide", the picture should change in the
first seconds.
- Modest jump-cut punch-ins on emphasis or new ideas, a return to the wider frame; important emotional lines stay on
  the face.
- A sourced b-roll shot or a simple, honest graphic when the words call for proof or explanation; if the source lacks
  it, record a pickup instead of implying proof.
- Every crop and graphic clear of faces, captions and phone buttons. Check the opening muted and the full export for
  static stretches; do not make a calm story frantic.
- A dialogue-led product Short longer than about 15 s: one punch-in followed by a held close-up is too little picture
  change: look for a wide → close → wide sequence across meaningful beats, or a sourced cutaway that explains one.
- Inspect the *rendered* picture at each change: several cuts and zoom settings can still read as one unchanging
  scene.
- A product action described with no screen recording: a clearly labelled explanatory illustration if it makes the
  mechanism clearer, and the real demonstration listed as a pickup. Do not draw an illustration that looks like proof
  the action occurred.
- Its rules for fixes up to the export (an illustration over the face, a graphic against captions, `hold:`): section
  1c.
[GEN; OURS]

**Draw what no camera caught.** On talking-head or other visually thin footage, a first cut draws at least one scene
fresh in code (`letitedit_code_scene`) on the strongest spoken line, unless the person's notes say not to or their
Motion graphics setting is None.
- This is what people come to letitedit for: the speaker's words turning into a world made for them, such as a
  moonlit road opening up behind someone as they talk.
- Choosing the easier still diagram, card or zoom instead is the failure this rule exists to stop: those may sit
  alongside a scene for something the viewer must read, but they are not the scene. Equally, a beautiful world that
  doesn't show what is being said is a failure: the scene answers the words (`letitedit-graphics`).
- No real product recording is no reason to skip it: draw it, plainly as a drawing, and keep the demonstration on the
  pickup list.
- Record the line, the world and why in the story plan's `visual_decision`; `letitedit-graphics` says what makes a
  scene good. Further scenes need their own strong line: Motion graphics, 3D, Courage and "How much is going on?" set
  how far to go, and "AI decides" is your judgment.
- Plan its music and sound, look at it in place after every change (`letitedit_code_scene` returns the look; looking
  is cheap, so keep improving it) and in the full export.
- Do not browse My scenes for a first cut or copy a past scene unless the person asks.
[OURS]

## 1c. Rules that hold to the export
**FIRST-1, to the export:**
- **The stage mark.** Write `stage:<name>:done — <summary>` once, with the stage's last artifact notes in the same tool
  step, after the outputs are ready; check that the reply accepted the mark. The summary is part of that one note, not
  a second mark.
- **Bookkeeping in code.** When the start message says bookkeeping is done in code, code writes each stage mark once
  that stage's outputs check out, and the phase's hand-over: write neither. The outputs themselves stay yours.

When: always. Not: do not skip the picture pass on wordless footage. Check: each stage has its actual outputs and its
own accepted `stage:<name>:done` journal note. [OURS] [GEN]

**FIRST-1s, the conversation that receives the work** (with `sessions: one per stage`, section 1a):
- A conversation that starts from a hand-over reads it, the files it names and the journal's latest notes, loads every
  skill the next stage needs in full (as for any stage: router section 2; another skill as soon as a fix needs it),
  and goes on; it never redoes a stage that is done.
- A run in phases with bookkeeping in code (its start message says so) gets a hand-over made from the files: read it
  like any other, and add what it can't know (the person's quoted words, a decision's reason) as a journal note.
- **Lean stage handoffs** are experimental and off unless the run explicitly says lean stage handoffs (a separate
  switch, `new_video_lean_stage_handoffs` / `LETITEDIT_LEAN_STAGE_HANDOFFS`): then the handover is a structured JSON
  object and every boundary may start fresh. Read `references/lean-handoffs.md` in full before each boundary, in every
  conversation of the run (a fresh one too).
[OURS]

**FIRST-3b, through every fix:**
- No clear space beside the speaker: let a short illustration take over the whole frame instead of placing a card
  over their eyes; bring the face back when the explanation ends. Check the actual rendered transition.
- Keep a useful graphic when choosing caption placement: move or reframe the footage for readable captions before
  discarding the only explanatory picture.
- A `hold:` marker needs a story reason; missing interface footage alone is not a reason to leave the whole middle
  visually unchanged.
[GEN; OURS]

**FIRST-2 Keep them posted; claim nothing.** Do: say briefly what is done and what comes next as stages finish; you may
show the rough render, marked "work in progress, not reviewed yet". When: during the run. Not: never present a version
as finished before `letitedit_review_bundle` has seen it. Check: progress messages carry no quality claims. [GEN]

**FIRST-3 Names.** If the request includes `Save video in: <folder>`, save the project, exports and AI working files
inside that exact folder, including for no-footage Looks. Keep source footage referenced where it is, never moved or
copied. Without that line, use the unchanged default: in the footage folder's parent, `<folder> - first cut.mlt`, and
`<folder> - first cut (short).mlt` when both are asked for. When: every first cut. Not: never inside the footage
folder; never move or copy the footage. Check: project files are inside the requested save folder when supplied,
otherwise next to the footage folder. [GEN]

**FIRST-3a, the target.** With "Let the AI choose", set `brief.json` `target_s` from the selected story, before the
rough cut. Never rewrite the target after export merely to make the check pass. End on a complete thought and keep the
promised payoff, even if that costs seconds. Check: the plan explains the length in terms of source
beats, and the final gate's story integrity check is complete. [OURS]

**FIRST-3c Batch checks around stable edits.** Once the story works, finish related picture and caption changes before
each face-aware `letitedit_caption_fit` call.
- Apply one plan, inspect its unresolved items and rendered frames, then fit again only when a later picture or caption
  edit invalidates it.
- Before a full review, inspect the rough export's opening and ending with `letitedit_check_range`, the rendered
  captions at 360 px phone width (including contrast against hats and busy backgrounds), and the source words at each
  cut; fix all those findings in one pass.
- If the fitter calls a caption over a cap clear because it sees only the face, protect the whole cap and re-fit; if
  the shared phone area has no clear space, move or zoom the footage so it still fills the frame rather than accept an
  unreadable cue. A caption on the chest below the chin is fine.
- Don't shrink footage that already fits the frame into a blurred or empty border to make room for a caption: that
  reads as a broken video, however clear the caption is (the project check flags it). An inset or split screen the
  Look or the person calls for is a layout, not this.
- Prefer a direct spoken benefit over a vague acronym or repeated false start, without changing the speaker's meaning.
- A full review belongs after a stable export, not after each small change; keep the final export and review after the
  last edit. This saves repeated renders without skipping the final checks.
- Follow an export with `letitedit_export_job(wait_s=1440)` (less for an AI with a shorter limit on a tool call); it
  returns early when finished, and avoids a run of short status polls. A job still `waiting` for the PC render lock is
  in line behind other work: keep following it, and don't end your turn until it has finished. Nothing reports back to
  you later.
- Word-by-word captions are the slowest thing to rebuild: settle the words and picture first, then build them once.
- Use letitedit's tools rather than shell scripts, including `letitedit_timeline_apply(code=...)` for long lists: a
  shell command can stop and ask the person, who may have walked away.
- A tool result saying the call was moved to the background is not a result: the tool is still running
  (`letitedit_status` names it). Don't call it again and don't plan from what it hasn't told you. Do what doesn't need
  it; if everything does, end your turn saying you're waiting: its result comes back to you by itself, the app keeps
  the job open, and you carry on from there.
[OURS]

**FIRST-S A song in the request.** When the request names a song to cut to (a legacy `song:` line, or `Music: trending`
with a `Music file:`; `Music: own` instead includes the supplied song in the export), read letitedit-sound section 13
before the rough cut and follow it: you pick the part, the upload has no song, the preview does, and the closing
message says how to add it. `letitedit_song(mode='land', project)` is the last edit before the export. Nothing is
asked.

## 2. Say why, on the timeline
**FIRST-4 A why on every clip.** Do: one marker spanning each main-track clip, `why: <one plain sentence>`
(`letitedit_bin`), saying what it does for the story, not what it shows ("Shows the noise, so we care about fixing
it"), and a `cut: <what and why>` marker at each big removed stretch ("cut: second take of the intro, weaker"). They
read these in the Markers panel. When: every first cut and every fix. Not: no `why:` that only describes the picture.
Check: every main-track clip has one. [ITE art:software-vs-storytelling-editing] [ITE CdyTIng0M8Q 02:20]
- **Bookkeeping in code.** When the start message says bookkeeping is done in code, code writes each main-track clip's
  `why:` marker from the `why` of the select in `selects.json` that plays it: write each select's `why` as what the
  clip does for the story, and add markers only for the clips the hand-over lists as unmatched. `cut:` markers, and
  `why:` markers for clips a fix adds (FIRST-8), stay yours.
- **The rest of the books in code.** When the start message also says code writes the `beat:`, `loop:` and `cut:`
  markers, write each big removed stretch as an entry of `selects.json`'s `cuts` (`file`, `in`, `out`, and its what
  and why as `why`) instead of a `cut:` marker, and rewrite no marker after an edit: markers follow their clips through
  every apply. A clip a fix adds still gets its `why:` marker from you (FIRST-8).

## 3. Openings, chosen for the mode
**FIRST-5a0 On a short from a talk, decide the opening before you draw.** A scene timed to the words is expensive to
redo, so a late swap doesn't happen in practice [OURS].
- So at the story stage put the line a stranger would stop for first, even if it was said last: the stakes, the fear,
  the result. Recording order is no reason, and "the next line needs the name first" is solved by the next line saying
  the name.
- An opening on the fear that the ending answers is a setup and its payoff, not a repeat of the ending's line. A line
  chosen because it's easy to draw is no reason either: the stakes can be drawn too.
- Keep what pays it off later in the video, and cut the opening line from where it was said.

**FIRST-5 Openings that differ in approach, made last, kept as hook candidates.**
- Do: once the main version is final (the beginning is cut last), run `letitedit_hooks(project)`: distinct candidates
  from the cut's own footage in about a second (a moment with in/out, 2-3 text options, the approach, why), kept in
  `<project>.letitedit/hooks.json`.
- Judge them against the plan's opening templates for this mode (letitedit-story STORY-12): urgent (the stakes in one
  breath), poetic or withholding (sound first, longer shots, the reveal later), a literal cold open, a result or
  flash-forward (only when it doesn't give away how), the person's own question, mid-action, or a brand or product
  frame first. For a short, each is a visual hook understood muted plus a foreshadow by about 3 s (letitedit-shorts).
- Put the strongest in the main project: `{op: hook, candidate, text}` swaps an opening as one undo step ('h0'
  restores the cut's own), or cut it into the story when it is a restructure, not a swap.
- Leave at least two others that differ in approach as `new` candidates for the app's **New hook** button, which swaps
  each one in as one undo step: sharpen their text in hooks.json, or add your own (`by: claude|codex`: a source moment
  with in/out, 2-3 text options, why) when the generated ones are weak or alike. Listing candidates marks nothing; mark
  only the ones you ruled out (`mark: {id: rejected}`).
- When the start message says bookkeeping is done in code, New hook adds and sharpens candidates when the person clicks
  it (its own background call): choose and swap in the main opening, mark what you ruled out, and write no extra
  candidates.
- When: every first cut. Not: no project copies for other openings (the New hook button replaces them); never three
  variations of one idea; never an opening the rest of the cut doesn't pay off, or one that repeats the ending's line.
- Check: the main opening passes the muted 10-second test for the intended feeling. After a swap, refresh the `why:`
  markers of its first clips, check that the music entry still fits it (a poetic opening may hold the music back) and
  that the captions line up (`letitedit_check_range` on its first 15-30 s; captions made before a swap don't cover the
  new opening: caption it again).
- Judge the alternatives you leave from their words, not from previews: during a first cut don't call
  `letitedit_hooks(preview=...)`, since New hook makes a preview when the person asks for one. Check each opening's
  words and ending so it does not repeat the payoff line.
[AOTC GNIP] [ITE esNXgCJh-yk 08:47] [JH 10:59] [JH 19:56] [OURS]

**FIRST-5a Music for this cut.** Do: when the first cut wants a bed and nothing from the person, the Look or the style
fixes its music, either write one with `letitedit_music_write` (letitedit-sound 2a) or use real music (2b): your own
call, with no one asked. Writing works with whichever AI is driving, on any PC; the library holds only what this PC
has. If a score still fails its check after two revisions, change route and say so. Not: a video the sound map leaves
dry. Check: the file is on the Music track, `{op: score}` has run, and a written score's check passed. [OURS]

## 4. Review it, then show it
**FIRST-5b The measured Look first.** With a measured Look (letitedit-learned-look), export the fine cut (a preview is
enough) and run `letitedit_look_check(project, video=<that export>)` before the first review round; fix what it
measures and check again on the new export. Read `references/measured-look.md` in full before that round: it says what
to fix and when a finding may stay open. A library Look skips this. [OURS]

**FIRST-6 The bundle before the person.** Do: review on a preview, then render the final once, as letitedit-gate's
steps say (one call renders and reviews; an unchanged video keeps its review; two full rounds, then a targeted look
per changed cut, three at most; the confirming bundle on the final itself; the exception for a critical or major still
listed). When: every first cut. Not: never present a render the bundle didn't see as checked, and never a final made after an edit the last
preview didn't have. Check: the final's `review.md` is newer than the final export, and it is the final's own review
(`render='final'`) or its final-file check matches. [OURS] [RES Timeline-Bench]
1. **Preview rounds.** Make a preview of the main version and run letitedit-gate on it in one call
   (`letitedit_review_bundle(project=<project>, render='preview', brief=..., critic='run')` has the export engine draw
   the preview, smaller, with the final's sound, waits for it and reviews it). Fix the blocked and revise findings and
   run that call again.
2. **One review per rendered version.** If its video bytes have not changed, read its
   existing review instead of running the critic again. Use `render='preview'` for a fix round, then review the delivered final as the
   gate says; keep the existing round limits and targeted-review rules, not an extra full critic round for an unchanged
   video.
3. **Two full rounds, then hand it over:** the person is waiting and can ask for more. After the second, fix what a
   measured check still lists and any major you can address with the available footage, a crop reset, a clear caption
   position, a truthful graphic or a cleaner cut, run the bundle once to confirm (a reviewer takes one targeted look at
   what is still open, one per changed cut, three at most per edit: `letitedit-gate`), and present the final.
4. **A finding is fixed** when the change answers all of it: every quality it names (a shot "darker and greener" than
   its neighbours needs its brightness and its colour matched; "no reaction" needs faces whose reaction reads at that
   size), checked on the frames at that moment beside its neighbours, not on one number of your own. An item the
   targeted look keeps open is what's left, with what you changed, never "fixed".
5. **The confirming bundle runs on the final itself:** `letitedit_review_bundle(project=..., render='final',
   critic='run')` renders the full-size final from the timeline as it stands and reviews that file, so the review is of
   the file you deliver and no `final_of` check follows it (letitedit-gate step 5). (A final rendered on its own, from
   `final=True` on a preview round or from `letitedit_export`, still gets the bundle with `final_of=<the reviewed
   preview>`: a short technical check that it is the reviewed video; a difference is a finding, so export again.)
6. **Then write the closing message (FIRST-7) at once,** quoting the final's `review.md`, with what is still open named
   as what's left; don't edit or export again just because measured findings remain. If an edit nevertheless follows,
   review the new export before handover under the same round limits; the earlier review cannot cover it. The
   exception, a critical or major finding the confirming bundle still lists: letitedit-gate step 5's "One exception".
   The round limit caps the critic, never the fixes: no critical or major is handed over as it is while a look is left;
   one that truly can't be fixed with this footage is named in the closing message as not fixed, with what you tried.
7. What needs new footage, a verified fact or the person's decision is on the **For you** list in `review.md`: it
   doesn't hold the video back and doesn't earn another round. A missing product demonstration never excuses an
   unchanging picture or captions covering a hat. If footage cannot support a product demonstration or a clean story,
   say so as a pickup rather than showing an unsupported claim.
8. One opening the person settles on gets the full bundle again (on its preview) before a final export.
   `letitedit_show(<main project>)` opens it for them.

**Captions after the last edit.** [OURS]
- After the last picture, opening or caption edit, run `letitedit_caption_fit` again and apply its plan if its summary
  shows fewer `covers_face` after than before; on a tight close-up the apps' covered areas can leave only the face, so
  otherwise place those captions by hand.
- If that last edit's reply already re-checked the captions (`captions_followed` applied or already fitting, none over
  a face, no placement problem left), that is the fit: don't run `letitedit_caption_fit` again.
- For a Short going to TikTok and Shorts, use `platform='tiktok'` and `faces='hard'` (see letitedit-captions §5:
  `phone` puts captions under the chin on a close-up, and the captions belong in the middle of the room below the
  face). Read the remaining `violations` and `unresolved` entries, then check the export.
- Any later `{op: captions}` call, including one with hand-written cues or a style change, replaces that fit: repeat it
  before the bundle.
- Within the two rounds, do not close a round while the bundle still lists measured caption placement, phrase,
  reading-speed or cut-edge faults; after the last bundle (`rounds.final`) they are listed as what's left, not fixed.

**FIRST-7 The message.** Do: the video path, then quote the **For the person** section of `review.md` (the verdict,
open findings, what was waived and what wasn't checked; listening isn't done by code); then the first-cut extras: the
opening you put in and why, the other openings waiting behind the app's New hook button, one line each (approach and
words: "Press New hook to try them; each is one Undo step"), the shots worth filming next time from `pickups.md`, and
the one change you would make next. When: every presentation. Not: no "looks great", no verdict of your own. Check:
the message quotes the plain section of `review.md`, not its technical tables. [GEN]
- Say what `review.md` says, in plain words, with its numbers: the verdict, how many findings are open and of what kind
  ("13 captions flagged as covering the face"), not a softer description of them ("some still touch the chin edge"),
  and which are still open because you chose to leave them.
- Name an opening candidate only if `hooks.json` lists it, and say whether you have previewed it; if you haven't, say
  that.
- What you changed since the last review comes from the review's "fixed" line, not from memory.
- In a run with no window (New video or a Studio job working on disk), letitedit opens the finished project for the
  person when the run ends: `letitedit_show` opens nothing there and says so. Say that, never that the project is
  open.
[OURS]

## 5. Plain-language fixes
**FIRST-8 A fix is a plan revision.** Do: map the note to levers with letitedit-craft's revision table ("less flashy",
"give the reveal room", "too fast", "keep the joke, drop the intro"), make the change with the same stage skills,
update the `why:` markers that changed, and run the bundle again before calling it done.
- Before removing or reordering beats, keep the current version (`letitedit_project_new` to `<name> - first cut
  v<n>.mlt` with `copy_of` the main); small trims need no copy, since each apply is one undo step in their open window.
- "Use the question opening" (or a candidate id) means `{op: hook, candidate}`: one undo step, no copy. First cuts made
  before openings moved to New hook have "(hook B)" / "(hook C)" project copies (Versions of This Video lists them):
  there "use opening B" means copy the main as v<n>, then make the B copy the main version.
- Reply one line per change ("Intro removed: now opens on the summit view at 0:00") and say where the previous version
  is.

When: every fix request. Not: don't rebuild from scratch for a local note. Check: a version copy exists before every
structural change; `review.md` is updated. [ITE KAO0n3C0kAg 00:27] [GEN]

**FIRST-9 Say once what a request costs.** Do: if a request would break the story, do it and say once what it costs
("Cutting the bracket line removes the setup for the ending, which now arrives unexplained"); when it drops a brief
requirement (a `must_keep` line, the `ending`), update `brief.json` too, or the gate will block on it. When: requests
that remove a setup, a payoff or a requirement. Not: don't argue twice. Check: the cost is in the reply and the brief
matches the request. [ITE KAO0n3C0kAg 00:27] [GEN]
