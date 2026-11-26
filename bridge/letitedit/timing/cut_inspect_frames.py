"""The per-frame analysis, the action phase and a detected cut snapped to its frame.

Part of `cut_inspect` (letitedit/timing/cut_inspect.py), which imports every name here back,
so `cut_inspect.X` is the same object it always was.
"""
from __future__ import annotations
import math
import numpy as np
from letitedit.timing.cut_inspect_base import (  # noqa: E402
    _cv2, _dis, _face_detector, _r, _saliency_obj, _settings, _sizes, faces_available, thresholds
)


# ------------------------------------------------------------------ per-frame analysis

_GRIDS = {}


def _grid(shape):
    g = _GRIDS.get(shape)
    if g is None:
        H, W = shape
        X, Y = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
        step = max(4, W // 32)
        ys, xs = np.mgrid[step // 2:H:step, step // 2:W:step]
        src = np.stack([xs.ravel(), ys.ravel()], 1).astype(np.float32)
        cx, cy = (W - 1) / 2.0, (H - 1) / 2.0
        prior = np.exp(-(((X - cx) / (0.30 * W)) ** 2 + ((Y - cy) / (0.30 * H)) ** 2) / 2.0).astype(np.float32)
        tx = np.clip(np.minimum(X, W - 1 - X) / (0.06 * W), 0.0, 1.0)
        ty = np.clip(np.minimum(Y, H - 1 - Y) / (0.06 * H), 0.0, 1.0)
        g = _GRIDS[shape] = {'X': X, 'Y': Y, 'ys': ys.ravel(), 'xs': xs.ravel(), 'src': src, 'prior': prior,
                             'taper': (tx * ty).astype(np.float32)}
    return g


def _flow_step(g0, g1, fps, thr):
    """Motion between two consecutive frames of one shot (grey, flow size) with the camera's own move removed: a
    homography fitted to the flow with RANSAC (a similarity when that fails). What remains is subject motion plus
    the parallax of a camera moving through a deep scene (they cannot be told apart reliably from two frames:
    'share', the part of the frame that moves, says which is likelier)."""
    cv2 = _cv2()
    H, W = g0.shape
    G = _grid((H, W))
    flow = _dis().calc(g0, g1, None)
    dst = G['src'] + flow[G['ys'], G['xs']]
    X, Y = G['X'], G['Y']
    Hm, inl = cv2.findHomography(G['src'], dst, cv2.RANSAC, 1.0, maxIters=400, confidence=0.99)
    cxp, cyp = (W - 1) / 2.0, (H - 1) / 2.0
    if Hm is not None and np.isfinite(Hm).all() and abs(float(Hm[2, 2])) > 1e-9:
        Hm = Hm / Hm[2, 2]
        den = Hm[2, 0] * X + Hm[2, 1] * Y + Hm[2, 2]
        den = np.where(np.abs(den) < 1e-6, 1e-6, den)
        cu = (Hm[0, 0] * X + Hm[0, 1] * Y + Hm[0, 2]) / den - X
        cv_ = (Hm[1, 0] * X + Hm[1, 1] * Y + Hm[1, 2]) / den - Y
        lim = 0.5 * max(W, H)                  # a degenerate fit (the field flies off somewhere): use the similarity
        if not (np.isfinite(cu).all() and np.isfinite(cv_).all()) or float(np.abs(cu).max()) > lim or \
                float(np.abs(cv_).max()) > lim or float(den.min()) <= 0.0:
            Hm = None
    if Hm is not None:
        inl_share = float(inl.mean()) if inl is not None else 0.0
        wc = Hm[2, 0] * cxp + Hm[2, 1] * cyp + Hm[2, 2]
        uc = (Hm[0, 0] * cxp + Hm[0, 1] * cyp + Hm[0, 2]) / wc
        vc = (Hm[1, 0] * cxp + Hm[1, 1] * cyp + Hm[1, 2]) / wc
        J = np.array([[(Hm[0, 0] - uc * Hm[2, 0]) / wc, (Hm[0, 1] - uc * Hm[2, 1]) / wc],
                      [(Hm[1, 0] - vc * Hm[2, 0]) / wc, (Hm[1, 1] - vc * Hm[2, 1]) / wc]])
        zoom = math.sqrt(abs(float(np.linalg.det(J))))
        rot = math.degrees(math.atan2(float(J[1, 0] - J[0, 1]), float(J[0, 0] + J[1, 1])))
        cdx, cdy = float(uc - cxp), float(vc - cyp)
        model = 'homography'
    else:
        M, inl = cv2.estimateAffinePartial2D(G['src'], dst, method=cv2.RANSAC, ransacReprojThreshold=1.0,
                                             maxIters=300, confidence=0.99)
        if M is None:
            M = np.float32([[1, 0, 0], [0, 1, 0]])
            inl_share = 0.0
        else:
            inl_share = float(inl.mean()) if inl is not None else 0.0
        a, b, tx, ty = float(M[0, 0]), float(M[1, 0]), float(M[0, 2]), float(M[1, 2])
        cu = (a - 1) * X - b * Y + tx
        cv_ = b * X + (a - 1) * Y + ty
        zoom, rot = math.hypot(a, b), math.degrees(math.atan2(b, a))
        cdx, cdy = (a - 1) * cxp - b * cyp + tx, b * cxp + (a - 1) * cyp + ty
        model = 'similarity'
    ru = flow[..., 0] - cu
    rv = flow[..., 1] - cv_
    diag = math.hypot(W, H)
    k = float(fps) / diag                                     # px/frame -> diag/s
    mag = np.hypot(ru, rv) * k
    moving = mag >= float(thr['cuts.move_speed'])
    if moving.any():
        moving = cv2.morphologyEx(moving.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    share = float(moving.mean())
    p95 = float(np.percentile(mag, 95))
    out = {'energy': float(mag.mean()), 'speed': 0.0, 'speed_p95': p95, 'share': share,
           'dir': None, 'coh': 0.0, 'region': None, 'centroid': None, 'region_share': 0.0, 'grid': []}
    out['cam'] = {'dx': cdx * k, 'dy': -cdy * k, 'zoom': zoom, 'rot': rot, 'inliers': inl_share, 'model': model}
    # the subject: the moving region with the most motion (area x median speed) among the 8 largest connected
    # moving regions of at least 0.15% of the frame. Its median speed is the frame's subject speed and its vectors
    # give the direction (a 95th percentile of the whole frame misses a subject smaller than 5% of it).
    min_area = max(12, 0.0015 * H * W)
    if moving.sum() >= min_area:
        n, lab, stats, cents = cv2.connectedComponentsWithStats(moving.astype(np.uint8), connectivity=8)
        areas = stats[1:, cv2.CC_STAT_AREA]
        best = None
        for j0 in np.argsort(-areas)[:8]:
            j = int(j0) + 1
            if stats[j, cv2.CC_STAT_AREA] < min_area:
                break
            sel = lab == j
            sp = float(np.median(mag[sel]))
            score = sp * float(stats[j, cv2.CC_STAT_AREA])
            if best is None or score > best[0]:
                best = (score, j, sp, sel)
        if best is not None:
            _, j, sp, sel = best
            out['speed'] = sp
            su, sv = float(ru[sel].sum()), float(rv[sel].sum())
            tot = float(np.hypot(ru[sel], rv[sel]).sum())
            out['coh'] = math.hypot(su, sv) / tot if tot > 1e-9 else 0.0
            out['dir'] = math.degrees(math.atan2(-sv, su))          # screen up = +90
            x0, y0, ww, hh = (int(stats[j, cv2.CC_STAT_LEFT]), int(stats[j, cv2.CC_STAT_TOP]),
                              int(stats[j, cv2.CC_STAT_WIDTH]), int(stats[j, cv2.CC_STAT_HEIGHT]))
            out['region'] = [x0 / W, y0 / H, (x0 + ww) / W, (y0 + hh) / H]
            out['centroid'] = [float(cents[j][0]) / W, float(cents[j][1]) / H]
            out['region_share'] = float(stats[j, cv2.CC_STAT_AREA]) / float(H * W)
    # coarse grid of arrows (for drawing): mean motion of the moving pixels in each cell
    gx, gy = (6, 4) if W >= H else (4, 6)
    ch, cw = H // gy, W // gx
    for j in range(gy):
        for i in range(gx):
            m = moving[j * ch:(j + 1) * ch, i * cw:(i + 1) * cw]
            if m.mean() < 0.12:
                continue
            u = float(ru[j * ch:(j + 1) * ch, i * cw:(i + 1) * cw][m].mean()) * k
            v = float(rv[j * ch:(j + 1) * ch, i * cw:(i + 1) * cw][m].mean()) * k
            if math.hypot(u, v) < float(thr['cuts.move_speed']):
                continue
            out['grid'].append([(i + 0.5) / gx, (j + 0.5) / gy, u, -v])
    out['mag'] = np.minimum(mag, 1000.0).astype(np.float16)
    return out


def _faces(bgr, thr):
    """[{box: [x0, y0, x1, y1] 0-1, h: height share, score, facing, row (YuNet row)}] biggest first."""
    if not faces_available():
        return []
    h, w = bgr.shape[:2]
    det = _face_detector((w, h), thr['cuts.face_min_score'])
    try:
        _, found = det.detect(bgr)
    except Exception:  # noqa: BLE001
        return []
    out = []
    if found is None:
        return out
    for f in found:
        x, y, fw, fh = (float(v) for v in f[:4])
        if fw < 8 or fh < 8:
            continue
        lm = [float(v) for v in f[4:14]]
        rex, rey, lex, ley, nx = lm[0], lm[1], lm[2], lm[3], lm[4]
        eye_d = math.hypot(lex - rex, ley - rey)
        yaw = (nx - (rex + lex) / 2.0) / eye_d if eye_d > 1e-3 else 0.0
        facing = 'right' if yaw > 0.18 else 'left' if yaw < -0.18 else 'front'
        out.append({'box': [max(0.0, x / w), max(0.0, y / h), min(1.0, (x + fw) / w), min(1.0, (y + fh) / h)],
                    'h': fh / h, 'score': float(f[14]), 'facing': facing, 'yaw': yaw,
                    'eyes': [((rex + lex) / 2.0) / w, ((rey + ley) / 2.0) / h], 'row': f.copy()})
    out.sort(key=lambda d: -(d['h'] * d['score']))
    return out


def _saliency(bgr, flow_size):
    """Still-image saliency at flow size, 0-1: the mean of spectral-residual saliency (Hou & Zhang 2007: what
    differs from the picture's own texture statistics) and frequency-tuned colour contrast (Achanta et al. 2009: how
    far each blurred pixel's Lab colour is from the frame's mean colour)."""
    cv2 = _cv2()
    small = cv2.resize(bgr, flow_size, interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    ft = np.linalg.norm(lab - lab.reshape(-1, 3).mean(0), axis=2)
    ft /= max(float(ft.max()), 1e-6)
    s = _saliency_obj()
    sr = None
    if s:
        ok, m = s.computeSaliency(bgr)
        if ok:
            sr = cv2.resize(m.astype(np.float32), flow_size, interpolation=cv2.INTER_AREA)
            sr /= max(float(sr.max()), 1e-6)
    if sr is None:
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        sr = np.abs(cv2.Laplacian(cv2.GaussianBlur(g, (0, 0), 2), cv2.CV_32F))
        sr /= max(float(sr.max()), 1e-6)
    return (0.5 * sr + 0.5 * ft).astype(np.float32)


def analyse_side(bgr_frames, fps, settings=None, thr=None, frames=None):
    """Per-frame measurements of the chronological frames of ONE shot (no cut inside): {'frames', 'bgr', 'small'
    (grey at flow size), 'motion' (per frame; a frame's motion is the step from the frame before it, the first
    frame's the step after it), 'faces', 'sal' (saliency maps), 'fps'}."""
    cv2 = _cv2()
    st = _settings(settings)
    thr = thr or thresholds()
    bgr_frames = [b for b in bgr_frames]
    n = len(bgr_frames)
    if not n:
        return {'frames': [], 'bgr': [], 'small': [], 'motion': [], 'faces': [], 'sal': [], 'fps': fps}
    h, w = bgr_frames[0].shape[:2]
    _, fsize = _sizes(w, h, st['decode_px'], st['flow_px'])
    small = [cv2.resize(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), fsize, interpolation=cv2.INTER_AREA)
             for b in bgr_frames]
    steps = [_flow_step(small[i - 1], small[i], fps, thr) for i in range(1, n)]
    motion = [(steps[0] if steps else None)] + steps
    faces = [_faces(b, thr) for b in bgr_frames]
    sal = [_saliency(b, fsize) for b in bgr_frames]
    sharp = [float(cv2.Laplacian(g, cv2.CV_32F).var()) for g in small]
    return {'frames': list(frames) if frames is not None else list(range(n)), 'bgr': bgr_frames, 'small': small,
            'motion': motion, 'faces': faces, 'sal': sal, 'sharp': sharp, 'fps': fps}


def _subset(side, a, b):
    return {k: (v[a:b] if isinstance(v, list) else v) for k, v in side.items()}


def _static_overlay(ga, gb, thr):
    """Burned-in text/graphics that stay the same across the cut while the picture changes (bool mask at flow
    size, or None when the picture itself barely changed)."""
    cv2 = _cv2()
    d = cv2.absdiff(ga, gb)
    same = d <= float(thr['cuts.overlay_diff'])
    gxa = cv2.Sobel(ga, cv2.CV_32F, 1, 0, ksize=3)
    gya = cv2.Sobel(ga, cv2.CV_32F, 0, 1, ksize=3)
    gxb = cv2.Sobel(gb, cv2.CV_32F, 1, 0, ksize=3)
    gyb = cv2.Sobel(gb, cv2.CV_32F, 0, 1, ksize=3)
    textured = np.hypot(gxa, gya) >= 40.0
    if textured.sum() < 20:
        return None, 0.0
    # an overlay has the same edges on both sides (the gradient vector, not only the brightness): a chance match of
    # two different pictures' brightness is common, of their edges rare
    edge_same = same & textured & (np.abs(gxa - gxb) <= 16.0) & (np.abs(gya - gyb) <= 16.0)
    if float(edge_same.sum()) / float(textured.sum()) > 0.5:
        return None, 0.0                      # the picture's own texture stays (a jump cut): nothing to mask
    m = edge_same.astype(np.uint8)
    H, W = m.shape
    k = max(3, int(round(0.03 * max(H, W))) | 1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    # each static block (a caption line, a logo) masked as its whole box: saliency spreads past the letters
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    out = np.zeros((H, W), np.uint8)
    pad = max(3, int(round(0.025 * max(H, W))))
    for j in range(1, n):
        x, y, w, h, a = (int(v) for v in stats[j])
        if a < 0.0015 * H * W:
            continue
        if float(edge_same[y:y + h, x:x + w].mean()) < 0.06:      # a sparse cloud of chance matches
            continue
        out[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad] = 1
    share = float(out.mean())
    if share < 0.002 or share > 0.35:
        return None, share
    return out > 0, share


def _attention(sal, motion, faces, mask, thr, w, h):
    """Attention point {x, y (0-1), basis: face|motion|saliency, spread (diag fraction)} for one frame."""
    cv2 = _cv2()
    if faces and faces[0]['h'] >= float(thr['cuts.face_attention_min_h']):
        f = faces[0]
        x0, y0, x1, y1 = f['box']
        ex, ey = f['eyes']
        return {'x': float(min(max(ex, x0), x1)), 'y': float(min(max(ey, y0), y1)), 'basis': 'face',
                'spread': float(math.hypot((x1 - x0) * w, (y1 - y0) * h) / math.hypot(w, h) / 2)}
    H, W = sal.shape
    G = _grid((H, W))
    s = sal.astype(np.float32).copy()
    mag = motion['mag'].astype(np.float32) if motion is not None else None
    moving = motion is not None and motion['speed'] >= float(thr['cuts.action_speed'])
    if mask is not None:
        s[mask] = 0.0
        if mag is not None:
            mag = mag.copy()
            mag[mask] = 0.0
    s = s * G['taper']                           # spectral residual lights up the frame borders: fade them out
    s /= max(float(s.max()), 1e-6)
    comb = s
    basis = 'saliency'
    if moving and mag is not None:
        m = np.clip(mag / (2.0 * float(thr['cuts.action_speed'])), 0.0, 1.0)
        wm = 0.6 * max(0.0, 1.0 - float(motion.get('share', 0.0)))   # frame-wide motion does not lead the eye
        comb = (1.0 - wm) * s + wm * m
        basis = 'motion' if wm >= 0.3 else 'saliency'
    for f in faces or []:                       # small faces still pull the eye
        x0, y0, x1, y1 = f['box']
        cx, cy = (x0 + x1) / 2 * W, (y0 + y1) / 2 * H
        sg = max(2.0, (x1 - x0) * W)
        comb = comb + 0.8 * np.exp(-(((G['X'] - cx) ** 2 + (G['Y'] - cy) ** 2) / (2 * sg * sg)))
    comb = comb * (0.5 + 0.5 * G['prior'])          # centre bias (Tatler 2007), kept mild
    comb = cv2.GaussianBlur(comb.astype(np.float32), (0, 0), max(1.0, 0.015 * math.hypot(W, H)))
    j = int(np.argmax(comb))
    py, px = divmod(j, W)
    top = comb >= 0.5 * float(comb.max())
    d2 = ((G['X'] - px) ** 2 + (G['Y'] - py) ** 2)[top]
    spread = float(math.sqrt(float(d2.mean())) / math.hypot(W, H)) if d2.size else 0.0
    return {'x': (px + 0.5) / W, 'y': (py + 0.5) / H, 'basis': basis, 'spread': spread}


def _median_point(points):
    if not points:
        return None
    xs = np.array([p['x'] for p in points])
    ys = np.array([p['y'] for p in points])
    bases = [p['basis'] for p in points]
    basis = max(set(bases), key=bases.count)
    return {'x': float(np.median(xs)), 'y': float(np.median(ys)), 'basis': basis,
            'spread': float(np.median([p['spread'] for p in points]))}


# ------------------------------------------------------------------ action phase

def _phase_out(s, thr_speed):
    """Where the cut falls in the outgoing shot's action. s: subject speed per frame, chronological, ending at the
    last frame before the cut."""
    s = np.asarray([x for x in s if x is not None], float)
    n = len(s)
    if not n:
        return {'phase': 'unknown'}
    act = s >= thr_speed
    recent = min(n, 3)
    if not act[-recent:].any():
        if act.any():
            last = int(np.flatnonzero(act)[-1])
            return {'phase': 'after the action', 'stopped_frames_before_cut': int(n - 1 - last),
                    'peak_speed': _r(float(s[:last + 1].max()))}
        return {'phase': 'still', 'peak_speed': _r(float(s.max()))}
    i = n - 1
    while i > 0 and act[i - 1]:
        i -= 1
    run = s[i:]
    pk = i + int(np.argmax(run))
    since_peak = n - 1 - pk
    if since_peak <= 1 and n - 1 - i >= 1 and s[-1] >= s[max(i, n - 3)] * 0.95:
        phase = 'building'
    elif s[-1] < 0.6 * s[pk]:
        phase = 'settling'
    else:
        phase = 'at the peak'
    return {'phase': phase, 'motion_frames_before_cut': int(n - i), 'peak_frames_before_cut': int(since_peak + 1),
            'peak_speed': _r(float(s[pk])), 'run_reaches_window_start': bool(i == 0)}


def _phase_in(s, thr_speed):
    """How the incoming shot starts. s: subject speed per frame, chronological, from the first frame after the
    cut."""
    s = np.asarray([x for x in s if x is not None], float)
    n = len(s)
    if not n:
        return {'phase': 'unknown'}
    act = s >= thr_speed
    first = min(n, 3)
    if act[:first].any():
        j = 0
        while j + 1 < n and act[j + 1]:
            j += 1
        run = s[:j + 1]
        pk = int(np.argmax(run))
        if pk <= 1 and len(run) > 2 and run[-1] < 0.6 * run[pk]:
            phase = 'settling'
        elif pk <= 1:
            phase = 'in motion'
        else:
            phase = 'building'
        return {'phase': phase, 'motion_frames_after_cut': int(j + 1), 'peak_frames_after_cut': int(pk),
                'peak_speed': _r(float(s[pk])), 'run_reaches_window_end': bool(j == n - 1)}
    if act.any():
        k = int(np.flatnonzero(act)[0])
        return {'phase': 'motion starts later', 'starts_frames_after_cut': k, 'peak_speed': _r(float(s[k:].max()))}
    return {'phase': 'still', 'peak_speed': _r(float(s.max()))}


def snap_cut(fr, f, radius=2, ratio=1.5):
    """The frame of the largest picture change within +-radius of f (fr: {frame: BGR}), when it is at least `ratio`
    times the change at f; else f. A detected cut can sit a frame off (time stamps rounded by a seek)."""
    cv2 = _cv2()
    small = {}

    def g(i):
        if i not in small:
            small[i] = cv2.resize(cv2.cvtColor(fr[i], cv2.COLOR_BGR2GRAY), (64, 36),
                                  interpolation=cv2.INTER_AREA).astype(np.float32)
        return small[i]
    diff = {}
    for k in range(f - radius, f + radius + 1):
        if k in fr and k - 1 in fr:
            diff[k] = float(np.abs(g(k) - g(k - 1)).mean())
    if f not in diff or not diff:
        return f
    best = max(diff, key=diff.get)
    return best if best != f and diff[best] >= ratio * max(diff[f], 1e-6) else f
