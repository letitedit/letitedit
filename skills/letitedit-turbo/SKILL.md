---
name: letitedit-turbo
description: 'Turbo, New video''s speed-first first cut (the request has a `turbo: on` line) - read this and nothing else (a Look with no footage also reads its own recipe once). A cut from the words, simple captions, a song by rule, little simple graphics or a brief cutaway scene where the Look has one - never a cut-out, never anything layered behind the person - one export, one free measured check, a message that says what wasn''t checked. The person chose speed over quality.'
metadata:
  version: 0.3.0
---

# Turbo: the Look, made as fast as it can be made

The person ticked "Turbo: sacrifices quality for speed". It is the first run through only and never changes your model or effort. Their
choice is **speed**: a video that opens, has picture and sound and an end, with the Look's idea in it, as soon as possible.
Tool names below are `mcp__letitedit__<name>` (the same name with that prefix); one wrong name costs a request.

**Read this skill and nothing else** (a Look with no footage also reads its own recipe once, `letitedit_looks(action='get', id=<id>)`): no router, no stage skills, no
`letitedit_guide`, and for the talking-head Looks no recipe, because its behind-the-person parts do not apply in Turbo. Nobody answers questions: decide.
One pass; don't watch the result; don't redo anything.

## Explicit New video choices

Style is the kind of video; Look is the layout. `look: freestyle` (Freestyle) is no
set Look: cut it the way the footage suits, within Turbo's limits. Theme is an optional treatment
inside that layout, not permission to replace source speech or put anything
behind the person in Turbo. Captions & pace names the caption/pace preset.
Explicit `Music: none` means no bed; `own` means the Music file is included;
`trending` means a phone-app sound excluded from export. `library`, `backdrop`,
`ai` and `written` name the source or role rather than an automatic library pick.
AI music generation is outside Turbo's limited tools: when explicitly selected,
that conflict is stated rather than silently substituting a library song. Absent
Music or `auto` retains the existing fast song rule. A Theme recipe and its shared
notes describe the selected treatment, subject to Turbo's existing layer limits.
`Theme: Freestyle (freestyle)` is no set Theme: treat it your own way or not at all.
`Theme: pick` lists the Themes shown: choose one, read its recipe, and name it and why in
your first message.

## No cut-out, on any PC, for any Look
**Nothing is ever put behind the person in Turbo.** No `behind_person`, no `{vfx: cutout}`, no `letitedit_object`: a cut-out costs about 14 to 19 s of PC work per second of
video here and far more on a PC with no NVIDIA card, and Turbo is for speed. A Look that is about a world or big words behind the person gets, instead, little simple graphics, a
table or a card **beside or above the person, on a panel, or as a brief full-frame cutaway** that covers the picture while the voice carries on: your call, whichever the words suit.

## Very simple and brief, and every shape says something
Scenes, cards, effects and graphics all stay, and each is **very simple and brief**. A scene costs the PC time for every element it draws, every frame (8 s of the template below drew in
47 s, 8 s of a detailed city in 164 s). A detailed scene makes a Turbo video slower than a careful one: that is the one way to get Turbo wrong. So:
- **The model of "simple":** a plain white background, a plain black outline of a building with plain windows, and a few plain black stick birds flying across.
  Flat shapes, one or two colours, thick lines, no gradients, glow, grain, fog, shadows or particles, no photographs of anything drawn, a handful of
  elements, one movement or none, a few events at most, each on a spoken word. There is no number of seconds to aim for: a scene stays as brief as its one idea.
- **A viewer must be able to say what each shape is.** A building, a sun, a bird, a box, an arrow, a word. Beams, rays, lines, streaks, shimmer or any other decoration nobody could name
  is left out, however plain it looks (a past Turbo video had grey beams sticking up that nobody could explain).
