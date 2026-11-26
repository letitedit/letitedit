"""Transitions between clips.

Part of `edit_script` (letitedit/timeline/edit_script.py), which imports every name here back,
so `edit_script.X` is the same object it always was.
"""
from __future__ import annotations
import copy
import os
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
import letitedit.timeline.edit_effects as ee
from letitedit.timeline.edit_script_base import (  # noqa: E402
    _get, _r, _set, to_seconds
)
from letitedit.timeline.edit_script_project import (  # noqa: E402
    tm_clock
)


# ---------------------------------------------------------------------------- transitions between clips

TRANSITION_PROP = 'shotcut:transition'
# Shotcut's stock wipes (its Transition panel), as %lumaNN.pgm shapes
WIPES = ['bar_horizontal', 'bar_vertical', 'barn_door_horizontal', 'barn_door_vertical', 'barn_door_diagonal_sw_ne',
         'barn_door_diagonal_nw_se', 'diagonal_top_left', 'diagonal_top_right', 'matrix_waterfall_horizontal',
         'matrix_waterfall_vertical', 'matrix_snake_horizontal', 'matrix_snake_parallel_horizontal',
         'matrix_snake_vertical', 'matrix_snake_parallel_vertical', 'barn_v_up', 'iris_circle', 'double_iris',
         'iris_box', 'box_bottom_right', 'box_bottom_left', 'box_right_center', 'clock_top']
TRANSITION_TYPES = ['dissolve', 'cut'] + WIPES


def transition_spec(spec):
    """Normalise an item's `transition`: a number of seconds (a dissolve) or {type, len, softness, invert, audio}."""
    if spec is None or spec is False:
        return None
    if isinstance(spec, (int, float, str)) and not isinstance(spec, bool):
        spec = {'len': spec}
    spec = dict(spec)
    if 'len' not in spec:
        raise ValueError(f'a transition needs a length in seconds: {spec}')
    spec['len'] = to_seconds(spec['len'])
    spec.setdefault('type', 'dissolve')
    t = str(spec['type'])
    if t not in TRANSITION_TYPES and not os.path.exists(t):
        raise ValueError(f"unknown transition {t!r}: use {', '.join(TRANSITION_TYPES)}, or the path of a greyscale "
                         'image (a luma map: dark parts change first; draw your own with Python)')
    return spec


def _transition_view(doc, tractor, n):
    luma = mix = None
    for trn in tractor.findall('transition'):
        svc = _get(trn, 'mlt_service')
        if svc in ('luma', 'movit.luma_mix'):
            luma = trn
        elif svc == 'mix':
            mix = trn
    out = {'type': 'dissolve', 'len': _r(n / doc.fps)}
    if luma is not None:
        res = _get(luma, 'resource') or ''
        m = re.search(r'%luma(\d\d)', res)
        if m and 1 <= int(m.group(1)) <= len(WIPES):
            out['type'] = WIPES[int(m.group(1)) - 1]
        elif res.startswith('color:'):
            out['type'] = 'cut'
        elif res:
            out['type'] = res
        soft = _get(luma, 'softness')
        if res and not res.startswith('color:') and soft not in (None, '', '0'):
            out['softness'] = float(soft)
        if _get(luma, 'invert') == '1':
            out['invert'] = True
    if mix is not None:
        st = float(_get(mix, 'start') or -2)
        if st != -2:
            out['audio'] = 'linear' if st == -1 else st
    return out


def _transition_info(doc, tractor):
    """What a Shotcut same-track transition joins: {a, a_in, a_out, b, b_in, b_out, n, view} or None."""
    if _get(tractor, TRANSITION_PROP) is None:
        return None
    tracks = tractor.findall('track')
    if len(tracks) != 2:
        return None
    pa, pb = doc.elements.get(tracks[0].get('producer')), doc.elements.get(tracks[1].get('producer'))
    if pa is None or pb is None:
        return None
    a_in, a_out = doc.f(tracks[0].get('in')), doc.f(tracks[0].get('out'))
    b_in, b_out = doc.f(tracks[1].get('in')), doc.f(tracks[1].get('out'))
    if None in (a_in, a_out, b_in, b_out):
        return None
    n = b_out - b_in + 1
    return {'a': pa, 'a_in': a_in, 'a_out': a_out, 'b': pb, 'b_in': b_in, 'b_out': b_out, 'n': n,
            'view': _transition_view(doc, tractor, n)}


