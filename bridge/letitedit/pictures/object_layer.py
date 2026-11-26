"""An object cut out of a shot, as a layer (T62).

What makes the edge clean is that one outline serves the whole shot: the object is tracked as a rigid thing, about 60 of
its frames are lined up into one clean, sharper picture of it at twice the size (the plate), the outline is made once on
that plate, and the track carries it. In the object's own coordinates the outline can't flicker: measured 0.08-0.10 px of
wobble against 0.39-0.80 for SAM 2's own per-frame masks (tests/t62/REPORT.md). The price is that it only works on things
that keep their shape and show the same side, so `make` checks that and refuses with a plain message rather than making
a bad layer. Each object is immutable: changing the outline makes a new id.

    frame_sheet     a sharp frame with a pixel grid, to choose points on
    try_points      what SAM 2 finds from "this" and "not this" points on one frame, as a picture to check
    make            follow, track, check, plate, first outline: an object id, or why not
    edit_outline    move, drop or add outline points: a new object id
    render_movie    the {vfx: {effect: object}} movie (vfx_items._fx_object)
    pose            where the object is in a frame of the shot (object_lift)
    filled_still    a frame of the shot with the object filled in, for the background plate
"""
from __future__ import annotations

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (no console windows)

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np

cv2 = None


def _cv():
    global cv2
    if cv2 is None:
        import cv2 as module
        module.setNumThreads(4)
        cv2 = module
    return cv2


from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = _paths.CODE_ROOT
HOME = Path(os.environ.get('LETITEDIT_CACHE', str(ROOT / 'cache'))) / 'objects'
SAM_MODEL = 'sam2-hiera-tiny'
MAX_SECONDS = 60.0
ENGINE = 1

# What counts as "this kept its shape". From the motor (rigid, handheld camera: overlap 0.93 worst, 0.97 median; match
# 0.86 worst, 0.97 median) and the failure runs in tests/t62/REPORT.md.
MIN_OVERLAP = 0.84          # the carried shape against SAM 2's own mask on a frame
MIN_MATCH = 0.72            # the picture inside the shape against the key frame's
MIN_VISIBLE = 0.92          # how much of the shape has to stay inside the frame
MIN_HOLD_S = 0.5            # a stretch shorter than this isn't offered as "try this range"


class Refused(ValueError):
    """A plain reason nothing was made."""


# ---------------------------------------------------------------------------- source frames

def _ff():
    import letitedit.timeline.made as made
    return Path(made.ffmpeg_exe())


def probe(clip):
    ffprobe = _ff().with_name('ffprobe.exe')
    r = subprocess.run([str(ffprobe), '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=width,height,r_frame_rate,avg_frame_rate,nb_frames:stream_side_data=rotation:format=duration',
                        '-of', 'json', str(clip)], capture_output=True, text=True)
    if r.returncode:
        raise Refused(f'{Path(clip).name} could not be read: {r.stderr.strip()[-200:]}')
    d = json.loads(r.stdout)
    s = (d.get('streams') or [{}])[0]
    if not s.get('width'):
        raise Refused(f'{Path(clip).name} has no picture')
    rate = lambda t: (lambda a, b: float(a) / float(b) if float(b) else 0.0)(*str(t).split('/')) if t and '/' in str(t) else 0.0
    fps = rate(s.get('r_frame_rate')) or rate(s.get('avg_frame_rate')) or 30.0
    if fps > 121:
        fps = rate(s.get('avg_frame_rate')) or 30.0
    w, h = int(s['width']), int(s['height'])
    rotation = 0
    for side in s.get('side_data_list') or []:
        rotation = int(float(side.get('rotation') or 0))
    if abs(rotation) % 180 == 90:
        w, h = h, w
    return {'width': w, 'height': h, 'fps': fps, 'duration': float((d.get('format') or {}).get('duration') or 0)}


def _frame_no(t, fps):
    return int(round(float(t) * fps))


