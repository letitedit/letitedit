"""The timing signal store (TIMING-SPEC.md): one set of frame-accurate measurements of an edit's motion, rhythm and
timing that every timing view and check reads.

    signals(source, start=None, end=None, lanes=None, refresh=False, settings=None) -> dict
    register_lane(name, compute, depends=(), version=1, optional=())   # compute(ctx) -> dict for that lane
    lanes() -> {name: {depends, optional, version, module}}
    threshold(name, default=None) / thresholds(prefix)   values from timing_thresholds.json
    array(sig, lane, key, sub=None) -> numpy float array of a per-frame series (None -> NaN)
    load_plugins() -> imports the bridge modules that register lanes or views

source: a project (.mlt path, a managed episode/cut folder, or 'live' for the open editor) or a video file.
A project is analysed as the viewer gets it: a preview render of its timeline (same fps, small size, with sound,
made by melt in cached chunks: timing_render.py). A video file is analysed itself.

Result: {schema_version, source, kind: project|video, fps, frames, duration_s, size, analysed_size, render, key,
project_revision, source_fingerprints, checked_ranges, unchecked_ranges, lanes: {name: {method, version, settings,
warnings, unsupported, ...data}}, warnings, unsupported, seconds, conventions}.

Conventions (also in every result's 'conventions'): frames are indexes on the source's own frame grid (a project:
its timeline frames; a video: round((pts - start_time) * fps)); every time is also given in seconds (t = f / fps);
frame ranges are half-open: f0 is the first frame, f1 the first frame after (t1 = f1 / fps is the end time);
per-frame series are lists of length `frames` aligned to frame index 0..frames-1 (None where not measured);
audio series are every 10 ms from t = 0.

Lanes built here: edit, motion, visual_beats, motion_events, attention, shots, audio (see each compute function's
docstring and timing_motion.py / timing_audio.py). Other modules register theirs at import (speech: prosody.py,
music: music_sync.py, meaning: motion_meaning.py).

Cache: <cache>\\timing\\<key>\\<lane>-v<version>-<identity>.json; key = hash of the source (project: the render
fingerprint of the whole timeline + the edit script's content; video: the file's content key) + the preview
settings + the analysed range. identity = hash of the lane's version, its settings and its dependencies'
identities, so a lane recomputes alone when its code or settings change. Expensive per-frame features are cached
per render chunk / file (timing_motion), so a small edit re-analyses only the chunks it changed.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import hashlib
import json
import math
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

SCHEMA_VERSION = 1
CACHE_ROOT = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
CACHE = CACHE_ROOT / 'timing'
THRESHOLDS_FILE = HERE / 'timing_thresholds.json'
FFMPEG = Path(os.environ.get('LETITEDIT_APP', os.path.join(_SAI_ROOT, 'app'))) / 'ffmpeg.exe'
VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.webm', '.mts', '.m2ts', '.mxf', '.wmv', '.mpg', '.mpeg', '.ts'}
CONVENTIONS = ('frames are indexes on the source frame grid (t = f / fps); ranges are half-open [f0, f1): f0 is the '
               'first frame, f1 the first frame after; per-frame series have one value per frame (None = not '
               'measured); audio series are every 10 ms from t = 0; boxes are [x0, y0, x1, y1] in 0-1 of the picture; '
               'angles are degrees on screen, 0 = right, 90 = up, 180 = left, 270 = down')

_LANES = {}                 # name -> {'compute', 'depends', 'optional', 'version', 'module'}
ON_REQUEST = {'meaning'}    # lanes that load a GPU model: never part of lanes=None
_LOCK = threading.RLock()
_KEY_LOCKS = {}


# ============================================================================ registry

def register_lane(name, compute, depends=(), version=1, optional=()):
    """Register (or replace) a lane. compute(ctx) -> dict (JSON-serialisable: lists, numbers, strings, None) with
    the lane's data plus 'method' (how it was measured), and optionally 'warnings', 'unsupported', 'settings'.
    depends: lanes computed first (their results are in ctx['lanes']). optional: lanes used when the caller asked
    for them too or when they are already cached (never computed just for this lane). version: bump when the
    computation changes (part of the cache identity)."""
    if not name or not isinstance(name, str) or not re.match(r'^[A-Za-z0-9_]+$', name):
        raise ValueError(f'lane name must be letters, digits or _: {name!r}')
    if not callable(compute):
        raise TypeError(f'lane {name!r}: compute must be callable')
    with _LOCK:
        _LANES[name] = {'compute': compute, 'depends': tuple(depends or ()), 'optional': tuple(optional or ()),
                        'version': int(version), 'module': public_module(compute)}
    return compute


def public_module(fn):
    """The module that defined fn, by the flat name lanes() and timing_views.views() have always reported
    ('joins', not 'letitedit.timing.joins')."""
    module = getattr(fn, '__module__', None)
    parts = module.split('.') if isinstance(module, str) else ()
    return parts[2] if len(parts) == 3 and parts[0] == 'letitedit' else module


def lanes(load=True):
    """{name: {depends, optional, version, module}} of every registered lane."""
    if load:
        load_plugins()
    with _LOCK:
        return {k: {'depends': list(v['depends']), 'optional': list(v['optional']), 'version': v['version'],
                    'module': v['module']} for k, v in sorted(_LANES.items())}


# ============================================================================ plugins

_PLUGINS = {'done': False, 'loaded': [], 'errors': {}}
_OWN = {'timing_signals', 'timing_views', 'timing_tools', 'timing_render', 'timing_motion', 'timing_audio',
        'rhythm_map', 'timing_slow'}
# The modules that register timing lanes or views, in load order: this layer's own first, then the others by
# name. A new one is added here (a test checks that every module calling register_lane( or register_view( is).
# Each is named as plugin_report() and the warnings name it, with the real module it is imported from.
PLUGINS = {'timing_motion': 'letitedit.timing.timing_motion', 'timing_audio': 'letitedit.timing.timing_audio',
           'rhythm_map': 'letitedit.timing.rhythm_map', 'timing_slow': 'letitedit.timing.timing_slow',
           'cut_inspect': 'letitedit.timing.cut_inspect', 'emotion_graph': 'letitedit.footage.emotion_graph',
           'joins': 'letitedit.timing.joins', 'motion_meaning': 'letitedit.timing.motion_meaning',
           'music_sync': 'letitedit.timing.music_sync', 'prosody': 'letitedit.timing.prosody',
           'trajectory': 'letitedit.timing.trajectory'}


def load_plugins(refresh=False):
    """Import the modules in PLUGINS that are present, once per process. Returns {'loaded': [...], 'errors':
    {module: message}}. LETITEDIT_TIMING_PLUGINS (comma-separated module names) adds modules outside that list."""
    with _LOCK:
        if _PLUGINS['done'] and not refresh:
            return {'loaded': list(_PLUGINS['loaded']), 'errors': dict(_PLUGINS['errors'])}
        _PLUGINS['done'] = True
    import importlib
    names = [mod for mod in PLUGINS if (HERE / f'{mod}.py').exists()]
    for extra in (os.environ.get('LETITEDIT_TIMING_PLUGINS') or '').split(','):
        if extra.strip() and extra.strip() not in names:
            names.append(extra.strip())
    for n in names:
        try:
            importlib.import_module(PLUGINS.get(n, n))
            with _LOCK:
                if n not in _PLUGINS['loaded']:
                    _PLUGINS['loaded'].append(n)
        except Exception as e:  # noqa: BLE001 - a broken plugin must not break the store
            with _LOCK:
                _PLUGINS['errors'][n] = f'{type(e).__name__}: {e}'
    return {'loaded': list(_PLUGINS['loaded']), 'errors': dict(_PLUGINS['errors'])}


def plugin_report():
    return {'loaded': list(_PLUGINS['loaded']), 'errors': dict(_PLUGINS['errors'])}


# ============================================================================ thresholds

_TH = {'mtime': None, 'data': {}}


def _thresholds_data():
    try:
        m = THRESHOLDS_FILE.stat().st_mtime_ns
    except OSError:
        return {}
    if _TH['mtime'] != m:
        try:
            _TH['data'] = json.loads(THRESHOLDS_FILE.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            _TH['data'] = {}
        _TH['mtime'] = m
    return _TH['data']


def threshold(name, default=None):
    """The value of a threshold key ('motion.static_speed') from timing_thresholds.json: a plain value, or the
    'value' of {value, unit, about}. default when the key is missing."""
    v = _thresholds_data().get(name, None)
    if isinstance(v, dict) and 'value' in v:
        return v['value']
    return default if v is None else v


def thresholds(prefix):
    """{short_key: value} of every key under 'prefix.' (e.g. thresholds('motion') -> {'static_speed': 0.02, ...})."""
    pre = prefix.rstrip('.') + '.'
    out = {}
    for k, v in _thresholds_data().items():
        if k.startswith(pre):
            out[k[len(pre):]] = v['value'] if isinstance(v, dict) and 'value' in v else v
    return out


def lane_settings(lane, defaults=None, given=None):
    """A lane's effective settings: its code defaults, then timing_thresholds.json '<lane>.*', then the caller's
    settings (signals(settings={lane: {...}}))."""
    out = dict(defaults or {})
    out.update(thresholds(lane))
    for k, v in (given or {}).items():
        if v is not None:
            out[k] = v
    return out


# ============================================================================ small helpers

def _hash(obj, n=16):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:n]


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(data, separators=(',', ':'), allow_nan=False, default=_jsonable))
        fh.flush()
        os.fsync(fh.fileno())
    for _ in range(30):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:          # a reader has it open (Windows): retry
            time.sleep(0.1)
    os.replace(tmp, path)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def _jsonable(x):
    try:
        import numpy as np
        if isinstance(x, np.ndarray):
            return clean(x.tolist())
        if isinstance(x, np.generic):
            return clean(x.item())
    except ImportError:
        pass
    if isinstance(x, Path):
        return str(x)
    if isinstance(x, (set, tuple)):
        return list(x)
    raise TypeError(f'not JSON-serialisable: {type(x).__name__}')


def clean(x, nd=None):
    """x with NaN/inf -> None, numpy -> Python, optionally floats rounded to nd decimals (recursively)."""
    try:
        import numpy as np
        if isinstance(x, np.ndarray):
            x = x.tolist()
        elif isinstance(x, np.generic):
            x = x.item()
    except ImportError:
        pass
    if isinstance(x, float):
        if not math.isfinite(x):
            return None
        return round(x, nd) if nd is not None else x
    if isinstance(x, dict):
        return {str(k): clean(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v, nd) for v in x]
    return x


def series(values, nd=4):
    """A per-frame/per-step series as a JSON list: floats rounded, NaN -> None."""
    return clean(values, nd)


def array(sig, lane, key, sub=None):
    """numpy float64 array of sig['lanes'][lane][key] (or [key][sub]); None -> NaN."""
    import numpy as np
    v = sig['lanes'][lane][key]
    if sub is not None:
        v = v[sub]
    return np.array([np.nan if a is None else a for a in v], dtype=np.float64)


def fr(t, fps):
    """Seconds -> frame index (nearest)."""
    return int(round(float(t) * float(fps)))


def add_cuts(sig, times, within_s=0.15):
    """A signals() result with cuts from outside the picture (a project's own clips: a jump cut on a person who stays in frame
    shows no picture change) added to its edit lane and its shots split there. Works on copies: the stored lanes don't change."""
    if not times:
        return sig
    fps, frames = float(sig['fps']), int(sig['frames'])
    lanes = dict(sig.get('lanes') or {})
    edit = dict(lanes.get('edit') or {})
    cuts = list(edit.get('cuts') or [])
    shot_lane = dict(lanes.get('shots') or {})
    shots = list(shot_lane.get('shots') or [])
    for t in times:
        f = fr(float(t), fps)
        if not 0 < f < frames or any(abs(int(c['f']) - f) <= within_s * fps for c in cuts):
            continue
        cuts.append({'f': f, 't': tsec(f, fps), 'kind': 'jump', 'detail': "from the project's clips"})
        for n, s in enumerate(shots):
            if s['f0'] < f < s['f1']:
                first, second = dict(s, f1=f, seconds=round((f - s['f0']) / fps, 3)), dict(s, f0=f, seconds=round((s['f1'] - f) / fps, 3))
                if 't1' in s:
                    first['t1'] = second['t0'] = tsec(f, fps)
                shots[n:n + 1] = [first, second]
                break
    edit['cuts'] = sorted(cuts, key=lambda c: int(c['f']))
    lanes['edit'] = edit
    if shots:
        shot_lane['shots'] = shots
        lanes['shots'] = shot_lane
    return dict(sig, lanes=lanes)


