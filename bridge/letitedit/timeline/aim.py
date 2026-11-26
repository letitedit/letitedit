"""{op: aim}: one effect on a chosen part of the video, made of pieces the engine already has (a clip's, a track's or the whole
video's effects, a mask around an effect, cut-out clips). `proof` compares before and after frames from the export engine.

`below` is a real adjustment layer now (adjust.py): one block under the named track. Effects tagged by the old `below`, one per
track, are still read, kept and moved with their picture.
"""
from __future__ import annotations

import uuid

from letitedit.timeline.edit_sync import layout, main_track, to_seconds

TAG = 'letitedit_ai:aim'
SHAPES = {'rectangle': 0, 'ellipse': 0.33, 'triangle': 0.67, 'diamond': 1}

def _fps(script):
    return float((script.get('profile') or {}).get('fps') or 30)


def _end(script):
    ends = [e for t in script['tracks'] if t.get('kind', 'video') == 'video' for _, _, e in layout(t)]
    return max(ends) if ends else 0.0


def _span(op, script, required=False):
    """(from, to) in seconds, or None for the whole video. words: the stretch where a phrase is said (near: which time, when it is
    said more than once; pad: seconds added at each end)."""
    if op.get('words'):
        if op.get('from') is not None or op.get('to') is not None:
            raise ValueError(f"aim on: {op['on']}: give words or from/to, not both")
        return _said(op, script)
    a, b = op.get('from'), op.get('to')
    if a is None and b is None:
        if required:
            raise ValueError(f"aim on: {op['on']} needs from and to (seconds): the person's matte is made for that stretch")
        return None
    a = 0.0 if a is None else float(a)
    b = _end(script) if b is None else float(b)
    if b <= a:
        raise ValueError(f'aim: to ({b:g}) has to be after from ({a:g})')
    return a, b


def _said(op, script):
    import letitedit.looks.popups as popups
    from letitedit.timeline.timeline_speech import timeline_words
    words = timeline_words(script)
    hits = popups.find_phrase(words, op['words'])
    if not hits:
        raise ValueError(f"\"{op['words']}\" is not said on the timeline")
    near = op.get('near')
    hit = min(hits, key=lambda h: abs(h[2] - to_seconds(near))) if near is not None else hits[0]
    pad = float(op.get('pad') or 0)
    return max(0.0, words[hit[0]]['t0'] - pad), words[hit[1] - 1]['t1'] + pad


def _engine_effect(op):
    effect = op['effect']
    if not isinstance(effect, dict) or not effect.get('filter'):
        raise ValueError(f"aim on: {op['on']}: effect has to be an engine effect, {{filter: NAME, params}} (letitedit_effects), "
                         f'not {effect!r}')
    return effect


def _tagged(effect, tag, span, fps):
    """A copy of the effect tagged as this aim, limited to a span of the timeline."""
    params = dict(effect.get('params') or {})
    params[TAG] = tag
    if span:
        params['in'], params['out'] = int(round(span[0] * fps)), max(int(round(span[1] * fps)) - 1, int(round(span[0] * fps)))
    return {**effect, 'params': params}


def _item(script, iid):
    for t in script['tracks']:
        for it in t['items']:
            if it.get('id') == iid:
                return t, it
    raise ValueError(f'No item with id {iid!r}')


