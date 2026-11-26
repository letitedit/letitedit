"""Edits computed by the agent's own Python: letitedit_timeline_apply(code=...).

The code runs in its own process (python -I, this folder on the path) with these names defined:

    timeline                      the edit script as read (tracks, items with ids, at/len, said, effects, captions...)
    changes                       a list; whatever the code appends is applied like `changes` passed to the tool
    words(start_s, end_s)         words said on the timeline: [{'w', 't0', 't1', 'id', 'track'}] in timeline seconds
    source_words(clip, start, end)  words in a source file: [{'w', 's', 'e'}] in source seconds
    find(text, clip=None, near=None)  a phrase: with clip, {'in', 'out', 'said'} source seconds cut on the gaps
                                  around it; without, {'start', 'end', 'id'} on the timeline (first match after near)
    layout(track)                 [(item, start_s, end_s)] for a track name
    clock(seconds), seconds(value)

print() output comes back with the result. The timeline itself only changes through `changes`.
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.append(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))   # started with -I, which leaves this folder off sys.path; last, so it shadows nothing
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
TIMEOUT = 300
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def run(script, code, timeout=TIMEOUT):
    """Run `code` against `script` in a separate process. Returns {'changes': [...], 'output': str}."""
    with tempfile.TemporaryDirectory() as d:
        job = Path(d) / 'job.json'
        out = Path(d) / 'out.json'
        job.write_text(json.dumps({'script': script, 'code': code, 'out': str(out)}), encoding='utf-8')
        try:
            r = subprocess.run([sys.executable, '-I', str((_paths.BRIDGE / 'edit_code.py')), str(job)], capture_output=True,
                               text=True, encoding='utf-8', errors='replace', timeout=timeout, cwd=d,
                               creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise ValueError(f'the code ran longer than {timeout} s') from None
        printed = (r.stdout or '')[-6000:]
        if not out.exists():
            err = (r.stderr or '').strip()
            raise ValueError('the code failed:\n' + err[-3000:] + (f'\n(printed: {printed[-1500:]})' if printed else ''))
        res = json.loads(out.read_text(encoding='utf-8-sig'))
    if res.get('error'):
        hint = ''
        if 'NameError' in res['error']:
            hint = ('\n(defined in `code`: timeline, changes (append ops to it; they are applied after the code runs), '
                    'words, source_words, find, layout, clock, seconds, plus anything you import)')
        raise ValueError('the code failed:\n' + res['error'] + hint + (f'\n(printed: {printed[-1500:]})' if printed else ''))
    changes = res.get('changes') or []
    if not isinstance(changes, list) or not all(isinstance(c, dict) and c.get('op') for c in changes):
        raise ValueError('`changes` must be a list of ops like {op: insert, ...}')
    return {'changes': changes, 'output': printed}


def _namespace(script):
    sys.path.insert(0, str(HERE))
    import letitedit.timeline.cutpoints as cutpoints
    import letitedit.timeline.edit_script as es
    import letitedit.footage.speech as speech
    import letitedit.timeline.timeline_speech as timeline_speech
    from letitedit.timeline.edit_sync import layout as _layout

    def words(start_s=None, end_s=None):
        return timeline_speech.timeline_words(script, start_s, end_s)

    def source_words(clip, start=None, end=None):
        return [{'w': w['w'], 's': w['s'], 'e': w['e']} for w in speech.words(clip, start, end)]

    def find(text, clip=None, near=None):
        if clip:
            got = cutpoints.find(clip, text, near=near)
            return {k: got[k] for k in ('in', 'out', 'said') if k in got}
        want = [x for x in re.findall(r"[\w$']+", text.lower())]
        ws = words()
        toks = [re.sub(r"[^\w$']", '', w['w'].lower()) for w in ws]
        for i in range(len(ws) - len(want) + 1):
            if toks[i:i + len(want)] == want and (near is None or ws[i]['t0'] >= float(near) - 1e-6):
                return {'start': ws[i]['t0'], 'end': ws[i + len(want) - 1]['t1'], 'id': ws[i]['id']}
        return None

    def layout(track):
        t = next((x for x in script['tracks'] if x['name'] == track), None)
        if t is None:
            raise KeyError(f'No track named {track}')
        return _layout(t)

    return {'timeline': script, 'changes': [], 'words': words, 'source_words': source_words, 'find': find,
            'layout': layout, 'clock': es.clock, 'seconds': es.to_seconds, '__name__': '__letitedit_code__'}


def _main(job_path):
    import traceback
    job = json.loads(Path(job_path).read_text(encoding='utf-8-sig'))
    ns = _namespace(job['script'])
    result = {}
    try:
        exec(compile(job['code'], '<code>', 'exec'), ns)
        result['changes'] = ns.get('changes') or []
    except Exception:  # noqa: BLE001 - reported back to the caller
        tb = traceback.format_exc()
        result['error'] = tb[tb.find('File "<code>"'):] if 'File "<code>"' in tb else tb[-3000:]
    Path(job['out']).write_text(json.dumps(result, default=str), encoding='utf-8')


if __name__ == '__main__':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    _main(sys.argv[1])
