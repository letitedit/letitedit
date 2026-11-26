"""Check a job.json without running it (contract/CONTRACT.md section 3, 'validate').

No letitedit imports: what this install offers comes in as `knowledge` (the real service builds it from capabilities;
the reference fake passes its own), so the fake and letitedit check jobs the same way.

knowledge: {
    'kinds': {kind: bool available},          missing kind -> available
    'looks': set of Look ids or None,         None: not checked
    'platforms': set of platform ids or None,
    'layouts': set of stills layout ids or None,
    'ai_available': list of engines or None,
    'install_root': path or None,              an output folder inside it is refused
    'find_job': callable(ref) -> job folder (Path) or None,
    'too_long': callable(path) -> the person's message when this PC can't use so long a path, else None,
}
"""
from __future__ import annotations

import json
import re
import tempfile
import os
from pathlib import Path

import letitedit.studio.contract_schemas as contract
import letitedit.studio.files as files

LANES = {'urgent': 'urgent', 'normal': 'normal', 'dev': 'dev', 'channel_urgent': 'urgent', 'channel': 'normal'}
OWN_FILES = {'job.json', 'cancel', 'status.json', 'events.jsonl', 'result.json', files.LOCK_NAME, files.FAKE_MARK,
             files.SIDE_MARK}
UNCLAIMED_OK = {'job.json', 'cancel', files.LOCK_NAME, files.SIDE_MARK}
FINAL_CHANGES = ('tier', 'rules', 'platforms', 'deliver', 'notes_for_final')   # what a final from a preview changes
FINAL_KEEPS = ('idea', 'sources', 'look_id')     # refused there, as in 1.0; any other input: input_ignored (1.1)
CONTINUES = {     # kind -> the kinds of job its from_job may be
    'short': {'short'},
    'revise': {'short', 'revise', 'retext', 'batch_item', 'still'},
    'retext': {'short', 'revise', 'retext', 'still', 'batch_item'},
    'hooks': {'short', 'revise', 'retext', 'batch_item'},
    'conform': {'short', 'revise', 'retext', 'batch_item', 'still'},
}


def _problem(field, code, message):
    return {'field': field, 'code': code, 'message': message}


def lane(job):
    return LANES.get(str(job.get('priority') or 'normal'), 'normal')


def load(ref):
    """(job dict or None, job.json path or None, problem or None) for a job folder or a job.json path."""
    p = Path(ref)
    path = p / 'job.json' if p.is_dir() else p
    try:
        return json.loads(path.read_text(encoding='utf-8-sig')), path, None
    except FileNotFoundError:
        return None, path, _problem('(file)', 'invalid_job', f'There is no job.json at {path}.')
    except (OSError, ValueError) as e:
        return None, path, _problem('(file)', 'invalid_job', f'job.json could not be read as JSON: {e}')


def _norm(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(str(path))))


def _inside(child, parent):
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p.rstrip('\\/') + os.sep)


FOLDER_KEYS = {'find_in', 'folders', 'folder'}
FILE_KEYS = {'path', 'file', 'files', 'video', 'references', 'pictures', 'reference', 'picture', 'music_file'}
_ABSOLUTE = re.compile(r'^(?:[A-Za-z]:[\\/]|[\\/]{2})')


def source_paths(job):
    """(field, path, 'file'|'folder'|'any') for every path the job reads: every string under a path field (path, file,
    folder, find_in, video, references, pictures ...) and every absolute path anywhere under inputs, at any depth
    (per-idea sources and find_in, music, references). Shapes the schema refuses are walked too, never raised on."""
    out = []

    def walk(value, field, key):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, f'{field}.{k}', k if isinstance(k, str) else None)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f'{field}.{i}', key)
        elif isinstance(value, str) and value:
            kind = 'folder' if key in FOLDER_KEYS else 'file' if key in FILE_KEYS else None
            if kind or _ABSOLUTE.match(value):
                out.append((field, value, kind or 'any'))
    walk(job.get('inputs'), 'inputs', None)
    return out


