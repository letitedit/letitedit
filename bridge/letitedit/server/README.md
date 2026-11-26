# letitedit\server

The tool server: the tools by family, their texts, the guide and the tool set.

- `annotate_tools`: MCP tool: point at something in a clip (annotate.py) - plan, preview, apply, refresh, list.
- `archive_tools`: MCP tool letitedit_archive: search, status and update of the footage archive (archive.py).
- `assets_tools`: MCP tool: the asset library (bridge/assets.py) - emoji, icons, stickers, graphics, transitions, sound effects and music letitedit can place, searched in one index with their licences.
- `caption_layout_tools`: MCP tool: the caption layout solver (caption_layout.fit / caption_layout.apply_plan).
- `check_tools`: MCP tools for fast, truthful checks and crash-proof exports (no editor window needed).
- `command_help`: The app's How to reference: command-reference.json at the install root, the same entries the editor's AI > How to / Command Finder shows.
- `core_tools`: The core tool set: what Claude needs to make and finish a video by script (see GUIDE.md).
- `dub_tools`: Dubbing a project into another language: letitedit_dub_lines, letitedit_dub, letitedit_dub_voices.
- `editor_tools`: MCP tool letitedit_editor: what the person is looking at in an open letitedit window right now.
- `factlog_tools`: MCP tools of the fact log (factlog.py): letitedit_ask_frames (one question to the local vision model over a range of a clip) and letitedit_segments (the segment map of a clip, folder or list of files).
- `fix_tools`: MCP tool letitedit_fix: fix-in-post repairs (night/noise, shake, punch-in, voice) of a file range or a project clip.
- `formats_tools`: MCP tool: linked versions of a project for other sizes/aspects (make, sync, list).
- `geo_tools`: MCP tool: GPS coordinates and nearest place of media files (geo.place).
- `guide_v2`: The v2 reference (toolset.txt 'v2'): an index by default; any tool's full description, or one section, on request.
- `hardware_tools`: MCP tools letitedit_hardware, letitedit_log_frames, letitedit_log_write (hardware.py, llm_log.py).
- `jobs_tools`: MCP tools letitedit_status and letitedit_jobs (background job queue, render lock, GPU, disk, local models).
- `journal_tools`: MCP tool: a project's journal (every apply and undo, plus free notes), its edit lease and its track owners.
- `kit_tools`: MCP tools: fonts, Look defaults, Python graphics and the engine's effects catalogue.
- `learned_looks_tools`: Tool boundary for personal Look storage and reference comparisons.
- `long_calls`: Tool calls that outlast the AI's own limit on a tool call.
- `maps_tools`: MCP tool letitedit_map: generated maps from clips' GPS with offline map data (maps.py).
- `motion_tools`: MCP tool letitedit_motion: make a motion clip (animated title, lower third, kinetic text, count-up, chart, end card...) from our own blocks or your own HTML/CSS/JS, rendered by the HyperFrames engine (motion.py).
- `music_gen_tools`: MCP tool letitedit_music_make: instrumental music generated on this PC and fitted to a cut (music_gen.py).
- `my_assets_tools`: MCP tool: My assets (bridge/my_assets.py) - the person's own logo, intro, outro, colours, clips, sounds, pictures and fonts, kept in one folder that works on every video.
- `object_tools`: MCP tool letitedit_object: an object cut out of a shot, as a layer.
- `platforms_tools`: MCP tool: platform profiles (published specs, export settings, covered areas of the frame).
- `range_search_tools`: MCP tool: exact ranges (start/end frames) of what is looked for in footage, with previews and stable ids (range_search.find).
- `reference_tools`: MCP tool: measure a reference video (reference.measure).
- `reframe_tools`: MCP tool: reframing solver (reframe.py) - plan, preview, offers (split / inset), apply.
- `render3d_tools`: MCP tool letitedit_3d: list a 3D model's parts, preview and render generated 3D clips (render3d.py).
- `review_tools`: MCP tool: a full-length review bundle and one delivery verdict for an export (review_bundle.bundle).
- `shot_match_tools`: MCP tool: match clips' exposure, white balance and tone to a reference shot (shot_match.match).
- `soundtrack_tools`: MCP tool: a deliberate score from one song (soundtrack.py).
- `takes_tools`: MCP tool: repeated takes of the same passage, grouped and measured side by side (takes.find).
- `timeline_tools`: MCP tools: read and edit a timeline as an edit script (no clicking through the editor window).
- `timing_tools`: MCP tool of the timing perception layer: letitedit_timing(source, view=...) with one view per kind of question (the views register themselves in timing_views; TIMING-SPEC.md).
- `tool_docs_v2`: Short tool descriptions for the v2 tool set (toolset.txt 'v2'): what goes in and what comes out, in a line or two.
- `toolset`: Which letitedit tools a run gets, from toolset.txt next to bridge\ (read when a server or script starts; the one switch: LETITEDIT_TOOLS is not read):
- `v2_tools`: MCP tools added by the v2 redesign (toolset.txt 'v2'): import the agent's own edit and export it back, views, scratch versions, music fitting, sync, tracking, shared markers and bin, sound separation and description, search, speakers...
- `books`: The rest of New video's bookkeeping in code: the beat, loop and cut markers, the licence notes of library files, and markers that follow their clips through an edit.  (no old name: imported as `letitedit.server.books`)
- `caption_follow`: Captions that follow their fit through an edit.  (no old name: imported as `letitedit.server.caption_follow`)
- `compact_reply`: Compact check replies with the full evidence on disk.  (no old name: imported as `letitedit.server.compact_reply`)
- `fetch_tools`: MCP tool: fetch a video from a link, as the reference video for "Match a video I like" and Learn (bridge/letitedit/footage/ fetch_link.py).
- `next_step_replies`: Replies that carry what the next step reads, and calls that take the shapes an AI sends.  (no old name: imported as `letitedit.server.next_step_replies`)
- `real_picture_tools`: MCP tool: real pictures of named things (bridge/real_pictures.py) - a logo or app, a person, a place, a book, a product, an animal, a food - from open sources that need no key, fetched into the video's own folder with their record....
- `scene_follow`: Drawn scenes that follow the cut.  (no old name: imported as `letitedit.server.scene_follow`)
- `self_checks`: Ops that check their own result.  (no old name: imported as `letitedit.server.self_checks`)
- `tool_profiles`: Tool profiles: the letitedit tools one New video or Studio phase is offered.  (no old name: imported as `letitedit.server.tool_profiles`)

Each module here also answers to its old name in `bridge\` (a small alias file: one module object under both names); inside the package, import the real name. What the other jobs may use from here: `IMPORTS.md`. The whole map: `CODEMAP.md` at the top of the repository.
