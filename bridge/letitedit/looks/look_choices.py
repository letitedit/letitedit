"""Data-backed New video choices and local owner review (catalog schema v2)."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from letitedit.looks import catalog as _catalog  # noqa: E402  (where Styles, Looks and Themes come from)


read_json = _catalog.read_json     # a JSON file's data, or the default when it isn't there


def review_enabled(root):
    settings = os.environ.get('LETITEDIT_CHAT_SETTINGS')
    directory = Path(settings).parent if settings else Path(root) / 'appdata'
    try:
        return read_json(directory / 'looks-review.json', {}).get('enabled') is True
    except (ValueError, AttributeError):
        return False


def style_id(value):
    return 'idea' if value == 'made-with-code' else value


def visible(entry, review):
    return bool(entry.get('id')) and ((entry.get('approved') is True and not entry.get('cut'))
                                     or (review and entry.get('review') == 'new')
                                     or (review and entry.get('cut')))


def catalog(root, looks_root, data, make_card):
    local = _catalog.LocalSource(looks_root)
    modern = local.has_styles()
    review = review_enabled(root)
    raw_styles = local.styles(data.get('styles') or [])
    raw_themes = local.themes() + data.get('_personal_themes', [])
    if any(entry.get('personal') for entry in data.get('looks', [])):
        known = {entry.get('id') for entry in raw_styles}
        raw_styles = raw_styles + [_catalog.PersonalSource().style] + [
            entry for entry in data.get('_personal_styles', []) if entry.get('id') not in known]
        modern = True
    problems, skipped, looks, styles, themes, reviews = list(data.get('_personal_problems', [])), [], [], [], [], []
    folders = {entry['id']: entry for entry in data.get('folders', []) if entry.get('id')}
    for entry in data.get('looks') or []:
        if not visible(entry, review):
            continue
        result = make_card(entry, folders.get(entry.get('folder')), problems)
        result.update(themes=entry.get('themes', 'none'), review=entry.get('review', ''),
                      cut=bool(entry.get('cut')), theme_only=bool(entry.get('theme_only')))
        if modern:
            result['style'] = style_id(result['style'])
            result['fits'] = list(dict.fromkeys(style_id(kind) for kind in result.get('fits') or [result['style']]))
        if not result['recipe'] and not result.get('settings_only'):
            skipped.append({'id': entry['id'], 'error': 'recipe file missing'})
        else:
            looks.append(result)
    for entry in sorted(raw_styles, key=lambda item: item.get('order', 0)):
        if not visible(entry, review):
            continue
        identity = style_id(entry['id']) if modern else entry['id']
        mine = [look for look in looks if look['style'] == identity and not (modern and look['theme_only'])]
        # every Look that fits this kind of video, its main Style or not (`looks` keeps the Looks whose main Style it is)
        fitting = [look['id'] for look in looks
                   if identity in (look.get('fits') or [look['style']]) and not (modern and look['theme_only'])]
        if not mine and not modern:
            continue
        works = {look['works_with'] for look in mine}
        footage = 'no' if works == {'no-footage'} else 'yes' if works == {'footage'} else 'optional'
        grouped = []
        for folder in folders.values():
            folder_style = style_id(folder.get('style')) if modern else folder.get('style')
            inside = [look['id'] for look in mine if look['folder'] == folder['id']]
            if folder_style == identity and folder.get('approved', True) and inside:
                grouped.append({'id': folder['id'], 'label': folder.get('label', folder['id']),
                                'line': folder.get('line', ''), 'looks': inside})
        styles.append({**entry, 'id': identity, 'label': entry.get('title') or entry.get('label') or identity,
                       'line': entry.get('blurb') or entry.get('line', ''), 'kind': entry.get('kind', 'both'),
                       'footage': entry.get('footage', footage), 'folders': grouped, 'looks': mine,
                       'fitting': fitting})
    allowed = {entry['id'] for entry in styles if not entry.get('cut')}
    if not review:
        looks = [look for look in looks if look['style'] in allowed]
        for look in looks:
            look['fits'] = [kind for kind in look.get('fits') or [look['style']] if kind in allowed]
        offered_ids = {look['id'] for look in looks}
        for entry in styles:
            entry['fitting'] = [identity for identity in entry['fitting'] if identity in offered_ids]
    for entry in sorted(raw_themes, key=lambda item: item.get('order', 0)):
        if not visible(entry, review) or entry.get('kind') not in ('kit', 'film'):
            continue
        recipe = looks_root / entry.get('recipe', '')
        if not recipe.is_file():
            skipped.append({'id': entry['id'], 'error': 'theme recipe file missing'})
            continue
        poster = looks_root / entry.get('poster', '')
        shared = looks_root / entry['recipe_shared'] if entry.get('recipe_shared') else None
        themes.append({**entry, 'recipe': str(recipe), 'recipe_shared': str(shared) if shared and shared.is_file() else None,
                       'poster': str(poster) if poster.is_file() else None})
    if review:
        for kind, entries in (('style', raw_styles), ('look', data.get('looks', [])), ('theme', raw_themes)):
            for entry in entries:
                if visible(entry, review) and not entry.get('personal') and not entry.get('private'):
                    reviews.append({**entry, 'entry_kind': kind, 'title': entry.get('title') or entry.get('label') or entry['id']})
    return {'layout_version': 2 if modern else 1, 'review_enabled': review, 'styles': styles, 'looks': looks,
            'themes': themes, 'review_items': reviews, 'skipped': skipped, 'problems': problems}


def review_entry(root, looks_root, kind, identity, action):
    if not review_enabled(root):
        raise PermissionError('Owner review is not enabled in this install.')
    if kind not in _catalog.FILES or action not in ('keep', 'cut', 'restore'):
        raise ValueError('Review needs a style, look or theme and keep, cut or restore.')
    target = _catalog.LocalSource(looks_root).path(kind)
    lock = target.with_suffix('.review-lock')
    deadline = time.monotonic() + 8
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError('Another review is saving. Try again in a moment.')
            time.sleep(.05)
    temporary = None
    try:
        for attempt in range(4):
            original = target.read_bytes()
            document = json.loads(original.decode('utf-8-sig'))
            entries = document['looks'] if kind == 'look' else document
            entry = next((item for item in entries if item.get('id') == identity), None)
            if entry is None:
                raise KeyError(f'No {kind} called {identity!r}.')
            if action == 'keep':
                entry['approved'] = True
                entry.pop('review', None)
                entry.pop('cut', None)
            elif action == 'cut':
                entry['cut'] = True
            else:
                entry.pop('cut', None)
            descriptor, temporary = tempfile.mkstemp(prefix=target.name, suffix='.tmp', dir=target.parent)
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
                json.dump(document, output, ensure_ascii=False, indent=2)
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            if target.read_bytes() != original:
                Path(temporary).unlink()
                temporary = None
                continue
            os.replace(temporary, target)
            temporary = None
            return {'kind': kind, 'id': identity, 'action': action, 'entry': entry}
        raise RuntimeError('The catalog changed while saving. Nothing was overwritten; try again.')
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
