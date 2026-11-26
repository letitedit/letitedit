"""Personal Look revisions, independent of the installed catalog."""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import re
import shutil
import uuid
from pathlib import Path

FORMAT = 'letitedit-personal-look/1'
STYLE = {'id': 'personal-looks', 'title': 'Your Looks', 'filter_label': 'Your Looks',
         'blurb': 'Ways of editing learned from your reference videos.', 'approved': True,
         'kind': 'both', 'footage': 'optional', 'order': 1000, 'personal': True}


def _documents():
    """The Documents folder Windows reports (a OneDrive or redirected one included), the same one the editor's Projects
    folder uses (Qt's DocumentsLocation); the home folder's Documents elsewhere or if Windows can't say."""
    if os.name == 'nt':
        try:
            import ctypes

            class _Guid(ctypes.Structure):
                _fields_ = [('a', ctypes.c_uint32), ('b', ctypes.c_uint16), ('c', ctypes.c_uint16),
                            ('d', ctypes.c_ubyte * 8)]

            documents = _Guid(0xFDD39AD0, 0x238F, 0x46AF,
                              (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))  # FOLDERID_Documents
            found = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(documents), 0, None, ctypes.byref(found)) == 0:
                try:
                    if found.value:
                        return Path(found.value)
                finally:
                    ctypes.windll.ole32.CoTaskMemFree(found)
        except Exception:
            pass
    return Path.home() / 'Documents'


def root():
    explicit = os.environ.get('LETITEDIT_MY_LOOKS')
    if explicit:
        return Path(explicit)
    import letitedit.app.letitedit_instances as instances
    registry = instances.ROOT / instances.current() / 'editor.json'
    try:
        profile = _read(registry)
        if isinstance(profile, dict) and profile.get('instance_id') == instances.current():
            folder = profile.get('my_looks')
            if isinstance(folder, str) and Path(folder).is_absolute():
                return Path(folder)
            appdata = profile.get('appdata')
            if instances.current() != 'main' and isinstance(appdata, str) and Path(appdata).is_absolute():
                return Path(appdata) / 'My Looks'
    except (OSError, ValueError, TypeError):
        pass
    if instances.current() != 'main':
        return instances.ROOT / instances.current() / 'appdata' / 'My Looks'
    return _documents() / 'letitedit' / 'My Looks'


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'mine-[a-z0-9]+(?:-[a-z0-9]+)*', value):
        raise ValueError('id must be mine- followed by lowercase words separated by hyphens')
    return value


def catalog(looks_root=None):
    entries, themes, problems = [], [], []
    directory_root = Path(looks_root) if looks_root is not None else root()
    for pointer in sorted(directory_root.glob('mine-*/look.json')):
        try:
            saved = _read(pointer)
            identity = _identity(saved['id'])
            from letitedit.looks import look_migration
            if not look_migration.visible_personal(identity):
                continue
            revision = saved['revision']
            if saved['format'] != FORMAT or identity != pointer.parent.name:
                raise ValueError('invalid personal Look record')
            if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{32}', revision):
                raise ValueError('invalid revision')
            directory = pointer.parent / 'revisions' / revision
            recipe = directory / 'recipe.md'
            if not recipe.is_file():
                raise ValueError('recipe missing')
            entry = {key: saved[key] for key in ('id', 'title', 'line', 'needs', 'works_with', 'asks')}
            if isinstance(saved.get('fits'), list):
                entry['fits'] = [STYLE['id']] + [kind for kind in saved['fits'] if isinstance(kind, str)]
            elif isinstance(saved.get('fits'), str):
                entry['fits_line'] = saved['fits']
            if saved.get('fits_line'):
                entry['fits_line'] = saved['fits_line']
            if (directory / 'place.json').is_file():
                entry['place'] = str(directory / 'place.json')
            entry.update(style=STYLE['id'], approved=True, personal=True, revision=revision,
                         recipe=str(recipe), themes=saved.get('themes') if saved.get('themes') in ('kits', 'film') else 'none')
            entry.update(example(pointer.parent))
            if saved.get('kind') in ('short', 'long', 'both'):
                entry['kind'] = saved['kind']
            if saved.get('based_on'):
                entry['based_on'] = saved['based_on']
            if isinstance(saved.get('own_media'), dict):
                entry['own_media'] = saved['own_media']
            if saved.get('share') is False:
                entry['share'] = False
            if saved.get('private') is True:
                entry['private'] = True
            settings = directory / 'settings.json'
            if not settings.is_file():
                settings = pointer.parent / 'settings.json'
            if settings.is_file():
                entry['settings'] = str(settings)
            if (directory / 'sound.json').is_file():
                entry['sound_profile'] = str(directory / 'sound.json')
            if (directory / 'visual.json').is_file():
                entry['visual_profile'] = str(directory / 'visual.json')
            if (directory / 'sources.json').is_file():
                entry['source_profile'] = str(directory / 'sources.json')
            if (directory / "lighting.json").is_file():
                entry["lighting_profile"] = str(directory / "lighting.json")
            if (directory / 'graphic-kit.json').is_file():
                entry['graphic_kit'] = str(directory / 'graphic-kit.json')
            if (directory / 'project.json').is_file():
                entry['project_profile'] = str(directory / 'project.json')
            if saved.get('theme'):
                theme = directory / 'theme.md'
                if not theme.is_file():
                    raise ValueError('Theme recipe missing')
                kind = saved['theme']['kind']
                if kind not in ('kit', 'film'):
                    raise ValueError('invalid Theme kind')
                entry['themes'] = 'kits' if kind == 'kit' else 'film'
                themes.append({'id': identity + '-theme', 'title': saved['theme']['title'],
                               'kind': kind, 'approved': True, 'personal': True,
                               'recipe': str(theme), 'looks': [identity], 'styles': [STYLE['id']]})
            entries.append(entry)
        except (OSError, ValueError, TypeError, KeyError) as error:
            problems.append(f'{pointer}: {error}')
    used = {kind for entry in entries for kind in entry.get('fits', [])}
    learned = [style for style in styles(directory_root) if style['id'] in used]
    return {'root': str(directory_root), 'looks': entries, 'themes': themes, 'styles': learned, 'problems': problems}


STYLES_FORMAT = 'letitedit-personal-styles/1'


