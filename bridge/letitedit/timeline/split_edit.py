"""Split edits (J and L cuts) on any picture track, built from the timeline's ordinary pieces.

A cut from clip A to clip B on a picture track switches picture and sound on the same frame. A split edit moves the
sound cut away from the picture cut, the way an editor rolls only the audio edit point:

    {op: split_edit, id: B, lead: 0.5}   J cut: B's sound starts 0.5 s before its picture (under A's last 0.5 s)
    {op: split_edit, id: B, lag: 0.5}    L cut: A's sound runs on 0.5 s under B's picture
    {op: split_edit, id: B, lead: 0}     back to a straight cut (lag: 0 too)

`move: sound` (the default) keeps the picture cut and reaches into the source beyond the clip's edge (B's file before
its in point for a J cut, A's file after its out point for an L cut). `move: picture` keeps the sound cut where it is
and moves the picture cut instead (later for a J cut: A's picture holds while B's sound starts; earlier for an L cut:
B's picture comes in while A is still heard): the sound of the timeline doesn't change, apart from a crossfade at
the sound cut.

How it is built (one undo step, like every op):
- The moved sound is a clip of the same file on an audio track (default `J/L cuts`, added at the end when missing),
  placed frame for frame: a J cut plays B's source [B.in - lead, B.in] (after one silent frame: the engine ramps a
  gain from the previous frame's, and a clip's first frame has none) and ends on the frame B's picture starts; an L
  cut plays A's source [A.out, A.out + lag] from the frame A's picture ends. Same file, same source time: the sound
  stays in sync with its own picture and joins the clip's own sound without a seam (measured bit-exact in renders).
- The clip whose sound is covered gets a `split_mute` effect (a keyframed Gain/Volume filter in Shotcut): A's last
  `lead` seconds (J) or B's first `lag` seconds (L) are silent.
- At the sound cut the two sounds cross over `fade` seconds (0.1 s by default; equal power, keyed frame by frame;
  the engine ramps the gain inside each frame), so nothing clicks.
- The moved clip (the bridge) carries the record: `split_edit: {into, out_of, lead | lag, fade}`. After every edit
  made through the tools, `refresh` rebuilds the bridges and mutes from the records, so trims, ripples, tighten and
  speech levelling keep each split edit right. A record whose cut no longer exists (A or B deleted or moved apart,
  a clip put between them, a transition added) is removed with a note; one that no longer fits its source handles
  or clip lengths is shortened to the most that fits, with a note. Edits made by hand in the Shotcut window are
  picked up at the next tool edit (deleting the bridge clip by hand deletes the split edit).
"""
from __future__ import annotations

import json
import math
import os

TRACK = 'J/L cuts'          # the default audio track for the moved sound (not a music/sfx name: speech tools see it)
FADE_S = 0.1                # the crossfade at the sound cut
FLOOR_DB = -100.0           # "silent" on a Gain/Volume key (1e-5 of the amplitude)
MIN_FRAMES = 2              # the shortest lead or lag
KINDS = {'lead': 'J', 'lag': 'L'}


# ------------------------------------------------------------------ small helpers

def _fps(script):
    return float((script.get('profile') or {}).get('fps', 30))


def _r(x, nd=4):
    return round(float(x), nd)


def _sec(v):
    from letitedit.timeline.edit_script import to_seconds
    return to_seconds(v)


def _clock(s):
    from letitedit.timeline.edit_script import clock
    return clock(s)


def record(it):
    """The split-edit record a bridge clip carries, or None."""
    r = it.get('split_edit') if isinstance(it, dict) else None
    return r if isinstance(r, dict) and r.get('into') else None


def is_mute(e):
    return isinstance(e, dict) and 'split_mute' in e


def _db(g):
    return round(20 * math.log10(max(g, 10 ** (FLOOR_DB / 20))), 2) if g < 1 - 1e-12 else 0.0


def _gain_in(j, k):
    return _db(math.sin(math.pi / 2 * j / k)) if k else 0.0


def _gain_out(j, k):
    return _db(math.cos(math.pi / 2 * j / k)) if k else FLOOR_DB


def mute_keys(spec, n, fps):
    """Gain keys [[seconds from the clip start, dB], ...] of a {split_mute: {tail | head, fade}} on a clip n frames
    long: silent over its last `tail` (first `head`) seconds, crossing over `fade` seconds at the sound cut."""
    side = 'tail' if 'tail' in spec else 'head'
    m = max(1, round(_sec(spec[side]) * fps))
    k = max(1, min(round(_sec(spec.get('fade', FADE_S)) * fps), max(1, m - 1)))
    pts = []
    if side == 'tail':
        e = n - m                                    # the frame the other clip's sound starts on (the sound cut)
        pts.append((0, 0.0))
        # the engine ramps each frame from the previous frame's gain to its own: keyed from the frame before the
        # sound cut, the fall happens during the k frames from the sound cut on, in step with the moved sound's rise
        pts += [(e - 1 + j, _gain_out(j, k)) for j in range(0, k + 1)]
        pts.append((n - 1, FLOOR_DB))
    else:
        w = m - 1 - k                                # the crossover ends on the clip's frame m - 1
        pts.append((0, FLOOR_DB))
        pts += [(w + j, _gain_in(j, k)) for j in range(0, k + 1)]
        pts.append((n - 1, 0.0))
    out = {}
    for f, v in pts:
        f = min(max(0, f), max(0, n - 1))
        out[f] = v
    return [[_r(f / fps, 6), v] for f, v in sorted(out.items())]


