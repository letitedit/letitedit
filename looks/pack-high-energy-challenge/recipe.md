# High-energy challenge: the recipe

A vertical challenge story (30-60 s) told at full speed: the goal and what happens if it fails in the first seconds,
a timer and a progress bar running, attempts and setbacks labelled, a re-hook every few seconds, half a second of
silence, then the result. Loud on screen, but the challenge must be real: real rules, real limits, real results. The
letitedit-shorts rules come first (hook, foreshadow, a visible mechanism, end on the payoff). Evidence tags are
explained in letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-high-energy-challenge}`; the look on every footage track; `{op: add_track, name: B-roll,
kind: video}` before the captions; `{op: captions, from_speech: true, animate: highlight, chunk: short, max_chars:
12, max_lines: 1}`; one `{op: fx}` batch with `progress` first; `{op: popups}`; `letitedit_hooks` + `{op: hook}`.

## Structure
1. Hook (0-2.5 s): the goal and the stakes, the hardest moment or the result teased - not shown [MKS]. Hook text in
   six words or fewer ("CAN I FIX IT WITHOUT PULLING IT?").
2. The challenge (2.5-6 s): `challenge_card` - the goal as a question and its rules or stakes, true facts only.
3. Attempts: each opens with an `attempt` label ("ATTEMPT 1", "DAY 9"), shows the work fast (days in seconds), and
   ends on a result or a setback (`fail_stamp` on a real fail).
4. Re-hooks: every 5-8 s a new question or a turn (`rehook`: "BUT...", "WAIT") [GEN]; the biggest ones at about a
   third and two-thirds of the way [MKS].
5. The result: half a second of silence (music out) [MKS], then `win_stamp`, `flash` and the level-up; out within a
   second.

## The clock
- `progress` along the top for the whole video (how close the end is).
- `timer` over an attempt or the whole run, only with a real limit or the video's own clock (from_s down to 0 over
  the item). Never a fake deadline: if there is no limit, count up the days or the attempts instead.

## Pacing
- Every gap over 0.12 s goes (`editing.max_pause`); jump cuts show and that is the look. Something new every 1-3 s:
  `snap_zoom` on every other cut [MON], `stake` on the consequences, `arrow` at the part, pop-ups for money and
  danger.
- Cover days in seconds; keep only the moments that move the challenge on.

## Captions
- 1-3 words in heavy Montserrat capitals, the word being said on a red box [BLZ highlight box, ASC]; centred at 60%.

## Sound
- A driving bed under the voice, out for half a second before every reveal [MKS]; whooshes on labels and re-hooks,
  booms on stakes and shakes, a buzzer on a fail, a riser into the result, a level-up on the win
  (`sfx.gain_db` -10). Never more than three flashes a second [RES].

## Look
- `look`: bright and punchy (saturation x1.2, a little contrast). Yellow, red and green on black; Rubik Black for
  labels and stamps.

## Avoid
- Fake stakes, fake deadlines or a result that didn't happen.
- The result in the first seconds (tease it, don't show it); a slow setup.
- The same re-hook word twice in a row; effects on faces, captions or the app's buttons.
