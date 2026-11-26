"""Maps drawn locally from clips' GPS (geo.py) with offline Natural Earth data (public domain), still or animated:
a route line drawing between places in recording order, place labels, a moving marker, camera moves from region to
place. Every output is marked generated (gen_common) and carries the data attribution.

    stops(clips=None, points=None, order='recorded', merge_km=1.0)   the places a route visits
    render(spec, width, height, fps, ...)    -> {'path', 'cached', 'sheet', 'stops', ...}
    preview(spec, width, height, fps, count) -> {'sheet', ...}
    still(spec, width, height, at=None)      -> {'path'} one PNG

Data: C:\\LetItEdit\\maps\\naturalearth (SOURCE.md): GeoJSON layers at 1:110m, 1:50m, 1:10m and the 1:10m shaded
relief raster SR_LR; parsed once into C:\\LetItEdit\\cache\\maps. Projection: Web Mercator. Place names of stops:
GeoNames cities1000 (CC BY 4.0) through geo.nearest, so the default attribution names GeoNames.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import copy
import datetime as _dt
import hashlib
import json
import math
import os
import pickle
import subprocess
import time
from pathlib import Path

import letitedit.pictures.gen_common as gc

DATA = Path(os.environ.get('LETITEDIT_MAPS', (_SAI_ROOT + '\\maps'))) / 'naturalearth'
CACHE = gc.CACHE / 'maps'
VERSION = 1
EARTH_KM = 40075.016686            # equator length
RELIEF_FLAT = 206.0                # SR_LR value of flat ground
DETAIL_KM = {'110m': 3000.0, '50m': 600.0}     # auto detail: km_across >= 3000 -> 110m, >= 600 -> 50m, else 10m
MIN_KM_ACROSS = 2.0
ATTRIBUTION_NE = 'Made with Natural Earth'
ATTRIBUTION_GEONAMES = 'Place names: GeoNames (CC BY 4.0)'

STYLES = {
    'light': {'water': '#bcd6ea', 'land': '#f3f0e8', 'relief': 0.0, 'urban': '#e6ddd0', 'lakes': '#bcd6ea',
              'rivers': '#9fc3e0', 'river_width': 1.2, 'states': '#b9b2a6', 'state_width': 1.0, 'countries': '#8d867b',
              'country_width': 1.6, 'roads': '#d9a46a', 'road_width': 1.1, 'route': '#e8452c', 'route_width': 5.0,
              'route_casing': '#ffffff', 'route_casing_width': 3.0, 'route_ahead': '#e8452c55', 'stop': '#ffffff',
              'stop_ring': '#e8452c', 'stop_radius': 7.0, 'marker': '#e8452c', 'marker_ring': '#ffffff',
              'marker_radius': 11.0, 'label': '#1f1d1a', 'label_halo': '#ffffffdd', 'label_size': 30,
              'label_weight': 700, 'context_label': '#5a554e', 'context_size': 22, 'context_weight': 500,
              'font': 'Inter', 'title_color': '#1f1d1a', 'title_box': '#ffffffd0', 'title_size': 46,
              'attribution_color': '#3a3732', 'attribution_size': 16},
    'dark': {'water': '#0f1a26', 'land': '#26303b', 'relief': 0.0, 'urban': '#323c48', 'lakes': '#0f1a26',
             'rivers': '#1f3a55', 'river_width': 1.2, 'states': '#46505c', 'state_width': 1.0, 'countries': '#6a7480',
             'country_width': 1.6, 'roads': '#56606a', 'road_width': 1.1, 'route': '#ffb000', 'route_width': 5.0,
             'route_casing': '#00000080', 'route_casing_width': 3.0, 'route_ahead': '#ffb00040', 'stop': '#1b232c',
             'stop_ring': '#ffb000', 'stop_radius': 7.0, 'marker': '#ffb000', 'marker_ring': '#1b232c',
             'marker_radius': 11.0, 'label': '#f2f4f7', 'label_halo': '#0b1016d0', 'label_size': 30,
             'label_weight': 700, 'context_label': '#9aa4ae', 'context_size': 22, 'context_weight': 500,
             'font': 'Inter', 'title_color': '#f2f4f7', 'title_box': '#0b1016c0', 'title_size': 46,
             'attribution_color': '#9aa4ae', 'attribution_size': 16},
    'relief': {'water': '#a9c9e2', 'land': '#e9e3d2', 'relief': 0.85, 'urban': '#ddd3c2', 'lakes': '#a9c9e2',
               'rivers': '#86b2d6', 'river_width': 1.2, 'states': '#a49b8b', 'state_width': 1.0,
               'countries': '#7a7264', 'country_width': 1.6, 'roads': '#c98d4e', 'road_width': 1.0,
               'route': '#d7261e', 'route_width': 5.0, 'route_casing': '#ffffff', 'route_casing_width': 3.0,
               'route_ahead': '#d7261e40', 'stop': '#ffffff', 'stop_ring': '#d7261e', 'stop_radius': 7.0,
               'marker': '#d7261e', 'marker_ring': '#ffffff', 'marker_radius': 11.0, 'label': '#1f1d1a',
               'label_halo': '#ffffffdd', 'label_size': 30, 'label_weight': 700, 'context_label': '#4f4a42',
               'context_size': 22, 'context_weight': 500, 'font': 'Inter', 'title_color': '#1f1d1a',
               'title_box': '#ffffffd0', 'title_size': 46, 'attribution_color': '#3a3732', 'attribution_size': 16},
    'paper': {'water': '#d8d2c0', 'land': '#f4ecd8', 'relief': 0.5, 'urban': '#e9dcc0', 'lakes': '#d8d2c0',
              'rivers': '#c5bca6', 'river_width': 1.0, 'states': '#c4b69a', 'state_width': 1.0,
              'countries': '#8f7f62', 'country_width': 1.8, 'roads': '#c9b48e', 'road_width': 1.0,
              'route': '#7a2e1d', 'route_width': 4.5, 'route_casing': '#f4ecd8', 'route_casing_width': 3.0,
              'route_ahead': '#7a2e1d40', 'stop': '#f4ecd8', 'stop_ring': '#7a2e1d', 'stop_radius': 7.0,
              'marker': '#7a2e1d', 'marker_ring': '#f4ecd8', 'marker_radius': 11.0, 'label': '#3b2a1a',
              'label_halo': '#f4ecd8e0', 'label_size': 30, 'label_weight': 700, 'context_label': '#6b5a44',
              'context_size': 22, 'context_weight': 500, 'font': 'Inter', 'title_color': '#3b2a1a',
              'title_box': '#f4ecd8d0', 'title_size': 46, 'attribution_color': '#5b4a34', 'attribution_size': 16},
}
LAYERS_DEFAULT = ['land', 'relief', 'urban', 'lakes', 'rivers', 'states', 'countries', 'roads']

DEFAULTS = {
    'clips': None, 'points': None, 'order': 'recorded', 'merge_km': 1.0, 'style': 'relief', 'style_overrides': {},
    'layers': LAYERS_DEFAULT, 'detail': 'auto', 'relief_fade_km': [20.0, 250.0], 'roads_below_km': 1500.0, 'rivers_below_km': 6000.0,
    'duration': 6.0, 'still': False,
    'camera': 'fit', 'fit_margin': 0.18, 'min_km_across': 60.0, 'follow_km': 400.0, 'zoom_km': 40.0,
    'zoom_to': -1, 'zoom_start': None, 'zoom_end': None, 'center': None, 'km_across': None, 'keys': None,
    'easing': 'ease_in_out',
    'route': True, 'path': 'arc', 'arc_bend': 0.12, 'route_start': None, 'route_end': None, 'route_easing': 'ease_in_out',
    'pace': 'distance', 'show_ahead': False,
    'marker': 'dot', 'stop_dots': True, 'labels': 'stops', 'label_fade': 0.35, 'label_offset': [14, -14],
    'context_places': 6, 'context_min_pop': 50000,
    'title': None, 'title_at': 'top_left', 'attribution': 'auto', 'attribution_at': 'bottom_right', 'safe_margin': 0.04,
    'format': 'mp4', 'crf': 16, 'background': None,
}


# ------------------------------------------------------------------ data

def _layer_file(name, detail):
    if not os.environ.get('LETITEDIT_MAPS'):      # first use: Natural Earth from the model manifest (155 MB)
        import letitedit.core.first_use as first_use
        first_use.need(models=['natural-earth'], feature='maps (letitedit_map)')
    return DATA / f'ne_{detail}_{name}.geojson'


LAYER_FILES = {'land': 'land', 'lakes': 'lakes', 'rivers': 'rivers_lake_centerlines',
               'states': 'admin_1_states_provinces_lines', 'countries': 'admin_0_boundary_lines_land',
               'places': 'populated_places_simple', 'urban': 'urban_areas', 'roads': 'roads'}
_mem = {}


def available():
    return _layer_file('land', '110m').exists()


def layer(name, detail):
    """[(kind 'poly'|'line'|'point', [arrays of (lon, lat)], bbox (lon0, lat0, lon1, lat1), props)] for a layer at a
    detail ('110m'|'50m'|'10m'); falls back to coarser files when a layer has no file at that detail."""
    import numpy as np
    order = {'10m': ['10m', '50m', '110m'], '50m': ['50m', '10m', '110m'], '110m': ['110m', '50m', '10m']}[detail]
    for d in order:
        f = _layer_file(LAYER_FILES[name], d)
        if f.exists():
            break
    else:
        return []
    key = (name, d)
    if key in _mem:
        return _mem[key]
    CACHE.mkdir(parents=True, exist_ok=True)
    st = f.stat()
    cf = CACHE / f'{name}-{d}-{st.st_size}-v{VERSION}.pkl'
    if cf.exists():
        with open(cf, 'rb') as fh:
            feats = pickle.load(fh)
        _mem[key] = feats
        return feats
    gj = json.loads(f.read_text(encoding='utf-8-sig'))
    feats = []
    keep = ('name', 'NAME', 'scalerank', 'SCALERANK', 'pop_max', 'POP_MAX', 'featurecla', 'type', 'adm0name',
            'min_zoom', 'labelrank', 'expressway')
    for ft in gj['features']:
        g = ft.get('geometry') or {}
        t = g.get('type')
        props = {k: v for k, v in (ft.get('properties') or {}).items() if k in keep}
        parts = []
        if t == 'Polygon':
            parts, kind = [g['coordinates']], 'poly'
        elif t == 'MultiPolygon':
            parts, kind = g['coordinates'], 'poly'
        elif t == 'LineString':
            parts, kind = [[g['coordinates']]], 'line'
        elif t == 'MultiLineString':
            parts, kind = [[c] for c in g['coordinates']], 'line'
        elif t == 'Point':
            parts, kind = [[[g['coordinates']]]], 'point'
        else:
            continue
        for poly in parts:
            rings = [np.asarray(r, dtype='float64')[:, :2] for r in poly if len(r)]
            if not rings:
                continue
            allp = np.concatenate(rings)
            bbox = (float(allp[:, 0].min()), float(allp[:, 1].min()), float(allp[:, 0].max()), float(allp[:, 1].max()))
            feats.append((kind, rings, bbox, props))
    with open(cf, 'wb') as fh:
        pickle.dump(feats, fh, protocol=pickle.HIGHEST_PROTOCOL)
    _mem[key] = feats
    return feats


_relief = None


def relief():
    """The SR_LR shaded relief (8100 x 16200 uint8, plate carree, 1/45 degree per pixel), cached as .npy."""
    global _relief
    if _relief is not None:
        return _relief
    import numpy as np
    src = DATA / 'raster_sr_lr' / 'SR_LR.tif'
    if not src.exists():
        return None
    npy = CACHE / f'sr_lr-{src.stat().st_size}.npy'
    if not npy.exists():
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        CACHE.mkdir(parents=True, exist_ok=True)
        np.save(npy, np.asarray(Image.open(src).convert('L')))
    _relief = np.load(npy)
    return _relief


# ------------------------------------------------------------------ projection / view

def merc(lon, lat):
    """Web Mercator world coordinates 0-1 (x east, y south)."""
    import numpy as np
    lat = np.clip(lat, -85.05, 85.05)
    x = np.asarray(lon) / 360.0 + 0.5
    y = 0.5 - np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) / (2 * np.pi)
    return x, y


def unmerc(x, y):
    import numpy as np
    lon = (np.asarray(x) - 0.5) * 360.0
    lat = np.degrees(2 * np.arctan(np.exp((0.5 - np.asarray(y)) * 2 * np.pi)) - np.pi / 2)
    return lon, lat


class View:
    """Centre (world x, y) and width (world units across the frame) for a frame of w x h pixels."""

    def __init__(self, cx, cy, ww, w, h):
        self.cx, self.cy, self.ww, self.w, self.h = cx, cy, ww, w, h

    @property
    def wh(self):
        return self.ww * self.h / self.w

    def km_across(self):
        lat = float(unmerc(self.cx, self.cy)[1])
        return self.ww * EARTH_KM * math.cos(math.radians(lat))

    def px(self, x, y):
        return (x - self.cx) / self.ww * self.w + self.w / 2, (y - self.cy) / self.ww * self.w + self.h / 2

    def lonlat_box(self, pad=0.1):
        x0, x1 = self.cx - self.ww * (0.5 + pad), self.cx + self.ww * (0.5 + pad)
        y0, y1 = self.cy - self.wh * (0.5 + pad), self.cy + self.wh * (0.5 + pad)
        lon0, lat1 = unmerc(x0, y0)
        lon1, lat0 = unmerc(x1, y1)
        return float(lon0), float(lat0), float(lon1), float(lat1)


def view_for(lat, lon, km, w, h):
    x, y = merc(lon, lat)
    ww = max(MIN_KM_ACROSS, float(km)) / (EARTH_KM * math.cos(math.radians(lat)))
    return View(float(x), float(y), ww, w, h)


def fit_view(stops, w, h, margin=0.18, min_km=60.0):
    import numpy as np
    xs, ys = merc(np.array([s['lon'] for s in stops]), np.array([s['lat'] for s in stops]))
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ww = max((x1 - x0), (y1 - y0) * w / h) / max(0.05, 1 - 2 * margin)
    lat = float(unmerc(cx, cy)[1])
    ww = max(ww, min_km / (EARTH_KM * math.cos(math.radians(lat))))
    return View(float(cx), float(cy), float(ww), w, h)


def ease(t, kind):
    t = max(0.0, min(1.0, t))
    if kind in (None, 'linear'):
        return t
    if kind in ('ease_in_out', 'smooth'):
        return t * t * (3 - 2 * t)
    if kind == 'ease_in':
        return t * t
    if kind == 'ease_out':
        return 1 - (1 - t) ** 2
    if kind == 'sine':
        return 0.5 - 0.5 * math.cos(math.pi * t)
    if kind == 'cubic':
        return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
    return t


def lerp_view(a, b, u):
    """Width changes log-linearly (constant zoom speed). When the widths differ, the zoom is about the one point that
    sits at the same pixel in both views (the place zoomed to stays in frame); else the centre moves linearly."""
    ww = math.exp(math.log(a.ww) + (math.log(b.ww) - math.log(a.ww)) * u)
    if abs(b.ww - a.ww) > 1e-3 * max(a.ww, b.ww):
        fx = (a.cx * b.ww - b.cx * a.ww) / (b.ww - a.ww)
        fy = (a.cy * b.ww - b.cy * a.ww) / (b.ww - a.ww)
        k = ww / a.ww
        return View(fx + (a.cx - fx) * k, fy + (a.cy - fy) * k, ww, a.w, a.h)
    return View(a.cx + (b.cx - a.cx) * u, a.cy + (b.cy - a.cy) * u, ww, a.w, a.h)


# ------------------------------------------------------------------ stops

def _probe_tags(path):
    import letitedit.footage.geo as geo
    try:
        r = subprocess.run([str(geo.FFPROBE), '-v', 'error', '-show_entries', 'format_tags:stream_tags', '-of', 'json',
                            str(path)], capture_output=True, text=True, encoding='utf-8', errors='replace',
                           creationflags=gc.NO_WINDOW, timeout=60)
        d = json.loads(r.stdout or '{}')
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    sets = [(d.get('format') or {}).get('tags') or {}]
    sets += [s.get('tags') or {} for s in d.get('streams') or []]
    return sets


def recorded_at(path):
    """(epoch seconds, text) of when a clip/photo was recorded (Apple creationdate, creation_time, EXIF
    DateTimeOriginal), else the file's modified time."""
    p = Path(path)
    text = None
    if p.suffix.lower() in ('.jpg', '.jpeg', '.heic', '.heif', '.tif', '.tiff', '.png', '.webp', '.dng'):
        try:
            from PIL import Image
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                pass
            ex = Image.open(p).getexif()
            sub = ex.get_ifd(0x8769) if hasattr(ex, 'get_ifd') else {}
            v = sub.get(36867) or ex.get(306)
            off = sub.get(36881)
            if v:
                text = str(v).replace(':', '-', 2).replace(' ', 'T') + (str(off) if off else '')
        except Exception:  # noqa: BLE001
            text = None
    else:
        for key in ('com.apple.quicktime.creationdate', 'creation_time'):
            for tags in _probe_tags(p):
                for k, v in tags.items():
                    if k.lower() == key and str(v).strip():
                        text = str(v).strip()
                        break
                if text:
                    break
            if text:
                break
    if text:
        try:
            d = _dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
            if d.tzinfo is None:
                d = d.replace(tzinfo=_dt.timezone.utc)
            return d.timestamp(), text
        except ValueError:
            pass
    try:
        return p.stat().st_mtime, 'file modified time'
    except OSError:
        return 0.0, None


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a['lat'], a['lon'], b['lat'], b['lon']))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def _expand(clips):
    out = []
    for c in ([clips] if isinstance(clips, str) else clips or []):
        p = Path(str(c))
        if p.is_dir():
            out += sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() not in ('.ini', '.json', '.txt'))
        else:
            out.append(p)
    return out


