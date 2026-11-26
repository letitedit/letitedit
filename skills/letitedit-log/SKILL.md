---
name: letitedit-log
description: Log raw footage for a letitedit edit in the brief's mode - text to find lines, picture and sound to judge them, picture-first logging for files with little or no talk, a role vocabulary per mode (not repair roles by default), repeated takes grouped with letitedit_find_takes, every brief requirement (required lines, must_keep, claims, ending, protected, must_avoid) mapped to a source time - then rank selects per beat. Writes log.json and selects.json. Use first on any edit from raw footage, and again for selects once a draft story plan exists.
metadata:
  version: 0.2.0
---

# Footage log and selects

**Decision:** what the footage holds, where, how good each moment is, and which moments compete for each beat. Log
what happens and what changes, not what the shots look like: the log serves the story plan.
[ITE eXUH3Z5ZntE 02:20] [ITE WlS5f8Plyl0 22:11]

**Inputs:** `brief.json` (or the journal brief): `mode` (the first leads), `driver`, `feel`, `required_lines`,
`must_keep`, `must_avoid`, `claims`, `ending`, `protected`, `narration`, `deliverables`; the footage, used in place;
the person's own transcript when they attached one (`letitedit_transcript`): it wins, never replace it. Load with the
router, letitedit-craft and the mode's playbook (letitedit-modes; section 1 of the mode file says what to log
first). No quotas anywhere: log what is there. Evidence tags as in the skills README; documents in
`references/sources.md`.

## 1. Overview first
**LOG-1 Map the shoot before the details.** Do: `letitedit_segments` on each folder (recording order, gaps, place
moves, people and camera changes), `letitedit_footage` for talk time, sound events, motion and picture problems per
file, then `letitedit_words` for every file with talk. Order by recording time, not file dates (they can be copy
dates). For a long shoot, log segments first, then drill into the stretches the brief and the mode's vocabulary
point at. When: every job. Not: when a `log.json` for the same files exists, update it instead of starting over.
Check: every source file is in the log with a summary, or `unused: <reason>`. [GEN]

**LOG-1b Sync several devices first.** Do: when the shoot has more than one camera or phone, or a separate sound
recorder (a WAV next to the videos, two devices filming the same moment), run `letitedit_sync` on the folder before
logging: it places every take on one timeline by sound and, with `synced_clips`, writes copies of the camera clips
with the recorder's sound in, so every later tool hears the good sound. Log and cut from those copies; keep the
sync timeline in the log (`sync`: file -> timeline time, level). Takes it leaves out (another day, no sound) are
logged on their own. Read its warnings: a take placed "up to about 20 ms" or "likely" gets a look at its sheet (the
cameras at a clap) before a cut leans on lip sync. When: two or more devices. Not: one device only. Check: every
device's takes are synced or listed as not placed, with the reason. [GEN]

**LOG-2 Say what the footage can drive.** Do: record the talk share, music already in the footage and the long
wordless stretches; if the brief's `driver` can't be carried (dialogue named but little usable talk, music named but
no track), write `driver_note` and tell the person before the plan. When: every job. Not: never change the brief's
driver yourself. Check: `driver_note` is filled. [FEP drivers]

## 2. Text to find, picture and sound to judge
**LOG-3 Find lines with text; choose them by ear and face.** Do: search and cluster with the transcript
(`letitedit_words`, `letitedit_search` on words), then judge each candidate line by its delivery: energy, spontaneity,
intonation, and whether face and body agree with the words. Look at the frames of every candidate (`letitedit_words`
with `pictures`, `letitedit_stills`) before you rank it. When: every file with talk. Not: never rank a line on its
text alone. Check: each candidate line has a `delivery` note (energy; natural or stiff; face agrees or not).
[ITE xiJmwycUxTY 09:05] [ITE mQT6QnsM2eI 07:19] [ITE DcA-Jfa2fdw 09:18]

**LOG-4 Log pictures first where nobody talks.** Do: describe each stretch by what happens: action chains (start,
development, completion), behaviour and reactions, shot size, camera motion, light, and the usable range. Write the
log yourself from frame sheets (`letitedit_log_frames`, then `letitedit_log_write`), or start from the local model's
log (`letitedit_footage` with `log=True`) and correct it. Ask `letitedit_ask_frames` only for a yes/no fact that
decides something, and confirm its answer on the frames yourself (its accuracy varies by question). When: every file
with little or no talk, and all b-roll. Not: don't caption every frame; log stretches. Check: every wordless file
has stretches with `action`, `size`, `motion`, `usable`. Inspect the picture before building the cut. [ITE zXHKcITf3x8 17:07] [ITE eXUH3Z5ZntE 06:45] [OURS]