def tsec(f, fps, nd=4):
    return round(float(f) / float(fps), nd)


def clock(s):
    s = max(0.0, float(s))
    return f'{int(s // 60)}:{s % 60:06.3f}'


def in_window(events, f0=None, f1=None, key='f'):
    """Events (dicts with 'f' or 'f0'/'f1') overlapping [f0, f1)."""
    out = []
    for e in events or []:
        a = e.get('f0', e.get(key))
        b = e.get('f1', (a + 1) if a is not None else None)
        if a is None:
            continue
        if f0 is not None and b is not None and b <= f0:
            continue
        if f1 is not None and a >= f1:
            continue
        out.append(e)
    return out


# ============================================================================ the source

def _is_project(source):
    s = str(source).strip()
    if s.lower() in ('live', 'current', 'editor'):
        return True
    p = Path(s)
    if p.suffix.lower() == '.mlt':
        return True
    if p.is_dir():
        return True
    return False


def _resolve_project(source):
    """(path of the .mlt to read, note). 'live' writes a snapshot of the open editor's timeline."""
    s = str(source).strip()
    if s.lower() in ('live', 'current', 'editor'):
        import letitedit.review.checks as checks
        _, path = checks.resolve('live')
        return Path(path), 'live: a snapshot of the open editor (unsaved changes included)'
    import letitedit.timeline.edit_script as es
    return Path(es._resolve(s)), None