def styles(looks_root=None):
    """The kinds of video Learn named because no Style fitted (My Looks' styles.json): each a Style New video shows
    as a tab when it has Looks."""
    path = (Path(looks_root) if looks_root else root()) / 'styles.json'
    try:
        data = _read(path)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get('format') != STYLES_FORMAT:
        return []
    return _route_corrected([dict(style) for style in data.get('styles', []) if isinstance(style, dict)
                             and isinstance(style.get('id'), str) and style['id'].startswith('mine-style-')],
                            path.parent)


def _route_fields(works_with):
    """A new learned Style's route, from the Look that named it: a Look made without footage names a 100% AI Style
    (the catalogue's own 100% AI Styles carry the same two fields); any other a filmed-footage one."""
    return {'group': 'ai', 'footage': 'no'} if works_with == 'no-footage' else {'group': 'footage', 'footage': 'yes'}


def _route_corrected(entries, directory_root):
    """A learned Style written as a filmed-footage one though every Look naming it is made without footage reads as a
    100% AI Style, so a Look learned before the route was written is offered where it works."""
    works = {}
    for pointer in Path(directory_root).glob('mine-*/look.json'):
        try:
            saved = _read(pointer)
        except (OSError, ValueError):
            continue
        if isinstance(saved, dict) and isinstance(saved.get('fits'), list):
            for kind in saved['fits']:
                if isinstance(kind, str):
                    works.setdefault(kind, set()).add(saved.get('works_with', 'footage'))
    for style in entries:
        if style.get('footage') != 'no' and works.get(style['id']) == {'no-footage'}:
            style.update(_route_fields('no-footage'))
    return entries


def known_styles(looks_root=None):
    """Style id -> title for every Style a learned Look may name: the catalogue's offered footage and 100% AI
    Styles and the person's learned ones."""
    known = {}
    try:
        from letitedit.looks import catalog as _catalog
        import letitedit.looks.looks as looks
        for style in _catalog.LocalSource(looks.LOOKS_ROOT).styles([]):
            if (style.get('approved') is True and not style.get('cut') and style.get('group') in ('footage', 'ai')
                    and isinstance(style.get('id'), str)):
                known[style['id']] = style.get('title') or style['id']
    except Exception:  # noqa: BLE001 - no catalogue on this install: only learned Styles
        pass
    for style in styles(looks_root):
        known[style['id']] = style['title']
    return known


def _register_styles(place, directory_root, works_with='footage'):
    """Give each new Style in the place an id in My Looks' styles.json (a learned Style with the same title is
    reused; a Look made without footage registers a 100% AI Style) and return the place's Style ids."""
    path = directory_root / 'styles.json'
    current = styles(directory_root)
    route = _route_fields(works_with)
    by_title = {style['title'].lower(): style['id'] for style in current}
    ids, changed = [], False
    for style in place['styles']:
        if isinstance(style, str):
            ids.append(style)
            continue
        new = style['new']
        identity = by_title.get(new['title'].lower())
        if identity is None:
            import letitedit.looks.look_place as look_place
            base = 'mine-style-' + (look_place._slug(new['title']) or 'kind')
            identity, number = base, 2
            while any(item['id'] == identity for item in current):
                identity, number = f'{base}-{number}', number + 1
            current.append({'id': identity, 'title': new['title'], 'filmed': new['filmed'], 'blurb': new['blurb'],
                            **route, 'kind': 'both', 'approved': True,
                            'personal': True, 'order': 500 + len(current)})
            by_title[new['title'].lower()] = identity
            changed = True
        ids.append(identity)
    if changed:
        directory_root.mkdir(parents=True, exist_ok=True)
        temporary = directory_root / ('styles-' + uuid.uuid4().hex + '.tmp')
        temporary.write_text(json.dumps({'format': STYLES_FORMAT, 'styles': current}, indent=2, ensure_ascii=False),
                             encoding='utf-8')
        os.replace(temporary, path)
    return list(dict.fromkeys(ids))


def reference_names(reports):
    """Names said in the reference videos (from their cached transcripts), for the place's topic guard."""
    names = set()
    try:
        import letitedit.footage.speech as speech
        import letitedit.looks.look_place as look_place
    except ImportError:
        return []
    for source in reports or []:
        try:
            video = _read(Path(source))['file'] if str(source).lower().endswith('.json') else str(source)
            words = speech.cached_words(video)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        names.update(look_place.reference_names(words or []))
    return sorted(names)


def check_place(place, reports=None):
    """The place as save would store it (new Styles not yet registered), with its soft warnings."""
    import letitedit.looks.look_place as look_place
    checked = look_place.validate(place, known_styles(), reference_names(reports))
    return {'place': checked, 'warnings': look_place.warnings(checked)}


def place_recipe(place, fits_line=None):
    """The recipe's "Where it fits" section, written from the saved place (the AI making a video reads it)."""
    import letitedit.looks.look_place as look_place
    place = look_place.content_needs(place)
    content = [device['name'] for device in place['devices'] if device['kind'] == 'content']
    lines = ['## Where it fits', fits_line or '', f"Pattern: {place['pattern']}",
             f"Footage: {place['footage']['what']}; {place['length']}, "
             f"{place['seconds'][0]:g}-{place['seconds'][1]:g} s.",
             'Format: ' + ' > '.join(section['id'] for section in place['structure']['sections']) + '.',
             ('Content-shaped (only when the words have it): ' + '; '.join(content) + '.') if content else '',
             'place.json beside this recipe holds the format, the needs and the style/content split: build the '
             'format from the new video\'s own content (letitedit-firstcut).']
    lines.extend(f'Without {need["what"]}: {need["without"]}' for need in place['needs']
                 if need.get('kind') == 'content' and need.get('without'))
    return '\n'.join(line for line in lines if line)


# A measuring step the PC refused memory: Python's MemoryError, numpy or OpenBLAS unable to allocate, Windows' "The
# paging file is too small for this operation to complete" (0x800705AF, which also stops Windows OCR from starting).
MEMORY_SHORT = re.compile(r'MemoryError|0x800705AF|paging file is too small|out of memory|not enough memory|'
                          r'unable to allocate|cannot allocate memory|memory allocation|too many memory regions', re.I)
TIMED_OUT = re.compile(r'TimeoutError|exceeded [\d.]+ seconds', re.I)
# what each measuring step of a reference learns, in the person's words
STEP_WORDS = {'captions': 'The caption style', 'typography': 'The lettering', 'font_styles': 'The font style',
              'typography_native': 'The detailed lettering', 'overlays': 'The pop-up style',
              'overlay_motion': 'How the pop-ups move', 'layout_speed': 'The pace of layout changes',
              'speed': 'The speed ramping', 'native_visual': 'The picture-effect style',
              'camera': 'The camera movement', 'sound': 'The sound'}
