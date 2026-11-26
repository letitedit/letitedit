"""Word timings for any source file, transcribed locally and cached.

words(path, start, end) -> [{'w': 'word', 's': source_seconds, 'e': source_seconds}]
prepare(paths)          -> transcribe many files in one go (the footage scan uses this)

Transcription runs on the GPU when this PC has openai-whisper with CUDA (large-v3-turbo, kept loaded in a worker
process: about 20x faster than the CPU here); otherwise on the CPU with faster-whisper medium.en (int8).
Settings that worked on this footage: no VAD filter, no conditioning on previous text, no prompt.
Short files are transcribed whole once; long files (over 20 minutes) only around the requested window.
A file transcribed earlier by either engine is never transcribed again.
The GPU worker (about 5.4 GB) shares the GPU with model_tools' workers and other processes' (model_tools, 'GPU room
across processes'): before it starts, room is made for it (this process's idle models off the GPU, other letitedit
processes asked to move theirs, a bounded wait; the report is in _gpu['room']), and after each transcription it ends
when another process is waiting for GPU memory (the next transcription starts it again).
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import contextlib
import hashlib
import json
import re
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'transcripts'
FFMPEG = Path((_SAI_ROOT + '\\app\\ffmpeg.exe'))
FFPROBE = Path((_SAI_ROOT + '\\app\\ffprobe.exe'))
MODEL = os.environ.get('LETITEDIT_WHISPER_MODEL', 'medium.en')          # CPU model
GPU_MODEL_ID = 'whisper-large-v3-turbo'     # the better model's entry in the model list
CPU_MODEL_ID = 'faster-whisper-medium-en'    # its entry in the model list (models-manifest.json)
GPU_MODEL = os.environ.get('LETITEDIT_WHISPER_GPU_MODEL', 'large-v3-turbo')
# GPU whisper's Python: LETITEDIT_WHISPER_GPU_PYTHON, else <root>\envs\whisper_gpu (built by env_build.py), else
# the uv tool 'openai-whisper' in %APPDATA% (where the first one on the build PC lives).
GPU_PYTHON = os.environ.get('LETITEDIT_WHISPER_GPU_PYTHON') or next(
    (p for p in (os.path.join(os.environ.get('LETITEDIT_ENVS') or os.path.join(_SAI_ROOT, 'envs'), 'whisper_gpu',
                              'Scripts', 'python.exe'),
                 os.path.join(os.environ.get('APPDATA', ''), 'uv', 'tools', 'openai-whisper', 'Scripts', 'python.exe'))
     if os.path.exists(p)),
    os.path.join(os.environ.get('APPDATA', ''), 'uv', 'tools', 'openai-whisper', 'Scripts', 'python.exe'))
WORKER = _paths.BRIDGE / 'whisper_gpu_worker.py'
LONG = 20 * 60
NO_WINDOW = 0x08000000
_model = None
_gpu = {'proc': None, 'ok': None, 'next': 1, 'lock': threading.Lock(), 'device': None}


def _identity(path):
    st = os.stat(path)
    return hashlib.sha256(f'{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}'.encode()).hexdigest()[:16]


def _duration(path):
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    return float(r.stdout.strip() or 0)


# ------------------------------------------------------------------ engines

def _setting_cpu():
    """True when hardware.py (settings.json speech_engine, or 'auto' by the GPU's memory) picks the CPU."""
    try:
        import letitedit.core.hardware as hardware
        return hardware.speech_engine() == 'cpu'
    except Exception:  # noqa: BLE001 - no reading: try the GPU as before
        return False


def _gpu_model_folder():
    """Where the GPU model's file is, seeing to it first: whisper's own cache (None), or the model list's folder, fetched the first-use way (T76: the
    person is told, and model_downloads holds: whisper would otherwise fetch 1.6 GB by itself, unannounced). False when it can't be had: the CPU engine."""
    if _gpu.get('folder') is not None or GPU_MODEL != 'large-v3-turbo':
        return _gpu.get('folder')
    if (Path.home() / '.cache' / 'whisper' / f'{GPU_MODEL}.pt').is_file():
        return None
    try:
        import letitedit.core.first_use as first_use
        import letitedit.core.model_fetch as model_fetch
        first_use.need(models=[GPU_MODEL_ID], feature='Better speech model')
        _gpu['folder'] = str(model_fetch.ensure(GPU_MODEL_ID))
    except Exception as ex:  # noqa: BLE001 - downloads off, or the download failed: the CPU engine, and its own message
        print(f'[speech] {GPU_MODEL} not used: {ex}', file=sys.stderr, flush=True)
        _gpu['folder'] = False
    return _gpu['folder']


def _gpu_worker():
    """The running GPU worker process, starting it if needed; None when this PC can't transcribe on a GPU. Call it
    through _ensure_gpu_worker (the PC lock's model slot and room on the GPU first), never directly to start one."""
    g = _gpu
    if g['ok'] is False or os.environ.get('LETITEDIT_WHISPER_CPU') or _setting_cpu():
        return None
    p = g['proc']
    if p is not None and p.poll() is None:
        return p
    if not os.path.exists(GPU_PYTHON):
        g['ok'] = False
        return None
    folder = _gpu_model_folder()
    if folder is False:
        g['ok'] = False
        return None
    try:
        import letitedit.core.render_lock as render_lock
        p = render_lock.popen_worker([GPU_PYTHON, '-I', str(WORKER), GPU_MODEL, '600'] + ([folder] if folder else []),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                     encoding='utf-8', creationflags=NO_WINDOW)
        hello = json.loads(p.stdout.readline() or '{}')
    except Exception:  # noqa: BLE001
        g['ok'] = False
        return None
    if not hello.get('ready') or hello.get('device') != 'cuda':
        p.kill()
        g['ok'] = False         # no CUDA: the CPU engine is the better choice
        return None
    g.update(proc=p, ok=True, device=hello['device'])
    return p


def _ensure_gpu_worker():
    """The GPU worker, started first when it isn't running (None when this PC can't transcribe on a GPU). Before a
    start, room is made for it on the GPU: model_tools.gpu_load takes the GPU turn when memory is tight, moves this
    process's idle models off the GPU and asks other processes for theirs (bounded wait); the report goes to
    _gpu['room']. The turn is taken before this module's lock (the order model_tools' jobs use)."""
    p = _gpu['proc']
    if p is not None and p.poll() is None:
        return p
    if (_gpu['ok'] is False or os.environ.get('LETITEDIT_WHISPER_CPU') or not os.path.exists(GPU_PYTHON)
            or _setting_cpu()):
        with _gpu['lock']:
            return _gpu_worker()            # None (and ok=False when there is no GPU Python), as before
    _gpu_model_folder()     # a first-use download happens before the PC lock, so nobody waits on it
    import letitedit.core.render_lock as render_lock
    # loading the model puts it on the GPU: under the PC render lock, taken here (outside the fallbacks below, which
    # must never start the worker without it) and before the GPU turn
    with render_lock.model_slot('speech model load'):
        mt = None
        try:
            import letitedit.sound.model_tools as mt
            load = mt.gpu_load(mt.WHISPER_MB, what=f'speech transcription ({GPU_MODEL})')
        except Exception:  # noqa: BLE001 - no model_tools: start as before
            load = contextlib.nullcontext(None)
        try:
            with load as room:
                with _gpu['lock']:
                    p = _gpu_worker()
                if room is not None and p is not None:
                    _gpu['room'] = room
        except Exception:  # noqa: BLE001 - making room failed (or the GPU turn stayed taken for hours): start as before
            with _gpu['lock']:
                p = _gpu_worker()
    if mt is not None:
        with contextlib.suppress(Exception):
            mt._hold_changed()              # gpu.has.<pid> lists it; the sharing thread runs while it is up
    return p


def _share_after():
    """After a GPU transcription: when another process asked for GPU memory, this worker (idle now) ends."""
    mt = sys.modules.get('letitedit.sound.model_tools')
    if mt is not None:
        with contextlib.suppress(Exception):
            mt._after_job()


def _extract(path, wav, offset=0.0, length=None):
    args = [str(FFMPEG), '-v', 'error', '-y']
    if offset:
        args += ['-ss', f'{offset:.3f}']
    if length:
        args += ['-t', f'{length:.3f}']
    args += ['-i', str(path), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)]
    r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0 and os.path.exists(wav)


