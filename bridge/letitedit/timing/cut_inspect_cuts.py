"""Where the cuts are.

Part of `cut_inspect` (letitedit/timing/cut_inspect.py), which imports every name here back,
so `cut_inspect.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import os
import re
import subprocess
from pathlib import Path
from letitedit.timing.cut_inspect_base import (  # noqa: E402
    CACHE, MELT, NO_WINDOW, _clock, _r
)


# ------------------------------------------------------------------ where the cuts are

PICTURE_EXT = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf', '.mpg', '.mpeg', '.wmv',
               '.jpg', '.jpeg', '.png', '.heic', '.webp', '.tif', '.tiff', '.gif', '.bmp'}
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.tif', '.tiff', '.gif', '.bmp'}


def _store():
    try:
        import letitedit.timing.timing_signals as timing_signals
    except Exception:  # noqa: BLE001 - the store is optional
        return None
    return timing_signals if hasattr(timing_signals, 'signals') else None


def _is_project(source):
    p = Path(str(source))
    return p.suffix.lower() == '.mlt' or p.is_dir()


def _resolve_project(source):
    import letitedit.timeline.edit_script as es
    return es._resolve(source)


def _is_picture(it, top_track):
    if it.get('color'):
        c = str(it['color'])
        return not (len(c) == 9 and c.startswith('#') and c[1:3].lower() == '00')   # transparent colour: overlay
    clip = it.get('clip')
    if not clip:
        return False
    p = str(clip).replace('/', '\\').lower()
    name = os.path.basename(p)
    ext = os.path.splitext(name)[1]
    if ext not in PICTURE_EXT or '\\graphics\\' in p or name.startswith(('word_captions', 'ass-', 'caption')):
        return False
    if top_track and ext in IMAGE_EXT:
        return False
    for e in it.get('effects') or []:
        if isinstance(e, dict) and 'size_position' in e and top_track:
            return False
    return True


def project_cuts(project):
    """Cuts of a project's visible picture from its edit script: where the topmost picture item (footage, not
    graphics, captions or picture-in-picture) changes, or the same file jumps in source time; gaps (black) and
    transitions are their own kinds. Returns (meta, cuts)."""
    import letitedit.timeline.edit_script as es
    path = _resolve_project(project)
    script = es.read(str(path))
    fps = float(script['profile']['fps'])
    total = int(round(es.to_seconds(script['length']) * fps))
    vids = [t for t in script['tracks'] if t.get('kind') == 'video' and t.get('hide') not in ('video', 'both')]
    top = [None] * max(0, total)
    trans = {}
    for order, t in enumerate(vids):
        for it in t['items']:
            if 'at' not in it or 'id' not in it or not _is_picture(it, order > 0):
                continue
            f0 = int(round(es.to_seconds(it['at']) * fps))
            f1 = min(total, f0 + int(round(float(it['len']) * fps)))
            rec = {'id': it['id'], 'track': t['name'], 'clip': it.get('clip') or it.get('color'), 'f0': f0, 'f1': f1,
                   'in_s': it.get('in'), 'out_s': it.get('out'), 'speed': float(it.get('speed') or 1.0),
                   'effects': [list(e.keys())[0] for e in it.get('effects') or [] if isinstance(e, dict)]}
            if it.get('transition'):
                trans[it['id']] = it['transition']
            for f in range(max(0, f0), f1):
                top[f] = rec
    cuts = []
    f = 1
    while f < total:
        if top[f] is top[f - 1]:
            f += 1
            continue
        A, B = top[f - 1], top[f]
        if A is None and B is not None:            # end of a gap: handled from its start
            f += 1
            continue
        if B is None:                               # a gap: find where it ends
            g = f
            while g < total and top[g] is None:
                g += 1
            if g >= total:
                break
            B = top[g]
            cuts.append({'f': g, 't': g / fps, 'kind': 'gap', 'gap': [f, g], 'from_item': A['id'], 'to_item': B['id'],
                         'from_clip': A['clip'], 'to_clip': B['clip'], 'a_end': f, 'b_start': g})
            f = g + 1
            continue
        if A['clip'] == B['clip'] and A['in_s'] is not None and B['in_s'] is not None and \
                abs(A['speed'] - B['speed']) < 1e-6:
            a_src = float(A['in_s']) + (f - A['f0']) * A['speed'] / fps     # where A would continue
            b_src = float(B['in_s']) + (f - B['f0']) * B['speed'] / fps
            if abs(a_src - b_src) <= 1.5 / fps:
                f += 1
                continue
        kind, a_end, b_start = 'cut', f, f
        tr = trans.get(B['id'])
        if tr and str(tr.get('type', 'dissolve')) != 'cut' and float(tr.get('len') or 0) > 0:
            n = int(round(float(tr['len']) * fps))
            kind, a_end, b_start = ('dissolve' if 'dissolve' in str(tr.get('type', 'dissolve')) else 'wipe'), f, f + n
        a_out = None
        if A['in_s'] is not None:
            a_out = float(A['in_s']) + (f - A['f0']) * A['speed'] / fps
        cuts.append({'f': b_start if kind != 'cut' else f, 't': (b_start if kind != 'cut' else f) / fps, 'kind': kind,
                     'from_item': A['id'], 'to_item': B['id'], 'from_clip': A['clip'], 'to_clip': B['clip'],
                     'a_end': a_end, 'b_start': b_start, 'from_out_s': _r(a_out, 4), 'to_in_s': B['in_s'],
                     'from_speed': A['speed'], 'to_speed': B['speed'], 'from_effects': A['effects'],
                     'to_effects': B['effects']})
        f += 1
    meta = {'project': str(path), 'fps': fps, 'frames': total, 'size': [script['profile']['width'],
                                                                        script['profile']['height']],
            'revision': script.get('base'), 'cuts_from': 'edit script (topmost picture item)'}
    return meta, cuts


def preview_render(project, px=480, refresh=False):
    """A small melt render of the whole timeline (same frame rate, with sound) for measuring, cached by the
    timeline's content. Used when the timing store is not present."""
    import letitedit.timeline.timeline_model as tm
    path = _resolve_project(project)
    tl = tm.load(path)
    key = tl.range_fingerprint(0, tl.frames, video=True, audio=True)
    p = tl.profile
    s = float(px) / max(p['width'], p['height'])
    w, h = max(16, int(round(p['width'] * s / 2)) * 2), max(16, int(round(p['height'] * s / 2)) * 2)
    out = CACHE / 'renders' / f'{key}-{w}x{h}.mp4'
    if out.exists() and not refresh:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(f'.{os.getpid()}.tmp.mp4')
    args = [str(MELT), '-quiet', str(path), 'in=0', f'out={tl.frames - 1}', '-consumer', f'avformat:{tmp}',
            'vcodec=libx264', 'crf=20', 'preset=veryfast', 'pix_fmt=yuv420p', 'acodec=aac', 'ab=128k', 'threads=4',
            f'width={w}',
            f'height={h}', f'progressive={p["progressive"]}', f'frame_rate_num={p["frame_rate_num"]}',
            f'frame_rate_den={p["frame_rate_den"]}', 'sample_aspect_num=1', 'sample_aspect_den=1',
            f'display_aspect_num={w}', f'display_aspect_den={h}', 'real_time=-1']

    def run():
        r = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=7200,
                           creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        if r.returncode != 0 or not tmp.exists():
            raise RuntimeError(f'melt preview render failed ({r.returncode}): {(r.stderr or r.stdout)[-800:]}')
    if tl.frames / tl.fps > 30:
        import letitedit.core.render_lock as render_lock
        with render_lock.slot('cut_inspect preview render', caller_pids=render_lock.ancestors()):
            run()
    else:
        run()
    os.replace(tmp, out)
    return out


