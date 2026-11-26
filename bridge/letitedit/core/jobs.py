"""Background jobs for letitedit: long work that outlives one tool call, one AI session or a PC restart.

Storage: <LETITEDIT_JOBS or C:\\LetItEdit\\jobs>\\<job_id>\\
    spec.json        kind, inputs, created, timeout_s, max_attempts
    status.json      state, progress (0-1), message, pid, attempts, started, finished, outputs, error
    checkpoint.json  what a job has finished so far (a resumed job continues from it)
    log.txt          the job's log
    cancel           present when a cancel was asked for

States: queued, running, done, failed, cancelled, interrupted (its process stopped without finishing: PC restart,
crash, killed). One worker process per jobs folder (python jobs.py worker) runs queued and interrupted jobs one at a
time, each in its own child process (python jobs.py run <job_id>), so a job that crashes doesn't stop the queue. An
interrupted job is run again from its checkpoint, up to max_attempts runs in all, then marked failed. The worker
exits after idle_s seconds with nothing to do; submit() and resume() start it when it isn't running.

Kinds
    'index'      footage scan (core_tools.footage, analyze=True), transcripts (speech.words) of files with talking,
                 fact log + segment map per folder (factlog.py, local vision model; default) or the older footage
                 log (step 'shot_log', shot_log.log_folder), archive (archive.update: the job's files added to the
                 archive database from those caches), for a folder or a list of files.
    'archive'    archive.update on its own: inputs paths (optional; default every file the caches know), span_words,
                 pause_s, device, batch (archive.BUILD_DEFAULTS).
    other kinds  register_kind(name, func) in a module the worker imports (LETITEDIT_JOB_KINDS: comma-separated
                 module names), or name the function directly as 'module:function' (or 'C:\\path\\file.py:function').
    A kind is func(ctx) -> outputs dict. ctx.inputs, ctx.checkpoint (dict), ctx.save(**done) stores a checkpoint,
    ctx.progress(fraction, message), ctx.log(...), ctx.check() raises Cancelled once a cancel was asked for.

Exports are render_queue jobs (C:\\LetItEdit\\cache\\exports); list_all() shows both.

CLI: python jobs.py worker | run <job_id> | list | status <job_id> | submit-index <path> [<path> ...] | cancel <id> |
     resume <id> | ensure-worker
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
import letitedit.core.render_lock as render_lock  # noqa: E402
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import contextlib
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path

HERE = _paths.BRIDGE
sys.path.insert(0, str(HERE))

ROOT = Path(os.environ.get('LETITEDIT_JOBS', (_SAI_ROOT + '\\jobs')))
IDLE_S = float(os.environ.get('LETITEDIT_JOBS_IDLE', '300'))     # worker exits after this long with nothing to do
POLL_S = 0.5
CANCEL_GRACE_S = 20.0          # a running job asked to cancel is killed when it hasn't stopped after this long
DEFAULT_TIMEOUT_S = 6 * 3600
DEFAULT_ATTEMPTS = 3
NO_WINDOW = 0x08000000
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
ACTIVE = ('running',)
FINAL = ('done', 'failed', 'cancelled')


class Cancelled(RuntimeError):
    pass


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _root(root=None):
    return Path(root) if root else ROOT


def _read(path, default=None):
    for _ in range(5):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except FileNotFoundError:
            return default
        except (OSError, ValueError):
            time.sleep(0.05)     # being replaced on Windows: try again
    return default


def _write(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + f'.{uuid.uuid4().hex[:6]}.tmp')
    tmp.write_text(json.dumps(data, indent=1, default=str), encoding='utf-8')
    for _ in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, path)


def _pid_alive(pid):
    import letitedit.core.render_lock as render_lock
    return render_lock.pid_alive(pid)


# ------------------------------------------------------------------ kinds

KINDS = {}


def register_kind(name, func, timeout_s=DEFAULT_TIMEOUT_S, about=''):
    """Make `name` a job kind run by func(ctx) -> outputs dict. timeout_s is the default time limit of its jobs."""
    KINDS[name] = {'func': func, 'timeout_s': timeout_s, 'about': about}
    return func


def kind(name, timeout_s=DEFAULT_TIMEOUT_S, about=''):
    def deco(func):
        return register_kind(name, func, timeout_s, about)
    return deco


def _load_kind_modules():
    for m in filter(None, (x.strip() for x in os.environ.get('LETITEDIT_JOB_KINDS', '').split(','))):
        try:
            importlib.import_module(m)
        except Exception:  # noqa: BLE001 - a broken plug-in must not stop the worker
            pass


def resolve(kind_name):
    """The kind's entry {'func', 'timeout_s', 'about'}; 'module:function' and 'file.py:function' load on demand."""
    if kind_name in KINDS:
        return KINDS[kind_name]
    _load_kind_modules()
    if kind_name in KINDS:
        return KINDS[kind_name]
    if ':' in kind_name:
        mod, _, fn = kind_name.rpartition(':')
        if mod.lower().endswith('.py'):
            spec = importlib.util.spec_from_file_location(Path(mod).stem, mod)
            module = importlib.util.module_from_spec(spec)
            sys.modules.setdefault(Path(mod).stem, module)
            spec.loader.exec_module(module)
        else:
            module = importlib.import_module(mod)
        if kind_name in KINDS:     # the module registered it under this exact name
            return KINDS[kind_name]
        return {'func': getattr(module, fn), 'timeout_s': DEFAULT_TIMEOUT_S, 'about': ''}
    raise KeyError(f'Unknown job kind {kind_name!r}; known: {sorted(KINDS)} (or "module:function")')


