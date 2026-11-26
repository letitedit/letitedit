"""MCP tools added by the v2 redesign (toolset.txt 'v2'): import the agent's own edit and export it back, views,
scratch versions, music fitting, sync, tracking, shared markers and bin, sound separation and description, search,
speakers and voice. Each is also a letitedit_ai function. The short descriptions shown to agents are in tool_docs_v2;
these full ones come from letitedit_guide('<tool>')."""
from __future__ import annotations

from pathlib import Path


def _images(Image, paths):
    out = []
    for p in paths or []:
        try:
            data = Path(p).read_bytes()
        except OSError:
            continue
        fmt = 'png' if str(p).lower().endswith('.png') else 'jpeg'
        out.append(Image(data=data, format=fmt))
    return out


def _speakers_brief(res, words=False, spans=False):
    """letitedit_speakers' reply without the long lists: the full result goes to a file (`full`); spans become a count,
    first and last time per file (spans=False), words a count per file (words=False)."""
    import hashlib
    import json
    import os
    from letitedit.core import paths
    out = dict(res)
    try:
        folder = Path(os.environ.get('LETITEDIT_CACHE', str(paths.CODE_ROOT / 'cache'))) / 'speakers'
        folder.mkdir(parents=True, exist_ok=True)
        text = json.dumps(res, indent=1, default=str)
        full = folder / (hashlib.sha1(text.encode('utf-8')).hexdigest()[:16] + '.json')
        full.write_text(text, encoding='utf-8')
        out['full'] = str(full)
    except OSError:
        pass

    def brief_spans(rows):
        per = {}
        for row in rows or []:
            if isinstance(row, (list, tuple)) and len(row) >= 3:
                per.setdefault(str(row[0]), []).append((float(row[1]), float(row[2])))
        return {f: {'spans': len(v), 'first': round(min(a for a, _ in v), 2), 'last': round(max(b for _, b in v), 2)}
                for f, v in per.items()}
    if not spans:
        for key in ('speakers', 'faces'):
            if isinstance(out.get(key), list):
                out[key] = [{**x, 'spans': brief_spans(x.get('spans'))} if isinstance(x, dict) and 'spans' in x else x
                            for x in out[key]]
    if not words and isinstance(out.get('words'), dict):
        out['words'] = {f: f'{len(v)} words (words=True lists them with speakers)' for f, v in out['words'].items()}
    return out


def _bin_reply(res):
    """letitedit_bin's reply; slim (new_video_stages.slim(), with the switch): each marker without its frame numbers
    (its start and end are there), and the markers just added as their ids (they are in `markers` too)."""
    import letitedit.app.new_video_stages as new_video_stages
    if not isinstance(res, dict) or not new_video_stages.slim():
        return res
    out = dict(res)
    if isinstance(out.get('markers'), list):
        out['markers'] = [{k: v for k, v in m.items() if k != 'frames'} if isinstance(m, dict) else m
                          for m in out['markers']]
    if isinstance(out.get('added'), list):
        out['added'] = [a.get('marker') if isinstance(a, dict) and a.get('marker') else a for a in out['added']]
    return out


TRY_JOINS = """
    joins=True: also the sound at every join of each version's span, as letitedit_timing view='joins' measures it on
    that version's scratch project: per join its time, the last word before it and the next word after it, a word
    the join falls inside, and its problems (clipped words, clicks, holes, level, room-tone and pitch jumps), with the
    verdict ('clean' or how many joins are flagged) and the file that holds every measure (each version's `joins`;
    the reply's `joins` has one line per version). The sound is that version's mix rendered by the export engine
    (lossless, cached). Default: on while a tool profile is in use (a New video or Studio phase), off otherwise."""

TRY_FITS = """
    A version's `name` is its label when it has no label. start_s / end_s (timeline seconds): the span the versions
    line up on, as align {'range': [start_s, end_s]} (the two go together); align, when given, wins."""


