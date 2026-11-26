# Podcast clip, split screen: the recipe

A vertical clip (20-60 s) cut from a conversation - a podcast, an interview, two people on a couch. Both faces stay
on screen in two equal panes, one above the other; the captions sit on the seam between them, each person's words in
their own colour, so a muted viewer always knows who said what. Calm on screen: the words and the faces are the show.
The interview rules in letitedit-modes (interview-podcast) come first: an excerpt stands alone, its meaning stays the
speaker's, everyone is named. Evidence tags are explained in letitedit's `looks\SOURCES.md` (optional reading).

## 1. Pick the excerpt
- One thought, self-contained: no dangling "it/that/he", no "like I said" [modes]. Start on the strongest line or a
  question the clip answers [EDS: strongest quote in the first 3 s]; end on the punchline or the line where the
  voice resolves, then cut [EDS, modes]. `letitedit_words` and `letitedit_search` find it.
- Never join parts of different answers into a new sentence or drop a "not" [modes]. Laughs and the breath before an
  answer stay.

## 2. The layout
- Make a vertical project (1080x1920) with the excerpt on the main track, then split it:
  `letitedit_reframe(project, keep=['face'], offers=['split'], offer_scope='item', apply=True, choose={'*': 'split'})`.
  Two equal stacked panes of 1080x960 [CPD]; the person on the left of a wide shot goes on top. Check the plan's
  coverage: both faces in their pane in every frame (`letitedit_check_frames`).
- Keep the panes stable for the whole clip [CPD: a change every few seconds reads as chaos]. A long solo stretch may
  switch to one tight crop of the speaker and back - at most a few layout changes per clip [CPD].
- No zoom punches on a split: a zoom moves the panes.

## 3. Captions in each speaker's colour
- `letitedit_speakers(files=[source], count=2, words=True)` labels who says each word (name the ids). Split the
  timeline's words (`letitedit_words(project=...)`) by speaker, then one caption track per speaker:
  `{op: captions, track: 'Captions - <name>', cues: [{start, end, text, words: [[w, t0, t1], ...]}], animate: pop,
  style: {fill: speaker_N, highlight: speaker_N}}` - colours `speaker_1` (yellow) for the first voice, `speaker_2`
  (cyan) for the second. Short cues: about 2-5 words, a new cue at every change of speaker and every pause over
  0.4 s.
- On the seam (`position: 0.5`), sentence case, Figtree ExtraBold with a dark edge, about 6.5% of the height [BLZ].
  Never in the bottom fifth [CPD].

## 4. On screen
- `title_bar`: the clip's topic or question, seven words or fewer, above the top face for the whole clip; it is
  also the hook text (apply the hook with `text: null`).
- `name_tag`: each person's name in their pane at their first words, 3-5 s [OVS, modes]. Top pane about
  [0.27, 0.42]; bottom pane about [0.73, 0.62] (the bottom corner is under the apps' buttons).
- `reaction_sticker` for a real laugh or gasp, in that person's pane; `key_line` at most once; `cutaway` rarely,
  never over a laugh, a reaction or the last line.

## 5. Sound
- The voices are the mix: level both speakers (`{op: level}`), room tone in the gaps, no music under talk [EDS,
  modes]. Effect sounds only for the name tags and the key line, quiet (`sfx.gain_db` -18).

## 6. Hook and ending
- The strongest line first; the title bar frames it. End on the last word of the punchline or the resolved
  sentence, at most a second after it [JH, modes]. No "follow for more" card.

## Avoid
- Panes that jump every few seconds; a face cut off at the seam; captions over a face or in the bottom fifth.
- One caption colour for everyone, or colours that change for the same person.
- Quoting words that weren't said, or a title that claims something the speakers didn't.