**LOG-5 Log sound as material.** Do: mark natural sound and actuality that carry meaning (candidates for
`protected`), on-location lines that back up an interview, a clean room-tone range per location (to fill gaps
later), music in the footage, and sound you can't use (wind, clipping). Tools: `letitedit_footage` sound events,
`letitedit_hear`, `letitedit_separate` when voice and background must be judged apart. When: every file with useful
sound. Not: don't mark ordinary background as protected. Check: each location has `room_tone` (a range, or
`none`). [ITE DcA-Jfa2fdw 09:00] [ITE urCAMKTsc6o 13:33] [AOTC Porcelain War]

**LOG-6 Tag roles in the mode's vocabulary.** Do: give each segment one role from the lead mode's row and save it on
the source (`letitedit_note` tags `role=...`, `quality=1-5`); something that fits no role is `texture` or `junk`, not
forced into one. When: every segment. Not: the repair roles belong to the DIY and repair playbook (letitedit-modes,
story-vlog); use them only when the plan follows it. Check: no segment carries a role outside its mode's row
without a note. [GEN; per-row sources in references/sources.md]

| Mode | Roles |
|---|---|
| story / vlog | want, setup, normal life, complication, turn, payoff, reaction, place, transition, texture |
| tutorial / explainer | step (numbered), why, hand-off ("let me show you"), detail to copy, mistake or warning, result, list |
| interview / podcast | topic (a short label), answer, first-line candidate, last-line candidate, personality, emotion, information only, listener reaction |
| documentary | character, decision point, complication, revelation, normal life, context, observed scene, location sync, archive |
| product / commercial | customer problem, feature, proof of a claim, in use, hero shot, brand frame, offer |
| travel / event | place, arrival, journey with a purpose, activity, people and reactions, before / during / after, sound of the place |
| montage / transformation | energy 1-5, motion direction, action start / peak / completion, before state, after state, texture |
| creative / stylised | motif, light and colour, symbol, rhythm, movement, sound texture |

**LOG-7 Mark lines and moments worth keeping.** Do: candidate lines carry experience, feeling, a specific detail or
personality, or state what the mode needs (a step, a claim, the problem, the result); prefer experience over
information-only lines. Moments: something changes, someone reacts, a process completes. In self-shot footage, what
the person chose to film tells you what matters to them. When: every file. Not: no lines-per-minute quota. Check:
each candidate has `why` (what it could do for the story). [ITE jN3TIBIQlac 08:06] [AOTC GNIP]
[AOTC Porcelain War]

**LOG-8 Flag emotion and surprise.** Do: flag emotion peaks (relief, frustration, laughter, a voice cracking, a long
look) and every moment that surprised you: you are the first audience. Emotion ranks first when choosing (LOG-13).
When the emotion graph is built (setting `emotion_graph`, or the person asked), read it first:
`letitedit_timing(<folder or file>, view='emotion')` gives mood and energy per sentence and turning points
(crossovers, rises, drops, peaks), each with the words either side and a `hone` call. It is a fast model's
judgement (`~`): use it to find candidates, then run the point's `hone` (view 'slow', frame by frame) and flag the
exact frame yourself; never use the graph's time as the cut. A feeling the list lacks (`other_moods_seen` shows
the ones the scorer named): `options={'moods': {'nostalgia': 'looking back fondly'}}` scores it on every stretch,
kept with the graph. No graph: log as before; build one
(`options={'build': true}`) only when the person asks, since it uses their AI usage. [OURS]
When: wherever they occur. Not: no emotion quota; a product or b-roll shoot may have none. Check: each flag has a
time and a word for the feeling. [ITE jN3TIBIQlac 06:33] [ITE pRpaqx_5jD8 07:06] [AOTC Porcelain War]

