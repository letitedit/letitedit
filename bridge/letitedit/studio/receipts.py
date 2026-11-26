"""What made a timeline resource, read from its producer's own receipt: the provenance a Short's result reports.

letitedit's producers mark what they make:
    pictures (letitedit_image)   <project stem>.letitedit/images/generated-image-NNNN[-fit-WxH].png, listed in that
                                 folder's log.jsonl
    music (letitedit_music_make) generated-music-*.wav with a sidecar <file>.json {generated, kind: music, model}
    voice (letitedit_voice)      a sidecar <file>.json {generated, kind: voice, engine}; in the model cache
                                 voice_<key>.wav beside voice_<key>.json
    dubs (letitedit_dub)         <project folder>/AI Generated/Dubs/dub-*.wav
    code scenes                  a timeline item {scene: {id, revision}} with no clip; the revision's scene.json names
                                 its pictures as file:// addresses and its page keeps a copy of each (scene_parts)
    graphics (recipes)           the files the recipe names (its params, its code's literal paths); each is read as
                                 above. A recipe whose code loads a picture from a path it builds at run time, or names
                                 a picture file that is not there, can't be traced: graphic_pictures says so.
    drawn by code                motion clips, maps, 3D and the like: a sidecar {generated, kind} with no model. Not
                                 AI-made media, unless the sidecar names a generated picture it was composed from.
                                 A map's sidecar also says its data credit (`attribution`), passed on.
Anything without a receipt is left as unknown: an unrecognised sound is never taken for library sound.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

PICTURE = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff'}
VOICE_ENGINES = {'chatterbox', 'dots-tts', 'voice'}


def _read(path):
    try:
        return Path(path).read_text(encoding='utf-8-sig')
    except (OSError, UnicodeDecodeError):
        return None


def _sidecars(p):
    return [Path(str(p) + '.json'), p.with_suffix('.json')]


def _logged(p):
    """Whether the picture tool's log in its side folder lists this file (as made or as its fitted copy)."""
    text = _read(p.parent / 'log.jsonl') or ''
    want = {str(p).lower(), str(p).replace('\\', '/').lower()}
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        for k in ('path', 'fit_path'):
            v = str(row.get(k) or '')
            if v and (v.lower() in want or v.replace('\\', '/').lower() in want):
                return True
    return False


def made(path):
    """{kind, ai_generated, source, how} for a resource a letitedit producer made, or None when nothing says so.
    how: 'receipt' (its producer's receipt says it) or 'path' (where its producer saves it)."""
    p = Path(str(path))
    low = str(p).replace('\\', '/').lower()
    if '/ai generated/dubs/' in low:
        return {'kind': 'generated_voice', 'ai_generated': True, 'source': 'letitedit_dub', 'how': 'path'}
    if (p.parent.name.lower() == 'images' and p.parent.parent.name.lower().endswith('.letitedit')
            and p.name.lower().startswith('generated-image-')):
        return {'kind': 'generated_picture', 'ai_generated': True, 'source': 'letitedit_image',
                'how': 'receipt' if _logged(p) else 'path'}
    for side in _sidecars(p):
        if side == p:
            continue
        text = _read(side)
        if not text:
            continue
        try:
            data = json.loads(text)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        kind = str(data.get('kind') or '').lower()
        if kind == 'voice' or str(data.get('engine') or '').lower() in VOICE_ENGINES or 'watermark' in data:
            return {'kind': 'generated_voice', 'ai_generated': True, 'source': 'letitedit_voice', 'how': 'receipt'}
        if not data.get('generated'):
            continue
        if kind == 'music':
            if data.get('model'):
                return {'kind': 'generated_music', 'ai_generated': True, 'source': 'ai_made', 'how': 'receipt'}
            return {'kind': 'written_music', 'ai_generated': False, 'source': 'written', 'how': 'receipt'}
        if kind == 'image':
            return {'kind': 'generated_picture', 'ai_generated': True, 'source': 'letitedit_image', 'how': 'receipt'}
        if 'generated-image-' in text.lower():        # drawn by code around a generated picture
            return {'kind': 'generated_picture', 'ai_generated': True, 'source': 'letitedit', 'how': 'receipt',
                    'composed': True}
        out = {'kind': 'drawn_scene' if p.suffix.lower() in PICTURE else 'motion_clip', 'ai_generated': False,
               'source': 'letitedit', 'how': 'receipt'}
        if data.get('attribution'):                   # a map's data credit, drawn in its picture
            out['attribution'] = str(data['attribution'])
        return out
    if p.name.lower().startswith('generated-music-'):
        return {'kind': 'generated_music', 'ai_generated': True, 'source': 'ai_made', 'how': 'path'}
    if p.parent.name.lower() == 'voice' and p.name.lower().startswith('voice_'):
        return {'kind': 'generated_voice', 'ai_generated': True, 'source': 'letitedit_voice', 'how': 'path'}
    return None


