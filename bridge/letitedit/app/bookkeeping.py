"""New video's bookkeeping in code (T319's rule 5, T331 step P8): the stage and phase done marks, each main-track
clip's `why:` marker and the hand-over between phases are written by code from the files on disk, not by the AI.

    enabled()                                  the switch below, and the run works in phases (new_video_stages)
    marks(project)                             {'stages': [...], 'phases': [...], 'refused': {stage: reason}}
    why_markers(project)                       the why markers written from selects.json (letitedit.server.journal_tools)
    handover_text(project, request, phase, since, why)   the hand-over to the phase after `phase`, from the files
    after_phase(project, request, phase, since)          all three at a phase boundary; returns the receipt
    read_script(project)                       the cut as the phases read it (the window's snapshot, else the file)

- **Marks.** A `stage:<name>:done` note is written for each stage whose outputs check out (project_journal's own
  rules: stage_progress), in order, by the actor 'letitedit', with the summary "written by letitedit: its outputs
  check out". The journal refuses a mark whose outputs are missing exactly as it refuses the AI's (the fine stage's
  restart check included), so a refusal is recorded and nothing later is marked. A `phase:<id>:done` note follows
  when a phase's outputs check out (letitedit.app.phases.done). Marks already there are never written twice.
- **Why markers.** Each main-track clip gets one marker spanning it, `why: <its select's why>`, from the select in
  selects.json that plays the same file over most of the clip's source range. A clip that already has a `why:` marker
  over its middle (the AI's, the person's or an earlier one of ours) keeps it; a `why:` marker of ours that no longer
  sits over any clip is removed. The writer needs the marker code (letitedit.sound.av_tools), which sits above this
  layer, so it runs in its own process (`python -m letitedit.server.journal_tools why <project>`); a failure is
  reported in the receipt and never stops the run.
- **Hand-over.** handover.md for the next phase, made from brief.json, story_plan.json, the cut on the timeline, the
  run's own journal notes and what the next phase still lacks. A hand-over the AI wrote during this run is kept as
  it is.

The rest of the books (T345 C1, letitedit.server.books), with full() on: at the same boundaries the why markers come
with the beat and loop markers from story_plan.json, the cut markers from selects.json's `cuts` and a licence note on
each library song or sound, all from one process (books_markers); the hand-over says what code couldn't place. The
journal's reply to a note that writes a stage file checks that file (letitedit.server.journal_tools). Its own switch:
settings.json `new_video_bookkeeping_full` (LETITEDIT_NEW_VIDEO_BOOKKEEPING_FULL), on top of the one below.
markers_follow() (settings.json `markers_follow_clips`, LETITEDIT_MARKERS_FOLLOW_CLIPS, or full()) makes every
letitedit_timeline_apply carry the markers with their clips (letitedit.server.books.follow).

The switch: settings.json `new_video_bookkeeping` (default true; LETITEDIT_NEW_VIDEO_BOOKKEEPING, 1 or 0, wins). It
applies only to a run in phases (new_video_stages.phases_on()): off, or without phases, nothing here runs and the AI
writes its marks, markers and hand-over as the skills say.
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

from letitedit.timeline import project_journal

SETTING = 'new_video_bookkeeping'
ENV = 'LETITEDIT_NEW_VIDEO_BOOKKEEPING'
FULL_SETTING = 'new_video_bookkeeping_full'          # T345 C1: the rest of the books
FULL_ENV = 'LETITEDIT_NEW_VIDEO_BOOKKEEPING_FULL'
FOLLOW_SETTING = 'markers_follow_clips'              # T345 C1: markers follow their clips through an apply
FOLLOW_ENV = 'LETITEDIT_MARKERS_FOLLOW_CLIPS'
ACTOR = 'letitedit'
MARK_SUMMARY = 'written by letitedit: its outputs check out'
HEADER = '# Hand-over (made by letitedit from the project\'s files)'
WHY_TIMEOUT_S = 20
BOOKS_TIMEOUT_S = 60     # the books also read the asset library once for the licence notes
NOTES_LAST = 12           # the run's own journal notes the hand-over quotes
NOTE_CHARS = 400          # ... each cut to this length (journal.md has them whole)
SKIP_NOTES = ('stage:', 'phase:', 'render:') + tuple(f'{name}:' for name in (
    'brief', 'log', 'selects', 'story_plan', 'pickups', 'fine_pass', 'finish_pass', 'handover'))


CRAFT_SETTING, CRAFT_ENV = 'review_craft_checks', 'LETITEDIT_REVIEW_CRAFT_CHECKS'    # T346 (review/craft_checks)


def craft_switch():
    """T346's switch (settings.json review_craft_checks, default true; LETITEDIT_REVIEW_CRAFT_CHECKS wins): the
    hand-over carries the plan's opening."""
    forced = os.environ.get(CRAFT_ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(CRAFT_SETTING) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


def opening_line(plan):
    """'- opening: ...' from story_plan.json's opening (its template, the chosen candidate and its first frame), or
    None when the plan has none."""
    opening = plan.get('opening') if isinstance(plan, dict) else None
    if not isinstance(opening, dict):
        return f'- opening: {_line(opening)}' if opening not in (None, '', [], {}) else None
    chosen = opening.get('chosen')
    picked = next((c for c in opening.get('candidates') or [] if isinstance(c, dict) and chosen is not None
                   and c.get('id') == chosen), None)
    parts = {'template': opening.get('template'), 'chosen': picked or chosen, 'first_frame': opening.get('first_frame')}
    return '- opening: ' + _line({k: v for k, v in parts.items() if v not in (None, '', [], {})}, 500)


def switch():
    """settings.json new_video_bookkeeping (default true); LETITEDIT_NEW_VIDEO_BOOKKEEPING (1 or 0) wins."""
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


def enabled():
    """Whether code keeps this run's books: the switch is on and the run works in phases."""
    if not switch():
        return False
    from letitedit.app import new_video_stages
    return new_video_stages.phases_on()


def _flag(setting, env):
    """A settings.json switch (default true); its environment variable (1 or 0) wins."""
    forced = os.environ.get(env, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(setting) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


def full():
    """Whether code keeps the rest of the books too (T345 C1): beat, loop and cut markers, licence notes, the stage
    files' checks in the journal's reply. Needs its own switch (settings.json new_video_bookkeeping_full,
    LETITEDIT_NEW_VIDEO_BOOKKEEPING_FULL) and enabled()."""
    return _flag(FULL_SETTING, FULL_ENV) and enabled()


def markers_follow():
    """Whether an apply carries the timeline's markers with their clips (T345 C1): its own switch (settings.json
    markers_follow_clips, LETITEDIT_MARKERS_FOLLOW_CLIPS), for any edit, or full() in a New video run."""
    return _flag(FOLLOW_SETTING, FOLLOW_ENV) or full()


def _marked(journal, text_of):
    return {name for name in (text_of(e) for e in journal if e.get('kind') == 'note') if name}


def _phase_mark(text):
    text = str(text or '').strip()
    if text.startswith('phase:') and ':done' in text:
        return text[len('phase:'):].split(':done', 1)[0]
    return None


def _tell_card(project, stages):
    """The progress card hears the stage marks written here as it hears the AI's own (a journal note through the tool
    server): written straight into the journal, New video's card stayed on its third step, "Cutting your video", from
    the rough cut to the end of a two-hour run (T379). The card's run is the one the project belongs to; none: nothing."""
    if not stages:
        return
    try:
        from letitedit.app import progress_feed
        for name in stages:
            progress_feed.record_tool('letitedit_journal', {'action': 'note', 'text': f'stage:{name}:done',
                                                            'project': str(project)}, finished=True)
    except Exception:  # noqa: BLE001 - the card is a view; the marks stand whatever it says
        pass


def marks(project, request=''):
    """Write the done marks whose outputs check out and that aren't there yet. Returns what was written and refused."""
    project = Path(project)
    out = {'stages': [], 'phases': [], 'refused': {}}
    if not project.is_file():
        return out
    for name in project_journal.STAGES:
        state = project_journal.stage_progress(project)[name]
        if state['done']:
            continue
        if state['missing']:
            break                                    # this stage isn't done: nothing after it can be
        try:
            project_journal.note(project, f'stage:{name}:done — {MARK_SUMMARY}', ACTOR)
        except ValueError as error:                  # the journal's own refusal (the fine stage's restarts, say)
            out['refused'][name] = str(error)
            break
        out['stages'].append(name)
    _tell_card(project, out['stages'])
    from letitedit.app import phases
    have = _marked(project_journal.entries(project, None), lambda e: _phase_mark(e.get('text')))
    for name in phases.AI_PHASES:
        if name in have:
            continue
        if not phases.done(name, project, request)['done']:
            break
        project_journal.note(project, f'phase:{name}:done — {MARK_SUMMARY}', ACTOR)
        out['phases'].append(name)
    return out


def books_markers(project, timeout_s=BOOKS_TIMEOUT_S):
    """With full(): the why, beat, loop and cut markers as one marker change and the licence notes, in their own
    process (letitedit.server.books.write). Returns its receipt, whose `why` is why_markers's. Never raises."""
    return why_markers(project, timeout_s, command='books')


def why_markers(project, timeout_s=WHY_TIMEOUT_S, command='why'):
    """The why markers, written in their own process (the marker code sits above this layer). Never raises."""
    from letitedit.core import paths
    try:
        run = subprocess.run([sys.executable, '-m', 'letitedit.server.journal_tools', command, str(Path(project))],
                             cwd=str(paths.BRIDGE), capture_output=True, text=True, encoding='utf-8',
                             errors='replace', timeout=timeout_s,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError) as error:
        return {'error': f'the why markers could not be written: {error}'}
    try:
        answer = json.loads((run.stdout or '').strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'error': 'the why markers could not be written: '
                         + ((run.stderr or run.stdout or 'no answer').strip()[-300:])}
    return answer if isinstance(answer, dict) else {'error': 'the why markers gave no receipt'}


def _json(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _line(value, limit=300):
    if isinstance(value, (list, tuple)):
        value = '; '.join(_line(v, limit) for v in value if v not in (None, '', [], {}))
    elif isinstance(value, dict):
        value = '; '.join(f'{k}: {_line(v, limit)}' for k, v in value.items() if v not in (None, '', [], {}))
    text = ' '.join(str(value if value is not None else '').split())
    return text if len(text) <= limit else text[:limit - 3] + '...'


def _ts(text):
    try:
        return dt.datetime.fromisoformat(str(text).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def read_script(project):
    """The project's edit script as the phases read it: the open window's snapshot when it is open, else the saved
    file; None without a project file (letitedit.app.phases.read_script, for the jobs above this one)."""
    from letitedit.app import phases
    return phases.read_script(project)


def _cut(project):
    """(main-track clips, length in seconds) of the cut now: the window's snapshot when it is open, else the file."""
    from letitedit.timeline import edit_sync
    script = read_script(project)
    track = edit_sync.main_track(script) if script else None
    rows = [(it, s, e) for it, s, e in edit_sync.layout(track)] if track else []
    clips = [row for row in rows if 'clip' in row[0]]
    return clips, (max((e for _, _, e in rows), default=0.0))


def _books_lines(books):
    """The hand-over's lines for the rest of the books (T345 C1): what code wrote and what it couldn't place."""
    if books.get('error'):
        return [f"- beat, loop and cut markers and licence notes: not written by code ({books['error']}): write them "
                '(letitedit-rough ROUGH-4, letitedit-firstcut FIRST-4, letitedit-sound).']
    beats, loops, cuts = books.get('beats') or {}, books.get('loops') or {}, books.get('cuts') or {}
    lines = [f"- beat markers: {beats.get('beats', 0) - len(beats.get('unmatched') or [])} of {beats.get('beats', 0)} "
             f"beats are on the timeline with one; loop markers for {loops.get('loops', 0)} loop(s)."]
    if beats.get('unmatched'):
        lines.append('  - beats no main-track clip plays (dropped, or their selects changed): '
                     + ', '.join(str(b) for b in beats['unmatched'][:12]) + '.')
    lines.append(f"- cut markers: {cuts.get('written', 0)} written from selects.json's cuts "
                 f"({cuts.get('cuts', 0)} listed).")
    for row in (cuts.get('unplaced') or [])[:8]:
        lines.append(f"  - a cut no join skips ({row.get('file')}: {row.get('why')}): place its `cut:` marker "
                     'if it was taken out.')
    for row in (cuts.get('uncovered') or [])[:8]:
        lines.append(f"  - {row.get('to', 0) - row.get('from', 0):.1f} s of {Path(str(row.get('file'))).name} "
                     f"({row.get('from')}-{row.get('to')} s) skipped at {row.get('at')} s with no `cut:` marker: add "
                     'it to selects.json\'s cuts with its why.')
    lic = books.get('licences') or {}
    if lic.get('error'):
        lines.append(f"- licence notes: not written by code ({lic['error']}).")
    elif lic.get('written'):
        lines.append('- licence notes written for the library files: '
                     + ', '.join(Path(f).name for f in lic['written'][:8]) + '.')
    return lines


def handover_text(project, request, phase, since, why=None, books=None):
    """The hand-over to the phase after `phase`, made from the files (a few KB)."""
    from letitedit.app import phases
    project = Path(project)
    work = project.with_suffix('.letitedit')
    following = phases.NEXT.get(phase)
    lines = [HEADER, '']
    title = phases.PHASES[phase]['title']
    if following:
        lines.append(f"The {title} phase is done: its outputs check out. Next: the "
                     f"{phases.PHASES[following]['title']} phase, from its "
                     f"{phases.first_step(following, project)} step.")
    else:
        lines.append(f'The {title} phase is done.')
    lines.append('The original request and brief.json govern; the files below are the record. Never redo a step '
                 'that is done.')
    brief = _json(work / 'brief.json') or {}
    if brief:
        lines += ['', '## The brief (brief.json)']
        for key in ('purpose', 'mode', 'look', 'deliverables', 'target_s', 'feel', 'must_keep', 'must_avoid',
                    'required_lines', 'claims', 'ending', 'protected', 'narration', 'captions', 'music'):
            if brief.get(key) not in (None, '', [], {}):
                lines.append(f'- {key}: {_line(brief[key])}')
    plan = _json(work / 'story_plan.json') or {}
    if plan:
        lines += ['', '## The plan (story_plan.json)']
        for key in ('purpose', 'logline', 'feel', 'stakes', 'open_question', 'ending'):
            if plan.get(key) not in (None, '', [], {}):
                lines.append(f'- {key}: {_line(plan[key])}')
        if craft_switch() and opening_line(plan):      # T346: the opening chosen at the story step, carried forward
            lines.append(opening_line(plan))
        for section in plan.get('sections') or []:
            if isinstance(section, dict):
                lines.append(f"- section {section.get('id', '?')}: " + _line(
                    {k: section.get(k) for k in ('label', 'purpose', 'driver', 'gear', 'feel', 'target_s')}))
        open_loops = [loop for loop in plan.get('loops') or [] if isinstance(loop, dict) and not loop.get('closes')]
        if open_loops:
            lines.append('- loops still open: ' + _line([loop.get('question') for loop in open_loops]))
    clips, length = _cut(project)
    lines += ['', '## The cut now', f'- the main track: {len(clips)} clip(s), {length:.1f} s.']
    if why:
        if why.get('error'):
            lines.append(f"- why markers: not written by code ({why['error']}): give each main-track clip its "
                         '`why:` marker (letitedit-firstcut FIRST-4).')
        else:
            lines.append(f"- why markers: {why.get('covered', 0)} of {why.get('clips', len(clips))} main-track clips "
                         'have one.')
            for row in why.get('unmatched') or []:
                lines.append(f"  - no select matched clip {row.get('id')} ({row.get('clip')} at "
                             f"{row.get('start', 0):.2f}-{row.get('end', 0):.2f} s): give it its `why:` marker.")
    if books:
        lines += _books_lines(books)
    notes = []
    for entry in project_journal.entries(project, None):
        text = str(entry.get('text') or '').strip()
        t = _ts(entry.get('time'))
        if entry.get('kind') != 'note' or not text or t is None or t < since or text.startswith(SKIP_NOTES):
            continue
        notes.append(f"- {entry.get('actor', '?')}: {_line(text, NOTE_CHARS)}")
    if notes:
        lines += ['', "## This run's notes (journal; journal.md has them whole)"] + notes[-NOTES_LAST:]
    if following:
        missing = phases.done(following, project, request)['missing']
        if missing:
            lines += ['', f"## What the {phases.PHASES[following]['title']} phase still needs"]
            lines += [f'- {item}' for item in missing]
    from letitedit.app import new_video_stages
    present = [name for name in new_video_stages.CARRIED if name != 'handover.md' and (work / name).is_file()]
    if present:
        lines += ['', '## Files to read', f'- in {work}: ' + ', '.join(present)]
    return '\n'.join(lines) + '\n'


def _ai_handover(work, since):
    """True when the AI wrote a hand-over during this run (kept as it is)."""
    path = Path(work) / 'handover.md'
    try:
        text = path.read_text(encoding='utf-8')
        return path.stat().st_mtime >= since and bool(text.strip()) and not text.startswith(HEADER)
    except OSError:
        return False


def after_phase(project, request, phase, since):
    """At a phase boundary: the marks, the why markers (after a phase that cut the picture) and the hand-over.
    Returns {'marks', 'why', 'handover': path, 'handover_by': 'letitedit' | 'ai'}."""
    project = Path(project)
    work = project.with_suffix('.letitedit')
    receipt = {'marks': marks(project, request)}
    why = books = None
    if phase in ('plan_rough', 'fine_finish'):
        if full():                                   # T345 C1: the why markers come with the rest of the books
            books = books_markers(project)
            why = books if books.get('error') else (books.get('why') or {})
            receipt['books'] = books
        else:
            why = why_markers(project)
    if why is not None:
        receipt['why'] = why
    path = work / 'handover.md'
    if _ai_handover(work, since):
        receipt.update(handover=str(path), handover_by='ai')
        return receipt
    try:
        text = handover_text(project, request, phase, since, why, books)
        work.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.md.tmp')
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, path)
        receipt.update(handover=str(path), handover_by=ACTOR)
    except OSError as error:
        receipt.update(handover=None, handover_error=str(error))
    return receipt
