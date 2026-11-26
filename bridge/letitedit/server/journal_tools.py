"""MCP tool: a project's journal (every apply and undo, plus free notes), its edit lease and its track owners.

Everything is stored beside the project in <stem>.letitedit\\ (see project_journal.py).
"""
from __future__ import annotations

import re

import letitedit.timeline.edit_script as es
import letitedit.timeline.project_journal as pj


ARTIFACT = re.compile(r'(brief|log|selects|story_plan|pickups|fine_pass|finish_pass|handover):')
NOTE_CHARS = 800   # a free note longer than this is cut in a slim read (journal.md has it whole)


def _slim_entry(entry):
    """One journal entry as a slim read gives it: an apply's change list as one count line, a note that wrote a file
    (brief:, story_plan:, handover: ...) as that file's name, a long free note cut (journal.md has everything)."""
    e = dict(entry)
    if isinstance(e.get('changes'), list):
        n = e.pop('changes_total', None) or len(e['changes'])
        e['changes'] = f'{n} change(s); journal.md lists them'
    text = e.get('text')
    if isinstance(text, str):
        m = ARTIFACT.match(text)
        if m:
            name = m.group(1)
            ext = '.md' if name in ('pickups', 'fine_pass', 'finish_pass', 'handover') else '.json'
            e['text'] = f'{name}: written to {name}{ext} ({len(text)} chars; read the file)'
        elif len(text) > NOTE_CHARS:
            e['text'] = text[:NOTE_CHARS] + f' ... ({len(text)} chars; journal.md has it whole)'
    return e


def _wrote(path, text):
    """What a note that writes a stage file wrote, checked (T345 C1, with the full books on): {file, bytes, keys or
    lines, problems}; None for any other note."""
    m = ARTIFACT.match(str(text or '').strip())
    if not m:
        return None
    import json
    name = m.group(1)
    target = pj.folder(path) / (name + ('.md' if name in ('pickups', 'fine_pass', 'finish_pass', 'handover')
                                        else '.json'))
    out = {'file': str(target)}
    try:
        body = target.read_text(encoding='utf-8-sig')
    except OSError:
        out['problems'] = ['the file was not written']
        return out
    out['bytes'] = len(body.encode('utf-8'))
    if target.suffix != '.json':
        out['lines'] = len(body.splitlines())
        return out
    value = json.loads(body)
    out['keys'] = list(value)
    problems = []
    if name == 'selects':
        beats = value.get('beats')
        groups = beats.values() if isinstance(beats, dict) else (beats or [])
        rows = [r for g in groups for r in ((g.get('selects') if isinstance(g, dict) else g) or [])
                if isinstance(r, dict)]
        out['selects'] = len(rows)
        lacking = sum(1 for r in rows if not str(r.get('why') or '').strip())
        if lacking:
            problems.append(f'{lacking} select(s) have no why (the why markers are made from it)')
        bad = sum(1 for r in value.get('cuts') or [] if not (isinstance(r, dict) and r.get('file') and r.get('why')
                                                               and r.get('in') is not None and r.get('out') is not None))
        if bad:
            problems.append(f'{bad} cut(s) lack file, in, out or why')
    if name == 'story_plan':
        beats = [b for b in value.get('beats') or [] if isinstance(b, dict)]
        out['beats'] = len(beats)
        selects = {}
        for candidate in (pj.folder(path) / 'selects.json', path.parent / 'selects.json'):
            try:
                selects = json.loads(candidate.read_text(encoding='utf-8-sig'))
                break
            except (OSError, ValueError):
                continue
        groups = set(selects.get('beats') or {}) if isinstance(selects.get('beats'), dict) else set()
        if groups:
            missing = [str(b.get('id')) for b in beats
                       if not any(str(k) in groups for k in (b.get('selects') or [b.get('id')]))]
            if missing:
                problems.append('beat(s) with no group in selects.json: ' + ', '.join(missing[:12]))
        if not beats:
            problems.append('no beats (the beat markers are made from them)')
    if problems:
        out['problems'] = problems
    return out


def _entries(path, entries, actor):
    """Several notes in one call, in order; the first refusal stops the rest."""
    added, refused = [], None
    for k, text in enumerate(entries):
        try:
            one = journal(path, 'add', text, actor=actor)
        except ValueError as error:
            refused = {'entry': k, 'starts': ' '.join(str(text or '').split())[:60], 'reason': str(error),
                       'not_added': len(entries) - k}
            break
        one.pop('stages', None)
        one.pop('journal', None)
        added.append(one)
    out = {'added': added, 'journal': str(pj.folder(path) / 'journal.md'), 'stages': pj.stage_progress(path)}
    if refused:
        out['refused'] = refused
    return out


def journal(project, action='read', text=None, limit=50, actor=None, entries=None):
    """letitedit_journal without MCP."""
    path = es._resolve(project)
    if entries is not None and action in ('add', 'note'):
        if text is not None:
            raise ValueError('Give the notes as text (one) or entries (several), not both.')
        if not isinstance(entries, (list, tuple)) or not entries:
            raise ValueError('entries is a list of notes, each as `text` would be.')
        return _entries(path, list(entries), actor)
    if action == 'read':
        out = {'project': str(path), 'folder': str(pj.folder(path))}
        out.update(pj.status(path))
        out['entries'] = pj.entries(path, limit)
        import letitedit.app.new_video_stages as new_video_stages
        if new_video_stages.slim():
            out['entries'] = [_slim_entry(e) for e in out['entries']]
        out['stages'] = pj.stage_progress(path)
        return out
    if action in ('add', 'note'):
        added = pj.note(path, text, actor)
        out = {'added': {key: value for key, value in added.items() if key != 'text'},
               'journal': str(pj.folder(path) / 'journal.md'),
               'stages': pj.stage_progress(path)}
        import letitedit.app.new_video_stages as new_video_stages
        if str(text or '').strip().startswith('stage:'):
            stage = pj.stage_name(text)
            accepted = bool(stage and out['stages'].get(stage, {}).get('done'))
            out['stage_mark'] = {'stage': stage, 'accepted': accepted}
            if not accepted:
                out['stage_mark']['reason'] = ('This note was not taken as a stage-done mark. Use '
                                               '`stage:<name>:done — <summary>` after the stage outputs are ready.')
        hand_over = new_video_stages.hand_over_note(text)
        if hand_over:
            out['hand_over'] = hand_over
        import letitedit.app.bookkeeping as bookkeeping
        if bookkeeping.full():
            wrote = _wrote(path, text)
            if wrote:
                out['wrote'] = wrote
        return out
    if action == 'release':
        before = pj.release(path, actor)
        return {'released': bool(before), 'lease_before': before, 'lease': pj.lease(path)}
    raise ValueError("Choose action='read', 'add', 'note' or 'release', then try again.")


WHY_CHARS = 200    # a why marker's text is one line of at most this many characters
WHY_SHARE = 0.5    # a select matches a clip when it plays the same file over at least this share of the clip


def _same_file(a, b):
    import os
    a, b = str(a or ''), str(b or '')
    if not a or not b:
        return False
    if os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b)):
        return True
    return os.path.normcase(os.path.basename(a)) == os.path.normcase(os.path.basename(b))


def _why_text(why):
    text = ' '.join(str(why or '').split())
    if text.lower().startswith('why:'):
        text = text[4:].strip()
    if len(text) > WHY_CHARS:
        text = text[:WHY_CHARS - 3].rstrip() + '...'
    return f'why: {text}' if text else None


def _selects(path):
    """[(file, in, out, why text)] of every select in selects.json that has a why."""
    import json
    work = pj.folder(path)
    for candidate in (work / 'selects.json', path.parent / 'selects.json'):
        try:
            data = json.loads(candidate.read_text(encoding='utf-8-sig'))
            break
        except (OSError, ValueError):
            continue
    else:
        return []
    beats = data.get('beats') if isinstance(data, dict) else None
    groups = beats.values() if isinstance(beats, dict) else (beats or [])
    out = []
    for group in groups:
        rows = group.get('selects') if isinstance(group, dict) else group
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get('file'):
                continue
            try:
                a, b = es.to_seconds(row.get('in')), es.to_seconds(row.get('out'))
            except (TypeError, ValueError):
                continue
            text = _why_text(row.get('why'))
            if text and a is not None and b is not None and b > a:
                out.append((row['file'], float(a), float(b), text))
    return out


