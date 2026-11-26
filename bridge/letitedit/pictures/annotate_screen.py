"""What else is on screen, and the layout of labels and insets.

Part of `annotate` (letitedit/pictures/annotate.py), which imports every name here back,
so `annotate.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import json
import math
import os
import subprocess
from pathlib import Path
from letitedit.pictures.annotate_geometry import (  # noqa: E402
    FFPROBE, NO_WINDOW, Unsupported, _props, box_area, box_center, box_distance, box_grow, box_h, box_inside,
    box_union, box_w, clip_places, overlap_area
)
from letitedit.pictures.annotate_chain import (  # noqa: E402
    chain_at, clip_chain, clip_span, point_in_quad
)


# ============================================================================ what else is on screen

_alpha = {}


def _has_alpha(path):
    """True when a picture/video file can be transparent (an alpha pixel format, or a PNG/GIF/WebP/TIFF image)."""
    key = os.path.normcase(os.path.abspath(path))
    if key not in _alpha:
        if Path(path).suffix.lower() in ('.png', '.gif', '.webp', '.tif', '.tiff'):
            _alpha[key] = True
        else:
            r = subprocess.run([str(FFPROBE), '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                'stream=pix_fmt', '-of', 'csv=p=0', str(path)], capture_output=True, text=True,
                               creationflags=NO_WINDOW, check=False)
            fmt = (r.stdout or '').strip().lower()
            _alpha[key] = any(x in fmt for x in ('yuva', 'rgba', 'argb', 'bgra', 'abgr', 'gbrap', 'ya8', 'ya16', 'pal8'))
    return _alpha[key]


def covered_spans(doc, place, F0, F1):
    """[(F_a, F_b, id, track, place)] where a clip on a video track above this one may cover the picture: footage,
    colours and made clips without transparency; graphics and files with an alpha channel don't count. A clip with its
    own Size/Position or crop is checked per frame by `covers_at` (it may cover only part of the frame)."""
    places = clip_places(doc)
    out = []
    for other in places.values():
        if other['track_kind'] != 'video' or other['track_index'] <= place['track_index']:
            continue
        a, b = clip_span(other)
        if b <= F0 or a >= F1:
            continue
        prod = other['producer']
        p = _props(prod) if prod is not None else {}
        if p.get('letitedit_ai:graphic') or (other['track_elem'].get('hide') in ('video', 'both')):
            continue
        res = p.get('warp_resource') or p.get('resource', '')
        if p.get('mlt_service') != 'color' and res and os.path.isfile(res) and _has_alpha(res):
            continue
        out.append((max(a, F0), min(b, F1), other['id'], other['track'], other))
    return out


def covers_at(doc, other, F, point):
    """Does the clip `other` (from covered_spans) hide `point` (output pixels) at timeline frame F? A clip whose
    picture fills the frame does; one with its own size/position or crop only where its picture is."""
    prod = other['producer']
    has_geom = any(c.tag == 'filter' and _props(c).get('mlt_service') in ('affine', 'crop') for c in prod)
    if not has_geom:
        return True
    try:
        ch = other.get('_chain') or clip_chain(doc, other)
        other['_chain'] = ch
        ev = chain_at(ch, other['in'] + (F - other['start']))
        return point_in_quad(point[0], point[1], ev['quad'], 0.0)
    except Unsupported:
        return True                                   # can't tell where its picture is: assume it covers


def protected_regions(doc, path, F0, F1, protect=None, platform=None, skip_ids=()):
    """Regions the label and inset must stay away from during [F0, F1): given boxes, burnt-in captions while a cue is
    on screen, other graphics on screen (their visible pixels), a platform's covered areas. Each is
    {name, box (output px), frames [a, b) relative to F0 or None (all), hard}."""
    W, H, fps = doc.width, doc.height, doc.fps
    out = []
    for k, pr in enumerate(protect or []):
        if isinstance(pr, dict):
            box, name = pr.get('box'), pr.get('name') or f'protect[{k}]'
            span = None
            if pr.get('start_s') is not None or pr.get('end_s') is not None:
                a = int(round(float(pr.get('start_s') or 0) * fps)) - F0
                b = int(round(float(pr['end_s']) * fps)) - F0 if pr.get('end_s') is not None else F1 - F0
                span = [a, b]
        else:
            box, name, span = pr, f'protect[{k}]', None
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise ValueError(f'protect[{k}] is a box [x0, y0, x1, y1] (fractions of the frame, or pixels) or '
                             '{box, start_s?, end_s?, name?}')
        b = [float(v) for v in box]
        if max(abs(v) for v in b) <= 1.5:
            b = [b[0] * W, b[1] * H, b[2] * W, b[3] * H]
        out.append({'name': name, 'box': (min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3])),
                    'frames': span, 'hard': True, 'source': 'given'})
    # burnt-in captions
    import letitedit.timeline.timeline_model as tm
    feeds = {}
    for f in doc.main.findall('filter'):
        fp = _props(f)
        if fp.get('mlt_service') == 'subtitle_feed':
            feeds[fp.get('feed', 'Subtitles')] = tm.parse_srt(fp.get('text', ''))
    for f in doc.main.findall('filter'):
        fp = _props(f)
        if fp.get('mlt_service') != 'subtitle' or fp.get('letitedit_ai:role') == 'shadow':
            continue
        try:
            x, y, w, h = [float(v) for v in str(fp.get('geometry')).split()[:4]]
        except ValueError:
            continue
        cues = [(s, e) for s, e, _ in feeds.get(fp.get('feed', 'Subtitles'), []) if s * fps < F1 and e * fps > F0]
        for s, e in cues:
            out.append({'name': f"captions ({fp.get('feed')})", 'box': (x, y, x + w, y + h),
                        'frames': [int(round(s * fps)) - F0, int(round(e * fps)) - F0], 'hard': True,
                        'source': 'captions'})
    # graphics on screen (titles, animated captions, other annotations)
    try:
        import letitedit.review.checks as checks
        for pl_id, other in clip_places(doc).items():
            prod = other['producer']
            if prod is None or other['track_kind'] != 'video' or pl_id in skip_ids:
                continue
            raw = _props(prod).get('letitedit_ai:graphic')
            if not raw:
                continue
            a, b = clip_span(other)
            if b <= F0 or a >= F1:
                continue
            g = json.loads(raw)
            if not g.get('file') or not os.path.exists(g['file']):
                continue
            lo, hi = max(a, F0), min(b, F1)
            boxes = [checks._graphic_bbox(g['file'], (f - other['start']) / fps) for f in
                     sorted({lo, (lo + hi) // 2, max(lo, hi - 2)})]
            box = box_union([bb for bb in boxes if bb])
            if box:
                label = (g.get('params') or {}).get('text') or g.get('template')
                out.append({'name': f"graphic {pl_id} ({str(label)[:30]})", 'box': tuple(float(v) for v in box),
                            'frames': [lo - F0, hi - F0], 'hard': True, 'source': 'graphic'})
    except Exception as e:  # noqa: BLE001 - graphics we can't read are reported, not fatal
        out.append({'name': f'(graphics not read: {e})', 'box': None, 'frames': None, 'hard': False, 'source': 'note'})
    if platform:
        import letitedit.catalogs.platforms as platforms
        prof = platforms.load(platform)
        for z in (prof.get('safe_zones') or {}).get('value') or []:
            out.append({'name': f"{prof['id']}: {z['name']}", 'box': (z['x'] * W, z['y'] * H, (z['x'] + z['w']) * W,
                                                                     (z['y'] + z['h']) * H),
                        'frames': None, 'hard': True, 'source': 'platform'})
    return [r for r in out if r.get('box')]


# ============================================================================ layout: labels and insets (shared geometry)

SIDES = {'right': (1.0, 0.0), 'left': (-1.0, 0.0), 'above': (0.0, -1.0), 'below': (0.0, 1.0),
         'above_right': (1.0, -1.0), 'above_left': (-1.0, -1.0), 'below_right': (1.0, 1.0), 'below_left': (-1.0, 1.0)}


def _beside(size, clear, side, gap, anchor_c):
    """A box of `size` beside the `clear` box on `side`, `gap` away, lined up with the anchor's centre."""
    w, h = size
    dx, dy = SIDES[side]
    cx, cy = anchor_c
    if dx > 0:
        x0 = clear[2] + gap * (0.72 if dy else 1.0)
    elif dx < 0:
        x0 = clear[0] - gap * (0.72 if dy else 1.0) - w
    else:
        x0 = cx - w / 2
    if dy > 0:
        y0 = clear[3] + gap * (0.72 if dx else 1.0)
    elif dy < 0:
        y0 = clear[1] - gap * (0.72 if dx else 1.0) - h
    else:
        y0 = cy - h / 2
    return (x0, y0, x0 + w, y0 + h)


