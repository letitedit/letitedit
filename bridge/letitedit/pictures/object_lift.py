"""{op: lift}: an object comes out of the shot, holds, and goes back, with its moves as keys on the timeline (T62).

The object layer is a steady movie: the object in the middle of the picture in its own coordinates. Its Size, Position &
Rotate filter carries the moves, a key per frame while it follows the shot's own shake on the way out and back, two keys
for the hold, so the lift can be re-timed with another {op: lift, id, ...} and the person can read the keys in the Filters
panel. The background is a still of the frame with the object filled in, on its own track, with its own keys. Both go
under no scene: the scene (the AI's own) goes on a track below them, over exactly the stretch the reply calls `cover`.

Every piece carries the op's settings in its filter (`lift`), so `follow` can rebuild the moves when an edit changes where
the group sits: a trim, a move, or a cut on the main picture.
"""
from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import letitedit.timeline.aim as aim
import letitedit.timeline.edit_sync as edit_sync
from letitedit.timeline.edit_sync import layout, main_track

FADE_IN = 3             # frames: over the real picture, where layer and footage match
FADE_OUT = 4
FALL_S, RISE_S = .57, .47
ROTATE_SIGN = 1.0       # the engine's rotate is clockwise on screen about the rectangle's centre, as the track's angle is (measured, tests/t62/stage2/rot_test.py)


def _bezier(x, a, b, c, d):
    lo, hi = 0.0, 1.0
    for _ in range(30):
        m = (lo + hi) / 2
        v = 3 * (1 - m) ** 2 * m * a + 3 * (1 - m) * m ** 2 * c + m ** 3
        lo, hi = (m, hi) if v < x else (lo, m)
    m = (lo + hi) / 2
    return 3 * (1 - m) ** 2 * m * b + 3 * (1 - m) * m ** 2 * d + m ** 3


def progress(n, f_from, n_arrive, f_to, n_leave):
    """0 in the shot, 1 at the hold. Rigid things arrive with no overshoot and a long settle; they leave a little faster."""
    if n <= f_from:
        return 0.0
    if n < f_from + n_arrive:
        return _bezier((n - f_from) / n_arrive, .3, 0, .1, 1)
    if n <= f_to - n_leave:
        return 1.0
    if n < f_to:
        return 1 - _bezier((n - (f_to - n_leave)) / n_leave, .5, 0, .35, 1)
    return 0.0


def fall_rect(u, W, H):
    """The background tipped back and dropping, u from 0 (in place) to 1 (gone), as a rectangle: it narrows and flattens."""
    th = 1.25 * u ** 1.7
    h = H * math.cos(th)
    w = W * (1 - .22 * u)
    drop = H * .4 * u ** 2.2
    return [(W - w) / 2, H + drop - h, w, h]


def _rect_text(values):
    return ' '.join(f'{v:.3f}'.rstrip('0').rstrip('.') for v in values)


def _record_of(item):
    for e in item.get('effects') or []:
        if isinstance(e, dict) and e.get('lift'):
            try:
                return json.loads(e['lift'])
            except (TypeError, ValueError):
                return None
    return None


def _remove(script, group):
    import letitedit.timeline.edit_script as es
    for t in script['tracks']:
        ids = [it['id'] for it in t['items'] if (_record_of(it) or {}).get('group') == group]
        if not ids:
            continue
        es.apply_ops(script, [{'op': 'delete', 'id': i, 'close_gap': False} for i in ids])
        if all('gap' in it for it in t['items']):
            t['items'] = []


def _track_for(script, name, after=None, below=None):
    t = next((x for x in script['tracks'] if x['name'] == name), None)
    if t is not None:
        return name
    t = {'name': name, 'kind': 'video', 'items': []}
    if after:
        i = next((k for k, x in enumerate(script['tracks']) if x['name'] == after), None)
        if i is None:
            raise ValueError(f'lift: no track named {after!r}')
        script['tracks'].insert(i + 1, t)
    else:
        videos = [k for k, x in enumerate(script['tracks']) if x.get('kind', 'video') == 'video']
        script['tracks'].insert(videos[-1] + 1 if videos else 0, t)
    return name


def _same_clip(a, b):
    return Path(str(a)).resolve().as_posix().lower() == Path(str(b)).resolve().as_posix().lower()