def _bridge_keys(kind, m, k, fps):
    """The bridge's own crossover: a J bridge (one silent frame, then the m frames of the lead) rises over the k
    frames after its silent first frame (a filter's first frame can't ramp, so it starts at 0); an L bridge (m
    frames) falls over its last k frames."""
    if kind == 'lead':
        return [[_r(j / fps, 6), _gain_in(j, k)] for j in range(0, k + 1)]
    w = m - 1 - k
    return [[0.0, 0.0]] + [[_r((w + j) / fps, 6), _gain_out(j, k)] for j in range(0, k + 1) if w + j > 0]


# ------------------------------------------------------------------ the timeline in frames, as the compiler writes it

def _plain_clip(it):
    import letitedit.timeline.made as made
    return 'clip' in it and 'graphic' not in it and not made.is_made(it) and 'raw' not in it


def _source_frames(clip, fps, speed=1.0):
    import letitedit.timeline.edit_script as es
    from pathlib import Path
    if Path(clip).suffix.lower() in es.IMAGE_EXT:
        return None
    dur = es.probe(clip).get('duration') or 0.0
    return int(round(dur * fps / speed)) if dur else None


def item_frames(it, fps):
    """(first source frame, frames on the timeline) of an item, as compile_script rounds them."""
    import letitedit.timeline.edit_script as es
    from letitedit.timeline.edit_sync import item_len
    if _plain_clip(it) or ('color' in it and 'out' in it):
        es.fill_out(it)
        speed = float(it.get('speed', 1.0))
        a = round(_sec(it['in']) * fps / speed)
        b = round(_sec(it['out']) * fps / speed) - 1
        if _plain_clip(it):
            plen = _source_frames(it['clip'], fps, speed)
            if plen and b >= plen and b - plen <= round(0.15 * fps) and plen > a:
                b = plen - 1
        return a, max(1, b - a + 1)
    return 0, max(1, round(item_len(it) * fps))


def frame_layout(script, t, fps=None):
    """[(item, start_frame, end_frame)] of a track's clips, the way compile_script places them (main picture track:
    frames summed one by one; other tracks: each item on the frame of its time)."""
    import letitedit.timeline.edit_script as es
    from letitedit.timeline.edit_sync import layout, main_track
    fps = fps or _fps(script)
    items = t['items']
    anchored = {} if t is main_track(script) else {id(it): st for it, st, _ in layout(t)}
    pos, out, prev_clip = 0, [], False
    for k, it in enumerate(items):
        if 'gap' in it:
            nxt = items[k + 1] if k + 1 < len(items) else {}
            if (nxt.get('pin') and nxt.get('at') is not None) or (id(nxt) in anchored and not nxt.get('transition')):
                prev_clip = False
                continue
            n = round(_sec(it['gap']) * fps)
            if n > 0:
                pos += n
                prev_clip = False
            continue
        if 'omitted' in it:
            continue
        if id(it) in anchored and not it.get('transition'):
            pos = max(pos, round(anchored[id(it)] * fps))
        elif it.get('pin') and it.get('at') is not None:
            pos = max(pos, round(_sec(it['at']) * fps))
        n = item_frames(it, fps)[1]
        spec = es.transition_spec(it.get('transition'))
        if spec and prev_clip:
            nt = round(spec['len'] * fps)
            out.append((it, pos - nt, pos - nt + n))
            pos += n - nt
        else:
            out.append((it, pos, pos + n))
            pos += n
        prev_clip = 'raw' not in it
    return out


def _find_cut(script, into):
    """(track, frame layout, index of the incoming item) for an item id; also follows tighten's pieces (from:)."""
    for t in script['tracks']:
        if t.get('kind', 'video') != 'video':
            continue
        lay = frame_layout(script, t)
        for i, (it, s, e) in enumerate(lay):
            if it.get('id') == into:
                return t, lay, i
    for t in script['tracks']:
        if t.get('kind', 'video') != 'video':
            continue
        lay = frame_layout(script, t)
        for i, (it, s, e) in enumerate(lay):
            if it.get('from') == into:
                return t, lay, i
    return None, None, None


def _has_sound(it):
    import letitedit.timeline.edit_script as es
    from pathlib import Path
    if not _plain_clip(it) or Path(it['clip']).suffix.lower() in es.IMAGE_EXT:
        return False
    try:
        return es.probe(it['clip'])['audio_index'] >= 0
    except Exception:  # noqa: BLE001 - an unreadable file has no sound to split
        return False


