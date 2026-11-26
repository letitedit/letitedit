"""Learn reference measurements: cached frame, caption, movement, lighting and sound evidence.

Analyse returns report.json, breakdowns and pictures. Run merges reference facts without publishing settings.
learn_measure supplies the public background-job interface; detector modules retain their existing file names.
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
import sys
import time
from pathlib import Path

import numpy as np

from letitedit.looks.style_import_stats import _r, _stats

VERSION = 12
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'style_import'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
THREADS = 4                     # decoder threads (the PC's rule: at most 4)
MAX_FRAMES_MB = 260             # memory for the small grey frames kept for the whole video

# Settings that change what is measured; part of the cache key
SETTINGS = {
    'short_side': 144,          # grey analysis frames: short side in pixels
    'max_fps': 30.0,            # analysis frame rate cap (60 fps sources are read at 30)
    'sample_fps_short': 6.0,    # colour frames for OCR / faces / overlays (Shorts)
    'sample_fps_long': 1.5,     # (long videos)
    'sample_width': 540,        # sampled frames' width for vertical video (landscape: 960)
    'typography_max_events': 8,
    'text_budget_s': 120,
    'cut_ratio': 3.0,           # a cut's frame difference against the median of its 12 neighbours
    'cut_min_diff': 6.0,        # and at least this mean difference (0-255)
    'cut_min_share': 0.22,      # and at least this share of the frame's blocks changing
    'jump_ratio': 2.4,          # weaker: same-framing jump cuts (reported apart, with a lower confidence)
    'jump_min_share': 0.07,
    'hist_cut': 0.38,           # a histogram change this large is a cut whatever the rest says
}


def clock(s):
    s = max(0.0, float(s))
    return f'{int(s // 60)}:{s % 60:05.2f}'


def _ff():
    import letitedit.timeline.made as made
    return str(made.ffmpeg_exe())


def _ffprobe():
    p = Path(_ff()).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
    return str(p)


# ------------------------------------------------------------------ the file

def probe(video):
    """{duration, fps, width, height (as displayed, rotation applied), rotation, has_audio, size_mb}."""
    r = subprocess.run([_ffprobe(), '-v', 'error', '-show_entries',
                        'stream=index,codec_type,width,height,avg_frame_rate,r_frame_rate:stream_tags=rotate:'
                        'stream_side_data=rotation:format=duration,size', '-of', 'json', str(video)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW,
                       stdin=subprocess.DEVNULL)
    d = json.loads(r.stdout or '{}')
    streams = d.get('streams') or []
    v = next((s for s in streams if s.get('codec_type') == 'video'), None)
    if v is None:
        raise ValueError(f'{video}: no video stream')
    a = any(s.get('codec_type') == 'audio' for s in streams)

    def rate(x):
        try:
            n, m = str(x).split('/')
            return float(n) / float(m) if float(m) else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0
    fps = rate(v.get('avg_frame_rate')) or rate(v.get('r_frame_rate')) or 30.0
    if fps > 240:
        fps = rate(v.get('r_frame_rate')) or 30.0
    rot = 0
    try:
        rot = int(float((v.get('tags') or {}).get('rotate') or 0))
    except ValueError:
        pass
    for sd in v.get('side_data_list') or []:
        if 'rotation' in sd:
            rot = int(float(sd['rotation']))
    w, h = int(v.get('width') or 0), int(v.get('height') or 0)
    if abs(rot) % 180 == 90:
        w, h = h, w
    fmt = d.get('format') or {}
    return {'duration': float(fmt.get('duration') or 0.0), 'fps': round(fps, 3), 'width': w, 'height': h,
            'rotation': rot, 'has_audio': a, 'size_mb': round(int(fmt.get('size') or 0) / 1e6, 1)}


def analysis_geometry(info, settings=SETTINGS):
    """(fps, w, h) of the grey analysis frames: the short side settings['short_side'] at up to max_fps; when the whole
    video would not fit in MAX_FRAMES_MB, first a smaller picture, then fewer frames (never under 6 fps)."""
    fps = float(info['fps'] or 30.0)
    step = 1
    while fps / step > settings['max_fps'] + 0.5:
        step += 1
    afps0 = fps / step
    W, H = max(1, info['width']), max(1, info['height'])
    side0 = int(settings['short_side'])

    def size(side):
        if W <= H:
            return side, int(round(H * side / W / 2) * 2)
        return int(round(W * side / H / 2) * 2), side
    tries = [(afps0, side0), (min(afps0, 15.0), side0), (min(afps0, 15.0), 108), (min(afps0, 12.0), 96),
             (min(afps0, 10.0), 90), (min(afps0, 8.0), 80), (min(afps0, 6.0), 72)]
    for afps, side in tries:
        if afps < afps0:
            # a whole fraction of the file's rate, so frames are not resampled unevenly
            afps = fps / max(1, math.ceil(fps / afps - 1e-6))
        w, h = size(side)
        if info['duration'] * afps * w * h / 1e6 <= MAX_FRAMES_MB:
            return afps, w, h
    afps, side = tries[-1]
    afps = fps / max(1, math.ceil(fps / afps - 1e-6))
    w, h = size(side)
    return afps, w, h


def grid_select(every_s, native_fps):
    """An ffmpeg select filter keeping, for each multiple of every_s from the first frame, the frame nearest it (the fps
    filter keeps the latest frame of each window instead: up to half a step late). Use with -fps_mode passthrough."""
    half = 0.5 / float(native_fps)
    return f"select='lt(mod(t+{half:.6f}\\,{float(every_s):.6f})\\,{2 * half:.6f})'"


def decode_grey(video, w, h, fps=None, start=None, duration=None, progress=None, total_s=None, native=None):
    """Frames as a uint8 array (N, h, w): ffmpeg scales (area) and turns them grey; fps None = the file's own rate.
    native: the file's own rate; with it, frame k is the one nearest k / fps."""
    args = [_ff(), '-v', 'error', '-nostdin', '-threads', str(THREADS)]
    if start:
        args += ['-ss', f'{float(start):.3f}']
    args += ['-i', str(video)]
    if duration:
        args += ['-t', f'{float(duration):.3f}']
    rate = ([grid_select(1.0 / fps, native)] if native else [f'fps={fps:.6f}']) if fps else []
    vf = rate + [f'scale={w}:{h}:flags=area', 'format=gray']
    args += ['-filter_threads', '2', '-vf', ','.join(vf), '-fps_mode', 'passthrough', '-an', '-sn', '-f', 'rawvideo',
             '-pix_fmt', 'gray', '-']
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         creationflags=NO_WINDOW)
    n = w * h
    chunks = []
    last = time.monotonic()
    while True:
        buf = p.stdout.read(n * 64)
        if not buf:
            break
        chunks.append(buf)
        if progress and total_s and time.monotonic() - last > 2:
            last = time.monotonic()
            done = sum(len(c) for c in chunks) / n / (fps or 30.0)
            progress(min(0.99, done / total_s))
    p.wait()
    data = b''.join(chunks)
    k = len(data) // n
    if k == 0:
        err = (p.stderr.read() or b'').decode('utf-8', 'replace')[-400:]
        raise RuntimeError(f'could not decode {video}: {err}')
    return np.frombuffer(data[:k * n], np.uint8).reshape(k, h, w)


