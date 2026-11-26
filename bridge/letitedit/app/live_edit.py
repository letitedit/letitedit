"""Apply edit-script changes straight into an open letitedit window as one native, undoable step.

Works on the window's current state (unsaved changes included): the live timeline is read through the bridge,
the edits are compiled against it, and only the tracks that changed are swapped in by the app's
`replace_tracks` command, labelled e.g. "Claude: tighten talk". Ctrl+Z in Shotcut undoes it. Edits that also add
or remove tracks (new video tracks on top, new audio tracks at the end), add caption tracks, change track or
whole-video effects, or set the project's Look ({op: look}: its letitedit_ai:look property, through
`project_properties`) go through the app's `apply_transaction`: still one undo step, still no save or reload.
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import letitedit.timeline.edit_script as es
from letitedit.timeline.edit_sync import main_track, resync

LIVE = es.HISTORY.parent / 'live'


def _bridge(instance_id):
    import letitedit.app.letitedit_instances as inst
    from letitedit.app.letitedit_client import ShotcutBridge
    class Ctx:
        def __enter__(self):
            self.s = inst.scope(instance_id)
            self.s.__enter__()
            self.b = ShotcutBridge(timeout=120).connect()
            return self.b
        def __exit__(self, *exc):
            self.b.close()
            self.s.__exit__(*exc)
    return Ctx()


def snapshot(instance_id):
    """Write the window's current timeline (with unsaved changes) to a file and return (path, revision)."""
    import letitedit.timeline.letitedit_extras as extras
    with _bridge(instance_id) as b:
        state = b.call('state')
        xml = b.call('project_xml')
        rev = b.call('live_context').get('revision')
    if not isinstance(xml, str):
        xml = xml.get('xml', '')
    prof = state.get('profile') or {}
    xml = extras.inject_profile(xml, {'width': prof.get('width', 1920), 'height': prof.get('height', 1080), 'fps': prof.get('fps', 30)})
    LIVE.mkdir(parents=True, exist_ok=True)
    path = LIVE / f'live-{instance_id}-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:4]}.mlt'
    path.write_text(xml, encoding='utf-8')
    return path, rev


def window_for(path):
    """The letitedit window that has this project open: its row from letitedit_instances.list_instances()
    ({'instance_id', 'project', 'modified', ...}), or None (no window has it open, or no editor runs)."""
    try:
        import letitedit.app.letitedit_instances as inst
        rows = inst.list_instances()
        want = Path(path).resolve()
    except Exception:  # noqa: BLE001 - no editor running is normal
        return None
    for r in rows:
        proj = r.get('project')
        try:
            if proj and Path(proj).resolve() == want:
                return r
        except OSError:
            continue
    return None


def state_of(row, revision=None):
    """What a reply says it read (T298): {'state': 'live', 'window', 'unsaved_changes', 'revision'} for an open
    window's row, {'state': 'saved'} for None."""
    if not row:
        return {'state': 'saved'}
    out = {'state': 'live', 'window': row['instance_id'], 'unsaved_changes': bool(row.get('modified'))}
    if revision:
        out['revision'] = revision
    return out


def current(project):
    """The project as every tool reads it (T298): (file, state). A .mlt path that is open in a letitedit window is
    that window's timeline now, unsaved changes included, written to a snapshot file; else `project` itself, as given
    (the saved file). state is state_of's dict, plus 'project' (the saved file's path)."""
    row = window_for(project)
    if not row:
        return project, {**state_of(None), 'project': str(project)}
    snap, rev = snapshot(row['instance_id'])
    return snap, {**state_of(row, rev), 'project': str(row.get('project') or project)}


def read(project, **kw):
    """es.read of the project as every tool reads it (current), with 'project' the saved path and 'read' saying
    which state was read ('read'). kw goes to es.read (start_s, end_s, tracks)."""
    source, state = current(project)
    script = es.read(source, **kw)
    if state['state'] == 'live':
        script['project'] = state['project']
    script['read'] = {k: v for k, v in state.items() if k != 'project'}
    return script


