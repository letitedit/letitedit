"""Drawn scenes that follow the cut (T362). On by default.

A code scene is one drawing with its own clock. When an edit trims, cuts or moves the speech under it, what it drew on
a word lands early or late: edit_sync only shortens the scene and says it "runs late against the speech", and in T360's
Run 2 the AI then re-timed the drawing by hand (a time map written into the scene's script and a revise through
Python, 2-7 steps an edit). With this switch on, an edit written to the saved file (no open window: a New video run
or a Studio job) that changes the main picture track does it:

- for every scene item on another track that the edit didn't name itself, the page time on the new timeline is mapped
  through the main track's source moments (edit_sync.mapper, new -> old) to the page time it had before;
- when that map isn't the identity, code_scenes.retime makes a new revision whose script opens with the map
  (pictures.scene_time_map), composed with any map it already has, and the item is set to it in the edit's own undo
  step (no second history copy): undoing the edit takes both back;
- the reply's `scenes_followed` lists them, and the note that the scene runs late against the speech is replaced by
  one saying its drawing follows the cut.

Never raises: the edit stands as it is when a scene can't follow. An open window's edit, a whole-script edit and an
edit that names the scene item (its own trim, move or set) are left alone. The switch: settings.json
`scenes_follow_cut`; LETITEDIT_SCENES_FOLLOW_CUT (1 or 0) wins."""
import json
import os

SETTING = 'scenes_follow_cut'
ENV = 'LETITEDIT_SCENES_FOLLOW_CUT'
LATE_NOTE = 'a scene keeps its own timing'      # edit_sync._scene_timing_note's words