_RAW_ERROR = re.compile(r'Traceback \(most recent call last\)|File "|[A-Za-z]:[\\/]|\b\w+(?:Error|Exception|Unavailable)\b|'
                        r'0x[0-9A-Fa-f]{6,}')


def memory_short(text):
    """True when a step's error says the PC ran short of memory."""
    return bool(MEMORY_SHORT.search(str(text or '')))


def plain_limitation(part, message):
    """One plain sentence for the person about a measuring step that failed: what wasn't learned, why, and what they
    can do. The technical error stays in the reference's report and its step-errors.log."""
    what = STEP_WORDS.get(part) or ('The ' + str(part).replace('_', ' ')).strip()
    text = str(message or '')
    if memory_short(text):
        why = 'the PC ran short of memory. Learn again with fewer programs open.'
    elif TIMED_OUT.search(text):
        why = 'it took longer than the time it is given. Learn again when the PC is less busy.'
    else:
        why = 'something went wrong while measuring it. The rest of the Look is ready to use.'
    return f"{what} wasn't learned: {why}"


def plain_limitations(items):
    """The limitations a person sees, each in plain words: a raw step error ('<part> was not learned: <error>', as
    Looks saved before plain words kept them) becomes its plain sentence, and any other line carrying a traceback,
    a file path or an exception name becomes a plain sentence too. Returns (plain lines, the technical lines they
    replaced)."""
    plain, details = [], []
    for item in items or []:
        item = str(item)
        raw = re.match(r'(\w+) was not learned: (.*)', item, re.S)
        if raw:
            plain.append(plain_limitation(raw.group(1), raw.group(2)))
            details.append(item)
        elif _RAW_ERROR.search(item):
            plain.append('Part of this Look was not learned: something went wrong while measuring it. '
                         'The rest of the Look is ready to use.')
            details.append(item)
        else:
            plain.append(item)
    return list(dict.fromkeys(plain)), details


def prepare(reports):
    if not isinstance(reports, list) or not 1 <= len(reports) <= 3:
        raise ValueError('reports must contain one to three importer report.json paths')
    from letitedit.looks.style_import_write import facts, merge
    from letitedit.looks.style_import_typography import learning_evidence
    loaded, provenance = [], []
    for source in reports:
        path = Path(source).resolve(strict=True)
        report = _read(path)
        duration = report.get('duration_s') if isinstance(report, dict) else None
        if (type(duration) not in (int, float) or not math.isfinite(duration)
                or duration <= 0 or not isinstance(report.get('file'), str) or not report['file']):
            raise ValueError(f'{path}: expected an importer report with file and positive duration_s')
        report.setdefault('kind', 'short' if duration <= 180 else 'long')
        report.setdefault('folder', str(path.parent))
        loaded.append(report)
        provenance.append({'report': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'file': report['file'], 'duration_s': duration,
                           'facts': facts(report), 'pictures': report.get('pictures', {}),
                           'typography': learning_evidence(report)})
        if report.get('learned_sound') is not None:
            from letitedit.looks.learned_sound import validate
            provenance[-1]['sound'] = validate(report['learned_sound'])
        if report.get('shot_sources') is not None:
            import letitedit.looks.style_import_sources as style_import_sources
            provenance[-1]['sources'] = style_import_sources.validate(report['shot_sources'], [report])
        if report.get("lighting") is not None:
            import letitedit.looks.lighting as lighting
            provenance[-1]["lighting"] = lighting.validate(report["lighting"], [report])
        provenance[-1]['limitations'] = [plain_limitation(part, message)
                                        for part, message in report.get('errors', {}).items()]
        if report.get('errors'):
            # the technical cause of each, for the AI; the full text is in the reference's step-errors.log
            provenance[-1]['errors'] = dict(report['errors'])
            if report.get('errors_log'):
                provenance[-1]['errors_log'] = report['errors_log']
        if report.get('typography', {}).get('partial'):
            provenance[-1]['limitations'].append('Typography detail was only partly learned within its analysis budget.')
    from letitedit.looks.style_import_visual import from_reports
    import letitedit.looks.style_import_sources as style_import_sources
    return {'references': provenance, 'merged': merge(loaded), 'visual': from_reports(loaded),
            'sources': style_import_sources.from_reports(loaded),
            'notice': 'Measurements are estimates. Frame observations and limitations are separate.'}


def _project_part(package):
    """A Look made from a finished project (package.project: the project-evidence.json letitedit_learn(action=
    'project') wrote): what is kept beside the recipe as project.json, with the person's own rules (package.rules,
    checked against what the project recorded them saying). None for a Look learned from videos alone."""
    if not package.get('project'):
        if package.get('rules'):
            raise ValueError('rules come from a finished project: give package.project (letitedit_learn action project)')
        return None
    import letitedit.looks.project_look as project_look
    evidence = _read(Path(package['project']))
    if not isinstance(evidence, dict) or evidence.get('format') != project_look.FORMAT:
        raise ValueError(f'project must be the project-evidence.json of letitedit_learn(action="project")')
    version = evidence.get('version') or {}
    if not version.get('file'):
        raise ValueError('that project has no exported video yet: export it, then make the Look from the export')
    measured = [str(Path(_read(Path(report)).get('file', '')).resolve()).lower() for report in package.get('reports') or []]
    if str(Path(version['file']).resolve()).lower() not in measured:
        raise ValueError('reports must include the importer report of the version the Look is made from '
                         f'({Path(version["file"]).name}): its pictures and sound are measured from that video')
    rules = project_look.check_rules(evidence['project'], package.get('rules'))
    from letitedit.looks.product_knowledge import validate as validate_knowledge
    for rule in rules:
        validate_knowledge(rule['words'], 'rule')
    exact = evidence.get('exact')
    return {'format': project_look.FORMAT, 'basis': {
                'exact': 'exact (read from the timeline the video was exported from)' if exact else None,
                'measured': 'visual.json, sound.json, sources.json, lighting.json and evidence.json: measured from '
                            'the exported video, as Learn measures any video'},
            'version': {key: version.get(key) for key in ('file', 'made', 'final', 'matched_by', 'note')},
            'other_versions': len(evidence.get('other_versions') or []),
            'exact': exact, 'provenance': evidence.get('provenance'), 'route': evidence.get('route'),
            'made_with': evidence.get('made_with'), 'rules': rules}


