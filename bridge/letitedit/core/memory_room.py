"""Memory the PC can promise, and letitedit's idle model helpers giving it back before a heavy render.

Windows refuses memory past its commit limit (RAM plus the page file, less what every program has been promised),
however much RAM is free. The export engine and x264 crash when refused (exit 0xC0000005, "malloc ... failed",
"[mlt_pool] out of memory"), and when the PC runs out altogether other programs crash with them. A model helper (a
worker process holding a model, kept alive between calls so the model loads once, and ending by itself after about
10 idle minutes) can sit on several GB of that commit while idle: the vision helper of a review holds 8-9.5 GB.

So a heavy render, once it holds the PC render lock (no model job starts while it does), makes room first:
  make_room(need_gb, what, wait_s)   when less than need_gb is free to promise: this process's idle helpers end, then
                                     other letitedit processes are asked to end theirs; it waits while the memory is
                                     short and someone still has idle helpers, up to ROOM_WAIT_S. Returns a report.
A process that keeps helpers registers them:
  register(name, alive, end_idle)    alive() -> {helper: {'pid': int, 'busy': bool}}; end_idle() -> [helpers ended].
                                     A busy helper is never ended; an ended one starts again on its next use.
  changed()                          after a helper started or ended: keeps ram.has.<pid> current, and the responder
                                     thread running while this process has helpers
  end_idle()                         this process's idle helpers end now
memory_gb()                          (physical memory free, commit free) in GB; (None, None) where it can't be read.
                                     Commit free counts the page file's room to grow to its fixed cap (page_file_growth_gb)
RENDER_GB, RESERVE_GB                about what one engine render commits, and what to leave for everything else
ENGINE_ENV, PICTURE_ENGINE_ENV       the settings that lower what an engine render commits without changing what it
                                     makes: ENGINE_ENV for any render, PICTURE_ENGINE_ENV for one that makes no sound

The processes cooperate through small files beside the GPU lock (LETITEDIT_GPU_LOCK, default
<install>\\cache\\models\\gpu.lock), as the GPU sharing does:
  ram.has.<pid>    {'pid', 'helpers', 'updated'} while that process has helpers, refreshed every RESPOND_S
  ram.want.<pid>   {'pid', 'need_gb', 'free_gb', 'what', 'since'} while a render waits for room
Files not refreshed for FRESH_S are ignored. A process removes its own when it no longer needs them and when it ends;
the file of a process that ended without doing so (it crashed or was stopped) is removed by the next one to read it.
"""
from __future__ import annotations

import atexit
import contextlib
import json
import os
import shutil
import threading
import time
from pathlib import Path

# One engine render (a chunk of an export, a check's pipe) commits 3.4-4.2 GB, measured on two projects, most of it the
# clips' decoders, so it hardly depends on the picture size; a heavy stretch of one reached 5.7-6.4 GB.
RENDER_GB = 4.5
RESERVE_GB = 1.5
# T239, T239b: an engine render commits 2 GB it never touches: OpenBLAS, which OpenCV's engine plugin loads, keeps a
# 128 MB buffer per OpenMP thread (16 on a 16-thread PC); each engine render is one or two threads of its own anyway.
# With OpenMP at one thread every frame's bytes and every sound sample came out the same at the same speed, measured on
# exports of two projects (upright and landscape, 60 fps, full size and preview; tests/t239/REPORT.md): each chunk's
# render 1.9 GB less, the sound's 1.9 GB less.
ENGINE_ENV = {'OMP_NUM_THREADS': '1'}
# A render that makes no sound (a picture chunk, a check's frames) also turns the clips' picture cache off (each clip it
# has opened kept 4 decoded pictures): the same frames at the same speed, 0.3-0.7 GB less per chunk. A render that makes
# sound keeps the cache: with it off, 13 short stretches of a project's sound (a quarter or half second at its cuts)
# came out different.
PICTURE_ENGINE_ENV = {**ENGINE_ENV, 'MLT_AVFORMAT_CACHE': '0'}
ROOM_WAIT_S = float(os.environ.get('LETITEDIT_ROOM_WAIT_S', '60'))   # the longest a render waits for helpers to end
RESPOND_S = 1.0           # how often a process with helpers looks for requests
FRESH_S = 30.0            # a has/want file not refreshed this long is ignored (its process hung or died)
POLL_S = 0.5
QUIET_ROUNDS = 4          # rounds with nobody holding an idle helper before a short render stops waiting
# T270: the page file's room to grow counts as free to promise only while its drive keeps letitedit's free room
# (cache_budget.reserve_bytes: a few GB by default; the setting disk_keep_free_gb on a PC that keeps more).

