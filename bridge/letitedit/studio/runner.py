"""One Studio job, run as a core/jobs.py job (kind 'letitedit.studio.runner:run') in its own process.

core/jobs.py gives the process, the time limit, cancel, the restart after a crash and the attempt count; this module
writes the contract's files in the caller's job folder: status.json (with a heartbeat), events.jsonl and result.json.
Each kind is a list of stages; a finished stage is kept in the checkpoint, so a resumed job starts the stopped stage
again from its beginning.

Test steering: with LETITEDIT_STUDIO_TEST_KINDS=1 in the submitter's environment (contract tests only), a job's top-level 'x_test'
adds stages before the kind's own: {"stages": n, "stage_s": s, "crash_at": k, "crash_attempts": a, "fail": code,
"fail_at": k}. Without that variable x_test is ignored, as every x_ field is.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import letitedit.core.jobs as jobs
import letitedit.core.render_lock as render_lock
import letitedit.studio.capabilities as capabilities
import letitedit.studio.files as files
import letitedit.studio.state as state
import letitedit.studio.validate as validate

# The few settings a job carries from whoever submitted it: core/jobs.py's worker is started outside the caller's
# process tree and doesn't inherit its environment. LETITEDIT_ROOT is the install the job's window runs from (its
# app, models and caches): without it the window ran from the code's own folder, which may have no models.
CARRIED = ('LETITEDIT_STUDIO_TEST_KINDS', 'LETITEDIT_STUDIO_PERSON_CHECK', 'LETITEDIT_STUDIO_LOCK_DEBUG',
           'LETITEDIT_STUDIO_TRY_KINDS', 'LETITEDIT_STUDIO_EXE', 'LETITEDIT_SETTINGS', 'LETITEDIT_ROOT')
HEARTBEAT_S = 5.0
PERSON_POLL_S = 15.0
TEST_ENV = 'LETITEDIT_STUDIO_TEST_KINDS'
PERSON_CHECK_ENV = 'LETITEDIT_STUDIO_PERSON_CHECK'


def carried_env():
    return {k: os.environ[k] for k in CARRIED if k in os.environ}


def _take_carried(inputs):
    for k, v in (inputs.get('env') or {}).items():
        if k in CARRIED and isinstance(v, str):
            os.environ[k] = v
    if inputs.get('home'):
        os.environ['LETITEDIT_STUDIO_HOME'] = str(inputs['home'])


def person_busy():
    """True while the person's own letitedit window is running an AI edit (its chat is busy). A read-only question to
    the window; anything that fails counts as not busy, so a job is never held by a check that can't answer."""
    if os.environ.get(PERSON_CHECK_ENV, '1') == '0':
        return False
    try:
        import letitedit.app.letitedit_instances as instances
        from letitedit.app.letitedit_client import ShotcutBridge
        with instances.scope('main'), ShotcutBridge(timeout=2) as bridge:
            return bool((bridge.call('chat_state') or {}).get('busy'))
    except Exception:  # noqa: BLE001
        return False


class Heartbeat:
    """Renews status.json's heartbeat and passes a caller's `cancel` file on to core/jobs.py."""

    def __init__(self, job_dir, job, ctx):
        self.job_dir, self.job, self.ctx = Path(job_dir), job, ctx
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self.stop_event.wait(HEARTBEAT_S):
            try:
                if (self.job_dir / 'cancel').exists() and not (self.ctx.dir / 'cancel').exists():
                    (self.ctx.dir / 'cancel').write_text(jobs.now(), encoding='utf-8')
                with state.attempt(self.job_dir):      # never a beat on a job that has its result
                    state.write_status(self.job_dir, self.job, heartbeat=files.now_iso())
            except Exception:  # noqa: BLE001 - a missed beat (or a job that ended) is not a failure
                pass

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()


def _cancelled(ctx, job_dir):
    if (Path(job_dir) / 'cancel').exists():
        raise jobs.Cancelled('Cancelled')
    ctx.check()


def _wait_for_person(ctx, job_dir, job):
    if job.get('kind') not in capabilities.USES_AI or not person_busy():
        return 0.0
    t0 = time.monotonic()
    with state.attempt(job_dir):
        state.write_status(job_dir, job, waiting_on={'what': 'person_working', 'since': files.now_iso(),
                                                     'detail': "The person's own letitedit is running an AI edit."},
                           message='Waiting: the person is editing with the AI in letitedit.')
        state.event(job_dir, job, 'waiting', waiting_on='person_working')
    while person_busy():
        for _ in range(int(PERSON_POLL_S)):
            _cancelled(ctx, job_dir)
            time.sleep(1)
    with state.attempt(job_dir):
        state.write_status(job_dir, job, waiting_on=None)
        state.event(job_dir, job, 'waiting_over', waiting_on='person_working')
    return time.monotonic() - t0


# ------------------------------------------------------------------ the kinds' stages

