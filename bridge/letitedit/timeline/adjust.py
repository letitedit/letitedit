"""Adjustment layers: a block on a track that changes everything below it in the stack and nothing above it.

The engine does this itself: a clip whose producer has meta.fx_cut has its effects run on the picture composited so far, once (the
app's own Adjustment Clip, Timeline > Generate; tests/t41/facts2.py). So a block is an ordinary timeline clip with ordinary effects:
dragging, trimming, the eye icon, Undo and the Filters panel are the app's own, and nothing else in the project depends on it.
"""
from __future__ import annotations

import uuid

ADJUST_PROP = 'meta.fx_cut'
COLOUR = '0'                        # the app's own: colour:0, transparent black
DEFAULT_NAME = 'Adjustment layer'
LONGEST_S = 4 * 3600                # as the app's own colour clips, so a person can drag it longer
# what the app blocks on an adjustment clip: they act on one clip's own picture or sound, so they have no meaning here
CLIP_ONLY = ('cairoblend_mode', 'blend_mode', 'qtblend_mode', 'blend_mode_qtblend', 'movit.overlay', 'crop', 'stabilize', 'vidstab',
             'audio_normalize_2p')


def is_marker(props):
    return str(props.get(ADJUST_PROP) or '') == '1'


def plain_item(item):
    """The colour clip a block compiles as."""
    out = {k: v for k, v in item.items() if k != 'adjust'}
    out['color'] = COLOUR
    out.setdefault('name', DEFAULT_NAME)
    if 'out' not in out:
        out['in'], out['out'] = 0.0, out.get('len', 0)      # the colour path takes a change of length this way
    return out


def mark(prod, fps):
    """Make a built colour clip a block."""
    import letitedit.timeline.edit_script as es
    es._set(prod, ADJUST_PROP, 1)
    es._set(prod, 'shotcut:producer', 'adjustment')
    es._set(prod, 'length', es.tm_clock(round(LONGEST_S * fps), fps))


def _free(script, name):
    names = {t['name'] for t in script['tracks']}
    out, n = name, 1
    while out in names:
        n += 1
        out = f'{name} {n}'
    return out


def _is_layer_track(track):
    return bool(track['items']) and all(it.get('adjust') or 'gap' in it for it in track['items'])


def _free_over(track, span):
    from letitedit.timeline.edit_sync import layout
    return not any(s < span[1] - 1e-6 and e > span[0] + 1e-6 for _, s, e in layout(track))


def _pick_track(script, op, span):
    """The track for a new block: one that holds only blocks and has room, or a new one, right where asked."""
    video = [t for t in script['tracks'] if t.get('kind', 'video') == 'video']
    if not video:
        raise ValueError('adjust: this project has no video track')
    below, above = op.get('below'), op.get('above')
    if below and above:
        raise ValueError('adjust takes below or above, not both')

    def named(name):
        t = next((x for x in script['tracks'] if x['name'] == name), None)
        if t is None or t not in video:
            raise ValueError(f'adjust: no video track named {name!r}')
        return t
    if below:
        spot = video.index(named(below))
        if spot == 0:
            raise ValueError(f'adjust: {below} is the first video track, so nothing is below it')
    elif above:
        spot = video.index(named(above)) + 1
    else:
        spot = len(video)
    neighbour = video[spot - 1] if spot >= 2 else None
    if neighbour is not None and _is_layer_track(neighbour) and _free_over(neighbour, span):
        return neighbour['name']
    name = _free(script, 'Adjustment')
    script['tracks'].insert(script['tracks'].index(video[spot - 1]) + 1, {'name': name, 'kind': 'video', 'items': []})
    return name


def apply_op(script, op):
    """{op: adjust, effects | effect, from, to | words, near, pad, below | above, name}. Sets op['_result'] and op['_pinned']."""
    import letitedit.timeline.aim as aim
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.stack as stack
    effects = op.get('effects')
    if effects is None and op.get('effect') is not None:
        effects = [op['effect']]
    if not effects:
        raise ValueError('adjust needs effects: a list of effects (letitedit_effects)')
    for e in effects:
        word = stack._word(e)
        if stack._is_audio(e):
            raise ValueError(f'adjust: {word} is a sound effect; an adjustment layer changes the picture only')
        if word in CLIP_ONLY:
            raise ValueError(f"adjust: {word} works on one clip's own picture, so it has no meaning on an adjustment layer")
    span = aim._span({**op, 'on': 'adjust'}, script)
    if span is None:
        span = (0.0, aim._end(script))
    if span[1] <= span[0]:
        raise ValueError('adjust: there is nothing on the timeline in that stretch')
    track = _pick_track(script, op, span)
    iid = op.get('id') or f'adjust-{uuid.uuid4().hex[:6]}'
    item = {'id': iid, 'adjust': True, 'len': round(span[1] - span[0], 4), 'name': op.get('name') or DEFAULT_NAME,
            'effects': list(effects)}
    es.apply_ops(script, [{'op': 'insert', 'track': track, 'at': round(span[0], 4), 'edge_mode': 'exact', 'item': item}])
    op['_pinned'] = iid
    words = ', '.join(str(stack._word(e)) for e in effects)
    op['_result'] = f'{words} on everything below {track}, {span[0]:.2f}-{span[1]:.2f} s, as a block on {track} ({iid})'
