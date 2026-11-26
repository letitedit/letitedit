# letitedit\pictures

Captions, graphics, motion clips, code scenes, 3D, maps, objects and reframing.

- `annotate`: Annotations that point at something in a clip: a ring, arrow, box, label or magnified detail, placed by the software from coordinates in the clip's OWN source picture.
- `caption_layout`: Caption layout solver behind letitedit_caption_fit.
- `caption_readability`: Conservative phone-size ink checks over every encoded native frame.
- `code_scenes`: Saved, revisioned code scenes for the live player and exact export.
- `gen_common`: Shared parts of generated clips (render3d.py, maps.py): colours, fonts, encoding RGBA frames, frame sheets, 'generated' metadata.
- `graphics`: Python-made graphics: title cards, lower thirds, callouts, badges, chapter cards, end cards, or any custom drawing.
- `graphics_runner`: Runs one custom graphic job in its own process (started by graphics._render_sandboxed with python -I).
- `image_gen`: letitedit_image: pictures for a video, drawn by whichever AI or key on this PC can draw, and kept in the video's side folder.
- `maps`: Maps drawn locally from clips' GPS (geo.py) with offline Natural Earth data (public domain), still or animated: a route line drawing between places in recording order, place labels, a moving marker, camera moves from region to place....
- `motion`: Motion clips: animated titles, lower thirds, kinetic text, count-ups, charts, end cards...
- `object_layer`: An object cut out of a shot, as a layer.
- `object_lift`: {op: lift}: an object comes out of the shot, holds, and goes back, with its moves as keys on the timeline.
- `reframe`: Reframing solver: crops of another shape (9:16, 4:5, 1:1, 16:9 or any size) that keep several things in frame at once - faces, hands, the part being worked on, anything named - with calm, smooth camera motion; and, where the things that...
- `render3d`: 3D render kit: clips of any creator's 3D model (.blend, .glb/.gltf, .obj, .fbx, .stl, .ply, .usd*, .dae) rendered headless by Blender, for when a shot can't be filmed.
- `scene_look`: Frames of a code scene from a browser that stays open (the AI's fast look at a scene).
- `vfx_items`: Shot effects and narration as timeline items: the creator / VFX features as words in the edit script.
- `annotate_chain`: The clip's picture chain as data, the target in source pixels, and source times as timeline frames.  (no old name: imported as `letitedit.pictures.annotate_chain`)
- `annotate_check`: The checks against the export engine.  (no old name: imported as `letitedit.pictures.annotate_check`)
- `annotate_draw`: The drawing, which runs in the graphics sandbox.  (no old name: imported as `letitedit.pictures.annotate_draw`)
- `annotate_geometry`: The settings and the shared geometry: boxes and matrices, MLT values, media orientation and size, the clip on the timeline.  (no old name: imported as `letitedit.pictures.annotate_geometry`)
- `annotate_screen`: What else is on screen, and the layout of labels and insets.  (no old name: imported as `letitedit.pictures.annotate_screen`)
- `caption_contrast`: Contrast of burned-in (native subtitle) captions against the picture around them, frame by frame.
- `caption_layout_cues`: Caption layers and cues, line breaks and grouping.  (no old name: imported as `letitedit.pictures.caption_layout_cues`)
- `caption_layout_frame`: The module's settings and errors, geometry and the frame: boxes, the frame's size, platform overlays and the safe area.  (no old name: imported as `letitedit.pictures.caption_layout_frame`)
- `caption_layout_place`: Obstacles, placement and violations.  (no old name: imported as `letitedit.pictures.caption_layout_place`)
- `caption_layout_render`: Fonts and measuring text, real renders with the export engine, and the word-caption template recorded.  (no old name: imported as `letitedit.pictures.caption_layout_render`)
- `caption_layout_solve`: The native caption layers and the word-caption layers, solved.  (no old name: imported as `letitedit.pictures.caption_layout_solve`)
- `caption_layout_words`: Words and break points: what may end a line, what must stay together, words run together.  (no old name: imported as `letitedit.pictures.caption_layout_words`)
- `caption_reuse`: What letitedit_caption_fit measured, reused for pictures and caption texts that didn't change.  (no old name: imported as `letitedit.pictures.caption_reuse`)
- `real_pictures`: Real pictures of named things (a logo or app, a person, a place, a book, a product, an animal, a food), found in open sources that need no key or sign-up and fetched into the video's own folder, each with a record of where it came from....
- `reframe_geometry`: The settings and the geometry: boxes, the target shape and crop, the linear program, who fits where.  (no old name: imported as `letitedit.pictures.reframe_geometry`)
- `reframe_path`: The crop path solved, and its keyframes (what renders).  (no old name: imported as `letitedit.pictures.reframe_path`)
- `scene_time_map`: A code scene's time map: the drawing follows the cut.  (no old name: imported as `letitedit.pictures.scene_time_map`)

Each module here also answers to its old name in `bridge\` (a small alias file: one module object under both names); inside the package, import the real name. What the other jobs may use from here: `IMPORTS.md`. The whole map: `CODEMAP.md` at the top of the repository.