def grab(video, t, out, width=None):
    """One frame (accurate seek) as an image file; width None = full size."""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    args = [_ff(), '-v', 'error', '-y', '-nostdin', '-ss', f'{max(0.0, float(t)):.3f}', '-i', str(video),
            '-frames:v', '1']
    if width:
        args += ['-vf', f'scale={int(width)}:-2']
    subprocess.run(args + [str(out)], capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    return Path(out) if Path(out).exists() else None


def grab_range(video, start, duration, width, fps=None):
    """Colour frames (BGR uint8 list) of a short stretch, every frame (or fps), width px wide."""
    info = probe(video) if not isinstance(video, dict) else video
    W, H = info['width'], info['height']
    h = int(round(H * width / W / 2) * 2)
    args = [_ff(), '-v', 'error', '-nostdin', '-threads', str(THREADS), '-ss', f'{max(0.0, float(start)):.3f}',
            '-i', str(info.get('path') or video), '-t', f'{float(duration):.3f}']
    vf = ([grid_select(1.0 / float(fps), info['fps'])] if fps else []) + [f'scale={width}:{h}:flags=area']
    args += ['-vf', ','.join(vf), '-fps_mode', 'passthrough', '-an', '-sn', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    n = width * h * 3
    k = len(r.stdout) // n
    return [np.frombuffer(r.stdout[i * n:(i + 1) * n], np.uint8).reshape(h, width, 3) for i in range(k)]


def sample_frames(video, folder, fps, width, info, progress=None):
    """Colour frames every 1/fps s written as JPEG files (q 3): [(t, path)]. Times are the frames' own times."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob('s_*.jpg'):
        old.unlink()
    W, H = info['width'], info['height']
    if W > H:
        width = int(round(width * 16 / 9 / 2) * 2) if width <= 600 else width
    h = int(round(H * width / W / 2) * 2)
    args = [_ff(), '-v', 'error', '-nostdin', '-y', '-threads', str(THREADS), '-i', str(video), '-filter_threads', '2',
            '-vf', f'{grid_select(1.0 / float(fps), info["fps"])},scale={width}:{h}:flags=area', '-fps_mode', 'passthrough',
            '-an', '-sn', '-q:v', '3', str(folder / 's_%05d.jpg')]
    subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    files = sorted(folder.glob('s_*.jpg'))
    # file k is the frame nearest k / fps
    return [(round(k / fps, 3), str(p)) for k, p in enumerate(files)]


# ------------------------------------------------------------------ frame-to-frame features

BLOCK = 8


def _blocks(a):
    """Mean over BLOCKxBLOCK blocks of a 2-D float array (edges cropped)."""
    h, w = a.shape
    hb, wb = h // BLOCK, w // BLOCK
    return a[:hb * BLOCK, :wb * BLOCK].reshape(hb, BLOCK, wb, BLOCK).mean(axis=(1, 3))


def frame_features(frames, progress=None):
    """Per frame i (against frame i-1): d (mean abs difference 0-255), share (share of 8x8 blocks whose mean abs
    difference passes 10), hist (Bhattacharyya distance of 32-bin histograms), luma, contrast (std), sharp (variance
    of the Laplacian), and per-block mean abs differences (kept as float16)."""
    import cv2
    n = len(frames)
    d = np.zeros(n, np.float32)
    share = np.zeros(n, np.float32)
    hist = np.zeros(n, np.float32)
    luma = np.zeros(n, np.float32)
    contrast = np.zeros(n, np.float32)
    sharp = np.zeros(n, np.float32)
    hb, wb = frames.shape[1] // BLOCK, frames.shape[2] // BLOCK
    bd = np.zeros((n, hb, wb), np.float16)
    prev_h = None
    for i in range(n):
        f = frames[i]
        luma[i] = f.mean()
        contrast[i] = f.std()
        sharp[i] = cv2.Laplacian(f, cv2.CV_32F).var()
        h_ = cv2.calcHist([f], [0], None, [32], [0, 256])
        cv2.normalize(h_, h_, 1, 0, cv2.NORM_L1)
        if i:
            diff = cv2.absdiff(f, frames[i - 1]).astype(np.float32)
            d[i] = diff.mean()
            b = _blocks(diff)
            bd[i] = b
            share[i] = float((b > 10).mean())
            hist[i] = cv2.compareHist(prev_h, h_, cv2.HISTCMP_BHATTACHARYYA)
        prev_h = h_
        if progress and i % 500 == 0:
            progress(i / max(1, n))
    return {'d': d, 'share': share, 'hist': hist, 'luma': luma, 'contrast': contrast, 'sharp': sharp, 'blocks': bd}


_WIN = {}


def _hann(shape):
    import cv2
    if shape not in _WIN:
        _WIN[shape] = cv2.createHanningWindow((shape[1], shape[0]), cv2.CV_32F)
    return _WIN[shape]


def align(a, b, scales=(1.0,), crop=0.12):
    """Best similarity between two grey frames: tries each scale of `a` (about the centre), aligns the shift by phase
    correlation on the central part, returns {scale, dx, dy (pixels of b), response (0-1), residual (mean abs
    difference after aligning, central part), centre (zoom centre as frame fractions, or None)}."""
    import cv2
    h, w = a.shape
    y0, y1, x0, x1 = int(h * crop), int(h * (1 - crop)), int(w * crop), int(w * (1 - crop))
    B = b.astype(np.float32)
    Bc = B[y0:y1, x0:x1]
    if np.std(a[y0:y1, x0:x1]) < 1 or np.std(Bc) < 1:
        return {'scale': 1.0, 'dx': 0.0, 'dy': 0.0, 'response': 0.0,
                'residual': float(np.abs(a[y0:y1, x0:x1].astype(np.float32) - Bc).mean()), 'centre': None}
    win = _hann(Bc.shape)
    best = None
    for s in scales:
        if abs(s - 1.0) < 1e-6:
            A = a.astype(np.float32)
        else:
            M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), 0, float(s))
            A = cv2.warpAffine(a.astype(np.float32), M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        Ac = A[y0:y1, x0:x1]
        (dx, dy), resp = cv2.phaseCorrelate(Ac, Bc, win)
        if best is None or resp > best['response']:
            best = {'scale': float(s), 'dx': float(dx), 'dy': float(dy), 'response': float(resp), '_A': A}
    A = best.pop('_A')
    M = np.float32([[1, 0, best['dx']], [0, 1, best['dy']]])
    As = cv2.warpAffine(A, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    best['residual'] = float(np.abs(As[y0:y1, x0:x1] - Bc).mean())
    s = best['scale']
    if abs(s - 1.0) > 0.015:
        # x' = s (x - c) + c + t  ->  fixed point x* = c + t / (1 - s)
        cx = w / 2.0 + best['dx'] / (1 - s)
        cy = h / 2.0 + best['dy'] / (1 - s)
        best['centre'] = [round(min(1.5, max(-0.5, cx / w)), 3), round(min(1.5, max(-0.5, cy / h)), 3)]
    else:
        best['centre'] = None
    return best


COARSE_SCALES = (0.70, 0.75, 0.80, 0.84, 0.88, 0.91, 0.94, 0.97, 1.0, 1.03, 1.065, 1.1, 1.14, 1.19, 1.25, 1.32, 1.4)


def scale_between(a, b, lo=0.70, hi=1.43):
    """Scale of b against a (b = a zoomed in by `scale` when > 1): coarse search, then refined in 1% steps."""
    coarse = [s for s in COARSE_SCALES if lo <= s <= hi]
    best = align(a, b, coarse)
    s0 = best['scale']
    fine = sorted({round(s0 * (1 + k * 0.01), 4) for k in range(-3, 4)})
    best2 = align(a, b, fine)
    return best2 if best2['response'] >= best['response'] else best


# ------------------------------------------------------------------ cuts and transitions

def _local_median(x, i, half=6):
    lo, hi = max(1, i - half), min(len(x), i + half + 1)
    nb = np.r_[x[lo:i], x[i + 1:hi]]
    return float(np.median(nb)) if len(nb) else 0.0


def masked_diffs(feat, masks=None):
    """Frame differences with text blocks left out: (d, share) per frame from the per-block differences, where
    masks(i) gives a boolean (hb, wb) array of blocks to ignore at frame i (captions and other text change on their
    own and are not cuts) or None."""
    bd = feat['blocks']
    n = len(bd)
    if masks is None:
        return feat['d'], feat['share']
    d = np.zeros(n, np.float32)
    share = np.zeros(n, np.float32)
    for i in range(1, n):
        m = masks(i)
        b = bd[i].astype(np.float32)
        if m is not None and m.any() and (~m).sum() > 0.3 * m.size:
            keep = b[~m]
        else:
            keep = b.ravel()
        d[i] = keep.mean()
        share[i] = float((keep > 10).mean())
    return d, share


def detect_cuts(frames, feat, fps, settings=SETTINGS, masks=None):
    """Hard cuts: [{frame, t, d, ratio, iso, share, hist, conf, kind_hint}] where kind_hint is 'cut' or 'jump' (a
    weaker, same-framing change: a jump cut; a dropped frame looks the same). Text blocks (masks) are left out of the
    differences. A spike that a camera move explains (the frames align with a high response and a small residual)
    is not a cut; a weak one must stand alone (a hand waving through the frame moves over several frames, a jump
    cut changes the picture in one)."""
    d, share = masked_diffs(feat, masks)
    hist = feat['hist']
    n = len(d)
    out = []
    for i in range(1, n - 1):
        loc = _local_median(d, i)
        ratio = float(d[i] / (loc + 1.0))
        iso = float(d[i] / max(0.5, float(max(d[i - 1], d[i + 1]))))
        strong = (ratio >= settings['cut_ratio'] and d[i] >= settings['cut_min_diff']
                  and share[i] >= settings['cut_min_share'] and (iso >= 1.8 or hist[i] >= 0.15 or share[i] >= 0.5))
        hist_cut = hist[i] >= settings['hist_cut'] and d[i] >= 10 and ratio >= 1.6
        weak = (not strong and ratio >= settings['jump_ratio'] and d[i] >= 4.0
                and share[i] >= settings['jump_min_share'] and iso >= 2.0)
        if not (strong or hist_cut or weak):
            continue
        lo, hi = max(1, i - 2), min(n, i + 3)
        if d[i] < d[lo:hi].max():
            continue
        al = align(frames[i - 1], frames[i])
        shift = math.hypot(al['dx'], al['dy'])
        moved = (al['response'] > 0.25 and al['residual'] < 0.42 * float(feat['d'][i]) and shift > 1.0)
        if moved:
            # a camera move goes on over several frames; one jump between still neighbours is a reframe (a jump cut)
            nb = [align(frames[j - 1], frames[j]) for j in (i - 1, i + 1) if 1 <= j - 1 and j < n]
            nb_shift = max([math.hypot(m['dx'], m['dy']) for m in nb] or [0.0])
            if nb_shift < 0.3 * shift:
                moved = False
        if moved and not hist_cut:
            continue
        # a cut is a step: steady before it and steady after it. A hand or an object swept through a still shot
        # changes part of the picture in one frame too, but it keeps changing on the frames after (measured on
        # letitedit's own talking-head edits and the hand-labelled set)
        if not hist_cut and share[i] < 0.6 and 3 <= i < n - 2:
            raw = float(feat['d'][i])
            after = float(np.abs(frames[i + 2].astype(np.int16) - frames[i].astype(np.int16)).mean())
            before = float(np.abs(frames[i - 1].astype(np.int16) - frames[i - 3].astype(np.int16)).mean())
            if max(after, before) > 0.6 * raw:
                continue
        conf = 0.95 if (strong or hist_cut) and ratio >= 4 else 0.8 if (strong or hist_cut) else 0.5
        out.append({'frame': i, 't': round(i / fps, 3), 'd': round(float(d[i]), 1), 'ratio': round(ratio, 1),
                    'iso': round(iso, 1), 'share': round(float(share[i]), 3), 'hist': round(float(hist[i]), 3),
                    'conf': conf, 'kind_hint': 'cut' if (strong or hist_cut) else 'jump', 'by': 'frames'})
    return out


def fuse_cuts(mine, other, fps, n):
    """My cuts plus the server's shot detector's (shots.detect: camera-move aware, very few false cuts, misses some
    same-framing jump cuts). One cut per frame; a cut both found is more certain."""
    out = [dict(c) for c in mine]
    for c in other:
        f = int(round(float(c['t']) * fps))
        near = [m for m in out if abs(m['frame'] - f) <= 2]
        if near:
            for m in near:
                m['conf'] = max(m['conf'], 0.95)
                m['by'] = 'both'
            continue
        if 1 <= f < n:
            out.append({'frame': f, 't': round(f / fps, 3), 'conf': 0.9, 'kind_hint': 'cut', 'by': 'shots.detect',
                        'd': None, 'ratio': None, 'share': None, 'hist': None,
                        'detector_kind': c.get('kind')})
    # nothing in the first frame or the last two (an export's last frame is often a repeat or black)
    out = [c for c in out if 1 <= c['frame'] < n - 2]
    return sorted(out, key=lambda c: c['frame'])


def _blend_ratio(fa, fm, fb):
    """How well the middle frame is a mix of the two ends: mean|m - (a+b)/2| / min(mean|m-a|, mean|m-b|)."""
    a, m, b = (x.astype(np.float32) for x in (fa, fm, fb))
    e_mix = float(np.abs(m - 0.5 * (a + b)).mean())
    e_end = min(float(np.abs(m - a).mean()), float(np.abs(m - b).mean()))
    return e_mix / (e_end + 1e-3), e_end


def detect_gradual(frames, feat, fps, cuts, settings=SETTINGS):
    """Gradual transitions: dissolves (the middle frames are a mix of the two ends), fades through black or white
    (the picture goes near black / white and comes back), flashes (a few very bright frames). [{start, end, t, kind,
    len_s, conf}]"""
    luma, d = feat['luma'], feat['d']
    n = len(frames)
    out = []
    cut_frames = {c['frame'] for c in cuts}
    # fades through black / white: runs of near-black (luma < 18) or near-white (> 232) frames
    contrast = feat['contrast']
    for kind, test in (('fade_black', lambda v, c: v < 20 and c < 9), ('fade_white', lambda v, c: v > 232 and c < 12)):
        i = 0
        while i < n:
            if not test(luma[i], contrast[i]):
                i += 1
                continue
            j = i
            while j + 1 < n and test(luma[j + 1], contrast[j + 1]):
                j += 1
            # gradual on the way in or out: luma moves over >= 3 frames towards the extreme
            k0 = i
            while k0 - 1 >= 0 and abs(float(luma[k0 - 1]) - float(luma[k0])) > 1.5 and i - k0 < int(fps * 2):
                k0 -= 1
            k1 = j
            while k1 + 1 < n and abs(float(luma[k1 + 1]) - float(luma[k1])) > 1.5 and k1 - j < int(fps * 2):
                k1 += 1
            ramp = (i - k0) + (k1 - j)
            whole = (i == 0 and j >= n - 1)
            ramp_steps = np.abs(np.diff(luma[k0:k1 + 1]))
            gradual_ramp = ramp >= 3 and len(ramp_steps) and float(ramp_steps.max()) < .65 * float(ramp_steps.sum())
            if not whole and gradual_ramp:
                if kind == 'fade_white' and j - i <= int(0.2 * fps) and ramp < 4:
                    kind2 = 'flash'
                else:
                    kind2 = kind
                at_edge = 'start' if i == 0 else 'end' if j >= n - 1 else None
                out.append({'start': round(k0 / fps, 3), 'end': round((k1 + 1) / fps, 3),
                            't': round((i + j + 1) / 2 / fps, 3), 'kind': kind2 if not at_edge else
                            ('fade_in' if at_edge == 'start' else 'fade_out') + ('' if kind == 'fade_black' else '_white'),
                            'len_s': round((k1 + 1 - k0) / fps, 3), 'conf': 0.85 if ramp >= 3 else 0.6})
            i = j + 1
    # flashes that don't reach full white: a brightness spike of 1-6 frames
    bright = np.array([luma[index] > 170 and luma[index] - _local_median(luma, index, half=int(fps * 0.4)) > 60
                       for index in range(n)])
    boundaries = np.diff(np.pad(bright.astype(int), (1, 1)))
    for first, last in zip(np.flatnonzero(boundaries == 1), np.flatnonzero(boundaries == -1) - 1):
        if first == 0 or last >= n - 1 or last - first + 1 > min(6, max(1, int(fps * .2))):
            continue
        returns = abs(float(luma[first - 1]) - float(luma[last + 1])) < 20
        pulse = float(luma[first:last + 1].min()) - max(luma[first - 1], luma[last + 1]) > 60
        if returns and pulse and not any(abs(event['t'] - first / fps) < .25 for event in out):
            out.append({'start': round((first - 1) / fps, 3), 'end': round((last + 2) / fps, 3),
                        't': round(first / fps, 3), 'kind': 'flash',
                        'len_s': round((last - first + 3) / fps, 3), 'conf': .7})
    # dissolves: frames k apart differ like a cut, no single frame-to-frame spike between them, and the middle is a mix
    taken = np.zeros(n, bool)
    for o in out:
        taken[int(o['start'] * fps):int(o['end'] * fps) + 1] = True
    for k in (int(round(fps * 0.33)), int(round(fps * 0.7)), int(round(fps * 1.2))):
        if k < 4:
            continue
        D = np.zeros(n, np.float32)
        for i in range(0, n - k, 2):
            D[i] = float(np.abs(frames[i + k].astype(np.int16) - frames[i]).mean())
        i = 0
        while i < n - k:
            if D[i] < 22 or taken[i:i + k + 1].any():
                i += 2
                continue
            seg = d[i + 1:i + k + 1]
            if seg.max() > 0.45 * D[i] or any(c for c in cut_frames if i < c <= i + k):
                i += 2
                continue
            br, e_end = _blend_ratio(frames[i], frames[i + k // 2], frames[i + k])
            # the ends must be stable shots (little change just outside the window)
            calm = (float(np.median(d[max(1, i - k // 2):i + 1])) < 0.5 * float(seg.mean()) + 2 or
                    float(np.median(d[i + k:min(n, i + k + k // 2)])) < 0.5 * float(seg.mean()) + 2)
            if br < 0.55 and e_end > 6 and calm:
                out.append({'start': round(i / fps, 3), 'end': round((i + k) / fps, 3), 't': round((i + k / 2) / fps, 3),
                            'kind': 'dissolve', 'len_s': round(k / fps, 3), 'conf': 0.8 if br < 0.4 else 0.6,
                            'blend_ratio': round(br, 2)})
                taken[i:i + k + 1] = True
                i += k
            else:
                i += 2
    return sorted(out, key=lambda o: o['t'])


def frames_at(video, times, width, info=None):
    """Colour frames (BGR) at the given times, read in one pass (ffmpeg's select filter): {time: frame}. A time
    takes the first frame whose start is within half a frame of it."""
    info = info or probe(video)
    if not times:
        return {}
    W, H = info['width'], info['height']
    h = int(round(H * width / W / 2) * 2)
    fps = float(info['fps'] or 30.0)
    half = 0.5 / fps
    times = sorted({round(float(t), 4) for t in times})
    out = {}
    for k in range(0, len(times), 60):          # keep the filter expression short
        chunk = times[k:k + 60]
        expr = '+'.join(f'between(t,{t - half:.4f},{t + half - 1e-4:.4f})' for t in chunk)
        t0 = max(0.0, chunk[0] - 1.0)
        args = [_ff(), '-v', 'error', '-nostdin', '-threads', str(THREADS), '-ss', f'{t0:.3f}',
                '-t', f'{chunk[-1] - t0 + 1.0:.3f}', '-i', str(video), '-copyts',
                '-vf', f"select='{expr}',scale={width}:{h}:flags=area", '-fps_mode', 'passthrough', '-an', '-sn',
                '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
        r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, timeout=60)
        n = width * h * 3
        got = [np.frombuffer(r.stdout[i * n:(i + 1) * n], np.uint8).reshape(h, width, 3)
               for i in range(len(r.stdout) // n)]
        for t, f in zip(chunk, got):
            out[t] = f
    return out


def feature_scale(a, b, mask_a=None, mask_b=None, nfeatures=1500):
    """Scale, shift and match quality between two pictures from ORB features and a RANSAC similarity fit (robust to
    the part of the picture that changed): {scale, dx, dy (fractions of the width / height), inliers, ratio (inliers /
    matches), centre} or None when too few features match."""
    import cv2
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY) if a.ndim == 3 else a
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY) if b.ndim == 3 else b
    orb = cv2.ORB_create(nfeatures=nfeatures, scaleFactor=1.2, nlevels=8, fastThreshold=12)
    ka, da = orb.detectAndCompute(ga, mask_a)
    kb, db = orb.detectAndCompute(gb, mask_b)
    if da is None or db is None or len(ka) < 12 or len(kb) < 12:
        return None
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    good = []
    for pair in bf.knnMatch(da, db, k=2):
        if len(pair) == 2 and pair[0].distance < 0.78 * pair[1].distance:
            good.append(pair[0])
    if len(good) < 10:
        return None
    pa = np.float32([ka[m.queryIdx].pt for m in good])
    pb = np.float32([kb[m.trainIdx].pt for m in good])
    M, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=3.0, maxIters=3000,
                                         confidence=0.995)
    if M is None or inl is None:
        return None
    scale = float(math.hypot(M[0, 0], M[1, 0]))
    if not np.isfinite(M).all() or not math.isfinite(scale) or round(scale, 3) <= 0:
        return None
    matched = inl.ravel().astype(bool)
    if len(np.unique(pa[matched], axis=0)) < 3 or len(np.unique(pb[matched], axis=0)) < 3:
        return None
    k = int(inl.sum())
    # how much of the picture the fit covers: cells of a 3x3 grid holding at least 3 matched points (a person who
    # moved fills one or two; the whole picture zoomed fills most)
    hh, ww = ga.shape
    pin = pa[inl.ravel().astype(bool)]
    cells = np.zeros((3, 3), int)
    for x, y in pin:
        cells[min(2, int(3 * y / hh)), min(2, int(3 * x / ww))] += 1
    spread = int((cells >= 3).sum())
    s = float(math.hypot(M[0, 0], M[1, 0]))
    rot = math.degrees(math.atan2(M[1, 0], M[0, 0]))
    h, w = ga.shape
    centre = None
    if abs(s - 1) > 0.015:
        # fixed point of x' = s R x + t (rotation ignored when small)
        cx = M[0, 2] / (1 - s)
        cy = M[1, 2] / (1 - s)
        centre = [round(min(1.5, max(-0.5, cx / w)), 3), round(min(1.5, max(-0.5, cy / h)), 3)]
    return {'scale': round(s, 4), 'rotation_deg': round(rot, 2), 'dx': round(float(M[0, 2]) / w, 4),
            'dy': round(float(M[1, 2]) / h, 4), 'inliers': k, 'matches': len(good), 'ratio': round(k / len(good), 3),
            'centre': centre, 'spread': spread}


def static_mask(a, b, boxes=(), min_px=60):
    """uint8 mask (255 = use) for comparing two colour frames: leaves out text boxes (fractions) and patches of edges
    that sit exactly in the same place in both (letters or a sticker laid on top: across a cut or a zoom the footage's
    edges move; flat areas are not judged, they look alike after any move), dilated a little."""
    import cv2
    h, w = a.shape[:2]
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY) if a.ndim == 3 else a
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY) if b.ndim == 3 else b
    ea, eb = cv2.Canny(ga, 80, 160) > 0, cv2.Canny(gb, 80, 160) > 0
    both = (ea & eb).astype(np.uint8)
    # a patch where most edges stayed put (not one stray coincidence)
    dens = cv2.boxFilter(both.astype(np.float32), -1, (15, 15))
    ref = cv2.boxFilter(ea.astype(np.float32), -1, (15, 15)) + 1e-3
    stay = ((dens / ref) > 0.6) & (dens > 0.08)
    n, lab, st, _ = cv2.connectedComponentsWithStats(stay.astype(np.uint8), 8)
    keep = np.zeros((h, w), np.uint8)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= min_px:
            keep[lab == i] = 1
    mask = np.where(cv2.dilate(keep, np.ones((9, 9), np.uint8)) > 0, 0, 255).astype(np.uint8)
    for x0, y0, x1, y1 in boxes:
        mask[max(0, int((y0 - 0.01) * h)):int((y1 + 0.01) * h), max(0, int((x0 - 0.01) * w)):int((x1 + 0.01) * w)] = 0
    return mask


def verify_punch(a, b, boxes=(), min_scale=0.04):
    """Is the change between two sharp colour frames a zoom of the same picture (a punch in or out)? Features on the
    footage only (text and anything laid on top that stayed put left out: a label across a cut made two different
    pictures 'align' before), a similarity fit with at least 25 matched points and a third of the matches, little
    rotation, a scale change of min_scale or more, and points over 4 or more cells of a 3x3 grid (the whole picture,
    not a person who moved). Returns (verdict 'punch' | 'same' | 'new', the fit or None)."""
    m = static_mask(a, b, boxes)
    fs = feature_scale(a, b, mask_a=m, mask_b=m)
    if not fs or fs['inliers'] < 25 or fs['ratio'] < 0.3 or abs(fs['rotation_deg']) >= 3:
        return 'new', fs
    if fs['spread'] < 4:
        return 'same' if abs(fs['scale'] - 1) < min_scale else 'new', fs
    if abs(fs['scale'] - 1) >= min_scale:
        return 'punch', fs
    return 'same', fs


def classify_cut(frames, feat, fps, cut, hi=None):
    """What happens around a hard cut: the framing change across it (punch in / out = the same picture at another
    scale; same = the same framing, a jump cut; new = another picture), from aligning the small frames and, when that
    is unsure, from feature matches on sharper frames `hi` = (before, after) BGR; and the cut's effect: plain cut,
    whip (motion blur with a big move on both sides), zoom (fast scale change with blur), glitch (colour channels
    pulled apart)."""
    i = cut['frame']
    n = len(frames)
    sharp = feat['sharp']
    out = {}
    a, b = frames[i - 1], frames[i]
    al = scale_between(a, b)
    out['across'] = {'scale': round(al['scale'], 3), 'response': round(al['response'], 3),
                     'residual': round(al['residual'], 1), 'centre': al['centre'],
                     'shift': [round(al['dx'] / a.shape[1], 3), round(al['dy'] / a.shape[0], 3)], 'by': 'phase'}
    d_cut = cut.get('d') if cut.get('d') is not None else float(feat['d'][i])   # cuts from shots.detect carry none
    same = al['response'] > 0.3 or (al['response'] > 0.18 and al['residual'] < 0.6 * max(1.0, d_cut))
    scale = al['scale']
    if not same and hi is not None:
        fs = feature_scale(hi[0], hi[1])
        if fs and fs['inliers'] >= 25 and fs['ratio'] >= 0.3 and abs(fs['rotation_deg']) < 4:
            same = True
            scale = fs['scale']
            out['across'] = {'scale': round(scale, 3), 'inliers': fs['inliers'], 'ratio': fs['ratio'],
                             'centre': fs['centre'], 'shift': [fs['dx'], fs['dy']], 'by': 'features'}
    if same and abs(scale - 1) >= 0.04:
        out['framing'] = 'punch_in' if scale > 1 else 'punch_out'
    elif same:
        out['framing'] = 'same'
    else:
        out['framing'] = 'new'
    # blur and movement around the cut (a whip or zoom transition blurs the frames on both sides and moves fast)
    lo, hi_ = max(1, i - 4), min(n, i + 4)
    base = float(np.median(sharp[max(0, i - int(fps)):min(n, i + int(fps))])) + 1e-3
    blur = [float(sharp[j]) / base for j in range(lo, hi_)]
    before, after = [], []
    for j in (i - 2, i - 1):
        if j >= 1:
            before.append(align(frames[j - 1], frames[j], scales=(0.92, 0.96, 1.0, 1.04, 1.085)))
    for j in (i + 1, i + 2):
        if j < n:
            after.append(align(frames[j - 1], frames[j], scales=(0.92, 0.96, 1.0, 1.04, 1.085)))

    def fast(m):
        return math.hypot(m['dx'] / frames.shape[2], m['dy'] / frames.shape[1]) > 0.05

    def zooming(m):
        return abs(m['scale'] - 1) >= 0.04 and m['response'] > 0.2
    blurred_before = sum(1 for x in blur[:len(blur) // 2] if x < 0.45)
    blurred_after = sum(1 for x in blur[len(blur) // 2:] if x < 0.45)
    effect = 'cut'
    # measured on letitedit's own edits: hand-held punch cuts zoom and blur a little on one side; a whip or zoom
    # transition moves fast with motion blur on both sides of the cut
    if min(blurred_before, blurred_after) >= 1 and blurred_before + blurred_after >= 3 and (
            sum(map(fast, before)) >= 1 and sum(map(fast, after)) >= 1):
        effect = 'whip'
    elif (len(before) == 2 and len(after) == 2 and sum(map(zooming, before)) == 2 and sum(map(zooming, after)) == 2
          and min(blurred_before, blurred_after) >= 1):
        effect = 'zoom'
    out['effect'] = effect
    out['blur_ratio_min'] = round(min(blur), 2) if blur else None
    return out


# ------------------------------------------------------------------ motion inside shots

def shot_spans(cuts, gradual, n, fps):
    """[(first frame, end frame)] of each shot. A gradual transition ends one shot at its start and starts the next
    at its end."""
    edges = []
    for c in cuts:
        edges.append((c['frame'], c['frame']))
    for g in gradual:
        if g['kind'] in ('dissolve', 'fade_black', 'fade_white'):
            edges.append((int(round(g['start'] * fps)), int(round(g['end'] * fps))))
    edges.sort()
    spans = []
    s = 0
    for a, b in edges:
        if a > s:
            spans.append((s, a))
        s = max(s, b)
    if s < n:
        spans.append((s, n))
    return [(a, b) for a, b in spans if b - a >= 1]


def image_motion_name(dx, dy, responses, fps, width, height):
    horizontal = np.asarray(dx, dtype=float)[1:]
    vertical = np.asarray(dy, dtype=float)[1:]
    confidence = np.asarray(responses, dtype=float)[1:]
    unknown = {'move': 'unresolved_image_motion', 'physical_camera': 'unproven', 'by': 'image alignment'}
    if not (fps > 0 and width > 0 and height > 0):
        return unknown
    valid = np.isfinite(horizontal) & np.isfinite(vertical) & np.isfinite(confidence) & (confidence >= .25)
    if valid.sum() < 2 or valid.sum() < len(valid) / 2:
        return unknown
    horizontal_speed = float(np.median(horizontal[valid])) * fps / width
    vertical_speed = float(np.median(vertical[valid])) * fps / height
    speed = math.hypot(horizontal_speed, vertical_speed)
    direction = 'none'
    if speed <= .03:
        move = 'static_or_subject_motion'
    elif abs(horizontal_speed) >= 2 * abs(vertical_speed):
        move = 'image_pan_or_drift'
        direction = 'right' if horizontal_speed > 0 else 'left'
    elif abs(vertical_speed) >= 2 * abs(horizontal_speed):
        move = 'image_tilt_or_drift'
        direction = 'down' if vertical_speed > 0 else 'up'
    else:
        move = 'image_diagonal_drift'
        direction = ('right' if horizontal_speed > 0 else 'left') + '_' + ('down' if vertical_speed > 0 else 'up')
    return {**unknown, 'move': move, 'image_direction': direction,
            'horizontal_per_s': round(horizontal_speed, 6), 'vertical_per_s': round(vertical_speed, 6),
            'frame_fraction_per_s': round(speed, 6)}


def motion_in_shots(frames, feat, fps, spans, progress=None):
    """Per shot: camera path (shift per frame from phase correlation), zoom punches (a scale jump of 4% or more from
    one frame to the next, the rest of the shot steady), slow zoom over the shot (push in / pull out), shake bursts.
    Returns (per-shot motion dicts, events)."""
    n, h, w = frames.shape
    d = feat['d']
    shots = []
    events = []
    step_s = 0.5
    for si, (a, b) in enumerate(spans):
        L = b - a
        dx = np.zeros(L, np.float32)
        dy = np.zeros(L, np.float32)
        resp = np.ones(L, np.float32)
        for k in range(1, L):
            i = a + k
            if d[i] < 0.6:
                continue
            m = align(frames[i - 1], frames[i])
            dx[k], dy[k], resp[k] = m['dx'], m['dy'], m['response']
        # zoom punches inside the shot: a spike in frame difference that a scale change explains
        punched = set()
        for k in range(2, L - 1):
            i = a + k
            loc = _local_median(d, i, half=5)
            if d[i] < 4 or d[i] < 1.6 * (loc + 1.0) or d[i] < d[i - 1] or d[i] < d[i + 1]:
                continue
            m = scale_between(frames[i - 1], frames[i])
            plain = align(frames[i - 1], frames[i])
            if (abs(m['scale'] - 1) >= 0.04 and m['response'] > 0.25 and m['response'] > plain['response'] + 0.1
                    and m['residual'] < 0.6 * float(d[i])):
                events.append({'kind': 'punch_in' if m['scale'] > 1 else 'punch_out', 't': round(i / fps, 3),
                               'frame': i, 'scale': round(m['scale'], 3), 'centre': m['centre'], 'inside_shot': True,
                               'conf': 0.85 if m['response'] > 0.45 else 0.65})
                punched.add(k)
                dx[k] = dy[k] = 0.0
        # slow zoom: frames step_s apart, fine scales
        k = max(2, int(round(fps * step_s)))
        logs = []
        for j in range(a, b - k, k):
            m = align(frames[j], frames[j + k], scales=(0.95, 0.965, 0.98, 0.99, 1.0, 1.01, 1.02, 1.035, 1.05))
            if m['response'] > 0.12:
                logs.append(math.log(m['scale']))
        total = float(np.exp(np.sum(logs))) if logs else 1.0
        # (push-ins and pull-outs themselves: zoom_ramps() on the motion track, which tells an editor's zoom from a
        # camera that moves; this whole-shot figure caught both)
        # shake: high-frequency part of the camera path
        shake_rms = 0.0
        if L >= 8:
            path = np.cumsum(np.stack([dx, dy], 1), 0)
            ker = np.ones(7) / 7.0
            smooth = np.stack([np.convolve(path[:, 0], ker, 'same'), np.convolve(path[:, 1], ker, 'same')], 1)
            hf = np.linalg.norm(path - smooth, axis=1) / w
            shake_rms = float(np.sqrt(np.mean(hf[3:-3] ** 2))) if L > 8 else 0.0
            # bursts: 0.15-1.5 s where the jitter is 3x the shot's median and over 1.2% of the width, going back and
            # forth (at least two reversals of the frame-to-frame move): a shake effect or a bump, not a pan
            med = float(np.median(hf)) + 1e-4
            hot = (hf > max(0.012, 3 * med))
            j = 0
            while j < L:
                if not hot[j]:
                    j += 1
                    continue
                e = j
                while e + 1 < L and hot[e + 1]:
                    e += 1
                seg = np.stack([dx[max(1, j - 1):e + 2], dy[max(1, j - 1):e + 2]], 1)
                main = seg[:, 0] if np.abs(seg[:, 0]).sum() >= np.abs(seg[:, 1]).sum() else seg[:, 1]
                signs = np.sign(main[np.abs(main) > 0.3])
                reversals = int((signs[1:] != signs[:-1]).sum()) if len(signs) > 1 else 0
                if (max(3, int(0.15 * fps)) <= (e - j + 1) <= int(1.5 * fps) and reversals >= 2
                        and not any(j - 2 <= q <= e + 2 for q in punched)):
                    events.append({'kind': 'shake', 't': round((a + j) / fps, 3), 'end': round((a + e + 1) / fps, 3),
                                   'amount': round(float(hf[j:e + 1].max()), 3), 'reversals': reversals, 'conf': 0.6})
                j = e + 1
        speed = float(np.median(np.hypot(dx[1:], dy[1:]))) / w if L > 1 else 0.0
        shots.append({'camera_speed': round(speed * fps, 3), 'shake_rms': round(shake_rms, 4),
                      'zoom_over_shot': round(total, 3), 'moving': bool(speed * fps > 0.03),
                      'named_motion': image_motion_name(dx, dy, resp, fps, w, h)})
        if progress:
            progress((si + 1) / max(1, len(spans)))
    return shots, events


# ------------------------------------------------------------------ zooms over time: push-ins vs a moving camera

MOTION = {'fps': 6.0, 'width': 270, 'k': 3, 'eps': 0.004, 'min_total': 0.035, 'min_s': 0.8, 'min_ramp_s': 2.0,
          'rot_std': 1.2, 'rot_mean': 0.6, 'h_gain': 0.2, 'smooth': 0.9, 'min_ratio': 0.25, 'static': 0.2}


def motion_track(video, info, fps=None, width=None):
    """Grey frames for measuring motion over time: MOTION['width'] px wide at MOTION['fps'] (sharper than the
    analysis frames, far fewer of them). (frames, fps)."""
    fps = fps or MOTION['fps']
    width = width or MOTION['width']
    h = int(round(info['height'] * width / info['width'] / 2) * 2)
    return decode_grey(info.get('path') or video, width, h, fps=fps, native=info.get('fps')), fps


def track_fit(a, b, mask=None):
    """The motion between two grey frames from tracked corners (Lucas-Kanade both ways, points that come back to
    within 0.8 px kept): a similarity fit {s, rot (deg), M, ratio (inliers), res (median px off the fit), flow (median
    px moved), h_gain (how much better a homography fits: perspective, parallax), fixed (the point that stays put, as
    frame fractions, when the scale changes enough to place it)} or None."""
    import cv2
    p0 = cv2.goodFeaturesToTrack(a, maxCorners=500, qualityLevel=0.005, minDistance=5, mask=mask, blockSize=5)
    if p0 is None or len(p0) < 20:
        return None
    p1, st, _ = cv2.calcOpticalFlowPyrLK(a, b, p0, None, winSize=(21, 21), maxLevel=3)
    p0r, st2, _ = cv2.calcOpticalFlowPyrLK(b, a, p1, None, winSize=(21, 21), maxLevel=3)
    fb = np.linalg.norm((p0 - p0r).reshape(-1, 2), axis=1)
    ok = (st.ravel() == 1) & (st2.ravel() == 1) & (fb < 0.8)
    if ok.sum() < 20:
        return None
    q0, q1 = p0.reshape(-1, 2)[ok], p1.reshape(-1, 2)[ok]
    M, inl = cv2.estimateAffinePartial2D(q0, q1, method=cv2.RANSAC, ransacReprojThreshold=1.0, maxIters=2000)
    if M is None or inl is None:
        return None
    s = math.hypot(M[0, 0], M[1, 0])
    rot = math.degrees(math.atan2(M[1, 0], M[0, 0]))
    res = np.linalg.norm(q0 @ M[:, :2].T + M[:, 2] - q1, axis=1)
    _, inlh = cv2.findHomography(q0, q1, cv2.RANSAC, 1.0)
    h, w = a.shape
    fixed = None
    if abs(s - 1) >= 0.008:
        try:
            x = np.linalg.solve(np.eye(2) - M[:, :2], M[:, 2])
            fixed = [float(x[0] / w), float(x[1] / h)]
        except np.linalg.LinAlgError:
            fixed = None
    ratio = float(inl.mean())
    flow = np.linalg.norm(q1 - q0, axis=1)
    return {'s': s, 'rot': rot, 'ratio': ratio, 'res': float(np.median(res)), 'flow': float(np.median(flow)),
            'h_gain': (float(inlh.mean()) - ratio) if inlh is not None else 0.0, 'fixed': fixed,
            # points that did not move at all (a car's dashboard, something laid on top): a digital zoom moves all
            'static': float((flow < 0.3).mean())}


def zoom_ramps(track, fps, spans, boxes_at=None, settings=None):
    """Slow zooms inside shots: runs where the picture keeps scaling the same way, from frames k steps apart on the
    motion track. A run is a digital push-in / pull-out (an editor's zoom) when it fits a pure scaling: no perspective
    (h_gain), little rotation jitter, a smooth ramp, its fixed point inside the frame; otherwise the camera moved
    (closer or away, with parallax and wobble, or a tracking shot whose 'zoom' centre is off the frame). Measured on
    letitedit's ground truth: physical pull-backs and walks gain 0.31-0.40 from a homography, digital zooms 0.04-0.12;
    handheld moves rotate 1.4-5.7 degrees per half second, digital zooms on steadier footage under 1.2. A digital zoom
    on footage that itself moves hard is lost in the camera's own motion (not found).
    Returns (zooms [{kind push_in | pull_out, t, end, scale, conf, ...}], camera [{kind camera_forward |
    camera_back, t, end, scale, why}])."""
    st = {**MOTION, **(settings or {})}
    k = int(st['k'])
    n, H, W = track.shape
    zooms, camera = [], []
    for a, b in spans:
        i0, i1 = int(math.ceil(a * fps)), min(n - 1, int(b * fps))
        series = []
        for j in range(i0, i1 - k + 1):
            mask = None
            if boxes_at:
                bx = boxes_at(j / fps)
                if bx:
                    mask = np.full((H, W), 255, np.uint8)
                    for x0, y0, x1, y1 in bx:
                        mask[max(0, int((y0 - 0.02) * H)):int((y1 + 0.02) * H),
                             max(0, int((x0 - 0.02) * W)):int((x1 + 0.02) * W)] = 0
            m = track_fit(track[j], track[j + k], mask)
            if m:
                m['t'] = j / fps
                m['ls'] = math.log(max(1e-6, m['s']))
                series.append(m)
        if len(series) < 3:
            continue
        sign = [1 if m['ls'] > st['eps'] else -1 if m['ls'] < -st['eps'] else 0 for m in series]
        j = 0
        while j < len(series):
            if sign[j] == 0:
                j += 1
                continue
            sg, e, bad = sign[j], j, 0
            while e + 1 < len(series):
                nxt = sign[e + 1]
                if nxt == sg:
                    e += 1
                    bad = 0
                elif bad == 0 and e + 2 < len(series) and sign[e + 2] == sg:
                    e += 1          # one step that disagrees: noise
                    bad = 1
                else:
                    break
            run = series[j:e + 1]
            t0, t1 = run[0]['t'], run[-1]['t'] + k / fps
            total = sum(m['ls'] for m in run) / k
            j = e + 1
            if abs(total) < st['min_total'] or t1 - t0 < st['min_s']:
                continue
            ls = np.array([m['ls'] for m in run])
            rot = np.array([m['rot'] for m in run])
            fixed = [m['fixed'] for m in run if m['fixed'] and abs(m['ls']) >= 0.008]
            fx = np.median(np.array(fixed), axis=0).tolist() if fixed else None
            feat = {'smooth': round(float(ls.std() / (abs(ls.mean()) + 1e-9)), 2), 'rot_std': round(float(rot.std()), 2),
                    'rot_mean': round(float(rot.mean()), 2),
                    'h_gain': round(float(np.median([m['h_gain'] for m in run])), 3),
                    'ratio': round(float(np.median([m['ratio'] for m in run])), 2),
                    'static': round(float(np.median([m['static'] for m in run])), 2),
                    'fixed': [round(v, 2) for v in fx] if fx else None}
            why = []
            if t1 - t0 < st['min_ramp_s']:
                why.append(f"shorter than {st['min_ramp_s']:g} s (an editor's push-in runs for seconds)")
            if feat['static'] >= st['static']:
                why.append('part of the picture does not move (seen from a vehicle, or something laid on top)')
            if feat['h_gain'] > st['h_gain']:
                why.append('perspective changes (camera or subject motion is possible)')
            if feat['rot_std'] > st['rot_std'] or abs(feat['rot_mean']) > st['rot_mean']:
                why.append('the picture turns and wobbles (handheld)')
            if feat['smooth'] > st['smooth']:
                why.append('the scale changes unevenly')
            if fx and not (-0.15 <= fx[0] <= 1.15 and -0.15 <= fx[1] <= 1.15):
                why.append('the zoom centre is off the frame (a tracking move)')
            if feat['ratio'] < st['min_ratio']:
                why.append('too little of the picture fits one zoom')
            ev = {'t': round(t0, 3), 'end': round(t1, 3), 'scale': round(math.exp(total), 3),
                  'log_scale_per_s': round(total / max(t1 - t0, 1e-6), 6), **feat}
            if not why:
                sure = feat['ratio'] >= 0.5 and feat['rot_std'] <= 0.6 and feat['h_gain'] <= 0.12
                zooms.append({'kind': 'push_in' if total > 0 else 'pull_out', **ev, 'conf': 0.85 if sure else 0.7,
                              'centre': ev['fixed'], 'by': 'motion track',
                              'move': 'digital_push_in_candidate' if total > 0 else 'digital_pull_out_candidate'})
            else:
                camera.append({'kind': 'camera_forward' if total > 0 else 'camera_back', **ev, 'why': why,
                               'move': 'forward_motion_candidate' if total > 0 else 'backward_motion_candidate',
                               'physical_camera': 'unproven'})
    return zooms, camera


# ------------------------------------------------------------------ picture: everything from the grey frames

def picture_frames(video, info, settings=SETTINGS, progress=None):
    """The grey analysis frames and their frame-to-frame features: (frames, feat, fps)."""
    afps, w, h = analysis_geometry(info, settings)
    frames = decode_grey(video, w, h, fps=afps if abs(afps - info['fps']) > 0.01 else None, progress=progress,
                         total_s=info['duration'], native=info['fps'])
    feat = frame_features(frames)
    return frames, feat, afps


def picture_events(video, info, frames, feat, afps, masks=None, settings=SETTINGS, progress=None, use_shots=True,
                   text_boxes=None, native_effects=None):
    """Cuts (mine fused with shots.detect's), transitions, zoom / shake events and shots. text_boxes(t) -> [boxes]
    of text on screen at t (left out when zooms are measured)."""
    n = len(frames)
    t0 = time.monotonic()
    from letitedit.looks.style_import_visual import inversion_events, analyse as native_visual
    native_error = None
    if native_effects is None:
        try:
            native_effects = native_visual(video)
        except (ValueError, OSError, ImportError) as error:
            native_effects = {}
            native_error = f'native visual analysis failed: {type(error).__name__}: {error}'[:200]
    if native_effects.get('decode_complete'):
        native_indices = np.rint(np.arange(n) * native_effects['fps'] / afps).astype(int)
        inverted = np.zeros(n, bool)
        for event in native_effects.get('events', []):
            inverted |= (native_indices >= event['start_frame']) & (native_indices < event['end_frame'])
        if inverted.any():
            frames = frames.copy()
            frames[inverted] = 255 - frames[inverted]
            feat = frame_features(frames)
    else:
        normalised = inversion_events((np.repeat(frame[:, :, None], 3, axis=2) for frame in frames), afps)
        if normalised['events']:
            frames = frames.copy()
            for event in normalised['events']:
                frames[event['start_frame']:event['end_frame']] = 255 - frames[event['start_frame']:event['end_frame']]
            feat = frame_features(frames)
    cuts = detect_cuts(frames, feat, afps, settings, masks=masks)
    other, notes = [], []
    if native_error:
        notes.append(native_error)
    if use_shots:
        try:
            import letitedit.footage.shots as _shots
            sd = _shots.detect(str(video), settings={'workers': 2})
            other = [c for c in sd.get('cuts') or [] if c.get('kind') in ('cut', 'punch')]
            notes.append(f"shots.detect: {len(other)} cuts ({sd.get('method', '')[:80]})")
        except Exception as e:  # noqa: BLE001
            notes.append(f'shots.detect failed: {type(e).__name__}: {e}'[:200])
    cuts = fuse_cuts(cuts, other, afps, n)
    gradual = detect_gradual(frames, feat, afps, cuts, settings)
    spans = [(int(g['start'] * afps) - 1, int(g['end'] * afps) + 1) for g in gradual
             if g['kind'] in ('dissolve', 'fade_black', 'fade_white', 'fade_in', 'fade_out', 'flash')]
    cuts = [c for c in cuts if not any(a <= c['frame'] <= b for a, b in spans)]
    zooms = []
    sw = 540 if info['width'] <= info['height'] else 960
    hi = frames_at(video, [t for c in cuts for t in ((c['frame'] - 1) / afps, c['frame'] / afps)], sw, info)

    def near(t):
        if not hi:
            return None
        k = min(hi, key=lambda x: abs(x - t))
        return hi[k] if abs(k - t) < 0.75 / afps else None
    for c in cuts:
        pair = (near((c['frame'] - 1) / afps), near(c['frame'] / afps))
        k = classify_cut(frames, feat, afps, c, hi=pair if pair[0] is not None and pair[1] is not None else None)
        if k['framing'] in ('punch_in', 'punch_out') and pair[0] is not None and pair[1] is not None:
            # checked on the sharp frames with text and anything laid on top left out
            verdict, fs = verify_punch(pair[0], pair[1], text_boxes(c['t']) if text_boxes else ())
            if verdict != 'punch':
                k['framing'] = verdict
                k['punch_check'] = 'not a zoom of the same picture'
            elif fs:
                k['across'] = {'scale': round(fs['scale'], 3), 'inliers': fs['inliers'], 'ratio': fs['ratio'],
                               'centre': fs['centre'], 'spread': fs['spread'], 'by': 'features, overlays left out'}
                k['framing'] = 'punch_in' if fs['scale'] > 1 else 'punch_out'
        c.update(k)
        if k['framing'] in ('punch_in', 'punch_out'):
            zooms.append({'kind': k['framing'], 't': c['t'], 'frame': c['frame'], 'scale': k['across']['scale'],
                          'centre': k['across'].get('centre'), 'at_cut': True, 'conf': c['conf']})
        c['kind'] = ('punch' if k['framing'] in ('punch_in', 'punch_out') else
                     'jump' if k['framing'] == 'same' else 'cut')
        # a cut only the frame detector found counts when it is a new picture or a big jump over most of the
        # frame; the rest stay listed as unsure (measured on 26 edits: of the frame detector's own finds 20 of 21
        # were real on letitedit's talking-head Shorts but 11 of 52 on close-up phone footage)
        if c['by'] == 'frames' and not (k['framing'] == 'new' or ((c.get('ratio') or 0) >= 5
                                                                   and (c.get('share') or 0) >= 0.5)):
            c['conf'] = min(c['conf'], 0.5)
            c['kind'] = 'jump?'
    spans = shot_spans(cuts, gradual, n, afps)
    shot_motion, events = motion_in_shots(frames, feat, afps, spans, progress=progress)
    # punches inside a shot: the frame-difference finds checked like those at cuts, on sharp frames
    inside = [e for e in events if e['kind'] in ('punch_in', 'punch_out')]
    if inside:
        hi2 = frames_at(video, [t for e in inside for t in ((e['frame'] - 1) / afps, e['frame'] / afps)], sw, info)
        for e in inside:
            def near2(t):
                if not hi2:
                    return None
                q = min(hi2, key=lambda x: abs(x - t))
                return hi2[q] if abs(q - t) < 0.75 / afps else None
            a_, b_ = near2((e['frame'] - 1) / afps), near2(e['frame'] / afps)
            if a_ is None or b_ is None:
                continue
            verdict, fs = verify_punch(a_, b_, text_boxes(e['t']) if text_boxes else ())
            if verdict == 'punch' and fs:
                e.update({'scale': round(fs['scale'], 3), 'kind': 'punch_in' if fs['scale'] > 1 else 'punch_out',
                          'centre': fs['centre'], 'spread': fs['spread']})
                zooms.append(e)
    # push-ins and pull-outs over time, told apart from a moving camera
    camera_moves = []
    try:
        track, tfps = motion_track(video, info)
        ramps, camera_moves = zoom_ramps(track, tfps, [(a / afps, b / afps) for a, b in spans], text_boxes)
        zooms += ramps
    except Exception as e:  # noqa: BLE001
        notes.append(f'zoom ramps failed: {type(e).__name__}: {e}'[:200])
    transitions = [dict(g) for g in gradual]
    for event in native_effects.get('events', []):
        transitions.append({**event, 'start': event['t'], 'len_s': event['len'],
                            'sound': None, 'sound_status': 'not measured by picture analysis'})
    for c in cuts:
        if c.get('effect') and c['effect'] != 'cut':
            transitions.append({'t': c['t'], 'start': c['t'], 'end': c['t'], 'kind': c['effect'], 'len_s': 0.0,
                                'conf': 0.6})
    transitions.sort(key=lambda g: g['t'])
    shot_list = []
    for (a, b), m in zip(spans, shot_motion):
        shot_list.append({'start': round(a / afps, 3), 'end': round(b / afps, 3), 'len': round((b - a) / afps, 3), **m})
    return {'analysis': {'fps': round(afps, 3), 'size': [int(frames.shape[2]), int(frames.shape[1])], 'frames': n,
                         'took_s': round(time.monotonic() - t0, 1), 'notes': notes},
            'cuts': cuts, 'transitions': transitions, 'zooms': sorted(zooms, key=lambda z: z['t']),
            'shake': [e for e in events if e['kind'] == 'shake'], 'shots': shot_list, 'camera_moves': camera_moves,
            'native_effects': native_effects}


def picture(video, info, settings=SETTINGS, progress=None, keep_frames=False, use_shots=True):
    """Cuts, transitions, zooms and shots without the text masks (quick look; analyse() does the full job)."""
    frames, feat, afps = picture_frames(video, info, settings)
    out = picture_events(video, info, frames, feat, afps, settings=settings, use_shots=use_shots)
    if keep_frames:
        out['_frames'], out['_feat'] = frames, feat
    return out


# ------------------------------------------------------------------ one video, every part

def cache_key(video, settings):
    import letitedit.footage.footage_notes as footage_notes
    from letitedit.looks.style_import_motion import SPEED_VERSION
    h = hashlib.sha256(json.dumps({**settings, 'v': VERSION, 'speed_detector': SPEED_VERSION},
                                 sort_keys=True).encode()).hexdigest()[:10]
    return f'{footage_notes.key(str(video))}-{h}'


PARTS = CACHE / 'parts'
PARTS_VERSION = {'ocr': 1, 'faces': 1}


def part_cached(video, name, params, make, samples=None):
    """A slow part of the analysis that a change to the rest does not touch (OCR, faces of the sampled frames), kept
    per file content and its own settings, so a report made again after a code change reuses it. Sample frame paths
    are stored by name and mapped back to this run's samples folder. make() -> JSON-able value."""
    import letitedit.footage.footage_notes as footage_notes
    key = hashlib.sha256(json.dumps({**params, 'v': PARTS_VERSION.get(name, 1)}, sort_keys=True).encode()).hexdigest()[:10]
    f = PARTS / f'{footage_notes.key(str(video))}-{name}-{key}.json'
    folder = str(Path(samples[0][1]).parent) if samples else None
    if f.exists():
        try:
            val = json.loads(f.read_text(encoding='utf-8-sig'))
            return _paths(val, lambda p: os.path.join(folder, p) if folder else p)
        except (ValueError, OSError):
            pass
    val = make()
    try:
        PARTS.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix('.tmp')
        tmp.write_text(json.dumps(_paths(val, lambda p: os.path.basename(p)), default=_json_default), encoding='utf-8')
        os.replace(tmp, f)
    except OSError:
        pass
    return val


def _paths(val, fn):
    """val with every 'path' value (a sample frame) passed through fn."""
    if isinstance(val, dict):
        return {k: (fn(v) if k == 'path' and isinstance(v, str) else _paths(v, fn)) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_paths(v, fn) for v in val]
    return val


def face_time(face_track, duration, sample_step):
    """Time supported by face samples; gaps beyond one sample interval remain unmeasured.

    Face presence is not evidence that a shot is talking-head footage rather than b-roll.
    """
    duration = max(0.0, float(duration))
    step = float(sample_step)
    if not math.isfinite(step) or step <= 0:
        raise ValueError('sample_step must be positive and finite')
    samples = sorted({float(at): bool(faces) for at, faces in face_track
                      if math.isfinite(float(at)) and 0 <= float(at) <= duration}.items())
    intervals = []
    for index, (at, present) in enumerate(samples):
        start = max(0.0, at - step / 2,
                    (samples[index - 1][0] + at) / 2 if index else 0.0)
        end = min(duration, at + step / 2,
                  (at + samples[index + 1][0]) / 2 if index + 1 < len(samples) else duration)
        if end > start:
            intervals.append((start, end, present))
    return intervals


def face_coverage(intervals, start, end):
    """Duration-weighted face, non-face and unknown coverage in a half-open span."""
    duration = max(0.0, end - start)
    face = nonface = 0.0
    for first, last, present in intervals:
        overlap = max(0.0, min(last, end) - max(first, start))
        if present:
            face += overlap
        else:
            nonface += overlap
    measured = face + nonface
    return {'face_seconds': round(face, 4), 'nonface_seconds': round(nonface, 4),
            'unknown_seconds': round(max(0.0, duration - measured), 4),
            'measured_share': round(measured / duration, 4) if duration else None,
            'face_share': round(face / duration, 4) if duration else None,
            'nonface_share': round(nonface / duration, 4) if duration else None}


# A measuring step's error: written in full to step-errors.log beside the reference's report; the report keeps a short
# form that always holds the exception line (a worker's traceback ends with the cause).
ERROR_LOG = 'step-errors.log'
# A text worker the PC refused memory waits for room, then runs once more (it peaks at about 1 GB with Windows OCR).
STEP_WORKER_GB = 2.0
MEMORY_WAIT_S = float(os.environ.get('LETITEDIT_LEARN_MEMORY_WAIT_S', '600'))
MEMORY_POLL_S = 5.0
MEMORY_STEADY_S = 10.0          # the room has to stay this long: a squeeze comes and goes


def short_error(error, limit=400):
    """A step's error in at most limit characters, the exception line always kept: a worker's traceback gives its
    last exception (its type and message, never the head of the traceback); any other error its type and message. A
    longer one keeps its start and its end (where Windows puts the error code)."""
    text = str(error).strip()
    lines = text.splitlines()
    heads = [i for i, line in enumerate(lines) if line.startswith('Traceback (most recent call last)')]
    if heads:
        rest = lines[heads[-1] + 1:]
        first = next((i for i, line in enumerate(rest) if line.strip() and not line[:1].isspace()), None)
        out = ' '.join(line.strip() for line in rest[first:] if line.strip()) if first is not None else text
    else:
        out = ' '.join(line.strip() for line in lines if line.strip())
        if isinstance(error, BaseException):
            out = f'{type(error).__name__}: {out}'
    if len(out) > limit:
        head = int(limit * 0.4)
        out = out[:head].rstrip() + ' … ' + out[-(limit - head - 3):].lstrip()
    return out


def log_step_error(folder, step, error, note=''):
    """Writes a step's whole error to <folder>/step-errors.log (beside the reference's report.json, private); returns
    the log's path, or None when it can't be written."""
    import datetime
    import traceback
    try:
        log = Path(folder) / ERROR_LOG
        log.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(error, BaseException):
            body = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        else:
            body = str(error)
        with open(log, 'a', encoding='utf-8') as handle:
            handle.write(f'--- {datetime.datetime.now().isoformat(timespec="seconds")} {step}'
                         f'{": " + note if note else ""}\n{body.rstrip()}\n')
        return str(log)
    except OSError:
        return None


def step_error(rep, errors, key, error, limit=400):
    """A failed step: its whole error into the log, its short form (exception line kept) into errors[key] (when errors
    is given) and returned."""
    log = log_step_error(rep.get('folder') or '.', key, error)
    if log:
        rep['errors_log'] = log
    short = short_error(error, limit)
    if errors is not None:
        errors[key] = short
    return short


def retry_cached(rep):
    """True when a cached report has a step that ran short of memory or time: measured again, since the person was
    told to learn again when the PC has room."""
    import letitedit.looks.learned_looks as learned_looks
    return any(learned_looks.memory_short(message) or learned_looks.TIMED_OUT.search(str(message))
               for message in (rep.get('errors') or {}).values())


def wait_for_memory(what, need_gb=None, progress=None, wait_s=None):
    """After a step the PC refused memory: asks letitedit's idle model helpers to end (memory_room.make_room), then
    waits until need_gb GB is free to promise and stays so for MEMORY_STEADY_S, at most wait_s (MEMORY_WAIT_S).
    progress(message) hears that it is waiting. Returns {'needed_gb', 'free_gb', 'waited_s', 'room'}."""
    import letitedit.core.memory_room as memory_room
    need = need_gb if need_gb is not None else STEP_WORKER_GB + memory_room.RESERVE_GB
    wait_s = MEMORY_WAIT_S if wait_s is None else wait_s
    t0 = time.monotonic()
    message = f'waiting for memory to free up, then {what} runs once more'
    if progress:
        progress(message)
    memory_room.make_room(need, what)
    steady = None
    free = memory_room.memory_gb()[1]
    while free is not None and time.monotonic() - t0 < wait_s:
        now = time.monotonic()
        if free >= need:
            steady = now if steady is None else steady
            if now - steady >= MEMORY_STEADY_S:
                break
        else:
            steady = None
        if progress:
            progress(message)
        time.sleep(MEMORY_POLL_S)
        free = memory_room.memory_gb()[1]
    return {'needed_gb': round(need, 1), 'free_gb': None if free is None else round(free, 1),
            'waited_s': round(time.monotonic() - t0, 1), 'room': free is None or free >= need}


def bounded_text(stage, folder, budget_s, progress=None, **request):
    """Runs the captions or typography stage in its own worker (style_import_text_worker.py) within budget_s. A worker
    the PC refused memory (memory_short) has its error logged, waits for room (wait_for_memory) and runs once more;
    any other failure, or a second one, raises with the worker's whole error."""
    import letitedit.looks.learned_looks as learned_looks
    try:
        return _bounded_text_once(stage, folder, budget_s, dict(request))
    except Exception as error:  # noqa: BLE001
        if not learned_looks.memory_short(error):
            raise
        log_step_error(folder, stage, error, 'the PC ran short of memory; waiting for room to run it once more')
    # outside the handler, so a second failure is logged on its own
    wait_for_memory(f'the {stage} step', progress=progress)
    return _bounded_text_once(stage, folder, budget_s, dict(request))


def _bounded_text_once(stage, folder, budget_s, request):
    import uuid
    from letitedit.core import paths as core_paths
    identity = uuid.uuid4().hex
    incoming = Path(folder) / f'.text-{identity}.json'
    outgoing = Path(folder) / f'.text-{identity}-result.json'
    request.update(stage=stage, folder=str(folder), budget_s=budget_s)
    incoming.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
    worker = core_paths.BRIDGE / 'style_import_text_worker.py'
    process = None
    try:
        process = subprocess.Popen([sys.executable, str(worker), str(incoming), str(outgoing)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = process.communicate(timeout=budget_s)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                try:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   capture_output=True, timeout=15, check=False)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            process.kill()
            process.communicate(timeout=15)
            raise TimeoutError(f'{stage} exceeded {budget_s:g} seconds; this detail was not learned') from None
        if process.returncode:
            # the whole error (its end holds the cause): the report keeps short_error of it, step-errors.log all of it
            raise RuntimeError((stderr or stdout or f'{stage} worker failed')[-20000:])
        return json.loads(outgoing.read_text(encoding='utf-8-sig'))
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=15)
        incoming.unlink(missing_ok=True)
        outgoing.unlink(missing_ok=True)


def _analyse_sound(prog, sound, words, video, timed, S, info, rep, log, check, separate, classify_sfx):
    """Measure sound, or reuse cached words when sound analysis is disabled."""
    # 4. sound (speech first: captions and triggers need the words)
    prog(0.5, 'speech, music and sound effects')
    if not sound:
        # picture and text only (a quick look, or work on those parts): the words from the transcript cache when
        # there is one, no GPU model and no wait for the render lock
        if words is None:
            try:
                import letitedit.footage.speech as speech
                words = speech.cached_words(str(video)) or []
            except Exception:  # noqa: BLE001
                words = []
        sound = {'skipped': True, 'note': 'sound not measured in this run (sound=False)'}
    else:
        try:
            sound, words = timed('sound', S.analyse, video, info, cuts=rep['cuts'], overlays=[],
                                 progress=(lambda x, m='': prog(0.5 + 0.25 * x, m or 'sound')), log=log, check=check,
                                 separate=separate, classify=classify_sfx, words=words,
                                 flashes=[g['t'] for g in rep.get('transitions') or []
                                          if g.get('kind') in ('invert', 'flash') and g.get('t') is not None],
                                 picture_events=S.picture_event_times(rep, titles=False))
        except Exception as e:  # noqa: BLE001
            sound, words = {'error': step_error(rep, None, 'sound', e)}, words or []
    rep['sound'] = sound
    words = words or []
    return sound, words


def _analyse_captions(prog, T, events, words, dur, rep, ocr_status, timed, folder, st, info, video, afps, errors, check):
    """Classify text and measure captions and optional typography."""
    # 5. text roles and caption style
    prog(0.76, 'captions')
    events = T.classify_text(events, words, dur, rep['cuts'])
    rep['text_events'] = [{k: v for k, v in e.items() if k not in ('readings',)} for e in events]
    rep['ocr'] = ocr_status

    try:
        rep['captions'] = timed('caption style', bounded_text, 'captions', folder, st['text_budget_s'],
                                progress=lambda message: prog(0.76, message),
                                events=events, info=info, video=str(video), words=words, fps=afps)
    except Exception as e:  # noqa: BLE001
        rep['captions'] = {'error': step_error(rep, errors, 'captions', e)}
    if st.get('typography', True):
        prog(0.79, 'bounded typography detail')
        try:
            rep['typography'] = timed('typography', bounded_text, 'typography', folder, st['text_budget_s'],
                                      progress=lambda message: prog(0.79, message),
                                      video=str(video), events=events, info=info,
                                      fps=st.get('typography_fps', 15), max_events=st.get('typography_max_events'))
        except Exception as error:
            rep['typography'] = {'error': step_error(rep, errors, 'typography', error)}
    else:
        rep['typography'] = {'skipped': True, 'note': 'Dense typography explicitly disabled.'}
    if st.get('font_styles', False) and isinstance(rep.get('typography'), dict):
        prog(0.8, 'font styles')
        try:
            import letitedit.looks.style_import_typography as style_import_typography
            rep['typography']['styles'] = timed('font styles', style_import_typography.font_styles, video, folder,
                                                check=check, budget_s=st.get('font_styles_budget_s', 600))
        except Exception as error:  # noqa: BLE001
            rep['typography']['styles'] = {'error': step_error(rep, errors, 'font_styles', error)}
    if st.get('typography_native', False):
        try:
            import letitedit.looks.style_import_typography as style_import_typography
            rep['typography']['native_inventory'] = timed(
                'native typography', style_import_typography.native_inventory, video, folder,
                band=st.get('typography_native_band', [0, 0, 1, 1]),
                start_s=st.get('typography_native_start_s', 0), end_s=st.get('typography_native_end_s'))
        except Exception as error:
            rep['typography']['native_inventory'] = {'error': step_error(rep, errors, 'typography_native', error)}
    roles = {}
    for e in events:
        roles[e['role']] = roles.get(e['role'], 0) + 1
    rep['on_screen_text'] = {'events_by_role': roles,
                             'watermarks': [e['text'] for e in events if e['role'] == 'watermark'][:5],
                             'titles': [e['text'] for e in events if e['role'] == 'title'][:10],
                             'labels': [e['text'] for e in events if e['role'] == 'label'][:20],
                             'text_pops': [e['text'] for e in events if e['role'] == 'text_pop'][:20]}
    return events


def _analyse_overlays(prog, timed, L, frames, feat, afps, rep, events, face_track, words, video, info, samples, dur, sound, kind, S, errors):
    """Measure overlays and associate them with sound effects."""
    # 6. overlays
    prog(0.82, 'overlays and pop-ups')
    try:
        pic_ov = timed('overlays', L.detect, frames, feat, afps, rep['cuts'], events, face_track, words,
                       spans=[(g.get('start', g['t']), g.get('end', g['t'])) for g in rep['transitions']], add_ocr=False)
        pic_ov = L.check_looks(pic_ov, video, info)
        # one event per thing on screen: text read by OCR and picture finds joined (labels read line by line and
        # again and again were counted many times; caption words popping in are captions)
        cards = L.card_shots(rep['shots'], samples)
        rep['cards'] = [{'t': round(a, 3), 'end': round(b, 3)} for a, b in cards]
        ov = L.elements(pic_ov, events, words, rep['cuts'], afps, dur, face_track, cards=cards, frames=frames,
                        samples=samples)
        for c in rep['cards']:
            c['text'] = ' / '.join(o['text'] for o in ov if o.get('role') == 'card' and o.get('text')
                                   and c['t'] - 0.1 <= o['t'] <= c['end'])[:200]
        rep['overlays_dropped'] = [{k: v for k, v in d.items() if k in ('t', 'end', 'box', 'text', 'why', 'conf')}
                                   for d in getattr(L.elements, 'dropped', [])][:60]
        # how each one comes in and goes out (cut, fade, slide, scale), at the file's own frame rate
        try:
            import letitedit.looks.style_import_motion as MO
            ov = timed('overlay motion', MO.overlay_motion, video, info, ov)
        except Exception as e:  # noqa: BLE001
            step_error(rep, errors, 'overlay_motion', e, 300)
        sfx_t = [s['t'] for s in (sound.get('sfx') or {}).get('events', [])] if isinstance(sound, dict) else []
        for o in ov:
            o['sfx'] = any(-0.25 <= s - o['t'] <= 0.35 for s in sfx_t)
        for s in (sound.get('sfx') or {}).get('events', []) if isinstance(sound, dict) else []:
            s['at_overlay'] = any(-0.25 <= s['t'] - o['t'] <= 0.35 for o in ov if o.get('conf', 0) >= 0.5)
        rep['overlays'] = {'events': ov, **L.summarise(ov, dur, kind)}
        if isinstance(sound, dict) and sound.get('sfx'):
            vis = ([c['t'] for c in rep['cuts']] + [g.get('start', g['t']) for g in rep['transitions']]
                   + [z['t'] for z in rep['zooms'] if z['kind'] in ('punch_in', 'punch_out')]
                   + [e['t'] for e in events if e.get('role') in ('title', 'label', 'text_pop')]
                   + [o['t'] for o in ov if o.get('conf', 0) >= 0.5] + [o['end'] for o in ov if o.get('conf', 0) >= 0.5])
            sound['sfx'] = S.gate_sfx(sound['sfx'], vis, (sound.get('music') or {}).get('music_share'),
                                      picture_events=S.picture_event_times({**rep, 'text_events': events}))
            for s_ in sound['sfx']['events']:
                s_['at_overlay'] = any(-0.25 <= s_['t'] - o['t'] <= 0.35 for o in ov if o.get('conf', 0) >= 0.5)
            ev_ = sound['sfx']['events']
            sound['sfx']['at_overlays_share'] = round(sum(1 for x in ev_ if x['at_overlay']) / len(ev_), 3) if ev_ else None
    except Exception as e:  # noqa: BLE001
        import traceback
        rep['overlays'] = {'events': [], 'error': step_error(rep, errors, 'overlays', e),
                           'where': traceback.format_exc()[-700:]}


def _analyse_layout(prog, L, events, rep, timed, frames, afps, errors):
    """Measure split screens and picture in picture around text."""
    # 6b. split screens, insets (picture-in-picture) and speed changes
    prog(0.86, 'layouts and speed')
    try:
        import letitedit.looks.style_import_motion as MO
        caps_ = [e for e in events if e.get('role') == 'caption']
        band_ = L.caption_band(caps_)

        def text_between(t0, t1, ev=events, band=band_):
            # text on screen then, and the captions' band all the time (words popping in change on their own)
            return [e['box'] for e in ev if e['t'] <= t1 and e['end'] >= t0] + ([[0.0, band[0], 1.0, band[1]]] if band
                                                                                else [])
        rep['layout'] = {'events': timed('layout', MO.layouts, frames, afps, None, text_between),
                         'method': 'edges that stay put while the footage moves: a straight seam across the frame with '
                                   'moving pictures on both sides (split screen), or a rectangle with its own moving '
                                   'picture (inset)'}
    except Exception as e:  # noqa: BLE001
        step_error(rep, errors, 'layout_speed', e, 300)


def _analyse_structure(prog, rep, T, face_track, have_faces, video, dur, info, R, samples, sfps, timed, frames, feat, afps, words, errors, kind, sound, S):
    """Summarize faces, pacing, speed, opening and ending."""
    # 7. faces, look, structure
    prog(0.88, 'look and structure')
    rep['faces'] = T.face_summary(face_track) if have_faces else {'available': False}
    full = []
    try:
        full = list(frames_at(video, [dur * k / 5 for k in (1, 2, 3, 4)], info['width'], info).values())
    except Exception:  # noqa: BLE001
        pass
    rep['look'] = R.look(samples, face_track, full)
    shots_ = rep['shots']
    lengths = [s['len'] for s in shots_]
    sure = [c for c in rep['cuts'] if c.get('conf', 0) >= 0.5 and c.get('kind') != 'jump?']
    kinds = {}
    for c in sure:
        kinds[c.get('kind', 'cut')] = kinds.get(c.get('kind', 'cut'), 0) + 1
    intervals = face_time(face_track if have_faces else [], dur, 1 / sfps)
    presence = face_coverage(intervals, 0, dur)
    presence['method'] = ('duration-weighted face detections; at most one sampling interval per detection; '
                          'missing intervals are unknown; a visible face does not identify talking-head or b-roll')
    rep['faces']['time'] = presence
    for s in shots_:
        coverage = face_coverage(intervals, s['start'], s['end'])
        measured = coverage['face_seconds'] + coverage['nonface_seconds']
        s['face_share'] = round(coverage['face_seconds'] / measured, 3) if measured else 0.0
        s['face_coverage'] = coverage['measured_share']
    talking = (presence['measured_share'] or 0) >= 0.8 and (presence['face_share'] or 0) >= 0.4
    for s in shots_:
        s['kind'] = ('talking' if s['face_share'] >= 0.5 else 'cutaway' if talking else 'shot')
    try:
        import letitedit.looks.style_import_motion as MO
        spans_f = [(int(round(s['start'] * afps)), int(round(s['end'] * afps))) for s in shots_]
        faces_f = {sp: s.get('face_share', 0) for sp, s in zip(spans_f, shots_)}
        rep['speed'] = timed('speed', MO.speed_profile, frames, feat, afps, spans_f, words,
                             faces=faces_f, native_fps=float(info['fps']))
    except Exception as e:  # noqa: BLE001
        step_error(rep, errors, 'speed', e, 300)
    mins = max(1e-6, dur / 60)
    rep['pacing'] = {'shots': len(shots_), 'cuts': len(sure), 'cuts_per_minute': round(len(sure) / mins, 1),
                     'cut_kinds': kinds, 'shot_length_s': _stats(lengths, 2),
                     'longest_shots': sorted(({'t': s['start'], 'len': s['len']} for s in shots_),
                                             key=lambda x: -x['len'])[:5],
                     'cutaway_share': presence['nonface_share'] if talking else None,
                     'cutaway_method': 'non-face time in a mostly face-present video; not semantic b-roll',
                     'broll_share': None,
                     'talking_head': talking,
                     'zooms_per_minute': round(len([z for z in rep['zooms'] if z['kind'] in ('punch_in', 'punch_out')])
                                               / mins, 2),
                     'push_ins': len([z for z in rep['zooms'] if z['kind'] in ('push_in', 'pull_out')]),
                     'transitions': {k: sum(1 for g in rep['transitions'] if g['kind'] == k)
                                     for k in sorted({g['kind'] for g in rep['transitions']})},
                     'possible_jump_cuts': sum(1 for c in rep['cuts'] if c.get('kind') == 'jump?')}
    win = 5.0 if kind == 'short' else 30.0
    curve = R.pace_curve(sure, dur, win)
    rep['pace_curve'] = curve
    rep['sections'] = R.sections(curve, words, dur, min_s=6.0 if kind == 'short' else 45.0)
    rep['_face0'] = bool(face_track and face_track[0][1])
    mus = (sound.get('music') or {}) if isinstance(sound, dict) else {}
    rep['_speech_spans'] = S.speech_spans(words)
    rep['_beats'] = list(mus.get('beat_times') or [])
    rep['_music0'] = None
    rep['hook'] = R.hook(rep, words, hook_s=3.0 if kind == 'short' else 15.0)
    rep['ending'] = R.ending(rep, words, dur, frames, end_s=4.0 if kind == 'short' else 20.0)
    rep['words'] = [{'w': w['w'], 's': round(float(w['s']), 3), 'e': round(float(w.get('e', w['s'])), 3)}
                    for w in words]


def analyse(video, kind=None, refresh=False, progress=None, log=None, check=None, separate=True, classify_sfx=True,
            words=None, settings=None, sound=True):
    """The deep breakdown of one reference video (see the module doc). kind: 'short' | 'long' | None (by length:
    under 3 min is a short). Cached per file content and settings; the report's 'folder' holds its pictures and
    breakdown.md. progress(fraction, message) and check() (raises to stop) are optional."""
    import letitedit.looks.style_import_layers as L
    import letitedit.looks.style_import_report as R
    import letitedit.looks.style_import_sound as S
    import letitedit.looks.style_import_text as T
    st = {**SETTINGS, **(settings or {})}
    video = Path(video).resolve()
    if not video.is_file():
        raise FileNotFoundError(f'No file at {video}')
    info = probe(video)
    info['path'] = str(video)
    dur = float(info['duration'])
    kind = kind or ('short' if dur <= 180 else 'long')
    key = cache_key(video, {**st, 'kind': kind, 'separate': bool(separate), 'sfx': bool(classify_sfx),
                            **({} if sound else {'sound': False})})
    folder = CACHE / key
    rep_file = folder / 'report.json'
    rep = json.loads(rep_file.read_text(encoding='utf-8-sig')) if rep_file.exists() and not refresh else None
    if rep is not None and retry_cached(rep):
        # a step ran short of memory or time when this was measured: measured again now
        if log:
            log(f'{video.name}: measuring again (a step ran short of memory or time last time)')
        rep = None
    if rep is not None:
        if 'camera' not in rep and rep.get('shots'):
            # a report made before the camera language was measured: measured once now and kept with it
            try:
                rep['camera'] = _camera(video, info, rep)
                tmp = rep_file.with_suffix('.tmp')
                tmp.write_text(json.dumps(rep, indent=1, default=_json_default), encoding='utf-8')
                os.replace(tmp, rep_file)
            except Exception as e:  # noqa: BLE001
                step_error(rep, rep.setdefault('errors', {}), 'camera', e, 300)
        rep['cached'] = True
        return rep
    folder.mkdir(parents=True, exist_ok=True)
    t_start = time.monotonic()
    steps = []

    def prog(x, msg):
        if progress:
            progress(min(0.99, x), msg)
        if log:
            log(f'{os.path.basename(str(video))}: {msg}')

    def timed(name, fn, *a, **kw):
        t0 = time.monotonic()
        try:
            return fn(*a, **kw)
        finally:
            steps.append({'step': name, 's': round(time.monotonic() - t0, 1)})

    rep = {'file': str(video), 'name': video.name, 'kind': kind, 'duration_s': round(dur, 3), 'duration': clock(dur),
           'video': {k: info[k] for k in ('width', 'height', 'fps', 'rotation', 'has_audio', 'size_mb')},
           'orientation': 'vertical' if info['height'] > info['width'] else 'horizontal' if info['width'] > info['height']
           else 'square', 'version': VERSION, 'settings': st, 'folder': str(folder)}
    errors = {}
    # 1. grey frames
    prog(0.02, 'reading every frame')
    frames, feat, afps = timed('frames', picture_frames, video, info, st)
    if check:
        check()
    # 2. sampled colour frames, faces, text
    sfps = st['sample_fps_short'] if kind == 'short' else st['sample_fps_long']
    sw = st['sample_width'] if info['width'] <= info['height'] else int(st['sample_width'] * 16 / 9)
    prog(0.12, 'sampling frames')
    samples = timed('samples', sample_frames, video, folder / 'samples', sfps, sw, info)
    prog(0.16, 'faces')
    sample_key = {'fps': sfps, 'width': sw, 'n': len(samples)}
    face_track, have_faces = timed('faces', part_cached, video, 'faces', sample_key,
                                   lambda: list(T.faces(samples)), samples)
    face_track = [(t, fs) for t, fs in face_track]
    prog(0.2, 'reading text (OCR)')
    try:
        def read_ocr():
            fr, status = T.read_text(samples, check=check, progress=(lambda x: prog(0.2 + 0.2 * x, 'reading text (OCR)')))
            if not status.get('available'):
                raise RuntimeError(status.get('why') or 'OCR unavailable')    # not cached: it may work next time
            return [fr, status]
        ocr_frames, ocr_status = timed('ocr', part_cached, video, 'ocr', {**sample_key, 'variants': ['raw', 'light']},
                                       read_ocr, samples)
    except Exception as e:  # noqa: BLE001
        ocr_frames, ocr_status = [], {'available': False, 'why': step_error(rep, None, 'ocr', e, 300)}
    events = T.text_events(ocr_frames, 1.0 / sfps)
    events = T.refine_text_times(events, feat, afps, 1.0 / sfps)
    # 3. cuts and motion, with the text left out
    prog(0.42, 'cuts, transitions and zooms')
    masks = T.text_masks(events, feat, afps) if events else None

    def text_boxes(t, ev=events):
        return [e['box'] for e in ev if e['t'] - 0.25 <= t <= e['end'] + 0.25]
    from letitedit.looks.style_import_visual import analyse as native_visual
    native_effects = {}
    try:
        native_effects = timed('native_visual', native_visual, video, check=check)
    except (ValueError, OSError, ImportError) as error:
        step_error(rep, errors, 'native_visual', error, 300)
    pic = timed('cuts', picture_events, video, info, frames, feat, afps, masks=masks, settings=st,
                text_boxes=text_boxes, native_effects=native_effects)
    rep.update({k: pic[k] for k in ('cuts', 'transitions', 'zooms', 'shake', 'shots', 'camera_moves', 'native_effects')})
    prog(0.44, 'camera language')
    try:
        rep['camera'] = timed('camera', _camera, video, info, rep)
    except Exception as e:  # noqa: BLE001 - the rest of the breakdown stands without it
        step_error(rep, errors, 'camera', e, 300)
    import letitedit.looks.style_import_sources as style_import_sources
    rep['shot_sources'] = style_import_sources.from_reports([rep])
    rep['picture_analysis'] = pic['analysis']
    if check:
        check()
    sound, words = _analyse_sound(prog, sound, words, video, timed, S, info, rep, log, check, separate, classify_sfx)

    events = _analyse_captions(prog, T, events, words, dur, rep, ocr_status, timed, folder, st, info, video, afps, errors, check)

    _analyse_overlays(prog, timed, L, frames, feat, afps, rep, events, face_track, words, video, info, samples, dur, sound, kind, S, errors)

    _analyse_layout(prog, L, events, rep, timed, frames, afps, errors)

    _analyse_structure(prog, rep, T, face_track, have_faces, video, dur, info, R, samples, sfps, timed, frames, feat, afps, words, errors, kind, sound, S)

    # 8. pictures and the breakdown
    prog(0.93, 'pictures')
    try:
        rep['pictures'] = timed('pictures', pictures, rep, video, info, folder, face_track)
    except Exception as e:  # noqa: BLE001
        rep['pictures'] = {'error': step_error(rep, None, 'pictures', e, 300)}
    rep['errors'] = errors
    rep['steps'] = steps
    rep['took_s'] = round(time.monotonic() - t_start, 1)
    for k in ('_face0', '_music0', '_beats', '_speech_spans'):
        rep.pop(k, None)
    (folder / 'breakdown.md').write_text(breakdown(rep), encoding='utf-8')
    rep['breakdown'] = str(folder / 'breakdown.md')
    tmp = rep_file.with_suffix('.tmp')
    tmp.write_text(json.dumps(rep, indent=1, default=_json_default), encoding='utf-8')
    os.replace(tmp, rep_file)
    rep['cached'] = False
    prog(1.0, 'done')
    return rep


def _camera(video, info, rep):
    """The reference's camera language: each shot's move and size (camera_language.measure on the report's shots,
    zooms and camera moves)."""
    import letitedit.looks.camera_language as camera_language
    return camera_language.measure(video, dict(info), picture={key: rep.get(key) for key in
                                                                ('shots', 'zooms', 'camera_moves')})


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def pictures(rep, video, info, folder, face_track):
    """Sheets beside the report: timeline.png (every event on one time axis), hook.png, ending.png, overlays.png
    (each overlay boxed, with what was said), transitions.png, captions.png (caption crops)."""
    import letitedit.looks.style_import_report as R
    folder = Path(folder)
    out = {}
    dur = rep['duration_s']
    W = 180
    im = R.timeline_image(rep)
    im.save(folder / 'timeline.png')
    out['timeline'] = str(folder / 'timeline.png')
    hs = rep['hook']['seconds']
    ht = [round(hs * k / 6, 3) for k in range(7)]
    fr = frames_at(video, ht, W * 2, info)
    rows = [(fr[min(fr, key=lambda q: abs(q - t))], clock(t)) for t in ht if fr]
    s = R.strip(rows, tile_w=W, title=f'Hook (first {hs:g} s): said "{rep["hook"]["said"][:90]}"')
    if s:
        s.save(folder / 'hook.png')
        out['hook'] = str(folder / 'hook.png')
    es_ = rep['ending']['seconds']
    et = [round(max(0.0, dur - es_ + es_ * k / 5), 3) for k in range(5)] + [round(max(0.0, dur - 0.1), 3)]
    fr = frames_at(video, et, W * 2, info)
    rows = [(fr[min(fr, key=lambda q: abs(q - t))], clock(t)) for t in et if fr]
    s = R.strip(rows, tile_w=W, title=f'Ending (last {es_:g} s): said "{rep["ending"]["said"][-90:]}"')
    if s:
        s.save(folder / 'ending.png')
        out['ending'] = str(folder / 'ending.png')
    ovs = [o for o in rep['overlays'].get('events', [])][:24]
    if ovs:
        times = [min(o['end'] - 0.05, o['t'] + 0.45) for o in ovs]
        fr = frames_at(video, times, W * 2, info)
        rows = []
        for o, t in zip(ovs, times):
            if not fr:
                break
            f = fr[min(fr, key=lambda q: abs(q - t))]
            lab = f"{clock(o['t'])} {o.get('kind') or ''} {o.get('trigger') or ''}".strip()
            rows.append((R.boxed(f, o['box'], (0, 255, 255) if o.get('conf', 0) >= 0.5 else (90, 90, 255)),
                         lab + (f" | {o.get('word', '')}" if o.get('word') else '')))
        lines = [R.strip(rows[k:k + 6], tile_w=W, title='Overlays and pop-ups (boxed; dim box = unsure)' if k == 0
                         else None) for k in range(0, len(rows), 6)]
        s = R.stack(lines)
        if s:
            s.save(folder / 'overlays.png')
            out['overlays'] = str(folder / 'overlays.png')
    trs = [g for g in rep['transitions']][:12]
    if trs:
        rows_all = []
        fps = info['fps'] or 30.0
        for g in trs:
            a, b = g.get('start', g['t']), g.get('end', g['t'])
            ts = [a - 2 / fps, a, (a + b) / 2, b, b + 2 / fps]
            fr = frames_at(video, ts, W * 2, info)
            if fr:
                rows_all.append(R.strip([(fr[min(fr, key=lambda q: abs(q - t))], clock(t)) for t in ts], tile_w=W // 2 * 2,
                                        title=f"{g['kind']} at {clock(g['t'])} ({g.get('len_s', 0)} s)"))
        s = R.stack(rows_all)
        if s:
            s.save(folder / 'transitions.png')
            out['transitions'] = str(folder / 'transitions.png')
    caps = [e for e in rep.get('text_events', []) if e.get('role') == 'caption'][:8]
    if caps:
        times = [e.get('best_t', e['t']) for e in caps]
        fr = frames_at(video, times, info['width'], info)
        rows = []
        for e, t in zip(caps, times):
            if not fr:
                break
            f = fr[min(fr, key=lambda q: abs(q - t))]
            h, w = f.shape[:2]
            x0, y0, x1, y1 = e['box']
            pad = 0.03
            crop = f[max(0, int((y0 - pad) * h)):min(h, int((y1 + pad) * h)), max(0, int((x0 - pad) * w)):min(w, int((x1 + pad) * w))]
            if crop.size:
                rows.append((crop, f"{clock(e['t'])} {e['text'][:40]}"))
        s = R.stack([R.strip([r], tile_w=520, title=None) for r in rows])
        if s:
            s.save(folder / 'captions.png')
            out['captions'] = str(folder / 'captions.png')
    return out


def _fmt(v, unit=''):
    if v is None:
        return 'n/a'
    if isinstance(v, dict) and 'median' in v:
        return f"{v['median']}{unit} (middle half {v.get('p25')}-{v.get('p75')}{unit})"
    return f'{v}{unit}'


def _words_count(d, names=None):
    """{'cut': 4, 'jump': 5} -> '5 jump, 4 cut' (largest first; names maps keys to words)."""
    names = names or {}
    items = sorted(((k, v) for k, v in (d or {}).items() if v), key=lambda kv: -kv[1])
    return ', '.join(f"{v} {names.get(k, str(k).replace('_', ' '))}" for k, v in items)


def _breakdown_pace(rep, a):
    """Pace and structure: cuts, shot lengths, kinds of cut, zooms, layouts, speed, cards, transitions, sections."""
    p = rep.get('pacing', {})
    a('')
    a('## Pace and structure')
    a(f"- {p.get('cuts')} cuts ({p.get('cuts_per_minute')} a minute) over {p.get('shots')} shots; shot length "
      f"{_fmt(p.get('shot_length_s'), ' s')}.")
    ck = p.get('cut_kinds') or {}
    a('- Kinds of cut: ' + _words_count(ck, {'cut': 'to a new picture', 'jump': 'jump cuts (same framing)',
                                            'punch': 'punch in or out', 'jump?': 'unsure (a jump cut or a dropped frame)'})
      + '.')
    if p.get('talking_head'):
        a(f"- Mostly face-present; non-face samples cover {round(100 * (p.get('cutaway_share') or 0))}% of the time"
          + ' (not a semantic b-roll measurement).')
    a(f"- Zoom punches: {p.get('zooms_per_minute')} a minute; slow push-ins / pull-outs: {p.get('push_ins')}"
      + (f"; possible forward/backward image moves: {len(rep.get('camera_moves') or [])} "
         f"(camera travel versus subject motion remains uncertain)" if rep.get('camera_moves') else '') + '.')
    lay = [e for e in (rep.get('layout') or {}).get('events') or []]
    if lay:
        a('- Layouts: ' + '; '.join(f"{clock(e['t'])}-{clock(e['end'])} "
                                    f"{'inset (picture-in-picture)' if e['kind'] == 'inset' else 'split screen ' + str(e.get('where', '')).replace('_', '/')}"
                                    f"{'' if e.get('conf', 0) >= 0.5 else ' (unsure)'}" for e in lay[:8]) + '.')
    spd = [e for e in (rep.get('speed') or {}).get('events') or []]
    if spd:
        a('- Speed: ' + '; '.join(f"{clock(e['t'])}-{clock(e['end'])} {e['kind']} (about {e.get('speed')}x, "
                                  f"{e.get('by')}){'' if e.get('conf', 0) >= 0.5 else ' unsure'}" for e in spd[:8]) + '.')
    if rep.get('cards'):
        a('- Full-screen cards: ' + '; '.join(f"{clock(c['t'])}-{clock(c['end'])} \"{c.get('text', '')[:60]}\""
                                            for c in rep['cards'][:4]) + '.')
    a(f"- Transitions: {_words_count(p.get('transitions') or {}) or 'only hard cuts'}.")
    if rep.get('sections'):
        a('- Sections: ' + '; '.join(f"{clock(s['t0'])}-{clock(s['t1'])} {s['per_minute']} cuts/min"
                                     f"{' talk' if s['talk'] else ' no talk'}" for s in rep['sections']))


def _breakdown_hook_and_ending(rep, a):
    """The hook and the ending: what is said and written, its devices, the call to action."""
    h = rep.get('hook', {})
    a('')
    a(f"## Hook (first {h.get('seconds')} s)")
    a(f"- Said: \"{h.get('said', '')}\" (first word at {h.get('first_word_s')} s).")
    if h.get('text_on_screen'):
        a('- Written: ' + '; '.join(f"\"{t['text']}\" ({t['role']}, {t['t']} s)" for t in h['text_on_screen'][:5]))
    a(f"- Devices: {', '.join(h.get('devices') or []) or 'none measured'}.")
    e = rep.get('ending', {})
    a('')
    a(f"## Ending (last {e.get('seconds')} s)")
    a(f"- Said: \"{e.get('said', '')}\".")
    a(f"- Call to action: {', '.join(e.get('call_to_action') or []) or 'none heard or read'}; loops back to the start: "
      f"{'likely' if e.get('loop_guess') else 'no sign'}.")


def _breakdown_captions(rep, a):
    """Captions: count, chunking, case, timing, position, look, the word set apart, fonts and entry."""
    c = rep.get('captions', {})
    a('')
    a('## Captions')
    if not c.get('present'):
        a('- No captions found (no text that matches what is said).')
    else:
        a(f"- {c.get('count')} captions, {c.get('chunking')} ({_fmt(c.get('words_per_caption'))} words each), "
          f"{c.get('case')}, timing {c.get('timing')} (lead {_fmt(c.get('lead_s'), ' s')}).")
        pos = c.get('position', {})
        a(f"- Position: {pos.get('zone')} (centre y {_fmt(pos.get('y'))}); line height "
          f"{_fmt((c.get('size') or {}).get('line_height_share'))} of the frame height.")
        lk = c.get('look') or {}
        if lk:
            ol = lk.get('outline')
            a(f"- Look: {lk.get('fill_kind') or ''} fill {lk.get('fill')}, "
              + (f"outline {ol['color']} about {ol['width_px']} px at full size (on {round(100 * ol.get('share', 1))}%)"
                 if ol else 'no outline')
              + f", drop shadow on {round(100 * (lk.get('shadow_share') or 0))}%"
              + (f", on a plate {lk['plate']}" if lk.get('plate') else '')
              + f", {lk.get('weight_guess') or '?'} weight (from {lk.get('read_from')} captions read at full size).")
        hl = c.get('highlight')
        if hl:
            a(f"- A word set apart in colour ({hl.get('kind') or '?'} {hl.get('color') or ''}): in "
              f"{hl.get('captions_with_one_word_set_apart')} of {hl.get('of_multi_word_captions')} multi-word captions, "
              f"moving word to word in {hl.get('moves_word_to_word')}"
              + ('.' if hl.get('present') else ' (too few to call it the style).'))
        if c.get('font_guess'):
            a('- Nearest bundled fonts: ' + ', '.join(f"{f['family']} {f['weight']}" for f in c['font_guess'][:4]) + '.')
        if c.get('entry'):
            a(f"- Comes in: mostly {c['entry'].get('style')} ({_words_count(c['entry'].get('styles') or {})} of the "
              f"captions looked at frame by frame).")


def _breakdown_text_and_overlays(rep, a):
    """Other text on screen, then the overlays and pop-ups found."""
    ot = rep.get('on_screen_text', {})
    if ot.get('labels') or ot.get('titles') or ot.get('text_pops') or ot.get('watermarks'):
        a('')
        a('## Other text on screen')
        for k in ('titles', 'labels', 'text_pops', 'watermarks'):
            if ot.get(k):
                a(f"- {k.replace('_', ' ')}: " + '; '.join(f'"{x}"' for x in ot[k][:8]))
    o = rep.get('overlays', {})
    a('')
    a('## Overlays and pop-ups')
    if o.get('count'):
        a(f"- {o.get('count', 0)} found ({o.get('per_minute', 0)} a minute; {o.get('unsure', 0)} more unsure, dim in "
          f"overlays.png); where: {_words_count(o.get('zones') or {})}; came in on: "
          f"{_words_count(o.get('triggers') or {})}; kinds: {_words_count(o.get('kinds') or {})}; on screen "
          f"{(o.get('on_screen_s') or {}).get('median')} s; about {round(100 * (o.get('size_median') or 0))}% of the "
          f"frame's short side.")
    else:
        a(f"- None found ({o.get('unsure', 0)} unsure finds, dim in overlays.png when there are any).")
    for ev in [x for x in o.get('events', []) if x.get('conf', 0) >= 0.5][:15]:
        text = ' "%s"' % ev['text'] if ev.get('text') else ''
        word = ' ("%s")' % ev.get('word', '') if ev.get('word') else ''
        a(f"  - {clock(ev['t'])}-{clock(ev['end'])} {ev.get('kind') or 'graphic'} {ev['zone']}{text}; trigger "
          f"{ev.get('trigger')}{word}; comes in: {ev.get('entry', '?')}, goes: {ev.get('exit', '?')}{'; with a sound' if ev.get('sfx') else ''}")


def _breakdown_sound(rep, a):
    """Sound: speech, loudness, music, cuts on the beat, sound effects and silences."""
    s = rep.get('sound') or {}
    a('')
    a('## Sound')
    sp = s.get('speech') or {}
    ps = sp.get('pauses_s') or {}
    a(f"- Speech: {sp.get('words')} words, {sp.get('words_per_minute_while_talking')} words a minute while talking, "
      f"speech on {round(100 * (sp.get('speech_share') or 0))}% of the time"
      + (f"; pauses between phrases {ps.get('median')} s in the middle, 9 in 10 under {ps.get('p90_within_talk')} s "
         f"(of those under 2 s)" if ps else '') + '.')
    lo = s.get('loudness') or {}
    a(f"- Loudness: {lo.get('integrated_lufs')} LUFS, range {lo.get('range_lu')} LU, peak {lo.get('true_peak_dbfs')} dBTP.")
    m = s.get('music') or {}
    if m:
        bq = {'clear': 'a clear beat', 'weak': 'a weak beat', 'none': 'no clear beat'}.get(m.get('beat_quality'),
                                                                                         m.get('beat_quality'))
        a(f"- Music on {round(100 * (m.get('music_share') or 0))}% of the time"
          + (f", about {round(m['tempo_bpm'])} BPM ({bq})" if m.get('tempo_bpm') else '')
          + (f"; under speech {m.get('level_under_speech_db')} dBFS, in the gaps {m.get('level_in_gaps_db')} dBFS "
             f"(up {m.get('ducking_db')} dB in the pauses; {m.get('under_voice_db')} dB against the voice)"
             if m.get('level_under_speech_db') is not None else '') + '.')
        if m.get('cuts_on_beat'):
            cb = m['cuts_on_beat']
            a(f"- Cuts on the beat: {round(100 * cb['share'])}% (chance {round(100 * cb['chance'])}%).")
    fx = s.get('sfx') or {}
    a(f"- Sound effects: {fx.get('count', 0)} ({fx.get('per_minute', 0)} a minute)"
      + (f": {_words_count(fx.get('kinds') or {})}; {round(100 * (fx.get('at_cuts_share') or 0))}% on cuts, "
         f"{round(100 * (fx.get('at_overlays_share') or 0))}% with pop-ups" if fx.get('count') else '')
      + (f"; {fx.get('dropped_as_music')} sharp sounds taken for the music" if fx.get('dropped_as_music') else '')
      + (f"; {fx['not_sure_count']} more not sure (unheard)" if fx.get('not_sure_count') else '')
      + '.')
    si = s.get('silences') or {}
    a(f"- Silences: {si.get('count', 0)}.")


def _breakdown_look(rep, a):
    """The look, the faces and the picture files."""
    lk = rep.get('look') or {}
    a('')
    a('## Look')
    bars = lk.get('bars') or {}
    a(f"- Brightness {_fmt(lk.get('brightness'))}, {lk.get('contrast_word')} contrast, {lk.get('saturation_word')} "
      f"colour, {lk.get('warmth')}; grain: {(lk.get('grain') or {}).get('word')}"
      + ('; darker corners (a vignette, or the scene)' if (lk.get('vignette') or {}).get('likely') else '')
      + ('; letterbox bars' if bars.get('letterbox') else '')
      + ('; soft, blurred bands at the top and bottom (a blurred copy behind a smaller picture?)'
         if (lk.get('blurred_bands') or {}).get('likely') else '') + '.')
    if lk.get('skin'):
        a(f"- Skin: hue {lk['skin']['hue_deg']} deg, saturation {lk['skin']['saturation']}.")
    f = rep.get('faces') or {}
    if f.get('share_with_face') is not None:
        a(f"- Face on screen {round(100 * f['share_with_face'])}% of the time, {f.get('typical_framing')} "
          f"(face height {_fmt(f.get('face_height'))}).")
    pics = rep.get('pictures') or {}
    if pics:
        a('')
        a('## Pictures')
        for k, v in pics.items():
            if isinstance(v, str):
                a(f'- {k}: {v}')


def breakdown(rep):
    """The report as plain reading (markdown)."""
    L = []
    a = L.append
    a(f"# {rep['name']}: breakdown")
    a('')
    a(f"{rep['duration']} long, {rep['orientation']} {rep['video']['width']}x{rep['video']['height']} at "
      f"{rep['video']['fps']} fps, read as a {rep['kind']} video. Measured by letitedit style import "
      f"v{rep['version']} in {rep.get('took_s', '?')} s.")
    _breakdown_pace(rep, a)
    _breakdown_hook_and_ending(rep, a)
    _breakdown_captions(rep, a)
    _breakdown_text_and_overlays(rep, a)
    _breakdown_sound(rep, a)
    _breakdown_look(rep, a)
    return '\n'.join(L) + '\n'


# ------------------------------------------------------------------ several videos -> a style (the job)

VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.mkv', '.webm', '.avi', '.mts', '.wmv'}
REFERENCES = Path(_SAI_ROOT) / 'style-references'


def find_videos(folder):
    """Video files directly in a folder (sorted by name) and its notes.txt text ('' when there is none)."""
    folder = Path(folder)
    if not folder.is_dir():
        alt = REFERENCES / str(folder)
        if alt.is_dir():
            folder = alt
        else:
            raise FileNotFoundError(f'No folder at {folder} (or {alt})')
    vids = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT)
    notes = ''
    for nm in ('notes.txt', 'NOTES.txt', 'notes.md'):
        if (folder / nm).exists():
            notes = (folder / nm).read_text(encoding='utf-8', errors='replace').strip()
            break
    return vids, notes, folder


def slug(name):
    s = re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')
    return s[:48] or 'imported-style'


def run(videos=None, folder=None, kind=None, notes=None, separate=True,
        classify_sfx=True, refresh=False, progress=None, log=None, check=None):
    """Measure cached references and merge facts for Learn, without publishing any preferences.
    videos: local files; folder: a reference folder whose notes.txt is read. Returns reports, pictures and merged facts.
    """
    import letitedit.looks.style_import_write as W
    vids = [Path(v) for v in (videos or [])]
    fnotes = ''
    src_folder = None
    if folder:
        found, fnotes, src_folder = find_videos(folder)
        vids += found
    if not vids:
        raise ValueError('give videos=[...] or folder= (a folder of reference videos)')
    missing = [str(v) for v in vids if not Path(v).is_file()]
    if missing:
        raise FileNotFoundError('not found: ' + ', '.join(missing))
    notes = notes if notes is not None else fnotes
    label = src_folder.name if src_folder else Path(vids[0]).stem
    if kind is None:
        durs = [probe(v)['duration'] for v in vids]
        kind = 'short' if float(np.median(durs)) <= 180 else 'long'
    reports = []
    n = len(vids)
    for k, v in enumerate(vids):
        if check:
            check()

        def sub(x, msg='', k=k, v=v):
            if progress:
                progress((k + min(0.999, x) * 0.97) / n * 0.92, f'{k + 1}/{n} {Path(v).name}: {msg}')
        r = analyse(v, kind=kind, refresh=refresh, progress=sub, log=log, check=check, separate=separate,
                    classify_sfx=classify_sfx)
        reports.append(r)
    if progress:
        progress(0.93, 'merging the references')
    merged = W.merge(reports, notes or '')
    out = {'kind': kind, 'label': label, 'notes': notes or '', 'merged_facts': len(merged['facts']),
           'consistent': merged['consistent'], 'varies': merged['varies'],
           'videos': [{'file': r['file'], 'breakdown': r.get('breakdown'), 'pictures': r.get('pictures'),
                       'took_s': r.get('took_s'), 'cached': r.get('cached')} for r in reports]}
    out['merged'] = merged
    out['reports'] = [str(Path(report['folder']) / 'report.json') for report in reports]
    if progress:
        progress(1.0, 'done')
    return json.loads(json.dumps(out, default=_json_default))


def job(ctx):
    """jobs.py entry (kind 'style_import:job'): run() with the job's inputs, progress and cancel check."""
    inp = dict(ctx.inputs)

    def prog(x, msg=''):
        now = time.monotonic()
        if now - prog.last > 1.5 or x >= 1.0:
            prog.last = now
            ctx.progress(x, msg)
    prog.last = 0.0
    return run(**inp, progress=prog, log=ctx.log, check=ctx.check)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Learn reference measurements: analyse and merge local videos')
    ap.add_argument('videos', nargs='*')
    ap.add_argument('--folder')
    ap.add_argument('--kind', choices=('short', 'long'))
    ap.add_argument('--notes')
    ap.add_argument('--analyse-only', action='store_true', help='one report per video, printed as JSON paths')
    a = ap.parse_args()
    if a.analyse_only:
        for v in a.videos:
            r = analyse(v, kind=a.kind, progress=lambda x, m: print(f'{x:.2f} {m}', flush=True))
            print(json.dumps({'file': r['file'], 'breakdown': r['breakdown'], 'pictures': r.get('pictures')}))
    else:
        res = run(a.videos, folder=a.folder, kind=a.kind, notes=a.notes,
                  progress=lambda x, m: print(f'{x:.2f} {m}', flush=True))
        print(json.dumps({k: v for k, v in res.items() if k != 'merged'}, indent=1, default=str))
