"""MCP tools letitedit_status and letitedit_jobs (background job queue, render lock, GPU, disk, local models).

Python: jobs_tools.status_report() -> dict, jobs_tools.jobs(action, ...) -> dict. register(mcp, Image) adds the tools.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import letitedit.core.jobs as J  # noqa: E402
import letitedit.core.render_lock as render_lock  # noqa: E402

MODELS = Path(os.environ.get('LETITEDIT_MODELS_HOME', (_SAI_ROOT + '\\models')))
NO_WINDOW = 0x08000000

SHORT_STATUS = ('What the PC is doing for letitedit: background jobs (running, queued, recent), export jobs, the PC '
                'render lock holder, GPU memory, free disk space, local models present.')
SHORT_JOBS = ('Background jobs: list, status, submit an index job (footage scan, transcripts, footage log) for a '
              'folder or files, cancel, resume.')


def _gpu():
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.used,memory.total,memory.free,utilization.gpu',
                            '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=15,
                           creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return [{'error': f'nvidia-smi not available: {e}'}]
    out = []
    for line in r.stdout.strip().splitlines():
        parts = [x.strip() for x in line.split(',')]
        if len(parts) >= 5:
            def num(x):
                try:
                    return int(float(x))
                except ValueError:
                    return None
            out.append({'name': parts[0], 'used_mb': num(parts[1]), 'total_mb': num(parts[2]),
                        'free_mb': num(parts[3]), 'util_pct': num(parts[4])})
    return out or [{'error': (r.stderr or 'no GPU reported').strip()[:200]}]


def _disk(drive='C:\\'):
    try:
        u = shutil.disk_usage(drive)
        return {'drive': drive, 'free_gb': round(u.free / 1024 ** 3, 1), 'total_gb': round(u.total / 1024 ** 3, 1)}
    except OSError as e:
        return {'drive': drive, 'error': str(e)}


def _work_files():
    import letitedit.core.cache_budget as cache_budget
    return cache_budget.last_trim(os.environ.get('LETITEDIT_CACHE', _SAI_ROOT + '\\cache'))


def _size(path):
    total = 0
    for dp, _, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def models(root=None):
    """Local model files and folders under root (default C:\\LetItEdit\\models): Hugging Face hub repos, torch hub
    checkpoints and loose files, each with its size in MB."""
    root = Path(root or MODELS)
    out = []
    if not root.exists():
        return out
    for hub in (root / 'hf' / 'hub', root / 'hf'):
        if hub.is_dir():
            for d in sorted(hub.glob('models--*')):
                out.append({'model': d.name[len('models--'):].replace('--', '/'), 'where': 'hf',
                            'mb': round(_size(d) / 1024 ** 2)})
    ck = root / 'torch' / 'hub' / 'checkpoints'
    if ck.is_dir():
        for f in sorted(ck.iterdir()):
            out.append({'model': f.name, 'where': 'torch', 'mb': round(_size(f) / 1024 ** 2 if f.is_dir()
                                                                       else f.stat().st_size / 1024 ** 2)})
    for f in sorted(root.iterdir()):
        if f.is_file() and f.suffix.lower() not in ('.txt', '.md', '.json'):
            out.append({'model': f.name, 'where': 'file', 'mb': round(f.stat().st_size / 1024 ** 2)})
    return out


def _gpu_lock():
    """Whether the model GPU lock (model_tools._gpu_turn) is held by any process right now."""
    p = Path(os.environ.get('LETITEDIT_GPU_LOCK', (_SAI_ROOT + '\\cache\\models\\gpu.lock')))
    if not p.exists():
        return {'path': str(p), 'held': False}
    try:
        import msvcrt
        fd = os.open(str(p), os.O_RDWR)
    except (ImportError, OSError):
        return {'path': str(p), 'held': None}
    try:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return {'path': str(p), 'held': False}
        except OSError:
            return {'path': str(p), 'held': True}
    finally:
        os.close(fd)


def _gpu_sharing(fresh_s=30.0):
    """Which processes hold models on the GPU and which wait for GPU memory (model_tools' gpu.has.<pid> and
    gpu.want.<pid> files beside the GPU lock; stale ones and those of processes no longer running left out)."""
    d = Path(os.environ.get('LETITEDIT_GPU_LOCK', (_SAI_ROOT + '\\cache\\models\\gpu.lock'))).parent
    out = {'holding': [], 'asking': []}
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    import time
    for n in names:
        kind, _, pid = n[len('gpu.'):].partition('.')
        if not n.startswith('gpu.') or kind not in ('has', 'want') or not pid.isdigit():
            continue
        try:
            if time.time() - os.stat(d / n).st_mtime > fresh_s or not render_lock.pid_alive(int(pid)):
                continue
            meta = json.loads((d / n).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        out['holding' if kind == 'has' else 'asking'].append(dict(meta, pid=int(pid)))
    return out


RUNNING_CALLS = {}  # tool calls this server is working on now: key -> (tool name, started at)


def call_started(name):
    key = object()
    RUNNING_CALLS[key] = (name, time.time())
    return key


def call_ended(key):
    RUNNING_CALLS.pop(key, None)


def running_calls_text(now=None):
    """The tool calls still working in this server, other than the status call asking (none: an empty string)."""
    now = time.time() if now is None else now
    calls = [(name, now - started) for name, started in list(RUNNING_CALLS.values()) if name != 'letitedit_status']
    if not calls:
        return ''
    return 'Tool calls still running here, no result yet: ' + ', '.join(
        f'{name} ({int(seconds // 60)} min {int(seconds % 60)} s)' for name, seconds in calls)


def status_report(limit=10, root=None, model_sizes=True):
    """Everything letitedit_status reports, as a dict."""
    js = J.list_jobs(200, root=root)
    running = [j for j in js if j['state'] == 'running']
    queued = [j for j in js if j['state'] in ('queued', 'interrupted')]
    recent = [j for j in js if j['state'] in J.FINAL][:limit]
    try:
        import letitedit.timeline.render_queue as render_queue
        exports = render_queue.list_jobs(limit)
    except Exception as e:  # noqa: BLE001
        exports = [{'error': f'render_queue: {e}'}]
    active_exports = [e for e in exports if e.get('state') in ('rendering', 'waiting', 'joining', 'audio', 'checking',
                                                               'queued')]
    return {'worker': J.worker_info(root), 'running': running, 'queued': queued, 'recent': recent,
            'exports_active': active_exports, 'exports_recent': [e for e in exports if e not in active_exports][:limit],
            'render_lock': render_lock.info(), 'gpu_lock': _gpu_lock(), 'gpu_sharing': _gpu_sharing(), 'gpu': _gpu(),
            'disk': _disk(),
            'work_files': _work_files(),
            'models': models() if model_sizes else None, 'jobs_folder': str(J._root(root))}


def _job_line(j):
    pct = f"{round(100 * (j.get('progress') or 0))}%"
    return (f"{j['job_id']}  {j.get('kind')}  {j.get('state')}  {pct}  {j.get('label') or ''}  "
            f"{(j.get('message') or '')[:160]}").rstrip()


def _export_line(e):
    if 'error' in e and 'job_id' not in e:
        return e['error']
    return (f"{e['job_id']}  export  {e.get('state')}  {round(100 * (e.get('progress') or 0))}%  "
            f"{Path(e.get('output') or '').name}  {(e.get('message') or '')[:160]}").rstrip()


def status_text(rep):
    w = rep['worker']
    lines = [f"Job worker: {'running, pid ' + str(w.get('pid')) if w.get('running') else 'not running'}"
             f"{' (on ' + w['current'] + ')' if w.get('current') else ''}; jobs folder {rep['jobs_folder']}"]
    lines.append(f"Running jobs: {len(rep['running'])}")
    lines += ['  ' + _job_line(j) for j in rep['running']]
    lines.append(f"Queued / to resume: {len(rep['queued'])}")
    lines += ['  ' + _job_line(j) for j in rep['queued']]
    if rep['recent']:
        lines.append('Recent jobs:')
        lines += ['  ' + _job_line(j) for j in rep['recent']]
    lines.append(f"Exports active: {len(rep['exports_active'])}")
    lines += ['  ' + _export_line(e) for e in rep['exports_active']]
    if rep['exports_recent']:
        lines.append('Recent exports:')
        lines += ['  ' + _export_line(e) for e in rep['exports_recent']]
    lines.append('Render lock: ' + rep['render_lock']['message'])
    for k, w in enumerate(rep['render_lock'].get('queue') or []):      # first come, first served
        lines.append(f"  {k + 1}. waiting: {w['name'][:100]} (pid {w['pid']}, since {w['since'][11:]}, "
                     f"{w['waited_s'] / 60:.0f} min)")
    g = rep['gpu_lock']
    lines.append(f"Model GPU lock ({g['path']}): {'held' if g.get('held') else 'free' if g.get('held') is False else 'unknown'}")
    sh = rep.get('gpu_sharing') or {}
    for h in sh.get('holding', []):
        held = ', '.join(f'{k} ~{v} MB' for k, v in (h.get('models') or {}).items())
        lines.append(f"  models on the GPU: pid {h['pid']}: {held}" + (f" (busy: {', '.join(h['busy'])})"
                                                                      if h.get('busy') else ' (idle)'))
    for a in sh.get('asking', []):
        lines.append(f"  waiting for GPU memory: pid {a['pid']}: {a.get('need_mb')} MB for {a.get('what')} "
                     f"(since {str(a.get('since'))[11:]})")
    for gpu in rep['gpu']:
        lines.append('GPU: ' + (gpu['error'] if 'error' in gpu else
                                f"{gpu['name']}, {gpu['used_mb']} of {gpu['total_mb']} MB used, {gpu['free_mb']} MB "
                                f"free, {gpu['util_pct']}% busy"))
    d = rep['disk']
    lines.append(f"Disk {d['drive']}: " + (d['error'] if 'error' in d else f"{d['free_gb']} GB free of {d['total_gb']} GB"))
    work = rep.get('work_files')
    if work:
        lines.append(f"Work files letitedit can draw again: {work['held'] / 1024 ** 3:.1f} GB, "
                     f"kept under {work['budget'] / 1024 ** 3:.1f} GB")
    if rep['models'] is not None:
        lines.append(f"Local models in {MODELS}: " + (', '.join(f"{m['model']} ({m['mb']} MB)" for m in rep['models'])
                                                      or 'none'))
    return '\n'.join(lines)


def jobs(action='list', job_id=None, paths=None, steps=None, context=None, shot_log=None, timeout_s=None,
         limit=20, log_chars=2000, root=None):
    """action: list | status | submit_index | cancel | resume. Returns a dict."""
    a = (action or 'list').lower().replace('-', '_')
    export = job_id is not None and (Path(J._root(root)) / job_id).exists() is False
    if a == 'list':
        return J.list_all(limit, root=root)
    if a in ('submit', 'submit_index', 'index'):
        if not paths:
            raise ValueError('submit_index needs paths (a folder, a file or a list)')
        return J.submit_index(paths, steps=steps, context=context, shot_log=shot_log, timeout_s=timeout_s, root=root)
    if not job_id:
        raise ValueError(f'{a} needs job_id')
    if export:      # an export job of render_queue
        import letitedit.timeline.render_queue as render_queue
        if a == 'status':
            return render_queue.status(job_id)
        if a == 'cancel':
            return render_queue.cancel(job_id)
        if a == 'resume':
            return render_queue.resume(job_id)
        raise ValueError(f'unknown action {action!r}')
    if a == 'status':
        out = J.status(job_id, root=root)
        if log_chars:
            out['log_tail'] = J.log_tail(job_id, log_chars, root=root)
        return out
    if a == 'cancel':
        return J.cancel(job_id, root=root)
    if a == 'resume':
        return J.resume(job_id, root=root)
    raise ValueError(f'unknown action {action!r}; one of list, status, submit_index, cancel, resume')


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_status(limit: int = 10, models: bool = True) -> str:
        """What the PC is doing for letitedit, in one reply: the background job worker (running or not, its pid,
        the job it is on); running jobs and queued or interrupted jobs (id, kind, state, progress, message); the
        `limit` most recent finished jobs and export jobs (default 10); active export jobs; the PC render lock
        (Videos\\render.lock: who holds it, since when, whether the owner process is alive, whether it is stale);
        whether the model GPU lock is held; GPU memory used/free and load (nvidia-smi); free space on C:; the local
        models under C:\\LetItEdit\\models with sizes (models=False leaves them out).
        A render of your own (ffmpeg, melt, a script) takes the PC render lock with
        `python C:\\LetItEdit\\bridge\\render_lock.py run --name <name> -- <command ...>`, which waits its turn
        (a line on stderr per check, --timeout-s default 43200, --poll-s default 15), runs the command and releases
        the lock when it ends; `render_lock.py status` prints the holder. A lock whose owner pid is not running
        counts as stale and is cleared; one without a pid counts as stale 3 h after it was written."""
        rep = status_report(limit=limit, model_sizes=models)
        running = running_calls_text()
        return (running + '\n' if running else '') + status_text(rep)

    @mcp.tool(structured_output=False)
    def letitedit_jobs(action: str = 'list', job_id: str | None = None, paths: str | list[str] | None = None,
                     steps: list[str] | None = None, context: str | None = None, shot_log: dict | None = None,
                     timeout_s: float | None = None, limit: int = 20) -> str:
        """Background jobs that keep running after this call, this session or a PC restart (one at a time, each
        in its own process; an interrupted job continues from its checkpoint, up to 3 runs, then counts as failed).
        Jobs live in C:\\LetItEdit\\jobs\\<job_id>\\ (spec.json, status.json, checkpoint.json, log.txt).
        action:
          list          these jobs and the export jobs (newest first, `limit` of each, default 20).
          status        one job (job_id): state (queued, running, done, failed, cancelled, interrupted), progress
                        0-1, message, attempts, outputs, error, the end of its log. An export job id gives the
                        export's status.
          submit_index  queue an 'index' job for `paths` (a folder, a file, or a list; folders are not searched
                        below). steps: any of 'footage' (probe, sound and picture analysis, voice detection, as
                        letitedit_footage analyze=True), 'words' (transcripts of files with more than 0.5 s of
                        detected talking), 'shot_log' (the footage log by the local vision model; waits for the model
                        GPU lock up to 2 h per call; skipped when the footage log engine is 'llm'), 'archive' (adds
                        what the other steps cached to the archive database, letitedit_archive); default all four, in
                        that order. context: text given to the
                        footage log model with every stretch. shot_log: settings for the footage log (max_s,
                        frames, width, merge_below, merge_max_s, cut_above, words, max_new_tokens, batch).
                        timeout_s: the job's time limit (default 43200). Everything it makes goes to the same caches
                        letitedit_footage, letitedit_words and the footage log read, so those answer at once afterwards.
                        outputs: counts, the files with talking, per-file errors, footage.txt (the scan's text).
          cancel        stop a job (job_id): queued ones at once, a running one at its next check or after 20 s.
          resume        queue an interrupted, failed or cancelled job again from its checkpoint (an export job id
                        resumes the export).
        The worker starts by itself when a job is submitted or resumed and stops after 300 s with nothing to do."""
        out = jobs(action, job_id=job_id, paths=paths, steps=steps, context=context, shot_log=shot_log,
                   timeout_s=timeout_s, limit=limit)
        if (action or 'list') == 'list':
            lines = ['Jobs:'] + (['  ' + _job_line(j) for j in out['jobs']] or ['  none'])
            lines += ['Exports:'] + (['  ' + _export_line(e) for e in out['exports']] or ['  none'])
            return '\n'.join(lines)
        return json.dumps(out, indent=1, default=str)
