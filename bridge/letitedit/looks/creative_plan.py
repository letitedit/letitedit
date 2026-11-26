"""Deterministic, footage-grounded candidates for ``{op: fx, auto: true}``.

The plan uses words already cached for this timeline. It never transcribes, guesses a
number or place, or invents a 3D model. Sliders are per-kind ceilings, not quotas.
"""
from __future__ import annotations

import re


CAPS = (0, 1, 2, 3, 5, 7, 9)  # per ten seconds, matching New video's Custom style
NUMBERS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
           'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
EMPHASIS = {'actually', 'really', 'finally', 'exactly', 'never', 'always', 'biggest', 'best',
            'worst', 'fixed', 'broke', 'failed', 'works', 'surprise', 'important'}
REVEAL = {'but', 'however', 'then', 'instead', 'until', 'finally', 'result'}
STEP = {'first', 'second', 'third', 'next', 'step'}
PLACES = {'california', 'arizona', 'oregon', 'nevada', 'utah', 'texas', 'florida',
          'montana', 'washington', 'colorado', 'yosemite', 'seattle', 'portland',
          'phoenix', 'sedona', 'denver', 'los angeles', 'san francisco'}
EMOJI = {'fire': 'emoji:fire', 'money': 'emoji:money bag', 'broken': 'emoji:broken heart'}


def _sliders(kit):
    return ((kit.get('custom') or {}).get('sliders') or {})


def _level(kit, key):
    values = _sliders(kit)
    if key in values:
        return max(0, min(6, int(values[key])))
    kinds = {'transitions': 'transition', 'punch_ins': 'zoom_punch', 'emoji': 'popup',
             'motion': 'motion', 'overlays': 'graphic', 'three_d': 'three_d', 'broll': 'broll'}
    return 2 if any(p.get('kind') == kinds.get(key) for p in (kit.get('effects') or {}).values()) else 0


def _words(script):
    from letitedit.timeline.timeline_speech import timeline_words
    try:
        return timeline_words(script, cached_only=True)
    except TypeError:  # older test stubs
        return timeline_words(script)


def _word(w):
    return re.sub(r'[^a-z0-9]+', '', str(w.get('w', '')).lower())


def _time(w):
    return float(w.get('t0', w.get('s', 0)))


def _keep(candidates, cap, existing=()):
    """Prefer stronger evidence and spread devices over the whole edit."""
    if not cap:
        return []
    chosen = []
    occupied = [float(t) for t in existing]
    for score, at, item in sorted(candidates, key=lambda c: (-c[0], c[1])):
        if any(abs(at - t) < 1.2 for t in occupied):
            continue
        trial = occupied + [at]
        if any(sum(start <= t < start + 10 for t in trial) > cap for start in trial):
            continue
        chosen.append(item)
        occupied.append(at)
    return sorted(chosen, key=lambda x: x['at'])


def _safe_overlay(item, frame):
    """Try supported corner/side positions; decline if all cover a face, caption or feed button."""
    from letitedit.looks.fx import _inter, _area
    kind = item['kind']
    if kind == 'motion':
        block = item.get('block')
        if block == 'location':
            boxes = {'top-left': (.05, .05, .55, .22), 'top-right': (.45, .05, .95, .22)}
        elif block == 'count_up':
            boxes = {'left': (.05, .36, .39, .64), 'right': (.61, .36, .95, .64),
                     'top': (.34, .08, .66, .32)}
        elif block == 'steps':
            boxes = {'left': (.05, .27, .48, .73), 'right': (.52, .27, .95, .73)}
        else:
            return True
    elif kind == 'graphic' and item.get('template') == 'badge':
        boxes = {'top-left': (.04, .05, .4, .18), 'top-right': (.6, .05, .96, .18)}
    elif kind == 'three_d':
        boxes = {'bottom-left': (.04, .56, .30, .82), 'bottom-right': (.70, .56, .96, .82),
                 'top-left': (.04, .08, .30, .34), 'top-right': (.70, .08, .96, .34)}
    else:
        return True
    faces = frame.faces(item['at'] + min(.3, item['len'] / 2)) or []
    captions = frame.captions_at(item['at'], item['at'] + item['len'])
    covered = [x[:4] for x in frame.covered]
    for pos, box in boxes.items():
        if any(_inter(box, face) > .03 * _area(face) for face in faces):
            continue
        if any(_inter(box, cap) > .03 * min(_area(box), _area(cap)) for cap in captions):
            continue
        if any(_inter(box, z) > .1 * _area(box) for z in covered):
            continue
        if kind == 'three_d':
            item['position'] = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
            item['size'] = box[2] - box[0]
        else:
            item.setdefault('params', {})['position'] = pos
        item['_box'] = box
        return True
    return False


