"""Exact ranges for what you look for in footage: start and end frames, previews, stable ids (letitedit_find_ranges).

    find(query | example | around | range_ids, files, ...) -> result dict (see find's docstring)
    compact(result, detail) -> the short form a tool returns
    job(ctx), submit(inputs) -> background job ('range_search:job' in jobs.py)

How a range is found (every number is in `settings`, and each range says how each of its edges was set):

1. Coarse: the picture index of index_tools (OpenCLIP ViT-B-32, the same index letitedit_search uses, cached per file)
   at `every_s` (default 0.5 s, exact frames on that grid) is scored against the query (CLIP text) or an example
   frame. Local peaks per file, at least `min_gap_s` apart, best first: the `candidates` best are refined.
2. Dense: `window_s` either side of each peak is decoded once and scored at `refine_fps` (default 10 per second)
   with the same model and views. The range is the run of samples around the peak whose (3-sample median) score
   stays at or above baseline + `level` x (peak - baseline); baseline = the window's 20th percentile (or the file's
   median when lower). Edges fall between samples by linear interpolation. A range still high at the window edge
   is followed up to `max_len_s`.
3. Motion: the frames of the window are measured by shots.features (camera move estimated and removed; residual
   motion per cell). Where the motion inside the range clearly exceeds the motion just outside it, an edge moves
   to the motion onset / end within `snap_motion_s` ('motion onset' / 'motion end'); a burst of movement within
   `lead_in_s` before a still range (the move that makes the picture, e.g. an arm going up) starts it ('motion
   lead-in'). Motion is never followed across a cut. With edges='motion' the range is instead the burst of
   subject movement at the matching moment ('movement').
4. Cuts: shot boundaries from shots.detect (camera moves do not count). A cut inside a range splits it (the part
   with the peak is kept); an edge within `snap_cut_s` of a cut moves onto it.
5. Frames: edges are put on the file's frame grid (nominal rate). Overlapping ranges in one file are merged (the
   one with the higher peak stays; the others are listed in `merged`); ranges of one file at most `join_gap_s`
   apart (the score dipped briefly) are joined.

A range's id is a hash of the source content key, its first and last frame and the query, so the same footage and
query give the same id on every call (and letitedit_find_ranges(range_ids=[...]) returns stored ranges by id).
Nothing is edited: `changes` is always []; each range carries an edit_item {clip, in, out} for
letitedit_timeline_apply.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

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

SCHEMA_VERSION = 1
ALGO_VERSION = 1
TOOL = 'letitedit_find_ranges'
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
OUT = CACHE / 'range-search'
DENSE = OUT / 'dense'
STORE = OUT / 'ranges'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

DEFAULTS = {
    'count': 8,               # ranges returned
    'candidates': 16,         # coarse peaks refined (at least count)
    'every_s': 0.5,           # coarse picture index spacing (shared cache with letitedit_search at the same spacing)
    'frames': 'exact',        # coarse sampling: 'exact' (frames on the every_s grid), 'keyframes', 'auto'
    'min_gap_s': 1.5,         # coarse peaks in one file at least this far apart
    'window_s': 2.5,          # refinement looks this far either side of a coarse peak
    'refine_fps': 10.0,       # dense picture samples per second inside the window
    'level': 0.5,             # range edges: score falls under baseline + level x (peak - baseline)
    'snap_motion_s': 0.35,    # an edge moves to a motion onset / end this close
    'motion_ratio': 1.4,      # ... when motion inside the range is this many times the motion outside (+ 0.8)
    'snap_cut_s': 0.25,       # an edge this close to a cut moves onto it
    'min_len_s': 0.2,         # shorter ranges grow to this around the peak
    'max_len_s': 10.0,        # a range is followed at most this long
    'merge_iou': 0.3,         # ranges in one file overlapping this much (or containing the other's peak) merge
    'join_gap_s': 0.6,        # ranges of one file this close (a short dip of the score) join into one
    'lead_in_s': 0.8,         # a burst of movement up to this long just before a still range starts it ('lead-in')
    'edges': 'picture',       # 'picture': the range is where the picture matches; 'motion': the burst of subject
                              # movement there (camera move removed) - a reach, a jump, a turn of the hand
    'motion_fps': 30.0,       # motion / cut analysis rate inside windows (shots.features max_fps)
    'frame_height': 200,      # preview tile height (px)
    'clip_height': 360,       # preview clip height (px)
    'clip_pad_s': 0.5,        # preview clips show this much before and after the range
}
PREVIEWS = ('sheets', 'clips', 'both', 'none')
UNSUPPORTED = [
    'things too small to see in a 224-pixel picture (a screw head in a wide shot): the picture model cannot score them',
    'what is only heard or said: letitedit_search with kind="speech" or kind="sound" finds those, and its moments can '
    'come back here as around=[{file, start, end}] for frame edges',
    'counting and order ("the second hit", "after he puts the tool down") and negation ("without gloves")',
    'off-screen or hidden actions, and actions the camera only shows from behind an obstacle',
    'an action shorter than 1/refine_fps whose picture barely changes (only motion snapping can place it)',
    'a range of a picture that never changes (a still): its edges come from cuts or the window, not from the action',
]


# ------------------------------------------------------------------ small helpers

def _it():
    import letitedit.footage.index_tools as index_tools
    return index_tools


def _shots():
    import letitedit.footage.shots as shots
    return shots


def _h(obj, n=12):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:n]


def _norm_query(q):
    return re.sub(r'\s+', ' ', str(q or '').strip().lower())


def _clock(s):
    s = max(0.0, float(s))
    return f'{int(s // 60)}:{s % 60:05.2f}'


def _settings(given):
    st = dict(DEFAULTS)
    used_default = []
    for k in DEFAULTS:
        if given.get(k) is not None:
            st[k] = given[k]
        else:
            used_default.append(k)
    st['candidates'] = max(int(st['candidates']), int(st['count']))
    return st, used_default


def _ask(op, **req):
    """index_tools' model worker; a worker started before 'clip_window' existed is restarted once."""
    it = _it()
    it.INDEX_OP_MODELS.setdefault('clip_window', ['clip-vit-b-32'])
    try:
        return it._worker.ask(op, **req)
    except RuntimeError as e:
        if op in str(e) and ('KeyError' in str(e) or 'unknown' in str(e).lower()):
            it.stop_worker()
            return it._worker.ask(op, **req)
        raise


def fingerprint(path):
    sh = _shots()
    st = os.stat(path)
    info = sh.probe(path)
    return {'file': str(path), 'content_key': sh.content_key(path), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns,
            'duration': round(info['duration'], 3), 'fps': round(info['fps'], 5),
            'start_time': round(info.get('start_time') or 0.0, 5)}


def range_id(content_key, start_frame, end_frame, qkey):
    return 'r' + hashlib.sha1(f'{content_key}|{int(start_frame)}|{int(end_frame)}|{qkey}'.encode()).hexdigest()[:12]


