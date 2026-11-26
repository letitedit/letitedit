"""The PC-wide one-render-at-a-time lock (Videos\\render.lock by default, LETITEDIT_RENDER_LOCK overrides).

The lock is a small text file. Whoever renders creates it (atomically) with an owner line
    '<name> pid <N> <YYYY-mm-dd HH:MM:SS>'
and deletes it when the render ends. letitedit exports (render_queue) and any other render (an agent's own ffmpeg or
melt command, a builder script) share it, so only one heavy render runs on the PC at a time.

Rules used when a lock file already exists
  * its owner pid is not running                      -> stale: removed, the slot is taken
  * its owner pid is running                          -> never stale, however old: a live owner may still be rendering
                                                         (and every render it started dies with it, below)
  * it names no pid (written by hand), older than 3 h  -> stale (younger: waited on, as before)
  * a lock left by the same export job (job_id)       -> stale only when its owner is gone, or is this very process
                                                         (the job's own leftover); a job id never outweighs a live
                                                         owner
  * it names a pid among `caller_pids` that is alive  -> the caller holds it: the caller's child renders under it
                                                         at once, never queued behind the others

First come, first served
  A waiter that cannot take the lock leaves a ticket in the queue folder next to it
  (render.lock.queue\\<time ns>-<pid>-<random>.ticket, holding its name) and only the oldest live ticket may take the
  lock (or clear a stale one): a free lock is never taken while someone who came earlier waits for it. The first in
  line checks every FIRST_POLL_S (1 s), so a released lock is taken within about a second; the others check their
  place every QUEUE_POLL_S (2 s); on_wait is still called about every poll_s seconds (and when the place in line
  changes). A ticket is removed when its waiter takes the lock, times out, is cancelled or fails in any way. A ticket
  whose pid is not running (or names a process started after the ticket was written: a reused pid) is dead and
  removed; one not touched for ANY_STALE_S too; one not touched for TICKET_IDLE_S (its waiter hung or the PC slept) is
  skipped until its waiter touches it again. Locks written by hand and processes still running older code don't queue.

Classes (Studio jobs, T258)
  Each ticket names its waiter's class: 'person' (the person's own work, and every caller that names none), 'urgent'
  and 'normal' (Studio jobs' lanes; 'channel_urgent' and 'channel' are the same) and 'dev' (test runs). The class comes
  from acquire(priority=...), else the LETITEDIT_LOCK_PRIORITY environment variable (children inherit it), else
  'person', so a caller that says nothing keeps today's standing. The line is ordered by class, then arrival; a waiter
  moves up one class for every AGE_S waited, never into 'person'. Person-first is the policy: while the person's own
  work keeps the lock busy, every other class waits, however long (ageing only orders Studio jobs and test runs among
  themselves, so a test run can't be starved by Studio jobs, but it can be by the person). While any live
  ticket names no class (a process running older code), the whole line is in plain arrival order, so every waiter sees
  one order. A held lock is never taken away; a Yielder gives way between pieces as before.

Fails closed
  The check-and-take runs under a short operating-system mutex (the .guard file next to the lock). A waiter that can't
  get that mutex never goes ahead without it: acquire keeps waiting (up to its own timeout_s), try_acquire reports the
  lock as not taken.

A render lives only as long as its owner
  While any thread of a process holds the lock, every program that process starts (a pool's threads included) is
  created suspended, put in the process's Windows job objects, and only then let run; the job objects end everything in
  them when the process ends, however it ends. A dead owner therefore means no render, and the lock it leaves can be
  cleared without two heavy jobs ever running at once. A program that can't be put in them is ended before it ran a
  single instruction, and the call fails. Left as they were: programs started on purpose to outlive the process
  (DETACHED_PROCESS or CREATE_BREAKAWAY_FROM_JOB: the editor, the export and job workers, the background syncs); a
  render started detached is tied explicitly (`with tied():`, popen_tied, run_bound). A render child can never leave
  its job, not even when it asks to. `render_lock.py run` puts itself in the job before it takes its command, so the
  command and everything it starts end with it, and the command may still start the independent workers.

Python
    with render_lock.slot('my ffmpeg render', timeout_s=3600):
        ...render...
    holder = render_lock.acquire('name');  ...;  render_lock.release(holder)
    render_lock.info()       # who holds it, since when, is the owner alive, is it stale, who waits for it (queue)

CLI
    python render_lock.py run --name <name> [--timeout-s S] [--poll-s S] -- <command ...>
        waits for the slot in turn (a line on stderr each poll saying what it waits on and how many wait ahead), runs
        the command while holding the lock (owner pid = this CLI process), releases it however the command ends;
        exits with the command's code (3 when the wait timed out).
    python render_lock.py status          JSON: path, held, text, owner pid, owner alive, age, stale, waiting, queue
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import contextlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

LOCK = Path(os.environ.get('LETITEDIT_RENDER_LOCK', str(Path.home() / 'Videos' / 'render.lock')))
# Set by an export job that renders under the lock its caller holds: the caller's process ids, so the job's own nested
# renders (code scenes, motion, cut-outs) count as the caller's too. The launcher between the two has exited, so the
# process chain alone no longer reaches the caller (5 Nov: a scene drawn inside such an export waited behind the lock
# its own caller held, while the caller waited for the export).
CALLERS_ENV = 'LETITEDIT_LOCK_CALLERS'
NO_PID_STALE_S = 3 * 3600      # a hand-written lock without a pid counts as stale after this
ANY_STALE_S = 12 * 3600        # a waiter's ticket untouched this long is dead (a held lock with a live owner never is)
GUARD_TIMEOUT_S = 30.0         # one check-and-take waits this long for the guard, then the attempt fails closed
# Windows refuses to delete a file another program has open (a waiter or `status` reading it): a release retries for
# this long under the guard, then a background thread of the holder's process keeps trying (T293).
RELEASE_RETRY_S = 2.0
ORPHAN_RETRY_MAX_S = 1.0       # the background retries back off to this interval
DEFAULT_TIMEOUT_S = 12 * 3600  # how long acquire() waits by default
DEFAULT_POLL_S = 15.0
FIRST_POLL_S = 1.0             # the first in line checks the lock this often (at most poll_s)
QUEUE_POLL_S = 2.0             # the others check their place in line this often (at most poll_s)
TICKET_IDLE_S = 120.0          # a ticket untouched this long is skipped (its waiter touches it at every check)
PID_RX = re.compile(r'pid[\s:=#]*(\d+)', re.I)                 # a lock written by another tool or by hand
# The owner record letitedit appends at the very end: ' pid N[ start T] YYYY-mm-dd HH:MM:SS'. Read from the end only, so
# a label (a file name like rapid4242.mp4, any text) can never be taken for the owner.
OWNER_RX = re.compile(r'^.*\bpid (\d+)(?: start (\d+))? \d{4}-\d\d-\d\d \d\d:\d\d:\d\d\s*$', re.S)
LABEL_PID_RX = re.compile(r'p[\s_.\-]*i[\s_.\-]*d(?=[\s:=#_.\-]*\d)', re.I)  # what in a label reads like an owner
TICKET_RX = re.compile(r'^(\d{20})-(\d+)-([0-9a-f]+)\.ticket$')
PRIORITY_ENV = 'LETITEDIT_LOCK_PRIORITY'
CLASSES = {'person': 0, 'urgent': 1, 'normal': 2, 'dev': 3}
CLASS_ALIASES = {'channel_urgent': 'urgent', 'channel': 'normal', 'interactive': 'person'}
AGE_S = float(os.environ.get('LETITEDIT_LOCK_AGE_S', '1800'))   # a waiter moves up one class per this many seconds


class LockTimeout(TimeoutError):
    """The wait for the render lock reached its time limit; str() says who held it."""


class GuardBusy(RuntimeError):
    """The lock's check-and-take mutex was not free in time: nothing was checked or taken (fails closed)."""


class Cancelled(RuntimeError):
    pass


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _path(path=None):
    return Path(path) if path else LOCK


ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87     # OpenProcess's answer for a pid no process has


def _open(pid, access):
    """(handle, 0) or (0, the Windows error): OpenProcess, one place, so a test can stand in for the OS's answer."""
    import ctypes
    k = _k32()
    h = k.OpenProcess(access, False, int(pid))
    return (h, 0) if h else (0, ctypes.get_last_error())


def pid_state(pid):
    """'alive', 'gone' or 'unknown'. 'gone' only when Windows says no process has that pid, or it has exited.
    'unknown': a process has the pid but can't be read (another user's, a protected program, an error): it may be
    running, so it is never treated as gone (no lock is cleared, no job started again on it)."""
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError):
        return 'gone'
    if pid <= 0 or pid > 0xFFFFFFFF:
        return 'gone'
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return 'alive'
        except ProcessLookupError:
            return 'gone'
        except OSError:
            return 'unknown'
    import ctypes
    from ctypes import wintypes
    try:
        h, err = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    except (OSError, ValueError, OverflowError):
        return 'unknown'
    if not h:
        return 'gone' if err == ERROR_INVALID_PARAMETER else 'unknown'
    k = _k32()
    try:
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(h, ctypes.byref(code)):
            return 'unknown'
        return 'alive' if code.value == STILL_ACTIVE else 'gone'
    finally:
        k.CloseHandle(h)


def pid_alive(pid):
    """True unless the process is known to be gone: one that can't be read counts as running (pid_state)."""
    return pid_state(pid) != 'gone'


