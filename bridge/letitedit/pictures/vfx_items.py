"""Shot effects and narration as timeline items: the creator / VFX features as words in the edit script.

    {id, vfx: {effect: NAME, source: {clip, in, out, speed?}, params: {...}}, len?}
    {id, voice: {text, voice?, speed?}}                  a narrated line (audio clip, local Kokoro TTS)

They are made items (see made.py): rendered once into <project folder>/made, placed like any clip, the recipe stored
on the clip so reading the timeline shows it and changing it re-renders. describe() is what the LLM reads: every
effect, its params with defaults, and what it makes:
  replace  a full-frame clip with the source's sound (H.264 .mp4, or lossless RGB .mov for lighting): goes on V1.
  overlay  a transparent layer without sound (ProRes 4444 .mov): goes on a video track above the footage.
Times inside an effect (source in/out, `at`, ramp keys) are SOURCE seconds, the clip's own clock. Boxes are
[x, y, w, h] in the source picture: pixels, or fractions 0-1 when every value is <= 1.

Renders are cached by a digest of (effect, params, source files' size + mtime, output size, fps, ENGINE): re-applying
an unchanged script never renders again. Nothing is printed (the MCP server talks on stdout); a log goes to
C:\\LetItEdit\\cache\\vfx-items\\vfx-items.log. The work is done by the creator package (C:\\LetItEdit\\creator:
tracking, backdrop, sky, shots, templates, dub) and the VFX package (C:\\LetItEdit\\vfx: person matte / depth
models, Blender templates, compositor), imported unchanged. The VFX beta switch (settings.json) gates the old
editor tools only; an item in the script is an explicit request.

Colour: the creator / VFX encoders write BT.601-matrix video without saying so, which the engine would read as
BT.709 (greens and reds shift); every file made here is tagged with the matrix it really uses.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import contextlib
import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import letitedit.timeline.made as made

os.environ.setdefault('OPENCV_LOG_LEVEL', 'ERROR')   # OpenCV's own warnings would go to the console
CREATOR_DIR = Path(os.environ.get('LETITEDIT_CREATOR', (_SAI_ROOT + '\\creator')))
VFX_DIR = Path(os.environ.get('LETITEDIT_VFX', (_SAI_ROOT + '\\vfx')))
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'vfx-items'
ENGINE = 1
MATTE_ENGINE = 3
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
TIMEOUT = 6 * 3600
REQUIRED = None
# what the creator/VFX encoders really write: BT.601 matrix, BT.709 primaries/transfer, limited range
H264_TAG = 'h264_metadata=matrix_coefficients=6:colour_primaries=1:transfer_characteristics=1'
PRORES_TAG = 'prores_metadata=color_primaries=bt709:color_trc=bt709:colorspace=smpte170m'
ENC_TAG = ['-colorspace', 'smpte170m', '-color_primaries', 'bt709', '-color_trc', 'bt709']
VOICE_DEFAULT = 'af_heart'
VOICE_LANG = {'a': 'en-us', 'b': 'en-gb', 'e': 'es', 'f': 'fr-fr', 'h': 'hi', 'i': 'it', 'j': 'ja', 'p': 'pt-br',
              'z': 'cmn'}
VOICE_LANG_NAME = {'a': 'American English', 'b': 'British English', 'e': 'Spanish', 'f': 'French', 'h': 'Hindi',
                   'i': 'Italian', 'j': 'Japanese', 'p': 'Brazilian Portuguese', 'z': 'Mandarin'}


# ---------------------------------------------------------------------------- the registry

def _fx(title, output, source, description, params, hints=None, notes='', required=(), length=None):
    d = {'title': title, 'description': description, 'params': params, 'output': output, 'notes': notes,
         'source': source, 'hints': hints or {}, 'required': list(required)}
    if length:
        d['len'] = length
    return d


_TRACK = {'box': REQUIRED, 'at': None, 'track': True, 'coords': 'source'}
_TRACK_HINTS = {'box': '[x, y, w, h] of the object at time `at`', 'at': 'source seconds, default = source in',
                'track': 'false = the box stays put', 'coords': 'source | frame (the project frame)'}
_BLENDER = {'glow': 0.0, 'quality': 'final', 'seed': 7}
_BLENDER_HINTS = {'quality': 'final | draft (half size, faster)', 'glow': '0-1 bloom'}

EFFECTS = {
    "lighting": _fx(
        "Protected lighting", "replace", "required",
        "A baked lighting clip, kept so projects that already carry one still render. New lighting is placed with "
        "{op: fx, lighting: true}: live editor filters on the speaker's clips, tuned to the Look, that the person can "
        "change by hand. One constant light level per clip is held by every-frame face measurements: whole mode only "
        "lifts the face, and its colour stays on natural skin. A lossless RGB MOV carries the result.",
        {"exposure_ev": 0., "contrast": 1., "black": 0., "saturation": 1.,
         "tint_rgb": [1., 1., 1.], "vignette": 0., "strength": 1., "mode": "whole", "target": None,
         "face_light": 0., "face_warmth": 0., "room_ev": 0.},
        {"mode": "whole",
         "target": "optional measured lighting region; fitted once at the clip head",
         "tint_rgb": "three RGB gains; each 0.25-2", "black": "offset -0.1 to 0.1",
         "face_light": "0-1: how far the face's mid-tones are raised (a gamma lift; white stays white)",
         "face_warmth": "0-0.06: red up and blue down on the face",
         "room_ev": "-1.5 to 0: exposure change outside the person (the face boxes widened to the shoulders and down), "
                    "softened at its edges",
         "vignette": "0-0.7: edge falloff that never enters a face box"},
        "Whole mode lifts the face and leaves its grade off the face box (the face keeps its own picture plus the face "
        "light); a face meant to take the Look's colour gets it from {op: fx, grade: true}, which grades faces too. It "
        "holds every detected face to: mean and median luma change at or above 0, hue shift "
        "of its mean colour at most 3 degrees (CIELAB h*ab), chroma change within 15%, median luma at most 0.80 "
        "(unless it already was higher) and no more than 1% newly clipped pixels. Natural skin sits on the "
        "vectorscope's skin-tone line (about 123 degrees), and lit skin usually reads 65-75 IRE on a waveform "
        "(about 50-65 for darker skin, up to about 80). Face light and warmth are cut back to the largest share "
        "(1, 0.75, 0.5, 0.25, 0) that holds those limits on every frame; the room is not cut back. A face missed on "
        "a frame takes the nearest frame's box, and a clip with no face found gets no face light, room or vignette. "
        "Background mode refuses a frame with neither a face nor a subject matte. "
        "A matte or face miss remains a limit; skin-colour protection may retain wood and other similar colours. "
        "The option changes scene appearance, not physical lamp positions."),
    'annotate': _fx(
        'Follow an object', 'overlay', 'required',
        'Arrow, circle, box or spotlight that sticks to an object as it moves (tracked from `box`), with an '
        'optional label.',
        {'shape': 'circle', **_TRACK, 'color': 'yellow', 'label': None, 'thickness': None, 'pad': 0.15,
         'fade_in': 0.25, 'fade_out': 0.25},
        {'shape': 'arrow | circle | box | spotlight', **_TRACK_HINTS,
         'color': 'name (yellow, orange, red, white, cream...) or #RRGGBB', 'thickness': 'px, default from size'},
        'Spotlight dims everything else. Put it on a track above the footage, starting where that footage starts.',
        required=('box',)),
    'blur': _fx(
        'Blur or pixelate', 'replace', 'required',
        'Blur or pixelate something that moves: a tracked box (licence plate, screen, face) or every face found '
        'automatically (faces: true).',
        {**_TRACK, 'faces': False, 'mode': 'blur', 'strength': 1.0, 'pad': 0.25, 'shape': 'auto'},
        {**_TRACK_HINTS, 'box': '[x, y, w, h] (or faces: true)', 'mode': 'blur | pixelate',
         'shape': 'auto | ellipse | rect (auto: ellipse for faces)'}),
    'erase': _fx(
        'Erase an object', 'replace', 'required',
        'Paint a tracked object out of the shot: a clean plate from other frames when it moves through a still '
        'shot, else LaMa inpainting (one patch for a still camera, every frame for a moving one).',
        {**_TRACK, 'pad': 0.12, 'camera': 'auto'}, {**_TRACK_HINTS, 'camera': 'auto | still | moving'},
        'A moving camera inpaints every frame: slow (seconds per frame) and it can shimmer.', required=('box',)),
    'backdrop': _fx(
        'New background', 'replace', 'required',
        'Keep the person, replace everything behind them: blur (portrait mode), a colour, a picture, a video '
        '(loops) or a rendered computer screen.',
        {'background': 'blur', 'dim': 0.0, 'blur_px': 0.0, 'color_match': 0.45, 'light_match': True,
         'camera': 'auto',
         'screen_title': '', 'screen_body': '', 'screen_url': '', 'screen_theme': 'dark'},
        {'background': "'blur' | colour (#RRGGBB or name) | picture or video path | 'screen'",
         'dim': '0-1 darken the new background', 'blur_px': 'blur the new background', 'color_match':
         '0-1 tint the person toward it', 'light_match': 'false turns off light, colour and edge wrap matching',
         'camera': 'auto | still | moving (moving: background follows the shake)',
         'screen_body': 'HTML for the screen', 'screen_theme': 'dark | light | brand'},
        'Best on a tripod shot with one person.'),
    'text_behind': _fx(
        'Text behind the person', 'replace', 'required',
        'Big title between the background and the person (the person stays in front of the letters).',
        {'text': REQUIRED, 'font': None, 'weight': 900, 'color': 'white', 'outline': None, 'size': 0.22, 'y': 0.42,
         'fade_in': 0.5, 'fade_out': 0.4},
        {'text': "use '\\n' for two lines", 'font': 'any family from letitedit_fonts (default Arial Black)',
         'size': 'letter height vs the shorter frame side', 'y': 'vertical centre 0 top - 1 bottom',
         'outline': 'colour or none'},
        required=('text',)),
    'clone': _fx(
        'Clone yourself', 'replace', 'required',
        'Cut the person out of another take (`take`) of the same locked-off camera and put them into this shot, '
        'so they appear twice.',
        {'take': REQUIRED, 'offset': 0.0, 'shift': [0.0, 0.0], 'scale': 1.0, 'feather': 1.5},
        {'take': '{clip, in, out}: the take with the person', 'offset': 'seconds into this shot when the clone starts',
         'shift': '[dx, dy] move the clone, fractions of the frame', 'scale': 'size of the clone'},
        'Same tripod position for both takes looks real; shift/scale place the clone elsewhere.', required=('take',)),
    'cutout': _fx(
        'Person cut-out', 'overlay', 'required',
        'Just the person (alpha), everything else transparent: put them over other footage.',
        {'feather': 1.5}, notes='Mattes are kept per frame of the footage and all the pieces of one edit are made as one job: about '
        '10 s per second of 60 fps footage the first time; any frame seen before only costs writing the piece, about 3-5 s per second.'),
    'object': _fx(
        'Object layer', 'overlay', 'required',
        'One object out of the shot (alpha), from letitedit_object. By itself it stays where it is in the shot, so anything on a track '
        'below it goes behind it; show changes what is drawn. {op: lift} is the way to move it: it adds steady and scale.',
        {'object': REQUIRED, 'show': 'object', 'color': None, 'width': None, 'steady': False, 'scale': None, 'rotate': None,
         'front_before': None, 'front_after': None, 'grain': None},
        {'object': 'an id from letitedit_object', 'show': 'object | outline (a line round it) | glow (a line and a soft light) | recolour (a new colour, same light and shade)',
         'color': '#rrggbb for outline, glow and recolour', 'width': 'how thick the outline is',
         'steady': 'true: in its own coordinates, in the middle of the picture', 'scale': 'with steady: plate pixels to picture pixels',
         'rotate': 'with steady: degrees', 'front_before': 'source seconds: things in front stay in front before this',
         'front_after': 'source seconds: things in front stay in front after this', 'grain': 'how much camera grain the steady object gets back'},
        required=('object',)),
    'sky': _fx(
        'Sky replacement', 'replace', 'required',
        'Replace the sky with a picture or video (sunset, stars, clouds); moves with the camera.',
        {'sky': REQUIRED, 'sensitivity': 0.5, 'color_match': 0.2, 'follow_camera': True},
        {'sky': 'picture or video path', 'sensitivity': '0-1, higher = more counts as sky'},
        required=('sky',)),
    'speed_ramp': _fx(
        'Speed ramp', 'replace', 'required',
        'Variable speed inside one clip: normal, ramp into slow motion (or fast), ramp back. Length follows the '
        'speed.',
        {'keys': None, 'slow': None, 'speed': None, 'ramp': 0.25, 'preset': None, 'ease': 'smooth',
         'frames': 'flow', 'sound': 'pitch', 'whoosh': False},
        {'keys': '[[t, speed], ...] t = source seconds; speed 0.05-20', 'slow': '[a, b] source seconds at `speed`',
         'speed': 'for slow/preset (default 0.35, rush/speed_up 3)', 'ramp': 'seconds to change speed (slow)',
         'preset': 'dip | rush | slow_start | slow_end | speed_up', 'ease': 'smooth | linear',
         'frames': 'flow (motion-interpolated) | blend | nearest', 'sound': 'pitch (kept) | varispeed | mute',
         'whoosh': 'add a whoosh where it slows'},
        'Give keys, slow, or preset.'),
    'tool_popup': _fx(
        '3D tool pop-up', 'overlay', 'none',
        'Blender: a 3D tool springs in beside you, sways, shows a label card, flies out.',
        {'tool': 'wrench', 'label': None, 'sublabel': None, 'x': 0.76, 'y': 0.32, 'size': 0.45, 'in_s': 0.5,
         'out_s': 0.45, 'spin_deg': 35, 'accent': 'orange', **_BLENDER},
        {'tool': 'wrench | ratchet | screwdriver | hammer', 'x': 'centre 0-1', 'size': 'vs shorter frame side',
         'accent': 'brand name or #hex', **_BLENDER_HINTS},
        'About 1 min per second of 1080p.', length=3.0),
    'bus_drive': _fx(
        '3D bus drives across', 'overlay', 'none',
        'Blender: a code-built 1980s Wanderlodge drives across the frame along a surface at ground_y.',
        {'start_x': -0.3, 'end_x': 1.3, 'ground_y': 0.78, 'length': 0.38, 'yaw_deg': 26, 'sign': 'ROAD TRIP',
         'bounce': 0.5, 'ease': True, **_BLENDER},
        {'start_x': '<0 or >1 = off screen', 'length': 'vs frame width', **_BLENDER_HINTS}, length=4.0),
    'explosion': _fx(
        'Explosion behind the person', 'replace', 'required',
        'Blender fireball, smoke and sparks composited into the shot with the person kept in front, plus glow, '
        'light flicker on the room and camera shake.',
        {'x': 0.5, 'y': 0.55, 'size': 0.7, 'delay_s': 0.15, 'smoke': True, 'sparks': 60, 'palette': 'fire',
         'flicker': 0.7, 'shake': 0.6, 'occlusion': 'subject', 'depth_cut': 0.6, **_BLENDER, 'glow': 0.5},
        {'palette': 'fire | blue | green', 'occlusion': 'subject | depth | subject+depth | none',
         'size': 'fireball vs frame height', **_BLENDER_HINTS}),
    'blender': _fx(
        'Free-form Blender', 'overlay', 'none',
        'Your own Blender Python: script defines build(ctx) (ctx.params, ctx.frames, ctx.fps, ctx.to_world(x, y), '
        'ctx.each_frame(fn); helpers in module vfx: box, cylinder, sphere, text, material, key, '
        'add_studio_lights, ease_*). Other params reach the script as ctx.params.',
        {'script': REQUIRED, **_BLENDER}, _BLENDER_HINTS,
        'Transparent background; camera looks along +Y, the y=0 plane maps onto the frame.', required=('script',),
        length=3.0),
    'light_leak': _fx(
        'Light leak', 'overlay', 'none',
        'Soft drifting colour blooms, e.g. over a cut.',
        {'palette': 'warm', 'strength': 0.45, 'seed': 4}, {'palette': 'warm | golden | cool | rose'},
        length=1.5),
}
BLENDER_TEMPLATE = {'tool_popup': 'tool_popup', 'bus_drive': 'bus_drive', 'explosion': 'explosion', 'blender': 'script'}
BLENDER_SETTINGS = ('glow', 'quality', 'seed', 'flicker', 'shake', 'occlusion', 'depth_cut')
FILE_PARAMS = ('background', 'sky')


# ---------------------------------------------------------------------------- small helpers

def _sec(v):
    if isinstance(v, (int, float)):
        return float(v)
    text = str(v).strip()
    if ':' in text:
        s = 0.0
        for part in text.split(':'):
            s = s * 60 + float(part)
        return s
    return float(text)


def _even(x):
    return max(2, int(x) // 2 * 2)


def _creator(name):
    for d in (CREATOR_DIR, VFX_DIR):
        if str(d) not in sys.path:
            sys.path.append(str(d))
    import importlib
    module = importlib.import_module(f'letitedit_creator.{name}')
    if name in ('shots', 'backdrop'):
        # These creator effects all use shots.MatteStream.  Install the shared
        # cleaner stream once, without changing the creator package or its API.
        shots = importlib.import_module('letitedit_creator.shots')
        portrait = importlib.import_module('letitedit_vfx.portrait_matte')
        shots.MatteStream = portrait.MatteStream
    if name == 'backdrop':
        importlib.import_module('letitedit_vfx.portrait_light').install(module)
    return module


def _vfx(name):
    if str(VFX_DIR) not in sys.path:
        sys.path.append(str(VFX_DIR))
    import importlib
    return importlib.import_module(f'letitedit_vfx.{name}')


_log = logging.getLogger('letitedit_ai.vfx_items')


def _logger():
    if not _log.handlers:
        CACHE.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(CACHE / 'vfx-items.log', encoding='utf-8')
        h.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        _log.addHandler(h)
        _log.setLevel(logging.INFO)
        _log.propagate = False
    return _log


class _ToLog:
    """Anything a library prints goes to the log, never to stdout (the MCP channel)."""

    def write(self, s):
        if s.strip():
            _logger().info('[stdout] %s', s.rstrip())
        return len(s)

    def flush(self):
        pass


def _run(cmd, what, cwd=None):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=TIMEOUT, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f'{what} failed: {r.stderr.strip()[-1500:]}')
    return r


_probes = {}


def _probe(path):
    """{duration, fps, has_audio, has_video, size: (w, h) as displayed (rotation applied)}."""
    st = os.stat(path)
    key = (str(path), st.st_size, int(st.st_mtime))
    if key not in _probes:
        ffprobe = made.APP_FFMPEG.with_name('ffprobe.exe')
        r = subprocess.run([str(ffprobe), '-v', 'error', '-show_entries',
                            'stream=codec_type,width,height,avg_frame_rate,r_frame_rate:stream_side_data=rotation:'
                            'format=duration', '-of', 'json', str(path)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
        d = json.loads(r.stdout or '{}')
        streams = d.get('streams', [])
        v = next((s for s in streams if s.get('codec_type') == 'video'), None)
        info = {'duration': float(d.get('format', {}).get('duration') or 0), 'has_video': v is not None,
                'has_audio': any(s.get('codec_type') == 'audio' for s in streams), 'fps': 0.0, 'size': (0, 0)}
        if v:
            def rate(text):
                try:
                    a, b = str(text).split('/')
                    return float(a) / float(b) if float(b) else 0.0
                except ValueError:
                    return 0.0
            info['fps'] = rate(v.get('avg_frame_rate')) or rate(v.get('r_frame_rate'))
            w, h = int(v.get('width') or 0), int(v.get('height') or 0)
            rot = next((int(sd.get('rotation') or 0) for sd in v.get('side_data_list') or [] if 'rotation' in sd), 0)
            info['size'] = (h, w) if abs(rot) % 180 == 90 else (w, h)
        _probes[key] = info
    return _probes[key]


def _is_still(path):
    return Path(path).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.heic', '.gif')


# ---------------------------------------------------------------------------- recipes (made.py calls these)

def _norm_source(s, what='source'):
    if isinstance(s, str):
        s = {'clip': s}
    if not isinstance(s, dict) or not s.get('clip'):
        raise ValueError(f'{what} needs {{clip, in, out}}')
    clip = str(s['clip'])
    if not Path(clip).is_file():
        raise FileNotFoundError(f'no such file: {clip}')
    a = _sec(s.get('in', 0))
    b = _sec(s['out']) if s.get('out') is not None else _probe(clip)['duration']
    if b <= a:
        raise ValueError(f'{what}: out ({b:.3f}) must be after in ({a:.3f})')
    d = {'clip': clip, 'in': round(a, 4), 'out': round(b, 4)}
    sp = float(s.get('speed', 1.0))
    if sp <= 0:
        raise ValueError(f'{what}: speed must be positive')
    if sp != 1.0:
        d['speed'] = sp
    return d


def _norm_params(effect, p):
    spec = EFFECTS[effect]
    if not isinstance(p, dict):
        raise ValueError(f'{effect}: params must be a mapping')
    unknown = set(p) - set(spec['params'])
    if unknown and effect != 'blender':
        raise ValueError(f"{effect} has no param {', '.join(sorted(unknown))}; it takes: {', '.join(spec['params'])}")
    out = json.loads(json.dumps(p))
    for k in ('at', 'offset'):
        if out.get(k) is not None:
            out[k] = _sec(out[k])
    if out.get('slow') is not None:
        if len(out['slow']) != 2:
            raise ValueError('speed_ramp: slow is [a, b] (source seconds)')
        out['slow'] = [_sec(x) for x in out['slow']]
    if out.get('keys') is not None:
        try:
            out['keys'] = [[_sec(k[0]), float(k[1])] for k in out['keys']]
        except (TypeError, IndexError, ValueError):
            raise ValueError('speed_ramp: keys are [[t, speed], ...] (t = source seconds)') from None
    if out.get('box') is not None:
        if not isinstance(out['box'], list) or len(out['box']) != 4:
            raise ValueError(f'{effect}: box is [x, y, w, h]')
        out['box'] = [float(v) for v in out['box']]
    if out.get('take') is not None:
        out['take'] = _norm_source(out['take'], 'clone take')
    for k in spec['required']:
        if out.get(k) in (None, ''):
            raise ValueError(f'{effect} needs params.{k} ({spec["hints"].get(k, "")})'.replace(' ()', ''))
    if effect == 'blur' and out.get('box') is None and not out.get('faces'):
        raise ValueError('blur needs params.box [x, y, w, h] or faces: true')
    if effect == 'lighting':
        from letitedit.looks.lighting import settings
        settings(out)
    return out


def recipe(item):
    """The made recipe of a {vfx: ...} item (normalised; what gets rendered and stored on the clip)."""
    v = item['vfx']
    if not isinstance(v, dict) or not v.get('effect'):
        raise ValueError('a vfx item is {vfx: {effect, source?, params?}} (letitedit_vfx_effects lists them)')
    effect = str(v['effect'])
    if effect not in EFFECTS:
        raise ValueError(f"unknown vfx effect {effect!r}; effects: {', '.join(EFFECTS)}")
    extra = set(v) - {'effect', 'source', 'params'}
    if extra:
        raise ValueError(f"vfx takes effect, source and params (got {', '.join(sorted(extra))}); settings go in params")
    spec = EFFECTS[effect]
    r = {'kind': 'vfx', 'effect': effect, 'params': _norm_params(effect, v.get('params') or {})}
    if spec['source'] == 'required':
        if not v.get('source'):
            raise ValueError(f'{effect} works on footage: give source: {{clip, in, out}}')
        r['source'] = _norm_source(v['source'])
    elif v.get('source'):
        raise ValueError(f'{effect} makes a layer by itself (no source): give len and put it on a track above the '
                         'footage')
    else:
        r['len'] = round(_sec(item['len']) if item.get('len') is not None else spec['len'], 4)
        if r['len'] <= 0:
            raise ValueError(f'{effect}: len must be positive')
    return r


def view(recipe_):
    """Script fields for a stored vfx recipe."""
    v = {'effect': recipe_['effect']}
    if recipe_.get('source'):
        v['source'] = recipe_['source']
    if recipe_.get('params'):
        v['params'] = recipe_['params']
    return {'vfx': v}


def default_len(item):
    """Seconds a vfx item lasts when it doesn't say (speed ramps: what the speed curve makes)."""
    if item.get('len') is not None:
        return _sec(item['len'])
    r = recipe(item)
    if 'len' in r:
        return r['len']
    src = r['source']
    if r['effect'] == 'speed_ramp':
        grid, speed, cum = _ramp_curve(src, {**EFFECTS['speed_ramp']['params'], **r['params']}, r['params'])
        return float(cum[-1])
    return (src['out'] - src['in']) / src.get('speed', 1.0)