def _slide_inside(box, side, safe):
    """Shift a box along the side's free axis so it stays inside `safe` (it keeps its side of the anchor)."""
    dx, dy = SIDES[side]
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if dy == 0 or dx == 0:
        if dx != 0:                                # left/right: slide vertically
            y0 = min(max(y0, safe[1]), safe[3] - h)
        else:                                      # above/below: slide horizontally
            x0 = min(max(x0, safe[0]), safe[2] - w)
    return (x0, y0, x0 + w, y0 + h)


def place_box(size, anchor, frame, avoid=(), clear=None, gaps=(40.0, 90.0, 160.0), prefer=None, margin=0.0,
              picture=None, sides=None):
    """Where a box of `size` (w, h) goes beside `anchor` (a box): inside `frame` less `margin`, off `clear` (the
    anchor's own drawing: a ring, a box; default the anchor) and off every box in `avoid` ([(name, box)]) - hard
    constraints; then the shortest gap, the preferred side, and covering less of `picture` (prefer empty bars) -
    soft costs. Returns {'box', 'side', 'gap', 'feasible', 'violations': [names], 'cost'}."""
    W, H = frame
    safe = (margin, margin, W - margin, H - margin)
    clear = clear or anchor
    ac = box_center(anchor)
    best = None
    for side in (sides or list(SIDES)):
        if side not in SIDES:
            continue
        for gi, gap in enumerate(gaps):
            box = _slide_inside(_beside(size, clear, side, gap, ac), side, safe)
            out_area = box_area(box) - overlap_area(box, safe)
            hard, names = out_area * 2.0, []
            if out_area > 0.5:
                names.append('frame edge')
            ov = overlap_area(box, clear)
            if ov > 0.5:
                hard += ov * 4
                names.append('the target')
            for name, ab in avoid:
                o = overlap_area(box, ab)
                if o > 0.5:
                    hard += o
                    names.append(name)
            dx, dy = SIDES[side]
            cost = box_distance(box, clear) + (25.0 if dx and dy else 0.0) + 8.0 * gi
            if prefer and prefer != 'auto' and side != prefer:
                cost += 600.0
            if picture:
                cost += 120.0 * overlap_area(box, picture) / max(1.0, box_area(box))
            key = (round(hard, 1), cost)
            if best is None or key < best[0]:
                best = (key, {'box': box, 'side': side, 'gap': gap, 'feasible': hard <= 0.5, 'violations': names,
                              'cost': round(cost, 2)})
    return best[1]


