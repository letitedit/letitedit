"""The module's settings and errors, geometry and the frame: boxes, the frame's size, platform overlays and the safe area.

Part of `caption_layout` (letitedit/pictures/caption_layout.py), which imports every name here back,
so `caption_layout.X` is the same object it always was.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
import letitedit.review.checks as checks          # melt/ffmpeg paths, the face detector; importing it sets the font folders melt loads

SCHEMA_VERSION = 'letitedit-caption-fit/1'
CACHE = checks.CACHE / 'caption-fit'
MELT, FFMPEG = checks.MELT, checks.FFMPEG
NO_WINDOW = 0x08000000
INF = float('inf')

SLOT_NAMES = ('free', 'top', 'high', 'middle', 'low', 'bottom')   # 'free': the middle of the room below the face (fit measures it)
DEFAULT_SLOTS = {'tall': ['bottom', 'low', 'middle', 'high', 'top'], 'wide': ['bottom', 'top']}
SEVERITY = {'fused_words': 'error', 'fused_at_peak': 'warning', 'missing_space': 'error',
            'suspected_missing_space': 'warning', 'too_small': 'error', 'auto_shrunk': 'warning',
            'too_many_lines': 'warning', 'outside_frame': 'error', 'outside_safe': 'warning',
            'platform_overlay': 'warning', 'covers_face': 'warning', 'covers_text': 'error',
            'protected_region': 'error', 'reading_speed': 'warning', 'too_short': 'warning', 'too_long': 'info',
            'overlapping_cues': 'warning', 'bad_break': 'info', 'render_mismatch': 'info'}
PREVIEW_ORDER = ['fused_words', 'missing_space', 'fused_at_peak', 'too_small', 'covers_text', 'protected_region',
                 'covers_face', 'outside_frame', 'platform_overlay', 'auto_shrunk', 'too_many_lines', 'outside_safe',
                 'reading_speed', 'too_short']
PLACE_KINDS = ('outside_frame', 'outside_safe', 'platform_overlay', 'covers_face', 'covers_text', 'protected_region')


class Refused(Exception):
    """A plan that would leave the captions worse, or lose a word. Its message is for the person reading the reply."""


class Conflict(Exception):
    """The project (or something the plan measured) changed since the proposal was made."""


class _Unsupported(Exception):
    pass


# ============================================================================ geometry

def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1]) if b else 0.0


def _inter(a, b):
    if not a or not b:
        return 0.0
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _shift(b, dx, dy):
    return (b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy) if b else None


def _pad(b, px, py=None):
    py = px if py is None else py
    return (b[0] - px, b[1] - py, b[2] + px, b[3] + py)


def _rbox(b, nd=1):
    return [round(float(v), nd) for v in b] if b else None


def parse_geometry(text, width, height):
    """(x, y, w, h) in pixels for an MLT rect: 'x y w h [opacity]', '10%/76%:80%x18%' (legacy form) or percentages.
    Raises ValueError for keyframed (animated) geometry, which the solver does not lay out."""
    s = str(text or '').strip()
    if not s:
        raise ValueError('empty geometry')
    if '=' in s or ';' in s:
        raise ValueError(f'animated geometry {s[:40]!r}')
    nums = re.findall(r'-?\d+(?:\.\d+)?%?', s)
    if len(nums) < 4:
        raise ValueError(f'geometry {s!r} has fewer than four numbers')
    pct = '%' in s
    vals = []
    for n, size in zip(nums[:4], (width, height, width, height)):
        v = float(n.rstrip('%'))
        vals.append((v / 100.0 * size if n.endswith('%') else v * size) if pct else v)
    return tuple(vals)


def _geom_text(x, y, w, h):
    return f'{int(round(x))} {int(round(y))} {int(round(w))} {int(round(h))} 1'


def _fmt(t):
    return checks.fmt(t)


def _slug(name):
    return re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-') or 't'


# ============================================================================ the frame: size, platform overlays, safe area

@dataclass
class Frame:
    width: int
    height: int
    fps: float
    shape: str
    platform: str | None
    zones: list
    safe: tuple
    min_size_px: float
    output_scale: float
    notes: list = field(default_factory=list)
    free_y: float | None = None     # the middle of the free area under the face (the 'free' place), once measured


def frame_spec(profile, platform=None, output=None, min_size_px=None, margin=None):
    """The frame captions are laid out in: project size, the platform's covered areas (pixels), the safe rectangle
    inside them and the margins, and the smallest readable text size (project pixels)."""
    W, H = int(profile['width']), int(profile['height'])
    fps = float(profile.get('fps') or 30)
    notes = []
    scale = 1.0
    if output:
        m = re.fullmatch(r'\s*(\d+)\s*[x:X*]\s*(\d+)\s*', str(output))
        if not m:
            raise ValueError(f"output {output!r}: give the export size as 'WIDTHxHEIGHT', e.g. '1080x1920'")
        ow, oh = int(m.group(1)), int(m.group(2))
        if abs(ow / oh - W / H) > 0.01:
            raise ValueError(f'output {ow}x{oh} has another shape than the project ({W}x{H}); captions are laid out on '
                             f"the project's own frame: make a version at that shape first (letitedit_versions)")
        scale = ow / W
        if abs(scale - 1) > 1e-6:
            notes.append(f'the export ({ow}x{oh}) is {scale:g} x the project frame; sizes are reported at export size')
    shape = 'tall' if H > W * 1.05 else 'wide'
    zones = []
    if platform:
        import letitedit.catalogs.platforms as platforms
        prof = platforms.load(platform)
        pw, ph = prof['export_preset']['width']['value'], prof['export_preset']['height']['value']
        zl = prof['safe_zones']['value'] or []
        if zl and pw and ph and abs(pw / ph - W / H) > 0.02:
            notes.append(f"{prof['name']}'s covered areas are for a {pw}x{ph} frame and this project is {W}x{H}, so "
                         f'they are not used')
            zl = []
        for z in zl:
            zones.append({'name': z['name'],
                          'box': (z['x'] * W, z['y'] * H, (z['x'] + z['w']) * W, (z['y'] + z['h']) * H),
                          'status': prof['safe_zones'].get('status'), 'confidence': prof['safe_zones'].get('confidence')})
        platform = prof['id']
    mx, my = (0.05 * W, 0.04 * H) if shape == 'tall' else (0.05 * W, 0.06 * H)
    if margin is not None:
        mx = my = float(margin) * min(W, H)
    x0, y0, x1, y1 = mx, my, W - mx, H - my
    for z in zones:
        bx0, by0, bx1, by1 = z['box']
        if bx1 - bx0 >= 0.9 * W:                 # a band across the frame: top or bottom
            if by0 <= 1 and by1 < H / 2:
                y0 = max(y0, by1 + 0.01 * H)
            elif by1 >= H - 1 and by0 > H / 2:
                y1 = min(y1, by0 - 0.01 * H)
        elif by1 - by0 >= 0.9 * H:               # a column down the frame: left or right
            if bx0 <= 1 and bx1 < W / 2:
                x0 = max(x0, bx1 + 0.01 * W)
            elif bx1 >= W - 1 and bx0 > W / 2:
                x1 = min(x1, bx0 - 0.01 * W)
    if min_size_px is None:
        min_size_px = 0.034 * min(W, H)          # about 37 px on a 1080-wide (or 1080-tall) frame
    else:
        min_size_px = float(min_size_px) / scale  # given at export size
    return Frame(W, H, fps, shape, platform, zones, (x0, y0, x1, y1), float(min_size_px), scale, notes)


def slot_anchor(frame, slot):
    """(y, align) where a caption block sits for a slot: 'bottom' puts the ink's bottom at y, 'top' its top, 'middle'
    its centre."""
    sy0, sy1 = frame.safe[1], frame.safe[3]
    if slot == 'free':
        return (frame.free_y if frame.free_y is not None else (sy0 + 0.75 * (sy1 - sy0))), 'middle'
    return {'top': (sy0, 'top'), 'high': (sy0 + 0.25 * (sy1 - sy0), 'middle'), 'middle': ((sy0 + sy1) / 2, 'middle'),
            'low': (sy0 + 0.75 * (sy1 - sy0), 'middle'), 'bottom': (sy1, 'bottom')}[slot]


def free_area(frame, obstacles):
    """The room for captions below the face, from the faces measured across the video: {'top' (the lowest chin seen),
    'bottom' (the bottom of the area the apps leave free), 'centre', 'chin_pct', ...} in project pixels, or None when
    there is no face or less room than one caption line. One place for the whole video: its middle."""
    chins = [b[3] for ob in obstacles if ob.kind == 'face' for _, b in ob.boxes if b]
    if not chins or frame.shape != 'tall':
        return None
    top, bottom = max(chins), frame.safe[3]
    if bottom - top < 0.05 * frame.height:
        return None
    return {'top': round(top, 1), 'bottom': round(bottom, 1), 'centre': round((top + bottom) / 2, 1),
            'top_pct': round(100 * top / frame.height, 1), 'bottom_pct': round(100 * bottom / frame.height, 1),
            'centre_pct': round(100 * (top + bottom) / 2 / frame.height, 1)}


def place_extra(name, slots, pref, w, free):
    """What a place costs beyond its fit: nothing for the preferred one. Where a free place exists, 'current' (wherever
    the captions happen to be now) is a move like any other, so the captions go to the middle of the free area."""
    if name == 'current':
        return (w.move + w.pref * 2) if free else 0.0
    return w.move + w.pref * abs(slots.index(name) - slots.index(pref))


def _merge_ranges(ranges):
    out = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + 0.05:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [[round(s, 3), round(e, 3)] for s, e in out]
