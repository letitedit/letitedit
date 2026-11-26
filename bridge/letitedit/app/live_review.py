"""Live Review's helpers (T53): the app's Review window keeps the AI's work on a copy of the project while the person
watches, and brings the changes into the open window when they are ready, one Undo step per note.

Called by the app as `python live_review.py <command> ...`, one JSON object on stdout. The folder of a session is
<project stem>.letitedit/review/live: work.mlt (the copy the AI changes), watched.mlt (what the window shows),
after-<note>.mlt (the copy after each finished note), reports/note-<note>.json (what the AI said about a note,
written by letitedit_review_note) and active.json (present while the AI works on a note: the open project then refuses
edits, so nothing changes under the person's eyes).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

STATES = ('done', 'could_not', 'not_an_edit')
ACTIVE_MAX_S = 6 * 3600     # a marker older than this was left by something that ended without tidying up


def live_dir(project):
    p = Path(project)
    return p.parent / f'{p.stem}.letitedit' / 'review' / 'live'


def _pid_alive(pid):
    if not pid:
        return False
    if sys.platform != 'win32':
        try:
            os.kill(int(pid), 0)
        except OSError:
            return False
        return True
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x1000, False, int(pid))     # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
    kernel.CloseHandle(handle)
    return bool(ok) and code.value == 259     # STILL_ACTIVE


def guard(project):
    """Raises ValueError when the AI is working on a Live Review note of this project: the person is watching it, so its
    edits go on the working copy. A marker from a program that has gone counts for nothing."""
    marker = live_dir(project) / 'active.json'
    try:
        active = json.loads(marker.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return
    if time.time() - float(active.get('since') or 0) > ACTIVE_MAX_S or not _pid_alive(active.get('pid')):
        return
    raise ValueError(f"The person is watching this project in Live Review, so it isn't changed now. Make this change on "
                     f"the working copy: project=\"{active.get('work')}\".")


# ------------------------------------------------------------------ the AI says what became of a note

def report(project, note, state, what='', why=''):
    """letitedit_review_note: kept beside the working copy, read by the app when the AI's turn ends."""
    work = Path(project)
    if not (work.parent / 'session.json').exists():
        raise ValueError(f'{work} is not a Live Review working copy.')
    if state not in STATES:
        raise ValueError(f"state is one of {', '.join(STATES)}, not {state!r}.")
    if state == 'could_not' and not (why or '').strip():
        raise ValueError("state 'could_not' takes why: what stopped it, in plain words.")
    folder = work.parent / 'reports'
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f'note-{int(note)}.json'
    temp = out.with_suffix('.tmp')
    body = {'note': int(note), 'state': state, 'what': (what or '').strip(), 'why': (why or '').strip(),
            'time': time.time()}
    temp.write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, out)
    return {'recorded': body}


# ------------------------------------------------------------------ moments

def begin(instance, folder):
    """The window's timeline as it is now (unsaved changes included) becomes the working copy and what is being watched."""
    import letitedit.app.live_edit as live_edit
    snap, _rev = live_edit.snapshot(instance)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'reports').mkdir(exist_ok=True)
    for name in ('work.mlt', 'base.mlt', 'watched.mlt'):
        shutil.copy2(snap, folder / name)
    return {'ok': True, 'work': str(folder / 'work.mlt')}


def _at(script, t):
    """(item, start, end) of the main picture track under time t, else None."""
    from letitedit.timeline.edit_sync import layout, main_track
    track = main_track(script)
    if not track:
        return None
    rows = layout(track)
    for it, s, e in rows:
        if s <= t < e:
            return it, s, e
    return rows[-1] if rows and t >= rows[-1][2] else None


def moment(watched, work, frame, fps):
    """A note's moment on the version being watched, tied to its clip and source time, and where that is on the working
    copy now that earlier notes may have changed the timing. now_s None: that moment isn't in the working copy any more."""
    import letitedit.timeline.edit_script as es
    from letitedit.timeline.edit_sync import layout, main_track
    t = float(frame) / float(fps)
    before, after = es.read(watched), es.read(work)
    hit = _at(before, t)
    out = {'watched_s': round(t, 3), 'clip': None, 'source_s': None, 'now_s': round(t, 3)}
    if not hit:
        return out
    it, s, _e = hit
    speed = float(it.get('speed', 1.0) or 1.0)
    source = float(it['in']) + (t - s) * speed if 'in' in it else None
    out.update(clip=it.get('id'), source_s=round(source, 3) if source is not None else None)
    track = main_track(after)
    for other, s2, _e2 in layout(track) if track else []:
        if other.get('id') != it.get('id') or 'in' not in other or source is None:
            if other.get('id') == it.get('id') and source is None:
                out['now_s'] = round(s2 + (t - s), 3)
                return out
            continue
        a, b = float(other['in']), float(other['out'])
        if a <= source <= b:
            out['now_s'] = round(s2 + (source - a) / float(other.get('speed', 1.0) or 1.0), 3)
            return out
    # the clip was cut, or its ids changed: the same source time in any clip of that file
    clip = it.get('clip')
    for other, s2, _e2 in layout(track) if track else []:
        if clip and other.get('clip') == clip and source is not None and float(other['in']) <= source <= float(other['out']):
            out['now_s'] = round(s2 + (source - float(other['in'])) / float(other.get('speed', 1.0) or 1.0), 3)
            return out
    out['now_s'] = None
    return out


