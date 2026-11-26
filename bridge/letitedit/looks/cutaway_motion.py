"""Coherent image motion, not proof of a physical camera move."""
import json
import math
import statistics

import cv2
import numpy as np


def pair(previous, current, seconds):
    height, width = previous.shape
    mask = np.zeros_like(previous)
    mask[height // 12:height * 3 // 5, width // 12:width * 11 // 12] = 255
    points = cv2.goodFeaturesToTrack(previous, 180, .015, 7, mask=mask)
    if points is None or len(points) < 12:
        return None
    tracked, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None)
    if tracked is None:
        return None
    valid = status.reshape(-1).astype(bool)
    if valid.sum() < 12:
        return None
    matrix, inliers = cv2.estimateAffinePartial2D(points[valid], tracked[valid], method=cv2.RANSAC,
                                                ransacReprojThreshold=1.5)
    if matrix is None or float(inliers.mean()) < .65:
        return None
    scale = math.hypot(matrix[0, 0], matrix[1, 0])
    if not .85 < scale < 1.15:
        return None
    centre = np.array([width / 2, height / 2])
    shift = matrix[:, :2] @ centre + matrix[:, 2] - centre
    horizontal, vertical = shift / np.array([width, height]) / seconds
    zoom = math.log(scale) / seconds
    speed = math.hypot(horizontal, vertical)
    if speed > .5 or abs(zoom) > .5:
        return None
    return {'x_per_s': float(horizontal), 'y_per_s': float(vertical), 'zoom_per_s': zoom,
            'speed_per_s': speed, 'moving': speed >= .003 or abs(zoom) >= .006,
            'inlier_share': float(inliers.mean())}


def measure(video, shots):
    cv2.setNumThreads(4)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError('Cutaway motion video cannot be decoded')
    results = []
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError('Cutaway motion needs a valid video frame rate')
        frame_index = 0
        for shot in shots:
            start, end = shot['start_s'], shot['end_s']
            if not 0 <= start < end:
                raise ValueError('Motion needs positive ordered shot spans')
            values, lumas, saturations = [], [], []
            previous = None
            clock = start + min(.1, (end - start) / 8)
            last_clock = clock
            while clock < end - .04:
                wanted = round(clock * fps)
                good = True
                while frame_index < wanted:
                    good = capture.grab()
                    frame_index += 1
                    if not good:
                        break
                if good:
                    good, frame = capture.read()
                    frame_index += 1
                if not good:
                    break
                frame = cv2.resize(frame, (320, max(2, round(frame.shape[0] * 320 / frame.shape[1]))))
                grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                lumas.append(float(np.median(grey) / 255))
                saturations.append(float(np.median(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[..., 1]) / 255))
                if previous is not None:
                    value = pair(previous, grey, clock - last_clock)
                    if value is not None:
                        values.append(value)
                previous, last_clock = grey, clock
                clock += .125
            known = len(values) >= 2
            moving = sum(value['moving'] for value in values) / len(values) if values else None
            row = {**shot, 'valid_pairs': len(values), 'moving_pair_share': moving,
                   'moving': bool(moving >= .5) if known else None,
                   'median_luma': statistics.median(lumas) if lumas else None,
                   'median_saturation': statistics.median(saturations) if saturations else None}
            for key in ('x_per_s', 'y_per_s', 'zoom_per_s', 'speed_per_s'):
                row[key] = statistics.median(value[key] for value in values) if known else None
            row['direction'] = ('right' if row['x_per_s'] > 0 else 'left') if known and abs(row['x_per_s']) >= .003 else 'none'
            row['vertical_direction'] = ('down' if row['y_per_s'] > 0 else 'up') if known and abs(row['y_per_s']) >= .003 else 'none'
            row['zoom'] = ('push_in' if row['zoom_per_s'] > 0 else 'pull_out') if known and abs(row['zoom_per_s']) >= .006 else 'none'
            results.append(row)
    finally:
        capture.release()
    known = [row for row in results if row['moving'] is not None]
    moving = [row for row in known if row['moving']]
    return {'shots': results, 'measured_shots': len(known), 'total_shots': len(results),
            'moving_share': len(moving) / len(known) if known else None,
            'median_speed_per_s': statistics.median(row['speed_per_s'] for row in moving) if moving else None,
            'median_zoom_per_s': statistics.median(abs(row['zoom_per_s']) for row in moving) if moving else None,
            'static_hold_seconds': [row['end_s'] - row['start_s'] for row in known if not row['moving']],
            'method': 'Sequential decode, 8Hz robust partial-affine flow at 320px; upper picture excludes caption band. Image drift direction, not physical camera direction; foreground motion and cuts can bias it. Untrackable shots stay unknown.'}


def check(entry, requirements, video=None):
    targets = []
    if 'visual.json' in requirements:
        targets = [row.get('broll_motion') for row in json.loads(requirements['visual.json'])['references']]
    targets = [row for row in targets if row and row.get('moving_share') is not None]
    if not targets:
        return None, []
    if not video or not entry.get('visible_shots'):
        return None, ['required cutaway motion needs a rendered video and visible_shots for measurement']
    import letitedit.core.render_lock as render_lock
    with render_lock.slot('Look cutaway motion', timeout_s=3600):
        measured = measure(video, entry['visible_shots'])
    target = statistics.median(row['moving_share'] for row in targets)
    problems = []
    if measured['measured_shots'] != measured['total_shots']:
        problems.append('some required cutaway motion is unmeasurable; inspect those shots')
    if measured['moving_share'] is None or measured['moving_share'] + 1 / max(1, measured['total_shots']) < target:
        problems.append('cutaways lack the moving-shot proportion measured by the Look')
    return measured, problems
