"""Work in passes (T353, T297-3's missing parts): look once, edit once, check once per pass. On by default.

    enabled()                    the switch
    REFERENCE                    the skill text a stage start attaches with the switch on (letitedit-craft's
                                 references/passes.md: the pass shape and each stage's step budget, with its reason)
    ROUTE                        the stage-start route it is attached on (letitedit.app.stage_start.routes)
    timing_pace(res, body)       a compact `letitedit_timing` trajectory reply keeps each section's pace and the gear
                                 check whole (`pace`, `gear_order`), one line each (the result file has the rest)
    watched_renders(work)        the files a project's journal names as watched renders (`render:<path>`), so a Studio
                                 final copied from its preview keeps the preview's watched rough render

What the switch changes, and nothing else:
- a stage or phase start (stage_start.build) attaches references/passes.md on every stage, as a skill file in full;
- `letitedit_timing`'s compact trajectory reply carries `pace` and `gear_order` as facts (the paintbrush rule: what
  was measured, never what to do);
- a Studio final made from a preview (studio.short.prepare_from) copies the preview's rendered files that its journal
  records as watched renders, so the rough stage's watched export still checks out in the final's folder.
The tools' texts, arguments and every other reply are unchanged.

The switch: settings.json `work_in_passes` (default true; LETITEDIT_WORK_IN_PASSES, 1 or 0, wins). Read at each
call, in the runner (the stage start), the tool server and the AI's own Python alike.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SETTING = 'work_in_passes'
ENV = 'LETITEDIT_WORK_IN_PASSES'
REFERENCE = 'letitedit-craft/references/passes.md'
ROUTE = 'passes'

PACE_FIELDS = (('gear', 'gear', '{}'), ('index', 'pace index', '{:+.2f}'), ('cuts_per_min', 'cuts/min', '{:g}'),
               ('median_shot_s', 'median shot', '{:g} s'), ('motion', 'motion', '{:.2f}'),
               ('words_per_min', 'words/min', '{:g}'), ('speech_share', 'speech', '{:.0%}'),
               ('music_db', 'music', '{:g} dB'))
PACE_LINE_CHARS = 260
PACE_LINES = 24


def enabled():
    """settings.json work_in_passes (default true); LETITEDIT_WORK_IN_PASSES (1 or 0) wins."""
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


# ------------------------------------------------------------------------------- timing: the pace of each section

def _num(value, fmt):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return fmt.format(value)
    except (ValueError, TypeError):
        return None


def _seconds(sec):
    t0, t1 = sec.get('t0'), sec.get('t1')
    if isinstance(t0, (int, float)) and isinstance(t1, (int, float)):
        return f'{t0:.1f}-{t1:.1f} s'
    return None


def pace_lines(res):
    """Each section of a trajectory view in one line ('<label> | <t0-t1> | gear 4 | pace index -0.16 | ...'), or []."""
    out = []
    for sec in (res.get('sections') or [])[:PACE_LINES]:
        if not isinstance(sec, dict):
            continue
        parts = [str(sec.get('label') or sec.get('id') or '?')]
        span = _seconds(sec)
        if span:
            parts.append(span)
        if sec.get('feel'):
            parts.append(f"feel {sec['feel']}")
        for key, name, fmt in PACE_FIELDS:
            text = _num(sec.get(key), fmt)
            if text is not None:
                parts.append(f'{name} {text}')
        line = ' | '.join(parts)
        out.append(line if len(line) <= PACE_LINE_CHARS else line[:PACE_LINE_CHARS].rstrip() + ' ...')
    extra = len(res.get('sections') or []) - PACE_LINES
    if extra > 0:
        out.append(f'... {extra} more sections in detail.file')
    return out


def gear_line(res):
    """The trajectory's gear check in one line of facts, or None."""
    gc = res.get('gear_check')
    if not isinstance(gc, dict):
        return None
    parts = []
    if gc.get('spearman_gear_vs_index') is not None:
        parts.append(f"planned gear against measured pace index: rank correlation {gc['spearman_gear_vs_index']:+.2f}"
                     + (f" (threshold {gc['threshold']:g})" if isinstance(gc.get('threshold'), (int, float)) else ''))
    if gc.get('matching_order') is not None:
        parts.append('sections in the planned order of pace: ' + ('yes' if gc['matching_order'] else 'no'))
    for n in (gc.get('neighbours') or [])[:PACE_LINES]:
        if not isinstance(n, dict):
            continue
        change = _num(n.get('index_change'), '{:+.2f}')
        parts.append(f"{n.get('from')} -> {n.get('to')}: gear {n.get('gear_change'):+d}, pace index {change}, "
                     + ('agree' if n.get('agree') else 'disagree')
                     if isinstance(n.get('gear_change'), int) else f"{n.get('from')} -> {n.get('to')}")
    return '; '.join(parts) or None


def timing_pace(res, body):
    """Keys a compact timing reply keeps whole for a trajectory view (switch on): `pace` (one line per section) and
    `gear_order` (the gear check in one line), written into body. () when the switch is off or the view has no sections."""
    if not (enabled() and isinstance(res, dict) and isinstance(body, dict) and res.get('view') == 'trajectory'):
        return ()
    lines = pace_lines(res)
    if not lines:
        return ()
    body['pace'] = '\n'.join(lines)
    keys = ['pace']
    gear = gear_line(res)
    if gear:
        body['gear_order'] = gear
        keys.append('gear_order')
    return tuple(keys)


# ------------------------------------------------------------------------- the Studio final: the watched renders

def watched_renders(work):
    """The paths (as written) a project's journal records as watched renders (`render:<path>` notes), or []."""
    journal = Path(work) / 'journal.jsonl'
    out = []
    try:
        lines = journal.read_text(encoding='utf-8-sig').splitlines()
    except (OSError, UnicodeDecodeError):
        return out
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        text = str(entry.get('text') or '') if isinstance(entry, dict) else ''
        if isinstance(entry, dict) and entry.get('kind') == 'note' and text.startswith('render:'):
            out.append(text.split(':', 1)[1].strip())
    return out
