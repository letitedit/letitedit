"""New video's phases in sub-steps, each in a fresh session that carries only its own skills (T344's lever 1, T354).
On by default.

    enabled()                         the switch
    ORDER, SUBSTEPS                   the sub-steps in order, each with the keys of a phase entry (letitedit.app.phases)
    of_phase(phase)                   a phase's sub-steps, in order
    first_of(phase), last_of(phase)   its first and last sub-step
    unit(name)                        a sub-step's entry (KeyError for anything else)
    done(name, project, request)      {'phase', 'done', 'missing', 'newest'}: its outputs, checked on the files
    first_step(name, project)         the stage a sub-step's work starts at

| Sub-step | Phase | Stages | Its own skills | Ends when (in code) |
|---|---|---|---|---|
| log_plan | plan_rough | log, story | log, story | brief, log and selects, story plan and pickups check out |
| rough_cut | plan_rough | rough_cut | rough | the rough cut is on the main track and its export was watched |
| fine_cut | fine_finish | fine_cut | fine, sound (captions once the cut has them) | fine_pass.md, the cut on the main track |
| finishing | fine_finish | finishing | finish, sound, captions | finish_pass.md; captions and music when the request asks |
| review_rounds | review_export | review_rounds | gate, review | a review says the rounds are used up, or one of the cut now is ready |
| final_look | review_export | review_rounds | gate, review | the review_export phase checks out, after this sub-step's own turn |

Every sub-step also carries the base four (stage_start.BASE_SKILLS) and the skills its routes attach
(stage_start.ROUTE_SKILLS, ROUTE_FROM_FINE, the references by route), exactly as its stage did inside its phase. The
cut points are Run 7's (tests/t354/REPORT.md): where a fresh start costs least and loses least. Finishing stays one
sub-step: its sound part has no output of its own that code could check before the captions start (the finish skill
runs them as one pass, finish_pass.md at its end), and splitting it saved about 3% more on Run 7's records. The
review's rounds and its final look are two: the second starts after the rounds are used up and opens with every
finding still open.

A sub-step after the first starts from a hand-off made and checked in code (letitedit.studio.substep_handoff): every
brief requirement, the overlay boxes, every open review finding with its evidence, the device ledger and each kept
clip's why. One missing stops the run before the next session starts.

The switch: settings.json `substep_sessions` (default true; LETITEDIT_SUBSTEP_SESSIONS, 1 or 0, wins). It acts only
in the session runner's phase run (studio.session_runner), read once when a run starts. Off, nothing here is used.
With `work_in_passes` on too, every sub-step's start attaches the pass shape like a phase's (stage_start's `passes`
route), so each sub-step works in passes inside its own session.
"""
import json
import os
from pathlib import Path

from letitedit.timeline import project_journal

SETTING = 'substep_sessions'
ENV = 'LETITEDIT_SUBSTEP_SESSIONS'
NOUN = 'sub-step'

