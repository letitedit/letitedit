"""The subject at a window's edge (T361): in a layout that puts the footage in a window (the picture drawn smaller than
the frame or partly off it, or partly under an opaque panel), whether what each shot is about sits at or past the
window's edge, where the source picture runs on unseen.

Behind the switch review_craft_checks (craft_checks.enabled, on by default). Off, nothing here runs.

Per visible shot of footage (craft_checks.visible_frames: the topmost picture) at least MIN_SHOT_S long:
  the window      where the shot's picture is seen, at the shot's middle: the engine fits the source to the frame,
                  then each Size/Position or zoom step in order fits the picture into its rectangle (centred, its
                  shape kept unless `distort`, as Shotcut's Size, Position & Rotate does), clipped to the frame each
                  time; less what an opaque layer above hides (footage or a still drawn opaque, or a code scene's,
                  motion clip's or graphic's own render read at its alpha; a layer hiding under MIN_PANEL of the frame,
                  such as a caption, doesn't count, nor one the same footage is drawn over again, as a cut-out is).
                  A shot seen over the whole frame has no window and is not measured further.
  what it shows   the share of the source picture hidden past each side of the window (the source runs on, unseen).
  the subject     on the source range the shot shows, without a graphics card (reframe's subjects, cached on disk):
                  the head (YuNet faces) when a face is found in at least FACE_MOST of the samples, else where the
                  picture moves with the camera's own motion taken out (the hands and the tool in hands-on footage),
                  when found in at least ACTION_MOST of them.
A finding (major) when, in at least MOST of at least three samples where the subject is found, it sits at an edge
where the source runs on: a face with at least HIDDEN_SHARE of its box unseen, or the strip of EDGE_SHARE of the
window's height (width) beyond one of its sides mostly unseen; the movement with the middle of its box unseen or within
CENTRE_EDGE of such an edge (its box runs down the arm to the source's own edge whenever a hand comes into the shot).
The window is read at the shot's middle (a Size/Position that moves within a shot is taken where it is then). A shot
whose geometry isn't modelled (a crop, a rotation, another effect that moves the picture) or whose source can't be
read is named as not measured; one whose subject isn't found is said so; neither is passed.

placement(item, W, H, src, t)      pure: where the source's pixels land in the frame and the box they're drawn in.
Canvas(...), edges(canvas, boxes, kind)   pure: the window as masks; the subject against it, sample by sample.
measure(project, script=None)      every windowed shot, its window, what it hides and its subject (reads media).
review(project)                    (findings, facts line, numbers) for the review bundle.
"""
from __future__ import annotations

import os
import subprocess

import letitedit.review.craft_checks as craft_checks

# [HYP numbers, set on Run 2 (the shafts at the window's bottom edge, a major in three fresh reviews) against Run 6
# (the same footage and Look, the shafts about a fifth of the window above its edge: "small", a minor) - T361]
EDGE_SHARE = 0.05      # the strip beyond a side of the subject, as a share of the window's height (width)
HIDDEN_SHARE = 0.25    # a subject with this share of its box unseen is cut by the window
CENTRE_EDGE = 0.10     # the middle of the movement this close to an edge (share of the window's height or width)
MOST = 0.5             # ... in at least this share of the samples where the subject is found
FACE_MOST = 0.5        # a shot is about a face when one is found in at least this share of its samples
ACTION_MOST = 0.3      # ... else about the movement in it, when that is found in at least this share
MIN_SHOT_S = 0.5       # shorter shots are left to the sliver and insert checks
SAMPLE_S = 0.2         # subject samples on the source range
MIN_PANEL = 0.15       # a layer above hides part of the window when it is opaque over this share of the frame
SCALE = 0.25           # masks at a quarter of the frame size
PAD = 0.5              # the masks reach this share of the frame past each side (the source that runs on past it)

SIDES = ('top', 'bottom', 'left', 'right')
STILL_KEYS = craft_checks.SAFE_KEYS | {'focus', 'distort', 'style', 'blur_pad', 'split_mute', 'mute'}   # sound, colour
STILL_EFFECTS = ('mute', 'blur_pad')
OVERLAY_EXT = {'.mov', '.webm', '.mkv', '.mp4', '.png', '.gif', '.webp', '.apng'}
IMAGE_EXT = {'.png', '.gif', '.webp', '.apng', '.jpg', '.jpeg'}


