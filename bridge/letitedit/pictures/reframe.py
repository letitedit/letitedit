"""Reframing solver: crops of another shape (9:16, 4:5, 1:1, 16:9 or any size) that keep several things in frame at
once - faces, hands, the part being worked on, anything named - with calm, smooth camera motion; and, where the
things that must stay can't share one crop, a split (two crops stacked) or an inset (picture in picture), offered as
ready edits.

How it works
  1. Subjects. For every moment of a clip it collects boxes (source display pixels, the upright picture):
       faces      OpenCV YuNet at two scales on frames at `face_hz` (squat boxes - mostly hands - dropped), linked
                  into tracks, tracks that never overlap in time joined (the same person found again);
       action     where the picture moves once the camera's own motion is taken out (feature flow + a robust
                  similarity fit, frame differences with faces masked out, a decaying heat map; the box holding most
                  of the heat) - in hands-on footage the hands and the tool;
       given      boxes named by the caller (an AI or a person): one box at a time (VitTrack, the tracker
                  letitedit_track uses, forwards and backwards), boxes at several times (between two given boxes
                  forwards from one and backwards from the next, joined), straight lines between boxes, or a static
                  box; the given size is kept (the tracker's own size wanders), and where the tracker loses the
                  thing it is carried with the camera's measured motion for up to `carry_lost_s`;
       track      saved letitedit_track results for the file;
       aim        the picture's middle, where no required subject is in view (the operator aimed there).
     Each subject has a priority: required (must stay inside), preferred (inside when it costs little), optional,
     ignore; required subjects are ranked (the order they are named in `keep`). Boxes are clipped to the picture.
  2. Path. One linear program per clip finds the crop centre (x, y) and size (zoom within a bound) at every sample
     (`solve_hz`): weighted L1 costs on the first, second and third differences (pans that start and stop gently,
     holds preferred - the camera stays put unless something must stay in), a weak pull towards the subjects' centre
     (`recentre_s`), and slack-penalised containment of every subject (a cheap margin zone, then the box itself;
     required >> preferred >> optional; face headroom), inside the platform's uncovered area when a platform is
     given. The crop never leaves the picture and never moves faster than `max_speed`. The path may jump at the
     clip's own cuts (an isolated picture change with steady frames on both sides, or given).
  3. Can't fit. Where the required subjects (with margins) are wider or taller than the largest crop, the lower-
     ranked ones are left out in rank order: those moments are reported with times and names, the path keeps the
     top-ranked ones, and the subject that comes back is brought in over `rejoin_s`. The result offers a split and an
     inset for those spans as complete edit ops (letitedit_timeline_apply vocabulary): a copy of the clip on a track
     above, muted, placed with Size/Position and cut to its panel with Crop: Rectangle; the clip itself gets the
     other panel's path. Nothing required is dropped without being listed.
  4. Output. The crop path is a keyframed Size, Position & Rotate effect ({size_position: {keys}}), keys thinned to
     where the path changes and checked frame by frame with the engine's own keyframe arithmetic (annotate.py), so the
     coverage reported is the coverage of what renders. Per subject: the share of frames fully in the crop (and in
     the uncovered area); smoothness in output pixels per second (speed, acceleration, holds). A preview sheet shows
     the source with the crop path and the boxes, and the frames the export engine (melt) renders.

Project mode reframes clips of a project to its own frame (plan, then apply through timeline_tools.apply_project:
one undo step); formats.py uses `version_item` for linked versions (letitedit_versions reframe mode 'solve'); file
mode plans a file range for any target without a project.

Coordinates: continuous pixels of the upright source picture, boxes (x0, y0, x1, y1). Times: source seconds for
subjects and given boxes (as letitedit_track and the frame tools show the file), clip seconds for keyframes.

The geometry and the path are in parts, each name imported back here: reframe_geometry (settings, boxes, crop
geometry, the linear program, who fits where) and reframe_path (the crop path and its keyframes). The subjects, one
clip, the offers and the preview stay here with the media facts, because they read WORK, which the tests point at
their own folder.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)


# ---- this module's parts: every name in them imported back, so each is the same object as before
# the settings and the geometry: boxes, the target shape and crop, the linear program, who fits where
from letitedit.pictures.reframe_geometry import (  # noqa: E402,F401
    _SAI_ROOT, SCHEMA, ENGINE, CACHE, SPLIT_TRACK, INSET_TRACK, NAMED, PRIORITIES, AUTO_KINDS, DEFAULTS, WEIGHT,
    MOTION, KEEP_OUT_WEIGHT, Unsupported, _r, _now, settings_of, box_w, box_h, union, inside, iou, resolve_target,
    max_window, safe_area, rect_for, window_of_rect, _LP, _diff_rows, _padded, _fits, fit_analysis
)
# the crop path solved, and its keyframes (what renders)
from letitedit.pictures.reframe_path import (  # noqa: E402,F401
    solve_path, _dilate_time, _runs, debounce, _rejoin_ramp, _fill_hold, _rect_text, eval_keys, _edge_dev,
    keys_from_path
)


import copy
import hashlib
import json
import math
import os
import re
import time
import uuid
from pathlib import Path

import numpy as np
WORK = CACHE / 'reframe'


# ============================================================================ media

def media(path):
    """Picture facts of a file (annotate.media_info: display size after the orientation flag, fps, duration,
    fingerprint). Refuses what the solver can't reframe honestly."""
    import letitedit.pictures.annotate as annotate
    try:
        info = annotate.media_info(path)
    except annotate.Unsupported as e:
        raise Unsupported(str(e)) from e
    if info['mirrored']:
        raise Unsupported(f'{Path(path).name}: its orientation flag mirrors the picture; not supported')
    if abs(float(info.get('sar') or 1.0) - 1.0) > 1e-3:
        raise Unsupported(f'{Path(path).name} has non-square pixels (pixel aspect {info["sar"]}); not supported yet')
    return info


def _frames(path, t0, t1, hz, long_side, info):
    """(t, BGR frame, display px per frame px) at `hz` over source [t0, t1), upright, the long side `long_side`."""
    import letitedit.sound.av_tools as av_tools
    W, H = info['display']
    k = long_side / max(W, H)
    w, h = max(2, int(round(W * k / 2)) * 2), max(2, int(round(H * k / 2)) * 2)
    for i, fr in enumerate(av_tools._frames(path, t0, max(0.05, t1 - t0), hz, w, h)):
        t = t0 + i / hz
        if t > t1 + 0.5 / hz:
            break
        yield t, fr, W / w


def _cache_path(kind, path, info, t0, t1, extra):
    key = json.dumps([ENGINE, kind, os.path.normcase(os.path.abspath(path)), info['fingerprint'], round(t0, 3),
                      round(t1, 3), extra], sort_keys=True, default=str)
    d = WORK / 'subjects'
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{kind}-{hashlib.sha1(key.encode()).hexdigest()[:20]}.json'


def _cached(kind, path, info, t0, t1, extra, compute):
    p = _cache_path(kind, path, info, t0, t1, extra)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding='utf-8-sig'))
        except ValueError:
            pass
    data = compute()
    tmp = p.with_name(p.name + f'.{uuid.uuid4().hex[:6]}.tmp')
    tmp.write_text(json.dumps(data), encoding='utf-8')
    os.replace(tmp, p)
    return data


# ============================================================================ subjects: faces

