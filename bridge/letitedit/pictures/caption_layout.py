"""Caption layout solver behind letitedit_caption_fit.

Lays a project's captions out against the picture: grouping and line breaks (pixel width, reading speed, cue
duration, natural break points, names and numbers kept whole), size (never under a readable minimum), and a place
from a small allowed set that keeps clear of faces, other text, the platform's overlays and protected regions, held
steady through a shot or phrase. Everything is measured with the renderer that draws it:

- native captions (a subtitle track burned in by Shotcut's Subtitle Burn In filter: MLT `subtitle` -> `qtext`): every
  cue's text block is rendered by melt in the track's own style (one frame per cue) and its ink measured, so the
  outline, the shadow copy, font matching and qtext's silent shrink-to-fit are the real thing. Pillow, with the same
  font file, predicts widths while line breaks are searched; melt corrects the prediction.
- word captions (graphics_templates/word_captions.py, drawn by Pillow): the template's own draw() runs frame by frame
  in a recording context, so every word's box at every animation frame (pop peaks, ease overshoot) is exact.

Footage frames (faces, final pixels, preview crops) are rendered by melt from the project and from a scratch copy
with the proposed changes compiled in (cache storage only: fit() never writes the project).

The approved words are never changed or dropped: only whitespace (line breaks; a space restored where the transcript
shows two words), grouping, cue edge timing, size, place and outline/animation strength change, and every proposal
is checked for that before it is returned. The result is a proposal whose `changes` use letitedit_timeline_apply's
vocabulary; apply_plan() applies it through the shared apply path and refuses a project that changed since.

Native caption tracks have one style (one place) per track: Shotcut's burn-in filter draws every cue of a feed in
the same rect. A cue that needs another place goes on a caption track of its own (native_mode='tracks'); word
captions take a place per cue.

    fit(project, ...)          -> proposal dict (fields documented in caption_layout_tools.letitedit_caption_fit)
    apply_plan(plan_or_id)     -> result of the shared apply path, with a check that every word is kept

The code is in parts, each imported back here: caption_layout_frame (settings, errors, geometry, the frame),
_words (break points), _render (fonts, measuring, real renders, the word-caption template), _cues (layers, cues,
line breaks and grouping), _place (obstacles, placement, violations) and _solve (native and word-caption layers).
This file keeps the faces (the tests patch what they read here), the checks of a proposal, the final pixels,
fit() and apply_plan().
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import copy
import dataclasses
import difflib
import hashlib
import itertools
import json
import math
import os
import re
import statistics
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import letitedit.review.checks as checks          # melt/ffmpeg paths, the face detector; importing it sets the font folders melt loads
import letitedit.timeline.edit_script as es
import letitedit.timeline.timeline_model as tm


# ---- this module's parts: every name in them imported back, so each is the same object as before
# the module's settings and errors, geometry and the frame: boxes, the frame's size, platform overlays and the safe area
from letitedit.pictures.caption_layout_frame import (  # noqa: E402,F401
    SCHEMA_VERSION, CACHE, MELT, FFMPEG, NO_WINDOW, INF, SLOT_NAMES, DEFAULT_SLOTS, SEVERITY, PREVIEW_ORDER,
    PLACE_KINDS, Refused, Conflict, _Unsupported, _area, _inter, _union, _shift, _pad, _rbox, parse_geometry,
    _geom_text, _fmt, _slug, Frame, frame_spec, slot_anchor, free_area, place_extra, _merge_ranges
)
# words and break points: what may end a line, what must stay together, words run together
from letitedit.pictures.caption_layout_words import (  # noqa: E402,F401
    ARTICLES, PREPS, CONJ, UNITS, PRONOUN_I, SUBJECTS, NAME_JOINERS, ABBREV, COMMON_WORDS, CAMEL_OK, norm, _core,
    sentence_end, clause_end, capitalised, numeric, lost_stop, break_cost, name_spans, keep_together_spans,
    suspected_join, vocab_lower
)
# fonts and measuring text, real renders with the export engine, and the word-caption template recorded
from letitedit.pictures.caption_layout_render import (  # noqa: E402,F401
    _FONTS, _METRICS, _pil_font, _qt_vmetrics, resolve_font, QtText, _esc, _srt_ms, _mlt_rgba, _css,
    _background_for, _run, CAPTION_RENDER_KEYS, melt_text_blocks, column_gaps, _profile_xml, render_frames,
    _RECORDER, _band_extent, _recorder_class, WordCaptions
)
# caption layers and cues, line breaks and grouping
from letitedit.pictures.caption_layout_cues import (  # noqa: E402,F401
    Cue, Layer, _shots, _shot_at, find_layers, cached_timeline_words, align_native, _fill_times, split_join,
    best_lines, Rules, _target_words, cue_issues, regroup_run, _runs, _cuts_inside, _windows, regroup_cues,
    _wanted_end, _group_times
)
# obstacles, placement and violations
from letitedit.pictures.caption_layout_place import (  # noqa: E402,F401
    Obstacle, protected_obstacles, zone_obstacles, _alpha_boxes, overlay_text_obstacles, Weights, placement_cost,
    solve_places, _violation, _place_violations, _timing_violations
)
# the native caption layers and the word-caption layers, solved
from letitedit.pictures.caption_layout_solve import (  # noqa: E402,F401
    OPTIONS, _unresolved, _unresolved_from, _min_gap, _native_layer_obstacles, _native_rect, _calibrate,
    _native_user_style, _outline_for_gaps, _break, _native_groups, _lend_native_display_time, solve_native,
    _nearest_slot, _native_cue_violations, solve_words, _nearest_word_slot, _word_slot_position, _settled,
    _gap_report, _word_cue_violations, _words_gap_fix, _words_groups, _word_changes, _absolutise, _variant,
    _text_track_indices
)



_DETECTORS = {}


def detect_faces(png, width=960):
    """[(face box, [right eye, left eye, nose, right mouth corner, left mouth corner])] in a frame: the same
    OpenCV YuNet model and thresholds as checks.faces_in, keeping the landmarks it also finds."""
    import cv2
    if not checks.faces_available():
        return []
    img = cv2.imread(str(png))
    if img is None:
        return []
    scale = width / img.shape[1]
    small = cv2.resize(img, (width, round(img.shape[0] * scale)))
    size = (small.shape[1], small.shape[0])
    det = _DETECTORS.get(size)
    if det is None:
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except AttributeError:
            pass
        det = _DETECTORS[size] = cv2.FaceDetectorYN.create(str(checks.YUNET), '', size, 0.75, 0.3, 20)
    _, found = det.detect(small)
    out = []
    for f in (found if found is not None else []):
        if f[2] < 14:
            continue
        box = (float(f[0]) / scale, float(f[1]) / scale, float(f[0] + f[2]) / scale, float(f[1] + f[3]) / scale)
        pts = [(float(f[4 + 2 * i]) / scale, float(f[5 + 2 * i]) / scale) for i in range(5)]
        out.append((box, pts))
    return out


def face_core(box, pts=None):
    """The region a caption must keep clear of: the detector's face box (brow to chin) plus headroom above it for a
    cap or hair. YuNet's box starts at the forehead, below a cap's crown, so without headroom a caption over a hat
    would count as clear. Nothing is added below the chin or at the sides: the neck and the chest are free, and
    `covers_face_part` (the project check) reads the same chin line."""
    x0, y0, x1, y1 = box
    h = y1 - y0
    return (x0, y0 - 0.55 * h, x1, y1)


CHIN_TOLERANCE = 0.05      # a caption may reach this share of the face box's height up from the chin line


def face_parts(box, pts):
    """{'mouth': box, 'eyes': box} from the detector's landmarks (right eye, left eye, nose, right and left mouth
    corner): the mouth is the corners' span and a little above and below it, the eyes and nose the span from eye
    line to nose tip. None for a part the landmarks don't give."""
    out = {}
    try:
        (rx, ry), (lx, ly), (nx, ny), (mx0, my0), (mx1, my1) = [(float(a), float(b)) for a, b in pts[:5]]
    except (TypeError, ValueError):
        return out
    mw = max(abs(mx1 - mx0), 1.0)
    out['mouth'] = (min(mx0, mx1) - 0.15 * mw, min(my0, my1) - 0.3 * mw, max(mx0, mx1) + 0.15 * mw,
                    max(my0, my1) + 0.3 * mw)
    ed = max(abs(lx - rx), 1.0)
    out['eyes'] = (min(rx, lx) - 0.25 * ed, min(ry, ly) - 0.2 * ed, max(rx, lx) + 0.25 * ed, max(ny, ry, ly) + 0.1 * ed)
    return out


