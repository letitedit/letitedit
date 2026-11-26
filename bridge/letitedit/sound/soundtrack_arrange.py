"""The arrangement: the skeleton of runs and fixed points, the beam search over bar slots, and the clips laid out in whole frames.

Part of `soundtrack` (letitedit/sound/soundtrack.py), which imports every name here back,
so `soundtrack.X` is the same object it always was.
"""
from __future__ import annotations
import math
import numpy as np
from letitedit.sound.soundtrack_base import (  # noqa: E402
    _clock, _ms, _r, _span
)
from letitedit.sound.soundtrack_song import (  # noqa: E402
    _norm01
)


# ============================================================================ the skeleton: runs, fixed points, slots

def _resid_cost(r, coarse):
    return (abs(r) / (0.15 if coarse else 0.03)) ** 2 * 0.5 + 0.3


def _break_cost(gap, beat, bar, kind):
    """A stop before a hit: a tight one is nearly a cut, a sliver of silence sounds like a glitch, half a beat to a
    beat is a deliberate stop, a longer hole only suits a drop or a phrase (a breath before it)."""
    if gap < 0.06:
        return 0.5
    if gap < 0.3 * beat:
        return 3.0
    big = kind in ('drop', 'phrase')
    if gap <= 1.05 * beat:
        return 0.8 if big else 1.4
    if gap <= 2.05 * beat:
        return 1.2 if big else 2.6
    if gap <= bar + 1e-6:
        return 1.8 if big else 4.0
    return 6.0


def _fit(D, an, approach, kind, max_stretch, tol):
    """The cheapest way to fill D seconds from a fixed point so the next fixed point lands: whole bars as they are
    ('natural'), whole beats with the last one trimmed ('join'), a bounded speed change ('stretch'), or music then
    silence ('break'). Returns the choice and the cheapest options considered."""
    beat, bar, bpb, coarse = an['beat_s'], an['bar_s'], an['beats_per_bar'], an['coarse']
    unit, per = (bar, 1) if coarse else (beat, bpb)
    m0 = D / unit
    opts = []
    for m in range(max(1, int(math.floor(m0)) - 3), int(math.ceil(m0)) + 4):
        n, k = divmod(m, per)
        r = D - m * unit
        sigma = (m * unit) / D
        meter = 0.0 if k == 0 else 2.0
        base = {'m': m, 'n': n, 'k': k, 'sigma': 1.0, 'gap': 0.0, 'residual': r}
        if abs(r) <= tol:
            opts.append({**base, 'approach': 'natural' if k == 0 else 'join', 'cost': meter})
        else:
            opts.append({**base, 'approach': 'join', 'cost': meter + _resid_cost(r, coarse)})
            if max_stretch > 0 and abs(sigma - 1) <= max_stretch + 1e-9:
                opts.append({**base, 'approach': 'stretch', 'sigma': sigma, 'residual': 0.0,
                             'cost': meter + 0.5 + 100 * abs(sigma - 1)})
        if r > 0.0:
            opts.append({**base, 'approach': 'break', 'gap': r, 'residual': 0.0,
                         'cost': 3.0 if coarse else meter + _break_cost(r, beat, bar, kind)})
    opts = [o for o in opts if o['n'] >= 1 or D < 1.5 * bar]
    if not opts:
        opts = [{'m': 1, 'n': 0, 'k': 1, 'sigma': 1.0, 'gap': max(0.0, D - unit), 'residual': 0.0,
                 'approach': 'break', 'cost': 9.0}]
    pool = opts
    if approach in ('join', 'stretch', 'break'):
        allowed = {'join': ('natural', 'join'), 'stretch': ('natural', 'stretch'), 'break': ('natural', 'break')}
        pool = [o for o in opts if o['approach'] in allowed[approach]] or opts
    best = min(pool, key=lambda o: o['cost'])
    return best, sorted(opts, key=lambda o: o['cost'])[:4]


def _ending_bar(an, room, bar):
    """First bar of the song's own ending that fits in `room` seconds: of the ending candidates (latest phrase
    starts first), the first that fits and leaves at least 2 bars + the tail."""
    L = an['duration']
    for j in an['ending']['bars']:
        U = L - an['bars'][j][0]
        if U <= room - 0.5 * bar and U >= min(4.0, 2 * bar):
            return j, U
    return None, None


def _skeleton_runs(req, o, a0, a1, bar, warnings):
    """The stretches with music between the drop_out ranges, each with its entry and exit; too-short ones
    dropped with a warning."""
    drops = [p for p in req['protect'] if p['mode'] == 'drop_out' and p['to'] > a0 and p['from'] < a1]
    runs, cur, entry = [], a0, {'kind': req['entry'], 'fade': o['fade_in_s'], 'after': None}
    for p in drops:
        if p['from'] > cur + 1e-6:
            fo = o['drop_fade_out_s'] if p['fade_out'] is None else float(p['fade_out'])
            runs.append({'a': cur, 'b': min(p['from'], a1), 'entry': entry,
                         'exit': {'kind': 'drop', 'fade': fo, 'protect': p}})
        cur = max(cur, p['to'])
        entry = {'kind': p['entry'], 'fade': o['drop_fade_in_s'] if p['fade_in'] is None else float(p['fade_in']),
                 'after': p}
    if cur < a1 - 1e-6:
        runs.append({'a': cur, 'b': a1, 'entry': entry, 'exit': {'kind': 'end', 'fade': o['fade_out_s']}})
    kept = []
    for r in runs:
        if r['b'] - r['a'] < max(o['min_run_s'], bar):
            warnings.append(f"no music {_span(r['a'], r['b'])}: only {r['b'] - r['a']:.1f} s between drop-outs "
                            f"(min_run_s {o['min_run_s']:g} s, a bar is {bar:.2f} s)")
            continue
        kept.append(r)
    runs = kept
    if not runs:
        raise ValueError('no stretch of the timeline is left for music (the drop_out ranges cover it)')
    return drops, runs