def _region_effects(region, effect, item, fps):
    """The mask's three effects, in the clip's own picture. box: [x0, y0, x1, y1], fractions of the frame; path: rows from
    letitedit_track, [t, x0, y0, x1, y1, ...], t in the clip's source seconds."""
    shape = region.get('shape', 'rectangle')
    if shape not in SHAPES:
        raise ValueError(f"aim region: shape is {' | '.join(SHAPES)}, not {shape!r}")
    soft = float(region.get('soft', 0.1))
    params = {'filter': 'frei0r.alphaspot', 'filter.0': SHAPES[shape], 'filter.5': 0.5, 'filter.6': soft,
              'filter.7': 1 if region.get('invert') else 0, 'filter.8': 0 if region.get('invert') else 1, 'filter.9': 0}
    path, box = region.get('path'), region.get('box')
    if path:
        start, speed = to_seconds(item.get('in') or 0), float(item.get('speed') or 1.0)
        length = None if item.get('out') is None else (to_seconds(item['out']) - start) / speed
        rows = []
        for row in path:
            t = (float(row[0]) - start) / speed
            if t < -1e-3 or (length is not None and t > length + 1e-3):
                continue
            rows.append((max(t, 0.0), [float(v) for v in row[1:5]]))
        if not rows:
            raise ValueError('aim region: no row of path falls inside this clip (t is in the clip\'s source seconds)')
        if len(rows) == 1:
            box = rows[0][1]
        else:
            for key, value in (('filter.1', lambda r: (r[0] + r[2]) / 2), ('filter.2', lambda r: (r[1] + r[3]) / 2),
                               ('filter.3', lambda r: abs(r[2] - r[0]) / 2), ('filter.4', lambda r: abs(r[3] - r[1]) / 2)):
                params[key] = {'keys': [[round(t, 3), round(value(r), 5)] for t, r in rows]}
    if box is not None:
        if len(box) != 4 or not all(0 <= float(v) <= 1 for v in box):
            raise ValueError(f'aim region: box is [x0, y0, x1, y1] in fractions of the frame, not {box!r}')
        x0, y0, x1, y1 = [float(v) for v in box]
        params.update({'filter.1': round((x0 + x1) / 2, 5), 'filter.2': round((y0 + y1) / 2, 5),
                       'filter.3': round(abs(x1 - x0) / 2, 5), 'filter.4': round(abs(y1 - y0) / 2, 5)})
    if 'filter.1' not in params:
        raise ValueError('aim region needs box or path')
    return [{'filter': 'mask_start', 'params': params}, effect, {'filter': 'mask_apply', 'params': {'transition': 'frei0r.cairoblend'}}]


def _is_cutout(item):
    return (item.get('vfx') or {}).get('effect') == 'cutout'


def _cut_pieces(script, span):
    """[(at, end, source)] a cut-out of the main footage needs, one per clip, over exactly that span."""
    a, b = span
    main = main_track(script)
    out = []
    for item, s, e in layout(main) if main else []:
        if s >= b - 1e-6 or e <= a + 1e-6 or not item.get('clip'):
            continue
        x, y = max(a, s), min(b, e)
        speed = float(item.get('speed') or 1.0)
        start = to_seconds(item.get('in') or 0)
        src = {'clip': item['clip'], 'in': round(start + (x - s) * speed, 4), 'out': round(start + (y - s) * speed, 4)}
        if speed != 1.0:
            src['speed'] = speed
        out.append((round(x, 4), round(y, 4), src))
    if not out:
        raise ValueError(f'aim: no clip of the main footage between {a:g} and {b:g} s, so there is no person to cut out')
    return out


def _new_track_above(script, span):
    """Index for a new track just above the main picture, a scene or a cut-out over that span, so titles stay on top."""
    a, b = span
    main = main_track(script)
    index = script['tracks'].index(main)
    for i, t in enumerate(script['tracks']):
        if t.get('kind', 'video') != 'video':
            continue
        if any((it.get('scene') or _is_cutout(it)) and s < b - 1e-6 and e > a + 1e-6 for it, s, e in layout(t)):
            index = max(index, i)
    return index + 1


def _free_name(script, base='Person'):
    names = {t['name'] for t in script['tracks']}
    name, n = base, 1
    while name in names:
        n += 1
        name = f'{base} {n}'
    return name


def _covering_cutouts(script, span):
    """Existing cut-out pieces over the whole span and above any scene there, or None."""
    a, b = span
    scene_top = -1
    found = []
    for i, t in enumerate(script['tracks']):
        if t.get('kind', 'video') != 'video':
            continue
        for it, s, e in layout(t):
            if s < b - 1e-6 and e > a + 1e-6:
                if it.get('scene'):
                    scene_top = max(scene_top, i)
                elif _is_cutout(it):
                    found.append((i, it, s, e))
    found = [f for f in found if f[0] > scene_top]
    pos = a
    for _, _, s, e in sorted(found, key=lambda f: f[2]):
        if s > pos + 0.05:
            return None
        pos = max(pos, e)
    return found if found and pos >= b - 0.05 else None


def _place_cutouts(script, span, effect=None):
    """New cut-out pieces on a new track, carrying `effect`. Returns (track name, how many)."""
    from letitedit.timeline.edit_script import apply_ops
    pieces = _cut_pieces(script, span)
    name = _free_name(script)
    script['tracks'].insert(_new_track_above(script, span), {'name': name, 'kind': 'video', 'items': []})
    ops = []
    for a, b, src in pieces:
        item = {'vfx': {'effect': 'cutout', 'source': src}}
        if effect:
            item['effects'] = [effect]
        ops.append({'op': 'insert', 'track': name, 'at': a, 'edge_mode': 'exact', 'item': item})
    apply_ops(script, ops)
    return name, len(pieces)