# ------------------------------------------------------------------ the job a kind sees

class Context:
    def __init__(self, job_dir):
        self.dir = Path(job_dir)
        self.job_id = self.dir.name
        self.spec = _read(self.dir / 'spec.json', {})
        self.inputs = self.spec.get('inputs') or {}
        self.checkpoint = _read(self.dir / 'checkpoint.json', {}) or {}
        self.resumed = bool(self.checkpoint)
        self._log = open(self.dir / 'log.txt', 'a', encoding='utf-8', buffering=1)

    def log(self, *a):
        self._log.write(time.strftime('%H:%M:%S ') + ' '.join(map(str, a)) + '\n')

    def save(self, **done):
        """Store checkpoint values (merged into ctx.checkpoint)."""
        self.checkpoint.update(done)
        _write(self.dir / 'checkpoint.json', self.checkpoint)

    def progress(self, fraction=None, message=None):
        st = _read(self.dir / 'status.json', {}) or {}
        if fraction is not None:
            st['progress'] = round(max(0.0, min(1.0, float(fraction))), 4)
        if message is not None:
            st['message'] = str(message)[:500]
        st.update(updated=now(), pid=os.getpid())
        _write(self.dir / 'status.json', st)

    def cancelled(self):
        return (self.dir / 'cancel').exists()

    def check(self):
        if self.cancelled():
            raise Cancelled('Cancelled')

    def close(self):
        try:
            self._log.close()
        except OSError:
            pass


# ------------------------------------------------------------------ submit / status / control

def _new_id():
    return time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]


LANES = {'urgent': 0, 'normal': 1, 'dev': 2}   # T258: a spec's lane orders the queue; a spec without one is 'normal'


def submit(kind_name, inputs=None, timeout_s=None, max_attempts=DEFAULT_ATTEMPTS, root=None, start_worker=True,
           label=None, lane=None, job_id=None):
    """Queue a job. kind_name: 'index', a registered kind or 'module:function'. timeout_s: the job's time limit (the
    kind's default when None). lane: 'urgent', 'normal' or 'dev' (jobs run lane first; within a lane a job resuming
    after a stop first, then oldest first; None: as 'normal', so a queue without lanes keeps its old order).
    job_id: a fixed id instead of a new one; submitting it again returns the existing job unchanged, so a caller that
    crashed part way can repeat the call. Returns its status."""
    entry = resolve(kind_name)
    r = _root(root)
    job_id = job_id or _new_id()
    d = r / job_id
    if (d / 'spec.json').is_file() and (d / 'status.json').is_file():
        out = status(job_id, root=r)
        if start_worker:
            out['worker'] = ensure_worker(root=r)
        return out
    d.mkdir(parents=True, exist_ok=True)
    spec = {'job_id': job_id, 'kind': kind_name, 'inputs': inputs or {}, 'label': label, 'created': now(),
            'created_t': time.time(), 'timeout_s': float(timeout_s or entry['timeout_s']),
            'max_attempts': int(max_attempts)}
    if lane is not None:
        if lane not in LANES:
            raise ValueError(f'lane must be one of {sorted(LANES)}')
        spec['lane'] = lane
    _write(d / 'spec.json', spec)                 # status.json last: a folder without it is not a job yet
    _write(d / 'status.json', {'state': 'queued', 'progress': 0, 'message': 'Queued', 'attempts': 0, 'updated': now()})
    out = status(job_id, root=r)
    if start_worker:
        out['worker'] = ensure_worker(root=r)
    return out


def status(job_id, root=None):
    d = _root(root) / job_id
    spec = _read(d / 'spec.json')
    if spec is None:
        raise KeyError(f'Unknown job {job_id}')
    st = _read(d / 'status.json', {}) or {}
    state = st.get('state')
    if state in ACTIVE and not _pid_alive(st.get('pid')):
        state = 'interrupted'
        st['message'] = (f'Its process (pid {st.get("pid")}) stopped without finishing (PC restart, crash or killed); '
                         'the worker runs it again from its checkpoint.')
    out = {'job_id': job_id, 'kind': spec.get('kind'), 'label': spec.get('label'), 'state': state,
           'progress': st.get('progress', 0), 'message': st.get('message'), 'attempts': st.get('attempts', 0),
           'max_attempts': spec.get('max_attempts'), 'timeout_s': spec.get('timeout_s'), 'created': spec.get('created'),
           'started': st.get('started'), 'finished': st.get('finished'), 'updated': st.get('updated'),
           'pid': st.get('pid') if state in ACTIVE else None, 'outputs': st.get('outputs'), 'error': st.get('error'),
           'cancel_requested': (d / 'cancel').exists(), 'folder': str(d)}
    cp = _read(d / 'checkpoint.json')
    if cp:
        out['checkpoint_keys'] = sorted(cp)
    return out


def list_jobs(limit=20, root=None, states=None):
    r = _root(root)
    if not r.exists():
        return []
    out = []
    for d in sorted((x for x in r.iterdir() if x.is_dir()), key=lambda x: x.name, reverse=True):
        try:
            s = status(d.name, root=r)
        except KeyError:
            continue
        if states and s['state'] not in states:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def log_tail(job_id, chars=3000, root=None):
    try:
        t = (_root(root) / job_id / 'log.txt').read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    return t[-chars:]


