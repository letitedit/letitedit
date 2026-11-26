"""Search footage by what is in it, and tell people apart: model-backed tools for letitedit.

    search(query | example, kind, files, ranges, count, min_gap_s, every_s, out_dir, ...)
        moments that look like (picture), are said like (speech) or sound like (sound) a text or an example moment;
        a frame sheet of the results with time labels.
    speakers(files, count, names, faces, out_dir, ...)
        who talks when (voice clusters), whose faces are seen (face clusters, with sample images), every word with
        its speaker; names the caller gives to ids are remembered.
    speaker_words(file)
        the words of one file with their speaker ids (and names), for other tools.
    set_names(names)
        give names to speaker or face ids ({'S1': 'Alex', 'F2': 'Dad'}).

Data in, data out: no verdicts. Every number (result count, spacing, sampling, number of speakers, thresholds) is the
caller's choice; the values used, defaults included, are in each result's `settings`. Every image is a file whose path
is in the result.

Models run in a separate Python (C:\\LetItEdit\\envs\\models: torch + CUDA) through index_worker.py, kept alive while
in use. Per-file indexes (embeddings) are cached under C:\\LetItEdit\\cache\\index\\, keyed by file content (like
perception.content_key), model and sampling, so a second search over the same footage only scores.

    picture   OpenCLIP ViT-B-32 (laion2B-s34B-b79K): a frame every every_s seconds (by default the keyframe nearest
              each grid time, which skips decoding the frames between), 4 views per frame (whole frame letterboxed +
              3 squares along its long side); a frame's score is its best view.
    speech    the transcript (speech.words): exact phrase, word overlap (difflib ratio over windows of about the
              query's length) and meaning (CLIP text encoder over windows of meaning_words words).
    sound     CLAP (laion/clap-htsat-unfused): windows of window_s seconds every every_s seconds.
    voices    SpeechBrain ECAPA (spkrec-ecapa-voxceleb) on speech segments cut from word timings and voice detection.
    faces     YuNet detection + SFace embeddings (OpenCV) on frames every face_every_s seconds.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import difflib
import hashlib
import io
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
INDEX = CACHE / 'index'
APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))
FFMPEG, FFPROBE = APP / 'ffmpeg.exe', APP / 'ffprobe.exe'
MODELS_PY = os.environ.get('LETITEDIT_MODELS_PYTHON', (_SAI_ROOT + '\\envs\\models\\Scripts\\python.exe'))
HF_HOME = os.environ.get('LETITEDIT_HF_HOME', (_SAI_ROOT + '\\models\\hf'))
WORKER = _paths.BRIDGE / 'index_worker.py'
IDLE_S = float(os.environ.get('LETITEDIT_INDEX_IDLE_S', 600))
GPU_LOCK = Path(os.environ.get('LETITEDIT_GPU_LOCK', (_SAI_ROOT + '\\cache\\models\\gpu.lock')))   # one model job at a time on this PC (all processes, any cache)
NAMES_FILE = INDEX / 'names.json'            # remembered speaker / face ids: centroids and names
SPEAKERS_DIR = INDEX / 'speakers'            # each file's last speaker assignment (for speaker_words)
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
VERSION = 1

PICTURE_MODEL = 'OpenCLIP ViT-B-32 laion2B-s34B-b79K'
SOUND_MODEL = 'CLAP laion/clap-htsat-unfused'
VOICE_MODEL = 'SpeechBrain ECAPA spkrec-ecapa-voxceleb'
FACE_MODEL = 'YuNet 2023mar + SFace 2021dec (OpenCV)'
KINDS = ('picture', 'speech', 'sound')

SEARCH_DEFAULTS = {
    'count': 12,            # results returned
    'min_gap_s': 5.0,       # results of one kind in one file at least this far apart (the best one is kept)
    'every_s': 1.0,         # seconds between indexed frames (picture) and between sound windows
    'window_s': 2.0,        # sound window length
    'frames': 'auto',       # picture sampling: 'keyframes' (nearest each grid time), 'exact', or 'auto'
    'span_level': 0.75,     # a result's start/end: neighbouring samples scoring at least this far from the median to the peak
    'speech_match': 'both',  # 'words' (exact + word overlap), 'meaning' (CLIP text), 'both'
    'per_kind': None,       # several kinds: each kind's best per_kind results are kept (None: count // kinds; 0: by score only)
    'meaning_words': 10,    # words per transcript window for meaning
    'speech_pause_s': 1.5,  # speech windows (words and meaning) do not cross a pause longer than this
    'frame_height': 320,    # result frame images and sheet tiles, px
    'sheet_per_row': 6,
}
SPEAKER_DEFAULTS = {
    'method': 'threshold',  # without count: 'threshold' (average-linkage distance) or 'eigengap'
    'threshold': 0.2,       # voices: segments group while their average cosine similarity is at least this
    'segment_s': 3.0,       # longest speech segment embedded
    'min_segment_s': 1.5,   # shorter segments do not shape the clusters; they get the nearest speaker afterwards
    'pause_s': 0.5,         # a word gap longer than this starts a new segment
    'voice_overlap': 0.5,   # a word segment counts when at least this share of it is detected voice
    'match': 0.5,           # a cluster takes a remembered id when its centroid is at least this similar
    'face_every_s': 1.0,    # seconds between frames searched for faces
    'face_frames': 'auto',
    'face_long_px': 1280,   # frames are decoded at this long side for face detection
    'face_min_score': 0.8,  # YuNet confidence
    'face_min_px': 48,      # smallest face height (px at face_long_px)
    'face_threshold': 0.363,  # faces group while their average SFace cosine similarity is at least this
    'face_count': None,     # number of face clusters (None: by face_threshold)
    'face_match': 0.45,
    'samples': 6,           # sample images per face cluster
    'sample_words': 3,      # longest segments quoted per speaker
}


# ------------------------------------------------------------------ worker

class _GpuLock:
    """One heavy model job at a time across processes on this PC (a lock file under the index cache)."""

    def __enter__(self):
        import msvcrt
        GPU_LOCK.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(GPU_LOCK, 'a+b')
        while True:
            try:
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except OSError:
                time.sleep(0.2)

    def __exit__(self, *exc):
        import msvcrt
        try:
            self.fh.seek(0)
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.fh.close()


class _Worker:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.next = 1
        self.hello = None

    def _start(self):
        if self.proc is not None and self.proc.poll() is None:
            return
        INDEX.mkdir(parents=True, exist_ok=True)
        log = INDEX / 'worker.log'
        if log.exists() and log.stat().st_size > 5_000_000:
            log.unlink()
        env = dict(os.environ, HF_HOME=HF_HOME, PYTHONIOENCODING='utf-8', HF_HUB_DISABLE_TELEMETRY='1',
                   HF_HUB_DISABLE_SYMLINKS_WARNING='1', TRANSFORMERS_VERBOSITY='error', TQDM_DISABLE='1')
        env.pop('PYTHONPATH', None)
        if not os.path.exists(MODELS_PY):
            raise RuntimeError(f'model Python not found: {MODELS_PY}')
        with open(log, 'a', encoding='utf-8') as err:       # the worker keeps its own handle to the log
            import letitedit.core.render_lock as render_lock
            self.proc = render_lock.popen_worker([MODELS_PY, '-I', str(WORKER), str(IDLE_S)], stdin=subprocess.PIPE,
                                                 stdout=subprocess.PIPE, stderr=err, text=True, encoding='utf-8',
                                                 creationflags=NO_WINDOW, env=env)
        hello = json.loads(self.proc.stdout.readline() or '{}')
        if not hello.get('ready'):
            self.proc = None
            raise RuntimeError('model worker did not start: ' + _log_tail())
        self.hello = hello

    def ask(self, op, **req):
        import letitedit.core.first_use as first_use                            # first use: the models environment + the op's models
        first_use.need_for_python(MODELS_PY, INDEX_OP_MODELS.get(op, ()), feature=f'index ({op})')
        import letitedit.core.render_lock as render_lock
        with render_lock.model_slot(f'index {op}'), self.lock, _GpuLock():     # the PC render lock first
            self._start()
            rid = self.next
            self.next += 1
            try:
                self.proc.stdin.write(json.dumps({'id': rid, 'op': op, **req}) + '\n')
                self.proc.stdin.flush()
                line = self.proc.stdout.readline()
            except OSError:
                line = ''
            if not line:
                self.proc = None
                raise RuntimeError(f'model worker stopped during {op}: ' + _log_tail())
            reply = json.loads(line)
            if reply.get('error'):
                raise RuntimeError(f'model worker {op}: {reply["error"]}')
            return reply

    def stop(self):
        with self.lock:
            p = self.proc
            if p is not None:
                try:
                    if p.poll() is None:
                        p.stdin.close()
                        p.wait(timeout=10)
                except Exception:  # noqa: BLE001
                    p.kill()
                for fh in (p.stdin, p.stdout):
                    try:
                        fh.close()
                    except Exception:  # noqa: BLE001
                        pass
            self.proc = None


def _log_tail(n=1500):
    try:
        return (INDEX / 'worker.log').read_text(encoding='utf-8', errors='replace')[-n:]
    except OSError:
        return ''


# models each worker op needs (model_fetch manifest ids), fetched on first use
INDEX_OP_MODELS = {'video': ['clip-vit-b-32', 'opencv-zoo-faces-tracking'], 'clip_text': ['clip-vit-b-32'],
                   'clip_frames': ['clip-vit-b-32'], 'audio': ['clap-htsat-unfused'],
                   'clap_text': ['clap-htsat-unfused'], 'clap_span': ['clap-htsat-unfused'],
                   'ecapa': ['spkrec-ecapa-voxceleb']}
_worker = _Worker()


def stop_worker():
    """Stop the model worker now (it also stops by itself after LETITEDIT_INDEX_IDLE_S idle seconds)."""
    _worker.stop()


# ------------------------------------------------------------------ files

def _pc():
    import letitedit.footage.perception as perception
    return perception


def _probe(path):
    import letitedit.server.core_tools as core_tools
    return core_tools.probe(path)


def _key(path):
    return _pc().content_key(path)


def _clock(s):
    return _pc().clock(s)


def _media_files(files):
    """files: a folder, a file, or a list of them -> [absolute paths of video and audio files], in name order."""
    if files is None:
        raise ValueError('files is required: a folder, a file, or a list of files')
    items = [files] if isinstance(files, (str, os.PathLike)) else list(files)
    out = []
    for it in items:
        p = Path(it)
        if p.is_dir():
            for f in sorted(p.iterdir(), key=lambda x: x.name.lower()):
                if f.is_file() and _pc().kind(f) in ('video', 'audio'):
                    out.append(str(f.resolve()))
        elif p.is_file():
            out.append(str(p.resolve()))
        else:
            raise FileNotFoundError(str(it))
    seen, uniq = set(), []
    for f in out:
        if f.lower() not in seen:
            seen.add(f.lower())
            uniq.append(f)
    return uniq


def _ranges(ranges, files):
    """{file: [(start, end)]} from {path or name: [[s, e], ...]} or [[file, s, e], ...]; None = everything."""
    if not ranges:
        return None
    by_name = {}
    for f in files:
        by_name.setdefault(Path(f).name.lower(), f)
        by_name.setdefault(str(Path(f)).lower(), f)

    def find(name):
        p = str(Path(name).resolve()).lower() if os.path.exists(str(name)) else None
        f = by_name.get(p) if p else None
        f = f or by_name.get(str(name).lower()) or by_name.get(Path(str(name)).name.lower())
        if f is None:
            raise ValueError(f'ranges names a file that is not in files: {name}')
        return f
    out = {}
    if isinstance(ranges, dict):
        for name, spans in ranges.items():
            f = find(name)
            if spans and isinstance(spans[0], (int, float)):
                spans = [spans]
            out.setdefault(f, []).extend((float(a), float(b)) for a, b in spans)
    else:
        for item in ranges:
            out.setdefault(find(item[0]), []).append((float(item[1]), float(item[2])))
    return out


def _in_ranges(rng, f, a, b=None):
    if rng is None:
        return True
    spans = rng.get(f)
    if not spans:
        return False
    b = a if b is None else b
    mid = (a + b) / 2
    return any(s - 1e-6 <= mid <= e + 1e-6 for s, e in spans)


def _settings(defaults, given):
    used = {k: (given[k] if given.get(k) is not None else v) for k, v in defaults.items() if k in given}
    return used, sorted(k for k in used if given.get(k) is None)


def _out_dir(out_dir, what):
    if out_dir:
        d = Path(out_dir)
    else:
        d = INDEX / 'results' / f'{time.strftime("%Y%m%d-%H%M%S")}-{what}-{uuid.uuid4().hex[:4]}'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _num(x):
    return f'{float(x):g}'.replace('.', 'p')


def _load(path):
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


# ------------------------------------------------------------------ sampling

_KF = {}


def keyframe_gap(path):
    """Median seconds between keyframes over the first 20 s of a video (packet flags; no decoding), or None."""
    k = _key(path)
    if k in _KF:
        return _KF[k]
    f = INDEX / 'keyframes' / f'{k}.json'
    if f.exists():
        _KF[k] = json.loads(f.read_text(encoding='utf-8-sig'))['gap']
        return _KF[k]
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-select_streams', 'v:0', '-read_intervals', '%+20',
                        '-show_entries', 'packet=pts_time,flags', '-of', 'csv=p=0', str(path)],
                       capture_output=True, text=True, errors='replace', creationflags=NO_WINDOW)
    ts = []
    for line in r.stdout.splitlines():
        parts = line.strip().split(',')
        if len(parts) >= 2 and 'K' in parts[1]:
            try:
                ts.append(float(parts[0]))
            except ValueError:
                pass
    ts = sorted(set(ts))
    gap = float(np.median(np.diff(ts))) if len(ts) >= 3 else None
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({'file': str(path), 'gap': gap, 'keyframes': ts[:60]}), encoding='utf-8')
    _KF[k] = gap
    return gap


def _mode(path, every_s, frames):
    if frames in ('keyframes', 'exact'):
        return frames
    gap = keyframe_gap(path)
    return 'keyframes' if gap and gap <= every_s + 1e-6 else 'exact'


def _dims(info, short=None, long_=None):
    w, h = int(info.get('width') or 16), int(info.get('height') or 9)
    if short:
        s = short / min(w, h)
    else:
        s = long_ / max(w, h)
    ow, oh = max(2, int(round(w * s / 2)) * 2), max(2, int(round(h * s / 2)) * 2)
    if short:
        ow, oh = (max(ow, short), max(oh, short))
    return ow, oh


def _picture_file(path, every_s, mode):
    return INDEX / 'picture' / f'{_key(path)}-clipB32laion2b-{mode[0]}{_num(every_s)}-v{VERSION}.npz'


def _faces_file(path, every_s, mode, long_px):
    return INDEX / 'faces' / f'{_key(path)}-yunet-sface-{mode[0]}{_num(every_s)}-l{int(long_px)}-v{VERSION}.npz'


def _sound_file(path, win_s, hop_s):
    return INDEX / 'sound' / f'{_key(path)}-clap-htsat-unfused-w{_num(win_s)}-h{_num(hop_s)}-v{VERSION}.npz'


def build_video_index(files, every_s=1.0, frames='auto', faces=False, face_every_s=None, face_frames=None,
                      face_long_px=1280):
    """Make sure the picture index (and with faces=True the face index) exists for each video; returns
    {'built': [{file, footage_s, decode_s}], 'cached': n, 'build_s': s, 'modes': {file: mode}}."""
    t0 = time.time()
    jobs, built, cached, modes = [], [], 0, {}
    for f in files:
        if _pc().kind(f) != 'video':
            continue
        info = _probe(f)
        mode = _mode(f, every_s, frames)
        modes[f] = mode
        pic = _picture_file(f, every_s, mode)
        need_pic = not pic.exists()
        fe = face_every_s or every_s
        fmode = _mode(f, fe, face_frames or frames) if faces else None
        fac = _faces_file(f, fe, fmode, face_long_px) if faces else None
        need_fac = bool(faces) and not fac.exists()
        if not need_pic and not need_fac:
            cached += 1
            continue
        if need_fac:
            w, h = _dims(info, long_=face_long_px)
            share = need_pic and fe == every_s and fmode == mode
            jobs.append({'video': f, 'out_w': w, 'out_h': h, 'every_s': fe, 'mode': fmode,
                         'clip': str(pic) if share else None, 'faces': str(fac), 'footage_s': info['duration']})
            if need_pic and not share:
                w2, h2 = _dims(info, short=224)
                jobs.append({'video': f, 'out_w': w2, 'out_h': h2, 'every_s': every_s, 'mode': mode,
                             'clip': str(pic), 'faces': None, 'footage_s': info['duration']})
        else:
            w, h = _dims(info, short=224)
            jobs.append({'video': f, 'out_w': w, 'out_h': h, 'every_s': every_s, 'mode': mode, 'clip': str(pic),
                         'faces': None, 'footage_s': info['duration']})
    errors = []
    if jobs:
        r = _worker.ask('video', ffmpeg=str(FFMPEG), jobs=[{k: v for k, v in j.items() if k != 'footage_s'}
                                                           for j in jobs], threads=4)
        foot = {j['video']: j['footage_s'] for j in jobs}
        for d in r['done']:
            built.append({'file': d['video'], 'footage_s': foot.get(d['video']), 'frames': d['frames'],
                          'faces': d.get('faces'), 'decode_s': d['decode_s']})
        errors = r.get('errors') or []
    return {'built': built, 'cached': cached, 'build_s': round(time.time() - t0, 2), 'modes': modes,
            'errors': errors}


def build_sound_index(files, window_s=2.0, every_s=1.0):
    t0 = time.time()
    built, cached = [], 0
    for f in files:
        info = _probe(f)
        if not info.get('audio'):
            continue
        out = _sound_file(f, window_s, every_s)
        if out.exists():
            cached += 1
            continue
        r = _worker.ask('audio', ffmpeg=str(FFMPEG), path=f, win_s=window_s, hop_s=every_s, out=str(out))
        built.append({'file': f, 'footage_s': r['seconds'], 'windows': r['windows'], 'took_s': r['took_s']})
    return {'built': built, 'cached': cached, 'build_s': round(time.time() - t0, 2)}


# ------------------------------------------------------------------ speech index

_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")


def _norm(text):
    return _TOKEN.findall(str(text).lower().replace('\u2019', "'"))


def _words(f):
    """speech.words for the whole file (the cached transcript when there is one; else it transcribes)."""
    import letitedit.footage.speech as speech
    try:
        ws = speech.cached_words(f)
        return ws if ws is not None else speech.words(f)
    except Exception as e:  # noqa: BLE001 - no audio / unreadable
        if type(e).__name__ == 'Busy':
            raise                           # waited behind a render (render_lock.Busy): say so, don't index without words
        return []


def _meaning_windows(ws, n, pause_s=1.0):
    """[(i0, i1)] word index windows of n words, every n // 2 words, within lines (a pause over pause_s starts a new
    line; a line's last window reaches its end)."""
    if not ws:
        return []
    n = max(1, int(n))
    step = max(1, n // 2)
    lines, a = [], 0
    for k in range(1, len(ws) + 1):
        if k == len(ws) or ws[k]['s'] - ws[k - 1]['e'] > pause_s:
            lines.append((a, k))
            a = k
    out = []
    for a, b in lines:
        i = a
        while True:
            j = min(b, i + n)
            out.append((i, j))
            if j >= b:
                break
            i += step
    return out


def _meaning_index(f, ws, n, pause_s=1.0):
    """CLIP text embeddings of the file's transcript windows (cached by transcript content)."""
    wins = _meaning_windows(ws, n, pause_s)
    if not wins:
        return wins, np.zeros((0, 512), np.float32)
    texts = [' '.join(w['w'] for w in ws[a:b]) for a, b in wins]
    h = hashlib.sha1(json.dumps([[w['w'], w['s'], w['e']] for w in ws]).encode()).hexdigest()[:16]
    out = INDEX / 'speech' / f'{h}-clipB32-n{n}-p{_num(pause_s)}-v{VERSION}.npz'
    if not out.exists():
        _worker.ask('clip_text', texts=texts, out=str(out))
    return wins, _load(out)['emb'].astype(np.float32)


# ------------------------------------------------------------------ scoring

def _z(raws):
    a = np.asarray(raws, dtype=np.float64)
    if a.size == 0:
        return a
    sd = a.std()
    return (a - a.mean()) / max(sd, 1e-3)


def _extent(times, starts, ends, raw, i, level, median):
    """Neighbouring samples (same file, consecutive) whose score stays above median + level * (peak - median)."""
    floor = median + level * (raw[i] - median)
    a = i
    while a - 1 >= 0 and raw[a - 1] >= floor and starts[a] - ends[a - 1] <= (ends[a] - starts[a]) + 1e-6:
        a -= 1
    b = i
    while b + 1 < len(raw) and raw[b + 1] >= floor and starts[b + 1] - ends[b] <= (ends[b] - starts[b]) + 1e-6:
        b += 1
    return starts[a], ends[b]


def _picture_candidates(files, qvec, every_s, modes, rng, example_frame=None):
    """[(file, at, start, end, raw, matched)] for every indexed frame in range."""
    out = []
    for f in files:
        if f not in modes:
            continue
        p = _picture_file(f, every_s, modes[f])
        if not p.exists():
            continue
        z = _load(p)
        times, emb, views = z['times'], z['emb'].astype(np.float32), [str(v) for v in z['views']]
        if len(times) == 0:
            continue
        sims = emb @ qvec                    # [n, V]
        best_v = sims.argmax(axis=1)
        raw = sims.max(axis=1)
        dur = _probe(f)['duration']
        half = every_s / 2
        for i, t in enumerate(times):
            t = float(t)
            if not _in_ranges(rng, f, t):
                continue
            out.append({'file': f, 'at': round(t, 3), 'start': round(max(0.0, t - half), 3),
                        'end': round(min(dur, t + half), 3), 'raw': float(raw[i]),
                        'matched': {'view': views[best_v[i]]}, '_series': (f, i)})
    return out


def _sound_candidates(files, qvec, window_s, every_s, rng):
    out = []
    for f in files:
        p = _sound_file(f, window_s, every_s)
        if not p.exists():
            continue
        z = _load(p)
        if len(z['start']) == 0:
            continue
        raw = z['emb'].astype(np.float32) @ qvec
        for i, (a, b) in enumerate(zip(z['start'], z['end'])):
            a, b = float(a), float(b)
            if not _in_ranges(rng, f, a, b):
                continue
            out.append({'file': f, 'at': round((a + b) / 2, 3), 'start': round(a, 3), 'end': round(b, 3),
                        'raw': float(raw[i]), 'matched': {'window': [round(a, 3), round(b, 3)]}, '_series': (f, i)})
    return out


def _speech_candidates(files, query, match, meaning_words, rng, qvec_text=None, speech_pause_s=1.0):
    """Exact phrase / word-overlap / meaning matches in the transcripts."""
    q = _norm(query)
    out = []
    if not q:
        return out, {}
    qtext = ' '.join(q)
    info = {'query_words': q}
    for f in files:
        ws = _words(f)
        if not ws:
            continue
        norm = [' '.join(_norm(w['w'])) for w in ws]
        if match in ('words', 'both'):
            n = len(q)
            line_end, end = [0] * len(ws), len(ws)        # the first word index after each word's line
            for k in range(len(ws) - 1, -1, -1):
                if k + 1 < len(ws) and ws[k + 1]['s'] - ws[k]['e'] > speech_pause_s:
                    end = k + 1
                line_end[k] = end
            for i in range(len(ws)):
                best = None
                for L in sorted({max(1, n - 1), n, n + 1}):
                    j = i + L
                    if j > line_end[i]:
                        break
                    seg = ' '.join(x for x in norm[i:j] if x)
                    if not seg:
                        continue
                    exact = L == n and seg == qtext
                    ratio = 1.0 if exact else difflib.SequenceMatcher(None, qtext, seg, autojunk=False).ratio()
                    if best is None or ratio > best[0]:
                        best = (ratio, j, exact)
                if best is None:
                    continue
                ratio, j, exact = best
                a, b = ws[i]['s'], ws[j - 1]['e']
                if not _in_ranges(rng, f, a, b):
                    continue
                out.append({'file': f, 'at': round(a, 3), 'start': round(a, 3), 'end': round(b, 3), 'raw': ratio,
                            'how': 'exact' if exact else 'words',
                            'matched': {'text': ' '.join(w['w'] for w in ws[i:j]),
                                        'how': 'exact' if exact else 'words', 'words_score': round(ratio, 3)}})
        if match in ('meaning', 'both') and qvec_text is not None:
            wins, emb = _meaning_index(f, ws, meaning_words, speech_pause_s)
            if len(wins):
                sims = emb @ qvec_text
                for (i, j), s in zip(wins, sims):
                    a, b = ws[i]['s'], ws[j - 1]['e']
                    if not _in_ranges(rng, f, a, b):
                        continue
                    out.append({'file': f, 'at': round(a, 3), 'start': round(a, 3), 'end': round(b, 3),
                                'raw': float(s), 'how': 'meaning',
                                'matched': {'text': ' '.join(w['w'] for w in ws[i:j]), 'how': 'meaning',
                                            'meaning_score': round(float(s), 3)}})
    return out, info


def _finish_kind(cands, kind, level, extent=True):
    """z-scores within the kind (speech: within each method), and start/end from neighbouring samples."""
    groups = {}
    for c in cands:
        groups.setdefault('meaning' if c.get('how') == 'meaning' else kind, []).append(c)
    for how, cs in groups.items():
        zs = _z([c['raw'] for c in cs])
        for c, z in zip(cs, zs):
            c['score'] = round(float(z), 3)
            c['kind'] = kind
        if extent and kind in ('picture', 'sound') and cs:
            med = float(np.median([c['raw'] for c in cs]))
            series = {}
            for c in cs:
                series.setdefault(c['_series'][0], []).append(c)
            for f, items in series.items():
                items.sort(key=lambda c: c['_series'][1])
                starts = [c['start'] for c in items]
                ends = [c['end'] for c in items]
                raw = [c['raw'] for c in items]
                for i, c in enumerate(items):
                    c['span'] = _extent(None, starts, ends, raw, i, level, med)
    return cands


def _pick(cands, count, min_gap_s, per_kind=0):
    """Best first; within one file and kind, results at least min_gap_s apart (and outside a kept result's span).
    per_kind: each kind's best per_kind results are in the list whatever the other kinds score; the rest by score."""
    cands = sorted(cands, key=lambda c: -c['score'])
    kept = _nms(cands, count, min_gap_s, per_kind_limit=count if per_kind else None)
    if not per_kind:
        return kept[:count]
    first, rest = [], []
    seen = {}
    for c in kept:
        n = seen.get(c['kind'], 0)
        (first if n < per_kind else rest).append(c)
        seen[c['kind']] = n + 1
    first = sorted(first, key=lambda c: -c['score'])[:count]
    return sorted(first + rest[:max(0, count - len(first))], key=lambda c: -c['score'])


def _nms(cands, count, min_gap_s, per_kind_limit=None):
    """cands sorted best first -> the kept ones. Without per_kind_limit, stop at count; with it, keep up to that
    many of each kind."""
    kept, groups, per = [], {}, {}
    kinds = {c['kind'] for c in cands}
    for c in cands:
        if per_kind_limit and per.get(c['kind'], 0) >= per_kind_limit:
            if all(per.get(k, 0) >= per_kind_limit for k in kinds):
                break
            continue
        g = groups.setdefault((c['file'], c['kind']), [])
        clash = False
        for k in g:
            ks, ke = k.get('span', (k['start'], k['end']))
            if abs(k['at'] - c['at']) < min_gap_s or ks - 1e-6 <= c['at'] <= ke + 1e-6:
                clash = True
                break
        if clash:
            continue
        g.append(c)
        kept.append(c)
        per[c['kind']] = per.get(c['kind'], 0) + 1
        if not per_kind_limit and len(kept) >= count:
            break
    return kept


# ------------------------------------------------------------------ images

def _font(size, bold=False):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf' if bold else r'C:\Windows\Fonts\arial.ttf', size)
    except OSError:
        return ImageFont.load_default()


def _grab(path, t, out, height=320, box=None, crop_scale=1.6, crop_px=None):
    """Save the frame at t (seconds) as a JPEG `height` px tall; with box (x0, y0, x1, y1 in a frame decoded at
    crop_px=(w, h)), a square crop around it instead. Returns the path or None."""
    if box is not None:
        w, h = crop_px
        x0, y0, x1, y1 = box
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        side = max(x1 - x0, y1 - y0) * crop_scale
        side = min(side, w, h)
        ax = int(max(0, min(w - side, cx - side / 2)))
        ay = int(max(0, min(h - side, cy - side / 2)))
        vf = f'scale={w}:{h}:flags=area,crop={int(side)}:{int(side)}:{ax}:{ay},scale=-2:{height}'
    else:
        vf = f'scale=-2:{height}:flags=area'
    r = subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-ss', f'{max(0.0, float(t)):.3f}', '-i', str(path),
                        '-frames:v', '1', '-vf', vf, '-q:v', '3', str(out)], capture_output=True,
                       creationflags=NO_WINDOW)
    return str(out) if r.returncode == 0 and os.path.exists(out) else None


