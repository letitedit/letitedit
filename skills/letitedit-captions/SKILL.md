---
name: letitedit-captions
description: Spoken captions and on-screen words for a letitedit edit - whether captions help (muted feeds, Reels, Shorts, accessibility), a calm or word-pop style chosen by mode, chunking for reading speed with names and numbers kept whole, placement inside the phone apps' uncovered area and away from faces, text and action (letitedit_caption_fit), fused words and missing spaces fixed, every name and claim spelled exactly, and an SRT. Use whenever captions or on-screen words are added, restyled, moved or corrected, or on notes like 'I can't read the captions' or 'the name is wrong'.
metadata:
  version: 0.1.0
---

# Captions and on-screen words

When the product name is spoken, captions print **letitedit**, never "Let It Edit". Correct the display spelling
without changing speech timing or unrelated uses of the ordinary words "let it edit".

**The decision:** which words appear on screen, in what style, where, and spelled how.
**Inputs:** the brief (`deliverables` and their platforms, `mode`, `driver`, `feel`, `claims`, `must_keep`,
`audience`), the transcript with its unsure words (`(?)` in `letitedit_words`), the person's word list (Look), and
where faces, on-screen text and the key objects sit in each shot.
The library says almost nothing about captions (two remarks from one Shorts creator, one subtitled documentary), so
most rules here are [GEN] (published caption practice) or [OURS] (local editing practice); the tools do every
measurement. Labels that explain the picture (pointers, steps, names, chapter cards) are letitedit-graphics; the
hook's words and frame 0 are letitedit-shorts; honesty about what was said is letitedit-craft's. Calls and defaults:
references/tool-recipes.md; styles by mode: references/styles.md.