def cancel(job_id, root=None):
    d = _root(root) / job_id
    s = status(job_id, root=root)
    if s['state'] in FINAL:
        return {**s, 'note': f'Already {s["state"]}'}
    (d / 'cancel').write_text(now(), encoding='utf-8')
    if s['state'] in ('queued', 'interrupted'):
        st = _read(d / 'status.json', {}) or {}
        st.update(state='cancelled', message='Cancelled before it ran', finished=now(), updated=now())
        _write(d / 'status.json', st)
        return status(job_id, root=root)
    return {**s, 'note': f'Cancel requested; the job stops at its next check, or is killed after {CANCEL_GRACE_S:g} s.'}


def resume(job_id, root=None, start_worker=True):
    """Queue an interrupted, failed or cancelled job again; it continues from its checkpoint. Its attempt count
    starts again."""
    d = _root(root) / job_id
    s = status(job_id, root=root)
    if s['state'] in ACTIVE:
        return {**s, 'note': 'Already running'}
    if s['state'] == 'done':
        return {**s, 'note': 'Already finished'}
    (d / 'cancel').unlink(missing_ok=True)
    st = _read(d / 'status.json', {}) or {}
    st.update(state='queued', message='Queued again (continues from its checkpoint)', attempts=0, error=None,
              finished=None, updated=now())
    _write(d / 'status.json', st)
    out = status(job_id, root=root)
    if start_worker:
        out['worker'] = ensure_worker(root=root)
    return out


def list_all(limit=20, root=None):
    """{'jobs': these jobs, 'exports': render_queue's export jobs}."""
    exports = []
    try:
        import letitedit.timeline.render_queue as render_queue
        exports = render_queue.list_jobs(limit)
    except Exception as e:  # noqa: BLE001
        exports = [{'error': f'render_queue: {e}'}]
    return {'jobs': list_jobs(limit, root=root), 'exports': exports}


# ------------------------------------------------------------------ worker process

def worker_info(root=None):
    """{'running': bool, 'pid', 'started', 'current', 'beat'} of this jobs folder's worker."""
    w = _read(_root(root) / 'worker.json', {}) or {}
    alive = _pid_alive(w.get('pid'))
    return {'running': alive, **({k: w.get(k) for k in ('pid', 'started', 'current', 'beat')} if w else {})}


def ensure_worker(root=None, wait_s=10.0, idle_s=None):
    """Start the worker when it isn't running (detached: closing the AI session doesn't stop it). Waits up to wait_s
    for it to report in. Returns worker_info plus 'started_now'."""
    r = _root(root)
    r.mkdir(parents=True, exist_ok=True)
    w = worker_info(r)
    if w['running']:
        return {**w, 'started_now': False}
    pid = launch_worker(r, idle_s)
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        w = worker_info(r)
        if w['running']:
            break
        time.sleep(0.2)
    if not w['running']:
        w['note'] = (f'Started a worker (pid {pid}) but it had not reported in {wait_s:g} s; if another worker holds '
                     f'{r / "worker.lock"} it runs these jobs.')
    return {**w, 'started_now': True, 'launched_pid': pid}


def launch_worker(root=None, idle_s=None):
    """Start `python jobs.py worker <root> <idle_s>` outside this process tree and its jobs (render_lock.start_independent).
    A WMI-started process doesn't inherit this process's environment variables, so root and idle_s go as arguments."""
    r = _root(root)
    idle = f'{IDLE_S if idle_s is None else float(idle_s):g}'
    pyw = Path(sys.executable).with_name('pythonw.exe')
    exe = pyw if pyw.exists() else Path(sys.executable)
    script = (_paths.BRIDGE / 'jobs.py')
    # The broker first (out of this process's jobs and tree, with the user's own environment), breakaway after;
    # never started inside a job it would die with.
    return render_lock.start_independent([str(exe), str(script), 'worker', str(r), idle], cwd=str(HERE),
                                         creationflags=DETACHED, broker_first=True, inherit=False)


@contextlib.contextmanager
def _worker_lock(root):
    """Held for the worker's life: a second worker on the same folder exits at once."""
    import msvcrt
    f = root / 'worker.lock'
    fd = os.open(str(f), os.O_RDWR | os.O_CREAT)
    try:
        os.lseek(fd, 0, 0)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError:
        os.close(fd)
        yield False
        return
    try:
        yield True
    finally:
        try:
            os.lseek(fd, 0, 0)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        os.close(fd)


def _set(d, **kw):
    st = _read(d / 'status.json', {}) or {}
    st.update(kw, updated=now())
    _write(d / 'status.json', st)
    return st


def _next_job(root):
    """(job_dir, what): what is 'run' (start it), 'adopt' (its process outlived the worker that started it: watch it
    to its end, enforcing cancel and the time limit) or None (nothing to do)."""
    waiting = []
    for d in sorted(x for x in root.iterdir() if x.is_dir()):
        spec = _read(d / 'spec.json')
        st = _read(d / 'status.json')
        if not spec or not st:
            continue
        state = st.get('state')
        if state in ACTIVE:
            seen = _child_state(st)
            if seen == 'alive':
                return d, 'adopt'
            if seen == 'unknown':
                _wait_or_fail_unknown(d, spec, st)
                continue
            state = 'interrupted'
            _set(d, state='interrupted', message=f'Its process (pid {st.get("pid")}) stopped without finishing.')
        if (d / 'cancel').exists() and state in ('queued', 'interrupted'):
            _set(d, state='cancelled', message='Cancelled before it ran again', finished=now())
            continue
        if state == 'interrupted':
            if st.get('attempts', 0) >= spec.get('max_attempts', DEFAULT_ATTEMPTS):
                _set(d, state='failed', finished=now(), message=(
                    f'Stopped without finishing {st.get("attempts")} times (max_attempts '
                    f'{spec.get("max_attempts")}); resume() queues it again.'),
                    error=st.get('error') or 'interrupted repeatedly')
                continue
            waiting.append((_order_key(spec, True), d))
        elif state == 'queued':
            waiting.append((_order_key(spec, False), d))
    pick = sorted(waiting, key=lambda x: x[0])
    return (pick[0][1], 'run') if pick else (None, None)


