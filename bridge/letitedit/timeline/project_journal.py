"""A project's own folder of edit records, beside its .mlt: <stem>.letitedit\\ (named <stem>.shotcut\\ before 30 Oct
2026: an old one is moved to the new name on first use, or merged into it when both exist; see folder())

  journal.jsonl   one JSON entry per line: every apply and undo (time UTC, actor, label, the changes), and free notes
  journal.md      the same entries as readable lines
  history\\        the copies kept before each apply (undo goes back through them); history\\undone\\ holds undone states
  lease.json      who is editing the project now and until when (an edit lease)
  tracks.json     owners of tracks: {track name: {owner, since, by}}

The actor of an edit is the `actor` argument, else the LETITEDIT_ACTOR environment variable, else the app the
tool server runs under ('claude' or 'codex', from the processes above it), else DEFAULT_ACTOR.
Edits made by the person in the Shotcut window never go through here and are never blocked.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

ACTOR_ENV = 'LETITEDIT_ACTOR'
DEFAULT_ACTOR = 'agent'
LEASE_S = 600.0          # a lease lasts this long after the last apply
WAIT_S = 0.0             # how long an apply waits for another owner's lease to end
POLL_S = 0.5             # how often a waiting apply looks at the lease again
CHANGES_KEPT = 12        # changes listed in a journal entry (the total is always recorded)
CHANGE_CHARS = 240       # longest change line kept in a journal entry
LOCK_TIMEOUT_S = 10.0    # longest wait for the folder's lock file
LOCK_STALE_S = 30.0      # a lock file older than this is left over from a crashed process


class LeaseHeld(ValueError):
    """Another actor holds an unexpired edit lease on the project."""


class TrackOwned(ValueError):
    """The edit changes (or re-owns) a track owned by another actor."""


# ---------------------------------------------------------------------------- places, time, actor

CLIENT_NAMES = (('codex', 'codex'), ('claude', 'claude'))   # (part of a process name above this one, actor)


def client_actor(pid=None):
    """The actor name of the app this tool server runs under, from the names of the processes above this one
    (nearest first, CLIENT_NAMES), or None."""
    try:
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
        info = {}
        try:
            e = Entry()
            e.dwSize = ctypes.sizeof(Entry)
            ok = k32.Process32First(snap, ctypes.byref(e))
            while ok:
                info[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.decode('utf-8', 'replace').lower())
                ok = k32.Process32Next(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
    except Exception:  # noqa: BLE001 - not Windows, or no snapshot
        return None
    cur, seen = int(pid or os.getpid()), set()
    while cur and cur not in seen and len(seen) < 32:
        seen.add(cur)
        parent, name = info.get(cur, (None, ''))
        for part, who in CLIENT_NAMES:
            if part in name:
                return who
        cur = parent
    return None


_CLIENT = []


def actor(given=None):
    """The `actor` argument, else LETITEDIT_ACTOR, else the app this runs under (client_actor), else DEFAULT_ACTOR."""
    if given or os.environ.get(ACTOR_ENV):
        return str(given or os.environ.get(ACTOR_ENV))
    if not _CLIENT:
        _CLIENT.append(client_actor())
    return _CLIENT[0] or DEFAULT_ACTOR


import letitedit.app.ai_clis as ai_clis  # noqa: E402  (the one list of AIs; it imports this module only inside a function)
LABEL_NAMES = {**{i: row.get('short') or i for i, row in ai_clis.AIS.items()}, DEFAULT_ACTOR: 'letitedit'}


def label_prefix(given=None):
    """The name an editor undo label starts with for this actor ('Claude', 'Codex', 'letitedit', or the name)."""
    who = actor(given)
    return LABEL_NAMES.get(who.lower(), who)


SIDE = '.letitedit'      # the project's own folder: <stem>.letitedit beside <stem>.mlt
OLD_SIDE = '.shotcut'    # its name before 30 Oct 2026 (hooks, review notes, version links, journal, history)


def _merge(old, new):
    """Moves what `old` has and `new` lacks into `new` (folders merged the same way); a file both have stays in
    `old` (the new one wins, nothing is lost). True when `old` ended up empty."""
    empty = True
    for entry in list(old.iterdir()):
        target = new / entry.name
        try:
            if not target.exists():
                entry.rename(target)
            elif entry.is_dir() and target.is_dir():
                if _merge(entry, target):
                    entry.rmdir()
                else:
                    empty = False
            else:
                empty = False
        except OSError:      # in use, or another process moved it first
            empty = empty and not entry.exists()
    return empty


def migrate(project):
    """Moves an old <stem>.shotcut folder to <stem>.letitedit (merged into it when both exist). Returns the folder
    to use: the new one, or the old one while it can't be moved (a file in it is open elsewhere)."""
    p = Path(project)
    new, old = p.parent / f'{p.stem}{SIDE}', p.parent / f'{p.stem}{OLD_SIDE}'
    if not old.is_dir():
        return new
    try:
        if not new.exists():
            old.rename(new)
        elif _merge(old, new):
            old.rmdir()
    except OSError:
        pass
    return new if new.is_dir() or not old.is_dir() else old


