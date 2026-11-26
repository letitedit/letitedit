# Podcast episode: the recipe

A 16:9 YouTube episode of a conversation (10-90 min): two or more people talking, cut like a multi-camera show -
the picture on whoever is talking, a reaction when it says something, the wide shot to reset - with a cold open,
names, chapters and the talk left to breathe. The interview-podcast playbook in letitedit-modes comes first: never
change what someone meant, keep the real reactions, no reordering that changes an answer. Evidence tags are explained
in letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-podcast-episode}`; the look on every footage track; `letitedit_speakers` (or a pitch check
per word when one microphone merges the voices) for who talks when; the cut as main-track pieces with their angle;
`{op: fx}` per chapter; `letitedit_bin` for `chapter:` markers; `{op: score}` with the theme on intro, outro and
chapter breaks only; `letitedit_hooks` for the cold open.

## Angles from one wide camera
- Each piece of the main track is one angle: the wide (the take as shot), or a single on one person - the same take
  punched in on them (`effects: [{zoom: 1.8, focus: [x, y]}]`, x/y their face as fractions of the frame; a punch-in
  makes a "fake" angle from a high-resolution wide [BBX]). With real cameras, cut between them the same way.
- Show who is talking, close, for most of their turn [AVE]; cut on nearly every speaker change [BBX].
- The wide for energy, crosstalk and laughter; singles for stories and answers [BBX]; the wide to re-establish the
  room at the start and after a topic change [AVE] (`reset_push` on it).
- A reaction shot when the listener's face says something - not for every "mm-hm" [AVE].
- A long monologue alternates close, medium (a smaller punch-in) and wide, so one face isn't on screen for minutes
  [AVE].
- No source gives a switching rate [AVE]: the picture follows the talk.

## Structure
1. Cold open (15-60 s): the best exchange from later, with its own setup and payoff [AVE], a `coming_up` label.
2. Intro under 20 s [BBX]: `show_title` on the wide, the theme under it.
3. Chapters, one per topic (the first at 0:00, at least three, each at least 10 s) [AVE]: a `chapter` card on the
   wide and a `chapter:` marker; the theme for a few seconds between chapters [SLC].
4. The close: the natural goodbye, the theme, out. An end screen, if any, in the last 5-20 s [AVE].

## Pacing
- Take out dead air, false starts and repeats; keep the thinking pauses (`editing.max_pause` 0.8) - an hour usually
  tightens to 45-50 minutes [BBX].

## On screen
- `name_tag` the first time each person talks on their own shot, and again after about 15 minutes [AVE].
- `pull_quote` at most once per chapter, the exact words; `cutaway` only when there's a shot of the exact thing,
  never over a laugh or an emotional answer.
- Captions as an SRT with speaker changes marked [AVE]; clips cut for Shorts get their own style (podcast-split).

## Sound
- Voices first, levelled to each other; no music under talk; the theme on the intro, outro and between chapters
  [SLC]. Export -14 LUFS for YouTube; -16 LUFS for podcast apps [BBX, AVE].
- Angles cut from one recording are one continuous sound: score with `{op: score, level_voice: false}` (levelling
  clip by clip would change the volume at every angle change); level the voices on the recording itself or per
  microphone track instead.

## Look
- `look`: clean and warm, natural skin; one grade for every angle so the cuts match [BBX]. Manrope for names and
  chapters, Fraunces italic for quotes.

## Avoid
- Cutting on every word or every "mm-hm"; reactions that weren't to that line.
- Music under the conversation; graphics over faces.
- Shortening an answer so it says something else.