def covers_face_part(ink, box, pts=None):
    """What a caption's ink covers of a face, or None: 'mouth' or 'eyes' (any overlap of the landmarks' regions) or
    'chin' (it reaches up into the face box more than CHIN_TOLERANCE of the box's height, over at least a fifth of
    the box's width). The neck and chest below the box, and the cap above it, are not the face."""
    if not ink:
        return None
    for name, part in face_parts(box, pts or []).items():
        if _inter(ink, part) > 0:
            return name
    x0, y0, x1, y1 = box
    ox = min(ink[2], x1) - max(ink[0], x0)
    oy = min(ink[3], y1) - max(ink[1], y0)
    if ox > 0.2 * (x1 - x0) and oy > CHIN_TOLERANCE * (y1 - y0):
        return 'chin'
    return None


def _visual_signature(script, timeline, layers, path):
    """Fingerprint only what can change the clean picture used by face detection.

    Caption text and caption-only video tracks are hidden in that render. Their edits
    must not invalidate face samples; a changed shot, crop, source or detector must.
    """
    hidden = _text_track_indices(timeline, layers)
    hidden_names = {t.name for t in timeline.video_tracks() if t.index in hidden}
    visible = [t for t in script.get('tracks', []) if t.get('name') not in hidden_names]
    resources = set()

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('clip', 'source', 'file', 'path') and isinstance(child, str):
                    p = Path(child)
                    if not p.is_absolute():
                        p = Path(path).parent / p
                    if p.is_file():
                        resources.add(p.resolve())
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(visible)
    stamps = []
    for p in sorted(resources):
        st = p.stat()
        stamps.append((str(p), st.st_size, st.st_mtime_ns))
    for p in (MELT, checks.YUNET):
        if Path(p).is_file():
            st = Path(p).stat()
            stamps.append((str(p), st.st_size, st.st_mtime_ns))
    payload = {'profile': script.get('profile'), 'tracks': visible,
               'master': script.get('master'), 'resources': stamps}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _faces_in_frames(path, timeline, layers, frame, work, frames, script=None):
    """({frame: [[face box, landmarks], ...]}, frames that had to be rendered): faces in the picture under the text at
    these timeline frames, rendered by melt with the text hidden and cached per picture state."""
    from PIL import Image
    import letitedit.pictures.caption_reuse as caption_reuse
    hidden = _text_track_indices(timeline, layers)
    clean = _variant(path, work / 'clean.mlt', hide_tracks=hidden, drop_feeds='all')
    keys = None
    if script and caption_reuse.enabled():      # T362: a frame keeps its faces while what it shows is unchanged
        try:
            names = {t.name for t in timeline.video_tracks() if t.index in hidden}
            keys = caption_reuse.frame_keys(script, path, names, sorted(set(frames)), (frame.width, frame.height))
        except Exception:  # noqa: BLE001 - no keys: the per-picture cache below, as before
            keys = None
    cache = CACHE / 'faces' / _visual_signature(script, timeline, layers, path) if script and keys is None else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    found = {}
    missing = []
    for f in sorted(set(frames)):
        if keys is not None:
            got = caption_reuse.read_faces(keys[f])
            if got is None:
                missing.append(f)
            else:
                found[f] = got
            continue
        item = cache / f'{f}.json' if cache else None
        try:
            found[f] = json.loads(item.read_text(encoding='utf-8-sig')) if item else None
            if not isinstance(found[f], list):
                raise ValueError('invalid face cache')
        except (OSError, ValueError, TypeError):
            missing.append(f)
    if missing:
        pngs = render_frames(clean, timeline.profile, missing, work / 'faces', 'face')
        for f, png in zip(missing, pngs):
            with Image.open(png) as im:
                pw = im.width
            k = frame.width / pw
            found[f] = [[list(v * k for v in box), [[x * k, y * k] for x, y in pts]]
                        for box, pts in detect_faces(png, width=min(960, pw * 2))]
            if keys is not None:
                caption_reuse.write_faces(keys[f], found[f])
            elif cache:
                item = cache / f'{f}.json'
                temp = cache / f'{f}-{uuid.uuid4().hex}.tmp'
                temp.write_text(json.dumps(found[f]), encoding='utf-8')
                os.replace(temp, item)
    return found, missing


def faces_detail_at(project, times, max_frames=60):
    """{time: [(face box, landmarks) in project pixels, ...]} at timeline times, from the picture the viewer sees:
    a clip's zoom, crop or ffmpeg graph moves a face and a full-frame scene hides it. The samples and cache are the
    same as fit's face check. With more times than max_frames, evenly spaced times are measured and the rest left out."""
    if not checks.faces_available():
        return {}
    path = es._resolve(project)
    script = es.read(path)
    timeline = tm.load(path)
    frame = frame_spec(script['profile'])
    layers = find_layers(script, None)
    picked = sorted({round(float(t), 2) for t in times})
    if len(picked) > max(1, int(max_frames)):
        step = len(picked) / max(1, int(max_frames))
        picked = [picked[int(i * step)] for i in range(max(1, int(max_frames)))]
    if not picked:
        return {}
    numbers = {t: min(timeline.frames - 1, max(0, int(round(t * frame.fps)))) for t in picked}
    CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='faces-', dir=CACHE) as d:
        found, _ = _faces_in_frames(path, timeline, layers, frame, Path(d), list(numbers.values()), script)
    return {t: [(tuple(box), pts) for box, pts in found[f]] for t, f in numbers.items()}


