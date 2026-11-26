"""The hand-off between New video's sub-step sessions, made and checked in code (T354; letitedit.app.substeps).

    gather(project, request, unit)              the record the next sub-step needs, read from the project's files
    check(handoff, project, request)            [gap, ...]: what the record misses, each in plain words ([] = complete)
    render(handoff)                             the Markdown the next sub-step's first message attaches (`handover`)
    write(project, request, unit, since)        gather, render and check; writes substep-handoff-<unit>.json and .md
                                                beside the project; returns {'json', 'md', 'gaps', 'sha256'}
    verify(path, project, request)              before the next session starts: the saved record is the one rendered,
                                                unchanged, and still complete against the files now ([] = go)

A later session doesn't remember why an earlier one cut where it did (T344), so the rules that span the edit travel
here, each read from where the edit keeps it and checked against that source, never against the AI's summary:
- **the brief's requirements**: brief.json's must_keep, must_avoid, required_lines, claims, ending, protected, rules
  and preferences, each word for word (REQUIRED);
- **the overlay boxes**, with the Studio's overlay facts on (review.overlay_clash): every box of overlay-boxes.json,
  in pixels of the frame;
- **every review finding still open**, with its evidence (what was found, where, the fix it names and who found it),
  from review_memory.json. A reviewer's own finding travels without its earlier severity: each review round rates it
  afresh (T349); a measured one keeps its measured severity;
- **the device ledger** (letitedit-craft L1): every `devices:` note in the journal, once the cut exists;
- **why each kept clip is in the cut**: each main-track clip with the `why:` marker over its middle.
Also, for reading (not checked): the plan's purpose, opening, ending, sections and open loops, the cut's length, the
run's notes and what the next sub-step still lacks.

A gap is named in plain words (`gaps`). The session runner treats gaps as a sub-step not yet done (the same session is
asked to fill them) and stops the run, naming them, before a next session would start without them.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

FORMAT = 'letitedit-substep-handoff/1'
REQUIRED = ('must_keep', 'must_avoid', 'required_lines', 'claims', 'ending', 'protected', 'rules', 'preferences')
CONTEXT = ('goal', 'purpose', 'audience', 'mode', 'driver', 'look', 'deliverables', 'target_s', 'feel', 'narration',
           'captions', 'music')
PLAN_KEYS = ('purpose', 'logline', 'feel', 'stakes', 'open_question', 'ending')
OPEN = ('open', 'person')                 # review_memory's item states still to act on (person: the person's to decide)
CUT_FROM = ('rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look')      # the sub-steps after which a cut exists
NOTES_LAST = 12
NOTE_CHARS = 400
HEADER = "# Hand-off to the next sub-step (made and checked by letitedit from the project's files)"


def _work(project):
    return Path(project).with_suffix('.letitedit')


def _json(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    return value


def _present(value):
    return value not in (None, '', [], {})


def _line(value, limit=600):
    """One line of a value, as the phases' hand-over writes it (letitedit.app.bookkeeping's own)."""
    if isinstance(value, (list, tuple)):
        value = '; '.join(_line(v, limit) for v in value if _present(v))
    elif isinstance(value, dict):
        value = '; '.join(f'{k}: {_line(v, limit)}' for k, v in value.items() if _present(v))
    text = ' '.join(str(value if value is not None else '').split())
    return text if len(text) <= limit else text[:limit - 3] + '...'


def _ts(text):
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(str(text).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def _overlay():
    try:
        from letitedit.review import overlay_clash
        return overlay_clash if overlay_clash.enabled() else None
    except Exception:  # noqa: BLE001 - an install without it: off
        return None


def _overlay_rows(project):
    clash = _overlay()
    if clash is None:
        return None
    data = clash.boxes_file(project) or {}
    frame = tuple(data.get('frame') or (1080, 1920))
    rows = []
    for item in data.get('items') or []:
        if not isinstance(item, dict) or not isinstance(item.get('box'), dict):
            continue
        rows.append({'text': item.get('text'), 'platform': item.get('platform'), 'placement': item.get('placement'),
                     'box': clash.plain_box(item['box'], frame), **({'if': item['if']} if item.get('if') else {})})
    return rows


def _asks_overlay(request):
    return 'overlay words' in (request or '') or 'overlay_text' in (request or '')


def _findings(project):
    """Every review finding still open (review_memory.json's items), with its evidence."""
    memory = _json(_work(project) / 'review_memory.json')
    rows = []
    for item in (memory or {}).get('items') or [] if isinstance(memory, dict) else []:
        if not isinstance(item, dict) or item.get('status') not in OPEN:
            continue
        row = {'id': item.get('id'), 'source': item.get('source'), 'status': item.get('status'),
               'what': item.get('what'), 'at': item.get('at'), 'fix': item.get('fix'),
               'round_found': item.get('round_found'), 'owner': item.get('owner')}
        if item.get('source') != 'critic' and item.get('severity'):
            row['severity'] = item['severity']          # measured: its measure's own severity
        rows.append({k: v for k, v in row.items() if v is not None})
    return rows, (len((memory or {}).get('rounds') or []) if isinstance(memory, dict) else 0)


def _devices(project):
    from letitedit.timeline import project_journal
    return [str(e.get('text')).strip() for e in project_journal.entries(project, None)
            if e.get('kind') == 'note' and str(e.get('text') or '').strip().lower().startswith('devices:')]


def _main_clips(project):
    from letitedit.app import phases
    from letitedit.timeline import edit_sync
    script = phases.read_script(project, live=False)
    track = edit_sync.main_track(script) if script else None
    rows = [(it, s, e) for it, s, e in (edit_sync.layout(track) if track else [])]
    return [(it, s, e) for it, s, e in rows if 'clip' in it], max((e for _, _, e in rows), default=0.0)


def _markers(project):
    from letitedit.sound import av_tools
    try:
        return [m for m in av_tools.bin(str(project)).get('markers', []) if isinstance(m, dict)]
    except Exception:  # noqa: BLE001 - unreadable markers: every clip reads as without its why (a gap, not a guess)
        return []


def _whys(project):
    clips, length = _main_clips(project)
    whys = [m for m in _markers(project) if str(m.get('text', '')).lower().startswith('why:')]
    rows = []
    for it, s, e in clips:
        middle = (s + e) / 2
        hit = next((m for m in whys if float(m.get('start', 0)) <= middle <= float(m.get('end', 0))), None)
        rows.append({'id': it.get('id'), 'clip': Path(str(it.get('clip'))).name, 'start': round(s, 2),
                     'end': round(e, 2), 'why': (str(hit['text']).split(':', 1)[1].strip() if hit else None)})
    return rows, length


def _plan(project):
    from letitedit.app import bookkeeping
    plan = _json(_work(project) / 'story_plan.json')
    if not isinstance(plan, dict):
        return {}
    out = {key: plan[key] for key in PLAN_KEYS if _present(plan.get(key))}
    opening = bookkeeping.opening_line(plan)
    if opening:
        out['opening'] = opening[len('- opening: '):]
    sections = [{k: s.get(k) for k in ('id', 'label', 'purpose', 'driver', 'gear', 'feel', 'target_s')
                 if _present(s.get(k))} for s in plan.get('sections') or [] if isinstance(s, dict)]
    if sections:
        out['sections'] = sections
    loops = [loop.get('question') for loop in plan.get('loops') or [] if isinstance(loop, dict)
             and not loop.get('closes')]
    if loops:
        out['open_loops'] = loops
    return out


def _notes(project, since):
    from letitedit.app import bookkeeping
    from letitedit.timeline import project_journal
    notes = []
    for entry in project_journal.entries(project, None):
        text = str(entry.get('text') or '').strip()
        t = _ts(entry.get('time'))
        if entry.get('kind') != 'note' or not text or t is None or t < since or \
                text.startswith(bookkeeping.SKIP_NOTES) or text.lower().startswith('devices:'):
            continue
        notes.append(f"{entry.get('actor', '?')}: {_line(text, NOTE_CHARS)}")
    return notes[-NOTES_LAST:]


def gather(project, request, unit, since=0.0):
    """The record the sub-step after `unit` needs, from the files (see the module text)."""
    from letitedit.app import substeps
    project = Path(project)
    following = substeps.NEXT.get(unit)
    brief = _json(_work(project) / 'brief.json')
    brief = brief if isinstance(brief, dict) else {}
    findings, rounds = _findings(project)
    whys, length = _whys(project) if project.is_file() else ([], 0.0)
    record = {'format': FORMAT, 'from': unit, 'next': following, 'project': str(project),
              'requirements': {key: brief[key] for key in REQUIRED if _present(brief.get(key))},
              'brief': {key: brief[key] for key in CONTEXT if _present(brief.get(key))},
              'findings': findings, 'review_rounds_done': rounds,
              'devices': _devices(project), 'clips': whys, 'length_s': round(length, 2),
              'plan': _plan(project), 'notes': _notes(project, since)}
    boxes = _overlay_rows(project)
    if boxes is not None:
        record['overlay_boxes'] = boxes
    if following:
        record['next_needs'] = substeps.done(following, project, request)['missing']
    return record


def check(handoff, project, request=''):
    """What the hand-off misses against the project's files now, each gap in plain words; [] when complete."""
    project = Path(project)
    gaps = []
    if not isinstance(handoff, dict) or handoff.get('format') != FORMAT:
        return ['the hand-off record itself (unreadable or not one letitedit made)']
    unit = handoff.get('from')
    brief = _json(_work(project) / 'brief.json')
    if not isinstance(brief, dict):
        gaps.append('brief.json (it is missing or unreadable, so the brief\'s requirements cannot travel)')
        brief = {}
    carried = handoff.get('requirements') or {}
    for key in REQUIRED:
        if _present(brief.get(key)) and carried.get(key) != brief[key]:
            gaps.append(f"the brief's {key} (brief.json has it; the hand-off doesn't carry it word for word)")
    clash = _overlay()
    if clash is not None:
        boxes = _overlay_rows(project) or []
        if _asks_overlay(request) and not boxes:
            gaps.append('the overlay boxes (the request has overlay words, and overlay-boxes.json has no box)')
        have = {(row.get('text'), row.get('platform'), row.get('box')) for row in handoff.get('overlay_boxes') or []}
        for row in boxes:
            if (row.get('text'), row.get('platform'), row.get('box')) not in have:
                gaps.append(f"the overlay box for \"{row.get('text')}\" on {row.get('platform')} ({row.get('box')})")
    findings, _ = _findings(project)
    carried = {row.get('id'): row for row in handoff.get('findings') or [] if isinstance(row, dict)}
    for row in findings:
        held = carried.get(row.get('id'))
        if held is None:
            gaps.append(f"review finding {row.get('id')} (still open in review_memory.json)")
        elif not _present(held.get('what')) or not (_present(held.get('at')) or _present(held.get('fix'))):
            gaps.append(f"the evidence of review finding {row.get('id')} (what was found, and where or its fix)")
        elif held.get('source') == 'critic' and 'severity' in held:
            gaps.append(f"review finding {row.get('id')} carries an earlier severity (each round rates it afresh)")
    if unit in CUT_FROM:
        if not _devices(project):
            gaps.append('the device ledger: no `devices:` note in the journal (letitedit-craft L1)')
        elif handoff.get('devices') != _devices(project):
            gaps.append('the device ledger (the journal\'s `devices:` notes, word for word)')
        if project.is_file():
            whys, _ = _whys(project)
            carried = {(row.get('id'), row.get('start')): row for row in handoff.get('clips') or []}
            for row in whys:
                held = carried.get((row['id'], row['start']))
                if not row.get('why'):
                    gaps.append(f"why clip {row['id']} ({row['clip']}, {row['start']:.2f}-{row['end']:.2f} s) is in "
                                'the cut: it has no `why:` marker over its middle (letitedit-firstcut FIRST-4)')
                elif held is None or held.get('why') != row['why']:
                    gaps.append(f"the why of clip {row['id']} ({row['start']:.2f}-{row['end']:.2f} s), word for word")
    return gaps


def render(handoff):
    """The hand-off as the next sub-step reads it (Markdown, every item in full)."""
    from letitedit.app import substeps
    unit, following = handoff.get('from'), handoff.get('next')
    title = substeps.SUBSTEPS[unit]['title'] if unit in substeps.SUBSTEPS else unit
    lines = [HEADER, '']
    if following:
        lines.append(f"The {title} sub-step is done: its outputs check out. Next: the "
                     f"{substeps.SUBSTEPS[following]['title']} sub-step ({following}), in a fresh conversation.")
    lines.append('The original request and brief.json govern; this record is how the edit so far reached you. Every '
                 'item below holds for the rest of the edit. Never redo a step that is done.')
    req = handoff.get('requirements') or {}
    lines += ['', '## The brief\'s requirements (brief.json, word for word)']
    lines += [f'- {key}: {json.dumps(value, ensure_ascii=False)}' for key, value in req.items()] or \
        ['- none stated in brief.json']
    if handoff.get('brief'):
        lines += ['', '## The brief, for context']
        lines += [f'- {key}: {_line(value)}' for key, value in handoff['brief'].items()]
    if 'overlay_boxes' in handoff:
        lines += ['', '## The overlay boxes (letitedit adds these words after the export: keep captions and key '
                  'picture clear of each box for the whole video)']
        lines += [f"- \"{row.get('text')}\" ({row.get('placement')}) on {row.get('platform')}: {row.get('box')} in "
                  'the 1080x1920 frame' + (f" (only when: {row['if']})" if row.get('if') else '')
                  for row in handoff['overlay_boxes']] or ['- none']
    lines += ['', f"## Review findings still open ({len(handoff.get('findings') or [])}; review rounds done: "
              f"{handoff.get('review_rounds_done', 0)})"]
    if handoff.get('findings'):
        lines.append('A reviewer\'s finding is listed without its earlier severity: rate it afresh from the cut now. '
                     'A measured one keeps its measure\'s severity.')
        for row in handoff['findings']:
            who = row.get('source') + (f", {row['severity']}" if row.get('severity') else '') + \
                (", the person's to decide" if row.get('status') == 'person' else '')
            where = f" at {row['at']}" if row.get('at') else ''
            text = f"- {row.get('id')} ({who}){where}: {_line(row.get('what'), 900)}"
            if row.get('fix'):
                text += ' | fix: ' + _line(row['fix'], 600)
            lines.append(text)
    else:
        lines.append('- none')
    lines += ['', '## The device ledger (letitedit-craft L1: the journal\'s `devices:` notes)']
    lines += [f'- {_line(text, 1200)}' for text in handoff.get('devices') or []] or ['- none yet']
    lines += ['', f"## Why each kept clip is in the cut (the main track: {len(handoff.get('clips') or [])} clip(s), "
              f"{handoff.get('length_s', 0):.1f} s)"]
    lines += [f"- {row.get('id')} ({row.get('clip')}, {row.get('start'):.2f}-{row.get('end'):.2f} s): "
              + (row.get('why') or 'NO why: marker') for row in handoff.get('clips') or []] or ['- no cut yet']
    plan = handoff.get('plan') or {}
    if plan:
        lines += ['', '## The plan (story_plan.json)']
        for key, value in plan.items():
            if key == 'sections':
                lines += [f"- section {s.get('id', '?')}: {_line({k: v for k, v in s.items() if k != 'id'})}"
                          for s in value]
            else:
                lines.append(f'- {key}: {_line(value)}')
    if handoff.get('notes'):
        lines += ['', "## This run's notes (journal; journal.md has them whole)"]
        lines += [f'- {note}' for note in handoff['notes']]
    if handoff.get('next_needs'):
        lines += ['', '## What the next sub-step still makes']
        lines += [f'- {item}' for item in handoff['next_needs']]
    return '\n'.join(lines) + '\n'


def _paths(project, unit):
    work = _work(project)
    return work / f'substep-handoff-{unit}.json', work / f'substep-handoff-{unit}.md'


def _atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temp.write_text(text, encoding='utf-8')
    os.replace(temp, path)


def write(project, request, unit, since=0.0):
    """gather, render and check the hand-off after `unit`; writes it beside the project. Returns {'json', 'md',
    'gaps', 'sha256'} (the gaps are what check found; the files are written either way, for the record)."""
    record = gather(project, request, unit, since)
    text = render(record)
    record['md_sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    gaps = check(record, project, request)
    record['gaps'] = gaps
    path_json, path_md = _paths(project, unit)
    _atomic(path_md, text)
    _atomic(path_json, json.dumps(record, ensure_ascii=False, indent=1))
    return {'json': str(path_json), 'md': str(path_md), 'gaps': gaps, 'sha256': record['md_sha256']}


def verify(path, project, request=''):
    """Before the next session starts: [] when the saved hand-off is the one rendered (its Markdown unchanged) and
    still complete against the files now; else the gaps, in plain words."""
    record = _json(path)
    if not isinstance(record, dict):
        return [f'the hand-off record {path} (missing or unreadable)']
    md = Path(str(path)[:-len('.json')] + '.md') if str(path).endswith('.json') else None
    try:
        text = md.read_text(encoding='utf-8') if md else ''
    except OSError:
        text = None
    if text is None or hashlib.sha256(text.encode('utf-8')).hexdigest() != record.get('md_sha256'):
        return [f'the hand-off {md} (missing, or changed since letitedit made it)']
    return check(record, project, request)
