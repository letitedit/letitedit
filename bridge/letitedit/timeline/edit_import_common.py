"""The shared helpers: forms and file kinds, times, media files found and probed, the project written.

Part of `edit_import` (letitedit/timeline/edit_import.py), which imports every name here back,
so `edit_import.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import letitedit.timeline.edit_script as es  # noqa: E402
import letitedit.timeline.made as made  # noqa: E402

FORMS = ('ffmpeg', 'list', 'edl', 'otio')
EXPORT_FORMS = ('json', 'python', 'ffmpeg', 'edl', 'otio')
VIDEO_EXT = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf', '.wmv', '.3gp', '.mpg', '.mpeg',
             '.ts', '.flv'}
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.heic', '.webp', '.bmp', '.tif', '.tiff', '.gif'}
AUDIO_EXT = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aiff', '.aif', '.wma'}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


# ============================================================================ small helpers


def _who():
    import letitedit.timeline.project_journal as project_journal
    return project_journal.label_prefix()

def _r(x, nd=4):
    return round(float(x), nd)


def _time(v, fps=30.0):
    """Seconds from 12.5, '12.5', '1:02.5', '00:01:02.500', '00:01:02:15' (frames at fps), '1500ms', '2s'."""
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError(f'not a time: {v!r}')
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower()
    m = re.fullmatch(r'([-+]?[\d.]+(?:e[-+]?\d+)?)\s*(ms|us|s|sec|secs|seconds)?', s)
    if m:
        x = float(m.group(1))
        return x / 1000 if m.group(2) == 'ms' else x / 1e6 if m.group(2) == 'us' else x
    parts = re.split(r'[:;]', s)
    if len(parts) == 4:
        h, mi, sec, f = parts
        return int(h) * 3600 + int(mi) * 60 + int(sec) + int(f) / float(fps)
    neg = s.startswith('-')
    out = es.to_seconds(s.lstrip('-'))
    return -out if neg else out


def _ext(path):
    return Path(str(path)).suffix.lower()


def _kind_of_file(path):
    e = _ext(path)
    return 'image' if e in IMAGE_EXT else 'audio' if e in AUDIO_EXT else 'video'


_probe_cache = {}


def _probe(path):
    """{'duration', 'width', 'height', 'fps', 'audio', 'video', 'kind', 'timecode'} for a media file ({} when missing)."""
    path = str(path)
    if path in _probe_cache:
        return _probe_cache[path]
    info = {}
    if os.path.isfile(path):
        try:
            import letitedit.server.core_tools as core_tools
            p = core_tools.probe(path)
            info = {'duration': float(p.get('duration') or 0), 'width': p.get('width'), 'height': p.get('height'),
                    'fps': p.get('fps'), 'audio': bool(p.get('audio')), 'video': bool(p.get('width')),
                    'kind': _kind_of_file(path)}
        except Exception:  # noqa: BLE001 - an unreadable file reads as nothing
            info = {'duration': 0.0, 'kind': _kind_of_file(path), 'audio': False, 'video': False}
    _probe_cache[path] = info
    return info


_tc_cache = {}


def _file_timecode(path, fps):
    """A file's start timecode in seconds (QuickTime/MXF tag), or 0."""
    key = (str(path), fps)
    if key not in _tc_cache:
        tc = 0.0
        try:
            r = subprocess.run([str(es.FFPROBE), '-v', 'error', '-show_entries', 'format_tags=timecode:stream_tags=timecode',
                                '-of', 'json', str(path)], capture_output=True, text=True, encoding='utf-8',
                               errors='replace', creationflags=NO_WINDOW, timeout=60)
            d = json.loads(r.stdout or '{}')
            tags = [d.get('format', {}).get('tags', {})] + [s.get('tags', {}) for s in d.get('streams', [])]
            for t in tags:
                if t and t.get('timecode'):
                    tc = _time(t['timecode'].replace(';', ':'), fps)
                    break
        except Exception:  # noqa: BLE001
            tc = 0.0
        _tc_cache[key] = tc
    return _tc_cache[key]