def _skeleton_hits(req, drops, runs, a0, a1, warnings):
    """The hits that can land (inside a run and before its last half second); the others are marked skipped
    with a warning."""
    hits = []
    for h in req['hits']:
        if any(p['from'] - 1e-6 <= h['at'] <= p['to'] + 1e-6 for p in drops):
            warnings.append(f"hit {_clock(h['at'])} is inside a drop_out range (no music there): not landed")
            h['skipped'] = 'inside a drop_out range'
            continue
        if not any(r['a'] - 1e-6 <= h['at'] < r['b'] - 0.5 for r in runs):
            warnings.append(f"hit {_clock(h['at'])} is outside the music ({_span(a0, a1)}) or in its last 0.5 s: "
                            'not landed')
            h['skipped'] = 'outside the music'
            continue
        hits.append(h)
    return hits


def _skeleton_ending(req, runs, hits, an, bar, warnings):
    """How the music ends: the song's own ending when it fits after the last fixed point, otherwise a fade."""
    ending = req['ending']
    last = runs[-1]
    last_fixed = max([last['a']] + [h['at'] for h in hits if last['a'] <= h['at'] < last['b']])
    eb = eu = None
    if ending in ('auto', 'song'):
        eb, eu = _ending_bar(an, last['b'] - last_fixed, bar)
        if eb is None or (ending == 'auto' and not an['ending']['natural']):
            if ending == 'song':
                warnings.append("the song's own ending does not fit after the last fixed point "
                                f"{_clock(last_fixed)}: fading out instead")
            eb = eu = None
            ending = 'fade'
        else:
            ending = 'song'
    return ending, eb, eu


def _skeleton_blocks(runs, hits, ending, eb, eu, an, req, ctx, bar, tol):
    """Each run cut at its fixed points (entry, hits, the ending, the exit) into blocks, each block fitted to
    its length."""
    blocks = []
    for ri, r in enumerate(runs):
        fixed = [(r['a'], 'entry', None)]
        for h in [h for h in hits if r['a'] - 1e-6 <= h['at'] < r['b'] - 0.5]:
            if h['approach'] == 'none':
                continue
            if abs(h['at'] - r['a']) <= 1.0 / ctx['fps']:
                fixed[0] = (r['a'], 'hit', h)         # the music enters on the hit
            else:
                fixed.append((h['at'], 'hit', h))
        is_last = ri == len(runs) - 1
        if is_last and ending == 'song':
            E0 = r['b'] - eu
            fixed = [f for k, f in enumerate(fixed) if k == 0 or f[0] < E0 - 0.5 * bar]
            A, ak = fixed[-1][0], fixed[-1][1]
            free = ak == 'entry' and r['entry']['kind'] == 'fade'
            if not free:
                # the ending may start up to a bar early (the song then ends just before the video does), so the
                # music reaches it on its own bar lines instead of with an edit
                n = int(math.floor((E0 - A + tol) / bar))
                if n >= 1 and E0 - (A + n * bar) <= bar + 1e-6:
                    E0 = A + n * bar
            fixed.append((E0, 'ending', None))
        fixed.append((r['b'], 'exit', None))
        for (A, ak, ah), (B, bk, bh) in zip(fixed, fixed[1:]):
            D = B - A
            starts = r['entry']['kind'] if ak == 'entry' else ak
            blk = {'run': ri, 'start': A, 'end': B, 'starts': starts, 'hit': ah, 'ends': bk, 'end_hit': bh,
                   'n': 0, 'k': 0, 'x': 0.0, 'sigma': 1.0, 'gap': 0.0, 'approach': None, 'residual': 0.0,
                   'options': None}
            if ak == 'ending':
                blk['forced'] = list(range(eb, len(an['bars'])))
                blk['n'] = len(blk['forced'])
                blocks.append(blk)
                continue
            if bk in ('hit', 'ending'):
                kind = bh['kind'] if bh else 'bar'
                if starts == 'fade':                    # free phase: start mid-bar so the next point lands
                    n = int(math.floor((D + tol) / bar))
                    x = D - n * bar
                    blk.update(n=n, x=x if x >= 0.08 else 0.0, approach='entry phase')
                else:
                    tl = bh['tolerance_ms'] / 1000.0 if bh and bh['tolerance_ms'] is not None else tol
                    best, considered = _fit(D, an, bh['approach'] if bh else 'auto', kind, req['max_stretch'], tl)
                    blk.update(n=best['n'], k=best['k'], sigma=best['sigma'], gap=best['gap'],
                               approach=best['approach'], residual=best['residual'],
                               options=[{k2: (_r(v, 4) if isinstance(v, float) else v) for k2, v in c.items()}
                                        for c in considered])
            elif is_last and req['ending'] == 'stop':
                best, considered = _fit(D, an, 'auto', 'bar', req['max_stretch'], tol)
                if best['approach'] == 'join' and abs(best['residual']) > tol:
                    best = next((c for c in considered if c['approach'] in ('break', 'natural', 'stretch')), best)
                blk.update(n=best['n'], k=best['k'], sigma=best['sigma'], gap=best['gap'], approach=best['approach'],
                           residual=best['residual'], stop=True)
            else:
                blk['n'] = max(1, int(math.ceil((D - 1e-6) / bar)))
            blocks.append(blk)
    return blocks


