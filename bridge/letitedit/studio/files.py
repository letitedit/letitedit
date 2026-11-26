"""The Studio job folder's files: safe writes and reads, the events log, hashes (contract/CONTRACT.md section 1, 3).

Standard library only: the reference fake (fake.py) uses it too.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os
import threading
import time
from pathlib import Path

LOCK_NAME = '.studio.lock'
FAKE_MARK = '.studio-fake'          # in a job folder the reference fake made: the real Studio never takes it
HOME_MARK = 'studio-home.json'      # in a Studio folder: {"side": "letitedit" | "fake"}
SIDE_MARK = '.studio-side'          # in a job folder: who took it ({side, home, job_id}), claimed atomically
SIDES = ('letitedit', 'fake')
FAKE_WARNING = {'code': 'fake_studio', 'message': "Made by letitedit Studio's reference fake (LETITEDIT_STUDIO_FAKE): "
                'placeholder files, nothing real was made.'}


def is_fake_folder(folder):
    folder = Path(folder)
    return (folder / FAKE_MARK).is_file() or side_of(folder) == 'fake'


def _create_once(path, text):
    """Create path holding text, atomically and only if it doesn't exist: True when this call made it, False when it
    was already there. The text is complete the moment the name appears (a hard link of a finished file)."""
    path = Path(path)
    tmp = path.with_name(f'{path.name}.{os.getpid()}-{threading.get_ident()}-{os.urandom(3).hex()}.new')
    tmp.write_text(text, encoding='utf-8')
    try:
        try:
            os.link(tmp, path)
            return True
        except FileExistsError:
            return False
        except OSError:                     # a drive without hard links: exclusive creation, then the text
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            return True
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _read_mark(path, wait_s=2.0):
    """The owner a marker file names, as a dict ({'side'} and, for a job folder, {'home', 'job_id'}), or None when
    there is none. A marker still being written (the fallback above) is read again for up to wait_s; one that never
    names a known side is {'side': 'unknown'}."""
    path = Path(path)
    deadline = time.monotonic() + wait_s
    while True:
        try:
            text = path.read_text(encoding='utf-8-sig').strip()
        except FileNotFoundError:
            return None
        except OSError:
            text = ''
        mark = {'side': text}
        if text.startswith('{'):
            with contextlib.suppress(ValueError):
                data = json.loads(text)
                mark = {k: data.get(k) for k in ('side', 'home', 'job_id') if data.get(k) is not None}
                mark['side'] = str(data.get('side') or '')
        if mark['side'] in SIDES:
            return mark
        if time.monotonic() > deadline:
            return {'side': 'unknown'}
        time.sleep(0.05)


def _read_side(path, wait_s=2.0):
    """The side named in a marker file ('letitedit', 'fake', 'unknown'), or None when there is none."""
    mark = _read_mark(path, wait_s)
    return None if mark is None else mark['side']


def home_key(h):
    """A Studio folder as a job folder's marker names it."""
    return os.path.normcase(os.path.abspath(str(h)))


def owner_of(job_dir):
    """Who took a job folder: {'side', 'home', 'job_id'} (an older marker names only the side), or None."""
    return _read_mark(Path(job_dir) / SIDE_MARK)


def holds(job_dir, side, home=None, job_id=None):
    """True when the job folder was taken by this side and, when given, this Studio folder (home) for this job id."""
    mark = owner_of(job_dir)
    if mark is None or mark.get('side') != side:
        return False
    if home is not None and mark.get('home') != home_key(home):
        return False
    return job_id is None or mark.get('job_id') == job_id


def side_of(job_dir):
    """Which side took a job folder: 'letitedit', 'fake', 'unknown' or None (not taken)."""
    return _read_side(Path(job_dir) / SIDE_MARK)


def claim_side(job_dir, side, home=None, job_id=None):
    """Take a job folder for one side and, when given, one Studio folder (home) and one job id, atomically, before
    anything else is written for it: the marker names its owner the moment it appears. True when it is this owner's
    (taken now or before); False when another owner has it (the other side, another Studio folder, another job id, an
    older marker that names no owner, an unreadable marker): then nothing may be written there."""
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    if side == 'letitedit' and (job_dir / FAKE_MARK).is_file():
        return False                        # a fake folder from before the side marker
    mark = {'side': side}
    if home is not None:
        mark['home'] = home_key(home)
    if job_id is not None:
        mark['job_id'] = job_id
    _create_once(job_dir / SIDE_MARK, json.dumps(mark) + '\n')
    return holds(job_dir, side, home, job_id)