def _stage_capabilities(ctx, job_dir, job, attempt):
    import letitedit.studio.service as service
    home = service.home()
    inp = job.get('inputs') or {}
    return capabilities.build(home, service.entry_points(home), inp.get('include'), inp.get('ai'))


def _checked(func):
    """A kind's stage that is handed a cancel check (the caller's cancel file and core/jobs.py's cancel), called
    between its files and steps."""
    def stage(ctx, job_dir, job, attempt):
        return func(ctx, job_dir, job, attempt, check=lambda: _cancelled(ctx, job_dir))
    return stage


def _index_stages():
    import letitedit.studio.library as library
    return [(name, _checked(func)) for name, func in library.STAGES]


def _short_stages(job):
    import letitedit.studio.short as short
    return [(name, _checked(func)) for name, func in short.stages(job)]


def _retext_stages():
    import letitedit.studio.retext as retext
    return [(name, _checked(func)) for name, func in retext.STAGES]


def _conform_stages():
    import letitedit.studio.conform as conform
    return [(name, _checked(func)) for name, func in conform.STAGES]


def _revise_stages():
    import letitedit.studio.revise as revise
    return [(name, _checked(func)) for name, func in revise.stages()]


def _still_stages():
    import letitedit.studio.still as still

    def measured(func):
        def stage(ctx, job_dir, job, attempt):
            try:
                return _checked(func)(ctx, job_dir, job, attempt)
            except (state.StudioError, jobs.Cancelled) as exc:
                exc.cost = still.cost(still.work(job_dir))
                raise
        return stage
    return [(name, measured(func)) for name, func in still.STAGES]


STAGES = {
    'capabilities': [('read', _stage_capabilities)],
    'index': _index_stages,
    'short': _short_stages,
    'retext': _retext_stages,
    'conform': _conform_stages,
    'still': _still_stages,
    'revise': _revise_stages,
}


def _test_stages(job):
    steer = job.get('x_test')
    if os.environ.get(TEST_ENV) != '1' or not isinstance(steer, dict):
        return []
    n = int(steer.get('stages', 1))
    stage_s = float(steer.get('stage_s', 0.2))

    def make(k):
        def stage(ctx, job_dir, job, attempt):
            if steer.get('fail') and int(steer.get('fail_at', 1)) == k:
                raise state.StudioError(steer['fail'], f'Test failure at stage {k}.', stage=f'x_wait_{k}')
            t_end = time.monotonic() + stage_s
            crash = int(steer.get('crash_at', 0)) == k and (steer.get('crash_always')
                                                           or attempt <= int(steer.get('crash_attempts', 1)))
            while time.monotonic() < t_end:
                _cancelled(ctx, job_dir)
                if crash and time.monotonic() > t_end - stage_s / 2:
                    os._exit(3)               # a crash mid-stage, as a power cut or a killed process would be
                time.sleep(0.05)
            return None
        return stage
    return [(f'x_wait_{k}', make(k)) for k in range(1, n + 1)]


def stages_for(job):
    kind = job.get('kind')
    if kind not in STAGES:
        raise state.StudioError('kind_not_installed', f'The kind "{kind}" is not available on this install yet.')
    plan = STAGES[kind]
    if callable(plan):
        plan = plan(job) if kind == 'short' else plan()
    return _test_stages(job) + plan


# ------------------------------------------------------------------ the run

