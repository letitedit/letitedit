"""Studio revisions through the app's saved Review queue, on a private project copy.

Review itself composes and sends the editing request (review/send.cpp). No second editing
prompt or note classifier lives here. Live Review's report and moment helpers retain each
note's outcome and its position in the version the caller watched. Finals then use New
video's review stage and Short delivery; stills reuse the saved drawing and still pipeline.
"""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
import shutil
import time
from pathlib import Path

from letitedit.studio import files, overlays, short, state, still, still_ai


EFFECTIVE = 'revise-inputs.json'


def unusable(message):
    raise state.StudioError('from_job_unusable', message, stage='apply', retry='after_change')


def earlier(job):
    import letitedit.studio.service as service
    folder = service.find(short._home(), job.get('from_job', ''))
    before = files.read_json(folder / 'result.json') if folder else None
    if not before or before.get('state') != 'done' or before.get('kind') not in ('short', 'revise', 'retext', 'still'):
        unusable('Revise needs a finished Short, revision, text revision, batch item or still.')
    return Path(folder), before


def inside(folder, relative):
    path = (Path(folder) / relative).resolve()
    if not path.is_relative_to(Path(folder).resolve()) or not path.is_file():
        unusable('The earlier editable project or drawing is missing from its job folder.')
    return path


def inputs_of(folder, seen=None):
    """Effective choices survive revise/retext chains, including explicit empty overlays/rules."""
    import letitedit.studio.service as service
    seen = set() if seen is None else seen
    folder = Path(folder)
    if str(folder.resolve()) in seen:
        unusable('The earlier jobs form a loop.')
    seen.add(str(folder.resolve()))
    saved = files.read_json(folder / 'work' / EFFECTIVE)
    if saved is not None:
        return saved
    spec = files.read_json(folder / 'job.json') or {}
    inp = {}
    if spec.get('from_job'):
        parent = service.find(short._home(), spec['from_job'])
        if not parent:
            unusable('An earlier job containing the inherited delivery choices cannot be found.')
        inp.update(inputs_of(parent, seen))
    inp.update(spec.get('inputs') or {})
    targets = list(folder.glob('work/*/retext-targets.json'))
    if targets:
        inp['platforms'] = files.read_json(targets[0])
    return inp


def effective(job, folder, before):
    inp = copy.deepcopy(inputs_of(folder))
    # Notes/openings describe one round, never instructions to replay on a later revise.
    for key in ('notes', 'hook'):
        inp.pop(key, None)
    # A still has no tier. A legacy text revision may have omitted the video's tier.
    if overlays.is_still(before):
        if 'tier' in job.get('inputs', {}):
            raise state.StudioError('invalid_job', "A still's revise has no tier.", stage='apply')
        if 'hook' in job.get('inputs', {}):
            raise state.StudioError('invalid_job', 'An opening applies to a video, not a still.', stage='apply')
        inp.pop('tier', None)
    else:
        inp['tier'] = before.get('tier') or inp.get('tier') or 'final'
    inp.update(job.get('inputs') or {})
    if 'overlay_text' not in inp:
        inp['overlay_text'] = [item for _, item in overlays.carried(before.get('text_items'))]
    if not inp.get('platforms'):
        inp['platforms'] = [f['platform'] for f in before.get('output', {}).get('files', [])] or ['youtube_shorts']
    return {**job, 'inputs': inp}


def _copy(old, new):
    if new.resolve() == old.resolve() or new.resolve().is_relative_to(old.resolve()):
        unusable('The new job cannot be inside the earlier project folder.')
    if new.exists():
        shutil.rmtree(new)
    new.parent.mkdir(parents=True, exist_ok=True)
    # Exports/review rounds belong to the earlier job, never to this revision's checks or cost.
    def omit(folder, names):
        return {n for n in names if n in ('lease.json', 'exports.json', 'reviews', 'review', 'reports',
                                         'session.json') or
                n.startswith('cost-') and n.endswith('.json') or n.endswith('.export.json')}
    shutil.copytree(old, new, ignore=omit)
    short._rewrite(new, old, new)