def pid_started(pid):
    """When process `pid` started (seconds since the epoch), or None when that can't be read (not Windows, gone)."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, int(pid))
    except (AttributeError, OSError, ValueError, OverflowError):
        return None
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return None
        ft = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return ft / 1e7 - 11644473600.0
    finally:
        k32.CloseHandle(handle)


def ancestors(pid=None):
    """This process (or `pid`) and the processes above it, nearest first (Windows process snapshot)."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                    ('th32DefaultHeapID', ctypes.c_void_p), ('th32ModuleID', wintypes.DWORD),
                    ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                    ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_char * 260)]
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    parent = {}
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k32.Process32First(snap, ctypes.byref(e))
        while ok:
            parent[e.th32ProcessID] = e.th32ParentProcessID
            ok = k32.Process32Next(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    chain, cur = [], int(pid or os.getpid())
    while cur and cur not in chain and len(chain) < 32:
        chain.append(cur)
        cur = parent.get(cur)
    if pid is None:  # this process: also the callers an export job renders for (CALLERS_ENV), after its own chain
        for p in os.environ.get(CALLERS_ENV, '').split(','):
            if p.strip().isdigit() and int(p) not in chain:
                chain.append(int(p))
    return chain


def owner_identity(text):
    """(pid, creation time or None, from letitedit's own record) of the lock's owner, read in one step, or (None, None,
    False). letitedit's lock ends with its owner record (' pid N[ start T] <time>'), read from the end only: the label
    before it never counts. A lock without that record (written by another tool or by hand: 'pid N', 'pid: N',
    'pid=N') gives its first pid and no creation time, so it is never called reused (as conservative as before)."""
    m = OWNER_RX.match(text or '')
    if m:
        return int(m.group(1)), (int(m.group(2)) if m.group(2) else None), True
    m = PID_RX.search(text or '')
    return (int(m.group(1)) if m else None), None, False


def owner_pid(text):
    return owner_identity(text)[0]


def owner_started(text):
    """The owner's creation time letitedit's record holds (Windows FILETIME ticks), or None."""
    return owner_identity(text)[1]


def lock_held_by(text, pids):
    """True when the lock's owner is one of `pids`. letitedit's own lock: only its owner record counts. A lock written
    by another tool: any 'pid N', 'pid: N' or 'pid=N' in it, as scripts and tools write it."""
    want = {int(p) for p in pids or ()}
    pid, _started, ours = owner_identity(text)
    if ours:
        return pid in want
    return any(int(n) in want for n in PID_RX.findall(text or ''))


def label(name):
    """A lock label that can't pass for an owner record: on one line, and 'pid' before a number (any case or spacing,
    rapid4242.mp4 included) written as 'p-i-d'. The editor finds its own process's lock by ' pid N ', which then only
    the owner record can hold."""
    return LABEL_PID_RX.sub('p-i-d', ' '.join(str(name).split()))


def start_ticks(pid):
    """('alive', creation time in FILETIME ticks), ('gone', None) or ('unknown', None), read with limited query rights
    only. 'unknown' (refused, or any failure) proves nothing either way."""
    seen = pid_state(pid)
    if seen != 'alive' or os.name != 'nt':
        return seen, None
    import ctypes
    from ctypes import wintypes
    try:
        h, _err = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    except (OSError, ValueError, OverflowError):
        return 'unknown', None
    if not h:
        return ('gone', None) if pid_state(pid) == 'gone' else ('unknown', None)
    k = _k32()
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        code = wintypes.DWORD()
        if not k.GetProcessTimes(h, *[ctypes.byref(t) for t in times]) or not k.GetExitCodeProcess(h, ctypes.byref(code)):
            return 'unknown', None
        if code.value != STILL_ACTIVE:
            return 'gone', None
        return 'alive', (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        k.CloseHandle(h)


def owner_state(text):
    """The lock owner's state: 'alive', 'gone', 'unknown' (it can't be read: it may be running), 'reused' (its pid now
    belongs to a process created at another time than the one the lock records, read and confirmed: the owner is
    gone), or None when the lock names no pid. A lock without a recorded creation time (older, or written by another
    tool) is never called 'reused'."""
    pid, recorded, _ours = owner_identity(text)
    if pid is None:
        return None
    if recorded is None:
        return pid_state(pid)
    seen, ticks = start_ticks(pid)
    if seen == 'alive' and ticks != recorded:
        return 'reused'
    return seen


def lock_is_stale(text, age_s, job_id=None):
    """Stale when its owner process is gone, when the lock records its owner's creation time and the process now under
    that pid was confirmed to be another one (the pid was reused), or when it names no pid and is older than
    NO_PID_STALE_S. A lock whose owner runs, or can't be read, is never stale, however old (ANY_STALE_S no longer
    applies to it), and the same export job's lock (job_id) counts as stale only when it names this very process: a
    job id never outweighs a live owner."""
    pid = owner_pid(text)
    if pid is None:
        return age_s > NO_PID_STALE_S
    if owner_state(text) in ('gone', 'reused'):
        return True
    return bool(job_id) and f'export {job_id} ' in (text or '') and pid == os.getpid()


def owner_text(name, pid=None):
    """'<name> pid N start T <time>': T, the owner's creation time, lets a later reader tell a reused pid from the
    owner (left out when it can't be read)."""
    pid = int(pid or os.getpid())
    seen, ticks = start_ticks(pid)
    return f'{label(name)} pid {pid}' + (f' start {ticks}' if seen == 'alive' and ticks else '') + f' {now()}'


# ------------------------------------------------------------------ the queue (first come, first served)

def priority_class(priority=None):
    """The lock class of a waiter: the given name, else LETITEDIT_LOCK_PRIORITY, else 'person'. An unknown name counts
    as 'person' (as a caller that names none)."""
    name = str(priority if priority is not None else os.environ.get(PRIORITY_ENV) or 'person').strip().lower()
    name = CLASS_ALIASES.get(name, name)
    return name if name in CLASSES else 'person'


def _rank(w):
    """A waiter's class rank, aged one step per AGE_S waited, never into 'person'."""
    rank = CLASSES.get(w.get('priority') or 'person', 0)
    if rank > 1 and AGE_S > 0:
        rank = max(1, rank - int((w.get('waited_s') or 0) // AGE_S))
    return rank


def ordered(waiting):
    """The waiters in the order they take the lock: class then arrival, or plain arrival while any names no class."""
    if any(not w.get('priority') for w in waiting):
        return sorted(waiting, key=lambda w: w['ticket'])
    return sorted(waiting, key=lambda w: (_rank(w), w['ticket']))


def _ahead_of(waiting, me):
    """The waiters before `me` (a queue entry, maybe not yet in `waiting`) in the order of ordered()."""
    line = ordered([w for w in waiting if w['ticket'] != me['ticket']] + [me])
    return line[:next(i for i, w in enumerate(line) if w is me)]


def queue_dir(path=None):
    """The folder of waiters' tickets for this lock: <lock>.queue next to it."""
    return Path(str(_path(path)) + '.queue')


def _ticket_owner_alive(pid, ts_ns):
    if not pid_alive(pid):
        return False
    started = pid_started(pid)
    return started is None or started <= ts_ns / 1e9 + 5.0      # started after the ticket: the pid was reused


def _queue(path, clean=False):
    """The live waiters for this lock, oldest first: [{'ticket', 'pid', 'name', 'job_id', 'since', 'waited_s'}].
    Dead tickets (pid not running or reused, or untouched for ANY_STALE_S) are left out and, with clean=True, removed;
    tickets untouched for TICKET_IDLE_S are left out and kept. Never raises for a missing or unreadable folder."""
    d = queue_dir(path)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    t = time.time()
    out = []
    for n in names:
        if not n.endswith('.ticket'):
            continue
        f = d / n
        try:
            idle = t - f.stat().st_mtime
        except OSError:
            continue
        m = TICKET_RX.match(n)
        if m is None:                                   # not one of ours (made by hand): never a waiter
            if clean and idle > NO_PID_STALE_S:
                with contextlib.suppress(OSError):
                    f.unlink()
            continue
        ts, tpid = int(m.group(1)), int(m.group(2))
        if idle > ANY_STALE_S or not _ticket_owner_alive(tpid, ts):
            if clean:
                with contextlib.suppress(OSError):
                    f.unlink()
            continue
        if idle > TICKET_IDLE_S:
            continue
        try:
            meta = json.loads(f.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            meta = {}
        out.append({'ticket': n, 'pid': tpid, 'name': str(meta.get('name') or '?')[:200],
                    'job_id': meta.get('job_id'),
                    'priority': meta.get('priority') if meta.get('priority') in CLASSES else None,
                    'since': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts / 1e9)),
                    'waited_s': round(max(0.0, t - ts / 1e9))})
    return out


class _Ticket:
    """This waiter's place in line: a file in the queue folder, named so names sort in arrival order."""

    def __init__(self, path, name, job_id=None, after_ts=0, priority=None):
        self.dir = queue_dir(path)
        self.meta = {'name': name, 'pid': os.getpid(), 'job_id': job_id, 'since': now(),
                     'priority': priority_class(priority)}
        self.ts = max(time.time_ns(), int(after_ts) + 1)
        self.name = f'{self.ts:020d}-{os.getpid()}-{secrets.token_hex(4)}.ticket'
        self.file = self.dir / self.name
        try:
            self._write()
        except BaseException:
            self.leave()                # a half-written ticket of a live pid would hold the line
            raise

    def _write(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.meta), encoding='utf-8')

    def entry(self):
        return {'ticket': self.name, 'pid': os.getpid(), 'name': str(self.meta['name'])[:200],
                'job_id': self.meta['job_id'], 'priority': self.meta['priority'],
                'since': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.ts / 1e9)),
                'waited_s': round(max(0.0, time.time() - self.ts / 1e9))}

    def touch(self):
        """Mark it as still waiting; put it back (same name, same place) if someone removed it."""
        try:
            os.utime(self.file)
        except FileNotFoundError:
            with contextlib.suppress(OSError):
                self._write()
        except OSError:
            pass

    def leave(self):
        with contextlib.suppress(OSError):
            self.file.unlink()


