"""Picture lanes of the timing store (timing_signals): frame_features, motion, visual_beats, motion_events,
attention, shots.

frame_features (cached per render chunk / file, so a small edit re-analyses only the chunks it changed): every
frame of the analysed source is decoded once (preview size, or the file scaled to 640 px long side) and measured
against the frame before it:
  * dense optical flow (OpenCV DIS, preset `flow_preset`, on grey frames scaled to `flow_px` long side);
  * the camera's own move: a similarity (shift, zoom, roll) fitted with RANSAC to the flow sampled every `fit_step`
    px (inliers within `fit_px`); the inlier share is the estimate's trust;
  * residual flow = flow minus the camera's flow field: its mean magnitude over the frame minus a `border` margin
    is the motion energy (px/frame at the flow size), the share of pixels moving more than `move_px`, a
    directogram (residual magnitude summed in 16 screen directions, Davis & Agrawala 2018), the strongest moving
    region (cells of the residual magnitude above max(`region_px`, `region_rel` x the strongest cell); the
    connected group with the most motion) and its direction (magnitude-weighted mean of the residual vectors,
    with their coherence 0-1);
  * still-image saliency (OpenCV spectral residual, Hou & Zhang 2007, at `sal_px`) and the residual motion, both
    as coarse grids; faces (OpenCV YuNet, score >= `face_score`) every `face_every` frames; mean and spread of luma.

The lanes read these numbers (cheap; thresholds in timing_thresholds.json):
  motion        per frame energy, camera {dx, dy, zoom, rot}, camera_label, direction, region (+ camera_trust,
                moving_share, energy_p90, raw_energy). Values at cut frames and inside transitions are None.
  visual_beats  sharp decelerations of subject motion: peaks of the impact envelope u(f) = sum over directions of
                the drop in the directogram from f-1 to f (Davis & Agrawala 2018 'Visual Rhythm and Beat'), each
                with the frame motion comes to rest after it (f_stop: the local minimum of motion speed after the
                peak, the spec's simpler reading).
  motion_events onset, peak and end of each burst of subject motion: energy (smoothed) rising above the shot's own
                resting level by a margin, onset/end where it falls back below a share of the rise.
  attention     where the eye is likely to go, per frame: a map of saliency + faces + residual motion + a centre
                bias (weights in settings), its weighted centre {x, y} and spread; faces as detected.
  shots         the shots between cuts with how they begin and their size from face height (closeup / medium /
                wide; unknown without a face), or the meaning lane's label when present.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import letitedit.timing.timing_signals as ts

FEATURE_VERSION = 2
MAX_GAP = 3                    # decoded frames up to this many grid frames apart still form a measured pair
FEATURES = ts.CACHE / 'features'
DIRS = 16                      # directogram bins

FEATURE_DEFAULTS = {
    'analysis_px': 640,        # long side of decoded frames (faces run at this size)
    'flow_px': 256,            # long side of the frames optical flow runs on (energy is px/frame at this size)
    'flow_preset': 'fast',     # DIS preset: ultrafast | fast | medium
    'fit_step': 6,             # flow sampled every this many px for the camera fit
    'fit_px': 0.5,             # RANSAC inlier distance (px at the flow size)
    'border': 0.04,            # margin (share of each side) left out of the motion measures
    'move_px': 0.5,            # a pixel 'moves' when its residual flow is at least this (px/frame)
    'region_px': 0.6,          # strongest region: cells moving at least this ...
    'region_rel': 0.35,        # ... and at least this share of the strongest cell
    'sal_px': 128,             # long side for saliency
    'grid_cells': 144,         # cells of the coarse saliency / motion grids (rows x cols by the frame's shape)
    'face_every': 3,           # faces on every n-th frame (frame index multiple of n)
    'face_score': 0.6,         # YuNet score threshold
    'workers': 3,              # frame-pair worker threads (OpenCV itself is held to 1 thread each: modest load)
}


# ============================================================================ helpers

def _grid_shape(w, h, cells):
    """(rows, cols) with about `cells` square-ish cells for a w x h frame."""
    cols = max(2, int(round(math.sqrt(cells * w / h))))
    rows = max(2, int(round(cells / cols)))
    return rows, cols


def _size_for(w, h, px):
    s = float(px) / max(w, h)
    return max(16, int(round(w * s / 2)) * 2), max(16, int(round(h * s / 2)) * 2)


def _block_mean(a, rows, cols):
    import cv2
    return cv2.resize(a, (cols, rows), interpolation=cv2.INTER_AREA)


_TLS = threading.local()


def _dis(preset):
    import cv2
    try:
        cv2.setNumThreads(1)       # the workers are the parallelism; keep the PC's load modest
    except Exception:  # noqa: BLE001
        pass
    d = getattr(_TLS, 'dis', None)
    if d is None or getattr(_TLS, 'dis_preset', None) != preset:
        p = {'ultrafast': cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST, 'fast': cv2.DISOPTICAL_FLOW_PRESET_FAST,
             'medium': cv2.DISOPTICAL_FLOW_PRESET_MEDIUM}[preset]
        d = cv2.DISOpticalFlow_create(p)
        _TLS.dis, _TLS.dis_preset = d, preset
    return d


def _saliency():
    import cv2
    s = getattr(_TLS, 'sal', None)
    if s is None:
        s = _TLS.sal = cv2.saliency.StaticSaliencySpectralResidual_create()
    return s


def _faces_detector(w, h, score):
    import cv2
    import letitedit.review.checks as checks
    key = (w, h, score)
    det = getattr(_TLS, 'yunet', None)
    if det is None or getattr(_TLS, 'yunet_key', None) != key:
        if not checks.faces_available():
            return None
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except AttributeError:
            pass
        det = cv2.FaceDetectorYN.create(str(checks.YUNET), '', (w, h), float(score), 0.3, 50)
        _TLS.yunet, _TLS.yunet_key = det, key
    return det


class _Static:
    """Per-size constants: sample grid for the camera fit, coordinate grids, the valid (border) mask."""
    def __init__(self, fw, fh, st):
        step = int(st['fit_step'])
        m = max(2, int(round(float(st['border']) * min(fw, fh))))
        ys, xs = np.mgrid[m:fh - m:step, m:fw - m:step]
        self.sy, self.sx = ys.ravel(), xs.ravel()
        self.pts = np.stack([self.sx, self.sy], 1).astype(np.float32)
        self.X, self.Y = np.meshgrid(np.arange(fw, dtype=np.float32), np.arange(fh, dtype=np.float32))
        mb = max(1, int(round(float(st['border']) * fw))), max(1, int(round(float(st['border']) * fh)))
        self.valid = np.zeros((fh, fw), bool)
        self.valid[mb[1]:fh - mb[1], mb[0]:fw - mb[0]] = True
        self.nvalid = int(self.valid.sum())
        self.cx, self.cy = (fw - 1) / 2.0, (fh - 1) / 2.0
        self.fw, self.fh = fw, fh
        self.rows, self.cols = _grid_shape(fw, fh, int(st['grid_cells']))
        # region grid: cells of about 8 px
        self.rrows, self.rcols = max(4, fh // 8), max(4, fw // 8)


def pair_features(prev_g, g, S, st):
    """Measures of the step prev_g -> g (grey uint8 at the flow size). Returns a dict of numbers and arrays."""
    import cv2
    flow = _dis(st['flow_preset']).calc(prev_g, g, None)
    fx, fy = flow[..., 0], flow[..., 1]
    d = flow[S.sy, S.sx]
    M, inl = None, None
    try:
        M, inl = cv2.estimateAffinePartial2D(S.pts, S.pts + d, method=cv2.RANSAC,
                                             ransacReprojThreshold=float(st['fit_px']), maxIters=300,
                                             confidence=0.99, refineIters=10)
    except cv2.error:
        M = None
    if M is None:
        med = np.median(d, axis=0)
        M = np.float32([[1, 0, med[0]], [0, 1, med[1]]])
        trust = 0.0
    else:
        trust = float(inl.sum()) / max(1, len(S.pts))
    a, b, tx, ty = float(M[0, 0]), float(M[1, 0]), float(M[0, 2]), float(M[1, 2])
    camx = (a - 1.0) * S.X - b * S.Y + tx
    camy = b * S.X + (a - 1.0) * S.Y + ty
    rx, ry = fx - camx, fy - camy
    mag = np.sqrt(rx * rx + ry * ry)
    mv = mag[S.valid]
    energy = float(mv.mean())
    p90 = float(np.percentile(mv, 90))
    moving = float((mv >= float(st['move_px'])).mean())
    raw = float(np.sqrt(fx * fx + fy * fy)[S.valid].mean())
    # directogram: residual magnitude by screen direction (0 = right, 90 = up)
    ang = (np.degrees(np.arctan2(-ry, rx)) % 360.0)[S.valid]
    sel = mv >= 0.25 * float(st['move_px'])
    hist = np.bincount((ang[sel] // (360.0 / DIRS)).astype(np.int64) % DIRS, weights=mv[sel], minlength=DIRS)
    directo = (hist / S.nvalid).astype(np.float32)
    # the strongest moving region
    magv = np.where(S.valid, mag, 0.0).astype(np.float32)
    cell = _block_mean(magv, S.rrows, S.rcols)
    top = float(cell.max())
    region = [np.nan] * 4
    rmag = rdir = rcoh = np.nan
    if top >= float(st['region_px']):
        thr = max(float(st['region_px']), float(st['region_rel']) * top)
        mask = (cell >= thr).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n > 1:
            sums = [float(cell[lab == k].sum()) for k in range(1, n)]
            k = 1 + int(np.argmax(sums))
            x, y, w, h = stats[k, 0], stats[k, 1], stats[k, 2], stats[k, 3]
            region = [x / S.rcols, y / S.rrows, (x + w) / S.rcols, (y + h) / S.rrows]
            rmag = float(cell[lab == k].mean())
            # direction inside the region (full-resolution vectors)
            y0, y1 = int(region[1] * S.fh), max(int(region[1] * S.fh) + 1, int(math.ceil(region[3] * S.fh)))
            x0, x1 = int(region[0] * S.fw), max(int(region[0] * S.fw) + 1, int(math.ceil(region[2] * S.fw)))
            vx, vy = rx[y0:y1, x0:x1], -ry[y0:y1, x0:x1]
            wm = mag[y0:y1, x0:x1]
            sx, sy, sw = float((vx * wm).sum()), float((vy * wm).sum()), float((wm * wm).sum())
            if sw > 1e-6:
                rdir = math.degrees(math.atan2(sy, sx)) % 360.0
                rcoh = math.hypot(sx, sy) / max(1e-6, float((wm * np.sqrt(vx * vx + vy * vy)).sum()))
    mgrid = _block_mean(magv, S.rows, S.cols).astype(np.float32)
    # the camera at the frame centre
    ccx = (a - 1.0) * S.cx - b * S.cy + tx
    ccy = b * S.cx + (a - 1.0) * S.cy + ty
    return {'cam': (ccx, ccy, math.hypot(a, b), math.degrees(math.atan2(b, a)), trust),
            'energy': energy, 'p90': p90, 'moving': moving, 'raw': raw, 'directo': directo,
            'region': region, 'rmag': rmag, 'rdir': rdir, 'rcoh': rcoh, 'mgrid': mgrid}


def still_features(y, S, st):
    """Saliency grid and luma of one frame (grey uint8 at the decoded size)."""
    import cv2
    h, w = y.shape
    sw, sh = _size_for(w, h, int(st['sal_px']))
    small = cv2.resize(y, (sw, sh), interpolation=cv2.INTER_AREA)
    ok, sal = _saliency().computeSaliency(small)
    if not ok or sal is None:
        sal = np.zeros((sh, sw), np.float32)
    sal = cv2.GaussianBlur(sal.astype(np.float32), (0, 0), max(1.0, 0.02 * max(sw, sh)))
    grid = cv2.resize(sal, (S.cols, S.rows), interpolation=cv2.INTER_AREA).astype(np.float32)
    return grid, float(y.mean()), float(y.std())


def faces_of(Y, U, V, st):
    """[[x0, y0, x1, y1, score], ...] in 0-1 of the frame (YuNet on the decoded colour frame)."""
    import cv2
    h, w = Y.shape
    det = _faces_detector(w, h, float(st['face_score']))
    if det is None:
        return None
    yuv = np.concatenate([Y.ravel(), U.ravel(), V.ravel()]).reshape(h * 3 // 2, w)
    bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
    _, found = det.detect(bgr)
    if found is None:
        return []
    out = []
    for f in found:
        x, y, fw, fh, sc = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14])
        if fw < 6 or fh < 6:
            continue
        out.append([max(0.0, x / w), max(0.0, y / h), min(1.0, (x + fw) / w), min(1.0, (y + fh) / h), sc])
    return out


# ============================================================================ per-chunk analysis

FIELDS = ('cdx', 'cdy', 'czoom', 'crot', 'trust', 'energy', 'p90', 'moving', 'raw', 'rmag', 'rdir', 'rcoh',
          'luma', 'lstd')


def _chunk_file(chunk, st):
    tag = ts._hash({'v': FEATURE_VERSION, 'st': {k: st[k] for k in FEATURE_DEFAULTS if k != 'workers'},
                    'f0': chunk['f0'], 'f1': chunk['f1'], 'off': chunk.get('offset'), 's': chunk.get('start_s')}, 12)
    safe = str(chunk['key']).replace('\\', '_').replace('/', '_').replace(':', '_')[:60]
    return FEATURES / f'{safe}-{tag}-f{FEATURE_VERSION}.npz'


def analyse_chunk(chunk, fps, st):
    """Features of the frames [f0, f1) of a chunk file. Frame index: a project chunk's file frame k is source frame
    f0 + k; a video file's frame is round(pts * fps) (+ offset when the chunk starts inside the file)."""
    import letitedit.footage.shots as shots
    t0 = time.time()
    info = shots.probe(chunk['file'])
    W, H = _size_for(info['w'], info['h'], int(st['analysis_px']))
    fw, fh = _size_for(W, H, int(st['flow_px']))
    S = _Static(fw, fh, st)
    f0, f1 = int(chunk['f0']), int(chunk['f1'])
    n = f1 - f0
    cols = {k: np.full(n, np.nan, np.float32) for k in FIELDS}
    region = np.full((n, 4), np.nan, np.float32)
    directo = np.full((n, DIRS), np.nan, np.float32)
    sgrid = np.full((n, S.rows, S.cols), np.nan, np.float16)
    mgrid = np.full((n, S.rows, S.cols), np.nan, np.float16)
    have = np.zeros(n, bool)
    faces = []           # [frame, x0, y0, x1, y1, score]
    face_frames = []
    first_g = last_g = None
    k_face = max(1, int(st['face_every']))
    face_ok = [True]
    filled = [0]
    start_s = chunk.get('start_s')
    dur = None if start_s is None else (f1 - f0 + 2) / fps
    import cv2
    workers = max(1, int(st['workers']))
    pend = []
    lock = threading.Lock()

    def job(i, prev, g, yuv, gap=1):
        out = {}
        if prev is not None:
            out['pair'] = pair_features(prev, g, S, st)
        out['still'] = still_features(yuv[0], S, st)
        if yuv[3] and face_ok[0]:
            try:
                fc = faces_of(yuv[0], yuv[1], yuv[2], st)
                if fc is None:
                    face_ok[0] = False
                out['faces'] = fc
            except Exception:  # noqa: BLE001 - no faces rather than no motion
                out['faces'] = None
        return i, out, gap

    def collect(fut):
        i, out, gap = fut.result()
        with lock:
            p = out.get('pair')
            if p is not None and gap > 1:
                # a step over a gap in the time stamps (variable frame rate): per-frame values
                k = float(gap)
                cdx, cdy, cz, cr, tr = p['cam']
                p['cam'] = (cdx / k, cdy / k, cz ** (1.0 / k), cr / k, tr)
                for key in ('energy', 'p90', 'raw', 'rmag'):
                    p[key] = p[key] / k
                p['directo'] = p['directo'] / k
                p['mgrid'] = p['mgrid'] / k
            sg, lm, ls = out['still']
            # the frames of a gap take the step measured across it
            for j in range(max(0, i - gap + 1), i + 1):
                have[j] = True
                sgrid[j] = sg
                cols['luma'][j], cols['lstd'][j] = lm, ls
                if p is not None:
                    (cols['cdx'][j], cols['cdy'][j], cols['czoom'][j], cols['crot'][j],
                     cols['trust'][j]) = p['cam']
                    for key in ('energy', 'p90', 'moving', 'raw', 'rmag', 'rdir', 'rcoh'):
                        cols[key][j] = p[key]
                    region[j] = p['region']
                    directo[j] = p['directo']
                    mgrid[j] = p['mgrid']
            if gap > 1:
                filled[0] += gap - 1
            if 'faces' in out and out['faces'] is not None:
                face_frames.append(f0 + i)
                for b in out['faces']:
                    faces.append([f0 + i] + b)
    prev = None
    last_idx = -1
    off = int(chunk.get('offset') or 0)
    t_start = float(info.get('start_time') or 0.0)
    with ThreadPoolExecutor(workers) as ex:
        for t, Y, U, V in shots.decode(chunk['file'], W, H, start_s, dur, threads=2):
            if chunk.get('project_chunk'):
                # a preview chunk: constant rate, file frame k is source frame f0 + k
                idx = last_idx + 1
            elif start_s is None:
                # a whole file: the frame grid of shots.detect (time stamp minus the stream start)
                idx = int(round((t - t_start) * fps)) + off - f0
            else:
                # a range of a file decoded from start_s: t is file time
                idx = int(round(t * fps)) - f0
            if idx < 0:
                prev = cv2.resize(Y, (fw, fh), interpolation=cv2.INTER_AREA)
                continue
            if idx >= n:
                break
            if idx <= last_idx:          # a duplicate time stamp (VFR): keep the first
                continue
            g = cv2.resize(Y, (fw, fh), interpolation=cv2.INTER_AREA)
            if first_g is None:
                first_g = (idx, g.copy())
            # faces on every k-th grid frame (or the first decoded frame after it, across a gap)
            face_now = any((f0 + j) % k_face == 0 for j in range(max(last_idx + 1, idx - 3), idx + 1))
            yuv = (Y.copy(), U.copy(), V.copy(), face_now) if face_now else (Y.copy(), None, None, False)
            gap = idx - last_idx if last_idx >= 0 else 1
            pp = prev if (prev is not None and 1 <= gap <= MAX_GAP) else None
            if pp is None:
                gap = 1
            pend.append(ex.submit(job, idx, pp, g, yuv, gap))
            if len(pend) >= 3 * workers:
                collect(pend.pop(0))
            prev = g
            last_idx = idx
            last_g = (idx, g)
        for fut in pend:
            collect(fut)
    return {'cols': cols, 'region': region, 'directo': directo, 'sgrid': sgrid, 'mgrid': mgrid, 'have': have,
            'faces': np.array(faces, np.float32).reshape(-1, 6), 'face_frames': np.array(sorted(face_frames),
                                                                                     np.int64),
            'first_g': first_g, 'last_g': last_g, 'flow_size': (fw, fh), 'size': (W, H),
            'grid': (S.rows, S.cols), 'seconds': time.time() - t0, 'faces_available': face_ok[0],
            'filled': filled[0]}