def taken_by(job_dir):
    """Who has a job folder, in plain words, for a refusal."""
    mark = owner_of(job_dir) or {}
    side = mark.get('side')
    if side == 'fake':
        return 'the reference fake'
    if side == 'letitedit':
        if mark.get('home'):
            return f"letitedit's Studio folder {mark['home']} (job {mark.get('job_id')})"
        return 'letitedit, before job folders named their owner'
    return 'another program'


def claim_home(h, side):
    """Mark a Studio folder as the real letitedit's or the fake's, atomically (two first uses at once can't both
    win); refuse one the other side already uses."""
    h = Path(h)
    h.mkdir(parents=True, exist_ok=True)
    mark = h / HOME_MARK
    if _read_side(mark) is None:
        legacy = side == 'fake' and (h / 'queue').is_dir()       # a real Studio folder from before the mark existed
        _create_once(mark, json.dumps({'side': 'letitedit' if legacy else side}) + '\n')
    seen = _read_side(mark)
    if seen != side:
        owner = {'fake': 'the reference fake', 'letitedit': 'letitedit'}.get(seen, 'another program')
        raise RuntimeError(f"The Studio folder {h} belongs to {owner}; "
                           f"{'the reference fake' if side == 'fake' else 'letitedit'} never shares it. "
                           'Give each its own folder (LETITEDIT_STUDIO_FAKE_HOME for the fake).')
    return h


def now_iso(t=None):
    """ISO 8601 with the UTC offset, to the second."""
    stamp = _dt.datetime.fromtimestamp(time.time() if t is None else t).astimezone()
    return stamp.isoformat(timespec='seconds')


class FolderBusy(TimeoutError):
    """A job folder's lock could not be taken in time: nothing was written."""


def write_json(path, data):
    """Write whole: a temporary file beside it (a name no other process or thread uses), then swapped in (retried
    while a reader has it open)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.{os.urandom(4).hex()}.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    try:
        for i in range(40):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.05 * (1 + i // 10))
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def read_json(path, default=None, tries=5):
    """Read a JSON file; a locked or half-written one is read again after about 100 ms (tries times)."""
    path = Path(path)
    for i in range(tries):
        try:
            return json.loads(path.read_text(encoding='utf-8-sig'))
        except FileNotFoundError:
            return default
        except (PermissionError, ValueError):
            if i == tries - 1:
                return default
            time.sleep(0.1)
    return default


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(chunk), b''):
            h.update(block)
    return h.hexdigest()


def canonical(data):
    """job.json compared after parsing: sorted keys, no spacing."""
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def job_hash(data):
    return hashlib.sha256(canonical(data).encode('utf-8')).hexdigest()


def _open_process(pid):
    """(handle, 0) or (0, the Windows error), for PROCESS_QUERY_LIMITED_INFORMATION."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    h = k.OpenProcess(0x1000, False, int(pid))
    return (h, 0) if h else (0, ctypes.get_last_error())


def _pid_alive(pid):
    """False only when the process is known to be gone. One that can't be read (another user's, a protected one)
    counts as running: a claim or a lock it holds is never taken over."""
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0 or pid > 0xFFFFFFFF:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        try:
            h, err = _open_process(pid)
        except (OSError, ValueError, OverflowError):
            return True
        if not h:
            return err != 87                           # ERROR_INVALID_PARAMETER: no process has that pid
        k = ctypes.WinDLL('kernel32')
        k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        code = wintypes.DWORD()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return not ok or code.value == 259             # STILL_ACTIVE (unreadable: running)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:                                    # not allowed to signal it: it exists
        return True


def _note_stuck(lock_file):
    """LETITEDIT_STUDIO_LOCK_DEBUG=<file>: note when a writer timed out waiting for a job folder's lock."""
    target = os.environ.get('LETITEDIT_STUDIO_LOCK_DEBUG')
    if target:
        with contextlib.suppress(OSError), open(target, 'a', encoding='utf-8') as log:
            log.write(f'{now_iso()} pid {os.getpid()} gave up waiting on {lock_file}\n')


