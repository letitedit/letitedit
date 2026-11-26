# Story / vlog mode (with the DIY and repair playbook)

A person's own experience told as a change: a vlog, a day, a challenge, a trip diary, a build, a repair. Shared craft
is in letitedit-craft; this file says how a story sets it. Tags: `sources.md`.

## 1. What drives it
- **Name the driver per section from the footage.** Talk to camera or voice-over usually drives; hands-on stretches
  (a repair, a build, cooking) are led by the pictures; a quiet walk can be led by sound or music. Not: never treat a
  wordless stretch as dead because nobody speaks. Check: each section of the plan names its driver. [FEP drivers]
- **Log talk by text, judge it by voice and face;** log hands-on and wordless footage by what changes on screen;
  group retakes with `letitedit_find_takes` and keep the most natural one. Check: every select says why a viewer would
  care, not only what it shows. [ITE xiJmwycUxTY 09:05] [ITE eXUH3Z5ZntE 02:20]
- **Purpose line:** for a goal story, "[person] wants [goal] but [obstacle], so [action]; in the end [change]"; for a
  reflective vlog, the question it answers and the feeling it leaves. A personal or ironic reason, with a cost if it
  fails, makes viewers invest. Not: never force a goal onto a calm day; a question carries it. Check: by about 5 s
  (Short) or the end of the first scene (long) a viewer can say who wants what, or what is being asked. [JH 1:18]
  [ITE D2iBdbNej78 03:09]

## 2. Structure options
| Shape | Choose when | Avoid when | Tag |
|---|---|---|---|
| Goal story: want, obstacle, attempts, outcome, linked by but or therefore | there is a want and real turns | the turns would have to be made up | [JH 22:07] |
| Cold open, then back: the end moment first, then how it came about | the outcome is visual and the how is the interest | the hook would give the how away | [JH 16:18] |
| Chronological day or trip, carried by a goal or a question, with time cues; routine compressed into a short montage | order is the experience | it becomes a list with no question | [AOTC GNIP] [FEP 4d] |
| Question-led reflection: the person's own question, answered by the end | the person reflects on why | the answer comes in the first minute | [ITE xZnHgyeZlsU 04:34] |
| Themed: moments grouped by idea | many short moments around one subject | two themes say the same thing | [GEN] |

Check: the plan names the shape and why the footage supports it; the critic can retell it from the render. Declare a
chronological shape in the plan so order warnings don't flag it. The footage decides the turns (SKILL.md: never
invent what the footage lacks).

### DIY and repair playbook
For a fix, install, build or make told as a story. For a reference how-to, lead with tutorial-explainer and borrow
this hook.