def _signature(it):
    return {k: v for k, v in it.items() if k not in ('at', 'said', 'recorded')}


def first_change(before, after):
    """Seconds into `after` where it first differs from `before`; 0 for a change that isn't at a place in time."""
    from letitedit.timeline.edit_sync import layout
    best = None
    tracks = {t['name']: t for t in before.get('tracks', [])}
    for t in after.get('tracks', []):
        old = tracks.get(t['name'])
        new_rows = layout(t)
        old_rows = layout(old) if old else []
        for i, (it, s, _e) in enumerate(new_rows):
            if i >= len(old_rows) or _signature(old_rows[i][0]) != _signature(it) or abs(old_rows[i][1] - s) > 0.001:
                best = s if best is None else min(best, s)
                break
        else:
            if len(old_rows) > len(new_rows):
                end = new_rows[-1][2] if new_rows else 0.0
                best = end if best is None else min(best, end)
    cues = {c['track']: c['cues'] for c in before.get('captions', [])}
    import letitedit.timeline.edit_script as es
    for c in after.get('captions', []):
        old = cues.get(c['track']) or []
        for i, q in enumerate(c['cues']):
            if i >= len(old) or old[i] != q:
                s = es.to_seconds(q['start'])
                best = s if best is None else min(best, s)
                break
    return round(best, 3) if best is not None else 0.0


def _map(before, after, t):
    """A time on one version of the timeline on a later one (through the main track's source times), else t."""
    from letitedit.timeline.edit_sync import mapper
    try:
        m = mapper(before, after)
        got = m(t) if m else None
    except Exception:  # noqa: BLE001 - a place to jump to is a convenience
        got = None
    return round(got if got is not None else t, 3)


def _started_by_window(instance):
    """True when that letitedit window started this process: its own button, not an AI session or a script."""
    import letitedit.app.letitedit_instances as inst
    import letitedit.core.render_lock as render_lock
    row = next((r for r in inst.list_instances() if r.get('instance_id') == instance), None)
    pid = int((row or {}).get('pid') or 0)
    return bool(pid) and pid in render_lock.ancestors()


def land_from_app(instance, plan_file):
    """The app's call: the person's own edit through their window, so an AI session that has edited this window (their
    chat's AI, on any other work) keeps its ownership and doesn't stand in the way. Only for the window that started this."""
    import letitedit.app.letitedit_instances as inst
    if not _started_by_window(instance):
        raise RuntimeError(f"Bringing Live Review's changes in is the letitedit window's own job, and window {instance} "
                           f"did not start this command; nothing was changed.")
    with inst.scope(instance), inst.app_edit():
        return land(instance, plan_file)


def land(instance, plan_file):
    """Each finished note, in order, into the open window as one Undo step. Stops at the first that can't go in."""
    import letitedit.timeline.edit_script as es
    import letitedit.app.live_edit as live_edit
    import letitedit.timeline.project_journal as pj
    plan = json.loads(Path(plan_file).read_text(encoding='utf-8-sig'))
    project, steps = plan.get('project'), []
    snap, _ = live_edit.snapshot(instance)
    previous = es.read(snap)
    t_all = time.time()
    kept = None
    for note in plan['notes']:
        t0 = time.time()
        after = es.read(note['after'])
        at = first_change(previous, after)
        try:
            result = live_edit.land(instance, note['after'], note['label'])
        except ValueError:     # a change to the order of the tracks, or a whole track hidden or muted
            steps.append({'id': note['id'], 'ok': False, 'seconds': round(time.time() - t0, 2),
                          'error': "it changed the tracks in a way that can't come in while the video is open"})
            break
        except Exception as e:  # noqa: BLE001 - whatever stops it is said on the note, in its own words
            steps.append({'id': note['id'], 'ok': False, 'error': str(e), 'seconds': round(time.time() - t0, 2)})
            break
        if project and result.get('changes'):
            pj.record(Path(project), 'apply', 'person', note['label'], [], where=f'letitedit window {instance}')
        if kept is None and plan.get('base') and project:
            # the video as it was, kept once per round as an earlier version (Versions of This Video)
            kept = keep_version(project, plan['base'])
        steps.append({'id': note['id'], 'ok': True, 'first_change_s': at, 'seconds': round(time.time() - t0, 2),
                      'nothing': not result.get('changes')})
        previous = after
    # where each change is on the version that was loaded
    for step, note in zip(steps, plan['notes']):
        if step.get('ok'):
            step['final_s'] = _map(es.read(note['after']), previous, step['first_change_s'])
    if steps and steps[-1].get('ok'):
        snap, _ = live_edit.snapshot(instance)
        shutil.copy2(snap, Path(plan['folder']) / 'watched.mlt')
    return {'ok': all(s.get('ok') for s in steps), 'steps': steps, 'seconds': round(time.time() - t_all, 2),
            'kept': kept, 'first_change_s': min((s['final_s'] for s in steps if s.get('ok')), default=0.0)}


