"""The progress file of "Learn from a video" (Home, and New video's "Match a video I like").

The editor writes <jobs folder>/<id>/job.json when the person starts learning and shows it; the AI doing the learning
(skills/letitedit-learn) reports through this script as it goes. Nothing here runs the learning.

    python learn_job.py progress <job.json> <stage> [message]   stages: fetch (a link only), measure, look, write, save
    python learn_job.py done <job.json> <look id>
    python learn_job.py fail <job.json> [message]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import tempfile
from pathlib import Path

STAGES = ['measure', 'look', 'write', 'save']
# 'fetch' (getting a video from a link) comes before them when the person gave a link; it keeps stage_index 0 so an
# editor that only knows the four stages shows it as the first one
FETCH = 'fetch'
WORDS = {FETCH: 'Getting the video', 'measure': 'Measuring the video', 'look': 'Watching it frame by frame', 'write': 'Writing the Look',
         'save': 'Saving it to Your Looks'}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _write(path: Path, data: dict):
    handle, temporary = tempfile.mkstemp(prefix='job-', suffix='.tmp', dir=path.parent)
    with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def read(path) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def progress(path, stage, message=''):
    if stage not in STAGES and stage != FETCH:
        raise ValueError(f'stage is one of {", ".join([FETCH] + STAGES)}')
    job = read(path)
    job.pop('finished', None)
    job.update(state='learning', stage=stage, stage_index=STAGES.index(stage) if stage in STAGES else 0, message=message or WORDS[stage],
               updated=_now())
    _write(Path(path), job)
    return job


def done(path, look_id):
    """The Look is saved. The AI named it when it saved it (an older editor's job carries the person's name, which
    still renames it); the job takes the saved name, and the Look gets its example clip from the person's own
    reference video (a Look without one still finishes)."""
    job = read(path)
    import letitedit.looks.learned_looks as learned_looks
    saved = learned_looks.finish_learning(look_id, job.get('name') or None, looks_root=job.get('my_looks'))
    # what the person reads is plain words; the technical lines go behind the dialog's Details, the full errors are in
    # each reference's step-errors.log
    limitations, details = learned_looks.plain_limitations(saved.get('limitations') or [])
    logs = [str(log) for log in saved.get('error_logs') or []]
    try:
        if not learned_looks.example(Path(job.get('my_looks') or learned_looks.root()) / look_id):
            learned_looks.make_example(look_id, looks_root=job.get('my_looks'))
        job.pop('example_error', None)
    except Exception as error:  # the example is a nicety: never fail the learning over it
        job['example_error'] = str(error)[:300]
    job.update(state='done', stage='save', stage_index=len(STAGES), look_id=look_id, message='Saved to Your Looks',
               name=saved.get('title') or job.get('name') or '', line=saved.get('line') or '',
               limitations=limitations, finished=_now(), updated=_now())
    if limitations:
        job['message'] += ' — ' + ' '.join(limitations)
    if details or logs or saved.get('step_errors'):
        job['details'] = list(dict.fromkeys(details + [str(line) for line in saved.get('step_errors') or []]
                                            + [f'The full errors are kept in {log}' for log in logs]))
    else:
        job.pop('details', None)
    _write(Path(path), job)
    return job


def fail(path, message=''):
    job = read(path)
    job.update(state='failed', message=message or 'Learning stopped', finished=_now(), updated=_now())
    _write(Path(path), job)
    return job


def main(argv=None):
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('progress')
    one.add_argument('job')
    one.add_argument('stage')
    one.add_argument('message', nargs='?', default='')
    two = commands.add_parser('done')
    two.add_argument('job')
    two.add_argument('look')
    three = commands.add_parser('fail')
    three.add_argument('job')
    three.add_argument('message', nargs='?', default='')
    args = parser.parse_args(argv)
    result = (progress(args.job, args.stage, args.message) if args.command == 'progress'
              else done(args.job, args.look) if args.command == 'done' else fail(args.job, args.message))
    print(json.dumps({'state': result['state'], 'stage': result.get('stage')}))


if __name__ == '__main__':
    main()
