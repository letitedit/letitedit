"""Short tool descriptions for the v2 tool set (toolset.txt 'v2'): what goes in and what comes out, in a line or two.
The full description of any tool, and the guide's sections, come from letitedit_guide(topic)."""

PROJECT_READ = (
    "A project that is open in a letitedit window is read as the window shows it now, unsaved changes included; "
    "with no window, the saved file. The reply's `read` says which (`live` with the window, or `saved`)."
)
PROJECT_READ_TOOLS = {
    'letitedit_timeline_read', 'letitedit_timeline_apply', 'letitedit_try', 'letitedit_bin', 'letitedit_fix',
    'letitedit_match_shots', 'letitedit_check_frames', 'letitedit_check_range', 'letitedit_check_audio',
    'letitedit_overview', 'letitedit_stills',
}



def with_project_read(name, description):
    if name in PROJECT_READ_TOOLS and PROJECT_READ not in (description or ''):
        return (description or '').rstrip() + '\n\n' + PROJECT_READ
    return description


SHORT = {
    'letitedit_look_check': 'Read Look sources and device decisions against the current timeline, including punchins, sound_accents and, with sources.json, shot_sources and stickers. Missing, stale or weak evidence is major. A Look with nothing measured beside its recipe (a library Look) returns measured false and needs no receipts; a placed device is still checked on the timeline. Optional decisions save a byte-bound receipt; video checks observations and measures the export against the reference of a measured Look: pace by stretch, grade_likeness (colour strength, lean, brightness, tonal range and the lean of the shadows and the highlights of the footage shots, how much each changes from shot to shot, outliers by clip id and time; footage_limits names, per shot and measure, a gap the grade fit of those clips could not close, apart from the problems; held_back names the clips whose picture grade the face checks took part of the way, and the gaps that explains) and sound_shape (opening, level through the body, ending, sharp hits a minute and what they land on). pace_targets (shot lengths and cuts a minute of the reference) come with or without video. Provenance and relevance remain declarations. Long Look files and the whole result are named by path in the reply (requirements_in_files, full_result).',
    'letitedit_caption_readability': '360px native-frame glyph contrast. inverted_then_white uses the selected Look colour policy, or 3:1 without one, excluding entrance/exit and exact two-frame negatives; apply saves one colour per caption and a picture-bound receipt without changing shape or motion. Legacy edge aids remain explicit options. Burned-in caption tracks get native: per cue, the contrast with the picture just outside its edge; with no kinetic tracks, the top level passed and reason are that measurement (measured: native). Kinetic items sharing a track with other items: unsupported: mixed tracks.',
    'letitedit_learn': 'Personal Looks and Themes outside the installation: prepare reference measurements, build portable graphic kits measured against their reference crops, return frozen placement edits, check rendered families and every-frame face overlap, save immutable revisions with where each Look fits (its kinds of video, format and needs), check whether clips fit a Look, or compare reference/result measurements.',
    'letitedit_guide': "The reference. No topic: the index (every tool in one line, how projects work). topic = a tool "
                     "name or a section ('edits', 'items', 'effects', 'code', 'python', 'import', 'engine'): that part in full; "
                     "'ops' (or an op name): every edit op and its fields.",
    'letitedit_instances': "Running editor windows, open projects, unsaved work.",
    'letitedit_show': "Open a project in the letitedit editor so the person sees it (the window that has it, else this session's own window if nothing is open in it, else a new one). The editor program started any other way has no link to this session.",
    'letitedit_editor': "What the person's editor window shows now: project and unsaved changes, playhead time, "
                      "selected items (timeline ids), in/out marks, the item under the playhead per track, markers, "
                      "the words said there, and optionally the frame.",
    'letitedit_footage': "Source files (folder, list or one): length, size, recording time, camera, talking, sounds, "
                       "picture problems, notes, what is seen in each shot (fact log: people, faces, shot, place, text, moments, each with its measured accuracy; and "
                       "segments), and frames (frames / "
                       "every_s / times / size, any number).",
    'letitedit_find_takes': 'Repeated takes of one passage (retakes, false starts, restarts inside a line, lines said again) from cached transcripts: groups, wording and claim differences (number, negation, name), separate measurements per take, comparison sheets and clips. Never picks or deletes.',
    'letitedit_match_shots': "Match clips to a reference clip's exposure, white balance and gentle tone (ids, its scene or track): an editable Color Grading effect per clip, before/after frames and measured differences; proposes first (apply=True or plan_id writes); leaves HDR/log, other scenes, sunset/night looks and changing light alone, with the reason.",
    'letitedit_annotate': "Point at something in a clip (ring, arrow, box, label, magnifier; freeze or tracking optional) from a box in the clip's own source picture, mapped by the software through rotation, crop, zoom, trims and position: edit ops, a rendered preview with measured checks; refresh after the clip changes.",
    'letitedit_soundtrack': 'A deliberate score from one song: sections by energy, hits landed on downbeats, phrases or drops, natural sound protected (deep duck or drop-out), no back-to-back loops; returns the plan (edit ops, where each hit lands, joins) or applies it and measures the rendered mix.',
    'letitedit_caption_fit': "Lay out a project's captions so every word reads: line breaks, grouping, size and a place clear of faces, other text, platform buttons and protected regions ('phone' uses Shorts, TikTok and Reels zones; faces are hard constraints by default). Finds words that run together (outline, shadow, pop peak). Returns editable changes, violations with times, before|after crops from the export engine and what it could not solve; apply=True writes.",
    'letitedit_find_ranges': 'Exact ranges of what you describe in footage (picture first, so silent moments too): first and last frame, peak, a before/start/peak/end/after strip, an edit_item for letitedit_timeline_apply and an id that stays the same on every call; refines moments you give (around=) or returns stored ones (range_ids=). Camera moves are not cuts.',
    'letitedit_reframe': "Reframe clips to another shape (9:16, 4:5, 1:1, 16:9) keeping several things in frame at once - faces, hands, the part being shown, boxes you name - on a smooth, mostly still crop path (keyframed Size/Position); per subject how much of the time it is fully in the crop; where the required ones can't share one crop it says when and which, and offers a split or an inset as ready edits. apply=True writes (one undo step).",
    'letitedit_timing': "Timing, motion and rhythm as pictures and numbers, frame-accurate: view='map' (the rhythm map: shots and sizes, motion with the camera's own move removed, camera labels, speech, music beats, captions, loudness; every cut flagged by its offset from the beat and whether it lands on action; numbers per section), 'slow' (1-3 s frame by frame with motion arrows and the likely eye position), 'cuts', 'speech', 'joins', 'sync', 'trajectory', 'meaning', 'emotion' (raw footage: mood and energy per sentence with turning points; an AI's judgement, so hone in on each with 'slow'; options.moods = {name: meaning} scores your own moods too). Works on a project (a cached small render of it) or a video file; nothing is edited.",
    'letitedit_review_note': "Say what became of a Live Review note: done (what changed), could_not (why) or not_an_edit; the person's list shows it.",
    'letitedit_my_assets': "My assets: a folder where the person keeps their own logo, intro, outro, colours, clips, sounds, pictures and fonts, the same folder whichever video is open (kind, length, size, transparency, measured colours, their note; ref mine:<id> for assets, styles, pop-ups and graphics; an edit's clip takes the item's path); nothing = what is there and a sheet, id = one item with a picture and the edits that place it, description/kind/note save what you saw or they said, add/remove. Empty is normal.",
    'letitedit_assets': 'Search the asset library, licences included: emoji (Fluent still, Noto animated), icons (Tabler), animated stickers, graphics and transitions (Elements), CC0 sound effects (pops, whooshes, risers, glitches, booms, dings, cash, crowd, comedy...) and CC0 music; a sheet of the results. id/ref (emoji:fire, sfx:whoosh, anim:party): one asset ready to place - a PNG, the sound file with where it peaks, or an asset_sticker recipe - with its credit line if it owes one and the edits that place it.',
    'letitedit_segments': "A clip, folder or shoot as segments in recording order (split at recording gaps, GPS moves, "
                        "changes in people/camera facts and in what is said): times, facts holding across each, "
                        "moments, text seen, first words, a frame.",
    'letitedit_ask_frames': "One question to the local vision model at several times of a clip or a photo (choices "
                          "optional): its answer per time and a frame sheet, with its measured accuracy for that kind "
                          "of question.",
    'letitedit_words': "What is said, with times: a file, folder or list (source seconds) or a project (timeline "
                     "seconds); lines grouped by pause / max_words, or per_word.",
    'letitedit_library': "Music or sound effects on this PC (kind, query, bpm and length ranges): path, length, tempo; music also genre, mood, artist, licence, and, with an active supporter key, on-demand songs marked as such (fetch= brings one down). Songs holding long pure howl- or whistle-like tones are left out (whistle_tones_hidden counts them; with_whistle_tones=True lists them).",
    'letitedit_stock': "Stock video and photos, with a personal Pixabay key on this PC or an active supporter key (search, preview, fetch): ref, length, size, credit, licence; a chosen file comes down once. Personal Pixabay API results are cached for 24 hours.",
    'letitedit_real_picture': "Real pictures of named things (logo or app, person, place, book, product, animal, food) from open sources with no key (Wikipedia, Wikimedia Commons, Openverse, Open Library, or an address you found): search gives numbered candidates with licence and restrictions; fetch saves one beside the project with its record (source page, licence, author, when fetched), which exports and reviews list, with a line for what is made from it (cut-outs, pictures drawn from it, motion clips, graphics, code scenes); made_from records the real pictures behind a file you made yourself.",
    'letitedit_fetch': "Fetch the video behind a link (one video, no sign-in; yt-dlp fetched on first use, pinned and checked) (or a part of a longer one, up to 30 minutes) as a reference video for Match a video I like and letitedit_learn: saved in the person's own working folders with its record (link, title, uploader, when fetched), never in the library.",
    'letitedit_note': "Read or write notes on a source file.",
    'letitedit_quality_gate': "Measure a rendered video against the letitedit quality gate (length, loudness, pace, "
                            "first 3 s, silences, speech start, audible words): verdict and every check.",
    'letitedit_critic': "A blind second opinion on a render from a separate run of an AI on this PC: verdict, retell, ranked "
                      "problems with timecodes.",
    'letitedit_transcript': "Give a source file your own transcript (words with times, or SRT/WebVTT); every tool "
                          "that reads what is said uses it instead of the local one.",
    'letitedit_project_new': "A new empty project (size, fps, or like a clip), or a copy of one.",
    'letitedit_timeline_read': "A project as an edit script (YAML): tracks, items with ids, in/out, effects, words said; a long one compact (keyframes and long texts folded), ids or a range for one part; stack_at: the layers at a moment, back to front, in plain text.",
    'letitedit_timeline_apply': "Change a project: edit ops by id (`changes`), a whole script, or Python `code`; "
                              "every change is checked first; dry_run says what would change without writing; "
                              "returns what changed, and words on screen the edit added or changed that are held "
                              "shorter than their reading time. Edit ops include split edits (J and L cuts).",
    'letitedit_timeline_undo': "Undo the last apply.",
    'letitedit_check_frames': "Frames of a project as the export renders them (times_s / every_s / count, any number, "
                            "width), or shots=True: frames per shot; platform: that app's covered areas drawn on each frame.",
    'letitedit_check_range': "Render a range of a project with its sound (start_s, duration_s, width): MP4 path and a "
                           "filmstrip (frames); joins=True: the words and problems at every join in the range, and "
                           "the sound at every clip start and end in it (edges), as the review bundle's edge check "
                           "measures it.",
    'letitedit_check_audio': "Loudness of a project's mix or a range of it: integrated, range, peaks, readings every_s, "
                           "music vs voice (stems; on by default with a Music track), quiet stretches (quiet_lu), and tones: "
                           "sustained narrow whistle-, whine- or howl-like tones in the mix and the music (seconds, pitch, how far they stand above their surroundings).",
    'letitedit_export': "Render a project to MP4 in the background (preset, loudness, true_peak, start_s/end_s, "
                       "platform, bitrates, sample rate): a job id, and the credit lines the video owes for library "
                       "assets it uses (the animated emoji are CC BY 4.0) to put in its description. preview=True: "
                       "drawn smaller by the export engine with the final's sound, cached apart from the final. wait_s: "
                       "waits for the render and answers with letitedit_export_job's status of it.",
    'letitedit_wait': 'The result of a call that answered "still working" (call_id), pictures included, or "still working" '
                      'again. A call answers "still working" past the AI\'s own limit on a tool call, or past about '
                      '25 minutes.',
    'letitedit_export_job': "An export job's status; wait_s waits; a finished one comes with a sheet (sheet_every_s), "
                          "picture_change (shot lengths, where the picture stays nearly still) and sound_change (loudness "
                          "over time, louder/quieter stretches) and tones (sustained narrow howl- or whistle-like tones in the finished sound); credits: the lines the video owes. Any other render "
                          "can take the PC render lock through render_lock.py beside the installed tool server.",
    'letitedit_fonts': "Fonts on this PC (query, category): a sheet of each and its weights.",
    'letitedit_status': "What the PC is doing for letitedit: tool calls still running in this server, background jobs (running, queued, recent), export jobs, "
                      "who holds the PC render lock, GPU memory, free disk space, local models present.",
    'letitedit_jobs': "Background jobs: list, status, submit an index job (footage scan, transcripts, footage log) for a "
                    "folder or files, cancel, resume.",
    'letitedit_journal': "A project's journal (every apply and undo, by whom, plus notes), add a note (or several in one "
                       "call: entries), or release your edit lease; edits also take a lease and respect track owners.",
    'letitedit_platforms': "Facts per platform (YouTube, Shorts, TikTok, Instagram, Facebook): sizes, frame rates, "
                         "lengths, areas the app covers, limits, each with its source and how sure; frame: those areas "
                         "drawn on a frame.",
    'letitedit_hardware': "This PC's GPU, memory, CPU and disk, its tier, and which engine each local feature uses "
                        "(settings in C:/LetItEdit/settings.json; emotion_graph true builds the emotion graph on first import).",
    'letitedit_log_frames': "For writing the footage log yourself: a video's stretches in batches, each a sheet of three "
                          "frames with the words said and an id.",
    'letitedit_log_write': "Save your descriptions of a video's stretches as its footage log (the same fields as the "
                         "local model's: action, things, place, framing, text, quality).",
    'letitedit_measure': "Any video's measurable style: shots and cuts per minute, words per minute, speech/music/"
                       "effects shares, loudness, brightness and colours, on-screen text, contact sheets.",
    'letitedit_review_bundle': "One export reviewed end to end: pages of the whole video, larger frames at key and "
                             "flagged moments, the full transcript, the gate's measurements, the project's checks, "
                             "the brief's must-keep/must-avoid/claims/ending, an optional critic, and one verdict "
                             "(blocked / revise / incomplete / ready) with what was not checked, what only the person can act "
                             "on (for_you) and how many review rounds there have been (rounds). On a preview the size "
                             "checks judge the project's size; final_of=<reviewed preview> checks a final export against it; "
                             "render='preview' | 'final' (with project=) exports the timeline first and reviews that file. With "
                             "review_code_first on: measured checks before any critic, and review_order says whether "
                             "the critic ran (held, reuse, look, run).",
    'letitedit_places': "Where footage was filmed, from its own GPS: each file's coordinates and nearest place (offline "
                      "GeoNames), and files grouped by place.",
    'letitedit_versions': "Linked versions of a project at other sizes or platforms (each its own project): make one from "
                        "ranges of the main, every clip reframed on its subject with a visible effect; sync carries the "
                        "main's later changes and keeps the version's own; list.",
    'letitedit_archive': "Every already-indexed clip on this PC in one local database (transcripts, footage log, "
                       "recording time, camera, place): search by meaning with filters and a frame sheet of the hits, "
                       "status (what is in it, what is not indexed yet), update.",
    'letitedit_fix': "Repaired copies of the part of a source a clip uses (night: denoise and brighten; shake: "
                   "stabilise; punch: 2x punch-in that can follow the subject; voice: enhance, work sounds kept on "
                   "their own stem), applied as a visible {fix: ...} effect on the clip; a list of clips or a whole track in one call and "
                   "one undo step; revert, list; before/after measures and sheet.",
    'letitedit_3d': "Generated 3D clips of a model (.blend, .glb, .obj, .fbx ...) or built-in extruded title/logo rendered by Blender: list model parts, "
                  "preview, render camera moves with x-ray, highlights and callouts (MP4, alpha or frames; a timeline "
                  "item), marked generated.",
    'letitedit_map': "Maps drawn on this PC from clips' GPS or coordinates (offline Natural Earth and GeoNames): a still or "
                   "animated route with labels and a moving marker, any size and style (a timeline item), marked "
                   "generated.",
    'letitedit_motion': "Motion clips rendered by HyperFrames on this PC: animated titles, lower thirds, kinetic quotes, "
                        "word captions, count-ups, bar charts, steps, location tags, callouts, chapter and end cards, "
                        "stingers, or your own HTML/CSS/JS; preview stills, render a ProRes 4444 .mov with alpha (a "
                        "{motion: ...} timeline item in the project's Look), marked generated. Draws with the "
                        "PC's Edge or Chrome; where it can't run, timeline items are drawn as the nearest graphic. "
                        "action='shaders' lists optional M.shader canvas helpers, their settings, sources and licences; "
                        "saved scenes carry the named helpers. No WebGL: plain 2D stand-ins keep the scene visible.",
    'letitedit_object': "One object out of a shot as a layer (a tool, a part, a product): points on a frame, a mask to check, one clean outline the track carries, "
                        "or a plain reason when it bends, turns or leaves. {op: lift} brings it out over a new backdrop; {vfx: {effect: object}} outlines, recolours or keeps "
                        "it in front of what's behind it.",
    'letitedit_image': "Pictures for a video, drawn by whichever AI or key on this PC can draw (Antigravity first when installed, signed in and allowed by the other-AI switch; then the AI's own image tool; the person's own image "
                       "API key; another AI on this PC, if the person turned that on), or a plain message when nothing can: prompt, references, "
                       "characters, edit, count, shape, transparent. Returns each file, its size, the scale-up on this video and the picture "
                       "itself; everything is kept in the video's side folder with its words. status says who draws; history lists what was made.",
    'letitedit_code_scene': "A custom code scene saved beside a project: create puts a selectable scene on a Code scene "
                           "track and requires script to register M.block('custom', ...) with a frame function driven "
                           "by t; browser-only animation does not follow the playhead or export reliably. "
                           "revise keeps immutable source revisions and changes the open player's picture as "
                           "one Undo; it takes a whole script, html or css, or edits: [{old, new, in?}] exact text "
                           "replacements in the pinned revision's script (in: html or css for those), applied in order, "
                           "each old found exactly once, and nothing changed when one isn't. source returns the pinned "
                           "revision's script, html, css, params and duration (revision: another one). scene_id is the "
                           "scene's id, or the id of its timeline item. status lists scene items; versions lists their revision hashes; restore pins "
                           "one revision as one Undo; save copies the pinned revision and a moving thumbnail to "
                           "the person's My scenes folder; favorites lists those saves. render draws the pinned "
                           "revision at full quality. Both app Export and letitedit_export prepare full scene "
                           "renders before encoding. A revision's page holds its own copy of the runtime and any drawing kit it names, and "
                           "draws from that copy, whatever this PC has later, a kit's absence included. revise keeps that copy; "
                           "kept_from_this_scene and kept_note in its reply say what this PC has different or lacks. create uses what is on this PC; "
                           "a kit that isn't here comes from this project's scenes or My scenes when one of them has it. "
                           "The live player is on by default. create and revise return a look at the scene "
                           "in place (times and count choose its frames); look draws the scene now (a browser kept open, closed after 5 idle minutes), with the "
                           "person, captions and every other layer as the export layers them, as a contact sheet "
                           "(times: seconds from the scene's start, else count frames, 8 by default; revision: a version "
                           "other than the pinned one), and reports page errors, a blank scene and a scene that does not "
                           "move. letitedit_check_frames and letitedit_check_range show scenes the same way: the finished "
                           "render when one exists for that revision, else frames drawn now; a scene that could not be "
                           "drawn is named in the result and on its frame labels. create with behind_person=true also places "
                           "the cut-out of the footage under the scene on a track named Person above the scene's, one "
                           "{vfx: cutout} piece per clip under it over exactly the scene's time, in the same Undo step; "
                           "revise with behind_person=true does the same for a scene already there; pieces where a cut-out "
                           "already sits above the scene are skipped; the call returns when the mattes are made: about 10 s "
                           "per second of 60 fps footage the first time, however many pieces, as one job; mattes are kept per "
                           "frame, so a trim or a re-cut piece only writes the piece, about 3-5 s per second. "
                           "behind_person in the reply lists what was placed or skipped, the seconds, or why none was "
                           "made. A cut-out that can't be placed fails the call with the reason and adds no scene. The cut-out is its own item: revise leaves it alone, "
                           "and moving, trimming or deleting the scene does not move, trim or delete it. The page runtime is the "
                           "motion tool's: letitedit_guide('letitedit_motion') lists its helpers (curves, springs, "
                           "M.camera, M.stagger, canvas parts under M.draw) and how a param named font loads a bundled font.",
    'letitedit_looks': "Looks: list or read recipes and their own settings; copy one into My Looks, update a personal revision, "
                       "or read settings. Also keeps a project's Look inputs and pop-ups. One store with Learn; no uploads or "
                       "automatic migrations. Select defaults with {op: look, id}; generic effects, pop-ups and hooks remain.",
    'letitedit_hooks': "Opening candidates for a project in about a second (a moment with in/out, 2-3 text options, "
                       "approach, why), distinct and not shown before; more, previews; kept in hooks.json for the "
                       "app's Regenerate button; mark and add (your own candidates) in the same call. Swap with {op: hook}.",
    'letitedit_graphic': "Python-drawn graphics: without template, what can be drawn (word captions, a progress bar, "
                       "the Look's own templates, or your own code); with template/code, frames of it at times.",
    'letitedit_effects': "Engine effects (~760): search, read one's settings, preview on a clip.",
    'letitedit_vfx_effects': "Shot effects and narration that can be placed as clips, with their settings.",
    'letitedit_fit_music': "A song cut and joined on its own beats and bars to a length or to hit cut points: the new "
                         "file, every joint and where each hit landed.",
    'letitedit_song': "A song the video is cut to but that stays out of every export, for adding in the phone app when posting: "
                      "its usable parts, its place on a named muted track, cuts against its beats, the upload measured against it, "
                      "a preview with it and the facts for posting.",
    'letitedit_sync': "Line up a whole shoot by its sound (cameras, phones, separate recorders, many takes, claps): "
                      "one timeline with how sure each placement is and drift; optionally a synced project and copies "
                      "of the camera clips with the recorder's sound.",
    'letitedit_track': "Follow a box, point or face through a span of a video: its position and size over time as "
                     "numbers, and a check sheet.",
    'letitedit_import_srt': "Captions from SRT text (or an .srt file) into a caption track of the project open in "
                          "letitedit: a new track named track_name, or overwrite its items; lang is a 3-letter code; "
                          "drawn on the video once the track has a caption look ({op: captions, track, burn_in: true}).",
    'letitedit_bin': "Markers and picked subclips stored in the project, read or written; the person sees and adds to "
                   "them in letitedit.",
    'letitedit_look': "A sheet of frames from any files and projects: times or ranges, crops, labels, layout and size; "
                    "optional waveform, spectrogram, loudness, speech and word lanes.",
    'letitedit_try': "Versions of an edit on scratch copies (changes or code each), lined up by time, words or clip: "
                   "frames side by side, words, loudness, one MP4 of them back to back; joins=True: the words and problems "
                   "at every join of each. The project stays as it is.",
    'letitedit_overview': "One picture (or pages) of a whole edit or a range: lanes of thumbnails, clips, tracks, speech, "
                        "words, loudness, beats, graphics, captions, gaps, recording-time jumps.",
    'letitedit_stills': "Frames of a file or project as image files: any times, region and size.",
    'letitedit_search': "Moments in footage that look, sound or are said like a text query or an example moment "
                      "(picture, speech, sound or any): times, scores, a frame sheet.",
    'letitedit_speakers': "Who talks when and whose faces are seen (voice and face clusters with spans, sample words "
                        "and sample images); name them once and words carry the names.",
    'letitedit_separate': "Split a file's sound (or a range) into voice, drums, bass, other, music and rest: one file "
                        "each, with loudness.",
    'letitedit_hear': "Sound described in words over time: windows of a file or a project's mix scored against labels "
                    "(yours or a default list); a spectrogram on request.",
    'letitedit_voice': "Speech of a text in someone's voice cloned from a few seconds of a clip (or a default voice), "
                     "made on this PC (engine: dots-tts by default with a clip, chatterbox without one): the audio "
                     "file with word timings.",
    'letitedit_music_make': "Instrumental music written on this PC (ACE-Step 1.5) to a description and length, then cut on "
                          "its beats to a length, hit times or a project's cuts: the file, tempo, beats and how it lines "
                          "up.",
    'letitedit_music_write': "Music written note by note as a score (JSON) and performed in code on this PC, on any PC: no GPU, "
                           "download or network; the style vocabularies, a bar grid over the cut's words and cuts, every check, "
                           "the file at the film's exact length, and revisions by changing single lines.",
    'letitedit_import': "Your own edit as an editable project: an ffmpeg command or script, a Python or JSON edit "
                      "list, an EDL or OTIO file; what was kept as made clips, and with compare=True how its render "
                      "differs from the source's.",
    'letitedit_export_edit': "A project written back out as JSON, Python, an ffmpeg script, an EDL or OTIO (the "
                           "person's hand edits included).",
    'letitedit_command_help': "The app's How to reference (AI > How to / Command Finder), searched: for a feature (New "
                              "video, New hook, Review, My Looks, captions, Remove pauses, Add music, Other sizes, styles, "
                              "the Elements panel...) where its button is, what to open first, what it does, how to undo "
                              "it and its limits; an empty query lists every entry.",
    'letitedit_dub_lines': "Dubbing, step 1: what is said on a project's timeline as lines with times ([{i, start, end, "
                           "text}], um and uh left out) for you to translate.",
    'letitedit_dub': "Dubbing, step 2: the translated lines spoken on this PC (Kokoro voices: es, fr, it, pt, hi, ja, zh, "
                     "en, en-gb), each fitted into its slot, on a 'Dub (<language>)' audio track; the original voice "
                     "lowered (-20 dB), muted or kept; one undo step. Returns the file and how each line fit.",
    'letitedit_dub_voices': "The dubbing voices (all, or one language's) and each language's default male and female "
                            "voice.",
}

# The tools the server offers (toolset.txt may leave some out): every tool with a short text above, and these, which
# show their full description. A new tool is one entry in SHORT, its function registered by its family's
# register(mcp) in letitedit_mcp.py, and its module in letitedit_ai's list.
for name in PROJECT_READ_TOOLS:
    if name in SHORT:
        SHORT[name] = with_project_read(name, SHORT[name])

# T345 C2: with the switch next_step_replies on, the facts an AI otherwise looked up in the guide mid-phase
import letitedit.server.next_step_replies as _next_step  # noqa: E402
for name in _next_step.DESCRIBED:
    if name in SHORT:
        SHORT[name] = _next_step.describe(name, SHORT[name])

FULL_TEXT = ('letitedit_qc',)
TOOLS = frozenset(SHORT) | frozenset(FULL_TEXT)
