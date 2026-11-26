# Tutorial / explainer mode (with screen recordings)

Teaching someone to do or understand something: a how-to, a hands-on tutorial, a concept explainer, a screen
recording. It works when the viewer can follow and copy it. Shared craft is in letitedit-craft. Tags: `sources.md`.
The library has no tutorial or screen-recording lesson, so most rules here are general practice [GEN] or carried over
from documentary pacing: defaults to test, not findings.

## 1. What drives it
- **Narration drives; the process is the proof.** A voice-over or talk to camera carries the order; the hands or the
  screen show each step happen. Log the spoken steps by text and the visual steps by picture (where each action
  starts and completes). Not: a silent demo set to music, which is montage-transformation or a captioned silent
  tutorial. Check: every step has a spoken or written start and a visible completion. [FEP drivers] [GEN]
- **Takes:** tutorials collect retakes. Group them with `letitedit_find_takes`, choose by clarity and energy rather than
  polish, and never mix takes that state different values (it flags differences in numbers, names and negation).
  Check: no step repeats in the render and every value matches the take used. [ITE xiJmwycUxTY 09:05]
  [ITE iAKUVUD7fG0 08:45]
- **Purpose line:** "After this, the viewer can [do X]" or "understands why [Y]". Check: the result it names is shown
  working by the end. [GEN]

## 2. Structure options
| Shape | Choose when | Avoid when | Tag |
|---|---|---|---|
| Numbered steps: the count promised up front, progress shown | a procedure | steps that aren't really separate | [JH 15:51] |
| Problem, then the fix | the viewer arrives with a problem | the problem is obvious from the title | [JH 22:07] |
| Result first, then how | the result is visual and motivating | it spoils a reveal the viewer wants | [JH 16:18] |
| Concept explainer: a question, one idea at a time, a recap | explaining why or how something works | ideas stacked with no space | [ITE pRpaqx_5jD8 05:12] |
| Reference how-to: steps only, with chapters | a lookup video people scrub through | viewers who need a reason first | [GEN] |

Check: the plan names the shape and its step list matches the steps in the render.
- **The list is the structure, not a fault:** state the count early, show progress, deliver every promised item.
  Not: padding a list to reach a round number. Check: promised count = steps shown = step labels. [JH 15:51]
- **The viewer's order:** the order they will do it in, even if it was filmed otherwise; tools, parts and files shown
  before step one. Check: no step uses something not yet shown. [GEN]

## 3. Pace profile
- **Gears 2-3 for steps, slower at the hard one:** split dense explanation into single ideas with a beat of picture
  or music after each; restructure rather than dumb down. Not: steps the viewer already understands (compress them).
  Check: no line tagged complex is followed by new speech within about a second; the critic can follow every step at
  normal speed. [ITE pRpaqx_5jD8 05:12] [RES]
- **The hook and the recap can run faster** (gear 4); the steps stay at a speed you can copy. [GEN]
- **Hold while the viewer must watch:** stay on an action until it completes; no cutaway, b-roll or punch-out during a
  step being copied. Check: each step's action is visible from start to completion; `hold:step <n>` markers over the
  long ones. [GEN]
- **Compress waits:** cut loading bars, renders, typing and searching; when the wait matters ("this takes ten
  minutes"), show it as a jump with a cue (a time card, a labelled speed-up, a visible change on screen). Check: no
  stretch over about 5 s where nothing changes and nothing is said, unless held on purpose. [FEP 4d]
  [ITE A2RYo1xNSA4 03:24] [GEN]
- **A shorter cut can feel longer** when viewers must work to keep up: give the hard part room. [AOTC GNIP]

## 4. Sound
- **The voice first:** clear, level narration (letitedit-sound for cleanup). Check: every step's words are
  intelligible over everything else. [GEN]
- **Keep music out of the way of instruction:** none, or a low bed without melody, under dense steps; bring it up in
  the intro, between chapters and on the result. In multimedia-learning studies, background music under narrated
  lessons reduced learning. Check: no musical change under a step's instruction. [RES] [ITE 2aux2Y9-4m8 03:51]
- **Real sounds as feedback:** a part clicking home, a meter's beep, an app's chime can confirm a step; keep them
  audible. [GEN]

## 5. Text and graphics
- **Step labels match the words:** "Step 2 of 5: export settings" appears as the narration starts that step, numbered
  as promised and worded like its chapter. Check: label count = spoken steps; each label lands within about a second
  of its spoken start. [JH 15:51] [RES]
- **Point at the target:** a ring, arrow or box on the button, field or part as it is used, or a magnified inset, with
  `letitedit_annotate` (it can follow a moving target and keeps its label clear of captions); one pointer at a time.
  Check: annotate's rendered-position check passes; no two pointers overlap in time. [RES] [GEN]
- **Exact values:** settings, commands, menu names, part numbers and prices copied from the recording, never from
  memory, and listed in `brief.claims` so the gate checks their spelling. Check: the claims check passes; on-screen
  text matches the recorded screen. [GEN]
- **Plain words:** define a term where it is first used; keep on-screen text short and simple. [JH 3:55]
- **Captions clear of the screen being taught:** tell `letitedit_caption_fit` which area must stay visible
  (letitedit-captions). [GEN]
- **Chapters** in long tutorials: `chapter:<name>` markers (`letitedit_bin`) at each step group, named like the labels.
  YouTube needs the first at 0:00, at least three, each at least 10 s long. Check: markers in order and spaced to that
  rule. [YT]
- **Show what the camera can't:** a diagram, a labelled freeze-frame, or a 3D view with callouts (`letitedit_3d`, when a
  model exists) for insides and principles (letitedit-graphics). [AOTC Porcelain War] [GEN]