def prepare(ctx, job_dir, job):
    folder, before = earlier(job)
    view = effective(job, folder, before)
    is_still = overlays.is_still(before)
    previous = short._run(ctx)
    if is_still:
        old = inside(folder, 'work/still/plan.json').parent
        new = Path(job_dir) / 'work' / 'still'
        receipts = {p.name: p.read_bytes() for p in new.glob('cost-*.json')}
        _copy(old, new)
        for name, body in receipts.items():
            (new / name).write_bytes(body)
        data = still.read(job_dir)
        data['lock_waited_s'] = 0
        data.pop('prefer_redo', None)
        still.save(job_dir, data)
        project = None
    else:
        if not before.get('output', {}).get('project'):
            unusable('The earlier video has no editable project.')
        old_project = inside(folder, before['output']['project'])
        old = old_project.parent
        new = Path(job_dir) / 'work' / 'video'
        _copy(old, new)
        project = new / old_project.name
    since = previous.get('since') if previous.get('from') == str(folder) else None
    since = since or time.time()
    run = {'from': str(folder), 'before': before, 'folder': str(new),
           'project': str(project) if project else None, 'still': is_still,
           'effective': view, 'earlier_job': view, 'since': since, 'changes': []}
    if not is_still:
        sources = files.read_json(project.with_suffix('.letitedit') / short.SOURCES_FILE)
        run['sources'] = sources
        run['tier'] = view['inputs']['tier']
        shutil.copy2(project, new / 'before-revise.mlt')
        files.write_json(new / 'session.json', {'kind': 'studio-revise', 'revision_of': job['from_job']})
        # A revision is a new edit made from the person's notes: it gets review rounds of its own under
        # the brief's limit. The earlier rounds' findings stay as history, so a reviewer says what is fixed.
        from letitedit.review import review_bundle
        review_bundle.start_revision(project, job.get('from_job'))
        # A note with a measurable target (a length, a level, a size) is measured on this cut, before any change,
        # so every review of the revision compares the cut with what the note asked.
        review_bundle.keep_note_targets(project, view['inputs'].get('notes') or [])
        # Rule outcomes must describe this revision. Keep all other journal history.
        journal = project.with_suffix('.letitedit') / 'journal.jsonl'
        if journal.is_file():
            rows = []
            for line in journal.read_text(encoding='utf-8-sig').splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    rows.append(line)
                    continue
                if record.get('kind') == 'note':
                    record['text'] = '\n'.join(s for s in str(record.get('text') or '').splitlines()
                                               if not s.strip().startswith('rule:'))
                rows.append(json.dumps(record, ensure_ascii=False))
            journal.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    short._save_run(ctx, run)
    files.write_json(Path(job_dir) / 'work' / EFFECTIVE, view['inputs'])
    return run


def review_queue(run):
    """The real app recovers this saved batch on open and sends its own Review request."""
    from letitedit.app import live_review
    from letitedit.timeline import edit_script
    project = Path(run['project'])
    view = run['effective']
    inp = view['inputs']
    batch = project.with_suffix('.letitedit') / 'review' / 'studio-revise'
    script = edit_script.read(project)
    fps = float(script.get('fps') or 30)
    lines, rows = [], []
    for i, note in enumerate(inp.get('notes') or []):
        at = note.get('at_s')
        anchor = live_review.moment(project, project, round(at * fps), fps) if at is not None else None
        rows.append({'id': i, 'text': note['text'], 'frame': round((at or 0) * fps), 'take': False,
                     'studio': {**note, 'anchor': anchor}})
        line = f'{i + 1}. ' + (f'At {at:g} s in the earlier version' if at is not None else 'For the whole video')
        if anchor:
            line += f' (clip {anchor.get("clip")}, source {anchor.get("source_s")} s)'
        if note.get('platform'):
            line += f' on {note["platform"]}'
        lines.append(line + ': ' + note['text'])
    hook = inp.get('hook')
    if hook:
        # Resolve only a finished hooks job, and give the app's hook op its actual candidate.
        import letitedit.studio.service as service
        hook_dir = service.find(short._home(), hook['from_job'])
        result = files.read_json(hook_dir / 'result.json') if hook_dir else None
        candidates = (result or {}).get('output', {}).get('candidates') or []
        candidate = next((c for c in candidates if c.get('hook_id') == hook['hook_id']), None)
        if not result or result.get('state') != 'done' or result.get('kind') != 'hooks' or not candidate:
            unusable('The requested opening is not in a finished hooks job.')
        rows.append({'id': len(rows), 'text': 'Use the selected opening', 'frame': 0, 'take': False})
        lines.append('Use this selected opening with the hook edit op: ' + json.dumps(candidate, ensure_ascii=False))
        lines.append(f'Report the selected opening with letitedit_review_note using note={len(rows) - 1}.')
    if not rows:
        raise state.StudioError('invalid_job', 'Supply a review note or an opening.', stage='apply')
    lines += [
        'Studio reporting: the notes above are pinned to the earlier version, not to times after a trim. '
        'Use their source anchors when earlier changes move them. Read the letitedit router and every skill '
        'the notes need. Do not review or export yet; the next Studio stage does that.',
        f'For each zero-based note index call letitedit_review_note(project={json.dumps(str(project))}, '
        'note=<index>, state="done", what=<what changed>), or state="could_not", why=<reason>. '
        'For a partial change use could_not with both what and why. Never claim a note done without checking it.',
        short.final_rules_text(inp.get('rules') or [])]
    files.write_json(batch / 'notes.json', {'notes': rows})
    files.write_json(batch / 'delivery.json', {'state': 'waiting', 'project': str(project),
                                             'lines': lines, 'takes': '', 'count': len(rows)})
    return batch