def _save_chunk(path, d):
    FEATURES.mkdir(parents=True, exist_ok=True)
    arrs = {f'c_{k}': v for k, v in d['cols'].items()}
    arrs.update(region=d['region'], directo=d['directo'], sgrid=d['sgrid'], mgrid=d['mgrid'], have=d['have'],
                faces=d['faces'], face_frames=d['face_frames'],
                meta=np.frombuffer(json.dumps({'flow_size': d['flow_size'], 'size': d['size'], 'grid': d['grid'],
                                               'seconds': d['seconds'], 'faces_available': d['faces_available'],
                                               'filled': d.get('filled', 0),
                                               'first_idx': d['first_g'][0] if d['first_g'] else None,
                                               'last_idx': d['last_g'][0] if d['last_g'] else None}).encode(),
                                   np.uint8))
    if d['first_g'] is not None:
        arrs['first_g'] = d['first_g'][1]
    if d['last_g'] is not None:
        arrs['last_g'] = d['last_g'][1]
    tmp = path.with_name(path.stem + f'.{os.getpid()}.{threading.get_ident()}.tmp.npz')
    np.savez_compressed(tmp, **arrs)
    try:
        with open(tmp, 'rb+') as fh:
            os.fsync(fh.fileno())
    except OSError:
        pass
    for _ in range(30):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.1)
    os.replace(tmp, path)


