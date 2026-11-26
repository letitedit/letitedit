"""The reference fake of the Studio: the same command line and job folders, made from the contract's examples.

For a caller's tests (letitedit Channel's, anyone's) and for letitedit's own contract tests. It runs every kind at
once, with placeholder files instead of media: nothing is rendered, no AI runs, the PC lock is never touched.

    python <bridge>\\letitedit\\studio\\fake.py [--home <folder>] validate|submit|run|status|cancel|retry <job folder | job.json | job id>
    python <bridge>\\letitedit\\studio\\fake.py [--home <folder>] capabilities | watch

--home (or LETITEDIT_STUDIO_FAKE_HOME) is the fake's own Studio folder (default: %TEMP%\\letitedit-studio-fake).
It needs Python 3.10+ and the jsonschema package; it imports nothing else of letitedit's but the contract's own modules
(files, contract_schemas, validate, state).

The real command line (bridge\\letitedit_studio.py) hands every command to this one when LETITEDIT_STUDIO_FAKE=1.
Everything it writes is marked fake (the fake_studio warning, versions.letitedit "fake", a .studio-fake file in each
job folder), and the real Studio never takes its folders, nor it the real Studio's.

Steering a test, by a top-level "x_test" object in job.json (letitedit itself ignores x_ fields):
    stages: n extra stages before the kind's own   stage_s: seconds each stage takes (default 0.05)
    fail: an error code, fail_at: the stage number  crash_at: the stage number where the worker process dies,
    crash_attempts: on how many attempts (default 1), crash_always: on every attempt
    wait: {"what": "pc_lock"|"ai_limit"|"person_working"|"memory", "s": seconds, "ahead": n} before the first stage
    ai_media: true: the result holds a generated picture (overlay_text's ai_generated_media then holds)
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import letitedit.studio.contract_schemas as contract   # noqa: E402
import letitedit.studio.estimates as estimates         # noqa: E402
import letitedit.studio.files as files                 # noqa: E402
import letitedit.studio.licences as licences           # noqa: E402
import letitedit.studio.overlays as overlays           # noqa: E402
import letitedit.studio.state as state                 # noqa: E402
import letitedit.studio.validate as validate           # noqa: E402

LANE_RANK = {'urgent': 0, 'normal': 1, 'dev': 2}
IDLE_S = float(os.environ.get('LETITEDIT_STUDIO_FAKE_IDLE', '60'))
NO_WINDOW = 0x08000000
DETACHED = 0x00000008 | 0x00000200

def _example_platforms():
    """Every preset a letitedit install has, as the capabilities example lists them (the fake answers the same)."""
    data = json.loads((contract.EXAMPLES / 'capabilities' / 'result.json').read_text(encoding='utf-8-sig'))
    return {p['id'] for p in data['output']['platforms']}


PLATFORMS = _example_platforms()
STAGES = {
    'capabilities': ['read'], 'index': ['files', 'transcripts', 'moments', 'photos', 'flags', 'write'],
    'match': ['fingerprint', 'search', 'write'], 'inspect': ['probe', 'transcript', 'pictures', 'sound', 'write'],
    'short.preview': ['log', 'story', 'rough', 'proxy'], 'short.final': ['fine', 'finish', 'review', 'export', 'proxy'],
    'batch_shorts': ['log', 'story', 'items'], 'still': ['layout', 'draw', 'check', 'export'],
    'revise': ['apply', 'review', 'export', 'proxy'], 'retext': ['apply', 'export', 'proxy'],
    'hooks': ['find', 'preview'], 'conform': ['probe', 'encode', 'cover', 'proxy'], 'learn': ['fetch', 'learn', 'save'],
}
VERSIONS = {'contract': contract.CONTRACT_VERSION, 'letitedit': 'fake'}


def home(given=None):
    h = Path(given or os.environ.get('LETITEDIT_STUDIO_FAKE_HOME') or Path(tempfile.gettempdir()) / 'letitedit-studio-fake')
    files.claim_home(h, 'fake')
    for sub in ('registry', 'inbox', 'jobs'):
        (h / sub).mkdir(parents=True, exist_ok=True)
    return h


def _fake_warnings(warnings):
    out = [w for w in (warnings or []) if w.get('code') != files.FAKE_WARNING['code']]
    return [dict(files.FAKE_WARNING)] + out


def _write_status(job_dir, job, **changes):
    """state.write_status, with the fake_studio warning always first in status.json's warnings."""
    current = state.read_status(job_dir).get('warnings')
    changes['warnings'] = _fake_warnings(changes['warnings'] if 'warnings' in changes else current)
    return state.write_status(job_dir, job, **changes)


def _write_result(job_dir, job, state_, versions, cost, **kw):
    """state.write_result, with the fake_studio warning in result.json (status.json has it from the start)."""
    kw['warnings'] = _fake_warnings(kw.get('warnings'))
    return state.write_result(job_dir, job, state_, versions, cost, **kw)


def _mark(job_dir, h=None, job_id=None):
    """Take a job folder for the fake, this Studio folder (h) and this job id (atomically: the real Studio, or another
    fake folder, can't take it at the same moment) and mark it. False when anyone else has it; then nothing is
    written."""
    if not files.claim_side(job_dir, 'fake', home=h, job_id=job_id):
        return False
    (Path(job_dir) / files.FAKE_MARK).write_text('letitedit Studio reference fake\n', encoding='utf-8')
    return True


def _real_folder(p):
    return p.is_dir() and not files.is_fake_folder(p) and ((p / 'status.json').is_file()
                                                          or files.side_of(p) not in (None, 'fake'))


def _side_refused(report, job_dir):
    return {'exit': 2, **report, 'valid': False, 'problems': [
        {'field': 'output_dir', 'code': 'output_dir_refused', 'message': f"The job folder {job_dir} belongs to "
         "letitedit's real Studio; the reference fake never takes one over. Use a new folder."}] + report['problems']}


def _not_found(ref):
    p = Path(str(ref))
    p = p.parent if p.name == 'job.json' else p
    why = (" That folder belongs to letitedit's real Studio; the reference fake never reads it."
           if _real_folder(p) else '')
    return {'exit': 2, 'problems': [{'field': 'job', 'code': 'not_found', 'message': f'No job {ref} here.{why}'}]}


def _reg(h, job_id):
    return Path(h) / 'registry' / f'{job_id}.json'