def decode(clip, first, count, info):
    """Frames first .. first+count-1 of the clip (BGR), in order, by frame number: seeking half a frame before gives the
    first frame at or after it, and this matches the frame the export engine shows for that number (checked, T62)."""
    w, h, fps = info['width'], info['height'], info['fps']
    at = max(0.0, (first - .5) / fps)
    p = subprocess.Popen([str(_ff()), '-nostdin', '-v', 'error', '-threads', '4', '-ss', f'{at:.5f}', '-i', str(clip),
                          '-frames:v', str(count), '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                         stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, bufsize=w * h * 3 * 2)
    try:
        for _ in range(count):
            b = p.stdout.read(w * h * 3)
            if len(b) < w * h * 3:
                break
            yield np.frombuffer(b, np.uint8).reshape(h, w, 3)
    finally:
        p.stdout.close()
        p.kill()
        p.wait()


def one_frame(clip, t, info=None):
    info = info or probe(clip)
    n = _frame_no(t, info['fps'])
    for f in decode(clip, n, 1, info):
        return f.copy(), n
    raise Refused(f'{Path(clip).name} has no frame at {t:.2f} s')


def _raw_range(clip, first, count, info, folder):
    """The range as a file on disk, so frames can be read in any order without holding them in memory."""
    w, h = info['width'], info['height']
    need = w * h * 3 * count
    import letitedit.core.cache_budget as cache_budget
    cache_budget.need_room(folder, int(need * 1.2), 'read these frames')
    path = Path(folder) / 'frames.raw'
    made = 0
    with open(path, 'wb') as f:
        for frame in decode(clip, first, count, info):
            f.write(frame.tobytes())
            made += 1
    if not made:
        raise Refused(f'{Path(clip).name} has no frames in that range')
    return path, made


# ---------------------------------------------------------------------------- SAM 2, in the models environment

def _models_python():
    p = ROOT / 'envs' / 'models' / 'Scripts' / 'python.exe'
    return p if p.is_file() else Path(sys.executable)


def _gpu_mb_free():
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'], capture_output=True,
                           text=True, timeout=5)
        return int(r.stdout.split()[0])
    except Exception:  # noqa: BLE001 - the worker has its own limit
        return 0


def _sam(raw, shape, jobs, chunk=None):
    """Run SAM 2 jobs in the models environment, under the PC lock and the GPU turn."""
    import letitedit.core.first_use as first_use
    import letitedit.sound.model_tools as model_tools
    import letitedit.core.render_lock as render_lock
    try:
        first_use.need(env='models', models=[SAM_MODEL], feature='object layers')
    except Exception as ex:  # noqa: BLE001
        raise Refused(f'SAM 2, which object layers follow things with, is not ready on this PC: {ex}') from None
    model = ROOT / 'vfx' / 'models' / SAM_MODEL
    if not (model / 'model.safetensors').is_file():
        raise Refused('SAM 2, which object layers follow things with, is not on this PC.')
    worker = _paths.BRIDGE.joinpath('object_sam_worker.py')
    with render_lock.model_slot('object follow'), model_tools._gpu_turn():
        free = _gpu_mb_free()
        # about 42 MB a frame (measured); leave room for the model itself
        limit = int(max(4, min(100, (free - 900) / 42))) if free else 60
        spec = {'model': str(model), 'raw': str(raw), 'shape': list(shape), 'chunk': chunk or limit, 'jobs': jobs}
        folder = Path(raw).parent
        spec_path = folder / f'sam-{uuid.uuid4().hex[:6]}.json'
        spec_path.write_text(json.dumps(spec), encoding='utf-8')
        r = subprocess.run([str(_models_python()), '-I', str(worker), str(spec_path)], capture_output=True, text=True, errors='replace')
    if r.returncode:
        tail = (r.stderr or '').strip().splitlines()
        if any('out of memory' in x.lower() for x in tail):
            raise Refused('The graphics card ran out of memory following this object. Close other programs using it or try '
                          'a shorter range.')
        raise RuntimeError(f'SAM 2 did not finish (exit {r.returncode}): ' + ' / '.join(tail[-3:])[-500:] + (r.stdout or '')[-200:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def _read_mask(path):
    return _cv().imread(str(path), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255


# ---------------------------------------------------------------------------- pictures for the AI to check

def _grid(img, step, scale=1.0, x0=0, y0=0, color=(0, 255, 255)):
    _cv()
    out = img.copy()
    h, w = out.shape[:2]
    fx = (int(math.ceil(x0 / step)) * step)
    for x in range(fx, int(x0 + w / scale), step):
        X = int((x - x0) * scale)
        cv2.line(out, (X, 0), (X, h), color, 1)
        cv2.putText(out, str(x), (X + 2, 12), 0, .4, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, str(x), (X + 2, 12), 0, .4, (255, 255, 255), 1, cv2.LINE_AA)
    fy = (int(math.ceil(y0 / step)) * step)
    for y in range(fy, int(y0 + h / scale), step):
        Y = int((y - y0) * scale)
        cv2.line(out, (0, Y), (w, Y), color, 1)
        cv2.putText(out, str(y), (2, Y - 2), 0, .4, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, str(y), (2, Y - 2), 0, .4, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def _work_dir(name):
    d = HOME / 'work' / f'{name}-{uuid.uuid4().hex[:8]}'
    d.mkdir(parents=True, exist_ok=True)
    return d


def frame_sheet(clip, at=None, start=None, end=None):
    """A sharp frame near `at` (or in start..end) with a grid in the clip's own pixels."""
    _cv()
    info = probe(clip)
    if at is None and start is None:
        raise Refused('Say which moment: at, or start and end (seconds in the clip).')
    a = float(start if start is not None else max(0, float(at) - .35))
    b = float(end if end is not None else min(info['duration'], float(at) + .35))
    fps = info['fps']
    first, count = _frame_no(a, fps), max(1, _frame_no(b, fps) - _frame_no(a, fps))
    step = max(1, count // 24)
    best, best_n, best_s = None, first, -1.0
    for k, f in enumerate(decode(clip, first, count, info)):
        if k % step:
            continue
        g = cv2.cvtColor(cv2.resize(f, None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        s = float(cv2.Laplacian(g, cv2.CV_32F).var())
        if s > best_s:
            best, best_n, best_s = f.copy(), first + k, s
    if best is None:
        raise Refused(f'{Path(clip).name} has no frames in that range')
    h, w = best.shape[:2]
    work = _work_dir('frame')
    scale = min(1.0, 1500 / max(h, w))
    small = cv2.resize(best, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    sheet = work / 'frame-grid.jpg'
    cv2.imwrite(str(sheet), _grid(small, 100, scale), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return {'at': round(best_n / fps, 4), 'width': w, 'height': h, 'fps': round(fps, 3), 'pictures': [str(sheet)]}


def _pieces(mask):
    n, _, stats, _ = cv2.connectedComponentsWithStats((mask > .5).astype(np.uint8), connectivity=8)
    big = max((stats[i, cv2.CC_STAT_AREA] for i in range(1, n)), default=0)
    return sum(1 for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= max(30, big * .02))


def try_points(clip, at, this, not_this=None, in_front=None):
    """What SAM 2 finds from the points on one frame, as a picture to check, in a second or two."""
    _cv()
    if not this:
        raise Refused('Give this: at least one point on the object, in the clip\'s pixels.')
    info = probe(clip)
    frame, n = one_frame(clip, at, info)
    work = _work_dir('try')
    raw = work / 'frames.raw'
    raw.write_bytes(frame.tobytes())
    h, w = frame.shape[:2]
    points = [list(map(float, p)) for p in this] + [list(map(float, p)) for p in (not_this or [])]
    labels = [1] * len(this) + [0] * len(not_this or [])
    jobs = [{'name': 'object', 'key': 0, 'indices': [0], 'points': points, 'labels': labels, 'out': str(work)}]
    if in_front:
        jobs.append({'name': 'front', 'key': 0, 'indices': [0], 'points': [list(map(float, p)) for p in in_front],
                     'labels': [1] * len(in_front), 'out': str(work)})
    _sam(raw, (1, h, w, 3), jobs)
    mask = _read_mask(work / 'object_00000.png')
    x, y, bw, bh = cv2.boundingRect((mask > .5).astype(np.uint8))
    area = float((mask > .5).mean())
    reply = {'at': round(n / info['fps'], 4), 'width': w, 'height': h, 'area_share': round(area, 4), 'box': [x, y, x + bw, y + bh],
             'pieces': _pieces(mask),
             'touches_frame_edge': bool(area and (x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1))}
    over = frame.astype(np.float32)
    over[mask > .5] = over[mask > .5] * .45 + np.array([200, 60, 255], np.float32) * .55
    if in_front:
        front = _read_mask(work / 'front_00000.png')
        over[front > .5] = over[front > .5] * .45 + np.array([60, 220, 60], np.float32) * .55
    over = over.astype(np.uint8)
    edge = cv2.morphologyEx((mask > .5).astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    over[edge > 0] = (255, 255, 255)
    for p in this:
        cv2.circle(over, (int(p[0]), int(p[1])), 7, (0, 255, 0), 2)
    for p in not_this or []:
        cv2.circle(over, (int(p[0]), int(p[1])), 7, (0, 0, 255), 2)
    pad = int(max(bw, bh) * .25) + 10
    x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad)
    crop = over[y0:y1, x0:x1] if area else over
    zoom = min(1.6, 1000 / max(crop.shape[:2]))
    a = work / 'mask-whole.jpg'
    b = work / 'mask-close.jpg'
    whole = min(1.0, 1100 / max(h, w))
    cv2.imwrite(str(a), _grid(cv2.resize(over, None, fx=whole, fy=whole, interpolation=cv2.INTER_AREA), 100, whole),
                [cv2.IMWRITE_JPEG_QUALITY, 88])
    cv2.imwrite(str(b), _grid(cv2.resize(crop, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC), 50, zoom, x0, y0),
                [cv2.IMWRITE_JPEG_QUALITY, 90])
    reply['pictures'] = [str(a), str(b)]
    shutil.rmtree(work / 'x', ignore_errors=True)
    raw.unlink(missing_ok=True)
    return reply


# ---------------------------------------------------------------------------- the rigid track

def _track(raw, shape, key, key_mask, front=None, progress=None):
    """Per-frame affine from the key frame to each frame, by ECC on the object plus a thin margin. Returns {index:
    (W 3x3, match)}, stopping a direction where the track is lost."""
    _cv()
    n, H, W, _ = shape
    frames = np.memmap(raw, dtype=np.uint8, mode='r', shape=tuple(shape))
    gray = lambda i: cv2.cvtColor(np.asarray(frames[i]), cv2.COLOR_BGR2GRAY).astype(np.float32)
    x, y, w, h = cv2.boundingRect((key_mask > .5).astype(np.uint8))
    pad = max(12, int(max(w, h) * .06))
    x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)
    w, h = x1 - x0, y1 - y0
    grow = max(5, int(max(w, h) * .02)) | 1
    T = gray(key)[y0:y1, x0:x1]
    M = cv2.dilate((key_mask[y0:y1, x0:x1] > .5).astype(np.uint8), np.ones((grow, grow), np.uint8))
    if front is not None:
        M[cv2.dilate((front[y0:y1, x0:x1] > .5).astype(np.uint8), np.ones((grow, grow), np.uint8)) > 0] = 0
    small = 2 if max(w, h) > 240 else 1
    Ts = cv2.resize(T, (w // small, h // small), interpolation=cv2.INTER_AREA)
    Ms = cv2.resize(M, (w // small, h // small), interpolation=cv2.INTER_NEAREST)

    def local(G, A):
        c = A @ np.array([x0 + w / 2, y0 + h / 2, 1.0])
        cx, cy = int(round(c[0] - w / 2)), int(round(c[1] - h / 2))
        C = cv2.warpAffine(G, np.float32([[1, 0, cx], [0, 1, cy]]), (w, h), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP,
                           borderMode=cv2.BORDER_REPLICATE)
        L = A.astype(np.float32).copy()
        L[0, 2] = A[0, 0] * x0 + A[0, 1] * y0 + A[0, 2] - cx
        L[1, 2] = A[1, 0] * x0 + A[1, 1] * y0 + A[1, 2] - cy
        return C, L, cx, cy

    def solve(i, A):
        C, L, cx, cy = local(gray(i), A)
        Ls = L.copy()
        Ls[:, 2] /= small
        Cs = cv2.resize(C, (w // small, h // small), interpolation=cv2.INTER_AREA)
        _, Ls = cv2.findTransformECC(Ts, Cs, Ls, cv2.MOTION_AFFINE,
                                     (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5), Ms, 5)
        L = Ls.copy()
        L[:, 2] *= small
        cc, L = cv2.findTransformECC(T, C, L, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 12, 1e-5), M, 3)
        out = L.astype(np.float64).copy()
        out[0, 2] = L[0, 2] + cx - L[0, 0] * x0 - L[0, 1] * y0
        out[1, 2] = L[1, 2] + cy - L[1, 0] * x0 - L[1, 1] * y0
        return out, float(cc)
    I = np.float64([[1, 0, 0], [0, 1, 0]])
    res = {key: (np.vstack([I, [0, 0, 1]]), 1.0)}
    for rng in (range(key + 1, n), range(key - 1, -1, -1)):
        A, prev = I.copy(), I.copy()
        lost = weak = 0
        for i in rng:
            guess = A + (A - prev) * .5
            try:
                A2, cc = solve(i, guess)
            except cv2.error:
                lost += 1
                A2, cc = guess, 0.0
                if lost >= 6:
                    break
            else:
                lost = 0
            prev, A = A, A2
            res[i] = (np.vstack([A, [0, 0, 1]]), cc)
            weak = weak + 1 if cc < .3 else 0
            if weak >= 15:      # half a second that looks nothing like it: there is no point following further
                break
            if progress:
                progress(len(res), n)
    return res


def _longest_good(flags):
    """(a, b) inclusive indices of the longest run of True, or None."""
    best, start = None, None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if best is None or i - 1 - start > best[1] - best[0]:
                best = (start, i - 1)
            start = None
    return best


def check_rigid(n, fps, first, track, overlaps, visible):
    """Whether one shape can serve this whole range. n: frames; track: {i: (W, match)}; overlaps: {i: carried shape against
    SAM 2's mask}; visible: {i: share of the shape inside the frame}. Returns (ok, reason, facts). Plain words: it goes to
    the person's AI as the reason nothing was made."""
    tracked = np.array([i in track for i in range(n)])
    match = np.array([track[i][1] if i in track else 0.0 for i in range(n)])
    idx = np.array(sorted(i for i in overlaps if i in track))
    over = np.interp(np.arange(n), idx, [overlaps[i] for i in idx]) if len(idx) else np.ones(n)
    vis = np.array([visible.get(i, 1.0) for i in range(n)])
    time_of = lambda i: round((first + int(i)) / fps, 2)
    facts = {'overlap_worst': round(float(over[tracked].min()), 3) if tracked.any() else 0.0,
             'overlap_median': round(float(np.median(over[tracked])), 3) if tracked.any() else 0.0,
             'match_worst': round(float(match.min()), 3), 'match_median': round(float(np.median(match)), 3),
             'visible_worst': round(float(vis.min()), 3)}
    bad_track = ~tracked | (match < MIN_MATCH)
    bad_shape = tracked & (over < MIN_OVERLAP)
    bad_edge = tracked & (vis < MIN_VISIBLE)
    good = ~(bad_track | bad_shape | bad_edge)
    # a frame or two of blur isn't a failed object: only runs longer than a tenth of a second count
    width = max(2, int(round(fps * .1)))
    runs = np.convolve((~good).astype(int), np.ones(width, int), 'same') >= width
    if not runs.any():
        return True, '', facts
    hold = _longest_good(~runs)
    try_range = ''
    if hold and (hold[1] - hold[0]) / fps >= MIN_HOLD_S:
        facts['holds'] = [time_of(hold[0]), time_of(hold[1])]
        try_range = f' It holds from {facts["holds"][0]:.2f} to {facts["holds"][1]:.2f} s: that range would work.'
    # the first thing to go wrong is the reason: what follows it is only its result
    where = lambda flags: int(np.argmax(flags & runs)) if (flags & runs).any() else n
    first_edge, first_shape, first_track = where(bad_edge), where(bad_shape), where(bad_track)
    earliest = min(first_edge, first_shape, first_track)
    if earliest == first_edge and first_edge < n:
        what = (f'it leaves the frame around {time_of(first_edge)} s, and a layer can\'t show what the camera didn\'t see')
    elif earliest == first_shape and first_shape < n:
        stretch = bad_shape & runs
        at = int(np.argmin(np.where(stretch, over, 2.0)))
        what = (f'its outline changes around {time_of(first_shape)} s: one shape matches only {over[at] * 100:.0f}% of it at the worst, so it '
                'bends, moves in parts or turns')
    else:
        what = (f'it stops looking like itself around {time_of(first_track)} s, so it turns to show another side, something covers it, or the '
                'picture blurs too long to follow')
    reason = ('No layer was made: ' + what + '. An object layer carries one shape through the shot, which works for something that keeps its '
              'shape and shows the same side.' + try_range)
    return False, reason, facts


# ---------------------------------------------------------------------------- the outline

def _gauss_wrap(a, sigma):
    if sigma <= 0:
        return a.copy()
    r = int(sigma * 3 + .5)
    k = np.exp(-.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    if a.ndim == 1:
        a2 = np.r_[a[-r:], a, a[:r]] if r else a
        return np.convolve(a2, k, 'valid')
    return np.stack([_gauss_wrap(a[:, i], sigma) for i in range(a.shape[1])], axis=1)


def _resample(points, step):
    p = np.asarray(points, np.float64)
    c = np.vstack([p, p[:1]])
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(c, axis=0).T))]
    t = np.arange(0, d[-1], step)
    return np.c_[np.interp(t, d, c[:, 0]), np.interp(t, d, c[:, 1])]


def corners_of(anchors, degrees=50.0):
    """Which outline points are corners: where the outline turns sharply there."""
    p = np.asarray(anchors, np.float64)
    a = p - np.roll(p, 1, axis=0)
    b = np.roll(p, -1, axis=0) - p
    ang = np.degrees(np.abs(np.arctan2(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0], (a * b).sum(axis=1))))
    return ang >= degrees


def spline(anchors, step=2.0):
    """A smooth closed curve through the outline points, sharp at corners. Returns (points, is_near_corner)."""
    p = np.asarray(anchors, np.float64)
    n = len(p)
    corner = corners_of(p)
    tang = (np.roll(p, -1, axis=0) - np.roll(p, 1, axis=0)) / 2
    out, near = [], []
    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        ma = np.zeros(2) if corner[i] else tang[i]
        mb = np.zeros(2) if corner[(i + 1) % n] else tang[(i + 1) % n]
        # keep the tangents from overshooting on uneven spacing
        length = np.hypot(*(b - a))
        for m_name, m in (('a', ma), ('b', mb)):
            size = np.hypot(*m)
            if size > length:
                m *= length / size
        steps = max(2, int(length / step))
        for k in range(steps):
            t = k / steps
            t2, t3 = t * t, t * t * t
            out.append((2 * t3 - 3 * t2 + 1) * a + (t3 - 2 * t2 + t) * ma + (-2 * t3 + 3 * t2) * b + (t3 - t2) * mb)
            near.append((corner[i] and k < 4) or (corner[(i + 1) % n] and k >= steps - 4))
    return np.array(out), np.array(near)


def snap(path, lab_img, band, lam, prior, keep=None):
    """Move each point of the path along its normal onto the picture's edge, as one smooth path through the edge strength,
    so a stretch with no clear edge stays where it was put."""
    _cv()
    if band <= 0:
        return path.copy()
    tang = _gauss_wrap(path, 3.0)
    tang = np.roll(tang, -1, axis=0) - np.roll(tang, 1, axis=0)
    nor = np.c_[tang[:, 1], -tang[:, 0]]
    nor /= np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-6)
    off = np.arange(-band, band + 1, dtype=np.float32)
    mx = (path[:, 0, None] + nor[:, 0, None] * off).astype(np.float32)
    my = (path[:, 1, None] + nor[:, 1, None] * off).astype(np.float32)
    P = cv2.remap(lab_img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    G = np.linalg.norm(np.gradient(P, axis=1), axis=2)
    G = G / (np.percentile(G.max(axis=1), 90) + 1e-3)
    score = np.minimum(G, 1) + .15 * np.exp(-.5 * (off / prior) ** 2)
    N, M = len(path), len(off)
    seq = np.r_[np.arange(N), np.arange(N // 2)]    # a closed path: once and a half round, the middle part is kept
    D = np.zeros((len(seq), M))
    B = np.zeros((len(seq), M), np.int32)
    D[0] = score[seq[0]]
    states = np.arange(M)
    for k in range(1, len(seq)):
        best = np.full(M, -1e9)
        arg = np.zeros(M, np.int32)
        for d in (-2, -1, 0, 1, 2):
            v = np.roll(D[k - 1], d) - lam * abs(d)
            if d > 0:
                v[:d] = -1e9
            elif d < 0:
                v[d:] = -1e9
            take = v > best
            best[take] = v[take]
            arg[take] = (states - d)[take]
        D[k] = best + score[seq[k]]
        B[k] = arg
    route = np.zeros(len(seq), np.int32)
    route[-1] = int(np.argmax(D[-1]))
    for k in range(len(seq) - 1, 0, -1):
        route[k - 1] = B[k, route[k]]
    o = np.zeros(N)
    o[seq[N // 2:N + N // 2]] = off[route[N // 2:N + N // 2]]
    o = _gauss_wrap(o, 2.0)
    out = path + nor * o[:, None]
    if keep is not None:
        out[keep] = path[keep]
    return out


def matte_from_outline(path, height, width, scale):
    """A soft-edged 16-bit-ready matte from an outline: the edge sits a little inside the real one so no background comes
    along, and is soft by about a pixel and a half of the source."""
    _cv()
    SS = 2
    big = np.zeros((height * SS, width * SS), np.uint8)
    cv2.fillPoly(big, [np.int32(np.round(path * SS * 16))], 255, lineType=cv2.LINE_AA, shift=4)
    m = cv2.resize(big, (width, height), interpolation=cv2.INTER_AREA) > 127
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    if n > 2:
        m = labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    inside = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 5).astype(np.float32)
    outside = cv2.distanceTransform(1 - m.astype(np.uint8), cv2.DIST_L2, 5).astype(np.float32)
    sd = inside - outside
    inset, soft = .75 * scale, 1.5 * scale
    x = np.clip((sd - inset) / soft + .5, 0, 1)
    return x * x * (3 - 2 * x)


def outline_to_matte(plate, anchors, scale, band=None):
    """The outline points -> a curve snapped to the plate's edges -> the matte. Returns (matte, curve)."""
    _cv()
    lab = cv2.GaussianBlur(cv2.cvtColor(plate, cv2.COLOR_BGR2LAB).astype(np.float32), (0, 0), .6 * scale)
    path, near = spline(anchors)
    band = int(band if band is not None else 2 * scale)
    path = snap(path, lab, band, .35, max(1.0, band * .7), keep=near)
    smooth = _gauss_wrap(path, 2.5)
    path = np.where(near[:, None], path, smooth)
    return matte_from_outline(path, plate.shape[0], plate.shape[1], scale), path


def auto_anchors(mask, scale):
    """Outline points from a rough mask: enough to follow its shape, few enough for an AI to move by number."""
    _cv()
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        raise Refused('No outline could be found for this object.')
    c = max(cs, key=len)[:, 0, :].astype(np.float64)
    c = _gauss_wrap(c, 4.0 * scale / 2)
    poly = cv2.approxPolyDP(np.float32(c[:, None, :]), 3.0 * scale, True)[:, 0, :]
    out = []
    limit = 70 * scale
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        out.append([float(a[0]), float(a[1])])
        d = float(np.hypot(*(b - a)))
        for k in range(1, int(d // limit) + 1):
            t = k / (int(d // limit) + 1)
            out.append([float(a[0] + (b[0] - a[0]) * t), float(a[1] + (b[1] - a[1]) * t)])
    return [[round(x, 1), round(y, 1)] for x, y in out]


# ---------------------------------------------------------------------------- objects on disk

def folder_of(object_id):
    if not object_id or not all(ch.isalnum() or ch == '-' for ch in str(object_id)):
        raise Refused(f'{object_id!r} is not an object id')
    return HOME / str(object_id)


def load(object_id):
    p = folder_of(object_id) / 'object.json'
    if not p.is_file():
        raise Refused(f'There is no object {object_id!r} on this PC: letitedit_object make makes one.')
    return json.loads(p.read_text(encoding='utf-8-sig'))


def _save_object(meta, plate, matte, anchors, curve, front_dir=None):
    _cv()
    key = json.dumps({k: meta.get(k) for k in ('clip', 'bytes', 'mtime', 'first', 'count', 'this', 'not_this')}, sort_keys=True) \
        + json.dumps(anchors) + str(ENGINE)
    oid = 'obj-' + hashlib.sha1(key.encode()).hexdigest()[:12]
    d = folder_of(oid)
    d.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(d / 'plate.png'), plate)
    cv2.imwrite(str(d / 'matte.png'), (np.clip(matte, 0, 1) * 65535).astype(np.uint16))
    meta = {**meta, 'id': oid, 'anchors': anchors, 'axis_deg': _axis_deg(matte)}
    if front_dir and Path(front_dir).is_dir() and not (d / 'front').is_dir():
        shutil.copytree(front_dir, d / 'front')
    (d / 'object.json').write_text(json.dumps(meta), encoding='utf-8')
    np.save(d / 'curve.npy', curve)
    return meta


def _axis_deg(matte):
    """The object's long axis, degrees from upright, as a fact the AI can use for `rotate` (0 for something roundish)."""
    ys, xs = np.nonzero(matte[::4, ::4] > .5)
    if len(xs) < 20:
        return 0.0
    c = np.cov(np.c_[xs, ys].T)
    vals, vecs = np.linalg.eigh(c)
    if vals[1] < vals[0] * 1.25:
        return 0.0
    vx, vy = vecs[0, 1], vecs[1, 1]
    if vy < 0:
        vx, vy = -vx, -vy
    return round(math.degrees(math.atan2(vx, vy)), 1)


def _sheets(meta, plate, matte, curve):
    """Pictures to check an object with: the cut-out on two backgrounds, and the numbered outline on the plate."""
    _cv()
    d = folder_of(meta['id'])
    h, w = plate.shape[:2]
    a = matte[..., None]
    p = plate.astype(np.float32)
    dark = (p * a + np.array([34, 28, 24], np.float32) * (1 - a)).astype(np.uint8)
    bright = (p * a + np.array([190, 215, 235], np.float32) * (1 - a)).astype(np.uint8)
    cut = np.hstack([dark, bright])
    s = min(1.0, 1100 / max(cut.shape[:2]))
    one = d / 'cutout.jpg'
    cv2.imwrite(str(one), cv2.resize(cut, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 90])
    s2 = min(1.0, 1500 / max(h, w))
    pic = cv2.resize(plate, None, fx=s2, fy=s2, interpolation=cv2.INTER_AREA)
    pic = _grid(pic, 100, s2)
    cv2.polylines(pic, [np.int32(curve * s2)], True, (255, 0, 255), 1, cv2.LINE_AA)
    for i, (x, y) in enumerate(meta['anchors']):
        X, Y = int(x * s2), int(y * s2)
        cv2.circle(pic, (X, Y), 3, (0, 255, 0), -1)
        cv2.putText(pic, str(i), (X + 4, Y - 4), 0, .42, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(pic, str(i), (X + 4, Y - 4), 0, .42, (120, 255, 120), 1, cv2.LINE_AA)
    two = d / 'outline.jpg'
    cv2.imwrite(str(two), pic, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return [str(one), str(two)]


def _noise_of(frame_stab, matte):
    res = frame_stab - cv2.GaussianBlur(frame_stab, (0, 0), 2.0)
    core = cv2.erode((matte > .9).astype(np.uint8), np.ones((21, 21), np.uint8)) > 0
    return float(np.median(np.abs(res[core])) * 1.48) if core.any() else 1.0


def _reply(meta, pictures):
    return {'made': True, 'object': meta['id'], 'clip': meta['clip'], 'start': meta['start'], 'end': meta['end'],
            'outline_points': [[i, x, y] for i, (x, y) in enumerate(meta['anchors'])], 'plate_size': [meta['plate_w'], meta['plate_h']],
            'plate_scale': meta['S'], 'axis_deg': meta['axis_deg'], 'checks': meta['checks'], 'clear': meta['clear'], 'pictures': pictures,
            'cost': meta.get('cost')}


def make(clip, start, end, at, this, not_this=None, in_front=None, progress=None):
    """Follow, track, check, plate, outline. Returns the object, or {'made': False, 'why': plain words, ...}."""
    _cv()
    clip = str(Path(clip))
    if not Path(clip).is_file():
        raise Refused(f'No such file: {clip}')
    if not this:
        raise Refused('Give this: at least one point on the object, in the clip\'s pixels, on the frame at `at`.')
    info = probe(clip)
    fps = info['fps']
    start, end, at = float(start), float(end), float(at)
    if end <= start:
        raise Refused('end has to be after start.')
    if end - start > MAX_SECONDS:
        raise Refused(f'An object layer covers at most {MAX_SECONDS:.0f} s at a time; this asks for {end - start:.0f} s.')
    if not start <= at <= end:
        raise Refused(f'at ({at:.2f} s) has to be inside the range ({start:.2f} to {end:.2f} s).')
    first, last = _frame_no(start, fps), _frame_no(end, fps)
    count = max(2, last - first)
    stamp = {}
    t0 = time.perf_counter()
    work = _work_dir('make')
    try:
        raw, count = _raw_range(clip, first, count, info, work)
        shape = (count, info['height'], info['width'], 3)
        key = min(count - 1, max(0, _frame_no(at, fps) - first))
        stride = max(1, int(round(fps / 10)))
        idx = sorted(set(range(key % stride, count, stride)) | {key})
        points = [list(map(float, p)) for p in this] + [list(map(float, p)) for p in (not_this or [])]
        labels = [1] * len(this) + [0] * len(not_this or [])
        jobs = [{'name': 'object', 'key': key, 'indices': idx, 'points': points, 'labels': labels, 'out': str(work / 'sam')}]
        if in_front:
            jobs.append({'name': 'front', 'key': key, 'indices': list(range(count)), 'points': [list(map(float, p)) for p in in_front],
                         'labels': [1] * len(in_front), 'out': str(work / 'sam')})
        tick = time.perf_counter()
        sam_report = _sam(raw, shape, jobs)
        stamp['follow_s'] = round(time.perf_counter() - tick, 1)
        key_mask = _read_mask(work / 'sam' / f'object_{key:05d}.png')
        if (key_mask > .5).sum() < 200:
            raise Refused('SAM 2 found almost nothing at those points. Look at the frame again and put `this` points well inside '
                          'the object (letitedit_object try shows what they pick).')
        front_at = lambda i: _read_mask(work / 'sam' / f'front_{i:05d}.png') if in_front else None
        tick = time.perf_counter()
        track = _track(raw, shape, key, key_mask, front_at(key))
        stamp['track_s'] = round(time.perf_counter() - tick, 1)
        # the checks: the carried shape against SAM 2's masks, and how much of it stays in the frame
        H, W = info['height'], info['width']
        overlaps, visible = {}, {}
        ys, xs = np.nonzero(key_mask[::2, ::2] > .5)
        pts = np.c_[xs * 2, ys * 2, np.ones(len(xs))]
        for i, (A, _) in track.items():
            q = pts @ A[:2].T
            visible[i] = float(((q[:, 0] >= 0) & (q[:, 0] < W) & (q[:, 1] >= 0) & (q[:, 1] < H)).mean())
        for i in idx:
            if i not in track:
                overlaps[i] = 0.0
                continue
            p = work / 'sam' / f'object_{i:05d}.png'
            if not p.is_file():
                continue
            m = _read_mask(p) > .5
            carried = cv2.warpAffine(key_mask, track[i][0][:2], (W, H), flags=cv2.INTER_LINEAR) > .5
            if in_front:
                f = front_at(i) > .5
                m, carried = m & ~f, carried & ~f
            union = (m | carried).sum()
            overlaps[i] = float((m & carried).sum() / union) if union else 0.0
        ok, why, facts = check_rigid(count, fps, first, track, overlaps, visible)
        if not ok:
            return {'made': False, 'why': why, 'checks': facts, 'cost': stamp}
        # the plate: about 60 frames lined up at twice the size, whatever was in front left out
        tick = time.perf_counter()
        x, y, bw, bh = cv2.boundingRect((key_mask > .5).astype(np.uint8))
        pad = max(16, int(max(bw, bh) * .08))
        x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + bw + pad), min(H, y + bh + pad)
        S = 2.0 if max(x1 - x0, y1 - y0) * 2 <= 2600 else 2600.0 / max(x1 - x0, y1 - y0)
        A = np.float64([[S, 0, -x0 * S], [0, S, -y0 * S], [0, 0, 1]])
        PW, PH = int((x1 - x0) * S), int((y1 - y0) * S)
        frames = np.memmap(raw, dtype=np.uint8, mode='r', shape=shape)
        use = [i for i in range(count) if i in track][::max(1, count // 60)]
        stack = np.zeros((len(use), PH, PW, 3), np.uint8)
        covered = np.zeros((len(use), PH, PW), bool)
        for k, i in enumerate(use):
            M = (A @ np.linalg.inv(track[i][0]))[:2]
            stack[k] = cv2.warpAffine(np.asarray(frames[i]), M, (PW, PH), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
            if in_front:
                f = cv2.dilate(front_at(i), np.ones((int(9 * S) | 1, int(9 * S) | 1), np.uint8))
                covered[k] = cv2.warpAffine(f, M, (PW, PH), flags=cv2.INTER_LINEAR) > .2
        plate = np.zeros((PH, PW, 3), np.uint8)
        for row in range(0, PH, 64):
            block = stack[:, row:row + 64].astype(np.float32)
            block[covered[:, row:row + 64]] = np.nan
            value = np.nanmedian(block, axis=0)
            plate[row:row + 64] = np.clip(np.nan_to_num(value, nan=128), 0, 255).astype(np.uint8)
        del stack, covered
        stamp['plate_s'] = round(time.perf_counter() - tick, 1)
        # a first outline: SAM 2 again on the clean plate (it keeps thin parts), BiRefNet with the surroundings dimmed (it
        # finds the best edge on the body). The AI sees it numbered and moves what's wrong.
        tick = time.perf_counter()
        to_plate = lambda p: [float(p[0]) * S - x0 * S, float(p[1]) * S - y0 * S]
        plate_raw = work / 'plate.raw'
        plate_raw.write_bytes(plate.tobytes())
        sam2 = _sam(plate_raw, (1, PH, PW, 3), [{'name': 'plate', 'key': 0, 'indices': [0],
                                                 'points': [to_plate(p) for p in points], 'labels': labels, 'out': str(work / 'p')}])
        sam_plate = _read_mask(work / 'p' / 'plate_00000.png')
        rough = _first_outline(plate, sam_plate, S)
        anchors = auto_anchors(rough, S)
        matte, curve = outline_to_matte(plate, anchors, S, band=int(4 * S))
        stamp['outline_s'] = round(time.perf_counter() - tick, 1)
        # what's in front, kept small, for the layer to stay behind it near the hand-offs
        front_dir = None
        clear = [[round(start, 3), round(end, 3)]]
        if in_front:
            front_dir = work / 'front_small'
            front_dir.mkdir()
            touching = []
            for i in range(count):
                f = front_at(i)
                cv2.imwrite(str(front_dir / f'{i:05d}.png'), cv2.resize((f * 255).astype(np.uint8), None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA))
                carried = cv2.warpAffine(key_mask, track[i][0][:2], (W, H), flags=cv2.INTER_LINEAR) > .5 if i in track else np.zeros((H, W), bool)
                touching.append(bool(((f > .5) & carried).sum() > 25))
            clear = []
            s = None
            for i, t in enumerate(touching + [True]):
                if not t and s is None:
                    s = i
                elif t and s is not None:
                    if (i - s) / fps >= .1:
                        clear.append([round((first + s) / fps, 3), round((first + i - 1) / fps, 3)])
                    s = None
        st = os.stat(clip)
        probe_frame = np.asarray(frames[key])
        M = (A @ np.linalg.inv(track[key][0]))[:2]
        noise = _noise_of(cv2.warpAffine(probe_frame, M, (PW, PH), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE).astype(np.float32), matte)
        stamp['total_s'] = round(time.perf_counter() - t0, 1)
        stamp['gpu_peak_mb'] = sam_report.get('gpu_peak_mb')
        meta = {'clip': clip, 'bytes': st.st_size, 'mtime': int(st.st_mtime), 'first': first, 'count': count, 'start': round(first / fps, 4),
                'end': round((first + count - 1) / fps, 4), 'fps': fps, 'width': W, 'height': H, 'key': key,
                'x0': x0, 'y0': y0, 'S': S, 'plate_w': PW, 'plate_h': PH, 'this': points[:len(this)], 'not_this': points[len(this):],
                'in_front': bool(in_front), 'track': {str(i): track[i][0][:2].round(5).tolist() for i in track}, 'noise': round(noise, 3),
                'checks': facts, 'clear': clear, 'cost': stamp, 'engine': ENGINE}
        meta = _save_object(meta, plate, matte, anchors, curve, front_dir)
        return _reply(meta, _sheets(meta, plate, matte, curve))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _first_outline(plate, sam_plate, S):
    """The rough shape: BiRefNet's body within SAM 2's outline, plus the thin parts only SAM 2 kept."""
    _cv()
    ell = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    sam = sam_plate > .5
    birefnet = None
    try:
        sys.path.insert(0, str(ROOT / 'vfx')) if str(ROOT / 'vfx') not in sys.path else None
        from letitedit_vfx.birefnet import MatteWorker
        import letitedit.sound.model_tools as model_tools
        import letitedit.core.render_lock as render_lock
        near = cv2.dilate(sam.astype(np.uint8), ell(int(4 * S))).astype(np.float32)
        near = cv2.GaussianBlur(near, (0, 0), 1.5 * S)[..., None]
        dim = (plate * near + np.array([28, 28, 28]) * (1 - near)).astype(np.uint8)
        with render_lock.model_slot('object outline'), model_tools._gpu_turn():
            worker = MatteWorker()
            try:
                birefnet = np.clip(worker(dim[..., ::-1]), 0, 1) > .5
            finally:
                worker.proc.stdin.close()
    except Exception:  # noqa: BLE001 - SAM 2's outline alone still gives the AI something to correct
        birefnet = None
    if birefnet is None:
        rough = sam.astype(np.uint8)
    else:
        radius = max(4, int(5 * S))
        opened = cv2.morphologyEx(sam.astype(np.uint8), cv2.MORPH_OPEN, ell(radius))
        thin = sam & (opened == 0)
        body = birefnet & cv2.dilate(sam.astype(np.uint8), ell(int(5 * S))).astype(bool)
        rough = (body | thin).astype(np.uint8)
    rough = cv2.morphologyEx(cv2.morphologyEx(rough, cv2.MORPH_CLOSE, ell(int(3 * S))), cv2.MORPH_OPEN, ell(int(1 * S)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(rough, connectivity=8)
    if n <= 1:
        raise Refused('No outline could be found on the clean picture of this object.')
    return (labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)


def edit_outline(object_id, move=None, drop=None, add=None, points=None):
    """Change the outline by point number, or replace it. A new object id; the old one stays."""
    _cv()
    meta = load(object_id)
    d = folder_of(object_id)
    plate = cv2.imread(str(d / 'plate.png'))
    anchors = [list(map(float, p)) for p in (points if points is not None else meta['anchors'])]
    n = len(anchors)
    if points is None:
        for key, value in (move or {}).items():
            i = int(key)
            if not 0 <= i < n:
                raise Refused(f'There is no outline point {i}: they run from 0 to {n - 1}.')
            anchors[i] = [float(value[0]), float(value[1])]
        gone = {int(i) for i in (drop or [])}
        extra = {}
        for row in add or []:
            if len(row) != 3:
                raise Refused('add takes rows of [after_point, x, y].')
            extra.setdefault(int(row[0]), []).append([float(row[1]), float(row[2])])
        out = []
        for i, p in enumerate(anchors):
            if i not in gone:
                out.append(p)
            out.extend(extra.get(i, []))
        anchors = out
    if len(anchors) < 3:
        raise Refused('An outline needs at least three points.')
    PH, PW = plate.shape[:2]
    for x, y in anchors:
        if not (-5 <= x <= PW + 5 and -5 <= y <= PH + 5):
            raise Refused(f'The point ({x:.0f}, {y:.0f}) is outside the plate, which is {PW} by {PH}.')
    matte, curve = outline_to_matte(plate, anchors, meta['S'])
    keep = {k: meta[k] for k in meta if k not in ('id', 'anchors', 'axis_deg')}
    keep['parent'] = meta['id']
    new = _save_object(keep, plate, matte, [[round(a, 1), round(b, 1)] for a, b in anchors], curve, d / 'front')
    return _reply(new, _sheets(new, plate, matte, curve))


# ---------------------------------------------------------------------------- where the object is

def fit_of(meta, W, H):
    """How the shot sits in the project's frame (the normal fit: whole picture, centred). 3x3, source px -> project px."""
    f = min(W / meta['width'], H / meta['height'])
    return np.float64([[f, 0, (W - f * meta['width']) / 2], [0, f, (H - f * meta['height']) / 2], [0, 0, 1]])


def plate_to_shot(meta, index):
    """3x3: plate px -> this frame's source px."""
    S = meta['S']
    A = np.float64([[S, 0, -meta['x0'] * S], [0, S, -meta['y0'] * S], [0, 0, 1]])
    W = np.vstack([np.float64(meta['track'][str(index)]), [0, 0, 1]])
    return W @ np.linalg.inv(A)


def nearest_tracked(meta, index):
    if str(index) in meta['track']:
        return index
    keys = sorted(int(k) for k in meta['track'])
    return min(keys, key=lambda k: abs(k - index))


def center_of(meta, matte=None):
    """The middle of the object in plate px."""
    if meta.get('center'):
        return meta['center']
    a = np.array(meta['anchors'])
    return [float((a[:, 0].min() + a[:, 0].max()) / 2), float((a[:, 1].min() + a[:, 1].max()) / 2)]


def canvas_map(meta, W, H, scale, rotate=0.0):
    """3x3: plate px -> the steady movie's picture: the object in the middle, at `scale`, turned by `rotate` degrees."""
    c = center_of(meta)
    r = math.radians(rotate)
    co, si = math.cos(r) * scale, math.sin(r) * scale
    return np.float64([[co, -si, W / 2 - co * c[0] + si * c[1]], [si, co, H / 2 - si * c[0] - co * c[1]], [0, 0, 1]])


def size_of(meta):
    a = np.array(meta['anchors'])
    return float(a[:, 0].max() - a[:, 0].min()), float(a[:, 1].max() - a[:, 1].min())


def pose(meta, index, W, H, scale, rotate=0.0):
    """Where the steady movie's picture has to go to put the object where it really is in this frame: (x, y, w, h,
    degrees), the picture's rectangle and its turn about its centre, in project px."""
    i = nearest_tracked(meta, index)
    Q = fit_of(meta, W, H) @ plate_to_shot(meta, i) @ np.linalg.inv(canvas_map(meta, W, H, scale, rotate))
    a, b, c, d = Q[0, 0], Q[0, 1], Q[1, 0], Q[1, 1]
    s = math.sqrt(abs(a * d - b * c))
    deg = math.degrees(math.atan2(c - b, a + d))
    cx, cy = Q[0, 0] * W / 2 + Q[0, 1] * H / 2 + Q[0, 2], Q[1, 0] * W / 2 + Q[1, 1] * H / 2 + Q[1, 2]
    return cx - s * W / 2, cy - s * H / 2, s * W, s * H, deg


def filled_still(meta, index):
    """This frame of the shot with the object filled in (LaMa, on the CPU when there's no GPU runtime), hand kept."""
    _cv()
    d = folder_of(meta['id']) / 'stills'
    d.mkdir(exist_ok=True)
    out = d / f'{index:05d}.png'
    if out.is_file():
        return str(out)
    info = {'width': meta['width'], 'height': meta['height'], 'fps': meta['fps']}
    frame = None
    for f in decode(meta['clip'], meta['first'] + index, 1, info):
        frame = f.copy()
    if frame is None:
        raise Refused(f"{Path(meta['clip']).name} has no frame {meta['first'] + index}")
    matte = cv2.imread(str(folder_of(meta['id']) / 'matte.png'), cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535
    R = plate_to_shot(meta, nearest_tracked(meta, index))
    hole = cv2.warpAffine(matte, R[:2], (meta['width'], meta['height']), flags=cv2.INTER_LINEAR) > .05
    grow = max(9, int(max(meta['width'], meta['height']) * .012)) | 1
    hole = cv2.dilate(hole.astype(np.uint8), np.ones((grow, grow), np.uint8))
    front = folder_of(meta['id']) / 'front' / f'{index:05d}.png'
    if front.is_file():
        f = cv2.resize(cv2.imread(str(front), cv2.IMREAD_GRAYSCALE), (meta['width'], meta['height']), interpolation=cv2.INTER_LINEAR)
        hole[f > 127] = 0
    if str(ROOT / 'creator') not in sys.path:
        sys.path.insert(0, str(ROOT / 'creator'))
    from letitedit_creator import tracking
    filled = tracking.lama(frame[..., ::-1].copy(), hole * 255)[..., ::-1]
    tmp = out.with_name(out.stem + '.tmp.png')
    cv2.imwrite(str(tmp), filled)
    os.replace(tmp, out)
    return str(out)


# ---------------------------------------------------------------------------- the movie

class _Frames:
    """Frames of the clip by index in the object's range, read forward, with a few kept."""

    def __init__(self, meta, first_index, count):
        self.meta = meta
        self.base = first_index
        info = {'width': meta['width'], 'height': meta['height'], 'fps': meta['fps']}
        self.gen = decode(meta['clip'], meta['first'] + first_index, count, info)
        self.next = first_index
        self.have = {}

    def get(self, i):
        while self.next <= i:
            f = next(self.gen, None)
            if f is None:
                self.next = i + 1
                break
            self.have[self.next] = f.copy()
            self.next += 1
            for k in [k for k in self.have if k < i - 4]:
                del self.have[k]
        if i in self.have:
            return self.have[i]
        return self.have[max(self.have)] if self.have else None


def _edge_tools(matte, S):
    """For taking the colours at the edge from further inside, so no background comes along."""
    ins = cv2.distanceTransform((matte > .5).astype(np.uint8), cv2.DIST_L2, 5)
    core = (ins >= 3.5 * S).astype(np.uint8)
    _, labels = cv2.distanceTransformWithLabels(1 - core, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.where(core > 0)
    table = np.zeros(labels.max() + 1, np.int64)
    table[labels[ys, xs]] = np.arange(len(ys))
    near = table[labels]
    band = cv2.GaussianBlur((1 - core).astype(np.float32), (0, 0), .75 * S)[..., None]
    return xs[near].astype(np.float32), ys[near].astype(np.float32), band


def _recolour(frame_bgr, alpha, color):
    target = cv2.cvtColor(np.uint8([[color]]), cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    m = alpha
    lab[..., 1] = lab[..., 1] * (1 - m) + (128 + (target[1] - 128) * .95 + (lab[..., 1] - 128) * .15) * m
    lab[..., 2] = lab[..., 2] * (1 - m) + (128 + (target[2] - 128) * .95 + (lab[..., 2] - 128) * .15) * m
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def _hex_bgr(text, default=(120, 215, 255)):
    t = str(text or '').lstrip('#')
    if len(t) != 6:
        return default
    return (int(t[4:6], 16), int(t[2:4], 16), int(t[0:2], 16))


def render_movie(params, source, W, H, fps, out_path):
    """The {vfx: {effect: object}} movie: RGBA frames to ProRes 4444.
    show: object (the object alone) | outline | glow | recolour; steady: true = in its own coordinates, in the middle of the
    picture (object_lift keys it to where it needs to be); false = where it is in the shot."""
    _cv()
    meta = load(params['object'])
    d = folder_of(meta['id'])
    plate = cv2.imread(str(d / 'plate.png')).astype(np.float32)
    matte = cv2.imread(str(d / 'matte.png'), cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535
    PH, PW = matte.shape
    S = meta['S']
    show = params.get('show') or 'object'
    steady = bool(params.get('steady'))
    native = meta['fps']
    a, b = float(source['in']), float(source['out'])
    n_out = max(1, int(round((b - a) * fps)))
    first_index = _frame_no(a, native) - meta['first']
    span = int(math.ceil(n_out * native / fps)) + 3
    if first_index < 0 or first_index + int(n_out * native / fps) > meta['count'] + 1:
        raise Refused(f"Object {meta['id']} was made for {meta['start']:.2f} to {meta['end']:.2f} s of {Path(meta['clip']).name}; "
                      f'this asks for {a:.2f} to {b:.2f} s.')
    reader = _Frames(meta, max(0, first_index - 1), span + 2)
    scale = float(params.get('scale') or 1.0)
    rotate = float(params.get('rotate') or 0.0)
    C = canvas_map(meta, W, H, scale, rotate)
    fit = fit_of(meta, W, H)
    mapx, mapy, band = _edge_tools(matte, S)
    high = plate - cv2.GaussianBlur(plate, (0, 0), 3.5 * S)
    rng = np.random.default_rng(1)
    grain_amount = float(params.get('grain', meta.get('noise', 1.0))) * max(.6, scale * 1.2)
    color = _hex_bgr(params.get('color'))
    width = float(params.get('width') or 2.2)
    fb, fa = params.get('front_before'), params.get('front_after')
    frames_dir = d / 'front'
    ramp_n = 6.0

    def front_mask(i):
        p = frames_dir / f'{i:05d}.png'
        if not p.is_file():
            return None
        return cv2.resize(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE), (meta['width'], meta['height']), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255

    def stabilised(i):
        ii = nearest_tracked(meta, max(0, min(meta['count'] - 1, i)))
        f = reader.get(i)
        if f is None:
            return None
        M = np.linalg.inv(plate_to_shot(meta, ii))[:2]
        o = cv2.warpAffine(f, M, (PW, PH), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        m = front_mask(ii)
        if m is not None and m.any():
            h = cv2.warpAffine(cv2.dilate(m, np.ones((5, 5), np.uint8)), M, (PW, PH), flags=cv2.INTER_LINEAR)
            h = np.clip(cv2.GaussianBlur(h, (0, 0), 1.5 * S) * 1.4, 0, 1)[..., None]
            o = o * (1 - h) + plate * h
        return o
    cache = {}

    def stab(i):
        if i not in cache:
            cache[i] = stabilised(i)
            for k in [k for k in cache if k < i - 3]:
                del cache[k]
        return cache[i]
    tmp_alpha = None
    if steady:
        tmp_alpha = np.clip(cv2.warpAffine(matte, C[:2], (W, H), flags=cv2.INTER_CUBIC), 0, 1)
    enc = subprocess.Popen([str(_ff()), '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgra', '-s', f'{W}x{H}',
                            '-framerate', f'{fps:.6f}', '-i', '-', '-threads', '4', '-c:v', 'prores_ks', '-profile:v', '4444',
                            '-pix_fmt', 'yuva444p10le', '-vendor', 'apl0', str(out_path)], stdin=subprocess.PIPE)
    try:
        for n in range(n_out):
            t = a + n / fps
            i = first_index + int(round(n * native / fps))
            ii = nearest_tracked(meta, max(0, min(meta['count'] - 1, i)))
            fm = None
            if fb is not None or fa is not None:
                w = 0.0
                if fb is not None and t <= float(fb) + ramp_n / fps:
                    w = max(w, 1.0 if t <= float(fb) else 1 - (t - float(fb)) * fps / ramp_n)
                if fa is not None and t >= float(fa) - ramp_n / fps:
                    w = max(w, 1.0 if t >= float(fa) else 1 - (float(fa) - t) * fps / ramp_n)
                if w > 0:
                    m = front_mask(ii)
                    if m is not None:
                        fm = np.clip(cv2.GaussianBlur(m, (0, 0), 1.0) * 1.3, 0, 1) * w
            if steady:
                # this moment's light, the plate's sharp detail, then the camera's own grain back on
                now = [x for x in (stab(i - 1), stab(i), stab(i + 1)) if x is not None]
                o = np.mean(now, axis=0) if now else plate
                low = cv2.GaussianBlur(o, (0, 0), 3.5 * S)
                o = low + high
                inner = cv2.GaussianBlur(cv2.remap(o, mapx, mapy, cv2.INTER_LINEAR), (0, 0), .6 * S)
                o = o * (1 - band) + inner * band
                rgb = cv2.warpAffine(o, C[:2], (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
                al = tmp_alpha.copy()
                if fm is not None:
                    shot_to_canvas = C @ np.linalg.inv(plate_to_shot(meta, ii))
                    al = al * (1 - cv2.warpAffine(fm, shot_to_canvas[:2], (W, H), flags=cv2.INTER_LINEAR))
                if grain_amount > 0:
                    g = rng.normal(0, 1, (H, W)).astype(np.float32)
                    g = cv2.GaussianBlur(g, (0, 0), 1.0)
                    g /= g.std() + 1e-6
                    rgb = rgb + grain_amount * g[..., None]
            else:
                f = reader.get(i)
                Q = fit @ plate_to_shot(meta, ii)
                frame = cv2.warpAffine(f, fit[:2], (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE) if (W, H) != (meta['width'], meta['height']) else f
                al = np.clip(cv2.warpAffine(matte, Q[:2], (W, H), flags=cv2.INTER_CUBIC), 0, 1)
                if fm is None:
                    m = front_mask(ii)
                    if m is not None:
                        fm = np.clip(cv2.GaussianBlur(m, (0, 0), 1.0) * 1.3, 0, 1)
                if fm is not None:
                    al = al * (1 - cv2.warpAffine(fm, fit[:2], (W, H), flags=cv2.INTER_LINEAR))
                if show == 'recolour':
                    rgb = _recolour(frame, al, color).astype(np.float32)
                elif show in ('outline', 'glow'):
                    line = np.clip((cv2.GaussianBlur(al, (0, 0), width) - al) * 3.2, 0, 1)
                    small = cv2.resize(al, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
                    halo = cv2.resize(cv2.GaussianBlur(small, (0, 0), 9), (W, H), interpolation=cv2.INTER_LINEAR)
                    halo = np.clip(halo - al, 0, 1)
                    al = np.maximum(line, halo * .62) if show == 'glow' else line
                    rgb = np.empty((H, W, 3), np.float32)
                    rgb[:] = color
                else:
                    rgb = frame.astype(np.float32)
            bgra = np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), np.clip(al * 255, 0, 255).astype(np.uint8)])
            enc.stdin.write(bgra.tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
    return n_out