def _loads(path):
    try:
        with np.load(path, allow_pickle=False) as z:
            json.loads(bytes(z['meta']).decode())
            z['have']
        return True
    except Exception:  # noqa: BLE001 - torn or empty after a crash
        return False


def _load_chunk(path):
    with np.load(path, allow_pickle=False) as z:
        meta = json.loads(bytes(z['meta']).decode())
        d = {'cols': {k[2:]: z[k] for k in z.files if k.startswith('c_')}, 'region': z['region'],
             'directo': z['directo'], 'sgrid': z['sgrid'], 'mgrid': z['mgrid'], 'have': z['have'],
             'faces': z['faces'], 'face_frames': z['face_frames'],
             'first_g': (meta['first_idx'], z['first_g']) if 'first_g' in z.files else None,
             'last_g': (meta['last_idx'], z['last_g']) if 'last_g' in z.files else None,
             'flow_size': tuple(meta['flow_size']), 'size': tuple(meta['size']), 'grid': tuple(meta['grid']),
             'seconds': meta['seconds'], 'faces_available': meta.get('faces_available', True),
             'filled': meta.get('filled', 0)}
    return d


_LOADED = OrderedDict()        # (cache identity) -> assembled features (a few kept in memory)


def _features_lane(ctx):
    """Per-frame picture measurements (cached per chunk): dense flow with the camera's move removed, saliency,
    faces. Data for the other picture lanes; this lane itself returns only where they are."""
    import letitedit.timing.timing_render as timing_render
    st = ctx['settings']
    fps, F = float(ctx['fps']), int(ctx['frames'])
    chunks = timing_render.chunks_of(ctx)
    is_project = ctx['kind'] == 'project'
    files, reused, took = [], 0, 0.0
    filled = 0
    warnings = []
    t0 = time.time()
    for c in chunks:
        c = dict(c, project_chunk=is_project and not (ctx.get('render') or {}).get('existing'))
        p = _chunk_file(c, st)
        if p.exists() and not _loads(p):
            warnings.append(f'a cached feature file did not read back and was measured again: {p.name}')
            try:
                p.unlink()
            except OSError:
                pass
        if p.exists():
            reused += 1
        else:
            d = analyse_chunk(c, fps, st)
            _save_chunk(p, d)
            took += d['seconds']
            filled += int(d.get('filled') or 0)
            if not d['faces_available']:
                warnings.append('faces: the YuNet model is not available; attention and shot sizes go without faces')
        files.append({'f0': c['f0'], 'f1': c['f1'], 'file': str(p)})
    return {'method': 'every frame decoded once and measured against the frame before: DIS optical flow on grey '
                      'frames at flow_px, the camera move as a RANSAC similarity fitted to the flow, residual flow '
                      'statistics (energy, moving share, directogram, strongest region and its direction), '
                      'spectral-residual saliency and residual motion as coarse grids, YuNet faces every face_every '
                      'frames, luma; cached per chunk',
            'chunks': files, 'chunks_reused': reused, 'chunks_analysed': len(files) - reused,
            'analysis_seconds': round(took, 2), 'wall_seconds': round(time.time() - t0, 2),
            'frames_per_second': round(sum(c['f1'] - c['f0'] for c in chunks) / max(1e-6, took), 1) if took else None,
            'frames_filled': filled,
            'warnings': warnings + ([f'{filled} frames had no picture of their own (variable frame rate): they take '
                                     'the step measured across the gap'] if filled else []),
            'unsupported': []}


