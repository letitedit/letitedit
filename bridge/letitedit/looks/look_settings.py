"""Versioned Look defaults and lossless, read-only style-pack conversion.

Values are preferences, never edit constraints. The legacy payload is retained
verbatim as JSON data, including fields not understood by the converter.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

import yaml

FORMAT = 'letitedit-look-settings/1'
PACK_FORMATS = ('letitedit-style/2', 'shotcut-ai-style/2', 'letitedit-style/3')
PATH_KEYS = frozenset(('path', 'file', 'image', 'sound', 'video', 'intro', 'outro', 'theme',
                       'recipe', 'preview', 'template', 'logo', 'font_file'))


def _local_names(key):
    import letitedit.core.hardware as hardware
    value = hardware.settings().get(key) or []
    value = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return tuple(name.strip() for name in value if isinstance(name, str) and name.strip())


def hidden_packs():
    """The private packs no longer offered for new videos (older versions): the settings' private_packs_hidden."""
    return _local_names('private_packs_hidden')


def private_packs():
    """The style packs this PC keeps to its owner: their Looks are never shared and never in the public catalogue or an
    installer. A PC names them in its own settings.local.json (private_packs, and private_packs_hidden), which is never
    committed or shipped; a PC without the lists has none."""
    return tuple(dict.fromkeys(_local_names('private_packs') + hidden_packs()))


def private_ids():
    """The Look ids of private_packs()."""
    return {'mine-' + name for name in private_packs()}


def merge(base, changes):
    """Deep merge with explicit nulls preserved, and no aliasing of either input."""
    result = copy.deepcopy(base)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def neutral(identity='neutral'):
    from letitedit.looks.style_pack import DEFAULTS
    return {'format': FORMAT, 'id': identity, 'defaults_are': 'taste', 'share': False,
            'values': copy.deepcopy(DEFAULTS), 'asset_root': '.', 'files': {},
            'links': {'recipe': None, 'preview': None}, 'legacy': None}


def validate(settings):
    if not isinstance(settings, dict) or settings.get('format') != FORMAT:
        raise ValueError('unsupported Look settings format')
    if not isinstance(settings.get('id'), str) or not settings['id']:
        raise ValueError('Look settings need an id')
    if not isinstance(settings.get('values'), dict):
        raise ValueError('Look values must be an object')
    if not isinstance(settings.get('share'), bool):
        raise ValueError('Look share must explicitly be true or false')
    if not isinstance(settings.get('asset_root', '.'), str):
        raise ValueError('Look asset_root must be a path')
    if not isinstance(settings.get('files', {}), dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in settings.get('files', {}).items()):
        raise ValueError('Look files must map references to paths')
    if not isinstance(settings.get('links', {}), dict):
        raise ValueError('Look links must be an object')
    if is_private(settings) and settings['share']:
        raise ValueError('private pack Looks cannot be shared')
    json.dumps(settings, allow_nan=False)
    return settings


def is_private(settings):
    legacy = settings.get('legacy')
    if legacy is not None and not isinstance(legacy, dict):
        raise ValueError('Look legacy metadata must be an object or null')
    legacy = legacy or {}
    return (settings.get('private') is True or legacy.get('pack') in private_packs()
            or settings.get('id') in private_ids())


def from_pack(data, identity, *, source=None, asset_root='.', private=False, pack=None):
    """Convert v1/v2/v3 data, keeping the exact original alongside resolved values."""
    from letitedit.looks import style_pack
    if not isinstance(data, dict):
        raise ValueError('a pack must be an object')
    raw = copy.deepcopy(data)
    pack_format = data.get('format')
    is_v1 = (pack_format in ('letitedit-style/1', 'shotcut-ai-style/1')
             or (pack_format is None and (data.get('schema') == 1
                 or (source is not None and Path(source).suffix.lower() == '.json'))))
    if is_v1:
        if data.get('schema') not in (None, 1):
            raise ValueError(f'unsupported pack schema {data.get("schema")!r}')
        version = pack_format or 'letitedit-style/1'
        prepared = copy.deepcopy(raw)
        nulls = []
        for section, fields in (('captions', ('weight', 'outline')), ('title', ('weight', 'outline')),
                                ('sfx', ('gain_db',))):
            for field in fields:
                if isinstance(prepared.get(section), dict) and field in prepared[section] and prepared[section][field] is None:
                    del prepared[section][field]
                    nulls.append((section, field))
        if isinstance(prepared.get('assets'), dict):
            prepared['assets'] = {key: value for key, value in prepared['assets'].items() if isinstance(value, dict)}
        converted = style_pack.from_v1(prepared)
        for section, field in nulls:
            if field == 'gain_db':
                converted['sfx']['gain_db'] = None
            elif field == 'outline':
                target = 'text' if section == 'title' else 'captions'
                converted[target]['outline'] = None
            else:
                target = 'heading' if section == 'title' else 'captions'
                converted.setdefault('fonts', {}).setdefault(target, {})['weight'] = None
    elif pack_format in PACK_FORMATS or (pack_format is None and data.get('schema') is None):
        converted = raw
        version = pack_format or style_pack.FORMAT
    else:
        raise ValueError(f'unsupported pack format {pack_format!r}')
    settings = neutral(identity)
    settings.update(values=merge(settings['values'], converted), asset_root=str(asset_root),
                    legacy={'format': version, 'source': source, 'pack': pack, 'data': raw})
    settings['links'] = {key: copy.deepcopy(converted.get(key)) for key in ('recipe', 'preview')}
    if private or pack in private_packs():
        settings.update(private=True, share=False)
    return validate(settings)