def _muted(it):
    return any(e == 'mute' or (isinstance(e, dict) and 'mute' in e) for e in it.get('effects') or [])


def _label(it):
    return f"{it.get('id')} ({os.path.basename(it.get('clip', '')) or it.get('name') or 'item'})"


# ------------------------------------------------------------------ words around a cut

def _words(clip, a, b):
    """Words (cached transcript) overlapping the source range a-b of a file: ([{'w', 's', 'e'}], 'words'),
    or voiced spans ([{'w': '(voice)', 's', 'e'}], 'voice') when the file isn't transcribed, or ([], None)."""
    try:
        import letitedit.footage.speech as speech
        ws = speech.cached_words(clip, max(0.0, a - 3.0), b + 0.5)
    except Exception:  # noqa: BLE001
        ws = None
    if ws is not None:
        return [w for w in ws if float(w['e']) > a + 1e-3 and float(w['s']) < b - 1e-3], 'words'
    try:
        import letitedit.sound.music as music
        voice = music.voice_times(clip)
    except Exception:  # noqa: BLE001 - no voice detection either
        return [], None
    return [{'w': '(voice)', 's': float(x), 'e': float(y)} for x, y in voice if y > a + 0.05 and x < b - 0.05], 'voice'


def _mostly_inside(w, a, b):
    ws, we = float(w['s']), float(w['e'])
    if we - ws < 1e-3:
        return a <= ws <= b
    return max(0.0, min(we, b) - max(ws, a)) >= 0.5 * (we - ws)


CLIP_S = 0.1    # a covered word: mostly inside the covered sound, or this much of it covered (heard cut off)


def _covered(w, a, b):
    ws, we = float(w['s']), float(w['e'])
    return _mostly_inside(w, a, b) or max(0.0, min(we, b) - max(ws, a)) >= CLIP_S


def _said(ws):
    return ' '.join(str(w['w']).strip() for w in ws).strip()


# ------------------------------------------------------------------ geometry of one split edit

class Refused(ValueError):
    pass


def _reserved(script, records, fps, skip=None):
    """{item id: {'head': frames, 'tail': frames}} the other split edits already use on each clip."""
    out = {}
    for r in records:
        if r is skip or r.get('into') == (skip or {}).get('into'):
            continue
        t, lay, i = _find_cut(script, r['into'])
        if t is None or i == 0:
            continue
        a_it, b_it = lay[i - 1][0], lay[i][0]
        if 'lead' in r:
            out.setdefault(a_it.get('id'), {}).setdefault('tail', 0)
            out[a_it['id']]['tail'] = max(out[a_it['id']]['tail'], round(_sec(r['lead']) * fps) + 1)
        elif 'lag' in r:
            out.setdefault(b_it.get('id'), {}).setdefault('head', 0)
            out[b_it['id']]['head'] = max(out[b_it['id']]['head'], round(_sec(r['lag']) * fps))
    return out