def _open(ctx, job_dir, job, run):
    w = short._WINDOWS.get(job['job_id'])
    if w and w.alive():
        return w
    try:
        w = short._window(ctx, job, job_dir, run)
        w.call('open', {'path': run['project']})
        if not w.wait_for(lambda: not (w.call('state', timeout=5) or {}).get('opening'), 90, 1):
            raise state.StudioError('ai_failed', 'The private revision project did not open.', stage='apply')
        return w
    except BaseException:
        short.close_window(job)
        raise


def wait_turn(w, check, stage, dispatched=lambda: True):
    end = time.monotonic() + 7200
    quiet = None
    while time.monotonic() < end:
        check()
        if not w.alive():
            raise state.StudioError('ai_failed', 'The revision window stopped.', stage=stage)
        st = w.chat_state()
        if dispatched() and not st.get('busy') and not st.get('new_video_carry_pending'):
            quiet = quiet or time.monotonic()
            if time.monotonic() - quiet >= short.IDLE_DONE_S:
                return
        else:
            quiet = None
        time.sleep(short.POLL_S)
    raise state.StudioError('ai_failed', 'The revision AI did not finish within two hours.', stage=stage)


def note_report(run, i):
    report = files.read_json(Path(run['folder']) / 'reports' / f'note-{i}.json') or {}
    done = report.get('state') == 'done'
    said = '; '.join(s for s in (report.get('what'), report.get('why')) if s)
    return {'note': i, 'done': 'yes' if done else 'partly' if report.get('what') else 'no',
            'said': said or 'The AI did not record a confirmed change for this note.'}


def reports(run):
    return [note_report(run, i) for i, _ in enumerate(run['effective']['inputs'].get('notes') or [])]


def apply(ctx, job_dir, job, attempt, check=lambda: None):
    run = prepare(ctx, job_dir, job)
    if run['still']:
        return apply_still(ctx, job_dir, job, run, check)
    batch = review_queue(run)
    w = _open(ctx, job_dir, job, run)
    try:
        wait_turn(w, check, 'apply', lambda: (files.read_json(batch / 'delivery.json') or {}).get('state') != 'waiting')
        # Save only this job's window; failure must not silently hand the earlier project onward.
        if not short.save_window(job, job_dir, 'apply', Path(run['project'])):
            raise state.StudioError('ai_failed', 'The changed private project could not be saved.', stage='apply')
        run['changes'] = reports(run)
        if run['effective']['inputs'].get('hook'):
            run['hook_change'] = note_report(run, len(run['changes']))
        run['applied'] = True
        short._save_run(ctx, run)
    finally:
        short.close_window(job)


