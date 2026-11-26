---
name: letitedit
description: Start here for any letitedit / letitedit video job (edit raw footage into a video of any kind - story or vlog, tutorial, interview or podcast excerpt, documentary, product, travel, montage, creative - as a Short, a long YouTube video or both; caption, finish, export; revise from plain feedback). Fixes the brief (mode, driver, feel, reference, deliverables, must-keep and must-avoid), picks the stage from the project files, and says which letitedit skills to load and which file comes next. Use before editing.
metadata:
  version: 0.5.0
---

# letitedit router

Tools: the `letitedit` MCP server (`letitedit_guide` lists them; `letitedit_guide('<tool>')` gives any tool in full).
If it is installed under another name, use that name with the same tool names. Never pass parameters from memory:
read the tool's description first.

## New video choice fields

When the person wants to learn a reusable Look from one to three supplied reference files,
read `letitedit-learn` first. A personal `mine-...` Look carries its own recipe path in the
New video request; read that revision, not a guessed shipped-catalog path. These fields can be recorded in
`brief.json` without changing their meaning.

- `Style:` names the kind of video, not a caption preset: what was filmed (the app works it out from the clips and
  the person can change it).
- `Look:` names its layout and recipe; old lowercase `look:` requests still mean the same Look. `Look: Freestyle
  (freestyle)`, with a `look: freestyle` line, means no set Look: work out the kind of video from the footage you log
  (`letitedit-modes`) and edit it the way that suits the clips. Leave `look` out of `brief.json`, and say in the story
  plan and your first progress message what kind of video you are making and why. A chosen Theme then applies to the
  whole video, as it would to a Look's surface.
- `Theme:` supplies an optional treatment recipe and shared notes. Theme changes the selected Look's surface,
  lighting, grade or rhythm, not its source footage, subject, narration or layer order. The recipe and shared notes
  are part of that choice. A kit Theme on a talking-head Look affects its illustrated elements only; the person's
  recorded voice and likeness remain the source. An absent Theme leaves the Look unchanged.
  - `Theme: Freestyle (freestyle)` means no set Theme: how the video is drawn or filmed is your call, and using no
    Theme is fine (on a learned Look, keep its own theme file unless another treatment clearly suits the video
    better).
  - `Theme: pick` lists the Themes the person was shown for this Look, each with its recipe: choose exactly one, read
    its recipe and shared notes, say which you chose and why in your first progress message and the story plan, then
    apply it as a chosen Theme.
  - A chosen Theme replaces the Look's own surface (grade, lighting mood, texture, palette and drawn elements); the
    Look keeps its structure and timing (cuts, pace, the amount and character of b-roll, caption behaviour, size and
    position, camera moves, flashes and sound effects). The request carries one Theme at most.
  - A learned Look has a theme file of its own: when the request says a Theme replaces the Look's own surface, don't
    read or apply that theme file; when it says no Theme was chosen, keep the Look as learned, theme file included.
- `Format:` is Short or YouTube video.
- `References I added` lists characters, a logo, photos or a script for a video with no footage: use them, and never
  change or move them.
- A recipe with an "Adjusted by the person" section lists settings the person chose for it; they come before the
  recipe's own choices where they differ.
- `Captions & pace:` names a Look settings preset (or saved custom settings), independently of the Look and Theme. An
  absent field or `auto` preserves the existing AI choice.
- `Music:` is one of:
  - `library` (the song library);
  - `own` (the supplied local song file, included in the export);
  - `made` (music made for this video: you choose the engine that suits it, such as a score written for the cut with
    `letitedit_music_write`, music made on this PC with `letitedit_music_make`, or a quiet bed; the person doesn't
    choose);
  - `trending` (no music in the export: the person adds a sound in the phone or video app when posting; with a `Music
    file:` song name or file, cut to it via `letitedit_song`, otherwise leave the cut ready for an added sound);
  - `none` (no music; original speech and natural sound remain).

  The older values `ai`, `written` and `backdrop` mean `made`. Absent Music or `auto` is today's automatic music
  choice. The older lowercase `song:` field still means a phone-app sound; an explicit Music choice takes precedence
  over it.
- `Music file:` is the file or sound name for that selection.

## 1. Fix the brief
Write `brief.json` in the project folder before anything else. Ask the person only what you can't infer from their
words and the footage; say in one line what you inferred.
- `goal`: one sentence in the person's words. `audience`. `footage`: folders or files, used in place (never copy).
- `mode`: the kind of video, one or several, the first leads: story (vlog, day, challenge, build, repair), tutorial
  (how-to, explainer, screen recording), interview (interview piece, podcast excerpt), documentary, product (ad,
  demo, brand film), travel (trip, place, event), montage (music-led, before/after), creative (stylised, music video,
  sketch). An old `genre` maps to a mode (letitedit-modes, section 1).