SHOT_MIN_S = 0.3    # a picture run shorter than this (a flash, a transition's overlap) gets no sample of its own
SNAP_S = 0.25       # T362 (caption_fit_reuse): how far a face sample may move to a frame measured before (half the grid)


def picture_runs(script, timeline, layers, fps):
    """[(start_s, end_s)] of the picture under the text: the stretches between any clip edge on the video tracks the
    text isn't on (the main track's cuts, an Angles track's camera changes, cutaways), so each shot is known."""
    import letitedit.timeline.edit_sync as edit_sync
    if not script:
        return []
    hidden = _text_track_indices(timeline, layers)
    hidden_names = {t.name for t in timeline.video_tracks() if t.index in hidden}
    edges, end = {0.0}, 0.0
    for t in script.get('tracks', []):
        if t.get('kind', 'video') != 'video' or t.get('name') in hidden_names or t.get('hide') in ('video', 'both'):
            continue
        for it, a, b in edit_sync.layout(t, fps):
            if 'clip' in it or 'graphic' in it:
                edges.update((round(a, 3), round(b, 3)))
                end = max(end, b)
    edges = sorted(e for e in edges if e <= end)
    return [(a, b) for a, b in zip(edges, edges[1:]) if b - a >= SHOT_MIN_S]


def face_obstacles(path, timeline, layers, fitted, frame, work, hard, max_frames, script=None):
    """Faces in the picture under every text layer, sampled at each caption's middle and through long captions
    (rendered by melt at a smaller size, OpenCV YuNet). Each sample is an obstacle for 1.5 s around its time, so a
    face that moves is where it was then. Every shot under a caption also gets a sample at its middle (beyond
    max_frames), an obstacle through the shot, so no camera's shot goes unlooked at when the cameras change often."""
    if not checks.faces_available():
        return [], {'available': False, 'note': 'face detector not available (OpenCV YuNet)'}
    if script is None:
        try:
            script = es.read(path)
        except Exception:  # noqa: BLE001 - no shots known: the caption samples stand alone
            script = None
    try:
        runs = picture_runs(script, timeline, layers, frame.fps)
    except Exception:  # noqa: BLE001
        runs = []
    times = set()
    for l in fitted:
        for c in l.cues:
            d = c.end - c.start
            times.add(round(c.start + d / 2, 2))
            k = c.start + 1.0
            while d > 2.5 and k < c.end - 0.5:
                times.add(round(k, 2))
                k += 1.5
    spans = [(c.start, c.end) for l in fitted for c in l.cues]
    if spans:           # and every half second across the captions, so a head that moves between two cues is seen
        k = min(s0 for s0, _ in spans)
        while k < max(e0 for _, e0 in spans):
            times.add(round(k, 2))
            k += 0.5
    times = sorted(times)
    cap = max(4, int(max_frames), min(len(times), 240))   # every caption gets a sample of its own, so none is placed blind
    if len(times) > cap:
        step = len(times) / cap
        times = [times[int(i * step)] for i in range(cap)]
    # every shot under a caption: a sample at its middle, never thinned away (spans: the stretch it stands for)
    shots = []
    for a, b in runs:
        under = [(max(a, s0), min(b, e0)) for s0, e0 in spans if s0 < b and e0 > a]
        if under:
            lo, hi = min(x for x, _ in under), max(y for _, y in under)
            mid = round((lo + hi) / 2, 2)
            shots.append((mid, max(a, mid - 3.0), min(b, mid + 3.0)))
    samples = [(t, t - 0.75, t + 0.75) for t in times] + shots

    def in_shot(t, t0, t1):     # a sample stands for its own shot only: the next camera shows something else
        for a, b in runs:
            if a <= t < b:
                return max(t0, a), min(t1, b)
        return t0, t1

    samples = [(t, *in_shot(t, t0, t1)) for t, t0, t1 in samples]
    frames = [min(timeline.frames - 1, max(0, int(round(t * frame.fps)))) for t, _, _ in samples]
    import letitedit.pictures.caption_reuse as caption_reuse
    if script and caption_reuse.enabled():
        try:        # T362: a sample moves (at most half the grid's spacing, inside its shot) to a frame measured before
            hidden = _text_track_indices(timeline, layers)
            names = {tr.name for tr in timeline.video_tracks() if tr.index in hidden}
            moved, frames_moved = caption_reuse.snap_samples(script, path, names, samples, frames, runs, frame.fps,
                                                             timeline.frames, (frame.width, frame.height), SNAP_S)
            delta = [b[0] - a[0] for a, b in zip(samples, moved)]
            n = len(times)
            times = [t + d for t, d in zip(times, delta[:n])]
            shots = [(m + d, a + d, b + d) for (m, a, b), d in zip(shots, delta[n:])]
            samples, frames = moved, frames_moved
        except Exception:  # noqa: BLE001 - the samples as planned
            pass
    found, missing = _faces_in_frames(path, timeline, layers, frame, work, frames, script)
    obs = []
    for (t, t0, t1), f in zip(samples, frames):
        for box, pts in found[f]:
            core = face_core(box, pts)
            obs.append(Obstacle('face', 'face', t0, t1, [(t, core)], hard))
    covered = _merge_ranges([(t - 1.5, t + 1.5) for t in times] + [(t0, t1) for _, t0, t1 in shots])
    unc = [(c.start, c.end) for l in fitted for c in l.cues
           if not any(s <= (c.start + c.end) / 2 <= e for s, e in covered)]
    return obs, {'available': True, 'sampled': len(set(frames)), 'faces_found': len(obs),
                 'shots_under_captions': len(shots),     # each with a sample of its own
                 'sample_times': [round(t, 2) for t, _, _ in samples[:200]], 'uncovered': _merge_ranges(unc),
                 'cache_hits': len(set(frames)) - len(missing)}


# ============================================================================ checks of the proposal

def layer_tokens(script, track_names, kind):
    """Every word of a caption layer in time order (native: the cue text split at spaces; word captions: the graphic
    words)."""
    from letitedit.timeline.edit_sync import layout
    seq = []
    cue_order = 0
    if kind == 'native':
        for cap in script.get('captions', []):
            if cap['track'] in track_names:
                for q in cap['cues']:
                    for k, tok in enumerate(q['text'].split()):
                        seq.append((es.to_seconds(q['start']), cue_order, k, tok))
                    cue_order += 1
    else:
        for t in script['tracks']:
            if t['name'] not in track_names:
                continue
            for it, s, e in layout(t):
                g = it.get('graphic') or {}
                if g.get('template') == 'word_captions':
                    for k, w in enumerate((g.get('params') or {}).get('words') or []):
                        seq.append((s, cue_order, k, str(w[0])))
                    cue_order += 1
    # Simultaneous cues are separate phrases. Sort the phrases, then their words;
    # sorting by word index interleaves them and falsely reports a word change.
    seq.sort(key=lambda x: (x[0], x[1], x[2]))
    return [x[3] for x in seq]


def _expected_tokens(before, fixes):
    out = list(before)
    for f in fixes or []:
        if f['from'] in out:
            k = out.index(f['from'])
            out[k:k + 1] = f['to']
    return out


