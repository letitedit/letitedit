# Choosing music

Read on demand from letitedit-sound section 2. The conventions below come mostly from one teacher (Inside The Edit)
plus a few feature-editor examples: use them as search words and starting tags, never as rules. The brief's `feel`,
the story plan and a `reference` video override them.

## 1. Tone conventions (search words)
| Intended feeling | Conventions seen in the library | Source |
|---|---|---|
| Urgent, tense opening | percussive, minimal, building; often minor; tight framing and faster cuts with it | [ITE esNXgCJh-yk 08:47-10:30] |
| Contemplative, poetic opening | ambient, subtle, atmospheric; can be romantic and major; longer takes with it | [ITE esNXgCJh-yk 10:52-12:10] |
| Sad reflection | slow, minor | [ITE ZcIVl01h14Y 12:34] |
| Exciting or funny | faster, major; happy songs at the top told an audience it could laugh | [ITE ZcIVl01h14Y; AOTC Invite] |
| Tender reflection | strings or piano | [ITE xZnHgyeZlsU 31:16] |
| Depth, grandeur / "the beautiful moment" | low strings / high strings | [ITE KAO0n3C0kAg 23:07] |
| A small doubt | a shift from major to minor | [ITE D2iBdbNej78 02:46] |
| A world of its own | unusual textures (bowed metal, an "underwater" orchestra, a psychedelic sound) | [AOTC MI; AOTC Dune; FEP drones] |
| Support without a melody | a sustained tone or drone: darker for tension, lighter for peace | [FEP drones; AOTC Hamnet] |

The research lists these sources for the conventions as a group; the split per row is our reading of it
(topic-music-sound-transitions.md F6, F16). Confidence: low to medium.

The same documentary scene was cut to an urgent dance track and to a stately orchestral piece: both right, for
different intended feelings [ITE KAO0n3C0kAg 16:28-17:21]. A reflective childhood memory should not sit on hard rock
[ITE FOJhAl9IyPg 06:30].

## 2. Audition for structure, not only tone
A track with the right chords can still fail [ITE KAO0n3C0kAg 19:11-19:41; ITE xZnHgyeZlsU 27:08-28:35]:
- the beat arrives where the scene is reflective (30 s in, say);
- the middle is busy or intense under the talk;
- it never turns where the story turns, or it turns where the story doesn't;
- it has no mystery when the scene needs wonder (a lovely track can be wrong for the place and the person)
  [ITE gwyneGrX9Jw 03:58-04:12].
Lay the song's sections and energy (`letitedit_soundtrack(mode='song')`, or `letitedit_footage(<song>)`) against the
section map. Prefer a song whose energy rises toward the section that needs it; check its own ending (`ending.natural`
in the analysis) when the video should end on the music.

## 3. Practical filters
- **Under talk:** instrumental, or a sung track only in gaps and music-only stretches; low melody density under words.
- **Beat strength:** `letitedit_library` reports strong / clear / weak. Hits and bar edits need a clear beat; a weak or
  unsteady beat makes soundtrack cut in coarse units with long crossfades (it says so).
- **Length:** a song shorter than the music span loops; soundtrack avoids back-to-back loops by default
  (`repeat.loops: false`) and reports when it has to relax that.
- **Famous songs:** a song whose identity overpowers the footage (or that a platform will mute) is a poor bed even when
  it fits the mood [GEN]; the feature editors' "Star Wars, not Star Wars" temp rule points the same way [AOTC Skeleton
  Crew] (our reading, not their claim).
- **When nothing fits:** leave the section dry (if no track accompanies it, it may need none) [AOTC Invite], write a score
  for the cut (SKILL section 2a), or make a bed with `letitedit_music_make(description, length, bpm, key, hits)`: instrumental, made on this PC, licence noted in
  its result; describe instruments, mood and energy, then listen.

## 4. Licences
- Record source and licence on each track: `letitedit_note(file, text='licence: CC0, Internet Archive', tags=['licence:cc0'])`.
- Clean by construction: the CC0 / public-domain library that ships with letitedit (Add music lists it with genre,
  mood, length and licence), YouTube Audio Library, `letitedit_music_make` and `letitedit_music_write` output, the person's own licensed folder.
- Check stock pages: a Pixabay track marked "Content ID Registered" will be claimed on YouTube [OURS]. Cutting a whole
  edit to music you can't license is the trap one documentary editor calls a no-no [AOTC Porcelain].
- Never another creator's music or footage.

## 5. Choosing a track from the library (letitedit-sound section 2b)
- **What a search shows.** `letitedit_library('music', query)` matches the words against each song's title, artist, genre and mood; a
  line gives the path, the measured tempo and length, then genre; mood, artist and licence. `bpm_min`, `bpm_max`, `min_length_s` and
  `max_length_s` narrow by the catalogue's tempo and length (a catalogue tempo can sit at half or double the felt one: the measured tempo
  on the line is the beat finder's). A clean install carries about 30 songs, so an empty query lists them all, and the choice
  is still made against the feeling and the section map, not by the first hit; with nothing that fits, the other route (section 2) is open.
  [OURS]
- **On-demand songs.** When `on_demand` is in the reply, the same search lists about 750 more songs there, marked as such, with a catalogue tempo, genre, mood, artist and
  licence. They come down once when used: pass `ondemand:<id>` as `song=` to a fit tool, or `letitedit_library(kind='music', fetch='ondemand:<id>')` for a path
  to put on a track. All are CC0 or public domain, and the song lists where it came from. Choose among all of them the same way; written music stays just as open. With no internet, the note says so
  and everything on the PC still works. [OURS]
- **Tone conventions are search words, not rules** (percussive and minor for urgent, ambient for contemplative,
  strings or piano for tender); one scene works urgent or stately by intent (section 1 above)
  [ITE esNXgCJh-yk 08:47; ITE KAO0n3C0kAg 16:28].
