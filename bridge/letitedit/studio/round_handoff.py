"""The hand-off between two review rounds, each in a fresh session (T363's cut 3; letitedit.app.substeps' switch
`review_round_sessions`, off by default). Made and checked in code, like the hand-off between sub-steps.

    gather(project, request, number, ...)     the record the next round needs, from the files and the round's session
    render(record)                            the Markdown the next round's first message attaches (`handover`)
    write(project, request, number, ...)      gather, render and check; writes
                                              substep-handoff-review_rounds-round<number>.json and .md beside the
                                              project; returns {'json', 'md', 'gaps', 'sha256'}
    rounds_done(project)                      how many critic rounds review_memory.json records

A round's session ends once its critic round is done (a review bundle whose critic read the cut). The next round must
not re-learn what the last one already knew, nor lose a rule that spans the edit, so the record holds:
- everything the hand-off between sub-steps holds (letitedit.studio.substep_handoff.gather for the review rounds:
  every brief requirement word for word, the overlay boxes, every review finding still open with its evidence, the
  device ledger, why each kept clip is in the cut, the plan and the run's notes), checked the same way
  (substep_handoff.check: a gap is asked for in the same session before the next round starts);
- what this round changed: each apply in the journal since the round began, with its label and first changes;
- what it tried that didn't work: each tool call of the round's session whose result was an error or a refusal, with
  what it asked and the first words of the answer;
- what it read: the files it opened and the drawn scenes whose code it read (so the next round knows where to look,
  and reads only what a fix needs);
- the round's own note: the session's closing message, word for word (cut at NOTE_CHARS).
The session's record is Claude Code's own log of it (claude_session.session_log); a missing log leaves those three
lists empty and says so.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from letitedit.studio import substep_handoff

FORMAT = 'letitedit-round-handoff/1'
UNIT = 'review_rounds'
NOTE_CHARS = 4000
APPLIES_LAST = 20
FAILED_LAST = 12
READ_LAST = 24
HEADER = "# Hand-off to the next review round (made and checked by letitedit from the project's files)"
REFUSED = re.compile(r'^\W*(?:refused|error|failed|not applied|could not|couldn\'t)\b', re.I)


def _work(project):
    return Path(project).with_suffix('.letitedit')


def rounds_done(project):
    """The critic rounds review_memory.json records (review_memory.rounds_done on the saved file); 0 when none."""
    memory = substep_handoff._json(_work(project) / 'review_memory.json')
    rounds = memory.get('rounds') if isinstance(memory, dict) else None
    return len(rounds) if isinstance(rounds, list) else 0


def _applies(project, since):
    from letitedit.timeline import project_journal
    rows = []
    for entry in project_journal.entries(project, None):
        t = substep_handoff._ts(entry.get('time'))
        if entry.get('kind') != 'apply' or t is None or t < since:
            continue
        changes = entry.get('changes')
        if isinstance(changes, str):
            try:
                changes = json.loads(changes)
            except ValueError:
                changes = [changes]
        changes = [str(c) for c in changes] if isinstance(changes, list) else []
        rows.append({'label': str(entry.get('label') or 'an edit'), 'changes_total': entry.get('changes_total'),
                     'changes': changes[:3]})
    return rows[-APPLIES_LAST:]


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(str(part.get('text') or '') for part in content if isinstance(part, dict))
    return ''


def _asked(name, args):
    """A short line for what a tool call asked (its label, op names, the command or the file), never its whole input."""
    if not isinstance(args, dict):
        return ''
    for key in ('label', 'action', 'command', 'file_path', 'path', 'id', 'project'):
        if args.get(key):
            text = str(args[key])
            thing = args.get('scene_id') or args.get('id')
            if key == 'action' and thing:
                text += f' {thing}'
            return f'{key}: ' + ' '.join(text.split())[:160]
    changes = args.get('changes')
    if isinstance(changes, list):
        ops = [str(c.get('op')) for c in changes if isinstance(c, dict) and c.get('op')]
        return 'ops: ' + ', '.join(ops[:8])
    return ''


def session_calls(log):
    """(failed, read) from a Claude Code session log (jsonl): each call whose result was an error or a refusal, and the
    files and drawn scenes the session read. Both empty when there is no log."""
    if log is None or not Path(log).is_file():
        return [], []
    uses, failed, read = {}, [], []
    try:
        lines = Path(log).read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return [], []
    for line in lines:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        content = (message.get('message') or {}).get('content') if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get('type') == 'tool_use':
                name = str(part.get('name') or '')
                args = part.get('input') if isinstance(part.get('input'), dict) else {}
                uses[part.get('id')] = (name, args)
                short = name.split('__')[-1]
                if short in ('Read', 'Grep', 'Glob') and (args.get('file_path') or args.get('path')):
                    read.append(str(args.get('file_path') or args.get('path')))
                elif short == 'letitedit_code_scene' and str(args.get('action') or '') in ('source', 'read', 'get'):
                    scene = args.get('scene_id') or args.get('id') or args.get('scene') or args.get('item') or '?'
                    read.append(f'the code of scene {scene} (letitedit_code_scene source)')
            elif part.get('type') == 'tool_result':
                name, args = uses.get(part.get('tool_use_id'), ('a tool', {}))
                text = ' '.join(_content_text(part.get('content')).split())
                if part.get('is_error') or REFUSED.match(text):
                    failed.append({'tool': name.split('__')[-1], 'asked': _asked(name, args), 'answer': text[:300]})
    read = list(dict.fromkeys(read))
    return failed[-FAILED_LAST:], read[-READ_LAST:]


def gather(project, request, number, *, log=None, said='', round_since=0.0, since=0.0):
    """The record the next review round needs after round `number` (the critic rounds done), see the module text."""
    record = substep_handoff.gather(project, request, UNIT, since)
    record.pop('next_needs', None)
    failed, read = session_calls(log)
    record.update({'round_format': FORMAT, 'round': int(number), 'next': None,
                   'round_work': {'applies': _applies(Path(project), round_since), 'failed': failed, 'read': read,
                                  'session_log': str(log) if log else None,
                                  'note': str(said or '').strip()[:NOTE_CHARS]}})
    return record


def render(record):
    """The hand-off as the next round reads it: the round's own work first, then the standing record in full."""
    number = record.get('round', 0)
    work = record.get('round_work') or {}
    lines = [HEADER, '',
             f'Review round {number} is done: its critic read the cut. Next: review round {number + 1}, in a fresh '
             'conversation. The original request and brief.json govern; this record is how the review so far reached '
             'you. Never redo a fix that is done; check what this round changed before changing it again.', '',
             f"## What round {number} changed (the journal's applies since the round began)"]
    for row in work.get('applies') or []:
        text = f"- {row['label']}"
        if row.get('changes_total'):
            text += f" ({row['changes_total']} change(s))"
        if row.get('changes'):
            text += ': ' + '; '.join(substep_handoff._line(c, 200) for c in row['changes'])
        lines.append(text)
    if not work.get('applies'):
        lines.append('- no apply in this round')
    lines += ['', f'## What round {number} tried that did not work (calls whose answer was an error or a refusal)']
    lines += [f"- {row['tool']}" + (f" ({row['asked']})" if row.get('asked') else '') + f": {row['answer']}"
              for row in work.get('failed') or []] or \
        ['- none' if work.get('session_log') else "- not known: the round's session log could not be read"]
    lines += ['', f'## What round {number} read (read again only what a fix needs)']
    lines += [f'- {path}' for path in work.get('read') or []] or ['- nothing recorded']
    lines += ['', f"## Round {number}'s own note (its closing message, word for word)"]
    lines.append(work.get('note') or '- the round ended without a note')
    standing = substep_handoff.render(record)
    standing = standing.replace(substep_handoff.HEADER, '# The standing record (as between sub-steps)', 1)
    return '\n'.join(lines) + '\n\n' + standing


def paths(project, number):
    work = _work(project)
    stem = f'substep-handoff-{UNIT}-round{int(number)}'
    return work / f'{stem}.json', work / f'{stem}.md'


def write(project, request, number, *, log=None, said='', round_since=0.0, since=0.0):
    """gather, render and check the hand-off after review round `number`; writes it beside the project. Returns
    {'json', 'md', 'gaps', 'sha256'} (the gaps are substep_handoff.check's; the files are written either way)."""
    record = gather(project, request, number, log=log, said=said, round_since=round_since, since=since)
    text = render(record)
    record['md_sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    gaps = substep_handoff.check(record, project, request)
    record['gaps'] = gaps
    path_json, path_md = paths(project, number)
    substep_handoff._atomic(path_md, text)
    substep_handoff._atomic(path_json, json.dumps(record, ensure_ascii=False, indent=1))
    return {'json': str(path_json), 'md': str(path_md), 'gaps': gaps, 'sha256': record['md_sha256']}
