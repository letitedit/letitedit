"""The settings and the shared geometry: boxes and matrices, MLT values, media orientation and size, the clip on the timeline.

Part of `annotate` (letitedit/pictures/annotate.py), which imports every name here back,
so `annotate.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
import json
import math
import os
import re
import subprocess
from pathlib import Path
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

SCHEMA = 'letitedit-annotate/1'
ENGINE = 1                       # geometry + drawing version: stored in recipes and plans (a change re-renders them)
DEFAULT_TRACK = 'Annotations'
KINDS = ('ring', 'arrow', 'box', 'label', 'magnify')
APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))
FFPROBE = APP / 'ffprobe.exe'
FFMPEG = APP / 'ffmpeg.exe'
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
CODE = 'def draw(ctx):\n    import annotate\n    annotate.draw(ctx)\n'     # the custom-graphic recipe's code
MARK = 'annotate'                 # params[MARK] = ENGINE marks a graphic made by this module


class Unsupported(ValueError):
    """The request can't be done correctly (a retimed clip, an effect that moves the picture in a way this module
    doesn't model...). The message says what and why; nothing was changed."""


# ============================================================================ boxes and matrices (shared geometry)

def box_w(b):
    return b[2] - b[0]


def box_h(b):
    return b[3] - b[1]


def box_area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def box_center(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def box_inter(a, b):
    """The overlap of two boxes, or None."""
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def overlap_area(a, b):
    i = box_inter(a, b)
    return box_area(i) if i else 0.0


def box_grow(b, dx, dy=None):
    dy = dx if dy is None else dy
    return (b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy)


def box_union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def box_inside(inner, outer, tol=0.0):
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol
            and inner[3] <= outer[3] + tol)


