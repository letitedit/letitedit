"""The Studio's front door: validate, submit, status, cancel, retry, run and the inbox (CONTRACT.md section 3).

The Studio folder (LETITEDIT_STUDIO_HOME, else %LOCALAPPDATA%\\letitedit\\studio) holds:
    registry\\<job_id>.json   job id -> its job folder, job.json's hash, lane, core/jobs.py id
    queue\\                   the core/jobs.py root that runs Studio jobs, one at a time, lane first
    inbox\\                   <job_id>.json dropped by a caller
    jobs\\<job_id>\\           the job folder of an inbox job that names no output_dir
Every entry point reads the inbox, brings each job's status.json up to date with its process (a stopped process, a
cancel before it ran, a job that gave up) and starts the worker when jobs are waiting.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path

import letitedit.core.jobs as jobs
import letitedit.core.long_paths as long_paths
import letitedit.core.paths as paths
import letitedit.studio.capabilities as capabilities
import letitedit.studio.contract_schemas as contract
import letitedit.studio.files as files
import letitedit.studio.runner as runner
import letitedit.studio.state as state
import letitedit.studio.validate as validate

RUNNER = 'letitedit.studio.runner:run'
TIMEOUT_S = {'capabilities': 600}
DEFAULT_TIMEOUT_S = 8 * 3600
JOB_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$')


def home():
    h = os.environ.get('LETITEDIT_STUDIO_HOME')
    if not h:
        base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        h = os.path.join(base, 'letitedit', 'studio')
    p = files.claim_home(h, 'letitedit')
    for sub in ('registry', 'queue', 'inbox', 'jobs'):
        (p / sub).mkdir(parents=True, exist_ok=True)
    return p


def queue_root(h):
    return Path(h) / 'queue'


def entry_points(h):
    script = paths.BRIDGE / 'letitedit_studio.py'
    exe = Path(sys.executable)
    if exe.name.lower() == 'pythonw.exe' and exe.with_name('python.exe').is_file():
        exe = exe.with_name('python.exe')          # the worker runs windowless; a caller needs the one that prints
    return {'cli': f'"{exe}" "{script}"', 'inbox': str(Path(h) / 'inbox'), 'studio_folder': str(h)}


class Knowledge:
    """What validate needs to know about this install, worked out only when a job asks."""

    def __init__(self, h):
        self.h = Path(h)
        self._cache = {}

    def get(self, key, default=None):
        if key in self._cache:
            return self._cache[key]
        if key == 'kinds':
            value = {k: v['available'] for k, v in capabilities.kinds_info().items()}
        elif key == 'looks':
            value = {lk['id'] for lk in capabilities.looks_list()[0]}
        elif key == 'platforms':
            value = {p['id'] for p in capabilities.platforms_list()}
        elif key == 'layouts':
            value = {layout['id'] for layout in capabilities.still_layouts()}
        elif key == 'ai_available':
            value = capabilities.ai_info()['available']
        elif key == 'install_root':
            value = str(capabilities.ROOT)
        elif key == 'find_job':
            value = lambda ref: find(self.h, ref)   # noqa: E731
        elif key == 'side':
            value = 'letitedit'
        elif key == 'home':
            value = str(self.h)
        elif key == 'owns':
            value = lambda job_id, d: owns(self.h, job_id, d)   # noqa: E731
        elif key == 'too_long':
            value = long_paths.too_long
        else:
            return default
        self._cache[key] = value
        return value


def _registry(h, job_id):
    return Path(h) / 'registry' / f'{job_id}.json'


def queue_id_for(job_id):
    """The core/jobs.py id of a Studio job: fixed by its job id, so a submit a crash interrupted is finished, never
    queued twice."""
    return f'studio-{job_id}'


def owns(h, job_id, job_dir):
    """True when this Studio already has job_id in job_dir (sent before, accepted or refused)."""
    if not (isinstance(job_id, str) and JOB_ID.match(job_id)):
        return False
    entry = files.read_json(_registry(h, job_id)) or {}
    return bool(entry.get('job_dir')) and validate._norm(entry['job_dir']) == validate._norm(job_dir)


def find(h, ref):
    """The job folder of a job id or a job folder this Studio knows, else None (never one the fake made)."""
    ref = str(ref)
    entry = files.read_json(_registry(h, ref)) if JOB_ID.match(ref) else None
    if entry:
        return Path(entry['job_dir'])
    p = Path(ref)
    if p.is_file() and p.name == 'job.json':
        p = p.parent
    if p.is_dir() and (p / 'job.json').is_file() and not files.is_fake_folder(p):
        return p
    return None


def _not_found(ref):
    p = Path(str(ref))
    p = p.parent if p.name == 'job.json' else p
    why = (' That folder was made by the reference fake (LETITEDIT_STUDIO_FAKE); the real letitedit never reads it.'
           if p.is_dir() and files.is_fake_folder(p) else '')
    return {'exit': 2, 'problems': [{'field': 'job', 'code': 'not_found', 'message': f'No job {ref} here.{why}'}]}


def _entry_for(h, ref):
    """(registry entry, job folder) for a job id, a job folder or a job.json path."""
    folder = find(h, ref)
    if folder is None:
        return None, None
    job = files.read_json(folder / 'job.json') or {}
    entry = files.read_json(_registry(h, job.get('job_id', ''))) if job.get('job_id') else None
    return entry, folder


def _refusal(report, code=None, message=None):
    problems = list(report.get('problems') or [])
    if code:
        problems.insert(0, {'field': 'job_id', 'code': code, 'message': message})
    return {'exit': 2, 'valid': False, 'problems': problems, 'warnings': report.get('warnings') or [],
            'job_id': report.get('job_id'), 'job_dir': report.get('job_dir')}


def _side_refusal(report, job_dir):
    return _refusal(report, 'output_dir_refused', f'The job folder {job_dir} was taken by {files.taken_by(job_dir)}; a '
                    'job folder belongs to one Studio folder and one job only. Use a new folder.')


def _claim(h, job_dir, job_id):
    """Take a job folder for this Studio folder and this job id (files.claim_side)."""
    return files.claim_side(job_dir, 'letitedit', home=h, job_id=job_id)


def _write_rejected(h, job_dir, job, report):
    """An invalid job in a folder letitedit may write to: status, events and result say why. The id is noted in the
    registry as refused (not a job: sending it again, fixed, is allowed)."""
    code = validate.first_code(report)
    lines = '; '.join(p['message'] for p in report['problems'][:3])
    err = state.error(code, f'The job was refused: {lines}', detail=str(report['problems'])[:2000])
    files.write_json(_registry(h, job['job_id']), {'job_id': job['job_id'], 'job_dir': str(job_dir),
                                                   'hash': files.job_hash(job), 'state': 'rejected'})
    if state.result_exists(job_dir):
        _archive_result(job_dir, 'rejected')
    state.write_status(job_dir, job, state='queued', priority=validate.lane(job), submitted=files.now_iso(),
                       attempt=0, message='Checking the job')
    state.event(job_dir, job, 'rejected', message=lines[:300], error=err)
    state.write_result(job_dir, job, 'failed', capabilities.versions(), state.cost_line(time.time()), err=err,
                       warnings=report.get('warnings'))


def _archive_result(job_dir, tag):
    hist = Path(job_dir) / 'history'
    hist.mkdir(exist_ok=True)
    shutil.move(str(Path(job_dir) / 'result.json'), str(hist / f'result-{tag}-{time.time_ns()}.json'))


def _complete(entry):
    """A registry entry of a job that is fully queued (older entries have no state, only a queue_id)."""
    return entry.get('state') == 'queued' or (entry.get('state') is None and bool(entry.get('queue_id')))


def submit(ref, h=None, start_worker=True):
    """Validate and queue a job (a job folder or a job.json path). Idempotent by job id. Returns {'exit', ...}.

    One submit at a time per Studio folder (the registry's lock; the order is always the registry's lock, then a job
    folder's). The job folder is first taken for the real side (files.claim_side, atomic: the reference fake can't
    take it at the same moment); then the registry entry is written whole, with state 'reserving' and the job's fixed
    queue id; then status and events; then the queue job; then state 'queued'. A crash anywhere in between is finished
    by the next entry point (repair_submissions), never left half-done."""
    h = Path(h) if h else home()
    report = validate.validate(ref, Knowledge(h))
    job, _, problem = validate.load(ref)
    if problem or not isinstance(job, dict) or not report.get('job_dir'):
        return _refusal(report)
    job_dir = Path(report['job_dir'])
    job_id = job.get('job_id')
    codes = {p['code'] for p in report['problems']}
    reg = _registry(h, job_id) if isinstance(job_id, str) and JOB_ID.match(job_id) else None
    with files.folder_lock(Path(h) / 'registry'):
        entry = (files.read_json(reg) or {}) if reg is not None else {}
        if entry and entry.get('state') != 'rejected':
            same_dir = validate._norm(entry.get('job_dir', '')) == validate._norm(job_dir)
            if entry.get('hash') != files.job_hash(job) or not same_dir:
                return _refusal(report, 'job_id_conflict', f'The job id {job_id} was already used for a different '
                                f'job ({entry.get("job_dir")}). Use a new job id.')
            if _complete(entry):
                return {'exit': 0, 'already': True, 'status': status(job_id, h)['status']}
            if not _claim(h, job_dir, job_id):
                return _side_refusal(report, job_dir)
            with files.folder_lock(job_dir):
                _finish_submission(h, entry, job, start_worker)      # a submit a crash interrupted
            return {'exit': 0, 'status': reconcile(h, entry)}
        if not report['valid']:
            if (reg is not None and job_dir.is_dir() and not codes & {'output_dir_refused', 'unsupported_version'}
                    and _claim(h, job_dir, job_id)):
                with files.folder_lock(job_dir):
                    _write_rejected(h, job_dir, job, report)
            return _refusal(report)
        if not _claim(h, job_dir, job_id):            # taken for this Studio folder and job before anything is written
            return _side_refusal(report, job_dir)
        with files.folder_lock(job_dir):              # the destination's own lock, kept through acceptance
            if not files.holds(job_dir, 'letitedit', h, job_id):
                return _side_refusal(report, job_dir)
            entry = {'job_id': job_id, 'job_dir': str(job_dir), 'hash': files.job_hash(job), 'lane': report['lane'],
                     'kind': job['kind'], 'submitted': files.now_iso(), 'queue_id': queue_id_for(job_id),
                     'state': 'reserving', 'warnings': report['warnings'] or None}
            files.write_json(reg, entry)
            if state.result_exists(job_dir):         # a refused try of this id, now valid: start clean
                _archive_result(job_dir, 'rejected')
            _finish_submission(h, entry, job, start_worker)
    return {'exit': 0, 'status': reconcile(h, entry)}


def _finish_submission(h, entry, job, start_worker=True):
    """The steps after the registry entry, each safe to repeat: status and events, the queue job, state 'queued'.
    A job folder holding a cancel file before the job was ever queued ends cancelled here and never runs."""
    job_dir = Path(entry['job_dir'])
    seen = {e.get('type') for e in files.read_events(job_dir)}
    if (job_dir / 'cancel').exists() and 'queued' not in seen and not (queue_root(h) / entry['queue_id']).is_dir():
        _cancel_at_claim(h, entry, job, seen)
        return
    if 'accepted' not in seen:
        state.write_status(job_dir, job, state='queued', priority=entry['lane'], submitted=entry['submitted'],
                           attempt=0, max_attempts=int(job.get('max_attempts') or 3), progress=0, message='Queued',
                           resuming=None, error=None, finished=None, warnings=entry.get('warnings'), waiting_on=None,
                           cancel_requested=None)
        warn = entry.get('warnings') or []
        state.event(job_dir, job, 'accepted', message='Valid; queued.' + (f' {len(warn)} warning(s).' if warn else ''))
    jobs.submit(RUNNER, {'job_dir': str(job_dir), 'job_id': entry['job_id'], 'hash': entry['hash'], 'home': str(h),
                         'env': runner.carried_env()},
                root=queue_root(h), job_id=entry['queue_id'],
                timeout_s=float(job.get('timeout_s') or TIMEOUT_S.get(job['kind'], DEFAULT_TIMEOUT_S)),
                max_attempts=int(job.get('max_attempts') or 3), start_worker=start_worker, label=entry['job_id'],
                lane=entry['lane'])
    if 'queued' not in seen:
        state.event(job_dir, job, 'queued')
    entry['state'] = 'queued'
    files.write_json(_registry(h, entry['job_id']), entry)


def _cancel_at_claim(h, entry, job, seen=()):
    """Contract 1.1: a job whose folder already holds a cancel file when letitedit takes it (a caller cancelling a job
    still waiting in the inbox) is accepted and ends at once as cancelled: result.json with error cancelled and no
    files; it is never queued and never runs. Safe to repeat."""
    job_dir = Path(entry['job_dir'])
    if not state.result_exists(job_dir):
        if 'accepted' not in seen:
            state.write_status(job_dir, job, state='queued', priority=entry['lane'], submitted=entry['submitted'],
                               attempt=0, max_attempts=int(job.get('max_attempts') or 3), progress=0,
                               message='Cancelled before it ran', warnings=entry.get('warnings'), waiting_on=None)
            state.event(job_dir, job, 'accepted', message='Valid; its folder already held a cancel file.')
        if 'cancel_requested' not in seen:
            state.event(job_dir, job, 'cancel_requested')
        state.write_result(job_dir, job, 'cancelled', capabilities.versions(), state.cost_line(time.time()),
                           err=state.error('cancelled', 'The job was cancelled before it ran: its folder held a cancel '
                                           'file when letitedit took it. Nothing was made.'),
                           warnings=entry.get('warnings'))
    entry['state'] = 'queued'
    entry['never_queued'] = True                      # retry queues it for the first time
    files.write_json(_registry(h, entry['job_id']), entry)


def repair_submissions(h):
    """Finish every submit a crash interrupted (registry state 'reserving'). One whose job.json has changed since is
    not run: its reservation ends with a failed result saying so."""
    for f in Path(h, 'registry').glob('*.json'):
        entry = files.read_json(f)
        if entry and entry.get('first_retry'):
            with files.folder_lock(Path(h) / 'registry'):
                entry = files.read_json(f) or {}
                job = files.read_json(Path(entry.get('job_dir', '')) / 'job.json') if entry.get('first_retry') else None
                if isinstance(job, dict) and files.job_hash(job) == entry.get('hash'):
                    _finish_first_retry(h, entry, job)          # a first retry that stopped part way
            continue
        if not entry or entry.get('state') != 'reserving':
            continue
        with files.folder_lock(Path(h) / 'registry'):
            entry = files.read_json(f) or {}
            if entry.get('state') != 'reserving':
                continue
            job_dir = Path(entry['job_dir'])
            if not _claim(h, job_dir, entry.get('job_id')):
                entry['state'] = 'rejected'                # the folder is another owner's: nothing more is written
                entry['why'] = f'the job folder was taken by {files.taken_by(job_dir)}'
                files.write_json(f, entry)
                continue
            job = files.read_json(job_dir / 'job.json')
            if isinstance(job, dict) and files.job_hash(job) == entry.get('hash'):
                _finish_submission(h, entry, job)
                continue
            queued = (queue_root(h) / entry['queue_id']).is_dir()
            if queued:
                entry['state'] = 'queued'                 # the runner refuses a changed job.json (B4)
                files.write_json(f, entry)
                continue
            entry['state'] = 'rejected'
            files.write_json(f, entry)
            if job_dir.is_dir():
                stub = job if isinstance(job, dict) else {'job_id': entry['job_id'], 'kind': entry.get('kind')}
                state.write_result(job_dir, stub, 'failed', capabilities.versions(), state.cost_line(time.time()),
                                   err=state.error('job_id_conflict', 'Sending this job was interrupted and job.json '
                                                   'changed before it was finished; send it with a new job id.'))


def _queue_fields(h, entry):
    """queue: position 1 is next; jobs_ahead counts the Studio jobs that run before it (the running one too)."""
    order = jobs.queue_order(queue_root(h))
    qid = entry.get('queue_id')
    worker = jobs.worker_info(queue_root(h)) or {}
    running = worker.get('current') if worker.get('running') else None
    running_job = None
    if running:
        running_job = (files.read_json(queue_root(h) / running / 'spec.json') or {}).get('label')
    index = order.index(qid) if qid in order else len(order)
    return {'position': index + 1, 'jobs_ahead': index + (1 if running and running != qid else 0),
            'running_job': running_job}


def _gave_up(qs):
    text = f'{qs.get("message") or ""} {qs.get("error") or ""}'
    if 'timeout' in text.lower() or 'timed out' in text.lower():
        return state.error('timeout', "The job ran out of its time limit (timeout_s); sending it again carries on from "
                           'its last finished stage.', detail=text[-1500:])
    if 'interrupted repeatedly' in text or 'Stopped without finishing' in text:
        return state.error('interrupted_too_often', "letitedit's process stopped before the job finished, as many "
                           'times as max_attempts allows. Retry carries on from its last finished stage.',
                           detail=text[-1500:])
    return state.error('internal', 'The job stopped without finishing; sending it again may work.', detail=text[-1500:])


def reconcile(h, entry):
    """Bring status.json up to date with the job's process; write result.json for a job that ended without its
    runner writing one (killed, crashed too often, cancelled before it ran). Returns status.json."""
    job_dir = Path(entry['job_dir'])
    job = files.read_json(job_dir / 'job.json') or {}
    st = state.read_status(job_dir)
    if state.result_exists(job_dir):
        state.finish_from_result(job_dir, job)           # the result is the commit record (a crash after it)
        return state.read_status(job_dir)
    qid = entry.get('queue_id')
    if not qid or not _complete(entry):
        return st
    try:
        qs = jobs.status(qid, root=queue_root(h))
    except KeyError:
        return st
    if (job_dir / 'cancel').exists() and qs['state'] in ('queued', 'interrupted', 'running'):
        jobs.cancel(qid, root=queue_root(h))
        qs = jobs.status(qid, root=queue_root(h))
    if qs['state'] == 'queued':
        return state.write_status(job_dir, job, state='queued', queue=_queue_fields(h, entry))
    if qs['state'] == 'interrupted':
        if st.get('state') == 'running' and not st.get('resuming'):
            state.event(job_dir, job, 'interrupted', attempt=st.get('attempt'),
                        message="letitedit's process stopped before the job finished.")
        return state.write_status(job_dir, job, state='queued', resuming=True, heartbeat=None,
                                  queue=_queue_fields(h, entry), waiting_on=None,
                                  message='Stopped part way (a crash or a restart); it carries on from the start of '
                                          'its last stage.')
    if qs['state'] == 'running':
        return st
    started_t = time.time()
    if qs['state'] == 'cancelled':
        state.write_result(job_dir, job, 'cancelled', capabilities.versions(), state.cost_line(started_t),
                           err=state.error('cancelled', 'The job was cancelled.'), started=st.get('started'),
                           attempts=st.get('attempt') or None)
    elif qs['state'] == 'failed':
        state.write_result(job_dir, job, 'failed', capabilities.versions(), state.cost_line(started_t),
                           err=_gave_up(qs), started=st.get('started'), attempts=st.get('attempt') or None)
    elif qs['state'] == 'done':
        state.write_result(job_dir, job, 'failed', capabilities.versions(), state.cost_line(started_t),
                           err=state.error('internal', 'The job finished without writing its result.'),
                           started=st.get('started'))
    return state.read_status(job_dir)


def touch(h, kick=True):
    """What every entry point does first: finish interrupted submits, read the inbox, then start the worker when jobs
    wait."""
    repair_submissions(h)
    scan_inbox(h)
    if kick and jobs.queue_order(queue_root(h)):
        jobs.ensure_worker(root=queue_root(h), wait_s=0.5)


def status(ref, h=None):
    h = Path(h) if h else home()
    touch(h)
    entry, folder = _entry_for(h, ref)
    if entry is None:
        if folder is not None and (folder / 'status.json').exists():
            state.finish_from_result(folder)
            return {'exit': 0, 'status': state.read_status(folder)}
        return _not_found(ref)
    st = reconcile(h, entry)
    return {'exit': 0, 'status': st}


def cancel(ref, h=None):
    h = Path(h) if h else home()
    entry, folder = _entry_for(h, ref)
    if entry is None and JOB_ID.match(str(ref)):
        taken = _cancel_from_inbox(h, str(ref))       # a job still waiting in the inbox (contract 1.1)
        if taken is not None:
            return taken
        files.wait_for_claims(Path(h) / 'inbox')     # another entry point may be taking it right now
        entry, folder = _entry_for(h, ref)
    if entry is None:
        return _not_found(ref)
    job = files.read_json(folder / 'job.json') or {}
    # The registry's lock, then the job folder's: the order retry and the repairs use, so a cancel never decides in
    # the middle of a first retry. A first retry that stopped part way is finished first; the cancel is then decided
    # on the attempt that is current now.
    with files.folder_lock(Path(h) / 'registry'):
        entry = files.read_json(_registry(h, entry['job_id'])) or entry
        if entry.get('first_retry') and isinstance(job, dict) and files.job_hash(job) == entry.get('hash'):
            _finish_first_retry(h, entry, job)
        qid = entry.get('queue_id')
        queued = bool(qid) and (queue_root(h) / qid / 'spec.json').is_file()
        with files.folder_lock(folder):            # the request is recorded before the runner can act on it
            asked = not state.result_exists(folder)
            if asked:
                state.event(folder, job, 'cancel_requested')
                state.write_status(folder, job, cancel_requested=True)
                (folder / 'cancel').write_text(files.now_iso(), encoding='utf-8')
        if asked and queued:
            jobs.cancel(qid, root=queue_root(h))   # the current attempt's queue job
        elif asked and entry.get('state') == 'reserving':
            _finish_submission(h, entry, job)      # not queued yet: it ends cancelled at its claim
        elif asked:                                 # no queue job and none coming: the attempt ends here
            state.write_result(folder, job, 'cancelled', capabilities.versions(), state.cost_line(time.time()),
                               err=state.error('cancelled', 'The job was cancelled before it ran. Nothing was made.'))
            entry['never_queued'] = True
            files.write_json(_registry(h, entry['job_id']), entry)
    return {'exit': 0, 'status': reconcile(h, entry)}


def _cancel_from_inbox(h, job_id):
    """Cancel a job still waiting in the inbox as <job_id>.json: it is taken as scan_inbox takes it, with a cancel file
    written into its job folder before it is submitted, so it ends cancelled at its claim and never runs. None when
    there is no such inbox file (another entry point may have taken it a moment ago: the caller looks again)."""
    claim = files.claim_inbox_file(Path(h) / 'inbox', f'{job_id}.json')
    if claim is None:
        return None
    original, claimed = claim
    try:
        problems = _take_inbox_item(h, claimed, cancel=True, expected_id=job_id)
    except files.FolderBusy as e:
        problems = [{'field': 'job', 'code': 'busy', 'message': str(e)}]
    files.finish_claim(original, claimed, problems, contract.CONTRACT_VERSION)
    if problems:
        return {'exit': 2, 'problems': problems}
    return cancel(job_id, h)              # now known: ended at its claim, or (sent before) cancelled as usual


def retry(ref, h=None):
    h = Path(h) if h else home()
    repair_submissions(h)                            # an interrupted first retry is finished before anything else
    entry, folder = _entry_for(h, ref)
    if entry is None:
        return _not_found(ref)
    reconcile(h, entry)
    result = files.read_json(folder / 'result.json') or {}
    if entry.get('state') == 'rejected':
        return {'exit': 2, 'problems': [{'field': 'job', 'code': 'not_retryable', 'message': 'A refused job is sent '
                                         'again with submit, once job.json is fixed.'}], 'status': state.read_status(folder)}
    if result.get('state') not in ('failed', 'cancelled'):
        return {'exit': 2, 'problems': [{'field': 'job', 'code': 'not_retryable',
                                         'message': 'Only a failed or cancelled job can be retried.'}],
                'status': state.read_status(folder)}
    job = files.read_json(folder / 'job.json')
    if not isinstance(job, dict) or files.job_hash(job) != entry.get('hash'):
        return {'exit': 2, 'problems': [{'field': 'job_id', 'code': 'job_id_conflict', 'message': 'job.json changed '
                                         'after this job was accepted; a changed job needs a new job id. Nothing was '
                                         'retried.'}], 'status': state.read_status(folder)}
    hist = folder / 'history'
    hist.mkdir(exist_ok=True)
    n = len(list(hist.glob('result-*.json'))) + 1
    if entry.get('never_queued'):                    # cancelled at its claim: queued now for the first time
        if _BEFORE_FIRST_RETRY_LOCK:
            _BEFORE_FIRST_RETRY_LOCK(entry)
        with files.folder_lock(Path(h) / 'registry'):
            # Everything is read again under the lock: another retry may have finished this one in the meantime.
            entry = files.read_json(_registry(h, entry['job_id'])) or entry
            if entry.get('first_retry'):            # one that stopped part way: finishing it is this retry
                _finish_first_retry(h, entry, job)
                return {'exit': 0, 'status': reconcile(h, entry)}
            with files.folder_lock(folder):
                current = files.read_json(folder / 'result.json') or {}
                after_seq = files.last_seq(folder)
            if not entry.get('never_queued') or current.get('state') not in ('failed', 'cancelled'):
                return {'exit': 2, 'problems': [{'field': 'job', 'code': 'not_retryable',
                                                 'message': 'This job was already queued again (another retry did '
                                                            'it); there is nothing to retry.'}],
                        'status': state.read_status(folder)}
            # The transition is recorded before anything changes, so a stop part way is finished by the next entry
            # point, never left with no result and no queue job. Its first step hands the old cancel file to the
            # ending attempt by renaming it (cancel.attempt-<n>); a cancel written after that is the new attempt's.
            entry['first_retry'] = {'archive': f'history/result-{n}.json', 'attempt': n, 'since': files.now_iso(),
                                    'after_seq': after_seq}
            files.write_json(_registry(h, entry['job_id']), entry)
            _finish_first_retry(h, entry, job)
        return {'exit': 0, 'status': reconcile(h, entry)}
    with files.folder_lock(folder):
        files.hand_off_cancel(folder, n)              # the ending attempt's cancel file, by an atomic rename
        shutil.move(str(folder / 'result.json'), str(hist / f'result-{n}.json'))
    state.write_status(folder, job, state='queued', error=None, finished=None, resuming=None, cancel_requested=None,
                       message='Queued again; it carries on from its last finished stage.')
    state.event(folder, job, 'queued', message='Retry')
    jobs.resume(entry['queue_id'], root=queue_root(h))
    return {'exit': 0, 'status': reconcile(h, entry)}


def _retry_queued(folder, after_seq=None):
    """True when this first retry's 'queued' (Retry) event is written: a 'queued' event after the seq the retry saved
    when it began (so a later cancel of the new attempt never makes the old steps run again), or, for a transition
    saved without it, after the job's last 'cancelled' event."""
    seen = files.read_events(folder)
    if after_seq is None:
        after_seq = max((e.get('seq', 0) for e in seen if e.get('type') == 'cancelled'), default=0)
    return any(e.get('type') == 'queued' and e.get('seq', 0) > after_seq for e in seen)