def _transcribe_gpu(wav):
    # one clip or window at a time under the PC render lock (a model never runs during a render), taken before the GPU turn
    import letitedit.core.render_lock as render_lock
    with render_lock.model_slot('speech transcription'):
        return _transcribe_gpu_locked(wav)


def _transcribe_gpu_locked(wav):
    for attempt in range(3):
        if _ensure_gpu_worker() is None:
            return None
        try:
            with _gpu['lock']:
                p = _gpu['proc']
                if (p is None or p.poll() is not None) and attempt < 2:
                    continue    # ended since (a job here made room, or idle): start it again with room made first
                p = _gpu_worker()
                if p is None:
                    return None
                rid = _gpu['next']
                _gpu['next'] += 1
                try:
                    p.stdin.write(json.dumps({'id': rid, 'wav': str(wav), 'language': 'en'}) + '\n')
                    p.stdin.flush()
                    reply = json.loads(p.stdout.readline() or '{}')
                except Exception:  # noqa: BLE001 - worker died: next call starts a new one
                    _gpu['proc'] = None
                    return None
                if reply.get('error') or 'words' not in reply:
                    return None
                return reply['words']
        finally:
            _share_after()
    return None


def _listening_english_only():
    """The person hears it while the English-only model listens; True when the card was changed (speech_language.py)."""
    if not MODEL.endswith('.en'):
        return False
    try:
        import letitedit.core.first_use as first_use
        import letitedit.app.progress_feed as progress_feed
        import letitedit.footage.speech_language as speech_language
        said = speech_language.up_front()
        if said:
            first_use.say_in_reply(said)
        progress_feed.note(speech_language.CARD)
        return True
    except Exception:  # noqa: BLE001 - words on a card never stop the work
        return False


