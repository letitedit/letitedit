# A song added when posting (letitedit-sound section 13)

Read in full when the brief's `Music:` is `trending`, a `song:` line names a phone-app sound, the person says they'll add
the song when posting, or the project has a 'Song (not in the export)' track. Tool: `letitedit_song`. Calls are in order below.

- **Pick the part yourself; don't ask, and pick one a person can find.** `letitedit_song(mode='parts', song, length_s)` lists starts with energy,
  tempo and `entrance_db` (how much louder that bar is than the one before). A quarter-second offset can make a montage's picture hits feel late or early
  [OURS; heuristic]. The apps' help pages describe dragging a control with no typed time, so nobody can be asked for 0:43.2.
  In order: (1) **the song's very start,** by dragging all the way back, the one position that should be exact (reasoned from those pages; no phone has tried
  it). Prefer it whenever the opening can carry the video, even over a stronger part later, and build the picture to it. (2) If the opening can't (a long quiet
  intro), a start the ear can find: a large `entrance_db`, a drop, the first hit after a gap, with the video's first big picture hit on it. Say plainly in the
  closing message that this one is lined up by eye and may miss. Don't choose a start in the middle of a steady groove: nothing tells a person where it is.
- **One uncut piece.** A phone app plays a song straight through from one point [YT, TikTok and Instagram help]. So no
  `letitedit_fit_music`, `letitedit_soundtrack`, `score` or speed on it. `letitedit_song(mode='place', project, song, start_s)` lays it
  on the track 'Song (not in the export)' and gives its beats and downbeats in timeline seconds. Place it again when the picture's
  length changes. The track stays muted; hearing it isn't the point, the preview does that.
- **Montage or anything music-led:** place it first and cut the picture to its bars (FEP drivers). The cuts are what lands on the beat [OURS].
- **`land` is the last edit, every time.** `letitedit_song(mode='land', project)` once nothing else will change on the timeline and before `check` and the export: a shot's length rounded by hand drifts off the beat by a frame or two per cut [OURS], and any trim shifts what was on a beat. `check` reports the result.
- **A talking head: don't force visible beat cuts.** Land scene events or existing moves on beats where useful.
  Otherwise use only moves already justified by the edit (`letitedit_song(mode='land', project)`, inside pauses).
  Never clip a word to hit a beat. Don't add punch-ins for the beat's sake or hold back a talking head because
  the beat doesn't show [OURS].
