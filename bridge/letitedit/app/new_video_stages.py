"""New video with a fresh conversation for the review: when the finish is done and handed over while the conversation
is big, the app starts the review rounds in a fresh conversation that carries the work on disk instead of the whole
conversation.

    next_session(folder, since, request)   None, or {'decision': 'next_stage', 'stage_done', 'next', 'request', ...}

The app asks for this (its request JSON to new_video_carry.py has `stage_sessions: true` and the New video request,
which has the line `sessions: one per stage`). A conversation ends after `stage:<name>:done` for a name in BOUNDARIES
once a hand-over note written during that stage exists (`handover:` through letitedit_journal writes handover.md;
letitedit-firstcut FIRST-1s). The stage note's reply asks for the hand-over only when the conversation has reached
fresh_at() tokens (hand_over_note, measured from the AI's own log): a smaller conversation goes on as it is. Each
boundary starts one fresh conversation, recorded in the project's working folder (stage-sessions.json), so a repeated
check never starts two. Without a hand-over nothing starts here: the app's ordinary carry-on goes on in the same
conversation.

Measured on 12 Nov (T194, tests/t194/REPORT.md): a fresh conversation after every stage (story, rough, fine, finish)
doubled the tokens of a 1:30 video, so only the review, where a long video's conversation is largest, starts fresh,
and only when the conversation is big.

A run that stops after a stage (a Studio preview, which ends after the rough cut: studio/short.py): the window runs with
LETITEDIT_NEW_VIDEO_STOP_AFTER=<stage>. That stage's done note's reply asks for the hand-over and the end of the turn
whatever the switch below or the conversation's size, and the carry-on check reads the run as finished (stopped()).

The switch: settings.json `new_video_stage_sessions` (default true; the environment variable LETITEDIT_STAGE_SESSIONS,
1 or 0, wins). Off, nothing here starts a conversation, a stage note's reply asks for no hand-over, and the slimmer
replies that come with it (slim(): the journal read, letitedit_bin, letitedit_caption_fit, compact JSON) stay as
they were: a request that has the line runs as one conversation, exactly as before the line existed.

Phases (T319's rule 1, T322 step P5; letitedit/app/phases.py): with settings.json `new_video_phases` on (or
LETITEDIT_NEW_VIDEO_PHASES=1) and lean hand-offs off (phases_on()), a run with the line works in three AI phases
instead of six stages: start_request builds a phase's first message for any of its stages' names, and next_session
starts the next phase's conversation once the current phase's outputs check out in code (phase_done), with no hand-over
mark or conversation size needed. Each boundary starts at most one conversation per run (stage-sessions.json). A run
that stops after a stage stops once that stage's phase checks out. Off, none of this is used.

Bookkeeping in code (T319's rule 5, T331 step P8; letitedit/app/bookkeeping.py): with settings.json
`new_video_bookkeeping` on (LETITEDIT_NEW_VIDEO_BOOKKEEPING=1) in a run in phases, every carry check writes the stage
and phase done marks whose outputs check out, and a phase boundary writes the clips' why markers from selects.json and
the hand-over from the files before the next phase starts (its result has `bookkeeping`, the receipt). Off (the
default), the AI writes them as the skills say.
"""
import datetime as dt
import glob
import json
import os
import re
import subprocess
import time
from pathlib import Path

from letitedit.timeline import project_journal

BOUNDARIES = ('finish',)   # a fresh conversation after these (for the review rounds), when the conversation is big
NEXT = {'story': 'rough', 'rough': 'fine', 'fine': 'finish', 'finish': 'review'}
STAGE_SKILL = {'rough': 'letitedit-rough', 'fine': 'letitedit-fine', 'finish': 'letitedit-finish',
               'review': 'letitedit-gate'}
REVIEW_WORK = ' (the review rounds, their fixes, the final export and the closing message: letitedit-firstcut section 4)'
# what the next stage reads from the working folder, in this order, when it exists
CARRIED = ('handover.md', 'brief.json', 'story_plan.json', 'selects.json', 'log.json', 'pickups.md', 'fine_pass.md',
           'finish_pass.md')