# ------------------------------------------------------------------ query

def _query_vector(query, example, files, every_s, modes):
    it = _it()
    if query:
        r = _ask('clip_text', texts=[str(query)])
        return np.array(r['emb'][0], dtype=np.float32), {'compared_with': 'text (CLIP text encoder)'}
    q = it._query_vectors(['picture'], None, example, files, every_s, modes, 2.0, 1.0, 'both')
    if 'picture' not in q or q['picture'] is None:
        raise ValueError('the example has no picture to compare with')
    v = np.asarray(q['picture'], dtype=np.float32)
    v = v / (np.linalg.norm(v) + 1e-9)
    return v, {'compared_with': 'example ' + ('frame' if 'at' in example else 'span') + ' (CLIP image)'}


# ------------------------------------------------------------------ coarse

def _coarse(scope, qvec, st, rng, warnings):
    """Per-file series of the coarse index scores and the best local peaks across files."""
    it = _it()
    every = float(st['every_s'])
    b = it.build_video_index(scope, every, st['frames'])
    for e in b.get('errors') or []:
        warnings.append(f"picture index failed for {Path(e.get('video', '?')).name}: {e.get('error')}"[:300])
    modes = b['modes']
    cands = it._picture_candidates(scope, qvec, every, modes, rng)
    series = {}
    for c in cands:
        series.setdefault(c['file'], []).append((c['at'], c['raw'], c['matched'].get('view')))
    peaks = []
    stats = {}
    for f, rows in series.items():
        rows.sort()
        at = np.array([r[0] for r in rows])
        raw = np.array([r[1] for r in rows])
        stats[f] = {'median': float(np.median(raw)), 'std': float(raw.std()) or 1e-3, 'samples': len(raw),
                    'p90': float(np.percentile(raw, 90))}
        for i in range(len(raw)):
            left = raw[i - 1] if i > 0 else -9
            right = raw[i + 1] if i + 1 < len(raw) else -9
            if raw[i] >= left and raw[i] >= right:
                peaks.append({'file': f, 'at': float(at[i]), 'raw': float(raw[i]), 'view': rows[i][2]})
    peaks.sort(key=lambda p: -p['raw'])
    kept, per = [], {}
    gap = float(st['min_gap_s'])
    for p in peaks:
        if any(abs(p['at'] - k['at']) < gap for k in per.get(p['file'], [])):
            continue
        per.setdefault(p['file'], []).append(p)
        kept.append(p)
    for r, p in enumerate(kept):
        p['rank'] = r + 1
    return kept, stats, b, modes, series


# ------------------------------------------------------------------ dense window scores

def _dense(file, a, b, st, qvec, info):
    """(times, scores, views) of the frames of file[a:b] at about refine_fps (cached per content and window)."""
    it, sh = _it(), _shots()
    pinfo = it._probe(file)
    w, h = it._dims(pinfo, short=224)
    step = max(1, int(round(info['fps'] / float(st['refine_fps']))))
    key = sh.content_key(file)
    a, b = round(max(0.0, a), 3), round(min(info['duration'], b), 3)
    out = DENSE / f'{key}-{a:.3f}-{b:.3f}-s{step}-{w}x{h}-v1.npz'
    if not out.exists():
        DENSE.mkdir(parents=True, exist_ok=True)
        _ask('clip_window', ffmpeg=str(it.FFMPEG), video=str(file), start=a, dur=max(0.05, b - a), step=step,
             out_w=w, out_h=h, out=str(out))
    with np.load(out, allow_pickle=False) as z:
        times, emb, views = z['times'], z['emb'].astype(np.float32), [str(v) for v in z['views']]
    if len(times) == 0:
        return np.zeros(0), np.zeros(0), []
    sims = emb @ qvec
    return times, sims.max(axis=1), [views[k] for k in sims.argmax(axis=1)]


def _med3(x):
    if len(x) < 3:
        return np.asarray(x, dtype=np.float64)
    y = np.array(x, dtype=np.float64)
    out = y.copy()
    out[1:-1] = np.median(np.stack([y[:-2], y[1:-1], y[2:]]), axis=0)
    return out


# ------------------------------------------------------------------ motion and cuts inside a window

def _motion(file, a, b, st):
    """shots.features of file[a:b] at motion_fps (cuts, camera move, residual motion per cell) and the cuts."""
    sh = _shots()
    fst = {'max_fps': float(st['motion_fps']), 'workers': 1}
    try:
        res = sh.detect(file, start=max(0.0, a), end=b, settings=fst)
        f = sh.features(file, start=max(0.0, a), end=b, settings=fst)
    except Exception as e:  # noqa: BLE001
        return None, [], f'{type(e).__name__}: {e}'
    g = np.asarray(f['grid'], dtype=np.float64)
    if g.size:
        top = np.sort(g, axis=1)[:, -4:].mean(axis=1)          # the 4 most active cells: local actions count
    else:
        top = np.zeros(len(f['t']))
    cam = np.hypot(np.nan_to_num(f['dx']), np.nan_to_num(f['dy'])) * (sh.probe(file)['fps'] / f['step'])
    m = {'t': np.asarray(f['t'], dtype=np.float64), 'act': _med3(top), 'cam': cam}
    cuts = [c for c in res['cuts'] if c['kind'] in ('cut', 'dissolve', 'fade')]
    return m, cuts, None


def _level(x):
    return float(np.median(x)) if len(x) else 0.0


