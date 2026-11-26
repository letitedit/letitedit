"""Looks: the flavours of a Style that New video offers, read from looks\\manifest.json.

A Style is the kind of video (Talking head). A Look is one flavour of it (Clean, Big Letters Behind You...): a recipe the
AI works from (looks\\<look>\\recipe.md) plus a short preview clip and poster for the picker. Nothing here is compiled
into the editor: adding, hiding or removing a Look is an edit to looks\\manifest.json (and its folder). Only entries with
`approved: true` are offered. `looks\\` ships with the app (recipes and small previews); `tests\\`
never does.

    looks/manifest.json            format letitedit-looks/1: picker settings, styles, looks
    looks/<look>/recipe.md         the written recipe (what the viewer sees, how to make it, must-nots, what footage it needs)
    looks/<look>/preview.mp4       a small clip of the result, played in the picker (sound is the person's to switch on)
    looks/<look>/poster.jpg        its still, shown before it plays

A Look can also say what it needs from the person before it starts (T64): `asks`, a list of boxes New video shows on
one screen after the Look is chosen (kind text | files | audio; need required | recommended | optional; a role the AI
and the review use: about, show, style, voiceover, product, person...). A Style can group its Looks in `folders`
(shown first, each opening to its Looks) and a folder can carry default `asks` that its Looks merge over by id. A Look
says `works_with: footage | no-footage | both`; a Style whose Looks are all no-footage needs no footage folder.
A Look can carry `pace` (the gate's pace checks for its videos, as a brief's `pace` does; the brief still wins), `read_also`
(files the AI reads with the recipe, relative to the install), `recipe_shared` (a file in this folder that several Looks' recipes
share, read after the Look's own text wherever the recipe is read) and `sample` (what made its preview: model, effort, date, story).
None of this needs an editor build: it is all in looks\\manifest.json.

    python looks.py --list-json    the picker's list (catalog()), as JSON
    python looks.py --read <look>  one Look in full: its card and recipe
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
from letitedit.looks import catalog as _catalog  # noqa: E402  (where Styles, Looks and Themes come from)
_ROOT = Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT))
LOOKS_ROOT = Path(os.environ.get('LETITEDIT_LOOKS') or (_ROOT / 'looks'))
FORMAT = 'letitedit-looks/1'
# the brief's `look` field takes one of these besides a Look's id
NO_LOOK = 'none'    # the Style has no Looks, or the person chose another Style
AI_PICKS = 'auto'   # "Let the AI pick": the AI chooses one of the Looks and says which and why


def _manifest() -> dict:
    """The shipped manifest with the person's learned Looks added (letitedit.looks.catalog knows where both are)."""
    return _catalog.merged(LOOKS_ROOT, {'format': FORMAT, 'picker': {}, 'styles': [], 'looks': []})


def _file(rel: str | None) -> str | None:
    """A manifest path made absolute, or None when it is missing (a card is shown without a preview, never hidden)."""
    if not rel:
        return None
    p = (LOOKS_ROOT / rel)
    return str(p) if p.is_file() else None


ASK_KINDS = ('text', 'files', 'audio')
ASK_NEEDS = ('required', 'recommended', 'optional')
WORKS_WITH = ('footage', 'no-footage', 'both')


def _ask(raw, problems: list, where: str) -> dict | None:
    """One box, checked. A box that can't be shown is left out and listed under `problems`; the Look stays offered."""
    if not isinstance(raw, dict) or not raw.get('id'):
        problems.append(f'{where}: an ask without an id')
        return None
    kind, need = raw.get('kind', 'text'), raw.get('need', 'optional')
    if kind not in ASK_KINDS or need not in ASK_NEEDS or not raw.get('role') or not raw.get('label'):
        problems.append(f"{where}: ask {raw.get('id')!r} needs a kind in {ASK_KINDS}, a need in {ASK_NEEDS}, a role and a label")
        return None
    return {'id': str(raw['id']), 'kind': kind, 'need': need, 'role': str(raw['role']), 'label': str(raw['label']),
            'hint': str(raw.get('hint', '')), 'instead': str(raw.get('instead', ''))}