def video_cuts(video, start_s=None, end_s=None, settings=None):
    """Cuts of a video file from shots.detect (hard cuts, punch-ins, dissolves, fades)."""
    import letitedit.footage.shots as shots
    det = shots.detect(video, start_s, end_s, settings=settings)
    cuts = []
    for c in det['cuts']:
        rec = {'f': int(c['frame']), 't': float(c['t']), 'kind': c['kind'], 'measures_detect': c.get('measures')}
        if c['kind'] in ('dissolve', 'fade') and c.get('start_frame') is not None:
            rec['a_end'] = int(c['start_frame'])
            rec['b_start'] = int(c['end_frame']) + 1
            if c['kind'] == 'fade' and c.get('flat'):
                rec['flat'] = c['flat']
        else:
            rec['a_end'] = rec['b_start'] = int(c['frame'])
        cuts.append(rec)
    return {'cuts_from': 'shots.detect', 'detect_warnings': det.get('warnings', [])}, cuts


def store_cut_list(raw, fps, video=None, warnings=None):
    """The timing store's edit.cuts in this module's form: {f, t, kind, a_end (A's frames are < a_end), b_start
    (B's frames are >= b_start), from/to item and clip, detail}. A hard cut has a_end = b_start = f; a dissolve or
    fade covers [f0, f1) (B1's half-open range); a cut to black followed by a cut from black is one 'gap' join (the
    black frames between two shots); a cut from or to black at the very start or end is not a join of two shots."""
    warnings = warnings if warnings is not None else []
    vid = os.path.normcase(os.path.abspath(str(video))) if video else None
    out = []
    raw = sorted(raw or [], key=lambda c: int(c.get('f', 0)))
    i = 0
    while i < len(raw):
        c = raw[i]
        f = int(c.get('f', round(float(c.get('t', 0)) * fps)))
        kind = c.get('kind') or 'cut'
        detail = c.get('detail')
        rec = {'f': f, 't': f / fps, 'kind': kind, 'detail': detail, 'from_item': c.get('from_item'),
               'to_item': c.get('to_item'), 'from_clip': c.get('from_clip'), 'to_clip': c.get('to_clip'),
               'from_track': c.get('from_track'), 'to_track': c.get('to_track')}
        for k in ('from_clip', 'to_clip'):
            if rec[k] and vid and os.path.normcase(os.path.abspath(str(rec[k]))) == vid:
                rec[k] = None                         # a plain video: the 'clip' is the file itself
        to_black = c.get('to_item') is None and c.get('from_item') is not None and \
            (detail == 'to black' or c.get('to_clip') is None and kind in ('cut', 'fade'))
        from_black = c.get('from_item') is None and c.get('to_item') is not None and \
            (detail == 'from black' or c.get('from_clip') is None and kind in ('cut', 'fade'))
        if c.get('from_item') is None and c.get('to_item') is None and c.get('from_clip') and c.get('to_clip'):
            to_black = from_black = False             # a video's cut: no items at all
        if to_black:
            nxt = raw[i + 1] if i + 1 < len(raw) else None
            if nxt is not None and nxt.get('from_item') is None and nxt.get('to_item') is not None:
                g1 = int(nxt.get('f', 0))
                b_start = int(nxt.get('f1', g1)) if (nxt.get('kind') == 'fade') else g1
                a_end = int(c.get('f0', f)) if kind == 'fade' else f
                rec.update(f=b_start, t=b_start / fps, kind='gap', a_end=a_end, b_start=b_start, gap=[f, g1],
                           to_item=nxt.get('to_item'), to_clip=nxt.get('to_clip'), to_track=nxt.get('to_track'),
                           detail=f'{g1 - f} black frame(s) between the shots'
                           + (' (with fades)' if 'fade' in (kind, nxt.get('kind')) else ''))
                if rec['to_clip'] and vid and os.path.normcase(os.path.abspath(str(rec['to_clip']))) == vid:
                    rec['to_clip'] = None
                out.append(rec)
                i += 2
                continue
            warnings.append(f'cut to black at {_clock(f / fps)} (f{f}) with nothing after it: not a join of two shots')
            i += 1
            continue
        if from_black:
            warnings.append(f'cut from black at {_clock(f / fps)} (f{f}) with no shot before it: not a join')
            i += 1
            continue
        if kind in ('dissolve', 'fade', 'wipe') and c.get('f0') is not None and c.get('f1') is not None:
            rec['a_end'], rec['b_start'] = int(c['f0']), int(c['f1'])
            rec['range'] = [int(c['f0']), int(c['f1'])]
        else:
            rec['a_end'] = rec['b_start'] = f
        if c.get('transition'):
            rec['transition'] = c['transition']
        if c.get('same_clip'):
            rec['same_clip'] = True
            rec['source_jump_s'] = c.get('source_jump_s')
        out.append(rec)
        i += 1
    return out