- `driver`: what leads the cut: dialogue | narration | music | visual | sound. Default: the mode's usual driver,
  checked against the footage (a wordless shoot is not dialogue-led).
- `reference` (optional): a video whose tempo and style to match; measure it with `letitedit_measure`.
- `look` (optional): the recipe and defaults the person chose. `none`, `neutral` or absent means neutral defaults
  and no chosen recipe: edit from the brief and these skills; leave `look` out of `brief.json`. `freestyle` means
  no set Look and none to pick: choose mode, driver and feel from the logged footage (letitedit-modes), and say
  what kind of video you are making and why. A Look id means that Look. `auto` ("Let the AI pick") chooses one
  offered Look with `letitedit_looks(action='list')`, by content-fit and each card's `needs` against the footage;
  say which and why, then treat it as chosen. Reading and following a chosen Look: section 1b.
- `turbo`: not a brief field. A request with a `turbo: on` line (New video's Turbo box, "sacrifices quality for speed") is answered by the `letitedit-turbo` skill alone, without this router, and nothing is written to `brief.json`. If you are reading this router for such a request, stop and read `letitedit-turbo`. Notes sent after a Turbo first cut come here as normal.
- `deliverables`: `[{"kind": "short", "platforms": ["tiktok", "youtube_shorts", "instagram_reels"], "target_s":
  45}, {"kind": "long", "target_s": 480, "deliverable": "web"}]`; `deliverable` web (-14 LUFS) | podcast (-16) |
  broadcast (-23). "Just make something good": one 45 s Short and one 6-10 min long video, mode inferred.
- Hard wishes become checked fields: section 1b.

## 1b. The brief at every stage
These fields and rules hold at every stage and in every revision.
- `feel`: a few words for the intended feeling ("calm, warm", "urgent, funny"); sections may differ. The feel and the
  reference set the tempo, not the format: a Short can be calm and a documentary urgent.
- `look`, once chosen: read a chosen Look in full with `letitedit_looks(action='get', id=<id>)` at the start of the
  story stage and again before the fine cut, finish and review. Select its defaults with `{op: look, id: <id>}` on
  the project.
  Its taste overrides generic pace, caption and effect defaults, never must-keep/must-avoid. A Look is a recipe,
  not a template: this video's words, moments and shots still come from its own footage. Keep its "Must not" list.
  The brief's `look` goes to the critic with the recipe. If the footage cannot carry its `needs`, say what you
  did instead rather than forcing it. `{op: fx}`, `{op: popups}` and `letitedit_hooks` retain their generic uses
  and take defaults from the Look; `letitedit_looks(action='settings', id=<id>)` reads those values.
- `inputs` (optional): what the person gave the chosen Look up front, in New video's one screen of boxes (the request
  lists them by role and says where the record is; it is kept beside the video as `<video>.letitedit/inputs.json`, which
  `letitedit_looks(action='inputs', project=project, inputs=<record path>)` writes and `letitedit_looks(action='inputs', project=project, inputs='read')` reads back, so
  every round of revision, a new chat and the review have the same ones). Roles: `about` is the brief's content; `show`
  files may appear on screen (use them, or record why not with `unused={path: reason}`); `style` files are pictures to
  look at for the feel the person wants and **never appear in the video**, not as a frame, a texture sample or a
  background; `voiceover` is the person's own voice and is the narration (empty: you write the script and a voice on this
  PC reads it); `product` and `person` are the subject. A box left empty means the person chose to leave it out: work
  without it, and do not ask. Nothing is asked of the person after Go: not about these, not for approval of a script,
  a beat table or an asset. Their files are only read, never changed or moved. A Look with no footage has no `footage`:
  everything on screen is drawn, written or taken from `show` files, there is no log stage, and `must_keep` holds only words the
  person quoted (a summary of your own goes in `purpose`: a render is checked for a must-keep word for word). The review lists any `show` file that is not in the
  video with your reason, and flags any `style` picture that is.
- **My assets** (`letitedit_my_assets`): a folder where the person keeps files they like: logo, intro, outro, colours, clips,
  sounds, pictures, fonts, each listed with its kind, length, size, measured colours and their own note if they wrote one. It is
  their organising space: no promise that a video will use these files and no requirement that it does, and this
  skill says nothing either way. For an item that does go in a video: refer to it by its ref (`mine:<id>`), which
  `letitedit_assets`, styles, pop-ups and graphics assets accept like any asset; a `clip` or `image` item in an edit takes the
  item's `path` (`clip: mine:...` is refused). `letitedit_my_assets(id=...)` returns a picture of an item in its
  reply (a still, or a strip of frames), and `description=` saves one sentence about it. Their files are their own: no credit line
  is owed for them (only library assets such as the Noto animated emoji owe one), and never change, move or re-export the
  original.
