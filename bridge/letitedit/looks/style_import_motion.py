"""More picture measurements for style_import: how overlays come in and go out, split screens and picture-in-picture,
and speed changes.

    overlay_motion(video, info, overlays)  each overlay's entry and exit: cut, fade, slide or scale (in place)
    layouts(frames, fps, spans)            split screens (a straight seam across the frame with moving pictures on both
                                           sides) and insets (a rectangle with its own moving picture), from edges
                                           that stay put while the footage moves
    speed_profile(frames, feat, fps, spans) confirmed picture holds/reverse replays, unsure motion/cadence candidates,
                                           observations and coverage; speed_changes returns confirmed events only
Every result says how it was measured; what can't be told apart is said (a camera that speeds up looks like a speed
ramp; a speed change at a cut can't be measured against the shot before).
"""
from __future__ import annotations

import math

import numpy as np


# ------------------------------------------------------------------ entries and exits

def _crop(f, box, grow=0.0):
    h, w = f.shape[:2]
    bw, bh = box[2] - box[0], box[3] - box[1]
    x0, y0 = max(0, int((box[0] - grow * bw) * w)), max(0, int((box[1] - grow * bh) * h))
    x1, y1 = min(w, int(math.ceil((box[2] + grow * bw) * w))), min(h, int(math.ceil((box[3] + grow * bh) * h)))
    return f[y0:y1, x0:x1], (x0, y0, x1, y1)


def _grey(f):
    import cv2
    return cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) if f.ndim == 3 else f.astype(np.float32)


def classify_motion(frames, box, on_first):
    """How an overlay goes from on to off across frames (on_first=True: an exit; False: an entry, read backwards).
    Each frame between the clearly-on and the clearly-off frame is compared with both ends inside the box: the
    element's share p (0 on .. 1 off). One step or less in between: 'cut'. Otherwise the element's look (the on
    frame's box) is searched in each step around its place at a few sizes: it shrinks or grows -> 'scale'; it moves
    by a fifth of its size or more -> 'slide'; it stays put and fades into the picture -> 'fade'.
    Returns {kind, frames (in between), moved, size} or None."""
    import cv2
    seq = list(frames) if on_first else list(frames)[::-1]
    if len(seq) < 4:
        return None
    on, off = _crop(seq[0], box)[0], _crop(seq[-1], box)[0]
    if on.size == 0 or on.shape != off.shape:
        return None
    on_g, off_g = _grey(on), _grey(off)
    diff = np.abs(on_g - off_g)
    span = float(diff.mean())
    if span < 4:
        return None
    # judged on the pixels that differ most between on and off (the overlay's own: letters, the sticker), so the
    # footage drifting behind it does not look like a fade
    key = diff >= np.percentile(diff, 75)
    p = []
    for f in seq:
        c = _grey(_crop(f, box)[0])
        if c.shape != on_g.shape:
            p.append(None)
            continue
        d_on, d_off = float(np.abs(c - on_g)[key].mean()), float(np.abs(c - off_g)[key].mean())
        p.append(d_on / max(1e-6, d_on + d_off))
    mid = [k for k, x in enumerate(p) if x is not None and 0.2 < x < 0.8]
    if len(mid) <= 1:
        return {'kind': 'cut', 'frames': len(mid)}
    # the element's look searched in the in-between frames: where and how big
    tmpl = on_g
    th, tw = tmpl.shape
    if th < 8 or tw < 8:
        return {'kind': 'fade', 'frames': len(mid)}
    shifts, sizes, scores = [], [], []
    for k in mid:
        area, (ax0, ay0, ax1, ay1) = _crop(seq[k], box, grow=0.6)
        g = _grey(area)
        best = None
        for s in (1.0, 0.85, 0.7, 0.55, 0.4, 1.15, 1.3):
            t = cv2.resize(tmpl, (max(4, int(tw * s)), max(4, int(th * s))), interpolation=cv2.INTER_AREA)
            if t.shape[0] >= g.shape[0] or t.shape[1] >= g.shape[1]:
                continue
            r = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
            if best is None or mx > best[0]:
                cx = ax0 + loc[0] + t.shape[1] / 2
                cy = ay0 + loc[1] + t.shape[0] / 2
                best = (mx, s, cx, cy)
        if best:
            h, w = seq[k].shape[:2]
            bx = (box[0] + box[2]) / 2 * w
            by = (box[1] + box[3]) / 2 * h
            scores.append(best[0])
            sizes.append(best[1])
            shifts.append(math.hypot(best[2] - bx, best[3] - by) / max(1.0, max(tw, th)))
    if not scores or max(scores) < 0.45:
        return {'kind': 'fade', 'frames': len(mid)}
    good = [i for i, s in enumerate(scores) if s >= 0.45]
    moved = max(shifts[i] for i in good)
    size = min(sizes[i] for i in good)
    big = max(sizes[i] for i in good)
    if size <= 0.75 or big >= 1.15:
        kind = 'scale'
    elif moved >= 0.2:
        kind = 'slide'
    else:
        kind = 'fade'
    return {'kind': kind, 'frames': len(mid), 'moved': round(moved, 2), 'size': round(size, 2)}


