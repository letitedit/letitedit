"""How much of a person's disk letitedit's redrawable work folders may hold (T95). The numbers live here, in one place.

checks._work makes a new timestamped folder for every set of frames a tool draws, and nothing else removes them. Each new
folder starts a trim in the background of that call: past the budget the folders touched longest ago go first, but never
one touched in the last hour, because a tool's reply names those files and an AI may read them next.

Sizes count a file once however many hard links it has. A scene's picture sequence is hard links to a few drawn frames,
so a plain add-up reads 20 times too high here (measured 4 Nov: 181 GB apparent, 8 GB on the disk).

The room letitedit always leaves free on a drive it writes to (reserve_bytes): DEFAULT_KEEP_FREE_GB, a few GB, so
Windows, its page file and other programs keep room on a typical laptop. A PC can keep more with the setting
disk_keep_free_gb (settings.json, or the untracked settings.local.json beside it) or the LETITEDIT_DISK_KEEP_FREE_GB
environment variable. Exports, the work folders' budget, the playback caches and the memory planner's page-file room
all read it. Short of room, a job says how much to free on which drive.
"""
import json
import math
import os
import re
import shutil
import threading
import time
from pathlib import Path

GB = 1024 ** 3

BUDGET_GB = 2
DEFAULT_KEEP_FREE_GB = 5
KEEP_FREE_SETTING = 'disk_keep_free_gb'
KEEP_FREE_ENV = 'LETITEDIT_DISK_KEEP_FREE_GB'
SPACE_WAIT_S = 120          # time for another job's temporary files to go; then the job says how much to free
SPACE_POLL_S = 60
# On a small or nearly full drive: this share of the room we have (free space plus what these folders hold).
SHARE_OF_ROOM = 0.2
KEEP_TOUCHED_S = 3600       # a reply names these files; an AI may read them next
EVERY_S = 120               # a trim walks the folders, so at most one this often across every process on the PC

# Folders that can be drawn again and that no project points at. Replies name their files, and only for a while.
WORK_KINDS = ('frames', 'changes', 'caption-fit', 'audio', 'exports', 'storyboard', 'ranges', 'qc', 'qc-faces',
              'audio-variants', 'face-variants', 'aim-before', 'aim-after', 'thumb-variants')
UNFINISHED_JOB_KEEP_S = 7 * 86400     # an export that never said it finished may be waiting or paused; past this it is dead
FINISHED_JOB = ('done', 'failed', 'cancelled')
# Throwaway pictures and pages, named per call, that no saved project pointed at (3162 projects searched, T95). By age, since
# each is small and some are looked up again while a video is being made.
AGED = ('views/look', 'views/try', 'views/overview', 'views/stills', 'timing/previews', 'timing/chunks', 'motion/work',
        'objects/work')
AGED_DAYS = 14
ENGINE_HISTORY_GB = 1       # HyperFrames' own edit history, one folder per scene page it drew (about 1.6 MB)
# Only checks._work's own names: cache\frames also holds other tools' long-lived folders (motion_meaning's stills).
WORK_NAME = re.compile(r'^\d{8}-\d{6}-[0-9a-f]{6}$')
STAMP = '.work-trim-stamp'
# Export need: the chunks plus the joined file. Measured on 364 past exports: 1.74 MB per second of video at the median,
# 4.07 at the 90th percentile; 4 is the median counted twice, so a refusal is rarely false.
EXPORT_BYTES_PER_S = 4 * 1000 ** 2
EXPORT_MIN_BYTES = GB
CHUNK_ROOM_BYTES = GB // 4   # an export under way: the room above the reserve that drawing one more piece asks for

_memo = {}                  # folder -> (real bytes, newest touch), only for folders past KEEP_TOUCHED_S, which don't change
_running = threading.Lock()