STYLE = {
    'color': 'secondary',        # pointer colour: a style-pack colour name or '#RRGGBB'
    'outline': 'dark',           # the dark edge that keeps it visible on light and dark footage
    'label_fill': 'dark',        # label box
    'label_text': 'light',
    'label_opacity': 0.88,
    'font': 'heading',           # style-pack font role (heading/body/captions) or a family name
    'size': 44,                  # label text size at 1080p
    'stroke': 7,                 # pointer line width at 1080p
    'pad': 0.3,                  # ring/box clearance around the target box (fraction of its size)
    'min_radius': 36,            # smallest ring radius at 1080p
    'arrow': 150,                # arrow length at 1080p
    'inset': 0.36,               # magnifier diameter as a share of the frame's shorter side
    'zoom': None,                # magnifier zoom (default: the target fills ~55% of the inset)
    'dim': 0.0,                  # 0-1: darken everything but the target (a spotlight)
    'fade_in': 0.3,              # seconds
    'fade_out': 0.25,
    'pop': True,                 # pop-in animation of the ring / label / inset
    'label_side': 'auto',        # right | left | above | below | above_right | ... | auto
    'margin': 0.035,             # frame margin (share of the shorter side) labels keep from the edges
}


def style_of(params):
    st = dict(STYLE)
    st.update({k: v for k, v in (params.get('style') or {}).items() if v is not None})
    return st