# ---------------------------------------------------------------------------- where the picture lands

def _nums(value):
    try:
        return [float(x) for x in (value.split() if isinstance(value, str) else value)]
    except (TypeError, ValueError):
        return None


def value_at(value, t):
    """A plain value, or {'keys': [[t, v, ...], ...]} at item time t (seconds from the item's start): linear between
    neighbouring keys for numbers and 'x y w h [o]' rectangles, the nearest key's value outside them."""
    if not isinstance(value, dict):
        return value
    keys = sorted(((float(k[0]), k[1]) for k in value.get('keys') or [] if isinstance(k, (list, tuple)) and len(k) >= 2),
                  key=lambda k: k[0])
    if not keys:
        return None
    if t <= keys[0][0]:
        return keys[0][1]
    for (ta, va), (tb, vb) in zip(keys, keys[1:]):
        if ta <= t <= tb:
            a, b = _nums(va), _nums(vb)
            if a is None or b is None or len(a) != len(b) or tb <= ta:
                return va
            u = (t - ta) / (tb - ta)
            mixed = [x + (y - x) * u for x, y in zip(a, b)]
            return mixed[0] if isinstance(va, (int, float)) else ' '.join(f'{x:g}' for x in mixed)
    return keys[-1][1]


def _rect_of(value, W, H):
    parts = value.split() if isinstance(value, str) else list(value)
    out = []
    for i, p in enumerate(parts[:4]):
        s = str(p).strip()
        out.append(float(s[:-1]) / 100.0 * (W if i % 2 == 0 else H) if s.endswith('%') else float(s))
    if len(out) < 4:
        raise ValueError(f'a rectangle is "x y w h", not {value!r}')
    return out


def _step_rect(effect, t, W, H):
    """(x, y, w, h) in frame pixels of a size_position or zoom step at item time t."""
    if 'zoom' in effect:
        import letitedit.timeline.edit_effects as ee
        static = {k: v for k, v in effect.items() if k in ('focus', 'style')}
        static['zoom'] = float(value_at(effect['zoom'], t))
        return _rect_of(ee.motion_rect(static, W, H, 30.0), W, H)
    return _rect_of(value_at(effect['size_position'], t), W, H)


def _clip(box, W, H):
    x0, y0, x1, y1 = max(0.0, box[0]), max(0.0, box[1]), min(float(W), box[2]), min(float(H), box[3])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def placement(item, W, H, src, t=0.0):
    """((sx, sy, tx, ty), box, '') or (None, None, why): where the source picture's pixels land in the frame at item
    time t (frame px = source px * s + t; the source's display size `src`) and the box of the frame its picture is
    drawn in; why: the effect it can't model."""
    sw, sh = float(src[0]), float(src[1])
    s = min(W / sw, H / sh)
    m = [s, s, (W - sw * s) / 2.0, (H - sh * s) / 2.0]
    box = _clip((m[2], m[3], m[2] + sw * s, m[3] + sh * s), W, H)
    for e in item.get('effects') or []:
        if isinstance(e, str):
            if e in STILL_EFFECTS:
                continue
            return None, None, f'its {e} effect'
        if not isinstance(e, dict):
            return None, None, "an effect it can't read"
        if 'size_position' in e or 'zoom' in e:
            if e.get('rotate') not in (None, 0, 0.0):
                return None, None, 'its rotation'
            try:
                x, y, w, h = _step_rect(e, t, W, H)
            except (TypeError, ValueError):
                return None, None, "a size and position it can't read"
            if w <= 0 or h <= 0:
                return None, None, 'an empty size and position'
            if e.get('distort'):
                ax, ay, ox, oy = w / W, h / H, x, y
            else:
                a = min(w / W, h / H)
                ax = ay = a
                ox, oy = x + (w - W * a) / 2.0, y + (h - H * a) / 2.0
            m = [m[0] * ax, m[1] * ay, m[2] * ax + ox, m[3] * ay + oy]
            box = _clip((box[0] * ax + ox, box[1] * ay + oy, box[2] * ax + ox, box[3] * ay + oy), W, H) if box else None
            continue
        for k, v in e.items():
            if k == 'filter' and str(v) not in craft_checks.SAFE_FILTERS:
                return None, None, f'its {v} filter'
            if k not in STILL_KEYS:
                return None, None, f'its {k} effect'
    if box is None:
        return None, None, 'its picture is outside the frame'
    return tuple(m), box, ''