def _skeleton_slots(blocks, an, bar, beat):
    """The bar, tail and head slots each block is filled with, in order, with their times and speeds."""
    slots = []
    for bi, blk in enumerate(blocks):
        prev = blocks[bi - 1] if bi else None
        restart = (blk['starts'] in ('fade', 'hard') or prev is None or prev['run'] != blk['run']
                   or prev['gap'] > 0)
        into = 'restart' if restart else 'anchor'
        t = blk['start']
        first = True
        kinds = None
        if blk['starts'] == 'hit' and blk['hit']:
            kinds = blk['hit']['kind'] if blk['hit'].get('song_at') is None else ('song_at', blk['hit']['song_at'])
        if blk.get('forced'):
            for j in blk['forced']:
                L0, L1 = an['bars'][j]
                slots.append({'kind': 'bar', 'block': bi, 'forced': j, 't0': t, 'dur': L1 - L0, 'sigma': 1.0,
                              'into': into if first else 'inner', 'kinds': None})
                t += L1 - L0
                first = False
            continue
        if blk['x'] > 0:
            slots.append({'kind': 'tail', 'x': blk['x'], 'block': bi, 't0': t, 'dur': blk['x'], 'sigma': 1.0,
                          'into': into, 'kinds': None})
            t += blk['x']
            first = False
        for _ in range(blk['n']):
            slots.append({'kind': 'bar', 'block': bi, 't0': t, 'dur': bar / blk['sigma'], 'sigma': blk['sigma'],
                          'into': into if first else 'inner', 'kinds': kinds if first else None})
            t += bar / blk['sigma']
            first = False
        if blk['k']:
            slots.append({'kind': 'head', 'k': blk['k'], 'block': bi, 't0': t, 'dur': blk['k'] * beat / blk['sigma'],
                          'sigma': blk['sigma'], 'into': into if first else 'inner', 'kinds': kinds if first else None})
    return slots


def _skeleton_slot_targets(slots, req, ctx):
    """Each slot's section, its energy target and how much of it is under speech."""
    talk = _talk(req, ctx)
    for sl in slots:
        mid = sl['t0'] + sl['dur'] / 2
        sec = next((s for s in req['sections'] if s['from'] <= mid < s['to']), None)
        sl['target'] = sec['energy'] if sec else None
        sl['section'] = req['sections'].index(sec) if sec else None
        a, b = sl['t0'], sl['t0'] + sl['dur']
        sl['speech'] = sum(max(0.0, min(b, y) - max(a, x)) for x, y in talk) / max(1e-6, b - a)


def _skeleton(req, ctx, an):
    o = req['options']
    a0, a1 = req['start'], req['end']
    tol = o['tolerance_ms'] / 1000.0
    bar, beat = an['bar_s'], an['beat_s']
    warnings = []
    drops, runs = _skeleton_runs(req, o, a0, a1, bar, warnings)
    hits = _skeleton_hits(req, drops, runs, a0, a1, warnings)
    ending, eb, eu = _skeleton_ending(req, runs, hits, an, bar, warnings)
    blocks = _skeleton_blocks(runs, hits, ending, eb, eu, an, req, ctx, bar, tol)
    slots = _skeleton_slots(blocks, an, bar, beat)
    _skeleton_slot_targets(slots, req, ctx)
    return {'runs': runs, 'blocks': blocks, 'slots': slots, 'hits': hits, 'ending': ending, 'ending_bar': eb,
            'warnings': warnings}


def _talk(req, ctx):
    import letitedit.sound.music as music
    if not req['options']['duck'] or not ctx['speech']:
        return []
    return music.merge([list(x) for x in ctx['speech']], gap=req['options']['merge_gap_s'], min_len=0.35)


# ============================================================================ the material: beam search over bar slots

def _join_matrix(an, fps):
    """Cost of playing bar j right after bar i (0 for i+1: the song playing on). A jump costs a base plus how
    unlike bar j is to the bar it replaces (i+1) and to bar i's own context, the chord at the seam, a different
    place in the 4/8-bar phrase, and the frame rounding of the join."""
    J = len(an['bars'])
    tz = np.asarray(an['timbre'], float)
    ch = np.asarray(an['chroma'], float)
    en = np.asarray(an['entry_chroma'], float)
    loud = np.asarray(an['loud_db'], float)
    sq = (tz ** 2).sum(1)
    dt = np.sqrt(np.maximum(0.0, sq[:, None] + sq[None, :] - 2 * tz @ tz.T)) / math.sqrt(tz.shape[1])
    dist = 0.5 * dt + 1.0 * (1 - ch @ ch.T) + 0.3 * np.abs(loud[:, None] - loud[None, :]) / 6.0
    seam = 1 - en @ en.T
    if an['coarse']:
        mis = np.zeros((J, J))
    else:
        off = an['phrase_offset']
        pos, pos8 = (np.arange(J) - off) % 4, (np.arange(J) - off) % 8
        mis = 0.5 * (pos[:, None] != pos[None, :]) + 0.2 * (pos8[:, None] != pos8[None, :])
    nxt = np.minimum(np.arange(J) + 1, J - 1)
    rep, seam_ij, mis_ij = dist[nxt, :].copy(), seam[nxt, :].copy(), mis[nxt, :].copy()
    ctxd = np.empty((J, J))
    ctxd[:, 1:] = dist[:, :-1]
    ctxd[:, 0] = rep[:, 0]
    rep[J - 1, :], seam_ij[J - 1, :], mis_ij[J - 1, :] = 0.6, 0.3, 0.3
    M = 0.8 + 0.6 * rep + 0.4 * ctxd + 0.5 * seam_ij + mis_ij
    M[J - 1, :] += 0.6           # out of the song's last bar: what follows it is the song's end
    M[:, 0] += 0.6               # into the song's first bar: the song starting over
    if not an['coarse']:
        starts = np.asarray([b[0] for b in an['bars']])
        ends = np.asarray([b[1] for b in an['bars']])
        q = (ends[:, None] - starts[None, :]) * fps
        M += 2.4 * (np.abs(q - np.round(q))) ** 2        # frame rounding of the join: up to 0.6 at half a frame
    idx = np.arange(J - 1)
    M[idx, idx + 1] = 0.0
    return M