def _build(script, record):
    """Make the group's items from its settings. Raises a plain ValueError when it can't."""
    import letitedit.timeline.edit_script as es
    import letitedit.pictures.object_layer as ol
    meta = ol.load(record['object'])
    profile = script.get('profile') or {}
    W, H = int(profile.get('width') or meta['width']), int(profile.get('height') or meta['height'])
    fps = float(profile.get('fps') or meta['fps'])
    f_from, f_to = int(round(record['from'] * fps)), int(round(record['to'] * fps))
    n_arrive = max(2, int(round(float(record.get('arrive', .8)) * fps)))
    n_leave = max(2, int(round(float(record.get('leave', .53)) * fps)))
    if f_to - f_from < n_arrive + n_leave:
        raise ValueError(f"lift: from {record['from']:.2f} to {record['to']:.2f} s is too short for an arrive of "
                         f"{n_arrive / fps:.2f} s and a leave of {n_leave / fps:.2f} s")
    f_start, f_end = max(0, f_from - FADE_IN), f_to + FADE_OUT
    pieces = aim._cut_pieces(script, (f_start / fps, f_end / fps))
    native = meta['fps']
    obj_w, obj_h = ol.size_of(meta)
    if record.get('scale'):
        scale = float(record['scale'])
    else:
        size = float(record.get('size') or .62)
        scale = min(size * H / max(obj_h, 1.0), .92 * W / max(obj_w, 1.0))
    rotate = float(record.get('rotate') or 0.0)
    at = record.get('at') or [W / 2, H * .44]
    push = float(record.get('push', .03))
    n_hold = max(1, (f_to - n_leave) - (f_from + n_arrive))

    def hero(n):
        u = min(1.0, max(0.0, (n - (f_from + n_arrive)) / n_hold))
        s = 1 + push * u
        return [at[0] - s * W / 2, at[1] - s * H / 2, s * W, s * H, 0.0]
    obj_track = _track_for(script, record.get('track') or 'Object', after=record.get('after'))
    back = record.get('background', 'fall')
    back_track = None
    if back in ('fall', 'fade'):
        i = next(k for k, x in enumerate(script['tracks']) if x['name'] == obj_track)
        back_track = record.get('back_track') or 'Background falls'
        if not any(x['name'] == back_track for x in script['tracks']):
            script['tracks'].insert(i, {'name': back_track, 'kind': 'video', 'items': []})
    stored = json.dumps(record, sort_keys=True)
    notes = []
    ids = []
    timeline_of = {}
    for k, (a, b, src) in enumerate(pieces):
        if src.get('speed'):
            raise ValueError('lift: the footage under it has a speed change, which a tracked object can\'t follow yet')
        if not _same_clip(src['clip'], meta['clip']):
            raise ValueError(f"lift: object {meta['id']} was cut from {Path(meta['clip']).name}, and the footage at "
                             f"{a:.2f} s is {Path(src['clip']).name}")
        na, nb = int(round(a * fps)), int(round(b * fps))
        first_src = int(round(float(src['in']) * native))
        rect_keys, rot_keys, fade_keys = [], [], []
        for n in range(na, nb):
            index = first_src + int(round((n - na) * native / fps)) - meta['first']
            if not 0 <= index < meta['count']:
                raise ValueError(f"lift: object {meta['id']} covers {meta['start']:.2f} to {meta['end']:.2f} s of "
                                 f"{Path(meta['clip']).name}, and this needs {(index + meta['first']) / native:.2f} s. "
                                 'Lift it inside that stretch, or make the object over a longer range.')
            timeline_of[n] = index
            p = progress(n, f_from, n_arrive, f_to, n_leave)
            held = p == 1.0
            if held and na < n < nb - 1 and n not in (f_from + n_arrive, f_to - n_leave):
                continue
            x, y, w, h, deg = ol.pose(meta, index, W, H, scale, rotate)
            target = hero(n)
            rect = [x + (target[0] - x) * p, y + (target[1] - y) * p, w + (target[2] - w) * p, h + (target[3] - h) * p]
            t = round((n - na) / fps, 4)
            rect_keys.append([t, _rect_text(rect)])
            rot_keys.append([t, round(ROTATE_SIGN * deg * (1 - p), 3)])
            # the engine takes no notice of a rectangle's opacity: fades are the Opacity effect's keys
            if n < f_from:
                fade_keys.append([t, round((n - f_start + 1) / (f_from - f_start + 1), 3)])
            elif n == f_from or n == f_to - 1:
                fade_keys.append([t, 1])
            elif n >= f_to:
                fade_keys.append([t, round(max(0.0, 1 - (n - f_to + 1) / FADE_OUT), 3)])
        params = {'object': meta['id'], 'steady': True, 'scale': round(scale, 5), 'rotate': rotate}
        if meta.get('in_front'):
            if k == 0:
                params['front_before'] = round((first_src + (f_from - na) * native / fps) / native, 4)
            if k == len(pieces) - 1:
                params['front_after'] = round((first_src + (f_to - na) * native / fps) / native, 4)
        iid = f"lift-{record['group']}-{k}"
        item = {'id': iid, 'vfx': {'effect': 'object', 'source': {'clip': src['clip'], 'in': src['in'], 'out': src['out']},
                                   'params': params},
                'effects': ([{'opacity': {'keys': fade_keys}}] if fade_keys else []) +
                           [{'size_position': {'keys': rect_keys}, 'rotate': {'keys': rot_keys}, 'lift': stored}]}
        es.apply_ops(script, [{'op': 'insert', 'track': obj_track, 'at': round(na / fps, 4), 'edge_mode': 'exact', 'item': item}])
        ids.append(iid)
    if back_track:
        ids += _background(script, record, meta, back, back_track, stored, W, H, fps, f_start, f_from, f_to, f_end, timeline_of)
    if scale * meta['S'] > 0:
        px = scale * meta['S'] / ol.fit_of(meta, W, H)[0, 0]
        if px > 1.6:
            notes.append(f'the object is shown at {px:.1f}x the shot\'s own pixels, so it may look soft: size {record.get("size") or .62:g} is large for it')
    return ids, notes, (f_from / fps, f_to / fps), scale