def run(ctx):
    _take_carried(ctx.inputs)
    job_dir = Path(ctx.inputs['job_dir'])
    if files.is_fake_folder(job_dir) or files.side_of(job_dir) not in (None, 'letitedit'):
        raise RuntimeError(f'{job_dir} was taken by the reference fake (or another program); the real Studio never '
                           'runs it.')
    owner = files.owner_of(job_dir) or {}
    if (owner.get('home') and ctx.inputs.get('home') and owner['home'] != files.home_key(ctx.inputs['home'])
            or owner.get('job_id') and ctx.inputs.get('job_id') and owner['job_id'] != ctx.inputs['job_id']):
        raise RuntimeError(f'{job_dir} was taken by {files.taken_by(job_dir)}; this Studio folder never runs it.')
    job = files.read_json(job_dir / 'job.json')
    if not isinstance(job, dict):
        raise RuntimeError(f'No job.json in {job_dir}')
    if state.result_exists(job_dir):
        state.finish_from_result(job_dir, job)          # a crash after the result: finish its event and status
        return {'note': 'result.json already written'}
    accepted = ctx.inputs.get('hash')
    if accepted and files.job_hash(job) != accepted:
        # job.json changed after it was accepted: never run another spec under this id, nor reuse its checkpoints
        state.write_result(job_dir, job, 'failed', capabilities.versions(), state.cost_line(time.time()),
                           err=state.error('job_id_conflict', 'job.json changed after this job was accepted, so it '
                                           'was not run. A changed job needs a new job id.'))
        return {'note': 'job.json changed after it was accepted'}
    os.environ[render_lock.PRIORITY_ENV] = validate.lane(job)      # every render this job starts waits in its lane
    attempt = int((files.read_json(ctx.dir / 'status.json') or {}).get('attempts') or 1)
    before = state.read_status(job_dir)
    started = before.get('started') or files.now_iso()
    started_t = time.time()
    resumed = attempt > 1 or bool(ctx.checkpoint)
    try:
        # The start is one step under the folder's lock: a cancel that ended the job first (its result written while
        # this attempt was being started) is seen here, and nothing of this attempt is written after it.
        with state.attempt(job_dir):
            if resumed:
                seen = files.read_events(job_dir)
                if not seen or seen[-1].get('type') != 'interrupted':
                    state.event(job_dir, job, 'interrupted', attempt=attempt - 1,
                                message="letitedit's process stopped before the job finished.")
                state.event(job_dir, job, 'resumed', attempt=attempt,
                            message='Carrying on from the start of its last unfinished stage.')
            state.event(job_dir, job, 'started', attempt=attempt)
            state.write_status(job_dir, job, state='running', attempt=attempt, started=started, resuming=None,
                               heartbeat=files.now_iso(),
                               queue={'position': 0, 'jobs_ahead': 0, 'running_job': job['job_id']},
                               waiting_on=None, message='Running' + (' again after a stop' if resumed else ''))
    except state.Ended:
        state.finish_from_result(job_dir, job)
        return {'note': 'result.json already written'}
    beat = Heartbeat(job_dir, job, ctx).start()
    waited = float(ctx.checkpoint.get('waited_s', 0.0))
    # wall_s is started to finished: the earlier attempts' time (saved as each one ended) counts too
    spent = float(ctx.checkpoint.get('spent_s', 0.0))
    first_t = started_t - spent
    try:
        plan = stages_for(job)
        done = list(ctx.checkpoint.get('done') or [])
        for i, (name, func) in enumerate(plan):
            if name in done:
                continue
            _cancelled(ctx, job_dir)
            waited += _wait_for_person(ctx, job_dir, job)
            with state.attempt(job_dir):       # a job an entry point ended meanwhile starts no stage
                state.event(job_dir, job, 'stage_started', attempt=attempt, stage=name)
                state.write_status(job_dir, job, stage=name, stage_index=i, stages_total=len(plan),
                                   progress=round(i / len(plan), 4), message=f'Stage {i + 1} of {len(plan)}: {name}')
            value = func(ctx, job_dir, job, attempt)
            done.append(name)
            saved = {'done': done, 'waited_s': waited}
            if value is not None:
                saved['output'] = value
            ctx.save(**saved)
            state.event(job_dir, job, 'stage_done', attempt=attempt, stage=name,
                        progress=round((i + 1) / len(plan), 4))
        cost = state.cost_line(first_t, waited_s=waited, measured=True)
        parts = ctx.checkpoint.get('output') or {}
        if isinstance(parts, dict) and parts.get('__result__'):
            # a making kind's last stage hands back the whole result: its output, the files it made, the shared
            # making fields (section 7), its warnings and what it measured of its cost
            cost.update(parts.get('cost') or {})
            versions = {**capabilities.versions(), **(parts.get('versions') or {})}
            state.write_result(job_dir, job, 'done', versions, cost, outputs=parts.get('outputs'),
                               output=parts.get('output') or {}, warnings=parts.get('warnings'),
                               extra=parts.get('extra'), started=started, attempts=attempt)
        else:
            state.write_result(job_dir, job, 'done', capabilities.versions(), cost, output=parts, started=started,
                               attempts=attempt)
        return {'result': str(job_dir / 'result.json')}
    except jobs.Cancelled as e:
        failure_cost = state.cost_line(first_t, waited_s=waited, measured=True)
        failure_cost.update(getattr(e, 'cost', {}) or {})
        state.write_result(job_dir, job, 'cancelled', capabilities.versions(),
                           failure_cost,
                           err=state.error('cancelled', 'The job was cancelled.'), started=started, attempts=attempt)
        raise
    except state.Ended as e:
        # an entry point ended the job while it ran (a cancel that decided first): its result stands, finished here
        state.finish_from_result(job_dir, job)
        raise jobs.Cancelled(str(e)) from e
    except state.StudioError as e:
        failure_cost = state.cost_line(first_t, waited_s=waited, measured=True)
        failure_cost.update(getattr(e, 'cost', {}) or {})
        state.write_result(job_dir, job, 'failed', capabilities.versions(),
                           failure_cost, err=e.as_error(),
                           started=started, attempts=attempt)
        raise
    except Exception as e:  # noqa: BLE001
        import traceback
        state.write_result(job_dir, job, 'failed', capabilities.versions(),
                           state.cost_line(first_t, waited_s=waited, measured=True),
                           err=state.error('internal', 'letitedit hit a fault while running this job; sending it '
                                           'again may work.', detail=traceback.format_exc()),
                           started=started, attempts=attempt)
        raise RuntimeError(str(e)) from e
    finally:
        ctx.save(spent_s=round(spent + max(0.0, time.time() - started_t), 3))
        beat.stop()
