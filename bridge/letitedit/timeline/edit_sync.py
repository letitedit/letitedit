"""Word-level tightening and keeping other tracks/captions in sync with the main picture track.

tighten(script, op): replace one clip by its spoken parts (pauses over max_pause cut; long silent work optionally
                     kept as a muted fast-forward).
resync(before, after): after the main picture track changed, move overlays/music/SFX and captions so each stays
                     with the picture (source moment) it belonged to.
"""
from __future__ import annotations

import copy
import os
import re

from letitedit.timeline.edit_script import _find, clock, to_seconds

AUDIO_EFFECTS = ('gain', 'fade_in_audio', 'fade_out_audio')


def tighten(script, op):
    import letitedit.footage.speech as speech
    t, i, it = _find(script, op['id'])
    if 'clip' not in it:
        raise ValueError(f'{op["id"]} is not a clip')
    a, b = to_seconds(it['in']), to_seconds(it['out'])
    if abs(float(it.get('speed', 1.0)) - 1) > 1e-6:
        raise ValueError(f'{op["id"]} is already sped up; tighten works on normal-speed clips')
    ws = speech.words(it['clip'], a, b)
    spans = speech.islands(ws, op.get('max_pause', 0.75), op.get('pad_in', 0.12), op.get('pad_out', 0.3), a, b)
    spans = _split_at_silences(it['clip'], spans, op.get('max_pause', 0.75), op.get('pad_in', 0.12),
                               op.get('pad_out', 0.3), ws)
    from letitedit.timeline.edit_script import _guard_spoken_edges
    clean_spans, edge_notes = [], []
    for start, end in spans:
        edge = {'in': start, 'out': end}
        edge_notes.extend(_guard_spoken_edges(it, edge) or [])
        if edge['in'] < a or edge['out'] > b:
            edge_notes.append('Natural word edge limited by the original clip bounds')
        clean_spans.append((max(a, edge['in']), min(b, edge['out'])))
    spans = clean_spans
    op['_result'] = {'words': len(ws), 'spoken_parts': len(spans)}
    if edge_notes:
        op['_result']['word_edges'] = edge_notes
    if not spans:
        return
    over = op.get('speed_up_over')
    base = {k: v for k, v in it.items() if k not in ('id', 'at', 'len', 'in', 'out', 'effects', 'speed')}
    effects = it.get('effects', [])
    new, k = [], 0

    def piece(sa, sb, speed=1.0, first=False, last=False):
        nonlocal k
        k += 1
        eff = []
        for e in effects:
            key = e if isinstance(e, str) else next(iter(e))
            if key in ('fade_in', 'fade_in_audio') and not first:
                continue
            if key in ('fade_out', 'fade_out_audio') and not last:
                continue
            if key == 'text' and not first:
                continue
            if speed != 1.0 and (key in AUDIO_EFFECTS or key == 'mute'):
                continue
            eff.append(e)
        if speed != 1.0:
            eff.append('mute')
        item = {**base, 'id': f'{it["id"]}.{k}', 'from': it['id'], 'in': round(sa, 4), 'out': round(sb, 4)}
        if speed != 1.0:
            item['speed'] = speed
        if eff:
            item['effects'] = eff
        new.append(item)

    prev = None
    for n, (sa, sb) in enumerate(spans):
        if prev is not None and over and sa - prev >= over:
            piece(prev, sa, float(op.get('speed_up') or max(4, round((sa - prev) / 3))))
        piece(sa, sb, first=(n == 0), last=(n == len(spans) - 1))
        prev = sb
    t['items'][i:i + 1] = new
    kept = sum((x['out'] - x['in']) / float(x.get('speed', 1)) for x in new)
    op['_result'].update(pieces=len(new), seconds_before=round(b - a, 2), seconds_after=round(kept, 2))


