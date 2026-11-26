# Sources for letitedit-rough 0.2.0

| Tag | Document | Times / lines | Used in |
|---|---|---|---|
| AOTC Dune | art-of-the-cut-dune.txt | L50-52, L104 (cut with the speakers off, then knit the sound back); L168-170 (string-outs) | ROUGH-1, ROUGH-7, ROUGH-8 |
| AOTC Skeleton Crew | art-of-the-cut-skeleton-crew.txt | L68-110 (line-by-line string-outs) | ROUGH-1 |
| ITE xiJmwycUxTY | The Biggest Dialogue Editing Mistake | 11:04, 14:19-14:50 (judge joins by listening, picture off) | ROUGH-1 |
| FEP drivers | how-to-start-a-cut-the-5-edit-drivers | note: build the element that drives the scene first | ROUGH-2 |
| ITE iAKUVUD7fG0 | How to Edit Unscripted Dialogue | 01:21-03:11 (dialogue builds the structure) | ROUGH-2 |
| ITE urCAMKTsc6o | How Pro Editors Fix Messy Interview Dialogue | 13:01-13:22 (b-roll only after the dialogue is fixed) | ROUGH-2 |
| AOTC Porcelain War | art-of-the-cut-porcelain-war.txt | L94-106 (scenes built sound-first); L116-122 (cut to the music from day one); L342-344 (an open ending) | ROUGH-2, FM4 |
| AOTC Invite | art-of-the-cut-the-invite.txt | L102-104, L130-136 (temp music from the assembly); L292-312 (the assembly keeps everything and stays a source) | ROUGH-2, ROUGH-3, ROUGH-6 |
| ITE xZnHgyeZlsU | How a Documentary Scene Is Built | 03:40-05:44 (is there a scene: start, middle, end); 08:16-08:22 (about 1 s between islands) | ROUGH-2, ROUGH-7 |
| AOTC MI | art-of-the-cut-mission-impossible-the-final-reckoning.txt | L34-40 (the first cut runs long); L62-84 (alternative structures for the opening); L192-196 (screen sequences dry) | ROUGH-3, ROUGH-6, ROUGH-8 |
| ITE WOX-WdXSOOc | Watch Me Edit: Rough Cut to Documentary Scene | 51:32 (a 4 min assembly cut to 1:58) | ROUGH-6 |
| AOTC GNIP | art-of-the-cut-greatest-night-in-pop.txt | L132-136, L252-256 (watch in context); the story was basically chronological (FM1); L182-194 (seed and pay off, FM11); L232-262 (breaths, FM8) | ROUGH-7, FM1, FM8, FM11 |
| AOTC Hamnet | art-of-the-cut-hamnet.txt | L56-58 (watch cold, as a first-time viewer) | ROUGH-7, FM12 |
| ITE ZcIVl01h14Y | What Makes a Great Documentary | 06:41 (test the order on scene cards) | ROUGH-8 |
| JH | Creator Science interview | 22:07 (but/therefore); 17:19 (the promise must be paid); 0:42, 16:32 (the end delivers the hook); 7:07-7:36 (trimming the last second lifted retention 83% to 88%) | FM2, FM4, FM5, FM10 |
| ITE eXUH3Z5ZntE | Why Your Edits Don't Feel Right | 16:27 (dialogue can carry the progression) | FM3 |
| ITE iAKUVUD7fG0 | How to Edit Unscripted Dialogue | 08:45 (retakes out) | FM7 |
| ITE gwyneGrX9Jw | Watch Me Edit: Cinematic Documentary Opening | 25:15 (an opening rebuilt with 3-5 s wordless shots) | FM8 |
| ITE xhJLcy8Kzl4 | How Pro Editors Structure Music & Dialogue | 16:00 (a scene needs to resolve) | FM10 |
| ITE esNXgCJh-yk | How to Start a Scene | 14:08-14:31 (the muted 10-second test) | ROUGH-9 |
| RES Timeline-Bench | https://arxiv.org/html/2609.35143 | agents who rendered late had no time to fix story; 18.5% left junk in | ROUGH-7, FM7 |
| OURS | local implementation | Plan fully before building; a retell alone does not replace the critic. | ROUGH-4, ROUGH-9 |
| GEN | general practice, unsourced | the 110-130% band; about 35% of the budget; 20 ms word straddle; 30 s without a breath; requirement checks | ROUGH-5, ROUGH-6, ROUGH-7, FM6, FM8, FM9 |

Tools named (parameters from `letitedit_guide('<tool>')`): `letitedit_try`, `letitedit_soundtrack`,
`letitedit_fit_music`, `letitedit_timeline_apply` (`dry_run`, `code`),
`letitedit_bin`, `letitedit_project_new` (`copy_of`), `letitedit_check_range`, `letitedit_check_frames` (`shots`, `count`),
`letitedit_overview`, `letitedit_look`, `letitedit_hear`, `letitedit_words`, `letitedit_ask_frames`, `letitedit_review_bundle`,
`letitedit_journal`. FM3, FM4, FM11 and FM12 exist only in the journal QA table: the review bundle doesn't compute
them (audit 4.3).
