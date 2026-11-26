"""Google Fonts on demand: a searchable index of every Google Fonts family (about 1,950, each under its open licence:
OFL, Apache or UFL), its measured shape, and a download of one family when it is chosen. T173.

The index ships with letitedit (fonts/google-fonts.json.gz, ~0.3 MB, and fonts/google-fonts-glyphs.bin, ~4 MB: a
small 1-bit drawing of 74 characters per family at its regular and heaviest weight), built once by
tools/fonts/build_google_index.py from one commit of github.com/google/fonts. A family chosen from it comes down from
that same commit (file sizes and git hashes checked) with its licence file, into ON_DEMAND/<Family>/, a folder melt
(LETITEDIT_FONT_DIRS) and the editor already read; open editor windows are asked to load it (bridge `load_fonts`).

    search(query, features)           families by name, category, tags, scripts and measured shape
    match_picture(crop, text)         families ranked against a crop of real text (drawn from the index)
    fetch('Bebas Neue')               the family's files and licence on this PC
    atlas_text('Anton', 'HELLO')      the index's drawing of text in a family (bool array), for previews
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402

_ROOT = os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)
FONTS = Path(os.environ.get('LETITEDIT_FONTS', _ROOT + '/fonts'))
INDEX_FILE = FONTS / 'google-fonts.json.gz'
GLYPH_FILE = FONTS / 'google-fonts-glyphs.bin'
USER_FONTS = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'Windows' / 'Fonts'
ON_DEMAND = Path(os.environ.get('LETITEDIT_FONTS_ON_DEMAND') or (USER_FONTS / 'letitedit-on-demand'))
USER_AGENT = 'letitedit/1.0 (+https://letitedit.app; font on demand)'
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_FAMILY_BYTES = 150 * 1024 * 1024
TIMEOUT_S = 60
RECORD = 'letitedit-font.json'
OFFLINE_NOTE = "This PC can't reach Google Fonts right now (offline or blocked): use a family already on this PC."

_MEMO = {}


class Offline(Exception):
    pass


# ---------------------------------------------------------------- the index

def index():
    """The index: {format, commit, raw_base, glyphs, em, ascent, descent, families: [...]}; {} when not shipped."""
    if 'index' not in _MEMO:
        try:
            with gzip.open(INDEX_FILE, 'rb') as f:
                _MEMO['index'] = json.loads(f.read().decode('utf-8'))
        except OSError:
            _MEMO['index'] = {}
        _MEMO['by_name'] = {r['family'].lower(): r for r in _MEMO['index'].get('families', [])}
    return _MEMO['index']


def entry(name):
    """The index row of a family (case-insensitive), or None."""
    index()
    return _MEMO['by_name'].get(str(name or '').strip().lower())


def _glyph_blob():
    if 'glyphs' not in _MEMO:
        try:
            _MEMO['glyphs'] = GLYPH_FILE.read_bytes()
        except OSError:
            _MEMO['glyphs'] = b''
    return _MEMO['glyphs']


def _stats():
    """Percentiles of the measured features over families that draw Latin, for the word buckets."""
    if 'stats' in _MEMO:
        return _MEMO['stats']
    import numpy as np
    rows = [r['features'] for r in index().get('families', []) if r.get('features')]
    out = {}
    for k in ('stroke', 'width', 'x_height'):
        v = np.array([f[k] for f in rows if f.get(k) is not None])
        out[k] = {p: float(np.percentile(v, p)) for p in (20, 80)} if len(v) else {20: 0, 80: 0}
    _MEMO['stats'] = out
    return out


def shape_words(row):
    """The measured shape of a family in words: weight look, width, x-height, contrast, slant, serif, rounded."""
    f = row.get('features') or {}
    if not f:
        return {}
    st = _stats()

    def bucket(k, low, high):
        v = f.get(k)
        if v is None:
            return None
        return low if v < st[k][20] else high if v > st[k][80] else 'normal'
    contrast = f.get('contrast')
    serif = f.get('serif')
    words = {'heaviness': bucket('stroke', 'light', 'heavy'), 'width': bucket('width', 'condensed', 'wide'),
             'x_height': bucket('x_height', 'small', 'tall'),
             'contrast': None if contrast is None else 'low' if contrast < 0.25 else 'high' if contrast > 0.5 else 'medium',
             'slant': 'slanted' if abs(f.get('slant') or 0) >= 4 else 'upright',
             'serif': (row.get('stroke') in ('Serif', 'Slab Serif') if row.get('stroke')
                       else row.get('category') == 'Serif' or (serif is not None and serif >= 1.45
                                                                 and row.get('category') == 'Display')),
             'slab': row.get('stroke') == 'Slab Serif',
             'rounded': bool((f.get('corner_fill') is not None and f['corner_fill'] < 0.9) or 'Rounded' in (row.get('tags') or {}))}
    return {k: v for k, v in words.items() if v is not None}


def _weights(row):
    """The upright weights a family offers, as numbers (variable fonts: every hundred in the axis range)."""
    ax = next((a for a in row.get('axes', []) if a['tag'] == 'wght'), None)
    if ax:
        return [w for w in range(100, 1000, 100) if ax['min'] <= w <= ax['max']]
    return sorted({int(w) for w in row.get('weights', []) if not str(w).endswith('i') and str(w).isdigit()})


WEIGHT_WORDS = {'thin': 100, 'extralight': 200, 'light': 300, 'regular': 400, 'normal': 400, 'medium': 500,
                'semibold': 600, 'bold': 700, 'extrabold': 800, 'black': 900, 'heavy': 900}


def on_pc(name):
    """'library' | 'windows' | 'on-demand' | None: where a family already is on this PC."""
    try:
        import letitedit.catalogs.fonts as fonts
        row = fonts.family(name)
    except Exception:  # noqa: BLE001
        return None
    return row['source'] if row else None


def describe(row, where=None):
    where = on_pc(row['family']) if where is None else where
    return {'family': row['family'], 'category': row.get('category'), 'source': where or 'google',
            'on_pc': bool(where), 'weights': _weights(row), 'italic': any(str(w).endswith('i') for w in row.get('weights', [])),
            'scripts': row.get('subsets', []), 'tags': list((row.get('tags') or {}))[:6], 'shape': shape_words(row),
            'licence': row.get('licence'), 'designers': row.get('designers', [])[:3]}


def _feature_ok(row, features):
    words = shape_words(row)
    for k, want in (features or {}).items():
        if want is None:
            continue
        k = k.lower()
        if k == 'weight':
            w = WEIGHT_WORDS.get(str(want).lower().replace('-', '').replace(' ', ''), want)
            try:
                w = int(w)
            except (TypeError, ValueError):
                raise ValueError(f'weight is a number (100-900) or a word ({", ".join(WEIGHT_WORDS)})')
            if not any(abs(x - w) <= 50 for x in _weights(row)):
                return False
        elif k == 'italic':
            if bool(want) != any(str(x).endswith('i') for x in row.get('weights', [])):
                return False
        elif k in ('script', 'scripts'):
            for s in ([want] if isinstance(want, str) else want):
                if s.lower() not in row.get('subsets', []):
                    return False
        elif k == 'monospace':
            if bool(want) != (row.get('category') == 'Monospace'):
                return False
        elif k in ('serif', 'slab', 'rounded'):
            if bool(want) != bool(words.get(k)):
                return False
        elif k in ('heaviness', 'width', 'x_height', 'contrast', 'slant'):
            if words.get(k) != str(want).lower():
                return False
        elif k == 'category':
            if str(want).lower() != str(row.get('category') or '').lower():
                return False
        else:
            raise ValueError(f'unknown feature {k!r}: weight, italic, script, monospace, serif, slab, rounded, '
                             'heaviness (light|normal|heavy), width (condensed|normal|wide), x_height (small|normal|tall), '
                             'contrast (low|medium|high), slant (upright|slanted), category')
    return True


def _vector(row):
    f = row.get('features') or {}
    if not f:
        return None
    return [f.get('stroke') or 0, f.get('width') or 0, f.get('x_height') or 0, (f.get('contrast') or 0) * 0.3,
            min(3.0, f.get('serif') or 1.0) * 0.1, (f.get('corner_fill') if f.get('corner_fill') is not None else 1.0) * 0.3,
            (f.get('slant') or 0) / 40]


def search(query=None, category=None, features=None, like=None, limit=30, offset=0):
    """Index families matching every word of query (name, category, tags), the category and every feature; with
    like=<family>, nearest in measured shape first. Rows: describe()."""
    rows = index().get('families', [])
    if not rows:
        return {'total': 0, 'families': [], 'note': 'The Google Fonts index is not installed here.'}
    words = str(query or '').lower().split()
    base = _vector(entry(like)) if like and entry(like) else None
    if like and base is None:
        raise ValueError(f'{like!r} is not a Google Fonts family in the index')
    found = []
    for r in rows:
        if category and str(r.get('category') or '').lower() != category.lower():
            continue
        tags = r.get('tags') or {}
        score = 0
        for w in words:
            hit = [s for t, s in tags.items() if t.lower().startswith(w)]
            if hit:
                score += max(hit)
            elif w not in (r['family'] + ' ' + str(r.get('category') or '') + ' ' + ' '.join(r.get('classifications') or [])).lower():
                break
        else:
            if not _feature_ok(r, features):
                continue
            dist = 0.0
            if base is not None:
                v = _vector(r)
                if v is None or r['family'].lower() == like.lower():
                    continue
                dist = math.dist(v, base) + (0.05 if r.get('category') != entry(like).get('category') else 0)
            exact = r['family'].lower() == str(query or '').strip().lower()
            found.append((not exact, dist, -score, r.get('popularity') or 99999, r['family'], r))
    found.sort(key=lambda t: t[:5])
    page = found[offset:offset + limit]
    return {'total': len(found), 'families': [describe(t[-1]) | ({'distance': round(t[1], 4)} if base is not None else {})
                                              for t in page]}


# ---------------------------------------------------------------- drawing text from the index

def _atlas(row, weight=None):
    """(table, cells, weight) of the family's index drawing nearest the weight: cells[ch] = (left, adv, bool array)."""
    import numpy as np
    atl = row.get('atlas') or []
    if not atl:
        return None
    a = min(atl, key=lambda x: abs(x['weight'] - (weight or 400)))
    key = (row['family'], a['weight'])
    if key in _MEMO.setdefault('atlases', {}):
        return _MEMO['atlases'][key]
    meta = index()
    blob = _glyph_blob()[a['at']:a['at'] + a['n']]
    if len(blob) != a['n']:
        return None
    data = zlib.decompress(blob)
    table, bits = data[:a['table_n']], data[a['table_n']:]
    H = meta['ascent'] + meta['descent']
    cells, pos = {}, 0
    for i, ch in enumerate(meta['glyphs']):
        x, w, adv = table[3 * i], table[3 * i + 1], table[3 * i + 2]
        if w == 0:
            if adv:
                cells[ch] = (0, adv, np.zeros((H, 0), bool))
            continue
        n = (H * w + 7) // 8
        cell = np.unpackbits(np.frombuffer(bits[pos:pos + n], np.uint8))[:H * w].reshape(H, w).astype(bool)
        pos += n
        cells[ch] = (x - 128, adv, cell)
    out = (cells, a['weight'])
    _MEMO['atlases'][key] = out
    return out


