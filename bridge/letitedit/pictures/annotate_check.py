"""The checks against the export engine.

Part of `annotate` (letitedit/pictures/annotate.py), which imports every name here back,
so `annotate.X` is the same object it always was.
"""
from __future__ import annotations
import math
from letitedit.pictures.annotate_geometry import (  # noqa: E402
    box_center, box_grow, box_h, box_inter, box_w, map_box, mat_apply, mat_inv, mat_mul, mat_scale, mat_scale_of,
    mat_translate
)
from letitedit.pictures.annotate_screen import (  # noqa: E402
    _arrow_tip, _closest_on_box, _ring_radius, label_box_at, style_of
)
from letitedit.pictures.annotate_draw import (  # noqa: E402
    _box_outline
)


# ============================================================================ checking against the export engine

def _gray(img):
    import numpy as np
    a = np.asarray(img.convert('RGB'), dtype=np.float32)
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def locate_target(render_png, source_img, src_box, m, search=48.0, scales=(1.0,), context=0.6, min_px=28.0,
                  visible=None, max_side=320):
    """Where the object is in a rendered frame, found from the pixels (not from the transform): the source patch
    around src_box (display pixels), drawn through the clip's transform m to its on-screen size, is matched
    (normalised cross-correlation, grey, lightly blurred) within `search` px of where m puts it; `scales` tries other
    sizes too. Only what is on screen is matched (`visible`: the picture's box in the frame); big patches are matched
    at reduced resolution (longest side max_side). Returns {'found': [x, y], 'predicted': [x, y], 'error_px',
    'score', 'scale', 'texture'} or None."""
    import cv2
    import numpy as np
    from PIL import Image
    W0, H0 = source_img.size
    bw, bh = box_w(src_box), box_h(src_box)
    sc = mat_scale_of(m) or 1.0
    grow_x = max(bw * context, (min_px / sc - bw) / 2, 4.0)
    grow_y = max(bh * context, (min_px / sc - bh) / 2, 4.0)
    region = (max(0.0, src_box[0] - grow_x), max(0.0, src_box[1] - grow_y), min(float(W0), src_box[2] + grow_x),
              min(float(H0), src_box[3] + grow_y))
    pred = mat_apply(m, *box_center(src_box))
    frame = Image.open(render_png).convert('RGB')
    FW, FH = frame.size
    g_full = _gray(frame)
    best = None
    for k in scales:
        mk = mat_mul(mat_translate(pred[0], pred[1]), mat_mul(mat_scale(k, k), mat_translate(-pred[0], -pred[1])))
        mm = mat_mul(mk, m)
        obox, _ = map_box(mm, region)
        # keep to what is on screen, and leave room for the search window inside the frame
        lim = box_inter(tuple(visible), (0, 0, FW, FH)) if visible else (0, 0, FW, FH)
        if lim is None:
            continue
        lim = (max(lim[0], search), max(lim[1], search), min(lim[2], FW - search), min(lim[3], FH - search))
        tb = box_inter(obox, lim)
        if tb is None or box_w(tb) < 12 or box_h(tb) < 12:
            continue
        r = min(1.0, max_side / max(box_w(tb), box_h(tb)))
        tw, th = max(8, int(round(box_w(tb) * r))), max(8, int(round(box_h(tb) * r)))
        # template pixel (u, v) -> output (tb.x0 + u / r, ...) -> source
        inv = mat_mul(mat_inv(mm), mat_mul(mat_translate(tb[0], tb[1]), mat_scale(1 / r, 1 / r)))
        tmpl = source_img.convert('RGB').transform((tw, th), Image.AFFINE,
                                                   data=(inv[0][0], inv[0][1], inv[0][2], inv[1][0], inv[1][1], inv[1][2]),
                                                   resample=Image.BICUBIC)
        g_t = cv2.GaussianBlur(_gray(tmpl), (0, 0), 1.0)
        texture = float(g_t.std())
        wx0, wy0 = int(math.floor(tb[0] - search)), int(math.floor(tb[1] - search))
        wx1, wy1 = int(math.ceil(tb[2] + search)), int(math.ceil(tb[3] + search))
        wx0, wy0, wx1, wy1 = max(0, wx0), max(0, wy0), min(FW, wx1), min(FH, wy1)
        win = g_full[wy0:wy1, wx0:wx1]
        if r < 1.0:
            win = cv2.resize(win, (max(1, int(round(win.shape[1] * r))), max(1, int(round(win.shape[0] * r)))),
                             interpolation=cv2.INTER_AREA)
        win = cv2.GaussianBlur(win, (0, 0), 1.0)
        if win.shape[0] <= th or win.shape[1] <= tw:
            continue
        res = cv2.matchTemplate(win, g_t, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        # a second peak almost as good elsewhere = a repeating pattern (vanes, grilles, text): the match is ambiguous
        rad = max(4, int(0.3 * min(tw, th)))
        masked = res.copy()
        masked[max(0, loc[1] - rad):loc[1] + rad + 1, max(0, loc[0] - rad):loc[0] + rad + 1] = -1.0
        second = float(masked.max()) if masked.size else -1.0
        px, py = float(loc[0]), float(loc[1])
        # sub-pixel peak (parabola through the neighbours)
        if 0 < loc[0] < res.shape[1] - 1:
            l, c0, rr = res[loc[1], loc[0] - 1], res[loc[1], loc[0]], res[loc[1], loc[0] + 1]
            den = l - 2 * c0 + rr
            px += 0.5 * (l - rr) / den if abs(den) > 1e-9 else 0.0
        if 0 < loc[1] < res.shape[0] - 1:
            u, c0, d = res[loc[1] - 1, loc[0]], res[loc[1], loc[0]], res[loc[1] + 1, loc[0]]
            den = u - 2 * c0 + d
            py += 0.5 * (u - d) / den if abs(den) > 1e-9 else 0.0
        found_tl = (wx0 + float(px) / r, wy0 + float(py) / r)
        shift = (found_tl[0] - tb[0], found_tl[1] - tb[1])
        found = (pred[0] + shift[0], pred[1] + shift[1])
        cand = {'found': [round(found[0], 2), round(found[1], 2)], 'predicted': [round(pred[0], 2), round(pred[1], 2)],
                'error_px': round(math.hypot(*shift), 2), 'score': round(float(score), 3), 'scale': k,
                'texture': round(texture, 1), 'matched_at': round(r, 3),
                'second_peak': round(second, 3), 'ambiguity': round(second / score, 3) if score > 0 else 1.0}
        if best is None or cand['score'] > best['score']:
            best = cand
    del np
    return best


def verdict(loc):
    """How far to trust a locate_target result: 'matched' (use it), or why not."""
    if not loc or 'found' not in loc:
        return 'not found'
    if loc['texture'] < 4.0:
        return 'flat patch (nothing to match)'
    if loc.get('ambiguity', 0) >= 0.92:
        return 'ambiguous (a repeating pattern matches in several places)'
    if loc['score'] >= 0.75:
        return 'matched'
    if loc['score'] >= 0.5:
        return 'weak (the object looks different here: blur, angle, light)'
    return 'not found'


def measure_pointer(before_png, after_png, kind, color, predicted_center, radius, window=None, tol=60, exclude=(),
                    box=None, segments=()):
    """Where the drawn pointer is in a rendered frame: pixels that changed between a render without and with the
    annotation and have the pointer's colour (boxes in `exclude`, such as the label, are left out). ring/magnify: the
    circle fitted to them (centre, radius); arrow: the coloured points (see arrow_tip); box: the centre of the outline
    found around the expected `box`. Returns {'center': [x, y], 'radius'?, 'pixels'} or None."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(before_png).convert('RGB'), dtype=np.int32)
    b = np.asarray(Image.open(after_png).convert('RGB'), dtype=np.int32)
    changed = np.abs(a - b).max(axis=2) > 30
    col = np.abs(b - np.array(color[:3], dtype=np.int32)).max(axis=2) < tol
    mask = changed & col
    H, W = mask.shape
    for ex in exclude or ():
        ex0, ey0 = int(max(0, math.floor(ex[0] - 3))), int(max(0, math.floor(ex[1] - 3)))
        ex1, ey1 = int(min(W, math.ceil(ex[2] + 3))), int(min(H, math.ceil(ex[3] + 3)))
        mask[ey0:ey1, ex0:ex1] = False
    if segments:
        gy, gx = np.mgrid[0:H, 0:W]
        gx, gy = gx + 0.5, gy + 0.5
        for (ax, ay), (bx, by), half in segments:      # leader lines: not part of the pointer's own shape
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy or 1.0
            t = np.clip(((gx - ax) * dx + (gy - ay) * dy) / ll, 0, 1)
            dist = np.hypot(gx - (ax + t * dx), gy - (ay + t * dy))
            mask &= dist > half
    cx, cy = predicted_center
    win = window or radius * 2.2 + 30
    x0, y0, x1, y1 = int(max(0, cx - win)), int(max(0, cy - win)), int(min(W, cx + win)), int(min(H, cy + win))
    sub = np.zeros_like(mask)
    sub[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    if kind == 'box' and box is not None:
        yy, xx = np.nonzero(sub)
        if len(xx) < 10:
            return None
        px, py = xx + 0.5, yy + 0.5
        band = 6.0
        inside = (px > box[0] - band) & (px < box[2] + band) & (py > box[1] - band) & (py < box[3] + band)
        px, py = px[inside], py[inside]
        if len(px) < 10:
            return None
        # the outline's extent (a leader line leaving it is mostly outside the expected box and is cut off above)
        return {'center': [round(float((np.percentile(px, 0.5) + np.percentile(px, 99.5)) / 2), 2),
                           round(float((np.percentile(py, 0.5) + np.percentile(py, 99.5)) / 2), 2)],
                'pixels': len(px)}
    if kind in ('ring', 'magnify'):
        yy, xx = np.nonzero(sub)
        if len(xx) < 20:
            return None
        d = np.hypot(xx + 0.5 - cx, yy + 0.5 - cy)
        keep = np.abs(d - radius) < max(18.0, radius * 0.45)
        xx, yy = xx[keep] + 0.5, yy[keep] + 0.5
        if len(xx) < 20:
            return None
        band = None
        for _ in range(4):                     # fit, drop what isn't on the circle (a leader line), fit again
            A_ = np.column_stack([xx, yy, np.ones_like(xx)])
            bb = xx ** 2 + yy ** 2
            sol, *_ = np.linalg.lstsq(A_, bb, rcond=None)
            fx, fy = sol[0] / 2, sol[1] / 2
            fr = math.sqrt(max(0.0, sol[2] + fx * fx + fy * fy))
            res = np.hypot(xx - fx, yy - fy) - fr
            band = max(2.5, float(np.percentile(np.abs(res), 70)) * 1.6)
            keep = np.abs(res) < band
            if keep.all() or keep.sum() < 20:
                break
            xx, yy = xx[keep], yy[keep]
        return {'center': [round(float(fx), 2), round(float(fy), 2)], 'radius': round(fr, 2), 'pixels': len(xx)}
    yy, xx = np.nonzero(sub)
    if len(xx) < 10:
        return None
    if kind == 'arrow':
        return {'pixels': len(xx), 'points': np.column_stack([xx + 0.5, yy + 0.5])}
    return {'center': [round(float((xx.min() + xx.max() + 1) / 2), 2), round(float((yy.min() + yy.max() + 1) / 2), 2)],
            'pixels': len(xx)}


def arrow_tip(points, tail, tip):
    """The drawn arrow's tip: the mean of the coloured points furthest along the tail->tip direction."""
    import numpy as np
    d = np.array([tip[0] - tail[0], tip[1] - tail[1]], dtype=float)
    d /= (np.hypot(*d) or 1.0)
    proj = points @ d
    cut = np.percentile(proj, 99.0)
    far = points[proj >= cut]
    return [round(float(far[:, 0].mean()), 2), round(float(far[:, 1].mean()), 2)]


def pointer_check(params, lay, frames, i, before_png, after_png, color, found=None):
    """Measure the drawn pointer on frame i of a render (with vs without the annotation) and compare it with where
    it should be: ring/magnify centre, box centre, arrow tip. With `found` (the object located in the render from
    its pixels), also how far the pointer is from where the object really is."""
    W, H = params['size']
    s = H / 1080.0
    st = style_of(params)
    f = frames[i]
    kind = params['kind']
    point = params.get('point', False)
    radius = _ring_radius(f[3], st, s, point)
    margin = float(st['margin']) * min(W, H)
    tx = lay.get('text')
    label_size = (tx['block'][0] + 2 * tx['pad'][0], tx['block'][1] + 2 * tx['pad'][1]) if tx else None
    lbox = label_box_at(lay, i, frames, s, W, H, margin, label_size, kind, radius) if label_size else None
    exclude = [lbox] if lbox else []
    if lay.get('inset'):
        exclude.append(box_grow(tuple(lay['inset']['box']), float(st['stroke']) * s * 2))
    out = {}
    if kind in ('ring', 'magnify'):
        r = radius + (float(st['stroke']) * s) / 2 + 1.5 * s
        m = measure_pointer(before_png, after_png, 'ring', color, (f[1], f[2]), r, exclude=exclude)
        if m:
            out['pointer_drawn_at'] = m['center']
            out['pointer_vs_plan_px'] = round(math.hypot(m['center'][0] - f[1], m['center'][1] - f[2]), 2)
            if found:
                out['pointer_to_object_px'] = round(math.hypot(m['center'][0] - found['found'][0],
                                                               m['center'][1] - found['found'][1]), 2)
    elif kind == 'box':
        shape, geo = _box_outline(f, st, s, bool(params['geom'].get('rotated')))
        gb = geo if shape == 'rect' else (min(q[0] for q in geo), min(q[1] for q in geo), max(q[0] for q in geo),
                                          max(q[1] for q in geo))
        gb = box_grow(gb, float(st['stroke']) * s / 2 + 3 * s)
        segs = []
        if lbox:
            start = _arrow_tip(f, (f[1], f[2]), box_center(lbox), s, point, radius)
            segs.append((start, _closest_on_box(lbox, start), (4 * s + 6 * s) / 2 + 3))
        m = measure_pointer(before_png, after_png, 'box', color, (f[1], f[2]), max(box_w(gb), box_h(gb)) / 2 + 30,
                            exclude=exclude, box=gb, segments=segs)
        if m:
            out['pointer_drawn_at'] = m['center']
            out['pointer_vs_plan_px'] = round(math.hypot(m['center'][0] - f[1], m['center'][1] - f[2]), 2)
            if found:
                out['pointer_to_object_px'] = round(math.hypot(m['center'][0] - found['found'][0],
                                                               m['center'][1] - found['found'][1]), 2)
    elif kind == 'arrow':
        c = (f[1], f[2])
        if lbox:
            tip = _arrow_tip(f, c, box_center(lbox), s, point, radius)
            tail = _closest_on_box(box_grow(lbox, 6 * s), tip)
        else:
            ux, uy = lay['arrow']['dir']
            tip = _arrow_tip(f, c, (c[0] + ux * 1000, c[1] + uy * 1000), s, point, radius)
            tail = (tip[0] + ux * lay['arrow']['length'], tip[1] + uy * lay['arrow']['length'])
        L = math.hypot(tip[0] - tail[0], tip[1] - tail[1]) + 60 * s
        m = measure_pointer(before_png, after_png, 'arrow', color, tip, L / 2.2, window=L, exclude=exclude)
        if m:
            import numpy as np
            pts = m['points']
            got = arrow_tip(pts, tail, tip)
            # the drawn arrow's axis (principal direction of its coloured pixels): does it run through the object?
            mean = pts.mean(axis=0)
            _, _, vt = np.linalg.svd(pts - mean, full_matrices=False)
            axis = vt[0]

            def miss(pt):
                v = np.array(pt, dtype=float) - mean
                return float(abs(v[0] * axis[1] - v[1] * axis[0]))
            out['arrow_tip_drawn_at'] = got
            out['arrow_tip_planned'] = [round(tip[0], 2), round(tip[1], 2)]
            out['tip_vs_plan_px'] = round(math.hypot(got[0] - tip[0], got[1] - tip[1]), 2)
            out['pointer_vs_plan_px'] = round(miss((f[1], f[2])), 2)       # the planned centre off the drawn axis
            if found:
                out['pointer_to_object_px'] = round(miss(found['found']), 2)  # the real centre off the drawn axis
    return out
