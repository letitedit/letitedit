# Caption tool recipes

The bridge modules `op_specs.py`, `timeline_speech.py`, `caption_layout.py`, `caption_layout_tools.py`,
`graphics_templates/word_captions.py`, `brief_check.py` and `edit_script.py` define these operations.
Confirm current field names with `letitedit_guide('letitedit_caption_fit')`.

## 1. The captions op (`letitedit_timeline_apply`)
`{op: captions, track, cues | from_speech, chunk, max_chars, max_lines, style, animate, fix, fillers, burn_in}`

| Field | Default | Notes |
|---|---|---|
| `from_speech` | - | `true`: captions of everything said on the timeline (runs after the other edits in the same apply) |
| `cues` | - | `[{start, end, text}]` written by hand (timeline seconds) |
| `chunk` | `short` when animated, else `sentence` | see below |
| `max_chars`, `max_lines` | 42, 2 | sentence chunks only |
| `style` | the Look's | `{font, size, fill, outline, highlight, position, ...}`; `position` top / middle / bottom or a share of the height |
| `animate` | none | `pop`, `karaoke`, `highlight`, `typewriter`, `bounce`: word-by-word graphics on a video track |
| `fix` | none | `{heard: Written}`: whole single words, any case, punctuation kept (`{"acme": "Acme", "ac": "A/C"}`) |
| `fillers` | false | true keeps um / uh |
| `burn_in` | true | false: a subtitle track that is not drawn on the picture (for the SRT) |

Chunking (`timeline_speech.captions_from_speech`):
- `sentence`: up to 42 characters x 2 balanced lines; a new cue after a pause over 0.6 s, at a sentence end once the
  cue has 3+ words, or when it would pass 6 s.
- `short`: up to 4 words and 22 characters on one line; a new cue after a 0.6 s pause or a sentence end once it has
  2+ words.
- Both: a lone word joins the cue next to it when said together; each cue holds 0.15 s past its last word, lasts at
  least 0.8 s, never runs into the next cue or past its clip; the first word after a sentence end is capitalised; "i"
  becomes "I".
- `fix` changes single words only. A multi-word form (spoken "twelve dollars" shown as "$12") needs the cue text
  edited with `cues`; it is a spelling form, not a change of meaning.
- Native captions are a subtitle feed named after the track, burned in by the editor's Subtitle Burn In filter; animated
  captions are `word_captions` graphics (defaults: `size` 84, `fill` light, `highlight` accent, `outline` dark,
  `outline_width` 7, `position` bottom, `margin_y` 0.12, `max_width` 0.82, `center_x` 0.5, `pop_scale` 1.15,
  `shrink_to_fit` true). `center_x` centres the lines over footage that isn't centred in the frame.

## 2. `letitedit_caption_fit`: measured layout
Nothing in the project changes until `apply=True`; the approved words are never changed or dropped (only line breaks,
grouping, cue edge times, size, place, outline and pop strength change, plus a space restored where the cached
transcript shows two words), and every proposal is checked for that. Renders use the export engine, so outlines,
shadows, font matching, shrink-to-fit and the biggest moment of a pop are the real thing.
- It reads the saved project (a window's unsaved changes are not seen) and cached transcripts only (nothing is
  transcribed here; cues without word times keep their grouping and are listed as unchecked): save and run
  `letitedit_words(project=...)` first.
- A native caption track has one place and style for all its cues; `native_mode='tracks'` moves cues that need
  another place to a caption track of their own (`<track> (top)`); word captions take a place per cue.
- With the project open in letitedit, applying a plan puts the regrouped cues and the caption style (place, size,
  outline) into the window as one undo step. A window of an older letitedit build takes cue text and times only: a saved
  project goes through the file (the window reloads), a window with unsaved changes refuses and says to save first.
- About 15 s of layout for a 45 s short with 37 animated cues, plus 15-40 s of rendering.