ORDER = ('log_plan', 'rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look')
SUBSTEPS = {
    'log_plan': {
        'number': 1, 'title': 'log and plan', 'who': 'ai', 'phase': 'plan_rough', 'stages': ('log', 'story'),
        'skills': ('letitedit-log', 'letitedit-story'), 'guides': (),
        'tools': 'plan', 'model_role': 'plan', 'step_roles': {'log': 'plan', 'story': 'plan'},
        'carries': ('brief.json', 'log.json', 'selects.json', 'inputs.json'),
        'outputs': ('brief.json', 'log.json and selects.json (unless the Look has no footage)',
                    'story_plan.json and pickups.md'),
        'work': 'log the footage and plan the story: brief.json, log.json and selects.json, story_plan.json and '
                'pickups.md. No edit on the timeline yet',
    },
    'rough_cut': {
        'number': 2, 'title': 'rough cut', 'who': 'ai', 'phase': 'plan_rough', 'stages': ('rough',),
        'skills': ('letitedit-rough',), 'guides': ('edits', 'items', 'effects'),
        'tools': 'plan', 'model_role': 'plan', 'step_roles': {'rough': 'plan'},
        'carries': ('brief.json', 'story_plan.json', 'selects.json', 'pickups.md', 'inputs.json'),
        'outputs': ('the rough cut on the main video track', 'a watched rough export (render:<file path>)'),
        'work': 'build the rough cut from story_plan.json and selects.json, render it and watch it (render:<file '
                'path>), and run the rough cut\'s story checks',
    },
    'fine_cut': {
        'number': 3, 'title': 'fine cut', 'who': 'ai', 'phase': 'fine_finish', 'stages': ('fine',),
        'skills': ('letitedit-fine', 'letitedit-sound'), 'guides': ('edits', 'items', 'effects'),
        'tools': 'finish', 'model_role': 'plan', 'step_roles': {'fine': 'plan'},
        'carries': ('brief.json', 'story_plan.json', 'selects.json', 'inputs.json'),
        'outputs': ('fine_pass.md', 'the cut on the main video track'),
        'work': 'the fine cut: retime the dialogue, clean the joins, time the b-roll and write fine_pass.md',
    },
    'finishing': {
        'number': 4, 'title': 'finish', 'who': 'ai', 'phase': 'fine_finish', 'stages': ('finish',),
        'skills': ('letitedit-finish', 'letitedit-sound', 'letitedit-captions'),
        'guides': ('edits', 'items', 'effects', 'code'),
        'tools': 'finish', 'model_role': 'routine', 'step_roles': {'finish': 'routine'},
        'carries': ('brief.json', 'story_plan.json', 'fine_pass.md', 'inputs.json'),
        'outputs': ('finish_pass.md', 'captions on the timeline when the request asks for them',
                    'music on a Music track when the request asks for it'),
        'work': 'the finish: match the shots, clean the voice, the sound pass and music, graphics and captions, '
                'then write finish_pass.md',
    },
    'review_rounds': {
        'number': 5, 'title': 'review rounds', 'who': 'ai', 'phase': 'review_export', 'stages': ('review',),
        'skills': ('letitedit-gate', 'letitedit-review'), 'guides': ('edits', 'items', 'effects'),
        'tools': 'review', 'model_role': 'plan', 'step_roles': {'review': 'plan'},
        'carries': ('brief.json', 'story_plan.json', 'fine_pass.md', 'finish_pass.md', 'review_memory.json',
                    'inputs.json'),
        'outputs': ('a review that says the review rounds are used up, or a review of the cut now that is ready',),
        'work': 'the review rounds: run the review bundle, fix what each round finds, and run the next round, until '
                'the bundle says the rounds are used up or a review of the cut now is ready. The final look, the '
                'hook candidates and the closing message come in the next sub-step',
    },
    'final_look': {
        'number': 6, 'title': 'final look and hand-over', 'who': 'ai', 'phase': 'review_export',
        'stages': ('review',), 'skills': ('letitedit-gate', 'letitedit-review'),
        'guides': ('edits', 'items', 'effects'),
        'tools': 'review', 'model_role': 'plan', 'step_roles': {'review': 'plan'},
        'carries': ('brief.json', 'story_plan.json', 'fine_pass.md', 'finish_pass.md', 'review_memory.json',
                    'inputs.json'),
        'outputs': ('a review of the current cut that is ready, or the last allowed round',),
        'needs_turn': True,
        'work': 'fix every finding still open that the hand-off lists, run the last review (render=\'final\') '
                'when the cut changed or the rounds ask for it, then the hook candidates and the closing message '
                '(letitedit-firstcut section 4)',
    },
}
# The route-scoped lists (stage_start's route switch on; phases.ROUTE_SCOPED's shape). `core` is always attached,
# each `routed` skill when one of its routes applies. The fine sub-step is the fine step of the fine-and-finish phase
# as T342 starts it: captions come once the cut has captions (stage_start keeps that rule).
ROUTE_SCOPED = {
    'log_plan': {'core': ('letitedit-log', 'letitedit-story'), 'routed': {}},
    'rough_cut': {'core': ('letitedit-rough',), 'routed': {}},
    'fine_cut': {'core': ('letitedit-fine', 'letitedit-sound'), 'routed': {}},
    'finishing': {'core': ('letitedit-finish', 'letitedit-sound', 'letitedit-captions'), 'routed': {}},
    'review_rounds': {'core': ('letitedit-gate', 'letitedit-review'),
               'routed': {'letitedit-captions': ('captions:on',), 'letitedit-sound': ('music:any', 'song')}},
    'final_look': {'core': ('letitedit-gate', 'letitedit-review'),
              'routed': {'letitedit-captions': ('captions:on',), 'letitedit-sound': ('music:any', 'song')}},
}
for _name, _spec in SUBSTEPS.items():
    _spec['noun'] = NOUN
    _spec['display_noun'] = 'step'
    _spec['id'] = _name