def find(h, ref):
    ref = str(ref)
    if validate_id(ref):
        entry = files.read_json(_reg(h, ref))
        if entry:
            return Path(entry['job_dir'])
        if '.' in ref:                                     # a batch item: <batch job id>.<idea_id>
            batch, item = ref.split('.', 1)
            entry = files.read_json(_reg(h, batch))
            if entry and (Path(entry['job_dir']) / 'items' / item / 'result.json').exists():
                return Path(entry['job_dir']) / 'items' / item
    p = Path(ref)
    if p.is_file() and p.name == 'job.json':
        p = p.parent
    if _real_folder(p):
        return None                                        # the real Studio's job: never the fake's
    return p if p.is_dir() and ((p / 'job.json').is_file() or (p / 'result.json').is_file()) else None


def validate_id(ref):
    import re
    return bool(re.match(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$', ref))


def knowledge(h):
    return {'kinds': {k: True for k in contract.kinds()}, 'looks': None, 'platforms': PLATFORMS, 'layouts': None,
            'ai_available': None, 'install_root': None, 'find_job': lambda ref: find(h, ref), 'side': 'fake',
            'home': str(h),
            'owns': lambda job_id, d: _owns(h, job_id, d)}


def _owns(h, job_id, job_dir):
    if not (isinstance(job_id, str) and validate_id(job_id)):
        return False
    entry = files.read_json(_reg(h, job_id)) or {}
    return bool(entry.get('job_dir')) and validate._norm(entry['job_dir']) == validate._norm(job_dir)


# ------------------------------------------------------------------ the front door

def submit(ref, h, start=True):
    """As letitedit's: one submit at a time (the registry's lock); the registry entry is written whole first (state
    'reserving'), then the folder's files, then state 'queued'; repair() finishes one a crash interrupted."""
    report = validate.validate(ref, knowledge(h))
    job, _, problem = validate.load(ref)
    if problem or not isinstance(job, dict) or not report.get('job_dir'):
        return {'exit': 2, **report}
    job_dir, job_id = Path(report['job_dir']), job.get('job_id')
    reg = _reg(h, job_id) if isinstance(job_id, str) and validate_id(job_id) else None
    codes = {p['code'] for p in report['problems']}
    with files.folder_lock(Path(h) / 'registry'):
        entry = (files.read_json(reg) or {}) if reg is not None else {}
        if entry and entry.get('state') != 'rejected':
            if entry.get('hash') != files.job_hash(job) or validate._norm(entry['job_dir']) != validate._norm(job_dir):
                return {'exit': 2, **report, 'valid': False, 'problems': [
                    {'field': 'job_id', 'code': 'job_id_conflict', 'message': f'The job id {job_id} was already used '
                     'for a different job. Use a new job id.'}] + report['problems']}
            if entry.get('state') == 'reserving':
                if not _mark(job_dir, h, job_id):
                    return _side_refused(report, job_dir)
                with files.folder_lock(job_dir):
                    _finish(h, entry, job)
            return {'exit': 0, 'already': True, 'status': status(job_id, h)['status']}
        if not report['valid']:
            if (reg is not None and job_dir.is_dir() and not codes & {'output_dir_refused', 'unsupported_version'}
                    and _mark(job_dir, h, job_id)):
                code = validate.first_code(report)
                err = state.error(code, 'The job was refused: ' + '; '.join(p['message'] for p in report['problems'][:3]))
                files.write_json(reg, {'job_id': job_id, 'job_dir': str(job_dir), 'hash': files.job_hash(job),
                                       'state': 'rejected'})
                if state.result_exists(job_dir):
                    _archive(job_dir, 'rejected')
                _write_status(job_dir, job, state='queued', priority=report['lane'], submitted=files.now_iso(),
                              message='Checking the job')
                state.event(job_dir, job, 'rejected', error=err)
                _write_result(job_dir, job, 'failed', VERSIONS, state.cost_line(time.time()), err=err)
            return {'exit': 2, **report}
        if not _mark(job_dir, h, job_id):         # taken for the fake before anything is written
            return _side_refused(report, job_dir)
        with files.folder_lock(job_dir):          # the destination's own lock, kept through acceptance
            if not files.holds(job_dir, 'fake', h, job_id):
                return _side_refused(report, job_dir)
            entry = {'job_id': job_id, 'job_dir': str(job_dir), 'hash': files.job_hash(job), 'lane': report['lane'],
                     'submitted_t': time.time(), 'attempts': 0, 'max_attempts': int(job.get('max_attempts') or 3),
                     'state': 'reserving', 'warnings': report['warnings'] or None}
            files.write_json(reg, entry)
            if state.result_exists(job_dir):
                _archive(job_dir, 'rejected')
            _finish(h, entry, job)
    answer = reconcile(h, job_id)       # queued (or cancelled at its claim), as letitedit answers a new submit
    if start:
        ensure_worker(h)
    return {'exit': 0, 'status': answer}


def _archive(job_dir, tag):
    hist = Path(job_dir) / 'history'
    hist.mkdir(exist_ok=True)
    os.replace(Path(job_dir) / 'result.json', hist / f'result-{tag}-{time.time_ns()}.json')


def _finish(h, entry, job):
    job_dir = Path(entry['job_dir'])
    seen = {e.get('type') for e in files.read_events(job_dir)}
    if (job_dir / 'cancel').exists() and 'queued' not in seen:
        _cancel_at_claim(h, entry, job, seen)
        return
    if 'accepted' not in seen:
        _write_status(job_dir, job, state='queued', priority=entry['lane'], submitted=files.now_iso(), attempt=0,
                      max_attempts=entry['max_attempts'], message='Queued', warnings=entry.get('warnings'))
        state.event(job_dir, job, 'accepted', message='Valid; queued.')
        state.event(job_dir, job, 'queued')
    entry['state'] = 'queued'
    files.write_json(_reg(h, entry['job_id']), entry)


def _cancel_at_claim(h, entry, job, seen=()):
    """As letitedit's: a folder holding a cancel file when it is taken is accepted and ends cancelled at once."""
    job_dir = Path(entry['job_dir'])
    if not state.result_exists(job_dir):
        if 'accepted' not in seen:
            _write_status(job_dir, job, state='queued', priority=entry['lane'], submitted=files.now_iso(), attempt=0,
                          max_attempts=entry['max_attempts'], message='Cancelled before it ran',
                          warnings=entry.get('warnings'))
            state.event(job_dir, job, 'accepted', message='Valid; its folder already held a cancel file.')
        if 'cancel_requested' not in seen:
            state.event(job_dir, job, 'cancel_requested')
        _write_result(job_dir, job, 'cancelled', VERSIONS, state.cost_line(time.time()),
                      err=state.error('cancelled', 'The job was cancelled before it ran: its folder held a cancel file '
                                      'when it was taken. Nothing was made.'))
    entry['state'] = 'queued'
    files.write_json(_reg(h, entry['job_id']), entry)


def repair(h):
    """Finish submits a crash interrupted; a changed job.json ends its reservation with a failed result."""
    for f in Path(h, 'registry').glob('*.json'):
        entry = files.read_json(f)
        if not entry or entry.get('state') != 'reserving':
            continue
        with files.folder_lock(Path(h) / 'registry'):
            entry = files.read_json(f) or {}
            if entry.get('state') != 'reserving':
                continue
            if not _mark(entry['job_dir'], h, entry.get('job_id')):
                entry['state'] = 'rejected'                # another owner has the folder: nothing more is written
                entry['why'] = f"the job folder was taken by {files.taken_by(entry['job_dir'])}"
                files.write_json(f, entry)
                continue
            job = files.read_json(Path(entry['job_dir']) / 'job.json')
            if isinstance(job, dict) and files.job_hash(job) == entry['hash']:
                _finish(h, entry, job)
                continue
            entry['state'] = 'rejected'
            files.write_json(f, entry)
            stub = job if isinstance(job, dict) else {'job_id': entry['job_id']}
            _write_result(entry['job_dir'], stub, 'failed', VERSIONS, state.cost_line(time.time()),
                          err=state.error('job_id_conflict', 'Sending this job was interrupted and job.json changed '
                                          'before it was finished; send it with a new job id.'))


def _entries(h):
    out = []
    for f in Path(h, 'registry').glob('*.json'):
        e = files.read_json(f)
        if e and e.get('state', 'queued') == 'queued' and not state.result_exists(e['job_dir']):
            out.append(e)
    return out


def _order(h):
    """Waiting jobs in the order the fake worker takes them: by lane; within a lane resuming first, then oldest."""
    waiting = []
    for e in _entries(h):
        st = state.read_status(e['job_dir'])
        if st.get('state') == 'queued':
            waiting.append((LANE_RANK.get(e['lane'], 1), 0 if st.get('resuming') else 1, e['submitted_t'], e['job_id']))
    return [w[-1] for w in sorted(waiting)]


def reconcile(h, job_id):
    entry = files.read_json(_reg(h, job_id))
    job_dir = Path(entry['job_dir'])
    job = files.read_json(job_dir / 'job.json') or {}
    st = state.read_status(job_dir)
    if state.result_exists(job_dir):
        state.finish_from_result(job_dir, job)
        return state.read_status(job_dir)
    if st.get('state') == 'running' and not files._pid_alive(entry.get('pid')):
        if entry['attempts'] >= entry['max_attempts']:
            state.event(job_dir, job, 'interrupted', attempt=entry['attempts'])
            _write_result(job_dir, job, 'failed', VERSIONS, state.cost_line(entry['submitted_t']),
                               err=state.error('interrupted_too_often', "The fake's process stopped before the job "
                                               'finished, as many times as max_attempts allows.'),
                               attempts=entry['attempts'])
            return state.read_status(job_dir)
        state.event(job_dir, job, 'interrupted', attempt=entry['attempts'],
                    message="The fake's process stopped before the job finished.")
        st = _write_status(job_dir, job, state='queued', resuming=True, heartbeat=None, waiting_on=None,
                                message='Stopped part way; it carries on from the start of its last stage.')
    if (job_dir / 'cancel').exists() and st.get('state') == 'queued':
        with files.folder_lock(job_dir):        # decided under the lock the worker starts a job under
            st = state.read_status(job_dir)
            if st.get('state') == 'queued':
                _write_result(job_dir, job, 'cancelled', VERSIONS, state.cost_line(entry['submitted_t']),
                              err=state.error('cancelled', 'The job was cancelled before it ran.'))
                return state.read_status(job_dir)
    if st.get('state') == 'queued':
        order = _order(h)
        i = order.index(job_id) if job_id in order else len(order)
        running = next((e['job_id'] for e in _entries(h)
                        if state.read_status(e['job_dir']).get('state') == 'running'), None)
        return _write_status(job_dir, job, queue={'position': i + 1, 'jobs_ahead': i + (1 if running else 0),
                                                       'running_job': running})
    return st


def touch(h):
    repair(h)
    scan_inbox(h)
    for e in _entries(h):
        reconcile(h, e['job_id'])
    if _order(h):
        ensure_worker(h)


def status(ref, h):
    touch(h)
    folder = find(h, ref)
    if folder is None:
        return _not_found(ref)
    job = files.read_json(folder / 'job.json') or {}
    entry = files.read_json(_reg(h, job['job_id'])) if job.get('job_id') else None
    if entry and entry.get('state', 'queued') == 'queued':
        return {'exit': 0, 'status': reconcile(h, job['job_id'])}
    state.finish_from_result(folder)
    return {'exit': 0, 'status': state.read_status(folder)}


def cancel(ref, h):
    folder = find(h, ref)
    if folder is None and validate_id(str(ref)):
        claim = files.claim_inbox_file(Path(h) / 'inbox', f'{ref}.json')     # still waiting in the inbox (1.1)
        if claim is not None:
            try:
                problems = _take(h, claim[1], cancel=True, expected_id=str(ref))
            except files.FolderBusy as e:
                problems = [{'field': 'job', 'code': 'busy', 'message': str(e)}]
            files.finish_claim(claim[0], claim[1], problems, contract.CONTRACT_VERSION)
            if problems:
                return {'exit': 2, 'problems': problems}
        files.wait_for_claims(Path(h) / 'inbox')
        folder = find(h, ref)
    if folder is None:
        return _not_found(ref)
    job = files.read_json(folder / 'job.json') or {}
    with files.folder_lock(folder):                # the request is recorded before the worker can act on it
        if not state.result_exists(folder):
            state.event(folder, job, 'cancel_requested')
            _write_status(folder, job, cancel_requested=True)
            (folder / 'cancel').write_text(files.now_iso(), encoding='utf-8')
    return status(ref, h)


def retry(ref, h):
    folder = find(h, ref)
    result = files.read_json(folder / 'result.json') if folder else None
    if not result or result.get('state') not in ('failed', 'cancelled'):
        return {'exit': 2, 'problems': [{'field': 'job', 'code': 'not_retryable',
                                         'message': 'Only a failed or cancelled job can be retried.'}]}
    job = files.read_json(folder / 'job.json') or {}
    entry = files.read_json(_reg(h, job.get('job_id', ''))) or {}
    if entry.get('state') == 'rejected':
        return {'exit': 2, 'problems': [{'field': 'job', 'code': 'not_retryable', 'message': 'A refused job is sent '
                                         'again with submit, once job.json is fixed.'}]}
    if files.job_hash(job) != entry.get('hash'):
        return {'exit': 2, 'problems': [{'field': 'job_id', 'code': 'job_id_conflict', 'message': 'job.json changed '
                                         'after this job was accepted; a changed job needs a new job id. Nothing was '
                                         'retried.'}]}
    hist = folder / 'history'
    hist.mkdir(exist_ok=True)
    n = len(list(hist.glob('result-*.json'))) + 1
    with files.folder_lock(folder):                   # as letitedit's: the ending attempt's cancel file, renamed
        files.hand_off_cancel(folder, n)
        os.replace(folder / 'result.json', hist / f'result-{n}.json')
    entry = files.read_json(_reg(h, job['job_id']))
    entry['attempts'] = 0
    files.write_json(_reg(h, job['job_id']), entry)
    _write_status(folder, job, state='queued', error=None, finished=None, resuming=None, cancel_requested=None,
                       message='Queued again; it carries on from its last finished stage.')
    state.event(folder, job, 'queued', message='Retry')
    ensure_worker(h)
    return status(job['job_id'], h)


def run(ref, h, timeout_s=600):
    out = submit(ref, h)
    if out['exit'] != 0:
        return out
    job_id = out['status']['job_id']
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        st = status(job_id, h)['status']
        if st.get('state') in state.FINAL:
            r = files.read_json(find(h, job_id) / 'result.json')
            return {'exit': {'done': 0, 'failed': 1, 'cancelled': 3}[r['state']], 'result': r}
        time.sleep(0.2)
    return {'exit': 1, 'note': 'Still running.'}


def scan_inbox(h):
    """As letitedit's: each file claimed by an atomic rename, checked whole, written into its job folder only when
    valid."""
    for original, claimed in files.claim_inbox(Path(h) / 'inbox'):
        try:
            problems = _take(h, claimed)
        except files.FolderBusy as e:
            problems = [{'field': 'job', 'code': 'busy', 'message': str(e)}]
        files.finish_claim(original, claimed, problems, contract.CONTRACT_VERSION)
    files.wait_for_claims(Path(h) / 'inbox')


def _take(h, claimed, cancel=False, expected_id=None):
    job = files.read_json(claimed)
    if not isinstance(job, dict) or not isinstance(job.get('job_id'), str) or not validate_id(job['job_id']):
        return [{'field': 'job_id', 'code': 'invalid_job', 'message': 'Not a job.json with a valid job_id.'}]
    if expected_id is not None and job['job_id'] != expected_id:
        return [{'field': 'job_id', 'code': 'invalid_job',
                 'message': f'The inbox file {expected_id}.json holds the job {job["job_id"]}: an inbox file is '
                            'named after its own job id. Nothing was cancelled or written.'}]
    out_dir = job.get('output_dir')
    if out_dir is not None and not (isinstance(out_dir, str) and Path(out_dir).is_absolute()):
        return [{'field': 'output_dir', 'code': 'invalid_job', 'message': 'output_dir must be an absolute path.'}]
    job_dir = Path(out_dir) if out_dir else Path(h) / 'jobs' / job['job_id']
    check = validate.validate(job=job, job_dir=job_dir, knowledge=knowledge(h))
    if not check['valid']:
        return check['problems']
    refused = [{'field': 'output_dir', 'code': 'output_dir_refused', 'message': f'The job folder {job_dir} is taken.'}]
    with files.folder_lock(Path(h) / 'registry'):          # as letitedit's: registry, then the destination's own lock
        if not files.claim_side(job_dir, 'fake', home=h, job_id=job['job_id']):
            return refused
        with files.folder_lock(job_dir):
            existing = files.read_json(job_dir / 'job.json')
            if existing is not None and files.job_hash(existing) != files.job_hash(job):
                return [{'field': 'job_id', 'code': 'job_id_conflict',
                         'message': f'{job_dir} already holds a different job.json.'}]
            if existing is None:
                if not files.holds(job_dir, 'fake', h, job['job_id']):
                    return refused
                files.write_json(job_dir / 'job.json', job)
            if cancel and not _owns(h, job['job_id'], job_dir):
                (job_dir / 'cancel').write_text(files.now_iso(), encoding='utf-8')
            out = submit(job_dir, h)
    return None if out['exit'] == 0 else (out.get('problems') or [{'field': 'job', 'code': 'invalid_job',
                                                                  'message': 'Refused.'}])


# ------------------------------------------------------------------ the worker

def ensure_worker(h):
    lock = Path(h) / 'worker.lock'
    try:
        pid = int(lock.read_text(encoding='utf-8').split()[0])
        if files._pid_alive(pid):
            return
    except (OSError, ValueError, IndexError):
        pass
    flags = (NO_WINDOW | DETACHED) if os.name == 'nt' else 0
    args = [sys.executable, str(Path(__file__).resolve()), '--home', str(h), '_worker']
    try:                                # out of any job its caller is in, when that job allows it
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags | (0x01000000 if os.name == 'nt' else 0), close_fds=True)
    except OSError:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, close_fds=True)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if files._pid_alive(int(lock.read_text(encoding='utf-8').split()[0])):
                return
        except (OSError, ValueError, IndexError):
            pass
        time.sleep(0.05)