def stops(clips=None, points=None, order='recorded', merge_km=1.0, place_names=True):
    """The route's stops: [{lat, lon, label, place, km_from_place, clips: [...], recorded}], in recording order
    (order 'recorded') or as given ('given'); consecutive points within merge_km of the previous stop join it.
    Returns (stops, notes)."""
    import letitedit.footage.geo as geo
    pts, notes = [], []
    for c in _expand(clips):
        co = geo.coords(str(c))
        if not co:
            notes.append(f'no GPS: {c.name}')
            continue
        ts, txt = recorded_at(c)
        pts.append({'lat': co['lat'], 'lon': co['lon'], 'clip': str(c), 'ts': ts, 'recorded': txt})
    for i, p in enumerate(points or []):
        if isinstance(p, (list, tuple)):
            p = {'lat': p[0], 'lon': p[1], **({'label': p[2]} if len(p) > 2 else {})}
        q = {'lat': float(p['lat']), 'lon': float(p['lon']), 'ts': float(p.get('ts', i)), 'recorded': p.get('recorded')}
        if p.get('label') is not None:
            q['label'] = str(p['label'])
        pts.append(q)
    if order == 'recorded':
        pts.sort(key=lambda p: p['ts'])
    out = []
    for p in pts:
        if out and merge_km and _km(out[-1], p) <= merge_km and 'label' not in p:
            out[-1]['clips'] += [p['clip']] if p.get('clip') else []
            continue
        out.append({'lat': p['lat'], 'lon': p['lon'], 'label': p.get('label'), 'clips': [p['clip']] if p.get('clip') else [],
                    'recorded': p.get('recorded')})
    if place_names and geo.available():
        for s in out:
            try:
                n = geo.nearest(s['lat'], s['lon'], 1)[0]
                s['place'] = n['name'] + (f", {n['region']}" if n.get('region') else '')
                s['km_from_place'] = n['km']
                if s['label'] is None:
                    s['label'] = n['name']
                s['place_source'] = 'GeoNames'
            except Exception as e:  # noqa: BLE001
                notes.append(f'place name: {e}')
    for i, s in enumerate(out):
        if s['label'] is None:
            s['label'] = f"{s['lat']:.3f}, {s['lon']:.3f}"
    return out, notes


