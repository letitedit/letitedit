"""The gain envelope, the edit ops and the preview (a picture of the plan, a listen).

Part of `soundtrack` (letitedit/sound/soundtrack.py), which imports every name here back,
so `soundtrack.X` is the same object it always was.
"""
from __future__ import annotations
import math
import uuid
from pathlib import Path
import numpy as np
from letitedit.sound.soundtrack_base import (  # noqa: E402
    MSR, _clock, _decode, _r
)
from letitedit.sound.soundtrack_request import (  # noqa: E402
    _range_lufs
)
from letitedit.sound.soundtrack_arrange import (  # noqa: E402
    _talk
)


# ============================================================================ the gain envelope

def _energy_level(e, lv):
    pts = [(0.2, lv['low']), (0.55, lv['mid']), (0.9, lv['high'])]
    if e <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if e <= x1:
            return y0 + (y1 - y0) * (e - x0) / (x1 - x0)
    return pts[-1][1]


def _value_at(pts, t):
    import letitedit.sound.music as music
    return music.value_at(pts, t) if pts else 0.0


def _placed_loudness(an, clips):
    """dB the song's placed material is louder (+) or quieter (-) than the whole song, by its per-bar loudness
    weighted by the seconds of each bar placed (song seconds in_s..out_s of each clip) against every bar weighted by
    its length. None when the bars or the clips' song ranges are unknown."""
    bars, loud = an.get('bars') or [], an.get('loud_db') or []
    if not bars or len(bars) != len(loud):
        return None
    starts = np.asarray([bar[0] for bar in bars], float)
    ends = np.asarray([bar[1] for bar in bars], float)
    power = 10 ** (np.asarray(loud, float) / 10)
    used = np.zeros(len(bars))
    for clip in clips:
        a, b = clip.get('in_s'), clip.get('out_s')
        if a is None or b is None:
            return None
        used += np.clip(np.minimum(ends, b) - np.maximum(starts, a), 0, None)
    lengths = np.clip(ends - starts, 0, None)
    if used.sum() <= 0 or lengths.sum() <= 0:
        return None
    return float(10 * np.log10((power * used).sum() / used.sum()) - 10 * np.log10((power * lengths).sum() / lengths.sum()))


