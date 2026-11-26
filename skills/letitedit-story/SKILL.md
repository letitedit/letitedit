---
name: letitedit-story
description: Plan a letitedit edit before the rough cut, for any kind of video - a purpose sentence (a logline only for goal stories), real stakes, sections that each have a driver, a gear and a feeling, an order by cause and curiosity (lists and chronology allowed), setups and payoffs, the open-loop ledger, a revelation map, an opening and an ending chosen for the mode, a place for every brief requirement, and a missing-footage and pickup report. Writes story_plan.json and pickups.md. Use after logging and before the rough cut, and update it after the first watch. The per-mode playbooks are in letitedit-modes.
metadata:
  version: 0.2.0
---

# Story plan

**Decision:** what the video is about, what the viewer should feel and know at the end, and in what order the
material gets them there. A provisional plan is enough to start the rough cut: editing is discovery, and the plan is
updated after the first watch (letitedit-rough). The person's brief and reference beat every default here.
[ITE ZcIVl01h14Y 06:41] [ITE FOJhAl9IyPg 11:44] [AOTC Porcelain War]

**Inputs:** `brief.json` (goal, `mode`, `driver`, `feel`, `reference`, deliverables with `target_s`, audience,
`desired_response`, `must_keep`, `claims`, `ending`, `narration`, `protected`), `log.json`, and the lead mode's
playbook in letitedit-modes (structure options, pace profile, openings, endings, failures for that kind of video).
Record a sub-playbook you follow in `playbook`: `repair` (story-vlog's DIY and repair playbook), `before_after`
(montage-transformation), or null. letitedit-craft owns the craft used here (S1-S6 spine, P1 and P3 gears, C1 and C6
scenes, T1-T3 tension). No `mode` in the brief: infer it from the log and the goal, say which, and ask only if two
modes would give clearly different cuts. Work order: draft sections and beats from the log, have letitedit-log rank
selects for them, then finish the plan. Evidence tags as in the skills README; documents in `references/sources.md`.
With an emotion graph (letitedit-log LOG-8), its turning points are candidates for the setback, the payoff, the
peaks and each section's `feel`, and its energy line shows whether the gears really vary; confirm each point on
the picture before planning on it.

## 1. Purpose and spine
For a learned Look with source_profile, read its sources.json before choosing coverage. Budget each base-picture
family separately: filmed own/licensed stock, screen recordings, generated pictures/video, rendered 3D/code,
or held/still pictures. Do not replace absent filmed coverage with generated scenes. Unknown provenance remains
a review gap. Keep caption/sticker/inset/sound overlays separate from the base family, and map reviewed event
durations and entrances to this story's beats; reference timestamps are not placements in the new film.

**STORY-1 Purpose sentence first.** Do: write "This video is about X; at the end the viewer should feel, know or do
Y" from the brief's goal, `feel` and `desired_response`, and a purpose line per section; plan nothing that serves
neither. When: every mode. Not: it may change after the first watch; having none is the failure. Check: `purpose`
and every section's `purpose` are filled; the critic restates the purpose from the render (letitedit-review).
[ITE FOJhAl9IyPg 02:49] [ITE xZnHgyeZlsU 01:05]

**STORY-2 A logline only for goal stories.** Do: when someone wants something (story/vlog, documentary, many shorts,
a tutorial or product framed as "I need X because Y"), add: [person] wants [goal] but [obstacle], so [action]; in
the end [change]. A personal reason, and irony, help. When: goal-driven footage. Not: montage, mood travel,
portraits, list tutorials: leave `logline` null rather than invent a goal. Check: every part of the logline points
at logged material. [JH 1:18] [ITE D2iBdbNej78 03:09]

**STORY-3 Real stakes, never invented ones.** Do: name what could be won or lost (small real stakes count: will it
hold, will she reply) and the one open question the viewer carries; heighten real complications the footage has.
With no real conflict, choose a structure that doesn't need one (a list, a process, a portrait, a mood, a
chronology) and tell the person. When: every plan. Not: never invent a setback, a deadline or a reveal the footage
doesn't have; manufactured drama turns formulaic. Check: `stakes` cites logged times. [ITE D2iBdbNej78 02:35]
[ITE 4s7WdcyV1H4 06:14] [AOTC GNIP]

