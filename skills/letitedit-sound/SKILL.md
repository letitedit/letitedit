---
name: letitedit-sound
description: Score and mix a letitedit edit - music written for the cut (letitedit_music_write) or chosen for the intended feeling and re-cut to the story (soft start, the beat's entrance, beat out before the end, edits on bars, a resolving ending), music and speech taking turns (peaks in the gaps), entrances and exits on story moments, dry stretches and one key silence, hard hits half a frame early, natural and protected sound (machines, punchlines, ambience) kept audible, sound bridges, few SFX, and loudness by deliverable (web -14 LUFS / -1 dBTP, podcast -16, broadcast -23). Tools - letitedit_music_write, letitedit_soundtrack, the score op, Add music. Use whenever music, sound or the mix is touched, or on notes like 'the music is too loud', 'more energy', 'give the reveal room', 'less piano', 'more hopeful', 'end it sooner'.
metadata:
  version: 0.5.0
---

# Sound: music, natural sound and the mix

**The decision:** what the viewer hears in each section and why: who leads (speech, music or natural sound), where
music enters, answers, drops out and resolves, which sounds stay untouched, and the delivery loudness.
**Inputs:** the brief (`driver`, `mode`, `feel`, `protected`, `must_keep`, `deliverables`, `reference`), the story
plan's sections and key lines, word times (`letitedit_words(project=...)`), the song's analysis.
Elsewhere: letitedit-craft (driver order, pacing gears, sync islands, the repetition ledger, the revision levers),
letitedit-fine (dialogue joins and J/L timing inside a scene), letitedit-finish (speech cleanup: noise, rumble,
de-ess, before the mix; FINISH-1b: a clip's `speed` changes the pitch of its own sound). Every number is a default to
tune. Calls: references/tool-recipes.md. The tools' details, the evidence and why some rules hold:
`references/manual.md`.

## New video choice fields
`Style:`, `Look:`, `Theme:`, `Captions & pace:`, `Music:` (`library`, `own`, `made`, `trending`, `none`; the older `ai`,
`written` and `backdrop` mean `made`), `Music file:` and the older `song:` line mean what the router (`letitedit`, "New
video choice fields") says, the one place they are defined; they can be recorded in `brief.json` without changing their meaning.

## 1. The sound map (before any music)
Per section: driver; music or dry, and what the music accompanies; energy (low / mid / high); the entrance and exit
moment; the key lines whose gaps the music answers; protected ranges; the one silence, if any. Keep it in the story plan's
sections or a `sound:` journal note.
- **Music only when it accompanies something real;** if no track genuinely fits, the moment may need none; never
  music to tell the viewer what to feel. Not: spectacle or montage the audience expects scored. Check: every section
  has a music decision with a reason; music-free ones carry `dry: intentional` [AOTC Invite; AOTC MI; FEP timing].
- **The driver sets the order** (letitedit-craft): dialogue-led = lock the words, then score; music-led montage =
  build the track first and cut picture to it; sound-led = the sound map first. Check: the journal's build order
  follows the brief's `driver` [FEP drivers; AOTC Porcelain].

## 2. Where the music comes from
**Two routes, your own choice per video:** write it in code for this cut (2a, `letitedit_music_write`), or real music:
a library track (2b, `letitedit_library`), one made with `letitedit_music_make`, or a file the person gave. What the
person gave or the brief fixes comes first (their own song, a Look's or style's music rules, a cut to a song). A score
that keeps failing its check is a reason to change route. Writing works on any PC; the library holds only what this
PC has. Every route lands on the Music track. [OURS]
On every route:
- **Pick for the intended feeling, then audition for structure;** never "it sounds nice". Lay the song's energy and
  sections (`letitedit_soundtrack(mode='song')`) against the section map; reject a beat under a reflective beat, a busy
  middle under talk, a track that can't turn where the story turns. Check: the plan names the feeling and why this
  track fits; the reviewer answers "has the music shifted the meaning?" [ITE 2aux2Y9-4m8 02:33; ITE KAO0n3C0kAg 19:11;
  ITE gwyneGrX9Jw 03:58; ITE FOJhAl9IyPg 06:30].
- **No howls or whistles under speech:** a held, pure, narrow tone (whistle- or theremin-like lead, a whine, a feedback
  howl) cuts through talk even when the music is quiet. When `letitedit_check_audio` or the export's checks name a
  stretch (`tones`), pick another section or song, unless the Look or the person asks for that sound. A section picked from any song but the
  library search's can still hold one; ordinary played or sung notes don't count (how the library and checks find
  them: the manual).
- **Licence before taste:** source and licence on every track (`letitedit_note`, tag `licence:<id>`). Safe: the free CC0
  library Add music lists, YouTube Audio Library, the person's licensed folder, `letitedit_music_make` and
  `letitedit_music_write`. A Pixabay page marked "Content ID Registered" gets claimed. Check: every music and SFX file
  on the timeline has a licence note [GEN; OURS]; when the start message says code writes the licence notes, it does so for letitedit's own
  library only: a song or sound from anywhere else still needs yours.

## 2a. Write a score for the cut
**When:** the route is a score written for this cut (`Music: made` and you write it, or `letitedit_music_write`). **Do:**
read references/written-music.md in full before the first score, its last section ('Writing for the cut') and the
format and order of work above it.

## 2b. Choosing a track from the library
**When:** a library or on-demand song (`Music: library`, or an automatic choice that may pick one). **Do:** read
references/music-choice.md in full before choosing (section 5: what a search shows, on-demand songs, tone conventions
as search words). Section 2's rules hold here too.

## 3. Shape the track: never wallpaper
- **Re-cut the song to the story:** a soft start (loop or borrow a quiet section), the beat entering on a story moment
  rather than bar one, the beat out before the end, sections reordered, edits on bar lines (phrases run 4, 8, 16 bars);
  in dialogue-led scenes the music adapts to the picture. Not: a performed or diegetic song that plays intact. Check:
  no dialogue scene longer than one phrase sits on one uncut track faded out at the end; every join in soundtrack's
  plan is on a bar line [ITE xZnHgyeZlsU 24:49; ITE xhJLcy8Kzl4 13:52].
- **An arc under the story's arc:** an internal jump (big to dreamy) is motivated by a picture change or a gap, or
  moved [ITE xhJLcy8Kzl4 15:15; ITE bCVeyUFGxi8 05:17].
- **End deliberately:** the song's own resolving phrase, a hard stop on a downbeat as the picture cuts to black or to a
  wide, or the last image riding the tail. A fade only from a phrase end with the level already low; never a fade from
  mid-phrase at full level. Vary endings between sections. Check: soundtrack's `ending` came out `song` or `stop` (a
  fallback to `fade` is warned: move the end or the last hit until the ending fits); the last 3 s of
  `letitedit_check_audio(every_s=0.5)` decay or cut on the beat [ITE xhJLcy8Kzl4 16:16; ITE KAO0n3C0kAg 21:58].
- **Let an emotional cue finish:** lengthen the picture (hold or reuse the reaction) rather than chop the phrase.
  Check: the picture runs to the phrase's end [AOTC Top Gun; AOTC GNIP].

## 4. Duet: music and speech take turns
- **Peaks go in the gaps:** each scene's 3-4 biggest musical events (a section entry, swell, chord change, drop,
  chorus) in the gaps between sync islands, best the gap right after a strong line, so the words land and the music
  answers; the next word starts after the phrase ends (widen the gap with picture rather than chop the phrase); don't
  align every cut. Not: dry scenes; music-led montage; voice-over with no gaps (keep the bed low and steady, change it
  at section turns [GEN]). Check: each planned event starts inside a gap (soundtrack's hits list); after every key line
  a gap with a music event; music under speech steady, rising only in chosen gaps
  (`letitedit_check_audio(stems=True, every_s=0.5)`) [ITE 2aux2Y9-4m8 03:51-06:29; ITE xhJLcy8Kzl4 09:30-10:12; AOTC
  Invite; AOTC Dune].
- **Ducking can't rescue a peak under speech:** a ducked chorus still fights the words; move the peak into a gap. Beds
  under talk carry little melody; never sung vocals under speech [ITE 2aux2Y9-4m8 05:39; ITE xhJLcy8Kzl4 07:52].
- **Depth:** music about 18 LU under the voice (`talk` -18; a written score starts at -14:
  references/written-music.md; a measured Look's stem LUFS win: references/learned-sound.md), the dip done before the first word, back up only in the
  gaps it answers; taste moves it a few LU. Check: `letitedit_check_audio(stems=True)` and a listen [OURS; ITE
  gwyneGrX9Jw 16:28].
- **Answer a line only by choice:** the shipped defaults keep music dipped through every gap under 4 s (`merge_gap`):
  keep `merge_gap` at 4 s (lower values swell in every ordinary pause). For each chosen gap,
  `{op: score, answer: [...]}` (a pause id from the score's `gaps`, a time, or `{after: '<the line>'}`); `answer: 'auto'`
  picks pauses of 2 s or more after a sentence, 20 s apart; on a soundtrack-built track, its sections and hits instead. Answer
  sparingly: the few gaps after key lines, a smaller rise (`levels: {swell: -8}`, about 10 dB over `talk`) unless the
  scene is music-forward. Check: answered pauses rise and are back down before the next word
  (`letitedit_timing(project, view='sync')` lists each gap's rise in dB); music under the words stays flat [OURS; GEN].

## 5. Entrances, exits and the one silence
- **Enter before the first word or in the gap after the first line;** never starting under a sentence. A cinematic
  opening layers: natural sound first, a sound as its source appears, music last. Bring the beat or a new layer in on
  a story moment. Not: music-led edits, a hook that must hit at once. Check: music onset vs word times; no onset inside
  a sentence [ITE xhJLcy8Kzl4 05:08; ITE gwyneGrX9Jw 10:28].
- **Start or stop music only on story markers:** stop it to expose a reaction, a punchline or suspense; start it to
  mark a development. Long-form: no wall-to-wall music; switch it off somewhere to reset; neighbouring sections at
  different music energy. Check: every start and stop within about 0.5 s of a marker [GEN tolerance]; music coverage
  under 100% in long-form [FEP timing; FEP trailer; AOTC MI; AOTC GNIP].
- **One key silence,** the strongest, scarcest device: once per stretch where it is needed most; approached from the
  loudest passage; the first sound after it gentle; no other silences in that scene and its neighbours (sound design
  under the neighbour). Pauses inside a performance breathe: different. Never digital silence under picture by accident
  (room tone). Check: `letitedit_check_audio` quiet stretches show one deliberate silence, loud before it, none nearby
  [AOTC Porcelain; AOTC Invite; ITE D2iBdbNej78 06:35].

## 6. Hits and stingers
- **A few deliberate hits** tied to on-screen events (a kick on an impact, a swell on a wide reveal, the chorus as
  someone finishes and smiles); not every onset, not one recipe throughout (a montage locked to one instrument delights
  once and bores by the fourth). Check: each hit has a reason; no identical pairing 3+ times (repetition ledger)
  [ITE 2aux2Y9-4m8 07:41; ITE 4s7WdcyV1H4 00:01].
- **Measure sync, don't guess it** (`letitedit_timing(project, view='sync')`; read `beat_confidence` first, weak on
  ambient or busy tracks): in music-led stretches most picture events within about a frame after the beat (a viewer
  preferred on-beat cuts 3 to 1); where the music returns after a gap or a break, cut to the next shot on that return
  [OURS].
- **Hard hits land half a frame early:** a bang, stop or downbeat on a picture cut gets its transient half a frame
  before the cut (17 ms at 30 fps, 21 ms at 24): hit `at` = cut minus half a frame, `tolerance_ms: 15`; a measured
  landing from one frame early up to the cut, never after. One editor's 35 mm rule, untested at 60 fps [AOTC Dune; GEN
  tolerance].
- **A stop before the button:** a `break` hit (the music stops just before it) exposes a punchline or reveal; the music
  returns on the next phrase or the scene stays dry; not on every joke. Check: the stop lands just before the line's
  first word [FEP trailer; AOTC MI].

## 7. Natural and protected sound
- **Natural sound is first-class:** the machine that proves the fix, the tool, the laugh, the place. Keep short
  on-location lines that back up the story; sync effects to their visible sources; ambience under every shot without
  dialogue; replace windy or clipped camera audio with clean atmos from the same place. Not: a stylised music-only
  montage. Check: a picture-off listen of each sound-led scene (`letitedit_check_range`): a scene that works with the
  picture off is strong [ITE gwyneGrX9Jw 09:46; ITE urCAMKTsc6o 13:33; AOTC Porcelain; AOTC GNIP].
- **Protect what carries meaning:** the brief's `protected` ranges, `must_keep` sound moments, a punchline and the laugh
  after it, a proving sound: each as a timeline range to soundtrack `protect` (`duck_deep`: music 20 dB under the
  natural sound; `drop_out`: the music leaves and returns), or a `score` zone at `quiet` (-24). Never a music peak on it.
  Check: soundtrack's measure gives the level in each protected range; listen to each one [ITE KAO0n3C0kAg 11:33; AOTC
  Porcelain].
- **The voice clean-up** (`letitedit_fix` voice, `separate: auto` by default, deciding per clip; the whole-mix clean-up takes
  every sound but speech 11-18 dB down; no one setting serves all clips): override it
  (`separate: true` or `false`, which always wins) when the story says otherwise: a steady hum or fan the story is about,
  or ambience the brief protects, stays; a sound that is only noise goes; a clip that only talks about a machine isn't
  a clip where the machine plays. Nobody asks the person. Say which clips were protected (letitedit-finish FINISH-2).
- **Montage with nobody talking:** the shots' own sound stays under the music, up for key actions; in action, close
  shots favour detail sound, wides let the score swell. Check: listen to each key action; each is heard over the music [OURS; AOTC MI].
- **Transcribe before `score`** (`letitedit_words`): score finds speech by word times, and its voice detector (for files
  with none) missed quiet narration under work noise and left music up under it (the result's `speech_from` says which) [OURS]. Name tracks for what they carry:
  tracks named sfx, sound, foley or ambience (and music, song, score, bed), and sound-effect or music library clips on any track, are never
  treated as speech by score or captions [OURS].

## 8. Sound bridges and SFX
### Choose the function before the timbre
Match what the picture does before a pleasant-sounding library result (`letitedit_assets` or
`letitedit_library(kind='sfx')`, plain words): a similar-sounding horn is not an alarm clock, a musical bell is not
typing. Candidates to audition, never a duty to decorate every cut:

| Picture or story function | Sound candidate | Evidence |
|---|---|---|
| Photo taken, photograph freezes, white camera flash | Camera shutter; film-camera clack for an analog cue, flash crack/recharge for a flash | moderate [SFX1] |
| Text types on | Typewriter keys or a short typing burst; line-end bell only when a line finishes | moderate [SFX2]; the bell is a heuristic |
| Freeze-frame interruption, rewind, narrative reset | Record scratch or rewind, timed to the interruption | moderate [SFX3]; not every frozen photo needs a scratch |
| A visible move or transition | Whoosh matched to direction and movement duration | moderate [SFX4] |
| An object or graphic appears | Short pop at its arrival | weak heuristic [SFX5] |
| Waking up or an urgent time cue | Alarm clock, mechanical ring or electronic buzzer | moderate [SFX6] |
| Waiting or time passing | Clock ticking rather than an alarm | weak heuristic [SFX6] |
| Page turns, paper tears or crumples | The corresponding paper foley rather than a generic whoosh | moderate [SFX6] |

Start with the few events that need a cue; leave speech intelligible; check the sound against the actual action. A
generated flash effect is a designed cue, not evidence of an authentic historical recording.

### A learned reference's sound
**When:** the selected Look has `sound_profile`, a sibling `sound.json` beside its recipe, or `sound.json` among its
`measured` files. **Do:** read references/learned-sound.md in full before the sound pass.

### Every effect sound, on its purpose
- **Name its moment:** the visible arrival, caption word, cut, transition midpoint or story moment it belongs to; keep
  the `sound_target` record the tools supply (an explicit target can be passed in an `fx` item). A source's loudest
  10 ms window, through its trim and speed, must be within **125 ms either way** of that target; aim for the target
  frame, not the tolerance edge; correct an `off_target` result before export. A caption's arrival is its first visible
  export frame, which a fade or reveal, a source offset, a trim or grouped captions can move off the word's speech time. After moving the picture, check again (the record doesn't
  move the sound). A missing or unreadable target is not a pass; an older sound with no record is matched to its own `-sfx`
  graphic, else a picture or caption event within half a second: confirm what that inferred target actually is.
- **A whoosh or riser:** the build-up before its target so its **peak** lands on the cut, transition midpoint or reveal;
  the tail can run on: neither the file start nor the end of the decay is the hit. Listen to the rendered cue and its tail as well.
- **Over talking is allowed:** keep the effect on its intended moment and lower it under the voice; never move it to a
  word boundary or call its overlap with speech a timing fault; loudness from the measured speech-relative gain and the
  rendered mix check.
- **Bridge scenes with sound** when anticipation or continuity helps: the incoming line, ambience or music starts before
  its picture (J), or the outgoing sound runs over the new picture (L); the viewer must soon know where the sound belongs.
  The picture leads when the viewer must see first (the reveal, then the line). One continuous cue makes fragmented
  images feel continuous. Never two voices at once. Check: the incoming sound leads the cut by about 0.3-1 s [GEN]; the
  reviewer can name its source. `{op: split_edit, id: <incoming clip>, lead: 0.5}` makes a J cut, `lag` an L cut
  (references/tool-recipes.md 5) [FEP bridge; AOTC Top Gun; AOTC Hamnet; ITE WOX-WdXSOOc 47:27].
- **One sound per job:** never one whoosh, riser or ding for every reveal, punchline or transition; tension is a
  feeling, not an effect. SFX from `letitedit_library(kind='sfx')` or the footage, with a licence. "Less flashy" removes
  them first. Check: count each SFX file on the timeline; one file reused for the same job is a flag [ITE 4s7WdcyV1H4
  05:32; ITE D2iBdbNej78 09:30; AOTC Skeleton Crew].

## 9. Loudness by deliverable (the one table)
| Deliverable | Integrated | True peak | Tolerance | Evidence |
|---|---|---|---|---|
| Web and social (YouTube, Shorts, TikTok, Reels) | -14 LUFS | <= -1 dBTP | +-1 LU | [GEN] no platform publishes one |
| Podcast | -16 LUFS | <= -1 dBTP | +-1 LU | [RES] Apple Podcasts |
| Broadcast | -23 LUFS | <= -1 dBTP | +-0.5 LU | [RES] EBU R128 |

This table is the single source: letitedit-finish, letitedit-shorts and the gate point here, never repeat numbers.
- **Even the speech first:** `score` levels it clip by clip, and a phrase 6 dB or more off the rest of its clip (a
  second voice, a much softer line) gets its own level (`{op: level}` does only that). Don't ride levels line by line
  after it: read its `speech_levelled` changes, and set a phrase back by hand only where the softness is the
  performance (a whisper, an aside), saying so in `finish_pass.md` [OURS]. **Master once**, on the whole mix, at
  export: `letitedit_export(..., loudness=<target>, true_peak=-1)`; never per clip, and no dynamic normaliser on the
  master (a limiter is fine) [OURS; GEN].
- Check before export: `letitedit_check_audio` (speech clips near their typical level, no music spike in wordless
  stretches, no sudden dips); the export measures its own mix (`result.mix_check`), so no need to run
  `letitedit_check_audio` again after the last export unless the cut changed after it. After:
  `letitedit_measure(<file>)` loudness within tolerance, true peak <= -1 on the encoded file [OURS].

## 10. Notes from the person
"Music too loud" -> `talk` 3 dB lower, gaps kept. "More energy" -> higher section energy, an earlier beat entrance,
hits on cuts. "Less flashy" -> no stingers or repeated SFX, fewer hits. "Give the reveal room" -> stop the music
before it, swell in the gap after it, widen that gap to the phrase. "Too much music" -> dry stretches. "The ending
feels cut off" -> the song's own ending or a downbeat stop. The full lever table is in letitedit-craft. A mood note
gets two scored variants with different outcomes; the person picks [ITE xZnHgyeZlsU 27:08].

## 11. Tools
`letitedit_song` (section 13), `letitedit_music_write` (2a), `letitedit_soundtrack` (one song arranged around the
edit: `mode='song'` analyses, `'plan'` proposes with a preview mp3 to listen to, `'apply'` with `plan_id` writes it as
one undo step, `'measure'` renders stems), `{op: score}` (evens speech, then levels every Music track under it; it turns
off a track's auto-duck), Add music (the person's button: a bed, not a score: to shape it, re-score and say so),
`letitedit_fit_music`, `letitedit_library`, `letitedit_separate`, `letitedit_check_audio`, `letitedit_check_range`,
`letitedit_hear`. Two traps: soundtrack plans from the saved file (save first) and replaces the clips on its track,
Add music's included; score and soundtrack both write the music's gain keys, so one of them per music track (score
after soundtrack erases it; `{op: level}` suits either). Calls: references/tool-recipes.md.

## 12. Checks and hand-off
Listen with `letitedit_check_range`: the first 10 s (then watch it muted: same feeling?), each entrance, the gaps after
key lines, each protected range, the ending [ITE esNXgCJh-yk 14:08]. Code never listens, so write what you listened
to. Journal note `stage:sound:done`: tracks and licences, the sound map, hits, protected ranges, measured music under
speech, the export's loudness and true peak.

## 13. A song added when posting
A trending song's reach and licence come from the phone app's sound picker: the video is cut to the song, the uploaded
file has none of it, and the person adds it when posting (`letitedit_song`). A song from outside a platform's tools in the file can draw a
Content ID claim or a removal [YT].
- **When:** the person gives a song file (New video's song line, or in the chat), or says they'll add the song when
  posting. Take this route by yourself unless the song is one they may use in the file (the free library,
  `letitedit_music_make`, `letitedit_music_write` or a licence they name: a Music track as usual). Say in the closing
  message which route you took.
- **Then, and on every later edit of a project with a 'Song (not in the export)' track:** read
  references/song-when-posting.md in full: pick the part yourself (the song's very start first), one uncut piece placed
  with `letitedit_song(mode='place')`, montage cut to its bars, `land` as the last edit, and a talking head that
  doesn't force visible beat cuts.
