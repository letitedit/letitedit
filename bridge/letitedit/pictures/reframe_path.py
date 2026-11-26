"""The crop path solved, and its keyframes (what renders).

Part of `reframe` (letitedit/pictures/reframe.py), which imports every name here back,
so `reframe.X` is the same object it always was.
"""
from __future__ import annotations
import numpy as np
from letitedit.pictures.reframe_geometry import (  # noqa: E402
    KEEP_OUT_WEIGHT, MOTION, WEIGHT, _LP, _diff_rows, _padded, box_h, box_w, fit_analysis, max_window, union
)


# ============================================================================ the path

def _path_motion_costs(breaks, cx, cy, dt, hh, hw, lp, n, s, settings, smax, smin, src_h, src_w, wh, ww):
    # the crop stays inside the picture: cx - hw s >= 0, cx + hw s <= W (same for y)
    i = np.arange(n)
    for c, h, lim in ((cx, hw, src_w), (cy, hh, src_h)):
        lp.rows(np.stack([c[i], s[i]], 1), np.tile([-1.0, h], (n, 1)), 0.0)
        lp.rows(np.stack([c[i], s[i]], 1), np.tile([1.0, h], (n, 1)), lim)
    calm = float(settings['calm'])
    brk = set(int(b) for b in breaks)
    # the crop never moves faster than max_speed crop widths (heights) per second, except across a cut
    vmax = float(settings['max_speed'])
    if vmax > 0:
        for var, size in ((cx, ww), (cy, wh)):
            cols, vals = _diff_rows(var, 1, brk)
            lp.rows(cols, vals, vmax * size * dt)
            lp.rows(cols, -vals, vmax * size * dt)
        if abs(smax - smin) > 1e-9:
            cols, vals = _diff_rows(s, 1, brk)
            lp.rows(cols, vals, float(settings['max_zoom_rate']) * dt)
            lp.rows(cols, -vals, float(settings['max_zoom_rate']) * dt)
    # ...and changes speed no faster than max_accel crop widths (heights) per second per second: no instant reversals
    amax = float(settings['max_accel'])
    if amax > 0:
        for var, size in ((cx, ww), (cy, wh)):
            cols, vals = _diff_rows(var, 2, brk)
            lp.rows(cols, vals, amax * size * dt * dt)
            lp.rows(cols, -vals, amax * size * dt * dt)
    for var, scale in ((cx, ww), (cy, wh), (s, 1.0)):
        if var is s and abs(smax - smin) < 1e-9:
            continue
        for order, w in ((1, MOTION['w1']), (2, MOTION['w2'] / dt), (3, MOTION['w3'] / dt ** 2)):
            cols, vals = _diff_rows(var, order, brk)
            lp.abs_cost(cols, vals, calm * w / scale)