def expand_geom(geom):
    """params['geom'] -> per annotation frame: None (hidden) or (alpha_flag, cx, cy, box, quad|None)."""
    n = int(geom['n'])
    out = [None] * n
    keys = sorted(geom['keys'], key=lambda k: k[0])
    k = 0
    cur = None
    for i in range(n):
        while k < len(keys) and keys[k][0] <= i:
            cur = keys[k]
            k += 1
        if cur is None or not cur[1]:
            out[i] = None
            continue
        quad = None
        if len(cur) > 8 and cur[8]:
            q = cur[8]
            quad = [(q[0], q[1]), (q[2], q[3]), (q[4], q[5]), (q[6], q[7])]
        out[i] = (cur[1], cur[2], cur[3], (cur[4], cur[5], cur[6], cur[7]), quad)
    return out


def vis_alpha(frames, fps, fade_in_s, fade_out_s, lost_fade_frames=3):
    """Opacity per frame from visibility: 0 where hidden; fades in after a hidden stretch and starts fading BEFORE
    a hidden stretch (the geometry is known ahead), so a pointer is never drawn on a frame where the target is lost."""
    n = len(frames)
    a = [0.0 if f is None else (0.6 if f[0] == 2 else 1.0) for f in frames]
    fi = max(1, int(round(fade_in_s * fps)))
    fo = max(1, int(round(fade_out_s * fps)))
    out = list(a)
    for i in range(n):
        if a[i] == 0:
            continue
        # distance back to the last hidden frame / to the start, and ahead to the next hidden frame / the end
        back = next((j for j in range(i, -1, -1) if a[j] == 0), None)
        ahead = next((j for j in range(i, n) if a[j] == 0), None)
        v = a[i]
        if back is None:
            v *= min(1.0, (i + 1) / fi)
        else:
            v *= min(1.0, (i - back) / lost_fade_frames)
        if ahead is None:
            v *= min(1.0, (n - i) / fo)
        else:
            v *= min(1.0, (ahead - i) / (lost_fade_frames + 1))
        out[i] = max(0.0, min(1.0, v))
    return out


def _ring_radius(box, st, s, point):
    if point:
        return st['min_radius'] * s
    w, h = box_w(box), box_h(box)
    return max(st['min_radius'] * s, 0.5 * math.hypot(w, h) * (1.0 + 0.6 * float(st['pad'])))


def _edge_toward(center, radius, toward):
    dx, dy = toward[0] - center[0], toward[1] - center[1]
    d = math.hypot(dx, dy) or 1.0
    return (center[0] + dx / d * radius, center[1] + dy / d * radius)


def _closest_on_box(box, p):
    return (min(max(p[0], box[0]), box[2]), min(max(p[1], box[1]), box[3]))


def _span_avoid(params, n):
    """The protected areas (name, box) that show during the annotation's frames."""
    span_avoid = []
    for r in params.get('protect') or []:
        fr = r.get('frames')
        if fr is None or (fr[1] > 0 and fr[0] < n):
            span_avoid.append((r['name'], tuple(r['box'])))
    return span_avoid