def keep_version(project, base):
    """<name> vN.mlt beside the project (as Review's Send does): what the video was before this round's changes."""
    p = Path(project)
    stem = re.sub(r' v\d+$', '', p.stem)
    numbers = [int(m.group(1)) for f in p.parent.glob(f'{stem} v*.mlt')
               if (m := re.fullmatch(re.escape(stem) + r' v(\d+)', f.stem))]
    out = p.parent / f'{stem} v{max(numbers, default=0) + 1}.mlt'
    shutil.copy2(base, out)
    return str(out)


# ------------------------------------------------------------------ the video's own sound in the microphone

def video_words(project):
    """The words said on the timeline, from transcripts already made (nothing is transcribed here)."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.timeline_speech as timeline_speech
    words = timeline_speech.timeline_words(es.read(project), cached_only=True)
    return [{'w': w['w'], 's': w['t0'], 'e': w['t1']} for w in words]


_WORD = re.compile(r"[^\w']+", re.UNICODE)


def _norm(text):
    return _WORD.sub('', str(text).lower())


def clean(note_words, video, ranges, margin=3.0, run=3):
    """Words of a note that are the video's own sound coming through the speakers, and what's left.

    note_words: [{'w', ...}] in order; video: the timeline's words [{'w','s','e'}]; ranges: [[start_s, end_s], ...] of the
    video on screen during the note. Runs of `run` or more words in the same order as the video's words at that moment are
    taken out. heard_video: nothing that reads as the person's own words is left (at most two words)."""
    said = [_norm(w.get('w')) for w in note_words]
    near = [_norm(w['w']) for w in video
            if any(float(w['s']) >= a - margin and float(w['e']) <= b + margin for a, b in ranges)]
    said_keep = [True] * len(said)
    matched = 0
    if said and near:
        blocks = SequenceMatcher(None, said, near, autojunk=False).get_matching_blocks()
        for b in blocks:
            if b.size >= run:
                matched += b.size
                for i in range(b.a, b.a + b.size):
                    said_keep[i] = False
    kept = [w for w, k in zip(note_words, said_keep) if k]
    left = sum(1 for w in kept if _norm(w.get('w')))
    return {'words': kept, 'text': ' '.join(str(w.get('w', '')).strip() for w in kept).strip(), 'matched': matched,
            'total': len(said), 'heard_video': matched > 0 and left <= 2}


def _cli(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('begin')
    p.add_argument('--instance', required=True)
    p.add_argument('--folder', required=True)
    p = sub.add_parser('moment')
    p.add_argument('--watched', required=True)
    p.add_argument('--work', required=True)
    p.add_argument('--frame', type=float, required=True)
    p.add_argument('--fps', type=float, required=True)
    p = sub.add_parser('land')
    p.add_argument('--instance', required=True)
    p.add_argument('--plan', required=True)
    p = sub.add_parser('words')
    p.add_argument('--project', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('clean')
    p.add_argument('--note', required=True)    # a JSON file: {"words": [...], "ranges": [[s, e], ...]}
    p.add_argument('--video', required=True)   # the file `words` wrote
    a = ap.parse_args(argv)
    if a.cmd == 'begin':
        return begin(a.instance, a.folder)
    if a.cmd == 'moment':
        return moment(a.watched, a.work, a.frame, a.fps)
    if a.cmd == 'land':
        return land_from_app(a.instance, a.plan)
    if a.cmd == 'words':
        words = video_words(a.project)
        Path(a.out).write_text(json.dumps(words, ensure_ascii=False), encoding='utf-8')
        return {'ok': True, 'count': len(words)}
    note = json.loads(Path(a.note).read_text(encoding='utf-8-sig'))
    video = json.loads(Path(a.video).read_text(encoding='utf-8-sig'))
    return clean(note.get('words') or [], video, note.get('ranges') or [])


if __name__ == '__main__':
    import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (no console windows, so nothing takes the keyboard focus)
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        print(json.dumps(_cli(), ensure_ascii=False))
    except Exception as e:  # noqa: BLE001 - the app shows the reason in plain words
        print(str(e), file=sys.stderr)
        sys.exit(1)