def _has_alpha(path):
    if _ext(path) not in IMAGE_EXT:
        return False
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.mode in ('RGBA', 'LA', 'PA') or 'transparency' in im.info
    except Exception:  # noqa: BLE001
        return False


def _image_size(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:  # noqa: BLE001
        p = _probe(path)
        return (p.get('width') or 0, p.get('height') or 0)


_dir_cache = {}


def _listing(d, depth=3):
    key = (str(d), depth)
    if key not in _dir_cache:
        found = []
        base = Path(d)
        try:
            for root, dirs, files in os.walk(base):
                rel = Path(root).relative_to(base)
                if len(rel.parts) >= depth:
                    dirs[:] = []
                for f in files:
                    found.append(Path(root) / f)
                if len(found) > 20000:
                    break
        except OSError:
            pass
        _dir_cache[key] = found
    return _dir_cache[key]


def _find_media(name, dirs):
    """A file for a path or a name: as given, next to one of `dirs`, or a file in them with that name or stem."""
    if not name:
        return None
    name = str(name).strip().strip('"').strip("'")
    if name.lower().startswith('file:'):
        name = _url_path(name)
    p = Path(name)
    if p.is_absolute() and p.is_file():
        return str(p)
    for d in dirs:
        if d and (Path(d) / name).is_file():
            return str((Path(d) / name).resolve())
    low, stem = p.name.lower(), p.stem.lower()
    for d in dirs:
        if not d or not Path(d).is_dir():
            continue
        files = _listing(d)
        for f in files:
            if f.name.lower() == low:
                return str(f)
        for f in files:
            if f.stem.lower() == stem and f.suffix.lower() in VIDEO_EXT | IMAGE_EXT | AUDIO_EXT:
                return str(f)
    return None


def _url_path(url):
    u = urllib.parse.urlparse(url)
    if u.scheme and u.scheme.lower() != 'file' and len(u.scheme) > 1:
        return url
    path = urllib.parse.unquote(u.path if u.scheme else url)
    if u.netloc and u.netloc not in ('', 'localhost'):
        path = f'//{u.netloc}{path}'
    if re.match(r'^/[A-Za-z]:[/\\]', path):
        path = path[1:]
    return path.replace('/', os.sep) if os.name == 'nt' else path


def _file_url(path):
    p = Path(path)
    try:
        return p.resolve().as_uri()
    except ValueError:
        return 'file:///' + urllib.parse.quote(str(p).replace('\\', '/'))


def _db(factor):
    return _r(20 * math.log10(max(float(factor), 1e-6)), 3)


def _ass_escape(text):
    return str(text).replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}').replace('\r', '').replace('\n', '\\N')


def _ass_time(s):
    cs = int(round(max(0.0, s) * 100))
    return f'{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}'


def _item_tlen(it):
    tr = it.get('transition')
    if not tr:
        return 0.0
    return es.to_seconds(tr['len'] if isinstance(tr, dict) else tr)


def _text_item(text, length):
    """An .ass text layer showing `text` for `length` seconds (the default style at the project size)."""
    return {'ass': f'Dialogue: 0,{_ass_time(0)},{_ass_time(length)},Default,,0,0,0,,{_ass_escape(text)}', 'len': _r(length)}


def item_len(it):
    """Seconds an edit-script item lasts on its track."""
    if it.get('len') is not None and ('clip' not in it or made.is_made(it) or 'out' not in it):
        return es.to_seconds(it['len'])
    from letitedit.timeline.edit_sync import item_len as _il
    return _il(dict(it))


# ============================================================================ loading the source

def _load(source):
    """(data: text or a Python object, path or None, base folder)."""
    if isinstance(source, (list, dict)):
        return source, None, Path.cwd()
    if isinstance(source, Path) or (isinstance(source, str) and len(source) < 1024 and '\n' not in source
                                    and not source.lstrip().startswith(('[', '{')) and Path(source).is_file()):
        p = Path(source).resolve()
        return p.read_text(encoding='utf-8-sig', errors='replace'), p, p.parent
    if (isinstance(source, str) and '\n' not in source and len(source) < 1024 and not re.search(r'\s-\w', source)
            and Path(source).suffix.lower() in ('.edl', '.otio', '.json', '.py', '.bat', '.cmd', '.ps1', '.sh', '.txt')):
        raise FileNotFoundError(f'no file {source}')
    return str(source), None, Path.cwd()