def _label_text(text, W, H, st, measure, s, out):
    """The label's text block: lines fitted to the frame (shrunk down to size 26 while too wide); its padded
    size, or None without text."""
    # the label's text block
    label_size = None
    if text:
        maxw = (0.42 if W >= H else 0.80) * W
        size = float(st['size'])
        lines, (tw, th) = _fit_text(text, size, maxw, measure, s)
        while tw > maxw and size > 26:
            size -= 2
            lines, (tw, th) = _fit_text(text, size, maxw, measure, s)
        pad_x, pad_y = 24 * s, 14 * s
        label_size = (tw + 2 * pad_x, th + 2 * pad_y)
        out['text'] = {'lines': lines, 'size': size, 'pad': [pad_x, pad_y], 'block': [tw, th]}
    return label_size


def solve_layout(params, measure, fps=None):
    """Everything the drawing needs, decided once for the whole annotation: per-frame target (centre, box, ring
    radius), the label box (one place for the whole span when the target moves little; else an offset that follows
    it), the arrow, the magnifier inset, opacity per frame, and every constraint that could not be met.
    measure(text, size) -> (w, h) of the text block. Deterministic: the tool and the drawing get the same answer."""
    W, H = params['size']
    s = H / 1080.0
    fps = float(fps or params.get('fps') or 30.0)
    st = style_of(params)
    kind = params['kind']
    text = (params.get('text') or '').strip()
    point = params.get('point', False)
    frames = expand_geom(params['geom'])
    n = len(frames)
    alpha = vis_alpha(frames, fps, float(st['fade_in']), float(st['fade_out']))
    vis = [i for i, f in enumerate(frames) if f is not None]
    margin = float(st['margin']) * min(W, H)
    out = {'n': n, 'alpha': alpha, 'kind': kind, 'warnings': [], 'unresolved': [], 'mode': 'anchored',
           'label': None, 'inset': None, 'arrow': None}
    if not vis:
        out['unresolved'].append('the target is not visible on any frame of the range')
        return out
    radius = [(_ring_radius(f[3], st, s, point) if f else 0.0) for f in frames]
    centers = [(f[1], f[2]) if f else None for f in frames]
    mean_c = (sum(centers[i][0] for i in vis) / len(vis), sum(centers[i][1] for i in vis) / len(vis))
    motion = max(math.hypot(centers[i][0] - mean_c[0], centers[i][1] - mean_c[1]) for i in vis)
    out['mode'] = 'anchored' if motion <= 0.06 * H else 'follow'
    sample = vis if len(vis) <= 48 else [vis[int(k * (len(vis) - 1) / 47)] for k in range(48)]

    def clear_of(i):
        f = frames[i]
        if kind in ('ring', 'magnify', 'label'):
            r = radius[i] + (st['stroke'] + 4) * s
            return (f[1] - r, f[2] - r, f[1] + r, f[2] + r)
        g = (st['stroke'] + 10) * s if kind == 'box' else 6 * s
        return box_grow(f[3], g * (1 + float(st['pad'])) if kind == 'box' else g)
    sweep_clear = box_union([clear_of(i) for i in sample])
    sweep_anchor = box_union([frames[i][3] if not point else clear_of(i) for i in sample])
    picture = tuple(params['picture']) if params.get('picture') else None
    span_avoid = _span_avoid(params, n)
    side_pref = st.get('label_side') or 'auto'
    label_size = _label_text(text, W, H, st, measure, s, out)
    # the magnifier inset (with the label under it when there is text)
    avoid_now = list(span_avoid)
    if kind == 'magnify':
        D = float(st['inset']) * min(W, H)
        block = (D, D + (label_size[1] + 10 * s if label_size else 0.0))
        if label_size and label_size[0] > D:
            block = (label_size[0], block[1])
        res = place_box(block, sweep_anchor, (W, H), avoid=avoid_now, clear=sweep_clear,
                        gaps=(70 * s, 150 * s, 260 * s), prefer=side_pref, margin=margin, picture=None)
        bx = res['box']
        # the label goes on the far side of the inset from the target (never across the connector)
        label_on_top = bool(label_size) and SIDES[res['side']][1] < 0
        top = bx[1] + (label_size[1] + 10 * s if label_on_top else 0.0)
        inset = ((bx[0] + bx[2]) / 2 - D / 2, top, (bx[0] + bx[2]) / 2 + D / 2, top + D)
        out['inset'] = {'box': inset, 'side': res['side'], 'feasible': res['feasible']}
        if not res['feasible']:
            out['unresolved'].append(f"magnifier overlaps {', '.join(sorted(set(res['violations'])))}")
        if label_size:
            ly = inset[1] - 10 * s - label_size[1] if label_on_top else inset[3] + 10 * s
            lb = ((inset[0] + inset[2]) / 2 - label_size[0] / 2, ly,
                  (inset[0] + inset[2]) / 2 + label_size[0] / 2, ly + label_size[1])
            out['label'] = {'box': lb, 'side': res['side'], 'follow': None}
        tb = tuple((params.get('mag') or {}).get('box') or sweep_anchor)
        zoom = st.get('zoom')
        if not zoom:
            zoom = (0.55 * D) / max(8.0 * s, max(box_w(tb), box_h(tb)) if not point else 2 * radius[vis[0]])
        out['inset']['zoom'] = round(min(6.0, max(1.5, float(zoom))), 3)
        return out
    if label_size:
        gaps =(40 * s, 90 * s, 160 * s) if kind != 'arrow' else (float(st['arrow']) * s * 0.75, float(st['arrow']) * s,
                                                                   float(st['arrow']) * s * 1.5)
        if out['mode'] == 'anchored':
            res = place_box(label_size, sweep_anchor, (W, H), avoid=avoid_now, clear=sweep_clear, gaps=gaps,
                            prefer=side_pref, margin=margin, picture=picture)
            out['label'] = {'box': res['box'], 'side': res['side'], 'follow': None}
            if not res['feasible']:
                out['unresolved'].append(f"label overlaps {', '.join(sorted(set(res['violations'])))}")
        else:
            # follow the target: one side/gap for the whole span, chosen over sampled frames
            best = None
            for side in SIDES:
                if side_pref not in (None, 'auto') and side != side_pref:
                    continue
                for gap in gaps:
                    bad, names = 0.0, set()
                    for i in sample:
                        cb = clear_of(i)
                        box = _beside(label_size, cb, side, gap, centers[i])
                        safe = (margin, margin, W - margin, H - margin)
                        box = _slide_inside(box, side, safe)
                        o = box_area(box) - overlap_area(box, safe)
                        o += 4 * overlap_area(box, cb)
                        for name, ab in avoid_now:
                            oo = overlap_area(box, ab)
                            if oo > 0.5:
                                names.add(name)
                            o += oo
                        bad += o
                    key = (round(bad, 1), gap, 0 if not (SIDES[side][0] and SIDES[side][1]) else 1)
                    if best is None or key < best[0]:
                        best = (key, side, gap, names)
            _, side, gap, names = best
            out['label'] = {'box': None, 'side': side, 'follow': {'gap': gap}}
            if best[0][0] > 0.5:
                out['unresolved'].append('label leaves the frame or overlaps '
                                         f"{', '.join(sorted(names)) or 'the frame edge'} on some frames")
    if kind == 'arrow' and not label_size:
        L = float(st['arrow']) * s
        best = None
        safe = (margin, margin, W - margin, H - margin)
        for side, (dx, dy) in SIDES.items():
            if side_pref not in (None, 'auto') and side != side_pref:
                continue
            d = math.hypot(dx, dy)
            ux, uy = dx / d, dy / d
            bad, names = 0.0, set()
            for i in sample:
                c = centers[i]
                tip = _arrow_tip(frames[i], c, (c[0] + ux * 1000, c[1] + uy * 1000), s, point, radius[i])
                tail = (tip[0] + ux * L, tip[1] + uy * L)
                seg = (min(tip[0], tail[0]) - 12 * s, min(tip[1], tail[1]) - 12 * s,
                       max(tip[0], tail[0]) + 12 * s, max(tip[1], tail[1]) + 12 * s)
                if not box_inside((tail[0], tail[1], tail[0], tail[1]), safe):
                    bad += 1000.0
                for name, ab in avoid_now:
                    if overlap_area(seg, ab) > 0.5:
                        bad += overlap_area(seg, ab)
                        names.add(name)
            # arrows read best coming from above, diagonally, from the side with more room
            room = (W - mean_c[0]) if ux > 0 else mean_c[0] if ux < 0 else W / 2
            cost = (0 if dy < 0 and dx else 30 if dy < 0 else 60 if dx else 90) - room * 0.01
            key = (round(bad, 1), cost)
            if best is None or key < best[0]:
                best = (key, side, (ux, uy), names)
        out['arrow'] = {'side': best[1], 'dir': [round(best[2][0], 4), round(best[2][1], 4)], 'length': L}
        if best[0][0] > 0.5:
            out['unresolved'].append('arrow leaves the frame or crosses '
                                     f"{', '.join(sorted(best[3])) or 'the frame edge'} on some frames")
    return out