def _ts(ticket_name):
    m = TICKET_RX.match(ticket_name)
    return int(m.group(1)) if m else 0


# ------------------------------------------------------------------ what the lock says

def info(path=None):
    """What the lock file says now: {'path', 'held', 'text', 'owner_pid', 'owner_alive', 'written', 'age_s',
    'hand_written' (no pid in it), 'stale', 'waiting' (how many wait for it), 'queue' (the waiters, first in line
    first: {'ticket', 'pid', 'name', 'job_id', 'since', 'waited_s'}), 'message'}."""
    p = _path(path)
    return _info(p, _queue(p))


def _info(p, waiting):
    q = [dict(w) for w in ordered(waiting)]
    try:
        text = _read_text(p).strip()
        mtime = p.stat().st_mtime
    except OSError:
        out = {'path': str(p), 'held': False, 'waiting': len(q), 'queue': q}
        out['message'] = held_message(out)
        return out
    age = max(0.0, time.time() - mtime)
    pid = owner_pid(text)
    seen = owner_state(text) if pid else None
    alive = (seen not in ('gone', 'reused')) if pid else None
    out = {'path': str(p), 'held': True, 'text': text[:300], 'owner_pid': pid, 'owner_alive': alive,
           'owner_state': seen,
           'written': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime)), 'age_s': round(age),
           'hand_written': pid is None, 'stale': lock_is_stale(text, age), 'waiting': len(q), 'queue': q}
    out['message'] = held_message(out)
    return out


def held_message(i):
    n = i.get('waiting') or 0
    if not i.get('held'):
        if n:
            return (f"The PC render lock {i['path']} is free; {n} waiting for it take it in the order they came "
                    f"(first: \"{i['queue'][0]['name'][:80]}\", waiting {i['queue'][0]['waited_s'] / 60:.0f} min).")
        return f"The PC render lock {i['path']} is free."
    mins = i['age_s'] / 60
    base = f'The PC render lock {i["path"]} is held by "{i["text"][:120]}" (written {i["written"]}, {mins:.0f} min ago'
    if i['owner_pid'] is None:
        tail = (f'; it names no pid, so its owner cannot be checked; it counts as stale {NO_PID_STALE_S / 3600:g} h '
                'after it was written).')
    elif i.get('owner_state') == 'reused':
        tail = (f'; owner pid {i["owner_pid"]} now belongs to another program, started after the lock\'s owner, so the '
                'owner is gone and the lock is stale).')
    elif i.get('owner_state') == 'unknown':
        tail = (f'; owner pid {i["owner_pid"]} is a program letitedit is not allowed to look at (another user\'s or a '
                'protected one), so it may still be rendering: the lock is waited on and never cleared while that '
                'program runs).')
    elif i['owner_alive']:
        tail = f'; owner pid {i["owner_pid"]} is running).'
    else:
        tail = f'; owner pid {i["owner_pid"]} is not running, so the lock is stale).'
    return base + tail + (f' {n} waiting for it.' if n else '')


# ------------------------------------------------------------------ taking and releasing

class Holder:
    """A taken slot. owned=False when the lock belongs to a caller (caller_pids) and is left in place on release."""

    def __init__(self, path, text, owned=True):
        self.path, self.text, self.owned = Path(path), text, owned
        self.thread = None

    def __repr__(self):
        return f'Holder({self.text!r}, owned={self.owned})'

    def as_dict(self):
        return {'path': str(self.path), 'text': self.text, 'owned': self.owned}


# Which threads of this process hold a slot now: a program they start is tied to this process (see _install_tie).
_HELD = {}
_HELD_LOCK = threading.Lock()


def _hold(h):
    if h is not None and getattr(h, 'thread', None) is None:
        h.thread = threading.get_ident()
        with _HELD_LOCK:
            _HELD[h.thread] = _HELD.get(h.thread, 0) + 1
    return h


def _unhold(h):
    t = getattr(h, 'thread', None)
    if t is None:
        return
    h.thread = None
    with _HELD_LOCK:
        n = _HELD.get(t, 0) - 1
        if n > 0:
            _HELD[t] = n
        else:
            _HELD.pop(t, None)


def holding():
    """True when this thread holds a slot (so what it starts now is tied to this process)."""
    return _HELD.get(threading.get_ident(), 0) > 0



@contextlib.contextmanager
def _guard(path, timeout=None):
    """A short cross-process mutex around check-and-take, so two helpers never both clear and take one stale lock.
    Fails closed: raises GuardBusy when it isn't free within timeout seconds; nothing runs without it."""
    g = Path(str(path) + '.guard')
    g.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(g), os.O_RDWR | os.O_CREAT)
    try:
        timeout = GUARD_TIMEOUT_S if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while not _os_lock(fd, True):
            if time.monotonic() > deadline:
                raise GuardBusy(f'Another process held the render lock\'s guard ({g}) for over {timeout:g} s.')
            time.sleep(0.05)
        try:
            yield
        finally:
            _os_lock(fd, False)
    finally:
        os.close(fd)


def _os_lock(fd, take):
    """Take (non-blocking) or let go of an operating-system lock on a file's first byte. True when done."""
    try:
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, 0)
            msvcrt.locking(fd, msvcrt.LK_NBLCK if take else msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, (fcntl.LOCK_EX | fcntl.LOCK_NB) if take else fcntl.LOCK_UN)
        return True
    except OSError:
        return False


def _attempt(p, name, pid=None, job_id=None, caller_pids=None, text=None, ticket=None, join=False, priority=None):
    """One check-and-take under the guard. Returns (Holder, None, None) when taken (the ticket is gone), else
    (None, info of the holder with 'ahead' = waiters before this one, ticket). join=True: a waiter without a ticket
    gets one (at the back of the line). A caller holding the lock (caller_pids) gets in whatever the queue."""
    p.parent.mkdir(parents=True, exist_ok=True)
    cleared = new = None
    waiting, ahead = [], []
    try:
        with _guard(p):
            if ticket is not None:
                ticket.touch()
            _clear_orphan(p, 0.5)           # this process's own released lock that Windows wouldn't delete yet
            for _ in range(3):
                cur = age = None
                try:
                    cur = _read_text(p)
                    age = time.time() - p.stat().st_mtime
                except FileNotFoundError:
                    cur = None
                except OSError:
                    continue                # being written or removed right now: look again
                if cur is not None:
                    cpid = owner_pid(cur)
                    if caller_pids and lock_held_by(cur, caller_pids) and cpid and pid_alive(cpid):
                        h = Holder(p, cur.strip(), False)
                        h.cleared = None
                        return h, None, ticket
                waiting = _queue(p, clean=True)
                if ticket is not None:
                    ahead = _ahead_of(waiting, ticket.entry())
                elif waiting:                # not in line yet: where a ticket made now would stand
                    newest = max(_ts(w['ticket']) for w in waiting)
                    ahead = _ahead_of(waiting, {'ticket': f'{max(time.time_ns(), newest + 1):020d}-{os.getpid()}-~',
                                                'priority': priority_class(priority), 'waited_s': 0})
                else:
                    ahead = []
                if cur is not None and not lock_is_stale(cur, age, job_id):
                    break                   # held: wait
                if ahead:
                    break                   # free or stale, but someone came first: the first in line takes it
                if cur is not None:
                    cleared = cur.strip()
                    _unlink(p, 0.5)         # a reader may have it open for a moment (Windows refuses the delete)
                try:
                    fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    continue                # someone wrote it between our look and our take (by hand): look again
                mine = text or owner_text(name, pid)
                try:
                    os.write(fd, (mine + '\n').encode('utf-8'))
                except BaseException:
                    os.close(fd)
                    _unlink(p, RELEASE_RETRY_S)  # an empty lock would read as a hand-written one, waited on for hours
                    raise
                os.close(fd)
                if ticket is not None:
                    ticket.leave()
                h = Holder(p, mine, True)
                h.cleared = cleared
                return h, None, None
            if join and ticket is None:
                ticket = new = _Ticket(p, name, job_id, after_ts=max([_ts(w['ticket']) for w in waiting] or [0]),
                                       priority=priority)
                ahead = _ahead_of(waiting, ticket.entry())
                waiting = waiting + [ticket.entry()]
            held = _info(p, waiting)
    except BaseException:
        if new is not None:
            new.leave()                     # a ticket made by this call never outlives a failure of it
        raise
    held['ahead'] = len(ahead)
    return None, held, ticket


def try_acquire(name, pid=None, path=None, job_id=None, caller_pids=None, text=None, priority=None):
    """One attempt. Returns (Holder, None) when taken, else (None, info dict of the current holder; info['waiting'] says
    how many wait for it: a free lock is not taken while others wait for it).
    A stale lock is removed (and noted in the holder's 'cleared' attribute) and the slot taken."""
    try:
        h, held, _ = _attempt(_path(path), name, pid=pid, job_id=job_id, caller_pids=caller_pids, text=text,
                              priority=priority)
    except GuardBusy as e:
        return None, {'message': str(e), 'waiting': 0, 'ahead': 0, 'guard_busy': True}
    return _hold(h), held


