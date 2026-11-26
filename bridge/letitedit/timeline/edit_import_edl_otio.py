"""CMX3600 EDLs and OpenTimelineIO JSON.

Part of `edit_import` (letitedit/timeline/edit_import.py), which imports every name here back,
so `edit_import.X` is the same object it always was.
"""
from __future__ import annotations
import copy
import json
import os
import re
from pathlib import Path
from letitedit.timeline.edit_import_common import (  # noqa: E402
    _file_timecode, _find_media, _probe, _r, _url_path
)


_EDL_EVENT = re.compile(r'^\s*(\d{1,6})\s+(\S+)\s+(\S+)\s+(C|D|W\d{3}|K[BO]?|KB|KO)\s+(\d+\s+)?'
                        r'(\d{1,2}[:;.]\d\d[:;.]\d\d[:;.]\d{2,3})\s+(\d{1,2}[:;.]\d\d[:;.]\d\d[:;.]\d{2,3})\s+'
                        r'(\d{1,2}[:;.]\d\d[:;.]\d\d[:;.]\d{2,3})\s+(\d{1,2}[:;.]\d\d[:;.]\d\d[:;.]\d{2,3})', re.M)


# ============================================================================ CMX3600 EDL

def _tc_frames(tc, base):
    h, m, s, f = (int(x) for x in re.split(r'[:;.]', tc))
    return ((h * 60 + m) * 60 + s) * base + f


def _edl_events(text, base, rate):
    """The CMX3600 events in order, with the clip names, source files and speeds of the comment lines under each."""
    events, cur = [], None
    for line in text.splitlines():
        ev = _EDL_EVENT.match(line)
        if ev:
            num, reel, trk, kind, tlen, si, so, ri, ro = ev.groups()
            cur = {'num': int(num), 'reel': reel, 'track': trk.upper(), 'kind': kind.upper(),
                   'trans': int(tlen) if tlen and tlen.strip() else 0,
                   'src_in': _tc_frames(si, base), 'src_out': _tc_frames(so, base),
                   'rec_in': _tc_frames(ri, base), 'rec_out': _tc_frames(ro, base), 'speed': 1.0}
            events.append(cur)
            continue
        s = line.strip()
        if cur is None:
            continue
        mm = re.match(r'\*\s*(FROM CLIP NAME|TO CLIP NAME|SOURCE FILE|CLIP NAME)\s*:\s*(.+)$', s, re.I)
        if mm:
            key = mm.group(1).upper()
            if key == 'TO CLIP NAME':
                cur['to_name'] = mm.group(2).strip()
            elif key == 'SOURCE FILE':
                cur['file'] = mm.group(2).strip()
            else:
                cur['name'] = mm.group(2).strip()
            continue
        mm = re.match(r'M2\s+(\S+)\s+([-\d.]+)\s+(\S+)', s)
        if mm:
            cur['speed'] = float(mm.group(2)) / rate
    return events


def _edl_sound(audio, v_ranges, sec, src_sec, offset, notes, model):
    """Audio events: one matching a picture event is that clip's sound; the others go on audio tracks."""
    # sound: an audio event matching a picture event keeps that clip's sound; the others go on audio tracks
    matched = set()
    extra = {}
    for a in audio:
        hit = None
        for e, it, rin, rout in v_ranges:
            if (e is a or (a.get('path') == e.get('path') and abs(a['rec_in'] - e['rec_in']) <= 1 and
                           abs(a['src_in'] - e['src_in']) <= 1)):
                hit = id(it)
        if hit is not None:
            matched.add(hit)
            continue
        if not a.get('path'):
            notes.append(f"event {a['num']}: no file found for {a.get('file') or a.get('name') or a['reel']} (left out; "
                         'media_dir= says where to look)')
            continue
        ch = re.findall(r'A(\d*)', a['track'])
        lane = 'A1' if not ch or ch[0] in ('', '1') or a['track'] == 'AA' else f'A{ch[0]}'
        rin = sec(a['rec_in'] - offset)
        rout = sec(a['rec_out'] - offset)
        st = src_sec(a, a['src_in'])
        extra.setdefault(lane, []).append({'clip': a['path'], 'in': _r(st), 'out': _r(st + (rout - rin) * (a['speed'] or 1)),
                                           'at': _r(rin)})
    if audio:
        muted = 0
        for e, it, rin, rout in v_ranges:
            if id(it) not in matched and 'clip' in it and _probe(it['clip']).get('audio'):
                it.setdefault('effects', []).append('mute')
                muted += 1
        if muted:
            notes.append(f'{muted} picture events without a matching audio event play muted')
    else:
        notes.append('the EDL has no audio events; picture clips keep their own sound')
    for lane in sorted(extra):
        model['tracks'].append({'name': lane, 'kind': 'audio', 'items': extra[lane]})