def worker(h):
    lock = Path(h) / 'worker.lock'
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            if files._pid_alive(int(lock.read_text(encoding='utf-8').split()[0])):
                return
        except (OSError, ValueError, IndexError):
            pass
        lock.unlink(missing_ok=True)
        return worker(h)
    os.write(fd, f'{os.getpid()} {time.time():.0f}'.encode())
    os.close(fd)
    try:
        idle = time.monotonic()
        while time.monotonic() - idle < IDLE_S:
            scan_inbox(h)
            for e in _entries(h):
                reconcile(h, e['job_id'])
            order = _order(h)
            if not order:
                time.sleep(0.1)
                continue
            _run_one(h, order[0])
            idle = time.monotonic()
    finally:
        lock.unlink(missing_ok=True)


def _sleep(job_dir, seconds):
    t_end = time.monotonic() + seconds
    while time.monotonic() < t_end:
        if (Path(job_dir) / 'cancel').exists():
            raise KeyboardInterrupt
        time.sleep(min(0.02, max(0.0, t_end - time.monotonic())))


def _run_one(h, job_id):
    reg = _reg(h, job_id)
    entry = files.read_json(reg)
    job_dir = Path(entry['job_dir'])
    owner = files.owner_of(job_dir) or {}
    if (owner.get('side') != 'fake' or owner.get('home') and owner['home'] != files.home_key(h)
            or owner.get('job_id') and owner['job_id'] != job_id):   # anyone else's folder: never run, never written
        entry['state'] = 'rejected'
        entry['why'] = 'the job folder is not the fake\'s'
        files.write_json(reg, entry)
        return
    job = files.read_json(job_dir / 'job.json')
    if not isinstance(job, dict) or files.job_hash(job) != entry['hash']:
        stub = job if isinstance(job, dict) else {'job_id': job_id}
        _write_result(job_dir, stub, 'failed', VERSIONS, state.cost_line(time.time()),
                      err=state.error('job_id_conflict', 'job.json changed after this job was accepted, so it was '
                                      'not run. A changed job needs a new job id.'))
        return
    entry['attempts'] += 1
    entry['pid'] = os.getpid()
    files.write_json(reg, entry)
    attempt = entry['attempts']
    steer = job.get('x_test') if isinstance(job.get('x_test'), dict) else {}
    kind, tier = job['kind'], (job.get('inputs') or {}).get('tier')
    own = STAGES.get(f'{kind}.{tier}') or STAGES.get(kind) or ['work']
    if kind == 'short' and tier == 'final' and not job.get('from_job'):
        own = STAGES['short.preview'][:-1] + own
    plan = [f'x_wait_{k}' for k in range(1, int(steer.get('stages', 0)) + 1)] + own
    st = state.read_status(job_dir)
    done = list(st.get('x_done') or [])
    started = st.get('started') or files.now_iso()
    try:
        # As letitedit's: the start is one step under the folder's lock, so a cancel that ended the job first (an entry
        # point's reconcile, while this worker was picking it) is seen here and nothing of this attempt follows it.
        with state.attempt(job_dir):
            if st.get('resuming'):
                state.event(job_dir, job, 'resumed', attempt=attempt,
                            message='Carrying on from the start of its last stage.')
            state.event(job_dir, job, 'started', attempt=attempt)
            _write_status(job_dir, job, state='running', attempt=attempt, started=started, resuming=None,
                          heartbeat=files.now_iso(), queue={'position': 0, 'jobs_ahead': 0, 'running_job': job_id},
                          message='Running')
    except state.Ended:
        state.finish_from_result(job_dir, job)
        return
    t0 = time.time()
    try:
        wait = steer.get('wait')
        if isinstance(wait, dict) and attempt == 1 and not done:
            with state.attempt(job_dir):
                _write_status(job_dir, job, waiting_on={'what': wait.get('what', 'pc_lock'), 'since': files.now_iso(),
                                                        'ahead': int(wait.get('ahead', 1)),
                                                        'holder': 'another render (fake)'})
                state.event(job_dir, job, 'waiting', waiting_on=wait.get('what', 'pc_lock'))
            _sleep(job_dir, float(wait.get('s', 0.5)))
            with state.attempt(job_dir):
                _write_status(job_dir, job, waiting_on=None)
                state.event(job_dir, job, 'waiting_over', waiting_on=wait.get('what', 'pc_lock'))
        for i, name in enumerate(plan):
            if name in done:
                continue
            with state.attempt(job_dir):       # a job an entry point ended meanwhile starts no stage
                state.event(job_dir, job, 'stage_started', attempt=attempt, stage=name)
                _write_status(job_dir, job, stage=name, stage_index=i, stages_total=len(plan),
                              progress=round(i / len(plan), 4), heartbeat=files.now_iso(),
                              message=f'Stage {i + 1} of {len(plan)}: {name}')
            if steer.get('fail') and int(steer.get('fail_at', 1)) == i + 1:
                raise state.StudioError(steer['fail'], f'Test failure at stage {i + 1} ({name}).', stage=name)
            stage_s = float(steer.get('stage_s', 0.05))
            crash = int(steer.get('crash_at', 0)) == i + 1 and (steer.get('crash_always')
                                                               or attempt <= int(steer.get('crash_attempts', 1)))
            _sleep(job_dir, stage_s / 2 if crash else stage_s)
            if crash:
                os._exit(3)
            done.append(name)
            with state.attempt(job_dir):
                if job['kind'] == 'index' and name in INDEX_COUNTED:
                    _write_status(job_dir, job, counts=_index_counts(name),
                                  progress=round((i + 1) / len(plan), 4))
                _write_status(job_dir, job, x_done=done)
                state.event(job_dir, job, 'stage_done', attempt=attempt, stage=name,
                            progress=round((i + 1) / len(plan), 4))
        outputs, output, extra = make_result(h, job, job_dir)
        _write_status(job_dir, job, x_done=None)
        _write_result(job_dir, job, 'done', VERSIONS, _cost(job, t0), outputs=outputs, output=output,
                           started=started, attempts=attempt, extra=extra)
    except state.Ended:                 # an entry point ended the job while it ran: its result stands
        _write_status(job_dir, job, x_done=None)
        state.finish_from_result(job_dir, job)
    except KeyboardInterrupt:
        _write_status(job_dir, job, x_done=None)
        _write_result(job_dir, job, 'cancelled', VERSIONS, _cost(job, t0),
                           err=state.error('cancelled', 'The job was cancelled.'), started=started, attempts=attempt)
    except state.StudioError as e:
        _write_status(job_dir, job, x_done=None)
        _write_result(job_dir, job, 'failed', VERSIONS, _cost(job, t0), err=e.as_error(), started=started,
                           attempts=attempt)
    except Exception as e:  # noqa: BLE001 - a fault in the fake fails the job, never the worker
        import traceback
        _write_status(job_dir, job, x_done=None)
        _write_result(job_dir, job, 'failed', VERSIONS, _cost(job, t0),
                           err=state.error('internal', f'The fake hit a fault: {e}', detail=traceback.format_exc()),
                           started=started, attempts=attempt)


