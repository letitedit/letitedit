# Sources for letitedit-finish 0.2.0

| Tag | Document | Times / lines | Used in |
|---|---|---|---|
| AOTC Porcelain War | art-of-the-cut-porcelain-war.txt | L218-244 (grade during the edit only when colour carries meaning, with simple exposure, white-balance and contrast moves); L280-306 (animation only with narrative meaning) | FINISH-1, FINISH-4 |
| JH | Creator Science interview | 29:50-30:05 (Reels are watched muted, so captions run throughout) | FINISH-5 |
| YT | `letitedit_platforms` (each fact with its source and how sure) | covered areas per app, sizes, frame rates | FINISH-6, FINISH-7 |
| RES Apple | Apple Podcasts audio requirements, https://podcasters.apple.com/support/893-audio-requirements | -16 LKFS, peaks at most -1 dBFS | FINISH-7 |
| RES EBU R128 | EBU R128, https://tech.ebu.ch/docs/r/r128.pdf | -23 LUFS, true peak at most -1 dBTP | FINISH-7 |
| GEN | -14 LUFS for web and social: common streaming normalisation (Spotify, https://support.spotify.com/us/artists/article/loudness-normalization/); no official YouTube, TikTok or Instagram target was found | | FINISH-7 |
| OURS | local implementation | Passing measured checks does not override the critic's findings. | FINISH-8 |
| RES Timeline-Bench | https://arxiv.org/html/2609.35143 | agents claimed full success in 93% of runs | FINISH-8 |
| GEN | general practice, unsourced | the speech-cleanup order and checks; graphics before captions; the SRT; per-platform safe-zone checks | FINISH-2, FINISH-3, FINISH-4, FINISH-5, FINISH-6 |

Tool facts used:
- `letitedit_match_shots`: proposes first, writes only on apply, one undo
  step, an editable Color Grading effect per clip, never touches footage; `reference`, `neutral_regions`,
  `ignore_regions`, `keep_looks` (golden-hour and night pictures left alone by default), `same_scene`; a project open
  with unsaved changes ('live') must be saved first.
- `letitedit_fix` voice: `atten_lim_db` 18 by default (100 = no limit),
  `separate` false and `dereverb` false by default,
  `rest_gain_db` for the rest stem when `separate` is true.
- `letitedit_export`: `preset`, `loudness`, `true_peak` (default -1.0),
  `platform`. The loudness table itself is letitedit-sound's section 9, the single source.
- Graphics and captions tools are named only through their skills: `letitedit_annotate` (letitedit-graphics),
  `letitedit_caption_fit` (letitedit-captions), `letitedit_soundtrack` and the `score` op (letitedit-sound).
- The gate: `letitedit_review_bundle`: `video`, `project`, `brief`, `critic`,
  `engine`; writes `review_bundle.json` and `review.md`.