def _split_at_silences(clip, spans, max_pause, pad_in, pad_out, words=()):
    """Word times from speech recognition often run across the pauses after words; voice detection sees them. Split
    each spoken stretch where no voice is heard for max_pause or longer - but never where that would drop a word
    the transcript places in the gap (voice detection misses quiet or long-drawn words like "motor" or "drain")."""
    try:
        import letitedit.sound.music as music
        voice = music.voice_times(clip)
    except Exception:  # noqa: BLE001 - no voice detection: the word islands as they are
        return spans
    out = []
    for sa, sb in spans:
        inside = [(max(sa, x), min(sb, y)) for x, y in voice if y > sa and x < sb]
        if not inside:
            out.append((sa, sb))
            continue
        cur = sa
        for (x0, y0), (x1, y1) in zip(inside, inside[1:]):
            cut_a, cut_b = y0 + pad_out, x1 - pad_in
            if x1 - y0 >= max_pause and not any(w['s'] < cut_b and w['e'] > cut_a for w in words):
                out.append((cur, min(sb, cut_a)))
                cur = max(sa, cut_b)
        out.append((cur, sb))
    return [(round(x, 4), round(y, 4)) for x, y in out if y - x > 0.05]


def item_len(it, fps=None):
    if 'raw' in it or 'graphic' in it or 'scene' in it or it.get('adjust') or ('color' in it and 'out' not in it):
        seconds = to_seconds(it.get('len', 0))
        return round(seconds * fps) / fps if fps else seconds
    import letitedit.timeline.made as made
    if 'ffmpeg' in it or 'freeze' in it or 'vfx' in it or 'voice' in it or 'ass' in it or made._generated_module(it):
        seconds = made.default_len(it)
        return round(seconds * fps) / fps if fps else seconds
    if 'out' not in it and 'clip' in it:
        from letitedit.timeline.edit_script import fill_out
        fill_out(it)
    speed = float(it.get('speed', 1.0))
    if fps:
        return (round(to_seconds(it['out']) * fps / speed) - round(to_seconds(it['in']) * fps / speed)) / fps
    return (to_seconds(it['out']) - to_seconds(it['in'])) / speed


def transition_len(it):
    tr = it.get('transition')
    if tr is None or tr is False:
        return 0.0
    return to_seconds(tr['len'] if isinstance(tr, dict) else tr)


def layout(track, fps=None):
    """[(item, start_s, end_s)] for the clips of a track, from order and gaps. A clip with a transition in starts
    that much before the previous clip ends (they overlap)."""
    units = fps or 1.0
    quantize = round if fps else float
    pos, out, prev_clip = 0, [], False
    for it in track['items']:
        if 'gap' in it:
            pos += quantize(to_seconds(it['gap']) * units)
            prev_clip = False
            continue
        if 'omitted' in it:
            continue
        if prev_clip:
            pos -= quantize(transition_len(it) * units)
        if it.get('pin') and it.get('at') is not None:     # placed at a time (at:): the compiler puts it there
            pos = max(pos, quantize(to_seconds(it['at']) * units))
        n = quantize(item_len(it, fps) * units)
        out.append((it, pos / units, (pos + n) / units))
        pos += n
        prev_clip = 'raw' not in it
    return out


def main_track(script):
    return next((t for t in script['tracks'] if t.get('kind', 'video') == 'video'), None)