def _store_cuts(store, source, start_s, end_s, warnings, settings=None, refresh=False):
    try:
        sig = store.signals(str(source), start=start_s, end=end_s, lanes=['edit'], settings=settings,
                            refresh=['edit'] if refresh else False)
    except Exception as ex:  # noqa: BLE001 - fall back to computing here
        warnings.append(f'timing_signals.signals failed ({type(ex).__name__}: {str(ex)[:160]}); cut list computed '
                        'here instead')
        return None
    lane = (sig.get('lanes') or {}).get('edit') or {}
    raw = lane.get('cuts')
    if raw is None:
        warnings.append('timing_signals gave no edit.cuts' + (f' ({lane.get("error")})' if lane.get('error') else '')
                        + '; cut list computed here instead')
        return None
    fps = float(sig['fps'])
    video = sig.get('render') if sig.get('kind') == 'project' else (sig.get('render') or sig.get('source'))
    cuts = store_cut_list(raw, fps, video, warnings)
    for w in sig.get('warnings') or []:
        warnings.append(f'timing_signals: {w}')
    meta = {'fps': fps, 'frames': int(sig['frames']), 'size': sig.get('size'), 'video': video,
            'cuts_from': f'timing_signals edit lane ({lane.get("source_of_cuts") or lane.get("method", "")[:60]})',
            'sig': sig, 'items': lane.get('items'), 'revision': sig.get('project_revision'),
            'project': sig.get('project')}
    return meta, cuts