def overlay_motion(video, info, overlays, width=270, before=0.15, after=0.5):
    """Each overlay's entry and exit (see classify_motion), read at the file's own frame rate around its start and its
    end. Sets o['entry'] / o['exit'] ('cut', 'fade', 'slide', 'scale') and o['entry_frames'] / o['exit_frames']."""
    import letitedit.looks.style_import as si
    fps = float(info.get('fps') or 30.0)
    plan, times = [], []
    for o in overlays:
        if o.get('conf', 0) < 0.5 or o['end'] - o['t'] < 0.3:
            continue
        a = [o['t'] - before + k / fps for k in range(int(round((before + after) * fps)) + 1)]
        b = [o['end'] - after + k / fps for k in range(int(round((before + after) * fps)) + 1)]
        a = [t for t in a if 0 <= t <= info['duration']]
        b = [t for t in b if 0 <= t <= info['duration'] - 0.02]
        plan.append((o, a, b))
        times += a + b
    if not plan:
        return overlays
    fr = si.frames_at(video, times, width, info)
    keys = sorted(fr)

    def get(ts):
        out = []
        for t in ts:
            if not keys:
                break
            k = min(keys, key=lambda q: abs(q - t))
            if abs(k - t) <= 0.6 / fps:
                out.append(fr[k])
        return out
    for o, a, b in plan:
        ent = classify_motion(get(a), o['box'], on_first=False)
        ext = classify_motion(get(b), o['box'], on_first=True)
        if ent:
            o['entry'] = ent['kind']
            o['entry_frames'] = ent['frames']
        if ext:
            o['exit'] = ext['kind']
            o['exit_frames'] = ext['frames']
    return overlays


# ------------------------------------------------------------------ split screens and insets

LAYOUT = {'win_s': 1.0, 'step_s': 0.5, 'peak': 2.5, 'min_peak': 0.5, 'motion': 0.5, 'min_s': 1.5, 'gap_s': 1.0,
          'seg_w': 0.12, 'seg_h': 0.1, 'cross': 0.85, 'hard_line': 1.5, 'both_move': 0.0}


def motion_seams(frames):
    """How differently the picture changes on the two sides of each pixel's row and column over the frames, against
    how much it changes there: (rows map (H, W), columns map (H, W), change per pixel). Inside one picture neighbouring
    rows change together (the same camera move, the same light); on the seam between two pictures laid side by side
    they don't. Measured on letitedit's ground truth: a split's seam 1.5-1.8 against 0.5 around it, nothing along the
    edges of a striped bus filmed from a moving car or a person talking."""
    f = frames.astype(np.float32)
    dt = np.abs(np.diff(f, axis=0))
    a, b = dt[:, :-2, :], dt[:, 2:, :]
    rows = np.abs(a - b).mean(axis=0) / ((a + b).mean(axis=0) / 2 + 0.5)
    a, b = dt[:, :, :-2], dt[:, :, 2:]
    cols = np.abs(a - b).mean(axis=0) / ((a + b).mean(axis=0) / 2 + 0.5)
    rows = np.pad(rows, ((1, 1), (0, 0)), mode='edge')
    cols = np.pad(cols, ((0, 0), (1, 1)), mode='edge')
    return rows, cols, dt.mean(axis=0)


