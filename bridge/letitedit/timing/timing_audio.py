"""Sound lane of the timing store (timing_signals): `audio`, every 10 ms from t = 0.

  loudness_db  K-weighted loudness (ITU-R BS.1770 weighting, channels summed) over a centred `loudness_window_s`
               window (default 0.4 s, the EBU 'momentary' length), in LUFS
  level_db     plain RMS level over a centred `level_window_s` window (default 0.03 s), dBFS: fast changes
  flux         spectral flux: the summed rise of the log-magnitude spectrum (mono mix, `fft` samples, Hann window)
               from one 10 ms step to the next, per bin
  onsets       [{t, f, strength, level_db}] peaks of the flux above its local median + `onset_k` x local MAD
               (within +-`onset_window_s`), at least `onset_min_gap_s` apart, where the sound is above
               `onset_floor_db`; strength = (peak - local median) / local MAD

Sound comes from the project's preview render (its .wav, sample-exact) or the video file's own sound (48 kHz).
The file is read in blocks, so long files don't need much memory.
"""
from __future__ import annotations

import math

import numpy as np

import letitedit.timing.timing_signals as ts

AUDIO_DEFAULTS = {
    'hop_s': 0.01,
    'loudness_window_s': 0.4,
    'level_window_s': 0.03,
    'fft': 1024,
    'onset_k': 4.0,
    'onset_window_s': 0.5,
    'onset_min_gap_s': 0.05,
    'onset_floor_db': -55.0,
    'block_s': 60.0,
}

# ITU-R BS.1770 K-weighting at 48 kHz
_K1 = (np.array([1.53512485958697, -2.69169618940638, 1.19839281085285]),
       np.array([1.0, -1.69065929318241, 0.73248077421585]))
_K2 = (np.array([1.0, -2.0, 1.0]), np.array([1.0, -1.99004745483398, 0.99007225036621]))


