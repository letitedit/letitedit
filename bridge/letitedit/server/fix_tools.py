"""MCP tool letitedit_fix: fix-in-post repairs (night/noise, shake, punch-in, voice) of a file range or a project clip.

    run_fix(target, item=None, fix=None, start=None, end=None, settings=None, action=None, job=None, fps=None,
            size=None, sheet_frames=3, handles_s=1.0, actor=None, kind=None)   same as the tool, without MCP
    job(ctx)                                             the 'fix_tools:job' job kind (make or apply as a job)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import letitedit.review.fix_post as fix_post

JOB_KIND = 'fix_tools:job'
PER_FRAME_S = {'scunet': 1.5, 'nlmeans': 0.15, 'hqdn3d': 0.02, 'none': 0.02, 'vidstab': 0.06, 'deshake': 0.05,
               'realesrgan-x2plus': 0.5, 'realesr-general-x4v3': 0.15}
JOB_OVER_S = 45.0       # job=None: estimated work above this many seconds runs as a background job


def _is_project(target):
    t = str(target)
    return t.lower().endswith('.mlt') or Path(t).is_dir()


def _spec(fix, settings):
    spec = fix_post.normalise(fix if fix is not None else 'night')
    spec.update(settings or {})
    return fix_post.normalise(spec)


def estimate_s(spec, dur, fps, w=1920, h=1080):
    """Rough seconds of work for a fix (for job=None)."""
    s = fix_post.settings_for(spec)
    kind = spec['kind']
    if kind == 'voice':
        return 8.0 + dur * 0.6
    if kind == 'night':
        eng = fix_post.resolve_engine('night', s)
    elif kind == 'shake':
        eng = fix_post.resolve_engine('shake', s)
    else:
        eng = s['engine'] if s['engine'] != 'auto' else 'realesrgan-x2plus' if fix_post.gpu_ok() else 'none'
    k = (w * h) / (1920 * 1080)
    return 6.0 + dur * fps * PER_FRAME_S.get(eng, 0.2) * k


def _item(script, item_id):
    for t in script['tracks']:
        for it in t['items']:
            if it.get('id') == item_id:
                return t, it
    raise KeyError(f'no clip with id {item_id!r} in the project')


def _item_range(it, handles_s, info):
    sp = float(it.get('speed', 1.0))
    import letitedit.timeline.edit_script as es
    a = max(0.0, es.to_seconds(it['in']) - handles_s * sp)
    b = es.to_seconds(it['out']) + handles_s * sp
    dur = float(info.get('duration') or 0)
    if dur:
        b = min(b, dur)
    return round(a, 4), round(b, 4), sp


def _brief(r):
    m = r.get('measures') or {}
    bef, aft = m.get('before') or {}, m.get('after') or {}
    keys = [k for k in ('brightness', 'dark_share', 'noise', 'sharpness', 'naive_sharpness', 'shake_px', 'motion_px',
                        'lufs', 'floor_db', 'speech_db', 'range_db') if k in bef or k in aft]
    took = 'cached' if r.get('cached') else f"took {r.get('took_s')} s"
    lines = [f"{r['kind']} fix of {Path(r['source']).name} {r['start']:.2f}-{r['end']:.2f}s: engine {r['engine']}, "
             f"{took}"
             f"{', ' + str(r['size'][0]) + 'x' + str(r['size'][1]) if r.get('size') else ''}"
             f"{', ' + str(r['fps']) + ' fps' if r.get('fps') else ''}",
             f"file: {r['file']}" + (f" (offset {r['offset']} s)" if r.get('offset') else '')]
    if keys:
        lines.append('measure        before -> after')
        for k in keys:
            lines.append(f'{k:<14} {bef.get(k, "-")} -> {aft.get(k, "-")}')
    for k in ('gamma', 'filters_after_denoise', 'crop_px', 'upscale_factor', 'focus_sources'):
        if r.get(k) is not None:
            lines.append(f'{k}: {r[k]}')
    if r.get('stems'):
        lines.append('stems: ' + ', '.join(f'{k} {v}' for k, v in r['stems'].items()))
    if r.get('sheet'):
        lines.append(f"sheet: {r['sheet']}")
    if r.get('auto_separate') and r['auto_separate'].get('why'):
        lines.append(f"separate auto chose {r['auto_separate']['chose']}: {r['auto_separate']['why']}")
    lines.append('settings: ' + json.dumps(r.get('settings'), sort_keys=True))
    return '\n'.join(lines)


def _read(project):
    """The project as it is now (T298): an open letitedit window's timeline with its unsaved changes, else the saved
    file; 'read' says which."""
    import letitedit.app.live_edit as live_edit
    return live_edit.read(project)


def _write(project, ops, label, actor=None):
    """A fix's change through letitedit_timeline_apply's route (T298): one undo step in an open letitedit window
    (its unsaved changes kept; nothing saved or reloaded), else the saved file with a history copy. Returns the
    apply's result with 'history' (the saved file's undo copy) or 'undo_label' (the window's Undo)."""
    import letitedit.app.live_edit as live_edit
    import letitedit.timeline.edit_script as es
    if live_edit.window_for(project) is None:
        import letitedit.review.review_bundle as review_bundle
        refused = review_bundle.edit_after_handover(Path(str(project)).resolve())   # as letitedit_timeline_apply's route
        if refused:
            raise ValueError(refused)
        return es.apply_changes(project, ops=ops, actor=actor, label=label)
    import letitedit.server.timeline_tools as timeline_tools
    result, _ = timeline_tools.apply_project(str(project), changes=ops, check=False, label=label, actor=actor)
    return result


def _undo_text(r):
    """How a fix's change is undone, from _write's result."""
    if r.get('history'):
        return f"history copy (undo): {r['history']}"
    return f"undo: one step in the letitedit window ({r.get('undo_label') or 'AI edit'})"


def _apply_effect(project, item_id, spec, actor=None):
    import letitedit.timeline.edit_script as es
    script = _read(project)
    _, it = _item(script, item_id)
    effects = list(it.get('effects') or [])
    n = sum(1 for e in effects if isinstance(e, dict) and 'fix' in e)
    effects.insert(n, {'fix': spec})          # after the clip's other fixes, before its other effects
    return _write(project, [{'op': 'effects', 'id': item_id, 'effects': effects}], f"fix {spec['kind']} on {item_id}",
                  actor)


def _prerender(project, item_id, spec, handles_s=1.0, progress=None):
    """Make the repair the clip's fix effect will use (its source range plus handles), at the project size/fps."""
    import letitedit.timeline.edit_script as es
    script = _read(project)
    _, it = _item(script, item_id)
    if 'clip' not in it:
        raise ValueError(f'{item_id} is not a clip of a video or sound file')
    prof = script['profile']
    info = fix_post.probe(it['clip'])
    a, b, sp = _item_range(it, handles_s, info)
    existing = [e['fix'] for e in it.get('effects') or [] if isinstance(e, dict) and 'fix' in e]
    fixes = existing + [spec]
    return fix_post.chain(it['clip'], a, b, fixes, float(prof['fps']) / sp, prof['width'], prof['height'],
                          progress=progress), (a, b, sp)


def _batch_ids(project, items=None, track=None):
    """The clip ids a batch names: `items` (a list of ids) and/or every clip of a video or sound file on `track`
    (a track name, or a list of them). Order kept, duplicates once."""
    import letitedit.timeline.edit_script as es
    ids = [str(i) for i in (items or [])]
    if track:
        names = [track] if isinstance(track, str) else list(track)
        script = _read(project)
        found = {t['name'] for t in script['tracks']}
        missing = [n for n in names if n not in found]
        if missing:
            raise KeyError(f"no track named {', '.join(map(repr, missing))} (tracks: {', '.join(sorted(found))})")
        for t in script['tracks']:
            if t['name'] in names:
                ids += [it['id'] for it in t['items'] if it.get('id') and 'clip' in it]
    return list(dict.fromkeys(ids))


def _has_kind(it, kind):
    return any(isinstance(e, dict) and 'fix' in e and fix_post.normalise(e['fix'])['kind'] == kind
               for e in it.get('effects') or [])


def _apply_many(project, ids, spec, handles_s=1.0, actor=None, progress=None, check=None):
    """Make the repair for every clip in `ids`, then add all their fix effects as ONE change (one undo step).
    A clip that already has a fix of this kind is left as it is; a clip whose repair fails is named, the others go on.
    Returns {'done': [{id, steps}], 'kept': [ids], 'failed': [{id, error}], 'history'}."""
    import letitedit.timeline.edit_script as es
    done, kept, failed = [], [], []
    for n, item_id in enumerate(ids):
        if check:
            check()
        try:
            _, it = _item(_read(project), item_id)
            if 'clip' not in it:
                raise ValueError(f'{item_id} is not a clip of a video or sound file')
            if _has_kind(it, spec['kind']):
                kept.append(item_id)
                continue
            sub = (lambda f, m=None, n=n: progress((n + f) / max(1, len(ids)), m)) if progress else None
            out, rng = _prerender(project, item_id, spec, handles_s, sub)
            done.append({'id': item_id, 'steps': out['steps'], 'range': rng})
        except Exception as e:  # noqa: BLE001 - one clip's failure never stops the others
            failed.append({'id': item_id, 'error': str(e)})
    history = None
    if done:
        script = _read(project)
        ops = []
        for d in done:
            _, it = _item(script, d['id'])
            effects = list(it.get('effects') or [])
            k = sum(1 for e in effects if isinstance(e, dict) and 'fix' in e)
            effects.insert(k, {'fix': spec})
            ops.append({'op': 'effects', 'id': d['id'], 'effects': effects})
        r = _write(project, ops, f"fix {spec['kind']} on {len(done)} clips", actor)
        history = r.get('history')
        undo = _undo_text(r)
    else:
        undo = None
    return {'done': done, 'kept': kept, 'failed': failed, 'history': history, 'undo': undo}


def _many_text(spec, r, took_s=None):
    """The reply for a batch: one short line per clip, the details in the steps' files."""
    lines = [f"{spec['kind']} fix added to {len(r['done'])} clips as one change"
             + (f" ({took_s:.0f} s)" if took_s is not None else '')
             + f"; effect {json.dumps({'fix': spec}, sort_keys=True)}"]
    for d in r['done']:
        last = d['steps'][-1] if d['steps'] else {}
        chose = ''.join(f", separate auto chose {s_['auto_separate']['chose']}" for s_ in d['steps']
                        if (s_.get('auto_separate') or {}).get('chose') is not None)
        lines.append(f"{d['id']}: {'cached' if last.get('cached') else 'made'}{chose}")
    if r['kept']:
        lines.append(f"already had a {spec['kind']} fix, left as they are: {', '.join(r['kept'])}")
    for f in r['failed']:
        lines.append(f"{f['id']}: not fixed: {f['error']}")
    if r.get('undo'):
        lines.append(r['undo'])
    elif r.get('history'):
        lines.append(f"history copy (undo): {r['history']}")
    lines.append("letitedit_fix(target, action='list') lists every clip's fix effects; action='revert' takes one off.")
    return '\n'.join(lines)


def job(ctx):
    """Job kind 'fix_tools:job'. inputs: mode 'make' {source, start, end, fix, fps, size, sheet_frames}, 'apply'
    {project, item, fix, handles_s, actor} or 'apply_many' {project, items, fix, handles_s, actor}."""
    inp = ctx.inputs
    prog = lambda f, m=None: ctx.progress(min(0.95, f), m)  # noqa: E731
    if inp['mode'] == 'apply_many':
        r = _apply_many(inp['project'], inp['items'], inp['fix'], inp.get('handles_s', 1.0), inp.get('actor'), prog,
                        ctx.check)
        return {'applied': bool(r['done']), 'project': inp['project'], 'history': r['history'],
                'text': _many_text(inp['fix'], r), 'fixed': [d['id'] for d in r['done']], 'kept': r['kept'],
                'failed': r['failed']}
    if inp['mode'] == 'make':
        r = fix_post.run(inp['source'], inp.get('start'), inp.get('end'), inp['fix'], fps=inp.get('fps'),
                         size=inp.get('size'), sheet_frames=inp.get('sheet_frames', 3), progress=prog)
        return {'file': r['file'], 'sheet': r.get('sheet'), 'engine': r['engine'], 'text': _brief(r)}
    out, rng = _prerender(inp['project'], inp['item'], inp['fix'], inp.get('handles_s', 1.0), prog)
    ctx.check()
    applied = _apply_effect(inp['project'], inp['item'], inp['fix'], inp.get('actor'))
    return {'applied': True, 'project': str(inp['project']), 'history': applied.get('history'),
            'undo': _undo_text(applied), 'steps': out['steps'], 'range': rng}


def _list_project(project):
    import letitedit.timeline.edit_script as es
    script = _read(project)
    rows = []
    for t in script['tracks']:
        for it in t['items']:
            fx = [e['fix'] for e in it.get('effects') or [] if isinstance(e, dict) and 'fix' in e]
            if fx:
                rows.append({'track': t['name'], 'id': it.get('id'), 'clip': it.get('clip'), 'in': it.get('in'),
                             'out': it.get('out'), 'at': it.get('at'), 'fixes': fx})
    return rows, script['read']


def _auto_line(auto):
    """What `separate: auto` chose for a voice fix and the number behind it (a fact), or ''."""
    if not auto or not auto.get('why'):
        return ''
    return f"\nvoice separate auto chose {auto['chose']}: {auto['why']}"


def _gaps_note(spec, clip, a, b):
    """For a voice fix: what plays between the words of the clip's range, as a fact ('' for other fixes or no words)."""
    if spec.get('kind') != 'voice':
        return ''
    try:
        import letitedit.footage.speech as speech
        return speech.gap_clause(clip, a, b)
    except Exception:  # noqa: BLE001 - no speech lane: nothing to add
        return ''


def _wait_job(job_id, wait_s):
    """The job's status once it has ended, or its latest status after wait_s seconds."""
    import letitedit.core.jobs as jobs
    end = time.monotonic() + max(0.0, float(wait_s or 0))
    while True:
        st = jobs.status(job_id)
        if st.get('state') in ('done', 'failed', 'cancelled') or time.monotonic() >= end:
            return st
        time.sleep(min(3.0, max(0.1, end - time.monotonic())))


def _job_actor(actor):
    """The name a job's edit is made under: the caller's, resolved here. The job runs in a process of its own that can't
    tell which AI started it (it would be 'agent'), and an edit lease under another name refuses the caller's own next
    edit (and the caller's lease refuses the job's)."""
    import letitedit.timeline.project_journal as project_journal
    return project_journal.actor(actor)


def _run_many(target, ids, spec, job, handles_s, actor, wait_s):
    import letitedit.timeline.edit_script as es
    import letitedit.core.jobs as jobs
    if not ids:
        raise ValueError('the batch names no clips (item: a list of clip ids; track: a track name)')
    script = _read(target)
    prof = script['profile']
    est = 0.0
    for item_id in ids:
        _, it = _item(script, item_id)
        if 'clip' not in it:
            raise ValueError(f'{item_id} is not a clip of a video or sound file')
        a, b, sp = _item_range(it, handles_s, fix_post.probe(it['clip']))
        est += estimate_s(spec, b - a, float(prof['fps']) / sp, prof['width'], prof['height'])
    if job or (job is None and est > JOB_OVER_S):
        st = jobs.submit(JOB_KIND, {'mode': 'apply_many', 'project': str(target), 'items': ids, 'fix': spec,
                                    'handles_s': handles_s, 'actor': _job_actor(actor)},
                         label=f"fix {spec['kind']} on {len(ids)} clips")
        job_id = st.get('id') or st.get('job_id')
        if wait_s:
            st = _wait_job(job_id, wait_s)
            if st.get('state') == 'done' and (st.get('outputs') or {}).get('text'):
                return {'text': st['outputs']['text'], 'job': {'job_id': job_id, 'state': 'done'},
                        **{k: st['outputs'].get(k) for k in ('fixed', 'kept', 'failed', 'history')}}
            if st.get('state') in ('failed', 'cancelled'):
                return {'text': f"job {job_id} {st['state']}: {st.get('error') or st.get('message')}",
                        'job': {'job_id': job_id, 'state': st['state']}}
        return {'text': f"job {job_id} queued: makes the {spec['kind']} repair of {len(ids)} clips (estimate "
                        f"{est:.0f} s), then adds all their effects as one change. letitedit_fix(target, job_id=..., "
                        f"wait_s=...) or letitedit_jobs(action='status') gives its result.",
                'job': {'job_id': job_id, 'state': st.get('state')}, 'estimate_s': round(est)}
    t0 = time.monotonic()
    r = _apply_many(target, ids, spec, handles_s, actor)
    return {'text': _many_text(spec, r, time.monotonic() - t0), 'fixed': [d['id'] for d in r['done']],
            'kept': r['kept'], 'failed': r['failed'], 'history': r['history'], 'read': script['read']}


def _job_result(job_id, wait_s):
    """A fix job's result (any mode), after waiting up to wait_s for it to end."""
    st = _wait_job(job_id, wait_s)
    out = st.get('outputs') or {}
    if st.get('state') == 'done':
        text = out.get('text') or (f"job {job_id} done: {'applied, history copy (undo): ' + str(out.get('history')) if out.get('applied') else ''}"
                                    f"{(' file: ' + out['file']) if out.get('file') else ''}")
        return {'text': text, 'job': {'job_id': job_id, 'state': 'done'},
                **{k: out[k] for k in ('fixed', 'kept', 'failed', 'history', 'file', 'sheet') if k in out}}
    return {'text': f"job {job_id} {st.get('state')}: {st.get('message') or ''}"
                    + (f" error: {st['error']}" if st.get('error') else '')
                    + (f" ({round(100 * float(st.get('progress') or 0))}%)" if st.get('state') in ('queued', 'running') else ''),
            'job': {'job_id': job_id, 'state': st.get('state')}}


def run_fix(target, item=None, fix=None, start=None, end=None, settings=None, action=None, job=None, fps=None, size=None,
        sheet_frames=3, handles_s=1.0, actor=None, kind=None, track=None, job_id=None, wait_s=0):
    """See the tool text. Returns {'text', 'sheet'?, ...}."""
    import letitedit.core.jobs as jobs
    if job_id:
        return _job_result(job_id, wait_s)
    if fix is None and kind and action not in ('revert', 'list'):
        fix = kind      # a fix named as `kind` is that fix, never the default night repair in its place
    project = _is_project(target)
    many = project and (isinstance(item, (list, tuple)) or track) and (action in (None, 'apply'))
    if many:
        ids = _batch_ids(target, item if isinstance(item, (list, tuple)) else ([item] if item else []), track)
        return _run_many(target, ids, _spec(fix, settings), job, handles_s, actor, wait_s)
    action = action or ('apply' if project and item else 'list' if project else 'make')
    if action == 'list':
        if project:
            rows, read = _list_project(target)
            text = (f'{len(rows)} clips with fix effects' + ''.join(
                f"\n{r['track']} {r['id']} {Path(r['clip'] or '').name} {r['in']}-{r['out']} at {r['at']}: "
                + '; '.join(json.dumps(f, sort_keys=True) for f in r['fixes']) for r in rows))
            return {'text': text, 'clips': rows, 'read': read}
        rows = fix_post.cached(target if Path(str(target)).is_file() else None)
        return {'text': f'{len(rows)} cached repairs' + ''.join(
            f"\n{r['kind']} {Path(r['source']).name} {r['start']}-{r['end']} {r['engine']} -> {r['file']}"
            for r in rows), 'repairs': rows}
    if action == 'revert':
        if not (project and item):
            raise ValueError('revert takes a project and an item id')
        import letitedit.timeline.edit_script as es
        script = _read(target)
        _, it = _item(script, item)
        effects = list(it.get('effects') or [])
        keep, removed = [], []
        for e in effects:
            if isinstance(e, dict) and 'fix' in e and (kind is None or fix_post.normalise(e['fix'])['kind'] == kind):
                removed.append(e['fix'])
            else:
                keep.append(e)
        if not removed:
            return {'text': f'{item} has no fix effects' + (f' of kind {kind}' if kind else ''), 'removed': []}
        r = _write(target, [{'op': 'effects', 'id': item, 'effects': keep}], f'fix revert on {item}', actor)
        return {'text': f"{item} plays {Path(it['clip']).name} again without: "
                        + '; '.join(json.dumps(x, sort_keys=True) for x in removed)
                        + f"\n{_undo_text(r)}", 'removed': removed, 'history': r.get('history'),
                'read': script['read']}
    spec = _spec(fix, settings)
    if action == 'apply':
        if not (project and item):
            raise ValueError('apply takes a project and an item id')
        import letitedit.timeline.edit_script as es
        script = _read(target)
        _, it = _item(script, item)
        prof = script['profile']
        info = fix_post.probe(it['clip'])
        a, b, sp = _item_range(it, handles_s, info)
        est = estimate_s(spec, b - a, float(prof['fps']) / sp, prof['width'], prof['height'])
        gaps = _gaps_note(spec, it['clip'], es.to_seconds(it['in']), es.to_seconds(it['out']))
        gaps_line = f"\n{Path(it['clip']).name} {gaps}" if gaps else ''
        if job or (job is None and est > JOB_OVER_S):
            st = jobs.submit(JOB_KIND, {'mode': 'apply', 'project': str(target), 'item': item, 'fix': spec,
                                        'handles_s': handles_s, 'actor': _job_actor(actor)},
                             label=f"fix {spec['kind']} {item}")
            if wait_s:
                done = _job_result(st.get('id') or st.get('job_id'), wait_s)
                if done['job']['state'] == 'done':
                    return done
            return {'text': f"job {st.get('id') or st.get('job_id')} queued: makes the {spec['kind']} repair of {item} "
                            f"({b - a:.1f} s of {Path(it['clip']).name}, estimate {est:.0f} s), then adds the effect "
                            f"(letitedit_fix(target, job_id=..., wait_s=...) gives its result)" + gaps_line, 'job': st, 'estimate_s': round(est)}
        t0 = time.monotonic()
        out, rng = _prerender(target, item, spec, handles_s)
        applied = _apply_effect(target, item, spec, actor)
        last = out['steps'][-1] if out['steps'] else {}
        text = (f"{item}: added effect {json.dumps({'fix': spec}, sort_keys=True)}; plays a repaired copy of "
                f"{Path(it['clip']).name} {rng[0]:.2f}-{rng[1]:.2f}s (source path kept on the clip; letitedit_fix "
                f"action='revert' or removing the effect plays the original). {time.monotonic() - t0:.0f} s.\n"
                + '\n'.join(f"step {s_['kind']}: engine {s_['engine']}, {'cached' if s_['cached'] else 'made'}, "
                            f"file {s_['file']}" for s_ in out['steps'])
                + ''.join(_auto_line(s_.get('auto_separate')) for s_ in out['steps'])
                + f"\n{_undo_text(applied)}"
                + ('' if any(s_.get('auto_separate') for s_ in out['steps']) else gaps_line))
        return {'text': text, 'sheet': last.get('sheet'), 'steps': out['steps'], 'history': applied.get('history'),
                'measures': last.get('measures'), 'read': script['read'], **({'gaps': gaps} if gaps else {})}
    # make: a repaired copy of a file range
    src = Path(str(target))
    info = fix_post.probe(src)
    a, b = fix_post._range(info, start, end)
    rate = float(fps or min(float(info.get('fps') or 30), 60.0))
    est = estimate_s(spec, b - a, rate, *(size or (info.get('width') or 1920, info.get('height') or 1080)))
    if job or (job is None and est > JOB_OVER_S):
        st = jobs.submit(JOB_KIND, {'mode': 'make', 'source': str(src), 'start': a, 'end': b, 'fix': spec,
                                    'fps': fps, 'size': size, 'sheet_frames': sheet_frames},
                         label=f"fix {spec['kind']} {src.name}")
        if wait_s:
            done = _job_result(st.get('id') or st.get('job_id'), wait_s)
            if done['job']['state'] == 'done':
                return done
        return {'text': f"job {st.get('id') or st.get('job_id')} queued: {spec['kind']} repair of {src.name} "
                        f"{a:.2f}-{b:.2f}s (estimate {est:.0f} s; letitedit_fix(target, job_id=..., wait_s=...) gives its result)", 'job': st,
                'estimate_s': round(est)}
    r = fix_post.run(src, a, b, spec, fps=fps, size=size, sheet_frames=sheet_frames)
    gaps = '' if r.get('auto_separate') else _gaps_note(spec, str(src), a, b)
    return {'text': _brief(r) + (f'\n{src.name} {gaps}' if gaps else ''), 'sheet': r.get('sheet'), 'result': r,
            **({'gaps': gaps} if gaps else {})}


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_fix(target: str, item: str | list[str] | None = None, fix: str | dict | None = None,
                    start: float | None = None, end: float | None = None, settings: dict | None = None,
                    action: str | None = None, job: bool | None = None, fps: float | None = None,
                    size: list[int] | None = None, sheet_frames: int = 3, handles_s: float = 1.0,
                    kind: str | None = None, actor: str | None = None, track: str | list[str] | None = None,
                    job_id: str | None = None, wait_s: float = 0) -> list:
        """Fix-in-post: a repaired copy of the part of a source a clip uses, made once and cached
        (C:\\LetItEdit\\cache\\fix); the source file is only read. Results report the engine that ran, the time taken,
        every setting with its default, before/after measures and a before/after sheet (returned as a picture).
        fix: 'night' | 'shake' | 'punch' | 'voice' or {kind, ...settings}; settings: more settings.
          night  denoise: auto (SCUNet real-noise model on the GPU, Apache-2.0) | scunet | nlmeans | hqdn3d | none;
                 strength 0.9 (scunet blend with the input; nlmeans s=3.5x; hqdn3d 4x); temporal 3.0 (hqdn3d temporal
                 smoothing after, 0 off); brighten 'auto' (gamma log(brightness)/log(target_luma) when darker, capped
                 at max_gamma) | a gamma | 'off'; target_luma 0.36; max_gamma 1.6; contrast 1.08 (with the
                 brightening); saturation 1.0; tile 0; half true. ~1.5 s per 1080p frame with SCUNet.
          shake  engine auto (vid.stab two-pass) | vidstab | deshake; smoothing 15 (frames each side); shakiness 5;
                 accuracy 15; stepsize 6; optzoom 1 (0 none, 1 static zoom hiding borders, 2 adaptive); zoom 0 (%);
                 maxshift -1; maxangle -1; crop 'black'|'keep'; tripod false; sharpen 0.8; deshake_rx 32.
                 The result's measures give shake_px and motion_px (px on a 480-wide frame) before and after. The crop
                 needed grows with the shake and with smoothing. Large motion of the subject in the frame is followed
                 as camera shake.
          punch  zoom 2.0 (x the frame that fills the output); focus 'auto' (given, tracker results, footage action
                 points, centre) | [x, y] (0-1) | [[source s, x, y], ...] | 'track' | 'action' | 'centre';
                 smooth_s 1.0; deadzone 0.03; min_score 0.3; engine auto (none when the crop has the output's pixels
                 or the PC has no NVIDIA card of about 4 GB, see letitedit_hardware; Real-ESRGAN x2plus up to 2x,
                 realesr-general-x4v3 above; BSD-3) | realesrgan-x2plus |
                 realesr-general-x4v3 | none. Several punch effects with different focus/zoom = several framings.
          voice  separate auto | true | false. false = DeepFilterNet on the whole mix; true = Demucs voice/rest first: only
                 the voice stem is denoised and the rest stem, the sounds that are not the voice, is remixed at rest_gain_db.
                 auto (the default) is settled when the clip is made, from the gaps between its words (speech.gap_fact: the
                 median level of 0.1 s windows more than 0.15 s from any word, in dB over the quietest tenth): true when that
                 median reaches 3 dB in the clip's range or in the whole source file, false below it; no speech found in the
                 range = true; too few gaps to measure = false. Words are transcribed first when missing. An explicit true or
                 false is always used as given. The result states what auto chose and both medians with the limit.
                 separation_model 'htdemucs';
                 dereverb false (true = WPE, taps 10, delay 3, iterations 3); denoise true (DeepFilterNet 3, MIT/Apache);
                 atten_lim_db 18 (dB the noise may be lowered: 12-18 light, 18-30 medium, 100 = no limit, only when the
                 noise beats the voice; unlimited sounds 'underwater'); post_filter false; voice_gain_db 0; rest_gain_db 0
                 (-120 leaves the rest out; with separate true the rest stem keeps background noise such as road noise).
                 With separate false everything but speech counts as noise: on footage with work sounds in the gaps
                 between speech they came out 11-18 dB lower and the speech 1-4 dB lower; with separate true they kept their
                 level (within 0.3 dB in 7 of 8 stretches, 2.9 dB lower in one) and the speech lost 0.3-0.7 dB, but
                 steady hiss at rest_gain_db 0 stays. dereverb on a noisy whole
                 mix (separate false) lowered the speech. -120 leaves digital silence.
                 Low rumble is not removed by DeepFilterNet. The result's measures give floor_db, speech_db, range_db;
                 the apply result also gives the clip's 'gaps:' line (windows of 0.1 s between the words, their median
                 and 90th percentile level in dB over the quietest tenth of the clip).
                 Stems are kept as WAV files (paths in the result).
          all    crf 14, preset 'medium', render_lock_over_s 30 (longer renders hold the PC render lock).
        action: 'make' (target = a media file; start/end source seconds; fps default the source's up to 60; size
          [w, h] default the source's) | 'apply' (target = project, item = clip id: adds the effect
          {fix: {kind, ...}} to the clip's effects after its other fixes; the clip keeps its source path and in/out,
          the project plays the repaired copy of its source range plus handles_s each side (default 1.0), at the
          project's size and frame rate) | 'revert' (removes the clip's fix effects, or only those of `kind`; history
          copy kept for undo) | 'list' (a project's clips with fix effects, or the cached repairs of a file / all).
          Default: apply with a project and item, list with a project alone, make with a file.
        Several clips at once: item = a list of clip ids, and/or track = a track name (or names: every clip of a video
          or sound file on it). Each repair is made, then all their effects are added as one change (one undo step,
          one history copy); a clip that already has a fix of the same kind is left as it is, a clip whose repair
          fails is named and the others still get theirs. The reply has one line per clip.
        job: None = a background job (letitedit_jobs) when the estimated work is over 45 s (a batch: its total),
          True/False = always/never. wait_s: seconds this call waits for its job (0 = answer at once); job_id: the
          result of a fix job, waiting up to wait_s for it to end.
        The effect can also be written by hand in letitedit_timeline_apply ({fix: {...}} among a clip's effects);
        fix effects run before the clip's other ffmpeg effects. In an open window the change is one undo step
        there (Ctrl+Z, or letitedit_timeline_undo); otherwise the saved file with a history copy."""
        try:
            rep = run_fix(target, item=item, fix=fix, start=start, end=end, settings=settings, action=action,
                                   job=job, fps=fps, size=size, sheet_frames=sheet_frames, handles_s=handles_s,
                                   actor=actor, kind=kind, track=track, job_id=job_id, wait_s=wait_s)
        except (FileNotFoundError, ValueError, KeyError) as e:
            return [{'error': str(e)}]
        out = []
        if rep.get('sheet') and Path(rep['sheet']).exists():
            out.append(Image(data=Path(rep['sheet']).read_bytes(), format='jpeg'))
        out.append(rep['text'])
        out.append({k: v for k, v in rep.items() if k not in ('text',)})
        return out
