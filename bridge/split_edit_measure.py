"""Measuring split edits and music in melt renders (used by test_split_edit.py and test_score_answer.py).

    render_audio(project, wav)          melt render of the mix (48 kHz float, stereo); renders of more than 30 s of
                                        timeline hold the PC render lock, as fix_post does (render_lock_over_s 30);
                                        shorter ones, like checks' frame and audio checks, don't
    render_stems(project, keep, wav)    the same with only some tracks' sound (checks._variant)
    decode(path)                        a source file's sound, decoded by ffmpeg (48 kHz float, stereo)
    align(rendered, r0, source, s0, n)  lag in samples of a rendered stretch against the source, and the correlation
    click(x, t)                         how much a sample-level discontinuity at t stands out (second difference)
    short_term(x)                       BS.1770 momentary loudness every 100 ms (400 ms windows)

Read-only on footage: sources are only decoded. Renders go wherever the caller says (tests use
C:\\LetItEdit\\cache\\split-edit-tests).
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import os
import subprocess
from pathlib import Path

import numpy as np

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_ROOT = os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)
MELT = os.path.join(_ROOT, 'app', 'melt.exe')
FFMPEG = os.path.join(_ROOT, 'app', 'ffmpeg.exe')
SR = 48000
NO_WINDOW = 0x08000000
_decoded = {}


LOCK_OVER_S = 30.0      # renders of more timeline than this hold the PC render lock (fix_post's render_lock_over_s)


def _seconds(project):
    try:
        import letitedit.timeline.timeline_model as tm
        return float(tm.load(project).seconds)
    except Exception:  # noqa: BLE001 - unknown length: take the lock
        return float('inf')


def _melt(args, name, timeout=None, seconds=None):
    """Run melt; a render that hangs (melt has deadlocked at start on this PC, using no CPU) is given up after a
    time scaled to its length and tried once more."""
    import contextlib
    import letitedit.core.render_lock as render_lock
    long_render = (seconds if seconds is not None else float('inf')) > LOCK_OVER_S
    if timeout is None:
        timeout = 1800 if seconds is None or seconds == float('inf') else max(120, 6 * seconds)
    for attempt in (1, 2):
        lock = (render_lock.slot(name, timeout_s=7200, poll_s=2, caller_pids=render_lock.ancestors()) if long_render
                else contextlib.nullcontext())
        try:
            with lock:
                r = subprocess.run([MELT, '-quiet', *[str(a) for a in args]], capture_output=True, text=True,
                                   errors='replace', timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            if attempt == 2:
                raise
            continue
        break
    if r.returncode != 0:
        raise RuntimeError(f'melt failed ({r.returncode}): {(r.stderr or r.stdout)[-800:]}')


def _read(wav):
    import soundfile
    y, sr = soundfile.read(str(wav), dtype='float32', always_2d=True)
    if sr != SR:
        raise RuntimeError(f'{wav}: {sr} Hz')
    return y


def render_audio(project, wav):
    """The project's mix as melt renders it (the export engine): 48 kHz float stereo."""
    _melt([project, '-consumer', f'avformat:{wav}', 'vn=1', 'video_off=1', 'acodec=pcm_f32le', 'ar=48000',
           'channels=2', 'real_time=-1'], f'split-edit test {Path(project).name}', seconds=_seconds(project))
    return _read(wav)


def render_stems(project, keep_names, wav):
    """The mix with only the named tracks' sound (others hidden), as melt renders it."""
    import letitedit.review.checks as checks
    import letitedit.timeline.timeline_model as tm
    timeline = tm.load(project)
    keep = {t.index for t in timeline.tracks if t.name in set(keep_names)}
    variant = checks._variant(project, timeline, keep)
    try:
        return render_audio(variant, wav)
    finally:
        Path(variant).unlink(missing_ok=True)


def render_frames(project, frames, out_dir):
    """PNG frames at the given timeline frames, rendered by melt in one run (checks.render_frames)."""
    import letitedit.review.checks as checks
    import letitedit.timeline.timeline_model as tm
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return checks.render_frames(tm.load(project), project, frames, out_dir)     # a few frames: no lock, as checks


def decode(path):
    key = str(path)
    if key not in _decoded:
        raw = subprocess.run([FFMPEG, '-v', 'error', '-i', key, '-vn', '-ac', '2', '-ar', str(SR), '-f', 'f32le', '-'],
                             capture_output=True, check=True, creationflags=NO_WINDOW).stdout
        _decoded[key] = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()
    return _decoded[key]


def align(rendered, r0, source, s0, n, search=2400):
    """(lag, correlation): rendered[r0:r0+n] best matches source[s0+lag : s0+lag+n], |lag| <= search samples."""
    x = rendered[r0:r0 + n].mean(axis=1).astype(np.float64)
    lo, hi = max(0, s0 - search), min(len(source), s0 + n + search)
    y = source[lo:hi].mean(axis=1).astype(np.float64)
    if len(x) < n or len(y) < n:
        return None, 0.0
    m = 1 << int(np.ceil(np.log2(len(x) + len(y))))
    c = np.fft.irfft(np.fft.rfft(y, m) * np.conj(np.fft.rfft(x, m)), m)[:len(y) - len(x) + 1]
    e = np.convolve(y * y, np.ones(len(x)), 'valid')
    den = np.sqrt((x * x).sum() * np.maximum(e, 1e-20))
    r = c / den
    k = int(np.argmax(r))
    return lo + k - s0, float(r[k])