def atlas_text(name, text, weight=None):
    """(bool array of the text drawn from the index, weight used, characters it lacks), or None without a drawing."""
    import numpy as np
    row = entry(name)
    got = _atlas(row, weight) if row else None
    if not got:
        return None
    cells, used = got
    meta = index()
    H, em = meta['ascent'] + meta['descent'], meta['em']
    space = max(3, int(em * 0.27))
    missing = set()
    lines = str(text).split('\n')
    pics = []
    for line in lines:
        pen, parts = 0, []
        for ch in line:
            c = cells.get(ch)
            if ch == ' ' or c is None:
                if ch != ' ':
                    missing.add(ch)
                pen += space
                continue
            left, adv, cell = c
            parts.append((pen + left, cell))
            pen += adv
        width = max([pen] + [x + c.shape[1] for x, c in parts]) + 2
        off = -min([0] + [x for x, _ in parts])
        img = np.zeros((H, width + off), bool)
        for x, c in parts:
            img[:, x + off:x + off + c.shape[1]] |= c
        pics.append(img)
    w = max(p.shape[1] for p in pics)
    out = np.zeros((H * len(pics), w), bool)
    for i, p in enumerate(pics):
        out[i * H:(i + 1) * H, :p.shape[1]] = p
    return out, used, sorted(missing)


