"""The settings and the geometry: boxes, the target shape and crop, the linear program, who fits where.

Part of `reframe` (letitedit/pictures/reframe.py), which imports every name here back,
so `reframe.X` is the same object it always was.
"""
from __future__ import annotations
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
import copy
import os
import re
import time
from pathlib import Path
import numpy as np
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

SCHEMA = 'letitedit-reframe/1'
ENGINE = 1                         # solver + detection version: stored in plans and caches (a change re-plans)
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
SPLIT_TRACK = 'Reframe split'
INSET_TRACK = 'Reframe inset'
NAMED = {'vertical': (1080, 1920), '9:16': (1080, 1920), 'portrait': (1080, 1350), '4:5': (1080, 1350),
         'square': (1080, 1080), '1:1': (1080, 1080), 'horizontal': (1920, 1080), '16:9': (1920, 1080),
         'landscape': (1920, 1080), '4:3': (1440, 1080), '3:4': (1080, 1440), '2:3': (1080, 1620)}
PRIORITIES = ('required', 'preferred', 'optional', 'ignore')
AUTO_KINDS = ('face', 'action', 'track')

# Every number the solver uses; each can be given in `settings` and is reported in the result.
DEFAULTS = {
    'zoom': [1.0, 1.0],          # [min, max] zoom over the largest crop of the target shape (1 = fills the frame)
    'margin': 0.04,              # space kept around required subjects, share of the crop's shorter side
    'headroom': 0.05,            # extra space above a face, share of the crop's height
    'solve_hz': 10.0,            # path samples per second (long clips use fewer: at most max_samples)
    'max_samples': 2400,
    'recentre_s': 3.0,           # a subject left off-centre this long is worth a move back
    'calm': 1.0,                 # multiplies every motion cost (2 = fewer, gentler moves; 0.5 = livelier)
    'max_speed': 1.0,            # fastest the crop moves, crop widths (heights) per second (0 = no limit)
    'max_accel': 1.0,            # fastest its speed changes, crop widths (heights) per second^2 (0 = no limit)
    'max_zoom_rate': 0.5,        # fastest the crop's size changes, share of the largest crop per second
    'lookahead_s': 0.25,         # required boxes include where they are this far before and after
    'rejoin_s': 0.8,             # a required subject that could not fit is brought back in over this time
    'min_span_s': 0.5,           # can't-fit moments shorter than this are merged into their neighbours or noted
    'span_pad_s': 0.4,           # split/inset spans start this much before and end after the can't-fit moments
    'ease': 'smooth_natural',    # keyframe ease (MLT smooth natural: eases out of and into holds)
    'key_tolerance_px': 1.5,     # keyframes are thinned while the path stays within this many output pixels
    'face_hz': 5.0,              # face detection rate
    'face_min_score': 0.6,       # YuNet confidence
    'action_hz': 10.0,           # motion analysis rate
    'action_px': 320,            # long side of the motion analysis picture
    'action_min': 0.6,           # least motion energy (heat, mean grey levels) for an action box
    'action_max_area': 0.6,      # an action box bigger than this share of the picture is too spread out to use
    'action_mass': 0.8,          # share of the motion heat the action box holds
    'track_hz': 10.0,            # tracking rate for given boxes
    'track_px': 480,             # long side of the tracking picture
    'hold_lost_s': 0.5,          # a lost tracked box is held this long before the subject counts as absent
    'carry_lost_s': 2.0,         # ...then carried with the camera's measured motion up to this long
    'cut_detect': True,          # find the clip's own cuts (the path may jump there)
}
# containment cost per (crop width x second) outside the crop, by priority
WEIGHT = {'required': 2000.0, 'preferred': 60.0, 'optional': 6.0, 'dropped': 0.0}
MOTION = {'w1': 1.0, 'w2': 0.35, 'w3': 0.012, 'zoom_pref': 0.5}
KEEP_OUT_WEIGHT = 12.0           # an inset's corner: the main crop's subjects are nudged away from it, never forced