## 6. Shot choice and b-roll
### Screen recordings
- **Readable at the delivered size.** When text the viewer must read is small at the deliverable's width (a desktop
  inside a phone frame almost always is), punch in on the active area for that step, after a brief whole-screen view
  to orient. Check: `letitedit_check_frames` at the deliverable width on every step; the critic reads the key text from
  the frames; anything unreadable gets a zoom. [GEN]
- **Zoom with intent:** orient wide, move in before the action, hold during it, move out when the area changes; one
  smooth move per change of area. Not: a zoom on every click, or a move during typing. Check: zoom moves per minute in
  the journal; the critic flags lost orientation or motion sickness. [GEN] [ITE 4s7WdcyV1H4 05:32]
- **A visible cursor and click:** if the pointer is tiny at the delivered size, ring the clicks (`letitedit_annotate`).
  [GEN]
- **Proof shots:** after a key step and at the end, show the result working (the setting applied, the file playing,
  the reading). Check: each promised result has a frame where it is visible. [ITE gwyneGrX9Jw 26:53] [GEN]
- **Private details off screen:** blur or crop email addresses, names, keys and tokens, notifications, open tabs and
  personal file paths. Check: look for them in frames (`letitedit_ask_frames`, `letitedit_look`) and ask the critic to
  look too; anything found is covered before export. [GEN]

### Hands-on and explainers
- **Orient, then close in:** a wide of where we are and what is being worked on, then a close-up or point-of-view shot
  of the copyable action, then the result; show each tool or part before it is used. Not: mirrored shots that swap
  left and right. Check: each step has an orienting shot and a close action shot. [ITE zXHKcITf3x8 17:07] [GEN]
- **Cut to the demonstration on the hand-off:** when the speaker says "let me show you" or names the step, the picture
  goes there. Check: the demo starts within the hand-off phrase. [ITE hwecWg2IR18 03:59]
- **The face for the why and the warnings:** safety notes and the common mistake land better on the person.
  [AOTC GNIP] [GEN]

## 7. Openings and endings
- **Open on the result or the problem, then the promise and the count** ("in three steps"): within about 3 s in a
  Short, within the first scene of a long video; no channel intro, no "in this video". Check: muted, the opening
  shows what the viewer will be able to do. [JH 19:20] [JH 21:20] [JH 15:51]
- **End on the working result and a one-line recap;** a reference how-to may end on a summary card of the steps.
  Short: end right after the result. Check: the last shot shows the result working; a Short's tail is about a second
  or less. [JH 0:42] [GEN]

## 8. Gate settings
| Check | Long | Short |
|---|---|---|
| `cuts_per_min` | advisory (zooms and pointers may not count as cuts) | advisory |
| `longest_static_s` | advisory; `hold:step <n>` over steps that need time | advisory |
| `visual_change_first3s`, `first_speech_s`, `silence_first3s_s`, `silent_share` | advisory | advisory |
| `frame0_not_black` | advisory | on |
| `tail_silence_s` | advisory | on |

Loudness: web -14 LUFS, true peak <= -1 dBTP [GEN]. Critic questions: can each step be followed and copied at normal
speed; is every on-screen value readable at this size and the same as said; is anything private visible; does the
promised count match the steps shown?

## 9. Common failures and how to check
| Failure | Check | Tag |
|---|---|---|
| Screen text unreadable at the delivered size | frames at the deliverable width; the critic reads the values | [GEN] |
| A step missing, merged or out of order | promised count = labels = spoken steps | [JH 15:51] |
| A value on screen differs from what is said | the claims check; the critic compares frames and words | [GEN] |
| Cutaway or b-roll over a step being copied | each step visible from start to completion | [GEN] |
| The hard step rushed | space after complex lines; the critic follows it | [ITE pRpaqx_5jD8 05:12] |
| Zoom thrash | zoom moves per minute; critic note | [ITE 4s7WdcyV1H4 05:32] |
| Private details visible | a frame scan for addresses, keys, notifications | [GEN] |
| No proof that it works | a result frame per promised outcome | [ITE gwyneGrX9Jw 26:53] |
| Jargon left undefined | each term defined where first used | [JH 3:55] |

## 10. Evidence strength
Thin. Nothing in the library teaches tutorials, explainers or screen recordings, and nothing covers captions.
Sourced and transferable: slow down and separate complex ideas (Inside The Edit), a visible list as the mechanism and
plain words (Hoyos), cut to the demo on the verbal hand-off (Inside The Edit), compressed time with visible cues (a
Film Editing Pro note, Inside The Edit). Signalling, one idea at a time and keeping music from under instruction draw
on multimedia-learning research outside the library [RES]. Zooms, pointers, exact values, privacy and chapters (apart
from YouTube's chapter rule [YT]) are [GEN]. Dropped: the list waiver, "faster delivery holds attention" and a framing
change every 20-40 s (contradicted or unsupported).