_FILE_URL = re.compile(r"file:///[^'\"\s)`<>\\]+?\.(?:png|jpe?g|webp|gif|svg|bmp|tiff?)", re.I)
_COPY = re.compile(r'^[0-9a-f]{10}-(.+)$')


def _copy_name(source):
    """The name a code scene's page gives its copy of a picture (pictures/<hash>-<name>, the motion page builder's)."""
    return hashlib.sha256(str(source).lower().encode()).hexdigest()[:10] + '-' + re.sub(r'[^\w.-]+', '-', source.name)


def scene_parts(revision):
    """[(path, made)] of the pictures a code scene's revision folder draws (<stem>.letitedit/scenes/<id>/revisions/
    <hash>): each file:// picture its scene.json names, read from its producer's receipt when the file is on this PC,
    else from the copy its page keeps (page/pictures/<hash>-<name>); then any other copy the page keeps. A picture
    with no receipt is given with made None."""
    from urllib.parse import urlparse
    from urllib.request import url2pathname
    folder = Path(revision)
    text = _read(folder / 'scene.json') or ''
    pictures = folder / 'page' / 'pictures'
    out, seen = [], set()
    for url in dict.fromkeys(_FILE_URL.findall(text)):
        source = Path(url2pathname(urlparse(url).path))   # as the page builder reads it
        copy = pictures / _copy_name(source)
        seen.add(copy.name.lower())
        got = made(source)              # its receipt, or where its producer saves it (the original's path)
        if got is None and source.name.lower().startswith('generated-image-'):
            got = {'kind': 'generated_picture', 'ai_generated': True, 'source': 'letitedit_image', 'how': 'path'}
        if source.is_file() or copy.is_file():
            out.append((str(source if source.is_file() else copy), got))
    for copy in sorted(pictures.glob('*')) if pictures.is_dir() else []:
        m = _COPY.match(copy.name)
        if copy.name.lower() in seen or not m or not copy.is_file():
            continue
        got = None
        if m.group(1).lower().startswith('generated-image-'):
            got = {'kind': 'generated_picture', 'ai_generated': True, 'source': 'letitedit_image', 'how': 'path'}
        out.append((str(copy), got))
    return out


# ------------------------------------------------------------------ the pictures a graphic draws

_LOAD = re.compile(r"(?<![\w.])(?:[\w.]*\.)?(?:image|open)\(\s*([^,)]*)")
_LITERAL = re.compile(r"""[rRuU]?(['"])[^'"]*\1""")
_FROM_PARAMS = re.compile(r"(?:ctx\.)?p(?:\[|\.get\()")
_FOOTAGE = ('ctx.src', 'ctx.still', 'src', 'still(', 'ctx.layer', 'layer(', 'ctx.canvas', 'canvas')
_NO_FILE = re.compile(r"^(?:ctx\.)?(?:still|layer)\(|^(?:Image\.new|ctx\.src|ctx\.canvas|src)")


def _code_of(graphic):
    params = graphic.get('params') if isinstance(graphic.get('params'), dict) else {}
    return '\n'.join(str(x) for x in (graphic.get('code'), params.get('code')) if isinstance(x, str))


def _loads_from_unknown_path(code):
    """Whether a drawing's code loads a picture from a path it works out when it runs (a variable, an f-string, a
    joined path) rather than one it states or takes from its params, so no file can be named from the recipe."""
    for m in _LOAD.finditer(code):
        arg = m.group(1).strip()
        if not arg or _LITERAL.fullmatch(arg) or _FROM_PARAMS.match(arg) or arg.startswith(_FOOTAGE):
            continue
        if re.fullmatch(r'[A-Za-z_]\w*', arg):       # a name: fine when it was made from footage or a blank layer
            assigned = re.findall(r'(?m)^\s*' + re.escape(arg) + r'\s*=\s*(.+)$', code)
            if assigned and all(_NO_FILE.match(a.strip()) or _LITERAL.fullmatch(a.strip()) or
                                _FROM_PARAMS.match(a.strip()) for a in assigned):
                continue
        return True
    return False


def graphic_pictures(graphic, base=None):
    """([(path, made)], [why]) for a graphic recipe: the pictures it draws that a letitedit producer made (made as
    made() gives it), and why anything it draws can't be traced to a maker: a picture file it names that is not on
    this PC (and whose name says nothing), or code that loads a picture from a path worked out when it runs."""
    if not isinstance(graphic, dict):
        return [], []
    try:
        import letitedit.pictures.real_pictures as real_pictures
        named = real_pictures.files_in(graphic, base)
    except Exception:  # noqa: BLE001 - a recipe that can't be read can't be traced
        return [], ['its recipe could not be read']
    found, why, seen = [], [], set()
    for path in named:
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        got = made(path)
        if got is not None:
            found.append((path, got))
        elif not os.path.exists(path) and Path(path).suffix.lower() in PICTURE:
            why.append(f'it names a picture, {Path(path).name}, that is not on this PC')
    if _loads_from_unknown_path(_code_of(graphic)):
        why.append('its drawing code loads a picture from a path worked out when it runs')
    return found, why