- `song` (optional): a song file the video is cut to and the person adds in the phone app when posting, so it is never in the upload
  (letitedit-sound section 13). A person who gives a song and nothing else gets this; nothing more is asked.
- Hard wishes become fields the gate checks on the render (`letitedit_review_bundle`), so they survive every revision:
  `must_keep` (lines, or moments `{"source": <file>, "from": s, "to": s}`), `must_avoid`, `claims` (exact names and
  numbers, spelled right in captions: `"$12"`, `"Acme"`), `ending` (the last line or shot), `narration`
  (`"none"` | `"own voice"` | `"ai voice ok"`), `protected` (source ranges that stay whole when used),
  `required_lines`, `pace` (optional: the person's own limits, `{"cuts_per_min": 20}`; they make that check
  blocking). `tone` and `desired_response` go to the critic.
  "Keep the joke, no voiceover, end on the sunset" is three checked fields, not a hope. Only the person's own wishes
  go in these fields. Your choices (a moment you plan to use, the channel name, a line you like) belong in the story
  plan: as brief fields they make the gate block your own edit when you change your mind [OURS].
- Soft wishes the person calls preferences go in `preferences` (a list of lines, in their order): each is followed
  unless it conflicts with a hard wish or an earlier preference. The gate never checks them and the critic never
  counts one as a problem.

## 2. Load every skill the work needs
**Never drop a quality rule to save tokens.** The person's AI subscription is not a reason to skip a skill or a
quality pass. There is no session skill limit.

- Before making an edit, read this router, **letitedit-craft** and **letitedit-modes**, including the lead mode's
  `references/<mode>.md`.
- Before starting each stage in section 3, read that stage's skill; a journal note is not a substitute. Read later
  stage skills when you reach those stages, so their guidance is complete and current in context.
- Then read, when the work has it:

| Read | When |
|---|---|
| **letitedit-shorts** | a Short |
| **letitedit-sound** | sound, during finishing (a bed written for the cut or real music, your own call: its section 2) |
| **letitedit-captions** | spoken captions, during finishing |
| **letitedit-graphics** | explanatory or decorative graphics, during finishing, when those tasks are present |
| **letitedit-layers** | at any stage, before stacking things (behind or over a person, picture-in-picture, a blend mode) or aiming an effect (one clip, a stretch, a region, a blur) |
| **letitedit-motion** | before writing any code scene, motion block or animated title, or when a moving thing looks stiff, cheap, busy or off the beat (how it moves, settles and lands on the word; letitedit-graphics still decides whether it earns its place) |
| **letitedit-broll** | whenever b-roll is planned, cut or revised: the rough and fine cuts of any edit with cutaways, a Look whose recipe sets a b-roll share, and footage with less b-roll than the Look needs (its section 6 says what to use, made b-roll included) |
| **letitedit-learned-look** | the chosen Look's card (`letitedit_looks(action='get', id=<id>)`) lists `measured` files |
| **letitedit-lighting** | importing reference lighting, or the chosen Look has a Measured lighting section |

- **A chosen style's recipe:** read it through `letitedit_looks(action='get', id=...)`; its settings guide the look
  while the craft skills still guide selection, timing, sound and clarity.
- **Lighting, when letitedit-lighting applies (the table above):** light the person on **every speaker clip** with
  `{op: fx, lighting: true}` once the picture is final, without a cut-out and without a model relighting the picture
  (live filters, tuned to the Look); one test clip is never the delivery. The live lighting only lifts the face and
  keeps skin natural (its every-frame limits cut the light back, never the room); disclose any cut back. A Look's grade
  and lighting apply to faces too, aimed at the reference's own faces.
- **Faces.** Effects (stickers, pop-ups, text, graphics, kit pieces, b-roll cards, flashes) stay off the person's face
  where they can; where a Look, its reference or the moment calls for covering it, they may, and a Look or the person
  may call for an inset, picture-in-picture or split screen. What a person asks for their own face is done as they
  mean it in ordinary words, for that video, without their having to name a technical step: "unchanged",
  "untouched", "as recorded" or "don't change how I look" keeps the grade, the lighting and effects off their face.
  "Full size" or "uncovered" alone is about size and cover: it doesn't forbid a grade, lighting or a punch-in that
  keeps the face full size and uncovered.
