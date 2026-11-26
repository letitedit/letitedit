"""The request typed and checked, and the project it scores.

Part of `soundtrack` (letitedit/sound/soundtrack.py), which imports every name here back,
so `soundtrack.X` is the same object it always was.
"""
from __future__ import annotations
import math
import os
import numpy as np
from letitedit.sound.soundtrack_base import (  # noqa: E402
    APPROACHES, ENDINGS, ENERGY_WORDS, ENTRIES, HIT_KINDS, LEVELS, OPTIONS, REPEAT, _clock, _file_id, _sec, _span
)


# ============================================================================ the request (typed, validated)

def _energy_of(v, where):
    if v is None:
        return None, 'none'
    if isinstance(v, str):
        k = v.strip().lower()
        if k in ENERGY_WORDS:
            return ENERGY_WORDS[k], ('mid' if k == 'medium' else k)
        try:
            v = float(k)
        except ValueError:
            raise ValueError(f'{where}: energy is low | mid | high or a level 0-1, not {v!r}') from None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f'{where}: energy is low | mid | high or a level 0-1, not {v!r}')
    v = float(v)
    if not 0.0 <= v <= 1.0:
        raise ValueError(f'{where}: an energy level is between 0 and 1, not {v}')
    return v, ('low' if v < 0.375 else 'mid' if v < 0.725 else 'high')


def _level_value(v, levels, where):
    if v is None:
        return None
    if isinstance(v, str):
        if v in levels:
            return float(levels[v])
        try:
            return float(v)
        except ValueError:
            raise ValueError(f'{where}: level is dB (relative to the dialogue) or one of {", ".join(levels)}; '
                             f'not {v!r}') from None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f'{where}: level is a number of dB, not {v!r}')
    return float(v)


def _parse_sections(raw, levels):
    out = []
    if raw is not None and not isinstance(raw, (list, tuple)):
        raise ValueError('sections is a list of {from, to, energy: low | mid | high | 0-1, level?: dB, name?}')
    for n, s in enumerate(raw or [], 1):
        where = f'sections[{n}]'
        if isinstance(s, (list, tuple)):
            if len(s) < 2:
                raise ValueError(f'{where}: [from, to, energy?]; got {s!r}')
            s = {'from': s[0], 'to': s[1], **({'energy': s[2]} if len(s) > 2 else {})}
        if not isinstance(s, dict):
            raise ValueError(f'{where} is {{from, to, energy}}; got {s!r}')
        extra = sorted(set(s) - {'from', 'to', 'energy', 'level', 'name'})
        if extra:
            raise ValueError(f'{where}: unknown {", ".join(extra)} (a section is {{from, to, energy, level?, name?}})')
        a, b = _sec(s.get('from'), f'{where}.from'), _sec(s.get('to'), f'{where}.to')
        if a is None or b is None or b <= a:
            raise ValueError(f'{where}: needs from < to; got {s!r}')
        e, word = _energy_of(s.get('energy'), where)
        out.append({'from': a, 'to': b, 'energy': e, 'word': word,
                    'level': _level_value(s.get('level'), levels, where), 'name': s.get('name')})
    out.sort(key=lambda x: x['from'])
    for x, y in zip(out, out[1:]):
        if y['from'] < x['to'] - 1e-6:
            raise ValueError(f"sections overlap: {_span(x['from'], x['to'])} and {_span(y['from'], y['to'])}")
    return out