def _envelope(req, ctx, an, sk, lay):
    """The music level over the whole span (dB relative to the dialogue, with ramps), the gain that brings the song
    to the dialogue's loudness, and each clip's effects (gain keyframes, fades)."""
    o, lv = req['options'], req['levels']
    fps = ctx['fps']
    a0, a1 = req['start'], req['end']
    warnings = []
    if ctx['dialogue_lufs'] > -70:
        ref, ref_from = ctx['dialogue_lufs'], 'the dialogue (measured over detected speech)'
    else:
        ref, ref_from = -14.0, 'the export loudness (-14 LUFS): nobody talks'
    talk = _talk(req, ctx)
    marks = []
    for k, s in enumerate(req['sections']):
        v = s['level'] if s['level'] is not None else (lv['none'] if s['energy'] is None
                                                       else _energy_level(s['energy'], lv))
        marks.append((max(a0, s['from']), min(a1, s['to']), float(v), 'section'))
    for x, y in talk:
        marks.append((x, y, lv['talk'], 'talk'))
    protects = []
    for p in req['protect']:
        if p['mode'] != 'duck_deep' or p['to'] <= a0 or p['from'] >= a1:
            continue
        margin = p['level'] if p['level'] is not None else lv['duck_deep']
        nat = _range_lufs(ctx['power'], p['from'], p['to']) if ctx['power_ok'] or ctx['power'].any() else -70.0
        if nat > -60:
            rel = (nat + margin) - ref
            how = f'{margin:+.0f} LU against the natural sound there ({nat:.1f} LUFS)'
        else:
            rel = lv['talk'] + margin + 6.0
            how = (f'the natural sound there could not be measured (silent or unknown): {-(margin + 6.0):.0f} dB under '
                   'the talk level')
        rel = min(rel, lv['talk'] - 6.0)
        marks.append((max(a0, p['from']), min(a1, p['to']), rel, 'protect'))
        protects.append({'from': p['from'], 'to': p['to'], 'mode': 'duck_deep', 'natural_lufs': _r(nat, 1),
                         'music_level_db': _r(rel, 1), 'how': how})
    for p in req['protect']:
        if p['mode'] == 'drop_out' and p['to'] > a0 and p['from'] < a1:
            nat = _range_lufs(ctx['power'], p['from'], p['to'])
            protects.append({'from': p['from'], 'to': p['to'], 'mode': 'drop_out', 'natural_lufs': _r(nat, 1),
                             'music': 'off (faded out before it, back after it)'})
    protects.sort(key=lambda x: x['from'])
    edges = sorted({a0, a1, *[m[0] for m in marks], *[m[1] for m in marks]})
    edges = [e for e in edges if a0 - 1e-9 <= e <= a1 + 1e-9]
    segs = []
    for x, y in zip(edges, edges[1:]):
        if y - x < 1e-6:
            continue
        mid = (x + y) / 2
        act = [m for m in marks if m[0] <= mid < m[1]]
        sec = next((m for m in act if m[3] == 'section'), None)
        cands = [(sec[2] if sec else lv['none'], 'section' if sec else 'none')] + \
                [(m[2], m[3]) for m in act if m[3] != 'section']
        v, why = min(cands, key=lambda c: c[0])
        if segs and abs(segs[-1][2] - v) < 1e-9 and segs[-1][3] == why:
            segs[-1][1] = y
        else:
            segs.append([x, y, v, why])
    hit_times = [h['at'] for h in sk['hits']]
    pts = [(segs[0][0], segs[0][2])]
    for i in range(1, len(segs)):
        va, vb, T = segs[i - 1][2], segs[i][2], segs[i][0]
        wa, wb = segs[i - 1][3], segs[i][3]
        if abs(va - vb) < 1e-9:
            continue
        at_hit = any(abs(T - h) <= 0.15 for h in hit_times)
        if vb < va:
            if wb in ('talk', 'protect'):
                t1 = T - o['preroll_s']
                t0 = t1 - o['attack_s']
            elif at_hit:
                t0, t1 = T - 1.0 / fps, T
            else:
                t0, t1 = T - o['section_ramp_s'] / 2, T + o['section_ramp_s'] / 2
        else:
            if wa in ('talk', 'protect'):
                t0 = T + o['hold_s']
                t1 = t0 + o['release_s']
            elif at_hit:
                t0, t1 = T - 1.0 / fps, T
            else:
                t0, t1 = T - o['section_ramp_s'] / 2, T + o['section_ramp_s'] / 2
        lo = max(pts[-1][0], segs[i - 1][0])
        hi = segs[i][1]
        t0 = min(max(t0, lo), hi)
        t1 = min(max(t1, t0), hi)
        if t1 - t0 < 1e-6 and t1 - 1.0 / fps > lo + 1e-6:
            # no room left for the ramp (a short stretch after it): a one-frame step at its end, so the level held
            # until then stays (merged onto one point, the curve ramped all the way from the last change instead:
            # music rising 3 dB across 14 s of talk)
            t0 = t1 - 1.0 / fps
        pts += [(t0, va), (t1, vb)]
    pts.append((segs[-1][1], segs[-1][2]))
    clean = []
    for t, v in pts:
        if clean and abs(clean[-1][0] - t) < 1e-6:
            clean[-1] = (t, v)
        else:
            clean.append((t, v))
    pts = clean
    song_lufs = an.get('integrated_lufs')
    if song_lufs is None or song_lufs <= -70:
        song_lufs = float(np.median(an['loud_db'])) - 3.0
    placed_db = _placed_loudness(an, lay['clips']) if o.get('match_placed_loudness') else None
    if placed_db is not None:
        song_lufs += placed_db
    base = max(-30.0, min(15.0, ref - song_lufs))
    peak_room = o['peak_ceiling_dbfs'] - (an.get('peak_dbfs') or 0.0) - max(v for _, v in pts)
    capped = None
    if base > peak_room:
        capped = base - peak_room
        warnings.append(f'the music is held {capped:.1f} dB under the level asked for: the song peaks at '
                        f'{an.get("peak_dbfs"):.1f} dBFS and the loudest part asked for would reach '
                        f'{o["peak_ceiling_dbfs"] + capped:+.1f} dBFS on its own (options.peak_ceiling_dbfs)')
        base = peak_room
    import letitedit.sound.music as music
    for c in lay['clips']:
        t0, t1 = c['start_s'], c['end_s']
        keys = [(0.0, base + _value_at(pts, t0))]
        keys += [(t - t0, base + v) for t, v in pts if t0 + 1e-6 < t < t1 - 1e-6]
        keys.append((t1 - t0, base + _value_at(pts, t1)))
        keys = music._simplify([(round(a, 3), round(b, 2)) for a, b in keys])
        effects = []
        if max(k[1] for k in keys) - min(k[1] for k in keys) < 0.05:
            effects.append({'gain': round(keys[0][1], 2)})
        else:
            effects.append({'gain': {'keys': [[a, b] for a, b in keys]}})
        length = t1 - t0
        e = c['entry']
        fin = None
        if not c['chained']:
            if e['kind'] == 'fade':
                fin = e['fade'] if e.get('fade') else o['fade_in_s']
            else:
                fin = 2.0 / fps
        fout = c.get('fade_out')
        if fin:
            fin = min(fin, length / 2)
            effects.append({'fade_in_audio': round(max(1.0 / fps, fin), 3)})
            c['fade_in_s'] = fin
        if fout:
            fout = min(fout, length / 2)
            effects.append({'fade_out_audio': round(max(1.0 / fps, fout), 3)})
            c['fade_out_s'] = fout
        c['effects'] = effects
    return {'curve': [[_r(t, 3), _r(v, 2)] for t, v in pts], 'base_gain_db': _r(base, 2), 'reference_lufs': _r(ref, 1),
            'reference': ref_from, 'song_lufs': _r(song_lufs, 1), 'peak_capped_db': _r(capped, 1),
            **({'placed_vs_song_db': _r(placed_db, 1)} if placed_db is not None else {}),
            'segments': [{'from': _r(a, 3), 'to': _r(b, 3), 'level_db': _r(v, 1), 'why': w} for a, b, v, w in segs],
            'protect': protects, 'talk_spans': [[_r(a, 3), _r(b, 3)] for a, b in talk], 'warnings': warnings}