def acquire(name, timeout_s=DEFAULT_TIMEOUT_S, poll_s=DEFAULT_POLL_S, pid=None, path=None, job_id=None,
            caller_pids=None, on_wait=None, cancelled=None, text=None, priority=None):
    """Wait (up to timeout_s seconds) for the slot in turn and take it: first come, first served (see the module
    doc). on_wait(info) is called about every poll_s seconds while it waits, and when its place in line changes
    (info['message'] says who holds it, since when and 'N waiting ahead'; info['ahead'], info['waited_s'],
    info['timeout_s']). cancelled() returning True stops the wait (raises Cancelled). Raises LockTimeout at the
    limit. Its ticket leaves the queue however the wait ends. priority: this waiter's class (priority_class)."""
    p = _path(path)
    t0 = time.monotonic()
    ticket = None
    told = None
    try:
        while True:
            if cancelled and cancelled():
                raise Cancelled('Cancelled')
            try:
                h, held, ticket = _attempt(p, name, pid=pid, job_id=job_id, caller_pids=caller_pids, text=text,
                                           ticket=ticket, join=True, priority=priority)
            except GuardBusy as e:              # fails closed: wait on, never take without the guard
                h, held = None, {'message': str(e), 'ahead': 0, 'guard_busy': True}
            if h:
                return _hold(h)
            waited = time.monotonic() - t0
            ahead = held['ahead']
            held['waited_s'] = round(waited)
            held['timeout_s'] = timeout_s
            held['message'] += f' {ahead} waiting ahead.'
            if timeout_s is not None and waited >= timeout_s:
                raise LockTimeout(f'Gave up after {waited:.0f} s (timeout_s={timeout_s:g}) waiting for the render lock. '
                                  + held['message'])
            t = time.monotonic()
            if on_wait and (told is None or t - told[0] >= poll_s or ahead != told[1]):
                told = (t, ahead)
                on_wait(held)
            step = max(0.05, min(poll_s, FIRST_POLL_S if ahead == 0 else QUEUE_POLL_S))
            time.sleep(step if timeout_s is None else max(0.05, min(step, timeout_s - waited)))
    finally:
        if ticket is not None:
            ticket.leave()


_CREATE_FILE = None


def _read_text(p):
    """The lock file's text, read without ever stopping its owner deleting it. A plain open on Windows shares reading
    and writing but not deleting, so the owner's delete fails while anyone reads (error 32); this open shares all
    three. Raises FileNotFoundError when there is no lock, OSError when it can't be read."""
    if os.name != 'nt':
        return Path(p).read_text(encoding='utf-8', errors='replace')
    global _CREATE_FILE
    import ctypes
    import msvcrt
    from ctypes import wintypes
    if _CREATE_FILE is None:
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        f = k.CreateFileW
        f.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                      wintypes.DWORD, wintypes.HANDLE)
        f.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        _CREATE_FILE = (f, k.CloseHandle)
    create, close = _CREATE_FILE
    h = create(str(p), 0x80000000, 0x7, None, 3, 0x80, None)     # GENERIC_READ, share read|write|delete, OPEN_EXISTING
    if h is None or h == wintypes.HANDLE(-1).value:
        err = ctypes.get_last_error()
        if err in (2, 3):                                          # file or path not found
            raise FileNotFoundError(2, 'No such file', str(p))
        raise OSError(None, ctypes.FormatError(err).strip(), str(p), err)
    try:
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY)
    except BaseException:
        close(h)
        raise
    with open(fd, 'rb') as fh:
        return fh.read().decode('utf-8', errors='replace').replace('\r\n', '\n').replace('\r', '\n')  # as text mode


def _unlink(p, retry_s=0.0):
    """Delete p: 'gone' when deleted, 'missing' when there was nothing to delete, 'busy' when it still couldn't be
    deleted after retry_s seconds. Windows refuses to delete a file another program has open without delete sharing (a
    waiter reading it, `render_lock.py status`, the editor's Jobs dialog: error 32), for as long as it has it open."""
    deadline = time.monotonic() + retry_s
    wait = 0.002
    while True:
        try:
            p.unlink()
            return 'gone'
        except FileNotFoundError:
            return 'missing'
        except OSError:
            if time.monotonic() >= deadline:
                return 'busy'
            time.sleep(wait)
            wait = min(wait * 2, 0.05)


def _file_id(p):
    with contextlib.suppress(OSError):
        return os.stat(p).st_ino or None
    return None


# Locks this process released but Windows wouldn't delete yet: {lock path: (its text, its file id)}. Only this process
# knows a lock of its own is released, so only it clears one (its waiters at once, a background thread meanwhile); a
# lock with another text or another file id (someone else's, written after ours went) is never touched.
_ORPHANS = {}
_ORPHANS_LOCK = threading.Lock()
_SWEEPER = None


def _clear_orphan(p, retry_s=0.0):
    """Under the guard: delete this process's released lock at p if it is still there. True when none is left."""
    key = str(p)
    with _ORPHANS_LOCK:
        o = _ORPHANS.get(key)
    if o is None:
        return True
    text, fid = o
    try:
        cur = _read_text(p).strip()
    except FileNotFoundError:
        cur = None
    except OSError:
        return False                        # can't be read right now: try again later
    if cur != text or (fid and _file_id(p) not in (None, fid)):
        done = True                         # gone, or another lock now: not ours to touch
    else:
        done = _unlink(p, retry_s) != 'busy'
    if done:
        with _ORPHANS_LOCK:
            if _ORPHANS.get(key) == o:
                del _ORPHANS[key]
    return done


def _sweep():
    global _SWEEPER
    wait = 0.05
    while True:
        with _ORPHANS_LOCK:
            keys = list(_ORPHANS)
            if not keys:
                _SWEEPER = None             # under the same lock _orphan checks it: a new one starts a new sweeper
                return
        for key in keys:
            p = Path(key)
            try:
                with _guard(p, timeout=5.0):
                    _clear_orphan(p, 0.2)
            except (GuardBusy, OSError):
                pass
        time.sleep(wait)
        wait = min(wait * 2, ORPHAN_RETRY_MAX_S)


def _orphan(p, text, fid):
    global _SWEEPER
    with _ORPHANS_LOCK:
        _ORPHANS[str(p)] = (text, fid)
        if _SWEEPER is None:
            _SWEEPER = threading.Thread(target=_sweep, name='render-lock-release', daemon=True)
            _SWEEPER.start()


def _release_own(p, mine):
    deadline = time.monotonic() + RELEASE_RETRY_S
    while True:
        try:
            cur = _read_text(p).strip()
            break
        except FileNotFoundError:
            return False
        except OSError:
            if time.monotonic() >= deadline:
                cur = None
                break
            time.sleep(0.01)
    if cur is None:                         # unreadable for RELEASE_RETRY_S: leave it to the background retries
        _orphan(p, mine, None)
        return False
    if cur != mine:
        return False
    fid = _file_id(p)
    r = _unlink(p, max(0.0, deadline - time.monotonic()))
    if r == 'busy':
        _orphan(p, mine, fid)               # still ours on disk: keep deleting it in the background
    return r == 'gone'


def release(holder):
    """Delete the lock when it is still the one this holder wrote. Returns True when deleted now. Under the guard, so a
    waiter never reads it while it goes; a delete Windows refuses because another program has the file open is
    retried for RELEASE_RETRY_S, then by a background thread of this process (and by this process's own next take)
    until the file is gone or no longer this holder's. Never raises."""
    if holder is None:
        return False
    _unhold(holder)
    if not holder.owned:
        return False
    p, mine = holder.path, holder.text.strip()
    try:
        with _guard(p):
            return _release_own(p, mine)
    except (GuardBusy, OSError):
        pass
    try:                                    # the guard couldn't be had: delete it as before, never leave it held
        return _release_own(p, mine)
    except OSError:
        _orphan(p, mine, None)
        return False


@contextlib.contextmanager
def slot(name, timeout_s=DEFAULT_TIMEOUT_S, poll_s=DEFAULT_POLL_S, **kw):
    """with slot('name'): ... holds the PC render lock for the block (see acquire for the parameters)."""
    h = acquire(name, timeout_s=timeout_s, poll_s=poll_s, **kw)
    try:
        yield h
    finally:
        release(h)


# ------------------------------------------------------------------ holds that give way, and model jobs

DEFAULT_HOLD_S = float(os.environ.get('LETITEDIT_HOLD_S', '300'))   # a long job offers the lock after this long
MODEL_WAIT_S = float(os.environ.get('LETITEDIT_MODEL_LOCK_WAIT_S', '900'))   # the longest a model job waits for it
CHECK_EVERY_S = 2.0