def _select(cut_list, cuts, items, start_s, end_s, fps, frames, warnings):
    """The cuts to inspect: by number (1-based, as listed), time, frame, item id, or range."""
    for k, c in enumerate(cut_list):
        c['n'] = k + 1
    sel = cut_list
    if start_s is not None or end_s is not None:
        lo = float(start_s or 0.0)
        hi = float(end_s) if end_s is not None else 1e12
        sel = [c for c in sel if lo <= c['t'] < hi]
    if items:
        ids = {str(i) for i in (items if isinstance(items, (list, tuple, set)) else [items])}
        sel = [c for c in sel if str(c.get('from_item')) in ids or str(c.get('to_item')) in ids]
    if cuts is None:
        return sel
    if not isinstance(cuts, (list, tuple)):
        cuts = [cuts]
    out = []
    for q in cuts:
        f = None
        if isinstance(q, bool):
            continue
        if isinstance(q, int):
            if 1 <= q <= len(cut_list):
                out.append(cut_list[q - 1])
            else:
                warnings.append(f'cut number {q} does not exist (1-{len(cut_list)})')
            continue
        if isinstance(q, float):
            f = int(round(q * fps))
        elif isinstance(q, dict):
            if 'f' in q:
                f = int(q['f'])
            elif 't' in q:
                f = int(round(float(q['t']) * fps))
            elif 'n' in q:
                n = int(q['n'])
                if 1 <= n <= len(cut_list):
                    out.append(cut_list[n - 1])
                continue
        elif isinstance(q, str):
            s = q.strip().lower()
            m = re.fullmatch(r'f(\d+)', s)
            if m:
                f = int(m.group(1))
            else:
                m = re.fullmatch(r'(?:(\d+):)?(\d+(?:\.\d+)?)s?', s)
                if m:
                    f = int(round(((int(m.group(1)) * 60) if m.group(1) else 0) * fps + float(m.group(2)) * fps))
                elif s.isdigit():
                    n = int(s)
                    if 1 <= n <= len(cut_list):
                        out.append(cut_list[n - 1])
                    continue
        if f is None:
            warnings.append(f'could not read cut {q!r}')
            continue
        near = [c for c in cut_list if abs(c['f'] - f) <= 2]
        if near:
            out.append(min(near, key=lambda c: abs(c['f'] - f)))
        elif 0 < f < frames:
            out.append({'f': f, 't': f / fps, 'kind': 'given', 'a_end': f, 'b_start': f, 'n': None})
            warnings.append(f'no cut at frame {f} ({_clock(f / fps)}); measured as a join there')
        else:
            warnings.append(f'frame {f} is outside the video')
    seen, uniq = set(), []
    for c in out:
        key = (c['f'], c['kind'])
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq
