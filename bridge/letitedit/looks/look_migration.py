"""Opt-in copy/backup migration. Importing or reading a project never writes files."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import uuid
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path

from letitedit.looks import look_settings


def _dump(path, data):
    with Path(path).open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def _inventory(source):
    files = {}
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'migration does not follow symbolic links: {path}')
        if path.is_file():
            files[path.relative_to(source).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


@contextmanager
def _migration_lock(path):
    """An OS lease, released even on process death; the stable lock file stays."""
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR)
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b'\0')
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise FileExistsError('this Look is being migrated; retry after the other copy finishes') from error
        yield
    finally:
        os.close(descriptor)


@contextmanager
def save_lock(directory):
    directory = Path(directory)
    flag = directory / '.save-lock'
    with _migration_lock(directory / '.save-lease'):
        if flag.exists():
            try:
                abandoned = json.loads(flag.read_text(encoding='utf-8-sig')).get('os_lease') == 1
            except (ValueError, AttributeError):
                abandoned = False
            if not abandoned:
                raise FileExistsError('this Look is being saved; retry after the other save finishes')
        temporary = directory / ('.save-lock-' + uuid.uuid4().hex + '.tmp')
        try:
            _dump(temporary, {'os_lease': 1})
            os.replace(temporary, flag)
            try:
                yield
            finally:
                flag.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)


def legacy_source(identity):
    from letitedit.looks import style_pack
    names = {'mine-' + name: name for name in look_settings.private_packs()}
    names['mine-my-style'] = 'My style'
    name = names.get(identity)
    source = style_pack.STYLE_ROOT / name if name else None
    return source if source is not None and source.is_dir() else None


def legacy_settings(identity):
    source = legacy_source(identity)
    if source is None:
        return None
    settings = look_settings.read_pack(source, identity, asset_root=str(source), private=True)
    settings['share'] = False
    settings_only = not settings['links'].get('recipe')
    if settings_only:
        settings['links']['recipe'] = look_settings.pack_file(source).name
    result = look_settings.resolved(settings, source)
    result['settings_only'] = settings_only
    result['notice'] = 'Read-only legacy preferences; no files have been migrated. Copy explicitly to edit a personal Look.'
    if settings_only:
        result['notice'] += ' The original settings file supplies its written guidance; it is not a measured recipe.'
    return result


def visible_personal(identity):
    return identity not in {'mine-' + name for name in look_settings.hidden_packs()}


def legacy_entries(personal_root):
    result = []
    offered = ['mine-' + name for name in look_settings.private_packs()]
    for identity in [*filter(visible_personal, offered), 'mine-my-style']:
        if (Path(personal_root) / identity / 'look.json').is_file():
            continue
        settings = legacy_settings(identity)
        if settings is None:
            continue
        recipe = settings['resolved_links'].get('recipe')
        result.append({'id': identity, 'label': settings['values'].get('label') or settings['values'].get('name') or identity,
                       'style': 'talking-head', 'approved': True, 'personal': False, 'private': True, 'share': False,
                       'settings_only': settings['settings_only'], 'settings_source': str(look_settings.pack_file(legacy_source(identity))),
                       'recipe': recipe, 'preview': settings['resolved_links'].get('preview'),
                       'line': settings['notice'], 'kind': settings['values'].get('kind') or 'both'})
    return result


def migrate_pack(source, looks_root, identity, *, private=False):
    """Publish a complete new personal Look atomically; never modify the source.

    A retry returns the first copy. Changed source data requires another id, not
    overwriting a Look the person may already have edited. No sharing is started.
    """
    from letitedit.looks.learned_looks import _identity
    _identity(identity)
    source, looks_root = Path(source).resolve(), Path(looks_root).resolve()
    if not source.is_dir():
        raise ValueError('migration source must be a pack folder')
    if source == looks_root or source in looks_root.parents or looks_root in source.parents:
        raise ValueError('source and My Looks must be separate folders')
    settings = look_settings.read_pack(source, identity, asset_root='resources', private=private)
    settings['share'] = False
    inventory = _inventory(source)
    fingerprint = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
    destination = looks_root / identity
    marker = {'format': 'letitedit-look-migration/1', 'source': str(source), 'files': inventory,
              'fingerprint': fingerprint}
    looks_root.mkdir(parents=True, exist_ok=True)
    lock = looks_root / ('.' + identity + '.migration-lock')
    staging = looks_root / ('.' + identity + '.tmp-' + uuid.uuid4().hex)
    with _migration_lock(lock):
        return _migrate_locked(source, destination, staging, settings, marker, inventory, identity)


def _migrate_locked(source, destination, staging, settings, marker, inventory, identity):
    from letitedit.looks.learned_looks import FORMAT
    try:
        if destination.exists():
            previous = destination / 'migration.json'
            if not previous.is_file() or json.loads(previous.read_text(encoding='utf-8-sig')) != marker:
                raise ValueError('destination exists or source changed; choose a new personal Look id')
            return {'id': identity, 'directory': str(destination), 'created': False, 'share': False}
        staging.mkdir()
        shutil.copytree(source, staging / 'backup')
        revision = uuid.uuid4().hex
        version = staging / 'revisions' / revision
        version.mkdir(parents=True)
        shutil.copytree(staging / 'backup', version / 'resources')
        if _inventory(staging / 'backup') != inventory or _inventory(source) != inventory:
            raise ValueError('source changed during migration; retry with a stable source')
        for reference in look_settings.references(settings):
            original = Path(look_settings.resolve_path(reference, source))
            if original.is_file() and not original.is_relative_to(source):
                name = hashlib.sha256(reference.encode()).hexdigest()[:16] + '-' + original.name
                relative = Path('resources') / '_external' / name
                (version / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, version / relative)
                settings['files'][reference] = relative.as_posix()
        recipe_ref = settings['links'].get('recipe')
        recipe_path = Path(look_settings.resolve_path(recipe_ref, source)) if recipe_ref else None
        recipe = (recipe_path.read_text(encoding='utf-8-sig') if recipe_path and recipe_path.is_file()
                  else settings['values'].get('taste') or settings['values'].get('description') or 'Look defaults.')
        (version / 'recipe.md').write_text(recipe, encoding='utf-8')
        _dump(version / 'settings.json', settings)
        _dump(staging / 'migration.json', marker)
        saved = {'format': FORMAT, 'id': identity, 'revision': revision,
                 'title': settings['values'].get('name') or source.name,
                 'kind': settings['values'].get('kind') if settings['values'].get('kind') in ('short', 'long', 'both') else 'both',
                 'line': settings['values'].get('description') or 'Copied Look preferences.',
                 'needs': '', 'works_with': 'footage', 'asks': [], 'share': False,
                 'private': look_settings.is_private(settings)}
        _dump(staging / 'look.json', saved)
        os.rename(staging, destination)
        return {'id': identity, 'directory': str(destination), 'created': True, 'share': False}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def migrate_private_packs(style_root, looks_root):
    """Only an explicit caller migrates the private packs this PC lists (look_settings.private_packs)."""
    return [migrate_pack(Path(style_root) / name, looks_root, 'mine-' + name, private=True)
            for name in look_settings.private_packs()]


def migrate_my_style(source, looks_root):
    """Opt-in only: source is the person's My style folder, never inferred."""
    return migrate_pack(source, looks_root, 'mine-my-style')