class Yielder:
    """A hold on the render lock that gives way. A long job (a cut-out, an export) holds the lock for its whole run;
    after hold_s seconds, maybe_yield() lets the lock go when someone waits for it, queues again behind them and carries
    on. Call it only between steps, when nothing heavy is running. A hold that is not ours (a caller's, joined through
    caller_pids) is never given up.
        with render_lock.Yielder('name') as y:
            for step in steps: ...; y.maybe_yield()
    on_pause(info) is called as the lock is let go (info: who waits), on_wait(info) while queueing again,
    on_resume() when it is taken back. y.pauses and y.paused_s say how often and how long it stood aside."""

    def __init__(self, name, hold_s=None, timeout_s=DEFAULT_TIMEOUT_S, poll_s=15.0, path=None, job_id=None,
                 caller_pids=None, on_pause=None, on_wait=None, on_resume=None, cancelled=None):
        self.name, self.hold_s = name, DEFAULT_HOLD_S if hold_s is None else float(hold_s)
        self.kw = dict(timeout_s=timeout_s, poll_s=poll_s, path=path, job_id=job_id, caller_pids=caller_pids,
                       on_wait=on_wait, cancelled=cancelled)
        self.on_pause, self.on_resume = on_pause, on_resume
        self.holder, self.since, self.checked = None, 0.0, 0.0
        self.pauses, self.paused_s = 0, 0.0

    def __enter__(self):
        self.holder = acquire(self.name, **self.kw)
        self.since = time.monotonic()
        return self

    def __exit__(self, *exc):
        release(self.holder)
        self.holder = None

    @property
    def owned(self):
        return bool(self.holder and self.holder.owned)

    def held_s(self):
        return time.monotonic() - self.since

    def should_yield(self):
        """True when we own the lock, have held it for hold_s and someone waits for it."""
        t = time.monotonic()
        if not self.owned or t - self.since < self.hold_s or t - self.checked < CHECK_EVERY_S:
            return False
        self.checked = t
        return bool(info(self.kw['path']).get('waiting'))

    def yield_now(self):
        i = info(self.kw['path'])
        if self.on_pause:
            self.on_pause(i)
        t0 = time.monotonic()
        release(self.holder)
        self.holder = None
        try:
            self.holder = acquire(self.name, **self.kw)
        finally:
            self.pauses += 1
            self.paused_s += time.monotonic() - t0
        self.since = self.checked = time.monotonic()
        if self.on_resume:
            self.on_resume()

    def maybe_yield(self):
        if self.should_yield():
            self.yield_now()
            return True
        return False


class Busy(RuntimeError):
    """A model job waited as long as it may for the render lock; str() says who has it and how long that may take."""


_model = {'mutex': threading.Lock(), 'n': 0, 'holder': None}


def behind_text(i):
    """Plain words for what holds the lock and roughly how long it may be: for an export, its own progress."""
    text = (i.get('text') or '').strip()
    who = f'"{text[:100]}"' if text else 'another job'
    out = f'{who}, running for {i.get("age_s", 0) / 60:.0f} min'
    m = re.search(r'letitedit export (\S+)', text)
    if m:
        try:
            import letitedit.timeline.render_queue as render_queue
            st = render_queue.status(m.group(1))
            pr = float(st.get('progress') or 0)
            out += f'; the export is {pr:.0%} done ({st.get("message") or st.get("state")})'
            if 0.03 < pr < 1 and i.get('age_s'):
                out += f', about {i["age_s"] * (1 - pr) / pr / 60:.0f} min to go'
        except Exception:  # noqa: BLE001 - no status: the plain words stay
            pass
    n = i.get('waiting') or 0
    return out + (f'; {n} job(s) already wait for it' if n else '')


@contextlib.contextmanager
def model_slot(what, timeout_s=None, path=None):
    """with model_slot('speech'): ... - a model job that uses the GPU runs only while it holds the PC render lock (one
    heavy job at a time, never a model during a render). Take it BEFORE the GPU turn (model_tools._gpu_turn), never
    inside it: that one order everywhere is what keeps two jobs from waiting on each other.
    One hold per process: jobs overlapping in threads share it, and it is let go when the last one ends, so the next
    waiter gets its turn between jobs. A caller that holds the lock (caller_pids: an export, `render_lock.py run`)
    owns it already and the job joins it. Waits up to timeout_s (LETITEDIT_MODEL_LOCK_WAIT_S, default 900 s), then raises
    Busy with who has it and about how long; it never runs without the lock. Yields {'waited_s', 'behind'}."""
    limit = MODEL_WAIT_S if timeout_s is None else timeout_s
    t0 = time.monotonic()
    first = {}
    with _model['mutex']:
        if _model['n'] == 0:
            def on_wait(i):
                first.setdefault('behind', behind_text(i))
            try:
                _model['holder'] = acquire(f'model job: {what}', timeout_s=limit, poll_s=5.0, path=path,
                                           caller_pids=ancestors(), on_wait=on_wait)
            except LockTimeout as e:
                i = info(path)
                raise Busy(f'The {what} job did not run: a model job waits while the PC is busy rendering (one heavy '
                           f'job at a time, so the PC does not crash). It waited {time.monotonic() - t0:.0f} s behind '
                           f'{behind_text(i)}. Nothing was started. Try again in a few minutes; letitedit_jobs shows '
                           f'what is running. ({str(e)[:160]})') from None
        _model['n'] += 1
    try:
        yield {'waited_s': round(time.monotonic() - t0, 1), **({'behind': first['behind']} if first else {})}
    finally:
        with _model['mutex']:
            _model['n'] -= 1
            if _model['n'] == 0:
                release(_model['holder'])
                _model['holder'] = None


# ------------------------------------------------------------------ the tools' own renders for a check

RENDER_THREADS = os.environ.get('LETITEDIT_RENDER_THREADS', '4')        # the export's thread cap (render_queue.THREADS)
CHECK_WAIT_S = float(os.environ.get('LETITEDIT_CHECK_LOCK_WAIT_S', '3600'))   # the longest a check's render waits
_render_turn = threading.RLock()


def is_render(args):
    """True for a run of melt, the export engine (a render, however short)."""
    return bool(args) and Path(str(args[0])).stem.lower() == 'melt'


def capped(args):
    """A command line with the export's thread cap unless it names its own: melt gets threads=RENDER_THREADS on its
    consumer, ffmpeg -threads RENDER_THREADS for its input; any other command as it is."""
    args = [str(a) for a in args]
    if is_render(args) and '-consumer' in args and not any(a.startswith('threads=') for a in args):
        args.append(f'threads={RENDER_THREADS}')
    elif args and Path(args[0]).stem.lower() == 'ffmpeg' and '-threads' not in args:
        args[1:1] = ['-threads', RENDER_THREADS]
    return args


@contextlib.contextmanager
def render_slot(what, timeout_s=None, path=None):
    """with render_slot('frames for check_frames'): ... - a render a tool makes for a check (frames, a stretch of the
    timeline, the mix, a review's pictures) runs only while this process holds the PC render lock, and one at a time in
    this process (its other threads wait their turn: the tool server runs calls side by side). A caller that holds the
    lock (this process, or one above it: an export, a tool that took it first, `render_lock.py run`) owns it already and
    the render joins it at once. Waits up to timeout_s (LETITEDIT_CHECK_LOCK_WAIT_S, default 3600 s; an export offers the
    lock to waiters every few minutes), then raises Busy with who has it; nothing is rendered without the lock.
    Run the command itself with capped() and background_flags() (below-normal priority)."""
    limit = CHECK_WAIT_S if timeout_s is None else timeout_s
    with _render_turn:
        t0 = time.monotonic()
        try:
            holder = acquire(f'letitedit check render: {what}', timeout_s=limit, poll_s=5.0, path=path,
                             caller_pids=ancestors())
        except LockTimeout as e:
            raise Busy(f'The render for {what} did not run: renders wait while the PC is busy rendering (one heavy job '
                       f'at a time, so the PC does not crash). It waited {time.monotonic() - t0:.0f} s behind '
                       f'{behind_text(info(path))}. Nothing was rendered. Try again in a few minutes; letitedit_jobs '
                       f'shows what is running. ({str(e)[:160]})') from None
        try:
            import letitedit.core.memory_room as memory_room
            memory_room.make_room(memory_room.RENDER_GB + memory_room.RESERVE_GB, f'the render for {what}')
            yield holder
        finally:
            release(holder)


_JOBS = {}
_JOBS_LOCK = threading.Lock()
JOB_KILL_ON_CLOSE = 0x2000
JOB_BREAKAWAY_OK = 0x0800
CREATE_SUSPENDED = 0x00000004
DETACHED_PROCESS = 0x00000008
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_TIE = threading.local()


def _job(kind):
    """This process's kill-on-close job objects (each made once, its handle held until the process ends, never
    inherited). 'owner': the process itself when it ties itself (bind_to_owner()) and the programs of ours it starts on
    purpose (tied(strict=False)); breakaway is allowed in it, so the deliberately independent export and job workers
    (started with CREATE_BREAKAWAY_FROM_JOB) still start from inside it. 'render': nested in 'owner', for every render
    child; nothing ever leaves it, not even a program that asks to (a browser's own sandbox, say)."""
    with _JOBS_LOCK:
        if kind in _JOBS:
            return _JOBS[kind]
        import ctypes
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ('r', 'w', 'o', 'rb', 'wb', 'ob')]

        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                        ('SchedulingClass', wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [('Basic', Basic), ('Io', IoCounters), ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                        ('PeakJobMemoryUsed', ctypes.c_size_t)]
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        job = k32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), 'CreateJobObject failed')
        info = Extended()
        info.Basic.LimitFlags = JOB_KILL_ON_CLOSE | (JOB_BREAKAWAY_OK if kind == 'owner' else 0)
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            k32.CloseHandle(job)
            raise OSError(err, 'SetInformationJobObject failed')
        _JOBS[kind] = job
        return job


def _owner_job():
    return _job('owner')