def _sheet(tiles, out, per_row=6, title=None):
    """tiles: [(image path or None, [label lines])] -> one JPEG with each tile under its labels."""
    from PIL import Image, ImageDraw
    ims = []
    for p, _ in tiles:
        try:
            ims.append(Image.open(p).convert('RGB') if p else None)
        except OSError:
            ims.append(None)
    th = max([im.height for im in ims if im is not None] or [180])
    tw = max([im.width for im in ims if im is not None] or [180])
    tw = max(tw, 200)
    font, bold = _font(13), _font(14, True)
    probe = ImageDraw.Draw(Image.new('RGB', (8, 8)))

    def fit(text, f, width):
        if probe.textlength(text, font=f) <= width:
            return text
        while text and probe.textlength(text + '...', font=f) > width:
            text = text[:-1]
        return text + '...'

    def wrap(text, f, width, max_lines=2):
        words, lines = text.split(), ['']
        for w in words:
            trial = (lines[-1] + ' ' + w).strip()
            if probe.textlength(trial, font=f) <= width or not lines[-1]:
                lines[-1] = trial
            else:
                lines.append(w)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = fit(lines[-1] + ' ...', f, width)
        return [fit(ln, f, width) for ln in lines]
    labels = []
    for _, lab in tiles:
        out_lines = []
        for n, line in enumerate(lab):
            f = bold if n == 0 else font
            out_lines += wrap(line, f, tw - 6) if line.startswith('"') else [fit(line, f, tw - 6)]
        labels.append(out_lines)
    tiles = [(p, lab) for (p, _), lab in zip(tiles, labels)]
    lines_n = max(len(lab) for _, lab in tiles) if tiles else 1
    lh = 17 * lines_n + 6
    per_row = max(1, min(per_row, len(tiles))) if tiles else 1
    rows = max(1, math.ceil(len(tiles) / per_row))
    head = 28 if title else 0
    sheet = Image.new('RGB', (per_row * (tw + 6) + 6, head + rows * (th + lh + 6) + 6), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    if title:
        d.text((8, 6), title, fill=(255, 220, 0), font=bold)
    for k, ((p, lab), im) in enumerate(zip(tiles, ims)):
        x = 6 + (k % per_row) * (tw + 6)
        y = head + 6 + (k // per_row) * (th + lh + 6)
        for n, line in enumerate(lab):
            d.text((x + 2, y + 2 + 17 * n), line, fill=(255, 220, 0) if n == 0 else (230, 230, 230),
                   font=bold if n == 0 else font)
        if im is not None:
            sheet.paste(im, (x + (tw - im.width) // 2, y + lh))
        else:
            d.rectangle((x, y + lh, x + tw, y + lh + th), outline=(90, 90, 90))
            d.text((x + 8, y + lh + th // 2), 'no picture', fill=(160, 160, 160), font=font)
    sheet.save(out, 'JPEG', quality=85)
    return str(out)


# ------------------------------------------------------------------ search

def _query_vectors(kinds, query, example, files, every_s, modes, window_s, sound_hop, speech_match):
    """Per kind, what the candidates are compared with."""
    q = {}
    ex = example or {}
    if query:
        text_vec = None
        if 'picture' in kinds or ('speech' in kinds and speech_match in ('meaning', 'both')):
            text_vec = np.array(_worker.ask('clip_text', texts=[query])['emb'][0], dtype=np.float32)
        if 'picture' in kinds:
            q['picture'] = text_vec
        if 'sound' in kinds:
            q['sound'] = np.array(_worker.ask('clap_text', texts=[query])['emb'][0], dtype=np.float32)
        if 'speech' in kinds:
            q['speech'] = query
            if speech_match in ('meaning', 'both'):
                q['speech_vec'] = text_vec
        return q
    f = str(Path(ex['file']).resolve())
    info = _probe(f)
    if 'at' in ex:                                  # a frame: pictures like it
        if 'picture' in kinds and info.get('width'):
            w, h = _dims(info, short=224)
            r = _worker.ask('clip_frames', ffmpeg=str(FFMPEG), video=f, times=[float(ex['at'])], out_w=w, out_h=h)
            if r['emb'][0] is not None:
                q['picture'] = np.array(r['emb'][0][0], dtype=np.float32)    # the whole-frame view
        return q
    s, e = float(ex['start']), float(ex['end'])
    if 'picture' in kinds and info.get('width'):
        mode = modes.get(f) or _mode(f, every_s, 'auto')
        p = _picture_file(f, every_s, mode)
        vec = None
        if p.exists():
            z = _load(p)
            sel = [(i) for i, t in enumerate(z['times']) if s - 1e-6 <= t <= e + 1e-6]
            if sel:
                vec = z['emb'][sel, 0, :].astype(np.float32).mean(axis=0)
        if vec is None:
            w, h = _dims(info, short=224)
            r = _worker.ask('clip_frames', ffmpeg=str(FFMPEG), video=f, times=[(s + e) / 2], out_w=w, out_h=h)
            vec = np.array(r['emb'][0][0], dtype=np.float32) if r['emb'][0] is not None else None
        if vec is not None:
            q['picture'] = vec / (np.linalg.norm(vec) + 1e-9)
    if 'sound' in kinds and info.get('audio'):
        r = _worker.ask('clap_span', ffmpeg=str(FFMPEG), path=f, start=s, end=e, win_s=window_s, hop_s=sound_hop)
        if r.get('emb'):
            q['sound'] = np.array(r['emb'], dtype=np.float32)
    if 'speech' in kinds:
        text = ' '.join(w['w'] for w in _words(f) if s - 0.05 <= w['s'] < e)
        if text.strip():
            q['speech'] = text
            if speech_match in ('meaning', 'both'):
                q['speech_vec'] = np.array(_worker.ask('clip_text', texts=[text])['emb'][0], dtype=np.float32)
    return q


def search(query=None, example=None, kind='any', files=None, ranges=None, count=None, min_gap_s=None,
           every_s=None, out_dir=None, window_s=None, frames=None, span_level=None, speech_match=None,
           meaning_words=None, speech_pause_s=None, frame_height=None, sheet_per_row=None, per_kind=None):
    """Moments in `files` like a text `query` or an `example` moment.

    query: text ('a fan blower vent', 'grinding', 'pull the fan assembly out').
    example: {file, at} (a frame: pictures like it) or {file, start, end} (a span: pictures, sounds and words like
        it). kind: 'picture' | 'speech' | 'sound' | 'any' (all three, merged by score) or a list of them.
    files: a folder, a file, or a list (required). ranges: {file or name: [[start, end], ...]} or
        [[file, start, end], ...]: only those parts.
    count, min_gap_s: how many results, how far apart within one file and kind. every_s: seconds between indexed
        frames and between sound windows (a number, or {'picture': s, 'sound': s}). window_s: sound window length.
    frames: 'auto' | 'keyframes' | 'exact' (picture sampling). span_level: how a result's start/end grows over
        neighbouring samples (0-1, of the way from the median score to the peak). speech_match: 'words' | 'meaning' |
        'both'. meaning_words: words per transcript window for meaning; speech_pause_s: speech windows do not cross
        a longer pause. per_kind: with several kinds, each kind's best per_kind results are kept whatever the
        others score (default count // number of kinds; 0 = by score alone).

    Returns {results: [{file, start, end, at, kind, score, raw, matched, frame}], sheet, out_dir, index_info,
    settings, defaults}. score: standard deviations above the mean of every candidate of the same kind (speech: same
    method) in this search, so kinds can be merged; raw: the model's cosine similarity (speech words: overlap ratio
    0-1, exact phrase 1.0). frame: a JPEG of the result at `at`; sheet: all results in one image with labels.
    """
    t_all = time.time()
    if not query and not example:
        raise ValueError('give query (text) or example ({file, at} or {file, start, end})')
    given = dict(count=count, min_gap_s=min_gap_s, every_s=every_s, window_s=window_s, frames=frames,
                 span_level=span_level, speech_match=speech_match, meaning_words=meaning_words,
                 speech_pause_s=speech_pause_s, frame_height=frame_height, sheet_per_row=sheet_per_row,
                 per_kind=per_kind)
    settings, defaulted = _settings(SEARCH_DEFAULTS, given)
    ev = settings['every_s']
    pic_every = float(ev.get('picture', SEARCH_DEFAULTS['every_s']) if isinstance(ev, dict) else ev)
    snd_every = float(ev.get('sound', SEARCH_DEFAULTS['every_s']) if isinstance(ev, dict) else ev)
    settings['every_s'] = {'picture': pic_every, 'sound': snd_every}
    if kind in (None, 'any', 'all'):
        kinds = list(KINDS)
        if example and 'at' in example:
            kinds = ['picture']
    else:
        kinds = [kind] if isinstance(kind, str) else list(kind)
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        raise ValueError(f'kind must be picture, speech, sound or any: {bad}')
    flist = _media_files(files)
    if example:
        exf = str(Path(example['file']).resolve())
        if not os.path.exists(exf):
            raise FileNotFoundError(example['file'])
    rng = _ranges(ranges, flist)
    scope = [f for f in flist if rng is None or f in rng]
    info = {'cache': str(INDEX), 'files': len(scope)}
    modes = {}
    footage_s = sum(_probe(f)['duration'] for f in scope)
    info['footage_s'] = round(footage_s, 1)

    if 'picture' in kinds:
        b = build_video_index(scope, pic_every, settings['frames'])
        modes = b['modes']
        info['picture'] = {'model': PICTURE_MODEL, 'every_s': pic_every, 'frames': settings['frames'],
                           'modes': {m: sum(1 for v in modes.values() if v == m) for m in set(modes.values())},
                           'views': 'whole frame letterboxed + 3 squares along the long side; score = best view',
                           'built': b['built'], 'cached_files': b['cached'], 'build_s': b['build_s'],
                           'errors': b['errors']}
    if 'sound' in kinds:
        b = build_sound_index(scope, settings['window_s'], snd_every)
        info['sound'] = {'model': SOUND_MODEL, 'window_s': settings['window_s'], 'every_s': snd_every,
                         'built': b['built'], 'cached_files': b['cached'], 'build_s': b['build_s']}
    t_q = time.time()
    qv = _query_vectors(kinds, query, example, flist, pic_every, modes, settings['window_s'], snd_every,
                        settings['speech_match'])
    cands = []
    level = float(settings['span_level'])
    if 'picture' in qv:
        c = _picture_candidates(scope, qv['picture'], pic_every, modes, rng)
        cands += _finish_kind(c, 'picture', level)
        info['picture']['candidates'] = len(c)
        info['picture']['compared_with'] = 'text (CLIP text encoder)' if query else 'example frame (CLIP image)'
    if 'sound' in qv:
        c = _sound_candidates(scope, qv['sound'], settings['window_s'], snd_every, rng)
        cands += _finish_kind(c, 'sound', level)
        info['sound']['candidates'] = len(c)
        info['sound']['compared_with'] = 'text (CLAP text encoder)' if query else 'example span (CLAP audio, mean of its windows)'
    if 'speech' in qv:
        t_s = time.time()
        c, sinfo = _speech_candidates(scope, qv['speech'], settings['speech_match'], settings['meaning_words'], rng,
                                      qv.get('speech_vec'), float(settings['speech_pause_s']))
        cands += _finish_kind(c, 'speech', level, extent=False)
        info['speech'] = {'transcripts': 'speech.words (cached whisper word timings)', 'query': qv['speech'],
                          'match': settings['speech_match'],
                          'methods': {'exact': 'the query words in order', 'words': 'difflib ratio of the query vs '
                                      'windows of its length +-1 word (not across a pause over speech_pause_s)', 'meaning': f'{PICTURE_MODEL} text encoder over '
                                      f'windows of {settings["meaning_words"]} words (every {max(1, settings["meaning_words"] // 2)}) '
                                      f'that do not cross a pause over {settings["speech_pause_s"]} s'},
                          'candidates': len(c), 'took_s': round(time.time() - t_s, 2)}
    for k in kinds:
        if k not in qv:
            info.setdefault(k, {})['skipped'] = 'nothing to compare with (the example has no picture, sound or words for it)'
    if settings['per_kind'] is None:
        settings['per_kind'] = int(settings['count']) // len(kinds) if len(kinds) > 1 else 0
    picked = _pick(cands, int(settings['count']), float(settings['min_gap_s']), int(settings['per_kind']))
    od = _out_dir(out_dir, 'search')
    results = []
    for c in picked:
        s, e = c.get('span', (c['start'], c['end']))
        r = {'file': c['file'], 'start': round(float(s), 3), 'end': round(float(e), 3), 'at': c['at'],
             'kind': c['kind'], 'score': c['score'], 'raw': round(c['raw'], 4), 'matched': dict(c['matched'])}
        if example:
            ef = str(Path(example['file']).resolve())
            ea = float(example.get('at', example.get('start', 0)))
            eb = float(example.get('at', example.get('end', ea)))
            if ef.lower() == c['file'].lower() and r['start'] <= eb + 1e-6 and r['end'] >= ea - 1e-6:
                r['matched']['example_itself'] = True
        results.append(r)
    fh = int(settings['frame_height'])

    def grab(k_r):
        k, r = k_r
        if not _probe(r['file']).get('width'):
            return None
        out = od / f'{k + 1:02d}-{r["kind"]}-{Path(r["file"]).stem}-{r["at"]:.1f}s.jpg'
        return _grab(r['file'], r['at'], out, fh)
    with ThreadPoolExecutor(max_workers=6) as pool:
        frames_ = list(pool.map(grab, enumerate(results)))
    tiles = []
    for k, (r, fr) in enumerate(zip(results, frames_)):
        r['frame'] = fr
        lab = [f'{k + 1}. {r["kind"]}  {_clock(r["start"])}-{_clock(r["end"])}',
               f'{Path(r["file"]).name} @ {_clock(r["at"])}',
               f'score {r["score"]:.2f}  raw {r["raw"]:.3f}' + (f'  {r["matched"].get("view")}' if r['kind'] == 'picture' else '')]
        if r['kind'] == 'speech':
            lab.append('"' + r['matched'].get('text', '') + '"')
        tiles.append((fr, lab))
    title = f'search: {query!r}' if query else f'search like {Path(example["file"]).name} ' + (
        f'@ {_clock(example["at"])}' if 'at' in example else f'{_clock(example["start"])}-{_clock(example["end"])}')
    sheet = _sheet(tiles, od / 'results.jpg', int(settings['sheet_per_row']), title) if tiles else None
    info['search_s'] = round(time.time() - t_q, 2)
    info['total_s'] = round(time.time() - t_all, 2)
    info['score'] = ('standard deviations above the mean of all candidates of the same kind (speech: same method) '
                     'in this search; raw = cosine similarity (speech words: overlap ratio, exact = 1.0)')
    return {'results': results, 'sheet': sheet, 'out_dir': str(od), 'index_info': info,
            'settings': {'kinds': kinds, **settings}, 'defaults': defaulted}


# ------------------------------------------------------------------ names registry

_names_lock = threading.Lock()


def _registry():
    try:
        return json.loads(NAMES_FILE.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {'version': 1, 'speakers': {}, 'faces': {}}


def _save_registry(reg):
    NAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = NAMES_FILE.with_name(f'names.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(reg, indent=1), encoding='utf-8')
    os.replace(tmp, NAMES_FILE)


def set_names(names):
    """Give names to ids: {'S1': 'Alex', 'F1': 'Alex'} (S = voices, F = faces; None removes a name).
    Returns {'speakers': {id: name}, 'faces': {id: name}, 'file': path}."""
    with _names_lock:
        reg = _registry()
        for i, n in (names or {}).items():
            group = 'faces' if str(i).upper().startswith('F') else 'speakers'
            ent = reg[group].setdefault(str(i), {})
            ent['name'] = n
        _save_registry(reg)
    return {'speakers': {k: v.get('name') for k, v in reg['speakers'].items()},
            'faces': {k: v.get('name') for k, v in reg['faces'].items()}, 'file': str(NAMES_FILE)}


def _match_ids(group, prefix, centroids, weights, match):
    """Stable ids: each cluster (largest first) takes the most similar remembered id at or above `match`, else a new
    one. Updates the remembered centroids. Returns ([id per cluster], [similarity to the remembered centroid])."""
    with _names_lock:
        reg = _registry()
        known = reg[group]
        taken, ids, sims = set(), [None] * len(centroids), [None] * len(centroids)
        order = sorted(range(len(centroids)), key=lambda i: -weights[i])
        for i in order:
            c = centroids[i]
            best, best_s = None, -2.0
            for kid, ent in known.items():
                if kid in taken or not ent.get('centroid'):
                    continue
                v = np.asarray(ent['centroid'], dtype=np.float32)
                s = float(v @ c / (np.linalg.norm(v) * np.linalg.norm(c) + 1e-9))
                if s > best_s:
                    best, best_s = kid, s
            if best is not None and best_s >= match:
                kid = best
                sims[i] = round(best_s, 3)
            else:
                n = 1
                while f'{prefix}{n}' in known or f'{prefix}{n}' in taken:
                    n += 1
                kid = f'{prefix}{n}'
                known[kid] = {'name': (known.get(kid) or {}).get('name')}
            taken.add(kid)
            ids[i] = kid
            ent = known[kid]
            old = np.asarray(ent.get('centroid') or np.zeros_like(c), dtype=np.float32)
            ow = float(ent.get('weight') or 0.0)
            new = old * ow + c * float(weights[i])
            new = new / (np.linalg.norm(new) + 1e-9)
            ent['centroid'] = [round(float(x), 5) for x in new]
            ent['weight'] = round(min(ow + float(weights[i]), 3600.0), 2)
            ent['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
        _save_registry(reg)
        return ids, sims, {k: v.get('name') for k, v in known.items()}


# ------------------------------------------------------------------ clustering

def _cluster(E, count=None, threshold=0.2, method='threshold', max_k=10, cap=3000):
    """Agglomerative (average linkage, cosine) clusters of the rows of E (L2-normalised). count: that many;
    otherwise method 'threshold' (merge while the average similarity >= threshold) or 'eigengap'.
    Returns (labels 0..k-1 by size, info)."""
    n = len(E)
    info = {'items': n}
    if n == 0:
        return np.zeros(0, int), info
    if n == 1:
        return np.zeros(1, int), {**info, 'clusters': 1}
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist
    rs = np.random.default_rng(0)
    idx = np.arange(n) if n <= cap else np.sort(rs.choice(n, cap, replace=False))
    X = E[idx]
    eig = _eigengap(X[:1500] if len(X) > 1500 else X, max_k)
    info['eigengap'] = eig
    Z = linkage(np.clip(pdist(X, 'cosine'), 0, 2), 'average')
    if count:
        lab = fcluster(Z, int(count), 'maxclust')
        info['chosen_by'] = f'count={int(count)}'
    elif method == 'eigengap':
        lab = fcluster(Z, eig['count'], 'maxclust')
        info['chosen_by'] = f'eigengap ({eig["count"]})'
    else:
        lab = fcluster(Z, 1.0 - float(threshold), 'distance')
        info['chosen_by'] = f'threshold (average cosine similarity >= {threshold})'
    lab = lab - 1
    if len(idx) < n:                          # the rest: nearest centroid
        cents = np.stack([X[lab == k].mean(axis=0) for k in range(lab.max() + 1)])
        full = (E @ cents.T).argmax(axis=1)
        full[idx] = lab
        lab = full
        info['clustered_sample'] = len(idx)
    sizes = np.bincount(lab)
    order = np.argsort(-sizes, kind='stable')
    remap = np.empty_like(order)
    remap[order] = np.arange(len(order))
    lab = remap[lab]
    info['clusters'] = int(lab.max() + 1)
    return lab, info


def _eigengap(X, max_k=10):
    """Suggested number of groups from the spectrum of the normalised Laplacian of the cosine affinity."""
    n = len(X)
    if n < 3:
        return {'count': 1, 'eigenvalues': []}
    A = np.clip(X @ X.T, 0, 1).astype(np.float64)
    np.fill_diagonal(A, 0)
    d = A.sum(axis=1)
    d[d <= 0] = 1e-9
    dm = 1 / np.sqrt(d)
    L = np.eye(n) - dm[:, None] * A * dm[None, :]
    w = np.linalg.eigvalsh(L)[:min(max_k + 1, n)]
    gaps = np.diff(w)
    k = int(np.argmax(gaps[:max_k]) + 1) if len(gaps) else 1
    return {'count': k, 'eigenvalues': [round(float(x), 4) for x in w]}


# ------------------------------------------------------------------ speakers

def _voice_segments(f, ws, voice, segment_s, min_segment_s, pause_s, voice_overlap):
    """[(start, end, word index from, word index to)] speech segments of one file: words grouped at pauses and
    split at word boundaries to at most segment_s, kept when enough of each is detected voice; plus detected voice
    with no words. Returns (segments, dropped)."""
    runs = []
    for i, w in enumerate(ws):
        if runs and w['s'] - ws[runs[-1][-1]]['e'] <= pause_s:
            runs[-1].append(i)
        else:
            runs.append([i])
    segs = []
    for run in runs:
        cur = [run[0]]
        for i in run[1:]:
            if ws[i]['e'] - ws[cur[0]]['s'] > segment_s and len(cur) >= 1:
                segs.append(cur)
                cur = [i]
            else:
                cur.append(i)
        if segs and segs[-1][-1] + 1 == cur[0] and ws[cur[-1]]['e'] - ws[cur[0]]['s'] < min_segment_s \
                and ws[cur[-1]]['e'] - ws[segs[-1][0]]['s'] <= segment_s * 1.5:
            segs[-1].extend(cur)
        else:
            segs.append(cur)

    def overlap(a, b):
        return sum(max(0.0, min(b, y) - max(a, x)) for x, y in voice)
    out, dropped = [], 0
    for seg in segs:
        a, b = ws[seg[0]]['s'], ws[seg[-1]]['e']
        if b - a < 0.2:
            b = a + 0.2
        if voice and overlap(a, b) < voice_overlap * (b - a):
            dropped += 1
            continue
        out.append((round(a, 3), round(b, 3), seg[0], seg[-1] + 1))
    # detected voice that no word covers (mumbling, another language, missed by the transcriber)
    covered = [(a, b) for a, b, _, _ in out]
    for x, y in voice:
        gaps = [(x, y)]
        for a, b in covered:
            nxt = []
            for g0, g1 in gaps:
                if b <= g0 or a >= g1:
                    nxt.append((g0, g1))
                else:
                    if a > g0:
                        nxt.append((g0, a))
                    if b < g1:
                        nxt.append((b, g1))
            gaps = nxt
        for g0, g1 in gaps:
            t = g0
            while g1 - t >= min_segment_s:
                e = min(g1, t + segment_s)
                if g1 - e < min_segment_s:
                    e = g1
                out.append((round(t, 3), round(e, 3), -1, -1))
                t = e
    out.sort()
    return out, dropped


def _voice_embeddings(f, segs):
    key = hashlib.sha1(json.dumps([[a, b] for a, b, _, _ in segs]).encode()).hexdigest()[:12]
    out = INDEX / 'voice' / f'{_key(f)}-ecapa-{key}-v{VERSION}.npz'
    if not out.exists():
        _worker.ask('ecapa', ffmpeg=str(FFMPEG), path=f, segments=[[a, b] for a, b, _, _ in segs], out=str(out))
    return _load(out)['emb'].astype(np.float32), out


def _assign_file(f):
    return SPEAKERS_DIR / f'{_key(f)}.json'


def _words_with_speakers(ws, segs, near_s=0.5):
    """Each word with the speaker of the segment holding its middle (or the nearest one within near_s)."""
    import bisect
    segs = sorted(segs, key=lambda s: s[0])
    starts = [s[0] for s in segs]
    out = []
    for w in ws:
        m = (w['s'] + w['e']) / 2
        k = bisect.bisect_right(starts, m)
        best, best_d = None, near_s
        for j in (k - 1, k, k - 2, k + 1):
            if 0 <= j < len(segs):
                a, b = segs[j][0], segs[j][1]
                d = 0.0 if a <= m <= b else min(abs(m - a), abs(m - b))
                if d < best_d or (d == 0.0 and best_d > 0):
                    best, best_d = segs[j][2], d
        out.append({'w': w['w'], 's': w['s'], 'e': w['e'], 'speaker': best})
    return out


def _speaker_voice_embeddings(flist, info, st):
    t0 = time.time()
    per_file, all_emb, all_dur, owners = {}, [], [], []
    dropped_total = 0
    built_voice = 0
    for f in flist:
        if not _probe(f).get('audio'):
            continue
        import letitedit.sound.music as music
        ws = _words(f)
        try:
            voice = music.voice_times(f)
        except Exception:  # noqa: BLE001
            voice = []
        segs, dropped = _voice_segments(f, ws, voice, float(st['segment_s']), float(st['min_segment_s']),
                                        float(st['pause_s']), float(st['voice_overlap']))
        dropped_total += dropped
        if not segs:
            per_file[f] = {'words': ws, 'segs': [], 'emb': np.zeros((0, 192), np.float32)}
            continue
        existed = INDEX / 'voice'
        n_before = len(list(existed.glob(f'{_key(f)}-ecapa-*'))) if existed.exists() else 0
        emb, _ = _voice_embeddings(f, segs)
        built_voice += int(len(list(existed.glob(f'{_key(f)}-ecapa-*'))) > n_before)
        per_file[f] = {'words': ws, 'segs': segs, 'emb': emb}
        for k, (a, b, _, _) in enumerate(segs):
            all_emb.append(emb[k])
            all_dur.append(b - a)
            owners.append((f, k))
    info['voice_embed_s'] = round(time.time() - t0, 2)
    info['voice_files_embedded'] = built_voice
    info['segments'] = len(owners)
    info['segments_dropped_not_voice'] = dropped_total
    return per_file, all_emb, all_dur, owners


def _speaker_assignments(count, ids, labels, owners, per_file, reg_names, seg_sim, st):
    # per-file assignments (saved for speaker_words)
    words_out = {}
    owner_index = {o: i for i, o in enumerate(owners)}
    for f, d in per_file.items():
        segs = []
        for kk, (a, b, i0, i1) in enumerate(d['segs']):
            gi = owner_index[(f, kk)]
            segs.append([a, b, ids[labels[gi]], round(float(seg_sim[gi]), 3)])
        _assign_file(f).parent.mkdir(parents=True, exist_ok=True)
        _assign_file(f).write_text(json.dumps({'file': f, 'segments': segs, 'settings': {**st, 'count': count},
                                               'updated': time.strftime('%Y-%m-%d %H:%M:%S')}), encoding='utf-8')
        ww = _words_with_speakers(d['words'], segs)
        for w in ww:
            nm = reg_names.get(w['speaker']) if w['speaker'] else None
            if nm:
                w['name'] = nm
        words_out[f] = ww
    return words_out, owner_index


def _speaker_summaries(E, cents, dur, flist, id_sims, ids, info, k, labels, owner_index, owners, per_file,
        reg_names, st):
    spk = []
    for c in range(k):
        sel = np.where(labels == c)[0]
        spans = []
        for f in flist:
            mine = sorted((per_file[f]['segs'][kk][0], per_file[f]['segs'][kk][1]) for (ff, kk) in
                          (owners[i] for i in sel) if ff == f)
            if not mine:
                continue
            others = sorted((per_file[f]['segs'][kk][0], per_file[f]['segs'][kk][1]) for kk in
                            range(len(per_file[f]['segs'])) if labels[owner_index[(f, kk)]] != c)
            cur = list(mine[0])
            for a, b in mine[1:]:
                between = any(cur[1] <= x < a for x, _ in others)
                if a - cur[1] <= 1.5 and not between:
                    cur[1] = max(cur[1], b)
                else:
                    spans.append([f, round(cur[0], 3), round(cur[1], 3)])
                    cur = [a, b]
            spans.append([f, round(cur[0], 3), round(cur[1], 3)])
        longest = sorted(sel, key=lambda i: -dur[i])[:int(st['sample_words'])]
        quotes = []
        for i in longest:
            f, kk = owners[i]
            a, b, i0, i1 = per_file[f]['segs'][kk]
            text = ' '.join(w['w'] for w in per_file[f]['words'][i0:i1]) if i0 >= 0 else ''
            quotes.append({'file': f, 'start': a, 'end': b, 'text': text})
        within = E[sel] @ cents[c]
        spk.append({'id': ids[c], 'name': reg_names.get(ids[c]), 'seconds': round(float(dur[sel].sum()), 1),
                    'segments': int(len(sel)), 'similarity_to_centre': {'mean': round(float(within.mean()), 3),
                                                                        'min': round(float(within.min()), 3)},
                    'remembered_match': id_sims[c], 'spans': spans, 'sample_words': quotes})
    spk.sort(key=lambda s: -s['seconds'])
    if k > 1:
        cc = cents @ cents.T
        info['voice_centroid_similarity'] = {ids[i]: {ids[j]: round(float(cc[i, j]), 3) for j in range(k) if j != i}
                                             for i in range(k)}
    return spk


def _speaker_faces(faces, flist, info, out_dir, st):
    # ---- faces
    faces_out, faces_sheet = [], None
    od = None
    if faces:
        od = _out_dir(out_dir, 'speakers')
        t1 = time.time()
        fe = float(st['face_every_s'])
        vids = [f for f in flist if _pc().kind(f) == 'video']
        b = build_video_index(vids, fe, st['face_frames'], faces=True, face_every_s=fe,
                              face_frames=st['face_frames'], face_long_px=int(st['face_long_px']))
        info['faces_index'] = {'model': FACE_MODEL, 'built': b['built'], 'cached_files': b['cached'],
                               'build_s': b['build_s'], 'errors': b['errors']}
        dets = []           # (file, t, box, score, emb, size)
        for f in vids:
            mode = _mode(f, fe, st['face_frames'])
            p = _faces_file(f, fe, mode, int(st['face_long_px']))
            if not p.exists():
                continue
            z = _load(p)
            size = tuple(int(x) for x in z['size'])
            for t, box, sc, em in zip(z['times'], z['box'], z['score'], z['emb']):
                if sc < float(st['face_min_score']) or (box[3] - box[1]) < float(st['face_min_px']):
                    continue
                dets.append((f, float(t), [float(x) for x in box], float(sc), em.astype(np.float32), size))
        info['face_detections'] = len(dets)
        if dets:
            FE = np.stack([d[4] for d in dets])
            FE = FE / (np.linalg.norm(FE, axis=1, keepdims=True) + 1e-9)
            flab, finfo = _cluster(FE, st['face_count'], float(st['face_threshold']), 'threshold')
            info['face_clustering'] = finfo
            fk = int(flab.max() + 1)
            fc = np.stack([FE[flab == c].mean(axis=0) for c in range(fk)])
            fc = fc / (np.linalg.norm(fc, axis=1, keepdims=True) + 1e-9)
            fw = [float((flab == c).sum()) * fe for c in range(fk)]
            fids, fsims, fnames = _match_ids('faces', 'F', list(fc), fw, float(st['face_match']))
            jobs = []
            for c in range(fk):
                sel = [i for i in np.where(flab == c)[0]]
                sel.sort(key=lambda i: (dets[i][0], dets[i][1]))
                n = min(int(st['samples']), len(sel))
                chunks = np.array_split(np.array(sel), n) if n else []
                picks = [max(ch, key=lambda i: dets[i][3] * (dets[i][2][3] - dets[i][2][1])) for ch in chunks if len(ch)]
                for j, i in enumerate(picks):
                    f, t, box, sc, _, size = dets[i]
                    out = od / f'{fids[c]}-{j + 1:02d}-{Path(f).stem}-{t:.1f}s.jpg'
                    jobs.append((c, i, f, t, box, size, out))
            with ThreadPoolExecutor(max_workers=4) as pool:
                got = list(pool.map(lambda j: _grab(j[2], j[3], j[6], 160, box=j[4], crop_px=j[5]), jobs))
            by_c = {}
            for (c, i, f, t, box, size, out), path in zip(jobs, got):
                by_c.setdefault(c, []).append((path, f, t))
            tiles = []
            for c in range(fk):
                sel = np.where(flab == c)[0]
                spans = []
                for f in vids:
                    ts = sorted(dets[i][1] for i in sel if dets[i][0] == f)
                    if not ts:
                        continue
                    cur = [ts[0], ts[0]]
                    for t in ts[1:]:
                        if t - cur[1] <= 1.6 * fe:
                            cur[1] = t
                        else:
                            spans.append([f, round(cur[0], 3), round(cur[1], 3)])
                            cur = [t, t]
                    spans.append([f, round(cur[0], 3), round(cur[1], 3)])
                within = FE[sel] @ fc[c]
                samples_ = [p for p, _, _ in by_c.get(c, []) if p]
                faces_out.append({'id': fids[c], 'name': fnames.get(fids[c]), 'detections': int(len(sel)),
                                  'seconds_seen': round(len(sel) * fe, 1),
                                  'files': len({dets[i][0] for i in sel}),
                                  'similarity_to_centre': {'mean': round(float(within.mean()), 3),
                                                           'min': round(float(within.min()), 3)},
                                  'remembered_match': fsims[c], 'samples': samples_, 'spans': spans})
                for p, f, t in by_c.get(c, []):
                    tiles.append((p, [f'{fids[c]}' + (f' {fnames.get(fids[c])}' if fnames.get(fids[c]) else '')
                                      + f' ({len(sel)})', f'{Path(f).stem} {_clock(t)}']))
            faces_out.sort(key=lambda x: -x['detections'])
            if tiles:
                faces_sheet = _sheet(tiles, od / 'faces.jpg', int(st['samples']), 'faces: samples per cluster')
        info['faces_s'] = round(time.time() - t1, 2)
    return faces_out, faces_sheet, od


def speakers(files, count=None, names=None, faces=True, out_dir=None, method=None, threshold=None, segment_s=None,
             min_segment_s=None, pause_s=None, voice_overlap=None, match=None, face_every_s=None, face_frames=None,
             face_long_px=None, face_min_score=None, face_min_px=None, face_threshold=None, face_count=None,
             face_match=None, samples=None, sample_words=None):
    """Who talks when, and whose faces are in the picture.

    Voices: speech segments (word timings from speech.words grouped at pauses of pause_s, at most segment_s long,
    kept where at least voice_overlap of the segment is detected voice (music.voice_times); voice with no words
    is added too) -> ECAPA embeddings -> agglomerative clusters (count = the caller's number of speakers; without
    it method='threshold' (average cosine similarity >= threshold) or 'eigengap'). Segments shorter than
    min_segment_s get the nearest speaker afterwards. Faces (faces=True): YuNet faces in frames every face_every_s
    seconds (decoded at face_long_px), at least face_min_px tall with confidence >= face_min_score -> SFace
    embeddings -> clusters (face_count, or average similarity >= face_threshold) -> `samples` crops per cluster.

    Ids (S1, S2 ... for voices, F1 ... for faces) are remembered by their centroid in names.json under the index
    cache: a later call over any footage reuses an id when a cluster's centroid is at least `match` (faces:
    `face_match`) similar. names={id: name} names ids (kept for later calls and speaker_words).

    Returns {speakers: [{id, name, seconds, segments, spans: [[file, start, end]], sample_words}], faces: [{id,
    name, detections, samples: [image paths], spans}], faces_sheet, words: {file: [{w, s, e, speaker, name}]},
    settings, defaults, info}.
    """
    t_all = time.time()
    given = dict(method=method, threshold=threshold, segment_s=segment_s, min_segment_s=min_segment_s,
                 pause_s=pause_s, voice_overlap=voice_overlap, match=match, face_every_s=face_every_s,
                 face_frames=face_frames, face_long_px=face_long_px, face_min_score=face_min_score,
                 face_min_px=face_min_px, face_threshold=face_threshold, face_count=face_count,
                 face_match=face_match, samples=samples, sample_words=sample_words)
    st, defaulted = _settings(SPEAKER_DEFAULTS, given)
    st['count'] = count
    flist = _media_files(files)
    if names:
        set_names(names)
    info = {'voice_model': VOICE_MODEL, 'files': len(flist)}

    # ---- voices
    per_file, all_emb, all_dur, owners = _speaker_voice_embeddings(flist, info, st)
    E = np.stack(all_emb) if all_emb else np.zeros((0, 192), np.float32)
    dur = np.array(all_dur)
    long_ = np.where(dur >= float(st['min_segment_s']))[0]
    if len(long_) < 2:
        long_ = np.arange(len(E))
    labels_long, cinfo = _cluster(E[long_], count, float(st['threshold']), st['method'])
    info['voice_clustering'] = cinfo
    labels = np.full(len(E), -1)
    labels[long_] = labels_long
    k = int(labels_long.max() + 1) if len(labels_long) else 0
    cents = np.stack([E[long_][labels_long == c].mean(axis=0) for c in range(k)]) if k else np.zeros((0, 192))
    cents = cents / (np.linalg.norm(cents, axis=1, keepdims=True) + 1e-9) if k else cents
    seg_sim = np.zeros(len(E))
    if k:
        sims = E @ cents.T
        rest = labels < 0
        labels[rest] = sims[rest].argmax(axis=1)
        seg_sim = sims[np.arange(len(E)), labels]
    weights = [float(dur[labels == c].sum()) for c in range(k)]
    ids, id_sims, reg_names = _match_ids('speakers', 'S', list(cents), weights, float(st['match'])) if k else ([], [], {})
    words_out, owner_index = _speaker_assignments(count, ids, labels, owners, per_file, reg_names, seg_sim,
        st)
    spk = _speaker_summaries(E, cents, dur, flist, id_sims, ids, info, k, labels, owner_index, owners,
        per_file, reg_names, st)

    faces_out, faces_sheet, od = _speaker_faces(faces, flist, info, out_dir, st)
    info['total_s'] = round(time.time() - t_all, 2)
    settings = {**st, 'count': count, 'faces': bool(faces),
                'segments': 'word timings grouped at pauses > pause_s, split to <= segment_s at word boundaries'}
    return {'speakers': spk, 'faces': faces_out, 'faces_sheet': faces_sheet, 'out_dir': str(od) if od else None,
            'words': words_out, 'settings': settings, 'defaults': defaulted, 'info': info,
            'names_file': str(NAMES_FILE)}


def speaker_words(file):
    """The words of one file, each with its speaker id ('S1' ...) and name when the id has one: [{w, s, e,
    speaker, name}]. Uses the file's last speakers() assignment; without one, runs speakers([file], faces=False)."""
    f = str(Path(file).resolve())
    p = _assign_file(f)
    if not p.exists():
        speakers([f], faces=False)
    data = json.loads(p.read_text(encoding='utf-8-sig'))
    names = {k: v.get('name') for k, v in _registry()['speakers'].items()}
    out = _words_with_speakers(_words(f), data['segments'])
    for w in out:
        if w['speaker'] and names.get(w['speaker']):
            w['name'] = names[w['speaker']]
    return out
