"""New video in three AI phases after a code-only prepare (T319's rule 1; T322 step P5). On by default.

    PHASES[id]                       a phase's stages, skills, guide sections, tool profile, model role and outputs
    phase_of(stage)                  the phase an old stage name (log, story, rough, fine, finish, review) belongs to
    done(phase, project, request)    {'phase', 'done', 'missing': [plain words], 'newest': mtime or None}
    progress(project, request)       {phase id: done(...)} in ORDER
    current(project, request)        the first AI phase whose outputs don't check out yet, or None

| Phase | Stages (its sub-steps) | Who |
|---|---|---|
| prepare | (none: the project, footage facts and the Look, made by code) | code |
| plan_rough | log, story, rough | AI, the planning model |
| fine_finish | fine, finish | AI, the planning model for the fine cut, the lighter one for finishing |
| review_export | review (code checks, the critic, the final render) | code, then the critic |

A phase is done when its outputs check out in code (`done`), never on the AI's free-text mark. The old stage names stay
as its sub-steps: the AI still writes `stage:<name>:done` for each, so the journal, the progress feed and run_cost keep
reading them, but no boundary waits on them. The skills, guide sections and conditional rules a phase attaches are the
union of today's lists for its stages (stage_start.STAGE_SKILLS, GUIDES), so no stage loses what it reads now. Step
P6d scopes them by route (ROUTE_SCOPED, behind stage_start's own switch `new_video_route_skills`, on by default); the
skills' references/ files are attached by route either way (stage_start.REFERENCES).

The switch: settings.json `new_video_phases` (default true; LETITEDIT_NEW_VIDEO_PHASES, 1 or 0, wins). Off, nothing
here is used: the six stages run exactly as before. A run with lean stage hand-offs (T290/T294) keeps its own path:
the phase path is taken only with lean off (new_video_stages.phases_on).
"""
import json
import os
import re
from pathlib import Path

from letitedit.timeline import project_journal

SETTING = 'new_video_phases'
ENV = 'LETITEDIT_NEW_VIDEO_PHASES'

ORDER = ('prepare', 'plan_rough', 'fine_finish', 'review_export')
PHASES = {
    'prepare': {
        'number': 0, 'title': 'prepare', 'who': 'code', 'stages': (), 'skills': (), 'guides': (),
        'tools': None, 'model_role': None, 'step_roles': {},
        'outputs': ('the project file',),
    },
    'plan_rough': {
        'number': 1, 'title': 'plan and rough cut', 'who': 'ai', 'stages': ('log', 'story', 'rough'),
        'skills': ('letitedit-log', 'letitedit-story', 'letitedit-rough'),
        'guides': ('edits', 'items', 'effects'),
        'tools': 'plan', 'model_role': 'plan', 'step_roles': {'log': 'plan', 'story': 'plan', 'rough': 'plan'},
        'outputs': ('brief.json', 'log.json and selects.json (unless the Look has no footage)',
                    'story_plan.json and pickups.md', 'the rough cut on the main video track',
                    'a watched rough export (render:<file path>)'),
    },
    'fine_finish': {
        'number': 2, 'title': 'fine cut and finish', 'who': 'ai', 'stages': ('fine', 'finish'),
        'skills': ('letitedit-fine', 'letitedit-captions', 'letitedit-sound', 'letitedit-finish', 'letitedit-graphics'),
        'guides': ('edits', 'items', 'effects', 'code'),
        'tools': 'finish', 'model_role': 'plan', 'step_roles': {'fine': 'plan', 'finish': 'routine'},
        'outputs': ('fine_pass.md', 'finish_pass.md', 'captions on the timeline when the request asks for them',
                    'music on a Music track when the request asks for it'),
    },
    'review_export': {
        'number': 3, 'title': 'review and export', 'who': 'code+ai', 'stages': ('review',),
        'skills': ('letitedit-gate', 'letitedit-review', 'letitedit-fine', 'letitedit-captions', 'letitedit-sound'),
        'guides': ('edits', 'items', 'effects'),
        'tools': 'review', 'model_role': 'plan', 'step_roles': {'review': 'plan'},
        'outputs': ('a review of the current cut that is ready, or the last allowed round',),
    },
}
# Route-scoped skill lists (T319 rule 2's phase table; T331 P6d). Used only with stage_start's route switch on
# (settings.json `new_video_route_skills`, on by default); off, a phase attaches PHASES[...]['skills'] as above.
# `core` is always attached, each `routed` skill when one of its routes applies (stage_start.routes); the router,
# craft, modes and firstcut stay on top (stage_start.BASE_SKILLS) and stage_start.ROUTE_SKILLS adds shorts, b-roll,
# learned-look and the rest by route. A skill a fix needs and that isn't attached is read with the Skill tool, in full,
# in one step (the router's "How to read").
ROUTE_SCOPED = {
    'plan_rough': {'core': ('letitedit-log', 'letitedit-story', 'letitedit-rough'), 'routed': {}},
    'fine_finish': {'core': ('letitedit-fine', 'letitedit-captions', 'letitedit-sound', 'letitedit-finish'),
                    'routed': {'letitedit-graphics': ('graphics:yes',)}},
    'review_export': {'core': ('letitedit-gate', 'letitedit-review'),
                      'routed': {'letitedit-captions': ('captions:on',),
                                 'letitedit-sound': ('music:any', 'song')}},
}
AI_PHASES = tuple(name for name in ORDER if PHASES[name]['who'] != 'code')
NEXT = dict(zip(ORDER[:-1], ORDER[1:]))
STAGE_PHASE = {stage: name for name in ORDER for stage in PHASES[name]['stages']}

