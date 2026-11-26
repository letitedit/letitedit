"""Camera moves on cutaways: varied, and aware of what each clip already does.

Names are the film terms: the camera pans right when the picture slides left. A clip's own image motion is measured
first (cutaway_motion): one that already moves enough gets nothing, one that moves a little is topped up in its own
direction, never against it, and only a still or a static shot gets a chosen move. The chosen move comes from the
Look's measured spread of moves, never the same one twice in a row.

plan()   the {kind: camera_move} items for a project's cutaways, with each clip's own motion and the reason.
apply()  writes one move as a keyframed size and position on the clip (cover fit kept, so the frame stays filled).
"""
from __future__ import annotations

import math
import random
from pathlib import Path

MOVES = ('pan_left', 'pan_right', 'tilt_up', 'tilt_down', 'push_in', 'pull_out')
# image direction of the measurement (which way the picture slides) -> the camera move that causes it
FROM_IMAGE = {'left': 'pan_right', 'right': 'pan_left', 'up': 'tilt_down', 'down': 'tilt_up'}
TO_IMAGE = {v: k for k, v in FROM_IMAGE.items()}
STATIC_SPEED = 0.02          # frame fractions per second below which a shot does not move
STATIC_ZOOM = 0.006          # log scale per second
DEFAULTS = {'drift_per_s': 0.12, 'max_scale': 1.22, 'push': 0.10, 'ease': 'linear', 'enough': 0.8}


# ------------------------------------------------------------------ reading a clip's own motion

def own_motion(row):
    """The measured row of a clip (cutaway_motion.measure) as {state, move?, speed, zoom}.
    state: moving (enough to need nothing) | little | static | unknown."""
    if row is None or row.get('moving') is None and row.get('x_per_s') is None:
        return {'state': 'unknown'}
    x, y, z = float(row.get('x_per_s') or 0), float(row.get('y_per_s') or 0), float(row.get('zoom_per_s') or 0)
    speed = math.hypot(x, y)
    move = None
    if speed >= STATIC_SPEED:
        if abs(x) >= 2 * abs(y):
            move = FROM_IMAGE['right' if x > 0 else 'left']
        elif abs(y) >= 2 * abs(x):
            move = FROM_IMAGE['down' if y > 0 else 'up']
        else:
            move = FROM_IMAGE['right' if x > 0 else 'left']       # diagonal: follow its larger part's direction
    zoom_move = None
    if abs(z) >= STATIC_ZOOM:
        zoom_move = 'push_in' if z > 0 else 'pull_out'
    return {'state': 'measured', 'move': move, 'zoom_move': zoom_move, 'speed': round(speed, 4),
            'x_per_s': round(x, 4), 'y_per_s': round(y, 4), 'zoom_per_s': round(z, 4)}


def spread_from_visual(visual):
    """Counts of each move among a Look's measured cutaways (visual.json): {pan_left: n, ..., static: n}."""
    refs = visual.get('references') if isinstance(visual, dict) else None
    counts = {m: 0 for m in MOVES}
    counts['static'] = 0
    for ref in refs or []:
        for shot in ((ref or {}).get('broll_motion') or {}).get('shots', []):
            if shot.get('moving') is None:
                continue
            own = own_motion(shot)
            kind = own.get('move') or own.get('zoom_move')
            if kind and shot.get('moving'):
                counts[kind] += 1
            else:
                counts['static'] += 1
    return counts


def measure_clip(path, start, end):
    """The cutaway_motion row of source seconds start..end of a video file (None for a picture)."""
    suffix = Path(str(path)).suffix.lower()
    if suffix in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff'):
        return {'moving': False, 'x_per_s': 0.0, 'y_per_s': 0.0, 'zoom_per_s': 0.0, 'speed_per_s': 0.0, 'still': True}
    import letitedit.looks.cutaway_motion as cutaway_motion
    rows = cutaway_motion.measure(path, [{'start_s': float(start), 'end_s': float(end)}])['shots']
    return rows[0] if rows else None