def geometry(script, into, kind, records=(), skip=None):
    """Everything about the cut into `into` that a split edit needs, or raises Refused with the reason:
    {track, lay, i, A, B, a0, T, nA, nB, fps, max_frames, max_picture_frames, ...} (frames)."""
    fps = _fps(script)
    t, lay, i = _find_cut(script, into)
    if t is None:
        raise Refused(f'no clip with id {into} on a picture track')
    B, sB, eB = lay[i]
    if i == 0:
        raise Refused(f'{_label(B)} is the first clip on {t["name"]}: a split edit needs a clip right before it')
    A, sA, eA = lay[i - 1]
    if B.get('transition'):
        raise Refused(f'{_label(B)} has a transition in (its own sound crossfade); remove it first '
                      '({op: set, id, transition: null}) or keep the transition instead of a split edit')
    if eA != sB:
        gap = (sB - eA) / fps
        raise Refused(f'{_label(B)} does not follow a clip directly on {t["name"]} '
                      f'({"a gap of %.2f s" % gap if gap > 0 else "they overlap"}): a split edit is made at a cut')
    for it in (A, B):
        if _plain_clip(it) and (abs(float(it.get('speed', 1.0)) - 1.0) > 1e-9 or it.get('reverse')):
            raise Refused(f'{_label(it)} plays at {it.get("speed", 1)}x{" reversed" if it.get("reverse") else ""}: '
                          'split edits work on clips at normal speed')
    giver, taker = (B, A) if kind == 'lead' else (A, B)
    for it in (A, B):
        if _plain_clip(it) and not os.path.exists(it['clip']):
            raise Refused(f"{_label(it)}'s file can't be found ({it['clip']})")
    if not _has_sound(giver):
        raise Refused(f'{_label(giver)} has no sound to {"lead with" if kind == "lead" else "run on"}')
    if _muted(giver):
        raise Refused(f'{_label(giver)} is muted: there is no sound to {"lead with" if kind == "lead" else "run on"}')
    nA, nB = eA - sA, eB - sB
    res = _reserved(script, records, fps, skip=skip)
    headA = res.get(A.get('id'), {}).get('head', 0)
    tailB = res.get(B.get('id'), {}).get('tail', 0)
    trA = 0                                          # A's own transition in: its sound mixes with the clip before
    if A.get('transition') and i >= 2:
        import letitedit.timeline.edit_script as es
        trA = round(es.transition_spec(A['transition'])['len'] * fps)
    g = {'track': t, 'lay': lay, 'i': i, 'A': A, 'B': B, 'sA': sA, 'T': sB, 'eB': eB, 'nA': nA, 'nB': nB,
         'fps': fps, 'headA': headA, 'tailB': tailB, 'trA': trA}
    UNLIMITED = 10 ** 9
    if kind == 'lead':
        # the moved sound starts one silent frame before the sound cut (see _bridge_keys): that frame is needed too
        b_in = item_frames(B, fps)[0]
        room = nA - headA - trA - 1
        g['handle'], g['room'] = b_in - 1, room
        g['max_frames'] = max(0, min(b_in - 1, room))
        g['why_max'] = (f"{_label(B)}'s file has {b_in / fps:.3f} s before its in point (a frame of it starts the "
                        "crossfade)" if b_in - 1 <= room else
                        f"{_label(A)} is {nA / fps:.3f} s long" + (f' ({(headA + trA) / fps:.3f} s of it under an L '
                                                                   'cut or a transition)' if headA + trA else ''))
        # move: picture: A's picture runs on past its out point (its file must go on), B starts later (B stays >= 1 frame)
        if not _plain_clip(A) or _source_frames(A['clip'], fps) is None:
            a_handle = UNLIMITED                     # a still, a colour or a graphic can simply be longer
        else:
            a_in, a_n = item_frames(A, fps)
            a_handle = _source_frames(A['clip'], fps) - (a_in + a_n)
        b_room = nB - tailB - 1
        g['max_picture_frames'] = max(0, min(a_handle, b_room)) if b_in >= 1 else 0
        g['why_picture'] = (f"{_label(B)} starts on the first frame of its file; a J cut needs one frame before it"
                            if b_in < 1 else f"{_label(A)}'s file has {max(0, a_handle) / fps:.3f} s after its out point"
                            if a_handle <= b_room else f"{_label(B)} is {nB / fps:.3f} s long"
                            + (f' ({tailB / fps:.3f} s of it under a J cut)' if tailB else ''))
    else:
        a_in, a_n = item_frames(A, fps)
        a_handle = (_source_frames(A['clip'], fps) or 0) - (a_in + a_n)
        room = nB - tailB
        g['handle'], g['room'] = a_handle, room
        g['max_frames'] = max(0, min(a_handle, room))
        g['why_max'] = (f"{_label(A)}'s file has {max(0, a_handle) / fps:.3f} s after its out point" if a_handle <= room
                        else f"{_label(B)} is {nB / fps:.3f} s long" + (f' ({tailB / fps:.3f} s of it under a J cut)'
                                                                        if tailB else ''))
        # move: picture: B's picture starts earlier (its file must have it), A ends earlier (A stays >= 1 frame)
        if not _plain_clip(B) or _source_frames(B['clip'], fps) is None:
            b_handle = UNLIMITED
        else:
            b_handle = item_frames(B, fps)[0]
        a_room = nA - headA - trA - 1
        g['max_picture_frames'] = max(0, min(b_handle, a_room))
        g['why_picture'] = (f"{_label(B)}'s file has {max(0, b_handle) / fps:.3f} s before its in point"
                            if b_handle <= a_room else f"{_label(A)} is {nA / fps:.3f} s long"
                            + (f' ({(headA + trA) / fps:.3f} s of it under an L cut or a transition)'
                               if headA + trA else ''))
    return g


def _plan(g, kind, m, k):
    """Source ranges (seconds) of the bridge and of the covered sound, and timeline frames of the sound cut."""
    fps, A, B, T = g['fps'], g['A'], g['B'], g['T']
    if kind == 'lead':
        b_in = item_frames(B, fps)[0]
        src = (B['clip'], (b_in - m - 1) / fps, b_in / fps)          # a silent first frame, then the lead
        a_in, a_n = item_frames(A, fps) if _plain_clip(A) else (0, g['nA'])
        covered = ((A['clip'], (a_in + a_n - m) / fps, (a_in + a_n) / fps) if _has_sound(A) and not _muted(A)
                   else None)
        return {'bridge_src': src, 'bridge_at': T - m - 1, 'covered': covered, 'sound_cut': T - m, 'giver': B,
                'taker': A, 'heard_src': (B['clip'], (b_in - m) / fps, b_in / fps)}
    a_in, a_n = item_frames(A, fps)
    src = (A['clip'], (a_in + a_n) / fps, (a_in + a_n + m) / fps)
    b_in = item_frames(B, fps)[0] if _plain_clip(B) else 0
    covered = (B['clip'], b_in / fps, (b_in + m) / fps) if _has_sound(B) and not _muted(B) else None
    return {'bridge_src': src, 'bridge_at': T, 'covered': covered, 'sound_cut': T + m, 'giver': A, 'taker': B,
            'heard_src': src}


