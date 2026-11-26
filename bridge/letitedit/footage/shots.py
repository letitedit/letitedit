"""Shot boundaries that camera moves do not fool: hard cuts, punch-ins, dissolves and fades, frame-accurate.

    detect(video, start=None, end=None, settings=None, kinds=None) -> {cuts, shots, camera_moves, rejected, ...}
    cut_times(video, settings=None, kinds=None) -> [seconds]
    features(video, start=None, end=None, settings=None) -> per-frame measurements (cached), used by detect and by
        range_search (residual motion inside a region, camera speed)
    scene_scores(video, start, end) -> ffmpeg's scene score per frame, exactly as the older method computes it (cached)
    picture_area(video) -> [x, y, w, h] of the picture inside black bars or a blurred copy of itself, else None (cached)
    ffmpeg_cuts(video, cut_above=0.15) -> the older method's cut times (reference.scene_cuts), for comparison
    evaluate(found, truth, fps, tol_frames) -> precision / recall numbers

How it works (every number is in `settings` and reported with each result):

1. Every frame is decoded once at a small size (long side `analysis_px`, default 192; above `max_fps` frames are
   decimated, and a cut found there is re-measured at the full rate around it). With `picture_area: 'auto'` only the
   picture is measured when the rest of the frame is a fixed surround (black bars, or a blurred copy of the picture
   beside or above and below it, as Blur: Pad makes): picture_area() finds it from the fine detail per column and row
   of frames spread over the video. Without it such a surround hides cuts and punch-ins (it looks the same on both
   sides of every cut).
2. For each pair of consecutive frames the camera move between them is estimated: corners (Shi-Tomasi) are tracked
   with pyramidal Lucas-Kanade both ways, and a similarity transform (shift, zoom, roll) is fitted with RANSAC; phase
   correlation (shift only) and no move at all are also tried. The earlier frame is warped by each, and the best
   normalised cross-correlation (NCC, -1..1, insensitive to brightness and contrast changes) over the overlap is the
   pair's similarity. `d = 1 - similarity` is the change the camera move does not explain. The frame is also split
   into 4x4 cells: the share of cells whose pattern (NCC) or level (plain cells) changed.
3. Where a pair looks like a break (d high, few tracked corners, or a big colour-histogram change), the frames on
   each side are compared across it: up to 3 frames before against up to 3 after, each pair with its own camera
   estimate. A pair whose estimate is trusted and whose cells mostly match means the picture continues (motion blur,
   a flash, a dropped frame): not a cut.
4. A hard cut must: change at least `min_d` after compensation and at least `min_cells` of the cells (cells that
   barely change all video long, e.g. a graphic side panel, are left out); stand out from its neighbourhood (d >=
   `adaptive_ratio` x the median d within `window_s` and `min_delta` above it, or for a big change `strong_d`,
   `strong_ratio`, `strong_delta`); change the colours (`low_hist`) unless d is large; not be a whip (boundary frames
   blurred under `whip_blur` of the sharpest nearby while the camera moves `whip_speed` frame widths per second or
   more); and make ffmpeg's scene score pass `require_scene_score` within 2 frames (an abrupt jump in the plain
   frame difference, a second independent view). Frames with a luma spread under `low_texture_std` only cut with
   a colour change of `low_texture_min_hist`.
5. Punch-ins (a reframe of the same picture: zoom or shift in one frame step while the frames around are calm) are
   kind 'punch' (an edit point that is not a change of view; `kinds` decides whether they count).
6. Dissolves: the picture `far_s` before and after is compared after the camera moves between them are undone; where
   it differs a lot while no single frame does, the middle frame is tested as a blend a*before + (1-a)*after; a run
   of frames that fit a blend is kind 'dissolve' (start and end frames). Fades: digitally flat frames (luma spread
   under `flat_std`: black, white, one colour) and the ramp into and out of them are kind 'fade'.
7. Two boundaries closer than `min_shot_s`: the stronger is kept. `occlusion_reach_s` (off by default) also drops a
   cut whose earlier picture comes back within that time.

Data only, no verdicts beyond the cut list: `rejected` lists the places that looked like a break in one measure and
why they were not counted (camera move, picture continued, part of the frame, whip, no scene-score jump...), with
their measures, so a caller can set its own thresholds. Per-frame values are cached under
<cache>\\range-search\\shots\\ by file content and settings.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1
FEATURE_VERSION = 4          # bump when the per-frame measurements change (part of the cache key)
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'range-search' / 'shots'
APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))
FFMPEG, FFPROBE = APP / 'ffmpeg.exe', APP / 'ffprobe.exe'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# measuring (part of the per-frame cache key)
FEATURE_DEFAULTS = {
    'analysis_px': 192,       # long side of the decoded analysis frames
    'max_fps': 60.0,          # frames above this rate are decimated (every k-th frame) for the first pass
    'corners': 160,           # Shi-Tomasi corners tracked per frame pair
    'ransac_px': 1.5,         # RANSAC reprojection threshold (analysis pixels)
    'min_inliers': 10,        # fewer agreeing corners than this: the camera estimate is not trusted
    'grid': 4,                # residual-motion grid (grid x grid cells) kept per frame
    'far_s': 0.5,             # dissolve test: frames this far before and after are compared
    'suspect_d': 0.12,        # pairs with d over this (or the other suspect signs) get the cross-boundary check
    'segment_s': 40.0,        # long files are measured in parallel pieces of about this length
    'workers': 6,             # parallel pieces / files
    'picture_area': None,     # None: the whole frame; 'auto': only the picture when the rest of the frame is bars or
                              # a blurred copy of it (picture_area()); [x, y, w, h]: that part of the frame
}
# finding the picture inside a fixed surround (picture_area)
PICTURE_AREA = {
    'samples': 24,            # frames spread over the video
    'px': 320,                # long side they are measured at
    'detail': 0.3,            # a column (row) is picture with at least this share of the frame's typical detail
    'side': 0.25,             # ... and the surround has at most this share of the picture's detail
    'agree': 0.75,            # ... in at least this share of the frames that are not flat
    'min_side': 0.04,         # a surround thinner than this share of the frame is not one
    'balance': 0.6,           # bars and Blur: Pad are centred: the thinner side is at least this share of the other
    'min_band': 0.15,         # a picture narrower than this share of the frame is not believed
    'inset': 0.01,            # the picture found is shrunk by this share of the frame each side (its soft edge)
}
# deciding (cheap, from the cached per-frame values)
DETECT_DEFAULTS = {
    'min_d': 0.30,            # a cut's change after camera compensation (1 - NCC) is at least this
    'adaptive_ratio': 3.0,    # ... and this many times the median change around it
    'min_delta': 0.20,        # ... and at least this much above that median
    'window_s': 0.5,          # neighbourhood each side for that median
    'min_cells': 0.5,         # ... and at least this share of the 4x4 cells changed (a caption, hand or flash: few)
    'static_mad': 1.5,        # cells whose change stays under this (0-255) in 90% of frames are a fixed layout part
                              # (a graphic side panel): left out of that share
    'strong_d': 0.55,         # a change this big needs only strong_ratio x the median around it
    'strong_ratio': 2.0,      # (and strong_delta above it): cuts in fast-cut, busy stretches
    'strong_delta': 0.30,
    'low_hist': 0.10,         # a cut whose colour histogram changes less than this needs d >= low_hist_min_d
    'low_hist_min_d': 0.8,    # (0 = off)
    'whip_blur': 0.12,        # a whip, not a cut: the boundary frames' sharpness is under this share of the sharpest
    'whip_speed': 0.8,        # nearby frame and the camera moves at least this many frame widths per second around
                              # it (coarse phase correlation, median of +-0.3 s); 0 = off
    'require_scene_score': 0.15,  # a hard cut / punch-in must also make ffmpeg's scene score pass this within 2
                                  # frames (the older method's measure, as a second view; 0 = off)
    'occlusion_reach_s': 0.0,  # a 'cut' whose earlier picture comes back within this is something passing in front
                               # of the lens or a look away and back (0 = off; a jump cut with the same framing
                               # also comes back, so it is not counted either)
    'low_texture_std': 6.0,   # frames with a luma spread under this (dark, misty, plain) are only cut from or into
    'low_texture_min_hist': 0.3,  # with a colour histogram change of at least this
    'min_shot_s': 0.15,       # two cuts closer than this: the stronger one is kept
    'punch_zoom': 0.06,       # a one-step zoom of at least 6% (or a shift of punch_shift of the width) ...
    'punch_shift': 0.10,
    'punch_calm': 0.015,      # ... while the steps around it zoom/shift less than this: a punch-in
    'punch_min_sim': 0.80,    # ... and the reframed picture matches (NCC after compensation)
    'punch_min_inliers': 18,  # ... on this many agreeing corners (25 until 2026-10-29: footage framed over a blurred
                              # copy of itself has corners only in the sharp band; 18 found 4 of 6 labelled punch-ins
                              # instead of 3, with the same false cuts on the edits, raw and hold-out clips)
    'punch_min_raw': 0.15,    # ... while the picture without compensation changed this much (0.30 until 2026-10-29:
    'punch_raw_ratio': 4.0,   # a 12% punch-in on soft or framed footage changes it 0.16-0.29) and this many times the
                              # median change of the steps around it
    'punch_scene_score': 0.10,  # a punch-in's ffmpeg scene score must pass this within 2 frames (never more than
                                # require_scene_score, which a cut's must pass; that one at 0 turns both off)
    'dissolve_far_d': 0.45,   # dissolve: frames far_s apart differ at least this much (after compensation)
    'dissolve_fit': 0.55,     # ... the middle frame fits a blend of them this much better than either alone
    'dissolve_min_frames': 4,
    'flat_std': 1.0,          # a frame whose luma spread is under this is flat (black, white, one colour): fades
    'kinds': ['cut', 'punch', 'dissolve', 'fade'],
}


def _settings(defaults, given):
    out = dict(defaults)
    for k, v in (given or {}).items():
        if k in defaults and v is not None:
            out[k] = v
    return out


def _hash(obj, n=10):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:n]


def content_key(path):
    try:
        import letitedit.footage.footage_notes as footage_notes
        return footage_notes.key(path)
    except Exception:  # noqa: BLE001 - footage_notes unavailable: size + first 2 MB
        st = os.stat(path)
        h = hashlib.sha1()
        with open(path, 'rb') as fh:
            h.update(fh.read(2 * 1024 * 1024))
        return f'{st.st_size}-{h.hexdigest()[:16]}'


# ------------------------------------------------------------------ probing and decoding

_PROBES = {}


def probe(path):
    """{w, h, fps (nominal r_frame_rate), avg_fps, duration, start_time, frames, rotation, codec}. Display size:
    rotation is applied (w, h are as shown)."""
    path = str(path)
    st = os.stat(path)
    memo = (path.lower(), st.st_size, st.st_mtime_ns)
    if memo in _PROBES:
        return _PROBES[memo]
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,codec_name,start_time:'
                        'stream_side_data=rotation:format=duration,start_time', '-of', 'json', path],
                       capture_output=True, text=True, errors='replace', creationflags=NO_WINDOW)
    j = json.loads(r.stdout or '{}')
    s = (j.get('streams') or [{}])[0]
    if not s.get('width'):
        raise ValueError(f'no video stream: {path}')

    def rate(x):
        try:
            a, b = str(x).split('/')
            return float(a) / float(b) if float(b) else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0
    rot = 0
    for sd in s.get('side_data_list') or []:
        if 'rotation' in sd:
            rot = int(round(float(sd['rotation'])))
    w, h = int(s['width']), int(s['height'])
    if abs(rot) % 180 == 90:
        w, h = h, w
    fps = rate(s.get('r_frame_rate')) or rate(s.get('avg_frame_rate')) or 30.0
    if fps > 240:                       # some phones write a timebase-like r_frame_rate
        fps = rate(s.get('avg_frame_rate')) or 30.0
    info = {'w': w, 'h': h, 'fps': fps, 'avg_fps': rate(s.get('avg_frame_rate')) or fps,
            'duration': float((j.get('format') or {}).get('duration') or 0.0),
            'start_time': float(s.get('start_time') or (j.get('format') or {}).get('start_time') or 0.0),
            'frames': int(s['nb_frames']) if str(s.get('nb_frames') or '').isdigit() else None,
            'rotation': rot, 'codec': s.get('codec_name')}
    _PROBES[memo] = info
    return info


def analysis_size(info, px):
    s = float(px) / max(info['w'], info['h'])
    return max(16, int(round(info['w'] * s / 2)) * 2), max(16, int(round(info['h'] * s / 2)) * 2)


AREA = CACHE / 'area'


def _area_frames(video, info, n, px):
    """Grey frames (float32) at `n` times spread over the video, long side `px`."""
    sw, sh = analysis_size(info, px)
    dur = max(0.0, float(info['duration']))

    def one(k):
        r = subprocess.run([str(FFMPEG), '-v', 'error', '-ss', f'{dur * (k + 0.5) / n:.3f}', '-i', str(video),
                            '-frames:v', '1', '-vf', f'scale={sw}:{sh}:flags=area', '-f', 'rawvideo', '-pix_fmt',
                            'gray', '-'], capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        if len(r.stdout) < sw * sh:
            return None
        return np.frombuffer(r.stdout[:sw * sh], np.uint8).reshape(sh, sw).astype(np.float32)
    with ThreadPoolExecutor(2) as ex:
        return [g for g in ex.map(one, range(n)) if g is not None], (sw, sh)


def _band(prof, p):
    """(a, b) (b exclusive) of the picture along one axis of the sample frames, from per-frame detail profiles
    (frames x positions); None when the picture spans the axis or the sides are not a plain or blurred surround."""
    n = prof.shape[1]
    med = np.median(prof / np.maximum(1e-6, np.percentile(prof, 90, axis=1, keepdims=True)), axis=0)
    idx = np.flatnonzero(med >= float(p['detail']))
    if not len(idx):
        return None
    gap = max(1, int(round(0.05 * n)))       # a dark or plain patch inside the picture does not split it
    runs, a, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > gap:
            runs.append((a, prev + 1))
            a = i
        prev = i
    runs.append((a, prev + 1))
    a, b = max(runs, key=lambda r: r[1] - r[0])
    thin, thick = sorted((a, n - b))
    if b - a < float(p['min_band']) * n or thin < float(p['min_side']) * n or thin < float(p['balance']) * thick:
        return None
    side = np.zeros(n, bool)
    side[:a] = True
    side[b:] = True
    edge = max(1, int(round(0.01 * n)))      # the picture's own edge is not the surround
    side[max(0, a - edge):a] = False
    side[b:b + edge] = False
    if not side.any():
        return None
    ok = prof[:, side].mean(axis=1) <= float(p['side']) * np.maximum(1e-6, prof[:, a:b].mean(axis=1))
    return (int(a), int(b)) if ok.mean() >= float(p['agree']) else None


def picture_area(video, info=None, refresh=False):
    """[x, y, w, h] (displayed pixels) of the picture when the rest of the frame is a fixed surround that is not part
    of it: bars of one colour (letterbox, pillarbox) or a blurred copy of the picture beside or above and below it
    (Blur: Pad); None when the picture fills the frame. Measured on PICTURE_AREA['samples'] frames spread over the
    video: per column (row), the mean difference to the next pixel (fine detail). The picture is the widest run of
    columns (rows) with at least `detail` of the frame's typical detail; it counts when what lies beside it has at
    most `side` of the picture's detail in at least `agree` of the frames. Cached per file content."""
    video = str(Path(video).resolve())
    info = info or probe(video)
    p = PICTURE_AREA
    cf = AREA / f'{content_key(video)}-a{_hash(p, 8)}.json'
    if not refresh:
        try:
            return json.loads(cf.read_text(encoding='utf-8-sig'))['area']
        except (OSError, ValueError, KeyError):
            pass
    frames, (sw, sh) = _area_frames(video, info, int(p['samples']), int(p['px']))
    frames = [g for g in frames if g.std() >= 4.0]       # black or flat frames (fades) say nothing
    area = None
    if len(frames) >= 3:
        cols = np.array([np.r_[d, d[-1]] for d in (np.abs(np.diff(g, axis=1)).mean(axis=0) for g in frames)])
        rows = np.array([np.r_[d, d[-1]] for d in (np.abs(np.diff(g, axis=0)).mean(axis=1) for g in frames)])
        bx, by = _band(cols, p), _band(rows, p)
        if bx or by:
            W, H = info['w'], info['h']
            x0, x1 = (bx[0] * W / sw + p['inset'] * W, bx[1] * W / sw - p['inset'] * W) if bx else (0.0, float(W))
            y0, y1 = (by[0] * H / sh + p['inset'] * H, by[1] * H / sh - p['inset'] * H) if by else (0.0, float(H))
            x, y = int(x0) // 2 * 2, int(y0) // 2 * 2
            area = [x, y, int(x1 - x) // 2 * 2, int(y1 - y) // 2 * 2]
    try:
        AREA.mkdir(parents=True, exist_ok=True)
        tmp = cf.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
        tmp.write_text(json.dumps({'video': video, 'area': area, 'frame': [info['w'], info['h']], 'settings': p}),
                       encoding='utf-8')
        os.replace(tmp, cf)
    except OSError:
        pass
    return area


def _crop_for(video, info, spec):
    """The part of the frame to measure: None (whole frame), from picture_area() for 'auto', or the given box."""
    if spec is None or spec is False:
        return None
    if spec == 'auto':
        return picture_area(video, info)
    if isinstance(spec, (list, tuple)) and len(spec) == 4:
        x, y, w, h = (int(round(float(v))) for v in spec)
        if w >= 16 and h >= 16 and x >= 0 and y >= 0 and x + w <= info['w'] and y + h <= info['h']:
            return [x, y, w, h]
    raise ValueError(f"picture_area is None, 'auto' or [x, y, w, h] inside the {info['w']}x{info['h']} frame "
                     f"(got {spec!r})")


_SHOWINFO = re.compile(r'\bn:\s*(\d+)\b.*?\bpts_time:\s*([-+0-9.eE]+|nan)')


def decode(path, w, h, start=None, dur=None, step=1, threads=2, crop=None):
    """Yield (t, Y, U, V) for each decoded frame of [start, start + dur) (seconds from the file's start, frame
    presentation times), every `step`-th frame, as yuv420p planes at w x h. crop: [x, y, w, h] of the displayed frame
    to keep before scaling."""
    args = [str(FFMPEG), '-hide_banner', '-nostdin', '-v', 'info', '-threads', str(int(threads))]
    if start:
        args += ['-ss', f'{max(0.0, float(start)):.4f}']
    args += ['-i', str(path)]
    if dur is not None:
        args += ['-t', f'{max(0.01, float(dur)):.4f}']
    vf = ([f"select='not(mod(n\\,{int(step)}))'"] if step > 1 else []) + ['showinfo'] + (
        [f'crop={int(crop[2])}:{int(crop[3])}:{int(crop[0])}:{int(crop[1])}'] if crop else []) + [
        f'scale={w}:{h}:flags=area']
    args += ['-an', '-sn', '-dn', '-vf', ','.join(vf), '-fps_mode', 'passthrough', '-f', 'rawvideo',
             '-pix_fmt', 'yuv420p', '-']
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW,
                         stdin=subprocess.DEVNULL)
    times, cond, done = [], threading.Condition(), [False]

    def read_err():
        for raw in p.stderr:
            line = raw.decode('utf-8', 'replace')
            if 'Parsed_showinfo' in line and 'pts_time' in line:
                m = _SHOWINFO.search(line)
                if m:
                    with cond:
                        try:
                            times.append(float(m.group(2)))
                        except ValueError:
                            times.append(float('nan'))
                        cond.notify_all()
        with cond:
            done[0] = True
            cond.notify_all()
    th = threading.Thread(target=read_err, daemon=True)
    th.start()
    ysz, csz = w * h, (w // 2) * (h // 2)
    size = ysz + 2 * csz
    t0 = float(start or 0.0)
    i = 0
    try:
        while True:
            buf = p.stdout.read(size)
            if not buf or len(buf) < size:
                break
            with cond:
                while len(times) <= i and not done[0]:
                    cond.wait(5)
                t = times[i] if len(times) > i else float('nan')
            i += 1
            if t != t:
                continue
            a = np.frombuffer(buf, np.uint8)
            yield (t0 + t, a[:ysz].reshape(h, w), a[ysz:ysz + csz].reshape(h // 2, w // 2),
                   a[ysz + csz:].reshape(h // 2, w // 2))
    finally:
        try:
            p.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        if p.poll() is None:
            p.kill()
        p.wait()
        th.join(timeout=5)


# ------------------------------------------------------------------ pair measurements

_I23 = np.float32([[1, 0, 0], [0, 1, 0]])


def _hist(y, u, v):
    hy = np.bincount((y >> 3).ravel(), minlength=32).astype(np.float32)
    hu = np.bincount((u >> 4).ravel(), minlength=16).astype(np.float32)
    hv = np.bincount((v >> 4).ravel(), minlength=16).astype(np.float32)
    return hy / hy.sum(), hu / hu.sum(), hv / hv.sum()


def _hist_d(a, b):
    return float(np.mean([0.5 * np.abs(x - y).sum() for x, y in zip(a, b)]))


def _ncc(a, b):
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    a -= a.mean()
    b -= b.mean()
    den = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum() / den) if den > 1e-6 else 0.0


class _Pair:
    """Camera estimate and similarity between two analysis frames."""
    __slots__ = ('M', 'how', 'sim', 'sim_raw', 'n_feat', 'n_trk', 'n_inl', 'mad', 'grid', 'cells', 'resp',
                 'trusted', 'cbits', 'cvalid')


def _corners(g, n):
    import cv2
    return cv2.goodFeaturesToTrack(g, maxCorners=int(n), qualityLevel=0.01, minDistance=5, blockSize=5)


CELLS = 4          # cells per side for 'how much of the picture changed'


def _cells_changed(wa, b, mask):
    """Share (0-1) of the CELLS x CELLS cells whose content changed between b and warped a: a textured cell changed
    when its NCC is under 0.5, a flat one when its mean moved by more than 12 levels. Cells mostly outside the
    overlap do not count. A cut changes nearly every cell; a caption, a hand or a flash changes a few."""
    h, w = b.shape
    ch, cw = h // CELLS, w // CELLS
    A = wa[:ch * CELLS, :cw * CELLS].astype(np.float32).reshape(CELLS, ch, CELLS, cw).transpose(0, 2, 1, 3)
    B = b[:ch * CELLS, :cw * CELLS].astype(np.float32).reshape(CELLS, ch, CELLS, cw).transpose(0, 2, 1, 3)
    A = A.reshape(CELLS * CELLS, -1)
    B = B.reshape(CELLS * CELLS, -1)
    if mask is not None:
        Mk = mask[:ch * CELLS, :cw * CELLS].reshape(CELLS, ch, CELLS, cw).transpose(0, 2, 1, 3)
        Mk = Mk.reshape(CELLS * CELLS, -1)
        valid = Mk.mean(axis=1) >= 0.6
        A = np.where(Mk, A, np.nan)
        B = np.where(Mk, B, np.nan)
    else:
        valid = np.ones(CELLS * CELLS, bool)
    if not valid.any():
        return 1.0, 0, 0
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        ma, mb = np.nanmean(A, axis=1), np.nanmean(B, axis=1)
        da, db = A - ma[:, None], B - mb[:, None]
        sa, sb = np.sqrt(np.nanmean(da * da, axis=1)), np.sqrt(np.nanmean(db * db, axis=1))
        cov = np.nanmean(da * db, axis=1)
        mad = np.nanmean(np.abs(A - B), axis=1)
    textured = (sa > 6) & (sb > 6)
    ncc = np.where(textured, cov / np.maximum(sa * sb, 1e-6), 1.0)
    # textured cells: the pattern changed (NCC); plain cells: the levels changed (mean abs difference)
    changed = np.where(textured, ncc < 0.5, mad > 10)
    changed = changed | ((sa > 6) != (sb > 6)) & (np.abs(sa - sb) > 6)
    bits = int(sum(1 << int(k) for k in np.flatnonzero(changed & valid)))
    vbits = int(sum(1 << int(k) for k in np.flatnonzero(valid)))
    return float(changed[valid].mean()), bits, vbits


def _overlap_sim(a, b, M, border=3, grid=0, cells=False):
    """NCC (and mean abs difference, a grid of mean abs differences, the share of cells that changed) between b and
    a warped by M, over the part of b that a covers (minus a border)."""
    import cv2
    h, w = b.shape
    if M is None:
        wa, mask = a, None
    else:
        wa = cv2.warpAffine(a, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        mask = cv2.warpAffine(np.full((h, w), 255, np.uint8), M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        if border:
            mask = cv2.erode(mask, np.ones((2 * border + 1, 2 * border + 1), np.uint8))
        mask = mask > 0
        if mask.sum() < 0.25 * h * w:
            return 0.0, 255.0, None, float(mask.mean()), (1.0, 0, 0)
    if mask is None:
        x, y = wa.astype(np.float32), b.astype(np.float32)
        cover = 1.0
    else:
        x, y = wa[mask].astype(np.float32), b[mask].astype(np.float32)
        cover = float(mask.mean())
    sim = _ncc(x, y)
    mad = float(np.abs(x - y).mean())
    gr = None
    if grid:
        diff = np.abs(wa.astype(np.float32) - b.astype(np.float32))
        if mask is not None:
            diff[~mask] = np.nan
        gh, gw = h // grid, w // grid
        cl = diff[:gh * grid, :gw * grid].reshape(grid, gh, grid, gw)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            gr = np.nanmean(cl, axis=(1, 3)).reshape(-1)
        gr = np.nan_to_num(gr, nan=0.0)
    ch = _cells_changed(wa, b, mask) if cells else None
    return sim, mad, gr, cover, ch


def measure_pair(a, b, st, pts=None, grid=0):
    """_Pair for frames a -> b (uint8 grey). pts: corners of a (found when None). trusted: the camera estimate rests
    on enough agreeing corners (or a clear phase-correlation peak, or no move at all)."""
    import cv2
    out = _Pair()
    out.n_feat = out.n_trk = out.n_inl = 0
    out.resp = 0.0
    if pts is None:
        pts = _corners(a, st['corners'])
    best = None
    cands = []
    if pts is not None and len(pts) >= 8:
        out.n_feat = len(pts)
        p1, s1, _ = cv2.calcOpticalFlowPyrLK(a, b, pts, None, winSize=(15, 15), maxLevel=3)
        p0b, s2, _ = cv2.calcOpticalFlowPyrLK(b, a, p1, None, winSize=(15, 15), maxLevel=3)
        fb = np.linalg.norm((pts - p0b).reshape(-1, 2), axis=1)
        ok = (s1.reshape(-1) == 1) & (s2.reshape(-1) == 1) & (fb < 1.0)
        out.n_trk = int(ok.sum())
        if out.n_trk >= 6:
            M, inl = cv2.estimateAffinePartial2D(pts[ok], p1[ok], method=cv2.RANSAC,
                                                 ransacReprojThreshold=float(st['ransac_px']), maxIters=500)
            if M is not None:
                out.n_inl = int(inl.sum()) if inl is not None else 0
                if out.n_inl >= 4:
                    cands.append((M.astype(np.float32), 1))
    if not cands or out.n_inl < st['min_inliers']:
        try:
            (dx, dy), resp = cv2.phaseCorrelate(a.astype(np.float32), b.astype(np.float32))
            out.resp = float(resp)
            if resp > 0.05:
                cands.append((np.float32([[1, 0, dx], [0, 1, dy]]), 2))
        except cv2.error:
            pass
    cands.append((None, 0))
    raw = None
    for M, how in cands:
        sim, mad, gr, cover, _ = _overlap_sim(a, b, M, grid=grid)
        if how == 0:
            raw = sim
        if best is None or sim > best[0] + 1e-6:
            best = (sim, mad, gr, M, how)
    out.sim, out.mad, out.grid, out.M, out.how = best[0], best[1], best[2], best[3], best[4]
    out.sim_raw = raw if raw is not None else best[0]
    out.cells, out.cbits, out.cvalid = _overlap_sim(a, b, out.M, cells=True)[4]
    if out.how == 1:
        out.trusted = out.n_inl >= int(st['min_inliers']) and out.n_inl >= 0.4 * max(1, out.n_trk)
    elif out.how == 2:
        out.trusted = out.resp >= 0.15
    else:
        out.trusted = True
    if out.grid is None and grid:
        out.grid = np.zeros(grid * grid, np.float32)
    return out


def _mparams(M, w):
    """(dx, dy) as fractions of the frame width, zoom (scale), roll (radians) of a 2x3 similarity (None: zero)."""
    if M is None:
        return 0.0, 0.0, 1.0, 0.0
    a, b = float(M[0, 0]), float(M[1, 0])
    return float(M[0, 2]) / w, float(M[1, 2]) / w, math.hypot(a, b), math.atan2(b, a)


def _to3(M):
    out = np.eye(3, dtype=np.float64)
    if M is not None:
        out[:2] = M
    return out


# ------------------------------------------------------------------ per-frame features

FIELDS = ('t', 'luma', 'std', 'sharp', 'hd', 'sim', 'sim_raw', 'how', 'n_feat', 'n_trk', 'n_inl', 'dx', 'dy', 'zoom',
          'roll', 'mad', 'cells', 'cmask', 'cvalid', 'resp', 'trusted', 'pc_dx', 'pc_dy', 'pc_resp', 'xsim', 'xcells',
          'far_sim', 'blend_fit', 'blend_a')


def _cross_boundary_check(r, i, base, absn, rows, frame, st):
    """Frame i's similarity across a suspected boundary: the best trusted pair of frames before i against
    frames from i on."""
    if r.get('suspect'):
        best, best_cells = r['sim'], r['cells']
        for a in range(i - 1, max(base, i - 3) - 1, -1):
            for b in range(i, min(absn, i + 2) + 1):
                if a == i - 1 and b == i:
                    continue
                if rows.get(b, {}).get('flat') or rows.get(a, {}).get('flat'):
                    continue
                pr = measure_pair(frame(a), frame(b), st)
                # continuity only from a pair whose camera estimate is trusted and whose cells mostly match
                if pr.trusted and pr.cells <= 0.5 and pr.sim > best:
                    best, best_cells = pr.sim, pr.cells
        r['xsim'], r['xcells'] = best, best_cells
    else:
        r['xsim'], r['xcells'] = r['sim'], r['cells']


def _dissolve_check(r, i, far, base, absn, rows, ring_m3, frame):
    """Dissolve test for frame i: frame i-far against i+far after the chained camera moves, then how well
    frame i fits a blend of the two."""
    import cv2
    a, b = i - far, i + far
    if a >= base and b <= absn and not rows[i].get('flat'):
        chain = np.eye(3)
        ok = True
        for k in range(a + 1, b + 1):
            pk = ring_m3[k - base]
            if pk is None:
                ok = False
                break
            chain = pk @ chain
        fa, fb, fm = frame(a), frame(b), frame(i)
        if ok:
            Mab = chain[:2].astype(np.float32)
            sim_ab, _, _, cover, _ = _overlap_sim(fa, fb, Mab)
            r['far_sim'] = sim_ab
            if sim_ab < 1.0 - float(DETECT_DEFAULTS['dissolve_far_d']) + 0.15:
                # blend test in frame i's coordinates
                ca = np.eye(3)
                for k in range(a + 1, i + 1):
                    ca = ring_m3[k - base] @ ca
                cb = np.eye(3)
                for k in range(i + 1, b + 1):
                    cb = ring_m3[k - base] @ cb
                try:
                    cbi = np.linalg.inv(cb)
                except np.linalg.LinAlgError:
                    cbi = np.eye(3)
                H, W = fm.shape
                wa = cv2.warpAffine(fa, ca[:2].astype(np.float32), (W, H), borderValue=0).astype(np.float32)
                wb = cv2.warpAffine(fb, cbi[:2].astype(np.float32), (W, H), borderValue=0).astype(np.float32)
                ma = cv2.warpAffine(np.full((H, W), 255, np.uint8), ca[:2].astype(np.float32), (W, H)) > 0
                mb = cv2.warpAffine(np.full((H, W), 255, np.uint8), cbi[:2].astype(np.float32), (W, H)) > 0
                m = ma & mb
                if m.sum() > 0.3 * H * W:
                    x, y, z = wa[m], wb[m], fm[m].astype(np.float32)
                    dxy = x - y
                    den = float((dxy * dxy).sum())
                    if den > 1e-3:
                        al = float(((z - y) * dxy).sum() / den)
                        al_c = min(1.0, max(0.0, al))
                        res = z - (al_c * x + (1 - al_c) * y)
                        e_blend = float(np.sqrt((res * res).mean()))
                        e_a = float(np.sqrt(((z - x) ** 2).mean()))
                        e_b = float(np.sqrt(((z - y) ** 2).mean()))
                        r['blend_fit'] = e_blend / max(1e-3, min(e_a, e_b))
                        r['blend_a'] = al
        else:
            r['far_sim'] = np.nan


def _segment_features(path, info, w, h, st, start, dur, step, lead_frames, emit_from, emit_to):
    """Features of the frames with emit_from <= t < emit_to (decoding starts lead_frames before emit_from)."""
    import cv2
    fps_a = info['fps'] / step
    far = max(2, int(round(float(st['far_s']) * fps_a)))
    look = max(3, far)
    ring_y, ring_hist, ring_t, ring_pair, ring_m3 = [], [], [], [], []        # recent frames (look * 2 + 2)
    cols = {k: [] for k in FIELDS}
    grids = []
    G = int(st['grid'])
    suspect_d = float(st['suspect_d'])
    keep = 2 * look + 3
    pending = []          # indices (into the ring's absolute numbering) whose window tests wait for later frames
    base = 0              # absolute index of ring[0]
    absn = -1
    rows = {}             # absolute index -> dict of that frame's values (until emitted)

    def emit(i):
        r = rows.pop(i)
        if not (emit_from - 1e-6 <= r['t'] < emit_to - 1e-6):
            return
        for k in FIELDS:
            cols[k].append(r.get(k, np.nan))
        grids.append(r.get('grid', np.zeros(G * G, np.float32)))

    def frame(i):
        return ring_y[i - base]

    def window_tests(i):
        """Cross-boundary check and dissolve test for frame i (all of i-look .. i+look are in the ring)."""
        r = rows[i]
        # cross-boundary: frames before i against frames from i on, each pair with its own camera estimate
        _cross_boundary_check(r, i, base, absn, rows, frame, st)
        # dissolve: frame i-far vs i+far after the chained camera moves between them
        _dissolve_check(r, i, far, base, absn, rows, ring_m3, frame)

    pts_prev = None
    coarse_prev = None
    win64 = None
    for t, y, u, v in decode(path, w, h, start, dur, step=step, threads=2, crop=info.get('crop')):
        absn += 1
        hist = _hist(y, u, v)
        yf = y
        std = float(y.std())
        r = {'t': t, 'luma': float(y.mean()), 'std': std, 'flat': std < float(DETECT_DEFAULTS['low_texture_std'])}
        r['sharp'] = float(cv2.Laplacian(y, cv2.CV_32F).var())
        # coarse shift (64 px, blurred): the camera's move even through motion blur
        cs = cv2.GaussianBlur(cv2.resize(y, (max(8, w // 3), max(8, h // 3)), interpolation=cv2.INTER_AREA)
                              .astype(np.float32), (0, 0), 1.0)
        if win64 is None:
            win64 = cv2.createHanningWindow((cs.shape[1], cs.shape[0]), cv2.CV_32F)
        if coarse_prev is not None:
            (cdx, cdy), cresp = cv2.phaseCorrelate(coarse_prev, cs, win64)
            r.update(pc_dx=float(cdx) / cs.shape[1], pc_dy=float(cdy) / cs.shape[1], pc_resp=float(cresp))
        else:
            r.update(pc_dx=0.0, pc_dy=0.0, pc_resp=1.0)
        coarse_prev = cs
        if ring_y:
            prev = ring_y[-1]
            pr = measure_pair(prev, yf, st, pts=pts_prev, grid=G)
            dxn, dyn, zoom, roll = _mparams(pr.M, w)
            r.update(hd=_hist_d(ring_hist[-1], hist), sim=pr.sim, sim_raw=pr.sim_raw, how=pr.how, n_feat=pr.n_feat,
                     n_trk=pr.n_trk, n_inl=pr.n_inl, dx=dxn, dy=dyn, zoom=zoom, roll=roll, mad=pr.mad, grid=pr.grid,
                     cells=pr.cells, cmask=float(pr.cbits), cvalid=float(pr.cvalid), resp=pr.resp,
                     trusted=float(pr.trusted))
            r['suspect'] = ((1 - pr.sim) > suspect_d or r['hd'] > 0.25 or
                            (pr.n_feat >= 30 and pr.n_trk < 0.3 * pr.n_feat))
            ring_pair.append(pr)
            ring_m3.append(_to3(pr.M))
        else:
            r.update(hd=0.0, sim=1.0, sim_raw=1.0, how=0, n_feat=0, n_trk=0, n_inl=0, dx=0.0, dy=0.0, zoom=1.0,
                     roll=0.0, mad=0.0, grid=np.zeros(G * G, np.float32), cells=0.0, cmask=0.0, cvalid=0.0,
                     resp=0.0, trusted=1.0)
            r['suspect'] = False
            ring_pair.append(None)
            ring_m3.append(None)
        r.setdefault('far_sim', np.nan)
        r.setdefault('blend_fit', np.nan)
        r.setdefault('blend_a', np.nan)
        rows[absn] = r
        ring_y.append(yf)
        ring_hist.append(hist)
        ring_t.append(t)
        pts_prev = _corners(yf, st['corners'])
        pending.append(absn)
        while pending and pending[0] + look <= absn:
            i = pending.pop(0)
            if i - look >= base:
                window_tests(i)
            else:
                rows[i]['xsim'], rows[i]['xcells'] = rows[i]['sim'], rows[i]['cells']
            emit(i)
        while len(ring_y) > keep:
            ring_y.pop(0)
            ring_hist.pop(0)
            ring_t.pop(0)
            ring_pair.pop(0)
            ring_m3.pop(0)
            base += 1
    for i in pending:                      # the last frames: no look-ahead
        if 'xsim' not in rows[i]:
            rows[i]['xsim'], rows[i]['xcells'] = rows[i]['sim'], rows[i]['cells']
        emit(i)
    out = {k: np.asarray(v, dtype=np.float64) for k, v in cols.items()}
    out['grid'] = np.asarray(grids, dtype=np.float32).reshape(-1, G * G)
    return out


def _feature_file(path, st, start, end, step, crop=None):
    k = content_key(path)
    key = {'v': FEATURE_VERSION, 'st': {k2: st[k2] for k2 in FEATURE_DEFAULTS if k2 not in ('workers', 'segment_s',
                                                                                          'picture_area')},
           'step': step, 'start': start, 'end': end}
    if crop:                                   # whole-frame measurements keep the keys they always had
        key['crop'] = [int(v) for v in crop]
    return CACHE / f'{k}-f{FEATURE_VERSION}-{_hash(key)}.npz'


def features(video, start=None, end=None, settings=None, refresh=False):
    """Per-frame measurements of video[start:end] (seconds; whole file by default), cached by content + settings.
    Returns {'t', 'luma', 'std', 'sharp', 'hd', 'sim', 'sim_raw', 'how', 'n_feat', 'n_trk', 'n_inl', 'dx', 'dy',
    'zoom', 'roll', 'mad', 'xsim', 'far_sim', 'blend_fit', 'blend_a', 'grid'} arrays (one row per analysed frame;
    values of a frame describe the step from the frame before it) plus 'info', 'size', 'step', 'settings',
    'cache_file', 'took_s'."""
    video = str(Path(video).resolve())
    st = _settings(FEATURE_DEFAULTS, settings)
    info = probe(video)
    crop = _crop_for(video, info, st.get('picture_area'))
    if crop:                                   # measure only the picture (its size drives the analysis size)
        info = {**info, 'w': crop[2], 'h': crop[3], 'crop': crop, 'frame': [info['w'], info['h']]}
    w, h = analysis_size(info, st['analysis_px'])
    step = max(1, int(math.ceil(info['fps'] / float(st['max_fps']) - 1e-6)))
    dur_all = info['duration']
    s0 = max(0.0, float(start or 0.0))
    s1 = min(dur_all, float(end)) if end is not None else dur_all
    if s1 <= s0:
        raise ValueError(f'empty range {s0}-{s1} for {video} ({dur_all:.2f} s)')
    whole = start is None and end is None
    cf = _feature_file(video, st, None if whole else round(s0, 3), None if whole else round(s1, 3), step, crop)
    if cf.exists() and not refresh:
        try:
            with np.load(cf, allow_pickle=False) as z:
                out = {k: z[k] for k in z.files}
            out.update(info=info, size=(w, h), step=step, settings=st, cache_file=str(cf), took_s=0.0, cached=True)
            return out
        except (OSError, ValueError):
            pass
    t0 = time.time()
    fps_a = info['fps'] / step
    far = max(2, int(round(float(st['far_s']) * fps_a)))
    lead = (max(3, far) + 2) / fps_a
    seg = float(st['segment_s'])
    n = max(1, int(math.ceil((s1 - s0) / seg - 0.25)))
    edges = [s0 + (s1 - s0) * i / n for i in range(n + 1)]
    jobs = []
    for i in range(n):
        a, b = edges[i], edges[i + 1]
        ds = max(0.0, a - lead) if i > 0 or start is not None else 0.0
        if i == 0 and start is not None:
            ds = max(0.0, a - lead)
        de = min(dur_all + 1.0, b + lead) if i < n - 1 else (b + lead if end is not None else None)
        jobs.append((ds, None if de is None else de - ds, a if (i > 0 or start is not None) else -1.0,
                     b if i < n - 1 or end is not None else 1e12))
    workers = max(1, min(int(st['workers']), len(jobs)))

    def run(j):
        ds, dd, ef, et = j
        return _segment_features(video, info, w, h, st, ds if ds > 0 else None, dd, step, 0, ef, et)
    if workers == 1:
        parts = [run(j) for j in jobs]
    else:
        with ThreadPoolExecutor(workers) as ex:
            parts = list(ex.map(run, jobs))
    out = {}
    for k in list(FIELDS) + ['grid']:
        out[k] = np.concatenate([p[k] for p in parts]) if parts else np.zeros(0)
    order = np.argsort(out['t'], kind='stable')
    for k in out:
        out[k] = out[k][order]
    if len(out['t']) > 1:                    # pieces overlap by a frame or two: keep the first of equal times
        keep = np.concatenate([[True], np.diff(out['t']) > 0.25 / max(1.0, fps_a)])
        for k in out:
            out[k] = out[k][keep]
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = cf.with_name(cf.stem + f'.{os.getpid()}.{threading.get_ident()}.tmp.npz')
    np.savez_compressed(tmp, **{k: (v.astype(np.float32) if k not in ('t',) else v) for k, v in out.items()})
    os.replace(tmp, cf)
    out.update(info=info, size=(w, h), step=step, settings=st, cache_file=str(cf), took_s=round(time.time() - t0, 2),
               cached=False)
    return out


# ------------------------------------------------------------------ deciding

def _frame_no(t, info):
    return int(round((float(t) - float(info.get('start_time') or 0.0)) * float(info['fps'])))


def _median_around(x, i, w, skip=1):
    lo, hi = max(0, i - w), min(len(x), i + w + 1)
    vals = np.concatenate([x[lo:max(lo, i - skip)], x[min(hi, i + skip + 1):hi]])
    vals = vals[np.isfinite(vals)]
    return float(np.median(vals)) if vals.size else 0.0


def _camera_moves(f, fps_a, min_s=0.4):
    """Spans where the camera moves (pan/tilt from the shift, zoom, roll, shake), from the per-frame estimates."""
    n = len(f['t'])
    if n < 3:
        return []
    dx, dy = np.nan_to_num(f['dx']), np.nan_to_num(f['dy'])
    lz = np.log(np.clip(np.nan_to_num(f['zoom'], nan=1.0), 0.5, 2.0))
    k = max(1, int(round(0.25 * fps_a)))
    ker = np.ones(k) / k

    def smooth(x):
        return np.convolve(x, ker, mode='same')
    sx, sy, sz = smooth(dx) * fps_a, smooth(dy) * fps_a, smooth(lz) * fps_a       # per second
    jit = smooth(np.hypot(dx - smooth(dx), dy - smooth(dy))) * fps_a
    labels = []
    for i in range(n):
        speed = math.hypot(sx[i], sy[i])
        if speed >= 1.0:
            lab = 'whip'
        elif abs(sz[i]) >= 0.08 and abs(sz[i]) * 1.5 >= speed:
            lab = 'zoom in' if sz[i] > 0 else 'zoom out'
        elif speed >= 0.06:
            lab = ('pan ' + ('left' if sx[i] > 0 else 'right')) if abs(sx[i]) >= abs(sy[i]) else \
                ('tilt ' + ('up' if sy[i] > 0 else 'down'))
        elif jit[i] >= 0.15:
            lab = 'shake'
        else:
            lab = None
        labels.append(lab)
    spans = []
    for i, lab in enumerate(labels):
        if spans and spans[-1][2] == lab and i - spans[-1][1] <= max(1, k // 2):
            spans[-1][1] = i
        else:
            spans.append([i, i, lab])
    out = []
    t = f['t']
    for a, b, lab in spans:
        if lab is None or (t[b] - t[a]) < min_s:
            continue
        out.append({'start': round(float(t[a]), 3), 'end': round(float(t[b]), 3), 'kind': lab,
                    'speed_w_per_s': round(float(np.hypot(sx[a:b + 1], sy[a:b + 1]).mean()), 3)})
    return out


def detect(video, start=None, end=None, settings=None, refresh=False, kinds=None):
    """Shot boundaries of `video` (or of video[start:end], seconds) that camera moves do not count as.

    settings: any of FEATURE_DEFAULTS (how frames are measured: analysis_px, max_fps, corners, far_s, picture_area,
    ...) and DETECT_DEFAULTS (how a cut is decided: min_d, adaptive_ratio, min_delta, window_s, min_shot_s, punch_*,
    dissolve_*, flat_std). kinds: which boundaries count as cuts (default ['cut', 'punch', 'dissolve', 'fade']).
    picture_area 'auto': the whole frame is measured and, when picture_area() finds a centred surround (bars or a
    blurred copy of the picture), the picture alone too; a boundary either view finds counts (`view`: 'frame' or
    'picture'), so cuts between framed clips and full-frame cutaways in one edit are both seen.

    Returns {schema_version, video, source_fingerprint, fps, analysed_fps, duration, cuts: [{t, frame, kind, start,
    end, start_frame, end_frame, measures}], shots: [{start, end, start_frame, end_frame}], camera_moves: [{start,
    end, kind}], rejected: [{t, frame, why, measures}], settings, method, unsupported, warnings, picture_area}.
    `t` of a cut is the first frame of the new shot; a gradual one also has start/end (its first and last blended
    frame). measures: d (change after camera compensation, 1 - NCC), d_raw (without compensation), baseline (median
    d around it), ratio, hist (colour histogram change 0-1), inliers (corners that agree on one camera move), zoom,
    shift (fraction of the width)."""
    if (settings or {}).get('picture_area') != 'auto':
        return _detect_view(video, start, end, settings, refresh, kinds)
    whole = _detect_view(video, start, end, {**settings, 'picture_area': None}, refresh, kinds)
    info = probe(str(Path(video).resolve()))
    crop = picture_area(video, info)
    if not crop:
        whole['settings']['picture_area'] = 'auto'
        return whole
    part = _detect_view(video, start, end, {**settings, 'picture_area': crop}, refresh, kinds)
    gap = float(whole['settings']['min_shot_s'])
    cuts = [{**c, 'view': 'frame'} for c in whole['cuts']]
    added = [{**c, 'view': 'picture'} for c in part['cuts'] if all(abs(c['t'] - w['t']) > gap for w in whole['cuts'])]
    cuts = sorted(cuts + added, key=lambda c: c['t'])
    s0, s1 = whole['range']
    fps_a = whole['analysed_fps']
    edges = [s0] + [c['t'] for c in cuts if s0 < c['t'] < s1] + [s1]
    whole.update(cuts=cuts, picture_area=crop,
                 shots=[{'start': round(a, 4), 'end': round(b, 4), 'start_frame': _frame_no(a, info),
                         'end_frame': _frame_no(b, info) - 1, 'seconds': round(b - a, 3)}
                        for a, b in zip(edges, edges[1:]) if b - a > 0.5 / fps_a],
                 picture_view={'area': crop, 'cuts': len(part['cuts']), 'added': len(added),
                               'feature_cache': part['feature_cache'], 'took_s': part['took_s']})
    whole['settings']['picture_area'] = 'auto'
    whole['warnings'] = whole['warnings'] + [w for w in part['warnings'] if w not in whole['warnings']]
    return whole


def _detect_hard_cuts(W, d, d1, events, f, flat, fps_a, info, lowtex, measures, n, pcs, rejected, sharp, st_d,
        t, xcells):
    # hard cuts
    for i in np.flatnonzero((d1 >= float(st_d['min_d']) * 0.8) | (d >= float(st_d['min_d']))):
        if i == 0 or flat[i] or flat[i - 1] or (lowtex[i] and lowtex[i - 1]):
            continue
        base = _median_around(d, i, W, skip=1)
        m = measures(i, base)
        if (lowtex[i] or lowtex[i - 1]) and f['hd'][i] < float(st_d['low_texture_min_hist']):
            rejected.append({'t': round(float(t[i]), 4), 'frame': _frame_no(t[i], info),
                             'why': 'a dark or plain frame on one side and the colours barely change', 'measures': m})
            continue
        if float(st_d['low_hist']) > 0 and f['hd'][i] < float(st_d['low_hist']) and \
                d[i] < float(st_d['low_hist_min_d']):
            rejected.append({'t': round(float(t[i]), 4), 'frame': _frame_no(t[i], info),
                             'why': 'the colours barely change and the change is not large', 'measures': m})
            continue
        if d[i] < float(st_d['min_d']):
            why = 'picture continues: frames on each side of it match (blur, flash or a dropped frame)' \
                if d1[i] >= float(st_d['min_d']) else 'change under min_d'
            rejected.append({'t': round(float(t[i]), 4), 'frame': _frame_no(t[i], info), 'why': why, 'measures': m})
            continue
        if xcells[i] < float(st_d['min_cells']):
            rejected.append({'t': round(float(t[i]), 4), 'frame': _frame_no(t[i], info),
                             'why': 'only part of the picture changed (a caption, a hand, a flash, a moving object)',
                             'measures': m})
            continue
        b2 = max(base, 0.02)
        normal = d[i] >= float(st_d['adaptive_ratio']) * b2 and d[i] - base >= float(st_d['min_delta'])
        strong = (d[i] >= float(st_d['strong_d']) and d[i] >= float(st_d['strong_ratio']) * b2
                  and d[i] - base >= float(st_d['strong_delta']))
        if not (normal or strong):
            rejected.append({'t': round(float(t[i]), 4), 'frame': _frame_no(t[i], info),
                             'why': 'does not stand out from the frames around it (busy or moving stretch)',
                             'measures': m})
            continue
        # a whip: the frames at the boundary are smeared by motion while the camera keeps moving fast around them
        if pcs is not None and float(st_d['whip_speed']) > 0:
            k = max(2, int(round(0.1 * fps_a)))
            nb = [j for j in range(max(1, i - 3 * k), min(n, i + 3 * k + 1)) if abs(j - i) > 1]
            ref = float(np.percentile(sharp[max(0, i - int(fps_a)):min(n, i + int(fps_a))], 90)) + 1e-6
            blur = min(sharp[i - 1], sharp[i]) / ref
            speed = float(np.median(pcs[nb])) * fps_a if nb else 0.0
            m.update(blur_ratio=round(float(blur), 3), camera_speed_w_per_s=round(speed, 2))
            if blur < float(st_d['whip_blur']) and speed >= float(st_d['whip_speed']):
                rejected.append({'t': round(float(t[i]), 4), 'frame': _frame_no(t[i], info),
                                 'why': 'camera whip: motion-blurred frames while the camera moves fast around them',
                                 'measures': m})
                continue
        events.append({'i': int(i), 'kind': 'cut', 'strength': float(d[i] - base), 'measures': m})


def _detect_punches(W, cells1, d, events, f, flat, measures, n, sim, sim_raw, st_d):
    # punch-ins: a one-step reframe of the same picture between calm steps
    lz = np.abs(np.log(np.clip(np.nan_to_num(f['zoom'], nan=1.0), 0.3, 3.0)))
    sh = np.hypot(np.nan_to_num(f['dx']), np.nan_to_num(f['dy']))
    pz, ps, calm = math.log(1 + float(st_d['punch_zoom'])), float(st_d['punch_shift']), float(st_d['punch_calm'])
    raw_d = 1.0 - sim_raw
    for i in np.flatnonzero(((lz >= pz) | (sh >= ps)) & (sim >= float(st_d['punch_min_sim']))
                            & (raw_d >= float(st_d['punch_min_raw'])) & (cells1 <= 0.4)):
        if i == 0 or flat[i]:
            continue
        if f['n_inl'][i] < int(st_d['punch_min_inliers']) or f['n_inl'][i] < 0.6 * max(1.0, f['n_trk'][i]):
            continue
        nz = _median_around(lz, i, W, skip=1)
        ns = _median_around(sh, i, W, skip=1)
        if raw_d[i] < float(st_d['punch_raw_ratio']) * _median_around(raw_d, i, W, skip=1):
            continue
        lo, hi = max(1, i - W), min(n, i + W + 1)
        steps = np.concatenate([np.maximum(lz[lo:max(lo, i - 1)] / pz, sh[lo:max(lo, i - 1)] / ps),
                                np.maximum(lz[min(hi, i + 2):hi] / pz, sh[min(hi, i + 2):hi] / ps)])
        jump = max(lz[i] / pz, sh[i] / ps)
        if nz < calm and ns < calm and (steps.size == 0 or jump >= 4 * float(np.percentile(steps, 90))):
            m = measures(i, _median_around(d, i, W, skip=1))
            events.append({'i': int(i), 'kind': 'punch', 'strength': float(max(lz[i] / pz, sh[i] / ps)), 'measures': m})


def _detect_dissolves(events, f, flat, measures, n, st_d):
    # dissolves: far frames differ, the middle fits a blend of them, no single step explains it
    far_d = 1.0 - np.nan_to_num(f['far_sim'], nan=1.0)
    fit = np.nan_to_num(f['blend_fit'], nan=9.0)
    al = np.nan_to_num(f['blend_a'], nan=-1.0)
    ok = (far_d >= float(st_d['dissolve_far_d'])) & (fit <= float(st_d['dissolve_fit'])) & (al > 0.08) & (al < 0.92) \
        & ~flat
    i = 0
    hard = {e['i'] for e in events if e['kind'] == 'cut'}
    while i < n:
        if not ok[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and (ok[j + 1] or (j + 2 < n and ok[j + 2])):
            j += 1
        if j - i + 1 >= int(st_d['dissolve_min_frames']) and not any(i - 2 <= hh <= j + 2 for hh in hard):
            mid = int(round((i + j) / 2))
            seg = al[i:j + 1]
            m = measures(mid)
            m.update(far_d=round(float(far_d[i:j + 1].mean()), 3), blend_fit=round(float(fit[i:j + 1].mean()), 3),
                     blend_a_first_last=[round(float(seg[0]), 2), round(float(seg[-1]), 2)])
            events.append({'i': mid, 'kind': 'dissolve', 'a': i, 'b': j, 'strength': float(far_d[i:j + 1].mean()),
                           'measures': m})
        i = j + 1


def _detect_fades(events, f, flat, measures, n):
    # fades / black (or flat) stretches
    i = 1
    while i < n:
        if not flat[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and flat[j + 1]:
            j += 1
        a = i
        while a - 1 > 0 and f['std'][a - 1] < f['std'][max(0, a - 2)] - 0.5 and not flat[a - 1]:
            a -= 1
        b = j
        while b + 1 < n - 1 and f['std'][b + 1] < f['std'][min(n - 1, b + 2)] - 0.5 and not flat[b + 1]:
            b += 1
        if i > 1 or j < n - 1:        # not the whole clip
            m = measures(i)
            m.update(flat_frames=int(j - i + 1), luma=round(float(np.mean(f['luma'][i:j + 1])), 1))
            events.append({'i': int(j + 1 if j + 1 < n else i), 'kind': 'fade', 'a': int(a), 'b': int(b),
                           'strength': 1.0, 'measures': m, 'flat': [int(i), int(j)]})
        i = j + 1


def _check_scene_scores(end, events, fps_a, info, rejected, st_d, start, t, video, warnings):
    # a second, independent view: ffmpeg's scene score (the older method's measure: an abrupt jump in the plain frame
    # difference) must also rise at a hard cut or punch-in. Hands and parts moving close to the lens, which change
    # the picture over a few frames, rarely make it jump.
    need = float(st_d['require_scene_score'])
    wants = {'cut': need, 'punch': min(need, float(st_d['punch_scene_score']))}
    if need > 0 and any(e['kind'] in ('cut', 'punch') for e in events):
        try:
            sc = scene_scores(video, None if start is None else float(t[0]) - 0.2,
                              None if end is None else float(t[-1]) + 0.2, crop=info.get('crop'))
        except Exception as ex:  # noqa: BLE001
            sc = None
            warnings.append(f'scene scores unavailable ({type(ex).__name__}); cuts not cross-checked')
        if sc:
            st_arr = np.array([x[0] for x in sc])
            sv_arr = np.array([x[1] for x in sc])
            tol = 2.5 / fps_a
            keep_ev = []
            for e in events:
                if e['kind'] not in ('cut', 'punch'):
                    keep_ev.append(e)
                    continue
                te = float(t[e['i']])
                near = sv_arr[np.abs(st_arr - te) <= tol]
                s_max = float(near.max()) if near.size else 0.0
                e['measures']['scene_score'] = round(s_max, 3)
                if s_max < wants[e['kind']]:
                    rejected.append({'t': round(te, 4), 'frame': _frame_no(te, info),
                                     'why': 'no jump in the plain frame difference (ffmpeg scene score '
                                            f"{s_max:.2f} < {wants[e['kind']]:g}): the picture changed without a jump",
                                     'measures': e['measures']})
                    continue
                keep_ev.append(e)
            events = keep_ev
    return events


def _check_scene_returns(events, f, fps_a, info, rejected, st_d, st_f, t, video):
    # something passed in front of the lens (a hand, a part) or the camera looked away and back: the picture from
    # just before the boundary comes back within occlusion_reach_s
    reach = float(st_d['occlusion_reach_s'])
    if reach > 0 and events:
        vcache = _verify_cache(video)
        keep_ev = []
        for e in events:
            if e['kind'] != 'cut':
                keep_ev.append(e)
                continue
            back, lag = _scene_returns(video, info, f, e['i'], reach, st_f, fps_a, vcache)
            e['measures']['scene_back_after_s'] = lag
            if back:
                rejected.append({'t': round(float(t[e['i']]), 4), 'frame': _frame_no(t[e['i']], info),
                                 'why': f'the picture from just before comes back {lag:.2f} s later: something passed '
                                        'in front of the lens, or the camera looked away and back',
                                 'measures': e['measures']})
                continue
            keep_ev.append(e)
        events = keep_ev
        _verify_save(video, vcache)
    return events


def _select_boundaries(events, info, rejected, st_d, t):
    # one event per min_shot_s: the strongest (cut > fade > punch > dissolve when equal)
    prio = {'cut': 3, 'fade': 2, 'punch': 1, 'dissolve': 0}
    events.sort(key=lambda e: (-prio[e['kind']], -e['strength']))
    kept = []
    gap = float(st_d['min_shot_s'])
    for e in events:
        te = t[e['i']]
        if any(abs(te - t[k['i']]) < gap for k in kept):
            rejected.append({'t': round(float(te), 4), 'frame': _frame_no(te, info),
                             'why': f'within min_shot_s of a stronger boundary ({e["kind"]})',
                             'measures': e['measures']})
            continue
        kept.append(e)
    kept.sort(key=lambda e: e['i'])
    cuts = []
    for e in kept:
        if e['kind'] not in st_d['kinds']:
            continue
        i = e['i']
        c = {'t': round(float(t[i]), 4), 'frame': _frame_no(t[i], info), 'kind': e['kind']}
        if 'a' in e:
            c.update(start=round(float(t[e['a']]), 4), end=round(float(t[e['b']]), 4),
                     start_frame=_frame_no(t[e['a']], info), end_frame=_frame_no(t[e['b']], info))
        else:
            c.update(start=c['t'], end=c['t'], start_frame=c['frame'], end_frame=c['frame'])
        if 'flat' in e:
            c['flat'] = [round(float(t[e['flat'][0]]), 4), round(float(t[e['flat'][1]]), 4)]
        c['measures'] = e['measures']
        cuts.append(c)
    return cuts


def _detect_view(video, start=None, end=None, settings=None, refresh=False, kinds=None):
    """detect() on one view: the whole frame, or the part of it settings['picture_area'] names."""
    video = str(Path(video).resolve())
    st_f = _settings(FEATURE_DEFAULTS, settings)
    st_d = _settings(DETECT_DEFAULTS, settings)
    if kinds is not None:
        st_d['kinds'] = list(kinds)
    f = features(video, start, end, st_f, refresh=refresh)
    info = f['info']
    t = f['t']
    n = len(t)
    fps_a = info['fps'] / f['step']
    W = max(3, int(round(float(st_d['window_s']) * fps_a)))
    sim, xsim, sim_raw = np.nan_to_num(f['sim'], nan=1.0), np.nan_to_num(f['xsim'], nan=1.0), \
        np.nan_to_num(f['sim_raw'], nan=1.0)
    xcells = np.nan_to_num(f['xcells'], nan=1.0) if 'xcells' in f else np.ones(n)
    cells1 = np.nan_to_num(f['cells'], nan=1.0) if 'cells' in f else np.ones(n)
    flat = f['std'] < float(st_d['flat_std'])
    lowtex = f['std'] < float(st_d['low_texture_std'])
    d = 1.0 - xsim
    d1 = 1.0 - sim
    if n:
        d[0] = d1[0] = 0.0
    events, rejected, warnings = [], [], []
    # a fixed layout (footage in one part of the frame, a still graphic panel elsewhere): cells that barely change in
    # 90% of the frames are left out of 'how much of the picture changed'
    layout = None
    if 'cmask' in f and n > 10:
        g = np.asarray(f['grid'], dtype=np.float32)
        active = np.percentile(g, 90, axis=0) >= float(st_d['static_mad'])
        if 3 <= int(active.sum()) <= active.size - 4:
            layout = int(sum(1 << int(k) for k in np.flatnonzero(active)))
            cm = np.nan_to_num(f['cmask'], nan=0.0).astype(np.int64)
            cv_ = np.nan_to_num(f['cvalid'], nan=0.0).astype(np.int64)

            def _pop(x):
                return np.array([bin(int(v)).count('1') for v in x])
            den = _pop(cv_ & layout)
            num = _pop(cm & cv_ & layout)
            frac = np.where(den > 0, num / np.maximum(den, 1), xcells)
            # where the cross check took another pair, keep its share
            xcells = np.where(np.abs(xsim - sim) < 1e-6, frac, xcells)
            warnings.append(f'fixed layout: {int(active.size - active.sum())} of {active.size} picture cells barely '
                            'change in this video (a graphic panel or border); cuts are judged on the other cells')

    pcs = np.hypot(np.nan_to_num(f['pc_dx']), np.nan_to_num(f['pc_dy'])) if 'pc_dx' in f else None
    sharp = np.nan_to_num(f['sharp'])

    def measures(i, base=None):
        z = float(f['zoom'][i]) if np.isfinite(f['zoom'][i]) else 1.0
        return {'d': round(float(d[i]), 3), 'd_pair': round(float(d1[i]), 3), 'd_raw': round(float(1 - sim_raw[i]), 3),
                'baseline': None if base is None else round(base, 3),
                'ratio': None if base is None else round(float(d[i]) / max(base, 0.02), 2),
                'hist': round(float(f['hd'][i]), 3), 'cells_changed': round(float(xcells[i]), 3),
                'inliers': int(f['n_inl'][i]),
                'tracked': int(f['n_trk'][i]), 'corners': int(f['n_feat'][i]),
                'zoom': round(z, 3), 'shift': round(float(math.hypot(f['dx'][i], f['dy'][i])), 3)}

    _detect_hard_cuts(W, d, d1, events, f, flat, fps_a, info, lowtex, measures, n, pcs, rejected, sharp, st_d,
        t, xcells)

    _detect_punches(W, cells1, d, events, f, flat, measures, n, sim, sim_raw, st_d)

    _detect_dissolves(events, f, flat, measures, n, st_d)

    _detect_fades(events, f, flat, measures, n)

    events = _check_scene_scores(end, events, fps_a, info, rejected, st_d, start, t, video, warnings)

    events = _check_scene_returns(events, f, fps_a, info, rejected, st_d, st_f, t, video)

    cuts = _select_boundaries(events, info, rejected, st_d, t)
    if f['step'] > 1:
        warnings.append(f'analysed every {f["step"]}th frame ({fps_a:.2f} fps of {info["fps"]:.2f}); cut times are '
                        'refined to the frame at the full rate')
        cuts = [_refine_full_rate(video, info, c, st_f) for c in cuts]
    s0 = float(t[0]) if n else 0.0
    s1 = float(t[-1]) + 1.0 / fps_a if n else 0.0
    edges = [s0] + [c['t'] for c in cuts if s0 < c['t'] < s1] + [s1]
    shots = [{'start': round(a, 4), 'end': round(b, 4), 'start_frame': _frame_no(a, info),
              'end_frame': _frame_no(b, info) - 1, 'seconds': round(b - a, 3)} for a, b in zip(edges, edges[1:])
             if b - a > 0.5 / fps_a]
    unsupported = ['a cut hidden inside a whip pan or heavy motion blur (the neighbourhood is already busy)',
                   'a jump cut between two nearly identical pictures (same framing, a small move)',
                   'split screens and picture-in-picture: a change in one panel only',
                   'wipes and other shaped transitions are reported as dissolves or hard cuts, or missed',
                   'a hand or a part right in front of the lens can still look like a cut',
                   'lens switches and time-lapse jumps inside one recording are real picture jumps and may be '
                   'reported (kind punch or cut)']
    method = ''
    if 'How it works' in (__doc__ or ''):
        method = __doc__.split('How it works')[1].split('Data only')[0].strip(' :\n')
    return {'schema_version': SCHEMA_VERSION, 'tool': 'shots.detect', 'video': video,
            'source_fingerprint': {'content_key': content_key(video), 'size': os.path.getsize(video)},
            'fps': round(info['fps'], 4), 'analysed_fps': round(fps_a, 4), 'duration': round(info['duration'], 3),
            'range': [round(s0, 4), round(s1, 4)], 'cuts': cuts, 'shots': shots,
            'camera_moves': _camera_moves(f, fps_a), 'rejected': rejected[:400], 'rejected_count': len(rejected),
            'settings': {**{k: st_f[k] for k in FEATURE_DEFAULTS}, **st_d}, 'method': method,
            'unsupported': unsupported, 'warnings': warnings, 'feature_cache': f['cache_file'],
            'took_s': f['took_s'], 'picture_area': info.get('crop')}


VERIFY = CACHE / 'verify'
SCENE = CACHE / 'scene'


def scene_scores(video, start=None, end=None, crop=None):
    """[[t, score], ...] ffmpeg's scene score for every frame of video[start:end], computed exactly as the older
    method does (scale=320:-2, select's scene value), cached per file content and range. crop: [x, y, w, h] scores
    only that part of the frame (the picture when the rest is bars or a blurred copy of it)."""
    import re as _re
    video = str(video)
    s0 = None if start is None else max(0.0, round(float(start), 3))
    s1 = None if end is None else round(float(end), 3)
    tag = '' if not crop else '-c' + '_'.join(str(int(v)) for v in crop)
    p = SCENE / f'{content_key(video)}-{s0}-{s1}{tag}-v1.json'
    try:
        return json.loads(p.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        pass
    try:
        import letitedit.timeline.made as made
        ff = str(made.ffmpeg_exe())
    except Exception:  # noqa: BLE001
        ff = str(FFMPEG)
    args = [ff, '-hide_banner', '-nostats']
    if s0:
        args += ['-ss', f'{s0:.3f}']
    args += ['-i', video]
    if s1 is not None:
        args += ['-t', f'{s1 - (s0 or 0.0):.3f}']
    cut = f'crop={int(crop[2])}:{int(crop[3])}:{int(crop[0])}:{int(crop[1])},' if crop else ''
    args += ['-vf', cut + "scale=320:-2,select='gte(scene\\,0)',metadata=print:key=lavfi.scene_score", '-an', '-f',
             'null', '-']
    r = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    out, tt = [], None
    for line in r.stderr.splitlines():
        m = _re.search(r'pts_time:([\d.]+)', line)
        if m:
            tt = float(m.group(1))
            continue
        m = _re.search(r'lavfi\.scene_score=([\d.]+)', line)
        if m and tt is not None:
            out.append([round((s0 or 0.0) + tt, 4), float(m.group(1))])
            tt = None
    try:
        SCENE.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
        tmp.write_text(json.dumps(out), encoding='utf-8')
        os.replace(tmp, p)
    except OSError:
        pass
    return out


def _verify_cache(video):
    p = VERIFY / f'{content_key(video)}-f{FEATURE_VERSION}.json'
    try:
        return json.loads(p.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def _verify_save(video, data):
    try:
        VERIFY.mkdir(parents=True, exist_ok=True)
        p = VERIFY / f'{content_key(video)}-f{FEATURE_VERSION}.json'
        tmp = p.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
        tmp.write_text(json.dumps(data), encoding='utf-8')
        os.replace(tmp, p)
    except OSError:
        pass


def _scene_returns(video, info, f, i, reach, st, fps_a, vcache):
    """(True, lag_s) when a frame up to `reach` seconds after boundary i matches the sharpest of the 3 frames before
    it (camera estimate trusted, NCC >= 0.6, at most 40% of the cells changed); else (False, None)."""
    t_cut = float(f['t'][i])
    key = f'{t_cut:.4f}|{reach:.2f}'
    if key in vcache:
        v = vcache[key]
        return bool(v[0]), v[1]
    import cv2
    w, h = analysis_size(info, st['analysis_px'])
    step = max(1, int(round(info['fps'] / fps_a)))
    frames = [(tt, y.copy()) for tt, y, _, _ in decode(video, w, h, max(0.0, t_cut - 4.5 / fps_a),
                                                         reach + 5.0 / fps_a, step=step, crop=info.get('crop'))]
    before = [(tt, y) for tt, y in frames if tt < t_cut - 0.25 / fps_a][-3:]
    after = [(tt, y) for tt, y in frames if tt >= t_cut + 1.5 / fps_a]
    res = (False, None)
    if before and after:
        ref = max(before, key=lambda x: cv2.Laplacian(x[1], cv2.CV_32F).var())[1]
        stride = max(1, int(round(0.1 * fps_a)))
        for tt, y in after[::stride]:
            pr = measure_pair(ref, y, st)
            if pr.trusted and pr.sim >= 0.6 and pr.cells <= 0.4:
                res = (True, round(tt - t_cut, 3))
                break
    vcache[key] = [res[0], res[1]]
    return res


def _refine_full_rate(video, info, cut, st):
    """A cut found on decimated frames: the exact frame at the full rate (largest change within one analysed step
    either side)."""
    if cut['kind'] not in ('cut', 'punch'):
        return cut
    w, h = analysis_size(info, st['analysis_px'])
    span = 2.5 / (info['fps'] / max(1, int(math.ceil(info['fps'] / float(st['max_fps']) - 1e-6))))
    frames = [(tt, y) for tt, y, _, _ in decode(video, w, h, max(0.0, cut['t'] - span), 2 * span,
                                                 crop=info.get('crop'))]
    best = None
    for (ta, a), (tb, b) in zip(frames, frames[1:]):
        pr = measure_pair(a, b, st)
        if best is None or pr.sim < best[0]:
            best = (pr.sim, tb)
    if best is not None:
        cut = dict(cut)
        cut['t'] = cut['start'] = cut['end'] = round(float(best[1]), 4)
        cut['frame'] = cut['start_frame'] = cut['end_frame'] = _frame_no(best[1], info)
    return cut


def cut_times(video, settings=None, kinds=None):
    """Just the cut times (seconds) of detect()."""
    return [c['t'] for c in detect(video, settings=settings, kinds=kinds)['cuts']]


def ffmpeg_cuts(video, cut_above=0.15, start_s=None, end_s=None):
    """The older method (reference.scene_cuts: ffmpeg's scene score over cut_above on a 320 px copy), for
    comparison."""
    import letitedit.footage.reference as reference
    return reference.scene_cuts(str(video), cut_above, start_s, end_s)


def evaluate(found, truth, fps, tol_frames=2):
    """found, truth: lists of times (s) or of {t | start/end}; a found cut matches an unmatched true one within
    tol_frames (gradual true boundaries: anywhere from start - tol to end + tol). Returns {tp, fp, fn, precision,
    recall, f1, matched: [[truth_t, found_t]], false_positives, missed}."""
    def span(x):
        if isinstance(x, dict):
            a = float(x.get('start', x.get('t')))
            b = float(x.get('end', x.get('t')))
            return a, b, float(x.get('t', (a + b) / 2))
        return float(x), float(x), float(x)
    tol = tol_frames / float(fps)
    T = sorted((span(x) for x in truth), key=lambda s: s[2])
    F = sorted((span(x) for x in found), key=lambda s: s[2])
    used = [False] * len(T)
    matched, fps_ = [], []
    for fa, fb, ft in F:
        best, bd = None, None
        for k, (ta, tb, tt) in enumerate(T):
            if used[k]:
                continue
            if ta - tol - 1e-6 <= ft <= tb + tol + 1e-6 or (fa <= tb + tol and fb >= ta - tol):
                dist = abs(ft - tt)
                if bd is None or dist < bd:
                    best, bd = k, dist
        if best is None:
            fps_.append(round(ft, 4))
        else:
            used[best] = True
            matched.append([round(T[best][2], 4), round(ft, 4)])
    missed = [round(T[k][2], 4) for k in range(len(T)) if not used[k]]
    tp, fp, fn = len(matched), len(fps_), len(missed)
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return {'tp': tp, 'fp': fp, 'fn': fn, 'precision': round(p, 4), 'recall': round(r, 4),
            'f1': round(2 * p * r / (p + r), 4) if p + r else 0.0, 'matched': matched, 'false_positives': fps_,
            'missed': missed}