def _with_joins(info):
    """try's info with each rendered version's joins (timing_tools.joins_brief over its span)."""
    import letitedit.server.timing_tools as timing_tools
    import letitedit.server.next_step_replies as next_step_replies     # T345 C2, behind its own switch
    rows, lines = [], []
    for row in info.get('versions') or []:
        if isinstance(row, dict) and row.get('project') and not row.get('error'):
            span = row.get('span') or [None, None]
            row = next_step_replies.heard_for_version(
                {**row, 'joins': timing_tools.joins_brief(row['project'], span[0], span[1])})
            lines.append(f"{row.get('n')}. {row.get('label')}: {timing_tools.joins_line(row['joins'])}"
                         + next_step_replies.heard_line(row['joins']))
        rows.append(row)
    return {**info, 'versions': rows, 'joins': lines}     # joins: one line per version, kept in a short reply


def register(mcp, Image):
    import letitedit.sound.av_tools as av_tools

    @mcp.tool()
    def letitedit_song(mode: str, project: str | None = None, song: str | None = None, start_s: float | None = None,
                       length_s: float | None = None, upload: str | None = None, platforms: list | str | None = None,
                       song_level_lu: float | None = None, out: str | None = None) -> dict:
        """A song the video is cut to that stays out of every export; the person adds it in the phone app when posting. It sits on
        an audio track named 'Song (not in the export)' as one uncut clip from the timeline's start. Any export (letitedit_export,
        the app's Export) leaves a track of that name out, muted or not, and letitedit_timing(view='sync') and
        letitedit_review_bundle measure the picture against its beats, not its level.
        mode 'parts' (song, length_s?): stretches that start on phrases, drops or sections, with energy and entrance_db (that bar against the one before); tempo, how sure the
        beat finder is (a note when it isn't, or when it couldn't run), the first beat.
        mode 'place' (project, song, start_s [0], length_s [the picture's length]): puts it on the track, replacing an earlier
        one; the beats and downbeats in timeline seconds. Place it again after the picture's length changes.
        mode 'land' (project, length_s = the most a cut may move [half a beat]): moves the main track's cuts to beats by changing each outgoing clip's tail, only inside the
        pause after its last word; punch-ins and overlays within 0.15 s of a beat come onto it (a later edit shifts them); which moved, which stayed and why.
        mode 'check' (project): the track's state, cuts and other picture events within a frame of a beat against chance, words clipped by cuts.
        mode 'finish' (project, upload, platforms?, song_level_lu?, out?): song_in_upload (the file's sound searched for the song,
        with controls saying how quiet a song it could have caught); then, if it isn't there, a preview '<name> - PREVIEW with the song, don't upload.mp4'
        (the picture copied, not rendered; song_level_lu: the song against the file's own loudness [talking -18, nobody
        talking +8]) and the facts for posting: where to start the song, how loud, a moment to check by eye, the furthest off a
        start can be, each platform's control and account limits with its help page."""
        import letitedit.sound.guide_song as guide_song
        if mode == 'parts':
            return guide_song.parts(song, length_s=length_s)
        if mode == 'place':
            return guide_song.place(project, song, start_s or 0.0, length_s=length_s)
        if mode == 'land':
            return guide_song.land(project, max_move_s=length_s)
        if mode == 'check':
            return guide_song.check(project)
        if mode == 'finish':
            return guide_song.finish(project, upload, platforms=platforms, song_level_lu=song_level_lu, out=out)
        raise ValueError(f"mode is parts, place, land, check or finish, not {mode!r}")

    @mcp.tool()
    def letitedit_fit_music(song: str, length: float | None = None, hits: list | None = None, keep: list | None = None,
                          loop: list | None = None, start: float | None = None, fade_out: float | None = None,
                          out: str | None = None, crossfade_s: float | None = None, land: str | None = None,
                          stretch_max: float | None = None, tolerance_s: float | None = None,
                          snap: str | None = None, fade_in: float | None = None, rate: int | None = None) -> dict:
        """A new audio file made from `song`, cut and joined on the song's own beats and bars.
        length: target seconds. hits: [[output_seconds, 'downbeat' | 'beat' | 'section' | 'section:<name>' | 'end' |
        <song seconds>], ...]: musical events to land at those times of the output. keep: song spans [[a, b], ...] to
        use; loop: a song span [a, b] to repeat; start: song time to start from. land: 'cut' (a joint at each hit, the
        incoming side on the event), 'stretch' (whole bars dropped or repeated at a bar line, then the tempo changed by
        at most stretch_max) or 'none' (only report where events fall). crossfade_s at joints, snap of span ends
        ('downbeat' | 'beat' | 'none'), fade_in / fade_out seconds, rate (Hz), out (file path).
        Returns the file and its length, the pieces used, every joint (song time on each side and which beat or
        downbeat each side sits on), where each hit landed and how, the output's downbeats, beats and section starts,
        and every setting used."""
        return av_tools.fit_music(song, length=length, hits=hits, keep=keep, loop=loop, start=start, fade_out=fade_out,
                                  out=out, crossfade_s=crossfade_s, land=land, stretch_max=stretch_max,
                                  tolerance_s=tolerance_s, snap=snap, fade_in=fade_in, rate=rate)

    @mcp.tool(structured_output=False)
    def letitedit_sync(files: list[str], reference: str | None = None, project: str | None = None,
                       synced_clips: str | None = None, devices: dict | None = None, fix_drift: bool = True,
                       sheet: bool = True, settings: dict | None = None) -> list:
        """Line up a whole shoot by its sound: cameras, phones and separate audio recorders, any number of takes each,
        in any order. files: media files and/or folders (read one level deep). Every file is compared with every
        other, each match is checked in windows across the overlap (which also measure clock drift), sharp hits
        (claps, slates) count as extra evidence, and all matches are solved together into one timeline, so a
        recorder split into several files, a take that only overlaps another camera, and a wrong match outvoted by
        the others are all handled. Files that match nothing (another day, no sound) are left out and listed.
        reference: the file the timeline is measured from (default the longest audio-only file, else the longest).
        project: write a letitedit project there: one video track per camera (the most-used one on V1, a device
        that overlaps itself gets a second track), the recorders' sound on audio tracks, cameras muted where a
        recorder covers them. synced_clips: a folder for copies of every camera clip with the recorder's sound in
        place of its own (picture copied untouched, drift corrected in the sound), so every other tool hears the
        good sound. devices: {file name: device name} where the guess from metadata and names is wrong (two phones
        of one model). fix_drift: correct drift with a tiny speed change when it would move a clip end by more than
        a quarter frame. sheet: a picture of the timeline (lanes per device, clips colored by how sure, sharp hits)
        and, when cameras overlap at a sharp hit, their frames there side by side. settings: rate, min_overlap_s,
        sure_z, likely_z, window_s, windows_max, agree_s, place_tol_s, drift_fix_frames, hit_tol_s.
        Returns per file: at (timeline seconds), end, speed, level (reference | sure | likely | assumed), device, the
        evidence (match score, windows that agree and their spread in ms, sharp hits that line up, the links used),
        drift in ppm and ms over the clip; files not placed and why; groups that match each other but not the
        reference; warnings and notes; sharp hits per file; every setting used; and details_file, the full record
        with every check window."""
        import letitedit.sound.shoot_sync as shoot_sync
        paths, folders = [], []
        for f in files:
            (folders if Path(f).is_dir() else paths).append(f)
        res = shoot_sync.sync_shoot(files=paths, folder=folders, reference=reference, project=project,
                                    synced_clips=synced_clips, devices=devices, fix_drift=fix_drift, sheet=sheet,
                                    **(settings or {}))
        for row in res.get('timeline') or []:         # every check window stays in details_file
            (row.get('evidence') or {}).pop('windows', None)
        pics = [res['sheet']] if res.get('sheet') else []
        pics += [res['frames_sheet']] if res.get('frames_sheet') else []
        return _images(Image, pics) + [res]

    @mcp.tool(structured_output=False)
    def letitedit_track(file: str, start: float, end: float, target: list | str, every_s: float | None = None,
                      size: float | None = None, out_dir: str | None = None, analysis_fps: float | None = None,
                      analysis_px: int | None = None, sheet_frames: int | None = None,
                      face_min_score: float | None = None) -> list:
        """Follow something through file[start:end] (seconds) with a visual tracker.
        target: a box [x0, y0, x1, y1] or a point [x, y] (0-1 fractions of the frame, at `start`; a point gets a box
        `size` wide), or 'face' (the largest face at start). every_s: how often to report; analysis_fps, analysis_px:
        how the video is read; sheet_frames: frames on the check sheet.
        Returns rows [t, x0, y0, x1, y1, score] (fractions), the times the target was lost, a sheet with the boxes
        drawn (shown, and saved), a JSON file of every analysed frame, and every setting used."""
        res = av_tools.track(file, start, end, target, every_s=every_s, size=size, out_dir=out_dir,
                             analysis_fps=analysis_fps, analysis_px=analysis_px, sheet_frames=sheet_frames,
                             face_min_score=face_min_score)
        sheet = res.get('sheet') if isinstance(res, dict) else None
        return _images(Image, [sheet] if sheet else []) + [res]

    @mcp.tool()
    def letitedit_bin(project: str, add: list | None = None, markers: list | None = None,
                    remove: list | None = None) -> dict:
        """Picks and notes stored inside a project, where the person sees them in letitedit (its Markers panel and its
        bin), and that they can add to. add: subclips [{file, in, out, name, note, color, folder}]; markers:
        [{at | start, end, text, color}]; remove: names or ids. Without arguments: everything there now, including
        what the person added. Markers go into an open window as one undo step; bin items go into the saved
        file (an open window must have no unsaved changes; it reloads)."""
        import letitedit.review.review_bundle as review_bundle
        import letitedit.server.next_step_replies as next_step_replies      # T345 C2, behind its own switch
        add, markers, fitted = next_step_replies.fit_bin(add, markers)
        res = _bin_reply(av_tools.bin(project, add=add, markers=markers, remove=remove,
                                      refuse=review_bundle.edit_after_handover))
        if fitted and isinstance(res, dict):
            res = {**res, 'fitted': fitted}
        return next_step_replies.bin_reply(res)

    import letitedit.footage.views as views
    import letitedit.server.compact_reply as compact_reply

    def _pages(pages, info):
        return [Image(data=pg, format='png' if pg[:4] == b'\x89PNG' else 'jpeg') for pg in pages] + [info]

    def letitedit_look(items: list, layout: str | None = None, size: int | None = None, per_row: int | None = None,
                     labels: bool | list | None = None, lanes: list | None = None, out_dir: str | None = None,
                     page_w: int | None = None, page_h: int | None = None) -> list:
        pages, info = views.look(items, layout=layout, size=size, per_row=per_row, labels=labels, lanes=lanes,
                                 out_dir=out_dir, page_w=page_w, page_h=page_h)
        return _pages(pages, compact_reply.look_reply(info))
    letitedit_look.__doc__ = views.look.__doc__
    mcp.tool(structured_output=False)(letitedit_look)

    def _try(project, versions, align, size, frames, render, lanes, out_dir, per_row, page_w, page_h, joins):
        pages, info = views.try_changes(project, versions, align=align, size=size, frames=frames, render=render,
                                        lanes=lanes, out_dir=out_dir, per_row=per_row, page_w=page_w, page_h=page_h)
        import letitedit.server.tool_profiles as tool_profiles
        if joins or (joins is None and tool_profiles.active()):
            info = _with_joins(info)
        return _pages(pages, compact_reply.try_reply(info))

    import letitedit.server.next_step_replies as next_step_replies
    if next_step_replies.enabled():     # T345 C2: a version's name is its label; start_s / end_s line versions up
        def letitedit_try(project: str, versions: list, align: dict | None = None, size: int | None = None,
                        frames: int | None = None, render: bool | dict = True, lanes: list | None = None,
                        out_dir: str | None = None, per_row: int | None = None, page_w: int | None = None,
                        page_h: int | None = None, joins: bool | None = None, start_s: float | None = None,
                        end_s: float | None = None) -> list:
            versions, align = next_step_replies.fit_try(versions, start_s, end_s, align)
            return _try(project, versions, align, size, frames, render, lanes, out_dir, per_row, page_w, page_h,
                        joins)
        letitedit_try.__doc__ = views.try_changes.__doc__ + TRY_JOINS + TRY_FITS
    else:
        def letitedit_try(project: str, versions: list, align: dict | None = None, size: int | None = None,
                        frames: int | None = None, render: bool | dict = True, lanes: list | None = None,
                        out_dir: str | None = None, per_row: int | None = None, page_w: int | None = None,
                        page_h: int | None = None, joins: bool | None = None) -> list:
            return _try(project, versions, align, size, frames, render, lanes, out_dir, per_row, page_w, page_h,
                        joins)
        letitedit_try.__doc__ = views.try_changes.__doc__ + TRY_JOINS
    mcp.tool(structured_output=False)(letitedit_try)

    def letitedit_overview(project: str, start: float | None = None, end: float | None = None,
                         scale: float | None = None, lanes: list | None = None, width: int | None = None,
                         out_dir: str | None = None) -> list:
        pages, info = views.overview(project, start=start, end=end, scale=scale, lanes=lanes, width=width,
                                     out_dir=out_dir)
        return _pages(pages, info)
    letitedit_overview.__doc__ = views.overview.__doc__
    mcp.tool(structured_output=False)(letitedit_overview)

    def letitedit_stills(source: str | None = None, times: list[float] | None = None, project: str | None = None,
                       region: list | None = None, size: int | list | None = None, out_dir: str | None = None,
                       format: str = 'png') -> dict:  # noqa: A002 - the parameter's name
        return views.stills(source=source, times=times, project=project, region=region, size=size, out_dir=out_dir,
                            format=format)
    letitedit_stills.__doc__ = views.stills.__doc__
    mcp.tool()(letitedit_stills)

    import letitedit.footage.index_tools as index_tools

    def letitedit_search(query: str | None = None, example: dict | None = None, kind: str | list = 'any',
                       files: str | list[str] | None = None, ranges: dict | list | None = None,
                       count: int | None = None, min_gap_s: float | None = None, every_s: float | dict | None = None,
                       out_dir: str | None = None, window_s: float | None = None, frames: str | None = None,
                       span_level: float | None = None, speech_match: str | None = None,
                       meaning_words: int | None = None, speech_pause_s: float | None = None,
                       frame_height: int | None = None, sheet_per_row: int | None = None,
                       per_kind: int | None = None) -> list:
        res = index_tools.search(query=query, example=example, kind=kind, files=files, ranges=ranges, count=count,
                                 min_gap_s=min_gap_s, every_s=every_s, out_dir=out_dir, window_s=window_s,
                                 frames=frames, span_level=span_level, speech_match=speech_match,
                                 meaning_words=meaning_words, speech_pause_s=speech_pause_s,
                                 frame_height=frame_height, sheet_per_row=sheet_per_row, per_kind=per_kind)
        return _images(Image, [res.get('sheet')] if res.get('sheet') else []) + [res]
    letitedit_search.__doc__ = index_tools.search.__doc__
    mcp.tool(structured_output=False)(letitedit_search)

    def letitedit_speakers(files: str | list[str], count: int | None = None, names: dict | None = None,
                         faces: bool = True, out_dir: str | None = None, method: str | None = None,
                         threshold: float | None = None, segment_s: float | None = None,
                         min_segment_s: float | None = None, pause_s: float | None = None,
                         voice_overlap: float | None = None, match: float | None = None,
                         face_every_s: float | None = None, face_frames: str | None = None,
                         face_long_px: int | None = None, face_min_score: float | None = None,
                         face_min_px: int | None = None, face_threshold: float | None = None,
                         face_count: int | None = None, face_match: float | None = None, samples: int | None = None,
                         sample_words: int | None = None, words: bool = False, spans: bool = False) -> list:
        res = index_tools.speakers(files, count=count, names=names, faces=faces, out_dir=out_dir, method=method,
                                   threshold=threshold, segment_s=segment_s, min_segment_s=min_segment_s,
                                   pause_s=pause_s, voice_overlap=voice_overlap, match=match,
                                   face_every_s=face_every_s, face_frames=face_frames, face_long_px=face_long_px,
                                   face_min_score=face_min_score, face_min_px=face_min_px,
                                   face_threshold=face_threshold, face_count=face_count, face_match=face_match,
                                   samples=samples, sample_words=sample_words)
        if not (words and spans):
            res = _speakers_brief(res, words, spans)
        return _images(Image, [res.get('faces_sheet')] if res.get('faces_sheet') else []) + [res]
    letitedit_speakers.__doc__ = (index_tools.speakers.__doc__ or '') + "\nwords=False (default) gives a count per file " \
        "instead of every word; spans=False (default) gives each speaker's (and face's) spans as a count, first and " \
        "last time per file instead of every span. The full result, every word and span included, is saved as a " \
        "file named in the reply (`full`)."
    mcp.tool(structured_output=False)(letitedit_speakers)

    import letitedit.sound.model_tools as model_tools

    def letitedit_separate(file: str, start: float | None = None, end: float | None = None,
                         parts: list[str] | None = None, out_dir: str | None = None, model: str = 'htdemucs',
                         shifts: int | None = None, overlap: float | None = None,
                         loudness_every_s: float | None = None) -> dict:
        return model_tools.separate(file, start=start, end=end, parts=parts, out_dir=out_dir, model=model,
                                    shifts=shifts, overlap=overlap, loudness_every_s=loudness_every_s)
    letitedit_separate.__doc__ = model_tools.separate.__doc__
    mcp.tool()(letitedit_separate)

    def letitedit_hear(source: str, start: float | None = None, end: float | None = None, every_s: float | None = None,
                     window_s: float | None = None, labels: list[str] | None = None, top: int | str | None = None,
                     spectrogram: bool | dict = False, out_dir: str | None = None, score: str | None = None,
                     template: str | None = None) -> list:
        res = model_tools.hear(source, start=start, end=end, every_s=every_s, window_s=window_s, labels=labels,
                               top=top, spectrogram=spectrogram, out_dir=out_dir, score=score, template=template)
        return _images(Image, [res.get('spectrogram')] if res.get('spectrogram') else []) + [res]
    letitedit_hear.__doc__ = model_tools.hear.__doc__
    mcp.tool(structured_output=False)(letitedit_hear)

    def letitedit_voice(text: str, reference: dict | str | None = None, out: str | None = None,
                      exaggeration: float | None = None, cfg_weight: float | None = None,
                      temperature: float | None = None, seed: int | None = None,
                      repetition_penalty: float | None = None, min_p: float | None = None, top_p: float | None = None,
                      pause_s: float | None = None, split: bool = True, words: bool = True,
                      engine: str | None = None, engine_settings: dict | None = None,
                      reference_text: str | None = None, reference_max_s: float | None = None) -> dict:
        return model_tools.voice(text, reference=reference, out=out, exaggeration=exaggeration, cfg_weight=cfg_weight,
                                 temperature=temperature, seed=seed, repetition_penalty=repetition_penalty,
                                 min_p=min_p, top_p=top_p, pause_s=pause_s, split=split, words=words, engine=engine,
                                 engine_settings=engine_settings, reference_text=reference_text,
                                 reference_max_s=reference_max_s)
    letitedit_voice.__doc__ = model_tools.voice.__doc__
    mcp.tool()(letitedit_voice)

    import letitedit.timeline.edit_import as edit_import

    def letitedit_import(source: str | list | dict, project: str, form: str | None = None, width: int | None = None,
                       height: int | None = None, fps: float | None = None, compare: bool = False,
                       compare_every_s: float | None = None, output: str | None = None,
                       media_dir: str | list[str] | None = None) -> dict:
        return edit_import.import_edit(source, project, form=form, width=width, height=height, fps=fps,
                                       compare=compare, compare_every_s=compare_every_s, output=output,
                                       media_dir=media_dir)
    letitedit_import.__doc__ = edit_import.import_edit.__doc__ + """
What each form becomes: letitedit_guide('import')."""
    mcp.tool()(letitedit_import)

    def letitedit_export_edit(project: str, form: str = 'json', output: str | None = None,
                            video_output: str | None = None) -> dict:
        return edit_import.export_edit(project, form=form, output=output, video_output=video_output)
    letitedit_export_edit.__doc__ = edit_import.export_edit.__doc__
    mcp.tool()(letitedit_export_edit)
