# letitedit-shorts: the evidence and the tools' details behind the checklist

Read the part you need. Every rule is in SKILL.md; this file holds the reasons, the evidence and the
tools' details behind some of them.

## The evidence

**Evidence.** One short-form source: Jenny Hoyos (Creator Science podcast, 2023), reporting her own channel's
analytics (a young audience, about 10M views a video). She says every channel has to read its own data [JH 6:29,
17:56], so the person's own results, when they exist, beat every number here. Openings and endings also draw on
professional editors. Tags: [JH m:ss] Hoyos; [ITE id mm:ss] Inside The Edit (one teacher); [AOTC film] Art of the
Cut; [YT] a platform's own docs or policy (sizes, lengths and covered areas through `letitedit_platforms`); [GEN]
general practice, unsourced. Sources: `references/sources.md`. Her examples and the professional opening and
ending templates: `references/method.md`. Platforms, reframing and export in detail: `references/platforms.md`.

## 0. Not frantic by default

- **Why:** her YouTube Shorts did best slower and more story-led [JH 29:13]; the teaching line that social video is
  cut at one fast pace is a generalisation without data [ITE vUIwB7i-6IQ 04:17]; over-tight cuts look insecure and
  can feel longer [AOTC Greatest Night in Pop].

## 5. The middle: change, expectation, twist

- **5.2** Meet the expectation the foreshadow set, then turn it if the footage has a turn (her $5 gift that breaks
  after the reveal) [JH 16:32-17:34]; professionals edit for surprise, the third beat breaking the pattern
  [ITE 4s7WdcyV1H4 12:31]. Never manufacture a twist. Mode-specific turns (a repair's failed first fix) belong to
  the mode playbook (letitedit-modes). Check: what the foreshadow named happens on screen, and a cold-open moment
  recurs in place.

## 6. Pay off, then end

- **6.1 Do:** end right after you have done what you said you would do [JH 0:42]. The payoff is the last beat, on
  screen, not only in the narration. Trim the dead last second: cutting one final second lifted one of her shorts
  from 83% to 88% retention [JH 7:07-7:36]; on a 30 s short each second is about 3% of it [JH 7:36]. Her endings
  read as abrupt but satisfying [JH 25:06].

## 7. Rewatch, and loops only when they fit

- **Do:** aim for a short people finish and watch again: her ~85% stay rate with ~95% retention only adds up
  because viewers rewatch [JH 8:31-9:07]. Design a loop only when the content invites it: the last line runs into
  the first, or the last frame matches the first; no end card, no fade [GEN: no source covers loop technique].

## 9. One edit per platform (low confidence)

- **Do:** when the brief lists several platforms, cut each its own version instead of posting one everywhere: the
  same short did well on one platform and poorly on another, then the reverse [JH 28:07-29:13]. Her reading of each platform: SKILL.md section 9.

## 10. Reframe to 9:16

- **Where an important object must stay in frame** (the broken part, the product, the face, the hand doing the
  step), say so: `letitedit_reframe` (or `letitedit_versions` with `reframe={'mode': 'solve', 'keep': [...]}`) keeps
  several named subjects in the crop on a smooth path and reports how much of the time each is in; name the part
  with a box (`{label, box, at}`), since it can't know which object is being shown. Never trust the centre crop
  with it. Never stretch; upscale at most 1.25x on 1080p sources [GEN]. When the required subjects can't share one
  crop, take its split or inset offer, or `reframe` fit 'fit' (bars or a blurred fill), and tell the person. It
  loses parts in fast handheld close-ups: add boxes where its plan warns.