def _section(text, heading):
    """The whole `heading` section of a recipe (its heading line included, ends trimmed), or None."""
    if not text or heading not in text:
        return None
    section = heading + text.split(heading, 1)[1]
    following = section.find('\n## ')
    return (section[:following] if following >= 0 else section).strip()


class _Previous:
    """The revision a save starts from. A part the save does not change is carried over from it exactly (its file
    byte for byte, its recipe section word for word) instead of being written again by today's code."""

    def __init__(self, directory, current):
        self.folder = directory / 'revisions' / current['revision'] if current else None
        recipe = self.file('recipe.md')
        self.recipe = recipe.read_text(encoding='utf-8') if recipe else None
        evidence = self.file('evidence.json')
        self.reports = ([(item.get('report'), item.get('sha256')) for item in _read(evidence).get('references', [])]
                        if evidence else None)

    def file(self, name):
        path = self.folder / name if self.folder else None
        return path if path is not None and path.is_file() else None

    def read(self, name):
        path = self.file(name)
        return _read(path) if path else None

    def same(self, value, name):
        """True when `value` is what this revision saved as `name`."""
        path = self.file(name)
        return (value is not None and path is not None
                and json.loads(json.dumps(value, ensure_ascii=False, default=str)) == _read(path))

    def same_reports(self, references):
        """True when the save measures the same report files, unchanged, as this revision did."""
        return self.reports is not None and self.reports == [(item['report'], item['sha256']) for item in references]

    def part(self, version, name, value, heading, dump, section, unchanged=True):
        """Writes part `name` into the new revision and returns its recipe section: the previous revision's file and
        section when the part is unchanged, else `dump(value)` and `section()`."""
        kept = _section(self.recipe, heading) if unchanged and self.same(value, name) else None
        if kept is not None:
            shutil.copyfile(self.file(name), version / name)
            return kept
        (version / name).write_text(dump(value), encoding='utf-8')
        return section()


SOUND_SECTION = ('## Measured sound profile\nThe sibling `sound.json` carries measured music and effect '
                 'evidence, licensed-library audio matches and uncertainty. At the sound pass, read it and '
                 'use `letitedit_learn(action="sound_plan", reference=<sound.json>, result=<project>, '
                 'package={duration_s, anchors:[{at,role}], voice_dbfs, audition:true})`. '
                 'Anchors belong to this story: broll entrances, emphasis, reveals, swells, drops and stop; '
                 'never copy reference timestamps. Plan/apply its soundtrack_request with letitedit_soundtrack '
                 'and apply its effect changes once with letitedit_timeline_apply. Unconfirmed effects are '
                 'auditions, not measured reference truth. Check stems and short listening clips; the person '
                 'judges musical character, masking and taste. Missing assets mean re-match locally, not download. When '
                 'sound.json has a `synced` block, the same plan returns `synced_sounds`: an `{op: fx, '
                 'sync_sounds}` that places its clicks on transitions and ticks on caption words once the '
                 'captions are on the timeline.')


def _carry_lighting(previous, version, recipe):
    """The recipe with the previous revision's Measured lighting and Measured grade sections, and its lighting.json
    and grade.json (when it had one), carried over unchanged."""
    import letitedit.looks.lighting as lighting
    recipe = lighting.without_section(lighting.without_section(recipe, '## Measured lighting'), '## Measured grade')
    for name in ('lighting.json', 'grade.json'):
        if previous.file(name):
            shutil.copyfile(previous.file(name), version / name)
    for heading in ('## Measured lighting', '## Measured grade'):
        kept = _section(previous.recipe, heading)
        if kept:
            recipe += '\n\n' + kept
    return recipe


def settings_for_save(package, current, directory):
    """Carry settings and their path base across revisions; private packs stay private."""
    from letitedit.looks import look_settings
    identity = _identity(package.get('id'))
    settings = package.get('settings')
    if 'settings' not in package and current:
        settings_path = Path(directory) / 'revisions' / current['revision'] / 'settings.json'
        if not settings_path.is_file():
            settings_path = Path(directory) / 'settings.json'
        if settings_path.is_file():
            settings = look_settings.read(settings_path)
            settings['asset_root'] = look_settings.resolve_path(settings.get('asset_root', '.'), settings_path.parent)
            settings['files'] = {key: look_settings.resolve_path(value, settings_path.parent)
                                 for key, value in settings.get('files', {}).items()}
    if settings is not None:
        settings = json.loads(json.dumps(look_settings.validate(settings), allow_nan=False))
        if settings['id'] != identity:
            raise ValueError('Look settings id must match the saved Look')
    private = ((current or {}).get('private') is True or identity in look_settings.private_ids()
        or (settings is not None and look_settings.is_private(settings)))
    share = package.get('share', (settings or {}).get('share', (current or {}).get('share', True) is not False))
    if not isinstance(share, bool):
        raise ValueError('share is true or false')
    if private:
        share = False
    if settings is not None:
        settings['share'] = share
        if 'title' in package:
            settings['values'].update(name=package['title'], label=package['title'])
        if private:
            settings['private'] = True
    return settings, share, private