STUDIO_PREFIX = 'studio-'   # the Studio's own hidden windows (studio/window.py instance_name); never a person's


SAVE_TIMEOUT_S = 30     # a project saves in well under a second; an older build's error box never answers
SAVE_RETRY_S = 1.0
SAVE_BOX_POLL_S = 0.5
# A cause that may pass by itself (a file another program holds for a moment, a window still busy): tried once more.
_PASSING = ('held open', 'being used', 'sharing violation', 'access is denied', 'permission denied',
            'could not replace', 'did not answer', 'timed out', 'timeout', 'still opening', 'busy')
_SAVE_BOX = 'error saving'   # an older build's modal box: "There was an error saving. Please try again."


def _passing(why):
    return any(p in str(why or '').lower() for p in _PASSING)


def file_holders(path):
    """The programs that have `path` open now, as Windows' Restart Manager (part of Windows) lists them:
    [{'pid', 'name', 'program'}], 'this' marking this process. [] when none, off Windows, or when it can't tell."""
    import os
    if os.name != 'nt':
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class _Unique(ctypes.Structure):
            _fields_ = [('pid', wintypes.DWORD), ('started', wintypes.FILETIME)]

        class _Info(ctypes.Structure):
            _fields_ = [('process', _Unique), ('app', ctypes.c_wchar * 256), ('service', ctypes.c_wchar * 64),
                        ('kind', ctypes.c_int), ('status', wintypes.ULONG), ('session', wintypes.DWORD),
                        ('restartable', wintypes.BOOL)]

        rm = ctypes.WinDLL('rstrtmgr')
        k32 = ctypes.WinDLL('kernel32')
        k32.OpenProcess.restype = wintypes.HANDLE
        session, key = wintypes.DWORD(), ctypes.create_unicode_buffer(64)
        if rm.RmStartSession(ctypes.byref(session), 0, key):
            return []
        try:
            files = (ctypes.c_wchar_p * 1)(str(path))
            if rm.RmRegisterResources(session, 1, files, 0, None, 0, None):
                return []
            needed, count, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
            got = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons))
            if got not in (0, 234) or not needed.value:     # 234: more data (the list's size is in needed)
                return []
            infos = (_Info * needed.value)()
            count = wintypes.UINT(needed.value)
            if rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reasons)):
                return []
            out = []
            for info in infos[:count.value]:
                pid, program = int(info.process.pid), ''
                handle = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
                if handle:
                    buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                        program = buf.value
                    k32.CloseHandle(handle)
                row = {'pid': pid, 'name': info.app or Path(program).name, 'program': program}
                if pid == os.getpid():
                    row['this'] = True
                out.append(row)
            return out
        finally:
            rm.RmEndSession(session)
    except Exception:  # noqa: BLE001 - naming the holder is extra detail; the failure is reported without it
        return []


def holders_text(path):
    """'held open now by python.exe (pid 123, this tool server), …' for a failed replace, or ''."""
    rows = file_holders(path)
    if not rows:
        return ''
    named = [f"{Path(r['program']).name or r['name']} (pid {r['pid']}{', this tool server' if r.get('this') else ''})"
             for r in rows]
    return 'held open now by ' + ', '.join(named)


def _close_save_box(instance_id):
    """An older build opens a modal error box in the window when a save fails; in the Studio's own window nobody is
    there to close it. Press its OK (only while the save call that opened it still waits). Returns True when one was
    closed."""
    try:
        with _bridge(instance_id) as b:
            b.timeout = 10
            dialog = (b.call('state') or {}).get('dialog') or {}
            if _SAVE_BOX in str(dialog.get('text') or '').lower():
                b.call('dialog_button', {'button': 'OK'})
                return True
    except Exception:  # noqa: BLE001 - best effort; the failure itself is reported by the caller
        pass
    return False