def _unknown_fields(job):
    """Fields this version's schema doesn't name (x_ fields are the caller's own and never named)."""
    out = [k for k in job if k not in contract.job_properties() and not k.startswith('x_')]
    kind = job.get('kind')
    known = contract.inputs_properties(kind)
    if known and isinstance(job.get('inputs'), dict):
        out += [f'inputs.{k}' for k in job['inputs'] if k not in known]
    return out


# How far below its folder each kind of job writes, in characters (measured on past jobs, with room to spare): a drawn
# scene's files for the kinds that draw them, a changed project's history for a retext, the job's own files for the rest.
FOLDER_DEPTH = {'short': 150, 'batch_shorts': 150, 'revise': 150, 'retext': 100}
OTHER_DEPTH = 60


def output_dir_problem(job, job_dir, knowledge):
    """None, or the problem that refuses this job folder."""
    if job_dir is None:
        return None
    d = Path(job_dir)
    if not d.is_absolute():
        return _problem('output_dir', 'output_dir_refused', f'The job folder must be an absolute path: {job_dir}')
    too_long = knowledge.get('too_long')
    kind = job.get('kind')
    depth = FOLDER_DEPTH.get(kind, OTHER_DEPTH) if isinstance(kind, str) else OTHER_DEPTH
    said = too_long(os.path.join(str(d), 'x' * depth)) if too_long else None
    if said:
        return _problem('output_dir', 'output_dir_refused', said)
    for field, path, kind in source_paths(job):
        if not Path(path).is_absolute():
            continue                                   # refused by the source checks; nothing to compare
        folder = path if kind == 'folder' or Path(path).is_dir() else os.path.dirname(path)
        if folder and _inside(d, folder):
            return _problem('output_dir', 'output_dir_refused',
                            f'The job folder {d} is inside a folder the job reads ({folder}, {field}). letitedit '
                            'never writes into a source folder: choose a folder elsewhere.')
    root = knowledge.get('install_root')
    if root and _inside(d, root):
        return _problem('output_dir', 'output_dir_refused', f"The job folder {d} is inside letitedit's install ({root}).")
    fake_side = knowledge.get('side') == 'fake'
    taken = files.side_of(d) if d.is_dir() else None
    if taken is not None and taken != (knowledge.get('side') or 'letitedit'):
        return _problem('output_dir', 'output_dir_refused',
                        f'The job folder {d} was taken by {"the reference fake" if taken == "fake" else "letitedit" if taken == "letitedit" else "another program"}; '
                        'a job folder belongs to one side only. Use a new folder.')
    owner = files.owner_of(d) if taken is not None else None
    home = knowledge.get('home')
    if owner and home and owner.get('home') and owner['home'] != files.home_key(home):
        return _problem('output_dir', 'output_dir_refused',
                        f'The job folder {d} was taken by {files.taken_by(d)}; a job folder belongs to one Studio '
                        'folder only. Use a new folder.')
    if owner and owner.get('job_id') and owner['job_id'] != job.get('job_id'):
        return _problem('output_dir', 'output_dir_refused',
                        f'The job folder {d} was taken for another job ({owner["job_id"]}). Use a new folder.')
    if not fake_side and files.is_fake_folder(d):
        return _problem('output_dir', 'output_dir_refused',
                        f'The job folder {d} was made by the Studio\'s reference fake; the real letitedit never '
                        'takes one over. Use a new folder.')
    if fake_side and (d / 'status.json').is_file() and not files.is_fake_folder(d):
        return _problem('output_dir', 'output_dir_refused',
                        f"The job folder {d} belongs to letitedit's real Studio; the reference fake never takes "
                        'one over. Use a new folder.')
    if d.is_dir():
        status = files.read_json(d / 'status.json') or {}
        if status and status.get('job_id') != job.get('job_id'):
            return _problem('output_dir', 'output_dir_refused',
                            f'The job folder {d} belongs to another job ({status.get("job_id")}).')
        owns = knowledge.get('owns')
        if not (owns and owns(job.get('job_id'), d)):
            # Not this Studio's folder for this job yet: it may hold only job.json, a cancel file (the job then ends
            # cancelled at its claim, contract 1.1) and the caller's own x_ files.
            stray = sorted(p.name for p in d.iterdir()
                           if p.name not in UNCLAIMED_OK and not p.name.startswith('x_'))
            if stray:
                return _problem('output_dir', 'output_dir_refused',
                                f'The job folder {d} already holds files that are not this job\'s: '
                                f'{", ".join(stray[:5])}. Use an empty folder.')
        try:
            with tempfile.TemporaryFile(dir=d, prefix='.studio-probe-'):
                pass
        except OSError as e:
            return _problem('output_dir', 'output_dir_refused', f'letitedit cannot write in the job folder {d}: {e}')
    else:
        parent = next((a for a in d.parents if a.is_dir()), None)
        if parent is None or not os.access(parent, os.W_OK):
            return _problem('output_dir', 'output_dir_refused', f'letitedit cannot make the job folder {d}.')
    return None


