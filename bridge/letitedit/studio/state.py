"""status.json and result.json for one job folder, written the contract's way (CONTRACT.md sections 3, 7, 8).

No letitedit imports beyond the studio's own standard-library modules: the reference fake writes through it too.
"""
from __future__ import annotations

import contextlib
import time
from pathlib import Path

import letitedit.studio.contract_schemas as contract
import letitedit.studio.files as files
import letitedit.studio.licences as licences

FINAL = ('done', 'failed', 'cancelled')
ATTEMPT_EVENTS = ('resumed', 'started', 'stage_started', 'stage_done', 'progress', 'waiting', 'waiting_over')
STATUS_KEYS = ('tier', 'stage', 'stage_index', 'stages_total', 'progress', 'message', 'heartbeat', 'submitted',
               'started', 'finished', 'attempt', 'max_attempts', 'resuming', 'priority', 'queue', 'waiting_on',
               'cancel_requested', 'events', 'outputs_so_far', 'warnings', 'error')
RETRY = {      # error code -> retry, when the code doesn't say otherwise
    'invalid_job': 'after_change', 'unsupported_version': 'no', 'job_id_conflict': 'after_change',
    'output_dir_refused': 'after_change', 'source_missing': 'after_change', 'source_unreadable': 'after_change',
    'look_unknown': 'after_change', 'platform_unknown': 'after_change', 'layout_unknown': 'after_change',
    'kind_not_installed': 'no', 'from_job_unusable': 'after_change', 'no_footage_for_idea': 'after_change',
    'ai_unavailable': 'after_change', 'ai_limit': 'after', 'ai_failed': 'yes', 'render_failed': 'yes',
    'out_of_memory': 'yes', 'disk_full': 'after_change', 'timeout': 'yes', 'interrupted_too_often': 'yes',
    'cancelled': 'yes', 'location_not_removed': 'no', 'internal': 'yes',
    'hdr_not_supported': 'after_change', 'hdr_not_delivered': 'no',
}
AI_LIMIT_RETRY_S = 3600       # ai_limit's retry_after_s when the AI gives no reset time


class StudioError(Exception):
    """A job's failure in the contract's terms: a code, a plain message, whether a retry makes sense."""

    def __init__(self, code, message, retry=None, detail=None, stage=None, retry_after_s=None):
        super().__init__(message)
        self.code, self.message, self.detail, self.stage = code, message, detail, stage
        self.retry = retry or RETRY.get(code, 'yes')
        if retry_after_s is None and (code == 'ai_limit' or self.retry == 'after'):
            retry_after_s = AI_LIMIT_RETRY_S       # contract 1.1: ai_limit (any 'after') always says when to try again
        self.retry_after_s = retry_after_s

    def as_error(self):
        d = {'code': self.code, 'message': self.message, 'retry': self.retry}
        if self.retry_after_s is not None:
            d['retry_after_s'] = self.retry_after_s
        if self.stage:
            d['stage'] = self.stage
        if self.detail:
            d['detail'] = str(self.detail)[-2000:]
        return d


def error(code, message, **kw):
    return StudioError(code, message, **kw).as_error()


def read_status(job_dir):
    return files.read_json(Path(job_dir) / 'status.json') or {}


def write_status(job_dir, job, **changes):
    """Merge changes into status.json and write it whole. Returns the new status."""
    job_dir = Path(job_dir)
    with files.folder_lock(job_dir):
        st = read_status(job_dir)
        if st.get('job_id') not in (None, job.get('job_id')):
            st = {}
        st.update({'contract_version': contract.CONTRACT_VERSION, 'job_id': job.get('job_id'),
                   'kind': job.get('kind')})
        tier = (job.get('inputs') or {}).get('tier')
        if tier:
            st['tier'] = tier
        st.setdefault('attempt', 0)
        st.setdefault('progress', 0)
        st.setdefault('message', 'Queued')
        for k, v in changes.items():
            if v is None and k in ('waiting_on',):
                st[k] = None
            elif v is None:
                st.pop(k, None)
            else:
                st[k] = files.delivered(v) if k == 'outputs_so_far' else v
        st['updated'] = files.now_iso()
        st['events'] = files.last_seq(job_dir)
        files.write_json(job_dir / 'status.json', st)
        return st


class Ended(Exception):
    """The job already has its result.json (an entry point ended it, a cancel deciding first): its running attempt
    writes nothing more and stops."""


def event(job_dir, job, type_, **fields):
    """Append one event. A running attempt's event (ATTEMPT_EVENTS) is written only while the job has no result, checked
    under the folder's lock that every result.json is written under, so the terminal event stays the job's last; once
    the result exists it is not written and None is returned."""
    if type_ not in ATTEMPT_EVENTS:
        return files.append_event(job_dir, contract.CONTRACT_VERSION, job.get('job_id'), type_, **fields)
    with files.folder_lock(job_dir):
        if result_exists(job_dir):
            return None
        return files.append_event(job_dir, contract.CONTRACT_VERSION, job.get('job_id'), type_, **fields)


