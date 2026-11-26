"""Opt-in, provider-neutral stage state. No tool registration or conversation-log inference.

The editor seeds begin_run once and supplies live state on each carry check. A prepared
transition is acknowledged only after the fresh session has actually been created.
"""
import contextlib
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from letitedit.timeline import project_journal

FORMAT = 'letitedit-stage-handoff/1'
RUN_FORMAT = 'letitedit-stage-run/1'
MIN_BYTES, MAX_BYTES = 2048, 5120
NEXT = dict(zip(('log', 'story', 'rough', 'fine', 'finish'),
                ('story', 'rough', 'fine', 'finish', 'review')))
BASE_SKILLS = ('letitedit', 'letitedit-craft', 'letitedit-firstcut')
STAGE_SKILLS = {
    'story': ('letitedit-modes', 'letitedit-story'),
    'rough': ('letitedit-modes', 'letitedit-rough'),
    'fine': ('letitedit-fine', 'letitedit-captions', 'letitedit-sound'),
    'finish': ('letitedit-finish', 'letitedit-sound', 'letitedit-captions'),
    'review': ('letitedit-gate', 'letitedit-review', 'letitedit-fine',
               'letitedit-captions', 'letitedit-sound'),
}
STAGE_ARTIFACTS = {
    'story': ('brief.json', 'log.json', 'selects.json'),
    'rough': ('brief.json', 'story_plan.json', 'selects.json', 'pickups.md'),
    'fine': ('brief.json', 'story_plan.json', 'selects.json'),
    'finish': ('brief.json', 'story_plan.json', 'fine_pass.md'),
    'review': ('brief.json', 'story_plan.json', 'fine_pass.md', 'finish_pass.md'),
}