def _check_from_job(job, knowledge, problems, warnings=None):
    ref = job.get('from_job')
    kind = job.get('kind')
    if not ref:
        if kind == 'short' and (job.get('inputs') or {}).get('tier') == 'final':
            needed = [k for k in ('idea', 'sources', 'look_id', 'platforms') if k not in (job.get('inputs') or {})]
            if needed:
                problems.append(_problem('inputs', 'invalid_job', 'A final without from_job needs '
                                         + ', '.join(needed) + '.'))
        return
    finder = knowledge.get('find_job')
    folder = finder(ref) if finder else None
    if folder is None and Path(str(ref)).is_dir():
        folder = Path(ref)
    if folder is None:
        problems.append(_problem('from_job', 'from_job_unusable', f'No earlier job {ref} on this PC.'))
        return
    result = files.read_json(Path(folder) / 'result.json') or {}
    if result.get('state') != 'done':
        problems.append(_problem('from_job', 'from_job_unusable',
                                 f'The earlier job {ref} has not finished ({result.get("state") or "still running"}).'))
        return
    was = 'batch_item' if '.' in str(result.get('job_id', '')) and result.get('kind') == 'short' and \
        (Path(folder).parent.name == 'items') else result.get('kind')
    allowed = CONTINUES.get(kind)
    if allowed is not None and was not in allowed and result.get('kind') not in allowed:
        problems.append(_problem('from_job', 'from_job_unusable',
                                 f'A {kind} job can\'t continue a {result.get("kind")} job.'))
    if kind == 'short' and result.get('kind') == 'short':
        inp = job.get('inputs') or {}
        if result.get('tier') != 'preview':
            problems.append(_problem('from_job', 'from_job_unusable', 'A final continues a preview; this one is a '
                                     f'{result.get("tier")}.'))
        changed = [k for k in FINAL_KEEPS if k in inp]
        if changed:
            problems.append(_problem('inputs', 'from_job_unusable',
                                     f'A final from a preview keeps its {", ".join(changed)}: changing them needs a new '
                                     'preview.'))
        known = contract.inputs_properties('short')
        for k in inp:
            if k in FINAL_CHANGES or k in FINAL_KEEPS or k not in known:
                continue                               # applied; refused above; or unknown (field_ignored)
            if warnings is not None:
                warnings.append({'code': 'input_ignored', 'field': f'inputs.{k}',
                                 'message': f'A final from a preview changes only {", ".join(FINAL_CHANGES)}; its '
                                            f'{k} is the preview\'s, so inputs.{k} is kept and not applied. Music and '
                                            'caption changes go in notes_for_final.'})
    if kind == 'revise' and result.get('kind') == 'still' and 'tier' in (job.get('inputs') or {}):
        problems.append(_problem('inputs.tier', 'invalid_job', 'A still has no tier: leave tier out of a still\'s '
                                 'revise.'))


