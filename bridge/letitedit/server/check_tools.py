"""MCP tools for fast, truthful checks and crash-proof exports (no editor window needed).

`project` accepts a saved .mlt path, a managed episode/cut folder, or "live" (the open editor, including
unsaved changes). Everything is rendered by melt, the same engine as the final export.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import time
import json
from pathlib import Path

import letitedit.review.checks as checks
import letitedit.server.compact_reply as compact_reply
import letitedit.server.long_calls as long_calls
import letitedit.timeline.render_queue as rq


EXPORT_WAIT_MAX_S = 1440.0   # export_job's longest wait in one call (24 min, under long_calls' 25)
PROBLEM_CHARS = 400          # a pre-export finding longer than this is cut in the reply (the full text is in its file)


def _brief_preexport(status):
    """An export status with its pre-export checks as what the AI acts on: passed, blocks_export, the findings (each
    cut to PROBLEM_CHARS) and the file that holds every check in full (the project's .export-checks.json, which the
    review reads). The measured evidence inside the checks (a Look's lighting and grade files, caption measurements)
    stays in that file."""
    pre = status.get('preexport_checks') if isinstance(status, dict) else None
    if not isinstance(pre, dict):
        return status
    import letitedit.timeline.export_checks as export_checks
    findings = []
    for f in pre.get('findings') or []:
        f = dict(f) if isinstance(f, dict) else {'problem': str(f)}
        text = str(f.get('problem') or '')
        if len(text) > PROBLEM_CHARS:
            f['problem'] = text[:PROBLEM_CHARS].rstrip() + f' ... ({len(text)} characters in all, in the file)'
        findings.append(f)
    brief = {k: pre[k] for k in ('passed', 'checked', 'unavailable', 'blocks_export', 'delivery_warning', 'error')
             if k in pre}
    brief['findings'] = findings
    brief['checks_run'] = sorted((pre.get('checks') or {}).keys())
    if status.get('project'):
        brief['file'] = str(export_checks.receipt_path(status['project']))
    return {**status, 'preexport_checks': brief}


def _finished_sheet(status, every_s=None):
    """A contact sheet of a finished export (a frame every every_s seconds, default ~5, 4 across), or None."""
    import io
    import subprocess
    from pathlib import Path
    out = status.get('output') if isinstance(status, dict) else None
    if not out or status.get('state') != 'done' or not Path(out).exists():
        return None
    import hashlib
    st = Path(out).stat()
    marker = checks.CACHE / 'export_sheets' / (hashlib.sha1(f'{out}|{st.st_size}|{st.st_mtime_ns}|{every_s}'.encode()).hexdigest()[:16] + '.jpg')
    if marker.exists():
        return marker.read_bytes()
    import letitedit.timeline.made as made
    ff = made.ffmpeg_exe()
    nw = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    pr = subprocess.run([str(ff).replace('ffmpeg.exe', 'ffprobe.exe'), '-v', 'error', '-show_entries', 'format=duration',
                         '-of', 'csv=p=0', out], capture_output=True, text=True, creationflags=nw)
    try:
        dur = float(pr.stdout.strip())
    except ValueError:
        dur = 150.0
    step = max(0.1, float(every_s)) if every_s else max(5.0, dur / 60)
    rows = max(1, -(-int(dur // step + 1) // 4))
    r = subprocess.run([str(ff), '-v', 'error', '-i', out, '-vf', f'fps=1/{step:.3f},scale=480:-2,tile=4x{rows}',
                        '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-q:v', '4', '-'], capture_output=True,
                       creationflags=nw)
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(r.stdout)
    except OSError:
        pass
    return r.stdout


def _measured_state(project):
    """The project file a check measures: an open window's state now (a snapshot), else the saved file."""
    return str(checks.resolve(project)[1])


def measure_audio(project, stems=None, target_lufs=-14.0, start_s=None, end_s=None, every_s=None, quiet_lu=15.0):
    """letitedit_check_audio without MCP: (png bytes, report). The same cut and settings measured before give that
    measurement back (reused) with no new render; a whole-timeline measurement is recorded in the journal."""
    settings = dict(stems=stems, target_lufs=target_lufs, start_s=start_s, end_s=end_s, every_s=every_s,
                    quiet_lu=quiet_lu)
    signature, hit = None, None
    if str(project).lower().endswith('.mlt'):
        try:
            # the cut checks.audio measures: an open window's timeline, unsaved changes included
            with checks.as_window_shows(project):
                signature = checks.audio_signature(project)
            hit = checks.audio_measured(project, signature, **settings)
        except Exception:  # noqa: BLE001 - measure it afresh
            hit = None
    if hit:     # the same cut and settings as a measurement already made: its numbers, no new render
        png, report = hit
        report = dict(report, reused='the cut has not changed since this was measured (same clips, cut points, '
                                     'levels and sound effects), so these are that measurement\'s numbers')
    else:
        png, report = checks.audio(project, **settings)
        if signature:
            checks.audio_keep(project, signature, png, report, **settings)
    if signature:
        try:   # the review bundle reads this to say whether the mix was measured
            import letitedit.timeline.project_journal as project_journal
            whole = start_s is None and end_s is None
            project_journal.record(project, 'sound_check', text=f"integrated {report.get('integrated_lufs')} LUFS",
                                   audio=signature, **({} if whole else {
                                       'range': report.get('range') or f"{start_s or 0:g}-{'end' if end_s is None else f'{end_s:g}'} s"}))
        except Exception:  # noqa: BLE001 - the measurement stands without the record
            pass
    return png, report


def caption_readability(project, video=None, solid_fallback=False, dark_edge=False, inverted_then_white=False,
                        apply=False):
    """letitedit_caption_readability without MCP: its reply list. The answer is JSON either way; a check that didn't
    run never passes."""
    try:
        return _caption_readability(project, video, solid_fallback, dark_edge, inverted_then_white, apply)
    except Exception as error:  # noqa: BLE001 - the answer is JSON either way; a check that didn't run never passes
        return [{'passed': False, 'checked': False, 'unavailable': True,
                 'reason': (str(error).strip() or type(error).__name__)[:1500], 'problem_kind': type(error).__name__}]


def _caption_readability(project, video, solid_fallback, dark_edge, inverted_then_white, apply):
    if inverted_then_white:
        if solid_fallback or dark_edge:
            raise ValueError('Colour selection cannot be combined with an edge aid')
        import letitedit.looks.caption_colour as caption_colour
        return [caption_colour.measure(project, video, apply=apply)]
    if apply:
        raise ValueError('apply is used with inverted_then_white')
    import letitedit.pictures.caption_readability as caption_readability
    if not (solid_fallback or dark_edge):
        kept = _caption_check_kept(project, video)
        if kept:
            return [kept]
    changed = caption_readability.outline(project, solid=solid_fallback) if (solid_fallback or dark_edge) else None
    result = {'changed': changed, **caption_readability.measure(project, video)}
    if not changed and (result.get('applicable') is False or result.get('unsupported')
                        or 'native' in str(result.get('reason', ''))):
        import letitedit.pictures.caption_contrast as caption_contrast     # burned-in caption tracks: fill against the picture around it
        result['native'] = native = caption_contrast.measure(project, video)
        if result.get('applicable') is False and native.get('passed') is not None:
            # burned-in captions are all there is: the top level says what they measured
            result['passed'] = bool(native['passed'])
            result['measured'] = 'native'
            result['reason'] = (f"Burned-in captions measured: {native.get('cues_measured')} of "
                                f"{native.get('cues_total')} cues, {native.get('hard_to_read_count')} hard to read; "
                                "no kinetic_type or word_captions tracks")
    if not changed:
        _caption_check_keep(project, video, result)
    return [result]

def _caption_check_key(project, video):
    """The project file's bytes and the video file's size and time: the same inputs measure the same."""
    import hashlib
    path = Path(project)
    if path.suffix.lower() != '.mlt' or not path.is_file():
        return None
    import letitedit.pictures.caption_readability as caption_readability
    key = hashlib.sha256(path.read_bytes()).hexdigest() + f'|v{caption_readability.MEASURE_VERSION}'
    if video:
        st = Path(video).stat()
        key += f'|{Path(video).resolve()}|{st.st_size}|{st.st_mtime_ns}'
    return key

def _caption_check_store(project):
    import letitedit.timeline.project_journal as project_journal
    return project_journal.folder(project) / 'caption_check.json'

def _caption_check_kept(project, video):
    try:
        key = _caption_check_key(project, video)
        kept = json.loads(_caption_check_store(project).read_text(encoding='utf-8-sig')).get(key) if key else None
    except (OSError, ValueError):
        return None
    if not kept:
        return None
    return {**kept, 'reused': 'the project file and the video are the same as when this was measured, so these '
                              'are that measurement\'s numbers'}

def _caption_check_keep(project, video, result):
    try:
        key = _caption_check_key(project, video)
        if not key:
            return
        store = _caption_check_store(project)
        store.parent.mkdir(parents=True, exist_ok=True)
        try:
            kept = json.loads(store.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            kept = {}
        kept.pop(key, None)
        kept[key] = result
        store.write_text(json.dumps(dict(list(kept.items())[-6:]), default=str), encoding='utf-8')
    except (OSError, TypeError, ValueError):
        pass        # the measurement stands without the memory


def _edges_brief(project, start_s, end_s):
    """checks.edge_sounds over a range with a verdict line: {verdict, checked, at} or {error}."""
    try:
        found = checks.edge_sounds(project, start_s, end_s)
    except Exception as exc:  # noqa: BLE001 - a measurement beside a check, never a reason to fail the check
        return {'error': f'clip edges not measured: {exc}'}
    rows = found['at']
    major = sum(1 for r in rows if r.get('review') == 'major')
    verdict = ('no clip edges' if not found['checked'] else 'clean' if not rows else
               f"{len(rows)} of {found['checked']} clip edges go through sound"
               + (f" ({major} the review counts as major)" if major else ''))
    return {'verdict': verdict, **found}


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_look_check(project: str, look: str | None = None, decisions: dict | None = None,
                           video: str | None = None) -> list:
        """Look device receipt for captions, transitions, broll, lighting, sound, opening, punchins and sound_accents,
        plus shot_sources and stickers when sources.json exists, and grade when the Look has a measured grade (its
        grade.json, or one worked out from the lighting.json of a Look saved before grades were kept): the grade is
        the Look's colour for every clip of footage, with or without a face, so a lighting or face refusal does not
        decline it, and a placed grade lists any footage clip without it. Also camera when the Look's visual.json
        holds its references' camera language (each shot's move, size and plain share of the frame): with video,
        the export is measured the same way, whatever the receipt says, and the cut's moving share under the
        reference's, a kind of move the reference relies on that the cut mostly lacks, a size mix far from it,
        frames plainer than its, and each stretch held static, at one size or plainer beyond any of the reference's
        are picture findings naming their footage clips (a plain stretch also names its plainest shots, as many as
        would have to become fuller frames to bring it under); without video it is a receipt row. With video, the
        same shots give the pace: a stretch whose shots run slower than any of the reference's stretches before its
        ending, one at its pace or slower more even than any of them, and an ending slower than its are a picture
        finding (device pace) naming the stretch, its shot lengths and clips. With video, sound
        (unless declined) also measures how many seconds the export's sound takes to reach its main level against the
        opening of the Look's measured music (sound.json, when its music is at its main level within 10 s): over 3 s
        later is a finding naming that stretch and how far under it is; sooner, against a reference whose music opens
        quiet (at its main level from 2 s or later), with nobody talking in either opening and the cut's first
        seconds over 6 dB louder against its main level than the reference's, is a finding naming both levels.
        Sources: the chosen Look's recipe.md, visual.json, lighting.json, grade.json, sound.json and sources.json. A Look with none
        of those measured files beside its recipe (a library Look) returns measured false and needs no receipts: its
        recipe is written guidance, and only a placed device's timeline checks apply. source_units lists device units
        only: recipe sections on footage, fit, format, limits or must-nots, a bare title, and a file's own format,
        digest, length and limits are not in it. decisions maps each
        device to status placed|declined and an evidence-based reason. decisions._sources also maps every returned
        source_units key to status, reason and placed items, covering each measured device in that source unit.
        Placed entries name current
        timeline items; broll also maps each item to narration/content relevance in relevance (or feelings: {id:
        {feeling, why}}). captions.contrast accepts caption_readability's measurement; without one for this edit,
        the caption tools' own measurement kept beside the project is read. B-roll also takes share_target (0..1, null if unmeasured);
        timeline_coverage measures the union of its declared relevant item spans. With video, placed entries also need export {sha256, observation}:
        one given with its video keeps a digest of the device's items, and stands for a later render while they are
        unchanged; the camera language, the sound's opening and caption contrast measured on the video stand as theirs.
        Declines need evidence.kind tool_refusal with path, sha256, tool, attempt and device; person_rule with
        quote and conflict matching an explicit prohibition in the brief; unmeasured when the source has no
        measurement for that device; or left_out for a measured device not placed, with because covered_by (and
        by: a device of the same kind, sound or picture, placed with items in the same decisions), unconfirmed (the
        Look marks every measured event of it unconfirmed) or no_moment (an overlay tied to a story moment the new
        story lacks). A Look that measured no cutaways accepts a b-roll decline. receipt_forms lists the forms this
        Look accepts. Weak declines include face protection for b-roll-only flashes or a large difference in light
        between reference and footage. A missing, weak or stale decision and a missing export observation are rows
        of severity receipt (kind receipt): the record of the decisions, not faults in the video. What the timeline
        or the measurements show (cutaway share and rhythm, cut flashes, grade and lighting cover, caption contrast,
        the kit's checks) are major findings of kind picture. passed counts critical and major findings only;
        receipt_complete is true when no receipt row is left.
        shot_sources.sources maps every visible picture item ID (adjustment layers are not pictures) to role
        base|overlay, kind and evidence, as an object or a list of {id, ...};
        inset overlays also carry source_kind. Reference source families constrain base pictures, not caption layers.
        shot_sources.coverage may restate reference-index:overlay-kind as the Look records it (partial|unassessed);
        left out, the Look's own record stands. shot_sources.events maps a source plan overlay key to placed|declined,
        reason and evidence; placed events carry current items and a new-story anchor; sound events name
        audible audio-track items; an event with no decision of its own is covered by its device's decision
        (captions placed, the sound effects decided, stickers decided). Candidates carry status
        unassessed and reason, not an invented placement. stickers accepts unassessed (a decline as unmeasured
        reads the same) when no reviewed event
        exists and coverage is incomplete, or declined with evidence.kind measured_absence for complete empty
        sticker/PIP inventories. Labels and story anchors are caller declarations, not automated provenance proof.
        No decisions reads without changing the receipt.
        The reply carries the Look's files up to 8,000 characters in requirements; a longer one is in
        requirements_in_files with its length and path. source_units gives every key whole and the first 300
        characters of each unit's text. decisions given in the call are not sent back (the receipt file holding them
        is named). full_result names a file holding the whole result, every file's text and every unit's included."""
        import letitedit.looks.look_check as look_check
        return [look_check.short_reply(look_check.check(project, look, decisions, video), project,
                                       given=decisions is not None)]

    @mcp.tool(structured_output=False)
    def letitedit_caption_readability(project: str, video: str | None = None, solid_fallback: bool = False,
                                     dark_edge: bool = False, inverted_then_white: bool = False,
                                     apply: bool = False) -> list:
        """360px caption ink contrast across every native frame, with a 4.5:1 floor. Dedicated kinetic_type
        and word_captions tracks are measured; mixed tracks are unsupported, not passed (burned-in tracks: native,
        below). Translucent frames without opaque ink fail. Timed word envelopes are checked separately;
        overlapping glyphs remain unverified. word_captions clips are drawn again from their stored recipe (layout,
        size, position, pop or bounce scale, box, highlight) as each word's letters and ink; a word counts on a
        frame where the rendered caption layer agrees with that drawing, else it is unmeasured there (not passed);
        its contrast is between its letters and the strongest of what lies up to 2 px outside each point of their
        edge (outline, box, highlight or picture): the ratio 95% of the edge meets, with the lowest point and the
        share under the floor reported.
        Fade-out frames are counted apart. word_captions.findings lists each word under the floor or unmeasured
        with its ratio, worst time and box.
        video measures delivered pixels with timeline masks. dark_edge applies the same thin normal-blend dark
        stroke companion under every Difference fill. solid_fallback changes all fills to white with that same
        edge. Neither treatment uses boxes. Aids have no translucent fades; words remain editable.
        inverted_then_white uses the selected Look's colour policy, or a 3:1 large-text floor without one,
        at 360px across fully-on native frames, excluding entrances, exits and exact two-frame cutaway negatives.
        apply saves that group's chosen colour and a picture-bound freshness receipt
        without changing its fonts, geometry, fades or motion. No boxes, new outlines or within-group switches.
        Delivered checks report actual contrast on those same fully-on frames; white on a light picture can fail.
        Old edge aids and unsupported effects refuse this selection. Other caption kinds refuse fallback.
        Burned-in (native subtitle) tracks get `native`: per cue, the fill's WCAG contrast with the picture in a
        2 px halo just outside its edge at 640 px wide, from captioned and caption-free frames of the export engine
        (video: captioned frames from that file); hard_to_read lists cues with over 30% of that halo under 2.5:1 (close
        to the letters' lightness, so the outline alone separates them); the share under 3:1 is reported.
        Renders of the picture under the captions and of the other measured layers are kept, keyed by what they draw
        and the engine build: a check of the same picture (after a change to the captions, the sound or nothing: the
        export's pre-check, a second check, a delivered-file check) reuses them, and the same measurement of the same
        picture, captions and file comes back with `reused`. A fully-on frame no decoder gives counts in
        unavailable_frames, never measured or passed. Every answer is JSON; a check that could not run has passed
        false, checked false and its reason."""
        return caption_readability(project, video, solid_fallback, dark_edge, inverted_then_white, apply)


    @mcp.tool(structured_output=False)
    def letitedit_check_frames(project: str, times_s: list[float] | None = None, every_s: float | None = None,
                             count: int | None = None, at_cuts: bool = False, width: int = 480,
                             shots: bool = False, per_row: int | None = None, per_page: int = 48,
                             per_shot: int = 3, start_s: float | None = None, end_s: float | None = None,
                             shot_height: int = 340, shots_per_page: int = 15, platform: str | None = None,
                             zone_alpha: float = 0.38, stack: bool = False) -> list:
        """See exactly what the export will show, in seconds: a labelled contact sheet rendered by melt (the export
        engine, not the on-screen preview), captions, overlays, speed changes and zooms included. Code scenes are shown: their finished render when one exists for that revision, else frames drawn now;
        a scene that could not be drawn is named in the result and on its frames' labels. Pick moments with
        times_s, every_s or count (spread evenly, default 12); any number. width: pixels per frame on the sheet (480
        default, up to the project width); per_row: frames per row (default 4, 2 or 1 by width); per_page: frames
        per image (48). Each frame is also saved as a full-size PNG (its path is in the result).
        shots=True (or at_cuts=True): a storyboard instead: every clip on the main picture track (only those in
        start_s-end_s when given) as per_shot frames (3: first, middle, last; 1: middle; more: spread through it),
        labelled with its id, time, source, when it was recorded and the words said in it, shots_per_page clips per
        image. Footage fitted inside a bigger frame (a phone video in a 16:9 project) is shown as its picture area,
        shot_height px tall, sides left out.
        platform (frames, not shots): a platform profile (letitedit_platforms): every frame on the sheet has the areas
        that platform's app covers drawn over it (fill opacity zone_alpha, default 0.38), and the result has those
        areas as fractions of the frame with their source and status; the plain frames are saved as well.
        stack (frames, not shots): each frame in the result also has the layers at that moment as letitedit_timeline_read
        stack_at gives them. Its render holds the PC render lock (one render on the PC at a time; it waits while another runs, and an export lets it in every few minutes)."""
        if shots or at_cuts:
            pages, info = checks.storyboard(project, per_page=max(1, int(shots_per_page)),
                                            tile_h=max(60, int(shot_height)), per_shot=per_shot,
                                            start_s=start_s, end_s=end_s)
            return [Image(data=pg, format='jpeg') for pg in pages] + [compact_reply.check_frames_reply(info)]
        width = max(64, min(int(width), 3840))
        cols = max(1, int(per_row)) if per_row else 4 if width <= 480 else 2 if width <= 960 else 1
        pages, info = checks.frame_pages(project, times_s=times_s, every_s=every_s, count=count, cols=cols,
                                         tile_w=width, per_page=per_page, platform=platform, zone_alpha=zone_alpha)
        if stack:
            checks.add_stack(project, info)
        return [Image(data=pg, format='jpeg') for pg in pages] + [compact_reply.check_frames_reply(info)]

    @mcp.tool(structured_output=False)
    def letitedit_check_range(project: str, start_s: float, duration_s: float = 10.0, width: int = 640,
                            frames: int = 6, joins: bool | None = None) -> list:
        """Render an MP4 of a timeline range (with sound) through the export engine, `width` px wide (up to the
        project's width), and return a filmstrip of `frames` frames spread through it, to check motion: zooms,
        slides, fades, speed-ups. Any length; the clip path is returned for listening. Code scenes in the range move in the clip (drawn at the clip's width when there is no finished render).
        Its render holds the PC render lock (one render on the PC at a time; it waits while another runs, and an export lets it in every few minutes).
        joins=True: also the sound at every join in the range, as letitedit_timing view='joins' measures it on the same
        state of the project: per join its time, the last word before it and the next word after it, a word the join
        falls inside, and its problems (clipped words, clicks, holes, level, room-tone and pitch jumps), with the
        verdict ('clean' or how many joins are flagged) and the file that holds every measure. The sound is the
        project's mix rendered by the export engine (lossless, cached). With it, `edges`: every clip start and end of
        the speech tracks in the range (the first clip's start and the last clip's end included), measured on the
        clip's own source as letitedit_review_bundle's edge check measures them: per edge that goes through sound its
        time, clip, side, kind (inside a word, a word's tail or soft opening, a sound, or sound that runs on between
        two words), the word, how far the sound runs past the edge, and how the review counts it (major or minor);
        edges in a pause are only counted. Default: on while a tool profile is in use (a New video or Studio phase),
        off otherwise."""
        jpeg, info = checks.range_clip(project, start_s, duration_s, width=width, strip=frames)
        import letitedit.server.tool_profiles as tool_profiles
        if joins or (joins is None and tool_profiles.active()):
            import letitedit.server.timing_tools as timing_tools
            state = _measured_state(project)
            info = {**info, 'joins': timing_tools.joins_brief(state, start_s, start_s + duration_s),
                    'edges': _edges_brief(state, start_s, start_s + duration_s)}
            import letitedit.server.next_step_replies as next_step_replies     # T345 C2, behind its own switch
            info = next_step_replies.heard_at_cuts(info)
        return [Image(data=jpeg, format='jpeg'), info]

    @mcp.tool(structured_output=False)
    def letitedit_check_audio(project: str, stems: bool | None = None, target_lufs: float = -14.0,
                            start_s: float | None = None, end_s: float | None = None,
                            every_s: float | None = None, quiet_lu: float | None = 15.0) -> list:
        """Measure the timeline's mix, before the export's loudness finishing (about 3x real time): overall loudness and true peak, near-silent stretches,
        clips far from the typical level, and a loudness graph. stems measures music vs voice (tracks named
        Music* vs the rest): how far the music sits under talking and how loud it is where nobody talks; the default
        (None) does when there is a track named Music*, False skips it (about 3x faster). quiet_lu: stretches of 2 s+
        this far under the mix's typical level (or under -40 LUFS) are listed as quiet; None for -40 LUFS only.
        start_s/end_s: measure only that range. every_s: also the loudness readings (momentary and short-term LUFS)
        at that interval. tones: sustained narrow tones (a pure howl, whine or whistle-like lead; PNPR and PHPR tests with
        a 0.4 s persistence) in the mix and in the music stem, with start, end, pitch, how far each stands above its
        surroundings and above its harmonics, and a finding when one is held 2 s or more (shorter ones are listed, not counted).
        Measurements are not listening; letitedit_check_range renders a range with its sound. Its render holds the PC render lock (one render on the PC at a time; it waits while another runs, and an export lets it in every few minutes)."""
        png, report = measure_audio(project, stems=stems, target_lufs=target_lufs, start_s=start_s, end_s=end_s,
                                    every_s=every_s, quiet_lu=quiet_lu)
        return [Image(data=png, format='png'), report]

    @mcp.tool(structured_output=False)
    def letitedit_qc(project: str, frames: bool = True, audio: bool = False, every_s: float = 2.0,
                   max_frames: int | None = 240, no_talk_s: float = 4.0) -> list:
        """Automatic quality check of a saved timeline: missing media, clips past their source end, V1 gaps, cuts that
        land inside a spoken word (voiced sound of the word on both sides of the cut; both trims given), stretches of
        no_talk_s or more where no one talks, shaky camera,
        whip-pans and blur in the footage of each main-track clip (from the footage analysis, when it has run), filter combinations that render wrongly (Size/Position after a padding filter, Speed/Time
        Remap on long sources), caption
        overflow/sound tags/reading speed, graphics overlapping each other or covering a face (faces found in the picture
        under the graphics), and rendered frames (the middle of every clip and one every every_s seconds, at most
        max_frames; None for no cap) checked for blank (grey/checkerboard), black, very dark, washed-out, blurry or
        squeezed pictures. Returns flagged frames as an image when any are found."""
        jpeg, report = checks.qc(project, frames=frames, audio_pass=audio, every_s=every_s, max_frames=max_frames,
                                 no_talk_s=no_talk_s)
        report = dict(report, findings=[
            f"{f['severity']} {f['at'] or '-'}  " + (f"[{f['track']}: {f['clip']}] " if f.get('clip') else '') + f['problem']
            for f in report['findings']])
        return [Image(data=jpeg, format='jpeg'), report] if jpeg else [report]

    @mcp.tool(structured_output=False)
    def letitedit_export(project: str, output: str | None = None,
                       preset: str = 'high_quality_h264', chunk_seconds: float | None = None, start_s: float | None = None,
                       end_s: float | None = None, name: str | None = None, qc: bool = False,
                       loudness: float | str | None = None, overwrite: bool = False,
                       true_peak: float | str | None = -1.0, platform: str | None = None,
                       video_bitrate_kbps: float | None = None, max_video_bitrate_kbps: float | None = None,
                       audio_bitrate_kbps: float | None = None, sample_rate_hz: int | None = None,
                       preview: bool = False, wait_s: float = 0) -> list:
        """Export a saved timeline to MP4 in the background, crash-proof: rendered in cached chunks (only changed
        chunks re-render), audio rendered once, run detached so closing this session or a PC restart doesn't lose
        finished work (letitedit_export_job action=resume). It takes the PC-wide render lock (Videos\\render.lock) itself
        while it renders, waiting while another render holds it, and removes it when done. The project is
        snapshotted when queued. Default output: the episode's 06 Exports folder, or next to the .mlt. Presets:
        high_quality_h264, social_h264, draft_h264, turbo_h264. The sound is finished at `loudness` LUFS (default: the project's Look's
        export loudness, else -14, the YouTube level) with a true-peak limiter; 'off' keeps the mix as it is.
        chunk_seconds: the size of each cached chunk; left out, a video is cut into as many chunks as the PC renders at once
        (never under 8 s or over 60 s), so a short video no longer renders as one piece.
        true_peak: the highest true peak the encoded sound may reach (dBTP, default -1); when AAC encoding pushes the
        peaks over it, the limiter runs again lower, and a file still over it is kept with a note. 'off' leaves peaks.
        A given output that exists is an error unless overwrite=True (it is replaced when the new render finishes).
        With no output the plain name is always the newest: when the render finishes, an earlier file of that name and
        its review folder move to '<name> (2)', '<name> (3)'... (the result's older_version says where); if it can't
        move, the new render takes that numbered name and the result's output says so.
        A track named 'Song (not in the export)' (letitedit_song) is left out, muted or not; with no output or name the file is called
        '<project> - upload this (no song).mp4', and song_left_out in the job's spec says so.
        qc=True also checks frames of the rendered file for black, blank or squeezed pictures.
        credits (in the reply and the job's status): the credit lines the video owes for library assets it uses
        (letitedit_assets; Google's Noto animated emoji are CC BY 4.0): tell the person and put them in the video's
        description.
        platform: a platform profile (letitedit_platforms id or name). Applied from it unless given here: a video
        bitrate it publishes as a maximum (crf kept, rate capped there), an audio bitrate it publishes as a minimum
        (the preset's or that, whichever is higher) and its sample rate. Its other published values (a recommended
        bitrate, size, frame rate, length limit, loudness) come back under 'platform' with the project's own values
        beside them; the export keeps the project's size and frame rate (letitedit_versions makes other sizes).
        video_bitrate_kbps: a target bitrate instead of the preset's crf (capped at the same rate);
        max_video_bitrate_kbps: the preset's crf with the rate capped there; audio_bitrate_kbps [the preset's: 320,
        192 or 128]; sample_rate_hz [the mix's]. Rate buffer: 2x the cap.
        preview=True: the export engine draws the video smaller (the shorter side 540 px) with a fast encode, and the
        sound exactly as the final (same bitrate, loudness finishing and true-peak limit); named '<project> preview.mp4'
        unless output or name is given, and a new preview replaces the last. Its chunks are cached apart from the
        final's; preset 'preview' or 'preview_h264' is the same as preview=True. letitedit_review_bundle on a preview measures and reviews it as the final; letitedit_review_bundle
        with final_of=<the reviewed preview> checks a final export against it.
        Returns a job_id for letitedit_export_job.
        wait_s (up to 1440; less for an AI with a shorter limit on a tool call): wait that long for the render to
        finish before answering, as letitedit_export_job's wait_s does: a job that finishes, fails or is interrupted
        in that time comes back as letitedit_export_job's status of it (its sheet, picture_change and sound_change
        included), with this call's own fields beside it; one still rendering comes back as its job_id and status.
        0 (the default) answers as soon as the job is queued."""
        import letitedit.server.toolset as toolset
        if 'letitedit_qc' in toolset.without():
            qc = False
        queued = _brief_preexport(rq.submit(project, output=output, preset=preset, chunk_s=chunk_seconds, start_s=start_s,
                         end_s=end_s, name=name, qc=qc, loudness=loudness, overwrite=overwrite, true_peak=true_peak,
                         platform=platform, video_bitrate_kbps=video_bitrate_kbps,
                         max_video_bitrate_kbps=max_video_bitrate_kbps, audio_bitrate_kbps=audio_bitrate_kbps,
                         sample_rate_hz=sample_rate_hz, preview=preview))
        job_id = queued.get('job_id') if isinstance(queued, dict) else None
        if not wait_s or not job_id:
            return [queued]
        out = _job_status(job_id, wait_s)
        last = out[-1]
        if isinstance(last, dict):
            out[-1] = {**last, **{k: v for k, v in queued.items() if k not in last}}
        return out

    @mcp.tool(structured_output=False)
    def letitedit_export_job(job_id: str | None = None, action: str = 'status', wait_s: float = 0,
                           sheet_every_s: float | None = None, picture_change: dict | bool | None = None,
                           sound_change: dict | bool | None = None) -> list:
        """An export job: action 'status' (progress; without job_id, the 20 most recent jobs), 'resume' (restart an
        interrupted or failed export, reusing finished chunks) or 'cancel' (stop after the current chunk).
        wait_s (status, up to 1440; less for an AI with a shorter limit on a tool call): wait that long for the job to finish before answering (it answers as soon as the
        job is done, failed or interrupted). 'interrupted' in a status means the worker stopped. A finished job's
        status comes with a contact sheet of the exported video, a frame every sheet_every_s seconds (default 5;
        0 for no sheet), and `picture_change`: its shots (cuts, punch-ins, dissolves and fades, camera moves not
        counted: count, median and longest), how much the picture changes and where it stays nearly still (a dict
        of settings {every_s: 0.5, still_below: 4.0, min_s: 3.0, cut_above: 'shots'} changes them, a number for
        cut_above = ffmpeg's scene score instead; false leaves it out),
        and `sound_change`: the finished file's loudness every 2 s, its range and true peak, and where it sits 4 LU
        or more above or below its typical level for 3 s or more ({every_s: 2.0, apart_lu: 4.0, min_s: 3.0} changes
        them; false leaves it out)."""
        if action == 'resume':
            return [rq.resume(job_id)]
        if action == 'cancel':
            return [rq.cancel(job_id)]
        if not job_id:
            return [rq.list_jobs()]
        return _job_status(job_id, wait_s, sheet_every_s, picture_change, sound_change)

    def _job_status(job_id, wait_s=0, sheet_every_s=None, picture_change=None, sound_change=None):
        """letitedit_export_job's status reply for one job, after waiting up to wait_s for it to finish."""
        st = rq.status(job_id)
        until = time.monotonic() + max(0.0, min(long_calls.wait_cap(EXPORT_WAIT_MAX_S), float(wait_s or 0)))
        while st.get('state') not in ('done', 'failed', 'error', 'cancelled', 'interrupted') and time.monotonic() < until:
            time.sleep(3)
            st = rq.status(job_id)
        sheet = None if sheet_every_s == 0 else _finished_sheet(st, sheet_every_s)
        if st.get('state') == 'done' and picture_change is not False and st.get('output'):
            try:
                pc = checks.picture_change(st['output'], **(picture_change if isinstance(picture_change, dict) else {}))
                pc.pop('readings', None)
                st = {**st, 'picture_change': pc}
            except Exception as exc:  # noqa: BLE001 - a measurement, never a reason to fail the status
                st = {**st, 'picture_change': f'not measured: {exc}'}
        if st.get('state') == 'done' and sound_change is not False and st.get('output'):
            try:
                st = {**st, 'sound_change': checks.sound_change(
                    st['output'], **(sound_change if isinstance(sound_change, dict) else {}))}
            except Exception as exc:  # noqa: BLE001 - a measurement, never a reason to fail the status
                st = {**st, 'sound_change': f'not measured: {exc}'}
        st = compact_reply.export_job_reply(_brief_preexport(st))
        return [Image(data=sheet, format='jpeg'), st] if sheet else [st]
