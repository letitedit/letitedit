"""New video's lean stage hand-offs: the editor's seed (T294; the bridge side is T290's letitedit/app/stage_handoff.py).

The editor runs this once a lean run's working project and brief exist, before its first stage can finish. It resolves
the run's inputs from the person's own choices, never from the AI's: the footage the request names (each video file's
exact frame rate from ffprobe), the Look or style pack the request names (its resolved settings and recipe files), the
review round limit from the existing review policy (review_memory.round_limit on the brief), and the extra skills the
format and the Look need. Then it seeds the run through new_video_carry's `stage_begin`, the editor's internal carry
protocol. Not a tool and not part of the tools' contract.

    python new_video_lean.py < {"folder", "since", "run_id", "request", "ai": {engine, model, effort}, "project"?}
      {"decision": "waiting"}                                       no working project with a brief yet: ask again later
      {"decision": "stage_ready", "run_id", "project", "source_ids"} seeded (an identical retry is safe)
      {"decision": "refused", "reason"}                             the run goes on in one conversation, as before

Source ids are each video file's name (its full path when two files share a name): the request's lean line tells the AI
so, and the next stage reads them from the run's sources file.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import letitedit.core.quiet_subprocess  # noqa: E402,F401  (no console windows)
from letitedit.core import paths  # noqa: E402

VIDEO = {'.mp4', '.mov', '.mkv', '.webm', '.m4v', '.avi', '.mts', '.m2ts', '.mxf', '.wmv', '.3gp'}
SKIP = {'cache', 'checks', 'review', 'made', 'source-check', 'takes', 'poster-still'}
STAGES = ('story', 'rough', 'fine', 'finish', 'review')


def _brief(project):
    try:
        data = json.loads((project.with_suffix('.letitedit') / 'brief.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None                      # not written yet, or still being written
    return data if isinstance(data, dict) else None


def working_project(folder, since, project=None):
    """The run's project: the one the window has open when it is in the folder, else the newest project in the folder
    whose side folder has a brief, made or changed since the run began. None until one exists."""
    folder = Path(folder).resolve()
    given = Path(project).resolve() if project else None
    candidates = ([given] if given else []) + sorted(folder.glob('*.mlt'), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            path = path.resolve()
            if path.parent != folder or not path.is_file() or _brief(path) is None:
                continue
            brief = path.with_suffix('.letitedit') / 'brief.json'
            if path != given and max(path.stat().st_mtime, brief.stat().st_mtime) < since:
                continue
            return path
        except OSError:
            continue
    return None


def footage(request):
    """The video files the request names: its files, or the video files in its folder (two levels, side folders
    skipped). [] for a video with no footage; None when the request names neither."""
    first = (request or '').split('\n', 1)[0]
    if first.startswith('Make a first cut with no footage'):
        return []
    files = re.match(r'Make a first cut from these files: (.+?) \(use the ', first)
    if files:
        return [Path(p.strip()) for p in files.group(1).split('; ') if Path(p.strip()).suffix.lower() in VIDEO]
    folder = re.match(r'Make a first cut from the folder (.+?) \(use the ', first)
    if not folder:
        return None
    root = Path(folder.group(1).strip())
    found = []
    level = [root]
    for _ in range(2):
        below = []
        for directory in level:
            try:
                entries = sorted(directory.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.is_dir():
                    if not entry.name.endswith('.letitedit') and entry.name.lower() not in SKIP:
                        below.append(entry)
                elif entry.suffix.lower() in VIDEO:
                    found.append(entry)
        level = below
    return found


def _probe():
    exe = paths.CODE_ROOT / 'app' / 'ffprobe.exe'
    return str(exe) if exe.is_file() else shutil.which('ffprobe')


def frame_rate(path, probe):
    """(num, den) of a video file's frame rate, exact, reduced."""
    out = subprocess.run([probe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=r_frame_rate,avg_frame_rate', '-of', 'json', str(path)],
                         capture_output=True, text=True, timeout=60)
    streams = json.loads(out.stdout or '{}').get('streams') or [{}]
    for key in ('r_frame_rate', 'avg_frame_rate'):
        num, _, den = str(streams[0].get(key) or '0/0').partition('/')
        try:
            num, den = int(num), int(den or 1)
        except ValueError:
            continue
        if num > 0 and den > 0:
            rate = Fraction(num, den)
            return rate.numerator, rate.denominator
    raise ValueError(f'no frame rate for {path}')


def sources(request, probe=None):
    files = footage(request)
    if files is None:
        raise ValueError('the request names no footage letitedit can resolve')
    files = [Path(p).resolve() for p in files]
    names = [p.name for p in files]
    unique = len(set(n.lower() for n in names)) == len(names)
    probe = probe or _probe()
    if files and not probe:
        raise ValueError('ffprobe is missing')
    out = []
    for path in files:
        num, den = frame_rate(path, probe)
        out.append({'id': path.name if unique else str(path), 'path': str(path), 'fps_num': num, 'fps_den': den})
    return out


def look(request):
    """(look, extra skills): the Look or style pack the request names, resolved."""
    named = re.search(r'^look: (\S+)\s*$', request or '', re.M)
    style = re.search(r'^style: (\S+)\s*$', request or '', re.M)
    if named and named.group(1) not in ('auto', 'freestyle', 'none'):
        from letitedit.looks import catalog, look_library, looks
        ident = looks.current_id(named.group(1))
        # a library Look's own values only, never neutral defaults its recipe may rule out (T332)
        settings = json.loads(json.dumps(look_library.own(catalog.resolve(ident)), default=str))
        recipe = None
        try:
            recipe = looks.read(ident).get('recipe')
        except (KeyError, OSError, ValueError):
            pass
        recipe = recipe or (settings.get('resolved_links') or {}).get('recipe')
        artifacts = []
        extra = []
        if recipe and Path(recipe).is_file():
            folder = Path(recipe).resolve().parent
            artifacts.append(str(Path(recipe).resolve()))
            if (folder / 'settings.json').is_file() and settings.get('values_are') != 'own':
                artifacts.append(str(folder / 'settings.json'))   # a library Look's own values are in `settings`
            from letitedit.looks.look_check import MEASUREMENTS
            measured = [str(folder / name) for name in MEASUREMENTS if (folder / name).is_file()]
            artifacts += measured
            if measured:
                extra.append('letitedit-learned-look')
        return {'id': ident, 'settings': settings, 'artifacts': artifacts}, extra
    if named:
        return {'id': named.group(1), 'settings': {}, 'artifacts': []}, []
    if style and style.group(1) != 'none':
        pack = style.group(1)
        root = Path(os.environ.get('LETITEDIT_STYLES') or paths.CODE_ROOT / 'style-packs') / pack
        files = [str((root / name).resolve()) for name in ('style.yaml', 'recipe.md', 'letitedit.json')
                 if (root / name).is_file()]
        return {'id': pack, 'settings': {'style_pack': pack}, 'artifacts': files}, []
    return {'id': 'none', 'settings': {}, 'artifacts': []}, []


def seed(request, probe=None):
    """The editor's request -> new_video_carry's stage_begin decision, or waiting / refused."""
    project = working_project(request['folder'], float(request.get('since') or 0), request.get('project'))
    if project is None:
        return {'decision': 'waiting'}
    try:
        from letitedit.review import review_memory
        text = request['request']
        found = sources(text, probe)
        chosen, extra = look(text)
        short = 'a vertical short' in text.split('\n', 1)[0] or 'What to make: both' in text \
            or 'What to make: a vertical short' in text
        extra = (['letitedit-shorts'] if short else []) + extra
        skills = {stage: list(extra) for stage in STAGES} if extra else {}
        from letitedit.app import new_video_carry
        decision = new_video_carry.dispatch({
            'action': 'stage_begin', 'project': str(project), 'run_id': request['run_id'], 'request': text,
            'ai': request['ai'], 'sources': found, 'look': chosen,
            'review_limit': review_memory.round_limit(_brief(project)), 'skills': skills})
    except Exception as error:  # noqa: BLE001 - any failure keeps the run in one conversation, with the reason
        return {'decision': 'refused', 'reason': f'{type(error).__name__}: {error}'}
    if decision.get('decision') != 'stage_ready':
        return {'decision': 'refused', 'reason': decision.get('reason') or 'the run could not be seeded'}
    return {'decision': 'stage_ready', 'run_id': decision['run_id'], 'project': str(project),
            'source_ids': [s['id'] for s in found]}


if __name__ == '__main__':
    try:
        print(json.dumps(seed(json.load(sys.stdin))))
    except Exception as error:  # noqa: BLE001
        print(json.dumps({'decision': 'refused', 'reason': f'{type(error).__name__}: {error}'}))