@contextmanager
def _copy_source(identity, looks_root, shipped_root):
    from letitedit.looks import catalog, learned_looks
    lock = None
    lease = None
    if isinstance(identity, str) and identity.startswith('mine-') and (Path(looks_root) / identity / 'look.json').is_file():
        learned_looks._identity(identity)
        directory = Path(looks_root) / identity
        lock = directory / '.save-lock'
        lease = save_lock(directory)
        lease.__enter__()
    try:
        settings = catalog.resolve(identity, looks_root=shipped_root, personal_root=looks_root)
        if lock is not None:
            metadata = catalog.read_json(directory / 'look.json', {})
            source = directory / 'revisions' / metadata['revision']
        elif legacy_source(identity) is not None:
            source = legacy_source(identity)
            metadata = {'title': settings['values'].get('name') or identity, 'private': True, 'share': False,
                        'kind': settings['values'].get('kind') or 'both'}
        else:
            from letitedit.core.paths import install_root
            directory = Path(shipped_root) if shipped_root is not None else Path(install_root()) / 'looks'
            metadata = next((entry for entry in catalog.LocalSource(directory).manifest({}).get('looks', [])
                             if entry.get('id') == identity), {})
            if metadata and (metadata.get('approved') is not True or metadata.get('cut')):
                raise ValueError(f'Look {identity!r} is not approved for copying or new selections; existing projects can still read and use it')
            metadata = copy.deepcopy(metadata)
            if metadata.get('recipe_shared'):
                metadata['recipe_shared'] = str(directory / metadata['recipe_shared'])
            recipe = settings['resolved_links'].get('recipe')
            source = Path(recipe).parent if recipe else None
        yield settings, metadata, source
    finally:
        if lease is not None:
            lease.__exit__(None, None, None)