def _audio_effects(it):
    """The source clip's effects that shape its sound, for the bridge: static gain and audio filters."""
    out = []
    for e in it.get('effects') or []:
        if isinstance(e, dict) and isinstance(e.get('gain'), (int, float)) and not isinstance(e.get('gain'), bool):
            out.append({'gain': e['gain']})
        elif isinstance(e, dict) and 'filter' in e:
            try:
                import letitedit.timeline.effects_catalog as effects_catalog
                kind = effects_catalog.resolve(e['filter'])['kind']
            except Exception:  # noqa: BLE001 - unknown to the catalogue: judge by its name
                kind = 'audio' if 'audio' in str(e['filter']).lower() or str(e['filter']).startswith(('sox', 'ladspa')) \
                    else 'video'
            if kind == 'audio':
                out.append(json.loads(json.dumps(e)))
    return out


def _words_report(plan, kind, fps):
    """(lost words, brought-in words, a note about a word cut at the far end of the moved sound)."""
    lost, kind_lost = [], None
    if plan['covered']:
        clip, a, b = plan['covered']
        ws, kind_lost = _words(clip, a, b)
        lost = [w for w in ws if _covered(w, a, b)]
    clip, a, b = plan['heard_src']
    ws, src_kind = _words(clip, a, b)
    brought = [w for w in ws if _mostly_inside(w, a, b)]
    edge = None
    far = a if kind == 'lead' else b
    for w in ws:
        if float(w['s']) < far - 0.02 < float(w['e']) - 0.0 and src_kind == 'words':
            lo = max(0.0, (b - float(w['s'])) if kind == 'lead' else (float(w['s']) - a))
            hi = (b - float(w['e'])) if kind == 'lead' else (float(w['e']) - a)
            edge = (f'the moved sound {"starts" if kind == "lead" else "ends"} inside the word "{str(w["w"]).strip()}"'
                    f' ({"a lead" if kind == "lead" else "a lag"} of {max(lo, hi) + 0.05:.2f} s takes all of it, '
                    f'{max(0.0, min(lo, hi) - 0.05):.2f} s none of it)')
            break
    return lost, kind_lost, brought, src_kind, edge


# ------------------------------------------------------------------ the op

def records_of(script):
    return [(t, it, record(it)) for t in script['tracks'] for it in t['items'] if record(it)]


def _bridge_id(into, kind):
    return f'{into}.{kind}'


