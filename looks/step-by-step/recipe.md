# Step by step: the recipe

A vertical Short (20-50 s) that shows how something is done or made: the finished result first, then each step on
screen with its number and a few words, the hands and the material doing the explaining. It works with someone
explaining as they go (their words name the steps and become the captions) and with silent process footage (short
labels name only what is visible). The tutorial-explainer playbook in letitedit-modes and the letitedit-shorts rules
come first: every step shown is real, nothing is invented. Evidence tags are explained in letitedit's
`looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: step-by-step}`; `{op: captions, from_speech: true}` only when someone talks; `{op: fx, items:
[...]}` with this Look's presets; `letitedit_hooks` and `{op: hook}`; `{op: score}` for the music.

## 1. Find the steps
- Read the footage picture first when nobody talks (`letitedit_footage`, `letitedit_find_ranges`, frames): name the
  visible stages. Each step needs a moment where it starts and a moment where its result shows.
- Three to six steps. Join tiny ones; leave a step out only when it can't be seen or repeats one already shown. Never
  invent a step the footage doesn't show, and never name a tool or material you can't see or hear [modes].
- Keep the real order. Jumps in time are the point (a process sped up); a step is never shown out of order.

## 2. Structure
1. Hook (0-2 s): the finished result, or the most surprising moment of the process, with the hook text saying what
   it is and how many steps ("CLAY TO VASE IN 4 STEPS") [JH].
2. Step 1 starts by about 3 s [JH].
3. Each step: its card at the start, then one to three shots (the start, the change, the result), 3-8 s a step:
   quicker for easy steps, longer for the one that takes skill.
4. The payoff: the finished result held 1-2 s, the result flash, the end.

## 3. Pictures and pace
- Close on the hands and the material; a wider shot only to show where we are or how big the result is.
- Get through repetition with speed (2-4x on a clip's `speed`, never faster than 4x) or a cut; keep normal speed for
  the moment that teaches (the hands' technique). A speed change sits on its own clip, so it starts on a cut [GEN].
- Cut on the action: every cut moves the process forward where the viewer can see it.
- Wide footage on a vertical project: reframe around the hands and the work, not the empty centre.

## 4. Step cards (one fx batch)
At each step's start, the same `at` for all three:
- `step_number`: the number, huge, amber, top third ("1", "2", "3"), with a whoosh.
- `step_title`: the action in two to five words, upper case ("CENTRE THE CLAY") [CLU: 6 words at most]. From the
  speaker's own words when they name it; from what is visible when nobody talks.
- `step_counter`: "1/4", "2/4"... top-left until the next step (`len` to the next card). It only counts up.
Inside a step: `done_check` where the footage shows that step finished. At the end: `result_flash` once on the
finished result. Leave the hands and the work clear: cards sit in the top third, never on the action.

## 5. Captions
- Someone talks: every word, calm box captions (the Look's caption settings), clear of the hands and the cards.
- Silent footage: no spoken captions; the step cards carry the words. All captions in a video are one kind.
- Names, numbers and measurements spelled exactly.

## 6. Sound
- Keep the real sound of the work (the wheel, the tool, the material) under the music: it makes a process worth
  watching [GEN]. Music light and steady: under speech about 20 dB below the voice [MON, RES]; in silent stretches
  it carries the video with the work's own sound beneath it.
- A whoosh into each step card, a tick for the counter, a ding on a check, a chime on the result (`sfx.gain_db` -12).
  Each sound lands with its card, within an eighth of a second.

## 7. Ending
- End on the finished result within about a second of showing it. No recap list, no outro card [JH].

## Avoid
- Steps or labels that claim more than the picture shows; a counter that skips or goes backwards.
- Cards over the hands, the work or a face; text in the apps' covered areas (the right-hand buttons, the top bar, the
  bottom title area).
- Long unbroken stretches of the same motion: speed them up or cut them.
- Effects between steps that don't teach anything: the process is the show.