def _path_subject_costs(blips, cx, cy, dt, hh, hw, keep_out, kept, lp, n, s, safe, settings, src_h, src_w,
        subjects, wh, ww):
    # where the subjects are: required (kept) > preferred > optional; the composition target
    mx = my = settings['margin'] * min(ww, wh)
    full = (0.0, 0.0, 1.0, 1.0)
    rejoin = max(1, int(round(float(settings['rejoin_s']) / dt)))
    look = int(round(float(settings['lookahead_s']) / dt))
    px = np.full(n, np.nan)
    py = np.full(n, np.nan)
    pz = np.full(n, np.nan)
    focus_w = np.zeros(n)
    boxes_for_target = [[] for _ in range(n)]
    for subj in subjects:
        pr = subj['priority']
        if pr == 'ignore':
            continue
        B = np.asarray(subj['box'], float)
        present = ~np.any(np.isnan(B), axis=1)
        if not present.any():
            continue
        if pr == 'required' and look > 0:
            B = _dilate_time(B, present, look)
        head = settings['headroom'] * wh if subj['kind'] == 'face' else 0.0
        # weights per sample
        w = np.zeros(n)
        if pr == 'required':
            ok = np.array([subj['id'] in kept[k] for k in range(n)])
            blip = blips.get(subj['id'], np.zeros(n, bool))
            ramp = _rejoin_ramp(ok, rejoin, blip)
            w = np.where(ok, WEIGHT['preferred'] + (WEIGHT['required'] - WEIGHT['preferred']) * ramp,
                         np.where(blip, WEIGHT['preferred'], WEIGHT['dropped']))
        else:
            w = np.full(n, WEIGHT[pr])
        w = np.where(present, w, 0.0)
        ks = np.nonzero(w > 0)[0]
        if len(ks):
            P = np.array([_padded(B[k], pr, src_w, src_h, mx, my, head) for k in ks])
            # how far each padded edge sits outside the bare box: entering that margin is cheap (the crop may
            # breathe into it for a calmer path), crossing the box itself costs the full weight
            Bk = B[ks]
            give = np.column_stack([Bk[:, 0] - P[:, 0], Bk[:, 1] - P[:, 1], P[:, 2] - Bk[:, 2], P[:, 3] - Bk[:, 3]])
            give = np.clip(give, 0.0, None)
            levels = [(full, 1.0)]
            if safe != full:
                levels.append((safe, 0.5))
            nk = len(ks)
            for (fx0, fy0, fx1, fy1), share in levels:
                for c, h, lo_f, hi_f, j0, j1 in ((cx, hw, fx0, fx1, 0, 2), (cy, hh, fy0, fy1, 1, 3)):
                    # crop edge (with its covered band) left of / above the box: c + h s (2 f0 - 1) <= b0 + e
                    cost = share * w[ks] * dt / (2 * h)
                    for sign, f, j in ((1.0, lo_f, j0), (-1.0, hi_f, j1)):
                        e_m = lp.var(nk, cost=0.04 * cost, lo=0.0, hi=give[:, j])
                        e = lp.var(nk, cost=cost, lo=0.0)
                        lp.rows(np.stack([c[ks], s[ks], e_m, e], 1),
                                np.column_stack([np.full(nk, sign), np.full(nk, sign * h * (2 * f - 1)),
                                                 -np.ones(nk), -np.ones(nk)]),
                                sign * P[:, j])
            if keep_out is not None and pr == 'required':
                kb = keep_out['band']
                kmask = np.asarray(keep_out['samples'], bool)[ks]
                kk = ks[kmask]
                if len(kk):
                    Pk = P[kmask]
                    for c, h, lo_f, hi_f, j0, j1 in ((cx, hw, kb[0], kb[2], 0, 2), (cy, hh, kb[1], kb[3], 1, 3)):
                        if lo_f > 0:
                            e = lp.var(len(kk), cost=KEEP_OUT_WEIGHT * dt / (2 * h), lo=0.0)
                            lp.rows(np.stack([c[kk], s[kk], e], 1),
                                    np.column_stack([np.ones(len(kk)), np.full(len(kk), h * (2 * lo_f - 1)),
                                                     -np.ones(len(kk))]), Pk[:, j0])
                        if hi_f < 1:
                            e2 = lp.var(len(kk), cost=KEEP_OUT_WEIGHT * dt / (2 * h), lo=0.0)
                            lp.rows(np.stack([c[kk], s[kk], e2], 1),
                                    np.column_stack([-np.ones(len(kk)), np.full(len(kk), -h * (2 * hi_f - 1)),
                                                     -np.ones(len(kk))]), -Pk[:, j1])
        # composition: kept required and preferred subjects pull the centre
        for k in np.nonzero(present)[0]:
            if pr == 'required' and subj['id'] not in kept[k]:
                continue
            if pr in ('required', 'preferred'):
                boxes_for_target[k].append((subj['kind'], B[k], 1.0 if pr == 'required' else 0.5))
    return px, py, pz, boxes_for_target, focus_w