**STORY-4 Name what changes and where it lives.** Do: say what is different at the end (knowledge, feeling, a
state, a relationship) and whether dialogue, pictures or music carry the progression. Only the `repair` and
`before_after` playbooks also need two source times whose pictures show different states, with one state question
(`change.start`, `change.end`, `change.question`; letitedit-rough's FM3). When: every plan. Not: never demand a
picture-state flip from an interview, an essay or a mood piece: progression can live almost entirely in the words.
Check: `change.what` and `change.lives_in` filled; picture states only with those playbooks.
[JH 22:17] [ITE eXUH3Z5ZntE 16:27] [ITE 5G2wGolpXxE 02:12]

## 2. Sections, each with a driver, a gear and a feeling
**STORY-5 Plan sections, each with its own engine.** Do: split the video into sections (a scene, a step, a place, a
topic); give each a purpose, a `driver` (dialogue | narration | music | visual | sound; the brief's by default), a
`gear` 1-5 (1 reflective, 2 observational, 3 progression, 4 tension, 5 urgency) and a `feel` (the brief's unless the
section needs another). Vary the gears. When: every plan; a short may have three to five sections. Not: two
neighbours in the same gear need a reason (one continuous push); don't repeat one gear pattern through the video.
Check: adjacent sections differ in gear or carry `same_gear_reason`. [ITE bCVeyUFGxi8 02:31]
[ITE bCVeyUFGxi8 16:38] [AOTC GNIP] [AOTC MI]

**STORY-6 Order by cause, curiosity and feeling.** Do: link consecutive beats by "but" or "therefore" (or so, turns
out, two days later); a visible list (three steps, five places) is a valid spine; chronology is right when it is
causal or the piece is observational, an event or a day; the emotional order may beat chronology. An "and then"
link is merged, cut, bridged or declared (`waive:and_then:<reason>`). Each section's `connector` says how it leads
into the next. When: every plan. Not: never keep recording order by default: if you do, give `order_reason`. Check:
undeclared "and then" = 0; the connectors read alone tell the story (the critic judges). [JH 22:07]
[ITE eXUH3Z5ZntE 03:25] [JH 15:51] [AOTC Porcelain War] [AOTC GNIP]

**STORY-7 Care before jeopardy.** Do: before the first risk or setback, give a beat of normal life or of what the
person loves, so the viewer cares. When: story, documentary, travel, event. Not: shorts and urgent openings may
state the stakes first and show the life after. Check: the first stakes beat follows a `normal life` or `want`
beat, or `investment_note` says why not. [AOTC Porcelain War] [AOTC Invite]

**STORY-8 Budget the length.** Do: give each section a `target_s`; together they make the deliverable's target
within about 10% [GEN]; the rough runs long and the fine cut removes. When a short and a long need different
sections, plan each under `deliverables` (the critic reads the one for each export). When: every plan. Not: never
pad a section or cut below what the story needs. Check: the sum is in range per deliverable. [JH 17:38] [AOTC MI]

For the strongest spoken line, record a `visual_decision` in its beat: the exact words, what carries them and why. On
talking-head or other visually thin footage that is a scene drawn in code unless the person's notes say not to or
Motion graphics is None (`letitedit-firstcut`, "Draw what no camera caught"). Name the world it shows (from the line's own images or
feeling, not a diagram of the sentence), whether the person stays visible through a cut-out, its entrance and exit,
and the sound or music cue. A missing real demonstration calls for a pickup and an honest illustration of the idea,
not a simulated interface. Further scenes need their own strong line; use the Custom Motion graphics, 3D, Courage
and "How much is going on?" settings as ceilings. A person-requested saved scene is a separate input; otherwise
write any new scene specifically for this video.

## 3. Loops, setups and revelations
**STORY-9 Loop ledger.** Do: every hook or question opens a loop (`loop:open:<id>`) and its answer closes it
(`loop:close:<id>`); open the main loop in the opening and close it in the last section; withhold the answer, never
the premise; long-form keeps at least one loop open until the payoff; loops inside a scene may close fast. A
documentary may end on a question by design: mark that loop `open_by_design` with the reason. When: every plan.
Not: never tease what the video never pays; never leave a loop open by accident. Check: every loop has a later
close or `open_by_design`. [JH 16:47] [ITE D2iBdbNej78 04:16] [ITE esNXgCJh-yk 05:28] [AOTC Porcelain War]

**STORY-10 Setups and payoffs.** Do: every payoff (a reveal, a result, a callback, a joke's return) has an earlier
seed; every highlighted setup pays off or is cut; seed people and objects early and clearly. When: every plan. Not:
a deliberate misdirect needs a note. Check: `setups` pairs each payoff with a seed; orphans = 0 (rough's FM11 blocks
on them). [AOTC GNIP] [ITE hwecWg2IR18 06:08]

**STORY-11 Revelation map.** Do: list each key revelation, place it on purpose, and note what the viewer must
already know and where they learn it; drip clues from least to most revealing; meet the expectation you set, then
twist it when the footage really has a twist; keep the line from setup to punchline clean; the strongest payoff goes
last. When: any piece with more than one reveal. Not: shorts withhold the outcome, never the premise. Check: each
reveal's `needs` appear earlier in the plan. [ITE ZcIVl01h14Y 09:47] [ITE gwyneGrX9Jw 22:56] [JH 17:19]
[AOTC Invite] [ITE iAKUVUD7fG0 11:18]

## 4. Opening and ending, chosen for the mode
**STORY-12 Opening: the template first, then candidates.** Do: choose from the mode playbook: urgent (time, place
and stakes in one breath; tight and fast), poetic or withholding (a reflective line or image, longer shots, sound
layered in, the reveal later), a literal cold open (show what is said while viewers learn the film), the short-form
hook (a visual premise understood muted plus a one- or two-line foreshadow by about 3 s; letitedit-shorts), or a
mode's own (a brand or product frame first, the person's own question, mid-action). Write two to four candidates
from logged material; the opening is cut last (letitedit-firstcut), except on a short from a talk with a scene timed to the words, where it's chosen here. When: every plan. Not: never a name-and-facts
dump or "in this video"; never a withholding opening for a feed short without a muted test. Check:
`opening.template` and its candidates name logged times. On a short, also `opening.first_frame`: the moment frame 0
shows and why. Choose it from full-size frames, not the log's thumbnails: the chosen line's own picture at 0 and 1 s
against the tightest steady shot of the subject anywhere in the footage. When the line's picture is wide or cluttered
and the subject small in it, frame 0 is that tight shot, laid as a muted cover over the same words (letitedit-shorts
2.1). [ITE esNXgCJh-yk 08:47] [AOTC GNIP] [JH 2:34] [JH 19:56] [OURS]

**STORY-13 Ending: write the last line first.** Do: choose the ending from the mode: a short ends right after the
payoff (or loops into its start); a long-form section resolves on a short line, a bookend image or a resolving
musical phrase; a long talk (interview, podcast, conversation) ends on a closing beat, its goodbye kept whole
(letitedit-modes, interview and podcast, section 7); a documentary may end as an open invitation; the brief's `ending` always wins. **One ending:** once the
peak or the last event lands (a finish, a landing, a goodbye), the video ends within a closing image or phrase;
an aftermath is that closing image, not a new section that starts again on new subjects, which plays as a second
ending. A bookend is cut straight after the last event, not after a coda. A Look with a measured ending follows its
shape (letitedit-learned-look). Name the last line or
shot before planning the middle. When: every plan. Not: no outro after a short's payoff; no fade on a mid-phrase
track. The last line must sound finished: a thought that lands, not one the source carries straight on from ("...than this" and then "and"); if the cut line runs on in the source, pick another ending or find a take where it lands. Check: `ending` names a logged time; with a brief `ending`, it is the last line (the gate looks for it in the
last 15%). [JH 0:42] [JH 23:54] [ITE iAKUVUD7fG0 11:18] [ITE xhJLcy8Kzl4 16:00] [AOTC Porcelain War]

**STORY-14 A reason to move on at every boundary.** Do: name each section's `jump_off` (a pictorial bridge, a verbal
hand-off, a question answered next, tension released next, energy set up) and whether the next section starts in
contrast; letitedit-craft C5 owns the forms. When: every boundary. Not: the link is a reason, not an effect; the
default device is a straight cut. Check: every section but the last has a `jump_off`. [ITE hwecWg2IR18 01:02]
[ITE esNXgCJh-yk 12:36]

## 5. Requirements and missing footage
**STORY-15 Place every requirement.** Do: put each `must_keep` and `required_lines` entry, each claim and the
`ending` in a section; keep `protected` ranges whole wherever they are used; plan nothing that needs `must_avoid`
material; follow `narration` (no voiceover bridge when it is "none"). When: every plan. Not: never leave a
requirement for a later stage. Check: every requirement in `log.json` has a section, or MISSING with a bridge. [GEN]

**STORY-16 Bridge a missing beat honestly.** Do, in this order: the person's own line that hands off; a short text
card that says why the next shot matters (letitedit-graphics); a voiceover only when `narration` allows it, with no
new claims; a wordless montage, a time card or a dissolve where time passes. When: a needed beat has no material.
Not: never an almost-right clip; never invent what happened. Check: each MISSING beat has a `bridge`, or its section
is cut. [ITE hwecWg2IR18 04:16] [FEP 4d] [ITE FOJhAl9IyPg 08:07]

**STORY-17 Missing-footage and pickup report.** Do: list what the edit lacks and could still get: gaps in a scene's
coverage chain (place, person, preparation, the event, reactions, completion, aftermath, exit), a proof or reveal
shot for each key claim, room tone, entry and exit shots, a line that links two threads, shots logged as unusable.
Per item: section, what, why it matters, the edit it blocks, how to shoot it (size and angle; an action that
completes in the shot; a 5-8 s hold; clean start and end frames on any move; two sizes for a process; the scene's
look; 30 s of room tone), and the bridge used until then. Write it into `missing` and to `pickups.md` next to the
project (or a journal note `pickups:`): the gate never rewrites them. When: every plan; update after the rough watch.
Not: list only what would change the video; never hold the first cut back for it. Check: every item names the edit
it blocks.
[ITE WlS5f8Plyl0 12:58] [ITE zXHKcITf3x8 07:07] [AOTC GNIP] [AOTC MI] [OURS]

## Output and checks
`story_plan.json` (the critic reads `purpose`, `logline`, `stakes`, `open_question`, `feel`, `ending` and each
section's `purpose`, `feel`, `gear`, `driver` and `connector`):
`{"purpose", "logline", "mode", "playbook", "feel", "stakes", "open_question", "order_reason", "investment_note",
"change": {"what", "lives_in", "start", "end", "question"}, "opening": {"template", "candidates": []},
"ending": "<the last line or shot, in words>", "ending_at": "<file@t>",
"sections": [{"id", "label", "purpose", "driver", "gear", "feel", "target_s", "connector", "jump_off",
"same_gear_reason"}], "beats": [{"id", "label", "section", "selects", "target_s", "connector", "loops",
"visual_decision": {"line", "device", "reason", "scene_candidate"}}],
"loops": [{"id", "question", "opens", "closes", "open_by_design"}], "setups": [{"id", "seed", "payoff"}],
"reveals": [{"id", "what", "at", "needs"}], "requirements": {"<requirement>": "<section> | MISSING"},
"missing": [{"section", "what", "why", "blocks", "shoot", "bridge"}], "waivers": [],
"deliverables": {"long": {"sections", "beats"}, "short": {"sections", "beats"}}}` (the last only when they differ)

`pickups.md`: the `missing` list in plain words for the person. One `beat:<id>:<label>` marker per beat once it is
on a timeline. In the app's chat panel, keep the plan and the pickups as journal notes starting `story_plan:` and
`pickups:`. When the start message says code writes the beat markers, give each beat a short `label` and its `selects`
(the groups of `selects.json` it plays): code places the marker from them, and the loops' markers from `opens` and
`closes`. Write both notes in one `letitedit_journal` call with `entries`.

Checks: purpose filled; logline null or grounded; undeclared "and then" = 0; adjacent gears differ or are explained;
section targets within about 10% of each deliverable's target; every loop closed or `open_by_design`; every payoff
seeded; every reveal's needs earlier; opening and ending named; every requirement placed, or MISSING with a bridge;
`pickups.md` written. Mark the stage done: `letitedit_journal` note `stage:story:done`.
