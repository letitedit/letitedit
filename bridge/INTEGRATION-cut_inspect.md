# Integrating the cut inspector (`cuts` view of `letitedit_timing`)

Built 2026-10-28 by builder B2 to TIMING-SPEC.md. New files only; nothing shared was edited except adding the
`cuts.*` keys to `bridge/timing_thresholds.json` (29 keys in B1's `{value, unit, about}` form, appended as one block;
every other key and line left as it was).

| File | What |
|---|---|
| `bridge/cut_inspect.py` | The view and its measures: `inspect()` (= the registered `view()`), `analyse_side()`, `measure_join()`, `verdict()`, `draw_strip()`, `draw_overview()`, validation helpers `shift_test()`, `roll_test()`, `separation()`, CLI |
| `bridge/tests/timing/test_cut_inspect.py` | 20 fast tests (synthetic shots with known answers, ~25 s) + 4 real-footage tests (A/B render with labelled cuts, A/B project through the store, Tears of Steel, agreement with 34 blind labels) |
| `bridge/timing_thresholds.json` | `cuts.*` keys (thresholds; calibration edits values here, not code) |

Run the tests: `cd C:\LetItEdit\bridge && python -m pytest test_cut_inspect.py -q -m "not real"` (fast) or without
`-m` for the real-footage ones too (several minutes; the first run on a project renders its preview).

## 1. Registration: nothing to add

`cut_inspect.py` imports `timing_views` and calls `register_view('cuts', view, SUMMARY)` at import, so
`timing_signals.load_plugins()` imports it (it is listed in `timing_signals.PLUGINS`). Check:
`python -c "import timing_views; print(timing_views.views()['cuts'])"`.

## 2. Calling it

```python
letitedit_timing(source, view='cuts', start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief', images=2)
# Python: import cut_inspect; cut_inspect.inspect(source, start_s, end_s, items, cuts, options, detail)
```
- `source`: a project (.mlt / managed folder / 'live') or a video. Projects are measured on the store's preview render
  (B1's `signals(..., lanes=['edit'])`); without the store, a melt preview made here (cached by the timeline's
  fingerprint, render lock when > 30 s).
- `cuts`: cut numbers as this view lists them (1-based), seconds (float), `'f372'`, `'0:12.5'`, `{f}`/`{t}`/`{n}`;
  a frame/time with no cut is measured as a join anyway (kind `given`). `items`: the cuts into or out of those ids.
- `options`: `before`/`after` (strip frames, 6/6), `context_s` (1.0), `motion_window_s` (0.3), `max_cuts` (80),
  `images` ('auto' = overview + 3 worst, 'all', or a number), `overview`, `kinds`, `thresholds` ({key: value} for this
  call), `refresh`, `settings` (passed to timing_signals and joins), `sound` (false = skip B3's joins; its first call
  transcribes the source).
- Result: the common contract fields (via `timing_views.common_fields`), `cuts` (per cut: verdict, reasons, masks,
  rhythm, eye_trace, screen_direction, space, extra, sound, image), `counts`, `text` (one line per cut), `images`
  (overview first, then strips worst-first, or the asked cuts in order), `thresholds`, `units`, `method`,
  `options_used`, `options_doc`, `numbers_from`, `cuts_from`, `result_file`, `cached_cuts`.
- Per-cut results are cached in `C:\LetItEdit\cache\timing-cuts\joins\` by the frames that decide them (a project:
  the timeline's range fingerprint of the decoded window, so an edit elsewhere keeps them), settings, thresholds,
  the joins entry and `CODE_VERSION`.

## 3. Load (the PC's rule since the 28 Oct crashes)

One cut at a time by default (`workers` 1), one ffmpeg decode (2 threads) at a time, OpenCV capped at 4 threads
(`LETITEDIT_CV_THREADS`), the fallback melt render `threads=4`, libx264, no GPU. `shots.detect` in the no-store
fallback runs with 1 worker. B3's joins (called with `sound` on) may transcribe the source on its first call.

## 4. Suggested doc lines (for whoever owns them)

`tool_docs_v2.py` / GUIDE: the view summary is `cut_inspect.SUMMARY`. A skill line for letitedit-fine (fine cut):
"Look at the cuts with `letitedit_timing(project, view='cuts')`: the overview shows every cut with its verdict;
open the strips of the noticeable/jarring ones. The verdict says how visible a cut is, not whether it is right: a
jump cut in a vlog is visible on purpose. Fix blank/flash frames and sound flags; for eye-trace jumps consider
whether the next shot's subject can sit nearer where the eye was, or cut on a movement."

## 5. Validation (28 Oct 2026; data in C:\LetItEdit\cache\timing-tests\b2)

- Shift test (Pardo et al. 2021: real cuts vs the same cut with A ended 2/4/8 frames early, B entered 2/4/8 late,
  or both), paired AUC with bootstrap CIs, `shift\*.json`, `shift_summary.json`:
  398 professional cuts (Tears of Steel, Sintel, Big Buck Bunny, Caminandes): every measure 0.43-0.56; verdict
  severity 0.50-0.52. Significant but small: real cuts have LESS motion just after the cut (post-motion 0.43-0.45)
  and slightly larger eye/brightness jumps (0.55). Our edits (264 cuts): post-cut motion higher at real cuts
  (0.59-0.62); A/B renders: eye jump lower at real cuts than with B entered 8 frames late (0.40 = 0.60 in the
  expected direction). Roll test from source clips (80 cuts of our projects, `roll\`): motion decays around our
  cuts; verdict severity 0.46-0.54. In short: the measures describe a join; they do not find the best frame.
- Blind labels (34 cuts labelled from strips before seeing measures, `labels\`): exact agreement 21/34 = 0.62,
  Cohen kappa 0.27.

## 6. Calibration

Thresholds are `cuts.*` in `timing_thresholds.json`. The noticeable/jarring lines for eye-trace and brightness
are set from 398 professional cuts (75th / 99th percentile; see the report). To recalibrate against human choices,
`shift_test()` stores every real cut's full measures (`real_measures`), so verdicts can be recomputed for any
thresholds without measuring again.
