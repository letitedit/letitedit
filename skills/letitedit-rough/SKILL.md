---
name: letitedit-rough
description: Build the letitedit rough cut from story_plan.json in the order each section's driver dictates - dialogue first only when dialogue drives, the music track first when music drives, picture chains first when visuals drive - with every brief requirement already placed and the cut running about 110-130% of the target; render and watch it early, try one alternative structure, then run the mode-aware story QA (FM1-FM12, the picture-state check only for repair and before/after) and a retell or muted test. Use after the story plan exists.
metadata:
  version: 0.2.0
---

# Rough cut and story QA

**Decision:** does the plan work as a film? Build it whole and long, watch it in context, restructure on evidence,
and catch the story failures before any polishing.

**Inputs:** `story_plan.json` (sections with driver, gear and feel; beats, loops, setups, reveals, opening, ending,
requirements, `playbook`), `selects.json`, `log.json`, `brief.json` (`mode`, `driver`, `reference`, `must_keep`,
`must_avoid`, `claims`, `ending`, `protected`, `narration`), the lead mode's playbook (letitedit-modes) and
letitedit-craft (C2-C4 scenes, D1-D2 dialogue). Load letitedit-sound when a section is music- or sound-driven.
Evidence tags as in the skills README; documents in `references/sources.md`.

## 1. Contested beats first
**ROUGH-1 String out what competes.** Do: for beats marked `contested`, put the candidates side by side on scratch
copies with `letitedit_try` (frames, words and one MP4 of them back to back) and pick by watching and listening. When:
beats with two or more close selects. Not: skip beats with one clear select; short targets usually have few. Check:
a `pick:<beat>:<reason>` journal note per contested beat. [AOTC Dune] [AOTC Skeleton Crew] [ITE xiJmwycUxTY 11:04]

## 2. Build in the driver's order
**ROUGH-2 Build each section on what drives it.** Do, by the section's `driver`:
- dialogue: pull the lines, cut them down (errors, repeats, tangents), put them in story order, and leave about 1 s
  between sync islands so the structure shows; b-roll and music only once the words stop changing (craft D1-D2);
- narration: the voice track first (the person's own recording, or an approved voice when `narration` allows it),
  then picture to it;
- music: choose and arrange the track first (letitedit-sound; `letitedit_soundtrack` arranges a song on its bars
  around hits and protected sound, `letitedit_fit_music` cuts one to a length or to hit points), mark its sections and
  hits, then cut picture to them;
- visual (an action, a process, a place): picture chains first (start, development, completion; sizes that vary),
  then the sound under them;
- sound: lay the sound map first (natural sound, a rhythm, a countdown), then picture to it.

With a measured Look, a section's `shot_s` target in story_plan.json (from the Look check's `pace_targets`:
letitedit-learned-look) is what its picture runs at from the first build: a music- or picture-led section cut at the
reference's band of shot lengths, varied within it, with no more long holds than the reference has, so the middle
doesn't settle into longer, even shots that a later pass has to break up. A dialogue-led section keeps its words' own
rate: its cut points stay on the phrases.
With a measured Look, cut a picture-led body to the reference's own lengths by code, `{op: fx, pace: true}`, right after
the selects are placed (letitedit-learned-look, "Pace built in, by code").

When: every section; drivers may differ by section. Not: never cut a music- or picture-led section dialogue-first;
never lay b-roll on a talk-led section whose words are still changing. Check: the journal shows the driver's layer
built first in each section. [FEP drivers] [ITE iAKUVUD7fG0 01:21] [ITE urCAMKTsc6o 13:01] [AOTC Porcelain War]
[AOTC Invite] [ITE xZnHgyeZlsU 08:16]

**ROUGH-3 What waits.** Do: graphics and captions wait for the finish; music waits only in dialogue-led sections
where it isn't structural (a temp track that helps judge rhythm is fine: label it `temp`). Play key sections once
without music to see whether they stand. When: every rough. Not: a music-led montage or a music-driven opening
never waits for its track. Check: no captions or graphics yet; temp music labelled. [AOTC MI] [AOTC Invite] [GEN]

**ROUGH-4 One planned edit per section, checked before it lands.** Do: write each section as one
`letitedit_timeline_apply` (`code` when in and out points need computing; no `dry_run` first: the apply checks every
change before anything lands and is one undo step), then put
`beat:<id>:<label>` markers at beat starts and the plan's `loop:` markers at their times (`letitedit_bin`). When:
every build. Not: avoid a stream of small patch applies: plan, then build. Check: every plan beat maps to a marker.
[OURS] [GEN]
- **Bookkeeping in code.** When the start message says code writes the `beat:` and `loop:` markers, place none: code
  puts each beat's marker at the first clip that plays its selects (`story_plan.json`, `selects.json`) and each loop's
  at its beats, and they follow their clips through every apply. The check stays: the hand-over lists any beat no clip
  plays.

**ROUGH-5 Place the requirements now.** Do: put every `must_keep` and `required_lines` entry, each claim and the
`ending` where the plan says; keep `protected` ranges whole; use nothing from `must_avoid`; no voiceover when
`narration` is "none". When: the first build. Not: never leave a requirement for the fine cut. Check: FM6 below.
[GEN]