# Music the request asks to be in the export (the router's `Music:` field; `trending`, `none`, `auto` and an absent
# field ask for none: an automatic choice may be no music).
MUSIC_IN_EXPORT = ('library', 'own', 'made', 'ai', 'written', 'backdrop')
# A music track by name, as letitedit.sound.music.MUSIC_NAME reads it (sound sits above app; a test keeps them equal);
# a song added when posting (letitedit.sound.guide_song) is not in the mix and doesn't count.
MUSIC_NAME = re.compile(r'music|song|score|bed', re.I)
GUIDE_SONG = re.compile(r'^\s*song \(not in the export\)', re.I)
NO_CAPTIONS = ('none', 'off', 'no', 'no captions', 'false')


def enabled():
    """Whether New video runs in phases on this install (the switch above; on by default)."""
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


def phase_of(stage):
    """The phase id an old stage name belongs to; a phase id is returned as it is; anything else is an error."""
    if stage in PHASES:
        return stage
    if stage in STAGE_PHASE:
        return STAGE_PHASE[stage]
    raise ValueError(f'Unknown New video stage or phase: {stage}')


def _field(request, name):
    match = re.search(r'^' + re.escape(name) + r':[ \t]*(.+)$', request or '', re.I | re.M)
    return match.group(1).strip().lower() if match else None