def _parse_hits(raw):
    out = []
    if raw is not None and not isinstance(raw, (list, tuple)):
        raise ValueError('hits is a list of {at, kind: downbeat | bar | phrase | drop | beat, approach?}')
    alias = {'downbeats': 'downbeat', 'bars': 'bar', 'phrases': 'phrase', 'phrase_start': 'phrase',
             'drops': 'drop', 'beats': 'beat'}
    for n, h in enumerate(raw or [], 1):
        where = f'hits[{n}]'
        if isinstance(h, (int, float, str)) and not isinstance(h, bool):
            h = {'at': h}
        elif isinstance(h, (list, tuple)):
            if not h:
                raise ValueError(f'{where}: [at, kind?, approach?]; got {h!r}')
            h = {'at': h[0], **({'kind': h[1]} if len(h) > 1 else {}), **({'approach': h[2]} if len(h) > 2 else {})}
        if not isinstance(h, dict):
            raise ValueError(f'{where} is {{at, kind}}; got {h!r}')
        extra = sorted(set(h) - {'at', 'kind', 'approach', 'tolerance_ms', 'name', 'song_at'})
        if extra:
            raise ValueError(f'{where}: unknown {", ".join(extra)} (a hit is {{at, kind, approach?, tolerance_ms?, '
                             'song_at?, name?}})')
        at = _sec(h.get('at'), f'{where}.at')
        if at is None:
            raise ValueError(f'{where}: needs at (timeline seconds)')
        kind = str(h.get('kind') or 'downbeat').strip().lower()
        kind = alias.get(kind, kind)
        if kind not in HIT_KINDS:
            raise ValueError(f"{where}: kind is downbeat | bar | phrase | drop | beat, not {h.get('kind')!r}")
        approach = str(h.get('approach') or 'auto').strip().lower()
        if approach == 'natural':
            approach = 'none'
        if approach not in APPROACHES:
            raise ValueError(f"{where}: approach is auto | join | stretch | break | none, not {h.get('approach')!r}")
        tol = h.get('tolerance_ms')
        if tol is not None and (isinstance(tol, bool) or not isinstance(tol, (int, float)) or tol < 0):
            raise ValueError(f'{where}: tolerance_ms is a number of milliseconds')
        out.append({'at': at, 'kind': kind, 'approach': approach, 'tolerance_ms': tol, 'name': h.get('name'),
                    'song_at': _sec(h.get('song_at'), f'{where}.song_at')})
    out.sort(key=lambda x: x['at'])
    for x, y in zip(out, out[1:]):
        if y['at'] - x['at'] < 0.25:
            raise ValueError(f"hits at {_clock(x['at'])} and {_clock(y['at'])} are closer than 0.25 s")
    for k, h in enumerate(out):
        h['index'] = k
    return out


def _parse_protect(raw):
    out = []
    if raw is not None and not isinstance(raw, (list, tuple)):
        raise ValueError('protect is a list of {from, to, mode: duck_deep | drop_out}')
    alias = {'duck': 'duck_deep', 'deep': 'duck_deep', 'duck_deep': 'duck_deep', 'drop': 'drop_out',
             'drop_out': 'drop_out', 'out': 'drop_out', 'mute': 'drop_out', 'off': 'drop_out'}
    for n, p in enumerate(raw or [], 1):
        where = f'protect[{n}]'
        if isinstance(p, (list, tuple)):
            if len(p) < 2:
                raise ValueError(f'{where}: [from, to, mode?]; got {p!r}')
            p = {'from': p[0], 'to': p[1], **({'mode': p[2]} if len(p) > 2 else {})}
        if not isinstance(p, dict):
            raise ValueError(f'{where} is {{from, to, mode}}; got {p!r}')
        extra = sorted(set(p) - {'from', 'to', 'mode', 'level', 'fade_out', 'fade_in', 'entry', 'name', 'why'})
        if extra:
            raise ValueError(f'{where}: unknown {", ".join(extra)} (a protected range is {{from, to, mode, level?, '
                             'fade_out?, fade_in?, entry?, name?}})')
        a, b = _sec(p.get('from'), f'{where}.from'), _sec(p.get('to'), f'{where}.to')
        if a is None or b is None or b <= a:
            raise ValueError(f'{where}: needs from < to; got {p!r}')
        mode = alias.get(str(p.get('mode') or 'duck_deep').strip().lower())
        if mode is None:
            raise ValueError(f"{where}: mode is duck_deep | drop_out, not {p.get('mode')!r}")
        level = p.get('level')
        if level is not None and (isinstance(level, bool) or not isinstance(level, (int, float))):
            raise ValueError(f'{where}: level is dB under the natural sound there (e.g. -20)')
        entry = str(p.get('entry') or 'fade').lower()
        if entry not in ENTRIES:
            raise ValueError(f"{where}: entry (how the music comes back after a drop_out) is fade | hard")
        fo, fi = p.get('fade_out'), p.get('fade_in')
        for v, nm in ((fo, 'fade_out'), (fi, 'fade_in')):
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
                raise ValueError(f'{where}: {nm} is seconds')
        out.append({'from': a, 'to': b, 'mode': mode, 'level': None if level is None else float(level),
                    'fade_out': fo, 'fade_in': fi, 'entry': entry, 'name': p.get('name') or p.get('why')})
    out.sort(key=lambda x: (x['from'], x['to']))
    merged = []
    for p in out:                                   # drop_outs that overlap become one
        q = merged[-1] if merged else None
        if q and p['mode'] == q['mode'] == 'drop_out' and p['from'] <= q['to'] + 1e-6:
            q['to'] = max(q['to'], p['to'])
            continue
        merged.append(dict(p))
    drops = [p for p in merged if p['mode'] == 'drop_out']
    return [p for p in merged if p['mode'] == 'drop_out' or         # a duck inside a drop_out is moot
            not any(d['from'] <= p['from'] and p['to'] <= d['to'] for d in drops)]