def resolve_asks(entry: dict, folder: dict | None, problems: list | None = None) -> list:
    """A Look's boxes: its folder's default asks, then its own merged over them by id (an own entry replaces the
    default; {"id": ..., "remove": true} drops a default)."""
    problems = problems if problems is not None else []
    out: dict = {}
    for source, where in ((folder, f"folder {folder.get('id')}" if folder else ''), (entry, f"look {entry.get('id')}")):
        for raw in (source or {}).get('asks') or []:
            if isinstance(raw, dict) and raw.get('remove') and raw.get('id'):
                out.pop(str(raw['id']), None)
                continue
            a = _ask(raw, problems, where)
            if a:
                out[a['id']] = a
    return list(out.values())


def fits(entry: dict) -> list:
    """The kinds of video (Style ids) a Look fits, its main one first: its `fits` list, with its single `style` (the
    only field older entries, saved projects and My Looks have) read as the first fit when `fits` leaves it out."""
    raw = entry.get('fits')
    out = list(dict.fromkeys(str(x) for x in raw if isinstance(x, str) and x)) if isinstance(raw, list) else []
    style = entry.get('style')
    if isinstance(style, str) and style and style not in out:
        out.insert(0, style)
    return out


def _seconds(value) -> float:
    """Where in its preview a poster was taken (seconds); 0 when not given."""
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def card(entry: dict, folder: dict | None = None, problems: list | None = None) -> dict:
    """One Look as the picker and the AI see it."""
    works = entry.get('works_with') or 'footage'
    kinds = fits(entry)
    return {'id': entry['id'], 'style': kinds[0] if kinds else entry.get('style'), 'fits': kinds, 'label': entry.get('title') or entry.get('label') or entry['id'],
            'line': entry.get('blurb') or entry.get('line', ''), 'needs': entry.get('needs', ''), 'recipe': _file(entry.get('recipe')),
            'preview': _file(entry.get('preview')), 'poster': _file(entry.get('poster')),
            'preview_long': _file(entry.get('preview_long')), 'poster_long': _file(entry.get('poster_long')),
            'poster_s': _seconds(entry.get('poster_s')), 'poster_long_s': _seconds(entry.get('poster_long_s')),
            'folder': entry.get('folder') or '', 'works_with': works if works in WORKS_WITH else 'footage',
            'kind': entry.get('kind') if entry.get('kind') in ('short', 'long', 'both') else 'both',
            'asks': resolve_asks(entry, folder, problems), 'pace': dict(entry.get('pace') or {}),
            'sample': dict(entry.get('sample') or {}),
            'talk': entry.get('talk') if entry.get('talk') in ('natural', 'clean') else '',
            'personal': bool(entry.get('personal')), 'revision': entry.get('revision'),
            **({'private': True, 'share': False} if entry.get('private') else {}),
            'based_on': entry.get('based_on') or '',
            'sound_profile': _file(entry.get('sound_profile')),
            'visual_profile': _file(entry.get('visual_profile')),
            'source_profile': _file(entry.get('source_profile')),
            'place': _file(entry.get('place')),
            'recipe_shared': _file(entry.get('recipe_shared')),
            'read_also': [str(_ROOT / r) for r in entry.get('read_also') or [] if (_ROOT / r).is_file()],
            **_own_media(entry),
            **({'settings_only': True, 'settings_source': entry.get('settings_source')}
               if entry.get('settings_only') and entry.get('private') and entry.get('share') is False else {})}


def _own_media(entry: dict) -> dict:
    """A personal Look's own media (own_media.py): the person's footage folders for its cutaways and their intro."""
    if not isinstance(entry.get('own_media'), dict):
        return {}
    try:
        import letitedit.looks.own_media as own_media
        described = own_media.describe(entry['own_media'], entry.get('id'))
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return {}
    return {'own_media': described} if described else {}