## 1. Do captions help here?
- **A learned Look overrides generic styling, not exact words or face safety.** When the selected Look has its own
  caption roles, measured arrivals, colour policy, picture-following letters or kinetic roles, read
  references/look-captions.md in full before styling (role hierarchy, one-word emphasis, word onsets, fixed phrase
  positions, the movement envelope, finding the reference's font, readability of its lettering). [OURS]
- **Caption all speech in anything that plays muted in a feed:** vertical shorts, Reels above all (viewers mute; one
  creator's successful Reels were very visual with subtitles throughout). Check: a muted watch of the first 10 s and
  of one middle minute still tells the story [JH 29:50; JH 2:34; ITE esNXgCJh-yk 14:08].
- **Long-form YouTube:** make an SRT the viewer can switch on; burn words in only when the brief, the person's style
  or the series asks, or for a few key words. Check: the hand-off names the SRT [GEN].
- **Music-led, wordless or process-montage pieces:** no running captions; short chapter or step text instead
  (letitedit-graphics). [OURS].
- **Not:** speech that isn't part of the story (crew, a radio, a passer-by), and fillers (`fillers: false`, the op's
  default) [GEN].

## 2. Style by mode
- **A person talking to camera in a vertical short gets word-pop, whatever the world behind them feels like:** a heavy face on one line
  of 1-3 words, thick outline, the said word in the accent colour and growing as it's said. A calm feel doesn't make captions thin: the
  run with regular-weight, mixed-case words on two lines and a 2.5 px outline lost on captions, and the other's were no bigger per letter,
  only heavier: "the captions are cooler/better" [OURS]. `references/styles.md` has the numbers.
- **Calm (sentence) captions** for interviews, documentary, tutorial explanations, reflective or cinematic pieces,
  older audiences and long-form: `chunk: 'sentence'` (up to 42 characters a line, 2 lines), no animation, a steady
  place. **Word-pop** (`animate: 'pop'`, `'highlight'` or `'karaoke'`, `chunk: 'short'`) for energetic creator
  shorts, vlogs and comedy where the words are the energy. `typewriter` and `bounce` are louder still: a reason
  first. Check: the journal names the style and the mode or feel that chose it [GEN].
- **One style per video**, in the person's Look look (`letitedit_looks(action='get', id=...)`), the same across a series. "Less
  flashy" moves word-pop to calm [GEN; JH 10:00].
- **Emphasis:** only the active word (the animation does it) and at most a few key words in a colour; numbers as
  digits ("$12", "3/8 inch"); no emoji in tutorials [GEN].
- **Check word-pop at its peak frame,** not only between pops: a growing word can touch its neighbour, and mid-pop
  stills read as uneven sizes (`fused_at_peak` in caption_fit) [OURS].

## 3. Chunk for reading
- **At most 20 characters a second** (17 is comfortable); each caption 0.8-7 s on screen; break at sentence ends and
  pauses; a name, a number with its unit, a price, an article with its noun stay on one line; no cue ends on "a",
  "the", "to" or "of"; no lone one-word cue (merge it). The captions op chunks (sentence: 42 x 2 lines, a new cue
  after a 0.6 s pause, 0.8-6 s each; short: up to 4 words and 22 characters on one line); `letitedit_caption_fit` then
  regroups by pixel width and reading speed (`max_cps` 20, `max_duration_s` 7) and keeps names, numbers and units
  together (`keep_together` adds the brief's multi-word names). Check: its `reading_speed`, `too_short`,
  `too_many_lines` and `bad_break` items are none or explained [GEN Netflix practice; OURS one-word lines and
  fragments cost points].
- **Speech faster than the limit:** never drop or change words to fit. Allow a little more (`max_cps` up to about 24
  on word-pop shorts) or let the line play longer in the edit [GEN].
- **Calm captions don't flash:** each cue holds just past its last word (the op holds 0.15 s) and never overlaps the
  next [GEN].

## 4. Exact words: names, numbers and claims
- **Spell every name and claim exactly** as the brief and the person write them, capitals included: each item in
  `claims`, people, places, products, prices, units. Build the op's `fix` table before burning in, from `claims`,
  the person's word list and every unsure `(?)` word near a name or number; listen to unsure words
  (`letitedit_check_range`). Check: the gate checks that each claim is said and on screen (caption tracks or
  word-caption graphics): names exactly (capitals count), numbers as the same amount ("$12" or "12 bucks"); read
  every cue once against the transcript [GEN; OURS misheard words in captions lost text points].
- **Fix spelling, never meaning:** a caption shows what was said. If the speaker misstated a claim, flag it to the
  person; don't quietly correct the caption [GEN; letitedit-craft].
- **Fused words and missing spaces are must-fix errors:** "itWithout", "wall.Then", two words touching under a thick
  outline or a pop. caption_fit reports `fused_words` and `missing_space` as errors and fixes them without changing
  words (restores a space the transcript shows, thins the outline, eases the pop); `suspected_missing_space` and
  `fused_at_peak` are warnings to look at. Check: zero errors in the final proposal and its rendered peak frames
  [OURS; caption_fit].
- **Names and "I" capitalised, sentences capitalised and punctuated;** lowercase names or leftover fillers read as
  sloppy [OURS].
- **One sentence per caption; a full stop ends the caption.** Two sentences in one cue are flagged by the review;
  the fix is a new cue at the full stop, never a dropped full stop or a comma in its place ("The camera is ready." /
  "Let's begin."), which changes what the line means [OURS]. The captions op and the cue tidy keep a cue that ends a
  sentence on its own, even a short one, and put back a full stop the transcript lost where it capitalises the next
  sentence's first word. Where the words read as two sentences but the transcript runs them together with no capital
  ("the camera is ready let's begin"), write the cues by hand with the full stop.

## 5. Place them where they can be read
- **Run `letitedit_caption_fit(project, platform=<target app>)`:** it keeps captions inside that app's uncovered area
  (from `letitedit_platforms`), never under a readable size (about 3.4% of the frame's short side, 37 px on a 1080
  frame), clear of faces, other text and any boxes you mark `protected`, and holds one place through a shot or
  phrase. Look at its preview frames, `violations_after` and `unresolved` (the reply is brief; `plan_file` has every cue and violation); then apply it (a plan that covers more faces than the captions do now is refused with both numbers: on a tight shot the app's buttons can leave only the face, and `platform_zones='soft'` or the current layout are the ways out [OURS]) (`plan_id` with `apply=True`);
  run it again after any edit that moves words [GEN; caption_fit].
- **An edit whose reply already re-checked the captions needs no fit of its own:** when its `captions_followed` shows
  them applied or already fitting, with nothing over a face and no placement problem left, don't run
  `letitedit_caption_fit` again for that edit [OURS].
- **The right place is the middle of the room, not the nearest spot that passes.** Look at the whole frame: the free
  area runs from the lowest chin in the video down to where the apps cover the picture. Put every caption at the middle
  of it, one steady place for the whole video, so the words don't creep around with the speaker's head; leave it only for a real
  reason in that moment (a hand, a tool, a graphic, another text there). `letitedit_caption_fit` measures the chin across
  the video (a sample every half second) and offers that place first, named `free`; its reply's `free_area` says where
  the room starts and ends, as a share of the frame's height, and what each app alone would leave. [OURS]
- **Test, place, retest.** Before applying, look at fit's `free_area` and its preview frames: is the place it chose the
  middle of the free shirt for this shot? After applying, look at the real frames at full height across the video
  (`letitedit_check_frames`, a frame every few seconds, not a crop): the gap under the chin, the words clear of the app
  areas, the same place throughout. The review flags captions that sit high with room lower down ("captions sit high") and says
  where to put them; it can't see a hand or a graphic that needs that spot, so that call is yours.
- **Which apps decide the bottom edge.** `platform='phone'` is the intersection of all three, and Reels' ad guidance
  (the bottom 35%, Meta's, for ads; none is published for ordinary Reels) starts at 65% of the height, which on a close-up
  leaves nothing under a chin at 62%. TikTok's covered area starts at about 81% and Shorts' at 84% (third-party
  figures, low confidence). For a video going to TikTok and Shorts, fit with `platform='tiktok'` (it covers the Shorts
  area too). If it is going to Reels as well, say in your message that Reels' account name and caption may cover the
  lower captions there, or make a Reels version (letitedit-shorts). Don't squeeze captions up under the chin to satisfy one
  app's ad rule on a close-up. Repeat and apply the fit after any later caption cue, style, picture or opening change,
  including a hand-written caption correction; use `faces='hard'`.
- **Keep the whole head clear:** the face detector's box starts near the forehead, so check hats, hair and the
  space just above the face in the rendered preview too. Mark a hat as `protected` if needed; a report of zero
  face overlap does not prove the head is clear. If the speaker fills the phone's shared clear area, reframe the
  picture to create caption space, or make separate platform versions, then run the fit again. Never solve that
  conflict by leaving tiny words on a cap or deleting the only useful explanatory graphic. The fitter's minimum
  size is a floor, not a target: judge actual readability at 360 px. [OURS]
- **Low on vertical by default (the middle of the free area);** move up only for on-screen text, a hand or the object the shot is about, or the app's bottom overlay;
  never cover the hand, tool or object the shot is about (mark it `protected`). Keep captions on the footage's
  picture area, not on side bands or past the edges of a vertical clip in a wide frame [OURS].
- **The apps' covered areas are estimates** (TikTok's from a third-party checker, low confidence; Reels' from its ad
  specs: the bottom 35%). One file for several apps: fit for each and keep a place that passes all; if none does,
  make one version per app (letitedit-shorts) [GEN; letitedit_platforms].
- **Check at feed size:** `letitedit_check_frames(times_s=[...], width=360, platform=...)` for vertical (480 for
  wide): every caption reads at a glance, clear of the drawn zones, faces and the key object [GEN].

## 6. On-screen words that aren't captions
Hook text, a muted-viewing headline, a price or a one-line label work like captions: short (2-3 words in the one
creator's series layout), plain words (about a 5th-grade reading level), inside the uncovered area, on screen at
least words / 3.5 + 0.5 s, never fighting the captions for the same place. They go through caption_fit like
captions; their design is letitedit-graphics' [JH 10:00; JH 3:55; GEN].

## 7. Tools
- **Whole-time readability:** call `letitedit_caption_readability` on the final edit at 360px, not just a still.
  It measures opaque letter cores against the underlying picture on every native frame; no-core/translucent
  lettering and unsupported routing are failures, not evidence of readability.
  A Look with its own lettering (inverted-then-white, `shot_dependent`, Difference, kinetic roles, timed protected face
  rectangles): references/look-captions.md, after all picture work and before the Look check.
- **Make:** `{op: captions, track: 'Captions', from_speech: true, chunk, style, animate, fix: {heard: Written},
  fillers: false}` in `letitedit_timeline_apply`: cues from the edit's own words (run it again after re-cuts).
- **Lay out:** `letitedit_caption_fit(project, platform, tracks, style, lock, placements, prefer, protected, faces,
  regroup, max_cps, keep_together, min_size_px, ...)` returns a proposal (changes, violations, unresolved, preview
  frames); nothing changes until `apply=True` (or `plan_id` with `apply=True`). It reads the saved file and cached
  transcripts only: save, and run `letitedit_words(project=...)`, first. With the project open in letitedit, a plan that
  changes caption style is refused: save and close the window, then apply. See `letitedit_guide('letitedit_caption_fit')`.
- **SRT:** a second, unburned track from the same words (`{op: captions, track: 'Subtitles', from_speech: true,
  chunk: 'sentence', burn_in: false}`); the person exports it from the Subtitles panel (Export SRT); with files,
  write it from the cues `letitedit_timeline_read` shows. Make one for every deliverable with speech (letitedit-finish
  puts it next to each export); upload it with long-form videos [GEN].
- **Look:** `letitedit_check_frames(platform=...)` on the busiest frames, then the review bundle's project checks
  (`letitedit_review_bundle`: graphics over captions, words cut at clip edges) and caption_fit's own report (faces,
  other text, the apps' buttons).

## 8. Checks and hand-off
Every cue read once against the transcript and the brief; caption_fit errors zero and warnings explained; claims and
numbers spelled exactly; a muted watch of the opening and one middle minute; the SRT made. Journal note
`stage:captions:done`: the style and why, the platforms fitted, fixes applied, open warnings.