def _read_edl(text, base_dir, media_dir, fps, notes):
    rate = fps
    m = re.search(r'^\*\s*FPS:\s*([\d.]+)', text, re.M | re.I)
    if m:
        rate = float(m.group(1))
        notes.append(f'timecode read at {rate:g} fps (from the EDL\'s FPS comment)')
    if not rate:
        rate = 30.0
        notes.append('timecode read at 30 fps (pass fps= for another rate)')
    base = int(round(rate))
    if re.search(r'^FCM:\s*DROP', text, re.M | re.I):
        notes.append('drop-frame timecode read as non-drop')
    dirs = [d for d in (*(media_dir or []), base_dir, Path.cwd()) if d]
    events = _edl_events(text, base, rate)
    if not events:
        raise ValueError('no CMX3600 events found')
    hour = 3600 * base
    offset = hour if min(e['rec_in'] for e in events) >= hour else 0
    if offset:
        notes.append('record timecode starts at 01:00:00:00; read as the start of the timeline')

    def sec(frames):
        return frames / rate

    def resolve(e):
        name = e.get('to_name') if e['kind'] == 'D' and e.get('to_name') else e.get('name')
        for cand in (e.get('file'), name, e['reel']):
            if cand and cand.upper() not in ('AX', 'BL', 'BLACK'):
                got = _find_media(cand, dirs)
                if got:
                    return got
        return None
    video, audio = [], []
    by_num = {}
    for e in events:
        by_num.setdefault(e['num'], []).append(e)
    for num in sorted(by_num):
        lines = by_num[num]
        for k, e in enumerate(lines):
            if e['kind'] == 'C' and len(lines) > 1 and k + 1 < len(lines) and lines[k + 1]['kind'] != 'C':
                continue      # the outgoing side of a dissolve: its clip is the event before
            e['path'] = None if e['reel'].upper() in ('BL', 'BLK', 'BLACK') else resolve(e)
            e['black'] = e['reel'].upper() in ('BL', 'BLK', 'BLACK')
            if e['kind'].startswith('W') and e['kind'] != 'W':
                code = int(e['kind'][1:])
                e['wipe'] = {1: 'bar_horizontal', 2: 'bar_vertical'}.get(code)
                if not e['wipe']:
                    notes.append(f'event {num}: wipe {e["kind"]} read as a dissolve')
            t = e['track']
            if 'V' in t or t == 'B':
                video.append(e)
            if 'A' in t or t == 'B':
                audio.append(e)
    video.sort(key=lambda e: e['rec_in'])

    def src_sec(e, frames):
        tc = _file_timecode(e['path'], rate) if e.get('path') else 0.0
        s = sec(frames)
        if tc and s >= tc:
            return s - tc
        return s
    main, pos = [], 0.0
    v_ranges = []
    for e in video:
        rin, rout = sec(e['rec_in'] - offset), sec(e['rec_out'] - offset)
        trans = sec(e['trans']) if e['kind'] != 'C' else 0.0
        if rin > pos + 1e-3 and not trans:
            main.append({'gap': _r(rin - pos)})
            pos = rin
        if e['black'] or not e['path']:
            it = {'color': '#ff000000', 'len': _r(rout - rin)}
            if not e['black']:
                it['name'] = f"missing: {e.get('name') or e['reel']}"
                notes.append(f"event {e['num']}: no file found for {e.get('file') or e.get('name') or e['reel']} "
                             '(a black placeholder; media_dir= says where to look)')
        else:
            sp = e['speed'] or 1.0
            a = src_sec(e, e['src_in'])
            if sp < 0:
                it = {'clip': e['path'], 'in': _r(max(0.0, a - (rout - rin) * abs(sp))), 'out': _r(a), 'reverse': True}
                if abs(abs(sp) - 1) > 1e-3:
                    notes.append(f"event {e['num']}: reverse at {abs(sp):g}x read as reverse at 1x")
            else:
                it = {'clip': e['path'], 'in': _r(a), 'out': _r(a + (rout - rin) * sp)}
                if abs(sp - 1) > 1e-3:
                    it['speed'] = _r(sp, 6)
            if e.get('name') and os.path.basename(e['path']) != e['name']:
                it['name'] = e['name']
        if trans:
            prev = next((x for x in reversed(main) if 'gap' not in x), None)
            if prev is not None and 'out' in prev and main and 'gap' not in main[-1]:
                prev['out'] = _r(prev['out'] + trans * float(prev.get('speed', 1.0)))
                spec = {'type': e.get('wipe') or 'dissolve', 'len': _r(trans)}
                it['transition'] = spec if spec['type'] != 'dissolve' else _r(trans)
            elif prev is not None and 'color' in prev and main and 'gap' not in main[-1]:
                prev['len'] = _r(prev['len'] + trans)
                it['transition'] = _r(trans)
            else:
                it.setdefault('effects', []).append({'fade_in': _r(trans)})
                notes.append(f"event {e['num']}: a dissolve from nothing read as a fade in")
        main.append(it)
        v_ranges.append((e, it, rin, rout))
        pos = rout
    model = {'tracks': [{'name': 'V1', 'kind': 'video', 'items': main, 'main': True}], 'notes': notes, 'made': []}
    _edl_sound(audio, v_ranges, sec, src_sec, offset, notes, model)
    return model