def apply_op(script, op):
    """{op: split_edit, id, lead | lag, move?, fade?, track?, drop_words?}: record (or remove) the split edit at the
    cut into `id` and build it. Raises ValueError (nothing changed) when it can't be made, naming the most possible."""
    into = op['id']
    kind = 'lead' if op.get('lead') is not None else 'lag'
    want = _sec(op.get(kind) or 0)
    move = op.get('move') or 'sound'
    fade = _sec(op['fade']) if op.get('fade') is not None else FADE_S
    fps = _fps(script)
    existing = [(t, it, r) for t, it, r in records_of(script) if r['into'] == into]
    others = [r for t, it, r in records_of(script) if r['into'] != into]
    if want <= 1e-9:
        if not existing:
            op['_result'] = f'no split edit at the cut into {into}: nothing to remove'
            return
        for t, it, r in existing:
            t['items'] = [x for x in t['items'] if x is not it]
        op['_result'] = f"removed the {KINDS['lead' if 'lead' in existing[0][2] else 'lag']} cut into {into}: a straight cut"
        return
    try:
        g = geometry(script, into, kind, others)
    except Refused as e:
        raise ValueError(f'split_edit {into}: {e}') from None
    m = round(want * fps)
    if m < MIN_FRAMES:
        raise ValueError(f'split_edit {into}: a {kind} of {want:g} s is {m} frame(s) at {fps:g} fps; '
                         f'the shortest is {MIN_FRAMES} frames ({MIN_FRAMES / fps:.3f} s)')
    word = 'J' if kind == 'lead' else 'L'
    rolled = None
    if move == 'picture':
        most = g['max_picture_frames']
        if m > most:
            raise ValueError(f'split_edit {into}: a {word} cut by moving the picture {want:g} s is more than there '
                             f'is: {g["why_picture"]} (most possible by moving the picture: {most / fps:.3f} s; by '
                             f'moving the sound: {g["max_frames"] / fps:.3f} s)')
        rolled = _roll(g, kind, m)
        g = geometry(script, into, kind, others)
    elif m > g['max_frames']:
        raise ValueError(f'split_edit {into}: a {kind} of {want:g} s is more than the source allows: {g["why_max"]} '
                         f'(most possible: {g["max_frames"] / fps:.3f} s; or move: picture, up to '
                         f'{g["max_picture_frames"] / fps:.3f} s)')
    k = max(1, min(round(fade * fps), m - 1))
    plan = _plan(g, kind, m, k)
    lost, lost_kind, brought, src_kind, edge = _words_report(plan, kind, fps)
    if lost and move != 'picture' and not op.get('drop_words'):
        if rolled:
            _unroll(rolled)
        who = plan['taker']
        what = (f'words "{_said(lost)}"' if lost_kind == 'words' else
                f'{sum(float(w["e"]) - float(w["s"]) for w in lost):.1f} s of voice (no transcript: letitedit_words '
                f'shows the words)')
        free = _longest_free(plan, kind, fps, lost)
        raise ValueError(f'split_edit {into}: the {word} cut would replace {who.get("id")}\'s {what} at '
                         f'{_clock(plan["covered"][1])}-{_clock(plan["covered"][2])} in its source with '
                         f'{plan["giver"].get("id")}\'s sound; a {kind} of up to {free:.3f} s keeps them, or trim '
                         f'{who.get("id")} first, or drop_words: true')
    for t, it, r in existing:
        t['items'] = [x for x in t['items'] if x is not it]
    home = existing[0][0] if existing and not op.get('track') else None
    name = op.get('track') or (home['name'] if home else TRACK)
    track = next((x for x in script['tracks'] if x['name'] == name), None)
    if track is None:
        track = {'name': name, 'kind': 'audio', 'items': []}
        script['tracks'].append(track)
    elif track.get('kind') != 'audio':
        raise ValueError(f'split_edit {into}: {name} is a picture track; the moved sound goes on an audio track')
    rec = {'into': g['B'].get('id'), 'out_of': g['A'].get('id'), kind: _r(m / fps), 'fade': _r(k / fps)}
    if op.get('drop_words'):
        rec['drop_words'] = True
    track['items'].append({'id': _bridge_id(g['B'].get('id'), kind), 'clip': plan['bridge_src'][0],
                           'in': _r(plan['bridge_src'][1]), 'out': _r(plan['bridge_src'][2]), 'split_edit': rec,
                           '_new': True})
    T = g['T'] / fps
    parts = []
    if kind == 'lead':
        parts.append(f"J cut into {_label(g['B'])}: its sound starts {m / fps:.3f} s ({m} frames) before its picture "
                     f"cut at {_clock(T)} (sound cut {_clock(plan['sound_cut'] / fps)}, from {_clock(plan['heard_src'][1])} in "
                     f"its file, on {name})")
    else:
        parts.append(f"L cut into {_label(g['B'])}: {_label(g['A'])}'s sound runs on {m / fps:.3f} s ({m} frames) under "
                     f"its picture from the cut at {_clock(T)} (sound cut {_clock(plan['sound_cut'] / fps)}, to "
                     f"{_clock(plan['bridge_src'][2])} in {g['A'].get('id')}'s file, on {name})")
    parts.append(f'crossfade {k / fps:.3f} s at the sound cut')
    if rolled:
        parts.append(f"the picture cut moved {'later' if kind == 'lead' else 'earlier'} by {m / fps:.3f} s to "
                     f"{_clock(T)} ({rolled['text']}); the sound cut stays at {_clock(plan['sound_cut'] / fps)}")
    else:
        parts.append(f'most possible here {g["max_frames"] / fps:.3f} s ({g["why_max"]})')
    if lost:
        parts.append(f'replaces {plan["taker"].get("id")}\'s "{_said(lost)}" (drop_words)')
    if brought and not rolled:
        parts.append(f'brings in "{_said(brought)}"' if src_kind == 'words' else
                     f'brings in {sum(float(w["e"]) - float(w["s"]) for w in brought):.1f} s of voice')
    if edge and not rolled:
        parts.append(edge)
    op['_result'] = '; '.join(parts)


def _longest_free(plan, kind, fps, lost):
    """The longest lead/lag that covers none of the lost words."""
    clip, a, b = plan['covered']
    if kind == 'lead':
        last = max(float(w['e']) for w in lost)
        return max(0.0, math.floor((b - last - 0.05) * fps) / fps)
    first = min(float(w['s']) for w in lost)
    return max(0.0, math.floor((first - a - 0.05) * fps) / fps)