def _runs(mask, min_len):
    """[(start, end)] of True runs of at least min_len in a 1-D boolean array."""
    out, i, n = [], 0, len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        if j - i >= min_len:
            out.append((i, j))
        i = j
    return out


def layout_window(frames, text=()):
    """Split seams and insets in one window of grey frames (N, H, W): [{'kind': 'split', 'where': 'top_bottom' |
    'left_right', 'at': fraction} | {'kind': 'inset', 'box': [...]}]. A seam: the row (column) between 25% and 75% of
    the frame whose motion_seams value, averaged across the frame, is 2.5x the middle value of the others (and 0.5 or
    more), with the picture moving on both sides. An inset: a rectangle of such seam pixels in a corner, 3-45% of the
    frame, its picture moving. text: boxes of text on screen in the window (captions popping in change on their own
    too: their band's edges are not seams)."""
    st = LAYOUT
    R, C, M = motion_seams(frames)
    H, W = M.shape
    out = []
    if M.mean() < 0.3:
        return out
    # a split's seam is also a hard line in the picture itself (two pictures meet across the whole frame): the
    # brightness step across each row / column, against the rows / columns around it
    f = frames.astype(np.float32)
    g_rows = np.abs(f[:, 2:, :] - f[:, :-2, :]).mean(axis=(0, 2))
    g_cols = np.abs(f[:, :, 2:] - f[:, :, :-2]).mean(axis=(0, 1))
    g_rows, g_cols = np.r_[g_rows[0], g_rows, g_rows[-1]], np.r_[g_cols[0], g_cols, g_cols[-1]]
    for prof, size, where, grad in ((R.mean(axis=1), H, 'top_bottom', g_rows), (C.mean(axis=0), W, 'left_right', g_cols)):
        prof = prof.copy()
        for x0, y0, x1, y1 in text:
            if where == 'top_bottom':
                prof[max(0, int((y0 - 0.08) * size)):int((y1 + 0.08) * size) + 1] = 0
            elif y1 - y0 >= 0.2:
                prof[max(0, int((x0 - 0.08) * size)):int((x1 + 0.08) * size) + 1] = 0
        lo, hi = int(0.25 * size), int(0.75 * size)
        seg = prof[lo:hi]
        k = int(np.argmax(seg))
        base = float(np.median(seg))
        if seg[k] >= st['peak'] * base and seg[k] >= st['min_peak']:
            at = lo + k
            # across (nearly) the whole frame: the edge of an inset or a box is not a split
            if where == 'top_bottom':
                line = (R[max(0, at - 1):at + 2] >= st['min_peak']).any(axis=0)
            else:
                line = (C[:, max(0, at - 1):at + 2] >= st['min_peak']).any(axis=1)
            if line.mean() < st['cross']:
                continue
            near = np.r_[grad[max(0, at - 12):max(0, at - 3)], grad[at + 4:at + 13]]
            if len(near) and grad[at] < st['hard_line'] * float(np.median(near)):
                continue
            band = int(0.15 * size)
            sides = (M[max(0, at - band):max(1, at - 2)].mean(), M[at + 2:at + band].mean()) if where == 'top_bottom' \
                else (M[:, max(0, at - band):max(1, at - 2)].mean(), M[:, at + 2:at + band].mean())
            if min(sides) >= st['motion']:
                # a still camera with movement in one part of the frame along a straight edge (a table's edge, a hand
                # moving below it) looks the same: sure only when both sides move
                out.append({'kind': 'split', 'where': where, 'at': round(at / size, 3),
                            'both_move': bool(min(sides) >= st['both_move'])})
    # insets: seam pixels that close a rectangle in a corner
    on_r = R >= max(st['min_peak'], st['peak'] * float(np.median(R)))
    on_c = C >= max(st['min_peak'], st['peak'] * float(np.median(C)))
    hseg = []
    for r in range(1, H - 1):
        for a, b in _runs(on_r[r] | on_r[r - 1] | on_r[r + 1], int(st['seg_w'] * W)):
            if b - a < 0.9 * W:
                hseg.append((r, a, b))
    vseg = []
    for c in range(1, W - 1):
        for a, b in _runs(on_c[:, c] | on_c[:, c - 1] | on_c[:, c + 1], int(st['seg_h'] * H)):
            if b - a < 0.9 * H:
                vseg.append((c, a, b))
    seen = []
    # a rectangle needs a horizontal side and a vertical side meeting at a corner; the frame's own border can be the
    # other two (an inset in a corner of the frame)
    for (r, a, b) in hseg:
        for (c, va, vb) in vseg:
            if not (a - 3 <= c <= b + 3 and va - 3 <= r <= vb + 3):
                continue
            # which corner of the frame the inset sits in
            x0, x1 = (0, c) if abs(c - b) <= 3 and a <= 0.15 * W else (c, W) if abs(c - a) <= 3 and b >= 0.85 * W else (None, None)
            y0, y1 = (0, r) if abs(r - vb) <= 3 and va <= 0.15 * H else (r, H) if abs(r - va) <= 3 and vb >= 0.85 * H else (None, None)
            if x0 is None or y0 is None:
                continue
            area = (x1 - x0) * (y1 - y0) / float(W * H)
            if not 0.03 <= area <= 0.45:
                continue
            if M[y0:y1, x0:x1].mean() < st['motion']:
                continue
            box = [round(x0 / W, 3), round(y0 / H, 3), round(x1 / W, 3), round(y1 / H, 3)]
            if any(max(abs(p - q) for p, q in zip(box, s_)) < 0.06 for s_ in seen):
                continue
            seen.append(box)
            out.append({'kind': 'inset', 'box': box})
    return out


