"""Measured likeness of a Look kit piece against its reference: numbers, not an AI's eye.

Each family example names parts of the reference frame (text lines, plates, marks, pictures). The reference side is
segmented from the frame; our side is the family drawn with the reference's own words at the reference frame's size,
so the same letters are compared. Text, plate and mark masks of our piece come from the drawing itself (text-only and
shape-only passes of the same code), so they are exact. Both sides go through the same measuring functions.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

UPSCALE = 4

# Tolerances. Why each one is this size is written in tests/t172/REPORT.md ("the measures and their tolerances").
TOLERANCE = {
    'size': 0.08,          # line ink height, ours/reference - 1: under one minor-second type-scale step (1.067-1.125)
    'stroke': 0.12,        # stroke width / line height, relative: under one CSS weight step (~15-25% stem change)
    'width': 0.08,         # ink width per character / line height, relative: under one width class (~10-15%)
    'slant': 4.0,          # degrees: upright (0) versus italic or oblique (8-15)
    'lines': 0,            # line count with the same words
    'text_colour': 8.0,    # CIEDE2000; thin strokes in compressed video blur into the background
    'plate_colour': 6.0,   # CIEDE2000 on large flat areas
    'mark_colour': 10.0,   # CIEDE2000 on small marks
    'radius': 0.08,        # corner radius / plate height, absolute
    'padding': 0.25,       # plate padding in line heights, absolute
    'position': 0.04,      # centre, as a share of the frame's width and height
    'mark_size': 0.20,     # mark or picture height and width, relative
    'fill': 0.35,          # ink share of a mark's box, relative
    'duration': 0.15,      # seconds outside the family's duration range
    'halo': 8.5,           # Lab units, the largest band-by-band difference of the outline-and-shadow profile: the
                           # same design after video-like damage stays within 8.0; a different one (no outline,
                           # another outline or shadow) is 9.5 or more, except a faint soft shadow that the damage
                           # itself erases (tests/t174/REPORT.md, "the halo measure")
    'outline_colour': 15.0,  # CIEDE2000 on a thin ring, which compression lightens
}
HALO = False               # the outline-and-shadow rows: off until calibrated on real reference frames (T174)
HALO_FILL = 15.0           # CIE76 Lab distance: pixels this close to the measured text colour are the letters' fill
HALO_FAR = 12.0            # a halo band's median change from the background behind it is at least this ...
HALO_TOWARD = 0.5          # ... and not mostly toward the fill (an anti-aliased or blurred edge is a blend)
HALO_BAND = 0.02           # outline bands, line heights
HALO_BANDS = 10            # the halo profile: ten bands, 0.2 line heights out from the letters
HALO_FAR_POINT = 0.25      # each pixel is compared with the picture this many line heights further out


# ------------------------------------------------------------------ colour

def _lab(rgb):
    rgb = np.asarray(rgb, dtype=np.float64).reshape(-1, 3) / 255.0
    linear = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    xyz = linear @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def delta_e(first, second):
    """CIEDE2000 between two '#RRGGBB' colours."""
    one, two = _lab([_rgb(first)])[0], _lab([_rgb(second)])[0]
    l1, a1, b1 = one
    l2, a2, b2 = two
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    mean_c = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(mean_c ** 7 / (mean_c ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + g), a2 * (1 + g)
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dl, dc = l2 - l1, c2p - c1p
    dh = 0 if c1p * c2p == 0 else (h2p - h1p if abs(h2p - h1p) <= 180 else h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360)
    dhh = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))
    ml, mc = (l1 + l2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        mh = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        mh = (h1p + h2p) / 2
    else:
        mh = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(mh - 30)) + 0.24 * math.cos(math.radians(2 * mh))
         + 0.32 * math.cos(math.radians(3 * mh + 6)) - 0.20 * math.cos(math.radians(4 * mh - 63)))
    sl = 1 + 0.015 * (ml - 50) ** 2 / math.sqrt(20 + (ml - 50) ** 2)
    sc, sh = 1 + 0.045 * mc, 1 + 0.015 * mc * t
    rt = (-2 * math.sqrt(mc ** 7 / (mc ** 7 + 25 ** 7))
          * math.sin(math.radians(60 * math.exp(-((mh - 275) / 25) ** 2))))
    return math.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhh / sh) ** 2 + rt * (dc / sc) * (dhh / sh))


def _rgb(value):
    value = str(value).lstrip('#')
    return [int(value[index:index + 2], 16) for index in (0, 2, 4)]


def _hex(rgb):
    return '#%02X%02X%02X' % tuple(int(round(float(channel))) for channel in rgb)


def _median_colour(pixels):
    if not len(pixels):
        return None
    return _hex(np.median(np.asarray(pixels, dtype=np.float64).reshape(-1, 3), axis=0))


# ------------------------------------------------------------------ shape measures of a binary mask

def _lines(mask):
    rows = mask.any(axis=1)
    lines, start = [], None
    for index, value in enumerate(list(rows) + [False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            lines.append((start, index))
            start = None
    if not lines:
        return []
    tallest = max(bottom - top for top, bottom in lines)
    lines = [line for line in lines if line[1] - line[0] >= 0.3 * tallest]  # dots and stray specks are not lines
    out = []
    for top, bottom in lines:
        columns = np.where(mask[top:bottom].any(axis=0))[0]
        out.append({'top': top, 'bottom': bottom, 'left': int(columns.min()), 'right': int(columns.max()) + 1})
    return out


def _stroke(mask):
    import cv2
    if not mask.any():
        return None
    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    ridge = (distance >= cv2.dilate(distance, np.ones((3, 3), np.uint8)) - 1e-6) & (distance >= 1)
    if not ridge.any():
        return None
    return float(2 * np.median(distance[ridge]) - 1)


def _slant(mask):
    import cv2
    rows, columns = np.where(mask)
    if len(rows) < 30:
        return None
    centre = rows.mean()

    def sharpness(angle):
        shifted = np.round(columns + math.tan(math.radians(angle)) * (rows - centre)).astype(np.int64)
        histogram = np.bincount(shifted - shifted.min())
        return float((histogram.astype(np.float64) ** 2).sum())

    coarse = max(range(-30, 31), key=sharpness)
    fine = max(np.arange(coarse - 1, coarse + 1.01, 0.25), key=sharpness)
    del cv2
    return float(fine)


def _words(mask, line, height):
    """Column runs of one line split at gaps of at least 0.28 line heights: the words."""
    columns = mask[line['top']:line['bottom']].any(axis=0)
    gap = max(2, int(round(0.28 * height)))
    runs, start, empty = [], None, 0
    for index, value in enumerate(list(columns) + [False] * (gap + 1)):
        if value:
            if start is None:
                start = index
            empty = 0
        elif start is not None:
            empty += 1
            if empty >= gap:
                runs.append((start, index - empty + 1))
                start, empty = None, 0
    return runs


def text_measures(mask, colour_image, text, frame_size, scale=1):
    """Measures of a text mask. mask and colour_image share one (upscaled) grid; frame_size is the native frame."""
    import cv2
    width, height = frame_size
    lines = _lines(mask)
    if not lines:
        return {'reliable': False, 'reason': 'no ink found'}
    heights = [line['bottom'] - line['top'] for line in lines]
    line_height = float(np.median(heights))
    characters = len(re.sub(r'\s', '', text))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    glyphs = sum(1 for index in range(1, count) if stats[index, cv2.CC_STAT_HEIGHT] >= 0.25 * line_height)
    letters = len(re.sub(r'[\W_]', '', text))
    reliable = letters == 0 or 0.45 <= glyphs / max(1, letters) <= 1.7
    eroded = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=max(1, scale // 2)) > 0
    core = eroded if eroded.sum() >= 0.15 * mask.sum() else mask
    stroke = _stroke(mask)
    ink_width = sum(line['right'] - line['left'] for line in lines)
    words = []
    for line in lines:
        for left, right in _words(mask, line, line['bottom'] - line['top']):
            region = core[line['top']:line['bottom'], left:right]
            pixels = colour_image[line['top']:line['bottom'], left:right][region]
            words.append(_median_colour(pixels))
    rows, columns = np.where(mask)
    box = [columns.min() / scale, rows.min() / scale, (columns.max() + 1) / scale, (rows.max() + 1) / scale]
    return {'reliable': bool(reliable), 'glyphs': int(glyphs), 'letters': letters,
            'lines': len(lines), 'line_height_px': round(line_height / scale, 2),
            'size': round(line_height / scale / height, 5),
            'stroke': None if stroke is None else round(stroke / line_height, 4),
            'width': round(ink_width / max(1, characters) / line_height, 4),
            'slant': _slant(mask), 'colour': _median_colour(colour_image[core]),
            'word_colours': [colour for colour in words if colour],
            'box': [round(value, 1) for value in box],
            'centre': [round((box[0] + box[2]) / 2 / width, 4), round((box[1] + box[3]) / 2 / height, 4)]}


def mark_measures(mask, colour_image, frame_size, scale=1):
    width, height = frame_size
    if not mask.any():
        return {'reliable': False, 'reason': 'no ink found'}
    rows, columns = np.where(mask)
    box = [columns.min() / scale, rows.min() / scale, (columns.max() + 1) / scale, (rows.max() + 1) / scale]
    area = max(1.0, (box[2] - box[0]) * (box[3] - box[1]) * scale * scale)
    return {'reliable': True, 'colour': _median_colour(colour_image[mask]),
            'height': round((box[3] - box[1]) / height, 5), 'width': round((box[2] - box[0]) / width, 5),
            'fill': round(float(mask.sum()) / area, 4), 'box': [round(value, 1) for value in box],
            'centre': [round((box[0] + box[2]) / 2 / width, 4), round((box[1] + box[3]) / 2 / height, 4)]}


def halo(colour, box, fill, line_height):
    """The outline and shadow around a text's letters, measured the same way on both sides. colour: an RGB crop
    reaching half a line height past the text; box: the text's ink box in the crop; fill: the letters' own colour;
    line_height in the crop's pixels.

    The letters are the pixels near the fill colour inside the box. Each pixel around them is compared with the
    picture a quarter line height further out along the same line from its nearest letter (what is behind the text
    there, past any halo); pixels whose far point is no further from every letter are left out. Around the letters,
    bands 0.02 line heights wide are read outward; a band is halo when the median change from that far point is large
    and doesn't point toward the fill (an anti-aliased or blurred edge is a blend toward the fill). The outline is
    the run of halo bands all round the letters; past it, a shadow is a run of halo bands on one side longer than on
    the opposite side. Returns outline (line heights, 0 for none), outline_colour, shadow {angle (degrees; 90 is
    straight down), reach (line heights past the letters or outline), colour} or None, and the profile (each band's
    change all round and on each side); or measured False with the reason."""
    import cv2
    height, width = colour.shape[:2]
    lab = _lab(colour.reshape(-1, 3)).reshape(height, width, 3)
    fill_lab = _lab([_rgb(fill)])[0]
    to_fill = np.sqrt(((lab - fill_lab) ** 2).sum(axis=2))
    letters = _letters(to_fill, box, line_height, (height, width))
    if letters.sum() < 50:
        return {'measured': False, 'reason': 'letter fill not found'}
    distance, labels = cv2.distanceTransformWithLabels((~letters).astype(np.uint8), cv2.DIST_L2, 5,
                                                       labelType=cv2.DIST_LABEL_PIXEL)
    reach = distance / line_height
    ys, xs = np.nonzero(letters)
    near_x, near_y = np.zeros(labels.max() + 1), np.zeros(labels.max() + 1)
    near_x[labels[ys, xs]], near_y[labels[ys, xs]] = xs, ys
    rows, columns = np.nonzero(~letters & (reach > 0) & (reach <= 0.3))
    nearest = labels[rows, columns]
    dx, dy = columns - near_x[nearest], rows - near_y[nearest]
    length = np.maximum(np.hypot(dx, dy), 1e-6)
    far_x = np.round(columns + dx / length * HALO_FAR_POINT * line_height).astype(int)
    far_y = np.round(rows + dy / length * HALO_FAR_POINT * line_height).astype(int)
    inside = (far_x >= 0) & (far_x < width) & (far_y >= 0) & (far_y < height)
    usable = np.zeros(len(rows), bool)
    usable[inside] = reach[far_y[inside], far_x[inside]] >= reach[rows[inside], columns[inside]] + 0.6 * HALO_FAR_POINT
    rows, columns, dx, dy = rows[usable], columns[usable], dx[usable], dy[usable]
    if len(rows) < 80:
        return {'measured': False, 'reason': 'no room around the letters in the frame'}
    outside = np.zeros((height, width), bool)
    outside[rows, columns] = True
    behind = np.zeros_like(lab)
    behind[rows, columns] = lab[far_y[usable], far_x[usable]]
    zone = outside
    change = lab - behind
    toward = fill_lab[None, None, :] - behind
    span = np.sqrt((toward ** 2).sum(axis=2))
    if float(np.median(span[zone])) < HALO_FAR:
        return {'measured': False, 'reason': 'the background behind the letters is their own colour'}
    unit = toward / np.maximum(span, 1e-6)[:, :, None]
    angle = np.degrees(np.arctan2(dy, dx)) % 360

    def band_halo(band):
        if band.sum() < 20:
            return None
        median = np.median(change[band], axis=0)
        size = float(np.sqrt((median ** 2).sum()))
        along = float(np.dot(median, np.median(unit[band], axis=0)))
        return size > HALO_FAR and along < HALO_TOWARD * size

    def band_strength(band):
        """The band's median change from what is behind it, less any part toward the fill (Lab units)."""
        if band.sum() < 20:
            return None
        median = np.median(change[band], axis=0)
        direction = np.median(unit[band], axis=0)
        along = max(0.0, float(np.dot(median, direction)))
        return round(float(np.sqrt(((median - along * direction) ** 2).sum())), 1)

    outline = _run(outside, reach, band_halo, 0.0, 0.30)
    ring = outside & (reach <= outline)
    if outline:
        strength = np.sqrt((change[ring] ** 2).sum(axis=1))
        outline_colour = _hex(_srgb(np.median(lab[ring][strength >= np.percentile(strength, 50)], axis=0)))
    result = {'measured': True, 'outline': outline,
              'background': _hex(_srgb(np.median(behind[zone], axis=0))),
              'outline_colour': outline_colour if outline else None, 'shadow': None}
    sector = ((angle + 22.5) // 45).astype(int) % 8
    sides = {'round': outside}
    for name, middle in (('right', 0), ('down', 90), ('left', 180), ('up', 270)):
        region = np.zeros((height, width), bool)
        pick = ((angle - middle + 45) % 360) < 90
        region[rows[pick], columns[pick]] = True
        sides[name] = region
    result['profile'] = {name: [band_strength(region & (reach > HALO_BAND * index) & (reach <= HALO_BAND * (index + 1)))
                                for index in range(HALO_BANDS)] for name, region in sides.items()}
    runs = []
    for index in range(8):
        region = np.zeros((height, width), bool)
        region[rows[sector == index], columns[sector == index]] = True
        runs.append(round(_run(region, reach, band_halo, outline, outline + 0.25) - outline, 3))
    result['runs'] = runs
    side = int(np.argmax(runs))
    if runs[side] < 2 * HALO_BAND - 1e-9 or runs[(side + 4) % 8] > 0.5 * runs[side]:
        return result
    weights = np.array([runs[(side + offset) % 8] for offset in (-1, 0, 1)])
    turns = np.radians([45.0 * ((side + offset) % 8) for offset in (-1, 0, 1)])
    heading = math.degrees(math.atan2((weights * np.sin(turns)).sum(), (weights * np.cos(turns)).sum())) % 360
    region = np.zeros((height, width), bool)
    region[rows[sector == side], columns[sector == side]] = True
    shadow = region & (reach > outline) & (reach <= outline + runs[side])
    strength = np.sqrt((change[shadow] ** 2).sum(axis=1))
    core = strength >= np.percentile(strength, 50)
    result['shadow'] = {'angle': round(heading, 1), 'reach': runs[side],
                        'colour': _hex(_srgb(np.median(lab[shadow][core], axis=0)))}
    return result


def profile_difference(first, second):
    """The largest band-by-band difference between two halo profiles (Lab units) for each side, and overall."""
    out = {}
    for name in first:
        pairs = [(a, b) for a, b in zip(first[name], second.get(name, [])) if a is not None and b is not None]
        out[name] = round(max(abs(a - b) for a, b in pairs), 1) if pairs else None
    return out


def _run(region, reach, is_halo, start, limit):
    """How far out (line heights) the bands of `region` from `start` stay halo. The run may begin up to two bands
    out: the first pixels past an edge are a blend of the two sides."""
    edge, found = start, False
    while edge < limit:
        verdict = is_halo(region & (reach > edge) & (reach <= edge + HALO_BAND))
        if verdict:
            found = True
        elif found or verdict is None or edge >= start + 2 * HALO_BAND - 1e-9:
            break
        edge = round(edge + HALO_BAND, 3)
    return edge if found else start


def _letters(to_fill, box, line_height, shape):
    """Pixels near the fill colour inside the text's box (a little margin around it)."""
    margin = 0.06 * line_height
    x0, y0 = max(0, int(box[0] - margin)), max(0, int(box[1] - margin))
    x1, y1 = min(shape[1], int(math.ceil(box[2] + margin))), min(shape[0], int(math.ceil(box[3] + margin)))
    inside = np.zeros(shape, bool)
    inside[y0:y1, x0:x1] = True
    return inside & (to_fill < HALO_FILL)


def _srgb(lab):
    """Lab (D65) back to an sRGB triple, for reporting halo colours."""
    l, a, b = [float(value) for value in lab]
    fy = (l + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    xyz = [value ** 3 if value ** 3 > 216 / 24389 else (116 * value - 16) / (24389 / 27) for value in (fx, fy, fz)]
    xyz = np.array(xyz) * np.array([0.95047, 1.0, 1.08883])
    linear = np.linalg.solve(np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722],
                                       [0.0193, 0.1192, 0.9505]]), xyz)
    linear = np.clip(linear, 0, 1)
    return np.clip(np.where(linear > 0.0031308, 1.055 * linear ** (1 / 2.4) - 0.055, 12.92 * linear) * 255, 0, 255)