INDEX_COUNTED = ('files', 'transcripts', 'moments')


def _index_counts(stage):
    """status.json's counts at the end of an index stage (1.2), from the example library's files."""
    rows = [json.loads(x) for x in (contract.EXAMPLES / 'index' / 'files.jsonl').read_text(encoding='utf-8-sig')
            .splitlines() if x.strip()]
    if stage != 'files':
        rows = [r for r in rows if r.get('kind') in ('video', 'audio')]
    c = {'stage': stage, 'files_done': len(rows), 'files_total': len(rows)}
    if stage != 'files':
        minutes = round(sum(float(r.get('duration_s') or 0) for r in rows) / 60, 1)
        c.update(footage_min_done=minutes, footage_min_total=minutes)
    return c


def _cost(job, t0):
    if job['kind'] in ('capabilities', 'index', 'match', 'retext', 'conform', 'inspect'):
        return state.cost_line(t0, measured=True)
    return state.cost_line(t0, ai=ran_with(job), measured=True,
                           tokens={'input': 0, 'cache_write': 0, 'cache_read': 0, 'output': 0, 'total': 0})


PERSON_AI = {'engine': 'claude', 'model': 'fake', 'effort': 'medium'}     # the fake person's chat choice


def ran_with(job):
    """The AI a making job runs on, as letitedit decides (CONTRACT.md section 5): the job's `ai` over the person's
    chat choice, part by part; an effort or model without an engine is for the person's engine."""
    ai = job.get('ai') or {}
    if ai.get('engine') and ai['engine'] != PERSON_AI['engine']:
        return {'engine': ai['engine'], 'model': ai.get('model') or 'fake', 'effort': ai.get('effort') or 'medium'}
    return {**PERSON_AI, **{k: ai[k] for k in ('engine', 'model', 'effort') if ai.get(k)}}