def _card_back():
    try:
        import letitedit.app.progress_feed as progress_feed
        progress_feed.note(None)
    except Exception:  # noqa: BLE001
        pass


def english_only_line(paths):
    """The plain line for an AI when any of these files' transcript came from an English-only model; '' otherwise."""
    for path in ([paths] if isinstance(paths, (str, Path)) else paths):
        try:
            ident = _identity(str(path))
            f = _cached(ident)
            if f is None:
                hits = sorted(CACHE.glob(f'{ident}-*.json'))
                f = hits[0] if hits else None
            if f is not None and str(json.loads(f.read_text(encoding='utf-8-sig')).get('model', '')).endswith('.en'):
                import letitedit.footage.speech_language as speech_language
                return speech_language.LINE
        except (OSError, ValueError):
            continue
    return ''


def _english_line():
    import letitedit.footage.speech_language as speech_language
    return speech_language.LINE


def will_read_english_only():
    """A file not transcribed yet will be read by the English-only model. Starts nothing."""
    return MODEL.endswith('.en') and bool(_gpu['ok'] is False or os.environ.get('LETITEDIT_WHISPER_CPU') or _setting_cpu()
                                          or not os.path.exists(GPU_PYTHON))


def _transcribe_cpu(wav):
    told = _listening_english_only()
    try:
        return _transcribe_cpu_now(wav)
    finally:
        if told:
            _card_back()