def review(ctx, job_dir, job, attempt, check=lambda: None):
    run = short._run(ctx)
    view = run['effective']
    if run['still']:
        still.draw(ctx, job_dir, view, attempt, check)
        still.check(ctx, job_dir, view, attempt, check)
        return
    if run['tier'] == 'preview':
        return
    from letitedit.app import new_video_stages
    project = Path(run['project'])
    side = project.with_suffix('.letitedit')
    handover = side / 'revise-handover.md'
    handover.write_text('Revision notes and outcomes:\n' + json.dumps(run['changes'], ensure_ascii=False) +
                        '\nKeep all unrelated choices. A note that keeps the rest as it is keeps its content and '
                        'choices, not its faults: fixing a clipped word, a cut through a sound or another fault the '
                        'review finds is a repair, never a change the note forbids. A note with a measurable target '
                        '(a length, a level, a size) keeps it: a repaired join is fixed within the target, at the '
                        'clean cut point nearest it, with any time it needs taken from elsewhere, never by giving '
                        "the note's change back; the review measures each target. The review that hands the video "
                        "over is the one on the export to deliver (render='final'). The earlier job is unchanged.\n",
                        encoding='utf-8')
    request = (side / short.REQUEST_FILE).read_text(encoding='utf-8-sig') if (side / short.REQUEST_FILE).exists() else ''
    request = request or f'Review the revised video at {project}. Keep the saved brief and creative choices.'
    request += ('\nStudio outcome reporting: after the review fixes and final export, update '
                'letitedit_review_note for any note whose outcome changed during review. Use the original '
                'zero-based note index. A partial change uses state="could_not" with both what (what was '
                'achieved) and why (what could not be kept). Do not leave a note marked done if a review '
                'fix changed that outcome. Original notes: ' +
                json.dumps(view['inputs'].get('notes') or [], ensure_ascii=False))
    rules = view['inputs'].get('rules') or []
    request += '\n' + short.final_rules_text(rules)
    if rules:
        request += '\nAfter review, add one journal note per rule: ' + json.dumps(rules, ensure_ascii=False)
        request += ('\nUse `rule:<id>: applied|not_applicable|not_met|could_not_check: '
                    '<one plain line> @<start>-<end>`. A prefer not met never changes the verdict on its own. '
                    + short.PREFER_NOTE)
    text = new_video_stages.fresh_request(request, side, 'finish', handover)
    w = _open(ctx, job_dir, job, run)
    from letitedit.review import review_bundle
    review_bundle.unattended(project, True)     # no person at this window: an edit after hand-over is decided by code
    try:
        sent = w.call('chat_send', {'text': text, 'summary': 'Review my revised video', 'autonomous': True})
        if not sent.get('sent'):
            raise state.StudioError('ai_failed', 'The AI did not take the revision review.', stage='review')
        wait_turn(w, check, 'review')
        if not short.save_window(job, job_dir, 'review', project):
            raise state.StudioError('ai_failed', 'The reviewed private project could not be saved.', stage='review')
        checked_final(run)
        run['changes'] = reports(run)
        if view['inputs'].get('hook'):
            run['hook_change'] = note_report(run, len(run['changes']))
        short._save_run(ctx, run)
    finally:
        review_bundle.unattended(project, False)
        short.close_window(job)


def target_outcomes(run, changes, duration=None):
    """Each note's outcome with its measured target, if it named one: the delivered value against the asked one in
    `said`, and a note reported done that misses its target beyond the tolerance reads partly. duration: the
    delivered master's length."""
    if not run.get('project'):
        return changes
    from letitedit.review import review_bundle
    try:
        checked = review_bundle.note_target_checks(run['project'], duration)
    except Exception:  # noqa: BLE001 - the outcomes stand as the AI reported them
        return changes
    out = [dict(c) for c in changes]
    for c in checked:
        entry = next((o for o in out if o.get('note') == c['note']), None)
        if entry is None or c.get('met') is None:
            continue
        said = str(entry.get('said') or '').rstrip(' .')
        entry['said'] = (said + '. ' if said else '') + 'Measured: ' + c['line'].split(': ', 1)[-1] + '.'
        if not c['met'] and entry.get('done') == 'yes':
            entry['done'] = 'partly'
    return out