# ---------------------------------------------------------------- matching a crop of real text

def _tight(a):
    import numpy as np
    ys, xs = np.nonzero(a)
    if not len(ys):
        return None
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _resize(a, h, w):
    from PIL import Image
    import numpy as np
    im = Image.fromarray((a * 255).astype('uint8')).resize((max(1, w), max(1, h)), Image.BILINEAR)
    return np.asarray(im) > 127


def text_mask(picture, invert=None):
    """The text of a crop as a bool array (text True), tight to the text. The background is whichever of the two
    Otsu classes covers most of the crop's border; invert=True/False forces light or dark text."""
    from PIL import Image
    import numpy as np
    im = Image.open(picture) if not hasattr(picture, 'convert') else picture
    g = np.asarray(im.convert('L'), dtype=np.float32)
    hist = np.bincount(g.astype(np.uint8).ravel(), minlength=256).astype(float)
    total, s_all = hist.sum(), (np.arange(256) * hist).sum()
    best, thr, wb, sb = -1, 128, 0.0, 0.0
    for t in range(256):
        wb += hist[t]
        if wb == 0 or wb == total:
            continue
        sb += t * hist[t]
        mb, mf = sb / wb, (s_all - sb) / (total - wb)
        between = wb * (total - wb) * (mb - mf) ** 2
        if between > best:
            best, thr = between, t
    light = g > thr
    if invert is None:
        border = np.concatenate([light[0], light[-1], light[:, 0], light[:, -1]])
        text = ~light if border.mean() > 0.5 else light
    else:
        text = light if invert else ~light
    try:                                              # drop specks smaller than 0.2% of the text
        from scipy import ndimage
        lab, n = ndimage.label(text)
        if n:
            sizes = ndimage.sum(text, lab, range(1, n + 1))
            keep = np.zeros(n + 1, bool)
            keep[1:] = sizes >= max(4, 0.002 * text.sum())
            text = keep[lab]
    except ImportError:
        pass
    return _tight(text)