def box_distance(a, b):
    """Gap between two boxes (0 when they touch or overlap)."""
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return math.hypot(dx, dy)


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mat_inv(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        raise ValueError('the picture transform is degenerate (zero size)')
    return [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
            [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
            [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]


def mat_apply(m, x, y):
    w = m[2][0] * x + m[2][1] * y + m[2][2]
    return ((m[0][0] * x + m[0][1] * y + m[0][2]) / w, (m[1][0] * x + m[1][1] * y + m[1][2]) / w)


def mat_translate(tx, ty):
    return [[1.0, 0.0, float(tx)], [0.0, 1.0, float(ty)], [0.0, 0.0, 1.0]]


def mat_scale(sx, sy):
    return [[float(sx), 0.0, 0.0], [0.0, float(sy), 0.0], [0.0, 0.0, 1.0]]


def mat_rot(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def map_box(m, b):
    """The box's four corners through m: (bounding box, corner points)."""
    pts = [mat_apply(m, x, y) for x, y in ((b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3]))]
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)), pts


def mat_scale_of(m):
    """Average linear scale of a 2-D affine matrix."""
    return math.sqrt(abs(m[0][0] * m[1][1] - m[0][1] * m[1][0]))


def mat_rotation_of(m):
    return math.degrees(math.atan2(m[1][0], m[0][0]))


# ============================================================================ MLT values: rects, times, keyframes

_NUM = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?%?')
_KEY = re.compile(r'^\s*(-?[\d:.;]+)([|!~$\-a-zA-D]?)=(.*)$')
EASE_OF = {'|': 'discrete', '!': 'discrete', '': 'linear', '~': 'smooth', '$': 'smooth_natural', '-': 'smooth_tight',
           'a': 'sine_in', 'b': 'sine_out', 'c': 'sine_in_out', 'd': 'quad_in', 'e': 'quad_out', 'f': 'quad_in_out',
           'g': 'cubic_in', 'h': 'cubic_out', 'i': 'cubic_in_out', 'j': 'quart_in', 'k': 'quart_out',
           'l': 'quart_in_out', 'm': 'quint_in', 'n': 'quint_out', 'o': 'quint_in_out', 'p': 'expo_in',
           'q': 'expo_out', 'r': 'expo_in_out', 's': 'circ_in', 't': 'circ_out', 'u': 'circ_in_out', 'v': 'back_in',
           'w': 'back_out', 'x': 'back_in_out', 'y': 'elastic_in', 'z': 'elastic_out', 'A': 'elastic_in_out',
           'B': 'bounce_in', 'C': 'bounce_out', 'D': 'bounce_in_out'}


def mlt_time_frames(text, fps):
    """An MLT time ('123' frames, 'HH:MM:SS.mmm', 'HH:MM:SS:FF', 'SS.mmm' with a colon) -> frames, as the engine reads
    it (timeline_model.clock_to_frames; a negative frame number counts from the end where the caller says so)."""
    import letitedit.timeline.timeline_model as timeline_model
    return timeline_model.clock_to_frames(str(text), fps)


def parse_rect(text, width, height):
    """An MLT rect ('x y w h [o]', 'x/y:wxh[:o]', any with %) -> [x, y, w, h, o] in pixels."""
    vals = _NUM.findall(str(text))
    if len(vals) < 4:
        raise ValueError(f'not a rectangle: {text!r}')
    pct = '%' in str(text)
    out = []
    for k, v in enumerate(vals[:5]):
        x = float(v.rstrip('%'))
        if v.endswith('%'):
            x /= 100.0
        out.append(x)
    if len(out) == 4:
        out.append(1.0)
    if pct:
        out[0] *= width
        out[1] *= height
        out[2] *= width
        out[3] *= height
    return out


def parse_keys(text, fps, length):
    """Keyframes of an MLT animation string: [(frame, ease_name, value_text)], or None for a plain value."""
    text = str(text)
    if '=' not in text:
        return None
    keys = []
    for part in text.split(';'):
        if not part.strip():
            continue
        m = _KEY.match(part)
        if not m:
            return None
        f = mlt_time_frames(m.group(1), fps)
        if f < 0:                                  # negative times count from the end
            f = length + f
        keys.append((f, EASE_OF.get(m.group(2), 'linear'), m.group(3)))
    keys.sort(key=lambda k: k[0])
    return keys or None


def _ease(name, t):
    """Fraction 0-1 of the way between two keys for MLT's eases (mlt_animation.c, Penner's functions)."""
    p2 = math.pi / 2
    kind, _, way = name.partition('_')
    way = way or 'in'
    if kind == 'linear':
        return t
    if kind == 'sine':
        return {'in': math.sin((t - 1) * p2) + 1, 'out': math.sin(t * p2)}.get(way, 0.5 * (1 - math.cos(t * math.pi)))
    if kind in ('quad', 'cubic', 'quart', 'quint'):
        n = {'quad': 2, 'cubic': 3, 'quart': 4, 'quint': 5}[kind]
        if way == 'in':
            return t ** n
        if way == 'out':
            return 1 - (1 - t) ** n
        return (2 ** n) * t ** n / 2 if t < 0.5 else 1 - (-2 * t + 2) ** n / 2
    if kind == 'expo':
        if t in (0.0, 1.0):
            return t
        if way == 'in':
            return 2 ** (10 * t - 10)
        if way == 'out':
            return 1 - 2 ** (-10 * t)
        return 2 ** (20 * t - 10) / 2 if t < 0.5 else (2 - 2 ** (-20 * t + 10)) / 2
    if kind == 'circ':
        if way == 'in':
            return 1 - math.sqrt(max(0.0, 1 - t * t))
        if way == 'out':
            return math.sqrt(max(0.0, 1 - (t - 1) ** 2))
        return 0.5 * (1 - math.sqrt(max(0.0, 1 - 4 * t * t))) if t < 0.5 else \
            0.5 * (math.sqrt(max(0.0, -((2 * t) - 3) * ((2 * t) - 1))) + 1)
    if kind == 'back':
        def f(x):
            return x ** 3 - x * math.sin(x * math.pi)
        if way == 'in':
            return f(t)
        if way == 'out':
            return 1 - f(1 - t)
        return 0.5 * f(2 * t) if t < 0.5 else 0.5 * (1 - f(1 - (2 * t - 1))) + 0.5
    if kind == 'elastic':
        if way == 'in':
            return math.sin(13 * p2 * t) * 2 ** (10 * (t - 1))
        if way == 'out':
            return math.sin(-13 * p2 * (t + 1)) * 2 ** (-10 * t) + 1
        return (0.5 * math.sin(13 * p2 * (2 * t)) * 2 ** (10 * ((2 * t) - 1)) if t < 0.5 else
                0.5 * (math.sin(-13 * p2 * ((2 * t - 1) + 1)) * 2 ** (-10 * (2 * t - 1)) + 2))
    if kind == 'bounce':
        def out(x):
            if x < 4 / 11.0:
                return 121 * x * x / 16.0
            if x < 8 / 11.0:
                return 363 / 40.0 * x * x - 99 / 10.0 * x + 17 / 5.0
            if x < 9 / 10.0:
                return 4356 / 361.0 * x * x - 35442 / 1805.0 * x + 16061 / 1805.0
            return 54 / 5.0 * x * x - 513 / 25.0 * x + 268 / 25.0
        if way == 'in':
            return 1 - out(1 - t)
        if way == 'out':
            return out(t)
        return 0.5 * (1 - out(1 - t * 2)) if t < 0.5 else 0.5 * out(2 * t - 1) + 0.5
    return t


def _catmull(x0, y0, x1, y1, x2, y2, x3, y3, t, alpha, tension):
    """MLT's catmull_rom_interpolate (mlt_animation.c)."""
    if x0 == x1:
        x0 -= 10000
    if x3 == x2:
        x3 += 10000

    def dist(ax, ay, bx, by):
        return math.hypot(bx - ax, by - ay)
    m1 = m2 = 0.0
    t12 = dist(x1, y1, x2, y2) ** alpha
    if tension > 0.0 or (y0 > y1 > y2) or (y0 < y1 < y2):
        t01 = dist(x0, y0, x1, y1) ** alpha
        m1 = abs(tension) * (y2 - y1 + t12 * ((y1 - y0) / t01 - (y2 - y0) / (t01 + t12)))
    if tension > 0.0 or (y1 > y2 > y3) or (y1 < y2 < y3):
        t23 = dist(x2, y2, x3, y3) ** alpha
        m2 = abs(tension) * (y2 - y1 + t12 * ((y3 - y2) / t23 - (y3 - y1) / (t12 + t23)))
    a = 2.0 * (y1 - y2) + m1 + m2
    b = -3.0 * (y1 - y2) - m1 - m1 - m2
    return a * t ** 3 + b * t * t + m1 * t + y1


def anim_values(text, pos, fps, length, parse):
    """The value of a (possibly keyframed) MLT property at `pos` (frames from the filter's in point), as MLT computes
    it: parse(value_text) -> tuple of numbers, interpolated component by component."""
    keys = parse_keys(text, fps, length)
    if keys is None:
        return parse(text)
    i = 0
    while i + 1 < len(keys) and pos >= keys[i + 1][0]:
        i += 1
    f1, ease, v1 = keys[i]
    if pos <= f1 or i + 1 >= len(keys):
        return parse(v1)
    f2, _, v2 = keys[i + 1]
    a, b = parse(v1), parse(v2)
    if ease == 'discrete':
        return a
    t = (pos - f1) / float(f2 - f1)
    if ease.startswith('smooth'):
        f0, _, v0 = keys[i - 1] if i > 0 else keys[i]
        f3, _, v3 = keys[i + 2] if i + 2 < len(keys) else keys[i + 1]
        p0, p3 = parse(v0), parse(v3)
        alpha, tension = {'smooth': (0.0, 1.0), 'smooth_natural': (0.5, -1.0), 'smooth_tight': (0.5, 0.0)}[ease]
        return tuple(_catmull(f0, p0[k], f1, a[k], f2, b[k], f3, p3[k], t, alpha, tension) for k in range(len(a)))
    e = _ease(ease, t)
    return tuple(a[k] + (b[k] - a[k]) * e for k in range(len(a)))


def anim_number(text, pos, fps, length, default=0.0, angle=False):
    if text in (None, ''):
        return default

    def parse(v):
        vals = _NUM.findall(str(v))
        if not vals:
            return (default,)
        x = float(vals[0].rstrip('%'))
        if angle and str(v).strip().endswith('%'):
            x = x / 100.0 * 360.0
        return (x,)
    return anim_values(text, pos, fps, length, parse)[0]


# ============================================================================ media: orientation and size

_media = {}


def fingerprint(path):
    st = os.stat(path)
    return [st.st_size, int(st.st_mtime)]


def media_info(path):
    """Picture facts of a file as players and the engine see it: coded size, the file's display rotation (degrees
    clockwise to turn the coded picture upright: 0/90/180/270), display size, pixel aspect, fps, duration,
    whether the orientation flag mirrors the picture, and a fingerprint (size, mtime)."""
    path = str(path)
    fp = fingerprint(path)
    key = (os.path.normcase(os.path.abspath(path)), tuple(fp))
    if key in _media:
        return _media[key]
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', path],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW,
                       check=False)
    data = json.loads(r.stdout or '{}')
    v = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'
              and not (s.get('disposition') or {}).get('attached_pic')), None)
    if v is None:
        raise Unsupported(f'{Path(path).name} has no picture to point at')
    cw, ch = int(v.get('width') or 0), int(v.get('height') or 0)
    tag = (v.get('tags') or {}).get('rotate')
    ffrot, mirrored = 0.0, False
    for sd in v.get('side_data_list') or []:
        if 'rotation' in sd:
            ffrot = float(sd['rotation'])
            rows = []
            for line in (sd.get('displaymatrix') or '').strip().splitlines():
                nums = re.findall(r'-?\d+', line.split(':', 1)[-1])
                if len(nums) >= 3:
                    rows.append([int(x) for x in nums[:3]])
            if len(rows) == 3 and rows[0][0] * rows[1][1] - rows[0][1] * rows[1][0] < 0:
                mirrored = True                    # the flag flips the picture as well as turning it
    # the engine's theta (producer_avformat.c get_rotation): a 'rotate' tag wins, else minus the display matrix angle
    if tag not in (None, '', '0'):
        try:
            theta = float(tag)
        except ValueError:
            theta = -ffrot
    else:
        theta = -ffrot
    theta = _norm_angle(theta)
    sar_txt = v.get('sample_aspect_ratio') or '1:1'
    try:
        n, d = [float(x) for x in sar_txt.split(':')]
        sar = n / d if n > 0 and d > 0 else 1.0
    except ValueError:
        sar = 1.0
    num, den = (v.get('avg_frame_rate') or v.get('r_frame_rate') or '0/1').split('/')
    fps = float(num) / float(den) if float(den or 0) else 0.0
    rfr_n, rfr_d = (v.get('r_frame_rate') or '0/1').split('/')
    rfps = float(rfr_n) / float(rfr_d) if float(rfr_d or 0) else fps
    dw, dh = (ch, cw) if theta in (90, 270) else (cw, ch)
    ext = Path(path).suffix.lower()
    info = {'file': path, 'coded': [cw, ch], 'rotation': int(theta), 'display': [dw, dh], 'sar': round(sar, 6),
            'fps': round(fps, 4), 'rate': round(rfps, 4), 'mirrored': mirrored,
            'duration': float((data.get('format') or {}).get('duration') or v.get('duration') or 0),
            'image': ext in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.webp', '.heic'),
            'fingerprint': fp}
    _media[key] = info
    return info


