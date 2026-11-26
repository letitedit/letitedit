"""MCP tools: read and edit a timeline as an edit script (no clicking through the editor window).

The saved .mlt stays the single source of truth. Read it as a script, change it with edits by clip id (or send a
whole script back), and every change is checked with frames rendered by the export engine.
"""
from __future__ import annotations

import io
import shutil
from pathlib import Path

import letitedit.review.checks as checks
import letitedit.server.next_step_replies as _next_step     # T345 C2: replies that carry the next step (switch, off)
import letitedit.timeline.edit_script as es
import letitedit.timeline.timeline_model as tm
from letitedit.timeline.timeline_speech import add_said


def _live_state(path):
    """The editor window (any instance) that has this project open: {'instance_id', 'modified'} or None."""
    import letitedit.app.live_edit as live_edit
    return live_edit.window_for(path)


def live_edit_snapshot(row):
    """The open window's current timeline, written out to a file (its unsaved changes included)."""
    import letitedit.app.live_edit as live_edit
    return live_edit.snapshot(row['instance_id'])[0]


def _reload(row, path):
    import letitedit.app.letitedit_instances as inst
    from letitedit.app.letitedit_client import ShotcutBridge
    with inst.scope(row['instance_id']), ShotcutBridge(timeout=60) as b:
        b.call('open', {'path': str(path)})


def change_sheet(path, before, after, limit=24):
    """First/middle/last frames of every clip that is new or changed in `after`."""
    changed = set()
    idx_b = {it.get('id'): it for t in before['tracks'] for it in t['items'] if 'id' in it}
    for t in after['tracks']:
        if t.get('kind') != 'video':
            continue
        for it in t['items']:
            if 'id' not in it:
                continue
            old = idx_b.get(it['id'])
            if old is None or es._comparable(old) != es._comparable(it):
                changed.add(it['id'])
    timeline = tm.load(path)
    picks = []
    for t in after['tracks']:
        if t.get('kind') != 'video':
            continue
        for it in t['items']:
            if it.get('id') in changed:
                a, n = es.to_seconds(it['at']), it['len']
                for x in (a + min(0.2, n / 4), a + n / 2, a + max(n - 0.2, n * 3 / 4)):
                    picks.append(round(x * timeline.fps))
    picks = sorted(set(picks))[:limit]
    if not picks:
        return None
    work = checks._work('changes')
    try:
        pngs = checks.render_frames(timeline, path, picks, work)
        import letitedit.pictures.code_scenes as code_scenes
        sheet = checks.contact_sheet(pngs, code_scenes.scene_labels(work, picks, [checks._label_for(timeline, f) for f in picks]),
                                     cols=3, tile_w=_next_step.sheet_width(420))
        buf = io.BytesIO()
        sheet.save(buf, 'JPEG', quality=85)
        return buf.getvalue()
    finally:
        shutil.rmtree(work, ignore_errors=True)   # the reply carries the sheet itself; nothing names these files (T95)


def frames_sheet(path, times, limit=24):
    """Frames of the project at the given timeline times (where effects were placed), from the export engine."""
    timeline = tm.load(path)
    picks = sorted({min(timeline.frames - 1, max(0, round(float(t) * timeline.fps))) for t in times})[:limit]
    if not picks:
        return None
    work = checks._work('changes')
    try:
        pngs = checks.render_frames(timeline, path, picks, work)
        import letitedit.pictures.code_scenes as code_scenes
        sheet = checks.contact_sheet(pngs, code_scenes.scene_labels(work, picks, [checks._label_for(timeline, f) for f in picks]),
                                     cols=4, tile_w=_next_step.sheet_width(360))
        buf = io.BytesIO()
        sheet.save(buf, 'JPEG', quality=85)
        return buf.getvalue()
    finally:
        shutil.rmtree(work, ignore_errors=True)   # the reply carries the sheet itself; nothing names these files (T95)


def _sheet(path, before, result, check):
    """The picture an apply returns: frames at every placed effect when the edit placed effects, else the
    changed clips."""
    if not check:
        return None
    times = result.pop('frames_at', None)
    if times:
        return frames_sheet(path, times)
    return change_sheet(path, before, es.read(path))


def _safe_sheet(path, before, result, check):
    """The picture of an edit that is already made: if it can't be drawn right now (a very busy PC) the reply says so and
    the edit still stands."""
    try:
        return _sheet(path, before, result, check)
    except Exception as e:  # noqa: BLE001
        result['notes'] = list(result.get('notes') or []) + [
            f'the edit is made, but its frames could not be drawn just now ({type(e).__name__}: {str(e)[:160]}); '
            'letitedit_check_frames shows them']
        return None


def _catching_up(path, result):
    """What is still redrawing after an edit that has landed in an open window, so a reply never promises more than is
    there. The export doesn't use these masks: it draws its own."""
    import letitedit.pictures.code_scenes as code_scenes
    if code_scenes.home(path).is_dir():
        result['catching_up'] = ('the window redraws its live scene in the background, in turns of the PC lock; until it is '
                                 'done the player may hide or lag the scene (the person stays in view). '
                                 'letitedit_check_frames and the export already show the edit.')


