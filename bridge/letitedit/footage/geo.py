"""Where a clip or photo was recorded: GPS from the file's own metadata, and the nearest place offline.

Coordinates: QuickTime/MP4 tags (com.apple.quicktime.location.ISO6709, location, location-eng,
com.android.location) read with ffprobe, or a photo's EXIF GPS block (PIL). Places: the GeoNames cities1000 dump in
C:\\LetItEdit\\models\\geo (CC BY 4.0, see SOURCE.md), parsed once into C:\\LetItEdit\\cache\\geo, nearest place by
great-circle distance (KD-tree on unit vectors). A file without GPS gives None, never an error.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import hashlib
import io
import json
import math
import os
import re
import subprocess
import threading
import zipfile
from pathlib import Path

CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'geo'
DATA = Path(os.environ.get('LETITEDIT_GEO', (_SAI_ROOT + '\\models\\geo')))
APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))
FFPROBE = APP / 'ffprobe.exe'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
EARTH_KM = 6371.0088
INDEX_VERSION = 2
COORD_VERSION = 1
LOCATION_TAGS = ('com.apple.quicktime.location.iso6709', 'location', 'location-eng', 'com.android.location')
PHOTO_EXT = {'.jpg', '.jpeg', '.heic', '.heif', '.tif', '.tiff', '.png', '.webp', '.dng'}

_lock = threading.Lock()
_index = None


# ---------------------------------------------------------------- ISO 6709 ----------------------------------------
_ISO = re.compile(r'^\s*([+-]\d+(?:\.\d*)?)([+-]\d+(?:\.\d*)?)([+-]\d+(?:\.\d*)?)?\s*(?:CRS[^/]*)?/?\s*$')


def _iso_part(text, deg_digits):
    """'+34.4211' (DD.D), '+3425.27' (DDMM.M) or '+342516.2' (DDMMSS.S) -> decimal degrees."""
    sign = -1.0 if text[0] == '-' else 1.0
    body = text[1:]
    whole, _, frac = body.partition('.')
    frac = float('0.' + frac) if frac else 0.0
    n = len(whole)
    if n <= deg_digits:
        val = int(whole or 0) + frac
    elif n <= deg_digits + 2:
        val = int(whole[:-2]) + (int(whole[-2:]) + frac) / 60.0
    else:
        val = int(whole[:-4]) + int(whole[-4:-2]) / 60.0 + (int(whole[-2:]) + frac) / 3600.0
    return sign * val


def parse_iso6709(text):
    """{'lat', 'lon', 'alt_m' (or None)} from an ISO 6709 point such as '+34.4211-119.6678+008.748/', or None."""
    m = _ISO.match(str(text or ''))
    if not m:
        return None
    lat, lon = _iso_part(m.group(1), 2), _iso_part(m.group(2), 3)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    alt = float(m.group(3)) if m.group(3) else None
    return {'lat': round(lat, 6), 'lon': round(lon, 6), 'alt_m': alt}


# ---------------------------------------------------------------- reading GPS ----------------------------------------
def _from_tags(*tag_sets):
    for key in LOCATION_TAGS:
        for tags in tag_sets:
            for k, val in (tags or {}).items():
                if k.lower() == key:
                    got = parse_iso6709(str(val).split(';')[0])
                    if got:
                        got['source'] = k
                        return got
    return None


def _video_coords(path):
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-print_format', 'json', '-show_entries',
                        'format_tags:stream_tags', str(path)],
                       capture_output=True, text=True, errors='replace', creationflags=NO_WINDOW)
    data = json.loads(r.stdout or '{}')
    sets = [(data.get('format') or {}).get('tags') or {}]
    sets += [s.get('tags') or {} for s in data.get('streams') or []]
    return _from_tags(*sets)


def _ratio(x):
    try:
        return float(x)
    except TypeError:
        n, d = x
        return float(n) / float(d) if d else 0.0


def _photo_coords(path):
    from PIL import Image
    if Path(path).suffix.lower() in ('.heic', '.heif'):
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            return None
    try:
        with Image.open(path) as im:
            gps = im.getexif().get_ifd(0x8825)
    except Exception:  # noqa: BLE001 - unreadable photo: no coordinates
        return None
    if not gps or 2 not in gps or 4 not in gps:
        return None
    try:
        def dms(v):
            parts = [_ratio(p) for p in v]
            return parts[0] + (parts[1] if len(parts) > 1 else 0) / 60 + (parts[2] if len(parts) > 2 else 0) / 3600
        lat, lon = dms(gps[2]), dms(gps[4])
        if str(gps.get(1, 'N')).upper().startswith('S'):
            lat = -lat
        if str(gps.get(3, 'E')).upper().startswith('W'):
            lon = -lon
        alt = _ratio(gps[6]) * (-1 if gps.get(5) in (1, b'\x01') else 1) if 6 in gps else None
    except Exception:  # noqa: BLE001
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return {'lat': round(lat, 6), 'lon': round(lon, 6), 'alt_m': round(alt, 3) if alt is not None else None,
            'source': 'exif'}


def _content_key(path):
    st = os.stat(path)
    h = hashlib.sha1()
    with open(path, 'rb') as fh:
        h.update(fh.read(2 * 1024 * 1024))
    return f'{st.st_size}-{h.hexdigest()[:16]}'


_memo = {}


def coords(path, refresh=False):
    """{'lat', 'lon', 'alt_m', 'source'} from the file's own metadata, or None (no GPS / unreadable / missing).
    Cached per file content under cache/geo/files."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    memo = (str(Path(path).resolve()), st.st_size, st.st_mtime_ns)
    if memo in _memo and not refresh:
        return _memo[memo]
    f = CACHE / 'files' / f'{_content_key(path)}-v{COORD_VERSION}.json'
    got, cached = None, False
    if f.exists() and not refresh:
        try:
            got, cached = json.loads(f.read_text(encoding='utf-8-sig'))['coords'], True
        except (ValueError, KeyError):
            pass
    if not cached:
        got = _read(path)
        _write(f, got)
    _memo[memo] = got
    return got


