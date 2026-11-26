"""Sound across every cut: the 'joins' view, the 'joins' lane and the per-cut measures the cut inspector shows
(builder B3, TIMING-SPEC.md).

    measure(source, cuts=None, start_s=None, end_s=None, settings=None, refresh=False) -> {joins: [...], contract}
    at_cut(source, cut, settings=None)      -> one join's measures (cut: {t} or {f} or seconds), for cut_inspect
    measure_audio(y, t, settings=None, ...) -> the measures at time t of a 48 kHz sound array (pure; tests use it)
    scan_clicks(y, ...)                     -> sample discontinuities anywhere (sound edits away from picture cuts)
    project_edit_points(project, script)    -> picture cuts, sound joins and items of a project, timeline seconds
    view(source, start_s, end_s, items, cuts, options, detail) -> the 'joins' view (images + numbers)
    lane(ctx)                               -> the 'joins' lane for timing_signals (registered at import)

Per join, every measure has its raw value, unit, method and the threshold used ('joins.*' keys of
bridge/timing_thresholds.json); `flags` lists the measures over threshold. Nothing here listens: a flag says a number
passed a threshold, not that a person would hear a problem.
- click: one-step prediction error of an AR(32) model fitted over +-21 ms (autocorrelation method), peak within
  +-1.5 ms of the join / median of the peaks of 3 ms windows over +-150 ms (Godsill & Rayner 1998: clicks are what a
  linear predictor can't predict); also the second-difference ratio split_edit_measure.click uses (about 1-2 where
  nothing happens; its tests call 3+ a click); and the click's own level (dBFS) so inaudible ones in silence pass.
- level jump: BS.1770 K-weighted momentary loudness (400 ms) just after minus just before (LU); and the speech level
  jump: loudness of the speech frames (words) within 3 s each side.
- room tone: noise floor (10th percentile of 20 ms K-weighted levels within 1.5 s each side, word frames left out)
  after minus before (dB), and digital silence (< -90 dBFS) touching the join (a hole instead of room tone).
- spectral jump: 32 mel bands to 16 kHz averaged over 0.5 s each side, each side's mean level removed, RMS of the
  band differences (dB); the same over non-speech frames only (room tone's colour).
- pitch jump (dialogue): median pitch of the last 0.3 s of voicing before vs the first 0.3 s after, within 1.5 s
  (semitones), from the speech lane.
- words: the last word before and the first after (gaps in s), a word cut by the join, the pause across the join,
  whether a thought ends there and whether a breath survives in it (letitedit-fine FINE-1, FINE-3, FINE-4).
- source (projects): the pause after the same word in the source recording, and whether it held a breath, so a
  thought end tightened below its natural pause, or a breath removed, shows.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import json
import math
import os
import re
import time
from pathlib import Path

import numpy as np

import letitedit.timing.prosody as prosody

SR = prosody.SR
SCHEMA_VERSION = 1
LANE = 'joins'
LANE_VERSION = 6
HOP = 0.01

# Thresholds calibrated 28 Oct 2026 on synthetic joins in real speech (3 clips, 54 untouched positions; see
# INTEGRATION-speech-joins.md): each sits near the 95th percentile of the untouched positions' values.
DEFAULTS = {
    'joins.click_ratio': 6.0,          # AR residual peak at the join / typical residual peaks around it
                                       # (untouched speech: 1% over it; hard cuts and impulses: 97%)
    'joins.click_ratio_lossy': 3.5,    # the same for a file whose sound is AAC/MP3/Opus (the codec smears a click:
                                       # through AAC 128k, 79% of clicks pass 3.5 with 3% false alarms; 73% pass 6)
    'joins.click_d2_ratio': 3.0,       # second-difference ratio (split_edit_measure.click; its tests use 3)
    'joins.click_min_dbfs': -60.0,     # a discontinuity quieter than this is not reported as a click
    'joins.level_jump_lu': 18.0,       # momentary loudness change (untouched speech: p95 17 LU: speech next to
                                       # a pause), so only extreme jumps flag; speech_level_jump is the useful one
    'joins.speech_level_jump_lu': 5.0,  # speech loudness change across the join (untouched p95 5.1 LU)
    'joins.floor_jump_db': 8.0,        # noise floor (room tone) change across the join (untouched p95 6.3 dB)
    'joins.silence_gap_s': 0.02,       # digital silence this long touching the join is a hole
    'joins.spectral_jump_db': 10.0,    # voice envelope change (untouched p95 9.5 dB; a level-matched EQ change ~30)
    'joins.room_spectral_jump_db': 10.0,  # room tone envelope change (untouched p95 8.8 dB)
    'joins.pitch_jump_st': 4.0,        # speaking pitch change across a dialogue join (FINE-4: pitch jumps)
    'joins.word_clear_before_s': 0.03,  # the join closer than this after the last word's end clips its tail
    'joins.word_clear_after_s': 0.02,  # ... or before the next word's start clips its onset (FINE-3: 50/80 ms pads)
    'joins.min_thought_pause_s': 0.30,  # a thought end kept with less pause than this (and less than the source's)
    'joins.source_pause_ratio': 0.6,   # ... and under this share of the source's own pause: the breath was cut
    'joins.clip_ms': 40,               # the cut takes more than this off a word's end or start (FINE-3)
    'joins.window_s': 0.5,             # spectra: seconds each side
    'joins.floor_window_s': 1.5,       # noise floor: seconds each side
}


INFO = {
    'joins.click_ratio': ('x', 'AR(32) prediction-error peak at the join over the typical peaks around it (lossless '
                               'sound; synthetic joins in real speech: 97% of hard cuts/impulses over it, 1% of '
                               'untouched positions)'),
    'joins.click_ratio_lossy': ('x', 'the same for AAC/MP3/Opus sound (through AAC 128k: 79% recall, 3% false alarms)'),
    'joins.click_d2_ratio': ('x', 'second-difference ratio (split_edit_measure.click), reported only'),
    'joins.click_min_dbfs': ('dBFS', 'a discontinuity quieter than this is not a click'),
    'joins.level_jump_lu': ('LU', 'momentary (0.4 s) loudness change; speech next to a pause makes up to 17 LU'),
    'joins.speech_level_jump_lu': ('LU', 'loudness change of the speech frames within 3 s each side'),
    'joins.floor_jump_db': ('dB', 'noise floor (room tone) change, non-speech frames within 1.5 s each side'),
    'joins.silence_gap_s': ('s', 'digital silence (< -90 dBFS) this long touching the join is a hole'),
    'joins.spectral_jump_db': ('dB', 'voice spectral envelope change (median log-mel 100 Hz-8 kHz, level removed, 8 '
                                     'DCT terms)'),
    'joins.room_spectral_jump_db': ('dB', 'room tone spectral envelope change (quietest non-speech frames)'),
    'joins.pitch_jump_st': ('semitones', 'speaking pitch change across a dialogue join (letitedit-fine FINE-4)'),
    'joins.word_clear_before_s': ('s', 'a join closer than this after the last word ends clips its tail (FINE-3)'),
    'joins.word_clear_after_s': ('s', "a join closer than this before the next word's start clips its onset"),
    'joins.min_thought_pause_s': ('s', 'a thought end left with less pause than this ...'),
    'joins.source_pause_ratio': ('x', "... and under this share of the recording's own pause there is tightened "
                                      '(FINE-1)'),
    'joins.clip_ms': ('ms', 'the cut takes more than this off the last word\'s end or the next word\'s start '
                            '(measured on the recordings)'),
    'joins.window_s': ('s', 'fallback spectra window each side when a side has too little speech'),
    'joins.floor_window_s': ('s', 'noise floor window each side'),
}


def threshold_entries():
    """This module's keys for timing_thresholds.json as {key: {value, unit, about}}."""
    return {k: {'value': DEFAULTS[k], 'unit': INFO.get(k, ('', ''))[0], 'about': INFO.get(k, ('', ''))[1]}
            for k in DEFAULTS}


def _st(settings=None):
    return prosody.settings_for(DEFAULTS, settings)


def _r(x, nd=3):
    return prosody._r(x, nd)


def _m(value, unit, threshold=None, over=None, method=None):
    """A measure: raw value, unit, the threshold and whether it is over it."""
    out = {'value': value, 'unit': unit}
    if threshold is not None:
        out['threshold'] = threshold
        out['over'] = bool(over) if value is not None else None
    if method:
        out['method'] = method
    return out


# ------------------------------------------------------------------ DSP helpers

def _k_filter(x, sr=SR):
    """BS.1770 K-weighting (two biquads) along axis 0."""
    from scipy.signal import lfilter
    G, Q, fc = 3.99984385397, 0.7071752369554193, 1681.9744509555319
    A, w0 = 10 ** (G / 40), 2 * math.pi * fc / sr
    al, c = math.sin(w0) / (2 * Q), math.cos(w0)
    b1 = [A * ((A + 1) + (A - 1) * c + 2 * math.sqrt(A) * al), -2 * A * ((A - 1) + (A + 1) * c),
          A * ((A + 1) + (A - 1) * c - 2 * math.sqrt(A) * al)]
    a1 = [(A + 1) - (A - 1) * c + 2 * math.sqrt(A) * al, 2 * ((A - 1) - (A + 1) * c),
          (A + 1) - (A - 1) * c - 2 * math.sqrt(A) * al]
    Q2, fc2 = 0.5003270373253953, 38.13547087613982
    w2 = 2 * math.pi * fc2 / sr
    al2, c2 = math.sin(w2) / (2 * Q2), math.cos(w2)
    b2, a2 = [(1 + c2) / 2, -(1 + c2), (1 + c2) / 2], [1 + al2, -2 * c2, 1 - al2]
    y = lfilter(np.array(b1) / a1[0], np.array(a1) / a1[0], x, axis=0)
    return lfilter(np.array(b2) / a2[0], np.array(a2) / a2[0], y, axis=0)


def _lufs(k_seg):
    """Loudness (LUFS-like) of a K-filtered [n, ch] stretch: -0.691 + 10 log10(sum over channels of mean square)."""
    if k_seg is None or len(k_seg) < 16:
        return None
    p = float(np.sum(np.mean(np.square(k_seg), axis=0)))
    return -0.691 + 10 * math.log10(max(p, 1e-12))


