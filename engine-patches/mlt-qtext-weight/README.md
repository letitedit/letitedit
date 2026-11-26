# Fix: bold and other font weights never render in text and captions

**Problem (found 2026-10-08).** MLT's `qtext` producer, which draws Shotcut's Text clips, the `text` filter and the
`count` producer, converts the `weight` property with the Qt 5 formula `weight / 10 - 1`. Under Qt 6 that asks Qt for
a weight below Thin, so:

- `weight=700` (Bold) renders Regular in Arial, Verdana, Segoe UI... (fonts with no lighter face);
- variable fonts (Inter, Montserrat, Roboto...) render hairline-thin at every weight.

Measured with melt 7.41.0 (app build of 2026-09-27): Arial 400 and 700 draw identical pixels; Inter 400 and 900 both
draw Thin. `filter_qtext.cpp` (the qtext filter: Simple Text = dynamictext, the captions burn-in, timer, GPS text)
already has the Qt 6 branch, but passes the value straight to `QFont::setWeight`, which clamps anything above 1000
to its heaviest weight. letitedit writes plain italics as `style: italic, weight: w * 10 + 10` (`fonts.mlt_text_style`,
the form the producer's formula decodes), so plain italic text drawn by the filter came out in the boldest italic
(measured 2026-10-29: Inter italic 4010 drew 28,442 lit pixels, 400 drew 16,355, 7010 drew 28,442).

**Fix** (`mlt-qtext-weight.patch`, applies after `mlt-qtext-fontdirs` on MLT 63218a28):
- `producer_qtext.cpp`: the Qt 6 branch passes the CSS weight to `QFont::setWeight` directly; values above 1000 are
  decoded as `(w - 10) / 10` (the italic form); a missing weight is 400.
- `filter_qtext.cpp`: values above 1000 are decoded the same way; every weight up to 1000 is passed on unchanged, as
  before.

**Status.** The producer half was deployed on 2026-10-20 with the owner's OK, inside `libmltqt6-fontdirs-weight.dll`
(ROADMAP-PROGRAM.md, 07:35Z), and `fonts.engine_honours_weight()` has measured it since. The filter half and the
rebuild with the font folders under their new name (`LETITEDIT_FONT_DIRS`) came on 2026-10-30, built with
`..\build_modules.sh` into `..\modules\libmltqt6.dll` and verified on a copy of the app (deploy and checks:
`..\README.md`).

**Measured** (`..\check_engine.py`, lit pixels of the same words at 1280x720, size 120, 2026-10-30; frames in
`tests\engine-patches\frames\stock`, `copy` (the 20 Oct build) and `new`):

| | stock 7.41 | 20 Oct build | 30 Oct build |
|---|---|---|---|
| `text` filter (qtext producer), Arial 400 / 700 / 800 | 15,446 / 15,446 / 15,446 | 15,446 / 22,288 / 22,288 | 15,446 / 22,288 / 22,288 |
| Simple Text (qtext filter), Arial 400 / 700 / 800 | 15,443 / 22,288 / 22,288 | same | same |
| `text` filter, Inter 400 / 700 / 800 | 16,359 x 3 (a fallback font) | 16,359 / 28,371 / 28,371 (fallback font) | 16,160 / 24,529 / 27,864 (Inter) |
| Simple Text, Inter italic 400 / 4010 / 7010 | 16,355 / 28,442 / 28,442 | same | 16,187 / 16,187 / 24,501 |

(Inter comes from letitedit's font library: only the 30 Oct build loads it, see `..\mlt-qtext-fontdirs`.)

letitedit still writes the face's style name for bold (`style: Bold`, `Black`, `SemiBold`...: `fonts.mlt_text_style`),
which every build matches exactly, so its own captions and text effects render the same on all three builds; what
changes is text made by hand in the editor (font dialog -> Bold on a Text clip) and plain italics.