def pack_file(folder):
    folder = Path(folder)
    if folder.is_file():
        return folder
    if (folder / 'style.yaml').is_file():
        return folder / 'style.yaml'
    versions = sorted(folder.glob('v[0-9][0-9][0-9].json'))
    if versions:
        return versions[-1]
    raise FileNotFoundError(f'no style.yaml or vNNN.json in {folder}')


def read_pack(folder, identity, *, asset_root='.', private=False):
    source = pack_file(folder)
    text = source.read_text(encoding='utf-8-sig')
    raw = json.loads(text) if source.suffix.lower() == '.json' else yaml.safe_load(text)
    if raw is None:
        raw = {}
    settings = from_pack(raw, identity, source=source.name, asset_root=asset_root,
                         private=private, pack=source.parent.name)
    if settings['links']['recipe'] is None and (source.parent / 'recipe.md').is_file():
        settings['links']['recipe'] = 'recipe.md'
    return settings


def to_pack(settings):
    """The exact original data, not a lossy reverse conversion of resolved defaults."""
    validate(settings)
    if not isinstance(settings.get('legacy'), dict) or 'data' not in settings['legacy']:
        raise ValueError('this Look was not converted from a pack')
    return copy.deepcopy(settings['legacy']['data'])


def read(path):
    settings = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    validate(settings)
    settings['values'] = merge(neutral()['values'], settings['values'])
    return settings


def path_reference(value):
    if not isinstance(value, str) or not value or '\n' in value:
        return False
    if PureWindowsPath(value).is_absolute():
        return True
    if urlsplit(value).scheme or value.startswith(('#', 'emoji:', 'sfx:', 'anim:')):
        return False
    return '/' in value or '\\' in value or bool(Path(value).suffix)


def references(settings):
    """File references understood by packs, without rewriting unknown data or URLs."""
    found = set()

    def visit(value, key=None, in_map=False):
        if isinstance(value, dict):
            for child, item in value.items():
                if child not in ('provenance', 'evidence', 'references', 'derived_by', 'measured'):
                    visit(item, child, in_map or child in ('map', 'assets', 'templates', 'brand'))
        elif isinstance(value, list):
            for item in value:
                visit(item, key, in_map)
        elif (in_map or key in PATH_KEYS) and path_reference(value):
            found.add(value)

    visit(settings.get('values', {}))
    visit(settings.get('links', {}))
    visit((settings.get('legacy') or {}).get('data', {}))
    return sorted(found)


def resolve_path(value, root):
    if PureWindowsPath(value).is_absolute() and not Path(value).is_absolute():
        return value
    return str((Path(root) / value.replace('\\', '/')).resolve())


def resolved(settings, directory):
    """Resolve paths relative to settings.json; missing files are facts, not edits."""
    settings = copy.deepcopy(validate(settings))
    settings['values'] = merge(neutral()['values'], settings['values'])
    asset_root = resolve_path(settings.get('asset_root', '.'), directory)
    settings['asset_root'] = asset_root
    files = settings.get('files', {})
    settings['references'] = {
        reference: resolve_path(files[reference], directory) if reference in files else resolve_path(reference, asset_root)
        for reference in references(settings)}
    settings['missing_assets'] = [reference for reference, path in settings['references'].items()
                                  if not Path(path).is_file()]
    settings['resolved_links'] = {
        key: settings['references'].get(value, value) if isinstance(value, str) else value
        for key, value in settings.get('links', {}).items()}
    return settings