def _watch_for_save_box(instance_id, stop, closed):
    """While a save call waits: an older build's error box opens inside that call, which then answers only once the
    box is closed. Close it from a second connection while the call still waits (closed after the call gave up, the
    window loses the call's connection mid-reply)."""
    while not stop.wait(SAVE_BOX_POLL_S):
        if _close_save_box(instance_id):
            closed.set()
            return


def own_save(row, path, who=None):
    """After an AI edit lands in a window: the Studio's own hidden window (a run's, never a person's) saves into its
    project, so a tool that still reads the saved file sees the same timeline (T298). A person's window is never
    saved. Returns {} (not the Studio's own window, or it shows another project), {'saved': path}, or, when the save
    failed (the edit stands in the window), {'save_failed': why, 'tries': n}: a cause that may pass is tried once
    more, and a failure is written in the project's journal and on stderr, never silent."""
    if not row or not str(row.get('instance_id') or '').startswith(STUDIO_PREFIX):
        return {}
    instance = row['instance_id']
    why, tries = None, 0
    for tries in (1, 2):
        stop, closed = threading.Event(), threading.Event()
        try:
            with _bridge(instance) as b:
                b.timeout = SAVE_TIMEOUT_S
                shown = (b.call('state') or {}).get('project')
                if not shown or Path(shown).resolve() != Path(path).resolve():
                    return {}
                watcher = threading.Thread(target=_watch_for_save_box, args=(instance, stop, closed), daemon=True)
                watcher.start()
                try:
                    got = b.call('save', {'path': str(path)}) or {}
                finally:
                    stop.set()
                    watcher.join(timeout=15)
                return {'saved': got.get('saved') or str(path)}
        except Exception as exc:  # noqa: BLE001 - the reason is reported below
            why = str(exc) or type(exc).__name__
        boxed = closed.is_set()     # a box still open after the call gave up stays: closing it then ends the window
        if boxed:
            why += ' (an older letitedit build showed its error box; it was closed)'
        if tries == 1 and (boxed or _passing(why)):
            time.sleep(SAVE_RETRY_S)
            continue
        break
    why = why[:400]
    if 'could not replace' in why.lower() or 'held open' in why.lower():   # T341: which program holds it, by name
        held = holders_text(path)
        if held:
            why = f'{why}; {held[:300]}'
    out = {'save_failed': why, 'tries': tries}
    import sys
    print(f"letitedit: the window {instance} could not save {path} ({tries} tries): {why}", file=sys.stderr)
    try:
        import letitedit.timeline.project_journal as pj
        pj.record(path, 'save_failed', who, text=f"the window could not save the project ({tries} tries): {why}",
                  where=f"letitedit window {instance}")
    except Exception:  # noqa: BLE001 - the reply still says it
        pass
    return out


def save_if_own(row, path, who=None):
    """own_save's saved path, or None (not the Studio's window, or the save failed: reported by own_save)."""
    return own_save(row, path, who).get('saved')


def save_note(saved):
    """A reply's line for own_save's result when the save failed, else None."""
    if not saved.get('save_failed'):
        return None
    return ("The edit is in the window, but saving the window's project failed: "
            f"{saved['save_failed']}. Tools that read the saved file see the cut before this edit until it saves.")


def set_markers(instance_id, markers, label):
    """Put the timeline's whole marker list into the open window as one undo step (the editor's set_markers, builds
    since T298): markers [{text, start, end, color}] in frames. Raises ValueError when the window's build doesn't
    have it."""
    with _bridge(instance_id) as b:
        try:
            return b.call('set_markers', {'label': label, 'markers': markers})
        except Exception as exc:  # noqa: BLE001 - an older build
            if 'unknown' in str(exc).lower() or 'not supported' in str(exc).lower():
                raise ValueError("this letitedit build can't take markers into an open window") from exc
            raise


def _graphics_home(instance_id):
    """Graphics for an open project are rendered next to its saved file (not next to the live snapshot)."""
    try:
        with _bridge(instance_id) as b:
            proj = (b.call('state') or {}).get('project')
    except Exception:  # noqa: BLE001
        proj = None
    return Path(proj).parent / 'graphics' if proj else LIVE / 'graphics'


