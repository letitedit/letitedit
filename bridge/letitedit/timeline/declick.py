"""Declick: a one-frame audio ramp on both sides of every straight sound cut, so the waveform can't jump.

Two clips butted together on one track splice their sound at an arbitrary sample, which clicks; the joins view
found clicks at 100 of 130 straight dialogue cuts in our round projects, none of which had a fade. The `declick`
op gives each clip edge that meets another clip's sound a `fade_out_audio` / `fade_in_audio` of `frames` frames
(default 2: the level ramps over one frame, 33 ms at 30 fps, under the 50 ms pad before a first word). Left alone:
music tracks (score and soundtrack own them), edges at gaps or transitions, split edits (they cross over already),
muted clips and edges that already fade. Run late, like score: `{op: declick}` after the cut is final.
"""

FADE_KEYS = ('fade_in_audio', 'fade_out_audio')
# The edge frame dips this far, not to silence: a full fade left 34 ms of digital silence at each cut (a hole the
# joins view flags), while -24 dB still shrinks the waveform's jump to about a sixteenth.
FLOOR_DB = -24.0


def _effects(item):
    return item.get('effects') or []


def _has(item, key):
    return any(isinstance(e, dict) and key in e for e in _effects(item))


def _silent(item):
    return any(e == 'mute' or (isinstance(e, dict) and ('mute' in e or 'split_mute' in e)) for e in _effects(item))


def _sound_clip(item):
    return 'clip' in item and 'gap' not in item and not item.get('split_edit') and not _silent(item)


def apply_op(script, op):
    """Adds the ramps in place; returns {'edges': n, 'skipped': {...}} (also left on op['_result'])."""
    import letitedit.sound.music as music
    fps = float((script.get('profile') or {}).get('fps', 30) or 30)
    frames = max(2, int(op.get('frames', 2)))
    seconds = round(frames / fps, 4)
    floor = float(op.get('floor_db', FLOOR_DB))
    skip_tracks = {t['name'] for t in music.music_tracks(script)} | set(op.get('skip_tracks') or [])
    only = set(op.get('tracks') or [])
    edges, skipped = 0, {'transition': 0, 'split_edit': 0, 'already_fading': 0, 'muted_or_gap': 0}
    for t in script['tracks']:
        if t['name'] in skip_tracks or (only and t['name'] not in only):
            continue
        items = t['items']
        for a, b in zip(items, items[1:]):
            if not (_sound_clip(a) and _sound_clip(b)):
                skipped['muted_or_gap'] += 1
                continue
            if b.get('transition'):
                skipped['transition'] += 1
                continue
            if _has(a, 'split_mute') or _has(b, 'split_mute'):
                skipped['split_edit'] += 1
                continue
            added = False
            if not _has(a, 'fade_out_audio'):
                a['effects'] = list(_effects(a)) + [{'fade_out_audio': seconds, 'floor_db': floor}]
                added = True
            if not _has(b, 'fade_in_audio'):
                b['effects'] = list(_effects(b)) + [{'fade_in_audio': seconds, 'floor_db': floor}]
                added = True
            if added:
                edges += 1
            else:
                skipped['already_fading'] += 1
    res = {'edges': edges, 'frames': frames, 'seconds': seconds, 'floor_db': floor, 'skipped': skipped}
    op['_result'] = res
    return res