def _edge_stroke(a):
    import numpy as np
    p = np.pad(a, 1)
    edge = p[1:-1, 1:-1] & ~(p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:])
    return float(2.0 * a.sum() / max(1, edge.sum()))


def _sdf(a):
    from scipy import ndimage
    return ndimage.distance_transform_edt(~a) - ndimage.distance_transform_edt(a)


def _profile(a):
    import numpy as np
    col = a.mean(axis=0)
    row = a.mean(axis=1)
    return np.concatenate([col, row * 0.5])


def _fine(t, dt_t, c1, c2, H, lighter=False):
    """Best (score, k, parts) over blends of the two weights' outlines (signed distance fields mixed by k, which
    is how a variable font's outlines move between its weights), against the target t."""
    import numpy as np
    from scipy import ndimage
    s1 = _sdf(c1)
    s2 = _sdf(c2) if c2 is not None else None
    best = None
    t_ink = t.mean()
    t_stroke = _edge_stroke(t)
    ks = (0.0, 0.25, 0.5, 0.75, 1.0) if s2 is not None else (0.0,)
    if lighter and s2 is not None:
        ks = (-0.3,) + ks                            # weights below the regular one: outlines moved the other way
    for k in ks:
        c = ((1 - k) * s1 + k * s2) < 0 if s2 is not None else c1
        if not c.any():
            continue
        dt_c = ndimage.distance_transform_edt(~c)
        chamfer = float(dt_c[t].mean() + dt_t[c].mean()) / H * 10
        ink = float(abs(t_ink - c.mean()) / max(0.05, t_ink))
        stroke = abs(t_stroke - _edge_stroke(c)) / max(0.5, t_stroke)
        score = chamfer + ink * 0.5 + stroke * 0.5
        if best is None or score < best[0]:
            best = (score, k, {'shape': round(chamfer, 3), 'ink': round(ink, 3), 'stroke': round(stroke, 3)})
    return best