def _finish_first_retry(h, entry, job):
    """The first retry of a job cancelled at its claim, every step safe to repeat (called under the registry's lock,
    with entry['first_retry'] already saved): the old cancel file handed to the ending attempt (renamed), the
    result archived, status and the Retry event,
    then the queue job under its fixed id (core/jobs.py returns the existing one when it is there), then the registry
    entry completed. Each step checks what is done, so a stop anywhere is finished by repeating it."""
    folder = Path(entry['job_dir'])
    step = entry['first_retry']
    with files.folder_lock(folder):
        if not _retry_queued(folder, step.get('after_seq')):   # the old attempt's steps; once Retry is written, never again
            archived = folder / step['archive']
            attempt = step.get('attempt') or Path(step['archive']).stem.rsplit('-', 1)[-1]
            # The handoff is first, and it is done once the renamed file or the archive exists (the archive only ever
            # follows it): after that, any cancel file is the new attempt's and nothing here removes it.
            if _BEFORE_CANCEL_HANDOFF:
                _BEFORE_CANCEL_HANDOFF(entry)
            if not archived.exists():
                files.hand_off_cancel(folder, attempt)
            if _AFTER_CANCEL_HANDOFF:
                _AFTER_CANCEL_HANDOFF(entry)
            r = files.read_json(folder / 'result.json')
            if r and r.get('state') in state.FINAL and not archived.exists():
                archived.parent.mkdir(exist_ok=True)
                os.replace(folder / 'result.json', archived)
            state.write_status(folder, job, state='queued', error=None, finished=None, resuming=None,
                               cancel_requested=None, message='Queued for the first time (retry).')
            state.event(folder, job, 'queued', message='Retry')
    if _AFTER_FIRST_RETRY_STEPS:
        _AFTER_FIRST_RETRY_STEPS(entry)
    _finish_submission(h, entry, job)                # jobs.submit with the fixed queue id, then state 'queued'
    if _AFTER_FIRST_RETRY_QUEUED:
        _AFTER_FIRST_RETRY_QUEUED(entry)
    entry.pop('first_retry', None)
    entry.pop('never_queued', None)
    files.write_json(_registry(h, entry['job_id']), entry)