def _transcribe_cpu_now(wav):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        threads = int(os.environ.get('LETITEDIT_WHISPER_CPU_THREADS') or 0) or max(2, (os.cpu_count() or 4) // 2)
        try:  # use the cached model without asking the internet for updates; download only the first time
            _model = WhisperModel(MODEL, device='cpu', compute_type='int8', cpu_threads=threads, local_files_only=True)
        except Exception:  # noqa: BLE001
            # T76: not on this PC. The first-use way, as other models: says what and how big first, keeps to model_downloads
            import letitedit.core.first_use as first_use
            import letitedit.core.model_fetch as model_fetch
            if MODEL == 'medium.en':
                first_use.need(models=[CPU_MODEL_ID], feature='Speech model, for a PC with no suitable graphics card (English only)')
                _model = WhisperModel(MODEL, device='cpu', compute_type='int8', cpu_threads=threads, local_files_only=True,
                                      download_root=str(Path(model_fetch.ensure(CPU_MODEL_ID)) / 'hub'))
            elif model_fetch._setting() != 'auto':
                raise RuntimeError(f"Listening to speech needs the {MODEL} speech model, and downloads are turned off "
                                   f"(settings.json model_downloads is '{model_fetch._setting()}').") from None
            else:
                _model = WhisperModel(MODEL, device='cpu', compute_type='int8', cpu_threads=threads)
    segments, _ = _model.transcribe(str(wav), word_timestamps=True, vad_filter=False,
                                    condition_on_previous_text=False, beam_size=5)
    out = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                out.append({'w': text, 's': round(w.start, 3), 'e': round(w.end, 3),
                            'p': round(float(getattr(w, 'probability', 1.0)), 2)})
    return out


PRONOUNS = {'i': 'I', "i'm": "I'm", "i've": "I've", "i'll": "I'll", "i'd": "I'd"}


def tidy(ws, pause=0.7):
    """The GPU model sometimes returns a clip in lowercase without punctuation. When it does, restore the basics
    captions need: 'I', a capital after a long pause or a full stop, and a full stop before a long pause."""
    if not ws:
        return ws
    punct = sum(1 for w in ws if w['w'][-1:] in '.,?!') / len(ws)
    caps = sum(1 for w in ws if w['w'][:1].isupper()) / len(ws)
    if punct > 0.03 and caps > 0.03:
        return ws
    out = []
    for k, w in enumerate(ws):
        text = PRONOUNS.get(w['w'].lower(), w['w'])
        prev = out[-1] if out else None
        if prev is None or w['s'] - prev['e'] >= pause or prev['w'][-1:] in '.?!':
            text = text[:1].upper() + text[1:]
        nxt = ws[k + 1] if k + 1 < len(ws) else None
        if (nxt is None or nxt['s'] - w['e'] >= pause) and text[-1:] not in '.,?!':
            text += '.'
        out.append({**w, 'w': text})
    return out


def _transcribe(path, offset=0.0, length=None):
    """(words, engine) for a file or a window of it; times are source seconds."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / 'a.wav'
        if not _extract(path, wav, offset, length):
            # 'no-audio' (cached) only for a file with no sound track; a read that failed is never cached
            from letitedit.core import media
            if media.audio_streams(path) == 0:          # raises UnreadableMedia when the file can't be read at all
                return [], 'no-audio'
            raise media.unreadable(path, 'the sound' + (f' from {offset:.0f} s' if offset else ''))
        got, engine = _transcribe_gpu(wav), GPU_MODEL
        if got is None:
            got, engine = _transcribe_cpu(wav), MODEL
        else:
            got = tidy(got)
    for w in got:
        w['s'] = round(w['s'] + offset, 3)
        w['e'] = round(w['e'] + offset, 3)
    return got, engine


UNSURE = 0.45     # a word the model gives less than this probability is shown with (?)
REHEARD = '^'     # after a word the transcript had folded into a stretched one, heard by itself (word_reheard)


def unsure(w):
    """True for a word the transcriber wasn't sure of (its probability is under UNSURE)."""
    return float(w.get('p', 1.0)) < UNSURE


def stretched(w):
    """Seconds, for a word that lasts far longer than a word does (over a second, plus a tenth per letter), else 0.
    The transcriber then folded other sound into it: a pause, a restart ("without the LLM... without risking" came back
    as 'without' 4.9 s and 'risking' 2.2 s), or a hesitation; the words before and after are not where they seem."""
    try:
        d = float(w['e'] if 'e' in w else w['t1']) - float(w['s'] if 's' in w else w['t0'])
    except (KeyError, TypeError, ValueError):
        return 0.0
    letters = sum(c.isalnum() for c in str(w.get('w') or ''))
    return round(d, 1) if d > 1.0 + 0.1 * letters else 0.0


def shown(w):
    """A word as the transcript tools print it: '(?)' after one the transcriber wasn't sure of, '[4.9 s]' after one
    that lasts far longer than a word does (see `stretched`)."""
    long_s = stretched(w)
    return w['w'].strip() + ('(?)' if unsure(w) else '') + (f'[{long_s:g} s]' if long_s else '') + (REHEARD if w.get('reheard') else '')


def bursts(path, start, end, min_pause=0.2):
    """[(start, end)] source seconds of the sound inside a stretch of a file: where the level stands well over the quietest
    part of that stretch, with pauses of under min_pause closed. A word the transcript stretched over seconds (see
    `stretched`) shows here as several bursts with pauses between them, each a word, a false start or a breath."""
    import subprocess
    import numpy as np
    ffmpeg = _paths.CODE_ROOT / 'app' / 'ffmpeg.exe'
    a, b = float(start), float(end)
    raw = subprocess.run([str(ffmpeg), '-v', 'error', '-ss', f'{a:.3f}', '-t', f'{b - a:.3f}', '-i', str(path), '-vn', '-ac', '1',
                          '-ar', '16000', '-f', 's16le', '-'], capture_output=True, timeout=120).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(float)
    hop = 320                                              # 20 ms
    n = len(x) // hop
    if n < 3:
        return []
    db = 20 * np.log10(np.maximum(np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1)), 1.0) / 32768)
    on = db > max(np.percentile(db, 10) + 12.0, -45.0)
    out, k = [], 0
    while k < n:
        if on[k]:
            j = k
            while j < n and on[j]:
                j += 1
            out.append([a + k * 0.02, a + j * 0.02])
            k = j
        else:
            k += 1
    merged = []
    for s0, e0 in out:
        if merged and s0 - merged[-1][1] < min_pause:
            merged[-1][1] = e0
        else:
            merged.append([s0, e0])
    return [(round(s0, 2), round(e0, 2)) for s0, e0 in merged if e0 - s0 >= 0.06]


