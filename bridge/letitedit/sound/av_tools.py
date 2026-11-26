"""Sound and picture helpers for an edit: a song fitted to the edit, recordings lined up by their sound, something
followed through a shot, and picks/notes kept inside the project where a person sees them in letitedit.

    fit_music(song, length, hits, keep, loop, start, fade_out, out, ...)   a new audio file cut and joined on the
                                                                           song's own beats/bars; where every joint,
                                                                           hit and beat lands
    sync(files, reference, max_offset_s, rate, ...)                        each file's offset to a reference from
                                                                           its sound (+ drift), next to the offset
                                                                           from the recording-time metadata
    track(file, start, end, target, every_s, size, out_dir, ...)           a box per sample through a span (OpenCV
                                                                           VitTrack) + a frame sheet with the boxes
    bin(project, add, markers, remove)                                     timeline markers (Shotcut's Markers panel)
                                                                           and subclips in the bin (Playlist panel),
                                                                           stored in the .mlt; no arguments = read

Every function takes data and returns data (dicts of numbers, times and file paths). Every number it uses is the
caller's choice; the values used (defaults included) come back in the result under 'settings'. Images are files.
Times are seconds.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import json
import math
import os
import shutil
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

HERE = _paths.BRIDGE
APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))
MELT = APP / 'melt.exe'
MODELS = Path(os.environ.get('LETITEDIT_VFX', (_SAI_ROOT + '\\vfx'))) / 'models'
VITTRACK = MODELS / 'vittrack_2023sep.onnx'
YUNET = MODELS / 'yunet_2023mar.onnx'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

__all__ = ['fit_music', 'sync', 'track', 'bin']


# ============================================================================ shared helpers

def _ffmpeg():
    import letitedit.timeline.made as made
    return str(made.ffmpeg_exe())


def _out_dir(kind, out_dir=None):
    if out_dir:
        d = Path(out_dir)
    else:
        d = Path(tempfile.gettempdir()) / 'letitedit_ai' / kind / (time.strftime('%Y%m%d-%H%M%S') + f'-{uuid.uuid4().hex[:4]}')
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sec(v):
    """Seconds from a number or 'm:ss.mmm' / 'h:mm:ss'."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    text = str(v).strip()
    if ':' in text:
        s = 0.0
        for part in text.split(':'):
            s = s * 60 + float(part)
        return s
    return float(text)


def _r(x, nd=3):
    return None if x is None else round(float(x), nd)