def save(package, expected_revision=None):
    """A new revision of a learned Look. A part the package leaves out (lighting and its grade, visual, sound,
    sources, place and fits, graphic kit, project, Theme, boxes, works_with, sharing, own media) is carried over from
    the revision it starts from exactly; a part given (or newly measured in changed reports) is written anew."""
    if not isinstance(package, dict):
        raise ValueError('package must be an object')
    package = dict(package)
    identity = _identity(package.get('id'))
    for key in ('title', 'line', 'needs', 'recipe'):
        if not isinstance(package.get(key), str) or not package[key].strip():
            raise ValueError(f'{key} must be nonempty text')
    evidence = prepare(package.get('reports'))
    observations = package.get('observations')
    if not isinstance(observations, list) or not observations:
        raise ValueError('observations must record the AI own frame inspection')
    seen = set()
    for observation in observations:
        if not isinstance(observation, dict):
            raise ValueError('each observation must be an object')
        reference, at = observation.get('reference'), observation.get('at_s')
        if type(reference) is not int or not 0 <= reference < len(evidence['references']):
            raise ValueError('observation reference is a zero-based report index')
        if (type(at) not in (int, float) or not math.isfinite(at)
                or not 0 <= at < evidence['references'][reference]['duration_s']):
            raise ValueError('observation at_s must lie inside its reference')
        if not all(isinstance(observation.get(key), str) and observation[key].strip()
                   for key in ('part', 'observation')):
            raise ValueError('observation needs part and observation text')
        seen.add(reference)
    if seen != set(range(len(evidence['references']))):
        raise ValueError('every reference needs an own frame observation')
    limitations = package.get('limitations')
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        raise ValueError('limitations must be a list of text')
    limitations = list(dict.fromkeys(limitations + [item for reference in evidence['references']
                                                    for item in reference.get('limitations', [])]))
    works = package.get('works_with', 'footage')
    if works not in ('footage', 'both', 'no-footage'):
        raise ValueError('invalid works_with')
    from letitedit.looks.looks import resolve_asks
    problems = []
    asks = package.get('asks', [])
    if not isinstance(asks, list):
        raise ValueError('asks must be a list')
    asks = resolve_asks({'id': identity, 'asks': asks}, None, problems)
    if problems:
        raise ValueError('; '.join(problems))
    theme = package.get('theme')
    if theme is not None and (not isinstance(theme, dict) or theme.get('kind') not in ('kit', 'film')
                              or not all(isinstance(theme.get(key), str) and theme[key].strip()
                                         for key in ('title', 'recipe'))):
        raise ValueError('theme needs kind kit|film, title and recipe text')
    from letitedit.looks.product_knowledge import validate as validate_knowledge, LEARNED_RECIPE_WORDS
    for key in ('title', 'line', 'needs'):
        validate_knowledge(package[key], key)
    for ask in asks:
        for key in ('role', 'label', 'hint', 'instead'):
            validate_knowledge(ask.get(key, ''), f'Ask {key}')
    if theme:
        validate_knowledge(theme['title'], 'Theme title')
        validate_knowledge(theme['recipe'], 'Theme recipe', LEARNED_RECIPE_WORDS)
    directory = root() / identity
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / '.save-lock'
    from letitedit.looks.look_migration import save_lock
    lease = save_lock(directory)
    try:
        lease.__enter__()
    except FileExistsError:
        raise ValueError('this Look is being saved; retry after the other save finishes') from None
    temporary = directory / ('look-' + uuid.uuid4().hex + '.tmp')
    version = None
    published = False
    try:
        pointer = directory / 'look.json'
        current = _read(pointer) if pointer.exists() else None
        if (current or {}).get('revision') != expected_revision:
            raise ValueError('revision changed; read the Look and supply its current expected_revision')
        previous = _Previous(directory, current)
        theme_carried = False
        if current:      # left out: carried over as the revision saved them
            if 'works_with' not in package:
                works = package['works_with'] = current.get('works_with', 'footage')
            if 'asks' not in package:
                asks = package['asks'] = current.get('asks', [])
            if 'theme' not in package and current.get('theme') and previous.file('theme.md'):
                theme = {**current['theme'], 'recipe': previous.file('theme.md').read_text(encoding='utf-8')}
                package['theme'], theme_carried = theme, True
        if package.get("lighting_only"):
            import letitedit.looks.lighting as lighting
            evidence = lighting.preserve_evidence(package, current, directory)
        elif previous.same_reports(evidence['references']):
            # the same, unchanged reports: their measured facts as the revision saved them, not today's re-reading
            kept = previous.read('evidence.json')
            evidence.update({key: kept[key] for key in ('references', 'merged') if key in kept})
            limitations = list(dict.fromkeys(package['limitations'] + [
                item for reference in evidence['references'] for item in reference.get('limitations', [])]))
        import letitedit.looks.graphic_kit as graphic_kit
        kit = graphic_kit.revision_kit(package, current, directory)
        previous_line = (current or {}).get('fits_line') or (
            (current or {}).get('fits') if isinstance((current or {}).get('fits'), str) else None)
        fits = package.get('fits') if 'fits' in package else previous_line
        if fits is not None:
            if not isinstance(fits, str) or not re.match(r'(?i)fits videos that\s+\S', fits.strip()):
                raise ValueError('fits is plain words starting "Fits videos that ..." (the format of the reference)')
            fits = ' '.join(fits.split())
            validate_knowledge(fits, 'fits')
        if package.get('graphic_kit') is not None and not fits:
            raise ValueError('a saved graphic kit needs fits: "Fits videos that ..." in plain words, the format '
                             'of the reference (what the video does), so the Look is offered where it fits')
        import letitedit.looks.look_place as look_place
        place, place_warnings = None, []
        if package.get('place') is not None:
            place = look_place.validate(package['place'], known_styles(), reference_names(package.get('reports')))
            place_warnings = look_place.warnings(place)
            if place['role'] in ('theme', 'both') and not theme:
                raise ValueError('place role says the reference is a Theme too: save its theme ({kind, title, recipe})')
            if place['role'] == 'look' and theme:
                raise ValueError('place role is look but this Look has a Theme: make the role both, or remove the '
                                 'Theme with theme: null' if theme_carried else
                                 'place role is look but a Theme was written: make the role both, or leave the Theme out')
        elif 'place' not in package and current:
            previous_place = directory / 'revisions' / current['revision'] / 'place.json'
            if previous_place.is_file():
                place = _read(previous_place)
        if package.get('graphic_kit') is not None and place is None:
            raise ValueError('a saved graphic kit needs place: where the Look sits in letitedit, its format and what '
                             'it needs from a new video (letitedit-learn, Where it fits)')
        style_ids = _register_styles(place, root(), works) if place is not None else None
        sound = package.get('sound')
        if 'sound' not in package and current:
            previous_sound = directory / 'revisions' / current['revision'] / 'sound.json'
            if previous_sound.is_file():
                sound = _read(previous_sound)
        if sound is not None:
            from letitedit.looks.learned_sound import validate
            validate(sound)
        from letitedit.looks.style_import_visual import validate as validate_visual, recipe as visual_recipe
        visual = package.get('visual')
        if 'visual' not in package and previous.same_reports(evidence['references']) and previous.file('visual.json'):
            visual = previous.read('visual.json')
        elif 'visual' not in package:
            prepared = evidence['visual']
            if any(source.get('native_effects') or source.get('review') for source in prepared['references']):
                visual = prepared
            elif current:
                previous_visual = directory / 'revisions' / current['revision'] / 'visual.json'
                if previous_visual.is_file():
                    visual = _read(previous_visual)
        if visual is not None:
            visual = validate_visual(visual, evidence['references'])
        evidence['visual'] = visual
        import letitedit.looks.style_import_sources as style_import_sources
        sources = package.get('sources')
        if ('sources' not in package and previous.same_reports(evidence['references'])
                and previous.file('sources.json')):
            sources = previous.read('sources.json')
        elif 'sources' not in package:
            if any(reference.get('sources') for reference in evidence['references']):
                sources = evidence['sources']
            elif current:
                previous_sources = directory / 'revisions' / current['revision'] / 'sources.json'
                if previous_sources.is_file():
                    sources = _read(previous_sources)
            if sources is None and not package.get('lighting_only'):
                sources = evidence['sources']
        if sources is not None:
            sources = style_import_sources.validate(sources, evidence['references'])
        evidence['sources'] = sources
        import letitedit.looks.own_media as own_media_module
        if 'own_media' in package:
            own_media = own_media_module.validate(package['own_media'])
        else:
            own_media = (current or {}).get('own_media')
        if 'share' in package and not isinstance(package['share'], bool):
            raise ValueError('share is true or false (false: this Look is never sent to letitedit)')
        settings, share, private = settings_for_save(package, current, directory)
        import letitedit.looks.lighting as lighting
        if ("lighting" not in package and not package.get("lighting_only") and previous.file("lighting.json")
                and previous.same_reports(evidence["references"])):
            package["lighting"] = previous.read("lighting.json")
        lighting_profiles = lighting.for_save(package, current, directory, evidence["references"])
        evidence["lighting"] = lighting_profiles
        revision = uuid.uuid4().hex
        version = directory / 'revisions' / revision
        version.mkdir(parents=True)
        if settings is not None:
            (version / 'settings.json').write_text(json.dumps(settings, indent=2, ensure_ascii=False,
                                                             allow_nan=False), encoding='utf-8')
        recipe = re.sub(r'(?m)^## Known limits\n.*?(?=^## |\Z)', '',
                        package['recipe'], flags=re.S).rstrip()
        if '## Measured visual profile' in recipe:
            before, section = recipe.split('## Measured visual profile', 1)
            following = section.find('\n## ')
            recipe = before.rstrip() + (section[following:] if following >= 0 else '')
        def dump(value):
            return json.dumps(value, indent=2, allow_nan=False)
        if visual is not None:
            recipe += '\n\n' + previous.part(version, 'visual.json', visual, '## Measured visual profile', dump,
                                              lambda: visual_recipe(visual))
        if '## Measured sound profile' in recipe:
            before, section = recipe.split('## Measured sound profile', 1)
            following = section.find('\n## ')
            recipe = before.rstrip() + (section[following:] if following >= 0 else '')
        if sound is not None:
            recipe += '\n\n' + previous.part(version, 'sound.json', sound, '## Measured sound profile', dump,
                                              lambda: SOUND_SECTION)
        if (lighting_profiles is not None and not package.get('lighting_only')
                and previous.same(lighting_profiles, 'lighting.json')
                and _section(previous.recipe, '## Measured lighting')):
            recipe = _carry_lighting(previous, version, recipe)       # unchanged lighting: its words and grade too
        else:
            recipe = lighting.save_revision(version, recipe, lighting_profiles)
        recipe = lighting.without_section(recipe, '## Graphic kit')
        recipe = lighting.without_section(recipe, '## Where it fits')
        if place is not None:
            place = {**place, 'styles': style_ids}
            recipe += '\n\n' + previous.part(version, 'place.json', place, '## Where it fits',
                                              lambda value: json.dumps(value, indent=2, ensure_ascii=False),
                                              lambda: place_recipe(place, fits), unchanged=fits == previous_line)
        elif fits:
            kept = (_section(previous.recipe, '## Where it fits')
                    if fits == previous_line and not previous.file('place.json') else None)
            recipe += '\n\n' + (kept or '## Where it fits\n' + fits)
        if kit is not None:
            recipe += '\n\n' + previous.part(version, 'graphic-kit.json', kit, '## Graphic kit', dump,
                                              lambda: graphic_kit.description(kit))
        recipe = lighting.without_section(recipe, '## Shot sources and overlays')
        if sources is not None:
            recipe += '\n\n' + previous.part(version, 'sources.json', sources, '## Shot sources and overlays', dump,
                                              lambda: style_import_sources.recipe(sources))
        project = _project_part(package)
        if project is not None:
            recipe = lighting.without_section(recipe, '## Your own rules')
            if '## Exact values from the finished video' not in recipe:
                import letitedit.looks.project_look as project_look
                recipe += '\n\n' + project_look.recipe_section(project)
            if project.get('rules'):
                import letitedit.looks.project_look as project_look
                recipe += '\n\n' + project_look.rules_section(project['rules']).rstrip()
            (version / 'project.json').write_text(json.dumps(project, indent=1, ensure_ascii=False, default=str),
                                                  encoding='utf-8')
        elif 'project' not in package and previous.file('project.json'):
            shutil.copyfile(previous.file('project.json'), version / 'project.json')
        recipe += '\n\n## Known limits\n' + ''.join(
            f'- {item}\n' for item in limitations)
        validate_knowledge(recipe, 'Look recipe', LEARNED_RECIPE_WORDS)
        (version / 'recipe.md').write_text(recipe, encoding='utf-8')
        if theme:
            (version / 'theme.md').write_text(theme['recipe'], encoding='utf-8')
        evidence.update(observations=observations, limitations=limitations)
        (version / 'evidence.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding='utf-8')
        saved = {'format': FORMAT, 'id': identity, 'revision': revision,
                 'title': package['title'], 'line': package['line'], 'needs': package['needs'],
                 'works_with': works, 'asks': asks, **({'fits_line': fits} if fits else {}),
                 **({'fits': style_ids, 'kind': place['length']} if place is not None else {}),
                 'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 'theme': {'kind': theme['kind'], 'title': theme['title']} if theme else None,
                 **({'private': True} if private else {}),
                 **({'own_media': own_media} if own_media else {}), **({} if share else {'share': False})}
        temporary.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, pointer)
        published = True
        reply = {**saved, 'recipe': str(version / 'recipe.md'), 'evidence': str(version / 'evidence.json')}
        if place is not None:
            reply['place'] = str(version / 'place.json')
        else:
            place_warnings.append('no place yet: save where the Look sits in letitedit, its format and what it '
                                  'needs from a new video (letitedit-learn, Where it fits)')
        if place_warnings:
            reply['warnings'] = place_warnings
        _share(directory.parent)
        if (own_media or {}).get('broll'):
            own_media_module.kick(identity, directory.parent)     # its picture index, in the background
        return reply
    finally:
        if version is not None and not published:
            shutil.rmtree(version)
        temporary.unlink(missing_ok=True)
        lease.__exit__(None, None, None)


