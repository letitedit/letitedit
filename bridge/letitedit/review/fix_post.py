r"""Fix-in-post: repaired copies of the part of a source a clip uses, made once and cached; the original is never touched.

Fixes (kind: settings with their defaults in DEFAULTS; every value used is reported):
  night  denoise (SCUNet real-noise model on the GPU, or ffmpeg nlmeans / hqdn3d) + temporal smoothing + brightening
         (gamma from the measured brightness toward target_luma)
  shake  stabilisation (vid.stab two-pass in the vid.stab ffmpeg build, or ffmpeg deshake)
  punch  a tighter framing (zoom x the frame that fills the output) centred on a focus point that can follow the subject
         (given points, tracker results, footage action points, centre); upscaled with Real-ESRGAN when the crop has
         fewer pixels than the output, plain resize when the source has enough
  voice  speech enhancement: DeepFilterNet 3 denoise on the whole mix by default (separate false, dereverb false);
         optional Demucs separation (voice / rest) and WPE dereverb (nara_wpe), the voice stem remixed with the rest
         stem at its own gain; the stems are kept as files

    run(source, start=None, end=None, fix='night', settings=None, fps=None, size=None, max_size=None, sheet=True,
        sheet_frames=3, progress=None) -> {'file', 'kind', 'engine', 'settings', 'measures': {'before', 'after'},
        'sheet', 'took_s', 'cached', ...}
    chain(clip, start, end, fixes, fps, max_w, max_h) -> {'video': path|None, 'audio': path|None, 'offset': s, 'steps'}
        (what made.render_fx uses for {fix: {...}} effects on a clip)
    cached(source=None) -> the cached repairs

Cache: <LETITEDIT_CACHE or C:\LetItEdit\cache>\fix\<family>\<start>-<end>\ (family = source file identity, fix,
settings, engine, fps, size). A cached repair whose range covers a later request is reused (offset into it).
Model work runs in C:\LetItEdit\envs\models (fix_worker.py) under the model GPU lock (model_tools._gpu_turn);
renders of more than render_lock_over_s seconds of footage hold the PC render lock (render_lock.slot).
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import copy
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'fix'
MODELS = Path(os.environ.get('LETITEDIT_MODELS_HOME', (_SAI_ROOT + '\\models')))
APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))
VIDSTAB_FFMPEG = Path(os.environ.get('LETITEDIT_VIDSTAB_FFMPEG', MODELS / 'ffmpeg-vidstab' / 'extracted' /
                                     'ffmpeg-n8.1-latest-win64-gpl-8.1' / 'bin' / 'ffmpeg.exe'))
if not os.environ.get('LETITEDIT_VIDSTAB_FFMPEG') and not VIDSTAB_FFMPEG.exists():
    # a dated BtbN build (model_fetch pins one) unpacks into its own folder name
    VIDSTAB_FFMPEG = next(iter(sorted((MODELS / 'ffmpeg-vidstab' / 'extracted').glob('ffmpeg-*/bin/ffmpeg.exe'))),
                          VIDSTAB_FFMPEG)
DEEP_FILTER = Path(os.environ.get('LETITEDIT_DEEP_FILTER', MODELS / 'deepfilternet' /
                                  'deep-filter-0.5.6-x86_64-pc-windows-msvc.exe'))
WORKER = HERE / 'fix_worker.py'
ENGINE_VERSION = 1
KINDS = ('night', 'shake', 'punch', 'voice')
VIDEO_KINDS = ('night', 'shake', 'punch')
FONT = r'C:\Windows\Fonts\segoeui.ttf'

COMMON = {
    'crf': 14,                  # x264 quality of the repaired copy (lower = bigger, closer to lossless)
    'preset': 'medium',         # x264 preset
    'render_lock_over_s': 30.0,  # renders of more footage than this hold the PC render lock
}
DEFAULTS = {
    'night': {
        'denoise': 'auto',      # auto (scunet when its weights and a CUDA GPU are there, else nlmeans) | scunet | nlmeans | hqdn3d | none
        'strength': 0.9,        # scunet: 1 = model output, 0 = untouched (blend); nlmeans: s = 3.5 x strength; hqdn3d: 4 x strength
        'temporal': 3.0,        # hqdn3d temporal-only smoothing after the denoise (luma strength; 0 = off)
        'brighten': 'auto',     # auto: gamma = log(brightness)/log(target_luma) when darker than target (1..max_gamma); a number = that gamma; 0/off = none
        'target_luma': 0.36,    # mean luma (0-1) brighten=auto aims for
        'max_gamma': 1.6,       # cap on the auto gamma
        'contrast': 1.08,       # eq contrast applied with the brightening (keeps blacks from going grey)
        'saturation': 1.0,      # eq saturation applied with the brightening
        'tile': 0,              # scunet tile size in px (0 = whole frame; ~3.1 GB GPU at 1920x1080)
        'half': True,           # scunet in fp16
    },
    'shake': {
        'engine': 'auto',       # auto (vidstab when the vid.stab ffmpeg is there, else deshake) | vidstab | deshake
        'smoothing': 15,        # vidstab: frames each side averaged for the camera path (bigger = smoother, more crop)
        'shakiness': 5,         # vidstabdetect 1-10
        'accuracy': 15,         # vidstabdetect 1-15
        'stepsize': 6,          # vidstabdetect search step px
        'optzoom': 1,           # vidstabtransform: 0 = fixed zoom only, 1 = static zoom so no border shows, 2 = adaptive zoom
        'zoom': 0.0,            # vidstabtransform extra zoom % (added to optzoom's)
        'maxshift': -1,         # px limit of the shift per frame (-1 = none)
        'maxangle': -1.0,       # radians limit of the rotation per frame (-1 = none)
        'crop': 'black',        # vidstabtransform border: black | keep (previous frame)
        'tripod': False,        # vidstab: hold the first frame's position (locked-off camera)
        'sharpen': 0.8,         # unsharp luma amount after the transform (0 = none)
        'deshake_rx': 32,       # deshake search range px (x and y) when engine is deshake
    },
    'punch': {
        'zoom': 2.0,            # x the frame that just fills the output (2 = half the width and height of the fill)
        'focus': 'auto',        # [x, y] (0-1 of the source frame) | [[source s, x, y], ...] | track | action | centre | auto (given, track, action, centre)
        'engine': 'auto',       # auto (none when the crop has the output's pixels or the PC has no graphics card for the model, realesrgan-x2plus up to 2x, realesr-general-x4v3 above) | realesrgan-x2plus | realesr-general-x4v3 | none
        'smooth_s': 1.0,        # moving average over the focus path (seconds)
        'deadzone': 0.03,       # the framing stays until the focus moved this fraction of the frame
        'min_score': 0.3,       # tracker samples under this confidence are not used
        'tile': 0,              # model tile size px (0 = whole crop)
        'half': True,
    },
    'voice': {
        'separate': 'auto',     # auto = decided from the clip's own gaps when it is made: True where something plays between
                                # the words (see AUTO_SEPARATE_DB), else False; the result says which and the number
                                # False = DeepFilterNet on the whole mix (everything but speech is noise, up to atten_lim_db off);
                                # True = Demucs voice/rest split first, only the voice stem is cleaned and the rest stem is
                                # remixed at rest_gain_db (work sounds and other non-voice sounds keep their level)
        'separation_model': 'htdemucs',
        'dereverb': False,      # WPE on the voice (on a noisy whole mix it lowered the speech by 10 dB)
        'taps': 10, 'delay': 3, 'iterations': 3,   # WPE settings (STFT 512 / shift 128)
        'denoise': True,        # DeepFilterNet 3 on the voice
        'atten_lim_db': 18,     # DeepFilterNet attenuation limit dB (lower keeps more of the noise; 100 = no limit, which
                                # over-suppresses into an 'underwater' voice; 100 until 2026-10-29)
        'post_filter': False,   # DeepFilterNet post-filter
        'voice_gain_db': 0.0,   # gain on the enhanced voice in the remix
        'rest_gain_db': 0.0,    # gain on the rest stem in the remix (-120 = left out)
    },
}


# ------------------------------------------------------------------ small helpers

# 'separate: auto' (voice). The two mistakes cost differently. The whole mix on a clip where a sound matters (a tool, a machine
# working in the gaps) takes that sound down 11-18 dB: harmful. Separating a clip that is only room keeps some room noise (the old
# behaviour) and takes a few seconds longer: cheap. So the line sits just above the talk-only readings and every in-between
# clip falls on the safe side. Readings of the gaps' median over the quietest tenth (speech.gap_fact, T46, 73 stretches of 29
# clips): talk-only 0.2-2.4 dB (T44's IMG_0014 and IMG_0455, the owner's other talking heads, T38's hiss mixes 1.2 and 1.4); the two
# clips known to have a sound in the gaps 8.5-10.7; 40 stretches in between (2.5-8.4, mostly the Rear AC shoot) have NO ground
# truth, which is why the limit is 3.0 and not a number the data picks. Not the 90th percentile (a breath or a cough in a gap
# moves it on room-only clips).
AUTO_SEPARATE_DB = 3.0     # separate when the median, over the range OR over the whole source file, reaches this (dB over the quietest tenth)
AUTO_MIN_WINDOWS = 5       # fewer gap windows (of 0.1 s) than this in a stretch can't be measured
AUTO_WHOLE_FILE_MAX_S = 1200   # the whole file is read too (a trim must not flip the decision) when it is no longer than this


def resolve_separate(src, a, b):
    """'separate: auto' for voice: (True|False, what it measured). Words first (cached; else transcribed now under the render
    lock), so it never decides blind. Rules:
      no speech found in the range (or the words can't be had)    -> True (the whole mix would crush everything)
      gap median over the range OR over the whole file >= limit    -> True  (a sound plays between the words)
      measured, under the limit                                    -> False (room only: the whole mix, the owner's pick)
      too few gaps to measure in both                              -> False, and the note says so
    The note carries both medians, their window counts, the limit and the reason."""
    import letitedit.footage.speech as speech
    note = {'limit_db': AUTO_SEPARATE_DB, 'rule': f'a median of {AUTO_SEPARATE_DB:g} dB over the quietest tenth, in the range or in the whole file, means a sound plays between the words'}
    whole_ok = False
    try:
        dur = float(speech._duration(str(src)))
        whole_ok = dur <= AUTO_WHOLE_FILE_MAX_S
        in_range = speech.words(str(src), a, b)          # cached, else transcribed here
        if whole_ok:
            speech.words(str(src))                       # the whole file's words, for the whole-file reading
    except Exception as e:  # noqa: BLE001 - a Busy (a render has the PC) must say so, never silently choose
        if type(e).__name__ == 'Busy':
            raise
        note.update(chose='separate', why=f'the words could not be had ({type(e).__name__}); with no way to tell, the voice stem is cleaned and the rest kept')
        return True, note
    if not in_range:
        note.update(chose='separate', why='the speech model found no speech in this range, so the gaps cannot be measured and the whole mix would lower everything')
        return True, note
    rng = speech.gap_fact(src, a, b)
    whole = speech.gap_fact(src) if whole_ok else None
    def usable(g):
        return g if g and g['windows'] >= AUTO_MIN_WINDOWS else None
    r, w = usable(rng), usable(whole)
    if rng:
        note.update(range_windows=rng['windows'], range_median_db=rng['median_db'], range_p90_db=rng['p90_db'])
    if whole:
        note.update(file_windows=whole['windows'], file_median_db=whole['median_db'])
    def txt(label, g, ok):
        if not g:
            return f'{label}: no gaps' if ok else f'{label}: not read'
        return f"{label}: median {g['median_db']:.1f} dB over {g['windows']} windows" + ('' if g['windows'] >= AUTO_MIN_WINDOWS else ' (too few)')
    both = f"{txt('range', rng, True)}; {txt('whole file', whole, whole_ok)}; limit {AUTO_SEPARATE_DB:g} dB"
    if r is None and w is None:
        note.update(chose='whole mix', why=f'too few gaps between the words to measure ({both})')
        return False, note
    sep = any(g is not None and g['median_db'] >= AUTO_SEPARATE_DB for g in (r, w))
    note.update(chose='separate' if sep else 'whole mix',
                why=f"{'a sound plays between the words' if sep else 'room only between the words'} ({both})")
    return sep, note


def resolve_auto(kind, s, src, a, b):
    """Settles `separate: auto` in the settings dict s (in place) for a voice fix of src a-b; returns what it measured, or
    None when nothing was auto (another fix, or an explicit true or false, which always wins)."""
    if kind != 'voice' or s.get('separate') != 'auto':
        return None
    s['separate'], note = resolve_separate(src, a, b)
    return note


def _ffmpeg():
    import letitedit.timeline.made as made
    return str(made.ffmpeg_exe())


def _run(cmd, what, cwd=None, timeout=6 * 3600):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       cwd=cwd, timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f'{what} failed: {r.stderr.strip()[-1500:]}')
    return r


def probe(path):
    import letitedit.server.core_tools as core_tools
    return core_tools.probe(path)


def _identity(path):
    st = os.stat(path)
    return [str(Path(path).resolve()).lower(), st.st_size, int(st.st_mtime)]


def _even(x):
    return max(2, int(round(x / 2.0)) * 2)


def normalise(spec):
    """A fix effect's content -> {'kind', ...given settings} (unknown kinds/keys refused)."""
    if isinstance(spec, str):
        spec = {'kind': spec}
    if not isinstance(spec, dict) or spec.get('kind') not in KINDS:
        raise ValueError(f'a fix is {{kind: {"|".join(KINDS)}, ...settings}} (got {spec!r})')
    allowed = set(DEFAULTS[spec['kind']]) | set(COMMON) | {'kind'}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValueError(f"fix {spec['kind']}: unknown setting(s) {', '.join(unknown)}; it takes "
                         f"{', '.join(sorted(allowed - {'kind'}))}")
    spec = dict(spec)
    if spec['kind'] == 'voice' and 'separate' in spec:
        v = spec['separate']
        v = {'true': True, 'false': False, 'auto': 'auto'}.get(v.strip().lower(), v) if isinstance(v, str) else v
        if v not in (True, False, 'auto'):
            raise ValueError(f"fix voice: separate is true, false or auto (got {spec['separate']!r})")
        spec['separate'] = v
    return spec


def settings_for(spec):
    spec = normalise(spec)
    s = {**copy.deepcopy(COMMON), **copy.deepcopy(DEFAULTS[spec['kind']])}
    s.update({k: v for k, v in spec.items() if k != 'kind'})
    return s


FIX_MODELS = {'scunet': ['scunet'], 'realesrgan-x2plus': ['realesrgan'], 'realesr-general-x4v3': ['realesrgan']}


def _vidstab(required):
    """The vid.stab FFmpeg: on first use downloaded (manifest 'ffmpeg-vidstab', 184 MB) - required: errors raise;
    otherwise a refused / failed download leaves ffmpeg's own deshake to be used."""
    global VIDSTAB_FFMPEG
    if not VIDSTAB_FFMPEG.exists() and not os.environ.get('LETITEDIT_VIDSTAB_FFMPEG'):
        import letitedit.core.first_use as first_use
        if required:
            first_use.need(models=['ffmpeg-vidstab'], feature='shake fix (vid.stab)')
        else:
            first_use.optional(['ffmpeg-vidstab'], feature='shake fix (vid.stab)')
        VIDSTAB_FFMPEG = next(iter(sorted((MODELS / 'ffmpeg-vidstab' / 'extracted').glob('ffmpeg-*/bin/ffmpeg.exe'))),
                              VIDSTAB_FFMPEG)
    return VIDSTAB_FFMPEG


def _has_cuda_env():
    import letitedit.sound.model_tools as model_tools
    return Path(model_tools.MODELS_PYTHON).exists()


def gpu_ok():
    """This PC has a graphics card that runs the local picture models (hardware.vision_unavailable is None). Without
    one, 'auto' picks the engines that need no model: frame by frame on the processor they have no ceiling."""
    try:
        import letitedit.core.hardware as hardware
        return hardware.vision_unavailable() is None
    except Exception:  # noqa: BLE001 - no reading: as before
        return True


def resolve_engine(kind, s, src_info=None, crop_factor=None):
    """The engine a fix will use with these settings on this PC."""
    if kind == 'night':
        d = s['denoise']
        if d == 'auto':
            d = ('scunet' if (MODELS / 'scunet' / 'scunet_color_real_psnr.pth').exists() and _has_cuda_env()
                 and gpu_ok() else 'nlmeans')
        return d
    if kind == 'shake':
        e = s['engine']
        if e in ('auto', 'vidstab'):
            _vidstab(required=(e == 'vidstab'))
        if e == 'auto':
            e = 'vidstab' if VIDSTAB_FFMPEG.exists() else 'deshake'
        if e == 'vidstab' and not VIDSTAB_FFMPEG.exists():
            raise FileNotFoundError(f'vid.stab ffmpeg not found at {VIDSTAB_FFMPEG}')
        return e
    if kind == 'punch':
        e = s['engine']
        if e == 'auto':
            f = crop_factor or 1.0
            e = 'none' if f <= 1.02 else 'realesrgan-x2plus' if f <= 2.05 else 'realesr-general-x4v3'
            if e != 'none' and not gpu_ok():
                e = 'none'
        return e
    if kind == 'voice':
        parts = []
        if s['separate']:
            parts.append(f"demucs-{s['separation_model']}")
        if s['dereverb']:
            parts.append('wpe')
        if s['denoise']:
            parts.append('deepfilternet3')
        return '+'.join(parts) or 'remix only'
    raise ValueError(kind)


def _work_size(info, size=None, max_size=None):
    w, h = int(info.get('width') or 0), int(info.get('height') or 0)
    if size:
        return _even(size[0]), _even(size[1])
    if max_size and w and h:
        k = min(1.0, max_size[0] / w, max_size[1] / h)
        return _even(w * k), _even(h * k)
    return _even(w), _even(h)


# ------------------------------------------------------------------ cache

def _family(identity, kind, s, engine, fps, size, prev):
    key = json.dumps({'src': identity, 'kind': kind, 's': s, 'engine': engine, 'fps': round(fps or 0, 4),
                      'size': list(size) if size else None, 'prev': prev, 'v': ENGINE_VERSION}, sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def _lookup(family, a, b):
    d = CACHE / family
    if not d.is_dir():
        return None
    best = None
    for sub in d.iterdir():
        try:
            s0, s1 = (float(x) for x in sub.name.split('_'))
        except ValueError:
            continue
        if s0 <= a + 1e-3 and s1 >= b - 1e-3 and (sub / 'result.json').exists():
            if best is None or (s1 - s0) < best[1] - best[0]:
                best = (s0, s1, sub)
    if not best:
        return None
    res = json.loads((best[2] / 'result.json').read_text(encoding='utf-8-sig'))
    if not Path(res['file']).exists():
        return None
    return res


# ------------------------------------------------------------------ measures

def _frames(path, times, w, h, rotate_ok=True):
    """RGB uint8 arrays at the given source seconds, scaled to w x h."""
    import numpy as np
    out = []
    for t in times:
        r = subprocess.run([_ffmpeg(), '-v', 'error', '-ss', f'{max(0.0, t):.4f}', '-i', str(path), '-frames:v', '1',
                            '-vf', f'scale={w}:{h}:flags=bicubic', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                           capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        if len(r.stdout) >= w * h * 3:
            out.append(np.frombuffer(r.stdout[:w * h * 3], np.uint8).reshape(h, w, 3))
    return out


def _luma(img):
    import numpy as np
    return (0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]).astype(np.float32)


def _noise_sigma(gray):
    """Immerkaer's fast noise estimate (8-bit units; fine texture counts as noise too)."""
    import cv2
    import numpy as np
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    conv = cv2.filter2D(gray, -1, k)
    hh, ww = gray.shape
    return float(np.sum(np.abs(conv[1:-1, 1:-1])) * math.sqrt(math.pi / 2) / (6.0 * (ww - 2) * (hh - 2)))


def _shake(path, a, dur, fps, window_s=6.0, width=480):
    """Camera jitter: global shift between consecutive frames (phase correlation) over a window from the middle of the
    range; shake_px = mean distance of the camera path from its 1 s moving average, motion_px = mean shift per frame;
    both in px of a frame `width` wide."""
    import cv2
    import numpy as np
    span = min(dur, window_s)
    t0 = a + max(0.0, (dur - span) / 2)
    rate = min(fps or 30.0, 30.0)
    info = probe(path)
    W, H = int(info.get('width') or 16), int(info.get('height') or 9)
    h = _even(width * H / W)
    r = subprocess.run([_ffmpeg(), '-v', 'error', '-ss', f'{t0:.4f}', '-t', f'{span:.4f}', '-i', str(path), '-vf',
                        f'fps={rate:g},scale={width}:{h},format=gray', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'],
                       capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    n = len(r.stdout) // (width * h)
    if n < 3:
        return None
    frames = np.frombuffer(r.stdout[:n * width * h], np.uint8).reshape(n, h, width).astype(np.float32)
    win = cv2.createHanningWindow((width, h), cv2.CV_32F)
    path_xy = [(0.0, 0.0)]
    steps = []
    for i in range(1, n):
        (dx, dy), _ = cv2.phaseCorrelate(frames[i - 1], frames[i], win)
        steps.append(math.hypot(dx, dy))
        path_xy.append((path_xy[-1][0] + dx, path_xy[-1][1] + dy))
    p = np.array(path_xy)
    k = max(3, int(round(rate)) | 1)
    pad = np.pad(p, ((k // 2, k // 2), (0, 0)), mode='edge')
    smooth = np.stack([np.convolve(pad[:, j], np.ones(k) / k, mode='valid') for j in range(2)], 1)
    jitter = float(np.mean(np.hypot(*(p - smooth).T)))
    return {'shake_px': round(jitter, 2), 'motion_px': round(float(np.mean(steps)), 2), 'width_px': width,
            'window_s': round(span, 2), 'fps': rate}


def measure_video(path, a, dur, w, h, fps, samples=6, shake=True):
    """{'brightness' (mean luma 0-1), 'dark_share' (pixels under 0.06), 'noise' (Immerkaer sigma, 8-bit), 'sharpness'
    (variance of the Laplacian), 'shake_px', 'motion_px'} of path from a (s) for dur s, frames scaled to w x h."""
    import cv2
    import numpy as np
    times = [a + dur * (i + 0.5) / samples for i in range(samples)]
    imgs = _frames(path, times, w, h)
    if not imgs:
        return {}
    lum = [_luma(i) for i in imgs]
    m = {'brightness': round(float(np.mean([np.mean(x) for x in lum])) / 255.0, 4),
         'dark_share': round(float(np.mean([np.mean(x < 15.3) for x in lum])), 4),
         'noise': round(float(np.median([_noise_sigma(x) for x in lum])), 3),
         'sharpness': round(float(np.median([cv2.Laplacian(x, cv2.CV_32F).var() for x in lum])), 1),
         'frames_measured': len(imgs), 'size': [w, h]}
    if shake:
        sh = _shake(path, a, dur, fps)
        if sh:
            m.update(sh)
    return m


def _pcm(path, a, dur, rate=48000):
    import numpy as np
    r = subprocess.run([_ffmpeg(), '-v', 'error', '-ss', f'{a:.4f}', '-t', f'{dur:.4f}', '-i', str(path), '-vn', '-ac',
                        '1', '-ar', str(rate), '-f', 'f32le', '-'], capture_output=True, creationflags=NO_WINDOW,
                       stdin=subprocess.DEVNULL)
    return np.frombuffer(r.stdout, np.float32)


def measure_audio(path, a, dur):
    """{'lufs' (integrated, EBU R128), 'floor_db' (10th percentile of 50 ms RMS, dBFS), 'speech_db' (95th
    percentile), 'range_db' (speech - floor)}."""
    import numpy as np
    x = _pcm(path, a, dur)
    if x.size < 4800:
        return {}
    n = 2400
    frames = x[:x.size // n * n].reshape(-1, n)
    db = 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9)
    r = subprocess.run([_ffmpeg(), '-hide_banner', '-nostats', '-ss', f'{a:.4f}', '-t', f'{dur:.4f}', '-i', str(path),
                        '-vn', '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True, errors='replace',
                       creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    lufs = None
    tail = r.stderr[r.stderr.rfind('Summary'):]
    for line in tail.splitlines():
        line = line.strip()
        if line.startswith('I:'):
            try:
                lufs = float(line.split()[1])
            except (ValueError, IndexError):
                pass
            break
    floor, speech = float(np.percentile(db, 10)), float(np.percentile(db, 95))
    return {'lufs': lufs, 'floor_db': round(floor, 1), 'speech_db': round(speech, 1), 'range_db': round(speech - floor, 1)}


# ------------------------------------------------------------------ sheets

def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def _label(img, text, size=22):
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    f = _font(size)
    box = d.textbbox((0, 0), text, font=f)
    d.rectangle([0, 0, box[2] + 16, box[3] + 12], fill=(0, 0, 0))
    d.text((8, 4), text, fill=(255, 255, 255), font=f)
    return img


def frame_sheet(pairs, out, title, panel_w=640):
    """pairs: [(t, before RGB array, after RGB array, before label, after label)] -> a JPEG of before|after rows."""
    from PIL import Image
    rows = []
    for t, b, a, lb, la in pairs:
        ib, ia = Image.fromarray(b), Image.fromarray(a)
        hb = round(ib.height * panel_w / ib.width)
        ha = round(ia.height * panel_w / ia.width)
        h = max(hb, ha)
        row = Image.new('RGB', (panel_w * 2 + 8, h), (40, 40, 40))
        row.paste(_label(ib.resize((panel_w, hb), Image.LANCZOS), f'{lb}  {t:.2f}s'), (0, 0))
        row.paste(_label(ia.resize((panel_w, ha), Image.LANCZOS), la), (panel_w + 8, 0))
        rows.append(row)
    head = Image.new('RGB', (panel_w * 2 + 8, 44), (20, 20, 20))
    _label(head, title, 22)
    H = head.height + sum(r.height + 8 for r in rows)
    sheet = Image.new('RGB', (panel_w * 2 + 8, H), (20, 20, 20))
    sheet.paste(head, (0, 0))
    y = head.height
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 8
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=90)
    return str(out)


def _spectrogram(x, rate=48000, width=1200, height=300, floor_db=90.0):
    import numpy as np
    from PIL import Image
    n, hop = 2048, max(256, x.size // width)
    if x.size < n:
        return Image.new('RGB', (width, height))
    idx = np.arange(0, x.size - n, hop)[:width]
    win = np.hanning(n).astype(np.float32)
    spec = np.abs(np.fft.rfft(np.stack([x[i:i + n] * win for i in idx]), axis=1)).T
    db = 20 * np.log10(spec + 1e-6)
    db = np.clip((db - (db.max() - floor_db)) / floor_db, 0, 1)
    f = np.linspace(0, 1, spec.shape[0])
    rows = np.clip((np.log10(1 + 99 * np.linspace(0, 1, height)) / 2 * (spec.shape[0] - 1)).astype(int), 0,
                   spec.shape[0] - 1)
    img = db[rows][::-1]
    del f
    rgb = np.stack([img ** 0.7, img ** 1.5, (1 - img) * img * 2], -1)
    return Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).resize((width, height))


def audio_sheet(before, after, out, title, labels=('before', 'after')):
    from PIL import Image
    imgs = [_label(_spectrogram(x), lab) for x, lab in zip((before, after), labels)]
    head = _label(Image.new('RGB', (imgs[0].width, 44), (20, 20, 20)), title)
    sheet = Image.new('RGB', (imgs[0].width, head.height + sum(i.height + 8 for i in imgs)), (20, 20, 20))
    sheet.paste(head, (0, 0))
    y = head.height
    for i in imgs:
        sheet.paste(i, (0, y))
        y += i.height + 8
    sheet.save(out, quality=90)
    return str(out)


# ------------------------------------------------------------------ the fixes

def _worker(spec, progress=None, need_mb=3500):
    """Run fix_worker.py in the models env under the model GPU lock."""
    import tempfile
    import letitedit.sound.model_tools as model_tools
    import letitedit.core.first_use as first_use                                # first use: the models environment + the weights it runs
    first_use.need_for_python(model_tools.MODELS_PYTHON, FIX_MODELS.get(spec.get('model') or spec.get('op'), ()),
                              feature=f"fix ({spec.get('model') or spec.get('op')})")
    import letitedit.core.render_lock as render_lock
    with render_lock.model_slot(f"fix {spec.get('model') or spec.get('op')}"), model_tools._gpu_turn():   # the PC render lock first
        room = model_tools._room(need_mb, what=f"fix {spec.get('model') or spec.get('op')}")
        free = room['free_mb_at_start']
        with tempfile.TemporaryDirectory() as d:
            sp = Path(d) / 'spec.json'
            sp.write_text(json.dumps(spec), encoding='utf-8')
            p = subprocess.Popen([str(model_tools.MODELS_PYTHON), '-I', str(WORKER), str(sp)], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                                 creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
            result, err = None, None
            for line in p.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if 'progress' in msg and progress:
                    progress(msg['progress'], f"{msg.get('frames')} frames")
                if 'result' in msg:
                    result = msg['result']
                if 'error' in msg:
                    err = msg['error'] + '\n' + msg.get('trace', '')
            stderr = p.stderr.read()
            p.wait()
            p.stdout.close()
            p.stderr.close()
    if result is None:
        raise RuntimeError(f'fix worker failed: {err or stderr[-1500:]}')
    result['gpu_free_mb_at_start'] = free
    if 'waited_s' in room or 'short_mb' in room:     # it waited for other processes' GPU memory, or stayed short
        result['gpu_room'] = room
    return result


def _night(src, a, dur, fps, w, h, s, out, before, progress):
    engine = resolve_engine('night', s)
    gamma = 1.0
    b = (before or {}).get('brightness')
    br = s['brighten']
    if br in (0, False, None, 'off', 'none'):
        gamma = 1.0
    elif br == 'auto':
        if b and 0.005 < b < s['target_luma']:
            gamma = max(1.0, min(float(s['max_gamma']), math.log(b) / math.log(s['target_luma'])))
    else:
        gamma = float(br)
    post = []
    if float(s['temporal']) > 0:
        t = float(s['temporal'])
        post.append(f'hqdn3d=0:0:{t:g}:{t * 0.75:g}')
    if abs(gamma - 1.0) > 1e-3 or float(s['saturation']) != 1.0:
        con = float(s['contrast']) if abs(gamma - 1.0) > 1e-3 else 1.0
        post.append(f"eq=gamma={gamma:.4f}:contrast={con:g}:saturation={float(s['saturation']):g}")
    has_audio = bool(probe(src).get('audio'))
    info = {'gamma': round(gamma, 4)}
    if engine == 'scunet':
        r = _worker({'op': 'frames', 'ffmpeg': _ffmpeg(), 'src': str(src), 'start': a, 'dur': dur, 'fps': fps,
                     'in_w': w, 'in_h': h, 'out_w': w, 'out_h': h, 'model': 'scunet', 'strength': float(s['strength']),
                     'tile': int(s['tile']), 'half': bool(s['half']), 'vf_post': ','.join(post) or 'null',
                     'audio': has_audio, 'out': str(out), 'crf': s['crf'], 'preset': s['preset']}, progress,
                    need_mb=3500 if not s['tile'] else 1500)
        info.update(model=r)
    else:
        den = []
        k = float(s['strength'])
        if engine == 'nlmeans' and k > 0:
            den.append(f'nlmeans=s={3.5 * k:.2f}:p=7:r=15')
        elif engine == 'hqdn3d' and k > 0:
            den.append(f'hqdn3d={4 * k:.2f}:{3 * k:.2f}:0:0')
        rate = f'{fps:.6f}'.rstrip('0').rstrip('.')
        vf = ','.join([f'fps={rate}', f'scale={w}:{h}:flags=lanczos', 'setsar=1'] + den + post + ['format=yuv420p'])
        cmd = [_ffmpeg(), '-hide_banner', '-v', 'error', '-y', '-ss', f'{a:.4f}', '-t', f'{dur:.4f}', '-i', str(src),
               '-vf', vf, '-c:v', 'libx264', '-crf', str(s['crf']), '-preset', s['preset']]
        cmd += (['-c:a', 'aac', '-b:a', '256k', '-ar', '48000'] if has_audio else ['-an'])
        _run(cmd + ['-movflags', '+faststart', str(out)], f'night fix ({engine})')
    info['filters_after_denoise'] = ','.join(post) or None
    return engine, info


def _shake_fix(src, a, dur, fps, w, h, s, out, work):
    engine = resolve_engine('shake', s)
    rate = f'{fps:.6f}'.rstrip('0').rstrip('.')
    base = f'fps={rate},scale={w}:{h}:flags=lanczos,setsar=1'
    has_audio = bool(probe(src).get('audio'))
    tail = ['-c:v', 'libx264', '-crf', str(s['crf']), '-preset', s['preset'], '-pix_fmt', 'yuv420p']
    tail += (['-c:a', 'aac', '-b:a', '256k', '-ar', '48000'] if has_audio else ['-an'])
    sharpen = f",unsharp=5:5:{float(s['sharpen']):g}:3:3:{float(s['sharpen']) / 2:g}" if float(s['sharpen']) > 0 else ''
    if engine == 'vidstab':
        ff = str(VIDSTAB_FFMPEG)
        det = (f"vidstabdetect=shakiness={int(s['shakiness'])}:accuracy={int(s['accuracy'])}:stepsize={int(s['stepsize'])}"
               f":result=transforms.trf")
        _run([ff, '-hide_banner', '-v', 'error', '-y', '-ss', f'{a:.4f}', '-t', f'{dur:.4f}', '-i', str(src), '-vf',
              f'{base},{det}', '-f', 'null', '-'], 'vidstabdetect', cwd=str(work))
        tr = (f"vidstabtransform=input=transforms.trf:smoothing={int(s['smoothing'])}:optzoom={int(s['optzoom'])}"
              f":zoom={float(s['zoom']):g}:maxshift={int(s['maxshift'])}:maxangle={float(s['maxangle']):g}"
              f":crop={s['crop']}:tripod={1 if s['tripod'] else 0}:interpol=bicubic")
        _run([ff, '-hide_banner', '-v', 'error', '-y', '-ss', f'{a:.4f}', '-t', f'{dur:.4f}', '-i', str(src), '-vf',
              f'{base},{tr}{sharpen},format=yuv420p', *tail, '-movflags', '+faststart', str(out)], 'vidstabtransform',
             cwd=str(work))
    else:
        rx = int(s['deshake_rx'])
        _run([_ffmpeg(), '-hide_banner', '-v', 'error', '-y', '-ss', f'{a:.4f}', '-t', f'{dur:.4f}', '-i', str(src),
              '-vf', f'{base},deshake=rx={rx}:ry={rx}:edge=mirror{sharpen},format=yuv420p', *tail, '-movflags',
              '+faststart', str(out)], 'deshake')
    return engine, {}


def focus_path(src, a, dur, fps, s, info):
    """[(source s, x, y, source)] per output frame (0-1 of the source frame) for a punch-in."""
    import letitedit.timeline.formats as formats
    fset = {**formats.REFRAME_DEFAULTS, 'min_score': s['min_score']}
    focus = s['focus']
    order = ['given', 'track', 'action', 'centre'] if focus == 'auto' else \
        ['given'] if isinstance(focus, (list, tuple)) else [str(focus)]
    given = focus if isinstance(focus, (list, tuple)) else None
    runs = formats._track_runs(str(src), fset) if 'track' in order else []
    spans = formats._action_spans(str(src), fset) if 'action' in order else None
    n = max(1, int(round(dur * fps)))
    pts = []
    for i in range(n):
        t = a + (i + 0.5) / fps
        got = None
        for o in order:
            if o == 'given' and given is not None:
                if len(given) == 2 and not isinstance(given[0], (list, tuple)):
                    got = (float(given[0]), float(given[1]), 'given')
                else:
                    keys = [[float(k[0]), k[1], k[2]] for k in given]
                    x, y = formats._given_point(keys, t)
                    got = (x, y, 'given')
            elif o == 'track' and runs:
                tp = formats._track_point(runs, t, s['min_score'], 0.5)
                if tp:
                    got = (tp[0], tp[1], 'track')
            elif o == 'action' and spans:
                sp = next((sp for sp in spans if sp[0] <= t <= sp[1]), None)
                if sp:
                    got = (sp[2], sp[3], 'action')
            elif o in ('centre', 'center'):
                got = (0.5, 0.5, 'centre')
            if got:
                break
        pts.append((t,) + (got or (0.5, 0.5, 'centre')))
    win = max(1, int(round(float(s['smooth_s']) * fps)))
    xs = formats._deadzone(formats._smooth([p[1] for p in pts], win), float(s['deadzone']))
    ys = formats._deadzone(formats._smooth([p[2] for p in pts], win), float(s['deadzone']))
    return [(p[0], x, y, p[3]) for p, x, y in zip(pts, xs, ys)]


def _crop_box(cx, cy, W, H, ow, oh, zoom):
    k = max(ow / W, oh / H) * float(zoom)
    cw, ch = min(W, ow / k), min(H, oh / k)
    x = min(max(0.0, cx * W - cw / 2), W - cw)
    y = min(max(0.0, cy * H - ch / 2), H - ch)
    return [round(x, 2), round(y, 2), round(cw, 2), round(ch, 2)]


def _punch(src, a, dur, fps, ow, oh, s, out, info, progress):
    W, H = _even(info['width']), _even(info['height'])
    path = focus_path(src, a, dur, fps, s, info)
    boxes = [_crop_box(x, y, W, H, ow, oh, s['zoom']) for _, x, y, _ in path]
    factor = ow / boxes[0][2]
    engine = resolve_engine('punch', s, crop_factor=factor)
    r = _worker({'op': 'frames', 'ffmpeg': _ffmpeg(), 'src': str(src), 'start': a, 'dur': dur, 'fps': fps,
                 'in_w': W, 'in_h': H, 'out_w': ow, 'out_h': oh, 'model': engine, 'boxes': boxes, 'tile': int(s['tile']),
                 'half': bool(s['half']), 'audio': bool(info.get('audio')), 'out': str(out), 'crf': s['crf'],
                 'preset': s['preset']}, progress, need_mb=1500)
    used = {}
    for p in path:
        used[p[3]] = used.get(p[3], 0) + 1
    return engine, {'crop_px': [round(boxes[0][2]), round(boxes[0][3])], 'upscale_factor': round(factor, 3),
                    'focus_sources': {k: round(v / len(path), 3) for k, v in used.items()},
                    'focus_first': [round(path[0][1], 3), round(path[0][2], 3)],
                    'focus_last': [round(path[-1][1], 3), round(path[-1][2], 3)], 'model': r,
                    '_boxes': boxes, '_path': path}


def _voice(src, a, dur, s, out, work, progress):
    import letitedit.sound.model_tools as model_tools
    ff = _ffmpeg()
    work = Path(work)
    steps = {}
    if s['separate']:
        if progress:
            progress(0.05, 'separating voice / rest (Demucs)')
        sep = model_tools.separate(str(src), start=a, end=a + dur, parts=['vocals', 'rest'],
                                   model=s['separation_model'])
        voice_in, rest_in = sep['files']['vocals'], sep['files']['rest']
        steps['separate'] = {'model': sep['model'], 'cached': sep['cached'], 'took_s': sep['took_s']}
    else:
        voice_in = str(work / 'mix.wav')
        _run([ff, '-v', 'error', '-y', '-ss', f'{a:.4f}', '-t', f'{dur:.4f}', '-i', str(src), '-vn', '-ac', '2', '-ar',
              '48000', '-c:a', 'pcm_f32le', voice_in], 'decode audio')
        rest_in = None
    v48 = work / 'voice48.wav'
    _run([ff, '-v', 'error', '-y', '-i', voice_in, '-ac', '2', '-ar', '48000', '-c:a', 'pcm_f32le', str(v48)], 'resample')
    cur = v48
    if s['dereverb']:
        if progress:
            progress(0.4, 'dereverb (WPE)')
        dr = work / 'voice_wpe.wav'
        r = _worker({'op': 'wpe', 'in': str(cur), 'out': str(dr), 'taps': s['taps'], 'delay': s['delay'],
                     'iterations': s['iterations']}, None, need_mb=0)
        steps['dereverb'] = r
        cur = dr
    if s['denoise']:
        if progress:
            progress(0.7, 'denoise (DeepFilterNet 3)')
        if not DEEP_FILTER.exists() and not os.environ.get('LETITEDIT_DEEP_FILTER'):
            import letitedit.core.first_use as first_use                        # first use: DeepFilterNet (26 MB)
            first_use.need(models=['deepfilternet'], feature='voice clean-up (DeepFilterNet)')
        if not DEEP_FILTER.exists():
            raise FileNotFoundError(f'DeepFilterNet not found at {DEEP_FILTER}')
        d16 = work / 'voice_df_in.wav'          # deep-filter reads 16/32-bit PCM
        _run([ff, '-v', 'error', '-y', '-i', str(cur), '-c:a', 'pcm_s16le', str(d16)], 'df input')
        od = work / 'df'
        od.mkdir(exist_ok=True)
        t0 = time.monotonic()
        cmd = [str(DEEP_FILTER), '-D', '-a', str(float(s['atten_lim_db'])), '-o', str(od)]
        if s['post_filter']:
            cmd.append('--pf')
        _run(cmd + [str(d16)], 'DeepFilterNet')
        steps['denoise'] = {'engine': 'deepfilternet3 (deep-filter 0.5.6, CPU)', 'run_s': round(time.monotonic() - t0, 2)}
        cur = od / d16.name
    vg, rg = float(s['voice_gain_db']), float(s['rest_gain_db'])
    voice_out = work / 'voice_enhanced.wav'
    _run([ff, '-v', 'error', '-y', '-i', str(cur), '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', str(voice_out)],
         'voice stem')
    if rest_in and rg > -120:
        rest_out = work / 'rest.wav'
        _run([ff, '-v', 'error', '-y', '-i', rest_in, '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', str(rest_out)],
             'rest stem')
        _run([ff, '-v', 'error', '-y', '-i', str(voice_out), '-i', str(rest_out), '-filter_complex',
              f'[0:a]volume={vg:g}dB[v];[1:a]volume={rg:g}dB[r];[v][r]amix=inputs=2:normalize=0:duration=first,'
              f'alimiter=limit=0.98:level=disabled[a]', '-map', '[a]', '-ar', '48000', '-c:a', 'pcm_s16le', '-t',
              f'{dur:.4f}', str(out)], 'remix')
        stems = {'voice': str(voice_out), 'rest': str(rest_out)}
    else:
        _run([ff, '-v', 'error', '-y', '-i', str(voice_out), '-af', f'volume={vg:g}dB', '-c:a', 'pcm_s16le', '-t',
              f'{dur:.4f}', str(out)], 'voice out')
        stems = {'voice': str(voice_out)}
    for tmp in ('voice48.wav', 'voice_wpe.wav', 'voice_df_in.wav', 'mix.wav'):
        with_suppress(lambda: (work / tmp).unlink())
    if (work / 'df').exists():
        shutil.rmtree(work / 'df', ignore_errors=True)
    return resolve_engine('voice', s), {'steps': steps, 'stems': stems}


def with_suppress(fn):
    try:
        fn()
    except OSError:
        pass


# ------------------------------------------------------------------ run one fix

def _range(info, start, end):
    dur = float(info.get('duration') or 0)
    a = max(0.0, float(start or 0))
    b = float(end) if end is not None else dur
    if dur:
        b = min(b, dur)
    if b <= a:
        raise ValueError(f'empty range {a}-{b} (source is {dur:.3f} s)')
    return round(a, 4), round(b, 4)


def run(source, start=None, end=None, fix='night', settings=None, fps=None, size=None, max_size=None, sheet=True,
        sheet_frames=3, progress=None, prev=None, src_offset=0.0, measure=True):
    """Make (or reuse) the repaired copy of source start-end (source seconds). fix: 'night'|'shake'|'punch'|'voice' or
    {kind, ...settings}; settings: more settings. fps: output frame rate (default: the source's, at most 60). size:
    [w, h] output size; max_size: [w, h] the output fits inside (default: the source's display size). prev / src_offset
    are used by chain() (a fix applied to an earlier fix's output)."""
    t0 = time.monotonic()
    spec = normalise(fix)
    spec.update(settings or {})
    spec = normalise(spec)
    kind = spec['kind']
    s = settings_for(spec)
    src = Path(source)
    if not src.exists():
        raise FileNotFoundError(f'no such file: {source}')
    info = probe(src)
    a, b = _range(info, start, end)
    dur = round(b - a, 4)
    auto = resolve_auto(kind, s, src, a, b)       # before the cache family: it caches on the resolved value
    src_fps = float(info.get('fps') or 30.0)
    fps = float(fps or min(src_fps, 60.0) or 30.0)
    if kind in VIDEO_KINDS and not info.get('width'):
        raise ValueError(f'{src.name} has no picture for the {kind} fix')
    if kind == 'voice' and not info.get('audio'):
        raise ValueError(f'{src.name} has no sound for the voice fix')
    if kind == 'punch':
        w, h = (_even(size[0]), _even(size[1])) if size else (_even(max_size[0]), _even(max_size[1])) if max_size \
            else _work_size(info)
    else:
        w, h = _work_size(info, size, max_size)
    if kind == 'punch':
        W, H = _even(info['width']), _even(info['height'])
        k = max(w / W, h / H) * float(s['zoom'])
        engine = resolve_engine(kind, s, crop_factor=w / min(W, w / k))
    else:
        engine = resolve_engine(kind, s)
    ident = prev or _identity(src)
    fam = _family(ident, kind, s, engine, fps if kind != 'voice' else None, (w, h) if kind != 'voice' else None, None)
    hit = _lookup(fam, a, b)
    if hit:
        hit = dict(hit, cached=True, offset=round(a - hit['start'], 4), took_s=round(time.monotonic() - t0, 2))
        if auto:
            hit['auto_separate'] = auto         # this call's reading, also when the repair was made earlier (or by an explicit setting)
        return hit
    folder = CACHE / fam / f'{a:.3f}_{b:.3f}'
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / ('fixed.wav' if kind == 'voice' else 'fixed.mp4')
    prog = progress or (lambda f, m=None: None)
    before = {}
    if measure:
        prog(0.0, 'measuring before')
        before = measure_audio(src, a, dur) if kind == 'voice' else measure_video(src, a, dur, w, h, fps,
                                                                                   shake=kind in ('shake', 'night'))
    import letitedit.core.render_lock as render_lock
    lock = (render_lock.slot(f'shotcut fix {kind} {src.name}', caller_pids=render_lock.ancestors())
            if dur > float(s['render_lock_over_s']) else _nolock())
    extra = {}
    with lock:
        if kind == 'night':
            engine, extra = _night(src, a, dur, fps, w, h, s, out, before, prog)
        elif kind == 'shake':
            engine, extra = _shake_fix(src, a, dur, fps, w, h, s, out, folder)
        elif kind == 'punch':
            engine, extra = _punch(src, a, dur, fps, w, h, s, out, info, prog)
        else:
            engine, extra = _voice(src, a, dur, s, out, folder, prog)
    boxes, fpath = extra.pop('_boxes', None), extra.pop('_path', None)
    after = {}
    if measure:
        prog(0.95, 'measuring after')
        after = measure_audio(out, 0, dur) if kind == 'voice' else measure_video(out, 0, dur, w, h, fps,
                                                                                 shake=kind in ('shake', 'night'))
        if kind == 'punch' and boxes:
            after['naive_sharpness'] = _naive_sharpness(src, a, dur, w, h, boxes, fps)
    sheet_path = None
    if sheet:
        try:
            sheet_path = _sheet(kind, src, out, a, dur, w, h, fps, sheet_frames, folder, engine, boxes, s)
        except Exception as e:  # noqa: BLE001 - a sheet must not lose the repair
            extra['sheet_error'] = str(e)[:300]
    res = {'file': str(out), 'kind': kind, 'source': str(src), 'start': a, 'end': b, 'offset': 0.0,
           'fps': None if kind == 'voice' else round(fps, 4), 'size': None if kind == 'voice' else [w, h],
           'engine': engine, 'settings': s, 'given': {k: v for k, v in spec.items() if k != 'kind'},
           'measures': {'before': before, 'after': after}, 'sheet': sheet_path, 'took_s': round(time.monotonic() - t0, 2),
           'made': time.strftime('%Y-%m-%d %H:%M:%S'), 'family': fam, 'source_offset': src_offset, **extra}
    if auto:
        res['auto_separate'] = auto
    (folder / 'result.json').write_text(json.dumps(res, indent=1), encoding='utf-8')
    return dict(res, cached=False)


class _nolock:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


def _naive_sharpness(src, a, dur, w, h, boxes, fps, samples=4):
    """Sharpness of the same punch-in done with a plain bicubic resize (what the model is compared with)."""
    import cv2
    import numpy as np
    info = probe(src)
    W, H = _even(info['width']), _even(info['height'])
    vals = []
    for i in range(samples):
        t = dur * (i + 0.5) / samples
        fr = _frames(src, [a + t], W, H)
        if not fr:
            continue
        x, y, cw, ch = (int(round(v)) for v in boxes[min(len(boxes) - 1, int(t * fps))])
        crop = fr[0][y:y + ch, x:x + cw]
        up = cv2.resize(crop, (w, h), interpolation=cv2.INTER_CUBIC)
        vals.append(cv2.Laplacian(_luma(up), cv2.CV_32F).var())
    return round(float(np.median(vals)), 1) if vals else None


def _sheet(kind, src, out, a, dur, w, h, fps, n, folder, engine, boxes, s):
    import numpy as np
    title = f'{Path(src).name} {a:.2f}-{a + dur:.2f}s  fix: {kind}  engine: {engine}'
    path = folder / 'sheet.jpg'
    if kind == 'voice':
        return audio_sheet(_pcm(src, a, dur), _pcm(out, 0, dur), path, title)
    pairs = []
    info = probe(src)
    for i in range(max(1, int(n))):
        t = dur * (i + 0.5) / max(1, int(n))
        aft = _frames(out, [t], w, h)
        if kind == 'punch':
            W, H = _even(info['width']), _even(info['height'])
            full = _frames(src, [a + t], W, H)
            if not full or not aft:
                continue
            x, y, cw, ch = (int(round(v)) for v in boxes[min(len(boxes) - 1, int(t * fps))])
            from PIL import Image, ImageDraw
            im = Image.fromarray(full[0])
            naive = np.asarray(im.crop((x, y, x + cw, y + ch)).resize((w, h), Image.BICUBIC))
            d = ImageDraw.Draw(im)
            d.rectangle([x, y, x + cw, y + ch], outline=(255, 210, 0), width=max(3, W // 300))
            pairs.append((a + t, np.asarray(im), naive, 'source + crop', 'plain resize'))
            pairs.append((a + t, naive, aft[0], 'plain resize', f'after ({engine})'))
        else:
            bef = _frames(src, [a + t], w, h)
            if bef and aft:
                pairs.append((a + t, bef[0], aft[0], 'before', f'after ({engine})'))
                if i == 0:      # a 1:1 detail of the middle of the frame (noise and sharpness show at this scale)
                    cw, ch = min(w, 480), min(h, 360)
                    x0, y0 = (w - cw) // 2, (h - ch) // 2
                    pairs.append((a + t, bef[0][y0:y0 + ch, x0:x0 + cw], aft[0][y0:y0 + ch, x0:x0 + cw],
                                  'before 1:1 detail', f'after 1:1 detail'))
    return frame_sheet(pairs, path, title)


# ------------------------------------------------------------------ chain (clip effects)

def chain(clip, start, end, fixes, fps, max_w=None, max_h=None, progress=None):
    """Apply fixes in order to clip start-end (source s). Video fixes feed each other (several are cached as one
    repair of the source range); the voice fix works on the source's sound. Returns {'video': path|None,
    'audio': path|None, 'offset_video', 'offset_audio' (s into those files), 'steps': [...]}."""
    src, a, b = str(clip), float(start), float(end)
    info = probe(src)
    fps = min(float(fps or 30.0), float(info.get('fps') or fps or 30.0))
    max_size = [max_w, max_h] if max_w and max_h else None
    specs = [normalise(f) for f in fixes]
    vfix = [f for f in specs if f['kind'] != 'voice']
    afix = [f for f in specs if f['kind'] == 'voice']
    out = {'video': None, 'audio': None, 'offset_video': 0.0, 'offset_audio': 0.0, 'steps': []}

    def step(r):
        out['steps'].append({k: r.get(k) for k in ('kind', 'engine', 'file', 'cached', 'took_s', 'sheet', 'measures',
                                                   'auto_separate')})

    if len(vfix) == 1:
        f = vfix[0]
        r = run(src, a, b, f, fps=fps, size=max_size if f['kind'] == 'punch' else None, max_size=max_size,
                progress=progress)
        out.update(video=r['file'], offset_video=r['offset'])
        step(r)
    elif vfix:
        fam = _family(_identity(src), 'chain', [settings_for(f) | {'kind': f['kind']} for f in vfix], None, fps,
                      max_size, None)
        hit = _lookup(fam, a, b)
        if hit:
            out.update(video=hit['file'], offset_video=round(a - hit['start'], 4))
            out['steps'] += hit.get('steps', [])
        else:
            cur, ca, cb = src, a, b
            for f in vfix:
                r = run(cur, ca, cb, f, fps=fps, size=max_size if f['kind'] == 'punch' else None, max_size=max_size,
                        progress=progress, sheet=False)
                cur, ca, cb = r['file'], r['offset'], r['offset'] + (b - a)
                step(r)
            folder = CACHE / fam / f'{a:.3f}_{b:.3f}'
            folder.mkdir(parents=True, exist_ok=True)
            final = folder / 'fixed.mp4'
            shutil.copyfile(cur, final)
            res = {'file': str(final), 'kind': 'chain', 'source': src, 'start': a, 'end': b, 'fps': fps,
                   'engine': ' -> '.join(f"{s_['kind']}:{s_['engine']}" for s_ in out['steps']),
                   'steps': out['steps'], 'made': time.strftime('%Y-%m-%d %H:%M:%S'), 'family': fam}
            (folder / 'result.json').write_text(json.dumps(res, indent=1), encoding='utf-8')
            out.update(video=str(final), offset_video=0.0)
    for f in afix:
        r = run(src, a, b, f, progress=progress)
        out.update(audio=r['file'], offset_audio=r['offset'])
        step(r)
    return out


def cached(source=None, limit=100):
    """Cached repairs, newest first: [{'file', 'kind', 'source', 'start', 'end', 'engine', 'made', 'sheet', ...}]."""
    rows = []
    if CACHE.is_dir():
        for res in CACHE.glob('*/*/result.json'):
            try:
                r = json.loads(res.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                continue
            if source and Path(r['source']).resolve() != Path(source).resolve():
                continue
            rows.append({k: r.get(k) for k in ('file', 'kind', 'source', 'start', 'end', 'engine', 'made', 'sheet',
                                                'took_s', 'size', 'fps')})
    rows.sort(key=lambda r: r.get('made') or '', reverse=True)
    return rows[:limit]
