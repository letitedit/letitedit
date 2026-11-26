# letitedit

A project is a letitedit timeline file (`.mlt`) that the person can open and edit in letitedit on this PC.

A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`).
Your own edit (an ffmpeg command or script, a Python or JSON edit list, an EDL or OTIO file) becomes a project with
`letitedit_import`; `letitedit_export_edit` writes a project back out in those forms, the person's hand edits included.
Projects can also be changed by edit ops or Python with `letitedit_timeline_apply`. Every tool is also a function of the
Python module `C:\LetItEdit\bridge\letitedit_ai.py` (`letitedit_ai.tool(name, **params)` reaches any of them), and
every picture a tool returns is also saved as a file whose path is in the result.
Know-how on stacking layers and aiming an effect is in the `letitedit-layers` skill.
Know-how on how things move (timing, easing, springs, camera, kinetic type, landing on the word) is in the `letitedit-motion` skill.

## Tools
- `letitedit_guide`: The reference. No topic: the index (every tool in one line, how projects work). topic = a tool name or a section ('edits', 'items', 'effects', 'code', 'python', 'import', 'engine'): that part in full; 'ops' (or an op name): every edit op and its fields.
- `letitedit_footage`: Source files (folder, list or one): length, size, recording time, camera, talking, sounds, picture problems, notes, what is seen in each shot (fact log: people, faces, shot, place, text, moments, each with its measured accuracy; and segments), and frames (frames / every_s / times / size, any number).
- `letitedit_segments`: A clip, folder or shoot as segments in recording order (split at recording gaps, GPS moves, changes in people/camera facts and in what is said): times, facts holding across each, moments, text seen, first words, a frame.
- `letitedit_ask_frames`: One question to the local vision model at several times of a clip or a photo (choices optional): its answer per time and a frame sheet, with its measured accuracy for that kind of question.
- `letitedit_words`: What is said, with times: a file, folder or list (source seconds) or a project (timeline seconds); lines grouped by pause / max_words, or per_word.
- `letitedit_transcript`: Give a source file your own transcript (words with times, or SRT/WebVTT); every tool that reads what is said uses it instead of the local one.
- `letitedit_search`: Moments in footage that look, sound or are said like a text query or an example moment (picture, speech, sound or any): times, scores, a frame sheet.
- `letitedit_find_ranges`: Exact ranges of what you describe in footage (picture first, so silent moments too): first and last frame, peak, a before/start/peak/end/after strip, an edit_item for letitedit_timeline_apply and an id that stays the same on every call; refines moments you give (around=) or returns stored ones (range_ids=). Camera moves are not cuts.
- `letitedit_find_takes`: Repeated takes of one passage (retakes, false starts, restarts inside a line, lines said again) from cached transcripts: groups, wording and claim differences (number, negation, name), separate measurements per take, comparison sheets and clips. Never picks or deletes.
- `letitedit_speakers`: Who talks when and whose faces are seen (voice and face clusters with spans, sample words and sample images); name them once and words carry the names.
- `letitedit_hear`: Sound described in words over time: windows of a file or a project's mix scored against labels (yours or a default list); a spectrogram on request.
- `letitedit_look`: A sheet of frames from any files and projects: times or ranges, crops, labels, layout and size; optional waveform, spectrogram, loudness, speech and word lanes. items: [{file | project, times | range (+ count | every_s) | nothing (the whole source), crop?, label?, lanes?, pad?, span?}].
- `letitedit_library`: Music or sound effects on this PC (kind, query, bpm and length ranges): path, length, tempo; music also genre, mood, artist, licence, and, with an active supporter key, on-demand songs marked as such (fetch= brings one down). Songs holding long pure howl- or whistle-like tones are left out (whistle_tones_hidden counts them; with_whistle_tones=True lists them).
- `letitedit_note`: Read or write notes on a source file.
- `letitedit_import`: Your own edit as an editable project: an ffmpeg command or script, a Python or JSON edit list, an EDL or OTIO file; what was kept as made clips, and with compare=True how its render differs from the source's.
- `letitedit_export_edit`: A project written back out as JSON, Python, an ffmpeg script, an EDL or OTIO (the person's hand edits included).
- `letitedit_project_new`: A new empty project (size, fps, or like a clip), or a copy of one.
- `letitedit_timeline_read`: A project as an edit script (YAML): tracks, items with ids, in/out, effects, words said; a long one compact (keyframes and long texts folded), ids or a range for one part; stack_at: the layers at a moment, back to front, in plain text. A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`).
- `letitedit_timeline_apply`: Change a project: edit ops by id (`changes`), a whole script, or Python `code`; every change is checked first; dry_run says what would change without writing; returns what changed, and words on screen the edit added or changed that are held shorter than their reading time. Edit ops include split edits (J and L cuts). A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`). The changes run in order, each on the timeline the ones before it left (ids stay the same), and the whole list is one undo step. Every change is checked before anything is written: a refused apply names the op, the field and what it takes, and writes nothing. With check, the reply's `after` gives the script of the tracks the ops name that changed, names the other tracks that changed, and lists the words said around a change on the main picture track.
- `letitedit_timeline_undo`: Undo the last apply.
- `letitedit_try`: Versions of an edit on scratch copies (changes or code each), lined up by time, words or clip: frames side by side, words, loudness, one MP4 of them back to back; joins=True: the words and problems at every join of each. The project stays as it is. A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`). versions: [{label (or name), changes | code}]; start_s and end_s (timeline seconds, together) line the versions up on that span (align: {range: [start_s, end_s]}). With joins, each version's joins carry `heard`: the words heard on its own render (transcribed), each join marked |t| where it falls, and heard_before / heard_after / heard_inside per join.
- `letitedit_bin`: Markers and picked subclips stored in the project, read or written; the person sees and adds to them in letitedit. A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`). add: subclips [{file, in, out, name, note, color, folder}]; markers: [{at | start, end?, text, color?}]; remove: marker ids or names. An add entry with a text and a time but no file is a marker. Without arguments: everything there now.
- `letitedit_hooks`: Opening candidates for a project in about a second (a moment with in/out, 2-3 text options, approach, why), distinct and not shown before; more, previews; kept in hooks.json for the app's Regenerate button; mark and add (your own candidates) in the same call. Swap with {op: hook}. add: [{from: <id> | id: <id> | source: {clip, in, out}, text: [1-3 options], label?, approach?, why?}]; an approach outside the list is kept as the label (the approach is then quote).
- `letitedit_import_srt`: Captions from SRT text (or an .srt file) into a caption track of the project open in letitedit: a new track named track_name, or overwrite its items; lang is a 3-letter code; drawn on the video once the track has a caption look ({op: captions, track, burn_in: true}).
- `letitedit_check_frames`: Frames of a project as the export renders them (times_s / every_s / count, any number, width), or shots=True: frames per shot; platform: that app's covered areas drawn on each frame. A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`).
- `letitedit_check_range`: Render a range of a project with its sound (start_s, duration_s, width): MP4 path and a filmstrip (frames); joins=True: the words and problems at every join in the range, and the sound at every clip start and end in it (edges), as the review bundle's edge check measures it. A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`). With joins, `heard`: the words heard on the render itself (transcribed, timeline seconds), every listed join and clip edge marked |t| where it falls, and heard_before / heard_after / heard_inside on each listed join and edge.
- `letitedit_check_audio`: Loudness of a project's mix or a range of it: integrated, range, peaks, readings every_s, music vs voice (stems; on by default with a Music track), quiet stretches (quiet_lu), and tones: sustained narrow whistle-, whine- or howl-like tones in the mix and the music (seconds, pitch, how far they stand above their surroundings). A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`).
- `letitedit_overview`: One picture (or pages) of a whole edit or a range: lanes of thumbnails, clips, tracks, speech, words, loudness, beats, graphics, captions, gaps, recording-time jumps. A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`).
- `letitedit_stills`: Frames of a file or project as image files: any times, region and size. A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`).
- `letitedit_timing`: Timing, motion and rhythm as pictures and numbers, frame-accurate: view='map' (the rhythm map: shots and sizes, motion with the camera's own move removed, camera labels, speech, music beats, captions, loudness; every cut flagged by its offset from the beat and whether it lands on action; numbers per section), 'slow' (1-3 s frame by frame with motion arrows and the likely eye position), 'cuts', 'speech', 'joins', 'sync', 'trajectory', 'meaning', 'emotion' (raw footage: mood and energy per sentence with turning points; an AI's judgement, so hone in on each with 'slow'; options.moods = {name: meaning} scores your own moods too). Works on a project (a cached small render of it) or a video file; nothing is edited. A compact reply keeps the per-cut summary (`text`, one line per cut) whole.
- `letitedit_quality_gate`: Measure a rendered video against the letitedit quality gate (length, loudness, pace, first 3 s, silences, speech start, audible words): verdict and every check.
- `letitedit_review_bundle`: One export reviewed end to end: pages of the whole video, larger frames at key and flagged moments, the full transcript, the gate's measurements, the project's checks, the brief's must-keep/must-avoid/claims/ending, an optional critic, and one verdict (blocked / revise / incomplete / ready) with what was not checked, what only the person can act on (for_you) and how many review rounds there have been (rounds). On a preview the size checks judge the project's size; final_of=<reviewed preview> checks a final export against it; render='preview' | 'final' (with project=) exports the timeline first and reviews that file. With review_code_first on: measured checks before any critic, and review_order says whether the critic ran (held, reuse, look, run).
- `letitedit_critic`: A blind second opinion on a render from a separate run of an AI on this PC: verdict, retell, ranked problems with timecodes.
- `letitedit_fit_music`: A song cut and joined on its own beats and bars to a length or to hit cut points: the new file, every joint and where each hit landed.
- `letitedit_soundtrack`: A deliberate score from one song: sections by energy, hits landed on downbeats, phrases or drops, natural sound protected (deep duck or drop-out), no back-to-back loops; returns the plan (edit ops, where each hit lands, joins) or applies it and measures the rendered mix.
- `letitedit_song`: A song the video is cut to but that stays out of every export, for adding in the phone app when posting: its usable parts, its place on a named muted track, cuts against its beats, the upload measured against it, a preview with it and the facts for posting.
- `letitedit_music_make`: Instrumental music written on this PC (ACE-Step 1.5) to a description and length, then cut on its beats to a length, hit times or a project's cuts: the file, tempo, beats and how it lines up.
- `letitedit_music_write`: Music written note by note as a score (JSON) and performed in code on this PC, on any PC: no GPU, download or network; the style vocabularies, a bar grid over the cut's words and cuts, every check, the file at the film's exact length, and revisions by changing single lines.
- `letitedit_sync`: Line up a whole shoot by its sound (cameras, phones, separate recorders, many takes, claps): one timeline with how sure each placement is and drift; optionally a synced project and copies of the camera clips with the recorder's sound.
- `letitedit_track`: Follow a box, point or face through a span of a video: its position and size over time as numbers, and a check sheet.
- `letitedit_separate`: Split a file's sound (or a range) into voice, drums, bass, other, music and rest: one file each, with loudness.
- `letitedit_voice`: Speech of a text in someone's voice cloned from a few seconds of a clip (or a default voice), made on this PC (engine: dots-tts by default with a clip, chatterbox without one): the audio file with word timings.
- `letitedit_dub_lines`: Dubbing, step 1: what is said on a project's timeline as lines with times ([{i, start, end, text}], um and uh left out) for you to translate.
- `letitedit_dub`: Dubbing, step 2: the translated lines spoken on this PC (Kokoro voices: es, fr, it, pt, hi, ja, zh, en, en-gb), each fitted into its slot, on a 'Dub (<language>)' audio track; the original voice lowered (-20 dB), muted or kept; one undo step. Returns the file and how each line fit.
- `letitedit_dub_voices`: The dubbing voices (all, or one language's) and each language's default male and female voice.
- `letitedit_graphic`: Python-drawn graphics: without template, what can be drawn (word captions, a progress bar, the Look's own templates, or your own code); with template/code, frames of it at times.
- `letitedit_motion`: Motion clips rendered by HyperFrames on this PC: animated titles, lower thirds, kinetic quotes, word captions, count-ups, bar charts, steps, location tags, callouts, chapter and end cards, stingers, or your own HTML/CSS/JS; preview stills, render a ProRes 4444 .mov with alpha (a {motion: ...} timeline item in the project's Look), marked generated. Draws with the PC's Edge or Chrome; where it can't run, timeline items are drawn as the nearest graphic. action='shaders' lists optional M.shader canvas helpers, their settings, sources and licences; saved scenes carry the named helpers. No WebGL: plain 2D stand-ins keep the scene visible.
- `letitedit_code_scene`: A custom code scene saved beside a project: create puts a selectable scene on a Code scene track and requires script to register M.block('custom', ...) with a frame function driven by t; browser-only animation does not follow the playhead or export reliably. revise keeps immutable source revisions and changes the open player's picture as one Undo; it takes a whole script, html or css, or edits: [{old, new, in?}] exact text replacements in the pinned revision's script (in: html or css for those), applied in order, each old found exactly once, and nothing changed when one isn't. source returns the pinned revision's script, html, css, params and duration (revision: another one). scene_id is the scene's id, or the id of its timeline item. status lists scene items; versions lists their revision hashes; restore pins one revision as one Undo; save copies the pinned revision and a moving thumbnail to the person's My scenes folder; favorites lists those saves. render draws the pinned revision at full quality. Both app Export and letitedit_export prepare full scene renders before encoding. A revision's page holds its own copy of the runtime and any drawing kit it names, and draws from that copy, whatever this PC has later, a kit's absence included. revise keeps that copy; kept_from_this_scene and kept_note in its reply say what this PC has different or lacks. create uses what is on this PC; a kit that isn't here comes from this project's scenes or My scenes when one of them has it. The live player is on by default. create and revise return a look at the scene in place (times and count choose its frames); look draws the scene now (a browser kept open, closed after 5 idle minutes), with the person, captions and every other layer as the export layers them, as a contact sheet (times: seconds from the scene's start, else count frames, 8 by default; revision: a version other than the pinned one), and reports page errors, a blank scene and a scene that does not move. letitedit_check_frames and letitedit_check_range show scenes the same way: the finished render when one exists for that revision, else frames drawn now; a scene that could not be drawn is named in the result and on its frame labels. create with behind_person=true also places the cut-out of the footage under the scene on a track named Person above the scene's, one {vfx: cutout} piece per clip under it over exactly the scene's time, in the same Undo step; revise with behind_person=true does the same for a scene already there; pieces where a cut-out already sits above the scene are skipped; the call returns when the mattes are made: about 10 s per second of 60 fps footage the first time, however many pieces, as one job; mattes are kept per frame, so a trim or a re-cut piece only writes the piece, about 3-5 s per second. behind_person in the reply lists what was placed or skipped, the seconds, or why none was made. A cut-out that can't be placed fails the call with the reason and adds no scene. The cut-out is its own item: revise leaves it alone, and moving, trimming or deleting the scene does not move, trim or delete it. The page runtime is the motion tool's: letitedit_guide('letitedit_motion') lists its helpers (curves, springs, M.camera, M.stagger, canvas parts under M.draw) and how a param named font loads a bundled font.
- `letitedit_image`: Pictures for a video, drawn by whichever AI or key on this PC can draw (Antigravity first when installed, signed in and allowed by the other-AI switch; then the AI's own image tool; the person's own image API key; another AI on this PC, if the person turned that on), or a plain message when nothing can: prompt, references, characters, edit, count, shape, transparent. Returns each file, its size, the scale-up on this video and the picture itself; everything is kept in the video's side folder with its words. status says who draws; history lists what was made.
- `letitedit_stock`: Stock video and photos, with a personal Pixabay key on this PC or an active supporter key (search, preview, fetch): ref, length, size, credit, licence; a chosen file comes down once. Personal Pixabay API results are cached for 24 hours.
- `letitedit_real_picture`: Real pictures of named things (logo or app, person, place, book, product, animal, food) from open sources with no key (Wikipedia, Wikimedia Commons, Openverse, Open Library, or an address you found): search gives numbered candidates with licence and restrictions; fetch saves one beside the project with its record (source page, licence, author, when fetched), which exports and reviews list, with a line for what is made from it (cut-outs, pictures drawn from it, motion clips, graphics, code scenes); made_from records the real pictures behind a file you made yourself.
- `letitedit_object`: One object out of a shot as a layer (a tool, a part, a product): points on a frame, a mask to check, one clean outline the track carries, or a plain reason when it bends, turns or leaves. {op: lift} brings it out over a new backdrop; {vfx: {effect: object}} outlines, recolours or keeps it in front of what's behind it.
- `letitedit_annotate`: Point at something in a clip (ring, arrow, box, label, magnifier; freeze or tracking optional) from a box in the clip's own source picture, mapped by the software through rotation, crop, zoom, trims and position: edit ops, a rendered preview with measured checks; refresh after the clip changes.
- `letitedit_caption_fit`: Lay out a project's captions so every word reads: line breaks, grouping, size and a place clear of faces, other text, platform buttons and protected regions ('phone' uses Shorts, TikTok and Reels zones; faces are hard constraints by default). Finds words that run together (outline, shadow, pop peak). Returns editable changes, violations with times, before|after crops from the export engine and what it could not solve; apply=True writes.
- `letitedit_fonts`: Fonts on this PC (query, category): a sheet of each and its weights.
- `letitedit_effects`: Engine effects (~760): search, read one's settings, preview on a clip.
- `letitedit_vfx_effects`: Shot effects and narration that can be placed as clips, with their settings.
- `letitedit_match_shots`: Match clips to a reference clip's exposure, white balance and gentle tone (ids, its scene or track): an editable Color Grading effect per clip, before/after frames and measured differences; proposes first (apply=True or plan_id writes); leaves HDR/log, other scenes, sunset/night looks and changing light alone, with the reason. A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`).
- `letitedit_reframe`: Reframe clips to another shape (9:16, 4:5, 1:1, 16:9) keeping several things in frame at once - faces, hands, the part being shown, boxes you name - on a smooth, mostly still crop path (keyframed Size/Position); per subject how much of the time it is fully in the crop; where the required ones can't share one crop it says when and which, and offers a split or an inset as ready edits. apply=True writes (one undo step).
- `letitedit_looks`: Looks: list or read recipes and their own settings; copy one into My Looks, update a personal revision, or read settings. Also keeps a project's Look inputs and pop-ups. One store with Learn; no uploads or automatic migrations. Select defaults with {op: look, id}; generic effects, pop-ups and hooks remain.
- `letitedit_assets`: Search the asset library, licences included: emoji (Fluent still, Noto animated), icons (Tabler), animated stickers, graphics and transitions (Elements), CC0 sound effects (pops, whooshes, risers, glitches, booms, dings, cash, crowd, comedy...) and CC0 music; a sheet of the results. id/ref (emoji:fire, sfx:whoosh, anim:party): one asset ready to place - a PNG, the sound file with where it peaks, or an asset_sticker recipe - with its credit line if it owes one and the edits that place it.
- `letitedit_my_assets`: My assets: a folder where the person keeps their own logo, intro, outro, colours, clips, sounds, pictures and fonts, the same folder whichever video is open (kind, length, size, transparency, measured colours, their note; ref mine:<id> for assets, styles, pop-ups and graphics; an edit's clip takes the item's path); nothing = what is there and a sheet, id = one item with a picture and the edits that place it, description/kind/note save what you saw or they said, add/remove. Empty is normal.
- `letitedit_review_note`: Say what became of a Live Review note: done (what changed), could_not (why) or not_an_edit; the person's list shows it.
- `letitedit_learn`: Personal Looks and Themes outside the installation: prepare reference measurements, build portable graphic kits measured against their reference crops, return frozen placement edits, check rendered families and every-frame face overlap, save immutable revisions with where each Look fits (its kinds of video, format and needs), check whether clips fit a Look, or compare reference/result measurements.
- `letitedit_export`: Render a project to MP4 in the background (preset, loudness, true_peak, start_s/end_s, platform, bitrates, sample rate): a job id, and the credit lines the video owes for library assets it uses (the animated emoji are CC BY 4.0) to put in its description. preview=True: drawn smaller by the export engine with the final's sound, cached apart from the final. wait_s: waits for the render and answers with letitedit_export_job's status of it.
- `letitedit_export_job`: An export job's status; wait_s waits; a finished one comes with a sheet (sheet_every_s), picture_change (shot lengths, where the picture stays nearly still) and sound_change (loudness over time, louder/quieter stretches) and tones (sustained narrow howl- or whistle-like tones in the finished sound); credits: the lines the video owes. Any other render can take the PC render lock through render_lock.py beside the installed tool server.
- `letitedit_show`: Open a project in the letitedit editor so the person sees it (the window that has it, else this session's own window if nothing is open in it, else a new one). The editor program started any other way has no link to this session.
- `letitedit_instances`: Running editor windows, open projects, unsaved work.
- `letitedit_editor`: What the person's editor window shows now: project and unsaved changes, playhead time, selected items (timeline ids), in/out marks, the item under the playhead per track, markers, the words said there, and optionally the frame.
- `letitedit_command_help`: The app's How to reference (AI > How to / Command Finder), searched: for a feature (New video, New hook, Review, My Looks, captions, Remove pauses, Add music, Other sizes, styles, the Elements panel...) where its button is, what to open first, what it does, how to undo it and its limits; an empty query lists every entry.
- `letitedit_status`: What the PC is doing for letitedit: tool calls still running in this server, background jobs (running, queued, recent), export jobs, who holds the PC render lock, GPU memory, free disk space, local models present.
- `letitedit_wait`: The result of a call that answered "still working" (call_id), pictures included, or "still working" again. A call answers "still working" past the AI's own limit on a tool call, or past about 25 minutes.
- `letitedit_jobs`: Background jobs: list, status, submit an index job (footage scan, transcripts, footage log) for a folder or files, cancel, resume.
- `letitedit_journal`: A project's journal (every apply and undo, by whom, plus notes), add a note (or several in one call: entries), or release your edit lease; edits also take a lease and respect track owners.
- `letitedit_platforms`: Facts per platform (YouTube, Shorts, TikTok, Instagram, Facebook): sizes, frame rates, lengths, areas the app covers, limits, each with its source and how sure; frame: those areas drawn on a frame.
- `letitedit_hardware`: This PC's GPU, memory, CPU and disk, its tier, and which engine each local feature uses (settings in C:/LetItEdit/settings.json; emotion_graph true builds the emotion graph on first import).
- `letitedit_log_frames`: For writing the footage log yourself: a video's stretches in batches, each a sheet of three frames with the words said and an id.
- `letitedit_log_write`: Save your descriptions of a video's stretches as its footage log (the same fields as the local model's: action, things, place, framing, text, quality).
- `letitedit_measure`: Any video's measurable style: shots and cuts per minute, words per minute, speech/music/effects shares, loudness, brightness and colours, on-screen text, contact sheets.
- `letitedit_places`: Where footage was filmed, from its own GPS: each file's coordinates and nearest place (offline GeoNames), and files grouped by place.
- `letitedit_versions`: Linked versions of a project at other sizes or platforms (each its own project): make one from ranges of the main, every clip reframed on its subject with a visible effect; sync carries the main's later changes and keeps the version's own; list.
- `letitedit_archive`: Every already-indexed clip on this PC in one local database (transcripts, footage log, recording time, camera, place): search by meaning with filters and a frame sheet of the hits, status (what is in it, what is not indexed yet), update.
- `letitedit_fix`: Repaired copies of the part of a source a clip uses (night: denoise and brighten; shake: stabilise; punch: 2x punch-in that can follow the subject; voice: enhance, work sounds kept on their own stem), applied as a visible {fix: ...} effect on the clip; a list of clips or a whole track in one call and one undo step; revert, list; before/after measures and sheet. A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`).
- `letitedit_3d`: Generated 3D clips of a model (.blend, .glb, .obj, .fbx ...) or built-in extruded title/logo rendered by Blender: list model parts, preview, render camera moves with x-ray, highlights and callouts (MP4, alpha or frames; a timeline item), marked generated.
- `letitedit_map`: Maps drawn on this PC from clips' GPS or coordinates (offline Natural Earth and GeoNames): a still or animated route with labels and a moving marker, any size and style (a timeline item), marked generated.
- `letitedit_look_check`: Read Look sources and device decisions against the current timeline, including punchins, sound_accents and, with sources.json, shot_sources and stickers. Missing, stale or weak evidence is major. A Look with nothing measured beside its recipe (a library Look) returns measured false and needs no receipts; a placed device is still checked on the timeline. Optional decisions save a byte-bound receipt; video checks observations and measures the export against the reference of a measured Look: pace by stretch, grade_likeness (colour strength, lean, brightness, tonal range and the lean of the shadows and the highlights of the footage shots, how much each changes from shot to shot, outliers by clip id and time; footage_limits names, per shot and measure, a gap the grade fit of those clips could not close, apart from the problems; held_back names the clips whose picture grade the face checks took part of the way, and the gaps that explains) and sound_shape (opening, level through the body, ending, sharp hits a minute and what they land on). pace_targets (shot lengths and cuts a minute of the reference) come with or without video. Provenance and relevance remain declarations. Long Look files and the whole result are named by path in the reply (requirements_in_files, full_result).
- `letitedit_caption_readability`: 360px native-frame glyph contrast. inverted_then_white uses the selected Look colour policy, or 3:1 without one, excluding entrance/exit and exact two-frame negatives; apply saves one colour per caption and a picture-bound receipt without changing shape or motion. Legacy edge aids remain explicit options. Burned-in caption tracks get native: per cue, the contrast with the picture just outside its edge; with no kinetic tracks, the top level passed and reason are that measurement (measured: native). Kinetic items sharing a track with other items: unsupported: mixed tracks.
- `letitedit_fetch`: Fetch the video behind a link (one video, no sign-in; yt-dlp fetched on first use, pinned and checked) (or a part of a longer one, up to 30 minutes) as a reference video for Match a video I like and letitedit_learn: saved in the person's own working folders with its record (link, title, uploader, when fetched), never in the library.

Full description of any tool: `letitedit_guide('<tool>')`. Every edit op and its fields: `letitedit_guide('ops')`. Sections: `edits`, `items`, `effects`, `code`, `python`,
`import`, `engine`.

## edits: edit ops for letitedit_timeline_apply (`changes`)
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

## items: clips and other items on a track
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

## effects: effects, motion, keyframes, transitions
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

## code: Python `code` in letitedit_timeline_apply
Python run in its own process, with: `timeline` (the timeline as `letitedit_timeline_read` shows it, `said` included),
`changes` (a list; every op appended is applied like `changes`), `words(start_s, end_s)` (words said on the timeline:
`w`, `t0`, `t1`, `id`, `track`), `source_words(clip, start, end)` (`w`, `s`, `e` in source seconds),
`find(text, clip=None, near=None)` (a phrase: with `clip` its source `in`/`out` cut on the gaps around it, without
`clip` its timeline `start`/`end`/`id`), `layout(track)` (`[(item, start, end)]`), `clock()`, `seconds()`. `print()`
output is returned. Any Python library on this PC can be imported, `letitedit_ai` included.

## python: the letitedit_ai module
The same projects, edits and checks as functions, for your own scripts:
`import sys; sys.path.insert(0, r'C:\LetItEdit\bridge'); import letitedit_ai as sa`. `sa.new_project(path, width,
height, fps)`, `sa.read(project)`, `sa.apply(project, changes, label, code)`, `sa.set_track(project, track, items)`
(replaces everything on a track, gaps included, with `items`: clips, `{gap: s}` and items with `at`; unchanged items are reused), `sa.words(clip, start, end)` / `sa.words(project=...)`,
`sa.transcript(folder, pictures=True)` (every talking file's words in lines, one call, each file headed by when it was recorded and the path of its sheet: a frame at every line), `sa.find(text, clip, near)`,
`sa.footage(path, frames, every_s, times, size)`, `sa.storyboard(project, per_shot, start, end)`, `sa.frames(project, times)`, `sa.qc(project)`,
`sa.audio(project, stems, start, end, every_s, quiet_lu)`, `sa.check_range(project, start, duration, width, frames)`, `sa.export(project, output, wait, loudness)`, `sa.effects(query)`, `sa.fonts(query)`,
`sa.library(kind, query)`; `sa.tool(name, **params)` runs any tool by name (a result with one dict comes back as that dict, its pictures' paths under `images`). Images come back as file paths. A project open in letitedit gets each `apply` as one undo
step, as with the tool.

## import: what letitedit_import reads and how it maps it
`letitedit_import(source, project, form, width, height, fps, compare, compare_every_s, output, media_dir)` reads an edit
written in another form and writes the project. `source` is inline text, a file path, or a Python list/dict.

- **ffmpeg** (a command line, or a .bat/.cmd/.ps1/.sh/.py script, read without running it; `output` picks the call
  when there are several, earlier calls that write intermediate files are followed): `-ss`/`-t`/`-to` on inputs and
  outputs, trim/atrim, setpts/atempo (speed), concat (filter or demuxer list) -> clips with their source in/out on the
  main track; a clip's filter chain -> its `{ffmpeg: "..."}` effect; fades -> fades; overlays (position, size, enable
  windows, opacity) -> items on their own tracks; subtitles/ass and simple drawtext -> `{ass}` text items;
  amix/amerge/volume/adelay -> audio items with gain; xfade fade -> a dissolve; lavfi colour -> colour items. Filters
  that only fit a clip to the frame (scale, pad, fps, setsar) are dropped and noted. Filters that change over time,
  wipe xfades, multi-input filters, moving overlays and dynamic text -> made clips `{ffmpeg: {inputs, video, audio},
  len}` carrying that part of the graph (listed in `kept_as_made_clips` with track and time; they move and trim like
  clips).
- **list** (a JSON or Python literal list of segments, or a .py file that assigns one, read with literal_eval):
  dicts or tuples; keys clip/file/src/path/source/media, in/start/ss/from, out/end/to, dur/duration/len,
  track/layer, at/time/position, text/caption/title, gain/volume, speed, effects/filter/vf (the mapping used is in
  `notes`); a string that names a file is the clip (found next to the list or in `media_dir`), other strings are
  names.
- **edl** (CMX3600): events, gaps, D dissolves, M2 speed, picture and sound events, timecode offsets.
- **otio** (OpenTimelineIO JSON): clips, gaps, transitions, time warps, freeze frames, audio tracks.

`compare=True` renders the source edit and the project and lists the mean absolute frame difference (0-255) every
`compare_every_s` seconds, largest first.

`letitedit_export_edit(project, form, output, video_output)` writes the saved project (hand edits included) as 'json',
'python', 'ffmpeg' (a runnable script: main track trimmed and joined with each clip's ffmpeg effects, other video
tracks overlaid, made clips and graphics by their rendered files, audio mixed with gains), 'edl' (main picture track
and sound) or 'otio'; what a form can't carry is listed in `notes`.

## engine: how the engine behaves
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