# ------------------------------------------------------------------ results made from the examples

def _example(kind, tier=None):
    folder = contract.EXAMPLES / kind
    names = [f'result-{tier}.json', 'result.json'] if tier else ['result.json']
    for n in names:
        if (folder / n).exists():
            return json.loads((folder / n).read_text(encoding='utf-8-sig'))
    raise FileNotFoundError(folder)


def _placeholder(job_dir, rel, note=''):
    p = Path(job_dir) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(f'letitedit Studio fake placeholder (not media): {rel} {note}'.encode('utf-8'))


def _platform_ids(job, fallback):
    plats = (job.get('inputs') or {}).get('platforms')
    if not plats and job.get('from_job'):
        return fallback
    return [p['id'] if isinstance(p, dict) else p for p in plats or fallback]


def _job_rules(h, ref):
    """The rules an earlier job set (with their kinds), followed back through the jobs it continued; None: none set."""
    seen = set()
    while ref and ref not in seen:
        seen.add(ref)
        folder = find(h, ref)
        data = files.read_json(folder / 'job.json') if folder else None
        if not isinstance(data, dict):
            return None
        rules = (data.get('inputs') or {}).get('rules')
        if rules is not None:
            return rules
        ref = data.get('from_job')
    return None


def _job_platforms(h, ref):
    """The platforms an earlier job asked for (a preview has no platform files, but its job names them), followed back
    through the jobs it continued."""
    seen = set()
    while ref and ref not in seen:
        seen.add(ref)
        folder = find(h, ref)
        data = files.read_json(folder / 'job.json') if folder else None
        if not isinstance(data, dict):
            return []
        plats = (data.get('inputs') or {}).get('platforms')
        if plats:
            return [p['id'] if isinstance(p, dict) else p for p in plats]
        ref = data.get('from_job')
    return []


