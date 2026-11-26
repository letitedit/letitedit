"""Pop-ups triggered by spoken words: when the speaker says a word or phrase, a picture, emoji, text, graphic or motion
clip pops onto the screen for a moment, with its sound effect.

    {op: popups, ...}   every entry of the project's style pack, the project's own list and the op's `entries`,
                        found in what is said on the finished timeline (timeline_speech.timeline_words), placed on a
                        "Pop-ups" video track with their sounds on a "Pop-up SFX" audio track: one undoable change
    one pop-up at a time, or any other effect at a moment: {op: fx} (fx.py) with kind popup

An entry (pack: style.yaml popups.entries; project: <project stem>.letitedit/popups.json; or inline):

    id: letitedit                      (optional; default from the first phrase)
    words: [letitedit, let it edit]    phrases that trigger it: case, punctuation, spacing and a possessive 's are
                                       ignored, so "letitedit" also matches "let it edit." in a transcript
    asset: {image: assets/icon.png} | {emoji: "🔥"} | {text: "NO WAY"} | {graphic: {template, params}}
           | {motion: {block, params}}
    position: upper_right | [x, y]     centre, fractions of the frame (style_pack.POSITIONS)
    size: 0.28                         longest side as a share of the frame's shorter side (image, emoji, text)
    in: pop, out: shrink, in_s: 0.28, out_s: 0.2, hold_s: 1.2, len: (graphic/motion: their own length)
    offset_s: 0                        start relative to the word's start (negative: before it)
    sfx: pop                           a sound from the pack's sfx.map or sfx.events, a file, or null
    sfx_gain_db, sfx_offset_s          [the pack's sfx.gain_db, 0]
    max_per_video: 3, cooldown_s: 6    how often it may fire
    wiggle, tilt, shadow: true, outline: 0 (a sticker edge, px at 1080p), outline_color, font, fill, stroke

Project entries live in <project folder>/<project stem>.letitedit/popups.json
    {"format": "letitedit-popups/1", "entries": [ ...entries... ]}
paths in them are absolute or relative to the project's folder. Third-party company logos are never shipped in
packs: a person's own images go in their project's list (or their own My style pack).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import letitedit.looks.style_pack as style_pack

PROJECT_FILE = 'popups.json'
PROJECT_FORMAT = 'letitedit-popups/1'
AUTO_PREFIX = 'pop-'          # ids of pop-ups placed by {op: popups} (a later run replaces them)
PHRASE_GAP_S = 1.2            # words further apart than this are not one phrase
ENTRY_DEFAULTS = {'position': 'upper_right', 'size': 0.28, 'in': 'pop', 'out': 'shrink', 'in_s': 0.28, 'out_s': 0.2,
                  'hold_s': 1.2, 'offset_s': 0.0, 'sfx_offset_s': 0.0, 'cooldown_s': 6.0, 'max_per_video': None,
                  'wiggle': 0.0, 'tilt': 0.0, 'shadow': True, 'outline': 0, 'outline_color': 'light',
                  'font': 'heading', 'fill': 'secondary', 'stroke': 'dark', 'stroke_width': 10}
STICKER_KEYS = ('in', 'out', 'in_s', 'out_s', 'wiggle', 'tilt', 'shadow', 'outline', 'outline_color', 'font', 'fill',
                'stroke', 'stroke_width', 'size')


# ------------------------------------------------------------------ words

def norm(token):
    """A word as matching sees it: lower case, a possessive 's dropped, letters and digits only."""
    t = str(token).lower().replace('’', "'").strip()
    t = re.sub(r"'s\b", '', t)
    return re.sub(r'[^0-9a-zÀ-ɏ]+', '', t)


def phrase_key(phrase):
    return ''.join(norm(t) for t in str(phrase).split())


def _base(token):
    token = norm(token)
    for suffix in ('ing', 'ed', 'es', 's'):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[:-len(suffix)]
    return token


def find_phrase(words, phrase, max_gap=PHRASE_GAP_S):
    """Every place `phrase` is said in `words` ([{w, t0, t1, ...}] in time order) -> [(i, j, t0, t1)], word i to j-1.
    Spacing is ignored: 'letitedit' matches 'let it edit'."""
    key = phrase_key(phrase)
    if not key:
        return []
    toks = [norm(w['w']) for w in words]
    hits = []
    for i in range(len(words)):
        if len(str(phrase).split()) == 1 and _base(phrase) == _base(words[i]['w']):
            hits.append((i, i + 1, float(words[i]['t0']), float(words[i]['t1'])))
            continue
        if not toks[i] or not key.startswith(toks[i]):
            continue
        acc, j = '', i
        while j < len(words) and len(acc) < len(key):
            if j > i and float(words[j]['t0']) - float(words[j - 1]['t1']) > max_gap:
                break
            acc += toks[j]
            j += 1
            if not key.startswith(acc):
                break
        if acc == key:
            hits.append((i, j, float(words[i]['t0']), float(words[j - 1]['t1'])))
    return hits