def usage(folder):
    """(bytes really on the disk, newest modified time) of a folder: each file counted once, however many links it has."""
    seen, total, newest = set(), 0, 0.0
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not _is_junction(os.path.join(root, d))]   # os.walk goes through junctions
        try:
            newest = max(newest, os.stat(root).st_mtime)
        except OSError:
            pass
        for name in files:
            try:
                st = os.stat(os.path.join(root, name))
            except OSError:
                continue                                # another process is removing it
            newest = max(newest, st.st_mtime)
            key = (st.st_dev, st.st_ino)
            if key not in seen:
                seen.add(key)
                total += st.st_size
    return total, newest


def _folders(cache):
    for kind in WORK_KINDS:
        try:
            entries = list(os.scandir(Path(cache) / kind))
        except OSError:
            continue
        for e in entries:
            try:
                if WORK_NAME.match(e.name) and e.is_dir(follow_symlinks=False) and not _is_junction(e.path):
                    yield e.path
            except OSError:
                continue


def _is_junction(path):
    check = getattr(os.path, 'isjunction', None)
    return bool(check and check(path))


def _job_is_live(folder, now):
    """An export job that may still run, and so keeps its folder whatever its age."""
    status = Path(folder) / 'status.json'
    try:
        data = json.loads(status.read_text(encoding='utf-8-sig'))
        import letitedit.timeline.render_queue as render_queue
        return render_queue._pid_alive(data.get('pid')) or (data.get('state') not in FINISHED_JOB and now - status.stat().st_mtime < UNFINISHED_JOB_KEEP_S)
    except (OSError, ValueError, AttributeError):
        return False                                    # no readable status past the hour: it never started


def _setting(key):
    """A key's value in the settings (settings.local.json over settings.json), read without writing either file."""
    from letitedit.core import hardware
    path = Path(os.environ['LETITEDIT_SETTINGS']) if os.environ.get('LETITEDIT_SETTINGS') else Path(hardware.SETTINGS)
    value = None
    for p in (path, path.with_name(path.stem + '.local' + path.suffix)):
        try:
            data = json.loads(p.read_text(encoding='utf-8-sig') or '{}')
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and key in data:
            value = data[key]
    return value


def reserve_bytes():
    """The bytes letitedit leaves free on a drive it writes to: LETITEDIT_DISK_KEEP_FREE_GB, else the settings'
    disk_keep_free_gb, else DEFAULT_KEEP_FREE_GB. A value that isn't a number of GB at or above 0 is skipped."""
    for value in (os.environ.get(KEEP_FREE_ENV), _setting(KEEP_FREE_SETTING)):
        try:
            gb = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(gb) and gb >= 0:
            return int(gb * GB)
    return int(DEFAULT_KEEP_FREE_GB * GB)


def budget(cache, held=0, limit_gb=None):
    """The bytes these folders may hold on this drive now."""
    limit = float(limit_gb if limit_gb is not None else os.environ.get('LETITEDIT_WORK_CACHE_GB', BUDGET_GB)) * GB
    try:
        return min(limit, SHARE_OF_ROOM * max(0, shutil.disk_usage(cache).free + held - reserve_bytes()))
    except OSError:
        return limit


def held(cache):
    """Bytes the work folders hold (for a health view)."""
    return sum(usage(f)[0] for f in _folders(cache))


def trim(cache, limit_gb=None, now=None):
    """Remove the folders touched longest ago until the rest fit the budget. A folder another process has open stays, or
    stays in part, and the next trim tries again. Returns what happened."""
    now = time.time() if now is None else now
    rows = []
    for folder in _folders(cache):
        known = _memo.get(folder)
        size, touched = known if known else usage(folder)
        if not known and now - touched >= KEEP_TOUCHED_S:
            _memo[folder] = (size, touched)
        rows.append((touched, folder, size))
    total = sum(r[2] for r in rows)
    allowed = budget(cache, total, limit_gb)
    removed = freed = 0
    for touched, folder, size in sorted(rows):
        if total <= allowed or now - touched < KEEP_TOUCHED_S:
            break
        if Path(folder).parent.name == 'exports' and _job_is_live(folder, now):
            continue
        shutil.rmtree(folder, ignore_errors=True)
        _memo.pop(folder, None)
        if not os.path.exists(folder):
            removed += 1
            freed += size
            total -= size
    trim_engine_history(now=now)
    trim_aged(cache, now=now)
    try:
        (Path(cache) / STAMP).write_text(json.dumps({'held': total, 'budget': allowed, 'at': now}), encoding='utf-8')
    except OSError:
        pass
    return {'removed': removed, 'freed': freed, 'held': total, 'budget': allowed}