def _share(looks_root=None):
    """Starts sending the Look to letitedit in the background when sharing is on (bridge/look_share.py); a save never
    waits on it or fails because of it."""
    try:
        import letitedit.looks.look_share as look_share
        look_share.kick(looks_root)
    except Exception:
        pass


def _retitle(directory, saved, title, line=None):
    """A new revision, a copy of the current one with the Look's name (and its recipe's heading) changed; the earlier
    revisions stay. Returns the new look.json record (not yet published) and the new revision's folder."""
    previous = directory / 'revisions' / saved['revision']
    settings, _, _ = settings_for_save({'id': saved['id'], 'title': title}, saved, directory)
    revision = uuid.uuid4().hex
    version = directory / 'revisions' / revision
    try:
        shutil.copytree(previous, version)
        recipe_path = version / 'recipe.md'
        recipe = recipe_path.read_text(encoding='utf-8-sig')
        recipe = re.sub(r'(?m)^# [^\n]+', lambda match: '# ' + title, recipe, count=1)
        recipe_path.write_text(recipe, encoding='utf-8')
        if settings is not None:
            (version / 'settings.json').write_text(json.dumps(settings, indent=2, ensure_ascii=False,
                                                             allow_nan=False), encoding='utf-8')
    except BaseException:
        if version.exists():
            shutil.rmtree(version)
        raise
    updated = {**saved, 'title': title, 'revision': revision,
               'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if line:
        updated['line'] = line
    return updated, version


def finish_learning(identity, title=None, looks_root=None):
    """Checks a learned Look is complete when its learning ends. The AI names the Look when it saves it; a title given
    here (an editor from before the AI named Looks sends the person's) renames it, as before."""
    directory = (Path(looks_root) if looks_root else root()) / _identity(identity)
    pointer = directory / 'look.json'
    lock = directory / '.save-lock'
    from letitedit.looks.look_migration import save_lock
    lease = save_lock(directory)
    lease.__enter__()
    version = None
    temporary = directory / f'.{uuid.uuid4().hex}.json'
    published = False
    try:
        saved = _read(pointer)
        previous = directory / 'revisions' / saved['revision']
        evidence = _read(previous / 'evidence.json')
        if not (previous / 'place.json').is_file():
            raise ValueError('this Look has no place yet: save where it sits in letitedit, its format and what it '
                             'needs from a new video (letitedit-learn, Where it fits), then finish')
        if title and title.strip() and saved['title'] != title.strip():
            saved, version = _retitle(directory, saved, title.strip())
            temporary.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, pointer)
            published = True
            _share(directory.parent)
        return {**saved, 'limitations': evidence.get('limitations', []),
                'step_errors': [f'{part}: {message}' for reference in evidence.get('references') or []
                                if isinstance(reference, dict) and isinstance(reference.get('errors'), dict)
                                for part, message in reference['errors'].items()],
                'error_logs': [reference['errors_log'] for reference in evidence.get('references') or []
                               if isinstance(reference, dict) and reference.get('errors_log')]}
    finally:
        if version is not None and not published:
            shutil.rmtree(version)
        temporary.unlink(missing_ok=True)
        lease.__exit__(None, None, None)