_features_lane.defaults = FEATURE_DEFAULTS


def load_features(ctx_or_lane, fps=None, frames=None):
    """The assembled per-frame features of a signals() result or a lane ctx: {'cols': {name: array[F]}, 'region'
    [F, 4], 'directo' [F, 16], 'sgrid' / 'mgrid' [F, rows, cols], 'have' [F], 'faces' [N, 6] (frame, x0, y0, x1, y1,
    score), 'face_frames', 'flow_size', 'size', 'grid'}. Boundary frame pairs between chunks are measured here."""
    if 'lanes' in ctx_or_lane and 'frame_features' in (ctx_or_lane.get('lanes') or {}):
        lane = ctx_or_lane['lanes']['frame_features']
        F = int(ctx_or_lane['frames'])
        st = lane.get('settings') or FEATURE_DEFAULTS
    else:
        lane = ctx_or_lane
        F = int(frames)
        st = lane.get('settings') or FEATURE_DEFAULTS
    if 'error' in lane:
        raise RuntimeError(f'frame features failed: {lane["error"]}')
    ident = lane.get('identity') or ts._hash(lane.get('chunks'), 12)
    key = (ident, F, tuple((c['file'] for c in lane['chunks'])))
    if key in _LOADED:
        _LOADED.move_to_end(key)
        return _LOADED[key]
    parts = [(c, _load_chunk(c['file'])) for c in lane['chunks']]
    g0 = parts[0][1]
    rows, cols_ = g0['grid']
    out = {'cols': {k: np.full(F, np.nan, np.float32) for k in FIELDS}, 'region': np.full((F, 4), np.nan, np.float32),
           'directo': np.full((F, DIRS), np.nan, np.float32), 'sgrid': np.full((F, rows, cols_), np.nan, np.float16),
           'mgrid': np.full((F, rows, cols_), np.nan, np.float16), 'have': np.zeros(F, bool),
           'flow_size': g0['flow_size'], 'size': g0['size'], 'grid': (rows, cols_),
           'faces_available': all(p[1]['faces_available'] for p in parts)}
    faces, fframes = [], []
    prev_last = None
    for c, d in parts:
        a, b = int(c['f0']), int(c['f1'])
        n = b - a
        for k in FIELDS:
            out['cols'][k][a:b] = d['cols'][k][:n]
        out['region'][a:b] = d['region'][:n]
        out['directo'][a:b] = d['directo'][:n]
        if d['sgrid'].shape[1:] == (rows, cols_):
            out['sgrid'][a:b] = d['sgrid'][:n]
            out['mgrid'][a:b] = d['mgrid'][:n]
        out['have'][a:b] = d['have'][:n]
        if len(d['faces']):
            faces.append(d['faces'])
        fframes.append(d['face_frames'])
        # the first frame of this chunk against the last of the one before
        if prev_last is not None and d['first_g'] is not None and d['first_g'][0] == 0 and prev_last[0] == a - 1:
            fw, fh = d['first_g'][1].shape[1], d['first_g'][1].shape[0]
            if prev_last[1].shape == d['first_g'][1].shape:
                S = _Static(fw, fh, st)
                p = pair_features(prev_last[1], d['first_g'][1], S, st)
                i = a
                (out['cols']['cdx'][i], out['cols']['cdy'][i], out['cols']['czoom'][i], out['cols']['crot'][i],
                 out['cols']['trust'][i]) = p['cam']
                for k in ('energy', 'p90', 'moving', 'raw', 'rmag', 'rdir', 'rcoh'):
                    out['cols'][k][i] = p[k]
                out['region'][i] = p['region']
                out['directo'][i] = p['directo']
                if p['mgrid'].shape == (rows, cols_):
                    out['mgrid'][i] = p['mgrid']
        prev_last = (d['last_g'][0] + a, d['last_g'][1]) if d['last_g'] is not None else None
    out['faces'] = np.concatenate(faces) if faces else np.zeros((0, 6), np.float32)
    out['face_frames'] = np.concatenate(fframes) if fframes else np.zeros(0, np.int64)
    _LOADED[key] = out
    while len(_LOADED) > 4:
        _LOADED.popitem(last=False)
    return out


# ============================================================================ shared: cuts and shots

def cut_mask(edit, F):
    """(is_cut_frame[F], in_transition[F], shot_id[F]): the first frame of each new shot (the step into it has no
    meaningful motion), frames inside dissolves/fades, and a shot number per frame (cuts split shots; a dissolve
    splits at its middle)."""
    cut = np.zeros(F, bool)
    trans = np.zeros(F, bool)
    shot = np.zeros(F, np.int32)
    edges = []
    for c in edit.get('cuts') or []:
        f = int(c['f'])
        if 0 <= f < F:
            cut[f] = True
            edges.append(f)
        if c.get('kind') in ('dissolve', 'fade') or (int(c.get('f1', f)) > int(c.get('f0', f))):
            a, b = max(0, int(c.get('f0', f))), min(F, int(c.get('f1', f)))
            trans[a:b] = True
    for t in edit.get('transitions') or []:
        a, b = max(0, int(t['f0'])), min(F, int(t['f1']))
        trans[a:b] = True
    edges = sorted(set(edges))
    k = 0
    for i, e in enumerate(edges):
        shot[e:] = i + 1
        k = i + 1
    return cut, trans, shot


def _lane_energy(ctx, ff, cut):
    """Motion energy as the motion lane reports it (None at cuts and where the camera move can't be separated),
    else the raw feature with cut frames removed."""
    mot = (ctx.get('lanes') or {}).get('motion')
    if mot and mot.get('energy') is not None and not mot.get('error'):
        return np.array([np.nan if v is None else float(v) for v in mot['energy']], dtype=np.float64)
    return np.where(cut, np.nan, ff['cols']['energy'].astype(np.float64))


def _smooth(x, n):
    """Centred moving mean over n frames that ignores NaN (a series shorter than n: its own length, so a shot of
    a few frames keeps its size)."""
    x = np.asarray(x, dtype=np.float64)
    n = min(int(n), len(x))
    if n <= 1:
        return x.copy()
    v = np.where(np.isfinite(x), x, 0.0)
    w = np.isfinite(x).astype(np.float64)
    k = np.ones(int(n))
    num = np.convolve(v, k, mode='same')
    den = np.convolve(w, k, mode='same')
    with np.errstate(invalid='ignore', divide='ignore'):
        return np.where(den > 0, num / np.maximum(den, 1e-9), np.nan)


def _per_shot(fn, x, shot, *args):
    """fn applied to x within each shot (no smoothing across cuts)."""
    out = np.full(len(x), np.nan)
    for s in np.unique(shot):
        idx = np.flatnonzero(shot == s)
        if idx.size:
            out[idx] = fn(x[idx], *args)
    return out


def _runs(labels):
    out, i = [], 0
    n = len(labels)
    while i < n:
        j = i
        while j + 1 < n and labels[j + 1] == labels[i]:
            j += 1
        out.append([i, j + 1, labels[i]])
        i = j + 1
    return out


# ============================================================================ motion

MOTION_DEFAULTS = {
    'smooth_s': 0.3,            # camera speed is judged on this centred mean (within a shot)
    'whip_smooth_s': 0.13,      # ... whips on this shorter one (they are fast and short)
    'unreliable_speed': 0.45,   # camera faster than this (frame widths/s) with an untrusted fit: the subject motion
                                # can't be separated from it (motion blur); energy there is None (unmeasured)
    'jitter_s': 0.5,            # shake: spread of the frame-to-frame camera motion around that mean over this
    'whip_speed': 0.9,          # camera speed (whip window) at least this: whip (frame widths per second)
    'zoom_rate': 0.04,          # |log zoom| per second at least this ...
    'zoom_dominance': 1.2,      # ... and the zoom's motion at the frame corners >= this x the camera speed: zoom
    'pan_speed': 0.25,          # camera speed at least this ...
    'pan_shake_ratio': 0.5,     # ... with shake under this x the speed (a steady move): pan (sideways) / tilt
    'steady_pan_speed': 0.12,   # a slower move is a pan / tilt too when it is steady: speed at least this ...
    'steady_max_jitter': 0.01,  # ... and shake under this (a tripod or gimbal move, not a hand)
    'handheld_speed': 0.08,     # otherwise a camera drifting at least this ...
    'handheld_jitter': 0.03,    # ... or shaking at least this (frame widths per second): handheld; else static
    'min_label_s': 0.3,         # shorter label runs merge into their neighbours
    'min_trust': 0.25,          # camera estimates with fewer agreeing flow samples are marked untrusted
    'direction_min_energy': 1.0,  # direction only where the region moves at least this (px/frame) ...
    'direction_min_coherence': 0.5,  # ... and its vectors agree this much (0-1)
}