def _track_records(doc, pl, name, ids):
    """The entries of a track with Shotcut's transitions folded in: a transition between two clips becomes
    `transition` on the incoming clip, and both clips show their full source range (the overlap included)."""
    recs = []
    for i, (k, e, nblank) in enumerate(doc.entries(pl)):
        if k == 'blank':
            recs.append({'kind': 'blank', 'frames': nblank})
            continue
        prod = doc.elements.get(e.get('producer'))
        if prod is not None:
            recs.append({'kind': 'entry', 'entry': e, 'prod': prod, 'id': ids[(name, i)]})
    out, j = [], 0
    while j < len(recs):
        r = recs[j]
        info = _transition_info(doc, r['prod']) if r['kind'] == 'entry' and r['prod'].tag == 'tractor' else None
        nxt = recs[j + 1] if j + 1 < len(recs) else None
        prev = out[-1] if out else None
        if (info and prev and nxt and prev['kind'] == 'entry' and nxt['kind'] == 'entry'
                and prev['prod'] is info['a'] and nxt['prod'] is info['b']
                and doc.f(prev['entry'].get('out')) + 1 == info['a_in']
                and info['b_out'] + 1 == (doc.f(nxt['entry'].get('in')) or 0)):
            pe = copy.deepcopy(prev['entry'])
            pe.set('out', tm_clock(info['a_out'], doc.fps))
            prev['entry'] = pe
            ne = copy.deepcopy(nxt['entry'])
            ne.set('in', tm_clock(info['b_in'], doc.fps))
            out.append({**nxt, 'entry': ne, 'transition': info['view'], 'tr_frames': info['n']})
            j += 2
            continue
        out.append(r)
        j += 1
    return out


def _build_transition(doc, spec, prod_a, a_in, prod_b, b_in, n):
    """A Shotcut same-track transition (what dragging one clip over another makes)."""
    fps = doc.fps
    tr = ET.Element('tractor', {'id': _new_id(doc, 'tractor'), 'in': tm_clock(0, fps), 'out': tm_clock(n - 1, fps)})
    _set(tr, TRANSITION_PROP, 'lumaMix')
    ET.SubElement(tr, 'track', {'producer': prod_a.get('id'), 'in': tm_clock(a_in, fps), 'out': tm_clock(a_in + n - 1, fps)})
    ET.SubElement(tr, 'track', {'producer': prod_b.get('id'), 'in': tm_clock(b_in, fps), 'out': tm_clock(b_in + n - 1, fps)})
    t = spec['type']
    luma = ET.SubElement(tr, 'transition', {'id': _new_id(doc, 'transition'), 'out': tm_clock(n - 1, fps)})
    props = {'a_track': 0, 'b_track': 1, 'factory': 'loader', 'mlt_service': 'luma', 'alpha_over': 1,
             'fix_background_alpha': 1}
    if t == 'cut':
        props.update(resource='color:#808080', progressive=1, invert=0, softness=0)
    elif t != 'dissolve':
        res = f'%luma{WIPES.index(t) + 1:02d}.pgm' if t in WIPES else str(Path(t).resolve())
        props.update(resource=res, progressive=1, invert=int(bool(spec.get('invert'))),
                     softness=ee.fmt(float(spec.get('softness', 0.1))))
    for k, v in props.items():
        _set(luma, k, v)
    mix = ET.SubElement(tr, 'transition', {'id': _new_id(doc, 'transition'), 'out': tm_clock(n - 1, fps)})
    audio = spec.get('audio', 'crossfade')
    start = -2 if audio in (None, 'crossfade', 'equal_power') else -1 if audio == 'linear' else float(audio)
    for k, v in (('a_track', 0), ('b_track', 1), ('start', ee.fmt(start)), ('accepts_blanks', 1), ('mlt_service', 'mix')):
        _set(mix, k, v)
    return tr


def _new_id(doc, prefix):
    while True:
        cand = f'{prefix}{uuid.uuid4().hex[:6]}'
        if cand not in doc.elements:
            return cand