def folder(project):
    """<project folder>/<stem>.letitedit, the project's own folder (an old <stem>.shotcut is moved there first)."""
    return migrate(project)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _iso_ms(dt):
    """A lease expiry: milliseconds kept, so a lease shorter than a second does not end early."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def _parse(text):
    fmt = '%Y-%m-%dT%H:%M:%S.%fZ' if '.' in text else '%Y-%m-%dT%H:%M:%SZ'
    return datetime.datetime.strptime(text, fmt).replace(tzinfo=datetime.timezone.utc)


@contextlib.contextmanager
def _locked(project, timeout_s=LOCK_TIMEOUT_S, stale_s=LOCK_STALE_S):
    """A short exclusive lock on the project's folder (journal appends, lease and owner changes)."""
    d = folder(project)
    d.mkdir(parents=True, exist_ok=True)
    lock = d / '.lock'
    end = time.monotonic() + timeout_s
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale_s:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > end:
                raise TimeoutError(f'{lock} is held by another process (waited {timeout_s:g} s)')
            time.sleep(0.05)
    try:
        yield d
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (FileNotFoundError, ValueError):
        return default


def _write_json(path, data):
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


# ---------------------------------------------------------------------------- journal

def _summary(changes, kept=CHANGES_KEPT, chars=CHANGE_CHARS):
    lines = [str(c) for c in (changes or [])]
    out = [c if len(c) <= chars else c[:chars].rstrip() + ' ...' for c in lines[:kept]]
    return out, len(lines)


def _md_line(e):
    head = f"- {e['time']}  {e['actor']}  {e['kind']}"
    if e.get('label'):
        head += f"  \"{e['label']}\""
    if e.get('where'):
        head += f"  ({e['where']})"
    if e.get('text'):
        head += f"  {e['text']}"
    lines = [head]
    for c in e.get('changes') or []:
        lines.append(f'    - {c}')
    more = (e.get('changes_total') or 0) - len(e.get('changes') or [])
    if more > 0:
        lines.append(f'    - ... and {more} more')
    return '\n'.join(lines) + '\n'


def stage_name(text):
    """A bare done mark, or a done mark with its single-line em-dash summary."""
    match = re.fullmatch(r'stage:(log|story|rough|fine|finish):done(?:[ \t]+—[ \t]+\S[^\r\n]*)?',
                         str(text or '').strip())
    return match.group(1) if match else None