def mapper(before, after):
    """Map a time on the old timeline to the new one through the main picture track's source times."""
    old_t, new_t = main_track(before), main_track(after)
    if old_t is None or new_t is None:
        return None
    fps = float((after.get('profile') or {}).get('fps') or 30)
    old, new = layout(old_t, fps), layout(new_t, fps)
    by_clip, by_id = {}, {}
    for it, s, e in new:
        by_id.setdefault(it.get('id'), (it, s, e))
        if 'clip' in it:
            by_clip.setdefault(it['clip'], []).append((it, s, e))

    def own(cand, old_it):
        return old_it.get('id') is not None and old_it.get('id') in (cand.get('id'), cand.get('from'))

    def find(old_it, src, end, T):
        hits = []
        for cand, cs, ce in by_clip.get(old_it['clip'], []):
            ca, cb = to_seconds(cand['in']), to_seconds(cand['out'])
            mine = own(cand, old_it)
            if (ca - 1e-3 <= src < cb) or ((end or mine) and ca < src <= cb + 1e-3):
                hits.append((not mine, abs(cs - T), cs + (src - ca) / float(cand.get('speed', 1.0))))
        return min(hits)[2] if hits else None

    def next_survivor(old_it, src, T):
        best = None
        for cand, cs, ce in by_clip.get(old_it['clip'], []):
            ca = to_seconds(cand['in'])
            if ca >= src - 1e-3:
                key = (not own(cand, old_it), abs(cs - T), ca)
                if best is None or key < best[0]:
                    best = (key, cs)
        return best[1] if best else None

    def map_t(T, end=False, nearest=False):
        for it, s, e in old:
            # a time on a cut belongs to the clip that starts there (rounding can leave it a hair inside the one before)
            if s - 1e-6 <= T < e - 1e-6 or (end and s < T <= e + 1e-6):
                if 'clip' not in it:
                    hit = by_id.get(it.get('id'))
                    return hit[1] + (T - s) if hit else None
                src = to_seconds(it['in']) + (T - s) * float(it.get('speed', 1.0))
                got = find(it, src, end, T)
                if got is None and nearest:
                    got = next_survivor(it, src, T)
                return got
        prev = [x for x in old if x[2] <= T + 1e-6]
        if not prev:
            return T
        it, s, e = prev[-1]
        mapped = map_t(e, end=True, nearest=nearest) if e > s else None
        return None if mapped is None else mapped + (T - e)
    return map_t