# ------------------------------------------------------------------ entries

def project_file(project):
    """<project folder>/<project stem>.letitedit/popups.json for a saved project (None for a live snapshot)."""
    if not project:
        return None
    import letitedit.timeline.project_journal as pj
    return pj.folder(Path(project).resolve()) / PROJECT_FILE


def project_entries(project):
    """The project's own pop-ups (paths made absolute), [] when it has none."""
    f = project_file(project)
    if f is None or not f.exists():
        return []
    data = json.loads(f.read_text(encoding='utf-8-sig') or '{}')
    entries = data.get('entries') if isinstance(data, dict) else data
    base = Path(project).resolve().parent
    out = []
    for e in entries or []:
        e = dict(e)
        e['_root'] = str(base)
        out.append(e)
    return out


def save_project_entries(project, entries):
    """Write the project's own pop-ups (replacing the list); [] removes them. Returns the file."""
    import letitedit.timeline.edit_script as es
    path = es._resolve(project)
    kit = style_pack.load(None)
    kit.root = Path(path).parent
    bad = [f'entry {i} ({(e or {}).get("id") or (e or {}).get("words")}): {p}'
           for i, e in enumerate(entries or [], 1) for p in style_pack.popup_problems(kit, e)]
    if bad:
        raise ValueError('pop-ups not saved: ' + ' | '.join(bad))
    f = project_file(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps({'format': PROJECT_FORMAT, 'entries': list(entries or [])}, ensure_ascii=False,
                              indent=1), encoding='utf-8')
    os.replace(tmp, f)
    return str(f)


def _entry_id(e, n):
    if e.get('id'):
        return re.sub(r'[^a-z0-9]+', '-', str(e['id']).lower()).strip('-') or f'e{n}'
    words = e.get('words')
    first = words if isinstance(words, str) else (words or [''])[0]
    return re.sub(r'[^a-z0-9]+', '-', str(first).lower()).strip('-')[:24] or f'e{n}'


def gather(script, op, kit=None):
    """Every entry this op uses, in order pack, project, inline: [(entry with defaults, source, root folder)]."""
    import letitedit.timeline.edit_script as es
    out = []
    use_pack = op.get('look', True)
    if use_pack:
        pk = es.kit_for(use_pack) if isinstance(use_pack, str) else (kit or es.kit_for(script))
        for e in ((pk.get('popups') or {}).get('entries') or []):
            entry = dict(e)
            asset = entry.get('asset')
            if isinstance(asset, dict) and asset.get('image'):
                entry['asset'] = dict(asset, image=pk.path(asset['image']))
            out.append((entry, 'look', str(pk.root) if pk.root is not None else None))
    if op.get('project', True):
        given = op.get('_project_entries')
        for e in (given if given is not None else project_entries(_real_project(script))):
            out.append((e, 'project', e.get('_root')))
    for e in op.get('entries') or []:
        out.append((e, 'op', e.get('_root') or _project_dir(script)))
    only = op.get('only')
    seen, result = set(), []
    for n, (e, src, root) in enumerate(out, 1):
        eid = _entry_id(e, n)
        if only and eid not in only and e.get('id') not in only:
            continue
        while eid in seen:
            eid += 'x'
        seen.add(eid)
        result.append(({**ENTRY_DEFAULTS, **{k: v for k, v in e.items() if v is not None}, 'id': eid}, src, root))
    return result


def _real_project(script):
    p = script.get('project')
    if not p:
        return None
    try:
        import letitedit.app.live_edit as live_edit
        if Path(p).resolve().is_relative_to(live_edit.LIVE.resolve()):
            return None                        # a live window's snapshot: the tool layer passes the entries
    except Exception:  # noqa: BLE001
        pass
    return p


def _project_dir(script):
    p = _real_project(script)
    return str(Path(p).resolve().parent) if p else None


def _abs(path, root):
    if not path:
        return path
    p = Path(str(path))
    if not p.is_absolute() and root:
        p = Path(root) / p
    return str(p)


# ------------------------------------------------------------------ items