class Unsupported(ValueError):
    """The request can't be done honestly (a reversed or retimed clip, an effect that moves the picture in a way
    this tool does not model...). The message says what and why; nothing was changed."""


def _r(x, nd=3):
    return round(float(x), nd)


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def settings_of(given=None):
    s = copy.deepcopy(DEFAULTS)
    for k, v in (given or {}).items():
        if k not in s:
            raise ValueError(f'unknown reframe setting {k!r}; settings: {", ".join(s)}')
        s[k] = v
    z = s['zoom']
    if isinstance(z, (int, float)):
        z = [float(z), float(z)]
    z = [float(z[0]), float(z[1])]
    if z[0] < 1.0 - 1e-9 or z[1] < z[0]:
        raise ValueError('zoom is a number >= 1 or [min, max] with 1 <= min <= max (1 = the largest crop that fills '
                         'the frame; below 1 would show bars)')
    s['zoom'] = z
    return s


# ============================================================================ boxes

def box_w(b):
    return b[2] - b[0]


def box_h(b):
    return b[3] - b[1]


def union(boxes):
    boxes = [b for b in boxes if b is not None and not np.any(np.isnan(b))]
    if not boxes:
        return None
    a = np.asarray(boxes, float)
    return np.array([a[:, 0].min(), a[:, 1].min(), a[:, 2].max(), a[:, 3].max()])


def inside(b, win, tol=0.5):
    return b[0] >= win[0] - tol and b[1] >= win[1] - tol and b[2] <= win[2] + tol and b[3] <= win[3] + tol


def iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    i = (x1 - x0) * (y1 - y0)
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)


# ============================================================================ target shape and crop geometry

def resolve_target(target):
    """(width, height, info) for '9:16' / 'vertical' / '1:1' / 'WxH' / [w, h] / a platform id."""
    info = {}
    if isinstance(target, (list, tuple)) and len(target) == 2:
        w, h = int(target[0]), int(target[1])
    elif isinstance(target, dict):
        w, h = int(target['width']), int(target['height'])
    else:
        text = str(target).strip().lower()
        m = re.fullmatch(r'(\d+)\s*[x*]\s*(\d+)', text)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
        elif text in NAMED:
            w, h = NAMED[text]
        else:
            m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)', text)
            if m:
                a = float(m.group(1)) / float(m.group(2))
                w, h = (1080, int(round(1080 / a / 2)) * 2) if a < 1 else (int(round(1080 * a / 2)) * 2, 1080)
            else:
                import letitedit.catalogs.platforms as platforms
                p = platforms.preset_for(text)
                if not p.get('width') or not p.get('height'):
                    raise ValueError(f'target {target!r}: give 9:16, 4:5, 1:1, 16:9, WxH or a platform with a size')
                w, h = int(p['width']), int(p['height'])
                info['platform'] = p.get('platform')
    if w < 16 or h < 16:
        raise ValueError(f'target size {w}x{h} is too small')
    return w // 2 * 2, h // 2 * 2, info


def max_window(src_w, src_h, out_w, out_h):
    """The largest crop (w, h) of the output's shape inside the source picture (zoom 1)."""
    a = out_w / out_h
    if src_w / src_h > a:
        return src_h * a, float(src_h)
    return float(src_w), src_w / a


def safe_area(platform, out_w, out_h):
    """(fx0, fy0, fx1, fy1, notes): the share of the output frame no platform overlay covers (bands only), from
    platforms.load(...)['safe_zones']. Zones that are not full-width or full-height bands are reported, not used."""
    if not platform:
        return (0.0, 0.0, 1.0, 1.0), []
    import letitedit.catalogs.platforms as platforms
    prof = platforms.load(platform)
    fx0, fy0, fx1, fy1 = 0.0, 0.0, 1.0, 1.0
    notes = []
    for z in (prof.get('safe_zones') or {}).get('value') or []:
        x, y, w, h = float(z['x']), float(z['y']), float(z['w']), float(z['h'])
        if w >= 0.98 and y <= 0.02:
            fy0 = max(fy0, y + h)
        elif w >= 0.98 and y + h >= 0.98:
            fy1 = min(fy1, y)
        elif h >= 0.98 and x <= 0.02:
            fx0 = max(fx0, x + w)
        elif h >= 0.98 and x + w >= 0.98:
            fx1 = min(fx1, x)
        else:
            notes.append(f"{prof['id']} zone '{z.get('name')}' is not a band along an edge; not kept clear")
    return (fx0, fy0, fx1, fy1), notes