def _same_file(a, b):
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def _follow_cutouts(before, after, pinned):
    """A cut-out piece on another track showing the same moments as the main picture under it (what `behind_person`
    places) stays with those moments: a trim, cut or split of the picture trims, cuts or splits the piece, through `skip`
    and `len`, the part of its movie that plays. Its recipe doesn't change, so nothing is drawn again and the same frames
    play. Only the frames a piece already has can play: a clip made longer than its piece gets a note saying so. A piece
    showing other moments than the picture under it, or with a speed, is left to resync as before. Returns notes."""
    main_a, main_b = main_track(after), main_track(before)
    fps = float((after.get('profile') or {}).get('fps') or 30)
    frame = 1.0 / fps
    old_main = list(layout(main_b, fps))
    new_main = list(layout(main_a, fps))
    old_tracks = {t['name']: t for t in before['tracks']}
    old_ids = {c.get('id') for c, _, _ in old_main}

    def parts_of(c):
        """What's left of an old clip on the new picture: what carries its id or `from`, and a new clip right beside those showing the same file inside
        the clip's own moments (a cut in the middle of a clip, made as a trim and an insert: no op splits a clip)."""
        c_in, c_out = to_seconds(c['in']), to_seconds(c['out'])

        def beside(n):
            return 'clip' in n and n.get('id') not in old_ids and not n.get('from') and _same_file(n['clip'], c['clip']) \
                and to_seconds(n['in']) >= c_in - 1.5 * frame and to_seconds(n['out']) <= c_out + 1.5 * frame
        keep = set()
        for k, (n, _, _) in enumerate(new_main):
            if c['id'] in (n.get('id'), n.get('from')):
                keep.add(k)
                for step in (1, -1):
                    j = k + step
                    while 0 <= j < len(new_main) and beside(new_main[j][0]):
                        keep.add(j)
                        j += step
        return [new_main[k] for k in sorted(keep)]

    notes = []
    for t in after['tracks']:
        if t is main_a or t['name'] not in old_tracks:
            continue
        was = {it.get('id'): (s, e) for it, s, e in layout(old_tracks[t['name']]) if it.get('id')}
        out, touched = [], False
        for it in t['items']:
            vfx = it.get('vfx') if isinstance(it.get('vfx'), dict) else None
            src = (vfx or {}).get('source') or {}
            if not vfx or vfx.get('effect') != 'cutout' or it.get('id') not in was or it.get('id') in pinned \
                    or float(src.get('speed') or 1.0) != 1.0 or not src.get('clip'):
                out.append(it)
                continue
            start, end = was[it['id']]
            first = to_seconds(src['in']) + to_seconds(it.get('skip') or 0)     # the source moment at its start
            under = [(c, s, e) for c, s, e in old_main if min(end, e) - max(start, s) > 1.5 * frame]
            locked = bool(under)
            for c, s, e in under:
                if 'clip' not in c or not c.get('id') or float(c.get('speed') or 1.0) != 1.0 \
                        or not _same_file(c['clip'], src['clip']) \
                        or abs((first + (max(start, s) - start)) - (to_seconds(c['in']) + (max(start, s) - s))) > 1.5 * frame:
                    locked = False
            if not locked:
                out.append(it)
                continue
            pieces, short = [], []
            for c, s, e in under:
                c_in, c_out = to_seconds(c['in']), to_seconds(c['out'])
                a = max(first + (max(start, s) - start), c_in)      # what of this clip the piece shows, in source time
                b = min(first + (min(end, e) - start), c_out)
                for new, ns, ne in parts_of(c):
                    if 'clip' not in new or float(new.get('speed') or 1.0) != 1.0:
                        continue
                    n_in, n_out = to_seconds(new['in']), to_seconds(new['out'])
                    x, y = max(a, n_in), min(b, n_out)
                    if y - x >= frame * 0.9:
                        pieces.append((ns + (x - n_in), x, y))
                    # the clip grew past what the piece has frames for, where the piece reached the clip's old end
                    if n_in < c_in - 1.5 * frame and a <= c_in + 1.5 * frame:
                        short.append((ns, ns + (min(c_in, n_out) - n_in), n_in, min(c_in, n_out)))
                    if n_out > c_out + 1.5 * frame and b >= c_out - 1.5 * frame:
                        lo = max(c_out, n_in)
                        short.append((ns + (lo - n_in), ne, lo, n_out))
            base_in = to_seconds(src['in'])
            pieces.sort()
            touched = True
            if len(pieces) == 1 and not short and abs(pieces[0][1] - first) < frame / 2 \
                    and abs((pieces[0][2] - pieces[0][1]) - (end - start)) < frame / 2:
                it['_follow_at'] = pieces[0][0]      # the same part of its movie: it only moves
                out.append(it)
                continue
            if not pieces:
                notes.append(f'{it["id"]} on {t["name"]}: the picture it shows was cut, so this cut-out went with it')
            for k, (at, x, y) in enumerate(pieces):
                piece = copy.deepcopy(it)
                if k:
                    piece['id'], piece['from'] = f'{it["id"]}.{k + 1}', it['id']
                skip = round((x - base_in) * fps) / fps
                piece.pop('skip', None)
                if skip > frame / 2:
                    piece['skip'] = round(skip, 4)
                piece['len'] = round(round((y - x) * fps) / fps, 4)
                piece['_follow_at'] = at
                out.append(piece)
            if pieces:
                notes.append(f'{it["id"]} on {t["name"]}: its cut-out follows the picture, playing the part it already has')
            for a0, b0, x0, y0 in short:
                notes.append(
                    f'{it["id"]} on {t["name"]}: the clip now runs longer than its cut-out, so from {a0:.2f} to {b0:.2f} s the '
                    f'person has no cut-out in front of what is behind them. To fill it: insert {{vfx: {{effect: cutout, source: '
                    f'{{clip, in: {x0:.3f}, out: {y0:.3f}}}}}}} at {a0:.3f} on that track (it draws, under the PC lock).')
        if touched:
            t['items'] = out
    return notes


def _word_caption(it):
    g = it.get('graphic')
    return isinstance(g, dict) and g.get('template') == 'word_captions' and bool((g.get('params') or {}).get('words'))


def _plain_word(text):
    return re.sub(r"[^\w']+", '', str(text)).lower()


def _heard_times(heard, words, start, end):
    """A caption over a stretched word has that word's wrong times. When the stretch has been heard by itself (word_reheard), and the caption's
    words are all there, in order, the last time they're said: their times on the old timeline. Otherwise None."""
    if not any(h.get('reheard') and h['t0'] < end and h['t1'] > start for h in heard):
        return None             # not over a heard stretch: its own times
    near = [h for h in heard if start - 1.0 <= h['t0'] < end + 1.0]
    j, out = len(near) - 1, []
    for w in reversed(words):
        want = _plain_word(w[0])
        while j >= 0 and _plain_word(near[j]['w']) != want:
            j -= 1
        if j < 0:
            return None
        out.append((near[j]['t0'], near[j]['t1']))
        j -= 1
    return out[::-1]


