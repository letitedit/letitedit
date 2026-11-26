"""Annotations that point at something in a clip: a ring, arrow, box, label or magnified detail, placed by the
software from coordinates in the clip's OWN source picture.

The person (or the LLM) names the object in the source the way every frame tool shows it - a box or point in the
upright source picture, at a source time - and this module does the rest in code:

  1. finds the clip on the timeline and reads its picture chain from the project file (the MLT XML is the truth):
     the file's orientation flag (and an editor rotation override), Crop: Source, Size/Position/Rotate (static or
     keyframed, fill/fit/distort, alignment, rotation), mirror/flip, and the fit into the project frame;
  2. keeps that chain as data (`clip_chain`) and evaluates it per timeline frame (`chain_at`) into a 3x3 matrix from
     source pixels to output pixels, following the engine's own arithmetic (MLT filter_crop, transition_affine,
     filter_resize), so the pointer lands where the export puts the object;
  3. maps the source/timeline time range through the clip's trims and timeline position (speed changes, reversed
     clips and retiming effects are refused, never guessed);
  4. follows the object with the existing tracker (av_tools.track, VitTrack) when asked, and hides the pointer
     wherever tracking is lost (the lost ranges are returned);
  5. lays the label (or the detail inset) out inside the frame and away from protected regions (captions, other
     graphics, platform covered areas, given boxes) with `place_box`, reusable by other layout tools;
  6. draws it through the existing graphics system (graphics.render, a 'custom' recipe whose code calls `draw`
     below), so the clip is an ordinary editable graphic: its recipe stores the text and style and the source
     relationship (clip id, file, source range, target), and `refresh` re-solves it after the clip is trimmed, moved,
     cropped or zoomed;
  7. returns a proposal (the existing edit vocabulary for letitedit_timeline_apply), rendered preview frames (melt, the
     export engine), a measured check of where the object really is in the rendered frame, warnings and the
     unsupported cases; `apply_plan` applies a proposal to the project file (one undo step, history kept).

Coordinates: continuous pixel coordinates (a pixel's centre is at +0.5); boxes are (x0, y0, x1, y1).
Times: source seconds (the clip's file), timeline seconds and timeline frames are kept apart by name.

The code is in parts, each imported back here: annotate_geometry (settings, boxes, MLT values, media, the clip),
annotate_chain (the picture chain, the target, times), annotate_screen (what else is on screen, layout), annotate_draw
(the drawing the graphics sandbox runs as annotate.draw) and annotate_check. This file keeps WORK and the tracking (the
tests point WORK at their own folder), the plan and the existing annotations.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)


# ---- this module's parts: every name in them imported back, so each is the same object as before
# the settings and the shared geometry: boxes and matrices, MLT values, media orientation and size, the clip on the timeline
from letitedit.pictures.annotate_geometry import (  # noqa: E402,F401
    _SAI_ROOT, SCHEMA, ENGINE, DEFAULT_TRACK, KINDS, APP, FFPROBE, FFMPEG, CACHE, NO_WINDOW, CODE, MARK,
    Unsupported, box_w, box_h, box_area, box_center, box_inter, overlap_area, box_grow, box_union, box_inside,
    box_distance, mat_mul, mat_inv, mat_apply, mat_translate, mat_scale, mat_rot, IDENTITY, map_box, mat_scale_of,
    mat_rotation_of, _NUM, _KEY, EASE_OF, mlt_time_frames, parse_rect, parse_keys, _ease, _catmull, anim_values,
    anim_number, _media, fingerprint, media_info, _norm_angle, rotate_map, _props, _frames_attr, load_doc,
    clip_places, find_clip
)
# the clip's picture chain as data, the target in source pixels, and source times as timeline frames
from letitedit.pictures.annotate_chain import (  # noqa: E402,F401
    MODELED, RETIMING, GEOMETRY_UNSUPPORTED, GEOMETRY_UNSUPPORTED_PREFIX, NEUTRAL, _effect_name, clip_chain,
    _crop_values, _rint, _align, _affine_matrix, _fit_matrix, chain_at, point_in_quad, target_box, clip_span,
    src_time, timeline_frame, resolve_range
)
# what else is on screen, and the layout of labels and insets
from letitedit.pictures.annotate_screen import (  # noqa: E402,F401
    _alpha, _has_alpha, covered_spans, covers_at, protected_regions, SIDES, _beside, _slide_inside, place_box,
    STYLE, style_of, expand_geom, vis_alpha, _ring_radius, _edge_toward, _closest_on_box, solve_layout, _fit_text,
    _arrow_tip, label_box_at
)
# the drawing, which runs in the graphics sandbox
from letitedit.pictures.annotate_draw import (  # noqa: E402,F401
    _STATE, _SS, _ease_out_back, _ease_out, _params_key, _setup, _source_picture, draw, _draw_annotation,
    _box_outline, _matrix_at
)
# the checks against the export engine
from letitedit.pictures.annotate_check import (  # noqa: E402,F401
    _gray, locate_target, verdict, measure_pointer, arrow_tip, pointer_check
)


import copy
import hashlib
import json
import math
import os
import re
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
WORK = CACHE / 'annotate'


# ============================================================================ tracking (av_tools.track + a backward pass)

TRACK_DEFAULTS = {'min_score': 0.35, 'max_jump': 0.12, 'max_grow': 3.0, 'recover_frames': 4, 'smooth': 5,
                  'analysis_px': 640, 'hold_s': 0.5}


def _track_backward(file, t0, at, frac_box, fps, px):
    """Follow the box from `at` back to t0 (VitTrack, the model av_tools.track uses): rows [t, x0, y0, x1, y1,
    score, ok] in display fractions, oldest first."""
    import cv2
    import numpy as np

    import letitedit.sound.av_tools as av_tools
    import letitedit.server.core_tools as core_tools
    info = core_tools.probe(file)
    W, H = int(info['width']), int(info['height'])
    k = px / max(W, H)
    aw, ah = max(2, int(round(W * k / 2)) * 2), max(2, int(round(H * k / 2)) * 2)
    frames = list(av_tools._frames(file, t0, at - t0 + 0.5 / fps, fps, aw, ah))
    if not frames:
        return []
    times = [t0 + i / fps for i in range(len(frames))]
    x0, y0, x1, y1 = frac_box
    params = cv2.TrackerVit_Params()
    params.net = str(av_tools.VITTRACK)
    tr = cv2.TrackerVit.create(params)
    tr.init(frames[-1], (int(round(x0 * aw)), int(round(y0 * ah)), max(4, int(round((x1 - x0) * aw))),
                         max(4, int(round((y1 - y0) * ah)))))
    rows = [[times[-1], x0, y0, x1, y1, 1.0, True]]
    for i in range(len(frames) - 2, -1, -1):
        ok, b = tr.update(frames[i])
        score = float(tr.getTrackingScore())
        bx, by, bw, bh = [float(v) for v in b]
        if ok and bw > 0 and bh > 0:
            rows.append([times[i], bx / aw, by / ah, (bx + bw) / aw, (by + bh) / ah, score, True])
        else:
            rows.append([times[i], *rows[-1][1:5], score, False])
    rows.reverse()
    del np
    return rows


def track_target(file, t0, t1, at, box_px, info, settings=None, out_dir=None):
    """Follow the target box (display pixels at source time `at`) through source [t0, t1] with the existing tracker.
    Returns {'rows': [[t, x0, y0, x1, y1, score, ok]] (display pixels, every analysed frame), 'lost': [[a, b]] (source
    seconds), 'sheet', 'json', 'settings'}. A frame counts as lost when the tracker says so, its score is under
    min_score, the box jumps more than max_jump of the picture between frames, or grows/shrinks over max_grow; after
    a loss it must hold recover_frames good frames in a row near where it was lost before it counts again."""
    import letitedit.sound.av_tools as av_tools
    s = {**TRACK_DEFAULTS, **(settings or {})}
    dw, dh = info['display']
    fps = min(float(info.get('fps') or 30.0) or 30.0, 30.0)
    frac = (box_px[0] / dw, box_px[1] / dh, box_px[2] / dw, box_px[3] / dh)
    if (frac[2] - frac[0]) * max(dw, dh) * s['analysis_px'] / max(dw, dh) < 4 or \
            (frac[3] - frac[1]) * s['analysis_px'] < 4:
        raise ValueError('the target box is too small to track (make it at least ~1% of the picture)')
    folder = Path(out_dir or WORK / 'track')
    folder.mkdir(parents=True, exist_ok=True)
    rows, sheet, js = [], None, None
    if t1 > at + 0.5 / fps:
        res = av_tools.track(file, at, min(t1 + 1.0 / fps, info['duration'] or t1 + 1), list(frac), out_dir=folder,
                             analysis_fps=fps, analysis_px=s['analysis_px'], sheet_frames=8)
        lost_t = {round(float(x), 3) for x in res.get('lost') or []}
        data = json.loads(Path(res['json']).read_text(encoding='utf-8-sig'))
        for r in data['frames']:
            rows.append([float(r[0]), *[float(v) for v in r[1:5]], float(r[5]), round(float(r[0]), 3) not in lost_t])
        sheet, js = res.get('sheet'), res.get('json')
    if at > t0 + 0.5 / fps:
        back = _track_backward(file, t0, at, frac, fps, s['analysis_px'])
        rows = [r for r in back if r[0] < (rows[0][0] if rows else at + 1) - 1e-6] + rows
    if not rows:
        rows = [[at, *frac, 1.0, True]]
    # loss rules on top of the tracker's own
    i0 = min(range(len(rows)), key=lambda i: abs(rows[i][0] - at))
    area0 = max(1e-9, (frac[2] - frac[0]) * (frac[3] - frac[1]))

    def judge(order):
        prev, lost_since, good_run, anchor = None, None, 0, None
        for i in order:
            r = rows[i]
            c = ((r[1] + r[3]) / 2, (r[2] + r[4]) / 2)
            area = max(1e-9, (r[3] - r[1]) * (r[4] - r[2]))
            ok = bool(r[6]) and r[5] >= s['min_score'] and 1 / s['max_grow'] <= area / area0 <= s['max_grow']
            if ok and prev is not None and math.hypot(c[0] - prev[0], c[1] - prev[1]) > s['max_jump']:
                ok = False
            if lost_since is not None:
                # back only after recover_frames good frames in a row near where it was lost
                near = anchor is None or math.hypot(c[0] - anchor[0], c[1] - anchor[1]) <= s['max_jump'] * 2
                good_run = good_run + 1 if ok and near else 0
                if good_run >= s['recover_frames']:
                    lost_since = None
                else:
                    ok = False
            elif not ok:
                lost_since, good_run, anchor = i, 0, prev
            r[6] = ok
            if ok:
                prev = c
    judge(range(i0, len(rows)))
    judge(range(i0, -1, -1))
    # smooth good stretches (centred moving average)
    k = int(s['smooth'])
    if k > 1:
        sm = [list(r) for r in rows]
        for i, r in enumerate(rows):
            if not r[6]:
                continue
            seg = [rows[j] for j in range(max(0, i - k // 2), min(len(rows), i + k // 2 + 1)) if rows[j][6]]
            for c in range(1, 5):
                sm[i][c] = sum(x[c] for x in seg) / len(seg)
        rows = sm
    out = [[r[0], r[1] * dw, r[2] * dh, r[3] * dw, r[4] * dh, round(r[5], 3), bool(r[6])] for r in rows]
    lost, cur = [], None
    for r in out:
        if not r[6] and cur is None:
            cur = [r[0], r[0]]
        elif not r[6]:
            cur[1] = r[0]
        elif cur is not None:
            lost.append([round(cur[0], 3), round(r[0], 3)])
            cur = None
    if cur is not None:
        lost.append([round(cur[0], 3), round(out[-1][0] + 1 / fps, 3)])
    return {'rows': out, 'lost': lost, 'sheet': sheet, 'json': js,
            'settings': {**s, 'analysis_fps': fps, 'tracker': 'OpenCV TrackerVit (av_tools.track)'}}


def box_at(rows, t):
    """The tracked box at source time t (linear between analysed frames), or None when lost there."""
    if not rows:
        return None
    if t <= rows[0][0]:
        return tuple(rows[0][1:5]) if rows[0][6] and rows[0][0] - t < 0.05 else None
    if t >= rows[-1][0]:
        return tuple(rows[-1][1:5]) if rows[-1][6] and t - rows[-1][0] < 0.05 else None
    lo, hi = 0, len(rows) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if rows[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    a, b = rows[lo], rows[hi]
    if not (a[6] and b[6]):
        return None
    f = (t - a[0]) / max(1e-9, b[0] - a[0])
    return tuple(a[c] + (b[c] - a[c]) * f for c in range(1, 5))


# ============================================================================ the plan: recipe, changes, preview

def _work_dir(out_dir, plan_id):
    d = Path(out_dir) if out_dir else WORK / plan_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _graphics_dir(path):
    return Path(path).parent / 'graphics'


def _key_row(i, vis, c, box, quad, m6):
    row = [i, vis, round(c[0], 2), round(c[1], 2), round(box[0], 2), round(box[1], 2), round(box[2], 2),
           round(box[3], 2), [round(v, 2) for q in quad for v in q] if quad else None,
           [round(v, 6) for v in m6] if m6 else None]
    return row


def _compress(rows):
    out, last = [], None
    for r in rows:
        sig = r[1:]
        if last is None or sig != last:
            out.append(r)
            last = sig
    return out


def _freeze_still(doc, path, place, F, chain_ev, out_png):
    """The clip's own picture at timeline frame F, rendered by melt (its effects and grade included, nothing above it
    or burnt in over it), cut to where the picture is: an RGBA PNG the size of the frame."""
    from PIL import Image, ImageDraw

    import letitedit.review.checks as checks
    import letitedit.timeline.timeline_model as tm
    tree = ET.parse(path)
    root = tree.getroot()
    tractors = [e for e in root if e.tag == 'tractor']
    marked = [t for t in tractors if _props(t).get('shotcut') == '1']
    main = (marked or tractors)[-1]
    keep = place['playlist'].get('id')
    for tr in main.findall('track'):
        if tr.get('producer') not in (keep, 'background'):
            tr.set('hide', 'both')
    for f in list(main.findall('filter')):
        main.remove(f)                                  # captions and whole-video effects: not part of the clip
    root.set('root', str(Path(path).resolve().parent))
    work = Path(out_png).parent / f'freeze-{uuid.uuid4().hex[:6]}'
    work.mkdir(parents=True, exist_ok=True)
    variant = work / 'clip-only.mlt'
    tree.write(variant, encoding='utf-8', xml_declaration=True)
    try:
        png = checks.render_frames(tm.load(variant), variant, [F], work)[0]
        img = Image.open(png).convert('RGBA')
    finally:
        variant.unlink(missing_ok=True)
    k = 4
    mk = Image.new('L', (img.width * k, img.height * k), 0)
    ImageDraw.Draw(mk).polygon([(x * k, y * k) for x, y in chain_ev['quad']], fill=255)
    mk = mk.resize(img.size, Image.LANCZOS)
    img.putalpha(mk)
    tmp = Path(str(out_png) + '.tmp.png')
    img.save(tmp)
    data = tmp.read_bytes()
    final = Path(out_png).parent / f'annotate-freeze-{hashlib.sha1(data).hexdigest()[:16]}.png'
    final.parent.mkdir(parents=True, exist_ok=True)
    if not final.exists():
        os.replace(tmp, final)
    else:
        tmp.unlink(missing_ok=True)
    return str(final)


def _ctx_for(params, W, H, fps, kit):
    import letitedit.pictures.graphics as graphics
    return graphics.Ctx(W, H, fps, params['geom']['n'] / fps, 0.0, 0, params, kit)


def _picks(frames_vis, F0, n, fps, count=3):
    """Timeline frames to check: after the pop-in, the middle, near the end - visible ones only."""
    want = [min(n - 1, int(round(0.45 * fps))), n // 2, max(0, n - 1 - int(round(0.3 * fps)))][:count]
    out = []
    for w in want:
        cand = sorted(range(n), key=lambda i: abs(i - w))
        j = next((i for i in cand if frames_vis[i]), None)
        if j is not None and F0 + j not in out:
            out.append(F0 + j)
    return sorted(out)


def _annotation_tracking(F0, F1, at, box_src, chain, follow, fps, info, out_dir, place, tkind, track_result,
        tracking):
    # follow the object
    trk = None
    if follow == 'track':
        if tkind == 'point':
            raise ValueError('tracking needs a box target [x0, y0, x1, y1] around the object')
        if track_result:
            data = track_result
            if isinstance(track_result, (str, Path)):
                data = json.loads(Path(track_result).read_text(encoding='utf-8-sig'))
            if 'frames' not in data and data.get('json'):
                data = json.loads(Path(data['json']).read_text(encoding='utf-8-sig'))
            if os.path.normcase(os.path.abspath(data.get('file', ''))) != os.path.normcase(os.path.abspath(chain['file'])):
                raise ValueError(f"track_result follows {data.get('file')}, not this clip's file {chain['file']}")
            dw, dh = info['display']
            rows = [[float(r[0]), r[1] * dw, r[2] * dh, r[3] * dw, r[4] * dh, float(r[5]) if len(r) > 5 else 1.0,
                     True] for r in data['frames']]
            for r in rows:
                if r[5] < TRACK_DEFAULTS['min_score']:
                    r[6] = False
            trk = {'rows': rows, 'lost': [], 'sheet': None, 'json': None, 'settings': {'from': 'track_result'}}
        else:
            trk = track_target(chain['file'], src_time(place, F0, fps), src_time(place, F1, fps), at, box_src, info,
                               tracking, out_dir=Path(out_dir or WORK) / 'track')
    return trk


def _annotation_geometry(F0, H, W, at, box_src, chain, covered, doc, fps, freeze, hold_s, kind, lost, n,
        place, trk):
    # per-frame geometry
    rows, reasons = [], []
    rotated = False
    last_good, last_good_i, stop_at = None, None, None
    at_frame = timeline_frame(place, at, fps)
    ev_at = chain_at(chain, place['in'] + (at_frame - place['start']))
    for i in range(n):
        F = F0 + i
        if freeze:
            ev, b, why = ev_at, box_src, None
        else:
            pos = place['in'] + (F - place['start'])
            ev = chain_at(chain, pos)
            t = pos / fps
            b, why = (box_src, None) if trk is None else (box_at(trk['rows'], t), None)
            if b is None:
                why = 'lost'
                if lost == 'hold' and last_good is not None and (i - last_good_i) / fps <= hold_s:
                    b, why = last_good, 'held'
                elif lost == 'stop' and stop_at is None:
                    stop_at = i
        m = ev['m']
        if abs(((ev['rotation'] + 180) % 360) - 180) > 0.5:
            rotated = True
        if b is None or (stop_at is not None and i >= stop_at):
            rows.append(_key_row(i, 0, (0, 0), (0, 0, 0, 0), None, None))
            reasons.append(why or 'stopped')
            continue
        obox, quad = map_box(m, b)
        c = mat_apply(m, *box_center(b))
        vis = 2 if why == 'held' else 1
        if not point_in_quad(c[0], c[1], ev['quad'], 1.0):
            vis, why = 0, 'cropped away (outside the part of the picture the clip shows)'
        elif not (0 <= c[0] < W and 0 <= c[1] < H):
            vis, why = 0, 'outside the frame (zoomed or moved out of view)'
        cov = next((x for x in covered if x[0] <= F < x[1] and covers_at(doc, x[4], F, c)), None) \
            if vis and not freeze else None
        if cov is not None:
            vis, why = 0, f'covered by {cov[2]} on {cov[3]}'
        m6 = (m[0][0], m[0][1], m[0][2], m[1][0], m[1][1], m[1][2]) if kind == 'magnify' else None
        rows.append(_key_row(i, vis, c, obox, quad, m6))
        reasons.append(why if not vis else ('held' if vis == 2 else None))
        if vis == 1:
            last_good, last_good_i = b, i
    geom = {'n': n, 'keys': _compress(rows)}
    if rotated:
        geom['rotated'] = True
    return rows, reasons, at_frame, ev_at, geom


def _annotation_motion(F0, F1, at, box_src, chain, follow, fps, freeze, info, motion_check, n, out_dir, place,
        rows, tkind, warnings):
    motion = None
    if motion_check and follow == 'static' and not freeze and tkind == 'box' and n / fps > 0.4:
        # a static pointer on a moving shot drifts off the object: follow it quietly and say how far it goes
        try:
            mt = track_target(chain['file'], src_time(place, F0, fps), src_time(place, F1, fps), at, box_src, info,
                              {'smooth': 3}, out_dir=Path(out_dir or WORK) / 'motion')
            worst = (0.0, None)
            for i in range(0, n, max(1, int(round(fps / 10)))):
                if not rows[i][1]:
                    continue
                pos = place['in'] + (F0 + i - place['start'])
                bt = box_at(mt['rows'], pos / fps)
                if bt is None:
                    continue
                c_obj = mat_apply(chain_at(chain, pos)['m'], *box_center(bt))
                d = math.hypot(c_obj[0] - rows[i][2], c_obj[1] - rows[i][3])
                if d > worst[0]:
                    worst = (d, (F0 + i) / fps)
            motion = {'max_px': round(worst[0], 1), 'at_s': round(worst[1], 3) if worst[1] is not None else None,
                      'followed': f"{sum(1 for r in mt['rows'] if r[6])} of {len(mt['rows'])} analysed frames",
                      'by': 'tracker estimate (av_tools.track), not a guarantee'}
            ob = rows[next(i for i in range(n) if rows[i][1])][4:8]
            if worst[0] > 8.0 + 0.2 * max(ob[2] - ob[0], ob[3] - ob[1]):
                warnings.append(f'the object moves about {worst[0]:.0f} px away from this static pointer by '
                                f"{worst[1]:.2f} s (camera or object motion): use follow='track', freeze=True, or a "
                                'shorter range')
        except Exception as e:  # noqa: BLE001 - the check is an extra; its failure is reported, not fatal
            motion = {'error': f'motion not checked: {str(e)[:160]}'}
    return motion


def _annotation_extent_warnings(H, W, geom, kind, mid, params, tkind, warnings):
    fm = expand_geom(geom)[mid]
    st_ = style_of(params)
    if kind in ('ring', 'magnify'):
        rr = _ring_radius(fm[3], st_, H / 1080.0, tkind == 'point') + float(st_['stroke']) * H / 1080.0
        extent = (fm[1] - rr, fm[2] - rr, fm[1] + rr, fm[2] + rr)
    else:
        extent = box_grow(fm[3], 12 * H / 1080.0)
    cut = 1.0 - overlap_area(extent, (0, 0, W, H)) / max(1.0, box_area(extent))
    if cut > 0.05:
        warnings.append(f'the {kind} is {cut:.0%} outside the frame (the object is big or near the edge on screen): '
                        'a tighter target box, or kind box/arrow, reads better')
    if kind in ('ring', 'magnify') and 2 * rr > 0.8 * min(W, H):
        warnings.append(f'the ring is {2 * rr:.0f} px wide for a {box_w(fm[3]):.0f}x{box_h(fm[3]):.0f} px object on '
                        'screen; a tighter box around the part itself points more clearly')


def _annotation_changes(F0, F1, ann_id, doc, fps, freeze, kind, n, params, place, script, text, track,
        warnings):
    track_name = track or DEFAULT_TRACK
    changes = []
    names = [t['name'] for t in script['tracks']]
    at_index = names.index(track_name) if track_name in names else None
    if at_index is not None and script['tracks'][at_index].get('kind') != 'video':
        raise ValueError(f'{track_name} is an audio track; give a video track name (or none: {DEFAULT_TRACK})')
    if at_index is not None and at_index <= place['track_index']:
        # that track is under the clip, so the annotation would be hidden by the picture: a new track on top
        k = 2
        while f'{track_name} {k}' in names:
            k += 1
        warnings.append(f"{track_name} is under {place['id']}'s track ({place['track']}); the annotation goes on a new "
                        f'track {track_name} {k} on top')
        track_name, at_index = f'{track_name} {k}', None
    if at_index is None:
        changes.append({'op': 'add_track', 'name': track_name, 'kind': 'video'})
        at_index = len(names)
    if freeze:
        between = [(pid, pl['track']) for pid, pl in clip_places(doc).items()
                   if pl['producer'] is not None and pl['track_kind'] == 'video'
                   and place['track_index'] < pl['track_index'] < at_index
                   and clip_span(pl)[1] > F0 and clip_span(pl)[0] < F1]
        if between:
            warnings.append('the held picture covers what is on the tracks between the clip and the annotation during '
                            f"the freeze ({', '.join(f'{a} on {b}' for a, b in between[:5])}): put the annotation on a "
                            'track right above the clip (track=...) or move those items up')
    label = (text or '').strip() or kind
    item = {'id': ann_id, 'name': f'Annotation: {label[:40]}',
            'graphic': {'template': 'custom', 'code': CODE, 'params': params}, 'len': round(n / fps, 6)}
    changes.append({'op': 'insert', 'track': track_name, 'at': round(F0 / fps, 6), 'item': item,
                    'overlap': 'next_track'})
    return changes


def build(project, clip, kind='ring', target=None, at=None, source_range=None, timeline_range=None, duration=None,
          text=None, space='display', units='fraction', follow='static', freeze=False, style=None, protect=None,
          platform=None, track=None, lost='hide', track_result=None, tracking=None, annotation_id=None,
          avoid_faces=True, preview=True, verify=True, out_dir=None, skip_ids=(), motion_check=True):
    """Plan one annotation (nothing in the project changes): the recipe, the edit ops, preview frames rendered by the
    export engine, and checks. See letitedit_annotate for the arguments. Returns the plan dict."""
    import letitedit.timeline.edit_script as es
    t_start = time.time()
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    if follow not in ('static', 'track'):
        raise ValueError("follow is 'static' (the object stays where it is in the source picture) or 'track'")
    if lost not in ('hide', 'hold', 'stop'):
        raise ValueError("lost is 'hide' (default), 'hold' (keep the last sure place up to hold_s) or 'stop'")
    if kind == 'label' and not (text or '').strip():
        raise ValueError("kind 'label' needs text")
    doc, path = load_doc(project)
    script = es.read(path)
    revision = script['base']
    W, H, fps = doc.width, doc.height, doc.fps
    place = find_clip(doc, clip)
    chain = clip_chain(doc, place)
    info = chain['media']
    if target is None:
        raise ValueError('give target: a box [x0, y0, x1, y1] or point [x, y] in the clip\'s own picture')
    box_src, tkind = target_box(target, info, space, units)
    F0, F1, at, notes = resolve_range(place, fps, source_range, timeline_range, at, duration)
    n = F1 - F0
    warnings = list(chain['notes']) + notes
    if freeze and follow == 'track':
        warnings.append('freeze holds one picture, so tracking is not needed; the target at `at` is used')
        follow = 'static'
    ann_id = annotation_id or f'ann-{uuid.uuid4().hex[:6]}'
    trk = _annotation_tracking(F0, F1, at, box_src, chain, follow, fps, info, out_dir, place, tkind,
        track_result, tracking)
    hold_s = float((tracking or {}).get('hold_s', TRACK_DEFAULTS['hold_s']))
    covered = covered_spans(doc, place, F0, F1)
    rows, reasons, at_frame, ev_at, geom = _annotation_geometry(F0, H, W, at, box_src, chain, covered, doc,
        fps, freeze, hold_s, kind, lost, n, place, trk)
    motion = _annotation_motion(F0, F1, at, box_src, chain, follow, fps, freeze, info, motion_check, n,
        out_dir, place, rows, tkind, warnings)
    vis_flags = [bool(r[1]) for r in rows]
    hidden = _runs([(i, reasons[i]) for i in range(n) if not vis_flags[i]], F0, fps, place)
    if not any(vis_flags):
        raise Unsupported('the target is not visible anywhere in the range (' +
                          '; '.join(f"{h['why']} {h['timeline'][0]:.2f}-{h['timeline'][1]:.2f} s" for h in hidden[:4]) +
                          '): check the box, the time, and the crop/zoom on the clip')
    if sum(vis_flags) / fps < 0.5:
        warnings.append(f'the annotation shows for only {sum(vis_flags) / fps:.2f} s' +
                        (f" ({'; '.join(h['why'] for h in hidden[:3])} for the rest)" if hidden else '') +
                        ': too short to read (1.5 s or more reads comfortably)')
    mid = next(i for i in sorted(range(n), key=lambda i: abs(i - n // 2)) if vis_flags[i])
    ev_mid = ev_at if freeze else chain_at(chain, place['in'] + (F0 + mid - place['start']))
    # what else is on screen, and frames for checking
    picks = _picks(vis_flags, F0, n, fps, 3 if follow == 'static' else 5)
    pid_src = json.dumps([revision, clip, kind, list(map(float, target)), at, source_range, timeline_range, duration,
                          text, space, units, follow, freeze, style, protect, platform, track, lost, ENGINE, ann_id],
                         sort_keys=True, default=str)
    plan_id = hashlib.sha1(pid_src.encode()).hexdigest()[:12]
    work = _work_dir(out_dir, plan_id)
    import letitedit.review.checks as checks
    import letitedit.timeline.timeline_model as tm
    orig_pngs = []
    if preview or verify or avoid_faces:
        orig_pngs = checks.render_frames(tm.load(path), path, picks, _sub(work, 'original'))
    regions = protected_regions(doc, path, F0, F1, protect, platform, skip_ids=set(skip_ids) | {ann_id})
    if avoid_faces and orig_pngs:
        try:
            faces = [fb for png in orig_pngs for fb in checks.faces_in(png)]
        except Exception:  # noqa: BLE001 - no face model: nothing added
            faces = []
        for fb in faces:
            tc = box_center(rows[mid][4:8])
            if fb[0] <= tc[0] <= fb[2] and fb[1] <= tc[1] <= fb[3]:
                continue                                 # the target is on that face: don't fence it off
            regions.append({'name': 'a face', 'box': tuple(fb), 'frames': None, 'hard': True, 'source': 'faces'})
    params = {MARK: ENGINE, 'id': ann_id, 'kind': kind, 'text': (text or '').strip(), 'style': dict(style or {}),
              'point': tkind == 'point', 'size': [W, H], 'fps': round(fps, 6), 'geom': geom, 'animated': True,
              'picture': [round(v, 2) for v in ev_mid['picture_box']] if ev_mid.get('picture_box') else None,
              'protect': [{'name': r['name'], 'box': [round(v, 1) for v in r['box']], 'frames': r['frames'],
                           'source': r['source']} for r in regions],
              'src_t0': round(src_time(place, F0, fps), 6),
              'source': {'clip_id': place['id'], 'file': chain['file'], 'fingerprint': info['fingerprint'],
                         'display': info['display'], 'rotation': info['rotation'],
                         'range': [round(src_time(place, F0, fps), 4), round(src_time(place, F1, fps), 4)],
                         'at': round(at, 4), 'target': [round(v, 2) for v in box_src], 'target_kind': tkind, 'given': list(target),
                         'space': space, 'units': units, 'follow': follow, 'lost': lost,
                         'tracking': tracking or {}, 'given_protect': protect or [], 'platform': platform}}
    if kind == 'magnify':
        # the detail shows the object as it was at `at` (or, with style live: true, frame by frame)
        ma = ev_at['m']
        ca = mat_apply(ma, *box_center(box_src))
        params['mag'] = {'m': [round(v, 6) for v in (ma[0][0], ma[0][1], ma[0][2], ma[1][0], ma[1][1], ma[1][2])],
                         'c': [round(ca[0], 2), round(ca[1], 2)],
                         'box': [round(v, 2) for v in map_box(ma, box_src)[0]]}
    if freeze:
        gdir = _graphics_dir(path)
        params['freeze'] = {'png': _freeze_still(doc, path, place, at_frame, ev_at, gdir / 'annotate-freeze.png'),
                            'at': round(at, 4)}
    kit = es.kit_for(script)
    lay = solve_layout(params, _measure_with(params, W, H, fps, kit), fps)
    warnings += [f'unresolved: {u}' for u in lay['unresolved']]
    _annotation_extent_warnings(H, W, geom, kind, mid, params, tkind, warnings)
    changes = _annotation_changes(F0, F1, ann_id, doc, fps, freeze, kind, n, params, place, script, text,
        track, warnings)
    plan = {'schema_version': SCHEMA, 'engine': ENGINE, 'plan_id': plan_id, 'project': str(path),
            'project_revision': revision, 'source_fingerprints': {chain['file']: info['fingerprint']},
            'annotation_id': ann_id, 'changes': changes,
            'target': _findings(place, chain, F0, n, fps, rows, box_src, tkind, at, info),
            'timeline_range': [round(F0 / fps, 4), round(F1 / fps, 4)],
            'source_range': params['source']['range'], 'frames': [F0, F1],
            'transform': {'orientation': {'file_rotation': chain['file_rotation'],
                                          'engine_rotation': chain['engine_rotation']},
                          'effects': chain['effects'], 'at_middle': _clean_applied(ev_mid['applied']),
                          'scale': round(ev_mid['scale'], 5), 'rotation': round(ev_mid['rotation'], 3)},
            'layout': _layout_summary(lay), 'hidden_ranges': hidden, 'protected': params['protect'],
            'warnings': warnings, 'unsupported': [], 'follow': follow,
            'lost_ranges': [{'source': lr, 'timeline': [round((timeline_frame(place, lr[0], fps)) / fps, 3),
                                                        round((timeline_frame(place, lr[1], fps)) / fps, 3)],
                             'policy': lost,
                             'note': 'the pointer is hidden here (the tracker lost the object or was not sure); to '
                                     'point at it again after it comes back, add another annotation with its box at a '
                                     'time after this range'}
                            for lr in (trk or {}).get('lost', [])],
            'tracking': ({k: trk[k] for k in ('sheet', 'json', 'settings')} if trk else None),
            'motion_check': motion,
            'recipe': {'id': ann_id, 'kind': kind, 'text': params['text'], 'style': params['style'],
                       'freeze': bool(freeze), 'source': params['source'],
                       'edit': f"change wording or style later with letitedit_timeline_apply {{op: set, id: {ann_id}, "
                               "graphic: {params: {text: ..., style: {...}}}}; after trimming, moving, cropping or "
                               f"zooming the clip run letitedit_annotate(project, refresh=['{ann_id}'])"},
            'preview_artifacts': {}, 'checked_ranges': [], 'unchecked_ranges': [], 'checks': [],
            'seconds': None}
    if preview:
        _preview(plan, path, doc, params, changes, picks, orig_pngs, work, fps, kit, place, chain, trk, box_src,
                 verify)
    else:
        plan['unchecked_ranges'].append({'timeline': plan['timeline_range'], 'why': 'preview=False: nothing rendered'})
    plan['seconds'] = round(time.time() - t_start, 1)
    _save_plan(plan)
    return plan


def _sub(work, name):
    d = Path(work) / name
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob('f_*.png'):
        f.unlink()
    return d


def _measure_with(params, W, H, fps, kit):
    ctx = _ctx_for(params, W, H, fps, kit)
    st = style_of(params)

    def measure(text, size):
        return ctx.measure(text, st['font'], size)
    return measure


def _runs(items, F0, fps, place):
    """[(i, why)] -> [{'why', 'frames', 'timeline': [a, b], 'source': [a, b]}] contiguous runs."""
    out = []
    for i, why in items:
        if out and out[-1]['why'] == why and out[-1]['frames'][1] == F0 + i:
            out[-1]['frames'][1] = F0 + i + 1
        else:
            out.append({'why': why, 'frames': [F0 + i, F0 + i + 1]})
    for r in out:
        r['timeline'] = [round(r['frames'][0] / fps, 3), round(r['frames'][1] / fps, 3)]
        r['source'] = [round(src_time(place, r['frames'][0], fps), 3), round(src_time(place, r['frames'][1], fps), 3)]
    return out


def _findings(place, chain, F0, n, fps, rows, box_src, tkind, at, info):
    """Where the target lands: in the output frame at a few moments (start, middle, end of the visible frames)."""
    vis = [r for r in rows if r[1]]
    pick = [vis[0], vis[len(vis) // 2], vis[-1]] if vis else []
    out = {'clip': place['id'], 'track': place['track'], 'file': chain['file'], 'kind': tkind,
           'source_box_px': [round(v, 2) for v in box_src], 'source_size': info['display'], 'at': round(at, 4),
           'in_output': []}
    seen = set()
    for r in pick:
        if r[0] in seen:
            continue
        seen.add(r[0])
        F = F0 + r[0]
        out['in_output'].append({'timeline_s': round(F / fps, 3), 'source_s': round(src_time(place, F, fps), 3),
                                 'center': [r[2], r[3]], 'box': r[4:8]})
    return out


def _clean_applied(applied):
    return [{k: v for k, v in a.items()} for a in applied]


def _layout_summary(lay):
    out = {'mode': lay.get('mode'), 'unresolved': lay.get('unresolved') or []}
    if lay.get('label'):
        lb = lay['label']
        out['label'] = {'side': lb['side'], 'box': [round(v, 1) for v in lb['box']] if lb.get('box') else 'follows'}
    if lay.get('inset'):
        out['inset'] = {'box': [round(v, 1) for v in lay['inset']['box']], 'zoom': lay['inset'].get('zoom'),
                        'side': lay['inset']['side']}
    if lay.get('arrow'):
        out['arrow'] = {'from': lay['arrow']['side']}
    if lay.get('text'):
        out['text_size'] = lay['text']['size']
    return out


def _preview_copy(path, changes, work, graphics_dir):
    """The project with the changes, as a separate file in the work folder (media referenced in place)."""
    import letitedit.timeline.edit_script as es
    tree = ET.parse(path)
    tree.getroot().set('root', str(Path(path).resolve().parent))
    copy_path = Path(work) / 'preview.mlt'
    tree.write(copy_path, encoding='utf-8', xml_declaration=True)
    before = es.read(copy_path)
    after, notes = es.edit(before, [copy.deepcopy(c) for c in changes])
    after['base'] = before['base']
    es.compile_script(after, base=copy_path, out=copy_path, graphics_dir=graphics_dir)
    return copy_path, notes


def _preview(plan, path, doc, params, changes, picks, orig_pngs, work, fps, kit, place, chain, trk, box_src, verify):
    import letitedit.review.checks as checks
    import letitedit.pictures.graphics as graphics
    import letitedit.timeline.timeline_model as tm
    gdir = Path(work) / 'graphics'
    copy_path, notes = _preview_copy(path, changes, work, gdir)
    plan['warnings'] += [f'edit: {x}' for x in notes]
    pngs = checks.render_frames(tm.load(copy_path), copy_path, picks, _sub(work, 'preview'))
    labels = [f'{checks.fmt(F / fps)}' for F in picks]
    sheet = checks.contact_sheet([str(p) for p in pngs], labels, cols=min(3, len(pngs)), tile_w=640)
    sheet_path = Path(work) / 'preview.jpg'
    sheet.save(sheet_path, 'JPEG', quality=88)
    rendered = sorted(gdir.glob('custom-*'))
    plan['preview_artifacts'] = {'sheet': str(sheet_path), 'frames': [str(p) for p in pngs],
                                 'original_frames': [str(p) for p in orig_pngs], 'preview_project': str(copy_path),
                                 'graphic': str(rendered[-1]) if rendered else None, 'folder': str(work)}
    plan['checked_ranges'] = [{'timeline_s': round(F / fps, 3), 'by': 'melt render (export engine)'} for F in picks]
    first_unchecked = plan['timeline_range']
    plan['unchecked_ranges'].append({'timeline': first_unchecked, 'why': f'only {len(picks)} frames were rendered and '
                                     'measured; motion between them was not watched (letitedit_check_range plays it)'})
    if not verify:
        return
    # where the object is in the rendered frame (from the pixels), and where the pointer was drawn
    st = style_of(params)
    color = kit.rgba(st['color'])
    frames = expand_geom(params['geom'])
    lay = solve_layout(params, _measure_with(params, *params['size'], fps, kit), fps)
    srcs = {}
    frozen = None
    if params.get('freeze'):
        # the held picture is the clip at `at`: find the object in the export engine's render of that frame, and
        # measure the pointer against the render plus the held picture (so only the pointer itself differs)
        from PIL import Image
        F_at = timeline_frame(place, float(params['freeze']['at']), fps)
        at_png = checks.render_frames(tm.load(path), path, [F_at], _sub(work, 'original-at'))[0]
        frozen = {'at_png': at_png, 'img': Image.open(params['freeze']['png']).convert('RGBA')}
        plan['checked_ranges'].append({'timeline_s': round(F_at / fps, 3), 'by': 'melt render of the held frame'})
    for F, before, after in zip(picks, orig_pngs, pngs):
        i = F - plan['frames'][0]
        f = frames[i]
        if f is None:
            continue
        before_ptr = before
        if frozen is not None:
            from PIL import Image
            comp = Image.alpha_composite(Image.open(before).convert('RGBA'), frozen['img'])
            before_ptr = str(Path(work) / 'original-at' / f'frozen-{F}.png')
            comp.convert('RGB').save(before_ptr)
            before = frozen['at_png']
        pos = place['in'] + (F - place['start'])
        t_src = params['freeze']['at'] if params.get('freeze') else pos / fps
        ev = chain_at(chain, timeline_frame(place, t_src, fps) - place['start'] + place['in']) if params.get('freeze') \
            else chain_at(chain, pos)
        # look for the object as it looked at `at` (the box given), where the pointer is drawn now: a camera that moved
        # under a static pointer, or a tracker that drifted onto something else, shows up as an error
        m_chk, t_img = ev['m'], float(params['source']['at'])
        if trk is not None and not params.get('freeze'):
            bt = box_at(trk['rows'], pos / fps)
            if bt is not None:
                ca, ct = box_center(box_src), box_center(bt)
                kx = box_w(bt) / max(1e-6, box_w(box_src))
                ky = box_h(bt) / max(1e-6, box_h(box_src))
                move = mat_mul(mat_translate(ct[0], ct[1]), mat_mul(mat_scale(kx, ky), mat_translate(-ca[0], -ca[1])))
                m_chk = mat_mul(ev['m'], move)
        try:
            key = round(t_img, 4)
            if key not in srcs:
                srcs[key] = graphics.still(chain['file'], t_img, tuple(chain['media']['display']))
            loc = locate_target(before, srcs[key], box_src, m_chk, visible=ev.get('picture_box'))
        except Exception as e:  # noqa: BLE001 - a check that can't run is reported as not done
            loc = {'error': str(e)[:200]}
        row = {'timeline_s': round(F / fps, 3), 'predicted_center': [round(f[1], 2), round(f[2], 2)]}
        if loc and 'found' in loc:
            row['object_in_render'] = {**loc, 'verdict': verdict(loc)}
        elif loc:
            row['object_in_render'] = loc
        if trk is not None and not params.get('freeze'):
            # the tracked box's own picture at this moment, through the transform: checks the mapping (not the tracker)
            bt = box_at(trk['rows'], pos / fps)
            if bt is not None:
                try:
                    kk = round(pos / fps, 4)
                    if kk not in srcs:
                        srcs[kk] = graphics.still(chain['file'], pos / fps, tuple(chain['media']['display']))
                    lt = locate_target(before, srcs[kk], bt, ev['m'], visible=ev.get('picture_box'))
                    if lt:
                        row['tracked_patch_in_render'] = {**lt, 'verdict': verdict(lt)}
                except Exception as e:  # noqa: BLE001
                    row['tracked_patch_in_render'] = {'error': str(e)[:160]}
        try:
            row.update(pointer_check(params, lay, frames, i, before_ptr, after, color,
                                     loc if loc and verdict(loc) == 'matched' else None))
        except Exception as e:  # noqa: BLE001 - a check that can't run is reported as not done
            row['pointer_check'] = f'not measured: {str(e)[:160]}'
        plan['checks'].append(row)
    matched = [c for c in plan['checks'] if isinstance(c.get('object_in_render'), dict)
               and c['object_in_render'].get('verdict') == 'matched']
    errs = [c['object_in_render']['error_px'] for c in matched]
    other = [c['object_in_render'].get('verdict') for c in plan['checks']
             if isinstance(c.get('object_in_render'), dict) and c['object_in_render'].get('verdict') != 'matched']
    plan['check_summary'] = (f'object found in {len(errs)} of {len(plan["checks"])} rendered frames, at most '
                             f'{max(errs):.1f} px from where the pointer aims' if errs else
                             'the object could not be matched confidently in the rendered frames; the mapping is '
                             'computed but not confirmed by pixels') + \
        (f" (not confirmed: {', '.join(sorted({v for v in other if v}))})" if other else '')
    mapped = [c['tracked_patch_in_render']['error_px'] for c in plan['checks']
              if isinstance(c.get('tracked_patch_in_render'), dict)
              and c['tracked_patch_in_render'].get('verdict') == 'matched']
    if mapped:
        plan['check_summary'] += (f'; the tracked box maps onto the rendered picture within {max(mapped):.1f} px in '
                                  f'{len(mapped)} frames (whether the tracker stayed on the object: see the tracking '
                                  'sheet)')
    tb = frames[next(i for i, f in enumerate(frames) if f is not None)][3]
    allow = 6.0 + 0.15 * max(box_w(tb), box_h(tb))
    far = [c for c in matched if c['object_in_render']['error_px'] > allow]
    if far:
        worst = max(far, key=lambda c: c['object_in_render']['error_px'])
        plan['warnings'].append(
            f"the object is {worst['object_in_render']['error_px']:.0f} px away from the pointer at "
            f"{worst['timeline_s']:.2f} s (it or the camera moves): " +
            ("check the tracking sheet, or shorten the range" if trk is not None else
             "use follow='track', freeze=True, or a shorter range"))
    del lay


def _plans_dir():
    d = WORK / 'plans'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_plan(plan):
    (_plans_dir() / f"{plan['plan_id']}.json").write_text(json.dumps(plan, indent=1, default=str), encoding='utf-8')


def load_plan(plan_id):
    p = _plans_dir() / f'{plan_id}.json'
    if not p.exists():
        raise ValueError(f'No plan {plan_id} (plans are kept in {_plans_dir()}); make it again with letitedit_annotate')
    return json.loads(p.read_text(encoding='utf-8-sig'))


def apply_plan(plan, expected_revision=None, label=None, actor=None):
    """Apply a plan (dict or plan_id) to its project file: refused when the project or the source media changed since
    the plan was made (make it again). The rendered graphic from the preview is reused. Returns the apply result
    (changes, history copy for undo)."""
    import letitedit.timeline.edit_script as es
    import letitedit.server.timeline_tools as timeline_tools
    if isinstance(plan, str):
        plan = load_plan(plan)
    path = Path(plan['project'])
    rev = es.file_hash(path)
    want = expected_revision or plan['project_revision']
    if rev != want:
        raise es.Conflict(f'the project changed since this annotation was planned (revision {want}, now {rev}); '
                          'plan it again (letitedit_annotate without apply)')
    for f, fp in (plan.get('source_fingerprints') or {}).items():
        if not os.path.exists(f) or fingerprint(f) != list(fp):
            raise es.Conflict(f'the source file changed or is missing since the plan was made: {f}')
    art = plan.get('preview_artifacts') or {}
    g = art.get('graphic')
    if g and os.path.exists(g):
        dst = _graphics_dir(path) / Path(g).name
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(g, dst)
    result, _ = timeline_tools.apply_project(str(path), plan['changes'], check=False,
                                             label=label or f"annotate: {plan['recipe']['kind']} "
                                                            f"{plan['recipe']['text'][:30]}".strip(),
                                             actor=actor)
    return result


# ============================================================================ existing annotations: list, refresh

def annotations(project):
    """Every annotation made by this module in a project: [{id, track, at, len, kind, text, source}]."""
    doc, _ = load_doc(project)
    out = []
    for iid, pl in clip_places(doc).items():
        prod = pl['producer']
        if prod is None:
            continue
        raw = _props(prod).get('letitedit_ai:graphic')
        if not raw:
            continue
        try:
            g = json.loads(raw)
        except ValueError:
            continue
        p = g.get('params') or {}
        if g.get('template') != 'custom' or not p.get(MARK):
            continue
        out.append({'id': iid, 'track': pl['track'], 'at': round(pl['start'] / doc.fps, 4),
                    'len': round(pl['frames'] / doc.fps, 4), 'kind': p.get('kind'), 'text': p.get('text'),
                    'freeze': bool(p.get('freeze')), 'source': p.get('source'), 'params': p})
    return out


def refresh(project, ids=None, preview=True, verify=True, out_dir=None):
    """Re-solve existing annotations against the timeline as it is now (after the clip was trimmed, moved, cropped,
    zoomed or re-timed elsewhere): each is planned again from its stored recipe (same id, text, style, target), and
    the ops that bring it up to date are returned (set/move, or delete when its moment is gone). Nothing is written."""
    import letitedit.timeline.edit_script as es
    found = annotations(project)
    if ids:
        want = set(ids if isinstance(ids, (list, tuple, set)) else [ids])
        missing = want - {a['id'] for a in found}
        if missing:
            raise ValueError(f"no annotation with id {', '.join(sorted(missing))} (annotations here: "
                             f"{', '.join(a['id'] for a in found) or 'none'})")
        found = [a for a in found if a['id'] in want]
    doc, path = load_doc(project)
    fps = doc.fps
    places = clip_places(doc)
    results = []
    for a in found:
        p, src = a['params'], a['source'] or {}
        cid = src.get('clip_id')
        place = places.get(cid)
        if place is None or _props(place['producer']).get('resource') not in (src.get('file'), None) and \
                _props(place['producer']).get('warp_resource') != src.get('file'):
            # the clip id is gone or now plays another file: look for the same file showing that moment
            place = next((pl for pl in places.values() if pl['producer'] is not None and
                          (_props(pl['producer']).get('resource') == src.get('file')) and
                          pl['in'] <= int(round(float(src['range'][0]) * fps)) < pl['in'] + pl['frames']), None)
        rec = {'id': a['id'], 'was': {'at': a['at'], 'len': a['len']}}
        if place is None:
            rec.update(status='gone', changes=[{'op': 'delete', 'id': a['id']}],
                       why=f"the annotated moment ({Path(src.get('file', '?')).name} {src.get('range')}) is no longer on "
                           'the timeline')
            results.append(rec)
            continue
        first, end = clip_span(place)
        r0, r1 = [float(v) for v in src['range']]
        F0 = max(first, timeline_frame(place, r0, fps))
        F1 = min(end, timeline_frame(place, r1, fps))
        if F1 - F0 < 2:
            rec.update(status='gone', changes=[{'op': 'delete', 'id': a['id']}],
                       why='the annotated source moment was trimmed out of the clip')
            results.append(rec)
            continue
        at = min(max(float(src['at']), src_time(place, F0, fps)), src_time(place, F1, fps))
        try:
            tgt = src['target'][:2] if src.get('target_kind') == 'point' or p.get('point') else src['target']
            plan = build(path, place['id'], kind=p['kind'], target=tgt, at=at,
                         source_range=[src_time(place, F0, fps), src_time(place, F1, fps)],
                         text=p.get('text'), space='display', units='px', follow=src.get('follow', 'static'),
                         freeze=bool(p.get('freeze')), style=p.get('style'), protect=src.get('given_protect'),
                         platform=src.get('platform'), track=a['track'], lost=src.get('lost', 'hide'),
                         tracking=src.get('tracking') or None, annotation_id=a['id'], preview=preview, verify=verify,
                         out_dir=(Path(out_dir) / a['id']) if out_dir else None, skip_ids={a['id']})
        except Unsupported as e:
            rec.update(status='unsupported', why=str(e), changes=[])
            results.append(rec)
            continue
        new_item = next(c['item'] for c in plan['changes'] if c['op'] == 'insert')
        new_at = next(c['at'] for c in plan['changes'] if c['op'] == 'insert')
        new_params = new_item['graphic']['params']
        for k in ('given', 'units', 'space'):          # the recipe keeps how the target was first given
            if k in src:
                new_params['source'][k] = src[k]
        changes = []
        same_geom = json.dumps(p, sort_keys=True, default=str) == json.dumps(new_params, sort_keys=True, default=str)
        if not same_geom or abs(new_item['len'] - a['len']) > 0.5 / fps:
            changes.append({'op': 'set', 'id': a['id'], 'graphic': {'template': 'custom', 'code': CODE,
                                                                    'params': new_item['graphic']['params']},
                            'len': new_item['len']})
        if abs(new_at - a['at']) > 0.5 / fps:
            changes.append({'op': 'move', 'id': a['id'], 'at': new_at, 'overlap': 'next_track'})
        rec.update(status='up to date' if not changes else 'changed', changes=changes, plan_id=plan['plan_id'],
                   now={'at': new_at, 'len': new_item['len']}, preview=plan.get('preview_artifacts', {}).get('sheet'),
                   checks=plan.get('checks'), warnings=plan.get('warnings'))
        results.append(rec)
    all_changes = [c for r in results for c in r.get('changes', [])]
    out = {'schema_version': SCHEMA, 'project': str(path), 'project_revision': es.file_hash(path),
           'annotations': results, 'changes': all_changes}
    out['plan_id'] = hashlib.sha1(json.dumps([out['project_revision'], all_changes], sort_keys=True,
                                             default=str).encode()).hexdigest()[:12]
    if all_changes:
        _save_plan({'plan_id': out['plan_id'], 'project': str(path), 'project_revision': out['project_revision'],
                    'source_fingerprints': {}, 'changes': all_changes, 'recipe': {'kind': 'refresh', 'text': ''},
                    'preview_artifacts': {}})
    return out