def _aim_sheet(project, changes, before_path, after_path, result, check):
    """For an edit with {op: aim}: before and after frames and how much changed where, in the result; the sheet, or None.
    Never fails the edit, which is already made."""
    aims = [o for o in changes or [] if isinstance(o, dict) and o.get('op') in ('aim', 'adjust')]
    if not aims or not check or not before_path:
        return None
    try:
        import letitedit.timeline.aim as aim
        import letitedit.pictures.code_scenes as code_scenes
        for p in (before_path, after_path):      # where these copies' scenes are kept
            code_scenes.SNAPSHOT_OF[str(Path(p))] = str(project)
        report, jpeg = aim.proof(before_path, after_path, aims)
        result['aim_proof'] = report
        return jpeg
    except Exception as e:  # noqa: BLE001
        result['aim_proof_error'] = f'{type(e).__name__}: {e}'[:300]
        return None


READING_LIMIT = 20      # reading-time lines in one reply; the rest are counted


def reading_time(before, after):
    """Words on screen (graphics, text, motion above the main picture; captions apart) that this edit added or whose
    words or time on screen it changed, held for less than their reading time: the review's own rule
    (letitedit.review.dense.reading_time), measured on the timeline. [{id, at, severity, problem}], at most
    READING_LIMIT, then {'more': n}."""
    import letitedit.review.dense as dense

    def shown(script):
        evts, _ = dense.events(script)
        return {e['id']: e for e in evts if e['kind'] == 'in' and e.get('text') and e.get('id') and e.get('end') is not None}

    def held(e):
        return round(e['end'] - e['t'], 3), e.get('text')

    old = shown(before) if before else {}
    found = []
    for item_id, e in shown(after).items():
        if item_id in old and held(old[item_id]) == held(e):      # moved along by a ripple, or untouched
            continue
        for f in dense.reading_time([dict(e)]):
            found.append({'id': item_id, 'at': f['at'], 'severity': f['severity'], 'problem': f['problem']})
    found.sort(key=lambda f: f['at'])
    return found[:READING_LIMIT] + ([{'more': len(found) - READING_LIMIT}] if len(found) > READING_LIMIT else [])


def _add_reading_time(result, before, after):
    """The edit's reading-time findings in its reply (`reading_time`) when there are any; never fails the edit."""
    try:
        if before is None or after is None:
            return
        found = reading_time(before, es.read(after) if isinstance(after, (str, Path)) else after)
        if found:
            result['reading_time'] = found
    except Exception:  # noqa: BLE001 - a measurement in the reply, never a reason to fail an edit that is made
        pass


def apply_project(project, changes=None, script_yaml=None, check=True, label=None, code=None, dry_run=False,
                  actor=None, lease_s=None, wait_s=None):
    """letitedit_timeline_apply without MCP: (result, jpeg of the changed clips or None). dry_run: check the changes and
    say what they would do, writing nothing. actor / lease_s / wait_s: the edit lease and track owners
    (project_journal; defaults LETITEDIT_ACTOR, else 'claude'/'codex' by the app above, else 'agent', 600 s, 0 s).
    With settings.json self_checks on (server/self_checks.py), a score op is aimed at its measured music level before
    the apply, and the reply's self_check carries the score's and the captions' own checks (and, with
    review_craft_checks on too, the picture under the words after a picture change: self_check.picture)."""
    records = {}
    result, jpeg = _apply_project(project, changes, script_yaml, check, label, code, dry_run, actor, lease_s, wait_s,
                                  records)
    if records.get('ran'):
        import letitedit.server.self_checks as self_checks
        self_checks.after(records['path'], records['changes'], result, records, live=records.get('live'))
    return result, jpeg