def _levinson(r, order):
    """AR coefficients a[1..p] (x[n] ~ sum a_k x[n-k]) from autocorrelation r[0..p]."""
    a = np.zeros(order + 1)
    a[0] = 1.0
    err = r[0]
    if err <= 0:
        return np.zeros(order)
    for i in range(1, order + 1):
        acc = r[i] + np.dot(a[1:i], r[i - 1:0:-1])
        k = -acc / err
        a_new = a.copy()
        a_new[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a_new[i] = k
        a = a_new
        err *= (1 - k * k)
        if err <= 1e-18:
            break
    return -a[1:]


def ar_click(x, c, order=32, fit=1024, look=72, around=7200, win=144):
    """(ratio, peak_dbfs, residual) for mono float64 x at sample c: AR(order) fitted on x[c-fit:c+fit] (Hann,
    autocorrelation), one-step prediction error over +-around; peak |error| within +-look samples of c divided by
    the median of the peaks of `win`-sample windows over +-around (the +-3*look middle left out)."""
    n = len(x)
    lo, hi = max(order, c - fit), min(n, c + fit)
    seg = x[lo:hi]
    if len(seg) < 4 * order or not np.any(seg):
        return None, None, None
    w = seg * np.hanning(len(seg))
    full = np.correlate(w, w, mode='full')[len(w) - 1:len(w) + order]
    full[0] *= 1.0 + 1e-6
    a = _levinson(full, order)
    a0, a1 = max(order, c - around), min(n, c + around)
    ext = x[a0 - order:a1]
    # e[n] = x[n] - sum a_k x[n-k]
    pred = np.convolve(ext, np.concatenate([[0.0], a]), mode='full')[:len(ext)]
    e = (ext - pred)[order:]
    k = c - a0
    if k < 0 or k >= len(e):
        return None, None, None
    peak = float(np.max(np.abs(e[max(0, k - look):k + look + 1])))
    mids = [float(np.max(np.abs(e[j:j + win]))) for j in range(0, len(e) - win, win)
            if abs(j + win // 2 - k) > 3 * look]
    base = float(np.median(mids)) if mids else 0.0
    ratio = peak / base if base > 0 else (float('inf') if peak > 0 else 0.0)
    return ratio, 20 * math.log10(max(peak, 1e-10)), e


def d2_click(x, c, half=144, around=19200):
    """split_edit_measure.click on mono x at sample c: largest |second difference| within +-3 ms over the median of
    the same in 6 ms windows over +-400 ms."""
    d2 = np.abs(np.diff(x, 2))
    lo, hi = max(0, c - around), min(len(d2), c + around)
    peak = d2[max(0, c - half):c + half].max(initial=0.0)
    wins = [d2[k:k + 2 * half].max() for k in range(lo, hi - 2 * half, 2 * half) if abs(k + half - c) > 4 * half]
    base = float(np.median(wins)) if wins else 0.0
    return float(peak / base) if base > 0 else (float('inf') if peak > 0 else 0.0)


def _band_matrix(n_fft=2048, n_bands=32, fmax=8000.0):
    fb, centres = prosody.mel_bands(n_bands, 100.0, fmax, n_fft, SR)
    return fb, centres


def envelope(B, keep=8):
    """Spectral envelope of band levels B [frames, bands]: the median level per band (dB, robust to transients),
    its mean removed, smoothed by keeping DCT coefficients 1..keep (an MFCC-like timbre; level is coefficient 0)."""
    from scipy.fft import dct, idct
    med = np.median(B, axis=0)
    c = dct(med - med.mean(), norm='ortho')
    c[0] = 0.0
    c[keep + 1:] = 0.0
    return idct(c, norm='ortho')


def envelope_distance(Ba, Bb, keep=8):
    """RMS (dB) over bands of the difference of two spectral envelopes."""
    return float(np.sqrt(np.mean((envelope(Ba, keep) - envelope(Bb, keep)) ** 2)))


_FB = {}


def band_levels(mono, a, b, n_fft=2048, hop=480):
    """[frames, 32] mel band levels (dB) of mono[a:b] (40 ms windows, 10 ms hop)."""
    if 'fb' not in _FB:
        _FB['fb'], _FB['c'] = _band_matrix(n_fft)
    seg = mono[max(0, a):max(0, b)]
    if len(seg) < n_fft:
        return np.zeros((0, _FB['fb'].shape[0]))
    frames = np.lib.stride_tricks.sliding_window_view(seg, n_fft)[::hop]
    spec = np.abs(np.fft.rfft(frames * np.hanning(n_fft), axis=1)) ** 2
    return 10 * np.log10(spec @ _FB['fb'].T + 1e-12)


def _frame_levels(k, a, b, step=960):
    """K-weighted levels (dB) of 20 ms frames of k[a:b] ([n] or [n, ch]: power averaged over the channels, so
    uncorrelated noise in two channels is not 3 dB low as in a downmix)."""
    seg = k[max(0, a):max(0, b)]
    if seg.ndim == 1:
        seg = seg[:, None]
    n = len(seg) // step
    if n < 1:
        return np.zeros(0)
    p = np.mean(np.square(seg[:n * step]).reshape(n, step, seg.shape[1]), axis=(1, 2))
    return 10 * np.log10(np.maximum(p, 1e-14))


def _silence_run(mono, c, limit_s=0.5, thr_db=-90.0):
    """Seconds of digital silence (|x| under thr) in the run that touches sample c (searching +-5 ms)."""
    thr = 10 ** (thr_db / 20)
    lim = int(limit_s * SR)
    lo, hi = max(0, c - lim), min(len(mono), c + lim)
    seg = np.abs(mono[lo:hi]) < thr
    k = c - lo
    best = 0
    for a, b in prosody._runs(seg):          # the longest silent run that reaches within 5 ms of the join
        if a <= k + 240 and b >= k - 240:
            best = max(best, b - a)
    return best / SR if best >= 48 else 0.0  # under 1 ms is a zero crossing, not silence


# ------------------------------------------------------------------ one join

def _measure_click(c, out, st, y):
    # ---- click (per channel, the worst)
    ratios, peaks, d2s = [], [], []
    for ch in range(y.shape[1]):
        r_, pk, _ = ar_click(y[:, ch], c)
        if r_ is not None:
            ratios.append(r_)
            peaks.append(pk)
        d2s.append(d2_click(y[:, ch], c))
    ratio = max(ratios) if ratios else None
    peak_db = peaks[int(np.argmax(ratios))] if ratios else None
    d2 = max(d2s) if d2s else None
    click = (ratio is not None and ratio >= st['joins.click_ratio'] and peak_db is not None
             and peak_db >= st['joins.click_min_dbfs'])
    out['click'] = _m(_r(ratio, 2), 'x (AR residual peak / typical)', st['joins.click_ratio'], click,
                      'AR(32) one-step prediction error, peak within +-1.5 ms over the median of 3 ms window peaks '
                      'within +-150 ms (Godsill & Rayner 1998)')
    out['click_level'] = _m(_r(peak_db, 1), 'dBFS', st['joins.click_min_dbfs'], (peak_db or -999) >= st['joins.click_min_dbfs'])
    out['click_d2'] = _m(_r(d2, 2), 'x (2nd difference peak / typical)', st['joins.click_d2_ratio'],
                         (d2 or 0) >= st['joins.click_d2_ratio'], 'split_edit_measure.click')
    if click:
        out['flags'].append('click')


def _measure_speech_levels(MIN_FR, S, T0, k_mono, mask_basis, n, no_speech, out, s0, s1, speech_mask, st):
    sw = 3.0

    def speech_level(a_s, b_s):
        lv = _frame_levels(k_mono, S(a_s), S(b_s))
        msk = speech_mask(a_s, b_s, 0.02, lv)[:len(lv)]
        sel = lv[:len(msk)][msk]
        if sel.size < MIN_FR:
            return None
        lo_, hi_ = np.percentile(sel, [25, 95])           # trimmed: word edges and single bursts left out
        sel = sel[(sel >= lo_) & (sel <= hi_)]
        return -0.691 + 10 * math.log10(float(np.mean(10 ** (sel / 10))))
    slb = speech_level(max(T0, s0 - sw), s0) if not no_speech else None
    sla = speech_level(s1, min(T0 + n / SR, s1 + sw)) if not no_speech else None
    sj = (sla - slb) if (sla is not None and slb is not None) else None
    out['speech_level_jump'] = _m(_r(sj, 1), 'LU', st['joins.speech_level_jump_lu'],
                                  sj is not None and abs(sj) >= st['joins.speech_level_jump_lu'],
                                  f'K-weighted loudness of speech frames ({mask_basis}) within 3 s each side, after '
                                  'minus before; None when a side has under 0.16 s of speech')
    out['speech_level_before'] = _m(_r(slb, 1), 'LUFS')
    out['speech_level_after'] = _m(_r(sla, 1), 'LUFS')
    if sj is not None and abs(sj) >= st['joins.speech_level_jump_lu']:
        out['flags'].append('speech_level_jump')


def _measure_room_floor(MIN_FR, S, T0, c, k_mono, mask_basis, mono, n, out, s0, s1, speech_mask, st):
    # ---- noise floor / room tone (non-speech frames only)
    fw = st['joins.floor_window_s']

    def floor(a_s, b_s):
        lv = _frame_levels(k_mono, S(a_s), S(b_s))
        msk = ~speech_mask(a_s, b_s, 0.02, lv)[:len(lv)]
        sel = lv[:len(msk)][msk]
        if sel.size < MIN_FR:
            return None, int(sel.size)
        return float(np.percentile(sel, 10)), int(sel.size)
    fb_, nb = floor(max(T0, s0 - fw), s0 - 0.005)
    fa_, na = floor(s1 + 0.005, min(T0 + n / SR, s1 + fw))
    fj = (fa_ - fb_) if (fa_ is not None and fb_ is not None) else None
    out['floor_before'] = _m(_r(fb_, 1), 'dB (K-weighted, 10th percentile of non-speech 20 ms frames)')
    out['floor_after'] = _m(_r(fa_, 1), 'dB (K-weighted, 10th percentile of non-speech 20 ms frames)')
    out['floor_jump'] = _m(_r(fj, 1), 'dB', st['joins.floor_jump_db'], fj is not None and abs(fj) >= st['joins.floor_jump_db'],
                           f'noise floor after minus before, from non-speech frames ({mask_basis}) within '
                           f'{fw} s; None when a side has under 0.16 s of them')
    if fj is not None and abs(fj) >= st['joins.floor_jump_db']:
        out['flags'].append('room_tone_jump')
    hole = _silence_run(mono, c)
    out['silence_gap'] = _m(_r(hole, 3), 's (digital silence < -90 dBFS touching the join)', st['joins.silence_gap_s'],
                            hole >= st['joins.silence_gap_s'])
    if hole >= st['joins.silence_gap_s']:
        out['flags'].append('silence_gap')


def _measure_spectral_jumps(MIN_FR, S, T0, ca, cb, gap, mono, no_speech, out, s0, s1, speech_mask, st):
    # ---- spectra: the voice's colour (speech frames) and the room's (the quietest non-speech frames), as
    # spectral envelopes (median log-mel 100 Hz-8 kHz, level removed, DCT-smoothed: an MFCC-like distance)
    sws = max(st['joins.window_s'], 1.5)
    Bb = band_levels(mono, S(max(T0, s0 - sws)), cb - gap)
    Ba = band_levels(mono, ca + gap, S(s1 + sws))
    if len(Bb) >= MIN_FR and len(Ba) >= MIN_FR:
        lb_ = Bb.mean(axis=1)
        la_ = Ba.mean(axis=1)
        mb = speech_mask(max(T0, s0 - sws), s0, 0.01, lb_)[:len(Bb)]
        ma = speech_mask(s1, s1 + sws, 0.01, la_)[:len(Ba)]
        mb = np.concatenate([mb, np.zeros(len(Bb) - len(mb), bool)])
        ma = np.concatenate([ma, np.zeros(len(Ba) - len(ma), bool)])
        if not no_speech and mb.sum() >= MIN_FR and ma.sum() >= MIN_FR:
            dv = envelope_distance(Ba[ma], Bb[mb])
            basis = 'speech frames (the voice)'
        else:
            k_ = int(st['joins.window_s'] / 0.01)
            dv = envelope_distance(Ba[:k_], Bb[-k_:])
            basis = f"all frames within {st['joins.window_s']} s (too little speech on a side)"
        out['spectral_jump'] = _m(_r(dv, 2), 'dB (RMS over 32 mel bands 100 Hz-8 kHz of the envelope difference)',
                                  st['joins.spectral_jump_db'], dv >= st['joins.spectral_jump_db'],
                                  f'spectral envelopes (median log-mel, level removed, 8 DCT terms) of {basis} '
                                  f'within {sws} s each side')
        if dv >= st['joins.spectral_jump_db']:
            out['flags'].append('spectral_jump')
        qb, qa = Bb[~mb], Ba[~ma]
        if len(qb) >= MIN_FR and len(qa) >= MIN_FR:
            qb = qb[qb.mean(axis=1) <= np.percentile(qb.mean(axis=1), 40)]
            qa = qa[qa.mean(axis=1) <= np.percentile(qa.mean(axis=1), 40)]
        if len(qb) >= 4 and len(qa) >= 4:
            dr = envelope_distance(qa, qb)
            out['room_spectral_jump'] = _m(_r(dr, 2), 'dB', st['joins.room_spectral_jump_db'],
                                           dr >= st['joins.room_spectral_jump_db'],
                                           'the same over the quietest 40% of non-speech frames (the room tone)')
            if dr >= st['joins.room_spectral_jump_db']:
                out['flags'].append('room_spectral_jump')
        else:
            out['room_spectral_jump'] = _m(None, 'dB', st['joins.room_spectral_jump_db'], False,
                                           'not measured: too little non-speech on a side')


def _measure_speech_context(out, s0, s1, speech, st, t, words, wspans):
    # ---- speech context
    if words:
        before = [w for w in words if w['t0'] < t - 0.02]
        after = [w for w in words if w['t1'] > t + 0.02]
        lw = max(before, key=lambda w: w['t1']) if before else None
        nw = min(after, key=lambda w: w['t0']) if after else None
        cut_word = next((w for w in words if w['t0'] + 0.03 < t < w['t1'] - 0.03), None)
        ctx = {'last_word': lw['w'] if lw else None, 'next_word': nw['w'] if nw else None,
               'gap_before_s': _r(t - lw['t1']) if lw else None, 'gap_after_s': _r(nw['t0'] - t) if nw else None,
               'pause_across_s': _r(nw['t0'] - lw['t1']) if (lw and nw) else None,
               'word_cut': cut_word['w'] if cut_word else None}
        if cut_word:
            out['flags'].append('word_cut')
        elif lw is not None and 0 <= t - lw['t1'] < st['joins.word_clear_before_s'] and t - lw['t1'] < 0.5:
            out['flags'].append('tight_after_word')
        if nw is not None and not cut_word and 0 <= nw['t0'] - t < st['joins.word_clear_after_s']:
            out['flags'].append('tight_before_word')
        ctx['thresholds'] = {'word_clear_before_s': st['joins.word_clear_before_s'],
                             'word_clear_after_s': st['joins.word_clear_after_s']}
        if lw is not None:
            ctx['text_end'] = str(lw['w'])[-1:] in '.?!'
        if speech and lw is not None:
            # the boundary after the last word as scored on the timeline (its pause is the edited one)
            bd = next((e for e in speech.get('boundaries', speech.get('thought_ends', []))
                       if abs(e['t'] - lw['t1']) < 0.03), None)
            min_s = float((speech.get('settings') or {}).get('speech.thought_end.min_strength', 0.55))
            ctx['thought_end'] = ({'strength': bd['strength'], 'cues': bd['cues'],
                                   'is_end': bd['strength'] >= min_s} if bd else None)
            br = [b for b in speech.get('breaths', []) if lw['t1'] - 0.02 <= b['t0'] and (nw is None or b['t1'] <= nw['t0'] + 0.02)]
            ctx['breath_in_pause'] = bool(br)
        out['words'] = ctx
    # ---- pitch jump (dialogue only: pitch inside words, so music under a montage is never read as a voice)
    if speech and speech.get('f0') and wspans:
        f0 = speech['f0']
        t0s = float(speech.get('t0', 0.0))

        def med(a_s, b_s, last):
            ia, ib = max(0, int((a_s - t0s) / HOP)), min(len(f0), int((b_s - t0s) / HOP))
            v = [x for k_, x in enumerate(f0[ia:ib], ia) if x and any(w0 <= t0s + k_ * HOP < w1 for w0, w1 in wspans)]
            v = v[-30:] if last else v[:30]
            return float(np.median(12 * np.log2(np.array(v) / 100.0))) if len(v) >= 8 else None
        pb, pa = med(s0 - 1.5, s0, True), med(s1, s1 + 1.5, False)
        pj = (pa - pb) if (pa is not None and pb is not None) else None
        out['pitch_jump'] = _m(_r(pj, 2), 'semitones', st['joins.pitch_jump_st'],
                               pj is not None and abs(pj) >= st['joins.pitch_jump_st'],
                               'median pitch of the last 0.3 s of voiced word frames before vs the first 0.3 s after '
                               '(within 1.5 s)')
        if pj is not None and abs(pj) >= st['joins.pitch_jump_st']:
            out['flags'].append('pitch_jump')


def measure_audio(y, t, settings=None, words=None, speech=None, span=None, fps=30.0, lossy=False, no_speech=False):
    """Measures of the join at time t (s) of y (48 kHz, [n, ch] or [n]). words: [{t0, t1, w}] in the same time
    (speech frames are left out of the noise floor and give the speech level); speech: the speech lane (pitch, thought
    ends, breaths, activity) in the same time; span: (t0, t1) of a crossfade/dissolve (the sides are measured outside
    it); lossy: the sound went through a lossy codec (the click threshold is joins.click_ratio_lossy)."""
    st = _st(settings)
    if lossy:
        st = dict(st, **{'joins.click_ratio': st['joins.click_ratio_lossy']})
    s0, s1 = (span if span else (t, t))
    out = {'t': _r(t, 4), 'f': prosody.frame(t, fps), 'flags': []}
    c_abs = int(round(t * SR))
    if c_abs <= 0 or c_abs >= len(y):
        out['unsupported'] = ['join outside the sound']
        return out
    # work on +-3.6 s around the join (times stay absolute; S() turns one into a sample of the window)
    base = max(0, int(round(s0 * SR)) - int(3.6 * SR))
    y = np.asarray(y[base:int(round(s1 * SR)) + int(3.6 * SR)], dtype=np.float64)
    if y.ndim == 1:
        y = y[:, None]
    T0 = base / SR
    n = len(y)

    def S(ta):
        return int(round((ta - T0) * SR))
    c, cb, ca = S(t), S(s0), S(s1)                       # the join, last sample before / first after its span
    mono = y.mean(axis=1)
    _measure_click(c, out, st, y)
    # ---- levels
    k = _k_filter(y)
    k_mono = k                                  # levels average power over the channels (_frame_levels)
    w4 = int(0.4 * SR)
    gap = int(0.005 * SR)
    lb = _lufs(k[max(0, cb - gap - w4):max(0, cb - gap)])
    la = _lufs(k[ca + gap:ca + gap + w4])
    lj = (la - lb) if (la is not None and lb is not None) else None
    out['level_before'] = _m(_r(lb, 1), 'LUFS (momentary, 0.4 s)')
    out['level_after'] = _m(_r(la, 1), 'LUFS (momentary, 0.4 s)')
    out['level_jump'] = _m(_r(lj, 1), 'LU', st['joins.level_jump_lu'], lj is not None and abs(lj) >= st['joins.level_jump_lu'],
                           'BS.1770 K-weighted momentary loudness after minus before')
    if lj is not None and abs(lj) >= st['joins.level_jump_lu']:
        out['flags'].append('level_jump')
    # ---- which frames are speech: the speech lane's activity (10 ms), else the words, else an energy split
    wspans = [(float(w['t0']), float(w['t1'])) for w in (words or [])]
    act = None
    if speech and speech.get('active'):
        act = np.frombuffer(speech['active'].encode(), dtype=np.uint8) == ord('1')
        act_t0 = float(speech.get('t0', 0.0))
        mask_basis = 'speech activity (voiced or loud, 10 ms)'
    elif wspans:
        mask_basis = 'word spans'
    else:
        mask_basis = 'energy split (frames above the window median + 3 dB count as speech)'

    def speech_mask(a_s, b_s, step_s, levels=None):
        n_ = max(0, int(round((b_s - a_s) / step_s)))
        centres = a_s + (np.arange(n_) + 0.5) * step_s
        if act is not None:
            idx = np.clip(((centres - act_t0) / HOP).astype(int), 0, max(0, len(act) - 1))
            return act[idx] if len(act) else np.zeros(n_, bool)
        if wspans:
            m = np.zeros(n_, bool)
            for w0, w1 in wspans:
                if w1 > a_s and w0 < b_s:
                    m[(centres >= w0) & (centres < w1)] = True
            return m
        if levels is not None and len(levels):
            return levels[:n_] > np.median(levels) + 3.0
        return np.zeros(n_, bool)
    MIN_FR = 8                             # at least 8 frames (0.16 s of 20 ms frames) a side
    _measure_speech_levels(MIN_FR, S, T0, k_mono, mask_basis, n, no_speech, out, s0, s1, speech_mask, st)
    _measure_room_floor(MIN_FR, S, T0, c, k_mono, mask_basis, mono, n, out, s0, s1, speech_mask, st)
    _measure_spectral_jumps(MIN_FR, S, T0, ca, cb, gap, mono, no_speech, out, s0, s1, speech_mask, st)
    _measure_speech_context(out, s0, s1, speech, st, t, words, wspans)
    return out


def scan_clicks(y, settings=None, step_s=0.003, min_gap_s=0.05, start_s=0.0):
    """Sample discontinuities anywhere in y (48 kHz): AR residual peaks over joins.click_ratio, at most one per
    min_gap_s. A cheap first pass (2nd-difference ratio over 3) picks the places to test."""
    st = _st(settings)
    y = np.asarray(y, dtype=np.float64)
    mono = y.mean(axis=1) if y.ndim > 1 else y
    d2 = np.abs(np.diff(mono, 2))
    half = int(step_s * SR / 2)
    n = len(d2) // (2 * half)
    if n < 10:
        return []
    peaks = d2[:n * 2 * half].reshape(n, 2 * half).max(axis=1)
    from scipy.ndimage import median_filter
    base = median_filter(peaks, size=int(0.8 / step_s) | 1, mode='nearest')
    cand = np.flatnonzero(peaks > 3.0 * np.maximum(base, 1e-12))
    out, last = [], -1e9
    for j in cand:
        c = int(j * 2 * half + np.argmax(d2[j * 2 * half:(j + 1) * 2 * half]))
        if (c - last) / SR < min_gap_s:
            continue
        r_, pk, _ = ar_click(mono, c)
        if r_ is not None and r_ >= st['joins.click_ratio'] and pk >= st['joins.click_min_dbfs']:
            out.append({'t': round(start_s + c / SR, 4), 'ratio': round(r_, 2), 'level_dbfs': round(pk, 1)})
            last = c
    return out


# ------------------------------------------------------------------ edit points of a project

def project_edit_points(project, script=None):
    """{'cuts': picture cuts [{t, f, kind, track, from_item, to_item, from_clip, to_clip, span}], 'sound_joins':
    [{t, f, kind: join|start|end, track, speech: bool, from_item, to_item, fade_s}], 'items': [{id, track, t0, t1,
    clip, in_s, out_s, muted}]} in timeline seconds, from the edit script."""
    import letitedit.timeline.edit_script as es
    from letitedit.timeline.edit_sync import layout
    if script is None:
        script = es.read(project)
    fps = float(script['profile']['fps'])
    items, cuts, joins_ = [], [], []

    def muted(it):
        return any(e == 'mute' or (isinstance(e, dict) and 'mute' in e) for e in it.get('effects', []))

    def short(c):
        return re.split(r'[\\/]', c)[-1] if c else None
    main = next((t for t in script['tracks'] if t.get('kind', 'video') == 'video'), None)

    def tr_of(it):
        tr = it.get('transition')
        if not tr:
            return 0.0, None
        return es.to_seconds(tr['len'] if isinstance(tr, dict) else tr), (tr.get('type') if isinstance(tr, dict)
                                                                           else 'dissolve')
    def split_mute(it):
        """(head_s, tail_s, fade_s) silenced by a split edit's mute on this item."""
        for e in it.get('effects', []) or []:
            if isinstance(e, dict) and isinstance(e.get('split_mute'), dict):
                m = e['split_mute']
                return (float(m.get('head') or 0.0), float(m.get('tail') or 0.0), float(m.get('fade') or 0.0))
        return 0.0, 0.0, 0.0
    split_records = []
    for t in script['tracks']:
        lay = layout(t)
        heard = t.get('hide') not in ('audio', 'both')
        is_speech = heard and not prosody.NOT_SPEECH.search(t['name'])
        sounding = [heard and 'clip' in it and not muted(it) for it, _, _ in lay]
        for k, (it, s, e) in enumerate(lay):
            head, tail, mfade = split_mute(it)
            rec = {'id': it.get('id'), 'track': t['name'], 't0': round(s, 4), 't1': round(e, 4),
                   'clip': it.get('clip'), 'in_s': it.get('in'), 'out_s': it.get('out'), 'muted': muted(it),
                   'speed': it.get('speed', 1.0)}
            if head or tail:
                rec['split_mute'] = {'head_s': head, 'tail_s': tail, 'fade_s': mfade}
            if it.get('split_edit'):
                rec['split_edit'] = it['split_edit']
                split_records.append({'bridge': it.get('id'), 'track': t['name'], 't0': round(s, 4),
                                      't1': round(e, 4), **it['split_edit']})
            items.append(rec)
            tr_len, tr_type = tr_of(it)
            prev = lay[k - 1] if k > 0 else None
            touch_prev = prev is not None and (abs(prev[2] - s) < 1e-3 or tr_len > 0)
            nxt = lay[k + 1] if k + 1 < len(lay) else None
            touch_next = nxt is not None and (abs(nxt[1] - e) < 1e-3 or tr_of(nxt[0])[0] > 0)
            if t is main and touch_prev and 'clip' in it and 'clip' in prev[0]:
                c = {'kind': 'cut', 'track': t['name'], 'from_item': prev[0].get('id'), 'to_item': it.get('id'),
                     'from_clip': short(prev[0].get('clip')), 'to_clip': short(it.get('clip'))}
                if tr_len > 0:      # a transition: 'cut' type cuts the picture mid-overlap, the sound crossfades
                    c.update(kind='cut' if tr_type == 'cut' else 'dissolve', span=[round(s, 4), round(s + tr_len, 4)],
                             t=round(s + tr_len / 2.0 if tr_type == 'cut' else s, 4))
                else:
                    c['t'] = round(s, 4)
                cuts.append(c)
            if not sounding[k]:
                continue
            p_head, p_tail = (split_mute(prev[0])[:2] if prev is not None else (0.0, 0.0))
            if touch_prev and sounding[k - 1] and not head and not p_tail:
                joins_.append({'t': round(s + tr_len / 2.0, 4), 'kind': 'join', 'track': t['name'],
                               'speech': is_speech, 'from_item': prev[0].get('id'), 'to_item': it.get('id'),
                               'fade_s': round(tr_len, 4)})
            else:            # the sound comes in here (after silence, a muted clip or a split edit's muted head)
                joins_.append({'t': round(s + head, 4), 'kind': 'start', 'track': t['name'], 'speech': is_speech,
                               'to_item': it.get('id'), 'fade_s': round(mfade if head else 0.0, 4)})
            n_head = split_mute(nxt[0])[0] if nxt is not None else 0.0
            if not (touch_next and sounding[k + 1] and not tail and not n_head):
                joins_.append({'t': round(e - tail, 4), 'kind': 'end', 'track': t['name'], 'speech': is_speech,
                               'from_item': it.get('id'), 'fade_s': round(mfade if tail else 0.0, 4)})
    # a sound ending on one speech track while another starts within a frame is one join across tracks (a split
    # edit's bridge clip, or sound moved to another track)
    tol = 1.0 / fps + 1e-3
    ends = [j for j in joins_ if j['kind'] == 'end' and j['speech']]
    for s_ in [j for j in joins_ if j['kind'] == 'start' and j['speech']]:
        e_ = next((j for j in ends if j['track'] != s_['track'] and abs(j['t'] - s_['t']) <= tol), None)
        if e_ is not None:
            ends.remove(e_)
            joins_.remove(e_)
            s_.update(kind='join', from_item=e_['from_item'], cross_track=[e_['track'], s_['track']],
                      fade_s=max(s_['fade_s'], e_['fade_s']), t=round((s_['t'] + e_['t']) / 2.0, 4))
    for c in cuts:
        c['f'] = prosody.frame(c['t'] + 1e-6, fps)
    for j in joins_:
        j['f'] = prosody.frame(j['t'] + 1e-6, fps)
    cuts.sort(key=lambda c: c['t'])
    joins_.sort(key=lambda j: (j['t'], j['track']))
    return {'cuts': cuts, 'sound_joins': joins_, 'items': items, 'split_edits': split_records, 'fps': fps,
            'length_s': es.to_seconds(script.get('length', 0))}


def _sound_at_cut(cut, sound_joins, fps, split_edits=()):
    """How the dialogue sound behaves at a picture cut: 'cut' (a speech-track sound join on the same frame), 'J cut'
    / 'L cut' (a split edit into this cut: the sound changes lead/lag seconds before/after the picture), 'starts' /
    'ends' (speech sound comes in or stops there), else 'continuous' (a picture-only change over the same sound)
    with the nearest speech-track sound change within 2 s."""
    tol = 1.0 / fps + 1e-3
    for se in split_edits or ():
        if se.get('into') == cut.get('to_item') and (not se.get('out_of') or se.get('out_of') == cut.get('from_item')):
            if se.get('lead'):
                return {'sound': 'J cut', 'offset_s': -float(se['lead']), 'offset_frames': -int(round(float(se['lead']) * fps)),
                        'sound_join_t': se.get('t0'), 'fade_s': se.get('fade'),
                        'note': f"J cut: the incoming sound starts {float(se['lead']):.2f} s before the picture"}
            if se.get('lag'):
                return {'sound': 'L cut', 'offset_s': float(se['lag']), 'offset_frames': int(round(float(se['lag']) * fps)),
                        'sound_join_t': se.get('t1'), 'fade_s': se.get('fade'),
                        'note': f"L cut: the outgoing sound runs on {float(se['lag']):.2f} s under the new picture"}
    same = [j for j in sound_joins if j['speech'] and abs(j['t'] - cut['t']) <= tol]
    jn = [j for j in same if j['kind'] == 'join']
    if jn:
        return {'sound': 'cut', 'sound_join_t': jn[0]['t'], 'offset_frames': 0, 'fade_s': jn[0]['fade_s'],
                'items': [jn[0].get('from_item'), jn[0].get('to_item')]}
    if same:
        k = same[0]['kind']
        return {'sound': 'starts' if k == 'start' else 'ends', 'sound_join_t': same[0]['t'], 'offset_frames': 0,
                'note': 'speech sound comes in at the cut' if k == 'start' else 'speech sound stops at the cut'}
    near = [j for j in sound_joins if j['speech'] and abs(j['t'] - cut['t']) <= 2.0]
    if near:
        j = min(near, key=lambda j: abs(j['t'] - cut['t']))
        off = int(round((j['t'] - cut['t']) * fps))
        return {'sound': 'continuous', 'nearest_sound_change_t': j['t'], 'offset_frames': off,
                'note': f"picture-only cut: the dialogue sound continues; its nearest change ({j['kind']}) is "
                        f"{abs(off)} frames {'before' if off < 0 else 'after'}"}
    return {'sound': 'continuous', 'note': 'picture-only cut: no dialogue sound change within 2 s'}


# ------------------------------------------------------------------ sources (projects): the natural pause

def _edge(item, side, settings=None):
    """The words and sound of an item's own recording at its edge (side 'out': where the item ends, 'in': where it
    starts), measured on the source file itself (read-only; a 10 s window, the cached transcript, prosody's word
    edges, pauses, breaths and boundary scores). Source seconds throughout."""
    import letitedit.footage.speech as speech_words
    from letitedit.timeline.edit_script import to_seconds
    if not item or not item.get('clip') or item.get('in_s') is None or item.get('muted'):
        return None
    clip = item['clip']
    edge = to_seconds(item['out_s'] if side == 'out' else item['in_s'])
    lo, hi = max(0.0, edge - 5.0), edge + 5.0
    ws = speech_words.cached_words(clip, max(0.0, lo - 2.0), hi + 2.0)
    if not ws:
        return {'clip': Path(clip).name, 'edge_s': round(edge, 3), 'note': 'no cached transcript near the edge'}
    x16 = _source_window(clip, lo, hi)
    if x16 is None or len(x16) < 1600:
        return {'clip': Path(clip).name, 'edge_s': round(edge, 3), 'note': 'source sound not readable'}
    wwin = [{'w': w['w'], 't0': float(w['s']), 't1': float(w['e'])} for w in ws if w['e'] > lo and w['s'] < hi]
    lane = prosody.analyse_audio(x16, wwin, lo, settings, with_series=True)
    W = lane['words']
    rec = {'clip': Path(clip).name, 'edge_s': round(edge, 3)}
    min_s = lane['settings']['speech.thought_end.min_strength']
    clip_s = float(_st(settings)['joins.clip_ms']) / 1000.0
    # is there speech sound at the edge itself (active +-30 ms, voiced within +-50 ms)? A word can only be clipped
    # where the recording is sounding: transcript and refined word ends can run on over a pause
    k = int(round((edge - float(lane['t0'])) / prosody.HOP))
    act_ = lane.get('active') or ''
    f0_ = lane.get('f0') or []
    near = act_[max(0, k - 3):k + 3]
    sounding = bool(near) and near.count('1') >= max(1, len(near) // 2) and any(
        v is not None for v in f0_[max(0, k - 5):k + 5])
    rec['sound_at_edge'] = sounding

    def vs(w):                       # the word's voiced extent (its edges when it has no voicing)
        return (w['v0'] if w.get('v0') is not None else w['t0'], w['v1'] if w.get('v1') is not None else w['t1'])
    if side == 'out':
        # the last word with at least clip_ms of its voiced sound before the out point
        inside = [k for k, w in enumerate(W) if vs(w)[0] <= edge - clip_s and not w.get('filler')]
        if not inside:
            rec['note'] = 'no word heard before the out point'
            return rec
        i = inside[-1]
        w = W[i]
        v0, v1 = vs(w)
        nxt = W[i + 1] if i + 1 < len(W) else None
        p = next((p for p in lane['pauses'] if p['after_word'] == i), None)
        br = lane['breaths'][p['breath']] if p and 'breath' in p else None
        b = next((b for b in lane['boundaries'] if b['word'] == i), None)
        over = v1 - edge                 # voiced sound of the word after the out point (cut off)
        clipped = over >= clip_s and w.get('timing') != 'unreliable' and sounding
        rec.update({'word': w['w'], 'word_end_s': w['t1'], 'voiced_end_s': v1,
                    'kept_after_word_s': round(edge - w['t1'], 3),
                    'tail_clipped_ms': int(round(over * 1000)) if clipped else 0,
                    'natural_pause_s': round(nxt['t0'] - w['t1'], 3) if nxt else None,
                    'next_word_in_source': nxt['w'] if nxt else None,
                    'breath': ({'t0': br['t0'], 't1': br['t1'], 'kept': br['t1'] <= edge + 0.02} if br else None),
                    'text_end': w['w'][-1:] in '.?!',
                    'thought_end': ({'strength': b['strength'], 'cues': b['cues'], 'is_end': b['strength'] >= min_s}
                                    if b else None)})
    else:
        # the first word with at least clip_ms of its voiced sound after the in point
        inside = [k for k, w in enumerate(W) if vs(w)[1] >= edge + clip_s and not w.get('filler')]
        if not inside:
            rec['note'] = 'no word heard after the in point'
            return rec
        i = inside[0]
        w = W[i]
        v0, v1 = vs(w)
        prv = W[i - 1] if i > 0 else None
        p = next((p for p in lane['pauses'] if p['after_word'] == i - 1), None) if i > 0 else None
        br = lane['breaths'][p['breath']] if p and 'breath' in p else None
        under = edge - v0                # voiced sound of the word before the in point (cut off)
        clipped = under >= clip_s and w.get('timing') != 'unreliable' and sounding
        rec.update({'word': w['w'], 'word_start_s': w['t0'], 'voiced_start_s': v0,
                    'kept_before_word_s': round(w['t0'] - edge, 3),
                    'onset_clipped_ms': int(round(under * 1000)) if clipped else 0,
                    'natural_pause_before_s': round(w['t0'] - prv['t1'], 3) if prv else None,
                    'breath': ({'t0': br['t0'], 't1': br['t1'],
                                'kept': 'yes' if br['t0'] >= edge - 0.02 else 'partly' if br['t1'] > edge else 'no'}
                               if br else None)})
    if w.get('timing') == 'unreliable':
        rec['timing'] = 'unreliable: the transcript stretched this word over seconds; its edges are not checked'
    return rec


def _sides(item_a, item_b, overlap_s=0.0, settings=None):
    """Both recordings at a cut: A's out point and B's in point, and the pause the edit leaves between A's last word
    and B's first word (source-measured, minus any transition overlap)."""
    out = {'out': _edge(item_a, 'out', settings), 'in': _edge(item_b, 'in', settings)}
    a, b = out['out'] or {}, out['in'] or {}
    if a.get('kept_after_word_s') is not None and b.get('kept_before_word_s') is not None:
        # a clipped word is still heard up to (from) the cut: its side adds no silence
        out['edited_pause_s'] = round(max(0.0, max(0.0, a['kept_after_word_s']) + max(0.0, b['kept_before_word_s'])
                                          - overlap_s), 3)
    return out


_SRC_MEMO = {}


def _source_window(clip, lo, hi):
    key = (clip, round(lo, 2), round(hi, 2))
    if key not in _SRC_MEMO:
        import subprocess
        raw = subprocess.run([str(prosody.FFMPEG), '-v', 'error', '-threads', '4', '-ss', f'{lo:.3f}', '-t', f'{hi - lo:.3f}', '-i', clip,
                              '-vn', '-ac', '1', '-ar', str(prosody.SR16), '-f', 'f32le', '-'], capture_output=True,
                             creationflags=prosody.NO_WINDOW).stdout
        if len(_SRC_MEMO) > 64:
            _SRC_MEMO.clear()
        _SRC_MEMO[key] = np.frombuffer(raw[:len(raw) - len(raw) % 4], dtype=np.float32).astype(np.float64) if raw else None
    return _SRC_MEMO[key]


def _fine_check(j, settings=None):
    """letitedit-fine at a cut, from both recordings (j['source'] = _sides()):
    - word_clipped (FINE-3): the cut takes more than joins.clip_ms off the last word's end or the next word's start;
    - thought_end_tightened (FINE-1): a thought ends at A's last word (timeline or source prosody, or a full stop in
      the transcript) and the edit leaves under joins.min_thought_pause_s between the words, under
      joins.source_pause_ratio of the pause the recording had there;
    - breath_removed (FINE-1): at a thought end, a breath the recordings had (after A's word, or before B's word)
      is cut off and none is left in the edited pause."""
    st = _st(settings)
    w = j.get('words') or {}
    src = j.get('source') or {}
    a, b = src.get('out') or {}, src.get('in') or {}
    notes = []
    for side, key, word in (('out', 'tail_clipped_ms', a.get('word')), ('in', 'onset_clipped_ms', b.get('word'))):
        ms = (a if side == 'out' else b).get(key)
        if ms and ms >= st['joins.clip_ms']:
            notes.append({'check': 'word_clipped', 'side': side, 'clipped_ms': ms, 'threshold_ms': st['joins.clip_ms'],
                          'note': f"the cut takes {ms} ms off '{word}' ({'its end' if side == 'out' else 'its start'})"})
    pause = src.get('edited_pause_s', w.get('pause_across_s'))
    why = [name for name, yes in (('timeline prosody', (w.get('thought_end') or {}).get('is_end')),
                                  ('source prosody', (a.get('thought_end') or {}).get('is_end')),
                                  ('transcript full stop', a.get('text_end', w.get('text_end')))) if yes]
    sp = a.get('natural_pause_s')
    if pause is not None and why and pause < st['joins.min_thought_pause_s'] and (
            sp is None or pause < st['joins.source_pause_ratio'] * sp):
        notes.append({'check': 'thought_end_tightened', 'pause_s': pause, 'source_pause_s': sp,
                      'threshold_s': st['joins.min_thought_pause_s'], 'thought_end_from': why,
                      'note': (f"a thought ends at '{a.get('word') or w.get('last_word')}' but only {pause:.2f} s "
                               f"pass before '{b.get('word') or w.get('next_word')}'"
                               + (f" (the recording had {sp:.2f} s)" if sp is not None else ''))})
    had = [x for x in ((a.get('breath'), 'after the last word'), (b.get('breath'), 'before the next word')) if x[0]]
    kept = any((x[0].get('kept') in (True, 'yes')) for x in had) or w.get('breath_in_pause')
    if why and had and not kept:
        notes.append({'check': 'breath_removed', 'pause_s': pause, 'source_pause_s': sp,
                      'thought_end_from': why,
                      'note': 'the recording had a breath ' + ' and '.join(x[1] for x in had) +
                              '; the cut leaves none'})
    return notes


# ------------------------------------------------------------------ whole sources

LOSSY = {'aac', 'mp3', 'opus', 'vorbis', 'ac3', 'eac3', 'mp2', 'wmav2'}


def _audio_codec(path):
    import subprocess
    r = subprocess.run([str(prosody.FFPROBE), '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                        'stream=codec_name', '-of', 'csv=p=0', str(path)], capture_output=True, text=True,
                       creationflags=prosody.NO_WINDOW)
    return (r.stdout or '').strip().lower() or None


_STORE = {}


def _store(source):
    """The store's result for the speech lane (with its preview render's WAV path), or None without a store."""
    if source in _STORE:
        return _STORE[source]
    try:
        import letitedit.timing.timing_signals as timing_signals
        sig = timing_signals.signals(source, lanes=['speech'])
        lane_ = sig['lanes'].get('speech') or {}
        res = sig if not lane_.get('error') else None
    except Exception:  # noqa: BLE001 - no store: measure here
        res = None
    if len(_STORE) > 8:
        _STORE.clear()
    _STORE[source] = res
    return res


def _speech_lane(source, settings=None, ctx_lanes=None):
    if ctx_lanes and ctx_lanes.get('speech') and not ctx_lanes['speech'].get('error'):
        return ctx_lanes['speech']
    sig = _store(source) if ctx_lanes is None else None      # inside a store lane: never call the store again
    if sig is not None:
        return sig['lanes']['speech']
    return prosody.analyse(source, settings=(settings or {}).get('speech') if isinstance(settings, dict) else None)['lane']


def _store_audio(source):
    """(stereo 48 kHz, description) of a project's preview WAV from the store, or None."""
    sig = _store(source)
    wav = (sig or {}).get('audio')
    if not wav or not os.path.exists(str(wav)):
        return None
    import soundfile
    y, sr = soundfile.read(str(wav), dtype='float32', always_2d=True)
    if sr != SR:
        return None
    f0 = int(((sig.get('range') or {}).get('f0')) or 0)
    if f0 > 0:                                   # the preview covers [f0, f1): put it on the timeline clock
        y = np.concatenate([np.zeros((int(round(f0 / float(sig['fps']) * SR)), y.shape[1]), np.float32), y])
    return y, f"mix: the timing store's preview render ({Path(str(wav)).name}, lossless)"


def _video_cuts(video, ctx_lanes=None):
    if ctx_lanes and isinstance(ctx_lanes.get('edit'), dict) and ctx_lanes['edit'].get('cuts') is not None:
        return ctx_lanes['edit']['cuts'], 'the edit lane'
    import letitedit.footage.shots as shots
    d = shots.detect(video)
    return [{'t': c['t'], 'f': c.get('frame'), 'kind': c.get('kind', 'cut'),
             'span': [c['start'], c['end']] if c.get('start') is not None and c.get('kind') in ('dissolve', 'fade') else None}
            for c in d['cuts']], 'shots.detect (picture cuts of the file)'


def _span_of(c, fps):
    """(t0, t1) seconds of a gradual cut: our 'span', or the edit lane's f0/f1 when they differ."""
    if c.get('span'):
        return tuple(float(x) for x in c['span'])
    if c.get('f0') is not None and c.get('f1') is not None and int(c['f1']) > int(c['f0']):
        return float(c['f0']) / fps, float(c['f1']) / fps
    return None


def measure(source, cuts=None, start_s=None, end_s=None, settings=None, refresh=False, ctx_lanes=None,
            sources=True, scan=False, basis='mix', audio=None, script=None, use_store=True):
    """Sound measures at every cut of a project or a video.
    Project: every picture cut (the edit lane's when given, else the main track's), plus every change of the
    dialogue sound that is not at a picture cut (a split edit's sound join, a sound starting or stopping on a speech
    track); each picture cut says how the dialogue sound behaves there (sound_at_cut: cut, J/L cut, starts, ends or
    continuous under a picture-only change). The recordings on both sides of each dialogue sound join are measured
    too (sources=True): clipped words, the natural pause, breaths, thought ends (letitedit-fine checks).
    Video: the picture cuts found in the file (the edit lane's when given).
    cuts: [{t} | {f} | seconds] to measure only those. audio: (stereo 48 kHz array, description) already loaded
    (the store's preview WAV); else a project's mix is rendered by melt (lossless WAV, cached), a video decoded.
    scan: also list clicks anywhere else in the sound."""
    t_begin = time.monotonic()
    source = str(Path(source).resolve())
    kind = prosody.kind_of(source)
    if isinstance(settings, dict) and isinstance(settings.get('joins'), dict):   # the store's {lane: {...}} form
        settings = dict(settings['joins'])
    st = _st(settings)
    warnings, unsupported = [], []
    pts = None
    lossy = False
    if kind == 'project':
        pts = project_edit_points(source, script)
        fps = pts['fps']
        if audio is None and basis == 'mix' and use_store:
            audio = _store_audio(source)
        y, desc = audio if audio is not None else prosody.project_audio(source, basis=basis)[:2]
        if cuts is None:
            lane_cuts = ((ctx_lanes or {}).get('edit') or {}).get('cuts') if ctx_lanes else None
            cuts = [dict(c) for c in (lane_cuts if lane_cuts is not None else pts['cuts'])]
            end_t = pts['length_s'] - 1.0 / fps
            for j in pts['sound_joins']:          # dialogue sound changes away from the picture cuts
                if not j['speech'] or j['t'] <= 1.0 / fps or j['t'] >= end_t:
                    continue
                if any(abs(float(c.get('t', (c.get('f') or 0) / fps)) - j['t']) <= 1.0 / fps + 1e-3 for c in cuts):
                    continue
                cuts.append({'t': j['t'], 'f': j['f'], 'kind': f"sound_{j['kind']}", 'track': j['track'],
                             'from_item': j.get('from_item'), 'to_item': j.get('to_item'),
                             'span': [j['t'] - j['fade_s'] / 2, j['t'] + j['fade_s'] / 2] if j['fade_s'] else None})
            cuts.sort(key=lambda c: float(c.get('t', (c.get('f') or 0) / fps)))
    else:
        import letitedit.footage.shots as shots
        fps = float(shots.probe(source)['fps'])
        y, desc = audio if audio is not None else prosody.video_audio(source)
        codec = _audio_codec(source)
        lossy = codec in LOSSY and audio is None
        if lossy:
            desc += f' ({codec}: click threshold joins.click_ratio_lossy {st["joins.click_ratio_lossy"]})'
        if cuts is None:
            cuts, how = _video_cuts(source, ctx_lanes)
            warnings.append(f'cuts from {how}')
    if y is None or not len(y):
        res = prosody.contract(source, kind, warnings=warnings, unsupported=['joins: the source has no sound'])
        res['joins'] = []
        return res
    lane = None
    try:
        lane = _speech_lane(source, settings, ctx_lanes)
    except Exception as e:  # noqa: BLE001
        warnings.append(f'speech lane unavailable ({e}): no word, breath or pitch context')
    words = (lane or {}).get('words') or []
    duration = len(y) / SR
    lo = float(start_s) if start_s is not None else 0.0
    hi = float(end_s) if end_s is not None else duration
    norm = []
    for c in cuts or []:
        if isinstance(c, (int, float)):
            c = {'t': float(c)}
        c = dict(c)
        if c.get('t') is None and c.get('f') is not None:
            c['t'] = float(c['f']) / fps
        if lo - 1e-6 <= c['t'] <= hi + 1e-6:
            norm.append(c)
    items = {it['id']: it for it in (pts['items'] if pts else []) if it.get('id')}
    out = []
    for c in norm:
        span = _span_of(c, fps)
        # a source whose speech lane found no words (music only, or untranscribed): no speech-level, voice-colour
        # or pitch measures, which would read the music as a voice
        j = measure_audio(y, c['t'], st, words=words, speech=lane, span=span, fps=fps, lossy=lossy,
                          no_speech=lane is not None and not words)
        j.update({k: c.get(k) for k in ('kind', 'track', 'from_item', 'to_item', 'from_clip', 'to_clip', 'detail')
                  if c.get(k)})
        for k in ('from_clip', 'to_clip'):
            if j.get(k):
                j[k] = re.split(r'[\\/]', str(j[k]))[-1]
        if span:
            j['span'] = [_r(span[0], 4), _r(span[1], 4)]
        pair = None
        if pts is not None:
            if str(c.get('kind', '')).startswith('sound_'):
                pair = (c.get('from_item'), c.get('to_item'))
            else:
                sac = _sound_at_cut(c, pts['sound_joins'], fps, pts.get('split_edits'))
                j['sound_at_cut'] = sac
                if sac['sound'] == 'cut':
                    pair = tuple(sac.get('items') or (c.get('from_item'), c.get('to_item')))
        if pts is not None and sources and pair and (pair[0] in items or pair[1] in items):
            try:
                ov = (span[1] - span[0]) if span else 0.0
                j['source'] = _sides(items.get(pair[0]), items.get(pair[1]), ov, settings)
            except Exception as e:  # noqa: BLE001
                j['source'] = {'warning': f'not measured: {e}'}
            fine = _fine_check(j, settings)
            if fine:
                j['fine_cut'] = fine
                j['flags'] += [n['check'] for n in fine if n['check'] not in j['flags']]
        j['problems'] = problems(j, st)
        out.append(j)
    res = prosody.contract(source, kind, checked=[[_r(lo), _r(hi)]], warnings=warnings, unsupported=unsupported,
                           extra={'kind': kind, 'fps': fps, 'audio_basis': desc,
                                  'seconds': _r(time.monotonic() - t_begin, 2)})
    res['joins'] = out
    res['thresholds'] = st
    res['summary'] = summarise(out)
    if scan:
        mono = y.mean(axis=1)
        a, b = int(lo * SR), int(hi * SR)
        found = scan_clicks(mono[a:b], st, start_s=lo)
        at_join = [s for s in found if any(abs(s['t'] - j['t']) < 0.01 for j in out)]
        res['clicks_elsewhere'] = [s for s in found if s not in at_join]
    return res


PROBLEM_ORDER = ('word_clipped', 'word_cut', 'silence_gap', 'click', 'breath_removed', 'thought_end_tightened',
                 'speech_level_jump', 'room_tone_jump', 'spectral_jump', 'room_spectral_jump', 'pitch_jump',
                 'level_jump', 'tight_after_word', 'tight_before_word')


def problems(j, st):
    """The join's flags as findings for readers like the cut inspector: [{kind, text, value, unit, threshold}],
    most important first; every text names its number and threshold."""
    out = []

    def val(k):
        return (j.get(k) or {}).get('value')
    fine = {n['check']: n for n in (j.get('fine_cut') or [])}
    for f in sorted(set(j.get('flags') or []), key=lambda f: PROBLEM_ORDER.index(f) if f in PROBLEM_ORDER else 99):
        if f in fine:
            n = fine[f]
            out.append({'kind': f, 'text': n['note'], 'value': n.get('clipped_ms', n.get('pause_s')),
                        'unit': 'ms' if 'clipped_ms' in n else 's',
                        'threshold': n.get('threshold_ms', n.get('threshold_s'))})
            continue
        if f == 'click':
            out.append({'kind': f, 'value': val('click'), 'unit': 'x', 'threshold': j['click']['threshold'],
                        'text': f"click: a sample jump {val('click')}x the sound around it (>= "
                                f"{j['click']['threshold']}), {val('click_level')} dBFS"})
        elif f == 'silence_gap':
            out.append({'kind': f, 'value': val('silence_gap'), 'unit': 's', 'threshold': j['silence_gap']['threshold'],
                        'text': f"a hole of digital silence {val('silence_gap')} s at the join (room tone missing)"})
        elif f in ('speech_level_jump', 'level_jump'):
            out.append({'kind': f, 'value': val(f), 'unit': 'LU', 'threshold': j[f]['threshold'],
                        'text': f"{'speech ' if f.startswith('speech') else ''}loudness jumps {val(f):+.1f} LU across "
                                f"the join (>= {j[f]['threshold']})"})
        elif f == 'room_tone_jump':
            out.append({'kind': f, 'value': val('floor_jump'), 'unit': 'dB', 'threshold': j['floor_jump']['threshold'],
                        'text': f"room tone (noise floor) jumps {val('floor_jump'):+.1f} dB (>= "
                                f"{j['floor_jump']['threshold']})"})
        elif f in ('spectral_jump', 'room_spectral_jump'):
            out.append({'kind': f, 'value': val(f), 'unit': 'dB', 'threshold': j[f]['threshold'],
                        'text': f"{'the voice' if f == 'spectral_jump' else 'the room tone'} changes colour: "
                                f"envelope difference {val(f)} dB (>= {j[f]['threshold']})"})
        elif f == 'pitch_jump':
            out.append({'kind': f, 'value': val('pitch_jump'), 'unit': 'st', 'threshold': j['pitch_jump']['threshold'],
                        'text': f"speaking pitch jumps {val('pitch_jump'):+.1f} semitones (>= "
                                f"{j['pitch_jump']['threshold']})"})
        elif f in ('word_cut', 'tight_after_word', 'tight_before_word'):
            w = j.get('words') or {}
            out.append({'kind': f, 'value': w.get('gap_before_s') if f != 'tight_before_word' else w.get('gap_after_s'),
                        'unit': 's', 'threshold': (st['joins.word_clear_before_s'] if f != 'tight_before_word'
                                                   else st['joins.word_clear_after_s']),
                        'text': (f"the join falls inside '{w.get('word_cut')}'" if f == 'word_cut' else
                                 f"the join is {w.get('gap_before_s')} s after '{w.get('last_word')}' ends"
                                 if f == 'tight_after_word' else
                                 f"the join is {w.get('gap_after_s')} s before '{w.get('next_word')}' starts")})
        else:
            out.append({'kind': f, 'text': f})
    return out


def summarise(joins_):
    flags = {}
    for j in joins_:
        for f in j['flags']:
            flags[f] = flags.get(f, 0) + 1
    return {'joins': len(joins_), 'flagged': sum(1 for j in joins_ if j['flags']), 'by_flag': flags}


def at_cut(source, cut, settings=None, lanes=None):
    """One join's measures for the cut inspector (B2): cut = {t} | {f} | seconds (plus optional span/kind/items).
    Uses the store's sound and speech lanes when given (lanes), else measures here."""
    if isinstance(cut, (int, float)):
        cut = {'t': float(cut)}
    res = measure(source, cuts=[cut], settings=settings, ctx_lanes=lanes)
    j = res['joins'][0] if res['joins'] else {'t': cut.get('t'), 'unsupported': ['join outside the range']}
    j['audio_basis'] = res.get('audio_basis')
    return j


# ------------------------------------------------------------------ the lane

def _flat_settings(ctx, name):
    s = ctx.get('settings') or {}
    out = {k: v for k, v in s.items() if not isinstance(v, dict)}
    out.update(s.get(name) or {})
    return out


def lane(ctx):
    """The 'joins' lane (depends on edit and speech): every cut's sound measures (joins.measure on the store's
    preview WAV for a project, the file's own sound for a video)."""
    kind = ctx.get('kind') or prosody.kind_of(ctx['source'])
    src = ctx.get('project') or ctx['source']
    audio = None
    if kind == 'project' and ctx.get('audio') and os.path.exists(str(ctx['audio'])):
        import soundfile
        y, sr = soundfile.read(str(ctx['audio']), dtype='float32', always_2d=True)
        f0 = int((ctx.get('range') or [0])[0] or 0)
        if f0 > 0:
            y = np.concatenate([np.zeros((int(round(f0 / float(ctx['fps']) * SR)), y.shape[1]), np.float32), y])
        if sr == SR:
            audio = (y, f"mix: the timing store's preview render ({Path(str(ctx['audio'])).name}, lossless)")
    res = measure(src, settings=_flat_settings(ctx, LANE), ctx_lanes=ctx.get('lanes'), audio=audio,
                  script=ctx.get('script'), use_store=False)
    return {'method': 'joins.measure: AR(32) click, K-weighted momentary and speech level, noise floor and holes, '
                      'spectral envelopes of voice and room, pitch jump, words across the join, both recordings at '
                      'each dialogue join (projects)',
            'version': LANE_VERSION, 'settings': res.get('thresholds'), 'warnings': res.get('warnings', []),
            'unsupported': res.get('unsupported', []), 'joins': res.get('joins', []), 'summary': res.get('summary'),
            'audio_basis': res.get('audio_basis')}


lane.defaults = {k.split('.', 1)[1]: v for k, v in DEFAULTS.items()}


# ------------------------------------------------------------------ the view

FLAG_TEXT = {'click': 'CLICK', 'level_jump': 'LEVEL', 'speech_level_jump': 'SPEECH LEVEL', 'room_tone_jump': 'ROOM TONE',
             'silence_gap': 'HOLE', 'spectral_jump': 'SPECTRUM', 'room_spectral_jump': 'ROOM COLOUR',
             'pitch_jump': 'PITCH', 'word_cut': 'WORD CUT', 'tight_after_word': 'TIGHT AFTER WORD',
             'tight_before_word': 'TIGHT BEFORE WORD', 'thought_end_tightened': 'THOUGHT END TIGHT',
             'breath_removed': 'BREATH REMOVED', 'word_clipped': 'WORD CLIPPED'}


def _panel(d, y, j, box, fonts, settings):
    """One join: waveform +-4 ms (sample level), loudness +-2 s with the floors, band spectra before/after."""
    x0, y0, x1, y1 = box
    fB, fS, fT = fonts
    t = j['t']
    c = int(round(t * SR))
    mono = y.mean(axis=1) if y.ndim > 1 else y
    red, grey, blue, orange = (200, 0, 0), (120, 120, 120), (0, 70, 200), (220, 120, 0)
    flags = j.get('flags') or []
    d.rectangle(box, outline=(160, 160, 160))
    head = f"#{j.get('n', '')} {prosody.clock(t)} f{j.get('f')} {j.get('kind', '')}"
    if j.get('from_clip') or j.get('to_clip'):
        head += f"  {j.get('from_clip') or ''} > {j.get('to_clip') or ''}"
    d.text((x0 + 6, y0 + 4), head[:80], fill=(0, 0, 0), font=fT)
    d.text((x0 + 6, y0 + 22), ('  '.join(FLAG_TEXT.get(f, f) for f in flags) or 'no flags')[:90],
           fill=red if flags else (0, 130, 0), font=fB)
    # waveform +-4 ms
    W = (x1 - x0 - 24) // 3
    wx0, wy0, wy1 = x0 + 8, y0 + 44, y0 + 150
    a, b = max(0, c - 192), min(len(mono), c + 192)
    seg = mono[a:b]
    if len(seg) > 2:
        amp = max(1e-6, float(np.max(np.abs(seg))))
        pts = [(wx0 + k / (len(seg) - 1) * W, (wy0 + wy1) / 2 - seg[k] / amp * (wy1 - wy0) / 2.2) for k in range(len(seg))]
        d.line(pts, fill=(0, 0, 0), width=1)
        xc = wx0 + (c - a) / max(1, len(seg) - 1) * W
        d.line((xc, wy0, xc, wy1), fill=red if 'click' in flags else grey, width=1)
    cl = j.get('click', {})
    d.text((wx0, wy1 + 2), 'waveform +-4 ms (each sample)', fill=grey, font=fS)
    d.text((wx0, wy1 + 16), f"click {cl.get('value')}x (thr {cl.get('threshold')}), "
                            f"{(j.get('click_level') or {}).get('value')} dBFS"[:44],
           fill=red if 'click' in flags else (0, 0, 0), font=fS)
    # loudness +-2 s
    lx0 = wx0 + W + 8
    k = _k_filter(y[max(0, c - 2 * SR - 4800):c + 2 * SR + 4800])
    km = k.mean(axis=1) if k.ndim > 1 else k
    step = 480
    nfr = len(km) // step
    if nfr > 4:
        p = np.mean(np.square(km[:nfr * step].reshape(nfr, step)), axis=1)
        p4 = np.convolve(p, np.ones(40) / 40, mode='same')
        lv = -0.691 + 10 * np.log10(np.maximum(p4, 1e-12))
        top, bot = max(-10.0, float(np.max(lv)) + 2), max(-10.0, float(np.max(lv)) + 2) - 60
        off = (max(0, c - 2 * SR - 4800) - (c - 2 * SR)) / SR

        def Y(v):
            return wy1 - (min(max(v, bot), top) - bot) / (top - bot) * (wy1 - wy0)
        pts = [(lx0 + (off + q * step / SR) / 4.0 * W, Y(v)) for q, v in enumerate(lv)]
        pts = [pt for pt in pts if lx0 <= pt[0] <= lx0 + W]
        if len(pts) > 1:
            d.line(pts, fill=blue, width=2)
        xm = lx0 + W / 2
        d.line((xm, wy0, xm, wy1), fill=grey)
        for key, side in (('floor_before', -1), ('floor_after', 1)):
            v = (j.get(key) or {}).get('value')
            if v is not None:
                yy = Y(v)
                d.line((xm + side * W * 0.05, yy, xm + side * W * 0.45, yy), fill=orange, width=2)
        d.text((lx0, wy0 - 2), f'{top:.0f}', fill=grey, font=fS)
    lj = (j.get('level_jump') or {}).get('value')
    fj = (j.get('floor_jump') or {}).get('value')
    sj = (j.get('speech_level_jump') or {}).get('value')
    lv_bad = any(f in flags for f in ('level_jump', 'speech_level_jump', 'room_tone_jump'))
    d.text((lx0, wy1 + 2), f'loudness +-2 s; jump {lj} LU', fill=grey, font=fS)
    d.text((lx0, wy1 + 16), f'speech {sj} LU, floor (orange) {fj} dB'[:44], fill=red if lv_bad else (0, 0, 0),
           font=fS)
    # spectral envelopes (what spectral_jump compares: median log-mel 100 Hz-8 kHz, level removed)
    sx0 = lx0 + W + 8
    Bb = band_levels(mono, c - int(1.5 * SR), c - 240)
    Ba = band_levels(mono, c + 240, c + int(1.5 * SR))
    if len(Bb) and len(Ba):
        eb, ea = envelope(Bb), envelope(Ba)
        top = float(max(eb.max(), ea.max())) + 3
        bot = float(min(eb.min(), ea.min())) - 3

        def Ys(v):
            return wy1 - (min(max(v, bot), top) - bot) / max(1e-6, top - bot) * (wy1 - wy0)
        for arr, col in ((eb, grey), (ea, red)):
            pts = [(sx0 + q / (len(arr) - 1) * W, Ys(v)) for q, v in enumerate(arr)]
            d.line(pts, fill=col, width=2)
    sp = (j.get('spectral_jump') or {}).get('value')
    rs = (j.get('room_spectral_jump') or {}).get('value')
    pj = (j.get('pitch_jump') or {}).get('value')
    sp_bad = any(f in flags for f in ('spectral_jump', 'room_spectral_jump', 'pitch_jump'))
    d.text((sx0, wy1 + 2), 'spectral envelope: grey before, red after', fill=grey, font=fS)
    d.text((sx0, wy1 + 16), f'voice {sp} dB, room {rs} dB, pitch {pj} st'[:46], fill=red if sp_bad else (0, 0, 0),
           font=fS)
    # words across the join (timeline) and both recordings at the cut (sources)
    w = j.get('words') or {}
    src = j.get('source') or {}
    line = ''
    if w:
        te = w.get('thought_end') or {}
        line = (f"timeline words: '{w.get('last_word')}' {w.get('gap_before_s')}s | JOIN | {w.get('gap_after_s')}s '"
                f"{w.get('next_word')}'; pause {w.get('pause_across_s')} s"
                + (f"; thought end {te.get('strength')}" if te else '')
                + ('; breath in it' if w.get('breath_in_pause') else ''))
    sac = j.get('sound_at_cut') or {}
    if sac.get('note'):
        line += f"; {sac['note']}"
    d.text((x0 + 6, wy1 + 34), line[:140], fill=(0, 0, 0), font=fS)
    a, b = src.get('out') or {}, src.get('in') or {}
    if a or b:
        s2 = (f"sources: '{a.get('word')}' kept {a.get('kept_after_word_s')}s after (recording paused "
              f"{a.get('natural_pause_s')}s{', breath' if a.get('breath') else ''}) | '{b.get('word')}' kept "
              f"{b.get('kept_before_word_s')}s before{', breath ' + str(b['breath']['kept']) if b.get('breath') else ''}"
              f"; edited pause {src.get('edited_pause_s')}s")
        fine = [n['check'] for n in (j.get('fine_cut') or [])]
        d.text((x0 + 6, wy1 + 50), s2[:140], fill=red if fine else (60, 60, 60), font=fS)


def render(y, joins_, out_png, title='', per_row=2, width=1600):
    from PIL import Image, ImageDraw
    rows = max(1, math.ceil(len(joins_) / per_row))
    PH = 232
    im = Image.new('RGB', (width, 60 + rows * (PH + 8)), (255, 255, 255))
    d = ImageDraw.Draw(im)
    fonts = (prosody._font(14, True), prosody._font(12), prosody._font(14, True))
    d.text((10, 6), title, fill=(0, 0, 0), font=prosody._font(17, True))
    d.text((10, 30), 'each join: waveform +-4 ms (vertical line = the join, red when a click) | K-weighted loudness '
                     '+-2 s (blue) with the noise floor each side (orange) | spectral envelope 1.5 s before (grey) and '
                     'after (red), level removed. Red text = over its threshold (numbers in the result).',
           fill=(60, 60, 60), font=prosody._font(12))
    pw = (width - 20) // per_row
    for k, j in enumerate(joins_):
        r, c = divmod(k, per_row)
        box = (10 + c * pw, 54 + r * (PH + 8), 10 + (c + 1) * pw - 8, 54 + r * (PH + 8) + PH)
        _panel(d, y, j, box, fonts, None)
    im.save(out_png)
    return str(out_png)


def view(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief'):
    """The 'joins' view (timing_views.register_view): per cut, click, level jump, room tone and spectral jump with
    their numbers, plus the words and breath across the join. options: per_image (12), max_images (3), out_dir,
    settings, sources (True), scan (False), flagged_only (False)."""
    options = dict(options or {})
    source = str(Path(source).resolve())
    kind = prosody.kind_of(source)
    if options.get('refresh'):
        _STORE.pop(source, None)
    if items and kind == 'project' and cuts is None:
        pts = project_edit_points(source)
        ids = set(items)
        cuts = [c for c in pts['cuts'] if c.get('from_item') in ids or c.get('to_item') in ids]
    sset = options.get('settings') or {}
    jset = sset.get('joins', sset) if isinstance(sset, dict) else None
    res = measure(source, cuts=cuts, start_s=start_s, end_s=end_s, settings=jset,
                  sources=options.get('sources', True), scan=options.get('scan', False))
    js = res['joins']
    for n, j in enumerate(js, 1):
        j['n'] = n
    res['options_used'] = {'per_image': int(options.get('per_image', 12)), 'max_images': int(options.get('max_images', 3)),
                           'sources': options.get('sources', True), 'scan': options.get('scan', False),
                           'flagged_only': bool(options.get('flagged_only')), 'images': options.get('images'),
                           'settings': jset or {}}
    shown = [j for j in js if j['flags']] if options.get('flagged_only') else js
    images = []
    if options.get('images') == 0 or options.get('max_images') == 0:      # numbers only (the cut inspector)
        shown = []
    if shown:
        if kind == 'project':
            got = _store_audio(source)
            y = got[0] if got is not None else prosody.project_audio(source)[0]
        else:
            y = prosody.video_audio(source)[0]
    out_dir = Path(options.get('out_dir') or (prosody.CACHE / 'views' / 'timing-joins'))
    out_dir.mkdir(parents=True, exist_ok=True)
    per = int(options.get('per_image', 12))
    limit = int(options.get('max_images', 3))
    stem = f'{Path(source).stem}-{prosody._hash([source, start_s, end_s, [j["t"] for j in shown]])}'
    for k in range(0, min(len(shown), per * limit), per):
        png = out_dir / f'{stem}-{k // per + 1}.png'
        render(y, shown[k:k + per], png, title=f'joins | {Path(source).name} | joins {k + 1}-{min(len(shown), k + per)} '
                                                f'of {len(shown)} ({res["summary"]["flagged"]} flagged)')
        images.append(str(png))
    res['images'] = images
    res['preview_artifacts'] = images
    if len(shown) > per * limit:
        res['unchecked_ranges'] = [[shown[per * limit]['t'], shown[-1]['t']]]
        res['warnings'].append(f'{len(shown) - per * limit} join(s) measured but not drawn (max_images)')
    res['view'] = 'joins'
    if detail != 'full':
        for j in res['joins']:
            for key in list(j):
                if isinstance(j[key], dict) and 'method' in j[key]:
                    j[key] = {k: v for k, v in j[key].items() if k != 'method'}
    return res


# ------------------------------------------------------------------ registration

VIEW_SUMMARY = 'per cut: click (sample discontinuity), level jump, room-tone gap, spectral jump, pitch jump, words and breath across the join'
_REGISTERED = {'lane': False, 'view': False}


def register():
    if not _REGISTERED['lane']:
        try:
            import letitedit.timing.timing_signals as timing_signals
            if hasattr(timing_signals, 'register_lane'):
                timing_signals.register_lane(LANE, lane, depends=('edit', 'speech'), version=LANE_VERSION)
                _REGISTERED['lane'] = True
        except Exception:  # noqa: BLE001
            pass
    if not _REGISTERED['view']:
        try:
            import letitedit.timing.timing_views as timing_views
            if hasattr(timing_views, 'register_view'):
                timing_views.register_view('joins', view, VIEW_SUMMARY)
                _REGISTERED['view'] = True
        except Exception:  # noqa: BLE001
            pass
    return dict(_REGISTERED)


register()
