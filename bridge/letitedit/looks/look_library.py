"""Look defaults, personal copies and revisioned settings in the existing catalog."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from letitedit.looks import catalog, learned_looks, look_migration, look_settings


def kit(identity=None):
    """Resolved drawing and editing preferences, with S01's portable asset paths."""
    from letitedit.looks.style_pack import Kit
    settings = catalog.resolve(identity)
    result = Kit(copy.deepcopy(settings['values']))
    result.root = None if settings['id'] == 'neutral' else Path(settings['asset_root'])
    result.source = 'defaults' if settings['id'] == 'neutral' else settings['id']
    result.references = settings['references']
    neutral = look_settings.neutral()['values']
    authored = (settings.get('legacy') or {}).get('data') or {}
    captions = authored.get('captions') if isinstance(authored.get('captions'), dict) else {}
    appearance = {key: value for key, value in (result.get('captions') or {}).items() if key != 'corrections'}
    default_appearance = {key: value for key, value in neutral['captions'].items() if key != 'corrections'}
    result.caption_preferences = (bool((result.get('app') or {}).get('captions'))
        or appearance != default_appearance
        or (result.get('fonts') or {}).get('captions') != (neutral.get('fonts') or {}).get('captions')
        or any(key in captions for key in ('size', 'fill', 'font', 'outline', 'background', 'geometry', 'position'))
        or 'captions' in (authored.get('fonts') or {}))
    for key, value in settings['resolved_links'].items():
        if value:
            result[key] = value
    return result


def project_identity(script):
    if 'look' in script:
        return script.get('look') or 'neutral'
    if 'letitedit_ai:look' in script:
        return script.get('letitedit_ai:look') or 'neutral'
    return look_migration.legacy_project_look(script)


def project_kit(script):
    identity = project_identity(script)
    try:
        return kit(identity)
    except FileNotFoundError:
        return kit()


OWN_ONLY = ("A library Look's values are only the ones it sets itself; letitedit's neutral defaults fill the rest "
            "in code (action='settings' without an id lists them).")


def _authored(values, shape):
    """`values` limited to the keys the Look's own data (`shape`) writes, nested objects key by key."""
    out = {}
    for key, given in shape.items():
        if key not in values:
            continue
        if isinstance(given, dict) and isinstance(values[key], dict):
            out[key] = _authored(values[key], given)
        else:
            out[key] = copy.deepcopy(values[key])
    return out