def apply_op(script, op):
    """The op. Sets op['_result'], a plain sentence for the reply."""
    on, effect = op['on'], op['effect']
    fps = _fps(script)
    tag = 'aim-' + uuid.uuid4().hex[:6]
    name = (effect.get('filter') or next(iter(effect), 'effect')) if isinstance(effect, dict) else str(effect)
    span = None
    if on == 'clip':
        if op.get('from') is not None or op.get('to') is not None:
            raise ValueError('aim on: clip takes the whole clip; for part of the timeline use on: all or on: below with from/to')
        if not op.get('id'):
            raise ValueError('aim on: clip needs id')
        track, item = _item(script, op['id'])
        if op.get('region'):
            trio = _region_effects(op['region'], _engine_effect(op), item, fps)
            trio[0] = {**trio[0], 'params': {**trio[0]['params'], TAG: tag}}
            # first, so the shape is in the clip's own picture, before any zoom or size and position
            item['effects'] = trio + list(item.get('effects') or [])
            done = f"{name} on a {op['region'].get('shape', 'rectangle')} of {op['id']}"
            if op['region'].get('invert'):
                done = f"{name} on {op['id']} except a {op['region'].get('shape', 'rectangle')}"
        else:
            item['effects'] = list(item.get('effects') or []) + [effect]
            done = f"{name} on {op['id']}"
    elif on == 'all':
        span = _span(op, script)
        script['master'] = list(script.get('master') or []) + [_tagged(_engine_effect(op), tag, span, fps)]
        done = f'{name} on every track, not captions'
    elif on == 'below':
        if not op.get('track'):
            raise ValueError('aim on: below needs track: the track the effect stays under')
        import letitedit.timeline.adjust as adjust
        layer = {k: v for k, v in op.items() if k in ('from', 'to', 'words', 'near', 'pad', 'name')}
        layer.update(effects=[effect], below=op['track'])
        adjust.apply_op(script, layer)
        op['_pinned'] = layer['_pinned']
        op['_result'] = layer['_result']
        return
    elif on == 'not_person':
        span = _span(op, script, required=True)
        main = main_track(script)
        main['effects'] = list(main.get('effects') or []) + [_tagged(_engine_effect(op), tag, span, fps)]
        if _covering_cutouts(script, span):
            done = f"{name} on {main['name']}, under the cut-out already there"
        else:
            track, pieces = _place_cutouts(script, span)
            done = f"{name} on {main['name']}, with {pieces} cut-out piece(s) on {track} above it"
    elif on == 'person':
        span = _span(op, script, required=True)
        engine = _engine_effect(op)
        existing = _covering_cutouts(script, span)
        exact = existing and all(abs(s - span[0]) < 0.05 or s > span[0] for _, _, s, _ in existing) and \
            all(abs(e - span[1]) < 0.05 or e < span[1] for _, _, _, e in existing)
        if exact:
            for _, it, _, _ in existing:
                it['effects'] = list(it.get('effects') or []) + [engine]
            done = f'{name} on the {len(existing)} cut-out piece(s) already there'
        else:
            track, pieces = _place_cutouts(script, span, engine)
            done = f'{name} on {pieces} new cut-out piece(s) on {track}'
    else:
        raise ValueError(f'aim: on is clip | all | below | person | not_person, not {on!r}')
    if span:
        done += f', {span[0]:.2f}-{span[1]:.2f} s'
    op['_result'] = done


def follow(after, map_t):
    """After the main picture's timing changed: a tagged effect's time range stays on its picture. Returns notes."""
    fps = _fps(after)
    notes = []

    def walk(owner, key):
        kept = []
        for e in owner.get(key) or []:
            params = e.get('params') if isinstance(e, dict) else None
            if not (isinstance(params, dict) and params.get(TAG) and 'in' in params and 'out' in params):
                kept.append(e)
                continue
            a, b = float(params['in']) / fps, (float(params['out']) + 1) / fps
            na = map_t(a, nearest=True)
            nb = map_t(b, end=True, nearest=True)
            if na is None or nb is None or nb - na < 1.5 / fps:
                notes.append(f"{e.get('filter')}: its picture ({a:.2f}-{b:.2f} s) was cut, so the effect was removed")
                continue
            if abs(na - a) > 1e-3 or abs(nb - b) > 1e-3:
                notes.append(f"{e.get('filter')} moved with its picture to {na:.2f}-{nb:.2f} s")
            kept.append({**e, 'params': {**params, 'in': int(round(na * fps)), 'out': int(round(nb * fps)) - 1}})
        if kept or owner.get(key):
            if kept:
                owner[key] = kept
            else:
                owner.pop(key, None)

    walk(after, 'master')
    for t in after['tracks']:
        walk(t, 'effects')
    return notes


