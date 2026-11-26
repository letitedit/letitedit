# Caption styles by mode

Read on demand from letitedit-captions section 2. The library has no caption-style evidence; this table is general
practice [GEN] with local editing practice [OURS]. The brief, the person's Look and a `reference` video win.

| Format and mode | Running captions | Style | Notes |
|---|---|---|---|
| Vertical short, a person talking to camera (vlog, comedy, explainer, founder, whatever the feel) | all speech, burned in | word-pop: `pop`, `chunk: short`, `max_chars` about 16, one line | one highlight colour; check peak frames |
| Vertical short, calm or reflective, or an older audience | all speech, burned in | calm: `chunk: sentence`, 1-2 lines | "less flashy" lands here |
| Vertical short, interview or podcast excerpt | all speech, burned in | calm, or `karaoke` (whole line shown, the said word lit) | the words matter more than the energy; names go in a lower third (graphics) |
| Vertical tutorial or product demo | all speech, burned in | calm | step labels and pointers carry the structure (graphics) |
| Music-led montage, travel, product mood piece, process montage | none | short chapter or step text instead (graphics) | chapter text carries the structure [OURS] |
| Long-form YouTube (talk, tutorial, vlog) | an SRT the viewer switches on | burn in only key words, or when the series does | |
| Documentary | an SRT; burned in only for another language or hard-to-hear speech | calm | one documentary subtitled every daily and checked comprehension at screenings [AOTC Porcelain] |
| Another language, or speech the viewer can't make out | burned in | calm subtitles | spell names exactly; keep the meaning |

## Looks [GEN]
- **Calm:** a plain bold sans in the Look's caption font; light text with a dark outline or a soft dark box; low
  or bottom; no motion beyond a quick fade.
- **Word-pop:** a heavy sans; light words with a dark outline; the active word in the Look's accent colour; uppercase
  only on 1-3-word pages; a gentle pop (`pop_scale` about 1.1-1.15); a box behind the words when the footage is busy
  (`box` in the word-caption params).
  **Heavy means a heavy face by name.** `font: "Montserrat"` is the regular weight, and a separate `weight` key is ignored: write
  the weight in the name (`"Montserrat Black"`, `"Inter:900"`) or a family drawn heavy (`"Archivo Black"`, `"Anton"`; `letitedit_fonts`). One starting point on a 1080-wide talking head: uppercase, 84 px, a 9 px outline, about 2.3 words a line, the spoken word recoloured and growing from 85% to 112% in 110 ms [OURS]. `size` is in pixels of a
  1080-high frame, so 84 px on a 1920-high frame is about 47; check what `letitedit_caption_fit` leaves.
- **Size:** from the Look, never under caption_fit's readable minimum; bigger reads better on phones, as long as
  two lines still fit inside the uncovered area.
- **Series:** the same caption look across a series, so viewers recognise it [JH 10:00 (series framing)].

## Caption checks [OURS]
- Avoid accidental one-word lines and fragments.
- Check misheard words and capitalise names correctly.
- Keep captions off faces and within the footage, not side bands.
- Caption the opening speech of a Short; do not leave the first 8 s uncaptioned.
- Inspect tiny or uneven sizes during the pop, not just at rest.
- Check word spaces and separation at peak scale.
