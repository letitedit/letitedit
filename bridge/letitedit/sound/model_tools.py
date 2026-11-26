r"""Model-backed sound tools: stems of a recording, what a stretch of sound is like, a voice saying your text.

    separate(file, start=None, end=None, parts=None, out_dir=None, model='htdemucs', shifts=None, overlap=None,
             loudness_every_s=None)
        -> {'files': {part: wav path}, 'loudness': {part: {...}}, 'model', 'seconds', 'settings', ...}
    hear(source, start=None, end=None, every_s=None, window_s=None, labels=None, top=None, spectrogram=False,
         out_dir=None, score=None, template=None)
        -> {'segments': [{'start', 'end', 'labels': [[label, score], ...]}], 'labels_used', 'model', 'spectrogram',
            'audio', 'settings', ...}
    voice(text, reference=None, out=None, exaggeration=None, cfg_weight=None, temperature=None, seed=None,
          repetition_penalty=None, min_p=None, top_p=None, pause_s=None, split=True, words=True, engine=None,
          engine_settings=None, reference_text=None, reference_max_s=None)
        -> {'file', 'seconds', 'words': [{'w', 's', 'e', 'p'}], 'sentences', 'reference_used', 'engine', 'settings',
            'seed', 'licence', 'watermark', ...}   engines: VOICE_ENGINES (voice_engine_worker.py for all but chatterbox)
    release(whisper=True)   every model off the GPU (they stay loaded in RAM); whisper: also end this process's
                            speech transcription worker
    status()                the workers and the GPU memory they hold
    stop()                  end the worker processes

From a shell (any agent): python model_tools.py <function> '<JSON object of arguments>'  -> the result as JSON.

The models run in two worker processes in their own Python environments (model_worker.py in envs\models: Demucs and
CLAP; voice_worker.py in envs\voice: Chatterbox), started on first use, kept alive between calls (they exit after
LETITEDIT_MODEL_IDLE seconds idle, default 600) and restarted if they die. One GPU job of these tools runs at a time
(a lock file shared by every process using this module); when a job needs GPU memory that is not free, the other
worker's models move to RAM, then this process's speech transcription worker ends; when that is still not enough and
other processes (other AI sessions' servers, background jobs) hold models on the GPU, they are asked to move their
idle ones off it and the job waits for the memory (up to LETITEDIT_GPU_WAIT_S, default 180 s) instead of loading
into a full GPU (see 'GPU room across processes' below; the result's 'gpu' says when it waited or stayed short).
Weights live under C:\LetItEdit\models. Times are seconds (source seconds for a file, timeline seconds for a project).
Every value used, defaults included, is in the result.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import atexit
import contextlib
import hashlib
import json
import math
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import letitedit.core.render_lock as render_lock
import letitedit.core.memory_room as memory_room

HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

ENVS = Path(os.environ.get('LETITEDIT_ENVS', (_SAI_ROOT + '\\envs')))
MODELS_PYTHON = Path(os.environ.get('LETITEDIT_MODELS_PYTHON', ENVS / 'models' / 'Scripts' / 'python.exe'))
VOICE_PYTHON = Path(os.environ.get('LETITEDIT_VOICE_PYTHON', ENVS / 'voice' / 'Scripts' / 'python.exe'))
MODELS_HOME = Path(os.environ.get('LETITEDIT_MODELS_HOME', (_SAI_ROOT + '\\models')))
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'models'
IDLE_S = float(os.environ.get('LETITEDIT_MODEL_IDLE', '600'))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

CLAP_MODEL = 'laion/clap-htsat-unfused'
VOICE_MODEL = 'ResembleAI/chatterbox (Chatterbox TTS, English)'
PART_ALIASES = {'voice': 'vocals', 'speech': 'vocals', 'dialogue': 'vocals'}
PART_NOTES = {
    'vocals': 'voices (speech and singing)',
    'drums': 'drums and percussion', 'bass': 'bass', 'other': 'everything else the model hears as music',
    'guitar': 'guitar', 'piano': 'piano',
    'music': 'the sum of every stem except vocals',
    'rest': 'the input minus vocals (vocals + rest = the input exactly)'}
WATERMARK = ('Chatterbox puts an inaudible watermark (Resemble AI Perth) in all audio it generates, marking it as '
             'AI-made; this file has it.')
VOICE_DEFAULTS = {'exaggeration': 0.5, 'cfg_weight': 0.5, 'temperature': 0.8, 'repetition_penalty': 1.2,
                  'min_p': 0.05, 'top_p': 1.0}

# Voice engines (voice(engine=...)). 'chatterbox' is the original worker (voice_worker.py); the others run
# voice_engine_worker.py in their own environment. Each: python, weights folder, model, licence, settings defaults,
# reference_max_s (the reference is cut at the last word ending before it; None: used whole), whether the reference's
# transcript is passed to the model, GPU MB to free before loading.
VOICE_ENGINE_DEFAULT = os.environ.get('LETITEDIT_VOICE_ENGINE', 'dots-tts')   # the blind-test pick, 2026-10-20
VOICE_ENGINE_NO_REFERENCE = 'chatterbox'   # the default when no reference is given (the model's own voice)
VOICE_ENGINES = {
    'chatterbox': {
        'model': VOICE_MODEL, 'licence': 'MIT (code and weights): https://huggingface.co/ResembleAI/chatterbox',
        'python': VOICE_PYTHON, 'dir': None, 'defaults': VOICE_DEFAULTS, 'reference_max_s': None,
        'uses_text': False, 'need_mb': 4000, 'watermark': True},
    'dots-tts': {
        'model': 'dots-studio/dots.tts-soar (2B)',
        'licence': 'Apache-2.0 (code and weights): https://huggingface.co/dots-studio/dots.tts-soar',
        'python': ENVS / 'voice_dots' / 'Scripts' / 'python.exe', 'dir': MODELS_HOME / 'dots-tts-soar',
        'defaults': {'num_steps': 10, 'guidance_scale': 1.2, 'speaker_scale': 1.5, 'language': 'en', 'dtype': 'auto'},
        'reference_max_s': 10.0, 'uses_text': True, 'need_mb': 6500, 'watermark': False},
}
for _name in ('dots-tts',):
    _over = os.environ.get('LETITEDIT_VOICE_' + _name.upper().replace('-', '_') + '_PYTHON')
    if _over:
        VOICE_ENGINES[_name]['python'] = Path(_over)

# Labels hear() scores against when the caller gives none. Plain descriptions; any list of your own works the same.
DEFAULT_LABELS = [
    # voices and people
    'a man speaking', 'a woman speaking', 'a child speaking', 'people talking', 'a crowd of people', 'whispering',
    'shouting', 'laughter', 'applause', 'cheering', 'singing', 'coughing', 'breathing', 'footsteps',
    # vehicles and road
    'a car engine idling', 'a car driving', 'a truck', 'a diesel engine', 'traffic', 'road noise inside a vehicle',
    'a motorcycle', 'a car horn', 'a siren', 'a train', 'an airplane', 'a helicopter', 'tires on gravel',
    # tools, machines, work
    'a power drill', 'an impact driver', 'a circular saw', 'an angle grinder', 'grinding metal', 'sanding',
    'hammering', 'metal clanking', 'a wrench ratcheting', 'an air compressor', 'a vacuum cleaner', 'an electric fan',
    'a fan blade hitting something', 'an air conditioner humming', 'a motor whirring', 'a generator',
    'rattling', 'squeaking', 'scraping', 'buzzing', 'clicking', 'beeping', 'typing on a keyboard', 'paper rustling',
    'plastic crinkling', 'a zipper', 'tape being pulled',
    # home and indoors
    'a door opening or closing', 'a door creaking', 'dishes clinking', 'water running from a tap',
    'a phone ringing', 'a notification sound', 'a television in the background', 'a radio playing',
    'a refrigerator hum', 'a clock ticking',
    # nature and outdoors
    'wind', 'wind noise on a microphone', 'rain', 'thunder', 'birds chirping', 'insects buzzing', 'crickets',
    'frogs', 'a dog barking', 'a cat meowing', 'a rooster', 'ocean waves', 'a stream or river', 'a waterfall',
    'a campfire crackling', 'leaves rustling', 'snow crunching',
    # room and recording
    'silence', 'a quiet room', 'room tone', 'a busy restaurant', 'an empty parking lot', 'an echoing room',
    'background hum', 'static noise', 'hiss', 'electrical buzz', 'microphone handling noise', 'distorted audio',
    'muffled sound',
    # music: genres
    'funk music', 'rock music', 'pop music', 'hip hop music', 'jazz', 'blues', 'country music', 'folk music',
    'electronic dance music', 'ambient music', 'classical music', 'orchestral music', 'cinematic music',
    'lo-fi music', 'reggae', 'soul music', 'metal music', 'indie music', 'acoustic music', 'chiptune music',
    # music: moods
    'upbeat music', 'happy music', 'sad music', 'calm music', 'relaxing music', 'tense music', 'dramatic music',
    'epic music', 'playful music', 'mysterious music', 'romantic music', 'dark music', 'groovy music',
    'inspiring music', 'nostalgic music', 'suspenseful music', 'quirky music',
    # music: instruments
    'acoustic guitar', 'electric guitar', 'bass guitar', 'piano', 'drums', 'a drum machine', 'synthesizer',
    'violin', 'strings', 'brass', 'saxophone', 'trumpet', 'organ', 'ukulele', 'harmonica', 'banjo', 'flute',
    'whistling', 'hand claps', 'a bell', 'a music box',
    # energy and shape
    'loud', 'quiet', 'high energy', 'low energy', 'fast tempo', 'slow tempo', 'a steady beat', 'building up',
    'fading out', 'a sudden loud sound', 'a steady background noise', 'an impact', 'a whoosh',
]


# ------------------------------------------------------------------ small helpers

def _ffmpeg():
    import letitedit.timeline.made as made
    return str(made.ffmpeg_exe())


def _duration(path):
    import letitedit.server.core_tools as core_tools
    return float(core_tools.probe(str(path)).get('duration') or 0)


_FP = {}


def _fingerprint(path, chunk=1 << 20):
    """A content key for a file: its size and three 1 MB samples (start, middle, end)."""
    st = os.stat(path)
    k = (str(Path(path).resolve()), st.st_size, st.st_mtime_ns)
    if k not in _FP:
        h = hashlib.sha256(str(st.st_size).encode())
        with open(path, 'rb') as f:
            for off in (0, max(0, st.st_size // 2 - chunk // 2), max(0, st.st_size - chunk)):
                f.seek(off)
                h.update(f.read(chunk))
        _FP[k] = h.hexdigest()[:20]
    return _FP[k]


def _range(path, start, end):
    dur = _duration(path)
    a = 0.0 if start is None else max(0.0, float(start))
    b = dur if end is None else float(end)
    if dur:
        b = min(b, dur)
    if b <= a:
        raise ValueError(f'end ({b}) must be after start ({a}); {Path(path).name} lasts {dur:.3f} s')
    return a, b


def _decode(src, wav, start, length, rate, channels, codec='pcm_s16le'):
    """The sound of src from start for length seconds as a WAV file."""
    args = [_ffmpeg(), '-v', 'error', '-nostdin', '-y']
    if start:
        args += ['-ss', f'{start:.3f}']
    args += ['-i', str(src)]
    if length is not None:
        args += ['-t', f'{length:.3f}']
    args += ['-vn', '-sn', '-dn', '-ac', str(channels), '-ar', str(rate), '-c:a', codec, str(wav)]
    r = subprocess.run(args, capture_output=True, text=True, errors='replace', creationflags=NO_WINDOW)
    if r.returncode != 0 or not os.path.exists(wav):
        raise ValueError(f'could not read sound from {src}: {(r.stderr or "").strip()[-400:]}')
    return str(wav)


def _wav_seconds(path):
    import wave
    try:
        with wave.open(str(path), 'rb') as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:  # noqa: BLE001 - float WAV: ask ffprobe
        import letitedit.server.core_tools as core_tools
        r = subprocess.run([str(core_tools.FFPROBE), '-v', 'error', '-show_entries', 'format=duration', '-of',
                            'csv=p=0', str(path)], capture_output=True, text=True, creationflags=NO_WINDOW)
        return float(r.stdout.strip() or 0)


def _new_dir(kind):
    d = CACHE / kind / f'{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _num(v, default, cast=float):
    return cast(default) if v is None else cast(v)


# ------------------------------------------------------------------ GPU turn (one job at a time, across processes)

_turn = threading.RLock()
_depth = threading.local()


def _gpu_lock_path():
    """One lock for the PC, whatever the cache (LETITEDIT_GPU_LOCK overrides); the GPU sharing files sit beside it."""
    return Path(os.environ.get('LETITEDIT_GPU_LOCK', (_SAI_ROOT + '\\cache\\models\\gpu.lock')))


@contextlib.contextmanager
def _gpu_turn(timeout=7200):
    with _turn:
        depth = getattr(_depth, 'n', 0)
        handle = None
        if depth == 0:
            try:
                import msvcrt
            except ImportError:      # not Windows: the thread lock only
                msvcrt = None
            if msvcrt is not None:
                lock = _gpu_lock_path()
                lock.parent.mkdir(parents=True, exist_ok=True)
                handle = os.open(str(lock), os.O_RDWR | os.O_CREAT)
                deadline = time.monotonic() + timeout
                while True:
                    try:
                        os.lseek(handle, 0, 0)
                        msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            os.close(handle)
                            raise TimeoutError('another process kept the model GPU lock for too long')
                        time.sleep(0.5)
        _depth.n = depth + 1
        try:
            yield
        finally:
            _depth.n = depth
            if handle is not None:
                try:
                    os.lseek(handle, 0, 0)
                    msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
                finally:
                    os.close(handle)


# ------------------------------------------------------------------ workers

class WorkerError(RuntimeError):
    def __init__(self, message, oom=False):
        super().__init__(message)
        self.oom = oom


class _Worker:
    """A long-lived model process spoken to over JSON lines (see model_worker.py / voice_worker.py)."""

    def __init__(self, name, python, script):
        self.name, self.python, self.script = name, Path(python), Path(script)
        self.proc = None
        self.q = None
        self.next = 1
        self.lock = threading.Lock()
        self.hello = None
        self.on_gpu = False
        self.started = None
        self.log = CACHE / 'logs' / f'{name}_worker.log'

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _env(self):
        env = dict(os.environ)
        env.update(getattr(self, 'extra_env', None) or {})
        env.update(HF_HOME=str(MODELS_HOME / 'hf'), TORCH_HOME=str(MODELS_HOME / 'torch'),
                   HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_PROGRESS_BARS='1', PYTHONIOENCODING='utf-8',
                   TOKENIZERS_PARALLELISM='false', TRANSFORMERS_VERBOSITY='error', PYTHONWARNINGS='ignore')
        return env

    def _start(self, timeout=300):
        if not self.python.exists():
            raise RuntimeError(f'the {self.name} environment is missing: {self.python}')
        self.log.parent.mkdir(parents=True, exist_ok=True)
        (MODELS_HOME / 'hf').mkdir(parents=True, exist_ok=True)
        (MODELS_HOME / 'torch').mkdir(parents=True, exist_ok=True)
        with open(self.log, 'a', encoding='utf-8') as log:
            log.write(f'\n--- {self.name} worker start {time.strftime("%Y-%m-%d %H:%M:%S")} ---\n')
            log.flush()
            p = render_lock.popen_worker([str(self.python), '-I', str(self.script), str(IDLE_S)], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=log, text=True, encoding='utf-8',
                                         errors='replace', creationflags=NO_WINDOW | getattr(self, 'extra_flags', 0),
                                         env=self._env(), cwd=str(MODELS_HOME))
        q = queue.Queue()

        def pump():
            for line in p.stdout:
                q.put(line)
            q.put(None)
        threading.Thread(target=pump, daemon=True).start()
        self.proc, self.q = p, q
        hello = self._read(timeout)
        if not hello or not hello.get('ready'):
            self.kill()
            raise RuntimeError(f'the {self.name} worker did not start; log: {self.log}\n{self.tail()}')
        self.hello, self.on_gpu, self.started = hello, hello.get('device') == 'cuda', time.time()
        memory_room.changed()          # a helper is alive here: a render short of memory may ask it to end

    def _read(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f'the {self.name} worker gave no answer in {timeout:.0f} s')
            try:
                line = self.q.get(timeout=min(left, 5.0))
            except queue.Empty:
                continue
            if line is None:
                return None
            line = line.strip()
            if line.startswith('{'):
                try:
                    return json.loads(line)
                except ValueError:
                    pass

    def tail(self, n=1500):
        try:
            return self.log.read_text(encoding='utf-8', errors='replace')[-n:]
        except OSError:
            return ''

    def kill(self):
        if self.proc is not None:
            with contextlib.suppress(Exception):
                self.proc.kill()
            self._close_pipes()
        self.proc = None
        self.on_gpu = False

    def _close_pipes(self):
        for pipe in (self.proc.stdin, self.proc.stdout):
            with contextlib.suppress(Exception):
                pipe.close()

    def detach(self):
        """Close the pipes: the worker sees the end of its input and exits by itself."""
        if self.proc is not None:
            self._close_pipes()
            self.proc = None

    def call(self, op, timeout=3600, **args):
        with self.lock:
            return self._call_locked(op, timeout=timeout, **args)

    def _call_locked(self, op, timeout=3600, **args):
        """call() for a caller that already holds self.lock (a job holds it from sizing the job to its end, so the
        GPU-sharing thread can't move this worker's model off the GPU in between)."""
        for attempt in (0, 1):
            if not self.alive():
                self._start()
            rid = self.next
            self.next += 1
            try:
                self.proc.stdin.write(json.dumps({'id': rid, 'op': op, **args}) + '\n')
                self.proc.stdin.flush()
                reply = self._read(timeout)
                while reply is not None and reply.get('id') != rid:
                    reply = self._read(timeout)
            except TimeoutError:
                self.kill()
                raise
            except OSError:
                reply = None
            if reply is None:                     # the process died (or had just exited idle): start a new one
                self.kill()
                if attempt:
                    raise RuntimeError(f'the {self.name} worker stopped during {op}; log: {self.log}\n{self.tail()}')
                continue
            self.on_gpu = bool(reply.get('on_gpu', self.on_gpu))
            if reply.get('error'):
                raise WorkerError(f'{self.name} worker, {op}: {reply["error"]}', oom=bool(reply.get('oom')))
            return reply

    def quit(self):
        if self.alive():
            with contextlib.suppress(Exception):
                self.call('quit', timeout=20)
            with contextlib.suppress(Exception):
                self.proc.wait(timeout=10)
        self.kill()


_WORKERS = {
    'models': _Worker('models', MODELS_PYTHON, HERE / 'model_worker.py'),
    'voice': _Worker('voice', VOICE_PYTHON, HERE / 'voice_worker.py'),
    'vision': _Worker('vision', MODELS_PYTHON, HERE / 'vision_worker.py'),
}
# T96: the same worker with no GPU, below normal priority and on 4 threads, for a short look while the PC is rendering:
# it needs neither the PC lock nor a GPU turn, so it doesn't wait behind anyone or disturb them.
_WORKERS['models-cpu'] = _Worker('models-cpu', MODELS_PYTHON, HERE / 'model_worker.py')
_WORKERS['models-cpu'].extra_env = {'CUDA_VISIBLE_DEVICES': '-1', 'OMP_NUM_THREADS': '4', 'MKL_NUM_THREADS': '4'}
_WORKERS['models-cpu'].extra_flags = 0x00004000 if os.name == 'nt' else 0      # BELOW_NORMAL_PRIORITY_CLASS
for _name, _e in VOICE_ENGINES.items():
    if _name != 'chatterbox':
        _w = _Worker('voice-' + _name, _e['python'], HERE / 'voice_engine_worker.py')
        _w.extra_env = {'LETITEDIT_VOICE_ENGINE': _name, 'LETITEDIT_VOICE_ENGINE_DIR': str(_e['dir'])}
        _WORKERS['voice-' + _name] = _w


@atexit.register
def _detach_all():
    for w in _WORKERS.values():
        w.detach()
    with _share['lock']:            # its workers end with their pipes: nothing held here any more
        _share['closing'] = True
        _share_remove('has')
        _share_remove('want')


# GPU memory (MB) a job needs when its models are not on the GPU yet (measured on an RTX 2070 SUPER, with margin)
NEED_MB = {('models', 'separate'): 1200, ('models', 'clap'): 1600, ('voice', 'speak'): 4000, ('vision', 'describe'): 4600}
NEED_MB.update({('voice-' + n, 'speak'): e['need_mb'] for n, e in VOICE_ENGINES.items() if n != 'chatterbox'})
WARM_NEED_MB = 700          # ... and when they are
WHISPER_MB = 5600           # speech.py's GPU transcriber (large-v3-turbo, ~5.4 GB measured) when it is not running yet


def _gpu_free_mb():
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
                           capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        return int(r.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001 - no NVIDIA tools: nothing to manage
        return None


# ------------------------------------------------------------------ GPU room across processes
#
# Every process using these tools (each AI session's MCP server, background jobs, scripts) has its own workers and its
# own speech worker (speech.py), and Windows does not fail a load that doesn't fit: it spills to shared system memory
# and everything on the GPU crawls. So the processes cooperate through small files beside the GPU lock:
#   gpu.has.<pid>    what that process holds on the GPU ({'models': {name: estimated MB}, 'busy': [...]}), kept fresh
#                    every GPU_RESPOND_S by a background thread that runs only while it holds something
#   gpu.want.<pid>   "I need need_mb MB": written by a process whose load does not fit even after its own models are
#                    off the GPU, refreshed while it waits, removed when it stops waiting
# A process holding models looks for others' requests every GPU_RESPOND_S (the thread) and at the end of each of its
# jobs and transcriptions; when there is one, its idle models move off the GPU (the workers' 'release') and its idle
# speech worker ends. A busy one is never interrupted: it gives way at the end of its job. It removes only its own files.
# The asking process waits (up to GPU_WAIT_S) while the memory is short and others still hold models, then loads; the
# job's 'gpu' report says how long it waited, whom it asked, and how short it still was. Every wait happens under the
# GPU turn, so two loads never race for the memory just freed; a process waiting for the turn asks for nothing (it
# would make the process ahead of it reload its model between back-to-back jobs). Files of processes no longer
# running, or not refreshed for GPU_SHARE_FRESH_S, are ignored. One process alone works as before, except that its
# speech worker no longer starts on top of its own idle models when the GPU lacks room (speech.py, gpu_load).

GPU_WAIT_S = float(os.environ.get('LETITEDIT_GPU_WAIT_S', '180'))     # the longest a load waits for others' memory
GPU_SHARE_FRESH_S = 30.0       # a has/want file not refreshed this long is ignored (its process hung or died)
GPU_RESPOND_S = 1.0            # how often a process holding models looks for requests
_share = {'thread': None, 'lock': threading.Lock(), 'written': None}


def _share_file(kind, pid=None):
    return _gpu_lock_path().parent / f'gpu.{kind}.{int(pid or os.getpid())}'


def _share_write(kind, data):
    f = _share_file(kind)
    tmp = f.with_name(f'{f.name}.{threading.get_ident()}.tmp')
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data), encoding='utf-8')
        os.replace(tmp, f)
        return True
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return False


def _share_touch(kind):
    with contextlib.suppress(OSError):
        os.utime(_share_file(kind))


def _share_remove(kind):
    with contextlib.suppress(OSError):
        _share_file(kind).unlink()


def _share_log(msg):
    with contextlib.suppress(Exception):
        f = CACHE / 'logs' / 'gpu_share.log'
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists() and f.stat().st_size > 2_000_000:
            f.unlink()
        with open(f, 'a', encoding='utf-8') as fh:
            fh.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} pid {os.getpid()}: {msg}\n')


def _peers(kind):
    """Other running processes' fresh gpu.<kind>.<pid> files: [{'pid', 'age_s', ...what they wrote}]."""
    d = _gpu_lock_path().parent
    try:
        names = os.listdir(d)
    except OSError:
        return []
    import letitedit.core.render_lock as render_lock
    pre, me, t, out = f'gpu.{kind}.', os.getpid(), time.time(), []
    for n in names:
        if not n.startswith(pre) or not n[len(pre):].isdigit() or int(n[len(pre):]) == me:
            continue
        pid = int(n[len(pre):])
        try:
            age = t - os.stat(d / n).st_mtime
            if age > GPU_SHARE_FRESH_S or not render_lock.pid_alive(pid):
                continue
            meta = json.loads((d / n).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        out.append({**(meta if isinstance(meta, dict) else {}), 'pid': pid, 'age_s': round(age, 1)})
    return out


def _speech():
    return sys.modules.get('letitedit.footage.speech')        # not imported: this process has no speech worker


def _whisper_alive():
    sp = _speech()
    p = sp._gpu.get('proc') if sp is not None else None
    return p is not None and p.poll() is None


def _worker_mb(name):
    sizes = [v for (n, _op), v in NEED_MB.items() if n == name]
    return max(sizes) if sizes else 1500


def _held():
    """What this process holds on the GPU now: ({name: estimated MB}, [names in a job right now])."""
    models, busy = {}, []
    for name, w in list(_WORKERS.items()):
        if w.alive() and w.on_gpu:
            models[name] = _worker_mb(name)
            if w.lock.locked():
                busy.append(name)
    if _whisper_alive():
        models['whisper'] = WHISPER_MB
        if _speech()._gpu['lock'].locked():
            busy.append('whisper')
    return models, busy


def _write_has(models, busy):
    """gpu.has.<pid> (the caller holds _share['lock']): rewritten when what is held changes, else touched."""
    data = {'pid': os.getpid(), 'models': models, 'busy': busy}
    if data != _share['written']:
        if _share_write('has', dict(data, updated=time.strftime('%Y-%m-%d %H:%M:%S'))):
            _share['written'] = data
    else:
        _share_touch('has')


def _hold_changed():
    """After models went onto or off the GPU here: gpu.has.<pid> says what this process holds (removed when nothing),
    and the responder thread runs while it holds something. ram.has.<pid> (memory_room) says which helpers are alive."""
    memory_room.changed()
    models, busy = _held()
    with _share['lock']:
        if not models or _share.get('closing'):
            _share_remove('has')
            _share['written'] = None
            return
        _write_has(models, busy)
        t = _share['thread']
        if t is None or not t.is_alive():
            t = threading.Thread(target=_responder, name='letitedit-gpu-share', daemon=True)
            _share['thread'] = t
            t.start()


def _responder():
    """While this process holds models on the GPU: keep gpu.has.<pid> fresh and give way to others' requests."""
    while True:
        time.sleep(GPU_RESPOND_S)
        try:
            wants = [] if _share.get('closing') else _peers('want')
            if wants:
                _yield_idle(wants)
            models, busy = _held()
            with _share['lock']:
                if not models or _share.get('closing'):
                    _share_remove('has')
                    _share['written'] = None
                    _share['thread'] = None
                    return
                _write_has(models, busy)
        except Exception as e:  # noqa: BLE001 - one bad round never ends the thread
            _share_log(f'responder: {type(e).__name__}: {e}')


def _yield_idle(wants=None):
    """Another process asked for GPU memory (wants: its requests, from _peers('want')): move this process's idle
    models off the GPU and end its idle speech worker. A busy one is left alone (it gives way at the end of its
    job). Returns the names released."""
    wants = _peers('want') if wants is None else wants
    out = []
    for name, w in list(_WORKERS.items()):
        if not (w.alive() and w.on_gpu) or not w.lock.acquire(blocking=False):
            continue
        try:
            if w.alive() and w.on_gpu:
                w._call_locked('release', timeout=300)
                out.append(name)
        except Exception as e:  # noqa: BLE001
            _share_log(f'could not release {name} for another process: {type(e).__name__}: {e}')
        finally:
            w.lock.release()
    if _stop_whisper(block=False):
        out.append('whisper')
    if out:
        _share_log(f'released {", ".join(out)} for ' + ', '.join(
            f"pid {p['pid']} ({p.get('what')}, {p.get('need_mb')} MB)" for p in wants))
        _hold_changed()
    return out


def _after_job():
    """At the end of a job or transcription here: give way when other processes asked for GPU memory, and keep
    gpu.has.<pid> up to date. Never raises."""
    try:
        wants = _peers('want')
        if wants:
            _yield_idle(wants)
        _hold_changed()
    except Exception as e:  # noqa: BLE001
        _share_log(f'after a job: {type(e).__name__}: {e}')


def _stop_whisper(block=True):
    """End this process's speech transcription worker (speech.py starts a new one on its next transcription).
    block=False: only when it is not transcribing right now. Returns True when one was running."""
    sp = _speech()
    if sp is None or not sp._gpu['lock'].acquire(blocking=block):
        return False
    try:
        p = sp._gpu.get('proc')
        running = p is not None and p.poll() is None
        if running:
            with contextlib.suppress(Exception):
                p.stdin.close()
                p.wait(timeout=20)
            with contextlib.suppress(Exception):
                p.kill()
        if p is not None:
            with contextlib.suppress(Exception):
                p.stdout.close()
        sp._gpu['proc'] = None
        return running
    finally:
        sp._gpu['lock'].release()


# ------------------------------------------------------------------ memory for a render (memory_room)
#
# An idle helper keeps its whole process: the vision helper of a review holds 8-9.5 GB of the PC's commit until it ends
# by itself after IDLE_S. A render that holds the PC lock and is short of memory asks (memory_room.make_room): this
# process's idle helpers end then, and start again on their next use. A helper in a job holds its lock and is left alone.

def _helpers_alive():
    """memory_room's view of this process's helpers: {name: {'pid', 'busy'}}."""
    out = {}
    for name, w in list(_WORKERS.items()):
        proc = w.proc
        if proc is not None and proc.poll() is None:
            out[name] = {'pid': proc.pid, 'busy': w.lock.locked()}
    sp = _speech()
    proc = sp._gpu.get('proc') if sp is not None else None
    if proc is not None and proc.poll() is None:
        out['whisper'] = {'pid': proc.pid, 'busy': sp._gpu['lock'].locked()}
    return out


def _end_locked(w):
    """End a helper whose lock the caller holds: asked to quit, then stopped. Its next call starts a new one."""
    with contextlib.suppress(Exception):
        w._call_locked('quit', timeout=5)
    with contextlib.suppress(Exception):
        w.proc.wait(timeout=10)
    w.kill()


def _end_idle_helpers():
    """Every helper of this process not in a job ends now (memory_room asked: a render needs the memory)."""
    ended = []
    for name, w in list(_WORKERS.items()):
        if not w.alive() or not w.lock.acquire(blocking=False):
            continue
        try:
            if w.alive():
                _end_locked(w)
                ended.append(name)
        finally:
            w.lock.release()
    if _stop_whisper(block=False):
        ended.append('whisper')
    if ended:
        _share_log(f'ended idle {", ".join(ended)}: a render needs the memory')
        _hold_changed()
    return ended


def _free_own(need_mb, keep=None, whisper=True, free=None):
    """This process's part of making room: the other workers' models move off the GPU, then (whisper=True) its speech
    transcription worker ends, until need_mb MB are free. Returns the free MB (None without nvidia-smi)."""
    free = _gpu_free_mb() if free is None else free
    if free is None or free >= need_mb:
        return free
    for w in _WORKERS.values():
        if w is not keep and w.alive() and w.on_gpu:
            w.call('release', timeout=300)
    free = _gpu_free_mb()
    if whisper and free is not None and free < need_mb and _whisper_alive():
        _stop_whisper()
        free = _gpu_free_mb()
    return free


def _ask_others(need_mb, free, rep, what=None):
    """Still short after this process's own models: when other processes hold models on the GPU, ask them for room
    (gpu.want.<pid>) and wait while the memory is short and they still hold something, up to GPU_WAIT_S."""
    peers = _peers('has')
    if not peers:
        rep.update(short_mb=need_mb - free, note=(
            f'{need_mb - free} MB short of the {need_mb} MB this needs on the GPU, and no other letitedit process '
            'holds models there (other programs use the rest): loading anyway, so Windows may use shared system '
            'memory, which is much slower'))
        return rep
    asked = {p['pid']: {'models': p.get('models'), 'busy': p.get('busy')} for p in peers}
    t0 = time.monotonic()
    _share_write('want', {'pid': os.getpid(), 'need_mb': need_mb, 'free_mb': free, 'what': what,
                          'since': time.strftime('%Y-%m-%d %H:%M:%S')})
    _share_log(f'{what}: needs {need_mb} MB, {free} MB free; asking ' + ', '.join(
        f'pid {k} {v["models"]}' for k, v in asked.items()))
    free0, quiet = free, 0
    try:
        while time.monotonic() - t0 < GPU_WAIT_S:
            time.sleep(0.5)
            _share_touch('want')
            free = _gpu_free_mb()
            if free is None or free >= need_mb:
                break
            peers = _peers('has')
            for p in peers:                     # the latest word of each process asked (what it holds, what's busy)
                asked[p['pid']] = {'models': p.get('models'), 'busy': p.get('busy')}
            quiet = 0 if peers else quiet + 1
            if quiet >= 2:            # nobody holds anything any more: what is left is not theirs to free
                break
    finally:
        _share_remove('want')
    waited = round(time.monotonic() - t0, 1)
    who = ', '.join(f'pid {k} ({", ".join(v["models"] or {})})' for k, v in asked.items())
    rep.update(free_mb_at_start=free, free_mb_before_wait=free0, waited_s=waited,
               asked=[{'pid': k, **v} for k, v in asked.items()])
    if free is not None and free < need_mb:
        rep.update(short_mb=need_mb - free, note=(
            f'waited {waited:.1f} s for other letitedit processes ({who}) to move models off the GPU; still '
            f'{need_mb - free} MB short of {need_mb} MB, so it loads anyway (Windows may use shared system memory, '
            'which is much slower)'))
    else:
        rep['note'] = f'waited {waited:.1f} s while other letitedit processes ({who}) moved idle models off the GPU'
    _share_log(f'{what}: {rep["note"]}')
    return rep


def _room(need_mb, keep=None, whisper=True, what=None):
    """Make need_mb MB free on the GPU for a load: this process's other models first (and, whisper=True, its speech
    worker), then other processes' idle ones (_ask_others). Returns {'free_mb_at_start' (free when the load starts),
    'needed_mb'} plus, when it waited or stayed short, 'waited_s', 'free_mb_before_wait', 'asked', 'short_mb', 'note'."""
    free = _gpu_free_mb()
    rep = {'free_mb_at_start': free, 'needed_mb': need_mb}
    if free is None or free >= need_mb:
        return rep
    free = _free_own(need_mb, keep=keep, whisper=whisper, free=free)
    rep['free_mb_at_start'] = free
    if free is None or free >= need_mb:
        return rep
    return _ask_others(need_mb, free, rep, what)


def _make_room(need_mb, keep=None, whisper=True):
    """Free GPU memory until need_mb MB are free (_room: this process's models, then other processes' idle ones).
    Returns the free MB (None without nvidia-smi)."""
    return _room(need_mb, keep=keep, whisper=whisper)['free_mb_at_start']


@contextlib.contextmanager
def gpu_load(need_mb, what=None):
    """Around a load that is not one of these workers' jobs (speech.py starting its whisper worker): unless the GPU
    has room for it and for the largest job here besides, take the GPU turn and make room (_room; this process's
    speech worker is the one loading, so it is not ended). Yields the room report."""
    free = _gpu_free_mb()
    if free is None or free >= need_mb + max(NEED_MB.values()):
        yield {'free_mb_at_start': free, 'needed_mb': need_mb}
        return
    with _gpu_turn():
        yield _room(need_mb, whisper=False, what=what)


# models each worker job needs (model_fetch manifest ids), fetched on first use with the worker's environment
JOB_MODELS = {('models', 'separate'): ['htdemucs'], ('models', 'clap'): ['clap-htsat-unfused'],
              ('models-cpu', 'clap'): ['clap-htsat-unfused'],
              ('voice', 'speak'): ['chatterbox'], ('voice-dots-tts', 'speak'): ['dots-tts-soar'], ('music', 'generate'): ['ace-step-1.5']}


GPU_ONLY_INSTEAD = {        # what needs no graphics card, for a job whose model is made for one
    ('music', 'generate'): 'Songs from the music library (letitedit_library, letitedit_soundtrack) and music written as '
                           'a score (letitedit_music_write) need none.',
    ('voice-dots-tts', 'speak'): "The voice engine 'chatterbox' runs on the processor (slower).",
}


def _gpu_only_refusal(name, op, models):
    """The plain fact when this PC has no graphics card that runs the local models (hardware.vision_unavailable) and
    one of the job's models is listed for graphics-card PCs only (the models manifest's tiers); else None. On the
    processor such a model runs in full precision: a long run that can fill the memory, after a download of GBs."""
    if not models:
        return None
    try:
        import letitedit.core.hardware as hardware
        if hardware.vision_unavailable() is None:
            return None
        import letitedit.core.model_fetch as model_fetch
        tiers = {e.get('id'): e.get('tiers') or [] for e in model_fetch.manifest().get('models', [])}
    except Exception:  # noqa: BLE001 - no reading or no manifest: as before
        return None
    gpu_only = [m for m in models if tiers.get(m) and 'cpu' not in tiers[m]]
    if not gpu_only:
        return None
    return (f"{name} {op}: its model ({', '.join(gpu_only)}) is made for an NVIDIA graphics card, and this PC has none "
            'that runs it. On the processor it would run for a long time and could fill the memory, so it was not '
            'started (nothing was downloaded). ' + GPU_ONLY_INSTEAD.get((name, op), '')).strip()


def _first_use(name, op, w, args):
    """Before a job: the worker's environment (built on first use) and the job's models (downloaded on first use);
    settings.json model_downloads 'ask' / 'never' turns both into an error naming the sizes (first_use.py). A model
    listed for graphics-card PCs only, on a PC without one: hardware.LocalModelUnavailable (_gpu_only_refusal)."""
    models = list(JOB_MODELS.get((name, op), ()))
    if (name, op) == ('models', 'separate') and args.get('model') not in (None, 'htdemucs'):
        models = []
    why = _gpu_only_refusal(name, op, models)
    if why:
        import letitedit.core.hardware as hardware
        raise hardware.LocalModelUnavailable(why, feature=f'{name} {op}')
    if name == 'vision' and (getattr(w, 'extra_env', None) or {}).get('LETITEDIT_VISION_MODEL',
                                                                       'Qwen/Qwen3.5-4B') == 'Qwen/Qwen3.5-4B':
        models.append('qwen3.5-4b')
    import letitedit.core.first_use as first_use
    first_use.need_for_python(w.python, models, feature=f'{name} {op}')


def _job(name, op, timeout=3600, **args):
    """Run op on a worker as the only GPU job of these tools, after making room for it on the GPU (_room: this
    process's other models, then other processes' idle ones). The reply's 'gpu' is the room report."""
    w = _WORKERS[name]
    _first_use(name, op, w, args)
    # the PC render lock first, then the GPU turn: that order everywhere (render_lock.model_slot)
    with render_lock.model_slot(f'{name} {op}') as lock, _gpu_turn():
        try:
            with w.lock:        # from sizing the job to its end, so the sharing thread can't release it in between
                if name == 'vision':
                    _vision_device_check(w)
                need = WARM_NEED_MB if (w.alive() and w.on_gpu) else NEED_MB.get((name, op), 1500)
                room = _room(need, keep=w, what=f'{name} {op}')
                try:
                    reply = w._call_locked(op, timeout=timeout, **args)
                except WorkerError as e:
                    if not e.oom:
                        raise
                    # out of GPU memory: everything else of this process off the GPU, this worker's cache cleared,
                    # one more try
                    _free_own(10 ** 6, keep=w)
                    w._call_locked('release', timeout=300)
                    reply = w._call_locked(op, timeout=timeout, **args)
            reply['gpu'] = room
            if lock.get('behind'):
                reply['render_lock'] = lock         # it waited behind a render: what and for how long
            return reply
        finally:
            _after_job()        # others asked for room meanwhile: this worker's model, idle now, gives way


HEAR_CPU_MAX_S = 60.0       # the most sound a look on the CPU takes when the PC is busy (measured: tests/t96/REPORT.md)


def _clap_job(wav, windows, texts, seconds):
    """The CLAP scores of hear. A free PC: on the GPU under the lock, as every model. A PC busy with someone else's job
    and a short range: on the CPU now, with no lock, since the sum is small and the queue can be many minutes long."""
    if seconds <= HEAR_CPU_MAX_S:
        i = render_lock.info()
        if i.get('held') and not i.get('stale') and not render_lock.lock_held_by(i.get('text') or '', render_lock.ancestors()):
            w = _WORKERS['models-cpu']
            _first_use('models-cpu', 'clap', w, {})
            with w.lock:
                reply = w._call_locked('clap', timeout=600, wav=wav, windows=windows, texts=texts)
            reply['device'] = 'cpu, not waiting behind ' + render_lock.behind_text(i)
            return reply
    return _job('models', 'clap', wav=wav, windows=windows, texts=texts)


NEED_MB_VISION = {'Qwen/Qwen3.5-4B': 4600, 'Qwen/Qwen3.5-2B': 2800}   # by vision model (2B: estimate, not measured)


def _vision_model(model=None):
    """The vision model repo: model, else LETITEDIT_VISION_MODEL, else hardware.vision_model() (settings.json by
    tier), else Qwen/Qwen3.5-4B. Sets it on the vision worker; a running worker with another model is ended first."""
    repo = model or os.environ.get('LETITEDIT_VISION_MODEL')
    if not repo:
        with contextlib.suppress(Exception):
            import letitedit.core.hardware as hardware
            repo = hardware.check()['settings'].get('vision_model')
            repo = None if repo in (None, 'auto') else repo
            repo = repo or hardware.vision_model()
    repo = repo or 'Qwen/Qwen3.5-4B'
    w = _WORKERS['vision']
    if w.alive() and (w.hello or {}).get('model') not in (None, repo):
        w.quit()
    w.extra_env = {'LETITEDIT_VISION_MODEL': repo}
    NEED_MB[('vision', 'describe')] = NEED_MB_VISION.get(repo, 4600)
    return repo


def _vision_refusal():
    """hardware.vision_unavailable(): the plain fact when this PC has no graphics card that runs the vision model,
    else None (also when the hardware can't be read: the worker's own device check stands behind it)."""
    try:
        import letitedit.core.hardware as hardware
        return hardware.vision_unavailable()
    except Exception:  # noqa: BLE001
        return None


def _vision_device_check(w):
    """Before a vision job: the worker must have found a CUDA device (its hello). A worker on the processor is ended
    and LocalModelUnavailable raised, so a card torch can't use never means an hour on the CPU."""
    import letitedit.core.hardware as hardware
    if os.environ.get(hardware.VISION_ON_CPU_ENV) == '1':
        return
    if not w.alive():
        w._start()
    if (w.hello or {}).get('device') == 'cuda':
        return
    _end_locked(w)
    raise hardware.LocalModelUnavailable(
        'the local picture model found no graphics card it can use (torch in the models environment sees no CUDA). '
        'On the processor it would take an hour or more and fill the memory, so it was not run. '
        f'{hardware.VISION_INSTEAD[0].upper()}{hardware.VISION_INSTEAD[1:]}.')


def describe(items, max_new_tokens=320, batch=2, timeout=7200, model=None):
    """What a local vision model (default Qwen3.5-4B, 4-bit; see _vision_model) sees: items = [{'images': [paths],
    'prompt': text}, ...] -> {'texts': [...], 'model', 'run_s', 'peak_mb', ...}. Used by shot_log.py.
    On a PC without a graphics card that runs it (hardware.vision_unavailable), raises
    hardware.LocalModelUnavailable at once with the plain fact: nothing is started or downloaded."""
    why = _vision_refusal()
    if why:
        import letitedit.core.hardware as hardware
        raise hardware.LocalModelUnavailable(why, feature='vision')
    _vision_model(model)
    return _job('vision', 'describe', timeout=timeout, items=items, max_new_tokens=int(max_new_tokens),
                batch=int(batch))


def release(whisper=True):
    """Every loaded model off the GPU (kept in RAM; the next job moves it back); whisper=True also ends this process's
    speech transcription worker (speech.py starts it again when it next transcribes). Returns {worker: released}."""
    out = {}
    with _gpu_turn():
        for name, w in _WORKERS.items():
            out[name] = bool(w.alive() and w.call('release', timeout=300).get('released'))
        if whisper:
            out['whisper'] = _whisper_alive()
            _stop_whisper()
    _hold_changed()
    return out


def status():
    """{worker: {'running', 'pid', 'device', 'on_gpu', 'memory'}} plus the GPU's own used/total MB and 'sharing':
    what this process holds on the GPU, what other letitedit processes hold ('others_hold') and ask for
    ('others_want'), and the room report of this process's last speech worker start ('whisper_start')."""
    out = {}
    for name, w in _WORKERS.items():
        row = {'running': w.alive(), 'python': str(w.python), 'log': str(w.log)}
        if w.alive():
            row.update(pid=w.proc.pid, device=(w.hello or {}).get('device'), on_gpu=w.on_gpu)
            with contextlib.suppress(Exception):
                row['memory'] = {k: v for k, v in w.call('memory', timeout=30).items() if k not in ('id', 'on_gpu')}
        out[name] = row
    with contextlib.suppress(Exception):
        r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.used,memory.total', '--format=csv,noheader,nounits'],
                           capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        gpu, used, total = [x.strip() for x in r.stdout.strip().splitlines()[0].split(',')]
        out['gpu'] = {'name': gpu, 'used_mb': int(used), 'total_mb': int(total)}
    with contextlib.suppress(Exception):
        sp = _speech()
        out['sharing'] = {'holds': _held()[0], 'others_hold': _peers('has'), 'others_want': _peers('want'),
                          'whisper_start': sp._gpu.get('room') if sp is not None else None,
                          'files': str(_gpu_lock_path().parent), 'log': str(CACHE / 'logs' / 'gpu_share.log')}
    return out


def stop():
    """End both worker processes (they start again on the next call)."""
    for w in _WORKERS.values():
        w.quit()
    _hold_changed()
    return {name: w.alive() for name, w in _WORKERS.items()}


# ------------------------------------------------------------------ loudness

def _loudness(wav, offset, every):
    import letitedit.review.checks as checks
    series, summary = checks.loudness_series(wav)       # a reading every 0.1 s: (t, momentary, short-term)
    rows, k, i = [], 1, 0
    while series and k * every <= series[-1][0] + 0.06:
        target = k * every
        while i + 1 < len(series) and abs(series[i + 1][0] - target) <= abs(series[i][0] - target):
            i += 1
        rows.append([round(offset + target, 2), round(series[i][2], 1)])
        k += 1
    return {'integrated_lufs': summary.get('integrated_lufs'), 'true_peak_dbfs': summary.get('true_peak_dbfs'),
            'range_lu': summary.get('range_lu'), 'short_term': rows}


# ------------------------------------------------------------------ separate

def _separate_folder(file, a, b, model, shifts, overlap):
    """Where separate() keeps the stems of this file content, range, model and settings."""
    key = hashlib.sha256(json.dumps([_fingerprint(file), round(a, 3), round(b, 3), model, int(shifts),
                                     float(overlap)]).encode()).hexdigest()[:24]
    return CACHE / 'separate' / key


def separate(file, start=None, end=None, parts=None, out_dir=None, model='htdemucs', shifts=None, overlap=None,
             loudness_every_s=None):
    """Split the sound of file (start-end, source seconds) into stems with Demucs.

    parts: any of 'vocals' (alias 'voice'), 'drums', 'bass', 'other' (+ 'guitar', 'piano' with htdemucs_6s), 'music'
    (every stem but vocals, summed) and 'rest' (the input minus vocals); None = all of them.
    Returns {'files': {part: WAV path (44.1 kHz stereo float)}, 'loudness': {part: {'integrated_lufs', 'true_peak_dbfs',
    'range_lu', 'short_term': [[source s, LUFS], ...]}}, 'model', 'seconds', 'settings', 'parts_available', ...}.
    Short-term readings are the 3 s ending at each time, every loudness_every_s s (-120 = digital silence).
    Results are cached by the file's content, the range, the model and its settings; out_dir gets copies.
    """
    t0 = time.monotonic()
    file = str(Path(file).resolve())
    a, b = _range(file, start, end)
    settings = {'shifts': _num(shifts, 1, int), 'overlap': _num(overlap, 0.25), 'split': True,
                'loudness_every_s': _num(loudness_every_s, 1.0), 'sample_rate': 44100, 'channels': 2}
    folder = _separate_folder(file, a, b, model, settings['shifts'], settings['overlap'])
    meta = folder / 'result.json'
    cached = meta.exists()
    if not cached:
        folder.mkdir(parents=True, exist_ok=True)
        wav = _decode(file, folder / 'input.wav', a, b - a, 44100, 2, codec='pcm_f32le')
        reply = _job('models', 'separate', wav=wav, out_dir=str(folder), model=model, shifts=settings['shifts'],
                     overlap=settings['overlap'])
        os.remove(wav)
        names = {k: Path(v).name for k, v in reply['files'].items()}
        loud = {k: _loudness(str(folder / v), a, settings['loudness_every_s']) for k, v in names.items()}
        info = {'files': names, 'loudness': loud, 'sources': reply['sources'], 'seconds': round(reply['seconds'], 3),
                'model_load_s': reply.get('load_s'), 'run_s': reply.get('run_s'), 'gpu_peak_mb': reply.get('gpu_peak_mb'),
                'loudness_every_s': settings['loudness_every_s']}
        tmp = meta.with_suffix('.tmp')
        tmp.write_text(json.dumps(info), encoding='utf-8')
        os.replace(tmp, meta)
    info = json.loads(meta.read_text(encoding='utf-8-sig'))
    available = list(info['files'])
    if info.get('loudness_every_s') != settings['loudness_every_s']:
        info['loudness'] = {k: _loudness(str(folder / v), a, settings['loudness_every_s']) for k, v in info['files'].items()}
    wanted = available if parts is None else [PART_ALIASES.get(p, p) for p in ([parts] if isinstance(parts, str) else parts)]
    unknown = [p for p in wanted if p not in available]
    if unknown:
        raise ValueError(f'unknown part(s) {unknown}; this model gives {available}')
    files = {p: str(folder / info['files'][p]) for p in wanted}
    if out_dir:
        od = Path(out_dir)
        od.mkdir(parents=True, exist_ok=True)
        for p in wanted:
            dst = od / f'{Path(file).stem}_{a:.2f}-{b:.2f}_{p}.wav'
            shutil.copyfile(files[p], dst)
            files[p] = str(dst)
    return {'file': file, 'start': round(a, 3), 'end': round(b, 3), 'files': files,
            'loudness': {p: info['loudness'][p] for p in wanted}, 'model': model, 'seconds': info['seconds'],
            'parts_available': available, 'parts': {p: PART_NOTES.get(p, p) for p in wanted}, 'settings': settings,
            'cached': cached, 'took_s': round(time.monotonic() - t0, 2),
            'model_load_s': None if cached else info.get('model_load_s'), 'gpu_peak_mb': info.get('gpu_peak_mb')}


# ------------------------------------------------------------------ hear

def _is_project(source):
    s = str(source)
    return s.strip().lower() in ('live', 'current', 'editor') or s.lower().endswith('.mlt') or Path(s).is_dir()


def hear(source, start=None, end=None, every_s=None, window_s=None, labels=None, top=None, spectrogram=False,
         out_dir=None, score=None, template=None):
    """Score windows of sound against text descriptions with CLAP (laion/clap-htsat-unfused, zero-shot).

    source: a media file (source seconds) or a project .mlt / 'live' (its mix, timeline seconds).
    A window_s-second window every every_s seconds from start to end is compared with each label in labels (your own
    descriptions; None = DEFAULT_LABELS). score: 'softmax' (each window's scores over labels_used sum to 1, at the
    model's own logit scale) or 'cosine' (similarity of the sound and text embeddings, -1..1, independent of the other
    labels). template: how a label is put to the model, '{}' standing for the label. top: labels per segment
    (highest first; 'all' or 0 = every label). spectrogram=True (or {width, height, fmin, floor_db}) also draws a PNG
    of the analysed sound (time axis in the same seconds as the segments, log frequency).
    Returns {'segments': [{'start', 'end', 'labels': [[label, score], ...]}], 'labels_used', 'model', 'audio' (the WAV
    analysed), 'spectrogram' (PNG path or None), 'settings', ...}.
    """
    t0 = time.monotonic()
    settings = {'window_s': _num(window_s, 2.0), 'score': score or 'softmax',
                'template': 'This is a sound of {}.' if template is None else str(template)}
    settings['every_s'] = _num(every_s, settings['window_s'])
    if settings['window_s'] <= 0 or settings['every_s'] <= 0:
        raise ValueError('window_s and every_s must be above 0')
    if settings['score'] not in ('softmax', 'cosine'):
        raise ValueError("score is 'softmax' or 'cosine'")
    if '{}' not in settings['template']:
        raise ValueError("template must contain '{}' where the label goes")
    used = list(DEFAULT_LABELS if labels is None else ([labels] if isinstance(labels, str) else labels))
    used = [str(x) for x in used if str(x).strip()]
    if not used:
        raise ValueError('labels is empty')
    n_top = len(used) if top in ('all', 0) else max(1, min(len(used), int(5 if top is None else top)))
    settings['top'] = n_top
    od = Path(out_dir) if out_dir else _new_dir('hear')
    od.mkdir(parents=True, exist_ok=True)
    if _is_project(source):
        import letitedit.review.checks as checks
        timeline, path = checks.resolve(source)
        fps = timeline.fps
        a = max(0.0, float(start or 0))
        b = timeline.seconds if end is None else min(float(end), timeline.seconds)
        if b <= a:
            raise ValueError(f'end ({b}) must be after start ({a}); the timeline lasts {timeline.seconds:.3f} s')
        first, last = round(a * fps), max(round(a * fps), round(b * fps) - 1)
        wav = str(od / f'mix_{a:.2f}-{b:.2f}.wav')
        checks.render_audio(str(path), wav, first, last)
        a, b = first / fps, (last + 1) / fps
        kind, src_name = 'project', str(path)
    else:
        src_name = str(Path(source).resolve())
        a, b = _range(src_name, start, end)
        wav = _decode(src_name, od / f'{Path(src_name).stem}_{a:.2f}-{b:.2f}.wav', a, b - a, 48000, 1)
        kind = 'file'
    length = _wav_seconds(wav)
    b = min(b, a + length)
    windows, k = [], 0
    while True:
        ws = round(k * settings['every_s'], 4)
        if ws >= (b - a) - 0.05:
            break
        windows.append([ws, round(min(ws + settings['window_s'], b - a), 4)])
        k += 1
    texts = [settings['template'].replace('{}', x) for x in used]
    reply = _clap_job(wav, windows, texts, b - a) if windows else {'cosine': [], 'logit_scale': None}
    scale = reply.get('logit_scale')
    segments = []
    for (ws, we), row in zip(windows, reply['cosine']):
        if settings['score'] == 'softmax':
            m = max(row)
            ex = [math.exp(scale * (v - m)) for v in row]
            tot = sum(ex)
            vals = [v / tot for v in ex]
        else:
            vals = row
        ranked = sorted(zip(used, vals), key=lambda kv: -kv[1])[:n_top]
        segments.append({'start': round(a + ws, 3), 'end': round(a + we, 3),
                         'labels': [[lab, round(v, 4)] for lab, v in ranked]})
    png = None
    if spectrogram:
        opts = spectrogram if isinstance(spectrogram, dict) else {}
        spec = {'width': int(opts.get('width', 1600)), 'height': int(opts.get('height', 480)),
                'fmin': float(opts.get('fmin', 40.0)), 'floor_db': float(opts.get('floor_db', 80.0))}
        png = _spectrogram(wav, od / (Path(wav).stem + '_spectrogram.png'), a, marks=[s['start'] for s in segments],
                           **spec)
        settings['spectrogram'] = {**spec, 'fft': 4096, 'frequency_axis': 'log',
                                   'colour': 'dB below the loudest bin, dark to bright'}
    settings.update(logit_scale=scale, model_window_max_s=reply.get('max_s'), padding=reply.get('padding'),
                    truncation=reply.get('truncation'), sample_rate=48000)
    return {'source': src_name, 'kind': kind, 'start': round(a, 3), 'end': round(b, 3), 'segments': segments,
            'labels_used': used, 'model': CLAP_MODEL, 'audio': str(wav), 'spectrogram': png,
            'times': 'timeline seconds' if kind == 'project' else 'source seconds', 'settings': settings,
            'took_s': round(time.monotonic() - t0, 2), 'model_load_s': reply.get('load_s'), 'gpu': reply.get('gpu'),
            **({'device': reply['device']} if reply.get('device') else {})}


_STOPS = [(0.0, (0, 0, 4)), (0.25, (60, 15, 110)), (0.5, (160, 40, 120)), (0.75, (245, 110, 60)), (1.0, (252, 253, 191))]


def _spectrogram(wav, png, t0, width=1600, height=480, marks=(), fmin=40.0, floor_db=80.0):
    """A PNG of the sound in wav: time across (labelled from t0), log frequency up, level as colour."""
    import wave
    import numpy as np
    from PIL import Image, ImageDraw
    with wave.open(str(wav), 'rb') as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    left, right, top, bottom = 64, 12, 12, 40
    W, H = max(50, width - left - right), max(50, height - top - bottom)
    nfft = 4096
    pad = np.pad(x, (nfft // 2, nfft // 2))
    centers = np.linspace(0, len(x), W, endpoint=False).astype(int) + nfft // 2
    idx = centers[:, None] + np.arange(-nfft // 2, nfft // 2)[None, :]
    idx = np.clip(idx, 0, len(pad) - 1)
    frames = pad[idx] * np.hanning(nfft)[None, :]
    mag = np.abs(np.fft.rfft(frames, axis=1))
    db = 20 * np.log10(mag + 1e-9)
    top_db = db.max()
    db = np.clip((db - (top_db - floor_db)) / floor_db, 0, 1)
    fmax = sr / 2
    freqs = fmin * (fmax / fmin) ** (np.arange(H)[::-1] / (H - 1))
    bins = np.clip(np.round(freqs / (sr / nfft)).astype(int), 0, mag.shape[1] - 1)
    img = db[:, bins].T                                           # (H, W), top row = highest frequency
    stops = np.array([s for s, _ in _STOPS])
    cols = np.array([c for _, c in _STOPS], dtype=np.float32)
    rgb = np.stack([np.interp(img, stops, cols[:, c]) for c in range(3)], axis=-1).astype(np.uint8)
    im = Image.new('RGB', (width, height), (18, 18, 22))
    im.paste(Image.fromarray(rgb, 'RGB'), (left, top))
    d = ImageDraw.Draw(im)
    secs = len(x) / sr
    step = next((s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if secs / s <= 16), 1200)
    k = math.ceil(t0 / step) * step
    while k <= t0 + secs + 1e-6:
        px = left + (k - t0) / secs * W
        d.line((px, top + H, px, top + H + 6), fill=(200, 200, 200))
        label = f'{int(k // 60)}:{k % 60:04.1f}' if k >= 60 else f'{k:g}s'
        tw = d.textlength(label)
        d.text((px + 2 if px + 2 + tw <= width else px - tw - 2, top + H + 8), label, fill=(220, 220, 220))
        k += step
    for m in marks:
        px = left + (m - t0) / secs * W
        d.line((px, top + H, px, top + H + 3), fill=(120, 200, 255))
    for f in (50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000):
        if fmin <= f <= fmax:
            py = top + (H - 1) * (1 - math.log(f / fmin) / math.log(fmax / fmin))
            d.line((left - 6, py, left, py), fill=(200, 200, 200))
            d.text((4, py - 6), f'{f // 1000}k' if f >= 1000 else str(f), fill=(220, 220, 220))
    d.text((4, top + H + 24), f'from {t0:.2f} s, {secs:.2f} s long; level: dB below the loudest bin (0 to -{floor_db:g})',
           fill=(150, 150, 160))
    im.save(png)
    return str(png)


# ------------------------------------------------------------------ voice

def _sentences(text, max_chars=300, min_chars=15):
    """Text cut into sentences; very short pieces join the next one, very long ones split at a comma or space."""
    text = ' '.join(str(text).split())
    raw = [s.strip() for s in re.findall(r'.+?(?:[.!?\u2026]+["\'\u201d\u2019)\]]*(?=\s|$)|$)', text) if s.strip()]
    merged = []
    for s in raw:
        if merged and len(merged[-1]) < min_chars:
            merged[-1] = merged[-1] + ' ' + s
        else:
            merged.append(s)
    if len(merged) > 1 and len(merged[-1]) < min_chars:
        merged[-2] = merged[-2] + ' ' + merged.pop()
    out = []
    for s in merged:
        while len(s) > max_chars:
            cut = max(s.rfind(', ', max_chars // 3, max_chars), s.rfind('; ', max_chars // 3, max_chars))
            cut = cut + 1 if cut > 0 else s.rfind(' ', 0, max_chars)
            if cut <= 0:
                cut = max_chars
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            out.append(s)
    return out


def _reference(reference):
    if reference is None:
        return None, None
    if isinstance(reference, (str, Path)):
        reference = {'clip': str(reference)}
    clip = str(Path(reference['clip']).resolve())
    a, b = _range(clip, reference.get('in'), reference.get('out'))
    key = hashlib.sha256(json.dumps([_fingerprint(clip), round(a, 3), round(b, 3)]).encode()).hexdigest()[:12]
    folder = CACHE / 'voice' / 'references'
    folder.mkdir(parents=True, exist_ok=True)
    wav = folder / f'{Path(clip).stem}_{a:.2f}-{b:.2f}_{key}.wav'
    if not wav.exists():
        tmp = folder / f'{wav.stem}.{uuid.uuid4().hex[:6]}.wav'
        _decode(clip, tmp, a, b - a, 24000, 1)
        os.replace(tmp, wav)
    return str(wav), {'clip': clip, 'in': round(a, 3), 'out': round(b, 3), 'seconds': round(b - a, 3),
                      'file': str(wav), 'model_reads': 'the first 10 s for the voice, the first 6 s as its speech prompt'}


def _reference_cut(ref_wav, ref_used, max_s, reference_text):
    """The reference for an engine that reads its transcript: cut at the last word ending at or before max_s
    seconds (when longer), and the words spoken in what is kept. reference_text given: used as is, no cut."""
    if reference_text:
        return ref_wav, str(reference_text), dict(ref_used, text=str(reference_text), text_from='given')
    import letitedit.footage.speech as speech
    ws = speech.cached_words(ref_wav)
    if ws is None:
        with render_lock.model_slot('speech'), _gpu_turn():   # the speech worker's start makes room for it (speech._ensure_gpu_worker)
            ws = speech.words(ref_wav)
    total = _wav_seconds(ref_wav)
    keep = ws
    cut = None
    if max_s is not None and total > max_s + 0.05:
        keep = [w for w in ws if w['e'] <= max_s] or ws[:1]
        cut = min(total, keep[-1]['e'] + 0.15)
        nxt = next((w['s'] for w in ws if w['s'] >= keep[-1]['e'] and w is not keep[-1]), None)
        if nxt is not None:
            cut = min(cut, max(keep[-1]['e'], nxt - 0.02))
        dst = Path(ref_wav).with_name(f'{Path(ref_wav).stem}_cut{cut:.2f}.wav')
        if not dst.exists():
            tmp = dst.with_name(f'{dst.stem}.{uuid.uuid4().hex[:6]}.wav')
            _decode(ref_wav, tmp, 0.0, cut, 24000, 1)
            os.replace(tmp, dst)
        ref_wav = str(dst)
    text = ' '.join(w['w'] for w in keep).strip()
    used = dict(ref_used, file=ref_wav, text=text, text_from=f'speech.words ({speech.GPU_MODEL})',
                seconds_used=round(cut if cut is not None else total, 3),
                cut_at_s=None if cut is None else round(cut, 3))
    return ref_wav, text, used


def voice(text, reference=None, out=None, exaggeration=None, cfg_weight=None, temperature=None, seed=None,
          repetition_penalty=None, min_p=None, top_p=None, pause_s=None, split=True, words=True, engine=None,
          engine_settings=None, reference_text=None, reference_max_s=None):
    """Speech of text in a voice, with zero-shot voice cloning by a local model.

    engine: 'chatterbox' (Resemble AI Chatterbox, MIT) or 'dots-tts' (dots.tts SOAR 2B, Apache-2.0). Default: 'dots-tts' with a reference (or LETITEDIT_VOICE_ENGINE), 'chatterbox' without one. Every
    engine other than 'chatterbox' needs a reference.
    reference: {clip, in, out} (seconds of someone speaking; any media file), a file path, or None for the model's own
    voice ('chatterbox' only). reference_text: what is said in the reference (read by dots-tts);
    None: transcribed with speech.words() and the reference cut at the last word ending before reference_max_s
    (default 10 for dots-tts; 0 = used whole).
    Chatterbox settings pass through: exaggeration, cfg_weight, temperature, repetition_penalty, min_p, top_p
    (temperature, top_p, repetition_penalty also reach dots-tts when it has them).
    engine_settings: dots-tts's settings, merged over its defaults (all reported in 'settings'):
      dots-tts {num_steps 10, guidance_scale 1.2, speaker_scale 1.5, language 'en', dtype 'auto'}
      dtype 'auto' = float16 on GPUs before Ampere, else bfloat16; or 'float16' | 'bfloat16' | 'float32'.
    seed makes a take repeatable (None: a random seed, reported). split=True speaks the text sentence by sentence and
    joins them with pause_s seconds of silence (default 0.3). out: the WAV to write (default: a file under the model
    cache). words=True transcribes the result with speech.words() for word timings (False: 'words' is None).
    Returns {'file', 'seconds', 'words': [{'w', 's', 'e', 'p'}] (transcribed from the file), 'sentences': [{'text',
    'start', 'end'}], 'reference_used', 'engine', 'engines', 'settings', 'seed', 'sample_rate', 'model', 'licence',
    'watermark', ...}.
    """
    t0 = time.monotonic()
    if not str(text or '').strip():
        raise ValueError('text is empty')
    if not engine:
        engine = VOICE_ENGINE_DEFAULT if reference is not None else VOICE_ENGINE_NO_REFERENCE
    engine = str(engine).strip().lower()
    if engine not in VOICE_ENGINES:
        raise ValueError(f'engine {engine!r}: one of {", ".join(VOICE_ENGINES)}')
    spec = VOICE_ENGINES[engine]
    pause = _num(pause_s, 0.3)
    seed = random.randrange(2**31) if seed is None else int(seed)
    sentences = _sentences(text) if split else [' '.join(str(text).split())]
    ref_wav, ref_used = _reference(reference)
    ref_text = None
    if engine == 'chatterbox':
        if engine_settings:
            raise ValueError("engine_settings are for the other engines; chatterbox takes exaggeration, cfg_weight, "
                             "temperature, repetition_penalty, min_p, top_p")
        given = {'exaggeration': exaggeration, 'cfg_weight': cfg_weight, 'temperature': temperature,
                 'repetition_penalty': repetition_penalty, 'min_p': min_p, 'top_p': top_p}
        settings = {k: float(VOICE_DEFAULTS[k] if v is None else v) for k, v in given.items()}
        key = hashlib.sha256(json.dumps([sentences, ref_used and _fingerprint(ref_wav), settings, seed, pause]).encode()).hexdigest()[:16]
        worker = 'voice'
    else:
        if ref_wav is None:
            raise ValueError(f'engine {engine!r} needs a reference: {{clip, in, out}} or a file of someone speaking')
        unknown = set(engine_settings or {}) - set(spec['defaults'])
        if unknown:
            raise ValueError(f'{engine} settings are {", ".join(spec["defaults"])} (got {", ".join(sorted(unknown))})')
        settings = {**spec['defaults'], **{k: v for k, v in (engine_settings or {}).items() if v is not None}}
        for k, v in (('temperature', temperature), ('top_p', top_p), ('repetition_penalty', repetition_penalty)):
            if v is not None and k in settings:
                settings[k] = float(v)
        if spec['uses_text']:
            max_s = spec['reference_max_s'] if reference_max_s is None else (float(reference_max_s) or None)
            ref_wav, ref_text, ref_used = _reference_cut(ref_wav, ref_used, max_s, reference_text)
        ref_used = dict(ref_used, model_reads={
            'dots-tts': 'all of it with its transcript (continuation)'}[engine])
        key = hashlib.sha256(json.dumps([engine, sentences, _fingerprint(ref_wav), ref_text, settings, seed,
                                         pause]).encode()).hexdigest()[:16]
        worker = 'voice-' + engine
    if out:
        dst = Path(out).resolve()
    else:
        dst = CACHE / 'voice' / f'voice_{key}.wav'
    cached = (not out) and dst.exists() and (dst.with_suffix('.json')).exists()
    if cached:
        reply = json.loads(dst.with_suffix('.json').read_text(encoding='utf-8-sig'))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        args = dict(sentences=sentences, reference=ref_wav, out=str(dst), pause_s=pause, seed=seed, settings=settings)
        if worker != 'voice':
            args['reference_text'] = ref_text
        reply = _job(worker, 'speak', **args)
        if not out:
            dst.with_suffix('.json').write_text(json.dumps(reply), encoding='utf-8')
        else:                       # a receipt beside a voice written where the caller asked: it is AI-made
            try:
                Path(str(dst) + '.json').write_text(json.dumps({'generated': True, 'kind': 'voice', 'engine': engine,
                                                                'model': (reply or {}).get('model')}, default=str),
                                                    encoding='utf-8')
            except OSError:
                pass
    t1 = time.monotonic()
    import letitedit.footage.speech as speech
    timed = None
    if words:
        ws = speech.cached_words(str(dst))
        if ws is None:
            with render_lock.model_slot('speech'), _gpu_turn():   # the speech worker's start makes room for it (speech._ensure_gpu_worker)
                ws = speech.words(str(dst))
        timed = [{'w': w['w'], 's': w['s'], 'e': w['e'], 'p': w.get('p', 1.0)} for w in ws]
    timings = {'generate_s': None if cached else reply.get('run_s'), 'transcribe_s': round(time.monotonic() - t1, 2)}
    return {'file': str(dst), 'seconds': reply['seconds'], 'words': timed, 'text': ' '.join(sentences),
            'sentences': reply['sentences'], 'reference_used': ref_used, 'engine': engine,
            'engines': {n: e['model'] for n, e in VOICE_ENGINES.items()},
            'settings': {**reply['settings'], 'pause_s': pause, 'split': bool(split)}, 'seed': seed,
            'sample_rate': reply['sample_rate'], 'model': spec['model'], 'licence': spec['licence'],
            'watermark': WATERMARK if spec['watermark'] else None, 'words_from': None if not words else (
                f'speech.words ({speech.GPU_MODEL}, GPU)' if speech._gpu.get('ok') else f'speech.words ({speech.MODEL})'),
            'cached': cached, 'took_s': round(time.monotonic() - t0, 2), 'timings': timings,
            'model_load_s': None if cached else reply.get('load_s'), 'gpu_peak_mb': reply.get('gpu_peak_mb'),
            'dtype': reply.get('dtype'), 'gpu': None if cached else reply.get('gpu')}


memory_room.register('model helpers', _helpers_alive, _end_idle_helpers)


def _main(argv):
    if len(argv) < 2 or argv[1] not in ('separate', 'hear', 'voice', 'release', 'status', 'stop'):
        print('usage: python model_tools.py separate|hear|voice|release|status|stop \'{"arg": value, ...}\'',
              file=sys.stderr)
        return 2
    args = json.loads(argv[2]) if len(argv) > 2 and argv[2].strip() else {}
    result = globals()[argv[1]](**args)
    print(json.dumps(result, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(_main(sys.argv))