| Beat | What it shows | Include | Into the next beat |
|---|---|---|---|
| Hook | the worst moment of the problem, or the result, plus the promise | always | "here's why" |
| Problem | the symptom on camera and why it matters | always | "so I opened it up" |
| Diagnosis | finding the cause: the "aha" | when filmed | "so the plan was" |
| Attempts and setbacks | a try that failed, with the real reaction | only if it happened | "but" / "two days later" |
| Fix | each step a viewer could copy: the action, why, the mistake to avoid (tutorial-explainer's step rules) | always | "therefore" |
| Result | the working state as proof: a reading, a before/after sound, a measurement | always; flag it if missing | "so the lesson" |
| Takeaway | one lesson, then end | always | (end) |

- **Name each turn on screen.** A muted viewer follows a repair from a few words per beat in the same place and
  style: the cause ("WHY: the wheel walks off the shaft"), each attempt ("FIX 1: crowbar it back on"), the setback
  with its real time ("2 DAYS LATER: the grind is back"), the real fix, the result. Point once at any part the
  viewer can't name (the set screw, the shaft) with `letitedit_annotate`; letitedit-graphics has the devices. Not:
  labels that only repeat the speech. Check: from the labels alone, someone retells the cause, the setback and the
  fix. [OURS]
  [JH 2:34] [ITE A2RYo1xNSA4 03:24]
- **Cut the side roads.** A discussion of another fix you didn't do (replacing the unit, a different part) is cut
  or kept to one line, unless it sets the stakes. Check: every beat moves this repair forward. [ITE FOJhAl9IyPg 09:30]
  [OURS]

- **One repair per video;** a second repair is a second video. Check: one problem and one result in the plan.
  [ITE FOJhAl9IyPg 09:30]
- **A setback only if it happened.** Without one, the stake is whether the fix works and holds: keep that doubt open
  until the result is shown working. Not: never reorder clips or lean on music to fake a failure. Check: each setback
  beat points to a source time where the thing really fails. [ITE D2iBdbNej78 08:43] [GEN]
- **Recording order is often causal:** keep it, and pull only the hook forward from the result. [JH 16:47]
- **Show the change:** the problem and the result answer one state question (does it spin? is it quiet?) in opposite
  ways, judged with `letitedit_ask_frames`, a measurement or a sound comparison. When: repair and before/after only.
  Check: both moments are in the cut and the answers differ. [GEN]
- **Keep the effort visible when compressing it:** light changing, a day card, jumps on a locked-off shot, a short
  progress montage. Not: when time doesn't matter to the story. Check: every big time skip shows a visible change or
  a cue. [FEP 4d] [ITE A2RYo1xNSA4 03:24]
- **Protect the proof sound** (the grind, the drip) in `brief.protected`, so music never covers it
  (`letitedit_soundtrack` ducks deep under protected ranges and measures them). Check: it is audible in the render.
  [GEN]
- **A steps-only reference cut** is a separate version (`letitedit_versions`), not this one. [GEN]
- A repair can follow hook, problem, attempt, a real setback if present, fix and demonstrated result. Never invent a setback to fill this pattern. [OURS]

## 3. Pace profile
Gears are letitedit-craft's (1 reflective to 5 urgent). The usual map, to break when the feel says so:

| Section | Usual gear | Break it when |
|---|---|---|
| Hook | 4-5 (urgent, result first) or 1-2 (reflective) | the feel picks the other template |
| Setup, problem | 3 | the problem is urgent (4) |
| Explaining a cause or a step | 2-3, slower at the complex point | the step is routine (compress it) |
| Attempts, progress | 3, rising to 4 just before the outcome | a calm build vlog (stay at 2-3) |
| Outcome, payoff | a held beat that lands, then out | a comic beat that wants a hard cut |

- **Vary the sections:** a challenge vlog may run gear 4 most of the way with breaths; a calm day can sit at 1-2 with
  one livelier section. Check: adjacent sections differ in gear, or the plan says why. [ITE bCVeyUFGxi8 02:31]
  [ITE pRpaqx_5jD8 05:12]
- **Talk to camera:** visible jump cuts are part of many creators' style; keep them motivated (energy, comedy, a
  ramble compressed) and break long runs with a cutaway or a size change. Not: in a calm or premium vlog. Check: the
  critic does not call the talk choppy. [ITE A2RYo1xNSA4 06:24]
- **Keep the person's breath:** remove dead search pauses and false starts; keep breaths at thought ends and their
  natural rhythm. Over-tight talk sounds unsure and can feel longer. Check: no 30 s of talk without a breath or a
  reset. [ITE xiJmwycUxTY 07:40] [AOTC GNIP]

## 4. Sound
- **The voice leads and music takes turns with it** (letitedit-sound): a bed under talk, the big musical moments in
  the gaps, a dry stretch when a strong moment carries itself. Check: no musical swell under a key line.
  [ITE 2aux2Y9-4m8 03:51] [AOTC Invite]
- **Keep actuality:** the sound of the work and the place, and short on-location lines, often say more than music.
  Check: natural sound sits under b-roll; no digital silence. [ITE KAO0n3C0kAg 11:33] [ITE urCAMKTsc6o 13:33]

## 5. Text and graphics
- **Chapters** in long vlogs: `chapter:<name>` markers (`letitedit_bin`) at section changes; on-screen chapter or day
  cards only where they help orientation (a multi-day build, a day in the life). Not: a card inside a building
  tension. Check: cards sit at section boundaries. [AOTC Invite] [FEP 4d]
- **Time cues** when elapsed time matters: dates, "two days later", a clock, always in order. [FEP 4d] [AOTC GNIP]
- **Steps and parts:** step labels, part names and pointers in the fix (`letitedit_annotate`, letitedit-graphics);
  prices, sizes and part numbers go in `brief.claims`. Captions: letitedit-captions. [GEN]