def match_picture(picture, text, limit=10, invert=None, category=None, features=None, candidates=None, shortlist=150):
    """Families ranked against a crop of real text. text: exactly what the crop says, capitals as shown (lines with
    '\n'). Every family is drawn from the index (its regular and heaviest weight) at the crop's size; a quick pass on
    width and ink profile keeps a shortlist, then outlines are compared at five weights between the two (shape,
    ink, stroke) and the closest weight is given as weight_guess."""
    import numpy as np
    from scipy import ndimage
    target = text_mask(picture, invert)
    if target is None:
        raise ValueError('no text found in the picture (it looks empty)')
    text = str(text or '').strip()
    if not text:
        raise ValueError('say what the crop says (text), capitals as they appear')
    pool = index().get('families', [])
    if candidates:
        want = {c.lower() for c in candidates}
        pool = [r for r in pool if r['family'].lower() in want]
    t_aspect = target.shape[1] / target.shape[0]
    H1, H2 = 24, 48
    W1, W2 = max(8, int(round(H1 * t_aspect))), max(8, int(round(H2 * t_aspect)))
    t1 = _resize(target, H1, W1)
    tp = _profile(t1)
    quick = []
    for r in pool:
        if not r.get('atlas') or not r.get('latin'):
            continue
        if category and str(r.get('category') or '').lower() != category.lower():
            continue
        if features and not _feature_ok(r, features):
            continue
        pics = []
        for a in r['atlas']:
            got = atlas_text(r['family'], text, a['weight'])
            if not got or len(got[2]) > max(1, len(text) // 5):
                pics = []
                break
            pic = _tight(got[0])
            if pic is None:
                pics = []
                break
            pics.append((a['weight'], pic))
        if not pics:
            continue
        q = min(abs(math.log((p.shape[1] / p.shape[0]) / t_aspect)) * 1.0
                + float(np.abs(_profile(_resize(p, H1, W1)) - tp).mean()) * 4 for _, p in pics)
        quick.append((q, r, pics))
    quick.sort(key=lambda t: t[0])
    t2 = _resize(target, H2, W2)
    dt_t = ndimage.distance_transform_edt(~t2)
    results = []
    for q, r, pics in quick[:shortlist]:
        (w1, p1) = pics[0]
        (w2, p2) = pics[-1] if len(pics) > 1 else (None, None)
        c1 = _resize(p1, H2, W2)
        c2 = _resize(p2, H2, W2) if p2 is not None else None
        aspects = [abs(math.log((p.shape[1] / p.shape[0]) / t_aspect)) for _, p in pics]
        lighter = bool(w2) and min(_weights(r) or [w1]) < w1
        best = _fine(t2, dt_t, c1, c2, H2, lighter)
        if not best:
            continue
        score, k, parts = best
        aspect = aspects[0] * (1 - k) + aspects[-1] * k
        parts['width'] = round(aspect, 3)
        score += aspect * 1.0
        guess = w1 if w2 is None else int(round((w1 + k * (w2 - w1)) / 100.0) * 100)
        offered = _weights(r)
        if offered:
            guess = min(offered, key=lambda w: abs(w - guess))
        results.append((score, r, guess, parts))
    results.sort(key=lambda t: t[0])
    out = []
    for score, r, guess, parts in results[:limit]:
        out.append(describe(r) | {'score': round(float(score), 3), 'weight_guess': int(guess), 'parts': parts})
    return {'text': text, 'compared': len(quick), 'shortlist': min(shortlist, len(quick)), 'families': out,
            'note': 'Lower score is closer. Drawn from the index; on_pc False needs get before use.'}


def match_sheet(picture, ranked, text, invert=None, rows=8):
    """JPEG bytes: the crop's text on top, then each ranked family's drawing of the same text (the real font at the
    guessed weight when it is on this PC, else the index's small drawing), labelled."""
    from PIL import Image, ImageDraw
    import numpy as np
    tile_w, tile_h = 900, 92
    target = text_mask(picture, invert)
    items = ranked[:rows]
    sheet = Image.new('RGB', (tile_w, tile_h * (len(items) + 1)), (24, 24, 28))
    d = ImageDraw.Draw(sheet)

    def put(arr, y, label):
        if arr is None:
            return
        h = tile_h - 30
        w = min(tile_w - 20, max(1, int(arr.shape[1] * h / arr.shape[0])))
        im = Image.fromarray((arr * 255).astype('uint8')).resize((w, h), Image.LANCZOS).convert('RGB')
        sheet.paste(im, (10, y + 24))
        d.text((10, y + 4), label, fill=(170, 170, 180))
    put(target, 0, 'the crop (its text, as read)')
    for i, row in enumerate(items):
        arr = None
        if row.get('on_pc'):
            try:
                import letitedit.catalogs.fonts as fonts
                f = fonts.pil_font(row['family'], 80, weight=row.get('weight_guess') or 400)
                l, t, r_, b = d.textbbox((0, 0), text, font=f)
                img = Image.new('L', (r_ - l + 8, b - t + 8), 0)
                ImageDraw.Draw(img).text((4 - l, 4 - t), text, font=f, fill=255)
                arr = _tight(np.asarray(img) > 127)
            except Exception:  # noqa: BLE001 - fall back to the index drawing
                arr = None
        if arr is None:
            got = atlas_text(row['family'], text, row.get('weight_guess'))
            arr = _tight(got[0]) if got else None
        put(arr, tile_h * (i + 1), f'{i + 1}. {row["family"]}  weight ~{row.get("weight_guess")}  score {row.get("score")}'
                                   f'  {"on this PC" if row.get("on_pc") else "Google Fonts (get first)"}')
    buf = io.BytesIO()
    sheet.save(buf, 'JPEG', quality=88)
    return buf.getvalue()


# ---------------------------------------------------------------- on demand

def _blob_sha(data):
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def _get(url, max_bytes):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            data = r.read(max_bytes + 1)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise Offline(str(getattr(e, 'reason', e))) from e
    if len(data) > max_bytes:
        raise ValueError(f'{url} is over the {max_bytes // 1024 // 1024} MB limit')
    return data


def folder_of(name):
    return ON_DEMAND / re.sub(r'[^A-Za-z0-9 _-]', '', name).strip()


def fetched(name):
    """The record of a family already fetched, or None."""
    try:
        return json.loads((folder_of(name) / RECORD).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def fetch(name, notify=True):
    """Download a Google Fonts family (every face it lists) and its licence into ON_DEMAND/<Family>/, checked
    against the index (size and git hash); a family already on this PC is not fetched again. Returns {family,
    folder, files, licence, ...}; offline gives {'offline': True, 'note'}."""
    row = entry(name)
    if not row:
        raise KeyError(f'{name!r} is not a Google Fonts family in the index; search first')
    where = on_pc(row['family'])
    if where in ('library', 'windows'):
        return {'family': row['family'], 'already': where, 'note': 'Already on this PC; nothing fetched.'}
    have = fetched(row['family'])
    if have and all((folder_of(row['family']) / f).exists() for f in have.get('files', [])):
        return have | {'already': 'on-demand', 'folder': str(folder_of(row['family']))}
    meta = index()
    base = meta['raw_base'] + row['folder'] + '/'
    files = {}
    for f in row['files']:
        files.setdefault(f['file'], f)
    total = sum(f['bytes'] for f in files.values()) + row.get('licence_bytes', 0)
    if total > MAX_FAMILY_BYTES:
        raise ValueError(f'{row["family"]} is {total // 1024 // 1024} MB, over the {MAX_FAMILY_BYTES // 1024 // 1024} MB limit')
    dest = folder_of(row['family'])
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.fetch-', dir=str(dest.parent)))
    try:
        got = []
        for fname, f in list(files.items()) + [(row['licence_file'], {'bytes': row.get('licence_bytes'), 'sha': row.get('licence_sha')})]:
            if '/' in fname or '\\' in fname or fname.startswith('.'):
                raise ValueError(f'unexpected file name {fname!r}')
            data = _get(base + urllib.request.quote(fname), MAX_FILE_BYTES)
            if f.get('bytes') is not None and len(data) != f['bytes']:
                raise ValueError(f'{fname}: {len(data)} bytes, the index says {f["bytes"]}')
            if f.get('sha') and not _blob_sha(data).startswith(f['sha']):
                raise ValueError(f'{fname}: its hash does not match the index')
            if fname.lower().endswith(('.ttf', '.otf')):
                from fontTools.ttLib import TTFont
                TTFont(io.BytesIO(data), lazy=True).close()     # a font file, or this raises
            (tmp / fname).write_bytes(data)
            got.append(fname)
        record = {'family': row['family'], 'files': [g for g in got if g != row['licence_file']],
                  'licence': row.get('licence'), 'licence_file': row['licence_file'],
                  'source': meta['raw_base'] + row['folder'], 'commit': meta.get('commit'),
                  'designers': row.get('designers', []), 'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  'bytes': total}
        (tmp / RECORD).write_text(json.dumps(record, indent=1), encoding='utf-8')
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    except Offline as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return {'offline': True, 'note': OFFLINE_NOTE, 'detail': str(e)}
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    try:
        import letitedit.catalogs.fonts as fonts
        fonts.index(refresh=True)
    except Exception:  # noqa: BLE001
        pass
    out = dict(record, folder=str(dest))
    out['windows'] = notify_windows([str(dest / f) for f in record['files']]) if notify else 'not asked'
    return out


def notify_windows(paths):
    """Ask each open letitedit window to load these font files (bridge `load_fonts`), so its preview draws them now.
    Exports (melt) read the folder anyway. Returns {instance: 'loaded' | why not}."""
    out = {}
    try:
        import letitedit.app.letitedit_instances as instances
        from letitedit.app.letitedit_client import ShotcutBridge
    except Exception as e:  # noqa: BLE001
        return {'all': f'not asked ({type(e).__name__})'}
    ids = {'main'}
    if instances.ROOT.exists():
        ids.update(p.parent.name for p in instances.ROOT.glob('*/editor.json'))
    for value in sorted(ids):
        try:
            with instances.scope(value), ShotcutBridge(timeout=3) as bridge:
                res = bridge.call('load_fonts', {'paths': paths})
            out[value] = 'loaded' if res.get('loaded') else f'refused: {res.get("refused")}'
        except Exception as e:  # noqa: BLE001 - a window that isn't open, or an older build
            text = str(e)
            if 'not running' in text or 'Could not connect' in text:
                continue
            out[value] = 'this build loads new fonts after a restart' if 'unknown' in text.lower() or 'method' in text.lower() else text[:120]
    return out


def ensure(name):
    """A family named in an edit is on this PC: fetched now when it is a Google Fonts family that isn't. Returns
    True when it is on the PC afterwards. Never raises."""
    try:
        if on_pc(name):
            return True
        row = entry(name)
        if not row:
            return False
        res = fetch(row['family'])
        return not res.get('offline') and bool(on_pc(row['family']))
    except Exception:  # noqa: BLE001
        return False