def shown_in(w, path):
    """`shown`, and for a stretched word of a file where the sound inside it is known: '[4.9 s: sound at 89.78-89.86,
    94.54-94.68, nothing between]': where the sound actually is inside the word's span."""
    long_s = stretched(w)
    if not long_s or w.get('reheard'):
        return shown(w)
    try:
        spans = bursts(path, w['s'], w['e'])
    except Exception:  # noqa: BLE001 - the plain marker still says it
        return shown(w)
    inside = ', '.join(f'{a:g}-{b:g}' for a, b in spans[:8]) or 'no sound'
    return (w['w'].strip() + ('(?)' if unsure(w) else '')
            + f'[{long_s:g} s: sound at {inside}' + (', nothing between' if len(spans) > 1 else '') + ']')


def engine():
    """Which engine transcribes on this PC: 'gpu (large-v3-turbo)' or 'cpu (medium.en)'."""
    import letitedit.core.render_lock as render_lock
    try:
        gpu = _ensure_gpu_worker() is not None
    except render_lock.Busy:       # a render has the PC: say which engine will do it, without loading anything now
        gpu = (_gpu['ok'] is not False and os.path.exists(GPU_PYTHON) and not _setting_cpu()
               and not os.environ.get('LETITEDIT_WHISPER_CPU'))
    return f'gpu ({GPU_MODEL})' if gpu else f'cpu ({MODEL})'


# ------------------------------------------------------------------ cache

def _cached(ident, suffix=''):
    """An existing transcript for this file (any engine), or None. One attached with attach() comes first.
    LETITEDIT_TRANSCRIPT=<variant> (an engine name such as large-v3-turbo or medium.en, or 'own') uses only that
    variant, so a test round can compare transcripts instead of silently sharing whichever came first."""
    want = os.environ.get('LETITEDIT_TRANSCRIPT', '').strip()
    if want:
        f = CACHE / f'{ident}-{want}{suffix}.json'
        return f if f.exists() else None
    own = CACHE / f'{ident}-own.json'
    if own.exists():
        return own
    hits = sorted(CACHE.glob(f'{ident}-*{suffix}.json'))
    if suffix == '':
        hits = [h for h in hits if h.stem.count('-') == 1 or not h.stem.rsplit('-', 1)[-1].isdigit()]
    return hits[0] if hits else None


_file_locks = {}


def words(path, start=None, end=None):
    path = str(path)
    CACHE.mkdir(parents=True, exist_ok=True)
    ident = _identity(path)
    with _file_locks.setdefault(ident, threading.Lock()):   # a file is transcribed once even when asked twice at once
        return _words(path, ident, start, end)


RUN_ON_S = 0.04     # words closer than this have no pause between them to cut in
NOISY_DB = 25.0     # speech less than this over the room (median speech level vs median floor, 80-5000 Hz) is noisy


