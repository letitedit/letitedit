---
name: letitedit-fine
description: Fine-cut a letitedit edit after the rough passes story QA - retime dialogue line by line (compress drag, keep the breaths that end thoughts, add space after key lines) instead of one pause threshold, clean cut points and joins (centred audio crossfades, room tone), J and L cuts (the split_edit op), b-roll timed by its job and cut as sequences, punch-ins and holds under the repetition guard, and pace measured against the story plan's gears or a reference video. Use for the fine cut, or when the person asks for tighter, slower, more breathing room or less flashy.
metadata:
  version: 0.3.0
---

# Fine cut

**Decision:** the timing of every join, so each section moves at its planned gear and feeling and every line lands.
letitedit-craft owns the craft (P2-P5 pace, C5 hand-offs, D3-D6 dialogue, R1-R2 faces, B1-B4 b-roll, T4 builds,
L1 the device ledger, X1-X2 transitions and time, the revision table); this skill applies it with the tools and
checks it. The brief's `feel`, the plan's gears and a `reference` beat every default here.

**Inputs:** the rough project (story QA passed), `story_plan.json` (sections with driver, gear and feel; key lines
and reveals), `log.json` (delivery, face or cover notes, room tone), `brief.json` (`feel`, `reference`,
deliverables). Measures: `letitedit_measure` (any video: cuts and words per minute, shot lengths), the
`picture_change` report of `letitedit_export_job` (shot lengths, near-still stretches),
`letitedit_words(project=..., per_word=True)`. Evidence tags as in the skills README; documents in
`references/sources.md`.

## 1. Retime dialogue line by line (craft D3, D5)
If the chosen style has `custom.sliders.pauses`, use that choice here: `0` keeps natural pauses and avoids automatic
`tighten`; the middle balances breaths with momentum; `6` favors jump cuts while keeping complete words, thoughts and
meaningful reactions. Use `editing.pause_style` and, when present, `editing.max_pause` as a starting point, then judge
each gap by ear. If `pauses` is absent, the AI chooses from the story and brief.