def _follow_word_captions(before, after, map_t, pinned):
    """A word-by-word caption keeps the words whose sound survives a change of the picture, each at its new time: a cut before it only moves it, a cut
    inside it takes those words out and closes up, a cut over all its words takes it away, and it ends with the picture. Its other settings stay. A
    caption whose words clips were moved between becomes one caption per part. One placed at a time is left to resync. Returns notes."""
    main_a, old_tracks = main_track(after), {t['name']: t for t in before['tracks']}
    tracks = [t for t in after['tracks'] if t is not main_a and t['name'] in old_tracks and any(_word_caption(i) for i in t['items'])]
    if not tracks:
        return []
    lay = layout(main_a, float((after.get('profile') or {}).get('fps') or 30))
    total = lay[-1][2] if lay else 0
    frame = 1.0 / float((after.get('profile') or {}).get('fps') or 30)
    heard = None
    notes, shortened, removed = [], 0, 0
    for t in tracks:
        was = {i.get('id'): (s, e) for i, s, e in layout(old_tracks[t['name']]) if i.get('id')}
        out = []
        for it in t['items']:
            if not _word_caption(it) or it.get('id') not in was or it.get('id') in pinned:
                out.append(it)
                continue
            start, end = was[it['id']]
            params = it['graphic']['params']
            words = params['words']
            if heard is None:
                try:
                    from letitedit.timeline.timeline_speech import timeline_words
                    heard = timeline_words(before, cached_only=True, heard=True)
                except Exception:  # noqa: BLE001 - no words known: the caption's own times
                    heard = []
            own = [(start + float(w[1]), start + float(w[2])) for w in words]
            # the heard times only when this change takes words from this caption: nothing else here is a reason to touch it
            better = _heard_times(heard, words, start, end) if any(map_t((x + y) / 2) is None for x, y in own) else None
            times = better or own
            groups, kept = [], []
            for w, (a, b) in zip(words, times):
                mid = (a + b) / 2
                m = map_t(mid)
                if m is None:
                    continue                # this word's sound was cut
                # a word never gets longer: an edge that lands further from its middle than it was has been parted from it (a hair across a clip's edge)
                seg = next(((x, y) for _, x, y in lay if x - 1e-6 <= m < y), (m - (mid - a), m + (b - mid)))
                na = map_t(a)
                if na is None:
                    na = map_t(a, nearest=True)
                if na is None or na > m or m - na > (mid - a) + frame:
                    na = max(m - (mid - a), seg[0])
                nb = map_t(b, end=True)
                if nb is None or nb < m or nb - m > (b - mid) + frame:
                    nb = min(m + (b - mid), seg[1])
                if m >= total - 1e-6:
                    continue                # past the end of the picture
                if kept and (na < kept[-1][1] - 2 * frame or na > kept[-1][2] + 1.0):
                    groups.append(kept)     # clips moved between these words: they're apart now, so each part is a caption
                    kept = []
                kept.append((w[0], max(0.0, na), min(nb, total)))
            if kept:
                groups.append(kept)
            if not groups:
                removed += 1
                continue
            if len(groups) == 1:
                kept = groups[0]
                # its edges follow its words: a start or end the change has parted from them doesn't count (clips moved, a cut at its edge)
                whole = not better and len(kept) == len(words)
                first, last = kept[0][1], kept[-1][2]
                if whole:
                    first = max(0.0, kept[0][1] - float(words[0][1]))
                    # its own end, even when its last word runs a little past it, as saved captions' do: nothing here changed that,
                    # unless that moment was cut: then it ends with its last word
                    if map_t(end, end=True) is not None:
                        last = min(kept[-1][2] + ((end - start) - float(words[-1][2])), total)
                same = not better and len(kept) == len(words) and abs((last - first) - (end - start)) < frame / 2 and all(
                    abs((x - first) - float(w[1])) < frame / 2 and abs((y - first) - float(w[2])) < frame / 2 for (_, x, y), w in zip(kept, words))
                if same:
                    it['_follow_at'] = first    # all its words, the same times: its picture stays; it only moves
                    out.append(it)
                    continue
            for k, part in enumerate(groups):
                first = part[0][1] if len(groups) > 1 else first
                last = part[-1][2] if len(groups) > 1 else last
                new = copy.deepcopy(it)
                if k:
                    new['id'], new['from'] = f"{it['id']}.{k + 1}", it['id']
                new['graphic']['params']['words'] = [[x, round(a - first, 4), round(b - first, 4)] for x, a, b in part]
                new['len'] = round(last - first, 4)
                new['_follow_at'] = first
                out.append(new)
            shortened += 1
        # a caption that now runs into the next would push it late: it ends where the next begins
        placed = sorted((i for i in out if _word_caption(i) and '_follow_at' in i), key=lambda i: i['_follow_at'])
        for i, nxt in zip(placed, placed[1:]):
            room = nxt['_follow_at'] - i['_follow_at']
            if frame <= room < to_seconds(i.get('len', 0)) - frame / 2:
                i['len'] = round(room, 4)
        t['items'] = out
    if shortened:
        notes.append(f'{shortened} word-by-word caption(s) changed: the words whose sound was cut are gone, the rest keep their sound')
    if removed:
        notes.append(f'{removed} word-by-word caption(s) removed with the speech they belonged to')
    return notes