def to_frame(m, b):
    """A source-pixel box through the placement m, in frame pixels."""
    return (b[0] * m[0] + m[2], b[1] * m[1] + m[3], b[2] * m[0] + m[2], b[3] * m[1] + m[3])


# ---------------------------------------------------------------------------- the subject against the window

class Canvas:
    """Boolean masks over the frame and PAD of it past each side, at SCALE: `source` where the shot's source picture
    lies (seen or not), `seen` where it is seen."""

    def __init__(self, W, H, m, src, box, hidden=None):
        import numpy as np
        self.W, self.H = float(W), float(H)
        self.ox, self.oy = PAD * W, PAD * H
        self.w, self.h = int(round(W * (1 + 2 * PAD) * SCALE)), int(round(H * (1 + 2 * PAD) * SCALE))
        self.source = np.zeros((self.h, self.w), bool)
        self.seen = np.zeros((self.h, self.w), bool)
        full = to_frame(m, (0.0, 0.0, float(src[0]), float(src[1])))
        self.source[self._slice(full)] = True
        self.seen[self._slice(box)] = True
        if hidden is not None:                      # opaque layers above, a frame-sized mask at SCALE
            fr = self._slice((0.0, 0.0, W, H))
            hh, ww = self.seen[fr].shape
            under = np.zeros((hh, ww), bool)
            a, b = min(hh, hidden.shape[0]), min(ww, hidden.shape[1])
            under[:a, :b] = hidden[:a, :b]
            self.seen[fr] &= ~under
        self.seen &= self.source
        ys, xs = np.nonzero(self.seen)
        self.window = None if not len(xs) else (xs.min() / SCALE - self.ox, ys.min() / SCALE - self.oy,
                                                (xs.max() + 1) / SCALE - self.ox, (ys.max() + 1) / SCALE - self.oy)

    def _slice(self, b):
        x0 = int(max(0, min(self.w, round((b[0] + self.ox) * SCALE))))
        x1 = int(max(0, min(self.w, round((b[2] + self.ox) * SCALE))))
        y0 = int(max(0, min(self.h, round((b[1] + self.oy) * SCALE))))
        y1 = int(max(0, min(self.h, round((b[3] + self.oy) * SCALE))))
        return slice(y0, y1), slice(x0, x1)

    def whole(self):
        """True when the shot is seen over (almost) the whole frame: no window."""
        fr = self._slice((0.0, 0.0, self.W, self.H))
        return self.seen[fr].mean() >= 0.98

    def hidden_past(self, full):
        """{side: share of the source picture past that side of the window} (frame px box of the full source)."""
        if self.window is None:
            return {}
        x0, y0, x1, y1 = self.window
        fw, fh = full[2] - full[0], full[3] - full[1]
        out = {'top': (y0 - full[1]) / fh, 'bottom': (full[3] - y1) / fh,
               'left': (x0 - full[0]) / fw, 'right': (full[2] - x1) / fw}
        return {k: round(v, 3) for k, v in out.items() if v > 0.005}

    def against(self, b):
        """(hidden share of the box, {side: True when the strip beyond that side is mostly unseen source}, {side: gap
        in frame px from the box's side to the window's edge})."""
        sl = self._slice(b)
        src, seen = self.source[sl], self.seen[sl]
        n = int(src.sum())
        hidden = float((src & ~seen).sum()) / n if n else 0.0
        wx0, wy0, wx1, wy1 = self.window
        dy, dx = EDGE_SHARE * (wy1 - wy0), EDGE_SHARE * (wx1 - wx0)
        strips = {'top': (b[0], b[1] - dy, b[2], b[1]), 'bottom': (b[0], b[3], b[2], b[3] + dy),
                  'left': (b[0] - dx, b[1], b[0], b[3]), 'right': (b[2], b[1], b[2] + dx, b[3])}
        at = {}
        for side, strip in strips.items():
            ss = self._slice(strip)
            s_src, s_seen = self.source[ss], self.seen[ss]
            if s_src.size == 0 or s_src.mean() < 0.5:      # the source itself ends there: not the window's doing
                at[side] = False
                continue
            at[side] = float((s_src & ~s_seen).sum()) / float(s_src.sum()) >= 0.5
        gaps = {'top': b[1] - wy0, 'bottom': wy1 - b[3], 'left': b[0] - wx0, 'right': wx1 - b[2]}
        return hidden, at, gaps

    def point(self, p):
        """(1.0 when the point is unseen else 0.0, {side: True when it lies within CENTRE_EDGE of the window's height
        (width) of that side, or past it, and the source runs on past that side}, {side: gap in frame px})."""
        wx0, wy0, wx1, wy1 = self.window
        x, y = p
        wh, ww = wy1 - wy0, wx1 - wx0
        r = 2.0 / SCALE                              # two mask cells either side of the point
        inside = self.seen[self._slice((x - r, y - r, x + r, y + r))]
        unseen = 0.0 if inside.size and inside.mean() >= 0.5 else 1.0
        gaps = {'top': y - wy0, 'bottom': wy1 - y, 'left': x - wx0, 'right': wx1 - x}
        beyond = {'top': (x - r, wy0 - 0.03 * wh - r, x + r, wy0 - 0.01 * wh),
                  'bottom': (x - r, wy1 + 0.01 * wh, x + r, wy1 + 0.03 * wh + r),
                  'left': (wx0 - 0.03 * ww - r, y - r, wx0 - 0.01 * ww, y + r),
                  'right': (wx1 + 0.01 * ww, y - r, wx1 + 0.03 * ww + r, y + r)}
        at = {}
        for side, strip in beyond.items():
            s = self.source[self._slice(strip)]
            runs_on = bool(s.size) and s.mean() >= 0.5
            share = gaps[side] / (wh if side in ('top', 'bottom') else ww)
            at[side] = runs_on and share <= CENTRE_EDGE
        return unseen, at, gaps