# ------------------------------------------------------------------ choosing

OPPOSITE = {'pan_left': 'pan_right', 'pan_right': 'pan_left', 'tilt_up': 'tilt_down', 'tilt_down': 'tilt_up',
            'push_in': 'pull_out', 'pull_out': 'push_in'}


def choose(own, previous, spread, rule, rng, follow_motion=False, used=None):
    """(move | None, reason). own: own_motion(); previous: the move before this clip's (chosen, or a clip's own);
    used: {move: times chosen so far}, which makes a move less likely the more it has been used.
    A move never repeats the previous one, in any mode. follow_motion only decides what a clip that already moves
    a little gets: its own direction topped up (never against it), where otherwise a chosen move that does not oppose
    it. A static shot or a still always gets a chosen move."""
    enough = float(rule.get('enough', DEFAULTS['enough'])) * float(rule.get('drift_per_s', DEFAULTS['drift_per_s']))
    own_dir = None
    if own['state'] == 'measured':
        speed, zoom = own['speed'], abs(own['zoom_per_s'])
        if speed >= enough or zoom >= 0.02:
            return None, 'already moves enough (' + (own.get('move') or own.get('zoom_move') or 'motion') + ')'
        if own.get('move') and speed >= STATIC_SPEED:
            own_dir = own['move']
        elif own.get('zoom_move'):
            own_dir = own['zoom_move']
        if own_dir and follow_motion and own_dir != previous:
            return own_dir, 'moves a little: topped up in its own direction'
    weights = {m: (spread.get(m, 0) + 0.6) for m in MOVES} if spread else {m: 1.0 for m in MOVES}
    for m in weights:
        weights[m] /= 1 + (used or {}).get(m, 0)
    banned = {previous} if previous else set()
    if own_dir:
        banned.add(OPPOSITE[own_dir])        # a chosen move never works against what the clip itself does
    options = [m for m in weights if m not in banned] or [m for m in weights if m != previous]
    pick = rng.choices(options, weights=[weights[m] for m in options])[0]
    if own_dir:
        why = f'moves a little ({own_dir.replace("_", " ")}): a different, compatible move'
    else:
        why = 'static shot' if own['state'] == 'measured' else 'its motion could not be measured'
    return pick, f'{why}: a chosen move'


# ------------------------------------------------------------------ geometry

def _rect(x, y, w, h):
    return f'{x:.1f} {y:.1f} {w:.1f} {h:.1f} 1'


def geometry(move, W, H, cw, ch, length_s, rule=None, extra=None):
    """Keys [[0, rect], [length_s, rect, ease]] of a move over a clip of source size cw x ch in a W x H frame.
    extra: for a top-up, the extra speed (frame fractions per second) instead of the Look's drift."""
    rule = {**DEFAULTS, **(rule or {})}
    k = max(W / cw, H / ch)
    bw, bh = cw * k, ch * k                                # cover fit
    ease = rule['ease']
    L = max(0.2, float(length_s))
    max_scale = float(rule['max_scale'])
    info = {}
    if move in ('push_in', 'pull_out'):
        amount = float(rule['push']) if extra is None else max(0.02, min(float(rule['push']), extra * L))
        s0, s1 = (1.0, 1.0 + amount) if move == 'push_in' else (1.0 + amount, 1.0)
        rects = [_rect(-(bw * s - W) / 2, -(bh * s - H) / 2, bw * s, bh * s) for s in (s0, s1)]
        info = {'scale': [round(s0, 3), round(s1, 3)]}
    elif move in ('pan_left', 'pan_right', 'tilt_up', 'tilt_down'):
        horizontal = move.startswith('pan')
        frame = W if horizontal else H
        base = bw if horizontal else bh
        speed = float(rule['drift_per_s']) if extra is None else max(0.02, float(extra))
        travel = speed * frame * L
        s = 1.0
        if base - frame < travel * 1.02:
            s = min(max_scale, (frame + travel * 1.02) / base)
        room = base * s - frame
        travel = min(travel, room)
        centre = -room / 2
        # the camera pans right / tilts up: the picture slides left / down... (pan_right: left; tilt_up: down)
        slide = {'pan_right': -1, 'pan_left': 1, 'tilt_up': 1, 'tilt_down': -1}[move]
        a, b = centre - slide * travel / 2, centre + slide * travel / 2
        w, h = bw * s, bh * s
        if horizontal:
            rects = [_rect(a, -(h - H) / 2, w, h), _rect(b, -(h - H) / 2, w, h)]
        else:
            rects = [_rect(-(w - W) / 2, a, w, h), _rect(-(w - W) / 2, b, w, h)]
        info = {'scale': round(s, 3), 'travel_fraction': round(travel / frame, 3),
                'speed_per_s': round(travel / frame / L, 4)}
    else:
        raise ValueError(f"camera move is one of {', '.join(MOVES)}; got {move!r}")
    keys = [[0.0, rects[0]], [round(L, 4), rects[1], ease]]
    return keys, info