def check_changes(script, plans, changes):
    """The changes pass the op checks and the edit compiler's own edit step, and keep every approved word (only a
    space restored between two transcript words may split a token). Raises RuntimeError otherwise."""
    import letitedit.timeline.op_specs as op_specs
    op_specs.check(changes)
    after, _ = es.edit(script, [dict(c) for c in changes])
    for p in plans:
        l = p['layer']
        expect = _expected_tokens(layer_tokens(script, {l.track, *l.siblings}, l.kind), p['summary'].get('token_fixes'))
        now = layer_tokens(after, set(p['tracks_out']) | {l.track, *l.siblings}, l.kind)
        if now != expect:
            sm = difflib.SequenceMatcher(None, expect, now, autojunk=False)
            diff = [(op, expect[i1:i2], now[j1:j2]) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != 'equal'][:5]
            raise RuntimeError(f'caption fit would change the words of {l.track}: {diff} (not proposed)')
    return after


# ============================================================================ the export engine: final pixels

def _caption_pixels(mag):
    """The captions' own pixels in a frame difference (mag: per-pixel largest channel difference): connected shapes
    that differ by more than 40, at least 4 px thick, 40 px in area, 15% filled and with somewhere a strong difference
    (90+). Glyphs (outlined, antialiased) are; the stray pixels and thin lines a burn-in's colour conversion leaves
    across the frame (picture edges, saturated areas) are not."""
    import numpy as np
    diff = mag > 40
    try:
        import cv2
    except ImportError:                       # fallback: pixels with at least four changed neighbours
        m = diff.astype(np.uint8)
        p = np.pad(m, 1)
        h, w = m.shape
        return diff & (sum(p[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3)) >= 5)
    cnt, lab, stats, _ = cv2.connectedComponentsWithStats(diff.astype(np.uint8), connectivity=8)
    peak = np.zeros(cnt, dtype=np.int32)
    np.maximum.at(peak, lab.ravel(), mag.astype(np.int32).ravel())
    keep = np.zeros(cnt, dtype=bool)
    for i in range(1, cnt):
        x, y, w, h, area = (int(v) for v in stats[i])
        keep[i] = min(w, h) >= 4 and area >= 40 and area >= 0.15 * w * h and peak[i] >= 90
    return keep[lab]


def _compile_after(path, changes, work):
    """The project with the changes compiled in, as a scratch copy in the cache (graphics rendered there)."""
    scratch = work / 'scratch'
    scratch.mkdir(parents=True, exist_ok=True)
    base = scratch / 'before.mlt'
    tree = ET.parse(path)
    _absolutise(tree.getroot(), Path(path).resolve().parent)
    tree.write(base, encoding='utf-8', xml_declaration=True)
    before = es.read(base)
    after, _ = es.edit(before, [dict(c) for c in changes])
    after['base'] = before['base']
    out = scratch / 'after.mlt'
    es.compile_script(after, base=base, out=out, graphics_dir=scratch / 'graphics')
    return out


def compile_after(path, changes, work):
    """_compile_after by its public name (server/self_checks.py measures a planned score on it, T345 C3)."""
    return _compile_after(path, changes, work)


def render_check(path, timeline, frame, plans, obstacles, work, max_frames, result):
    """Risk frames of the project and of the proposal rendered by melt: the captions' own pixels (the frame minus the
    same frame without the laid-out captions) are checked against faces, other text, regions, overlays and the safe
    area, compared with the measured boxes, and cut into before/after preview crops."""
    import numpy as np
    from PIL import Image
    fps = frame.fps
    picks = []
    for v in result['violations']:
        if v['stage'] == 'before' and v['severity'] in ('error', 'warning'):
            picks.append((v.get('at', (v['start'] + v['end']) / 2), 0))
    for p in plans:
        for c in p['cues_after']:
            picks.append(((c['start'] + c['end']) / 2, 1))
    seen, times = set(), []
    for t, _ in sorted(picks, key=lambda x: (x[1], x[0])):
        f = int(round(t * fps))
        if f in seen or f >= timeline.frames or f < 0:
            continue
        seen.add(f)
        times.append(t)
        if len(times) >= max(2, int(max_frames)):
            break
    times.sort()
    frames = [int(round(t * fps)) for t in times]
    if not frames:
        return None
    fitted = [p['layer'] for p in plans]
    nocap = _variant(path, work / 'nocap.mlt',
                     hide_tracks={t.index for t in timeline.video_tracks()
                                  if t.name in {l.track for l in fitted if l.kind == 'words'}},
                     drop_feeds={n for l in fitted if l.kind == 'native' for n in (l.track, *l.siblings)})
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.monotonic()
    with ThreadPoolExecutor(3) as pool:        # three melt/compile jobs side by side
        fb = pool.submit(render_frames, path, timeline.profile, frames, work / 'r-before', 'b')
        fn = pool.submit(render_frames, nocap, timeline.profile, frames, work / 'r-nocap', 'n')
        fa = pool.submit(_compile_after, path, result['changes'], work) if result['changes'] else None
        before_png, nocap_png = fb.result(), fn.result()
        after_path = fa.result() if fa else None
    after_png = None
    if after_path:
        after_png = render_frames(after_path, tm.load(after_path).profile, frames, work / 'r-after', prefix='a')
    result.setdefault('timings', {})['render: frames and proposal'] = round(time.monotonic() - t0, 2)
    own = {f'caption track {l.track}' for l in fitted} | {f'word captions {l.track}' for l in fitted}
    predicted = [(c['start'], c['end'], c['box']) for p in plans for c in p['cues_after'] if c.get('box')]
    rows = []
    for k, t in enumerate(times):
        with Image.open(nocap_png[k]) as im:
            nb = np.asarray(im.convert('RGB'), dtype=np.int16)
        row = {'at': round(t, 3), 'at_clock': _fmt(t)}
        for stage, pngs in (('before', before_png), ('after', after_png)):
            if pngs is None:
                continue
            with Image.open(pngs[k]) as im:
                a = np.asarray(im.convert('RGB'), dtype=np.int16)
            mask = _caption_pixels(np.abs(a - nb).max(axis=2))
            ys, xs = np.nonzero(mask)
            box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if len(xs) else None
            row[f'{stage}_ink'] = _rbox(box, 0)
            if not box:
                continue
            hits = []
            for ob in obstacles:
                if ob.name in own:
                    continue
                b = ob.box_in(t - 0.05, t + 0.05)
                if not b:
                    continue
                x0, y0 = max(0, int(b[0])), max(0, int(b[1]))
                x1, y1 = min(mask.shape[1], int(math.ceil(b[2]))), min(mask.shape[0], int(math.ceil(b[3])))
                if x1 > x0 and y1 > y0:
                    n = int(mask[y0:y1, x0:x1].sum())
                    if n > 25:
                        hits.append({'obstacle': ob.name, 'kind': ob.kind, 'caption_pixels': n})
            row[f'{stage}_overlaps'] = hits
            sx0, sy0, sx1, sy1 = frame.safe
            row[f'{stage}_inside_safe'] = bool(box[0] >= sx0 - 2 and box[1] >= sy0 - 2 and box[2] <= sx1 + 2
                                               and box[3] <= sy1 + 2)
            if stage == 'after' or not result['changes']:
                pred = _union([tuple(b) for s, e, b in predicted if s - 0.02 <= t <= e + 0.02])
                if pred:
                    x0, y0 = max(0, int(pred[0] - 8)), max(0, int(pred[1] - 8))
                    x1 = min(mask.shape[1], int(math.ceil(pred[2] + 8)))
                    y1 = min(mask.shape[0], int(math.ceil(pred[3] + 8)))
                    total = int(mask.sum())
                    inside = int(mask[y0:y1, x0:x1].sum()) if x1 > x0 and y1 > y0 else 0
                    share = (total - inside) / max(1, total)
                    row['outside_predicted_share'] = round(share, 4)
                    if share > 0.03:
                        result['violations'].append(_violation(
                            'render_mismatch', 'render check', None, f'at {_fmt(t)} {share:.0%} of the rendered '
                            f'caption pixels are outside the measured box', 'after', start=t, end=t, at=t, box=box,
                            evidence='melt-footage', other={'predicted': _rbox(pred)}))
        rows.append(row)
    result['render_check'] = {'engine': 'melt (the export engine)', 'frames': len(frames), 'rows': rows,
                              'method': 'caption pixels = rendered frame minus the same frame without the laid-out '
                                        'captions; overlaps count those pixels inside each obstacle box'}
    sheet = preview_sheet(times, before_png, after_png, rows, frame, work, result)
    if sheet:
        result['preview_artifacts'].append(sheet)
    if after_png:
        result['preview_artifacts'].append(str(work / 'r-after'))
    return {'times': times}


