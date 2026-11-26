"""{op: multicam}: a camera-switched cut of several synced angles of one talk, as one change.

The sound never cuts: it is the main picture track, whose clips come from one angle (the sound angle). The switched
pictures go on a video track just above it (default `Angles`): muted clips of the other angles at exactly the same
moment of the talk, with gaps where the main track's own angle is the one to show. So the words, captions, clean cut
edges, score and tighten all keep working on the main track as for any talk, and every angle clip can be moved,
trimmed, deleted or replaced by hand.

Times:
- sync time: the shoot's common clock, as letitedit_sync reports it (timeline time = at + file time / speed). Each
  angle is {file, at, speed}; file time = (sync - at) * speed.
- timeline time: the project's. Each main-track clip of an angle file maps timeline time to sync time.

Who speaks when comes from `speech` ([{who, from, to}] in sync seconds) or, by default, from the speaker words of one
angle (index_tools.speaker_words: letitedit_speakers' last assignment for that file). Which angle shows whom is the
angle's `shows` (speaker names or ids); an angle that shows two people or more is a wide.

Every angle clip carries a record (`multicam`: its angle's at and speed, and every angle's) so `refresh` can put it
back in sync after later edits to the main track (trims, deletes, tighten, ripples): each clip is mapped by its sync
time onto wherever the main track now plays that moment, split where the main track was cut, and removed when that
moment was cut.
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import time
from pathlib import Path

from letitedit.timeline.edit_script_base import clock, to_seconds

DEFAULTS = {
    'min_shot_s': 1.5,          # shorter shots are merged into a neighbour (pins excepted)
    'max_shot_s': 12.0,         # a longer shot gets a cutaway (a reaction or the wide) at a clean spot
    'lead_s': 0.15,             # a cut to a new speaker lands this long before their first word (inside the pause)
    'quick_s': 2.0,             # turns shorter than this, two or more speakers in a row: back-and-forth, on the wide
    'reset_s': 2.5,             # a pause this long with nobody talking shows the wide
    'merge_gap_s': 0.8,         # one speaker's words closer than this are one turn
    'reaction_every_s': 20.0,   # a long shot's cutaway is a reaction when the last one was this long ago, else the wide
    'reaction_s': 2.0,          # a reaction cutaway's length
    'wide_s': 4.0,              # a wide cutaway's length
    'snap_s': 1.5,              # how far a cutaway may move to land in a pause between words
    'jump_cut_min_s': 2.0,      # with hide_jump_cuts: both sides of a main-track cut at least this long to switch there
}
LAUGH = re.compile(r"\b(?:h[ae]h[ae]\w*|haha\w*|laugh\w*|chuckl\w*|giggl\w*)\b|[\[(](?:laugh|chuckl|giggl)", re.I)
EPS = 1e-6


# ============================================================================ angles and the main track

def _norm(p):
    return os.path.normcase(os.path.abspath(str(p))) if p else ''


def _angles(op):
    import letitedit.timeline.edit_script as edit_script
    raw = op.get('angles')
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError('multicam: angles is a list of two or more {file, at, shows}')
    out, names = [], set()
    for k, a in enumerate(raw, 1):
        if not isinstance(a, dict) or not a.get('file'):
            raise ValueError(f'multicam: angle {k} needs file')
        f = str(Path(a['file']).expanduser())
        if not Path(f).is_file():
            raise ValueError(f'multicam: angle {k}: no file {f}')
        dur = float(a.get('duration') or edit_script.probe(f)['duration'] or 0)
        if dur <= 0:
            raise ValueError(f'multicam: angle {k}: {Path(f).name} has no length')
        speed = float(a.get('speed') or 1.0)
        at = float(a.get('at') or 0.0)
        shows = a.get('shows') or []
        if isinstance(shows, str):
            shows = [shows]
        name = str(a.get('name') or Path(f).stem)
        if name in names:
            name = f'{name} {k}'
        names.add(name)
        out.append({'file': f, 'key': _norm(f), 'name': name, 'at': at, 'speed': speed, 'dur': dur,
                    'end': at + dur / speed, 'shows': [str(s).strip().lower() for s in shows if str(s).strip()]})
    if not any(a['shows'] for a in out):
        raise ValueError('multicam: say who each angle shows (shows: [names or speaker ids]; a wide lists everyone)')
    return out


def _pieces(main, by_key, fps, lo=None, hi=None):
    """The main track's clips as [{t0, t1, angle, s0, rate, item}]: sync(t) = s0 + (t - t0) * rate. Clips of files that
    are no angle get angle None. Clipped to [lo, hi] timeline seconds."""
    from letitedit.timeline.edit_sync import layout
    out = []
    for it, s, e in layout(main, fps):
        if 'clip' not in it or e - s < EPS:
            continue
        a = by_key.get(_norm(it['clip']))
        if lo is not None and e <= lo + EPS or hi is not None and s >= hi - EPS:
            continue
        cs = float(it.get('speed', 1.0))
        p = {'t0': s, 't1': e, 'angle': a, 'item': it, 'rate': 0.0, 's0': 0.0}
        if a is not None and not it.get('reverse'):
            p['rate'] = cs / a['speed']
            p['s0'] = a['at'] + to_seconds(it['in']) / a['speed']
        else:
            p['angle'] = None
        if lo is not None and p['t0'] < lo:
            p['s0'] += (lo - p['t0']) * p['rate']
            p['t0'] = lo
        if hi is not None and p['t1'] > hi:
            p['t1'] = hi
        out.append(p)
    return out


def _sync(p, t):
    return p['s0'] + (t - p['t0']) * p['rate']


def _time(p, sigma):
    return p['t0'] + (sigma - p['s0']) / p['rate']


def _cover_in_piece(g, p, margin):
    """The timeline span [c0, c1] of piece p that angle g covers, or None."""
    if p['angle'] is None or p['rate'] <= 0:
        return None
    c0 = max(p['t0'], _time(p, g['at'] + margin))
    c1 = min(p['t1'], _time(p, g['end'] - margin))
    return (c0, c1) if c1 - c0 > EPS else None


def _cover_end(g, pieces, t, margin, fps):
    """How far from timeline time t angle g covers without a break (t itself when it doesn't cover t)."""
    x = t
    for p in pieces:
        if p['t1'] <= x + EPS:
            continue
        if p['t0'] > x + 0.5 / fps:
            break                           # a gap on the main track: nothing to show there
        c = _cover_in_piece(g, p, margin)
        if c is None or c[0] > x + 0.5 / fps:
            break
        x = c[1]
        if c[1] < p['t1'] - EPS:
            break
    return x


# ============================================================================ who speaks when

def _speech_words(op, angles, pieces, notes):
    """Words in sync time: [{keys, who, s, e, w}]. keys: the lower-case names and ids the word's speaker goes by."""
    given = op.get('speech')
    if given is not None:
        if not isinstance(given, list):
            raise ValueError('multicam: speech is a list of {who, from, to} in sync seconds')
        out = []
        for k, t in enumerate(given, 1):
            if not isinstance(t, dict) or t.get('who') in (None, '') or t.get('from') is None or t.get('to') is None:
                raise ValueError(f'multicam: speech turn {k} needs who, from and to (sync seconds)')
            who = str(t['who'])
            out.append({'keys': {who.lower()}, 'who': who, 's': float(t['from']), 'e': float(t['to']),
                        'w': str(t.get('text') or '')})
        return sorted(out, key=lambda w: w['s']), 'given'
    import letitedit.footage.index_tools as index_tools
    src = op.get('speech_from')
    if src:
        g = next((a for a in angles if a['key'] == _norm(src) or a['name'] == src), None)
        if g is None:
            raise ValueError(f'multicam: speech_from {src!r} is not one of the angles')
    else:
        share = {}
        for p in pieces:
            if p['angle'] is not None:
                share[p['angle']['name']] = share.get(p['angle']['name'], 0) + p['t1'] - p['t0']
        order = sorted(angles, key=lambda a: -share.get(a['name'], 0))
        g = next((a for a in order if index_tools._assign_file(str(Path(a['file']).resolve())).exists()), order[0])
    ws = index_tools.speaker_words(g['file'])
    out = []
    for w in ws:
        keys = {str(x).lower() for x in (w.get('speaker'), w.get('name')) if x}
        if not keys:
            continue
        out.append({'keys': keys, 'who': w.get('name') or w.get('speaker'), 's': g['at'] + float(w['s']) / g['speed'],
                    'e': g['at'] + float(w['e']) / g['speed'], 'w': str(w.get('w') or '')})
    notes.append(f"who speaks when: letitedit_speakers' words of {g['name']}")
    return out, g['name']


def _timeline_words(words, pieces):
    out = []
    for p in pieces:
        if p['angle'] is None:
            continue
        lo, hi = p['s0'], _sync(p, p['t1'])
        for w in words:
            if w['e'] <= lo or w['s'] >= hi:
                continue
            mid = (max(w['s'], lo) + min(w['e'], hi)) / 2
            if not (lo <= mid <= hi):
                continue
            out.append(dict(w, t0=_time(p, max(w['s'], lo)), t1=_time(p, min(w['e'], hi))))
    return sorted(out, key=lambda w: w['t0'])


def _turns(tw, merge_gap):
    turns = []
    for w in tw:
        last = turns[-1] if turns else None
        if last and last['who'] == w['who'] and w['t0'] - last['b'] <= merge_gap:
            last['b'] = max(last['b'], w['t1'])
            last['words'].append(w)
        else:
            turns.append({'who': w['who'], 'keys': w['keys'], 'a': w['t0'], 'b': w['t1'], 'words': [w]})
    return turns


# ============================================================================ the plan

def _paint(segs, x, y, want):
    """Segments [(a, b, want)] with [x, y] set to `want`."""
    out = []
    for a, b, w in segs:
        if b <= x or a >= y:
            out.append((a, b, w))
            continue
        if a < x:
            out.append((a, x, w))
        if b > y:
            out.append((y, b, w))
    out.append((max(x, segs[0][0] if segs else x), min(y, segs[-1][1] if segs else y), want))
    return sorted([s for s in out if s[1] - s[0] > EPS], key=lambda s: s[0])


def _merge(segs, key=lambda s: s[2]):
    out = []
    for s in segs:
        if out and key(out[-1]) == key(s) and abs(out[-1][1] - s[0]) < EPS:
            out[-1] = (out[-1][0], s[1]) + tuple(out[-1][2:])
        else:
            out.append(s)
    return out


def _wants(turns, T0, T1, st):
    """[(a, b, want)] over [T0, T1]; want ('single', keys, who) | ('wide',)."""
    WIDE = ('wide',)
    if not turns:
        return [(T0, T1, WIDE)]
    cuts = [T0]
    for i in range(1, len(turns)):
        prev_end, start = max(t['b'] for t in turns[:i]), turns[i]['a']
        c = max(prev_end, start - st['lead_s']) if start > prev_end else start
        cuts.append(min(max(c, cuts[-1]), T1))
    cuts.append(T1)
    segs = []
    for i, t in enumerate(turns):
        a, b = cuts[i], cuts[i + 1]
        if b - a > EPS:
            segs.append((a, b, ('single', frozenset(t['keys']), t['who'])))
    # back-and-forth: runs of short turns with two or more speakers
    i = 0
    while i < len(turns):
        j = i
        while j < len(turns) and turns[j]['b'] - turns[j]['a'] < st['quick_s'] and \
                (j == i or turns[j]['a'] - turns[j - 1]['b'] < st['reset_s']):
            j += 1
        run = turns[i:j]
        if len(run) >= 3 and len({t['who'] for t in run}) >= 2:
            segs = _paint(segs, cuts[i], cuts[j], WIDE)
        i = max(j, i + 1)
    for i in range(1, len(turns)):
        a, b = turns[i - 1], turns[i]
        if b['a'] < a['b'] - 0.1 and a['who'] != b['who']:          # talking over each other
            segs = _paint(segs, max(T0, b['a'] - 0.3), min(T1, max(a['b'], b['b'])), WIDE)
        gap = b['a'] - max(t['b'] for t in turns[:i])
        if gap >= st['reset_s']:                                      # a pause with nobody talking
            segs = _paint(segs, max(T0, b['a'] - gap + 0.3), cuts[i], WIDE)
    for t in turns:
        for w in t['words']:
            if LAUGH.search(w['w'] or ''):
                segs = _paint(segs, max(T0, w['t0'] - 0.2), min(T1, w['t1'] + 0.8), WIDE)
    if turns[0]['a'] - T0 >= st['reset_s']:
        segs = _paint(segs, T0, max(T0, turns[0]['a'] - st['lead_s']), WIDE)
    tail = max(t['b'] for t in turns)
    if T1 - tail >= st['reset_s']:
        segs = _paint(segs, tail + 0.3, T1, WIDE)
    return _merge(segs)


class Planner:
    def __init__(self, angles, pieces, tw, turns, st, fps):
        self.angles, self.pieces, self.tw, self.turns, self.st, self.fps = angles, pieces, tw, turns, st, fps
        self.margin = 0.5 / fps
        most = max(len(a['shows']) for a in angles)
        self.wides = [a for a in angles if len(a['shows']) >= 2 and len(a['shows']) == most] or \
                     [a for a in angles if len(a['shows']) >= 2]
        self.wides += [a for a in angles if len(a['shows']) >= 2 and a not in self.wides]
        gaps = []
        for a, b in zip(tw, tw[1:]):
            if b['t0'] - a['t1'] > 0.08:
                gaps.append((a['t1'], b['t0']))
        self.gaps = gaps
        self.fallbacks = {}

    def singles(self, keys):
        return [a for a in self.angles if len(a['shows']) == 1 and a['shows'][0] in keys]

    def showing(self, keys):
        return [a for a in self.angles if keys & set(a['shows'])]

    def candidates(self, want):
        if want[0] == 'single':
            c = self.singles(want[1]) + self.wides + self.showing(want[1])
        elif want[0] == 'angle':
            c = [want[1]]
        else:
            c = list(self.wides) + sorted(self.angles, key=lambda a: -len(a['shows']))
        seen, out = set(), []
        for a in c + ([] if want[0] == 'angle' else list(self.angles)):
            if a['name'] not in seen:
                seen.add(a['name'])
                out.append(a)
        return out

    def cover_end(self, g, t):
        return _cover_end(g, self.pieces, t, self.margin, self.fps)

    def covers(self, g, a, b):
        return self.cover_end(g, a) >= b - 0.5 / self.fps

    def resolve(self, segs):
        """[(a, b, want)] -> shots [(a, b, angle or None, want)], each angle inside the time it covers."""
        shots = []
        for a, b, want in segs:
            cands = self.candidates(want)
            t = a
            while t < b - EPS:
                pick = None
                for g in cands:
                    x = self.cover_end(g, t)
                    if x > t + 0.5 / self.fps:
                        pick = (g, min(x, b))
                        break
                if pick is None:                    # nothing covers here (a gap, or a clip that is no angle)
                    nxt = min([p['t0'] for p in self.pieces if p['t0'] > t + EPS] + [b])
                    shots.append((t, min(nxt, b), None, want))
                    t = min(nxt, b)
                    continue
                g, x = pick
                if want[0] == 'single' and g is not cands[0]:
                    k = (want[2], g['name'])
                    self.fallbacks[k] = self.fallbacks.get(k, 0) + (x - t)
                shots.append((t, x, g, want))
                t = x
        return _merge(shots, key=lambda s: (s[2] and s[2]['name'], s[3]))

    def speaker_at(self, t):
        for tu in self.turns:
            if tu['a'] - 0.3 <= t <= tu['b'] + 0.3:
                return tu
        return None

    def listener(self, t, speaker_keys):
        """The most recent other speaker before t (else the next one after)."""
        before = [tu for tu in self.turns if tu['b'] <= t and not (tu['keys'] & speaker_keys)]
        if before:
            return before[-1]['keys']
        after = [tu for tu in self.turns if tu['a'] >= t and not (tu['keys'] & speaker_keys)]
        return after[0]['keys'] if after else None

    def snap(self, p, lo, hi):
        """A point in the pause between words nearest p, within [lo, hi] and snap_s of p (p when there is none)."""
        best = None
        for g0, g1 in self.gaps:
            m = (g0 + g1) / 2
            if lo <= m <= hi and abs(m - p) <= self.st['snap_s']:
                score = abs(m - p) - min(g1 - g0, 0.6)
                if best is None or score < best[0]:
                    best = (score, m)
        return best[1] if best else p

    def in_word(self, t):
        return any(w['t0'] + 0.02 < t < w['t1'] - 0.02 for w in self.tw)

    def alt_angle(self, shot, t0, t1):
        """Another angle for [t0, t1] of a shot: the wide for a single, the speaker's single (or the listener's) for
        a wide; None when nothing else covers."""
        a, b, g, want = shot
        cands = []
        if g is not None and g in self.wides:
            tu = self.speaker_at((t0 + t1) / 2)
            if tu:
                cands += self.singles(tu['keys'])
                lk = self.listener(t0, tu['keys'])
                if lk:
                    cands += self.singles(lk)
        else:
            cands += self.wides
        for c in cands:
            if c is not g and self.covers(c, t0, t1):
                return c
        return None

    def hide_jump_cuts(self, shots):
        out = []
        cuts = [p['t0'] for p in self.pieces[1:] if p['angle'] is not None]
        m = self.st['jump_cut_min_s']
        for s in shots:
            a, b, g, want = s
            inner = [c for c in cuts if a + m <= c <= b - m]
            if g is None or not inner:
                out.append(s)
                continue
            c = inner[0]
            alt = self.alt_angle(s, c, b)
            if alt is None:
                out.append(s)
                continue
            out.append((a, c, g, want))
            out.extend(self.hide_jump_cuts([(c, b, alt, want)]))
        return out

    def split_long(self, shots):
        st, out = self.st, []
        last_reaction = -1e9
        for s in shots:
            a, b, g, want = s
            if g is None or b - a <= st['max_shot_s'] + EPS:
                out.append(s)
                continue
            t = a
            while b - t > st['max_shot_s'] + EPS:
                target = t + min(st['max_shot_s'], max(st['min_shot_s'], (b - t) / math.ceil((b - t) / st['max_shot_s'])))
                tu = self.speaker_at(target)
                keys = tu['keys'] if tu else (want[1] if want[0] == 'single' else frozenset())
                react = st['reaction_every_s'] > 0 and target - last_reaction >= st['reaction_every_s']
                lk = self.listener(target, keys) if keys else None
                reactions = self.singles(lk) if lk else []
                if g in self.wides:         # out of a wide: the speaker's single, else a reaction (nothing else to cut to)
                    choices = (reactions + self.singles(keys)) if react else (self.singles(keys) + reactions)
                else:                       # out of a single: a reaction when one is due, else the wide
                    choices = (reactions + self.wides) if react else (self.wides + reactions)
                if not choices:             # nobody talking on a long wide: any single
                    choices = [x for x in self.angles if len(x['shows']) == 1]
                placed = False
                if b - t < 3 * st['min_shot_s'] - EPS:
                    # no room for shot, cutaway, shot: switch once, near the middle, for the rest of it
                    for c in choices:
                        if c is g:
                            continue
                        lo, hi = t + st['min_shot_s'], b - st['min_shot_s']
                        c0 = min(max(self.snap((t + b) / 2, lo, hi), lo), hi)
                        if self.covers(c, c0, b):
                            out.append((t, c0, g, want))
                            out.append((c0, b, c, ('cutaway',)))
                            if c in reactions:
                                last_reaction = c0
                            t = b
                            placed = True
                            break
                    break
                for c in choices:
                    if c is g:
                        continue
                    length = st['wide_s'] if c in self.wides else st['reaction_s']
                    length = max(st['min_shot_s'], min(length, b - t - 2 * st['min_shot_s']))
                    lo = t + st['min_shot_s']
                    c0 = self.snap(target, lo, b - st['min_shot_s'] - length)
                    c0 = min(max(c0, lo), b - st['min_shot_s'] - length)
                    if c0 <= lo - EPS or c0 + length > b - st['min_shot_s'] + EPS:
                        continue
                    c1 = self.snap(c0 + length, c0 + st['min_shot_s'], b - st['min_shot_s'])
                    if not self.covers(c, c0, c1):
                        continue
                    out.append((t, c0, g, want))
                    out.append((c0, c1, c, ('cutaway',)))
                    if c in reactions:
                        last_reaction = c0
                    t = c1
                    placed = True
                    break
                if not placed:
                    break
            if b - t > EPS:
                out.append((t, b, g, want))
        return out

    def snap_edges(self, shots):
        """Angle changes inside a word move to the nearest word edge (within snap_s / 3), keeping min_shot_s and
        each angle inside the time it covers. A picture cut mid-word is allowed; between words it reads cleaner."""
        if not self.tw:
            return shots
        reach, m = self.st['snap_s'] / 3, self.st['min_shot_s']
        edges = sorted({w['t0'] for w in self.tw} | {w['t1'] for w in self.tw})
        shots = list(shots)
        for i in range(1, len(shots)):
            a0, b0, g0, w0 = shots[i - 1]
            a1, b1, g1, w1 = shots[i]
            t = a1
            if g0 is g1 or not self.in_word(t):
                continue
            best = None
            for e in edges:
                if abs(e - t) > reach or self.in_word(e) or e - a0 < m - EPS or b1 - e < m - EPS:
                    continue
                lo, hi = min(e, t), max(e, t)
                if e > t and g0 is not None and not self.covers(g0, lo, hi):
                    continue
                if e < t and g1 is not None and not self.covers(g1, lo, hi):
                    continue
                if best is None or abs(e - t) < abs(best - t):
                    best = e
            if best is not None:
                shots[i - 1] = (a0, best, g0, w0)
                shots[i] = (best, b1, g1, w1)
        return shots

    def merge_short(self, shots):
        """Shots shorter than min_shot_s: joined to a neighbour that stays within max_shot_s, else made longer by
        taking from a neighbour that keeps min_shot_s, else joined to a neighbour anyway (split_long runs again)."""
        m, mx = self.st['min_shot_s'], self.st['max_shot_s']
        key = lambda s: (s[2] and s[2]['name'], s[3][0] == 'pin')         # noqa: E731
        shots = _merge(list(shots), key=key)
        for strict in (True, False):
            changed = True
            while changed:
                changed = False
                for i, (a, b, g, want) in enumerate(shots):
                    if b - a >= m - EPS or want[0] == 'pin' or len(shots) == 1:
                        continue
                    prev = shots[i - 1] if i > 0 else None
                    nxt = shots[i + 1] if i + 1 < len(shots) else None
                    free = lambda nb: nb is not None and nb[3][0] != 'pin' and (nb[2] is None or self.covers(nb[2], a, b))  # noqa: E731
                    joins = [(nb, side) for nb, side in ((prev, 'prev'), (nxt, 'next')) if free(nb)]
                    joins.sort(key=lambda x: x[0][1] - x[0][0])
                    done = False
                    for nb, side in joins:
                        if strict and (nb[1] - nb[0]) + (b - a) > mx + EPS:
                            continue
                        if side == 'prev':
                            shots[i - 1] = (prev[0], b, prev[2], prev[3])
                        else:
                            shots[i + 1] = (a, nxt[1], nxt[2], nxt[3])
                        del shots[i]
                        done = True
                        break
                    if not done and strict and g is not None:
                        need = m - (b - a)
                        if nxt is not None and nxt[3][0] != 'pin' and nxt[1] - nxt[0] - need >= m and \
                                self.covers(g, b, b + need):
                            shots[i], shots[i + 1] = (a, b + need, g, want), (b + need, nxt[1], nxt[2], nxt[3])
                            done = True
                        elif prev is not None and prev[3][0] != 'pin' and prev[1] - prev[0] - need >= m and \
                                self.covers(g, a - need, a):
                            shots[i - 1], shots[i] = (prev[0], a - need, prev[2], prev[3]), (a - need, b, g, want)
                            done = True
                    if done:
                        shots = _merge(shots, key=key)
                        changed = True
                        break
        return shots


def _frames(shots, fps):
    out = []
    for a, b, g, want in shots:
        a, b = round(a * fps) / fps, round(b * fps) / fps
        if out:
            a = out[-1][1]
        if b - a > 0.5 / fps:
            out.append((a, b, g, want))
    return out


# ============================================================================ the sound angle

def _decode(path, start, seconds, rate=16000):
    import numpy as np
    from letitedit.timeline.edit_script_base import FFPROBE
    ff = str(Path(FFPROBE).with_name('ffmpeg.exe'))
    r = subprocess.run([ff, '-v', 'error', '-ss', f'{max(0.0, start):.3f}', '-t', f'{seconds:.3f}', '-i', str(path),
                        '-vn', '-ac', '1', '-ar', str(rate), '-f', 's16le', '-'], capture_output=True,
                       creationflags=0x08000000, timeout=120)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def sound_scores(cands, span, words=(), windows=3, seconds=20.0):
    """Per angle: noise floor, speech level, their spread, clipping, and the level difference between speakers
    (sync time), over a few windows of `span`. score = spread - speaker difference - clipping penalty."""
    import numpy as np
    out = {}
    s0, s1 = span
    length = max(0.0, s1 - s0)
    n = max(1, min(windows, int(length // max(1.0, seconds)) or 1))
    starts = [s0 + (k + 0.5) * length / n - min(seconds, length) / 2 for k in range(n)]
    for g in cands:
        frames_db, frame_t, clip_n, total = [], [], 0, 0
        for s in starts:
            y = _decode(g['file'], (s - g['at']) * g['speed'], min(seconds, length))
            if y.size < 1600:
                continue
            hop = 800                                   # 50 ms at 16 kHz
            k = y.size // hop
            fr = y[:k * hop].reshape(k, hop)
            db = 10 * np.log10((fr ** 2).mean(axis=1) + 1e-10)
            frames_db.append(db)
            frame_t.append(s + (np.arange(k) + 0.5) * hop / 16000 / g['speed'])
            clip_n += int((np.abs(y) >= 0.995).sum())
            total += y.size
        if not frames_db:
            out[g['name']] = {'score': -1e9, 'why': 'no sound'}
            continue
        db, ft = np.concatenate(frames_db), np.concatenate(frame_t)
        floor, loud = float(np.percentile(db, 10)), float(np.percentile(db, 90))
        per = {}
        for w in words:
            sel = (ft >= w['s']) & (ft <= w['e'])
            if sel.any():
                per.setdefault(w['who'], []).append(db[sel])
        levels = {k: round(float(np.percentile(np.concatenate(v), 75)), 1) for k, v in per.items() if v}
        diff = (max(levels.values()) - min(levels.values())) if len(levels) >= 2 else 0.0
        clip = clip_n / max(1, total)
        score = (loud - floor) - diff - 2000 * clip
        out[g['name']] = {'score': round(score, 2), 'floor_db': round(floor, 1), 'speech_db': round(loud, 1),
                          'spread_db': round(loud - floor, 1), 'speaker_levels_db': levels,
                          'speaker_difference_db': round(diff, 1), 'clipped_share': round(clip, 6)}
    return out


# ============================================================================ the op

def _find_track(script, name):
    return next((t for t in script['tracks'] if t['name'] == name), None)


def _ids(script):
    return {it.get('id') for t in script['tracks'] for it in t['items'] if it.get('id')}


def _new_ids(script, n):
    used, out, k = _ids(script), [], 1
    while len(out) < n:
        i = f'cam{k}'
        if i not in used:
            out.append(i)
        k += 1
    return out


def _rebuild(track, placed, fps):
    """Items [(item, start)] -> the track's items with gaps between them (sorted, frame-rounded)."""
    items, pos = [], 0.0
    from letitedit.timeline.edit_sync import item_len
    for it, s in sorted(placed, key=lambda x: x[1]):
        s = round(s * fps) / fps
        if s > pos + 0.5 / fps:
            items.append({'gap': round(s - pos, 4)})
            pos = s
        it.pop('at', None)
        it.pop('pin', None)
        items.append(it)
        pos += item_len(it, fps)
    track['items'] = items


def _record(g, angles):
    return {'angle': g['name'], 'at': round(g['at'], 6), 'speed': g['speed'],
            'angles': [[a['file'], round(a['at'], 6), a['speed'], a['name']] for a in angles]}


def _clip(g, p, a, b, fps, angles):
    sa, sb = _sync(p, a), _sync(p, b)
    it = {'clip': g['file'], 'in': round((sa - g['at']) * g['speed'], 4), 'out': round((sb - g['at']) * g['speed'], 4),
          'name': g['name'], 'effects': ['mute'], 'multicam': _record(g, angles)}
    sp = p['rate'] * g['speed']
    if abs(sp - 1.0) > 1e-6:
        it['speed'] = round(sp, 8)
    return it


def _choose_sound_track(op, lay, angles, notes, angle_named, main, layout, fps, by_key):
    """Choose the continuous sound source and map main-track clips to its clock."""
    sound = op.get('sound')
    words, speech_src = None, None
    if lay:
        if sound in (None, 'best'):
            sf = op.get('source_from')
            stt = op.get('source_to')
            lo = float(sf) if sf is not None else max(a['at'] for a in angles if len(a['shows']) >= 2) \
                if any(len(a['shows']) >= 2 for a in angles) else min(a['at'] for a in angles)
            hi = float(stt) if stt is not None else None
            cands = [a for a in angles if a['at'] <= lo + 0.05 and (hi is None or a['end'] >= hi - 0.05)]
            if not cands:
                raise ValueError('multicam: no angle covers the whole of source_from..source_to, so none can carry '
                                 'the sound; give a shorter span or sound: <angle>')
            if len(cands) == 1:
                g = cands[0]
                notes.append(f"sound: {g['name']}, the only angle that covers the span")
            else:
                span = (lo, hi if hi is not None else min(a['end'] for a in cands))
                try:
                    words, speech_src = _speech_words(op, angles, [], notes)
                except Exception as exc:  # noqa: BLE001 - no speakers yet: score the sound without them
                    words = []
                    notes.append(f'who speaks when: not known yet ({exc})')
                sc = sound_scores(cands, span, words)
                g = max(cands, key=lambda a: sc[a['name']]['score'])
                notes.append('sound: ' + g['name'] + ', the best measured (' + '; '.join(
                    f"{k}: spread {v.get('spread_db')} dB, speakers {v.get('speaker_difference_db')} dB apart"
                    for k, v in sc.items()) + ')')
                op['_sound_scores'] = sc
        else:
            g = angle_named(sound, 'sound')
        s_lo = float(op['source_from']) if op.get('source_from') is not None else g['at']
        s_hi = float(op['source_to']) if op.get('source_to') is not None else g['end']
        s_lo, s_hi = max(s_lo, g['at']), min(s_hi, g['end'])
        if s_hi - s_lo < 1.0:
            raise ValueError(f"multicam: {g['name']} covers sync {g['at']:.2f}-{g['end']:.2f} s, not "
                             f"source_from..source_to")
        it = {'clip': g['file'], 'in': round((s_lo - g['at']) * g['speed'], 4),
              'out': round((s_hi - g['at']) * g['speed'], 4), 'name': f"{g['name']} (sound)"}
        if abs(g['speed'] - 1.0) > 1e-9:
            it['speed'] = g['speed']
        main['items'] = [it]
        notes.append(f"the main track is now {g['name']} from sync {s_lo:.2f} to {s_hi:.2f} s (picture and sound)")
    elif sound not in (None, 'main'):
        g = angle_named(sound, 'sound')
        moved = 0
        for it, s, e in layout(main, fps):
            a = by_key.get(_norm(it.get('clip'))) if 'clip' in it else None
            if a is None or a is g or it.get('reverse'):
                continue
            s0 = a['at'] + to_seconds(it['in']) / a['speed']
            s1 = a['at'] + to_seconds(it['out']) / a['speed']
            if s0 < g['at'] or s1 > g['end']:
                notes.append(f"{it.get('id')}: kept on {a['name']}: {g['name']} doesn't cover it")
                continue
            it['clip'] = g['file']
            it['in'], it['out'] = round((s0 - g['at']) * g['speed'], 4), round((s1 - g['at']) * g['speed'], 4)
            sp = float(it.get('speed', 1.0)) * g['speed'] / a['speed']
            if abs(sp - 1.0) > 1e-9:
                it['speed'] = round(sp, 8)
            else:
                it.pop('speed', None)
            moved += 1
        if moved:
            notes.append(f"{moved} main-track clip(s) now play {g['name']} (its picture and sound), same moments")
    files = {_norm(it['clip']) for it in main['items'] if 'clip' in it and _norm(it['clip']) in by_key}
    if len(files) > 1:
        notes.append('the main track plays the sound of ' + ', '.join(by_key[f]['name'] for f in sorted(files))
                     + ": the level may change where it changes file (sound: <angle> makes it one)")
    return words, speech_src


def _write_angle_track(script, track_name, main, layout, fps, T0, T1, shots, pieces, angles, op):
    """Replace the selected range with muted angle clips and retain outside items."""
    # the clips, split where the main track is cut; nothing where the main track's own angle is the one to show
    track = _find_track(script, track_name)
    if track is None:
        track = {'name': track_name, 'kind': 'video', 'items': []}
        script['tracks'].insert(script['tracks'].index(main) + 1, track)
    elif track.get('kind', 'video') != 'video':
        raise ValueError(f'multicam: {track_name} is an audio track')
    kept = []
    dropped = 0
    for it, s, e in layout(track, fps):
        if e <= T0 + EPS or s >= T1 - EPS:
            kept.append((it, s))
        else:
            dropped += 1
    new = []
    for a, b, g, want in shots:
        if g is None:
            continue
        for p in pieces:
            x, y = max(a, p['t0']), min(b, p['t1'])
            if y - x < 0.5 / fps or p['angle'] is None:
                continue
            if p['angle'] is g:
                continue
            new.append((_clip(g, p, x, y, fps, angles), x))
    ids = _new_ids(script, len(new))
    for (it, s), i in zip(new, ids):
        it['id'] = i
    _rebuild(track, kept + new, fps)
    op['_pinned'] = ids
    return new, dropped


def _describe_switches(shots, speech_src, pl, T0, T1, new, track_name, turns, dropped, notes, t_start, op):
    """Record the switching summary and planned shots on the operation."""
    # the result
    per = {}
    for a, b, g, want in shots:
        n = g['name'] if g else '(no angle)'
        d = per.setdefault(n, [0, 0.0])
        d[0] += 1
        d[1] += b - a
    lens = [b - a for a, b, g, w in shots]
    switches = sum(1 for x, y in zip(shots, shots[1:]) if (x[2] and x[2]['name']) != (y[2] and y[2]['name']))
    in_words = 0 if speech_src == 'given' else \
        sum(1 for x, y in zip(shots, shots[1:]) if pl.in_word(y[0]) and (x[2] is not y[2]))
    fall = [f"{who} on {n} for {sec:.0f} s (their own angle doesn't cover it)" for (who, n), sec in pl.fallbacks.items()
            if sec >= 0.5]
    parts = [f"{len(shots)} shots over {clock(T0)}-{clock(T1)} ({switches} angle changes, shots "
             f"{min(lens):.1f}-{max(lens):.1f} s, median {sorted(lens)[len(lens) // 2]:.1f} s)",
             'per angle: ' + ', '.join(f'{n} {c} shots / {sec:.0f} s' for n, (c, sec) in per.items()),
             f"{len(new)} clip(s) on {track_name} (muted: the sound is the main track's, uncut)",
             f"{len(turns)} speaker turns from {speech_src}"]
    if in_words:
        parts.append(f'{in_words} angle change(s) inside a word (no pause near enough)')
    if dropped:
        parts.append(f'{dropped} earlier item(s) on {track_name} in this range replaced')
    parts += fall + notes
    parts.append(f'{time.time() - t_start:.1f} s')
    parts.sort(key=lambda x: not x.startswith('WHO TALKS WHEN'))       # the warning first, the rest in order
    op['_result'] = '; '.join(parts)
    op['_shots'] = [{'from': round(a, 3), 'to': round(b, 3), 'angle': g['name'] if g else None,
                     'why': want[0] if want[0] != 'single' else f'{want[2]} speaking'} for a, b, g, want in shots]


def apply_op(script, op):
    t_start = time.time()
    from letitedit.timeline.edit_sync import layout, main_track
    st = dict(DEFAULTS)
    for k in DEFAULTS:
        if op.get(k) is not None:
            st[k] = float(op[k])
    if st['min_shot_s'] <= 0 or st['max_shot_s'] < 2 * st['min_shot_s']:
        raise ValueError('multicam: min_shot_s > 0 and max_shot_s at least twice min_shot_s')
    fps = float((script.get('profile') or {}).get('fps') or 30)
    angles = _angles(op)
    by_key = {a['key']: a for a in angles}
    by_name = {a['name']: a for a in angles}
    main = main_track(script)
    if main is None:
        raise ValueError('multicam: the project has no video track')
    notes = []
    lay = op.get('source_from') is not None or op.get('source_to') is not None or \
        not any('clip' in it for it in main['items'])

    def angle_named(v, what):
        g = by_name.get(v) or by_key.get(_norm(v))
        if g is None:
            raise ValueError(f"multicam: {what} {v!r} is not one of the angles ({', '.join(by_name)})")
        return g

    words, speech_src = _choose_sound_track(op, lay, angles, notes, angle_named, main, layout, fps, by_key)

    # the cameras' own full clips on other video tracks (letitedit_sync's stack) would cover the cut
    track_name = op.get('track') or 'Angles'
    if op.get('clear_stacks', True):
        cleared = 0
        for t in script['tracks']:
            if t is main or t['name'] == track_name or t.get('kind', 'video') != 'video':
                continue
            if any('clip' in it and _norm(it['clip']) in by_key and not it.get('multicam') for it in t['items']):
                kept = [(it, s) for it, s, e in layout(t, fps)
                        if not ('clip' in it and _norm(it['clip']) in by_key and not it.get('multicam'))]
                cleared += sum(1 for it in t['items'] if 'clip' in it) - len(kept)
                _rebuild(t, kept, fps)
        if cleared:
            notes.append(f'{cleared} full camera clip(s) on other video tracks taken off (they would cover the cut; '
                         'clear_stacks: false keeps them)')

    lo = float(op['from']) if op.get('from') is not None else None
    hi = float(op['to']) if op.get('to') is not None else None
    pieces = _pieces(main, by_key, fps, lo, hi)
    if not any(p['angle'] for p in pieces):
        raise ValueError('multicam: the main track has no clip of an angle in that range')
    T0, T1 = pieces[0]['t0'], pieces[-1]['t1']
    if words is None:
        words, speech_src = _speech_words(op, angles, pieces, notes)
    tw = _timeline_words(words, pieces)
    if speech_src != 'given' and (not tw or T1 - max(w['t1'] for w in tw) > 30 or min(w['t0'] for w in tw) - T0 > 30):
        heard = (f"{clock(min(w['t0'] for w in tw))}-{clock(max(w['t1'] for w in tw))}" if tw else 'nowhere')
        notes.insert(0, f"WHO TALKS WHEN IS KNOWN ONLY {heard} of {clock(T0)}-{clock(T1)}: {speech_src}'s words stop "
                        f"there (a long file is transcribed in parts). Outside it the cut shows the wide and cutaways. "
                        f"Run letitedit_words on {speech_src}'s whole file, then letitedit_speakers, then this op again")
    unknown = sorted({w['who'] for w in tw if not any(w['keys'] & set(a['shows']) for a in angles)})
    if unknown:
        notes.append(f"no angle lists {', '.join(map(str, unknown))} in shows: their turns show the wide")
    turns = _turns(tw, st['merge_gap_s'])
    pl = Planner(angles, pieces, tw, turns, st, fps)
    if not pl.wides:
        notes.append('no angle shows two people or more, so there is no wide: back-and-forth stays on the speakers')
    segs = _wants(turns, T0, T1, st)
    shots = pl.resolve(segs)
    if op.get('hide_jump_cuts', True):
        shots = pl.hide_jump_cuts(shots)
    shots = pl.merge_short(shots)       # first: a join can make a shot too long, and split_long makes none too short
    shots = pl.split_long(shots)
    for k, pin in enumerate(op.get('pins') or [], 1):
        if not isinstance(pin, dict) or pin.get('from') is None or pin.get('to') is None or not pin.get('angle'):
            raise ValueError(f'multicam: pin {k} needs from, to (timeline s) and angle')
        g = angle_named(pin['angle'], f'pin {k} angle')
        a, b = max(T0, float(pin['from'])), min(T1, float(pin['to']))
        if not pl.covers(g, a, b):
            raise ValueError(f"multicam: pin {k}: {g['name']} doesn't cover {a:.2f}-{b:.2f} s (it ends at "
                             f"{pl.cover_end(g, a):.2f} s from there)" if pl.cover_end(g, a) > a else
                             f"multicam: pin {k}: {g['name']} doesn't cover {a:.2f} s")
        out = []
        for s in shots:
            if s[1] <= a or s[0] >= b:
                out.append(s)
                continue
            if s[0] < a:
                out.append((s[0], a) + s[2:])
            if s[1] > b:
                out.append((b, s[1]) + s[2:])
        out.append((a, b, g, ('pin',)))
        shots = sorted(out, key=lambda s: s[0])
    if op.get('pins'):
        shots = pl.merge_short(shots)
    shots = _frames(pl.snap_edges(shots), fps)

    new, dropped = _write_angle_track(script, track_name, main, layout, fps, T0, T1, shots, pieces, angles, op)

    _describe_switches(shots, speech_src, pl, T0, T1, new, track_name, turns, dropped, notes, t_start, op)

    return shots


# ============================================================================ after later edits

def _edited_spans(item, original, old_pieces, pieces, old_ids, fps):
    original_item, start, end = original
    source_in = to_seconds(original_item['in'])
    speed = float(original_item.get('speed', 1))
    spans = []
    for old in old_pieces:
        left, right = max(start, old['t0']), min(end, old['t1'])
        if right <= left:
            continue
        lower, upper = _sync(old, left), _sync(old, right)
        for piece in pieces:
            candidate = piece['item']
            if _norm(candidate['clip']) != _norm(old['item']['clip']):
                continue
            owner = old['item'].get('id')
            if owner not in (candidate.get('id'), candidate.get('from')) and candidate.get('id') in old_ids:
                continue
            if _norm(candidate['clip']) == _norm(item['clip']):
                continue
            lower_kept = max(lower, piece['s0'])
            upper_kept = min(upper, _sync(piece, piece['t1']))
            if upper_kept <= lower_kept:
                continue
            old_left, old_right = _time(old, lower_kept), _time(old, upper_kept)
            new_left, new_right = _time(piece, lower_kept), _time(piece, upper_kept)
            edges = [round(source_in + (old_left - start) * speed, 4),
                     round(source_in + (old_right - start) * speed, 4), speed * piece['rate'] / old['rate']]
            if abs(old_left - start) < EPS:
                edges[0] = to_seconds(original_item['in'])
            if abs(old_right - end) < EPS:
                edges[1] = to_seconds(original_item['out'])
            spans.append((abs(new_left - start), new_left, new_right, piece, lower_kept, upper_kept, edges))
    merged = []
    for span in sorted(spans, key=lambda value: value[1]):
        if merged and abs(merged[-1][2] - span[1]) < 0.5 / fps and (
                abs(merged[-1][6][1] - span[6][0]) < 1e-3 and abs(merged[-1][6][2] - span[6][2]) < 1e-6):
            previous = merged.pop()
            merged.append((*previous[:2], span[2], *previous[3:6],
                           [previous[6][0], span[6][1], previous[6][2]]))
        else:
            merged.append(span)
    return merged


def refresh(script, skip=(), before=None):
    """Put every angle clip (an item with a multicam record) back on the moment of the talk it shows, wherever the main
    track now plays that moment: split where the main track is cut, removed where that moment was cut, never over
    another item of its track. Returns notes."""
    from letitedit.timeline.edit_sync import layout, main_track
    fps = float((script.get('profile') or {}).get('fps') or 30)
    main = main_track(script)
    if main is None:
        return []
    notes, moved, removed, split = [], 0, 0, 0
    old_tracks = {track['name']: track for track in before['tracks']} if before else {}
    for t in script['tracks']:
        if t is main or t.get('kind', 'video') != 'video':
            continue
        lay = layout(t, fps)
        mine = [(it, s, e) for it, s, e in lay if isinstance(it.get('multicam'), dict) and it.get('id') not in skip
                and 'clip' in it]
        if not mine:
            continue
        rec0 = mine[0][0]['multicam']
        angles = {}
        for f, at, sp, name in rec0.get('angles') or []:
            angles[_norm(f)] = {'file': f, 'key': _norm(f), 'at': float(at), 'speed': float(sp), 'name': name}
        for it, s, e in mine:
            for f, at, sp, name in it['multicam'].get('angles') or []:
                angles.setdefault(_norm(f), {'file': f, 'key': _norm(f), 'at': float(at), 'speed': float(sp),
                                             'name': name})
        pieces = [p for p in _pieces(main, angles, fps) if p['angle'] is not None and p['rate'] > 0]
        old_main = main_track(before) if before else None
        old_pieces = ([p for p in _pieces(old_main, angles, fps) if p['angle'] is not None and p['rate'] > 0]
                      if old_main else [])
        old_ids = {piece['item'].get('id') for piece in old_pieces}
        originals = {item.get('id'): (item, start, end)
                     for item, start, end in layout(old_tracks.get(t['name'], {'items': []}), fps)}
        fixed = [(s, e) for it, s, e in lay if not (isinstance(it.get('multicam'), dict) and it.get('id') not in skip
                                                     and 'clip' in it)]
        placed_spans = list(fixed)
        out = [(it, s) for it, s, e in lay if not (isinstance(it.get('multicam'), dict) and it.get('id') not in skip
                                                   and 'clip' in it)]
        cands = []
        same = True
        for it, s, e in mine:
            r = it['multicam']
            g_at, g_sp = float(r['at']), float(r['speed'])
            A = g_at + to_seconds(it['in']) / g_sp
            B = g_at + to_seconds(it['out']) / g_sp
            got = []
            original = originals.get(it.get('id'))
            anchored = original is not None and all(it.get(key) == original[0].get(key)
                                                    for key in ('clip', 'in', 'out', 'speed', 'multicam'))
            if anchored:
                got = _edited_spans(it, original, old_pieces, pieces, old_ids, fps)
            for p in (() if anchored else pieces):
                lo, hi = p['s0'], _sync(p, p['t1'])
                x, y = max(A, lo), min(B, hi)
                if y - x < 0.5 / fps * p['rate']:
                    continue
                if _norm(p['item']['clip']) == _norm(it['clip']):
                    continue                        # the main track shows this angle there itself
                ta, tb = _time(p, x), _time(p, y)
                got.append((abs(ta - s), ta, tb, p, x, y,
                            [round((x - g_at) * g_sp, 4), round((y - g_at) * g_sp, 4), p['rate'] * g_sp]))
            minimum = min(3, round((e - s) * fps))
            got = [span for span in got if round(span[2] * fps) - round(span[1] * fps) >= minimum]
            if len(got) != 1 or abs(got[0][1] - s) > 0.5 / fps or abs(got[0][2] - e) > 0.5 / fps:
                same = False
            if not got:
                removed += 1
            cands.append((it, s, got))
        if same:
            continue
        for it, s, got in cands:
            got.sort(key=lambda g: g[0])
            first = True
            for dist, ta, tb, p, x, y, edges in got:
                if any(ta < fe - 0.5 / fps and tb > fs + 0.5 / fps for fs, fe in placed_spans):
                    continue
                piece = dict(it) if first else {k: v for k, v in it.items() if k != 'id'}
                piece['in'], piece['out'], sp = edges
                if abs(sp - 1.0) > 1e-6:
                    piece['speed'] = round(sp, 8)
                else:
                    piece.pop('speed', None)
                if abs(ta - s) > 0.5 / fps:
                    moved += 1
                if not first:
                    split += 1
                placed_spans.append((ta, tb))
                out.append((piece, ta))
                first = False
        _rebuild(t, out, fps)
    if moved or removed or split:
        notes.append(f'angle clips followed the main track: {moved} moved, {split} split where it was cut, {removed} '
                     'removed with the moments that were cut')
    return notes
