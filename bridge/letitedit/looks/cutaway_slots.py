"""Where the cutaways go: slots planned from the Look's own numbers and the words said.

    plan(script, look=None)  -> {'numbers', 'slots': [{n, at, len, line, filled_by}], 'filled', 'open', 'findings'}

The Look (visual.json) measures how many cutaways a minute its reference has, how long they last, how much of the time
they cover and the longest stretch of the speaker alone. From those and the timeline's length, this lays out the
slots: lengths around the measured median inside its shortest and longest, the speaker's stretches between them, each
slot starting where a spoken phrase starts or ends, with the words said there. A slot is filled when a cutaway on a
b-roll track covers it. Nothing here places a shot or blocks an export: the Look check reports the open slots and the
shortfall.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path

PATTERN = (1.0, 0.7, 1.25, 0.85, 1.15, 0.75, 1.05, 0.9)   # lengths vary around the median, as the reference's do
FIRST_TALK_S = 1.4
LAST_TALK_S = 0.8
SNAP_S = 0.4
TOLERANCE = 0.85          # fewer than this share of the planned slots filled is a shortfall


def look_numbers(look):
    """The Look's cutaway numbers from its visual.json: {per_minute, median_s, min_s, max_s, share, longest_talking_head_s}
    (medians over its references), or None when it carries none."""
    import letitedit.looks.looks as looks
    card = looks.read(look)
    visual = Path(card['recipe']).with_name('visual.json')
    if not visual.is_file():
        return None
    data = json.loads(visual.read_text(encoding='utf-8-sig'))
    rhythm, shares = [], []
    for ref in data.get('references', []):
        sem = ref.get('semantic') or {}
        if sem.get('broll_rhythm'):
            rhythm.append(sem['broll_rhythm'])
        seconds, length = sem.get('broll_seconds'), ref.get('duration_s')
        if sem.get('broll_share') is not None:
            shares.append(float(sem['broll_share']))
        elif seconds and length:
            shares.append(float(seconds) / float(length))
    if not rhythm:
        return None

    def med(key):
        values = [r[key] for r in rhythm if r.get(key) is not None]
        return statistics.median(values) if values else None

    return {'per_minute': med('per_minute'), 'median_s': med('median_s'), 'min_s': med('min_s'), 'max_s': med('max_s'),
            'longest_talking_head_s': med('longest_talking_head_s'),
            'share': statistics.median(shares) if shares else None}


def _lengths(count, total, lo, hi):
    raw = [PATTERN[i % len(PATTERN)] for i in range(count)]
    scale = total / sum(raw)
    out = [min(hi, max(lo, r * scale)) for r in raw]
    for _ in range(3):                      # give what the limits took back to the shots that can take it
        spare = total - sum(out)
        free = [i for i, v in enumerate(out) if (spare > 0 and v < hi - 1e-6) or (spare < 0 and v > lo + 1e-6)]
        if abs(spare) < 0.02 or not free:
            break
        for i in free:
            out[i] = min(hi, max(lo, out[i] + spare / len(free)))
    return out


def _boundaries(words):
    """Times a phrase can start or end at: after each word, with the pause that follows it (longer pauses first)."""
    marks = []
    for a, b in zip(words, words[1:]):
        marks.append((round(a['t1'], 3), max(0.0, b['t0'] - a['t1'])))
    return marks


def _snap(target, marks, floor, ceiling):
    best = None
    for t, pause in marks:
        if t < floor or t > ceiling or abs(t - target) > SNAP_S:
            continue
        score = abs(t - target) - min(pause, 0.4) * 0.8
        if best is None or score < best[0]:
            best = (score, t)
    return best[1] if best else min(max(target, floor), ceiling)


def _said(words, a, b):
    got = [w['w'].strip() for w in words if a - 0.02 <= (w['t0'] + w['t1']) / 2 <= b + 0.02]
    return ' '.join(got)


def existing(script):
    """[(id, start, end)] of the cutaway clips on the b-roll tracks."""
    from letitedit.timeline.edit_sync import layout
    out = []
    for t in script.get('tracks', []):
        if (t.get('kind') or 'video') == 'video' and re.search(r'(?i)b-?roll|cutaway', t.get('name') or ''):
            for it, s, e in layout(t):
                if it.get('id') and any(k in it for k in ('clip', 'image', 'motion', 'graphic', 'color')):
                    out.append((it['id'], s, e))
    return sorted(out, key=lambda x: x[1])


def plan(script, look=None, numbers=None, words=None):
    from letitedit.timeline.edit_sync import layout, main_track
    main = main_track(script)
    duration = max((e for _, _, e in layout(main)), default=0.0) if main else 0.0
    numbers = numbers or (look_numbers(look) if look else None)
    if not numbers or not duration:
        return {'numbers': numbers, 'slots': [], 'filled': 0, 'open': [], 'findings': [],
                'note': 'no Look numbers for cutaways' if not numbers else 'no picture on the timeline'}
    if words is None:
        try:
            from letitedit.timeline.timeline_speech import timeline_words
            words = timeline_words(script, cached_only=True)
        except Exception:  # noqa: BLE001 - no transcript yet: slots fall on the clock
            words = []
    marks = _boundaries(words)
    lo = numbers.get('min_s') or 0.6
    hi = numbers.get('max_s') or 3.0
    share = numbers.get('share')
    count = max(1, round((numbers.get('per_minute') or 0) * duration / 60.0)) if numbers.get('per_minute') else 0
    total = (share or 0) * duration if share else (numbers.get('median_s') or 2.0) * count
    if count and total / count > hi:
        count = math.ceil(total / hi)
    if not count:
        return {'numbers': numbers, 'slots': [], 'filled': 0, 'open': [], 'findings': [], 'note': 'no cutaway rate in the Look'}
    lengths = _lengths(count, total, lo, hi)
    talk = max(0.0, duration - sum(lengths))
    stretch = talk / (count + 1)
    limit = numbers.get('longest_talking_head_s')
    slots, cursor = [], 0.0
    for n, length in enumerate(lengths):
        want = cursor + (min(FIRST_TALK_S, stretch * 1.2 + 0.2) if n == 0 else stretch)
        ceiling = duration - LAST_TALK_S - length
        if want > ceiling:
            break
        start = _snap(want, marks, cursor + 0.3, ceiling)
        end = min(start + length, duration - LAST_TALK_S)
        if end - start < lo * 0.8:
            break
        slots.append({'n': n + 1, 'at': round(start, 2), 'len': round(end - start, 2), 'line': _said(words, start, end),
                      'before': _said(words, max(0.0, start - 1.5), start)})
        cursor = end
    have = existing(script)
    taken = set()
    for slot in slots:
        a, b = slot['at'], slot['at'] + slot['len']
        best = None
        for ident, s, e in have:
            if ident in taken:
                continue
            overlap = min(b, e) - max(a, s)
            if overlap >= 0.5 * min(b - a, e - s) and (best is None or overlap > best[0]):
                best = (overlap, ident)
        if best:
            slot['filled_by'] = best[1]
            taken.add(best[1])
    open_slots = [s for s in slots if 'filled_by' not in s]
    have_seconds = sum(e - s for _, s, e in have)
    result = {'numbers': {**{k: (round(v, 3) if isinstance(v, float) else v) for k, v in numbers.items()},
                          'duration_s': round(duration, 2), 'planned': len(slots), 'planned_seconds': round(sum(s['len'] for s in slots), 1),
                          'placed': len(have), 'placed_seconds': round(have_seconds, 1),
                          'placed_share': round(have_seconds / duration, 3)},
              'slots': slots, 'filled': len(slots) - len(open_slots), 'open': [s['n'] for s in open_slots], 'findings': []}
    short_count = len(have) < TOLERANCE * len(slots)
    short_share = share and have_seconds / duration + 0.05 < share
    if short_count or short_share:
        result['findings'].append(
            f"Cutaways fall short of the Look: {len(have)} placed covering {have_seconds / duration:.0%} of the time, the Look's "
            f"numbers plan {len(slots)} covering {(sum(s['len'] for s in slots) / duration):.0%}; open slots "
            + ', '.join(f"{s['n']} at {s['at']:g} s ({s['len']:g} s)" for s in open_slots[:12]))
    if limit:
        spans, cursor = [], 0.0
        for _, s, e in have:
            if s > cursor:
                spans.append((cursor, s))
            cursor = max(cursor, e)
        if duration > cursor:
            spans.append((cursor, duration))
        longest = max(spans, key=lambda x: x[1] - x[0], default=None)
        if longest and longest[1] - longest[0] > limit + 0.05:
            result['findings'].append(f"The speaker is alone for {longest[1] - longest[0]:.1f} s ({longest[0]:g}-{longest[1]:g} s); "
                                      f"the Look's longest stretch is {limit:.1f} s")
    return result