_BEFORE_FIRST_RETRY_LOCK = None     # tests: a retry that has checked the job, paused before the registry's lock
_BEFORE_CANCEL_HANDOFF = None       # tests: a caller's raw cancel write just before the handoff's rename
_AFTER_CANCEL_HANDOFF = None        # tests: a caller's raw cancel write just after it
_AFTER_FIRST_RETRY_STEPS = None     # tests: a stop after the folder's steps, before the queue job exists
_AFTER_FIRST_RETRY_QUEUED = None    # tests: a stop after the queue job exists, before the registry is completed


def run(ref, h=None, poll_s=1.0, timeout_s=None):
    """submit, then wait for the result. Returns {'exit', 'result'}."""
    h = Path(h) if h else home()
    out = submit(ref, h)
    if out['exit'] != 0:
        return out
    job_id = out['status']['job_id']
    t0 = time.monotonic()
    while True:
        st = status(job_id, h)['status']
        if st.get('state') in state.FINAL:
            entry, folder = _entry_for(h, job_id)
            r = files.read_json(folder / 'result.json') or {}
            return {'exit': {'done': 0, 'failed': 1, 'cancelled': 3}[r.get('state', 'failed')], 'result': r}
        if timeout_s and time.monotonic() - t0 > timeout_s:
            return {'exit': 1, 'status': st, 'note': 'Still running; follow it with status.'}
        time.sleep(poll_s)


