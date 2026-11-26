"""The Studio's command line (CONTRACT.md section 3, 'Entry points').

    <python> <bridge>\\letitedit_studio.py validate|submit|run|status|cancel|retry <job folder | job.json | job id>
    <python> <bridge>\\letitedit_studio.py capabilities
    <python> <bridge>\\letitedit_studio.py watch [--idle-s S]

Prints JSON on stdout. Exit codes: 0 done (submit: queued), 1 failed, 2 invalid job, 3 cancelled, 4 couldn't start.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

USAGE = __doc__


def _print(data):
    sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    if not argv or argv[0] in ('-h', '--help', 'help'):
        sys.stderr.write(USAGE)
        return 2 if not argv else 0
    try:
        import letitedit.studio.capabilities as capabilities
        import letitedit.studio.service as service
        import letitedit.studio.validate as validate
        h = service.home()
    except Exception as e:  # noqa: BLE001
        _print({'exit': 4, 'problems': [{'code': 'internal', 'message': f'letitedit could not start: {e}'}]})
        return 4
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == 'capabilities':
            service.touch(h)
            _print(capabilities.build(h, service.entry_points(h)))
            return 0
        if cmd == 'watch':
            idle = float(rest[rest.index('--idle-s') + 1]) if '--idle-s' in rest else 600.0
            out = service.watch(h, idle_s=idle)
            _print(out)
            return out['exit']
        if cmd not in ('validate', 'submit', 'run', 'status', 'cancel', 'retry') or not rest:
            sys.stderr.write(USAGE)
            return 2
        ref = rest[0]
        if cmd == 'validate':
            service.touch(h)
            report = validate.validate(Path(ref), service.Knowledge(h))
            _print(report)
            return 0 if report['valid'] else 2
        if cmd == 'submit':
            service.touch(h, kick=False)
            out = service.submit(ref, h)
            _print(out.get('status') if out['exit'] == 0 else out)
            return out['exit']
        if cmd == 'run':
            out = service.run(ref, h)
            _print(out.get('result') or out)
            return out['exit']
        out = {'status': service.status, 'cancel': service.cancel, 'retry': service.retry}[cmd](ref, h)
        _print(out.get('status') if out['exit'] == 0 else out)
        return out['exit']
    except Exception as e:  # noqa: BLE001
        import letitedit.studio.files as files
        if isinstance(e, files.FolderBusy):
            _print({'exit': 4, 'problems': [{'code': 'busy', 'message': str(e)}]})
            return 4
        import traceback
        _print({'exit': 4, 'problems': [{'code': 'internal', 'message': f'letitedit hit a fault: {e}',
                                         'detail': traceback.format_exc()[-2000:]}]})
        return 4


if __name__ == '__main__':
    sys.exit(main())