def plan(script, kit, op, existing=(), frame=None):
    """Return (items, notes). A caller can append hand-selected items afterwards."""
    from letitedit.timeline.edit_sync import layout, main_track
    from letitedit.looks.fx import _timeline_end

    duration = _timeline_end(script)
    courage = _level(kit, 'courage') if 'courage' in _sliders(kit) else 2
    notes = []
    try:
        words = _words(script)
    except Exception as exc:  # cached speech is optional
        words = []
        notes.append(f'no cached timeline words ({type(exc).__name__}); only cut-based effects considered')
    word_events = []
    for w in words:
        token, at = _word(w), _time(w)
        if 0.5 < at < duration - 0.6 and token:
            word_events.append((token, at))

    cuts = []
    main = main_track(script)
    if main:
        clips = [(it, s, e) for it, s, e in layout(main) if 'clip' in it]
        cuts = [s for it, s, e in clips[1:] if 0.5 < s < duration - 0.5]

    occupied = [r['at'] for r in existing if r.get('kind') not in ('sfx', 'whoosh')]
    out = []
    level = _level(kit, 'punch_ins')
    if level:
        candidates = []
        for token, at in word_events:
            if token in EMPHASIS or token in REVEAL:
                score = 3 if token in EMPHASIS else 2
                kind = 'push_in' if courage < 4 and token in REVEAL else 'zoom_punch'
                item = {'at': at, 'kind': kind, 'trigger': 'emphasis' if score == 3 else 'reveal',
                        'scale': round(1.09 + 0.025 * courage, 3),
                        'len': 1.8 if kind == 'push_in' else 0.65,
                        'ramp_s': 0.16, 'note': f'spoken {token}'}
                candidates.append((score, at, item))
        picked = _keep(candidates, CAPS[level], occupied)
        out += picked
        occupied += [x['at'] for x in picked]

    level = _level(kit, 'transitions')
    if level:
        candidates = []
        for at in cuts:
            near = [token for token, t in word_events if abs(t - at) < 1.0 and token in REVEAL]
            if near:
                transition = ('zoom_through' if courage >= 6 else 'whip_left' if courage >= 5
                              else 'push_left' if courage >= 4 else 'dissolve')
                candidates.append((3, at, {'at': at, 'kind': 'transition', 'trigger': 'topic_change',
                                           'transition': {'type': transition, 'len': 0.24},
                                           'note': f'topic turn near {near[0]}'}))
        picked = _keep(candidates, CAPS[level], occupied)
        out += picked
        occupied += [x['at'] for x in picked]

    level = _level(kit, 'motion')
    if level:
        candidates = []
        for token, at in word_events:
            if token.isdigit() or token in NUMBERS:
                value = int(token) if token.isdigit() else NUMBERS[token]
                if value <= 9999:
                    candidates.append((3, at, {'at': at, 'kind': 'motion', 'block': 'count_up',
                                                'params': {'to': value, 'position': 'left', 'size': 110},
                                                'len': 1.8, 'trigger': 'number', 'note': f'spoken number {token}'}))
            elif token in PLACES:
                candidates.append((3, at, {'at': at, 'kind': 'motion', 'block': 'location',
                                            'params': {'place': token.title(), 'position': 'top-left'},
                                            'len': 2.5, 'trigger': 'place', 'note': f'spoken place {token}'}))
            elif token in STEP:
                candidates.append((2, at, {'at': at, 'kind': 'motion', 'block': 'steps',
                                            'params': {'steps': [token.title()], 'current': 1,
                                                       'position': 'left'}, 'len': 2.0,
                                            'trigger': 'list_item', 'note': f'spoken step {token}'}))
        picked = _keep(candidates, CAPS[level], occupied)
        out += picked
        occupied += [x['at'] for x in picked]

    level = _level(kit, 'overlays')
    if level:
        candidates = [(2, at, {'at': at, 'kind': 'graphic', 'template': 'badge',
                                'params': {'text': token.upper(), 'position': 'top-left'},
                                'len': 1.2, 'trigger': 'reveal', 'note': f'spoken {token}'})
                      for token, at in word_events if token in ('before', 'after', 'saved', 'failed')]
        picked = _keep(candidates, CAPS[level], occupied)
        out += picked
        occupied += [x['at'] for x in picked]

    level = _level(kit, 'emoji')
    if level and courage >= 4:
        candidates = [(1, at, {'at': at, 'kind': 'popup', 'asset': EMOJI[token],
                                'zone': 'opposite_face', 'hold_s': 0.8,
                                'trigger': 'mention', 'note': f'spoken {token}'})
                      for token, at in word_events if token in EMOJI]
        out += _keep(candidates, min(2, CAPS[level]), occupied)

    level = _level(kit, 'three_d')
    model = op.get('model')
    if level:
        candidates = [(2, at, {'at': at, 'kind': 'three_d', 'model': model or 'builtin:title',
                                'params': {'move': {'type': 'reveal', 'framing_from': 1.0,
                                                    'framing_to': .78, 'degrees': 22},
                                           'text': token.upper(), 'background': 'transparent',
                                           'samples': 12},
                                'len': 1.8, 'trigger': 'reveal', 'note': f'spoken {token}'})
                      for token, at in word_events if token in REVEAL]
        out += _keep(candidates, min(1, CAPS[level]), occupied)

    density = (kit.get('fx') or {}).get('density') or {}
    overall = density.get('per_10s')
    if overall is not None:
        weights = {'transition': 4, 'three_d': 4, 'motion': 3, 'zoom_punch': 3,
                   'push_in': 3, 'graphic': 2, 'popup': 1}
        selected = _keep([(weights.get(item['kind'], 1), item['at'], item) for item in out],
                         int(overall), [r['at'] for r in existing if 'at' in r])
        if len(selected) < len(out):
            notes.append(f'{len(out) - len(selected)} candidate effect(s) left out to honor the style density')
        out = selected
    if frame is not None:
        safe = []
        for item in out:
            if _safe_overlay(item, frame):
                safe.append(item)
            else:
                notes.append(f"{item['kind']} at {item['at']:.2f} s skipped: no clear space around faces, captions and buttons")
        out = safe
    return sorted(out, key=lambda x: x['at']), notes