**FINE-1 Clean first, then set each gap by ear.** Do: a first pass may clear dead air with the `tighten` op and a
generous `max_pause` (`letitedit_guide('tighten')`), or rebuild a talk section as one item per line
(`{clip, words: "..."}` cuts on the gaps around the phrase). Then set every gap on its own: compress hesitations and
search pauses inside a thought; keep the breath where one thought ends and the next begins; open space after an
emotional, complex or revealing line (extend that item's out point while the speaker stays silent so the face
holds, or let b-roll or a musical phrase carry the gap); keep laughs and reactions whole. When: every talk-led
section. Not: never one pause threshold for a whole interview or an emotional scene; never cut every breath for
speed; never change what was meant (craft D5: a sentence from two answers, a dropped "not" or condition, an answer
moved to another question all need the person's OK). Check: sentence-boundary gaps vary; after each key line the
next speech waits as long as the section's gear asks (craft P4); no in-thought pause of about 1 s or more unless it
is meant [GEN]; the render's words show no false starts or doubled words; every sentence built from two source
answers is listed in the journal (`frankenbite:`). [ITE DcA-Jfa2fdw 03:31] [ITE xiJmwycUxTY 07:40]
[ITE urCAMKTsc6o 05:41] [AOTC GNIP]
Where the person restarts a line ("without the LLM... without risking the LLM"), keep the restart and cut the first try,
at the sound where the restart begins; never leave a piece of the first try in front of it. The transcript often hides a
restart inside one stretched word: a word `letitedit_words` marks `[4.9 s: sound at 89.78-89.86, 94.54-94.68, nothing
between]` was said, then a pause, then said again (the same word twice, or a first try that trails off), so put the cut
where the last sound before the pause ends and resume at the sound after it, and drop the first try. Then play the join
(`letitedit_check_range`), read the words the render says there (`letitedit_words(project)`; that is how you listen): a word said
twice, or a word clipped at its start, means it isn't done. [OURS]
In a conversation (an interview or podcast brief, a Look whose `talk` is natural, a cut between angles of one talk)
cut only the false starts: a sentence begun, dropped mid-way and begun again, or a stumble that blurs the meaning.
Doubled words, a phrase said twice whole, an echo of the other speaker and a quick self-correction stay; the fine
stage and the review count only the false starts there (letitedit-modes, interview). [RES fox-tree-1995] [OURS]

**FINE-2 Shorts: tight edges, a breathing middle.** Do: remove the air before the hook, after the payoff, and any
meta line ("so today"); keep the breath that ends an idea and a beat after the payoff line. letitedit-shorts owns
the hook and the ending. When: short deliverables. Not: don't assume frantic: a story-led short can breathe. Check:
no idea boundary closed to zero; the tail as letitedit-shorts sets it. [JH 20:52] [JH 29:13]

## 2. Cut points and joins (craft D4, D6)
**FINE-3 Cut in the silence and on the move.** Do: never cut inside a word; start about 50 ms before the first word
and end about 80 ms after the last (30-200 ms) [GEN]; a gap under about 150 ms rarely cuts cleanly [GEN]; never cut
off a sound mid-way (a clang, a laugh, an 'um', a machine stopping) either. `letitedit_words` source times are where
each word's sound starts and ends, but a word's last consonant after a stop ('first': the vowel, a short silence, then the 'st'
release) and a soft opening ('s', 'f', 'h') can sit up to about half a second outside them: the review bundle and the edit guard measure the
real tail on the sound (the room's own floor, never past the next word), so end a cut past the tail it reports, not at the word's time; `~` after a word means it runs straight into the next: there is no clean cut
between them, so cut at the pause before or after, or cover the join (FINE-4). `timeline_apply` already moves a numeric clip edge that
goes through a word or sound to the nearest clean place, by the review's own measure, and says so in a `clean cut:` note: give the
word times you mean, read that note, and don't measure the sound around each cut yourself; where it says no clean place is near, choose
another cut (a sentence end, a breath) rather than nudging the same one. Pin an edge with `edge_mode: exact` only for
a reason the sound can't show: a frame chosen by picture (a move, a flash), a beat, a sound kept on purpose; write it
as `edge_reason` (the journal keeps it and the review quotes it beside any finding at that edge). Never pin a time you
measured on the sound yourself (your own loudness or ffmpeg scripts): the tool and the review measure the edge with the
same rules, so a self-measured pin is the edge the review flags. For speech, take the tool's place or the time the review
suggests (those times pass its own tests); when a reply says a pinned edge goes through a word or sound, take the clean
place it names or drop `exact`. [OURS] Enter a moving shot just before its move starts
(what professional editors mostly do: 398 film cuts) or already in motion, matching speed and direction across the
cut. Don't chase single frames: moving a cut 3-8 frames was mostly invisible to a viewer and to the measures
[OURS]; fix what reads as a jump instead. When: every cut. Not: a deliberate smash cut, or a mid-word cut
for comedy, is a choice: say so in its `why:`. Check: `letitedit_words(project=..., per_word=True)` around each cut; the last line ends on a finished thought (it falls and lands; if the source keeps talking right after the cut, pick another ending or find a take that lands), the review bundle's minor finding says when the source runs straight on;
`letitedit_timing(project, view='cuts')` (action phase, eye-trace jump, direction, size, sound across the join; fix the
`jarring` ones, read the `noticeable` ones); the review bundle flags words cut at clip edges (and their tails) and cuts that go through a sound (measured on the audio, with the
clean in/out points to use): move each to one of those points; don't waive one without listening.
[ITE WOX-WdXSOOc 16:51] [GEN] [OURS]

**FINE-4 Smooth a join that jumps; never hide a problem.** Do: where pitch, breath or room tone jumps at a dialogue
join, give it a short centred audio crossfade of about 6-8 frames: set the incoming item's `transition` to
`{type: cut, len: <seconds>}` (the picture still cuts, at the middle of the overlap, while the sound crossfades
across it; `letitedit_guide('effects')`). The overlap shortens the timeline, so leave about half the crossfade of
silence on each side of the join and no word fades. A 2-3 frame dissolve can clean a stutter at a line start; a
one-frame audio fade at a clip edge stops a click [GEN]: once the cut is final run `{op: declick}`, which ramps every
straight sound cut (music, split edits and crossfades are left alone). (`letitedit_timing(project, view='joins')` lists clicks, level and room-tone
jumps per cut) [OURS]. Fill an opened hole with that location's logged room tone,
never digital silence. When: dialogue joins that jump. Not: never a visible dissolve over an edit the cut hasn't
solved. Check: the join's words are intact in the project's words; loudness is steady across it (`letitedit_look`
loudness lane, `letitedit_check_audio`); joins you couldn't judge are listed for the person (code can't hear).
[ITE xiJmwycUxTY 10:16] [ITE gwyneGrX9Jw 14:21] [ITE DcA-Jfa2fdw 09:00] [AOTC Dune]

Visible jump cuts follow craft D6 (hidden by default, a reason for each one left, the mode's budget): log the count
per minute and the longest run.

## 3. J and L cuts inside a scene (bridges between scenes: letitedit-sound)
Read `letitedit-motion/references/camera-moves.md` for transition names, feeling,
handles, timing and supported methods. Choose matches or directional handoffs
from actual images; do not invent whip, focus or speed-ramp effects.
**FINE-5 Let sound lead or trail the picture on purpose.** Do: a J cut (the next shot's sound starts before its
picture) pulls the viewer into a moment or lets a line begin over the listener; an L cut (the sound runs on after
the picture changes) keeps a voice under a reaction or b-roll. `{op: split_edit, id: <incoming>, lead: s}` makes a J
cut and `lag: s` an L cut; `move: picture` keeps the words where they are and moves the picture cut instead (the
usual dialogue J cut: the listener holds while the next line starts). It uses the source beyond the cut, stays in
sync, refuses to cover words and names the most it can do; `lead: 0` removes it (`letitedit_guide('split_edit')`).
Make it the default at dialogue joins where the source allows; 0.4-0.6 s is a starting range [OURS]. When: reactions, lines that
start over a listener, voice under cover, most changes of speaker or place inside a scene. Not: never two voices at once; never a moving mouth on screen under sound
from another moment (only a speaker turned away, distant or out of frame). Check: frames across each overlap show
no talking mouth under foreign sound; the incoming sound's source is clear within a few seconds. [FEP bridge]
[ITE WOX-WdXSOOc 30:14] [GEN]

## 4. B-roll timing and sequences (craft B1-B4, R1-R2)
**FINE-6 Place cover by its job, and say the job.** Do: lay cutaways on a video track above the speaker (`insert`
with `at`), their own sound lowered or muted per letitedit-sound; give each a `why:` marker naming its job and link
(craft B1) and its anchor (a word, a look, a movement). Time it to the intent: tell-then-show (the picture arrives on
or just after its word) or show-then-tell (the picture leads so it registers before the line, about half a second
to a second [GEN]); enter on the anchor, an eyeline or matching movement; leave on a phrase gap [GEN]. Find shots
with `letitedit_search` and `letitedit_archive`. When: every cutaway. Not: don't key every shot to a keyword; no
wallpaper over an emotional line; never the same source range twice unless it is a declared callback or bookend.
Check: every b-roll item has a job, a link and an anchor; its frames show what the job needs (`letitedit_ask_frames`
only for literal facts); no repeated range without `callback:`. [ITE 9jRZIqPQHm8 03:46] [ITE 5G2wGolpXxE 24:19]
[ITE WOX-WdXSOOc 47:44] [RES Timeline-Bench]

A line that points at something to be seen ("you can see", "this one", "here") sends the viewer's eyes to the thing
named within about a fifth of a second of the word, for a second or so [STUDY Tanenhaus et al. 1995; Allopenna et al.
1998]. A whip, a fast pan or shake there hides it, deliberate or not: put the thing named on screen, steady, under the
line (a cover, a steadier stretch of the take, a held frame). Check: the frames under each pointing line show the
thing named; a picture change's reply names a measured one under `self_check.picture` when it is there.

**FINE-7 Sequences for processes, single shots for mood.** Do: cover a process or journey with a chain (start,
development, completion; a size change between neighbours); use one illustrative shot for a mood or a place; a slow
gear may use one long shot where a fast one uses several; give a join's cover enough length not to read as a patch.
When: every b-roll run. Not: never three or more pretty shots in a row with no progression and no words carrying
them. Check: per run, the shot count, sizes and a completion shot (`letitedit_check_frames(shots=True)`).
[ITE jN3TIBIQlac 01:43] [ITE eXUH3Z5ZntE 04:05] [ITE KAO0n3C0kAg 27:07]

**FINE-8 Keep the face when it carries the line.** Do: stay on the speaker for credibility lines, jokes, emotion, a
call to action, the moment just after a revealing line, and at least the last line of each of their sections; cover
information-only stretches; with a compelling speaker, staying on them is right. When: every talk section. Not:
never bury an interviewee under b-roll for a whole piece. Check: key lines (plan, log) and each section's last line
are on camera. [AOTC GNIP] [ITE xZnHgyeZlsU 20:22]

## 5. Punch-ins and holds, under the repetition guard (craft L1, P4)
**FINE-9 Punch-ins with a reason, varied.** Do: use a scale change (the `zoom` effect with a focus point, or
`letitedit_fix` punch to follow a subject) for emphasis, a new idea, or to hide a join; vary or escalate them, keep the
strongest for the biggest moment, and log each in craft's device ledger. Upscale no more than about 1.25x on 1080p
sources [GEN]. When: talking heads and static shots. Not: not on every sentence; not in calm or premium pieces
unless the brief wants it; not the same punch pattern twice within about 30 s [GEN]. Check: punch count, spacing and
a reason for each, counted from the timeline (scene detection can miss punch-ins).
[ITE 4s7WdcyV1H4 10:54] [ITE art:why-repetition-in-editing-kills-impact] [OURS]

A Look that measures speaker punches (scale 1.08-1.12) or slow pushes (1 to 1.10 over 1.5-3 s) gets them on earned
moments, a few in the whole video and never on every sentence: `{op: fx, items: [{kind: zoom_punch, at, scale: 1.1},
{kind: push_in, at, len: 2.5, scale: 1.1}]}`. Both enlarge the speaker, so a person's words about their face ("full size,
uncovered") never forbid them; keep the face in frame and log each in the Look check as `punchins`.

A Look whose shots change by camera (a new angle or shot size at most cuts) still asks for that change when it
measures no punches or moves. On one locked-off take, a jump cut that keeps the same framing reads as one unbroken
shot, whatever the cut count says: alternate two or three static framings at the cuts (the full frame and a crop of
about 1.15-1.25x around the face, held for the whole shot), so most cuts also change the shot size. A crop held still
for a whole shot is a framing, not a punch or a move, and it enlarges the speaker, so a person's wish for "full size" allows it. Check:
count the cuts that change the framing on rendered frames either side, not only the cuts. [OURS]

**FINE-10 Hold when the frame is alive, and mark it.** Do: hold a shot while something is still happening in it (a
performance, behaviour, a realisation) or a moment needs to land, and mark it `hold:<reason>` over its range
(`letitedit_bin`; the gate's longest-shot check honours it); a very slow push of a few percent can finish a long
static shot. A slow opening or a few-cuts section the plan asks for that trips another pace check gets
`waive:<check>:<reason>` (letitedit-modes, section 4). When: reflective gears, reactions, payoffs. Not: a cool shot
alone never justifies a hold; never waive a stretch the plan didn't ask for. Check: every shot well past its
section's usual length has a `hold:` and something changing in it (frames 1-2 s apart); every waiver names its plan
section. [AOTC Hamnet] [AOTC Skeleton Crew] [ITE gwyneGrX9Jw 33:49]

## 6. Pace against the plan (craft P2, P3)
**FINE-11 Measure each section against its gear.** Do: render the cut (`letitedit_check_range` per section, or an
export) and measure shot lengths (`picture_change`), cuts and words per minute (`letitedit_measure`) and speech gaps
(`letitedit_words`); compare each section with its gear and feel, and change speed by moving several levers together
(cut rate, action in the shot, shot size, camera movement, dialogue spacing, music energy). With a `reference`,
measure it the same way and stay at or above about 0.8x its cut rate. Read `letitedit_timing(project,
view='trajectory')` (energy over time against each section's gear) and `view='map'` (cuts, motion, speech, beats in
one picture) and quote their numbers, not impressions. Pace is judged over 30 s-2 min: the viewer wants it to vary
across sections, so a short stretch being fast or slow is not a fault by itself [OURS]. When: the end of the fine cut, and after any
faster or slower note. Not: no fixed cuts-per-minute target without a reference; cut rate alone isn't pace. Check:
measured against planned gear per section in the journal; neighbours differ; no stretch stays in one gear with
nothing new for long (in one demo a second slow scene went flat about 30 s in); at most three measure-fix rounds.
[ITE CdyTIng0M8Q 09:17] [ITE bCVeyUFGxi8 10:51] [ITE ZcIVl01h14Y 03:30] [RES Timeline-Bench]

Write `fine_pass:` with measured pace per section against its gear, the joins checked, holds and waivers with
reasons, visible jump cuts and punch-ins, each b-roll item's job, and each repeat kept on purpose on a line that says
`kept on purpose` and quotes its words, with why. The journal saves `fine_pass.md`. Then add a separate
`letitedit_journal` note `stage:fine:done`; it is refused while the cut keeps a restart the review's own check finds
(the same check, so a restart cut here is never a review finding later) that `fine_pass.md` doesn't keep on purpose.
