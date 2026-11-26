# Integrating the 'meaning' lane and view (B6, timing perception layer)

Built 2026-10-28 to TIMING-SPEC.md. Measurement gives the timing (the store's motion events and shots); the local
vision model (Qwen/Qwen3.5-4B, 4-bit, through `model_tools.describe` and its GPU turn) gives the meaning: what
happens, a few words, whether the step is finished by the end, shot size, camera, main subject. Every label type
carries the accuracy measured on a labelled set; types under 80% are kept but marked `~` and `trusted: false`.

## Files (all new; nothing shared was edited)

| File | What |
|---|---|
| `bridge/motion_meaning.py` | The lane (`compute_lane`), the view (`view`), `meaning()` for direct use, the fallback motion events, prompts, parsing, the per-item answer cache |
| `bridge/motion_meaning_accuracy.json` | Measured accuracy per label type (like `factlog_accuracy.json`), per design, per footage set, held-out split, answer precision (confidence), measured camera labels, speed |
| `bridge/tests/timing/test_motion_meaning.py` | pytest: fast tests (no GPU), footage tests on 3 sets, label-set re-score, GPU tests (skip with `LETITEDIT_TEST_GPU=0`) |
| `bridge/timing_thresholds.json` | `meaning.*` keys merged in (`{value, unit, about}`), nobody else's keys touched |
| `C:\LetItEdit\cache\timing-tests\b6\labelset\` | The label set: `items.json` (103 items, half-open ranges), `labels.py` (references), `sheets\` (what they were labelled from), `answers_*.json`, `grades_what.json`, the scripts that build, run, score and write the accuracy file |

Run the tests: `cd C:\LetItEdit\bridge && python -m pytest test_motion_meaning.py -q` (fast part ~30 s;
`LETITEDIT_TEST_GPU=0` skips the three model tests, which take ~1-2 min on first run and are cached after).

## 1. Registration: nothing to add

`timing_signals.load_plugins()` imports `motion_meaning` (it is listed in `timing_signals.PLUGINS`); at import it registers:

```python
ts.register_lane('meaning', compute_lane, depends=('motion_events', 'shots', 'motion'), version=LANE_VERSION)
tv.register_view('meaning', view, VIEW_SUMMARY)
```

Checked: `ts.load_plugins()` lists `motion_meaning`, `ts.lanes()['meaning']` and `timing_views.views()['meaning']`
are present, so `letitedit_timing(source, view='meaning')` works with no edit to `timing_tools.py`, `letitedit_mcp.py`
or `letitedit_ai.py`. `compute_lane.defaults` carries DEFAULTS plus a stamp of the prompt and of the accuracy file,
so the store's cached lane is recomputed when either changes.

## 2. Requests to B1 (timing_signals / timing_motion) — please read

1. **Keep 'meaning' out of default lane lists.** `signals(source)` with `lanes=None` computes every registered
   lane, and this one runs the vision model on the GPU (about 3-5 s per event or shot after a 20-30 s model load;
   `max_items` caps it at 150 per call). On 28 Oct 09:55 a store call with all lanes computed it (1 shot, 63 s).
   The map, slow, cuts, sync and speech views already pass explicit lane lists, so nothing breaks today. Suggested
   change in `signals()`: an `expensive=True` (or `default=False`) flag in `register_lane` and
   `want = [n for n in _LANES if not _LANES[n].get('expensive')]` when `lanes` is None. Until then, callers who
   want every cheap lane should name them.
2. **`_merge_meaning_sizes` treats the meaning item's `f1` as inclusive** (`min(b + 1, s['f1'])`). Meaning items
   use the store's half-open ranges (`f1` = first frame after), so use `min(b, s['f1'])`. The size words are
   `close-up | medium | wide` in `labels.size.value` and in `size`; `labels.size.trusted` and `.accuracy` say how
   far to believe it (shot size measured at ~80%, see section 4). The code in `timing_motion._shots_lane` that
   reads an optional `meaning` dependency looks for the size word in `m['label']`; that path never runs
   (meaning depends on shots), and `label` is the action there, not the size.
3. **Frame grid of odd phone files.** `_video_info` takes the nominal `r_frame_rate`; `quick\hands-work-closeup.mp4`
   says 120 fps but holds 752 frames over 30.0 s (25 fps of frames), so `frames` covers 6.3 s of a 30 s clip at
   120 fps. `motion_meaning.video_grid()` uses the real rate when the frame count disagrees with the nominal rate
   by more than 15%; inside the store the lane uses `ctx['fps']` / `ctx['frames']` as given.

## 3. The lane ('meaning') and the view

Lane data (besides `method`, `version`, `settings`, `warnings`, `unsupported`):

- `meaning`: items `[{kind: event|shot, id, f0, f1, t0, t1, f_peak, t_peak (events), shot, part, label, what,
  completes: true|false|null, size, camera, subject, confidence, accuracy_basis, labels: {action, completes, size,
  camera, subject: {value, answer, confidence, accuracy, trusted, from}}, frames: [{f, t, role}], cached, raw}]`.
  Ranges are half-open on the store's frame grid. `label` = what happens (closed vocabulary), `confidence` = how
  often that answer was right on the label set (not the model's own say-so).
- `accuracy` per label type (`accuracy`, `n`, `trusted`, `from`), `legend` (one line), `vocabulary`,
  `checked_ranges` / `unchecked_ranges` (items over `max_items`, unbuilt, too short), `events_from`, `model`,
  `timing` (items, asked, cached, model seconds per item), `gpu` (the room report).

Settings (`signals(settings={'meaning': {...}})`, or `timing_thresholds.json` `meaning.*`): `design` (6f),
`max_items` (150), `min_accuracy` (0.8), `vocabulary` (general | repair | travel | talk), `camera_from`
(measured | model), `build` (false: cached answers only), `range_s` ([start, end] inside the analysed range), and
the frame choices (`pre_s`, `post_s`, `shot_max_s`, ...). Everything that changes the result is a setting, so it
is part of the store's cache identity.

View `meaning` (`letitedit_timing(source, view='meaning', start_s, end_s, items, cuts, options, detail)`): PNG pages
(a time axis with shots and numbered events coloured by what happens, then cards with each item's frames before /
at the peak / after, its label and confidence, `~` on untrusted types), `lines` (one text line per item),
`meaning` (slim items in `brief`; the full ones in `full_file`), `options_used`. `items` narrows to edit item ids
(edit lane), `cuts` to the events and shots within 1 s of the given cut frames (ints) or times (floats).
Options: any setting above, `kinds`, `per_page`, `pages`, `refresh`, `settings` ({lane: {...}} passed to the
store).

Direct use: `motion_meaning.meaning(source, start, end, settings=..., build=..., kinds=...)` goes through the store
(`signals(lanes=['meaning'], settings={'meaning': {..., 'range_s': [start, end]}})`) when it exists, else labels
this module's fallback events (residual-motion bursts in `shots.features`, shots from `shots.detect`; a project is
rendered small by melt, under the render lock past 30 s).

## 4. Measured accuracy (label set, design 6f, Qwen3.5-4B 4-bit)

Label set: 103 items (80 motion events, 23 shot parts) from 4 footage sets (quick 21, broll 28, story-mini 27,
story-rear-ac 27), labelled by Claude from 8-frame sheets before any model answer was read; 30 items held out (the
prompt and the design were chosen on the other 73). "Strict" = the reference's first answer; "defensible" = any
answer the reference listed as a fair second reading (written blind, before the model ran).

| Label type | Strict (all 103) | Defensible | Held-out (30) | Notes |
|---|---|---|---|---|
| what happens (`label`) | 0.71 | 0.90 | 0.73 | right 12/12 when it says `vehicle moves`, 0/4 for `part moves`; calls most `tool use` `hands working` (6 of 9) |
| done (`completes`, n=48 yes/no refs) | 0.75 | - | 0.83 (n=12) | always answering yes would score 0.67; never answers `unclear`; said yes on 45 of the 55 items whose reference is unclear |
| shot size | 0.80 (0.796) | 0.88 | 0.73 | `wide` right 12/12; calls 14 of 24 medium shots close-up |
| camera, model | 0.64 | - | 0.57 | replaced by the measured label (default `camera_from='measured'`) |
| camera, measured: store `camera_label` | 0.79 | - | 0.77 | not tuned on this set; 18 of 28 locked-off shots read handheld, zoom or pan (subject motion near the lens) |
| camera, measured: fallback shifts | 0.82 (all) | - | 0.77 | thresholds fitted on dev (jitter 0.064, drift 0.035 frame widths/s) |
| subject | 0.54 | 0.80 | 0.43 | over-answers `hands` (44 said, 18 right) |
| words (`what`, graded 1 / 0.5 / 0) | 0.68 | - | 0.63 | right object and action about half the time; generic ("the camera shakes and blurs") on fast moves |

Every type is under 0.8 strict, so every label is marked `~` and `trusted: false`; `confidence` per answer comes
from the precision table (e.g. `vehicle moves` 0.96, `hands working` 0.73, `part moves` 0.24; done `yes` 0.78,
`no` 0.68).

Frames shown (the 3 vs 6 vs strip question), all 103 items: done right on 36/48 with 6 separate frames, 33/48 with
3 (before / peak / after), 33/48 with one image tiled from 8 frames; what happens 0.71 / 0.66 / 0.67; shot size
0.80 / 0.80 / 0.79. Six frames is the default; no frame design makes "done" reliable.

Speed on this PC (RTX 2070 SUPER, shared GPU): model time per item, median, 4.5 s with 6 frames (2.7 s with 3,
3.2 s for the strip); uncontended runs gave 2.6-4.4 s, runs sharing the GPU with other builders' whisper jobs
6-7 s. Plus about 0.4 s per item to pull 6 frames, and 20-60 s to load the model once per process (more when
another process had the GPU and the worker had to reload). Answers are cached per item by frame content, so a
second look at the same footage asks nothing.

Completion-only prompts (same 6 frames, one question tied to the last frame): "done?" alone flipped the bias to
"no" (0.65 on all 48, 0.69 dev); the reversed "still going?" scored 0.67; requiring two prompts to agree reached
0.70-0.78 only by leaving about a quarter unanswered. The joint answer stays (`completes_only_prompt` in the
accuracy file).

Spot check on the store's own events (IMG_0516 15-45 s: 11 events + 4 shot parts, 5.5 s per item): every label
defensible; about 5 of 12 say `hands working` where a pry bar is in hand (`tool use` is stricter), and the words
sometimes misname the yellow tool handle.

Load rule (after the 28 Oct power crashes): the model runs only through `model_tools.describe` (GPU turn); frame
grabs use `ffmpeg -threads 4` (`LETITEDIT_FFMPEG_THREADS`) two at a time (`LETITEDIT_MEANING_FRAME_WORKERS`).

## 5. Suggested doc and skill lines (owners decide)

- `GUIDE_V2.md`, the timing section: "`letitedit_timing(view='meaning')`: what happens in each motion event and
  shot (label, a few words, done or not, size, camera, subject) from the local vision model, every label with its
  measured accuracy; `~` marks types measured under 80% (check them on the frames)."
- `letitedit-fine` / `letitedit-review`: before cutting on an action, read `view='meaning'` for that range; a
  `done: no` or `done: unclear` near a cut is a prompt to look at the frames, never a verdict (the done answer is
  ~75% right, barely above always answering yes).
