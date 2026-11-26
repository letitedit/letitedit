"""My assets (T69): the person's own logo, intro, outro, colours, clips, sounds, pictures and fonts, in one folder that
works on every video and survives a reinstall.

Where: `LETITEDIT_MY_ASSETS`, else `my_assets_dir` in settings.json (the person may point it at a Google Drive folder),
else `Documents\\letitedit\\My assets` in the person's home (outside the install, so uninstalling leaves it). Looking never
makes the folder; adding does. The person's files are only read. Adding copies a file in; removing moves the copy
into `.letitedit\\removed` (nothing is deleted). What letitedit learns lives beside them in `.letitedit\\`:
    notes.json   the person's one-line notes and any kind they set, and the description an AI wrote after looking
    facts.json   measured facts (cache, safe to delete; keyed by path, size and modified time)
    thumbs\\      small pictures

Each item: id (the file name, lower-case with hyphens), ref (`mine:<id>`, accepted by letitedit_assets, styles, pop-ups and graphics; an edit's clip takes the path),
path, kind (logo, intro, outro, clip, sound, picture, font, colours) and where the kind came from, length, size in pixels,
transparency, colours measured from the picture, the person's note, a description, and `text`: the line the AI reads
(note, else an AI's description, else one built from the measured facts, so nothing waits on anyone).

    python my_assets.py folder                       the folder and whether it exists
    python my_assets.py list [--quick]               JSON: every item (facts measured within a time budget)
    python my_assets.py add <file-or-folder>...      copy files in
    python my_assets.py note <id> <text>             the person's note ('' clears it)
    python my_assets.py kind <id> <kind>             the person's kind ('' clears it)
    python my_assets.py remove <id>                  move a copy aside
"""
from __future__ import annotations

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (no console windows, so nothing takes the keyboard focus)

import colorsys
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT))
APP = ROOT / 'app'
SETTINGS = Path(os.environ.get('LETITEDIT_SETTINGS', ROOT / 'settings.json'))
SIDE = '.letitedit'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

VIDEO = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.webm', '.mxf'}
AUDIO = {'.wav', '.mp3', '.m4a', '.flac', '.aac', '.ogg', '.opus'}
PICTURE = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff', '.heic'}
VECTOR = {'.svg'}
FONT = {'.ttf', '.otf', '.woff', '.woff2'}
COLOUR_FILES = {'.txt', '.json', '.csv', '.gpl', '.md'}
KINDS = ('logo', 'intro', 'outro', 'clip', 'sound', 'picture', 'font', 'colours')
NAME_KINDS = (  # (kind, words in the file name that say it)
    ('logo', ('logo', 'watermark', 'wordmark', 'brandmark', 'brand mark', 'bug', 'badge')),
    ('intro', ('intro', 'opener', 'opening', 'title sting', 'sting', 'bumper')),
    ('outro', ('outro', 'end card', 'endcard', 'end screen', 'endscreen', 'closer', 'closing', 'sign off', 'signoff')),
    ('colours', ('colour', 'colours', 'color', 'colors', 'palette', 'brand colors', 'swatch')),
)
PROBE_TIMEOUT = 25
FRAME_TIMEOUT = 45
BUDGET_S = 30.0          # how long one listing may spend measuring new files; the rest read "measuring" until next time


# ---------------------------------------------------------------- where
def _settings_dir():
    try:
        v = json.loads(SETTINGS.read_text(encoding='utf-8-sig')).get('my_assets_dir')
        return Path(os.path.expandvars(os.path.expanduser(str(v)))) if v else None
    except (OSError, ValueError, AttributeError):
        return None


def folder() -> Path:
    env = os.environ.get('LETITEDIT_MY_ASSETS')
    if env:
        return Path(env)
    return _settings_dir() or (Path.home() / 'Documents' / 'letitedit' / 'My assets')


def side(root=None) -> Path:
    return (Path(root) if root else folder()) / SIDE


def _atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, path)


def _load(path: Path) -> dict:
    try:
        v = json.loads(path.read_text(encoding='utf-8-sig'))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- the files
