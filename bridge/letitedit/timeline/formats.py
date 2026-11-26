"""Linked versions of a project for other sizes and aspects (one project, every format).

make(main, target, ranges=None, name=None, ...) -> a new .mlt beside the main project at the target size, holding the
    chosen ranges of the main timeline (main-timeline seconds; none = all). Every picture clip gets a reframe: a
    Size, Position & Rotate effect (Shotcut's affineSizePosition filter) that fills the new frame and is placed on
    the subject (tracker boxes, else the footage analysis' action point for that span, else the centre, in the
    order given by `reframe['order']`).
sync(version, ...)  -> carries the main project's changes since the version was made (or last synced) into the
    version, inside its ranges, by stable item id; items the version changed itself are never overwritten.
list_versions(main_or_folder) -> the versions made from a project, with whether the main changed since.

The link is kept in the version's own folder <version stem>.letitedit\\version.json: the main project and its file hash
at make/sync, the ranges (main seconds), the piece map (version item id -> main item id, track, range), the reframe of
every item (method, source, rect or keyframes), the settings used, the main's timeline as it was (edit script) and the
version's timeline as made (edit script), and a list of syncs. The main's folder <main stem>.letitedit\\versions.json
lists the versions made from it.
"""
from __future__ import annotations

import copy
import datetime
import glob
import json
import math
import os
import re
import tempfile
from pathlib import Path

import letitedit.timeline.edit_script as es
from letitedit.timeline.edit_sync import layout, main_track, mapper

LINK_FORMAT = 'letitedit-version/1'
LINK_FILE = 'version.json'
INDEX_FILE = 'versions.json'
NAMED_SIZES = {'vertical': (1080, 1920), '9:16': (1080, 1920), 'portrait': (1080, 1350), '4:5': (1080, 1350),
               'square': (1080, 1080), '1:1': (1080, 1080), 'horizontal': (1920, 1080), '16:9': (1920, 1080),
               'landscape': (1920, 1080)}

# Every number used when reframing; each is a parameter of make/sync (reframe={...}) and reported in the result.
REFRAME_DEFAULTS = {
    'order': ['given', 'track', 'action', 'centre'],  # sources tried for each moment of a clip, first that has data wins
    'fit': 'fill',          # fill: the picture covers the whole new frame (cropped); fit: the whole picture shows (bars)
    'zoom': 1.0,            # extra scale on top of fill/fit (1 = just fills / just fits)
    'key_every_s': 0.5,     # spacing of reframe keyframes when the subject moves (clip seconds)
    'smooth_s': 1.0,        # moving-average window over the subject point (seconds; 0 = none)
    'deadzone': 0.03,       # the frame stays put until the subject point has moved this fraction of the source size
    'min_score': 0.3,       # tracker samples under this confidence are not used
    'track_search': True,   # also look for saved tracker results (letitedit_track JSON files) in track_folder
    'track_folder': str(Path(tempfile.gettempdir()) / 'letitedit_ai' / 'track'),
    'analyse': False,       # run the footage picture analysis for clips that have none cached (else: cached only)
    'text_scale': 'min',    # text sizes (captions, text effects) x min(new w / old w, new h / old h), or a number
    # 'follow': one subject point per moment (the sources in `order`, smoothed) - the original way, the default.
    # 'solve': reframe.py keeps several subjects in the crop (faces, motion, given boxes) on a smooth path and
    # reports where they can't share it; the five keys below are its options (see reframe.version_item).
    'mode': 'follow',
    'keep': None,           # solve: subjects to keep, in rank order: names ('face', 'hands') or {label, box, at}
    'priorities': None,     # solve: {subject: required | preferred | optional | ignore}
    'sources': None,        # solve: automatic subject finders (default face, action, track)
    'platform': None,       # solve: keep required subjects out of this platform's covered areas
    'solver': None,         # solve: reframe.DEFAULTS overrides (zoom range, margin, calm, ...)
}
TOL = 1e-3


# ---------------------------------------------------------------------------- small helpers

def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _r(x, nd=4):
    return round(float(x), nd)


def _norm(p):
    return os.path.normcase(os.path.abspath(str(p)))


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def link_path(version):
    import letitedit.timeline.project_journal as pj
    return pj.folder(Path(version).resolve()) / LINK_FILE


def index_path(main):
    import letitedit.timeline.project_journal as pj
    return pj.folder(Path(main).resolve()) / INDEX_FILE


def _cmp(item, with_at=False):
    drop = {'len', 'from', 'said', 'recorded', 'pin'} | (set() if with_at else {'at'})
    out = {k: v for k, v in item.items() if k not in drop}
    if with_at and 'at' in item:
        out['at'] = _r(es.to_seconds(item['at']), 2)
    return json.dumps(out, sort_keys=True, default=str)


def _items_by_id(script):
    out = {}
    for t in script.get('tracks', []):
        for it in t.get('items', []):
            if it.get('id') is not None:
                out[it['id']] = (t['name'], it)
    return out


def _effect_key(e):
    return e if isinstance(e, str) else next(iter(e), None)


# ---------------------------------------------------------------------------- target size

def resolve_target(target, fps=None):
    """(width, height, info) for 'WxH', [w, h], a named aspect ('vertical', '4:5', ...) or a platform profile."""
    info = {}
    if isinstance(target, (list, tuple)) and len(target) == 2:
        w, h = int(target[0]), int(target[1])
    elif isinstance(target, dict):
        w, h = int(target['width']), int(target['height'])
    else:
        text = str(target).strip()
        m = re.fullmatch(r'(\d+)\s*[x:*X]\s*(\d+)', text)
        if m and int(m.group(1)) >= 64:
            w, h = int(m.group(1)), int(m.group(2))
        elif text.lower() in NAMED_SIZES:
            w, h = NAMED_SIZES[text.lower()]
            info['named'] = text.lower()
        else:
            import letitedit.catalogs.platforms as platforms
            p = platforms.preset_for(text)
            if not p.get('width') or not p.get('height'):
                raise ValueError(f'platform {text!r} publishes no export size; give target as WxH')
            w, h = int(p['width']), int(p['height'])
            info.update(platform=p['platform'], platform_name=p['name'], platform_fps=p.get('fps'),
                        checked=p.get('checked'))
    if w < 16 or h < 16:
        raise ValueError(f'target size {w}x{h} is too small')
    w, h = w // 2 * 2, h // 2 * 2
    return w, h, info