@contextlib.contextmanager
def attempt(job_dir):
    """A running attempt's step (its events and status.json changes together), made only while the job has no result:
    held under the folder's lock, so an entry point ending the job and the worker never interleave. Raises Ended, and
    nothing is written, when result.json already exists."""
    with files.folder_lock(job_dir):
        if result_exists(job_dir):
            raise Ended(f'{job_dir} already has its result.json.')
        yield


def result_exists(job_dir):
    r = files.read_json(Path(job_dir) / 'result.json')
    return bool(r and r.get('state') in FINAL)


def _final_fields(r):
    err = r.get('error')
    message = {'done': 'Finished', 'failed': (err or {}).get('message', 'Failed'), 'cancelled': 'Cancelled'}[r['state']]
    final = dict(state=r['state'], message=message[:500], finished=r.get('finished') or files.now_iso(),
                 waiting_on=None, heartbeat=None, error=err, resuming=None,
                 queue={'position': 0, 'jobs_ahead': 0, 'running_job': None})
    if r['state'] == 'done':
        final['progress'] = 1
    return final, message


def finish_from_result(job_dir, job=None):
    """result.json is the commit record: when it exists, make the terminal event and status.json agree with it (after
    a crash between the three writes). Idempotent. Returns the result, or None when there is none."""
    job_dir = Path(job_dir)
    with files.folder_lock(job_dir):
        r = files.read_json(job_dir / 'result.json')
        if not (r and r.get('state') in FINAL):
            return None
        job = job or files.read_json(job_dir / 'job.json') or {'job_id': r.get('job_id'), 'kind': r.get('kind')}
        final, message = _final_fields(r)
        seen = files.read_events(job_dir)
        last_start = max((e['seq'] for e in seen if e.get('type') in ('queued', 'started', 'resumed')), default=0)
        if not any(e.get('type') == r['state'] and e.get('seq', 0) > last_start for e in seen):
            event(job_dir, job, r['state'], message=message[:300], error=r.get('error'))
        st = read_status(job_dir)
        if st.get('state') != r['state'] or st.get('finished') != final['finished']:
            write_status(job_dir, job, **final)
        return r


def write_result(job_dir, job, state, versions, cost, outputs=None, output=None, err=None, warnings=None,
                 started=None, attempts=None, extra=None):
    """Write result.json once (never over a final one), then the terminal event and the final status.json, all under
    the folder's lock. An existing result wins and is finished instead (finish_from_result). Returns the result."""
    job_dir = Path(job_dir)
    with files.folder_lock(job_dir):
        if result_exists(job_dir):
            return finish_from_result(job_dir, job)
        return _write_result(job_dir, job, state, versions, cost, outputs, output, err, warnings, started, attempts,
                             extra)


def _write_result(job_dir, job, state, versions, cost, outputs, output, err, warnings, started, attempts, extra):
    r = {'contract_version': contract.CONTRACT_VERSION, 'job_id': job.get('job_id'), 'kind': job.get('kind')}
    tier = (job.get('inputs') or {}).get('tier')
    if tier:
        r['tier'] = tier
    r['state'] = state
    if started:
        r['started'] = started
    r['finished'] = files.now_iso()
    if job.get('from_job'):
        r['from_job'] = job['from_job']
    if attempts:
        r['attempts'] = attempts
    r['versions'] = versions
    r['cost'] = cost
    r['outputs'] = files.delivered(outputs)      # never the box file or other internal bookkeeping (T357)
    r.update(extra or {})
    if state == 'done':
        r['output'] = output if output is not None else {}
    else:
        r['error'] = err or error('internal', 'The job ended without saying why.')
    r['warnings'] = warnings or []
    licences.for_job(r, job.get('contract_version'))   # no id from a later minor than the job's (contract 1.6)
    files.write_json(job_dir / 'result.json', r)
    if _CRASH_AFTER_RESULT:                    # tests: a kill between the commit and the rest
        _CRASH_AFTER_RESULT()
    final, message = _final_fields(r)
    event(job_dir, job, state, message=message[:300], error=r.get('error'))
    write_status(job_dir, job, **final)
    return r


_CRASH_AFTER_RESULT = None


def cost_line(started_t, ai=None, measured=False, waited_s=0.0, **kw):
    c = {'wall_s': round(max(0.0, time.time() - started_t), 3), 'waited_s': round(waited_s, 3), 'measured': measured}
    if ai:
        c['ai'] = ai
    c.update({k: v for k, v in kw.items() if v is not None})
    return c