def _background(script, record, meta, back, track, stored, W, H, fps, f_start, f_from, f_to, f_end, timeline_of):
    import letitedit.timeline.edit_script as es
    import letitedit.pictures.object_layer as ol
    n_fall = max(2, int(round(FALL_S * fps)))
    n_rise = max(2, int(round(RISE_S * fps)))
    out = []
    a_still = ol.filled_still(meta, timeline_of[f_start])
    b_still = ol.filled_still(meta, timeline_of[min(f_to, f_end - 1)])
    keys, fades = [], []
    for n in range(f_start, f_from):
        t = round((n - f_start) / fps, 4)
        keys.append([t, _rect_text([0, 0, W, H])])
        fades.append([t, round((n - f_start + 1) / (f_from - f_start + 1), 3)])
    for n in range(f_from, f_from + n_fall + 1):
        u = (n - f_from) / n_fall
        t = round((n - f_start) / fps, 4)
        keys.append([t, _rect_text(fall_rect(u, W, H) if back == 'fall' else [0, 0, W, H])])
        fades.append([t, round(1 - max(0.0, (u - .6) / .4) ** 1.5 if back == 'fall' else 1 - u, 3)])
    iid = f"lift-{record['group']}-in"
    es.apply_ops(script, [{'op': 'insert', 'track': track, 'at': round(f_start / fps, 4), 'edge_mode': 'exact',
                           'item': {'id': iid, 'clip': a_still, 'in': 0, 'out': round((f_from + n_fall + 1 - f_start) / fps, 4),
                                    'effects': [{'opacity': {'keys': fades}}, {'size_position': {'keys': keys}, 'distort': True, 'lift': stored}]}}])
    out.append(iid)
    keys, fades = [], []
    f0 = f_to - n_rise
    for n in range(f0, f_end):
        t = round((n - f0) / fps, 4)
        if n < f_to:
            v = (n - f0) / n_rise
            u = (1 - v) ** 1.6
            keys.append([t, _rect_text(fall_rect(u, W, H) if back == 'fall' else [0, 0, W, H])])
            fades.append([t, round(min(1.0, v / .2) if back == 'fall' else v, 3)])
        else:
            keys.append([t, _rect_text([0, 0, W, H])])
            fades.append([t, round(max(0.0, 1 - (n - f_to + 1) / FADE_OUT), 3)])
    iid = f"lift-{record['group']}-out"
    es.apply_ops(script, [{'op': 'insert', 'track': track, 'at': round(f0 / fps, 4), 'edge_mode': 'exact',
                           'item': {'id': iid, 'clip': b_still, 'in': 0, 'out': round((f_end - f0) / fps, 4),
                                    'effects': [{'opacity': {'keys': fades}}, {'size_position': {'keys': keys}, 'distort': True, 'lift': stored}]}}])
    out.append(iid)
    return out


SETTINGS = ('object', 'at', 'size', 'scale', 'rotate', 'arrive', 'leave', 'background', 'push', 'track', 'after')


