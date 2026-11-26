"""3D render kit: clips of any creator's 3D model (.blend, .glb/.gltf, .obj, .fbx, .stl, .ply, .usd*, .dae) rendered
headless by Blender, for when a shot can't be filmed. Every output is marked generated (gen_common).

    inspect(model)                              objects, materials, bounds, cameras, lights (cached)
    render(spec, width, height, fps, ...)       -> {'path', 'cached', 'alpha', 'sheet'?, ...}
    preview(spec, width, height, fps, count)    a frame sheet of `count` frames at preview size

The model file is only read: a .blend (and single-file models) is copied to cache/render3d/models and the copy is
opened (relative texture paths are pointed at the original folder); .gltf/.obj (multi-file) are imported from where
they are, read only. Blender: LETITEDIT_BLENDER or C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe,
run with -b --factory-startup -P render3d_blender.py.

spec (every field optional except model; defaults in DEFAULTS / MOVE_DEFAULTS):
    model, scene (a .blend's scene name), duration 4.0 s,
    move {type: orbit|turntable|push_in|push_out|reveal|fly_past|static|keys, ...} (see MOVE_DOC),
    easing 'ease_in_out', highlight [{target, color, mode solid|glow, strength}], xray {show: [targets], ...},
    hide [targets], callouts [{target, text, ...}], lighting studio|daylight|sunset|night|flat|model,
    background 'transparent'|'#rrggbb(aa)'|'gradient:#top,#bottom'|'world', ground 'none'|'shadow'|'#rrggbb',
    engine eevee|cycles|workbench, samples, view_transform 'AgX' (bright saturated colours render paler under AgX than 'Standard'), format mp4|mov|png, crf 16.
Targets: an object name (exact, else case-insensitive substring, or a glob with * ?), 'collection:<name>',
'material:<name>' (faces using that material).
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import copy
import hashlib
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

import letitedit.pictures.gen_common as gc

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
BLENDER = Path(os.environ.get('LETITEDIT_BLENDER', r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'))
SCRIPT = HERE / 'render3d_blender.py'
CACHE = gc.CACHE / 'render3d'
VERSION = 2
BUILTIN_MODELS = {'builtin:title', 'builtin:logo'}
NO_WINDOW = gc.NO_WINDOW
MODEL_EXT = {'.blend', '.glb', '.gltf', '.obj', '.fbx', '.stl', '.ply', '.usd', '.usda', '.usdc', '.usdz', '.dae'}
COPY_EXT = {'.blend', '.glb', '.fbx', '.stl', '.ply', '.usdz', '.usdc'}
LOCK_OVER_S = 30.0          # estimated renders longer than this hold the PC render lock
BLENDER_TIMEOUT_S = 6 * 3600
PER_FRAME_S = {'eevee': 0.5, 'cycles': 3.0, 'workbench': 0.08}     # per 1080p frame (estimate), plus start-up
STARTUP_S = 8.0

DEFAULTS = {
    'duration': 4.0, 'easing': 'ease_in_out', 'lighting': 'studio', 'light_strength': 1.0, 'world_color': None,
    'background': 'transparent', 'ground': 'none', 'engine': 'eevee', 'samples': 32, 'view_transform': 'AgX',
    'format': None, 'crf': 16, 'highlight': [], 'xray': None, 'hide': [], 'callouts': [], 'scene': None,
    'frame_ignore': None,
}
MOVE_DEFAULTS = {'type': 'orbit', 'azimuth': 30.0, 'elevation': 12.0, 'framing': 0.9, 'lens': 35.0, 'roll': 0.0,
                 'focus': 'model'}
XRAY_DEFAULTS = {'show': [], 'color': '#7fc8ff', 'alpha': 0.04, 'edge': 0.5, 'edge_strength': 1.5}
HIGHLIGHT_DEFAULTS = {'color': '#ffb000', 'mode': 'solid', 'strength': 2.0}
CALLOUT_DEFAULTS = {'anchor': 'center', 'offset': None, 'point': None, 'label_at': None, 'dx': 160, 'dy': -120,
                    'start': 0.0, 'end': None, 'fade': 0.3, 'font': 'Inter', 'weight': 700, 'size': 40,
                    'color': '#ffffff', 'box': '#000000b4', 'padding': 14, 'line_color': '#ffffff',
                    'line_width': 3, 'dot_radius': 7, 'when_hidden': 'show', 'margin': 0.04, 'check_hidden': True}
MOVE_DOC = """orbit      azimuth_from (=azimuth 30) -> azimuth_to (=from + degrees 120), elevation_from/_to (=elevation 12)
turntable  camera still at azimuth/elevation; the model turns turn_from 0 -> turn_to 360 degrees (easing linear)
push_in    framing_from 0.75 -> framing_to 1.6, focus_from (focus) -> focus_to (target, else focus)
push_out   framing_from 1.6 -> framing_to 0.75, focus_from (target, else focus) -> focus_to (focus)
reveal     azimuth_from (azimuth_to - degrees 40) -> azimuth_to (azimuth), elevation_from -2 -> elevation_to
           (elevation + 8), framing_from 2.4 -> framing_to (framing)
