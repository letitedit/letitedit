---
name: letitedit-shorts
description: Make short vertical videos (YouTube Shorts, TikTok, Instagram Reels) with letitedit - find self-contained moments in long footage, open on a visual hook that works muted and could be a title, foreshadow the ending within about 3 s, show a visible mechanism (steps, a countdown), meet the expectation then twist it, end right after the payoff, and make a separate edit per platform, reframed to 9:16 with letitedit_versions and exported per platform. Not frantic by default - pace comes from the brief's feel and mode. Use for any short, "make clips from this", or a vertical version of a long edit.
metadata:
  version: 0.4.0
---

# Shorts (a format, not a pace)

**Decides:** which moments become shorts and, for each, the first frame and line, the foreshadow, the mechanism, the
beats, the payoff and last frame, and the cut for each platform. **Needs:** `brief.json` (mode, driver, feel,
`deliverables` `{kind: "short", platforms, target_s}`, must_keep, claims, ending), `story_plan.json` or the log's
selects, the footage. With letitedit-craft (pace, revision levers) and the mode's playbook (letitedit-modes); captions:
letitedit-captions. Step labels, counters and arrows: letitedit-graphics. **Evidence:** mostly one creator, Jenny Hoyos
[JH m:ss], from her own channel: the person's own results, when they exist, beat every number here [JH 6:29, 17:56].
Tags and sources: `references/sources.md` (`[GEN]` and `[OURS]` as letitedit-craft defines them); her examples, the opening and ending templates and the meta-phrase list:
`references/method.md`; platforms, reframing and export in detail: `references/platforms.md`; the evidence
behind sections 0, 5.2, 6.1, 7, 9 and 10, and the reframe tool's details: `references/manual.md`.

## 0. Not frantic by default
- Pace from the brief's feel, mode and reference with letitedit-craft's levers, as for any edit. Cut dead time (air
  before the hook and after the payoff, meta talk, search pauses); keep the breath that ends a thought and the beat a
  reaction needs [JH 20:52; ITE xiJmwycUxTY 07:40]. Not when the brief, a reference or the platform cut asks for dense
  and fast (the TikTok cut, section 9). Check: the plan names the feel; the gate's pace checks only advise on shorts
  unless the brief or a reference sets the tempo (letitedit-gate).

## 1. Find the short in long footage
- **1.1 Candidates** that could stand alone: a result or reveal, a stake or goal, a strong or funny line, a twist, a
  step list, a reaction. Rank by a good hook, a mechanism, a reason to rewatch or share [JH 14:13]; a personal reason
  or goal makes viewers care [JH 1:37]. One subject per short. Find them with the log's selects, `letitedit_search`
  (words and pictures), `letitedit_words`. Check: one row per candidate (source range, hook frame and words,
  mechanism, payoff, rewatch or share reason, stands alone yes/no); drop one that overlaps a better one by more than
  half [GEN].