def parse_request(sections=None, hits=None, protect=None, start=None, end=None, repeat=None, max_stretch=0.0,
                  track='Music', levels=None, ending='auto', entry='fade', song_range=None, options=None):
    """The tool's inputs checked and normalized (times in seconds); raises ValueError naming the field and what is
    accepted. Values not given take the defaults (LEVELS, OPTIONS, REPEAT), and all come back in the plan."""
    lv = dict(LEVELS)
    for k, v in (levels or {}).items():
        if k not in LEVELS:
            raise ValueError(f'levels: unknown {k!r}; levels are {", ".join(LEVELS)} (dB)')
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f'levels.{k} is a number of dB')
        lv[k] = float(v)
    opts = dict(OPTIONS)
    for k, v in (options or {}).items():
        if k not in OPTIONS:
            raise ValueError(f'options: unknown {k!r}; options are {", ".join(OPTIONS)}')
        d = OPTIONS[k]
        if isinstance(d, bool):
            if not isinstance(v, bool):
                raise ValueError(f'options.{k} is true or false')
            opts[k] = v
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f'options.{k} is a number')
        if k != 'peak_ceiling_dbfs' and v < 0:
            raise ValueError(f'options.{k} is a number >= 0')
        opts[k] = type(d)(v)
    if opts['beats_per_bar'] not in (2, 3, 4, 5, 6, 7, 8, 12):
        raise ValueError('options.beats_per_bar is 2-8 or 12')
    opts['beam'] = int(max(8, min(512, opts['beam'])))
    rep = dict(REPEAT)
    if repeat is not None and not isinstance(repeat, dict):
        raise ValueError('repeat is {max_uses?, min_gap_s?, loops?, loop_bars?}')
    for k, v in (repeat or {}).items():
        if k not in REPEAT:
            raise ValueError(f'repeat: unknown {k!r}; it takes {", ".join(REPEAT)}')
        rep[k] = v
    if rep['max_uses'] is not None and (isinstance(rep['max_uses'], bool) or not isinstance(rep['max_uses'], int)
                                        or rep['max_uses'] < 1):
        raise ValueError('repeat.max_uses is a whole number >= 1 (how many times any one bar may play)')
    if isinstance(rep['min_gap_s'], bool) or not isinstance(rep['min_gap_s'], (int, float)) or rep['min_gap_s'] < 0:
        raise ValueError('repeat.min_gap_s is seconds >= 0')
    if not isinstance(rep['loops'], bool):
        raise ValueError('repeat.loops is true or false (false: no block of bars plays twice back to back)')
    if isinstance(rep['loop_bars'], bool) or not isinstance(rep['loop_bars'], int) or rep['loop_bars'] < 1:
        raise ValueError('repeat.loop_bars is a whole number of bars >= 1')
    if isinstance(max_stretch, bool) or not isinstance(max_stretch, (int, float)) or not 0 <= max_stretch <= 0.12:
        raise ValueError('max_stretch is a fraction 0-0.12 (0.02 = up to 2% faster or slower; the pitch moves with it)')
    ending = str(ending or 'auto').lower()
    if ending not in ENDINGS:
        raise ValueError(f'ending is {" | ".join(ENDINGS)}, not {ending!r}')
    entry = str(entry or 'fade').lower()
    if entry not in ENTRIES:
        raise ValueError(f'entry is {" | ".join(ENTRIES)}, not {entry!r}')
    if song_range is not None:
        if not isinstance(song_range, (list, tuple)) or len(song_range) != 2:
            raise ValueError('song_range is [from, to] in song seconds')
        song_range = [_sec(song_range[0], 'song_range'), _sec(song_range[1], 'song_range')]
        if song_range[1] <= song_range[0]:
            raise ValueError('song_range: from < to')
    if not isinstance(track, str) or not track.strip():
        raise ValueError('track is the name of the music track')
    return {'sections': _parse_sections(sections, lv), 'hits': _parse_hits(hits), 'protect': _parse_protect(protect),
            'start': _sec(start, 'start'), 'end': _sec(end, 'end'), 'repeat': rep, 'max_stretch': float(max_stretch),
            'track': track.strip(), 'levels': lv, 'ending': ending, 'entry': entry, 'song_range': song_range,
            'options': opts}


# ============================================================================ the project