def _assign(handle, strict=False):
    """Put a process in this process's owner job and, strict, in the render job nested in it."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    for kind in (('owner', 'render') if strict else ('owner',)):
        if not k32.AssignProcessToJobObject(_job(kind), handle):
            raise OSError(ctypes.get_last_error(), f'AssignProcessToJobObject ({kind}) failed')


def tie_process(handle, strict=False):
    """Tie a process this code created itself (raw CreateProcess, suspended; a program that needs a STARTUPINFO field
    Popen can't set) to this process's owner job, and, strict, to the render job too. Fails closed: when it can't be
    tied the process is ended (it never ran, so nothing it could start exists) and OSError raised. Follow it with
    resume_process(handle)."""
    try:
        _assign(handle, strict=strict)
    except BaseException:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.TerminateProcess(handle, 1)
        raise


def resume_process(handle):
    """Let a process created suspended run (every thread of it); when it can't be resumed it is ended."""
    try:
        _resume(handle)
    except BaseException:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.TerminateProcess(handle, 1)
        raise


def in_job(proc, kind='render'):
    """True when proc (a Popen) is in this process's owner or render job (for checks and tests)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
    with _JOBS_LOCK:
        job = _JOBS.get(kind)
    if job is None:
        return False
    found = wintypes.BOOL()
    if not k32.IsProcessInJob(int(proc._handle), job, ctypes.byref(found)):
        raise OSError(ctypes.get_last_error(), 'IsProcessInJob failed')
    return bool(found.value)


def bind_to_owner(proc=None):
    """Tie a process's life to this one: proc (a subprocess.Popen already running) or, with None, this process itself
    (then everything it starts afterwards inherits the tie; it may still start the deliberately independent workers).
    When this process ends, however it ends, the tied processes end too. Fails closed: a child that can't be tied is
    killed and OSError raised. Returns True (False off Windows, or for an object without a process handle, a test's
    stand-in, where nothing is done). A program not yet started is tied at birth instead: start it inside
    `with tied():` (or while holding a slot), so it never runs a single instruction untied."""
    if os.name != 'nt':
        return False
    if proc is not None and getattr(proc, '_handle', None) is None:
        return False                    # no process handle: a stand-in (tests' fakes), nothing to tie
    import ctypes
    from ctypes import wintypes
    try:
        if proc is None:
            k32 = ctypes.WinDLL('kernel32')
            k32.GetCurrentProcess.restype = wintypes.HANDLE     # the pseudo-handle -1: an int would be cut to 32 bits
            _assign(k32.GetCurrentProcess())
        else:
            _assign(int(proc._handle), strict=True)
    except OSError:
        if proc is not None:
            with contextlib.suppress(OSError):
                proc.kill()
        raise
    return True


def _resume(handle):
    """Let a process created suspended run (every thread of it)."""
    import ctypes
    from ctypes import wintypes
    nt = ctypes.WinDLL('ntdll')
    nt.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    nt.NtResumeProcess.restype = ctypes.c_long
    status = nt.NtResumeProcess(handle)
    if status != 0:
        raise OSError(f'NtResumeProcess failed (status {status & 0xFFFFFFFF:#x})')


def resume(proc):
    """Let a Popen started with CREATE_SUSPENDED run."""
    if os.name == 'nt':
        _resume(int(proc._handle))


def _end_unstarted(proc):
    """End a child that never ran (it was created suspended): nothing it could have started exists."""
    import _winapi
    with contextlib.suppress(OSError):
        _winapi.TerminateProcess(proc._handle, 1)
    with contextlib.suppress(Exception):
        proc.wait(5)
    for f in (proc.stdin, proc.stdout, proc.stderr):
        if f:
            with contextlib.suppress(OSError):
                f.close()


@contextlib.contextmanager
def tied(strict=True):
    """Programs this thread starts inside the block are tied to this process from birth. strict (the default, for a
    render): they can never leave the tie. strict=False: a program of ours that may start the deliberately independent
    workers (render_lock.py run's command)."""
    stack = _TIE.__dict__.setdefault('stack', [])
    stack.append(bool(strict))
    try:
        yield
    finally:
        stack.pop()


def popen_tied(args, strict=True, **kw):
    """subprocess.Popen, the child tied to this process from birth (see tied())."""
    with tied(strict):
        return subprocess.Popen(args, **kw)


def popen_worker(args, **kw):
    """subprocess.Popen for a worker kept between requests (a speech or other model worker, the OCR or a browser
    worker): tied to this process from birth and strictly, whether or not a slot is held when it starts. A worker
    started before anyone took the PC lock and reused later by a lock holder is therefore already contained: if this
    process ends (killed included) the request it is running ends with it, so it never overlaps the next holder."""
    return popen_tied(args, strict=True, **kw)


def _tie_wanted(flags):
    """None (leave it), or strict True/False. In tied(): always. Otherwise while any thread of this process holds a slot
    (a pool's threads included), every program started is a render child and tied strictly, except one started on
    purpose to outlive this process (DETACHED_PROCESS, CREATE_BREAKAWAY_FROM_JOB: the editor, the workers, the
    background syncs), which stays as it was."""
    stack = getattr(_TIE, 'stack', None)
    if stack:
        return stack[-1]
    if _HELD and not flags & (DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB):
        return True
    return None


def _install_tie():
    """Wrap subprocess.Popen so a program that should be tied (see _tie_wanted) is created suspended, put in this
    process's job objects, then resumed: it never runs a single instruction untied. When it can't be put in them it is
    ended (it never ran, so nothing it could start exists) and OSError raised."""
    if os.name != 'nt' or getattr(subprocess.Popen, '_letitedit_tied', False):
        return
    original = subprocess.Popen.__init__

    def init(self, *args, **kwargs):
        flags = kwargs.get('creationflags', 0) or 0
        strict = None if len(args) > 11 else _tie_wanted(flags)
        if strict is None:
            return original(self, *args, **kwargs)
        if strict:
            flags &= ~CREATE_BREAKAWAY_FROM_JOB
        kwargs['creationflags'] = flags | CREATE_SUSPENDED
        original(self, *args, **kwargs)
        try:
            _assign(int(self._handle), strict=strict)
            _resume(int(self._handle))
        except BaseException:
            _end_unstarted(self)
            raise

    subprocess.Popen.__init__ = init
    subprocess.Popen._letitedit_tied = True


_install_tie()


# ------------------------------------------------------------------ a process's identity, and a supervised start

PROCESS_TERMINATE = 0x0001
PROCESS_DUP_HANDLE = 0x0040
PROCESS_SUSPEND_RESUME = 0x0800
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
STILL_ACTIVE = 259


def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    k.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD))
    k.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.WaitForSingleObject.restype = wintypes.DWORD
    return k


def identity_of(handle):
    """{'started': creation time (FILETIME ticks), 'image': the program's full path} of a running process, read through
    an open handle; None when it has exited or can't be read."""
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    k = _k32()
    code = wintypes.DWORD()
    if not k.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != STILL_ACTIVE:
        return None
    times = [wintypes.FILETIME() for _ in range(4)]
    if not k.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
        return None
    buf = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buf))
    if not k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
        return None
    return {'started': (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime, 'image': buf.value}


def _same_image(a, b):
    return bool(a) and bool(b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


class Verified:
    """An open handle to a process whose identity was checked (pid, creation time and program). Every look and every
    kill goes through this handle, so a pid reused after it was checked can never be hit."""

    def __init__(self, handle, pid):
        self.handle, self.pid = handle, pid

    def alive(self):
        return _k32().WaitForSingleObject(self.handle, 0) == 0x102          # WAIT_TIMEOUT

    def terminate(self, code=1):
        return bool(_k32().TerminateProcess(self.handle, code))

    def resume(self):
        _resume(self.handle)

    def close(self):
        if self.handle:
            _k32().CloseHandle(self.handle)
            self.handle = None


def verify_process(pid, started, image):
    """('alive', Verified) when pid runs and is the process recorded (same creation time and program); ('gone', None)
    when it doesn't run, or the pid now belongs to another process; ('unknown', None) when it runs but its identity
    wasn't recorded or can't be read. Only 'alive' may be watched, resumed or killed: unknown means wait or fail."""
    if not pid:
        return 'gone', None
    if os.name != 'nt':
        return ('unknown', None) if pid_alive(pid) else ('gone', None)
    k = _k32()
    h, _err = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE | PROCESS_TERMINATE | PROCESS_SUSPEND_RESUME)
    if not h:                    # can't be opened this way: gone only when Windows says no such process
        return ('gone', None) if pid_state(pid) == 'gone' else ('unknown', None)
    keep = False
    try:
        now = identity_of(h)
        if now is None:
            if k.WaitForSingleObject(h, 0) == 0:                         # signalled: it has exited
                return 'gone', None
            return 'unknown', None
        if started is None or not image:
            return 'unknown', None
        if now['started'] != started or not _same_image(now['image'], image):
            return 'gone', None                                          # the pid is someone else's now
        keep = True
        return 'alive', Verified(h, int(pid))
    finally:
        if not keep:
            k.CloseHandle(h)


def _new_job(breakaway=True):
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ('r', 'w', 'o', 'rb', 'wb', 'ob')]

    class Basic(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [('Basic', Basic), ('Io', IoCounters), ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t)]
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    k.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    job = k.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), 'CreateJobObject failed')
    info = Extended()
    info.Basic.LimitFlags = JOB_KILL_ON_CLOSE | (JOB_BREAKAWAY_OK if breakaway else 0)
    if not k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        err = ctypes.get_last_error()
        k.CloseHandle(job)
        raise OSError(err, 'SetInformationJobObject failed')
    return job


_CRASH_BEFORE_RECORD = None      # tests: called after the child is made and put in its job, before it is recorded


