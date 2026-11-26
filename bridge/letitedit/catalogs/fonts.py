"""The font library: every family letitedit can use, by name, in captions, titles and Python graphics.

Bundled: ~300 Google Fonts families (open licences, free to use and ship) in C:\\LetItEdit\\fonts\\library, listed
in catalog.json (built by fonts_build.py). install() makes them available to the editor and to exports (melt) by
installing them for the current Windows user. Windows' own fonts are usable too.

    search('rounded')                  families matching a word, with category and weights
    sample_sheet(['Sniglet', 'Anton'])  JPEG of each family drawn in itself
    pil_font('Anton', 96, weight=700)  a Pillow font for graphics (variable fonts set to the weight)
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import ctypes
import io
import json
import os
import re
import shutil
from pathlib import Path

FONTS = Path(os.environ.get('LETITEDIT_FONTS', (_SAI_ROOT + '/fonts')))
LIB = FONTS / 'library'
CATALOG = FONTS / 'catalog.json'
MANIFEST = FONTS / 'installed.json'
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
INDEX = CACHE / 'fonts-index.json'
USER_FONTS = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'Windows' / 'Fonts'
# Google Fonts families fetched on demand (google_fonts.py), each in its own folder with its licence (T173)
ON_DEMAND = Path(os.environ.get('LETITEDIT_FONTS_ON_DEMAND') or (USER_FONTS / 'letitedit-on-demand'))
REG_KEY = r'Software\Microsoft\Windows NT\CurrentVersion\Fonts'
WEIGHTS = {'thin': 100, 'hairline': 100, 'extralight': 200, 'ultralight': 200, 'light': 300, 'book': 400,
           'regular': 400, 'normal': 400, 'medium': 500, 'semibold': 600, 'demibold': 600, 'bold': 700,
           'extrabold': 800, 'ultrabold': 800, 'black': 900, 'heavy': 900}


_MEMO = {}


def _load_json(path):
    with open(path, encoding='utf-8-sig') as fh:
        return json.load(fh)


def _save_json(data, path, indent=None):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=indent)


def catalog():
    """Bundled families: [{family, category, popularity, weights, variable_axes, tags, files, folder}]."""
    if 'catalog' not in _MEMO:
        _MEMO['catalog'] = _load_json(CATALOG)['families'] if CATALOG.exists() else []
    return _MEMO['catalog']


# ---------------------------------------------------------------- index of every usable font file

def _faces(path):
    """(family, style, weight, italic, axes) for each face in a font file, read from its name/OS2/fvar tables."""
    from fontTools.ttLib import TTCollection, TTFont
    out = []
    try:
        fonts = TTCollection(str(path), lazy=True).fonts if str(path).lower().endswith('.ttc') else [TTFont(str(path), lazy=True)]
    except Exception:  # noqa: BLE001 - unreadable font files are skipped
        return out
    for i, f in enumerate(fonts):
        try:
            name = f['name']
            fam = (name.getDebugName(16) or name.getDebugName(1) or '').strip()
            sub = (name.getDebugName(17) or name.getDebugName(2) or 'Regular').strip()
            weight = f['OS/2'].usWeightClass if 'OS/2' in f else 400
            italic = bool(f['OS/2'].fsSelection & 1) if 'OS/2' in f else 'italic' in sub.lower()
            axes = {a.axisTag: [a.minValue, a.defaultValue, a.maxValue] for a in f['fvar'].axes} if 'fvar' in f else {}
            instances = []
            if 'fvar' in f:
                for ins in f['fvar'].instances:
                    iname = (name.getDebugName(ins.subfamilyNameID) or '').strip()
                    if iname:
                        instances.append({'style': iname, 'weight': int(round(ins.coordinates.get('wght', weight))),
                                          'italic': italic or 'italic' in iname.lower()})
        except Exception:  # noqa: BLE001
            continue
        if fam:
            out.append({'family': fam, 'style': sub, 'weight': int(weight), 'italic': italic, 'axes': axes,
                        'instances': instances, 'path': str(path), 'index': i})
    return out


def _system_files():
    import winreg
    files = []
    for root, base in ((winreg.HKEY_LOCAL_MACHINE, Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'),
                       (winreg.HKEY_CURRENT_USER, USER_FONTS)):
        try:
            key = winreg.OpenKey(root, REG_KEY)
        except OSError:
            continue
        i = 0
        while True:
            try:
                _, value, _ = winreg.EnumValue(key, i)
            except OSError:
                break
            i += 1
            p = Path(value) if os.path.isabs(str(value)) else base / str(value)
            if p.suffix.lower() in ('.ttf', '.otf', '.ttc') and p.exists():
                files.append(p)
    return files


def index(refresh=False):
    """Every face letitedit can draw with: bundled library first, then fonts installed in Windows.
    {family_lower: {'family', 'source': 'library'|'windows', 'faces': [...]}}, cached until files change."""
    if 'index' in _MEMO and not refresh:
        return _MEMO['index']
    lib_files = sorted(LIB.glob('*/*.ttf')) if LIB.exists() else []
    sys_files = _system_files()
    od_files = sorted(p for p in ON_DEMAND.glob('*/*') if p.suffix.lower() in ('.ttf', '.otf')) if ON_DEMAND.exists() else []
    stamp = [len(lib_files), len(sys_files), max([p.stat().st_mtime for p in lib_files] or [0])]
    if od_files:
        stamp += [len(od_files), max(p.stat().st_mtime for p in od_files)]
    if INDEX.exists() and not refresh:
        try:
            data = _load_json(INDEX)
            if data.get('stamp') == stamp:
                _MEMO['index'] = data['families']
                return data['families']
        except Exception:  # noqa: BLE001
            pass
    fams = {}
    installed_copies = {Path(p).name.lower() for p in _manifest().get('files', {}).values()}
    for source, files in (('library', lib_files), ('on-demand', od_files), ('windows', sys_files)):
        for p in files:
            if source == 'windows' and p.parent == USER_FONTS and p.name.lower() in installed_copies:
                continue  # our own installed copy of a library file
            for face in _faces(p):
                row = fams.setdefault(face['family'].lower(), {'family': face['family'], 'source': source, 'faces': []})
                if row['source'] == source:
                    row['faces'].append(face)
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    _save_json({'stamp': stamp, 'families': fams}, INDEX)
    _MEMO['index'] = fams
    return fams


def family(name):
    """The index row for a family name (case-insensitive), or None."""
    return index().get(str(name).strip().lower())


WEIGHT_WORDS = {'thin': 100, 'hairline': 100, 'extralight': 200, 'ultralight': 200, 'light': 300, 'regular': 400,
                'normal': 400, 'book': 400, 'medium': 500, 'semibold': 600, 'demibold': 600, 'bold': 700,
                'extrabold': 800, 'ultrabold': 800, 'black': 900, 'heavy': 900}


def parse_name(name):
    """(family, weight or None, italic) for 'Barlow Condensed', 'Barlow Condensed ExtraBold Italic',
    'Barlow Condensed:800' or 'Inter 600'. A name that is itself a family (Archivo Black) stays whole."""
    text = str(name).strip()
    if family(text):
        return text, None, False
    base, _, w = text.partition(':')
    weight, italic = (int(w) if w.strip().isdigit() else None), False
    words = base.split()
    while len(words) > 1 and not family(' '.join(words)):
        last = words[-1].lower().replace('-', '')
        if last == 'italic':
            italic = True
        elif last in WEIGHT_WORDS:
            weight = weight or WEIGHT_WORDS[last]
        elif last.isdigit():
            weight = weight or int(last)
        else:
            break
        words.pop()
    fam = ' '.join(words)
    return (fam if family(fam) else text), weight, italic


def search(query=None, category=None, limit=60, offset=0, include_windows=True):
    """Families matching every word of `query` in their name, category or mood/shape tags (e.g. 'rounded', 'playful
    loud', 'handwritten', 'vintage', 'stencil', 'condensed', 'futuristic', 'cute', 'brush', 'slab') and/or `category`
    (Sans Serif | Serif | Display | Handwriting | Monospace). Best tag match first, then most popular."""
    cat = {c['family'].lower(): c for c in catalog()}
    words = str(query or '').lower().split()
    rows = []
    for key, row in index().items():
        if row['source'] == 'windows' and not include_windows:
            continue
        c = cat.get(key, {})
        tags = c.get('tags', {})
        score = 0
        for w in words:
            hit = [s for t, s in tags.items() if t.lower().startswith(w)]
            if hit:
                score += max(hit)
            elif w not in (row['family'] + ' ' + c.get('category', '')).lower():
                break
        else:
            rows.append({'family': row['family'],
                         'category': c.get('category', 'Windows font' if row['source'] == 'windows' else ''),
                         'tags': list(tags)[:6], 'source': row['source'],
                         'weights': sorted({s['weight'] for s in styles(row['family']) if not s['italic']}),
                         'italic': any(s['italic'] for s in styles(row['family'])),
                         '_score': score, '_pop': c.get('popularity', 99999)})
    if category:
        rows = [r for r in rows if r['category'].lower() == category.lower()]
    rows.sort(key=lambda r: (-r['_score'], r['source'] != 'library', r['_pop'], r['family']))
    for r in rows:
        del r['_score'], r['_pop']
    return {'total': len(rows), 'families': rows[offset:offset + limit]}


# ---------------------------------------------------------------- fonts for Python graphics

def font_file(name, weight=400, italic=False):
    """(path, face index, {axis: value}) for the closest face of a family. Raises KeyError if unknown."""
    row = family(name)
    if not row and _fetch_google(name):
        row = family(name)
    if not row:
        raise KeyError(f'Font family {name!r} is not installed or bundled. Use search() to find one.')
    faces = row['faces']
    pool = [f for f in faces if f['italic'] == bool(italic)] or faces

    def distance(f):
        w = f['axes'].get('wght')
        if w:
            return 0 if w[0] <= weight <= w[2] else min(abs(weight - w[0]), abs(weight - w[2]))
        return abs(f['weight'] - weight)
    best = min(pool, key=lambda f: (distance(f), 0 if f['axes'] else 1))
    var = {}
    if best['axes'].get('wght'):
        lo, _, hi = best['axes']['wght']
        var['wght'] = max(lo, min(hi, weight))
    RESOLVED.add(str(best['path']))
    return best['path'], best['index'], var


# every font file font_file has given in this process (what any drawing here has drawn with): a check that keeps its
# results records these files' contents, and keeps nothing once one of them changes (graphic_kit)
RESOLVED = set()


def _fetch_google(name):
    """A Google Fonts family named in an edit or a graphic but not on this PC comes down now (google_fonts.py):
    True when it is here afterwards. Names that aren't Google Fonts families cost nothing."""
    try:
        import letitedit.catalogs.google_fonts as google_fonts
        if not google_fonts.entry(name):
            return False
        ok = google_fonts.ensure(name)
        _MEMO.pop('index', None)
        return ok
    except Exception:  # noqa: BLE001 - the old answer (not installed) stands
        return False


def styles(name):
    """Named styles of a family as [{'style', 'weight', 'italic'}] (static faces and variable-font instances)."""
    row = family(name)
    if not row:
        return []
    out, seen = [], set()
    for f in row['faces']:
        for s in (f.get('instances') or [{'style': f['style'], 'weight': f['weight'], 'italic': f['italic']}]):
            if s['style'].lower() not in seen:
                seen.add(s['style'].lower())
                out.append(s)
    return sorted(out, key=lambda s: (s['italic'], s['weight']))


_WIDTHS = re.compile(r'condensed|expanded|narrow|wide|compressed|extended', re.I)


def mlt_text_style(name, weight=400, italic=False):
    """Properties that make Shotcut's text, caption and title filters (MLT qtext) draw `name` at `weight`.

    The stock MLT 7.41 qtext ignores `weight` under Qt 6 (it divides it by 10, so every weight asks Qt for something
    lighter than Thin: bold never renders, and variable fonts come out hairline-thin); see engine_honours_weight().
    What it always honours is `style` set to the face's own style name ('Bold', 'Black', 'SemiBold Italic'...), so
    that is what this writes; it renders the same with the fixed engine. A style starting with 'i' only switches
    italics on, so plain italic gets its weight in the form both engines decode (weight * 10 + 10). `weight`
    otherwise stays the real CSS weight, which is what Shotcut's font button shows.
    Returns {'family', 'style', 'weight'}; an unknown family is returned unchanged (the QC flags it)."""
    weight = int(weight or 400)
    if not family(name):
        _fetch_google(name)
    options = [s for s in styles(name) if s['italic'] == bool(italic)] or styles(name)
    if not options:
        return {'family': name, 'style': 'italic' if italic else 'normal', 'weight': weight}
    best = min(options, key=lambda s: (abs(s['weight'] - weight), _WIDTHS.search(s['style']) is not None,
                                       s['weight'] < weight))
    fam = family(name)['family']
    if best['style'][:1].lower() == 'i':
        return {'family': fam, 'style': 'italic', 'weight': best['weight'] * 10 + 10}
    return {'family': fam, 'style': best['style'], 'weight': best['weight']}


def text_weight_problem(props):
    """Why a text/caption filter's font will not render as written, or None. props: the filter's properties."""
    fam = props.get('family')
    if not fam:
        return None
    if not family(fam):
        return f"font '{fam}' is not installed, so it renders in a fallback font"
    style = str(props.get('style') or 'normal')
    try:
        weight = int(float(props.get('weight') or 400))
    except ValueError:
        weight = 400
    if style.lower() in ('normal', 'italic', '') and weight <= 1000:
        if engine_honours_weight():
            return None
        italic = style.lower() == 'italic'
        pool = [s for s in styles(fam) if s['italic'] == italic] or styles(fam)
        lightest = min(pool, key=lambda s: s['weight'])
        wanted = mlt_text_style(fam, weight, italic)
        if min(pool, key=lambda s: abs(s['weight'] - weight))['weight'] != lightest['weight']:
            return (f"'{fam}' weight {weight} renders as its lightest style ({lightest['style']}): the text engine "
                    f"ignores weight; use style '{wanted['style']}' (weight {wanted['weight']})")
    elif style[:1].lower() != 'i' and style.lower() not in {s['style'].lower() for s in styles(fam)}:
        return f"'{fam}' has no style named '{style}' (has: {', '.join(s['style'] for s in styles(fam))})"
    return None


APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))