def _live_state(path):
    """The editor window that has this project open (a read-only query of running editors), or None."""
    try:
        import letitedit.server.timeline_tools as timeline_tools
        return timeline_tools._live_state(path)
    except Exception:  # noqa: BLE001 - no editor running is normal
        return None


def _programme(script, exclude, total):
    """K-weighted power every 100 ms of the timeline's non-music sound (clip and track gain applied), from each
    source file's cached voice profile; (power array, source files used, ok)."""
    import letitedit.sound.music as music
    from letitedit.timeline.edit_sync import layout
    n = int(math.ceil(total * 10)) + 2
    power = np.zeros(n)
    used, ok = [], True
    for t in script['tracks']:
        if t['name'] in exclude or music.MUSIC_NAME.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        tg = music._static_gain(t.get('gain', 0) if not isinstance(t.get('gain'), dict) else 0)
        for it, s, e in layout(t):
            if 'clip' not in it or music._muted(it) or it.get('reverse') or not os.path.exists(it['clip']):
                continue
            try:
                prof = music.voice_profile(it['clip'])
            except Exception:  # noqa: BLE001 - no audio, or the voice detector is missing
                ok = False
                continue
            p = np.asarray(prof.get('power') or [], float)
            used.append(it['clip'])
            if not p.size:
                continue
            speed, a = float(it.get('speed', 1.0)), float(it['in'])
            ks = np.arange(max(0, int(math.floor(s * 10))), min(n, int(math.ceil(e * 10))))
            src = np.floor((a + (ks / 10.0 - s) * speed) * 10).astype(int)
            good = (src >= 0) & (src < len(p))
            if music._keyframed(it.get('effects')):     # a gain that changes inside the clip: each reading at its own
                gain = np.array([music.clip_gain_db(it.get('effects'), k / 10.0 - s) for k in ks[good]])
                power[ks[good]] += p[src[good]] * 10 ** ((tg + gain) / 10)
            else:
                power[ks[good]] += p[src[good]] * 10 ** ((tg + music._static_gain(it.get('effects'))) / 10)
    return power, sorted(set(used)), ok


def _range_lufs(power, a, b):
    import letitedit.sound.music as music
    p = power[max(0, int(a * 10)):max(0, int(math.ceil(b * 10)))]
    return float(music.integrated(p)) if p.size >= 4 else -70.0


def _project_context(path, req):
    import letitedit.timeline.edit_script as es
    import letitedit.sound.music as music
    from letitedit.timeline.edit_sync import layout
    script = es.read(path)
    fps = float(script['profile']['fps'])
    name = req['track']
    mtrack = next((t for t in script['tracks'] if t['name'] == name), None)
    if mtrack is not None and mtrack.get('kind') != 'audio':
        raise ValueError(f'{name} is a video track; name an audio track (or a new name) for the music')
    ends = [e for t in script['tracks'] if t is not mtrack for it, s, e in layout(t)]
    end = max(ends) if ends else 0.0
    others = [t['name'] for t in script['tracks'] if t is not mtrack and t.get('kind') == 'audio'
              and music.MUSIC_NAME.search(t['name']) and any('clip' in it for it in t['items'])]
    ctx = {'path': str(path), 'script': script, 'fps': fps, 'profile': script['profile'], 'revision': script['base'],
           'track': name, 'track_exists': mtrack is not None,
           'track_items': [it['id'] for it in (mtrack or {}).get('items', []) if it.get('id')],
           'track_gain': (mtrack or {}).get('gain'), 'track_duck': (mtrack or {}).get('duck'),
           'programme_end': float(end), 'other_music': others, 'master': script.get('master') or [],
           'ids': {it.get('id') for t in script['tracks'] for it in t['items'] if it.get('id')}}
    total = max(end, req['end'] or 0.0) + 1.0
    try:
        spans, dialogue = music.speech(script, exclude={name})
        ctx['speech_ok'] = True
    except Exception as e:  # noqa: BLE001 - the voice detector is unavailable: speech unknown, not 'none'
        spans, dialogue = [], -70.0
        ctx['speech_ok'] = False
        ctx['speech_error'] = f'{type(e).__name__}: {e}'
    ctx['speech'] = [[round(a, 3), round(b, 3)] for a, b in spans]
    ctx['dialogue_lufs'] = float(dialogue)
    power, used, ok = _programme(script, {name}, total)
    ctx['power'], ctx['power_ok'] = power, ok
    ctx['sources'] = []
    for f in used:
        try:
            ctx['sources'].append(_file_id(f))
        except OSError:
            pass
    return ctx