def _order_key(spec, interrupted=False):
    """(lane, resuming first, created). A spec without a lane counts as 'normal', so a queue without lanes keeps its
    old order (interrupted jobs first, then oldest first)."""
    return (LANES.get(spec.get('lane') or 'normal', 1), 0 if interrupted else 1, spec.get('created_t', 0))


def queue_order(root=None):
    """The job ids waiting to run, in the order the worker takes them: by lane; within a lane interrupted ones first,
    then oldest first. Cancelled ones still waiting are left out. Read only."""
    r = _root(root)
    if not r.is_dir():
        return []
    waiting = []
    for d in (x for x in r.iterdir() if x.is_dir()):
        spec, st = _read(d / 'spec.json'), _read(d / 'status.json')
        if not spec or not st or (d / 'cancel').exists():
            continue
        state = st.get('state')
        if state in ACTIVE and _child_state(st) == 'gone':
            state = 'interrupted'
        if state == 'interrupted' and st.get('attempts', 0) < spec.get('max_attempts', DEFAULT_ATTEMPTS):
            waiting.append((_order_key(spec, True), d.name))
        elif state == 'queued':
            waiting.append((_order_key(spec, False), d.name))
    return [n for _, n in sorted(waiting)]


def _process_started(pid):
    """When a process started (Windows FILETIME ticks), or None when it isn't running or can't be asked."""
    if not pid or os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
            return None
        code = wintypes.DWORD()
        if k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:
            return None                                  # exited
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        k.CloseHandle(h)


def _child_state(st):
    """'alive' when a running job's own process still runs, checked by pid, creation time and program; 'gone' when it
    doesn't (or the pid now belongs to another process); 'unknown' when a process runs under that pid but it can't be
    shown to be this job's (a record without its creation time or program, from older code, or a process that can't be
    read). Only an 'alive' one is ever adopted, resumed or stopped."""
    seen, handle = render_lock.verify_process(st.get('pid'), st.get('pid_started'), st.get('pid_image'))
    if handle is not None:
        handle.close()
    return seen


def _child_alive(st):
    return _child_state(st) == 'alive'


def _wait_or_fail_unknown(d, spec, st):
    """A job whose recorded process can't be verified: never adopted, never killed (the pid may be anyone's now, the
    person's editor included). It waits while within its time limit, then fails, leaving that process alone."""
    limit = float(spec.get('timeout_s') or DEFAULT_TIMEOUT_S)
    began = float(st.get('attempt_started_t') or 0) or None
    if began is None:
        try:
            began = (d / 'status.json').stat().st_mtime
        except OSError:
            began = time.time()
    if time.time() - began <= limit:
        return
    _set(d, state='failed', finished=now(), error='unverified process',
         message=(f'Its process (pid {st.get("pid")}) could not be shown to be this job\'s (no recorded start time or '
                  'program, or letitedit is not allowed to look at it), so it was not stopped and no second attempt '
                  'was started beside it; the job was given up after its time limit. resume() queues it again.'))