class InvalidHandoff(ValueError):
    """Keep the current session; repair evidence rather than guess a restart."""


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reference(path):
    path = Path(path).resolve(strict=True)
    return {'path': str(path), 'sha256': digest(path)}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def checked(ref):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'} or not Path(ref['path']).is_absolute():
        raise InvalidHandoff('An artifact needs an absolute path and SHA-256.')
    if digest(ref['path']) != ref['sha256']:
        raise InvalidHandoff(f"Changed artifact: {ref['path']}")
    return Path(ref['path'])


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _atomic(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def transition_lock(work):
    lock = Path(work) / '.stage-transition-lock'
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise InvalidHandoff('A stage transition is busy or interrupted; repair its lock before retrying.') from error
    try:
        yield
    finally:
        lock.rmdir()


def _skills(names):
    if not isinstance(names, list) or any(not isinstance(name, str) or
            not re.fullmatch(r'letitedit(?:-[a-z0-9-]+)?', name) for name in names):
        raise InvalidHandoff('Skills must be explicit letitedit skill names, not excerpts.')
    return names


def begin_run(project, run_id, request, ai, sources, look, review_limit, skills=None):
    """Seed immutable inputs before starting a run; an identical retry is safe.

    sources: [{id, path, fps_num, fps_den}], empty for a no-footage video.
    look: {id, settings, artifacts: [absolute recipe/settings paths]}.
    skills: extra required skill names per destination stage (mode, Shorts, layers, etc.).
    review_limit: the existing review policy's resolved limit; this layer never chooses one.
    """
    project = Path(project).resolve(strict=True)
    work = project_journal.folder(project)
    work.mkdir(parents=True, exist_ok=True)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise InvalidHandoff('A run needs a stable, filesystem-safe id.')
    if not request or set(ai) != {'engine', 'model', 'effort'} or ai['engine'] not in ('claude', 'codex') or \
            any(not isinstance(value, str) or not value.strip() for value in ai.values()):
        raise InvalidHandoff('Keep the original request and resolved engine/model/effort.')
    if type(review_limit) is not int or review_limit < 1:
        raise InvalidHandoff('Carry the resolved review limit from the existing review policy.')
    if not isinstance(sources, list) or any(not isinstance(source, dict) or
            not {'id', 'path', 'fps_num', 'fps_den'} <= source.keys() or not source['id'] or
            not Path(source['path']).is_absolute() or
            any(type(source[key]) is not int or source[key] <= 0 for key in ('fps_num', 'fps_den'))
            for source in sources) or len({source['id'] for source in sources}) != len(sources):
        raise InvalidHandoff('Source ids, absolute paths and exact positive fps are required.')
    if not isinstance(look, dict) or not {'id', 'settings', 'artifacts'} <= look.keys() or \
            not isinstance(look['settings'], dict):
        raise InvalidHandoff('A resolved Look identity, settings and recipe paths are required.')
    skills = skills or {}
    if set(skills) - STAGE_SKILLS.keys():
        raise InvalidHandoff('Unknown skill stage.')
    for names in skills.values():
        _skills(names)
    look = dict(look, artifacts=[reference(path) for path in look['artifacts']])
    values = {'request': request, 'original_brief': read_json(work / 'brief.json'),
              'sources': sources, 'look': look, 'skills': skills}
    with transition_lock(work):
        memory = work / 'review_memory.json'
        if (work / 'stage-run.json').exists() and not memory.exists():
            raise InvalidHandoff('Review memory went missing; repair it rather than resetting rounds.')
        root = work / 'stage-runs' / run_id
        if root.exists():
            config = read_json(root / 'run.json')
            if config['ai'] != ai or config['project'] != str(project) or config['review_limit'] != review_limit or any(
                    read_json(checked(config['inputs'][key])) != value for key, value in values.items()):
                raise InvalidHandoff('A run id cannot be reused for changed inputs.')
        else:
            root.mkdir(parents=True)
            inputs = {}
            for name, value in values.items():
                path = root / (name + '.json')
                _atomic(path, _json_bytes(value))
                inputs[name] = reference(path)
            config = {'format': RUN_FORMAT, 'run_id': run_id, 'started_at': time.time(),
                      'project': str(project), 'ai': ai, 'inputs': inputs, 'review_limit': review_limit}
            _atomic(root / 'run.json', _json_bytes(config))
        if not memory.exists():
            _atomic(memory, _json_bytes({'rounds': [], 'items': []}))
        _atomic(work / 'stage-run.json', _json_bytes(config))
    return config


def latest_boundary(work, run_id):
    events = Path(work) / 'stage-boundaries.jsonl'
    rows = [json.loads(line) for line in events.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    matches = [row for row in rows if row.get('run_id') == run_id]
    if not matches:
        raise InvalidHandoff('No durable stage boundary for this run.')
    event = matches[-1]
    if not isinstance(event.get('id'), str) or not re.fullmatch(r'[0-9a-f]{32}', event['id']) or \
            event.get('stage') not in NEXT or not isinstance(event.get('recorded_at'), (int, float)) or \
            not isinstance(event.get('revision'), str) or not re.fullmatch(r'[0-9a-f]{64}', event['revision']):
        raise InvalidHandoff('Invalid durable boundary event.')
    return event


def _editorial(path, source_ids):
    data = read_json(path)
    if not isinstance(data, dict) or set(data) != {'decisions', 'unresolved', 'pending_jobs', 'next_step',
                                                'skills', 'artifacts'}:
        raise InvalidHandoff('The lean handover needs decisions, unresolved, pending_jobs, next_step, skills, artifacts.')
    for key in ('decisions', 'unresolved', 'pending_jobs', 'artifacts'):
        if not isinstance(data[key], list):
            raise InvalidHandoff(f'{key} must be a list.')
    _skills(data['skills'])
    if not isinstance(data['next_step'], str) or not data['next_step'].strip():
        raise InvalidHandoff('Name the exact next editorial step.')
    ids = set()
    for decision in data['decisions']:
        if not isinstance(decision, dict) or not {'id', 'why', 'ranges'} <= decision.keys() or \
                not isinstance(decision['id'], str) or not decision['id'] or decision['id'] in ids or \
                not isinstance(decision['why'], str) or not decision['why'].strip() or \
                not isinstance(decision['ranges'], list):
            raise InvalidHandoff('Each decision needs a unique id, reason and source ranges.')
        ids.add(decision['id'])
        for span in decision['ranges']:
            if not isinstance(span, dict) or span.get('source_id') not in source_ids or \
                    any(type(span.get(key)) is not int for key in ('in', 'out')) or not 0 <= span['in'] < span['out']:
                raise InvalidHandoff('Decision ranges are source-frame [in, out) with known source ids.')
    finding_ids = []
    for finding in data['unresolved']:
        if not isinstance(finding, dict) or not isinstance(finding.get('id'), str) or not finding['id'] or \
                not isinstance(finding.get('what'), str) or not finding['what'].strip():
            raise InvalidHandoff('Findings need stable ids and descriptions; retain resolved history explicitly.')
        finding_ids.append(finding['id'])
    if len(set(finding_ids)) != len(finding_ids):
        raise InvalidHandoff('Finding ids must be unique.')
    return data


def _carry_forward(previous, editorial, rounds):
    if not previous:
        return
    prior = read_json(checked(previous))
    before = read_json(checked(prior['editorial']))
    for key in ('decisions', 'unresolved'):
        if not {item['id'] for item in before[key]} <= {item['id'] for item in editorial[key]}:
            raise InvalidHandoff(f'Carry forward {key} ids; mark replaced/resolved entries explicitly, never drop them.')
    if rounds['done'] < prior['rounds']['done']:
        raise InvalidHandoff('Completed review rounds cannot decrease at a stage boundary.')


def _rounds(path, limit):
    memory = read_json(path)
    if not isinstance(memory, dict) or not isinstance(memory.get('rounds'), list) or \
            not isinstance(memory.get('items'), list):
        raise InvalidHandoff('Invalid review memory; never reset review rounds.')
    return {'done': len(memory['rounds']), 'limit': limit}


def _config(work):
    config = read_json(Path(work) / 'stage-run.json')
    run_id = config.get('run_id')
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id) or \
            config.get('format') != RUN_FORMAT or config != read_json(Path(work) / 'stage-runs' / run_id / 'run.json'):
        raise InvalidHandoff('The active run must match its immutable seed.')
    return config


def _live(config, live):
    if not isinstance(live, dict) or any(live.get(key) != config[key] for key in ('run_id', 'project', 'ai')):
        raise InvalidHandoff('The editor must attest this run, project and resolved AI.')
    if live.get('pending_jobs') != [] or live.get('revision') != digest(config['project']):
        raise InvalidHandoff('Pending jobs or a changed/live-unsaved timeline: keep the current session.')


def build(work, live):
    """Write once from the latest journal boundary; a retry returns the same checked manifest."""
    work = Path(work)
    config = _config(work)
    _live(config, live)
    event = latest_boundary(work, config['run_id'])
    if event['stage'] not in NEXT or event['revision'] != live['revision']:
        raise InvalidHandoff('Stale boundary; record completion against the current timeline.')
    if (work / 'handover.md').stat().st_mtime < event['recorded_at']:
        raise InvalidHandoff('Missing fresh editorial handover after the boundary.')
    root = work / 'stage-handoffs' / event['id']
    path = root / 'stage-handoff.json'
    if path.exists():
        validate(path, live)
    else:
        inputs = config['inputs']
        for ref in inputs.values():
            checked(ref)
        source_ids = {source['id'] for source in read_json(checked(inputs['sources']))}
        editorial = _editorial(work / 'handover.md', source_ids)
        if editorial['pending_jobs']:
            raise InvalidHandoff('Finish or collect pending jobs before changing sessions.')
        nxt = NEXT[event['stage']]
        artifacts = {name: reference(work / name) for name in STAGE_ARTIFACTS[nxt]}
        for name, filename in enumerate(editorial['artifacts']):
            artifacts[f'extra-{name}'] = reference(filename)
        look = read_json(checked(inputs['look']))
        for ref in look['artifacts']:
            checked(ref)
        names = list(dict.fromkeys(BASE_SKILLS + STAGE_SKILLS[nxt] +
                     tuple(read_json(checked(inputs['skills'])).get(nxt, [])) + tuple(editorial['skills'])))
        memory = reference(work / 'review_memory.json')
        rounds = _rounds(memory['path'], config['review_limit'])
        pointer = work / 'stage-handoff-current.json'
        previous = read_json(pointer) if pointer.exists() else None
        _carry_forward(previous, editorial, rounds)
        root.mkdir(parents=True, exist_ok=True)
        editorial_path = root / 'editorial.json'
        _atomic(editorial_path, (work / 'handover.md').read_bytes())
        artifact_path = root / 'artifacts.json'
        _atomic(artifact_path, _json_bytes(artifacts))
        data = {'format': FORMAT, 'run_id': config['run_id'], 'boundary_id': event['id'],
                'from': event['stage'], 'next': nxt, 'project': {'path': config['project'], 'revision': event['revision']},
                'ai': config['ai'], 'inputs': inputs, 'look_id': look['id'], 'artifacts': reference(artifact_path),
                'constraints': {'artifact': 'brief.json', 'fields': ['deliverables', 'must_keep', 'must_avoid']},
                'editorial': reference(editorial_path), 'last_transaction': event['last_transaction'],
                'previous': previous,
                'pending_jobs': [], 'review_memory': memory, 'rounds': rounds, 'skills': names,
                'authority': 'Original request and brief govern deliverables, must-keep and must-avoid. '
                             'Read required skills in full; review.md remains the final word. '
                             'Do not repeat completed stages or reset review rounds.'}
        payload = _json_bytes(data)
        if len(payload) > MAX_BYTES:
            raise InvalidHandoff('Manifest exceeds 5120 bytes; link large evidence instead of truncating it.')
        _atomic(path, payload + b' ' * max(0, MIN_BYTES - len(payload)))
        _atomic(root / 'receipt.json', _json_bytes(reference(path)))
        validate(path, live)
    _atomic(work / 'stage-handoff-current.json', _json_bytes(reference(path)))
    return path


def validate(path, live):
    """Validate shape, all referenced evidence and live revision before any fresh-session launch."""
    path = Path(path)
    if not MIN_BYTES <= path.stat().st_size <= MAX_BYTES:
        raise InvalidHandoff('Manifest must be 2048–5120 UTF-8 bytes.')
    if checked(read_json(path.parent / 'receipt.json')) != path.resolve():
        raise InvalidHandoff('The immutable manifest receipt points elsewhere.')
    data = read_json(path)
    required = {'format', 'run_id', 'boundary_id', 'from', 'next', 'project', 'ai', 'inputs', 'look_id',
                'artifacts', 'constraints', 'editorial', 'last_transaction', 'pending_jobs', 'review_memory',
                'rounds', 'skills', 'authority', 'previous'}
    if not isinstance(data, dict) or set(data) != required or data['format'] != FORMAT or \
            data['from'] not in NEXT or data['next'] != NEXT[data['from']] or data['pending_jobs'] != []:
        raise InvalidHandoff('Unsupported or inconsistent handoff schema.')
    work = path.parent.parent.parent
    config = _config(work)
    _live(config, live)
    event = latest_boundary(work, config['run_id'])
    if data['run_id'] != config['run_id'] or data['ai'] != config['ai'] or data['inputs'] != config['inputs'] or \
            data['project'] != {'path': config['project'], 'revision': live['revision']} or \
            (data['boundary_id'], data['from'], data['project']['revision'], data['last_transaction']) != \
            (event['id'], event['stage'], event['revision'], event['last_transaction']):
        raise InvalidHandoff('The run, boundary, AI, timeline or transaction changed.')
    if project_journal.last_transaction(config['project']) != data['last_transaction']:
        raise InvalidHandoff('An edit or undo happened after this boundary.')
    artifacts = read_json(checked(data['artifacts']))
    for ref in [*data['inputs'].values(), *artifacts.values(), data['editorial'], data['review_memory']]:
        checked(ref)
    if read_json(artifacts['brief.json']['path']).get('turbo') != \
            read_json(data['inputs']['original_brief']['path']).get('turbo'):
        raise InvalidHandoff('Review policy inputs changed; resolve them before another stage.')
    look = read_json(checked(data['inputs']['look']))
    for ref in look['artifacts']:
        checked(ref)
    if digest(work / 'handover.md') != data['editorial']['sha256']:
        raise InvalidHandoff('Editorial decisions changed after sealing this boundary.')
    editorial = _editorial(checked(data['editorial']),
                           {source['id'] for source in read_json(checked(data['inputs']['sources']))})
    _carry_forward(data['previous'], editorial, data['rounds'])
    skills = list(dict.fromkeys(BASE_SKILLS + STAGE_SKILLS[data['next']] +
                  tuple(read_json(checked(data['inputs']['skills'])).get(data['next'], [])) + tuple(editorial['skills'])))
    if data['skills'] != skills or editorial['pending_jobs'] or data['look_id'] != look['id'] or \
            not set(STAGE_ARTIFACTS[data['next']]) <= artifacts.keys() or \
            data['rounds'] != _rounds(data['review_memory']['path'], config['review_limit']) or \
            data['constraints'] != {'artifact': 'brief.json', 'fields': ['deliverables', 'must_keep', 'must_avoid']}:
        raise InvalidHandoff('Skills, stage evidence or review rounds disagree.')
    return data


def fresh_request(path, live):
    data = validate(path, live)
    files = [data['inputs'][name]['path'] for name in ('request', 'original_brief', 'look')]
    files += [data['editorial']['path'], data['inputs']['sources']['path'], data['review_memory']['path']]
    files += [data['artifacts']['path']]
    text = (f"This run explicitly uses lean stage handoffs.\nsessions: one per stage\n"
            f"Continue only stage {data['next']} of run {data['run_id']}. Completed: {data['from']}.\n"
            f"1. Read {path} in full, then in one batched read these exact evidence files (not the old conversation "
            f"or entire journal): {json.dumps(files, ensure_ascii=False)}. Read the Look's linked recipes/settings "
            "and needed indexed stage evidence. Read brief/story/selects and stage notes in full; consult bulky "
            "word/log evidence by the decision ranges, not a wholesale rescan. Deeper originals remain available.\n"
            f"2. In one batched read load EVERY required skill IN FULL, in this order: {', '.join(data['skills'])}. "
            "Include the lead mode reference and every additional skill the router or a fix needs, in full. "
            "Do not use skill excerpts even if a section-loading switch is on.\n"
            f"3. Work from project {data['project']['path']}; read its exact current timeline only when needed. "
            "No repeated project/source discovery or completed-stage work. Preserve the original request, permissions, "
            "Look/settings, deliverables and decisions. Skills and evidence take precedence over this startup budget. "
            f"Review rounds already done: {data['rounds']['done']}; limit: {data['rounds']['limit']}. "
            "Keep review_memory.json, all review rounds, their fixes, final export and final review unchanged; "
            "review.md is final authority. At the next boundary follow FIRST-1s.\n")
    if len(text.encode('utf-8')) > 4096:
        raise InvalidHandoff('The fresh-session wrapper exceeds 4096 bytes; repair its evidence index.')
    return text


def complete_request(path, live):
    """Expand the checked lean evidence into the same complete startup as a legacy stage."""
    from letitedit.app import new_video_stages
    data = validate(path, live)
    inputs = data['inputs']
    artifacts = read_json(checked(data['artifacts']))
    evidence = [checked(inputs[name]) for name in ('original_brief', 'sources')]
    evidence += [checked(data['editorial']), checked(data['review_memory'])]
    evidence += [checked(ref) for ref in artifacts.values()]
    return new_video_stages.start_request(
        read_json(checked(inputs['request'])), data['next'], data['project']['path'],
        ai=data['ai']['engine'], handover=path, timeline=live.get('timeline'),
        look=live.get('look') or read_json(checked(inputs['look'])), skills=data['skills'], evidence=evidence,
        lean=True, max_bytes=live.get('stage_start_max_bytes', 512_000))


def current(work, live):
    """Read the atomic current pointer, checking its checksum as well as its manifest."""
    return validate(checked(read_json(Path(work) / 'stage-handoff-current.json')), live)


def acknowledge(work, run_id, boundary_id, session_id):
    """Idempotent editor receipt after a session is created, never before launch."""
    work = Path(work)
    with transition_lock(work):
        state = read_json(work / 'stage-transitions.json')
        item = state[boundary_id]
        if item['run_id'] != run_id or not session_id or item.get('session_id', session_id) != session_id:
            raise InvalidHandoff('Transition acknowledgement does not match its session.')
        item.update(state='started', session_id=session_id)
        _atomic(work / 'stage-transitions.json', _json_bytes(state))


def next_transition(work, live):
    """Prepare once, or explicitly retry the same launch token after an interrupted dispatch."""
    work = Path(work)
    with transition_lock(work):
        path = build(work, live)
        data = validate(path, live)
        state_path = work / 'stage-transitions.json'
        state = read_json(state_path) if state_path.exists() else {}
        boundary_id = data['boundary_id']
        prior = state.get(boundary_id)
        if prior and prior['state'] == 'started':
            return None
        if prior and live.get('retry_transition') != boundary_id:
            return {'decision': 'stage_pending', 'transition_id': boundary_id,
                    'reason': 'A launch is prepared; reconcile its session id before retrying.'}
        from letitedit.app import stage_start
        if prior and prior.get('startup'):
            startup = read_json(checked(prior['startup']))
            stage_start.verify(startup)
        else:
            startup = complete_request(path, live)
        startup_path = path.parent / 'stage-start.json'
        if not prior or not prior.get('startup'):
            _atomic(startup_path, _json_bytes(startup))
        state[boundary_id] = {'run_id': data['run_id'], 'state': 'prepared', 'manifest': reference(path),
                              'startup': reference(startup_path)}
        _atomic(state_path, _json_bytes(state))
        return {'decision': 'next_stage', 'transition_id': boundary_id, 'stage_done': data['from'],
                'next': data['next'], 'project': data['project']['path'], 'handover': str(path),
                'request': startup['request'],
                'startup': {key: value for key, value in startup.items() if key != 'request'}}