def catalog() -> dict:
    """What New video's Style and Look pages show: the approved Styles that have Looks, each with its approved Looks
    that have a recipe (a Look without its recipe file is left out and listed under `skipped`), its folders (an
    approved folder with at least one Look) and whether it needs footage."""
    data = _manifest()
    if (LOOKS_ROOT / 'styles.json').is_file() or any(entry.get('personal') for entry in data['looks']):
        import letitedit.looks.look_choices as look_choices
        result = look_choices.catalog(_ROOT, LOOKS_ROOT, data, card)
        return {'format': FORMAT, 'root': str(LOOKS_ROOT), 'picker': data.get('picker') or {},
                'default_look': AI_PICKS, 'choices': [{'value': AI_PICKS, 'label': 'Let the AI pick'},
                                                   {'value': NO_LOOK, 'label': 'No Look'}], **result}
    folders_by_id = {f['id']: f for f in data.get('folders') or [] if f.get('id') and f.get('approved', True)}
    looks, skipped, problems = [], [], []
    for entry in data.get('looks') or []:
        if not entry.get('approved') or not entry.get('id'):
            continue
        c = card(entry, folders_by_id.get(entry.get('folder')), problems)
        (looks if c['recipe'] else skipped).append(c if c['recipe'] else {'id': c['id'], 'error': 'recipe file missing'})
    styles = []
    for s in data.get('styles') or []:
        if not s.get('approved') or not s.get('id'):
            continue
        mine = [c for c in looks if c['style'] == s['id']]
        if not mine:
            continue
        folders = []
        for f in data.get('folders') or []:
            if f.get('style') != s['id'] or not f.get('approved', True):
                continue
            inside = [c['id'] for c in mine if c['folder'] == f.get('id')]
            if inside:
                folders.append({'id': f['id'], 'label': f.get('label') or f['id'], 'line': f.get('line', ''),
                                'poster': _file(f.get('poster')), 'looks': inside})
        works = {c['works_with'] for c in mine}
        footage = 'no' if works == {'no-footage'} else 'yes' if works == {'footage'} else 'optional'
        styles.append({'id': s['id'], 'label': s.get('label') or s['id'], 'line': s.get('line', ''),
                       'filter_label': s.get('filter_label') or s.get('label') or s['id'],
                       'kind': s.get('kind') or 'both', 'footage': footage, 'folders': folders, 'looks': mine})
    return {'format': FORMAT, 'root': str(LOOKS_ROOT), 'picker': data.get('picker') or {}, 'default_look': AI_PICKS,
            'choices': [{'value': AI_PICKS, 'label': 'Let the AI pick',
                         'about': "The AI picks one of the Looks for this footage from each recipe's 'what footage it "
                                  "needs', and says which and why."},
                        {'value': NO_LOOK, 'label': 'No Look',
                         'about': 'A Style without Looks (or Let the AI decide): nothing to read.'}],
            'styles': styles, 'looks': looks, 'skipped': skipped, 'problems': problems}


def read(look_id: str) -> dict:
    """One Look in full: its card and recipe text. Raises KeyError for a Look that is not offered."""
    look_id = current_id(look_id)
    data = _manifest()
    folders = {entry['id']: entry for entry in data.get('folders', [])}
    for entry in data.get('looks', []):
        if entry.get('id') != look_id:
            continue
        c = card(entry, folders.get(entry.get('folder')))
        if not c['recipe']:
            break
        if c['id'] == look_id:
            text = Path(c['recipe']).read_text(encoding='utf-8-sig')
            if c.get('recipe_shared'):
                text += Path(c['recipe_shared']).read_text(encoding='utf-8-sig')
            # what Learn or Import a style measured beside the recipe (look_check reads the same files); a library
            # Look has only its recipe
            from letitedit.looks.look_check import MEASUREMENTS
            measured = [name for name in MEASUREMENTS if Path(c['recipe']).with_name(name).is_file()]
            return {**c, 'recipe_text': text, 'measured': measured}
    raise KeyError(f'No Look called {look_id!r}. Offered: {[c["id"] for c in catalog()["looks"]]}')