def _read(path):
    try:
        if Path(path).suffix.lower() in PHOTO_EXT:
            return _photo_coords(path)
        return _video_coords(path)
    except Exception:  # noqa: BLE001 - GPS is extra; never a reason to fail
        return None


def _write(f, value):
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f'{f.stem}.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps({'coords': value}), encoding='utf-8')
    os.replace(tmp, f)


# ---------------------------------------------------------------- places index ----------------------------------------
def available():
    if not os.environ.get('LETITEDIT_GEO'):       # first use: GeoNames from the model manifest (11 MB)
        try:
            import letitedit.core.first_use as first_use
            first_use.optional(['geonames'], feature='place names')
        except ImportError:
            pass
    return (DATA / 'cities1000.zip').exists() or (DATA / 'cities1000.txt').exists() or (DATA / 'cities500.zip').exists()


def _source_file():
    for name in ('cities1000.zip', 'cities1000.txt', 'cities500.zip', 'cities500.txt'):
        if (DATA / name).exists():
            return DATA / name
    raise FileNotFoundError(f'No GeoNames cities file in {DATA}')


def _lines(src):
    if src.suffix == '.zip':
        with zipfile.ZipFile(src) as z:
            with z.open(src.stem + '.txt') as fh:
                yield from io.TextIOWrapper(fh, encoding='utf-8')
    else:
        with open(src, encoding='utf-8') as fh:
            yield from fh


def _build(src, out):
    import numpy as np
    admin1, countries = {}, {}
    a1 = DATA / 'admin1CodesASCII.txt'
    if a1.exists():
        for line in a1.read_text(encoding='utf-8').splitlines():
            p = line.split('\t')
            if len(p) >= 2:
                admin1[p[0]] = p[1]
    ci = DATA / 'countryInfo.txt'
    if ci.exists():
        for line in ci.read_text(encoding='utf-8').splitlines():
            if line.startswith('#'):
                continue
            p = line.split('\t')
            if len(p) >= 5:
                countries[p[0]] = p[4]
    lat, lon, pop, name, region, cc, country, gid = [], [], [], [], [], [], [], []
    for line in _lines(src):
        p = line.rstrip('\n').split('\t')
        if len(p) < 15:
            continue
        try:
            la, lo = float(p[4]), float(p[5])
        except ValueError:
            continue
        lat.append(la)
        lon.append(lo)
        pop.append(int(p[14] or 0))
        name.append(p[1])
        cc.append(p[8])
        region.append(admin1.get(f'{p[8]}.{p[10]}', ''))
        country.append(countries.get(p[8], p[8]))
        gid.append(int(p[0]))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + f'.{os.getpid()}.tmp.npz')
    def text(col):   # one UTF-8 blob per text column (fixed-width unicode arrays are ~10x larger)
        return np.frombuffer('\n'.join(x.replace('\n', ' ') for x in col).encode('utf-8'), dtype=np.uint8)
    np.savez(tmp, lat=np.array(lat), lon=np.array(lon), pop=np.array(pop, dtype=np.int64),
             gid=np.array(gid, dtype=np.int64), name=text(name), region=text(region), cc=text(cc),
             country=text(country))
    os.replace(tmp, out)