def _path_composition_costs(boxes_for_target, cx, cy, dt, focus_w, lp, n, s, settings, smax, smin, src_h,
        src_w, wh, ww, px, py, pz):
    last = None
    for k in range(n):
        items = boxes_for_target[k]
        if not items:
            continue
        u = union([b for _, b, _ in items])
        x, y = (u[0] + u[2]) / 2, (u[1] + u[3]) / 2
        if len(items) == 1 and items[0][0] == 'face':
            y = (u[1] + u[3]) / 2 + 0.1 * wh * smax       # a face sits a little above the middle
        px[k], py[k] = x, y
        need = max(box_w(u) / (ww * 0.72), box_h(u) / (wh * 0.72))
        pz[k] = min(smax, max(smin, need))
        focus_w[k] = 1.0
        last = k
    if last is not None:
        px, py, pz = _fill_hold(px), _fill_hold(py), _fill_hold(pz)
    else:
        px[:], py[:], pz[:] = src_w / 2, src_h / 2, smax
    w0 = MOTION['w1'] / max(0.2, float(settings['recentre_s']))
    for var, tgt, scale in ((cx, px, ww), (cy, py, wh)):
        u = lp.var(n, cost=w0 * dt / scale, lo=0.0)
        lp.rows(np.stack([var, u], 1), np.tile([1.0, -1.0], (n, 1)), tgt)
        lp.rows(np.stack([var, u], 1), np.tile([-1.0, -1.0], (n, 1)), -tgt)
    if abs(smax - smin) > 1e-9:
        # zoom: as wide as allowed unless the subjects would fill a tighter crop (then towards that)
        u = lp.var(n, cost=MOTION['zoom_pref'] * dt, lo=0.0)
        lp.rows(np.stack([s, u], 1), np.tile([1.0, -1.0], (n, 1)), pz)
        lp.rows(np.stack([s, u], 1), np.tile([-1.0, -1.0], (n, 1)), -pz)
    return px, py, pz


def solve_path(times, subjects, src_size, out_size, settings, breaks=(), safe=(0.0, 0.0, 1.0, 1.0),
               keep_out=None, panel=None):
    """The crop path for samples `times` (seconds, evenly spaced): {'cx', 'cy', 's' (crop size / largest crop),
    'kept', 'left', 'left_safe', 'ww', 'wh', 'status'}. subjects: [{'id', 'kind', 'priority', 'rank', 'box': (n, 4)
    array with NaN rows where absent}]. breaks: sample indices where a cut starts (no smoothness across it).
    keep_out: optional {'band': (fx0, fy0, fx1, fy1), 'samples': bool array} - extra uncovered-area band for the
    required subjects at those samples (an inset's corner). panel: (w, h) of the output region the crop fills
    (default the whole output frame)."""
    src_w, src_h = src_size
    out_w, out_h = panel if panel else out_size
    n = len(times)
    dt = float(times[1] - times[0]) if n > 1 else 1.0
    ww, wh = max_window(src_w, src_h, out_w, out_h)
    zmin, zmax = settings['zoom']
    smin, smax = 1.0 / zmax, 1.0 / zmin
    hw, hh = ww / 2.0, wh / 2.0
    kept, left, left_safe = fit_analysis(subjects, n, src_w, src_h, ww * smax, wh * smax, safe, settings)
    n_min = max(1, int(round(float(settings['min_span_s']) / dt)))
    blips = {}
    for subj in subjects:
        if subj['priority'] != 'required':
            continue
        present = ~np.any(np.isnan(np.asarray(subj['box'], float)), axis=1)
        ok = np.array([subj['id'] in kept[k] for k in range(n)])
        ok2, blip = debounce(ok, present, n_min)
        for k in np.nonzero(ok & ~ok2)[0]:
            kept[k].discard(subj['id'])
            left[k].add(subj['id'])
        blips[subj['id']] = blip
    lp = _LP()
    cx = lp.var(n, lo=hw * smin, hi=src_w - hw * smin)
    cy = lp.var(n, lo=hh * smin, hi=src_h - hh * smin)
    s = lp.var(n, lo=smin, hi=smax)
    _path_motion_costs(breaks, cx, cy, dt, hh, hw, lp, n, s, settings, smax, smin, src_h, src_w, wh, ww)
    px, py, pz, boxes_for_target, focus_w = _path_subject_costs(blips, cx, cy, dt, hh, hw, keep_out, kept, lp,
        n, s, safe, settings, src_h, src_w, subjects, wh, ww)
    px, py, pz = _path_composition_costs(boxes_for_target, cx, cy, dt, focus_w, lp, n, s, settings, smax,
        smin, src_h, src_w, wh, ww, px, py, pz)
    try:
        x, res = lp.solve()
    except RuntimeError:
        if float(settings.get('max_accel') or 0) <= 0 and float(settings.get('max_speed') or 0) <= 0:
            raise
        # the motion limits left no way through (a zoom range can do that): solve again without them, and say so
        loose = dict(settings, max_accel=0.0, max_speed=0.0)
        out = solve_path(times, subjects, src_size, out_size, loose, breaks, safe, keep_out, panel)
        out['status'] = 'solved without the speed/acceleration limits (no path met them): ' + str(out['status'])
        return out
    return {'cx': x[cx], 'cy': x[cy], 's': x[s], 'kept': kept, 'left': left, 'left_safe': left_safe,
            'ww': ww, 'wh': wh, 'status': res.message, 'variables': lp.n, 'constraints': lp.m,
            'target': np.column_stack([px, py])}