def _roll(g, kind, m):
    """move: picture: the picture cut moves m frames (later for a J cut, earlier for an L cut); returns what to undo."""
    fps, A, B = g['fps'], g['A'], g['B']
    keys = ('in', 'out', 'len')
    old = {'A': {k: A.get(k) for k in keys}, 'B': {k: B.get(k) for k in keys}, 'items': (A, B)}
    d = m if kind == 'lead' else -m                  # frames the picture cut moves (later is +)
    a_in, a_n = item_frames(A, fps)
    if 'out' in A:                                   # A ends d frames later (a clip, or a colour with in/out)
        A['out'] = _r((a_in + a_n + d) / fps)
    else:                                            # a graphic or a made clip: its length
        A['len'] = _r((a_n + d) / fps)
    b_in, b_n = item_frames(B, fps)
    if 'in' in B:                                    # B starts d frames later in its own material
        B['in'] = _r((b_in + d) / fps)
    else:
        B['len'] = _r((b_n - d) / fps)
    old['text'] = (f"{A.get('id')} {'out ' + str(old['A'].get('out')) + ' -> ' + str(A.get('out')) if 'out' in A else 'len ' + str(old['A'].get('len')) + ' -> ' + str(A.get('len'))}, "
                   f"{B.get('id')} {'in ' + str(old['B'].get('in')) + ' -> ' + str(B.get('in')) if 'in' in B else 'len ' + str(old['B'].get('len')) + ' -> ' + str(B.get('len'))}")
    return old


def _unroll(old):
    A, B = old['items']
    for it, key in ((A, 'A'), (B, 'B')):
        for k, v in old[key].items():
            if v is None:
                it.pop(k, None)
            else:
                it[k] = v


# ------------------------------------------------------------------ rebuilding after every edit

def _rebuild_track(t, entries):
    """Rewrite a non-main track from [(item, start_s)]: gaps between, every item on its time."""
    from letitedit.timeline.edit_sync import item_len
    items, pos = [], 0.0
    for it, st in sorted(entries, key=lambda x: x[1]):
        if st > pos + 1e-4:
            items.append({'gap': round(st - pos, 4)})
        items.append(it)
        pos = max(pos, st + item_len(it))
    t['items'] = items


def _place(script, t, item, start_s):
    from letitedit.timeline.edit_sync import item_len, layout
    n = item_len(item)
    lay = layout(t)
    if any(s < start_s + n - 1e-4 and e > start_s + 1e-4 for _, s, e in lay):
        return False
    item['at'], item['pin'] = _clock(start_s), True
    _rebuild_track(t, [(it, s) for it, s, _ in lay] + [(item, start_s)])
    return True