def layouts(frames, fps, spans=None, text_boxes=None):
    """Split screens and insets over the video: layout_window on windows of LAYOUT['win_s'] every step_s, joined
    into events that last min_s or more. text_boxes(t0, t1) -> boxes of text on screen then. [{t, end, kind,
    where | box, conf}]."""
    st = LAYOUT
    n = len(frames)
    win, step = max(4, int(st['win_s'] * fps)), max(2, int(st['step_s'] * fps))
    hits = []
    for i in range(0, max(1, n - win), step):
        text = text_boxes(i / fps, (i + win) / fps) if text_boxes else ()
        for h in layout_window(frames[i:i + win], text):
            hits.append((i / fps, (i + win) / fps, h))
    events = []
    for t0, t1, h in hits:
        key = h['where'] if h['kind'] == 'split' else None
        ev = next((e for e in events if e['kind'] == h['kind'] and t0 <= e['end'] + st['gap_s'] and
                   (key == e.get('where') if key else
                    max(abs(a - b) for a, b in zip(h['box'], e['box'])) < 0.06)), None)
        if ev:
            ev['end'] = t1
            ev['moving'] = ev.get('moving', 0) + int(bool(h.get('both_move', True)))
            ev['windows'] = ev.get('windows', 1) + 1
        else:
            events.append({'t': t0, 'end': t1, 'kind': h['kind'], 'moving': int(bool(h.get('both_move', True))),
                           'windows': 1, **({'where': key, 'at': h['at']} if key else {'box': h['box']})})
    out = []
    for e in events:
        if e['end'] - e['t'] >= st['min_s']:
            e['t'], e['end'] = round(e['t'], 2), round(e['end'], 2)
            # insets count; a split stays unsure: on letitedit's ground truth both split screens were found, but phone
            # footage on a table (a still upper part, a hand moving below its edge) gave 15 false ones in 9 Shorts
            e['conf'] = 0.7 if e['kind'] == 'inset' else 0.45
            e.pop('moving', None)
            e.pop('windows', None)
            out.append(e)
    return out


