"""The beat finder: Beat This! (Foscarin, Schlueter & Widmer, ISMIR 2024; checkpoint final0, MIT), run on the CPU with ONNX Runtime, which every install already has.

    available()            -> None when it can run here, else the plain reason it can't
    frames(y, sr=22050)    -> {'beat_act', 'down_act', 'fps', 'run_s', ...}: beat and downbeat probabilities every 20 ms of a mono signal at 22050 Hz

The model file ships in the installer: <root>\\models\\beat-finder\\ (made by tools\\music\\export_beat_finder.py). Nothing is downloaded. The spectrogram is the same sum as Beat This!'s torchaudio
one, in numpy; chunks and how they are joined are as in its inference.py (split_predict_aggregate, 1500 frames, border 6, keep_first). Measured against the PyTorch model in tests\\t72\\REPORT.md.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_ROOT = Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT))
MODEL_DIR = Path(os.environ.get('LETITEDIT_BEAT_FINDER') or _ROOT / 'models' / 'beat-finder')
MODEL_NAME = 'beat_this_final0_fp16.onnx'
SR, N_FFT, HOP, F_MIN, F_MAX, N_MELS, LOG_MULT = 22050, 1024, 441, 30.0, 11000.0, 128, 1000.0
FPS = 50.0
CHUNK, BORDER = 1500, 6
THREADS = 4          # the PC rule
_session = {}


def model_path() -> Path:
    return MODEL_DIR / MODEL_NAME


def available():
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return 'ONNX Runtime is missing from the tools (Repair letitedit\'s Python tools puts it back)'
    if not model_path().is_file():
        return f'the beat finder\'s model file is missing ({model_path()}): reinstalling letitedit puts it back'
    return None


def _mel_bank():
    def hz_to_mel(f):
        f = np.asarray(f, float)
        linear = 3.0 * f / 200.0
        log = 15.0 + 27.0 / np.log(6.4) * np.log(np.maximum(f, 1e-9) / 1000.0)
        return np.where(f >= 1000.0, log, linear)

    def mel_to_hz(m):
        m = np.asarray(m, float)
        return np.where(m >= 15.0, 1000.0 * 6.4 ** ((m - 15.0) / 27.0), 200.0 * m / 3.0)
    freqs = np.linspace(0, SR // 2, N_FFT // 2 + 1)
    pts = mel_to_hz(np.linspace(hz_to_mel(F_MIN), hz_to_mel(F_MAX), N_MELS + 2))
    diff = pts[1:] - pts[:-1]
    slopes = pts[None, :] - freqs[:, None]
    down = -slopes[:, :-2] / diff[:-1]
    up = slopes[:, 2:] / diff[1:]
    return np.maximum(0.0, np.minimum(down, up)).astype(np.float32)


def spectrogram(y) -> np.ndarray:
    """(frames, 128) log-mel, as Beat This!'s LogMelSpect: centred reflect-padded STFT, magnitudes over sqrt(n_fft), slaney mel, log1p(1000 x)."""
    y = np.asarray(y, np.float32)
    pad = N_FFT // 2
    x = np.pad(y, pad, mode='reflect')
    n = 1 + (len(x) - N_FFT) // HOP
    window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)
    bank = _mel_bank()
    out = np.empty((n, N_MELS), np.float32)
    for a in range(0, n, 2048):             # in blocks, so a long song doesn't hold every frame's spectrum at once
        b = min(n, a + 2048)
        idx = np.arange(N_FFT)[None, :] + HOP * np.arange(a, b)[:, None]
        mag = np.abs(np.fft.rfft(x[idx] * window, axis=1)).astype(np.float32) / np.sqrt(N_FFT, dtype=np.float32)
        out[a:b] = np.log1p(LOG_MULT * (mag @ bank))
    return out


def _load():
    path = str(model_path())
    if path not in _session:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = THREADS
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3
        # no memory arena: the beat finder runs inside the tool server's own process, where an arena kept the most
        # any song ever needed for good (T288: GBs after a listing of new songs)
        opts.enable_cpu_mem_arena = False
        _session[path] = ort.InferenceSession(path, opts, providers=['CPUExecutionProvider'])
    return _session[path]


def _pad(chunk, left, right):
    if not left and not right:
        return chunk
    return np.pad(chunk, ((left, right), (0, 0)))


def logits(spect) -> tuple[np.ndarray, np.ndarray]:
    """Frame-wise beat and downbeat logits of a whole spectrogram."""
    n = len(spect)
    starts = np.arange(-BORDER, n - BORDER, CHUNK - 2 * BORDER)
    if n > CHUNK - 2 * BORDER:
        starts[-1] = n - (CHUNK - BORDER)
    sess = _load()
    beat, down = np.full(n, -1000.0, np.float32), np.full(n, -1000.0, np.float32)
    for start in reversed(starts.tolist()):        # earlier chunks overwrite later ones (keep_first)
        chunk = _pad(spect[max(start, 0):min(start + CHUNK, n)], max(0, -start), max(0, min(BORDER, start + CHUNK - n)))
        b, d = sess.run(['beat', 'downbeat'], {'spect': chunk[None].astype(np.float32)})
        b, d = b[0][BORDER:-BORDER], d[0][BORDER:-BORDER]
        lo = start + BORDER
        hi = min(n, lo + len(b))
        beat[lo:hi], down[lo:hi] = b[:hi - lo], d[:hi - lo]
    return beat, down


def peaks(logit) -> list:
    """Times of the probability's peaks, as Beat This!'s 'minimal' postprocessor: maxima within 70 ms over 0.5, neighbours merged."""
    v = np.asarray(logit, np.float64)
    n = len(v)
    pad = np.pad(v, 3, constant_values=-np.inf)
    window = np.stack([pad[i:i + n] for i in range(7)])
    idx = np.flatnonzero((v == window.max(axis=0)) & (v > 0))
    out, peak, count = [], None, 0
    for p in idx.astype(float):
        if peak is not None and p - peak <= 1:
            count += 1
            peak += (p - peak) / count
        else:
            if peak is not None:
                out.append(peak)
            peak, count = p, 1
    if peak is not None:
        out.append(peak)
    return [round(float(p) / FPS, 4) for p in out]


def frames(y, sr=SR) -> dict:
    if int(sr) != SR:
        raise ValueError(f'the beat finder takes {SR} Hz sound, not {sr}')
    t0 = time.time()
    spect = spectrogram(y)
    t1 = time.time()
    b, d = logits(spect)
    sig = lambda v: np.round(1.0 / (1.0 + np.exp(-np.clip(v.astype(np.float64), -50, 50))), 3).tolist()   # noqa: E731
    return {'beat_act': sig(b), 'down_act': sig(d), 'beats': peaks(b), 'downbeats': peaks(d), 'fps': FPS, 'spect_s': round(t1 - t0, 2), 'run_s': round(time.time() - t1, 2), 'model': MODEL_NAME, 'device': 'cpu (ONNX Runtime)'}