def label(recipe_):
    """Short name for the clip in the editor."""
    if recipe_.get('kind') == 'voice':
        t = recipe_['text']
        return f"voice: {t[:40]}{'...' if len(t) > 40 else ''}"
    src = recipe_.get('source')
    return f"{recipe_['effect']}: {os.path.basename(src['clip'])}" if src else recipe_['effect']


def _files(recipe_):
    out = []
    if recipe_.get('source'):
        out.append(recipe_['source']['clip'])
    p = recipe_.get('params') or {}
    for k in FILE_PARAMS:
        v = p.get(k)
        if isinstance(v, str) and (os.sep in v or '/' in v or Path(v).suffix):
            if Path(v).is_file():
                out.append(v)
            elif not (k == 'background' and (v in ('blur', 'screen') or v.startswith('#'))):
                raise FileNotFoundError(f'no such file: {v}')
    if p.get('take'):
        out.append(p['take']['clip'])
    return out


def digest(recipe_, width, height, fps):
    files = []
    for f in _files(recipe_):
        try:
            st = os.stat(f)
        except OSError:
            raise FileNotFoundError(f'no such file: {f}') from None
        files.append([f, st.st_size, int(st.st_mtime)])
    key_parts = {'r': recipe_, 'f': files, 'size': [width, height], 'fps': round(fps, 4), 'engine': ENGINE}
    if recipe_.get('effect') in ('backdrop', 'text_behind', 'cutout', 'clone', 'explosion', 'lighting'):
        key_parts['matte'] = MATTE_ENGINE
    if recipe_.get("effect") == "lighting":
        key_parts["lighting"] = 11
    key = json.dumps(key_parts, sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def render_recipe(recipe_, width=1920, height=1080, fps=30.0, out_dir=None):
    """made.render for vfx/voice recipes: cached by digest. Returns {'path', 'cached', 'alpha', ...}."""
    out_dir = Path(out_dir or CACHE.parent / 'made')
    if recipe_['kind'] == 'voice':
        return render_voice(recipe_, out_dir)
    effect = recipe_['effect']
    alpha = EFFECTS[effect]['output'] == 'overlay'
    path = out_dir / f"vfx-{effect}-{digest(recipe_, width, height, fps)}{'.mov' if alpha or effect == 'lighting' else '.mp4'}"
    if path.exists():
        return {'path': str(path), 'cached': True, 'alpha': alpha}
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.stem}.{uuid.uuid4().hex[:6]}.tmp{path.suffix}')
    try:
        # Every effect encodes video and the cut-outs run a GPU model (BiRefNet): one heavy job at a time on this PC, so
        # wait for the render lock after the cache check (a caller that already holds it, such as an export, joins it).
        # A long cut-out gives the lock up between frames (about every 5 minutes, when a job waits for it): the matte is
        # cached per frame, so it carries on where it stopped.
        import letitedit.core.render_lock as render_lock
        whole_lighting = effect == 'lighting' and _norm_params(effect, recipe_.get('params') or {}).get('mode', 'whole') == 'whole'
        portrait = None if whole_lighting else _vfx('portrait_matte')
        with render_lock.Yielder(f'vfx {effect} {path.stem[-8:]}', caller_pids=render_lock.ancestors()) as hold:
            token = portrait.between_frames.set(hold.maybe_yield) if portrait else None
            try:
                _fill_runs(_matte_runs([recipe_], width, height, fps, out_dir), width, height, fps)
                res = render(effect, recipe_.get('source'), recipe_.get('params') or {}, width, height, fps, tmp,
                             length=recipe_.get('len'))
            finally:
                if portrait:
                    portrait.between_frames.reset(token)
        os.replace(tmp, path)
        receipt = tmp.with_suffix('.face-check.json')
        if receipt.exists():
            os.replace(receipt, path.with_suffix('.face-check.json'))
    finally:
        tmp.unlink(missing_ok=True)
    out = {'path': str(path), 'cached': False, 'alpha': alpha, 'frames': res['frames']}
    if res.get('notes'):
        out['notes'] = res['notes']
    return out


