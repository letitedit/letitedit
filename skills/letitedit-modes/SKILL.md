---
name: letitedit-modes
description: Playbooks for the kind of video in a letitedit edit - story/vlog (with DIY and repair), tutorial/explainer and screen recordings, interview/podcast excerpts, documentary, product/commercial, travel/event, montage/transformation (music-led) and creative/stylised. Picks and combines modes from the brief's mode, driver, feel and reference, and gives each mode's structure options, pace gears, sound, text, shot choice, openings and endings, gate settings and failure checks. Load with letitedit-craft whenever a letitedit edit is planned, cut or revised, or when the person names a kind of video.
metadata:
  version: 0.1.1
---

# Modes: the kind of video

A mode is the kind of video. It sets the structure options, what usually drives the cut, the gears its sections tend
to use, how sound, text and shots work, and which gate checks apply. It does not set tempo or look: the brief's
`feel` and `reference` do, so a slow Short, an urgent documentary and a calm product film are all fine. Shared craft
(purpose line, gears and levers, scenes, dialogue, reactions, b-roll, loops, repetition, transitions, revision
levers) is in letitedit-craft; a mode file only says how its mode sets it. Tags are explained in
`references/sources.md`.

Inputs: `brief.json` (`mode`, `driver`, `feel`, `reference`, `deliverables`, `claims`, `protected`, the old `genre`)
and the log.

## 1. Pick the mode

| Mode | File | Usual driver | Evidence |
|---|---|---|---|
| story: vlog, day, challenge, build, repair | `references/story-vlog.md` | the creator's talk or voice-over; pictures in hands-on parts | strong spine, thin vlog pacing |
| tutorial: how-to, explainer, screen recording | `references/tutorial-explainer.md` | narration plus the visible process | thin |
| interview: interview piece, podcast excerpt, a whole podcast on several cameras | `references/interview-podcast.md` | dialogue | strong on dialogue, thin on podcasts and multicam |
| documentary | `references/documentary.md` | interviews for structure, observation for feeling | strongest |
| product: ad, demo, brand film | `references/product-commercial.md` | music or voice-over, product action | thin |
| travel: trip, place, event | `references/travel-event.md` | pictures and natural sound, music | thin |
| montage: music-led, before/after | `references/montage-transformation.md` | music, or the visible change | medium |
| creative: stylised, music video, sketch | `references/creative-stylised.md` | whatever the style needs | medium to thin |

- **Use the brief's `mode`.** Without one, map the old `genre`: diy -> story (repair playbook; tutorial when the
  person wants a reference how-to), education -> tutorial, business -> product, travel -> travel, day -> story,
  doc -> documentary, before_after -> montage. With neither, infer it from the goal and the footage and write one
  line why. Ask only when two modes would give clearly different cuts (a repair story or a reference tutorial; an
  event recap or a mood montage). Not: never pick a mode from the topic alone; a cooking video can be a tutorial, a
  story or a montage. Check: the `modes:` note (section 6) names the mode and the reason. [ITE ZcIVl01h14Y 02:15]
  [FEP drivers]

## 2. Combine modes
Several modes are allowed; the first leads.
- **The lead mode sets the structure, the default driver and the gate settings; another mode lends sections or
  techniques.** Story + tutorial: a repair story whose fix runs as copyable steps. Product + tutorial: a demo.
  Documentary + interview. Travel + montage: a trip with a music-led montage. Story + montage: a build that ends on a
  transformation reveal. Creative can lead (a music video, a sketch) or ride on another mode as a style layer that
  changes presentation, not structure. Not: never average two modes into a blur. Check: every section of the story
  plan has one mode. [GEN]
- **When modes conflict:** the brief and the reference beat both; on honesty, claims, legibility and loudness the
  strictest mode present wins; on pace each section follows its own mode. Where the lead mode's gate settings would
  flag a looser section (a held montage inside a tutorial), add `hold:<reason>` markers over it, which waive the
  longest-shot check there, or a `waive:<check>:<reason>` marker (`letitedit_bin`). [GEN]
- **Read only what you use:** the lead mode's file, and from another mode only the sections you borrow. [OURS]

## 3. Driver, feel and reference
- **Driver:** the brief's `driver` (dialogue, narration, music, visual, sound) wins; otherwise the mode's usual
  driver, checked against the footage (a wordless stretch is not dialogue-led). It sets the build order in
  letitedit-rough: the dialogue first, the track first, or the pictures first. Check: each section of the plan names
  its driver. [FEP drivers] [ITE ml7w8spLRtI 00:01]