NAME_LIMIT = 60


def rename(identity, title, looks_root=None, line=None):
    """The person renames one of their own Looks (its card's Rename). Only the name (and, when given, its one-line
    description) changes, in a new revision; the earlier revisions and everything else stay as they are."""
    title = ' '.join(str(title or '').split())
    if not title:
        raise ValueError('a Look needs a name')
    if len(title) > NAME_LIMIT:
        raise ValueError(f"a Look's name is at most {NAME_LIMIT} characters")
    line = ' '.join(str(line or '').split()) or None
    directory = (Path(looks_root) if looks_root else root()) / _identity(identity)
    pointer = directory / 'look.json'
    if not pointer.is_file():
        raise ValueError(f'no Look {identity} in {directory.parent}')
    lock = directory / '.save-lock'
    from letitedit.looks.look_migration import save_lock
    lease = save_lock(directory)
    try:
        lease.__enter__()
    except FileExistsError:
        raise ValueError('this Look is being saved; try again in a moment') from None
    version = None
    temporary = directory / f'.{uuid.uuid4().hex}.json'
    published = False
    try:
        saved = _read(pointer)
        if saved['title'] == title and (line is None or saved.get('line') == line):
            return saved
        saved, version = _retitle(directory, saved, title, line)
        temporary.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, pointer)
        published = True
        _share(directory.parent)
        return saved
    finally:
        if version is not None and not published:
            shutil.rmtree(version)
        temporary.unlink(missing_ok=True)
        lease.__exit__(None, None, None)


# The example video on a learned Look's card: a few seconds of the person's own video, kept in the Look's folder
# beside its revisions (so every revision keeps it), shown only on this PC and never shipped or synced.
EXAMPLE_FOLDER = 'example'
EXAMPLE_SECONDS = 8.0
TALL, WIDE = 9 / 16, 16 / 9


def example(directory):
    """The card fields of a Look's example clips: preview/poster (tall) and preview_long/poster_long (wide)."""
    folder = Path(directory) / EXAMPLE_FOLDER
    try:
        record = _read(folder / 'example.json')
    except (OSError, ValueError):
        return {}
    fields = {}
    for clip in record.get('clips') or [] if isinstance(record, dict) else []:
        if not isinstance(clip, dict) or not clip.get('file') or not clip.get('poster'):
            continue
        video, poster = folder / str(clip['file']), folder / str(clip['poster'])
        if not (video.is_file() and poster.is_file()):
            continue
        suffix = '_long' if clip.get('shape') == 'wide' else ''
        fields.setdefault('preview' + suffix, str(video))
        fields.setdefault('poster' + suffix, str(poster))
    if fields:
        fields['example'] = {'mine': True, 'source': record.get('source') or 'reference',
                             'note': record.get('note') or 'An example from your own video, only on this PC.'}
    return fields


