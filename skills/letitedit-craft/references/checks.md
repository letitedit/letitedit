# Running the craft checks

How to do each *Check:* in SKILL.md with the `letitedit` tools, what to write down, and what to do when a newer tool
isn't installed yet. Thresholds marked [GEN] are our starting points, not sourced norms: tune them on the person's
footage and their `reference`. Demo numbers from the sources are in `examples.md` (calibration table).

The critic in `letitedit_review_bundle` sees contact pages, frames, the transcript and measurements; it cannot hear.
So the listening checks (section 4) are yours: do them, or log what was not heard so the review can say so.

## 1. The gear list (P1, P2, P3, P4)
For each section of the plan, write its stated feeling, its gear (1 reflective, 2 observational, 3 progression,
4 tension, 5 urgency) and what the render measures:
- cut rate and shot lengths: `letitedit_measure` on the export, or the finished `letitedit_export_job` (picture_change:
  shot lengths and where the picture stays nearly still);
- words per minute and the gaps between lines: `letitedit_measure`; `letitedit_words` on the project, per word;
- camera movement and action in frame: frames per shot (`letitedit_check_frames`), the footage facts in
  `letitedit_footage` (shake, whips); shot scale mix from the same frames;
- music energy and coverage: `letitedit_check_audio` (music against voice), `letitedit_overview` (music lane).

No tool computes a gear. ITE's five gears are a teaching map (ITE bCVeyUFGxi8 02:31) and Walker describes pace as
what drives you underneath, not cut speed (AOTC dune L128), so the gear is your judgment from those numbers. A rough
guide to the levers per gear [GEN, built from the levers in ITE CdyTIng0M8Q 09:17 and KAO0n3C0kAg 26:29]:

| Gear | Shots | Camera and scale | Space around lines | Music |
|---|---|---|---|---|
| 1 reflective | few, long, often static | locked-off, wides or a held close-up | wide gaps, silences | sparse, ambient, or none |
| 2 observational | moderate | steady, mixed sizes | natural, some breaths | light bed, gaps |
| 3 progression | steady flow, chains | some movement, varied sizes | moderate | pulse, phrases in gaps |
| 4 tension | shorter, inserts creeping in | closer, held stares | gaps that linger | building, or cut out |
| 5 urgency | many, short | handheld, whips, close | speech starts at once | percussive, driving |

Flags: two neighbours with the same gear; a repeating cycle (slow-medium-fast, again); a section whose levers
contradict its feeling (a "calm" section with sub-2 s shots and whips; an "urgent" one of long static wides); a sharp
change of pace inside a section with no event (a reveal, arrival, decision) within a couple of seconds (ITE
CdyTIng0M8Q 06:12). A gear held on purpose gets a note saying so.

## 2. The muted 10-second test (C3)
1. Render the first 10 s with sound (`letitedit_check_range`) and watch it.
2. Look at the same 10 s as frames, about one per second, without sound (`letitedit_check_frames`).
3. Write: the feeling it starts in your words; whether a stranger would keep watching; whether the tone is clear; how
   many separate facts are stated; whether words, pictures and sound agree; and how that compares with the brief's
   `feel` and `tone`.
4. Fail and rebuild when: the feeling doesn't match the brief; the opening is a greeting, a self-introduction or a
   stack of facts (ITE gwyneGrX9Jw 02:20); it starts mid-sentence; or, for a Short, frame 0 can't be understood muted
   (letitedit-shorts).
Do it again at the start of each major section. Source: ITE esNXgCJh-yk 14:08.

