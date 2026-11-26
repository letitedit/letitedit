"""Footage notes: what happens where in a source file, remembered across sessions (Claude's memory of the footage).

Notes are optional; nothing requires them. They are keyed by the file's content (size + a hash of its first 2 MB), so a
clip keeps its notes when it is copied or moved (Drive original vs local copy). letitedit_footage shows them per file.

    add(path, at, text)            at = seconds, 'm:ss', or 'm:ss-m:ss'
    get(path)                      [{in, out, text, tags, source}], in time order
    import_episode(system_folder)  bring in the reviewed scenes of a managed episode (old pipeline)
"""
from __future__ import annotations
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import hashlib
import json
import os
import time
from pathlib import Path

CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
NOTES = CACHE / 'notes'
_KEYS = {}


def key(path):
    st = os.stat(path)
    memo = (str(Path(path).resolve()), st.st_size, st.st_mtime_ns)
    if memo not in _KEYS:
        h = hashlib.sha1()
        with open(path, 'rb') as fh:
            h.update(fh.read(2 * 1024 * 1024))
        _KEYS[memo] = f'{st.st_size}-{h.hexdigest()[:16]}'
    return _KEYS[memo]


def _file(path):
    return NOTES / f'{key(path)}.json'


def _load(path):
    f = _file(path)
    if f.exists():
        with open(f, encoding='utf-8-sig') as fh:
            return json.load(fh)
    return {'names': [], 'notes': []}


def _save(path, data):
    NOTES.mkdir(parents=True, exist_ok=True)
    name = Path(path).name
    if name not in data['names']:
        data['names'].append(name)
    f = _file(path)
    tmp = f.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, f)


def _span(at):
    from letitedit.timeline.edit_script import to_seconds
    if isinstance(at, (int, float)):
        return float(at), float(at)
    if isinstance(at, (list, tuple)):
        if len(at) == 1:
            return to_seconds(at[0]), to_seconds(at[0])
        if len(at) != 2:
            raise ValueError(f'at is a time, or [start, end] for a stretch; got {list(at)!r}')
        return to_seconds(at[0]), to_seconds(at[1])
    text = str(at).strip()
    if '-' in text[1:]:
        a, b = text.split('-', 1) if not text.startswith('-') else (text, text)
        return to_seconds(a.strip()), to_seconds(b.strip())
    return to_seconds(text), to_seconds(text)


def add(path, at, text, tags=None, source='claude'):
    """Remember something about a stretch of a source file. Returns the note."""
    a, b = _span(at)
    data = _load(path)
    note = {'in': round(a, 2), 'out': round(max(a, b), 2), 'text': str(text).strip(), 'tags': list(tags or []),
            'source': source, 'added': time.strftime('%Y-%m-%d')}
    if not any(n['in'] == note['in'] and n['out'] == note['out'] and n['text'] == note['text'] for n in data['notes']):
        data['notes'].append(note)
        data['notes'].sort(key=lambda n: (n['in'], n['out']))
        _save(path, data)
    return note


def remove(path, text_contains):
    data = _load(path)
    before = len(data['notes'])
    data['notes'] = [n for n in data['notes'] if text_contains.lower() not in n['text'].lower()]
    if len(data['notes']) != before:
        _save(path, data)
    return before - len(data['notes'])


def get(path):
    try:
        return _load(path)['notes']
    except OSError:
        return []


def brief(path, limit=12):
    """Short lines for listings: 'm:ss-m:ss text'."""
    def fmt(s):
        return f'{int(s // 60)}:{s % 60:04.1f}'
    out = []
    for n in get(path)[:limit]:
        span = fmt(n['in']) if n['in'] == n['out'] else f"{fmt(n['in'])}-{fmt(n['out'])}"
        out.append(f"{span} {n['text']}" + (f" [{', '.join(n['tags'])}]" if n['tags'] else ''))
    return out


def import_episode(system_folder):
    """Copy a managed episode's reviewed scene notes (03 Analysis/scenes.json) into the notes store. Re-runnable."""
    system = Path(system_folder)
    media_file, scenes_file = system / '03 Analysis' / 'media.json', system / '03 Analysis' / 'scenes.json'
    if not scenes_file.exists() or not media_file.exists():
        return {'imported': 0, 'reason': 'no scenes.json / media.json here'}
    with open(media_file, encoding='utf-8-sig') as fh:
        media = {m['id']: m for m in json.load(fh).get('items', [])}
    with open(scenes_file, encoding='utf-8-sig') as fh:
        scenes = json.load(fh).get('items', [])
    imported, missing = 0, set()
    for s in scenes:
        if s.get('stale'):
            continue
        m = media.get(s.get('media_id'))
        if not m or not os.path.exists(m.get('path', '')):
            missing.add(s.get('media_id'))
            continue
        text = s.get('summary', '')
        if s.get('quality'):
            text += f" ({s['quality']})"
        before = len(get(m['path']))
        add(m['path'], [s.get('in_s', 0), s.get('out_s', s.get('in_s', 0))], text, tags=s.get('roles') or [],
            source=f"scene:{s.get('id')}")
        imported += len(get(m['path'])) > before
    return {'imported': imported, 'scenes': len(scenes), 'files_missing': len(missing)}