def camera_labels(dx, dy, zoom, shot, fps, flow_w, aspect, st):
    """Per-frame camera labels from the camera's per-frame move (dx, dy px/frame of the picture centre at a flow
    width of flow_w; zoom scale per frame), judged within shots. Returns (labels, measures) with measures speed
    (frame widths/s on a smooth_s centred mean), speed_w (on whip_smooth_s), jitter (shake: RMS of the per-frame
    move around that mean over jitter_s), sx, sy (mean velocity), sz (log zoom per second).
    Rules in order: whip (speed_w >= whip_speed); zoom (|sz| >= zoom_rate and the zoom's motion at the frame corners
    >= zoom_dominance x speed); pan / tilt (speed >= pan_speed and jitter <= pan_shake_ratio x speed, or a steady
    slower move: speed >= steady_pan_speed and jitter < steady_max_jitter; pan when sideways dominates); handheld (speed >= handheld_speed or jitter >= handheld_jitter); else static. Runs shorter
    than min_label_s merge into a neighbour."""
    F = len(dx)
    n_s = max(1, int(round(float(st['smooth_s']) * fps)))
    n_j = max(1, int(round(float(st['jitter_s']) * fps)))
    n_w = max(1, int(round(float(st['whip_smooth_s']) * fps)))
    vx = dx / flow_w * fps
    vy = dy / flow_w * fps
    lz = np.log(np.clip(np.nan_to_num(zoom, nan=1.0), 0.5, 2.0)) * fps
    lz = np.where(np.isfinite(zoom), lz, np.nan)
    sx = _per_shot(_smooth, vx, shot, n_s)
    sy = _per_shot(_smooth, vy, shot, n_s)
    sz = _per_shot(_smooth, lz, shot, n_s)
    speed_w = np.hypot(_per_shot(_smooth, vx, shot, n_w), _per_shot(_smooth, vy, shot, n_w))
    jx, jy = vx - sx, vy - sy
    jit = np.sqrt(_per_shot(_smooth, jx * jx + jy * jy, shot, n_j))
    speed = np.hypot(sx, sy)
    # the zoom's motion at the frame corners, in frame widths per second
    half_diag = 0.5 * math.sqrt(1.0 + (1.0 / max(1e-6, aspect)) ** 2)
    labels = []
    for i in range(F):
        if not np.isfinite(speed[i]):
            labels.append(None)
            continue
        s = speed[i]
        z = abs(sz[i]) if np.isfinite(sz[i]) else 0.0
        j = jit[i] if np.isfinite(jit[i]) else 0.0
        if np.isfinite(speed_w[i]) and speed_w[i] >= float(st['whip_speed']):
            lab = 'whip'
        elif z >= float(st['zoom_rate']) and z * half_diag >= float(st['zoom_dominance']) * s:
            lab = 'zoom'
        elif (s >= float(st['pan_speed']) and j <= float(st['pan_shake_ratio']) * s) or                 (s >= float(st['steady_pan_speed']) and j < float(st['steady_max_jitter'])):
            lab = 'pan' if abs(sx[i]) >= abs(sy[i]) else 'tilt'
        elif s >= float(st['handheld_speed']) or j >= float(st['handheld_jitter']):
            lab = 'handheld'
        else:
            lab = 'static'
        labels.append(lab)
    min_n = max(1, int(round(float(st['min_label_s']) * fps)))
    for _ in range(2):
        runs = _runs(list(zip(labels, shot.tolist())))
        for k, (a, b, (lab, sh)) in enumerate(runs):
            if lab is None or b - a >= min_n:
                continue
            prev = runs[k - 1] if k > 0 and runs[k - 1][2][1] == sh and runs[k - 1][2][0] else None
            nxt = runs[k + 1] if k + 1 < len(runs) and runs[k + 1][2][1] == sh and runs[k + 1][2][0] else None
            if prev and nxt:
                pick = prev if (prev[1] - prev[0]) >= (nxt[1] - nxt[0]) else nxt
            else:
                pick = prev or nxt
            if pick:
                for i in range(a, b):
                    labels[i] = pick[2][0]
    return labels, {'speed': speed, 'speed_w': speed_w, 'jitter': jit, 'sx': sx, 'sy': sy, 'sz': sz}


def _motion_lane(ctx):
    """Per frame: motion energy with the camera's own move removed (px/frame at the flow size), the camera's move
    {dx, dy (px/frame of the picture centre at the flow size), zoom (scale per frame), rot (degrees per frame)},
    a camera label (static | pan | tilt | zoom | handheld | whip), the dominant direction of subject motion and the
    box of the strongest moving region."""
    st = ctx['settings']
    fps, F = float(ctx['fps']), int(ctx['frames'])
    ff = load_features(ctx)
    c = ff['cols']
    fw, fh = ff['flow_size']
    edit = ctx['lanes'].get('edit') or {}
    cut, trans, shot = cut_mask(edit, F)
    bad = cut | ~np.isfinite(c['energy'])
    energy = np.where(bad, np.nan, c['energy'])
    dx = np.where(bad, np.nan, c['cdx'])
    dy = np.where(bad, np.nan, c['cdy'])
    zoom = np.where(bad, np.nan, c['czoom'])
    rot = np.where(bad, np.nan, c['crot'])
    trust = np.where(bad, np.nan, c['trust'])
    W0, H0 = ff['size']
    labels, cam = camera_labels(dx, dy, zoom, shot, fps, fw, W0 / float(H0), st)
    speed, speed_w, jit, sx, sy, sz = (cam[k] for k in ('speed', 'speed_w', 'jitter', 'sx', 'sy', 'sz'))
    # subject motion can't be told from a fast camera move the fit doesn't trust (blur): unmeasured
    unreliable = (np.nan_to_num(trust, nan=1.0) < float(st['min_trust'])) & \
        (np.nan_to_num(speed_w, nan=0.0) >= float(st['unreliable_speed']))
    energy = np.where(unreliable, np.nan, energy)
    region = []
    direction = []
    bad = bad | unreliable
    for i in range(F):
        r = ff['region'][i]
        if bad[i] or not np.all(np.isfinite(r)):
            region.append(None)
        else:
            region.append([round(float(v), 3) for v in r])
        d = c['rdir'][i]
        if (not bad[i] and np.isfinite(d) and np.isfinite(c['rmag'][i])
                and c['rmag'][i] >= float(st['direction_min_energy'])
                and np.isfinite(c['rcoh'][i]) and c['rcoh'][i] >= float(st['direction_min_coherence'])):
            direction.append(round(float(d), 1))
        else:
            direction.append(None)
    camera_moves = []
    for a, b, (lab, sh) in _runs(list(zip(labels, shot.tolist()))):
        if lab is None:
            continue
        seg = slice(a, b)
        camera_moves.append({'f0': a, 'f1': b, 't0': ts.tsec(a, fps), 't1': ts.tsec(b, fps), 'label': lab,
                             'speed_fw_s': ts.clean(float(np.nanmean(speed[seg])), 3),
                             'dx_fw_s': ts.clean(float(np.nanmean(sx[seg])), 3),
                             'dy_fw_s': ts.clean(float(np.nanmean(sy[seg])), 3),
                             'zoom_per_s': ts.clean(float(np.nanmean(sz[seg])), 3),
                             'jitter_fw_s': ts.clean(float(np.nanmean(jit[seg])), 3)})
    untrusted = int(np.nansum(trust < float(st['min_trust'])))
    unmeasured = [{'f0': a, 'f1': b, 't0': ts.tsec(a, fps), 't1': ts.tsec(b, fps),
                   'why': 'fast camera move the flow fit does not trust (motion blur): subject motion not separable'}
                  for a, b, v in _runs(unreliable.tolist()) if v]
    return {'method': 'dense optical flow (OpenCV DIS) with the camera\'s move (a RANSAC similarity fitted to the '
                      'flow) removed; energy = mean residual flow magnitude; camera speed in frame widths per second '
                      'on a centred mean within each shot; handheld = spread of the frame-to-frame camera motion',
            'units': {'energy': f'px/frame at {fw}x{fh} (the flow size)', 'camera.dx/dy': f'px/frame of the picture '
                      f'centre at {fw}x{fh}', 'camera.zoom': 'scale per frame (1 = none, >1 zooms in)',
                      'camera.rot': 'degrees per frame', 'camera_speed': 'frame widths per second',
                      'direction': 'degrees, 0 = right, 90 = up', 'region': '[x0, y0, x1, y1] 0-1'},
            'flow_size': [fw, fh],
            'energy': ts.series(energy, 3), 'camera': {'dx': ts.series(dx, 3), 'dy': ts.series(dy, 3),
                                                        'zoom': ts.series(zoom, 5), 'rot': ts.series(rot, 4)},
            'camera_label': labels, 'camera_speed': ts.series(speed, 3), 'camera_jitter': ts.series(jit, 3),
            'camera_trust': ts.series(trust, 3), 'direction': direction, 'region': region,
            'moving_share': ts.series(np.where(bad, np.nan, c['moving']), 3),
            'energy_p90': ts.series(np.where(bad, np.nan, c['p90']), 3),
            'raw_energy': ts.series(np.where(bad, np.nan, c['raw']), 3),
            'in_transition': [int(i) for i in np.flatnonzero(trans)],
            'unmeasured': unmeasured,
            'camera_moves': camera_moves,
            'warnings': ([f'{untrusted} frames where fewer than {st["min_trust"]:.0%} of the flow agreed on one '
                          'camera move (a close subject filling the frame or a featureless picture): their camera '
                          'values and labels are uncertain'] if untrusted > 0.2 * F else []),
            'unsupported': ['a subject that fills most of the frame and moves as one is taken for the camera',
                            'the camera moving forward (dolly) reads as a zoom; parallax is not separated from '
                            'subject motion', 'motion under heavy blur or in very dark frames is underestimated']}