def _snap_motion(m, start, end, st, cuts=()):
    """(start, end, start_basis, end_basis, motion components) after moving edges to motion onset / end (and a
    lead-in); motion is never followed across a cut (the frames of a cut are not movement)."""
    if m is None or len(m['t']) < 4:
        return start, end, None, None, {'available': False}
    t, act = m['t'], m['act'].copy()
    for c in cuts or ():                      # a cut's frame difference is not movement
        ct = float(c['t'] if isinstance(c, dict) else c)
        act[np.abs(t - ct) <= 0.05] = 0.0
    last_cut = max([float(c['t'] if isinstance(c, dict) else c) for c in cuts or () if
                    float(c['t'] if isinstance(c, dict) else c) <= start] or [-1e9])
    snap = float(st['snap_motion_s'])
    ratio = float(st['motion_ratio'])
    inside = act[(t >= start) & (t <= end)]
    before = act[(t >= start - 0.9) & (t < start - 0.15)]
    after = act[(t > end + 0.15) & (t <= end + 0.9)]
    a_in, a_b, a_a = _level(inside), _level(before), _level(after)
    sb = eb = None
    if len(inside) >= 2 and len(before) >= 2 and a_in >= ratio * a_b + 0.8:
        thr = a_b + 0.5 * (a_in - a_b)
        sel = np.flatnonzero((t >= start - snap) & (t <= min(end, start + snap)) & (act >= thr))
        if sel.size:
            start, sb = float(t[sel[0]]), 'motion onset'
    if len(inside) >= 2 and len(after) >= 2 and a_in >= ratio * a_a + 0.8:
        thr = a_a + 0.5 * (a_in - a_a)
        sel = np.flatnonzero((t <= end + snap) & (t >= max(start, end - snap)) & (act >= thr))
        if sel.size:
            end, eb = float(t[sel[-1]]), 'motion end'
    # lead-in: a burst of movement just before a still range is the move that makes it (an arm going up, a hand
    # reaching): the range starts where that burst starts
    lead = float(st.get('lead_in_s') or 0)
    if sb is None and lead > 0 and len(inside) >= 2:
        win = (t >= max(start - lead, last_cut + 0.1)) & (t < start)
        quiet = act[(t >= max(start - lead - 0.8, last_cut + 0.1)) & (t < start - lead)]
        if win.sum() >= 3:
            burst = float(np.max(act[win]))
            q = _level(quiet) if len(quiet) >= 2 else _level(act[win])
            if burst >= max(2.0 * a_in, a_in + 3.0) and burst >= ratio * q + 0.8:
                thr = q + 0.5 * (burst - q)
                sel = np.flatnonzero(win & (act >= thr))
                if sel.size:
                    start, sb = float(t[sel[0]]), 'motion lead-in'
    cam_in = m['cam'][(t >= start) & (t <= end)]
    comp = {'available': True, 'inside': round(a_in, 2), 'before': round(a_b, 2), 'after': round(a_a, 2),
            'ratio_before': round(a_in / max(a_b, 0.5), 2), 'ratio_after': round(a_in / max(a_a, 0.5), 2),
            'camera_speed': round(float(np.median(cam_in)), 3) if len(cam_in) else None,
            'what': 'residual motion after the camera move is removed (mean abs change of the 4 busiest of 16 cells, '
                    '0-255); camera_speed in frame widths per second'}
    return start, end, sb, eb, comp


# ------------------------------------------------------------------ one candidate

def _range_from_profile(times, prof, hint, every, level, file_med):
    """(start, end, peak index, baseline, threshold, touched_left, touched_right) from a smoothed score profile."""
    n = len(times)
    near = np.flatnonzero(np.abs(times - hint) <= max(every, 0.25) + 1e-6)
    if near.size:
        top = near[prof[near] >= prof[near].max() - 1e-6]          # ties: the sample nearest the coarse hit
        p = int(top[np.argmin(np.abs(times[top] - hint))])
    else:
        p = int(np.argmax(prof))
    base = min(float(np.percentile(prof, 20)), file_med) if file_med is not None else float(np.percentile(prof, 20))
    peak = float(prof[p])
    thr = base + level * (peak - base)
    a = p
    while a - 1 >= 0 and (prof[a - 1] >= thr or (a - 2 >= 0 and prof[a - 2] >= thr and prof[a - 1] >= thr - 0.5 *
                                                   (thr - base))):
        a -= 1
    b = p
    while b + 1 < n and (prof[b + 1] >= thr or (b + 2 < n and prof[b + 2] >= thr and prof[b + 1] >= thr - 0.5 *
                                                (thr - base))):
        b += 1

    def cross(i_in, i_out):
        y0, y1 = prof[i_in], prof[i_out]
        if y0 == y1:
            return float(times[i_in])
        f = (y0 - thr) / (y0 - y1)
        return float(times[i_in] + min(1.0, max(0.0, f)) * (times[i_out] - times[i_in]))
    s = cross(a, a - 1) if a - 1 >= 0 else float(times[a])
    e = cross(b, b + 1) if b + 1 < n else float(times[b])
    return s, e, p, base, thr, a == 0, b == n - 1


def _refine_picture(c, st, qvec, stats, info):
    """Stage 1 (GPU): dense picture scores around a coarse peak and the range they give (no motion yet)."""
    file = c['file']
    W = float(st['window_s'])
    dur = info['duration']
    a, b = max(0.0, c['at'] - W), min(dur, c['at'] + W)
    times, sc, views = _dense(file, a, b, st, qvec, info)
    if len(times) < 3:
        return None
    file_med = stats.get(file, {}).get('median')
    # follow a range that is still high at the window edge
    for _ in range(int(math.ceil(float(st['max_len_s']) / W))):
        prof = _med3(sc)
        s, e, p, base, thr, tl, tr = _range_from_profile(times, prof, c['at'], float(st['every_s']),
                                                         float(st['level']), file_med)
        grow = False
        if tl and a > 0 and (e - s) < float(st['max_len_s']):
            na = max(0.0, a - W)
            t2, s2, v2 = _dense(file, na, a, st, qvec, info)
            keep = t2 < times[0] - 1e-4
            times, sc = np.concatenate([t2[keep], times]), np.concatenate([s2[keep], sc])
            views = [v for v, k in zip(v2, keep) if k] + views
            a, grow = na, True
        if tr and b < dur and (e - s) < float(st['max_len_s']):
            nb = min(dur, b + W)
            t2, s2, v2 = _dense(file, b, nb, st, qvec, info)
            keep = t2 > times[-1] + 1e-4
            times, sc = np.concatenate([times, t2[keep]]), np.concatenate([sc, s2[keep]])
            views = views + [v for v, k in zip(v2, keep) if k]
            b, grow = nb, True
        if not grow:
            break
    prof = _med3(sc)
    s, e, p, base, thr, tl, tr = _range_from_profile(times, prof, c['at'], float(st['every_s']), float(st['level']),
                                                     file_med)
    stt = stats.get(file, {})
    peak_t, peak_s = float(times[p]), float(sc[p])
    raw = c.get('raw')
    return {'file': file, 'start_s': s, 'end_s': e, 'peak_t': peak_t, 'peak_view': views[p] if views else None,
            'window': (a, b), 'times': times, 'prof': prof,
            'sb': 'window edge' if tl else 'picture score', 'eb': 'window edge' if tr else 'picture score',
            'picture': {'peak': round(peak_s, 4),
                        'coarse': None if raw is None or raw != raw else round(float(raw), 4),
                        'z_file': round((peak_s - stt.get('median', 0.0)) / max(stt.get('std', 1e-3), 1e-3), 2)
                        if stt else None,
                        'prominence': round(peak_s - base, 4), 'baseline': round(base, 4),
                        'threshold': round(thr, 4), 'coarse_rank': c['rank'],
                        'what': 'CLIP cosine similarity of the frame (best of 4 views) with the query; z_file: '
                                'standard deviations above the median of the file (coarse); prominence: peak - '
                                'baseline'},
            'given': c.get('given')}


