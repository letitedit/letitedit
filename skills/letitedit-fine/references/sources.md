# Sources for letitedit-fine 0.2.0

ITE articles: `inside-the-edit\articles\raw-text\<slug>.txt`, `https://www.insidetheedit.com/blog/<slug>`.


| Tag | Document | Times / lines | Used in |
|---|---|---|---|
| ITE DcA-Jfa2fdw | How Pro Editors Shape Dialogue | 03:31, 04:28-05:41 (retime moment by moment, sometimes adding space); 07:06-07:48 (retiming isn't manipulation); 09:00-09:10 (room tone) | FINE-1, FINE-4 |
| ITE xiJmwycUxTY | The Biggest Dialogue Editing Mistake | 07:40-08:19 (cutting breaths flattens thought); 10:16-10:51 (a 6-8 frame crossfade centred on the cut) | FINE-1, FINE-4 |
| ITE urCAMKTsc6o | How Pro Editors Fix Messy Interview Dialogue | 05:41-05:44, 07:01-07:07, 08:09-08:12 (pauses of about 1, 3 and 1.3 s flagged in speech meant to be fluent) | FINE-1 |
| AOTC GNIP | art-of-the-cut-greatest-night-in-pop.txt | L232-262 (keep breaths; over-fast cutting reads as insecure); L272-308 (interviews as performance; hold after the line; the last line on camera); L286-290 (frankenbiting in commercials) | FINE-1, FINE-8 |
| JH | Creator Science interview | 20:52-21:45 (a breather that keeps momentum); 29:13-29:50 (YouTube Shorts rewarded a slower, story-led pace) | FINE-2 |
| ITE WOX-WdXSOOc | Watch Me Edit: Rough Cut to Documentary Scene | 16:51, 26:34 (cut in when the subject is already moving); 30:14-33:13 (borrowed audio only where lips can't be seen); 47:27-47:52 (show the shot, then the line) | FINE-3, FINE-5, FINE-6 |
| ITE gwyneGrX9Jw | Watch Me Edit: Cinematic Documentary Opening | 14:11-14:29 (a 2-3 frame dissolve over a stutter); 33:49-34:21 (a very subtle push on a held shot) | FINE-4, FINE-10 |
| AOTC Dune | art-of-the-cut-dune.txt | L36 (don't dissolve to fix an unsolved edit) | FINE-4 |
| FEP bridge | smooth-your-scene-transitions-with-a-sound-bridge | note: the next scene's sound before its picture | FINE-5 |
| ITE 9jRZIqPQHm8 | How Pro Editors Use B-Roll | 03:46-07:42 (literal, symbolic, wallpaper and mood links) | FINE-6 |
| ITE 5G2wGolpXxE | How Pro Editors Build a Scene | 24:19-25:07 (tell then show, or show then tell) | FINE-6 |
| ITE jN3TIBIQlac | How to Edit B-Roll Like a Pro | 01:43-03:12 (sequential vs illustrative b-roll) | FINE-7 |
| ITE eXUH3Z5ZntE | Why Your Edits Don't Feel Right | 04:05-04:59 (chains of action, not collections) | FINE-7 |
| ITE KAO0n3C0kAg | The Same Scene Cut 2 Ways | 27:07 (the slow version used one shot where the fast one used several) | FINE-7 |
| ITE xZnHgyeZlsU | How a Documentary Scene Is Built | 20:22 (cut to the face for inner-world lines) | FINE-8 |
| ITE 4s7WdcyV1H4 | 7 Ways to Avoid Repetitive Editing | 10:54-12:26 (repeat only with escalation) | FINE-9 |
| ITE art:why-repetition-in-editing-kills-impact | The Economics of Editing | YouTube Edits section: digital zooms and rapid cuts wear viewers out | FINE-9 |
| AOTC Hamnet | art-of-the-cut-hamnet.txt | L76-94 (an uncut take creates tension) | FINE-10 |
| AOTC Skeleton Crew | art-of-the-cut-skeleton-crew.txt | L320-324 (hold a little longer to land a moment) | FINE-10 |
| ITE CdyTIng0M8Q | Pacing: Techniques | 09:17-11:42 (cut rate, action, distance and camera movement all set pace) | FINE-11 |
| ITE bCVeyUFGxi8 | Pacing: The Framework Pro Editors Use | 10:51-11:08 (a second slow scene goes flat about 30 s in) | FINE-11 |
| ITE ZcIVl01h14Y | What Makes a Great Documentary | 03:30 (ask for a reference film) | FINE-11 |
| RES Timeline-Bench | https://arxiv.org/html/2609.35143 | judges flag repeated ranges; against a reference, each halving of the cut rate costs about 6.6 points of win-or-tie and cutting faster isn't penalised | FINE-6, FINE-11 |
| RES fox-tree-1995 | Fox Tree (1995), Journal of Memory and Language 34, 709-738 (abstract) | words after a false start are recognised more slowly; after a repetition, not slower (sometimes faster): in a conversation cut false starts, keep repetitions | FINE-1 |
| OURS | local implementation | Count punch-ins from the timeline; scene detection can miss them. | FINE-9 |
| GEN | general practice, unsourced | 50/80 ms pads (from video-use, outside the library); 150 ms gaps; one-frame click fades; 0.5-1 s picture lead; 1.25x upscale; 30 s spacing; never two voices | FINE-1, 3, 4, 5, 6, 9 |

Tool facts used: the `tighten` op, items placed with `words`, `transition: {type: cut, len}` (picture cuts at the
middle of the overlap, audio crossfades across it; the clip overlaps the one before it), `insert` with `at` on a
track above the main one, the `mute`, `fade_in_audio` and `zoom` effects, `add_track`, Python `code` with `find` and
`layout`: `letitedit_guide` (edits, items, effects, code); the J/L
recipe matches `letitedit-sound/references/tool-recipes.md` section 5. `letitedit_check_frames(at_cuts=True)`,
`letitedit_measure`, `letitedit_export_job` (`picture_change`), `letitedit_fix` (punch). `split_edit` makes source-backed J and L cuts and can move picture rather than sound.