# ---------------------------------------------------------------------------- the mattes of a whole plan

MATTE_EFFECTS = ('cutout', 'backdrop', 'text_behind')   # read their person matte frame by frame from their source
_filled = set()     # runs already filled in this process, so the piece that follows doesn't read them again


def _matte_path(recipe_, width, height, fps, out_dir):
    alpha = EFFECTS[recipe_['effect']]['output'] == 'overlay'
    return Path(out_dir) / f"vfx-{recipe_['effect']}-{digest(recipe_, width, height, fps)}{'.mov' if alpha or recipe_['effect'] == 'lighting' else '.mp4'}"


def _matte_runs(recipes, width, height, fps, out_dir):
    """The stretches of source these recipes need mattes for: (clip, start s, frames), overlaps and small gaps joined.
    A recipe whose movie exists needs none; one with a speed works on a made copy, so its frames are found as it runs."""
    spans = {}
    for r in recipes:
        s = r.get('source')
        if r.get('effect') == 'lighting' and _norm_params('lighting', r.get('params') or {}).get('mode', 'whole') == 'whole':
            continue
        if r.get('kind') != 'vfx' or r.get('effect') not in MATTE_EFFECTS or not s or s.get('speed', 1.0) != 1.0:
            continue
        try:
            if _matte_path(r, width, height, fps, out_dir).exists():
                continue
        except OSError:
            continue
        spans.setdefault(s['clip'], []).append((float(s['in']), float(s['out'])))
    runs = []
    for clip, parts in spans.items():
        parts.sort()
        a, b = parts[0]
        for x, y in parts[1:]:
            if x <= b + 0.25:
                b = max(b, y)
            else:
                runs.append((clip, a, max(1, int(round((b - a) * fps)))))
                a, b = x, y
        runs.append((clip, a, max(1, int(round((b - a) * fps)))))
    return runs