| Parameter | Default | Use |
|---|---|---|
| `platform` | none | the target app (`tiktok`, `youtube_shorts`, `instagram_reels`, `facebook_reels`...): its covered areas |
| `output` | the project size | export size as `'1080x1920'` (same shape only) |
| `tracks` | every visible caption layer | which to lay out, in order; the others (and each laid-out layer) are obstacles |
| `style` | the track's own | a look to apply first (native: the captions op's keys; word captions: the template's params) |
| `lock` | none | properties it must not change: `size`, `outline`, `pop_scale`, `position`, `center_x`, `max_width` |
| `min_size_px` | 3.4% of the short side (37 px on 1080) | the readable minimum at export size; text is never shrunk below it |
| `protected` | none | `[{box: [x0, y0, x1, y1] (fractions or px), start?, end?, hard?, name?}]`, or a moving `{keys: [[t, box], ...]}`: the object the shot is about, a logo |
| `faces` | `auto` | `hard`: never over a face; `off`: ignore faces |
| `placements` | tall: bottom, low, middle, high, top; wide: bottom, top | the allowed places (the current one is always a candidate and kept when nothing is wrong) |
| `prefer` | the one nearest the current captions | a place to lean toward |
| `regroup` | `auto` (problem cues and their neighbours) | `all`, `none` |
| `native_mode` | `track` | `tracks` (see above) |
| `max_lines` | 2 (3 when the track already uses 3) | |
| `max_cps` | 20 | reading speed in characters a second (native captions) |
| `min_duration_s`, `max_duration_s` | 0.8 native / 0.4 word captions, 7 | |
| `keep_together` | none | phrases never split across lines or cues (multi-word names; numbers with units are kept together anyway where possible) |
| `min_gap_em`, `peak_gap_em` | 0.12, 0.04 | the space kept between words, and while a word pops |
| `platform_zones` | `hard` | `soft` avoids when possible; `off` ignores the app's overlays |
| `render_check`, `max_frames` | true, 40 | rendered before / after checks of the riskiest frames |
| `apply`, `plan_id`, `expected_revision` | false | write the plan; apply or show an earlier plan; refuse if the project changed |

The result: `frame` (size, safe rect, covered zones, minimum size, placements), `layers` (place used, style changes,
regrouped cues, spaces restored), `changes` (ops in the timeline vocabulary), `cues` after the fit, `violations` (kind,
severity, stage before or after, cue, times, worst moment, measured, limit, evidence), `summary` (counts before and
after), `unresolved` (what no allowed choice satisfies, with options), `render_check`, `preview_artifacts` (a before |
after sheet), checked and unchecked ranges, warnings. A plan is refused when the project, a font, the text engine or
the template changed since (run it again).

| Severity | Kinds |
|---|---|
| error (must fix) | `fused_words`, `missing_space`, `too_small`, `outside_frame`, `covers_text`, `protected_region` |
| warning (look, then fix or explain) | `fused_at_peak`, `suspected_missing_space`, `auto_shrunk`, `too_many_lines`, `outside_safe`, `platform_overlay`, `covers_face`, `reading_speed`, `too_short`, `overlapping_cues` |
| info | `too_long`, `bad_break`, `render_mismatch` |

Fix options it suggests: `covers_face` -> another allowed place, `native_mode='tracks'`, word captions, or
`faces='off'`; `platform_overlay` -> a smaller size, fewer words per cue, `platform_zones='soft'`; `fused_words` ->
a thinner outline, a font with a wider space, less pop; `fused_at_peak` -> less pop, a thinner outline, karaoke or
highlight style; `too_small` -> shorter cues, a narrower font; `reading_speed` -> allow more (`max_cps`) or let the
line play longer in the edit; `too_many_lines` -> regroup, allow more lines, a smaller size.

## 3. Platform covered areas (from `letitedit_platforms`; read live values, don't copy these)
| App (9:16) | Covered | Source status |
|---|---|---|
| TikTok | top 6.8%, bottom 19.1%, right 11.1% | third-party checker, low confidence |
| YouTube Shorts | top 6.25%, bottom 15.6%, a right column | unconfirmed, low |
| Instagram Reels | top 14%, bottom 35%, both edges | official ad specs, medium |
| YouTube (16:9) | none documented | - |

A file meant for all three vertical apps keeps its captions above Reels' bottom 35%.

## 4. Names, numbers and claims
- The gate (`brief_check.py`) passes a claim when it is heard exactly in the render; it also needs the claim on screen
  (caption tracks and word-caption or title graphics): a name exactly (a capitals-only difference fails), a number as
  the same amount in any form ("$12", "12 dollars", "12 bucks"); a missing or different number fails.
- Build `fix` from: the brief's `claims`, the person's word list (Look settings), names in `must_keep` lines, and every
  `(?)` word (under 45% sure) near a name or number in `letitedit_words(project=..., per_word=True)`. Listen to unsure
  words before deciding (`letitedit_check_range`).

## 5. SRT
1. `{op: captions, track: 'Subtitles', from_speech: true, chunk: 'sentence', burn_in: false}`: a subtitle track from
   the edit's words, not drawn on the picture; fit it like any caption track if it is ever burned in.
2. The person exports it: Subtitles panel, choose the track, Export SRT. With files, write the SRT yourself from the
   cues `letitedit_timeline_read` shows for that track, next to the export.
3. Make it again after any edit that changes the words or their timing.
