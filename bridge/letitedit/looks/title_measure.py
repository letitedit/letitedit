"""A title as it renders: its lines' heights, stroke weight and place on the frame, and how plain the picture behind it
is, measured on the export; and the Look recipe's title rule (its "## Title" section's numbers) to check it against.

measure(video, at, colour, before=None, near=None) -> {'lines': [{'box', 'height', 'stroke', 'centre'}], 'behind_std',
        'frame_std', 'plainest'}
    at       a time when the title is fully on (seconds); before: a time on the same shot without it [at - 0.5, at least 0]
    colour   the title's fill (#RRGGBB): its pixels are those within COLOUR_DISTANCE of it that the frame without the
             title doesn't have there
    height   a line's ink height as a share of the frame height (capitals: the cap height)
    stroke   the strokes' width over the line's height (2 x the 90th percentile of the distance to the nearest edge): a
             heavy face reads about 0.16 and over, a regular one about 0.11
    centre   the line's box centre (x, y) as shares of the frame
    behind_std / frame_std   brightness spread (0-255) behind the title's box in the frame without it, and across that
             whole frame: a plain area (sky, a wall) is far under the frame's own; plainest: plain_spot of that frame
             (with near, the rule's place: the spot nearest it whose spread is under SPOT_RATIO of the frame's)
rule(recipe_text) -> {'colour', 'cap_height', 'second_height', 'centre', 'heavy', 'plain'} from the recipe's title
    section; {} when it has none
title_on(script)  -> (start_s, end_s) of the title on a timeline: the first text or graphic item on a picture track other
    than the main one (a track named for titles first) starting in the first OPENING_S; None without one
check(rule, found) -> problems (plain sentences) for each line too small or large, a light stroke where the rule asks for
    a heavy face, and a busy picture behind it where the rule asks for a plain area (with the plainest place for the
    title's box in that frame); the rule's place counts where the picture behind the title is busy (the rule's
    place is where the reference's own picture was plain), where a plain spot sits nearer the rule's place than the
    title by over PLACE_TOLERANCE, or where the rule asks for no plain area
plain_spot(frame, w, h, near=None, plain_under=None) -> where a title can sit: the plainest window of a frame for a box
    that size; with near (x, y) and plain_under (a spread), the window nearest near among those plain enough (spread
    under plain_under), the plainest when none is ('near': False)

The bars: a line's height within HEIGHT_TOLERANCE of the rule's (a share of it); a heavy face's stroke at least
HEAVY_STROKE; the centre within PLACE_TOLERANCE of the frame (either axis); behind the title, at most PLAIN_RATIO of the
frame's own spread; a place suggested for it, under SPOT_RATIO.
"""
from __future__ import annotations

import math
import re

import numpy as np

COLOUR_DISTANCE = 70        # RGB distance (0-255 scale) from the title's colour
HEIGHT_TOLERANCE = 0.2
HEAVY_STROKE = 0.16
PLACE_TOLERANCE = 0.1
PLAIN_RATIO = 0.6
SPOT_RATIO = 0.3            # a place suggested for the title: its window's spread under this share of the frame's
MIN_PIXELS = 200
OPENING_S = 8.0
WIDTH = 1920


def _frame(video, t):
    import cv2
    cap = cv2.VideoCapture(str(video))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, frame = cap.read()
        if not ok:
            return None
        h, w = frame.shape[:2]
        if w != WIDTH:
            frame = cv2.resize(frame, (WIDTH, round(h * WIDTH / w)), interpolation=cv2.INTER_AREA)
        return frame
    finally:
        cap.release()