# the review works from the hand-over, the brief and the plan; the hand-over sums up the rest
CARRIED_REVIEW = ('handover.md', 'brief.json', 'story_plan.json')
JOURNAL_LAST = 10          # journal entries a fresh conversation reads
STATE = 'stage-sessions.json'
LINE = 'sessions: one per stage'
SETTING = 'new_video_stage_sessions'
ENV = 'LETITEDIT_STAGE_SESSIONS'
FRESH_AT = 250_000         # tokens in the conversation from which a fresh one pays (LETITEDIT_STAGE_SESSIONS_AT)
STOP_ENV = 'LETITEDIT_NEW_VIDEO_STOP_AFTER'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
LEAN_ENV = 'LETITEDIT_LEAN_STAGE_HANDOFFS'
LEAN_SETTING = 'new_video_lean_stage_handoffs'
PREPARED_PROJECT_ENV = 'LETITEDIT_NEW_VIDEO_PREPARED_PROJECT'


def lean_enabled():
    """Independent experimental switch; the legacy review-only switch is unchanged."""
    forced = os.environ.get(LEAN_ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(LEAN_SETTING) is True
    except Exception:
        return False


def phases_on():
    """Whether this run works in phases (letitedit.app.phases, on by default). Lean hand-offs keep their own path."""
    from letitedit.app import phases
    return phases.enabled() and not lean_enabled()


def phase_done(project, request=''):
    """letitedit.app.phases.done for the phase a project is in: {'phase', 'done', 'missing', 'newest'} of the first AI
    phase whose outputs don't check out yet (the last phase's, when all do)."""
    from letitedit.app import phases
    states = phases.progress(project, request)
    current = next((name for name in phases.AI_PHASES if not states[name]['done']), phases.AI_PHASES[-1])
    return states[current]


def enabled():
    """Whether New video may hand the review to a fresh conversation, with the slimmer replies, on this install (the
    switch above; on by default)."""
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


slim = enabled   # the slimmer replies come and go with the switch


def fresh_at():
    """Tokens in the conversation from which the review starts fresh (FRESH_AT; LETITEDIT_STAGE_SESSIONS_AT wins)."""
    try:
        return int(os.environ.get(ENV + '_AT') or FRESH_AT)
    except ValueError:
        return FRESH_AT


_PARENTS = r'''$p = {pid}; $out = @()
for ($i = 0; $i -lt 6 -and $p; $i++) {{
  $x = Get-CimInstance Win32_Process -Filter "ProcessId=$p"
  if (-not $x) {{ break }}
  $out += [string]$x.CommandLine
  $p = $x.ParentProcessId
}}
$out -join "`n"'''


def _parent_sessions():
    """Claude Code session ids named on the command lines of this process's parents (the AI program that started
    this tool server was given --session-id or --resume), nearest first. Windows only; [] elsewhere or on failure."""
    if os.name != 'nt':
        return []
    try:
        text = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                               _PARENTS.format(pid=os.getpid())], capture_output=True, text=True, timeout=20,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return re.findall(r'--(?:session-id|resume)[ =]"?(' + UUID + ')', text or '')


def context_of(session, homes=None):
    """The size in tokens of a Claude Code conversation at its last step (its log's last usage), or None."""
    for home in homes or [Path.home()]:
        for path in glob.glob(str(Path(home) / '.claude' / 'projects' / '*' / f'{session}.jsonl')):
            try:
                with open(path, 'rb') as f:
                    f.seek(0, os.SEEK_END)
                    f.seek(max(0, f.tell() - 600_000))
                    tail = f.read().decode('utf-8', errors='replace').splitlines()
            except OSError:
                continue
            for line in reversed(tail):
                if '"usage"' not in line:
                    continue
                try:
                    u = json.loads(line)['message']['usage']
                except (ValueError, KeyError, TypeError):
                    continue
                return int(u.get('input_tokens', 0) + u.get('cache_read_input_tokens', 0)
                           + u.get('cache_creation_input_tokens', 0))
    return None


def current_context():
    """The size of the conversation this tool server works for, or None when it can't be told (Codex; not Windows)."""
    for session in _parent_sessions():
        size = context_of(session)
        if size is not None:
            return size
    return None


def stop_after():
    """The stage after which this run stops (LETITEDIT_NEW_VIDEO_STOP_AFTER), or None."""
    stage = os.environ.get(STOP_ENV, '').strip().lower()
    return stage if stage in NEXT else None


