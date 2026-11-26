# letitedit reference

letitedit edits video projects for **letitedit**, the video editor on this PC. A project is a letitedit
timeline file (`.mlt`). `letitedit_timeline_read` shows it as YAML; `letitedit_timeline_apply` changes it with edits by clip
id. If the project is open in letitedit, each apply lands in that window as one undo step, and reads include the user's
unsaved edits. Anything you make yourself (a file from your own ffmpeg or Python, an image, a render) can be a clip.

## Tools

| Tool | What it does |
|---|---|
| `letitedit_footage(path, frames \| every_s \| times, size, sheet_frames, log)` | A folder, file list or file: per file its length, size, orientation, when it was recorded (start-end to the second, by the camera's clock; which clips were recorded at the same time; the camera), talking time, sounds that aren't speech, camera motion, notes, and, once the footage log is written (`log=True`; cached), what a local vision model saw in each shot (`seen:`: framing, what happens, text in the picture; in full for one file); for a folder or list, the path of an image of `sheet_frames` frames spread through each video (default one every ~6 s, 6-24, with times); text files inlined; photos and audio listed. Frames you choose: `frames` (how many per video, spread evenly), `every_s` or `times` (one file), `size` (frame height in px), any number, with their times; without them a folder gets three frames per video (start, middle, end) and one file 12. One file also gives its sound events and motion spans; a song, tempo, beats and sections. |
| `letitedit_words(clip \| project, start_s, end_s, pictures, pause, max_words, per_word)` | Word timings in lines (a new line after a `pause`-second gap or `max_words` words; `per_word=True`: each word with its start, end and how sure the transcriber was): source seconds for a clip, a folder or a list of files (each video's text names its sheet image: a frame of the footage at the start of every line, with its time and words; `pictures` also returns the sheets as images), timeline seconds (with clip ids) for a project. `(?)` after a word: the transcriber gave it under 45% probability. `[picture: dark]` after a line: what the footage analysis found in the picture over at least half of it (dark, blown out, blurry, whip). |
| `letitedit_note(file, at, text, tags)` | Save or read notes about a source file. |
| `letitedit_library(kind, query, beats)` | Music or sound effects on this PC, one line per file (its path inside `folder` and its length; music also its tempo). |
| `letitedit_project_new(path, like \| width, height, fps \| copy_of)` | A new empty project, or a copy of one. |
| `letitedit_timeline_read(project, start_s, end_s, tracks)` | The timeline as YAML; clips whose files are transcribed show the words heard in them (`said`), and video clips show when that shot was recorded (`recorded`). |
| `letitedit_timeline_apply(project, changes \| script_yaml \| code, label, check)` | Change the timeline; returns the change list (added or trimmed clips with the words heard in them, and what the source says next when the speaker is still talking where a clip ends) and frames of what changed. `code` is Python that computes changes (see below). |
| `letitedit_timeline_undo(project)` | Undo your last apply. |
| `letitedit_check_frames(project, times_s \| every_s \| count \| shots, width, per_row, per_page)` | Frames as the export renders them, any number, on sheets `width` px per frame; each also saved as a full-size PNG. `shots=True`: every main-track clip (or those in `start_s`-`end_s`) as `per_shot` frames (3: first, middle, last), `shot_height` px tall, `shots_per_page` to an image (footage fitted inside a bigger frame shown as its picture area, sides left out), with its id, time, when it was recorded and the words said in it. |
| `letitedit_check_range(project, start_s, duration_s, width, frames)` | A render of a range with its sound (MP4 path), `width` px wide, and a filmstrip of `frames` frames. |
| `letitedit_check_audio(project, stems, start_s, end_s, every_s, quiet_lu)` | The timeline's mix (or a range of it) before the export's loudness finishing: loudness, peaks, quiet stretches (`quiet_lu` under the typical level, default 15); music vs voice (`stems`, on by default when there is a Music track); `every_s`: the loudness readings at that interval. |
| `letitedit_qc(project, every_s, max_frames, no_talk_s)` | Automatic checks: missing media, black, blank, very dark, washed-out or blurry frames (every `every_s` s and every clip, at most `max_frames`), shaky camera, whip-pans and blur in each main-track clip's footage (from the footage analysis), graphics overlapping each other or captions or covering a face (found in the picture under the graphics), cut words (voiced on both sides of the cut), stretches of `no_talk_s` or more where no one talks, caption problems. |
| `letitedit_export(project, output, preset, loudness, overwrite)` / `letitedit_export_job(job_id, action, wait_s, sheet_every_s)` | Render to MP4 in the background (cached chunks, resumable; it takes the render lock itself). `wait_s` (up to 540) waits for the job to finish before answering. Final loudness -14 LUFS unless `loudness` says otherwise (`'off'` keeps the mix). A finished job's status comes with a contact sheet of the video, a frame every `sheet_every_s` s (default 5; 0: none). |
| `letitedit_show(project)` / `letitedit_instances()` | Open a project in letitedit for the user / list open editor windows. |
| `letitedit_effects(query \| name, preview_clip)` | Every engine effect (~760) with its settings, and a before/after preview. |
| `letitedit_vfx_effects()` | Shot effects and narration you can place as clips, with their settings. |
| `letitedit_graphic(template, params, times)` | Python graphics: your own drawing code (`custom`), the caption animator, a Look's saved templates; previews. |
| `letitedit_fonts(query)` | Installed fonts (~300 families plus Windows'). |
| `letitedit_looks(action, id)` | Offered Looks, full recipes, resolved settings, private copies and personal revisions; project inputs and pop-ups. |

## Edit commands (`changes`)

- `{op: insert, track, after | before | at_start | at, item}` (with none of them, at the end of the track, so inserts in
  a list land in that order); `{op: trim, id, in, out}` (or `words: "..."`; on a code scene, in and out count in the scene's own time and `timeline_read` shows a trimmed start as its `in`);
  `{op: delete, id, close_gap}` (closes the gap on the main picture track; on other tracks the rest keep their times;
  trimming or changing the length of an item on those tracks also leaves the items after it where they are);
  `{op: move, id, track, after | before | at_start | at}`; `{op: set, id, ...}` (`null` removes a field);
  `{op: effects, id, effects}`; one op for many items: `{op: effects, ids | track, effects | add}` (`ids` a list,
  `track` a name or names: every clip of a file on it; `effects` replaces each one's effects, `add` adds to each one's
  own, `{fix: ...}` entries after its other fixes, the rest at the end); `{op: gap, id, before | after}` (sets the empty space next to an item);
  `{op: add_track, name, kind, after}` (on top of the stack, or just above the track named by `after`).
- `at: seconds` puts the item at that time on the finished timeline, on any track but the main picture track; the empty
  space around it adjusts and the track's other items keep their times.
- `{op: adjust, effects, from, to | words, below | above, name}`: an adjustment layer, a block on a track whose picture effects change
  every track below it and none above it for as long as it lasts, one undo step, with before and after frames in the reply. It reads back
  as an item `{adjust: true, len, name, effects}`; it moves, trims and deletes as any item does. Every field: `letitedit_guide('adjust')`.
- `{op: aim, effect, on, id, track, from, to, region}`: one effect on a chosen part of the video (`on`: clip, all, below,
  person, not_person), one undo step, with before and after frames in the reply. Every field: `letitedit_guide('aim')`.
- `{op: track, name, gain, duck, effects}`: a whole track. `{op: master, effects}`: the whole video and final mix
  (`{gain: dB or {keys}}`, `{loudness: {target, window, max_gain, min_gain, max_rate}}`,
  `{limiter: {input_gain, limit_db, release_s}}`, or any engine effect `{filter, params}`).
- `{op: captions, track, cues | from_speech, chunk, style, animate, fix, fillers}`: caption tracks.
- `{op: split_edit, id, lead | lag, move, fade, track, drop_words}`: a J cut (`lead`: id's sound starts that many
  seconds before its picture) or an L cut (`lag`: the clip before id is heard that long under id's picture). The
  moved sound is the same file on a `J/L cuts` audio track, in sync with its picture; the covered sound is
  silenced (`split_mute`), the two cross over 0.1 s (`fade`). `move: picture` keeps the sound cut and moves the
  picture cut instead (the classic dialogue J cut: hold the listener while the next line starts). `lead: 0` removes
  it. Later edits rebuild it; refused past the source handles (the message gives the most possible) or over words.
- `{op: multicam, angles: [{file, at, speed, shows}], sound, source_from, source_to, from, to, speech, pins, ...}`:
  a camera-switched cut of synced angles of one talk (`at` and `speed` from `letitedit_sync`; `shows`: the speaker
  names or ids seen in the angle, two or more for a wide). The main track carries the sound, uncut (one angle); the
  other angles' pictures are muted clips on a track just above it (`Angles`), at the same moment of the talk. Shots
  follow who talks (`speech`, or `letitedit_speakers`' words): the speaker's single, the wide for back-and-forth,
  talking over each other, laughter and pauses, cutaways (a reaction or the wide) in shots over `max_shot_s`; an angle
  is used only inside the time it recorded. `pins` puts moments on an angle by hand. Later edits to the main track
  keep the angle clips on their moments. Every field: `letitedit_guide('multicam')`.
- `{op: tighten, id, max_pause}`: cut the pauses out of a clip (pauses from the word timings and voice detection). `{op: score, zones, end, level_voice}`: evens out
  the speech clip by clip (clip gains), then sets music levels under it (speech is where the words are: cached
  transcripts; the voice detector for files without one, with a warning) (fades a music clip already has are kept); `level_voice: false` leaves clip gains.
  Its other settings (defaults in brackets): `fade_in` [1.5 s] and `fade_out` [3 s] where a song starts or ends alone,
  `crossfade` [3 s] where songs meet, `attack` [0.3 s] and `release` [0.9 s] of the dips under speech, `merge_gap` [4 s]
  (speech gaps shorter than this stay dipped), `dialogue_lufs` [measured], `levels` [talk -18, montage -6, quiet -24,
  swell -3, end -4 dB, relative to the dialogue], `tracks` [tracks named Music...]. `answer` [none]: pauses the music comes up in
  (gap ids from the result's `gaps`, times, the phrase a pause follows, or 'auto'), with ramps scaled to the pause;
  zones may carry their own `attack`/`release`.
  `{op: level, target}`: only the speech levelling. `{op: look, id}`.
- `{op: fx, items}` or `{op: fx, auto: true}`: a batch of effects at moments as one change (pop-ups, text pops, zoom
  punches, slow pushes, modern transitions, 3D, shakes, flashes, glitches, whooshes, sounds, count-ups, place tags,
  b-roll cutaways, light leaks, graphics, motion), each
  a style preset or a kind at `at`, `words` or `id`; the style's when/where rules are measured on the result.
  `{op: popups, entries}`: pictures that pop up when words are said (the style's, the project's popups.json and
  `entries`). `{op: hook, candidate, text, mode}`: swap the opening for a `letitedit_hooks` candidate (`h0` puts the
  original back). Every field: `letitedit_guide('op fx')` and the like.
  `{op: fx, sync_sounds: true | {look, rules, voice_dbfs, transitions: cutaways | all_cuts, roles}}` adds sounds tied to
  the picture as one change: a click on each cutaway transition and a key tick on each caption word (captions must
  already be on the timeline), at the Look's `synced` offsets and levels (its `sound.json`), with no two closer than the
  sound itself; the reply counts each kind.
  `{op: fx, camera_moves: true | {look, follow_motion, drift_per_s, max_scale, push, moving_target}}` puts a move on
  each cutaway (`pan_left`, `pan_right`, `tilt_up`, `tilt_down`, `push_in`, `pull_out`; a camera pans right when the
  picture slides left) as keyed size and position over the cover fit. Each clip's own image motion is measured first:
  enough motion gets nothing, a little is topped up in its own direction, a static shot or a picture gets a chosen
  move that differs from the clip before; the Look's spread, drift speed and share of moving cutaways steer it. The
  reply lists each clip's own motion, its move and the reason. A single move: `{kind: camera_move, id, move}`.

## Code (`code` in letitedit_timeline_apply)

Python run in its own process, with: `timeline` (the timeline as `letitedit_timeline_read` shows it, `said` included),
`changes` (a list; every op appended is applied like `changes`), `words(start_s, end_s)` (words said on the timeline:
`w`, `t0`, `t1`, `id`, `track`), `source_words(clip, start, end)` (`w`, `s`, `e` in source seconds),
`find(text, clip=None, near=None)` (a phrase: with `clip` its source `in`/`out` cut on the gaps around it, without
`clip` its timeline `start`/`end`/`id`), `layout(track)` (`[(item, start, end)]`), `clock()`, `seconds()`. `print()`
output is returned. Any Python library on this PC can be imported, `letitedit_ai` included.

## Python (`letitedit_ai`)

The same projects, edits and checks as functions, for your own scripts:
`import sys; sys.path.insert(0, r'C:\LetItEdit\bridge'); import letitedit_ai as sa`. `sa.new_project(path, width,
height, fps)`, `sa.read(project)`, `sa.apply(project, changes, label, code)`, `sa.set_track(project, track, items)`
(replaces everything on a track, gaps included, with `items`: clips, `{gap: s}` and items with `at`; unchanged items are reused), `sa.words(clip, start, end)` / `sa.words(project=...)`,
`sa.transcript(folder, pictures=True)` (every talking file's words in lines, one call, each file headed by when it was recorded and the path of its sheet: a frame at every line), `sa.find(text, clip, near)`,
`sa.footage(path, frames, every_s, times, size)`, `sa.storyboard(project, per_shot, start, end)`, `sa.frames(project, times)`, `sa.qc(project)`,
`sa.audio(project, stems, start, end, every_s, quiet_lu)`, `sa.check_range(project, start, duration, width, frames)`, `sa.export(project, output, wait, loudness)`, `sa.effects(query)`, `sa.fonts(query)`,
`sa.library(kind, query)`; `sa.tool(name, **params)` runs any tool by name (a result with one dict comes back as that dict, its pictures' paths under `images`). Images come back as file paths. A project open in letitedit gets each `apply` as one undo
step, as with the tool.

## Clips (`item`)

- `{clip, in, out, speed, reverse}` (`speed` is one number per clip; the clip's sound changes pitch with it, uncompensated; frames below 1x repeat): any video, picture or sound file (without `out`, a video or sound plays to the file's end, a picture lasts `len`, 5 s; an `out` up to 0.15 s past a file's end plays to its last frame). `{clip, words: "they put these on tight"}`
  places exactly that phrase (cut points on the gaps around it).
- `{color, len}`.
- `{graphic: {template, params, code, source}, len}`: a Python graphic; `code: "def draw(ctx): ..."` for your own.
  With `source: {clip, in, out}`, `ctx.src` is that clip's frame each time (`ctx.still`, `ctx.matte`, `ctx.depth`).
- `{ffmpeg: {inputs: [{clip, in, out}], video, audio, alpha, fit}, len}`: a clip made by an ffmpeg filter chain or
  graph (`[0:v]`..., ending `[v]`/`[a]`); the full ffmpeg here has drawtext, ass/subtitles, xfade, zoompan, lut3d.
- `{ass: "<an .ass subtitle script>", len}`: a transparent text layer rendered with libass (styles, \pos, \move,
  \t, \fad, \k karaoke, drawing commands). Times are from the start of the clip; installed fonts are available.
- `{render3d: {model, move, ...}, len}`: a generated 3D clip of a model (`letitedit_3d` lists the settings);
  `{map: {clips | points, ...}, len}`: a generated map from clips' GPS or coordinates (`letitedit_map`);
  `{motion: {block, params, duration}, len}`: an animated title, lower third, kinetic quote, word captions, count-up,
  chart, steps, location tag, callout, chapter/end card or stinger rendered by HyperFrames with alpha, in the
  project's Look (`letitedit_motion` lists the blocks; `block: custom` with your own html/css/script).
- `{freeze: {clip, at}, len}` (it plays through its own and its track's ffmpeg effects like a clip), `{vfx: {effect, source, params}}`, `{voice: {text, voice}}`.
- Any clip may have `effects` and `transition`. `mute: true` on an item is the `mute` effect.

## Effects, motion, transitions

- `{ffmpeg: "<filter chain or graph>"}` or `{ffmpeg: {video, audio, inputs, fit}}`: the clip's picture and sound
  pass through ffmpeg. In a graph the clip is `[0:v]`/`[0:a]`, `inputs` (files) are `[1:v]`..., and it ends in
  `[v]`/`[a]`. The output keeps the graph's size (`fit: contain | cover` fills the frame); the engine then places it like
  any clip, and the clip's other effects apply after it. As a track effect it applies to every clip with a picture on
  that track, after each clip's own.
- `{filter: NAME, params: {...}}`: any engine effect (`letitedit_effects`). Shorthands: `mute`,
  `{gain: dB}`, `{fade_in: s}`, `{fade_out: s}`, `{fade_in_audio: s}`, `{fade_out_audio: s}`, `{zoom: z, focus: [x, y]}`,
  `{size_position: "x y w h"}`, `{opacity: 0-1}`, `{text: "...", style}`.
- `{fix: {kind: night | shake | punch | voice, ...settings}}`: the clip plays a repaired copy of the part of its source
  it uses (made and cached by `letitedit_fix`, which lists the settings); removing the effect plays the source again.
- Any number can change over time: `{keys: [[seconds, value], [seconds, value, ease], ...]}`; eases: linear, hold,
  smooth, ease_in, ease_out, ease_in_out, and sine/quad/cubic/expo/circ/back/elastic/bounce + `_in`/`_out`/`_in_out`.
- `transition: seconds` (dissolve) or `{type, len, softness, invert, audio}`; types: dissolve, cut, bar_horizontal,
  bar_vertical, barn_door_horizontal, barn_door_vertical, barn_door_diagonal_sw_ne, barn_door_diagonal_nw_se,
  diagonal_top_left, diagonal_top_right, matrix_waterfall_horizontal, matrix_waterfall_vertical,
  matrix_snake_horizontal, matrix_snake_parallel_horizontal, matrix_snake_vertical, matrix_snake_parallel_vertical,
  barn_v_up, iris_circle, double_iris, iris_box, box_bottom_right, box_bottom_left, box_right_center, clock_top, or the
  path of a greyscale image (dark parts change first). The clip overlaps the one before it.

## How the engine behaves

- Caption graphics (`word_captions`) and motion `kinetic_type` accept `blend: normal | difference | exclusion` and
  other named Cairo modes. The engine blends the transparent glyph layer, not the source picture. Nonnormal modes
  reject boxes, shadows and highlight backgrounds. `protected: [{box: [x0,y0,x1,y1], start, end}]` uses normalized
  frame coordinates and local seconds; an overlapping glyph envelope is refused. `normal` is solid type.
- `{op: fx, items: [{kind: transition, id: <b-roll clip>, transition: {type: cutaway_negative, edge: in | out,
  len: 0.03-0.2}, sfx: <sound>, sfx_offset_s: <seconds>}]}` adds a negative-colour pulse on that boundary's
  full-frame B-roll clip. Its filter reanchors after trims; the sound and clip follow main-track edits. It refuses
  a speaker-track target or a cropped, positioned or translucent B-roll item.

- Track order: later video tracks draw over earlier ones. Audio tracks mix. Burned-in captions draw over every track,
  and master effects don't change them. `letitedit_timeline_read(stack_at=...)` gives the layers at a moment. The first
  video track stays first: a script that puts another video track under it is refused.
- A clip's blend mode is an effect: `cairoblend_mode` (`mode`: a name such as multiply or screen) on a track that blends
  with cairoblend, which is what these tools write; `qtblend_mode` (`mode`: a number, 13 multiply, 14 screen) on one that
  blends with Qt, which a project started by hand in the app can have. On the other kind it has no effect, and the edit's
  reply says so. A blend mode set on a whole track in the app stays through edits; `stack_at` shows it, the YAML read doesn't.
- Vertical footage in a wide project is centred with empty sides unless something fills them.
- The bottom video track has nothing behind it, so its opacity has no visible effect.
- When the first video track's timing changes, clips on other tracks and captions move with their picture unless an op
  has `ripple: false`.
- Adding, removing or reordering tracks, master effects and track engine effects apply to the saved file; a project
  open in letitedit with unsaved changes must be saved first.
- A clip with ffmpeg effects plays a render of its source range made in the background (several at once); trims
  within 0.5 s of that range reuse it, longer ones render again. Reads show the source clip, its in/out and the graphs.
- Made clips and graphics are saved next to the project in `made\` and `graphics\` and re-render when their recipe
  changes.