def _rgb(colour):
    colour = colour.lstrip('#')
    return np.array([int(colour[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def lines_of(mask):
    """Each text line of a mask: (y0, y1, x0, x1) from rows with ink, split at empty rows."""
    rows = np.where(mask.any(axis=1))[0]
    if not len(rows):
        return []
    out, start = [], rows[0]
    gap = max(3, mask.shape[0] // 100)
    for a, b in zip(rows, rows[1:]):
        if b - a > gap:
            out.append((start, a + 1))
            start = b
    out.append((start, rows[-1] + 1))
    boxes = []
    for y0, y1 in out:
        cols = np.where(mask[y0:y1].any(axis=0))[0]
        if len(cols) and mask[y0:y1].sum() >= MIN_PIXELS:
            boxes.append((int(y0), int(y1), int(cols[0]), int(cols[-1]) + 1))
    return boxes


def measure(video, at, colour, before=None, near=None):
    import cv2
    frame = _frame(video, at)
    if frame is None:
        return {'not_measured': 'no frame at the title'}
    clean = _frame(video, max(0., at - .5) if before is None else before)
    rgb = frame[..., ::-1].astype(np.float32)
    want = _rgb(colour)
    mask = np.linalg.norm(rgb - want, axis=2) < COLOUR_DISTANCE
    if clean is not None:
        mask &= ~(np.linalg.norm(clean[..., ::-1].astype(np.float32) - want, axis=2) < COLOUR_DISTANCE)
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    h, w = mask.shape
    lines = []
    for y0, y1, x0, x1 in lines_of(mask):
        part = mask[y0:y1, x0:x1].astype(np.uint8)
        dist = cv2.distanceTransform(part, cv2.DIST_L2, 3)
        inked = dist[part > 0]
        stroke = 2 * float(np.percentile(inked, 90)) / max(1, y1 - y0) if len(inked) else None
        lines.append({'box': [round(x0 / w, 4), round(y0 / h, 4), round(x1 / w, 4), round(y1 / h, 4)],
                      'height': round((y1 - y0) / h, 4), 'stroke': round(stroke, 3) if stroke else None,
                      'centre': [round((x0 + x1) / 2 / w, 3), round((y0 + y1) / 2 / h, 3)]})
    out = {'lines': lines}
    if clean is not None and lines:
        grey = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY).astype(np.float32)
        x0 = min(int(l['box'][0] * w) for l in lines)
        y0 = min(int(l['box'][1] * h) for l in lines)
        x1 = max(int(l['box'][2] * w) for l in lines)
        y1 = max(int(l['box'][3] * h) for l in lines)
        out['behind_std'] = round(float(grey[y0:y1, x0:x1].std()), 2)
        out['frame_std'] = round(float(grey.std()), 2)
        out['plainest'] = plain_spot(clean, (x1 - x0) / w, (y1 - y0) / h, near=near,
                                     plain_under=SPOT_RATIO * out['frame_std'] if near else None)
    return out


def plain_spot(frame, box_w, box_h, step=0.02, near=None, plain_under=None):
    """Where a box_w x box_h window (shares) of a BGR frame can sit plainly: {'centre': [x, y] (shares of the frame),
    'spread' (brightness spread, 0-255)}. Windows are scanned in steps of `step`. Without near: the plainest. With near
    (x, y) and plain_under: the window whose centre is nearest near among those whose spread is under plain_under
    ('near': True), else the plainest ('near': False)."""
    import cv2
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = grey.shape
    bw, bh = max(2, int(box_w * w)), max(2, int(box_h * h))
    windows = []
    for y in range(0, h - bh + 1, max(1, int(step * h))):
        for x in range(0, w - bw + 1, max(1, int(step * w))):
            windows.append((float(grey[y:y + bh, x:x + bw].std()), (x + bw / 2) / w, (y + bh / 2) / h))
    if not windows:
        return None
    best = min(windows)
    out = None
    if near is not None and plain_under is not None:
        plain = [win for win in windows if win[0] < plain_under]
        if plain:
            best = min(plain, key=lambda win: (math.hypot(win[1] - near[0], win[2] - near[1]), win[0]))
        out = {'near': bool(plain)}
    return {'centre': [round(best[1], 3), round(best[2], 3)], 'spread': round(best[0], 2), **(out or {})}


def _section(text, heading='## Title'):
    lines = (text or '').splitlines()
    for k, line in enumerate(lines):
        if line.strip().lower() == heading.lower():
            body = []
            for more in lines[k + 1:]:
                if more.startswith('## '):
                    break
                body.append(more)
            return '\n'.join(body)
    return ''


def rule(recipe_text):
    """The recipe's title rule as numbers; {} without a title section or numbers in it."""
    body = _section(recipe_text)
    if not body:
        return {}
    out = {}
    colour = re.search(r'#[0-9A-Fa-f]{6}', body)
    if colour:
        out['colour'] = colour.group(0)
    cap = re.search(r'cap height\s*(?:of\s*)?([0-9]*\.[0-9]+)', body)
    if cap:
        out['cap_height'] = float(cap.group(1))
    after = re.search(r'second line|line 2', body, re.I)
    if after:
        second = re.search(r'height\s*(?:of\s*)?([0-9]*\.[0-9]+)', body[after.end():after.end() + 120])
        if second:
            out['second_height'] = float(second.group(1))
    place = re.search(r'\(x\s*([0-9.]+),\s*y\s*([0-9.]+)\)', body)
    if place:
        out['centre'] = [float(place.group(1)), float(place.group(2))]
    weight = re.search(r'\b([5-9]00)\b', body)
    out['heavy'] = bool(re.search(r'\b(heavy|bold|black|extra ?bold)\b', body, re.I)) or bool(
        weight and int(weight.group(1)) >= 600)
    out['plain'] = bool(re.search(r'\bplain|open sky|empty sky|negative space\b', body, re.I))
    return out if out.get('colour') else {}


def check(spec, found):
    """Problems of a measured title (measure()) against the recipe's rule (rule())."""
    problems = []
    lines = (found or {}).get('lines') or []
    if not spec or not lines:
        return problems
    wanted = [('cap_height', 'the first line')] + ([('second_height', 'the second line')] if len(lines) > 1 else [])
    for (key, name), line in zip(wanted, lines):
        target = spec.get(key)
        if target and abs(line['height'] / target - 1) > HEIGHT_TOLERANCE:
            problems.append(f"{name} is {line['height']:.3f} of the frame high against the rule's {target:.3f} "
                            f"({line['height'] / target:.0%} of it)")
    if spec.get('heavy') and lines[0].get('stroke') is not None and lines[0]['stroke'] < HEAVY_STROKE:
        problems.append(f"the title's strokes are {lines[0]['stroke']:.2f} of its height: a light face where the rule "
                        f"asks for a heavy one (about {HEAVY_STROKE} and over)")
    busy = (spec.get('plain') and found.get('behind_std') is not None and found.get('frame_std')
            and found['behind_std'] > PLAIN_RATIO * found['frame_std'])
    if busy:
        spot = found.get('plainest')
        problems.append(f"the picture behind the title is busy (brightness spread {found['behind_std']:.0f} against the "
                        f"frame's {found['frame_std']:.0f}) where the rule asks for a plain area"
                        + (f"; the {'plain area nearest the rule' + chr(39) + 's place' if spot.get('near') else 'plainest area'} "
                           f"of that frame for a box this size is at x {spot['centre'][0]:.2f}, "
                           f"y {spot['centre'][1]:.2f} (spread {spot['spread']:.0f})" if spot else ''))
    if spec.get('centre'):
        cx, cy = lines[0]['centre']
        tx, ty = spec['centre']
        spot = found.get('plainest') or {}
        off = math.hypot(cx - tx, cy - ty)
        nearer = (spec.get('plain') and spot.get('near') and not busy
                  and off - math.hypot(spot['centre'][0] - tx, spot['centre'][1] - ty) > PLACE_TOLERANCE)
        if (busy or not spec.get('plain') or nearer) and (abs(cx - tx) > PLACE_TOLERANCE or abs(cy - ty) > PLACE_TOLERANCE):
            problems.append(f"the title sits at x {cx:.2f}, y {cy:.2f} of the frame against the rule's x {tx:.2f}, "
                            f"y {ty:.2f}" + (f"; a plain area nearer the rule's place is at x {spot['centre'][0]:.2f}, "
                                             f"y {spot['centre'][1]:.2f}" if nearer else ''))
    return problems


def title_on(script):
    """(start_s, end_s) of the opening title on the timeline, or None."""
    from letitedit.timeline.edit_sync import layout, main_track
    main = main_track(script or {'tracks': []})
    tracks = [t for t in (script or {}).get('tracks') or [] if t.get('kind', 'video') == 'video' and t is not main]
    tracks.sort(key=lambda t: 0 if re.search(r'title', t.get('name', ''), re.I) else 1)
    for track in tracks:
        for item, start, end in layout(track):
            if start > OPENING_S:
                break
            if any(k in item for k in ('ass', 'graphic', 'text', 'motion', 'scene')) and end > start:
                return round(start, 3), round(end, 3)
    return None


def check_export(recipe_text, video, script):
    """(summary, problems) of the export's opening title against the recipe's rule: {} and [] without a rule or a title."""
    spec = rule(recipe_text)
    span = title_on(script) if spec else None
    if not spec or not span:
        return {}, []
    start, end = span
    at = min(end - .05, start + max(.5, (end - start) * .6))
    before = max(0., start - .3) if start >= .35 else None
    found = measure(video, at, spec['colour'], before=before, near=spec.get('centre'))
    return {'rule': spec, 'at_s': round(at, 3), **found}, check(spec, found)