def record(project, kind, who=None, label=None, changes=None, text=None, kept=CHANGES_KEPT, **extra):
    """Append one entry to the project's journal (journal.jsonl and journal.md). Returns the entry."""
    project = Path(project)
    summary, total = _summary(changes, kept)
    e = {'time': _iso(_now()), 'actor': actor(who), 'kind': kind}
    if label:
        e['label'] = str(label)
    if text:
        e['text'] = str(text)
    if changes is not None:
        e['changes'] = summary
        e['changes_total'] = total
    e.update({k: v for k, v in extra.items() if v is not None})
    with _locked(project) as d:
        with open(d / 'journal.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
        md = d / 'journal.md'
        new = not md.exists()
        with open(md, 'a', encoding='utf-8') as f:
            if new:
                f.write(f'# Journal: {project.name}\n\n')
            f.write(_md_line(e))
        stage = stage_name(text)
        if kind == 'note' and stage:
            run_file = d / 'stage-run.json'
            if run_file.exists():
                run = json.loads(run_file.read_text(encoding='utf-8-sig'))
                if run.get('format') == 'letitedit-stage-run/1':
                    with project.open('rb') as stream:
                        revision = hashlib.file_digest(stream, 'sha256').hexdigest()
                    boundary = {'id': uuid.uuid4().hex, 'run_id': run['run_id'], 'stage': stage,
                                'recorded_at': time.time(), 'revision': revision,
                                'last_transaction': last_transaction(project)}
                    with (d / 'stage-boundaries.jsonl').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(boundary) + '\n')
                        stream.flush()
                        os.fsync(stream.fileno())
    return e