## 3. The first-time-viewer pass (S1, S3, C1, T2)
Watch (or page through) the whole render as if new to it, or put these questions to the critic:
- What is this about, in one sentence? (S1; compare with the brief's `goal`.)
- What is at stake, and for whom? By when did you know? (S3.)
- After each section: what just happened, and what did you feel? (C1; dilution shows up as "I didn't feel it", not
  as confusion: ITE FOJhAl9IyPg 09:49.)
- Who is this, where and when are we? (T2.)
Log a "bump" with its time whenever you are confused rather than intrigued, wonder why the video is still on this beat,
or lose track of time or place. When a stretch feels slow, look at the setup before it first (AOTC invite L310-314).
Sources: AOTC hamnet L56-58 (watching cold as a first-time viewer), AOTC mi L34-40, L244-246.

## 4. The listening pass (D4)
For every sentence built from more than one source span, and every reordered pair of islands:
1. Render the range with sound (`letitedit_check_range`) and listen without watching.
2. Listen for: one continuous thought; the same emotional temperature on both sides; an outgoing fragment that ends
   on a finished, falling contour while the sentence carries on (a fail); a breath where one thought ends; room tone
   that doesn't jump; clicks; digital silence.
3. Fix with a short crossfade (about 6-8 frames centred at a tonal jump, 2-3 frames at a stutter; ITE xiJmwycUxTY
   10:24, gwyneGrX9Jw 14:11), room tone from the same place, another take, or a different join point.
`letitedit_hear` describes sound over time in words (useful to find silence, clicks or noise), but it does not judge
whether a join sounds like one thought. If nobody listened, write it in the journal:
`craft: joins not heard: 0:41, 1:12, 2:03` so the review can list it as not checked.

## 5. Gaps, holds and breaths (P4, P5, D3, B4)
Read the project's words per word (`letitedit_words` on the project). Defaults to start from:

| Measure | Starting point | Basis |
|---|---|---|
| Pause inside a thought in speech meant to be fluent | flag at about 1 s or more unless marked dramatic | demo pauses of ~1 s, 1.3 s and 3 s were cut (ITE urCAMKTsc6o 05:41-08:12); threshold [GEN] |
| Space after a key emotional, complex or revealing line | about 1.5 s or more in long-form | [GEN]; the slowest demo ran 7-14 s (ITE 5G2wGolpXxE, measured), an upper reference |
| Face held after a revealing line | about 1 s, until the expression resolves | [GEN]; principle from AOTC pop L298-302 |
| Stretch with no breath or reset | flag over about 30 s | [GEN]; principle from AOTC pop L232-262 |
| Sentence-boundary gaps | not uniform | principle from ITE DcA-Jfa2fdw 04:35; measure [GEN] |
| Shorts tail after the payoff | about 1 s or less | JH 7:07-8:15 (one anecdote); letitedit-shorts |

A deliberate long hold gets a `hold:<reason>` marker (`letitedit_bin`), so the gate can waive its longest-shot check
there. A held shot still needs something changing every few seconds (behaviour, expression, action) [GEN; principle
from AOTC skeleton L252-258 and AOTC hamnet L76-94].

## 6. Island list (D1)
One row per sync island, in story order: id, first and last words with times, its one job (premise, memory, detail,
stakes, doubt, payoff, hand-off...), and the link to the next island (but / therefore / list item / time jump). Name
the section's first line and last line. While building, a spacer of about 1 s between islands makes the structure
visible before cover goes on (ITE xZnHgyeZlsU 08:16). The "words stop changing before cover" check: no change to the
spoken words after b-roll placement started (read `letitedit_journal`, which logs every apply).

## 6b. Beat connectors (S4)
Label the link between each pair of consecutive beats: but, therefore (so, turns out, a time jump that changes
things), list item, or and-then. Then read only the connector sentences, top to bottom: they should retell the story
(a test carried over from the earlier story skill; ITE ZcIVl01h14Y 06:41 does the same with scene cards). Flags: three
"and then" links in a row (merge, cut or bridge them, JH 22:07); a list without a visible count or with items spoken
less than about 2 s apart in a reflective section (ITE 5G2wGolpXxE, measured); chronology that isn't causal and isn't
asked for by the mode.

## 7. Boundary table (C5)
One row per section boundary: outgoing last line and last shot, the reason to move on (pictorial bridge, verbal
hand-off, question answered next, tension released next, sound bridge, energy set up), incoming first line and first
shot, and whether the energy or shot scale contrasts (or a note that one push carries through). A boundary with no
nameable reason gets reordered or given one (a sound bridge, a hand-off line, a bridging shot). Source: ITE hwecWg2IR18
01:02-11:16 and its checklist (the last shot's mood, what the last words imply, the emotional state, whether the moment
invites a response, a contrast or a continuation).

## 8. Setups, payoffs and loops (S5, T1)
A list of every setup and its payoff with both times, and every open question with its open and close times. Use
`loop:open:<id>` and `loop:close:<id>` markers (`letitedit_bin`) once they are on a timeline. Flags: a payoff with no
earlier seed; a highlighted setup that never pays off; a thread the story opened and dropped [OURS]; a loop meant to drive the piece that closes within a few seconds [GEN]; a loop
never closed without a declared open ending. The story plan (letitedit-story) keeps the planned version.

## 9. Anchors and b-roll runs (B1-B4)
- **Anchor list:** from the transcript, mark emotional peaks, key nouns, list items and tonal shifts. For each: cover
  it (with its link level: literal, symbolic, mood, wallpaper) or keep the face on purpose.
- **Run labels:** each b-roll run's `why:` marker names its job (illustrate, hide a join, make space, set mood or
  place, carry structure) and its link. A run whose only job is "cover" in a story section is a soft flag.