def refresh(script):
    """Rebuild every split edit from its record after the timeline changed (idempotent; does nothing on a timeline
    without split edits). Returns notes about split edits that were shortened or removed."""
    from letitedit.timeline.edit_sync import layout
    found = records_of(script)
    has_mutes = any(is_mute(e) for t in script['tracks'] for it in t['items'] for e in (it.get('effects') or []))
    if not found and not has_mutes:
        return []
    # media offline (a drive not mounted): change nothing, rather than drop split edits whose files can't be read
    offline = sorted({it['clip'] for t in script['tracks'] for it in t['items'] if 'clip' in it
                      and (record(it) or any(is_mute(e) for e in (it.get('effects') or [])))
                      and not os.path.exists(it['clip'])})
    if offline:
        return [f"split edits left as they were (not rebuilt for this edit): {len(offline)} file(s) can't be found: "
                + ', '.join(offline[:3]) + (' ...' if len(offline) > 3 else '')]
    fps = _fps(script)
    notes = []
    old_bridges = {}
    homes = {}
    for t in {id(t): t for t, _, _ in found}.values():
        lay = layout(t)
        for it, s, e in lay:
            if record(it):
                old_bridges[id(it)] = json.dumps({k: it.get(k) for k in ('clip', 'in', 'out', 'effects', 'at',
                                                                          'split_edit')}, sort_keys=True, default=str)
                homes[id(it)] = t
        _rebuild_track(t, [(it, s) for it, s, _ in lay if not record(it)])
    old_mutes = {}
    for t in script['tracks']:
        for it in t['items']:
            effs = it.get('effects')
            if effs and any(is_mute(e) for e in effs):
                old_mutes[it.get('id')] = [e for e in effs if is_mute(e)]
                kept = [e for e in effs if not is_mute(e)]
                if kept:
                    it['effects'] = kept
                else:
                    it.pop('effects', None)
    done = []
    order = []
    for t, it, r in found:
        tt, lay, i = _find_cut(script, r['into'])
        order.append(((lay[i][1] if lay else 10 ** 12), t, it, r))
    order.sort(key=lambda x: x[0])
    new_mutes = {}
    for _, t_home, br, r in order:
        r = dict(r)
        kind = 'lead' if 'lead' in r else 'lag'
        word = KINDS[kind]
        try:
            g = geometry(script, r['into'], kind, done)
        except Refused as e:
            notes.append(f"{word} cut into {r['into']} removed: {e}")
            continue
        if r.get('out_of') and g['A'].get('id') != r['out_of'] and g['A'].get('from') != r['out_of']:
            notes.append(f"{word} cut into {r['into']} removed: the clip before it is now {g['A'].get('id')} "
                         f"(was {r['out_of']}); make it again with split_edit if wanted")
            continue
        m = round(_sec(r[kind]) * fps)
        if m > g['max_frames']:
            if g['max_frames'] < MIN_FRAMES:
                notes.append(f"{word} cut into {r['into']} removed: no room left ({g['why_max']})")
                continue
            notes.append(f"{word} cut into {r['into']} shortened from {m / fps:.3f} to {g['max_frames'] / fps:.3f} s: "
                         f"{g['why_max']}")
            m = g['max_frames']
        k = max(1, min(round(_sec(r.get('fade', FADE_S)) * fps), m - 1))
        plan = _plan(g, kind, m, k)
        into = g['B'].get('id')
        rec = {'into': into, 'out_of': g['A'].get('id'), kind: _r(m / fps), 'fade': _r(k / fps)}
        if r.get('drop_words'):
            rec['drop_words'] = True
        giver = plan['giver']
        bridge = {'id': _bridge_id(into, kind), 'name': f"{word} cut sound: {os.path.basename(giver['clip'])}",
                  'clip': plan['bridge_src'][0], 'in': _r(plan['bridge_src'][1]), 'out': _r(plan['bridge_src'][2]),
                  'effects': _audio_effects(giver) + [{'gain': {'keys': _bridge_keys(kind, m, k, fps)}}],
                  'split_edit': rec}
        t = homes.get(id(br), t_home)
        start = plan['bridge_at'] / fps
        if not _place(script, t, bridge, start):
            alt = _overflow(script, t, bridge, start)
            notes.append(f"{word} cut into {into}: {t['name']} is busy at {_clock(start)}; its sound went on {alt['name']}")
        taker = plan['taker']
        if plan['covered'] is not None:
            side = 'tail' if kind == 'lead' else 'head'
            eff = {'split_mute': {side: _r(m / fps), 'fade': _r(k / fps)}}
            taker['effects'] = list(taker.get('effects') or []) + [eff]
            new_mutes.setdefault(taker.get('id'), []).append(eff)
        if kind == 'lead':
            _drop_fade(giver, 'fade_in_audio', notes, f'{into}: its audio fade-in removed (its sound now comes in '
                                                       'before the cut)')
        else:
            _drop_fade(giver, 'fade_out_audio', notes, f"{giver.get('id')}: its audio fade-out removed (its sound "
                                                        'now runs on after the cut)')
        new = json.dumps({k: bridge.get(k) for k in ('clip', 'in', 'out', 'effects', 'at', 'split_edit')},
                         sort_keys=True, default=str)
        if old_bridges.get(id(br)) != new and not br.get('_new'):
            if (r.get('into') != into):
                notes.append(f"{word} cut into {r['into']} now goes into {into} (the clip was replaced by its pieces)")
            lost, lost_kind, _, _, _ = _words_report(plan, kind, fps)
            if lost and not rec.get('drop_words'):
                notes.append(f"{word} cut into {into} now covers {taker.get('id')}'s "
                             + (f'"{_said(lost)}"' if lost_kind == 'words' else 'voice') +
                             f': shorten it (split_edit {into} {kind}: ...) or trim {taker.get("id")}')
        done.append(rec)
    return notes


def _overflow(script, t, item, start):
    """The next audio track named like t ('J/L cuts 2', ...) that is free then, added at the end if needed."""
    import re
    root = re.sub(r'\s+\d+$', '', t['name'])
    k = 2
    while True:
        name = f'{root} {k}'
        cand = next((x for x in script['tracks'] if x['name'] == name), None)
        if cand is None:
            cand = {'name': name, 'kind': 'audio', 'items': []}
            script['tracks'].append(cand)
        if cand.get('kind') == 'audio' and _place(script, cand, item, start):
            return cand
        k += 1


def _drop_fade(it, key, notes, text):
    effs = it.get('effects') or []
    if any(isinstance(e, dict) and key in e for e in effs):
        it['effects'] = [e for e in effs if not (isinstance(e, dict) and key in e)]
        if not it['effects']:
            it.pop('effects', None)
        notes.append(text)


# ------------------------------------------------------------------ what a timeline's split edits are

def listing(script):
    """[{kind, into, out_of, seconds, fade, track, sound_cut_s, picture_cut_s}] for every split edit (reads only)."""
    fps = _fps(script)
    out = []
    for t, it, r in records_of(script):
        kind = 'lead' if 'lead' in r else 'lag'
        tt, lay, i = _find_cut(script, r['into'])
        cut = lay[i][1] / fps if lay else None
        sec = _sec(r[kind])
        out.append({'kind': KINDS[kind], 'into': r['into'], 'out_of': r.get('out_of'), 'seconds': sec,
                    'fade': r.get('fade'), 'track': t['name'], 'picture_cut_s': cut,
                    'sound_cut_s': None if cut is None else round(cut - sec if kind == 'lead' else cut + sec, 4)})
    return out