def spawn_recorded(args, record, **kw):
    """Start a program that outlives this process (a job worker's child) without ever leaving a running child unknown:
    it is created suspended inside a kill-on-close job object whose only handle this process holds; record(identity)
    stores {'pid', 'started', 'image'}; the job's handle is then handed to the child itself and the child resumed. If
    this process dies before the handover, the job closes and the never-run child ends with it, so a later worker can
    never start a second one beside it; after the handover the child (and everything it starts) lives exactly as long
    as the child does, and a later worker can find it by its recorded identity. Any failure ends the child (it never
    ran) and raises. Returns the Popen."""
    if os.name != 'nt':
        proc = subprocess.Popen(args, **kw)
        record({'pid': proc.pid, 'started': None, 'image': None})
        return proc
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.DuplicateHandle.argtypes = (wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE),
                                  wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    job = _new_job(breakaway=True)
    try:
        kw['creationflags'] = (kw.get('creationflags', 0) or 0) | CREATE_SUSPENDED
        with _no_tie():
            proc = subprocess.Popen(args, **kw)
        try:
            if not k.AssignProcessToJobObject(job, int(proc._handle)):
                raise OSError(ctypes.get_last_error(), 'AssignProcessToJobObject failed')
            if _CRASH_BEFORE_RECORD:
                _CRASH_BEFORE_RECORD(proc)
            ident = identity_of(int(proc._handle))
            if ident is None:
                raise OSError('the new process could not be identified')
            record({'pid': proc.pid, **ident})
            target = wintypes.HANDLE()
            if not k.DuplicateHandle(k.GetCurrentProcess(), job, int(proc._handle), ctypes.byref(target), 0, False,
                                     2):                                 # DUPLICATE_SAME_ACCESS
                raise OSError(ctypes.get_last_error(), 'DuplicateHandle failed')
            _resume(int(proc._handle))
        except BaseException:
            _end_unstarted(proc)
            raise
        return proc
    finally:
        k.CloseHandle(job)


@contextlib.contextmanager
def _no_tie():
    """Inside: programs started here are left as they are (spawn_recorded ties its child itself)."""
    stack = _TIE.__dict__.setdefault('stack', [])
    stack.append(None)
    try:
        yield
    finally:
        stack.pop()


def run_bound(args, timeout=None, input=None, check=False, capture_output=False, **kw):
    """subprocess.run, with the child tied to this process from birth (tied()): it ends when this process ends."""
    if capture_output:
        kw['stdout'] = kw['stderr'] = subprocess.PIPE
    if input is not None:
        kw['stdin'] = subprocess.PIPE
    with popen_tied(args, **kw) as proc:
        try:
            out, err = proc.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            raise subprocess.TimeoutExpired(proc.args, timeout, output=out, stderr=err) from None
        except BaseException:
            proc.kill()
            raise
    if check and proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, proc.args, out, err)
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def run_render(args, what=None, timeout=None, heavy=None, **kw):
    """subprocess.run of a render for a check: in render_slot, with the thread cap (capped), at below-normal priority
    and without a console window. heavy: None for any melt run (a render); True for another heavy pass (an ffmpeg pass
    over a whole video, a speech model), False to run the command as it is. kw go to subprocess.run (capture_output,
    text, encoding, cwd...); creationflags given there are kept and the priority added."""
    args = [str(a) for a in args]
    if not (is_render(args) if heavy is None else heavy):
        return subprocess.run(args, timeout=timeout, **kw)
    args = capped(args)
    if what is None:
        source = (args[args.index('-i') + 1] if '-i' in args[:-1] else
                  next((a for a in args[1:] if not a.startswith('-') and '=' not in a), args[0]))
        what = f'{Path(args[0]).stem} {Path(source).name}'
    flags = kw.pop('creationflags', getattr(subprocess, 'CREATE_NO_WINDOW', 0)) | background_flags()
    with render_slot(what):
        return run_bound(args, timeout=timeout, creationflags=flags, **kw)


# ------------------------------------------------------------------ programs that must outlive whoever starts them

BROKER_TIMEOUT_S = 60.0
_BROKER_TEST = None          # tests: 'force' sends every independent start through the broker, 'refuse' makes it fail


def in_any_job(handle=None):
    """True when the process (an open handle; None: this process) is in any job object (Windows)."""
    if os.name != 'nt':
        return False
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
    found = wintypes.BOOL()
    if not k.IsProcessInJob(handle if handle is not None else k.GetCurrentProcess(), None, ctypes.byref(found)):
        raise OSError(ctypes.get_last_error(), 'IsProcessInJob failed')
    return bool(found.value)


JOB_PROCESS_TIME = 0x0002
JOB_JOB_TIME = 0x0004
# A job whose processes it ends on its own: when its last handle closes, or when a time limit runs out.
JOB_ENDS_ITS_PROCESSES = JOB_KILL_ON_CLOSE | JOB_PROCESS_TIME | JOB_JOB_TIME


def own_job_limits():
    """This process's immediate job's limit flags (QueryInformationJobObject with no handle: for a nested job, the
    immediate one), or None when it is in no job (Windows; None elsewhere)."""
    if os.name != 'nt' or not in_any_job():
        return None
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [('Basic', Basic), ('Io', ctypes.c_ulonglong * 6), ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t)]
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD))
    info, n = Extended(), wintypes.DWORD()
    if not k.QueryInformationJobObject(None, 9, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(n)):
        raise OSError(ctypes.get_last_error(), 'QueryInformationJobObject failed')
    return int(info.Basic.LimitFlags)


def start_independent(args, cwd=None, env=None, creationflags=0, broker_first=False, inherit=True, kept_job_ok=None):
    """Start a program that must outlive this process and every job object it is in (the person's editor, the export
    and job workers, the background syncs): it never dies with whoever started it. Returns its pid.

    It is created suspended with CREATE_BREAKAWAY_FROM_JOB and checked to be in no job before it runs. When a job this
    process is in forbids breakaway (a render's job, or an outside one), or the new program still lands in a job, it is
    ended before it ran and started through an independent broker instead: Windows' own process service (WMI's
    Win32_Process.Create) starts a small launcher outside this process's jobs and tree, which starts the program with
    `env` and `cwd` and reports its pid. broker_first: the broker first (also out of this process tree, so closing the
    AI session's whole tree can't end it), breakaway after. Raises OSError when no way works: it is never started
    inside a job it would die with. stdin, stdout and stderr go nowhere. Off Windows: a new session.

    kept_job_ok (default: broker_first, so the export and job workers; never the person's editor): when neither way
    gets it out of every job, a last way starts it in the outside job it can't leave, if that job never ends it: a
    small launcher is started with breakaway (out of this process's own jobs, which all end their processes), checks
    its own immediate job ends nothing by itself (no kill-on-close, no time limit: a scheduled task's job, say), starts
    the program there and exits, so the program is out of this process tree too. A job that would end it is refused.

    Whichever way it starts, it gets the same environment and working folder: when env or cwd is left out it is this
    process's own, taken here before the way is chosen (as a plain start would give it); a relative cwd is made
    absolute here. inherit=False (the export and job workers, which take their settings as arguments): what is left
    out is left to the way it starts (the broker's is the person's own environment, never this process's)."""
    args = [str(a) for a in args]
    if cwd is not None:
        cwd = os.path.abspath(str(cwd))
    elif inherit:
        cwd = os.getcwd()
    if env is None and inherit:
        env = dict(os.environ)
    if os.name != 'nt':
        return subprocess.Popen(args, cwd=cwd, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True).pid
    flags = (creationflags or 0) | DETACHED_PROCESS
    order = ('broker', 'breakaway') if broker_first or _BROKER_TEST == 'force' else ('breakaway', 'broker')
    if _BROKER_TEST == 'force':
        order = ('broker',)
    elif broker_first if kept_job_ok is None else kept_job_ok:
        order += ('kept job',)
    errors = []
    for way in order:
        try:
            if way == 'broker':
                return _start_via_broker(args, cwd, env, flags)
            if way == 'kept job':
                return _start_in_kept_job(args, cwd, env, flags)
            pid = _start_breakaway(args, cwd, env, flags)
            if pid:
                return pid
            errors.append('breakaway: the program would still be in a job, so it was not run')
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            errors.append(f'{way}: {e}')
    raise OSError('could not start ' + Path(args[0]).name + ' outside the jobs it would die with: ' + '; '.join(errors))


def _start_breakaway(args, cwd, env, flags):
    """Started with breakaway, suspended, and let run only when it is in no job: its pid; else None (it never ran)."""
    with _no_tie():
        proc = subprocess.Popen(args, cwd=cwd, env=env, close_fds=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=flags | CREATE_BREAKAWAY_FROM_JOB | CREATE_SUSPENDED)
    try:
        if in_any_job(int(proc._handle)):
            _end_unstarted(proc)
            return None
        _resume(int(proc._handle))
    except BaseException:
        _end_unstarted(proc)
        raise
    return proc.pid