def _check_known(job, knowledge, problems):
    inp = job.get('inputs') or {}
    looks = knowledge.get('looks')
    look_ids = [('inputs.look_id', inp.get('look_id'))]
    look_ids += [(f'inputs.ideas.{i}.look_id', (idea or {}).get('look_id')) for i, idea in enumerate(inp.get('ideas') or [])]
    if looks is not None:
        for field, look in look_ids:
            if look and look != 'auto' and look not in looks:
                problems.append(_problem(field, 'look_unknown', f'No Look "{look}" on this install.'))
    plats = knowledge.get('platforms')
    if plats is not None:
        for i, p in enumerate(inp.get('platforms') or []):
            pid = p.get('id') if isinstance(p, dict) else p
            if pid not in plats:
                problems.append(_problem(f'inputs.platforms.{i}', 'platform_unknown',
                                         f'No platform preset "{pid}" on this install.'))
        for field, item in overlay_items(job):
            for j, pid in enumerate(item.get('platforms') or []):
                if pid not in plats:
                    problems.append(_problem(f'{field}.platforms.{j}', 'platform_unknown',
                                             f'No platform preset "{pid}" on this install.'))
    layouts = knowledge.get('layouts')
    if layouts is not None and job.get('kind') == 'still' and inp.get('layout') not in layouts:
        problems.append(_problem('inputs.layout', 'layout_unknown', f'No stills layout "{inp.get("layout")}".'))
    engines = knowledge.get('ai_available')
    engine = (job.get('ai') or {}).get('engine')
    if engines is not None and engine and engine not in engines:
        problems.append(_problem('ai.engine', 'ai_unavailable',
                                 f'{engine} is not installed or signed in on this PC; letitedit never switches to '
                                 'another AI by itself.'))


def overlay_items(job):
    """(field, item) for every overlay_text item of a job: the top level's, then each idea's (batch_shorts)."""
    inp = job.get('inputs') if isinstance(job.get('inputs'), dict) else {}
    out = [(f'inputs.overlay_text.{i}', it) for i, it in enumerate(inp.get('overlay_text') or [])
           if isinstance(it, dict)]
    for n, idea in enumerate(inp.get('ideas') or []):
        if isinstance(idea, dict):
            out += [(f'inputs.ideas.{n}.overlay_text.{i}', it) for i, it in enumerate(idea.get('overlay_text') or [])
                    if isinstance(it, dict)]
    return out


def _check_sources(job, problems):
    for field, path, kind in source_paths(job):
        p = Path(path)
        if not p.is_absolute():
            problems.append(_problem(field, 'invalid_job', f'Not an absolute path: {path}'))
        elif kind == 'folder' and not p.is_dir():
            problems.append(_problem(field, 'source_missing', f'The folder {path} is not there (moved, renamed or '
                                     'on a drive that is not connected).'))
        elif kind == 'file' and not p.is_file():
            problems.append(_problem(field, 'source_missing', f'The file {path} is not there (moved, renamed or on '
                                     'a drive that is not connected).'))
        elif kind == 'any' and not p.exists():
            problems.append(_problem(field, 'source_missing', f'{path} is not there (moved, renamed or on a drive '
                                     'that is not connected).'))
        elif p.is_file() and not os.access(p, os.R_OK):
            problems.append(_problem(field, 'source_unreadable', f'The file {path} cannot be read.'))
        elif p.is_dir():
            try:
                with os.scandir(p) as entries:
                    next(entries, None)
            except OSError:
                problems.append(_problem(field, 'source_unreadable', f'The folder {path} cannot be read.'))


