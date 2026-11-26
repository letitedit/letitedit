"""Save a Look the person adjusted with New video's "Adjust..." sliders as their own Look, "<Look> (yours)".

The new Look is a personal Look (see learned_looks.py): the base Look's recipe, with the person's settings added as a
section the AI follows. Nothing is copied from reference videos; no evidence file is needed. Saving the same name again
makes a new revision.

    python look_adjust.py save --base <look id> --name "<name>" --settings <json file, or - for stdin>
    prints {"id": ..., "title": ..., "revision": ...} as JSON.

The settings are {"levels": {<slider>: {"title": ..., "label": ..., "meaning": ...}}, "ai": [<slider titles left to the AI>]}.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import uuid
from pathlib import Path

import letitedit.looks.learned_looks as learned_looks
import letitedit.looks.looks as looks


def _slug(name: str) -> str:
    text = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return (text or 'look')[:40]


def _section(settings: dict) -> str:
    """The person's choices in words."""
    lines = ['## Adjusted by the person',
             "These settings are the person's own and come before the choices above where they differ. Anything not "
             'listed stays your call.']
    for name, value in (settings.get('levels') or {}).items():
        if isinstance(value, dict):
            lines.append(f'- {value.get("title", name)}: {value.get("label", "")}'
                         + (f' ({value["meaning"]})' if value.get('meaning') else ''))
        else:
            lines.append(f'- {name}: {value}')
    if settings.get('ai'):
        lines.append('- Left to you: ' + ', '.join(settings['ai']))
    return '\n'.join(lines) + '\n'


def save(base: str, name: str, settings: dict) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise ValueError('name must be nonempty text')
    catalog = looks.catalog()
    found = next((entry for entry in catalog.get('looks', []) if entry['id'] == base), None)
    if found is None:
        raise ValueError(f'no Look called {base!r}')
    recipe_text = Path(found['recipe']).read_text(encoding='utf-8')
    shared = found.get('recipe_shared')
    if shared and Path(shared).is_file():
        recipe_text = recipe_text.rstrip() + '\n\n' + Path(shared).read_text(encoding='utf-8')
    identity = 'mine-' + _slug(name)
    directory = learned_looks.root() / identity
    directory.mkdir(parents=True, exist_ok=True)
    pointer = directory / 'look.json'
    current = json.loads(pointer.read_text(encoding='utf-8-sig')) if pointer.is_file() else None
    revision = uuid.uuid4().hex
    version = directory / 'revisions' / revision
    version.mkdir(parents=True)
    (version / 'recipe.md').write_text(recipe_text.rstrip() + '\n\n' + _section(settings), encoding='utf-8')
    (version / 'settings.json').write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding='utf-8')
    saved = {'format': learned_looks.FORMAT, 'id': identity, 'revision': revision, 'title': name.strip(),
             'line': found.get('line', ''), 'needs': found.get('needs', ''),
             'works_with': found.get('works_with', 'footage'), 'asks': found.get('asks', []),
             'kind': found.get('kind', 'both'), 'based_on': base,
             'themes': found.get('themes') if found.get('themes') in ('kits', 'film') else 'none',
             'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'theme': None}
    temporary = directory / ('look-' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(pointer)
    return {'id': identity, 'title': saved['title'], 'revision': revision, 'replaced': (current or {}).get('revision')}


def main(argv=None):
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('save')
    one.add_argument('--base', required=True)
    one.add_argument('--name', required=True)
    one.add_argument('--settings', default='-')
    args = parser.parse_args(argv)
    raw = sys.stdin.read() if args.settings == '-' else Path(args.settings).read_text(encoding='utf-8-sig')
    print(json.dumps(save(args.base, args.name, json.loads(raw or '{}')), ensure_ascii=False))


if __name__ == '__main__':
    main()
