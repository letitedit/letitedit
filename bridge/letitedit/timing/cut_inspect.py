"""Cut inspector: what happens at each cut, measured, with the frames to look at (the timing layer's 'cuts' view).

    inspect(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief') -> dict
    view(source, start_s, end_s, items, cuts, options, detail)      the registered 'cuts' view (timing_views)
    analyse_side(bgr_frames, fps, settings=None) -> per-frame motion, saliency and faces of ONE shot's frames
    measure_join(side_a, side_b, fps, ...) -> the measures of one join (frames before the cut, frames after it)
    verdict(measures, kind='cut', sound=None) -> smooth | noticeable | jarring, with the findings behind it
    shift_test(video, cuts, shifts=(2, 4, 8), ...) -> do real cuts measure differently from the same cuts moved?
    roll_test(project, ...) -> the same with frames from the source clips (the cut moved earlier and later)
    thresholds() -> the 'cuts.' thresholds in use (bridge/timing_thresholds.json, defaults for missing keys)

`source` is a project (.mlt or a managed episode/cut folder) or a video file. For a project the frames come from the
preview render of the timeline (timing_signals' render when that store is present, else a melt render made here,
cached by the timeline's content), so what is measured is what the viewer gets.

What is measured at each cut (Walter Murch's rule of six: emotion and story are for the editor and the skills to
judge; the four measurable parts are measured here, every value with its unit and the threshold used):

1. Rhythm / action. Dense optical flow (OpenCV DIS) between consecutive frames of each shot, at `flow_px` (long side
   256), with the camera's own move (a similarity transform fitted to the flow with RANSAC) removed. Per frame:
   `subject speed` = 95th percentile of the remaining flow (frame diagonals per second, diag/s: 0.01 static, ~0.2
   a talking head's small moves, 0.3+ a gesture or walk), `energy` (mean), moving share, dominant direction and its
   coherence, the moving region. At the cut: speed over the last frames of the outgoing shot (A) and the first of the
   incoming one (B), where the cut falls in A's action (still / building / at the peak / settling / after the
   action) and how B starts, `cut on action` (motion on both sides), the share of a cross-cut action shown before the
   cut, and post-cut motion over B's first 0.3 s (Smith & Martin-Portugues 2017: motion right after a cut hides it
   best).
2. Eye-trace. An attention point per frame: the main face when one is big enough (YuNet), else the peak of a
   spectral-residual saliency map mixed with the motion map and a centre bias; burned-in text and graphics that stay
   the same across the cut are masked out. Jump = distance from A's point (its last 3 frames) to B's point (its first
   0.3 s: the eye's first saccade target after a cut) in frame diagonals; dx in frame widths, dy in heights.
3. 2D plane / screen direction. Dominant subject-motion direction (degrees, 0 = screen right, 90 = up) in A's last
   and B's first 0.3 s with its coherence, the angle change and left/right agreement; camera pan direction on each
   side; the subject's screen position (left / centre / right) on each side; face facing (left / front / right).
4. 3D space. Framing similarity of A's last and B's first frame (NCC after the best camera compensation, as
   shots.py measures it, and a coarse layout NCC), the reframe zoom between them, colour change; shot size from the
   main face's height (extreme close-up .. wide); size ratio; same person on both sides (SFace); jump cut (same
   framing and size), punch-in (same picture, zoomed), scene change.
Also measured: brightness jump, colour shift, blank frames at the join, shot lengths (flash frames). Sound across the
join comes from B3's 'joins' view when it is registered; otherwise it is reported as unchecked.

The verdict (smooth / noticeable / jarring) is only a summary of these measures: every finding names its measure,
its value and the threshold it passed (thresholds: 'cuts.*' in bridge/timing_thresholds.json, so calibration can
retune them without code changes). It says how visible the cut is, not whether it is right: a jump cut in a vlog is
visible on purpose. Motion running across the cut lowers eye-trace and direction findings by one step (edit
blindness). Gradual transitions (dissolves, fades) are not scored for eye-trace and direction.

Images: per cut one strip (the frames before the cut on the first row, after it on the second, at the full frame
rate, with motion arrows, attention dots and faces drawn, a blend of the two frames at the join with the eye-trace
jump, the subject-speed curve and the key numbers) and one overview sheet of every cut with its verdict. All files
are written under <cache>\\timing-cuts\\.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)


# ---- this module's parts: every name in them imported back, so each is the same object as before
# the settings and thresholds, small helpers, the per-thread OpenCV objects and decoding
from letitedit.timing.cut_inspect_base import (  # noqa: E402,F401
    _SAI_ROOT, SCHEMA_VERSION, CODE_VERSION, VIEW, SUMMARY, CACHE, APP, MELT, FFMPEG, YUNET, SFACE,
    THRESHOLDS_FILE, NO_WINDOW, DEFAULTS, THRESHOLD_SPEC, THRESHOLD_DEFAULTS, _THR_CACHE, _read_threshold_file,
    thresholds, ensure_thresholds_file, _settings, _h, _r, _clock, _jsonable, _write_json, _angle_diff, _circ_mean,
    _dir_word, _TL, CV_THREADS, _cv2, _dis, _saliency_obj, faces_available, _face_detector, _face_recognizer,
    probe, _sizes, decode_frames, _SHOWINFO, _decode_raw, decode_at_times
)
# the per-frame analysis, the action phase and a detected cut snapped to its frame
from letitedit.timing.cut_inspect_frames import (  # noqa: E402,F401
    _GRIDS, _grid, _flow_step, _faces, _saliency, analyse_side, _subset, _static_overlay, _attention,
    _median_point, _phase_out, _phase_in, snap_cut
)
# a join measured, its verdict, and the sound across it
from letitedit.timing.cut_inspect_join import (  # noqa: E402,F401
    _size_class, _SIZE_ORDER, _yuv_hist, _textured_cells_changed, _ncc, measure_join, SOUND_FLAG_SEVERITY,
    SOUND_FLAG_WORDS, _sound_findings, verdict, _joins, _match_sound
)
# the strips drawn
from letitedit.timing.cut_inspect_draw import (  # noqa: E402,F401
    _FONTS, _font, VCOL, COL_A, COL_B, COL_MOVE, COL_FACE, COL_CUT, _arrow, _dot, _tile_size, _draw_tile, _chart,
    _measure_lines, _sound_line, sound_brief, _wrap, draw_strip
)
# where the cuts are
from letitedit.timing.cut_inspect_cuts import (  # noqa: E402,F401
    PICTURE_EXT, IMAGE_EXT, _store, _is_project, _resolve_project, _is_picture, project_cuts, preview_render,
    video_cuts, store_cut_list, _store_cuts, _select
)
# the validation: real cuts against the same cuts moved
from letitedit.timing.cut_inspect_validate import (  # noqa: E402,F401
    FEATURES, _features, shift_test, roll_test, separation
)



# ------------------------------------------------------------------ inspecting

def _windows(sel, cut_list, frames):
    """Shot bounds of every selected cut: A = [prev boundary, a_end), B = [b_start, next boundary)."""
    bounds = sorted({(c['a_end'], c['b_start']) for c in cut_list})
    for c in sel:
        prev_b = [b for a, b in bounds if b <= c['a_end'] and (a, b) != (c['a_end'], c['b_start'])]
        next_a = [a for a, b in bounds if a >= c['b_start'] and (a, b) != (c['a_end'], c['b_start'])]
        c['_a0'] = max(prev_b) if prev_b else 0
        c['_b1'] = min(next_a) if next_a else frames


def _window(c, st, fps):
    """The frames decoded for one cut: A = [a0, a_end), B = [b_start, b1), each at most context_s long and inside
    the shot."""
    ctx = max(int(round(float(st['context_s']) * fps)), int(st['before']), int(st['after']), 3)
    a0 = max(int(c['_a0']), int(c['a_end']) - ctx)
    b1 = min(int(c['_b1']), int(c['b_start']) + ctx)
    return a0, int(c['a_end']), int(c['b_start']), b1


def _measure_cut(video, info, c, st, thr, fps):
    """Decode the frames around one cut, analyse both sides, measure the join. A hard cut found in the picture (not
    from an edit script) is first snapped to the largest change within 2 frames."""
    a0, a1, b0, b1 = _window(c, st, fps)
    if a1 - a0 < 1 or b1 - b0 < 1:
        raise ValueError('no frames on one side of the cut (a shot of 0 frames)')
    dsize, _ = _sizes(info['w'], info['h'], st['decode_px'], st['flow_px'])
    fr = decode_frames(video, a0 - 2, b1 + 2, dsize, info)
    if c.get('snap') and c['kind'] == 'cut' and a1 == b0:
        g = snap_cut(fr, a1)
        if g != a1:
            c['snapped_from'] = c['f']
            c['f'] = c['a_end'] = c['b_start'] = g
            a0, a1, b0, b1 = _window(c, st, fps)
    af = [i for i in range(a0, a1) if i in fr]
    bf = [i for i in range(b0, b1) if i in fr]
    if not af or not bf:
        raise ValueError(f'could not decode frames around frame {c["f"]}')
    A = analyse_side([fr[i] for i in af], fps, st, thr, frames=af)
    B = analyse_side([fr[i] for i in bf], fps, st, thr, frames=bf)
    m = measure_join(A, B, fps, st, thr, shot_frames=(int(c['a_end'] - c['_a0']), int(c['_b1'] - c['b_start'])),
                     kind=c['kind'])
    return A, B, m


def draw_cell(rec, a_bgr, b_bgr, pa, pb, out_path):
    """The overview cell of one cut: A's last and B's first frame side by side with the attention points."""
    from PIL import Image, ImageDraw
    cv2 = _cv2()
    h, w = a_bgr.shape[:2]
    if w >= h:
        cw_, ch_ = 150, int(round(150 * h / w))
    else:
        ch_, cw_ = 160, int(round(160 * w / h))
    im = Image.new('RGB', (2 * cw_ + 2, ch_), (16, 16, 18))
    for j, (img, p, col) in enumerate(((a_bgr, pa, COL_A), (b_bgr, pb, COL_B))):
        t = Image.fromarray(cv2.cvtColor(cv2.resize(img, (cw_, ch_), interpolation=cv2.INTER_AREA),
                                         cv2.COLOR_BGR2RGB))
        if p:
            _dot(ImageDraw.Draw(t), p['x'] * cw_, p['y'] * ch_, col, r=4)
        im.paste(t, (j * (cw_ + 2), 0))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path, quality=88)
    return str(out_path)


def draw_overview(cuts, out_path, title=''):
    """One sheet of every cut: its overview cell (A last | B first, attention dots), the verdict colour, its number,
    time and first reason."""
    from PIL import Image, ImageDraw
    cells = []
    for c in cuts:
        p = c.get('cell')
        if p and os.path.exists(p):
            cells.append((c, Image.open(p).convert('RGB')))
    if not cells:
        return None
    cw, chh = cells[0][1].size
    cell_w, cell_h = cw + 6, chh + 34
    cols = max(1, min(len(cells), 1500 // cell_w))
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * cell_w, 32 + rows * cell_h), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    d.text((6, 6), title, fill=(235, 235, 235), font=_font(15, bold=True))
    for k, (c, im) in enumerate(cells):
        x, y = (k % cols) * cell_w, 32 + (k // cols) * cell_h
        if im.size != (cw, chh):
            im = im.resize((cw, chh))
        sheet.paste(im, (x, y))
        vcol = VCOL.get(c['verdict']['verdict'], VCOL['unknown'])
        d.rectangle([x, y + chh + 1, x + cw, y + chh + 6], fill=vcol)
        d.text((x + 2, y + chh + 8), f'{c["n"] if c.get("n") is not None else "-"} {_clock(c["t"])} '
                                     f'{c["verdict"]["verdict"]}', fill=(235, 235, 235), font=_font(12, bold=True))
        why = (c['verdict']['reasons'] or [''])[0]
        d.text((x + 2, y + chh + 21), why[:int(cell_w / 6.0)], fill=(190, 190, 195), font=_font(10))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=88)
    return str(out_path)


def _cut_key(c, base_key, st, thr, sound, fps, tl=None):
    """Cache key of one cut's measures and pictures: the frames that decide them (a project: the timeline's own
    fingerprint of the decoded range, so an edit elsewhere keeps it; a video: its content key), the cut's place in
    them, the settings, thresholds, the sound entry and the code version."""
    a0, a1, b0, b1 = _window(c, st, fps)
    if tl is not None:
        try:
            frames_key = tl.range_fingerprint(a0, b1, video=True, audio=False)
        except Exception:  # noqa: BLE001
            frames_key = [base_key, a0, b1]
    else:
        frames_key = [base_key, a0, b1]
    return _h([CODE_VERSION, frames_key, base_key if tl is None else None, a1 - a0, b0 - a0, b1 - a0,
               c['a_end'] - c['_a0'], c['_b1'] - c['b_start'], c.get('n'), c['f'], c['kind'], c.get('gap'),
               c.get('from_clip'), c.get('to_clip'), c.get('from_item'), c.get('to_item'), c.get('detail'),
               {k: st[k] for k in ('before', 'after', 'context_s', 'motion_window_s', 'att_a_frames', 'att_b_s',
                                   'decode_px', 'flow_px')}, thr, sound], 20)


OPTIONS_DOC = {
    'before': 'frames shown before the cut (6)', 'after': 'frames shown after it (6)',
    'context_s': 'rhythm window each side, clipped to the shot (1.0)',
    'motion_window_s': 'direction and pre/post-cut motion window (0.3)',
    'max_cuts': 'cuts measured per call (80)', 'images': "'auto' (overview + 3 worst), 'all' or a number",
    'overview': 'draw the overview sheet (true)', 'kinds': 'cut kinds to include',
    'thresholds': '{cuts.key: value} overrides for this call', 'refresh': 'measure again (ignore the cache)',
    'settings': 'timing store settings {lane: {...}} (passed to timing_signals and joins)',
    'sound': 'false skips the sound measures (joins; its first call transcribes the source); default true',
}


def _inspection_source(end_s, kind, options, refresh, src, st, start_s, store, warnings):
    meta = None
    if store is not None:
        got = _store_cuts(store, src, start_s, end_s, warnings, settings=options.get('settings'), refresh=refresh)
        if got:
            meta, cut_list = got
    if meta is None:
        if kind == 'project':
            meta, cut_list = project_cuts(src)
            meta['video'] = str(preview_render(src, px=int(st['preview_px'])))
            meta['render_made_here'] = True
        else:
            info0 = probe(src)
            m2, cut_list = video_cuts(src, None, None, st.get('detect') or {'workers': 1})
            meta = dict(m2, video=src, fps=float(info0['fps']),
                        frames=int(info0['frames'] or round(info0['duration'] * info0['fps'])),
                        size=[info0['w'], info0['h']])
            warnings.extend(m2.get('detect_warnings') or [])
        meta['numbers_from'] = 'cut_inspect alone (timing_signals not present)'
    else:
        meta['numbers_from'] = ('cut list: timing_signals edit lane; join measures: full-rate frames of the same '
                                'render, measured here')
    return meta, cut_list


def _inspect_selected_cuts(base_key, fps, info, jdir, refresh, sel, sound_entries, sound_why, st, thr, tl,
        video, warnings):
    def job(c):
        rec = {k: c.get(k) for k in ('n', 'f', 'kind', 'detail', 'from_item', 'to_item', 'from_clip', 'to_clip',
                                     'a_end', 'b_start', 'gap', 'range', 'from_out_s', 'to_in_s', 'same_clip',
                                     'source_jump_s') if c.get(k) is not None}
        rec['n'] = c.get('n')
        rec['t'] = _r(c['f'] / fps, 4)
        snd = _match_sound(sound_entries, c, fps)
        sound = snd if snd is not None else {'status': 'unchecked', 'why': sound_why or 'no joins entry for this cut'}
        key = _cut_key(c, base_key, st, thr, snd, fps, tl)
        cf = jdir / key[:2] / f'{key}.json'
        if not refresh and cf.exists():
            try:
                old = json.loads(cf.read_text(encoding='utf-8-sig'))
                if all(os.path.exists(old.get(k) or '') for k in ('image', 'cell')):
                    old.update({k: rec[k] for k in ('n', 't')}, cached=True)
                    return old
            except (OSError, ValueError):
                pass
        try:
            A, B, m = _measure_cut(video, info, c, st, thr, fps)
        except Exception as ex:  # noqa: BLE001 - one bad cut does not stop the view
            rec['error'] = f'{type(ex).__name__}: {ex}'
            rec['verdict'] = {'verdict': 'unknown', 'severity': None, 'findings': [], 'masks': [],
                              'reasons': [f'not measured: {ex}']}
            rec['sound'] = sound
            return rec
        if c.get('snapped_from') is not None:
            rec.update(f=c['f'], a_end=c['a_end'], b_start=c['b_start'], t=_r(c['f'] / fps, 4),
                       snapped_from=c['snapped_from'])
            warnings.append(f'cut {rec.get("n")}: the picture changes at f{c["f"]}, not f{c["snapped_from"]} as the '
                            'cut list said; measured at f' + str(c['f']))
        rec['sound'] = sound
        gap_n = (c['gap'][1] - c['gap'][0]) if c.get('gap') else None
        rec['measures'] = m
        rec['verdict'] = verdict(m, c['kind'], snd, thr, gap_frames=gap_n)
        rec['a_frames'] = A['frames']
        rec['b_frames'] = B['frames']
        try:
            rec['image'] = draw_strip(rec, A, B, st, thr, jdir / key[:2] / f'{key}.jpg', video=video)
            rec['cell'] = draw_cell(rec, A['bgr'][-1], B['bgr'][0], m['_draw'].get('pa'), m['_draw'].get('pb'),
                                    jdir / key[:2] / f'{key}-cell.jpg')
        except Exception as ex:  # noqa: BLE001
            warnings.append(f'pictures for cut {rec.get("n")} failed: {type(ex).__name__}: {ex}')
        out = _full(rec)
        try:
            _write_json(cf, out)
        except OSError:
            pass
        return out
    workers = max(1, min(int(st['workers']), len(sel) or 1))
    if workers == 1:
        results = [job(c) for c in sel]
    else:
        with ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(job, sel))
    return results


def _inspection_pictures(cuts, folder, results, src, st, warnings):
    counts = {'smooth': 0, 'noticeable': 0, 'jarring': 0, 'unknown': 0}
    for r in results:
        counts[r['verdict']['verdict']] = counts.get(r['verdict']['verdict'], 0) + 1
    images, artifacts = [], []
    overview = None
    if st['overview'] and len(results) > 1:
        try:
            overview = draw_overview(results, folder / 'overview.jpg',
                                     title=f'{Path(src).name}: {len(results)} cuts  smooth {counts["smooth"]}  '
                                           f'noticeable {counts["noticeable"]}  jarring {counts["jarring"]}'
                                           f'  (yellow dot: eye before the cut, cyan: after)')
        except Exception as ex:  # noqa: BLE001
            warnings.append(f'overview failed: {type(ex).__name__}: {ex}')
    if overview:
        artifacts.append({'kind': 'overview', 'path': overview})
    for r in results:
        if r.get('image'):
            artifacts.append({'kind': 'strip', 'path': r['image'], 'cut': r.get('n'), 'f': r['f']})
    listed = cuts is not None
    if listed:
        ranked = [r for r in results if r.get('image')]
    else:
        ranked = sorted([r for r in results if r.get('image')],
                        key=lambda r: (-(r['verdict']['severity'] or 0), r['f']))
    nimg = st['images']
    if nimg == 'all':
        n_strips = len(ranked)
    elif isinstance(nimg, (int, float)) and not isinstance(nimg, bool):
        n_strips = max(0, int(nimg))
    else:
        n_strips = len(ranked) if listed and len(ranked) <= 4 else 3
    if overview and not (listed and len(ranked) <= 4):
        images.append(overview)
    images += [r['image'] for r in ranked[:n_strips]]
    lines = []
    for r in results:
        v = r['verdict']
        lines.append(f'cut {r.get("n") if r.get("n") is not None else "-"} {_clock(r["t"])} f{r["f"]} {r["kind"]}'
                     + (f' ({r["detail"]})' if r.get('detail') else '')
                     + (f' {r.get("from_item")} -> {r.get("to_item")}' if r.get('from_item') else '')
                     + f': {v["verdict"].upper()} - ' + '; '.join(v['reasons'][:3]))
    return counts, images, artifacts, lines


def inspect(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief'):
    """The 'cuts' view: measures and frames for every cut (or the listed ones) of a project or video.

    cuts: cut numbers as this view lists them (1-based ints), times (floats, seconds), 'f123' frames, '0:12.5'
    times, or dicts {f}/{t}/{n}; a time or frame with no cut there is measured as a join anyway. items: item ids
    (the cuts into or out of them). options: any of DEFAULTS (before, after, context_s, max_cuts, images, ...),
    'thresholds': {key: value} overrides for this call, 'refresh': true, 'settings': timing-store settings.
    detail: 'brief' (verdict, reasons and key numbers per cut) or 'full' (every measure with units and thresholds,
    per-frame series)."""
    t_start = time.time()
    options = dict(options or {})
    st = _settings(options)
    thr = thresholds(options.get('thresholds'))
    refresh = bool(options.get('refresh'))
    warnings, unsupported = [], list(UNSUPPORTED)
    src = str(source)
    kind = 'project' if _is_project(src) else 'video'
    store = _store()
    meta, cut_list = _inspection_source(end_s, kind, options, refresh, src, st, start_s, store, warnings)
    video = meta['video']
    if not video or not os.path.exists(str(video)):
        raise FileNotFoundError(f'no picture to measure for {src} (render {video!r})')
    info = probe(video)
    fps = float(meta.get('fps') or info['fps'])
    frames = int(meta.get('frames') or info['frames'] or round(info['duration'] * fps))
    cut_list = [c for c in cut_list if c.get('kind', 'cut') in st['kinds']]
    if kind == 'video':                        # cuts found in the picture: snap each to its largest change
        for c in cut_list:
            c['snap'] = True
    sel = _select(cut_list, cuts, items, start_s, end_s, fps, frames, warnings)
    allc = cut_list + [c for c in sel if c.get('kind') == 'given']
    _windows(sel, allc, frames)
    unchecked = []
    if len(sel) > int(st['max_cuts']):
        rest = sel[int(st['max_cuts']):]
        unchecked.append({'t0': _r(rest[0]['t']), 't1': _r(rest[-1]['t']), 'f0': rest[0]['f'], 'f1': rest[-1]['f'] + 1,
                          'cuts': len(rest),
                          'why': f'more than max_cuts={st["max_cuts"]} cuts; ask for them by number or range'})
        sel = sel[:int(st['max_cuts'])]
    sound_entries, sound_why = _joins(src, sel, fps, options, warnings)
    import letitedit.footage.shots as shots
    base_key = shots.content_key(video)
    tl = None
    if kind == 'project':
        try:
            import letitedit.timeline.timeline_model as tm
            tl = tm.load(meta.get('project') or _resolve_project(src))
            if int(tl.frames) != frames:
                tl = None
        except Exception:  # noqa: BLE001 - fall back to the render's content key
            tl = None
    rid = _h([VIEW, src, base_key, start_s, end_s, items, cuts, {k: st[k] for k in DEFAULTS if k != 'workers'}, thr,
              CODE_VERSION], 16)
    folder = CACHE / 'results' / rid
    folder.mkdir(parents=True, exist_ok=True)
    jdir = CACHE / 'joins'

    results = _inspect_selected_cuts(base_key, fps, info, jdir, refresh, sel, sound_entries, sound_why, st,
        thr, tl, video, warnings)
    counts, images, artifacts, lines = _inspection_pictures(cuts, folder, results, src, st, warnings)
    clean = [_brief(r) if detail != 'full' else r for r in results]
    checked = [{'t0': _r(start_s or 0.0), 't1': _r(end_s if end_s is not None else frames / fps),
                'f0': int(round((start_s or 0.0) * fps)), 'f1': int(round(end_s * fps)) if end_s is not None
                else frames, 'cuts_measured': len(results)}]
    res = {'view': VIEW, 'tool': 'cut_inspect', 'source': src, 'kind': kind, 'analysed_video': str(video),
           'fps': _r(fps, 4), 'frames': frames, 'cuts_total': len(cut_list), 'cuts': clean,
           'counts': counts, 'text': '\n'.join(lines) or 'no cuts in range', 'images': images,
           'numbers_from': meta.get('numbers_from'), 'cuts_from': meta.get('cuts_from'), 'thresholds': thr,
           'options_used': dict({k: st[k] for k in DEFAULTS if k not in ('detect', 'workers')}, refresh=refresh,
                                thresholds=options.get('thresholds') or {}),
           'options_doc': OPTIONS_DOC, 'units': UNITS,
           'method': __doc__.split('What is measured')[1].split('Images:')[0].strip(' :\n') if __doc__ else '',
           'cached_cuts': sum(1 for r in results if r.get('cached')),
           'result_folder': str(folder), 'seconds': _r(time.time() - t_start, 2)}
    sig = meta.get('sig')
    try:
        import letitedit.timing.timing_views as timing_views
        base = timing_views.common_fields(source=src, sig=sig, view=VIEW,
                                          inputs=[start_s, end_s, items, cuts, res['options_used'], thr, base_key,
                                                  CODE_VERSION],
                                          checked_ranges=checked, unchecked_ranges=unchecked, warnings=warnings,
                                          unsupported=unsupported, preview_artifacts=artifacts)
    except Exception:  # noqa: BLE001 - registry not present: the same fields here
        base = {'schema_version': SCHEMA_VERSION, 'result_id': rid, 'project_revision': None,
                'source_fingerprints': {}, 'checked_ranges': checked, 'unchecked_ranges': unchecked,
                'warnings': warnings, 'unsupported': unsupported, 'preview_artifacts': artifacts, 'changes': []}
    if sig:
        base['checked_ranges'] = checked
        base['unchecked_ranges'] = list(sig.get('unchecked_ranges') or []) + unchecked
    res.update(base)
    if kind == 'project' and not res.get('project_revision'):
        res['project_revision'] = meta.get('revision')
    if not res.get('source_fingerprints'):
        res['source_fingerprints'] = {str(video): base_key}
    _write_json(folder / 'result.json', dict(res, cuts=results))
    res['result_file'] = str(folder / 'result.json')
    return res


UNITS = {'speed': 'diag/s: frame diagonals per second, 95th percentile of the camera-compensated optical flow at '
                  '256 px (subject speed)', 'energy': 'diag/s, mean of the same flow',
         'eye_trace.jump': 'frame diagonals; dx in frame widths, dy in heights; x, y in 0-1 (left/top = 0)',
         'direction': 'degrees, 0 = screen right, 90 = up, 180 = left, -90 = down',
         'framing_sim': 'NCC -1..1 after the best camera compensation (shots.measure_pair)',
         'layout_sim': 'NCC of 1/8-size blurred thumbnails', 'luma': '0-255 mean',
         'face_h': 'face height as a share of the frame height', 'frames': 'frames at the edit frame rate'}

UNSUPPORTED = [
    'emotion and story (Murch\'s first two criteria) are not measured: judge them from the story plan',
    'the attention point is a model (faces, saliency, motion, centre bias), not eye tracking',
    'screen direction across the 180-degree line is only approximated (motion direction, face facing)',
    'picture-in-picture and split screens: only the topmost full picture is followed',
    'speed-ramped clips and freeze frames are measured as they appear in the render',
    'beats and music: see the sync view; words and pauses at the cut: see the speech and joins views',
]


def _brief(r):
    out = {k: r.get(k) for k in ('n', 'f', 't', 'kind', 'from_item', 'to_item', 'from_clip', 'to_clip', 'image',
                                 'error') if r.get(k) is not None}
    v = r['verdict']
    out['verdict'] = v['verdict']
    out['reasons'] = v['reasons']
    if v.get('masks'):
        out['masks'] = v['masks']
    m = r.get('measures')
    if m:
        rh, ey, sd, sp, ex = m['rhythm'], m['eye_trace'], m['screen_direction'], m['space'], m['extra']
        out['rhythm'] = {k: rh.get(k) for k in ('a_end_speed', 'b_start_speed', 'post_motion', 'cut_on_action',
                                                 'action_share_before_cut')}
        out['rhythm']['a_phase'] = rh['a_phase'].get('phase')
        out['rhythm']['b_phase'] = rh['b_phase'].get('phase')
        out['eye_trace'] = {'jump': ey.get('jump'), 'a': [ey['a'].get('x'), ey['a'].get('y'), ey['a'].get('basis')],
                            'b': [ey['b'].get('x'), ey['b'].get('y'), ey['b'].get('basis')]}
        out['screen_direction'] = {'a': sd.get('a_dir'), 'b': sd.get('b_dir'), 'angle_change': sd.get('angle_change'),
                                   'camera': [sd['camera_a']['label'], sd['camera_b']['label']],
                                   'subject_side': [sd.get('subject_a_side'), sd.get('subject_b_side')]}
        out['space'] = {k: sp.get(k) for k in ('framing_sim', 'layout_sim', 'reframe_zoom', 'size_a', 'size_b',
                                               'size_ratio', 'same_person', 'jump_cut', 'punch_in', 'scene_change')}
        out['extra'] = {k: ex.get(k) for k in ('luma_jump', 'colour_shift_de', 'shot_a_frames', 'shot_b_frames')}
    out['sound'] = sound_brief(r.get('sound'))
    return out


def _full(r):
    out = {k: v for k, v in r.items() if not k.startswith('_') and k not in ('measures',)}
    if r.get('measures'):
        out['measures'] = {k: v for k, v in r['measures'].items() if not k.startswith('_')}
    return _jsonable(out)


def view(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief'):
    """The 'cuts' view for timing_views / letitedit_timing (see inspect)."""
    return inspect(source, start_s, end_s, items, cuts, options, detail)


def register():
    """Register the 'cuts' view with timing_views (done at import when timing_views is present)."""
    import letitedit.timing.timing_views as timing_views
    timing_views.register_view(VIEW, view, SUMMARY)
    return True


try:
    import letitedit.timing.timing_views as _tv
    _tv.register_view(VIEW, view, SUMMARY)
    REGISTERED = True
except Exception:  # noqa: BLE001 - registry not present yet
    REGISTERED = False


# ------------------------------------------------------------------ command line

def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='Inspect the cuts of a project or video (the timing layer cuts view).')
    ap.add_argument('source')
    ap.add_argument('--cuts', default=None, help='comma list: cut numbers, times (12.5), frames (f372)')
    ap.add_argument('--start', type=float, default=None)
    ap.add_argument('--end', type=float, default=None)
    ap.add_argument('--detail', default='brief')
    ap.add_argument('--images', default='auto')
    a = ap.parse_args(argv)
    cuts = None
    if a.cuts:
        cuts = []
        for x in a.cuts.split(','):
            x = x.strip()
            cuts.append(int(x) if x.isdigit() else float(x) if re.fullmatch(r'\d+\.\d*', x) else x)
    res = inspect(a.source, a.start, a.end, None, cuts, {'images': a.images}, a.detail)
    print(res['text'])
    print('images:', *res['images'], sep='\n  ')
    print('warnings:', res['warnings'])
    print('result:', res['result_folder'], f'{res["seconds"]} s')


if __name__ == '__main__':
    _main()