def _unlike(values, base):
    """`values` without what is equal to `base` (the neutral defaults)."""
    out = {}
    for key, value in values.items():
        if key not in base:
            out[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(base[key], dict):
            inner = _unlike(value, base[key])
            if inner:
                out[key] = inner
        elif value != base[key]:
            out[key] = copy.deepcopy(value)
    return out


def own(settings):
    """A Look's settings as the AI is given them. A personal Look's are as they are. A library Look's values are only
    the ones it writes itself (a converted pack's own data, else what differs from the neutral defaults), so a recipe
    is never shown beside defaults it doesn't set; code still resolves the full values (`kit`, `catalog.resolve`)."""
    identity = settings.get('id')
    if not isinstance(identity, str) or identity == 'neutral' or identity.startswith('mine-') or settings.get('private'):
        return settings
    result = copy.deepcopy(settings)
    legacy = settings.get('legacy') or {}
    if legacy.get('format') in look_settings.PACK_FORMATS and isinstance(legacy.get('data'), dict):
        result['values'] = _authored(settings['values'], legacy['data'])
    else:
        result['values'] = _unlike(settings['values'], look_settings.neutral()['values'])
    result['values_are'] = 'own'
    result['not_set'] = OWN_ONLY
    return result


def library_own(identity, looks_root=None):
    """A library Look's own settings (`own`), from the shipped catalogue only."""
    return own(catalog.resolve(identity, looks_root=looks_root, public=True))


def read(identity):
    from letitedit.looks import looks
    try:
        settings = catalog.resolve(identity)
    except FileNotFoundError as error:
        raise ValueError(f'Look {identity!r} is not offered and has no stored settings') from error
    if looks.offered(identity) is not None:
        card = looks.read(identity)
    else:
        recipe = settings['resolved_links'].get('recipe')
        has_recipe = bool(recipe and Path(recipe).is_file())
        if not has_recipe and not settings.get('notice'):
            raise ValueError(f'Look {identity!r} has no saved recipe')
        text = Path(recipe).read_text(encoding='utf-8-sig') if has_recipe else ''
        entry = next((item for item in looks._manifest().get('looks', []) if item.get('id') == identity), {})
        from letitedit.looks.look_check import MEASUREMENTS
        card = {**entry, 'id': identity, 'label': settings['values'].get('label') or identity,
                'recipe': recipe, 'recipe_text': text,
                'measured': [name for name in MEASUREMENTS if has_recipe and Path(recipe).with_name(name).is_file()]}
    return {**card, 'settings': own(settings), **({'notice': settings['notice']} if settings.get('notice') else {})}


def require_offered(identity):
    from letitedit.looks import looks
    if looks.offered(identity) is None:
        read(identity)
        raise ValueError(f'Look {identity!r} is not approved for new selections; existing projects can still read its recipe and defaults')


def list_looks(kind=None):
    from letitedit.looks import looks
    if kind not in (None, 'short', 'long', 'both'):
        raise ValueError('kind is short, long or both')
    result = looks.catalog()
    if kind and kind != 'both':
        result['looks'] = [entry for entry in result['looks'] if entry.get('kind', 'both') in (kind, 'both')]
        wanted = {entry['id'] for entry in result['looks']}
        result['styles'] = [{**entry, 'looks': [item for item in entry.get('looks', []) if item['id'] in wanted]}
                            for entry in result.get('styles', [])]
    return result


def copy_look(identity, title=None):
    if title is not None:
        title = _title(title)
    read(identity)
    return look_migration.copy_look(identity, learned_looks.root(), title=title)


def create(title, values=None, recipe=None, *, assets=None, kind=None, works_with='footage',
           asks=None, personal_root=None, identity=None):
    """Publish new personal preferences in the Learn store, with sharing off and no source edits."""
    title = _title(title)
    if values is not None and not isinstance(values, dict):
        raise ValueError('values must be an object of Look defaults')
    kind = kind if kind is not None else (values or {}).get('kind') or 'both'
    if kind not in ('short', 'long', 'both'):
        raise ValueError('kind is short, long or both')
    if works_with not in ('footage', 'no-footage', 'both'):
        raise ValueError('works_with is footage, no-footage or both')
    if asks is not None and not isinstance(asks, list):
        raise ValueError('asks must be a list')
    assets = _assets(assets)
    identity = learned_looks._identity(identity) if identity else 'mine-custom-' + uuid.uuid4().hex
    revision = uuid.uuid4().hex
    settings = look_settings.neutral(identity)
    settings['values'] = look_settings.merge(settings['values'], values or {})
    settings['values']['kind'] = kind
    settings['values'].update(name=title, label=title)
    settings['asset_root'] = 'resources'
    settings['links']['recipe'] = 'recipe.md'
    settings['files']['recipe.md'] = 'recipe.md'
    for reference in assets:
        settings['files'][reference] = 'resources/' + reference.replace('\\', '/')
    look_settings.validate(settings)
    saved = {'format': learned_looks.FORMAT, 'id': identity, 'revision': revision, 'title': title,
             'line': settings['values'].get('summary') or 'Personal Look preferences.', 'needs': '',
             'works_with': works_with, 'kind': kind, 'asks': copy.deepcopy(asks or []), 'share': False}
    json.dumps(saved, allow_nan=False)
    directory_root = Path(personal_root) if personal_root is not None else learned_looks.root()
    directory = directory_root / identity
    staging = directory_root / ('.' + identity + '.tmp')
    version = staging / 'revisions' / revision
    try:
        version.mkdir(parents=True)
        for reference, original in assets.items():
            target = version / settings['files'][reference]
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(original, (bytes, bytearray)):
                target.write_bytes(original)
            else:
                shutil.copy2(original, target)
        (version / 'recipe.md').write_text(recipe if recipe is not None else 'Personal Look defaults.',
                                          encoding='utf-8')
        look_migration._dump(version / 'settings.json', settings)
        look_migration._dump(staging / 'look.json', saved)
        os.rename(staging, directory)
        return {**saved, 'directory': str(directory),
                'settings': str(directory / 'revisions' / revision / 'settings.json'),
                'recipe': str(directory / 'revisions' / revision / 'recipe.md')}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _assets(assets):
    if assets is not None and not isinstance(assets, dict):
        raise ValueError('assets must map relative references to files or bytes')
    assets = assets or {}
    from pathlib import PureWindowsPath
    for reference in assets:
        if (not isinstance(reference, str) or not reference or reference == 'recipe.md'
                or Path(reference).is_absolute() or PureWindowsPath(reference).root
                or PureWindowsPath(reference).drive
                or any(part in ('', '.', '..') or ':' in part for part in reference.replace('\\', '/').split('/'))):
            raise ValueError('asset references must stay inside the Look resources folder; recipe.md is reserved')
    return assets


def _write_assets(version, settings, assets):
    for reference, original in assets.items():
        relative = 'resources/' + reference.replace('\\', '/')
        settings['files'][reference] = relative
        target = version / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(original, (bytes, bytearray)):
            target.write_bytes(original)
        else:
            shutil.copy2(original, target)


def editor_read(identity=None):
    from letitedit.looks.style_pack import MY_STYLE_FIELDS, get_path
    selected = kit(identity)
    pointer = catalog.read_json(learned_looks.root() / identity / 'look.json', {}) if identity and identity.startswith('mine-') else {}
    return {'id': identity or 'neutral', 'revision': pointer.get('revision'),
            'title': pointer.get('title') or selected.get('label') or identity,
            'folder': str(selected.root) if selected.root else None,
            'fields': [dict(field, label='Name of your Look' if field['key'] == 'label' else field['label'],
                            value=pointer.get('kind', get_path(selected, field['key'])) if field['key'] == 'kind'
                            else get_path(selected, field['key'])) for field in MY_STYLE_FIELDS],
            'style': dict(selected)}


def _title(title):
    if not isinstance(title, str):
        raise ValueError('a Look name must be text')
    title = ' '.join(title.split())
    if not title or len(title) > learned_looks.NAME_LIMIT:
        raise ValueError(f'a Look name is 1-{learned_looks.NAME_LIMIT} characters')
    return title


def update(identity, changes=None, title=None, expected_revision=None, *, assets=None):
    """Atomically publish a personal revision; leave all prior revisions untouched."""
    directory = learned_looks.root() / learned_looks._identity(identity)
    with look_migration.save_lock(directory):
        return _update_locked(identity, changes, title, expected_revision, assets=assets)


def _update_locked(identity, changes=None, title=None, expected_revision=None, *, assets=None):
    identity = learned_looks._identity(identity)
    if changes is not None and not isinstance(changes, dict):
        raise ValueError('changes must be an object of Look values')
    assets = _assets(assets)
    if not changes and title is None and not assets:
        raise ValueError('an update needs changes, a title or assets')
    if title is not None:
        title = _title(title)
    directory = learned_looks.root() / identity
    pointer = directory / 'look.json'
    version = None
    temporary_pointer = directory / ('.' + uuid.uuid4().hex + '.json')
    published = False
    try:
        current = catalog.read_json(pointer, {})
        if current.get('id') != identity or current.get('format') != learned_looks.FORMAT:
            raise ValueError('no personal Look with that id')
        previous = current.get('revision')
        if not isinstance(previous, str) or len(previous) != 32 or any(char not in '0123456789abcdef' for char in previous):
            raise ValueError('invalid personal Look revision')
        if expected_revision is not None and previous != expected_revision:
            raise ValueError('the Look changed; read its current revision before updating')
        source = directory / 'revisions' / previous
        settings_file = source / 'settings.json'
        if not settings_file.is_file() and (directory / 'settings.json').is_file():
            settings_file = directory / 'settings.json'
        if settings_file.is_file():
            settings = look_settings.read(settings_file)
        else:
            settings = look_settings.neutral(identity)
            settings['links']['recipe'] = 'recipe.md'
            settings['share'] = current.get('share', True)
            settings['values'].update(name=current.get('title') or identity,
                                      label=current.get('title') or identity)
        settings = copy.deepcopy(settings)
        settings['asset_root'] = look_settings.resolve_path(settings.get('asset_root', '.'), settings_file.parent)
        settings['files'] = {key: look_settings.resolve_path(value, settings_file.parent)
                             for key, value in settings.get('files', {}).items()}
        settings['values'] = look_settings.merge(settings['values'], changes or {})
        if changes and 'kind' in changes and settings['values']['kind'] not in (None, 'short', 'long', 'both'):
            raise ValueError('kind is short, long or both')
        if title is not None:
            settings['values']['name'] = title
            settings['values']['label'] = title
        if current.get('private') or look_settings.is_private(settings):
            settings.update(private=True, share=False)
        elif current.get('share') is False:
            settings['share'] = False
        look_settings.validate(settings)
        revision = uuid.uuid4().hex
        version = directory / 'revisions' / revision
        shutil.copytree(source, version)
        _write_assets(version, settings, assets)
        if title is not None:
            recipe_path = version / 'recipe.md'
            recipe = recipe_path.read_text(encoding='utf-8-sig')
            recipe = re.sub(r'(?m)^# [^\n]+', lambda match: '# ' + title, recipe, count=1)
            recipe_path.write_text(recipe, encoding='utf-8')
        look_migration._dump(version / 'settings.json', settings)
        saved = {**current, 'revision': revision, 'share': settings['share']}
        if changes and 'kind' in changes:
            saved['kind'] = settings['values']['kind'] or 'both'
        if title is not None:
            saved['title'] = title
        if settings.get('private'):
            saved['private'] = True
        look_migration._dump(temporary_pointer, saved)
        os.replace(temporary_pointer, pointer)
        published = True
        return saved
    finally:
        temporary_pointer.unlink(missing_ok=True)
        if version is not None and not published:
            shutil.rmtree(version)


def query(action='list', identity=None, *, kind=None, title=None, changes=None,
          expected_revision=None, project=None, inputs=None, unused=None, popups=None, assets=None):
    """The shared factual interface for the editor and the Looks tool; no renders or migrations."""
    if action == 'list':
        return list_looks(kind)
    if action == 'get':
        if not identity:
            raise ValueError('get needs a Look id')
        return read(identity)
    if action == 'settings':
        if identity not in (None, 'neutral'):
            return read(identity)['settings']
        return catalog.resolve()
    if action == 'copy':
        if not identity:
            raise ValueError('copy needs a Look id')
        return copy_look(identity, title)
    if action == 'update':
        if not identity:
            raise ValueError('update needs a personal Look id')
        return update(identity, changes, title, expected_revision, assets=assets)
    if action == 'inputs':
        from letitedit.looks import look_inputs
        if not project:
            raise ValueError('inputs needs a project')
        record = (look_inputs.attach(inputs if inputs != 'read' else None, project, unused)
                  if (inputs and inputs != 'read') or unused else look_inputs.read(project))
        return {'inputs_file': str(look_inputs.record_path(project)), 'record': record,
                'by_role': look_inputs.by_role(record), 'plain': look_inputs.describe(record)}
    if action == 'popups':
        from letitedit.looks import popups as project_popups
        if not project:
            raise ValueError('popups needs a project')
        if popups is not None:
            project_popups.save_project_entries(project, popups)
        return {'project_popups': str(project_popups.project_file(project)),
                'entries': project_popups.project_entries(project)}
    raise ValueError('action is list, get, settings, copy, update, inputs or popups')


def main(argv=None):
    """JSON-only local CLI. Requests name their target explicitly; no ambient app state is changed."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', help='UTF-8 JSON object with the query arguments')
    parser.add_argument('--list-json', action='store_true', help='offered Looks and content categories')
    parser.add_argument('--root', action='store_true', help='personal Look store location, without creating it')
    args = parser.parse_args(argv)
    try:
        if sum((bool(args.request), args.list_json, args.root)) != 1:
            raise ValueError('choose --request, --list-json or --root')
        if args.root:
            result = {'root': str(learned_looks.root())}
        elif args.list_json:
            result = query()
        else:
            request = json.loads(Path(args.request).read_text(encoding='utf-8-sig'))
            if not isinstance(request, dict):
                raise ValueError('a Look request must be an object')
            if request.get('action') == 'create':
                request.pop('action')
                result = create(**request)
            elif request.get('action') == 'project':
                result = {'id': project_identity(request.get('project') or {}), 'root': str(learned_looks.root())}
            elif request.get('action') == 'location':
                result = {'root': str(learned_looks.root())}
            elif request.get('action') == 'editor':
                result = editor_read(request.get('identity'))
            else:
                result = query(**request)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())