- **Sequences:** per run, the number of shots, their sizes, and whether the last one completes the action.
  Flag three or more illustrative shots in a row with no dialogue progression or visible change, and three same-size
  shots in a row.
- **Faces:** key lines and each speaker's last line of a section are on camera (frames at those times).
- **Timing:** each cutaway entry is labelled word, eyeline or movement; for a line that comments on a new image, the
  image starts before the line.

## 10. Device ledger (L1)
Keep a `letitedit_journal` note starting `devices:` and update it as devices go in, for example
`devices: whoosh 0:12, 1:40; punch-in 0:33, 0:51, 1:20 (escalating); dissolve 2:05 (time); reveal=hold+music-drop 1:10`.
Count what is on the timeline from `letitedit_timeline_read` (transitions, effects and scale keyframes per item, SFX
clips on audio tracks, graphics); note the judgment items by hand (reveal treatments, reaction formulas, how sections
open and end). Flags [GEN spacing; principle ITE 4s7WdcyV1H4 11:04]: the same device twice within about 30 s; three
uses without escalation; consecutive reveals with the same treatment; no low-intensity stretch anywhere. Series
grammar (a recurring first-frame layout, bookends, one chapter-card style) is not counted as repetition.
No tool reads the `devices:` note yet: it exists for your revisions and for the person.

## 11. Meaning map and cheat log (D5)
`letitedit_words` on the project gives timeline words with the clips they come from. For each rendered sentence, note its
source file and span. Review every sentence that crosses two source answers, and every removed span that contained
not, never, unless, but, maybe, or I think (that word list is [GEN]). Keep cheats in the journal, one line each:
`cheat: 1:12 reaction from 1:40 source, same moment, meaning unchanged`. In documentary or interview modes, a cheat
involving a third party needs the person's OK before delivery. Sources: ITE KAO0n3C0kAg 12:09 (does the change alter
the information or meaning?), ITE DcA-Jfa2fdw 07:06, AOTC pop L36-42 (the arc must stay true to the person); the
policy itself is our synthesis.

## 12. Visible jump cuts (D6)
A visible jump cut: two consecutive pieces from the same source, similar framing, the face on screen, a gap in source
time. Count them per minute and find the longest run of consecutive ones (frames at the joins). Compare with the mode's
budget (letitedit-modes) and the brief's tone. Each kept one has a reason (energy, comedy, compressing a ramble).

## 13. Time gaps (X2)
Recording times come from `letitedit_footage`; `letitedit_segments` splits a shoot at recording gaps; `letitedit_overview`
shows recording-time jumps on the edit. For each large gap between consecutive pieces (the threshold depends on the
story: minutes inside a scene, hours or days across it [GEN]), confirm a cue: a visible change in the frame, light,
a clock, a card, a dissolve, a step montage. Time cards use the real recording dates and elapsed time [OURS].

## 14. What craft writes down
- `why:` markers on main-track clips and b-roll runs (what it does for the story, or its job and link).
- `hold:<reason>` markers on deliberate long holds; `loop:open:<id>` / `loop:close:<id>`; `cut:<reason>` at big
  removed stretches (kept so they can come back).
- Journal notes: `devices: ...` (section 10), `cheat: ...` (section 11), `craft: ...` with the results of the checks
  run before a render is shown (gear list, boundary reasons, muted test, first-time-viewer bumps, joins not heard).

## 15. If a tool named in SKILL.md isn't listed yet
`letitedit_guide` lists what this install offers. The newer tools have older routes:
- `letitedit_find_takes` missing: read the files' words (`letitedit_words`) and search for the line's words
  (`letitedit_search`) to find its other takes; compare them by ear and face.
- `letitedit_soundtrack` missing: cut the song to length or hit points with `letitedit_fit_music`, and mix it under the
  speech with the `score` op (letitedit-sound).
- `letitedit_annotate` missing: follow the object with `letitedit_track` and draw the pointer with `letitedit_graphic`
  (letitedit-graphics).
- `letitedit_caption_fit` missing: the `captions` op of `letitedit_timeline_apply` (letitedit-captions).
- `letitedit_review_bundle` missing: `letitedit_quality_gate` plus `letitedit_critic` (letitedit-gate).