def stop_note(text):
    """The reply's words when this done note ends a run that stops after its stage, or None."""
    name = project_journal.stage_name(text)
    stage = stop_after()
    if not stage or name != stage:
        return None
    if lean_enabled():
        return (f'This lean New video stops after {stage}: write the structured FIRST-1s handover now, '
                f'then end with `Stage {stage} done; stopping here`. No further stage, review or export.')
    from letitedit.app import bookkeeping
    if bookkeeping.enabled():
        return (f"This New video stops after the {stage} stage (a preview; the person continues it later from this "
                f"project). The hand-over is made from the files: end your turn with the one line `Stage {stage} "
                "done; stopping here` and start nothing more: no further stage, no review, no export.")
    return (f"This New video stops after the {stage} stage (a preview; the person continues it later from this "
            f"project): hand over now as letitedit-firstcut FIRST-1s says (the `handover:` note, written for the "
            f"{NEXT[stage]} stage), then end your turn with the one line `Stage {stage} done; stopping here` and start "
            "nothing more: no further stage, no review, no export.")


def stopped(folder, since):
    """True when this run stops after a stage (stop_after()) and a working folder in `folder` has that stage's done
    note since `since`."""
    stage = stop_after()
    if not stage or not folder or not Path(folder).is_dir():
        return False
    if phases_on():
        from letitedit.app import phases
        phase = phases.phase_of(stage)
        if stage == phases.PHASES[phase]['stages'][-1]:     # a preview that ends with its phase stops when it checks out
            for work in Path(folder).glob('*.letitedit'):
                state = phases.done(phase, _project_of(work))
                if state['done'] and state['newest'] is not None and state['newest'] >= since:
                    return True
    return any(name == stage for work in Path(folder).glob('*.letitedit')
               for _, name in _stage_notes(work / 'journal.jsonl', since))


def bookkeep_stopped(folder, since, request=''):
    """A run that stopped after a stage (stopped()) with bookkeeping in code: the marks, the why markers and the
    hand-over of that stage's phase, for each project in `folder` (letitedit.app.bookkeeping.after_phase). Returns
    {project: receipt}; {} when bookkeeping is off. Never raises."""
    from letitedit.app import bookkeeping
    stage = stop_after()
    if not stage or not folder or not bookkeeping.enabled():
        return {}
    from letitedit.app import phases
    out = {}
    for work in Path(folder).glob('*.letitedit'):
        project = _project_of(work)
        if not project.is_file():
            continue
        try:
            out[str(project)] = bookkeeping.after_phase(project, request or '', phases.phase_of(stage), since)
        except (OSError, ValueError, KeyError, TypeError) as error:
            out[str(project)] = {'error': f'{type(error).__name__}: {error}'}
    return out


def hand_over_note(text, context=None):
    """The words a `stage:<name>:done` note's reply adds when this stage ends a conversation, or None. context: the
    conversation's size in tokens [measured from the AI's own log]; below fresh_at(), or unknown, the run goes on in
    the same conversation. A run that stops after this stage always gets stop_note's words."""
    stop = stop_note(text)
    if stop:
        return stop
    stage = project_journal.stage_name(text)
    if stage and phases_on():
        from letitedit.app import phases
        phase = phases.phase_of(stage)
        entry = phases.PHASES[phase]
        if stage != entry['stages'][-1] or phase == phases.ORDER[-1]:
            return None
        return (f"This step ends the {entry['title']} phase. When its outputs check out ("
                + '; '.join(entry['outputs']) + "), end your turn: the "
                f"{phases.PHASES[phases.NEXT[phase]]['title']} phase starts in a fresh conversation from the files. "
                "Missing outputs keep this conversation going until they are there.")
    if lean_enabled() and stage:
        return (f"If this run explicitly uses lean stage handoffs and `{LINE}`, write the structured handover "
                "now as FIRST-1s says, then end this turn. Code validates the boundary before a fresh session; "
                "missing or stale evidence stays in this session for repair. No context-size threshold applies.")
    if not enabled() or not stage:
        return None
    if stage not in BOUNDARIES:
        return None
    size = current_context() if context is None else context
    if size is None or size < fresh_at():
        return None
    return (f"If this New video's request has the line `{LINE}`: hand over now and end your turn "
            f"(letitedit-firstcut FIRST-1s); the {NEXT[stage]} stage starts in a fresh conversation (this one is at "
            f"about {size // 1000}k tokens). Without that line, go on in this conversation.")