def preview_sheet(times, before_png, after_png, rows, frame, work, result, limit=12):
    """Before | after crops around the captions at the riskiest moments (violations first), labelled; saved PNG."""
    from PIL import Image, ImageDraw, ImageFont
    vio = {}
    for v in result['violations']:
        if v['stage'] == 'before' and v['severity'] in ('error', 'warning'):
            vio.setdefault(round(v.get('at', (v['start'] + v['end']) / 2), 2), []).append(v['kind'])

    def rank(i):
        kinds = vio.get(round(times[i], 2), [])
        return (min([PREVIEW_ORDER.index(k) if k in PREVIEW_ORDER else len(PREVIEW_ORDER) for k in kinds]
                    or [len(PREVIEW_ORDER) + 1]), times[i])
    items = sorted(sorted(range(len(times)), key=rank)[:limit], key=lambda i: times[i])
    if not items:
        return None
    W, H = frame.width, frame.height
    try:
        font = ImageFont.truetype('arial.ttf', 15)
    except OSError:
        font = ImageFont.load_default()
    tw = 330
    tiles = []
    for i in items:
        row = rows[i]
        u = _union([tuple(b) for b in (row.get('before_ink'), row.get('after_ink')) if b]) or (0, H * 0.4, W, H * 0.9)
        cw, ch = max(u[2] - u[0], W * 0.6), max(u[3] - u[1], H * 0.22)
        cx, cy = (u[0] + u[2]) / 2, (u[1] + u[3]) / 2
        box = tuple(int(v) for v in (max(0, cx - cw / 2 - 20), max(0, cy - ch / 2 - 20), min(W, cx + cw / 2 + 20),
                                     min(H, cy + ch / 2 + 20)))
        pair = []
        for pngs in (before_png, after_png):
            if pngs is None:
                continue
            with Image.open(pngs[i]) as im:
                c = im.convert('RGB').crop(box)
            pair.append(c.resize((tw, max(1, int(c.height * tw / c.width)))))
        th = max(p.height for p in pair)
        tile = Image.new('RGB', (tw * len(pair) + 6 * (len(pair) - 1), th + 22), (24, 24, 28))
        for n, p in enumerate(pair):
            tile.paste(p, (n * (tw + 6), 22))
        kinds = ', '.join(sorted(set(vio.get(round(times[i], 2), [])))) or 'cue'
        ImageDraw.Draw(tile).text((4, 3), f'{_fmt(times[i])}  {kinds}' + ('   (before | after)' if len(pair) > 1 else ''),
                                  fill=(255, 220, 90), font=font)
        tiles.append(tile)
    cols = 2 if len(tiles) > 1 else 1
    cw = max(t.width for t in tiles)
    nrows = (len(tiles) + cols - 1) // cols
    rh = [max(t.height for t in tiles[r * cols:(r + 1) * cols]) for r in range(nrows)]
    sheet = Image.new('RGB', (cols * cw + (cols - 1) * 10, sum(rh) + 10 * (nrows - 1)), (10, 10, 12))
    y = 0
    for r in range(nrows):
        for c in range(cols):
            if r * cols + c < len(tiles):
                sheet.paste(tiles[r * cols + c], (c * (cw + 10), y))
        y += rh[r] + 10
    out = work / 'caption-fit-preview.png'
    sheet.save(out)
    return str(out)


# ============================================================================ the whole fit

def _fit_slots(faces, frame, native_mode, placements, platform_zones, prefer, regroup):
    if native_mode not in ('track', 'tracks'):
        raise ValueError("native_mode is 'track' (one place per caption track) or 'tracks' (a caption track per place)")
    if regroup not in ('auto', 'all', 'none'):
        raise ValueError("regroup is 'auto', 'all' or 'none'")
    if faces not in ('auto', 'off', 'hard'):
        raise ValueError("faces is 'auto', 'off' or 'hard'")
    if platform_zones not in ('hard', 'soft', 'off'):
        raise ValueError("platform_zones is 'hard', 'soft' or 'off'")
    slots = list(placements or DEFAULT_SLOTS[frame.shape])
    bad = [s for s in slots if s not in SLOT_NAMES]
    if bad or not slots:
        raise ValueError(f"unknown placement {', '.join(bad)}; placements: {', '.join(SLOT_NAMES)}")
    if prefer and prefer not in slots:
        raise ValueError(f'prefer {prefer!r} is not one of the allowed placements {slots}')
    return slots


def _fit_word_timings(fitted, result, script):
    # ---- words said (native layers take their timing from them; cached transcripts only)
    joins = {}
    if any(l.kind == 'native' for l in fitted):
        words, missing = cached_timeline_words(script)
        if missing:
            result['warnings'].append(f'{len(missing)} file(s) on the timeline have no cached transcript, so captions '
                                      f'over them keep their grouping (letitedit_words transcribes them)')
        for l in fitted:
            if l.kind == 'native':
                joins[l.track] = align_native(l, words)
    return joins