def trim_aged(cache, now=None):
    """Remove what AGED holds that nothing has touched for AGED_DAYS. Returns how many entries went."""
    now = time.time() if now is None else now
    removed = 0
    for name in AGED:
        try:
            entries = list(os.scandir(Path(cache) / name))
        except OSError:
            continue
        for e in entries:
            try:
                if _is_junction(e.path) or e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if now - usage(e.path)[1] >= AGED_DAYS * 86400:
                        shutil.rmtree(e.path, ignore_errors=True)
                        removed += not os.path.exists(e.path)
                elif now - e.stat().st_mtime >= AGED_DAYS * 86400:
                    os.unlink(e.path)
                    removed += 1
            except OSError:
                continue                                # in use: the next trim tries again
    return removed


def trim_engine_history(home=None, now=None):
    """The engine keeps an edit history for every page it draws and never removes one. Ours are throwaway pages."""
    now = time.time() if now is None else now
    base = Path(home or Path.home()) / '.cache' / 'hyperframes' / 'history'
    try:
        entries = [e.path for e in os.scandir(base) if e.is_dir(follow_symlinks=False) and not _is_junction(e.path)]
    except OSError:
        return 0
    rows = []
    for folder in entries:
        size, touched = usage(folder)
        rows.append((touched, folder, size))
    total, removed = sum(r[2] for r in rows), 0
    for touched, folder, size in sorted(rows):
        if total <= ENGINE_HISTORY_GB * GB or now - touched < KEEP_TOUCHED_S:
            break
        shutil.rmtree(folder, ignore_errors=True)
        if not os.path.exists(folder):
            total -= size
            removed += 1
    return removed