def _from_result(h, job):
    folder = find(h, job.get('from_job')) if job.get('from_job') else None
    return files.read_json(folder / 'result.json') if folder else None


def _ai_media(job, shared):
    """x_test.ai_media: the fake's result holds a generated picture, so a caller can test overlay_text's
    ai_generated_media both ways (the examples hold none)."""
    steer = job.get('x_test') if isinstance(job.get('x_test'), dict) else {}
    if not steer.get('ai_media') or 'provenance' not in shared:
        return
    shared['provenance'].setdefault('assets', []).append({
        'kind': 'generated_picture', 'what': 'a generated picture (fake)', 'source': 'image_generator',
        'licence': licences.block('generated'), 'ai_generated': True, 'ranges': [{'in': 4.2, 'out': 6.0}]})
    if 'ai_labels' in shared:
        shared['ai_labels']['generated_picture'] = True
        shared['ai_labels'].setdefault('items', []).append({'what': 'a generated picture (fake)', 'kind': 'picture',
                                                            'realistic': True, 'start': 4.2, 'end': 6.0})


def _with_overlays(job, result, text_items, item=None, earlier=None):
    """text_items with the overlay items decided for this job's files (overlays.decide): the job's own overlay_text,
    else (a final from a preview, a revise without it) the earlier job's items, decided again."""
    kept = [t for t in text_items or [] if 'overlay' not in t]
    own = 'overlay_text' in (job.get('inputs') or {}) or (item is not None and 'overlay_text' in (item[1] or {}))
    if job['kind'] == 'short' and job.get('from_job'):
        own = False                                   # a final from a preview keeps the preview's (input_ignored)
    given = None if own or earlier is None else overlays.carried(earlier.get('text_items'))
    return kept + overlays.decide(job, result, idea=item, given=given)


def _retext(job, text_items):
    """A retext's changes applied to text_items (changed in place): the output's `applied`."""
    items = {t['id']: t for t in text_items or []}
    applied = []
    for c in (job.get('inputs') or {}).get('changes') or []:
        t = items.get(c['id'])
        if t is None:
            applied.append({'id': c['id'], 'status': 'refused', 'reason': 'unknown_id'})
        elif t['editable'] == 'baked':
            applied.append({'id': c['id'], 'status': 'refused', 'reason': 'baked',
                            'message': 'This text is inside a picture letitedit cannot redraw.'})
        elif t.get('max_chars') and len(c['text']) > t['max_chars']:
            applied.append({'id': c['id'], 'status': 'refused', 'reason': 'too_long'})
        elif t['text'] == c['text']:
            applied.append({'id': c['id'], 'status': 'unchanged_same_text'})
        else:
            t['text'] = c['text']
            applied.append({'id': c['id'], 'status': 'changed' if t['editable'] == 'live' else 'redrawn'})
    return applied


def legacy_still_fields(output, shared, earlier):
    """A still's retext answers a 1.0 or 1.1 caller in the shape it knows (CONTRACT.md, retext): `files` empty (the
    pictures are in `sets`), `project` (the still's working project), and `choices` and `review` that hold for a
    still (no cuts, no words spoken, not reviewed again)."""
    output.setdefault('files', [])
    output.setdefault('project', (earlier.get('output') or {}).get('project') or 'work/still.mlt')
    earlier_choices = earlier.get('choices') or {}
    sets = output.get('sets') or [{}]
    moments = [{'moment_id': m, 'file_id': s.get('file_id'), 'in': s.get('in', 0), 'out': s.get('out', 0)}
               for s in (shared.get('provenance') or {}).get('sources') or [] if s.get('file_id')
               for m in s.get('moment_ids') or []]
    shared['choices'] = {**{'look_id': earlier_choices.get('look_id') or 'auto', 'hook_kind': 'other',
                            'first_3s': f"A still ({sets[0].get('size', 'picture')}).", 'duration_s': 0.0,
                            'cuts_per_min': 0.0, 'words_per_min': 0.0, 'caption_style': 'none',
                            'music_kind': 'none', 'broll_share': 0.0, 'moments': moments}, **earlier_choices}
    shared['review'] = earlier.get('review') or {'verdict': 'not_reviewed',
                                                 'plain': 'Only text changed; a still has no review of its own.'}


