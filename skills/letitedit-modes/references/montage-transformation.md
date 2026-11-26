# Montage / transformation mode (music-led)

Edits the music drives or a visible change carries: a highlights montage, a sports or travel reel, a music-led recap,
a before/after transformation (a makeover, a build, a restoration, a garden through a season). Shared craft is in
letitedit-craft; music craft (bars, phrases, hits, endings, ducking) is in letitedit-sound. Tags: `sources.md`.

## 1. What drives it
- **Build the track first.** Choose the music by the feel, arrange it to the length and the sections, then cut the
  picture to it. When: the brief's driver is music, or the footage has little speech. Not: a transformation whose
  process talk drives (that is story-vlog with a montage section). Check: the music track exists before the picture
  selection is final, and its sections line up with the plan's sections. [FEP drivers] [AOTC Porcelain War]
- **The music tools:** `letitedit_soundtrack` arranges one song around the project (cut on bar lines, hits landed and
  measured, protected ranges ducked, drop-outs); `letitedit_fit_music` cuts a song to a length or to cut points;
  `letitedit_music_make` writes an instrumental to a description; `letitedit_library` lists the music on this PC. Use only
  music the person can publish. Parameters: see letitedit_guide('<tool>'). [GEN]
- **Log pictures by energy and motion:** what moves, how fast and which way, the peak moments, and for a
  transformation the before, the stages and the after. Check: every candidate shot has an energy note.
  [ITE CdyTIng0M8Q 09:17] [GEN]
- **Purpose line:** "From [before] to [after]", or "the feeling of [X], rising to [the peak]". Check: the critic
  names the change or the peak from the render. [GEN]

## 2. Structure options
| Shape | Choose when | Avoid when | Tag |
|---|---|---|---|
| Build and release: rising intensity to a peak, then a release | a highlights or energy reel | one level of intensity from start to end | [ITE eXUH3Z5ZntE 11:46] |
| Transformation: before, the work in stages, the reveal, after | a visible change | the after doesn't visibly differ | [FEP 4d] |
| Greatest hits: a short run of best moments (about 30 s) | a recap, an intro, an ending | the whole video with no arc | [AOTC MI] |
| Time-sculpted progress: jolts cut from one long locked-off shot | a long process filmed static | handheld or moving footage | [ITE A2RYo1xNSA4 03:24] |
| Elliptical: one continuous sound across jumps in time and place | compressing a period (a season, a courtship) | the exact order matters | [AOTC Hamnet] |

Check: the plan names the shape; the render's energy curve (cut rate, motion, music loudness) matches the planned one.

## 3. Pace profile
- **Build and release: the music's energy sets the gear.** The intro sets the tone, the build speeds the picture up,
  the drop or chorus carries the peak, the outro releases. Escalate any repeated device and give the montage an arc
  that completes. Not: one pattern from start to finish. Check: shot rate and motion rise toward the planned peak,
  which sits in the music's high point. [ITE eXUH3Z5ZntE 11:46] [ITE 4s7WdcyV1H4 12:26]
- **Release before the peak:** a held shot, a drop-out or a breath just before the reveal makes it land. Check: a
  slower stretch or a music drop sits in the few seconds before the main peak. [ITE D2iBdbNej78 06:35] [AOTC MI]
- **Short bursts:** real action is exciting in bursts; cut long takes down to their best seconds. [AOTC TGM]
- **Vary the cut patterns:** cuts on bars, a few instrument hits, some held shots; not a cut on every beat. Check:
  the cuts are not nearly all on beats; at least two patterns are used. [ITE xhJLcy8Kzl4 23:09]
  [ITE 4s7WdcyV1H4 00:01]

## 4. Sound
- **Cut on bars and phrases; hit on instrument events:** picture changes on bar lines and phrase starts; a few
  distinctive musical moments get a picture moment each (a kick on an impact, a swell on a wide reveal, the chorus on
  the after). Check: `letitedit_soundtrack`'s measure shows each planned hit landed (its measured timing error) and
  joins on bar lines. [ITE 2aux2Y9-4m8 07:41] [ITE xZnHgyeZlsU 26:09]
- **Hard hits a hair early:** an impact sound on a cut sits about half a frame before it. [AOTC Dune]
- **Let real sounds punch through** at key hits (the hammer, the door, the splash) by protecting them.
  [ITE 2aux2Y9-4m8 07:41] [GEN]