def over_room(path):
    """How far the speech stands over the room's own sound in a file (dB: the speech lane's median voiced level minus
    its median noise floor, 80-5000 Hz), or None. Phone and camera mics in a room or a vehicle give about 15-25 dB;
    under NOISY_DB the voice fix is worth trying (letitedit-finish FINISH-2)."""
    try:
        import letitedit.timing.prosody as prosody
        sp = prosody.analyse(str(path), transcribe=False)['lane']['speaker']
        return round(float(sp['speech_level_db']) - float(sp['noise_floor_db']), 1)
    except Exception:  # noqa: BLE001 - no speech lane
        return None


def gap_fact(path, start=None, end=None):
    """What plays between the words of a clip (a fact, no judgement): the stretch of the file from start to end in 0.1 s
    windows, leaving out every window within 0.15 s of a word, from the speech lane's word times and its 10 ms levels.
    Returns {'windows': n, 'median_db', 'p90_db'} (the median and the 90th percentile of the gap windows' level, each
    over the mean of the quietest tenth of all the windows: the room), or None when there is no speech lane or no gap."""
    try:
        import numpy as np
        import letitedit.timing.prosody as prosody
        lane = prosody.analyse(str(path), transcribe=False)['lane']
        if not lane['words'] and cached_words(str(path)):
            # the lane was cached before the file was transcribed (its cache doesn't know): measure it again
            lane = prosody.analyse(str(path), transcribe=False, refresh=True)['lane']
        hop, t0 = float(lane['hop_s']), float(lane['t0'])
        energy = np.asarray(lane['energy'], float)
        words = [(w['t0'], w['t1']) for w in lane['words']]
        if not words:
            return None                 # no words known: every window would count as a gap, speech included
        a = 0.0 if start is None else float(start)
        b = t0 + len(energy) * hop if end is None else float(end)
        n = max(1, int(round(0.1 / hop)))
        gaps, every, t = [], [], a
        while t + 0.1 <= b + 1e-9:
            i = int(round((t - t0) / hop))
            seg = energy[i:i + n]
            if i >= 0 and len(seg) == n:
                level = float(10 * np.log10(np.mean(10 ** (seg / 10))))
                every.append(level)
                if not any(t < we + 0.15 and t + 0.1 > wb - 0.15 for wb, we in words):
                    gaps.append(level)
            t += 0.1
        if not gaps or len(every) < 3:
            return None
        every.sort()
        room = float(np.mean(every[:max(3, len(every) // 10)]))
        return {'windows': len(gaps), 'median_db': round(float(np.median(gaps)) - room, 1),
                'p90_db': round(float(np.percentile(gaps, 90)) - room, 1)}
    except Exception:  # noqa: BLE001 - no speech lane
        return None


def gap_clause(path, start=None, end=None):
    """'gaps: 2 windows of 0.1 s, median 0.2 dB over the quietest tenth, 90th percentile 0.3 dB' or ''."""
    g = gap_fact(path, start, end)
    if not g:
        return ''
    return (f"gaps: {g['windows']} windows of 0.1 s, median {g['median_db']:.1f} dB over the quietest tenth, "
            f"90th percentile {g['p90_db']:.1f} dB")


def over_room_line(path, start=None, end=None):
    """'# sound: speech 20 dB over the room; gaps: ... (noisy ...)' for letitedit_words, or ''. start/end: the range
    asked for (the gaps clause is measured there; the speech level is the file's)."""
    d = over_room(path)
    if d is None:
        return ''
    gaps = gap_clause(path, start, end)
    return f"# sound: speech {d:.0f} dB over the room" + (f'; {gaps}' if gaps else '') + (
        ' (noisy: clean the voice, letitedit-finish FINISH-2)' if d < NOISY_DB else '')


def sound_words(path, start=None, end=None, cached=False, heard=False):
    """words() with each word's start and end moved onto its sound (the speech lane's measured edges: transcript
    word times often run over the pause after a word and touch the next word's), the transcript's own times as
    'asr_s'/'asr_e', and 'run_on': True when the word runs straight into the next with no pause to cut in (under
    RUN_ON_S). A word whose sound the lane can't find keeps the transcript's times and gets 'edge': 'transcript'.
    cached: only what is already transcribed (None when it isn't yet), like cached_words().
    heard: a stretched word is replaced by what that stretch says heard by itself (word_reheard): the words tool's view; nothing else changes."""
    ws = (cached_words if cached else words)(path, start, end)
    if ws is None:
        return None
    if heard:
        import letitedit.footage.word_reheard as word_reheard
        ws = word_reheard.overlay(path, ws, start, end, hear=not cached)
    try:
        import letitedit.timing.prosody as prosody
        lw = prosody.analyse(str(path), transcribe=False)['lane']['words']
    except Exception:  # noqa: BLE001 - no speech lane: the transcript's times
        return [dict(w, edge='transcript') for w in ws]
    by = {(round(float(x['asr_t0']), 2), round(float(x['asr_t1']), 2)): x for x in lw if x.get('asr_t0') is not None}
    out = []
    for w in ws:
        x = by.get((round(float(w['s']), 2), round(float(w['e']), 2)))
        if x and not x.get('quiet') and x.get('timing') != 'unreliable':
            out.append(dict(w, s=float(x['t0']), e=float(x['t1']), asr_s=w['s'], asr_e=w['e']))
        else:
            out.append(dict(w, edge='transcript'))
    for a, b in zip(out, out[1:]):
        if 'edge' not in a and 'edge' not in b:
            a['run_on'] = b['s'] - a['e'] < RUN_ON_S
    return out


def _stale_no_audio(f, path):
    """A cached 'no-audio' transcript for a file that does have a sound track: a failed read cached by an older
    letitedit. It is removed (and True returned), so the file is transcribed again."""
    if f is None or '-no-audio' not in f.name:
        return False
    from letitedit.core import media
    if media.audio_streams(path) == 0:
        return False
    f.unlink(missing_ok=True)
    return True


def _words(path, ident, start, end):
    dur = _duration(path)
    if not dur:
        from letitedit.core import media
        media.audio_streams(path)                       # a file that can't be read just now: UnreadableMedia
    start = 0.0 if start is None else max(0.0, float(start))
    end = dur if end is None else min(dur, float(end))
    if dur <= LONG:
        f = _cached(ident)
        if _stale_no_audio(f, path):
            f = _cached(ident)
        if f is None:
            got, eng = _transcribe(path)
            f = CACHE / f'{ident}-{eng}.json'
            f.write_text(json.dumps({'path': path, 'model': eng, 'words': got}), encoding='utf-8')
        ws = json.loads(f.read_text(encoding='utf-8-sig'))['words']
    else:
        # windows of 5 minutes, aligned, so repeated requests reuse them
        ws = []
        w0 = int(start // 300) * 300
        while w0 < end:
            f = _cached(ident, f'-{w0}')
            if _stale_no_audio(f, path):
                f = _cached(ident, f'-{w0}')
            if f is None:
                pad = 3.0
                a = max(0.0, w0 - pad)
                got, eng = _transcribe(path, offset=a, length=300 + 2 * pad)
                got = [w for w in got if w0 <= w['s'] < w0 + 300]
                f = CACHE / f'{ident}-{eng}-{w0}.json'
                f.write_text(json.dumps({'path': path, 'model': eng, 'window': w0, 'words': got}), encoding='utf-8')
            ws += json.loads(f.read_text(encoding='utf-8-sig'))['words']
            w0 += 300
    return [w for w in ws if start - 0.05 <= w['s'] < end]


def _srt_seconds(stamp):
    h, m, rest = stamp.replace(',', '.').split(':')
    return int(h) * 3600 + int(m) * 60 + float(rest)


def parse_own(words=None, srt=None):
    """Word timings from an outside transcript: `words` as [{'w', 's', 'e'}] (also 'word'/'text', 'start', 'end'),
    or SRT/WebVTT text, whose cue times are shared out across the cue's words by their length."""
    out = []
    if words:
        for w in words:
            text = str(w.get('w', w.get('word', w.get('text', '')))).strip()
            s, e = w.get('s', w.get('start')), w.get('e', w.get('end'))
            if text and s is not None and e is not None:
                out.append({'w': text, 's': round(float(s), 3), 'e': round(float(e), 3)})
    elif srt:
        cue = re.compile(r'(\d+:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})\s*-->\s*'
                         r'(\d+:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})[^\n]*\n(.*?)(?:\n\s*\n|\Z)', re.S)
        for a, b, text in cue.findall(srt.replace('\r\n', '\n') + '\n'):
            a = _srt_seconds(a if a.count(':') == 2 else '0:' + a)
            b = _srt_seconds(b if b.count(':') == 2 else '0:' + b)
            ws = re.sub(r'<[^>]+>', '', text).split()
            total = sum(len(w) for w in ws) or 1
            t = a
            for w in ws:
                d = (b - a) * len(w) / total
                out.append({'w': w, 's': round(t, 3), 'e': round(t + d, 3)})
                t += d
    out.sort(key=lambda w: w['s'])
    return out


def attach(path, words=None, srt=None, source='own'):
    """Use an outside transcript for this file from now on (every tool that reads what is said). None: drop it."""
    path = str(path)
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f'{_identity(path)}-own.json'
    if words is None and srt is None:
        f.unlink(missing_ok=True)
        return []
    ws = parse_own(words, srt)
    if not ws:
        raise ValueError('no words with times found: give words=[{w, s, e}] or SRT/WebVTT text')
    f.write_text(json.dumps({'path': path, 'model': f'own ({source})', 'words': ws}), encoding='utf-8')
    return ws


def variants(path):
    """Every transcript kept for this file: {variant: {'words': n, 'sha': short hash}}. Variants are never merged
    or overwritten, so a better transcript can be compared with the old one."""
    ident = _identity(str(path))
    out = {}
    for f in sorted(CACHE.glob(f'{ident}-*.json')):
        name = f.stem[len(ident) + 1:]
        data = f.read_bytes()
        try:
            n = len(json.loads(data)['words'])
        except (ValueError, KeyError):
            n = None
        out[name] = {'words': n, 'sha': hashlib.sha1(data).hexdigest()[:10]}
    return out


def cached_words(path, start=None, end=None):
    """Like words(), but only from what is already transcribed: None when the file (or that window) isn't yet."""
    path = str(path)
    try:
        ident = _identity(path)
    except OSError:
        return None
    f = _cached(ident)
    if f is not None:
        ws = json.loads(f.read_text(encoding='utf-8-sig'))['words']
    else:
        lo = 0.0 if start is None else max(0.0, float(start))
        hi = lo + 1 if end is None else float(end)
        if start is None and end is None:
            # the whole file, as words() gives it: every 5-minute window up to its end (it read only the first before)
            try:
                hi = max(hi, _duration(path))
            except (OSError, ValueError):
                pass
        ws, w0 = [], int(lo // 300) * 300
        while w0 < hi:
            f = _cached(ident, f'-{w0}')
            if f is None:
                return None
            ws += json.loads(f.read_text(encoding='utf-8-sig'))['words']
            w0 += 300
    lo = -1.0 if start is None else float(start)
    hi = float('inf') if end is None else float(end)
    return [w for w in ws if lo - 0.05 <= w['s'] < hi]


def prepare(paths):
    """Transcribe every file not yet in the cache (one model load for all of them). Returns {path: words count}."""
    out = {}
    for p in paths:
        try:
            out[str(p)] = len(words(p))
        except Exception:  # noqa: BLE001 - a file without audio or unreadable: skip it
            out[str(p)] = 0
    return out


def islands(ws, max_pause=0.75, pad_in=0.12, pad_out=0.3, lo=None, hi=None):
    """Group words into spoken spans separated by pauses longer than max_pause; returns [(a, b)] source seconds."""
    if not ws:
        return []
    groups = [[ws[0]]]
    for w in ws[1:]:
        if w['s'] - groups[-1][-1]['e'] > max_pause:
            groups.append([w])
        else:
            groups[-1].append(w)
    spans = []
    for g in groups:
        a = g[0]['s'] - pad_in
        b = g[-1]['e'] + pad_out
        if lo is not None:
            a = max(lo, a)
        if hi is not None:
            b = min(hi, b)
        if spans and a <= spans[-1][1] + 0.05:
            spans[-1][1] = max(spans[-1][1], b)
        elif b > a:
            spans.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in spans]