def _fit_obstacles(faces, fitted, frame, lap, layers, max_frames, path, platform_zones, protected, result,
        script, shots, timeline, work):
    # ---- what captions keep clear of
    total = max([e for _, e in shots] + [timeline.seconds])
    obstacles = []
    if platform_zones != 'off':
        obstacles += zone_obstacles(frame, hard=(platform_zones == 'hard'))
    obstacles += protected_obstacles(protected, frame, total)
    try:
        obstacles += overlay_text_obstacles(timeline, frame, {l.track for l in fitted})
    except Exception as exc:  # noqa: BLE001
        result['warnings'].append(f'other text layers could not be measured: {exc}')
    for l in layers:
        if l.kind == 'native' and not l.fit and l.style and l.cues and l.style.get('geometry'):
            try:
                obstacles += _native_layer_obstacles(l, frame, work / f'other-{_slug(l.track)}')
            except Exception as exc:  # noqa: BLE001
                result['warnings'].append(f'caption track {l.track} could not be measured: {exc}')
    lap('other text')
    face_info = {'checked': False}
    if faces != 'off':
        try:
            fobs, face_info = face_obstacles(path, timeline, layers, fitted, frame, work, faces == 'hard', max_frames,
                                            script=script)
            obstacles += fobs
        except Exception as exc:  # noqa: BLE001 - faces are one input; the layout goes on without them
            result['warnings'].append(f'faces were not checked: {exc}')
            face_info = {'error': str(exc)}
    lap('faces')
    return obstacles, face_info


def _fit_free_area(faces, frame, obstacles, opts, result, script):
    # ---- where captions go: the middle of the room below the face, one place for the whole video; the other places
    # are for a cue that cannot be there (another text, a protected region)
    free = free_area(frame, obstacles) if faces != 'off' else None
    if free and 'position' not in opts['lock']:
        frame.free_y = free['centre']
        opts['slots'] = ['free'] + [x for x in opts['slots'] if x != 'free']
        opts['prefer'] = opts['prefer'] or 'free'
        result['free_area'] = {**free, 'note': 'the middle of the room between the lowest chin in the video and the bottom of '
                               'the area the apps leave free is the place "free"; captions go there unless something else '
                               'is there for that moment', 'platform': frame.platform}
        if frame.platform == 'phone':       # the three apps' covered areas together: what each one alone would leave
            import letitedit.catalogs.platforms as _pl
            alone = {}
            for pid in ('tiktok', 'youtube_shorts', 'instagram_reels'):
                try:
                    bottom = frame_spec(script['profile'], pid).safe[3]
                    alone[pid] = {'room_px': round(max(0.0, bottom - free['top']), 1),
                                  'centre_pct': round(100 * (free['top'] + bottom) / 2 / frame.height, 1)}
                except Exception:  # noqa: BLE001
                    pass
            result['free_area']['each_platform_alone'] = alone
    elif faces != 'off':
        result['free_area'] = None


def _fit_layers(ctx, fitted, joins, result, work, obstacles):
    # ---- each layer in turn; a laid-out layer is text the next one keeps clear of
    plans = []
    for l in fitted:
        try:
            plan = solve_native(ctx, l, obstacles, joins.get(l.track, []), work) if l.kind == 'native' else \
                solve_words(ctx, l, obstacles, work)
        except _Unsupported as exc:
            result['unsupported'].append({'layer': l.track, 'why': str(exc)})
            continue
        plans.append(plan)
        obstacles = obstacles + plan['as_obstacles']
    for p in plans:
        result['layers'].append(p['summary'])
        result['changes'] += p['changes']
        result['violations'] += p['violations']
        result['unresolved'] += p['unresolved']
        result['warnings'] += p['warnings']
    return plans, obstacles


def fit(project, tracks=None, platform=None, output=None, style=None, lock=None, min_size_px=None, protected=None,
        faces='auto', placements=None, prefer=None, regroup='auto', native_mode='track', max_lines=None,
        max_cps=20.0, min_duration_s=None, max_duration_s=7.0, keep_together=None, min_gap_em=0.12,
        peak_gap_em=0.04, platform_zones='hard', render_check_frames=True, max_frames=40, work_dir=None):
    """Lay out a project's captions. Returns the proposal (every field is documented in
    caption_layout_tools.letitedit_caption_fit). Nothing in the project is written; renders and previews go to the
    cache (CACHE/caption-fit/<run>)."""
    started = time.monotonic()
    clock = {'t': started}
    timings = {}

    def lap(name):
        now = time.monotonic()
        timings[name] = round(timings.get(name, 0.0) + now - clock['t'], 2)
        clock['t'] = now
    path = es._resolve(project)
    reuse_key = None
    if work_dir is None:
        # A repeated request for the same project revision and settings has the
        # same plan. Validate its sources before skipping all three render passes.
        options = {'tracks': tracks, 'platform': platform, 'output': output, 'style': style, 'lock': lock,
                   'min_size_px': min_size_px, 'protected': protected, 'faces': faces,
                   'placements': placements, 'prefer': prefer, 'regroup': regroup,
                   'native_mode': native_mode, 'max_lines': max_lines, 'max_cps': max_cps,
                   'min_duration_s': min_duration_s, 'max_duration_s': max_duration_s,
                   'keep_together': keep_together, 'min_gap_em': min_gap_em,
                   'peak_gap_em': peak_gap_em, 'platform_zones': platform_zones,
                   'render_check_frames': render_check_frames, 'max_frames': max_frames}
        reuse_key = hashlib.sha256(json.dumps([str(path), es.file_hash(path), options],
                                             sort_keys=True, default=str).encode()).hexdigest()[:24]
        index = CACHE / 'fit-index' / f'{reuse_key}.txt'
        try:
            saved = load_plan(index.read_text(encoding='utf-8').strip())
            if not stale_reasons(saved):
                saved['plan_file'] = str(CACHE / 'plans' / f"{saved['plan_id']}.json")
                saved['seconds'] = round(time.monotonic() - started, 1)
                saved['timings'] = {'cached plan': saved['seconds']}
                saved['cache_hit'] = True
                return saved
        except (OSError, ValueError, KeyError):
            pass
    script = es.read(path)
    timeline = tm.load(path)
    frame = frame_spec(script['profile'], platform, output, min_size_px)
    slots = _fit_slots(faces, frame, native_mode, placements, platform_zones, prefer, regroup)
    work = Path(work_dir) if work_dir else CACHE / f'{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}'
    work.mkdir(parents=True, exist_ok=True)
    layers = find_layers(script, tracks)
    fitted = [l for l in layers if l.fit]
    result = {'schema_version': SCHEMA_VERSION, 'project': str(path), 'project_revision': script['base'],
              'frame': {'width': frame.width, 'height': frame.height, 'fps': round(frame.fps, 4), 'shape': frame.shape,
                        'platform': frame.platform, 'safe': _rbox(frame.safe),
                        'zones': [{'name': z['name'], 'box': _rbox(z['box']), 'status': z['status'],
                                   'confidence': z['confidence']} for z in frame.zones],
                        'min_size_px': round(frame.min_size_px * frame.output_scale, 1),
                        'output_scale': frame.output_scale, 'placements': slots},
              'warnings': list(frame.notes), 'unsupported': [], 'unresolved': [], 'layers': [], 'changes': [],
              'violations': [], 'preview_artifacts': [], 'work_dir': str(work)}
    result['timings'] = timings
    for l in layers:
        for n in l.notes:
            result['unsupported'].append({'layer': l.track, 'why': n})
    if not fitted:
        result['warnings'].append('no caption layer to lay out: a burned-in caption track or a word-caption graphic '
                                  'track with cues')
        return _finish(result, started, [], {})
    opts = dict(lock={str(x).lower() for x in (lock or [])}, style=style or {}, regroup=regroup,
                native_mode=native_mode, max_lines=max_lines, max_cps=float(max_cps), min_duration_s=min_duration_s,
                max_duration_s=float(max_duration_s), keep_together=keep_together or [],
                min_gap_em=float(min_gap_em), peak_gap_em=float(peak_gap_em), slots=slots, prefer=prefer)
    shots = _shots(script)
    holder = {}

    def wordcaps():
        if 'wc' not in holder:
            holder['wc'] = WordCaptions(es.kit_for(script), frame)
        return holder['wc']
    ctx = {'frame': frame, 'opts': opts, 'weights': Weights(), 'script': script, 'kit': es.kit_for(script),
           'cuts': [s for s, _ in shots[1:]], 'shots': shots, 'wordcaps': wordcaps}
    joins = _fit_word_timings(fitted, result, script)
    lap('read and words')
    obstacles, face_info = _fit_obstacles(faces, fitted, frame, lap, layers, max_frames, path, platform_zones,
        protected, result, script, shots, timeline, work)
    _fit_free_area(faces, frame, obstacles, opts, result, script)
    plans, obstacles = _fit_layers(ctx, fitted, joins, result, work, obstacles)
    lap('layout (measure, group, place)')
    if result['changes']:
        check_changes(script, plans, result['changes'])
    lap('edit check')
    if render_check_frames and plans:
        try:
            render_check(path, timeline, frame, plans, obstacles, work, max_frames, result)
        except Exception as exc:  # noqa: BLE001 - a proposal without pictures is still a proposal
            result['warnings'].append(f'render check failed: {type(exc).__name__}: {exc}')
        lap('render check')
    result['faces'] = face_info
    result = _finish(result, started, plans, face_info)
    if reuse_key and result.get('plan_file'):
        try:
            index = CACHE / 'fit-index' / f'{reuse_key}.txt'
            index.parent.mkdir(parents=True, exist_ok=True)
            temp = index.with_suffix(f'.{uuid.uuid4().hex}.tmp')
            temp.write_text(result['plan_id'], encoding='utf-8')
            os.replace(temp, index)
        except OSError:
            pass  # the fit is valid even when the optional cache cannot be written
    return result