# ------------------------------------------------------------------ route geometry

def route_path(stops_, path='arc', bend=0.12, n_seg=48):
    """World-coordinate polyline through the stops, and the index in it of each stop."""
    import numpy as np
    xs, ys = merc(np.array([s['lon'] for s in stops_]), np.array([s['lat'] for s in stops_]))
    P = np.stack([xs, ys], 1)
    if len(P) < 2:
        return P, [0]
    pts, idx = [P[0]], [0]
    for i in range(len(P) - 1):
        a, b = P[i], P[i + 1]
        if path == 'straight':
            seg = np.array([b])
        elif path == 'smooth':
            p0 = P[i - 1] if i > 0 else a
            p3 = P[i + 2] if i + 2 < len(P) else b
            t = np.linspace(0, 1, n_seg + 1)[1:, None]
            seg = 0.5 * ((2 * a) + (-p0 + b) * t + (2 * p0 - 5 * a + 4 * b - p3) * t ** 2
                         + (-p0 + 3 * a - 3 * b + p3) * t ** 3)
        else:   # arc: a quadratic curve bowed sideways by bend x the segment length
            d = b - a
            nrm = np.array([-d[1], d[0]])
            ctrl = (a + b) / 2 + nrm * float(bend)
            t = np.linspace(0, 1, n_seg + 1)[1:, None]
            seg = (1 - t) ** 2 * a + 2 * (1 - t) * t * ctrl + t ** 2 * b
        pts += list(seg)
        idx.append(len(pts) - 1)
    return np.array(pts), idx