def last_trim(cache):
    """What the last trim found, for a health view: {'held', 'budget', 'at'}, or None. Reads one small file."""
    try:
        return json.loads((Path(cache) / STAMP).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def _gb(n):
    return f'{n / GB:.1f} GB' if n >= GB / 10 else f'{n / 1024 ** 2:.0f} MB'


def _gb_up(n):
    """Like _gb, rounded up: freeing this much is enough (a few bytes over a tenth don't round up)."""
    if n >= GB / 10:
        return f'{math.ceil(n / GB * 10 - 1e-6) / 10:.1f} GB'
    return f'{max(1, math.ceil(n / 1024 ** 2 - 1e-6))} MB'


def short_of_room(what, need, reserve, free, drive):
    """The plain words for a job short of room: how much to free on which drive, and why."""
    why = f'it needs about {_gb(need)} for the job and keeps {_gb(reserve)} free for Windows and other programs'
    if free is None:
        return f'Not enough disk space to {what}: drive {drive} could not be read ({why}).'
    return (f'Not enough disk space to {what}: free about {_gb_up(need + reserve - free)} on drive {drive}, then try '
            f'again ({why}; the drive has {_gb(free)} free).')


def _free(path):
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free, p.anchor or str(p)
    except OSError:
        return None, str(p)


from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
def make_room(cache=None, pressure=False):
    """Trim only redrawable caches, preserving recent replies and unfinished exports; report measured free-byte change."""
    if cache is None:
        cache = _paths.CODE_ROOT / 'cache'
    cache = Path(cache)
    before, _ = _free(cache)
    work = trim(cache, limit_gb=0 if pressure else None)
    import letitedit.timeline.render_queue as render_queue
    chunks = render_queue.prune_cache(limit_gb=0 if pressure else None, cache=cache)
    leftovers = render_queue.clean_leftovers(cache)
    after, _ = _free(cache)
    return {'freed': max(0, after - before) if after is not None and before is not None else 0,
            'work': work, 'chunks_removed': chunks, 'leftovers_removed': leftovers,
            'note': 'Free-byte change can include other programs writing or freeing space.'}


def space_users():
    """Bounded diagnostic from the render lock and last inventory, without scanning a disk while a job waits."""
    root = _paths.CODE_ROOT
    details = []
    try:
        import letitedit.core.render_lock as render_lock
        holder = render_lock.info()
        if holder:
            details.append('render lock: ' + str(holder)[:300])
    except Exception:
        pass
    try:
        summary = json.loads((root / 'tools/storage-consumers.json').read_text(encoding='utf-8-sig'))
        details.append('last storage inventory: ' + '; '.join(summary['largest'][:6]))
    except (OSError, ValueError, KeyError):
        details.append('Windows Settings > System > Storage shows what uses the space')
    return '. '.join(details)


def need_room(path, need, what, cache=None, *, reserve=None, wait_s=None, poll_s=None,
              cancelled=None, progress=None):
    """Return once the drive holding `path` has `need` bytes plus reserve_bytes() free. Short of that: make room from
    letitedit's own redrawable caches, then wait up to wait_s (SPACE_WAIT_S; 0: no wait) in poll_s steps for room,
    then raise OSError saying how much to free on which drive. Cancellation is checked every second. Call outside a
    render-lock slot; workers check again between work units."""
    reserve = reserve_bytes() if reserve is None else reserve
    wait_s = SPACE_WAIT_S if wait_s is None else wait_s
    poll_s = SPACE_POLL_S if poll_s is None else poll_s
    required = max(0, need) + reserve
    deadline = time.monotonic() + max(0, wait_s)
    while True:
        if cancelled and cancelled():
            raise InterruptedError('Cancelled while waiting for disk space')
        free, drive = _free(path)
        if free is not None and free >= required:
            return
        try:
            make_room(cache, pressure=True)
        except Exception:
            pass
        free, drive = _free(path)
        if free is not None and free >= required:
            return
        message = short_of_room(what, max(0, need), reserve, free, drive)
        if progress:
            progress(message.replace('Not enough disk space to', 'Waiting for disk space to', 1)
                     .replace(', then try again', '', 1))
        if time.monotonic() >= deadline:
            waited = f' Waited {wait_s / 60:.0f} min for room.' if wait_s >= 60 else ''
            hint = space_users().strip()
            raise OSError(message + waited + (' ' + hint.rstrip('.') + '.' if hint else ''))
        until = min(deadline, time.monotonic() + max(1, poll_s))
        while time.monotonic() < until:
            if cancelled and cancelled():
                raise InterruptedError('Cancelled while waiting for disk space')
            time.sleep(min(1, max(0, until - time.monotonic())))


def export_need(seconds):
    """Bytes an export of this length should have room for."""
    return max(EXPORT_MIN_BYTES, int(seconds * EXPORT_BYTES_PER_S))


def trim_soon(cache):
    """Start a trim beside the caller if none has run lately. Never raises and never holds the caller up."""
    try:
        stamp = Path(cache) / STAMP
        try:
            if time.time() - stamp.stat().st_mtime < EVERY_S:
                return False
        except OSError:
            pass
        if not _running.acquire(blocking=False):
            return False
        try:
            stamp.touch()
            threading.Thread(target=_trim_and_release, args=(cache,), daemon=True, name='cache-trim').start()
        except Exception:  # noqa: BLE001 - no thread, no trim: the next folder tries again
            _running.release()
            return False
        return True
    except Exception:  # noqa: BLE001 - a trim must never cost a tool its answer
        return False


def _trim_and_release(cache):
    try:
        make_room(cache)
    except Exception:  # noqa: BLE001 - tried again by a later folder
        pass
    finally:
        _running.release()
