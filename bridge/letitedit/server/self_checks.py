"""Ops that check their own result (T345 C3, T344's lever 5). On by default.

With the switch on, letitedit_timeline_apply measures two ops' results by the same measures as the separate tools,
and its reply carries what those tools would have said:

- **{op: score}** aims at a measured music level. Before the apply, the planned timeline is compiled into a scratch
  copy beside the project and measured with check_audio's own stem measure (review.checks.audio, stems on, its other
  settings at letitedit_check_audio's defaults): how far the music sits under the voice while people talk
  (`music_below_voice_while_talking_lu`). When that is more than TOLERANCE_LU from the aim, the op's talk level moves
  by the difference and the copy is measured again (AIMS times at most). The apply then writes the op with the level
  found, as one undo step. After it, the reply's self_check.score is letitedit_check_audio(project, stems=True)'s own
  report on the project as written (check_tools.measure_audio): the copy's measurement is reused when the copy's
  sound signature is the project's, else the project is measured again.
  The aim: the op's `under_voice_lu`, else its own talk level (`levels.talk`, the Look's or -18: 18 LU under).
  `measure: false` on the op leaves it unmeasured.
- **{op: captions, fit: {...}}** fits and checks its own captions. After the apply, caption_fit runs on the project
  with fit's arguments (letitedit_caption_fit's; tracks: the op's track) and apply=True, then caption_readability.
  The reply's self_check.captions holds both tools' replies and one verdict (caption_verdict). caption_fit's apply is
  an undo step of its own. caption_fit reads the saved file, so in a window whose edit was not saved the fit is not
  run and the reply says so.

- **The picture under the words** (T349, with review_craft_checks on as well): after an apply that changes the
  picture (any op but score, level, captions, master and declick), the reply's self_check.picture holds the review's
  own measured facts on the cut as written, before any export (review.picture_words.cut): a whip, a fast camera move or
  shake under a line that points at something to be seen or under a must-keep line (major), a long one under other
  words (minor), and b-roll in the footage that the cut never shows. Facts only; the reply names no fix.

The switch: settings.json `self_checks` (default true; LETITEDIT_SELF_CHECKS, 1 or 0, wins). It also covers the
session runner's two parts of T345 C3 (studio/session_runner.py: the review's code checks before its phase, the
phase's tools loaded up front). Off, `under_voice_lu` and `fit` are refused and nothing here runs.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

SETTING = 'self_checks'
ENV = 'LETITEDIT_SELF_CHECKS'
TOLERANCE_LU = 1.0          # a measured music level this close to the aim is on it
AIMS = 2                    # corrections of the talk level at most (each one measured)
TALK_RANGE = (-60.0, 0.0)   # the talk level a correction may set (dB against the dialogue)
AUDIO = {'stems': True, 'target_lufs': -14.0, 'start_s': None, 'end_s': None, 'every_s': None, 'quiet_lu': 15.0}
GAP = 'music_below_voice_while_talking_lu'
OFF = 'needs the self_checks setting on (settings.json self_checks, or LETITEDIT_SELF_CHECKS=1)'


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


def _ops(changes, kind):
    return [o for o in changes or [] if isinstance(o, dict) and o.get('op') == kind]


def refused(changes):
    """With the switch off, the fields only it serves: a plain refusal, or None."""
    if enabled():
        return None
    asked = [f"{o['op']}'s {k}" for o in changes or [] if isinstance(o, dict)
             for k in (('under_voice_lu',) if o.get('op') == 'score' else ('fit',) if o.get('op') == 'captions' else ())
             if o.get(k) not in (None, False)]
    return f"{', '.join(asked)} {OFF}" if asked else None


# ------------------------------------------------------------------------------------------------ score

def _talk_level(op, script):
    import letitedit.timeline.edit_script as es
    zones = {**(es.kit_for(script).get('music') or {}).get('zones', {}), **(op.get('levels') or {})}
    return float(zones.get('talk', -18.0))


def _scratch(path):
    import letitedit.timeline.project_journal as project_journal
    work = project_journal.folder(Path(path).resolve()) / 'self_check' / 'score'
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    return work


def aim_score(path, changes, before_path=None):
    """Before an apply: (changes, record). The last measured {op: score} in changes gets the talk level whose measured
    music level is on its aim; record (None when there is nothing to aim) carries the measurements and the scratch
    copy for after_score. before_path: the .mlt the apply starts from (a window's snapshot), else the saved file."""
    ops = [o for o in _ops(changes, 'score') if o.get('measure', True) is not False]
    if not enabled() or not ops:
        return changes, None
    import letitedit.pictures.caption_layout as caption_layout
    import letitedit.review.checks as checks
    import letitedit.timeline.edit_script as es
    source = str(before_path or path)
    op = ops[-1]
    index = next(i for i, o in enumerate(changes) if o is op)
    talk = _talk_level(op, es.read(source))
    aim = float(op['under_voice_lu']) if op.get('under_voice_lu') is not None else -talk
    record = {'aim_lu': round(aim, 1), 'tolerance_lu': TOLERANCE_LU, 'tries': [], 'talk_db': round(talk, 2)}
    work = _scratch(path)
    level, trial = talk, list(changes)
    for n in range(AIMS + 1):
        trial = list(changes)
        if n:
            trial[index] = {**op, 'levels': {**(op.get('levels') or {}), 'talk': round(level, 2)}}
        try:
            mlt = caption_layout.compile_after(source, trial, work)
            png, report = checks.audio(str(mlt), **AUDIO)
        except Exception as e:  # noqa: BLE001 - the op goes in as given; the reply says it wasn't measured
            record['not_measured'] = f'the planned timeline could not be measured ({type(e).__name__}: {e})'[:600]
            return changes, record
        gap = report.get(GAP)
        record['tries'].append({'talk_db': round(level, 2), 'measured_lu': gap})
        record.update(talk_db=round(level, 2), scratch=str(mlt), png=png, report=report)
        if gap is None:
            record['not_measured'] = ('the music\'s level under the voice needs 2 s or more of talk with music; '
                                      'the op went in as given')
            return changes, record
        if abs(gap - aim) <= TOLERANCE_LU or n == AIMS:
            break
        level = max(TALK_RANGE[0], min(TALK_RANGE[1], level + (gap - aim)))
    return trial, record


def after_score(path, record):
    """After the apply: check_audio(stems=True)'s own report on the project as written, with the aim beside it."""
    import letitedit.review.checks as checks
    import letitedit.server.check_tools as check_tools
    out = {k: record[k] for k in ('aim_lu', 'tolerance_lu', 'talk_db', 'tries', 'not_measured') if k in record}
    if record.get('scratch') and record.get('report') is not None and not record.get('not_measured'):
        try:
            with checks.as_window_shows(str(path)):
                written = checks.audio_signature(str(path))
            if written == checks.audio_signature(record['scratch']):
                checks.audio_keep(str(path), written, record['png'], {**record['report'], **checks.reported(str(path))},
                                  **AUDIO)
        except Exception:  # noqa: BLE001 - check_audio measures the project afresh instead
            pass
    try:
        _, report = check_tools.measure_audio(str(path), **AUDIO)
    except Exception as e:  # noqa: BLE001 - the edit stands; the reply says the check didn't run
        out['check_audio'] = {'checked': False, 'reason': f'{type(e).__name__}: {e}'[:600]}
        return out
    out['check_audio'] = report
    gap = report.get(GAP)
    out['measured_lu'] = gap
    if gap is not None:
        out['on_aim'] = abs(gap - record['aim_lu']) <= TOLERANCE_LU
    out['measured_by'] = 'letitedit_check_audio(stems=True) on the project as written'
    return out


# ------------------------------------------------------------------------------------------------ captions

def caption_verdict(fit_reply, readability):
    """One verdict from caption_fit's reply (its summary after the fit) and caption_readability's (passed)."""
    fit_reply, readability = fit_reply or {}, readability or {}
    summary = fit_reply.get('summary') or {}
    problems = []
    if fit_reply.get('error'):
        problems.append(f"caption_fit: {fit_reply['error']}")
    after, unresolved = summary.get('after_total'), summary.get('unresolved')
    if after:
        problems.append(f'caption_fit: {after} problem(s) after the fit ({summary.get("after")})')
    if unresolved:
        problems.append(f'caption_fit: {unresolved} unresolved')
    if readability.get('passed') is not True:
        problems.append('caption_readability: ' + ('not passed' if readability.get('checked', True) is not False
                                                   else 'not checked') +
                        (f" ({str(readability.get('reason'))[:300]})" if readability.get('reason') else ''))
    return {'clear': not problems, 'fit_after_total': after, 'fit_unresolved': unresolved,
            'readable': readability.get('passed'), 'problems': problems}


def after_captions(path, op, result, live=None):
    """After the apply: caption_fit (fit's arguments, apply=True) and caption_readability on the project."""
    import letitedit.server.caption_layout_tools as caption_layout_tools
    import letitedit.server.check_tools as check_tools
    if live and not result.get('saved'):
        return {'fitted': False, 'reason': 'the edit is in an open window and not saved: caption_fit reads the saved '
                                           'file, so it was not run'}
    args = dict(op['fit']) if isinstance(op.get('fit'), dict) else {}
    args.setdefault('tracks', [op['track']])
    args.update(apply=True, plan_id=None, expected_revision=None)
    try:
        sheet, fit_reply = caption_layout_tools.fit(str(path), **args)
    except TypeError as e:
        fit_reply, sheet = {'error': f'fit takes letitedit_caption_fit\'s arguments ({e})'}, None
    readability = (check_tools.caption_readability(str(path)) or [{}])[0]
    return {'fit': fit_reply, 'sheet': sheet, 'readability': readability,
            'verdict': caption_verdict(fit_reply, readability)}


# ------------------------------------------------------------------------------------------------ the picture

NOT_PICTURE = {'score', 'level', 'captions', 'master', 'declick'}     # ops that leave the picture as it was


def _changes_picture(changes):
    ops = [o.get('op') for o in changes or [] if isinstance(o, dict)]
    return not ops or any(op not in NOT_PICTURE for op in ops)


def picture(path, result=None, live=None):
    """The review's picture-under-the-words facts on the project as written (review.picture_words.cut), or None while
    review_craft_checks is off. A measurement that can't run says so; in a window whose edit isn't saved it reads the
    saved file, so it isn't run."""
    import letitedit.review.picture_words as picture_words
    if not picture_words.enabled():
        return None
    if live and not (result or {}).get('saved'):
        return {'checked': False, 'reason': 'the edit is in an open window and not saved: the picture check reads the '
                                            'saved file, so it was not run'}
    try:
        return picture_words.cut(str(path))
    except Exception as e:  # noqa: BLE001 - the edit stands; the reply says the check didn't run
        return {'checked': False, 'reason': f'{type(e).__name__}: {e}'[:600]}


# ------------------------------------------------------------------------------------------------ the apply

def before(path, changes, before_path=None):
    """Before an apply: (changes, records). Refuses (ValueError) the fields only the switch serves when it is off."""
    why = refused(changes)
    if why:
        raise ValueError(why)
    changes, aim = aim_score(path, changes, before_path)
    return changes, {'score': aim}


def after(path, changes, result, records, live=None):
    """After the apply: result['self_check'] with each op's own check."""
    if not enabled() or not isinstance(result, dict):
        return result
    out = {}
    if (records or {}).get('score'):
        out['score'] = after_score(path, records['score'])
    if _changes_picture(changes):
        out_picture = picture(path, result, live)
        if out_picture is not None:
            out['picture'] = out_picture
    fits = [o for o in _ops(changes, 'captions') if o.get('fit')]
    if fits:
        out['captions'] = [after_captions(path, o, result, live) for o in fits]
        if len(out['captions']) == 1:
            out['captions'] = out['captions'][0]
    if out:
        result['self_check'] = out
    return result
