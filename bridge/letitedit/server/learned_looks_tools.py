"""Tool boundary for personal Look storage and reference comparisons."""


def register(mcp, Image):
    @mcp.tool()
    def letitedit_learn(action: str = 'list', reports: list[str] | None = None,
                       package: dict | None = None, expected_revision: str | None = None,
                       reference: str | None = None, result: str | None = None,
                       out: str | None = None, render: bool = False,
                       scores: dict | None = None, job_id: str | None = None) -> list:
        """Personal Looks outside the installation. list returns saved cards; prepare reads 1-3 importer
        report.json files and returns measurements/provenance; save writes a versioned recipe and optional Theme.
        measure takes reference=<local video>, or package={videos:[one to three files], folder?, kind?, notes?,
        separate?, classify_sfx?, refresh?}. It runs the existing cut, caption, movement, light, b-roll and sound
        detectors as a background Learn job. No pack or Look is published. job_id returns that job's progress,
        reports, pictures and merged facts; those reports are inputs to prepare.
        package: id (mine-...), title, line, needs, works_with (footage|no-footage|both), recipe (Markdown), reports
        (paths), observations ([{reference: zero-based index, at_s, part, observation}]), limitations ([text]),
        optional asks (New video boxes) and theme ({kind:kit|film,title,recipe}). An update needs expected_revision from list
        and may include sound (a measured learned-sound/1 profile). Omitted sound is preserved; null removes it.
        share: false keeps the Look on this PC (never sent to letitedit); omitted keeps the saved setting (default
        true). own_media {broll:[{folder, skip?:[folder names], what?}], intro:{file, where, reference_at_s?, seconds?,
        loudness_lufs?, notes?}, logo:{file, where, notes?}} names the person's own footage folders for cutaways, their
        own intro video and their logo; kept in
        look.json (never in the recipe, never sent), shown on the Look's card (letitedit_looks(action='get', id=...)) with the
        folders letitedit_search takes (subfolders included) and the progress of their picture index, which a save
        starts in the background (one file per PC-lock turn, below-normal priority, cached in the install's cache).
        Omitted own_media is preserved; null removes it.
        visual_reference takes reference (importer report), out (new private output folder), optional package
        {review:{reviewer,intervals:[{start_s,end_s,role,subject}],transitions:[{start_s,end_s,kind}],
        captions:[{start_s,end_s,text,blend_candidates}],rules:[text]},
        blend_samples:[{background,observed,mask}]} using aligned PNG clean plates and glyph-core masks.
        It returns a new enriched report, native inversion candidates and nine-mode letter-blend fits.
        Semantic review is caller-supplied, not automatic recognition. prepare exposes its visual profile;
        save may include visual (letitedit-visual-evidence/1). Omitted visual is learned from enriched reports,
        otherwise preserved; null removes it. Source identity/duration must match the reports.
        source_reference takes reference (importer report), out (new private folder), and optional package
        {segments:[{start_s,end_s,kind,status:reviewed|unknown,evidence,frames:[path]}],
        overlays:[{start_s,end_s,kind:caption|sticker|pip|sound_effect,status:reviewed|candidate,evidence,anchor}],
        overlay_coverage:{caption,sticker,pip,sound_effect:unassessed|partial|complete}}.
        Base-picture intervals cover the whole reference; captions and effects are separate overlays.
        picture_sheets takes reference (importer report) and out (private folder): contact sheets of the moments worth
        looking at (each cut, each sudden change in one region, each layout change, about one a second in long
        shots; at most 90 a minute, 9 or 10 numbered tiles a sheet with a 0.1 grid), their paths, the request file and
        the question to answer by looking at them. package picture_marks {request, pages:[{tiles:[first,last],
        items:[{kind:sticker|split,first,last,box|parts,end_box|end_parts,what,sure,why}]}]} on source_reference times
        each marked item by the frame differences inside its box at the file's own frame rate, snaps split parts to
        straight edges, and adds them as sticker and pip overlays (sure: reviewed; unsure: candidate), with sticker
        and pip coverage complete when every tile was marked.
        Known production kinds are reviewed declarations, never inferred from missing faces or detector silence.
        Returns an enriched report, sources.json, private HTML evidence and film/generate/render/screen routes.
        prepare exposes sources; save accepts sources, learns it from enriched reports or preserves it when omitted;
        null removes it. Catalog source_profile identifies the revision's sibling sources.json for New video.
        lighting_reference takes reference (importer report), out (private output folder) and optional package
        {samples_per_scene:3,max_scenes:24,roles:[{start_s,end_s,role,evidence}],model:auto|modnet|birefnet}.
        It samples person/background appearance under the PC lock, writes lighting.json and an enriched report.json.
        Visible light-colour and corner-darkness values are appearance proxies, not recovered lamps or haze.
        save may include lighting (a profile or list); omitted lighting is learned from enriched reports or preserved;
        null removes it. The measured recipe and sibling lighting.json carry the numbers into New video. Saving a
        lighting profile also saves grade.json beside it (letitedit-grade/1: each usable sample's black level,
        median, highlights, saturation and colour lean by brightness; graphics, native effects and black or flat
        frames left out) and a Measured grade recipe section: the Look's colour, applied with {op: fx, grade: true}
        on every clip of footage. A Look saved before grade.json has its grade worked out from lighting.json when read.
        package lighting_only:true retains the guarded revision's other evidence; unrelated recipe, metadata,
        observations, limitations, sound, visual and Theme changes are refused.
        kit_build takes out (private folder) and package {kit, size:[360,640], reference_video, examples:[{family,
        content,seconds,reference_frame,crop?:[x0,y0,x1,y1],times?:[entry,hold,exit],span_s:[start,end],
        parts:[{kind:text|mark|picture,box:[x0,y0,x1,y1] reference-frame pixels,text?,slot?,plate?,ink?:[#hex]}]}]}.
        kit has format letitedit-graphic-kit/1, style:{colors:{},fonts:{}}, families:[{id,job:speech|explanation|cta,
        rate_per_min:[min,max] or count_per_video:[min,max],duration_s:[min,max],persistence?:transient|stays|
        accumulates,placement,never_covers?:[face] (the default: placed clear of faces) or [],slots:[text],graphic:{
        template:custom,params:{animated:true},code:def draw(ctx): ...},anchor?:{to:speaker,slot},
        blend?:normal|difference|exclusion}]. blend is how the
        family's letters meet the picture under them: normal (the default) as drawn; difference or exclusion composited
        by the engine on every frame (white letters show the inverse of what is under them and change with the shot).
        A slot named ...picture holds a picture file path
        (ctx.image); a blank or missing picture is refused. An anchor names the slot holding the piece's vertical
        centre (frame share); kit_build adds what it measured on the reference frame (side below|above|over the face,
        face heights below the chin or above the brow, the share of the visible body, half height, measured:false
        without a face). An accumulates family gets params.kit_index (0, 1, 2...) per instance. Each family gets a
        private rendered comparison and is measured against its parts: text is drawn with the part's text (the
        reference's words) in its slot at the reference frame's size; rows give line count, text height, stroke,
        width per letter, slant, word colours (CIEDE2000), letter blend (fitted on the reference frame against the
        picture behind the letters painted in from around them: normal, difference/exclusion, or no row when the
        picture is too even or neither fits clearly; with an inverted reference the colour compared is the fitted one
        before the blend), plate yes/no, colour, corner radius and padding, centre,
        mark and picture size, colour and ink share, and time on screen measured in reference_video around span_s
        (stays to the end or not; seconds inside duration_s). Each row has the reference, ours, the tolerance and
        passed; failed stroke, width or slant rows list bundled fonts ranked by those numbers and letter shape.
        Private likeness sheets and likeness-private.json go in out. kit.measured names the families inside every
        tolerance; save refuses a new kit with a family outside it. Omitted kit preserves, null removes. A save with a
        new kit also needs fits ("Fits videos that ...", plain words). Drawings are portable Python graphics; slots
        contain only new content, not drawing code.
        kit_plan takes reference (saved graphic-kit.json), optional result (project) and package
        {placements:[{family,at,seconds,content:{text:...},face?:[x0,y0,x1,y1]}],video_s?}; a stays or accumulates
        family without seconds runs to the video end. A blend family's pieces carry the engine's glyph-layer blend
        effect ({filter:cairoblend_mode,params:{mode}}). An anchored family without its slot is placed by the face
        (given, or found on result's main picture at that time): the same place on the body when it fits inside the
        uncovered frame (bottom edge 0.80, top 0.07), else the same share of the visible body, clear of the face;
        each placement lists anchored and a note when moved. Returns frozen placement ops without applying them.
        kit_check takes reference and result (project), optional package {video:path}; checks visible family
        rates/durations (stays and accumulates families must last to the end) and real pictures in picture slots, and
        measures on every native rendered frame where kit ink falls inside a detected face box: face_overlap_frames,
        and face_cover for the whole kit's ink together (frames, seconds, first frame, and pieces_on_screen: every
        piece placed at those frames, without saying which covered the face), as facts, with a note when one of those
        pieces is of a family whose never_covers is [face]. picture lists what was done to the speaker's picture (smaller than the frame, blurred,
        graded, see-through), as facts. For each piece of a blend
        family it returns inversion rows: fully-on frames (opaque letter cores; entrances, exits and two-frame negative
        flashes left out), those where inverted letters have under 1.5:1 median contrast with the picture under them,
        and choose: plain white (normal) when that is more than half, else the family's blend; a piece placed otherwise
        is a finding with its edit (effects: null for white, the blend effect back for inverted). letitedit's own live lighting
        on the picture, which only lifts the face, is measured with lighting.check_live (a darker or tinted face is a
        finding; room change reported).
        Missing local detector/render evidence fails; detector silence is reported, not proof of face absence.
        Old recipe/Theme/evidence revisions remain on disk. No reference media is copied.
        match reads reference/result importer reports, writes part-by-part measurement evidence and a critic brief
        in out; render adds a private side-by-side MP4 and 1fps pages, under the render lock. scores records an
        independent critic's part scores (0-10 or null), evidence, limits and engine/model/effort; it is not generated
        by the measuring code. sound_reference takes reference (importer report), out and optional package
        {music_limit:48,effect_limit:96}; it separates sound and ranks local licensed audio under the PC lock.
        sound_plan takes reference (sound.json), result (project) and package {duration_s,voice_dbfs,
        anchors:[{at,role:cut|broll|emphasis|reveal|swell|drop|stop,sound?:whoosh|hit|riser|click|ambience}],
        audition:false}; returns a soundtrack request and effect edit ops without applying them.
        Unconfirmed events need audition:true; role-library proposals are not identified reference effects.
        place_evidence takes reference (a video file, or an importer report.json) and returns what its words and
        footage supply: seconds, the footage kind (talking-head, conversation, activity, screen), talk share, and counted
        signals with quoted evidence (list_items, named_things, numbers, questions, steps, groups, contrast, story, cta),
        the names said and the opening and ending lines. It reads cached transcripts (package {transcribe:true} makes them).
        place_check takes package {place, reports?} and returns the place as save stores it, or the error. save takes
        package.place (letitedit-look-place/1): subject (what the reference is about), pattern (the general pattern),
        uses (4-16 kinds of content it could dress), not_for?, length short|long|both, seconds [min,max], role
        look|theme|both, styles (Style ids it fits, main first, or {new:{title,filmed,blurb}} when none fits; a new one is
        kept in My Looks' styles.json and reused by title), footage {kinds, speech needed|optional|none, people?, what},
        structure {arc, opening, ending, chapters?, sections:[{id, job, does, needs:[need ids], seconds, repeats, optional}]},
        needs [{id, what, signal (a place_evidence signal, talk, words, people, or ai), min, max?, must, why,
        kind?:content|format, without?}] and devices
        [{name, kind style|content, when (content only), why}]. Names said in the reference may not appear in the pattern,
        uses or a new Style's title. Content needs are optional even with must:true; without describes the alternative
        and is required for kind:content. Format needs can remain required. A saved graphic kit needs a place;
        the catalogue's fits become its Style ids.
        fit takes reference (Look id, place.json or recipe path) and result (clips, a folder) with optional package
        {transcribe:false,budget_s:4,format:short|long}: fits|maybe|partly|no|unknown, a plain line,
        framing (all measured clip shapes, target shape, mismatch and layout options), found/missing/unchecked needs, leaves
        (optional needs the clips lack: fits and maybe hold with them, the cut leaves those parts out) and which format
        sections the clips can fill (a section's without: the optional needs it is built without); a Look saved without a place gives unknown with no_place:true (it still
        works). plan_check takes reference (Look) and result (story_plan.json or project): problems with its format plan
        (format: {fit, sections:[{id, built, count, content, at, why}], left_out, content_devices}); no_place:true and no
        problems for a Look without a place. Learn's done step refuses a Look without a place; older saved Looks without
        one still load and are used.
        project takes reference (a finished project, .mlt), optional result (which exported video of it; default its
        newest final export) and out (private folder). It returns and writes project-evidence.json: version (the video,
        and the exact timeline it was exported from: the export record, a hash match with the saved timeline or a
        history snapshot, or the timeline saved just before the newest export; none when no timeline matches, then
        nothing is exact), other_versions, exact (the timeline's values part by part: pacing, angles, cutaways, framing,
        captions with font, size, colours, outline, box and cue lengths, graphics and their fonts, stickers, splits,
        speed, sound effects, music levels and fades, transitions, grade and lighting filters; no words, names or
        text), provenance (who set each value in the final timeline: person, ai or both, from the project's history and
        journal; counts weighted person 3, both 2, ai 1), route (stages, edits by whom, undos, reviews), made_with (the
        Look, Style and Theme from the brief and where the video differs from that Look's kit) and instructions (the
        person's recorded words to the AI, with their always/never sentences). A project with no export returns
        no_export. save takes package.project (that file's path; reports must include the importer report of the
        same video) and optional package.rules ([{words, said_at}]: always/never sentences the person said, as
        recorded); it keeps project.json beside the recipe, adds an "Exact values from the finished video" section
        when the recipe has none, and a "Your own rules" section; catalog project_profile names project.json.
        See letitedit-learn skill for learning and comparison know-how."""
        import letitedit.looks.learned_looks as learned_looks
        try:
            if action == 'measure':
                from letitedit.looks import learn_measure
                return [learn_measure.status(job_id) if job_id else learn_measure.submit(reference, package)]
            if action == 'list':
                return [learned_looks.catalog()]
            if action == 'prepare':
                return [learned_looks.prepare(reports)]
            if action == 'save':
                return [learned_looks.save(package, expected_revision)]
            if action == 'project':
                import letitedit.looks.project_look as project_look
                return [project_look.evidence(reference, result, out)]
            if action in ('kit_build', 'kit_plan', 'kit_check'):
                import letitedit.looks.graphic_kit as graphic_kit
                if action == 'kit_build':
                    return [graphic_kit.build(package, out)]
                if action == 'kit_check':
                    return [graphic_kit.check(reference, result, (package or {}).get('video'))]
                from letitedit.looks.look_check import current_project
                return [graphic_kit.plan(reference, package, current_project(result)[2] if result else None)]
            if action == 'sound_reference':
                import letitedit.looks.learned_sound as learned_sound
                return [learned_sound.analyse(reference, out, package)]
            if action == 'visual_reference':
                import letitedit.looks.style_import_visual as style_import_visual
                return [style_import_visual.reference_report(reference, out, package)]
            if action == 'picture_sheets':
                import letitedit.looks.style_import_marks as style_import_marks
                return [style_import_marks.prepare_report(reference, out)]
            if action == 'source_reference':
                import letitedit.looks.style_import_sources as style_import_sources
                return [style_import_sources.reference_report(reference, out, package)]
            if action == "lighting_reference":
                import letitedit.looks.lighting as lighting
                return [lighting.analyse_report(reference, out, **(package or {}))]
            if action == 'sound_plan':
                import letitedit.looks.learned_sound as learned_sound
                return [learned_sound.plan(reference, result, **(package or {}))]
            if action in ('place_evidence', 'place_check', 'fit', 'plan_check'):
                import letitedit.looks.look_place as look_place
                if action == 'place_evidence':
                    source = reference
                    if source and str(source).lower().endswith('.json'):
                        source = learned_looks._read(source)['file']
                    measured = look_place.measure([source], transcribe=bool((package or {}).get('transcribe')))
                    measured['format'] = 'letitedit-place-evidence/1'
                    measured['signal_meanings'] = {key: value[1] for key, value in look_place.SIGNALS.items()}
                    return [measured]
                if action == 'place_check':
                    return [learned_looks.check_place((package or {}).get('place'), (package or {}).get('reports'))]
                try:
                    place = look_place.load(reference)
                except look_place.NoPlace as missing:
                    if action == 'fit':
                        return [look_place.no_place(reference)]
                    return [{'problems': [], 'no_place': True, 'note': str(missing)}]
                if action == 'fit':
                    options = package or {}
                    measured = look_place.measure([result] if isinstance(result, str) else result,
                                                  transcribe=bool(options.get('transcribe')),
                                                  budget_s=float(options.get('budget_s', 4.0)))
                    return [{**look_place.fit(place, measured, options.get('format')), 'measured': {
                        key: measured.get(key) for key in ('seconds', 'footage', 'signals', 'evidence', 'names',
                                                           'not_transcribed', 'frame', 'frames')}}]
                import json
                from pathlib import Path
                plan_path = Path(result)
                if plan_path.suffix.lower() != '.json':
                    import letitedit.review.review_bundle as review_bundle
                    plan_path = review_bundle.story_plan_path(project=str(plan_path))
                    if plan_path is None:
                        return [{'problems': ['no story_plan.json beside the project']}]
                plan = json.loads(Path(plan_path).read_text(encoding='utf-8-sig'))
                return [{'story_plan': str(plan_path), 'problems': look_place.plan_check(place, plan)}]
            if action == 'match':
                import letitedit.looks.look_match as look_match
                return [look_match.bundle(reference, result, out, render=render, scores=scores)]
            raise ValueError('action must be list, measure, prepare, save, project, match, kit_build, kit_plan, kit_check, source_reference, picture_sheets, visual_reference, lighting_reference, sound_reference, sound_plan, place_evidence, place_check, fit or plan_check')
        except (OSError, ValueError, TypeError, KeyError) as error:
            return [{'error': str(error)}]
