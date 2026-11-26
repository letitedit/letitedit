"""Which project did a New video run make? The window asks when a run ends and nothing has been opened.

An assigned output folder is authoritative: only valid timelines newly saved directly in that folder count, using this
run's footage when supplied. A no-footage request needs no footage match there. No edit journal is required in this case.

Without an assigned folder, a project counts only if its own side folder's journal has an edit made during this run AND
it uses this run's footage. Names are never compared. The legacy search checks the footage folder, its parent (where a
first cut goes by default), and the projects the progress feed lists, which can be anywhere.

The footage test matters because neither other fact is about this run alone. The feed is one file for the whole PC, so
any session's tool calls land in the running job's list, and a journal only says that someone edited a project at that
time. (T59: a test window with a mocked run opened another agent's project, edited at the same moment.) With no footage
known, nothing fits and the person is asked, unless the Look draws everything (T78): then the fact about this run alone is the
record of what the person gave it, kept beside the project during this run (look_inputs, inputs.json).

    python first_cut_result.py --json '{"source": <folder or file>, "since": <epoch seconds>, "request_id": <id>, "output": <optional assigned folder>}'
prints {"project": <path or null>, "candidates": [paths, newest edit first], "already_open": <window id or null>, "why": ...}
project is set only when exactly one project fits: one saved/edited in this run, or among several, the only one whose brief
was written in this run."""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import argparse
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import letitedit.timeline.project_journal as journal
import letitedit.app.progress_feed as progress_feed


def _when(text):
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00')).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None


def _side_folder(project):
    """The side folder if it is there; looking must not make one or move one."""
    side = project.with_name(project.stem + '.letitedit')
    return side if side.is_dir() else None


def _edited_at(project, since):
    """When this run last edited the project, from its journal; None if it didn't."""
    side = _side_folder(project)
    if side is None or not (side / 'journal.jsonl').is_file():
        return None
    last = None
    for line in (side / 'journal.jsonl').read_text(encoding='utf-8-sig', errors='replace').splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        at = _when(entry.get('time'))
        if entry.get('kind') == 'apply' and at is not None and at >= since:
            last = max(last or at, at)
    return last


def _same_path(path):
    return os.path.normcase(os.path.realpath(path))


def _uses_footage(project, source):
    """Does this project play a file from the run's footage (the folder it was given, or that file)?"""
    if not source:
        return False
    path = Path(source)
    folder = _same_path(path if path.is_dir() else path.parent)
    try:
        root = ET.parse(project).getroot()
    except (OSError, ET.ParseError):
        return False
    base = root.get('root') or str(project.parent)

    def here(text):
        where = Path(text.split('?')[0])
        if not where.is_absolute():
            where = Path(base) / where
        return os.path.dirname(_same_path(where)) == folder

    for prop in root.iter('property'):
        text = (prop.text or '').strip()
        if not text:
            continue
        if prop.get('name') in ('resource', 'warp_resource') and here(text):
            return True
        # A clip with a fix or a cut-out plays a made copy from the cache; its recipe names the footage it came from.
        if text.startswith('{') and '"clip"' in text:
            try:
                if any(here(clip) for clip in _clips_in(json.loads(text))):
                    return True
            except ValueError:
                pass
    return False


def _clips_in(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            if key == 'clip' and isinstance(inner, str):
                yield inner
            else:
                yield from _clips_in(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _clips_in(inner)


def _given_this_run(project, since):
    """A run with no footage: the project holds the record of the person's boxes, kept during this run, for a no-footage Look."""
    import letitedit.looks.look_inputs as look_inputs
    record = look_inputs.record_path(project)
    return record.is_file() and record.stat().st_mtime >= since and look_inputs.no_footage(project)


def _brief_this_run(project, since):
    side = _side_folder(project)
    brief = side / 'brief.json' if side else None
    return bool(brief and brief.is_file() and brief.stat().st_mtime >= since)


def _looked_at(source, request_id):
    """Project files worth asking about: in the footage folder and above it, and those this run's tools named."""
    found = []
    if source:
        path = Path(source)
        folder = path if path.is_dir() else path.parent
        for place in (folder, folder.parent):
            if place.is_dir():
                found += sorted(place.glob('*.mlt'))
    run = progress_feed._find(request_id, request_id) if request_id else {}   # the run's own record (T193)
    if run:
        found += [Path(p) for p in run.get('projects') or []]
    unique = {}
    for path in found:
        if path.is_file() and path.suffix.lower() == '.mlt':
            unique.setdefault(str(path.resolve()).casefold(), path.resolve())
    return list(unique.values())


def _open_elsewhere(project):
    """A window that already holds this project (the AI opened it another way)."""
    try:
        import letitedit.app.letitedit_instances as inst
        for row in inst.list_instances():
            if row.get('project') and Path(row['project']).resolve() == project:
                return row['instance_id']
    except Exception:  # noqa: BLE001 - no answer from the windows is no reason to withhold the video
        pass
    return None


def find(source, since, request_id=None, output=None):
    assigned = Path(output).resolve() if output else None
    placed = list(assigned.glob('*.mlt')) if assigned and assigned.is_dir() else []
    edited = [(at, p.resolve()) for p in placed
              if (at := p.stat().st_mtime) >= since
              and _valid_project(p) and (not source or _uses_footage(p, source))]
    if assigned is None:
        edited = [(at, p) for p in _looked_at(source, request_id)
                  if (at := _edited_at(p, since)) is not None
                  and (_uses_footage(p, source) if source else _given_this_run(p, since))]
    edited.sort(key=lambda row: -row[0])
    candidates = [p for _, p in edited]
    project, why = None, "no project using this run's footage was edited during this run"
    if len(candidates) == 1:
        project, why = candidates[0], 'the only project edited during this run'
    elif candidates:
        briefed = [p for p in candidates if _brief_this_run(p, since)]
        if len(briefed) == 1:
            project, why = briefed[0], 'the only project among several whose brief was written during this run'
        else:
            why = f'{len(candidates)} projects were edited during this run and nothing tells them apart'
    return {'project': str(project) if project else None, 'candidates': [str(p) for p in candidates],
            'already_open': _open_elsewhere(project) if project else None, 'why': why}


def _valid_project(project):
    try:
        root = ET.parse(project).getroot()
        return root.tag == 'mlt' and root.find('tractor') is not None
    except (OSError, ET.ParseError):
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', required=True)
    options = json.loads(parser.parse_args().json)
    print(json.dumps(find(options.get('source') or '', float(options.get('since') or 0), options.get('request_id'), options.get('output'))),
          flush=True)
