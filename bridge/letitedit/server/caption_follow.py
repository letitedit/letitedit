"""Captions that follow their fit through an edit (T360). On by default.

letitedit-firstcut's "Captions after the last edit" has the AI run letitedit_caption_fit again after every picture,
opening or caption edit and apply its plan when it covers fewer faces. In T358's Azure runs that was 6 and 10 fit
calls in one review, each its own step. With this switch on, the edit does it:

- letitedit_caption_fit remembers the arguments of each fit it makes (remember_fit) and, once one is applied (with
  apply=True or by its plan_id), keeps them as the project's last fit (remember_applied), beside the project in its
  side folder (`<name>.letitedit/caption-fit-last.json`);
- a letitedit_timeline_apply written to the saved file (no open window: a New video run or a Studio job) that changes
  anything on a video or caption track then runs that fit again on the edited project (no render check) and applies
  its plan through caption_layout.apply_plan's own rules: refused when it covers more faces than the captions do now,
  when a word would be lost, when the plan is stale or the run was handed over. The plan goes into the edit's own undo
  step (no second history copy): undoing the edit takes both back;
- the reply's `captions_followed` says what happened ({applied, covers_face: [now, after the plan], left, plan_id} or
  {applied: false, why}), and a note line says so in words.

Never raises: the edit stands as it is when the fit can't run. An open window's edit, an edit that only touches sound
tracks, and caption_fit's own apply are left alone. The switch: settings.json `captions_follow_fit`;
LETITEDIT_CAPTIONS_FOLLOW_FIT (1 or 0) wins."""
import json
import os
import time
from pathlib import Path

SETTING = 'captions_follow_fit'
ENV = 'LETITEDIT_CAPTIONS_FOLLOW_FIT'
ARGS_FILE = 'caption-fit-args.json'      # plan_id -> the fit's arguments (the newest ARGS_KEPT)
LAST_FILE = 'caption-fit-last.json'      # the last fit applied: {plan_id, args, at}
ARGS_KEPT = 20
# the fit's own arguments a re-fit repeats; `style` is left out (a look applied once, which later edits may change),
# and so are where it writes and how much it renders
KEEP = ('tracks', 'platform', 'lock', 'min_size_px', 'protected', 'faces', 'placements', 'prefer', 'regroup',
        'native_mode', 'max_lines', 'max_cps', 'min_duration_s', 'max_duration_s', 'keep_together', 'min_gap_em',
        'peak_gap_em', 'platform_zones')
FIT_NOTE = 'letitedit_caption_fit'       # the note on every op a fit plan makes (caption_layout_solve)
FIT_LABEL = 'Caption fit'                # caption_layout.apply_plan's label


def enabled():
    """Whether an edit re-fits the captions (default on; the environment variable, 1 or 0, wins)."""
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


def _side(project):
    p = Path(project)
    return p.with_name(p.stem + '.letitedit')


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    os.replace(temp, path)


def kept_args(args):
    """The arguments a re-fit repeats: KEEP's, without the ones left at None."""
    return {k: args[k] for k in KEEP if args.get(k) is not None}


def remember_fit(project, plan_id, args):
    """A fit's arguments under its plan_id (with the switch on), so an apply by plan_id knows them."""
    if not (enabled() and project and plan_id):
        return
    try:
        path = _side(project) / ARGS_FILE
        rows = [r for r in (_read(path) or []) if isinstance(r, dict) and r.get('plan_id') != plan_id]
        rows.append({'plan_id': plan_id, 'args': kept_args(args)})
        _write(path, rows[-ARGS_KEPT:])
    except Exception:  # noqa: BLE001 - bookkeeping: the fit stands without it
        pass


def remember_applied(project, plan_id, args=None):
    """The fit applied last (with the switch on): its arguments, given or remembered under its plan_id."""
    if not (enabled() and project):
        return
    try:
        if args is None:
            rows = _read(_side(project) / ARGS_FILE) or []
            args = next((r.get('args') for r in reversed(rows) if isinstance(r, dict) and r.get('plan_id') == plan_id),
                        None)
        if args is None:
            return
        _write(_side(project) / LAST_FILE, {'plan_id': plan_id, 'args': kept_args(args),
                                            'at': time.strftime('%Y-%m-%dT%H:%M:%S')})
    except Exception:  # noqa: BLE001
        pass


def last(project):
    rec = _read(_side(project) / LAST_FILE)
    return rec if isinstance(rec, dict) and isinstance(rec.get('args'), dict) else None