def _norm_angle(theta):
    theta = theta - 360 * math.floor(theta / 360 + 0.9 / 360)
    for a in (0, 90, 180, 270):
        if abs(theta - a) < 1.0 or abs(theta - a - 360) < 1.0:
            return a
    return theta


def rotate_map(theta, w, h):
    """Matrix taking a (w, h) picture's coordinates to the picture turned theta degrees clockwise (0/90/180/270) -
    the engine's autorotate (transpose=clock / cclock, hflip+vflip)."""
    theta = int(theta) % 360
    if theta == 0:
        return IDENTITY
    if theta == 90:
        return [[0.0, -1.0, float(h)], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    if theta == 270:
        return [[0.0, 1.0, 0.0], [-1.0, 0.0, float(w)], [0.0, 0.0, 1.0]]
    if theta == 180:
        return [[-1.0, 0.0, float(w)], [0.0, -1.0, float(h)], [0.0, 0.0, 1.0]]
    raise Unsupported(f'a rotation of {theta} degrees is not a quarter turn')


# ============================================================================ the clip on the timeline

def _props(el):
    return {p.get('name'): (p.text or '') for p in el.findall('property')}


def _frames_attr(value, fps, default=None):
    if value in (None, ''):
        return default
    return mlt_time_frames(value, fps)


def load_doc(project):
    import letitedit.timeline.edit_script as es
    path = es._resolve(project)
    return es.Doc(path), path


def clip_places(doc):
    """Every item of every track with its exact place: {id: {...}} (timeline frames, producer frames, transitions)."""
    import letitedit.timeline.edit_script as es
    ids = es._ids_for(doc)
    out = {}
    for t_index, (tr, pl, name, kind) in enumerate(doc.tracks()):
        entries = doc.entries(pl)
        pos = 0
        recs = []
        for i, (k, e, nblank) in enumerate(entries):
            if k == 'blank':
                pos += nblank or 0
                continue
            prod = doc.elements.get(e.get('producer'))
            a = _frames_attr(e.get('in'), doc.fps, 0)
            b = _frames_attr(e.get('out'), doc.fps)
            if b is None and prod is not None:
                b = _frames_attr(prod.get('out'), doc.fps, 0)
            n = b - a + 1
            is_tr = prod is not None and prod.tag == 'tractor' and es._get(prod, 'shotcut:transition') is not None
            recs.append({'index': i, 'entry': e, 'producer': prod, 'start': pos, 'in': a, 'out': b, 'frames': n,
                         'transition': is_tr, 'id': ids.get((name, i))})
            pos += n
        for j, r in enumerate(recs):
            if r['transition'] or r['producer'] is None:
                continue
            lead = tail = 0
            if j > 0 and recs[j - 1]['transition'] and recs[j - 1]['start'] + recs[j - 1]['frames'] == r['start']:
                trk = recs[j - 1]['producer'].findall('track')
                if len(trk) == 2 and trk[1].get('producer') == r['producer'].get('id'):
                    lead = recs[j - 1]['frames']
            if j + 1 < len(recs) and recs[j + 1]['transition'] and r['start'] + r['frames'] == recs[j + 1]['start']:
                trk = recs[j + 1]['producer'].findall('track')
                if len(trk) == 2 and trk[0].get('producer') == r['producer'].get('id'):
                    tail = recs[j + 1]['frames']
            out[r['id']] = {'id': r['id'], 'track': name, 'track_kind': kind, 'track_index': t_index, 'playlist': pl,
                            'track_elem': tr, 'entry': r['entry'], 'producer': r['producer'], 'start': r['start'],
                            'in': r['in'], 'out': r['out'], 'frames': r['frames'], 'lead': lead, 'tail': tail}
    return out


def find_clip(doc, clip_id):
    places = clip_places(doc)
    if clip_id not in places:
        near = [k for k in places if k and str(clip_id).lower() in str(k).lower()][:8]
        raise ValueError(f'No clip with id {clip_id!r} on the timeline' + (f' (ids like it: {", ".join(near)})' if near else
                         ' (letitedit_timeline_read lists the ids)'))
    return places[clip_id]
