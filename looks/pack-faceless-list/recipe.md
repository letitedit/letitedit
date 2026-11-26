# Faceless list: the recipe

A vertical Short (25-60 s) where a voice works through a numbered list ("3 steps to...", "5 things nobody tells
you...") over footage of the things themselves - hands, objects, places, screens - with no face on camera. The list
is the mechanism that keeps people watching: the count is promised in the hook, each item opens with a big number
and its name, and a small counter shows how far along we are [JH]. The rules in letitedit-shorts and letitedit-modes
(tutorial-explainer for steps) come first: deliver every promised item, never pad a list. Evidence tags are
explained in letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-faceless-list}`; the look on the footage tracks; `{op: captions, from_speech: true,
animate: karaoke}`; `{op: fx}`; `letitedit_hooks` + `{op: hook}`.
Make the B-roll track right after the cut, before the captions (`{op: add_track, name: B-roll, kind: video}`): a B-roll track made later draws over the captions in a render.

## 1. The voice and the list
- The narration drives [modes]: a voiceover track (recorded, or the person's own narration from footage where their
  face isn't shown). Cut its dead air (`editing.max_pause` 0.35) and keep the breath that ends an item.
- Find the items in the words first: each item needs a spoken start ("first", "next", "then I...") and footage that
  shows it. Three to five items; if the footage shows only two, it is a list of two [JH, modes: never pad].
- Order: the order the viewer would do or care about them; the best item last when there is no natural order.

## 2. Pictures
- The picture changes every 2-5 s [OVS: median 3.6 s per scene; MON: 3-5 s per cutaway]; hard cuts [OVS]. Each shot
  shows what the voice is saying at that moment, starting within about 1.5 s of the words [MON].
- Proof over decoration: the result of each item on screen (the part moved, the tool in place) [modes].
- Mixed footage brought to one look (exposure and colour, `letitedit_match_shots`) [OVS].

## 3. Cards and counter (one fx batch)
At each item's spoken start, the same `at` for all three:
- `number_card` - the number, huge, amber ("1", "2", "3") with a whoosh.
- `item_title` - the item in three to five words under it, upper case [CLU: 6 words at most].
- `counter` - "1/3", "2/3"... top-left until the next item (`len` to the next card).
Then, inside the item: `key_word` for the word or number it turns on (not while the card is up), `done_check` where
the footage shows it done, `cutaway` to change the shot. At the end: `result_flash` once on the final result.

## 4. Captions
- Every word, highlight-box style for lists and busy footage [BLZ]: white Inter ExtraBold on a black box at 75%
  [BLZ 65-80%], the word being said in amber. About 5.7% of the height (`size: 62`), the block's middle at 62%, under
  the cards and above the apps' bottom bars.

## 5. Sound
- Voice first [OVS]; a light beat bed 20 dB under it [MON, RES], a little higher under the number cards. A whoosh
  into each card, a paper swish for titles, a tick for the counter, a ding for a check, a chime on the result
  (`sfx.gain_db` -12).

## 6. Hook and ending
- The count and the payoff in the first 3 s: hook text such as "3 STEPS TO FIX A GRINDING FAN" over the result or
  the problem [JH, CLU]. The first item starts by about 5 s [JH].
- End on the last item's result, within a second [JH]. No recap list unless the brief asks for one.

## Avoid
- A face on camera (another style fits that); random b-roll that doesn't show what is said.
- Cards that say something the voice doesn't; a counter that skips or goes backwards.
- Captions under the cards, cards on the apps' buttons.