def _items(script):
    """{(track, id or position): item} of the video tracks (every track whose kind isn't audio) and of the captions,
    which the timeline script keeps apart from the tracks, in its `captions` list (Shotcut's subtitle feeds: T360's
    first Azure run with the switch on re-fitted after picture edits but never after a caption edit)."""
    out = {}
    for t in (script or {}).get('tracks') or []:
        if str(t.get('kind') or '').lower() == 'audio':
            continue
        for i, it in enumerate(t.get('items') or []):
            out[(t.get('name'), it.get('id') or i)] = json.dumps(it, sort_keys=True, default=str)
    for i, cap in enumerate((script or {}).get('captions') or []):
        out[('captions', cap.get('track') if isinstance(cap, dict) else i)] = json.dumps(cap, sort_keys=True,
                                                                                      default=str)
    return out


def picture_changed(before, after):
    """Whether the edit from script `before` to `after` changed anything on a video track or in the captions."""
    return _items(before) != _items(after)


def _fit_apply(changes, label):
    if label == FIT_LABEL:
        return True
    ops = [o for o in changes or [] if isinstance(o, dict)]
    return bool(ops) and all(str(o.get('note') or '').startswith(FIT_NOTE) for o in ops)


def follow(path, before, changes, label, who, result):
    """After an edit written to the saved file: the project's last caption fit run again and applied when it may be
    (module text). Writes `captions_followed` and a note into `result`; nothing when off or not needed."""
    if not enabled() or _fit_apply(changes, label):
        return
    rec = last(path)
    if not rec:
        return
    try:
        import letitedit.timeline.edit_script as es
        if not picture_changed(before, es.read(path)):
            return
        import letitedit.pictures.caption_layout as caption_layout
        plan = caption_layout.fit(str(path), render_check_frames=False, **rec['args'])
    except Exception as error:  # noqa: BLE001 - the edit stands as it is
        result['captions_followed'] = {'applied': False, 'why': f'the fit could not run: {type(error).__name__}: '
                                                                f'{str(error)[:200]}'}
        result.setdefault('notes', []).append("letitedit couldn't re-fit the captions after this edit "
                                              f"({type(error).__name__}); run letitedit_caption_fit if they need it")
        return
    now, then = caption_layout.faces_covered(plan)
    left = len([v for v in plan.get('violations') or [] if v.get('stage') == 'after'])
    out = {'covers_face': [now, then], 'left': left, 'unresolved': len(plan.get('unresolved') or []),
           'plan_id': plan.get('plan_id'), 'tracks': rec['args'].get('tracks'), 'platform': rec['args'].get('platform'),
           'seconds': plan.get('seconds')}
    faces = plan.get('faces') or {}
    if faces.get('sampled') is not None:     # T362: face frames rendered again / sampled (the rest came from the cache)
        out['face_frames_rendered'] = [faces['sampled'] - int(faces.get('cache_hits') or 0), faces['sampled']]
    settings = ', '.join(f'{k} {rec["args"][k]}' for k in ('platform', 'faces', 'tracks') if rec['args'].get(k))
    if not plan.get('changes'):
        out.update(applied=False, why='the captions already fit')
        result['captions_followed'] = out
        result.setdefault('notes', []).append(f"letitedit re-ran the last caption fit after this edit ({settings}): "
                                              'the captions already fit; no caption_fit call is needed for this edit')
        return
    try:
        applied = caption_layout.apply_plan(plan, via='file', keep_history=False,
                                            label=f'{label or "edit"}: captions follow the fit', actor=who)
        out['applied'] = bool(applied.get('applied'))
        out['words_kept'] = all(k.get('identical') for k in applied.get('words_kept') or [])
        remember_applied(path, plan.get('plan_id'), rec['args'])
        result.setdefault('notes', []).append(
            f"letitedit re-fitted the captions after this edit with the last caption fit's settings ({settings}), in "
            f"this edit's own undo step: captions over a face {now} -> {then}, {left} placement problem(s) left "
            f"(plan {plan.get('plan_id')}). No caption_fit call is needed for this edit.")
    except Exception as error:  # noqa: BLE001 - Refused, Conflict or a failure: the edit stands as it is
        out.update(applied=False, why=str(error)[:300])
        result.setdefault('notes', []).append(f"letitedit's re-fit of the captions after this edit wasn't applied: "
                                              f"{str(error)[:200]}")
    result['captions_followed'] = out
