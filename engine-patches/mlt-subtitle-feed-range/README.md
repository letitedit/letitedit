# Fix: a caption that runs to the end of the video is never drawn

**Problem (found 2026-10-29, BACKLOG-HISTORY.md "a caption that runs to the video's last frame is never burned in").** The
editor's own captions (the Captions panel's speech-to-text captions, typed cues, imported SRT) are a `subtitle_feed`
filter on the timeline's main tractor holding the SRT text, plus the burn-in `subtitle` filter that draws the feed's
current cue. A cue whose end reached the start of the video's last frame, or later, was drawn on no frame at all:
on a 2 s video (frames 0-59 at 30 fps) a last cue from 1.2 s showed when it ended at 1.933 s, and vanished for its
whole length when it ended at 1.967 s, 2.000 s or 2.5 s. Speech-to-text and SRT files often end the last cue with the
video (or after it), so the last caption went missing. letitedit's AI captions end every cue a frame early to dodge it
(`edit_script.fit_captions`).

**Cause.** `src/modules/plus/filter_subtitle_feed.cpp` (MLT 7.41, commit 335d0093 "Fix Exporting marker ranges as
separate videos") passes on a cue only when it lies wholly inside the producer's in..out range, and takes the range's
end as `out * frame duration`: the START of the out frame, although `out` is inclusive. On the main tractor
(in = 0, out = last frame) every cue ending after the last frame's start failed the test. Any range render
(`melt project in=N out=M`) also dropped every cue crossing either edge of the range, for its whole length: the
editor's Export > marker ranges, `letitedit_export`'s 60-second chunks (`bridge\render_queue.py`: a caption crossing
a chunk join was missing from both chunks of a long video) and `letitedit_check_range`'s preview.
`letitedit_check_frames` was not affected (it renders one-frame cuts of the whole timeline).

**Fix** (`mlt-subtitle-feed-range.patch`, module plus, MLT 63218a28): the range ends where the out frame ends
(`(out + 1) * frame duration`); a cue that overlaps the range is passed on, its start and end positions clipped to the
range (so the avformat consumer's subtitle stream never gets a negative or out-of-range time). Cues inside the range
are passed on exactly as before. Built with `..\build_modules.sh` into `..\modules\libmltplus.dll`.

**Measured** 2026-10-30 (`..\check_engine.py`, lit pixels of the burned-in caption on a 2 s, 30 fps video, frames
0-59; frames in `tests\engine-patches\frames\copy` and `new`):

| last cue (from 1.2 s) ends at | stock 7.41 module (also the 20 Oct app) | patched |
|---|---|---|
| 1.933 s (before the last frame) | drawn: frame 50 = 7,032 | same |
| 1.967 s (the last frame's start) | never drawn: frame 50 = 0 | drawn through frame 58 |
| 2.000 s (the video's end) | never drawn | drawn through frame 59 (the last) |
| 2.5 s (past the end) | never drawn | drawn through frame 59 |
| range render in=15 out=44 of a 3 s video, cues 0-1 s and 1.2-3 s | nothing drawn on any frame | each cue drawn on its frames inside the range |

Real projects (`..\compare_frames.py`, both engines loading the same fonts): a copy of the style-import test video
whose last caption ("And", 39.34 s) ends with the video at 40.000 s: today's engine draws nothing from 39.34 s, the
patched one draws it through the last frame; the editor's own preview engine (a test window per app copy) shows the
same. Every other sampled frame of 12 projects (84 frames: captions, Simple Text, the style library's effect-heavy
test videos, two of the owner's 2.5-minute caption projects) is pixel-identical.
