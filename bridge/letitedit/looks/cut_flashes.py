"""Inverted flashes on the cuts between the speaker and the b-roll.

    {op: fx, cut_flashes: true | {len?, edges?, track?, sides?}}   plan() -> {kind: transition, transition: {type: cutaway_negative}}
                                                            items, one per cutaway edge that is a cut with the speaker
    missing(script)                                         the cutaway edges that carry no flash (the Look check reads it)

A flash is the editor's own Invert filter on the first or last frames of a full-frame b-roll clip, so the picture goes
negative for a moment right at the cut (the item type cutaway_negative; fx places it and keeps it editable). Edges next
to another cutaway (b-roll to b-roll), at the start of the video or at its end are not cuts with the speaker and get
none. The click that goes with it is sound_sync's transition click, placed on the same edges (`sync_sounds` in the same
fx op).
"""
from __future__ import annotations

import re

LEN_S = 0.034      # two frames at 60 fps; at 30 fps the engine rounds it to one whole frame
ADJOIN_S = 0.04
SPEAKER_BLOCK = 'Cut flash (speaker side)'


def _broll_tracks(script):
    return [t for t in script.get('tracks', []) if (t.get('kind') or 'video') == 'video'
            and re.search(r'(?i)b-?roll|cutaway', t.get('name') or '')]


def _eligible(item, profile):
    """A b-roll clip the flash can sit on: a clip, opaque and filling the frame."""
    import letitedit.looks.fx as fx
    if not item.get('clip'):
        return 'it is not a clip'
    width, height = (profile or {}).get('width', 1920), (profile or {}).get('height', 1080)
    for effect in item.get('effects') or []:
        if not isinstance(effect, dict):
            continue
        if any(key in effect for key in ('opacity', 'crop')):
            return 'it is not opaque full-frame'
        if 'size_position' in effect and not fx._fills_frame(effect['size_position'], width, height):
            return 'it does not fill the frame'
    return None


def _edges(script):
    """[(track, item, edge, at)] for every b-roll clip edge, with whether it joins another cutaway or the video's end."""
    from letitedit.timeline.edit_sync import layout, main_track
    main = main_track(script)
    end = max((e for _, _, e in layout(main)), default=0.0) if main else 0.0
    out = []
    for track in _broll_tracks(script):
        spans = [(it, s, e) for it, s, e in layout(track) if it.get('id') and ('clip' in it or 'image' in it or 'motion' in it)]
        for n, (it, s, e) in enumerate(spans):
            prev_end = spans[n - 1][2] if n else None
            next_start = spans[n + 1][1] if n + 1 < len(spans) else None
            out.append((track, it, 'in', s, s <= 0.04 or (prev_end is not None and abs(prev_end - s) < ADJOIN_S)))
            out.append((track, it, 'out', e, e >= end - 0.04 or (next_start is not None and abs(next_start - e) < ADJOIN_S)))
    return out


def plan(script, length=LEN_S, edges='both', track=None, sides='both'):
    if sides not in ('cutaway', 'both'):
        raise ValueError('fx cut_flashes: sides is both (the b-roll and the speaker flash, the default) or cutaway (the b-roll side only)')
    if edges not in ('both', 'in', 'out'):
        raise ValueError("fx cut_flashes: edges is both, in or out")
    if not .03 <= float(length) <= .2:
        raise ValueError('fx cut_flashes: len is .03 to .2 seconds')
    items, skipped, flashed, speaker = [], [], 0, []
    profile = script.get('profile') or {}
    for tr, it, edge, at, not_a_cut in _edges(script):
        if track and tr.get('name') != track:
            continue
        if edges != 'both' and edge != edges:
            continue
        label = f"{it['id']} {edge} at {at:.2f}s"
        if not_a_cut:
            skipped.append(f'{label}: not a cut with the speaker')
            continue
        why = _eligible(it, profile)
        if why:
            skipped.append(f'{label}: {why}')
            continue
        items.append({'kind': 'transition', 'id': it['id'], 'track': tr['name'], 'trigger': 'cut flash',
                      'transition': {'type': 'cutaway_negative', 'edge': edge, 'len': float(length)}})
        flashed += 1
        if sides == 'both':
            # the same pulse on the speaker's picture right before an 'in' cut or right after an 'out' cut
            speaker.append({'id': it['id'], 'track': tr['name'], 'edge': edge, 'from': round(max(0.0, at - float(length)), 4) if edge == 'in' else round(at, 4),
                            'to': round(at, 4) if edge == 'in' else round(at + float(length), 4)})
    return {'items': items, 'counts': {'cut_flash': flashed, 'speaker_flash': len(speaker)}, 'skipped': skipped,
            'speaker': speaker}


def plan_for_op(script, spec):
    spec = {} if spec is True else dict(spec or {})
    extra = sorted(set(spec) - {'len', 'edges', 'track', 'sides'})
    if extra:
        raise ValueError(f"fx cut_flashes: unknown {', '.join(extra)}; use len, edges (both | in | out), track, sides (both | cutaway)")
    return plan(script, spec.get('len', LEN_S), spec.get('edges', 'both'), spec.get('track'), spec.get('sides', 'both'))


def place_speaker_side(script, plan_result):
    """Blocks that invert the speaker's picture for the same frames (an adjustment layer just under the cutaway's own track).
    Returns the ids placed."""
    import letitedit.timeline.adjust as adjust
    import letitedit.timeline.edit_script as es
    old = [it['id'] for t in script['tracks'] for it in t['items'] if it.get('adjust') and it.get('name') == SPEAKER_BLOCK]
    if old:                                   # calling it again replaces the earlier blocks, it does not double them
        es.apply_ops(script, [{'op': 'delete', 'id': i} for i in old])
    ids = []
    for s in plan_result.get('speaker') or []:
        op = {'op': 'adjust', 'effects': [{'filter': 'invert'}], 'from': s['from'], 'to': s['to'], 'below': s['track'],
              'name': SPEAKER_BLOCK}
        adjust.apply_op(script, op)
        ids.append(op['_pinned'])
    return ids


def missing(script):
    """The cutaway edges that are cuts with the speaker but carry no flash: [{id, edge, at}]."""
    out = []
    for tr, it, edge, at, not_a_cut in _edges(script):
        if not_a_cut or _eligible(it, script.get('profile') or {}):
            continue
        has = any(isinstance(e, dict) and (e.get('cutaway_negative') or {}).get('edge') == edge
                  for e in it.get('effects') or [])
        if not has:
            out.append({'id': it['id'], 'edge': edge, 'at': round(at, 3)})
    return out