def _dilate_time(B, present, k):
    """Each box widened to also hold where the subject is up to k samples before and after (moving subjects are
    kept with room ahead of them)."""
    n = len(B)
    out = B.copy()
    for i in np.nonzero(present)[0]:
        a, b = max(0, i - k), min(n, i + k + 1)
        seg = B[a:b][present[a:b]]
        out[i] = [seg[:, 0].min(), seg[:, 1].min(), seg[:, 2].max(), seg[:, 3].max()]
    return out


def _runs(a):
    """[(value, start, end)] runs of equal values in a 1-D sequence (end exclusive)."""
    out = []
    for i, v in enumerate(a):
        if out and out[-1][0] == v:
            out[-1][2] = i + 1
        else:
            out.append([v, i, i + 1])
    return [tuple(r) for r in out]


def debounce(ok, present, n_min):
    """A required subject's fit sequence made calm: stretches where it fits that are shorter than n_min samples
    between stretches where it doesn't count as not fitting (dropping a subject that could fit is always
    possible); stretches shorter than n_min where it doesn't fit, between stretches where it does, are 'blips'
    (it is held at the preferred weight there and its comeback ramp doesn't restart). Returns (kept, blip)."""
    ok = np.asarray(ok, bool).copy()
    st = np.where(~np.asarray(present, bool), 2, ok.astype(int))      # 2 = absent: neutral for both rules
    runs = _runs(st.tolist())
    for j, (v, a, b) in enumerate(runs):
        if v == 1 and b - a < n_min and 0 < j < len(runs) - 1:
            prev_v = next((r[0] for r in reversed(runs[:j]) if r[0] != 2), None)
            next_v = next((r[0] for r in runs[j + 1:] if r[0] != 2), None)
            if prev_v == 0 and next_v == 0:
                ok[a:b] = False
    blip = np.zeros(len(ok), bool)
    st = np.where(~np.asarray(present, bool), 2, ok.astype(int))
    runs = _runs(st.tolist())
    for j, (v, a, b) in enumerate(runs):
        if v == 0 and b - a < n_min:
            prev_v = next((r[0] for r in reversed(runs[:j]) if r[0] != 2), None)
            next_v = next((r[0] for r in runs[j + 1:] if r[0] != 2), None)
            if prev_v == 1 and next_v == 1:
                blip[a:b] = True
    return ok, blip


def _rejoin_ramp(ok, n_ramp, blip=None):
    """1 where a subject has been kept for n_ramp samples or more, rising from 0 after each stretch it was left
    out (so it is brought back in by a smooth move instead of a jump); the clip's own start counts as kept, and a
    blip doesn't restart the ramp."""
    out = np.zeros(len(ok))
    run = n_ramp
    for k, v in enumerate(ok):
        if v:
            run += 1
            out[k] = min(1.0, run / n_ramp)
        elif blip is not None and blip[k]:
            out[k] = 0.0
        else:
            run = 0
    return out


def _fill_hold(a):
    """NaNs filled with the last value before them (the first value before any)."""
    a = a.copy()
    idx = np.nonzero(~np.isnan(a))[0]
    if not len(idx):
        return a
    a[:idx[0]] = a[idx[0]]
    for i in range(idx[0] + 1, len(a)):
        if np.isnan(a[i]):
            a[i] = a[i - 1]
    return a