- **End on the music:** the track's real ending, a ring-out, or a hard cut to black on the beat; never a fade from
  mid-phrase. Check: the last music segment is a resolving phrase or a cut aligned to a beat.
  [ITE xhJLcy8Kzl4 16:16] [ITE xZnHgyeZlsU 26:40]

## 5. Text and graphics
- **Minimal text:** before and after labels, a progress counter ("Day 1" to "Day 30") as the device that pulls viewers
  to the end, an occasional name or place. Not: captions over a wordless montage. Check: the counter only moves
  forward. [JH 15:51] [AOTC GNIP]
- **Comparisons:** a split screen, or a wipe between matched before and after frames that moves with the action.
  [AOTC Skeleton Crew] [GEN]

## 6. Shot choice and b-roll
- **Matched before and after views:** the same angle, framing, lens and height for the reveal; find the best-matching
  pair with `letitedit_search` (the before frame as the example), or request a pickup. Check: the critic sees the two
  frames side by side and confirms they compare. [GEN]
- **Match the camera, not the result:** `letitedit_match_shots` can even out exposure and white balance between shots,
  but never grade the after to look better than it was: keep the changed subject out of the measurement, or leave
  the after untouched. Check: the after's colour in the render matches its source. [GEN]
- **Evidence of effort:** stages, hands at work, time passing (light, a clock, piles of debris), so the change feels
  earned. Check: each big time skip shows a change on both sides. [FEP 4d] [ITE A2RYo1xNSA4 03:24]
- **Images:** impressionistic and textured, revealing more of the place and activity as it goes; motion matched across
  cuts; jump cuts inside moving shots work on music. [AOTC TGM] [ITE A2RYo1xNSA4 01:48]

## 7. Openings and endings
- **Open on a chosen first image after the fade-up,** or tease the after for a moment when the process is the draw;
  withhold the after when the reveal is the draw. Check: the plan says which, and why. [AOTC TGM] [JH 16:18]
- **Land the reveal on the music's biggest moment,** hold it long enough to look, then end soon after on the track's
  ending. Check: the reveal cut sits within a frame or two of its planned musical event. [ITE 2aux2Y9-4m8 07:41]
  [GEN]

## 8. Gate settings
| Check | Long | Short |
|---|---|---|
| `cuts_per_min`, `longest_static_s` | off (the music sets the tempo) | advisory |
| `visual_change_first3s`, `first_speech_s`, `silence_first3s_s` | off | advisory |
| `silent_share` | advisory | advisory |
| `frame0_not_black` | off | on |
| `tail_silence_s` | advisory (a ring-out) | on |

Loudness: web -14 LUFS, true peak <= -1 dBTP [GEN]; also run `letitedit_soundtrack`'s measure (true peak, hits and
joins as rendered). Critic questions: does it rise and release; does the reveal land on the music; do the before and
after compare fairly; does the music end resolved?

## 9. Common failures and how to check
| Failure | Check | Tag |
|---|---|---|
| Wallpaper: one track laid from start to end, faded out | the music has internal edits and a resolving ending | [ITE xhJLcy8Kzl4 13:52] |
| A cut on every beat | the share of cuts on beats; the patterns vary | [ITE xhJLcy8Kzl4 23:09] |
| No arc | rate and motion rise toward a peak | [ITE eXUH3Z5ZntE 11:46] |
| Before and after don't compare | the frames side by side | [GEN] |
| The after graded up | the after's colour matches its source | [GEN] |
| The reveal buried in a busy bar | the reveal on its planned event, with a breath before | [ITE D2iBdbNej78 06:35] |
| A mid-phrase ending | the last music segment resolves | [ITE xhJLcy8Kzl4 16:16] |
| A device repeated without escalation | letitedit-craft's repetition ledger | [ITE 4s7WdcyV1H4 00:01] |

## 10. Evidence strength
Medium. Cutting to music is well covered by professionals: Inside The Edit's music lessons (bars, phrases, instrument
hits, resolved endings) and Art of the Cut (music first in Porcelain War, half-frame-early hits in Dune, action in
short bursts in Top Gun). There is no dedicated montage lesson and nothing on transformation videos: matched
before/after views, honest grading of the after and progress counters are [GEN], and hit tolerances are untested.