def overlay_item(entry, root, kit, script):
    """The timeline item an entry places, and its length in seconds."""
    asset = style_pack.resolve_asset(entry.get('asset') or {}, kit)     # a mapping, or a library reference
    prof = script.get('profile') or {}
    kind = next((k for k in style_pack.ASSET_KINDS if k in asset), None)
    if kind in ('image', 'emoji', 'text'):
        x, y = style_pack.position_xy(entry.get('position'))
        params = {k: entry[k] for k in STICKER_KEYS if k in entry}
        params.update(x=round(x, 4), y=round(y, 4))
        params['text'] = ''
        if kind == 'image':
            path = _abs(asset['image'], root)
            if not os.path.isfile(path):
                raise ValueError(f"pop-up {entry['id']}: image {asset['image']!r} not found ({path})")
            st = os.stat(path)
            params.update(image=path, asset_stamp=f'{st.st_size}-{int(st.st_mtime)}')
        else:
            params[kind] = str(asset[kind])
        n = float(entry.get('len') or (float(entry['in_s']) + float(entry['hold_s']) + float(entry['out_s'])))
        return {'graphic': {'template': 'popup', 'params': params}, 'len': round(n, 3)}, n
    if kind == 'graphic':
        g = dict(asset['graphic'])
        import letitedit.pictures.graphics as graphics
        n = float(entry.get('len') or graphics.normalise(g, kit)['len'])
        return {'graphic': g, 'len': round(n, 3)}, n
    if kind == 'motion':
        m = dict(asset['motion']) if isinstance(asset['motion'], dict) else {'block': asset['motion']}
        if entry.get('len'):
            m['duration'] = float(entry['len'])
        import letitedit.pictures.motion as motion
        n = motion.normalise(m)['duration']
        return {'motion': m}, n
    raise ValueError(f"pop-up {entry['id']}: asset is one of {', '.join(style_pack.ASSET_KINDS)}; got {asset!r}")


def sound_item(entry, root, kit, length):
    """The sound-effect clip of a pop-up (None without one) and its gain."""
    ref = entry.get('sfx')
    if not ref:
        return None
    path = kit.sfx_file(ref) if not os.path.isabs(str(ref)) else str(ref)
    if not path and root:
        cand = _abs(ref, root)
        path = cand if os.path.isfile(cand) else None
    if not path or not os.path.isfile(path):
        raise ValueError(f"pop-up {entry['id']}: sound {ref!r} is not in the pack's sfx.map / sfx.events or a file")
    import letitedit.timeline.edit_script as es
    dur = float(es.probe(path).get('duration') or 1.0)
    gain = entry.get('sfx_gain_db')
    gain = float((kit.get('sfx') or {}).get('gain_db', -16.0) if gain is None else gain)
    out = round(min(dur, max(0.1, length + 0.5)), 3)
    return {'clip': path, 'in': 0, 'out': out, 'effects': [{'gain': gain}] if abs(gain) > 1e-6 else []}


def _ensure_track(script, name, kind):
    t = next((x for x in script['tracks'] if x['name'] == name), None)
    if t is None:
        t = {'name': name, 'kind': kind, 'items': []}
        script['tracks'].append(t)
    elif (t.get('kind') or 'video') != kind:
        raise ValueError(f'{name} is a{"n audio" if kind == "video" else " video"} track; pop-ups need a {kind} track '
                         f'there (name another with track / sfx_track)')
    return t


def _family(script, name):
    root = re.sub(r'\s+\d+$', '', name)
    return [t for t in script['tracks'] if re.fullmatch(re.escape(root) + r'(\s+\d+)?', t['name'])]


def remove_auto(script, track, sfx_track):
    """Take out the pop-ups (and sounds) an earlier {op: popups} placed; the other items keep their times."""
    n = 0
    for t in _family(script, track) + _family(script, sfx_track):
        items = []
        for it in t['items']:
            if str(it.get('id', '')).startswith(AUTO_PREFIX):
                from letitedit.timeline.edit_sync import item_len
                items.append({'gap': item_len(it)})
                n += 1
            else:
                items.append(it)
        merged = []                                    # neighbouring gaps become one; a trailing gap goes
        for it in items:
            if 'gap' in it and merged and 'gap' in merged[-1]:
                merged[-1] = {'gap': round(float(merged[-1]['gap']) + float(it['gap']), 4)}
            else:
                merged.append(it)
        while merged and 'gap' in merged[-1]:
            merged.pop()
        t['items'] = merged
    return n


def _timeline_end(script):
    from letitedit.timeline.edit_sync import layout, main_track
    m = main_track(script)
    spans = layout(m) if m else []
    return max((e for _, _, e in spans), default=0.0)