# ============================================================================ edit ops in the existing vocabulary

def _changes(req, ctx, an, lay, plan_id):
    track = req['track']
    fps = ctx['fps']
    ops = []
    if not ctx['track_exists']:
        ops.append({'op': 'add_track', 'name': track, 'kind': 'audio'})
    else:
        for iid in ctx['track_items']:
            ops.append({'op': 'delete', 'id': iid, 'close_gap': False})
        if ctx.get('track_gain') not in (None, 0, 0.0) or ctx.get('track_duck'):
            # the envelope sets the level; the editor's auto-duck or a track volume would stack on top of it
            ops.append({'op': 'track', 'name': track, 'gain': 0.0, 'duck': None})
    title = Path(an['path']).stem
    taken = set(ctx['ids'])
    prev = None
    for k, c in enumerate(lay['clips'], 1):
        iid = f'st{plan_id[:6]}-{k:02d}'
        while iid in taken:
            iid = f'st{uuid.uuid4().hex[:6]}-{k:02d}'
        taken.add(iid)
        c['id'] = iid
        b0, b1 = c['slots'][0]['bar'] + 1, c['slots'][-1]['bar'] + 1
        item = {'id': iid, 'clip': an['path'], 'in': round(c['in_s'], 6), 'out': round(c['out_s'], 6),
                'name': f'{title[:40]} (bars {b0}-{b1})', 'effects': c['effects']}
        if abs(c['sigma'] - 1) > 1e-9:
            item['speed'] = round(c['sigma'], 6)
        if c['chained'] and prev is not None:
            if c['xfade']:
                item['transition'] = {'type': 'dissolve', 'len': round(c['xfade'] / fps, 6), 'audio': 'crossfade'}
            ops.append({'op': 'insert', 'track': track, 'after': prev, 'item': item})
        else:
            ops.append({'op': 'insert', 'track': track, 'at': round(c['start_s'], 6), 'item': item})
        prev = iid
    return ops


