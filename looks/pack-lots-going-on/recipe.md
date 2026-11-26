# Lots going on: the recipe

A vertical Short (20-60 s) of one person talking, edited at the busy end of short-form: something new appears,
moves or makes a sound every one to two seconds - a sticker for every thing named, a word slamming in, a snap zoom,
the screen splitting to show the thing, a flash, a glitch. The person chose maximal, so it may be loud; the brief's
must-keep and must-avoid, and the letitedit-shorts rules (hook, foreshadow, payoff, end), still win. The busy part
is the decoration, never the story: the story still has to make sense with every effect switched off. Evidence tags
are explained in letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-lots-going-on}`; the look on the footage tracks (`{op: track, name: <track>, effects:
<look.effects>}` for the main track and B-roll; make the B-roll track before the captions with `{op: add_track,
name: B-roll, kind: video}`); `{op: captions, from_speech: true, animate: pop, chunk: sentence, max_chars: 12,
max_lines: 1}` (chunk `short` always makes 2-4 words a cue); one big `{op: fx}` batch; `{op: popups}`;
`letitedit_hooks` + `{op: hook}`.

## Structure
Same skeleton as any Short [JH]: hook (0-2.5 s), the promise by ~3 s, beats that each change something, the payoff
on screen, out within a second. Talk with lots of nameable things in it (products, parts, prices, places) suits this
style best: every thing named is a moment.

## Pacing
- Cut every gap over 0.15 s (`editing.max_pause`); jump cuts show and that is the look [GEN]. Keep one beat before
  the payoff and the word after it [ITE]: the one place the style goes quiet.
- Something changes on screen every 1-2 s: about double the ~4 s pattern interrupt of a normal talking head [MON].
  The fx op measures it: no more than 7 effects in 10 s, at least 0.5 s apart.
- Alternate framings: a punch-in on every second cut (1.18), back to normal on the next [MON: two framings, 110-120%].

## Captions
- One to three words at a time, ALL CAPS, Archivo Black, white with the word being said in green, a heavy black
  stroke [ASC]. About 8% of the frame height (`size: 84`) [BLZ 6-8%], block middle at 55% [BLZ 50-60%].
- Captions win over effects: nothing sits on them (`over_captions` in the presets).

## Effects: when and where (one batch)
Go through the transcript and mark every moment; most lines get one effect, a few get two (a sticker and a sound):
- **Every thing named** - `thing_pop` with an emoji (or the person's own picture). Beside the face (`opposite_face`).
- **Every number** - `number_pop` as numerals; money gets `sfx: cash`.
- **The stressed word** - `word_slam`, one per sentence.
- **Every second cut** - `punch_in`; in a long take with nothing else, `zoom_bump` on a list item or number.
- **There is footage of the thing** - `split_broll` (the bottom half shows it, the speaker stays on top) when the
  face sits in the top half; `cutaway` (full frame, 1-2 s) otherwise. Start within 1.5 s of the word, 4 s at most
  [MON].
- **New topic** - `whoosh_cut`, `flash_cut` or `glitch_hit` on the cut (rotate them; never the same one twice in a
  row) [ITE: vary devices].
- **Surprise, fail, joke** - `shake_hit` or `reaction_sticker` (an emoji or "WAIT", "OOPS"); `riser_reveal` into the
  big reveal and `bass_drop` on the payoff word.
- **A place** - `place_tag`.
- Word pop-ups that always fire (money, idea, wow, careful, done, fire) come from `{op: popups}`; run it after the
  fx batch and drop any that land on top of an fx sticker.
Flashes: never more than three a second [RES]. Read the fx op's broken rules and fix them; don't argue with them.

## Sound
- Sound on almost everything: pops for stickers, swishes for words, clicks for bumps, a whoosh or glitch on new
  topics, impacts on hits, a riser into the reveal. `sfx.gain_db` -10: loud enough to feel, never over a word.
- Music: a driving bed 20 dB under the voice [MON, RES], up hard in any gap. Drop it for the beat before the payoff.

## Colour and look
- `look`: punchy (saturation x1.18, a little extra contrast). Yellow, hot pink, cyan and green on dark for anything
  drawn: loud colours, but only one colour per element.

## Hook
- Frame 0 is moving: mid-sentence, a sticker or word already on screen, `bass_drop` under it. Hook text: five
  words or fewer, upper case, Luckiest Guy, at the top.

## Ending
- Cut on the payoff, at most a second after it [JH]. No outro, no subscribe animation.

## Avoid
- Effects on the face, the captions or the phone apps' buttons; two stickers on top of each other.
- The same effect three times in a row (rotate); a split screen with nothing to show in it.
- Third-party logos the person didn't give you; emoji or their own pictures instead.
- Effects that change the meaning (a fail sound on something that worked).