def _track_doc(doc, playlist):
    """Standalone MLT document whose root producer is `playlist`, with everything it references."""
    needed, order = set(), []
    def visit(pid):
        if pid in needed or pid not in doc.elements:
            return
        el = doc.elements[pid]
        for child in el.iter():
            if child.tag in ('entry', 'track') and child is not el:
                visit(child.get('producer'))
        needed.add(pid)
        order.append(el)
    for e in playlist.findall('entry'):
        visit(e.get('producer'))
    root = ET.Element('mlt', {'LC_NUMERIC': 'C', 'producer': playlist.get('id')})
    root.append(copy.deepcopy(doc.root.find('profile')))
    for el in order:
        root.append(copy.deepcopy(el))
    root.append(copy.deepcopy(playlist))
    return ET.tostring(root, encoding='unicode')


def _structure(script):
    return [(t['name'], t.get('kind'), t.get('hide')) for t in script['tracks']]


def _filters_of(elem):
    """The effects on a tractor or playlist as [{property: value}], the way the app's apply_transaction takes them:
    captions and the engine's own (_loader) filters left out, internal (_) properties dropped."""
    out = []
    for f in elem.findall('filter'):
        props = {p.get('name'): (p.text or '') for p in f.findall('property')}
        if props.get('mlt_service') in ('subtitle_feed', 'subtitle') or props.get('_loader') == '1':
            continue
        for attr in ('in', 'out'):
            if f.get(attr) is not None:
                props.setdefault(attr, f.get(attr))
        out.append({k: v for k, v in props.items() if k and not k.startswith('_')})
    return out


def _has_layer(track):
    # an adjustment layer, or a multicam op's angle clips (they go just above the main track, under any overlays)
    return any(it.get('adjust') or isinstance(it.get('multicam'), dict) for it in track.get('items') or [])


def _layer_spots(before, after):
    """{new track: the track just below it} for new video tracks holding an adjustment layer in the middle of the stack. An
    adjustment layer's place in the stack is what it does, so this one goes in live."""
    video = [t for t in after['tracks'] if t.get('kind', 'video') == 'video']
    names = {t['name'] for t in before['tracks']}
    return {t['name']: video[i - 1]['name'] for i, t in enumerate(video)
            if t['name'] not in names and _has_layer(t) and 0 < i < len(video) - 1}


def _shape(before, after, spots=None):
    """(added [(name, kind)], removed [name]) when the new track list can be made live: existing tracks keep their
    order and hide state, new video tracks go above the existing ones and new audio tracks after them (where the app
    adds tracks), except `spots` (_layer_spots), which go where they are asked. Anything else raises ValueError (it needs a
    saved project)."""
    if spots:
        after = {**after, 'tracks': [t for t in after['tracks'] if t['name'] not in spots]
                 + [t for t in after['tracks'] if t['name'] in spots]}
    b = [(t['name'], t.get('kind') or 'video', t.get('hide')) for t in before['tracks']]
    a = [(t['name'], t.get('kind') or 'video', t.get('hide')) for t in after['tracks']]
    nb, na = {x[0] for x in b}, {x[0] for x in a}
    added = [x for x in a if x[0] not in nb]
    removed = [x[0] for x in b if x[0] not in na]
    keep = [x for x in b if x[0] in na]
    video = lambda xs: [x[:2] for x in xs if x[1] == 'video']          # noqa: E731
    audio = lambda xs: [x[:2] for x in xs if x[1] != 'video']          # noqa: E731
    if (video(a) != video(keep) + video(added) or audio(a) != audio(keep) + audio(added)
            or [x for x in a if x[0] in nb] != keep):
        raise ValueError('These changes reorder tracks, insert a video track below another or change a track\'s '
                         'hide/mute state, which can only be applied to a saved project. Ask the user to save in '
                         'Shotcut, then apply again (the window will reload).')
    return [(x[0], 'audio' if x[1] == 'audio' else 'video') for x in added], removed