def read_markers(project):
    """Markers of a project: [{f, f1, t, t1, text, kind, name, label}] where text 'beat:b3:the fix' -> kind 'beat',
    name 'b3', label 'the fix'; 'chapter:The test' -> kind 'chapter', label 'The test'. f1 is the marker's end
    (exclusive) when it spans a range, else f + 1."""
    import xml.etree.ElementTree as ET
    import letitedit.timeline.timeline_model as tm
    root = ET.parse(str(project)).getroot()
    prof = root.find('profile')
    fps = int(prof.get('frame_rate_num', 30)) / int(prof.get('frame_rate_den', 1))
    out = []
    for ps in root.iter('properties'):
        if ps.get('name') != 'shotcut:markers':
            continue
        for m in ps:
            d = {q.get('name'): (q.text or '') for q in m.findall('property')}
            text = d.get('text', '')
            try:
                a = tm.clock_to_frames(d.get('start'), fps) or 0
                b = tm.clock_to_frames(d.get('end'), fps)
            except ValueError:
                continue
            b = a if b is None else b
            parts = text.split(':', 2)
            kind = parts[0].strip().lower() if len(parts) > 1 else ''
            name = label = ''
            if kind in ('beat', 'loop', 'setback', 'waive') and len(parts) == 3:
                name, label = parts[1].strip(), parts[2].strip()
            elif len(parts) >= 2:
                label = text.split(':', 1)[1].strip()
            out.append({'f': int(a), 'f1': int(max(b, a)) + 1, 't': tsec(a, fps), 't1': tsec(max(b, a) + 1, fps),
                        'text': text, 'kind': kind or 'note', 'name': name, 'label': label or text,
                        'color': d.get('color')})
    out.sort(key=lambda m: (m['f'], m['text']))
    return out


def _script_hash(script):
    s = {k: v for k, v in script.items() if k not in ('project', 'base')}
    return _hash(s, 24)


def grid_fps(info):
    """The frame grid of a video file: its nominal rate, or its average rate when the nominal one is far above
    it (phones write 120 or 600 for footage that runs at 25-30: a variable frame rate)."""
    fps = float(info['fps'])
    avg = float(info.get('avg_fps') or 0.0)
    if avg > 1.0 and fps > 1.5 * avg:
        return avg, True
    return fps, False


def _video_info(path):
    import letitedit.footage.shots as shots
    info = shots.probe(path)
    fps, vfr = grid_fps(info)
    dur = float(info['duration'] or 0.0)
    frames = info.get('frames') if not vfr else None
    frames = int(frames or int(round(dur * fps)))
    return info, fps, frames, dur


def _content_key(path):
    import letitedit.footage.shots as shots
    return shots.content_key(str(path))


# ============================================================================ signals

def default_store_settings():
    return lane_settings('store', {
        'preview_px': 640,          # long side of a project's preview render
        'max_whole_s': 1200.0,      # sources up to this long are analysed whole; longer: the asked range only
        'pad_s': 2.0,               # a long source's asked range is widened by this much each side
        'video': None,              # an existing render of the project to analyse instead of a preview render
    }, None)


def signals(source, start=None, end=None, lanes=None, refresh=False, settings=None):
    """Frame-accurate timing signals of `source` (see the module doc). start/end (seconds): the range that must be
    analysed (sources longer than store.max_whole_s are analysed only there; shorter ones whole). lanes: names
    (default: every registered lane). refresh: recompute the asked lanes (True) or a list of lane names; renders
    and per-chunk features stay cached unless settings={'store': {'refresh_render': True}}. settings: {lane:
    {key: value}} overrides, and 'store': {preview_px, max_whole_s, pad_s, video (an existing render of the project
    to analyse instead of rendering a preview; checked for frame count and rate)}."""
    t_all = time.time()
    load_plugins()
    settings = dict(settings or {})
    st_store = lane_settings('store', default_store_settings(), settings.get('store'))
    warnings, unsupported = [], []
    rep = plugin_report()
    for mod, err in rep['errors'].items():
        warnings.append(f'timing plugin {mod} failed to import: {err}')

    ctx = _context(source, start, end, st_store, warnings)
    key = ctx['key']
    with _LOCK:
        klock = _KEY_LOCKS.setdefault(key, threading.RLock())
    with klock:
        # the default leaves out lanes that run a vision model (meaning): asked for by name only
        want = list(lanes) if lanes else sorted(n for n in _LANES if n not in ON_REQUEST)
        unknown = [n for n in want if n not in _LANES]
        for n in unknown:
            warnings.append(f'no lane {n!r} is registered (registered: {", ".join(sorted(_LANES))})')
        want = [n for n in want if n in _LANES]
        order = _order(want)
        refresh_set = set(order) if refresh is True else set(refresh or ())
        computed, ids = {}, {}
        for name in order:
            spec = _LANES[name]
            st = lane_settings(name, getattr(spec['compute'], 'defaults', None), settings.get(name))
            dep_ids = {d: ids.get(d) for d in spec['depends']}
            ident = _hash({'v': spec['version'], 'st': st, 'deps': dep_ids, 'schema': SCHEMA_VERSION}, 10)
            ids[name] = ident
            f = Path(ctx['cache_dir']) / f'{name}-v{spec["version"]}-{ident}.json'
            data = None if name in refresh_set else _read_json(f)
            if data is None:
                deps = {d: computed[d] for d in spec['depends'] if d in computed}
                for d in spec['optional']:
                    if d in computed:
                        deps[d] = computed[d]
                # the lane's effective settings, plus the caller's own overrides for it under its name (some
                # modules read ctx['settings'][<lane>])
                lst = dict(st)
                lst.setdefault(name, dict(settings.get(name) or {}))
                lctx = dict(ctx['public'], lanes=deps, settings=lst, all_settings=settings, lane=name)
                t0 = time.time()
                try:
                    data = spec['compute'](lctx)
                    if not isinstance(data, dict):
                        raise TypeError(f'lane {name} returned {type(data).__name__}, not a dict')
                    data = clean(data)
                    data.setdefault('method', (spec['compute'].__doc__ or name).strip().splitlines()[0])
                    data['version'] = spec['version']
                    data.setdefault('settings', clean(st))
                    data.setdefault('warnings', [])
                    data.setdefault('unsupported', [])
                    data['seconds'] = round(time.time() - t0, 2)
                    data['identity'] = ident
                    _write_json(f, data)
                except Exception as e:  # noqa: BLE001 - one lane failing must not lose the others
                    data = {'error': f'{type(e).__name__}: {e}', 'method': name, 'version': spec['version'],
                            'settings': clean(st), 'warnings': [], 'unsupported': [],
                            'trace': traceback.format_exc()[-1500:], 'seconds': round(time.time() - t0, 2)}
                    warnings.append(f'lane {name} failed: {data["error"]}')
            computed[name] = data
        _merge_meaning_sizes(computed)
    out = {'schema_version': SCHEMA_VERSION, 'source': ctx['source'], 'kind': ctx['kind'], 'fps': ctx['fps'],
           'frames': ctx['frames'], 'duration_s': ctx['duration_s'], 'size': ctx['size'],
           'analysed_size': ctx['analysed_size'], 'render': ctx['render_path'], 'audio': ctx['audio'],
           'render_info': ctx['render_info'], 'key': key, 'project': ctx['project'],
           'project_revision': ctx['project_revision'], 'source_fingerprints': ctx['source_fingerprints'],
           'range': ctx['range_info'], 'checked_ranges': ctx['checked_ranges'],
           'unchecked_ranges': ctx['unchecked_ranges'], 'lanes': {n: computed[n] for n in order},
           'warnings': warnings + ctx['warnings'], 'unsupported': unsupported, 'conventions': CONVENTIONS,
           'cache_dir': ctx['cache_dir'], 'seconds': round(time.time() - t_all, 2)}
    return out