def _decode(path, sr, channels=1):
    """Whole audio stream as float32 (n,) for mono or (n, channels)."""
    r = subprocess.run([_ffmpeg(), '-v', 'error', '-nostdin', '-i', str(path), '-vn', '-sn', '-dn', '-ac', str(channels),
                        '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True, creationflags=NO_WINDOW)
    data = r.stdout[:len(r.stdout) // (4 * channels) * (4 * channels)]
    y = np.frombuffer(data, np.float32).copy()
    if not y.size and r.returncode:
        raise ValueError(f'could not decode the sound of {path}: {r.stderr.decode(errors="replace")[-300:]}')
    return y if channels == 1 else y.reshape(-1, channels)


# ============================================================================ fit_music

FIT_DEFAULTS = {'crossfade_s': 0.04, 'land': 'cut', 'stretch_max': 0.06, 'tolerance_s': 0.02, 'snap': 'downbeat',
                'fade_in': 0.005, 'fade_out': 1.5, 'rate': 48000}
_EPS = 1e-6


def _nearest(arr, x):
    arr = np.asarray(arr, float)
    if not arr.size:
        return None
    return float(arr[int(np.argmin(np.abs(arr - x)))])


def _grid_label(t, beats, down, tol=0.002):
    if t is None:
        return None
    if down.size and np.min(np.abs(down - t)) <= tol:
        return 'downbeat'
    if beats.size and np.min(np.abs(beats - t)) <= tol:
        return 'beat'
    return None


def _parse_hits(hits):
    out = []
    for h in hits or []:
        if isinstance(h, dict):
            t, kind = h.get('at', h.get('t')), h.get('on', h.get('kind', 'downbeat'))
        elif isinstance(h, (int, float, str)):
            t, kind = h, 'downbeat'
        else:
            t, kind = h[0], (h[1] if len(h) > 1 else 'downbeat')
        if isinstance(kind, str):
            k = kind.strip().lower()
            k = {'downbeats': 'downbeat', 'beats': 'beat', 'sections': 'section', 'bar': 'downbeat',
                 'bars': 'downbeat'}.get(k, k)
            try:
                kind = _sec(k)            # a song time given as text
            except ValueError:
                kind = k
        else:
            kind = float(kind)
        out.append((_sec(t), kind))
    return sorted(out, key=lambda h: h[0])


def _stretch_audio(x, ratio, sr):
    """x (n, 2) played `ratio` times faster (pitch kept): ffmpeg rubberband when it has it, else atempo."""
    filt, name = (f'rubberband=tempo={ratio:.6f}', 'rubberband') if _has_filter('rubberband') else \
        (f'atempo={ratio:.6f}', 'atempo')
    r = subprocess.run([_ffmpeg(), '-v', 'error', '-nostdin', '-f', 'f32le', '-ar', str(sr), '-ac', '2', '-i', '-',
                        '-af', filt, '-f', 'f32le', '-ar', str(sr), '-ac', '2', '-'],
                       input=np.ascontiguousarray(x, np.float32).tobytes(), capture_output=True, creationflags=NO_WINDOW)
    y = np.frombuffer(r.stdout[:len(r.stdout) // 8 * 8], np.float32).reshape(-1, 2)
    want = int(round(len(x) / ratio))
    if len(y) < want:
        y = np.vstack([y, np.zeros((want - len(y), 2), np.float32)])
    return y[:want], name


_FILTERS = {}


def _has_filter(name):
    if name not in _FILTERS:
        r = subprocess.run([_ffmpeg(), '-hide_banner', '-filters'], capture_output=True, text=True, errors='replace',
                           creationflags=NO_WINDOW)
        _FILTERS[name] = any(line.split()[1:2] == [name] for line in r.stdout.splitlines() if len(line.split()) > 1)
    return _FILTERS[name]


def _write_audio(y, sr, out):
    ext = Path(out).suffix.lower()
    codec = {'.wav': ['-c:a', 'pcm_f32le'], '.flac': ['-c:a', 'flac', '-sample_fmt', 's32'], '.mp3': ['-c:a', 'libmp3lame', '-q:a', '2'],
             '.m4a': ['-c:a', 'aac', '-b:a', '256k'], '.aac': ['-c:a', 'aac', '-b:a', '256k'],
             '.ogg': ['-c:a', 'libvorbis', '-q:a', '6'], '.opus': ['-c:a', 'libopus', '-b:a', '192k']}.get(ext, [])
    tmp = Path(out).with_name(f'{Path(out).stem}.{uuid.uuid4().hex[:6]}.part{ext}')
    r = subprocess.run([_ffmpeg(), '-v', 'error', '-nostdin', '-y', '-f', 'f32le', '-ar', str(sr), '-ac', '2', '-i', '-',
                        *codec, str(tmp)], input=np.ascontiguousarray(y, np.float32).tobytes(), capture_output=True,
                       creationflags=NO_WINDOW)
    if r.returncode or not tmp.exists():
        raise RuntimeError(f'writing {out} failed: {r.stderr.decode(errors="replace")[-400:]}')
    os.replace(tmp, out)


def _fit_music_material(keep, start, loop, length, grid, L, snapped):
    def snap_t(x, what):
        x = min(max(0.0, float(x)), L)
        if x <= _EPS or x >= L - _EPS or grid is None or not grid.size:
            return x
        y = _nearest(grid, x)
        if abs(y - x) > _EPS:
            snapped.append({'what': what, 'given': _r(x), 'used': _r(y)})
        return y

    # ---- material: the song spans in play order (before hits)
    pieces = []          # [a, b, label]
    if keep:
        for i, span in enumerate(keep, 1):
            a, b = snap_t(_sec(span[0]), f'keep {i} start'), snap_t(_sec(span[1]), f'keep {i} end')
            if b - a > _EPS:
                pieces.append([a, b, f'keep {i}'])
        if not pieces:
            raise ValueError('every keep span is empty')
    else:
        pieces.append([0.0, L, 'song'])
    if start is not None:
        s0 = _sec(start)
        if not 0 <= s0 < L:
            raise ValueError(f'start {s0} is outside the song (0-{L:.2f} s)')
        k = next((i for i, p in enumerate(pieces) if p[0] - _EPS <= s0 < p[1]), None)
        if k is None:
            raise ValueError(f'start {s0} is not inside any keep span')
        pieces = [[s0, pieces[k][1], pieces[k][2]]] + pieces[k + 1:]
    loop_info = None
    if loop:
        la, lb = snap_t(_sec(loop[0]), 'loop start'), snap_t(_sec(loop[1]), 'loop end')
        if lb - la <= _EPS:
            raise ValueError('the loop span is empty')
        k = next((i for i, p in enumerate(pieces) if p[0] < lb - _EPS and lb <= p[1] + _EPS), None)
        if k is None:
            loop_info = {'span': [_r(la), _r(lb)], 'times': 0, 'note': 'playback never reaches the loop end'}
        else:
            if len(loop) > 2:
                n = int(loop[2])
            elif length is not None:
                base = sum(p[1] - p[0] for p in pieces)
                n = max(0, math.ceil((length - base) / (lb - la) - 1e-9))
            else:
                n = 1
            a_k, b_k, lab = pieces[k]
            new = [[a_k, lb, lab]] + [[la, lb, f'loop {j + 1}'] for j in range(n)]
            if b_k - lb > _EPS:
                new.append([lb, b_k, lab])
            pieces = pieces[:k] + new + pieces[k + 1:]
            loop_info = {'span': [_r(la), _r(lb)], 'times': n}
    V = [0.0]
    for p in pieces:
        V.append(V[-1] + p[1] - p[0])
    Vtot = V[-1]
    return pieces, V, Vtot, loop_info


def _fit_music_hits(down, beats, sections, pieces, V, Vtot, hits, length, xf, tol, land, bar, smax):
    def song_events(kind):
        if kind == 'downbeat':
            return down
        if kind == 'beat':
            return beats
        if isinstance(kind, float):
            return np.array([kind])
        if kind == 'section' or kind.startswith('section:'):
            name = kind.split(':', 1)[1].strip() if ':' in kind else ''
            starts = [float(s[0]) for s in sections if not name or str(s[2]).startswith(name)]
            # section starts are stored to 0.01 s after being snapped to a downbeat: use that downbeat
            return np.array([d if (d := _nearest(down, t)) is not None and abs(d - t) <= 0.011 else t
                             for t in starts], float)
        raise ValueError(f"unknown hit kind {kind!r}: 'downbeat', 'beat', 'section', 'section:<name>', 'end' or a "
                         'song time')

    def vevents(kind):
        src = song_events(kind)
        out_v = []
        for (a, b, _), v0 in zip(pieces, V):
            sel = src[(src >= a - _EPS) & (src < b - _EPS)]
            out_v.extend((v0 + (sel - a)).tolist())
        return np.array(sorted(out_v), float)

    # ---- hits -> output segments [o0, o1, v0, v1, rate, why]
    segs, hit_rep = [], []
    oa, va = 0.0, 0.0
    why_next = 'start'          # what made the joint at the start of the next segment
    for n_hit, (T, kind) in enumerate(_parse_hits(hits), 1):
        rep = {'hit': n_hit, 'at': _r(T), 'on': kind}
        hit_rep.append(rep)
        if length is not None and T > length + _EPS:
            rep['by'] = 'skipped: after the end of the output'
            continue
        if T < oa + max(xf, 0.01):
            rep['by'] = 'skipped: at or too close after the previous hit'
            continue
        vp = va + (T - oa)
        if kind == 'end':
            ve = Vtot
        else:
            cands = vevents(kind)
            if not cands.size:
                rep['by'] = f'skipped: no {kind} in the material'
                continue
            ve = _nearest(cands, vp)
        d = ve - vp
        rep['song'] = _r(_v_to_song(pieces, V, ve))
        if abs(d) <= tol:
            rep.update(by='already there', lands_at=_r(T + d), error_s=_r(d, 4))
            continue
        if land == 'none':
            rep.update(by='none', lands_at=_r(T + d), error_s=_r(d, 4))
            continue
        if land == 'stretch':
            J = K = None
            if abs(d) > bar / 2:
                vd = vevents('downbeat')
                cj = vd[(vd >= va + xf) & (vd <= min(vp, Vtot) - xf)]
                if cj.size:
                    J = float(cj[-1])
                    K = _nearest(vd, J + d)
            span_v = ((J - va) + (ve - K)) if J is not None else (ve - va)
            ratio = span_v / (T - oa)
            if span_v > 0 and abs(ratio - 1) <= smax:
                if J is not None:
                    oj = oa + (J - va) / ratio
                    segs.append([oa, oj, va, J, ratio, why_next])
                    segs.append([oj, T, K, ve, ratio, f'bars for hit {n_hit}'])
                else:
                    segs.append([oa, T, va, ve, ratio, why_next])
                oa, va = T, ve
                why_next = f'tempo back after hit {n_hit}'
                rep.update(by='stretch', rate=_r(ratio, 5), lands_at=_r(T), error_s=0.0)
                continue
            rep['stretch_needed'] = _r(ratio, 4)
        # cut
        if kind == 'end':
            lo_t = oa + xf
            hi_t = min(T, oa + (Vtot - va))
            lo_v, hi_v = max(0.0, Vtot - (T - lo_t)), Vtot - (T - hi_t)
            if hi_v < lo_v:
                rep['by'] = 'skipped: no room for the ending'
                continue
            sec_v = vevents('section')
            last_sec = float(sec_v[-1]) if sec_v.size else None
            vd = vevents('downbeat')
            inside = vd[(vd >= lo_v - _EPS) & (vd <= hi_v + _EPS)]
            if last_sec is not None and lo_v - _EPS <= last_sec <= hi_v + _EPS:
                v_in = last_sec
            elif inside.size:
                v_in = float(inside[0])
            else:
                v_in = lo_v
            tj = T - (Vtot - v_in)
            segs.append([oa, tj, va, va + (tj - oa), 1.0, why_next])
            oa, va = tj, v_in
            why_next = f'hit {n_hit}'
            rep.update(by='cut', joint_at=_r(tj), lands_at=_r(T), error_s=0.0)
        else:
            segs.append([oa, T, va, vp, 1.0, why_next])
            oa, va = T, ve
            why_next = f'hit {n_hit}'
            rep.update(by='cut', lands_at=_r(T), error_s=0.0)
    o_end = length if length is not None else oa + max(0.0, Vtot - va)
    music_end = min(o_end, oa + max(0.0, Vtot - va))
    if music_end > oa + _EPS:
        segs.append([oa, music_end, va, va + (music_end - oa), 1.0, why_next])
    return segs, hit_rep, o_end, music_end


def _fit_music_pieces(segs, Vtot, V, pieces):
    out_p = []
    for o0, o1, v0, v1, ratio, why in segs:
        v, first = v0, True
        while v < min(v1, Vtot) - 1e-9:
            i = max(0, int(np.searchsorted(V, v, side='right')) - 1)
            if i >= len(pieces):
                break
            sub = min(v1, V[i + 1])
            a = pieces[i][0] + (v - V[i])
            b = pieces[i][0] + (sub - V[i])
            out_p.append({'o0': o0 + (v - v0) / ratio, 'o1': o0 + (sub - v0) / ratio, 'a': a, 'b': b, 'rate': ratio,
                          'why': why if first else pieces[i][2]})
            v, first = sub, False
    merged = []
    for p in out_p:
        q = merged[-1] if merged else None
        if q and abs(q['b'] - p['a']) < 1e-6 and abs(q['o1'] - p['o0']) < 1e-6 and abs(q['rate'] - p['rate']) < 1e-9:
            q['b'], q['o1'] = p['b'], p['o1']
        else:
            merged.append(dict(p))
    out_p = merged
    return out_p


def _mix_music_pieces(o_end, sr, out_p, xf, audio, down, beats, L, music_end, fade_out, fin):
    n_out = int(round(o_end * sr))
    buf = np.zeros((n_out, 2), np.float32)
    stretch_filter = None
    joints = []
    for k, p in enumerate(out_p):
        prev = out_p[k - 1] if k else None
        nxt = out_p[k + 1] if k + 1 < len(out_p) else None
        joined = prev is not None and abs(prev['o1'] - p['o0']) < 1e-6
        xf_in, xf_out = _join_xf(prev, p, xf), _join_xf(p, nxt, xf)
        a0 = p['a'] - xf_in * p['rate']
        i0, i1 = int(round(a0 * sr)), int(round(p['b'] * sr))
        seg = audio[max(0, i0):max(0, i1)]
        if i0 < 0:
            seg = np.vstack([np.zeros((-i0, 2), np.float32), seg])
        if abs(p['rate'] - 1.0) > 1e-9:
            seg, stretch_filter = _stretch_audio(seg, p['rate'], sr)
        seg = seg.astype(np.float32, copy=True)
        start_n = int(round((p['o0'] - xf_in) * sr))
        want = int(round(p['o1'] * sr)) - start_n
        seg = seg[:want] if len(seg) >= want else np.vstack([seg, np.zeros((want - len(seg), 2), np.float32)])
        nin, nout = int(round(xf_in * sr)), int(round(xf_out * sr))
        if nin:
            seg[:nin] *= np.sin(np.linspace(0, np.pi / 2, nin, dtype=np.float32))[:, None]
        if nout:
            seg[-nout:] *= np.cos(np.linspace(0, np.pi / 2, nout, dtype=np.float32))[:, None]
        lo, hi = max(0, start_n), min(n_out, start_n + len(seg))
        if hi > lo:
            buf[lo:hi] += seg[lo - start_n:hi - start_n]
        if prev is not None and (not joined or abs(prev['b'] - p['a']) > 1e-6):
            fd, td = _nearest(down, prev['b']), _nearest(down, p['a'])
            j = {'at': _r(p['o0']), 'from_song': _r(prev['b']), 'to_song': _r(p['a']), 'why': p['why'],
                 'from_on': _grid_label(prev['b'], beats, down), 'to_on': _grid_label(p['a'], beats, down),
                 'from_nearest_downbeat_s': _r(prev['b'] - fd, 4) if fd is not None else None,
                 'to_nearest_downbeat_s': _r(p['a'] - td, 4) if td is not None else None,
                 'crossfade_s': _r(xf_in, 4)}
            if not joined:
                j['silence_before_s'] = _r(p['o0'] - prev['o1'])
            joints.append(j)
    ends_on_song_end = bool(out_p) and abs(out_p[-1]['b'] - L) < 0.05 and abs(out_p[-1]['o1'] - music_end) < 1e-6
    fo = float(fade_out) if fade_out is not None else (0.0 if ends_on_song_end else FIT_DEFAULTS['fade_out'])
    if fin > 0 and n_out:
        m = min(n_out, int(round(fin * sr)))
        buf[:m] *= np.linspace(0, 1, m, dtype=np.float32)[:, None]
    if fo > 0 and music_end > 0:
        e = min(n_out, int(round(music_end * sr)))
        m = min(e, int(round(fo * sr)))
        buf[e - m:e] *= np.linspace(1, 0, m, dtype=np.float32)[:, None]
    peak = float(np.abs(buf).max(initial=0.0))
    return n_out, buf, stretch_filter, joints, fo, peak


def fit_music(song, length=None, hits=None, keep=None, loop=None, start=None, fade_out=None, out=None,
              crossfade_s=None, land=None, stretch_max=None, tolerance_s=None, snap=None, fade_in=None, rate=None):
    """A new audio file made from `song`, cut and joined on the song's own beats and bars.

    length       output length (s). Default: where the material runs out.
    hits         [[timeline_s, on], ...]: a musical event to land at that output time. `on`: 'downbeat' | 'beat' |
                 'section' | 'section:<name>' (e.g. 'section:peak') | 'end' (the song's own ending finishes there) |
                 a song time (s). The event used is the one nearest to where the song would be at that time.
    keep         [[a, b], ...]: song spans to use, in this order (ends snapped to `snap`).
    loop         [a, b] or [a, b, times]: that span repeats where playback first reaches b (times: enough for
                 `length`, else 1).
    start        song time the material begins at (exact, not snapped). Default 0 / the first keep span.
    fade_out     seconds faded at the end. Default 1.5 when the output stops before the song's end, else 0.
    out          output file (.wav = 32-bit float, so peaks over full scale are kept; .flac, .mp3, .m4a, .ogg).
                 Default: a new temp folder.
    crossfade_s  length of each joint's crossfade; it ends at the joint so the incoming event is at full level there.
    land         how a hit that is not already there is landed: 'cut' (a joint at the hit time whose incoming side is
                 the event), 'stretch' (tempo change between the previous hit and this one, after dropping/repeating
                 whole bars at a bar-line joint when the event is more than half a bar away; over `stretch_max` it
                 cuts), 'none' (nothing; the result says where the event lands).
    stretch_max  largest tempo change for 'stretch' (fraction). tolerance_s: a hit whose event already falls
                 within this is left alone. snap: what keep/loop span ends snap to: 'downbeat' | 'beat' | False
                 (exact).
    fade_in      seconds faded in at the start. rate: output sample rate.

    Returns the file, its length, the material, every piece (song span -> output span, rate), every joint (output
    time, song time on each side and what grid point each side is on), every hit (requested time, event song
    time, where it lands, how), and the output's beat grid (beats, downbeats, section starts in output time)."""
    import letitedit.footage.perception as perception
    import letitedit.sound.audio_library as audio_library
    t_start = time.time()
    song = str(audio_library.song_file(str(song)))
    if not Path(song).is_file():
        raise FileNotFoundError(song)
    xf = float(FIT_DEFAULTS['crossfade_s'] if crossfade_s is None else crossfade_s)
    land = (land or FIT_DEFAULTS['land']).lower()
    if land not in ('cut', 'stretch', 'none'):
        raise ValueError(f"land is how a hit is landed: 'cut', 'stretch' or 'none' (got {land!r}). To finish on the "
                         "song's own ending, give a hit: hits=[[<output time>, 'end']]")
    smax = float(FIT_DEFAULTS['stretch_max'] if stretch_max is None else stretch_max)
    tol = float(FIT_DEFAULTS['tolerance_s'] if tolerance_s is None else tolerance_s)
    snap_mode = FIT_DEFAULTS['snap'] if snap is None else (snap or 'none')
    fin = float(FIT_DEFAULTS['fade_in'] if fade_in is None else fade_in)
    sr = int(rate or FIT_DEFAULTS['rate'])
    length = _sec(length)

    res = perception.music(song)
    beats = np.asarray(res.get('beat_times') or [], float)
    down = np.asarray(res.get('downbeats') or [], float)
    sections = res.get('sections') or []
    audio = _decode(song, sr, 2)
    L = min(len(audio) / sr, float(res.get('duration') or len(audio) / sr)) if len(audio) else 0.0
    if L <= 0:
        raise ValueError(f'{song} has no sound')
    bar = float(np.median(np.diff(down))) if down.size > 1 else (4 * 60.0 / res['bpm'] if res.get('bpm') else 2.0)
    grid = {'downbeat': down, 'beat': beats}.get(str(snap_mode).lower())
    snapped = []

    pieces, V, Vtot, loop_info = _fit_music_material(keep, start, loop, length, grid, L, snapped)

    segs, hit_rep, o_end, music_end = _fit_music_hits(down, beats, sections, pieces, V, Vtot, hits, length, xf, tol, land, bar, smax)

    # ---- segments -> song pieces
    out_p = _fit_music_pieces(segs, Vtot, V, pieces)

    # ---- render
    n_out, buf, stretch_filter, joints, fo, peak = _mix_music_pieces(o_end, sr, out_p, xf, audio, down, beats, L, music_end, fade_out, fin)

    if out is None:
        name = f"{Path(song).stem[:48]} fit {_r(o_end, 2):g}s.wav"
        out = _out_dir('fit_music') / name
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_audio(buf, sr, out)

    # ---- the output's grid
    g_beats, g_down, g_secs = [], [], []
    sec_starts = [(d if (d := _nearest(down, float(s[0]))) is not None and abs(d - float(s[0])) <= 0.011
                   else float(s[0]), s[2]) for s in sections]
    for p in out_p:
        def m(t):
            return p['o0'] + (t - p['a']) / p['rate']
        g_beats += [m(t) for t in beats if p['a'] - _EPS <= t < p['b'] - _EPS]
        g_down += [m(t) for t in down if p['a'] - _EPS <= t < p['b'] - _EPS]
        g_secs += [[_r(m(t)), name] for t, name in sec_starts if p['a'] - _EPS <= t < p['b'] - _EPS]
    import letitedit.server.core_tools as core_tools
    try:
        file_len = core_tools.probe(str(out)).get('duration')
    except Exception:  # noqa: BLE001
        file_len = None
    return {
        'file': str(out), 'length_s': _r(n_out / sr, 4), 'file_duration_s': file_len,
        'song': song, 'song_length_s': _r(L), 'bpm': res.get('bpm'), 'bar_s': _r(bar, 4),
        'settings': {'length': length, 'start': _r(_sec(start)) if start is not None else None, 'crossfade_s': xf,
                     'land': land, 'stretch_max': smax, 'tolerance_s': tol, 'snap': snap_mode, 'fade_in': fin,
                     'fade_out': fo, 'rate': sr, 'stretch_filter': stretch_filter},
        'material': [[_r(a), _r(b), lab] for a, b, lab in pieces], 'material_length_s': _r(Vtot),
        'snapped': snapped, 'loop': loop_info,
        'pieces': [{'at': [_r(p['o0']), _r(p['o1'])], 'song': [_r(p['a']), _r(p['b'])], 'rate': _r(p['rate'], 5)}
                   for p in out_p],
        'joints': joints, 'hits': hit_rep, 'music_ends_s': _r(music_end),
        'grid': {'downbeats': [_r(t) for t in g_down], 'beats': [_r(t) for t in g_beats], 'sections': g_secs},
        'peak': _r(peak, 4), 'song_peak': _r(float(np.abs(audio).max(initial=0.0)), 4),
        'sample_format': 'float32' if out.suffix.lower() == '.wav' else out.suffix.lower().lstrip('.'),
        'seconds': _r(time.time() - t_start, 2),
    }


def _join_xf(prev, cur, xf):
    """Crossfade (s) ending where `cur` starts: the full length at a cut in the song, 5 ms where the song runs on
    (a tempo change), none after silence."""
    if prev is None or cur is None or abs(prev['o1'] - cur['o0']) > 1e-6:
        return 0.0
    base = xf if abs(prev['b'] - cur['a']) > 1e-6 else min(xf, 0.005)
    return max(0.0, min(base, cur['o0'], prev['o1'] - prev['o0']))


def _v_to_song(pieces, V, v):
    i = max(0, min(len(pieces) - 1, int(np.searchsorted(V, v, side='right')) - 1))
    return pieces[i][0] + (v - V[i])


# ============================================================================ sync

SYNC_DEFAULTS = {'rate': 8000, 'hop_s': 0.01, 'min_overlap_s': 10.0, 'fine_window_s': 20.0, 'drift_window_s': 20.0,
                 'near_max_offset_s': 10.0}
_BANDS = ((100, 400), (400, 1200), (1200, 3400))


def _onset_env(y, sr, hop):
    """Onset strength per hop: summed positive change of log band energy (three speech/music bands)."""
    from scipy.signal import butter, sosfilt
    n = len(y) // hop
    if n < 4:
        return np.zeros(max(n, 0))
    total = np.zeros(n)
    for lo, hi in _BANDS:
        hi = min(hi, 0.45 * sr)
        if hi <= lo:
            continue
        sos = butter(4, [lo, hi], btype='band', fs=sr, output='sos')
        z = sosfilt(sos, y.astype(np.float64))
        e = (z[:n * hop] ** 2).reshape(n, hop).mean(axis=1)
        le = np.log10(e + 1e-4 * e.max() + 1e-12)
        total += np.maximum(0.0, np.diff(le, prepend=le[:1]))
    return total


def _pearson_lags(r, x, lag_lo, lag_hi, min_overlap):
    """Pearson correlation of r[i + L] with x[i] for every lag L in [lag_lo, lag_hi] (FFT + running sums)."""
    nr, nx = len(r), len(x)
    n = 1 << int(math.ceil(math.log2(max(2, nr + nx))))
    c = np.fft.irfft(np.fft.rfft(r, n) * np.conj(np.fft.rfft(x, n)), n)
    lags = np.arange(lag_lo, lag_hi + 1)
    sxy = c[lags % n]
    i0 = np.maximum(0, -lags)
    i1 = np.minimum(nx, nr - lags)
    cnt = (i1 - i0).astype(float)
    ok = cnt >= max(2, min_overlap)
    i1 = np.maximum(i1, i0)
    cx, cx2 = np.concatenate([[0], np.cumsum(x)]), np.concatenate([[0], np.cumsum(x * x)])
    cr, cr2 = np.concatenate([[0], np.cumsum(r)]), np.concatenate([[0], np.cumsum(r * r)])
    j0, j1 = np.clip(i0 + lags, 0, nr), np.clip(i1 + lags, 0, nr)
    sx, sx2 = cx[i1] - cx[i0], cx2[i1] - cx2[i0]
    s_r, s_r2 = cr[j1] - cr[j0], cr2[j1] - cr2[j0]
    cnt = np.maximum(cnt, 1)
    num = sxy - sx * s_r / cnt
    den = np.sqrt(np.maximum(sx2 - sx * sx / cnt, 0) * np.maximum(s_r2 - s_r * s_r / cnt, 0))
    rho = np.where(ok & (den > 0), num / np.where(den > 0, den, 1), -1.0)
    return lags, rho


def _peak(lags, rho, exclude):
    k = int(np.argmax(rho))
    frac = 0.0
    if 0 < k < len(rho) - 1 and rho[k - 1] > -1 and rho[k + 1] > -1:
        a, b, c = rho[k - 1], rho[k], rho[k + 1]
        den = a - 2 * b + c
        if den < 0:
            frac = float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))
    far = np.abs(lags - lags[k]) > exclude
    second = float(rho[far].max()) if far.any() else None
    return float(lags[k]) + frac, float(rho[k]), second


def _gcc_phat(r, x, max_shift, sr, band=(150.0, 3400.0)):
    """Residual lag (samples, r[i + lag] ~ x[i]) and peak height of the phase-transform cross-correlation."""
    n = 1 << int(math.ceil(math.log2(len(r) + len(x))))
    R, X = np.fft.rfft(r, n), np.fft.rfft(x, n)
    G = R * np.conj(X)
    G /= np.maximum(np.abs(G), 1e-12)
    f = np.fft.rfftfreq(n, 1 / sr)
    G[(f < band[0]) | (f > min(band[1], 0.45 * sr))] = 0
    c = np.fft.irfft(G, n)
    lags = np.arange(-max_shift, max_shift + 1)
    v = c[lags % n]
    k = int(np.argmax(v))
    frac = 0.0
    if 0 < k < len(v) - 1:
        a, b, cc = v[k - 1], v[k], v[k + 1]
        den = a - 2 * b + cc
        if den < 0:
            frac = float(np.clip(0.5 * (a - cc) / den, -0.5, 0.5))
    return float(lags[k]) + frac, float(v[k] / max(1e-12, np.count_nonzero(G) / (n // 2 + 1)))


def _local_offset(yr, yx, sr, off, t0, t1, search_s):
    """Offset (s) measured on file span [t0, t1] (file seconds) around `off`, +- search_s: envelope Pearson then
    phase correlation. Returns (offset_s, envelope_r, waveform_peak) or None."""
    pad = search_s + 0.05
    a, b = int(t0 * sr), int(t1 * sr)
    ra, rb = int((t0 + off - pad) * sr), int((t1 + off + pad) * sr)
    if a < 0 or b > len(yx) or ra < 0 or rb > len(yr) or b - a < sr:
        return None
    hop = int(sr * SYNC_DEFAULTS['hop_s'])
    ex, er = _onset_env(yx[a:b], sr, hop), _onset_env(yr[ra:rb], sr, hop)
    base = int(round(pad * sr / hop))
    lags, rho = _pearson_lags(er, ex, base - int(search_s * sr / hop) - 1, base + int(search_s * sr / hop) + 1,
                              int(0.8 * len(ex)))
    lag, rp, _ = _peak(lags, rho, 50)
    coarse = (ra - a) / sr + lag * hop / sr          # file sample a + i*hop <-> reference sample ra + (i+lag)*hop
    s0 = int(round((a / sr + coarse) * sr))
    seg_r = yr[max(0, s0):max(0, s0) + (b - a)]
    if s0 < 0 or len(seg_r) < b - a:
        return coarse, rp, None
    res, ph = _gcc_phat(seg_r, yx[a:b], int(0.03 * sr), sr)
    return (s0 + res - a) / sr, rp, ph


def sync(files, reference=None, max_offset_s=None, rate=None, near=None, min_overlap_s=None, drift_window_s=None,
         fine_window_s=None):
    """Line up recordings of the same moment by their sound.

    files          the recordings (video or audio files).
    reference      the one the others are measured against (default: the first of `files`).
    max_offset_s   only offsets within this of `near` are considered (default: any with enough overlap).
    rate           analysis sample rate (Hz).
    near           None (search around 0) | 'clock' (around each file's offset from the recording-time metadata;
                   max_offset_s then defaults to 10) | a number of seconds.
    min_overlap_s  least overlap a candidate offset must give. drift_window_s: length of the windows at the start
                   and end of the overlap that drift is measured on (needs 3 windows of overlap).
    fine_window_s  length of the span the waveform refinement uses (middle of the overlap).

    Returns per file: offset_s (reference time = file time + offset_s), strength (Pearson r of the onset
    envelopes at that offset), peak_ratio (strength / best r more than 0.5 s away), waveform_peak (height of the
    phase-correlation peak), the overlap in reference time, drift (offset near the start vs near the end of the
    overlap), and the offset from the recording-time metadata (probe 'created') side by side."""
    import letitedit.server.core_tools as core_tools
    t_start = time.time()
    files = [str(f) for f in files]
    ref = str(reference) if reference else files[0]
    sr = int(rate or SYNC_DEFAULTS['rate'])
    hop = max(1, int(round(sr * SYNC_DEFAULTS['hop_s'])))
    hop_s = hop / sr
    fine_w = float(fine_window_s or SYNC_DEFAULTS['fine_window_s'])
    drift_w = float(drift_window_s or SYNC_DEFAULTS['drift_window_s'])
    if near == 'clock' and max_offset_s is None:
        max_offset_s = SYNC_DEFAULTS['near_max_offset_s']

    def clock_of(path):
        try:
            info = core_tools.probe(path)
        except Exception:  # noqa: BLE001
            return None, None
        return info.get('created'), core_tools.rec_start(info)

    yr = _decode(ref, sr)
    er = _onset_env(yr, sr, hop)
    ref_created, ref_clock = clock_of(ref)
    dur_r = len(yr) / sr
    rows = []
    for f in files:
        if Path(f).resolve() == Path(ref).resolve():
            continue
        row = {'file': f}
        rows.append(row)
        yx = _decode(f, sr)
        dur_x = len(yx) / sr
        row['duration_s'] = _r(dur_x)
        created, clk = clock_of(f)
        clock_off = (clk - ref_clock).total_seconds() if (clk is not None and ref_clock is not None) else None
        row['clock'] = {'created': created, 'reference_created': ref_created, 'offset_s': _r(clock_off)}
        if not yx.size or not np.any(yx):
            row['note'] = 'no sound'
            continue
        ex = _onset_env(yx, sr, hop)
        min_ov = min_overlap_s if min_overlap_s is not None else min(SYNC_DEFAULTS['min_overlap_s'],
                                                                     0.5 * min(dur_x, dur_r))
        min_ov_n = max(4, int(min_ov / hop_s))
        center = 0.0
        if near == 'clock':
            center = clock_off if clock_off is not None else 0.0
        elif near is not None:
            center = float(near)
        lo, hi = -(len(ex) - min_ov_n), len(er) - min_ov_n
        if max_offset_s is not None:
            lo = max(lo, int(math.floor((center - max_offset_s) / hop_s)))
            hi = min(hi, int(math.ceil((center + max_offset_s) / hop_s)))
        if hi < lo:
            row['note'] = 'no offset in the search range gives the minimum overlap'
            continue
        lags, rho = _pearson_lags(er, ex, lo, hi, min_ov_n)
        lag, strength, second = _peak(lags, rho, int(round(0.5 / hop_s)))
        coarse = lag * hop_s
        row.update(envelope_offset_s=_r(coarse, 4), strength=_r(strength, 4),
                   peak_ratio=_r(strength / second, 3) if second and second > 0 else None)
        # waveform refinement on the middle of the overlap
        o0, o1 = max(0.0, -coarse), min(dur_x, dur_r - coarse)
        mid, half = (o0 + o1) / 2, min(fine_w, o1 - o0) / 2 - 0.05
        offset, wpeak = coarse, None
        if half > 0.5:
            a, b = int((mid - half) * sr), int((mid + half) * sr)
            s0 = int(round(a + coarse * sr))
            seg_r = yr[max(0, s0):max(0, s0) + (b - a)]
            if s0 >= 0 and len(seg_r) == b - a:
                res, wpeak = _gcc_phat(seg_r, yx[a:b], int(3 * hop), sr)
                offset = (s0 + res - a) / sr
        o0, o1 = max(0.0, -offset), min(dur_x, dur_r - offset)
        row.update(offset_s=_r(offset, 4), waveform_peak=_r(wpeak, 4),
                   overlap_s=[_r(o0 + offset), _r(o1 + offset)],
                   meaning='reference time = file time + offset_s')
        if row['clock']['offset_s'] is not None:
            row['clock']['minus_sound_s'] = _r(clock_off - offset)
        # drift: windows at the start and end of the overlap
        if o1 - o0 >= 3 * drift_w:
            first = _local_offset(yr, yx, sr, offset, o0 + 0.5, o0 + 0.5 + drift_w, 1.0)
            last = _local_offset(yr, yx, sr, offset, o1 - 0.5 - drift_w, o1 - 0.5, 1.0)
            if first and last:
                span = (o1 - 0.5 - drift_w / 2) - (o0 + 0.5 + drift_w / 2)
                d = last[0] - first[0]
                row['drift'] = {'offset_at_start_s': _r(first[0], 4), 'start_window_file_s': [_r(o0 + 0.5), _r(o0 + 0.5 + drift_w)],
                                'offset_at_end_s': _r(last[0], 4), 'end_window_file_s': [_r(o1 - 0.5 - drift_w), _r(o1 - 0.5)],
                                'drift_s': _r(d, 4), 'ppm': _r(d / span * 1e6, 1) if span > 0 else None,
                                'strength_start': _r(first[1], 3), 'strength_end': _r(last[1], 3)}
            else:
                row['drift'] = None
        else:
            row['drift'] = None
            row['drift_note'] = f'overlap {o1 - o0:.1f} s is under 3 drift windows ({3 * drift_w:g} s)'
    return {'reference': ref, 'reference_duration_s': _r(dur_r),
            'reference_created': ref_created, 'files': rows,
            'settings': {'rate': sr, 'hop_s': hop_s, 'max_offset_s': max_offset_s, 'near': near,
                         'min_overlap_s': min_overlap_s if min_overlap_s is not None else
                         f"min({SYNC_DEFAULTS['min_overlap_s']:g}, half the shorter file)",
                         'fine_window_s': fine_w, 'drift_window_s': drift_w, 'bands_hz': [list(b) for b in _BANDS]},
            'seconds': _r(time.time() - t_start, 2)}


# ============================================================================ track

TRACK_DEFAULTS = {'max_fps': 30.0, 'analysis_px': 640, 'size': 0.15, 'sheet_frames': 12, 'face_min_score': 0.6}


def _frames(path, start, dur, fps, w, h):
    """BGR frames (h, w, 3) of path from start for dur seconds at fps."""
    cmd = [_ffmpeg(), '-v', 'error', '-nostdin', '-ss', f'{max(0.0, start):.4f}', '-i', str(path), '-t', f'{dur:.4f}',
           '-an', '-sn', '-vf', f'fps={fps:.6f},scale={w}:{h}:flags=area', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    size = w * h * 3
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        proc.wait()


def _faces(img, min_score):
    import cv2
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(str(YUNET), '', (w, h), float(min_score), 0.3, 50)
    _, faces = det.detect(img)
    if faces is None:
        return []
    return [(float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14])) for f in faces]


def _track_start_box(target, frame, size, face_min_score, aw, ah, folder, start):
    """The target's box on the first analysed frame (the largest face, a box, or a box around a point), in
    analysed pixels."""
    import cv2
    if isinstance(target, str):
        if target.lower() != 'face':
            raise ValueError("target is [x0, y0, x1, y1], [x, y] or 'face'")
        ms = float(face_min_score if face_min_score is not None else TRACK_DEFAULTS['face_min_score'])
        faces = _faces(frame, ms)
        if not faces:
            p = folder / f'start-frame-{start:.2f}.jpg'
            cv2.imwrite(str(p), frame)
            raise ValueError(f'no face found at {start:.2f} s (YuNet, score >= {ms}); the frame: {p}')
        x, y, w, h, sc = max(faces, key=lambda f: f[2] * f[3])
        box = (x, y, x + w, y + h)
        tgt_desc = {'kind': 'face', 'face_score': _r(sc, 3), 'faces_found': len(faces), 'face_min_score': ms}
    elif len(target) == 4:
        x0, y0, x1, y1 = [float(v) for v in target]
        box = (x0 * aw, y0 * ah, x1 * aw, y1 * ah)
        tgt_desc = {'kind': 'box'}
    elif len(target) == 2:
        cx, cy = float(target[0]) * aw, float(target[1]) * ah
        sz = size if size is not None else TRACK_DEFAULTS['size']
        if isinstance(sz, (list, tuple)):
            bw, bh = float(sz[0]) * aw, float(sz[1]) * ah
        else:
            bw = bh = float(sz) * min(aw, ah)
        box = (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
        tgt_desc = {'kind': 'point', 'size': sz}
    else:
        raise ValueError("target is [x0, y0, x1, y1], [x, y] or 'face'")
    x0, y0 = max(0.0, min(box[0], box[2])), max(0.0, min(box[1], box[3]))
    x1, y1 = min(float(aw), max(box[0], box[2])), min(float(ah), max(box[1], box[3]))
    if x1 - x0 < 4 or y1 - y0 < 4:
        raise ValueError('the target box is under 4 analysed pixels; give a bigger box or analysis_px')
    return x0, y0, x1, y1, tgt_desc


def _track_sheet(kept, all_rows, aw, ah, folder, file, start, end):
    """The check sheet: the kept frames with their boxes drawn, six to a row, saved as a JPEG (None when no
    frame is kept)."""
    import cv2
    # sheet
    sheet_path = None
    if kept:
        tiles = []
        th = 320
        for i in sorted(kept):
            img = kept[i].copy()
            r = all_rows[i]
            p0 = (int(r[1] * aw), int(r[2] * ah))
            p1 = (int(r[3] * aw), int(r[4] * ah))
            cv2.rectangle(img, p0, p1, (0, 0, 0), 4)
            cv2.rectangle(img, p0, p1, (40, 230, 255), 2)
            scale = th / img.shape[0]
            img = cv2.resize(img, (max(1, int(img.shape[1] * scale)), th), interpolation=cv2.INTER_AREA)
            band = np.full((26, img.shape[1], 3), 24, np.uint8)
            cv2.putText(band, f'{r[0]:.2f}s  {r[5]:.2f}', (4, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1,
                        cv2.LINE_AA)
            tiles.append(np.vstack([band, img]))
        per_row = min(6, len(tiles))
        tw = max(t.shape[1] for t in tiles)
        rows_img = []
        for j in range(0, len(tiles), per_row):
            chunk = tiles[j:j + per_row]
            chunk = [np.hstack([c, np.full((c.shape[0], tw - c.shape[1] + 4, 3), 16, np.uint8)]) for c in chunk]
            while len(chunk) < per_row:
                chunk.append(np.full_like(chunk[0], 16))
            rows_img.append(np.hstack(chunk))
        sheet = np.vstack(rows_img)
        sheet_path = folder / f'track-{Path(file).stem}-{start:.2f}-{end:.2f}.jpg'
        cv2.imwrite(str(sheet_path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return sheet_path


def track(file, start, end, target, every_s=None, size=None, out_dir=None, analysis_fps=None, analysis_px=None,
          sheet_frames=None, face_min_score=None):
    """Follow something through file[start:end] with OpenCV's VitTrack (vittrack_2023sep.onnx).

    target          [x0, y0, x1, y1] box in 0-1 fractions of the picture at `start`; or [x, y] a point (a box of
                    `size` around it); or 'face' (the largest YuNet face at `start`).
    every_s         time between returned samples (default: every analysed frame).
    size            box around a point target: a fraction of the picture's shorter side, or [w, h] fractions of
                    its width and height.
    analysis_fps    frames analysed per second (default: the file's rate, at most 30, adjusted so a frame falls on
                    every `every_s`). analysis_px: long side of the
                    analysed picture. sheet_frames: frames on the check sheet. face_min_score: YuNet threshold.
    out_dir         where the sheet and the box list are saved (default a new temp folder).

    Returns columns [t, x0, y0, x1, y1, score] per sample (file seconds; 0-1 fractions of the displayed picture;
    score = the tracker's confidence; on a frame it reports the target lost, the last box it gave is repeated and
    the time is listed in `lost`), the start box, the sheet
    path (frames with the boxes drawn) and a JSON file with every analysed frame's box."""
    import cv2
    import letitedit.server.core_tools as core_tools
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:  # noqa: BLE001
        pass
    t_start = time.time()
    file = str(file)
    info = core_tools.probe(file)
    W, H = int(info.get('width') or 0), int(info.get('height') or 0)
    if not W or not H:
        raise ValueError(f'{file} has no picture')
    start, end = _sec(start), _sec(end)
    dur_file = float(info.get('duration') or 0)
    if end is None or end > dur_file:
        end = dur_file
    if not (0 <= start < end):
        raise ValueError(f'start/end must satisfy 0 <= start < end <= {dur_file:.3f}')
    src_fps = float(info.get('fps') or 30.0)
    fps = float(analysis_fps or min(src_fps, TRACK_DEFAULTS['max_fps']))
    if every_s and not analysis_fps:              # analyse on a rate that has a frame at every sample time
        fps = max(1, round(fps * float(every_s))) / float(every_s)
    px = int(analysis_px or TRACK_DEFAULTS['analysis_px'])
    k = px / max(W, H)
    aw, ah = max(2, int(round(W * k / 2)) * 2), max(2, int(round(H * k / 2)) * 2)
    step = float(every_s) if every_s else 1.0 / fps
    n_sheet = int(sheet_frames if sheet_frames is not None else TRACK_DEFAULTS['sheet_frames'])
    folder = _out_dir('track', out_dir)
    expected = max(1, int(math.floor((end - start) * fps + 1e-6)))
    sheet_idx = set(np.linspace(0, expected - 1, min(n_sheet, expected)).round().astype(int).tolist()) if n_sheet else set()

    all_rows, lost, kept = [], [], {}
    tracker, init_box, tgt_desc = None, None, None
    for i, frame in enumerate(_frames(file, start, end - start, fps, aw, ah)):
        t = start + i / fps
        if i == 0:
            x0, y0, x1, y1, tgt_desc = _track_start_box(target, frame, size, face_min_score, aw, ah, folder,
                start)
            params = cv2.TrackerVit_Params()
            params.net = str(VITTRACK)
            tracker = cv2.TrackerVit.create(params)
            tracker.init(frame, (int(round(x0)), int(round(y0)), int(round(x1 - x0)), int(round(y1 - y0))))
            init_box = (x0, y0, x1, y1)
            row = [t, x0 / aw, y0 / ah, x1 / aw, y1 / ah, 1.0]
        else:
            ok, b = tracker.update(frame)
            score = float(tracker.getTrackingScore())
            bx0, by0, bw, bh = [float(v) for v in b]
            if ok and bw > 0 and bh > 0:
                row = [t, bx0 / aw, by0 / ah, (bx0 + bw) / aw, (by0 + bh) / ah, score]
            else:                                   # lost: the last box it reported, with this frame's score
                row = [t, *all_rows[-1][1:5], score]
                lost.append(_r(t))
        all_rows.append(row)
        if i in sheet_idx:
            kept[i] = frame
    if not all_rows:
        raise ValueError(f'no frames decoded from {file} at {start}-{end}')

    samples, nxt = [], start
    for row in all_rows:
        if row[0] >= nxt - 1e-6:
            samples.append(row)
            nxt += step
    fmt = [[_r(r[0], 3)] + [_r(v, 4) for v in r[1:5]] + [_r(r[5], 3)] for r in samples]

    sheet_path = _track_sheet(kept, all_rows, aw, ah, folder, file, start, end)
    json_path = folder / f'track-{Path(file).stem}-{start:.2f}-{end:.2f}.json'
    json_path.write_text(json.dumps({'file': file, 'columns': ['t', 'x0', 'y0', 'x1', 'y1', 'score'],
                                     'frames': [[_r(r[0], 4)] + [_r(v, 5) for v in r[1:5]] + [_r(r[5], 4)]
                                                for r in all_rows]}), encoding='utf-8')
    return {
        'file': file, 'start': _r(start), 'end': _r(end),
        'target': {**(tgt_desc or {}), 'given': target,
                   'box': [_r(init_box[0] / aw, 4), _r(init_box[1] / ah, 4), _r(init_box[2] / aw, 4),
                           _r(init_box[3] / ah, 4)]},
        'columns': ['t', 'x0', 'y0', 'x1', 'y1', 'score'], 'boxes': fmt, 'lost': lost,
        'frames_analysed': len(all_rows),
        'settings': {'every_s': _r(step, 4), 'analysis_fps': _r(fps, 3), 'source_fps': src_fps,
                     'analysis_size': [aw, ah], 'source_size': [W, H], 'size': size if size is not None else
                     TRACK_DEFAULTS['size'], 'sheet_frames': n_sheet,
                     'tracker': 'OpenCV TrackerVit', 'model': str(VITTRACK),
                     'tracking_score_threshold': _r(cv2.TrackerVit_Params().tracking_score_threshold, 3)},
        'sheet': str(sheet_path) if sheet_path else None, 'json': str(json_path),
        'seconds': _r(time.time() - t_start, 2),
    }


# ============================================================================ bin (markers + subclips in the .mlt)

MARKERS_PROP = 'shotcut:markers'          # Shotcut: kShotcutMarkersProperty, on the main tractor
BIN_ID = 'main_bin'                       # Shotcut: kPlaylistTrackId (the Playlist panel)
CAPTION, COMMENT, FOLDER = 'shotcut:caption', 'shotcut:comment', 'shotcut:bins'
PICK_ID, PICK_COLOR = 'letitedit_ai:bin_id', 'letitedit_ai:color'
DEFAULT_MARKER_COLOR = '#008000'          # Shotcut's default marker colour ("green")
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.webp', '.heic'}


def _p_get(el, name, default=None):
    for p in el.findall('property'):
        if p.get('name') == name:
            return p.text or ''
    return default


def _p_set(el, name, value):
    for p in el.findall('property'):
        if p.get('name') == name:
            p.text = str(value)
            return
    p = ET.Element('property', {'name': name})
    p.text = str(value)
    kids = list(el)
    first = next((i for i, c in enumerate(kids) if c.tag != 'property'), None)
    if first is None:
        el.append(p)
    else:
        el.insert(first, p)


def _color(c):
    if c is None:
        return DEFAULT_MARKER_COLOR
    from PIL import ImageColor
    rgb = ImageColor.getrgb(str(c))
    return '#{:02X}{:02X}{:02X}'.format(*rgb[:3])


def _clock(frames, fps):
    import letitedit.timeline.timeline_model as tm
    return tm.frames_to_clock(frames, fps)      # as the engine writes it, so it reads back as the same frame


def _frames_of(value, fps):
    import letitedit.timeline.timeline_model as tm
    return tm.clock_to_frames(value, fps)


class _Project:
    def __init__(self, path):
        self.path = Path(path)
        self.tree = ET.parse(self.path)
        self.root = self.tree.getroot()
        prof = self.root.find('profile')
        self.fps = (int(prof.get('frame_rate_num', 30)) / int(prof.get('frame_rate_den', 1))) if prof is not None else 30.0
        tractors = [e for e in self.root if e.tag == 'tractor']
        marked = [t for t in tractors if _p_get(t, 'shotcut') == '1']
        if not tractors:
            raise ValueError(f'{path} has no timeline (tractor)')
        self.main = (marked or tractors)[-1]

    def by_id(self):
        return {e.get('id'): e for e in self.root if e.get('id')}

    def bin(self, create=False):
        el = next((e for e in self.root if e.tag == 'playlist' and e.get('id') in (BIN_ID, 'main bin')), None)
        if el is None and create:
            el = ET.Element('playlist', {'id': BIN_ID})
            _p_set(el, 'xml_retain', 1)
            prof = self.root.find('profile')
            self.root.insert(list(self.root).index(prof) + 1 if prof is not None else 0, el)
        if el is not None and create and _p_get(el, 'xml_retain') is None:
            _p_set(el, 'xml_retain', 1)
        return el

    def markers_el(self, create=False):
        el = next((c for c in self.main.findall('properties') if c.get('name') == MARKERS_PROP), None)
        if el is None and create:
            el = ET.Element('properties', {'name': MARKERS_PROP})
            kids = list(self.main)
            first = next((i for i, c in enumerate(kids) if c.tag not in ('property', 'properties')), len(kids))
            self.main.insert(first, el)
        return el


def _resolve_media(proj, res):
    if not res:
        return res
    p = Path(res)
    if p.is_absolute():
        return str(p)
    root = proj.root.get('root') or str(proj.path.parent)
    return str(Path(root) / p)


def _read_bin(proj):
    fps = proj.fps
    markers = []
    mel = proj.markers_el()
    if mel is not None:
        for m in mel.findall('properties'):
            s, e = _frames_of(_p_get(m, 'start'), fps), _frames_of(_p_get(m, 'end'), fps)
            markers.append({'id': f"marker-{m.get('name')}", 'text': _p_get(m, 'text', ''),
                            'start': _r((s or 0) / fps), 'end': _r((e if e is not None else s or 0) / fps),
                            'color': _p_get(m, 'color'), 'frames': [s, e]})
    markers.sort(key=lambda m: (m['start'], m['id']))
    clips, folders = [], []
    bl = proj.bin()
    ids = proj.by_id()
    if bl is not None:
        fol = next((c for c in bl.findall('properties') if c.get('name') == FOLDER), None)
        if fol is not None:
            folders = [p.text or '' for p in fol.findall('property') if not (p.get('name') or '').startswith(('_', '.'))]
        for i, e in enumerate(x for x in bl if x.tag in ('entry', 'blank')):
            if e.tag == 'blank':
                continue
            prod = ids.get(e.get('producer'))
            if prod is None:
                clips.append({'index': i, 'id': None, 'producer': e.get('producer'), 'note': None,
                              'missing_producer': True})
                continue
            a = _frames_of(e.get('in'), fps)
            b = _frames_of(e.get('out'), fps)
            if a is None:
                a = _frames_of(prod.get('in'), fps) or 0
            if b is None:
                b = _frames_of(prod.get('out'), fps) or 0
            res = (_p_get(prod, 'shotcut:resource') or _p_get(prod, 'warp_resource') or _p_get(prod, 'resource'))
            clips.append({'index': i, 'id': _p_get(prod, PICK_ID) or prod.get('id'), 'producer': prod.get('id'),
                          'name': _p_get(prod, CAPTION) or (Path(res).name if res else prod.get('id')),
                          'file': _resolve_media(proj, res), 'in': _r(a / fps), 'out': _r((b + 1) / fps),
                          'len': _r((b - a + 1) / fps), 'note': _p_get(prod, COMMENT),
                          'folder': _p_get(prod, FOLDER), 'color': _p_get(prod, PICK_COLOR)})
    return markers, clips, folders


def _new_bin_chain(proj, item, used_ids):
    import letitedit.timeline.edit_script as es
    fps = proj.fps
    f = item.get('file') or item.get('clip')
    if not f:
        raise ValueError('a bin item needs file')
    f = str(f)
    if not Path(f).is_file():
        raise FileNotFoundError(f)
    pid = None
    while pid is None or pid in used_ids:
        pid = f'binclip{uuid.uuid4().hex[:6]}'
    used_ids.add(pid)
    name = item.get('name') or Path(f).name
    if Path(f).suffix.lower() in IMAGE_EXT:
        el = ET.Element('producer', {'id': pid, 'in': '0', 'out': '1079999'})
        props = [('length', 1080000), ('eof', 'pause'), ('resource', f), ('ttl', 1), ('aspect_ratio', 1),
                 ('progressive', 1), ('seekable', 1), ('mlt_service', 'qimage')]
        total = None
    else:
        info = es.probe(f)
        total = int(round(info['duration'] * fps))
        el = ET.Element('chain', {'id': pid, 'out': str(max(0, total - 1))})
        props = [('length', total), ('eof', 'pause'), ('resource', f), ('mlt_service', 'avformat-novalidate'),
                 ('seekable', 1), ('audio_index', info['audio_index']), ('video_index', info['video_index']),
                 ('mute_on_pause', 0)]
    props.append((CAPTION, name))
    if item.get('note'):
        props.append((COMMENT, item['note']))
    if item.get('folder'):
        props.append((FOLDER, item['folder']))
    if item.get('color') is not None:
        props.append((PICK_COLOR, _color(item['color'])))
    pick = item.get('id') or f'pick-{uuid.uuid4().hex[:6]}'
    props.append((PICK_ID, pick))
    for k, v in props:
        _p_set(el, k, v)
    a = int(round((_sec(item.get('in')) or 0.0) * fps))
    out_s = _sec(item.get('out'))
    if out_s is None:
        out_s = (total / fps) if total else (_sec(item.get('len')) or 5.0) + a / fps
    b = int(round(out_s * fps)) - 1
    if total:
        b = min(b, total - 1)
    if b < a:
        raise ValueError(f'{name}: out must be after in')
    entry = ET.Element('entry', {'producer': pid, 'in': _clock(a, fps), 'out': _clock(b, fps)})
    return el, entry, pick, (a, b)


def _melt_check(path, timeout=180):
    """melt loads the project and plays its first frames; returns (ok, messages)."""
    try:
        r = subprocess.run([str(MELT), '-quiet', str(path), 'out=1', '-consumer', 'null'], capture_output=True,
                           text=True, errors='replace', timeout=timeout, cwd=str(Path(path).parent),
                           creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, ['melt timed out']
    msgs = [ln.strip() for ln in (r.stdout + r.stderr).splitlines() if ln.strip()]
    bad = [m for m in msgs if 'failed' in m.lower() or 'error' in m.lower()]
    return r.returncode == 0 and not bad, msgs[-12:]


def _melt_bin_check(proj, fps):
    """melt reads the bin playlist on its own (as the root producer): returns (frames melt counts, frames written)."""
    bl = proj.bin()
    if bl is None:
        return None, 0
    ids = proj.by_id()
    doc = ET.Element('mlt', {'LC_NUMERIC': 'C'})
    prof = proj.root.find('profile')
    if prof is not None:
        doc.append(prof)
    want = 0
    pl = ET.Element('playlist', {'id': 'bin_check'})
    seen = set()
    for e in bl.findall('entry'):
        prod = ids.get(e.get('producer'))
        if prod is None:
            continue
        if prod.get('id') not in seen:
            seen.add(prod.get('id'))
            doc.append(prod)
        pl.append(e)
        a, b = _frames_of(e.get('in'), fps), _frames_of(e.get('out'), fps)
        want += (b - a + 1) if (a is not None and b is not None) else 0
    if not len(pl):
        return 0, 0
    doc.append(pl)
    tmp = Path(tempfile.gettempdir()) / f'letitedit_ai_bincheck_{uuid.uuid4().hex[:8]}.mlt'
    ET.ElementTree(doc).write(tmp, encoding='utf-8', xml_declaration=True)
    try:
        r = subprocess.run([str(MELT), '-quiet', str(tmp), '-consumer', 'xml'], capture_output=True, text=True,
                           errors='replace', timeout=120, creationflags=NO_WINDOW, cwd=str(proj.path.parent))
        got = None
        try:
            out = ET.fromstring(r.stdout[r.stdout.find('<mlt'):]) if '<mlt' in r.stdout else None
            if out is not None:
                tr = out.find('tractor')
                if tr is not None:
                    got = _frames_of(tr.get('out'), fps) + 1
        except ET.ParseError:
            got = None
        return got, want
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _live(path):
    try:
        import letitedit.app.letitedit_instances as inst
        for r in inst.list_instances():
            if r.get('project') and Path(r['project']).resolve() == Path(path).resolve():
                return r
    except Exception:  # noqa: BLE001 - no editor running is normal
        return None
    return None


def _bin_remove(proj, remove, removed, unmatched):
    """Removes the markers and bin items named (by id, text or name), then producers only the bin used."""
    names = [str(x) for x in (remove if isinstance(remove, (list, tuple)) else [remove])]
    mk, clips, _ = _read_bin(proj)
    mel = proj.markers_el()
    bl = proj.bin()
    ids = proj.by_id()
    entries = [x for x in bl if x.tag in ('entry', 'blank')] if bl is not None else []
    for nm in names:
        hit = False
        for m in mk:
            if nm in (m['id'], m['text']) and mel is not None:
                key = m['id'].split('-', 1)[1]
                el = next((x for x in mel.findall('properties') if x.get('name') == key), None)
                if el is not None:
                    mel.remove(el)
                    removed.append({'marker': m['id'], 'text': m['text'], 'start': m['start']})
                    hit = True
        for c in clips:
            if bl is not None and c.get('id') is not None and nm in (c['id'], c.get('name'), c.get('producer')):
                el = entries[c['index']] if c['index'] < len(entries) else None
                if el is not None and any(x is el for x in bl):
                    bl.remove(el)
                    removed.append({'bin': c['id'], 'name': c.get('name')})
                    hit = True
        if not hit:
            unmatched.append(nm)
    # drop producers nothing references any more (only ones the bin used)
    if bl is not None:
        refs = {e.get('producer') for e in proj.root.iter('entry')} | {t.get('producer') for t in proj.root.iter('track')}
        for c in clips:
            pid = c.get('producer')
            if pid and pid not in refs and pid in ids and ids[pid] in list(proj.root):
                proj.root.remove(ids[pid])


def _bin_add_markers(proj, markers, fps, added):
    """Adds timeline markers (at, or start and end; snapped to frames) under the first free keys."""
    mel = proj.markers_el(create=True)
    keys = {int(x.get('name')) for x in mel.findall('properties') if str(x.get('name')).isdigit()}
    for m in markers:
        if 'at' in m:
            s = e = _sec(m['at'])
        else:
            s = _sec(m.get('start'))
            e = _sec(m.get('end', s))
        if s is None:
            raise ValueError('a marker needs at, or start (and end)')
        fs, fe = int(round(s * fps)), int(round(e * fps))
        if fe < fs:
            fs, fe = fe, fs
        key = 0
        while key in keys:
            key += 1
        keys.add(key)
        el = ET.SubElement(mel, 'properties', {'name': str(key)})
        col = _color(m.get('color'))
        for k, v in (('text', m.get('text', '')), ('start', _clock(fs, fps)), ('end', _clock(fe, fps)),
                     ('color', col)):
            _p_set(el, k, v)
        added.append({'marker': f'marker-{key}', 'text': m.get('text', ''), 'start': _r(fs / fps),
                      'end': _r(fe / fps), 'color': col})


def _bin_add_items(proj, add, fps, added):
    """Adds subclips to the editor's bin (and their folders to its folder list)."""
    bl = proj.bin(create=True)
    used = set(proj.by_id())
    for item in add:
        chain, entry, pick, (a, b) = _new_bin_chain(proj, item, used)
        proj.root.insert(list(proj.root).index(bl), chain)
        bl.append(entry)
        if item.get('folder'):
            fol = next((c for c in bl.findall('properties') if c.get('name') == FOLDER), None)
            if fol is None:
                fol = ET.Element('properties', {'name': FOLDER})
                kids = list(bl)
                first = next((i for i, c in enumerate(kids) if c.tag not in ('property', 'properties')), len(kids))
                bl.insert(first, fol)
            have = [p.text for p in fol.findall('property')]
            if item['folder'] not in have:
                nums = [int(p.get('name')) for p in fol.findall('property') if str(p.get('name')).isdigit()]
                _p_set(fol, str(max(nums, default=1) + 1), item['folder'])
        added.append({'bin': pick, 'name': _p_get(chain, CAPTION), 'file': item.get('file') or item.get('clip'),
                      'in': _r(a / fps), 'out': _r((b + 1) / fps)})


def _bin_write_checked(path, proj, fps):
    """Writes a copy that must load in melt and in edit_script.read, then replaces the project (the previous
    file kept as .bak)."""
    import letitedit.timeline.edit_script as es
    # write: a copy that must load, then replace (previous file kept as .bak)
    tmp = path.with_name(f'{path.stem}.bin-{uuid.uuid4().hex[:6]}.mlt')
    ET.indent(proj.tree, space='  ')
    proj.tree.write(tmp, encoding='utf-8', xml_declaration=True)
    checks = {}
    try:
        ok, msgs = _melt_check(tmp)
        checks['melt'] = {'ok': ok, 'messages': msgs}
        try:
            es.read(tmp)
            checks['edit_script_read'] = {'ok': True}
        except Exception as ex:  # noqa: BLE001
            checks['edit_script_read'] = {'ok': False, 'error': f'{type(ex).__name__}: {ex}'}
        got, want = _melt_bin_check(_Project(tmp), fps)
        checks['melt_bin'] = {'ok': got == want if want else True, 'frames_melt': got, 'frames_written': want}
        if not (ok and checks['edit_script_read']['ok'] and checks['melt_bin']['ok']):
            raise RuntimeError(f'the changed project did not pass its checks; nothing was replaced: {checks}')
        backup = path.with_name(path.name + '.bak')
        shutil.copy2(path, backup)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return checks, backup


def bin(project, add=None, markers=None, remove=None, refuse=None):  # noqa: A001 - the tool's name
    """Picks and notes stored inside the project (.mlt), where a person sees them in letitedit.

    add      [{file, in, out, name, note, color, folder}, ...]: subclips in the editor's bin (the Playlist panel:
             name = its caption, note = its Comment column, folder = a Playlist bin; color is kept for readers here
             - the editor does not draw it).
    markers  [{at | start, end, text, color}, ...]: timeline markers (the editor's Markers panel and ruler); times are
             timeline seconds (snapped to frames); color: '#rrggbb' or a colour name (default the editor's green).
    remove   ids or names/texts of markers and bin items to delete.
    refuse   None, or refuse(path) -> None or why: asked before a change to bin items or folders is written (raised
             as ValueError); a change to markers alone never asks. A markers-only change in an open window is
             journalled with markers_only=True.
    No arguments: read only (everything in the file, including what a person added in letitedit).

    Writes go to a copy that must load in melt and in edit_script.read before it replaces the project; the
    previous file is kept as <project>.bak. Returns the markers, bin items and folders after the change, what
    changed, and the checks."""
    import letitedit.timeline.edit_script as es
    t_start = time.time()
    path = es._resolve(project)
    live = _live(path)
    read, source = {'state': 'saved'}, path
    if live:     # the window as it is now, unsaved changes and the person's own markers included (T298)
        import letitedit.app.live_edit as live_edit
        source, rev = live_edit.snapshot(live['instance_id'])
        read = live_edit.state_of(live, rev)
    proj = _Project(source)
    fps = proj.fps
    changing = bool(add or markers or remove)
    result = {'project': str(path), 'fps': _r(fps, 4), 'read': read}
    if not changing:
        m, c, f = _read_bin(proj)
        result.update(markers=m, bin=c, folders=f, seconds=_r(time.time() - t_start, 2))
        return result

    def edit(pr):
        added, removed, unmatched = [], [], []
        if remove:      # remove first (so a remove + add of the same name replaces)
            _bin_remove(pr, remove, removed, unmatched)
        if markers:
            _bin_add_markers(pr, markers, fps, added)
        if add:
            _bin_add_items(pr, add, fps, added)
        return added, removed, unmatched

    _, bin_before, folders_before = _read_bin(proj)
    added, removed, unmatched = edit(proj)
    m, c, f = _read_bin(proj)
    if (c, f) != (bin_before, folders_before) and refuse is not None:
        why = refuse(path)          # bin items or folders change: the caller's hand-over rule (markers alone never)
        if why:
            raise ValueError(why)
    if live and (c, f) == (bin_before, folders_before):
        # markers only: into the window as one undo step, nothing saved or reloaded (the editor's set_markers)
        done = _bin_markers_live(path, live, proj, fps)
        if done is not None:
            missing = sorted({x['file'] for x in c if x.get('file') and not Path(x['file']).exists()})
            result.update(markers=m, bin=c, folders=f, added=added, removed=removed, not_found=unmatched,
                          missing_files=missing, **done)
            result['seconds'] = _r(time.time() - t_start, 2)
            return result
    if live and live.get('modified'):
        raise ValueError("This project is open in letitedit with unsaved changes, and bin items (subclips and folders) "
                         "go into the saved file. Save it in letitedit (or ask the user to), then call again, so "
                         "nobody's work is overwritten. Markers alone go into the open window as one undo step.")
    if live:
        proj = _Project(path)     # the saved file (the window has no unsaved changes): the edit again, on it
        added, removed, unmatched = edit(proj)

    checks, backup = _bin_write_checked(path, proj, fps)
    m, c, f = _read_bin(_Project(path))
    missing = sorted({x['file'] for x in c if x.get('file') and not Path(x['file']).exists()})
    result.update(markers=m, bin=c, folders=f, added=added, removed=removed, not_found=unmatched,
                  backup=str(backup), checks=checks, missing_files=missing)
    if live:
        try:
            from letitedit.app.letitedit_client import ShotcutBridge
            import letitedit.app.letitedit_instances as inst
            with inst.scope(live['instance_id']), ShotcutBridge(timeout=60) as b:
                b.call('open', {'path': str(path)})
            result['editor'] = f"reloaded the open project in letitedit ({live['instance_id']})"
        except Exception as ex:  # noqa: BLE001
            result['editor'] = f'open in letitedit ({live["instance_id"]}); reload failed: {ex}'
    result['seconds'] = _r(time.time() - t_start, 2)
    return result


FOLLOW_LABEL = 'markers follow'     # the undo step a marker retime makes in an open window: '<prefix>: markers follow'


def retime_markers(project, retime, actor=None, saved_only=False):
    """Move or remove timeline markers by a rule, keeping each marker's text and colour (T345: markers that follow
    their clips through an edit). retime(markers) gets the markers as letitedit_bin lists them ([{id, text, start, end,
    color}], seconds, the open window's when it is open) and returns (moves, remove): moves {id: (start_s, end_s)},
    remove [ids]. Nothing to do: None. An open window gets the whole list as one undo step named
    '<prefix>: markers follow' (nothing saved or reloaded); a saved file is written checked, as letitedit_bin writes
    it, with no history copy of its own (undoing the edit before it restores the markers too). Returns
    {'moved', 'removed', 'where'} or None. saved_only: the saved file even when a window has it open (the caller
    reloads the window after)."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.project_journal as pj
    path = es._resolve(project)
    live = None if saved_only else _live(path)
    source = path
    if live:
        import letitedit.app.live_edit as live_edit
        source = live_edit.snapshot(live['instance_id'])[0]
    proj = _Project(source)
    fps = proj.fps
    moved, removed = _retime(proj, fps, *retime(_read_bin(proj)[0]))
    if not moved and not removed:
        return None
    if live:
        who = pj.actor(actor)
        done = _bin_markers_live(path, live, proj, fps, actor=actor, label=f'{pj.label_prefix(who)}: {FOLLOW_LABEL}')
        if done is not None:
            return {'moved': moved, 'removed': removed, 'where': done.get('editor'), 'undo_label': done.get('undo_label')}
        if live.get('modified'):
            return None                 # an older window build with unsaved changes: the markers stay where they are
        proj = _Project(path)           # an older window build: the saved file, as letitedit_bin writes it
        moved, removed = _retime(proj, fps, *retime(_read_bin(proj)[0]))
        if not moved and not removed:
            return None
    _bin_write_checked(path, proj, fps)
    return {'moved': moved, 'removed': removed, 'where': str(path)}


def followed_rows(source, retime):
    """The timeline's whole marker list after a rule, without writing anything (T356: the markers an open window's
    apply carries in its own undo step). source: a project file (the window's snapshot); retime as retime_markers
    takes it. Returns {'rows': [{text, start, end, color}] in frames, as the editor's set_markers and
    apply_transaction take them, 'moved', 'removed'}, or None when nothing moves."""
    proj = _Project(source)
    fps = proj.fps
    moved, removed = _retime(proj, fps, *retime(_read_bin(proj)[0]))
    if not moved and not removed:
        return None
    return {'rows': _marker_rows(proj, fps), 'moved': moved, 'removed': removed}


def _marker_rows(proj, fps):
    """`proj`'s timeline markers as the editor takes them: [{text, start, end, color}], frames."""
    mel = proj.markers_el()
    rows = []
    for el in (mel.findall('properties') if mel is not None else []):
        s = _frames_of(_p_get(el, 'start'), fps) or 0
        e = _frames_of(_p_get(el, 'end'), fps)
        rows.append({'text': _p_get(el, 'text', '') or '', 'start': int(s), 'end': int(e if e is not None else s),
                     'color': _p_get(el, 'color') or DEFAULT_MARKER_COLOR})
    return rows


def _retime(proj, fps, moves, remove):
    """Moves (by id: (start_s, end_s)) and removes (ids) markers in `proj`. Returns (moved, removed)."""
    remove = set(remove or [])
    mel = proj.markers_el()
    by_key = {f"marker-{el.get('name')}": el for el in (mel.findall('properties') if mel is not None else [])}
    moved = removed = 0
    for mid, (s, e) in (moves or {}).items():
        el = by_key.get(mid)
        if el is None or mid in remove:
            continue
        fs, fe = int(round(float(s) * fps)), int(round(float(e) * fps))
        _p_set(el, 'start', _clock(min(fs, fe), fps))
        _p_set(el, 'end', _clock(max(fs, fe), fps))
        moved += 1
    for mid in remove:
        el = by_key.get(mid)
        if el is not None:
            mel.remove(el)
            removed += 1
    return moved, removed


def _bin_markers_live(path, live, proj, fps, actor=None, label=None):
    """The timeline's marker list as `proj` has it, put into the open window as one undo step under the same edit
    lease as letitedit_timeline_apply (T298). Returns the reply's extra fields, or None when the window's build can't
    take markers (an older build: the caller writes the saved file as before). label: the undo step's name
    [<actor's prefix>: markers]."""
    import letitedit.app.live_edit as live_edit
    import letitedit.timeline.project_journal as pj
    rows = _marker_rows(proj, fps)
    who = pj.actor(actor)
    label = label or f'{pj.label_prefix(who)}: markers'
    try:
        with pj.writing(path, who) as lease:
            got = live_edit.set_markers(live['instance_id'], rows, label)
    except ValueError as exc:
        if "can't take markers" in str(exc):
            return None
        raise
    where = f"letitedit window {live['instance_id']}"
    pj.record(path, 'apply', who, label, None, where=where, hand_checked=True, markers_only=True)
    saved = live_edit.own_save(live, path, who)     # the Studio's own window only, never a person's
    out = {'editor': f"markers went into the open letitedit window ({live['instance_id']}) as one undo step "
                     f"({label}); nothing was saved or reloaded", 'undo_label': label, 'lease': lease,
           'live': {'changed': bool((got or {}).get('changed', True)), 'markers': len(rows)}}
    if saved.get('save_failed'):                    # said in the reply and the journal, never silent (T329)
        out.update(save_failed=saved['save_failed'], note=live_edit.save_note(saved))
    return out