def _place(script, track, at, item):
    import letitedit.timeline.edit_script as es
    sub = {'op': 'insert', 'track': track, 'at': round(at, 3), 'item': item, 'overlap': 'next_track'}
    es._place_at(script, sub)
    return sub.get('_result')


def _clock(s):
    import letitedit.timeline.edit_script as es
    return es.clock(s)


# ------------------------------------------------------------------ the ops

def plan(script, op, words=None):
    """Which entries fire where: ([{entry, source, root, t0, t1, said}], [skipped reasons]). Nothing is changed."""
    entries = gather(script, op)
    if words is None:
        from letitedit.timeline.timeline_speech import timeline_words
        words = timeline_words(script, op.get('start_s'), op.get('end_s'))
    hits = []
    for entry, src, root in entries:
        phrases = entry.get('words')
        phrases = [phrases] if isinstance(phrases, str) else list(phrases or [])
        for ph in phrases:
            for i, j, t0, t1 in find_phrase(words, ph):
                hits.append({'entry': entry, 'source': src, 'root': root, 't0': t0, 't1': t1, 'i': i, 'j': j,
                             'said': ' '.join(w['w'].strip() for w in words[i:j]), 'key': len(phrase_key(ph))})
    hits.sort(key=lambda h: (h['t0'], -h['key']))
    kit_pop = op.get('_kit_popups') or {}
    min_gap = float(op.get('min_gap_s', kit_pop.get('min_gap_s', 1.5)) or 0)
    max_total = op.get('max_total', kit_pop.get('max_total'))
    chosen, skipped, used_words, count, last = [], [], set(), {}, {}
    last_any = None
    for h in hits:
        e = h['entry']
        span = set(range(h['i'], h['j']))
        if span & used_words:
            continue                                   # a longer phrase over the same words already fired
        why = None
        if e.get('max_per_video') and count.get(e['id'], 0) >= int(e['max_per_video']):
            why = f"max_per_video {e['max_per_video']}"
        elif e['id'] in last and h['t0'] - last[e['id']] < float(e.get('cooldown_s') or 0):
            why = f"cooldown {e['cooldown_s']} s"
        elif last_any is not None and h['t0'] - last_any < min_gap:
            why = f'within {min_gap} s of another pop-up'
        elif max_total is not None and len(chosen) >= int(max_total):
            why = f'max_total {max_total}'
        if why:
            skipped.append(f"{e['id']} at {_clock(h['t0'])} (\"{h['said']}\"): {why}")
            continue
        chosen.append(h)
        used_words |= span
        count[e['id']] = count.get(e['id'], 0) + 1
        last[e['id']] = h['t0']
        last_any = h['t0']
    return chosen, skipped


def _sfx_path(entry, root, kit):
    """A pop-up's sound: a name from the pack, a file in the pack, or a file relative to the entry's own folder."""
    ref = entry.get('sfx')
    if not ref:
        return None
    path = kit.sfx_file(ref)
    if not path and root:
        cand = _abs(ref, root)
        path = cand if os.path.isfile(cand) else None
    if not path:
        raise ValueError(f"pop-up {entry['id']}: sound {ref!r} is not in the pack's sfx.map / sfx.events or a file")
    return path