def _start_via_broker(args, cwd, env, flags):
    """WMI starts `python render_lock.py _independent <spec>` (outside this process's jobs and tree); that launcher
    starts the program as asked and writes its pid beside the spec."""
    if _BROKER_TEST == 'refuse':
        raise OSError('the broker is refused (test)')
    folder, spec, answer, exe, script = _launcher_spec(args, cwd, env, flags)
    line = f'"{exe}" "{script}" _independent "{spec}"'
    ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine='"
          + line.replace("'", "''") + "'; CurrentDirectory='" + str(script.parent).replace("'", "''")
          + "'}; Write-Output \"$($r.ReturnValue) $($r.ProcessId)\"")
    try:
        with _no_tie():
            r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True,
                               text=True, timeout=BROKER_TIMEOUT_S,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        code = (r.stdout.strip().split() + [''])[0]
        if code != '0':
            raise OSError(f'Win32_Process.Create answered {r.stdout.strip() or r.stderr.strip()[:200]!r}')
        return _launcher_answer(answer, "the broker's launcher", 'the broker')
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def _launcher_spec(args, cwd, env, flags, kept_job=False):
    """A folder with the launcher's spec (what to start, where its pid goes); (folder, spec, answer, exe, script)."""
    import tempfile
    folder = Path(tempfile.mkdtemp(prefix='letitedit-start-'))
    spec, answer = folder / 'spec.json', folder / 'pid.json'
    spec.write_text(json.dumps({'args': args, 'cwd': str(cwd) if cwd else None,
                                'env': dict(env) if env is not None else None, 'flags': int(flags),
                                'answer': str(answer), 'kept_job': bool(kept_job)}), encoding='utf-8')
    return folder, spec, answer, launcher_python(), Path(__file__).resolve().parents[2] / 'render_lock.py'


def launcher_python():
    """The interpreter for the small launchers: the base one, never a virtual environment's Scripts\\python(w).exe. That
    one is a stand-in that runs the real interpreter inside a private job of its own (kill-on-close, silent breakaway),
    so a launcher started through it always finds itself in a job, and the job it sees is that private one, not the
    one it was started in. The launchers need only the standard library. pythonw when there is one."""
    base = Path(getattr(sys, '_base_executable', None) or sys.executable)
    if not base.exists():
        base = Path(sys.executable)
    pyw = base.with_name('pythonw.exe')
    return pyw if pyw.exists() else base


def _launcher_answer(answer, who, way, proc=None):
    """The pid the launcher wrote; OSError with its reason when it started nothing, or when it never answers."""
    deadline = time.time() + BROKER_TIMEOUT_S
    while time.time() < deadline:
        got = None
        with contextlib.suppress(OSError, ValueError):
            got = json.loads(answer.read_text(encoding='utf-8-sig'))
        if got is not None:
            if got.get('pid'):
                return int(got['pid'])
            raise OSError(f"{who} could not start it: {got.get('error')}")
        if proc is not None and proc.poll() is not None:
            raise OSError(f'{who} ended (exit code {proc.returncode}) without reporting a pid')
        time.sleep(0.05)
    raise OSError(f'{way} did not report a pid in time')


def _start_in_kept_job(args, cwd, env, flags):
    """The last way (see start_independent's kept_job_ok): `python render_lock.py _independent <spec>` started with
    breakaway, suspended, checked to be in none of this process's own jobs, then let run; it starts the program in its
    own immediate job only when that job ends nothing by itself. Breakaway refused (an immediate job that forbids it):
    the launcher starts without it, still in that job, and its own check decides."""
    folder, spec, answer, exe, script = _launcher_spec(args, cwd, env, flags, kept_job=True)
    try:
        line = [str(exe), str(script), '_independent', str(spec)]
        base = DETACHED_PROCESS | getattr(subprocess, 'CREATE_NO_WINDOW', 0) | CREATE_SUSPENDED
        with _no_tie():
            try:
                proc = subprocess.Popen(line, cwd=str(script.parent), close_fds=True, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        creationflags=base | CREATE_BREAKAWAY_FROM_JOB)
            except OSError:
                proc = subprocess.Popen(line, cwd=str(script.parent), close_fds=True, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=base)
        try:
            with _JOBS_LOCK:
                own = [kind for kind in _JOBS]
            for kind in own:                      # this process's own jobs all end their processes when it ends
                if in_job(proc, kind):
                    raise OSError(f"the launcher is still in this process's own {kind} job, so it was not run")
            _resume(int(proc._handle))
        except BaseException:
            _end_unstarted(proc)
            raise
        return _launcher_answer(answer, 'the kept-job launcher', 'the kept-job launcher', proc)
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def job_ends_its_processes(limits):
    """A plain-words reason when a job with these limit flags ends its processes by itself, else None."""
    reasons = [why for flag, why in ((JOB_KILL_ON_CLOSE, 'kills them when its last handle closes'),
                                     (JOB_PROCESS_TIME, 'ends a process at its time limit'),
                                     (JOB_JOB_TIME, 'ends them all at its time limit')) if limits & flag]
    return ' and '.join(reasons) or None


def _independent_launcher(spec_path):
    """The broker's launcher (it runs outside every job), or the kept-job launcher (in an outside job it can't leave,
    which it checks ends nothing by itself): start the program the spec names, write its pid."""
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8-sig'))
    answer = Path(spec['answer'])
    try:
        if spec.get('kept_job'):
            limits = own_job_limits()
            why = job_ends_its_processes(limits) if limits is not None else None
            if why:
                raise OSError(f'the job it would stay in {why} (limits {limits:#x}), so it started nothing')
        elif in_any_job():         # the broker is only worth anything outside every job: never start it from inside one
            raise OSError("the broker's launcher is itself in a job, so it started nothing")
        proc = subprocess.Popen(spec['args'], cwd=spec.get('cwd'), env=spec.get('env'), close_fds=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=int(spec.get('flags') or 0))
        out = {'pid': proc.pid}
    except OSError as e:
        out = {'error': str(e)}
    tmp = answer.with_suffix('.tmp')
    tmp.write_text(json.dumps(out), encoding='utf-8')
    os.replace(tmp, answer)
    return 0 if 'pid' in out else 1


# ------------------------------------------------------------------ CLI

def background_flags():
    """Creation flags for a heavy job: below-normal priority on Windows (T52), which its child processes inherit."""
    return getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0) if os.name == 'nt' else 0


def below_normal():
    """Put this process at below-normal priority, as background_flags() does for a program started with it: for a
    heavy job started some other way (an export worker started through WMI). The programs it starts after inherit it.
    True when done (Windows)."""
    if os.name != 'nt':
        return False
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE      # the pseudo-handle -1: an int would be cut to 32 bits
    k32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k32.SetPriorityClass.restype = wintypes.BOOL
    return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000))


def _cli(argv):
    import argparse
    if argv and argv[0] == 'run':
        if '--' not in argv:
            print('usage: render_lock.py run --name <name> [--timeout-s S] [--poll-s S] -- <command ...>',
                  file=sys.stderr)
            return 2
        k = argv.index('--')
        ap = argparse.ArgumentParser(prog='render_lock.py run')
        ap.add_argument('--name', required=True)
        ap.add_argument('--timeout-s', type=float, default=DEFAULT_TIMEOUT_S)
        ap.add_argument('--poll-s', type=float, default=DEFAULT_POLL_S)
        ap.add_argument('--priority', choices=sorted(set(CLASSES) | set(CLASS_ALIASES)),
                        help="this render's class in the line (default: LETITEDIT_LOCK_PRIORITY, else person); the "
                             'command and everything it starts inherit it')
        ap.add_argument('--normal-priority', action='store_true',
                        help='run the command at normal priority (the default is below normal, so other work stays responsive; '
                             'the command and everything it starts inherit it)')
        a = ap.parse_args(argv[1:k])
        cmd = argv[k + 1:]
        if not cmd:
            print('render_lock.py run: no command after --', file=sys.stderr)
            return 2

        def waiting(i):
            print(f'[render_lock] waiting {i["waited_s"]} s of {a.timeout_s:g} s: {i["message"]}', file=sys.stderr,
                  flush=True)
        try:
            if a.priority:
                os.environ[PRIORITY_ENV] = priority_class(a.priority)
            h = acquire(a.name, timeout_s=a.timeout_s, poll_s=a.poll_s, on_wait=waiting)
        except LockTimeout as e:
            print(f'[render_lock] {e}', file=sys.stderr)
            return 3
        print(f'[render_lock] holding {h.path}: {h.text}' + (f' (cleared stale lock "{h.cleared[:100]}")'
                                                              if getattr(h, 'cleared', None) else ''),
              file=sys.stderr, flush=True)
        import letitedit.core.memory_room as memory_room
        room = memory_room.make_room(memory_room.RENDER_GB + memory_room.RESERVE_GB, a.name)
        if room.get('note'):
            print(f'[render_lock] {room["note"]}', file=sys.stderr, flush=True)
        try:
            # The command and everything it starts end with this process, however it ends (killed included): a dead
            # holder never leaves a render running behind the lock it held. Not tied: not run.
            try:
                bind_to_owner()
            except OSError as e:
                print(f'[render_lock] could not tie the command to this process ({e}); not running it', file=sys.stderr)
                return 4
            # T72: name the streams. With no window the child gets its own hidden console, and whatever it printed went there, not
            # to whoever started us: the app's Export reads the volume step's report from this output.
            proc = popen_tied(cmd, strict=False, stdout=sys.stdout, stderr=sys.stderr,
                              creationflags=0 if a.normal_priority else background_flags())
            try:
                return proc.wait()
            except KeyboardInterrupt:
                proc.kill()
                proc.wait()
                return 130
        except OSError as e:
            print(f'[render_lock] could not start the command: {e}', file=sys.stderr)
            return 127
        finally:
            release(h)
            print('[render_lock] released', file=sys.stderr, flush=True)
    if argv and argv[0] == 'status':
        print(json.dumps(info(), indent=1))
        return 0
    if len(argv) == 2 and argv[0] == '_independent':
        return _independent_launcher(argv[1])
    print(__doc__)
    return 2


if __name__ == '__main__':
    # the wait lines name other jobs (project and file names, any script): UTF-8 whatever the Windows code page is
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, 'reconfigure'):
            _stream.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(_cli(sys.argv[1:]))