def checked_final(run):
    """The delivered master must be the reviewed file, after the latest timeline transaction."""
    from letitedit.timeline import project_journal
    bundle = short._review_bundle(run['folder'], run['since'])
    master = short.final_export(run['folder'], run['since'])
    if bundle and master:
        data = files.read_json(bundle) or {}
        identity = data.get('video') or {}
        changes = project_journal.entries(run['project'], None)
        edits = []
        for entry in changes:
            # markers change neither picture nor sound: a markers-only change (letitedit_bin's) is no edit to the cut
            if entry.get('kind') in ('apply', 'undo') and not (entry.get('kind') == 'apply' and entry.get('markers_only') is True):
                try:
                    edits.append(datetime.fromisoformat(entry['time'].replace('Z', '+00:00')).timestamp())
                except (KeyError, ValueError, TypeError):
                    pass
        last_edit = max(edits or [0])
        if isinstance(identity, dict) and identity.get('file') and \
                short._norm(identity['file']) == short._norm(master) and \
                bundle.stat().st_mtime + 1 >= last_edit and Path(master).stat().st_mtime + 1 >= last_edit:
            with Path(master).open('rb') as stream:
                digest = hashlib.sha1(stream.read(1 << 20)).hexdigest()
            if identity.get('bytes') == Path(master).stat().st_size and identity.get('sha1_first_mb') == digest:
                return master
    raise state.StudioError('ai_failed', 'The AI stopped without a review of the revised final export after its last edit.',
                            stage='review')


def export(ctx, job_dir, job, attempt, check=lambda: None):
    run = short._run(ctx)
    if run['still'] or run['tier'] == 'preview':
        return
    checked_final(run)
    return short.export_files(ctx, job_dir, run['effective'], attempt, check)


def proxy(ctx, job_dir, job, attempt, check=lambda: None):
    run = short._run(ctx)
    view = run['effective']
    if run['still']:
        result = still.export(ctx, job_dir, view, attempt, check)
    elif run['tier'] == 'preview':
        # No further AI, review, or platform delivery. Short's draft-caption/proxy path is shared.
        result = short.preview_result(ctx, job_dir, view, attempt, check)
    else:
        result = short.final_result(ctx, job_dir, view, attempt, check)
    changed = run['changes'] if run['still'] or run['tier'] == 'preview' else target_outcomes(run, run['changes'])
    lines = [c['said'] for c in changed]
    if run.get('hook_change'):
        lines.append('Opening: ' + run['hook_change']['said'])
    result['output'].update(revision_of=job['from_job'], changes=changed,
                            what_changed=' '.join('; '.join(lines).splitlines()) or 'No confirmed change was recorded.')
    if not run['still']:
        result['extra']['tier'] = run['tier']
        # Short's session-log grouping can span a long pause between revision attempts.
        # Keep measured total usage; omit optional stage durations rather than count that pause.
        result['cost'].pop('stages', None)
    # Keep IDs of known moments even when an index ledger is no longer present on this machine.
    preserve_moments(result['extra'], run['before'])
    return result


def preserve_moments(shared, before):
    old = (before.get('provenance') or {}).get('sources') or []
    for source in (shared.get('provenance') or {}).get('sources') or []:
        mids = list(source.get('moment_ids') or [])
        for prior in old:
            if source.get('file_id') and source.get('file_id') == prior.get('file_id') and source.get('in', 0) <= prior.get('out', 0) and \
                    source.get('out', 0) >= prior.get('in', 0):
                mids += [m for m in prior.get('moment_ids') or [] if m not in mids]
        if mids:
            source['moment_ids'] = mids
    if 'choices' in shared:
        shared['choices']['moments'] = [
            {'moment_id': mid, 'file_id': s['file_id'], 'in': s['in'], 'out': s['out']}
            for s in shared.get('provenance', {}).get('sources', []) for mid in s.get('moment_ids', [])]