def scan_inbox(h):
    """Take every <job_id>.json in the inbox (each claimed by an atomic rename first, so two entry points never take
    one file twice). It is checked whole before anything is written: a valid one is written into its job folder and
    submitted (renamed .taken); any other is refused with nothing written (renamed .refused, with <job_id>.refused.json
    beside it holding the problems)."""
    for original, claimed in files.claim_inbox(Path(h) / 'inbox'):
        try:
            problems = _take_inbox_item(h, claimed)
        except files.FolderBusy as e:
            problems = [{'field': 'job', 'code': 'busy', 'message': str(e)}]
        files.finish_claim(original, claimed, problems, contract.CONTRACT_VERSION)
    files.wait_for_claims(Path(h) / 'inbox')


def _take_inbox_item(h, claimed, cancel=False, expected_id=None):
    """Take one claimed inbox file. cancel: the cancel command asked for it while it waited; a cancel file is written
    into its job folder before it is submitted, so it ends cancelled at once (_cancel_at_claim)."""
    job = files.read_json(claimed)
    if not isinstance(job, dict) or not isinstance(job.get('job_id'), str) or not JOB_ID.match(job['job_id']):
        return [{'field': 'job_id', 'code': 'invalid_job', 'message': 'Not a job.json with a valid job_id.'}]
    if expected_id is not None and job['job_id'] != expected_id:
        return [{'field': 'job_id', 'code': 'invalid_job',
                 'message': f'The inbox file {expected_id}.json holds the job {job["job_id"]}: an inbox file is '
                            'named after its own job id. Nothing was cancelled or written.'}]
    out_dir = job.get('output_dir')
    if out_dir is not None and not (isinstance(out_dir, str) and Path(out_dir).is_absolute()):
        return [{'field': 'output_dir', 'code': 'invalid_job', 'message': 'output_dir must be an absolute path.'}]
    job_dir = Path(out_dir) if out_dir else Path(h) / 'jobs' / job['job_id']
    check = validate.validate(job=job, job_dir=job_dir, knowledge=Knowledge(h))
    if not check['valid']:
        return check['problems']                      # nothing is written for a refused inbox job
    # The registry's lock, then the destination's own: the order is the same everywhere. The destination is first
    # claimed for this Studio folder and job id (atomic, so another Studio folder can't take it too), then read,
    # written and submitted under its lock, the claim checked again right before job.json is written.
    def refused():
        return [{'field': 'output_dir', 'code': 'output_dir_refused',
                 'message': f'The job folder {job_dir} was taken by {files.taken_by(job_dir)}.'}]
    with files.folder_lock(Path(h) / 'registry'):
        if not _claim(h, job_dir, job['job_id']):
            return refused()
        with files.folder_lock(job_dir):
            existing = files.read_json(job_dir / 'job.json')
            if _AFTER_DEST_READ:
                _AFTER_DEST_READ(job)
            if existing is not None and files.job_hash(existing) != files.job_hash(job):
                return [{'field': 'job_id', 'code': 'job_id_conflict',
                         'message': f'{job_dir} already holds a different job.json.'}]
            if existing is None:
                if not files.holds(job_dir, 'letitedit', h, job['job_id']):
                    return refused()
                files.write_json(job_dir / 'job.json', job)
            if cancel and not owns(h, job['job_id'], job_dir):
                (job_dir / 'cancel').write_text(files.now_iso(), encoding='utf-8')
            out = submit(job_dir, h)
    return None if out['exit'] == 0 else (out.get('problems') or [{'field': 'job', 'code': 'invalid_job',
                                                                  'message': 'Refused.'}])


_AFTER_DEST_READ = None          # tests: called inside the inbox's destination check


def watch(h=None, idle_s=600.0, poll_s=2.0):
    """Read the inbox every poll_s seconds; return after idle_s with nothing in it and no job waiting."""
    h = Path(h) if h else home()
    last = time.monotonic()
    while time.monotonic() - last < idle_s:
        if files.waiting_in_inbox(Path(h) / 'inbox') or jobs.queue_order(queue_root(h)):
            last = time.monotonic()
        touch(h)
        time.sleep(poll_s)
    return {'exit': 0, 'note': f'No jobs for {idle_s:g} s.'}