def validate(ref=None, knowledge=None, job=None, job_dir=None):
    """Check a job without running it. ref: a job folder or a job.json path (or pass job=dict and job_dir).
    Returns {'valid', 'problems': [{field, code, message}], 'warnings': [{code, message, field}], 'job_id', 'kind',
    'lane', 'job_dir'}."""
    knowledge = knowledge or {}
    problems, warnings = [], []
    path = None
    if job is None:
        job, path, problem = load(ref)
        if problem:
            too_long = knowledge.get('too_long')
            said = too_long(path) if too_long and path is not None else None
            if said:                    # job.json may well be there, under a path Windows can't open
                problem = _problem('output_dir', 'output_dir_refused', said)
            return {'valid': False, 'problems': [problem], 'warnings': [], 'job_id': None, 'kind': None,
                    'lane': None, 'job_dir': None}
    if not isinstance(job, dict):
        return {'valid': False, 'problems': [_problem('(top)', 'invalid_job', 'job.json must hold an object.')],
                'warnings': [], 'job_id': None, 'kind': None, 'lane': None, 'job_dir': None}
    version = str(job.get('contract_version') or '')
    major = version.split('.')[0]
    if job.get('output_dir') is not None and not isinstance(job.get('output_dir'), str):
        return {'valid': False, 'problems': [_problem('output_dir', 'invalid_job', 'output_dir must be a path.')],
                'warnings': [], 'job_id': None, 'kind': None, 'lane': None, 'job_dir': None}
    if job_dir is None:
        if job.get('output_dir'):
            job_dir = Path(job['output_dir'])
        elif path is not None:
            job_dir = path.parent
    out = {'job_id': job.get('job_id'), 'kind': job.get('kind'), 'lane': lane(job),
           'job_dir': str(job_dir) if job_dir is not None else None}
    if major.isdigit() and int(major) != contract.MAJOR:
        problems.append(_problem('contract_version', 'unsupported_version',
                                 f'This letitedit reads contract major {contract.MAJOR}; the job is {version}.'))
        return {'valid': False, 'problems': problems, 'warnings': warnings, **out}
    for p in contract.problems(job, 'job'):
        problems.append(_problem(p['field'], 'invalid_job', p['message']))
    try:                                               # a malformed job is refused, never an internal error
        for field in _unknown_fields(job):
            warnings.append({'code': 'field_ignored', 'field': field,
                             'message': f'{field} is not part of contract {contract.CONTRACT_VERSION}; it is kept and '
                                        'ignored.'})
        kind = job.get('kind')
        if kind is not None and not isinstance(kind, str):
            if not any(p['field'] == 'kind' for p in problems):
                problems.append(_problem('kind', 'invalid_job', 'kind must be the name of a kind of job.'))
        else:
            avail = (knowledge.get('kinds') or {}).get(kind)
            if kind and avail is False:
                problems.append(_problem('kind', 'kind_not_installed', f'The kind "{kind}" is not available on this '
                                         'install yet (see capabilities).'))
        if path is not None and job.get('output_dir') and _norm(job['output_dir']) != _norm(path.parent):
            problems.append(_problem('output_dir', 'output_dir_refused', f'job.json is in {path.parent} but names the '
                                     f'job folder {job["output_dir"]}: write it into its own job folder.'))
        refused = output_dir_problem(job, job_dir, knowledge)
        if refused:
            problems.append(refused)
    except (TypeError, AttributeError, KeyError, ValueError, IndexError) as e:
        problems.append(_problem('(top)', 'invalid_job', f'A field has a shape letitedit cannot read: {e}'))
        return {'valid': False, 'problems': problems, 'warnings': warnings, **out}
    shaped = not problems or all(p['code'] != 'invalid_job' for p in problems)
    for check in (_check_sources, lambda j, ps: _check_known(j, knowledge, ps),
                  lambda j, ps: _check_from_job(j, knowledge, ps, warnings)):
        if not shaped:
            break                                      # a malformed job: the schema's problems are the answer
        try:
            check(job, problems)
        except (TypeError, AttributeError, KeyError, ValueError, IndexError) as e:
            problems.append(_problem('inputs', 'invalid_job', f'A field has a shape letitedit cannot read: {e}'))
            break
    return {'valid': not problems, 'problems': problems, 'warnings': warnings, **out}


def first_code(report):
    """The error code a refused job reports: the most specific problem's."""
    codes = [p['code'] for p in report.get('problems') or []]
    for code in ('unsupported_version', 'output_dir_refused', 'job_id_conflict', 'kind_not_installed',
                 'source_missing', 'source_unreadable', 'from_job_unusable', 'look_unknown', 'platform_unknown',
                 'layout_unknown', 'ai_unavailable'):
        if code in codes:
            return code
    return codes[0] if codes else 'invalid_job'