def _apply_project(project, changes, script_yaml, check, label, code, dry_run, actor, lease_s, wait_s, records):
    import letitedit.timeline.project_journal as pj
    path = es._resolve(project)
    import letitedit.app.live_review as live_review
    if not dry_run:
        live_review.guard(path)     # a person is watching it in Live Review: the edit goes on the working copy
        import letitedit.review.review_bundle as review_bundle
        refused = review_bundle.edit_after_handover(path)   # an unattended run handed over, no look left for a change
        if refused:
            raise ValueError(refused)
    who = pj.actor(actor)
    live = _live_state(path)
    printed = None
    if code:
        import letitedit.timeline.edit_code as edit_code
        from letitedit.timeline.timeline_speech import add_said
        if live:
            import letitedit.app.live_edit as live_edit
            current = es.read(live_edit.snapshot(live['instance_id'])[0])
            current['project'] = str(path)
        else:
            current = es.read(path)
        ran = edit_code.run(add_said(current), code)
        changes = list(changes or []) + ran['changes']
        printed = ran['output']
        if not changes:
            return {'changes': [], 'notes': ['the code made no changes'], 'printed': printed}, None
    if changes is not None and not script_yaml:
        import letitedit.timeline.op_specs as op_specs
        op_specs.check(changes)
        changes = _resolve_refs(path, changes)
        if not dry_run:
            import letitedit.server.self_checks as self_checks
            snap = None
            if live and self_checks.enabled() and any(isinstance(o, dict) and o.get('op') == 'score' for o in changes):
                import letitedit.app.live_edit as live_edit
                snap = live_edit.snapshot(live['instance_id'])[0]     # the window as the apply will start from it
            changes, made = self_checks.before(path, changes, snap)
            if self_checks.enabled():
                records.update(made, ran=True, path=path, changes=changes, live=live)
    if dry_run:
        if live:     # the window as it is now, unsaved changes included: the ids a live apply would edit (T298)
            import letitedit.app.live_edit as live_edit
            snap, rev = live_edit.snapshot(live['instance_id'])
            before = es.read(snap)
            before['project'] = str(path)
            state = live_edit.state_of(live, rev)
        else:
            before = es.read(path)
            state = {'state': 'saved'}
        if script_yaml:
            after, notes = es.from_yaml(script_yaml), []
        else:
            after, notes = es.edit(before, [dict(o) for o in changes or []])
        out = {'dry_run': True, 'written': False, 'changes': es.diff(before, after), 'notes': notes, 'read': state}
        _add_reading_time(out, before, after)
        if printed:
            out['printed'] = printed
        return out, None
    if live and changes is not None and not script_yaml:
        import letitedit.app.live_edit as live_edit
        try:
            requests = pj.owner_requests(changes)
            with pj.writing(path, who, lease_s, wait_s) as lease:
                snap = live_edit.snapshot(live['instance_id'])[0]
                before = es.read(snap)
                import letitedit.looks.project_look as project_look
                project_look.note_hand_edits(path, snap, script=before)   # the person's own edits since the AI's last
                before_copy = None
                if any(isinstance(o, dict) and o.get('op') in ('aim', 'adjust') for o in changes):
                    before_copy = Path(snap).with_name(Path(snap).stem + '-before-aim.mlt')
                    shutil.copy2(snap, before_copy)
                if pj.blocked_by(path, who):
                    planned, _ = es.edit(before, [dict(o) for o in changes])
                    pj.check(path, who, before, planned, requests)
                carry = _carry_markers()        # off: the call is as it always was
                result = live_edit.apply(live['instance_id'], changes, label=label,
                                         **({'markers': carry} if carry else {}))
                pj.save_requests(path, who, requests)
            result['lease'] = lease
            pj.record(path, 'apply', who, label or result.get('undo_label'), result.get('changes'),
                      where=f"letitedit window {live['instance_id']}", hand_checked=True)
            saved = live_edit.own_save(live, path, who)     # the Studio's own window only, never a person's (T298)
            if saved.get('saved'):
                result['saved'] = saved['saved']
            elif saved.get('save_failed'):                  # said in the reply and the journal, never silent (T329)
                result['save_failed'] = saved['save_failed']
                result.setdefault('notes', []).append(live_edit.save_note(saved))
            if result.get('preview_project'):
                project_look.remember(path, result['preview_project'])    # the window as this edit left it
                follow = result.pop('markers_follow', None)
                if follow not in ('carried', 'none'):
                    _follow_markers(path, before, result['preview_project'], who, result)
                    if follow == 'not_taken' and (result.get('markers_followed') or {}).get('undo_label'):
                        result.setdefault('notes', []).append(
                            "this letitedit window's build can't take markers with an edit, so the markers that "
                            f"follow their clips went in as a second undo step ({result['markers_followed']['undo_label']})")
            preview = result.pop('preview_project', None)
            if printed:
                result['printed'] = printed
            _after_apply(path, changes, label, who)
            _catching_up(path, result)
            if preview is None:
                return result, None
            preview = Path(preview)
        except (pj.LeaseHeld, pj.TrackOwned):
            raise
        except ValueError:
            # Track structure changes can't go in as one live step; a saved project falls back to the
            # file apply below (the window reloads), an unsaved one must be saved first.
            if live.get('modified'):
                raise
            preview = None
        if preview is not None:
            _add_reading_time(result, before, preview)
            if check:
                _next_step.after_apply(result, before, preview, path, changes)
            jpeg = _aim_sheet(path, changes, before_copy, preview, result, check)
            return result, jpeg or _safe_sheet(preview, before, result, check)
    if live and live.get('modified'):
        raise ValueError('This project is open in letitedit with unsaved changes. Save it in letitedit (or ask the user to), '
                         'then apply again, so nobody\'s work is overwritten.')
    before = es.read(path)
    if script_yaml:
        result = es.apply_changes(path, script=es.from_yaml(script_yaml), actor=who, label=label, lease_s=lease_s,
                                  wait_s=wait_s)
    else:
        result = es.apply_changes(path, ops=changes or [], actor=who, label=label, lease_s=lease_s, wait_s=wait_s)
    _follow_markers(path, before, path, who, result, saved=True)
    if not live:
        _follow_scenes(path, before, None if script_yaml else changes, label, who, result)
        _follow_captions(path, before, changes, label, who, result)
    if live:
        _reload(live, path)
        result['editor'] = f"reloaded the open project in letitedit ({live['instance_id']})"
    if printed:
        result['printed'] = printed
    if not script_yaml:
        _after_apply(path, changes, label, who)
    _add_reading_time(result, before, path)
    if check and not script_yaml:
        _next_step.after_apply(result, before, path, path, changes)
    jpeg = None if script_yaml else _aim_sheet(path, changes, result.get('history'), path, result, check)
    return result, jpeg or _safe_sheet(path, before, result, check)


def _carry_markers():
    """With markers following their clips (letitedit.app.bookkeeping.markers_follow): the rule an open window's apply
    uses to carry the moved markers in the edit's own undo step (letitedit.server.books.carry, T356). Off: None."""
    import letitedit.app.bookkeeping as bookkeeping
    try:
        if not bookkeeping.markers_follow():
            return None
    except Exception:  # noqa: BLE001 - markers are bookkeeping: the edit stands without them
        return None
    from letitedit.server import books
    return books.carry