def _fill_runs(runs, width, height, fps):
    """Make the mattes these runs are missing as one job. Never fails the edit: what isn't made here is made as it is used."""
    key = lambda run: (run[0], round(run[1], 4), run[2], width, height, round(fps, 4))  # noqa: E731
    known = {key(r) for r in runs}
    # a run inside one this process already filled needs nothing
    runs = [r for r in runs if key(r) not in _filled and not _inside_filled(r, width, height, fps)]
    if not runs:
        return None
    shots = _creator('shots')
    portrait = _vfx('portrait_matte')

    def reader(clip, start, frames):
        return shots.FrameReader(clip, start, frames, fps, width, height)
    started = time.monotonic()
    try:
        with contextlib.redirect_stdout(_ToLog()):
            res = portrait.fill(runs, reader)
    except Exception as exc:  # noqa: BLE001 - frames not made here are made as they are used
        _logger().info('matte fill failed: %s', exc)
        return {'stopped': f'{type(exc).__name__}: {exc}'}
    _logger().info('matte fill %s in %.1f s: %s', runs, time.monotonic() - started, res)
    if not res.get('stopped'):
        _filled.update(known)
        with contextlib.suppress(OSError):
            portrait.prune_store()
    return res


def _inside_filled(run, width, height, fps):
    clip, start, frames = run
    for c, s, n, w, h, f in _filled:
        if c == clip and (w, h, f) == (width, height, round(fps, 4)) and s - 1e-6 <= start \
                and start + frames / fps <= s + n / fps + 1e-6:
            return True
    return False


def fill_mattes(recipes, width, height, fps, out_dir=None):
    """Before a plan's clips are rendered: every person matte its recipes need, as one job with one model load.
    Returns what happened ({frames, drawn, kept, seconds, stopped?}) or None when there was nothing to do."""
    out_dir = Path(out_dir or CACHE.parent / 'made')
    runs = _matte_runs(recipes, width, height, fps, out_dir)
    if not runs:
        return None
    import letitedit.core.render_lock as render_lock
    portrait = _vfx('portrait_matte')
    with render_lock.Yielder('vfx cut-out mattes', caller_pids=render_lock.ancestors()) as hold:
        token = portrait.between_frames.set(hold.maybe_yield)
        try:
            return _fill_runs(runs, width, height, fps)
        finally:
            portrait.between_frames.reset(token)


# ---------------------------------------------------------------------------- rendering

class _Src:
    """A source range ready to read: path/start (a constant-speed proxy when the source has a speed), frames."""

    def __init__(self, path, start, dur, fps, clip, has_audio, native_fps):
        self.path, self.start, self.dur, self.clip = str(path), start, dur, clip
        self.frames = max(1, int(round(dur * fps)))
        self.has_audio, self.native_fps = has_audio, native_fps


class _Job:
    def __init__(self, effect, source, given, width, height, fps, out, work, length):
        self.effect, self.source, self.given = effect, source, given
        self.p = {**EFFECTS[effect]['params'], **given}
        self.W, self.H, self.fps, self.out, self.work = width, height, float(fps), Path(out), Path(work)
        self.length = length
        self.notes = []
        self._src = {}

    def src(self, source=None):
        s = source or self.source
        key = json.dumps(s, sort_keys=True)
        if key not in self._src:
            self._src[key] = _prepare(self, s)
        return self._src[key]


def _prepare(job, s):
    info = _probe(s['clip'])
    if not info['has_video']:
        raise ValueError(f"{os.path.basename(s['clip'])} has no picture")
    a, b, sp = s['in'], s['out'], s.get('speed', 1.0)
    if b > info['duration'] + 0.1 and not _is_still(s['clip']):
        raise ValueError(f"source out {b:.2f} s is past the end of {os.path.basename(s['clip'])} "
                         f"({info['duration']:.2f} s)")
    if sp == 1.0:
        return _Src(s['clip'], a, b - a, job.fps, s['clip'], info['has_audio'], info['fps'])
    proxy = job.work / f'source-{uuid.uuid4().hex[:6]}.mov'
    fit = _creator('shots').fit_filter(job.W, job.H, None)
    cmd = [made.ffmpeg_exe(), '-hide_banner', '-y', '-ss', f'{a:.4f}', '-t', f'{b - a:.4f}', '-i', s['clip'],
           '-vf', f'setpts=PTS/{sp:g},{fit}', '-c:v', 'libx264', '-crf', '10', '-preset', 'veryfast',
           '-pix_fmt', 'yuv420p']
    if info['has_audio']:
        cmd += ['-af', ','.join(f'atempo={x:g}' for x in made._atempo(sp)), '-c:a', 'pcm_s16le', '-ar', '48000']
    else:
        cmd += ['-an']
    _run(cmd + [proxy], 'speed change')
    native = info['fps'] * sp if info['fps'] else 0.0
    return _Src(proxy, 0.0, (b - a) / sp, job.fps, s['clip'], info['has_audio'], native)


def render(effect, source, params, width, height, fps, out_path, length=None):
    """Render one effect to out_path. replace -> H.264 .mp4 (lighting: RGB .mov); overlay -> ProRes 4444 .mov.
    Returns {'path', 'alpha', 'frames', 'notes'}. No caching here (render_recipe caches)."""
    if effect not in EFFECTS:
        raise ValueError(f'unknown vfx effect {effect!r}')
    spec = EFFECTS[effect]
    given = _norm_params(effect, params or {})
    src = _norm_source(source) if source else None
    if spec['source'] == 'required' and not src:
        raise ValueError(f'{effect} needs a source')
    if spec['source'] == 'none':
        length = float(length or spec['len'])
    work = CACHE / 'work' / f'{effect}-{uuid.uuid4().hex[:10]}'
    work.mkdir(parents=True, exist_ok=True)
    job = _Job(effect, src, given, int(width), int(height), fps, out_path, work, length)
    started = time.monotonic()
    log = _logger()
    log.info('render %s %s %s %sx%s@%s -> %s', effect, json.dumps(src), json.dumps(given)[:400], width, height,
             fps, out_path)
    try:
        portrait = None if effect == 'lighting' and given.get('mode', 'whole') == 'whole' else _vfx('portrait_matte')
        fallbacks = portrait.FALLBACKS if portrait else None
        with contextlib.redirect_stdout(_ToLog()):
            frames = _RENDER[effect](job)
        if portrait and portrait.FALLBACKS != fallbacks:
            job.notes.append('BiRefNet was not available, so cleaned MODNet made this cut-out (rougher edges); '
                             'it is not kept as a BiRefNet matte, so render again to retry')
    except Exception as exc:
        log.info('FAILED %s after %.1f s: %s', effect, time.monotonic() - started, exc)
        raise
    finally:
        if os.environ.get('LETITEDIT_KEEP_VFX_WORK') != '1':
            for _ in range(3):                    # a killed encoder can hold its file for a moment
                shutil.rmtree(work, ignore_errors=True)
                if not work.exists():
                    break
                time.sleep(1)
    log.info('done %s: %d frames in %.1f s %s', effect, frames, time.monotonic() - started, job.notes or '')
    return {'path': str(out_path), 'alpha': spec['output'] == 'overlay', 'frames': frames, 'notes': job.notes}


# ---------------------------------------------------------------------------- output helpers

def _tag_copy(src, dst, alpha):
    """Copy a creator/VFX encode to dst, labelled with the colour matrix it really uses (BT.601)."""
    _run([made.ffmpeg_exe(), '-hide_banner', '-y', '-i', src, '-map', '0', '-c', 'copy', '-bsf:v',
          PRORES_TAG if alpha else H264_TAG] + ([] if alpha else ['-movflags', '+faststart']) + [dst], 'tagging')


def _frames_of(path):
    ffprobe = made.APP_FFMPEG.with_name('ffprobe.exe')
    r = subprocess.run([str(ffprobe), '-v', 'error', '-count_packets', '-select_streams', 'v:0', '-show_entries',
                        'stream=nb_read_packets', '-of', 'csv=p=0', str(path)], capture_output=True, text=True,
                       creationflags=NO_WINDOW)
    try:
        return int(r.stdout.strip().split(',')[0])
    except ValueError:
        return 0


def _audio_args(src, dur):
    if not src.has_audio:
        return [], []
    return (['-ss', f'{src.start:.4f}', '-t', f'{dur:.4f}', '-i', src.path],
            ['-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-af', f'apad=whole_dur={dur:.4f}'])


def _mux(job, video, src, frames, tag=True):
    """Final replace clip: the made picture (no sound) + the source's sound for the same range."""
    dur = frames / job.fps
    a_in, a_out = _audio_args(src, dur)
    cmd = [made.ffmpeg_exe(), '-hide_banner', '-y', '-i', video] + a_in + ['-map', '0:v:0']
    if a_in:
        cmd += ['-map', '1:a:0'] + a_out
    cmd += ['-c:v', 'copy'] + (['-bsf:v', H264_TAG] if tag else []) + ['-t', f'{dur:.4f}', '-movflags', '+faststart',
                                                                      job.out]
    _run(cmd, 'mux')


def _flatten(job, src, overlay, frames, at=0.0, move=(0.0, 0.0), scale=1.0):
    """Final replace clip: an alpha overlay (made from src's frames) composited back over src, with its sound.
    move/scale place the overlay elsewhere (fractions of the frame; scale about the centre)."""
    sh = _creator('shots')
    dur = frames / job.fps
    shift = f'setpts=PTS-STARTPTS+{at:.4f}/TB' if at else 'setpts=PTS-STARTPTS'
    if scale != 1.0:
        shift += f',scale=iw*{scale:g}:ih*{scale:g}'
    x = f'(W-w)/2+{move[0] * job.W:.1f}'
    y = f'(H-h)/2+{move[1] * job.H:.1f}'
    graph = (f'[0:v]{sh.fit_filter(job.W, job.H, job.fps)},format=rgb24[b];[1:v]{shift}[o];'
             f'[b][o]overlay=x={x}:y={y}:eof_action=pass:format=rgb,format=yuv420p[v]')
    cmd = [made.ffmpeg_exe(), '-hide_banner', '-y', '-ss', f'{src.start:.4f}', '-t', f'{dur + 0.5:.4f}', '-i', src.path,
           '-i', overlay, '-filter_complex', graph, '-map', '[v]']
    if src.has_audio:
        cmd += ['-map', '0:a:0', '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-af', f'apad=whole_dur={dur:.4f}']
    cmd += ['-frames:v', str(frames), '-c:v', 'libx264', '-crf', '15', '-preset', 'fast', *ENC_TAG, '-t', f'{dur:.4f}',
            '-movflags', '+faststart', job.out]
    _run(cmd, 'composite')


# ---------------------------------------------------------------------------- boxes and tracking