NEXT = dict(zip(ORDER[:-1], ORDER[1:]))
PREVIOUS = {after: before for before, after in NEXT.items()}


def enabled():
    """Whether New video's phases run as sub-steps, a session each (on by default)."""
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


# Two switches of the sub-step run (settings.json; the environment variable, 1 or 0,
# wins), read once when a run starts, and acting only with sub-step sessions on:
#   - review_round_sessions (cut 3): the review rounds sub-step gives each critic round its own session. The round ends
#     its turn once its critic has read the cut; the next round starts in a fresh session from a hand-off made and
#     checked in code (letitedit.studio.round_handoff), never from the last round's conversation;
#   - hooks_on_demand (cut 5): the run makes no hook candidates. The opening is the story's (letitedit-firstcut
#     FIRST-5a0); the app's New hook button makes candidates from the cut when the person clicks it (hooks.py next
#     builds hooks.json when there is none, in its own background process).
ROUND_SETTING, ROUND_ENV = 'review_round_sessions', 'LETITEDIT_REVIEW_ROUND_SESSIONS'
HOOKS_SETTING, HOOKS_ENV = 'hooks_on_demand', 'LETITEDIT_HOOKS_ON_DEMAND'
ROUND_SESSIONS_MAX = 4          # a ceiling, not a target: the bundle's round limit ends the rounds well before it
ROUND_NOTE = ('End the round\'s turn with your note for the next round, at most about 15 lines: what you changed and '
              'why, what you tried that didn\'t work and why, where things are that the next round needs (a drawn '
              'scene\'s id and file, clip ids, the music file) and what you would do next. letitedit carries it word '
              'for word, with every finding still open, what this round changed, the calls that failed and the files '
              'it read')
ON_DEMAND_LINE = ('Hook candidates are made on demand in this run: the app\'s New hook button makes them from the cut '
                  'when the person clicks it. Don\'t call letitedit_hooks and write no candidates; keep the opening '
                  'the story chose (letitedit-firstcut FIRST-5a0) unless a review finding asks for another. In the '
                  'closing message, say that New hook offers other openings, and name none (FIRST-7: only candidates '
                  'hooks.json lists)')