def _follow_scene_ends(before, after, map_t, pinned):
    """A cut under a scene shortens the scene by what was cut, so it ends with the same moment of the picture as it did, and with the cut-out that
    follows that picture (T96: otherwise the scene shows with nobody in front of it for as long as the cut). Only ever shorter. Returns notes."""
    main, old_tracks = main_track(after), {t['name']: t for t in before['tracks']}
    frame = 1.0 / float((after.get('profile') or {}).get('fps') or 30)
    notes = []
    for t in after['tracks']:
        if t is main or t['name'] not in old_tracks:
            continue
        was = {i.get('id'): (s, e) for i, s, e in layout(old_tracks[t['name']]) if i.get('scene') and i.get('id')}
        for it in t['items']:
            if it.get('id') not in was or it.get('id') in pinned or not it.get('scene'):
                continue
            s, e = was[it['id']]
            a, b = map_t(s, nearest=True), map_t(e, end=True, nearest=True)
            if a is not None and b is not None and a < b < a + to_seconds(it.get('len', 0)) - 1e-3:
                was_len = to_seconds(it.get('len', 0))
                it['len'] = round(b - a, 4)
                if was_len - (b - a) >= frame / 2:
                    notes.append(f'{it.get("id")} on {t["name"]} (a scene) shortened from {was_len:.2f} to {b - a:.2f} s, to end with the same moment of the picture')
    return notes


def _scene_timing_note(before, after, map_t):
    """A scene is one drawing with its own clock: when the picture is cut inside it, what follows the cut no longer meets
    the same words. That is a fact the AI can act on, so it goes in the reply."""
    fps = float((after.get('profile') or {}).get('fps') or 30)
    main = main_track(before)
    notes = []
    for t in before['tracks']:
        if t is main:
            continue
        for it, s, e in layout(t):
            if not it.get('scene'):
                continue
            a, b = map_t(s, nearest=True), map_t(e, end=True, nearest=True)
            if a is None or b is None:
                continue
            drift = (e - s) - (b - a)
            if abs(drift) >= 1.5 / fps:
                notes.append(f'{it.get("id")} on {t["name"]}: a scene keeps its own timing, so after the cut it runs '
                             f'{abs(drift):.2f} s {"late" if drift > 0 else "early"} against the speech; '
                             "revising the scene moves anything that lands on a word")
    return notes