# ============================================================================ preview: a picture of the plan, a listen

def _graph(plan, lay, env, an, out, measured=None):
    from PIL import Image, ImageDraw
    a0, a1 = plan['music']['start'], plan['music']['end']
    span = max(1.0, a1 - a0)
    W, H = 1500, 560 if measured is None else 720
    im = Image.new('RGB', (W, H), (22, 22, 26))
    d = ImageDraw.Draw(im)
    x0, x1 = 70, W - 20

    def X(t):
        return x0 + (t - a0) / span * (x1 - x0)
    colors = {'low': (70, 120, 220), 'mid': (230, 170, 50), 'high': (230, 70, 60), 'none': (90, 90, 100)}
    # lane 1: sections, speech, protected ranges, hits
    d.text((8, 12), 'plan', fill=(200, 200, 200))
    for s in plan['sections']:
        d.rectangle((X(s['from']), 10, X(s['to']), 40), fill=colors.get(s['energy_asked'], (120, 120, 120)))
        d.text((X(s['from']) + 3, 14), str(s.get('name') or s['energy_asked']), fill=(255, 255, 255))
    for a, b in env['talk_spans']:
        d.rectangle((X(a), 44, X(b), 52), fill=(90, 180, 255))
    for p in env['protect']:
        col = (255, 140, 0) if p['mode'] == 'duck_deep' else (255, 255, 255)
        d.rectangle((X(p['from']), 56, X(p['to']), 66), outline=col, width=2)
        d.text((X(p['from']) + 2, 68), p['mode'], fill=col)
    for h in plan['hits']:
        if 'lands_at' not in h:
            continue
        d.line((X(h['at']), 8, X(h['at']), H - 30), fill=(255, 80, 200), width=1)
        d.text((X(h['at']) + 3, 82), f"{h['kind']} {h.get('error_ms', 0):+.0f}ms", fill=(255, 120, 220))
    # lane 2: song time vs timeline time
    top, bot = 110, 300
    L = an['duration']
    d.text((8, top), 'song', fill=(200, 200, 200))
    d.rectangle((x0, top, x1, bot), outline=(60, 60, 70))
    uses = {}
    for c in lay['clips']:
        for sl in c['slots']:
            uses[sl['bar']] = uses.get(sl['bar'], 0) + 1
    for c in lay['clips']:
        t0, t1 = c['M'] / plan['fps'], c['E'] / plan['fps']
        s0 = c['W_in'] * c['sigma'] / plan['fps']
        s1 = s0 + (t1 - t0) * c['sigma']
        rep = any(uses.get(sl['bar'], 0) > 1 for sl in c['slots'])
        col = (240, 200, 90) if rep else (120, 220, 140)
        d.line((X(t0), bot - s0 / L * (bot - top), X(t1), bot - s1 / L * (bot - top)), fill=col, width=3)
    for j in plan['joins']:
        d.line((X(j['at']), bot, X(j['at']), bot + 6), fill=(250, 250, 250))
    # lane 3: the level (dB relative to the dialogue) and the energy of the material
    top, bot = 320, 520
    d.text((8, top), 'level', fill=(200, 200, 200))
    d.rectangle((x0, top, x1, bot), outline=(60, 60, 70))

    def Y(v):
        return top + (0 - max(-40, min(0, v))) / 40 * (bot - top)
    for db in (-6, -12, -18, -24, -30):
        d.line((x0, Y(db), x1, Y(db)), fill=(45, 45, 52))
        d.text((x0 - 34, Y(db) - 6), f'{db}', fill=(140, 140, 150))
    curve = env['curve']
    d.line([(X(t), Y(v)) for t, v in curve], fill=(240, 240, 240), width=2)
    for c in lay['clips']:
        for sl in c['slots']:
            if 'tau0' not in sl:
                continue
            e = an['energy'][sl['bar']]
            ty = bot - e * (bot - top) * 0.35
            d.line((X(sl['tau0']), ty, X(sl['tau0'] + (sl['u1'] - sl['u0']) / c['sigma']), ty), fill=(230, 120, 60))
    if measured:
        top2, bot2 = 540, 700
        d.text((8, top2), 'measured', fill=(200, 200, 200))
        d.rectangle((x0, top2, x1, bot2), outline=(60, 60, 70))

        def Y2(v):
            return top2 + (-10 - max(-60, min(-10, v))) / 50 * (bot2 - top2)
        for name, col in (('music', (255, 150, 60)), ('other', (90, 180, 255))):
            ser = measured.get(name) or []
            if len(ser) > 1:
                d.line([(X(t), Y2(v)) for t, v in ser[::2]], fill=col, width=2)
        d.text((x0 + 4, top2 + 4), 'music (orange) / everything else (blue), momentary LUFS', fill=(170, 170, 170))
    for k in range(int(a0 // 30) * 30, int(a1) + 1, 30):
        if k >= a0:
            d.text((X(k) - 10, H - 22), _clock(k)[:-2], fill=(150, 150, 160))
    im.save(out)
    return str(out)


def _render_bed(lay, env, an, fps, out, sr=MSR):
    """The planned music bed alone, mixed here the way the timeline will play it (gain keys, fades, crossfades), as
    an mp3 for listening before anything is applied. Returns the path."""
    import letitedit.sound.av_tools as av_tools
    y = _decode(an['path'], sr, 2)
    clips = lay['clips']
    if not clips:
        return None
    total = int(math.ceil(max(c['E'] for c in clips) / fps * sr)) + sr
    buf = np.zeros((total, 2), np.float32)
    pts = env['curve']
    base = env['base_gain_db']
    for c in clips:
        sg = c['sigma']
        i0 = int(round(c['in_s'] * sr))
        i1 = int(round(c['out_s'] * sr))
        seg = y[max(0, i0):max(0, min(len(y), i1))].astype(np.float32)
        if abs(sg - 1) > 1e-9 and len(seg) > 2:
            n_out = int(round(len(seg) / sg))
            src = np.linspace(0, len(seg) - 1, n_out)
            seg = np.stack([np.interp(src, np.arange(len(seg)), seg[:, ch]) for ch in (0, 1)], 1).astype(np.float32)
        start = int(round(c['start_s'] * sr))
        n = len(seg)
        t = c['start_s'] + np.arange(n) / sr
        db = base + np.interp(t, [p[0] for p in pts], [p[1] for p in pts])
        g = (10 ** (db / 20)).astype(np.float32)
        nx = int(round(c['xfade'] / fps * sr))
        if nx > 0:
            ramp = np.sin(np.linspace(0, np.pi / 2, nx)).astype(np.float32)
            g[:nx] *= ramp
        if c.get('fade_in_s') and not c['chained']:
            k = int(round(c['fade_in_s'] * sr))
            g[:k] *= (10 ** (np.linspace(-60, 0, k) / 20)).astype(np.float32)
        if c.get('fade_out_s'):
            k = int(round(c['fade_out_s'] * sr))
            g[n - k:] *= (10 ** (np.linspace(0, -60, k) / 20)).astype(np.float32)
        nxt = next((d for d in clips if d['chained'] and d['M'] == c['E'] and d['xfade']), None)
        if nxt is not None:
            k = int(round(nxt['xfade'] / fps * sr))
            if k:
                g[n - k:] *= np.cos(np.linspace(0, np.pi / 2, k)).astype(np.float32)
        seg = seg * g[:, None]
        lo, hi = max(0, start), min(total, start + n)
        if hi > lo:
            buf[lo:hi] += seg[lo - start:hi - start]
    av_tools._write_audio(buf, sr, out)
    return str(out)