def apply_op(script, op):
    """{op: popups}: every triggered pop-up and its sound, placed and checked by the fx machinery (fx.place,
    fx.check: the entries' own never/avoid rules and the style's fx rules). Writes op['_result'], op['_placed'],
    op['_problems'] and op['_frames_at']."""
    import letitedit.timeline.edit_script as es
    import letitedit.looks.fx as fx
    identity = op.get('look')
    kit = es.kit_for(identity) if isinstance(identity, str) else es.kit_for(script)
    kp = kit.get('popups') or {}
    op['_kit_popups'] = kp
    settings = fx.settings_for(kit, {'track': op.get('track') or kp.get('track'),
                                     'sfx_track': op.get('sfx_track') or kp.get('sfx_track')})
    removed = remove_auto(script, settings['track'], settings['sfx_track']) if op.get('replace', True) else 0
    chosen, skipped = plan(script, op)
    op.pop('_kit_popups', None)
    end = _timeline_end(script)
    frame = fx.Frame(script, kit, op.get('platform'))
    existing = fx.existing_effects(script)
    recs, n_by = [], {}
    for h in chosen:
        e = h['entry']
        start = max(0.0, h['t0'] + float(e.get('offset_s') or 0))
        if start >= end - 0.2:
            skipped.append(f"{e['id']} at {_clock(h['t0'])}: too close to the end")
            continue
        n_by[e['id']] = n_by.get(e['id'], 0) + 1
        spec = {k: v for k, v in e.items() if k not in ('words', 'max_per_video', 'cooldown_s', 'never', 'avoid',
                                                        'offset_s')}
        spec.update(kind='popup', at=start, _root=h['root'], _id=f"{AUTO_PREFIX}{e['id']}-{n_by[e['id']]}")
        n = float(e.get('len') or (float(e['in_s']) + float(e['hold_s']) + float(e['out_s'])))
        if start + n > end:                       # a pop-up never runs past the video's end
            spec['len'] = round(end - start, 3)
        snd = _sfx_path(e, h['root'], kit) if op.get('sfx', True) else None
        spec['sfx'] = snd
        rec = fx.place(script, spec, kit, frame, settings, prefix=AUTO_PREFIX)
        rec.update(entry=e['id'], source=h['source'], said=h['said'], trigger=e.get('trigger') or 'mention',
                   rules={'never': list(e.get('never') or []),
                          'placement': {'avoid': list(e.get('avoid') or [])}})
        recs.append(rec)
    problems = fx.check(recs, frame, kit, existing) if op.get('check', 'warn') != 'off' else []
    if problems and op.get('check') == 'strict':
        raise ValueError('pop-ups not placed (check: strict): ' + ' | '.join(
            f"{p['id']} at {_clock(p['at'])}: {p['rule']}" for p in problems))
    from letitedit.looks import sound_targets
    sound_receipts = sound_targets.receipts(script, recs)
    op['_placed'] = [{'id': r['id'], 'entry': r['entry'], 'source': r['source'], 'at': r['at'], 'len': r['len'],
                      'said': r['said'], **({'sfx': r['sfx'], 'sound_sync': r['sound_sync']} if r.get('sfx') else {})} for r in recs]
    op['_problems'] = problems
    op['_frames_at'] = sorted({round(r['at'] + min(0.4, r['len'] / 2), 2) for r in recs})[:24]
    script.setdefault('_frames_at', []).extend(op['_frames_at'])
    op['_pinned'] = [r['id'] for r in recs] + [r['sfx_id'] for r in recs if r.get('sfx_id')]
    parts = [f"{len(recs)} pop-up{'s' if len(recs) != 1 else ''} on {settings['track']}"
             + (f" (sounds on {settings['sfx_track']})" if any(r.get('sfx') for r in recs) else '')]
    if recs:
        parts.append(', '.join(f"{r['entry']} {_clock(r['at'])} \"{r['said']}\"" for r in recs[:20])
                     + (', ...' if len(recs) > 20 else ''))
    if sound_receipts:
        parts.append('sound timing (125 ms limit): ' + sound_receipts)
    if removed:
        parts.append(f'{removed} earlier pop-up items replaced')
    if skipped:
        parts.append(f'not placed: {"; ".join(skipped[:12])}' + ('; ...' if len(skipped) > 12 else ''))
    if not chosen and gather(script, op):
        import letitedit.timeline.timeline_speech as timeline_speech
        try:
            words = timeline_speech.timeline_words(script, op.get('start_s'), op.get('end_s'), cached_only=True)
        except TypeError:  # older callers may provide a timeline_words shim
            words = timeline_speech.timeline_words(script, op.get('start_s'), op.get('end_s'))
        if not words:
            parts.append('no cached spoken words on this cut; transcribe the source clips to use spoken triggers')
        else:
            parts.append('none of the style or project trigger phrases are said in this cut')
    if problems:
        parts.append(f'{len(problems)} rule(s) broken: ' + '; '.join(
            f"{p['id']} {_clock(p['at'])}: {p['rule']}" for p in problems[:12]))
    if frame.face_note:
        parts.append(frame.face_note)
    if not gather(script, op):
        parts.append('no pop-up entries: the project has no style pack with popups, no popups.json and the op gave '
                     'no entries')
    op['_result'] = '; '.join(parts)
    return op['_placed']


def inline_project_entries(project, changes):
    """For the tool layer: give every popups op the project's own entries (read from the saved project's folder), and
    relative image paths in ops their project folder, so they also work on an open window's snapshot."""
    ents = None
    root = str(Path(project).resolve().parent)
    for op in changes or []:
        if not isinstance(op, dict):
            continue
        if op.get('op') == 'popups':
            if op.get('project', True) and '_project_entries' not in op:
                if ents is None:
                    ents = project_entries(project)
                op['_project_entries'] = ents
            if op.get('entries'):
                op['entries'] = [dict(e, _root=e.get('_root') or root) if isinstance(e, dict) else e
                                 for e in op['entries']]
        elif op.get('op') == 'fx':
            op.setdefault('_root', root)
    return changes