_state = {'lock': threading.Lock(), 'registered': {}, 'thread': None, 'written': None}


@atexit.register
def _tidy():
    """This process's own files go when it ends."""
    with contextlib.suppress(Exception):
        _remove('has')
        _remove('want')


def page_file_growth_gb():
    """How much more the page file can grow now, in GB: each page file with a fixed cap (Windows' PagingFiles setting,
    "path initial maximum" in MB) has room up to its maximum less its size now, and on a drive never more than the
    drive's free space less letitedit's free room, so the file can really grow and the drive keeps its room. Windows
    grows the file toward the cap only when commit runs short, so this is memory it will promise but is not counted in
    the commit limit yet. 0.0 for a system-managed page file, none, a non-Windows PC or anything that can't be read."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management') as key:
            entries = winreg.QueryValueEx(key, 'PagingFiles')[0]
        if isinstance(entries, str):
            entries = [entries]
        room = {}       # drive -> GB the files on it can grow
        for entry in entries or []:
            parts = str(entry).rsplit(None, 2)
            if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit() or '?' in parts[0]:
                continue                                  # system-managed ("?:\pagefile.sys"): no fixed cap
            path, maximum = parts[0], int(parts[2]) / 1024
            drive = os.path.splitdrive(path)[0].upper()
            if not drive or maximum <= 0:
                continue                                  # a zero maximum is system-managed too
            with contextlib.suppress(OSError):
                room[drive] = room.get(drive, 0.0) + max(0.0, maximum - os.path.getsize(path) / 2 ** 30)
        import letitedit.core.cache_budget as cache_budget
        margin = cache_budget.reserve_bytes() / 2 ** 30
        total = 0.0
        for drive, grow in room.items():
            free = shutil.disk_usage(drive + '\\').free / 2 ** 30
            total += max(0.0, min(grow, free - margin))
        return total
    except Exception:  # noqa: BLE001 - not Windows, no setting, unreadable: today's answer
        return 0.0


def memory_gb():
    """(physical memory free, commit free) now, in GB (Windows); (None, None) where it can't be read. Commit free is
    what Windows will still promise programs: RAM plus the page file, less what every program already holds, plus the
    part the page file can still grow (page_file_growth_gb)."""
    available, commit = _memory_now()
    if commit is not None:
        commit += page_file_growth_gb()
    return available, commit


def _memory_now():
    """(physical memory free, commit free) as Windows reports them, the page file at its size right now."""
    try:
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong),
                        ('avail', ctypes.c_ulonglong), ('total_page', ctypes.c_ulonglong), ('avail_page', ctypes.c_ulonglong),
                        ('total_virtual', ctypes.c_ulonglong), ('avail_virtual', ctypes.c_ulonglong),
                        ('avail_extended', ctypes.c_ulonglong)]
        status = Status()
        status.length = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None, None
        return status.avail / 2 ** 30, status.avail_page / 2 ** 30
    except Exception:  # noqa: BLE001 - not Windows, or no kernel32: nothing to manage
        return None, None


def folder():
    """Where the has/want files live: LETITEDIT_MEMORY_ROOM_DIR (each test process has its own, so a test never asks a
    real tool server), else beside the GPU lock, where model_tools' sharing files are."""
    if os.environ.get('LETITEDIT_MEMORY_ROOM_DIR'):
        return Path(os.environ['LETITEDIT_MEMORY_ROOM_DIR'])
    from letitedit.core import paths
    lock = os.environ.get('LETITEDIT_GPU_LOCK') or str(Path(paths.install_root()) / 'cache' / 'models' / 'gpu.lock')
    return Path(lock).parent