def _picture(video):
    """(width, height, seconds, has sound) of a video, its rotation applied."""
    from letitedit.core import media
    info = media.probe(str(video))
    stream = next((item for item in info.get('streams') or [] if item.get('codec_type') == 'video'), None)
    if not stream:
        raise ValueError(f'{video}: no picture')
    width, height = int(stream.get('width') or 0), int(stream.get('height') or 0)
    rotation = 0
    for side in stream.get('side_data_list') or []:
        if side.get('rotation') is not None:
            rotation = int(side['rotation'])
    rotation = rotation or int((stream.get('tags') or {}).get('rotate') or 0)
    if abs(rotation) % 180 == 90:
        width, height = height, width
    if width <= 0 or height <= 0:
        raise ValueError(f'{video}: no picture size')
    seconds = float((info.get('format') or {}).get('duration') or 0)
    sound = any(item.get('codec_type') == 'audio' for item in info.get('streams') or [])
    return width, height, seconds, sound


def make_example(identity, looks_root=None, source=None, start_s=None, seconds=EXAMPLE_SECONDS,
                 origin='reference', shape=None, note=None):
    """Cuts a few seconds of the person's own video into the Look's example clip: by default from its first reference
    still on this PC, about a third of the way in. A picture taller than wide becomes the Short preview (9:16), a wider
    one the YouTube preview (16:9), cropped around the centre where its shape differs. Replaces an earlier example of
    the same shape; a small encode (two threads, a few seconds of video)."""
    from letitedit.core import media
    directory = (Path(looks_root) if looks_root else root()) / _identity(identity)
    saved = _read(directory / 'look.json')
    if source is None:
        evidence = _read(directory / 'revisions' / saved['revision'] / 'evidence.json')
        found = [item['file'] for item in evidence.get('references') or []
                 if isinstance(item, dict) and isinstance(item.get('file'), str) and Path(item['file']).is_file()]
        if not found:
            raise ValueError("none of this Look's reference videos is on this PC any more")
        source = found[0]
    source = Path(source)
    if not source.is_file():
        raise ValueError(f'{source} is not on this PC')
    width, height, duration, sound = _picture(source)
    shape = shape or ('tall' if height > width else 'wide')
    if shape not in ('tall', 'wide'):
        raise ValueError('shape is tall or wide')
    want = TALL if shape == 'tall' else WIDE
    seconds = max(2.0, min(float(seconds), 20.0))
    if start_s is None:
        start_s = max(0.0, min(duration * 0.3, duration - seconds)) if duration > 0 else 0.0
    start_s = max(0.0, float(start_s))
    if width / height > want:
        crop = 'crop=trunc(ih*9/32)*2:ih' if shape == 'tall' else 'crop=trunc(ih*8/9)*2:ih'
    else:
        crop = 'crop=iw:trunc(iw*8/9)*2' if shape == 'tall' else 'crop=iw:trunc(iw*9/32)*2'
    size = '540:960' if shape == 'tall' else '960:540'
    folder = directory / EXAMPLE_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    stem = 'example-' + shape
    video, poster = folder / (stem + '.mp4'), folder / (stem + '.jpg')
    temporary_video = folder / f'.{uuid.uuid4().hex}.mp4'
    temporary_poster = folder / f'.{uuid.uuid4().hex}.jpg'
    try:
        media.run_tool([media.ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{start_s:.3f}',
                        '-t', f'{seconds:.3f}', '-i', str(source), '-vf', f'{crop},scale={size},setsar=1,fps=30',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-pix_fmt', 'yuv420p', '-threads', '2',
                        *(['-c:a', 'aac', '-b:a', '96k', '-ac', '2'] if sound else ['-an']), '-movflags', '+faststart',
                        str(temporary_video)], timeout=300)
        media.run_tool([media.ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(temporary_video),
                        '-frames:v', '1', '-q:v', '3', str(temporary_poster)], timeout=120)
        os.replace(temporary_video, video)
        os.replace(temporary_poster, poster)
    finally:
        temporary_video.unlink(missing_ok=True)
        temporary_poster.unlink(missing_ok=True)
    record_path = folder / 'example.json'
    try:
        record = _read(record_path)
    except (OSError, ValueError):
        record = {}
    clips = [clip for clip in record.get('clips') or [] if isinstance(clip, dict) and clip.get('shape') != shape]
    clips.append({'shape': shape, 'file': video.name, 'poster': poster.name, 'from': str(source),
                  'start_s': round(start_s, 3), 'seconds': round(seconds, 3), 'origin': origin,
                  'made_at': datetime.datetime.now(datetime.timezone.utc).isoformat()})
    record = {'format': 'letitedit-look-example/1', 'private': True, 'source': origin,
              'note': note or ('An example from your own reference video, only on this PC.' if origin == 'reference'
                               else 'An example made with this Look from your own footage, only on this PC.'),
              'clips': clips}
    handle = folder / f'.{uuid.uuid4().hex}.json'
    handle.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(handle, record_path)
    return {'id': identity, **example(directory)}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="The person's own Looks: rename one, or make its example clip.")
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('rename')
    one.add_argument('id')
    one.add_argument('title')
    one.add_argument('--line')
    one.add_argument('--root')
    two = commands.add_parser('example')
    two.add_argument('id')
    two.add_argument('--root')
    two.add_argument('--source')
    two.add_argument('--start', type=float)
    two.add_argument('--seconds', type=float, default=EXAMPLE_SECONDS)
    two.add_argument('--shape', choices=('tall', 'wide'))
    two.add_argument('--origin', default='reference', choices=('reference', 'own'))
    two.add_argument('--note')
    args = parser.parse_args(argv)
    try:
        if args.command == 'rename':
            result = rename(args.id, args.title, looks_root=args.root, line=args.line)
            reply = {'ok': True, 'id': result['id'], 'title': result['title'], 'revision': result['revision']}
        else:
            reply = {'ok': True, **make_example(args.id, looks_root=args.root, source=args.source, start_s=args.start,
                                                 seconds=args.seconds, origin=args.origin, shape=args.shape,
                                                 note=args.note)}
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        reply = {'ok': False, 'error': str(error)}
    print(json.dumps(reply, ensure_ascii=False))
    return 0 if reply['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