def _run_child(root, d, beat):
    """Run one job in its own process; enforce its time limit and cancel. Returns its final state."""
    spec = _read(d / 'spec.json', {})
    st = _read(d / 'status.json', {}) or {}
    attempts = st.get('attempts', 0) + 1
    was = st.get('state')
    _set(d, state='running', attempts=attempts, started=st.get('started') or now(), pid=None, pid_started=None,
         pid_image=None,
         message=('Resuming from its checkpoint' if was == 'interrupted' else 'Starting') + f' (attempt {attempts})')
    exe = Path(sys.executable)
    env = dict(os.environ, LETITEDIT_JOBS=str(root))

    def record(ident):         # before the child runs a single instruction (render_lock.spawn_recorded)
        _set(d, pid=ident['pid'], pid_started=ident['started'], pid_image=ident['image'], attempt_started_t=time.time())
    proc = render_lock.spawn_recorded([str(exe), str((_paths.BRIDGE / 'jobs.py')), 'run', d.name, str(root)],
                                      record, cwd=str(HERE), env=env, creationflags=NO_WINDOW,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return _supervise(d, proc.pid, beat, proc)


def _supervise(d, pid, beat, proc=None):
    """Watch a job's process to its end: cancel (killed after CANCEL_GRACE_S) and the time limit (counted from the
    attempt's start, so a worker that adopts an orphan keeps the same deadline). Returns its final state."""
    spec = _read(d / 'spec.json', {}) or {}
    st = _read(d / 'status.json', {}) or {}
    limit = float(spec.get('timeout_s') or DEFAULT_TIMEOUT_S)
    t_start = float(st.get('attempt_started_t') or time.time())
    cancel_at = None
    why = None
    adopted = None
    if proc is None:
        # an orphan: only ever through a handle opened on the process verified as this job's (pid, creation time and
        # program), so a pid reused meanwhile is never touched; one left suspended at its start is let run
        seen, adopted = render_lock.verify_process(st.get('pid'), st.get('pid_started'), st.get('pid_image'))
        if adopted is not None:
            with contextlib.suppress(OSError):
                adopted.resume()

    def alive():
        return proc.poll() is None if proc is not None else (adopted is not None and adopted.alive())

    def stop():           # the job's process; what it started ends with it (its job object closes)
        if proc is not None:
            with contextlib.suppress(OSError):
                proc.kill()
        elif adopted is not None:
            adopted.terminate()
    try:
        while alive():
            beat(d.name)
            if (d / 'cancel').exists():
                cancel_at = cancel_at or time.monotonic()
                if time.monotonic() - cancel_at > CANCEL_GRACE_S:
                    stop()
                    why = 'cancelled'
            if time.time() - t_start > limit:
                stop()
                why = 'timeout'
            time.sleep(POLL_S)
    finally:
        if adopted is not None:
            adopted.close()
    if proc is not None:
        proc.wait()
    code = proc.returncode if proc is not None else 'unknown: adopted'
    st = _read(d / 'status.json', {}) or {}
    if why == 'cancelled':
        _set(d, state='cancelled', message=f'Cancelled (killed after {CANCEL_GRACE_S:g} s)', finished=now())
    elif why == 'timeout':
        _set(d, state='failed', finished=now(), message=f'Timed out after {limit:g} s (timeout_s); resume() continues '
             'from its checkpoint.', error=f'timeout after {limit:g} s')
    elif st.get('state') in ACTIVE:
        _set(d, state='interrupted', message=f'Its process exited ({code}) without finishing.',
             error=f'process exit code {code}')
    return (_read(d / 'status.json', {}) or {}).get('state')


def worker(root=None, idle_s=None):
    """The queue loop; returns when idle for idle_s seconds or when another worker already serves `root`."""
    r = _root(root)
    r.mkdir(parents=True, exist_ok=True)
    idle_s = IDLE_S if idle_s is None else float(idle_s)
    with _worker_lock(r) as mine:
        if not mine:
            return 'another worker is running'
        info = {'pid': os.getpid(), 'started': now(), 'current': None, 'beat': now()}
        last_beat = [0.0]

        def beat(current=None):
            if time.monotonic() - last_beat[0] >= 2:
                info.update(current=current, beat=now())
                _write(r / 'worker.json', info)
                last_beat[0] = time.monotonic()
        _write(r / 'worker.json', info)
        idle_since = time.monotonic()
        while True:
            try:
                d, what = _next_job(r)
            except Exception:  # noqa: BLE001 - a broken job folder must not stop the queue
                d, what = None, None
            if d is None:
                beat(None)
                if time.monotonic() - idle_since > idle_s:
                    break
                time.sleep(POLL_S)
                continue
            try:
                info['current'] = d.name
                if what == 'adopt':                      # its worker died; its process didn't: supervise it
                    st = _read(d / 'status.json', {}) or {}
                    _supervise(d, st.get('pid'), beat)
                else:
                    _run_child(r, d, beat)
            except Exception as e:  # noqa: BLE001
                try:
                    _set(d, state='failed', message=f'worker error: {e}'[:500], error=traceback.format_exc()[-2000:],
                         finished=now())
                except Exception:  # noqa: BLE001
                    pass
            info['current'] = None
            last_beat[0] = 0
            beat(None)
            idle_since = time.monotonic()
        info.update(current=None, beat=now(), stopped=now())
        _write(r / 'worker.json', info)
        return 'idle'


def run_job(job_id, root=None):
    """Run one job in this process (the worker's child). Writes its final state."""
    d = _root(root) / job_id
    ctx = Context(d)
    _set(d, pid=os.getpid())
    try:
        entry = resolve(ctx.spec['kind'])
        ctx.log(f'start kind={ctx.spec["kind"]} attempt={(_read(d / "status.json", {}) or {}).get("attempts")}'
                + (f' resuming from {sorted(ctx.checkpoint)}' if ctx.resumed else ''))
        ctx.check()
        outputs = entry['func'](ctx)
        _set(d, state='done', progress=1, message='Finished', outputs=outputs, finished=now(), error=None)
        ctx.log('done')
    except Cancelled:
        _set(d, state='cancelled', message='Cancelled', finished=now())
        ctx.log('cancelled')
    except BaseException as e:  # noqa: BLE001
        tb = traceback.format_exc()
        ctx.log(tb)
        _set(d, state='failed', message=f'{type(e).__name__}: {e}'[:500], error=tb[-3000:], finished=now())
    finally:
        ctx.close()


# ------------------------------------------------------------------ the 'index' kind

MEDIA = {'video', 'audio'}


def _index_files(paths):
    import letitedit.server.core_tools as core_tools
    files, _, _ = core_tools._collect(paths)
    return [str(f) for f in files]


@contextlib.contextmanager
def _no_background_transcription():
    """core_tools.footage starts transcription threads for talking files; the job does that step itself, in order."""
    import letitedit.server.core_tools as core_tools
    a, b = core_tools.transcribe_in_background, core_tools.sheets_in_background
    core_tools.transcribe_in_background = lambda paths: []
    core_tools.sheets_in_background = lambda paths: None
    try:
        yield
    finally:
        core_tools.transcribe_in_background, core_tools.sheets_in_background = a, b


def _default_index_steps():
    """footage, words, facts, archive; plus emotion (after words) when the emotion_graph setting is on."""
    try:
        import letitedit.footage.emotion_graph as emotion_graph
        emo = emotion_graph.enabled()
    except Exception:  # noqa: BLE001
        emo = False
    return ['footage', 'words'] + (['emotion'] if emo else []) + ['facts', 'archive']


def _index_footage(steps, cp, media, ctx, page, prog, errors, base, weights):
    """Scan footage in resumable pages and checkpoint detected speech."""
    # 1. footage scan: probe, sound/picture analysis, voice detection (all cached by core_tools / perception)
    if 'footage' in steps:
        import letitedit.server.core_tools as core_tools
        import letitedit.sound.music as music
        talk = dict(cp.get('talk', {}))
        k = int(cp.get('footage_done', 0))
        while k < len(media):
            ctx.check()
            chunk = media[k:k + page]
            prog('footage', k / max(1, len(media)), f'footage scan: files {k + 1}-{k + len(chunk)} of {len(media)} '
                 '(probe, sound and picture analysis, voice detection)')
            try:
                with _no_background_transcription():
                    _, rep = core_tools.footage([Path(f) for f in chunk], speech=True, transcribe=False, sheet=False,
                                                offset=0, limit=len(chunk), analyze=True)
                with open(ctx.dir / 'footage.txt', 'a', encoding='utf-8') as fh:
                    fh.write(rep.get('text', '') + '\n\n')
            except Exception as e:  # noqa: BLE001
                errors.append({'step': 'footage', 'files': chunk, 'error': f'{type(e).__name__}: {e}'[:300]})
                ctx.log(traceback.format_exc())
            for f in chunk:
                try:
                    if core_tools.probe(Path(f)).get('audio'):
                        talk[f] = round(sum(b - a for a, b in music.voice_times(f)), 1)
                    else:
                        talk[f] = 0.0
                except Exception:  # noqa: BLE001
                    talk[f] = 0.0
            k += len(chunk)
            ctx.save(footage_done=k, talk=talk, errors=errors)
        cp = ctx.checkpoint
        base[0] += weights['footage']
    return cp


def _index_words(cp, steps, media, talk_s, ctx, prog, inp, kinds, errors, base, weights):
    """Transcribe talking files and optionally build word sheets, checkpointing each file."""
    # 2. transcripts of files with talking (speech.words: GPU whisper when available, cached)
    transcribed = list(cp.get('words_done', []))
    if 'words' in steps:
        import letitedit.footage.speech as speech
        talk = cp.get('talk')
        if talk is None:      # footage step skipped: detect voice now
            import letitedit.sound.music as music
            talk = {}
            for f in media:
                try:
                    talk[f] = round(sum(b - a for a, b in music.voice_times(f)), 1)
                except Exception:  # noqa: BLE001
                    talk[f] = 0.0
            ctx.save(talk=talk)
        talking = [f for f in media if (talk.get(f) or 0) > talk_s]
        for i, f in enumerate(talking):
            if f in transcribed:
                continue
            ctx.check()
            prog('words', i / max(1, len(talking)), f'transcribing {Path(f).name} ({i + 1} of {len(talking)} files '
                 f'with talking; engine {speech.engine()})')
            try:
                n = len(speech.words(f))
                ctx.log(f'words {f}: {n}')
                if inp.get('word_sheets', True) and kinds[f] == 'video':
                    try:
                        import letitedit.server.core_tools as core_tools
                        core_tools.word_sheet_file(Path(f))
                    except Exception:  # noqa: BLE001
                        ctx.log('word sheet failed', f, traceback.format_exc()[-500:])
            except Exception as e:  # noqa: BLE001
                errors.append({'step': 'words', 'file': f, 'error': f'{type(e).__name__}: {e}'[:300]})
                ctx.log(traceback.format_exc())
            transcribed.append(f)
            ctx.save(words_done=transcribed, errors=errors)
        base[0] += weights['words']
    return transcribed


def _index_emotion(cp, steps, videos, ctx, prog, errors, base, weights):
    """Build and checkpoint the requested emotion graphs."""
    # 2b. emotion graph (emotion_graph.py: mood per sentence / shot from the connected AI's fast model, run headless;
    # cached per file, so a file already done costs nothing)
    emotion_done = dict(cp.get('emotion_done', {}))
    if 'emotion' in steps:
        import letitedit.footage.emotion_graph as emotion_graph
        for i, f in enumerate(videos):
            if f in emotion_done:
                continue
            ctx.check()
            prog('emotion', i / max(1, len(videos)), f'emotion graph: {Path(f).name} ({i + 1} of {len(videos)} videos; '
                 'uses the connected AI')
            r = emotion_graph.build([f], check=ctx.check,
                                    progress=lambda fr, m, i=i: prog('emotion', (i + fr) / max(1, len(videos)), m))
            emotion_done[f] = r.get(f, 'skipped')
            if str(emotion_done[f]).startswith('error'):
                errors.append({'step': 'emotion', 'file': f, 'error': emotion_done[f]})
            ctx.save(emotion_done=emotion_done, errors=errors)
        base[0] += weights['emotion']
    return emotion_done


def _index_shot_log(cp, steps, inp, ctx, videos, prog, errors, base, weights):
    """Log footage through the selected engine, recording skipped LLM work."""
    # 3. footage log (shot_log: a local vision model; waits for the PC's model GPU lock, up to model_tools' limit)
    logged = list(cp.get('shot_log_done', []))
    log_engine = None
    if 'shot_log' in steps:
        import letitedit.footage.shot_log as shot_log
        kw = dict(inp.get('shot_log') or {})
        if inp.get('context'):
            kw['context'] = inp['context']
        e = kw.get('engine')
        log_engine = {'engine': e, 'why': 'engine argument'} if isinstance(e, str) else shot_log._engine()
        if log_engine.get('engine') == 'llm':
            ctx.log(f"footage log step not run: engine 'llm' ({log_engine.get('why')}); "
                    'the LLM writes it with letitedit_log_frames / letitedit_log_write')
            videos_to_log = []
        else:
            videos_to_log = videos
        for i, f in enumerate(videos_to_log):
            if f in logged:
                continue
            ctx.check()
            prog('shot_log', i / max(1, len(videos)), f'footage log: {Path(f).name} ({i + 1} of {len(videos)} videos; '
                 'local vision model, waits for the model GPU lock C:\\LetItEdit\\cache\\models\\gpu.lock up to 2 h)')
            try:
                shot_log.log_folder([f], **kw)
            except Exception as e:  # noqa: BLE001
                errors.append({'step': 'shot_log', 'file': f, 'error': f'{type(e).__name__}: {e}'[:300]})
                ctx.log(traceback.format_exc())
            logged.append(f)
            ctx.save(shot_log_done=logged, errors=errors)
        base[0] += weights['shot_log']
    return logged, log_engine


def _index_archive(cp, steps, ctx, prog, media, inp, errors, base, weights):
    """Update the archive from indexed media while preserving cancellation."""
    # 4. archive: the job's files added to the archive database (archive.py; reads the caches above, incremental)
    archived = cp.get('archive_done') if isinstance(cp.get('archive_done'), dict) else None
    if 'archive' in steps and archived is None:
        ctx.check()
        prog('archive', 0.0, 'archive: adding the files to the archive database')
        try:
            import letitedit.footage.archive as archive
            rep = archive.update(files=media, progress=lambda f, m: prog('archive', f, m), check=ctx.check,
                                 **{k: inp[k] for k in ('span_words', 'pause_s', 'device', 'batch') if k in inp})
            archived = {k: rep[k] for k in ('files_seen', 'files_new_or_changed', 'contents_built',
                                            'contents_unchanged', 'spans_added', 'errors', 'db')}
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            errors.append({'step': 'archive', 'error': f'{type(e).__name__}: {e}'[:300]})
            ctx.log(traceback.format_exc())
            archived = {'error': f'{type(e).__name__}: {e}'[:300]}
        ctx.save(archive_done=archived, errors=errors)
        base[0] += weights['archive']
    return archived


def index_kind(ctx):
    """inputs: paths (a folder, files, or a list of both; folders are not searched below), steps (any of 'footage',
    'words', 'emotion', 'shot_log', 'facts', 'archive'; default footage, words, facts, archive, plus emotion when
    the emotion_graph setting is on), page (files per footage pass, default 20), talk_s (seconds of detected
    voice that make a file count as having talking, default 0.5), shot_log (dict of shot_log.log settings),
    context (text given to the footage log model with every stretch), word_sheets (default True), facts (dict of
    factlog.facts settings, factlog.DEFAULTS), segments (dict of factlog.SEGMENT_DEFAULTS settings)."""
    import letitedit.footage.perception as pc
    inp = ctx.inputs
    paths = inp.get('paths') or inp.get('path')
    if not paths:
        raise ValueError("index needs inputs['paths'] (a folder, a file, or a list)")
    steps = inp.get('steps') or _default_index_steps()
    page = int(inp.get('page', 20))
    talk_s = float(inp.get('talk_s', 0.5))
    cp = ctx.checkpoint
    files = cp.get('files') or _index_files(paths)
    if 'files' not in cp:
        ctx.save(files=files)
    kinds = cp.get('kinds') or {f: pc.kind(Path(f)) for f in files}
    if 'kinds' not in cp:
        ctx.save(kinds=kinds)
    media = [f for f in files if kinds[f] in MEDIA]
    videos = [f for f in files if kinds[f] == 'video']
    errors = list(cp.get('errors', []))
    weights = {'footage': 0.3, 'words': 0.3, 'emotion': 0.2, 'shot_log': 0.4, 'facts': 0.4, 'archive': 0.05}
    total_w = sum(weights[s] for s in steps if s in weights) or 1
    base = [0.0]

    def prog(step, frac, msg):
        ctx.progress((base[0] + weights[step] * frac) / total_w, msg)

    cp = _index_footage(steps, cp, media, ctx, page, prog, errors, base, weights)

    transcribed = _index_words(cp, steps, media, talk_s, ctx, prog, inp, kinds, errors, base, weights)

    emotion_done = _index_emotion(cp, steps, videos, ctx, prog, errors, base, weights)

    logged, log_engine = _index_shot_log(cp, steps, inp, ctx, videos, prog, errors, base, weights)

    facts_done = list(cp.get('facts_done', []))
    seg_maps = list(cp.get('segment_maps', []))
    if 'facts' in steps:
        import letitedit.core.hardware as hardware
        import letitedit.footage.factlog as factlog
        fkw = dict(inp.get('facts') or {})
        skw = dict(inp.get('segments') or {})
        vids_, stills = factlog._media(files) if files else ([], [])   # a photo kept as .HEIC + .jpeg: once
        todo = videos + [str(p) for p in stills]
        t_facts = time.time()
        for i, f in enumerate(todo):
            if f in facts_done:
                continue
            ctx.check()
            prog('facts', 0.9 * i / max(1, len(todo)), f'fact log: {Path(f).name} ({i + 1} of {len(todo)}; local '
                 'vision model, waits for the model GPU lock)')
            try:
                factlog.facts(f, **fkw)
            except hardware.LocalModelUnavailable as e:   # no graphics card for the model: none of them, said once
                if not any(x.get('step') == 'facts' and x.get('skipped') for x in errors):
                    errors.append({'step': 'facts', 'skipped': len(todo) - len(facts_done), 'error': e.fact})
                ctx.save(errors=errors)
                break
            except Exception as e:  # noqa: BLE001
                errors.append({'step': 'facts', 'file': f, 'error': f'{type(e).__name__}: {e}'[:300]})
                ctx.log(traceback.format_exc())
            facts_done.append(f)
            ctx.save(facts_done=facts_done, errors=errors)
        if not seg_maps and todo:
            groups = {}
            for f in todo:
                groups.setdefault(str(Path(f).parent), []).append(f)
            for folder, fs in groups.items():
                ctx.check()
                prog('facts', 0.95, f'segment map: {Path(folder).name} ({len(fs)} files)')
                try:
                    m = factlog.segment_map(fs, build=False, facts_kw=fkw, **skw)
                    seg_maps.append({'folder': folder, 'files': len(m['files']), 'segments': len(m['segments']),
                                     'text_file': m['text_file'], 'missing': m['missing'], 'seconds': m['seconds']})
                except Exception as e:  # noqa: BLE001
                    errors.append({'step': 'segments', 'folder': folder, 'error': f'{type(e).__name__}: {e}'[:300]})
                    ctx.log(traceback.format_exc())
            ctx.save(segment_maps=seg_maps, errors=errors, facts_s=round(time.time() - t_facts, 1))
        base[0] += weights['facts']

    archived = _index_archive(cp, steps, ctx, prog, media, inp, errors, base, weights)

    talk = ctx.checkpoint.get('talk', {})
    return {'archive': archived, 'files': len(files), 'media': len(media), 'videos': len(videos), 'steps': steps,
            'talking': sorted(f for f in media if (talk.get(f) or 0) > talk_s),
            'transcribed': len(transcribed), 'logged': len(logged), 'facts': len(facts_done),
            'emotion': emotion_done,
            'segment_maps': seg_maps, 'errors': errors,
            'shot_log_engine': log_engine,
            'not_logged': (sorted(videos) if log_engine and log_engine.get('engine') == 'llm' else []),
            'footage_text': str(ctx.dir / 'footage.txt') if (ctx.dir / 'footage.txt').exists() else None}


register_kind('index', index_kind, timeout_s=12 * 3600,
              about='footage scan, transcripts of files with talking, footage log, archive; for a folder or files')


def archive_kind(ctx):
    """inputs: paths (optional: a folder, files or a list; default every file the caches know), span_words, pause_s,
    device, batch (archive.BUILD_DEFAULTS). Incremental: an interrupted run continues with the clips not yet added."""
    import letitedit.footage.archive as archive
    inp = ctx.inputs
    paths = inp.get('paths') or inp.get('path')
    rep = archive.update(files=paths, progress=ctx.progress, check=ctx.check,
                         **{k: inp[k] for k in ('span_words', 'pause_s', 'device', 'batch') if k in inp})
    return rep


register_kind('archive', archive_kind, timeout_s=6 * 3600,
              about='archive database update from the caches (transcripts, footage log, footage scan, GPS)')


def submit_index(paths, steps=None, context=None, shot_log=None, timeout_s=None, root=None, start_worker=True,
                 **more):
    """Queue an 'index' job for a folder, a file or a list of them (see index_kind for the inputs)."""
    if isinstance(paths, (str, Path)):
        paths = [str(paths)]
    inputs = {'paths': [str(p) for p in paths], **more}
    if steps:
        inputs['steps'] = list(steps)
    if context:
        inputs['context'] = context
    if shot_log:
        inputs['shot_log'] = shot_log
    for p in inputs['paths']:
        if not Path(p).exists():
            raise FileNotFoundError(f'Not found: {p}')
    return submit('index', inputs, timeout_s=timeout_s, root=root, start_worker=start_worker,
                  label=', '.join(Path(p).name for p in paths)[:80])


# ------------------------------------------------------------------ CLI

def _main(argv):
    cmd = argv[0] if argv else ''
    if cmd == 'worker':
        root = argv[1] if len(argv) > 1 else None
        if root:
            os.environ['LETITEDIT_JOBS'] = root
        print(worker(root, float(argv[2]) if len(argv) > 2 else None))
        return 0
    if cmd == 'run' and len(argv) >= 2:
        root = argv[2] if len(argv) > 2 else None
        run_job(argv[1], root)
        return 0
    if cmd == 'list':
        print(json.dumps(list_all(), indent=1))
        return 0
    if cmd == 'status' and len(argv) >= 2:
        print(json.dumps(status(argv[1]), indent=1))
        return 0
    if cmd == 'submit-index' and len(argv) >= 2:
        print(json.dumps(submit_index(argv[1:]), indent=1))
        return 0
    if cmd == 'cancel' and len(argv) >= 2:
        print(json.dumps(cancel(argv[1]), indent=1))
        return 0
    if cmd == 'resume' and len(argv) >= 2:
        print(json.dumps(resume(argv[1]), indent=1))
        return 0
    if cmd == 'ensure-worker':
        print(json.dumps(ensure_worker(), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    os.environ.pop('LETITEDIT_TOOL_SERVER_PID', None)  # a job outlives the chat that queued it, and so do its model workers
    sys.exit(_main(sys.argv[1:]))