# ------------------------------------------------------------------ speed

SPEED = {'still': 0.35, 'exact': 0.12, 'min_hold_s': 0.5, 'min_replay_s': 0.6,
         'repeat_share': 0.25, 'step': 3.0, 'motion_hz': 12.0}
SPEED_VERSION = 2
SPEED_METHOD = ('Pixel holds are compared with their first frame to exclude drift; an interrupted exact hold '
                'and a backward replay of earlier changing frames are measured. Repeated-frame cadence, '
                'optical-flow changes and direction turns alone remain unsure, not retiming. Absolute slow/fast '
                'speed and standalone reverse require a real-time or physical baseline; none is inferred from '
                'speech pace, frame rate, smoothness or the longer side of a shot.')


def _speed_event(start, end, fps, kind, by, **details):
    return {'t': round(start / fps, 6), 'end': round(end / fps, 6), 'kind': kind,
            'speed': None, 'by': by, **details}


def _speed_runs(flags):
    padded = np.r_[False, flags, False].astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist()))


def _speed_same(first, second, threshold):
    difference = np.abs(first.astype(np.float32) - second.astype(np.float32))
    return float(difference.mean()) <= threshold and float((difference > 2).mean()) <= 0.001


def _speed_holds(frames, differences, fps, start, end, native, events, unsure):
    minimum = max(3, int(math.ceil(SPEED['min_hold_s'] * fps)))
    for first, last in _speed_runs(differences[start + 1:end] <= SPEED['still']):
        first, last = start + first, start + last + 1

        if last - first < minimum:
            continue
        anchor = frames[first]
        samples = sorted(set([first, last - 1] + list(range(first + 1, last, max(1, int(fps / 6))))))
        if not all(_speed_same(anchor, frames[index], SPEED['still']) for index in samples):
            continue
        exact = all(_speed_same(anchor, frames[index], SPEED['exact']) for index in range(first + 1, last))
        window = max(2, int(round(fps * .25)))
        left = differences[max(start + 1, first - window + 1):first + 1]
        right = differences[last:min(end, last + window)]
        moving = (len(left) >= 2 and len(right) >= 2 and
                  float(np.median(left)) >= .6 and float(np.median(right)) >= .6)
        continuous = (first > start and last < end and moving and
                      differences[first] <= float(np.median(left)) * 2 and
                      differences[last] <= float(np.median(right)) * 2)
        confirmed = native and exact and moving and continuous and float(anchor.std()) >= 5
        event = _speed_event(first, last, fps, 'freeze', 'anchored full-picture hold',
                             status='found' if confirmed else 'unsure', conf=.95 if confirmed else .3,
                             reason='Exact held frame interrupts a moving shot and motion resumes.' if confirmed else
                                    'A still picture, locked camera or near-still action can look the same.',
                             evidence={'frames': [first, last - 1], 'anchor_samples': samples,
                                       'exact': exact, 'moving_on_both_sides': moving,
                                       'native_cadence_verified': native})
        if confirmed:
            event['speed'] = 0.0
        (events if confirmed else unsure).append(event)


def _speed_replays(frames, differences, fps, start, end, native, events):
    if not native:
        return
    minimum = max(6, int(math.ceil(SPEED['min_replay_s'] * fps)))
    index = start + minimum + 1
    while index + minimum <= end:
        if differences[index] < .6 or not _speed_same(frames[index], frames[index - 2], SPEED['exact']):
            index += 1
            continue
        length = 1
        while index + length < end and index - 2 - length >= start:
            if not _speed_same(frames[index + length], frames[index - 2 - length], SPEED['exact']):
                break
            length += 1
        if length >= minimum and float(np.median(differences[index:index + length])) >= .6:
            events.append(_speed_event(index, index + length, fps, 'reverse', 'backward picture replay',
                                       status='found', conf=.98,
                                       reason='Earlier changing pictures recur in the opposite order.',
                                       evidence={'frames': [index, index + length - 1],
                                                 'matched_frames': [index - 2, index - 1 - length],
                                                 'matched_count': length, 'native_cadence_verified': True}))
            index += length
        else:
            index += 1