**ROUGH-6 Run long, keep the assembly.** Do: aim at about 110-130% of the target [GEN]: the fine cut should remove,
not find. Keep this full version (`letitedit_project_new` with `copy_of`, named `<project> assembly`) so cut material
can come back on request. When: every rough. Not: a short from one clip may land near its target: don't pad. Check:
length against target in range; the assembly copy exists. [AOTC Invite] [AOTC MI] [ITE WOX-WdXSOOc 51:32]

## 3. Render early, watch in context
**ROUGH-7 Render and watch by about a third of the budget.** Do: render the whole rough as a preview
(`letitedit_export(project, preview=True)`: the export engine draws it smaller with a fast encode and the final's sound,
and after a change only the changed stretches render again; never a full-size export to watch a rough), or a part of it
with `letitedit_check_range` (low width, with sound); `letitedit_check_frames(shots=True)`; `letitedit_overview` for
structure. Watch it as a
first-time viewer: what is at stake, what just happened, who is this, does each section start, develop and end.
Note every bump, confusion or "why are we still here" with its time. Watch picture-led sections muted; for talk
sections use the render's words, `letitedit_look` loudness and word lanes and `letitedit_hear` as listening proxies, and
list what you couldn't judge (code can't hear). Log `render:<n>:<budget %>` in `letitedit_journal`. When: every edit.
Not: never wait for the fine cut to watch. Check: a `render:` entry by about 35% of the budget [GEN]; a bump list.
[AOTC GNIP] [AOTC Hamnet] [AOTC Dune] [RES Timeline-Bench]

**ROUGH-8 Restructure once, on evidence.** Do: after the first watch, write what you would move, drop or swap and
why; try at least one alternative for the opening or the weakest section with `letitedit_try`, keep the better, and
update `story_plan.json` (and the pickups). When: every rough. Not: if the alternative loses, keep the original and
say why. Check: an `alt:` journal note with both versions and the choice. [AOTC MI] [AOTC Dune]
[ITE ZcIVl01h14Y 06:41]

## 4. Story QA (on the rendered rough; log the table in the journal)
A block is fixed before the fine cut; one that can't be fixed needs the person's OK, recorded in the journal.

| FM | Failure | Check | Severity | Source |
|---|---|---|---|---|
| FM1 | Order not chosen | the cut plays in recording order end to end (`letitedit_overview` recording times) and the plan has no `order_reason` | warn | [AOTC GNIP] |
| FM2 | "And then" links | undeclared "and then" connectors in the plan | warn | [JH 22:07] |
| FM3 | No change | `repair` or `before_after` playbook: the state question gets the same answer at `change.start` and `change.end` (`letitedit_ask_frames`, confirmed on the frames). Other modes: name what changes (knowledge, feeling, state) and where; the critic judges it | block for those two playbooks; else warn | [ITE eXUH3Z5ZntE 16:27] |
| FM4 | Unpaid loop | a `loop:open` with no later close that isn't `open_by_design` | block | [JH 17:19] [AOTC Porcelain War] |
| FM5 | Promise not paid | say the opening's promise in one line; it isn't delivered on screen | warn | [JH 0:42] |
| FM6 | Requirement broken | a must_keep entry, a claim or the ending missing; must_avoid material used; a protected range cut; the narration rule broken | block (a missing required line warns unless the brief says must) | [GEN] |
| FM7 | Junk or retakes left | a span over a logged junk span; a line said twice that isn't a declared callback | warn | [ITE iAKUVUD7fG0 08:45] [RES Timeline-Bench] |
| FM8 | Unplanned stretch | a wordless, static or silent stretch the section's gear and feel didn't ask for, with no `hold:`; or 30 s or more of unbroken speech with no breath or reset in a talk-led section | warn | [ITE gwyneGrX9Jw 25:15] [AOTC GNIP] [GEN] |
| FM9 | Cut inside a word | a word straddling a cut by more than 20 ms (`letitedit_words(project=..., per_word=True)`) | warn | [GEN] |
| FM10 | Tail | a short: more than about 1 s after the payoff; long-form: no resolving beat, or dead time after it | warn | [JH 7:07] [ITE xhJLcy8Kzl4 16:00] |
| FM11 | Payoff without setup | a reveal or callback with no earlier seed in `setups` | block | [AOTC GNIP] |
| FM12 | Never watched | no `render:` journal entry before the export | block | [AOTC Hamnet] |

Also run the lead mode's own failure checks (letitedit-modes, section 9 of its file) on this render.

**ROUGH-9 Retell or muted test.** Do: in narrative modes, give a fresh agent only the rough render's words
(`letitedit_words(project=...)`) and 6-8 frames (`letitedit_check_frames(count=8)`) and ask for the purpose, the question
or goal, and what changed; in wordless or music-led modes, ask it to describe the feeling and what happens from muted
frames and the first 10 s. In the app's chat (no sub-agent), run `letitedit_review_bundle` with the critic on the
rough render, or say the test wasn't run. When: before the fine cut. Not: a retell that only repeats the narration
proves little, and a pass doesn't prove the story works. Check: the retell matches `purpose` and `change.what`; if not, restructure. [GEN]
[ITE esNXgCJh-yk 14:08] [OURS]

Mark the stage done: `letitedit_journal` note `stage:rough:done` with the QA table, the bump list and the alternative
tried.
