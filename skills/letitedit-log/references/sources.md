# Sources for letitedit-log 0.2.0

Inside The Edit (ITE) transcripts: `inside-the-edit\youtube\transcripts\<id>.txt`, `https://www.youtube.com/watch?v=<id>`.
Art of the Cut (AOTC): `art-of-the-cut\articles\raw-text\art-of-the-cut-<film>.txt` (Top Gun: `top-gun-maverick-2022.txt`),
`https://borisfx.com/blog/aotc/<file name>/`; line numbers as in the research files. Jenny Hoyos (JH):
`complementary-youtube\transcripts\creatorscience-jenny-hoyos.txt`, `https://www.creatorscience.com/podcast/jenny-hoyos/`.
Film Editing Pro (FEP): `film-editing-pro\articles\<slug>.txt` (collector's notes, low weight).


| Tag | Document | Times / lines | Used in |
|---|---|---|---|
| ITE eXUH3Z5ZntE | Why Your Edits Don't Feel Right | 02:20, 06:22 (progression, not description); 06:45 (illustrative vs sequential) | intro, LOG-4 |
| ITE WlS5f8Plyl0 | Shoot for the Edit 1 | 22:11-22:30 (structural value: entry, exit, transition); 06:14 (event before/during/after) | intro, LOG-6 travel row |
| FEP drivers | how-to-start-a-cut-the-5-edit-drivers | note | LOG-2 |
| ITE xiJmwycUxTY | The Biggest Dialogue Editing Mistake | 06:35, 09:05 (transcripts find lines; voice energy judges them) | LOG-3 |
| ITE mQT6QnsM2eI | Body Language | 07:00-07:32 (words vs body) | LOG-3 |
| ITE DcA-Jfa2fdw | How Pro Editors Shape Dialogue | 09:00-09:10 (room tone library); 09:18-09:31 (delivery must match the face) | LOG-3, LOG-5 |
| ITE zXHKcITf3x8 | Shoot for the Edit 2 | 17:07-21:21 (progressive chains); 06:50-07:30 (undecided camera, holds) | LOG-4, LOG-9 |
| ITE urCAMKTsc6o | How Pro Editors Fix Messy Interview Dialogue | 08:30-08:46 (the resolving ending); 13:33-13:38 (location sync) | LOG-5, LOG-10 |
| AOTC Porcelain War | art-of-the-cut-porcelain-war.txt | L74-78 (self-shooters film what they love); L100-106 (their recordings as the soundscape) | LOG-5, LOG-7, LOG-8 |
| ITE iAKUVUD7fG0 | How to Edit Unscripted Dialogue (3 stages) | 04:33 (the pull); 08:45 (cut down: retakes, errors) | LOG-6 interview row, LOG-9 |
| JH | Creator Science interview | 15:51 (a visible list of steps); 10:00 (brand, product and price in frame one) | LOG-6 tutorial and product rows |
| ITE hwecWg2IR18 | Why Your Scenes Don't Flow | 03:59-04:27 (verbal hand-off to the example) | LOG-6 tutorial row |
| AOTC GNIP | art-of-the-cut-greatest-night-in-pop.txt | L52-58 (decision points); L278-284 (information belongs in a book, experience on film) | LOG-6 documentary row, LOG-7, LOG-15 |
| ITE 2aux2Y9-4m8 | 2 Music Editing Techniques | 07:41 (instruments assigned to moments) | LOG-6 montage row |
| AOTC TGM | top-gun-maverick-2022.txt | L69-95 (break footage down by kind of activity) | LOG-6 montage row |
| ITE jN3TIBIQlac | How to Edit B-Roll Like a Pro | 06:33 (emotion first); 08:06 (mark emotional and descriptive lines first) | LOG-7, LOG-8, LOG-13 |
| ITE pRpaqx_5jD8 | How Pacing Controls Emotion | 07:06-07:24 (the editor is the first audience) | LOG-8 |
| ITE WOX-WdXSOOc | Watch Me Edit: Rough Cut to Documentary Scene | 07:19 (enter where it gets good); 26:16 (keep an aside that shows character); 28:46-29:11 (the natural take) | LOG-9, LOG-10, LOG-14 |
| AOTC Skeleton Crew | art-of-the-cut-skeleton-crew.txt | L102-106 (the first take was the most natural); L252-258 (a cool shot never wins over story) | LOG-10, LOG-13 |
| AOTC MI | art-of-the-cut-mission-impossible-the-final-reckoning.txt | L300-304 (fine selects, every option known) | LOG-12 |
| AOTC Dune | art-of-the-cut-dune.txt | L168-170 (a string-out of every setup) | LOG-12 |
| ITE 9jRZIqPQHm8 | How Pro Editors Use B-Roll | 04:22 (symbolic b-roll is legitimate) | LOG-15 |
| ITE FOJhAl9IyPg | Why Your Scenes Don't Work | 08:07-09:30 (almost-right material dilutes a scene) | LOG-16 |
| RES Timeline-Bench | https://arxiv.org/html/2609.35143 | agents left slates, crew talk or retakes in 18.5% of rejected computer-use edits | LOG-9 |
| OURS | local implementation | Inspect enough actual frames to judge the selects before building. | LOG-4 |
| GEN | general practice, unsourced | overview order, recording time over file dates, requirement mapping, select edges, the vocabulary table as a synthesis, the tie-break order | LOG-1, LOG-6, LOG-11, LOG-13, LOG-14, LOG-16 |

Tools named (parameters from `letitedit_guide('<tool>')`): `letitedit_segments`, `letitedit_footage` (`log=True`),
`letitedit_words` (`pictures`, `per_word`), `letitedit_search`, `letitedit_stills`, `letitedit_log_frames`,
`letitedit_log_write`, `letitedit_ask_frames`, `letitedit_hear`, `letitedit_separate`, `letitedit_note`, `letitedit_find_takes`
(groups and measures takes, never picks one, splits claim variants),
`letitedit_archive`, `letitedit_transcript`, `letitedit_journal`.
