"""What was filmed: the kind of video a set of clips is, worked out on this PC in a few seconds, for New video's Style tabs.

    detect(paths, budget_s=4.0)   -> {style, kind, label, why, sure, looked_at, of, seconds, complete, clips}
    python what_was_filmed.py <folder or file> [<file> ...] [--budget 4]   one JSON line on stdout

`paths` is a folder (its media files, as New video lists them) or the chosen files. The answer's `style` is a Style
id from looks\\styles.json, or "all" when the clips don't say clearly:

    talking-head   one person talking to the camera (a face in most frames, talk most of the time)
    conversation   two or more people talking (two or more faces in many frames, talk most of the time)
    activity       action or activity: doing, making, going somewhere, an event; little talk, or talk over the work
                   with no face to the camera
    screen         a screen recording (flat, sharp, text-like pictures, or the file's name says so)

What it measures, per clip, from at most about 30 s of sound and three frames (more clips than `MAX_CLIPS` are
sampled evenly across the list): the share of the time someone talks (the transcript already made for the clip when
there is one, else the cached voice detector's result, else the voice detector on that window: Silero, from
faster-whisper), and on each frame the faces (OpenCV YuNet, the model the other face checks use) and how flat and
sharp the picture is. Each clip's result is cached by path, size and modification time, so a second look is instant.
Nothing is uploaded and no AI runs. When the face model or the voice detector isn't on this PC, what they would have
said counts as unknown and the answer leans to "all".

The budget is soft: clips not started when it runs out are left out (`complete: false`), and the answer is made from
the clips measured.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)

ROOT = Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT))
FFMPEG = ROOT / 'app' / 'ffmpeg.exe'
CACHE = Path(os.environ.get('LETITEDIT_CACHE', str(ROOT / 'cache'))) / 'what-was-filmed'
YUNET = Path(os.environ.get('LETITEDIT_VFX', str(ROOT / 'vfx'))) / 'models' / 'yunet_2023mar.onnx'
LOOKS = Path(os.environ.get('LETITEDIT_LOOKS') or (ROOT / 'looks'))
VERSION = 2                     # bump when a measure changes, so old cached clips are measured again

VIDEO = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.webm', '.mxf'}
AUDIO = {'.wav', '.mp3', '.m4a', '.flac', '.aac', '.ogg'}
PHOTO = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.bmp'}
MAX_CLIPS = 8                   # clips measured from a bigger folder, spread evenly over it
WINDOW_S = 30.0                 # seconds of sound measured per clip (from its middle)
FRAMES = 3                      # frames looked at per clip
TALK = 0.35                     # a clip "talks" when someone talks this share of the time or more
LITTLE_TALK = 0.2               # a set of clips has little talk below this share of its time
ANGLES_WIDE = 0.25               # several angles of one talk: talking clips with two faces in most frames carry this share of the talk
FACE_MIN = 0.06                 # a face counts when its box is at least this share of the frame's height tall
SCREEN_FLAT = 0.6               # a screen-like frame: this share of its 8x8 blocks are flat colour (camera footage
SCREEN_EDGES = 0.02             # measured here stays under 0.6), with at least this share of sharp edge pixels
SCREEN_WORDS = ('screen', 'recording', 'capture', 'screencast', 'obs ', 'obs_', 'loom', 'zoom meeting')

LABELS = {'talking-head': 'One person talking to the camera', 'conversation': 'Two or more people talking',
          'activity': 'Action or activity', 'screen': 'A screen recording', 'all': 'Not sure'}
KIND = {'talking-head': 'one-person-talking', 'conversation': 'people-talking', 'activity': 'activity',
        'screen': 'screen-recording', 'all': 'unsure'}

_detector_lock = threading.Lock()
_vad_lock = threading.Lock()


# ---------------------------------------------------------------------------- which files

def media_files(paths) -> list[str]:
    """The media files New video would list: a folder's own files (not its sub-folders), or the files given."""
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            try:
                entries = sorted((e for e in p.iterdir() if e.is_file()), key=lambda e: e.name.casefold())
            except OSError:
                continue
            out += [str(e) for e in entries if e.suffix.lower() in VIDEO | AUDIO | PHOTO]
        elif p.is_file() and p.suffix.lower() in VIDEO | AUDIO | PHOTO:
            out.append(str(p))
    return out