_motion_lane.defaults = MOTION_DEFAULTS


# ============================================================================ visual beats

BEATS_DEFAULTS = {
    'smooth_frames': 2,         # the impact envelope is smoothed over this many frames
    'scale_s': 3.0,             # ... and divided by its 90th percentile within +-this (local scale)
    'min_strength': 0.6,        # a beat's envelope peak, relative to that scale, at least this
    'min_abs': 0.02,            # ... and its absolute drop at least this (px/frame summed over directions)
    'min_gap_s': 0.18,          # beats closer than this: the stronger is kept
    'min_speed_before': 0.5,    # motion before the drop (the most within stop_s, px/frame) at least this: a stop
                                # needs a movement to stop (still pictures make no beats)
    'stop_s': 0.35,             # the frame motion comes to rest: the local minimum of speed within this after
    'edge_frames': 2,           # no beats this close to a cut or inside a transition
}


def _visual_beats_lane(ctx):
    """Visual beats (Davis & Agrawala 2018): peaks of the impact envelope u(f) = sum over 16 screen directions of
    the drop in residual motion from frame f-1 to f (sharp decelerations), within shots."""
    st = ctx['settings']
    fps, F = float(ctx['fps']), int(ctx['frames'])
    ff = load_features(ctx)
    edit = ctx['lanes'].get('edit') or {}
    cut, trans, shot = cut_mask(edit, F)
    D = ff['directo'].astype(np.float64)
    u = np.full(F, np.nan)
    prevD = np.vstack([np.full((1, DIRS), np.nan), D[:-1]])
    drop = np.clip(prevD - D, 0, None).sum(axis=1)
    ok = np.isfinite(D).all(axis=1) & np.isfinite(prevD).all(axis=1)
    edge = int(st['edge_frames'])
    blocked = trans.copy()
    for f in np.flatnonzero(cut):
        blocked[max(0, f - edge):min(F, f + edge + 1)] = True
    energy = _lane_energy(ctx, ff, cut)
    # frames whose motion is unmeasured (a cut, a fast camera move the fit doesn't trust) and the frame after them
    # carry no beat
    unm = ~np.isfinite(energy)
    blocked = blocked | unm | np.r_[False, unm[:-1]]
    u[ok] = drop[ok]
    u[blocked] = np.nan
    us = _per_shot(_smooth, u, shot, int(st['smooth_frames']))
    es = _per_shot(_smooth, energy, shot, max(1, int(round(0.1 * fps))))
    W = max(3, int(round(float(st['scale_s']) * fps)))
    beats = []
    vals = np.nan_to_num(us, nan=0.0)
    for i in range(1, F - 1):
        if not np.isfinite(us[i]) or blocked[i]:
            continue
        if not (vals[i] >= vals[i - 1] and vals[i] > vals[i + 1]):
            continue
        lo, hi = max(0, i - W), min(F, i + W + 1)
        loc = us[lo:hi]
        loc = loc[np.isfinite(loc)]
        scale = float(np.percentile(loc, 90)) if loc.size >= 5 else float('nan')
        if not np.isfinite(scale) or scale <= 1e-6:
            continue
        rel = vals[i] / scale
        if rel < float(st['min_strength']) or vals[i] < float(st['min_abs']):
            continue
        k = int(round(float(st['stop_s']) * fps))
        seg = es[i:min(F, i + k + 1)]
        same = shot[i:min(F, i + k + 1)] == shot[i]
        seg = np.where(same, seg, np.nan)
        j = i + int(np.nanargmin(seg)) if np.isfinite(seg).any() else i
        before = es[max(0, i - k):i]
        before = before[np.isfinite(before)]
        if not before.size or float(before.max()) < float(st['min_speed_before']):
            continue
        beats.append({'f': i, 't': ts.tsec(i, fps), 'strength': round(float(rel), 3),
                      'drop': round(float(vals[i]), 4), 'f_stop': int(j), 't_stop': ts.tsec(j, fps),
                      'speed_before': ts.clean(float(before.max()) if before.size else None, 3),
                      'speed_after': ts.clean(float(es[j]) if np.isfinite(es[j]) else None, 3)})
    # one beat per min_gap: the stronger
    gap = max(1, int(round(float(st['min_gap_s']) * fps)))
    kept = []
    for b in sorted(beats, key=lambda b: -b['strength']):
        if all(abs(b['f'] - k['f']) >= gap for k in kept):
            kept.append(b)
    kept.sort(key=lambda b: b['f'])
    return {'method': 'Davis & Agrawala 2018 (Visual Rhythm and Beat): directogram of the residual flow (camera '
                      'removed) in 16 directions; impact envelope = summed drop from each frame to the next; beats '
                      'are its local peaks above min_strength x its local 90th percentile (within scale_s) and '
                      'min_abs; f_stop = where motion speed reaches its local minimum after the peak',
            'beats': kept, 'envelope': ts.series(us, 4),
            'units': {'strength': 'envelope peak / local 90th percentile', 'drop': 'px/frame summed over directions',
                      'speed': 'px/frame at the flow size'},
            'warnings': [], 'unsupported': ['beats are motion decelerations, not their meaning: a hand stopping and '
                                            'a shaky camera settling look alike when the camera fit fails']}


_visual_beats_lane.defaults = BEATS_DEFAULTS


# ============================================================================ motion events