fly_past   straight path beside the focus: side 90 (azimuth of the side), offset 2.2, height 0.15, length 5.0
           (x model radius), direction 1|-1, look 'focus' (keeps aiming at it) | 'ahead' (look_ahead 1.5)
static     one camera pose (azimuth, elevation, framing)
keys       keys [{t, azimuth, elevation, framing | distance (x model radius), focus, lens, roll, easing}]
all        azimuth 30 (0 = camera on -Y looking +Y, Blender's front view; 90 = camera on +X), elevation 12,
           framing 0.9 (the subject's bounding sphere fills this share of the frame's smaller side), lens 35 mm
           (36 mm sensor), roll 0, focus 'model' | a target | [x, y, z], distance (x radius, overrides framing)"""


def blender_exe():
    if not BLENDER.exists():
        raise FileNotFoundError(f'Blender not found at {BLENDER} (set LETITEDIT_BLENDER)')
    return str(BLENDER)


def _key(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def model_key(path):
    if path in BUILTIN_MODELS:
        return _key(path, VERSION)
    st = os.stat(path)
    return _key(str(Path(path).resolve()).lower(), st.st_size, int(st.st_mtime))


def model_copy(path):
    """(path Blender opens, original folder). Copies single-file models into the cache; never writes the original."""
    p = Path(path)
    if path in BUILTIN_MODELS:
        return path, None
    if not p.is_file():
        raise FileNotFoundError(f'no such model: {path}')
    ext = p.suffix.lower()
    if ext not in MODEL_EXT:
        raise ValueError(f'model type {ext} not supported ({", ".join(sorted(MODEL_EXT))})')
    if ext not in COPY_EXT:
        return str(p), str(p.parent)
    d = CACHE / 'models' / model_key(p)
    dst = d / p.name
    if not dst.exists():
        d.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + '.part')
        shutil.copyfile(p, tmp)
        os.replace(tmp, dst)
    return str(dst), str(p.parent)


def _run_blender(job, work, timeout=BLENDER_TIMEOUT_S, progress=None):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    jf = work / 'job.json'
    jf.write_text(json.dumps(job, default=str), encoding='utf-8')
    cmd = [blender_exe(), '-b', '--factory-startup', '-noaudio', '-P', str(SCRIPT), '--', str(jf)]
    logf = open(work / 'blender.log', 'w', encoding='utf-8', errors='replace')
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                                stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace')
        t0 = time.monotonic()
        for line in proc.stdout:
            logf.write(line)
            if progress and line.startswith('[render3d] frame'):
                try:
                    a, b = line.split()[2].split('/')
                    progress(int(a) / int(b), line.strip())
                except (ValueError, IndexError):
                    pass
            if time.monotonic() - t0 > timeout:
                proc.kill()
                raise TimeoutError(f'Blender ran over {timeout} s')
        code = proc.wait()
        proc.stdout.close()
    finally:
        logf.close()
    err = work / 'error.json'
    if err.exists():
        e = json.loads(err.read_text(encoding='utf-8-sig'))
        raise RuntimeError(f"Blender: {e['error']}")
    if code != 0:
        tail = (work / 'blender.log').read_text(encoding='utf-8', errors='replace')[-1500:]
        raise RuntimeError(f'Blender exited {code}: {tail}')


def inspect(model, scene=None, refresh=False):
    """{'objects': [{name, type, parent, collections, renders, materials, bounds, vertices, faces}], 'materials':
    [{name, objects}], 'bounds', 'size', 'unit_scale', 'unit_system', 'length_unit', 'cameras', 'lights', 'scene',
    'scenes', 'blender'} of a model (cached by file size + time)."""
    path, orig = model_copy(model)
    out = CACHE / 'inspect' / f'{model_key(model)}-{_key(scene)}'
    f = out / 'list.json'
    if f.exists() and not refresh:
        return json.loads(f.read_text(encoding='utf-8-sig'))
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    _run_blender({'mode': 'list', 'model': path, 'original_dir': orig, 'out_dir': str(out), 'scene': scene}, out,
                 timeout=900)
    return json.loads(f.read_text(encoding='utf-8-sig'))


def inspect_text(info, limit=80):
    b = info.get('bounds')
    size = info.get('size')
    lines = [f"Blender {info.get('blender')}, scene {info.get('scene')} (scenes: {', '.join(info.get('scenes') or [])})",
             f"bounds {[[round(v, 3) for v in x] for x in b] if b else None}, size x/y/z "
             f"{[round(v, 3) for v in size] if size else None} (Blender units; unit scale {info.get('unit_scale')}, "
             f"{info.get('unit_system')} {info.get('length_unit')})",
             f"subject bounds {[[round(v, 3) for v in x] for x in info['subject_bounds']] if info.get('subject_bounds') else None}"
             f" (size {[round(v, 3) for v in info.get('subject_size') or []]}), leaving out ground-like objects: "
             f"{', '.join(info.get('ground_like') or []) or 'none'}",
             f"cameras: {', '.join(info.get('cameras') or []) or 'none'}; lights: "
             f"{', '.join(info.get('lights') or []) or 'none'}"]
    objs = [o for o in info['objects'] if o['type'] not in ('CAMERA', 'LIGHT')]
    lines.append(f'{len(objs)} objects (name, type, renders, size x/y/z, materials):')
    for o in objs[:limit]:
        sz = ([round(o['bounds'][1][i] - o['bounds'][0][i], 3) for i in range(3)] if o.get('bounds') else '-')
        lines.append(f"  {o['name']} {o['type']}{'' if o.get('renders') else ' (hidden)'} {sz} "
                     f"[{', '.join(o.get('materials') or [])}]")
    if len(objs) > limit:
        lines.append(f'  ... {len(objs) - limit} more (all in the result)')
    lines.append(f"{len(info['materials'])} materials: " + ', '.join(m['name'] for m in info['materials'][:limit]))
    return '\n'.join(lines)


# ------------------------------------------------------------------ spec

def normalise(spec):
    """Spec with every default filled in (the form stored on a made item and used for the cache key)."""
    if isinstance(spec, str):
        spec = {'model': spec}
    s = copy.deepcopy(DEFAULTS)
    s.update({k: v for k, v in dict(spec).items() if v is not None})
    if not s.get('model'):
        raise ValueError('a 3D render needs a model path, builtin:title, or builtin:logo')
    s['model'] = str(s['model'])
    if s['model'] in BUILTIN_MODELS:
        s['text'] = str(s.get('text') or ('YOUR TITLE' if s['model'] == 'builtin:title' else 'L')).strip()
        if not 1 <= len(s['text']) <= 32:
            raise ValueError('built-in 3D text must be 1-32 characters')
        s['front_color'] = str(s.get('front_color') or '#F8F5ED')
        s['side_color'] = str(s.get('side_color') or '#FF7468')
        s['font'] = str(s.get('font') or 'Anton')
        if not s.get('font_path'):
            import letitedit.catalogs.fonts as fonts
            s['font_path'] = fonts.font_file(s['font'], 700)[0]
        if 'view_transform' not in spec:
            s['view_transform'] = 'Standard'
    mv = dict(MOVE_DEFAULTS)
    m = s.get('move') or {}
    if isinstance(m, str):
        m = {'type': m}
    mv.update({k: v for k, v in m.items() if v is not None})
    if mv['type'] in ('push_in', 'push_out') and 'framing' in m and 'framing_from' not in m:
        mv['framing_from'] = float(m['framing'])
    s['move'] = mv
    if s['move']['type'] == 'keys' and s['move'].get('keys'):
        s['duration'] = max(float(s['duration']) if 'duration' in spec else 0.0,
                            max(float(k['t']) for k in s['move']['keys']))
    s['duration'] = float(s['duration'])
    if s['duration'] <= 0:
        raise ValueError('duration must be over 0 s')
    hl = s.get('highlight') or []
    if isinstance(hl, (str, dict)):
        hl = [hl]
    s['highlight'] = [dict(HIGHLIGHT_DEFAULTS, **({'target': h} if isinstance(h, str) else h)) for h in hl]
    xr = s.get('xray')
    if xr:
        if isinstance(xr, (str, list)):
            xr = {'show': [xr] if isinstance(xr, str) else xr}
        xr = dict(XRAY_DEFAULTS, **xr)
        if isinstance(xr['show'], str):
            xr['show'] = [xr['show']]
        s['xray'] = xr
    hide = s.get('hide') or []
    s['hide'] = [hide] if isinstance(hide, str) else list(hide)
    cos = s.get('callouts') or []
    if isinstance(cos, dict):
        cos = [cos]
    s['callouts'] = [dict(CALLOUT_DEFAULTS, **c) for c in cos]
    for c in s['callouts']:
        if not c.get('text') and c.get('text') != '':
            c['text'] = str(c.get('target') or '')
    eng = s['engine']
    if eng not in PER_FRAME_S:
        raise ValueError(f"engine must be one of {sorted(PER_FRAME_S)}")
    if s['format'] not in (None, *gc.FORMATS):
        raise ValueError(f'format must be one of {gc.FORMATS}')
    return s


def wants_alpha(s):
    return s['background'] == 'transparent'


def out_format(s):
    return s['format'] or ('mov' if wants_alpha(s) else 'mp4')


def estimate_s(s, width, height, fps, frames=None):
    n = frames if frames is not None else max(1, round(s['duration'] * fps))
    k = (width * height) / (1920 * 1080)
    per = PER_FRAME_S[s['engine']] * max(0.15, k) * (max(1, int(s.get('samples') or 32)) / 32
                                                       if s['engine'] != 'workbench' else 1)
    return STARTUP_S + n * per


def digest(s, width, height, fps):
    return _key(s, model_key(s['model']), [int(width), int(height)], round(float(fps), 4), VERSION)


def describe(s):
    mv = s['move']
    bits = [f"{mv['type']} of {s['text']!r}" if s['model'] in BUILTIN_MODELS
            else f"{mv['type']} of {Path(s['model']).stem}"]
    if s['highlight']:
        bits.append('highlight ' + ', '.join(str(h['target']) for h in s['highlight']))
    if s.get('xray'):
        bits.append('x-ray ' + ', '.join(map(str, s['xray']['show'])))
    if s['callouts']:
        bits.append('callouts ' + ', '.join(repr(c['text']) for c in s['callouts']))
    return '; '.join(bits)


# ------------------------------------------------------------------ callouts

def _alpha_at(c, t, duration):
    start = float(c.get('start') or 0)
    end = float(c['end']) if c.get('end') is not None else duration + 1
    fade = float(c.get('fade') or 0)
    if t < start or t > end:
        return 0.0
    if fade <= 0:
        return 1.0
    return max(0.0, min(1.0, (t - start) / fade, (end - t) / fade if c.get('end') is not None else 1.0))


def draw_callouts(im, callouts, rows, t, duration):
    """Draw callout labels with a line to each anchor on an RGBA image (sizes are px at 1080 tall, scaled)."""
    from PIL import Image, ImageDraw
    W, H = im.size
    k = H / 1080.0
    layer = Image.new('RGBA', im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for c, a in zip(callouts, rows):
        if not a:
            continue
        al = _alpha_at(c, t, duration)
        if al <= 0 or not a.get('in_front', True):
            continue
        if a.get('hidden') and c['when_hidden'] == 'hide':
            continue
        if a.get('hidden') and c['when_hidden'] == 'dim':
            al *= 0.35
        ax, ay = a['x'], a['y']
        f = gc.font(c['font'], c['size'] * k, c['weight'])
        text = str(c['text'])
        bb = d.multiline_textbbox((0, 0), text, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        pad = c['padding'] * k
        bw, bh = tw + 2 * pad, th + 2 * pad
        mx, my = c['margin'] * W, c['margin'] * H
        if c.get('label_at'):
            lx, ly = c['label_at'][0] * W - bw / 2, c['label_at'][1] * H - bh / 2
        else:
            lx = ax + c['dx'] * k - (bw if c['dx'] < 0 else 0)
            ly = ay + c['dy'] * k - bh / 2
        lx = max(mx, min(W - mx - bw, lx))
        ly = max(my, min(H - my - bh, ly))
        # line from the anchor to the nearest point on the label box
        px = max(lx, min(lx + bw, ax))
        py = max(ly, min(ly + bh, ay))
        if abs(px - ax) < 1 and abs(py - ay) < 1:
            px, py = lx, ly + bh / 2

        def col(x, a_=al):
            r, g, b, aa = gc.rgba(x)
            return (r, g, b, int(aa * a_))
        lw = max(1, round(c['line_width'] * k))
        d.line((ax, ay, px, py), fill=col(c['line_color']), width=lw)
        r = c['dot_radius'] * k
        if r > 0:
            d.ellipse((ax - r, ay - r, ax + r, ay + r), fill=col(c['line_color']))
        if gc.rgba(c['box'])[3] > 0:
            d.rounded_rectangle((lx, ly, lx + bw, ly + bh), radius=pad * 0.6, fill=col(c['box']))
        d.multiline_text((lx + pad - bb[0], ly + pad - bb[1]), text, font=f, fill=col(c['color']))
    im.alpha_composite(layer)
    return im


# ------------------------------------------------------------------ render

def _job(s, width, height, fps, frames, out):
    path, orig = model_copy(s['model'])
    j = {k: v for k, v in s.items() if k not in ('format', 'crf')}
    j.update(mode='render', model=path, original_dir=orig, out_dir=str(out), width=int(width), height=int(height),
             fps=float(fps), frames_total=max(1, round(s['duration'] * fps)), frames=frames,
             world_color=s.get('world_color'))
    j.pop('background', None)
    j['film_transparent'] = s['background'] != 'world'
    if s.get('world_color') is None:
        j.pop('world_color')
    return j


def _composite(s, work, info, width, height, fps, frame_list):
    from PIL import Image
    bg = gc.background(width, height, 'transparent' if s['background'] in ('transparent', 'world') else s['background'])
    for k, row in enumerate(info['frames']):
        im = Image.open(Path(work) / f'f_{k:05d}.png').convert('RGBA')
        out = bg.copy()
        out.alpha_composite(im)
        if s['callouts']:
            draw_callouts(out, s['callouts'], row['callouts'], row['t'], s['duration'])
        yield row, out


def _lock(name, est):
    import contextlib
    if est <= LOCK_OVER_S:
        return contextlib.nullcontext()
    import letitedit.core.render_lock as render_lock
    return render_lock.slot(name, caller_pids=render_lock.ancestors())


def render(spec, width=1920, height=1080, fps=30.0, out_dir=None, out=None, fmt=None, progress=None,
           sheet_count=6, keep_work=False):
    """Render a full clip. Returns {'path', 'cached', 'alpha', 'format', 'frames', 'seconds', 'sheet', 'spec',
    'missing', 'engine', 'sidecar'}."""
    s = normalise(spec)
    if fmt:
        s['format'] = fmt
    f = out_format(s)
    out_dir = Path(out_dir or CACHE / 'out')
    out_dir.mkdir(parents=True, exist_ok=True)
    dg = digest(s, width, height, fps)
    name = f"generated-3d-{_safe(Path(s['model']).stem)}-{s['move']['type']}-{dg}"
    path = Path(out) if out else out_dir / (name + ('' if f == 'png' else '.' + f))
    side = Path(str(path) + '.json') if f != 'png' else path / 'generated.json'
    if path.exists() and side.exists() and not out:
        meta = json.loads(side.read_text(encoding='utf-8-sig'))
        return {'path': str(path), 'cached': True, 'alpha': f != 'mp4', 'format': f, 'sheet': meta.get('sheet'),
                'spec': s, 'missing': meta.get('missing', []), 'frames': meta.get('frames'),
                'engine': meta.get('engine'), 'sidecar': str(side), 'seconds': 0}
    total = max(1, round(s['duration'] * fps))
    work = CACHE / 'work' / f'{dg}-{int(time.time())}'
    t0 = time.monotonic()
    est = estimate_s(s, width, height, fps)
    with _lock(f'shotcut 3d render {Path(s["model"]).name}', est):
        _run_blender(_job(s, width, height, fps, None, work), work, progress=progress)
    info = json.loads((work / 'frames.json').read_text(encoding='utf-8-sig'))
    tmp = path.with_name(path.stem + '.part' + path.suffix) if f != 'png' else path
    enc = gc.Encoder(tmp, width, height, fps, f, crf=s['crf'], kind='3D render', title=describe(s),
                     comment=f"3D render of {Path(s['model']).name} by Blender ({info.get('engine')}); "
                             f"move {s['move']['type']}")
    picks = set(gc.even_frames(total, sheet_count)) if sheet_count else set()
    shots, labels = [], []
    try:
        for row, im in _composite(s, work, info, width, height, fps, None):
            enc.add(im)
            if row['frame'] in picks:
                shots.append(im.copy())
                labels.append(f"{row['t']:.2f}s")
        enc.close()
    except Exception:
        enc.abort()
        raise
    if f != 'png':
        os.replace(tmp, path)
    sheet = gc.sheet(shots, labels, str(path) + '.sheet.jpg' if f != 'png' else path / 'sheet.jpg') if shots else None
    meta = {'kind': '3d', 'spec': s, 'width': width, 'height': height, 'fps': fps, 'frames': total,
            'engine': info.get('engine'), 'missing': info.get('missing'), 'sheet': sheet,
            'blender_seconds': info.get('seconds'), 'bounds': info.get('bounds'), 'keys': info.get('keys'),
            'attribution': None, 'description': describe(s)}
    side = gc.sidecar(path, meta)
    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)
    return {'path': str(path), 'cached': False, 'alpha': f != 'mp4', 'format': f, 'frames': total,
            'seconds': round(time.monotonic() - t0, 1), 'sheet': sheet, 'spec': s, 'missing': info.get('missing'),
            'engine': info.get('engine'), 'sidecar': side}


def preview(spec, width=640, height=360, fps=30.0, count=6, times=None, out=None, cols=3):
    """Render `count` frames (or the frames at `times` seconds) and return {'sheet', 'frames', 'missing', ...}."""
    s = normalise(spec)
    total = max(1, round(s['duration'] * fps))
    frames = ([min(total - 1, max(0, round(float(t) * fps))) for t in times] if times
              else gc.even_frames(total, count))
    dg = _key(digest(s, width, height, fps), frames)
    work = CACHE / 'work' / f'preview-{dg}-{int(time.time())}'
    t0 = time.monotonic()
    est = estimate_s(s, width, height, fps, len(frames))
    with _lock(f'shotcut 3d preview {Path(s["model"]).name}', est):
        _run_blender(_job(s, width, height, fps, frames, work), work)
    info = json.loads((work / 'frames.json').read_text(encoding='utf-8-sig'))
    ims, labels = [], []
    for row, im in _composite(s, work, info, width, height, fps, frames):
        ims.append(im)
        labels.append(f"{row['t']:.2f}s")
    out = Path(out or CACHE / 'previews' / f'generated-3d-preview-{dg}.jpg')
    sheet = gc.sheet(ims, labels, out, cols=cols, tile_w=min(width, 480))
    shutil.rmtree(work, ignore_errors=True)
    return {'sheet': sheet, 'frames': frames, 'times': [r['t'] for r in info['frames']],
            'missing': info.get('missing'), 'engine': info.get('engine'), 'keys': info.get('keys'),
            'bounds': info.get('bounds'), 'radius': info.get('radius'), 'spec': s,
            'seconds': round(time.monotonic() - t0, 1),
            'callouts': [r['callouts'] for r in info['frames']]}


def _safe(name):
    import re
    return re.sub(r'[^A-Za-z0-9._-]+', '_', name)[:40] or 'model'


# ------------------------------------------------------------------ a tiny test model

def write_test_glb(path, parts=None):
    """A small .glb of named boxes (each its own mesh, node and material): parts = [(name, (cx, cy, cz),
    (sx, sy, sz), (r, g, b))]. Default: 'Body' 4x2x1.5 grey, 'Engine' 1x1x0.8 red inside the body, 'Wheel' x4."""
    import struct
    parts = parts or [('Body', (0, 0, 0.95), (4.0, 2.0, 1.5), (0.7, 0.72, 0.75)),
                      ('Engine', (1.2, 0, 0.8), (1.0, 1.0, 0.8), (0.8, 0.1, 0.1)),
                      ('Wheel FL', (-1.3, -1.05, 0.35), (0.7, 0.25, 0.7), (0.05, 0.05, 0.05)),
                      ('Wheel FR', (-1.3, 1.05, 0.35), (0.7, 0.25, 0.7), (0.05, 0.05, 0.05)),
                      ('Wheel RL', (1.3, -1.05, 0.35), (0.7, 0.25, 0.7), (0.05, 0.05, 0.05)),
                      ('Wheel RR', (1.3, 1.05, 0.35), (0.7, 0.25, 0.7), (0.05, 0.05, 0.05))]
    faces = [((1, 0, 0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
             ((-1, 0, 0), [(-1, 1, -1), (-1, -1, -1), (-1, -1, 1), (-1, 1, 1)]),
             ((0, 1, 0), [(1, 1, -1), (-1, 1, -1), (-1, 1, 1), (1, 1, 1)]),
             ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
             ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
             ((0, 0, -1), [(-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1)])]
    binbuf = bytearray()
    gl = {'asset': {'version': '2.0', 'generator': 'letitedit render3d test'}, 'scene': 0,
          'scenes': [{'nodes': []}], 'nodes': [], 'meshes': [], 'materials': [], 'accessors': [],
          'bufferViews': [], 'buffers': []}
    for i, (name, c, size, col) in enumerate(parts):
        pos, nrm, idx = [], [], []
        for n, quad in faces:
            base = len(pos)
            for v in quad:
                # glTF is Y-up: Blender (x, y, z) -> glTF (x, z, -y)
                bx, by, bz = (v[0] * size[0] / 2, v[1] * size[1] / 2, v[2] * size[2] / 2)
                pos.append((bx, bz, -by))
            nrm += [(n[0], n[2], -n[1])] * 4
            idx += [base, base + 1, base + 2, base, base + 2, base + 3]
        acc0 = len(gl['accessors'])
        for data, typ, fmt, comp in ((pos, 'VEC3', '<3f', 5126), (nrm, 'VEC3', '<3f', 5126)):
            off = len(binbuf)
            for v in data:
                binbuf += struct.pack(fmt, *v)
            gl['bufferViews'].append({'buffer': 0, 'byteOffset': off, 'byteLength': len(binbuf) - off,
                                      'target': 34962})
            acc = {'bufferView': len(gl['bufferViews']) - 1, 'componentType': comp, 'count': len(data), 'type': typ}
            if data is pos:
                acc['min'] = [min(v[k] for v in pos) for k in range(3)]
                acc['max'] = [max(v[k] for v in pos) for k in range(3)]
            gl['accessors'].append(acc)
        off = len(binbuf)
        for v in idx:
            binbuf += struct.pack('<H', v)
        while len(binbuf) % 4:
            binbuf += b'\0'
        gl['bufferViews'].append({'buffer': 0, 'byteOffset': off, 'byteLength': len(idx) * 2, 'target': 34963})
        gl['accessors'].append({'bufferView': len(gl['bufferViews']) - 1, 'componentType': 5123,
                                'count': len(idx), 'type': 'SCALAR'})
        gl['materials'].append({'name': name + ' Paint', 'pbrMetallicRoughness': {
            'baseColorFactor': [*col, 1.0], 'metallicFactor': 0.0, 'roughnessFactor': 0.5}})
        gl['meshes'].append({'name': name, 'primitives': [{'attributes': {'POSITION': acc0, 'NORMAL': acc0 + 1},
                                                           'indices': acc0 + 2, 'material': i}]})
        gl['nodes'].append({'name': name, 'mesh': i, 'translation': [c[0], c[2], -c[1]]})
        gl['scenes'][0]['nodes'].append(i)
    gl['buffers'].append({'byteLength': len(binbuf)})
    js = json.dumps(gl).encode()
    while len(js) % 4:
        js += b' '
    total = 12 + 8 + len(js) + 8 + len(binbuf)
    out = struct.pack('<III', 0x46546C67, 2, total) + struct.pack('<II', len(js), 0x4E4F534A) + js
    out += struct.pack('<II', len(binbuf), 0x004E4942) + bytes(binbuf)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(out)
    return str(path)


# ------------------------------------------------------------------ made items {render3d: {...}, len?}

def recipe(item):
    return {'kind': 'render3d', 'spec': normalise(item['render3d'])}


def view(r):
    return {'render3d': r['spec']}


def default_len(item):
    return normalise(item['render3d'])['duration']


def label(r):
    return f"generated 3D: {Path(r['spec']['model']).stem} {r['spec']['move']['type']}"


def render_recipe(r, width, height, fps, out_dir):
    """A made item's clip: ProRes 4444 .mov with alpha when the background is transparent, else H.264 .mp4."""
    fmt = 'mov' if wants_alpha(r['spec']) else 'mp4'
    res = render(r['spec'], width, height, fps, out_dir=out_dir, fmt=fmt)
    notes = []
    if res.get('missing'):
        notes.append(f"targets not found in the model: {res['missing']}")
    return {'path': res['path'], 'cached': res['cached'], 'alpha': res['alpha'], 'notes': notes}