def _ink(crop, box, line, seed=None):
    """The text's ink in a native crop that reaches past it: pixels unlike the crop's border colours (two modes)
    inside the box and within 0.15 line heights of the segmented letters (`seed`, the same crop's text mask), in
    glyph-sized pieces. Letters, outlines and shadows alike, not what is behind them."""
    import cv2
    height, width = crop.shape[:2]
    lab = _lab(crop.reshape(-1, 3)).reshape(height, width, 3)
    border = np.zeros((height, width), bool)
    border[:2], border[-2:], border[:, :2], border[:, -2:] = True, True, True, True
    _, modes = _clusters(lab[border], 2)
    far = np.min(np.sqrt(((lab[:, :, None, :] - modes[None, None, :, :]) ** 2).sum(axis=3)), axis=2) > 25
    margin = int(math.ceil(0.08 * line))
    inside = np.zeros((height, width), bool)
    inside[max(0, int(box[1]) - margin):int(math.ceil(box[3])) + margin,
           max(0, int(box[0]) - margin):int(math.ceil(box[2])) + margin] = True
    if seed is not None:
        reach = int(math.ceil(0.15 * line))
        inside &= cv2.dilate(seed.astype(np.uint8), cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * reach + 1,) * 2)).astype(bool)
    count, labels, stats, _ = cv2.connectedComponentsWithStats((far & inside).astype(np.uint8), 8)
    keep = [index for index in range(1, count) if stats[index, cv2.CC_STAT_HEIGHT] >= 0.25 * line]
    return np.isin(labels, keep), lab