def _brief(work):
    try:
        value = json.loads((work / 'brief.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def wants_captions(request='', brief=None):
    """True when the person's request or brief asks for spoken captions (a `Captions & pace:` preset other than none,
    or a brief `captions` field that is on). Otherwise the captions skill decides, and nothing is required here."""
    value = (brief or {}).get('captions')
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip():
        return value.strip().lower() not in NO_CAPTIONS
    line = _field(request, 'Captions & pace')
    return bool(line) and line not in NO_CAPTIONS + ('auto',)


def wants_music(request='', brief=None):
    """True when the request (or the brief's copy of its Music field) puts music in the export."""
    value = _field(request, 'Music') or str((brief or {}).get('music') or '').strip().lower() or None
    return bool(value) and value.split()[0] in MUSIC_IN_EXPORT


def _clips(track):
    return [item for item in track.get('items', []) if isinstance(item, dict) and 'gap' not in item]


def _main_clips(script):
    for track in (script or {}).get('tracks', []):
        if track.get('kind') == 'video':
            return _clips(track)
    return []


def _has_captions(script):
    return any(isinstance(cap.get('cues'), list) and cap['cues'] for cap in (script or {}).get('captions', []) or [])


def _has_music(script):
    return any(track.get('kind') == 'audio' and MUSIC_NAME.search(str(track.get('name') or '')) and
               not GUIDE_SONG.match(str(track.get('name') or '')) and _clips(track)
               for track in (script or {}).get('tracks', []))


def read_script(project, live=True):
    """The project's edit script: the open window's non-saving snapshot when the project is open, else the saved file;
    None when there is no project file yet."""
    project = Path(project)
    if live:
        try:
            from letitedit.app import letitedit_instances, live_edit
            for row in letitedit_instances.list_instances():
                if row.get('project') and Path(row['project']).resolve() == project.resolve():
                    source, _ = live_edit.snapshot(row['instance_id'])
                    from letitedit.timeline import edit_script
                    return edit_script.read(source)
        except Exception:  # noqa: BLE001 - no window to ask: the saved file is the state
            pass
    if not project.is_file():
        return None
    from letitedit.timeline import edit_script
    try:
        return edit_script.read(project)
    except Exception:  # noqa: BLE001 - an unreadable project has no checked outputs
        return None


def _mtime(*paths):
    times = []
    for path in paths:
        try:
            times.append(Path(path).stat().st_mtime)
        except OSError:
            continue
    return max(times) if times else None


def _output(project, work, name):
    """The path of a stage output that checks out (project_journal's content rules), or None."""
    if not project_journal.has_stage_output(project, name):
        return None
    return next((path for path in (project.parent / name, work / name) if path.is_file()), None)


def _rough_render(project):
    """The newest watched rough export the journal names that exists (render:<file path>), or None."""
    found = []
    for entry in project_journal.entries(project, None):
        text = str(entry.get('text') or '')
        if entry.get('kind') == 'note' and text.startswith('render:'):
            path = Path(text.split(':', 1)[1].strip())
            if path.is_file() and path.stat().st_size:
                found.append(path)
    return max(found, key=lambda path: path.stat().st_mtime) if found else None


def _reviews(folder):
    return list(folder.glob('* review/review_bundle.json')) + list(folder.glob('*/* review/review_bundle.json'))


def done(phase, project, request='', script=None, live=True):
    """Whether a phase's outputs check out, from the files alone (no journal mark needed). missing names each output
    still missing or failing, in plain words; newest is the newest output's modification time (a boundary's identity).
    script: the edit script to judge (the caller's live one); otherwise read_script(project, live)."""
    phase = phase_of(phase)
    project = Path(project)
    work = project_journal.folder(project)
    missing, outputs = [], []
    index = ORDER.index(phase)
    if index > 1:                                   # the earlier AI phases still hold
        prior = done(ORDER[index - 1], project, request, script=script, live=live)
        if not prior['done']:
            missing.append(f"the {PHASES[ORDER[index - 1]]['title']} phase")
            missing.extend(prior['missing'])
    if phase == 'prepare':
        if not project.is_file():
            missing.append('the project file')
        return {'phase': phase, 'done': not missing, 'missing': missing, 'newest': _mtime(project)}
    if not project.is_file():
        missing.append('the project file')
    if script is None and project.is_file():
        script = read_script(project, live=live)
    brief = _brief(work) if work.is_dir() else None
    if brief is None and (project.parent / 'brief.json').is_file():
        brief = _brief(project.parent)
    if phase == 'plan_rough':
        names = ['brief.json']
        if not project_journal.nothing_to_log(project):
            names += ['log.json', 'selects.json']
        names += ['story_plan.json', 'pickups.md']
        for name in names:
            path = _output(project, work, name)
            if path is None:
                missing.append(project_journal.OUTPUT_HINTS.get(name, name))
            else:
                outputs.append(path)
        if project.is_file() and not _main_clips(script):
            missing.append('the rough cut on the main video track')
        render = _rough_render(project) if project.is_file() else None
        if render is None:
            missing.append('a watched rough export (render:<file path>)')
        else:
            outputs.append(render)
    elif phase == 'fine_finish':
        for name in ('fine_pass.md', 'finish_pass.md'):
            path = _output(project, work, name)
            if path is None:
                missing.append(name)
            else:
                outputs.append(path)
        if project.is_file():
            if not _main_clips(script):
                missing.append('the cut on the main video track')
            if wants_captions(request, brief) and not _has_captions(script):
                missing.append('captions on the timeline (the request asks for them)')
            if wants_music(request, brief) and not _has_music(script):
                missing.append('music on a Music track (the request asks for it)')
            outputs.append(project)
    elif phase == 'review_export':
        cut = _mtime(project)
        ready = []
        for bundle in _reviews(project.parent):
            try:
                if cut is not None and bundle.stat().st_mtime < cut:
                    continue                        # a review of an earlier cut
                data = json.loads(bundle.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and (data.get('verdict') == 'ready' or (data.get('rounds') or {}).get('final')):
                ready.append(bundle)
        if ready:
            outputs.extend(ready)
        else:
            missing.append('a review of the current cut that is ready, or the last allowed round')
    return {'phase': phase, 'done': not missing, 'missing': missing, 'newest': _mtime(*outputs)}


def progress(project, request='', script=None, live=True):
    """{phase id: done(...)} for every phase, in ORDER, reading the project once."""
    project = Path(project)
    if script is None and project.is_file():
        script = read_script(project, live=live)
    return {name: done(name, project, request, script=script, live=live) for name in ORDER}


def current(project, request='', script=None, live=True):
    """The first AI phase whose outputs don't check out yet, or None when the review is done."""
    states = progress(project, request, script=script, live=live)
    return next((name for name in AI_PHASES if not states[name]['done']), None)


def first_step(phase, project):
    """The sub-step a phase's work starts at: its first stage whose outputs aren't there yet (today's stage gate,
    project_journal.stage_progress, without its journal marks)."""
    phase = phase_of(phase)
    stages = PHASES[phase]['stages']
    if not stages:
        return None
    project = Path(project)
    for stage in stages:
        if stage == 'log' and project_journal.nothing_to_log(project):
            continue
        names = project_journal.STAGE_FILES.get(stage, ())
        if any(not project_journal.has_stage_output(project, name) for name in names):
            return stage
        if stage == 'rough' and (not project.is_file() or _rough_render(project) is None):
            return stage
    return stages[-1]