def find_faces(path, t0, t1, info, settings):
    """Face tracks over source [t0, t1]: {'times': [...], 'tracks': [{'boxes': [[x0, y0, x1, y1] | None per
    time], 'size': median face width, 'hits'}]} - YuNet detections at face_hz linked by overlap, gaps up to 0.7 s
    bridged, tracks seen fewer than 3 times dropped. Boxes are the detector's face boxes (display pixels)."""
    import cv2

    import letitedit.review.checks as checks
    hz = float(settings['face_hz'])
    score = float(settings['face_min_score'])

    def compute():
        if not checks.faces_available():
            return {'times': [], 'tracks': [], 'note': 'the face model (YuNet) is not available'}
        dets, dets_by = [], {}
        for t, fr, k in _frames(path, t0, t1, hz, 640, info):
            boxes = []
            # two scales: big close faces score far better on the smaller picture
            for scale in (1.0, 0.5):
                img = fr if scale == 1.0 else cv2.resize(fr, (fr.shape[1] // 2, fr.shape[0] // 2),
                                                         interpolation=cv2.INTER_AREA)
                size = (img.shape[1], img.shape[0])
                det = dets_by.get(size)
                if det is None:
                    det = dets_by[size] = cv2.FaceDetectorYN.create(str(checks.YUNET), '', size, score, 0.3, 50)
                _, found = det.detect(img)
                kk = k / scale
                for f in (found if found is not None else []):
                    # a face box is taller than wide (h/w 1.15-1.5 on real faces); squat boxes are mostly hands
                    if f[2] * kk >= 12 * k and (f[3] / max(1e-6, f[2]) >= 1.08 or f[14] >= 0.9):
                        boxes.append([float(f[0]) * kk, float(f[1]) * kk, float(f[0] + f[2]) * kk,
                                      float(f[1] + f[3]) * kk, float(f[14])])
            dets.append((t, _nms(boxes, 0.4)))
        times = [d[0] for d in dets]
        tracks = _link_tracks(dets, max_gap=0.7)
        return {'times': times, 'tracks': tracks}
    return _cached('faces', path, info, t0, t1, [hz, score, 'two-scale lanes shape'], compute)


def _nms(boxes, thr):
    """Boxes [x0, y0, x1, y1, score] without the lower-scored of any pair overlapping more than thr (IoU)."""
    out = []
    for b in sorted(boxes, key=lambda b: -b[4]):
        if all(iou(b, o) <= thr for o in out):
            out.append(b)
    return out


def _link_tracks(dets, max_gap=0.7, min_hits=3):
    """Detections [(t, [[x0, y0, x1, y1, score], ...])] -> tracks {'boxes': per time box or None, 'size'}."""
    tracks = []
    n = len(dets)
    for i, (t, boxes) in enumerate(dets):
        used = set()
        for b in sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
            best, best_score = None, 0.0
            for j, tr in enumerate(tracks):
                if j in used or t - tr['last_t'] > max_gap:
                    continue
                lb = tr['last_b']
                sc = iou(lb, b)
                if sc < 0.15:
                    d = math.hypot((lb[0] + lb[2] - b[0] - b[2]) / 2, (lb[1] + lb[3] - b[1] - b[3]) / 2)
                    if d < 0.6 * max(lb[2] - lb[0], b[2] - b[0]):
                        sc = 0.15
                if sc > best_score:
                    best, best_score = j, sc
            if best is None or best_score < 0.15:
                tracks.append({'hits': {}, 'last_t': t, 'last_b': b[:4]})
                best = len(tracks) - 1
            tr = tracks[best]
            tr['hits'][i] = b[:4]
            tr['last_t'], tr['last_b'] = t, b[:4]
            used.add(best)
    out = []
    times = [d[0] for d in dets]
    for tr in tracks:
        if len(tr['hits']) < min_hits:
            continue
        idx = sorted(tr['hits'])
        boxes = [None] * n
        for a, b in zip(idx, idx[1:] + [None]):
            boxes[a] = tr['hits'][a]
            if b is not None and times[b] - times[a] <= max_gap + 1e-6:
                for m in range(a + 1, b):
                    f = (times[m] - times[a]) / max(1e-9, times[b] - times[a])
                    boxes[m] = [tr['hits'][a][c] + f * (tr['hits'][b][c] - tr['hits'][a][c]) for c in range(4)]
        widths = sorted(tr['hits'][i][2] - tr['hits'][i][0] for i in idx)
        out.append({'boxes': boxes, 'size': widths[len(widths) // 2], 'hits': len(idx)})
    out.sort(key=lambda tr: -tr['size'] * tr['hits'])
    return _lanes(out, n)


def _lanes(tracks, n):
    """Tracks that never share a moment merged into one lane (the same person found again after a gap): the
    biggest/longest first; a track joins the first lane it doesn't overlap in time."""
    lanes = []
    for tr in tracks:
        own = [b is not None for b in tr['boxes']]
        for ln in lanes:
            if not any(a and b for a, b in zip(own, ln['_own'])):
                ln['boxes'] = [x if x is not None else y for x, y in zip(ln['boxes'], tr['boxes'])]
                ln['_own'] = [a or b for a, b in zip(own, ln['_own'])]
                ln['hits'] += tr['hits']
                break
        else:
            lanes.append({'boxes': list(tr['boxes']), 'size': tr['size'], 'hits': tr['hits'], '_own': own})
    for ln in lanes:
        ln.pop('_own')
    return lanes


def head_box(b, src_w, src_h):
    """A face detector's box widened a little to the whole face (forehead, ears, chin) - the hair above may be
    cropped, as in any close-up; `headroom` adds room above it where the crop allows."""
    w, h = b[2] - b[0], b[3] - b[1]
    return [max(0.0, b[0] - 0.06 * w), max(0.0, b[1] - 0.12 * h), min(src_w, b[2] + 0.06 * w),
            min(src_h, b[3] + 0.04 * h)]


# ============================================================================ subjects: action (motion)

def find_action(path, t0, t1, info, settings, exclude=None):
    """Where the picture moves once the camera's own motion is taken out, over source [t0, t1] at action_hz:
    {'times', 'boxes' (display px or None), 'energy', 'spread', 'cuts' (times of hard cuts)}. Per frame pair:
    corners followed with Lucas-Kanade, a similarity fit with RANSAC (the camera), the previous frame warped onto
    this one, the difference above the frame's own noise, accumulated in a heat map that follows the camera and
    halves every 0.5 s; the box is the one holding `action_mass` of the heat (per axis). exclude: [(times,
    boxes)] regions (display px, e.g. heads) whose motion doesn't count - a talking head isn't a demonstration."""
    import cv2
    hz = float(settings['action_hz'])
    px = int(settings['action_px'])
    mass = float(settings['action_mass'])

    def compute():
        times, boxes, energy, spread, cuts, cams = [], [], [], [], [], []
        change = []                      # per frame: (histogram correlation with the previous frame, inlier share)
        prev = heat = prev_hist = None
        decay = 0.5 ** (1.0 / (hz * 0.5))
        for t, fr, k in _frames(path, t0, t1, hz, px, info):
            g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            h, w = g.shape
            hist = cv2.calcHist([g], [0], None, [32], [0, 256])
            cv2.normalize(hist, hist)
            times.append(t)
            if prev is None:
                heat = np.zeros((h, w), np.float32)
                boxes.append(None)
                energy.append(0.0)
                spread.append(1.0)
                cams.append(None)
                change.append((1.0, 1.0))
                prev, prev_hist = g, hist
                continue
            M, inl = _camera_motion(prev, g)
            # the camera's motion from the previous frame to this one, in display pixels
            cams.append([round(float(M[0, 0]), 6), round(float(M[0, 1]), 6), round(float(M[0, 2]) * k, 3),
                         round(float(M[1, 0]), 6), round(float(M[1, 1]), 6), round(float(M[1, 2]) * k, 3)]
                        if inl >= 0.25 else None)
            corr = float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL))
            change.append((corr, inl))
            if corr < 0.55 and inl < 0.3:
                heat[:] = 0
                boxes.append(None)
                energy.append(0.0)
                spread.append(1.0)
                cams[-1] = None
                prev, prev_hist = g, hist
                continue
            warped = cv2.warpAffine(prev, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            valid = cv2.warpAffine(np.ones((h, w), np.uint8), M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
            valid = cv2.erode(valid, np.ones((7, 7), np.uint8))
            d = cv2.absdiff(g, warped).astype(np.float32) * valid
            d = cv2.GaussianBlur(d, (0, 0), 1.2)
            vals = d[valid > 0]
            noise = float(np.median(vals)) if vals.size else 0.0
            thr = max(10.0, 3.0 * noise + 5.0)
            mot = np.clip(d - thr, 0, None)
            for ex_t, ex_b in exclude or ():
                b = _box_at(ex_t, ex_b, t)
                if b is not None:
                    bw, bh = (b[2] - b[0]) / k, (b[3] - b[1]) / k
                    x0, y0 = max(0, int(b[0] / k - 0.15 * bw)), max(0, int(b[1] / k - 0.1 * bh))
                    x1, y1 = min(w, int(b[2] / k + 0.15 * bw) + 1), min(h, int(b[3] / k + 0.05 * bh) + 1)
                    mot[y0:y1, x0:x1] = 0
            heat = cv2.warpAffine(heat, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=0) * decay + mot
            tot = float(heat.sum())
            e = tot / (w * h)
            energy.append(round(e, 4))
            if e <= 0:
                boxes.append(None)
                spread.append(1.0)
            else:
                b = _mass_box(heat, mass)
                area = (b[2] - b[0]) * (b[3] - b[1]) / (w * h)
                spread.append(round(area, 4))
                boxes.append([round(b[0] * k, 1), round(b[1] * k, 1), round(b[2] * k, 1), round(b[3] * k, 1)])
            prev, prev_hist = g, hist
        for i, (corr, inl) in enumerate(change):
            if corr < 0.55 and inl < 0.3:
                before = change[i - 1] if i > 0 else (1.0, 1.0)
                after = change[i + 1] if i + 1 < len(change) else (1.0, 1.0)
                if before[0] > 0.8 and after[0] > 0.8 and before[1] >= 0.3 and after[1] >= 0.3:
                    cuts.append(round(times[i], 3))
        return {'times': times, 'boxes': boxes, 'energy': energy, 'spread': spread, 'cuts': cuts, 'cams': cams}
    ex_key = hashlib.sha1(json.dumps(exclude or [], default=str).encode()).hexdigest()[:12]
    return _cached('action', path, info, t0, t1, [hz, px, mass, ex_key, 'cams', 'isolated cuts'], compute)


def _box_at(times, boxes, t, max_gap=0.5):
    """The box of a (times, boxes|None) series at t: linear between known neighbours, else None."""
    if not len(times):
        return None
    j = int(np.searchsorted(times, t))
    a, b = j - 1, j
    if 0 <= a < len(times) and b < len(times) and boxes[a] is not None and boxes[b] is not None             and times[b] - times[a] <= max_gap:
        f = (t - times[a]) / max(1e-9, times[b] - times[a])
        return [boxes[a][c] + f * (boxes[b][c] - boxes[a][c]) for c in range(4)]
    for x in (a, b):
        if 0 <= x < len(times) and boxes[x] is not None and abs(times[x] - t) <= max_gap / 2:
            return boxes[x]
    return None


def _camera_motion(prev, cur):
    """The camera's motion from prev to cur as a 2x3 similarity (corners + LK + RANSAC), and the inlier share."""
    import cv2
    pts = cv2.goodFeaturesToTrack(prev, maxCorners=220, qualityLevel=0.01, minDistance=7, blockSize=7)
    eye = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    if pts is None or len(pts) < 10:
        (dx, dy), resp = cv2.phaseCorrelate(prev.astype(np.float32), cur.astype(np.float32))
        return np.array([[1.0, 0.0, dx], [0.0, 1.0, dy]]), 0.5 if resp > 0.2 else 0.0
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None, winSize=(17, 17), maxLevel=3)
    good = st.ravel() == 1
    if good.sum() < 8:
        return eye, 0.0
    M, inl = cv2.estimateAffinePartial2D(pts[good], nxt[good], method=cv2.RANSAC, ransacReprojThreshold=1.5,
                                         maxIters=500, confidence=0.98)
    if M is None:
        return eye, 0.0
    return M, float(inl.sum()) / max(1, len(pts))


def _mass_box(heat, share):
    """The box holding `share` of the heat along each axis (quantiles of the marginals)."""
    lo = (1.0 - share) / 2
    xs = heat.sum(0)
    ys = heat.sum(1)
    cx = np.cumsum(xs) / max(1e-9, xs.sum())
    cy = np.cumsum(ys) / max(1e-9, ys.sum())
    x0 = int(np.searchsorted(cx, lo))
    x1 = int(np.searchsorted(cx, 1 - lo)) + 1
    y0 = int(np.searchsorted(cy, lo))
    y1 = int(np.searchsorted(cy, 1 - lo)) + 1
    return [float(x0), float(y0), float(min(heat.shape[1], x1)), float(min(heat.shape[0], y1))]


# ============================================================================ subjects: given boxes, tracked

def _vit(path, t_a, t_b, box, info, settings, backward=False):
    """VitTrack (the model av_tools.track uses) from `box` (display px) at t_a towards t_b, forwards or
    backwards: [(t, box | None, score)] with simple loss rules (low score, jumps, size changes; back after 3 sure
    frames)."""
    import cv2

    import letitedit.sound.av_tools as av_tools
    hz = float(settings['track_hz'])
    px = int(settings['track_px'])

    def backwards(chunk_s=15.0):
        # decoded in chunks from the end, each chunk handed out last frame first (memory stays small)
        hi = t_a + 0.5 / hz
        while hi > t_b + 1e-6:
            lo = max(t_b, hi - chunk_s)
            part = list(_frames(path, lo, hi, hz, px, info))
            part = [f for f in part if f[0] < hi - 0.5 / hz or hi >= t_a]
            yield from reversed(part)
            hi = lo
    it = backwards() if backward else _frames(path, t_a, t_b, hz, px, info)
    tr, out, k0 = None, [], None
    good_run, lost_at, last_ok = 0, None, None
    area0 = max(1.0, (box[2] - box[0]) * (box[3] - box[1]))
    for t, fr, k in it:
        if tr is None:
            if backward and t > t_a + 0.5 / hz:
                continue
            k0 = k
            params = cv2.TrackerVit_Params()
            params.net = str(av_tools.VITTRACK)
            tr = cv2.TrackerVit.create(params)
            x0, y0, x1, y1 = [v / k for v in box]
            tr.init(fr, (int(round(x0)), int(round(y0)), max(4, int(round(x1 - x0))), max(4, int(round(y1 - y0)))))
            out.append((t, list(box), 1.0))
            last_ok = list(box)
            continue
        ok, b = tr.update(fr)
        sc = float(tr.getTrackingScore())
        bx = [b[0] * k0, b[1] * k0, (b[0] + b[2]) * k0, (b[1] + b[3]) * k0]
        sure = bool(ok) and b[2] > 0 and b[3] > 0 and sc >= 0.3
        if sure and last_ok is not None:
            jump = math.hypot((bx[0] + bx[2] - last_ok[0] - last_ok[2]) / 2,
                              (bx[1] + bx[3] - last_ok[1] - last_ok[3]) / 2)
            ratio = (bx[2] - bx[0]) * (bx[3] - bx[1]) / area0
            if jump > 0.15 * max(info['display']) or not (1 / 2.5 <= ratio <= 2.5):
                sure = False
        if lost_at is not None:
            good_run = good_run + 1 if sure and sc >= 0.45 else 0
            if good_run >= 3:
                lost_at = None
            else:
                sure = False
        elif not sure:
            lost_at, good_run = t, 0
        out.append((t, bx if sure else None, sc))
        if sure:
            last_ok = bx
    if backward:
        out.reverse()
    return out


def _given_keys(spec, info, t0):
    """A keep entry's given boxes -> [[t, x0, y0, x1, y1] (display px)] sorted by time."""
    W, H = info['display']
    units = spec.get('units', 'fraction')
    keys = []
    if spec.get('boxes'):
        for row in spec['boxes']:
            if len(row) != 5:
                raise ValueError(f"keep {spec.get('label')!r}: boxes rows are [t, x0, y0, x1, y1]")
            keys.append([float(row[0])] + [float(v) for v in row[1:5]])
    elif spec.get('box') is not None:
        at = spec.get('at', spec.get('t'))
        if len(spec['box']) != 4:
            raise ValueError(f"keep {spec.get('label')!r}: box is [x0, y0, x1, y1]")
        keys.append([float(at) if at is not None else t0] + [float(v) for v in spec['box']])
    else:
        raise ValueError(f"keep entry {spec.get('label')!r} needs box (+ at) or boxes [[t, x0, y0, x1, y1], ...]")
    for row in keys:
        if units == 'fraction':
            if any(v < -0.05 or v > 1.05 for v in row[1:]):
                raise ValueError(f"keep {spec.get('label')!r}: box {row[1:]} is not in 0-1 fractions (units='px')")
            row[1:] = [row[1] * W, row[2] * H, row[3] * W, row[4] * H]
        elif units != 'px':
            raise ValueError("units is 'fraction' (default) or 'px'")
        x0, y0, x1, y1 = row[1:]
        row[1:] = [max(0.0, min(x0, x1)), max(0.0, min(y0, y1)), min(float(W), max(x0, x1)),
                   min(float(H), max(y0, y1))]
        if row[3] - row[1] < 2 or row[4] - row[2] < 2:
            raise ValueError(f"keep {spec.get('label')!r}: box {row[1:]} is empty")
    keys.sort(key=lambda r: r[0])
    return keys


def given_subject(path, info, spec, t0, t1, settings):
    """Boxes of a subject named by the caller over source [t0, t1]: {'times', 'boxes', 'how', 'lost'}.
    spec: {'label', 'box': [x0, y0, x1, y1], 'at': s} or {'boxes': [[t, x0, y0, x1, y1], ...]}, units 'fraction'
    (0-1 of the upright picture, default) or 'px'; follow 'track' (default: VitTrack from each given box - between
    two given boxes forwards from one and backwards from the next, joined), 'keys' (straight lines between the
    given boxes) or 'static' (one box throughout)."""
    keys = _given_keys(spec, info, t0)
    follow = spec.get('follow') or 'track'
    if follow not in ('track', 'keys', 'static'):
        raise ValueError("follow is 'track' (default), 'keys' or 'static'")
    step = 1.0 / float(settings['track_hz'])
    times = [float(x) for x in np.arange(t0, t1 + 1e-6, step)]
    if follow == 'static' or (follow == 'keys' and len(keys) == 1):
        b = keys[0][1:]
        return {'times': times, 'boxes': [list(b)] * len(times), 'how': 'static box', 'lost': []}
    if follow == 'keys':
        kt = [k[0] for k in keys]
        boxes = [[float(np.interp(t, kt, [k[c] for k in keys])) for c in range(1, 5)] for t in times]
        return {'times': times, 'boxes': boxes, 'how': f'straight lines between {len(keys)} given boxes', 'lost': []}

    def compute():
        rows = []
        first = keys[0]
        if first[0] > t0 + step / 2:
            rows += _vit(path, first[0], t0, first[1:], info, settings, backward=True)[:-1]
        for i, kk in enumerate(keys):
            end = keys[i + 1][0] if i + 1 < len(keys) else t1
            if end <= kk[0] + step / 2:
                rows.append((kk[0], kk[1:], 1.0))
                continue
            fwd = _vit(path, kk[0], end, kk[1:], info, settings)
            if i + 1 < len(keys):
                # between two given boxes: forwards from this one and backwards from the next, then joined
                bwd = _vit(path, end, kk[0], keys[i + 1][1:], info, settings, backward=True)
                seg = _join_runs(fwd, bwd, kk, keys[i + 1])
                seg = [r for r in seg if r[0] < keys[i + 1][0] - step / 2]
            else:
                seg = fwd
            rows += seg
        return [[r[0], r[1], r[2]] for r in rows]
    rows = _cached('given', path, info, t0, t1, [keys, settings['track_hz'], settings['track_px'], 'fb'], compute)
    rows = _steady_size(rows, keys)
    rt = np.asarray([r[0] for r in rows], float)
    out, raw = [], []
    hold = float(settings['hold_lost_s'])
    last, last_t = None, None
    lost = []
    for t in times:
        j = int(np.argmin(np.abs(rt - t))) if len(rt) else None
        b = rows[j][1] if j is not None and abs(rt[j] - t) <= step else None
        raw.append(b)
        if b is None and last is not None and t - last_t <= hold:
            b = last
        elif b is not None:
            last, last_t = b, t
        if b is None:
            lost.append(t)
        out.append(b)
    return {'times': times, 'boxes': out, 'raw': raw, 'how': f'tracked (VitTrack) from {len(keys)} given box(es)',
            'lost': _spans(lost, step)}


def _steady_size(rows, keys, lo=0.75, hi=1.33, window=9):
    """Tracked boxes with the tracker's centre but the given box's size, scaled by the tracker's own scale change
    smoothed over `window` samples and kept within [lo, hi] (VitTrack's box size wanders; the given size is the
    caller's measure of the thing)."""
    if not rows:
        return rows
    kt = [k[0] for k in keys]
    gw = [k[3] - k[1] for k in keys]
    gh = [k[4] - k[2] for k in keys]
    scale = []
    for t, b, _ in rows:
        if b is None:
            scale.append(np.nan)
            continue
        w0, h0 = float(np.interp(t, kt, gw)), float(np.interp(t, kt, gh))
        scale.append(math.sqrt(max(1e-6, (b[2] - b[0]) * (b[3] - b[1])) / max(1e-6, w0 * h0)))
    sc = np.asarray(scale)
    out = []
    for i, (t, b, score) in enumerate(rows):
        if b is None:
            out.append([t, None, score])
            continue
        seg = sc[max(0, i - window // 2):i + window // 2 + 1]
        seg = seg[~np.isnan(seg)]
        k = float(np.clip(np.median(seg) if len(seg) else 1.0, lo, hi))
        w0, h0 = float(np.interp(t, kt, gw)) * k, float(np.interp(t, kt, gh)) * k
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        out.append([t, [cx - w0 / 2, cy - h0 / 2, cx + w0 / 2, cy + h0 / 2], score])
    return out


def carry_with_camera(times, boxes, cam_t, cams, W, H, max_s=2.0):
    """A subject's lost stretches filled by carrying its last box along with the camera's measured motion (the
    thing stays where it was in the world while the camera moves), for up to max_s seconds or until the carried
    box leaves the picture. Returns (boxes, carried times)."""
    if not cams or not any(c is not None for c in cams):
        return boxes, []
    out = list(boxes)
    carried = []
    ct = np.asarray(cam_t, float)
    last, last_t, since = None, None, None
    for i, (t, b) in enumerate(zip(times, boxes)):
        if b is not None:
            last, last_t, since = list(b), t, None
            continue
        if last is None:
            continue
        since = last_t if since is None else since
        if t - since > max_s:
            continue
        # carry the last box over the camera steps between last_t and t
        pts = np.array([[last[0], last[1]], [last[2], last[1]], [last[2], last[3]], [last[0], last[3]]], float)
        ok = True
        for j in np.nonzero((ct > last_t + 1e-6) & (ct <= t + 1e-6))[0]:
            c = cams[j]
            if c is None:
                ok = False
                break
            M = np.array([[c[0], c[1], c[2]], [c[3], c[4], c[5]]])
            pts = pts @ M[:, :2].T + M[:, 2]
        if not ok:
            last = None
            continue
        nb = [float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())]
        cx, cy = (nb[0] + nb[2]) / 2, (nb[1] + nb[3]) / 2
        if not (0 <= cx <= W and 0 <= cy <= H):
            last = None
            continue
        out[i] = [max(0.0, nb[0]), max(0.0, nb[1]), min(float(W), nb[2]), min(float(H), nb[3])]
        carried.append(t)
        last, last_t = out[i], t
    return out, carried


def _join_runs(fwd, bwd, ka, kb):
    """One run between given boxes ka and kb from a forward run (from ka) and a backward run (from kb): where both
    are sure and agree (overlap), a blend weighted by nearness in time; where they disagree, the run whose given
    box is nearer in time; where one is sure, that one; where neither, a straight line between the given boxes."""
    ta, tb = ka[0], kb[0]
    bt = np.asarray([r[0] for r in bwd], float)
    out = []
    for t, bf, sf in fwd:
        j = int(np.argmin(np.abs(bt - t))) if len(bt) else None
        bb = bwd[j][1] if j is not None and abs(bt[j] - t) < 0.06 else None
        w = min(1.0, max(0.0, (t - ta) / max(1e-9, tb - ta)))
        if bf is not None and bb is not None:
            if iou(bf, bb) >= 0.2:
                box = [(1 - w) * bf[c] + w * bb[c] for c in range(4)]
            else:
                box = bf if w < 0.5 else bb
        elif bf is not None:
            box = bf
        elif bb is not None:
            box = bb
        else:
            box = [ka[c] + w * (kb[c] - ka[c]) for c in range(1, 5)]
        out.append((t, box, sf))
    return out


def _spans(ts, step):
    out = []
    for t in ts:
        if out and t - out[-1][1] <= step * 1.5:
            out[-1][1] = t
        else:
            out.append([t, t])
    return [[_r(a), _r(b + step)] for a, b in out]


def saved_tracks(path, info, given=()):
    """Saved letitedit_track results for this file (formats._track_runs: the tracker's folder and any given
    results or JSON files): [(t0, t1, rows px, file)]."""
    import letitedit.timeline.formats as formats
    s = dict(formats.REFRAME_DEFAULTS)
    W, H = info['display']
    out = []
    for a, b, frames, src in formats._track_runs(path, s, given or ()):
        rows = [[float(r[0]), float(r[1]) * W, float(r[2]) * H, float(r[3]) * W, float(r[4]) * H,
                 float(r[5]) if len(r) > 5 else 1.0] for r in frames]
        out.append((a, b, rows, src))
    return out


# ============================================================================ subjects on the solve grid

def _resample(src_t, src_b, grid, max_gap):
    """Boxes known at src_t (None where absent) on the grid times: linear between known ones no more than
    max_gap apart, the nearest within max_gap / 2 at the ends; NaN rows where absent."""
    out = np.full((len(grid), 4), np.nan)
    if not len(src_t):
        return out
    st = np.asarray(src_t, float)
    known = [b is not None for b in src_b]
    for i, t in enumerate(grid):
        j = int(np.searchsorted(st, t))
        a, b = j - 1, j
        if 0 <= a < len(st) and b < len(st) and known[a] and known[b] and st[b] - st[a] <= max_gap + 1e-6:
            f = (t - st[a]) / max(1e-9, st[b] - st[a])
            out[i] = [src_b[a][c] + f * (src_b[b][c] - src_b[a][c]) for c in range(4)]
            continue
        cands = [x for x in (a, b) if 0 <= x < len(st) and known[x] and abs(st[x] - t) <= max_gap / 2 + 1e-6]
        if cands:
            x = min(cands, key=lambda x: abs(st[x] - t))
            out[i] = src_b[x][:4]
    return out


def _smooth_boxes(B, n):
    """Centred moving average of n samples over present stretches."""
    if n <= 1:
        return B
    out = B.copy()
    present = ~np.any(np.isnan(B), axis=1)
    h = n // 2
    for i in np.nonzero(present)[0]:
        a, b = max(0, i - h), min(len(B), i + h + 1)
        seg = B[a:b][present[a:b]]
        out[i] = seg.mean(0)
    return out


ALIASES = {'faces': 'face', 'person': 'face', 'speaker': 'face', 'hands': 'action', 'hand': 'action',
           'motion': 'action', 'work': 'action', 'tracked': 'track', 'centre': 'aim', 'center': 'aim'}
DEFAULT_SOURCES = ('face', 'action', 'track', 'aim')


def _norm_keep(keep):
    """keep entries -> (given specs [dict], named entries in order [('given', i) | ('name', text)])."""
    specs, names = [], []
    if isinstance(keep, (str, dict)):
        keep = [keep]
    for k in keep or []:
        if isinstance(k, (list, tuple)) and k and isinstance(k[0], (list, tuple)) and len(k[0]) == 4:
            # [box, label?, priority?] (box in 0-1 fractions; at = the range start unless a fourth item gives it)
            k = {'box': list(k[0]), 'label': k[1] if len(k) > 1 else None,
                 'priority': k[2] if len(k) > 2 else 'required', **({'at': k[3]} if len(k) > 3 else {})}
        if isinstance(k, dict):
            specs.append(dict(k))
            names.append(('given', len(specs) - 1))
        elif isinstance(k, str):
            names.append(('name', k.strip().lower()))
        else:
            raise ValueError(f'keep entry {k!r}: a name (face, hands/action, a given label), {{label, box, at}} or '
                             '[box, label, priority]')
    return specs, names


def subjects_for(path, info, t0, t1, grid_src, keep=None, priorities=None, sources=None, settings=None,
                 notes=None, track_given=(), out_size=None):
    """Every subject of a clip range on the solve grid (source seconds `grid_src`), with priority and rank.
    Returns (subjects, extras) - extras: {'cuts': [source s], 'action': raw motion data}."""
    settings = settings or settings_of()
    notes = notes if notes is not None else []
    sources = [ALIASES.get(str(s).lower(), str(s).lower())
               for s in (DEFAULT_SOURCES if sources is None else sources)]
    specs, named = _norm_keep(keep)
    W, H = info['display']
    grid_src = np.asarray(grid_src, float)
    dt = float(grid_src[1] - grid_src[0]) if len(grid_src) > 1 else 0.1
    subjects, extras = [], {'cuts': []}
    given_raw = []
    for i, spec in enumerate(specs):
        label = str(spec.get('label') or f'given {i + 1}')
        g = given_subject(path, info, spec, t0, t1, settings)
        given_raw.append(g)
        B = _resample(g['times'], g['boxes'], grid_src, 0.35)
        subjects.append({'id': _uid(label, subjects), 'label': label, 'kind': 'given',
                         'priority': spec.get('priority', 'required'), 'box': B, 'source': g['how'],
                         'lost': g['lost'], 'order': ('given', i), 'given': True})
    if 'track' in sources:
        for a, b, rows, src in saved_tracks(path, info, track_given):
            if b < t0 or a > t1:
                continue
            tt = [r[0] for r in rows]
            bb = [r[1:5] if r[5] >= 0.3 else None for r in rows]
            B = _resample(tt, bb, grid_src, 0.35)
            if np.all(np.isnan(B)):
                continue
            subjects.append({'id': _uid('tracked', subjects), 'label': 'tracked', 'kind': 'track',
                             'priority': 'required', 'box': _smooth_boxes(B, 3), 'source': f'saved track {src}',
                             'order': ('track', len(subjects))})
    heads = []
    if 'face' in sources:
        fd = find_faces(path, t0, t1, info, settings)
        if fd.get('note'):
            notes.append(fd['note'])
        for j, tr in enumerate(fd['tracks']):
            heads.append((fd['times'], [head_box(b, W, H) if b is not None else None for b in tr['boxes']]))
            hb = [head_box(b, W, H) if b is not None else None for b in tr['boxes']]
            B = _resample(fd['times'], hb, grid_src, 0.45)
            B = _smooth_boxes(B, max(1, int(round(0.4 / dt))) | 1)
            if np.all(np.isnan(B)):
                continue
            label = 'face' if j == 0 else f'face {j + 1}'
            subjects.append({'id': _uid(label, subjects), 'label': label, 'kind': 'face', 'priority': 'required',
                             'box': B, 'source': f'YuNet faces at {settings["face_hz"]:g}/s ({tr["hits"]} detections)',
                             'order': ('face', j)})
    if 'action' in sources:
        ad = find_action(path, t0, t1, info, settings, exclude=heads)
        extras['cuts'] = list(ad.get('cuts') or [])
        bb = []
        for b, e, sp in zip(ad['boxes'], ad['energy'], ad['spread']):
            ok = b is not None and e >= float(settings['action_min']) and sp <= float(settings['action_max_area'])
            bb.append(b if ok else None)
        B = _resample(ad['times'], bb, grid_src, 0.35)
        B = _smooth_boxes(B, max(1, int(round(0.5 / dt))) | 1)
        if not np.all(np.isnan(B)):
            subjects.append({'id': _uid('action', subjects), 'label': 'action', 'kind': 'action',
                             'priority': 'optional', 'box': B,
                             'source': f'motion with the camera taken out at {settings["action_hz"]:g}/s',
                             'order': ('action', 0)})
        extras['action'] = ad
        # a given subject the tracker lost is carried along with the camera's motion for a while
        for subj_, g in zip([s for s in subjects if s.get('given')], given_raw):
            if not g['lost']:
                continue
            boxes2, carried = carry_with_camera(g['times'], g.get('raw') or g['boxes'], ad['times'],
                                                ad.get('cams') or [], W, H, float(settings['carry_lost_s']))
            boxes2 = [b2 if b2 is not None else b1 for b1, b2 in zip(g['boxes'], boxes2)]
            if carried:
                subj_['box'] = _resample(g['times'], boxes2, grid_src, 0.35)
                subj_['carried_s'] = _r(len(carried) / float(settings['track_hz']), 2)
                subj_['source'] += f"; {subj_['carried_s']:g} s carried with the camera where the tracker lost it"
    unknown = [s for s in sources if s not in ('face', 'action', 'track', 'given', 'aim')]
    if unknown:
        notes.append(f'unknown subject source(s) {unknown}; sources: face, action, track, aim')
    for s_ in subjects:
        # only the part of a subject inside the picture can be kept in a crop
        B = s_['box']
        ok = ~np.any(np.isnan(B), axis=1)
        B[ok, 0] = np.clip(B[ok, 0], 0, W)
        B[ok, 2] = np.clip(B[ok, 2], 0, W)
        B[ok, 1] = np.clip(B[ok, 1], 0, H)
        B[ok, 3] = np.clip(B[ok, 3], 0, H)
        gone = ok & ((B[:, 2] - B[:, 0] < 2) | (B[:, 3] - B[:, 1] < 2))
        B[gone] = np.nan
    _rank(subjects, named, priorities, notes)
    if 'aim' in sources and out_size:
        # where the camera was aimed: the picture's middle, half the crop's size - kept (preferred) at moments when
        # no required subject is in the picture, so the crop rests there instead of chasing stray motion
        ww, wh = max_window(W, H, out_size[0], out_size[1])
        aw, ah = 0.5 * ww, 0.5 * wh
        req_present = np.zeros(len(grid_src), bool)
        for s_ in subjects:
            if s_['priority'] == 'required':
                req_present |= ~np.any(np.isnan(s_['box']), axis=1)
        B = np.full((len(grid_src), 4), np.nan)
        B[~req_present] = [W / 2 - aw / 2, H / 2 - ah / 2, W / 2 + aw / 2, H / 2 + ah / 2]
        if (~req_present).any():
            subjects.append({'id': _uid('aim', subjects), 'label': 'aim', 'kind': 'aim', 'priority': 'preferred',
                             'rank': len(subjects) + 1, 'box': B,
                             'source': "the picture's middle (half a crop), where no required subject is in view"})
            for key, pr in (priorities or {}).items():
                if str(key).lower() in ('aim', 'centre', 'center'):
                    subjects[-1]['priority'] = pr
    for s in subjects:
        if s['priority'] not in PRIORITIES:
            raise ValueError(f"priority of {s['label']!r} is {s['priority']!r}; use {', '.join(PRIORITIES)}")
    return subjects, extras


def _uid(label, subjects):
    base = re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-') or 'subject'
    used = {s['id'] for s in subjects}
    k, sid = 2, base
    while sid in used:
        sid = f'{base}-{k}'
        k += 1
    return sid


def _rank(subjects, named, priorities, notes):
    """Priorities and ranks. With `keep`: the named subjects keep their place in that order (given boxes as their
    entry says, default required; named automatic subjects required); the other found subjects are optional.
    Without `keep`: given > tracked > faces > action; action (motion) is optional (where no required subject is
    in view the crop rests on the camera's aim and drifts towards motion when that is free), the rest required.
    `priorities` (by id, label or kind) overrides either."""
    if named:
        order = []
        for how, v in named:
            if how == 'given':
                hit = [s for s in subjects if s.get('order') == ('given', v)]
            else:
                v2 = ALIASES.get(v, v)
                hit = [s for s in subjects if s['id'] == v or s['label'].lower() == v or s['kind'] == v2]
                if not hit:
                    notes.append(f"keep {v!r}: nothing like it was found in this clip (subjects: "
                                 f"{', '.join(s['label'] for s in subjects) or 'none'})")
                for s in hit:
                    s['priority'] = 'required'
            for s in hit:
                if s not in order:
                    order.append(s)
        for s in subjects:
            if s not in order:
                s['priority'] = 'optional'
        rest = [s for s in subjects if s not in order]
        for i, s in enumerate(order + rest):
            s['rank'] = i + 1
    else:
        pri = {'given': 0, 'track': 1, 'face': 2, 'action': 3}
        for i, s in enumerate(sorted(subjects, key=lambda s: (pri.get(s['kind'], 9), s['order'][1]))):
            s['rank'] = i + 1
    for key, p in (priorities or {}).items():
        k2 = ALIASES.get(str(key).lower(), str(key).lower())
        hit = [s for s in subjects if s['id'] == key or s['label'].lower() == str(key).lower() or s['kind'] == k2]
        if not hit:
            notes.append(f'priorities: no subject {key!r} in this clip')
        for s in hit:
            s['priority'] = p


# ============================================================================ one clip: subjects -> path -> keys

def _grid(clip_len, settings):
    hz = float(settings['solve_hz'])
    if clip_len * hz > int(settings['max_samples']):
        hz = int(settings['max_samples']) / clip_len
    n = max(2, int(math.floor(clip_len * hz + 1e-6)) + 1)
    g = np.linspace(0.0, clip_len, n) if clip_len > 0 else np.zeros(2)
    return g


def boxes_at(B, grid, t):
    """A subject's box at time t from its grid boxes: linear between present neighbours, else None."""
    j = int(np.searchsorted(grid, t))
    if j <= 0:
        b = B[0]
        return None if np.any(np.isnan(b)) else b
    if j >= len(grid):
        b = B[-1]
        return None if np.any(np.isnan(b)) else b
    a, c = B[j - 1], B[j]
    if np.any(np.isnan(a)) or np.any(np.isnan(c)):
        x = j - 1 if t - grid[j - 1] < grid[j] - t else j
        b = B[x]
        return None if np.any(np.isnan(b)) else b
    f = (t - grid[j - 1]) / max(1e-9, grid[j] - grid[j - 1])
    return a + f * (c - a)


def coverage(rendered, subjects, grid, fps, src, out, safe, path=None, panel=None, frames=None):
    """Per subject, over the frames it is present: the share fully inside the crop as rendered, inside the
    uncovered area (platform), and for required subjects how the frames outside split between moments it could
    not fit with higher-ranked subjects and moments the path missed it (solver error)."""
    W, H = src
    ow, oh = out
    fx0, fy0, fx1, fy1 = safe
    n = len(rendered)
    res = {}
    wins = np.array([window_of_rect(r, W, H, ow, oh, panel) for r in rendered])
    for s in subjects:
        tot = inn = ins = missed = cant = 0
        out_frames = []
        for f in (range(n) if frames is None else [f for f in frames if 0 <= f < n]):
            t = f / fps
            b = boxes_at(s['box'], grid, t)
            if b is None:
                continue
            tot += 1
            w = wins[f]
            ok = inside(b, w, tol=0.5)
            ww_, wh_ = w[2] - w[0], w[3] - w[1]
            sw = [w[0] + fx0 * ww_, w[1] + fy0 * wh_, w[0] + fx1 * ww_, w[1] + fy1 * wh_]
            inn += ok
            ins += ok and inside(b, sw, tol=0.5)
            if not ok:
                out_frames.append(f)
                if s['priority'] == 'required' and path is not None:
                    k = int(np.clip(np.searchsorted(grid, t), 0, len(grid) - 1))
                    if s['id'] in path['left'][k]:
                        cant += 1
                    else:
                        missed += 1
        row = {'label': s['label'], 'kind': s['kind'], 'priority': s['priority'], 'rank': s.get('rank'),
               'present_frames': tot, 'in_frame': _r(inn / tot, 4) if tot else None}
        if safe != (0.0, 0.0, 1.0, 1.0):
            row['in_uncovered_area'] = _r(ins / tot, 4) if tot else None
        if s['priority'] == 'required' and tot:
            row['out_cant_fit'] = _r(cant / tot, 4)
            row['out_missed'] = _r(missed / tot, 4)
        res[s['id']] = row
    return res


def smoothness(rendered, fps, cut_frames=()):
    """How the picture moves on screen (output pixels), from the per-frame rects as rendered: speed and
    acceleration of the picture, zoom speed, share of time held still, number of moves. A jump at one of the
    clip's own cuts (cut_frames: the first frame after each) is counted apart, not as motion."""
    r = np.asarray(rendered, float)
    if len(r) < 3:
        return {'max_speed_px_s': 0.0, 'max_accel_px_s2': 0.0, 'hold_share': 1.0, 'moves': 0, 'cut_jumps': 0}
    cx = r[:, 0] + r[:, 2] / 2
    cy = r[:, 1] + r[:, 3] / 2
    v = np.column_stack([np.diff(cx), np.diff(cy)]) * fps
    jumps = 0
    for f in cut_frames:
        if 1 <= f < len(r):
            if np.hypot(*v[f - 1]) > 2.0:
                jumps += 1
            v[f - 1] = v[f - 2] if f >= 2 else 0.0     # the jump itself is not motion
    sp = np.hypot(v[:, 0], v[:, 1])
    a = np.diff(v, axis=0) * fps
    am = np.hypot(a[:, 0], a[:, 1])
    k = max(1, int(round(0.2 * fps)))
    vs = np.column_stack([np.convolve(v[:, i], np.ones(k) / k, 'same') for i in range(2)])
    a_s = np.hypot(*(np.diff(vs, axis=0) * fps).T)[k:-k] if len(vs) > 2 * k + 1 else np.zeros(1)
    zoom = np.abs(np.diff(np.log(np.maximum(r[:, 2], 1e-6)))) * fps
    still = sp < 2.0
    moves = sum(1 for v_, a_, b_ in _runs(list(~still)) if v_ and (b_ - a_) / fps >= 0.2)
    return {'max_speed_px_s': _r(sp.max(), 1), 'p95_speed_px_s': _r(np.percentile(sp, 95), 1),
            'max_accel_px_s2': _r(am.max(), 1), 'p99_accel_px_s2': _r(np.percentile(am, 99), 1),
            'max_accel_0.2s_px_s2': _r(a_s.max() if a_s.size else 0.0, 1),
            'max_zoom_per_s': _r(zoom.max(), 4), 'hold_share': _r(still.mean(), 3), 'moves': int(moves),
            'cut_jumps': jumps}


def cant_fit_spans(path, subjects, grid, settings, src_of=None, timeline_of=None):
    """Moments where required subjects can't share one crop: [{'clip': [a, b], 'source', 'timeline', 'left_out',
    'kept', 'why', 'brief'}]; spans closer than min_span_s are merged."""
    left = path['left']
    n = len(grid)
    dt = float(grid[1] - grid[0]) if n > 1 else 0.1
    flags = [bool(x) for x in left]
    spans = []
    for v, a, b in _runs(flags):
        if v:
            spans.append([a, b])
    merged = []
    gap = float(settings['min_span_s'])
    for a, b in spans:
        if merged and (grid[a] - grid[merged[-1][1] - 1]) <= gap + dt:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    by_id = {s['id']: s for s in subjects}
    out = []
    ww, wh = path['ww'], path['wh']
    smax = 1.0 / settings['zoom'][0]
    for a, b in merged:
        lo = set().union(*[left[k] for k in range(a, b)])
        kept = set().union(*[path['kept'][k] for k in range(a, b)]) - lo
        t0, t1 = float(grid[a]), float(grid[min(b, n - 1)]) if b < n else float(grid[-1]) + dt
        t1 = min(t1, float(grid[-1]))
        # how much bigger than the crop the required subjects are together, at the worst moment
        worst = 0.0
        for k in range(a, b):
            req = [by_id[i]['box'][k] for i in (path['kept'][k] | left[k]) if i in by_id
                   and not np.any(np.isnan(by_id[i]['box'][k]))]
            u = union(req)
            if u is not None:
                worst = max(worst, box_w(u) / (ww * smax), box_h(u) / (wh * smax))
        names = sorted(by_id[i]['label'] for i in lo if i in by_id)
        row = {'clip': [_r(t0), _r(t1)], 'left_out': names,
               'kept': sorted(by_id[i]['label'] for i in kept if i in by_id),
               'why': _why(names + sorted(by_id[i]['label'] for i in kept if i in by_id), worst),
               'brief': (t1 - t0) < float(settings['min_span_s'])}
        if src_of:
            row['source'] = [_r(src_of(t0)), _r(src_of(t1))]
        if timeline_of:
            row['timeline'] = [_r(timeline_of(t0)), _r(timeline_of(t1))]
        out.append(row)
    return out


def _why(names, worst):
    if not worst:
        return 'they do not fit together'
    if len(names) == 1:
        return f'{names[0]} alone is {worst:.2f} x the largest crop'
    return f"{' + '.join(names)} together need {worst:.2f} x the largest crop"


def solve_clip(path, src_in, src_out, out_size, fps, speed=1.0, keep=None, priorities=None, sources=None,
               platform=None, settings=None, cuts=None, panel=None, subjects=None, extras=None, keep_out=None,
               track_given=()):
    """Plan the crop of one clip (source [src_in, src_out] seconds of `path`, playing at `speed`) for an output
    of out_size at fps. Returns everything about it: subjects, path samples, keys (the size_position effect),
    per-frame rects as rendered, coverage, smoothness, can't-fit spans, notes."""
    settings = settings or settings_of()
    info = media(path)
    W, H = info['display']
    out_w, out_h = out_size
    if speed <= 0:
        raise Unsupported('reversed clips are not supported')
    clip_len = (src_out - src_in) / speed
    if clip_len <= 0:
        raise ValueError('the clip has no length')
    n_frames = max(2, int(round(clip_len * fps)))
    grid = _grid(clip_len, settings)
    grid_src = src_in + grid * speed
    notes = []
    if subjects is None:
        subjects, extras = subjects_for(path, info, src_in, src_out, grid_src, keep, priorities, sources, settings,
                                        notes, track_given, out_size=(panel[2], panel[3]) if panel else out_size)
    extras = extras or {}
    pw, ph = (panel[2], panel[3]) if panel else (out_w, out_h)
    safe, znotes = safe_area(platform, pw, ph) if not panel else ((0.0, 0.0, 1.0, 1.0), [])
    notes += znotes
    cut_src = list(extras.get('cuts') or []) + [float(c) for c in (cuts or [])]
    breaks = sorted({int(np.searchsorted(grid_src, c)) for c in cut_src if src_in < c < src_out})
    p = solve_path(grid, subjects, (W, H), (pw, ph), settings, breaks, safe, keep_out=keep_out)
    rects = np.array([rect_for(cx, cy, sc, W, H, out_w, out_h, panel) for cx, cy, sc in zip(p['cx'], p['cy'], p['s'])])
    keys, rendered, dev = keys_from_path(grid, rects, fps, n_frames, settings['ease'],
                                         float(settings['key_tolerance_px']))
    cov = coverage(rendered, subjects, grid, fps, (W, H), (out_w, out_h), safe, p, panel)
    clip_cuts = [int(round((c - src_in) / speed * fps)) for c in cut_src if src_in < c < src_out]
    sm = smoothness(rendered, fps, clip_cuts)
    spans = cant_fit_spans(p, subjects, grid, settings, src_of=lambda t: src_in + t * speed)
    effect = {'size_position': keys if isinstance(keys, str) else {'keys': keys}}
    return {'file': str(path), 'info': info, 'source_range': [_r(src_in, 4), _r(src_out, 4)], 'speed': speed,
            'clip_len': clip_len, 'fps': fps, 'n_frames': n_frames, 'out': [out_w, out_h], 'panel': panel,
            'grid': grid, 'grid_src': grid_src, 'subjects': subjects, 'path': p, 'rects': rects, 'keys': keys,
            'rendered': rendered, 'key_deviation_px': _r(dev, 2), 'effect': effect, 'coverage': cov,
            'smoothness': sm, 'cant_fit': spans, 'safe': safe, 'cuts': [c for c in cut_src if src_in < c < src_out],
            'notes': notes, 'extras': extras, 'settings': settings}


def subject_summary(subjects, grid):
    out = []
    for s in subjects:
        present = ~np.any(np.isnan(s['box']), axis=1)
        row = {'id': s['id'], 'label': s['label'], 'kind': s['kind'], 'priority': s['priority'], 'rank': s.get('rank'),
               'present': _r(present.mean(), 3), 'from': s.get('source')}
        if s.get('lost'):
            row['lost_source_s'] = s['lost'][:12]
        if s.get('carried_s'):
            row['carried_with_camera_s'] = s['carried_s']
        out.append(row)
    return out


# ============================================================================ offers: split and inset

def _inset_rect(corner, out_w, out_h, safe, size=0.42, aspect=0.8):
    """The inset panel for a corner ('top_left', 'top_right', 'bottom_left', 'bottom_right'), size = share of
    the frame's width (of its height for a wide frame), aspect w / h, kept inside the uncovered area."""
    fx0, fy0, fx1, fy1 = safe
    m = 0.035 * min(out_w, out_h)
    if out_w <= out_h:
        w = size * out_w
        h = w / aspect
    else:
        h = size * out_h
        w = h * aspect
    w, h = round(w / 2) * 2, round(h / 2) * 2
    x = fx0 * out_w + m if 'left' in corner else fx1 * out_w - m - w
    y = fy0 * out_h + m if 'top' in corner else fy1 * out_h - m - h
    return (float(round(x)), float(round(y)), float(w), float(h))


def _subset(subjects, ids, prio='required', others='ignore', keep_kinds=()):
    """Copies of the subjects: those in ids get `prio` (ranked as given), the others `others`; subjects of the
    kinds in keep_kinds (e.g. 'aim') keep their own priority."""
    out = []
    for s in subjects:
        c = dict(s)
        if s['id'] in ids:
            c['priority'] = prio
            c['rank'] = ids.index(s['id']) + 1
        elif s['kind'] in keep_kinds:
            pass
        else:
            c['priority'] = others
        out.append(c)
    return out


def _span_mask(grid, spans, pad):
    m = np.zeros(len(grid), bool)
    for a, b in spans:
        m |= (grid >= a - pad) & (grid <= b + pad)
    return m


def _scope_spans(res, settings, scope):
    """The clip-time spans an offer covers: the can't-fit spans where some required subjects are kept and others
    left out (a split or an inset can show both groups; a single subject bigger than the crop is not helped by
    either), padded and merged; the whole clip when scope is 'item' or the spans cover nearly all of it."""
    L = res['clip_len']
    spans = [s['clip'] for s in res['cant_fit'] if not s['brief'] and s['kept'] and s['left_out']]
    if not spans:
        return []
    pad = float(settings['span_pad_s'])
    merged = []
    for a, b in sorted(spans):
        a, b = max(0.0, a - pad), min(L, b + pad)
        if merged and a <= merged[-1][1] + 1.0:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    covered = sum(b - a for a, b in merged)
    if scope == 'item' or covered > 0.85 * L:
        return [[0.0, L]]
    return [[_r(a, 4), _r(b, 4)] for a, b in merged if b - a >= 0.8]


def _mix_keys(base, alt, mask, fps, n_frames, ease):
    """Keys for a clip that shows `base` (a solve_clip result) outside the masked frames and `alt` inside: a
    cut-like switch of layout at each edge (a hold key on the last frame before it; the keys next to a switch are
    linear so neither layout bends towards the other). Returns (keys, per-frame rects as rendered)."""
    want = np.where(mask[:, None], alt['rendered'], base['rendered'])

    def key_frames(r):
        if isinstance(r['keys'], str):
            return {0, n_frames - 1}
        return {min(n_frames - 1, int(round(k[0] * fps))) for k in r['keys']}
    frames = {f for f in key_frames(base) if not mask[f]} | {f for f in key_frames(alt) if mask[f]} | {0, n_frames - 1}
    edges = set(np.nonzero(np.diff(mask.astype(int)))[0].tolist())
    for e in edges:
        frames |= {e, e + 1}
    frames = sorted(f for f in frames if 0 <= f < n_frames)
    near = set()
    for e in edges:
        before = [f for f in frames if f < e]
        if before:
            near.add(before[-1])
        near.add(e + 1)
    keys = []
    for f in frames:
        kind = 'hold' if f in edges else 'linear' if f in near else ease
        keys.append([round(f / fps, 4), _rect_text(want[f]), kind])
    return keys, eval_keys(keys, fps, n_frames)


def offers_for(res, settings, kinds=('split', 'inset'), scope='spans', platform=None):
    """Split and inset layouts for a clip whose required subjects can't share one crop. Each offer: {'kind',
    'spans' (clip seconds), 'main_effect' (the clip's own Size/Position), 'copy' {in, out, at_clip, effects},
    'panels', 'coverage', 'note'}; None when nothing needs it."""
    spans = _scope_spans(res, settings, scope)
    if not spans:
        return {}
    W, H = res['info']['display']
    out_w, out_h = res['out']
    fps = res['fps']
    grid = res['grid']
    subjects = res['subjects']
    by_id = {s['id']: s for s in subjects}
    req = sorted([s for s in subjects if s['priority'] == 'required'], key=lambda s: s['rank'])
    left_ids = set()
    for sp in res['cant_fit']:
        if not sp['brief'] and sp['kept'] and sp['left_out']:
            left_ids |= {s['id'] for s in subjects if s['label'] in sp['left_out']}
    kept_ids = [s['id'] for s in req if s['id'] not in left_ids]
    left_list = [s['id'] for s in req if s['id'] in left_ids]
    if not kept_ids:
        kept_ids, left_list = left_list[:1], left_list[1:]
    if not left_list:
        return {}
    n_frames = res['n_frames']
    span_mask_g = _span_mask(grid, spans, 0.0)
    frame_t = np.arange(n_frames) / fps
    span_mask_f = _span_mask(frame_t, spans, 0.0)
    out = {}
    src_in = res['source_range'][0]
    speed = res['speed']

    def path_in(panel, ids, keep_out=None):
        sub = _subset(subjects, ids)
        r = solve_clip(res['file'], res['source_range'][0], res['source_range'][1], (out_w, out_h), fps, speed,
                       settings=settings, panel=panel, subjects=sub, extras={'cuts': res['cuts']},
                       keep_out=keep_out)
        return r

    if 'split' in kinds:
        # which group goes where: by where they sit in the source (the upper one above / the left one left)
        def centre(ids, axis):
            vals = []
            for i in ids:
                B = by_id[i]['box'][span_mask_g]
                B = B[~np.any(np.isnan(B), axis=1)]
                if len(B):
                    vals.append(np.median((B[:, axis] + B[:, axis + 2]) / 2))
            return float(np.mean(vals)) if vals else 0.0
        def need(ids, pw, ph):
            """How much bigger than a panel's largest crop each group gets (worst moment in the spans)."""
            ww_, wh_ = max_window(W, H, pw, ph)
            worst = 0.0
            for k in np.nonzero(span_mask_g)[0]:
                u = union([by_id[i]['box'][k] for i in ids if not np.any(np.isnan(by_id[i]['box'][k]))])
                if u is not None:
                    worst = max(worst, box_w(u) / ww_, box_h(u) / wh_)
            return worst
        h2, w2 = out_h // 2, out_w // 2
        stacked = max(need(kept_ids, out_w, h2), need(left_list, out_w, h2))
        side = max(need(kept_ids, w2, out_h), need(left_list, w2, out_h))
        # the halves separate the groups along the axis they are apart on (one above the other: stacked), unless
        # the groups only fit the other way
        apart_y = abs(centre(kept_ids, 1) - centre(left_list, 1)) / H
        apart_x = abs(centre(kept_ids, 0) - centre(left_list, 0)) / W
        prefer_stacked = apart_y >= apart_x
        if prefer_stacked:
            use_stacked = stacked <= 1.0 or (side > 1.0 and stacked <= side)
        else:
            use_stacked = not (side <= 1.0 or (stacked > 1.0 and side <= stacked))
        if use_stacked:
            p1, p2, how = (0.0, 0.0, float(out_w), float(h2)), (0.0, float(h2), float(out_w), float(out_h - h2)), 'stacked'
        else:
            p1, p2, how = (0.0, 0.0, float(w2), float(out_h)), (float(w2), 0.0, float(out_w - w2), float(out_h)), 'side by side'
        axis = 1 if how == 'stacked' else 0
        a_ids, b_ids = (kept_ids, left_list) if centre(kept_ids, axis) <= centre(left_list, axis) else (left_list, kept_ids)
        ra = path_in(p1, a_ids)
        rb = path_in(p2, b_ids)
        # the clip itself carries panel b (and the single crop outside the spans); a muted copy above carries a
        main_keys, main_r = _mix_keys(res, rb, span_mask_f, fps, n_frames, settings['ease'])
        copies = []
        for a, b in spans:
            fa, fb = int(round(a * fps)), min(n_frames, int(round(b * fps)))
            ka, rr, _ = keys_from_path(ra['grid'][(ra['grid'] >= a - 1e-6) & (ra['grid'] <= b + 1e-6)] - a,
                                       ra['rects'][(ra['grid'] >= a - 1e-6) & (ra['grid'] <= b + 1e-6)],
                                       fps, max(2, fb - fa), settings['ease'], float(settings['key_tolerance_px']))
            copies.append({'clip_span': [a, b], 'source': [_r(src_in + a * speed, 4), _r(src_in + b * speed, 4)],
                           'effects': ['mute', {'size_position': ka if isinstance(ka, str) else {'keys': ka}},
                                       {'filter': 'Crop: Rectangle',
                                        'params': {'rect': _rect_text(p1), 'color': '#00000000', 'radius': 0}}]})
        span_frames = np.nonzero(span_mask_f)[0]
        cov = _offer_cov(res, {sid: ra for sid in a_ids} | {sid: rb for sid in b_ids}, span_frames, by_id)
        out['split'] = {'kind': 'split', 'layout': how, 'spans': spans,
                        'panels': {'copy': [round(v) for v in p1], 'clip': [round(v) for v in p2]},
                        'fit': {'stacked': _r(stacked, 2), 'side by side': _r(side, 2)},
                        'in_copy': [by_id[i]['label'] for i in a_ids], 'in_clip': [by_id[i]['label'] for i in b_ids],
                        'main_effect': {'size_position': {'keys': main_keys}}, 'copies': copies,
                        'coverage_in_spans': cov, 'smoothness': {'copy': ra['smoothness'], 'clip': rb['smoothness']}}
    if 'inset' in kinds:
        safe = res['safe']
        best = None
        # the corner the kept subjects use least (in the single-crop render, over the spans)
        for corner in ('top_right', 'top_left', 'bottom_right', 'bottom_left'):
            rect = _inset_rect(corner, out_w, out_h, safe)
            hit = 0.0
            for f in np.nonzero(span_mask_f)[0][::max(1, int(fps // 5))]:
                k = window_of_rect(res['rendered'][f], W, H, out_w, out_h)
                sc = out_w / (k[2] - k[0])
                for sid in kept_ids:
                    b = boxes_at(by_id[sid]['box'], grid, f / fps)
                    if b is None:
                        continue
                    ob = [(b[0] - k[0]) * sc, (b[1] - k[1]) * sc, (b[2] - k[0]) * sc, (b[3] - k[1]) * sc]
                    ix = max(0.0, min(ob[2], rect[0] + rect[2]) - max(ob[0], rect[0]))
                    iy = max(0.0, min(ob[3], rect[1] + rect[3]) - max(ob[1], rect[1]))
                    hit += ix * iy / max(1.0, (ob[2] - ob[0]) * (ob[3] - ob[1]))
            if best is None or hit < best[0] - 1e-6:
                best = (hit, corner, rect)
        _, corner, rect = best
        # the main crop's subjects are nudged clear of the inset (a band the height of the inset, weak)
        band = (0.0, (rect[1] + rect[3]) / out_h, 1.0, 1.0) if 'top' in corner else (0.0, 0.0, 1.0, rect[1] / out_h)
        # where the kept subjects are out of view the main crop still has the others (optional) and the aim to go by
        main = solve_clip(res['file'], res['source_range'][0], res['source_range'][1], (out_w, out_h), fps, speed,
                          settings=settings, subjects=_subset(subjects, kept_ids, others='optional', keep_kinds=('aim',)),
                          extras={'cuts': res['cuts']}, keep_out={'band': band, 'samples': span_mask_g},
                          platform=platform)
        ri = path_in(rect, left_list)
        main_keys, _ = _mix_keys(res, main, span_mask_f, fps, n_frames, settings['ease'])
        copies = []
        for a, b in spans:
            fa, fb = int(round(a * fps)), min(n_frames, int(round(b * fps)))
            sel = (ri['grid'] >= a - 1e-6) & (ri['grid'] <= b + 1e-6)
            ka, _, _ = keys_from_path(ri['grid'][sel] - a, ri['rects'][sel], fps, max(2, fb - fa), settings['ease'],
                                      float(settings['key_tolerance_px']))
            copies.append({'clip_span': [a, b], 'source': [_r(src_in + a * speed, 4), _r(src_in + b * speed, 4)],
                           'effects': ['mute', {'size_position': ka if isinstance(ka, str) else {'keys': ka}},
                                       {'filter': 'Crop: Rectangle',
                                        'params': {'rect': _rect_text(rect), 'color': '#00000000',
                                                   'radius': 0.12}}]})
        span_frames = np.nonzero(span_mask_f)[0]
        cov = _offer_cov(res, {sid: main for sid in kept_ids} | {sid: ri for sid in left_list}, span_frames, by_id)
        out['inset'] = {'kind': 'inset', 'corner': corner, 'spans': spans, 'panels': {'copy (inset)': [round(v) for v in rect]},
                        'in_copy': [by_id[i]['label'] for i in left_list],
                        'in_clip': [by_id[i]['label'] for i in kept_ids],
                        'main_effect': {'size_position': {'keys': main_keys}}, 'copies': copies,
                        'coverage_in_spans': cov, 'smoothness': {'copy': ri['smoothness'], 'clip': main['smoothness']}}
    return out


def _offer_cov(res, where, frames, by_id):
    """Per required subject, over the offer's frames: the share fully shown by the single crop and by the offer
    (in the panel that carries it)."""
    out = {}
    for sid, r in where.items():
        subj = by_id[sid]
        single = coverage(res['rendered'], [subj], res['grid'], res['fps'], tuple(res['info']['display']), res['out'],
                          res['safe'], None, None, frames)[sid]
        sub2 = next(s for s in r['subjects'] if s['id'] == sid)
        off = coverage(r['rendered'], [sub2], r['grid'], r['fps'], tuple(r['info']['display']), r['out'],
                       (0.0, 0.0, 1.0, 1.0), None, r['panel'], frames)[sid]
        out[subj['label']] = {'frames_seen': single['present_frames'], 'single_crop': single['in_frame'],
                              'offer': off['in_frame']}
    return out


def offer_ops(item_id, offer, file, timeline_start, other_effects, speed=1.0):
    """The edit ops of an offer for item `item_id` (letitedit_timeline_apply vocabulary)."""
    track = SPLIT_TRACK if offer['kind'] == 'split' else INSET_TRACK
    ops = [{'op': 'effects', 'id': item_id, 'effects': [offer['main_effect']] + list(other_effects)},
           {'op': 'add_track', 'name': track, 'kind': 'video'}]
    for j, c in enumerate(offer['copies']):
        item = {'id': f"{item_id}-{offer['kind']}{'' if len(offer['copies']) == 1 else j + 1}", 'clip': file,
                'in': c['source'][0], 'out': c['source'][1], 'effects': c['effects']}
        if abs(speed - 1.0) > 1e-9:
            item['speed'] = speed
        ops.append({'op': 'insert', 'track': track, 'at': round(timeline_start + c['clip_span'][0], 4), 'item': item,
                    'overlap': 'next_track'})
    return ops


# ============================================================================ project items

REPLACED = ('size_position', 'zoom', 'blur_pad')        # effects the reframe takes the place of


def _effect_word(e):
    return e if isinstance(e, str) else next(iter(e), None) if isinstance(e, dict) else None


def _item_check(doc, place, item):
    """None when the clip can be reframed, else why not (refused cases are listed, never guessed)."""
    import letitedit.pictures.annotate as annotate
    import letitedit.timeline.made as made
    prod = place['producer']
    if prod is None:
        return 'its media element is missing from the project'
    if prod.tag == 'tractor':
        return 'a nested timeline or transition, not a source clip'
    p = annotate._props(prod)
    if p.get('letitedit_ai:graphic'):
        return 'a graphic, not footage'
    if p.get(made.MADE_PROP):
        return 'a made clip (rendered file)'
    if p.get(made.FX_PROP):
        return 'plays through an ffmpeg effect graph (a rendered copy)'
    if p.get('mlt_service') == 'color':
        return 'a colour clip'
    if item.get('reverse') or float(p.get('warp_speed') or 1.0) < 0:
        return 'plays in reverse (its time runs backwards); reframe the forward clip, then reverse it'
    res = p.get('warp_resource') or p.get('resource') or ''
    if not res or not os.path.isfile(res):
        return f'its source file is missing ({res})'
    if Path(res).suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.webp', '.heic'):
        return 'a still picture (stills are not reframed by this tool yet; size_position places them)'
    for el in prod:
        if el.tag not in ('filter', 'link'):
            continue
        fp = annotate._props(el)
        svc = fp.get('mlt_service', '')
        if fp.get('_loader') == '1' or fp.get('disable') == '1' or fp.get('letitedit_ai:part'):
            continue
        if el.tag == 'link' and svc in ('timeremap',):
            return 'Time Remap changes its speed along the clip'
        if svc in annotate.GEOMETRY_UNSUPPORTED or svc.startswith(annotate.GEOMETRY_UNSUPPORTED_PREFIX):
            return f'the effect {annotate.GEOMETRY_UNSUPPORTED.get(svc, svc)} moves or warps the picture'
        if svc == 'crop' and fp.get('active') != '1':
            return 'it has Crop: Source; remove it (the reframe is a crop) or plan without it'
    return None


def _picture_shape(path):
    info = media(path)
    W, H = info['display']
    return W / H, info


def _timeline_start(item):
    import letitedit.timeline.edit_script as es
    return float(es.to_seconds(item.get('at', 0)))


# ============================================================================ plan

def _clips_to_reframe(all_items, places, doc, out_w, out_h, unsupported, warnings):
    """The clips to reframe when none are named: footage of another shape than the frame that can be reframed
    (the rest are listed in unsupported, with why)."""
    ids = []
    for iid, (t, it) in all_items.items():
        if 'clip' not in it or iid not in places:
            continue
        if not os.path.isfile(str(it['clip'])):
            unsupported.append({'item': iid, 'why': f"its source file is missing ({it['clip']})"})
            continue
        try:
            shape, _ = _picture_shape(it['clip'])
        except Unsupported as e:
            unsupported.append({'item': iid, 'why': str(e)})
            continue
        if abs(shape - out_w / out_h) / (out_w / out_h) <= 0.02:
            continue                         # already the frame's shape: nothing to crop
        why = _item_check(doc, places[iid], it)
        if why:
            unsupported.append({'item': iid, 'why': why})
            continue
        ids.append(iid)
    if not ids:
        warnings.append('no clip here has a picture of another shape than the frame; name items to reframe '
                        'them anyway (with zoom > 1)')
    return ids


def _cant_fit_and_warnings(items_out, warnings):
    """Every clip's stretches where the subjects can't share the crop, and warnings for subjects the tracker
    lost or required subjects partly out of the crop."""
    cant = []
    for rec in items_out:
        for sp in rec['cant_fit']:
            if not sp['brief']:
                cant.append({'item': rec['item_id'], **{k: v for k, v in sp.items() if k != 'brief'}})
        for su in rec['subjects']:
            lost = su.get('lost_source_s') or []
            secs = sum(b - a for a, b in lost)
            if su['kind'] == 'given' and secs >= 1.0:
                warnings.append(f"{rec['item_id']}: the tracker lost '{su['label']}' for {secs:.1f} s (source "
                                + ', '.join(f'{a:.1f}-{b:.1f}' for a, b in lost[:6]) + ('...' if len(lost) > 6 else '')
                                + "); boxes given there too (keep boxes [[t, x0, y0, x1, y1], ...]) keep it known")
        for sid, c in rec['coverage'].items():
            if c['priority'] == 'required' and c.get('in_frame') is not None and c['in_frame'] < 0.999:
                why = (f"{c['out_cant_fit']:.0%} where it can't share the crop with higher-ranked subjects"
                       if c.get('out_cant_fit') else '')
                miss = f"{c['out_missed']:.0%} missed by the path" if c.get('out_missed') else ''
                warnings.append(f"{rec['item_id']}: required '{c['label']}' is fully in the crop {c['in_frame']:.1%} "
                                f"of the frames it is seen ({'; '.join(x for x in (why, miss) if x)})")
    return cant


def plan(project=None, items=None, file=None, source_range=None, target=None, keep=None, priorities=None,
         sources=None, platform=None, settings=None, cuts=None, offers=('split', 'inset'), offer_scope='spans',
         preview=True, out_dir=None):
    """Plan reframing (nothing is written to the project). See letitedit_reframe for the arguments. Returns the
    plan dict (saved as WORK/plans/<plan_id>.json)."""
    import letitedit.timeline.edit_script as es
    t_start = time.time()
    st = settings_of(settings)
    warnings, unsupported = [], []
    items_out, changes, offer_map, fingerprints = [], [], {}, {}
    if offers in (None, False):
        offers = ()
    offers = tuple([offers] if isinstance(offers, str) else offers)
    bad = [o for o in offers if o not in ('split', 'inset')]
    if bad:
        raise ValueError(f"offers: {bad}; offers are 'split' and 'inset'")
    if offer_scope not in ('spans', 'item'):
        raise ValueError("offer_scope is 'spans' (only where they can't fit) or 'item' (the whole clip)")
    if project:
        import letitedit.pictures.annotate as annotate
        doc, path = annotate.load_doc(project)
        script = es.read(path)
        revision = script['base']
        out_w, out_h, fps = int(doc.width), int(doc.height), float(doc.fps)
        if target is not None:
            tw, th, _ = resolve_target(target)
            if abs(tw / th - out_w / out_h) > 0.01:
                raise ValueError(f'target {target} is not this project\'s shape ({out_w}x{out_h}); a project is '
                                 'reframed to its own frame - make a linked version at another size with '
                                 "letitedit_versions(reframe={'mode': 'solve', ...}) or plan a file with file=...")
        places = annotate.clip_places(doc)
        all_items = {it['id']: (t, it) for t in script['tracks'] if t.get('kind', 'video') == 'video'
                     for it in t['items'] if it.get('id') is not None and 'gap' not in it}
        if items:
            ids = [items] if isinstance(items, str) else list(items)
            missing = [i for i in ids if i not in all_items]
            if missing:
                raise ValueError(f"no clip {', '.join(missing)} on a video track (ids: "
                                 f"{', '.join(list(all_items)[:20])})")
        else:
            ids = _clips_to_reframe(all_items, places, doc, out_w, out_h, unsupported, warnings)
        for iid in ids:
            t, it = all_items[iid]
            place = places.get(iid)
            why = _item_check(doc, place, it) if place is not None and 'clip' in it else 'not a footage clip'
            if why:
                unsupported.append({'item': iid, 'why': why})
                continue
            a, b = float(es.to_seconds(it.get('in', 0))), float(es.to_seconds(it['out']))
            sp = float(it.get('speed', 1.0))
            given = _per_item(keep, iid)
            try:
                res = solve_clip(it['clip'], a, b, (out_w, out_h), fps, sp, given, _per_item(priorities, iid),
                                 sources, platform, st, _per_item(cuts, iid))
            except Unsupported as e:
                unsupported.append({'item': iid, 'why': str(e)})
                continue
            fingerprints[res['file']] = res['info']['fingerprint']
            start = _timeline_start(it)
            others = [e for e in (it.get('effects') or []) if _effect_word(e) not in REPLACED]
            replaced = [_effect_word(e) for e in (it.get('effects') or []) if _effect_word(e) in REPLACED]
            if replaced:
                warnings.append(f"{iid}: its {', '.join(replaced)} effect is replaced by the reframe")
            ch = [{'op': 'effects', 'id': iid, 'effects': [res['effect']] + others}]
            changes += ch
            rec = _item_record(iid, t['name'], res, start)
            rec['changes'] = ch
            if offers and any(not s['brief'] for s in res['cant_fit']):
                offs = offers_for(res, st, offers, offer_scope, platform)
                rec['offers'] = {}
                for kind, off in offs.items():
                    ops = offer_ops(iid, off, res['file'], start, others, sp)
                    summary = {k: v for k, v in off.items() if k not in ('main_effect', 'copies')}
                    summary['changes'] = ops
                    summary['timeline_spans'] = [[_r(start + a_), _r(start + b_)] for a_, b_ in off['spans']]
                    rec['offers'][kind] = summary
                offer_map[iid] = rec['offers']
            items_out.append(rec)
            items_out[-1]['_res'] = res
        mode, file_out = 'project', None
    else:
        if not file or source_range is None or target is None:
            raise ValueError('give project (reframe its clips to its frame) or file + source_range + target')
        out_w, out_h, tinfo = resolve_target(target)
        platform = platform or tinfo.get('platform')
        info = media(file)
        fps = float(info.get('fps') or 30.0) or 30.0
        fps = min(fps, 60.0)
        a, b = float(source_range[0]), float(source_range[1])
        if not (0 <= a < b):
            raise ValueError('source_range is [start, end] seconds of the file')
        b = min(b, float(info['duration'] or b))
        res = solve_clip(file, a, b, (out_w, out_h), fps, 1.0, keep, priorities, sources, platform, st, cuts)
        fingerprints[res['file']] = info['fingerprint']
        rec = _item_record('file', None, res, 0.0)
        rec['item'] = {'clip': str(file), 'in': _r(a, 4), 'out': _r(b, 4), 'effects': [res['effect']]}
        if offers and any(not s['brief'] for s in res['cant_fit']):
            offs = offers_for(res, st, offers, offer_scope, platform)
            rec['offers'] = {}
            for kind, off in offs.items():
                summary = {k: v for k, v in off.items() if k not in ('main_effect', 'copies')}
                summary['changes'] = offer_ops('<clip id>', off, str(file), 0.0, [], 1.0)
                rec['offers'][kind] = summary
            offer_map['file'] = rec['offers']
        rec['_res'] = res
        items_out.append(rec)
        revision, path, mode, file_out = None, None, 'file', str(file)
    safe, _ = safe_area(platform, out_w, out_h)
    pid_src = json.dumps([ENGINE, str(path) if path else file_out, revision, items, source_range, target, keep,
                          priorities, sources, platform, st, cuts, offers, offer_scope,
                          sorted(fingerprints.items())], sort_keys=True, default=str)
    plan_id = 'rf-' + hashlib.sha1(pid_src.encode()).hexdigest()[:10]
    cant = _cant_fit_and_warnings(items_out, warnings)
    plan = {'schema_version': SCHEMA, 'engine': ENGINE, 'plan_id': plan_id, 'result_id': plan_id, 'mode': mode,
            'project': str(path) if path else None, 'file': file_out, 'project_revision': revision,
            'source_fingerprints': fingerprints,
            'target': {'width': out_w, 'height': out_h, 'fps': fps, 'platform': platform,
                       'uncovered_area': list(safe)},
            'settings': st, 'items': [], 'changes': changes, 'offers': offer_map, 'cant_fit': cant,
            'checked_ranges': [], 'unchecked_ranges': [], 'warnings': warnings, 'unsupported': unsupported,
            'preview_artifacts': {}, 'made': _now(), 'seconds': None}
    work = Path(out_dir) if out_dir else WORK / plan_id
    work.mkdir(parents=True, exist_ok=True)
    if preview and items_out:
        try:
            _preview(plan, items_out, work, path)
        except Exception as e:  # noqa: BLE001 - a preview that can't render is reported, the plan still stands
            plan['warnings'].append(f'preview not made: {str(e)[:300]}')
            plan['unchecked_ranges'].append({'what': 'everything', 'why': f'preview failed: {str(e)[:120]}'})
    else:
        plan['unchecked_ranges'].append({'what': 'everything', 'why': 'preview=False: nothing rendered; coverage is '
                                         'from the engine keyframe arithmetic, not from rendered frames'})
    for rec in items_out:
        rec.pop('_res', None)
    plan['items'] = items_out
    plan['seconds'] = _r(time.time() - t_start, 1)
    _save_plan(plan)
    return plan


ENTRY_KEYS = ('box', 'boxes', 'label', 'at', 'priority', 'follow', 'units')


def _per_item(value, iid):
    """A setting given once for every clip, or per clip as {item id: value, '*': value for the rest}."""
    if isinstance(value, dict) and value and not (set(value) & set(ENTRY_KEYS)) and             all(isinstance(v, (list, tuple, dict)) or v is None for v in value.values()):
        return value.get(iid, value.get('*'))
    return value


def _item_record(iid, track, res, start):
    """What the plan says about one clip (no arrays)."""
    sm = res['smoothness']
    keys = res['keys']
    return {'item_id': iid, 'track': track, 'file': res['file'], 'source_range': res['source_range'],
            'speed': res['speed'], 'timeline_range': [_r(start), _r(start + res['clip_len'])],
            'source_size': list(res['info']['display']), 'output': res['out'],
            'subjects': subject_summary(res['subjects'], res['grid']),
            'path': {'keys': 1 if isinstance(keys, str) else len(keys), 'key_deviation_px': res['key_deviation_px'],
                     'zoom_range': [_r(1 / max(res['path']['s']), 3), _r(1 / min(res['path']['s']), 3)],
                     'samples': len(res['grid']), 'cuts': res['cuts'],
                     'solver': {'variables': res['path']['variables'], 'constraints': res['path']['constraints'],
                                'status': res['path']['status']}},
            'coverage': res['coverage'], 'smoothness': sm,
            'cant_fit': [{**c, 'timeline': [_r(start + c['clip'][0]), _r(start + c['clip'][1])]} for c in res['cant_fit']],
            'effect': res['effect'], 'notes': res['notes']}


# ============================================================================ preview and render check

_COL = {'required': (255, 70, 60), 'preferred': (255, 200, 0), 'optional': (150, 150, 150), 'ignore': (90, 90, 90)}


def _preview(plan, items_out, work, path):
    """Rendered frames (melt) of the reframed clips at a few moments each - in the can't-fit spans first - next
    to the source frame with the crop, its path and the subject boxes drawn; the split/inset offers rendered in
    their spans; and a pixel check of each rendered crop against the planned crop of the source frame."""
    from PIL import Image, ImageDraw

    import letitedit.review.checks as checks
    import letitedit.timeline.timeline_model as tm
    out_w, out_h = plan['target']['width'], plan['target']['height']
    fps = plan['target']['fps']
    proj, frames_of = _preview_project(plan, items_out, work, path, plan['changes'], 'reframed')
    picks = []
    for rec in items_out:
        res = rec['_res']
        L = res['clip_len']
        want = [((c['clip'][0] + c['clip'][1]) / 2) for c in res['cant_fit'] if not c['brief']][:2]
        want += [L * f for f in (0.15, 0.5, 0.85)]
        ts = []
        for t in want:
            if all(abs(t - u) > 0.25 * L / 4 for u in ts):
                ts.append(min(L - 1 / fps, max(0.0, t)))
        for t in sorted(ts[:4]):
            picks.append((rec, t))
    picks = picks[:16]
    F = [frames_of(rec, t) for rec, t in picks]
    rdir = work / 'render'
    rdir.mkdir(exist_ok=True)
    for f in rdir.glob('f_*.png'):
        f.unlink()
    pngs = checks.render_frames(tm.load(proj), proj, F, rdir)
    offer_pngs = {}
    for rec in items_out:
        for kind, off in (rec.get('offers') or {}).items():
            if rec['item_id'] == 'file':
                continue
            ts = [t for r2, t in picks if r2 is rec and any(a - 1e-6 <= t <= b + 1e-6 for a, b in off['spans'])][:3]
            if not ts:
                ts = [((a + b) / 2) for a, b in off['spans']][:1]
            pp, fo = _preview_project(plan, items_out, work, path,
                                      _only_item(plan['changes'], rec['item_id'], off['changes']),
                                      f'{rec["item_id"]}-{kind}')
            od = work / f'render-{rec["item_id"]}-{kind}'
            od.mkdir(exist_ok=True)
            for f in od.glob('f_*.png'):
                f.unlink()
            try:
                op = checks.render_frames(tm.load(pp), pp, [fo(rec, t) for t in ts], od)
                offer_pngs[(rec['item_id'], kind)] = list(zip(ts, op))
            except Exception as e:  # noqa: BLE001
                plan['warnings'].append(f'{rec["item_id"]} {kind} preview not rendered: {str(e)[:200]}')
    th = 420
    rows, checks_out = [], []
    for (rec, t_pick), png in zip(picks, pngs):
        res = rec['_res']
        W, H = res['info']['display']
        f = min(res['n_frames'] - 1, int(round(t_pick * fps)))
        t = f / fps                                     # the frame melt rendered
        src_t = res['source_range'][0] + t * res['speed']
        win = window_of_rect(res['rendered'][f], W, H, out_w, out_h)
        best = None
        # every source frame within 0.2 s: the frame the engine showed is among them (seeking by time alone can
        # land a frame off, and in fast handheld motion one frame is several pixels)
        for t_, im_ in _source_frames(res['file'], src_t, (W, H), 0.2):
            c_ = _pixel_check(im_, win, png, out_w, out_h)
            if best is None or c_.get('shift_px', 1e9) < best[0].get('shift_px', 1e9):
                best = (c_, im_, t_)
        if best is None:
            best = (_pixel_check(graphics_still(res['file'], src_t, (W, H)), win, png, out_w, out_h), None, src_t)
        check = dict(best[0], source_frame_s=_r(best[2], 4))
        im = graphics_still(res['file'], src_t, (W, H))
        check.update({'item': rec['item_id'], 'clip_s': _r(t), 'timeline_s': _r(rec['timeline_range'][0] + t),
                      'render': str(png)})
        checks_out.append(check)
        sk = th / H
        src_tile = im.convert('RGB').resize((max(1, round(W * sk)), th))
        d = ImageDraw.Draw(src_tile)
        cs = [(res['rendered'][g][0], res['rendered'][g][1]) for g in range(0, res['n_frames'], max(1, int(fps // 4)))]
        trail = []
        for g in range(0, res['n_frames'], max(1, int(fps // 4))):
            w2 = window_of_rect(res['rendered'][g], W, H, out_w, out_h)
            trail.append((((w2[0] + w2[2]) / 2) * sk, ((w2[1] + w2[3]) / 2) * sk))
        del cs
        if len(trail) > 1:
            d.line(trail, fill=(0, 220, 255), width=2)
        for s in res['subjects']:
            b = boxes_at(s['box'], res['grid'], t)
            if b is None or s['priority'] == 'ignore':
                continue
            d.rectangle([b[0] * sk, b[1] * sk, b[2] * sk, b[3] * sk], outline=_COL[s['priority']], width=2)
            d.text((b[0] * sk + 3, b[1] * sk + 2), s['label'], fill=_COL[s['priority']])
        d.rectangle([win[0] * sk, win[1] * sk, win[2] * sk, win[3] * sk], outline=(0, 0, 0), width=5)
        d.rectangle([win[0] * sk, win[1] * sk, win[2] * sk, win[3] * sk], outline=(255, 255, 255), width=2)
        _label(d, f"{rec['item_id']} {t:.1f}s (source {src_t:.1f}s)", th)
        out_tile = Image.open(png).convert('RGB')
        out_tile = out_tile.resize((max(1, round(out_tile.width * th / out_tile.height)), th))
        _label(ImageDraw.Draw(out_tile), f"render {rec['timeline_range'][0] + t:.1f}s", th)
        tiles = [src_tile, out_tile]
        for kind in ('split', 'inset'):
            for (ot, op) in offer_pngs.get((rec['item_id'], kind), []):
                if abs(ot - t_pick) < 1e-6:
                    ti = Image.open(op).convert('RGB')
                    ti = ti.resize((max(1, round(ti.width * th / ti.height)), th))
                    _label(ImageDraw.Draw(ti), f'{kind} offer', th)
                    tiles.append(ti)
        rows.append(tiles)
    width = max(sum(t.width + 6 for t in r) for r in rows)
    sheet = Image.new('RGB', (width, len(rows) * (th + 6)), (24, 24, 24))
    for i, r in enumerate(rows):
        x = 0
        for t in r:
            sheet.paste(t, (x, i * (th + 6)))
            x += t.width + 6
    if sheet.width > 2000:                                # keep the reply image a reasonable size
        sheet = sheet.resize((2000, round(sheet.height * 2000 / sheet.width)), Image.LANCZOS)
    sp = work / 'reframe-preview.jpg'
    sheet.save(sp, 'JPEG', quality=86)
    plan['preview_artifacts'] = {'sheet': str(sp), 'preview_project': str(proj), 'frames': [str(p) for p in pngs],
                                 'offer_frames': {f'{k[0]}:{k[1]}': [str(p) for _, p in v] for k, v in offer_pngs.items()},
                                 'folder': str(work)}
    plan['render_check'] = checks_out
    bad = [c for c in checks_out if not c.get('match')]
    plan['checked_ranges'] = [{'item': c['item'], 'timeline_s': c['timeline_s'], 'by': 'melt render vs the planned '
                               'crop of the source frame'} for c in checks_out]
    plan['unchecked_ranges'].append({'what': 'frames between the rendered ones', 'why': 'coverage there is from the '
                                     "engine's keyframe arithmetic on the subjects' boxes, not from rendered pixels"})
    if bad:
        plan['warnings'].append(f'{len(bad)} rendered frame(s) do not match the planned crop: ' +
                                '; '.join(f"{c['item']} {c['timeline_s']}s shift {c.get('shift_px')}" for c in bad[:4]))


def _source_frames(path, t, size, span=0.2):
    """[(source s, PIL image)] every frame of the file within t +- span (upright, display size)."""
    import subprocess

    import letitedit.pictures.annotate as annotate
    from PIL import Image
    w, h = size
    a = max(0.0, t - span)
    r = subprocess.run([str(annotate.FFMPEG), '-v', 'error', '-ss', f'{a:.4f}', '-i', str(path), '-t', f'{2 * span:.4f}',
                        '-an', '-sn', '-vf', f'scale={w}:{h}', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt',
                        'rgb24', '-'],
                       capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    n = len(r.stdout) // (w * h * 3)
    fps = float(media(path).get('rate') or 30.0) or 30.0
    first = math.ceil(a * fps - 1e-6)                # the seek gives the first frame at or after a
    return [((first + i) / fps, Image.frombytes('RGB', (w, h), r.stdout[i * w * h * 3:(i + 1) * w * h * 3]))
            for i in range(n)]


def graphics_still(path, t, size):
    import letitedit.pictures.graphics as graphics
    return graphics.still(path, t, tuple(size))


def _label(d, text, th):
    d.rectangle([0, th - 18, 7 * len(text) + 8, th], fill=(0, 0, 0))
    d.text((4, th - 16), text, fill=(255, 235, 120))


def _pixel_check(src_img, win, png, out_w, out_h):
    """The rendered frame against the planned crop of the source frame: the shift between them (phase
    correlation, output pixels) and the mean difference - the crop is where it was planned when both are small."""
    import cv2
    from PIL import Image
    W, H = src_img.size
    k = out_w / (win[2] - win[0])
    # the source scaled as the engine does, then the crop cut out
    sw, sh = int(round(W * k)), int(round(H * k))
    big = np.asarray(src_img.convert('RGB').resize((sw, sh), Image.BILINEAR), np.float32)
    x0, y0 = int(round(win[0] * k)), int(round(win[1] * k))
    pred = np.zeros((out_h, out_w, 3), np.float32)
    ys0, xs0 = max(0, y0), max(0, x0)
    ys1, xs1 = min(sh, y0 + out_h), min(sw, x0 + out_w)
    pred[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0] = big[ys0:ys1, xs0:xs1]
    rend = np.asarray(Image.open(png).convert('RGB'), np.float32)
    if rend.shape[:2] != (out_h, out_w):
        return {'match': False, 'why': f'render size {rend.shape[1]}x{rend.shape[0]}'}
    g1 = cv2.cvtColor(pred, cv2.COLOR_RGB2GRAY)
    g2 = cv2.cvtColor(rend, cv2.COLOR_RGB2GRAY)
    s = 0.25
    a = cv2.resize(g1, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    b = cv2.resize(g2, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    win_h = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(a, b, win_h)
    shift = math.hypot(dx, dy) / s
    mad = float(np.mean(np.abs(g1 - g2)))
    return {'match': bool(shift <= 4.0 and mad <= 18.0), 'shift_px': _r(shift, 2), 'mean_diff': _r(mad, 2),
            'peak': _r(resp, 3)}


def _only_item(changes, iid, ops):
    """The plan's changes with item iid's own change swapped for an offer's ops."""
    out = [c for c in changes if c.get('id') != iid]
    return out + list(ops)


def _preview_project(plan, items_out, work, path, changes, name):
    """A copy of the project (or, in file mode, a new one at the target size) with the changes, in the work
    folder; and a function (record, clip seconds) -> timeline frame."""
    import xml.etree.ElementTree as ET

    import letitedit.server.core_tools as core_tools
    import letitedit.timeline.edit_script as es
    fps = plan['target']['fps']
    out = work / f'preview-{name}.mlt'
    if path is not None:
        tree = ET.parse(path)
        tree.getroot().set('root', str(Path(path).resolve().parent))
        tree.write(out, encoding='utf-8', xml_declaration=True)
        before = es.read(out)
        after, _ = es.edit(before, [copy.deepcopy(c) for c in _dedupe_tracks(before, changes)])
        after['base'] = before['base']
        es.compile_script(after, base=out, out=out, graphics_dir=work / 'graphics')

        def frames_of(rec, t):
            return int(round((rec['timeline_range'][0] + t) * fps))
        return out, frames_of
    rec = items_out[0]
    if out.exists():
        out.unlink()
    core_tools.new_project(str(out), width=plan['target']['width'], height=plan['target']['height'], fps=fps)
    s = es.read(out)
    s['tracks'][0]['items'] = [copy.deepcopy(rec['item'])]
    es.compile_script(s, base=out, out=out)

    def frames_of(rec_, t):
        return int(round(t * fps))
    return out, frames_of


def _dedupe_tracks(script, changes):
    """add_track ops for tracks that exist already (or twice) dropped."""
    have = {t['name'] for t in script['tracks']}
    out = []
    for c in changes:
        if c.get('op') == 'add_track':
            if c['name'] in have:
                continue
            have.add(c['name'])
        out.append(c)
    return out


# ============================================================================ plans: save, load, apply

def _plans_dir():
    d = WORK / 'plans'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_plan(plan):
    (_plans_dir() / f"{plan['plan_id']}.json").write_text(json.dumps(plan, indent=1, default=_jsonable),
                                                          encoding='utf-8')


def _jsonable(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, set):
        return sorted(o)
    return str(o)


def load_plan(plan_id):
    p = _plans_dir() / f'{plan_id}.json'
    if not p.exists():
        raise ValueError(f'no plan {plan_id} (plans are kept in {_plans_dir()}); plan again with letitedit_reframe')
    return json.loads(p.read_text(encoding='utf-8-sig'))


def changes_for(plan, choose=None):
    """The plan's changes with each chosen item's offer in place of its single crop. choose: {item id: 'crop' |
    'split' | 'inset'} ('*' for every clip that has that offer)."""
    choose = dict(choose or {})
    every = choose.pop('*', None)
    by_item = {}
    for c in plan['changes']:
        by_item.setdefault(c.get('id'), []).append(c)
    out = []
    for rec in plan['items']:
        iid = rec['item_id']
        kind = choose.get(iid, every if every and (rec.get('offers') or {}).get(every) else None)
        if kind in (None, 'crop'):
            out += by_item.get(iid, [])
            continue
        off = (rec.get('offers') or {}).get(kind)
        if not off:
            raise ValueError(f"{iid} has no {kind} offer (offers: {', '.join(rec.get('offers') or {}) or 'none'})")
        out += off['changes']
    unknown = [k for k in choose if k not in {r['item_id'] for r in plan['items']}]
    if unknown:
        raise ValueError(f"choose: no planned clip {', '.join(unknown)}")
    return out


def apply_plan(plan, choose=None, expected_revision=None, label=None, actor=None):
    """Apply a plan (dict or plan_id) to its project through the shared apply path (timeline_tools.apply_project:
    one undo step in an open window, else the file with a history copy). Refused when the project or a source
    file changed since the plan was made."""
    import letitedit.timeline.edit_script as es
    import letitedit.server.timeline_tools as timeline_tools
    if isinstance(plan, str):
        plan = load_plan(plan)
    if plan.get('mode') != 'project' or not plan.get('project'):
        raise ValueError('a file plan has nothing to apply to; insert its item (items[0].item) with '
                         'letitedit_timeline_apply, or plan a project')
    path = Path(plan['project'])
    rev = es.file_hash(path)
    want = expected_revision or plan['project_revision']
    if rev != want:
        raise es.Conflict(f'the project changed since this reframe was planned (revision {want}, now {rev}); plan '
                          'it again')
    for f, fp in (plan.get('source_fingerprints') or {}).items():
        import letitedit.pictures.annotate as annotate
        if not os.path.exists(f) or annotate.fingerprint(f) != list(fp):
            raise es.Conflict(f'a source file changed or is missing since the plan was made: {f}')
    changes = _dedupe_tracks(es.read(path), changes_for(plan, choose))
    if not changes:
        return {'changes': [], 'notes': ['nothing to apply']}
    what = ', '.join(sorted({c['op'] for c in changes}))
    result, _ = timeline_tools.apply_project(str(path), changes, check=False,
                                             label=label or f'reframe {len(plan["items"])} clip(s) ({what})',
                                             actor=actor)
    return result


# ============================================================================ linked versions (formats.py mode 'solve')

VERSION_KEYS = ('keep', 'priorities', 'sources', 'platform', 'solver')


def version_item(item, out_w, out_h, fps, settings, given_focus=None, track_given=(), item_id=None):
    """formats.reframe_item for reframe mode 'solve' (letitedit_versions(..., reframe={'mode': 'solve', 'keep':
    [...], 'priorities': {...}, 'sources': [...], 'platform': ..., 'solver': {reframe settings}})): (effect,
    record) for one picture clip of a linked version. keep / priorities may be per main-item id ({id: [...],
    '*': [...]}). A focus point given to make() becomes a small required box. Split/inset offers for the spans
    that can't fit come from planning the made version itself (letitedit_reframe(project=<version>, items=[id]))."""
    clip = item.get('clip')
    if not clip:
        return None, {'method': 'none', 'why': 'not a clip'}
    if settings.get('fit', 'fill') != 'fill':
        return None, {'method': 'none', 'why': "mode 'solve' crops to fill the frame; fit: 'fit' shows the whole "
                      "picture instead - use mode 'follow' for it"}
    try:
        info = media(clip)
    except Unsupported as e:
        return None, {'method': 'none', 'why': str(e)}
    if info.get('image'):
        return None, {'method': 'none', 'why': 'a still picture (stills are not reframed by the solver yet)'}
    import letitedit.timeline.edit_script as es
    a = float(es.to_seconds(item.get('in', 0)))
    b = float(es.to_seconds(item.get('out', a)))
    sp = float(item.get('speed', 1.0))
    if item.get('reverse') or sp <= 0:
        return None, {'method': 'none', 'why': 'a reversed clip'}
    iid = item_id or item.get('id')
    main_id = str(iid).split('~')[0] if iid is not None else None      # a piece of a main item: 'id~2'

    def per(value):
        v = _per_item(value, iid)
        return _per_item(value, main_id) if v is None and main_id != iid else v
    keep = per(settings.get('keep'))
    keep = list(keep) if isinstance(keep, (list, tuple)) else ([keep] if keep else [])
    if given_focus is not None:
        pts = [[0.0] + list(given_focus)] if len(given_focus) == 2 and not isinstance(given_focus[0], (list, tuple)) \
            else [list(p) for p in given_focus]
        rows = []
        for p in pts:
            t, x, y = float(p[0]), float(p[1]), float(p[2])
            rows.append([a + t * sp, max(0.0, x - 0.05), max(0.0, y - 0.05), min(1.0, x + 0.05), min(1.0, y + 0.05)])
        keep = [{'label': 'focus', 'boxes': rows, 'follow': 'keys' if len(rows) > 1 else 'static'}] + keep
    st = settings_of(settings.get('solver'))
    if float(settings.get('zoom') or 1.0) > 1.0 and st['zoom'] == [1.0, 1.0]:
        z = float(settings['zoom'])
        st['zoom'] = [z, z]
    try:
        res = solve_clip(clip, a, b, (out_w, out_h), fps, sp, keep or None, per(settings.get('priorities')),
                         settings.get('sources'), settings.get('platform'), st, track_given=track_given)
    except Unsupported as e:
        return None, {'method': 'none', 'why': str(e)}
    rec = {'method': 'solve', 'source_size': list(info['display']), 'clip_seconds': [_r(a), _r(b)],
           'subjects': subject_summary(res['subjects'], res['grid']), 'coverage': res['coverage'],
           'smoothness': res['smoothness'], 'cant_fit': res['cant_fit'],
           'keys': 1 if isinstance(res['keys'], str) else len(res['keys']), 'effect': res['effect']}
    if any(not c['brief'] for c in res['cant_fit']):
        rec['offers'] = ("required subjects can't share one crop here; split/inset edits: "
                         f"letitedit_reframe(project=<this version>, items=['{iid}'], ...)")
    return res['effect'], rec
