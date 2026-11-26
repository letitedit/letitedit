# Word-pop talking head: the recipe

A vertical Short (20-60 s) where one person talks to camera, made to feel fast and alive: every word on screen as
it is said, quick punch-ins, and the things they talk about popping up beside them. This is a chosen style, so it is
allowed to be busy; the brief's must-keep and must-avoid, and the letitedit-shorts rules (hook, foreshadow, payoff,
end), still win over anything here. Evidence tags are explained in letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-word-pop}`, then the look on the footage tracks (`{op: track, name: <main track>,
effects: <look.effects>}`, the same on B-roll), `{op: captions, from_speech: true, animate: pop}` (the look comes
from this Look), `{op: fx, items: [...]}` with this Look's presets, `{op: popups}` for the pop-ups that place
themselves, `letitedit_hooks` and `{op: hook}` for the opening.
Make the B-roll track right after the cut, before the captions (`{op: add_track, name: B-roll, kind: video}`): a B-roll track made later draws over the captions in a render.

## Structure
1. Hook (0-3 s): the most interesting moment first (a result, a question, the problem), with the hook text on top
   [JH].
2. The point in one breath (by about 3 s): what this is about and why to stay [JH].
3. The body: one idea per line, each line earning the next ("but", "so", "then I found..."). Cut anything that
   repeats a point already made.
4. The payoff: the result, the answer or the punchline, shown as well as said.
5. Out: end within a second of the payoff. No outro card, no "thanks for watching" [JH].

## Pacing
- Tight: pauses over a quarter of a second go (`editing.max_pause` 0.25), but keep the breath before a punchline
  and the beat after it [ITE].
- Jump cuts are part of the look. Hide them with a punch-in on every second or third cut (in at 1.15, out at the
  next cut), so the frame size alternates between two framings [MON].
- Something changes on screen about every 2-4 seconds: a cut, a punch-in, a pop-up or a text pop [MON: about every
  4 s; this style a little faster]. Never more than four effects in any 10 seconds; never two in the same spot.

## Hook
- Frame 0 is content: no logo, no black, no greeting. The best opening is often the result or the problem said in
  one line [JH].
- Hook text: the promise in under six words, upper case, at the top (`hook.text`), on for the length of the hook
  clip. Ask `letitedit_hooks` for candidates and pick by approach, not by score alone.

## Captions
- Every spoken word, word by word, upper case, Montserrat Black, white with a thick dark outline, the word being
  said in yellow [ASC]. One to three words a line, two lines at most [ASC, BLZ].
- Type about 7% of the frame's height (`size: 80` on a vertical project) [BLZ 6-8%], the block's middle at 56% of
  the height [BLZ 50-60%]: below the face, above every app's bottom bar. Names, numbers and claims spelled exactly
  (fix them in the captions op's `fix`).

## Effects: when and where
Read the transcript line by line and mark the moments; then place them in one `{op: fx}`:
- **A thing is named** (a tool, a part, a product, a food): `thing_pop` with an emoji that shows it, or the
  person's own picture of it. Beside the face, never on it. Not for abstract words.
- **A number or price**: `number_pop` with the number written as numerals ("$12", "3 hrs", "12 V").
- **The word they lean on**: `emphasis_word`, one word, at most one per sentence.
- **A stressed word or a restart**: `punch_in` on that clip.
- **A punchline or a real surprise**: `shake_hit` (rare: a few per minute at most).
- **A change of topic or a jump in time**: `whoosh_cut` on the cut; `flash_cut` for the first look at a result.
- **A place is named**: `place_tag`.
- **There is footage of exactly what is being described**: `cutaway`, starting within 1.5 s of the word and 1-4 s
  long [MON], never over a punchline or a reaction.
The fx op measures the presets' rules (how often, where, how long) and lists what breaks them; fix those, don't
argue with them. Pop-ups that are just "this word means this picture" (the letitedit icon on "letitedit", a money
bag on "bucks") come from `{op: popups}` by themselves.

## Sound
- Every pop-up and text pop has its pop; numbers get a ding; shakes get a low thump; whooshes land on the cut.
  All sit under the voice (the Look's `sfx.gain_db` -12 dB): the words always win.
- No sound effect on the payoff line itself if it would cover a word.

## Music
- Optional. If used: one light, steady track at least 20 dB under the voice [MON, RES] (talk -22 dB), coming up
  only in pauses without words. Never a vocal track.

## Colour and look
- `look`: natural, slightly brighter and more saturated (saturation x1.08); skin looks healthy. No heavy grades.
- White, yellow (#FFD23F) and a warm red (#FF5A36) for anything drawn on screen.

## Ending
- Cut right after the payoff (within a second) [JH]. If the end loops into the start naturally, keep it; never
  force it.

## Avoid
- Effects that cover the face or the captions; effects in the app's covered areas (the right-hand buttons, the
  top bar, the bottom title area).
- Effects on every single word: it stops meaning anything. Leave some lines plain.
- Third-party logos the person didn't give you. Emoji or their own pictures instead.
- Stock "subscribe" animations, intro cards, slow fades.