- **1.2 It stands alone:** no dangling "it/that/he", no "like I said", no mid-list start; a young viewer still learning
  English would follow it [JH 26:14]. Fix in this order: add the setup line, a 4-8-word on-screen label, then (with the
  person's approval, disclosed) a short voiceover [GEN]. Never invent a beat, a twist or a reaction the footage doesn't
  have: say what is missing and suggest a pickup.
- **1.3 The ends first:** from a talk, the hook is the line a stranger would stop for, wherever it was said; recording
  order is no reason [OURS]. The last line or frame and the hook, then the foreshadow, then the middle [JH 23:54;
  ITE iAKUVUD7fG0 11:18]; the opening cut last, once you know what the short became [AOTC Greatest Night in Pop].
  Check: the plan names the first frame, the last frame and the foreshadow before the middle is placed.
- **1.4 The story chooses the length.** With New video's "Let the AI choose", select a complete setup, change and
  payoff from the source before a duration; record in `story_plan.json` `deliverables.short` the `selected_story_s`,
  `length_reason` (the source beats that need that room) and `payoff_line` (the exact spoken words that close the promise). A picture or sound
  payoff uses `payoff: {"kind": "visual" | "sound" | "audiovisual", "description": "the closing action and
  release"}` with its logged source range (the critic judges it in the export). The chosen target goes in `brief.json`
  once; do not keep shortening it to match a thin render. A full talking-head setup and payoff usually needs around 20
  seconds or more when the source has more to say; a genuinely self-contained joke or reveal can be shorter. Never end
  mid-sentence or drop a payoff to satisfy a pace, caption or duration check. A new source discovery that changes the
  story: revise the plan (source ranges, reason) before the target. The gate compares the export with the selected
  story, the exact payoff line and the final spoken phrase. [OURS]

## 2. The hook: a picture that works muted and could be a title
- **2.1 First frame like a thumbnail:** the most recognisable thing in the premise (the place, the product, the
  result, the broken part) plus at most a few words; muted, a stranger can say what this is, and it would work as a long
  video's title and thumbnail [JH 2:34]; picture first, then the fewest words [JH 3:16]. Not when the creator is the
  draw: then the face can be it [GEN]. Check: frames 0 s and 1 s (`letitedit_check_frames`, times_s=[0, 1]) and the
  first 3 s muted: write the premise from them alone (ITE's 10-second test plays an opening twice, the second time
  muted [ITE esNXgCJh-yk 14:08]).
- **2.2 Frame 0 is content:** no black, fade, logo card or title card; a logo inside the picture is fine [JH 10:00].
  Check: the gate's frame0_not_black (advisory).
- **2.3 Literal first:** show what is being said; subtext can come later in long-form [AOTC Greatest Night in Pop]. No
  greeting, no "in this video", no name-and-job opener [ITE gwyneGrX9Jw 02:20]. Check: the first 3 s of the transcript
  and the frames say the same thing.
- **2.4 Options:** 3-6 hooks with different approaches (visual premise, stake, result first, question, mystery);
  offer the person three, keep the runner-up as a test variant [JH 10:59-11:42]. A series keeps one first-frame layout
  [JH 10:36]; vary the devices inside each video [ITE 4s7WdcyV1H4 11:04]. `letitedit_hooks` proposes candidates (a
  chosen style's hook rules order them): judge them against this section, sharpen their text, swap with `{op: hook}`.

## 3. Foreshadow, then keep moving
- **3.1 Say what they'll get by the end** (or show it as text) after the hook: hook and foreshadow are two short lines,
  done by about 3 s [JH 19:20, 20:14]. Name the end state, never the outcome: the result and any twist stay withheld
  [JH 16:47; ITE esNXgCJh-yk 05:28]. A flash-forward cold open can show the moment; it must then appear later
  [JH 16:47]. Not possible when the footage has no such line: then on-screen text, or propose a voiceover line to the person. Check: word times
  (`letitedit_words`) put both lines' ends by ~3 s.
- **3.2 No pace-breaking transition lines** ("let's get started", "so today", "without further ado"): replace one with
  a line that is itself a story beat [JH 21:20], "a pacing break without the pacing actually breaking" [JH 20:52]. No
  new facts right after the two key lines; viewers forget them [JH 21:45]. Check: no meta phrases in the first 10 s of
  the transcript (list in `references/method.md`); at most one new fact between the foreshadow and the first beat
  [GEN].

## 3a. Keep a talking-head picture alive
- With "Let the AI decide" and one camera angle, the normal jump-cut grammar: a modest punch-in at an emphatic word or
  new idea, then a reset to the wider frame; a motivated crop or cutaway changes the picture within the opening few
  seconds; the face and the cadence carry reflective lines; do not zoom on every sentence. A dialogue-led product Short
  with only a speaker still resets: do not punch in once and hold the close-up through a 15-30 s Short. Crops sharp,
  the eyes in a comfortable place; a zoom that only separates two spoken cuts stays subtle; a stronger emphasis zoom
  must earn its place in the story. [GEN; OURS]
- Where the words name a product action, step, comparison or object: a relevant screen shot, detail shot, b-roll or one
  simple explanatory graphic if the source supports it. No proof in the footage: say so in `pickups.md`; an honest,
  clearly labelled illustration only if it clarifies the line; it cannot stand in for a real demonstration. Every
  graphic clear of faces, captions and the platforms' covered areas; if captions crowd out the only explanatory graphic,
  first find a new caption place or reframe the footage. Check the rendered frames at phone size: timeline zoom
  settings alone don't prove a viewer sees a change. [GEN; OURS]
- Watch the first three seconds muted, then sample the middle and ending: each picture change points to a new thought,
  reveal or emphasis; hold a face when the emotion matters; no long unmotivated static stretch.

## 4. A visible mechanism
- **When:** steps, builds, challenges, lists, tutorials; not a single moment (a reaction, a joke) [GEN]. Show how
  close the payoff is: "three things to do" with the list on screen, a countdown, a shrinking budget or time limit, a
  step counter [JH 15:29-16:18]. Documentary editors get the same pull from a ticking clock and dates [AOTC Greatest
  Night in Pop]. Step labels or a counter (letitedit-graphics: `letitedit_graphic`, `letitedit_annotate` to point at
  the thing). Check: the device appears by
  ~5 s and updates at each part; no promised part is missing.

## 5. The middle: change, expectation, twist
- **5.1** Every beat changes the situation: "but" or "therefore", or problem then solution [JH 22:07; ITE eXUH3Z5ZntE
  03:15]. Check: the plan's connectors; no three "and then" links in a row.
- **5.2** Meet the expectation the foreshadow set, then turn it if the footage has a turn [JH 16:32-17:34]; professionals
  edit for surprise, the third beat breaking the pattern [ITE 4s7WdcyV1H4 12:31]. Never manufacture a twist; mode-specific turns (a repair's failed
  first fix) belong to the mode playbook (letitedit-modes). Check: what the foreshadow named happens on screen, and a
  cold-open moment recurs in place.
- **5.3** Room to breathe comes from story beats (a reaction, a short wide, a line that moves on), not dead air
  [JH 20:52]; a moment that must land gets its beat (letitedit-craft), short in a Short: one reaction or a 1-2 s hold
  before the payoff, not a run of listening shots. A payoff the viewer must hear (a test, a noise that stopped) also
  gets a visible cue (a label, a meter): many watch muted [OURS]. Check: every pause over about 1 s carries a reaction,
  a picture or a sound worth hearing; the build before the payoff is under ~3 s.

## 6. Pay off, then end
- **6.1 End right after you've done what you said you would** [JH 0:42]: the payoff is the last beat, on screen, not
  only in the narration; trim the dead last second (on a 30 s short each second is about 3% of it [JH 7:36]). Her endings
  read as abrupt but satisfying [JH 25:06].
- **6.2** No outro card, subscribe ask, logo sting or slow fade after the payoff; at most one call to action, under 2 s,
  riding the payoff [GEN]. Music carrying the end: cut on the beat rather than fade, on a phrase that resolves
  [ITE xZnHgyeZlsU 26:40; ITE xhJLcy8Kzl4 16:16] (letitedit-sound). End on a short line or image and cut soon after [ITE
  WOX-WdXSOOc 44:52]. Check: payoff (the last key word, the reaction peak, the action done) to the end about 1 s or
  less (one anecdote: tune it on the channel's data); the gate's tail_silence_s; watch the last 3 s
  (`letitedit_check_range`).
- **6.3 The beat after the payoff is picture:** the breath that ends the last line comes from running the picture on
  past the voice's out point (the same shot held, or a cover, with room tone or the music under it), never from moving
  the voice clip's out point into the source's next sound (the review's edge check flags that cut). Check: last word to
  the end from `letitedit_words` on the cut (the gate's tail_silence_s counts the whole mix, so with music under the
  ending it stays near 0 whatever the voice does). [OURS] [GEN]

## 7. Rewatch, and loops only when they fit
- Aim for a short people finish and watch again [JH 8:31-9:07]. A loop only when the content invites it (the last line
  runs into the first, or the last frame matches the first; no end card, no fade) [GEN: no source covers loop
  technique]; not when the end resolves a story (a fix that works, a reveal): forcing a loop undoes it. Check: play the
  last 2 s into the first 2 s.

## 8. Plain words
- Hook lines, on-screen text and any voiceover at a 5th-grade reading level or below; explain a hard word in the same
  breath [JH 3:16, 4:20-5:29]. You cannot change what the person said: choose the plainer take (`letitedit_find_takes`),
  write plain text, suggest a line. Plain words, not fewer ideas: each idea its own beat [ITE pRpaqx_5jD8 05:12].
  Check: a readability score on the hook and the text (approximate [JH 4:52]).

## 9. One edit per platform (low confidence)
- Several platforms in the brief: cut each its own version rather than one posted everywhere [JH 28:07-29:13]. Her
  reading: YouTube Shorts older, slower, more story (her best about 34 s) [JH 17:38, 29:13]; TikTok shorter and denser
  (for her 10-20 s, packed with information, few jokes) [JH 29:13]; Reels very visual, subtitles throughout because many
  watch muted, easy to share [JH 29:50]. Confidence low (one creator, 2023, a young audience; platforms change):
  lengths come from the brief's target_s or the channel's data; never pad, never cut below what the story needs
  [JH 18:43, 19:20].
- TikTok Creator Rewards counts videos of at least 60 s [YT]: if the person is in it, choose on purpose (60 s or more,
  or short and dense); never 57-59.9 s by accident (the gate warns, on TikTok cuts only).
- The cuts are versions of one master (`letitedit_versions`, ranges per platform), labelled with the platform. Check:
  one file per requested platform; the Reels file passes a fully muted watch with captions on all speech
  (letitedit-captions).

## 10. Reframe to 9:16
- One 1080x1920 master at the source frame rate (`letitedit_project_new(path, width=1080, height=1920, fps=...)`, or
  from a long edit `letitedit_versions(main, action='make', target='vertical' or a platform id, ranges=[...])`; in the
  app the person has Make a vertical short, each clip cropped to fill, centred).
- **An important object must stay in frame** (the broken part, the product, the face, the hand doing the step): say so
  with `letitedit_reframe` (or `letitedit_versions` with `reframe={'mode': 'solve', 'keep': [...]}`), which keeps several
  named subjects in the crop on a smooth path and reports how much of the time each is in, naming the part
  with a box (`{label, box, at}`); never trust the centre crop with it. Never stretch; upscale at most 1.25x on 1080p
  sources [GEN]. Subjects that can't share one crop: take its split or inset offer, or `reframe` fit 'fit' (bars or a
  blurred fill), and tell the person. Fast handheld close-ups lose parts: add boxes where its plan warns.
- Check: `letitedit_check_frames` on the version at every reframed item, with `platform=` to draw the covered areas: the object inside the frame
  and clear of the covered areas in every frame checked, and so are text and captions (letitedit-captions).

## 11. Export per platform
- `letitedit_export(version, platform=<id>)` for each cut (ids from `letitedit_platforms`: youtube_shorts, tiktok,
  instagram_reels; their sizes, lengths and covered areas too [YT]); web loudness, -14 LUFS with true peak <= -1 dBTP, is the export
  default (letitedit-sound). Never upload another app's download with its
  watermark [GEN].
- Metadata: the hook doubles as the title idea (40-60 characters); caption = hook + context + 3-5 hashtags [GEN];
  disclose AI voice or AI visuals [YT]; scheduling is the person's job.
- Gate each file: `letitedit_review_bundle` with the brief (its mode, driver and the deliverable's platforms): pace
  checks advise, the TikTok length warning shows on the TikTok file only, and the final word is review.md.

## 11a. A song added when posting
A song the person will add from the app's sound picker: letitedit-sound section 13. It changes the export and the hand-off (two files and a few lines on posting), not the
story: hook, payoff and words first; a separate cut per platform keeps the same start in the song only if its own
length still fits.

## 12. Hand-off and checks
Each short into `story_plan.json` under `deliverables.short` (in the app, a journal note starting `shorts:`): source
range, hook (frame, text, line), foreshadow, mechanism, beats with connectors, payoff and last frame, loop yes/no,
platforms with lengths, reframe focus. Markers (`letitedit_bin`): `hook:`, `beat:<id>:<label>`, `loop:open:<id>` /
`loop:close:<id>`, `hold:<reason>` over a shot long on purpose (the gate then waives the longest-shot check inside it).
Before the gate, confirm: the muted first 3 s are understood; hook and foreshadow end by ~3 s; no meta lines; the mechanism is
visible and complete; the payoff is on screen; about 1 s or less after it; each platform's file exists and its covered
areas are clear.
