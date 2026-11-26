# Product ad (UGC): the recipe

A vertical ad (20-45 s) that looks like a person showing something they really use: the problem or the curiosity in
the first seconds, the product in hand, proof (what it does, what comes with it, what it costs), one reason to
believe, one ask. Native on purpose - the text and captions look like the app's own, nothing glossy. The
product-commercial playbook in letitedit-modes comes first: true claims only, the product shown working, the
person's real words. Evidence tags are explained in letitedit's `looks\SOURCES.md` (optional reading).

Tools: `{op: look, id: pack-ugc-product-ad}`; the look on every footage track; `{op: add_track, name: B-roll, kind:
video}` before the captions; `{op: captions, from_speech: true, animate: pop, chunk: short, max_chars: 16,
max_lines: 1}`; one `{op: fx}` batch; `{op: popups}`; `letitedit_hooks` + `{op: hook}`.

## Two variants (ask, or follow the brief)
- **Produced** (the default here): a music bed 6-10 dB under the voice, a swipe on the reveal, ticks and pops, an end
  card with the ask (3-5 s) [RSL].
- **Organic**: no music, no sound effects, no transitions, no end card - captions, the hook text and punch-ins only;
  end on the last spoken line plus about half a second [RSL]. Never mix the two in one ad [RSL].

## Structure (five beats) [SGN, NIN]
1. Hook (0-3 s): the first frame and first line both inside 3 s, the product already in hand or in frame [NIN, SGN].
   The `hook_text` on a white box says the problem, a curiosity or the benefit in seven words or fewer; no logo,
   brand name or greeting [RSL]. Make three openings of different kinds for the person to test [SGN].
2. Context: the problem or the before (5-8 s).
3. The product: in frame, named the way the speaker names it.
4. Proof: what it does and what comes with it, shown, not described - `proof_points` ticking in as each is said,
   inserts of the exact part (15-25 s for the body) [NIN].
5. The ask: one action (3-5 s) [NIN, RSL]; produced variant on `cta`.

## Pacing
- Sentence gaps about 0.15 s, pauses capped at 0.25 s (one beat may run to 0.4 s) [RSL]; start each clip on the action
  (trim the first half-second) [SGN].
- A visual change every 2-3 s [RSL]: `product_punch` on every other jump cut (112%, back to 100% on the next) [RSL],
  `insert` close-ups of 1.5-3 s covering 30-50% of the body [RSL]; no shot held past about 4 s.
- 20-45 s in all [RSL: 25-45 s for talking UGC; NIN: 15-45 s].

## Captions and text
- Captions: one fixed place a little below the middle (62% down), 1-3 words at a time, sentence case, Inter Bold
  with a thin dark outline [RSL, NIN]. Numbers as digits with units ($12, 2 tabs) [RSL].
- `hook_text` (white box, dark text) for the first 2-3 s; `price_pop` for the price; `tick` or the
  `proof_points` card for each benefit; `arrow` at the exact spot of a feature.

## Sound
- Produced: an upbeat bed without lyrics 6-10 dB under the voice [RSL]; a pop on stickers, a ding on ticks, a till on
  the price, a swipe on the reveal, a notification on the ask (`sfx.gain_db` -14). Organic: none of these.

## Look
- True to life and bright: the product's real colours (`look`), white cards, yellow price, green ticks.

## Avoid
- Claims the person didn't make or can't show; prices or offers not in the brief; competitor or brand logos.
- A logo, a brand name or "hey guys" in the first 3 s [RSL]; long unboxing starts.
- Mixing organic and produced pieces; music under an organic ad.