def _sets_project_properties(instance_id):
    """Whether the window's build takes apply_transaction's project_properties (builds since 2026-10-29 .7 report the
    project's style in `state`; older ones don't know either)."""
    with _bridge(instance_id) as b:
        state = b.call('state') or {}
        return 'look' in state or 'style' in state


def _knows_caption_styles(instance_id):
    """Whether the window's build takes apply_transaction's caption_styles (how a caption track is drawn); an older
    one ignores them, so a style change must not be sent to it."""
    with _bridge(instance_id) as b:
        return bool((b.call('state') or {}).get('caption_styles'))


def _knows_layers(instance_id):
    with _bridge(instance_id) as b:
        return bool((b.call('state') or {}).get('adjust_layers'))


def land(instance_id, source, label):
    """Bring a finished timeline file (Live Review's copy after a note) into the open window as one undo step, the way
    `apply` puts in a compiled edit. Raises ValueError for what can't go in live (`_shape`)."""
    base, revision = snapshot(instance_id)
    before = es.read(base)
    after = es.read(source)
    new = es.Doc(source)
    engine = lambda sc: {t['name']: [e for e in t.get('effects') or [] if not es.made.is_fx(e)] for t in sc['tracks']}
    style = (after.get('look') or None) if (before.get('look') or None) != (after.get('look') or None) else False
    hook = (after.get('hook') or None) if (before.get('hook') or None) != (after.get('hook') or None) else False
    structure = lambda sc: sorted(_structure(sc), key=lambda x: x[0])
    transaction = (structure(before) != structure(after) or before.get('master') != after.get('master')
                   or engine(before) != engine(after) or style is not False or hook is not False)
    spots = {}
    if transaction and _knows_layers(instance_id):
        # any new video track in the middle of the stack goes in where it is (a scene behind the person, a layer)
        video = [t for t in after['tracks'] if t.get('kind', 'video') == 'video']
        names = {t['name'] for t in before['tracks']}
        spots = {t['name']: video[i - 1]['name'] for i, t in enumerate(video)
                 if t['name'] not in names and 0 < i < len(video) - 1}
    # the window may list a new video track after the audio tracks; only the order within video and within audio means anything
    in_window = {t['name']: i for i, t in enumerate(before['tracks'])}
    shaped = {**after, 'tracks': sorted(after['tracks'], key=lambda t: (t['name'] not in in_window, in_window.get(t['name'], 0)))}
    video_order = lambda sc: [t['name'] for t in sc['tracks'] if t.get('kind', 'video') == 'video' and t['name'] in in_window]
    audio_order = lambda sc: [t['name'] for t in sc['tracks'] if t.get('kind', 'video') != 'video' and t['name'] in in_window]
    if video_order(after) != video_order(shaped) or audio_order(after) != audio_order(shaped):
        shaped = after     # they really did change order: _shape says so
    added, removed = _shape(before, shaped, spots) if transaction else ([], [])
    new_names = {n for n, _ in added}
    payload, track_filters = [], []
    strip = lambda items: [{k: v for k, v in it.items() if k not in ('at', 'said', 'recorded')} for it in items]
    for _tr, pl, name, _kind in new.tracks():
        if name in new_names:
            payload.append({'name': name, 'xml': _track_doc(new, pl)})
            if _filters_of(pl):
                track_filters.append({'name': name, 'filters': _filters_of(pl)})
            continue
        before_t = next(t for t in before['tracks'] if t['name'] == name)
        after_t = next(t for t in after['tracks'] if t['name'] == name)
        if strip(before_t['items']) != strip(after_t['items']) or before_t.get('effects') != after_t.get('effects'):
            payload.append({'name': name, 'xml': _track_doc(new, pl)})
        if transaction and engine(before).get(name) != engine(after).get(name):
            track_filters.append({'name': name, 'filters': _filters_of(pl)})
    caps = []
    cb = {c['track']: c['cues'] for c in before.get('captions', [])}
    for c in after.get('captions', []):
        if cb.get(c['track']) != c['cues']:
            entry = {'track': c['track'], 'cues': [{'start_ms': round(es.to_seconds(q['start']) * 1000),
                                                    'end_ms': round(es.to_seconds(q['end']) * 1000), 'text': q['text']}
                                                   for q in sorted(c['cues'], key=lambda q: es.to_seconds(q['start']))]}
            if c['track'] not in cb:
                entry.update(create=True, lang=c.get('lang') or 'eng')
            caps.append(entry)
    master = transaction and before.get('master') != after.get('master')
    if not payload and not caps and not added and not removed and not track_filters and not master \
            and style is False and hook is False:
        return {'changes': [], 'live': True}
    params = {'label': label, 'tracks': payload, 'captions': caps}
    if revision:
        params['expected_revision'] = revision
    if transaction or any(c.get('create') for c in caps):
        params.update(add_tracks=[{'name': n, 'kind': k, **({'above': spots[n]} if n in spots else {})} for n, k in added],
                      remove_tracks=removed, track_filters=track_filters)
        if master:
            params['master_filters'] = _filters_of(new.main)
        if style is not False:
            params['project_properties'] = {es.LOOK_PROP: style}
        if hook is not False:
            params.setdefault('project_properties', {})[es.HOOK_PROP] = hook
        method = 'apply_transaction'
    else:
        method = 'replace_tracks'
    with _bridge(instance_id) as b:
        result = b.call(method, params)
    return {'changes': True, 'live': True, 'undo_label': label, 'bridge': result}