def current_id(look_id):
    """The id a Look goes by now: a Look that was renamed lists its old ids under `was`, so videos saved under one still read."""
    try:
        for entry in _manifest().get('looks') or []:
            if look_id in (entry.get('was') or []):
                return entry.get('id')
    except (OSError, ValueError):
        pass
    return look_id


def offered(look_id) -> dict | None:
    """A Look's card, or None when it isn't offered: the review asks this for a video whose Look may have gone since."""
    look_id = current_id(look_id)
    try:
        return next((c for c in catalog()['looks'] if c['id'] == look_id), None)
    except (OSError, ValueError):
        return None


def sample_sheet(look_id: str, frames: int = 8):
    """Path of a contact sheet of the Look's sample clip (frames spread over its length, 4 across), made once and kept in
    the cache; None when the Look has no sample clip or the sheet can't be made. The recipe says what the viewer sees,
    the sheet shows it."""
    import subprocess
    import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401
    card_ = read(look_id)
    clip = card_.get('preview')
    if not clip or not Path(clip).is_file():
        return None
    import hashlib
    st = Path(clip).stat()
    key = hashlib.sha1(f'{clip}{st.st_size}{st.st_mtime_ns}{frames}'.encode()).hexdigest()[:12]
    root = _paths.CODE_ROOT
    out = root / 'cache' / 'looks' / f'{look_id}-{key}.jpg'
    if out.is_file():
        return str(out)
    ffmpeg, ffprobe = root / 'app' / 'ffmpeg.exe', root / 'app' / 'ffprobe.exe'
    try:
        from PIL import Image
        dur = float(subprocess.run([str(ffprobe), '-v', 'error', '-show_entries', 'format=duration', '-of',
                                    'default=noprint_wrappers=1:nokey=1', clip], capture_output=True, text=True,
                                   timeout=30).stdout.strip())
        out.parent.mkdir(parents=True, exist_ok=True)
        tiles = []
        for k in range(frames):
            png = out.parent / f'{look_id}-{key}-{k}.png'
            subprocess.run([str(ffmpeg), '-y', '-v', 'error', '-ss', f'{dur * (k + 0.5) / frames:.2f}', '-i', clip,
                            '-frames:v', '1', '-vf', 'scale=270:-2', str(png)], check=True, timeout=60)
            tiles.append(Image.open(png).convert('RGB'))
        w, h = tiles[0].size
        cols = 4
        sheet = Image.new('RGB', (cols * w, -(-len(tiles) // cols) * h))
        for k, t in enumerate(tiles):
            sheet.paste(t, ((k % cols) * w, (k // cols) * h))
        sheet.save(out, quality=85)
        for k in range(frames):
            (out.parent / f'{look_id}-{key}-{k}.png').unlink(missing_ok=True)
        return str(out)
    except Exception:  # noqa: BLE001 - the recipe still comes back
        return None


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # the app reads UTF-8 whatever the code page
    args = sys.argv[1:]
    if args[:1] == ['--list-json']:
        sys.stdout.write(json.dumps(catalog(), ensure_ascii=False, indent=1) + '\n')
    elif args[:1] == ['--read'] and len(args) > 1:
        sys.stdout.write(json.dumps(read(args[1]), ensure_ascii=False, indent=1) + '\n')
    elif args[:1] == ['--review'] and len(args) == 4:
        import letitedit.looks.look_choices as look_choices
        try:
            result = look_choices.review_entry(_ROOT, LOOKS_ROOT, *args[1:])
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            sys.stderr.write(str(error) + '\n')
            sys.exit(1)
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + '\n')
    else:
        sys.stdout.write('usage: looks.py --list-json | --read <look>\n')