def _merge_meaning_sizes(computed):
    """Shots whose size is unknown (no face) take the meaning lane's shot-size label when both lanes were
    computed (the meaning lane depends on shots, so this happens after both; the cached shots file is unchanged).
    The basis says so and carries the label's accuracy."""
    sh, me = computed.get('shots'), computed.get('meaning')
    if not sh or not me or sh.get('error') or me.get('error'):
        return
    items = [m for m in (me.get('meaning') or me.get('items') or []) if isinstance(m, dict)
             and m.get('kind', 'shot') == 'shot']
    words = {'close-up': 'closeup', 'closeup': 'closeup', 'close up': 'closeup', 'medium': 'medium', 'wide': 'wide'}
    for s in sh.get('shots') or []:
        if s.get('size') != 'unknown' or s.get('black'):
            continue
        best = None
        for m in items:
            a, b = int(m.get('f0', -1)), int(m.get('f1', -1))
            ov = min(b, s['f1']) - max(a, s['f0'])          # both ranges half-open
            if ov > 0.5 * (s['f1'] - s['f0']) and (best is None or ov > best[0]):
                best = (ov, m)
        if best is None:
            continue
        lab = ((best[1].get('labels') or {}).get('size') or {})
        v = words.get(str(lab.get('value') or '').lower())
        if v:
            s['size'] = v
            acc = lab.get('accuracy')
            s['size_basis'] = (f'meaning lane (vision model) says {lab.get("value")}'
                               + (f', label accuracy {acc:.0%}' if isinstance(acc, (int, float)) else '')
                               + ('' if lab.get('trusted') else ', not trusted') + '; no face measured')
            s['size_from'] = 'meaning'


def _order(want):
    """Topological order of the wanted lanes and their dependencies."""
    out, seen = [], set()

    def visit(n, stack=()):
        if n in seen:
            return
        if n in stack:
            raise ValueError(f'lane dependency cycle: {" -> ".join(stack + (n,))}')
        spec = _LANES.get(n)
        if spec is None:
            return
        for d in spec['depends']:
            visit(d, stack + (n,))
        seen.add(n)
        out.append(n)
    for n in want:
        visit(n)
    # optional dependencies that are also wanted go first when that keeps the order valid
    return out


def _context(source, start, end, st, warnings):
    """Everything about the source a lane needs (renders the project preview when needed)."""
    t0 = time.time()
    src = str(source)
    pub = {'source': src, 'start': start, 'end': end}
    render_info = None
    if _is_project(src):
        import letitedit.timeline.edit_script as es
        import letitedit.timeline.timeline_model as tm
        path, note = _resolve_project(src)
        if note:
            warnings.append(note)
        script = es.read(path)
        timeline = tm.load(path)
        fps = float(timeline.fps)
        frames = int(timeline.frames)
        size = [int(timeline.profile['width']), int(timeline.profile['height'])]
        dur = frames / fps
        rng = _analysis_range(start, end, dur, fps, frames, st)
        import letitedit.timing.timing_render as timing_render
        if st.get('video'):
            render_info = timing_render.use_existing(path, st['video'], timeline, rng)
        else:
            render_info = timing_render.preview(path, timeline=timeline, f0=rng[0], f1=rng[1],
                                                px=int(st['preview_px']),
                                                refresh=bool(st.get('refresh_render')))
        warnings.extend(render_info.get('warnings') or [])
        video = render_info['video']
        audio = render_info.get('audio')
        analysed = render_info['size']
        fp = {'render': render_info['fingerprint'], 'script': _script_hash(script)}
        key = _hash({'kind': 'project', 'fp': fp, 'px': st['preview_px'], 'range': rng if rng[2] else None,
                     'video': render_info.get('existing_key')}, 20)
        markers = read_markers(path)
        pub.update(kind='project', project=str(path), script=script, timeline=timeline, markers=markers)
        project_revision = script.get('base')
        source_fps = {str(path): project_revision}
        if render_info.get('existing_key'):
            source_fps[str(st['video'])] = render_info['existing_key']
    else:
        p = Path(src)
        if not p.is_file():
            raise FileNotFoundError(f'no such file: {src}')
        if p.suffix.lower() not in VIDEO_EXT:
            warnings.append(f'{p.suffix} is not a usual video extension; analysing it as a video anyway')
        info, fps, frames, dur = _video_info(str(p))
        size = [int(info['w']), int(info['h'])]
        rng = _analysis_range(start, end, dur, fps, frames, st)
        ck = _content_key(str(p))
        key = _hash({'kind': 'video', 'ck': ck, 'range': rng if rng[2] else None}, 20)
        video = str(p.resolve())
        audio = None
        analysed = None
        script = None
        project_revision = None
        source_fps = {video: ck}
        pub.update(kind='video', project=None, script=None, timeline=None, markers=[], probe=info)
        if abs(float(info['fps']) - fps) > 0.01:
            warnings.append(f'variable frame rate: the file says {float(info["fps"]):.3f} fps but averages '
                            f'{fps:.3f}; frames are placed on a {fps:.3f} fps grid by their time stamps (short gaps '
                            'are filled from the frame before)')
        elif abs(float(info.get('avg_fps') or fps) - fps) > 0.02 * fps:
            warnings.append(f'variable frame rate: nominal {fps:.3f} fps, average {float(info["avg_fps"]):.3f}; '
                            'frames are placed on the nominal grid by their time stamps (short gaps are filled from '
                            'the frame before)')
    cache_dir = CACHE / key
    cache_dir.mkdir(parents=True, exist_ok=True)
    f0, f1, partial = rng
    checked = [{'f0': f0, 'f1': f1, 't0': tsec(f0, fps), 't1': tsec(f1, fps)}]
    unchecked = []
    if f0 > 0:
        unchecked.append({'f0': 0, 'f1': f0, 't0': 0.0, 't1': tsec(f0, fps), 'why': 'outside the analysed range'})
    if f1 < frames:
        unchecked.append({'f0': f1, 'f1': frames, 't0': tsec(f1, fps), 't1': tsec(frames, fps),
                          'why': 'outside the analysed range'})
    pub.update(video=video, audio=audio, fps=fps, frames=frames, duration_s=round(frames / fps, 4), size=size,
               analysed_size=analysed, cache_dir=str(cache_dir), range=[f0, f1], render=render_info,
               source_fingerprint=source_fps, key=key)
    return {'public': pub, 'key': key, 'cache_dir': str(cache_dir), 'source': src, 'kind': pub['kind'],
            'fps': fps, 'frames': frames, 'duration_s': round(frames / fps, 4), 'size': size,
            'analysed_size': analysed, 'render_path': video if pub['kind'] == 'project' else None,
            'audio': audio, 'render_info': _render_summary(render_info), 'project': pub.get('project'),
            'project_revision': project_revision, 'source_fingerprints': source_fps,
            'range_info': {'f0': f0, 'f1': f1, 't0': tsec(f0, fps), 't1': tsec(f1, fps), 'partial': partial},
            'checked_ranges': checked, 'unchecked_ranges': unchecked, 'warnings': [],
            'context_seconds': round(time.time() - t0, 2)}