def _file(kind, pid=None):
    return folder() / f'ram.{kind}.{int(pid or os.getpid())}'


def _write(kind, data):
    target = _file(kind)
    temporary = target.with_name(f'{target.name}.{threading.get_ident()}.tmp')
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(data), encoding='utf-8')
        os.replace(temporary, target)
        return True
    except OSError:
        with contextlib.suppress(OSError):
            temporary.unlink()
        return False


def _touch(kind):
    with contextlib.suppress(OSError):
        os.utime(_file(kind))


def _remove(kind):
    with contextlib.suppress(OSError):
        _file(kind).unlink()


def _log(message):
    with contextlib.suppress(Exception):
        log = folder().parent / 'logs' / 'memory_room.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        if log.exists() and log.stat().st_size > 2_000_000:
            log.unlink()
        with open(log, 'a', encoding='utf-8') as handle:
            handle.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} pid {os.getpid()}: {message}\n')


def _peers(kind):
    """Other running processes' fresh ram.<kind>.<pid> files: [{'pid', 'age_s', ...what they wrote}]."""
    import letitedit.core.render_lock as render_lock
    where = folder()
    try:
        names = os.listdir(where)
    except OSError:
        return []
    prefix, me, now, out = f'ram.{kind}.', os.getpid(), time.time(), []
    for name in names:
        if not name.startswith(prefix) or not name[len(prefix):].isdigit() or int(name[len(prefix):]) == me:
            continue
        pid = int(name[len(prefix):])
        try:
            if not render_lock.pid_alive(pid):
                (where / name).unlink()          # its process ended without removing it
                continue
            age = now - os.stat(where / name).st_mtime
            if age > FRESH_S:
                continue
            meta = json.loads((where / name).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        out.append({**(meta if isinstance(meta, dict) else {}), 'pid': pid, 'age_s': round(age, 1)})
    return out


def _idle(peer):
    return any(not (meta or {}).get('busy') for meta in (peer.get('helpers') or {}).values())


def register(name, alive, end_idle_fn):
    """A module of this process keeps helpers: alive() -> {helper: {'pid', 'busy'}}, end_idle_fn() -> [ended]."""
    with _state['lock']:
        _state['registered'][name] = (alive, end_idle_fn)
    changed()


def _helpers():
    out = {}
    for name, (alive, _) in list(_state['registered'].items()):
        try:
            found = alive() or {}
        except Exception as error:  # noqa: BLE001 - one module's fault never hides the others'
            _log(f'{name}: alive() failed: {type(error).__name__}: {error}')
            found = {}
        for helper, meta in found.items():
            out[f'{name}: {helper}'] = meta
    return out


def end_idle():
    """This process's idle helpers end now (each registered module ends its own). Returns the names ended."""
    ended = []
    for name, (_, end) in list(_state['registered'].items()):
        try:
            ended += [f'{name}: {helper}' for helper in (end() or [])]
        except Exception as error:  # noqa: BLE001
            _log(f'{name}: end_idle() failed: {type(error).__name__}: {error}')
    if ended:
        changed()
    return ended


def changed():
    """After a helper started or ended here: ram.has.<pid> says which (removed when none), and the responder thread
    runs while there are some."""
    helpers = _helpers()
    with _state['lock']:
        if not helpers:
            _remove('has')
            _state['written'] = None
            return
        data = {'pid': os.getpid(), 'helpers': helpers}
        if data != _state['written']:
            if _write('has', dict(data, updated=time.strftime('%Y-%m-%d %H:%M:%S'))):
                _state['written'] = data
        else:
            _touch('has')
        thread = _state['thread']
        if thread is None or not thread.is_alive():
            thread = threading.Thread(target=_responder, name='letitedit-memory-room', daemon=True)
            _state['thread'] = thread
            thread.start()


def _responder():
    """While this process has helpers: keep ram.has.<pid> fresh and end the idle ones when a render asks for room."""
    while True:
        time.sleep(RESPOND_S)
        try:
            wants = _peers('want')
            if wants:
                ended = end_idle()
                if ended:
                    _log(f'ended {", ".join(ended)} for ' + ', '.join(
                        f"pid {w['pid']} ({w.get('what')}, {w.get('need_gb')} GB)" for w in wants))
            with _state['lock']:
                if not _helpers():
                    _remove('has')
                    _state['written'] = None
                    _state['thread'] = None
                    return
            changed()
        except Exception as error:  # noqa: BLE001 - one bad round never ends the thread
            _log(f'responder: {type(error).__name__}: {error}')


def _round(value):
    return None if value is None else round(value, 1)


def _growth_words(growth):
    """A note's words for the page file's room to grow ('' when there is none)."""
    return f' (including {growth:.1f} GB the page file can still grow)' if growth and growth >= 0.05 else ''


def make_room(need_gb, what, wait_s=None):
    """Before a heavy render, holding the PC render lock: when less than need_gb GB is free to promise, end this
    process's idle model helpers, then ask other letitedit processes to end theirs and wait (at most wait_s, default
    ROOM_WAIT_S) while the memory is short and one of them still has an idle helper. Never raises. Returns
    {'needed_gb', 'free_gb_at_start', 'free_gb', 'free_commit_gb_at_start', 'page_file_can_grow_gb'} (free_gb counts the
    page file's room to grow; the last two split the start's number) plus, when it had to make room, 'ended_here', 'asked', 'waited_s',
    'short_gb' (still short) and a plain 'note'."""
    wait_s = ROOM_WAIT_S if wait_s is None else wait_s
    t0 = time.monotonic()
    commit = memory_gb()[1]
    growth = page_file_growth_gb() if commit is not None else 0.0
    # free_gb is what is compared with the need: free commit now plus the part the page file can still grow
    report = {'needed_gb': round(need_gb, 1), 'free_gb_at_start': _round(commit), 'free_gb': _round(commit),
              'free_commit_gb_at_start': _round(None if commit is None else commit - growth),
              'page_file_can_grow_gb': _round(growth)}
    if commit is None or commit >= need_gb:
        return report
    try:
        ended = end_idle()
        commit = memory_gb()[1]
        asked = {p['pid']: p.get('helpers') for p in _peers('has') if _idle(p)}
        if commit is not None and commit < need_gb and asked:
            _write('want', {'pid': os.getpid(), 'need_gb': round(need_gb, 1), 'free_gb': _round(commit),
                            'what': what, 'since': time.strftime('%Y-%m-%d %H:%M:%S')})
            try:
                quiet = 0
                while time.monotonic() - t0 < wait_s:
                    time.sleep(POLL_S)
                    _touch('want')
                    commit = memory_gb()[1]
                    if commit is None or commit >= need_gb:
                        break
                    holders = _peers('has')
                    quiet = 0 if any(_idle(p) for p in holders) else quiet + 1
                    if quiet >= QUIET_ROUNDS:   # nobody has an idle helper any more: what is left is not theirs to give
                        break
            finally:
                _remove('want')
        report.update(free_gb=_round(commit), waited_s=round(time.monotonic() - t0, 1), ended_here=ended,
                      asked=[{'pid': pid, 'helpers': sorted(helpers or {})} for pid, helpers in asked.items()])
        gave = ', '.join(ended + [f'pid {pid}' for pid in asked]) or 'none were idle'
        if commit is not None and commit < need_gb:
            report['short_gb'] = round(need_gb - commit, 1)
            report['note'] = (f'{what} needs about {need_gb:.1f} GB free to promise and {commit:.1f} GB is'
                              f'{_growth_words(growth)}, after asking letitedit\'s idle model helpers to end ({gave}): '
                              f'other programs hold the rest')
        else:
            report['note'] = (f'letitedit\'s idle model helpers ended so {what} has memory ({gave}); '
                              f'{report["free_gb_at_start"]} GB was free, now {report["free_gb"]} GB'
                              f'{_growth_words(growth)}')
        _log(report['note'])
    except Exception as error:  # noqa: BLE001 - making room is a courtesy: the render goes ahead either way
        _log(f'make_room for {what}: {type(error).__name__}: {error}')
        report['error'] = f'{type(error).__name__}: {error}'
    return report