def _fit_text(text, size, maxw, measure, s):
    """Wrap text to maxw at size: (lines, (w, h))."""
    words = text.split()
    lines, cur = [], ''
    for para in text.split('\n'):
        cur = ''
        for wd in para.split():
            trial = (cur + ' ' + wd).strip()
            if cur and measure(trial, size)[0] > maxw:
                lines.append(cur)
                cur = wd
            else:
                cur = trial
        lines.append(cur)
    del words
    w, h = measure('\n'.join(lines), size)
    return lines, (w, h)


def _arrow_tip(frame_geom, c, toward, s, point, radius):
    """Where an arrow coming from `toward` stops: just outside the target box (or the point's small circle)."""
    if point:
        return _edge_toward(c, max(10 * s, radius * 0.45), toward)
    box = box_grow(frame_geom[3], 8 * s)
    dx, dy = toward[0] - c[0], toward[1] - c[1]
    d = math.hypot(dx, dy) or 1.0
    ux, uy = dx / d, dy / d
    # distance from the centre to the box edge along (ux, uy)
    hx, hy = box_w(box) / 2, box_h(box) / 2
    t = min(hx / abs(ux) if abs(ux) > 1e-9 else 1e9, hy / abs(uy) if abs(uy) > 1e-9 else 1e9)
    return (c[0] + ux * t, c[1] + uy * t)


def label_box_at(lay, i, frames, s, W, H, margin, label_size, kind, radius):
    """The label's box on frame i (follow mode moves it with the target, kept inside the frame)."""
    lab = lay.get('label')
    if not lab:
        return None
    if lab.get('box'):
        return tuple(lab['box'])
    f = frames[i]
    if f is None:
        return None
    if kind in ('ring', 'label', 'magnify'):
        r = radius + 4 * s
        cb = (f[1] - r, f[2] - r, f[1] + r, f[2] + r)
    else:
        cb = box_grow(f[3], 10 * s)
    box = _beside(label_size, cb, lab['side'], lab['follow']['gap'], (f[1], f[2]))
    safe = (margin, margin, W - margin, H - margin)
    box = _slide_inside(box, lab['side'], safe)
    x0 = min(max(box[0], safe[0]), safe[2] - label_size[0])
    y0 = min(max(box[1], safe[1]), safe[3] - label_size[1])
    return (x0, y0, x0 + label_size[0], y0 + label_size[1])