def why_plan(project):
    """What the why markers need: {'clips', 'covered', 'add': [markers], 'remove': [ids], 'unmatched': [...]}. A clip
    with a `why:` marker over its middle is covered; any other clip gets its best-matching select's why (the same file
    over at least WHY_SHARE of the clip's source range); a `why:` marker with a select's text over no clip is stale."""
    import letitedit.app.bookkeeping as bookkeeping
    import letitedit.sound.av_tools as av_tools
    import letitedit.timeline.edit_sync as edit_sync
    path = es._resolve(project)
    script = bookkeeping.read_script(path)
    track = edit_sync.main_track(script) if script else None
    clips = [(it, s, e) for it, s, e in (edit_sync.layout(track) if track else []) if 'clip' in it]
    markers = [m for m in av_tools.bin(path).get('markers', []) if str(m.get('text', '')).lower().startswith('why:')]
    selects = _selects(path)
    ours = {text for *_, text in selects}
    fps = float(((script or {}).get('profile') or {}).get('fps') or 0)
    frame = 1 / fps if fps > 0 else 0.0     # a marker ends on the clip's last frame, not on the next clip's first
    plan = {'clips': len(clips), 'covered': 0, 'add': [], 'remove': [], 'unmatched': []}
    for it, s, e in clips:
        middle = (s + e) / 2
        if any(float(m['start']) <= middle <= float(m['end']) for m in markers):
            plan['covered'] += 1
            continue
        a = float(es.to_seconds(it['in'])) if it.get('in') is not None else 0.0
        b = float(es.to_seconds(it['out'])) if it.get('out') is not None else a + (e - s) * float(it.get('speed', 1.0))
        best = None
        for file, i0, i1, text in selects:
            if not _same_file(file, it['clip']):
                continue
            cover = max(0.0, min(b, i1) - max(a, i0))
            if b > a and cover >= WHY_SHARE * min(b - a, i1 - i0) and (best is None or cover > best[0]):
                best = (cover, text)
        if best:
            plan['add'].append({'start': round(s, 3), 'end': round(max(s, e - frame), 3), 'text': best[1]})
            plan['covered'] += 1
        else:
            plan['unmatched'].append({'id': it.get('id'), 'clip': str(it['clip']), 'start': round(s, 3),
                                      'end': round(e, 3)})
    for m in markers:
        if m.get('text') in ours and not any(float(m['start']) <= (s + e) / 2 <= float(m['end']) for _, s, e in clips):
            plan['remove'].append(m['id'])
    return plan


def why_markers(project):
    """Write the why markers why_plan finds (letitedit_bin's markers: one undo step in an open window). Returns the
    plan with what was written: {'clips', 'covered', 'written', 'removed', 'unmatched'}."""
    import letitedit.sound.av_tools as av_tools
    plan = why_plan(project)
    receipt = {key: plan[key] for key in ('clips', 'covered', 'unmatched')}
    receipt.update(written=len(plan['add']), removed=len(plan['remove']))
    if plan['add'] or plan['remove']:
        av_tools.bin(es._resolve(project), markers=plan['add'] or None, remove=plan['remove'] or None)
    return receipt


def register(mcp, Image):
    @mcp.tool()
    def letitedit_journal(project: str, action: str = 'read', text: str | None = None, limit: int = 50,
                        actor: str | None = None, entries: list[str] | None = None) -> dict:
        """A project's journal, kept beside it in <stem>.letitedit\\journal.jsonl and journal.md. Every apply and undo
        adds an entry (UTC time, actor, label, the changes); notes are added by anyone.
        action='read' [default]: the last `limit` entries [50], the edit lease (owner, expires) and track owners.
        action='add' or 'note': persist `text` and return a receipt without echoing it; 'read' returns the full note.
        entries: several notes in one call instead of `text`, written in order, each as `text` would be; the first
        refused one stops the rest (`refused` names it and why).
        JSON notes starting `brief:`, `log:`, `selects:` or
        `story_plan:` write those files in the project's .letitedit folder; `pickups:`, `fine_pass:`,
        `finish_pass:` and `handover:` write Markdown files (handover.md: the latest replaces the one before). A separate `stage:<name>:done` note is accepted only after its
        required output exists and the preceding stage is done; when the install runs New video in one conversation
        per stage (settings.json new_video_stage_sessions), the reply to a story, rough, fine or finish one has
        `hand_over`. `render:<full path>` records a watched rough
        export. action='release': end your own edit lease now.
        actor: who is writing [LETITEDIT_ACTOR environment variable, else 'claude' or 'codex' by the app
        this runs under, else 'agent']. Reading never waits on a lease."""
        out = journal(project, action, text, limit, actor, entries)
        if action == 'read':                 # a long read: the newest entries whole, journal.md has every one
            import letitedit.server.compact_reply as compact_reply
            out = compact_reply.journal_reply(out, _slim_entry)
        return out

    return letitedit_journal


if __name__ == '__main__':      # python -m letitedit.server.journal_tools why|books <project>: one JSON line
    import json                 # (letitedit.app.bookkeeping; books: T345 C1, letitedit.server.books)
    import sys
    try:
        if len(sys.argv) != 3 or sys.argv[1] not in ('why', 'books'):
            raise ValueError('usage: python -m letitedit.server.journal_tools why|books <project>')
        if sys.argv[1] == 'books':
            from letitedit.server import books
            print(json.dumps(books.write(es._resolve(sys.argv[2]))))
        else:
            print(json.dumps(why_markers(sys.argv[2])))
    except Exception as error:  # noqa: BLE001 - the caller reads the reason and carries on
        print(json.dumps({'error': f'{type(error).__name__}: {error}'}))