def _still_revision(h, job, job_dir, earlier):
    """A still's revise (contract 1.1) or retext (1.2): a still's output and fields, plus what changed: the notes
    applied to its text, layout or picture choice, or the retext's changes applied to its text items. Its provenance,
    AI labels and music are the earlier job's."""
    ex = copy.deepcopy(_example('still'))
    output = copy.deepcopy(earlier.get('output') or ex['output'])
    for s_ in output.get('sets') or []:
        s_['files'] = [f'files/{Path(f).name}' for f in s_.get('files') or []]
    for k in ('what_changed', 'revision_of', 'changes', 'applied'):
        output.pop(k, None)
    shared = {k: copy.deepcopy(earlier.get(k, ex.get(k))) for k in ('provenance', 'ai_labels', 'music', 'text_items')}
    licences.fonts_for_version(shared.get('provenance'), job.get('contract_version'))
    if job['kind'] == 'retext':
        output.update({'applied': _retext(job, shared['text_items']), 'revision_of': job.get('from_job'),
                       'what_changed': 'The text items were changed (fake).'})
        legacy_still_fields(output, shared, earlier)
    else:
        notes = (job.get('inputs') or {}).get('notes') or []
        output.update({'what_changed': 'The notes were applied to the still (fake).',
                       'revision_of': job.get('from_job'),
                       'changes': [{'note': i, 'done': 'yes', 'said': 'Done (fake).'} for i in range(len(notes))]})
    rules = (job.get('inputs') or {}).get('rules')
    if rules is None:
        rules = _job_rules(h, job.get('from_job')) or [{'id': r['id']} for r in earlier.get('rules') or []]
    shared['rules'] = rule_results(rules)
    shared['proxy'] = {'poster': 'proxy/poster.jpg'}
    if job['kind'] != 'retext':                       # a retext adds no media: only the earlier job's are in it
        _ai_media(job, shared)
    ojob = job                                        # the still's own platforms, as the earlier job asked for them
    if not (job.get('inputs') or {}).get('platforms') and _job_platforms(h, job.get('from_job')):
        ojob = {**job, 'inputs': {**(job.get('inputs') or {}), 'platforms': _job_platforms(h, job.get('from_job'))}}
    shared['text_items'] = _with_overlays(ojob, {**shared, 'output': output}, shared.get('text_items'),
                                          earlier={'text_items': shared.get('text_items')})
    outputs = []
    for rel, role in sorted({(f, 'image') for s_ in output.get('sets') or [] for f in s_['files']}
                            | {('proxy/poster.jpg', 'poster')}):
        _placeholder(job_dir, rel)
        outputs.append(files.output_entry(job_dir, rel, role, location_metadata='none'))
    return outputs, output, shared


def make_result(h, job, job_dir, item=None):
    """(outputs, output, the shared making fields) for a finished fake job, files written as placeholders. item: a
    batch item's (index, idea)."""
    kind = job['kind']
    tier = (job.get('inputs') or {}).get('tier')
    earlier = _from_result(h, job)
    of_still = kind in ('revise', 'retext') and earlier is not None and overlays.is_still(earlier)
    if kind in ('revise', 'retext') and not tier and earlier:
        tier = earlier.get('tier')
    if of_still:                                      # a still's revise (1.1) or retext (1.2) returns a still
        return _still_revision(h, job, job_dir, earlier)
    ex = copy.deepcopy(_example(kind, tier if kind == 'short' else None))
    output = ex.get('output') or {}
    shared = {k: ex[k] for k in ('provenance', 'ai_labels', 'music', 'rules', 'choices', 'text_items', 'proxy',
                                 'review') if k in ex}
    if kind in ('short', 'revise', 'retext') and tier:
        shared['tier'] = tier
    rules = (job.get('inputs') or {}).get('rules')
    if rules is None and earlier:
        rules = _job_rules(h, job.get('from_job')) or [{'id': r['id']} for r in earlier.get('rules') or []]
    if 'rules' in shared or rules:
        shared['rules'] = rule_results(rules, preview=tier == 'preview')
    if kind in ('short', 'revise', 'retext'):
        fallback = ([f['platform'] for f in (earlier or {}).get('output', {}).get('files', [])]
                    or _job_platforms(h, job.get('from_job')) or ['youtube_shorts'])
        plats = _platform_ids(job, fallback)
        is_preview = tier == 'preview'
        output['files'] = [] if is_preview else [
            {'platform': p, 'status': 'made', 'video': f'files/{p}.mp4', 'srt': 'files/captions.srt',
             'cover': 'files/cover.jpg'} for p in plats]
        output['project'] = 'project/project.mlt'
        output.pop('post_text', None)
        if ((job.get('inputs') or {}).get('deliver') or {}).get('post_text'):
            output['post_text'] = {p: 'A suggested caption (fake).' for p in plats}
        if is_preview:
            shared['review'] = {'verdict': 'not_reviewed', 'plain': 'A preview is not reviewed; the final is.'}
        if earlier and earlier.get('text_items'):
            shared['text_items'] = copy.deepcopy(earlier['text_items'])
        if kind in ('revise', 'retext'):
            output['revision_of'] = job.get('from_job')
        if kind == 'revise':
            notes = (job.get('inputs') or {}).get('notes') or []
            output['changes'] = [{'note': i, 'done': 'yes', 'said': 'Done (fake).'} for i in range(len(notes))]
        if kind == 'retext':
            output['applied'] = _retext(job, shared.get('text_items'))
            shared['review'] = {'verdict': 'not_reviewed', 'plain': 'Only text changed.'}
            if earlier:                               # only text changed: the earlier job's media and their provenance
                shared.update(overlays.carry_media(earlier))
                licences.fonts_for_version(shared.get('provenance'), job.get('contract_version'))
            shared['text_items'] = _with_overlays(job, {**shared, 'output': output}, shared.get('text_items'),
                                                  earlier={'text_items': shared.get('text_items')})
    if kind == 'still':
        licences.fonts_for_version(shared.get('provenance'), job.get('contract_version'))   # 1.6: the font's id
        sizes = (job.get('inputs') or {}).get('sizes') or ['story_9x16']
        output['sets'] = [{'size': s, 'files': [f'files/{s}.png'], 'alt_text': 'A placeholder picture (fake).'}
                          for s in sizes]
        shared['proxy'] = {'poster': 'proxy/poster.jpg'}
        shared['rules'] = shared.get('rules') or []
    if kind in ('short', 'revise', 'still'):
        _ai_media(job, shared)
        shared['text_items'] = _with_overlays(job, {**shared, 'output': output}, shared.get('text_items'), item,
                                              earlier)
    if kind == 'batch_shorts':
        items = []
        for n, idea in enumerate((job.get('inputs') or {}).get('ideas') or []):
            item_job = {**job, 'kind': 'short', 'job_id': f'{job["job_id"]}.{idea["idea_id"]}',
                        'inputs': {**job['inputs'], 'idea': idea}}
            item_job['inputs'].pop('ideas', None)
            folder = Path(job_dir) / 'items' / idea['idea_id']
            outs, out, extra = make_result(h, item_job, folder, item=(n, idea))
            r = {'contract_version': contract.CONTRACT_VERSION, 'job_id': item_job['job_id'], 'kind': 'short',
                 'tier': job['inputs'].get('tier'), 'state': 'done', 'finished': files.now_iso(), 'versions': VERSIONS,
                 'cost': _cost(item_job, time.time()), 'outputs': outs, **extra, 'output': out,
                 'warnings': _fake_warnings([])}
            licences.for_job(r, job.get('contract_version'))      # a batch item answers in the batch's version
            files.write_json(folder / 'result.json', r)
            items.append({'idea_id': idea['idea_id'], 'state': 'done',
                          'result': f'items/{idea["idea_id"]}/result.json'})
        output = {'shared': {'log': 'shared/log.json', 'story_plan': 'shared/story_plan.json'}, 'items': items}
        shared = {}
    if kind == 'capabilities':
        output['letitedit_version'] = 'fake'
        output['typical'] = fake_typical((job.get('inputs') or {}).get('ai') or output['ai']['default'])
        output['kinds'] = {k: {'available': True} for k in contract.kinds()}
        output['platforms'] = [p for p in output.get('platforms', [])]
    # every file the result names is written as a placeholder and listed with its hash
    paths = set()
    for k in ('video', 'poster'):
        if shared.get('proxy', {}).get(k):
            paths.add((shared['proxy'][k], 'proxy' if k == 'video' else 'poster'))
    if shared.get('review', {}).get('path'):
        paths.add((shared['review']['path'], 'review'))
    for f in (output.get('files') if kind in ('short', 'revise', 'retext', 'conform') else None) or []:
        for key, role in (('video', 'video'), ('srt', 'srt'), ('cover', 'cover')):
            if f.get(key):
                paths.add((f[key], role))
    if output.get('project'):
        paths.add((output['project'], 'project'))
    for s in output.get('sets') or []:
        for p in s['files']:
            paths.add((p, 'image'))
    for rel in ('shared/log.json', 'shared/story_plan.json') if kind == 'batch_shorts' else ():
        paths.add((rel, 'other'))
    for name in ('files', 'moments', 'photos', 'changes') if kind == 'index' else ():
        paths.add((output[name], 'index'))
    outputs = []
    media = {'video', 'cover', 'proxy', 'poster', 'image', 'motion_still', 'evidence'}
    for rel, role in sorted(paths):
        sample = contract.EXAMPLES / 'index' / Path(rel).name
        if kind == 'index' and sample.is_file():          # the library's lines, as the example has them
            (Path(job_dir) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(job_dir) / rel).write_bytes(sample.read_bytes())
        elif kind == 'index' and rel.endswith('.jsonl'):
            (Path(job_dir) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(job_dir) / rel).write_text('', encoding='utf-8')
        else:
            _placeholder(job_dir, rel)
        extra = {'location_metadata': 'none'} if role in media else {}
        if role == 'video' and rel.startswith('files/'):
            extra['platform'] = Path(rel).stem
        outputs.append(files.output_entry(job_dir, rel, role, **extra))
    return outputs, output, shared