**LOG-9 Flag junk and what can't cut.** Do: flag slates, "is it recording", crew talk, false starts, coughs, and
shots that won't cut: an undecided camera, a zoom at the wrong moment, a focus pull that takes more than about a
second, a usable part too short for its section. Keep off-task asides that show character. When: every file. Not:
don't junk a whole shot when part of it works; log the usable range. Check: each junk span has a reason; an unusable
shot that is the only cover for a needed moment goes to `missing` (the story plan's pickup report). In
Timeline-Bench, agents left slates, crew talk or retakes in 18.5% of rejected edits. [ITE iAKUVUD7fG0 08:45]
[ITE WOX-WdXSOOc 26:16] [ITE zXHKcITf3x8 06:50] [RES Timeline-Bench]

## 3. Repeated takes
**LOG-10 Group takes with the tool; choose them yourself.** Do: run `letitedit_find_takes` on the talking files (see
`letitedit_guide('letitedit_find_takes')`): it groups repeats, marks false starts and measures delivery, and never picks
a winner. Choose by watching and listening: the most natural take that fits the scene's energy, not the most
complete one; when an answer has several endings, keep one, usually the one where the voice resolves. When: whenever
a line or passage was said more than once. Not: takes the tool splits as claim variants (a different number, name or
negation) are not the same line: keep both in the log and check them against the brief's `claims`. Check: every
group has `kept` and `why`, and the others are marked `junk: retake`. [ITE WOX-WdXSOOc 28:46]
[AOTC Skeleton Crew] [ITE urCAMKTsc6o 08:30]

## 4. Brief requirements, mapped now
**LOG-11 Map every hard requirement before the plan.** Do: find a source time for each `required_lines` and
`must_keep` entry, each `claims` item (where it is said and how it is spelled), the `ending` (candidate lines or
shots), and each `protected` range (check it holds a whole, usable moment); mark `must_avoid` spans so no select can
use them. Search with `letitedit_search` (words, picture, sound) and `letitedit_archive` (the person's indexed library)
before you write `MISSING`. When: every job, at the log, not first at the gate. Not: never meet a requirement with a
near miss; log it as `near` with what differs. Check: every requirement is `file@t`, `near` or `MISSING`; MISSING
ones go into the story plan's pickup report. [GEN]

## 5. Selects (`selects.json`; markers `sel:<beat>:<rank>`)
Rank once letitedit-story has a draft beat list (or a rough one of your own).

**LOG-12 Ranked alternatives per beat.** Do: list every candidate worth comparing, ranked, with a one-line reason;
mark a beat `contested` when two or more are close, for a string-out in letitedit-rough. When: every beat. Not: one
candidate is fine when only one exists; no fixed number. Check: each select has `rank` and `why`.
[AOTC MI] [AOTC Dune] [AOTC Skeleton Crew]

**LOG-13 Rank by feeling and story first.** Do: emotion and story value decide; performance, rhythm and technical
quality break ties [GEN for the tie order]. When: every ranking. Not: never let a beautiful but off-purpose shot
outrank a moment the story needs. Check: `why` names the deciding factor. [ITE jN3TIBIQlac 06:33]
[AOTC Skeleton Crew]

**LOG-14 Whole thoughts as the unit.** Do: speech selects start and end on thought or sentence boundaries (the fine
cut cuts inside them later); wordless selects enter where the action starts and leave after it completes. When:
every select. Not: never start or end inside a word. Check: `letitedit_words(per_word=True)` shows no word cut at a
select edge. [GEN] [ITE WOX-WdXSOOc 07:19]

**LOG-15 Note face or cover; don't choose b-roll yet.** Do: for each speech select note whether the face carries it
(emotion, credibility, a joke, a key line, a section's last line) or it is information that could be covered. When:
every speech select. Not: never pair b-roll just because the picture doesn't literally show the words: the fine cut
chooses cover by its job (letitedit-craft B1-B4). Check: each speech select has `face: keep | cover_ok`.
[AOTC GNIP] [ITE 9jRZIqPQHm8 04:22]

**LOG-16 An empty beat stays empty.** Do: a beat with no fitting select is `MISSING` (the plan bridges or cuts it).
When: every beat. Not: never fill it with an almost-right clip; no select overlaps a `junk` or `must_avoid` span.
Check: an overlap test against the log's spans. [ITE FOJhAl9IyPg 08:07] [GEN]

## Output and checks
`log.json`:
`{"files": [{"file", "recorded", "summary", "talk_share", "unused"}], "driver_note",
"segments": [{"file", "start", "end", "role", "quality", "summary", "lines": [{"t", "text", "why", "delivery"}],
"moments": [{"t", "what"}], "emotion": [{"t", "feeling"}], "picture": {"action", "size", "motion", "usable"},
"sound": {"protect": [{"from", "to", "why"}], "room_tone"}, "junk"}],
"takes": [{"group", "takes", "kept", "why", "claim_variants"}],
"requirements": {"required_lines": {}, "must_keep": {}, "claims": {}, "ending": [], "protected": {},
"must_avoid": []}, "missing": [{"what", "why", "blocks"}]}`

`selects.json`: `{"beats": {"<beat id>": [{"file", "in", "out", "rank", "why", "face", "contested"}]}}`

In the app's chat panel (no files), keep both as journal notes starting `log:` and `selects:`, as the router says.
- **Bookkeeping in code.** When the start message says code writes the `cut:` markers, add `"cuts": [{"file", "in",
  "out", "why"}]` to `selects.json`: each big stretch the cut leaves out, and why in plain words ("second take of the
  intro, weaker"); code places its marker (letitedit-firstcut FIRST-4). Update it when a later cut leaves out another
  one. Write the `brief:`, `log:` and `selects:` notes in one `letitedit_journal` call with `entries`: its reply
  checks each file it writes, so the files need no reading back.

Before the story plan: every file logged or `unused`; every requirement mapped, `near` or `MISSING`; every take
group decided; every wordless file has picture stretches; `driver_note` written; no select over `junk` or
`must_avoid`. Mark the stage done: `letitedit_journal` note `stage:log:done`.