def engine_honours_weight():
    """True when the installed text engine (MLT qtext) draws `weight` as asked; False for the stock 7.41 build, which
    divides it by ten (see C:\\LetItEdit\\engine-patches\\mlt-qtext-weight). Measured once per engine build."""
    dll = APP / 'lib' / 'mlt' / 'libmltqt6.dll'
    melt = APP / 'melt.exe'
    if not dll.exists() or not melt.exists():
        return False
    key = f'{dll.stat().st_size}-{int(dll.stat().st_mtime)}'
    memo = _MEMO.get('engine')
    if memo and memo[0] == key:
        return memo[1]
    path = CACHE / 'fonts-engine.json'
    try:
        data = _load_json(path)
        if data.get('key') == key:
            _MEMO['engine'] = (key, data['honours_weight'])
            return data['honours_weight']
    except Exception:  # noqa: BLE001
        pass
    import subprocess
    import tempfile
    from PIL import Image
    lit = []
    with tempfile.TemporaryDirectory() as d:
        for w in (400, 700):
            subprocess.run([str(melt), '-quiet', '-profile', 'atsc_1080p_30', 'color:0x000000ff', 'in=0', 'out=0',
                            '-filter', 'text', 'argument=Weight 48', 'family=Arial', 'size=120', f'weight={w}',
                            'style=normal', 'fgcolour=0xffffffff', 'geometry=0 0 1920 1080 1', 'halign=center',
                            'valign=middle', '-consumer', f'avformat:{d}/w{w}-%02d.png', 'vcodec=png', 'an=1',
                            'audio_off=1'], capture_output=True, timeout=60)
            img = Image.open(f'{d}/w{w}-01.png').convert('L')
            lit.append(sum(1 for p in img.getdata() if p > 128))
            img.close()
    honours = lit[1] > lit[0] * 1.15
    CACHE.mkdir(parents=True, exist_ok=True)
    _save_json({'key': key, 'honours_weight': honours, 'lit': lit}, path)
    _MEMO['engine'] = (key, honours)
    return honours