def _static_rect(effects):
    """True when the clip already has a moving size_position (its own move)."""
    for e in effects or []:
        if isinstance(e, dict) and isinstance(e.get('size_position'), dict):
            keys = e['size_position'].get('keys') or []
            if len({str(k[1]) for k in keys}) > 1:
                return True
    return False


def existing_move(effects):
    """The named camera move a keyed size and position already makes (None when there is none)."""
    for e in effects or []:
        sp = e.get('size_position') if isinstance(e, dict) else None
        keys = sp.get('keys') if isinstance(sp, dict) else None
        if keys and len(keys) >= 2:
            try:
                a = [float(v) for v in str(keys[0][1]).split()[:4]]
                b = [float(v) for v in str(keys[-1][1]).split()[:4]]
            except (ValueError, IndexError, TypeError):
                return None
            if abs(b[2] / a[2] - 1) > 0.02:
                return 'push_in' if b[2] > a[2] else 'pull_out'
            dx, dy = b[0] - a[0], b[1] - a[1]
            if abs(dx) >= abs(dy):
                return 'pan_right' if dx < 0 else 'pan_left'
            return 'tilt_down' if dy < 0 else 'tilt_up'
    return None


def _source_size(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return None
        return int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()


def apply(script, item, length_s, spec):
    """Write the move on a clip item: its static fit/size_position is replaced by the keyed one. Returns a note."""
    prof = script.get('profile') or {}
    W, H = int(prof.get('width', 1920)), int(prof.get('height', 1080))
    clip = item.get('clip') or item.get('image')
    size = _source_size(clip) if clip else None
    if size is None:
        raise ValueError(f"camera move: cannot read the picture size of {clip}")
    if _static_rect(item.get('effects')):
        if not spec.get('replace'):
            raise ValueError('camera move: the clip already has a moving size and position; take that out first')
        item['effects'] = [e for e in item['effects'] if not (isinstance(e, dict) and isinstance(e.get('size_position'), dict)
                                                              and len({str(k[1]) for k in e['size_position'].get('keys') or []}) > 1)]
    keys, info = geometry(spec['move'], W, H, size[0], size[1], length_s,
                          {k: spec[k] for k in ('drift_per_s', 'max_scale', 'push', 'ease') if spec.get(k) is not None},
                          spec.get('extra_per_s'))
    effects = [e for e in (item.get('effects') or [])
               if not (isinstance(e, dict) and 'size_position' in e and not isinstance(e['size_position'], dict))]
    effects.append({'size_position': {'keys': keys}})
    item['effects'] = effects
    return f"{spec['move'].replace('_', ' ')} " + ', '.join(f'{k} {v}' for k, v in info.items())


# ------------------------------------------------------------------ the plan for a project

def _cutaways(script):
    from letitedit.timeline.edit_sync import layout
    import re
    out = []
    for t in script['tracks']:
        if not re.search(r'b-?roll|cutaway', t['name'], re.I) or (t.get('kind') or 'video') != 'video':
            continue
        for it, s, e in layout(t):
            if it.get('clip') or it.get('image'):
                out.append((s, e, t, it))
    out.sort(key=lambda x: x[0])
    return out


def plan(script, spread=None, rule=None, follow_motion=False, moving_target=None, seed=11, measure=True,
         keep_existing=False):
    """Items for {op: fx, camera_moves}: [{kind: camera_move, id, move, ...}] and a report row per cutaway."""
    rule = {**DEFAULTS, **(rule or {})}
    rng = random.Random(seed)
    clips = _cutaways(script)
    rows = []
    for s, e, t, it in clips:
        replace = _static_rect(it.get('effects')) and not keep_existing    # a move from an earlier call is chosen again
        if _static_rect(it.get('effects')) and keep_existing:
            rows.append({'id': it.get('id'), 'at': round(s, 3), 'len': round(e - s, 3), 'state': 'own move',
                         'why': 'already has a moving size and position', 'own': {'state': 'measured'}, 'item': it,
                         'skip': True})
            continue
        clip = it.get('clip') or it.get('image')
        row = None
        if measure and it.get('clip'):
            try:
                import letitedit.core.render_lock as render_lock
                with render_lock.slot('camera moves: measuring cutaways', timeout_s=1800):
                    row = measure_clip(it['clip'], float(it.get('in', 0)), float(it.get('out', 0)) or
                                       float(it.get('in', 0)) + (e - s))
            except Exception:  # noqa: BLE001 - unreadable file: its motion stays unknown
                row = None
        elif it.get('image'):
            row = measure_clip(clip, 0, 1)
        rows.append({'id': it.get('id'), 'at': round(s, 3), 'len': round(e - s, 3), 'own': own_motion(row),
                     'row': row, 'item': it, 'replace': replace})
    natural = sum(1 for r in rows if r['own']['state'] == 'measured' and not r.get('skip')
                  and (r['own']['speed'] >= STATIC_SPEED or abs(r['own']['zoom_per_s']) >= STATIC_ZOOM))
    todo = [r for r in rows if not r.get('skip')]
    needed = len(todo)
    if moving_target is not None:
        needed = max(0, math.ceil(float(moving_target) * len(rows)) - natural)
    items, report, previous, chosen_count, used = [], [], None, 0, {}
    # clips that are already enough or are topped up come first in the order of time; static ones are spread evenly
    static = [r for r in todo if r['own']['state'] != 'measured'
              or (r['own']['speed'] < STATIC_SPEED and abs(r['own']['zoom_per_s']) < STATIC_ZOOM)]
    allowed = set()
    if static and needed < len(static):
        step = len(static) / max(1, needed)
        allowed = {id(static[min(len(static) - 1, int(i * step))]) for i in range(needed)} if needed else set()
    else:
        allowed = {id(r) for r in static}
    for r in rows:
        base = {k: r[k] for k in ('id', 'at', 'len')}
        if r.get('skip'):
            report.append({**base, 'move': None, 'why': r['why'], 'own': 'own move'})
            previous = existing_move(r['item'].get('effects'))
            continue
        own = r['own']
        is_static = r in static
        if is_static and id(r) not in allowed:
            report.append({**base, 'move': None, 'own': _own_text(own),
                           'why': "left still: the Look's share of moving cutaways is already met"})
            continue
        move, why = choose(own, previous, spread, rule, rng, follow_motion, used)
        if move is None:
            report.append({**base, 'move': None, 'own': _own_text(own), 'why': why})
            previous = own.get('move') or own.get('zoom_move') or previous
            continue
        item = {'kind': 'camera_move', 'id': r['id'], 'move': move, 'note': f'{move.replace("_", " ")}: {why}'}
        if r.get('replace'):
            item['replace'] = True
        topped_up = not is_static and own['state'] == 'measured' and move in (own.get('move'), own.get('zoom_move'))
        if topped_up:
            target = float(rule['drift_per_s'])
            if move in ('push_in', 'pull_out'):
                item['extra_per_s'] = max(0.02, 0.012 - abs(own['zoom_per_s']))
            else:
                item['extra_per_s'] = round(max(0.02, target - own['speed']), 4)
        for key in ('drift_per_s', 'max_scale', 'push', 'ease'):
            if key in (rule or {}) and rule[key] != DEFAULTS.get(key):
                item[key] = rule[key]
        items.append(item)
        report.append({**base, 'move': move, 'own': _own_text(own), 'why': why})
        previous = move
        used[move] = used.get(move, 0) + 1
        chosen_count += 1
    return {'items': items, 'report': report, 'counts': {'moved': chosen_count, 'cutaways': len(rows),
                                                          'left_alone': len(rows) - chosen_count}}


def _own_text(own):
    if own['state'] != 'measured':
        return 'unmeasured'
    bits = []
    if own['speed'] >= STATIC_SPEED:
        bits.append(f"{TO_IMAGE.get(own['move'], 'drift')} drift {own['speed']:.2f} frame widths/s" if own.get('move')
                    else f"drift {own['speed']:.2f}/s")
    if own.get('zoom_move'):
        bits.append(f"{own['zoom_move'].replace('_', ' ')} {own['zoom_per_s']:+.3f}/s")
    return ', '.join(bits) or 'static'


def plan_for_op(script, spec):
    """plan() for {op: fx, camera_moves: true | {look?, spread?, follow_motion?, drift_per_s?, max_scale?, push?, ease?,
    moving_target?, seed?}}."""
    spec = {} if spec is True else dict(spec or {})
    allowed = {'look', 'spread', 'follow_motion', 'drift_per_s', 'max_scale', 'push', 'ease', 'moving_target', 'seed',
               'measure', 'keep_existing'}
    extra = sorted(set(spec) - allowed)
    if extra:
        raise ValueError(f"fx camera_moves: unknown {', '.join(extra)}; use {', '.join(sorted(allowed))}")
    spread, look_rule, follow, target = spec.get('spread'), {}, spec.get('follow_motion'), spec.get('moving_target')
    if spread is None:
        look = spec.get('look')
        try:
            if not look:
                import letitedit.looks.look_inputs as look_inputs
                look = (look_inputs.read(script.get('project')) or {}).get('look')
            if look:
                import json
                import letitedit.looks.looks as looks
                card = looks.read(look)
                recipe = Path(card['recipe'])
                visual = recipe.with_name('visual.json')
                if visual.is_file():
                    data = json.loads(visual.read_text(encoding='utf-8-sig'))
                    spread = spread_from_visual(data)
                    refs = [((r or {}).get('broll_motion') or {}) for r in data.get('references', [])]
                    speeds = [r['median_speed_per_s'] for r in refs if r.get('median_speed_per_s')]
                    if speeds and spec.get('drift_per_s') is None:
                        look_rule['drift_per_s'] = max(0.06, min(0.2, sum(speeds) / len(speeds)))
                text = recipe.read_text(encoding='utf-8') if recipe.is_file() else ''
                if follow is None and 'pans follow the scene' in text.lower():
                    follow = True
        except Exception:  # noqa: BLE001 - no Look: the plain vocabulary
            spread = spread
    rule = {**look_rule, **{k: spec[k] for k in ('drift_per_s', 'max_scale', 'push', 'ease') if spec.get(k) is not None}}
    return plan(script, spread, rule, bool(follow), target, int(spec.get('seed', 11)), spec.get('measure', True) is not False,
                bool(spec.get('keep_existing')))