def rect_for(cx, cy, s, src_w, src_h, out_w, out_h, panel=None):
    """Size/Position rect [x, y, w, h] (output pixels) that shows the crop centred (cx, cy) of size s x the largest
    crop in the panel (default the whole frame) - the picture placed so that crop fills the panel."""
    px, py, pw, ph = panel if panel else (0.0, 0.0, float(out_w), float(out_h))
    ww, wh = max_window(src_w, src_h, pw, ph)
    ww, wh = ww * s, wh * s
    k = pw / ww
    return [px - (cx - ww / 2) * k, py - (cy - wh / 2) * k, src_w * k, src_h * k]


def window_of_rect(rect, src_w, src_h, out_w, out_h, panel=None):
    """The source crop (x0, y0, x1, y1) a Size/Position rect shows in the panel (default the frame)."""
    px, py, pw, ph = panel if panel else (0.0, 0.0, float(out_w), float(out_h))
    x, y, w, h = rect[:4]
    k = w / src_w
    return np.array([(px - x) / k, (py - y) / k, (px + pw - x) / k, (py + ph - y) / k])


# ============================================================================ the linear program

class _LP:
    """A sparse LP built block by block: min c.x subject to A x <= b and bounds (HiGHS through scipy)."""

    def __init__(self):
        self.n = 0
        self.m = 0
        self.c, self.lo, self.hi = [], [], []
        self.ri, self.ci, self.vi, self.b = [], [], [], []

    def var(self, k, cost=0.0, lo=-np.inf, hi=np.inf):
        idx = np.arange(self.n, self.n + k)
        self.n += k
        self.c.append(np.broadcast_to(np.asarray(cost, float), (k,)).astype(float))
        self.lo.append(np.broadcast_to(np.asarray(lo, float), (k,)).astype(float))
        self.hi.append(np.broadcast_to(np.asarray(hi, float), (k,)).astype(float))
        return idx

    def rows(self, cols, vals, rhs):
        cols = np.asarray(cols, int)
        if cols.ndim == 1:
            cols = cols[:, None]
        vals = np.broadcast_to(np.asarray(vals, float), cols.shape)
        R, m = cols.shape
        if R == 0:
            return
        self.ri.append(np.repeat(np.arange(self.m, self.m + R), m))
        self.ci.append(cols.ravel())
        self.vi.append(vals.ravel())
        self.b.append(np.broadcast_to(np.asarray(rhs, float), (R,)).astype(float))
        self.m += R

    def abs_cost(self, cols, vals, w):
        """u >= |sum vals * x[cols]| per row, cost w * u."""
        cols = np.asarray(cols, int)
        R = cols.shape[0]
        if R == 0:
            return None
        u = self.var(R, cost=w, lo=0.0)
        vals = np.broadcast_to(np.asarray(vals, float), cols.shape)
        self.rows(np.hstack([cols, u[:, None]]), np.hstack([vals, -np.ones((R, 1))]), 0.0)
        self.rows(np.hstack([cols, u[:, None]]), np.hstack([-vals, -np.ones((R, 1))]), 0.0)
        return u

    def solve(self):
        from scipy.optimize import linprog
        from scipy.sparse import coo_matrix
        c = np.concatenate(self.c)
        bounds = np.column_stack([np.concatenate(self.lo), np.concatenate(self.hi)])
        A = coo_matrix((np.concatenate(self.vi), (np.concatenate(self.ri), np.concatenate(self.ci))),
                       shape=(self.m, self.n)).tocsr()
        res = linprog(c, A_ub=A, b_ub=np.concatenate(self.b), bounds=bounds, method='highs',
                      options={'presolve': True, 'time_limit': 120.0})
        if res.x is None:
            raise RuntimeError(f'the path solver failed: {res.message}')
        return res.x, res