- **Draw it once. Look at it once** (the picture in the tool's reply) and change only what is broken (nothing shows, it covers a face). No second round of polish.
- A starting scene, to be changed to fit the words (the canvas contract: `M.block('custom', (stage, p, c) => ...)` returns a function of `t`, seconds from the
  scene's start; `c.w` and `c.h` are the pixel size):
```
M.block('custom', (stage, p, c) => {
  const S = c.w / 1080, cv = document.createElement('canvas'); cv.width = c.w; cv.height = c.h;
  cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%'; stage.appendChild(cv);
  const g = cv.getContext('2d');
  return (t) => {
    g.setTransform(S, 0, 0, S, 0, 0); g.clearRect(0, 0, 1080, 1920);
    g.fillStyle = '#fff'; g.fillRect(0, 0, 1080, 1920);                     // a plain background
    g.strokeStyle = '#111'; g.lineWidth = 6; g.strokeRect(300, 700, 480, 900);  // a building outline
    for (let r = 0; r < 6; r++) for (let k = 0; k < 3; k++) g.strokeRect(350 + k * 150, 760 + r * 140, 80, 90);   // plain windows
    for (let b = 0; b < 4; b++) {                                              // stick birds crossing
      const x = ((t * 180 + b * 260) % 1400) - 150, y = 300 + b * 90 + Math.sin(t * 3 + b) * 20;
      g.beginPath(); g.moveTo(x - 24, y); g.lineTo(x, y + 12 * Math.sin(t * 9 + b)); g.lineTo(x + 24, y); g.stroke();
    }
  };
});
```

## Dropped for every Look
The review, the critic and the quality gate; `check_frames`, `check_range`, `check_audio`, `timing`; `caption_fit`; voice clean-up; `soundtrack`, `music_make`,
`music_write`; `letitedit_hooks`; `brief.json`, journal notes, story plan, "why" markers; a second round of anything; a second export. The one check kept is
free: the export's own `quick_check` (below).

## The steps (every Look with footage)
1. **One message, parallel calls:** `letitedit_footage(path=<the folder or files>, transcribe=True)` (the sheet shows where the face sits) and
   `letitedit_words(clip=<each video file, up to three of the longest>)`.
2. **Choose the cut from the words, in one go.** The best complete thought, in order, from the one clip with the most speech (more clips only if the length asked
   for needs them). Drop every phrase said before a restart (a line said twice: keep the second), pauses, "um", "so yeah", "I forgot to mention". In at a phrase's
   start minus 0.10 s, out at its end plus 0.15 s. "Let the AI choose": the complete thought, usually 20 to 45 s. A length given: within a few seconds.
   No measuring of cut edges, no listening: this is where Turbo costs quality (a word can lose its last sound).
3. **Save location:** if the request includes `Save video in: <folder>`, keep the project, export and AI working files
   inside that exact folder; reference footage where it is, never move or copy it. Without that line the unchanged default
   is `<the folder's parent>\<folder name> - first cut.mlt`.
   **One message, parallel calls:** `letitedit_project_new(path=<the save path above>, like=<the clip>)` and
   `letitedit_library(kind='music', query='calm', limit=5)` (`upbeat` for an energetic subject). Take the first song.
4. **ONE `letitedit_timeline_apply(project, label='Turbo: first cut', changes=[...])`:** each kept range `{op: insert, track: V1, item: {clip, in, out}, edge_mode: exact}`
   in the order they play; captions `{op: captions, track: Captions, from_speech: true, chunk: short, animate: false, burn_in: true, max_chars: 22,
   style: {size: 70, fill: '#FFFFFF', outline: {color: '#000000', width: 5}, position: bottom, margin: 0.29, max_lines: 2}, fix: {<a misheard name>: <right spelling>}}`
   (the words on the chest, below the chin, clear of the phone apps' buttons: on five phone clips of one person the chin sat at 53 to 60% of the height and the
   captions' top at about 64%; **if the sheet shows the chin lower than 58%, use `margin: 0.22`**; one setting, no fitting); the song `{op: add_track, name: Music,
   kind: audio}`, `{op: insert, track: Music, at: 0, item: {clip: <song>, in: 0, out: <the video's length, the sum of the kept ranges>}}`,
   `{op: score, fade_in: 0.9, fade_out: 0.8, levels: {talk: -12}}`.
5. **The Look's part (below), once.**
6. **Export once:** `letitedit_export(project=<the .mlt>, preset='turbo_h264')`, then `letitedit_export_job(job_id, wait_s=240)` again until it is done.
   Read `result.quick_check` in the last reply: `problems` lists anything truly broken (a black picture, a silent video, a video cut short or ending black); `notes` says how many
   sampled frames have a face. **Only if `problems` is not empty** and one change fixes it: make that change and export once more. Otherwise no second export, whatever else you notice.
7. **`letitedit_show(project=<the .mlt>)`**, then the message.

## What each Look becomes (no cut-out in any of them)
- **Clean, and no Look or "the AI decides":** exactly the steps above; nothing is added.
- **You + Visuals On Top:** after step 4, put the person lower and smaller and a paper panel above: in step 4 give each V1 clip
  `effects: [{size_position: '151 538 778 1382'}]` and use `margin: 0.19` for the captions; then `letitedit_code_scene(action='create', project, script, at=0, duration=<the video's length>,
  title='Panel')`: a scene that fills only y 0 to 520 with a plain paper colour (everything under 520 stays transparent so the person shows) and draws, one at a time, two or three
  very simple pictures of what is said (a box and an arrow for a process, two stacked blocks for an order, a plain wall for a problem), each landing on the word that names it.
  Draw concepts, never a number, chart or result.
- **Scenes Behind You:** one brief **cutaway** on the strong word where the video turns, after a few seconds of the real room: `letitedit_code_scene(action='create', project, script,
  at=<s>, duration=<s>, title='Cutaway')`, an opaque full-frame scene in the very simple style above (the template is the model: change the building, windows and birds to what the words say),
  `behind_person` left out. The voice and captions carry on over it. Or, if the words suit it better, the panel layout of You + Visuals above.
- **Big Letters Behind You:** the one to three words that carry the video, each as a plain full-frame cutaway card for about a second (a plain colour, the word in thick letters across the middle,
  nothing else), one `letitedit_code_scene(create, ...)` for each, dropped on the word as it is said.
- **Looks with no footage** (Filmed scrapbook, and Flat Explainer, Drawn Story and Made with code when they are offered): there is no folder to cut. Read the Look's recipe
  once and `letitedit_looks(action='inputs', project=project, inputs='read')`; look at every picture the person gave once (`letitedit_look(items=[...])`); write the script from **only** what the person wrote
  and the pictures show, **no fact, number, name or date of your own** (this is the one thing Turbo does not loosen: a false claim about a real thing breaks the video); read it with
  `letitedit_voice` once (never the microphone; no voice clean-up on a voice this PC made; ask for the file in the project's own side folder and check it is there before using it);
  then **one very simple scene** in the Look's medium (its hand or kit) for the whole length, at most four or five very simple beats, with each picture as one plain print, **always at least one
  print in view: the camera moves only between prints that sit close together, never across empty page** (an empty page for a second or more reads as a mistake), no story plan, no frame check of every
  beat. Captions only where the recipe has them, a song by rule and the export as above; the project goes where the Look's recipe says. No cut, no word-by-word captions where the recipe forbids them.
- **Orbit Stack and anything else:** the plain cut, and say which Look was left out.

## The message (eight lines at most)
The video's path and length (or that it is still exporting: the file isn't there yet, where it will appear, the job id; do not wait beyond the one `export_job` call asked for);
two lines on what it says; then **"Turbo was on"** and plainly what was **not** checked: nobody listened or looked at cut edges, captions against the face, the mix, or what the
review would have said; no voice clean-up; simple captions at one fixed place; the music set by rule; one export; and what the Look became (a brief cutaway scene, a panel, word cards, or the
Look left out) and that Turbo puts nothing behind the person. Then what `quick_check` found, in its own words. No claim about quality, no verdict, no "ready".
Notes the person sends afterwards are handled the normal way.