def _motion_burst(m, s, e, a, b, cuts, st):
    """The burst of subject movement (camera move removed) at the matching picture: the strongest movement from
    lead_in_s before the picture range to its end, grown while it stays above quiet + 40% of (peak - quiet).
    Returns (start, end, info) or None when nothing clearly moves."""
    if m is None or len(m['t']) < 6:
        return None
    t, act = m['t'], m['act'].copy()
    for c in cuts or ():
        act[np.abs(t - float(c['t'])) <= 0.05] = 0.0
    lead = float(st.get('lead_in_s') or 0.8)
    last_cut = max([float(c['t']) for c in cuts or () if float(c['t']) <= s] or [-1e9])
    first_cut = min([float(c['t']) for c in cuts or () if float(c['t']) > s] or [1e9])
    region = np.flatnonzero((t >= max(a, s - lead, last_cut + 0.1)) & (t <= min(b, e, first_cut - 0.05)))
    if region.size < 3:
        return None
    q = float(np.percentile(act[(t >= a) & (t <= b)], 20))
    k = int(region[np.argmax(act[region])])
    peak = float(act[k])
    if peak < q + 3.0 or peak < 1.5 * q:
        return None
    thr = q + 0.4 * (peak - q)
    i = j = k
    gap = 2
    while i - 1 >= 0 and (act[i - 1] >= thr or (i - gap >= 0 and act[max(0, i - gap):i].max() >= thr)):
        i -= 1
    while j + 1 < len(t) and (act[j + 1] >= thr or (j + gap < len(t) and act[j + 1:j + 1 + gap].max() >= thr)):
        j += 1
    return float(t[i]), float(t[j]), {'peak': round(peak, 2), 'quiet': round(q, 2), 'at': round(float(t[k]), 3)}


def _join(kept, gap):
    """Join ranges of one file whose gap is at most `gap` seconds; the one with the higher peak keeps its peak and
    picture numbers, the window and profile become the union, the other is listed in merged (joined: True)."""
    by_file = {}
    for r in kept:
        by_file.setdefault(r['file'], []).append(r)
    out = []
    for f, rs_ in by_file.items():
        rs_.sort(key=lambda r: r['start_s'])
        cur = rs_[0]
        for nx in rs_[1:]:
            if nx['start_s'] - cur['end_s'] <= gap:
                lead, other = (cur, nx) if cur['picture']['peak'] >= nx['picture']['peak'] else (nx, cur)
                t = np.concatenate([cur['times'], nx['times']])
                pr = np.concatenate([cur['prof'], nx['prof']])
                order = np.argsort(t, kind='stable')
                t, pr = t[order], pr[order]
                uniq = np.concatenate([[True], np.diff(t) > 1e-4])
                joined = dict(lead)
                joined.update(start_s=min(cur['start_s'], nx['start_s']), end_s=max(cur['end_s'], nx['end_s']),
                              window=(min(cur['window'][0], nx['window'][0]), max(cur['window'][1], nx['window'][1])),
                              times=t[uniq], prof=pr[uniq],
                              sb=cur['sb'] if cur['start_s'] <= nx['start_s'] else nx['sb'],
                              eb=nx['eb'] if nx['end_s'] >= cur['end_s'] else cur['eb'],
                              merged=lead.get('merged', []) + other.get('merged', []) + [
                                  {'peak_at': round(other['peak_t'], 3), 'start': round(other['start_s'], 3),
                                   'end': round(other['end_s'], 3), 'peak': other['picture']['peak'],
                                   'joined': True}])
                cur = joined
            else:
                out.append(cur)
                cur = nx
        out.append(cur)
    out.sort(key=lambda r: -r['picture']['peak'])
    return out


def _refine_edges(rr, st, info, motion_cache, warnings):
    """Stage 2 (CPU): motion onset / end and cuts move the edges; the final range record."""
    file = rr['file']
    a, b = rr['window']
    s, e, peak_t = rr['start_s'], rr['end_s'], rr['peak_t']
    sb, eb = rr['sb'], rr['eb']
    times, prof = rr['times'], rr['prof']
    dur = info['duration']
    mk = (file, round(a, 2), round(b, 2))
    if mk not in motion_cache:
        motion_cache[mk] = _motion(file, a - 0.6, b + 0.6, st)
    m, cuts, err = motion_cache[mk]
    if err:
        warnings.append(f'{Path(file).name} {_clock(a)}-{_clock(b)}: motion/cut analysis failed ({err})'[:300])
    s2, e2, msb, meb, mcomp = _snap_motion(m, s, e, st, cuts)
    if str(st.get('edges') or 'picture') == 'motion':
        mv = _motion_burst(m, s, e, a, b, cuts, st)
        if mv is not None:
            s, e, sb, eb = mv[0], mv[1], 'movement', 'movement'
            mcomp = dict(mcomp, burst=mv[2])
        else:
            if msb:
                s, sb = s2, msb
            if meb:
                e, eb = e2, meb
            warnings.append(f'{Path(file).name} {_clock(s)}: edges="motion" but no clear movement there; picture '
                            'edges kept')
    else:
        if msb:
            s, sb = s2, msb
        if meb:
            e, eb = e2, meb
    # cuts: split at a cut inside; snap an edge onto a nearby cut
    cut_info = {'inside_split': [], 'snapped': []}
    snap_c = float(st['snap_cut_s'])
    for cut in cuts:
        ct = float(cut['t'])
        if s + 1e-3 < ct <= e:
            cut_info['inside_split'].append(round(ct, 3))
            if peak_t >= ct:
                s, sb = ct, 'cut'
            else:
                e, eb = ct - 1.0 / info['fps'], 'cut'
    for cut in cuts:
        ct = float(cut['t'])
        if 0 < s - ct <= snap_c:
            s, sb = ct, 'cut'
            cut_info['snapped'].append(['start', round(ct, 3)])
        if 0 <= ct - e <= snap_c:
            e, eb = ct - 1.0 / info['fps'], 'cut'
            cut_info['snapped'].append(['end', round(ct, 3)])
    # minimum length around the peak, file bounds
    if e - s < float(st['min_len_s']):
        half = float(st['min_len_s']) / 2
        s, e = min(s, peak_t - half), max(e, peak_t + half)
    s, e = max(0.0, s), min(dur - 1.0 / info['fps'], e)

    def slope(t0):
        k = int(np.argmin(np.abs(times - t0)))
        lo, hi = max(0, k - 1), min(len(times) - 1, k + 1)
        return round(float(abs(prof[hi] - prof[lo]) / max(1e-3, times[hi] - times[lo])), 3)
    out = {k: v for k, v in rr.items() if k not in ('times', 'prof', 'sb', 'eb', 'window')}
    out.update(start_s=s, end_s=e,
               edges={'start': {'basis': sb, 'score_slope_per_s': slope(s)},
                      'end': {'basis': eb, 'score_slope_per_s': slope(e)}},
               motion=mcomp, cuts=cut_info,
               dense={'window': [round(a, 3), round(b, 3)], 'samples': int(len(times)),
                      'profile': [[round(float(t_), 3), round(float(v_), 4)] for t_, v_ in zip(times, prof)]})
    return out