MERGE_TRIES = 3     # an apply that clashes with the window reads it again and goes again, up to this many times in all


def _named_ids(ops):
    """The clip ids a list of ops names (the clips it changes, and the ones it places things next to)."""
    ids = set()
    for o in ops:
        if not isinstance(o, dict):
            continue
        for key in ('id', 'after', 'before'):
            if isinstance(o.get(key), str):
                ids.add(o[key])
        ids.update(i for i in o.get('ids') or [] if isinstance(i, str))
    return ids


def _clips(script, ids):
    """Those clips as the script has them (what they are, not where: a ripple from an edit elsewhere moves them)."""
    out = {}
    for t in script.get('tracks') or []:
        for it in t.get('items') or []:
            if it.get('id') in ids:
                out[it['id']] = {k: v for k, v in it.items() if k not in ('at', 'said', 'recorded')}
    return out


def apply(instance_id, ops, label=None, markers=None):
    """ops by id into the open window as one undo step. The window's timeline can change between this read and the
    edit (the person's own hand edit, or the window's background work): the window then refuses the edit as a clash,
    and it is read again and the same ops go into what is there now, up to MERGE_TRIES times in all. It fails only
    when a clip the ops name was itself changed in between.

    markers (T356, markers that follow their clips): markers(snapshot_file, before, after) -> {'rows', 'moved',
    'removed'} | {'error'} | None, the timeline's whole marker list as the edit leaves it, worked out from the
    window's snapshot and the compiled edit before anything is sent. The rows go into the window's apply_transaction,
    in the edit's own undo step. The reply's `markers_follow` says what happened: 'carried' (in the edit's step;
    `markers_followed` has the receipt), 'none' (nothing moved, or an error in `markers_followed`) or 'not_taken'
    (an older build ignored them: the edit went in without them)."""
    import letitedit.app.letitedit_client as letitedit_client
    seen = {}
    for attempt in range(MERGE_TRIES):
        try:
            result = _apply_once(instance_id, copy.deepcopy(list(ops)), label, seen, markers)
        except letitedit_client.BridgeError as exc:
            if 'Edit conflict' not in str(exc) or attempt == MERGE_TRIES - 1:
                raise
            continue
        if attempt:
            result.setdefault('notes', []).append(
                f'the timeline changed in the window while this edit was being made; it was read again and the edit '
                f'went into it as it is now ({attempt + 1} tries)')
            result['merged'] = attempt
        return result