def _speed_flow(frames, fps, start, end, masks=None):
    import cv2

    stride = max(1, int(math.ceil(fps / SPEED['motion_hz'])))
    indices = list(range(start, end, stride))
    values, directions = [], []
    times = []
    for previous, current in zip(indices[:-1], indices[1:]):
        allowed = None
        if masks is not None:
            allowed = np.where((masks[previous] > 0) | (masks[current] > 0), 0, 255).astype(np.uint8)
        points = cv2.goodFeaturesToTrack(frames[previous], 80, .03, 5, mask=allowed)
        if points is None or len(points) < 8:
            continue
        tracked, status, error = cv2.calcOpticalFlowPyrLK(frames[previous], frames[current], points, None,
                                                       winSize=(15, 15), maxLevel=2)
        if tracked is None or status is None or error is None:
            continue
        returned, back_status, _ = cv2.calcOpticalFlowPyrLK(frames[current], frames[previous], tracked, None,
                                                         winSize=(15, 15), maxLevel=2)
        if returned is None or back_status is None:
            continue
        good = ((status[:, 0] > 0) & (back_status[:, 0] > 0) & (error[:, 0] < 20) &
                (np.linalg.norm(returned[:, 0] - points[:, 0], axis=1) < 1))
        if int(good.sum()) < 8:
            continue
        movement = tracked[good, 0] - points[good, 0]
        duration = (current - previous) / fps
        values.append(float(np.median(np.linalg.norm(movement, axis=1))) / duration)
        directions.append(np.median(movement, axis=0) / duration)
        times.append(current)
    return np.array(times), np.array(values), np.array(directions)


