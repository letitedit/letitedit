"""Edits written in other forms, in and out of Shotcut projects.

    import_edit(source, project, form=None, width=None, height=None, fps=None, compare=False, compare_every_s=None,
                output=None, media_dir=None)                               -> dict
    export_edit(project, form='json', output=None, video_output=None)       -> dict

Forms read: 'ffmpeg' (a command line, or a .bat/.cmd/.ps1/.sh/.py script with ffmpeg calls), 'list' (a JSON or Python
literal list of segments, or a .py file that assigns one), 'edl' (CMX3600), 'otio' (OpenTimelineIO JSON, read as
plain JSON). Forms written: 'json', 'python', 'ffmpeg', 'edl', 'otio'.

The project is written with letitedit_ai.set_track (whole tracks), so the edit-script compiler does the MLT work. A part
of an ffmpeg graph with no Shotcut equivalent becomes a made clip ({ffmpeg: {inputs, video, audio}, len}) carrying
that part of the graph; the result lists each one.

The code is in parts, each imported back here: edit_import_common (forms, file kinds, times, media found and probed,
the project written), edit_import_scripts (scripts read as a shell would), edit_import_lists (edit lists),
edit_import_edl_otio (EDLs and OpenTimelineIO) and edit_import_ffmpeg (ffmpeg command lines and filter graphs).
This file keeps reading the form, import_edit, and the export back (export_edit, with the render-lock wait).
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import ast
import copy
import json
import math
import os
import pprint
import re
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.parse
from fractions import Fraction
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import letitedit.timeline.edit_script as es  # noqa: E402
import letitedit.timeline.made as made  # noqa: E402


# ---- this module's parts: every name in them imported back, so each is the same object as before
# the shared helpers: forms and file kinds, times, media files found and probed, the project written
from letitedit.timeline.edit_import_common import (  # noqa: E402,F401
    FORMS, EXPORT_FORMS, VIDEO_EXT, IMAGE_EXT, AUDIO_EXT, NO_WINDOW, _who, _r, _time, _ext, _kind_of_file,
    _probe_cache, _probe, _tc_cache, _file_timecode, _has_alpha, _image_size, _dir_cache, _listing, _find_media,
    _url_path, _file_url, _db, _ass_escape, _ass_time, _item_tlen, _text_item, item_len, _load, _spread,
    _lane_name, _project_profile, _first_video, _clean_item, _write, _summary
)
# scripts read as a shell would: .bat/.cmd/.ps1/.sh lines and .py files, their variables and calls
from letitedit.timeline.edit_import_scripts import (  # noqa: E402,F401
    _FF_EXE, _SEPS, _style_of, _joined_lines, _uncaret, _expand, _set_var, _tokens, _py_value, _parse_py,
    _py_calls, _echo_lists, _find_calls
)
# edit lists: a JSON or Python list of segments (or tracks of them), or a .py file that assigns one
from letitedit.timeline.edit_import_lists import (  # noqa: E402,F401
    _EDIT_NAMES, _py_literal, _looks_like_segments, KEY_ALIASES, NATIVE_KEYS, _ALIAS, AUDIO_TRACK, TEXT_TRACK,
    MAIN_TRACK, _norm_key, _key_map, _ListReader
)
# CMX3600 EDLs and OpenTimelineIO JSON
from letitedit.timeline.edit_import_edl_otio import (  # noqa: E402,F401
    _EDL_EVENT, _tc_frames, _read_edl, _rt, _schema, _read_otio
)
# ffmpeg command lines: options and filter graphs rebuilt as tracks, the parts with no Shotcut equivalent as made clips
from letitedit.timeline.edit_import_ffmpeg import (  # noqa: E402,F401
    _BOOL_OPTS, _GLOBAL_OPTS, _NULL_OUT, _parse_call, _opt, _has, _split_top, _unquote, _quote_path, _Node,
    AUDIO_FILTERS, NOT_AUDIO, _is_audio_filter, _INREF, _SOURCES, _FILE_ARGS, _absolute_files, _parse_graph,
    _CONSTS, _FUNCS, _calc, _TIMEVAR, _time_dependent, _enable_window, _Fallback, INF, _Inp, _Piece, _made_cut,
    _tlen, _V, _Layer, _Lane, _A, _window_pieces, _vwindow, _awindow, _NAMED_COLORS, _rgba, _hex, _mlt_rgba,
    _ass_colour, _size_opt, _even, _scale_size, _chain_size, _FFMPEG_ASS_HEADER, _ASS_STYLE_FORMAT, _srt_to_ass,
    _force_style, _shift_ass, _font_info, PIXELWISE, NOOP_V, NOOP_A, GEOMETRY, DURATION_CHANGING, TIME_DEPENDENT,
    _FFImport, _layout, _NeedRender, _ff_path
)

RENDER_LOCK = Path(os.environ.get('LETITEDIT_RENDER_LOCK', str(Path.home() / 'Videos' / 'render.lock')))


def _detect(data, path):
    if not isinstance(data, str):
        return 'list'
    ext = path.suffix.lower() if path else ''
    if ext == '.edl':
        return 'edl'
    if ext == '.otio':
        return 'otio'
    if ext in ('.bat', '.cmd', '.ps1', '.sh', '.bash', '.zsh'):
        return 'ffmpeg'
    s = data.lstrip()
    if s.startswith(('{', '[')):
        try:
            d = json.loads(s)
            if isinstance(d, dict) and str(d.get('OTIO_SCHEMA', '')).split('.')[0] in ('Timeline', 'Stack', 'SerializableCollection', 'Track'):
                return 'otio'
            return 'list'
        except ValueError:
            try:
                ast.literal_eval(s)
                return 'list'
            except (ValueError, SyntaxError):
                pass
    if ext == '.py':
        lit = _py_literal(data)
        if lit is not None and _looks_like_segments(lit):
            return 'list'
        if re.search(r'ffmpeg', data, re.I):
            return 'ffmpeg'
        return 'list'
    if _EDL_EVENT.search(data) or re.match(r'\s*TITLE:', data):
        return 'edl'
    if re.search(r'(^|[\s"\'/\\&(\[])ffmpeg(\.exe)?["\']?(\s|,|$)', data, re.I | re.M):
        return 'ffmpeg'
    try:
        ast.literal_eval(s)
        return 'list'
    except (ValueError, SyntaxError):
        pass
    raise ValueError('could not tell what form this edit is in; pass form= one of ' + ', '.join(FORMS))


# ============================================================================ import_edit

def import_edit(source, project, form=None, width=None, height=None, fps=None, compare=False, compare_every_s=None,
                output=None, media_dir=None):
    """Write an editable Shotcut project at `project` from an edit in another form.

    source: inline text, a file path, or (list form) a Python list/dict. form: 'ffmpeg' | 'list' | 'edl' | 'otio'
    (None: from the file's extension and contents). width/height/fps: the project's size and rate (default: from the
    edit, else the first video source). output: with several ffmpeg calls, the output file of the one to read (default
    the last call that writes a file). media_dir: a folder or list of folders where file names are looked up (also
    the source's own folder). compare/compare_every_s: render the source edit and the project and give the mean absolute
    difference (0-255) of frames every compare_every_s seconds (2), sorted largest first.

    Returns {project, form, tracks: {name: items}, items, kept_as_made_clips: [...], notes: [...], compare?}."""
    data, path, base_dir = _load(source)
    project = Path(project).resolve()
    import letitedit.core.long_paths as long_paths
    long_paths.check(*long_paths.project_files(project))
    form = (form or _detect(data, path)).lower()
    if form not in FORMS:
        raise ValueError(f'form is one of {", ".join(FORMS)}')
    media_dir = ([str(Path(d).resolve()) for d in media_dir] if isinstance(media_dir, (list, tuple))
                 else [str(Path(media_dir).resolve())] if media_dir else [])
    notes = []
    ff = None
    if form == 'list':
        model = _ListReader(data, path, base_dir, media_dir, fps, notes).read()
    elif form == 'edl':
        model = _read_edl(data, base_dir, media_dir, fps, notes)
    elif form == 'otio':
        model = _read_otio(data, base_dir, media_dir, notes)
    else:
        ff = _FFImport(data, path, base_dir, output, notes, media_dir)
        model = ff.prepare()
    model.setdefault('like', _first_video(model))
    profile = _project_profile(project, model, width, height, fps)
    if ff is not None:
        model = ff.translate(profile, project)
    _write(project, model)
    counts, script = _summary(project)
    result = {'project': str(Path(project).resolve()), 'form': form, 'tracks': counts, 'items': sum(counts.values()),
              'kept_as_made_clips': list(model.get('made') or []), 'notes': list(dict.fromkeys(model['notes']))}
    if compare:
        result['compare'] = _compare(project, form, model, ff, profile, float(compare_every_s or 2.0), script)
    return result


class _FFBuild:
    """One ffmpeg command (argv) that plays a timeline's tracks."""

    def __init__(self, profile, notes, resource):
        self.W, self.H, self.fps = int(profile['width']), int(profile['height']), float(profile['fps'])
        self.notes = notes
        self.resource = resource
        self.args, self.graph = [], []
        self.k = 0

    def _lab(self, p):
        self.k += 1
        return f'{p}{self.k}'

    def _input(self, args):
        self.args.append(args)
        return len(self.args) - 1

    def _fx(self, it, length, layer):
        """(video filters, audio filters, muted, rect) for an item's effects; _NeedRender for graphs."""
        v, a, rect, muted = [], [], None, False
        name = it.get('id') or os.path.basename(str(it.get('clip', '')))
        for e in it.get('effects') or []:
            if e == 'mute':
                muted = True
                continue
            if not isinstance(e, dict):
                self.notes.append(f'{name}: effect {e!r} is not in the ffmpeg version')
                continue
            if 'ffmpeg' in e:
                spec = e['ffmpeg']
                spec = {'video': spec} if isinstance(spec, str) else dict(spec)
                if spec.get('inputs') or '[' in str(spec.get('video') or '') or '[' in str(spec.get('audio') or ''):
                    raise _NeedRender()
                if spec.get('video'):
                    v.append(str(spec['video']))
                if isinstance(spec.get('audio'), str):
                    a.append(spec['audio'])
                elif spec.get('audio') is False:
                    muted = True
                if spec.get('fit') in ('contain', 'cover'):
                    if spec['fit'] == 'cover':
                        v.append(f'scale={self.W}:{self.H}:force_original_aspect_ratio=increase,crop={self.W}:{self.H}')
                continue
            if 'gain' in e and not isinstance(e['gain'], dict):
                a.append(f"volume={float(e['gain']):g}dB")
            elif 'fade_in' in e:
                v.append(f"fade=t=in:st=0:d={es.to_seconds(e['fade_in']):g}" + (':alpha=1' if e.get('opacity') else ''))
            elif 'fade_out' in e:
                d = es.to_seconds(e['fade_out'])
                v.append(f"fade=t=out:st={max(0.0, length - d):.4f}:d={d:g}" + (':alpha=1' if e.get('opacity') else ''))
            elif 'fade_in_audio' in e:
                a.append(f"afade=t=in:st=0:d={es.to_seconds(e['fade_in_audio']):g}")
            elif 'fade_out_audio' in e:
                d = es.to_seconds(e['fade_out_audio'])
                a.append(f'afade=t=out:st={max(0.0, length - d):.4f}:d={d:g}')
            elif set(e) == {'opacity'} and isinstance(e['opacity'], (int, float)):
                if layer:
                    v.append(f"format=yuva420p,colorchannelmixer=aa={float(e['opacity']):g}")
            elif 'size_position' in e and isinstance(e['size_position'], str):
                vals = [float(x) for x in e['size_position'].split()]
                rect = vals[:4]
                if len(vals) > 4 and layer and vals[4] < 1:
                    v.append(f'format=yuva420p,colorchannelmixer=aa={vals[4]:g}')
            else:
                self.notes.append(f'{name}: {next(iter(e))} is not in the ffmpeg version')
        return v, a, muted, rect

    def _source(self, it, length):
        """(input index, is image, offset, speed applied by us, has audio)."""
        res = None
        if made.is_made(it) or 'graphic' in it:
            res = self.resource(it)
            if res is None:
                raise ValueError(f"{it.get('id', 'an item')}: no rendered file for this made clip")
        if res is not None:
            path, off, sp = res['path'], float(res.get('in', 0)), 1.0
        else:
            path, off, sp = it['clip'], es.to_seconds(it.get('in', 0)), float(it.get('speed', 1.0))
        image = _ext(path) in IMAGE_EXT
        if image:
            k = self._input(['-loop', '1', '-framerate', f'{self.fps:g}', '-t', f'{length:.4f}', '-i', path])
        else:
            k = self._input(['-ss', f'{off:.4f}', '-t', f'{length * sp + 0.05:.4f}', '-i', path])
        info = _probe(path)
        return k, image, sp, bool(info.get('audio')) and not image

    def _item_streams(self, it, length, layer=False, track_fx=False):
        """(video label, audio label or None, rect) for one item, sized for the main picture or as a layer."""
        if 'color' in it:
            rgba = _mlt_rgba(it['color'])
            c = f'0x{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}@{rgba[3]:.3f}' if rgba else 'black'
            vl = self._lab('c')
            fmt = 'yuva420p' if layer else 'yuv420p'
            self.graph.append(f'color=c={c}:s={self.W}x{self.H}:r={self.fps:g}:d={length:.4f},format={fmt},settb=AVTB[{vl}]')
            return vl, None, None
        try:
            vf, af, muted, rect = self._fx(it, length, layer)
            if track_fx:
                raise _NeedRender()
            k, image, sp, has_a = self._source(it, length)
        except _NeedRender:
            res = self.resource(it)
            if res is None:
                raise ValueError(f"{it.get('id', 'a clip')}: its ffmpeg effect is a graph; render the project first")
            plain = {kk: vv for kk, vv in it.items() if kk not in ('effects',)}
            plain['effects'] = [e for e in it.get('effects') or [] if not (isinstance(e, dict) and 'ffmpeg' in e)]
            vf, af, muted, rect = self._fx(plain, length, layer)
            path = res['path']
            image = _ext(path) in IMAGE_EXT
            k = self._input((['-loop', '1', '-framerate', f'{self.fps:g}', '-t', f'{length:.4f}'] if image else
                             ['-ss', f"{float(res.get('in', 0)):.4f}", '-t', f'{length + 0.05:.4f}']) + ['-i', path])
            sp, has_a = 1.0, bool(_probe(path).get('audio')) and not image
        speed = [f'setpts=PTS/{sp:g}'] if abs(sp - 1) > 1e-6 else []
        vl = self._lab('v')
        if layer:
            if rect:
                rx, ry, rw, rh = rect
                place = [f'scale=w={rw:g}:h={rh:g}:force_original_aspect_ratio=decrease:force_divisible_by=2']
            else:
                place = [f'scale=w={self.W}:h={self.H}:force_original_aspect_ratio=decrease:force_divisible_by=2']
            chain = ['setpts=PTS-STARTPTS'] + speed + ['format=yuva420p'] + vf + place + ['format=yuva420p']
        else:
            if rect:
                rx, ry, rw, rh = rect
                place = [f'scale=w={rw:g}:h={rh:g}:force_original_aspect_ratio=decrease',
                         f'pad={self.W}:{self.H}:{rx:g}+({rw:g}-iw)/2:{ry:g}+({rh:g}-ih)/2:color=black']
            else:
                place = [f'scale={self.W}:{self.H}:force_original_aspect_ratio=decrease',
                         f'pad={self.W}:{self.H}:(ow-iw)/2:(oh-ih)/2:color=black']
            chain = (['setpts=PTS-STARTPTS'] + speed + vf + place +
                     [f'setsar=1,fps={self.fps:g},format=yuv420p,tpad=stop_mode=clone:stop_duration=1',
                      f'trim=duration={length:.4f}', 'settb=AVTB'])
        self.graph.append(f'[{k}:v]' + ','.join(chain) + f'[{vl}]')
        al = None
        if has_a and not muted:
            al = self._lab('a')
            tempo = [f'atempo={x:g}' for x in made._atempo(sp)] if abs(sp - 1) > 1e-6 else []
            self.graph.append(f'[{k}:a]' + ','.join(['asetpts=PTS-STARTPTS'] + tempo + af + [
                'aresample=48000', 'aformat=sample_fmts=fltp:channel_layouts=stereo', 'apad',
                f'atrim=duration={length:.4f}']) + f'[{al}]')
        return vl, al, rect

    def _silence(self, length):
        al = self._lab('s')
        self.graph.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={length:.4f}[{al}]')
        return al

    def build(self, tracks, video_output, captions=None, caption_file=None):
        main = next((t for t in tracks if t.get('main')), None) or next((t for t in tracks if t['kind'] == 'video'), None)
        lays = {id(t): _layout(t, t is main) for t in tracks}
        total = max([e for t in tracks for _, _, e in lays[id(t)]] or [0.0])
        if total <= 0:
            raise ValueError('the timeline is empty')
        segs = []
        if main is not None and main.get('hide') not in ('video', 'both'):
            pos = 0.0
            for it, s, e in lays[id(main)]:
                tr = it.get('transition') if segs else None
                tl = es.to_seconds(tr['len'] if isinstance(tr, dict) else tr) if tr else 0.0
                if not tl and s > pos + 1e-3:
                    g = s - pos
                    vl = self._lab('g')
                    self.graph.append(f'color=c=black:s={self.W}x{self.H}:r={self.fps:g}:d={g:.4f},format=yuv420p,'
                                      f'settb=AVTB[{vl}]')
                    segs.append((vl, self._silence(g), g, 0.0, None))
                vl, al, _ = self._item_streams(it, e - s, track_fx=bool([x for x in main.get('effects') or []
                                                                         if made.is_fx(x)]))
                if main.get('hide') == 'audio':
                    al = None
                ttype = tr.get('type', 'dissolve') if isinstance(tr, dict) else 'dissolve'
                if tl and ttype != 'dissolve':
                    self.notes.append(f"{it.get('id', 'a clip')}: the {ttype} transition is drawn as a dissolve")
                segs.append((vl, al or self._silence(e - s), e - s, tl, it))
                pos = e
        # join: concat runs, xfade between runs that start with a transition
        runs = []
        for sg in segs:
            if sg[3] and runs:
                runs.append([sg])
            elif runs:
                runs[-1].append(sg)
            else:
                runs.append([sg])
        joined = []
        for run in runs:
            if len(run) == 1:
                joined.append((run[0][0], run[0][1], run[0][2], run[0][3]))
                continue
            vl, al = self._lab('cv'), self._lab('ca')
            self.graph.append(''.join(f'[{x[0]}][{x[1]}]' for x in run) + f'concat=n={len(run)}:v=1:a=1[{vl}][{al}]')
            joined.append((vl, al, sum(x[2] for x in run), run[0][3]))
        if joined:
            cv, ca, cl = joined[0][0], joined[0][1], joined[0][2]
            for vl2, al2, l2, tl in joined[1:]:
                xv, xa = self._lab('xv'), self._lab('xa')
                self.graph.append(f'[{cv}][{vl2}]xfade=transition=fade:duration={tl:g}:offset={cl - tl:.4f}[{xv}]')
                self.graph.append(f'[{ca}][{al2}]acrossfade=d={tl:g}[{xa}]')
                cv, ca, cl = xv, xa, cl + l2 - tl
        else:
            cv = self._lab('bg')
            self.graph.append(f'color=c=black:s={self.W}x{self.H}:r={self.fps:g}:d={total:.4f},format=yuv420p[{cv}]')
            ca, cl = self._silence(total), total
        if cl < total - 1e-3:
            pv = self._lab('pv')
            self.graph.append(f'[{cv}]tpad=stop_mode=add:stop_duration={total - cl:.4f}:color=black[{pv}]')
            cv = pv
        if main is not None and main.get('gain') is not None and not isinstance(main['gain'], dict):
            gl = self._lab('mg')
            self.graph.append(f"[{ca}]volume={float(main['gain']):g}dB[{gl}]")
            ca = gl
        mix = [ca]
        base = cv
        for t in tracks:
            if t is main:
                continue
            gain = t.get('gain') if not isinstance(t.get('gain'), dict) else None
            if isinstance(t.get('gain'), dict):
                self.notes.append(f"{t['name']}: keyframed track gain is not in the ffmpeg version")
            for it, s, e in lays[id(t)]:
                L = e - s
                if t['kind'] == 'video' and t.get('hide') not in ('video', 'both'):
                    vl, al, rect = self._item_streams(it, L, layer=True,
                                                      track_fx=bool([x for x in t.get('effects') or [] if made.is_fx(x)]))
                    sv = self._lab('o')
                    self.graph.append(f'[{vl}]setpts=PTS+{s:.4f}/TB[{sv}]')
                    if rect:
                        rx, ry, rw, rh = rect
                        xy = f"x='{rx:g}+({rw:g}-w)/2':y='{ry:g}+({rh:g}-h)/2'"
                    else:
                        xy = "x='(W-w)/2':y='(H-h)/2'"
                    nb = self._lab('b')
                    self.graph.append(f"[{base}][{sv}]overlay={xy}:eof_action=pass:enable='between(t,{s:.4f},{e:.4f})'[{nb}]")
                    base = nb
                elif t['kind'] == 'audio' and t.get('hide') not in ('audio', 'both'):
                    it2 = dict(it)
                    _, al, _ = self._audio_only(it2, L)
                    al = al
                else:
                    al = None
                if al and t.get('hide') not in ('audio', 'both'):
                    dl = self._lab('d')
                    vol = f',volume={float(gain):g}dB' if gain is not None else ''
                    self.graph.append(f'[{al}]adelay={int(round(s * 1000))}:all=1{vol}[{dl}]')
                    mix.append(dl)
            if [x for x in t.get('effects') or [] if not made.is_fx(x)]:
                self.notes.append(f"{t['name']}: track effects are not in the ffmpeg version")
        if caption_file:
            nb = self._lab('cap')
            self.graph.append(f"[{base}]subtitles={_quote_path(caption_file)}[{nb}]")
            base = nb
        aout = self._lab('aout')
        if len(mix) > 1:
            self.graph.append(''.join(f'[{m}]' for m in mix) + f'amix=inputs={len(mix)}:duration=longest:'
                              f'dropout_transition=0:normalize=0,apad,atrim=duration={total:.4f}[{aout}]')
        else:
            self.graph.append(f'[{mix[0]}]apad,atrim=duration={total:.4f}[{aout}]')
        vout = self._lab('vout')
        self.graph.append(f'[{base}]trim=duration={total:.4f},format=yuv420p[{vout}]')
        argv = [str(made.ffmpeg_exe()), '-y', '-hide_banner']
        for a in self.args:
            argv += a
        argv += ['-filter_complex', ';'.join(self.graph), '-map', f'[{vout}]', '-map', f'[{aout}]',
                 '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', f'{self.fps:g}',
                 '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-t', f'{total:.4f}', str(video_output)]
        return argv, total

    def _audio_only(self, it, length):
        """A sound item's audio label (any track kind)."""
        if 'color' in it:
            return None, None, None
        try:
            _, af, muted, _ = self._fx(it, length, False)
            k, image, sp, has_a = self._source(it, length)
        except _NeedRender:
            res = self.resource(it)
            if res is None:
                raise ValueError(f"{it.get('id', 'a clip')}: its ffmpeg effect is a graph; render the project first")
            plain = dict(it, effects=[e for e in it.get('effects') or [] if not (isinstance(e, dict) and 'ffmpeg' in e)])
            _, af, muted, _ = self._fx(plain, length, False)
            k = self._input(['-ss', f"{float(res.get('in', 0)):.4f}", '-t', f'{length + 0.05:.4f}', '-i', res['path']])
            sp, has_a = 1.0, bool(_probe(res['path']).get('audio'))
        if not has_a or muted:
            return None, None, None
        al = self._lab('a')
        tempo = [f'atempo={x:g}' for x in made._atempo(sp)] if abs(sp - 1) > 1e-6 else []
        self.graph.append(f'[{k}:a]' + ','.join(['asetpts=PTS-STARTPTS'] + tempo + af + [
            'aresample=48000', 'aformat=sample_fmts=fltp:channel_layouts=stereo', 'apad',
            f'atrim=duration={length:.4f}']) + f'[{al}]')
        return None, al, None


def _script_text(argv, flavor):
    exe, rest = argv[0], argv[1:]
    groups, cur, i = [], [], 0
    while i < len(rest):
        a = rest[i]
        if a == '-filter_complex' and i + 1 < len(rest):
            if cur:
                groups.append(cur)
            groups.append([a, rest[i + 1]])
            cur, i = [], i + 2
            continue
        cur.append(a)
        if a == '-i' and i + 1 < len(rest):
            cur.append(rest[i + 1])
            groups.append(cur)
            cur, i = [], i + 2
            continue
        i += 1
    if cur:
        groups.append(cur)
    if flavor == 'bat':
        def q(s):
            s = str(s).replace('%', '%%')
            return f'"{s}"' if re.search(r'[\s&|<>^,;=()\'"]', s) or s == '' else s
        lines = ['@echo off', f'"{exe}" ' + ' ^\n  '.join(' '.join(q(x) for x in g) for g in groups)]
        return '\n'.join(lines) + '\n'
    if flavor == 'ps1':
        def q(s):
            s = str(s)
            return "'" + s.replace("'", "''") + "'" if re.search(r'[\s&|<>`$@,;(){}\'"#]', s) or s == '' else s
        return f"& '{exe}' " + ' `\n  '.join(' '.join(q(x) for x in g) for g in groups) + '\n'
    return '#!/bin/sh\n' + shlex.quote(_ff_path(exe)) + ' ' + ' \\\n  '.join(
        ' '.join(shlex.quote(_ff_path(x) if os.sep == '\\' and re.match(r'^[A-Za-z]:\\', str(x)) else str(x)) for x in g)
        for g in groups) + '\n'


# ============================================================================ compare

COMPARE_LOCK_WAIT_S = 12 * 3600  # how long a compare waits for someone else's render before giving up


def _wait_for_render_lock(timeout_s=None, poll_s=30.0):
    """Wait until the PC render lock is free or stale, or held by a process above this one (a run under
    render_lock.py run: its renders are this one's); raises render_lock.LockTimeout after timeout_s
    (default COMPARE_LOCK_WAIT_S)."""
    import letitedit.core.render_lock as rl
    limit = COMPARE_LOCK_WAIT_S if timeout_s is None else float(timeout_s)
    t0 = time.monotonic()
    above = None
    while True:
        try:
            i = rl.info(RENDER_LOCK)
        except Exception:  # noqa: BLE001
            return
        if not i.get('held') or i.get('stale'):
            return
        if above is None:
            above = rl.ancestors()[1:]
        if rl.lock_held_by(i.get('text'), above):
            return
        waited = time.monotonic() - t0
        if waited >= limit:
            raise rl.LockTimeout(f'Gave up after {waited:.0f} s (timeout_s={limit:g}) waiting for the render lock. '
                                 + i.get('message', ''))
        time.sleep(max(0.05, min(poll_s, limit - waited)))


def _grab(path, t, w, h):
    import numpy as np
    r = subprocess.run([str(made.ffmpeg_exe()), '-v', 'error', '-ss', f'{t:.3f}', '-i', str(path), '-frames:v', '1',
                        '-vf', f'scale={w}:{h}:flags=area,format=rgb24', '-f', 'rawvideo', '-'],
                       capture_output=True, creationflags=NO_WINDOW, timeout=120)
    if len(r.stdout) < w * h * 3:
        return None
    return np.frombuffer(r.stdout[:w * h * 3], np.uint8).reshape(h, w, 3).astype(np.int16)


def _compare(project, form, model, ff, profile, every, script):
    from concurrent.futures import ThreadPoolExecutor
    import letitedit.review.checks as checks
    work = Path(tempfile.mkdtemp(prefix='edit_import_compare_'))
    ref = work / 'reference.mp4'
    notes = []
    try:
        _wait_for_render_lock()
    except TimeoutError as e:
        return {'error': str(e)}
    total = es.to_seconds(script['length'])
    cap = total + max(2.0, every)
    if form == 'ffmpeg':
        argv = ff.reference_argv(ref, cap=cap)
        what = f'the ffmpeg command as written (its output cut at {cap:g} s)'
        cwd = str(ff.base_dir)
    else:
        made_dir = Path(project).parent / 'made'
        W, H, F = int(profile['width']), int(profile['height']), float(profile['fps'])

        def resource(it):
            if made.is_made(it):
                r = made.render(made.recipe_of(it), W, H, F, out_dir=made_dir)
                return {'path': r['path'], 'in': float(it.get('skip', 0))}
            return None
        argv, _ = _FFBuild(profile, notes, resource).build(model['tracks'], ref)
        what = 'an ffmpeg render of the edit as read (before it went into the project)'
        cwd = None
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=cwd,
                           creationflags=NO_WINDOW, timeout=max(300.0, 30 * cap), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {'error': 'the reference render did not finish', 'reference_command': argv}
    if r.returncode != 0 or not ref.exists():
        return {'error': 'the reference render failed: ' + r.stderr.strip()[-800:], 'reference_command': argv}
    width = min(640, int(profile['width'])) // 2 * 2
    _, info = checks.range_clip(project, 0.0, total, width=width, strip=1)
    proj = info['clip']
    d_ref = _probe_fresh(ref)
    d_proj = _probe_fresh(proj)
    w = 160
    h = max(2, int(round(w * int(profile['height']) / int(profile['width']) / 2)) * 2)
    times = []
    t = every / 2
    while t < min(d_ref, d_proj) - 1e-3:
        times.append(round(t, 3))
        t += every

    def one(tt):
        a, b = _grab(ref, tt, w, h), _grab(proj, tt, w, h)
        if a is None or b is None:
            return {'time': tt, 'difference': None}
        return {'time': tt, 'difference': round(float(abs(a - b).mean()), 2)}
    with ThreadPoolExecutor(max_workers=6) as pool:
        frames = list(pool.map(one, times))
    frames.sort(key=lambda f: -1 if f['difference'] is None else -f['difference'])
    out = {'reference': str(ref), 'reference_is': what, 'project_render': str(proj), 'reference_s': round(d_ref, 3),
           'project_s': round(d_proj, 3), 'every_s': every, 'frame_size': [w, h],
           'difference_is': 'mean absolute difference of RGB values (0-255) per frame', 'frames': frames}
    if notes:
        out['notes'] = notes
    return out


def _probe_fresh(path):
    r = subprocess.run([str(es.FFPROBE), '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ============================================================================ export_edit

def _resources(path):
    """{item id: {'path', 'in'}}: the file each item plays (rendered made clips, graphics, ffmpeg-effect renders)."""
    doc = es.Doc(path)
    ids = es._ids_for(doc)
    out = {}
    for tr, pl, name, kind in doc.tracks():
        for r in es._track_records(doc, pl, name, ids):
            if r['kind'] != 'entry' or r['prod'].tag == 'tractor':
                continue
            p = es._props(r['prod'])
            res = p.get('warp_resource') or p.get('resource')
            if res and not os.path.isabs(res):
                for cand in (Path(path).parent / res, Path.cwd() / res):
                    if cand.exists():
                        res = str(cand.resolve())
                        break
            out[r['id']] = {'path': res, 'in': (doc.f(r['entry'].get('in')) or 0) / doc.fps}
    return out


def _clean_script(script):
    data = {'format': script.get('format'), 'project': script.get('project'), 'profile': script.get('profile'),
            'length': _r(es.to_seconds(script.get('length', 0)))}
    tracks = []
    for t in script['tracks']:
        tt = {k: copy.deepcopy(v) for k, v in t.items() if k != 'items'}
        items = []
        for it in t['items']:
            it = {k: copy.deepcopy(v) for k, v in it.items() if k not in ('said', 'recorded', 'pin', 'from')}
            if 'at' in it:
                it['at'] = _r(es.to_seconds(it['at']))
            items.append(it)
        tt['items'] = items
        tracks.append(tt)
    data['tracks'] = tracks
    if script.get('captions'):
        caps = copy.deepcopy(script['captions'])
        for c in caps:
            for q in c.get('cues', []):
                q['start'], q['end'] = _r(es.to_seconds(q['start'])), _r(es.to_seconds(q['end']))
        data['captions'] = caps
    for k in ('master', 'style'):
        if script.get(k):
            data[k] = copy.deepcopy(script[k])
    return data


def _edl_text(script, res, notes, title):
    fps = float(script['profile']['fps'])
    base = int(round(fps))
    hour = 3600 * base

    def tc(frames):
        frames = int(max(0, frames))
        return f'{frames // (3600 * base):02d}:{frames // (60 * base) % 60:02d}:{frames // base % 60:02d}:{frames % base:02d}'

    def fr(sec):
        return int(round(sec * fps))
    tracks = script['tracks']
    main = next((t for t in tracks if t['kind'] == 'video'), None)
    lines = [f'TITLE: {title}', 'FCM: NON-DROP FRAME', f'* FPS: {fps:g}', '']
    events = []
    if main is not None:
        lay = _layout(main, True)
        for k, (it, s, e) in enumerate(lay):
            ev = {'it': it, 's': s, 'e': e}
            if 'clip' in it and not made.is_made(it):
                ev['path'] = it['clip']
                ev['src_in'] = es.to_seconds(it.get('in', 0))
                ev['speed'] = float(it.get('speed', 1.0))
            elif 'color' in it:
                ev['path'] = None
                ev['src_in'] = 0.0
                ev['speed'] = 1.0
            else:
                r = res.get(it.get('id')) or {}
                ev['path'] = r.get('path')
                ev['src_in'] = float(r.get('in', 0))
                ev['speed'] = 1.0
                notes.append(f"{it.get('id')}: a made clip; the EDL names its rendered file")
            tr = it.get('transition') if k else None
            ev['trans'] = es.to_seconds(tr['len'] if isinstance(tr, dict) else tr) if tr else 0.0
            ev['sound'] = bool(ev['path']) and _probe(ev['path']).get('audio') and 'mute' not in (it.get('effects') or [])
            events.append(ev)
        for k, ev in enumerate(events):
            ev['rec_out'] = ev['e']
            ev['src_len'] = (ev['e'] - ev['s'])
            nxt = events[k + 1] if k + 1 < len(events) else None
            if nxt is not None and nxt['trans']:
                ev['rec_out'] = ev['e'] - nxt['trans']
            for e in ev['it'].get('effects') or []:
                if not (e == 'mute' or (isinstance(e, dict) and set(e) <= {'gain'})):
                    notes.append(f"{ev['it'].get('id')}: effects are not in the EDL")
                    break
    n = 0
    for k, ev in enumerate(events):
        it = ev['it']
        reel = 'BL' if ev['path'] is None else 'AX'
        trk = 'AA/V' if ev['sound'] else 'V'
        tco = _file_timecode(ev['path'], fps) if ev['path'] else 0.0
        src_a = ev['src_in'] + tco
        if ev['trans'] and k:
            prev = events[k - 1]
            pa = prev['src_in'] + (prev['rec_out'] - prev['s']) * prev['speed'] + (_file_timecode(prev['path'], fps) if prev['path'] else 0)
            n += 1
            lines.append(f"{n:03d}  {'BL' if prev['path'] is None else 'AX':<8} {trk:<5} C        "
                         f"{tc(fr(pa))} {tc(fr(pa))} {tc(hour + fr(ev['s']))} {tc(hour + fr(ev['s']))}")
            if prev['path']:
                lines.append(f"* FROM CLIP NAME: {os.path.basename(prev['path'])}")
            lines.append(f"{n:03d}  {reel:<8} {trk:<5} D    {fr(ev['trans']):03d} "
                         f"{tc(fr(src_a))} {tc(fr(src_a + (ev['rec_out'] - ev['s']) * ev['speed']))} "
                         f"{tc(hour + fr(ev['s']))} {tc(hour + fr(ev['rec_out']))}")
            if ev['path']:
                lines.append(f"* TO CLIP NAME: {os.path.basename(ev['path'])}")
        else:
            n += 1
            lines.append(f"{n:03d}  {reel:<8} {trk:<5} C        "
                         f"{tc(fr(src_a))} {tc(fr(src_a + (ev['rec_out'] - ev['s']) * ev['speed']))} "
                         f"{tc(hour + fr(ev['s']))} {tc(hour + fr(ev['rec_out']))}")
            if ev['path']:
                lines.append(f"* FROM CLIP NAME: {os.path.basename(ev['path'])}")
        if ev['path']:
            lines.append(f"* SOURCE FILE: {ev['path']}")
        if abs(ev['speed'] - 1) > 1e-6:
            lines.append(f"M2   AX       {fps * ev['speed']:05.1f}                {tc(fr(src_a))}")
    audio = [t for t in tracks if t['kind'] == 'audio']
    for ai, t in enumerate(audio):
        ch = 'A' if ai == 0 else f'A{ai + 1}'
        if ai >= 4:
            notes.append(f"{t['name']}: CMX3600 has four sound channels; this track is written as {ch}")
        for it, s, e in _layout(t, False):
            if 'clip' not in it or made.is_made(it):
                r = res.get(it.get('id')) or {}
                path, a0 = r.get('path'), float(r.get('in', 0))
            else:
                path, a0 = it['clip'], es.to_seconds(it.get('in', 0))
            if not path:
                continue
            sp = float(it.get('speed', 1.0))
            src_a = a0 + _file_timecode(path, fps)
            n += 1
            lines.append(f"{n:03d}  AX       {ch:<5} C        {tc(fr(src_a))} {tc(fr(src_a + (e - s) * sp))} "
                         f"{tc(hour + fr(s))} {tc(hour + fr(e))}")
            lines.append(f'* FROM CLIP NAME: {os.path.basename(path)}')
            lines.append(f'* SOURCE FILE: {path}')
    others = [t['name'] for t in tracks if t['kind'] == 'video' and t is not main and any('gap' not in i for i in t['items'])]
    if others:
        notes.append('CMX3600 has one picture track; not in the EDL: ' + ', '.join(others))
    if script.get('captions'):
        notes.append('captions are not in the EDL')
    return '\n'.join(lines) + '\n'


def _otio_rt(sec, rate):
    return {'OTIO_SCHEMA': 'RationalTime.1', 'rate': rate, 'value': round(sec * rate, 6)}


def _otio_range(start, dur, rate):
    return {'OTIO_SCHEMA': 'TimeRange.1', 'start_time': _otio_rt(start, rate), 'duration': _otio_rt(dur, rate)}


def _otio_doc(script, res, notes, title):
    rate = float(script['profile']['fps'])
    main = next((t for t in script['tracks'] if t['kind'] == 'video'), None)
    children = []
    for t in script['tracks']:
        kids = []
        lay = _layout(t, t is main)
        pos = 0.0
        clips = []
        for k, (it, s, e) in enumerate(lay):
            if s > pos + 1e-4 and not (t is main and it.get('transition') and k):
                kids.append({'OTIO_SCHEMA': 'Gap.1', 'name': '', 'source_range': _otio_range(0, s - pos, rate),
                             'effects': [], 'markers': [], 'metadata': {}, 'enabled': True})
            meta = {'id': it.get('id')}
            if it.get('effects'):
                meta['effects'] = copy.deepcopy(it['effects'])
            effects = []
            if 'clip' in it and not made.is_made(it):
                ref = {'OTIO_SCHEMA': 'ExternalReference.1', 'name': os.path.basename(it['clip']), 'available_range': None,
                       'target_url': _file_url(it['clip']), 'metadata': {}}
                start = es.to_seconds(it.get('in', 0))
                sp = float(it.get('speed', 1.0))
                if abs(sp - 1) > 1e-6:
                    effects.append({'OTIO_SCHEMA': 'LinearTimeWarp.1', 'name': '', 'effect_name': 'LinearTimeWarp',
                                    'time_scalar': sp, 'metadata': {}})
            elif 'color' in it:
                ref = {'OTIO_SCHEMA': 'GeneratorReference.1', 'name': 'color', 'generator_kind': 'SolidColor',
                       'parameters': {'color': it['color']}, 'available_range': None, 'metadata': {}}
                start = 0.0
            else:
                r = res.get(it.get('id')) or {}
                ref = {'OTIO_SCHEMA': 'ExternalReference.1', 'name': os.path.basename(str(r.get('path', ''))),
                       'available_range': None, 'target_url': _file_url(r['path']) if r.get('path') else '', 'metadata': {}}
                start = float(r.get('in', 0))
                meta['item'] = {k: copy.deepcopy(v) for k, v in it.items() if k not in ('said', 'recorded', 'at', 'pin')}
            clip = {'OTIO_SCHEMA': 'Clip.2', 'name': it.get('name') or ref.get('name') or it.get('id', ''),
                    'source_range': _otio_range(start, e - s, rate), 'effects': effects, 'markers': [],
                    'enabled': True, 'metadata': {'letitedit_ai': meta},
                    'media_references': {'DEFAULT_MEDIA': ref}, 'active_media_reference_key': 'DEFAULT_MEDIA'}
            tr = it.get('transition') if (t is main and k) else None
            if tr and clips:
                L = es.to_seconds(tr['len'] if isinstance(tr, dict) else tr)
                prev = clips[-1]
                pr = prev['source_range']
                pr['duration']['value'] = round(pr['duration']['value'] - L / 2 * rate, 6)
                cr = clip['source_range']
                cr['start_time']['value'] = round(cr['start_time']['value'] + L / 2 * rate * float(it.get('speed', 1.0)), 6)
                cr['duration']['value'] = round(cr['duration']['value'] - L / 2 * rate, 6)
                kids.append({'OTIO_SCHEMA': 'Transition.1', 'name': '', 'transition_type': 'SMPTE_Dissolve',
                             'in_offset': _otio_rt(L / 2, rate), 'out_offset': _otio_rt(L / 2, rate), 'metadata': {}})
                if isinstance(tr, dict) and tr.get('type', 'dissolve') != 'dissolve':
                    notes.append(f"{it.get('id')}: the {tr['type']} transition is written as a dissolve")
            kids.append(clip)
            clips.append(clip)
            pos = e
        children.append({'OTIO_SCHEMA': 'Track.1', 'name': t['name'], 'kind': 'Audio' if t['kind'] == 'audio' else 'Video',
                         'children': kids, 'source_range': None, 'effects': [], 'markers': [], 'enabled': True,
                         'metadata': {'letitedit_ai': {k: v for k, v in t.items() if k in ('gain', 'duck', 'effects', 'hide')}}})
    if script.get('captions'):
        notes.append('captions are kept in the timeline metadata only')
    return {'OTIO_SCHEMA': 'Timeline.1', 'name': title, 'global_start_time': None,
            'metadata': {'letitedit_ai': {'profile': script['profile'], 'captions': script.get('captions'),
                                        'master': script.get('master')}},
            'tracks': {'OTIO_SCHEMA': 'Stack.1', 'name': 'tracks', 'children': children, 'source_range': None,
                       'effects': [], 'markers': [], 'enabled': True, 'metadata': {}}}


def export_edit(project, form='json', output=None, video_output=None):
    """The project's timeline (as saved, hand edits included) written in another form.

    form: 'json' | 'python' | 'ffmpeg' | 'edl' | 'otio'. output: a file to write the text to (for 'ffmpeg' its
    extension picks .bat/.cmd, .ps1 or .sh; otherwise a .bat on Windows). video_output: the file the ffmpeg command
    writes (default <project>.ffmpeg.mp4 next to the project).

    Returns {form, text, file (when output given), notes} (+ argv and video_output for 'ffmpeg')."""
    form = form.lower()
    if form not in EXPORT_FORMS:
        raise ValueError(f'form is one of {", ".join(EXPORT_FORMS)}')
    path = es._resolve(project)
    script = es.read(path)
    notes = []
    title = path.stem
    out = {'form': form}
    if form in ('json', 'python'):
        data = _clean_script(script)
        text = (json.dumps(data, indent=2, ensure_ascii=False) + '\n' if form == 'json' else
                '# letitedit edit: ' + title + '\nEDIT = ' + pprint.pformat(data, width=110, sort_dicts=False) + '\n')
    elif form == 'edl':
        text = _edl_text(script, _resources(path), notes, title)
    elif form == 'otio':
        text = json.dumps(_otio_doc(script, _resources(path), notes, title), indent=2) + '\n'
    else:
        res = _resources(path)
        video_output = Path(video_output) if video_output else path.with_name(path.stem + '.ffmpeg.mp4')
        flavor = 'bat' if os.name == 'nt' else 'sh'
        if output:
            ext = Path(output).suffix.lower()
            flavor = {'.bat': 'bat', '.cmd': 'bat', '.ps1': 'ps1', '.sh': 'sh'}.get(ext, flavor)
        cap_file = None
        caps = [c for c in script.get('captions') or [] if c.get('burn_in', True) and c.get('cues')]
        if caps:
            if output:
                cap_file = Path(output).with_suffix('.captions.srt')
                cap_file.write_text(es._srt(caps[0]['cues']), encoding='utf-8')
                notes.append(f'captions burned from {cap_file.name} with ffmpeg\'s default subtitle style, not the '
                             'project\'s caption style')
            else:
                notes.append('captions left out (pass output= to write them as an .srt next to the script)')
        tracks = [dict(t, main=(i == next(k for k, x in enumerate(script['tracks']) if x['kind'] == 'video')))
                  for i, t in enumerate(script['tracks'])]

        def resource(it):
            r = res.get(it.get('id'))
            return dict(r) if r else None
        argv, total = _FFBuild(script['profile'], notes, resource).build(tracks, video_output, caption_file=cap_file)
        if script.get('master'):
            notes.append('master effects are not in the ffmpeg version')
        text = _script_text(argv, flavor)
        out.update(argv=argv, command=subprocess.list2cmdline(argv), video_output=str(video_output),
                   length=_r(total))
        if flavor == 'bat' and len(text) > 8000:
            notes.append(f'the script is {len(text)} characters; cmd.exe allows 8191 per command')
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text, encoding='utf-8', newline='\n' if form != 'ffmpeg' or flavor != 'bat' else '\r\n')
        out['file'] = str(Path(output))
    out['text'] = text
    out['notes'] = list(dict.fromkeys(notes))
    return out