def _caption_styles(before, after, new):
    """[{track, filters}] for each caption track already in the window whose style the edit changes: the burn-in
    filters the compiled project draws it with (the text and its shadow copy), which apply_transaction sets in the same
    undo step as the cues. Empty when no style changed."""
    was = {c['track']: c.get('style') or {} for c in before.get('captions', [])}
    out = []
    for c in after.get('captions', []):
        if c['track'] not in was or was[c['track']] == (c.get('style') or {}):
            continue
        filters = []
        for f in new.main.findall('filter'):
            props = {p.get('name'): (p.text or '') for p in f.findall('property')}
            if props.get('mlt_service') == 'subtitle' and props.get('feed') == c['track']:
                filters.append({k: v for k, v in props.items() if k and not k.startswith('_')})
        if filters:
            out.append({'track': c['track'], 'filters': filters})
    return out


def _apply_once(instance_id, ops, label, seen, markers=None):
    base, revision = snapshot(instance_id)
    before = es.read(base)
    named = _named_ids(ops)
    now = _clips(before, named)
    if 'clips' not in seen:
        seen['clips'] = now
    elif now != seen['clips']:
        changed = sorted(i for i in set(now) | set(seen['clips']) if now.get(i) != seen['clips'].get(i))
        raise es.Conflict('Edit conflict: ' + ', '.join(changed) + ' changed in the window while this edit was being '
                          'made. Read the timeline again and make the edit on it as it is now.')
    ops = [dict(o) for o in ops]
    after, notes = es.edit(before, ops)
    style = (after.get('look') or None) if (before.get('look') or None) != (after.get('look') or None) else False
    # the opening a hook swap put in (letitedit_ai:hook): set in the same undo step, so Undo and Redo carry it; a build
    # that can't set project properties simply doesn't get it (its Opening panel doesn't follow Undo either)
    hook = (after.get('hook') or None) if (before.get('hook') or None) != (after.get('hook') or None) else False
    if hook is not False and not _sets_project_properties(instance_id):
        hook = False
    if style is not False and not _sets_project_properties(instance_id):
        # the style pack is a property of the project itself, which this window's build can't set (STYLES.md 5.4): a
        # saved project takes it through the file (the window reloads), an unsaved one must be saved first
        raise ValueError('A style pack choice is stored in the project file, and this letitedit window is an older '
                         'build that can only take it from a saved project. Ask the user to save in letitedit, then '
                         'apply again (the window reloads).')
    engine = lambda sc: {t['name']: [e for e in t.get('effects') or [] if not es.made.is_fx(e)] for t in sc['tracks']}
    # adding/removing tracks, changing track or whole-video effects and the project's style go in as one native
    # transaction
    transaction = (_structure(before) != _structure(after) or before.get('master') != after.get('master')
                   or engine(before) != engine(after) or style is not False or hook is not False)
    spots = _layer_spots(before, after) if transaction else {}
    if spots and not _knows_layers(instance_id):
        spots = {}          # an older build can't put a track in the middle: _shape says so, as for any other such change
    added, removed = _shape(before, after, spots) if transaction else ([], [])
    out = base.with_name(base.stem + '-new.mlt')
    after['base'] = before['base']
    es.compile_script(after, base=base, out=out, graphics_dir=_graphics_home(instance_id))
    notes = list(notes) + after.pop('_render_notes', [])
    frames_at = after.pop('_frames_at', None)
    new = es.Doc(out)
    compiled = es.read(out)
    payload, track_filters = [], []
    new_names = {n for n, _ in added}
    for tr, pl, name, kind in new.tracks():
        after_t = next(t for t in compiled['tracks'] if t['name'] == name)
        if name in new_names:
            payload.append({'name': name, 'xml': _track_doc(new, pl)})
            if _filters_of(pl):
                track_filters.append({'name': name, 'filters': _filters_of(pl)})
            continue
        before_t = next(t for t in before['tracks'] if t['name'] == name)
        strip = lambda items: [{k: v for k, v in it.items() if k not in ('at',)} for it in items]
        if strip(before_t['items']) != strip(after_t['items']) or before_t.get('effects') != after_t.get('effects'):
            payload.append({'name': name, 'xml': _track_doc(new, pl)})
        if transaction and engine(before).get(name) != engine(after).get(name):
            track_filters.append({'name': name, 'filters': _filters_of(pl)})
    caps = []
    cb = {c['track']: c['cues'] for c in before.get('captions', [])}
    for c in after.get('captions', []):
        if cb.get(c['track']) != c['cues']:
            entry = {'track': c['track'], 'cues': [{'start_ms': round(es.to_seconds(q['start']) * 1000),
                                                    'end_ms': round(es.to_seconds(q['end']) * 1000), 'text': q['text']}
                                                   for q in sorted(c['cues'], key=lambda q: es.to_seconds(q['start']))]}
            if c['track'] not in cb:
                entry.update(create=True, lang=c.get('lang') or 'eng')
            caps.append(entry)
    master = transaction and before.get('master') != after.get('master')
    caption_styles = _caption_styles(before, compiled, new)    # read the same way on both sides
    if not payload and not caps and not added and not removed and not track_filters and not master \
            and style is False and hook is False and not caption_styles:
        return {'changes': [], 'notes': notes + ['nothing changed'], 'live': True}
    if not label:
        import letitedit.timeline.project_journal as project_journal
        label = project_journal.label_prefix() + ': ' + ', '.join(sorted({o['op'] for o in ops}))
    params = {'label': label, 'tracks': payload, 'captions': caps}
    if revision:
        params['expected_revision'] = revision
    carried = markers(base, before, compiled) if markers else None
    if carried and carried.get('rows') is not None:
        # the markers as the edit leaves them, in the same undo step (T356): only apply_transaction takes them
        params['markers'] = carried['rows']
        transaction = True
    if caption_styles and not _knows_caption_styles(instance_id):
        raise ValueError("This letitedit window is an older build that can't change how captions are drawn while the "
                         'project is open. Save and close the project in letitedit, then apply (the file takes it), or '
                         'update letitedit.')
    if caption_styles:
        params['caption_styles'] = caption_styles       # how the captions are drawn: in their cues' undo step
    if transaction or caption_styles or any(c.get('create') for c in caps):
        # one native transaction: new and removed tracks, contents, captions (new caption tracks too) and effects
        params.update(add_tracks=[{'name': n, 'kind': k, **({'above': spots[n]} if n in spots else {})} for n, k in added],
                      remove_tracks=removed,
                      track_filters=track_filters)
        if master:
            params['master_filters'] = _filters_of(new.main)
        if style is not False:
            # the project's style pack on the timeline itself (null removes it), in the same undo step
            params['project_properties'] = {es.LOOK_PROP: style}
        if hook is not False:
            params.setdefault('project_properties', {})[es.HOOK_PROP] = hook
        method = 'apply_transaction'
    else:
        method = 'replace_tracks'
    with _bridge(instance_id) as b:
        result = b.call(method, params)
    final, _ = snapshot(instance_id)
    out = {**({'frames_at': sorted(set(frames_at))} if frames_at else {}),
           'changes': es.diff(before, es.read(final)), 'notes': notes, 'live': True, 'undo_label': label,
           'editor': f'applied in the open Shotcut window ({instance_id}) as one undoable step', 'bridge': result,
           'preview_project': str(final)}
    if markers:
        if 'markers' in params:
            took = isinstance(result, dict) and isinstance(result.get('markers'), dict)
            out['markers_follow'] = 'carried' if took else 'not_taken'
            if took:
                out['markers_followed'] = {'moved': carried['moved'], 'removed': carried['removed'],
                                           'where': f"letitedit window {instance_id}, in this edit's own undo step",
                                           'undo_label': label}
        else:
            out['markers_follow'] = 'none'
            if carried and carried.get('error'):
                out['markers_followed'] = {'error': carried['error']}
    return out