- **How to read.** The stage starter attaches known skills in full: read each attached `SKILL.md`, including the lead
  mode reference when attached, and the Look recipe and inputs it attaches, in full, without fetching them again.
  Read the rest in one step with the Skill tool, in full, as soon as the mode or a fix calls for them. A `references/`
  file
  a skill names for your route (a switch the run uses, a measured Look, a music choice) is read in full when that
  route applies.
- **Check that every read returned the full file;** if the tool clips its output, continue from the missing lines
  before using that skill. A clipped response or batch does not count as loading those skills.

## 3. Pick the stage from the files that exist

| Missing in the project folder | Next skill | It writes |
|---|---|---|
| `log.json` | letitedit-log | `log.json`, `selects.json` (repeated takes via `letitedit_find_takes`) |
| `story_plan.json` | letitedit-story | `story_plan.json` (sections with mode, driver, feel, gear), `pickups.md` |
| a rendered rough cut in the journal | letitedit-rough | project `.mlt`, its render, story QA in the journal |
| fine-cut pass logged | letitedit-fine | updated project (joins, J/L cuts, b-roll timing, pace) |
| finishing pass logged | letitedit-finish (+ sound, captions, graphics in turn) | matched shots, mix, captions, SRT, exports |
| a gate verdict of `ready` | letitedit-gate (`letitedit_review_bundle` with the critic) | `review_bundle.json`, `review.md` |

- The app's **New video** button (was Make a first cut; or "make me a video from this folder"): letitedit-firstcut
  runs these stages in order, puts the strongest opening in and leaves others for the app's New hook button.
- A Short from existing long footage: log, then letitedit-shorts. A Short made alongside a long video is its own
  structure, not the long video cut down.
- **Revisions** ("less flashy", "the reveal needs room", "too slow at the start"): letitedit-craft's levers table
  turns the note into levers; change the levers, keep the structure, re-render the changed stretch, then the gate.

## 4. Rules that hold at every stage
- Render early: the first watchable render by about a third of the time budget, then watch it
  (`letitedit_check_range`, `letitedit_check_frames`). Agents that render last run out of time to fix the story.
- Never invent what the footage lacks (a setback, a reaction, a result). Say what's missing and offer a pickup or an
  honest bridge (`pickups.md`).
- Judgment here, maths in the tools: timing, coordinates, colour and layout come from tools (`letitedit_annotate`,
  `letitedit_caption_fit`, `letitedit_soundtrack`, `letitedit_match_shots`, `letitedit_find_takes`, `letitedit_search`, and
  `letitedit_find_ranges` for the exact first and last frame of a described moment, silent ones too). If
  `letitedit_guide` doesn't list one, use the fallback in letitedit-craft `references/checks.md`.
- Never claim success yourself. The final message gives the video path and quotes only `review.md`'s **For the
  person** section, with what remains and what was not checked. The technical section is for your own fixes.
- Defaults are defaults: break a craft default with a marker `waive:<check>:<one-line reason>` (`letitedit_bin`); a
  `hold:<reason>` marker over a deliberately long shot waives the longest-shot check there. Delivery limits
  (loudness, true peak, the 9:16 size) and story blockers need the person's OK instead.
- Markers (`letitedit_bin`): `why:`, `beat:<id>:<label>`, `loop:open:<id>`, `loop:close:<id>`, `hold:<reason>`,
  `chapter:<name>`, `hook:<A|B|C>`, `callback:`, `waive:<check>:<reason>`. Source facts: `letitedit_note`.
- Stage done: after its outputs exist, add a separate `letitedit_journal` note `stage:<name>:done`. The journal
  checks the required files and stage order; if it refuses, finish the missing work. Do not combine stage markers
  in one note. The mode choice is a `modes:` note (letitedit-modes).
- In the app's chat panel, store `brief:`, `log:`, `selects:` and `story_plan:` with valid JSON through
  `letitedit_journal(action='add', text=...)`; it writes the matching files in the project's `.letitedit` folder.
  `pickups:` writes `pickups.md`. For the rough stage, add `render:<path to the rough export>` after watching it.
  Outside the panel, normal project files work too. Read `letitedit_journal` before claiming progress.
- Every change is one undo step (`letitedit_timeline_apply`, also on an unsaved project open in the editor); the
  person can always undo you. Footage stays where it is.
- Wait with the tools, not a shell loop. Every check-in is a step that reads the whole conversation again, so wait
  long per step: call a long tool directly (one that runs past about 25 minutes answers "still working";
  `letitedit_wait(call_id)` collects it), and wait for an export with `letitedit_export_job(wait_s=1440)` (less for an
  AI with a shorter limit on a tool call). Do repeated work in one call (a list of clip ids, a track) instead of one
  call per clip.