def _switch(env, setting, default=False):
    forced = os.environ.get(env, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        value = hardware.settings().get(setting)
        return value is not False if default else value is True
    except Exception:  # noqa: BLE001 - an unreadable setting uses the default
        return default


def round_sessions_on():
    """Whether each review round gets its own session (T363's cut 3; off by default)."""
    return _switch(ROUND_ENV, ROUND_SETTING)


def hooks_on_demand():
    """Whether the run leaves hook candidates to the New hook button (on by default)."""
    return _switch(HOOKS_ENV, HOOKS_SETTING, default=True)


def work(name, rounds=None, on_demand=None):
    """A sub-step's work line, by the switches. rounds: the critic rounds done before this session, when the review
    rounds run a session each (None: one session for all of them, as T354 made it)."""
    on_demand = hooks_on_demand() if on_demand is None else on_demand
    text = SUBSTEPS[name]['work']
    if name == 'review_rounds' and rounds is not None:
        number = int(rounds) + 1
        if number == 1:
            text = ('the review rounds, one round in this conversation: fix what letitedit\'s measured checks found '
                    '(attached, when they ran), then run the review bundle until its critic has read the cut once '
                    '(one review round), then end your turn. Each later round starts in a fresh conversation from a '
                    'hand-off letitedit makes from the files. ' + ROUND_NOTE)
        else:
            text = (f'review round {number}, in a fresh conversation: fix the findings still open (the hand-off lists '
                    'them, with what the last round changed and tried, the files it read and its note), then run the '
                    'review bundle until its critic has read the changed cut, then end your turn; never redo a fix the '
                    'hand-off says is done. ' + ROUND_NOTE)
        text += ('. The bundle says when the rounds are used up; the final look'
                 + (' and the closing message come' if on_demand else ', the hook candidates and the closing message '
                    'come') + ' in the next sub-step')
    elif name == 'review_rounds' and on_demand:
        text = text.replace('The final look, the hook candidates and the closing message',
                            'The final look and the closing message')
    if name == 'final_look' and on_demand:
        text = text.replace(', then the hook candidates and the closing message', ', then the closing message')
        text += '. ' + ON_DEMAND_LINE
    return text


def unit(name):
    return SUBSTEPS[name]


def of_phase(phase):
    return tuple(name for name in ORDER if SUBSTEPS[name]['phase'] == phase)


def first_of(phase):
    return of_phase(phase)[0]


def last_of(phase):
    return of_phase(phase)[-1]


def _bundles(folder):
    from letitedit.app import phases
    return phases._reviews(Path(folder))


def _rounds_used(project):
    """True when a review bundle of this project says the rounds are used up (they never go back), or one of the cut
    now is ready."""
    project = Path(project)
    try:
        cut = project.stat().st_mtime
    except OSError:
        cut = None
    for bundle in _bundles(project.parent):
        try:
            data = json.loads(bundle.read_text(encoding='utf-8-sig'))
            newer = cut is not None and bundle.stat().st_mtime >= cut
        except (OSError, ValueError):
            continue
        rounds = (data.get('rounds') or {}) if isinstance(data, dict) else {}
        if rounds.get('limit_reached') or rounds.get('final') or (newer and data.get('verdict') == 'ready'):
            return True
    return False


def done(name, project, request='', script=None, live=False):
    """Whether a sub-step's outputs check out on the files ({'phase': name, 'done', 'missing', 'newest'}). A
    sub-step that ends its phase is its phase's own test (phases.done); one before it checks its own outputs and
    every earlier phase. `needs_turn` (the final sub-step) is the runner's: its own turn must have run."""
    from letitedit.app import phases
    spec = SUBSTEPS[name]
    project = Path(project)
    if name == last_of(spec['phase']):
        result = dict(phases.done(spec['phase'], project, request, script=script, live=live))
        result['phase'] = name
        return result
    work = project_journal.folder(project)
    missing, outputs = [], []
    index = phases.AI_PHASES.index(spec['phase'])
    if index:
        before = phases.done(phases.AI_PHASES[index - 1], project, request, script=script, live=live)
        if not before['done']:
            missing.append(f"the {phases.PHASES[phases.AI_PHASES[index - 1]]['title']} phase")
            missing.extend(before['missing'])
    if name == 'log_plan':
        names = ['brief.json']
        if not project_journal.nothing_to_log(project):
            names += ['log.json', 'selects.json']
        names += ['story_plan.json', 'pickups.md']
        for file in names:
            path = phases._output(project, work, file)
            if path is None:
                missing.append(project_journal.OUTPUT_HINTS.get(file, file))
            else:
                outputs.append(path)
    elif name == 'fine_cut':
        path = phases._output(project, work, 'fine_pass.md')
        if path is None:
            missing.append('fine_pass.md')
        else:
            outputs.append(path)
        if project.is_file():
            if script is None:
                script = phases.read_script(project, live=live)
            if not phases._main_clips(script):
                missing.append('the cut on the main video track')
            outputs.append(project)
        else:
            missing.append('the project file')
    elif name == 'review_rounds':
        if not _rounds_used(project):
            missing.append('a review that says the review rounds are used up, or a review of the cut now that is '
                           'ready')
        else:
            outputs.extend(_bundles(project.parent))
    else:                                            # pragma: no cover - every sub-step is named above
        raise ValueError(f'Unknown sub-step: {name}')
    return {'phase': name, 'done': not missing, 'missing': missing, 'newest': phases._mtime(*outputs)}


def first_step(name, project):
    """The stage a sub-step's work starts at (phases.first_step within its own stages)."""
    stages = SUBSTEPS[name]['stages']
    if len(stages) == 1:
        return stages[0]
    project = Path(project)
    for stage in stages:
        if stage == 'log' and project_journal.nothing_to_log(project):
            continue
        if any(not project_journal.has_stage_output(project, file) for file in project_journal.STAGE_FILES[stage]):
            return stage
    return stages[-1]