# ============================================================================ building the project

def _spread(track):
    """A non-main track's items (with at) as lanes that don't overlap: [[items], ...]."""
    lanes = []
    for it in sorted(track['items'], key=lambda x: float(x.get('at', 0))):
        s = float(it.get('at', 0))
        e = s + item_len(it)
        for lane in lanes:
            if lane[-1][1] <= s + 1e-3:
                lane.append((it, e))
                break
        else:
            lanes.append([(it, e)])
    return [[it for it, _ in lane] for lane in lanes]


def _lane_name(name, k, taken):
    if k == 0 and name not in taken:
        return name
    m = re.fullmatch(r'([VA])(\d+)', name)
    if m:
        n = int(m.group(2)) + 1
        while f'{m.group(1)}{n}' in taken:
            n += 1
        return f'{m.group(1)}{n}'
    n = k + 1
    while f'{name} {n}' in taken:
        n += 1
    return f'{name} {n}'


def _project_profile(project, model, width, height, fps):
    """Create the project (or use an empty existing one); returns its profile {width, height, fps}."""
    import letitedit_ai as sa
    path = Path(project)
    if path.exists():
        script = es.read(path)
        if any('gap' not in it for t in script['tracks'] for it in t['items']):
            raise FileExistsError(f'{path} already has a timeline; import into a new project path (or an empty one)')
        model['notes'].append(f'imported into the existing empty project {path.name} '
                              f"({script['profile']['width']}x{script['profile']['height']} at {script['profile']['fps']:g} fps)")
        return script['profile']
    size = model.get('size') or {}
    like = model.get('like')
    w = width or size.get('width')
    h = height or size.get('height')
    f = fps or size.get('fps')
    sa.new_project(path, width=w, height=h, fps=f, like=like if like and os.path.isfile(like) else None)
    return es.read(path)['profile']


def _first_video(model):
    for t in model['tracks']:
        for it in t['items']:
            c = it.get('clip')
            if c and _kind_of_file(c) == 'video' and os.path.isfile(c):
                return c
    return None


def _clean_item(it):
    out = {k: v for k, v in it.items() if not k.startswith('_')}
    if 'effects' in out and not out['effects']:
        out.pop('effects')
    return out


def _write(project, model):
    """Write the model's tracks with set_track (whole tracks) and track gains with apply."""
    import letitedit_ai as sa
    tracks = model['tracks']
    main = next((t for t in tracks if t.get('main')), None)
    if main is None:
        main = {'name': 'V1', 'kind': 'video', 'items': [], 'main': True}
    if main['name'] != 'V1':
        main['name'] = 'V1'
    gains = []
    if main['items']:
        sa.set_track(project, 'V1', [_clean_item(i) for i in main['items']], label=f'{_who()}: import V1')
    if main.get('gain') is not None:
        gains.append(('V1', main['gain']))
    written = {'V1'}
    for t in tracks:
        if t is main or not t['items']:
            continue
        for k, lane in enumerate(_spread(t)):
            name = _lane_name(t['name'], k, written)
            if k:
                model['notes'].append(f"{t['name']}: items that overlap went on {name}")
            sa.set_track(project, name, [_clean_item(i) for i in lane], kind=t['kind'], label=f'{_who()}: import {name}')
            written.add(name)
            if t.get('gain') is not None:
                gains.append((name, t['gain']))
    if gains:
        sa.apply(project, [{'op': 'track', 'name': n, 'gain': g} for n, g in gains], label=f'{_who()}: import track gains')


def _summary(project):
    script = es.read(project)
    counts = {t['name']: sum(1 for it in t['items'] if 'gap' not in it) for t in script['tracks']}
    return {k: v for k, v in counts.items() if v}, script
