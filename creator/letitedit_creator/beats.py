"""Beat detection for cutting on the music: onset strength (spectral flux) -> tempo (autocorrelation)
-> beat times (dynamic programming, Ellis 2007), plus downbeat guess (every 4th beat with the most
energy). Pure numpy/scipy, works on any audio file or a rendered timeline track."""

import numpy as np

from . import common, words as wordmod

SR = 22050
HOP = 512


def load(path, start_s=0.0, duration_s=None):
    """Mono float32 audio at 22.05 kHz via ffmpeg."""
    wav = common.WORK / f"beats-{common.sha1_file(path, limit=1 << 20)[:10]}-{start_s:.2f}-{duration_s}.wav"
    if not wav.exists():
        args = [common.ffmpeg(), "-v", "error", "-y", "-ss", f"{start_s:.3f}"]
        if duration_s:
            args += ["-t", f"{duration_s:.3f}"]
        common.run(args + ["-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(wav)])
    samples, rate = wordmod.load_wav(wav)
    return samples.astype(np.float32), rate


def onset_envelope(y, sr=SR):
    from scipy.signal import stft
    _, _, Z = stft(y, sr, nperseg=2048, noverlap=2048 - HOP, boundary=None)
    S = np.log1p(np.abs(Z) * 1000.0)
    # mel-ish weighting: emphasise kick/snare bands
    flux = np.maximum(0, np.diff(S, axis=1))
    env = flux.mean(axis=0)
    env = np.concatenate([[0], env])
    env -= np.convolve(env, np.ones(16) / 16, mode="same")       # local mean removal
    env = np.maximum(env, 0)
    return env / (env.std() + 1e-9)