def _slug(text: str) -> str:
    t = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-') or 'item'


def _type_of(ext: str, p: Path) -> str | None:
    if ext in VIDEO:
        return 'video'
    if ext in AUDIO:
        return 'audio'
    if ext in PICTURE or ext in VECTOR:
        return 'image'
    if ext in FONT:
        return 'font'
    if ext in COLOUR_FILES and re.search(r'colou?rs?|palette|swatch|brand', p.stem, re.I):
        return 'colours'
    return None


def files(root=None) -> list[Path]:
    """Every file we understand under the folder, in a steady order (the hidden .letitedit folder left out)."""
    root = Path(root) if root else folder()
    if not root.is_dir():
        return []
    out = []
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if not d.startswith('.'))
        for f in sorted(fn):
            p = Path(dp) / f
            if not f.startswith('.') and _type_of(p.suffix.lower(), p):
                out.append(p)
    return out


def _rel(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def _ids(paths: list[Path], root: Path) -> dict:
    seen, out = {}, {}
    for p in paths:
        base = _slug(p.stem)
        n = seen.get(base, 0) + 1
        seen[base] = n
        out[_rel(p, root)] = base if n == 1 else f'{base}-{n}'
    return out


# ---------------------------------------------------------------- measuring
def _exe(name):
    p = APP / (name + ('.exe' if os.name == 'nt' else ''))
    return str(p) if p.exists() else name


def _run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)


def _probe(path: Path) -> dict:
    r = _run([_exe('ffprobe'), '-v', 'error', '-show_entries',
              'format=duration:stream=codec_type,width,height,pix_fmt,r_frame_rate', '-of', 'json', str(path)],
             PROBE_TIMEOUT)
    if r.returncode != 0:
        raise OSError((r.stderr or b'').decode('utf-8', 'replace').strip()[:200] or 'could not read it')
    j = json.loads(r.stdout.decode('utf-8', 'replace') or '{}')
    out = {}
    try:
        out['duration_s'] = round(float(j['format']['duration']), 2)
    except (KeyError, ValueError, TypeError):
        pass
    for s in j.get('streams') or []:
        if s.get('codec_type') == 'video' and 'width' not in out:
            out['width'], out['height'] = s.get('width'), s.get('height')
            out['pix_fmt'] = s.get('pix_fmt')
        if s.get('codec_type') == 'audio':
            out['has_audio'] = True
    return out


def _frame(path: Path, at: float | None, out: Path, width=480):
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_exe('ffmpeg'), '-hide_banner', '-loglevel', 'error']
    if at:
        cmd += ['-ss', f'{at:.2f}']
    cmd += ['-i', str(path), '-an', '-frames:v', '1', '-vf', f'scale={width}:-2:force_original_aspect_ratio=decrease',
            '-y', str(out)]
    r = _run(cmd, FRAME_TIMEOUT)
    return r.returncode == 0 and out.is_file()


def _hex(rgb):
    return '#%02X%02X%02X' % tuple(int(v) for v in rgb)