def fill_colour(crop, box, line, seed=None):
    """The letters' own colour: the ink deepest inside the text's ink (at least 60% of the thickest part's
    half-width in from its edge), so an outline or shadow around the letters doesn't count."""
    import cv2
    ink, _ = _ink(crop, box, line, seed)
    if not ink.any():
        return None
    distance = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 5)
    return _median_colour(crop[distance >= 0.6 * distance.max()])


def _text_zone(rgb, text):
    line = float(text['line_height_px'])
    box = text['box']
    pad = int(math.ceil(0.5 * line))
    x0, y0 = max(0, int(box[0]) - pad), max(0, int(box[1]) - pad)
    x1, y1 = min(rgb.shape[1], int(math.ceil(box[2])) + pad), min(rgb.shape[0], int(math.ceil(box[3])) + pad)
    return x0, y0, x1, y1, line, [box[0] - x0, box[1] - y0, box[2] - x0, box[3] - y0]


def painted_out(rgb, text, seed=None):
    """rgb with the text's ink (letters, outline, shadow) and 0.3 line heights around it painted in from what
    surrounds it: the background behind the text, native size."""
    import cv2
    x0, y0, x1, y1, line, box = _text_zone(rgb, text)
    crop = np.ascontiguousarray(rgb[y0:y1, x0:x1])
    ink, _ = _ink(crop, box, line, None if seed is None else seed[y0:y1, x0:x1])
    radius = int(math.ceil(0.32 * line)) + 2
    zone = cv2.dilate(ink.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1,) * 2))
    out = rgb.copy()
    out[y0:y1, x0:x1] = cv2.inpaint(crop, zone, 5, cv2.INPAINT_TELEA)
    return out