EVENTS_DEFAULTS = {
    'signal': 'energy',         # what rises: energy (frame mean), p90 (90th percentile) or rmag (the strongest region)
    'smooth_s': 0.1,            # energy smoothed over this (centred mean, within a shot)
    'rest_pct': 20,             # the shot's resting level: this percentile of its energy
    'rise_px': 0.5,             # an event rises at least this above the resting level (px/frame) ...
    'rise_mad': 3.0,            # ... and this many MADs of the shot's energy
    'min_peak_px': 0.6,         # ... and peaks at least this
    'edge_share': 0.25,         # onset/end: where it falls back under rest + this share of the rise
    'min_s': 0.12,              # events shorter than this are dropped
    'merge_s': 0.2,             # events closer than this merge
}


def _motion_events_lane(ctx):
    """Bursts of subject motion (camera removed): onset, peak and end where the smoothed energy rises above the
    shot's resting level by a margin and falls back."""
    st = ctx['settings']
    fps, F = float(ctx['fps']), int(ctx['frames'])
    ff = load_features(ctx)
    edit = ctx['lanes'].get('edit') or {}
    cut, trans, shot = cut_mask(edit, F)
    e = _lane_energy(ctx, ff, cut)
    sig_name = str(st.get('signal') or 'energy')
    if sig_name in ('p90', 'rmag'):
        alt = ff['cols'][sig_name].astype(np.float64)
        if sig_name == 'rmag':
            alt = np.where(np.isfinite(alt), alt, 0.0)
        e = np.where(np.isfinite(e), alt, np.nan)
    es = _per_shot(_smooth, e, shot, max(1, int(round(float(st['smooth_s']) * fps))))
    region = ff['region']
    events = []
    for s in np.unique(shot):
        idx = np.flatnonzero(shot == s)
        x = es[idx]
        fin = np.isfinite(x)
        if fin.sum() < 3:
            continue
        rest = float(np.percentile(x[fin], float(st['rest_pct'])))
        mad = float(np.median(np.abs(x[fin] - np.median(x[fin])))) + 1e-6
        hi = rest + max(float(st['rise_px']), float(st['rise_mad']) * mad)
        above = fin & (x >= hi) & (x >= float(st['min_peak_px']))
        i = 0
        n = len(idx)
        while i < n:
            if not above[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and above[j + 1]:
                j += 1
            pk = i + int(np.nanargmax(x[i:j + 1]))
            peak = float(x[pk])
            lo_thr = rest + float(st['edge_share']) * (peak - rest)
            a = i
            while a - 1 >= 0 and np.isfinite(x[a - 1]) and x[a - 1] > lo_thr:
                a -= 1
            b = j
            while b + 1 < n and np.isfinite(x[b + 1]) and x[b + 1] > lo_thr:
                b += 1
            events.append([int(idx[a]), int(idx[pk]), int(idx[b]) + 1, peak, rest, int(s)])
            i = b + 1
    # merge close ones (same shot)
    events.sort()
    merged = []
    gap = int(round(float(st['merge_s']) * fps))
    for ev in events:
        if merged and ev[5] == merged[-1][5] and ev[0] - merged[-1][2] <= gap:
            m = merged[-1]
            if ev[3] > m[3]:
                m[1], m[3] = ev[1], ev[3]
            m[2] = max(m[2], ev[2])
            continue
        merged.append(list(ev))
    out = []
    min_n = max(1, int(round(float(st['min_s']) * fps)))
    for a, pk, b, peak, rest, s in merged:
        if b - a < min_n:
            continue
        boxes = [region[k] for k in range(max(a, pk - 2), min(b, pk + 3)) if np.all(np.isfinite(region[k]))]
        box = [round(float(v), 3) for v in np.median(np.array(boxes), axis=0)] if boxes else None
        dirs = [ff['cols']['rdir'][k] for k in range(max(a, pk - 2), min(b, pk + 3))
                if np.isfinite(ff['cols']['rdir'][k]) and np.isfinite(ff['cols']['rcoh'][k])
                and ff['cols']['rcoh'][k] >= 0.35]
        if dirs:
            ang = np.radians(dirs)
            dirn = round(float(np.degrees(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())) % 360.0), 1)
        else:
            dirn = None
        out.append({'f0': a, 'f_peak': pk, 'f1': b, 't0': ts.tsec(a, fps), 't_peak': ts.tsec(pk, fps),
                    't1': ts.tsec(b, fps), 'strength': round(peak - rest, 3), 'peak_energy': round(peak, 3),
                    'rest_energy': round(rest, 3), 'region': box, 'direction': dirn,
                    'duration_s': round((b - a) / fps, 3)})
    return {'method': 'smoothed motion energy (camera removed) per shot; an event = a stretch above the shot\'s '
                      'resting level (rest_pct percentile) + max(rise_px, rise_mad x MAD) and min_peak_px; onset/end '
                      'where it falls back under rest + edge_share x the rise; close events merged',
            'events': out, 'units': {'strength': 'peak minus resting energy, px/frame at the flow size'},
            'warnings': [], 'unsupported': ['an event is a burst of movement, not an action: a hand reaching and a '
                                            'person walking past look alike (the meaning lane names them)',
                                            'slow continuous movement without a burst is not an event']}


_motion_events_lane.defaults = EVENTS_DEFAULTS


# ============================================================================ attention

ATTENTION_DEFAULTS = {
    'w_saliency': 1.0,          # weight of still-image saliency (normalised to its frame maximum)
    'w_faces': 2.0,             # weight of faces (a blob per face, by its size and score)
    'w_motion': 1.5,            # weight of residual motion (normalised by motion_norm_px)
    'w_center': 0.35,           # weight of the centre bias (viewers look near the middle)
    'motion_norm_px': 2.0,      # residual motion this strong counts fully (px/frame)
    'face_hold_frames': 6,      # faces carry over to frames up to this far from a detection (within the shot)
    'sharpen': 2.0,             # the map is raised to this power before its centre is taken
}


