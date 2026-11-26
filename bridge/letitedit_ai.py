"""letitedit from your own Python: the same projects, edits and checks as the letitedit tools, as functions.

    import sys; sys.path.insert(0, r'C:\\LetItEdit\\bridge')
    import letitedit_ai as sa

Projects are letitedit timeline files (.mlt). Everything here works on the saved file, or lands in an open letitedit window
as one undo step, exactly like the tools. Times are seconds.

    sa.new_project(path, width=1920, height=1080, fps=30)       create an empty project (tracks V1, A1)
    sa.read(project)                     the timeline as a dict (tracks, items with ids, at, len, said, effects...)
    sa.apply(project, changes, label=None, code=None)           change it; returns the change list
    sa.set_track(project, track, items, kind='video')           replace everything on a track (gaps too) with `items`
    sa.words(clip=None, start=None, end=None, project=None)     words: [{'w','s','e','p'}] for a file, or on the timeline
                                                                [{'w','t0','t1','id','track'}] for a project
    sa.transcript(folder)                every talking file's words as text lines, one call, each headed '# recorded ...'
                                         and '# frames at each line: <sheet path>': {file: 'start-end  text\n...'}
    sa.find(text, clip, near=None)       a phrase in a file: {'in','out','said'} cut on the gaps around it
    sa.footage(path, every_s=None, frames=None, size=None, times=None, sheet_frames=None)
                                         the footage report text and sheet image paths (frames: how many per video,
                                         every_s, times (one video), size: frame height px; any number)
    sa.storyboard(project, per_shot=3, start=None, end=None, per_page=15, height=340)
                                         per_shot frames of every main-track clip (in start-end) + words: image paths
    sa.frames(project, times)            frames as the export renders them: PNG paths
    sa.qc(project, every_s=2, max_frames=240, no_talk_s=4)      automatic checks: {'errors','warnings','findings'}
    sa.audio(project, stems=None, start=None, end=None, every_s=None, quiet_lu=15)  loudness, peaks, quiet stretches, music vs
                                         voice; every_s: readings at that interval
    sa.export(project, output, wait=True, loudness=-14, sheet_every_s=None)  render an MP4 (waits, then returns
                                         the path and a contact sheet, a frame every sheet_every_s s; 0: none)
    sa.effects(query)                    engine effects matching a search
    sa.fonts(query)                      installed fonts
    sa.library(kind='music'|'sfx', query)   music and sound effects on this PC
    sa.check_range(project, start, duration=10, width=640, frames=6)  a render of a range (with sound): mp4 path
                                         and the path of a filmstrip of `frames` frames
    sa.graphic(recipe, times=None, background=None)  frames of a graphic (same recipes as {graphic: ...}): image path
    sa.undo(project)                     the project back to the copy kept before the last apply
    sa.journal(project, action='read'|'add'|'release', text=None)   the project's journal, edit lease and track owners
    sa.note(path, at=None, text=None, tags=None, remove=None)   footage notes on a source file
    sa.import_edit(source, project)      your own edit (ffmpeg command/script, Python/JSON edit list, EDL, OTIO) as a
                                         project; sa.export_edit(project, form) writes a project back out in those forms
    sa.look(items), sa.try_changes(project, versions), sa.overview(project), sa.stills(source, times)
    sa.fit_music(song, length, hits), sa.sync(files), sa.track(file, start, end, target), sa.bin(project, ...)
    sa.separate(file), sa.hear(source), sa.voice(text, reference), sa.search(query, files=...), sa.speakers(files)
                                         (same parameters as the letitedit_ tools of those names)
    sa.tool('status'|'jobs'|'platforms'|'hardware'|'log_frames'|'log_write'|'measure', ...)
                                         PC status and background jobs, platform profiles, hardware tier, the footage
                                         log written by you, a video's measured style
    sa.tool(name, **params)              any letitedit tool by name with the same parameters (sa.tool('letitedit_fonts',
                                         query=...)); pictures it returns are saved as files and given as paths
    sa.tools()                           every tool name with the first line of its description
    sa.<name>(**params)                  any tool not named above, by its name with or without letitedit_
                                         (sa.timeline_apply(project=..., changes=[...]) is sa.tool('timeline_apply', ...))

`changes` are the same edit ops as letitedit_timeline_apply ({op: insert, track, at, item}, {op: trim, id, words}, ...);
items are the same clip types (clip/in/out or clip/words, {ffmpeg}, {ass}, {graphic: {template: custom, code}},
{color}, ...) and effects ({filter}, {ffmpeg}, keyframes).
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import letitedit.core.windows_trust as _windows_trust  # noqa: E402  (downloads on a clean PC: Windows checks the certificates)
_windows_trust.use()

import os
import sys
import tempfile
import time
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import letitedit.timeline.edit_script as _es  # noqa: E402


def _out_dir(kind):
    d = Path(tempfile.gettempdir()) / 'letitedit_ai' / kind / time.strftime('%Y%m%d-%H%M%S')
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_project(path, width=1920, height=1080, fps=30, like=None):
    import letitedit.server.core_tools as core_tools
    return core_tools.new_project(str(path), like=like, width=width, height=height, fps=fps)


def read(project, start_s=None, end_s=None, tracks=None):
    from letitedit.timeline.timeline_speech import add_said
    return add_said(_es.read(_es._resolve(project), start_s=start_s, end_s=end_s, tracks=tracks))


def apply(project, changes=None, label=None, code=None, check=False, dry_run=False, actor=None, lease_s=None,
          wait_s=None):
    import letitedit.server.timeline_tools as timeline_tools
    result, _ = timeline_tools.apply_project(project, changes, None, check, label, code, dry_run, actor, lease_s,
                                             wait_s)
    return result


def set_track(project, track, items, kind='video', label=None):
    """Replace everything on `track` (created if missing), gaps included, with `items` in order: clips, {'gap': s}
    and items with `at` (they land at that time; other tracks than the main picture track). Items keep their ids,
    so unchanged ones are reused, not re-rendered."""
    import letitedit.server.timeline_tools as timeline_tools
    from letitedit.timeline.edit_sync import layout
    path = _es._resolve(project)
    script = _es.read(path)
    if not any(x['name'] == track for x in script['tracks']):
        apply(project, [{'op': 'add_track', 'name': track, 'kind': kind}], label=f'{_who()}: add {track}')
        script = _es.read(path)
    t = next(x for x in script['tracks'] if x['name'] == track)
    main = t is _main(script)
    if not main and items and all('at' in it for it in items):
        items = sorted(items, key=lambda it: _es.to_seconds(it['at']))
    new, placed = [], []
    fps = (script.get('profile') or {}).get('fps', 30)
    for it in items:
        it = dict(it)
        if it.get('words') and it.get('clip') and 'out' not in it:     # {clip, words}: cut on the gaps around the phrase
            op = {}
            it = _es._place_words(it, op, fps)
            placed.append(op.get('_result'))
        at = it.pop('at', None)
        it.pop('said', None)
        it.pop('recorded', None)
        if at is not None and not main:
            at_s = _es.to_seconds(at)
            end = layout({'items': new + [{'color': '#00000000', 'len': 0}]})[-1][1]     # where the track ends so far
            if at_s < end - 1e-3:
                raise ValueError(f"{it.get('id', 'an item')} at {_es.clock(at_s)} would overlap the item before it on "
                                 f"{track} (it ends at {_es.clock(end)}); pick another time or track")
            if at_s > end + 1e-4:
                new.append({'gap': round(at_s - end, 4)})
            it['at'], it['pin'] = _es.clock(at_s), True
        new.append(it)
    t['items'] = new
    result, _ = timeline_tools.apply_project(project, script_yaml=_es.to_yaml(script), check=False,
                                             label=label or f'{_who()}: set {track}')
    if placed:
        result = dict(result, notes=list(result.get('notes') or []) + [p for p in placed if p])
    return result


def _main(script):
    from letitedit.timeline.edit_sync import main_track
    return main_track(script)


def words(clip=None, start=None, end=None, project=None):
    if project:
        import letitedit.timeline.timeline_speech as timeline_speech
        return timeline_speech.timeline_words(_es.read(_es._resolve(project)), start, end)
    import letitedit.footage.speech as speech
    return [{'w': w['w'], 's': w['s'], 'e': w['e'], 'p': w.get('p', 1.0)} for w in speech.words(str(clip), start, end)]


def transcript(folder, pause=0.6, pictures=True, picture_limits=None):
    """Every file with talking in a folder (or list of files): its words grouped into lines at pauses. Each video's
    text also names its sheet image: a frame of the footage at the start of every line, with its time and words
    (pictures=False names it only when it has been made already)."""
    import letitedit.server.core_tools as core_tools
    import letitedit.sound.music as music
    import letitedit.footage.speech as speech
    files, _, _ = core_tools._collect(folder)
    out = {}
    for f in files:
        try:
            if not music.voice_times(str(f)):
                continue
        except Exception:  # noqa: BLE001 - not audio/video
            continue
        rows, cur, start, last = [], [], None, None
        for w in speech.words(str(f)):
            if cur and w['s'] - last > pause:
                rows.append((start, last, ' '.join(cur)))
                cur, start = [], None
            start = w['s'] if start is None else start
            cur.append(speech.shown(w))
            last = w['e']
        if cur:
            rows.append((start, last, ' '.join(cur)))
        tags = core_tools.picture_tags(f, [(a, b) for a, b, _ in rows], picture_limits)
        lines = [f"{a:7.2f}-{b:7.2f}  {t}" + (f"  [picture: {g}]" if g else '') for (a, b, t), g in zip(rows, tags)]
        info = core_tools.probe(f)
        if info.get('created'):
            lines.insert(0, f"# recorded {core_tools._created(info)}" + (f", {info['camera']}" if info.get('camera') else ''))
        if core_tools._kind(f) == 'video':
            wl = core_tools.word_lines(f, pause=pause)
            try:
                made = pictures or (wl and core_tools._word_section_cache(f, wl).exists())
                sheet = core_tools.word_sheet_file(f, wl) if made else None
            except Exception:  # noqa: BLE001 - the words still stand without the picture sheet
                sheet = None
            if sheet:
                lines.insert(1 if info.get('created') else 0, f'# frames at each line: {sheet}')
        out[str(f)] = '\n'.join(lines)
    return out


def find(text, clip, near=None):
    import letitedit.timeline.cutpoints as cutpoints
    got = cutpoints.find(str(clip), text, near=near)
    return {k: got[k] for k in ('in', 'out', 'said') if k in got}


def footage(path, every_s=None, frames=None, size=None, times=None, sheet_frames=None, picture_limits=None):
    """Text and sheet image paths for footage. frames (how many per video, spread evenly), every_s, times (one video)
    and size (frame height px) choose the frames, any number; without them, the default sheet."""
    import letitedit.server.core_tools as core_tools
    d = _out_dir('footage')
    files, folders, _ = core_tools._collect(path)
    many = bool(folders) or len(files) > 1
    if every_s or frames or size or (times and not many):
        _, report = core_tools.footage(path, sheet=False, times=None if many else times,
                                       every_s=None if many else every_s, sheet_frames=sheet_frames,
                                       picture_limits=picture_limits)
        pages = core_tools.footage_sheets(files, every_s=every_s, count=frames, times=None if many else times,
                                          row_h=size)
    else:
        img, report = core_tools.footage(path, sheet_frames=sheet_frames, picture_limits=picture_limits)
        pages = [img] if img else []
    paths = []
    for i, pg in enumerate(pages, 1):
        p = d / f'sheet_{i}.jpg'
        p.write_bytes(pg)
        paths.append(str(p))
    return {'text': report['text'], 'sheets': paths}


def storyboard(project, per_shot=3, start=None, end=None, per_page=15, height=340):
    import letitedit.review.checks as checks
    pages, info = checks.storyboard(project, per_page=per_page, tile_h=height, per_shot=per_shot, start_s=start,
                                    end_s=end)
    out = {'pages': [str(Path(info['folder']) / f'storyboard_{i}.jpg') for i in range(1, len(pages) + 1)],
           'shots': info['shots']}
    if info.get('tiles'):
        out['tiles'] = info['tiles']
    return out


def frames(project, times):
    import letitedit.review.checks as checks
    _, info = checks.frames(project, times_s=list(times), cols=4, tile_w=480)
    return [f['png'] for f in info['frames']]


def qc(project, every_s=2.0, max_frames=240, no_talk_s=4.0):
    _available('letitedit_qc')
    import letitedit.review.checks as checks
    _, report = checks.qc(project, every_s=every_s, max_frames=max_frames, no_talk_s=no_talk_s)
    return report


def audio(project, stems=None, start=None, end=None, every_s=None, quiet_lu=15.0):
    import letitedit.review.checks as checks
    _, report = checks.audio(project, stems=stems, start_s=start, end_s=end, every_s=every_s, quiet_lu=quiet_lu)
    return report


def picture_change(video, every_s=0.5, still_below=4.0, min_s=3.0, start_s=None, end_s=None, cut_above='shots'):
    """Shots, how much the picture changes over any video file, and where it stays nearly still (see
    checks.picture_change)."""
    import letitedit.review.checks as checks
    return checks.picture_change(video, every_s, still_below, min_s, start_s, end_s, cut_above)


def sound_change(video, every_s=2.0, apart_lu=4.0, min_s=3.0):
    """Loudness of any video or audio file over time and its louder/quieter stretches (see checks.sound_change)."""
    import letitedit.review.checks as checks
    return checks.sound_change(video, every_s, apart_lu, min_s)


def export(project, output, wait=True, loudness=-14.0, overwrite=False, sheet_every_s=None, true_peak=-1.0):
    import letitedit.server.check_tools as check_tools
    import letitedit.timeline.render_queue as rq
    job = rq.submit(str(_es._resolve(project)), output=str(output), loudness=loudness, overwrite=overwrite,
                    true_peak=true_peak)
    if not wait:
        return job
    jid = job.get('job_id') or job.get('id')
    while True:
        st = rq.status(jid)
        if st.get('state') in ('done', 'failed', 'interrupted', 'cancelled', 'error'):
            break
        time.sleep(5)
    sheet = None if sheet_every_s == 0 else check_tools._finished_sheet(st, sheet_every_s)
    if sheet:
        p = _out_dir('export') / 'final_sheet.jpg'
        p.write_bytes(sheet)
        st['sheet'] = str(p)
    return st


def effects(query):
    import letitedit.timeline.effects_catalog as effects_catalog
    return effects_catalog.search(query)


def fonts(query=None):
    import letitedit.catalogs.fonts as _fonts
    return _fonts.search(query)


def library(kind='music', query=None):
    import letitedit.server.core_tools as core_tools
    return core_tools.library(kind, query or '')


def check_range(project, start, duration=10.0, width=640, frames=6):
    import letitedit.review.checks as checks
    jpeg, info = checks.range_clip(project, float(start), float(duration), width=width, strip=frames)
    path = _out_dir('ranges') / f'range-{time.strftime("%H%M%S")}-{float(start):.1f}.jpg'
    path.write_bytes(jpeg)
    return {'clip': info.get('clip'), 'filmstrip': str(path), **{k: v for k, v in info.items() if k != 'clip'}}


def graphic(recipe, times=None, background=None):
    import letitedit.pictures.graphics as graphics
    import letitedit.looks.style_pack as style_pack
    kit = style_pack.load(None)
    img = graphics.preview(recipe, 1920, 1080, 30.0, kit=kit, times=times, background=background or 'checker')
    path = _out_dir('graphics') / f'preview-{time.strftime("%H%M%S")}.jpg'
    path.write_bytes(img)
    return str(path)


def undo(project, actor=None, lease_s=None, wait_s=None):
    import letitedit.timeline.edit_script as es
    return es.undo(es._resolve(project), actor=actor, lease_s=lease_s, wait_s=wait_s)


def journal(project, action='read', text=None, limit=50, actor=None):
    import letitedit.server.journal_tools as journal_tools
    return journal_tools.journal(project, action, text, limit, actor)


def note(path, at=None, text=None, tags=None, remove=None):
    import letitedit.footage.footage_notes as footage_notes
    if remove:
        return {'removed': footage_notes.remove(str(path), remove), 'notes': footage_notes.brief(str(path), limit=200)}
    if text:
        return {'added': footage_notes.add(str(path), at, text, tags=tags), 'notes': footage_notes.brief(str(path), limit=200)}
    return {'notes': footage_notes.brief(str(path), limit=200)}


class _SavedImage:
    """What a tool returns as a picture, saved to a file: .path"""
    def __init__(self, data=None, format='jpeg', path=None):
        if path is not None and data is None:
            self.path = str(path)
            return
        out = _out_dir('tools') / f'image-{time.strftime("%H%M%S")}-{id(self) % 100000}.{format}'
        out.write_bytes(data)
        self.path = str(out)


_REGISTRY = {}


def _who():
    import letitedit.timeline.project_journal as project_journal
    return project_journal.label_prefix()


def _available(tool):
    import letitedit.server.toolset as toolset
    if tool in toolset.without():
        raise RuntimeError(f'{tool} is not part of this setup')


def _registry():
    if _REGISTRY:
        return _REGISTRY

    class _Collect:
        def tool(self, *args, **kwargs):
            def deco(fn):
                from letitedit.server import tool_docs_v2
                fn.__doc__ = tool_docs_v2.with_project_read(fn.__name__, fn.__doc__)
                _REGISTRY[fn.__name__] = fn
                return fn
            return deco
    import letitedit.server.check_tools as check_tools
    import letitedit.server.core_tools as core_tools
    import letitedit.server.kit_tools as kit_tools
    import letitedit.server.timeline_tools as timeline_tools
    import letitedit.server.v2_tools as v2_tools
    import letitedit.server.jobs_tools as jobs_tools
    import letitedit.server.journal_tools as journal_tools
    import letitedit.server.platforms_tools as platforms_tools
    import letitedit.server.hardware_tools as hardware_tools
    import letitedit.server.reference_tools as reference_tools
    import letitedit.server.geo_tools as geo_tools
    import letitedit.server.formats_tools as formats_tools
    import letitedit.server.archive_tools as archive_tools
    import letitedit.server.editor_tools as editor_tools
    import letitedit.server.fix_tools as fix_tools
    import letitedit.server.render3d_tools as render3d_tools
    import letitedit.server.maps_tools as maps_tools
    import letitedit.server.motion_tools as motion_tools
    import letitedit.pictures.code_scenes as code_scenes
    import letitedit.pictures.image_gen as image_gen
    import letitedit.server.music_gen_tools as music_gen_tools
    import letitedit.sound.written_music as written_music
    import letitedit.server.factlog_tools as factlog_tools
    import letitedit.server.review_tools as review_tools
    import letitedit.server.assets_tools as assets_tools
    import letitedit.server.my_assets_tools as my_assets_tools
    import letitedit.server.learned_looks_tools as learned_looks_tools
    import letitedit.server.timing_tools as timing_tools
    import letitedit.server.reframe_tools as reframe_tools
    import letitedit.server.range_search_tools as range_search_tools
    import letitedit.server.caption_layout_tools as caption_layout_tools
    import letitedit.server.soundtrack_tools as soundtrack_tools
    import letitedit.server.annotate_tools as annotate_tools
    import letitedit.server.shot_match_tools as shot_match_tools
    import letitedit.server.takes_tools as takes_tools
    import letitedit.server.command_help as command_help
    import letitedit.server.dub_tools as dub_tools
    import letitedit.sound.media_server as media_server
    import letitedit.server.object_tools as object_tools
    import letitedit.server.fetch_tools as fetch_tools
    import letitedit.server.real_picture_tools as real_picture_tools
    media_server.register(_Collect())      # takes no image class
    object_tools.register(_Collect(), _SavedImage)
    fetch_tools.register(_Collect(), _SavedImage)
    real_picture_tools.register(_Collect(), _SavedImage)
    for mod in (check_tools, timeline_tools, kit_tools, core_tools, v2_tools, jobs_tools, journal_tools,
                platforms_tools, hardware_tools, reference_tools, geo_tools, formats_tools,
                archive_tools, editor_tools, fix_tools, render3d_tools, maps_tools, motion_tools, code_scenes, image_gen, music_gen_tools, written_music,
                factlog_tools, review_tools, takes_tools, shot_match_tools, annotate_tools, soundtrack_tools,
                caption_layout_tools, range_search_tools, reframe_tools, timing_tools,
                assets_tools, my_assets_tools, command_help, dub_tools, learned_looks_tools):
        mod.register(_Collect(), _SavedImage)

    def letitedit_guide(topic=None):
        """One-page reference: every letitedit tool, edit command, clip type, effect form and transition.
        topic: a tool name or a section, as the MCP tool takes it (the same text the MCP server's letitedit_guide
        gives)."""
        import letitedit.server.guide_v2 as guide_v2
        import letitedit.server.toolset as toolset
        docs = {n: (f.__doc__ or '') for n, f in _REGISTRY.items()}
        return guide_v2.text(topic, docs, toolset.without())

    def letitedit_instances():
        """List running custom editors, open projects, unsaved work and AI ownership. Read-only."""
        import letitedit.app.letitedit_instances as _inst
        return _inst.list_instances()
    def letitedit_import_srt(srt=None, path=None, track_name='Subtitles', lang='eng'):
        """Captions from SRT text (or an .srt file) into a caption track of the project open in letitedit: a new track
        named track_name, or overwrite its items; lang is a 3-letter code."""
        from letitedit.app.letitedit_client import ShotcutBridge
        if not srt and not path:
            raise ValueError('Give srt text or a path to an .srt file.')
        params = {'track_name': track_name, 'lang': lang, ('srt' if srt else 'path'): srt or path}
        with ShotcutBridge() as bridge:
            return bridge.call('import_srt', params)
    _REGISTRY['letitedit_guide'] = letitedit_guide
    _REGISTRY['letitedit_instances'] = letitedit_instances
    _REGISTRY['letitedit_import_srt'] = letitedit_import_srt
    import letitedit.server.toolset as toolset
    for name in toolset.without():
        _REGISTRY.pop(name, None)
    return _REGISTRY


def tools():
    return {name: ((fn.__doc__ or '').strip().splitlines() or [''])[0] for name, fn in sorted(_registry().items())}


def _plain(x):
    if isinstance(x, _SavedImage):
        return x.path
    if isinstance(x, list):
        return [_plain(v) for v in x]
    return x


def tool(name, **params):
    """Any letitedit tool by name. A result with one dict (and pictures) comes back as that dict, its pictures' file
    paths under 'images'; anything else as the tool gives it, pictures as file paths."""
    fn = _registry().get(name) or _registry().get('letitedit_' + name)
    if fn is None:
        raise KeyError(f'No tool {name!r}; sa.tools() lists them')
    try:
        import letitedit.app.progress_feed as progress_feed
        progress_feed.record_tool(name, params)
    except Exception:
        progress_feed = None
    try:
        out = fn(**params)
    except Exception:
        if progress_feed:
            try:
                progress_feed.record_tool(name, params, finished=True, success=False)
            except Exception:
                pass
        raise
    if progress_feed:
        try:
            progress_feed.record_tool(name, params, finished=True)
        except Exception:
            pass
    import letitedit.server.compact_reply as compact_reply
    out = compact_reply.expand(out)      # a compact check reply (T295) as the whole result it was made from
    if isinstance(out, list):
        dicts = [x for x in out if isinstance(x, dict)]
        imgs = [x.path for x in out if isinstance(x, _SavedImage)]
        if len(dicts) == 1 and len(dicts) + len(imgs) == len(out):
            return dict(dicts[0], **({'images': imgs} if imgs else {}))
    return _plain(out)


# ---------------------------------------------------------------- v2: your own edit in, views, services
def import_edit(source, project, **params):
    import letitedit.timeline.edit_import as edit_import
    return edit_import.import_edit(source, project, **params)


def export_edit(project, form='json', output=None):
    import letitedit.timeline.edit_import as edit_import
    return edit_import.export_edit(project, form=form, output=output)


def look(items, **params):
    """A comparison sheet: {'sheets': [paths], 'info': ...} (views.look)."""
    import letitedit.footage.views as views
    _, info = views.look(items, **params)
    return info


def try_changes(project, versions, **params):
    import letitedit.footage.views as views
    _, info = views.try_changes(project, versions, **params)
    return info


def overview(project, **params):
    import letitedit.footage.views as views
    _, info = views.overview(project, **params)
    return info


def stills(source=None, times=None, **params):
    import letitedit.footage.views as views
    return views.stills(source=source, times=times, **params)


def fit_music(song, **params):
    import letitedit.sound.av_tools as av_tools
    return av_tools.fit_music(song, **params)


def sync(files, **params):
    """A whole shoot lined up by sound (cameras, phones, recorders, many takes): see shoot_sync.sync_shoot."""
    import letitedit.sound.shoot_sync as shoot_sync
    return shoot_sync.sync_shoot(files=files, **params)


def sync_pair(files, **params):
    """Offsets of files against one reference only (the older, per-pair measure): see av_tools.sync."""
    import letitedit.sound.av_tools as av_tools
    return av_tools.sync(files, **params)


def track(file, start, end, target, **params):
    import letitedit.sound.av_tools as av_tools
    return av_tools.track(file, start, end, target, **params)


def bin(project, add=None, markers=None, remove=None):  # noqa: A001 - the tool's name
    import letitedit.sound.av_tools as av_tools
    return av_tools.bin(project, add=add, markers=markers, remove=remove)


def separate(file, **params):
    import letitedit.sound.model_tools as model_tools
    return model_tools.separate(file, **params)


def hear(source, **params):
    import letitedit.sound.model_tools as model_tools
    return model_tools.hear(source, **params)


def voice(text, reference=None, **params):
    import letitedit.sound.model_tools as model_tools
    return model_tools.voice(text, reference=reference, **params)


def search(query=None, **params):
    import letitedit.footage.index_tools as index_tools
    return index_tools.search(query=query, **params)


def speakers(files, **params):
    import letitedit.footage.index_tools as index_tools
    return index_tools.speakers(files, **params)


def __getattr__(name):
    """sa.<tool name>(**params): any letitedit tool without a function of its own here, called as tool(name, ...)."""
    if name.startswith('_'):
        raise AttributeError(name)
    reg = _registry()
    if name in reg or 'letitedit_' + name in reg:
        import functools
        fn = functools.partial(tool, name)
        fn.__doc__ = (reg.get(name) or reg.get('letitedit_' + name)).__doc__
        return fn
    raise AttributeError(f'letitedit_ai has no {name!r}; sa.tools() lists the tools')