def cut_path(P, frac):
    """The first `frac` (0-1) of a polyline by length: (points, head point, index reached)."""
    import numpy as np
    if len(P) < 2:
        return P, P[0], 0
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    L = cum[-1] * max(0.0, min(1.0, frac))
    i = int(np.searchsorted(cum, L, side='right') - 1)
    i = max(0, min(len(seg) - 1, i))
    u = (L - cum[i]) / seg[i] if seg[i] > 0 else 0
    head = P[i] + (P[i + 1] - P[i]) * u
    return np.vstack([P[:i + 1], head]), head, i


# ------------------------------------------------------------------ spec

def normalise(spec):
    s = copy.deepcopy(DEFAULTS)
    s.update({k: v for k, v in dict(spec or {}).items() if v is not None})
    if s['style'] not in STYLES:
        raise ValueError(f"style must be one of {sorted(STYLES)}")
    if s['format'] not in gc.FORMATS:
        raise ValueError(f'format must be one of {gc.FORMATS}')
    if s['camera'] not in ('fit', 'follow', 'zoom_in', 'zoom_out', 'fixed', 'keys'):
        raise ValueError("camera must be 'fit', 'follow', 'zoom_in', 'zoom_out', 'fixed' or 'keys'")
    if s['path'] not in ('arc', 'straight', 'smooth'):
        raise ValueError("path must be 'arc', 'straight' or 'smooth'")
    if s['clips']:
        s['clips'] = [str(c) for c in ([s['clips']] if isinstance(s['clips'], str) else s['clips'])]
    s['duration'] = float(s['duration'])
    if not (s['clips'] or s['points'] or s['center']):
        raise ValueError('a map needs clips (files with GPS), points [{lat, lon, label?}] or a center [lat, lon]')
    return s


def style_of(s):
    st = dict(STYLES[s['style']])
    st.update(s.get('style_overrides') or {})
    return st


def _files_sig(s):
    out = []
    for c in _expand(s.get('clips')):
        try:
            st = os.stat(c)
            out.append([str(c), st.st_size, int(st.st_mtime)])
        except OSError:
            out.append([str(c), None])
    return out


def digest(s, width, height, fps):
    key = json.dumps([s, _files_sig(s), int(width), int(height), round(float(fps), 4), VERSION], sort_keys=True,
                     default=str)
    return hashlib.sha1(key.encode()).hexdigest()[:16]


# ------------------------------------------------------------------ drawing

def _bgr(c):
    return gc.rgba(c)


def _blend_draw(img, draw, color):
    """Draw with alpha: draw(layer) onto a copy, blend by the colour's alpha."""
    r, g, b, a = _bgr(color)
    if a >= 255:
        draw(img, (r, g, b))
        return
    if a <= 0:
        return
    tmp = img.copy()
    draw(tmp, (r, g, b))
    import cv2
    cv2.addWeighted(tmp, a / 255.0, img, 1 - a / 255.0, 0, dst=img)


def _pts(view, ring, shift=3):
    import numpy as np
    x, y = merc(ring[:, 0], ring[:, 1])
    px, py = view.px(x, y)
    arr = np.stack([px, py], 1) * (1 << shift)
    arr = np.clip(arr, -2.0e9, 2.0e9)
    return arr.astype(np.int32)


def _visible(bbox, box):
    return not (bbox[2] < box[0] or bbox[0] > box[2] or bbox[3] < box[1] or bbox[1] > box[3])