def _finish(result, started, plans, face_info):
    def count(vs):
        out = {}
        for v in vs:
            out[v['kind']] = out.get(v['kind'], 0) + 1
        return dict(sorted(out.items()))
    before = [v for v in result['violations'] if v['stage'] == 'before']
    after = [v for v in result['violations'] if v['stage'] == 'after']
    result['summary'] = {'before': count(before), 'after': count(after),
                         'before_total': sum(1 for v in before if v['severity'] != 'info'),
                         'after_total': sum(1 for v in after if v['severity'] != 'info'),
                         'unresolved': len(result['unresolved']), 'changes': len(result['changes'])}
    result['checked_ranges'] = _merge_ranges([(c['start'], c['end']) for p in plans for c in p['cues_after']])
    unchecked = [u for p in plans for u in p.get('unchecked', [])]
    if face_info.get('available') is False:
        unchecked.append({'what': 'faces', 'ranges': result['checked_ranges'], 'why': face_info.get('note')})
    elif face_info.get('uncovered'):
        unchecked.append({'what': 'faces', 'ranges': face_info['uncovered'],
                          'why': 'no face sample within 1.5 s of these captions (raise max_frames)'})
    elif face_info.get('error'):
        unchecked.append({'what': 'faces', 'ranges': result['checked_ranges'], 'why': face_info['error']})
    result['unchecked_ranges'] = unchecked
    result['cues'] = [{'layer': p['summary']['track'], **c} for p in plans for c in p['cues_after']]
    fp = {'project': result['project_revision']}
    if MELT.is_file():
        st = MELT.stat()
        fp['melt'] = f'{st.st_size}-{st.st_mtime_ns}'
    fonts = {}
    for p in plans:
        for f in p.get('fonts', []):
            try:
                st = os.stat(f)
                fonts[f] = f'{st.st_size}-{int(st.st_mtime)}'
            except OSError:
                fonts[f] = 'missing'
    fp['fonts'] = fonts
    for p in plans:
        if p.get('template'):
            fp['word_captions_template'] = p['template']
    for name in ('libmltqt6.dll', 'libmltplus.dll'):
        f = MELT.parent / 'lib' / 'mlt' / name
        if f.exists():
            fp[name] = f'{f.stat().st_size}-{int(f.stat().st_mtime)}'
    if result['frame'].get('platform'):
        try:
            import letitedit.catalogs.platforms as platforms
            fp['platform'] = f"{result['frame']['platform']}@{platforms.load(result['frame']['platform'])['checked']}"
        except Exception:  # noqa: BLE001
            pass
    wh = [p.get('words_hash') for p in plans if p.get('words_hash')]
    if wh:
        fp['words'] = hashlib.sha1('|'.join(wh).encode()).hexdigest()[:12]
    fp['media'] = _media_fingerprint(result['project'])
    result['source_fingerprints'] = fp
    result['plan_id'] = hashlib.sha1(json.dumps({'rev': result['project_revision'], 'fp': fp,
                                                 'changes': result['changes']}, sort_keys=True, default=str)
                                     .encode()).hexdigest()[:16]
    result['seconds'] = round(time.monotonic() - started, 1)
    try:
        d = CACHE / 'plans'
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{result['plan_id']}.json"
        f.write_text(json.dumps(result, default=str, indent=1), encoding='utf-8')
        result['plan_file'] = str(f)
    except OSError:
        pass
    return result


# ============================================================================ applying a plan

def _media_fingerprint(project):
    """Size and time of every media file the project uses (faces and pictures were measured on them)."""
    h = hashlib.sha1()
    try:
        root = ET.parse(project).getroot()
        folder = Path(project).resolve().parent
        files = set()
        for p in root.iter('property'):
            if p.get('name') in ('resource', 'warp_resource') and p.text:
                f = Path(p.text.strip())
                f = f if f.is_absolute() else folder / f
                if f.is_file():
                    files.add(str(f.resolve()))
        for f in sorted(files):
            st = os.stat(f)
            h.update(f'{f}:{st.st_size}:{int(st.st_mtime)}'.encode())
    except (OSError, ET.ParseError):
        return None
    return h.hexdigest()[:16]


def load_plan(plan_id):
    f = CACHE / 'plans' / f'{plan_id}.json'
    if not f.exists():
        raise FileNotFoundError(f'no caption-fit plan {plan_id} (plans are kept in {CACHE / "plans"})')
    return json.loads(f.read_text(encoding='utf-8-sig'))