def _render_summary(ri):
    if not ri:
        return None
    keep = ('video', 'audio', 'size', 'fps', 'frames', 'fingerprint', 'chunks_total', 'chunks_reused',
            'chunks_rendered', 'seconds', 'lock_wait_s', 'existing', 'method')
    return {k: ri.get(k) for k in keep if k in ri}


def _analysis_range(start, end, dur, fps, frames, st):
    """(f0, f1, partial): the whole source when it is short enough, else the asked range (padded)."""
    if dur <= float(st['max_whole_s']) or (start is None and end is None):
        return 0, frames, False
    pad = float(st['pad_s'])
    a = max(0.0, float(start or 0.0) - pad)
    b = min(dur, float(end if end is not None else dur) + pad)
    return max(0, fr(a, fps)), min(frames, max(fr(b, fps), fr(a, fps) + 1)), True


# ============================================================================ the edit lane

PICTURE_GRAPHICS = {'title_card', 'end_card'}      # graphics drawn on a full-frame background by default


def _rect_numbers(text, W, H):
    """'x y w h [opacity]' (px or %) -> (x, y, w, h, opacity) in px."""
    nums = re.findall(r'-?\d+(?:\.\d+)?%?', str(text))
    if len(nums) < 4:
        return None
    vals = []
    for i, n in enumerate(nums[:5]):
        if n.endswith('%'):
            v = float(n[:-1]) / 100.0
            vals.append(v * (W if i in (0, 2) else H) if i < 4 else v)
        else:
            vals.append(float(n))
    if len(vals) == 4:
        vals.append(1.0)
    return tuple(vals)


def _covers(item, W, H):
    """(covers_the_frame, why). A picture shrunk or moved by size_position so that it leaves part of the frame
    uncovered, or made see-through by opacity, does not replace the picture under it."""
    for e in item.get('effects') or []:
        if not isinstance(e, dict):
            continue
        if 'size_position' in e:
            sp = e['size_position']
            rects = []
            if isinstance(sp, str):
                rects = [_rect_numbers(sp, W, H)]
            elif isinstance(sp, dict):
                for k in sp.get('keys') or []:
                    v = k[1] if isinstance(k, (list, tuple)) and len(k) > 1 else k
                    rects.append(_rect_numbers(v if isinstance(v, str) else ' '.join(map(str, v))
                                               if isinstance(v, (list, tuple)) else v, W, H))
            for r in rects:
                if r is None:
                    continue
                x, y, w, h, o = r
                if x > 0.02 * W or y > 0.02 * H or x + w < 0.98 * W or y + h < 0.98 * H:
                    return False, 'size_position leaves part of the frame uncovered (an inset)'
                if o < 0.95:
                    return False, 'size_position opacity under 1'
        if 'opacity' in e:
            o = e['opacity']
            vals = []
            if isinstance(o, (int, float)):
                vals = [float(o)]
            elif isinstance(o, dict):
                vals = [float(k[1]) for k in o.get('keys') or [] if isinstance(k, (list, tuple)) and len(k) > 1
                        and isinstance(k[1], (int, float))]
            if vals and max(vals) < 0.95:
                return False, 'opacity under 1 throughout'
    return True, ''


def _fade(item, key):
    for e in item.get('effects') or []:
        if isinstance(e, dict) and key in e:
            v = e[key]
            try:
                s = float(v if not isinstance(v, dict) else v.get('len', 0))
            except (TypeError, ValueError):
                continue
            return s, bool(e.get('opacity'))
    return 0.0, False


def _ass_text(script):
    out = []
    for line in str(script or '').splitlines():
        if line.startswith('Dialogue:'):
            parts = line.split(',', 9)
            if len(parts) == 10:
                t = re.sub(r'\{[^}]*\}', '', parts[9]).replace('\\N', ' ').replace('\\n', ' ').strip()
                if t:
                    out.append(t)
    return ' / '.join(out)


def _graphic_text(g):
    p = g.get('params') or {}
    if g.get('template') == 'word_captions':
        return ' '.join(str(w[0]) for w in p.get('words') or [] if isinstance(w, (list, tuple)) and w)
    bits = []
    for k in ('title', 'text', 'name', 'subtitle', 'kicker', 'number', 'role', 'label', 'value'):
        v = p.get(k)
        if v not in (None, '') and not isinstance(v, (dict, list)):
            bits.append(str(v))
    return ' / '.join(bits)


def _what(it):
    for k in ('graphic', 'ass', 'freeze', 'color', 'ffmpeg', 'vfx', 'voice', 'raw', 'clip'):
        if k in it:
            return k
    return 'made'