def edge_width(rgb, text, seed=None):
    """How soft the letters' edges are, in native pixels: the blend pixels between the fill and what borders it
    (a quarter to three quarters of the way across) per pixel of the letters' outline. Video compression and
    scaling widen it; a fresh drawing is about one pixel."""
    import cv2
    x0, y0, x1, y1, line, box = _text_zone(rgb, text)
    crop = _upscale(np.ascontiguousarray(rgb[y0:y1, x0:x1]))
    fill = fill_colour(np.ascontiguousarray(rgb[y0:y1, x0:x1]), box, line,
                       None if seed is None else seed[y0:y1, x0:x1])
    if not fill:
        return None
    lab = _lab(crop.reshape(-1, 3)).reshape(crop.shape)
    to_fill = np.sqrt(((lab - _lab([_rgb(fill)])[0]) ** 2).sum(axis=2))
    letters = _letters(to_fill, [value * UPSCALE for value in box], line * UPSCALE, crop.shape[:2])
    if letters.sum() < 50:
        return None
    reach = cv2.distanceTransform((~letters).astype(np.uint8), cv2.DIST_L2, 5) / UPSCALE
    near = ~letters & (reach <= 0.12 * line)
    contrast = float(np.percentile(to_fill[near], 90))
    if contrast < 2 * HALO_FILL:
        return None
    blend = near & (to_fill >= HALO_FILL) & (to_fill <= 0.75 * contrast)
    edge = letters & ~cv2.erode(letters.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    return round(float(blend.sum()) / max(1, edge.sum()) , 2)


def softened(drawn, ours, reference_width, seed=None):
    """Our composited drawing blurred so its letters' edges are as soft as the reference's (edge_width), so the
    halo is compared as it would look in the same video. Returns (picture, blur sigma in native pixels)."""
    import cv2
    if reference_width is None:
        return drawn, 0.0
    best = (abs((edge_width(drawn, ours, seed) or 0) - reference_width), 0.0, drawn)
    for sigma in (0.4, 0.6, 0.8, 1.0, 1.3, 1.6, 2.0, 2.5):
        picture = cv2.GaussianBlur(drawn, (0, 0), sigma)
        width = edge_width(picture, ours, seed)
        if width is None:
            continue
        gap = abs(width - reference_width)
        if gap < best[0]:
            best = (gap, sigma, picture)
    return best[2], best[1]


def our_halo(rgba, ours, behind, theirs):
    """Our drawing's halo: drawn over the reference's own background with its text painted out (`behind`),
    softened to the reference's edge sharpness, then measured as the reference was."""
    seed = _letter_seed(rgba, ours)
    drawn, sigma = softened(composite(rgba, behind), ours, theirs.get('edge_width'), seed)
    return {**text_halo(drawn, ours, seed), 'softened_px': sigma}


def _letter_seed(rgba, text):
    """Our letters as a mask: the drawn pixels inside the measured text box (the plate around them is not)."""
    seed = np.zeros(rgba.shape[:2], bool)
    x0, y0, x1, y1 = [int(round(value)) for value in text['box']]
    seed[y0:y1, x0:x1] = rgba[y0:y1, x0:x1, 3] >= 128
    if text.get('plate', {}).get('found') and text.get('colour'):
        lab = _lab(rgba[y0:y1, x0:x1, :3].reshape(-1, 3)).reshape(y1 - y0, x1 - x0, 3)
        seed[y0:y1, x0:x1] &= np.sqrt(((lab - _lab([_rgb(text['colour'])])[0]) ** 2).sum(axis=2)) < 2 * HALO_FILL
    return seed


def text_halo(rgb, text, seed=None):
    """halo() for a measured text (its box and line height in rgb's native pixels; seed: its segmented letters, the
    same size as rgb): the fill found by fill_colour, a crop half a line height wider on every side, upscaled as the
    other text measures are."""
    x0, y0, x1, y1, line, box = _text_zone(rgb, text)
    native = np.ascontiguousarray(rgb[y0:y1, x0:x1])
    fill = fill_colour(native, box, line, None if seed is None else seed[y0:y1, x0:x1])
    if not fill:
        return {'measured': False, 'reason': 'letter fill not found'}
    crop = _upscale(native)
    result = halo(crop, [value * UPSCALE for value in box], fill, line * UPSCALE)
    return {**result, 'fill': fill}


# ------------------------------------------------------------------ the reference side

def _upscale(image):
    import cv2
    return cv2.resize(image, (image.shape[1] * UPSCALE, image.shape[0] * UPSCALE), interpolation=cv2.INTER_CUBIC)


def _clusters(pixels_lab, count):
    import cv2
    data = np.asarray(pixels_lab, dtype=np.float32)
    count = max(1, min(count, len(data)))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, labels, centres = cv2.kmeans(data, count, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    return labels.ravel(), centres


def _box(part, size):
    box = part.get('box')
    if (not isinstance(box, list) or len(box) != 4 or any(type(value) not in (int, float) for value in box)
            or not 0 <= box[0] < box[2] <= size[0] or not 0 <= box[1] < box[3] <= size[1]):
        raise ValueError(f"part {part.get('id')}: box is [x0, y0, x1, y1] pixels inside the reference frame")
    return [int(value) for value in box]


def reference_ink(crop_rgb, ink=None, plate=False):
    """Boolean ink mask of an (upscaled) RGB crop. The background is the colours on the crop's border (up to two
    modes); the ink's core colours are the two clusters of the 12% of pixels farthest from them. Each pixel goes to
    the nearest of these colours, which puts an anti-aliased edge at its half-way blend (as alpha >= 128 does for our
    drawing). With `ink` colours given, they replace the core colours."""
    import cv2
    height, width = crop_rgb.shape[:2]
    lab = _lab(crop_rgb.reshape(-1, 3))
    border = np.zeros((height, width), bool)
    ring = max(2, UPSCALE)
    border[:ring], border[-ring:], border[:, :ring], border[:, -ring:] = True, True, True, True
    edge = lab[border.ravel()]
    _, modes = _clusters(edge, 1 if plate else 2)
    distance = np.min(np.sqrt(((lab[:, None, :] - modes[None, :, :]) ** 2).sum(axis=2)), axis=1)
    if ink:
        hints = _lab([_rgb(colour) for colour in ink])
        to_ink = np.min(np.sqrt(((lab[:, None, :] - hints[None, :, :]) ** 2).sum(axis=2)), axis=1)
        return (to_ink < distance).reshape(height, width)
    core = lab[distance >= np.percentile(distance, 88)]
    _, centres = _clusters(core, 2)
    anchors = np.vstack([centres, modes])
    nearest = np.argmin(((lab[:, None, :] - anchors[None, :, :]) ** 2).sum(axis=2), axis=1)
    del cv2
    return (nearest < len(centres)).reshape(height, width)


BLEND_MARGIN = 0.5          # one way of compositing fits when its error is at most half the other's
BLEND_TONES = 0.05          # the picture behind the letters varies at least this much (0-1), or the fit can't tell


def letter_blend(frame_rgb, text, mask, origin):
    """How a reference's letters meet the picture under them, from its one frame: the letters' glyph cores (the ink
    mask shrunk off its anti-aliased edge) against the picture behind them, painted in from around the letters. Plain
    letters keep one colour whatever is under them ('normal'); white letters composited with Difference (or Exclusion:
    the same result) show the inverse of the picture under them, so they change with the shot ('difference').
    Unresolved when the picture behind is too even to tell them apart, or neither fits clearly."""
    import cv2
    import letitedit.looks.style_import_visual as style_import_visual
    height, width = frame_rgb.shape[:2]
    rows, columns = mask.shape[0] // UPSCALE, mask.shape[1] // UPSCALE
    cells = mask[:rows * UPSCALE, :columns * UPSCALE].reshape(rows, UPSCALE, columns, UPSCALE)
    x0, y0 = origin
    seed = np.zeros((height, width), bool)
    core = np.zeros((height, width), bool)
    seed[y0:y0 + rows, x0:x0 + columns] = cells.any(axis=(1, 3))[:height - y0, :width - x0]
    inner = cv2.erode(cells.all(axis=(1, 3)).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    core[y0:y0 + rows, x0:x0 + columns] = inner[:height - y0, :width - x0]
    if core.sum() < 32:
        return {'measured': False, 'reason': 'too few glyph-core pixels to fit how the letters are composited'}
    behind = painted_out(frame_rgb, text, seed)
    zx0, zy0, zx1, zy1, _, _ = _text_zone(frame_rgb, text)
    try:
        fit = style_import_visual.fit_blend(behind[zy0:zy1, zx0:zx1] / 255.0, frame_rgb[zy0:zy1, zx0:zx1] / 255.0,
                                            core[zy0:zy1, zx0:zx1])
    except ValueError as error:
        return {'measured': False, 'reason': str(error)}
    errors = {item['mode']: item['rmse'] for item in fit['fits']}
    colours = {item['mode']: item['colour_rgb'] for item in fit['fits']}
    inverted = min(errors['difference'], errors['exclusion'])
    found = {'rmse': {mode: errors[mode] for mode in ('normal', 'difference', 'exclusion')},
             'pixels': fit['pixels'], 'tones_behind': round(fit['background_tonal_variation'], 4),
             'scope': 'one reference frame; the picture behind the letters is painted in from around them'}
    if fit['background_tonal_variation'] < BLEND_TONES:
        return {**found, 'measured': False, 'reason': 'the picture behind the letters is too even to tell plain '
                                                      'letters from inverted ones'}
    if inverted <= BLEND_MARGIN * errors['normal']:
        mode = 'difference' if errors['difference'] <= errors['exclusion'] else 'exclusion'
        return {**found, 'measured': True, 'mode': 'difference', 'candidates': ['difference', 'exclusion'],
                'colour': _hex([255 * channel for channel in colours[mode]]),
                'reason': 'the letters show the inverse of the picture under them (white Difference and Exclusion '
                          'look the same)'}
    if errors['normal'] <= BLEND_MARGIN * inverted:
        return {**found, 'measured': True, 'mode': 'normal', 'candidates': ['normal'],
                'colour': _hex([255 * channel for channel in colours['normal']]),
                'reason': 'the letters keep one colour whatever is under them'}
    return {**found, 'measured': False, 'reason': 'neither plain nor inverted letters fit clearly'}


def measure_reference(frame_rgb, part):
    """Numbers for one declared part of a reference frame (RGB array, native size)."""
    size = (frame_rgb.shape[1], frame_rgb.shape[0])
    x0, y0, x1, y1 = _box(part, size)
    kind = part.get('kind')
    if kind == 'text':
        # a margin around the declared box, so its border is background; letters that touch the declared box
        # are kept whole, anything else in the margin is dropped
        import cv2
        pad = max(4, int(round(0.2 * (y1 - y0))))
        bx0, by0 = max(0, x0 - pad), max(0, y0 - pad)
        bx1, by1 = min(size[0], x1 + pad), min(size[1], y1 + pad)
        crop = _upscale(frame_rgb[by0:by1, bx0:bx1])
        mask = reference_ink(crop, part.get('ink'), bool(part.get('plate')))
        count, labels = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
        inner = labels[(y0 - by0) * UPSCALE:(y1 - by0) * UPSCALE, (x0 - bx0) * UPSCALE:(x1 - bx0) * UPSCALE]
        keep = np.unique(inner[inner > 0])
        mask = np.isin(labels, keep)
        x0, y0 = bx0, by0
        measures = text_measures(mask, crop, part['text'], size, UPSCALE)
        measures = _shift(measures, x0, y0, size)
        measures['_mask'] = mask
        if measures.get('lines'):
            measures['blend'] = letter_blend(frame_rgb, measures, mask, (x0, y0))
        if HALO and measures.get('lines'):
            seed = np.zeros(frame_rgb.shape[:2], bool)
            small = mask[:mask.shape[0] // UPSCALE * UPSCALE, :mask.shape[1] // UPSCALE * UPSCALE]
            small = small.reshape(small.shape[0] // UPSCALE, UPSCALE, small.shape[1] // UPSCALE, UPSCALE).any(axis=(1, 3))
            seed[y0:y0 + small.shape[0], x0:x0 + small.shape[1]] = small
            behind = painted_out(frame_rgb, measures, seed)
            measures['halo'] = {**text_halo(frame_rgb, measures, seed),
                                'edge_width': edge_width(frame_rgb, measures, seed)}
            measures['_behind'] = behind
        if part.get('plate') and measures.get('lines'):
            measures['plate'] = reference_plate(frame_rgb, measures, part, mask, (x0, y0))
        return measures
    crop = _upscale(frame_rgb[y0:y1, x0:x1])
    if kind in ('mark', 'picture'):
        if kind == 'picture':
            mask = np.ones(crop.shape[:2], bool)
        else:
            mask = reference_ink(crop, part.get('ink'))
        return _shift(mark_measures(mask, crop, size, UPSCALE), x0, y0, size)
    raise ValueError(f"part {part.get('id')}: kind is text, mark or picture")


def _shift(measures, x0, y0, size):
    if 'box' in measures:
        box = measures['box']
        measures['box'] = [round(box[0] + x0, 1), round(box[1] + y0, 1), round(box[2] + x0, 1), round(box[3] + y0, 1)]
        measures['centre'] = [round((measures['box'][0] + measures['box'][2]) / 2 / size[0], 4),
                              round((measures['box'][1] + measures['box'][3]) / 2 / size[1], 4)]
    return measures


def _strongest_step(profile, low, high, inward):
    """Index in [low, high) where a 1-D colour profile changes most (across 4 samples, for soft edges)."""
    low, high = max(2, low), min(len(profile) - 2, high)
    if high - low < 2:
        return None
    steps = np.sqrt(((profile[low + 2:high + 2] - profile[low - 2:high - 2]) ** 2).sum(axis=1))
    if not len(steps) or steps.max() < 3:
        return None
    return low + int(np.argmax(steps)) + (0 if inward > 0 else 0)


def _filled(values, good, fallback):
    """values where good; elsewhere interpolated between good neighbours (letters fill those rows or columns)."""
    if good.all():
        return values
    if not good.any():
        return fallback
    index = np.arange(len(values))
    return np.stack([np.interp(index, index[good], values[good, channel]) for channel in range(values.shape[1])], axis=1)


def plate_edges(lab, text_box, line, hint=None, skip=None):
    """Plate box and corner radius from colour steps around a text box. lab is HxWxC (Lab, or 100 x plate alpha
    for our drawing); rows and columns through the text are averaged, leaving out `skip` (the text's own letters).
    The plate edge on each side is the strongest step within 3 line heights, or, with a rough hint box, within 0.4
    line heights of the hint's side."""
    height, width = lab.shape[:2]
    x0, y0, x1, y1 = [int(round(value)) for value in text_box]
    reach, inner = int(3 * line), max(1, int(0.08 * (x1 - x0)))
    columns = slice(max(0, x0 + inner), max(x0 + inner + 1, x1 - inner))
    rows = slice(max(0, y0 + int(0.25 * (y1 - y0))), max(y0 + 1, y1 - int(0.25 * (y1 - y0))))
    vertical = lab[:, columns].mean(axis=1)
    horizontal = lab[rows, :].mean(axis=0)
    if skip is not None:
        keep = (~skip).astype(np.float64)[:, :, None]
        kept_v, kept_h = keep[:, columns].sum(axis=1), keep[rows, :].sum(axis=0)
        enough_v = kept_v[:, 0] >= 0.3 * keep[:, columns].shape[1]
        enough_h = kept_h[:, 0] >= 0.3 * keep[rows, :].shape[0]
        vertical = _filled(((lab[:, columns] * keep[:, columns]).sum(axis=1) / np.maximum(1, kept_v)), enough_v, vertical)
        horizontal = _filled(((lab[rows, :] * keep[rows, :]).sum(axis=0) / np.maximum(1, kept_h)), enough_h, horizontal)
    if hint:
        near = max(2, int(0.4 * line))
        hx0, hy0, hx1, hy1 = [int(round(value)) for value in hint]
        spans = {'top': (max(1, hy0 - near), min(y0 - 1, hy0 + near)), 'bottom': (max(y1 + 1, hy1 - near), min(height - 2, hy1 + near)),
                 'left': (max(1, hx0 - near), min(x0 - 1, hx0 + near)), 'right': (max(x1 + 1, hx1 - near), min(width - 2, hx1 + near))}
    else:
        spans = {'top': (max(1, y0 - reach), y0 - 1), 'bottom': (y1 + 1, min(height - 2, y1 + reach)),
                 'left': (max(1, x0 - reach), x0 - 1), 'right': (x1 + 1, min(width - 2, x1 + reach))}
    limits = {'top': spans['top'][0], 'bottom': spans['bottom'][1], 'left': spans['left'][0], 'right': spans['right'][1]}
    top = _strongest_step(vertical, *spans['top'], -1)
    bottom = _strongest_step(vertical, *spans['bottom'], 1)
    left = _strongest_step(horizontal, *spans['left'], -1)
    right = _strongest_step(horizontal, *spans['right'], 1)
    found = {'top': top, 'bottom': bottom, 'left': left, 'right': right}
    open_sides = [side for side, value in found.items() if value is None]
    if len(open_sides) == 4:
        return None
    # one side without an edge runs past the search (a band to the frame's edge): it ends at the search limit
    top = limits['top'] - 1 if top is None else top
    left = limits['left'] - 1 if left is None else left
    bottom = limits['bottom'] if bottom is None else bottom
    right = limits['right'] if right is None else right
    top, left = top + 1, left + 1
    plate_height = bottom - top + 1
    radii = []
    for corner_x, direction_x, corner_y, direction_y in ((left, 1, top, 1), (right, -1, top, 1),
                                                        (left, 1, bottom, -1), (right, -1, bottom, -1)):
        radius = plate_height / 2
        for step in range(0, int(plate_height / 2)):
            y = corner_y + direction_y * step
            band = lab[max(0, y - 1):y + 2]
            row = np.median(band, axis=0)
            if direction_x > 0:
                found = _strongest_step(row, max(1, corner_x - 4), corner_x + int(plate_height / 2) + 2, 1)
            else:
                found = _strongest_step(row, corner_x - int(plate_height / 2) - 2, min(width - 2, corner_x + 4), -1)
            inset = None if found is None else abs((found + (1 if direction_x > 0 else 0)) - corner_x)
            if inset is not None and inset <= 1:
                radius = step
                break
        radii.append(radius)
    return {'box': [left, top, right + 1, bottom + 1], 'radius_px': float(np.median(radii)),
            'plate_height': plate_height, 'open_sides': open_sides}


def _plate_numbers(edges, text, frame_size, colour):
    width, height = frame_size
    x0, y0, x1, y1 = text['box']
    line = text['line_height_px']
    left, top, right, bottom = edges['box']
    sides = {'left': x0 - left, 'right': right - x1, 'top': y0 - top, 'bottom': bottom - y1}
    shut = {side: value for side, value in sides.items() if side not in edges.get('open_sides', [])}

    def mean(names):
        values = [shut[name] for name in names if name in shut]
        return round(sum(values) / len(values) / line, 3) if values else None

    return {'found': True, 'colour': colour, 'open_sides': edges.get('open_sides', []),
            'padding_sides': {side: round(value / line, 3) for side, value in shut.items()},
            'radius': None if edges.get('open_sides') else round(min(0.5, edges['radius_px'] / edges['plate_height']), 4),
            'padding_x': mean(('left', 'right')),
            'padding_y': mean(('top', 'bottom')),
            'box': [float(left), float(top), float(right), float(bottom)],
            'centre': [round((left + right) / 2 / width, 4), round((top + bottom) / 2 / height, 4)]}


def reference_plate(frame_rgb, text, part, text_mask=None, text_origin=(0, 0)):
    """The plate around a measured text box, from the colour steps around it."""
    height, width = frame_rgb.shape[:2]
    lab = _lab(frame_rgb.reshape(-1, 3)).reshape(height, width, 3)
    hint = part.get('plate_box')
    if hint is not None:
        _box({'id': part.get('id'), 'box': hint}, (width, height))
    line = text['line_height_px']
    skip = np.zeros((height, width), bool)
    if text_mask is not None:
        mx0, my0 = text_origin
        small = text_mask[::UPSCALE, ::UPSCALE]
        skip[my0:my0 + small.shape[0], mx0:mx0 + small.shape[1]] = small[:height - my0, :width - mx0]
        import cv2
        skip = cv2.dilate(skip.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    edges = plate_edges(lab, text['box'], line, hint, skip)
    if edges is None:
        return {'found': False, 'reason': 'no plate edge around the text'}
    left, top, right, bottom = edges['box']
    x0, y0, x1, y1 = [int(round(value)) for value in text['box']]
    inside = np.zeros((height, width), bool)
    inside[top + 2:bottom - 2, left + 2:right - 2] = True
    inside[max(0, y0 - 2):y1 + 2, max(0, x0 - 2):x1 + 2] = False
    if not inside.any():
        return {'found': False, 'reason': 'plate too small to measure'}
    return _plate_numbers(edges, text, (width, height), _median_colour(frame_rgb[inside]))


# ------------------------------------------------------------------ our side: the family drawn in passes

def _passes(recipe, drawing, size, moment, only=None):
    """RGBA of the family at `moment`: 'full', or only text whose words are in `only` ('text'), or no text ('shapes'),
    or only the picture at path `only` ('picture'). Returns (image, text calls)."""
    import letitedit.pictures.graphics as graphics
    calls = []
    mode, target = only if isinstance(only, tuple) else ('full', None)

    class Probe(graphics.Ctx):
        def text(self, xy, text, font_ref='body', size=54, *args, **kwargs):
            face = self.kit.font(font_ref, 'body')
            words = ' '.join(str(text).split())
            calls.append({'text': words, 'family': face['family'], 'weight': face['weight'],
                          'italic': face['italic'], 'size_px': round(self.s(size), 1)})
            if mode == 'shapes' or mode == 'picture' or (mode == 'text' and not _belongs(words, target)):
                # drawn on a throwaway layer, so code that sizes a plate from the returned box still gets it exactly
                if 'on' not in kwargs and len(args) <= 9:
                    kwargs['on'] = self.layer()
                    return super().text(xy, text, font_ref, size, *args, **kwargs)
                return None
            return super().text(xy, text, font_ref, size, *args, **kwargs)

        def rect(self, *args, **kwargs):
            if mode in ('full', 'shapes'):
                return super().rect(*args, **kwargs)

        def line(self, *args, **kwargs):
            if mode in ('full', 'shapes'):
                return super().line(*args, **kwargs)

        def circle(self, *args, **kwargs):
            if mode in ('full', 'shapes'):
                return super().circle(*args, **kwargs)

        def image(self, path, *args, **kwargs):
            if mode in ('full', 'shapes') or (mode == 'picture' and str(path) == str(target)):
                return super().image(path, *args, **kwargs)

    original = graphics.Ctx
    graphics.Ctx = Probe
    try:
        _, picture = next(graphics.draw_frames(recipe, drawing, size[0], size[1], 30, times=[moment]))
        return np.asarray(picture.convert('RGBA')).copy(), calls
    finally:
        graphics.Ctx = original


def composite(rgba, background):
    """An RGBA drawing over a background (an RGB picture of the same size, or one '#RRGGBB' colour), as RGB."""
    alpha = rgba[:, :, 3:4].astype(np.float64) / 255
    under = (np.asarray(background, dtype=np.float64) if not isinstance(background, str)
             else np.array(_rgb(background), dtype=np.float64))
    return np.clip(rgba[:, :, :3] * alpha + under * (1 - alpha) + 0.5, 0, 255).astype(np.uint8)


def _belongs(words, target):
    words, target = ' '.join(str(words).split()).lower(), ' '.join(str(target).split()).lower()
    return bool(words) and (words in target or target in words)


def _declared_ink(rgba, ink, drawn):
    """Our letters by the same rule as a reference part with declared ink colours (reference_ink): a drawn pixel is ink
    when it is nearer one of those colours than the background, here a flat grey, so an outline or shadow in another
    colour stays out of the letters on both sides. drawn is the upscaled alpha mask; returns a mask of its shape."""
    rows, columns = np.nonzero(rgba[:, :, 3])
    if not len(rows):
        return drawn
    pad = 4
    y0, y1 = max(0, rows.min() - pad), min(rgba.shape[0], rows.max() + 1 + pad)
    x0, x1 = max(0, columns.min() - pad), min(rgba.shape[1], columns.max() + 1 + pad)
    crop = rgba[y0:y1, x0:x1].astype(np.float64)
    weight = crop[:, :, 3:4] / 255
    flat = np.clip(crop[:, :, :3] * weight + 128 * (1 - weight) + 0.5, 0, 255).astype(np.uint8)
    mask = np.zeros_like(drawn)
    mask[y0 * UPSCALE:y1 * UPSCALE, x0 * UPSCALE:x1 * UPSCALE] = reference_ink(_upscale(flat), ink)
    return mask & drawn


def measure_ours(kit, family, content, part, size, moment):
    """Numbers for our family drawn with `content` (the part's slot holds the reference's words)."""
    import letitedit.looks.graphic_kit as graphic_kit
    import letitedit.pictures.graphics as graphics
    import letitedit.looks.style_pack as style_pack
    drawing = style_pack.Kit({**copy.deepcopy(style_pack.DEFAULTS), **kit['style']})
    seconds = max(moment + 1 / 30, float(family['duration_s'][1]) if family.get('persistence', 'transient') == 'transient'
                  else max(moment + 1, float(family['duration_s'][0])))
    recipe = graphics.normalise(graphic_kit.recipe(kit, family, content, seconds, check_duration=False), drawing)
    kind = part.get('kind')
    full, calls = _passes(recipe, drawing, size, moment)
    if kind == 'text':
        words = content[part['slot']]
        text_only, _ = _passes(recipe, drawing, size, moment, ('text', words))
        alpha = _upscale(text_only[:, :, 3]) >= 128
        if part.get('ink'):
            alpha = _declared_ink(text_only, part['ink'], alpha)
        colour = _upscale(text_only[:, :, :3])
        measures = text_measures(alpha, colour, part['text'], size, UPSCALE)
        faces = [call for call in calls if _belongs(call['text'], words)]
        measures['faces'] = [{key: call[key] for key in ('family', 'weight', 'italic', 'size_px')} for call in faces][:3]
        measures['blend'] = family.get('blend', 'normal')
        if measures.get('lines'):
            shapes, _ = _passes(recipe, drawing, size, moment, ('shapes', None))
            measures['plate'] = our_plate(shapes, measures)
            if HALO:
                measures['_rgba'] = full     # the whole piece: a plate behind the letters is part of what's around them
        return measures
    if kind == 'mark':
        shapes, _ = _passes(recipe, drawing, size, moment, ('shapes', None))
        window = _search_window(part, size)
        x0, y0, x1, y1 = window
        crop = shapes[y0:y1, x0:x1]
        mask = _upscale(crop[:, :, 3]) >= 128
        return _shift(mark_measures(mask, _upscale(crop[:, :, :3]), size, UPSCALE), x0, y0, size)
    if kind == 'picture':
        path = content.get(part['slot'])
        picture, _ = _passes(recipe, drawing, size, moment, ('picture', path))
        mask = picture[:, :, 3] >= 128
        return mark_measures(mask, picture[:, :, :3], size, 1)
    raise ValueError(f"part {part.get('id')}: kind is text, mark or picture")


def _search_window(part, size):
    x0, y0, x1, y1 = part['box']
    reach_x, reach_y = TOLERANCE['position'] * size[0], TOLERANCE['position'] * size[1]
    return [max(0, int(x0 - reach_x)), max(0, int(y0 - reach_y)),
            min(size[0], int(math.ceil(x1 + reach_x))), min(size[1], int(math.ceil(y1 + reach_y)))]


def our_plate(shapes, text):
    """Our plate: the opaque non-text drawing around the text box, found with the same edge method on alpha."""
    height, width = shapes.shape[:2]
    line = text['line_height_px']
    x0, y0, x1, y1 = [int(round(value)) for value in text['box']]
    gap = max(2, int(round(0.3 * line)))
    near = shapes[max(0, y0 - gap):y1 + gap, max(0, x0 - gap):x1 + gap, 3]
    if not near.size or (near >= 128).mean() < 0.6:
        return {'found': False}
    likeness = (shapes[:, :, 3:4] >= 128).astype(np.float64) * 100
    edges = plate_edges(likeness, text['box'], line)
    if edges is None:
        return {'found': False}
    left, top, right, bottom = edges['box']
    inside = np.zeros((height, width), bool)
    inside[top + 2:bottom - 2, left + 2:right - 2] = True
    flat = inside & (shapes[:, :, 3] >= 230)
    return _plate_numbers(edges, text, (width, height), _median_colour(shapes[:, :, :3][flat]))


# ------------------------------------------------------------------ comparison

def _row(name, reference, ours, tolerance, passed, unit=''):
    return {'measure': name, 'reference': reference, 'ours': ours, 'tolerance': tolerance, 'unit': unit,
            'passed': bool(passed)}


def _relative(name, reference, ours, key):
    if reference is None or ours is None:
        return _row(name, reference, ours, f'±{TOLERANCE[key]:.0%}', False)
    ratio = ours / reference if reference else float('inf')
    return _row(name, reference, ours, f'±{TOLERANCE[key]:.0%}', abs(ratio - 1) <= TOLERANCE[key] + 1e-9)


def _absolute(name, reference, ours, key, unit=''):
    if reference is None or ours is None:
        return _row(name, reference, ours, f'±{TOLERANCE[key]}', False, unit)
    return _row(name, reference, ours, f'±{TOLERANCE[key]}', abs(ours - reference) <= TOLERANCE[key] + 1e-9, unit)


def _colour(name, reference, ours, key):
    if not reference or not ours:
        return _row(name, reference, ours, f'dE00 <= {TOLERANCE[key]}', False)
    difference = delta_e(reference, ours)
    return {**_row(name, reference, ours, f'dE00 <= {TOLERANCE[key]}', difference <= TOLERANCE[key]),
            'delta_e': round(difference, 2)}


def compare(part, reference, ours):
    kind = part.get('kind')
    rows = []
    if not reference.get('reliable', True):
        rows.append(_row('reference measured', reference.get('reason') or
                         f"{reference.get('glyphs')} glyph shapes for {reference.get('letters')} letters", None, 'reliable', False))
    if not ours.get('reliable', True):
        rows.append(_row('ours measured', None, ours.get('reason') or
                         f"{ours.get('glyphs')} glyph shapes for {ours.get('letters')} letters", 'reliable', False))
    if kind == 'text':
        rows.append(_row('lines', reference.get('lines'), ours.get('lines'), 'equal', reference.get('lines') == ours.get('lines')))
        rows.append(_relative('text height / frame height', reference.get('size'), ours.get('size'), 'size'))
        rows.append(_relative('stroke / line height', reference.get('stroke'), ours.get('stroke'), 'stroke'))
        rows.append(_relative('width per letter / line height', reference.get('width'), ours.get('width'), 'width'))
        rows.append(_absolute('slant', reference.get('slant'), ours.get('slant'), 'slant', 'degrees'))
        reference_words, our_words = reference.get('word_colours') or [], ours.get('word_colours') or []
        blend = reference.get('blend') or {}
        if blend.get('measured'):
            mine = ours.get('blend', 'normal')
            rows.append({**_row('letter blend', '/'.join(blend['candidates']), mine, 'one of',
                                mine in blend['candidates']), 'why': blend['reason']})
        if blend.get('measured') and blend['mode'] != 'normal':
            # the reference's letters take their colour from the picture under them: the colour compared is the one
            # composited (the fit's), not the inverted picture seen inside them
            rows.append(_colour('text colour before the blend', blend['colour'], ours.get('colour'), 'text_colour'))
        elif len(reference_words) == len(our_words) and reference_words and len(set(reference_words)) > 1:
            for index, (first, second) in enumerate(zip(reference_words, our_words)):
                rows.append(_colour(f'text colour, word {index + 1}', first, second, 'text_colour'))
        else:
            rows.append(_colour('text colour', reference.get('colour'), ours.get('colour'), 'text_colour'))
        rows.append(_absolute('centre x / frame width', (reference.get('centre') or [None])[0],
                              (ours.get('centre') or [None])[0], 'position'))
        rows.append(_absolute('centre y / frame height', (reference.get('centre') or [None, None])[1],
                              (ours.get('centre') or [None, None])[1], 'position'))
        want_plate = bool(part.get('plate'))
        theirs, mine = reference.get('plate') or {}, ours.get('plate') or {}
        rows.append(_row('plate', 'yes' if want_plate else 'no', 'yes' if mine.get('found') else 'no', 'equal',
                         want_plate == bool(mine.get('found'))))
        if want_plate:
            if not theirs.get('found'):
                rows.append(_row('reference plate measured', theirs.get('reason', 'not found'), None, 'found', False))
            elif mine.get('found'):
                rows.append(_colour('plate colour', theirs['colour'], mine['colour'], 'plate_colour'))
                if theirs.get('radius') is not None:
                    rows.append(_absolute('corner radius / plate height', theirs['radius'], mine.get('radius'), 'radius'))
                # padding on the sides the reference's plate has (an edge that fades away is not compared)
                for name, sides in (('side padding / line height', ('left', 'right')),
                                    ('top-bottom padding / line height', ('top', 'bottom'))):
                    present = [side for side in sides if side in (theirs.get('padding_sides') or {})]
                    if not present:
                        continue
                    ours_sides = mine.get('padding_sides') or {}
                    reference_value = round(sum(theirs['padding_sides'][side] for side in present) / len(present), 3)
                    ours_value = (round(sum(ours_sides[side] for side in present) / len(present), 3)
                                  if all(side in ours_sides for side in present) else None)
                    label = name if len(present) == 2 else name.replace('side padding', present[0] + ' padding').replace('top-bottom padding', present[0] + ' padding')
                    rows.append(_absolute(label, reference_value, ours_value, 'padding'))
        rows.extend(halo_rows(reference.get('halo'), ours.get('halo')))
    else:
        rows.append(_relative('height / frame height', reference.get('height'), ours.get('height'), 'mark_size'))
        rows.append(_relative('width / frame width', reference.get('width'), ours.get('width'), 'mark_size'))
        if kind == 'mark':
            rows.append(_colour('colour', reference.get('colour'), ours.get('colour'), 'mark_colour'))
            rows.append(_relative('ink share of its box', reference.get('fill'), ours.get('fill'), 'fill'))
        rows.append(_absolute('centre x / frame width', (reference.get('centre') or [None])[0],
                              (ours.get('centre') or [None])[0], 'position'))
        rows.append(_absolute('centre y / frame height', (reference.get('centre') or [None, None])[1],
                              (ours.get('centre') or [None, None])[1], 'position'))
    return rows


def halo_summary(value):
    """A halo in plain words: outline width and colour, shadow side, reach and colour."""
    parts = [f"outline {value['outline']:g} line heights {value['outline_colour']}" if value.get('outline') else 'no outline']
    shadow = value.get('shadow')
    if shadow:
        sides = ['right', 'below right', 'below', 'below left', 'left', 'above left', 'above', 'above right']
        parts.append(f"shadow {sides[int(((shadow['angle'] + 22.5) % 360) // 45)]} reaching {shadow['reach']:g} "
                     f"line heights {shadow['colour']}")
    else:
        parts.append('no shadow')
    return '; '.join(parts)


def halo_rows(theirs, mine):
    """Outline and shadow rows. The pass is the halo profile: band by band (0.02 line heights, out to 0.2), all
    round the letters and on each side, how much the picture changes from what is behind it, our drawing softened to
    the reference's edge sharpness first. The summary (outline, shadow) is what the profile looks like in words.
    A reference halo that can't be read on its frame fails with the reason, so another frame (the text over a
    background unlike its letters) is chosen; it is never passed unmeasured."""
    if theirs is None:
        return []
    if not theirs.get('measured'):
        return [_row('outline and shadow measured', theirs.get('reason'), None, 'measured', False)]
    if not (mine or {}).get('measured'):
        return [_row('outline and shadow measured', None, (mine or {}).get('reason', 'not drawn'), 'measured', False)]
    difference = profile_difference(theirs['profile'], mine['profile'])
    worst = max((value for value in difference.values() if value is not None), default=None)
    rows = [{**_row('outline and shadow', halo_summary(theirs), halo_summary(mine),
                    f"halo profile within {TOLERANCE['halo']:g} (Lab) band by band, all round and on each side",
                    worst is not None and worst <= TOLERANCE['halo']), 'difference': difference}]
    if theirs.get('outline', 0) >= 2 * HALO_BAND and mine.get('outline', 0) >= 2 * HALO_BAND:
        rows.append(_colour('outline colour', theirs['outline_colour'], mine['outline_colour'], 'outline_colour'))
    return rows


# ------------------------------------------------------------------ timing in the reference video

def reference_span(video, frame_rgb, part, span):
    """When the part is on screen in the reference video: onset, offset and whether it stays to the end.
    Present at a time = at least 60% of the hold frame's ink pixels within dE76 15 of the hold frame, with at least
    60% of the hold frame's contrast between the ink and the rest of the part's box."""
    import cv2
    start, end = float(span[0]), float(span[1])
    capture = cv2.VideoCapture(str(video))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30
    duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    x0, y0, x1, y1 = _box(part, (frame_rgb.shape[1], frame_rgb.shape[0]))
    hold = frame_rgb[y0:y1, x0:x1]
    if part.get('kind') == 'picture':
        mask = np.ones(hold.shape[:2], bool)
    else:
        import cv2 as _cv
        mask = _cv.resize(reference_ink(_upscale(hold), part.get('ink'), bool(part.get('plate'))).astype(np.uint8),
                          (hold.shape[1], hold.shape[0]), interpolation=_cv.INTER_AREA) > 0
    if mask.sum() < 20:
        capture.release()
        return {'measured': False, 'reason': 'too little ink to follow'}
    hold_lab = _lab(hold[mask])
    others = ~mask
    if others.sum() < 20:
        others = np.ones(mask.shape, bool)

    def contrast(lab_ink, lab_rest):
        return float(np.sqrt(((np.median(lab_ink, axis=0) - np.median(lab_rest, axis=0)) ** 2).sum()))

    hold_contrast = contrast(hold_lab, _lab(hold[others]))

    def present(at):
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(round(at * fps)))
        ok, frame = capture.read()
        if not ok:
            return None
        crop = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)[y0:y1, x0:x1]
        ink = _lab(crop[mask])
        close = float((np.sqrt(((ink - hold_lab) ** 2).sum(axis=1)) < 15).mean())
        kept = contrast(ink, _lab(crop[others])) >= 0.6 * hold_contrast if part.get('kind') != 'picture' else True
        return close if kept else 0.0

    def edge(around, direction):
        times = [around + step / 10 for step in range(-10, 11)]
        times = [at for at in times if 0 <= at < duration]
        values = [(at, present(at)) for at in times]
        on = [at for at, value in values if value is not None and value >= 0.6]
        if not on:
            return None
        return min(on) if direction < 0 else max(on)

    try:
        onset = edge(start, -1)
        offset = edge(end, 1)
        middle = [present(at) for at in np.arange(start + 1, end - 1, 1.0)] if end - start > 2 else []
        continuous = all(value is not None and value >= 0.5 for value in middle)
        last = present(max(0, duration - 2 / fps))
    finally:
        capture.release()
    if onset is None or offset is None:
        return {'measured': False, 'reason': 'the part was not found on screen at the declared span'}
    return {'measured': True, 'onset_s': round(onset, 2), 'offset_s': round(offset + 0.1, 2),
            'duration_s': round(offset + 0.1 - onset, 2), 'continuous': continuous,
            'stays_to_end': bool(last is not None and last >= 0.6), 'video_s': round(duration, 2)}


def timing_rows(family, timing):
    persistence = family.get('persistence', 'transient')
    if not timing.get('measured'):
        return [_row('time on screen', timing.get('reason'), None, 'measured', False)]
    rows = [_row('stays to the video end', 'yes' if timing['stays_to_end'] else 'no',
                 'yes' if persistence in ('stays', 'accumulates') else 'no', 'equal',
                 timing['stays_to_end'] == (persistence in ('stays', 'accumulates')))]
    if persistence == 'transient':
        low, high = family['duration_s']
        rows.append(_row('seconds on screen', timing['duration_s'], f'{low}-{high}', f'±{TOLERANCE["duration"]} s',
                         low - TOLERANCE['duration'] <= timing['duration_s'] <= high + TOLERANCE['duration'], 's'))
    return rows


# ------------------------------------------------------------------ fonts by measures

def _shape(mask, height=48):
    import cv2
    rows, columns = np.where(mask)
    if not len(rows):
        return None
    crop = mask[rows.min():rows.max() + 1, columns.min():columns.max() + 1].astype(np.uint8) * 255
    return cv2.resize(crop, (max(8, int(crop.shape[1] * height / crop.shape[0])), height), interpolation=cv2.INTER_AREA) > 127


def shape_overlap(first, second):
    """Overlap (intersection over union) of two glyph masks scaled to one height and stretched to one width."""
    import cv2
    one, two = _shape(first), _shape(second)
    if one is None or two is None:
        return None
    two = cv2.resize(two.astype(np.uint8), (one.shape[1], one.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    return float((one & two).sum() / max(1, (one | two).sum()))


def _face_mask(family, weight, italic, words):
    from PIL import Image, ImageDraw
    import letitedit.catalogs.fonts as fonts
    font = fonts.pil_font(family, 96, weight=weight, italic=italic)
    canvas = Image.new('L', (int(font.getlength(words)) + 200, 240), 0)
    ImageDraw.Draw(canvas).text((60, 60), words, font=font, fill=255)
    return np.asarray(canvas) >= 128


def font_matches(text, reference, limit=6, cache_dir=None, mask=None):
    """Bundled faces ranked by how close the same words drawn in them come to the reference's stroke, width and
    slant (each in units of its tolerance), then by letter shape: the 40 closest are drawn again and their glyphs
    overlapped with the reference's (each 0.1 of overlap lost counts as one tolerance unit). Every weight and italic
    of every bundled family is measured once per text and cached."""
    from PIL import Image, ImageDraw
    import letitedit.catalogs.fonts as fonts
    if reference.get('stroke') is None or reference.get('width') is None:
        return []
    words = ' '.join(str(text).split())[:40]
    if len(re.sub(r'\W', '', words)) < 3:
        return []
    cache = None
    if cache_dir:
        cache = Path(cache_dir) / ('fonts-' + hashlib.sha256(words.encode('utf-8')).hexdigest()[:16] + '.json')
    table = json.loads(cache.read_text(encoding='utf-8-sig')) if cache and cache.is_file() else None
    if table is None:
        table = []
        for row in fonts.catalog():
            name = row['family']
            faces = set()
            for weight in row.get('weights') or ['400']:
                italic = weight.endswith('i')
                number = int(re.sub(r'\D', '', weight) or 400)
                faces.add((number, italic))
            for weight, italic in sorted(faces):
                try:
                    font = fonts.pil_font(name, 96, weight=weight, italic=italic)
                except Exception:  # noqa: BLE001 - a broken face is skipped
                    continue
                canvas = Image.new('L', (int(font.getlength(words)) + 200, 240), 0)
                ImageDraw.Draw(canvas).text((60, 60), words, font=font, fill=255)
                mask = np.asarray(canvas) >= 128
                if not mask.any():
                    continue
                measured = text_measures(mask, np.zeros(mask.shape + (3,), np.uint8), words, (1080, 1920), 1)
                if measured.get('stroke') is None:
                    continue
                table.append({'family': name, 'weight': weight, 'italic': italic, 'category': row.get('category'),
                              'stroke': measured['stroke'], 'width': measured['width'],
                              'slant': measured['slant'], 'lines': measured['lines']})
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(table), encoding='utf-8')
    ranked = []
    for face in table:
        distance = (abs(face['stroke'] / reference['stroke'] - 1) / TOLERANCE['stroke']
                    + abs(face['width'] / reference['width'] - 1) / TOLERANCE['width']
                    + abs((face['slant'] or 0) - (reference.get('slant') or 0)) / TOLERANCE['slant'])
        inside = (abs(face['stroke'] / reference['stroke'] - 1) <= TOLERANCE['stroke'] and
                  abs(face['width'] / reference['width'] - 1) <= TOLERANCE['width'] and
                  abs((face['slant'] or 0) - (reference.get('slant') or 0)) <= TOLERANCE['slant'])
        ranked.append({**face, 'distance': round(distance, 3), 'inside_tolerance': inside})
    ranked.sort(key=lambda face: face['distance'])
    if mask is not None and mask.any():
        reference_mask = mask
        for face in ranked[:40]:
            try:
                overlap = shape_overlap(reference_mask, _face_mask(face['family'], face['weight'], face['italic'], words))
            except Exception:  # noqa: BLE001 - a broken face keeps its numeric rank
                overlap = None
            if overlap is not None:
                face['shape_overlap'] = round(overlap, 3)
                face['distance'] = round(face['distance'] + (1 - overlap) / 0.1, 3)
        ranked = sorted(ranked[:40], key=lambda face: face['distance'])
    return ranked[:limit]


# ------------------------------------------------------------------ one family

def measure_family(kit, family, example, video=None, cache_dir=None):
    """Every declared part of a family example measured on both sides; passed only when every row passes."""
    from PIL import Image
    parts = example.get('parts')
    if not isinstance(parts, list) or not parts:
        raise ValueError(f"{family['id']}: example needs parts: the reference's text lines, plates, marks and pictures to measure")
    with Image.open(example['reference_frame']) as image:
        frame = np.asarray(image.convert('RGB')).copy()
    size = (frame.shape[1], frame.shape[0])
    moments = example.get('times') or []
    moment = float(moments[1]) if len(moments) == 3 else float(example.get('seconds', sum(family['duration_s']) / 2)) / 2
    content = dict(example['content'])
    for part in parts:
        if part.get('kind') == 'text':
            if part.get('slot') not in family['slots'] or not str(part.get('text', '')).strip():
                raise ValueError(f"{family['id']}: a text part names its slot and the reference's words as shown")
            content[part['slot']] = part['text']
        if part.get('kind') == 'picture' and part.get('slot') not in family['slots']:
            raise ValueError(f"{family['id']}: a picture part names its picture slot")
    results, passed = [], True
    for index, part in enumerate(parts):
        part = {**part, 'id': part.get('id') or f"{part.get('kind')}-{index + 1}"}
        reference = measure_reference(frame, part)
        reference_mask = reference.pop('_mask', None)
        ours = measure_ours(kit, family, content, part, size, moment)
        rgba, behind = ours.pop('_rgba', None), reference.pop('_behind', None)
        if rgba is not None and behind is not None and (reference.get('halo') or {}).get('measured'):
            ours['halo'] = our_halo(rgba, ours, behind, reference['halo'])
        rows = compare(part, reference, ours)
        entry = {'part': part['id'], 'kind': part['kind'], 'rows': rows, 'reference': reference, 'ours': ours}
        if part['kind'] == 'text' and any(not row['passed'] for row in rows
                                          if row['measure'].startswith(('stroke', 'width', 'slant'))):
            entry['font_matches'] = font_matches(part['text'], reference, cache_dir=cache_dir, mask=reference_mask)
        passed &= all(row['passed'] for row in rows)
        results.append(entry)
    timing = None
    span = example.get('span_s')
    if span is not None:
        if not video:
            raise ValueError('span_s needs package.reference_video')
        timing = reference_span(video, frame, {**parts[0], 'id': parts[0].get('id', 'first')}, span)
        rows = timing_rows(family, timing)
        results.append({'part': 'time on screen', 'kind': 'timing', 'rows': rows, 'reference': timing})
        passed &= all(row['passed'] for row in rows)
    else:
        results.append({'part': 'time on screen', 'kind': 'timing',
                        'rows': [_row('time on screen', 'span_s not given', None, 'measured', False)]})
        passed = False
    speaker = speaker_place(frame, next((entry['reference'] for entry in results if entry.get('kind') == 'text'), None))
    return {'family': family['id'], 'passed': bool(passed), 'parts': results,
            **({'speaker': speaker} if speaker else {})}


def speaker_place(frame_rgb, text):
    """Where a text piece sits relative to the speaker in the reference frame (the largest face): side (below the
    chin, above the brow, or over the face), below_chin or above_brow (face heights from the chin down, or the brow
    up, to the text's centre), band (that place as a share of the space between the chin and the frame's bottom, or
    the brow and its top), across (face widths from the face's centre), half_height (the text block's half height)
    and face_height, both shares of the frame's height. None without a face or text."""
    if not text or not text.get('box'):
        return None
    try:
        import letitedit.looks.graphic_kit as graphic_kit
        faces = graphic_kit.detect_faces(np.ascontiguousarray(frame_rgb[:, :, ::-1]))
    except Exception:  # noqa: BLE001 - no detector: unknown
        return None
    if not faces:
        return None
    height, width = frame_rgb.shape[:2]
    x0, y0, x1, y1 = max(faces, key=lambda f: (f[2] - f[0]) * (f[3] - f[1]))
    box = text['box']
    return speaker_numbers([x0 / width, y0 / height, x1 / width, y1 / height],
                           [box[0] / width, box[1] / height, box[2] / width, box[3] / height])


def speaker_numbers(face, box):
    """speaker_place's numbers from a face box and a text box, both [x0, y0, x1, y1] frame shares."""
    fx0, fy0, fx1, fy1 = face
    centre_x, centre_y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    face_height = fy1 - fy0
    place = {'face': [round(value, 4) for value in face], 'across': round((centre_x - (fx0 + fx1) / 2) / (fx1 - fx0), 3),
             'half_height': round((box[3] - box[1]) / 2, 4), 'face_height': round(face_height, 4)}
    if centre_y >= fy1:
        place.update(side='below', below_chin=round((centre_y - fy1) / face_height, 3),
                     band=round((centre_y - fy1) / max(1 - fy1, 1e-6), 3))
    elif centre_y <= fy0:
        place.update(side='above', above_brow=round((fy0 - centre_y) / face_height, 3),
                     band=round((fy0 - centre_y) / max(fy0, 1e-6), 3))
    else:
        place['side'] = 'over'
    return place


def sheet(frame_path, family_result, kit, family, example, out):
    """A private picture: the reference crop beside ours at the same scale, with each row's numbers."""
    from PIL import Image, ImageDraw
    import letitedit.looks.graphic_kit as graphic_kit
    import letitedit.pictures.graphics as graphics
    import letitedit.looks.style_pack as style_pack
    with Image.open(frame_path) as image:
        frame = image.convert('RGB')
    boxes = []
    for entry in family_result['parts']:
        if entry.get('kind') == 'timing':
            continue
        for side in ('reference', 'ours'):
            boxes.append((entry.get(side) or {}).get('box'))
            boxes.append(((entry.get(side) or {}).get('plate') or {}).get('box'))
    boxes = [box for box in boxes if box]
    if not boxes:
        return None
    pad = 40
    x0 = max(0, int(min(box[0] for box in boxes)) - pad)
    y0 = max(0, int(min(box[1] for box in boxes)) - pad)
    x1 = min(frame.width, int(max(box[2] for box in boxes)) + pad)
    y1 = min(frame.height, int(max(box[3] for box in boxes)) + pad)
    drawing = style_pack.Kit({**copy.deepcopy(style_pack.DEFAULTS), **kit['style']})
    content = dict(example['content'])
    for part in example['parts']:
        if part.get('kind') == 'text':
            content[part['slot']] = part['text']
    moments = example.get('times') or []
    moment = float(moments[1]) if len(moments) == 3 else 0.5
    seconds = max(moment + 1 / 30, float(family['duration_s'][1]))
    recipe = graphics.normalise(graphic_kit.recipe(kit, family, content, seconds, check_duration=False), drawing)
    ours, _ = _passes(recipe, drawing, (frame.width, frame.height), moment)
    ours_image = Image.fromarray(ours, 'RGBA')
    background = frame.crop((x0, y0, x1, y1)).convert('RGBA')
    dimmed = Image.new('RGBA', background.size, (70, 70, 70, 255))
    dimmed.alpha_composite(ours_image.crop((x0, y0, x1, y1)))
    scale = min(1.0, 520 / background.width)
    size = (max(1, int(background.width * scale)), max(1, int(background.height * scale)))
    rows = [row for entry in family_result['parts'] for row in entry['rows']]
    text_height = 18 * (len(rows) + 3)
    page = Image.new('RGB', (size[0] * 2 + 30, size[1] + 40 + text_height), '#202020')
    draw = ImageDraw.Draw(page)
    draw.text((10, 8), f"{family['id']}: reference LEFT, ours RIGHT (ours over grey), same scale", fill='white')
    page.paste(background.convert('RGB').resize(size), (10, 30))
    page.paste(dimmed.convert('RGB').resize(size), (size[0] + 20, 30))
    top = size[1] + 40
    for row in rows:
        mark = 'ok ' if row['passed'] else 'OUT'
        extra = f" (dE {row['delta_e']})" if 'delta_e' in row else ''
        draw.text((10, top), f"{mark} {row['measure']}: reference {row['reference']} / ours {row['ours']} "
                             f"[{row['tolerance']}]{extra}", fill='#9BE39B' if row['passed'] else '#FF8C7A')
        top += 18
    draw.text((10, top + 4), 'PASSED' if family_result['passed'] else 'NOT INSIDE TOLERANCE',
              fill='#9BE39B' if family_result['passed'] else '#FF8C7A')
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    page.save(out)
    return str(Path(out).resolve())