def pil_font(name, size, weight=400, italic=False):
    """A Pillow ImageFont for drawing; variable fonts are set to the requested weight."""
    from PIL import ImageFont
    path, idx, var = font_file(name, weight, italic)
    font = ImageFont.truetype(path, int(size), index=idx)
    if var:
        try:
            axes = font.get_variation_axes()
            tags = _axis_tags(path, idx)
            values = [var.get(tags[i], a['default']) if i < len(tags) else a['default'] for i, a in enumerate(axes)]
            font.set_variation_by_axes(values)
        except Exception:  # noqa: BLE001 - fall back to the default instance
            pass
    return font


_TAGS = {}


def _axis_tags(path, idx):
    key = (path, idx)
    if key not in _TAGS:
        from fontTools.ttLib import TTFont
        with TTFont(path, lazy=True, fontNumber=idx) as f:
            _TAGS[key] = [a.axisTag for a in f['fvar'].axes] if 'fvar' in f else []
    return _TAGS[key]


def sample_sheet(families=None, text=None, category=None, query=None, offset=0, limit=30, cols=3, tile_w=600):
    """JPEG bytes: each family drawn in itself (its name, or `text`), labelled. Pick families by list, query or category."""
    from PIL import Image, ImageDraw
    if families:
        names = [family(f)['family'] if family(f) else f for f in families][:limit]
    else:
        names = [r['family'] for r in search(query, category, limit=limit, offset=offset)['families']]
    tile_h = 150
    rows = max(1, (len(names) + cols - 1) // cols)
    sheet = Image.new('RGB', (cols * tile_w, rows * tile_h), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)
    label_font = pil_font('Inter', 18) if family('Inter') else None
    for i, name in enumerate(names):
        x, y = (i % cols) * tile_w, (i // cols) * tile_h
        draw.rectangle([x + 4, y + 4, x + tile_w - 4, y + tile_h - 4], outline=(60, 60, 70))
        draw.text((x + 14, y + 10), name, fill=(150, 150, 160), font=label_font)
        sample = text or name
        if not family(name):                 # a Google Fonts family not on this PC: the index's own drawing of it
            try:
                import letitedit.catalogs.google_fonts as google_fonts
                got = google_fonts.atlas_text(name, sample, 700 if text is None else 400)
                if got:
                    import numpy as np
                    arr = google_fonts._tight(got[0])
                    h = 70
                    w = min(tile_w - 30, max(1, int(arr.shape[1] * h / arr.shape[0])))
                    im = Image.fromarray((arr * 255).astype('uint8')).resize((w, h), Image.LANCZOS)
                    sheet.paste((250, 246, 235), (x + 14, y + 50), mask=im)
                    draw.text((x + tile_w - 220, y + tile_h - 26), 'Google Fonts, not on this PC', fill=(120, 170, 200),
                              font=label_font)
                    continue
            except Exception:  # noqa: BLE001 - falls through to 'unavailable'
                pass
        try:
            size = 64
            f = pil_font(name, size, weight=700 if text is None else 400)
            while draw.textlength(sample, font=f) > tile_w - 30 and size > 18:
                size -= 4
                f = pil_font(name, size, weight=700 if text is None else 400)
            draw.text((x + 14, y + 40), sample, fill=(250, 246, 235), font=f)
        except Exception as e:  # noqa: BLE001
            draw.text((x + 14, y + 60), f'unavailable: {e}'[:60], fill=(230, 90, 80), font=label_font)
    buf = io.BytesIO()
    sheet.save(buf, 'JPEG', quality=88)
    return buf.getvalue()


# ---------------------------------------------------------------- install for the editor and exports

def _manifest():
    if MANIFEST.exists():
        return _load_json(MANIFEST)
    return {'files': {}}


def _broadcast_font_change():
    HWND_BROADCAST, WM_FONTCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001D, 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0, SMTO_ABORTIFHUNG, 2000, None)


def install():
    """Install every bundled font for the current Windows user (no admin rights needed), so Shotcut's text, caption
    and title filters and melt exports find them by family name. Fonts already installed are skipped. Programs that
    were already open (an open Shotcut window) see new fonts after they restart."""
    import winreg
    manifest = _manifest()
    files = manifest.setdefault('files', {})
    USER_FONTS.mkdir(parents=True, exist_ok=True)
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY)
    existing = set()
    i = 0
    while True:
        try:
            existing.add(winreg.EnumValue(key, i)[0])
        except OSError:
            break
        i += 1
    added = 0
    for src in sorted(LIB.glob('*/*.ttf')):
        dest = USER_FONTS / src.name
        faces = _faces(src)
        if not faces:
            continue
        f = faces[0]
        style = '' if f['style'].lower() == 'regular' else ' ' + f['style']
        value = f"{f['family']}{style} (TrueType)"
        if value in existing and files.get(value) != str(dest):
            value = f"{f['family']}{style} [{src.stem}] (TrueType)"
        if files.get(value) == str(dest) and dest.exists():
            continue
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
        winreg.SetValueEx(key, value, 0, winreg.REG_SZ, str(dest))
        ctypes.windll.gdi32.AddFontResourceW(str(dest))
        files[value] = str(dest)
        existing.add(value)
        added += 1
    winreg.CloseKey(key)
    _save_json(manifest, MANIFEST, indent=1)
    if added:
        _broadcast_font_change()
    index(refresh=True)
    return {'installed_now': added, 'installed_total': len(files), 'folder': str(USER_FONTS)}


def uninstall():
    """Remove exactly the fonts install() added (registry entries and copies), nothing else."""
    import winreg
    manifest = _manifest()
    files = manifest.get('files', {})
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY)
    removed = 0
    for value, path in list(files.items()):
        try:
            current, _ = winreg.QueryValueEx(key, value)
        except OSError:
            current = None
        if current == path:
            winreg.DeleteValue(key, value)
        ctypes.windll.gdi32.RemoveFontResourceW(path)
        try:
            Path(path).unlink()
        except OSError:
            pass  # in use until programs close; Windows ignores an unregistered file
        files.pop(value)
        removed += 1
    winreg.CloseKey(key)
    _save_json(manifest, MANIFEST, indent=1)
    _broadcast_font_change()
    index(refresh=True)
    return {'removed': removed}


if __name__ == '__main__':
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if cmd == 'install':
        print(install())
    elif cmd == 'uninstall':
        print(uninstall())
    else:
        print({'bundled': len(catalog()), 'installed': len(_manifest().get('files', {}))})