def _edit_item_records(F, H, W, by_id, edit_sync, es, fps, graphics, items, pops, script, segs, warnings):
    for order, t in enumerate(script['tracks']):
        kind = t.get('kind', 'video')
        hide = t.get('hide') or ''
        for it, s, e in edit_sync.layout(t):
            at = es.to_seconds(it['at']) if it.get('at') is not None else s
            ln = float(it['len']) if it.get('len') is not None else (e - s)
            f0 = fr(at, fps)
            f1 = f0 + max(0, fr(ln, fps))
            if abs(at * fps - f0) > 0.02:
                warnings.append(f'item {it.get("id")} starts off the frame grid ({at * fps:.3f})')
            what = _what(it)
            rec = {'id': it.get('id'), 'track': t['name'], 'kind': kind, 'f0': f0, 'f1': min(f1, F),
                   't0': tsec(f0, fps), 't1': tsec(min(f1, F), fps), 'what': what}
            if 'clip' in it:
                rec.update(clip=it['clip'], in_s=it.get('in'), out_s=it.get('out'))
            elif 'freeze' in it:
                rec.update(clip=(it['freeze'] or {}).get('clip'), in_s=(it['freeze'] or {}).get('at'),
                           out_s=(it['freeze'] or {}).get('at'))
            if it.get('speed') not in (None, 1, 1.0):
                rec['speed'] = it['speed']
            if it.get('reverse'):
                rec['reverse'] = True
            if it.get('name'):
                rec['name'] = it['name']
            if 'mute' in (it.get('effects') or []):
                rec['muted'] = True
            tr = it.get('transition')
            if tr:
                trs = es.transition_spec(tr)
                rec['transition'] = {'type': trs.get('type', 'dissolve'), 'len_s': round(float(trs['len']), 4),
                                     'frames': fr(trs['len'], fps)}
            layer = 'audio' if kind == 'audio' else 'picture'
            if kind == 'video':
                if what == 'graphic':
                    g = it['graphic'] or {}
                    tpl = g.get('template')
                    bg = (g.get('params') or {}).get('background', 'dark')
                    if (tpl in PICTURE_GRAPHICS and bg not in (None, 'none', '')) or \
                            (g.get('source') and not (g.get('params') or {}).get('alpha')):
                        layer = 'picture'
                    else:
                        layer = 'graphic'
                    gk = 'caption' if tpl == 'word_captions' else 'graphic'
                    text = _graphic_text(g)
                    graphics.append({'f0': f0, 'f1': min(f1, F), 't0': tsec(f0, fps), 't1': tsec(min(f1, F), fps),
                                     'kind': gk, 'text': text, 'id': it.get('id'), 'track': t['name'],
                                     'template': tpl, 'visible': 'video' not in hide and hide != 'both'})
                    words = (g.get('params') or {}).get('words') if tpl == 'word_captions' else None
                    style = (g.get('params') or {}).get('style')
                    if words and style in ('pop', 'karaoke', 'highlight', 'word', None):
                        for w in words:
                            if isinstance(w, (list, tuple)) and len(w) >= 2:
                                pf = f0 + fr(float(w[1]), fps)
                                if pf < min(f1, F):
                                    pops.append({'f': pf, 't': tsec(pf, fps), 'text': str(w[0]), 'kind': 'word',
                                                 'id': it.get('id')})
                    else:
                        pops.append({'f': f0, 't': tsec(f0, fps), 'text': text[:60], 'kind': gk,
                                     'id': it.get('id')})
                elif what == 'ass':
                    layer = 'graphic'
                    text = _ass_text(it['ass'] if isinstance(it['ass'], str) else (it['ass'] or {}).get('script'))
                    graphics.append({'f0': f0, 'f1': min(f1, F), 't0': tsec(f0, fps), 't1': tsec(min(f1, F), fps),
                                     'kind': 'text', 'text': text, 'id': it.get('id'), 'track': t['name'],
                                     'visible': 'video' not in hide and hide != 'both'})
                    pops.append({'f': f0, 't': tsec(f0, fps), 'text': text[:60], 'kind': 'text',
                                 'id': it.get('id')})
                elif what in ('voice', 'raw'):
                    layer = 'none'
                for e2 in it.get('effects') or []:
                    if isinstance(e2, dict) and 'text' in e2 and isinstance(e2['text'], str):
                        graphics.append({'f0': f0, 'f1': min(f1, F), 't0': tsec(f0, fps),
                                         't1': tsec(min(f1, F), fps), 'kind': 'text', 'text': e2['text'],
                                         'id': it.get('id'), 'track': t['name'], 'on_clip': True,
                                         'visible': 'video' not in hide and hide != 'both'})
                        pops.append({'f': f0, 't': tsec(f0, fps), 'text': e2['text'][:60], 'kind': 'text',
                                     'id': it.get('id')})
                if layer == 'picture':
                    cov, why = _covers(it, W, H)
                    if not cov:
                        layer = 'inset'
                        rec['inset_why'] = why
                if hide in ('video', 'both') and layer in ('picture', 'inset', 'graphic'):
                    rec['hidden'] = True
                    layer = 'hidden'
            rec['layer'] = layer
            fi, fi_op = _fade(it, 'fade_in')
            fo, fo_op = _fade(it, 'fade_out')
            if fi:
                rec['fade_in'] = {'s': fi, 'frames': fr(fi, fps), 'opacity': fi_op}
            if fo:
                rec['fade_out'] = {'s': fo, 'frames': fr(fo, fps), 'opacity': fo_op}
            if it.get('split_edit'):
                rec['split_edit'] = it['split_edit']
            items.append(rec)
            by_id[rec['id']] = rec
            if layer == 'picture' and f1 > f0:
                segs.append((order, f0, min(f1, F), rec))


def _edit_picture_runs(F, segs):
    # the top picture at every frame
    top = [None] * F
    for order, f0, f1, rec in sorted(segs, key=lambda s: s[0]):
        for f in range(max(0, f0), min(F, f1)):
            top[f] = rec['id']
    runs = []
    f = 0
    while f < F:
        g = f
        while g + 1 < F and top[g + 1] == top[f]:
            g += 1
        runs.append([f, g + 1, top[f]])
        f = g + 1
    return runs


