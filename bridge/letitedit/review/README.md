# letitedit\review

Checks and review: the quality gate, the critic, the review bundle and the finishing fixes.

- `brief_check`: Does the edit keep what the person asked for? Checks a brief's hard requirements against a render (its own transcript) and, when given, the project timeline.
- `checks`: Fast, truthful checks of a saved timeline, rendered by melt (the same engine as the final export).
- `fix_post`: Fix-in-post: repaired copies of the part of a source a clip uses, made once and cached; the original is never touched.
- `review_bundle`: Everything a reviewer needs to judge one export, covering the whole video, and one delivery verdict.
- `review_memory`: What a video's reviews remember, and who can fix what.
- `shot_match`: Shot matching: bring clips toward a reference shot's exposure, white balance and (gently) tone, written as an editable Color Grading effect on each clip (Shotcut's own lift/gamma/gain filter: change it in the filter panel, with...
- `story_integrity`: Checks that a Short still contains the story selected before editing.
- `turbo_check`: The lightest check that still catches a video that is broken: measured, free, a few seconds, no AI.
- `craft_checks`: Measured craft facts for the review: the cuts a viewer can see, an insert held too briefly to read, how busy the opening picture is against the rest of the video, and how long the picture runs after the last word.  (no old name: imported as `letitedit.review.craft_checks`)
- `dense`: Dense videos: what the eye and ear follow, event by event, measured in code before any reviewer looks.
- `final_check`: The final export against the preview that was reviewed: a short technical check of the final file (its length, loudness and true peak, black or frozen stretches, sound and picture in step with the preview, the picture the same as the...
- `note_targets`: A revision note's measurable target, kept: the length, the music's level or the captions' size a note asks for, measured on the cut the review reads and compared with what the note asked.  (no old name: imported as `letitedit.review.note_targets`)
- `overlay_clash`: Overlay words over the video's own text: words a caller has letitedit add to each delivered file after the export (the Studio's `overlay_text`, contract section 6), measured against the text and graphics the video draws itself under the...  (no old name: imported as `letitedit.review.overlay_clash`)
- `picture_words`: The picture under the words: a camera move the viewer can't read while a line is said, above all a line that points at something to be seen, and b-roll in the footage that the cut never shows.  (no old name: imported as `letitedit.review.picture_words`)
- `review_order`: The order of a review: the code checks first, then one critic, a second critic round only for a real defect, and no critic on a video that hasn't changed.  (no old name: imported as `letitedit.review.review_order`)
- `window_edge`: The subject at a window's edge: in a layout that puts the footage in a window (the picture drawn smaller than the frame or partly off it, or partly under an opaque panel), whether what each shot is about sits at or past the window's...  (no old name: imported as `letitedit.review.window_edge`)

Each module here also answers to its old name in `bridge\` (a small alias file: one module object under both names); inside the package, import the real name. What the other jobs may use from here: `IMPORTS.md`. The whole map: `CODEMAP.md` at the top of the repository.