def edges(canvas, boxes, kind='face'):
    """{'samples', 'at_edge', 'share', 'side', 'gap_px', 'hidden'}: the subject's frame-px boxes (None where not found)
    against the window; at_edge counts the samples where the subject sits on an edge where the source runs on. A
    face: at least HIDDEN_SHARE of its box unseen, or the strip beyond one of its sides mostly unseen source. The
    movement: the middle of its box unseen or within CENTRE_EDGE of such an edge (the box of the movement reaches
    the source's own edge whenever a hand or an arm comes into the shot; its middle is where the work is)."""
    import statistics
    rows = []
    for b in boxes:
        if b is None:
            continue
        if kind == 'movement':
            rows.append(canvas.point(((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)))
        else:
            rows.append(canvas.against(b))
    if not rows:
        return {'samples': 0, 'at_edge': 0, 'share': 0.0, 'side': None, 'gap_px': None, 'hidden': None}
    count = {s: sum(1 for _, at, _ in rows if at[s]) for s in SIDES}
    side = max(SIDES, key=lambda s: count[s])
    edge = sum(1 for hidden, at, _ in rows if hidden >= HIDDEN_SHARE or any(at.values()))
    return {'samples': len(rows), 'at_edge': edge, 'share': round(edge / len(rows), 3),
            'side': side if count[side] else None,
            'gap_px': round(statistics.median(g[side] for _, _, g in rows), 1) if count[side] else None,
            'hidden': round(statistics.median(h for h, _, _ in rows), 3)}


# ---------------------------------------------------------------------------- reading the project

def _runs(script):
    fps, top = craft_checks.visible_frames(script)
    runs = []
    for f, rec in enumerate(top):
        if runs and runs[-1][0] is rec:
            runs[-1][2] = f + 1
        else:
            runs.append([rec, f, f + 1])
    return fps, runs


def _items_at(script, f, fps):
    """[(track order, item)] of the shown video tracks' items over timeline frame f."""
    out = []
    tracks = [t for t in script.get('tracks') or [] if t.get('kind', 'video') == 'video'
              and t.get('hide') not in ('video', 'both')]
    for order, t in enumerate(tracks):
        for it in t.get('items') or []:
            if 'at' not in it or 'len' not in it:
                continue
            a = int(round(craft_checks._secs(it['at']) * fps))
            if a <= f < a + int(round(float(it['len']) * fps)):
                out.append((order, t.get('name'), it))
    return out


def _shows(it):
    """The footage an item draws (its clip, or a cut-out's source)."""
    vfx = it.get('vfx') if isinstance(it.get('vfx'), dict) else {}
    return os.path.normcase(str(it.get('clip') or vfx.get('source') or ''))


def read_alpha(resource, t, W, H, ffmpeg):
    """A frame-sized boolean mask at SCALE of where a layer's own render is opaque at its time t, or None."""
    import numpy as np
    w, h = int(round(W * SCALE)), int(round(H * SCALE))
    seek = [] if os.path.splitext(resource)[1].lower() in IMAGE_EXT else ['-ss', f'{max(0.0, t):.3f}']
    vf = (f'format=rgba,scale={w}:{h}:force_original_aspect_ratio=decrease,'
          f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black@0,format=rgba')
    raw = subprocess.run([str(ffmpeg), '-v', 'error', *seek, '-i', resource, '-frames:v', '1', '-vf', vf,
                          '-f', 'rawvideo', '-'], capture_output=True, timeout=120,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    if len(raw) < w * h * 4:
        return None
    return np.frombuffer(raw[:w * h * 4], np.uint8).reshape(h, w, 4)[:, :, 3] >= 128


def _render_of(project, it, place):
    """The file a layer's picture is drawn from: a code scene's finished render of its revision, else the clip's own
    file (a graphic, a motion clip)."""
    scene = it.get('scene')
    if isinstance(scene, dict) and scene.get('id') and scene.get('revision'):
        import letitedit.pictures.code_scenes as code_scenes
        try:
            movie = code_scenes.finished_render(code_scenes.revision_dir(project, scene['id'], scene['revision']),
                                                scene['revision'])
        except ValueError:
            return None
        return str(movie) if movie else None
    return _resource(place)


def _overlays(script, places, order, f, fps, file, W, H, ffmpeg, notes, project=None):
    """A frame-sized mask at SCALE of what opaque layers above track `order` hide at timeline frame f, or None."""
    import numpy as np
    w, h = int(round(W * SCALE)), int(round(H * SCALE))
    hidden = np.zeros((h, w), bool)
    above = [(o, name, it) for o, name, it in _items_at(script, f, fps) if o > order]
    for o, name, it in above:
        if any(o2 > o and _shows(it2) == os.path.normcase(str(file)) for o2, _, it2 in above):
            continue                                 # the same footage drawn over it again (a cut-out): not hidden
        mask = None
        if craft_checks._source(it) is not None:
            if it.get('transition') or not craft_checks._opaque(it, W, H, whole=False):
                continue
            mask = np.zeros((h, w), bool)
            for r in craft_checks._rects(it, W, H) or []:
                mask[int(r[1] * SCALE):int(r[3] * SCALE), int(r[0] * SCALE):int(r[2] * SCALE)] = True
        elif it.get('scene') or it.get('motion') or it.get('graphic') or it.get('clip'):
            place = places.get(it.get('id'))
            res = _render_of(project, it, place)
            if it.get('scene') and not res:
                notes.append(f"{it.get('id')} on {name}: a code scene with no finished render, not read as a panel")
                continue
            if not res or os.path.splitext(res)[1].lower() not in OVERLAY_EXT or not os.path.isfile(res):
                continue
            if any(isinstance(e, dict) and ('size_position' in e or 'zoom' in e) for e in it.get('effects') or []):
                notes.append(f"{it.get('id')} on {name} has its own size and position: not read as a panel")
                continue
            local = (place['in'] + (f - place['start'])) / fps if place else 0.0
            mask = read_alpha(res, local, W, H, ffmpeg)
            if mask is None:
                notes.append(f"{it.get('id')} on {name}: its render could not be read")
                continue
        if mask is not None and mask.mean() >= MIN_PANEL:
            hidden |= mask
    return hidden if hidden.any() else None


def _resource(place):
    if not place or place.get('producer') is None:
        return None
    props = {p.get('name'): (p.text or '') for p in place['producer'].findall('property')}
    return props.get('warp_resource') or props.get('resource') or None


def _subject(file, info, s0, s1):
    """('face' | 'movement' | None, [source-px box or None per sample]) on the source range [s0, s1)."""
    import numpy as np
    import letitedit.pictures.reframe as reframe
    grid = np.arange(s0, s1, SAMPLE_S)
    if len(grid) < 2:
        grid = np.array([s0, (s0 + s1) / 2.0])
    subjects, _ = reframe.subjects_for(file, info, s0, s1, grid, sources=('face', 'action'))

    def series(kind):
        out = []
        for i in range(len(grid)):
            found = [s['box'][i] for s in subjects if s['kind'] == kind and not np.any(np.isnan(s['box'][i]))]
            out.append(max(found, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if found else None)
        return out
    faces = series('face')
    if sum(b is not None for b in faces) >= FACE_MOST * len(grid):
        return 'face', faces
    moves = series('action')
    if sum(b is not None for b in moves) >= ACTION_MOST * len(grid):
        return 'movement', moves
    return None, []


def measure(project, script=None):
    """{'shots': [...], 'not_measured': [...], 'notes': [...]}: every visible shot of footage at least MIN_SHOT_S long
    that is seen in a window, with its window (frame px), the source hidden past each side, and its subject's
    measure (edges); shots it can't measure, with why."""
    import letitedit.timeline.edit_script as es
    import letitedit.pictures.annotate as annotate
    import letitedit.pictures.reframe as reframe
    import letitedit.review.checks as checks
    script = script or es.read(project)
    prof = script.get('profile') or {}
    W, H = float(prof.get('width') or 1920), float(prof.get('height') or 1080)
    fps, runs = _runs(script)
    try:
        places = annotate.clip_places(annotate.load_doc(project)[0])
    except Exception as e:  # noqa: BLE001 - no panels read; said
        places, notes = {}, [f'layers above not read ({type(e).__name__})']
    else:
        notes = []
    tracks = [t.get('name') for t in script.get('tracks') or [] if t.get('kind', 'video') == 'video'
              and t.get('hide') not in ('video', 'both')]
    shots, skipped = [], []
    for rec, f0, f1 in runs:
        if rec is None or rec.get('in_s') is None or (f1 - f0) / fps < MIN_SHOT_S:
            continue
        label = f"{rec['id']} {f0 / fps:.2f}-{f1 / fps:.2f}"
        item = _item(script, rec['id'])
        try:
            info = reframe.media(rec['file'])
        except Exception as e:  # noqa: BLE001 - said, never a pass
            skipped.append(f'{label}: its source could not be read ({type(e).__name__})')
            continue
        fm = (f0 + f1) // 2
        m, box, why = placement(item or {}, W, H, info['display'], (fm - rec['f0']) / fps)
        if m is None:
            skipped.append(f'{label}: {why}')
            continue
        order = tracks.index(rec['track']) if rec['track'] in tracks else 0
        hidden = _overlays(script, places, order, fm, fps, rec['file'], W, H, checks.FFMPEG, notes, project)
        canvas = Canvas(W, H, m, info['display'], box, hidden)
        if canvas.window is None or canvas.whole():
            continue
        s0 = float(rec['in_s']) + (f0 - rec['f0']) * rec['speed'] / fps
        s1 = float(rec['in_s']) + (f1 - rec['f0']) * rec['speed'] / fps
        full = to_frame(m, (0.0, 0.0) + tuple(info['display']))
        shot = {'id': rec['id'], 't0': round(f0 / fps, 3), 't1': round(f1 / fps, 3), 'file': rec['file'],
                'window_px': [round(v) for v in canvas.window], 'hidden_past': canvas.hidden_past(full),
                'shows': _shows_share(canvas.window, full)}
        try:
            kind, boxes = _subject(rec['file'], info, s0, s1)
        except Exception as e:  # noqa: BLE001 - said, never a pass
            kind, boxes = None, []
            shot['subject_error'] = type(e).__name__
        shot['subject'] = kind
        if kind:
            shot.update(edges(canvas, [to_frame(m, b) if b is not None else None for b in boxes], kind))
        shots.append(shot)
    return {'shots': shots, 'not_measured': skipped, 'notes': list(dict.fromkeys(notes))}


def _item(script, item_id):
    for t in script.get('tracks') or []:
        for it in t.get('items') or []:
            if it.get('id') == item_id:
                return it
    return None


def _shows_share(window, full):
    """'x a-b%, y c-d%': the part of the source picture the window shows."""
    fw, fh = full[2] - full[0], full[3] - full[1]
    xa, xb = (window[0] - full[0]) / fw, (window[2] - full[0]) / fw
    ya, yb = (window[1] - full[1]) / fh, (window[3] - full[1]) / fh
    return f'x {max(0, xa):.0%}-{min(1, xb):.0%}, y {max(0, ya):.0%}-{min(1, yb):.0%}'


# ---------------------------------------------------------------------------- for the review bundle

def flagged(shot):
    return bool(shot.get('subject')) and shot.get('samples', 0) >= 3 and shot.get('share', 0) >= MOST


def _gap(px):
    return f'{px:.0f} px inside it' if px >= 0 else f'{-px:.0f} px past it'


def finding(shot):
    side = shot.get('side')
    where = (f"at the window's {side} edge" + (f" ({_gap(shot['gap_px'])}, median)" if shot.get('gap_px') is not None
                                                else '')) if side else 'cut by the window'
    if shot['subject'] == 'face':
        subject = (f"the face sits {where} in {shot['share']:.0%} of the shot, {shot['hidden']:.0%} of it unseen "
                   "(median)")
    else:
        subject = (f"the middle of the movement in it (hands, a tool, the thing shown) sits {where} in "
                   f"{shot['share']:.0%} of the shot")
    hides = ', '.join(f'{v:.0%} of the source past the {k}' for k, v in (shot.get('hidden_past') or {}).items())
    return {'at': shot['t0'], 't1': shot['t1'], 'severity': 'major', 'check': 'window_edge',
            'what': f"{shot['id']} ({shot['t0']:.2f}-{shot['t1']:.2f}) is seen in a window (x {shot['window_px'][0]}-"
                    f"{shot['window_px'][2]}, y {shot['window_px'][1]}-{shot['window_px'][3]}) that shows "
                    f"{shot['shows']} of its source{f' ({hides})' if hides else ''}: {subject}",
            'fix': "Move or scale the clip inside the window (its size and position) so what the shot is about sits "
                   "clear of the edge, giving up the part of the picture the shot isn't about, then look at the "
                   "frames."}


def _line(s):
    """One windowed shot as the critic reads it."""
    w = s['window_px']
    past = ', '.join(f'{v:.0%} past the {k}' for k, v in (s.get('hidden_past') or {}).items())
    if not s.get('subject'):
        subject = 'subject not found (no face, too little movement)'
    else:
        what = 'face' if s['subject'] == 'face' else 'middle of the movement'
        subject = (f"{what} at the window's {s['side']} edge in {s['share']:.0%} of samples ({_gap(s['gap_px'])}, median)"
                   if s.get('side') else f"{what} at a window edge in {s['share']:.0%} of samples")
    return (f"{s['id']} {s['t0']:.2f}-{s['t1']:.2f}: x {w[0]}-{w[2]}, y {w[1]}-{w[3]}; shows {s['shows']}"
            + (f' ({past})' if past else '') + f'; {subject}')


def review(project):
    """(findings, facts line, numbers) for the review bundle."""
    got = measure(project)
    rows = [finding(s) for s in got['shots'] if flagged(s)]
    numbers = {'shots_seen_in_a_window (window in frame px; part of the source shown; subject against the window)': [
        _line(s) for s in got['shots']]}
    if got['not_measured']:
        numbers['windowed_shots_not_measured'] = got['not_measured']
    unknown = [s['id'] for s in got['shots'] if not s['subject']]
    facts = (f"{len(got['shots'])} shot(s) seen in a window; subject at the window's edge in {len(rows)}"
             + (f" ({', '.join(r['what'].split(' ', 1)[0] for r in rows)})" if rows else '')
             + (f"; subject not found in {len(unknown)}" if unknown else '')
             + (f"; not measured: {'; '.join(got['not_measured'])}" if got['not_measured'] else '')
             + (f"; {'; '.join(got['notes'])}" if got['notes'] else ''))
    return rows, facts, numbers if got['shots'] or got['not_measured'] else {}
