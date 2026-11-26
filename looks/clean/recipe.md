# Look: Clean

Style: talking head, for Shorts/Reels/TikTok (9:16) and YouTube videos (16:9). Flavour: nothing but the person, cut well. The plain, confident option, and
the baseline every other Look is judged against. If a Look can't beat this one, it shouldn't exist.

The sections below describe the Short. When the request's `Format:` is YouTube video, read "On a YouTube video (16:9)"
near the end as well: where it differs (length and structure, framing, captions, sound, vertical footage), it wins.

## What the viewer sees
- The person, full frame, in their real place. No graphics, no effects, no pop-ups.
- The framing changes with the thought: wider for a statement, closer for the point that matters. It looks like a second camera, not a zoom effect.
- Calm captions, one phrase at a time, that don't move or pop. Low on the chest, clear of the face.
- A clear, close voice, with very quiet music underneath that you notice only when it fades at the end.

## What makes this Look this Look
Restraint. Everything the viewer would notice as "an edit" has been taken out except the cuts themselves. The energy comes
from the speaker and from when the picture changes. Don't add anything to make it less plain: if it feels dull, the cure
is better selection, tighter cuts or a closer framing at the right moment.

## How to choose the picture changes
Read the sentences and mark where one thought ends and the next begins. Change the framing only at those places, in the speaker's own pause.
- A starting range is 1.4 to 3.7 s per shot, about every sentence or half-sentence; follow the thought rather than a shot quota.
- Close for the turn or the claim ("And here's what I did about it", "that's AI first", "you simply direct"). Wide for the set-up or a new subject ("The LLM drives the software").
- Stay within 1.0 to 1.2 times the shot, centred between the eyes and the mouth, so the head never crops badly and the picture stays sharp. Above about 1.2 on 1080p footage, it starts to soften.
- A step in framing at a cut, not a moving zoom. Very slow pushes (1.0 to 1.04 over the shot) are allowed on the wide shots so they don't go dead.
- A real jump cut (time removed) should land on a change of framing, so the jump reads as a new angle.

## Captions
- One phrase at a time, broken where a person would breathe. Never leave "and", "as" or "the" hanging at the end of a line.
- Same family as the other Looks (Montserrat), SemiBold, about 64 px at 1080 wide, near-white with a thin dark outline. One colour, no highlight, no animation.
- Colour follows the first Look's rule: the near-white takes a trace of the room's main hue (`looks\big-letters-behind-you\recipe.md`), and its outline is a very dark version of that hue, both measured from this video, never carried over from a sample.
- A soft halo under the letters, always: on the captions op, `style.shadow: {color: <the outline's dark hue at about 60% opacity, e.g. '#1A141099'>, x: 0, y: 1, spread: 6}`. It is a translucent, wider copy of the outline: over a dark room it disappears, and over something bright (a white dog, a window, a pale shirt) it gives the letters a gentle dark edge where the thin outline alone would wash out. No box, no hard drop shadow [OURS]. Check it with `letitedit_caption_readability`: its `native` part lists any caption whose surround is still close to the letters' lightness [RES-WCAG].

## Sound
- Clean the voice with the default, `{fix: {kind: voice}}`. If a sound other than the voice matters, see FINISH-2 in `letitedit-finish`. Do not use `rest_gain_db: -120` for room tone: digital silence makes the room go dead.
- Music about 15-17 LU under the voice, soft, with no strong rhythm. It should never pull attention. No sound effects.
- Cut in the room tone between words, measured on the sound (`letitedit_words` per word, then the loudness), never on the transcript's times alone.
- End a beat after the last word: half a second of the person's face and room tone, music fading over the last 1.2 s.

## What footage it needs
Any talking head with steady framing and enough resolution for 1.2 times. A good speaker carries it; a weak delivery has nowhere to hide.

## Must not
- No pop-ups, emoji, flashes, shakes or sound effects. No word-by-word captions.
- Don't zoom on a schedule. A change with no new thought behind it is just noise.
- Don't let a punch-in crop the top of the head or put the eyes off the upper third.

## On a YouTube video (16:9)
The same restraint, made for a viewer who chose to watch for minutes rather than one who might swipe. Everything not
named here stays as above.
- **Structure, not one arc.** A Short is one 60-second arc; a YouTube video is a few sections, each one idea with its own
  small payoff. Mark the sections from the words (where the subject turns) and put a `chapter:<name>` marker at each one
  (`letitedit_bin`): YouTube makes chapters from a description list that starts at 0:00, has at least three entries and
  gives each at least 10 s [YT]. Name chapters with words the person said. Keep it as long as the material, never
  padded: viewing time drops off as videos get longer [RES-Guo].