def _attention_lane(ctx):
    """Where the eye is likely to go, per frame: a map of still-image saliency (spectral residual), faces and
    residual motion with a centre bias; its weighted centre {x, y} (0-1) and spread (share of the frame diagonal)."""
    st = ctx['settings']
    fps, F = float(ctx['fps']), int(ctx['frames'])
    ff = load_features(ctx)
    edit = ctx['lanes'].get('edit') or {}
    cut, trans, shot = cut_mask(edit, F)
    rows, cols = ff['grid']
    yy, xx = np.mgrid[0:rows, 0:cols]
    cxg, cyg = (xx + 0.5) / cols, (yy + 0.5) / rows
    center = np.exp(-(((cxg - 0.5) ** 2) / (2 * 0.22 ** 2) + ((cyg - 0.5) ** 2) / (2 * 0.22 ** 2)))
    W, H = ff['size']
    aspect = W / float(H)
    # faces by frame
    faces_by = {}
    for row in ff['faces']:
        faces_by.setdefault(int(row[0]), []).append([float(v) for v in row[1:]])
    checked = sorted(set(int(x) for x in ff['face_frames']))
    hold = int(st['face_hold_frames'])
    xs, ys, sp = np.full(F, np.nan), np.full(F, np.nan), np.full(F, np.nan)
    j = 0
    for f in range(F):
        if not ff['have'][f]:
            continue
        sal = ff['sgrid'][f].astype(np.float64)
        sal = np.nan_to_num(sal)
        if sal.max() > 0:
            sal = sal / sal.max()
        mot = np.nan_to_num(ff['mgrid'][f].astype(np.float64)) / float(st['motion_norm_px'])
        mot = np.clip(mot, 0, 1)
        if cut[f]:
            mot[:] = 0
        # nearest face detection within hold frames, same shot
        while j + 1 < len(checked) and checked[j + 1] <= f:
            j += 1
        fb = None
        best = None
        for k in (j, j + 1):
            if 0 <= k < len(checked) and abs(checked[k] - f) <= hold and shot[checked[k]] == shot[f]:
                if best is None or abs(checked[k] - f) < abs(best - f):
                    best = checked[k]
        if best is not None:
            fb = faces_by.get(best, [])
        fmap = np.zeros((rows, cols))
        for b in fb or []:
            x0, y0, x1, y1, sc = b
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2 - 0.1 * (y1 - y0)
            sx_, sy_ = max(0.03, (x1 - x0) * 0.6), max(0.03, (y1 - y0) * 0.6)
            area = (x1 - x0) * (y1 - y0)
            fmap += sc * min(1.0, 0.4 + 8 * area) * np.exp(-(((cxg - mx) ** 2) / (2 * sx_ ** 2)
                                                            + ((cyg - my) ** 2) / (2 * sy_ ** 2)))
        m = (float(st['w_saliency']) * sal + float(st['w_faces']) * fmap + float(st['w_motion']) * mot
             + float(st['w_center']) * center)
        m = np.clip(m, 0, None) ** float(st['sharpen'])
        tot = m.sum()
        if tot <= 0:
            continue
        x = float((m * cxg).sum() / tot)
        y = float((m * cyg).sum() / tot)
        var = float((m * (((cxg - x) * aspect) ** 2 + (cyg - y) ** 2)).sum() / tot)
        xs[f], ys[f] = x, y
        sp[f] = math.sqrt(var) / math.sqrt(aspect ** 2 + 1)
    faces =[{'f': int(f), 't': ts.tsec(int(f), fps), 'boxes': [[round(v, 3) for v in b] for b in faces_by.get(f, [])]}
             for f in checked]
    return {'method': 'per frame: spectral-residual saliency (OpenCV) normalised to its maximum x w_saliency + '
                      'faces (YuNet, a Gaussian per face by size and score; nearest detection within '
                      'face_hold_frames in the same shot) x w_faces + residual motion (camera removed) / '
                      'motion_norm_px x w_motion + a centre bias x w_center, raised to `sharpen`; x, y = its weighted '
                      'centre, spread = its weighted spread / frame diagonal',
            'every': 1, 'x': ts.series(xs, 3), 'y': ts.series(ys, 3), 'spread': ts.series(sp, 3),
            'faces': faces, 'face_every': int((ctx.get('lanes', {}).get('frame_features') or {}).get('settings', {})
                                              .get('face_every', 3)),
            'faces_available': bool(ff.get('faces_available', True)),
            'units': {'x': '0-1 of the width', 'y': '0-1 of the height', 'spread': 'share of the frame diagonal'},
            'warnings': [] if ff.get('faces_available', True) else ['no face model: attention without faces'],
            'unsupported': ['a still-image saliency model plus faces and motion, not measured gaze: text, '
                            'gestures and what the speaker talks about are not modelled (Tangemann et al.: '
                            'still-image models explain only part of gaze in video)',
                            'no eye-tracking data was available to calibrate the weights']}


_attention_lane.defaults = ATTENTION_DEFAULTS


# ============================================================================ shots

SHOTS_DEFAULTS = {
    'closeup_face': 0.25,       # median face height / the frame's shorter side at least this: closeup
    'medium_face': 0.10,        # ... at least this: medium; under: wide
    'min_face_share': 0.3,      # a face in at least this share of the shot's checked frames, else unknown
    'black_luma': 18.0,         # mean luma under this and spread under black_std: a black frame
    'black_std': 6.0,
}


def _shots_lane(ctx):
    """The shots between cuts: how each begins (start / cut / dissolve / fade) and its size from the median height
    of its largest face relative to the frame's shorter side (closeup / medium / wide; unknown without a face)."""
    st = ctx['settings']
    fps, F = float(ctx['fps']), int(ctx['frames'])
    ff = load_features(ctx)
    edit = ctx['lanes'].get('edit') or {}
    meaning = (ctx['lanes'] or {}).get('meaning')
    W, H = ff['size']
    short = min(W, H)
    cuts = sorted(edit.get('cuts') or [], key=lambda c: c['f'])
    edges = [0] + [int(c['f']) for c in cuts if 0 < int(c['f']) < F] + [F]
    kinds = {int(c['f']): c.get('kind', 'cut') for c in cuts}
    pics = edit.get('pictures') or []
    faces_by = {}
    for row in ff['faces']:
        faces_by.setdefault(int(row[0]), []).append(row[1:])
    checked = np.array(sorted(set(int(x) for x in ff['face_frames'])), np.int64)
    out = []
    luma, lstd = ff['cols']['luma'], ff['cols']['lstd']
    for a, b in zip(edges, edges[1:]):
        if b <= a:
            continue
        rec = {'f0': a, 'f1': b, 't0': ts.tsec(a, fps), 't1': ts.tsec(b, fps), 'seconds': round((b - a) / fps, 3),
               'kind_in': 'start' if a == 0 else kinds.get(a, 'cut')}
        pic = next((p for p in pics if p['f0'] <= a < p['f1']), None)
        if pic is not None:
            rec['item'] = pic.get('item')
            rec['clip'] = pic.get('clip')
            if pic.get('item') is None:
                rec['black'] = True
        lm = luma[a:b]
        lsd = lstd[a:b]
        if np.isfinite(lm).any() and np.nanmedian(lm) < float(st['black_luma']) and \
                np.nanmedian(lsd) < float(st['black_std']):
            rec['black'] = True
        inside = checked[(checked >= a) & (checked < b)]
        heights = []
        for f in inside:
            bs = faces_by.get(int(f), [])
            if bs:
                big = max(bs, key=lambda q: (q[3] - q[1]))
                heights.append((big[3] - big[1]) * H / short)
        share = len(heights) / max(1, len(inside))
        rec['faces_checked'] = int(len(inside))
        rec['face_share'] = round(share, 3)
        size, basis = 'unknown', ''
        if rec.get('black'):
            basis = 'black frames'
        elif len(inside) == 0:
            basis = 'no frame checked for faces (shot shorter than the face step)'
        elif share >= float(st['min_face_share']) and heights:
            fh = float(np.median(heights))
            rec['face_height'] = round(fh, 3)
            size = ('closeup' if fh >= float(st['closeup_face']) else 'medium' if fh >= float(st['medium_face'])
                    else 'wide')
            basis = (f'largest face {fh:.2f} of the shorter side (median of {len(heights)} frames; closeup >= '
                     f'{st["closeup_face"]}, medium >= {st["medium_face"]})')
        else:
            basis = f'a face in {share:.0%} of {len(inside)} checked frames (needs {st["min_face_share"]:.0%})'
        if size == 'unknown' and meaning and isinstance(meaning, dict):
            for m in meaning.get('labels') or meaning.get('items') or []:
                if not isinstance(m, dict):
                    continue
                if m.get('f0', -1) <= a and m.get('f1', -1) >= b - 1:
                    lab = str(m.get('label', '')).lower()
                    for w in ('closeup', 'close-up', 'close up', 'medium', 'wide'):
                        if w in lab:
                            size = 'closeup' if w.startswith('close') else w
                            basis = f'meaning lane: {m.get("label")} ({m.get("accuracy_basis", "")})'
                            break
        rec['size'] = size
        rec['size_basis'] = basis
        out.append(rec)
    return {'method': 'shots between the cuts of the edit lane; size from the median height of the largest YuNet '
                      'face relative to the frame\'s shorter side, else the meaning lane\'s label, else unknown',
            'shots': out, 'warnings': [],
            'unsupported': ['shot size without a face (objects, hands, landscapes) is unknown unless the meaning lane '
                            'labels it', 'a face on a screen or a photo counts as a face']}


_shots_lane.defaults = SHOTS_DEFAULTS


# ============================================================================ registration

ts.register_lane('frame_features', _features_lane, depends=(), version=FEATURE_VERSION)
ts.register_lane('motion', _motion_lane, depends=('edit', 'frame_features'), version=1)
ts.register_lane('visual_beats', _visual_beats_lane, depends=('edit', 'frame_features', 'motion'), version=2)
ts.register_lane('motion_events', _motion_events_lane, depends=('edit', 'frame_features', 'motion'), version=2)
ts.register_lane('attention', _attention_lane, depends=('edit', 'frame_features'), version=1)
ts.register_lane('shots', _shots_lane, depends=('edit', 'frame_features'), optional=('meaning',), version=1)