# ============================================================================ OpenTimelineIO (as plain JSON)

def _rt(rt):
    """seconds from an OTIO RationalTime dict."""
    if not rt:
        return 0.0
    rate = float(rt.get('rate') or 1.0)
    return float(rt.get('value') or 0.0) / rate


def _schema(obj):
    return str((obj or {}).get('OTIO_SCHEMA', '')).split('.')[0]


def _otio_clip_item(ch, ref, rs, sr, name, notes, dirs):
    """One OTIO clip as an item: its media (a file, a colour or a placeholder), range, speed and freeze."""
    avail = ref.get('available_range') or {}
    start = _rt(sr.get('start_time')) if sr else _rt(avail.get('start_time'))
    dur = _rt(sr.get('duration')) if sr else _rt(avail.get('duration'))
    meta = (ch.get('metadata') or {}).get('letitedit_ai') or {}
    speed = 1.0
    freeze = False
    for eff in ch.get('effects') or []:
        es_ = _schema(eff)
        if es_ == 'LinearTimeWarp':
            speed *= float(eff.get('time_scalar', 1.0))
        elif es_ == 'FreezeFrame':
            freeze = True
        else:
            notes.append(f"{name}: effect {eff.get('effect_name') or es_} on {ch.get('name')} not read")
    it = None
    if meta.get('item'):
        it = copy.deepcopy(meta['item'])
        it.pop('at', None)
    elif rs == 'GeneratorReference':
        color = ((ref.get('parameters') or {}).get('color') or '#ff000000')
        it = {'color': color if str(color).startswith('#') else '#ff000000', 'len': _r(dur)}
    elif rs == 'ExternalReference':
        path = _find_media(_url_path(ref.get('target_url', '')), dirs)
        if path is None:
            notes.append(f"{name}: no file for {ref.get('target_url')} (a black placeholder)")
            it = {'color': '#ff000000', 'len': _r(dur), 'name': f"missing: {ch.get('name')}"}
        else:
            a0 = start - _rt(avail.get('start_time')) if avail.get('start_time') else start
            if freeze:
                it = {'freeze': {'clip': path, 'at': _r(a0)}, 'len': _r(dur)}
            elif speed < 0:
                it = {'clip': path, 'in': _r(max(0.0, a0 - dur * abs(speed))), 'out': _r(a0), 'reverse': True}
            else:
                it = {'clip': path, 'in': _r(a0), 'out': _r(a0 + dur * speed), '_kind': 'clip'}
                if abs(speed - 1) > 1e-6:
                    it['speed'] = _r(speed, 6)
            if ch.get('name') and ch['name'] != os.path.basename(path):
                it['name'] = ch['name']
    else:
        notes.append(f"{name}: {ch.get('name') or 'a clip'} has no media (a black placeholder)")
        it = {'color': '#ff000000', 'len': _r(dur), 'name': f"missing: {ch.get('name') or 'clip'}"}
    return it, meta, dur


def _otio_audio_twins(audio_tracks, main_layout, notes, model):
    """Audio clips that repeat a main clip (same file, range and place) become that clip's own sound."""
    # audio clips that repeat a main clip (same file, range and place) are that clip's sound
    if audio_tracks and main_layout:
        used = set()
        for name, items in audio_tracks:
            keep = []
            for it in items:
                twin = next((m for m, s, e in main_layout if 'clip' in m and m['clip'] == it.get('clip')
                             and abs(s - it.get('at', -1)) < 0.05 and abs(m.get('in', 0) - it.get('in', 0)) < 0.05), None)
                if twin is not None:
                    used.add(id(twin))
                else:
                    keep.append(it)
            items[:] = keep
        if used:
            for m, s, e in main_layout:
                if 'clip' in m and id(m) not in used and _probe(m['clip']).get('audio'):
                    m.setdefault('effects', []).append('mute')
            notes.append('audio clips that repeat a picture clip were read as that clip\'s own sound; picture clips '
                         'without one play muted')
        model['tracks'] = [t for t in model['tracks'] if t['kind'] == 'video' or t['items']]