def _geometry(job, src):
    """Where the source picture sits in the project frame (letterboxed like the editor) and its own size."""
    sw, sh = _probe(src.clip)['size']
    if not sw or not sh:
        return (0, 0, job.W, job.H), (job.W, job.H)
    s = min(job.W / sw, job.H / sh)
    cw, ch = int(round(sw * s)), int(round(sh * s))
    return ((job.W - cw) // 2, (job.H - ch) // 2, cw, ch), (sw, sh)


def _box_px(job, src):
    b = job.p.get('box')
    if b is None:
        return None
    x, y, w, h = [float(v) for v in b]
    frac = max(abs(x), abs(y), abs(w), abs(h)) <= 1.0
    if job.p.get('coords', 'source') == 'frame':
        return (x * job.W, y * job.H, w * job.W, h * job.H) if frac else (x, y, w, h)
    (rx, ry, rw, rh), (sw, sh) = _geometry(job, src)
    if frac:
        return rx + x * rw, ry + y * rh, w * rw, h * rh
    k = rw / sw
    return rx + x * k, ry + y * k, w * k, h * k


def _at_frame(job, src):
    at = job.p.get('at')
    if at is None:
        return 0
    s = job.source
    f = int(round((at - s['in']) / s.get('speed', 1.0) * job.fps))
    if f < 0 or f >= src.frames:
        raise ValueError(f"at ({at}) must be inside the source range {s['in']}-{s['out']}")
    return f


def _boxes(job, src):
    """One box per frame in project pixels: tracked (CSRT, forward and backward from `at`) or fixed."""
    box = _box_px(job, src)
    n = src.frames
    if not job.p.get('track', True):
        return [{'f': i, 'x': box[0], 'y': box[1], 'w': box[2], 'h': box[3], 'ok': True} for i in range(n)]
    import cv2
    tracking, shots = _creator('tracking'), _creator('shots')
    at = _at_frame(job, src)
    k = min(1.0, 960 / max(job.W, job.H))
    ww, wh = _even(job.W * k), _even(job.H * k)
    bx = tuple(int(round(v * k)) for v in box)
    if bx[2] < 4 or bx[3] < 4:
        raise ValueError('box too small to track (make it at least ~10 px)')
    found, before, tr, lost = [None] * n, [], None, 0
    for i, fr in enumerate(shots.FrameReader(src.path, src.start, n, job.fps, ww, wh)):
        bgr = cv2.cvtColor(fr, cv2.COLOR_RGB2BGR)
        if i < at:
            before.append(bgr)
            continue
        if i == at:
            tr = tracking._tracker()
            tr.init(bgr, bx)
            found[i] = (*bx, True)
            if before:                                   # backwards from `at` to the start
                tb, prev = tracking._tracker(), bx
                tb.init(bgr, bx)
                for j in range(at - 1, -1, -1):
                    ok, b = tb.update(before[j])
                    if ok:
                        prev = tuple(b)
                    else:
                        lost += 1
                    found[j] = (*prev, bool(ok))
                before = []
            continue
        ok, b = tr.update(bgr)
        if ok:
            found[i] = (*b, True)
        else:
            lost += 1
            found[i] = (*found[i - 1][:4], False)
    last = next((f for f in reversed(found) if f is not None), (*bx, True))
    found = [f if f is not None else last for f in found]
    boxes = [{'f': i, 'x': f[0] / k, 'y': f[1] / k, 'w': f[2] / k, 'h': f[3] / k, 'ok': f[4]} for i, f in enumerate(found)]
    if lost:
        job.notes.append(f'tracking lost the object on {lost} of {n} frames (it held the last good box)')
    return tracking.smooth(boxes)


def _camera_still(job, src, setting):
    if setting in ('still', 'tripod'):
        return True
    if setting == 'moving':
        return False
    shots = _creator('shots')
    st = shots.stationary(src.path, src.start, min(src.dur, 30.0))
    if st.get('lost_tracking') or 'reason' in st:
        job.notes.append('camera treated as moving (its motion could not be measured)')
    else:
        job.notes.append(f"camera {'still' if st['stationary'] else 'moving'} (drift {st.get('max_shift', 0) * 100:.1f}%)")
    return bool(st['stationary'])


# ---------------------------------------------------------------------------- effects

def _fx_annotate(job):
    p = job.p
    if p['shape'] not in ('arrow', 'circle', 'box', 'spotlight'):
        raise ValueError('annotate: shape is arrow, circle, box or spotlight')
    tracking = _creator('tracking')
    src = job.src()
    boxes = _boxes(job, src)
    tmp = job.work / 'annotate.mov'
    res = tracking.render_annotation(boxes, tmp, job.fps, job.W, job.H, kind=p['shape'], color=p['color'],
                                     label=p['label'], thickness=p['thickness'], t_in=float(p['fade_in']),
                                     t_out=float(p['fade_out']), pad=float(p['pad']))
    _tag_copy(tmp, job.out, alpha=True)
    return res['frames']


def _fx_blur(job):
    p = job.p
    if p['mode'] not in ('blur', 'pixelate'):
        raise ValueError('blur: mode is blur or pixelate')
    tracking = _creator('tracking')
    src = job.src()
    per = [[] for _ in range(src.frames)]
    if p.get('box') is not None:
        for i, b in enumerate(_boxes(job, src)):
            per[i].append((b['x'], b['y'], b['w'], b['h']))
    if p.get('faces'):
        faces = tracking.detect_faces(src.path, src.start, src.frames, job.fps, job.W, job.H)
        for i, fl in enumerate(faces[:src.frames]):
            per[i] += list(fl)
        job.notes.append(f'faces found on {sum(1 for f in faces if f)} of {src.frames} frames')
    shape = p['shape'] if p['shape'] != 'auto' else ('ellipse' if p.get('faces') and p.get('box') is None else 'rect')
    tmp = job.work / 'blur.mov'
    res = tracking.render_blur(src.path, src.start, src.frames, job.fps, job.W, job.H, tmp, per, mode=p['mode'],
                               strength=float(p['strength']), pad=float(p['pad']), ellipse=shape == 'ellipse')
    _flatten(job, src, tmp, res['frames'])
    return res['frames']


def _fx_erase(job):
    p = job.p
    tracking = _creator('tracking')
    src = job.src()
    boxes = _boxes(job, src)
    still = _camera_still(job, src, p['camera'])
    tmp = job.work / 'erase.mov'
    shots = _creator('shots')
    with shots.GPU_LOCK:
        res = tracking.render_erase(src.path, src.start, src.frames, job.fps, job.W, job.H, tmp, boxes,
                                    static_camera=still, pad=float(p['pad']))
    job.notes.append(f"erased with {res['method']}")
    _flatten(job, src, tmp, res['frames'])
    return res['frames']


def _background(job):
    """(kind, source) for backdrop.Background from params.background."""
    bd, g = _creator('backdrop'), _creator('graphics')
    bg = str(job.p.get('background') or 'blur').strip()
    if bg == 'blur':
        return 'blur', None
    if bg == 'screen':
        p = job.p
        html = bd.screen_html(p['screen_title'], p['screen_body'], p['screen_url'], p['screen_theme'])
        return 'screen', str(bd.render_html(html, job.work / 'screen.png', job.W, job.H))
    if Path(bg).is_file():
        return ('image' if _is_still(bg) else 'video'), bg
    try:
        g.color(bg)
        return 'color', bg
    except (ValueError, KeyError):
        raise ValueError("backdrop: background is 'blur', a colour (#RRGGBB or a name), 'screen', or a picture/video "
                         f'path (not found: {bg})') from None


def _portrait_cache(src, job):
    portrait = _vfx('portrait_matte')
    return portrait.cache_for(src.path, src.start, src.frames, job.fps, job.W, job.H)


def _fx_backdrop(job):
    p = job.p
    bd = _creator('backdrop')
    src = job.src()
    kind, source = _background(job)
    follow = False
    if kind in ('image', 'video', 'screen'):
        follow = not _camera_still(job, src, p['camera'])
    tmp = job.work / 'backdrop.mp4'
    light = _vfx('portrait_light')
    with _portrait_cache(src, job), light.use(p['light_match']):
        res = bd.render_backdrop(src.path, src.start, src.frames, job.fps, job.W, job.H, tmp, kind=kind, source=source,
                                 dim=float(p['dim']), blur_px=float(p['blur_px']), match=float(p['color_match']),
                                 follow_camera=follow)
    _mux(job, tmp, src, res['frames'])
    return res['frames']


def _text_font(p, px):
    if p.get('font'):
        import letitedit.catalogs.fonts as fonts
        try:
            return fonts.pil_font(p['font'], px, int(p.get('weight') or 400))
        except KeyError:
            raise ValueError(f"text_behind: unknown font {p['font']!r} (letitedit_fonts lists them)") from None
    g = _creator('graphics')
    w = int(p.get('weight') or 900)
    return g.font(px, 'black' if w >= 800 else 'bold' if w >= 600 else 'regular')


def _fx_text_behind(job):
    import numpy as np
    from PIL import Image
    p = job.p
    g, shots = _creator('graphics'), _creator('shots')
    src = job.src()
    short = min(job.W, job.H)
    lines = str(p['text']).replace('\\n', '\n').split('\n')
    px = int(short * float(p['size']))
    outline = p.get('outline')
    if str(outline).strip().lower() in ('', 'none', 'false', '0'):
        outline = None            # the documented 'none'
    stroke = int(short * 0.006) if outline else 0

    def block_for(size):
        fnt = _text_font(p, size)
        imgs = [g.text_image(ln, fnt, g.color(p['color']), stroke=stroke, stroke_fill=g.color(outline or 'black'),
                             shadow=0) for ln in lines]
        return imgs
    imgs = block_for(px)
    while max(i.width for i in imgs) > job.W * 0.94 and px > 20:
        px = int(px * 0.9)
        imgs = block_for(px)
    block = Image.new('RGBA', (max(i.width for i in imgs), sum(int(i.height * 0.92) for i in imgs)), (0, 0, 0, 0))
    yy = 0
    for im in imgs:
        block.alpha_composite(im, ((block.width - im.width) // 2, yy))
        yy += int(im.height * 0.92)
    dur = src.frames / job.fps
    t_in, t_out = float(p['fade_in']), float(p['fade_out'])
    tmp = job.work / 'text.mp4'
    with _portrait_cache(src, job), shots.VideoWriter(tmp, job.W, job.H, job.fps) as wr:
        mattes = shots.MatteStream()
        for i, fr in enumerate(shots.FrameReader(src.path, src.start, src.frames, job.fps, job.W, job.H)):
            t = i / job.fps
            k_in = g.ease_out_cubic(t / t_in) if t_in > 0 else 1.0
            k_out = 1 - g.clamp01((t - (dur - t_out)) / t_out) if t_out > 0 else 1.0
            layer = Image.new('RGBA', (job.W, job.H), (0, 0, 0, 0))
            rise = int((1 - k_in) * job.H * 0.06)
            g.paste_center(layer, block, job.W / 2, job.H * float(p['y']) + rise, opacity=max(0.0, min(k_in, k_out)))
            arr = np.asarray(layer, np.float32)
            a = arr[..., 3:4] / 255.0 * (1 - mattes(fr)[..., None])
            out = fr.astype(np.float32) * (1 - a) + arr[..., :3] * a
            wr.write(np.clip(out + 0.5, 0, 255).astype(np.uint8))
    _mux(job, tmp, src, wr.frames)
    return wr.frames


def _fx_clone(job):
    p = job.p
    bd = _creator('backdrop')
    src = job.src()
    take = job.src(p['take'])
    if not _camera_still(job, take, 'auto'):
        job.notes.append('the take looks handheld: the clone may slide against the shot')
    tmp = job.work / 'person.mov'
    with _portrait_cache(take, job):
        res = bd.render_person_only(take.path, take.start, take.frames, job.fps, job.W, job.H, tmp,
                                    feather=float(p['feather']))
    shift = p.get('shift') or [0.0, 0.0]
    if not isinstance(shift, list) or len(shift) != 2:
        raise ValueError('clone: shift is [dx, dy] (fractions of the frame)')
    _flatten(job, src, tmp, src.frames, at=float(p.get('offset') or 0.0), move=(float(shift[0]), float(shift[1])),
             scale=float(p.get('scale') or 1.0))
    job.notes.append(f"clone plays {res['frames'] / job.fps:.2f} s from {float(p.get('offset') or 0):.2f} s")
    return src.frames


def _fx_cutout(job):
    bd = _creator('backdrop')
    src = job.src()
    tmp = job.work / 'cutout.mov'
    with _portrait_cache(src, job):
        res = bd.render_person_only(src.path, src.start, src.frames, job.fps, job.W, job.H, tmp,
                                    feather=float(job.p['feather']))
    _tag_copy(tmp, job.out, alpha=True)
    return res['frames']


def _fx_object(job):
    import letitedit.pictures.object_layer as object_layer
    src = job.src()
    p = {k: v for k, v in job.p.items() if v is not None}
    tmp = job.work / 'object.mov'
    frames = object_layer.render_movie(p, {'in': src.start, 'out': src.start + src.dur}, job.W, job.H, job.fps, tmp)
    _tag_copy(tmp, job.out, alpha=True)
    return frames


def _fx_sky(job):
    p = job.p
    sky = _creator('sky')
    src = job.src()
    pic = str(p['sky'])
    if not Path(pic).is_file():
        raise FileNotFoundError(f'sky: no such file: {pic}')
    tmp = job.work / 'sky.mp4'
    res = sky.render_sky(src.path, src.start, src.frames, job.fps, job.W, job.H, tmp,
                         kind='image' if _is_still(pic) else 'video', source=pic,
                         sensitivity=float(p['sensitivity']), match=float(p['color_match']),
                         follow_camera=bool(p['follow_camera']))
    job.notes.append(f"sky covers {res['sky_coverage'] * 100:.0f}% of the frame")
    if res['sky_coverage'] < 0.03:
        job.notes.append('almost no sky found: little changes')
    _mux(job, tmp, src, res['frames'])
    return res['frames']


def _fx_light_leak(job):
    p = job.p
    if p['palette'] not in ('warm', 'golden', 'cool', 'rose'):
        raise ValueError('light_leak: palette is warm, golden, cool or rose')
    templates = _creator('templates')
    tmp = job.work / 'leak.mov'
    res = templates.light_leak(tmp, job.fps, job.W, job.H, duration=job.length, palette=p['palette'],
                               strength=float(p['strength']), seed=int(p['seed']))
    _tag_copy(tmp, job.out, alpha=True)
    return res['frames']


# ---------------------------------------------------------------------------- speed ramp

PRESETS = {  # name: (default speed, [(fraction of the range, use speed?)])
    'dip': (0.35, [(0.3, False), (0.4, True), (0.6, True), (0.7, False)]),
    'rush': (3.0, [(0.25, False), (0.35, True), (0.65, True), (0.75, False)]),
    'slow_end': (0.35, [(0.5, False), (0.62, True)]),
    'slow_start': (0.35, [(0.38, True), (0.5, False)]),
    'speed_up': (3.0, [(0.0, False), (1.0, True)]),
}


def _ramp_keys(src, p, given):
    a, b = src['in'], src['out']
    if p.get('keys'):
        pts = sorted((float(t), float(s)) for t, s in p['keys'])
    elif p.get('slow'):
        sa, sb = p['slow']
        sp = float(given.get('speed') or 0.35)
        r = max(0.0, float(p.get('ramp') or 0.0))
        pts = [(sa - r, 1.0), (sa, sp), (sb, sp), (sb + r, 1.0)]
    elif p.get('preset'):
        if p['preset'] not in PRESETS:
            raise ValueError(f"speed_ramp: preset is one of {', '.join(PRESETS)}")
        d, shape = PRESETS[p['preset']]
        sp = float(given.get('speed') or d)
        pts = [(a + f * (b - a), sp if use else 1.0) for f, use in shape]
    else:
        raise ValueError('speed_ramp needs params.keys [[t, speed], ...], slow [a, b] (+ speed), or preset')
    for t, s in pts:
        if not 0.05 <= s <= 20:
            raise ValueError(f'speed_ramp: speed {s} is outside 0.05-20')
    return pts


def _ramp_curve(src, p, given):
    """Source-relative seconds grid, speed on it and output seconds at each grid point."""
    import numpy as np
    sp = src.get('speed', 1.0)
    dur = (src['out'] - src['in']) / sp
    pts = [((t - src['in']) / sp, s) for t, s in _ramp_keys(src, p, given)]
    grid = np.linspace(0.0, dur, max(64, int(dur * 480)) + 1)
    ts = np.array([t for t, _ in pts])
    vs = np.array([s for _, s in pts])
    if len(pts) == 1:
        speed = np.full_like(grid, vs[0])
    else:
        idx = np.clip(np.searchsorted(ts, grid, side='right') - 1, 0, len(ts) - 2)
        t0, t1 = ts[idx], ts[idx + 1]
        u = np.clip((grid - t0) / np.maximum(t1 - t0, 1e-9), 0, 1)
        if p.get('ease', 'smooth') == 'smooth':
            u = u * u * (3 - 2 * u)
        speed = vs[idx] + (vs[idx + 1] - vs[idx]) * u
        speed = np.where(grid <= ts[0], vs[0], np.where(grid >= ts[-1], vs[-1], speed))
    mid = (speed[:-1] + speed[1:]) / 2
    cum = np.concatenate([[0.0], np.cumsum(np.diff(grid) / mid)])
    return grid, speed, cum


@contextlib.contextmanager
def _reading(reader):
    """Stop a shots.FrameReader that was not read to the end (its ffmpeg and pipe)."""
    try:
        yield reader
    finally:
        reader.close()
        with contextlib.suppress(Exception):
            reader.proc.stdout.close()


class _Frames:
    """Sequential random access to decoded frames (keeps a small window)."""

    def __init__(self, it):
        self.it, self.buf, self.next, self.done = it, {}, 0, False

    def get(self, i):
        while not self.done and self.next <= i:
            fr = next(self.it, None)
            if fr is None:
                self.done = True
                break
            self.buf[self.next] = fr
            self.next += 1
        i = max(0, min(i, self.next - 1))
        return self.buf[i]

    def drop_before(self, i):
        for k in [k for k in self.buf if k < i]:
            del self.buf[k]


def _flow_between(f0, f1, w, cache, key):
    """Motion-interpolated frame at fraction w between f0 and f1 (DIS optical flow, both directions)."""
    import cv2
    import numpy as np
    h, wd = f0.shape[:2]
    if cache.get('key') != key:
        s = min(1.0, 640 / max(h, wd))
        sw, sh = max(16, int(wd * s)), max(16, int(h * s))
        g0 = cv2.cvtColor(cv2.resize(f0, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY)
        g1 = cv2.cvtColor(cv2.resize(f1, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY)
        dis = cache.get('dis') or cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        cache['dis'] = dis
        f01 = cv2.resize(dis.calc(g0, g1, None), (wd, h)) / s
        f10 = cv2.resize(dis.calc(g1, g0, None), (wd, h)) / s
        if 'gx' not in cache or cache['gx'].shape != (h, wd):
            cache['gx'], cache['gy'] = np.meshgrid(np.arange(wd, dtype=np.float32), np.arange(h, dtype=np.float32))
        cache.update(key=key, f01=f01, f10=f10)
    gx, gy, f01, f10 = cache['gx'], cache['gy'], cache['f01'], cache['f10']
    w = float(w)
    f32 = np.float32
    a = cv2.remap(f0, (gx - w * f01[..., 0]).astype(f32), (gy - w * f01[..., 1]).astype(f32), cv2.INTER_LINEAR,
                  borderMode=cv2.BORDER_REPLICATE)
    b = cv2.remap(f1, (gx - (1 - w) * f10[..., 0]).astype(f32), (gy - (1 - w) * f10[..., 1]).astype(f32),
                  cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return cv2.addWeighted(a, 1 - w, b, w, 0)


def _ramp_audio(job, src, grid, speed, cum, total):
    """Sound for the ramp: pitch kept (rubberband / atempo driven by the speed curve), varispeed or none."""
    import numpy as np
    mode = job.p['sound']
    if mode not in ('pitch', 'varispeed', 'mute'):
        raise ValueError('speed_ramp: sound is pitch, varispeed or mute')
    if mode == 'mute' or not src.has_audio:
        return None
    ff = made.ffmpeg_exe()
    raw = job.work / 'src.wav'
    _run([ff, '-hide_banner', '-y', '-ss', f'{src.start:.4f}', '-t', f'{src.dur:.4f}', '-i', src.path, '-vn', '-ac', '2',
          '-ar', '48000', '-c:a', 'pcm_f32le', raw], 'audio extract')
    out = job.work / 'ramp.wav'
    if mode == 'varispeed':
        import soundfile as sf
        y, sr = sf.read(raw, dtype='float32', always_2d=True)
        t_out = np.arange(int(round(total * sr))) / sr
        pos = np.interp(t_out, cum, grid) * sr
        res = np.stack([np.interp(pos, np.arange(len(y)), y[:, c]) for c in range(y.shape[1])], axis=1)
        sf.write(out, res.astype(np.float32), sr, subtype='PCM_16')
        return out
    # pitch kept: tempo commands at source times (the filter sees source timestamps)
    have_rb = 'rubberband' in _filters(ff)
    lines, last = [], None
    step = max(1, len(grid) // max(1, int(src.dur * 40)))
    for i in range(0, len(grid), step):
        v = float(speed[i])
        if last is None or abs(v - last) > 0.004:
            if have_rb:
                lines.append(f'{grid[i]:.4f} rubberband tempo {v:.5f};')
            else:
                c = max(0.5, v ** (1 / 3))
                lines.append(f'{grid[i]:.4f} atempo@a tempo {c:.5f}, atempo@b tempo {c:.5f}, atempo@c tempo {c:.5f};')
            last = v
    (job.work / 'tempo.cmd').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    v0 = float(speed[0])
    stretch = (f'rubberband=tempo={v0:.5f}:transients=mixed:window=standard' if have_rb else
               ','.join(f'atempo@{n}=tempo={max(0.5, v0 ** (1 / 3)):.5f}' for n in 'abc'))
    _run([ff, '-hide_banner', '-y', '-i', raw.name, '-af', f'asendcmd=f=tempo.cmd,{stretch},'
          f'apad=whole_dur={total:.4f},atrim=0:{total:.4f}', '-c:a', 'pcm_s16le', out.name], 'pitch-kept speed',
         cwd=job.work)
    return out


_filter_cache = {}


def _filters(ff):
    if ff not in _filter_cache:
        r = subprocess.run([str(ff), '-hide_banner', '-filters'], capture_output=True, text=True, creationflags=NO_WINDOW)
        _filter_cache[ff] = r.stdout
    return _filter_cache[ff]


def _fx_speed_ramp(job):
    import numpy as np
    p = job.p
    if p['frames'] not in ('flow', 'blend', 'nearest'):
        raise ValueError('speed_ramp: frames is flow, blend or nearest')
    shots = _creator('shots')
    src = job.src()
    grid, speed, cum = _ramp_curve(job.source, p, job.given)
    total_s = float(cum[-1])
    n = max(1, int(round(total_s * job.fps)))
    t_src = np.interp(np.arange(n) / job.fps, cum, grid)
    t_next = np.interp((np.arange(n) + 1) / job.fps, cum, grid)
    sfps = src.native_fps if src.native_fps > job.fps * 1.2 else job.fps
    sfps = min(sfps, 240.0)
    count = int(math.ceil(src.dur * sfps)) + 2
    reader = shots.FrameReader(src.path, src.start, count, sfps, job.W, job.H)
    frames = _Frames(iter(reader))
    flow_cache = {}
    tmp = job.work / 'ramp.mp4'
    with _reading(reader), shots.VideoWriter(tmp, job.W, job.H, job.fps) as wr:
        for k in range(n):
            f, fn = t_src[k] * sfps, t_next[k] * sfps
            i0 = int(math.floor(f))
            frames.drop_before(i0 - 1)
            if p['frames'] == 'nearest':
                img = frames.get(int(round(f)))
            elif fn - f > 1.5:                            # fast: average what the frame covers (motion blur)
                picks = np.linspace(f, fn, min(8, int(fn - f) + 1), endpoint=False)
                acc = np.zeros((job.H, job.W, 3), np.float32)
                for q in picks:
                    acc += frames.get(int(round(q)))
                img = (acc / len(picks) + 0.5).astype(np.uint8)
            else:
                w = f - i0
                if w < 0.04:
                    img = frames.get(i0)
                elif w > 0.96:
                    img = frames.get(i0 + 1)
                elif p['frames'] == 'flow':
                    img = _flow_between(frames.get(i0), frames.get(i0 + 1), w, flow_cache, i0)
                else:
                    img = ((1 - w) * frames.get(i0).astype(np.float32) + w * frames.get(i0 + 1) + 0.5).astype(np.uint8)
            wr.write(img)
    audio = _ramp_audio(job, src, grid, speed, cum, n / job.fps)
    whoosh = None
    if p.get('whoosh'):
        reactions = _creator('reactions')
        found = reactions.find_sound('whoosh')
        slow = np.nonzero(speed < 0.9)[0]
        if found and len(slow):
            whoosh = (found, max(0.0, float(np.interp(grid[slow[0]], grid, cum)) - 0.25))
        else:
            job.notes.append('no whoosh added: ' + ('the ramp never slows' if found else
                                                    reactions.NO_SOUND_WHY.format(name='whoosh')))
    dur = n / job.fps
    cmd = [made.ffmpeg_exe(), '-hide_banner', '-y', '-i', tmp]
    inputs = [x for x in (audio, whoosh and whoosh[0]) if x]
    for x in inputs:
        cmd += ['-i', x]
    cmd += ['-map', '0:v:0', '-c:v', 'copy', '-bsf:v', H264_TAG]
    if inputs:
        chains, labels = [], []
        if audio:
            chains.append('[1:a]anull[a0]')
            labels.append('[a0]')
        if whoosh:
            chains.append(f'[{len(inputs)}:a]adelay={int(whoosh[1] * 1000)}:all=1,volume=0.8[a1]')
            labels.append('[a1]')
        mix = (f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest," if len(labels) > 1
               else f"{labels[0]}anull,")
        chains.append(f'{mix}apad=whole_dur={dur:.4f},atrim=0:{dur:.4f}[aout]')
        cmd += ['-filter_complex', ';'.join(chains), '-map', '[aout]', '-c:a', 'aac', '-b:a', '256k', '-ar', '48000']
    _run(cmd + ['-t', f'{dur:.4f}', '-movflags', '+faststart', job.out], 'speed ramp mux')
    lo, hi = float(speed.min()), float(speed.max())
    job.notes.append(f'{src.dur:.2f} s of source -> {dur:.2f} s (speed {lo:.2f}-{hi:.2f})')
    return n


# ---------------------------------------------------------------------------- Blender effects

def _blender_frames(job, template, frames, light=None):
    config, hardware = _vfx('config'), _vfx('hardware')
    p = job.p
    if p.get('quality', 'final') not in ('final', 'draft'):
        raise ValueError('quality is final or draft')
    tier = hardware.detect()
    final = p.get('quality', 'final') == 'final'
    scale = 1.0 if final else tier['settings']['preview_scale']
    rdir = job.work / 'render'
    rdir.mkdir(parents=True, exist_ok=True)
    tparams = {k: v for k, v in p.items() if k not in BLENDER_SETTINGS and v is not None}
    bjob = {'effect': template, 'params': tparams, 'width': job.W, 'height': job.H,
            'render_width': _even(job.W * scale), 'render_height': _even(job.H * scale), 'fps': job.fps,
            'frames': int(frames), 'samples': tier['settings']['final_samples' if final else 'preview_samples'],
            'out_dir': str(rdir), 'light': light, 'seed': int(p.get('seed', 7)), 'engine': 'AUTO'}
    jf = rdir / 'blender_job.json'
    jf.write_text(json.dumps(bjob, indent=1), encoding='utf-8')
    with open(rdir / 'blender.log', 'w', encoding='utf-8', errors='replace') as log:
        proc = subprocess.run([str(config.blender_exe()), '-b', '--factory-startup', '--python',
                               str(config.BLENDER_SCRIPTS / 'runner.py'), '--', str(jf)], stdout=log,
                              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
                              timeout=TIMEOUT)
    try:
        st = json.loads((rdir / 'render_status.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        st = {'state': 'failed', 'error': 'no render status written'}
    if proc.returncode != 0 or st.get('state') != 'done':
        tail = (rdir / 'blender.log').read_text(encoding='utf-8', errors='replace')[-1500:]
        raise RuntimeError(f"Blender render failed: {str(st.get('error', ''))[-2000:]}\n{tail}")
    job.notes.append(f"Blender {st.get('engine')} at {bjob['render_width']}x{bjob['render_height']}")
    return sorted(rdir.glob('elem_*.png'))


def _fx_blender_overlay(job):
    composite, media = _vfx('composite'), _vfx('media')
    if job.effect == 'blender' and not str(job.p.get('script') or '').strip():
        raise ValueError('blender needs params.script (Blender Python defining build(ctx))')
    frames = max(1, int(round(job.length * job.fps)))
    elems = _blender_frames(job, BLENDER_TEMPLATE[job.effect], frames)
    over = composite.overlay_frames(elems, job.work / 'over', (job.W, job.H), glow=float(job.p.get('glow') or 0))
    tmp = job.work / 'overlay.mov'
    media.encode_overlay(over[0].parent / 'over_%05d.png', job.fps, tmp)
    _tag_copy(tmp, job.out, alpha=True)
    return len(over)


def _shake(frames, elems, size, amount, seed=3):
    """Camera shake that follows the effect's energy: zoom in 3% and move within that margin (edges never show)."""
    import numpy as np
    from PIL import Image
    w, h = size
    energies = []
    for e in elems[:len(frames)]:
        im = np.asarray(Image.open(e).convert('RGBA').resize((max(8, w // 8), max(8, h // 8))), np.float32) / 255
        energies.append(float((im[..., :3].mean(axis=2) * im[..., 3]).mean()))
    peak = max(energies or [0]) or 1.0
    rng = np.random.default_rng(seed)
    z = 1.03
    margin_x, margin_y = (w - w / z) / 2, (h - h / z) / 2
    for path, en in zip(frames, energies):
        en /= peak
        if en <= 0.05:
            continue
        amp = amount * en * h * 0.012
        dx, dy = rng.normal(0, amp, 2)
        dx = float(np.clip(dx, -margin_x * 0.95, margin_x * 0.95))
        dy = float(np.clip(dy, -margin_y * 0.95, margin_y * 0.95))
        img = Image.open(path).convert('RGB')
        img = img.transform(size, Image.AFFINE, (1 / z, 0, margin_x + dx, 0, 1 / z, margin_y + dy), Image.BILINEAR)
        img.save(path, quality=95)


def _fx_explosion(job):
    analyze, composite, media = _vfx('analyze'), _vfx('composite'), _vfx('media')
    shots = _creator('shots')
    p = job.p
    if p['occlusion'] not in ('subject', 'depth', 'subject+depth', 'none'):
        raise ValueError('explosion: occlusion is subject, depth, subject+depth or none')
    src = job.src()
    an = job.work / 'analysis'
    plates = media.frames_from_file(src.path, src.start, src.frames / job.fps, job.fps, (job.W, job.H), an)
    with shots.GPU_LOCK:
        result = analyze.analyze(plates, an, job.fps)
    elems = _blender_frames(job, 'explosion', len(plates), light=result.get('light'))
    # composite.py's own shake zooms out (black edges show), so shake is applied here instead
    comp = composite.composite_frames(plates, elems, an, job.work / 'comp', occlusion=p['occlusion'],
                                      depth_cut=float(p['depth_cut']), glow=float(p['glow']),
                                      flicker=float(p['flicker']), shake=0.0, size=(job.W, job.H))
    if float(p['shake']) > 0:
        _shake(comp, elems, (job.W, job.H), float(p['shake']), int(p.get('seed', 7)))
    tmp = job.work / 'explosion.mp4'
    media.encode_full(comp[0].parent / 'comp_%05d.jpg', job.fps, tmp)
    if not result.get('subject_found') and 'subject' in p['occlusion']:
        job.notes.append('no person found in the shot: nothing is kept in front of the blast')
    _mux(job, tmp, src, len(comp))
    return len(comp)


def _fx_lighting(job):
    import letitedit.looks.lighting as lighting
    return lighting.render_job(job)


_RENDER = {
    "lighting": _fx_lighting,
    'annotate': _fx_annotate, 'blur': _fx_blur, 'erase': _fx_erase, 'backdrop': _fx_backdrop,
    'text_behind': _fx_text_behind, 'clone': _fx_clone, 'cutout': _fx_cutout, 'object': _fx_object, 'sky': _fx_sky,
    'speed_ramp': _fx_speed_ramp, 'tool_popup': _fx_blender_overlay, 'bus_drive': _fx_blender_overlay,
    'blender': _fx_blender_overlay, 'explosion': _fx_explosion, 'light_leak': _fx_light_leak,
}


# ---------------------------------------------------------------------------- voice (narration)

_voices = None


def voices():
    """Kokoro voice names (read from the voices file, without loading the speech model)."""
    global _voices
    if _voices is None:
        import numpy as np
        path = _creator('dub').VOICES
        if not Path(path).exists():
            raise FileNotFoundError(f'{path} missing (Kokoro voices)')
        with np.load(path) as data:
            _voices = sorted(data.keys())
    return _voices


def voice_recipe(item):
    v = item['voice']
    if isinstance(v, str):
        v = {'text': v}
    if not isinstance(v, dict):
        raise ValueError('a voice item is {voice: {text, voice?, speed?}}')
    extra = set(v) - {'text', 'voice', 'speed'}
    if extra:
        raise ValueError(f"voice takes text, voice and speed (got {', '.join(sorted(extra))})")
    text = ' '.join(str(v.get('text') or '').split())
    if not text:
        raise ValueError('voice: text is empty')
    name = str(v.get('voice') or VOICE_DEFAULT)
    if name not in voices():
        raise ValueError(f"voice: unknown voice {name!r}; voices: {', '.join(voices())}")
    r = {'kind': 'voice', 'text': text, 'voice': name}
    sp = float(v.get('speed', 1.0))
    if not 0.5 <= sp <= 2.0:
        raise ValueError('voice: speed is 0.5-2')
    if sp != 1.0:
        r['speed'] = sp
    return r


def voice_view(recipe_):
    v = {'text': recipe_['text'], 'voice': recipe_['voice']}
    if recipe_.get('speed', 1.0) != 1.0:
        v['speed'] = recipe_['speed']
    return {'voice': v}


def _voice_key(recipe_):
    key = json.dumps({'r': {k: recipe_.get(k) for k in ('text', 'voice', 'speed')}, 'engine': ENGINE}, sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _voice_master(recipe_):
    """The spoken line as a 48 kHz stereo WAV in the shared voice cache (synthesised once)."""
    path = CACHE / 'voice' / f'{_voice_key(recipe_)}.wav'
    if path.exists():
        return path
    import numpy as np
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    dub, shots = _creator('dub'), _creator('shots')
    started = time.monotonic()
    with contextlib.redirect_stdout(_ToLog()):
        k = dub.kokoro()
        with shots.GPU_LOCK:
            y, sr = k.create(recipe_['text'], voice=recipe_['voice'], speed=float(recipe_.get('speed', 1.0)),
                             lang=VOICE_LANG.get(recipe_['voice'][0], 'en-us'))
    y = np.asarray(y, np.float32).reshape(-1)
    y = np.concatenate([np.zeros(int(sr * 0.08), np.float32), y, np.zeros(int(sr * 0.25), np.float32)])
    y = y / (float(np.abs(y).max()) or 1.0) * 0.89
    raw = path.with_name(f'{path.stem}.{uuid.uuid4().hex[:6]}.raw.wav')
    tmp = path.with_name(f'{path.stem}.{uuid.uuid4().hex[:6]}.tmp.wav')
    try:
        sf.write(raw, y, sr, subtype='FLOAT')
        _run([made.ffmpeg_exe(), '-hide_banner', '-y', '-i', raw, '-af', 'aresample=48000', '-ac', '2',
              '-c:a', 'pcm_s16le', tmp], 'voice resample')
        os.replace(tmp, path)
    finally:
        raw.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    _logger().info('voice %s %r: %.2f s of speech in %.1f s', recipe_['voice'], recipe_['text'][:60],
                   len(y) / sr, time.monotonic() - started)
    return path


def render_voice(recipe_, out_dir):
    out_dir = Path(out_dir)
    dst = out_dir / f'voice-{_voice_key(recipe_)}.wav'
    if dst.exists():
        return {'path': str(dst), 'cached': True, 'alpha': False}
    master = _voice_master(recipe_)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f'{dst.stem}.{uuid.uuid4().hex[:6]}.tmp.wav')
    shutil.copyfile(master, tmp)
    os.replace(tmp, dst)
    return {'path': str(dst), 'cached': False, 'alpha': False}


def voice_len(item):
    if item.get('len') is not None:
        return _sec(item['len'])
    import soundfile as sf
    return float(sf.info(str(_voice_master(voice_recipe(item)))).duration)


# ---------------------------------------------------------------------------- the LLM's menu

def _fmt(v, required=False):
    if required:
        return 'REQUIRED'
    if v is None:
        return 'none'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, str):
        return v if v else "''"
    return json.dumps(v)


def describe_one(name):
    """One effect from describe(): its heading line and what follows it, up to the next effect."""
    if name not in EFFECTS:
        close = [e for e in EFFECTS if name.lower() in e.lower() or e.lower() in name.lower()]
        raise ValueError(f"unknown vfx effect {name!r}; effects: {', '.join(close or EFFECTS)}")
    lines, out, on = describe().splitlines(), [], False
    for line in lines:
        head = line.split('  [', 1)[0] if '  [' in line and not line.startswith(' ') else None
        if head in EFFECTS:
            on = head == name
        elif on and not line.startswith(' ') and line.strip():
            on = False
        if on:
            out.append(line)
    return '\n'.join(out)


def describe():
    """Every effect, its params (defaults) and output kind, the voice item and its voices: compact text."""
    out = [
        'VFX ITEMS - shot effects as timeline items (made clips; insert/set them with letitedit_timeline_apply).',
        '  {id, vfx: {effect: NAME, source: {clip, in, out, speed?}, params: {...}}, len?}',
        '  {id, voice: {text, voice?, speed?}}   a narrated line (local Kokoro TTS) -> an audio clip: put it on an '
        'audio track',
        'Output: replace = full-frame clip WITH the source sound: put it where the plain clip would go (e.g. V1, '
        'instead of it).',
        '        overlay = transparent layer, no sound: put it on a video track above the footage, starting where that '
        'footage starts.',
        'Times inside vfx (in/out, at, keys, slow) are SOURCE seconds, the clip\'s own clock. Boxes [x, y, w, h] are in '
        'the source picture: pixels, or fractions 0-1 when all values are <= 1 (coords: frame = the project frame).',
        'An effect with a source lasts as long as the source range (speed_ramp: as its speeds make it); len and skip '
        'on the item trim the made clip. Effects without a source render exactly len.',
        'Renders are cached (re-applying an unchanged item is instant; changing params or the source re-renders). '
        'Tracking, erase, mattes and Blender take from seconds to minutes. Look at the result with '
        'letitedit_check_frames.',
        '',
    ]
    for name, e in EFFECTS.items():
        src = {'required': 'needs source', 'none': f"no source, len (default {e.get('len')} s)"}[e['source']]
        out.append(f"{name}  [{e['output']}, {src}]  {e['description']}")
        parts = []
        for k, v in e['params'].items():
            hint = e['hints'].get(k)
            parts.append(f"{k}={_fmt(v, k in e['required'])}" + (f' ({hint})' if hint else ''))
        out.append('    params: ' + '; '.join(parts))
        if e['notes']:
            out.append('    note: ' + e['notes'])
    out += ['', 'Examples:',
            "  {op: insert, track: V2, after: <id>, item: {vfx: {effect: annotate, source: {clip: C, in: 12, out: 16}, "
            "params: {shape: arrow, box: [0.42, 0.55, 0.12, 0.1], label: 'set screw'}}}}",
            "  {op: insert, track: V1, after: <id>, item: {vfx: {effect: speed_ramp, source: {clip: C, in: 30, out: 36}, "
            "params: {slow: [32, 33.5], speed: 0.3}}}}",
            "  {op: insert, track: A1, after: <id>, item: {voice: {text: 'Two hours later...', voice: am_michael}}}",
            '']
    try:
        names = voices()
        groups = {}
        for v in names:
            groups.setdefault(v[0], {}).setdefault('female' if v[1] == 'f' else 'male', []).append(v)
        out.append(f'Voices (default {VOICE_DEFAULT}; speed 0.5-2):')
        for pre, g in groups.items():
            out.append(f"  {VOICE_LANG_NAME.get(pre, pre)}: female {' '.join(g.get('female', [])) or '-'}; "
                       f"male {' '.join(g.get('male', [])) or '-'}")
    except (FileNotFoundError, OSError) as exc:
        out.append(f'Voices: unavailable ({exc})')
    return '\n'.join(out)