def _follow_markers(path, before, after_file, who, result, saved=False):
    """With markers following their clips (letitedit.app.bookkeeping.markers_follow, T345 C1): the timeline's
    markers moved with the moments they mark, from script `before` to the project `after_file` as the edit left it
    (letitedit.server.books.follow). A saved file is rewritten in place (undoing the edit restores the markers too).
    An open window takes them in the edit's own undo step (_carry_markers, T356); only a window whose build can't
    take them gets them here, as a second undo step, '<prefix>: markers follow', which letitedit_timeline_undo takes
    back with the edit. The reply gets `markers_followed`. Off, nothing happens."""
    import letitedit.app.bookkeeping as bookkeeping
    try:
        if not bookkeeping.markers_follow():
            return
        after = es.read(after_file)
    except Exception:  # noqa: BLE001 - markers are bookkeeping: the edit stands without them
        return
    from letitedit.server import books
    got = books.follow_apply(path, before, after, actor=who, saved_only=saved)
    if got:
        result['markers_followed'] = got


def _follow_scenes(path, before, changes, label, who, result):
    """T362 (letitedit.server.scene_follow, on by default): a drawn scene over picture the edit cut, trimmed or moved
    gets a revision whose drawing follows the cut, in the edit's own undo step. The reply gets `scenes_followed`.
    Never raises: the edit stands as it is."""
    try:
        from letitedit.server import scene_follow
        scene_follow.follow(path, before, changes, label, who, result)
    except Exception:  # noqa: BLE001 - bookkeeping: the edit stands without it
        pass


def _follow_captions(path, before, changes, label, who, result):
    """T360 (letitedit.server.caption_follow, on by default): the project's last caption fit run again after an edit
    written to the saved file, and its plan applied in the edit's own undo step when caption_layout.apply_plan allows
    it. The reply gets `captions_followed`. Never raises: the edit stands as it is."""
    try:
        from letitedit.server import caption_follow
        caption_follow.follow(path, before, changes, label, who, result)
    except Exception:  # noqa: BLE001 - bookkeeping: the edit stands without it
        pass


def _resolve_refs(path, changes):
    """Ops that refer to files beside the project get their contents before the edit runs (so the edit also works on
    an open window's snapshot): hook candidates by id (hooks.json) and the project's own pop-ups (popups.json)."""
    import letitedit.footage.hooks as hooks
    import letitedit.looks.popups as popups
    changes = [dict(o) if isinstance(o, dict) else o for o in changes]
    hooks.resolve_ops(path, changes)
    popups.inline_project_entries(path, changes)
    return changes


def _after_apply(path, changes, label=None, who=None):
    import letitedit.footage.hooks as hooks
    hooks.after_apply(path, changes)
    _record_pins(path, changes, label, who)
    import letitedit.pictures.code_scenes as code_scenes
    code_scenes.request_refresh(path)


def _record_pins(path, changes, label=None, who=None):
    """Clip edges kept as given with edge_mode exact (trim or set by id, numeric in/out), in the project's journal as a
    'pin' entry: [{id, side, at, reason}], the reason the op's edge_reason (else its label). The review quotes it beside
    a finding at that edge."""
    pins = []
    for o in changes or []:
        if not (isinstance(o, dict) and o.get('edge_mode') == 'exact' and o.get('op') in ('trim', 'set') and o.get('id')):
            continue
        for side in ('in', 'out'):
            if isinstance(o.get(side), (int, float)) or (isinstance(o.get(side), str) and o[side].strip()):
                pins.append({'id': o['id'], 'side': side, 'at': o[side],
                             **({'reason': str(o['edge_reason'])[:300]} if o.get('edge_reason') else {})})
    if pins:
        try:
            import letitedit.timeline.project_journal as pj
            pj.record(path, 'pin', who, label, pins=pins)
        except Exception:  # noqa: BLE001 - the edit stands without the record
            pass


def undo_project(project, list_only=False, actor=None, lease_s=None, wait_s=None):
    """letitedit_timeline_undo without MCP."""
    import letitedit.timeline.project_journal as pj
    path = es._resolve(project)
    if list_only:
        return es.history(path)
    import letitedit.review.review_bundle as review_bundle
    refused = review_bundle.edit_after_handover(path)   # an undo changes the cut as much as an apply does
    if refused:
        raise ValueError(refused)
    who = pj.actor(actor)
    live = _live_state(path)
    if live:
        import letitedit.app.letitedit_instances as inst
        from letitedit.app.letitedit_client import ShotcutBridge
        with pj.writing(path, who, lease_s, wait_s) as lease:
            with inst.scope(live['instance_id']), ShotcutBridge(timeout=60) as b:
                hist = (b.call('live_context') or {}).get('history') or {}
                top = next((e for e in hist.get('entries', []) if e.get('index') == hist.get('cursor', 0) - 1), None)
                label = (top or {}).get('label') or ''
                if not (label.startswith(tuple(pj.LABEL_NAMES.values()) + (pj.label_prefix(who),)) or label == 'AI edit'):
                    raise ValueError(f"The latest step in the letitedit window is the person's own ({label or 'nothing to undo'}); "
                                     "not undoing it. Ask them, or apply a new edit that restores what you need.")
                undid = b.call('undo')
                import letitedit.sound.av_tools as av_tools
                if label.endswith(f': {av_tools.FOLLOW_LABEL}'):   # the markers an edit carried (T345 C1): the edit too
                    hist = (b.call('live_context') or {}).get('history') or {}
                    top = next((e for e in hist.get('entries', []) if e.get('index') == hist.get('cursor', 0) - 1),
                               None)
                    below = (top or {}).get('label') or ''
                    if below.startswith(tuple(pj.LABEL_NAMES.values()) + (pj.label_prefix(who),)) or below == 'AI edit':
                        undid = b.call('undo')
                        label = below
        where = f"letitedit window {live['instance_id']}"
        pj.record(path, 'undo', who, f'undo {label}', None, where=where)
        import letitedit.app.live_edit as live_edit
        saved = live_edit.own_save(live, path, who)     # the Studio's own window only, never a person's (T298)
        import letitedit.pictures.code_scenes as code_scenes
        code_scenes.request_refresh(path)
        out = {'undid': undid, 'where': where, 'lease': lease}
        if saved.get('save_failed'):                    # said in the reply and the journal, never silent (T329)
            out.update(save_failed=saved['save_failed'], note=live_edit.save_note(saved))
        return [out]
    result = es.undo(path, actor=who, lease_s=lease_s, wait_s=wait_s)
    import letitedit.pictures.code_scenes as code_scenes
    code_scenes.request_refresh(path)
    return [result]