- **A cold open, then the start.** Open on the strongest line, the result or the question the video answers, in the
  first seconds, so the first 30 s deliver what the title and thumbnail promised; no greeting, channel intro or "in
  this video" before it [YT-hook]. Then one plain line that says what the video covers, and the first section.
- **Framing.** A wide frame shows the room, so the steps are wider apart in time: change framing on a new thought or a
  turn, about every 4 to 12 s as a starting range, not every sentence [OURS]. The same limits: 1.0 to 1.2 times, a step
  at the cut, a real jump cut on a change of framing. The person stays full frame; with horizontal footage keep their
  eyes near the upper third and the head clear of the top edge.
- **Long stretches.** One locked-off shot for minutes goes dead. If the person filmed cutaways of what they talk about
  (the thing, the place, their hands at it), use them as the second angle under the voice, a few seconds each. No stock,
  graphics or effects: that is another Look.
- **Captions, a steady 16:9 place.** Burned in, calm, the same family and colour rule as above, at about 46 to 52 px at
  1920x1080 (roughly 4.5% of the height) [OURS], centred, the bottom line's baseline about 8% above the bottom edge,
  inside the 90% graphics-safe area [RES-EBU]. One or two lines of up to 42 characters, at most about 20 characters a
  second [GEN-Netflix]; `chunk: 'sentence'`. If a caption would sit on the face (a low framing), lift the framing
  rather than move the captions up the picture. Also write an SRT beside the export and say in the hand-off that it is
  for search and translation: uploaded as YouTube captions as well, it would double the burned line when a viewer turns
  captions on.
- **Sound.** The same voice clean. Music stays about 15-17 LU under the voice, can drop out entirely under a long
  explanation and comes back at a chapter turn; never a loop that the viewer hears repeat. Export at -14 LUFS / -1 dBTP
  (letitedit's web setting).
- **End** right after the last point lands: a beat of the person's face and room tone, no "like and subscribe" tail
  unless they said one.

**Vertical clips on a YouTube video.** A phone held upright gives a 9:16 picture; a YouTube video is 16:9. Filling the
wide frame would mean cropping to a band about a third of the picture's height (the head or chin cut off, and soft at
about 1.8 times), and shrinking the picture or framing it with a blurred copy is never done. So the clip goes in as it
is: full height, centred, plain dark bars at the sides, the face the same size it is in the frame's height. That uses
about a third of the screen, which is a poor YouTube video; say so in the hand-off and offer a Short of the same
material, which suits these clips. Captions then sit in the picture's own lower part, centred under the face, not out
in the bars.

**Evidence for this section.**
- [YT] YouTube Help, "Video chapters": timestamps listed from 0:00, at least three, each chapter at least 10 s
  (platform rule; strong). https://support.google.com/youtube/answer/9884579
- [YT-hook] YouTube Help, "Measure key moments for audience retention", Intros: YouTube measures the share of
  viewers still watching after the first 30 s, and advises that those 30 s match the expectation the title and
  thumbnail set (platform guidance; medium).
  https://support.google.com/youtube/answer/9314415
- [RES-Guo] Guo, Kim and Rubin (2014), "How video production affects student engagement", ACM Learning at Scale:
  6.9 million viewing sessions of lecture videos; engagement fell as videos got longer, and videos mixing the speaker's
  face with other pictures held viewers better than slides alone (large observational study of lectures, not creator
  videos; medium).
- [RES-EBU] EBU R 95, "Safe areas for 16:9 television production": graphics kept inside the central 90% of width and
  height (broadcast standard; strong for broadcast, a reasonable margin for a web player whose controls cover the
  bottom when shown).
- [RES-WCAG] WCAG 2.2, success criterion 1.4.3: text against its background needs at least 3:1 contrast when large
  (accessibility standard; strong for contrast, not written for moving pictures).
- [GEN-Netflix] Netflix Timed Text Style Guide (English): up to 42 characters a line, two lines, up to 20 characters a
  second for adult programmes (industry practice; strong for subtitles).
- [OURS] the caption size and the 4 to 12 s framing range are starting points to adjust by eye on the video, not
  measured results.

## Weak spots
- One clip, one speaker, no hands in shot.
- With a single locked-off shot, the framing steps are the only picture change. On a longer video they'd need real b-roll to stay watchable.
- The cleaned voice and the mix have only been measured. Nobody has listened to them.