def _diff_rows(idx, order, breaks):
    """Rows of finite differences of `order` over consecutive samples of `idx`, none across a break (a cut sits
    between samples i and i+1 when i+1 is in breaks)."""
    n = len(idx)
    coef = {1: [-1, 1], 2: [1, -2, 1], 3: [-1, 3, -3, 1]}[order]
    starts = [i for i in range(n - order) if not any((i + j) in breaks for j in range(1, order + 1))]
    if not starts:
        return np.zeros((0, order + 1), int), np.zeros((0, order + 1))
    st = np.asarray(starts)
    cols = np.stack([idx[st + j] for j in range(order + 1)], axis=1)
    return cols, np.tile(np.asarray(coef, float), (len(st), 1))


# ============================================================================ who fits where

def _padded(box, prio, src_w, src_h, mx, my, head):
    """A subject box with its margins (required subjects get all of it), clipped to the picture."""
    k = 1.0 if prio == 'required' else 0.5
    x0, y0, x1, y1 = box
    return np.array([max(0.0, x0 - k * mx), max(0.0, y0 - k * my - head), min(src_w, x1 + k * mx),
                     min(src_h, y1 + k * my)])


def _fits(u, ww, wh, safe, src_w, src_h):
    """Can a crop of the largest size (ww x wh, may be smaller by zoom elsewhere) hold box u inside its uncovered
    area while staying in the picture? (frame level when safe is the whole frame)."""
    fx0, fy0, fx1, fy1 = safe
    if box_w(u) > ww * (fx1 - fx0) + 0.5 or box_h(u) > wh * (fy1 - fy0) + 0.5:
        return False
    # the crop's uncovered area must reach the box without the crop leaving the picture
    lo_x, hi_x = u[2] - ww * fx1, u[0] - ww * fx0          # range of the crop's left edge
    lo_y, hi_y = u[3] - wh * fy1, u[1] - wh * fy0
    lo_x, hi_x = max(lo_x, 0.0), min(hi_x, src_w - ww)
    lo_y, hi_y = max(lo_y, 0.0), min(hi_y, src_h - wh)
    return lo_x <= hi_x + 0.5 and lo_y <= hi_y + 0.5


def fit_analysis(subjects, n, src_w, src_h, ww, wh, safe, settings):
    """Per sample: the required subjects kept (in rank order, while their union with margins fits the largest
    crop) and those left out; the same against the uncovered area when a platform is given.
    Returns (kept [n] sets, left [n] sets, left_safe [n] sets)."""
    mx = my = 0.25 * settings['margin'] * min(ww, wh)        # margins are soft in the path: fit needs a little
    req = sorted([s for s in subjects if s['priority'] == 'required'], key=lambda s: s['rank'])
    kept, left, left_safe = [], [], []
    full = (0.0, 0.0, 1.0, 1.0)
    for k in range(n):
        u = us = None
        kk, lo, los = set(), set(), set()
        for s in req:
            b = s['box'][k]
            if np.any(np.isnan(b)):
                continue
            pb = _padded(b, 'required', src_w, src_h, mx, my, 0.0)
            u2 = pb if u is None else union([u, pb])
            if _fits(u2, ww, wh, full, src_w, src_h):
                u = u2
                kk.add(s['id'])
                us2 = pb if us is None else union([us, pb])
                if safe != full:
                    if _fits(us2, ww, wh, safe, src_w, src_h):
                        us = us2
                    else:
                        los.add(s['id'])
            else:
                lo.add(s['id'])
        kept.append(kk)
        left.append(lo)
        left_safe.append(los)
    return kept, left, left_safe
