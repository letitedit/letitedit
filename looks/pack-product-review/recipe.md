# Product review: the recipe

A 16:9 YouTube review (4-20 min) of one product, calm and exact: the product and one opinion up front, then the
parts in order - what it is, how it's built, how it does, who it's for - ending on a verdict held on one shot. Spec
and verdict cards where a list helps, close detail shots, the product's true colour. The product-commercial and
tutorial-explainer playbooks in letitedit-modes come first: claims only as said and shown, values exactly as
recorded, borrowed footage credited. Evidence tags are explained in letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-product-review}`; the look on every footage track; `blur_pad` on each vertical phone clip
(a clip effect: on a whole track it squeezes wide shots into the tall panel too); `{op: add_track, name: B-roll,
kind: video}` right after the cut; `{op: fx}` per part; `letitedit_bin` for `chapter:` markers; `{op: score}`;
`letitedit_hooks` + `{op: hook}`.

## Structure [EDS, PND]
1. Cold open: a hero shot of the product and one key opinion; the thesis within about 2-3 s, under 10 s [PND, EDS].
2. Intro, 3-5 s: `title` (the product and the question the review answers) [EDS].
3. The parts, in the order that suits the product - design, then fit or setup, then performance, then the extras
   [EDS design -> performance -> ... -> verdict]; each opens on a `section` band and a chapter marker.
4. The verdict: one held shot of the reviewer (or the product) with the `verdict_card` (pros and cons in the
   reviewer's words); speech ends 4-6 s before the video does; no long subscribe ask [PND, EDS].

## Pacing
- Even energy all the way [EDS]: about 7 cuts a minute on average (6-9), shots of 4-7 s at the median [PND];
  the first 30 s busier (10-14 cuts), the last 30 s calmer [PND].
- Talk and close-up b-roll take turns at least every 8-10 s [EDS], about as much b-roll as talking head [PND].
- Jump cuts; no speed ramps [EDS]. Pauses over half a second trimmed (`editing.max_pause` 0.5).

## On screen (graphics are a small share of a review: 0-9% of the frames [PND])
- `spec_card` once, early (about 20 s in), at most four facts, exact values, on screen 4 s or more [PND, EDS];
  `part_label` for a part as it is shown; `detail_push` on close-ups; `verdict_card` at the end; a score only when
  the reviewer gives one.
- `credit_tag` over any footage the reviewer didn't film [PND].
- Captions as an SRT; none burned in [PND].

## Sound
- The voice first, clean and level. Minimal ambient music low under the talk with 2 s fades [EDS], up in b-roll
  montages, out under the verdict. Clicks on cards and labels, a swipe on section bands (`sfx.gain_db` -20).

## Look
- `look`: neutral and exact - the product's real colours, a touch of contrast [EDS]. Match the shots first if the
  lights differ (`letitedit_match_shots`). White cards, dark type, one red accent; Geist throughout.

## Avoid
- Claims the reviewer didn't make or can't show; prices not in the footage or the brief.
- Heavy grades, speed ramps, flashy transitions, stickers.
- A verdict buried under graphics; borrowed footage without a credit.