# ------------------------------------------------------------------ speech words inside a range

def _words_in(file, a, b):
    try:
        import letitedit.footage.speech as speech
        ws = speech.cached_words(str(file))
    except Exception:  # noqa: BLE001
        ws = None
    if ws is None:
        return {'available': False, 'what': 'no cached transcript (letitedit_words or letitedit_transcript makes one)'}
    inside = [w for w in ws if float(w['e']) > a and float(w['s']) < b]
    return {'available': True, 'words': len(inside), 'text': ' '.join(str(w['w']) for w in inside)[:200],
            'silent': not inside}


# ------------------------------------------------------------------ previews

def _font(size, bold=False):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf' if bold else r'C:\Windows\Fonts\arial.ttf', size)
    except OSError:
        return ImageFont.load_default()


def _grab(file, t, out, height):
    it = _it()
    return it._grab(file, t, out, height)


def _filmstrip(r, folder, height, label_extra=''):
    """before | start | peak | end | after tiles of one range as a JPEG."""
    from PIL import Image, ImageDraw
    fps = r['fps']
    pts = [('before', max(0.0, r['start'] - 0.5)), ('start', r['start']), ('peak', r['peak_at']),
           ('end', r['end']), ('after', min(r['source_duration'] - 0.01, r['end'] + 0.5))]
    tiles = []
    folder.mkdir(parents=True, exist_ok=True)
    for name, t in pts:
        p = folder / f'{r["range_id"]}-{name}.jpg'
        if not p.exists():
            _grab(r['file'], t, p, height)
        tiles.append((name, t, p))
    ims = []
    for name, t, p in tiles:
        try:
            ims.append(Image.open(p).convert('RGB'))
        except OSError:
            ims.append(None)
    tw = max([im.width for im in ims if im is not None] or [height])
    th = max([im.height for im in ims if im is not None] or [height])
    head = 40
    sheet = Image.new('RGB', (5 * (tw + 6) + 6, th + head + 26), (22, 22, 26))
    d = ImageDraw.Draw(sheet)
    title = f'{r["range_id"]}  {Path(r["file"]).name}  {_clock(r["start"])}-{_clock(r["end"])}  ' \
            f'frames {r["start_frame"]}-{r["end_frame"]}  ({r["duration"]:.2f} s) {label_extra}'
    d.text((6, 4), title[:150], fill=(255, 220, 0), font=_font(14, True))
    d.text((6, 22), f'start: {r["confidence"]["edges"]["start"]["basis"]}   end: '
                    f'{r["confidence"]["edges"]["end"]["basis"]}   peak {r["confidence"]["picture"]["peak"]:.3f}',
           fill=(220, 220, 220), font=_font(12))
    for k, ((name, t, _), im) in enumerate(zip(tiles, ims)):
        x = 6 + k * (tw + 6)
        if im is not None:
            sheet.paste(im, (x + (tw - im.width) // 2, head))
        col = (90, 200, 90) if name in ('start', 'end') else (255, 220, 0) if name == 'peak' else (150, 150, 150)
        if name in ('start', 'end', 'peak'):
            d.rectangle((x - 2, head - 2, x + tw + 1, head + th + 1), outline=col, width=2)
        d.text((x + 2, head + th + 4), f'{name} {_clock(t)} f{int(round((t - r["start_time"]) * fps))}',
               fill=col, font=_font(12))
    out = folder / f'{r["range_id"]}-strip.jpg'
    sheet.save(out, 'JPEG', quality=86)
    return str(out)


def _overview(ranges, out, title, height=150):
    from PIL import Image, ImageDraw
    rows = []
    for r in ranges:
        ims = []
        for name in ('start', 'peak', 'end'):
            p = Path(r['preview']['strip']).with_name(f'{r["range_id"]}-{name}.jpg')
            try:
                im = Image.open(p).convert('RGB')
                im = im.resize((max(1, int(im.width * height / im.height)), height))
            except OSError:
                im = None
            ims.append(im)
        rows.append((r, ims))
    tw = max([im.width for _, ims in rows for im in ims if im is not None] or [height])
    lw = 360
    sheet = Image.new('RGB', (lw + 3 * (tw + 4) + 8, 30 + len(rows) * (height + 8) + 4), (22, 22, 26))
    d = ImageDraw.Draw(sheet)
    d.text((6, 6), title[:160], fill=(255, 220, 0), font=_font(15, True))
    for k, (r, ims) in enumerate(rows):
        y = 30 + k * (height + 8)
        c = r['confidence']
        lines = [f'{k + 1}. {r["range_id"]}', f'{Path(r["file"]).name}',
                 f'{_clock(r["start"])} - {_clock(r["end"])}  ({r["duration"]:.2f} s)',
                 f'frames {r["start_frame"]}-{r["end_frame"]}',
                 f'peak {c["picture"]["peak"]:.3f}  z {c["picture"]["z_file"]}  rank {c["picture"]["coarse_rank"]}',
                 f'edges: {c["edges"]["start"]["basis"]} / {c["edges"]["end"]["basis"]}']
        if c.get('speech', {}).get('available'):
            lines.append('silent' if c['speech']['silent'] else f'words: {c["speech"]["text"][:40]}')
        for j, ln in enumerate(lines):
            d.text((6, y + j * 16), ln[:52], fill=(255, 220, 0) if j == 0 else (225, 225, 225),
                   font=_font(13, j == 0))
        for j, im in enumerate(ims):
            x = lw + 4 + j * (tw + 4)
            if im is not None:
                sheet.paste(im, (x, y))
    sheet.save(out, 'JPEG', quality=85)
    return str(out)


def _clip(r, folder, st):
    it = _it()
    out = folder / f'{r["range_id"]}.mp4'
    if out.exists():
        return str(out)
    a = max(0.0, r['start'] - float(st['clip_pad_s']))
    b = min(r['source_duration'], r['end'] + 1.0 / r['fps'] + float(st['clip_pad_s']))
    h = int(st['clip_height'])
    cmd = [str(it.FFMPEG), '-v', 'error', '-y', '-ss', f'{a:.3f}', '-i', r['file'], '-t', f'{b - a:.3f}',
           '-vf', f'scale=-2:{h}', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', str(out)]
    p = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    return str(out) if p.returncode == 0 and out.exists() else None


# ------------------------------------------------------------------ the tool

def _final(file, rr, info, qkey, fp):
    """Frame grid, id, edit item."""
    fps, st0 = info['fps'], float(info.get('start_time') or 0.0)
    sf = int(round((rr['start_s'] - st0) * fps))
    ef = max(sf, int(round((rr['end_s'] - st0) * fps)))
    nmax = int(math.floor((info['duration']) * fps)) - 1
    ef = min(ef, max(sf, nmax))
    start, end = st0 + sf / fps, st0 + ef / fps
    rid = range_id(fp['content_key'], sf, ef, qkey)
    return {'range_id': rid, 'file': file, 'start': round(start, 4), 'end': round(end, 4),
            'start_frame': sf, 'end_frame': ef, 'duration': round((ef - sf + 1) / fps, 4),
            'peak_at': round(rr['peak_t'], 4), 'peak_frame': int(round((rr['peak_t'] - st0) * fps)),
            'fps': round(fps, 5), 'start_time': st0, 'source_duration': round(info['duration'], 4),
            'edit_item': {'clip': file, 'in': round(start, 4), 'out': round(st0 + (ef + 1) / fps, 4)}}


def _load_stored(ids):
    out, missing = [], []
    for rid in ids:
        p = STORE / f'{rid}.json'
        if p.exists():
            out.append(json.loads(p.read_text(encoding='utf-8-sig')))
        else:
            missing.append(rid)
    return out, missing


def _store(r):
    STORE.mkdir(parents=True, exist_ok=True)
    p = STORE / f'{r["range_id"]}.json'
    tmp = p.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(r, default=str), encoding='utf-8')
    os.replace(tmp, p)


def _find_scope(files, it, ranges, sh, unchecked):
    flist = it._media_files(files)
    vids = []
    for f in flist:
        try:
            if it._pc().kind(f) == 'video':
                vids.append(f)
            else:
                unchecked.append({'file': f, 'ranges': None, 'reason': 'no picture (audio file)'})
        except Exception as e:  # noqa: BLE001
            unchecked.append({'file': f, 'ranges': None, 'reason': f'unreadable ({type(e).__name__})'})
    rng = it._ranges(ranges, vids) if ranges else None
    scope = [f for f in vids if rng is None or f in rng]
    for f in vids:
        if f not in scope:
            unchecked.append({'file': f, 'ranges': None, 'reason': 'outside the given ranges'})
    prints, infos = [], {}
    for f in scope:
        try:
            infos[f] = sh.probe(f)
            prints.append(fingerprint(f))
        except Exception as e:  # noqa: BLE001
            unchecked.append({'file': f, 'ranges': None, 'reason': f'cannot read the video ({type(e).__name__}: {e})'})
    scope = [f for f in scope if f in infos]
    return scope, rng, prints, infos


def _find_candidates(around, example, infos, it, modes, prog, query, rng, scope, st, unchecked, warnings):
    if around:
        cands = []
        for k, a in enumerate(around):
            f = str(Path(a['file']).resolve())
            if f not in infos:
                warnings.append(f'around[{k}]: {a["file"]} is not a readable video in files')
                continue
            at = float(a['at']) if 'at' in a else (float(a['start']) + float(a['end'])) / 2
            cands.append({'file': f, 'at': at, 'raw': float('nan'), 'rank': k + 1, 'view': None,
                          'given': {kk: a[kk] for kk in ('at', 'start', 'end') if kk in a}})
        if query:
            qvec, qinfo = _query_vector(query, None, scope, float(st['every_s']), modes)
        else:
            qvec = None
            qinfo = {'compared_with': 'the picture at each moment given (CLIP image)'}
        stats = {}
        coarse_info = {'mode': 'around', 'moments': len(cands)}
    else:
        if example:
            exf = str(Path(example['file']).resolve())
            if not os.path.exists(exf):
                raise FileNotFoundError(example['file'])
        qvec, qinfo = _query_vector(query, example, scope, float(st['every_s']), modes)
        prog(0.15, 'coarse picture index')
        cands, stats, b, modes, series = _coarse(scope, qvec, st, rng, warnings)
        coarse_info = {'mode': 'search', 'every_s': float(st['every_s']), 'frames': st['frames'],
                       'built': b['built'], 'cached_files': b['cached'], 'build_s': b['build_s'],
                       'peaks': len(cands), 'model': it.PICTURE_MODEL}
        for f in scope:
            if f not in series:
                unchecked.append({'file': f, 'ranges': None, 'reason': 'no picture index (decode failed)'})
        cands = cands[:int(st['candidates'])]
    return cands, qvec, qinfo, stats, coarse_info


def _find_picture_ranges(cands, chk, infos, it, prog, qvec, st, stats, warnings):
    motion_cache, refined = {}, []
    for k, c in enumerate(cands):
        chk()
        prog(0.2 + 0.5 * k / max(1, len(cands)), f'scoring {k + 1}/{len(cands)}')
        info = infos[c['file']]
        q = qvec
        if q is None:                                      # around without a query: the picture at that moment
            pinfo = it._probe(c['file'])
            w, h = it._dims(pinfo, short=224)
            r = _ask('clip_frames', ffmpeg=str(it.FFMPEG), video=c['file'], times=[c['at']], out_w=w, out_h=h)
            if not r['emb'] or r['emb'][0] is None:
                warnings.append(f'{Path(c["file"]).name} @ {_clock(c["at"])}: no picture there')
                continue
            q = np.array(r['emb'][0][0], dtype=np.float32)
            q = q / (np.linalg.norm(q) + 1e-9)
        rr = _refine_picture(c, st, q, stats, info)
        if rr is None:
            warnings.append(f'{Path(c["file"]).name} @ {_clock(c["at"])}: too few frames to refine')
            continue
        refined.append(rr)
    return motion_cache, refined


def _merge_picture_ranges(around, refined, st):
    # merge duplicates (same file, overlapping): the higher peak stays
    refined.sort(key=lambda r: -r['picture']['peak'])
    kept = []
    for r in refined:
        dup = None
        for k in kept:
            if k['file'] != r['file'] or around:
                continue
            inter = max(0.0, min(k['end_s'], r['end_s']) - max(k['start_s'], r['start_s']))
            union = max(k['end_s'], r['end_s']) - min(k['start_s'], r['start_s'])
            if ((union > 0 and inter / union >= float(st['merge_iou'])) or k['start_s'] <= r['peak_t'] <= k['end_s']
                    or r['start_s'] <= k['peak_t'] <= r['end_s']):
                dup = k
                break
        if dup is None:
            r['merged'] = []
            kept.append(r)
        else:
            dup['merged'].append({'peak_at': round(r['peak_t'], 3), 'start': round(r['start_s'], 3),
                                  'end': round(r['end_s'], 3), 'peak': r['picture']['peak']})
    # ranges of one file separated by a short dip of the score are one moment: joined (the higher peak leads)
    if not around and float(st['join_gap_s']) > 0:
        kept = _join(kept, float(st['join_gap_s']))
    if around:
        kept.sort(key=lambda r: r['picture']['coarse_rank'])
    else:
        kept = kept[:int(st['count'])]
    return kept


def _find_previews(artifacts, example, folder, out_ranges, previews, query, st):
    if previews != 'none' and out_ranges:
        pv = folder / 'previews'

        def one(r):
            r['preview'] = {'strip': _filmstrip(r, pv, int(st['frame_height']))}
            if previews in ('clips', 'both'):
                r['preview']['clip'] = _clip(r, pv, st)
            return r
        with ThreadPoolExecutor(max_workers=4) as ex:
            out_ranges = list(ex.map(one, out_ranges))
        title = f'find ranges: {query!r}' if query else 'find ranges: ' + (
            f'like {Path(example["file"]).name} @ {_clock(example.get("at", 0))}' if example
            else 'around given moments')
        ov = _overview(out_ranges, folder / 'overview.jpg', title)
        artifacts.append({'kind': 'overview', 'path': ov})
        for r in out_ranges:
            artifacts.append({'kind': 'sheet', 'path': r['preview']['strip'], 'range_id': r['range_id']})
            if r['preview'].get('clip'):
                artifacts.append({'kind': 'clip', 'path': r['preview']['clip'], 'range_id': r['range_id']})
    else:
        for r in out_ranges:
            r['preview'] = {}
    return out_ranges


def find(query=None, files=None, example=None, around=None, range_ids=None, ranges=None, count=None,
         settings=None, previews='sheets', out_dir=None, pad_s=None, reuse=True, progress=None, check=None):
    """Exact ranges (start/end seconds and frames) of what `query` describes, picture first.

    query: text ('a hand turns the screw', 'the dog jumps onto the bed'). example: {file, at} (pictures like that
    frame). around: [{file, at} | {file, start, end}, ...] moments you already know roughly: each is refined (with
    `query` when given, else the picture at `at`/the middle) instead of searching. range_ids: ids from an earlier
    call: those ranges again (with pad_s applied to their edit items). files: a folder, a file or a list. ranges:
    {file: [[start, end], ...]} limits the search. count: ranges returned. settings: any of DEFAULTS. previews:
    'sheets' (a strip per range + one overview), 'clips' (also a short MP4 per range), 'both', 'none'. pad_s: seconds
    added before and after in each edit_item (the range itself is not changed).

    Returns {schema_version, tool, result_id, plan_id, project_revision: None, source_fingerprints, ranges: [...],
    checked_ranges, unchecked_ranges, warnings, unsupported, preview_artifacts, changes: [], settings,
    defaults_used, timing, result_file}. Each range: range_id, file, start, end (seconds, frame times), start_frame,
    end_frame (inclusive, nominal frame grid), duration, peak_at, edit_item {clip, in, out (exclusive)}, confidence
    {picture {peak, coarse, z_file, prominence, baseline, threshold, coarse_rank}, edges {start, end: {basis,
    score_slope_per_s}}, motion {inside, before, after, ratios, camera_speed}, cuts {inside_split, snapped}, speech
    {words, text, silent}}, preview {strip, clip}, merged (other hits inside it)."""
    t_all = time.time()
    prog = progress or (lambda *a, **k: None)
    chk = check or (lambda: None)
    st, used_default = _settings(dict(settings or {}, **({'count': count} if count is not None else {})))
    if previews not in PREVIEWS:
        raise ValueError(f"previews: {', '.join(PREVIEWS)}")
    warnings, unchecked, artifacts = [], [], []
    sh, it = _shots(), _it()
    # stored ranges by id
    if range_ids:
        got, missing = _load_stored(list(range_ids))
        for m in missing:
            warnings.append(f'no stored range {m} (ids come from earlier letitedit_find_ranges results)')
        for r in got:
            if pad_s:
                r['edit_item'] = {'clip': r['file'], 'in': round(max(0.0, r['start'] - float(pad_s)), 4),
                                  'out': round(min(r['source_duration'], r['edit_item']['out'] + float(pad_s)), 4)}
            if r.get('preview', {}).get('strip') and not Path(r['preview']['strip']).exists():
                r['preview']['strip'] = _filmstrip(r, STORE / 'previews', int(st['frame_height']))
            if r.get('preview', {}).get('strip'):
                artifacts.append({'kind': 'sheet', 'path': r['preview']['strip'], 'range_id': r['range_id']})
        return {'schema_version': SCHEMA_VERSION, 'tool': TOOL, 'result_id': _h(['ids', range_ids, pad_s]),
                'plan_id': None, 'project_revision': None, 'source_fingerprints': [], 'ranges': got,
                'checked_ranges': [], 'unchecked_ranges': [], 'warnings': warnings, 'unsupported': [],
                'preview_artifacts': artifacts, 'changes': [], 'settings': st, 'defaults_used': used_default,
                'timing': {'total_s': round(time.time() - t_all, 2)}}
    if not query and not example and not around:
        raise ValueError('give query (text), example ({file, at}), around ([{file, at}]) or range_ids')
    if files is None and around:
        files = sorted({str(Path(a['file']).resolve()) for a in around})
    if files is None and example:
        files = [example['file']]
    scope, rng, prints, infos = _find_scope(files, it, ranges, sh, unchecked)
    qkey = ('q:' + _norm_query(query)) if query else ('ex:' + _h([sh.content_key(example['file']),
                                                                  example.get('at'), example.get('start'),
                                                                  example.get('end')])) if example else 'around'
    ident = {'schema': SCHEMA_VERSION, 'algo': ALGO_VERSION, 'q': qkey, 'around': around, 'ranges': ranges,
             'settings': st, 'previews': previews, 'pad_s': pad_s,
             'sources': [{k: p[k] for k in ('content_key', 'size', 'mtime_ns')} for p in prints],
             'shots': [sh.FEATURE_VERSION, sh.SCHEMA_VERSION]}
    result_id = _h(ident)
    folder = Path(out_dir) if out_dir else OUT / result_id
    rfile = folder / 'result.json'
    if reuse and rfile.exists():
        try:
            old = json.loads(rfile.read_text(encoding='utf-8-sig'))
            if old.get('result_id') == result_id and all(Path(a['path']).exists()
                                                         for a in old.get('preview_artifacts') or []):
                old['reused'] = True
                return old
        except (OSError, ValueError):
            pass
    folder.mkdir(parents=True, exist_ok=True)
    timing = {}
    prog(0.05, 'query')
    chk()
    modes = {}
    t0 = time.time()
    cands, qvec, qinfo, stats, coarse_info = _find_candidates(around, example, infos, it, modes, prog, query,
        rng, scope, st, unchecked, warnings)
    timing['coarse_s'] = round(time.time() - t0, 2)
    # refine, stage 1: dense picture scores (GPU) for every candidate
    t0 = time.time()
    motion_cache, refined = _find_picture_ranges(cands, chk, infos, it, prog, qvec, st, stats, warnings)
    timing['picture_s'] = round(time.time() - t0, 2)
    kept = _merge_picture_ranges(around, refined, st)
    # stage 2: motion onsets and cuts (CPU, parallel) for the ranges kept
    t0 = time.time()
    prog(0.75, 'motion and cuts')
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {}
        for r in kept:
            a, b2 = r['window']
            mk = (r['file'], round(a, 2), round(b2, 2))
            if mk not in futs:
                futs[mk] = pool.submit(_motion, r['file'], a - 0.6, b2 + 0.6, st)
        for mk, fu in futs.items():
            motion_cache[mk] = fu.result()
    kept = [_refine_edges(r, st, infos[r['file']], motion_cache, warnings) for r in kept]
    timing['edges_s'] = round(time.time() - t0, 2)
    # final ranges
    out_ranges = []
    fps_by = {p['file']: p for p in prints}
    for r in kept:
        info = infos[r['file']]
        fr = _final(r['file'], r, info, qkey, fps_by[r['file']])
        conf = {'picture': r['picture'], 'edges': r['edges'], 'motion': r['motion'], 'cuts': r['cuts'],
                'speech': _words_in(r['file'], fr['start'], fr['end'] + 1.0 / info['fps'])}
        if pad_s:
            fr['edit_item'] = {'clip': r['file'], 'in': round(max(0.0, fr['start'] - float(pad_s)), 4),
                               'out': round(min(info['duration'], fr['edit_item']['out'] + float(pad_s)), 4)}
        rec = {**fr, 'query': query, 'confidence': conf, 'merged': r.get('merged', []),
               'dense': r['dense'], 'given': r.get('given'), 'result_id': result_id}
        out_ranges.append(rec)
    # previews
    t0 = time.time()
    prog(0.85, 'previews')
    out_ranges = _find_previews(artifacts, example, folder, out_ranges, previews, query, st)
    timing['previews_s'] = round(time.time() - t0, 2)
    for r in out_ranges:
        _store(r)
    checked = []
    for f in scope:
        info = infos[f]
        spans = rng.get(f) if rng else [[0.0, round(info['duration'], 3)]]
        dense_w = sorted({(round(r['window'][0], 3), round(r['window'][1], 3)) for r in refined if r['file'] == f})
        checked.append({'file': f, 'ranges': [[round(a, 3), round(b, 3)] for a, b in spans],
                        'coarse_every_s': None if around else float(st['every_s']),
                        'refined_windows': [list(w) for w in dense_w]})
    timing['total_s'] = round(time.time() - t_all, 2)
    res = {'schema_version': SCHEMA_VERSION, 'tool': TOOL, 'result_id': result_id, 'plan_id': result_id,
           'project_revision': None, 'source_fingerprints': prints, 'query': query, 'example': example,
           'around': around, 'ranges': out_ranges, 'checked_ranges': checked, 'unchecked_ranges': unchecked,
           'warnings': warnings, 'unsupported': UNSUPPORTED, 'preview_artifacts': artifacts, 'changes': [],
           'note': 'analysis only: nothing was cut or moved. Insert a range with its edit_item ({clip, in, out}) in '
                   'letitedit_timeline_apply; ask for it again later with range_ids=[...]',
           'coarse': coarse_info, 'query_info': qinfo, 'settings': st, 'defaults_used': used_default,
           'method': __doc__.split('How a range is found')[1].split('A range\'s id')[0].strip(' :\n')
           if 'How a range is found' in (__doc__ or '') else '', 'timing': timing,
           'result_file': str(rfile), 'folder': str(folder)}
    tmp = rfile.with_suffix('.tmp')
    tmp.write_text(json.dumps(res, default=str, indent=1), encoding='utf-8')
    os.replace(tmp, rfile)
    prog(1.0, 'done')
    return res


# ------------------------------------------------------------------ short form

def compact(res, detail='brief'):
    """What a tool call returns: everything needed to choose and use a range; the dense profiles and full
    components stay in result_file (detail='full' returns them)."""
    if detail == 'full':
        return res
    keep = ('schema_version', 'tool', 'result_id', 'plan_id', 'project_revision', 'query', 'warnings',
            'unchecked_ranges', 'changes', 'note', 'result_file', 'folder', 'reused', 'timing')
    out = {k: res.get(k) for k in keep if k in res}
    lines, rows = [], []
    for k, r in enumerate(res.get('ranges') or []):
        c = r['confidence']
        sp = c.get('speech') or {}
        mo = c.get('motion') or {}
        rows.append({'range_id': r['range_id'], 'file': r['file'], 'start': r['start'], 'end': r['end'],
                     'start_frame': r['start_frame'], 'end_frame': r['end_frame'], 'duration': r['duration'],
                     'peak_at': r['peak_at'], 'edit_item': r['edit_item'],
                     'picture': {kk: c['picture'].get(kk) for kk in ('peak', 'coarse', 'z_file', 'prominence',
                                                                     'coarse_rank')},
                     'edges': [c['edges']['start']['basis'], c['edges']['end']['basis']],
                     'motion': {kk: mo.get(kk) for kk in ('inside', 'before', 'after', 'camera_speed')}
                     if mo.get('available') else 'not measured',
                     'cuts': c.get('cuts'), 'speech': (('silent' if sp.get('silent') else sp.get('text'))
                                                       if sp.get('available') else 'no transcript'),
                     'merged': len(r.get('merged') or []), 'preview': r.get('preview')})
        lines.append(f'{k + 1}. {r["range_id"]} {Path(r["file"]).name} {_clock(r["start"])}-{_clock(r["end"])} '
                     f'f{r["start_frame"]}-{r["end_frame"]} ({r["duration"]:.2f}s) peak {c["picture"]["peak"]:.3f} '
                     f'z{c["picture"]["z_file"]} edges {c["edges"]["start"]["basis"]}/{c["edges"]["end"]["basis"]}'
                     + ('' if not sp.get('available') else ' silent' if sp.get('silent') else ' (talk)'))
    out['text'] = '\n'.join(lines) or 'no ranges'
    out['ranges'] = rows
    out['checked'] = {'files': len(res.get('checked_ranges') or [])}
    out['preview_artifacts'] = res.get('preview_artifacts') or []
    out['unsupported'] = res.get('unsupported') or []
    return out


# ------------------------------------------------------------------ background job

def job(ctx):
    """jobs.py kind 'range_search:job': find(**ctx.inputs) with progress and cancel; outputs the result file."""
    inputs = dict(ctx.inputs or {})
    inputs.pop('background', None)
    inputs.pop('detail', None)
    inputs.pop('images', None)
    res = find(**inputs, progress=ctx.progress, check=ctx.check)
    return {'result_file': res['result_file'], 'result_id': res['result_id'],
            'ranges': [{k: r[k] for k in ('range_id', 'file', 'start', 'end', 'start_frame', 'end_frame')}
                       for r in res['ranges']], 'warnings': res['warnings'][:10]}


def submit(inputs, root=None):
    import letitedit.core.jobs as jobs
    return jobs.submit('range_search:job', inputs=inputs, label='find ranges', root=root, timeout_s=2 * 3600)