def _unit(lat, lon):
    import numpy as np
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def index():
    """The loaded places index (built from the dump once, then read from cache/geo)."""
    global _index
    with _lock:
        if _index is not None:
            return _index
        import numpy as np
        src = _source_file()
        st = src.stat()
        tag = hashlib.sha1(f'{src.name}|{st.st_size}|{st.st_mtime_ns}|{INDEX_VERSION}'.encode()).hexdigest()[:12]
        out = CACHE / f'{src.stem}-{tag}.npz'
        if not out.exists():
            _build(src, out)
        with np.load(out, allow_pickle=False) as z:
            d = {k: z[k] for k in z.files}
        for k in ('name', 'region', 'cc', 'country'):
            d[k] = d[k].tobytes().decode('utf-8').split('\n')
        d['xyz'] = _unit(d['lat'], d['lon'])
        try:
            from scipy.spatial import cKDTree
            d['tree'] = cKDTree(d['xyz'])
        except ImportError:
            d['tree'] = None
        d['source'] = src.name
        _index = d
        return d


def _km(chord):
    return 2 * EARTH_KM * math.asin(min(1.0, chord / 2))


def nearest(lat, lon, count=1, min_population=0):
    """The `count` nearest places to (lat, lon): [{'name', 'region' (admin1), 'country_code', 'country', 'lat',
    'lon', 'population', 'km', 'geonameid'}], nearest first. min_population (default 0) leaves out smaller places."""
    import numpy as np
    d = index()
    q = _unit(np.array([lat]), np.array([lon]))[0]
    count = max(1, int(count))
    if min_population > 0 or d['tree'] is None:
        mask = d['pop'] >= min_population if min_population > 0 else slice(None)
        ids = np.arange(len(d['lat']))[mask]
        dist = np.linalg.norm(d['xyz'][ids] - q, axis=1)
        order = np.argsort(dist)[:count]
        hits = [(float(dist[i]), int(ids[i])) for i in order]
    else:
        dist, ids = d['tree'].query(q, k=count)
        dist, ids = np.atleast_1d(dist), np.atleast_1d(ids)
        hits = [(float(a), int(b)) for a, b in zip(dist, ids)]
    return [{'name': str(d['name'][i]), 'region': str(d['region'][i]), 'country_code': str(d['cc'][i]),
             'country': str(d['country'][i]), 'lat': float(d['lat'][i]), 'lon': float(d['lon'][i]),
             'population': int(d['pop'][i]), 'km': round(_km(c), 2), 'geonameid': int(d['gid'][i])}
            for c, i in hits]


def place_text(p):
    """'Santa Barbara, California, US (1.2 km)'."""
    bits = [p['name']] + ([p['region']] if p.get('region') and p['region'] != p['name'] else []) + [p['country_code']]
    return f"{', '.join(bits)} ({p['km']:.1f} km)"


def place(path, min_population=0):
    """{'lat', 'lon', 'alt_m', 'source', 'place': {...nearest()...}, 'text': 'Santa Barbara, California, US (1.2 km)'}
    for a file with GPS in its metadata, or None (no GPS, or no places dataset: then 'place' and 'text' are left
    out and only the coordinates are given)."""
    c = coords(path)
    if not c:
        return None
    out = dict(c)
    if available():
        try:
            p = nearest(c['lat'], c['lon'], 1, min_population)[0]
            out['place'] = p
            out['text'] = place_text(p)
        except Exception as e:  # noqa: BLE001
            out['place_error'] = f'{type(e).__name__}: {e}'[:160]
    return out


def place_line(path):
    """'place: Santa Barbara, California, US (1.2 km)' (or 'gps: 34.4211, -119.6678' without the dataset), or None."""
    try:
        got = place(path)
    except Exception:  # noqa: BLE001 - extra information; never fails the caller
        return None
    if not got:
        return None
    if got.get('text'):
        return f"place: {got['text']}"
    return f"gps: {got['lat']:.4f}, {got['lon']:.4f}"