def _spread(items, n):
    if len(items) <= n:
        return list(items)
    step = len(items) / n
    return [items[int(step * k + step / 2)] for k in range(n)]


# ---------------------------------------------------------------------------- one clip

def _key(path):
    st = os.stat(path)
    return hashlib.sha256(f'{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}|{VERSION}'.encode()).hexdigest()[:20]


def _duration(cap):
    try:
        import cv2
        n, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS)
        return float(n / fps) if n > 0 and fps > 0 else None
    except Exception:  # noqa: BLE001
        return None


def _probe_duration(path):
    probe = FFMPEG.with_name('ffprobe.exe')
    try:
        r = subprocess.run([str(probe), '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                           capture_output=True, text=True, timeout=5)
        return float(r.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _speech_from_cache(path, duration):
    """(share, how) from what letitedit already measured for this file, or (None, None)."""
    try:
        import letitedit.footage.speech as speech
        ws = speech.cached_words(path)
    except Exception:  # noqa: BLE001
        ws = None
    if ws and duration:
        talk = sum(max(0.0, min(float(w['e']), float(w['s']) + 1.5) - float(w['s'])) for w in ws)
        span = duration
        try:        # a long file transcribed in 5-minute windows, not all of them yet: the share of what was transcribed
            if speech._cached(speech._identity(path)) is None:
                span = min(duration, 300.0 * max(1, -(-max(float(w['e']) for w in ws) // 300)))
        except Exception:  # noqa: BLE001
            pass
        return min(1.0, talk / span), 'transcript'
    try:
        import letitedit.sound.music as music
        f = Path(music.CACHE) / 'voice' / f'{music._identity(path)}.json'
        if f.is_file() and duration:
            voice = json.loads(f.read_text(encoding='utf-8-sig')).get('voice') or []
            return min(1.0, sum(max(0.0, b - a) for a, b in voice) / duration), 'voice detector (cached)'
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _speech_window(path, duration):
    """(share, how) from the voice detector on up to WINDOW_S seconds from the clip's middle."""
    import numpy as np
    start = max(0.0, (duration or 0) / 2 - WINDOW_S / 2) if duration else 0.0
    cmd = [str(FFMPEG), '-v', 'error', '-ss', f'{start:.2f}', '-t', f'{WINDOW_S:.0f}', '-i', str(path), '-vn',
           '-ac', '1', '-ar', '16000', '-f', 'f32le', '-']
    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None, 'sound unreadable'
    audio = np.frombuffer(raw[:len(raw) - len(raw) % 4], dtype=np.float32)
    if audio.size < 16000 * 0.5:
        return 0.0, 'no sound'
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except Exception:  # noqa: BLE001
        return None, 'voice detector not on this PC'
    opts = VadOptions(threshold=0.5, min_speech_duration_ms=250, min_silence_duration_ms=500, speech_pad_ms=120)
    with _vad_lock:     # one model session, shared by the threads
        spans = get_speech_timestamps(audio, opts)
    talk = sum(s['end'] - s['start'] for s in spans) / 16000
    return min(1.0, talk / (audio.size / 16000)), 'voice detector'


def _frames(path, duration):
    """Up to FRAMES frames (BGR, at most 640 wide) spread over the clip."""
    try:
        import cv2
    except ImportError:
        return []
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []
    duration = duration or _duration(cap)
    out = []
    try:
        for k in range(FRAMES):
            if duration:
                cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * duration * (k + 0.5) / FRAMES)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            if w > 640:
                frame = cv2.resize(frame, (640, round(h * 640 / w)))
            out.append(frame)
    finally:
        cap.release()
    return out


_detectors = {}


def _faces(frame):
    """Faces at least FACE_MIN of the frame's height tall, or None when the face model isn't on this PC."""
    import cv2
    if not YUNET.is_file():
        return None
    h, w = frame.shape[:2]
    with _detector_lock:
        det = _detectors.get((w, h))
        if det is None:
            try:
                cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
            except AttributeError:
                pass
            det = _detectors[(w, h)] = cv2.FaceDetectorYN.create(str(YUNET), '', (w, h), 0.75, 0.3, 20)
        _, found = det.detect(frame)
    return sum(1 for f in (found if found is not None else []) if f[3] >= FACE_MIN * h)


def _screen_like(frame):
    """(flat share, edge share): a screen's picture is mostly flat colour with sharp edges (text, buttons)."""
    import cv2
    import numpy as np
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    grey = cv2.resize(grey, (320, max(8, round(grey.shape[0] * 320 / grey.shape[1]))))
    h, w = (grey.shape[0] // 8) * 8, (grey.shape[1] // 8) * 8
    blocks = grey[:h, :w].reshape(h // 8, 8, w // 8, 8).astype(np.float32)
    flat = float((blocks.std(axis=(1, 3)) < 1.5).mean())
    edges = float((cv2.Canny(grey, 100, 200) > 0).mean())
    return flat, edges


def measure(path) -> dict:
    """One clip's measures (cached): {path, kind, duration, speech, speech_how, faces: [per frame], screen}."""
    path = str(path)
    suffix = Path(path).suffix.lower()
    kind = 'video' if suffix in VIDEO else 'audio' if suffix in AUDIO else 'photo'
    try:
        key = _key(path)
    except OSError:
        return {'path': path, 'kind': kind, 'error': 'not readable'}
    f = CACHE / f'{key}.json'
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding='utf-8-sig'))
        except ValueError:
            pass
    out = {'path': path, 'kind': kind}
    duration = None
    if kind != 'photo':
        duration = _probe_duration(path)
        out['duration'] = round(duration, 2) if duration else None
        share, how = _speech_from_cache(path, duration)
        if share is None:
            share, how = _speech_window(path, duration)
        out['speech'], out['speech_how'] = (round(share, 3) if share is not None else None), how
    frames = []
    if kind == 'video':
        frames = _frames(path, duration)
    elif kind == 'photo':
        try:
            import cv2
            img = cv2.imread(path)
            if img is not None:
                h, w = img.shape[:2]
                frames = [cv2.resize(img, (640, round(h * 640 / w)))] if w > 640 else [img]
        except ImportError:
            pass
    faces = [_faces(fr) for fr in frames]
    out['faces'] = None if any(x is None for x in faces) else faces
    shapes = [_screen_like(fr) for fr in frames]
    out['screen'] = [[round(a, 3), round(b, 3)] for a, b in shapes]
    name = Path(path).name.casefold()
    out['screen_name'] = any(word in name for word in SCREEN_WORDS)
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f'{f.stem}.{os.getpid()}-{threading.get_ident()}.tmp')
        tmp.write_text(json.dumps(out), encoding='utf-8')
        os.replace(tmp, f)
    except OSError:
        pass
    return out


# ---------------------------------------------------------------------------- the set of clips

def _clip_reading(m):
    """One clip read: talks?, face share, two-face share, screen? (None where unknown)."""
    faces = m.get('faces')
    frames = len(faces) if faces is not None else len(m.get('screen') or [])
    face = (sum(1 for n in faces if n >= 1) / frames) if faces and frames else (0.0 if faces is not None else None)
    two = (sum(1 for n in faces if n >= 2) / frames) if faces and frames else (0.0 if faces is not None else None)
    shots = m.get('screen') or []
    screen_frames = sum(1 for flat, edges in shots if flat >= SCREEN_FLAT and edges >= SCREEN_EDGES)
    screen = m.get('screen_name') or (bool(shots) and screen_frames * 3 >= 2 * len(shots))
    return {'speech': m.get('speech'), 'face': face, 'two': two, 'screen': bool(screen)}


def _styles():
    try:
        return {s.get('id') for s in json.loads((LOOKS / 'styles.json').read_text(encoding='utf-8-sig'))}
    except (OSError, ValueError, AttributeError):
        return set()


def decide(measured: list[dict]) -> dict:
    """The kind of video from the clips' measures: {style, kind, label, why, sure}. Clips count by their length
    (a photo or a clip of unknown length counts as 5 s)."""
    clips = [m for m in measured if m.get('kind') in ('video', 'audio', 'photo') and not m.get('error')]
    if not clips:
        return _answer('all', 'No clips to look at.', 0.0)
    total = 0.0
    talk = face = two = screen = 0.0
    face_known = talk_known = 0.0
    for m in clips:
        r = _clip_reading(m)
        w = float(m.get('duration') or 5.0)
        total += w
        if r['speech'] is not None:
            talk_known += w
            talk += w * (1.0 if r['speech'] >= TALK else 0.0)
        if r['face'] is not None and m.get('kind') != 'audio':
            face_known += w
            face += w * r['face']
            two += w * r['two']
        screen += w * (1.0 if r['screen'] else 0.0)
    talk_share = talk / talk_known if talk_known else None
    face_share = face / face_known if face_known else None
    two_share = two / face_known if face_known else None
    screen_share = screen / total
    if screen_share >= 0.5:
        return _answer('screen', 'Most clips look like a screen: flat colour and sharp text.', min(1.0, screen_share))
    if talk_share is None:
        return _answer('all', "Couldn't hear the clips' sound on this PC.", 0.0)
    if talk_share < LITTLE_TALK:
        return _answer('activity', f'Little talk: someone talks in {round(100 * talk_share)}% of the footage.',
                       1.0 - talk_share)
    if talk_share >= 0.5:
        if face_share is None:
            return _answer('all', "Mostly talk, but the face model isn't on this PC.", 0.3)
        if two_share >= 0.4:
            return _answer('conversation', 'Mostly talk, with two or more faces in many frames.', min(1.0, two_share + .3))
        # several cameras on one talk: a wide shows both people, the close-ups one each, so the two-face share is diluted
        talking = [(m, _clip_reading(m)) for m in clips if m.get('kind') == 'video']
        talk_time = sum(float(m.get('duration') or 5.0) for m, r in talking if (r['speech'] or 0) >= TALK)
        wide_time = sum(float(m.get('duration') or 5.0) for m, r in talking
                        if (r['speech'] or 0) >= TALK and (r['two'] or 0) >= 0.5)
        if talk_time and wide_time >= ANGLES_WIDE * talk_time:
            return dict(_answer('conversation', 'Mostly talk; one clip shows two people in most frames and the others one '
                                'face each: likely several cameras on one conversation.', min(1.0, wide_time / talk_time + .3)),
                        angles=True)
        if face_share >= 0.5:
            return _answer('talking-head', 'Mostly talk, with one face to the camera in most frames.', min(1.0, face_share))
        if face_share < 0.2:
            return _answer('activity', 'Talk over the work: someone talks, but the camera is on what they do.',
                           1.0 - face_share)
    return _answer('all', 'A mix: some talk to the camera, some not.', 0.3)


def _answer(style, why, sure):
    if style != 'all' and style not in _styles():
        why, style = f'{why} (no Style for it yet)', 'all'
    return {'style': style, 'kind': KIND[style] if style in KIND else 'unsure', 'label': LABELS.get(style, style),
            'why': why, 'sure': round(float(sure), 2)}


def detect(paths, budget_s: float = 4.0, workers: int = 4) -> dict:
    """The kind of video the clips are (module doc). Never raises for a bad file: it is left out."""
    started = time.monotonic()
    files = media_files(paths)
    picked = _spread(files, MAX_CLIPS)
    measured = []
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers))
    futures = [pool.submit(measure, p) for p in picked]
    for fut in futures:
        left = budget_s - (time.monotonic() - started)
        try:
            measured.append(fut.result(timeout=max(0.05, left)))
        except concurrent.futures.TimeoutError:
            break
        except Exception:  # noqa: BLE001 - one bad file never stops the answer
            continue
    # clips not started are dropped; one being measured finishes in the background and fills the cache for next time
    pool.shutdown(wait=False, cancel_futures=True)
    result = decide(measured)
    result.update(looked_at=len(measured), of=len(files), seconds=round(time.monotonic() - started, 2),
                  complete=len(measured) == len(picked),
                  clips=[{'name': Path(m['path']).name, **{k: m.get(k) for k in ('speech', 'faces', 'screen')}}
                         for m in measured])
    return result


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    args = sys.argv[1:]
    budget = 4.0
    if '--budget' in args:
        i = args.index('--budget')
        budget = float(args[i + 1])
        del args[i:i + 2]
    try:
        out = detect(args, budget_s=budget)
    except Exception as error:  # noqa: BLE001 - New video shows All when this fails
        out = {'style': 'all', 'kind': 'unsure', 'label': LABELS['all'], 'why': f'{type(error).__name__}: {error}',
               'sure': 0.0, 'looked_at': 0, 'of': 0, 'complete': False}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + '\n')