def _kind_mask(kind, an, J):
    m = np.zeros(J, bool)
    if isinstance(kind, tuple):                       # ('song_at', t): the bar starting nearest that song time
        starts = np.asarray([b[0] for b in an['bars']])
        m[int(np.argmin(np.abs(starts - kind[1])))] = True
        return m, None
    if kind in ('downbeat', 'bar', 'beat', None):
        m[:] = True
        return m, None
    if kind == 'phrase':
        m[an['phrases']] = True
        return m, None
    if kind == 'drop':
        d = [x['bar'] for x in an.get('drops') or []]
        if d:
            m[d] = True
            return m, None
        m[[x['bar'] for x in an.get('drops_weak') or []]] = True
        return m, 'no clear drop in this song: "drop" hits use its biggest energy rise'
    raise ValueError(kind)


def _search(sk, an, req, ctx):
    """One song bar per slot by beam search; returns (bars per slot, search info)."""
    slots = sk['slots']
    J = len(an['bars'])
    o, rep = req['options'], req['repeat']
    W = o['beam']
    E = np.asarray(an['energy'], float)
    dens = _norm01(an['density'])
    starts = np.asarray([b[0] for b in an['bars']])
    ends = np.asarray([b[1] for b in an['bars']])
    nbeats = np.asarray([len(b) for b in an['bar_beats']])
    phr = np.zeros(J, bool)
    phr[an['phrases']] = True
    JOIN = _join_matrix(an, ctx['fps'])
    after_head = JOIN.copy()
    idx = np.arange(J - 1)
    after_head[idx, idx + 1] = 0.8 + 2.0             # after a short bar the next bar is always a join (and a metre change)
    in_range = np.asarray(an.get('usable') or [True] * J, bool)
    if req['song_range']:
        lo, hi = req['song_range']
        in_range = in_range & (starts >= lo - 1e-6) & (ends <= hi + 1e-6)
        if in_range.sum() < 2:
            raise ValueError(f'song_range {lo:g}-{hi:g} s holds fewer than 2 usable bars of the song')
    fps = ctx['fps']
    need = sum(1 for s in slots if s['kind'] == 'bar' and s.get('forced') is None)
    avail = int(in_range.sum())
    max_uses = rep['max_uses'] or max(2, int(math.ceil(need / max(1, avail))) + 1)
    relaxed, notes = [], []
    cost = np.zeros(1)
    bar = np.full(1, -1)
    head = np.zeros(1, bool)
    run0 = np.full(1, -1)
    uses = np.zeros((1, J), np.int16)
    last = np.full((1, J), -1e9)
    backs = []
    jj = np.arange(J)[None, :]
    for s, sl in enumerate(slots):
        allowed = in_range.copy()
        if sl['kind'] == 'tail':
            allowed &= ends - sl['x'] >= -1e-6
        if sl['kind'] == 'head':
            allowed &= nbeats > sl['k']
        if sl.get('forced') is not None:
            allowed = np.zeros(J, bool)
            allowed[sl['forced']] = True
        elif sl.get('kinds') is not None:
            km, kind_note = _kind_mask(sl['kinds'], an, J)
            if (km & allowed).any():
                allowed &= km
            else:
                kind_note = f'no bar of kind {sl["kinds"]} inside song_range at {_clock(sl["t0"])}: any bar used'
            if kind_note and kind_note not in notes:
                notes.append(kind_note)
        sc = np.zeros(J)
        if sl['target'] is not None:
            # under talking the music is dipped and its energy matters less than fewer edits
            sc += 4.0 * (1.0 - 0.6 * sl['speech']) * (E - sl['target']) ** 2
        if sl['speech'] > 0:
            sc += 1.0 * sl['speech'] * dens               # busy bars compete with talking
        restart = s == 0 or sl['into'] == 'restart'
        if restart and sl['kind'] == 'bar':
            sc += 0.3 * (~phr)                            # music entering prefers a phrase start
        if s == 0:
            sc += 0.4 * (np.arange(J) >= 8)               # the video's opening prefers the song's opening
        if sl.get('kinds') is not None and sl.get('forced') is None:
            # a hit bar placed on whole frames: prefer bars whose downbeat falls near a frame boundary there
            y = sl['t0'] * fps - starts * fps / sl['sigma']
            q = np.abs((y + 0.5) % 1.0 - 0.5)
            sc += 1.0 * (2 * q) ** 2
        for level in range(5):
            tot = cost[:, None] + sc[None, :]
            if not restart:
                tot = tot + np.where(head[:, None], after_head[np.maximum(bar, 0)], JOIN[np.maximum(bar, 0)])
            tot = tot + 0.6 * uses
            over = uses >= max_uses
            tot = np.where(over, np.inf, tot) if level < 2 else tot + 8.0 * over
            gapm = (sl['t0'] - last) < rep['min_gap_s']          # playing on into a recent bar counts too
            tot = np.where(gapm, np.inf, tot) if level < 1 else tot + 4.0 * gapm
            if not rep['loops'] and not restart:
                lo_b = np.maximum(run0, bar - rep['loop_bars'] + 1)
                loop = (jj >= lo_b[:, None]) & (jj <= bar[:, None]) & (bar[:, None] >= 0)
                tot = np.where(loop, np.inf, tot) if level < 3 else tot + 6.0 * loop
            if level < 4 or sl.get('forced') is not None:
                tot[:, ~allowed] = np.inf
            else:
                tot[:, ~allowed] += 20.0
                tot[:, ~in_range] = np.inf
            if np.isfinite(tot).any():
                if level:
                    what = ['minimum gap between uses of a bar', 'uses per bar', 'no back-to-back loops',
                            f"the hit's kind ({sl.get('kinds')})"][:level]
                    relaxed.append({'at': _r(sl['t0']), 'relaxed': what})
                break
        flat = tot.ravel()
        fin = np.flatnonzero(np.isfinite(flat))
        if len(fin) > 4 * W:
            fin = fin[np.argpartition(flat[fin], 4 * W)[:4 * W]]
        fin = fin[np.argsort(flat[fin], kind='stable')]
        cap = max(2, W // 12)
        keep, count = [], {}
        for i in fin:
            j = int(i % J)
            if count.get(j, 0) < cap:
                keep.append(int(i))
                count[j] = count.get(j, 0) + 1
                if len(keep) >= W:
                    break
        keep = np.asarray(keep, int)
        parent, nb = keep // J, keep % J
        natural = (not restart) & (nb == bar[parent] + 1) & ~head[parent]
        cost = flat[keep]
        uses = uses[parent].copy()
        uses[np.arange(len(keep)), nb] += 1
        last = last[parent].copy()
        last[np.arange(len(keep)), nb] = sl['t0']
        run0 = np.where(natural, run0[parent], nb)
        bar, head = nb, np.full(len(keep), sl['kind'] == 'head')
        backs.append((parent, nb))
    b = int(np.argmin(cost))
    total = float(cost[b])
    chosen = [0] * len(slots)
    for s in range(len(slots) - 1, -1, -1):
        parent, nb = backs[s]
        chosen[s] = int(nb[b])
        b = int(parent[b])
    # per-slot costs of the chosen path (for the report)
    for s, sl in enumerate(slots):
        j = chosen[s]
        sl['bar'] = j
        sl['energy_got'] = float(E[j])
        if s == 0 or sl['into'] == 'restart':
            sl['join_cost'] = None
        else:
            prev = slots[s - 1]
            m = after_head if prev['kind'] == 'head' else JOIN
            sl['join_cost'] = float(m[chosen[s - 1], j])
    return chosen, {'cost': _r(total, 2), 'max_uses': max_uses, 'relaxed': relaxed, 'notes': notes,
                    'about_cost': 'search cost of the whole arrangement (lower is smoother); not a probability'}


# ============================================================================ the layout: clips in whole frames

def _grid_label(an, u, tol=0.02, before=0.0):
    """What a song time is on the grid. `before`: how far before a grid line still counts as on it (a cut made
    just ahead of a downbeat's transient: the pre-roll plus a frame of rounding)."""
    def on(times):
        d = np.asarray(times) - u                     # > 0: the grid line is after u
        return bool(np.any((d >= -tol) & (d <= max(tol, before))))
    if on([b[0] for b in an['bars']] + [an['bars'][-1][1]]):
        return 'unit start' if an['coarse'] else 'downbeat'
    if an['beats']:
        return 'beat' if on(an['beats']) else 'between beats'
    return 'between units'


def _next_bar_start(an, u):
    starts = [b[0] for b in an['bars']] + [an['bars'][-1][1]]
    nxt = [s for s in starts if s >= u - 0.03]
    return nxt[0] if nxt else None


def _event_of(an, j, kind):
    if kind == 'drop':
        d = next((x for x in (an.get('drops') or []) + (an.get('drops_weak') or []) if x['bar'] == j), None)
        if d:
            return f"drop (+{d['jump_db']:.1f} dB)"
    if j in an['phrases']:
        return 'phrase start' if kind != 'drop' else 'phrase start (no drop there)'
    return 'downbeat' if not an['coarse'] else 'unit start (no steady beat)'


def _song_len(an):
    import letitedit.timeline.edit_script as es
    L = float(an['duration'])
    try:
        pd = float(es.probe(an['path'])['duration'] or 0)
        if pd > 0:
            L = min(L, pd)
    except Exception:  # noqa: BLE001 - the decoded length then
        pass
    return L


def _layout_song_clips(blocks, by_block, fps, o, runs, sk, tol_default):
    clips = []
    state = {'cur': None}

    def close(end, kind, fade=None):
        c = state['cur']
        c.update(end=end, end_kind=kind, fade_out=fade)
        clips.append(c)
        state['cur'] = None

    def new_clip(sl, tau, sigma, entry, bi):
        state['cur'] = {'slots': [sl], 'u_in': sl['u0'], 'tau_in': tau, 'sigma': sigma, 'entry': entry,
                        'block': bi, 'run': blocks[bi]['run']}

    for bi, blk in enumerate(blocks):
        ss = by_block.get(bi, [])
        if not ss:
            continue
        sigma = blk['sigma']
        run = runs[blk['run']]
        new_run = bi == 0 or blocks[bi - 1]['run'] != blk['run']
        if state['cur'] is not None and new_run:
            prun = runs[blocks[bi - 1]['run']]
            close(prun['b'], 'exit', prun['exit']['fade'])
        t_first = blk['start']
        if blk['starts'] == 'fade' and blk['ends'] in ('hit', 'ending'):
            # free phase: the material ends exactly on the next fixed point; the fragment before the first full
            # bar takes up the difference (the music fades in mid-bar)
            room = (blk['end'] - blk['gap']) - blk['start']
            if ss[0]['kind'] == 'tail':
                rest = sum(s['u1'] - s['u0'] for s in ss[1:]) / sigma
                u0 = ss[0]['u1'] - (room - rest) * sigma
                if u0 < 0:
                    t_first = blk['start'] - u0 / sigma
                    u0 = 0.0
                ss[0]['u0'] = u0
                if ss[0]['u1'] - ss[0]['u0'] < 1.5 / fps:
                    ss = ss[1:]
                    t_first = blk['end'] - blk['gap'] - sum(s['u1'] - s['u0'] for s in ss) / sigma
            else:
                dur = sum(s['u1'] - s['u0'] for s in ss) / sigma
                t_first = blk['end'] - blk['gap'] - dur
                if t_first < blk['start']:
                    ss[0]['u0'] += (blk['start'] - t_first) * sigma
                    t_first = blk['start']
        cur = state['cur']
        hit = blk.get('hit')
        tol = hit['tolerance_ms'] / 1000.0 if hit and hit.get('tolerance_ms') is not None else tol_default
        cont = False
        if cur is not None and ss[0]['into'] == 'anchor':
            last_sl = cur['slots'][-1]
            natural = (last_sl['kind'] != 'head' and ss[0]['kind'] != 'tail' and ss[0]['bar'] == last_sl['bar'] + 1
                       and abs(ss[0]['u0'] - last_sl['u1']) < 1e-6)
            if natural and abs(blk['start'] - cur['tau_end']) <= tol and abs(cur['sigma'] - sigma) < 1e-9:
                cont = True
        if cur is not None and not cont:
            pblk = blocks[bi - 1]
            if pblk['gap'] > 0:
                close(cur['tau_end'], 'break', o['break_fade_s'])
            else:
                close(blk['start'], 'join')
        tau = state['cur']['tau_end'] if cont else t_first
        if state['cur'] is None:
            if new_run or not any(c['run'] == blk['run'] for c in clips):
                entry = {'kind': 'hard' if blk['starts'] == 'hit' else run['entry']['kind'],
                         'fade': run['entry']['fade']}
            elif blocks[bi - 1]['gap'] > 0:
                entry = {'kind': 'hard', 'fade': None}
            else:
                entry = {'kind': 'join', 'fade': None}
        for k, sl in enumerate(ss):
            if state['cur'] is None:
                new_clip(sl, tau, sigma, entry, bi)
            elif k == 0 and cont:
                state['cur']['slots'].append(sl)
            else:
                p = state['cur']['slots'][-1]
                natural = (p['kind'] != 'head' and sl['bar'] == p['bar'] + 1 and abs(sl['u0'] - p['u1']) < 1e-6
                           and abs(state['cur']['sigma'] - sigma) < 1e-9)
                if natural:
                    state['cur']['slots'].append(sl)
                else:
                    close(tau, 'join')
                    new_clip(sl, tau, sigma, {'kind': 'join', 'fade': None}, bi)
            sl['tau0'] = tau
            tau += (sl['u1'] - sl['u0']) / sigma
            state['cur']['tau_end'] = tau
    if state['cur'] is not None:
        lr, lb = runs[-1], blocks[-1]
        if sk['ending'] == 'song':
            close(state['cur']['tau_end'], 'song_end', None)
        elif lb.get('stop'):
            close(state['cur']['tau_end'], 'stop', 2.0 / fps)
        else:
            close(lr['b'], 'exit', lr['exit']['fade'])
    return clips


def _layout_clip_frames(L, an, blocks, by_block, clips, fps, notes, o, runs):
    xf_s = (o['coarse_crossfade_s'] if an['coarse'] else
            o['weak_crossfade_s'] if an['beat_quality'] == 'weak' else o['crossfade_s'])
    hit_slots = {id(by_block[bi][0]): b['start'] for bi, b in enumerate(blocks)
                 if b.get('hit') is not None and by_block.get(bi)}
    for c in clips:
        s0, sg = c['slots'][0], c['sigma']
        c['u_in'] = s0['u0']
        if s0['kind'] == 'tail' or c['entry']['kind'] == 'fade':
            # a free start (it fades in): placed so its first hit lands, else its first downbeat
            hs = next((sl for sl in c['slots'] if id(sl) in hit_slots), None)
            if hs is not None:
                u_al, tau_al = hs['u0'], hit_slots[id(hs)]
            else:
                u_al = s0['u1'] if s0['kind'] == 'tail' else s0['u0']
                tau_al = c['tau_in'] + (u_al - c['u_in']) / sg
            W_in = int(round(c['u_in'] * fps / sg))
        else:
            u_al = c['u_in']
            back = 2 if c['entry']['kind'] == 'hard' else 0       # 2 frames of lead-in, faded up, before the downbeat
            W_in = int(math.floor((c['u_in'] - 0.006) * fps / sg + 1e-9)) - back
            tau_al = c['tau_in']
        W_in = max(0, W_in)
        M = int(round(tau_al * fps - (u_al * fps / sg - W_in)))
        run_a = int(round(runs[c['run']]['a'] * fps))
        if M < run_a:                                   # never before the music may start: start later in the song
            W_in += run_a - M
            M = run_a
        c.update(W_in=W_in, M=M, u_al=u_al, tau_al=tau_al)
        c['event_t'] = (M + (u_al * fps / sg - W_in)) / fps
    for i, c in enumerate(clips):
        nxt = clips[i + 1] if i + 1 < len(clips) else None
        if c['end_kind'] == 'join' and nxt is not None and nxt['run'] == c['run']:
            E = nxt['M']
        else:
            E = int(round(c['end'] * fps))
            if nxt is not None and nxt['run'] == c['run'] and E > nxt['M'] - 1:
                # a stop whose measured bars filled its silence: it still stops (a frame at least) before the hit
                E = nxt['M'] - 1
        wmax = int(math.floor(L * fps / c['sigma'] + 1e-6)) - 1      # one frame inside the file's end
        if c['W_in'] + (E - c['M']) > wmax:
            short = c['W_in'] + (E - c['M']) - wmax
            E -= short
            if c['end_kind'] == 'join':
                notes.append(f'the song runs out {short} frame(s) before the join at {_clock(E / fps)} (a short gap)')
        c['E'], c['n'] = E, E - c['M']
    kept = []
    for i, c in enumerate(clips):
        if c['n'] >= 3:
            kept.append(c)
            continue
        notes.append(f'a {max(0, c["n"])}-frame piece at {_clock(c["M"] / fps)} was too short to place and was left out')
        if kept and i + 1 < len(clips) and kept[-1]['E'] == c['M'] and c['E'] == clips[i + 1]['M']:
            p = kept[-1]
            p['E'] = clips[i + 1]['M']
            p['n'] = p['E'] - p['M']
    clips = kept
    for i, c in enumerate(clips):
        p = clips[i - 1] if i else None
        c['chained'] = bool(p is not None and p['E'] == c['M'] and p['run'] == c['run'] and p['end_kind'] == 'join')
        c['xfade'] = 0
        if c['chained']:
            nt = max(2, int(round(xf_s * fps)))
            limit = min(c['W_in'], p['n'] - 1, c['n'] - 1)
            if an['coarse']:
                limit = min(limit, int(0.4 * min(p['n'], c['n'])))
            c['xfade'] = max(0, min(nt, limit))
        sg = c['sigma']
        c['in_s'] = (c['W_in'] - c['xfade']) * sg / fps
        c['out_s'] = (c['W_in'] + c['n']) * sg / fps
        c['start_s'] = (c['M'] - c['xfade']) / fps
        c['end_s'] = c['E'] / fps
    return clips, xf_s


def _layout_joins(an, blocks, by_block, clips, fps):
    joins = []
    for i, c in enumerate(clips):
        if not c['chained']:
            continue
        p = clips[i - 1]
        out_song = (p['W_in'] + p['n']) * p['sigma'] / fps
        nb = _next_bar_start(an, out_song)
        t_nb = (p['M'] + (nb * fps / p['sigma'] - p['W_in'])) / fps if nb is not None else None
        grid = c['event_t'] - t_nb if t_nb is not None and not an['coarse'] else None   # no grid without a beat
        b0 = blocks[c['block']]
        s0 = c['slots'][0]
        first_of_block = by_block.get(c['block'], [None])[0] is s0
        if first_of_block and b0['starts'] == 'hit':
            why = f"lands hit {b0['hit']['index'] + 1}"
        elif first_of_block and b0['starts'] == 'ending':
            why = "the song's own ending"
        elif s0.get('section') is not None and p['slots'][-1].get('section') != s0.get('section'):
            why = 'section change'
        else:
            why = 'material (energy, length or repeat limits)'
        j = {'at': _r(c['M'] / fps, 4), 'from_song': _r(out_song, 4), 'to_song': _r(c['u_al'], 4),
             'from_on': _grid_label(an, out_song, before=1.0 / fps + 0.012), 'to_on': _grid_label(an, c['u_al']),
             'from_bar': p['slots'][-1]['bar'] + 1, 'to_bar': s0['bar'] + 1,
             'crossfade_s': _r(c['xfade'] / fps, 4), 'event_at': _r(c['event_t'], 4),
             'grid_error_ms': _ms(grid), 'why': why, 'cost': _r(s0.get('join_cost'), 2)}
        if t_nb is not None and t_nb < c['M'] / fps - 0.004:
            j['flam_risk'] = (f"the outgoing piece's own downbeat (song {_clock(nb)}) plays "
                              f"{(c['M'] / fps - t_nb) * 1000:.0f} ms before the cut")
        joins.append(j)
    return joins


def _layout_hits(an, bars, blocks, by_block, clips, fps, req):
    slot_clip = {id(sl): c for c in clips for sl in c['slots']}
    hits_out = []
    for h in req['hits']:
        rec = {'hit': h['index'] + 1, 'at': _r(h['at'], 4), 'kind': h['kind'], 'approach': h['approach']}
        if h.get('name'):
            rec['name'] = h['name']
        if h.get('skipped'):
            rec['by'] = 'skipped: ' + h['skipped']
            hits_out.append(rec)
            continue
        bi = next((i for i, b in enumerate(blocks) if b.get('hit') is h), None)
        if bi is not None and by_block.get(bi):
            sl = by_block[bi][0]
            c = slot_clip.get(id(sl))
            if c is None:
                rec['by'] = 'skipped: its piece was too short to place'
                hits_out.append(rec)
                continue
            u = sl['u0']
            t = (c['M'] + (u * fps / c['sigma'] - c['W_in'])) / fps
            prev_blk = blocks[bi - 1] if bi and blocks[bi - 1]['run'] == blocks[bi]['run'] else None
            if c['slots'][0] is not sl:
                by = 'natural'
            elif prev_blk is None:
                by = 'entry'
            elif prev_blk['gap'] > 0:
                by = 'break'
            elif abs(prev_blk['sigma'] - 1) > 1e-9:
                by = 'stretch'
            else:
                by = 'join'
            rec.update(by=by, song=_r(u, 4), bar=sl['bar'] + 1, event=_event_of(an, sl['bar'], h['kind']),
                       lands_at=_r(t, 4), error_ms=_ms(t - h['at']))
            if prev_blk is not None:
                rec['fit'] = {'approach': prev_blk['approach'], 'bars': prev_blk['n'], 'extra_beats': prev_blk['k'],
                              'speed': _r(prev_blk['sigma'], 5), 'stop_s': _r(prev_blk['gap'], 3),
                              'trimmed_ms': _ms(prev_blk['residual']) if prev_blk['approach'] == 'join' else 0.0}
                if abs(prev_blk['sigma'] - 1) > 1e-9:
                    rec['fit']['pitch_cents'] = _r(1200 * math.log2(prev_blk['sigma']), 1)
                if prev_blk.get('options'):
                    rec['options_considered'] = prev_blk['options']
            ci = clips.index(c)
            pc = clips[ci - 1] if ci and clips[ci - 1]['run'] == c['run'] else None
            if by in ('join', 'stretch', 'break') and pc is not None:
                # where the music's own grid would put a downbeat near the hit if nothing were edited
                best = None
                for d0, _d1 in bars:
                    tt = (pc['M'] + (d0 * fps / pc['sigma'] - pc['W_in'])) / fps
                    if best is None or abs(tt - h['at']) < abs(best - h['at']):
                        best = tt
                if best is not None:
                    rec['without_edit'] = {'nearest_downbeat': _r(best, 3), 'off_ms': _ms(best - h['at']),
                                           'note': 'a picture cut moved there would land on the beat with no edit '
                                                   'in the music'}
        else:
            km, _ = _kind_mask(h['kind'], an, len(bars))
            best = None
            for c in clips:
                for j in np.flatnonzero(km):
                    u = bars[j][0]
                    if c['in_s'] - 1e-6 <= u <= c['out_s']:
                        tt = (c['M'] + (u * fps / c['sigma'] - c['W_in'])) / fps
                        if best is None or abs(tt - h['at']) < abs(best[0] - h['at']):
                            best = (tt, u, int(j))
            if best:
                rec.update(by='none (reported only)', song=_r(best[1], 4), bar=best[2] + 1,
                           event=_event_of(an, best[2], h['kind']), lands_at=_r(best[0], 4),
                           error_ms=_ms(best[0] - h['at']))
            else:
                rec['by'] = 'none: no event of this kind in the music'
        hits_out.append(rec)
    return hits_out


def _layout(sk, an, req, ctx):
    """Clips of the song in whole frames: where each starts on the timeline (M), its first song frame (W_in, in
    frames of the clip's own speed), its length (n), the crossfade into it; the joins and where each hit lands."""
    fps = ctx['fps']
    o = req['options']
    bars, bb = an['bars'], an['bar_beats']
    L = _song_len(an)
    slots, blocks, runs = sk['slots'], sk['blocks'], sk['runs']
    tol_default = o['tolerance_ms'] / 1000.0
    notes = []
    for sl in slots:
        j = sl['bar']
        if sl['kind'] == 'bar':
            sl['u0'], sl['u1'] = bars[j]
        elif sl['kind'] == 'tail':
            sl['u0'], sl['u1'] = max(0.0, bars[j][1] - sl['x']), bars[j][1]
        else:
            sl['u0'] = bars[j][0]
            sl['u1'] = bb[j][sl['k']] if sl['k'] < len(bb[j]) else bars[j][1]
    by_block = {}
    for sl in slots:
        by_block.setdefault(sl['block'], []).append(sl)
    for bi, blk in enumerate(blocks):
        if blk.get('forced') and bi in by_block:
            by_block[bi][-1]['u1'] = L              # the song's own ending, decay included
    clips = _layout_song_clips(blocks, by_block, fps, o, runs, sk, tol_default)
    # frames
    clips, xf_s = _layout_clip_frames(L, an, blocks, by_block, clips, fps, notes, o, runs)
    # joins
    joins = _layout_joins(an, blocks, by_block, clips, fps)
    # hits
    hits_out = _layout_hits(an, bars, blocks, by_block, clips, fps, req)
    return {'clips': clips, 'joins': joins, 'hits': hits_out, 'notes': notes, 'song_len': L,
            'crossfade_s': xf_s}


def _arrangement_repeats(clips, an, req):
    """Bars used more than once, the shortest gap between two uses, and back-to-back repeats of the same block of
    bars (an audible loop the edit makes)."""
    seq = []                                        # (timeline start, bar, clip index) of every full bar played
    for ci, c in enumerate(clips):
        for sl in c['slots']:
            if sl['kind'] == 'bar':
                seq.append((sl.get('tau0', 0.0), sl['bar'], ci))
    uses, gaps = {}, []
    for t, j, _ in seq:
        if j in uses:
            gaps.append(t - uses[j][-1])
        uses.setdefault(j, []).append(t)
    loops = []
    bars_only = [j for _, j, _ in seq]
    i = 0
    while i < len(seq):
        found = None
        for Lb in range(1, int(req['repeat']['loop_bars']) + 1):
            if i + 2 * Lb <= len(seq) and bars_only[i:i + Lb] == bars_only[i + Lb:i + 2 * Lb]:
                found = Lb
                break
        if found:
            loops.append({'at': _r(seq[i + found][0], 3), 'bars': f'{bars_only[i] + 1}-{bars_only[i + found - 1] + 1}',
                          'length_bars': found, 'first_play': _r(seq[i][0], 3)})
            i += 2 * found
        else:
            i += 1
    return {'bars_played': len(seq), 'distinct_bars': len(uses), 'bars_used_more_than_once':
            sum(1 for v in uses.values() if len(v) > 1), 'max_uses': max((len(v) for v in uses.values()), default=0),
            'shortest_reuse_gap_s': _r(min(gaps), 1) if gaps else None, 'back_to_back_loops': loops}