## 6. Shot choice and b-roll
- **Actions as chains:** preparation, action, completion, at changing sizes; a long job may need only seconds on
  screen. Not: one illustrative shot standing in for a whole process. Check: each process run has a start, a middle
  and a completion shot. [ITE eXUH3Z5ZntE 01:22] [ITE zXHKcITf3x8 17:07]
- **The face for feeling:** emotional, funny and credibility lines, and the reaction to the result, stay on the
  person. Check: the payoff reaction is on screen. [AOTC GNIP] [ITE D2iBdbNej78 04:49]
- **Personality counts:** keep a line or moment that shows who they are even if it adds no facts; what they chose to
  film shows what matters to them. [ITE WOX-WdXSOOc 26:25] [AOTC Porcelain War]

## 7. Openings and endings
- **Pick the opening for the feel:** the result or the worst moment with the promise, a stakes line, the question,
  mid-action, or a slow poetic start for a reflective vlog. Build it last, once the story is known. Not: "hi guys,
  today..." or a name-and-facts intro. Check: muted, the first 3 s (Short) or 10 s (long) carry the premise and the
  feel the plan names. [JH 16:47] [ITE esNXgCJh-yk 08:47] [AOTC GNIP] [JH 21:20]
- **Pay off the promise on screen, then stop.** Short: end within about a second of the payoff. Long: let the
  outcome land, give one takeaway or a bookend, let the music resolve, then end. Check: the hook's question is
  answered on screen near the end; a Short's tail after the payoff is about a second or less. [JH 0:42] [JH 7:07]
  [ITE xhJLcy8Kzl4 16:16] [ITE xZnHgyeZlsU 18:57]

## 8. Gate settings
| Check | Long | Short |
|---|---|---|
| `cuts_per_min`, `longest_static_s` | advisory (`hold:` waives a range) | advisory |
| `visual_change_first3s` | advisory; off for a poetic opening | advisory |
| `first_speech_s`, `silence_first3s_s` | advisory; off for a wordless cold open | advisory |
| `silent_share` | advisory | advisory |
| `frame0_not_black` | advisory (a fade-up is fine) | on |
| `tail_silence_s` | advisory | on |

Loudness: web and social -14 LUFS, true peak <= -1 dBTP [GEN]; broadcast -23 LUFS (EBU R128) [RES]. With a
reference, the pace rows are active against it. Critic questions: who wants what, what turned, what changed; is the
hook's promise paid on screen; does any turn look constructed?

## 9. Common failures and how to check
| Failure | Check | Tag |
|---|---|---|
| "And then" chronology with no question | read the beat connectors alone; three "and then" in a row means restructure | [JH 22:07] |
| A constructed turn or setback | every "but" maps to a source moment where it happens | [AOTC GNIP] |
| The promise not paid | the hook's question is answered on screen near the end | [JH 16:18] |
| A long setup before anything is at stake | the want or the problem is clear within the first scene | [AOTC MI] |
| One gear all the way | adjacent sections differ, or a reason is noted | [ITE bCVeyUFGxi8 10:51] |
| Retakes or a passage said twice | `letitedit_find_takes` groups resolved; no repeated passage in the render transcript | [ITE iAKUVUD7fG0 08:45] |
| Breathless talk | no 30 s of talk without a breath or a reset | [AOTC GNIP] |
| The result never shown working | the change check (repair) or an outcome shot is in the cut | [GEN] |

## 10. Evidence strength
- **Strong:** the story spine (a personal reason, stakes, but/therefore links, setup and payoff, ending soon after
  the payoff): Inside The Edit, Art of the Cut and Hoyos agree.
- **Medium:** repair specifics (hook from the result or the problem, one repair per video, real setbacks kept,
  visible effort): Hoyos plus Inside The Edit in part. Proof by measurement, protected proof sound and the change
  check are [GEN].
- **Thin:** vlog and talking-head rhythm (jump-cut density, punch-ins as rhythm): no vlog editor in the library. The
  old DIY beat shares had no source and are gone. Uncollected candidates are listed in `sources.md`.
