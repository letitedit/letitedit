"""The 'slow' timing view: the AI's scrub. 1-3 s of the edit (or a video) at 10-15 frames per second, or every
frame, as a sheet of frames with what moves drawn on them:

  * white arrows: subject motion with the camera's own move removed (dense flow on a grid, drawn over
    `arrow_frames` frames so small moves show; only where it moves at least `arrow_min_px` px/frame);
  * a blue arrow from the centre: the camera's own move (its label: static, pan, tilt, zoom, handheld, whip);
  * a dashed box: the strongest moving region; thin green boxes: faces;
  * a red dot: where the eye likely is (attention), its ring = the spread;
  * the frame number and time; a red frame and 'CUT' on the first frame of a new shot, orange inside a
    transition; motion energy (px/frame) in the corner.

Numbers per shown frame come back too (energy, camera, direction, attention). Uses the same store (timing_signals)
as every other view.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

import letitedit.timing.timing_signals as ts
import letitedit.timing.timing_views as timing_views

SLOW = ts.CACHE / 'slow'
SLOW_DEFAULTS = {
    'rate': 12.0,             # frames per second shown (ignored when every is set)
    'every': None,            # show every n-th frame instead (1 = every frame)
    'max_frames': 45,         # at most this many frames per sheet
    'default_s': 2.0,         # length when only start_s is given
    'max_s': 3.0,             # longest range (s)
    'tile_long': 300,         # long side of a frame tile (px)
    'width': 1560,            # sheet width (px)
    'arrow_min_px': 0.6,      # arrows where residual motion is at least this (px/frame at the flow size)
    'arrow_frames': 4.0,      # arrows show the motion over this many frames
    'grid': 14,               # arrows on a grid with this many columns along the long side
}


def _residual(prev_g, g, st_feat):
    """Residual flow (camera removed) and the camera params between two grey frames at the flow size."""
    import cv2
    import letitedit.timing.timing_motion as tmo
    S = tmo._Static(g.shape[1], g.shape[0], st_feat)
    flow = tmo._dis(st_feat['flow_preset']).calc(prev_g, g, None)
    d = flow[S.sy, S.sx]
    try:
        M, inl = cv2.estimateAffinePartial2D(S.pts, S.pts + d, method=cv2.RANSAC,
                                             ransacReprojThreshold=float(st_feat['fit_px']), maxIters=300,
                                             confidence=0.99, refineIters=10)
    except cv2.error:
        M = None
    if M is None:
        med = np.median(d, axis=0)
        M = np.float32([[1, 0, med[0]], [0, 1, med[1]]])
    a, b, tx, ty = float(M[0, 0]), float(M[1, 0]), float(M[0, 2]), float(M[1, 2])
    camx = (a - 1.0) * S.X - b * S.Y + tx
    camy = b * S.X + (a - 1.0) * S.Y + ty
    return flow[..., 0] - camx, flow[..., 1] - camy, ((a - 1.0) * S.cx - b * S.cy + tx,
                                                     b * S.cx + (a - 1.0) * S.cy + ty, math.hypot(a, b))


def _arrow(d, x0, y0, x1, y1, col, width=2, head=6):
    d.line([x0, y0, x1, y1], fill=col, width=width)
    ang = math.atan2(y1 - y0, x1 - x0)
    if math.hypot(x1 - x0, y1 - y0) < 3:
        return
    for s in (-1, 1):
        a = ang + math.pi + s * 0.45
        d.line([x1, y1, x1 + head * math.cos(a), y1 + head * math.sin(a)], fill=col, width=width)


def _slow_range(cuts, st, fps, F, edit, start_s, end_s, warnings):
    """The frames to show: the range (centred on a cut when one is given, cut to max_s) and every n-th
    frame."""
    if cuts:
        c0 = cuts[0]
        cf = int(c0) if isinstance(c0, int) else ts.fr(float(c0.get('t', c0.get('f', 0) / fps)
                                                            if isinstance(c0, dict) else c0), fps)
        if isinstance(c0, dict) and 'f' in c0:
            cf = int(c0['f'])
        half = float(st['default_s']) / 2
        start_s, end_s = max(0.0, cf / fps - half), min(F / fps, cf / fps + half)
    if start_s is None:
        cs = edit.get('cuts') or []
        start_s = (cs[0]['t'] - float(st['default_s']) / 2) if cs else max(0.0, F / fps / 2 - 1.0)
        start_s = max(0.0, start_s)
        warnings.append(f'no start_s given: showing from {start_s:.2f} s')
    if end_s is None:
        end_s = float(start_s) + float(st['default_s'])
    if end_s - start_s > float(st['max_s']):
        warnings.append(f'range cut to {st["max_s"]} s (slow shows 1-3 s; use the map for longer stretches)')
        end_s = float(start_s) + float(st['max_s'])
    f_a, f_b = max(1, ts.fr(start_s, fps)), min(F, ts.fr(end_s, fps))
    every = int(st['every']) if st.get('every') else max(1, int(round(fps / float(st['rate']))))
    show = list(range(f_a, f_b, every))
    if len(show) > int(st['max_frames']):
        every = int(math.ceil((f_b - f_a) / float(st['max_frames'])))
        show = list(range(f_a, f_b, every))
        warnings.append(f'showing every {every}th frame to stay under {st["max_frames"]} frames')
    return f_a, f_b, every, show


def _slow_tile_marks(d, rec, f, x0, y0, tw, th, faces_by, is_cut, trans, fps):
    """One tile's marks: the strongest-motion box, faces, the attention dot, the cut or transition frame and
    the labels."""
    import letitedit.timing.rhythm_map as rhythm_map
    reg = rec['region']
    if reg:
        bx = [x0 + reg[0] * tw, y0 + reg[1] * th, x0 + reg[2] * tw, y0 + reg[3] * th]
        for i in range(int(bx[0]), int(bx[2]), 8):
            d.line([i, bx[1], min(i + 4, bx[2]), bx[1]], fill=(255, 235, 59), width=2)
            d.line([i, bx[3], min(i + 4, bx[2]), bx[3]], fill=(255, 235, 59), width=2)
        for i in range(int(bx[1]), int(bx[3]), 8):
            d.line([bx[0], i, bx[0], min(i + 4, bx[3])], fill=(255, 235, 59), width=2)
            d.line([bx[2], i, bx[2], min(i + 4, bx[3])], fill=(255, 235, 59), width=2)
    # faces: the nearest detection in this shot
    fb = None
    for dd in range(0, 4):
        for ff in (f - dd, f + dd):
            if ff in faces_by:
                fb = faces_by[ff]
                break
        if fb is not None:
            break
    for b in fb or []:
        d.rectangle([x0 + b[0] * tw, y0 + b[1] * th, x0 + b[2] * tw, y0 + b[3] * th], outline=(0, 200, 83),
                    width=1)
    ax_, ay_, sp_ = rec['attention']['x'], rec['attention']['y'], rec['attention']['spread']
    if ax_ is not None and ay_ is not None:
        px, py = x0 + ax_ * tw, y0 + ay_ * th
        rr = max(6.0, (sp_ or 0.1) * math.hypot(tw, th))
        d.ellipse([px - rr, py - rr, px + rr, py + rr], outline=(229, 57, 53), width=1)
        d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=(229, 57, 53), outline=(255, 255, 255))
    if is_cut:
        d.rectangle([x0 - 3, y0 - 3, x0 + tw + 3, y0 + th + 3], outline=(211, 47, 47), width=3)
        d.rectangle([x0, y0, x0 + 44, y0 + 18], fill=(211, 47, 47))
        d.text((x0 + 4, y0 + 2), 'CUT', fill=(255, 255, 255), font=rhythm_map.font(12, True))
    elif f in trans:
        d.rectangle([x0 - 3, y0 - 3, x0 + tw + 3, y0 + th + 3], outline=(245, 124, 0), width=3)
    e = rec['energy']
    etxt = f'{e:.1f}' if isinstance(e, (int, float)) else '-'
    d.rectangle([x0 + tw - 40, y0, x0 + tw, y0 + 16], fill=(0, 0, 0))
    d.text((x0 + tw - 37, y0 + 1), etxt, fill=(255, 255, 255), font=rhythm_map.font(12))
    lab = f'f{f}  {ts.clock(f / fps)[2:]}'
    d.text((x0, y0 + th + 2), lab, fill=(20, 20, 20), font=rhythm_map.font(12, True))
    cam_l = rec['camera_label'] or '-'
    dirn = rec['direction']
    sub = f'cam {cam_l}' + (f'  dir {dirn:.0f}' if isinstance(dirn, (int, float)) else '')
    d.text((x0, y0 + th + 17), sub, fill=(80, 80, 80), font=rhythm_map.font(11))


def slow_view(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief'):
    """1-3 s at 10-15 fps (or every frame) with motion arrows, the camera's move, faces and the attention dot."""
    from PIL import Image, ImageDraw
    import cv2
    import letitedit.footage.shots as shots
    import letitedit.timing.timing_motion as tmo
    import letitedit.timing.rhythm_map as rhythm_map
    t_start = time.time()
    options = dict(options or {})
    st = ts.lane_settings('slow', SLOW_DEFAULTS, {k: v for k, v in options.items() if k in SLOW_DEFAULTS})
    sig = ts.signals(source, start_s, end_s, lanes=['edit', 'frame_features', 'motion', 'attention', 'shots'],
                     refresh=bool(options.get('refresh')), settings=options.get('settings'))
    fps, F = float(sig['fps']), int(sig['frames'])
    warnings = list(sig.get('warnings') or [])
    # the range: start_s..end_s; a cut given (frame or time) centres the range on it
    edit = sig['lanes']['edit']
    f_a, f_b, every, show = _slow_range(cuts, st, fps, F, edit, start_s, end_s, warnings)
    # decode the range (with one frame before the first) from the analysed file
    video = sig['render'] or sig['source']
    info = shots.probe(video)
    feat_st = (sig['lanes'].get('frame_features') or {}).get('settings') or tmo.FEATURE_DEFAULTS
    W0, H0 = tmo._size_for(info['w'], info['h'], int(feat_st.get('analysis_px', 640)))
    fw, fh = tmo._size_for(W0, H0, int(feat_st.get('flow_px', 256)))
    offset = int((sig.get('range') or {}).get('f0') or 0) if sig['kind'] == 'project' else 0
    t0 = max(0.0, (f_a - 1 - offset) / fps - 0.05)
    frames = {}
    t_first = float(info.get('start_time') or 0.0)
    for t, Y, U, V in shots.decode(video, W0, H0, t0 if t0 > 0 else None, (f_b - f_a + 3) / fps + 0.1):
        f = int(round((t - (0.0 if t0 > 0 else t_first)) * fps)) + offset
        if f_a - 1 <= f < f_b and f not in frames:
            frames[f] = (Y.copy(), U.copy(), V.copy())
    mot = sig['lanes']['motion']
    att = sig['lanes']['attention']
    faces_by = {fc['f']: fc['boxes'] for fc in att.get('faces') or []}
    cut_frames = {int(c['f']): c for c in edit.get('cuts') or []}
    trans = set(mot.get('in_transition') or [])
    tl = int(st['tile_long'])
    tw, th = (tl, int(round(tl * H0 / W0))) if W0 >= H0 else (int(round(tl * W0 / H0)), tl)
    Wsheet = int(st['width'])
    cols = max(1, (Wsheet - 10) // (tw + 8))
    rows = int(math.ceil(len(show) / cols)) if show else 1
    lab_h = 34
    sheet = Image.new('RGB', (Wsheet, 46 + rows * (th + lab_h + 8) + 60), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    name = Path(sig.get('project') or sig['source']).name
    d.text((8, 6), f'{name}  slow {ts.clock(f_a / fps)} - {ts.clock(f_b / fps)}  frames {f_a}-{f_b - 1}, every '
                   f'{every} ({fps / every:.1f}/s)', fill=(20, 20, 20), font=rhythm_map.font(19, True))
    d.text((8, 28), 'white arrows: motion with the camera removed (x%g frames); blue arrow: the camera\'s move; dashed '
                    'box: strongest motion; green: faces; red dot: likely eye position' % float(st['arrow_frames']),
           fill=(90, 90, 90), font=rhythm_map.font(12))
    per = []
    sx_, sy_ = tw / float(fw), th / float(fh)
    for k, f in enumerate(show):
        r, c = divmod(k, cols)
        x0, y0 = 8 + c * (tw + 8), 46 + r * (th + lab_h + 8)
        fr_ = frames.get(f)
        if fr_ is None:
            d.rectangle([x0, y0, x0 + tw, y0 + th], outline=(200, 200, 200))
            d.text((x0 + 6, y0 + 6), f'frame {f} not decoded', fill=(150, 0, 0), font=rhythm_map.font(12))
            continue
        Y, U, V = fr_
        yuv = np.concatenate([Y.ravel(), U.ravel(), V.ravel()]).reshape(H0 * 3 // 2, W0)
        rgb = cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420)
        tile = Image.fromarray(cv2.resize(rgb, (tw, th), interpolation=cv2.INTER_AREA))
        sheet.paste(tile, (x0, y0))
        is_cut = f in cut_frames
        rec = {'f': f, 't': ts.tsec(f, fps), 'energy': mot['energy'][f], 'camera_label': mot['camera_label'][f],
               'camera': {k2: mot['camera'][k2][f] for k2 in ('dx', 'dy', 'zoom', 'rot')},
               'direction': mot['direction'][f], 'region': mot['region'][f],
               'attention': {'x': att['x'][f], 'y': att['y'][f], 'spread': att['spread'][f]}}
        if is_cut:
            rec['cut'] = cut_frames[f].get('kind')
        # motion arrows (not across a cut)
        prev = frames.get(f - 1)
        if prev is not None and not is_cut:
            pg = cv2.resize(prev[0], (fw, fh), interpolation=cv2.INTER_AREA)
            g = cv2.resize(Y, (fw, fh), interpolation=cv2.INTER_AREA)
            rx, ry, cam = _residual(pg, g, feat_st)
            n = int(st['grid'])
            step = max(4, max(fw, fh) // n)
            k_ = float(st['arrow_frames'])
            for yy in range(step // 2, fh, step):
                for xx in range(step // 2, fw, step):
                    vx = float(rx[max(0, yy - 2):yy + 3, max(0, xx - 2):xx + 3].mean())
                    vy = float(ry[max(0, yy - 2):yy + 3, max(0, xx - 2):xx + 3].mean())
                    if math.hypot(vx, vy) < float(st['arrow_min_px']):
                        continue
                    ax, ay = x0 + xx * sx_, y0 + yy * sy_
                    _arrow(d, ax, ay, ax + vx * k_ * sx_, ay + vy * k_ * sy_, (0, 0, 0), width=3, head=6)
                    _arrow(d, ax, ay, ax + vx * k_ * sx_, ay + vy * k_ * sy_, (255, 255, 255), width=1, head=5)
            cx, cy = x0 + tw / 2, y0 + th / 2
            if rec['camera_label'] not in (None, 'static'):
                _arrow(d, cx, cy, cx + cam[0] * k_ * sx_ * 2, cy + cam[1] * k_ * sy_ * 2, (30, 136, 229), width=3,
                       head=8)
        _slow_tile_marks(d, rec, f, x0, y0, tw, th, faces_by, is_cut, trans, fps)
        per.append(rec)
    out_dir = SLOW / timing_views.result_id('slow', sig['key'], f_a, f_b, every)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f'slow-{f_a}-{f_b}.jpg'
    sheet.save(p, 'JPEG', quality=90)
    res = timing_views.common_fields(source=str(source), sig=sig, view='slow', inputs=[f_a, f_b, every],
                                     warnings=warnings, preview_artifacts=[{'kind': 'slow_sheet', 'path': str(p)}])
    res.update({'view': 'slow', 'images': [str(p)], 'range': {'f0': f_a, 'f1': f_b, 't0': ts.tsec(f_a, fps),
                                                                't1': ts.tsec(f_b, fps)},
                'every': every, 'shown_fps': round(fps / every, 2), 'frames': per,
                'cuts_in_range': [c for f, c in sorted(cut_frames.items()) if f_a <= f < f_b],
                'options_used': {k: st[k] for k in SLOW_DEFAULTS},
                'units': {'energy': 'px/frame at the flow size (camera removed)', 'direction': 'degrees, 0 = right, '
                          '90 = up', 'attention': '0-1 of the picture; spread = share of the diagonal'},
                'unsupported': ['arrows are optical flow, not tracked objects: they can be wrong in blur, on '
                                'repeating texture or in very dark frames'],
                'seconds': round(time.time() - t_start, 2)})
    if detail != 'full':
        res['frames'] = [{k: v for k, v in r.items() if k in ('f', 't', 'energy', 'camera_label', 'direction', 'cut')}
                         for r in per]
    return res


timing_views.register_view('slow', slow_view, "the AI's scrub: 1-3 s at 10-15 frames per second (options.every = 1 "
                                               'for every frame) with motion arrows (camera removed), the camera\'s '
                                               'move, the strongest moving region, faces and the likely eye position; '
                                               'cuts=[frame] centres it on a cut')