def _set_profile(path, width, height, fps=None):
    """Change the profile of a project file in place (a new version file only)."""
    import xml.etree.ElementTree as ET
    tree = ET.parse(path)
    prof = tree.getroot().find('profile')
    g = math.gcd(width, height)
    prof.set('width', str(width))
    prof.set('height', str(height))
    prof.set('sample_aspect_num', '1')
    prof.set('sample_aspect_den', '1')
    prof.set('display_aspect_num', str(width // g))
    prof.set('display_aspect_den', str(height // g))
    if fps:
        from fractions import Fraction
        fr = Fraction(float(fps)).limit_denominator(1001)
        prof.set('frame_rate_num', str(fr.numerator))
        prof.set('frame_rate_den', str(fr.denominator))
    num, den = int(prof.get('frame_rate_num', 30)), int(prof.get('frame_rate_den', 1))
    prof.set('description', f'{width}x{height} {num / den:g} fps')
    ET.indent(tree, space='  ')
    tree.write(path, encoding='utf-8', xml_declaration=True)


# ---------------------------------------------------------------------------- ranges and pieces

def _ranges(ranges, total):
    """[[a, b], ...] in main seconds (clipped to the timeline); empty/None = the whole timeline."""
    if not ranges:
        return [[0.0, _r(total)]]
    if isinstance(ranges, (list, tuple)) and len(ranges) == 2 and not isinstance(ranges[0], (list, tuple, dict)):
        ranges = [ranges]
    out = []
    for r in ranges:
        if isinstance(r, dict):
            a, b = r.get('start', r.get('from', 0)), r.get('end', r.get('to', total))
        else:
            a, b = r[0], r[1]
        a = max(0.0, es.to_seconds(a))
        b = min(float(total), es.to_seconds(b))
        if b - a <= TOL:
            raise ValueError(f'range {r!r} is empty on a {total:.3f} s timeline')
        out.append([_r(a), _r(b)])
    return out


def _total(script):
    end = 0.0
    for t in script['tracks']:
        lay = layout(t)
        if lay:
            end = max(end, lay[-1][2])
    return end


def _shift_keys(effect, dt, length):
    """A keyed effect moved dt seconds earlier (a piece that starts dt into its clip); keys before 0 are dropped,
    keeping the value at 0 from the last one before it."""
    if not isinstance(effect, dict) or dt <= TOL:
        return effect
    out = copy.deepcopy(effect)
    for k, v in out.items():
        if isinstance(v, dict) and isinstance(v.get('keys'), list):
            keys = v['keys']
            before = [x for x in keys if float(x[0]) <= dt + TOL]
            after = [[_r(float(x[0]) - dt, 3)] + list(x[1:]) for x in keys if float(x[0]) > dt + TOL]
            if before:
                after.insert(0, [0.0] + list(before[-1][1:]))
            v['keys'] = after
    return out


def _cut_item(it, s, e, lo, hi, notes, tname):
    """The part [lo, hi] (main seconds) of an item that sits at [s, e]; None when it can't be cut."""
    p = copy.deepcopy(it)
    for k in ('at', 'pin', 'len'):
        p.pop(k, None)
    head, tail = lo - s, e - hi
    if 'in' in p and 'out' in p:
        sp = float(p.get('speed', 1.0))
        a0 = es.to_seconds(p['in'])
        p['in'] = _r(a0 + head * sp)
        p['out'] = _r(a0 + (hi - s) * sp)
    elif head > TOL or tail > TOL:
        if 'graphic' in p or 'color' in p or 'adjust' in p:
            p['len'] = _r(hi - lo)
        else:
            notes.append(f'{it.get("id")} on {tname}: only part of it is in a range and it has no in/out; left out')
            return None
    else:
        if 'len' in it and ('graphic' in p or 'raw' in p or 'color' in p or 'adjust' in p or 'scene' in p):
            p['len'] = it['len']
    effs = []
    for eff in p.get('effects') or []:
        key = _effect_key(eff)
        if head > TOL and key in ('fade_in', 'fade_in_audio'):
            continue
        if tail > TOL and key in ('fade_out', 'fade_out_audio'):
            continue
        effs.append(_shift_keys(eff, head, hi - lo))
    if effs:
        p['effects'] = effs
    else:
        p.pop('effects', None)
    return p


def pieces(main_script, ranges):
    """The version's tracks and captions (no reframe yet) from a main script and ranges in main seconds.
    Returns (script, piece_map, notes)."""
    fps = float(main_script['profile']['fps'])
    frame = 1.0 / fps
    out = {k: copy.deepcopy(v) for k, v in main_script.items() if k not in ('tracks', 'captions', 'project', 'base',
                                                                            'length', 'partial')}
    out['tracks'] = []
    pmap, notes = {}, []
    used = {}
    offsets, pos = [], 0.0
    for a, b in ranges:
        offsets.append(pos)
        pos += b - a
    main_t = main_track(main_script)
    for t in main_script['tracks']:
        nt = {k: copy.deepcopy(v) for k, v in t.items() if k != 'items'}
        nt.pop('partial', None)
        is_main = t is main_t
        placed = []      # (version start, version end, piece, had transition)
        lay = layout(t)
        for ri, (a, b) in enumerate(ranges):
            prev_piece = None
            for it, s, e in lay:
                lo, hi = max(s, a), min(e, b)
                if hi - lo < frame - 1e-6:
                    continue
                p = _cut_item(it, s, e, lo, hi, notes, t['name'])
                if p is None:
                    continue
                if p.get('transition'):
                    tl = es.to_seconds(p['transition']['len'] if isinstance(p['transition'], dict) else p['transition'])
                    ok = (s >= a - TOL and prev_piece is not None and prev_piece[1] - prev_piece[0] > tl + frame
                          and abs(prev_piece[1] - (offsets[ri] + (s - a) + tl)) < 2 * frame)
                    if not ok:
                        p.pop('transition')
                        notes.append(f'{it.get("id")} on {t["name"]}: its transition is cut by the range start; '
                                     'left out in the version')
                mid = it.get('id')
                n = used.get(mid, 0) + 1
                used[mid] = n
                pid = mid if n == 1 else f'{mid}~{n}'
                p['id'] = pid
                vs = offsets[ri] + (lo - a)
                ve = vs + (hi - lo)
                pmap[pid] = {'main_id': mid, 'track': t['name'], 'range': ri, 'main_start': _r(lo), 'main_end': _r(hi),
                             'cut_head': _r(lo - s), 'cut_tail': _r(e - hi)}
                placed.append((vs, ve, p))
                prev_piece = (vs, ve)
        items, cur = [], 0.0
        for vs, ve, p in placed:
            if vs > cur + frame / 2:
                items.append({'gap': _r(vs - cur)})
                cur = vs
            if not is_main and not p.get('transition'):
                p['at'], p['pin'] = es.clock(vs), True
            items.append(p)
            cur = max(cur, ve)
        nt['items'] = items
        out['tracks'].append(nt)
    caps = []
    for cap in main_script.get('captions', []):
        nc = {k: copy.deepcopy(v) for k, v in cap.items() if k != 'cues'}
        cues = []
        for ri, (a, b) in enumerate(ranges):
            for q in cap['cues']:
                qa, qb = es.to_seconds(q['start']), es.to_seconds(q['end'])
                lo, hi = max(qa, a), min(qb, b)
                if hi - lo < frame - 1e-6:
                    continue
                cues.append({'start': es.clock(offsets[ri] + lo - a), 'end': es.clock(offsets[ri] + hi - a),
                             'text': q['text']})
        nc['cues'] = cues
        caps.append(nc)
    if caps:
        out['captions'] = caps
    return out, pmap, notes


# ---------------------------------------------------------------------------- where the subject is

def _source_size(path):
    import letitedit.server.core_tools as core_tools
    info = core_tools.probe(path)
    w, h = int(info.get('width') or 0), int(info.get('height') or 0)
    return (w, h) if w and h else None


def _track_runs(clip, settings, given=()):
    """Tracker results for a file: [(t0, t1, frames)] from given results/JSON paths and the tracker's folder."""
    runs = []
    files = []
    for g in given or ():
        if isinstance(g, dict):
            data = g
            if 'frames' not in data and data.get('json'):
                data = _read_json(data['json'], {}) or {}
            if 'frames' not in data and 'boxes' in g:
                data = {'file': g.get('file'), 'frames': g['boxes']}
            if data.get('file') and _norm(data['file']) == _norm(clip) and data.get('frames'):
                runs.append((0, data, '(given)'))
        else:
            files.append(str(g))
    if settings.get('track_search') and settings.get('track_folder'):
        stem = Path(clip).stem
        files += glob.glob(os.path.join(settings['track_folder'], '*', f'track-{glob.escape(stem)}-*.json'))
    for f in files:
        data = _read_json(f, {}) or {}
        if data.get('file') and _norm(data['file']) == _norm(clip) and data.get('frames'):
            try:
                mt = os.path.getmtime(f)
            except OSError:
                mt = 0
            runs.append((mt, data, f))
    runs.sort(key=lambda r: -r[0])          # newest first
    return [(float(d['frames'][0][0]), float(d['frames'][-1][0]), d['frames'], src) for _, d, src in runs]


def _action_spans(clip, settings):
    """[(a, b, x, y)] action points of steady spans from the footage picture analysis (cached unless analyse)."""
    import letitedit.footage.perception as perception
    try:
        if not settings.get('analyse') and not perception.is_cached('motion', clip):
            return None
        res = perception.picture(clip)
    except Exception:  # noqa: BLE001
        return None
    out = []
    for sp in res.get('spans') or []:
        for extra in sp[3:]:
            m = re.search(r'\(x ([\d.]+), y ([\d.]+)', str(extra))
            if m:
                out.append((float(sp[0]), float(sp[1]), float(m.group(1)), float(m.group(2))))
    return out


def _given_point(given, t_clip):
    """A given focus: [x, y] or [[t, x, y], ...] (clip seconds); linear between keys."""
    if given is None:
        return None
    if len(given) == 2 and not isinstance(given[0], (list, tuple)):
        return float(given[0]), float(given[1])
    keys = sorted(given, key=lambda k: float(k[0]))
    if t_clip <= float(keys[0][0]):
        return float(keys[0][1]), float(keys[0][2])
    for k0, k1 in zip(keys, keys[1:]):
        if float(k0[0]) <= t_clip <= float(k1[0]):
            f = (t_clip - float(k0[0])) / max(1e-9, float(k1[0]) - float(k0[0]))
            return (float(k0[1]) + f * (float(k1[1]) - float(k0[1])), float(k0[2]) + f * (float(k1[2]) - float(k0[2])))
    return float(keys[-1][1]), float(keys[-1][2])


def _track_point(runs, src_t, min_score, max_dt):
    for t0, t1, frames, _src in runs:
        if t0 - max_dt <= src_t <= t1 + max_dt:
            best = min(frames, key=lambda r: abs(float(r[0]) - src_t))
            if abs(float(best[0]) - src_t) <= max_dt and float(best[5] if len(best) > 5 else 1.0) >= min_score:
                return (float(best[1]) + float(best[3])) / 2, (float(best[2]) + float(best[4])) / 2, _src
    return None


def _smooth(vals, window_n):
    if window_n <= 1:
        return list(vals)
    half = window_n // 2
    out = []
    for i in range(len(vals)):
        seg = vals[max(0, i - half):i + half + 1]
        out.append(sum(seg) / len(seg))
    return out


def _deadzone(vals, dz):
    if dz <= 0 or not vals:
        return list(vals)
    out, cur = [], vals[0]
    for v in vals:
        if abs(v - cur) > dz:
            cur = v - math.copysign(dz, v - cur)
        out.append(cur)
    return out


def _rect(cx, cy, src_w, src_h, out_w, out_h, settings):
    """The size/position rect (version pixels) that shows the source with point (cx, cy) as near the middle as the
    frame allows."""
    if settings['fit'] == 'fit':
        k = min(out_w / src_w, out_h / src_h)
    else:
        k = max(out_w / src_w, out_h / src_h)
    k *= float(settings['zoom'])
    dw, dh = src_w * k, src_h * k
    x = out_w / 2 - cx * dw
    y = out_h / 2 - cy * dh
    x = min(0.0, max(out_w - dw, x)) if dw >= out_w else (out_w - dw) / 2
    y = min(0.0, max(out_h - dh, y)) if dh >= out_h else (out_h - dh) / 2
    return [round(x, 1), round(y, 1), round(dw, 1), round(dh, 1)]


def reframe_item(item, out_w, out_h, fps, settings, given_focus=None, track_given=()):
    """(effect, record) for one picture clip: a size_position effect and how it was chosen; (None, record) when the
    item is not a picture clip."""
    if settings.get('mode') == 'solve':
        import letitedit.pictures.reframe as reframe
        return reframe.version_item(item, out_w, out_h, fps, settings, given_focus, track_given)
    clip = item.get('clip')
    size = _source_size(clip) if clip else None
    if not size:
        return None, {'method': 'none', 'why': 'no picture size (not a video/image clip)'}
    src_w, src_h = size
    a = es.to_seconds(item.get('in', 0))
    b = es.to_seconds(item.get('out', a))
    sp = float(item.get('speed', 1.0))
    length = max(1.0 / fps, (b - a) / sp)
    step = max(1.0 / fps, float(settings['key_every_s']))
    n = max(1, int(math.floor(length / step + 1e-6)))
    times = [min(length, i * step) for i in range(n + 1)]
    if times[-1] < length - 1e-6:
        times.append(length)
    order = list(settings['order'])
    runs = _track_runs(clip, settings, track_given) if 'track' in order else []
    actions = _action_spans(clip, settings) if 'action' in order else None
    max_dt = max(step, 2.0 / fps)
    xs, ys, used, sources = [], [], {}, set()
    for t in times:
        src_t = a + t * sp
        pt, how = None, None
        for m in order:
            if m == 'given' and given_focus is not None:
                pt, how = _given_point(given_focus, t), 'given'
            elif m == 'track' and runs:
                got = _track_point(runs, src_t, float(settings['min_score']), max_dt)
                if got:
                    pt, how = got[:2], 'track'
                    sources.add(got[2])
            elif m == 'action' and actions:
                hit = next(((x, y) for sa, sb, x, y in actions if sa - TOL <= src_t < sb + TOL), None)
                if hit:
                    pt, how = hit, 'action'
            elif m in ('centre', 'center'):
                pt, how = (0.5, 0.5), 'centre'
            if pt is not None:
                break
        if pt is None:
            pt, how = (0.5, 0.5), 'centre'
        xs.append(min(1.0, max(0.0, float(pt[0]))))
        ys.append(min(1.0, max(0.0, float(pt[1]))))
        used[how] = used.get(how, 0) + 1
    win = int(round(float(settings['smooth_s']) / step)) | 1 if float(settings['smooth_s']) > 0 else 1
    xs, ys = _smooth(xs, win), _smooth(ys, win)
    xs, ys = _deadzone(xs, float(settings['deadzone'])), _deadzone(ys, float(settings['deadzone']))
    rects = [_rect(x, y, src_w, src_h, out_w, out_h, settings) for x, y in zip(xs, ys)]
    method = max(used, key=used.get)
    rec = {'method': method, 'share': {k: _r(v / len(times), 3) for k, v in used.items()},
           'source_size': [src_w, src_h], 'clip_seconds': [_r(a), _r(b)]}
    if sources:
        rec['track_results'] = sorted(sources)
    if actions is None and 'action' in order:
        rec['action'] = 'no picture analysis cached for this file (reframe analyse=True runs it)'
    if all(max(abs(r[i] - rects[0][i]) for i in range(4)) < 0.5 for r in rects):
        rec['rect'] = rects[0]
        rec['point'] = [_r(xs[0], 3), _r(ys[0], 3)]
        eff = {'size_position': ' '.join(f'{v:g}' for v in rects[0])}
    else:
        keys, last = [], None
        for t, r in zip(times, rects):
            if last is None or max(abs(r[i] - last[i]) for i in range(4)) >= 0.5 or t == times[-1]:
                keys.append([_r(t, 3), ' '.join(f'{v:g}' for v in r)])
                last = r
        rec['keys'] = len(keys)
        rec['points'] = [[_r(t, 2), _r(x, 3), _r(y, 3)] for t, x, y in zip(times, xs, ys)]
        eff = {'size_position': {'keys': keys}}
    return eff, rec


# ---------------------------------------------------------------------------- applying the new size

def _scale_box(geom, sx, sy):
    vals = str(geom).split()
    try:
        x, y, w, h = [float(v.rstrip('%')) for v in vals[:4]]
    except ValueError:
        return geom
    if any(v.endswith('%') for v in vals[:4]):
        return geom
    rest = vals[4:]
    return ' '.join([f'{round(x * sx)}', f'{round(y * sy)}', f'{round(w * sx)}', f'{round(h * sy)}'] + rest)


def _scale_text_style(style, sx, sy, k):
    st = dict(style)
    if 'geometry' in st and '=' not in str(st['geometry']):
        st['geometry'] = _scale_box(st['geometry'], sx, sy)
    for key in ('size', 'outline', 'pad'):
        if key in st:
            try:
                st[key] = str(round(float(st[key]) * k))
            except (TypeError, ValueError):
                pass
    return st


def _scale_rect_text(rect, sx, sy, k):
    vals = [float(v) for v in str(rect).split()]
    x, y, w, h = vals[:4]
    cx, cy = (x + w / 2) * sx, (y + h / 2) * sy
    nw, nh = w * k, h * k
    return ' '.join(f'{round(v, 1):g}' for v in [cx - nw / 2, cy - nh / 2, nw, nh] + vals[4:])


def _fit_effects(item, sx, sy, k, notes):
    """Text and size/position effects moved to the new frame (positions by the frame's change, sizes by k)."""
    effs, own_rect = [], False
    for eff in item.get('effects') or []:
        if isinstance(eff, dict) and 'text' in eff and isinstance(eff.get('style'), dict):
            eff = dict(eff, style=_scale_text_style(eff['style'], sx, sy, k))
        elif isinstance(eff, dict) and 'size_position' in eff:
            own_rect = True
            r = eff['size_position']
            if isinstance(r, dict) and r.get('keys'):
                eff = {'size_position': {'keys': [[kk[0], _scale_rect_text(kk[1], sx, sy, k)] + list(kk[2:])
                                                  for kk in r['keys']]}}
            elif isinstance(r, str):
                eff = {'size_position': _scale_rect_text(r, sx, sy, k)}
        effs.append(eff)
    if effs:
        item['effects'] = effs
    return own_rect


def _picture_track(t):
    return t.get('kind', 'video') == 'video'


def _reframe_script(script, pmap, out_w, out_h, in_w, in_h, settings, focus, track_given, only=None,
                    captions=True):
    """Adds the reframe effect to every picture clip (only: a set of item ids). Returns {item id: record}."""
    fps = float(script['profile']['fps'])
    sx, sy = out_w / in_w, out_h / in_h
    k = min(sx, sy) if settings['text_scale'] == 'min' else float(settings['text_scale'])
    records = {}
    for t in script['tracks']:
        for it in t['items']:
            iid = it.get('id')
            if iid is None or (only is not None and iid not in only):
                continue
            notes = []
            own = _fit_effects(it, sx, sy, k, notes)
            if not _picture_track(t):
                continue
            if own:
                records[iid] = {'method': 'own size_position', 'why': 'the item has its own Size/Position effect; '
                                'its rectangle was moved to the new frame (centre by the frame change, size x '
                                f'{k:.3f}) and no reframe was added'}
                continue
            if 'clip' not in it:
                records[iid] = {'method': 'none', 'why': 'not a clip (graphic, colour or made item): unchanged'}
                continue
            main_id = (pmap.get(iid) or {}).get('main_id', iid)
            given = (focus or {}).get(iid, (focus or {}).get(main_id))
            eff, rec = reframe_item(it, out_w, out_h, fps, settings, given, track_given)
            if eff is not None:
                it['effects'] = [eff] + list(it.get('effects') or [])
                rec['effect'] = eff
            records[iid] = rec
    for cap in script.get('captions', []) if captions else []:
        if isinstance(cap.get('style'), dict):
            cap['style'] = _scale_text_style(cap['style'], sx, sy, k)
    return records


def _settings(reframe):
    s = copy.deepcopy(REFRAME_DEFAULTS)
    for key, v in (reframe or {}).items():
        if key not in s:
            raise ValueError(f'unknown reframe setting {key!r}; settings: {", ".join(s)}')
        s[key] = v
    if s['fit'] not in ('fill', 'fit'):
        raise ValueError("reframe fit is 'fill' or 'fit'")
    if s['mode'] not in ('follow', 'solve'):
        raise ValueError("reframe mode is 'follow' (one subject point, default) or 'solve' (several subjects, "
                         "reframe.py)")
    s['order'] = [str(m).lower() for m in s['order']]
    bad = [m for m in s['order'] if m not in ('given', 'track', 'action', 'centre', 'center')]
    if bad:
        raise ValueError(f'reframe order: unknown source(s) {bad}; sources: given, track, action, centre')
    return s


# ---------------------------------------------------------------------------- make

def _version_path(main, name, folder=None):
    main = Path(main)
    slug = re.sub(r'[^A-Za-z0-9._ -]+', '-', str(name)).strip(' .-') or 'version'
    return (Path(folder) if folder else main.parent) / f'{main.stem} - {slug}.mlt'


def make(main, target, ranges=None, name=None, path=None, fps=None, reframe=None, focus=None, tracks=None,
         actor=None):
    """A linked version of `main` at `target` size covering `ranges` (main-timeline seconds; none = all).
    focus: {item id: [x, y] | [[t, x, y], ...]} subject points (0-1 of the picture; t in clip seconds) used where the
    reframe order says 'given'. tracks: tracker results (letitedit_track result dicts or their JSON files).
    Returns the version path, link file, pieces, reframes and notes."""
    import letitedit.timeline.project_journal as pj
    main_path = es._resolve(main)
    w, h, tinfo = resolve_target(target)
    settings = _settings(reframe)
    ms = es.read(main_path)
    total = _total(ms)
    rr = _ranges(ranges, total)
    label = name or (tinfo.get('platform') or f'{w}x{h}')
    vpath = Path(path) if path else _version_path(main_path, label)
    if vpath.suffix.lower() != '.mlt':
        vpath = vpath / _version_path(main_path, label).name
    if vpath.exists():
        raise FileExistsError(f'{vpath} already exists; choose another name or path')
    if _norm(vpath) == _norm(main_path):
        raise ValueError('the version path is the main project')
    script, pmap, notes = pieces(ms, rr)
    in_w, in_h = ms['profile']['width'], ms['profile']['height']
    records = _reframe_script(script, pmap, w, h, in_w, in_h, settings, focus, tracks or ())
    who = pj.actor(actor)
    vpath.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(main_path, vpath)
    try:
        import letitedit.pictures.code_scenes as code_scenes
        code_scenes.copy_scenes(main_path, vpath)    # its markers name scenes kept beside the project: the copy needs its own
        _set_profile(vpath, w, h, fps)
        # the copy carries the main's folder records only through this link (journal, history, lease are its own)
        script['project'] = str(vpath)
        script.pop('base', None)
        with pj.writing(vpath, who):
            es.compile_script(script, base=vpath, out=vpath, force=True)
    except Exception:
        try:
            os.remove(vpath)
        except OSError:
            pass
        raise
    notes += script.pop('_render_notes', [])
    made = es.read(vpath)
    link = {'format': LINK_FORMAT, 'name': label, 'version': str(vpath), 'main': str(main_path),
            'main_base': ms['base'], 'made': _now(), 'made_by': who, 'synced': None,
            'target': {'width': w, 'height': h, 'fps': made['profile']['fps'], **tinfo},
            'main_size': [in_w, in_h], 'ranges': rr, 'ranges_as_made': rr, 'whole': not ranges, 'settings': settings,
            'focus': focus or {}, 'tracks_given': [t if isinstance(t, str) else t.get('json') for t in (tracks or [])],
            'pieces': pmap, 'reframe': records, 'main_script': ms, 'version_script': made, 'syncs': []}
    _write_json(link_path(vpath), link)
    _index_add(main_path, vpath, label, w, h, rr)
    pj.record(vpath, 'version', who, label=f'made from {main_path.name}',
              text=f'{w}x{h} version of {main_path} ranges {rr}')
    pj.record(main_path, 'version', who, label=f'version {label}', text=f'{vpath} ({w}x{h}) ranges {rr}')
    return {'version': str(vpath), 'link': str(link_path(vpath)), 'main': str(main_path), 'size': [w, h],
            'fps': made['profile']['fps'], 'target': tinfo or None, 'ranges': rr, 'length': made['length'],
            'items': len(pmap), 'reframe': {k: _brief(v) for k, v in records.items()},
            'settings': settings, 'notes': notes}


def _brief(rec):
    out = {'method': rec.get('method')}
    for k in ('share', 'rect', 'point', 'keys', 'why', 'action', 'track_results', 'coverage', 'cant_fit', 'offers'):
        if k in rec:
            out[k] = rec[k]
    return out


def _index_add(main, vpath, name, w, h, ranges):
    p = index_path(main)
    data = _read_json(p, {'versions': []}) or {'versions': []}
    data['versions'] = [v for v in data['versions'] if _norm(v.get('version', '')) != _norm(vpath)]
    data['versions'].append({'version': str(vpath), 'name': name, 'size': [w, h], 'ranges': ranges, 'made': _now()})
    _write_json(p, data)


# ---------------------------------------------------------------------------- sync

def _anchor(lay, x, end, frame):
    """Where a range edge sits on the main picture track: (item id, 'start'|'end'|'inside', source time)."""
    for it, s, e in lay:
        inside = (s - TOL <= x < e - TOL) if not end else (s + TOL < x <= e + TOL)
        if not inside:
            continue
        if not end and x - s < frame / 2:
            return it.get('id'), 'start', None
        if end and e - x < frame / 2:
            return it.get('id'), 'end', None
        src = es.to_seconds(it['in']) + (x - s) * float(it.get('speed', 1.0)) if 'in' in it else None
        return it.get('id'), 'inside', (src, (x - s) / max(1e-9, e - s))
    return None


def _move_edge(anchor, lay, frame):
    iid, edge, src = anchor
    hit = next(((it, s, e) for it, s, e in lay if it.get('id') == iid), None)
    if hit is None:
        return None
    it, s, e = hit
    if edge == 'start':
        return s
    if edge == 'end':
        return e
    t_src, frac = src
    if t_src is not None and 'in' in it:
        a0, b0 = es.to_seconds(it['in']), es.to_seconds(it['out'])
        if a0 - TOL <= t_src <= b0 + TOL:
            return s + (t_src - a0) / float(it.get('speed', 1.0))
        return s if t_src < a0 else e
    return s + frac * (e - s)


def _map_ranges(old_main, cur_main, ranges, whole=False):
    """The ranges moved with the main's changes: each edge stays with the main-track item it was on (its start, its
    end, or the same source moment inside it); edges whose item is gone follow the source-time mapping."""
    total = _total(cur_main)
    if whole:
        return [[0.0, _r(total)]], []
    if _cmp_main(old_main) == _cmp_main(cur_main):
        return [list(r) for r in ranges], []
    fps = float(cur_main['profile']['fps'])
    frame = 1.0 / fps
    old_t, new_t = main_track(old_main), main_track(cur_main)
    lay_old = layout(old_t) if old_t else []
    lay_new = layout(new_t) if new_t else []
    m = mapper(old_main, cur_main)
    out, notes = [], []
    for a, b in ranges:
        ea, eb = _anchor(lay_old, a, False, frame), _anchor(lay_old, b, True, frame)
        na = _move_edge(ea, lay_new, frame) if ea else None
        nb = _move_edge(eb, lay_new, frame) if eb else None
        if na is None:
            na = (m(a, nearest=True) if m else None)
            na = a if na is None else na
        if nb is None:
            nb = (m(b, end=True, nearest=True) if m else None)
            if nb is None or nb <= na:
                nb = min(total, na + (b - a))
        na, nb = max(0.0, na), min(total, nb)
        if nb - na <= TOL:
            notes.append(f'range {a:g}-{b:g} s no longer has anything on the main timeline')
            continue
        if abs(na - a) > TOL or abs(nb - b) > TOL:
            notes.append(f'range {a:g}-{b:g} s of the main is now {na:.3f}-{nb:.3f} s (the main timeline changed)')
        out.append([_r(na), _r(nb)])
    return out, notes


def _cmp_main(script):
    return json.dumps(main_track(script), sort_keys=True, default=str)


def _cues(cap):
    return [(q['start'], q['end'], q['text']) for q in cap.get('cues', [])]


def _sync_track_items(out, fresh_tracks, vmain, version_changed, made_by, vcur_by, left, main_diff, take_fresh, carried, base_by, fresh_pos, link, cur_main):
    """Merge main and version track edits while preserving version-side changes."""
    for t in out['tracks']:
        ft = fresh_tracks.get(t['name'])
        if ft is None:
            continue                                   # a track only the version has: kept
        is_main = vmain is not None and t['name'] == vmain['name']
        vitems = [it for it in t['items'] if 'gap' not in it]
        vorder = [it.get('id') for it in vitems]
        result = []
        for fit in [x for x in ft['items'] if 'gap' not in x]:
            iid = fit.get('id')
            vc = version_changed(iid, is_main)
            if iid in made_by and vc:
                if iid in vcur_by:
                    result.append(('v', copy.deepcopy(vcur_by[iid][1])))
                    left.append(f'{iid} on {t["name"]}: changed in the version; kept as the version has it'
                                + (' (the main changed it too)' if iid in main_diff else ''))
                else:
                    left.append(f'{iid} on {t["name"]}: removed in the version; stays removed'
                                + (' (the main changed it)' if iid in main_diff else ''))
                continue
            if iid in main_diff or iid not in vcur_by:
                result.append(('f', copy.deepcopy(fit)))
                take_fresh.add(iid)
                carried.append(_carried_line(iid, t['name'], base_by.get(iid), fit))
            else:
                v = copy.deepcopy(vcur_by[iid][1])
                if not is_main and 'at' in fit:
                    v['at'], v['pin'] = fit['at'], True
                    fresh_pos.add(iid)
                result.append(('v', v))
        fresh_ids = {x.get('id') for x in ft['items']}
        for iid in vorder:
            if iid in fresh_ids:
                continue
            if iid in made_by and not version_changed(iid, is_main):
                mid = (link.get('pieces', {}).get(iid) or {}).get('main_id', iid)
                why = ('no longer in the ranges' if mid in _items_by_id(cur_main) else 'removed in the main')
                carried.append(f'{iid} on {t["name"]}: {why}; removed from the version')
                continue
            v = copy.deepcopy(vcur_by[iid][1])
            k = vorder.index(iid)
            prev = next((vorder[j] for j in range(k - 1, -1, -1) if any(x[1].get('id') == vorder[j] for x in result)),
                        None)
            at = 0 if prev is None else next(i for i, x in enumerate(result) if x[1].get('id') == prev) + 1
            result.insert(at, ('v', v))
            if iid in made_by:
                left.append(f'{iid} on {t["name"]}: changed in the version and gone from the main ranges; kept')
            else:
                left.append(f'{iid} on {t["name"]}: added in the version; kept')
        if is_main:
            same_order = [x[1].get('id') for x in result] == vorder
            if same_order and all(src == 'v' for src, _ in result):
                continue                               # nothing to carry on the main track: keep it exactly
            fgaps = _gaps_before(ft)
            vgaps = _gaps_before(t)
            items = []
            for src, it in result:
                g = fgaps.get(it.get('id')) if src == 'f' else vgaps.get(it.get('id'), fgaps.get(it.get('id')))
                if g:
                    items.append({'gap': g})
                items.append(it)
            t['items'] = items
        else:
            t['items'] = [it for _, it in result]
            t['_place'] = True


def _sync_track_positions(vcur, out, fresh_pos, notes):
    """Place non-main items through the updated picture timing."""
    # other tracks: place items by their times (fresh ones from the main, version ones mapped through the picture)
    vmap = mapper(vcur, out)
    for t in out['tracks']:
        if not t.pop('_place', False):
            continue
        rows = []
        for it in t['items']:
            at = es.to_seconds(it['at']) if 'at' in it else None
            if it.get('id') not in fresh_pos and at is not None and vmap:
                m = vmap(at, nearest=True)
                at = at if m is None else m
            rows.append([at if at is not None else 0.0, it])
        rows.sort(key=lambda r: r[0])
        items, pos = [], 0.0
        for at, it in rows:
            if at < pos - 1e-3:
                notes.append(f'{it.get("id")} on {t["name"]} would overlap the item before it; placed after it')
                at = pos
            if at > pos + 1e-4:
                items.append({'gap': _r(at - pos)})
            it['at'], it['pin'] = es.clock(at), True
            items.append(it)
            pos = at + _item_len(it)
        t['items'] = items


def _sync_captions(made, fresh, out, left, carried, w, in_w, h, in_h, settings):
    """Carry changed main captions while preserving version edits and scaling new feeds."""
    # captions: the main's cues inside the ranges, unless the version changed its own
    made_caps = {c['track']: c for c in made.get('captions', [])}
    fresh_caps = {c['track']: c for c in fresh.get('captions', [])}
    caps = []
    for c in out.get('captions', []):
        mc, fc = made_caps.get(c['track']), fresh_caps.get(c['track'])
        if fc is None:
            caps.append(c)
            continue
        if mc is not None and _cues(mc) != _cues(c):
            caps.append(c)
            if _cues(fc) != _cues(mc):
                left.append(f'captions "{c["track"]}": the version changed its cues; the main\'s caption changes '
                            'were not carried')
            continue
        if _cues(fc) != _cues(c):
            changed = _cue_changes(c, fc)
            carried.append(f'captions "{c["track"]}": {changed}')
        c['cues'] = fc['cues']
        caps.append(c)
    for name, fc in fresh_caps.items():
        if name not in made_caps and not any(c['track'] == name for c in caps):
            nc = copy.deepcopy(fc)
            if isinstance(nc.get('style'), dict):
                sx, sy = w / in_w, h / in_h
                k = min(sx, sy) if settings['text_scale'] == 'min' else float(settings['text_scale'])
                nc['style'] = _scale_text_style(nc['style'], sx, sy, k)
            caps.append(nc)
            carried.append(f'captions "{name}": new in the main; added')
    if caps:
        out['captions'] = caps


def sync(version, actor=None, reframe=None, focus=None, tracks=None, dry_run=False):
    """Carry the main project's changes since the version was made/synced into the version (inside its ranges).
    Items the version changed itself are kept as the version has them. Returns carried / left lists and notes."""
    vpath = es._resolve(version)
    link = _read_json(link_path(vpath))
    if not link or link.get('format') != LINK_FORMAT:
        raise ValueError(f'{vpath} is not a linked version (no {link_path(vpath)})')
    main_path = Path(link['main'])
    if not main_path.is_file():
        raise FileNotFoundError(f'the main project {main_path} is not there')
    stored = {k: v for k, v in (link.get('settings') or {}).items() if k in REFRAME_DEFAULTS}
    settings = _settings({**stored, **(reframe or {})})
    focus = {**(link.get('focus') or {}), **(focus or {})}
    track_given = list(tracks or []) + [t for t in link.get('tracks_given') or [] if t]
    old_main, made = link['main_script'], link['version_script']
    cur_main = es.read(main_path)
    vcur = es.read(vpath)
    carried, left, notes = [], [], []
    if cur_main['base'] == link['main_base'] and not reframe and not focus and not tracks:
        return {'version': str(vpath), 'main': str(main_path), 'carried': [], 'left': [],
                'notes': ['the main project has not changed since the version was made/synced'],
                'ranges': link['ranges'], 'changed': False}
    new_ranges, rnotes = _map_ranges(old_main, cur_main, link['ranges'], whole=link.get('whole', False))
    notes += rnotes
    base_fresh, _, _ = pieces(old_main, link['ranges'])
    fresh, pmap, pnotes = pieces(cur_main, new_ranges)
    notes += pnotes
    w, h = link['target']['width'], link['target']['height']
    in_w, in_h = cur_main['profile']['width'], cur_main['profile']['height']
    base_by, fresh_by = _items_by_id(base_fresh), _items_by_id(fresh)
    made_by, vcur_by = _items_by_id(made), _items_by_id(vcur)
    main_ids = {i for i in fresh_by} | {i for i in base_by}

    def main_changed(iid):
        if iid not in base_by or iid not in fresh_by:
            return True
        return _cmp(base_by[iid][1]) != _cmp(fresh_by[iid][1])

    def version_changed(iid, track_is_main):
        if iid not in made_by or iid not in vcur_by:
            return iid in made_by        # deleted in the version counts as changed there
        return _cmp(made_by[iid][1], not track_is_main) != _cmp(vcur_by[iid][1], not track_is_main)

    # main-side changes inside the ranges (by id), for the report
    main_diff = {i for i in main_ids if main_changed(i)}
    # which fresh items get a fresh reframe: new or changed in the main (and not changed in the version)
    take_fresh = set()
    fresh_pos = set()     # items whose place on a non-main track comes from the main
    out = copy.deepcopy(vcur)
    out.pop('partial', None)
    fresh_tracks = {t['name']: t for t in fresh['tracks']}
    vmain = main_track(vcur)
    _sync_track_items(out, fresh_tracks, vmain, version_changed, made_by, vcur_by, left, main_diff, take_fresh, carried, base_by, fresh_pos, link, cur_main)

    # reframe the items taken from the main
    pmap_all = {**link.get('pieces', {}), **pmap}
    records = _reframe_script(out, pmap_all, w, h, in_w, in_h, settings, focus, track_given, only=take_fresh,
                              captions=False)
    fresh_pos |= take_fresh
    _sync_track_positions(vcur, out, fresh_pos, notes)

    _sync_captions(made, fresh, out, left, carried, w, in_w, h, in_h, settings)

    # outside the ranges: main changes that the version does not include
    outside = _outside_changes(old_main, cur_main, link['ranges'], new_ranges, main_diff)
    for line in outside:
        left.append(line)
    result = {'version': str(vpath), 'main': str(main_path), 'ranges': new_ranges,
              'carried': carried, 'left': left, 'notes': notes,
              'reframe': {k: _brief(v) for k, v in records.items()}, 'settings': settings}
    if dry_run:
        result['dry_run'] = True
        return result
    out['base'] = vcur['base']
    out['project'] = str(vpath)
    applied = es.apply_changes(vpath, script=out, actor=actor, label=f'sync from {main_path.name}')
    after = es.read(vpath)
    link['pieces'] = {**{k: v for k, v in link.get('pieces', {}).items() if k in _items_by_id(after)}, **pmap}
    link['reframe'] = {**{k: v for k, v in link.get('reframe', {}).items() if k in _items_by_id(after)}, **records}
    link.update(main_base=cur_main['base'], main_script=cur_main, version_script=after, ranges=new_ranges,
                synced=_now(), settings=settings, focus=focus)
    link['syncs'].append({'time': _now(), 'main_base': cur_main['base'], 'carried': len(carried), 'left': len(left),
                          'history': applied.get('history')})
    _write_json(link_path(vpath), link)
    result.update(changes=applied['changes'], history=applied.get('history'), length=after['length'],
                  changed=True, notes=notes + applied.get('notes', []))
    return result


def _item_len(it):
    from letitedit.timeline.edit_sync import item_len
    try:
        return item_len(it)
    except Exception:  # noqa: BLE001
        return es.to_seconds(it.get('len', 0))


def _gaps_before(track):
    out, g = {}, 0.0
    for it in track['items']:
        if 'gap' in it:
            g += es.to_seconds(it['gap'])
        else:
            if g > 0:
                out[it.get('id')] = _r(g)
            g = 0.0
    return out


def _carried_line(iid, tname, old, new):
    if old is None:
        return f'{iid} on {tname}: new in the main; added'
    o, n = old[1], new
    parts = []
    if o.get('clip') != n.get('clip'):
        parts.append(f'clip replaced ({Path(str(o.get("clip"))).name} -> {Path(str(n.get("clip"))).name})')
    if o.get('in') != n.get('in') or o.get('out') != n.get('out'):
        parts.append(f'trimmed (in {o.get("in")} -> {n.get("in")}, out {o.get("out")} -> {n.get("out")})')
    if (o.get('effects') or []) != (n.get('effects') or []):
        parts.append('effects changed (' + ', '.join(str(_effect_key(e)) for e in n.get('effects') or []) + ')')
    rest = {k for k in set(o) | set(n) if k not in ('clip', 'in', 'out', 'effects', 'at', 'pin', 'len', 'id')
            and o.get(k) != n.get(k)}
    if rest:
        parts.append('changed: ' + ', '.join(sorted(rest)))
    return f'{iid} on {tname}: ' + ('; '.join(parts) or 'moved')


def _cue_changes(old, new):
    a, b = set(_cues(old)), set(_cues(new))
    return f'{len(b - a)} cue(s) new or changed, {len(a - b)} removed or replaced'


def _outside_changes(old_main, cur_main, old_ranges, new_ranges, piece_diff=()):
    """Lines for main changes that fall outside the version's ranges (not carried). piece_diff: version piece ids
    whose part of the main changed; an item changed in the main whose pieces did not changed outside them."""
    lines = []
    old_by, cur_by = _items_by_id(old_main), _items_by_id(cur_main)
    lay_old = {it.get('id'): (s, e) for t in old_main['tracks'] for it, s, e in layout(t)}
    lay_new = {it.get('id'): (s, e) for t in cur_main['tracks'] for it, s, e in layout(t)}

    def inside(span, ranges):
        return span is not None and any(min(span[1], b) - max(span[0], a) > TOL for a, b in ranges)
    for iid in sorted(set(old_by) | set(cur_by), key=str):
        o, n = old_by.get(iid), cur_by.get(iid)
        if o and n and _cmp(o[1]) == _cmp(n[1]):
            continue
        if inside(lay_old.get(iid), old_ranges) or inside(lay_new.get(iid), new_ranges):
            if o and n and not any(d == iid or str(d).startswith(f'{iid}~') for d in piece_diff):
                lines.append(f'{iid} on {n[0]}: changed in the main outside the part of it the version holds; '
                             'nothing to carry')
            continue
        what = 'added' if o is None else 'removed' if n is None else 'changed'
        lines.append(f'{iid} on {(n or o)[0]}: {what} in the main outside the version\'s ranges; not carried')
    return lines


# ---------------------------------------------------------------------------- list

def info(version):
    """The link record of a version (without the stored scripts) and whether its main changed since."""
    vpath = es._resolve(version)
    link = _read_json(link_path(vpath))
    if not link:
        raise ValueError(f'{vpath} is not a linked version')
    return _summary(vpath, link)


def _summary(vpath, link):
    main = Path(link['main'])
    try:
        main_now = es.file_hash(main)
    except OSError:
        main_now = None
    try:
        v_now = es.file_hash(vpath)
    except OSError:
        v_now = None
    made_base = (link.get('version_script') or {}).get('base')
    return {'version': str(vpath), 'name': link.get('name'), 'main': str(main), 'size': [link['target']['width'],
            link['target']['height']], 'fps': link['target'].get('fps'), 'platform': link['target'].get('platform'),
            'ranges': link.get('ranges'), 'made': link.get('made'), 'synced': link.get('synced'),
            'main_changed_since': None if main_now is None else main_now != link.get('main_base'),
            'version_changed_since': None if v_now is None else v_now != made_base,
            'items': len(link.get('pieces') or {}),
            'reframe_methods': _method_counts(link.get('reframe') or {}), 'syncs': len(link.get('syncs') or []),
            'link': str(link_path(vpath))}


def _method_counts(records):
    out = {}
    for r in records.values():
        out[r.get('method')] = out.get(r.get('method'), 0) + 1
    return out


def list_versions(project):
    """Versions made from a main project (its versions.json and linked .mlt files in its folder), or, for a version,
    its own record. A folder lists every linked version in it."""
    p = Path(project)
    found = {}
    if p.is_dir():
        cands = list(p.glob('*.mlt'))
        main = None
    else:
        main = es._resolve(p)
        own = _read_json(link_path(main))
        if own and own.get('format') == LINK_FORMAT:
            return {'version_of': own['main'], 'versions': [_summary(main, own)]}
        idx = _read_json(index_path(main), {'versions': []}) or {'versions': []}
        cands = [Path(v['version']) for v in idx['versions']] + list(main.parent.glob('*.mlt'))
    for c in cands:
        if not c.is_file() or _norm(c) in found:
            continue
        link = _read_json(link_path(c))
        if not link or link.get('format') != LINK_FORMAT:
            continue
        if main is not None and _norm(link['main']) != _norm(main):
            continue
        found[_norm(c)] = _summary(c, link)
    out = {'versions': sorted(found.values(), key=lambda v: v.get('made') or '')}
    if main is not None:
        out['main'] = str(main)
        idx = _read_json(index_path(main), {'versions': []}) or {'versions': []}
        missing = [v['version'] for v in idx['versions'] if not Path(v['version']).is_file()]
        if missing:
            out['missing'] = missing
    return out