def stale_reasons(plan):
    """Why a plan no longer matches its project and what it measured (empty when it still does)."""
    out = []
    path = Path(plan['project'])
    if not path.exists():
        return [f'the project {path} is gone']
    if es.file_hash(path) != plan['project_revision']:
        out.append('the project changed since the proposal (run letitedit_caption_fit again)')
    fp = plan.get('source_fingerprints') or {}
    for f, sig in (fp.get('fonts') or {}).items():
        try:
            st = os.stat(f)
            now = f'{st.st_size}-{int(st.st_mtime)}'
        except OSError:
            now = 'missing'
        if now != sig:
            out.append(f'font file changed: {f}')
    for name in ('libmltqt6.dll', 'libmltplus.dll'):
        if name in fp:
            f = MELT.parent / 'lib' / 'mlt' / name
            now = f'{f.stat().st_size}-{int(f.stat().st_mtime)}' if f.exists() else 'missing'
            if now != fp[name]:
                out.append(f'the text engine changed ({name})')
    if fp.get('melt'):
        st = MELT.stat() if MELT.is_file() else None
        now = f'{st.st_size}-{st.st_mtime_ns}' if st else 'missing'
        if now != fp['melt']:
            out.append('the export engine changed')
    if fp.get('media') and _media_fingerprint(plan['project']) != fp['media']:
        out.append('a media file the project uses changed (faces and pictures were measured on the old one)')
    if fp.get('platform'):
        try:
            import letitedit.catalogs.platforms as platforms
            name = fp['platform'].split('@', 1)[0]
            now = f"{name}@{platforms.load(name)['checked']}"
            if now != fp['platform']:
                out.append('the platform covered areas changed')
        except Exception:  # noqa: BLE001
            out.append('the platform covered areas could not be checked')
    if fp.get('word_captions_template'):
        try:
            import letitedit.pictures.graphics as graphics
            import letitedit.looks.style_pack as style_pack
            mod = graphics._resolve_template({'template': 'word_captions'}, style_pack.load())
            now = hashlib.sha1(Path(mod.__file__).read_bytes()).hexdigest()[:12]
            if now != fp['word_captions_template']:
                out.append('the word_captions template changed')
        except Exception:  # noqa: BLE001
            pass
    return out


def faces_covered(plan):
    """(now, with the plan): captions over a face, from the plan's own count."""
    summary = plan.get('summary') or {}
    return ((summary.get('before') or {}).get('covers_face', 0), (summary.get('after') or {}).get('covers_face', 0))


def _word_times(script, names):
    """Every word of the word-caption tracks with where it plays: [(word, seconds)], in time order."""
    from letitedit.timeline.edit_sync import layout
    out = []
    for track in script['tracks']:
        if track['name'] in names:
            for item, start, _ in layout(track):
                graphic = item.get('graphic') or {}
                if graphic.get('template') == 'word_captions':
                    out += [(str(w[0]), start + float(w[1])) for w in (graphic.get('params') or {}).get('words') or []]
    return sorted(out, key=lambda w: w[1])


def _refuse_lost_words(plan, before):
    """Regrouping replaces caption items, so the changes can hold deletes. Every word must still be there afterwards,
    in order and when it was said; otherwise a delete is a caption gone, and nothing is written."""
    after, _ = es.edit(before, [dict(c) for c in plan.get('changes') or []])
    frame = 1.5 / float((before.get('profile') or {}).get('fps') or 30)
    for layer in plan.get('layers', []):
        if layer.get('kind') != 'words':
            continue
        old = _word_times(before, {layer['track'], *(layer.get('siblings') or [])})
        new = _word_times(after, set(layer.get('tracks_out') or []) | {layer['track'], *(layer.get('siblings') or [])})
        if ''.join(w for w, _ in old).replace(' ', '') != ''.join(w for w, _ in new).replace(' ', ''):
            raise Refused(f'Not applied, the project is unchanged: this plan would remove or change words in the captions '
                          f'on {layer["track"]} ({len(old)} words now, {len(new)} after).')
        if len(old) == len(new):
            moved = [(a, b) for a, b in zip(old, new) if abs(a[1] - b[1]) > frame]
            if moved:
                raise Refused(f'Not applied, the project is unchanged: this plan would move {len(moved)} words of '
                              f'{layer["track"]} away from when they are said, first "{moved[0][0][0]}" at '
                              f'{moved[0][0][1]:.2f} s to {moved[0][1][1]:.2f} s.')


def apply_plan(plan_or_id, expected_revision=None, via='shared', label='Caption fit', actor=None,
               keep_history=True):
    """Apply a proposal's changes. via='shared' is letitedit_timeline_apply's path (an open letitedit window gets one
    undo step, otherwise the file is written with an undo copy); via='file' writes the saved file only. Refuses a plan
    whose project or measured sources changed (Conflict). An open window takes the cues and the caption style as one undo
    step (a window of an older build can't take a style: letitedit_timeline_apply's path says what it does). keep_history=False (via='file' only): no undo copy of its own, so the
    edit before it stays the undo point (T360's captions that follow an edit). Returns the apply result and, per
    layer, whether every word is kept."""
    plan = load_plan(plan_or_id) if isinstance(plan_or_id, str) else plan_or_id
    if expected_revision and expected_revision != plan['project_revision']:
        raise Conflict(f"expected_revision {expected_revision} is not the plan's project revision "
                       f"{plan['project_revision']}")
    why = stale_reasons(plan)
    if why:
        raise Conflict('; '.join(why))
    changes = plan.get('changes') or []
    if not changes:
        return {'applied': False, 'note': 'the plan has no changes'}
    now, then = faces_covered(plan)
    if then > now:
        raise Refused(f'Not applied, the project is unchanged: this plan covers more faces than the captions do now, '
                      f"{then} against {now} (captions over a face, by this plan's own count). "
                      "Options: platform_zones=soft (captions may then sit under the app's buttons instead of on the face), "
                      f'or keep the current layout.')
    path = plan['project']
    before = es.read(path)
    _refuse_lost_words(plan, before)
    if via == 'file':
        import letitedit.review.review_bundle as review_bundle
        refused = review_bundle.edit_after_handover(es._resolve(path))   # as letitedit_timeline_apply's route
        if refused:
            raise Refused(refused)
        res = es.apply_changes(path, ops=[dict(c) for c in changes], actor=actor, label=label,
                               keep_history=keep_history)
    else:
        import letitedit.server.timeline_tools as timeline_tools
        res, _ = timeline_tools.apply_project(path, [dict(c) for c in changes], check=False, label=label, actor=actor)
    after = es.read(path)
    kept = []
    for layer in plan.get('layers', []):
        names = set(layer.get('tracks_out') or []) | {layer['track'], *(layer.get('siblings') or [])}
        b = _expected_tokens(layer_tokens(before, {layer['track'], *(layer.get('siblings') or [])}, layer['kind']),
                             layer.get('token_fixes'))
        a = layer_tokens(after, names, layer['kind'])
        kept.append({'track': layer['track'], 'words_before': len(b), 'words_after': len(a), 'identical': a == b})
    return {'applied': True, 'plan_id': plan.get('plan_id'), 'result': res, 'words_kept': kept}