_HELD = {}                      # this process's held folder locks: path -> [depth, fd, thread id]
_HELD_GUARD = threading.Lock()


def _try_lock(fd):
    try:
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, 0)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd):
    with contextlib.suppress(OSError):
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, 0)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)


LOCK_TIMEOUT_S = 60.0


@contextlib.contextmanager
def folder_lock(folder, timeout_s=None):
    """A short lock on one job folder's status, events and result writes: an operating-system lock on .studio.lock, a
    file that stays in the folder (deleting a lock file fails on Windows while someone reads it). A process that dies
    lets go of it by itself. Taking it again inside the same thread (nested) is allowed. Fails closed: when it can't be
    taken within timeout_s (default LOCK_TIMEOUT_S) it raises FolderBusy and nothing runs unlocked."""
    f = Path(folder) / LOCK_NAME
    key = os.path.normcase(os.path.abspath(str(f)))
    with _HELD_GUARD:
        held = _HELD.get(key)
        if held is not None and held[2] == threading.get_ident():
            held[0] += 1
            nested = True
        else:
            nested = False
    if nested:
        try:
            yield
        finally:
            with _HELD_GUARD:
                _HELD[key][0] -= 1
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(f), os.O_RDWR | os.O_CREAT)
    deadline = time.monotonic() + (LOCK_TIMEOUT_S if timeout_s is None else timeout_s)
    while not _try_lock(fd):
        if time.monotonic() > deadline:
            os.close(fd)
            _note_stuck(f)
            raise FolderBusy(f'The job folder {Path(folder)} is locked by another letitedit process; nothing was '
                             'written. Try again.')
        time.sleep(0.01)
    with _HELD_GUARD:
        _HELD[key] = [1, fd, threading.get_ident()]
    try:
        yield
    finally:
        with _HELD_GUARD:
            _HELD.pop(key, None)
        _unlock(fd)
        os.close(fd)


CLAIM = '.claim-'


def claim_inbox(inbox):
    """Yield (original path, claimed path) for each waiting <job_id>.json, claimed by renaming it (atomic: of several
    entry points reading the inbox at once, exactly one takes each file). A claim whose process died is put back first,
    so a crash mid-take loses nothing."""
    inbox = Path(inbox)
    # A rename alone is not exclusive on Windows (os.replace opens the file by name, then renames that open file: two
    # entry points can both "succeed", the second moving the first one's claim away). So claims are chosen and made
    # under the Studio folder's lock (the one above the inbox, so the inbox holds only jobs), held only for this step
    # and never with another lock; taking the files happens after, outside it.
    taken = []
    with folder_lock(inbox.parent):
        for c in inbox.glob(f'*.json{CLAIM}*'):
            name, _, tail = c.name.partition(CLAIM)
            try:
                pid = int(tail.split('-')[0])
            except ValueError:
                pid = 0
            if not _pid_alive(pid):
                with contextlib.suppress(OSError):
                    os.replace(c, c.with_name(name)) if not (inbox / name).exists() else os.replace(
                        c, c.with_name(name + '.refused'))
        for f in sorted(inbox.glob('*.json')):
            if f.name.endswith('.refused.json'):
                continue
            claimed = f.with_name(f'{f.name}{CLAIM}{os.getpid()}-{os.urandom(4).hex()}')
            try:
                os.replace(f, claimed)
            except OSError:
                continue
            taken.append((f, claimed))
    yield from taken


def claim_inbox_file(inbox, name):
    """Claim one waiting inbox file by name, as claim_inbox does (under the Studio folder's lock, by a rename): (original
    path, claimed path), or None when it isn't waiting (never sent, or another entry point took it a moment ago)."""
    inbox = Path(inbox)
    f = inbox / name
    if Path(name).name != name or not name.endswith('.json') or name.endswith('.refused.json'):
        return None
    with folder_lock(inbox.parent):
        if not f.is_file():
            return None
        claimed = f.with_name(f'{f.name}{CLAIM}{os.getpid()}-{os.urandom(4).hex()}')
        try:
            os.replace(f, claimed)
        except OSError:
            return None
    return f, claimed


