"""An old managed episode folder opened as a project: its timeline file, found through its episode.json.

Managed episodes are retired; the tools only read one as a project. A path the tools are given as a project may be an
episode folder (layout 1: episode.json at its top; layout 2: episode.json inside the SYSTEM folder in it).

    machine_root(project)   the folder holding episode.json
    load(project)           (that folder, its episode.json); refuses an unknown schema and an episode inside its own
                            source folders or an originals folder (settings.json 'originals_folders')
    owned(root, relative)   root / relative, refusing a path that leaves root
"""
from __future__ import annotations

from pathlib import Path

from letitedit.core import hardware
from letitedit.core.store import inside, read_json

SCHEMA = 1
SYSTEM = "9 System (AI working files - don't edit)"


def originals():
    """The person's originals folders, which no episode may be inside: settings.json 'originals_folders'."""
    value = hardware.settings().get('originals_folders') or []
    return [Path(v) for v in ([value] if isinstance(value, str) else value) if v]


def machine_root(project):
    p = Path(project).resolve()
    if (p / 'episode.json').is_file():
        return p
    if (p / SYSTEM / 'episode.json').is_file():
        return (p / SYSTEM).resolve()
    return p


def load(project):
    p = machine_root(project)
    data = read_json(p / 'episode.json')
    if data.get('schema') != SCHEMA:
        raise ValueError('Unsupported episode schema')
    if any(inside(p, o) for o in originals()) or any(inside(p, s) for s in data['source_roots']):
        raise ValueError('Episode outputs must be outside original/source folders')
    return p, data


def owned(p, relative):
    target = (p / relative).resolve()
    if not inside(target, p) or target == p:
        raise ValueError('Project path escapes episode folder')
    return target
