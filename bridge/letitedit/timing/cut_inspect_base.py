"""The settings and thresholds, small helpers, the per-thread OpenCV objects and decoding.

Part of `cut_inspect` (letitedit/timing/cut_inspect.py), which imports every name here back,
so `cut_inspect.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
from pathlib import Path
import numpy as np
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)
SCHEMA_VERSION = 1
CODE_VERSION = 9               # bump when a measure changes (part of the per-cut cache key)
VIEW = 'cuts'
SUMMARY = ('cut inspector: the frames around each cut at the full rate with motion and attention drawn; per cut the '
           'action phase, motion across the cut, eye-trace jump, screen direction, jump cut / shot-size change, '
           'sound across the join (joins), and a smooth / noticeable / jarring summary with the numbers behind it')
CACHE = Path(os.environ.get('LETITEDIT_CACHE', _SAI_ROOT + '\\cache')) / 'timing-cuts'
APP = Path(os.environ.get('LETITEDIT_APP', _SAI_ROOT + '\\app'))
MELT, FFMPEG = APP / 'melt.exe', APP / 'ffmpeg.exe'
YUNET = Path(os.environ.get('LETITEDIT_VFX', _SAI_ROOT + '\\vfx')) / 'models' / 'yunet_2023mar.onnx'
SFACE = YUNET.with_name('face_recognition_sface_2021dec.onnx')
THRESHOLDS_FILE = _paths.BRIDGE.joinpath('timing_thresholds.json')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# ------------------------------------------------------------------ settings and thresholds

DEFAULTS = {
    'before': 6,              # strip: frames shown before the cut (full rate)
    'after': 6,               # ... and after it
    'context_s': 1.0,         # rhythm window each side of the cut (clipped to the shot)
    'motion_window_s': 0.3,   # direction and pre/post-cut motion: this much of each side next to the cut
    'att_a_frames': 3,        # A's attention point: median of its last frames
    'att_b_s': 0.3,           # B's attention point: median over its first 0.3 s (the first saccade after a cut)
    'decode_px': 384,         # long side of the decoded frames (faces, strips)
    'flow_px': 256,           # long side for optical flow and the maps (thresholds in diag/s are for this size)
    'max_cuts': 80,           # cuts measured per call (the rest are listed as unchecked)
    'workers': 1,             # cuts measured in parallel (1: one ffmpeg decode at a time; the PC's load rule)
    'images': 'auto',         # strips returned: 'auto' (overview + the worst cuts), 'all', or a number
    'overview': True,
    'kinds': ['cut', 'punch', 'dissolve', 'fade', 'wipe', 'gap', 'given'],
    'preview_px': 480,        # long side of the melt preview render (project without the timing store)
    'detect': None,           # shots.detect settings for a video without the timing store
}

# 'cuts.' keys of bridge/timing_thresholds.json: (default, unit, about). The file wins for any key it has; the
# defaults are used for a key missing there. Every verdict finding names the key and value it used.
THRESHOLD_SPEC = {
    'cuts.move_speed': (0.06, 'diag/s', 'a pixel moves when its camera-compensated flow is at least this (frame '
                                        'diagonals per second, flow at 256 px): moving share, motion arrows'),
    'cuts.action_speed': (0.30, 'diag/s', 'a frame has action when its subject speed (median speed of its most '
                                          'moving region, camera removed) is at least this (a talking head moves '
                                          '~0.15-0.25; 85th percentile of the last frames before 398 professional '
                                          'cuts)'),
    'cuts.frame_wide_share': (0.40, 'share', 'motion over this share of the frame is frame-wide (camera parallax or a '
                                             'frame-filling subject), not a local action: no direction, no masking'),
    'cuts.post_motion_masks': (0.30, 'diag/s', "local motion this fast over B's first 0.3 s lowers eye-trace findings "
                                               'one step (Smith & Martin-Portugues 2017)'),
    'cuts.eye_jump_noticeable': (0.25, 'frame diagonals', 'the attention point jumps at least this across the cut: '
                                                          'noticeable (75th percentile of 398 professional cuts: '
                                                          'Tears of Steel, Sintel, Big Buck Bunny, Caminandes)'),
    'cuts.eye_jump_jarring': (0.58, 'frame diagonals', '... at least this: jarring (their 99th percentile)'),
    'cuts.direction_min_coherence': (0.45, '0-1', 'local motion has a direction when its vectors agree this much'),
    'cuts.direction_reversed_deg': (135.0, 'degrees', 'directions of local motion this far apart across the cut: '
                                                      'screen direction reverses (noticeable)'),
    'cuts.direction_same_deg': (60.0, 'degrees', 'directions this close: the motion keeps its direction'),
    'cuts.pan_speed': (0.08, 'diag/s', 'the picture shifts at least this fast: the camera pans or tilts'),
    'cuts.jump_framing_sim': (0.55, 'NCC', "A's last and B's first frame match at least this after camera "
                                           'compensation: same framing (jump cut unless the size changes)'),
    'cuts.jump_layout_sim': (0.85, 'NCC', '... or their 1/8-size layouts match at least this'),
    'cuts.jump_max_cells': (0.5, 'share', '... and at most this share of the 4x4 cells changed their local texture '
                                          '(a shared gradient or vignette alone is not the same framing)'),
    'cuts.same_size_ratio': (1.25, 'ratio', 'face heights within this ratio: the same shot size'),
    'cuts.punch_zoom': (1.12, 'x', 'the same picture reframed by at least this zoom: a punch-in'),
    'cuts.luma_jump_noticeable': (40.0, '0-255', 'mean brightness changes at least this across the cut: noticeable '
                                                 '(75th percentile of 398 professional cuts)'),
    'cuts.luma_jump_jarring': (100.0, '0-255', '... at least this: jarring, a flash (their 99th percentile)'),
    'cuts.blank_flat_share': (0.85, 'share', 'a frame with at least this share of its pixels within 2 levels of its '
                                             'median is blank (black, white or flat, a caption on it allowed)'),
    'cuts.blur_mask_ratio': (0.35, 'ratio', "A's last frames at most this sharp (Laplacian variance) relative to the "
                                            'sharpest frame of its window while the frame moves: the cut hides in '
                                            'motion blur (a whip), eye-trace findings one step lower'),
    'cuts.scene_hist': (0.35, '0-1', 'colour histogram change at least this with unrelated framing: a new place or '
                                     'subject (reported, not scored)'),
    'cuts.flash_frames': (3, 'frames', 'a shot this short or shorter is a flash frame (jarring)'),
    'cuts.short_shot_frames': (8, 'frames', 'a shot this short or shorter is noticeable'),
    'cuts.gap_jarring_frames': (6, 'frames', 'empty (black) frames between two shots: fewer than this read as a '
                                             'glitch (jarring), more as a deliberate pause (noticeable)'),
    'cuts.many_noticeable': (3, 'findings', 'this many noticeable findings at one cut make it jarring'),
    'cuts.face_min_score': (0.7, '0-1', 'YuNet face score threshold'),
    'cuts.face_attention_min_h': (0.05, 'share of frame height', 'a face this tall or taller is the attention point'),
    'cuts.same_person_cos': (0.363, 'cosine', 'SFace features this similar: the same person (OpenCV threshold)'),
    'cuts.overlay_diff': (6.0, '0-255', 'textured pixels this close on both sides of a cut that changes the picture: a '
                                        'static overlay (caption, logo), masked out of the attention point'),
    'cuts.sound_level_jump_db': (6.0, 'dB', 'used only when the joins view reports a level jump without its own flag'),
}
THRESHOLD_DEFAULTS = {k: v[0] for k, v in THRESHOLD_SPEC.items()}

_THR_CACHE = {'mtime': None, 'values': None}


def _read_threshold_file():
    try:
        st = THRESHOLDS_FILE.stat()
    except OSError:
        return {}
    if _THR_CACHE['mtime'] == st.st_mtime_ns and _THR_CACHE['values'] is not None:
        return _THR_CACHE['values']
    try:
        data = json.loads(THRESHOLDS_FILE.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    flat = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if k == 'cuts' and isinstance(v, dict):      # nested {'cuts': {...}} also read
                for k2, v2 in v.items():
                    flat['cuts.' + k2] = v2
            else:
                flat[k] = v
    out = {}
    for k, v in flat.items():
        if isinstance(v, dict) and 'value' in v:
            v = v['value']
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = v
    _THR_CACHE.update(mtime=st.st_mtime_ns, values=out)
    return out


def thresholds(overrides=None):
    """The 'cuts.' thresholds in use: timing_thresholds.json, defaults for missing keys, then `overrides`."""
    got = _read_threshold_file()
    out = {k: got.get(k, v) for k, v in THRESHOLD_DEFAULTS.items()}
    for k, v in (overrides or {}).items():
        kk = k if k.startswith('cuts.') else 'cuts.' + k
        if kk in THRESHOLD_DEFAULTS and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[kk] = v
    return out


def ensure_thresholds_file(path=None):
    """Add the missing 'cuts.' keys to timing_thresholds.json as {value, unit, about} lines, inserted as one block
    before the closing brace: every other key, value and line of the file stays as it is. Returns the keys added."""
    p = Path(path) if path else THRESHOLDS_FILE
    lock = p.with_name(p.name + '.lock')
    for _ in range(100):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 30:
                    lock.unlink()
            except OSError:
                pass
            time.sleep(0.1)
    try:
        try:
            text = p.read_text(encoding='utf-8-sig')
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError(f'{p} is not a JSON object')
        except FileNotFoundError:
            text, data = '{\n}\n', {}
        have = set(data) | {'cuts.' + k for k in (data.get('cuts') or {})} if isinstance(data.get('cuts'), dict) \
            else set(data)
        missing = [k for k in THRESHOLD_SPEC if k not in have]
        if not missing:
            return []
        lines = [f' {json.dumps(k)}: {json.dumps({"value": THRESHOLD_SPEC[k][0], "unit": THRESHOLD_SPEC[k][1], "about": THRESHOLD_SPEC[k][2]})}'
                 for k in missing]
        end = text.rstrip().rfind('}')
        head = text[:end].rstrip()
        sep = ',' if data else ''
        new = head + sep + '\n\n' + ',\n'.join(lines) + '\n}\n'
        json.loads(new)                               # still valid JSON, or nothing is written
        tmp = p.with_name(p.name + f'.{os.getpid()}.tmp')
        tmp.write_text(new, encoding='utf-8')
        os.replace(tmp, p)
        return missing
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _settings(options):
    st = dict(DEFAULTS)
    for k, v in (options or {}).items():
        if k in DEFAULTS and v is not None:
            st[k] = v
    return st


# ------------------------------------------------------------------ small helpers

def _h(obj, n=12):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:n]


def _r(x, n=3):
    if x is None:
        return None
    try:
        if isinstance(x, (bool, np.bool_)):
            return bool(x)
        x = float(x)
    except (TypeError, ValueError):
        return x
    if not math.isfinite(x):
        return None
    return round(x, n)


def _clock(t):
    t = max(0.0, float(t))
    return f'{int(t // 60)}:{t % 60:05.2f}'


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating,)):
        return _r(float(o), 4)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, float):
        return _r(o, 4)
    if isinstance(o, Path):
        return str(o)
    return o


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(_jsonable(data), indent=1), encoding='utf-8')
    os.replace(tmp, path)


def _angle_diff(a, b):
    if a is None or b is None:
        return None
    return abs((float(b) - float(a) + 180.0) % 360.0 - 180.0)


def _circ_mean(angles_deg, weights):
    if not angles_deg:
        return None, 0.0
    a = np.radians(np.asarray(angles_deg, float))
    w = np.asarray(weights, float)
    if w.sum() <= 0:
        return None, 0.0
    x, y = float((w * np.cos(a)).sum()), float((w * np.sin(a)).sum())
    r = math.hypot(x, y) / float(w.sum())
    return (math.degrees(math.atan2(y, x)), r)


def _dir_word(deg):
    if deg is None:
        return 'none'
    d = (deg + 360.0) % 360.0
    names = ['right', 'up-right', 'up', 'up-left', 'left', 'down-left', 'down', 'down-right']
    return names[int(((d + 22.5) % 360) // 45)]


# ------------------------------------------------------------------ per-thread OpenCV objects

_TL = threading.local()


CV_THREADS = int(os.environ.get('LETITEDIT_CV_THREADS', '4'))   # the PC's load rule: at most 4 threads per tool


def _cv2():
    import cv2
    if not getattr(_TL, 'quiet', False):
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except AttributeError:
            pass
        try:
            cv2.setNumThreads(CV_THREADS)
        except Exception:  # noqa: BLE001
            pass
        _TL.quiet = True
    return cv2


def _dis():
    cv2 = _cv2()
    d = getattr(_TL, 'dis', None)
    if d is None:
        d = _TL.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    return d


def _saliency_obj():
    cv2 = _cv2()
    s = getattr(_TL, 'sal', None)
    if s is None:
        try:
            s = _TL.sal = cv2.saliency.StaticSaliencySpectralResidual_create()
        except AttributeError:
            s = _TL.sal = False
    return s


def faces_available():
    cv2 = _cv2()
    return YUNET.exists() and hasattr(cv2, 'FaceDetectorYN')


def _face_detector(size, score):
    cv2 = _cv2()
    dets = getattr(_TL, 'faces', None)
    if dets is None:
        dets = _TL.faces = {}
    key = (size, round(float(score), 3))
    d = dets.get(key)
    if d is None:
        d = dets[key] = cv2.FaceDetectorYN.create(str(YUNET), '', size, float(score), 0.3, 50)
    return d


def _face_recognizer():
    cv2 = _cv2()
    r = getattr(_TL, 'sface', None)
    if r is None:
        try:
            r = _TL.sface = cv2.FaceRecognizerSF.create(str(SFACE), '') if SFACE.exists() else False
        except Exception:  # noqa: BLE001 - recognizer unavailable
            r = _TL.sface = False
    return r


# ------------------------------------------------------------------ decoding

def probe(path):
    import letitedit.footage.shots as shots
    return shots.probe(path)


def _sizes(w, h, decode_px, flow_px):
    def fit(px):
        s = float(px) / max(w, h)
        return max(16, int(round(w * s / 2)) * 2), max(16, int(round(h * s / 2)) * 2)
    return fit(decode_px), fit(flow_px)


def decode_frames(video, f0, f1, size, info=None):
    """{frame index: BGR uint8 frame at size (w, h)} for frames f0 <= f < f1 of `video` (exact frame indices: the
    file's frame grid at its nominal rate: round((pts - start_time) * fps), pts as stored in the file)."""
    import letitedit.footage.shots as shots
    info = info or shots.probe(video)
    fps = float(info['fps'])
    st0 = float(info.get('start_time') or 0.0)
    f0 = max(0, int(f0))
    f1 = int(f1)
    if f1 <= f0:
        return {}
    out = {}
    for pts, img in _decode_raw(video, max(0.0, st0 + (f0 - 1.0) / fps), f1 - f0 + 4, size):
        fi = int(math.floor((pts - st0) * fps + 0.5))
        if f0 <= fi < f1 and fi not in out:
            out[fi] = img
    missing = [f for f in range(f0, f1) if f not in out]
    for f in missing:                          # a variable-rate file: a gap takes the frame before it (as the store)
        prev = [g for g in range(f - 1, f0 - 1, -1) if g in out]
        if prev:
            out[f] = out[prev[0]]
    return out


_SHOWINFO = re.compile(r'\bn:\s*(\d+)\b.*?\bpts_time:\s*([-+0-9.eE]+|nan)')


def _decode_raw(video, start_s, nframes, size, threads=2):
    """(pts_time as stored in the file, BGR frame at size) for up to nframes frames from start_s (seconds of the
    file's own clock). -copyts keeps every frame's own time stamp: a seek otherwise shifts them by the seek position,
    truncated to the stream's time base (a 1/24 time base then puts every frame half a frame early)."""
    w, h = size
    args = [str(FFMPEG), '-hide_banner', '-nostdin', '-v', 'info', '-threads', str(int(threads)), '-copyts']
    if start_s > 0:
        args += ['-ss', f'{start_s:.6f}']
    args += ['-i', str(video), '-an', '-sn', '-dn', '-vf', f'showinfo,scale={w}:{h}:flags=area', '-frames:v',
             str(int(nframes)), '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         creationflags=NO_WINDOW)
    times, cond, done = [], threading.Condition(), [False]

    def read_err():
        for raw in p.stderr:
            line = raw.decode('utf-8', 'replace')
            if 'Parsed_showinfo' in line and 'pts_time' in line:
                m = _SHOWINFO.search(line)
                if m:
                    with cond:
                        try:
                            times.append(float(m.group(2)))
                        except ValueError:
                            times.append(float('nan'))
                        cond.notify_all()
        with cond:
            done[0] = True
            cond.notify_all()
    th = threading.Thread(target=read_err, daemon=True)
    th.start()
    size_b = w * h * 3
    i = 0
    try:
        while True:
            buf = p.stdout.read(size_b)
            if not buf or len(buf) < size_b:
                break
            with cond:
                while len(times) <= i and not done[0]:
                    cond.wait(5)
                t = times[i] if len(times) > i else float('nan')
            i += 1
            if t != t:
                continue
            yield t, np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()
    finally:
        try:
            p.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        if p.poll() is None:
            p.kill()
        p.wait()
        th.join(timeout=5)


def decode_at_times(video, times, size, info=None):
    """BGR frames of `video` nearest to each source time in `times` (seconds from the file's start). For frames of
    a source clip on another frame grid (the roll test)."""
    import letitedit.footage.shots as shots
    info = info or shots.probe(video)
    fps = float(info['fps'])
    st0 = float(info.get('start_time') or 0.0)
    times = [float(t) for t in times]
    if not times:
        return []
    lo, hi = min(times), max(times)
    n = int(math.ceil((hi - lo) * fps)) + 6
    got_t, got_f = [], []
    for pts, img in _decode_raw(video, max(0.0, st0 + lo - 2.0 / fps), n, size):
        got_t.append(pts - st0)
        got_f.append(img)
    if not got_t:
        return [None] * len(times)
    arr = np.asarray(got_t)
    out = []
    for t in times:
        k = int(np.argmin(np.abs(arr - t)))
        out.append(got_f[k] if abs(arr[k] - t) <= 1.0 / fps else None)
    return out