def apply_still(ctx, job_dir, job, run, check):
    """AI translates notes to the still renderer's existing data, never executable code."""
    view, folder = run['effective'], still.work(job_dir)
    data = still.read(job_dir)
    pictures = [p['path'] for p in data.get('pages') or [] if Path(p['path']).is_file()]
    prompt = ('Apply the supplied plain revision notes to this saved still. Return JSON only: '
              '{"inputs":{optional layout,text,pictures},"placement":"top|bottom",'
              '"font":"installed family or existing font","background":"#rrggbb",'
              '"changes":[{"note":0,"done":"yes|partly|no","said":"what changed or why not"}]}. '
              'Keep every unmentioned field, picture and choice. Text must be supplied by the caller, '
              'not invented quotations or claims. Picture choices must be existing local files supplied '
              'in the inputs or explicitly named in a note, never a download. Only the supplied layouts '
              'and their text fields are supported. If a note cannot be implemented, report no and why.\n' +
              json.dumps({'inputs': view['inputs'], 'saved': {k: data.get(k) for k in
                         ('layout', 'text', 'font', 'placement', 'background')},
                         'layouts': still.drawing.LAYOUTS}, ensure_ascii=False))
    answer = still_ai.ask(job, folder, 'apply', prompt, pictures, check)
    changes = answer.get('changes')
    notes = view['inputs'].get('notes') or []
    if not isinstance(changes, list) or len(changes) != len(notes) or \
            {c.get('note') for c in changes} != set(range(len(notes))) or any(
                c.get('done') not in ('yes', 'partly', 'no') or not c.get('said') for c in changes):
        raise state.StudioError('ai_failed', 'The AI did not account for each still revision note.', stage='apply')
    patch = answer.get('inputs') or {}
    if not isinstance(patch, dict) or set(patch) - {'layout', 'text', 'pictures'}:
        raise state.StudioError('ai_failed', 'The AI changed unsupported still inputs.', stage='apply')
    previous = copy.deepcopy(view['inputs'])
    inp = {**previous, **patch}
    if 'text' in patch and inp['layout'] == previous['layout']:
        inp['text'] = {**previous.get('text', {}), **patch['text']}
    for picture in patch.get('pictures') or []:
        path = picture.get('path')
        inherited = [p.get('path') for p in view['inputs'].get('pictures') or []]
        inherited += [p.get('path') for p in data.get('pictures') or []]
        if path and path not in inherited and not any(path in n['text'] for n in notes):
            raise state.StudioError('ai_failed', 'The AI chose a picture the caller did not supply.', stage='apply')
    text = still.validate_inputs(inp)
    view['inputs'] = inp
    if inp['layout'] != data['layout'] or inp.get('pictures') != previous.get('pictures'):
        still.layout(ctx, job_dir, view, 1, check, guidance='; '.join(n['text'] for n in notes))
        data = still.read(job_dir)
    data.update(layout=inp['layout'], text=text, since=run['since'], ai_choice=still_ai.choice(job)[0])
    for key in ('placement', 'font', 'background'):
        if key in answer:
            data[key] = answer[key]
    if data.get('placement') not in ('top', 'bottom'):
        raise state.StudioError('ai_failed', 'The AI chose an unsupported still placement.', stage='apply')
    data['font'] = still.drawing.font_family(data.get('font'))
    data.pop('pages', None)
    still.save(job_dir, data)
    run.update(effective=view, earlier_job=view, changes=sorted(changes, key=lambda c: c['note']), applied=True)
    short._save_run(ctx, run)
    files.write_json(Path(job_dir) / 'work' / EFFECTIVE, inp)


STAGES = [('apply', apply), ('review', review), ('export', export), ('proxy', proxy)]


def stages():
    from letitedit.core import jobs

    def measured(fn):
        def stage(ctx, job_dir, job, attempt, check=lambda: None):
            try:
                return fn(ctx, job_dir, job, attempt, check)
            except (state.StudioError, jobs.Cancelled) as exc:
                run = short._run(ctx)
                if run.get('still'):
                    exc.cost = still.cost(still.work(job_dir))
                elif run.get('folder'):
                    exc.cost = short._cost(job, run['folder'], run['since'])
                    exc.cost.pop('_models', None)
                    exc.cost.pop('stages', None)
                    if job.get('ai'):
                        exc.cost['ai'] = job['ai']
                raise
        return stage
    return [(name, measured(fn)) for name, fn in STAGES]