def last_transaction(project):
    """Stable identity of the latest apply/undo, including a changed-then-restored timeline."""
    transactions = [entry for entry in entries(project, None) if entry.get('kind') in ('apply', 'undo')]
    if not transactions:
        return None
    payload = json.dumps(transactions[-1], sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def note(project, text, who=None):
    """A free note in the journal."""
    if not text or not str(text).strip():
        raise ValueError('text is the note to add')
    text = str(text).strip()
    artifact = re.fullmatch(r'(brief|log|selects|story_plan|pickups|fine_pass|finish_pass|handover):\s*([\s\S]+)', text)
    if artifact:
        name, body = artifact.groups()
        target = folder(project) / (name + ('.md' if name in ('pickups', 'fine_pass', 'finish_pass', 'handover')
                                            else '.json'))
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix == '.json':
            try:
                value = json.loads(body)
            except ValueError as e:
                raise ValueError(f'{name} needs valid JSON; correct the note and try again') from e
            if not isinstance(value, dict):
                raise ValueError(f'{name} needs a JSON object; correct the note and try again')
            _write_json(target, value)
        else:
            target.write_text(body.strip() + '\n', encoding='utf-8')
    stage = stage_name(text)
    if stage:
        state = stage_progress(project)
        name = stage
        missing = state[name]['missing']
        if missing:
            raise ValueError(f"The {name} stage is not done yet. Add {', '.join(missing)}, then mark it done.")
        if name == 'fine':
            left = _restarts_left(project)
            if left:
                raise ValueError(
                    f"The fine stage is not done yet: the cut keeps {len(left)} restart(s) the review will flag: "
                    + '; '.join(f"{f['problem']} [{f.get('id')}]" for f in left[:8])
                    + ". Cut the first try of each ({op: trim} on the sound where the last try begins; letitedit_hear "
                    "has what's said there). One said twice on purpose: name it in fine_pass.md on a line that says "
                    "kept on purpose and quotes the words, with why. Then mark it done.")
    return record(project, 'note', who, text=text)


def _restarts_left(project):
    """Restarts the review's project check finds in the cut and the fine notes don't keep on purpose; [] when the check
    can't run (no project file, no cached words), so a stage is never refused for a check that couldn't look."""
    try:
        import letitedit.review.checks as checks
        return checks.restarts_left(project)
    except Exception:  # noqa: BLE001 - the review still runs the same check on the export
        return []


STAGES = ('log', 'story', 'rough', 'fine', 'finish')
STAGE_FILES = {'log': ('log.json', 'selects.json'), 'story': ('story_plan.json', 'pickups.md'),
               'rough': (), 'fine': ('fine_pass.md',), 'finish': ('finish_pass.md',)}
OUTPUT_HINTS = {'log.json': 'log.json with files, segments and driver_note',
                'selects.json': 'selects.json with ranked beats',
                'story_plan.json': 'story_plan.json with purpose and sections'}


def _has_stage_output(project, side, name):
    for path in (project.parent / name, side / name):
        if not path.is_file() or not path.stat().st_size:
            continue
        if name.endswith('.md'):
            if path.read_text(encoding='utf-8').strip():
                return True
            continue
        try:
            value = json.loads(path.read_text(encoding='utf-8-sig'))
        except ValueError:
            continue
        if not isinstance(value, dict):
            continue
        if name == 'log.json' and not (value.get('files') and value.get('segments') and value.get('driver_note')):
            continue
        if name == 'selects.json' and not value.get('beats'):
            continue
        if name == 'story_plan.json' and not (value.get('purpose') and value.get('sections')):
            continue
        return True
    return False


def has_stage_output(project, name):
    """Whether a stage output (a name in STAGE_FILES, or brief.json) is beside the project or in its working folder
    and checks out (non-empty; log.json with files, segments and driver_note; selects.json with beats; story_plan.json
    with purpose and sections)."""
    project = Path(project)
    return _has_stage_output(project, folder(project), name)


def nothing_to_log(project):
    """True for a Look that draws everything: there is no footage, so no log stage."""
    import letitedit.looks.look_inputs as look_inputs
    return look_inputs.no_footage(project)


def stage_progress(project):
    """Accepted stage markers and the concrete output still missing for a first cut."""
    project = Path(project)
    side = folder(project)
    journal = entries(project, None)
    done = set()
    result = {}
    nothing = nothing_to_log(project)   # a Look that draws everything has no footage to log
    for name in STAGES:
        if name == 'log' and nothing:
            done.add(name)
            result[name] = {'done': True, 'missing': []}
            continue
        prior = STAGES[STAGES.index(name) - 1] if name != STAGES[0] else None
        missing = [OUTPUT_HINTS.get(f, f) for f in STAGE_FILES[name] if not _has_stage_output(project, side, f)]
        if prior and prior not in done:
            missing.insert(0, f'the {prior} stage')
        if name == 'rough':
            if not project.is_file():
                missing.append('the project file')
            renders = [e['text'].split(':', 1)[1].strip() for e in journal if e.get('kind') == 'note'
                       and str(e.get('text', '')).startswith('render:')]
            if not any(Path(p).is_file() and Path(p).stat().st_size for p in renders):
                missing.append('a watched rough export (render:<file path>)')
        if name in ('fine', 'finish') and not project.is_file():
            missing.append('the project file')
        accepted = not missing and any(e.get('kind') == 'note' and stage_name(e.get('text')) == name for e in journal)
        if accepted:
            done.add(name)
        result[name] = {'done': accepted, 'missing': missing}
    return result


def entries(project, limit=50):
    """The last `limit` journal entries, oldest first (limit=None: all)."""
    path = folder(project) / 'journal.jsonl'
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out[-limit:] if limit else out


# ---------------------------------------------------------------------------- edit lease

def lease(project):
    """The lease on the project: {owner, taken, expires, lease_s, expired, expires_in_s} or None."""
    data = _read_json(folder(project) / 'lease.json', None)
    if not data or not data.get('owner'):
        return None
    left = (_parse(data['expires']) - _now()).total_seconds()
    return dict(data, expired=left <= 0, expires_in_s=round(max(left, 0), 1))


def _held_by_other(project, who):
    cur = lease(project)
    if cur and not cur['expired'] and cur['owner'] != who:
        return cur
    return None


def _held_message(project, cur, wait_s):
    return (f"{Path(project).name} has an edit lease held by {cur['owner']!r} until {cur['expires']} "
            f"({cur['expires_in_s']:g} s from now); waited {wait_s:g} s (wait_s). Nothing was changed. "
            f"Reading is not blocked.")


def take(project, who=None, lease_s=None, wait_s=None, poll_s=POLL_S, applying=True):
    """Take or renew the lease for `who`. Raises LeaseHeld when another owner's lease is unexpired after wait_s.
    Returns the lease record (plus waited_s)."""
    who = actor(who)
    lease_s = LEASE_S if lease_s is None else float(lease_s)
    wait_s = WAIT_S if wait_s is None else float(wait_s)
    start = time.monotonic()
    while True:
        with _locked(project) as d:
            cur = _held_by_other(project, who)
            if cur is None:
                now = _now()
                prev = lease(project)
                hold = lease_s if lease_s > 0 else LEASE_S       # held while the apply runs, even with lease_s=0
                data = {'owner': who, 'taken': prev['taken'] if prev and prev['owner'] == who and not prev['expired']
                        else _iso(now), 'expires': _iso_ms(now + datetime.timedelta(seconds=hold)), 'lease_s': lease_s,
                        'applying': bool(applying)}
                _write_json(d / 'lease.json', data)
                waited = round(time.monotonic() - start, 2)
                return dict(data, waited_s=waited)
        waited = time.monotonic() - start
        if waited >= wait_s:
            raise LeaseHeld(_held_message(project, cur, wait_s))
        time.sleep(min(poll_s, max(wait_s - waited, 0.01)))


def renew(project, who=None, lease_s=None):
    """After an apply: the lease runs lease_s more seconds from now; lease_s=0 releases it. Returns what the result
    reports: {owner, expires, lease_s} or {released: True}."""
    who = actor(who)
    lease_s = LEASE_S if lease_s is None else float(lease_s)
    if lease_s <= 0:
        release(project, who)
        return {'owner': None, 'released': True, 'lease_s': lease_s}
    with _locked(project) as d:
        now = _now()
        prev = lease(project) or {}
        data = {'owner': who, 'taken': prev.get('taken') if prev.get('owner') == who else _iso(now),
                'expires': _iso_ms(now + datetime.timedelta(seconds=lease_s)), 'lease_s': lease_s, 'applying': False}
        _write_json(d / 'lease.json', data)
    return {'owner': who, 'expires': data['expires'], 'lease_s': lease_s}


def release(project, who=None, force=False):
    """End `who`'s lease now. Another owner's unexpired lease stays unless force. Returns the lease before."""
    who = actor(who)
    with _locked(project) as d:
        cur = lease(project)
        if not cur:
            return None
        if cur['owner'] != who and not cur['expired'] and not force:
            raise LeaseHeld(f"The lease on {Path(project).name} is held by {cur['owner']!r} until {cur['expires']}, "
                            f"not by {who!r}; not released.")
        _write_json(d / 'lease.json', {})
        return cur


@contextlib.contextmanager
def writing(project, who=None, lease_s=None, wait_s=None):
    """Hold the lease around a write. Yields a dict that ends up as the result's `lease` report."""
    who = actor(who)
    got = take(project, who, lease_s, wait_s)
    report = {'owner': who, 'lease_s': got['lease_s']}
    if got.get('waited_s'):
        report['waited_s'] = got['waited_s']
    ok = False
    try:
        yield report
        ok = True
    finally:
        if ok:
            report.update(renew(project, who, lease_s))
        else:   # a failed write keeps the lease it took (released with lease_s=0) and is no longer applying
            try:
                renew(project, who, lease_s) if (lease_s is not None and float(lease_s) <= 0) else _mark_idle(project, who)
            except Exception:  # noqa: BLE001 - never hide the write's own error
                pass


def _mark_idle(project, who):
    with _locked(project) as d:
        data = _read_json(d / 'lease.json', {})
        if data.get('owner') == who:
            data['applying'] = False
            _write_json(d / 'lease.json', data)


# ---------------------------------------------------------------------------- track owners

def owners(project):
    """{track name: {owner, since, by}}"""
    return _read_json(folder(project) / 'tracks.json', {})


def set_owner(project, track, owner, who=None, force=False):
    """Record (owner) or clear (owner=None) the owner of a track. A track owned by someone else than `who` is
    refused unless force. Returns the owners."""
    who = actor(who)
    with _locked(project) as d:
        data = _read_json(d / 'tracks.json', {})
        cur = data.get(track)
        if cur and cur.get('owner') != who and not force:
            raise TrackOwned(f"Track {track!r} is owned by {cur['owner']!r} (since {cur.get('since')}); "
                             f"{who!r} can't change its owner.")
        if owner:
            data[track] = {'owner': str(owner), 'since': _iso(_now()), 'by': who}
        else:
            data.pop(track, None)
        _write_json(d / 'tracks.json', data)
        return data


def owner_requests(ops):
    """[(track, owner or None)] from track / add_track ops that carry an `owner` field."""
    out = []
    for o in ops or []:
        if isinstance(o, dict) and o.get('op') in ('track', 'add_track') and 'owner' in o and o.get('name'):
            out.append((o['name'], o['owner'] or None))
    return out


def _sig(obj):
    return json.dumps(obj, sort_keys=True, default=str)


def _track_sigs(script):
    """{track or caption-track name: signature} ignoring positions, pins and gap lengths (what ripple alone moves)."""
    keep = lambda it: {k: v for k, v in it.items() if k not in ('at', 'len', 'from', 'said', 'recorded', 'pin')}
    out = {}
    for t in (script or {}).get('tracks', []):
        fields = {k: v for k, v in t.items() if k not in ('items', 'partial', 'said')}
        items = [keep(it) for it in t.get('items', []) if not (isinstance(it, dict) and set(it) <= {'gap'})]
        out[t['name']] = _sig([fields, items])
    for c in (script or {}).get('captions', []) or []:
        out[f"captions:{c.get('track')}"] = _sig(c)
    return out


def changed_tracks(before, after):
    """Names of tracks (and caption tracks, by their track name) whose clips, clip settings or track settings differ
    between two scripts. Position and gap changes alone do not count."""
    a, b = _track_sigs(before), _track_sigs(after)
    names = set()
    for k in set(a) | set(b):
        if a.get(k) != b.get(k):
            names.add(k.split(':', 1)[1] if k.startswith('captions:') else k)
    return names


def blocked_by(project, who):
    """Owned tracks whose owner is not `who` (empty when nothing can be refused)."""
    who = actor(who)
    return {t: o for t, o in owners(project).items() if o.get('owner') and o['owner'] != who}


def check(project, who, before=None, after=None, requests=()):
    """Raise TrackOwned when `who` changes, or re-owns, a track owned by another actor."""
    who = actor(who)
    others = blocked_by(project, who)
    if not others:
        return
    problems = []
    for track, _ in requests:
        if track in others:
            o = others[track]
            problems.append(f"track {track!r} is owned by {o['owner']!r} (since {o.get('since')}); "
                            f"its owner can change or clear that")
    if before is not None and after is not None:
        for track in sorted(changed_tracks(before, after)):
            if track in others and not any(track == r[0] for r in requests):
                o = others[track]
                problems.append(f"track {track!r} is owned by {o['owner']!r} (since {o.get('since')}) and this "
                                f"edit changes it")
    if problems:
        raise TrackOwned(f'Not applied ({who!r}): ' + '; '.join(problems) + '. Nothing was changed.')


def save_requests(project, who, requests):
    for track, owner in requests:
        set_owner(project, track, owner, who)


def status(project):
    """{lease, track_owners, journal} for reading."""
    d = folder(project)
    return {'lease': lease(project), 'track_owners': owners(project),
            'journal': str(d / 'journal.md') if (d / 'journal.md').exists() else None}