class Painter:
    """Draws map frames for one spec (layers cached per detail level)."""

    def __init__(self, s, width, height):
        self.s = s
        self.st = style_of(s)
        self.w, self.h = int(width), int(height)
        self.k = self.h / 1080.0

    def detail(self, km):
        d = self.s['detail']
        if d != 'auto':
            return d
        return '110m' if km >= DETAIL_KM['110m'] else '50m' if km >= DETAIL_KM['50m'] else '10m'

    def base(self, view):
        """The map without the route: RGB uint8 array."""
        import cv2
        import numpy as np
        st, s, k = self.st, self.s, self.k
        W, H = self.w, self.h
        km = view.km_across()
        det = self.detail(km)
        box = view.lonlat_box()
        img = np.zeros((H, W, 3), np.uint8)
        img[:] = _bgr(st['water'])[:3]
        layers = s['layers']
        if 'land' in layers:
            mask = np.zeros((H, W), np.uint8)
            for kind, rings, bbox, _ in layer('land', det):
                if _visible(bbox, box):
                    cv2.fillPoly(mask, [_pts(view, rings[0])], 255, cv2.LINE_AA, shift=3)
                    if len(rings) > 1:
                        cv2.fillPoly(mask, [_pts(view, r) for r in rings[1:]], 0, cv2.LINE_AA, shift=3)
            land = np.empty_like(img)
            land[:] = _bgr(st['land'])[:3]
            if 'relief' in layers and float(st.get('relief') or 0) > 0:
                rel = relief()
                if rel is not None:
                    xs = np.arange(W, dtype=np.float64)
                    ys = np.arange(H, dtype=np.float64)
                    wx = view.cx + (xs - W / 2) / W * view.ww
                    wy = view.cy + (ys - H / 2) / W * view.ww
                    lon, _ = unmerc(wx, np.zeros_like(wx) + 0.5)
                    _, lat = unmerc(np.zeros_like(wy) + 0.5, wy)
                    mx = ((lon + 180.0) * 45.0 - 0.5).astype(np.float32)
                    my = ((90.0 - lat) * 45.0 - 0.5).astype(np.float32)
                    mapx = np.repeat(mx[None, :], H, 0)
                    mapy = np.repeat(my[:, None], W, 1)
                    shade = cv2.remap(rel, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                    lo_km, hi_km = s['relief_fade_km']
                    fade = 1.0 if km >= hi_km else 0.0 if km <= lo_km else math.log(km / lo_km) / math.log(hi_km / lo_km)
                    f = 1 + float(st['relief']) * fade * (shade.astype(np.float32) / RELIEF_FLAT - 1)
                    land = np.clip(land.astype(np.float32) * f[:, :, None], 0, 255).astype(np.uint8)
            a = (mask.astype(np.float32) / 255.0)[:, :, None]
            img = (img * (1 - a) + land * a).astype(np.uint8)
        if 'urban' in layers and km < 2500:
            polys = [_pts(view, r) for kind, rings, bbox, _ in layer('urban', '10m' if km < 600 else '50m')
                     if _visible(bbox, box) for r in rings[:1]]
            if polys:
                _blend_draw(img, lambda im, c: cv2.fillPoly(im, polys, c, cv2.LINE_AA, shift=3), st['urban'])
        if 'lakes' in layers:
            polys = [_pts(view, r) for kind, rings, bbox, _ in layer('lakes', det) if _visible(bbox, box)
                     for r in rings[:1]]
            if polys:
                _blend_draw(img, lambda im, c: cv2.fillPoly(im, polys, c, cv2.LINE_AA, shift=3), st['lakes'])

        def lines(name, color, width, det_=det, keep=None):
            ls = [_pts(view, r) for kind, rings, bbox, props in layer(name, det_) if _visible(bbox, box)
                  and (keep is None or keep(props)) for r in rings]
            lw = max(1, round(width * k))
            if ls:
                _blend_draw(img, lambda im, c: cv2.polylines(im, ls, False, c, lw, cv2.LINE_AA, shift=3), color)
        if 'rivers' in layers and km < float(s['rivers_below_km']):
            lines('rivers', st['rivers'], st['river_width'])
        if 'states' in layers:
            lines('states', st['states'], st['state_width'])
        if 'countries' in layers:
            lines('countries', st['countries'], st['country_width'])
        if 'roads' in layers and km < float(s['roads_below_km']):
            lines('roads', st['roads'], st['road_width'], '10m',
                  keep=(lambda p: (p.get('scalerank') or 99) <= (6 if km > 600 else 8 if km > 150 else 99)))
        return img

    def context_labels(self, view, avoid):
        """Populated places in view (largest first), up to context_places, not overlapping `avoid` boxes."""
        n = int(self.s['context_places'] or 0)
        if n <= 0:
            return []
        km = view.km_across()
        box = view.lonlat_box(0)
        cand = []
        for kind, rings, bbox, p in layer('places', self.detail(km)):
            if _visible(bbox, box):
                pop = p.get('pop_max') or p.get('POP_MAX') or 0
                if pop >= self.s['context_min_pop']:
                    cand.append((pop, p.get('name') or p.get('NAME'), rings[0][0]))
        cand.sort(key=lambda c: -c[0])
        out = []
        for pop, name, (lon, lat) in cand[:n * 4]:
            if len(out) >= n:
                break
            x, y = view.px(*merc(lon, lat))
            out.append((name, float(x), float(y)))
        return out


def _text(d, xy, text, font, fill, halo, halo_w):
    d.text(xy, text, font=font, fill=fill, stroke_width=halo_w, stroke_fill=halo)


def _place_label(d, x, y, text, font, off, W, H, used, margin):
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    for dx, dy in ((off[0], off[1] - th), (off[0], -off[1]), (-off[0] - tw, off[1] - th), (-off[0] - tw, -off[1])):
        lx, ly = x + dx, y + dy
        r = (lx - 4, ly - 4, lx + tw + 4, ly + th + 4)
        if r[0] < margin or r[1] < margin or r[2] > W - margin or r[3] > H - margin:
            continue
        if any(not (r[2] < u[0] or r[0] > u[2] or r[3] < u[1] or r[1] > u[3]) for u in used):
            continue
        used.append(r)
        return lx - bb[0], ly - bb[1]
    return None


# ------------------------------------------------------------------ timeline of an animation

class Plan:
    """Everything that varies with time for one spec: views, route progress, stop arrival times."""

    def __init__(self, s, width, height):
        import numpy as np
        self.s, self.w, self.h = s, int(width), int(height)
        self.notes = []
        if s.get('clips') or s.get('points'):
            self.stops, self.notes = stops(s.get('clips'), s.get('points'), s['order'], s['merge_km'])
        else:
            self.stops = []
        if not self.stops and not s.get('center'):
            raise ValueError('no stops with GPS: ' + '; '.join(self.notes[:6]))
        self.dur = max(1e-3, s['duration'])
        self.P, self.stop_idx = (route_path(self.stops, s['path'], s['arc_bend']) if len(self.stops) >= 1
                                 else (np.zeros((0, 2)), []))
        if len(self.P) >= 2:
            seg = np.linalg.norm(np.diff(self.P, axis=0), axis=1)
            cum = np.concatenate([[0], np.cumsum(seg)])
            self.stop_frac = [float(cum[i] / cum[-1]) if cum[-1] > 0 else 0 for i in self.stop_idx]
            if s['pace'] == 'stops':     # equal time per leg
                self.stop_frac_t = [i / (len(self.stops) - 1) for i in range(len(self.stops))]
            else:
                self.stop_frac_t = self.stop_frac
        else:
            self.stop_frac = self.stop_frac_t = [0.0] * len(self.stops)
        rs = s['route_start'] if s['route_start'] is not None else (0.0 if s['still'] else self.dur * 0.08)
        re_ = s['route_end'] if s['route_end'] is not None else (self.dur if s['still'] else self.dur * 0.85)
        if s['camera'] in ('zoom_in',) and s['route_end'] is None and not s['still']:
            re_ = self.dur * 0.55
        self.rs, self.re = float(rs), float(max(re_, rs + 1e-3))
        self.fit = fit_view(self.stops, self.w, self.h, s['fit_margin'], s['min_km_across']) if self.stops else None

    def progress(self, t):
        """Share of the route drawn (by length) at t."""
        if self.s['still'] or not self.s['route']:
            return 1.0 if self.s['route'] else 0.0
        u = ease((t - self.rs) / (self.re - self.rs), self.s['route_easing'])
        if self.s['pace'] == 'stops' and len(self.stops) >= 2:
            ft, fl = self.stop_frac_t, self.stop_frac
            for i in range(len(ft) - 1):
                if ft[i] <= u <= ft[i + 1]:
                    v = (u - ft[i]) / max(1e-9, ft[i + 1] - ft[i])
                    return fl[i] + (fl[i + 1] - fl[i]) * v
            return 1.0
        return u

    def arrival(self, i):
        """Time the route line reaches stop i."""
        if self.s['still']:
            return 0.0
        f = self.stop_frac_t[i] if self.s['pace'] == 'stops' else self.stop_frac[i]
        # invert the easing numerically
        lo, hi = self.rs, self.re
        for _ in range(40):
            mid = (lo + hi) / 2
            if self.progress(mid) < f - 1e-9:
                lo = mid
            else:
                hi = mid
        return hi if f > 0 else min(self.rs, hi)

    def target_stop(self):
        i = int(self.s['zoom_to'])
        return self.stops[i] if self.stops else None

    def view(self, t):
        s, W, H = self.s, self.w, self.h
        cam = s['camera']
        if s.get('center') and cam in ('fit', 'fixed') and (cam == 'fixed' or not self.stops):
            return view_for(s['center'][0], s['center'][1], s['km_across'] or 500.0, W, H)
        if cam == 'fixed':
            return self.fit if not s.get('km_across') else view_for(
                *unmerc_pair(self.fit.cx, self.fit.cy), s['km_across'], W, H)
        if cam == 'fit':
            if s.get('km_across'):
                lat, lon = unmerc_pair(self.fit.cx, self.fit.cy)
                return view_for(lat, lon, s['km_across'], W, H)
            return self.fit
        if cam == 'follow':
            _, head, _ = cut_path(self.P, self.progress(t)) if len(self.P) else (None, None, None)
            if head is None:
                return self.fit
            lon, lat = unmerc(head[0], head[1])
            return view_for(float(lat), float(lon), s['follow_km'], W, H)
        if cam in ('zoom_in', 'zoom_out'):
            st = self.target_stop()
            close = view_for(st['lat'], st['lon'], s['zoom_km'], W, H)
            wide = self.fit
            z0 = s['zoom_start'] if s['zoom_start'] is not None else (self.re + 0.05 * self.dur if cam == 'zoom_in'
                                                                      else 0.0)
            z1 = s['zoom_end'] if s['zoom_end'] is not None else (self.dur * 0.95 if cam == 'zoom_in'
                                                                  else self.dur * 0.35)
            u = ease((t - z0) / max(1e-6, z1 - z0), s['easing'])
            a, b = (wide, close) if cam == 'zoom_in' else (close, wide)
            return lerp_view(a, b, u)
        if cam == 'keys':
            keys = sorted(s['keys'], key=lambda k: float(k['t']))
            views = [self._key_view(k, t) for k in keys]
            if t <= float(keys[0]['t']):
                return views[0]
            for (ka, va), (kb, vb) in zip(zip(keys, views), list(zip(keys, views))[1:]):
                if float(ka['t']) <= t <= float(kb['t']):
                    u = ease((t - float(ka['t'])) / max(1e-6, float(kb['t']) - float(ka['t'])),
                             kb.get('easing', s['easing']))
                    return lerp_view(va, vb, u)
            return views[-1]
        return self.fit

    def _key_view(self, k, t):
        W, H = self.w, self.h
        c = k.get('center', 'fit')
        if c == 'fit':
            v = self.fit
            if k.get('km_across'):
                lat, lon = unmerc_pair(v.cx, v.cy)
                return view_for(lat, lon, k['km_across'], W, H)
            return v
        if c == 'marker':
            _, head, _ = cut_path(self.P, self.progress(t))
            lon, lat = unmerc(head[0], head[1])
            return view_for(float(lat), float(lon), k.get('km_across', self.s['follow_km']), W, H)
        if isinstance(c, int):
            st = self.stops[c]
            return view_for(st['lat'], st['lon'], k.get('km_across', self.s['zoom_km']), W, H)
        return view_for(float(c[0]), float(c[1]), k.get('km_across', self.s['zoom_km']), W, H)


def unmerc_pair(x, y):
    lon, lat = unmerc(x, y)
    return float(lat), float(lon)


# ------------------------------------------------------------------ frames

def draw_frame(painter, plan, t, base_cache=None):
    """One RGBA PIL frame at time t."""
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
    s, st, k = plan.s, painter.st, painter.k
    W, H = painter.w, painter.h
    view = plan.view(t)
    key = (round(view.cx, 12), round(view.cy, 12), round(view.ww, 14))
    if base_cache is not None and key in base_cache:
        img = base_cache[key].copy()
    else:
        img = painter.base(view)
        if base_cache is not None:
            base_cache.clear()
            base_cache[key] = img.copy()
    head = None
    if s['route'] and len(plan.P) >= 2:
        frac = plan.progress(t)
        full = np.stack(view.px(plan.P[:, 0], plan.P[:, 1]), 1)
        if s['show_ahead']:
            pts = [(full * 8).astype(np.int32)]
            _blend_draw(img, lambda im, c: cv2.polylines(im, pts, False, c, max(1, round(st['route_width'] * k * 0.6)),
                                                         cv2.LINE_AA, shift=3), st['route_ahead'])
        part, head_w, _ = cut_path(plan.P, frac)
        if frac > 0:
            pp = np.stack(view.px(part[:, 0], part[:, 1]), 1)
            pts = [(pp * 8).astype(np.int32)]
            cw = round((st['route_width'] + 2 * st['route_casing_width']) * k)
            if st['route_casing_width'] > 0:
                _blend_draw(img, lambda im, c: cv2.polylines(im, pts, False, c, max(1, cw), cv2.LINE_AA, shift=3),
                            st['route_casing'])
            _blend_draw(img, lambda im, c: cv2.polylines(im, pts, False, c, max(1, round(st['route_width'] * k)),
                                                         cv2.LINE_AA, shift=3), st['route'])
        head = view.px(head_w[0], head_w[1])
    pil = Image.fromarray(img, 'RGB').convert('RGBA')
    d = ImageDraw.Draw(pil)
    margin = s['safe_margin'] * H
    used = []
    # stop dots
    stop_px = []
    for i, sp in enumerate(plan.stops):
        x, y = view.px(*merc(sp['lon'], sp['lat']))
        stop_px.append((float(x), float(y)))
    arrivals = [plan.arrival(i) for i in range(len(plan.stops))] if s['route'] else [0.0] * len(plan.stops)
    if s['stop_dots']:
        r = st['stop_radius'] * k
        for (x, y), ta in zip(stop_px, arrivals):
            if t + 1e-9 >= ta:
                d.ellipse((x - r, y - r, x + r, y + r), fill=gc.rgba(st['stop']), outline=gc.rgba(st['stop_ring']),
                          width=max(1, round(3 * k)))
    # marker
    if s['marker'] and head is not None and s['route']:
        x, y = head
        r = st['marker_radius'] * k
        if s['marker'] == 'pin':
            d.polygon([(x, y), (x - r * 0.8, y - r * 1.6), (x + r * 0.8, y - r * 1.6)], fill=gc.rgba(st['marker']))
            d.ellipse((x - r, y - r * 2.6, x + r, y - r * 0.6), fill=gc.rgba(st['marker']),
                      outline=gc.rgba(st['marker_ring']), width=max(1, round(3 * k)))
        else:
            d.ellipse((x - r * 1.8, y - r * 1.8, x + r * 1.8, y + r * 1.8), fill=gc.rgba(st['marker'])[:3] + (70,))
            d.ellipse((x - r, y - r, x + r, y + r), fill=gc.rgba(st['marker']), outline=gc.rgba(st['marker_ring']),
                      width=max(1, round(3 * k)))
    # title
    if s.get('title'):
        f = gc.font(st['font'], st['title_size'] * k, 800)
        bb = d.textbbox((0, 0), s['title'], font=f)
        pad = 18 * k
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        x0 = margin if 'left' in s['title_at'] else (W - tw) / 2 if 'center' in s['title_at'] else W - margin - tw - 2 * pad
        y0 = margin if 'top' in s['title_at'] else H - margin - th - 2 * pad
        d.rounded_rectangle((x0, y0, x0 + tw + 2 * pad, y0 + th + 2 * pad), radius=pad * 0.6,
                            fill=gc.rgba(st['title_box']))
        d.text((x0 + pad - bb[0], y0 + pad - bb[1]), s['title'], font=f, fill=gc.rgba(st['title_color']))
        used.append((x0, y0, x0 + tw + 2 * pad, y0 + th + 2 * pad))
    # attribution box reserved first
    attr = attribution_text(s, plan)
    if attr:
        f = gc.font(st['font'], st['attribution_size'] * k, 500)
        bb = d.textbbox((0, 0), attr, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        x0 = W - margin * 0.5 - tw if 'right' in s['attribution_at'] else margin * 0.5
        y0 = H - margin * 0.5 - th if 'bottom' in s['attribution_at'] else margin * 0.5
        d.text((x0 - bb[0], y0 - bb[1]), attr, font=f, fill=gc.rgba(st['attribution_color']),
               stroke_width=max(1, round(2 * k)), stroke_fill=gc.rgba(st['label_halo']))
        used.append((x0 - 4, y0 - 4, x0 + tw + 4, y0 + th + 4))
    # stop labels
    if s['labels'] in ('stops', 'all'):
        f = gc.font(st['font'], st['label_size'] * k, st['label_weight'])
        rr = st['stop_radius'] * k
        off = (s['label_offset'][0] * k + rr * 0.5, s['label_offset'][1] * k - rr * 0.5)
        seen = set()
        for sp, (x, y), ta in zip(plan.stops, stop_px, arrivals):
            if t + 1e-9 < ta or sp['label'] in seen:
                continue
            a = 1.0 if s['label_fade'] <= 0 or s['still'] else min(1.0, (t - ta) / s['label_fade'])
            if a <= 0:
                continue
            pos = _place_label(d, x, y, sp['label'], f, off, W, H, used, margin * 0.5)
            if pos is None:
                continue
            seen.add(sp['label'])
            fill = gc.rgba(st['label'])
            halo = gc.rgba(st['label_halo'])
            _text(d, pos, sp['label'], f, fill[:3] + (int(fill[3] * a),), halo[:3] + (int(halo[3] * a),),
                  max(1, round(4 * k)))
    if s['labels'] in ('context', 'all') or (s['labels'] == 'stops' and s['context_places']):
        f = gc.font(st['font'], st['context_size'] * k, st['context_weight'])
        names = {sp['label'] for sp in plan.stops}
        for name, x, y in painter.context_labels(view, used):
            if not name or name in names:
                continue
            if not (0 <= x <= W and 0 <= y <= H):
                continue
            pos = _place_label(d, x, y, name, f, (6 * k, -6 * k), W, H, used, margin * 0.5)
            if pos is None:
                continue
            rr = 3 * k
            d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=gc.rgba(st['context_label']))
            _text(d, pos, name, f, gc.rgba(st['context_label']), gc.rgba(st['label_halo']), max(1, round(3 * k)))
    return pil, view


def attribution_text(s, plan=None):
    a = s.get('attribution')
    if a in (None, False, '', 'none'):
        return ''
    if a != 'auto':
        return str(a)
    bits = [ATTRIBUTION_NE]
    if plan is not None and any(sp.get('place_source') == 'GeoNames' for sp in plan.stops) and s['labels'] != 'none':
        bits.append(ATTRIBUTION_GEONAMES)
    return '  |  '.join(bits)


def describe(s, plan=None):
    n = len(plan.stops) if plan else '?'
    names = ' -> '.join(sp['label'] for sp in plan.stops[:6]) if plan else ''
    return f"map ({s['style']}, camera {s['camera']}), {n} stops{': ' + names if names else ''}"


# ------------------------------------------------------------------ render

def _lock(name, est):
    import contextlib
    if est <= 30:
        return contextlib.nullcontext()
    import letitedit.core.render_lock as render_lock
    return render_lock.slot(name, caller_pids=render_lock.ancestors())


def estimate_s(s, width, height, fps):
    n = 1 if s['still'] else max(1, round(s['duration'] * fps))
    per = 0.05 + 0.12 * (width * height) / (1920 * 1080) * (1.6 if 'relief' in s['layers'] else 1.0)
    return 2.0 + n * per


def render(spec, width=1920, height=1080, fps=30.0, out_dir=None, out=None, progress=None, sheet_count=6):
    """Render the map clip (or one PNG with still=True). Returns {'path', 'cached', 'alpha', 'format', 'frames',
    'seconds', 'sheet', 'stops', 'notes', 'attribution', 'sidecar'}."""
    s = normalise(spec)
    out_dir = Path(out_dir or CACHE / 'out')
    out_dir.mkdir(parents=True, exist_ok=True)
    dg = digest(s, width, height, fps)
    fmt = 'png' if s['still'] else s['format']
    ext = '.png' if s['still'] else ('' if fmt == 'png' else '.' + fmt)
    path = Path(out) if out else out_dir / f'generated-map-{s["style"]}-{s["camera"]}-{dg}{ext}'
    side = Path(str(path) + '.json') if not (fmt == 'png' and not s['still']) else path / 'generated.json'
    if path.exists() and side.exists() and not out:
        meta = json.loads(side.read_text(encoding='utf-8-sig'))
        return {'path': str(path), 'cached': True, 'alpha': False, 'format': fmt, 'sheet': meta.get('sheet'),
                'stops': meta.get('stops'), 'notes': meta.get('notes'), 'attribution': meta.get('attribution'),
                'frames': meta.get('frames'), 'sidecar': str(side), 'seconds': 0}
    t0 = time.monotonic()
    plan = Plan(s, width, height)
    painter = Painter(s, width, height)
    attr = attribution_text(s, plan)
    est = estimate_s(s, width, height, fps)
    sheet = None
    with _lock(f'shotcut map {path.name}', est):
        if s['still']:
            im, _ = draw_frame(painter, plan, s['duration'])
            tmp = path.with_name(path.stem + '.part.png')
            im.convert('RGB').save(tmp, pnginfo=_png_info(describe(s, plan), attr))
            os.replace(tmp, path)
            total = 1
        else:
            total = max(1, round(s['duration'] * fps))
            tmp = path.with_name(path.stem + '.part' + path.suffix) if fmt != 'png' else path
            enc = gc.Encoder(tmp, width, height, fps, fmt, crf=s['crf'], kind='map', title=describe(s, plan),
                             comment=f'map drawn from GPS and offline data; {attr}')
            picks = set(gc.even_frames(total, sheet_count)) if sheet_count else set()
            shots, labels, cache = [], [], {}
            try:
                for f in range(total):
                    t = f / fps
                    im, _ = draw_frame(painter, plan, t, cache)
                    enc.add(im)
                    if f in picks:
                        shots.append(im.copy())
                        labels.append(f'{t:.2f}s')
                    if progress and f % 10 == 0:
                        progress(f / total, f'frame {f}/{total}')
                enc.close()
            except Exception:
                enc.abort()
                raise
            if fmt != 'png':
                os.replace(tmp, path)
            if shots:
                sheet = gc.sheet(shots, labels, str(path) + '.sheet.jpg' if fmt != 'png' else path / 'sheet.jpg',
                                 checker=False)
    meta = {'kind': 'map', 'spec': s, 'width': width, 'height': height, 'fps': fps, 'frames': total,
            'stops': plan.stops, 'notes': plan.notes, 'attribution': attr, 'sheet': sheet,
            'description': describe(s, plan),
            'data': 'Natural Earth v5.1.2 (public domain); place names GeoNames cities1000 (CC BY 4.0)'}
    side = gc.sidecar(path, meta)
    return {'path': str(path), 'cached': False, 'alpha': False, 'format': fmt, 'frames': total,
            'seconds': round(time.monotonic() - t0, 1), 'sheet': sheet, 'stops': plan.stops, 'notes': plan.notes,
            'attribution': attr, 'sidecar': side}


def _png_info(title, attr):
    from PIL.PngImagePlugin import PngInfo
    i = PngInfo()
    i.add_text('Title', f'Generated map: {title}')
    i.add_text('Comment', f'generated by letitedit - not camera footage; {attr}')
    i.add_text('letitedit_ai_generated', '1')
    return i


def preview(spec, width=640, height=360, fps=30.0, count=6, times=None, out=None, cols=3):
    s = normalise(spec)
    t0 = time.monotonic()
    plan = Plan(s, width, height)
    painter = Painter(s, width, height)
    if s['still']:
        times = [s['duration']]
    elif not times:
        total = max(1, round(s['duration'] * fps))
        times = [f / fps for f in gc.even_frames(total, count)]
    ims, labels, views = [], [], []
    for t in times:
        im, v = draw_frame(painter, plan, float(t))
        ims.append(im)
        labels.append(f'{float(t):.2f}s  {v.km_across():.0f} km across')
        views.append(round(v.km_across(), 1))
    dg = digest(s, width, height, fps)
    out = Path(out or CACHE / 'previews' / f'generated-map-preview-{dg}.jpg')
    sheet = gc.sheet(ims, labels, out, cols=cols, tile_w=min(width, 480), checker=False)
    return {'sheet': sheet, 'times': [float(t) for t in times], 'km_across': views, 'stops': plan.stops,
            'notes': plan.notes, 'attribution': attribution_text(s, plan), 'seconds': round(time.monotonic() - t0, 1),
            'spec': s}


# ------------------------------------------------------------------ made items {map: {...}, len?}

def recipe(item):
    return {'kind': 'map', 'spec': normalise(dict(item['map'], still=False, format='mp4'))}


def view(r):
    return {'map': r['spec']}


def default_len(item):
    return float(dict(DEFAULTS, **{k: v for k, v in item['map'].items() if v is not None})['duration'])


def label(r):
    return f"generated map: {r['spec']['style']} {r['spec']['camera']}"


def render_recipe(r, width, height, fps, out_dir):
    res = render(r['spec'], width, height, fps, out_dir=out_dir)
    notes = [f"attribution: {res['attribution']}"] if res.get('attribution') else []
    notes += res.get('notes') or []
    return {'path': res['path'], 'cached': res['cached'], 'alpha': False, 'notes': notes}