def apply_op(script, op):
    """{op: lift, object, from, to | words, ...}; with id: that lift again, with any setting changed; with remove: gone."""
    record = None
    if op.get('id'):
        _, item = aim._item(script, op['id'])
        record = _record_of(item)
        if not record:
            raise ValueError(f"lift: {op['id']} isn't part of a lift")
        group = record['group']
        if op.get('remove'):
            _remove(script, group)
            op['_result'] = f'lift {group} removed'
            return
        record = dict(record)
        _remove(script, group)
    else:
        if not op.get('object'):
            raise ValueError('lift needs object: an id from letitedit_object')
        group = uuid.uuid4().hex[:6]
        record = {'group': group}
    for k in SETTINGS:
        if op.get(k) is not None:
            record[k] = op[k]
    if op.get('words') or op.get('from') is not None or op.get('to') is not None:
        span = aim._span({**op, 'on': 'lift', 'from': op.get('from', record.get('from')), 'to': op.get('to', record.get('to'))}
                         if not op.get('words') else {**op, 'on': 'lift'}, script, required=True)
        record['from'], record['to'] = round(span[0], 4), round(span[1], 4)
    if record.get('from') is None or record.get('to') is None:
        raise ValueError('lift needs from and to (seconds on the timeline), or words')
    ids, notes, cover, scale = _build(script, record)
    op['_pinned'] = ids
    text = (f"{record['object']} lifted from {cover[0]:.2f} to {cover[1]:.2f} s on {record.get('track') or 'Object'}, as "
            f"{ids[0]} and the rest of its group. A scene for behind it goes on a track below, over {cover[0]:.2f} to {cover[1]:.2f} s")
    if notes:
        text += '; ' + '; '.join(notes)
    op['_result'] = text


def uncovered(after):
    """Facts for the reply: something on a track under a lift that shows while the lift's own background isn't covering it yet (or any
    more), so it appears over the footage for those frames. A re-time moves the lift and not the scene, so this reads every edit."""
    notes = []
    fps = float((after.get('profile') or {}).get('fps') or 30)
    main = main_track(after)
    groups = {}
    for i, t in enumerate(after['tracks']):
        for it, _, _ in layout(t):
            r = _record_of(it)
            if r and r.get('group') not in groups:
                groups[r.get('group')] = (i, r)
    for group, (lowest, record) in groups.items():
        if record.get('background', 'fall') not in ('fall', 'fade') or record.get('from') is None or record.get('to') is None:
            continue
        for t in after['tracks'][:lowest]:
            if t is main or t.get('kind', 'video') != 'video':
                continue
            for it, s, e in layout(t):
                early, late = record['from'] - s, e - record['to']
                if s < record['from'] < e and 1 / fps < early < 1.5:
                    notes.append(f"{it.get('id')} on {t['name']} starts {round(early * fps)} frames before lift {group} covers the picture at "
                                 f"{record['from']:.2f} s, so it shows over the footage for those frames")
                if s < record['to'] < e and 1 / fps < late < 1.5:
                    notes.append(f"{it.get('id')} on {t['name']} ends {round(late * fps)} frames after lift {group} stops covering the picture at "
                                 f"{record['to']:.2f} s, so it shows over the footage for those frames")
    return notes


def follow(after):
    """After an edit: a lift whose pieces no longer sit where its keys say has its moves rebuilt for where it is now (a trim,
    a move, a cut on the main picture). Returns notes."""
    notes = []
    seen = {}
    for t in after['tracks']:
        for it, s, e in layout(t):
            r = _record_of(it)
            if r:
                seen.setdefault(r.get('group'), []).append((it, s, e, r))
    if not seen:
        return notes
    fps = float((after.get('profile') or {}).get('fps') or 30)
    for group, rows in seen.items():
        objects = [(s, e, r) for it, s, e, r in rows if (it.get('vfx') or {}).get('effect') == 'object']
        record = rows[0][3]
        if not objects:
            _remove(after, group)
            notes.append(f'lift {group}: its object was removed, so its background went too')
            continue
        start = min(s for s, _, _ in objects)
        end = max(e for _, e, _ in objects)
        want_start = max(0, int(round(record['from'] * fps)) - FADE_IN) / fps
        want_end = (int(round(record['to'] * fps)) + FADE_OUT) / fps
        if abs(start - want_start) <= 1.5 / fps and abs(end - want_end) <= 1.5 / fps:
            continue
        new = dict(record)
        new['from'] = round(start + FADE_IN / fps if start > 0 else record['from'], 4)
        new['to'] = round(end - FADE_OUT / fps, 4)
        _remove(after, group)
        try:
            _build(after, new)
            notes.append(f"lift {group}: its moves were rebuilt for {new['from']:.2f} to {new['to']:.2f} s")
        except ValueError as ex:
            notes.append(f'lift {group} was removed: {ex}')
    return notes
