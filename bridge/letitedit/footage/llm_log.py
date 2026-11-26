r"""The footage log written by the agent (LLM) itself, for PCs whose footage log engine is 'llm' (see hardware.py).

    frames(video, start=0, batch=8, frames=3, width=448, max_s=8.0, merge_below=5.0, merge_max_s=30.0,
           cut_above=0.3, words=True)
        -> {'file', 'duration', 'total', 'start', 'next', 'stretches': [{'id', 'from', 'to', 'sheet', 'said'}],
            'described': [ids], 'settings', 'entry_fields'}
    write(video, entries, model='llm', finish=False, same settings as frames)
        -> {'written', 'described', 'missing', 'complete', 'log' (path when the log is stored), ...}

The stretches are shot_log.segments() of the video (the same split as the local model's log). Each stretch's sheet is
one JPEG with `frames` frames side by side (each `width` px wide, taken at (i + 0.5) / frames through the stretch),
saved under <cache>\shot_log\llm\<key>\. `said` is the cached transcript's words in the stretch ('' without one).
An entry is {'id': n, 'action', 'things', 'place', 'framing', 'text', 'quality', 'best'} (every field a string,
'best' optional), or {'id': n, 'raw': 'Action: ...\nThings: ...'} in shot_log's labelled-lines form. Entries are kept
in a draft until every stretch has one; then (or with finish=True) the log is stored in shot_log's cache in the same
format the local model writes, so shot_log.log(build=False) and letitedit_footage read it.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import json
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import letitedit.footage.shot_log as shot_log

FIELDS = ('action', 'things', 'place', 'framing', 'text', 'quality', 'best')


def _settings(max_s, frames, width, merge_below, merge_max_s, cut_above, words):
    return {'max_s': max_s, 'frames': frames, 'width': width, 'merge_below': merge_below,
            'merge_max_s': merge_max_s, 'cut_above': cut_above, 'words': bool(words)}


def _dir(key):
    d = shot_log.CACHE / 'llm' / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def _spans(video, s, key):
    f = _dir(key) / 'stretches.json'
    if f.exists():
        return [tuple(x) for x in json.loads(f.read_text(encoding='utf-8-sig'))]
    spans = shot_log.segments(video, s['max_s'], s['merge_below'], s['merge_max_s'], s['cut_above'])
    f.write_text(json.dumps(spans), encoding='utf-8')
    return spans


def _sheet(video, a, b, n, width, out):
    if out.exists():
        return str(out)
    from PIL import Image
    tmp = Path(tempfile.mkdtemp(prefix='llmlog-'))
    try:
        paths = shot_log._frames(video, a, b, n, width, tmp)
        ims = [Image.open(p).convert('RGB') for p in paths]
        if not ims:
            return None
        h = max(i.height for i in ims)
        gap = 4
        sheet = Image.new('RGB', (sum(i.width for i in ims) + gap * (len(ims) - 1), h), (0, 0, 0))
        x = 0
        for i in ims:
            sheet.paste(i, (x, 0))
            x += i.width + gap
        sheet.save(out, quality=85)
        for i in ims:
            i.close()
        return str(out)
    finally:
        for p in tmp.glob('*'):
            p.unlink(missing_ok=True)
        tmp.rmdir()


def _said(video, a, b):
    try:
        import letitedit.footage.speech as speech
        ws = speech.cached_words(str(video), a, b)
    except Exception:  # noqa: BLE001
        ws = None
    return ' '.join(w['w'].strip() for w in ws) if ws else ''


def _draft(key):
    f = _dir(key) / 'draft.json'
    return f, (json.loads(f.read_text(encoding='utf-8-sig')) if f.exists() else {})


def frames(video, start=0, batch=8, frames=3, width=448, max_s=8.0, merge_below=5.0, merge_max_s=30.0,
           cut_above=0.3, words=True):
    video = Path(video)
    s = _settings(max_s, frames, width, merge_below, merge_max_s, cut_above, words)
    key = shot_log._key(video, s)
    spans = _spans(video, s, key)
    start, batch = max(0, int(start)), max(1, int(batch))
    pick = list(enumerate(spans))[start:start + batch]
    d = _dir(key)
    with ThreadPoolExecutor(4) as ex:
        sheets = list(ex.map(lambda p: _sheet(video, p[1][0], p[1][1], int(frames), int(width),
                                              d / f'{p[0]:04d}.jpg'), pick))
    _, draft = _draft(key)
    out = []
    for (i, (a, b)), sh in zip(pick, sheets):
        out.append({'id': i, 'from': a, 'to': b, 'clock': f'{shot_log._clock(a)}-{shot_log._clock(b)}',
                    'sheet': sh, 'said': _said(video, a, b) if words else ''})
    nxt = start + batch
    return {'file': str(video), 'duration': round(shot_log._duration(video), 2), 'total': len(spans),
            'start': start, 'batch': batch, 'next': nxt if nxt < len(spans) else None, 'stretches': out,
            'described': sorted(int(k) for k in draft), 'settings': s, 'entry_fields': list(FIELDS),
            'stored': (shot_log.CACHE / f'{key}.json').exists()}


def _entry(e):
    if e.get('raw') and not any(e.get(k) for k in FIELDS):
        row = shot_log.parse(str(e['raw']))
        row['raw'] = str(e['raw'])
    else:
        row = {k: str(e[k]).strip() for k in FIELDS if e.get(k) is not None}
        row['raw'] = '\n'.join(f'{k.capitalize() if k != "best" else "Best moment"}: {row[k]}' for k in FIELDS if k in row)
    return row


def write(video, entries, model='llm', finish=False, frames=3, width=448, max_s=8.0, merge_below=5.0,
          merge_max_s=30.0, cut_above=0.3, words=True):
    video = Path(video)
    s = _settings(max_s, frames, width, merge_below, merge_max_s, cut_above, words)
    key = shot_log._key(video, s)
    spans = _spans(video, s, key)
    f, draft = _draft(key)
    if isinstance(entries, str):
        entries = json.loads(entries)
    if isinstance(entries, dict):
        entries = [{'id': k, **v} if isinstance(v, dict) else {'id': k, 'raw': v} for k, v in entries.items()]
    written, bad = [], []
    for e in entries or []:
        try:
            i = int(e['id'])
        except (KeyError, TypeError, ValueError):
            bad.append({'entry': str(e)[:120], 'error': "no integer 'id'"})
            continue
        if not 0 <= i < len(spans):
            bad.append({'id': i, 'error': f'id outside 0-{len(spans) - 1}'})
            continue
        draft[str(i)] = {**_entry(e), 'model': str(model)}
        written.append(i)
    f.write_text(json.dumps(draft, indent=1), encoding='utf-8')
    have = sorted(int(k) for k in draft)
    missing = [i for i in range(len(spans)) if str(i) not in draft]
    out = {'file': str(video), 'written': written, 'rejected': bad, 'described': have, 'missing': missing,
           'total': len(spans), 'complete': not missing, 'settings': s, 'log': None}
    if not missing or finish:
        shots = []
        models = []
        for i, (a, b) in enumerate(spans):
            row = draft.get(str(i))
            if row is None:
                continue
            row = dict(row)
            models.append(row.pop('model', model))
            shots.append({'from': a, 'to': b, **row})
        names = list(dict.fromkeys(models)) or [str(model)]
        entry = {'file': str(video), 'duration': round(shot_log._duration(video), 2), 'shots': shots,
                 'model': ', '.join(names), 'settings': s, 'context': None, 'seconds': None, 'model_s': None,
                 'engine': 'llm', 'complete': not missing, 'written_at': time.strftime('%Y-%m-%d %H:%M:%S')}
        log = shot_log.CACHE / f'{key}.json'
        log.write_text(json.dumps(entry, indent=1), encoding='utf-8')
        out['log'] = str(log)
    return out