# ============================================================================ keyframes (what renders)

def _rect_text(r):
    return ' '.join(f'{round(float(v), 1) + 0.0:g}' for v in r[:4]) + ' 1'


def eval_keys(keys, fps, n_frames):
    """Per-frame rects [x, y, w, h] of size_position keys [[t, 'x y w h 1', ease], ...] as the engine computes
    them (annotate.anim_values: MLT's keyframe arithmetic, eases included)."""
    import letitedit.pictures.annotate as annotate
    import letitedit.timeline.edit_effects as ee
    if isinstance(keys, str):
        r = annotate.parse_rect(keys, 1, 1)
        return np.tile(np.asarray(r[:4], float), (n_frames, 1))
    text = ee.anim([[k[0], k[1]] + list(k[2:3]) for k in keys], fps)

    def parse(v):
        return tuple(annotate.parse_rect(v, 1, 1)[:4])
    return np.array([annotate.anim_values(text, f, fps, n_frames, parse) for f in range(n_frames)], float)


def _edge_dev(a, b):
    """Largest movement of any crop edge (output pixels) between two rects (x, y, w, h) - zoom moves the far
    edges by the size change."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    return np.max(np.abs(np.stack([a[..., 0] - b[..., 0], a[..., 1] - b[..., 1],
                                   (a[..., 0] + a[..., 2]) - (b[..., 0] + b[..., 2]),
                                   (a[..., 1] + a[..., 3]) - (b[..., 1] + b[..., 3])], -1)), axis=-1)


def keys_from_path(times, rects, fps, n_frames, ease='smooth', tol=1.5, key_hz=5.0, max_rounds=40):
    """Size/Position keys for a path given at evenly spaced sample times (clip seconds). Where the path moves,
    keys sit at a steady rate (key_hz) so the engine's Catmull-Rom 'smooth' interpolation keeps the speed
    continuous; a hold becomes its two ends plus one steady-spaced key inside each end (no overshoot into the
    hold). Keys are snapped to frames and checked frame by frame with the engine's arithmetic; a key is added
    where the rendered path strays more than 2 x tol output pixels. Returns (keys | rect text when the path
    never moves, per-frame rects as rendered, max deviation px)."""
    times = np.asarray(times, float)
    rects = np.asarray(rects, float)
    ft = np.arange(n_frames) / fps
    want = np.column_stack([np.interp(ft, times, rects[:, j]) for j in range(4)])
    if np.max(_edge_dev(rects, rects[0])) < 0.5:
        r = _rect_text(rects[0])
        return r, np.tile(np.round(rects[0], 1), (n_frames, 1)), 0.0
    m = len(times)
    dt = float(times[1] - times[0]) if m > 1 else 1.0
    stride = max(1, int(round(1.0 / (key_hz * dt))))
    step_moves = np.r_[_edge_dev(rects[1:], rects[:-1]) > 0.25, False]       # sample k moves on to k + 1
    moving = step_moves | np.r_[False, step_moves[:-1]]
    idx = {0, m - 1}
    k = 0
    while k < m:
        if moving[k]:
            a = k
            while k < m and moving[k]:
                k += 1
            b = k - 1                                       # a moving stretch [a, b]
            idx.update(range(a, b + 1, stride))
            idx.add(b)
            for j in (a - stride, a - 2 * stride, b + stride, b + 2 * stride):
                if 0 <= j < m:
                    idx.add(j)                              # steady spacing into the holds on both sides
        else:
            k += 1
    frames = sorted({min(n_frames - 1, int(round(times[k] * fps))) for k in idx} | {0, n_frames - 1})
    dev = 0.0
    rendered = None
    keys = None
    for _ in range(max_rounds):
        keys = [[round(f / fps, 4), _rect_text(want[f]), ease] for f in frames]
        rendered = eval_keys(keys, fps, n_frames)
        d = _edge_dev(rendered, want)
        worst = int(np.argmax(d))
        dev = float(d[worst])
        if dev <= 2 * tol or worst in frames:
            break
        frames = sorted(set(frames) | {worst})
    return keys, rendered, dev