def analyse(wav, st=None, t0=0.0, t1=None):
    """The audio lane's numbers for a WAV file (48 kHz expected; other rates are measured with the 48 kHz
    weighting and a warning). t0/t1: the part of the file to measure (seconds)."""
    import soundfile
    from scipy.signal import lfilter, lfilter_zi
    st = dict(AUDIO_DEFAULTS, **(st or {}))
    info = soundfile.info(str(wav))
    sr = int(info.samplerate)
    warnings = []
    if sr != 48000:
        warnings.append(f'sample rate {sr} Hz: K-weighting coefficients are those for 48 kHz')
    hop = int(round(float(st['hop_s']) * sr))
    nfft = int(st['fft'])
    total = info.frames
    a0 = int(round(t0 * sr))
    a1 = total if t1 is None else min(total, int(round(t1 * sr)))
    nh = max(0, (a1 - a0) // hop)
    P = np.zeros(nh)              # K-weighted power per hop (channels summed)
    R = np.zeros(nh)              # plain power per hop (channels averaged)
    flux = np.zeros(nh)
    win = np.hanning(nfft).astype(np.float32)
    zi1 = zi2 = None
    prev_mag = None
    block = max(hop * 100, int(float(st['block_s']) * sr) // hop * hop)
    half = nfft // 2
    pos = a0
    h = 0
    with soundfile.SoundFile(str(wav)) as f, soundfile.SoundFile(str(wav)) as g:
        f.seek(a0)
        while pos < a1 and h < nh:
            n = min(block, a1 - pos)
            y = f.read(n, dtype='float32', always_2d=True)
            if y.shape[0] == 0:
                break
            blk0 = pos
            pos += y.shape[0]
            ch = y.shape[1]
            if zi1 is None:
                zi1 = [lfilter_zi(*_K1) * 0.0 for _ in range(ch)]
                zi2 = [lfilter_zi(*_K2) * 0.0 for _ in range(ch)]
            kw = np.empty_like(y)
            for c in range(ch):
                z, zi1[c] = lfilter(_K1[0], _K1[1], y[:, c], zi=zi1[c])
                kw[:, c], zi2[c] = lfilter(_K2[0], _K2[1], z, zi=zi2[c])
            m = y.shape[0] // hop
            hh = min(m, nh - h)
            if hh <= 0:
                break
            kp = (kw[:hh * hop] ** 2).sum(axis=1).reshape(hh, hop).mean(axis=1)
            rp = (y[:hh * hop] ** 2).mean(axis=1).reshape(hh, hop).mean(axis=1)
            P[h:h + hh] = kp
            R[h:h + hh] = rp
            # STFT input: this block's hops plus half a window of real samples each side (zeros past the file)
            s0 = blk0 - half
            g.seek(max(0, s0))
            z = g.read(hh * hop + 2 * half - max(0, -s0), dtype='float32', always_2d=True).mean(axis=1)
            buf = np.concatenate([np.zeros(max(0, -s0), np.float32), z])
            if buf.size < hh * hop + 2 * half:
                buf = np.concatenate([buf, np.zeros(hh * hop + 2 * half - buf.size, np.float32)])
            # frame k is centred on the middle of hop k
            idx = (np.arange(hh) * hop + hop // 2)[:, None] + np.arange(nfft)[None, :]
            frames = buf[idx] * win
            spec = np.abs(np.fft.rfft(frames, axis=1))
            mag = np.log1p(100.0 * spec)
            if prev_mag is None:
                prev_mag = mag[:1]
            dif = np.diff(np.vstack([prev_mag[-1:], mag]), axis=0)
            flux[h:h + hh] = np.clip(dif, 0, None).mean(axis=1)
            prev_mag = mag[-1:]
            h += hh
    eps = 1e-12
    nl = max(1, int(round(float(st['loudness_window_s']) / float(st['hop_s']))))
    nr = max(1, int(round(float(st['level_window_s']) / float(st['hop_s']))))
    kern = np.ones(nl) / nl
    loud = -0.691 + 10 * np.log10(np.convolve(P, kern, mode='same') + eps)
    lev = 10 * np.log10(np.convolve(R, np.ones(nr) / nr, mode='same') + eps)
    # onsets: local median + k * MAD of the flux
    W = max(3, int(round(float(st['onset_window_s']) / float(st['hop_s']))))
    gap = max(1, int(round(float(st['onset_min_gap_s']) / float(st['hop_s']))))
    onsets = []
    if nh > 3:
        from scipy.ndimage import median_filter
        med = median_filter(flux, size=2 * W + 1, mode='nearest')
        mad = median_filter(np.abs(flux - med), size=2 * W + 1, mode='nearest') + 1e-6
        peak = (flux >= np.roll(flux, 1)) & (flux > np.roll(flux, -1))
        peak[0] = peak[-1] = False
        cand = np.flatnonzero(peak & (flux > med + float(st['onset_k']) * mad) & (lev > float(st['onset_floor_db'])))
        strengths = (flux[cand] - med[cand]) / mad[cand]
        kept = []
        for i in np.argsort(-strengths):
            c = int(cand[i])
            if all(abs(c - k) >= gap for k in kept):
                kept.append(c)
        kept.sort()
        for c in kept:
            onsets.append({'t': round(t0 + c * float(st['hop_s']), 3), 'strength': round(float((flux[c] - med[c]) / mad[c]), 2),
                           'level_db': round(float(lev[c]), 1)})
    return {'hop_s': float(st['hop_s']), 't0': float(t0), 'loudness_db': ts.series(np.maximum(loud, -120.0), 2),
            'level_db': ts.series(np.maximum(lev, -120.0), 2), 'flux': ts.series(flux, 4), 'onsets': onsets,
            'sample_rate': sr, 'channels': int(info.channels), 'warnings': warnings,
            'integrated_note': 'loudness_db is a short window, not the integrated loudness of the whole'}


def _audio_lane(ctx):
    """Sound every 10 ms: K-weighted loudness (0.4 s window, LUFS), plain level (30 ms, dBFS), spectral flux and
    onsets (flux peaks above the local median + k x MAD)."""
    import letitedit.timing.timing_render as timing_render
    st = ctx['settings']
    fps = float(ctx['fps'])
    f0, f1 = ctx['range']
    wav = ctx.get('audio')
    t_off = 0.0
    if not wav:
        if ctx['kind'] == 'project':
            return {'method': 'no sound', 'warnings': ['the preview render has no sound file'], 'unsupported': [],
                    'loudness_db': [], 'level_db': [], 'flux': [], 'onsets': [], 'hop_s': st['hop_s']}
        F = int(ctx['frames'])
        if f0 == 0 and f1 >= F:
            wav = timing_render.extract_audio(ctx['video'])
        else:
            wav = timing_render.extract_audio(ctx['video'], f0 / fps, (f1 - f0) / fps)
            t_off = f0 / fps
        if not wav:
            return {'method': 'no sound', 'warnings': ['the video has no sound'], 'unsupported': [],
                    'loudness_db': [], 'level_db': [], 'flux': [], 'onsets': [], 'hop_s': st['hop_s']}
    elif ctx['kind'] == 'project':
        t_off = (ctx.get('render') or {}).get('f0', 0) / fps
    res = analyse(wav, st)
    if t_off:
        # series start at the analysed range: pad so index 0 is t = 0
        pad = int(round(t_off / float(st['hop_s'])))
        for k in ('loudness_db', 'level_db', 'flux'):
            res[k] = [None] * pad + res[k]
        for o in res['onsets']:
            o['t'] = round(o['t'] + t_off, 3)
    for o in res['onsets']:
        o['f'] = ts.fr(o['t'], fps)
    res['method'] = ('K-weighted (BS.1770) loudness over a centred loudness_window_s window; plain RMS level over '
                     'level_window_s; spectral flux of the log-magnitude spectrum (mono mix, Hann window of fft '
                     'samples) every hop_s; onsets = flux peaks above local median + onset_k x MAD within '
                     'onset_window_s, onset_min_gap_s apart, above onset_floor_db')
    res['units'] = {'loudness_db': 'LUFS (short window)', 'level_db': 'dBFS', 'flux': 'mean rise of log(1 + 100 '
                    '|X|) per bin', 'onsets.strength': 'MADs above the local median'}
    res['source'] = wav
    res.setdefault('unsupported', ['onsets are sound changes of any kind (a word, a hit, a click), not their '
                                   'meaning; music beats come from the music lane'])
    return res


_audio_lane.defaults = AUDIO_DEFAULTS
ts.register_lane('audio', _audio_lane, depends=(), version=1)
