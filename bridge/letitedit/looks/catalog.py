"""The catalogue's sources: the one place that knows where New video's Styles, Looks and Themes, and the style packs, come from.

Read on every call, nothing kept, so an edited file or a newly learned Look shows at once:

- `LocalSource(looks_root)`: what ships with the install, in `looks\\`: `manifest.json` (picker settings, Styles,
  folders, Looks), `styles.json` (the Styles, layout 2) and `themes.json` (the Themes). Owner review writes back to
  the same three files (`path(kind)`).
- `PersonalSource()`: the person's own Looks learned from their videos, and the Theme a Look learned, in My Looks
  (`learned_looks` reads that folder), with the Style they are listed under (`style`).
- `style_packs(style_root)`: the style packs in `style-packs\\`, a separate catalogue (`style_pack` loads them).

`looks.catalog()` and `look_choices.catalog()` build New video's lists from these, and every other module asks `looks`
(`catalog`, `read`, `offered`). A source serving the catalogue from letitedit.app would be a third class with
`LocalSource`'s methods.
"""
from __future__ import annotations

import json
from pathlib import Path

FILES = {'style': 'styles.json', 'look': 'manifest.json', 'theme': 'themes.json'}   # owner review's kinds and files


def read_json(path, default):
    """A JSON file's data, or `default` when the file isn't there (any other error is raised)."""
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return default


class LocalSource:
    """The catalogue that ships with the install: the files in `looks\\`."""

    def __init__(self, looks_root):
        self.root = Path(looks_root)

    def path(self, kind):
        """The file that holds one kind of entry ('style' | 'look' | 'theme')."""
        return self.root / FILES[kind]

    def manifest(self, empty):
        """`manifest.json`'s data, or `empty` when there is none."""
        p = self.path('look')
        return json.loads(p.read_text(encoding='utf-8-sig')) if p.is_file() else empty

    def has_styles(self):
        """Whether the Styles have their own file (catalog layout 2)."""
        return self.path('style').is_file()

    def styles(self, default):
        return read_json(self.path('style'), default)

    def themes(self):
        return read_json(self.path('theme'), [])


class PersonalSource:
    """The person's own Looks and Themes, learned from their videos (My Looks)."""

    def read(self):
        """{root, looks, themes, problems}: every saved Look as a manifest entry, the Themes they learned, and the
        records that couldn't be read."""
        import letitedit.looks.learned_looks as learned_looks
        return learned_looks.catalog()

    @property
    def style(self):
        """The Style the person's Looks are listed under ("Your Looks")."""
        from letitedit.looks.learned_looks import STYLE
        return STYLE


def merged(looks_root, empty):
    """The shipped manifest with the person's Looks after its own (a learned Look never takes a shipped Look's id) and
    their Themes and unreadable records beside it (`_personal_themes`, `_personal_problems`)."""
    data = LocalSource(looks_root).manifest(empty)
    personal = PersonalSource().read()
    occupied = {entry.get('id') for entry in data.get('looks', [])}
    data['looks'] = data.get('looks', []) + [entry for entry in personal['looks'] if entry['id'] not in occupied]
    from letitedit.looks import learned_looks, look_migration
    data['looks'] += look_migration.legacy_entries(learned_looks.root())
    data['_personal_themes'] = personal['themes']
    data['_personal_styles'] = personal.get('styles', [])
    data['_personal_problems'] = personal['problems']
    return data


def style_packs(style_root):
    """Names of the style packs under `style_root` (v2/v3 folders with a style.yaml, and v1 folders of vNNN.json)."""
    root = Path(style_root)
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and ((p / 'style.yaml').exists() or any(p.glob('v[0-9][0-9][0-9].json'))))


def resolve(identity=None, *, looks_root=None, personal_root=None, public=False):
    """One read-only settings resolver for shipped, learned and copied Looks.

    Old recipe-only Looks get neutral values without writing a settings file.
    Public resolution never reads personal folders or private Looks. Approval and
    content-fit remain the existing picker's responsibility, not defaults policy.
    """
    from letitedit.looks import learned_looks, look_settings
    if identity is None or identity == 'neutral':
        return look_settings.resolved(look_settings.neutral(), Path.cwd())
    if not isinstance(identity, str) or not identity or any(char in identity for char in '/\\:') or identity in ('.', '..'):
        raise ValueError('a Look id, not a path, is required')
    if looks_root is None:
        from letitedit.core.paths import install_root
        looks_root = Path(install_root()) / 'looks'
    local = LocalSource(looks_root)
    entry = next((item for item in local.manifest({'looks': []}).get('looks', [])
                  if item.get('id') == identity), None)
    directory = None
    personal_recipe = None
    if entry is not None:
        if entry.get('personal') or entry.get('private') or identity in look_settings.private_packs():
            raise ValueError('personal Looks do not belong in the public manifest')
        settings_path = entry.get('settings')
        directory = Path(looks_root)
        settings_path = directory / settings_path if settings_path else directory / identity / 'settings.json'
    elif not public:
        if not identity.startswith('mine-'):
            raise FileNotFoundError(f'Look {identity!r} not found')
        learned_looks._identity(identity)
        directory = (Path(personal_root) if personal_root is not None else learned_looks.root()) / identity
        pointer = read_json(directory / 'look.json', {})
        if pointer.get('id') != identity or pointer.get('format') != learned_looks.FORMAT:
            from letitedit.looks import look_migration
            legacy = look_migration.legacy_settings(identity)
            if legacy is not None:
                return legacy
            directory = (Path(personal_root) if personal_root is not None else learned_looks.root()).parent / 'Custom Looks' / identity
            pointer = read_json(directory / 'look.json', {})
            if not identity.startswith('mine-custom-') or pointer.get('id') != identity or pointer.get('format') != learned_looks.FORMAT:
                raise FileNotFoundError(f'Look {identity!r} not found')
        revision = pointer.get('revision')
        import re
        if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{32}', revision):
            raise ValueError('invalid personal Look revision')
        entry = pointer
        directory = directory / 'revisions' / revision
        personal_recipe = directory / 'recipe.md'
        settings_path = directory / 'settings.json'
        if not settings_path.is_file() and (directory.parent.parent / 'settings.json').is_file():
            settings_path = directory.parent.parent / 'settings.json'
    else:
        raise FileNotFoundError(f'public Look {identity!r} not found')
    if settings_path.is_file():
        settings = look_settings.read(settings_path)
        if settings['id'] != identity:
            raise ValueError('Look id does not match settings')
        directory = settings_path.parent
    else:
        if entry.get('settings'):
            raise FileNotFoundError(settings_path)
        settings = look_settings.neutral(identity)
        settings['links'] = {key: entry.get(key) for key in ('recipe', 'preview')}
        if entry.get('personal') or identity.startswith('mine-'):
            settings['links']['recipe'] = 'recipe.md'
    if entry.get('share') is False:
        settings['share'] = False
    if entry.get('private'):
        settings.update(private=True, share=False)
    if public and look_settings.is_private(settings):
        raise ValueError('private Look is not public')
    resolved = look_settings.resolved(settings, directory)
    if personal_recipe is not None and personal_recipe.is_file():
        resolved['resolved_links']['recipe'] = str(personal_recipe)
    return resolved