def copy_look(identity, looks_root, *, shipped_root=None, title=None):
    """Copy one stable revision, its defaults and measured profiles; never copy reference videos."""
    if title is not None:
        from letitedit.looks.learned_looks import NAME_LIMIT
        if not isinstance(title, str) or not title.strip() or len(' '.join(title.split())) > NAME_LIMIT:
            raise ValueError(f'a Look name is 1-{NAME_LIMIT} characters')
        title = ' '.join(title.split())
    with _copy_source(identity, looks_root, shipped_root) as snapshot:
        return _copy_look(identity, looks_root, *snapshot, title=title)


def _copy_look(identity, looks_root, settings, metadata, source, title=None):
    new_identity = 'mine-copy-' + uuid.uuid4().hex
    destination = Path(looks_root) / new_identity
    temporary = Path(looks_root) / ('.' + new_identity + '.tmp')
    revision = uuid.uuid4().hex
    version = temporary / 'revisions' / revision
    try:
        version.mkdir(parents=True)
        settings = copy.deepcopy(settings)
        graphics = Path(settings['asset_root']) / 'graphics'
        allowed = {'.py', '.json', '.png', '.jpg', '.jpeg', '.webp', '.svg', '.ttf', '.otf'}
        if graphics.is_symlink():
            raise ValueError('Look graphics do not follow symbolic links')
        if graphics.is_dir():
            for original in graphics.rglob('*'):
                if original.is_symlink():
                    raise ValueError('Look graphics do not follow symbolic links')
                if not original.is_file() or original.suffix.lower() not in allowed:
                    continue
                target = version / 'resources' / 'graphics' / original.relative_to(graphics)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, target)
        settings.update(id=new_identity, share=False, asset_root='resources', files={})
        for reference, original in settings.pop('references').items():
            path = Path(original)
            if path.is_file():
                relative = Path('resources') / (hashlib.sha256(reference.encode()).hexdigest()[:16] + '-' + path.name)
                (version / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, version / relative)
                settings['files'][reference] = relative.as_posix()
            else:
                settings['files'][reference] = original
        recipe = settings.get('resolved_links', {}).get('recipe')
        recipe_text = (Path(recipe).read_text(encoding='utf-8-sig') if recipe and Path(recipe).is_file()
                       else 'Copied Look defaults.')
        shared = metadata.get('recipe_shared')
        if shared:
            shared_path = Path(shared)
            if not shared_path.is_absolute():
                shared_path = Path(settings['asset_root']) / shared_path
            if shared_path.is_file():
                recipe_text += '\n\n' + shared_path.read_text(encoding='utf-8-sig')
        if title is not None:
            recipe_text = re.sub(r'(?m)^# [^\n]+', lambda match: '# ' + title, recipe_text, count=1)
            settings['values'].update(name=title, label=title)
        recipe_text = recipe_text.replace('{op: look, id: ' + identity + '}', '{op: look, id: ' + new_identity + '}')
        (version / 'recipe.md').write_text(recipe_text, encoding='utf-8')
        settings['links']['recipe'] = 'recipe.md'
        settings['files']['recipe.md'] = 'recipe.md'
        if source is not None:
            for name in ('visual.json', 'lighting.json', 'grade.json', 'sound.json', 'sources.json',
                         'graphic-kit.json', 'place.json', 'evidence.json', 'project.json', 'theme.md'):
                original = source / name
                if original.is_file():
                    shutil.copy2(original, version / name)
        for key in ('missing_assets', 'resolved_links'):
            settings.pop(key, None)
        _dump(version / 'settings.json', look_settings.validate(settings))
        from letitedit.looks.learned_looks import FORMAT
        saved = {key: copy.deepcopy(metadata[key]) for key in
                 ('title', 'line', 'needs', 'works_with', 'asks', 'kind', 'fits', 'fits_line',
                  'theme', 'themes', 'own_media') if key in metadata}
        if title is not None:
            saved['title'] = title
        saved.setdefault('title', settings['values'].get('name') or identity)
        saved.setdefault('line', metadata.get('blurb') or 'Copied Look.')
        saved.setdefault('needs', '')
        saved.setdefault('works_with', 'footage')
        saved.setdefault('asks', [])
        saved.update(format=FORMAT, id=new_identity, revision=revision, based_on=identity,
                     share=False, private=look_settings.is_private(settings))
        _dump(temporary / 'look.json', saved)
        os.rename(temporary, destination)
        return {'id': new_identity, 'revision': revision, 'directory': str(destination), 'share': False}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def legacy_project_look(project, mapping=None, *, looks_root=None, personal_root=None):
    """Read metadata only. Return the mapped id, never apply a Look or save XML.

    Accept an edit-script object/JSON or MLT's pinned ai:style metadata, including
    old versioned pack filenames. Unknown ids are left unresolved.
    """
    personal_mapping = mapping is None
    if mapping is None:
        from letitedit.core.paths import install_root
        from letitedit.looks.catalog import LocalSource
        source = LocalSource(looks_root if looks_root is not None else Path(install_root()) / 'looks')
        mapping = source.manifest({}).get('legacy_packs', {})
    if isinstance(project, dict):
        data = project
    else:
        path = Path(project)
        if path.suffix.lower() == '.json':
            data = json.loads(path.read_text(encoding='utf-8-sig'))
        else:
            tree = ET.parse(path)
            root = tree.getroot()
            tractors = root.findall('./tractor')
            marked = [tractor for tractor in tractors if any(
                element.get('name') == 'shotcut' and element.text == '1'
                for element in tractor.findall('./property'))]
            main = (marked or tractors)[-1] if tractors else root
            data = {element.get('name'): element.text for element in main.findall('./property')}
    value = data.get('style') or data.get('letitedit_ai:style') or data.get('ai:style')
    if isinstance(value, dict):
        value = value.get('pack') or value.get('name') or value.get('id')
    if not isinstance(value, str) or not value:
        return None
    parts = value.replace('\\', '/').rstrip('/').split('/')
    if re.fullmatch(r'v[0-9]{3}\.json|style\.yaml', parts[-1]):
        parts = parts[:-1]
    pack = parts[-1] if parts else ''
    if pack in look_settings.private_packs():
        return 'mine-' + pack
    if pack == 'My style':
        return 'mine-my-style'
    entry = mapping.get(pack)
    identity = entry.get('look') if isinstance(entry, dict) else entry
    if identity or not personal_mapping:
        return identity
    from letitedit.looks import learned_looks
    directory = Path(personal_root) if personal_root is not None else learned_looks.root()
    matches = []
    for marker in directory.glob('mine-*/migration.json'):
        try:
            pointer = json.loads(marker.with_name('look.json').read_text(encoding='utf-8-sig'))
            revision = pointer.get('revision')
            if not isinstance(revision, str) or not re.fullmatch('[a-f0-9]{32}', revision):
                continue
            settings = look_settings.read(marker.parent / 'revisions' / revision / 'settings.json')
            if (settings.get('legacy') or {}).get('pack') == pack:
                matches.append(settings['id'])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return matches[0] if len(matches) == 1 else None