def _palette(img, n=5) -> tuple[list, bool]:
    """(colours, has_transparency) of a PIL image: the n most used colours, transparent pixels left out. Near-identical
    shades are merged by the quantiser; each is {hex, share}."""
    from PIL import Image
    im = img.convert('RGBA')
    im.thumbnail((96, 96))
    alpha = im.getchannel('A')
    lo = alpha.getextrema()[0]
    has_alpha = lo < 250
    getd = getattr(im, 'get_flattened_data', None) or im.getdata
    px = [(r, g, b) for (r, g, b, a) in getd() if a >= 128]
    if not px:
        return [], has_alpha
    flat = Image.new('RGB', (len(px), 1))
    flat.putdata(px)
    q = flat.quantize(colors=n * 2, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    counts = sorted(q.getcolors() or [], reverse=True)
    total = float(sum(c for c, _ in counts)) or 1.0
    out = []
    for c, i in counts:
        rgb = pal[i * 3:i * 3 + 3]
        if len(rgb) < 3:
            continue
        for colour in out:
            if sum(abs(a - b) for a, b in zip(rgb, bytes.fromhex(colour['hex'][1:]))) < 60:
                colour['share'] += c / total
                break
        else:
            out.append({'hex': _hex(rgb), 'share': c / total})
    for o in out:
        o['share'] = round(o['share'], 3)
    return sorted(out, key=lambda o: -o['share'])[:n], has_alpha


def _named_colour(hexv: str) -> str:
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if l > 0.92:
        return 'white'
    if l < 0.1:
        return 'black'
    if s < 0.12:
        return 'light grey' if l > 0.6 else 'grey' if l > 0.3 else 'dark grey'
    deg = h * 360
    base = ('red' if deg < 15 or deg >= 345 else 'orange' if deg < 40 else 'yellow' if deg < 65 else
            'green' if deg < 165 else 'teal' if deg < 195 else 'blue' if deg < 255 else
            'purple' if deg < 290 else 'pink')
    return ('light ' if l > 0.72 else 'dark ' if l < 0.28 else '') + base


def hexes_in(text: str) -> list[str]:
    """Colours written in a text/JSON/CSV/GPL file: #RGB, #RRGGBB, 0xRRGGBB or 'r g b' lines of a GIMP palette."""
    out = []

    def add(h):
        h = h.upper()
        if h not in out:
            out.append(h)
    for m in re.finditer(r'(?:#|0x)([0-9a-fA-F]{6})\b', text):
        add('#' + m.group(1))
    for m in re.finditer(r'(?<![0-9a-zA-Z])#([0-9a-fA-F]{3})\b', text):
        add('#' + ''.join(c * 2 for c in m.group(1)))
    for m in re.finditer(r'^\s*(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})\b', text, re.M):
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        if max(r, g, b) <= 255:
            add(_hex((r, g, b)))
    return out[:24]


def _measure(p: Path, root: Path, key: str) -> dict:
    """The facts of one file. Raises nothing: what could not be read is in `problem`."""
    ext = p.suffix.lower()
    typ = _type_of(ext, p)
    f: dict = {'type': typ, 'size_bytes': p.stat().st_size}
    thumbs = side(root) / 'thumbs'
    th = thumbs / (hashlib.sha1(key.encode('utf-8')).hexdigest()[:16] + '.png')
    try:
        if typ == 'image' and ext in VECTOR:
            f['vector'] = True
        elif typ == 'image':
            from PIL import Image
            with Image.open(p) as im:
                f['width'], f['height'] = im.size
                f['animated'] = bool(getattr(im, 'is_animated', False))
                im.load()
                f['colours'], f['has_alpha'] = _palette(im)
                small = im.convert('RGBA')
                small.thumbnail((480, 480))
                th.parent.mkdir(parents=True, exist_ok=True)
                small.save(th)
                f['thumb'] = str(th)
        elif typ == 'video':
            f.update(_probe(p))
            f['has_alpha'] = 'a' in str(f.get('pix_fmt') or '').replace('yuv', '').replace('gray', '') and \
                str(f.get('pix_fmt')).startswith(('yuva', 'rgba', 'bgra', 'argb', 'gbrap'))
            d = f.get('duration_s') or 0
            if _frame(p, d * 0.4 if d > 1 else 0, th):
                from PIL import Image
                with Image.open(th) as im:
                    f['colours'], _ = _palette(im)
                f['thumb'] = str(th)
        elif typ == 'audio':
            f.update(_probe(p))
            try:
                import letitedit.catalogs.assets as assets
                m = assets.measure_sound(p)
                f.update({k: m[k] for k in ('duration_s', 'peak_s', 'onset_s', 'rms_db', 'peak_db') if k in m})
            except Exception:       # no analysis libraries: the length stands
                pass
        elif typ == 'font':
            try:
                from PIL import ImageFont
                fam, style = ImageFont.truetype(str(p), 20).getname()
                f['family'], f['style'] = fam, style
            except Exception:
                pass
        elif typ == 'colours':
            f['colour_list'] = hexes_in(p.read_text(encoding='utf-8', errors='replace')[:200000])
    except subprocess.TimeoutExpired:
        f['problem'] = 'slow to open (is it still downloading from Google Drive?)'
    except Exception as e:  # noqa: BLE001 - what the person reads, not the program's own words
        f['problem'] = 'it could not be opened (a half-finished download, or not a file letitedit can read)'
        f['problem_detail'] = str(e)[:200] or type(e).__name__
    return f


def _guess_kind(p: Path, f: dict) -> tuple[str, str]:
    """(kind, where it came from): 'name' (the file name says it), 'guess' (shape of the file) or 'extension'."""
    typ = f.get('type')
    name = ' ' + ' '.join(re.findall(r'[a-z0-9]+', re.sub(r'([a-z])([A-Z])', r'\1 \2', p.stem).lower())) + ' '
    if typ == 'font':
        return 'font', 'extension'
    if typ == 'colours':
        return 'colours', 'name'
    for kind, ws in NAME_KINDS:
        if kind == 'colours':
            continue
        if any(f' {w} ' in name or f' {w}s ' in name for w in ws):
            if kind == 'logo' and typ not in ('image', 'video'):
                continue
            if kind in ('intro', 'outro') and typ not in ('video', 'image'):
                continue
            return kind, 'name'
    if typ == 'audio':
        return 'sound', 'extension'
    if typ == 'video':
        return 'clip', 'extension'
    if typ == 'image':
        big = max(f.get('width') or 0, f.get('height') or 0)
        if f.get('has_alpha') and 0 < big <= 2000:
            return 'logo', 'guess'
        return 'picture', 'extension'
    return 'picture', 'extension'


def _shape(f: dict) -> str:
    w, h = f.get('width'), f.get('height')
    if not w or not h:
        return ''
    r = w / h
    return 'wide' if r > 1.2 else 'tall' if r < 0.83 else 'square'


def _fmt_s(s) -> str:
    s = float(s)
    return f'{s:.1f} s' if s < 60 else f'{int(s // 60)} min {int(round(s % 60))} s'


def _auto_text(kind: str, f: dict, name: str) -> str:
    """One plain sentence from the measured facts, for when nobody described the item."""
    bits = []
    if f.get('problem'):
        return f'{kind} "{name}": {f["problem"]}.'
    if kind == 'colours':
        cl = f.get('colour_list') or []
        return 'colour set: ' + (', '.join(cl[:8]) if cl else 'no colours found in it') + '.'
    if kind == 'font':
        return f'font {f.get("family") or name}' + (f' ({f["style"]})' if f.get('style') else '') + '.'
    if f.get('duration_s') is not None and kind in ('intro', 'outro', 'clip', 'sound'):
        bits.append(_fmt_s(f['duration_s']))
    if f.get('width'):
        bits.append(f'{f["width"]}x{f["height"]}' + (f' {_shape(f)}' if _shape(f) else ''))
    if f.get('has_alpha'):
        bits.append('transparent background')
    if kind in ('intro', 'outro', 'clip') and f.get('type') == 'video':
        bits.append('with sound' if f.get('has_audio') else 'silent')
    if f.get('colours'):
        names = []
        for c in f['colours'][:3]:
            n = _named_colour(c['hex'])
            names.append(f'{n} {c["hex"]}')
        bits.append('mostly ' + ', '.join(names))
    if kind == 'sound' and f.get('rms_db') is not None:
        bits.append(f'loud part {f["rms_db"]:.0f} dB, loudest at {f["peak_s"]:.1f} s')
    return f'{kind}: ' + ', '.join(bits) + '.' if bits else f'{kind} "{name}".'


# ---------------------------------------------------------------- the list
def items(measure: bool = True, budget_s: float = BUDGET_S, root=None) -> list[dict]:
    """Every item in the folder. New or changed files are measured (up to budget_s; the rest show `measuring` and are
    measured on the next call); nothing waits for a person or an AI."""
    root = Path(root) if root else folder()
    paths = files(root)
    if not paths:
        return []
    sd = side(root)
    notes = _load(sd / 'notes.json')
    cache = _load(sd / 'facts.json')
    ids = _ids(paths, root)
    t0 = time.time()
    dirty = False
    out = []
    live = set()
    for p in paths:
        rel = _rel(p, root)
        try:
            st = p.stat()
        except OSError:
            continue
        key = f'{rel}|{st.st_size}|{st.st_mtime_ns}'
        live.add(key)
        f = cache.get(key)
        if f is None and measure and time.time() - t0 < budget_s:
            f = _measure(p, root, key)
            if 'problem' not in f:
                cache[key] = f
                dirty = True
        n = notes.get(rel) or {}
        measuring = f is None
        f = f or {'type': _type_of(p.suffix.lower(), p)}
        kind, src = _guess_kind(p, f)
        if n.get('kind') in KINDS:
            kind, src = n['kind'], 'person'
        item = {'id': ids[rel], 'ref': 'mine:' + ids[rel], 'name': p.name, 'path': str(p), 'rel': rel, 'kind': kind,
                'kind_from': src, **{k: v for k, v in f.items() if k not in ('type', 'pix_fmt')},
                'note': n.get('note') or '', 'description': n.get('description') or ''}
        if measuring:
            item['measuring'] = True
        auto = _auto_text(kind, f, p.stem)
        item['auto'] = auto
        item['text'] = item['note'] or item['description'] or auto
        if item['note'] and item['description']:
            item['text'] = item['note'] + ' (' + item['description'] + ')'
        out.append(item)
    if dirty:
        stale = [k for k in cache if k not in live]
        for k in stale:
            cache.pop(k, None)
        try:
            _atomic(sd / 'facts.json', cache)
        except OSError:
            pass
    return out


def get(ref_or_id: str, root=None) -> dict:
    """One item by id, `mine:<id>`, file name or path; LookupError (with the ids that exist) when none matches."""
    s = str(ref_or_id).strip()
    if s.lower().startswith('mine:'):
        s = s[5:].strip()
    its = items(root=root)
    for key in ('id', 'name', 'path', 'rel'):
        for it in its:
            if str(it[key]).lower() == s.lower():
                return it
    near = [it['id'] for it in its if _slug(s) in it['id'] or it['id'] in _slug(s)]
    raise LookupError(f'no item "{s}" in My assets' + (f'; close: {", ".join(near)}' if near else
                      f'; there are: {", ".join(i["id"] for i in its) or "nothing yet"}'))


def palette(its: list[dict] | None = None) -> list[str]:
    """The person's colours: a colour set's list if there is one, else the colours measured from the logos."""
    its = its if its is not None else items()
    for it in its:
        if it['kind'] == 'colours' and it.get('colour_list'):
            return it['colour_list']
    out = []
    for it in its:
        if it['kind'] == 'logo':
            for c in it.get('colours') or []:
                if c['hex'] not in out:
                    out.append(c['hex'])
    return out[:8]


def summary(its: list[dict] | None = None) -> dict:
    """What the AI reads first: the folder, the items grouped by kind with their `text`, and the colours."""
    its = its if its is not None else items()
    by = {}
    for it in its:
        by.setdefault(it['kind'], []).append(it['id'])
    return {'folder': str(folder()), 'exists': folder().is_dir(), 'count': len(its), 'by_kind': by,
            'colours': palette(its), 'items': [{k: v for k, v in it.items()
                                                if k in ('id', 'ref', 'kind', 'kind_from', 'text', 'duration_s', 'width',
                                                         'height', 'has_alpha', 'has_audio', 'colours', 'colour_list',
                                                         'note', 'description', 'path', 'measuring', 'problem',
                                                         'family', 'rms_db', 'peak_s')} for it in its]}


# ---------------------------------------------------------------- changing it
def _update_notes(rel: str, **kw):
    sd = side()
    notes = _load(sd / 'notes.json')
    n = notes.get(rel) or {}
    for k, v in kw.items():
        if v is None:
            continue
        if v == '':
            n.pop(k, None)
        else:
            n[k] = v
    if n:
        notes[rel] = n
    else:
        notes.pop(rel, None)
    _atomic(sd / 'notes.json', notes)


def set_note(ref: str, note: str | None = None, description: str | None = None, kind: str | None = None) -> dict:
    """The person's note (one line, beats everything), an AI's description of what it saw, or the person's kind.
    An empty string clears a field. Returns the item."""
    it = get(ref)
    if kind not in (None, '') and kind not in KINDS:
        raise ValueError(f'kind must be one of {", ".join(KINDS)}')
    _update_notes(it['rel'], note=(note.strip()[:300] if note is not None else None),
                  description=(description.strip()[:400] if description is not None else None), kind=kind)
    return get(it['id'])


def add(paths) -> dict:
    """Copy files (or the files in folders) into My assets. The originals are only read. A name already there gets
    ' (2)'. Returns {added: [ids], skipped: [{path, why}]}."""
    root = folder()
    added, skipped = [], []
    todo = []
    for p in [paths] if isinstance(paths, (str, os.PathLike)) else list(paths or []):
        p = Path(p)
        if p.is_dir():
            todo += [(q, q.relative_to(p)) for q in sorted(p.rglob('*')) if q.is_file()]
        elif p.is_file():
            todo.append((p, Path(p.name)))
        else:
            skipped.append({'path': str(p), 'why': 'not found'})
    for src, rel in todo:
        if any(part.startswith('.') for part in rel.parts) or not _type_of(src.suffix.lower(), src):
            skipped.append({'path': str(src), 'why': 'not a picture, clip, sound, font or colour file'})
            continue
        try:
            if root in src.resolve().parents:
                skipped.append({'path': str(src), 'why': 'already in My assets'})
                continue
        except OSError:
            pass
        dst = root / rel
        n = 2
        while dst.exists():
            dst = root / rel.parent / f'{rel.stem} ({n}){rel.suffix}'
            n += 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + '.part')
        try:
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
            added.append(dst)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            skipped.append({'path': str(src), 'why': str(e)[:120]})
    ids = _ids(files(root), root)
    return {'added': [ids.get(_rel(d, root), d.name) for d in added], 'skipped': skipped, 'folder': str(root)}