# ------------------------------------------------------------------ the command line

def fake_typical(want):
    """capabilities.typical for the AI `want`, chosen from the example's figures as letitedit chooses (1.2)."""
    figures = {}
    for k, v in _example('capabilities')['output']['typical'].items():
        figures[k] = [dict(f) for f in v.get('by_ai') or []] or [{x: y for x, y in v.items() if x not in ('match', 'match_note')}]
    ref = {k: v[0] for k, v in figures.items()}
    return estimates.choose_all(ref, want, {k: v[1:] for k, v in figures.items() if len(v) > 1})


def rule_results(rules, preview=False):
    """The fake's rule results: nothing is checked, except that a final reports every prefer as not met, so a caller
    sees a missed prefer beside a verdict it doesn't move (contract 1.5)."""
    out = []
    for r in rules or []:
        if r.get('kind') == 'prefer' and not preview:
            out.append({'id': r['id'], 'status': 'not_met', 'how': 'ai_review',
                        'reason': 'The fake reports every prefer as not met; the verdict stays as the review gave it.'})
        else:
            out.append({'id': r['id'], 'status': 'could_not_check', 'how': 'not_checked',
                        'reason': 'The fake checks nothing.'})
    return out


def capabilities_output(h, entry=None):
    ex = _example('capabilities')['output']
    ex['typical'] = fake_typical(ex['ai']['default'])
    ex['letitedit_version'] = 'fake'
    ex['fake'] = True
    ex['kinds'] = {k: {'available': True, 'uses_ai': k in ('short', 'batch_shorts', 'still', 'revise', 'hooks', 'learn'),
                       'heavy': k != 'capabilities'} for k in contract.kinds()}
    cli = f'"{sys.executable}" "{entry}"' if entry else f'"{sys.executable}" "{Path(__file__).resolve()}" --home "{h}"'
    ex['entry_points'] = {'cli': cli,
                          'inbox': str(Path(h) / 'inbox'), 'studio_folder': str(h)}
    return ex


def main(argv=None, entry=None):
    """The fake's command line. entry: the real command line's entry file when letitedit_studio.py hands over to the
    fake (LETITEDIT_STUDIO_FAKE=1), named in capabilities.entry_points.cli."""
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    given = None
    if '--home' in argv:
        i = argv.index('--home')
        given = argv[i + 1]
        del argv[i:i + 2]
    h = home(given)
    if not argv:
        sys.stderr.write(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]

    def show(data):
        sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    if cmd == '_worker':
        worker(h)
        return 0
    if cmd == 'capabilities':
        show(capabilities_output(h, entry))
        return 0
    if cmd == 'watch':
        t_end = time.monotonic() + IDLE_S
        while time.monotonic() < t_end:
            touch(h)
            time.sleep(1)
        return 0
    if not rest:
        sys.stderr.write(__doc__)
        return 2
    ref = rest[0]
    if cmd == 'validate':
        touch(h)
        report = validate.validate(Path(ref), knowledge(h))
        show(report)
        return 0 if report['valid'] else 2
    if cmd == 'submit':
        scan_inbox(h)
        out = submit(ref, h)
    elif cmd == 'run':
        out = run(ref, h)
        show(out.get('result') or out)
        return out['exit']
    elif cmd in ('status', 'cancel', 'retry'):
        out = {'status': status, 'cancel': cancel, 'retry': retry}[cmd](ref, h)
    else:
        sys.stderr.write(__doc__)
        return 2
    show(out.get('status') if out['exit'] == 0 else out)
    return out['exit']


if __name__ == '__main__':
    sys.exit(main())