def resync(before, after, touched=(), pinned=()):
    """Move items on the other tracks with their picture after the main track changed. Each item keeps the place it
    has after this change's edits (gaps edited by the same change included), mapped onto the new picture timing; items
    placed with at: (pinned) keep exactly that time. `touched` is accepted for older callers."""
    map_t = mapper(before, after)
    if map_t is None:
        return []
    notes = []
    main_new = main_track(after)
    fps = float((after.get('profile') or {}).get('fps') or 30)
    lay = layout(main_new, fps)
    total = lay[-1][2] if lay else 0
    old_tracks = {t['name']: t for t in before['tracks']}
    moved = 0
    notes += _follow_cutouts(before, after, pinned)
    notes += _scene_timing_note(before, after, map_t)
    notes += _follow_word_captions(before, after, map_t, pinned)
    notes += _follow_scene_ends(before, after, map_t, pinned)
    for t in after['tracks']:
        if t is main_new or t['name'] not in old_tracks:
            continue
        old_pos = {it.get('id'): s for it, s, e in layout(old_tracks[t['name']])}
        placed = []
        reorder = False
        for it, edited, ends in layout(t):
            if '_follow_at' in it:           # a cut-out or caption that follows its picture: it knows where it goes
                placed.append((it, it.pop('_follow_at')))
                reorder = True
                continue
            if it.get('id') in pinned:
                placed.append((it, edited))
                continue
            nt = map_t(edited, nearest=True)
            if it.get('adjust'):             # an adjustment layer stays on its picture, and goes if all of that is cut
                nb = map_t(ends, end=True, nearest=True)
                fps = float((after.get('profile') or {}).get('fps') or 30)
                if nt is None or nb is None or nb - nt < 1.5 / fps:
                    notes.append(f'{it.get("id")}: its picture ({edited:.2f}-{ends:.2f} s) was cut, so the adjustment layer was removed')
                    continue
                if abs((nb - nt) - item_len(it)) > 1e-3:
                    it['len'] = round(nb - nt, 4)
                    notes.append(f'{it.get("id")}: the adjustment layer now runs {nt:.2f}-{nb:.2f} s, with its picture')
            if nt is not None and abs(nt - old_pos.get(it.get('id'), edited)) > 1e-3:
                moved += 1
            placed.append((it, nt))
        if reorder:                          # clips moved: what follows them lands in their new order, or each pushes the next along
            placed.sort(key=lambda x: float('inf') if x[1] is None else x[1])
        items, pos = [], 0.0
        for it, nt in placed:
            if nt is None:
                nt = pos
            nt = round(nt * fps) / fps
            if nt > pos + 1e-4:
                items.append({'gap': round(nt - pos, 4)})
                pos = nt
            n = item_len(it, fps)
            if pos + n > total + 1e-3 and 'clip' in it and pos < total:
                cut = (pos + n - total) * float(it.get('speed', 1.0))
                it['out'] = round(to_seconds(it['out']) - cut, 4)
                notes.append(f'{it.get("id")} on {t["name"]} shortened to end with the picture')
                n = item_len(it, fps)
            if pos + n > total + 1e-3 and it.get('scene') and pos < total:     # or the video would end on the scene alone
                it['len'] = round(total - pos, 4)
                notes.append(f'{it.get("id")} on {t["name"]} (a scene) shortened to end with the picture')
                n = item_len(it, fps)
            if not it.get('transition') and 'raw' not in it:
                it['at'], it['pin'] = clock(pos), True    # lands on exactly that frame, whatever the rounding before it
            items.append(it)
            pos += n
        t['items'] = items
    if moved:
        notes.append(f'{moved} item(s) on other tracks moved to stay with their picture')
    for cap in after.get('captions', []):
        kept = []
        for q in cap['cues']:
            a = map_t(to_seconds(q['start']))
            b = map_t(to_seconds(q['end']), end=True)
            if a is None:
                # its start was cut: what's left of it stays, from where the picture goes on; a cue with nothing left goes
                a = map_t(to_seconds(q['start']), nearest=True) if b is not None else None
                if a is None or a >= b:
                    continue
            if b is None or b <= a:
                seg = next(((s, e) for it, s, e in lay if s - 1e-6 <= a < e), None)
                b = seg[1] if seg else a + 0.5
            kept.append({'start': clock(a), 'end': clock(b), 'text': q['text']})
        dropped = len(cap['cues']) - len(kept)
        if dropped:
            notes.append(f'{dropped} caption(s) on "{cap["track"]}" removed with the speech they belonged to')
        cap['cues'] = kept
    import letitedit.timeline.aim as aim
    return notes + aim.follow(after, map_t)
