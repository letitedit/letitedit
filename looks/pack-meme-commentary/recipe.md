# Meme commentary: the recipe

A vertical comedy edit (15-45 s) in meme format: a setup line on a white bar over the clip ("me after fixing the A/C
once:"), the clip playing out, and the joke landing hard - a freeze frame with a record scratch, a snap zoom with a
boom, a reaction emoji, meme text - then straight on or out. The joke is the person's real moment; the edit only
times it. The letitedit-shorts rules come first (open moving, a payoff, end on it), and the story still has to read
with every effect off. Evidence tags are explained in letitedit's `looks\SOURCES.md` (optional reading); most numbers here are general practice [GEN]:
no checked source describes meme timing.

Tools: `{op: look, id: pack-meme-commentary}`; `{op: add_track, name: B-roll, kind: video}` before the captions;
`{op: captions, from_speech: true, animate: pop, chunk: short}`; freeze frames as main-track items
(`{op: insert, track: V1, item: {freeze: {clip, at}, len: 1.2}}`, at the cut where the moment happens); one
`{op: fx}` batch per bit; `{op: popups}`; `letitedit_hooks` + `{op: hook}` (its text drawn as the caption bar).

## Structure: bits
- A meme edit is one to four bits. Each bit: a `setup_bar` line (the situation, lowercase, 12 words at most - never
  the punchline) -> the clip plays clean -> the punchline lands -> out or on to the next bit.
- The punchline treatment, two or three things within half a second, rotated between bits (never the same pair twice):
  - freeze frame + `scratch_stop` (the music cut on the same frame) + `impact_text` ("YEP. AGAIN.")
  - `snap_zoom` on the face or the thing (with its boom) + `reaction_emoji`
  - `shake_hit` + `fail_sting` on a real fail
  - `rimshot` or `crowd_laugh` after a pun or a self-own (after the words, never under them)
- Time jumps the joke needs get a `time_card` ("9 DAYS LATER", only true times: the footage's dates or the person).
- End on the last punchline, out within half a second [JH]; a `win_sting` if the ending is a (small) win.

## Pacing
- Tight talk (`editing.max_pause` 0.3) except the beat before a punchline - leave it [ITE].
- Bursts, not a stream: the setup plays clean, the joke is loud, then quiet again. At most three flashes a second
  [RES].

## Text
- `setup_bar`: dark Arimo on a white band under the app's top bar, lowercase, the situation in the viewer's voice
  ("me", "when you").
- `impact_text`: Anton capitals with a black edge, one to three words.
- Spoken captions: plain white Arimo with a black edge, 2-4 words, low (66%); the bar is the joke's text, not the
  captions.

## Sound
- The stings are the punctuation: boom on a snap zoom, scratch on a freeze, bonk on a shake, trombone on a fail,
  rimshot or a short laugh after a line, a slide whistle on a time card, ta-da on a win (`sfx.gain_db` -10).
- Music optional (quirky or playful, 22 dB under the voice); it stops dead on the scratch and comes back after.
- Word pop-ups that fire by themselves (again, broken, what, money, illegal) come from `{op: popups}` - one each
  per video.

## Look
- As shot: no film grade. White bar, black text, Anton capitals, a purple time card in Bangers.

## Avoid
- Explaining the joke in text; putting the punchline on the setup bar.
- Stings over the speaker's words; a laugh track on something that isn't funny.
- Memes that mock someone who didn't agree to it; other people's clips without the right to use them.
