# Sources for letitedit-captions

The library says almost nothing about captions: no style, size, font, position, safe zones, timing, line breaks,
word-pop, burn-in or SRT guidance. Rules here are therefore mostly [GEN]
and [OURS], with the few library remarks below.

## Library
| Tag | Source | Used for |
|---|---|---|
| JH 29:50 | Jenny Hoyos interview, Creator Science (`complementary-youtube/transcripts/creatorscience-jenny-hoyos.txt`, https://www.creatorscience.com/podcast/jenny-hoyos/) 29:50-30:05 | Reels viewers can mute, so her successful Reels were very visual with subtitles throughout (her observation, not a test) |
| JH 2:34 | same, 2:34-3:08 | a hook understandable without listening |
| JH 10:00 | same, 10:00-10:48 | first-frame layout: logo, item, a short centred label; the same layout across a series |
| JH 3:55 | same, 3:55-5:29 | about a 5th-grade reading level for on-screen words and scripts |
| ITE esNXgCJh-yk 14:08 | Inside The Edit, How to Start a Scene (`inside-the-edit/youtube/transcripts/esNXgCJh-yk.txt`) 14:08-14:31 | the 10-second test, once with sound and once muted |
| AOTC Porcelain | Art of the Cut, Porcelain War (`art-of-the-cut/articles/raw-text/art-of-the-cut-porcelain-war.txt`) L172, L204 | every daily translated and subtitled; screenings checked comprehension across the language barrier |

## General practice [GEN] (outside the library)
- Netflix Timed Text Style Guide, English: up to 42 characters a line, 2 lines, reading speed up to 20 characters a
  second for adult programmes (17 for children's), a minimum duration of 5/6 s and a maximum of 7 s, line breaks after
  punctuation and never between an article and its noun or inside a name.
  https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide
  (cited from general knowledge; not collected in the library).
- SRT for long-form, burned-in captions for muted feeds, emphasis restraint, digits for numbers, looks: common
  creator and subtitling practice, unsourced.

## Tools and platform data (2026-10-28)
- Speech captioning (`captions_from_speech`: chunk sizes, the 0.6 s pause, holds),
  `op_specs.py` (the captions op's fields and defaults), `edit_script.py` (captions as a subtitle feed; `burn_in`),
  `caption_layout.py` and `caption_layout_tools.py` (`fit`: defaults, rules, severities, fix options, fused-word
  detection, apply and plan ids), `INTEGRATION-caption_layout.md` (open windows take caption style changes as one undo step; the
  word-caption spacing cause of "it Without"),
  `graphics_templates\word_captions.py` (word-pop defaults), `brief_check.py` (claims checked on screen: caption tracks and
  graphics; numbers as the same amount).
- `letitedit_platforms` profiles checked 2026-10-19: TikTok covered areas from a third-party checker (low confidence),
  YouTube Shorts unconfirmed (low), Instagram Reels from its ad specs (medium; the bottom 35% covered), no zones
  documented for YouTube 16:9.
- The Subtitles panel's Export SRT.

## Local practice [OURS]
Use the actionable rules in the skill; no general audience-validation claim.