def _read_otio(text_or_obj, base_dir, media_dir, notes):
    data = json.loads(text_or_obj) if isinstance(text_or_obj, str) else text_or_obj
    dirs = [d for d in (*(media_dir or []), base_dir, Path.cwd()) if d]
    sch = _schema(data)
    if sch == 'SerializableCollection':
        data = next((c for c in data.get('children', []) if _schema(c) == 'Timeline'), None)
        if data is None:
            raise ValueError('no Timeline in this OTIO collection')
        sch = 'Timeline'
    stack = data.get('tracks') if sch == 'Timeline' else data if sch == 'Stack' else {'children': [data]}
    tracks = [t for t in (stack or {}).get('children', []) if _schema(t) == 'Track']
    if not tracks:
        raise ValueError('no tracks in this OTIO timeline')
    rate_seen = None
    model = {'tracks': [], 'notes': notes, 'made': []}
    vcount = acount = 0
    main_layout = []
    audio_tracks = []
    for t in tracks:
        kind = 'audio' if str(t.get('kind', 'Video')).lower() == 'audio' else 'video'
        given = str(t.get('name') or '').strip()
        if kind == 'video':
            vcount += 1
            generic = not given or re.fullmatch(r'(video|v)\s*\d*', given, re.I)
            name = 'V1' if vcount == 1 else (f'V{vcount}' if generic else given)
        else:
            acount += 1
            generic = not given or re.fullmatch(r'(audio|a)\s*\d*', given, re.I)
            name = f'A{acount}' if generic else given
        if any(x['name'] == name for x in model['tracks']):
            name = f'{name} ({len(model["tracks"]) + 1})'
        items, pos = [], 0.0
        children = t.get('children', [])
        pending_out = None
        for k, ch in enumerate(children):
            s = _schema(ch)
            sr = ch.get('source_range') or {}
            if s == 'Gap':
                d = _rt(sr.get('duration'))
                items.append({'gap': _r(d)})
                pos += d
                continue
            if s == 'Transition':
                a_off, b_off = _rt(ch.get('in_offset')), _rt(ch.get('out_offset'))
                ttype = str(ch.get('transition_type', 'SMPTE_Dissolve'))
                if ttype not in ('SMPTE_Dissolve', 'dissolve'):
                    notes.append(f'{name}: transition {ttype} read as a dissolve')
                prev = next((x for x in reversed(items) if 'gap' not in x), None)
                if prev is not None and 'gap' not in items[-1] and prev.get('_kind') == 'clip':
                    prev['out'] = _r(prev['out'] + b_off * float(prev.get('speed', 1.0)))
                    pending_out = (a_off, a_off + b_off)
                else:
                    notes.append(f'{name}: a transition with no clip before it was left out')
                continue
            if s in ('Stack', 'Track'):
                notes.append(f'{name}: a nested {s} (compound clip) at {pos:.2f} s was read as a gap')
                d = _rt(sr.get('duration')) if sr else 0.0
                items.append({'gap': _r(d)})
                pos += d
                continue
            if s != 'Clip':
                continue
            refs = ch.get('media_references') or {}
            ref = refs.get(ch.get('active_media_reference_key') or 'DEFAULT_MEDIA') if refs else ch.get('media_reference')
            ref = ref or {}
            rs = _schema(ref)
            if rate_seen is None and sr.get('duration'):
                rate_seen = float(sr['duration'].get('rate') or 0) or None
            it, meta, dur = _otio_clip_item(ch, ref, rs, sr, name, notes, dirs)
            if meta.get('effects'):
                it['effects'] = copy.deepcopy(meta['effects'])
            if pending_out is not None:
                a_off, total = pending_out
                if it.get('_kind') == 'clip':
                    it['in'] = _r(it['in'] - a_off * float(it.get('speed', 1.0)))
                    it['transition'] = _r(total)
                pending_out = None
            for mk in ch.get('markers') or []:
                notes.append(f"{name}: marker {mk.get('name', '')!r} on {ch.get('name')}")
            if kind == 'video' and vcount == 1:
                main_layout.append((it, pos, pos + dur))
            else:
                it['at'] = _r(pos)
            items.append(it)
            pos += dur
        for it in items:
            it.pop('_kind', None)
        if kind == 'video' and vcount > 1:
            items = [x for x in items if 'gap' not in x]
        if kind == 'audio':
            items = [x for x in items if 'gap' not in x]
            audio_tracks.append((name, items))
        tr = {'name': name, 'kind': kind, 'items': items}
        if kind == 'video' and vcount == 1:
            tr['main'] = True
        model['tracks'].append(tr)
    _otio_audio_twins(audio_tracks, main_layout, notes, model)
    if rate_seen:
        model['size'] = {'fps': rate_seen}
    return model