def enabled():
    forced = os.environ.get(ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(SETTING) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


def _named(changes):
    out = set()
    for o in changes or []:
        if not isinstance(o, dict):
            continue
        if o.get('id'):
            out.add(str(o['id']))
        for i in o.get('ids') or []:
            out.add(str(i))
    return out


def _span(script, item_id, fps):
    """(track, start_s, end_s, page time at its start) of item `item_id` on a track that isn't the main one."""
    from letitedit.timeline.edit_sync import layout, main_track, to_seconds
    main = main_track(script)
    for t in script.get('tracks') or []:
        if t is main:
            continue
        for it, s, e in layout(t, fps):
            if it.get('id') == item_id:
                return t, s, e, to_seconds(it.get('in') or 0)
    return None


def cut_map(before, after, item_id):
    """[[p0, p1, q0, q1], ...]: the scene item's page time on `after` -> its page time on `before`, through the main
    track's source moments, frame by frame; stretches over new picture are left out (the clock runs on there). None
    when nothing moved under it or it can't be read."""
    from letitedit.timeline.edit_sync import mapper
    fps = float((after.get('profile') or {}).get('fps') or 30)
    old, new = _span(before, item_id, fps), _span(after, item_id, fps)
    if not old or not new:
        return None
    _, s_old, _, in_old = old
    _, s_new, e_new, in_new = new
    back = mapper(after, before)
    if back is None:
        return None
    frame = 1.0 / fps
    runs, cur = [], None
    k0, k1 = int(round(s_new * fps)), int(round(e_new * fps))
    for k in range(k0, k1):
        t = (k + 0.5) / fps
        o = back(t)
        p = in_new + (t - s_new)
        q = None if o is None else in_old + (o - s_old)
        if q is None:
            cur = None
            continue
        if cur is not None:
            step = q - cur['q_last']
            if cur['step'] is None:
                same = 0 < step < 4 * frame                 # a second frame: any forward step starts its slope
            else:
                same = abs(step - cur['step']) < 0.25 * frame
            if same:
                cur['step'] = step if cur['step'] is None else cur['step']
                cur['p_last'], cur['q_last'] = p, q
                continue
        cur = {'p0': p, 'q0': q, 'p_last': p, 'q_last': q, 'step': None}
        runs.append(cur)
    segments = []
    for r in runs:
        slope = (r['step'] / frame) if r['step'] else 1.0
        segments.append([r['p0'] - frame / 2, r['p_last'] + frame / 2,
                         r['q0'] - slope * frame / 2, r['q_last'] + slope * frame / 2])
    segments = [[round(v, 4) + 0.0 for v in s] for s in segments]
    if not segments or all(abs(q0 - p0) < frame / 2 and abs(q1 - p1) < frame / 2 for p0, p1, q0, q1 in segments):
        return None
    return segments


def follow(path, before, changes, label, who, result):
    """After an edit written to the saved file: each scene under the changed picture follows the cut when it may
    (module text). Writes `scenes_followed` and a note into `result`; nothing when off or not needed."""
    if not enabled() or changes is None:
        return
    try:
        import letitedit.timeline.edit_script as es
        from letitedit.timeline.edit_sync import main_track
        after = es.read(path)
        mb, ma = main_track(before), main_track(after)
        if mb is None or ma is None or json.dumps(mb.get('items'), sort_keys=True, default=str) == \
                json.dumps(ma.get('items'), sort_keys=True, default=str):
            return
        named = _named(changes)
        old_ids = {it.get('id') for t in before.get('tracks') or [] for it in t.get('items') or [] if it.get('scene')}
        scenes = [(t, it) for t in after.get('tracks') or [] if t is not ma for it in t.get('items') or []
                  if isinstance(it.get('scene'), dict) and it.get('id') in old_ids]
        uses = {}
        for _, it in scenes:
            uses[it['scene'].get('id')] = uses.get(it['scene'].get('id'), 0) + 1
    except Exception:  # noqa: BLE001 - the edit stands as it is
        return
    import letitedit.pictures.code_scenes as code_scenes
    done, ops = [], []
    for t, it in scenes:
        row = {'id': it['id'], 'scene_id': it['scene'].get('id'), 'track': t.get('name')}
        if it['id'] in named:
            continue                    # the edit changed this scene itself: what it asked for stands
        if uses.get(row['scene_id'], 0) != 1:
            done.append({**row, 'followed': False, 'why': 'the scene is on the timeline more than once'})
            continue
        try:
            segments = cut_map(before, after, it['id'])
            if not segments:
                continue
            marker = code_scenes.retime(path, row['scene_id'], segments)
            if not marker:
                continue
            ops.append({'op': 'set', 'id': it['id'], 'scene': marker})
            done.append({**row, 'followed': True, 'revision': marker['revision'], 'was': it['scene'].get('revision'),
                         'pieces': len(segments), 'map': segments[:12]})
        except Exception as error:  # noqa: BLE001 - this scene keeps its own clock, as without the switch
            done.append({**row, 'followed': False, 'why': f'{type(error).__name__}: {str(error)[:200]}'})
    if ops:
        try:
            es.apply_changes(path, ops=ops, keep_history=False, actor=who,
                             label=f'{label or "edit"}: scenes follow the cut')
        except Exception as error:  # noqa: BLE001 - the edit stands; the scenes keep their own clock
            for row in done:
                if row.get('followed'):
                    row.update(followed=False, why=f'{type(error).__name__}: {str(error)[:200]}')
    if not done:
        return
    result['scenes_followed'] = done
    followed = [r for r in done if r.get('followed')]
    notes = result.setdefault('notes', [])
    if followed:
        ids = {r['id'] for r in followed}
        notes[:] = [n for n in notes if not (isinstance(n, str) and LATE_NOTE in n
                                             and any(n.startswith(f'{i} on ') for i in ids))]
        for r in followed:
            notes.append(f"{r['id']} on {r['track']} (a scene): its drawing follows the cut, in this edit's own undo "
                         f"step: scene {r['scene_id']} is now revision {r['revision']}, whose script opens with a time map "
                         f"(page time now -> the time the drawing was made for; {r['pieces']} piece(s)). The times in "
                         "the script stay the drawing's own; nothing needs re-timing for this edit.")
    for r in done:
        if not r.get('followed'):
            notes.append(f"{r['id']} on {r['track']} (a scene) couldn't follow the cut ({r['why']}); it keeps its own "
                         "clock")