def remove(ref: str) -> dict:
    """Move an item's file (and its note) out of My assets into `.letitedit\\removed`, where it can be fetched back.
    Nothing is deleted."""
    it = get(ref)
    root = folder()
    p = Path(it['path'])
    dst = side(root) / 'removed' / it['rel']
    n = 2
    while dst.exists():
        dst = dst.with_name(f'{Path(it["rel"]).stem} ({n}){p.suffix}')
        n += 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(dst))
    _update_notes(it['rel'], note='', description='', kind='')
    return {'removed': it['id'], 'moved_to': str(dst)}


# ---------------------------------------------------------------- pictures
def _checker(size, step=12):
    from PIL import Image, ImageDraw
    im = Image.new('RGB', size, (200, 200, 200))
    d = ImageDraw.Draw(im)
    for y in range(0, size[1], step):
        for x in range(0, size[0], step):
            if (x // step + y // step) % 2:
                d.rectangle([x, y, x + step - 1, y + step - 1], fill=(150, 150, 150))
    return im


def look_picture(ref: str, frames: int = 6, width: int = 360) -> str | None:
    """A picture of one item for an AI to look at: a still on a chequer (so a transparent logo shows), a strip of
    frames for a clip, None for a sound, font and colour file. Saved in `.letitedit\\looks`."""
    from PIL import Image
    it = get(ref)
    out = side() / 'looks' / (hashlib.sha1((it['rel'] + str(it.get('size_bytes'))).encode()).hexdigest()[:12] + '.png')
    if it.get('type') == 'audio' or it['kind'] in ('sound', 'colours'):
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    p = Path(it['path'])
    ext = p.suffix.lower()
    if ext in VIDEO:
        d = it.get('duration_s') or 0
        n = max(1, min(frames, int(d) + 1 if d else 1))
        tiles = []
        tmpdir = side() / 'looks' / ('_t' + str(os.getpid()))
        for i in range(n):
            at = d * (i + 0.5) / n if d > 1 else 0
            t = tmpdir / f'{i}.png'
            if _frame(p, at, t, width):
                tiles.append(Image.open(t).convert('RGB'))
        if not tiles:
            return None
        h = max(t.height for t in tiles)
        cols = min(3, len(tiles))
        rows = -(-len(tiles) // cols)
        sheet = Image.new('RGB', (cols * width, rows * h), (30, 30, 30))
        for i, t in enumerate(tiles):
            sheet.paste(t, ((i % cols) * width, (i // cols) * h))
        sheet.save(out)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return str(out)
    if ext in VECTOR:
        import letitedit.catalogs.assets as assets
        try:
            return assets.rasterize(str(p), 512)
        except Exception:      # noqa: BLE001
            return None
    if it.get('thumb') and Path(it['thumb']).is_file():
        im = Image.open(it['thumb']).convert('RGBA')
    else:
        im = Image.open(p).convert('RGBA')
        im.thumbnail((480, 480))
    im.thumbnail((720, 720))
    bg = _checker(im.size).convert('RGBA')
    bg.alpha_composite(im)
    bg.convert('RGB').save(out)
    return str(out)


def sheet(its: list[dict] | None = None, tile=168, cols=5) -> str | None:
    """One contact sheet of every picture and clip, labelled with its id and kind."""
    from PIL import Image, ImageDraw
    its = [i for i in (its if its is not None else items()) if i.get('thumb') and Path(i['thumb']).is_file()]
    if not its:
        return None
    rows = -(-len(its) // cols)
    lab = 30
    im = Image.new('RGB', (cols * tile, rows * (tile + lab)), (28, 28, 28))
    d = ImageDraw.Draw(im)
    for n, it in enumerate(its):
        x, y = (n % cols) * tile, (n // cols) * (tile + lab)
        t = Image.open(it['thumb']).convert('RGBA')
        t.thumbnail((tile - 8, tile - 8))
        bg = _checker(t.size, 10).convert('RGBA')
        bg.alpha_composite(t)
        im.paste(bg.convert('RGB'), (x + (tile - t.width) // 2, y + 4 + (tile - 8 - t.height) // 2))
        d.text((x + 4, y + tile), it['id'][:26], fill=(240, 240, 240))
        sub = it['kind'] + (f' {_fmt_s(it["duration_s"])}' if it.get('duration_s') and it['kind'] != 'picture' else '')
        d.text((x + 4, y + tile + 13), sub[:26], fill=(160, 200, 220))
    out = side() / 'sheet.png'
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return str(out)


# ---------------------------------------------------------------- what a project uses
def used_in(project) -> list[dict]:
    """My assets items a project uses: its file or its scenes' code name the item's file (by path, or by file name and
    size for a copy). Colours and fonts the AI took from an item are not detectable here."""
    its = items(measure=False)
    if not its:
        return []
    try:
        import letitedit.looks.look_inputs as look_inputs
        names, texts = look_inputs._project_names(project)
        return [{'id': it['id'], 'kind': it['kind']} for it in its if look_inputs._named(it['path'], names, texts)]
    except Exception:       # no way to read the project: say nothing rather than guess
        return []


# ---------------------------------------------------------------- command line (the app's panel)
def _main(a):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    cmd = a[0] if a else ''
    if cmd == 'folder':
        r = {'folder': str(folder()), 'exists': folder().is_dir()}
    elif cmd == 'list':
        its = items(measure='--quick' not in a)
        r = {**summary(its), 'items': its}      # the panel wants every field (thumbnails, facts), the AI's tool a short one
    elif cmd == 'add':
        r = add(a[1:])
    elif cmd == 'note' and len(a) >= 3:
        r = set_note(a[1], note=' '.join(a[2:]))
    elif cmd == 'kind' and len(a) >= 3:
        r = set_note(a[1], kind=a[2])
    elif cmd == 'remove' and len(a) >= 2:
        r = remove(a[1])
    else:
        sys.stdout.write(__doc__.split('    python')[0] + '\n')
        return 2
    sys.stdout.write(json.dumps(r, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(_main(sys.argv[1:]))
    except (LookupError, ValueError, OSError) as e:
        sys.stdout.write(json.dumps({'error': str(e)}, ensure_ascii=False) + '\n')
        sys.exit(1)