def _diff(a, b):
    import numpy as np
    from PIL import Image
    x = np.asarray(Image.open(a).convert('RGB'), np.int16)
    y = np.asarray(Image.open(b).convert('RGB'), np.int16)
    if x.shape != y.shape:
        return None
    return np.abs(x - y).max(axis=2)


def _what(op):
    effect = op.get('effect') or (op.get('effects') or [None])[0]
    if op.get('op') == 'adjust':
        import letitedit.timeline.stack as stack
        return ', '.join(str(stack._word(e)) for e in op.get('effects') or [effect]) + ' on everything below'
    name = (effect.get('filter') or next(iter(effect), 'effect')) if isinstance(effect, dict) else str(effect)
    return f"{name} on {op.get('on')}" + (f" {op['id']}" if op.get('id') else '') + (f" {op['track']}" if op.get('track') else '')


def proof(before_path, after_path, ops):
    """Before and after frames of each aim, from the export engine: what changed where it should, and where it shouldn't.
    Returns (report, jpeg bytes of the sheet)."""
    import io

    import letitedit.review.checks as checks
    import letitedit.timeline.timeline_model as tm
    timeline = tm.load(after_path)
    fps, end = timeline.fps, timeline.frames / timeline.fps
    report, tiles, labels = [], [], []
    for op in ops[:3]:
        span = None
        if op.get('words'):
            import letitedit.timeline.edit_script as es
            span = _said(op, es.read(after_path))
        elif op.get('from') is not None or op.get('to') is not None:
            span = (float(op.get('from') or 0), float(op['to']) if op.get('to') is not None else end)
        if span:
            times = [('inside', (span[0] + span[1]) / 2)]
            if span[0] > 0.2:
                times.append(('before its stretch', max(0, span[0] - 0.25)))
            if span[1] < end - 0.2:
                times.append(('after its stretch', min(end - 1 / fps, span[1] + 0.25)))
        else:
            mid = _clip_mid(after_path, op.get('id')) if op.get('id') else end / 2
            times = [('inside', mid)]
        frames = [min(timeline.frames - 1, max(0, round(t * fps))) for _, t in times]
        old_work, new_work = checks._work('aim-before'), checks._work('aim-after')
        old = checks.render_frames(tm.load(before_path), before_path, frames, old_work)
        new = checks.render_frames(timeline, after_path, frames, new_work)
        rows = []
        for (where, t), a, b in zip(times, old, new):
            d = _diff(a, b)
            row = {'where': where, 't': round(t, 2)}
            if d is not None:
                row['pixels_changed_pct'] = round(float((d > 8).mean()) * 100, 1)
                row['mean_change'] = round(float(d.mean()), 1)
                region = op.get('region')
                if where == 'inside' and region and region.get('box'):
                    h, w = d.shape
                    x0, y0, x1, y1 = region['box']
                    box = d[int(h * y0):max(int(h * y0) + 1, int(h * y1)), int(w * x0):max(int(w * x0) + 1, int(w * x1))]
                    row['mean_change_in_box'] = round(float(box.mean()), 1)
                    row['mean_change_outside_box'] = round(float((d.sum() - box.sum()) / max(1, d.size - box.size)), 1)
            rows.append(row)
            tiles += [a, b]
            labels += [f'{t:.2f} s before', f'{t:.2f} s after ({where})']
        inside = rows[0].get('pixels_changed_pct')
        outside = [r.get('pixels_changed_pct') or 0 for r in rows[1:]]
        verdict = []
        if inside is not None and inside < 0.5:
            verdict.append('almost nothing changed inside the target: check the effect\'s settings')
        if any(x >= 0.5 for x in outside):
            verdict.append('the picture changed outside its stretch')
        entry = {'aim': _what(op), 'frames': rows}
        if verdict:
            entry['warning'] = '; '.join(verdict)
        report.append(entry)
    sheet = checks.contact_sheet(tiles, labels, cols=2, tile_w=360)
    buf = io.BytesIO()
    sheet.save(buf, 'JPEG', quality=85)
    return report, buf.getvalue()


def _clip_mid(path, iid):
    import letitedit.timeline.edit_script as es
    for t in es.read(path)['tracks']:
        for item, s, e in layout(t):
            if item.get('id') == iid:
                return (s + e) / 2
    return 0.0