def speed_profile(frames, feat, fps, spans, words=(), masks=None, faces=None, native_fps=None):
    """Found events, unsure candidates, cadence observations and explicit checked/unavailable coverage.

    Frames must be uniformly timed grayscale pictures; spans use half-open frame indices. native_fps is the
    source cadence, not an assumed 30 fps. A different or unknown cadence disables hold/replay confirmation.
    masks is an optional full-picture Boolean text/exclusion mask per frame. Cadence and full-picture holds
    deliberately use unmasked pixels: a moving audience or background must not disappear behind an exclusion.
    Legacy words/faces arguments remain accepted, but neither proves or vetoes picture retiming.
    """
    result = {'version': SPEED_VERSION, 'events': [], 'unsure': [], 'observations': [],
              'status': 'not_checked', 'method': SPEED_METHOD,
              'checks': {'absolute_slow_fast': 'not_checked: real-time/physical baseline required',
                         'standalone_reverse': 'not_checked: temporal/physical baseline required'},
              'limitations': ['This signal-only pass does not model physical time or action semantics.',
                              'Optical motion includes real camera and subject acceleration.',
                              'Only supplied continuous shot spans are checked; cuts are never speed steps.']}
    if not math.isfinite(float(fps)) or fps <= 0:
        result['checks']['frames'] = 'unavailable: invalid analysis rate'
        return result
    if frames is None or len(frames) < 3:
        result['checks']['frames'] = 'unavailable: pictures required; difference or speech arrays alone are not evidence'
        return result
    if not isinstance(frames, np.ndarray) or frames.ndim != 3:
        raise ValueError('speed_profile needs grayscale frames shaped (frames, height, width)')
    if frames.dtype != np.uint8:
        raise ValueError('speed_profile needs uint8 grayscale frames')
    if masks is not None and np.shape(masks) != frames.shape:
        raise ValueError('speed_profile masks must have the same shape as frames')
    native = (native_fps is not None and math.isfinite(float(native_fps)) and
              abs(float(native_fps) - fps) <= max(1e-4, fps * 1e-4))
    differences = np.r_[0., [float(np.abs(current.astype(np.float32) - previous).mean())
                             for previous, current in zip(frames[:-1], frames[1:])]]
    events, unsure = result['events'], result['unsure']
    checked, tracked = 0, 0
    for start, end in spans:
        if not 0 <= start < end <= len(frames) or int(start) != start or int(end) != end:
            raise ValueError('speed_profile spans must be valid half-open frame indices')
        start, end = int(start), int(end)
        if end - start < 3:
            continue
        checked += 1
        _speed_holds(frames, differences, fps, start, end, native, events, unsure)
        _speed_replays(frames, differences, fps, start, end, native, events)
        segment = differences[start + 1:end]
        repeats = segment <= SPEED['still']
        alternations = float(np.mean(repeats[:-1] != repeats[1:])) if len(repeats) > 1 else 0
        if (len(segment) >= fps * .5 and SPEED['repeat_share'] <= float(repeats.mean()) <= .8
                and alternations >= .5 and np.any(segment > .6)):
            observation = _speed_event(start, end, fps, 'repeat_cadence', 'alternating repeated pictures',
                                       repeat_share=round(float(repeats.mean()), 3),
                                       reason='Frame-rate conversion and slow playback are indistinguishable here.')
            result['observations'].append(observation)
            unsure.append({**observation, 'kind': 'slow_or_conversion', 'status': 'unsure', 'conf': .2})
        times, values, directions = _speed_flow(frames, fps, start, end, masks)
        if len(values) < 8:
            continue
        tracked += 1
        smoothed = np.array([np.median(values[max(0, index - 1):index + 2]) for index in range(len(values))])
        low, high = float(np.percentile(smoothed, 20)), float(np.percentile(smoothed, 80))
        ratio = high / max(.5, low)
        result['observations'].append(_speed_event(start, end, fps, 'image_motion', 'tracked picture features',
                                                   p20_px_s=round(low, 3), p80_px_s=round(high, 3),
                                                   samples=len(values)))
        if ratio >= SPEED['step'] and high >= 8 and end - start >= fps:
            unsure.append(_speed_event(start, end, fps, 'ramp_or_action', 'within-shot image motion change',
                                       status='unsure', conf=.25, motion_ratio=round(ratio, 2),
                                       reason='Camera/subject acceleration or retiming; no normal-speed side is known.',
                                       evidence={'frames': times.tolist()}))
        if len(directions) >= 8:
            midpoint = len(directions) // 2
            before, after = np.median(directions[:midpoint], axis=0), np.median(directions[midpoint:], axis=0)
            if min(np.linalg.norm(before), np.linalg.norm(after)) >= 8 and np.dot(before, after) < 0:
                if not any(event['kind'] == 'reverse' and start / fps <= event['t'] < end / fps for event in events):
                    unsure.append(_speed_event(start, end, fps, 'reverse_or_turn', 'picture direction turn',
                                               status='unsure', conf=.2,
                                               reason='Changing travel direction is not evidence of reverse playback.'))
    events.sort(key=lambda event: event['t'])
    unsure.sort(key=lambda event: event['t'])
    result['checks'] = {'spans': checked, 'picture_holds': 'checked' if checked else 'not_checked',
                        'reverse_replays': 'checked' if native and checked else 'not_checked: native cadence required',
                        'cadence': 'native' if native else 'unknown_or_resampled',
                        'tracked_motion_spans': tracked,
                        'unresolved_motion_spans': checked - tracked,
                        'absolute_slow_fast': 'not_checked: real-time/physical baseline required',
                        'standalone_reverse': 'not_checked: temporal/physical baseline required'}
    result['status_scope'] = 'Picture holds, reverse replays and motion/cadence candidates in supplied spans only.'
    result['status'] = 'found' if events else 'unsure' if unsure else 'checked_and_none' if checked else 'not_checked'
    return result


def speed_changes(frames, feat, fps, spans, words=(), masks=None, faces=None, native_fps=None):
    """Confirmed picture events only. speed_profile also retains uncertainty, observations and coverage."""
    return speed_profile(frames, feat, fps, spans, words, masks, faces, native_fps)['events']
