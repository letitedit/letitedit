# Storytime: the recipe

A vertical Short (30-60 s) of one person telling something that happened to them, to camera. The story does the
work; the edit keeps out of its way: one line at the top naming the story, calm captions on every word, slight
zooms instead of flickery jump cuts, a beat of quiet before the turn, and the end right after the payoff. Evidence
tags are explained in letitedit's `looks\SOURCES.md` (optional reading); the story rules in letitedit-craft and letitedit-modes (story-vlog) come
first.

Tools: `{op: look, id: pack-storytime}`; the look on the footage tracks (`{op: track, name: <track>, effects:
<look.effects>}`); `{op: captions, from_speech: true, animate: karaoke}`; `{op: fx}` with this Look's presets;
`letitedit_hooks` + `{op: hook}`; music with `letitedit_soundtrack` (protect `drop_out` for the beat before the turn).
Make the B-roll track right after the cut, before the captions (`{op: add_track, name: B-roll, kind: video}`): a B-roll track made later draws over the captions in a render.

## Structure (about 45 s; scale it to the story) [EOP]
| Beat | About | What it does |
|---|---|---|
| Hook | 0-3 s | the line that makes you need the rest: the problem, the strangest moment, the question |
| Setup | 3-15 s | who, where, what was wanted; one line of why it mattered [JH: a personal reason] |
| Build | 15-30 s | what was tried, what got worse; but/therefore links, never "and then, and then" [JH, ITE] |
| Turn | 30-40 s | the twist or the setback - only if it happened [modes: never invent one] |
| Payoff | 40-45 s | how it ended, shown as well as said; out within a second [JH] |
Leave a beat (half a second to a second) before the turn and before the payoff [EOP; ITE: slow down before the
critical moment]. Never a recap or a sign-off after the last line [EOP].

## Pacing
- Keep the teller's rhythm: cut dead air and false starts, keep pauses up to half a second and the breath before a
  line that lands (`editing.max_pause` 0.5) [ITE: over-tight talk sounds unsure].
- About 150 words a minute is a normal telling pace [EOP]; don't speed the talk up.
- A slight zoom (108%) on every other cut so jump cuts read as a change of framing [EOP]; a closer push (114%) only
  on the turn and the payoff line.

## The story label
- One short line near the top that names the story, not its ending - "The fan that wouldn't stay fixed" - on from
  the first frame to the end [EOP]. Place it with `story_label` (asset `{text}`, `at: 0`, `len` = the video's
  length). It is also the hook text: apply the hook with `text: null` so the two don't double up.
- It sits below the apps' top bars (18.5% down) and above the face. When the face is high in the frame, make the
  label smaller rather than raising it: above 18.5% the apps' bars and any handle line added on posting cover it.

## Captions
- Every word [EOP], sentence case, Poppins SemiBold, white with the word being said warming to peach (karaoke), a
  thin edge and a soft shadow [BLZ clean sentence]. Two lines at most, the block's middle at 58%.

## Effects: when and where
- `time_card` where the story jumps in time or place and the words don't say it ("9 DAYS LATER"). Upper case,
  three words or fewer.
- `turn_sting` once, on the beat before the turn, with the music dropping out under it.
- `flashback` only if the telling jumps back in time.
- `thing_pop` for the two or three objects the story turns on; not every noun.
- `cutaway` when there is footage of exactly what is told; never over the teller's face at the turn or the payoff.
- `payoff_chime` after the payoff word, never over it.
Calm on screen: about one change every 4-6 s, the slight zooms doing most of it. The fx op measures the rules.

## Sound and music
- A soft acoustic or lo-fi bed, 24 dB under the voice (talk zone) [MON, RES]. It drops out for the beat before the
  turn and comes back for the payoff [ITE].
- Few sounds: a paper swish for time cards, a record scratch at the turn, a chime after the payoff (`sfx.gain_db`
  -14).

## Colour and look
- `look`: warm and soft - a little golden, a touch of grain. Cream, peach and warm orange on deep brown for
  anything drawn; Fraunces for titles.

## Hook
- `letitedit_hooks` with approaches stakes, question, quote, result first. Open on the problem or the strangest
  moment, never "so this happened" or a greeting [JH, EOP]. If the hook is a flash-forward, that moment must come
  back later in place [JH].

## Ending
- The payoff line, a beat, out. If the last line loops into the first, keep it; never force it [JH].

## Avoid
- Word-pop captions, big text slams, shakes: they fight the telling.
- Music under the turn; a sting anywhere else; cutaways that hide the teller's reaction.
- A label that gives the ending away.
