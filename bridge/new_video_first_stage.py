"""New video's first stage, started complete (T300; the starter itself is T299's letitedit/app/stage_start.py).

The editor runs this before the first conversation of a New video run (not Turbo, not a connector, not Learn), with
the run's request as New video wrote it. It works out the first stage (log, or story when the video has no footage),
the project the stage works on (a Studio job's prepared project wins, through new_video_stages.start_request), the
Look the person chose (resolved as the lean seed resolves it, new_video_lean.look) and the Look input record the request
names, then asks new_video_carry's internal `stage_start` for the complete first message. Not a tool and not part of
the tools' contract.

    python new_video_first_stage.py < {"action": "start", "folder", "request", "ai": {engine, model, effort},
                                       "max_bytes", "project"?}
      {"decision": "stage_ready", "request", "original_request", "stage", "project", "folder", "bytes", "sha256",
       "attachments", ...}                                     the complete first message and its checksums
      {"decision": "refused", "reason"}                        the run starts with its own request, as before
    python new_video_first_stage.py < {"action": "verify", "startup": {...}, "delivered": "<the exact outgoing text>"}
      {"decision": "stage_verified"} or {"decision": "refused", "reason"}

stdin is read as UTF-8 bytes (never the console code page) and the reply is ASCII JSON.
"""
import json
import os
import re
import sys
from pathlib import Path

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import letitedit.core.quiet_subprocess  # noqa: E402,F401  (no console windows)

RECORD = re.compile(r'What the person gave this Look up front \(kept in (.+?)\)\. Once the project exists')


def first_stage(request):
    """log, or story for a video with no footage (no folder to log)."""
    return 'story' if (request or '').startswith('Make a first cut with no footage') else 'log'


def planned_project(folder, given=None):
    """The project the first stage works on: the one given (the window's open one in this folder), the newest one
    already in the folder, else <folder>/<folder name>.mlt, which the AI makes."""
    folder = Path(folder).resolve()
    if given:
        path = Path(given).resolve()
        if path.parent == folder and path.suffix.lower() == '.mlt':
            return path
    existing = sorted(folder.glob('*.mlt'), key=lambda p: p.stat().st_mtime, reverse=True)
    return existing[0] if existing else folder / (folder.name + '.mlt')


def input_record(request):
    """The Look input record the request names, when it is there."""
    match = RECORD.search(request or '')
    if not match:
        return None
    path = Path(match.group(1).strip())
    return str(path) if path.is_file() else None


def start(request):
    text = request['request']
    folder = request.get('folder') or ''
    if not folder or not Path(folder).is_dir():
        return {'decision': 'refused', 'reason': 'the video has no folder yet'}
    max_bytes = request.get('max_bytes')
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        return {'decision': 'refused', 'reason': 'the AI\'s message limit is not known'}
    try:
        import new_video_lean
        chosen, extra = new_video_lean.look(text)
    except Exception as error:  # noqa: BLE001 - an unresolved Look starts as before, with the reason
        return {'decision': 'refused', 'reason': f'the chosen Look could not be resolved ({type(error).__name__}: {error})'}
    call = {'action': 'stage_start', 'stage': first_stage(text),
            'project': str(planned_project(folder, request.get('project'))),
            'request': text, 'ai': request['ai'], 'max_bytes': max_bytes}
    if chosen.get('id') not in (None, '', 'none', 'auto', 'freestyle'):
        call['look'] = chosen
    if extra:
        call['skills'] = list(extra)
    record = input_record(text)
    if record:
        call['input_record'] = record
    from letitedit.app import new_video_carry
    try:
        result = new_video_carry.dispatch(call)
    except Exception as error:  # noqa: BLE001
        return {'decision': 'refused', 'reason': f'{type(error).__name__}: {error}'}
    if result.get('decision') != 'stage_ready':
        return {'decision': 'refused', 'reason': result.get('reason') or 'the first stage could not be prepared'}
    return result


def verify(request):
    from letitedit.app import stage_start
    startup = dict(request['startup'])
    startup.pop('request', None)
    startup.pop('decision', None)
    try:
        stage_start.verify(startup, request['delivered'])
    except (stage_start.IncompleteStart, KeyError, TypeError, ValueError) as error:
        return {'decision': 'refused', 'reason': str(error)}
    return {'decision': 'stage_verified', 'bytes': startup['bytes'], 'sha256': startup['sha256']}


def main(data):
    request = json.loads(data.decode('utf-8-sig'))
    action = request.get('action')
    if action == 'start':
        return start(request)
    if action == 'verify':
        return verify(request)
    return {'decision': 'refused', 'reason': f'unknown action {action!r}'}


if __name__ == '__main__':
    try:
        reply = main(sys.stdin.buffer.read())
    except Exception as error:  # noqa: BLE001
        reply = {'decision': 'refused', 'reason': f'{type(error).__name__}: {error}'}
    sys.stdout.write(json.dumps(reply, ensure_ascii=True) + '\n')