def _edit_cut_records(by_id, fps, runs, transitions):
    cuts = []
    for (a0, a1, aid), (b0, b1, bid) in zip(runs, runs[1:]):
        A, B = by_id.get(aid), by_id.get(bid)
        c = {'f': b0, 't': tsec(b0, fps), 'kind': 'cut', 'from_item': aid, 'to_item': bid,
             'from_clip': (A or {}).get('clip'), 'to_clip': (B or {}).get('clip'),
             'from_track': (A or {}).get('track'), 'to_track': (B or {}).get('track'), 'f0': b0, 'f1': b0}
        if A is None:
            c['detail'] = 'from black'
        if B is None:
            c['detail'] = 'to black'
        trn = (B or {}).get('transition')
        if B is not None and trn and B['f0'] == b0 and A is not None:
            n = int(trn['frames'])
            c.update(kind='dissolve' if trn['type'] in ('dissolve',) else 'dissolve' if trn['type'] != 'cut' else
                     'cut', f0=b0, f1=b0 + n, f=b0 + n // 2, t=tsec(b0 + n // 2, fps), transition=trn['type'])
            if trn['type'] not in ('dissolve', 'cut'):
                c['detail'] = f'wipe ({trn["type"]})'
            transitions.append({'f0': b0, 'f1': b0 + n, 't0': tsec(b0, fps), 't1': tsec(b0 + n, fps),
                                'kind': c['kind'], 'type': trn['type'], 'from_item': aid, 'to_item': bid,
                                'track': B['track']})
        else:
            fo = (A or {}).get('fade_out') if A is not None and A['f1'] == b0 else None
            fi = (B or {}).get('fade_in') if B is not None and B['f0'] == b0 else None
            if fi and fi.get('opacity') and A is not None:
                n = int(fi['frames'])
                c.update(kind='dissolve', f0=b0, f1=b0 + n, f=b0 + n // 2, t=tsec(b0 + n // 2, fps),
                         transition='opacity fade-in of the overlay')
                transitions.append({'f0': b0, 'f1': b0 + n, 't0': tsec(b0, fps), 't1': tsec(b0 + n, fps),
                                    'kind': 'dissolve', 'type': 'opacity fade', 'from_item': aid, 'to_item': bid,
                                    'track': B['track']})
            elif fo and fo.get('opacity') and B is not None and not fi:
                n = int(fo['frames'])
                c.update(kind='dissolve', f0=b0 - n, f1=b0, f=b0 - n // 2, t=tsec(b0 - n // 2, fps),
                         transition='opacity fade-out of the overlay')
                transitions.append({'f0': b0 - n, 'f1': b0, 't0': tsec(b0 - n, fps), 't1': tsec(b0, fps),
                                    'kind': 'dissolve', 'type': 'opacity fade', 'from_item': aid, 'to_item': bid,
                                    'track': A['track']})
            elif fo or fi:
                n0 = int(fo['frames']) if fo else 0
                n1 = int(fi['frames']) if fi else 0
                c.update(kind='fade', f0=b0 - n0, f1=b0 + n1, transition='through black')
                transitions.append({'f0': b0 - n0, 'f1': b0 + n1, 't0': tsec(b0 - n0, fps),
                                    't1': tsec(b0 + n1, fps), 'kind': 'fade', 'type': 'brightness fade',
                                    'from_item': aid, 'to_item': bid, 'track': (B or A)['track']})
        if A is not None and B is not None and A.get('clip') and A.get('clip') == B.get('clip'):
            c['same_clip'] = True
            try:
                c['source_jump_s'] = round(float(B.get('in_s')) - float(A.get('out_s')), 3)
            except (TypeError, ValueError):
                pass
        cuts.append(c)
    return cuts


def _edit_project(ctx):
    """Cuts from the edit script: the top picture at every frame (later video tracks over earlier ones; graphics,
    text and insets don't replace the picture), a change of that picture is a cut (dissolve: a same-track
    transition or an opacity fade-in of an overlay; fade: through black or a brightness fade)."""
    import letitedit.timeline.edit_sync as edit_sync
    import letitedit.timeline.edit_script as es
    script, fps, F = ctx['script'], float(ctx['fps']), int(ctx['frames'])
    W, H = ctx['size']
    warnings = []
    items, graphics, transitions, split_edits, pops = [], [], [], [], []
    segs = []          # picture segments per track: (track_order, f0, f1, item_record)
    by_id = {}
    _edit_item_records(F, H, W, by_id, edit_sync, es, fps, graphics, items, pops, script, segs, warnings)
    runs = _edit_picture_runs(F, segs)
    cuts = _edit_cut_records(by_id, fps, runs, transitions)
    # fades from black at the very start / to black at the end
    for rec in items:
        if rec['layer'] != 'picture':
            continue
        if rec.get('fade_in') and rec['f0'] == 0 and not rec['fade_in'].get('opacity'):
            n = rec['fade_in']['frames']
            transitions.append({'f0': 0, 'f1': n, 't0': 0.0, 't1': tsec(n, fps), 'kind': 'fade',
                                'type': 'fade in from black', 'from_item': None, 'to_item': rec['id'],
                                'track': rec['track']})
        if rec.get('fade_out') and rec['f1'] >= F and not rec['fade_out'].get('opacity'):
            n = rec['fade_out']['frames']
            transitions.append({'f0': F - n, 'f1': F, 't0': tsec(F - n, fps), 't1': tsec(F, fps), 'kind': 'fade',
                                'type': 'fade out to black', 'from_item': rec['id'], 'to_item': None,
                                'track': rec['track']})
    # split edits (J/L cuts): the moved sound and the picture cut it crosses
    for rec in items:
        se = rec.get('split_edit')
        if not se:
            continue
        into, out_of = se.get('into'), se.get('out_of')
        cut = next((c for c in cuts if c.get('to_item') == into and (out_of is None or c.get('from_item') == out_of)),
                   None) or next((c for c in cuts if c.get('to_item') == into), None)
        cut_f = cut['f'] if cut else (by_id.get(into) or {}).get('f0')
        lead, lag = se.get('lead'), se.get('lag')
        split_edits.append({'kind': 'J' if lead else 'L', 'id': rec['id'], 'into': into, 'out_of': out_of,
                            'cut_f': cut_f, 'cut_t': tsec(cut_f, fps) if cut_f is not None else None,
                            'sound_f0': rec['f0'], 'sound_f1': rec['f1'], 't0': rec['t0'], 't1': rec['t1'],
                            'offset_s': lead if lead else lag,
                            'offset_frames': fr(float(lead or lag or 0), fps), 'record': se})
    # subtitle feeds (captions as subtitles): burned ones are on screen
    for cap in script.get('captions') or []:
        burned = 'style' in cap
        for q in cap.get('cues') or []:
            a, b = fr(es.to_seconds(q['start']), fps), fr(es.to_seconds(q['end']), fps)
            graphics.append({'f0': a, 'f1': min(b, F), 't0': tsec(a, fps), 't1': tsec(min(b, F), fps),
                             'kind': 'caption', 'text': q.get('text', ''), 'track': cap.get('track'),
                             'subtitle_feed': True, 'visible': burned})
            if burned:
                pops.append({'f': a, 't': tsec(a, fps), 'text': q.get('text', '')[:60], 'kind': 'caption',
                             'id': f'{cap.get("track")}@{a}'})
    graphics.sort(key=lambda g: (g['f0'], g['f1']))
    pops.sort(key=lambda p: p['f'])
    transitions.sort(key=lambda x: x['f0'])
    pictures = [{'f0': a, 'f1': b, 't0': tsec(a, fps), 't1': tsec(b, fps), 'item': i,
                 'clip': (by_id.get(i) or {}).get('clip'), 'track': (by_id.get(i) or {}).get('track')}
                for a, b, i in runs]
    return {'method': 'edit script: the top picture item at every frame (later video tracks over earlier; '
                      'graphics, text and insets do not replace the picture); a change of it is a cut, a '
                      'same-track transition or overlay opacity fade a dissolve, a brightness fade a fade',
            'source_of_cuts': 'edit script (exact frames)', 'cuts': cuts, 'items': items, 'pictures': pictures,
            'graphics': graphics, 'text_pops': pops, 'transitions': transitions, 'split_edits': split_edits,
            'markers': ctx.get('markers') or [], 'warnings': warnings,
            'unsupported': ['cuts inside a single clip (a jump in a pre-rendered file, a cut baked into a graphic) '
                            'are not in the edit script: compare with the picture (shots.detect on the render)',
                            'an inset (picture-in-picture) is listed as an item with layer inset, not as a cut',
                            'keyframed opacity other than fades is not read as a transition']}


def _edit_video(ctx):
    """Cuts of a video file from shots.detect (camera moves don't count: cut / punch-in / dissolve / fade)."""
    import letitedit.footage.shots as shots
    fps, F = float(ctx['fps']), int(ctx['frames'])
    st = ctx['settings']
    f0, f1 = ctx['range']
    s0, s1 = (None, None) if (f0 == 0 and f1 >= F) else (f0 / fps, f1 / fps)
    bars_note = None
    det = shots.detect(ctx['video'], s0, s1, settings=st.get('shots_settings') or None)
    t_start = float(shots.probe(ctx['video']).get('start_time') or 0.0)
    area = active_area(ctx['video'])
    if area and area['share'] < float(st.get('bars_max_share', 0.85)) and             area.get('frames_share', 1.0) >= float(st.get('bars_min_frames', 0.2)):
        # bars (pillarbox / letterbox) hide cuts from a whole-frame comparison: the picture part is checked too
        # (a small cropped analysis copy; same time stamps) and its cuts are added where the whole frame had none
        proxy = cropped_proxy(ctx['video'], area['crop'])
        det2 = shots.detect(proxy, s0, s1, settings=st.get('shots_settings') or None)
        t2 = float(shots.probe(proxy).get('start_time') or 0.0)
        have = [float(c['t']) - t_start for c in det['cuts']]
        added = 0
        for c in det2['cuts']:
            tt = float(c['t']) - t2
            if all(abs(tt - h) > 2.5 / fps for h in have):
                c = dict(c, t=round(tt + t_start, 4), start=round(float(c.get('start', c['t'])) - t2 + t_start, 4),
                         end=round(float(c.get('end', c['t'])) - t2 + t_start, 4), found_in='picture area')
                det['cuts'].append(c)
                have.append(tt)
                added += 1
        det['cuts'].sort(key=lambda c: float(c['t']))
        bars_note = (f'{area["frames_share"]:.0%} of sampled frames have bars (the picture is {area["crop"]}, '
                     f'{area["share"]:.0%} of the frame): cuts were also looked for in that part ({added} added)')
    cuts, transitions = [], []

    def grid(t):            # shots' times are stream time stamps: onto this source's frame grid
        return int(round((float(t) - t_start) * fps))
    for c in det['cuts']:
        k = c['kind']
        f = grid(c['t'])
        a = grid(c.get('start', c['t']))
        b = grid(c.get('end', c['t'])) + (1 if k not in ('cut', 'punch') else 0)
        rec = {'f': f, 't': tsec(f, fps), 'kind': 'cut' if k in ('cut', 'punch') else k, 'from_item': None,
               'to_item': None, 'from_clip': ctx['video'], 'to_clip': ctx['video'],
               'f0': a if k not in ('cut', 'punch') else f, 'f1': b if k not in ('cut', 'punch') else f,
               'measures': c.get('measures')}
        if k == 'punch':
            rec['detail'] = 'punch-in (a reframe of the same picture)'
        if k in ('dissolve', 'fade'):
            transitions.append({'f0': rec['f0'], 'f1': rec['f1'], 't0': tsec(rec['f0'], fps),
                                't1': tsec(rec['f1'], fps), 'kind': k, 'type': k, 'from_item': None,
                                'to_item': None})
        cuts.append(rec)
    items = [{'id': 'file', 'track': 'V1', 'kind': 'video', 'f0': 0, 'f1': F, 't0': 0.0, 't1': tsec(F, fps),
              'what': 'clip', 'clip': ctx['video'], 'in_s': 0.0, 'out_s': tsec(F, fps), 'layer': 'picture'}]
    edges = [0] + [c['f'] for c in cuts] + [F]
    pictures = [{'f0': a, 'f1': b, 't0': tsec(a, fps), 't1': tsec(b, fps), 'item': 'file', 'clip': ctx['video'],
                 'track': 'V1'} for a, b in zip(edges, edges[1:]) if b > a]
    return {'method': 'shots.detect on the file: each frame pair compared after the camera move between them is '
                      'undone (corners + LK + RANSAC similarity; phase correlation), a cut must stand out from its '
                      'neighbourhood and make ffmpeg\'s scene score jump; punch-ins, dissolves and fades found too',
            'source_of_cuts': 'shots.detect (picture; measured precision 0.955 / recall 0.892 on 167 labelled cuts)',
            'cuts': cuts, 'items': items, 'pictures': pictures, 'graphics': [], 'text_pops': [],
            'transitions': transitions, 'split_edits': [], 'markers': [],
            'camera_moves': det.get('camera_moves'), 'rejected_count': det.get('rejected_count'),
            'detector_settings': det.get('settings'), 'active_area': area,
            'warnings': list(det.get('warnings') or []) + ([bars_note] if bars_note else []),
            'unsupported': list(det.get('unsupported') or []) + ['graphics, captions and split edits of a plain '
                                                                 'video are not known (no edit script)']}


def active_area(video):
    """Bars (black borders that never change) in a video: ffmpeg cropdetect on every 10th frame, each measured
    alone. {'crop': 'w:h:x:y' (the most common picture area), 'share': its area share, 'frames_share': share of
    the sampled frames with exactly that area, 'size': [W, H]}, or None when nothing could be measured. A render
    can mix pillarboxed vertical clips with full-frame ones, so frames_share says how much of it has the bars.
    Cached by content."""
    import collections
    import subprocess
    import letitedit.footage.shots as shots
    cf = CACHE / 'areas' / f'{_content_key(video)}-v2.json'
    got = _read_json(cf)
    if got is not None:
        return got or None
    info = shots.probe(video)
    W, H = int(info['w']), int(info['h'])
    r = subprocess.run([str(FFMPEG), '-hide_banner', '-nostats', '-threads', '4', '-i', str(video), '-an', '-vf',
                        r"select='not(mod(n\,10))',cropdetect=limit=0.09:round=2:reset=1", '-f', 'null', '-'],
                       capture_output=True, text=True, errors='replace', creationflags=0x08000000)
    m = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', r.stderr or '')
    out = {}
    if m:
        cnt = collections.Counter(m)
        (w, h, x, y), n = cnt.most_common(1)[0]
        w, h, x, y = int(w), int(h), int(x), int(y)
        if w > 0 and h > 0:
            out = {'crop': f'{w}:{h}:{x}:{y}', 'share': round(w * h / float(W * H), 3),
                   'frames_share': round(n / float(len(m)), 3), 'size': [W, H], 'samples': len(m)}
    _write_json(cf, out)
    return out or None


def cropped_proxy(video, crop, px=640):
    """A small analysis copy of the active part of a video (every frame, same time stamps), cached by content."""
    import subprocess
    w, h, x, y = (int(v) for v in crop.split(':'))
    s = min(1.0, float(px) / max(w, h))
    ow, oh = max(16, int(round(w * s / 2)) * 2), max(16, int(round(h * s / 2)) * 2)
    out = CACHE / 'crops' / f'{_content_key(video)}-{w}x{h}+{x}+{y}-{ow}.mp4'
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.stem + f'.{os.getpid()}.partial.mp4')
    r = subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-threads', '4', '-i', str(video), '-an', '-sn', '-vf',
                        f'crop={w}:{h}:{x}:{y},scale={ow}:{oh}:flags=area', '-fps_mode', 'passthrough',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-threads', '4', '-pix_fmt',
                        'yuv420p', str(part)], capture_output=True, text=True, errors='replace',
                       creationflags=0x08000000)
    if r.returncode != 0:
        raise RuntimeError(f'cropped analysis copy failed: {r.stderr[-600:]}')
    with open(part, 'rb+') as fh:
        os.fsync(fh.fileno())
    os.replace(part, out)
    return str(out)


def _edit_lane(ctx):
    """The edit: cuts, items, graphics, transitions, split edits (edit script for a project, shots.detect for a
    video)."""
    if ctx['kind'] == 'project':
        return _edit_project(ctx)
    return _edit_video(ctx)


_edit_lane.defaults = {}
register_lane('edit', _edit_lane, depends=(), version=3)


# ============================================================================ CLI

def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(description='timing signals of a project or video')
    ap.add_argument('source')
    ap.add_argument('--lanes', default=None)
    ap.add_argument('--start', type=float, default=None)
    ap.add_argument('--end', type=float, default=None)
    ap.add_argument('--refresh', action='store_true')
    a = ap.parse_args(argv)
    sig = signals(a.source, a.start, a.end, lanes=a.lanes.split(',') if a.lanes else None, refresh=a.refresh)
    summ = {k: v for k, v in sig.items() if k != 'lanes'}
    summ['lanes'] = {n: {k: (v if not isinstance(v, list) or len(v) < 8 else f'[{len(v)} items]')
                         for k, v in d.items() if k not in ('trace',)} for n, d in sig['lanes'].items()}
    print(json.dumps(summ, indent=1, default=str)[:20000])


if __name__ == '__main__':
    _cli(sys.argv[1:])