def _ts(text):
    try:
        return dt.datetime.fromisoformat(str(text).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def stage_notes(journal, since):
    """[(time, stage)] of the stage done notes in a journal since `since` (the Studio reads a run's stages)."""
    return _stage_notes(journal, since)


def _stage_notes(journal, since):
    """[(time, stage)] of the journal's `stage:<name>:done` notes after `since`, in order."""
    out = []
    try:
        lines = journal.read_text(encoding='utf-8-sig', errors='replace').splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            o = json.loads(line)
        except ValueError:
            continue
        text = str(o.get('text') or '').strip()
        t = _ts(o.get('time'))
        stage = project_journal.stage_name(text)
        if o.get('kind') == 'note' and t is not None and t >= since and stage:
            out.append((t, stage))
    return sorted(out)


def _read_state(work):
    try:
        return json.loads((work / STATE).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {'sessions': []}


def _project_of(work):
    """The project file a working folder belongs to: <stem>.letitedit beside <stem>.mlt."""
    return work.parent / (work.name[:-len('.letitedit')] + '.mlt')


def handed_over(folder, since):
    """(working folder, stage, its done-note time, hand-over path) of the newest boundary this run handed over and
    has not yet started a conversation for, or None."""
    best = None
    for work in Path(folder).glob('*.letitedit'):
        notes = _stage_notes(work / 'journal.jsonl', since)
        if not notes:
            continue
        t, stage = notes[-1]                     # the newest stage done
        if stage not in BOUNDARIES:
            continue
        before = max([tt for tt, name in notes[:-1] if name != stage] or [since])
        handover = work / 'handover.md'
        try:                                     # a hand-over written during this stage, before or after its note
            if handover.stat().st_mtime < before or not handover.read_text(encoding='utf-8').strip():
                continue
        except OSError:
            continue
        started = {(s.get('stage'), round(float(s.get('done_at') or 0))) for s in _read_state(work).get('sessions', [])}
        if (stage, round(t)) in started:
            continue
        if best is None or t > best[2]:
            best = (work, stage, t, handover)
    return best


def _load_line(skills):
    """A stage always starts with whole skills, regardless of the section-loading switch."""
    return f'Skills attached in full: {skills}; read the rest in one step with the Skill tool, in full.\n'


def start_request(request, stage, project, **options):
    """Internal editor entry point for the first stage and later stages, on Claude or Codex."""
    from letitedit.app import stage_start
    prepared = os.environ.get(PREPARED_PROJECT_ENV)
    first = stage in ('log', 'story') or stage == 'plan_rough'
    if phases_on():
        from letitedit.app import phases
        stage = phases.phase_of(stage)
        options['lean'] = False
        options.setdefault('stop_after', stop_after())
    if prepared and first and options.get('handover') is None:
        project = Path(prepared)
        if not project.is_file():
            raise stage_start.IncompleteStart('The Studio prepared project is missing; do not start the AI.')
        folder = project.parent.as_posix()
        request = re.sub(r'^Save video in:[^\r\n]*', lambda match: 'Save video in: ' + folder,
                         request, flags=re.M)
    options.setdefault('lean', lean_enabled() and LINE in request.splitlines())
    return stage_start.build(request, stage, project, **options)


def fresh_request(request, work, stage, handover):
    """The first message of the next stage's conversation: the original New video request, word for word, then what
    is done and what to read."""
    return start_request(request, NEXT[stage], _project_of(Path(work)), handover=handover)['request']


def next_session(folder, since, request, live=None, checkpoint_only=False):
    """The next stage's fresh conversation, or None. Records it, so the same boundary never starts two."""
    if not folder or not Path(folder).is_dir():
        return None
    if phases_on():
        return _next_phase(folder, since, request, live)
    if lean_enabled():
        from letitedit.app import stage_handoff
        if LINE not in (request or '').splitlines():
            return None
        if not isinstance(live, dict) or not live.get('project'):
            return {'decision': 'unfinished', 'reason': 'Lean handoff needs explicit live editor state; repair in this session.'}
        try:
            work = Path(live['project']).with_suffix('.letitedit')
            if work.parent.resolve() != Path(folder).resolve() or \
                    stage_handoff.read_json(work / 'stage-run.json')['started_at'] < since:
                raise stage_handoff.InvalidHandoff('The run is outside this folder or predates this request.')
            if checkpoint_only:
                with stage_handoff.transition_lock(work):
                    path = stage_handoff.build(work, live)
                return {'decision': 'stage_checkpoint', 'handover': str(path)}
            return stage_handoff.next_transition(work, live)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
            return {'decision': 'unfinished', 'reason': f'Lean handoff needs repair in this session: {error}'}
    found = handed_over(folder, since)
    if not found:
        return None
    work, stage, done_at, handover = found
    try:
        options = {}
        if live:
            options.update({key: live[key] for key in ('timeline', 'look') if key in live})
            if live.get('ai'):
                options['ai'] = live['ai']['engine']
            if 'stage_start_max_bytes' in live:
                options['max_bytes'] = live['stage_start_max_bytes']
        startup = start_request(request, NEXT[stage], _project_of(work), handover=handover,
                                **options)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {'decision': 'unfinished', 'reason': f'Complete stage startup needs repair: {error}'}
    state = _read_state(work)
    state.setdefault('sessions', []).append({'stage': stage, 'next': NEXT[stage], 'done_at': done_at,
                                             'started': time.time(), 'handover': str(handover)})
    try:
        (work / STATE).write_text(json.dumps(state, indent=1), encoding='utf-8')
    except OSError:
        return None                               # without the record, starting one could repeat: carry on as before
    return {'decision': 'next_stage', 'stage_done': stage, 'next': NEXT[stage], 'project': str(_project_of(work)),
            'handover': str(handover), 'request': startup['request'],
            'startup': {key: value for key, value in startup.items() if key != 'request'}}


def _phase_boundary(folder, since, request):
    """(working folder, project, phase done, its newest output's time) of the newest phase whose outputs checked out
    during this run and whose next conversation this run hasn't started yet, or None."""
    from letitedit.app import phases
    best = None
    for work in Path(folder).glob('*.letitedit'):
        project = _project_of(work)
        if not project.is_file():
            continue
        states = phases.progress(project, request)
        finished = [name for name in phases.AI_PHASES if states[name]['done']]
        if not finished or finished[-1] == phases.ORDER[-1]:
            continue                                  # nothing done yet, or the review is (the carry check ends the run)
        phase = finished[-1]
        newest = states[phase]['newest']
        if newest is None or newest < since:
            continue                                  # done before this run: not this run's boundary
        started = [entry for entry in _read_state(work).get('sessions', [])
                   if entry.get('phase') == phase and float(entry.get('started') or 0) >= since]
        if started:
            continue                                  # this run already started the next phase
        if best is None or newest > best[3]:
            best = (work, project, phase, newest)
    return best


def _next_phase(folder, since, request, live=None):
    """The next phase's fresh conversation once a phase's outputs check out, or None (carry on in this one)."""
    if LINE not in (request or '').splitlines():
        return None
    from letitedit.app import bookkeeping
    books = bookkeeping.enabled()
    if books:                                     # the done marks whose outputs check out (T331 P8), every check
        for work in Path(folder).glob('*.letitedit'):
            try:
                bookkeeping.marks(_project_of(work), request)
            except (OSError, ValueError, KeyError, TypeError):
                pass                              # a mark is bookkeeping: it never stops the run
    found = _phase_boundary(folder, since, request)
    if not found:
        return None
    from letitedit.app import phases
    work, project, phase, newest = found
    following = phases.NEXT[phase]
    handover = work / 'handover.md'
    receipt = None
    if books:                                     # the why markers and the hand-over, made from the files
        try:
            receipt = bookkeeping.after_phase(project, request, phase, since)
        except (OSError, ValueError, KeyError, TypeError) as error:
            receipt = {'error': f'{type(error).__name__}: {error}'}
    try:
        fresh = handover.stat().st_mtime >= since and handover.read_text(encoding='utf-8').strip()
    except OSError:
        fresh = False
    options = {}
    if live:
        options.update({key: live[key] for key in ('timeline', 'look') if key in live})
        if live.get('ai'):
            options['ai'] = live['ai']['engine']
        if 'stage_start_max_bytes' in live:
            options['max_bytes'] = live['stage_start_max_bytes']
    try:
        startup = start_request(request, following, project, handover=handover if fresh else None, **options)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {'decision': 'unfinished', 'reason': f'Complete phase startup needs repair: {error}'}
    state = _read_state(work)
    state.setdefault('sessions', []).append({'phase': phase, 'next': following, 'done_at': newest,
                                             'started': time.time(), 'handover': str(handover) if fresh else None})
    try:
        (work / STATE).write_text(json.dumps(state, indent=1), encoding='utf-8')
    except OSError:
        return None                               # without the record, starting one could repeat: carry on as before
    out = {'decision': 'next_stage', 'stage_done': phase, 'next': following, 'phase_done': phase,
           'project': str(project), 'handover': str(handover) if fresh else None, 'request': startup['request'],
           'startup': {key: value for key, value in startup.items() if key != 'request'}}
    if receipt is not None:
        out['bookkeeping'] = receipt
    return out