- **Feel:** a few words for the intended feeling, per section where it changes. letitedit-craft turns feelings into
  gears and levers; each mode file says which gears its mode usually uses and when to break them. When the feel and
  the mode's habit disagree, the feel wins and the plan says so. Check: the plan names a feeling and a gear per
  section. [ITE CdyTIng0M8Q 04:59] [ITE ZcIVl01h14Y 13:10]
- **Reference:** measure it with `letitedit_measure` (cuts per minute, shot lengths, words per minute, speech, music
  and effects shares, loudness, colour, on-screen text) and put the numbers in the `modes:` note. They replace the
  mode's pace defaults and make the pace checks active (section 4). A reference sets tempo and style, not the story:
  keep the structure this footage supports, and never copy its footage, music or words. Check: the render's own
  `letitedit_measure` cut rate and median shot length sit within about 0.8-1.25x of the reference's (a starting band
  to calibrate). [ITE ZcIVl01h14Y 03:30] [GEN]

## 4. Gate settings (proposal for letitedit-gate; `gate.py` stays the one source of truth)
Each mode file sets the gate's pace and opening checks (`cuts_per_min`, `longest_static_s`, `visual_change_first3s`,
`first_speech_s`, `silence_first3s_s`, `silent_share`, `frame0_not_black`, `tail_silence_s`) to one of: **on** (a
miss is a finding at the gate's normal severity), **advisory** (reported as minor; never changes the verdict by
itself) or **off** (not applicable; shown as not checked). A reference or a tempo in the brief makes the pace checks
active against the reference in any mode. `hold:` markers waive the longest-shot check for their range. TikTok's
57-60 s check applies only to TikTok deliverables.

| Mode | Pace checks, no reference | Long-form openings (first speech, opening silence, frame 0) | Usual loudness |
|---|---|---|---|
| story | advisory | advisory; off for a poetic or wordless cold open | web |
| tutorial | advisory; `hold:` over steps | advisory | web |
| interview | off for cut rate and longest shot | advisory | podcast or web |
| documentary | off; longest shot advisory | off | web or broadcast |
| product | advisory; first speech off | advisory | web or broadcast |
| travel | off; longest shot advisory | off | web |
| montage | off | off | web |
| creative | off | off | by deliverable |

Any Short: `frame0_not_black` is on in every mode and `tail_silence_s` in every mode but creative; without a
reference, nothing else is more than advisory (letitedit-shorts owns the hook). Loudness by deliverable: web and
social -14 LUFS, true peak <= -1 dBTP [GEN]; podcast -16 LUFS [RES]; broadcast -23 LUFS, true peak <= -1 dBTP (EBU
R128) [RES]. If the installed gate still grades a check your mode sets off or advisory as major, waive it:
`waive:<check>:<mode> mode (letitedit-modes)`.

## 5. Rules for every mode
- **Never invent what the footage lacks:** no manufactured setback, transformation, stakes, reaction or testimony.
  Say what is missing and offer an honest bridge (the person's own line, a short card) or a pickup. Keep the real
  complications: they make it believable. Check: every turn in the plan points to a source moment. [AOTC GNIP]
  [ITE A2RYo1xNSA4 08:58]
- **Words and claims stay true:** letitedit-craft holds the honesty boundary for retiming and cheats; interview,
  documentary, product and tutorial apply it strictly. Other people's words, facts, numbers and product claims never
  change meaning without the person's approval. Check: claims are in `brief.claims`; the critic compares each
  rebuilt sentence with its source. [ITE KAO0n3C0kAg 12:09] [AOTC GNIP]
- **No baked looks:** design text and graphics for this video (letitedit-graphics); filled-in templates lost to
  made-for-the-video designs. [OURS]

## 6. What every mode file holds, and the hand-off
Ten sections, the same in each file: 1 what drives it (driver, what to log first, the purpose line); 2 structure
options; 3 pace profile (the usual gears and when to break them, never a fixed cut rate); 4 sound; 5 text and
graphics; 6 shot choice and b-roll; 7 openings and endings; 8 gate settings (checks, loudness by deliverable,
questions for the critic); 9 common failures and how to check them; 10 evidence strength. Every rule says what to
do, when, when not, how to check, and its tag.

Write one `letitedit_journal` note: `modes: lead=<mode> others=<modes> driver=<...> feel=<...> reference=<file and
measured numbers> gate=<settings applied> waivers=<...>`. Put each section's mode, driver and gear in the story plan
(letitedit-story owns its fields), and give the critic the mode's questions (letitedit-review, run by
`letitedit_review_bundle`). Checks: a mode is named or inferred with a reason; the lead mode's file was read; the
`modes:` note exists; the mode's failure checks ran on the first render (letitedit-rough) and again before the gate.