def residual_db(rendered, r0, source, s0, n):
    """Energy left after subtracting the source from the render (dB relative to the source)."""
    x = rendered[r0:r0 + n].mean(axis=1).astype(np.float64)
    y = source[s0:s0 + n].mean(axis=1).astype(np.float64)
    if len(x) < n or len(y) < n:
        return None
    return float(10 * np.log10(((x - y) ** 2).sum() / max((y * y).sum(), 1e-20) + 1e-20))


def present_db(rendered, r0, source, s0, n):
    """How much of a source stretch is in the render there (dB; 0 = all of it, -40 = practically none): the
    least-squares gain of the source in the render, so other sounds in the mix don't count."""
    x = rendered[r0:r0 + n].mean(axis=1).astype(np.float64)
    y = source[s0:s0 + n].mean(axis=1).astype(np.float64)
    if len(x) < n or len(y) < n or (y * y).sum() < 1e-12:
        return None
    g = (x * y).sum() / (y * y).sum()
    return float(20 * np.log10(abs(g) + 1e-6))


def click(x, t_s, half_ms=3.0, around_ms=400.0):
    """How much the largest second difference within +-half_ms of t stands out against the same measure in
    6 ms windows over +-around_ms (median of them): about 1-2 where nothing happens, much more on a click."""
    mono = x.mean(axis=1).astype(np.float64) if x.ndim > 1 else x.astype(np.float64)
    d2 = np.abs(np.diff(mono, 2))
    c = int(round(t_s * SR))
    h = int(SR * half_ms / 1000)
    a = int(SR * around_ms / 1000)
    lo, hi = max(0, c - a), min(len(d2), c + a)
    peak = d2[max(0, c - h):c + h].max(initial=0.0)
    wins = [d2[k:k + 2 * h].max() for k in range(lo, hi - 2 * h, 2 * h) if abs(k + h - c) > 4 * h]
    base = float(np.median(wins)) if wins else 0.0
    return float(peak / base) if base > 0 else float('inf') if peak > 0 else 0.0


def kpower(x, hop_s=0.1):
    """K-weighted power of every 100 ms (BS.1770, channels summed)."""
    import letitedit.sound.music as music
    from scipy.signal import lfilter
    (b1, a1), (b2, a2) = music._k_weighting(SR)
    z = lfilter(b2, a2, lfilter(b1, a1, x.astype(np.float64), axis=0), axis=0)
    hop = int(SR * hop_s)
    n = len(z) // hop
    return (z[:n * hop] ** 2).reshape(n, hop, -1).mean(axis=1).sum(axis=1)


def momentary(x):
    """(times of the 400 ms windows' centres, LUFS) every 100 ms."""
    p = kpower(x)
    if len(p) < 4:
        return np.zeros(0), np.zeros(0)
    blocks = np.convolve(p, np.ones(4) / 4, mode='valid')
    return (np.arange(len(blocks)) + 2) / 10.0, -0.691 + 10 * np.log10(np.maximum(blocks, 1e-12))


def level_over(x, a, b):
    """Mean power level (LUFS-like, K-weighted) of x between a and b seconds."""
    p = kpower(x)
    seg = p[int(a * 10):max(int(a * 10) + 1, int(b * 10))]
    return float(-0.691 + 10 * np.log10(max(float(np.mean(seg)) if len(seg) else 0.0, 1e-12)))


def write_wav(path, y, sr=SR):
    import soundfile
    soundfile.write(str(path), y, sr, subtype='FLOAT')
    return path


def transcribe(wav):
    """Words of a short rendered stretch (the local whisper), times in seconds from its start."""
    import letitedit.footage.speech as speech
    got, _engine = speech._transcribe(str(wav))
    return got


def source_frame(clip, t, width, height):
    """A source file's frame at t seconds (accurate seek), as a grey numpy array of width x height."""
    raw = subprocess.run([FFMPEG, '-v', 'error', '-i', str(clip), '-ss', f'{max(0.0, t):.4f}', '-frames:v', '1',
                          '-vf', f'scale={width}:{height}', '-pix_fmt', 'gray', '-f', 'rawvideo', '-'],
                         capture_output=True, check=True, creationflags=NO_WINDOW).stdout
    return np.frombuffer(raw[:width * height], dtype=np.uint8).reshape(height, width).astype(np.float64)


def frame_distance(png, clip, t):
    """Mean absolute grey difference between a rendered frame and a source file's frame at t."""
    from PIL import Image
    im = Image.open(png).convert('L')
    a = np.asarray(im, dtype=np.float64)
    b = source_frame(clip, t, im.width, im.height)
    return float(np.abs(a - b).mean())