def changes_from_file(path):
    """A changes list from a .json or .yaml file: the list itself, or a mapping with a `changes` list."""
    import json
    p = Path(path)
    if not p.is_file():
        raise ValueError(f'changes_file: no such file {path}')
    text = p.read_text(encoding='utf-8-sig')
    if p.suffix.lower() in ('.yaml', '.yml'):
        import yaml
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if isinstance(data, dict):
        data = data.get('changes')
    if not isinstance(data, list) or not all(isinstance(op, dict) for op in data):
        raise ValueError('changes_file holds a list of ops (or {changes: [...]})')
    return data


def register(mcp, Image):
    @mcp.tool()
    def letitedit_review_note(project: str, note: int, state: str, what: str = '', why: str = '') -> dict:
        """Say what became of a Live Review note. project: the working copy the note names; note: its number; state:
        done (what: one plain line saying what changed), could_not (why: what stopped it), not_an_edit (nothing
        was asked of the video: talk to someone else, thinking aloud). The person's list shows it."""
        import letitedit.app.live_review as live_review
        return live_review.report(project, note, state, what=what, why=why)

    @mcp.tool()
    def letitedit_timeline_read(project: str, start_s: float | None = None, end_s: float | None = None,
                              tracks: list[str] | None = None, stack_at: float | list[float] | None = None,
                              ids: list[str] | None = None, detail: str = 'auto') -> str:
        """Read a saved timeline as an edit script (YAML): every track (volume `gain`, auto-`duck`, track `effects`),
        every clip with a stable id, source file, in/out (source seconds), speed, effects (every engine effect, with
        keyframes), transitions, gaps; made clips as their recipes (graphic, ffmpeg, freeze, vfx, voice); captions
        with their style; the selected Look (`look`) and the whole-video `master` effects. Positions (at), lengths
        (len), `said` (the words heard in a clip, when its file is transcribed) and `recorded` (when that shot was filmed,
        by the camera's clock) are for reading. With two or more video tracks a comment line gives their order, back to front.
        Limit with start_s/end_s, tracks or ids (only those clips) for long projects. project = .mlt path or
        episode/cut folder. detail: full (everything), compact (each keyframe list of more than two keys shown as its
        count, first and last time and lowest and highest value; each text over 600 characters, such as a libass script
        or a graphic's code, as its length and first characters; a `view` line says how many were folded) or auto (the
        default: full, or compact when the full YAML would be over 36,000 characters; with ids, full). A compact
        script is for reading: script_yaml refuses it, and ops by id work on it as on any read. An auto read still over
        36,000 characters compact covers the timeline up to a cut on the main picture track: its `view` line gives
        `continues: {start_s}`, where the next read starts.
        stack_at: seconds, or [start, end]: plain text instead of YAML, the layers at that moment (one block per change in
        a range), back to front: what each shows, its size, alpha, blend and effects (clip, track), then whole-video effects
        and captions, and warnings (a blend that does nothing there, a scene with no cut-out above it, a cut-out out of step
        with the footage).
        Then change it with letitedit_timeline_apply. Clips edited by hand in letitedit keep their ids."""
        path = es._resolve(project)
        live = _live_state(path)
        if stack_at is not None:
            import letitedit.timeline.stack as stack
            source = live_edit_snapshot(live) if live else path
            return stack.view(es.read(source), es.Doc(source), stack_at)
        import letitedit.looks.project_look as project_look
        if detail not in ('auto', 'full', 'compact'):
            raise ValueError("detail is auto, full or compact")
        if live:
            import letitedit.app.live_edit as live_edit
            snap, rev = live_edit.snapshot(live['instance_id'])
            project_look.note_hand_edits(path, snap)        # the person's own edits since the AI's last, journalled
            script = es.read(snap, start_s=start_s, end_s=end_s, tracks=tracks)
            script['project'] = str(path)
            script['live'] = {'window': live['instance_id'], 'unsaved_changes': bool(live.get('modified')), 'revision': rev}
            script['read'] = live_edit.state_of(live, rev)
        else:
            project_look.note_hand_edits(path)
            script = es.read(path, start_s=start_s, end_s=end_s, tracks=tracks)
            script['read'] = {'state': 'saved'}
        if ids:
            script = es.only_ids(script, list(ids))
        script = add_said(script)
        if detail == 'compact':
            return es.to_yaml(es.compact(script))
        text = es.to_yaml(script)
        if detail == 'auto' and not ids and len(text) > es.COMPACT_AUTO:
            folded = es.compact(script)
            folded.setdefault('view', {'compact': True})
            folded['view']['full_chars'] = len(text)
            folded, more = es.page(folded, lambda sc: len(es.to_yaml(sc)), es.COMPACT_PAGE, lo=start_s or 0)
            if more is not None:
                folded['view']['continues'] = {'start_s': round(more, 3)}
            return es.to_yaml(folded)
        return text

    @mcp.tool(structured_output=False)
    def letitedit_timeline_apply(project: str, changes: list[dict] | None = None, script_yaml: str | None = None,
                               check: bool = True, label: str | None = None, code: str | None = None,
                               dry_run: bool = False, actor: str | None = None, lease_s: float = 600,
                               wait_s: float = 0, changes_file: str | None = None) -> list:
        """Change a saved timeline, then see the result. `changes` are edits by clip id, applied to the current
        file even if the user edited it meanwhile:
          {op: insert, track, after?|before?|at_start?|at?: s, item}   {op: trim, id, in?, out? | words: "phrase"}
          {op: delete, id, close_gap?}   (default: closes on the main picture track; other tracks keep their times,
            and trimming an item there leaves the items after it in place)
          {op: move, id, track?, after?|before?|at_start?|at?: s}   {op: set, id, ...fields (null removes)}
            at: that time on the finished timeline, any track but the main picture track; other items keep their times
          {op: effects, id, effects: [...]}   {op: gap, id, before?|after?: s} (sets the space next to it)
          {op: effects, ids?: [...], track?: name(s), effects?: [...] | add?: [...]}   many items in one op: ids and/or
            every clip of a file on the track; effects replaces each one's effects, add adds to each one's own
            ({fix: ...} entries after its other fixes, the rest at the end)
          {op: add_track, name, kind: video|audio}
          {op: track, name, gain?, duck?, effects?: [...]}   effects on a whole track (grade the B-roll, EQ the music)
          {op: master, effects: [...]}   whole-video effects and the final sound chain ({limiter}, {loudness}, any filter)
          {op: aim, effect, on: clip|all|below|person|not_person, id?, track?, from?, to?, region?}   one effect on a chosen
            part of the video; the reply has before and after frames and how much changed where (letitedit_guide('aim'))
          {op: captions, track, cues?|from_speech: true, chunk?: sentence|short, style?, animate?: pop|karaoke|
            highlight|typewriter|bounce, fix?: {heard: Written}, style_fix?: false, fillers?: false}   from_speech:
            captions of everything said, from word timings (runs after the other edits; um/uh left out unless fillers:
            true), spelled with the project Look's list (its captions.corrections, e.g. from My Looks; `fix` words or
            phrases win; style_fix: false leaves the style's list out). animate:
            word-by-word captions as graphics on a video track named `track`, sized to the picture under them (the
            result says how wide the lines are and how much of the width the footage under them covers). The result
            of from_speech lists the words the transcriber gave under 45% probability (those the fixes cover aside).
            A caption never runs into the video's last frame (the engine would not draw it): its end stops a frame
            before.
          {op: tighten, id, max_pause?, speed_up_over?}   keep a clip's spoken parts, cut pauses (word timings and
            voice detection)
          {op: score, zones?, end?, level_voice?}   even out the speech clip by clip, then mix the music under it
            (after the picture edit; level_voice: false leaves clip gains)   {op: level, target?}   speech levelling only
          {op: look, id|null}   project Look defaults; null selects neutral
        Items (anything the script shows can be inserted, and every one takes effects and transition):
          {clip, in, out, speed?, reverse?: true}   any video, picture or sound file, including ones you make yourself
          {clip, words: "they put these on tight", near?: s}   that phrase, cut on the gaps around it (audio-checked)
          {color, len}   {graphic: {template, params, code?, source?}, len}   Python-drawn (letitedit_graphic); with
            source: {clip, in, out, fit?} custom code gets every footage frame as ctx.src (and ctx.still, ctx.matte,
            ctx.depth): process footage in Python
          {ffmpeg: {inputs: [{clip, in, out}], video?: "-vf chain or graph ending [v]", audio?: chain|false,
            alpha?: false, fit?: contain|cover}, len?}   a clip made by an ffmpeg filter graph (zoompan, drawtext, xfade...)
          {ass: "<.ass script, or Dialogue lines>", len?}   a transparent text layer drawn by libass (times from the
            clip's start; PlayRes defaults to the project size; installed fonts)
          {freeze: {clip, at}, len}   a held frame        {vfx: {effect, source, params}}  tracked arrows, backdrops,
            sky, speed ramps... (letitedit_vfx_effects)      {voice: {text}} narration made locally (audio tracks)
          transition: seconds | {type: dissolve|cut|iris_circle|clock_top|bar_horizontal|...(22 wipes)|<luma image
            path>, len, softness?, invert?, audio?: crossfade|linear}   on an item: overlaps the clip before it.
        Effects: any engine effect as {filter: NAME, params: {...}} (letitedit_effects finds names and settings: colour,
          blur, glow, grain, vignette, masks, chroma key, EQ, compressor, noise reduction...), plus the short words
          mute | {gain: dB} | {fade_in: s, opacity?} | {fade_out: s} | {fade_in_audio: s} | {fade_out_audio: s}
          | {zoom: 1.1, focus?: [x, y]} | {size_position: "x y w h"} | {opacity: 0-1} | {text: "...", style}
          | {ffmpeg: "filter chain or graph" | {video, audio?, inputs?: [files], fit?: contain|cover}}: the clip's
          picture/sound through ffmpeg (graph: clip [0:v]/[0:a], inputs [1:v]..., ends [v]/[a]; output keeps the
          graph's size), rendered in the background; as a track effect, on every clip with a picture on the track.
          Any numeric setting can move: {keys: [[seconds, value], [seconds, value, ease], ...]} (seconds from the clip's
          start; ease: linear, hold, smooth, ease_in, ease_out, ease_in_out, sine_/quad_/cubic_/expo_/back_/elastic_/
          bounce_ + in|out|in_out). E.g. {zoom: {keys: [[0, 1], [4, 1.3, ease_in_out]]}} is a slow push-in.
        Text and caption style: font ({family, weight, italic} or heading|body|captions), fill, outline {color, width},
          background, position top|middle|bottom, shadow {color, x, y}; colours '#RRGGBB' or kit names; any installed font.
        When the main picture track changes, other tracks and captions move with their picture (ripple: false stops it).
        `code`: Python that computes changes. It runs in its own process with `timeline` (the script as read, with `said`),
          `changes` (a list it appends ops to; applied after any `changes` given), words(start_s, end_s) (words said on
          the timeline: w, t0, t1, id, track), source_words(clip, start, end) (w, s, e), find(text, clip=None, near=None)
          (a phrase: source in/out cut on the gaps with clip, timeline start/end/id without), layout(track) and
          clock()/seconds(); print() output is returned. Any Python library on this PC can be imported.
        changes_file: a .json or .yaml file holding the `changes` list (or {changes: [...]}), read as if sent in
          `changes` and applied after them; for a long list.
        Or send `script_yaml` (a full script from letitedit_timeline_read; refused if the file changed since). If the
        project is open in letitedit, `changes` land in the window as ONE undo step labelled `label` (the user
        can Ctrl+Z it); otherwise the file changes and an undo copy is kept (letitedit_timeline_undo).
        Every change is checked before anything is applied; a problem names the op, the field and what it accepts
        (letitedit_guide('ops') lists every op and field). dry_run=True: check and say what the changes would do, without
        writing anything.
        Returns the change list (added or trimmed clips with the words heard in them, and what the source says next
        when the speaker is still talking where a clip ends) and, with check=True, frames of
        every changed clip from the export engine, and the edit lease. reading_time (also on a dry run), when there
        are any: words on screen above the main picture (graphics, text, motion; captions apart) that this edit added
        or whose words or time on screen it changed, held shorter than their reading time (words / 3.5 + 0.5 s, at
        least 1.5 s; 0.6 s for one word or number; 1.0 s for a short two-word label; an animated arrival's first
        0.25 s not counted), each with its id, time, severity and the time it needs: the review measures the same
        on the export.
        actor: who is editing [LETITEDIT_ACTOR environment variable, else 'claude' or 'codex' by the
        app this runs under, else 'agent']. A write takes the project's edit
        lease for actor; while another actor's lease is unexpired the apply waits up to wait_s seconds [0], then is
        refused, naming the owner and expiry. The lease lasts lease_s seconds after the apply [600]; 0 releases it.
        An apply that changes a track owned by another actor ({op: track, name, owner}) is refused. Each apply adds an
        entry to the project's journal (letitedit_journal). Edits made in the letitedit window are never blocked."""
        if changes_file:
            changes = list(changes or []) + changes_from_file(changes_file)
        result, sheet = apply_project(project, changes, script_yaml, check, label, code, dry_run, actor, lease_s, wait_s)
        return [Image(data=sheet, format='jpeg'), result] if sheet else [result]

    @mcp.tool(structured_output=False)
    def letitedit_timeline_undo(project: str, list_only: bool = False, actor: str | None = None, lease_s: float = 600,
                              wait_s: float = 0) -> list:
        """Undo your last edit. If the project is open in letitedit, this is the window's own Undo, and only when the
        latest step is an AI step (labelled "Claude: ...", "Codex: ...", "Antigravity: ..." or "letitedit: ..."): the user's own steps are never undone. Otherwise the
        file goes back to the copy kept before your last letitedit_timeline_apply; repeat to go further back.
        list_only=True lists the kept copies instead (<stem>.letitedit\\history beside the project, and older copies in
        the cache). An undo holds the edit lease like letitedit_timeline_apply (actor, lease_s [600], wait_s [0]) and
        adds a journal entry."""
        return undo_project(project, list_only, actor, lease_s, wait_s)

    @mcp.tool(structured_output=False)
    def letitedit_words(clip: str | list[str] | None = None, start_s: float | None = None, end_s: float | None = None,
                      project: str | None = None, pictures: bool = True, pause: float = 0.6, max_words: int = 14,
                      per_word: bool = False, picture_limits: dict | None = None) -> list:
        """What is said, with times: lines of words grouped at pauses (a new line after a pause of `pause` seconds or
        `max_words` words), as 'start-end  text'; per_word=True: one word per line, 'start-end  word  p' (p = how sure
        the transcriber was, 0-1), and '~' after a word that runs straight into the next (no pause between them to
        cut in). Source times are where each word's sound starts and ends, measured on the audio (the transcript's
        own word times run over the pauses). Transcribed locally once (on the GPU when available) and cached. '(?)' after a word: the transcriber gave it under 45% probability.
        '[4.9 s: sound at 89.78-89.86, 94.54-94.68, nothing between]' after a word: it lasts that long, far more than a word does (over a second plus a tenth per letter), and the bracket says where the sound actually is inside it (a file's words; on a timeline just '[4.9 s]'): the transcriber folded a pause or a restart of the line into it, so the words around it are not where they seem.
        '^' after a word: the transcript had folded it into a stretched word, and this is that stretch heard by itself, with its own times: a stretch
        is heard once, then kept; when the PC is rendering it is heard on the CPU's speech model if the PC has one, otherwise it stays as the marker above until a later call.
        '[picture: ...]' after a line: what the footage analysis found in the picture over at least half of that
        line (dark, blown out, blurry, whip); picture_limits sets the cutoffs (as in letitedit_footage).
        Each file's '# sound:' line gives how far the speech stands over the room and, for the range asked, what plays
        between the words: 'gaps: N windows of 0.1 s' (windows more than 0.15 s from any word), their median and 90th
        percentile level in dB over the quietest tenth of the range's windows.
        - clip=<source file>, or a folder or list of files (every file with talking, each headed by when it was
          recorded): source seconds (pick cut points, phrases). Each video's text names its sheet image (a frame of
          the footage at the start of every line, labelled with its time and words); with pictures (default) the
          sheets also come back as images.
        - project=<.mlt>: timeline seconds between start_s and end_s, with the clip id each line comes from (check
          what is said around a cut, or line up a graphic with a line)."""
        if project:
            from letitedit.timeline.timeline_speech import timeline_words
            path = es._resolve(project)
            ws = timeline_words(es.read(path), start_s, end_s, heard=True)
            if not ws:
                return ['Nothing is said on the timeline in that range.']
            import letitedit.footage.speech as speech
            if per_word:
                return ['\n'.join(f"{w['t0']:.2f}-{w['t1']:.2f}  [{w['id']}]  {speech.shown(w)}  {w.get('p', 1):.2f}"
                                   for w in ws)]
            lines, cur = [], [ws[0]]
            for w in ws[1:]:
                if w['t0'] - cur[-1]['t1'] > pause or len(cur) >= max_words or w['id'] != cur[-1]['id']:
                    lines.append(cur)
                    cur = [w]
                else:
                    cur.append(w)
            lines.append(cur)
            import letitedit.footage.speech as speech
            return ['\n'.join(f"{l[0]['t0']:8.2f}-{l[-1]['t1']:8.2f}  [{l[0]['id']}]  {' '.join(speech.shown(x) for x in l)}"
                               for l in lines)]
        if not clip:
            raise ValueError('Give clip (a source file, folder or list of files) or project (a timeline).')
        import letitedit.server.core_tools as core_tools
        import letitedit.sound.music as music
        files, folders, _ = core_tools._collect(clip)
        many = bool(folders) or len(files) > 1
        texts, items = [], []
        for f in files:
            if many:
                try:
                    if core_tools._kind(f) not in ('video', 'audio') or not music.voice_times(str(f)):
                        continue
                except Exception:  # noqa: BLE001 - not a media file
                    continue
            if per_word:
                import letitedit.footage.speech as speech
                ws = speech.sound_words(str(f), start_s, end_s, heard=True)
                info = core_tools.probe(f)
                head = f"# {Path(f).name}" + (f"  recorded {core_tools._created(info)}" if info.get('created') else '')
                body = '\n'.join(f"{w['s']:.2f}-{w['e']:.2f}  {speech.shown_in(w, f).replace('(?)', '')}  {w.get('p', 1):.2f}"
                                 + ('  ~' if w.get('run_on') else '') for w in ws) \
                    or 'No speech found in that range.'
                room = speech.over_room_line(f, start_s, end_s) if ws else ''
                if room:
                    body = f'{room}\n{body}'
                language = speech.english_only_line(f) if ws else ''
                if language:
                    body = f'# {language}\n{body}'
                texts.append(f'{head}\n{body}' if many else body)
                continue
            lines = core_tools.word_lines(f, start_s, end_s, pause=pause, max_words=max_words, heard=True)
            info = core_tools.probe(f)
            head = f"# {Path(f).name}" + (f"  recorded {core_tools._created(info)}" if info.get('created') else '')
            tags = core_tools.picture_tags(f, [(a, b) for a, b, _ in lines], picture_limits)
            body = '\n'.join(f"{a:8.2f}-{b:8.2f}  {t}" + (f"  [picture: {g}]" if g else '')
                             for (a, b, t), g in zip(lines, tags)) or 'No speech found in that range.'
            import letitedit.footage.speech as speech
            room = speech.over_room_line(f, start_s, end_s) if lines else ''
            if room:
                body = f'{room}\n{body}'
            language = speech.english_only_line(f) if lines else ''
            if language:
                body = f'# {language}\n{body}'
            try:
                sheet = core_tools.word_sheet_file(f, lines)
            except Exception:  # noqa: BLE001 - the words still stand without the picture sheet
                sheet = None
            if sheet:
                head += f'\n# frames at each line: {sheet}'
            texts.append(f'{head}\n{body}' if many else (f'# frames at each line: {sheet}\n' if sheet else '') + body)
            items.append((f, lines))
        out = ['\n\n'.join(texts) if texts else 'No speech found.']
        if pictures:
            out += [Image(data=pg, format='jpeg') for pg in core_tools.word_sheets(items)]
        return out