def hand_off_cancel(folder, attempt, wait_s=10.0):
    """Hand a job folder's cancel file to the attempt that is ending, by renaming it atomically to
    cancel.attempt-<attempt> (never check-then-delete: a cancel file a caller writes a moment later is a new file and is
    kept). A cancel written before the rename belongs to the ending attempt; any cancel that exists after it belongs to
    the next. Retried while a writer has the file open (a sharing violation on Windows). Returns the new name's path
    when a file was handed off, else None (there was none, or this attempt's was already handed off)."""
    folder = Path(folder)
    src, dst = folder / 'cancel', folder / f'cancel.attempt-{attempt}'
    if dst.exists():
        return None                                    # already done (a repeat after a stop): leave any cancel alone
    deadline = time.monotonic() + wait_s
    while True:
        try:
            os.rename(src, dst)                        # atomic; refuses to replace an existing dst
            return dst
        except FileNotFoundError:
            return None
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.02)


def wait_for_claims(inbox, timeout_s=15.0):
    """Wait while another live process is taking an inbox file, so the caller sees the inbox settled (a job dropped
    there a moment ago is then submitted, or refused)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        busy = False
        for c in Path(inbox).glob(f'*.json{CLAIM}*'):
            try:
                pid = int(c.name.partition(CLAIM)[2].split('-')[0])
            except ValueError:
                continue
            if pid != os.getpid() and _pid_alive(pid):
                busy = True
        if not busy:
            return True
        time.sleep(0.05)
    return False


def finish_claim(original, claimed, problems, contract_version):
    """Rename a claimed inbox file to .taken, or to .refused with <job_id>.refused.json beside it."""
    if problems:
        write_json(original.with_name(original.stem + '.refused.json'),
                   {'contract_version': contract_version, 'problems': problems})
    os.replace(claimed, original.with_name(original.name + ('.refused' if problems else '.taken')))


def waiting_in_inbox(inbox):
    """True when the inbox holds a job.json not yet taken (refusal notes don't count)."""
    return any(not f.name.endswith('.refused.json') for f in Path(inbox).glob('*.json'))


def last_seq(folder):
    """The seq of the last whole line of events.jsonl (0 when none)."""
    p = Path(folder) / 'events.jsonl'
    try:
        lines = p.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return 0
    for line in reversed(lines):
        try:
            return int(json.loads(line)['seq'])
        except (ValueError, KeyError, TypeError):
            continue
    return 0


def append_event(folder, contract_version, job_id, type_, **fields):
    """Append one line to events.jsonl (whole, one write; a broken last line is ended first). Returns its seq."""
    folder = Path(folder)
    p = folder / 'events.jsonl'
    with folder_lock(folder):
        seq = last_seq(folder) + 1
        line = {'contract_version': contract_version, 'job_id': job_id, 'seq': seq, 'time': now_iso(), 'type': type_}
        line.update({k: v for k, v in fields.items() if v is not None})
        prefix = ''
        try:
            with open(p, 'rb') as f:
                f.seek(0, 2)
                if f.tell():
                    f.seek(-1, 2)
                    if f.read(1) != b'\n':
                        prefix = '\n'
        except FileNotFoundError:
            pass
        with open(p, 'a', encoding='utf-8', newline='\n') as f:
            f.write(prefix + json.dumps(line, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())
    return seq


def read_events(folder):
    """The whole lines of events.jsonl (a last line that doesn't parse is skipped)."""
    out = []
    try:
        text = (Path(folder) / 'events.jsonl').read_text(encoding='utf-8')
    except FileNotFoundError:
        return out
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


INTERNAL_FILES = ('overlay-boxes.json', 'overlay-facts.json')   # T357: bookkeeping, never in a result's file list
#   (overlay_clash.BOXES_FILE and FACTS_FILE; a test keeps them equal)


def delivered(entries):
    """The outputs[] entries without internal bookkeeping files (INTERNAL_FILES), whatever lists them."""
    return [e for e in entries or []
            if not (isinstance(e, dict) and Path(str(e.get('path') or '')).name.lower() in INTERNAL_FILES)]


def output_entry(folder, rel, role, **extra):
    """An outputs[] entry for a file in the job folder: its size and SHA-256, plus the fields given."""
    p = Path(folder) / rel
    d = {'role': role, 'path': Path(rel).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha256_file(p)}
    d.update({k: v for k, v in extra.items() if v is not None})
    return d
