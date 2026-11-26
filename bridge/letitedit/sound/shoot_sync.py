"""Sync a whole shoot by its sound: cameras, phones and separate audio recorders, many takes each.

Every file is compared with every other by the shape of its sound over time (onset envelopes in three speech/music
bands, a Fisher-scored Pearson search over every lag), and each likely match is checked and refined on the waveform
(phase correlation) in windows spread over the overlap; the windows also measure clock drift. Sharp hits (claps,
slates, hammer blows) are found in each file and count as extra evidence, and can rescue a pair whose overall match is
weak. The matches are then solved into one timeline by voting from the reference outwards, so one bad match is
outvoted by the others. Deterministic: the same files give the same answer.

    sync_shoot(files or folder) -> where every file sits on one timeline, how sure each placement is, drift, hits,
                                   and optionally a project (each device on its own track, the recorder's sound under
                                   the pictures) and synced copies of the camera clips with the recorder's sound in.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import math
import re
import subprocess
import time
from pathlib import Path

import numpy as np

from letitedit.sound.av_tools import NO_WINDOW, _decode, _ffmpeg, _gcc_phat, _r

DEFAULTS = {
    'rate': 8000,              # analysis sample rate (Hz)
    'hop_s': 0.01,             # envelope step (s)
    'min_overlap_s': 4.0,      # least shared time a match must give
    'sure_z': 9.0,             # match score (robust z of the best lag) for a sure match
    'likely_z': 6.5,           # ... for a likely one (also needs its windows to agree)
    'window_s': 12.0,          # length of a check window
    'windows_max': 9,          # check windows per match
    'agree_s': 0.02,           # windows within this of the fitted line agree
    'place_tol_s': 0.10,       # placements within this vote together
    'drift_fix_frames': 0.25,  # correct drift (a speed change) when it would move a clip end more than this many frames
    'hit_tol_s': 0.015,        # two sharp hits line up within this
}
_BANDS = ((100, 400), (400, 1200), (1200, 3400))
MEDIA = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf', '.wmv', '.3gp',
         '.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aiff', '.aif', '.bwf'}
AUDIO_EXT = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aiff', '.aif', '.bwf'}


# ============================================================================ features

def _envelope(y, sr, hop):
    """Onset strength per hop (summed positive change of log band energy), filtered in 60 s chunks so hour-long
    recordings stay small in memory."""
    from scipy.signal import butter, sosfilt
    n = len(y) // hop
    if n < 4:
        return np.zeros(max(n, 0))
    soss = [butter(4, [lo, min(hi, 0.45 * sr)], btype='band', fs=sr, output='sos') for lo, hi in _BANDS
            if min(hi, 0.45 * sr) > lo]
    E = np.zeros((len(soss), n))
    zi = [np.zeros((s.shape[0], 2)) for s in soss]
    step = hop * 6000
    for a in range(0, n * hop, step):
        seg = y[a:min(a + step, n * hop)].astype(np.float64)
        k = len(seg) // hop
        for b, sos in enumerate(soss):
            z, zi[b] = sosfilt(sos, seg, zi=zi[b])
            E[b, a // hop:a // hop + k] = (z[:k * hop] ** 2).reshape(k, hop).mean(axis=1)
    total = np.zeros(n)
    for e in E:
        le = np.log10(e + 1e-4 * e.max() + 1e-12)
        total += np.maximum(0.0, np.diff(le, prepend=le[:1]))
    return total


def _hits(y, sr, max_hits=40):
    """Sharp hits (claps, slates, knocks): a jump of 15 dB or more in the 1-3.4 kHz band within 2 ms, loud for the file,
    dying away within 0.1 s. Returns [(time_s, strength_db)], strongest first, at least 0.3 s apart."""
    from scipy.signal import butter, sosfilt
    hop = max(1, int(0.002 * sr))
    hi = min(3400, 0.45 * sr)
    z = sosfilt(butter(4, [1000, hi], btype='band', fs=sr, output='sos'), y.astype(np.float64))
    n = len(z) // hop
    if n < 200:
        return []
    e = (z[:n * hop] ** 2).reshape(n, hop).mean(axis=1) + 1e-12
    le = 10 * np.log10(e)
    from scipy.ndimage import median_filter, maximum_filter
    floor = median_filter(le, size=101, origin=50)               # median of the 0.2 s before each step
    loud = np.percentile(le, 99.5)
    jump = le - floor
    cand = np.where((jump >= 15) & (le >= loud - 6) & (le == maximum_filter(le, size=5)))[0]
    out = []
    for i in cand:
        tail = le[i + 25:i + 50]                                  # 50-100 ms later
        if len(tail) and tail.mean() <= le[i] - 10:
            out.append((i * hop / sr, float(jump[i])))
    out.sort(key=lambda h: -h[1])
    kept = []
    for t, s in out:
        if all(abs(t - k[0]) >= 0.3 for k in kept):
            kept.append((t, s))
        if len(kept) >= max_hits:
            break
    return kept


def _scored_lags(r, x, lo, hi, min_ov):
    """Every lag L in [lo, hi] (r[i + L] ~ x[i]): Pearson r, the overlap length and a Fisher score
    atanh(r) * sqrt(overlap) standardised over all lags (robust z), which does not favour short overlaps."""
    nr, nx = len(r), len(x)
    n = 1 << int(math.ceil(math.log2(max(2, nr + nx))))
    c = np.fft.irfft(np.fft.rfft(r, n) * np.conj(np.fft.rfft(x, n)), n)
    lags = np.arange(lo, hi + 1)
    sxy = c[lags % n]
    i0 = np.maximum(0, -lags)
    i1 = np.maximum(np.minimum(nx, nr - lags), i0)
    cnt = (i1 - i0).astype(float)
    cx, cx2 = np.concatenate([[0], np.cumsum(x)]), np.concatenate([[0], np.cumsum(x * x)])
    cr, cr2 = np.concatenate([[0], np.cumsum(r)]), np.concatenate([[0], np.cumsum(r * r)])
    j0, j1 = np.clip(i0 + lags, 0, nr), np.clip(i1 + lags, 0, nr)
    sx, sx2 = cx[i1] - cx[i0], cx2[i1] - cx2[i0]
    s_r, s_r2 = cr[j1] - cr[j0], cr2[j1] - cr2[j0]
    m = np.maximum(cnt, 1)
    num = sxy - sx * s_r / m
    den = np.sqrt(np.maximum(sx2 - sx * sx / m, 0) * np.maximum(s_r2 - s_r * s_r / m, 0))
    ok = (cnt >= max(4, min_ov)) & (den > 1e-12)
    rho = np.where(ok, num / np.where(den > 0, den, 1), 0.0)
    f = np.arctanh(np.clip(rho, -0.999, 0.999)) * np.sqrt(np.maximum(cnt - 3, 1))
    if ok.sum() < 8:
        return lags, rho, cnt, np.where(ok, 0.0, -np.inf)
    v = f[ok]
    med = np.median(v)
    mad = 1.4826 * np.median(np.abs(v - med)) or (v.std() or 1.0)
    z = np.where(ok, (f - med) / mad, -np.inf)
    return lags, rho, cnt, z


# ============================================================================ one pair

class _File:
    def __init__(self, path, info, y, sr, hop):
        self.path, self.info, self.y, self.sr, self.hop = path, info, y, sr, hop
        self.dur = len(y) / sr
        self.env = _envelope(y, sr, hop)
        self.hits = _hits(y, sr)
        self.audio_only = Path(path).suffix.lower() in AUDIO_EXT or not info.get('width')


def _window_offset(A, B, off, t0, t1, search_s):
    """Offset (A time - B time) measured on B's span [t0, t1] near `off`: envelope Pearson within +-search_s, then the
    waveform's phase correlation within +-30 ms. Returns (offset_s, envelope_r, waveform_peak) or None."""
    sr, hop = A.sr, A.hop
    hb = int(round(t0 / (hop / sr))), int(round(t1 / (hop / sr)))
    xb = B.env[hb[0]:hb[1]]
    if len(xb) < 50:
        return None
    pad = int(math.ceil(search_s * sr / hop)) + 1
    a0 = int(round((t0 + off) * sr / hop)) - pad
    a1 = a0 + len(xb) + 2 * pad
    if a0 < 0 or a1 > len(A.env):
        return None
    lags, rho, cnt, z = _scored_lags(A.env[a0:a1], xb, 0, 2 * pad, int(0.9 * len(xb)))
    k = int(np.argmax(rho))
    coarse = (a0 + lags[k]) * hop / sr - t0
    s_b0, s_b1 = int(t0 * sr), int(t1 * sr)
    s_a0 = int(round((t0 + coarse) * sr))
    seg_a = A.y[s_a0:s_a0 + (s_b1 - s_b0)] if s_a0 >= 0 else np.zeros(0)
    if len(seg_a) < s_b1 - s_b0:
        return coarse, float(rho[k]), None
    res, ph = _gcc_phat(seg_a.astype(np.float64), B.y[s_b0:s_b1].astype(np.float64), int(0.03 * sr), sr,
                        band=(150.0, min(7000.0, 0.45 * sr)))
    return (s_a0 + res - s_b0) / sr, float(rho[k]), ph


def _check_windows(A, B, off, ov_b, cfg):
    """Measure the offset in windows spread over B's overlap [ov_b0, ov_b1] (B time); fit offset = a + b * t_B.
    Returns {'line': (a, b), 'windows': [...], 'agree': n, 'n': n, 'mid_offset'}."""
    ov = ov_b[1] - ov_b[0]
    w = min(cfg['window_s'], max(3.0, (ov - 0.2) / 3), ov - 0.2)    # short overlaps: three short windows
    if w < 2.0:
        return None
    edge = min(0.4, max(0.0, (ov - w) / 2))           # room for the +-0.25 s search at both ends
    span = ov - w - 2 * edge
    count = 1 if span < 0.5 else int(min(cfg['windows_max'], max(3 if w < cfg['window_s'] else 2, 1 + span // 25)))
    starts = [ov_b[0] + edge + span * i / max(1, count - 1) for i in range(count)] if count > 1 else \
        [ov_b[0] + edge + max(0.0, span) / 2]
    wins = []
    for s in starts:
        got = _window_offset(A, B, off, s, s + w, 0.25)
        if got:
            wins.append({'t': s + w / 2, 'offset': got[0], 'r': got[1], 'peak': got[2]})
    if not wins:
        return None
    t = np.array([x['t'] for x in wins])
    o = np.array([x['offset'] for x in wins])
    keep = np.abs(o - np.median(o)) <= max(cfg['agree_s'], 0.005)
    a, b, se = (float(np.mean(o[keep])) if keep.any() else float(np.median(o))), 0.0, None
    if keep.sum() >= 3 and np.ptp(t[keep]) > 10:
        b1, a1 = np.polyfit(t[keep], o[keep], 1)
        keep = np.abs(o - (a1 + b1 * t)) <= cfg['agree_s']
        if keep.sum() >= 3:
            b1, a1 = np.polyfit(t[keep], o[keep], 1)
            res1 = o[keep] - (a1 + b1 * t[keep])
            sd = max(5e-4, float(np.sqrt((res1 ** 2).sum() / max(1, keep.sum() - 2))))
            se = sd / math.sqrt(float(((t[keep] - t[keep].mean()) ** 2).sum()))
            if abs(b1) > 3 * se and abs(b1) < 2e-3:      # drift only when the windows show it clearly
                a, b = float(a1), float(b1)
            else:
                a = float(np.mean(o[keep]))
    if b == 0.0:
        a = float(np.mean(o[keep])) if keep.any() else float(np.median(o))
    resid = o - (a + b * t)
    agree = int((np.abs(resid) <= cfg['agree_s']).sum())
    for x, rr in zip(wins, resid):
        x['offset'], x['residual_ms'] = _r(x['offset'], 5), _r(rr * 1000, 2)
        x['t'], x['r'], x['peak'] = _r(x['t'], 2), _r(x['r'], 3), _r(x['peak'], 3)
    mid = (ov_b[0] + ov_b[1]) / 2
    ok = np.abs(resid) <= cfg['agree_s']
    sd = float(np.std(resid[ok], ddof=1)) if ok.sum() >= 2 else 0.004
    delta, wz = _stacked_phat(A, B, a, b, ov_b)
    if delta is not None and wz >= 6.0:
        a += delta                       # the whole overlap's waveform agrees on one fine shift
        sigma = 3e-4 if wz >= 10 else 1.5e-3
    else:
        sigma = max(4e-3, sd / math.sqrt(max(1, ok.sum())))   # the waveform is too buried: envelope precision
    return {'line': (float(a), float(b)), 'windows': wins, 'agree': agree, 'n': len(wins),
            'mid': float(mid), 'mid_offset': float(a + b * mid), 'sigma_s': sigma, 'slope_se': se,
            'waveform_z': _r(wz, 2), 'waveform_shift_ms': _r(1000 * delta, 2) if delta is not None else None}


def _stacked_phat(A, B, a, b, ov_b, win_s=6.0, reach_s=0.04, max_windows=24):
    """Phase correlation summed over windows tiling the overlap, each aligned on the line offset = a + b * t_B, so a
    weak waveform match adds up over the whole overlap. Returns (shift_s to add to a, robust z of the summed peak)."""
    sr = A.sr
    L = int(reach_s * sr)
    win_s = min(win_s, ov_b[1] - ov_b[0] - 0.2)
    if win_s < 2.0:
        return None, 0.0
    n_w = int(min(max_windows, max(1, (ov_b[1] - ov_b[0] - 0.2) // win_s)))
    total = None
    length = int(win_s * sr)
    nfft = 1 << int(math.ceil(math.log2(length + 2 * L + length)))
    f = np.fft.rfftfreq(nfft, 1 / sr)
    band = (f >= 150) & (f <= min(7000.0, 0.45 * sr))
    span = ov_b[1] - ov_b[0] - win_s - 0.2
    for i in range(n_w):
        t0 = ov_b[0] + 0.1 + (span * i / max(1, n_w - 1) if n_w > 1 else max(0.0, span) / 2)
        sb = int(t0 * sr)
        xb = B.y[sb:sb + length].astype(np.float64)
        sa = int(round((t0 + a + b * (t0 + win_s / 2)) * sr)) - L
        ya = A.y[max(0, sa):sa + length + 2 * L].astype(np.float64) if sa >= 0 else np.zeros(0)
        if len(xb) < length or len(ya) < length + 2 * L:
            continue
        G = np.fft.rfft(ya, nfft) * np.conj(np.fft.rfft(xb, nfft))
        G /= np.maximum(np.abs(G), 1e-12)
        G[~band] = 0
        c = np.fft.irfft(G, nfft)[:2 * L + 1]
        total = c if total is None else total + c
    if total is None:
        return None, 0.0
    k = int(np.argmax(total))
    frac = 0.0
    if 0 < k < len(total) - 1:
        p, q, r = total[k - 1], total[k], total[k + 1]
        den = p - 2 * q + r
        if den < 0:
            frac = float(np.clip(0.5 * (p - r) / den, -0.5, 0.5))
    med = np.median(total)
    mad = 1.4826 * np.median(np.abs(total - med)) or 1e-12
    return (k + frac - L) / sr, float((total[k] - med) / mad)


def _hits_agree(A, B, off, tol):
    """Hits of B that land on a hit of A at this offset (A time = B time + off)."""
    if not A.hits or not B.hits:
        return 0
    ta = np.array([h[0] for h in A.hits])
    return int(sum(1 for t, _ in B.hits if np.min(np.abs(ta - (t + off))) <= tol))


def _level_out(F_, win_s=0.03):
    """The waveform divided by its own 30 ms loudness, cached: a clap or a hammer blow then weighs no more than a
    word, so one loud hit cannot line up with another file's hit by itself."""
    if getattr(F_, '_flat', None) is None:
        y = F_.y.astype(np.float64)
        n = max(1, int(win_s * F_.sr))
        env = np.sqrt(np.convolve(y * y, np.ones(n) / n, 'same'))
        floor = 0.1 * float(np.median(env[env > 0])) if np.any(env > 0) else 1e-6
        F_._flat = (y / (env + floor + 1e-12)).astype(np.float32)
    return F_._flat


def _phat_search(A, B, excerpt_s=12.0, chunk_s=60.0, band=(150.0, 3400.0), peaks=5):
    """Where excerpts of B's waveform sit in A, by phase correlation over every lag (A in chunks). Finds short or
    buried takes the envelopes miss. Returns [(offset_s, z)] best first, offsets 0.5 s or more apart, where
    A time = B time + offset and z is the peak's robust z over all lags."""
    sr = A.sr
    E = int(min(excerpt_s, B.dur) * sr)
    if E < sr:
        return []
    # excerpts: the liveliest stretch, plus the start and the end of longer takes
    hop = B.hop
    w = max(1, E // hop)
    act = np.convolve(B.env, np.ones(w), 'valid') if len(B.env) > w else np.array([B.env.sum()])
    starts = {int(np.argmax(act)) * hop}
    if B.dur * sr > 3 * E:
        starts |= {0, len(B.y) - E}
    C = int(chunk_s * sr)
    nfft = 1 << int(math.ceil(math.log2(C + 2 * E)))
    ay, by = _level_out(A), _level_out(B)
    f = np.fft.rfftfreq(nfft, 1 / sr)
    keep = (f >= band[0]) & (f <= min(band[1], 0.45 * sr))
    ya = np.concatenate([np.zeros(E, np.float32), ay, np.zeros(E, np.float32)])
    found = []
    for s0 in sorted(starts):
        xb = by[s0:s0 + E].astype(np.float64)
        X = np.conj(np.fft.rfft(xb, nfft))
        tops, sample = [], []
        for c0 in range(0, len(ya) - E + 1, C):
            seg = ya[c0:c0 + C + E].astype(np.float64)
            G = np.fft.rfft(seg, nfft) * X
            G /= np.maximum(np.abs(G), 1e-12)
            G[~keep] = 0
            c = np.fft.irfft(G, nfft)[:min(C, len(seg) - E + 1)]
            if not len(c):
                continue
            sample.append(c[::max(1, len(c) // 4000)])
            idx = np.argpartition(c, -peaks)[-peaks:] if len(c) > peaks else np.arange(len(c))
            tops += [(float(c[i]), c0 + int(i)) for i in idx]
        if not sample:
            continue
        allv = np.concatenate(sample)
        med = float(np.median(allv))
        mad = 1.4826 * float(np.median(np.abs(allv - med))) or 1e-12
        for v, lag in tops:
            # ya[lag + i] ~ xb[i]: A time (lag - E) / sr holds B time s0 / sr
            found.append(((lag - E - s0) / sr, (v - med) / mad))
    found.sort(key=lambda t: -t[1])
    out = []
    for off, zz in found:
        if all(abs(off - o) >= 0.5 for o, _ in out):
            out.append((off, zz))
        if len(out) >= peaks:
            break
    return out


def _match(A, B, cfg, deep=False):
    """Offsets of B against A (A time = B time + offset), each checked in windows. Candidates come from the onset
    envelopes, from sharp hits that line up and (when those are not clear) from the waveform itself. Returns the best
    with its evidence (level 'sure' | 'likely' | 'ambiguous') and, in 'alts', other offsets that fit about as well
    (repeating music, a rhythm that comes back), or a reason there is none."""
    hop_s = A.hop / A.sr
    min_ov = cfg['min_overlap_s']
    if min(A.dur, B.dur) < min_ov:
        min_ov = 0.8 * min(A.dur, B.dur)
    n_ov = max(8, int(min_ov / hop_s))
    lo, hi = -(len(B.env) - n_ov), len(A.env) - n_ov
    if hi < lo:
        return {'why': 'too short'}
    lags, rho, cnt, z = _scored_lags(A.env, B.env, lo, hi, n_ov)
    apart = int(0.5 / hop_s)
    order = np.argsort(-z)[:4000]
    peaks = []
    for i in order:
        if not np.isfinite(z[i]) or z[i] < z[order[0]] - 4.0 or len(peaks) >= 5:
            break
        if all(abs(lags[i] - lags[j]) > apart for j in peaks):
            peaks.append(int(i))
    k = peaks[0]
    far = np.abs(lags - lags[k]) > apart
    runner_up = float(z[far].max()) if far.any() else None

    def env_at(off):
        i = int(round(off / hop_s)) - lo
        if not 0 <= i < len(z):
            return 0.0, 0.0
        sel = slice(max(0, i - 2), min(len(z), i + 3))
        j = sel.start + int(np.argmax(z[sel]))
        return float(z[j]), float(rho[j])

    cands = [{'offset': float(lags[i]) * hop_s, 'z': float(z[i]), 'r': float(rho[i]), 'how': 'sound'} for i in peaks
             if deep or z[i] >= 5.0]                  # weaker envelope peaks only on the second, deeper pass
    clear = z[k] >= cfg['sure_z'] and (runner_up is None or z[k] - runner_up >= 3.0)
    # sharp hits: offsets where hits of both files line up are candidates too
    if A.hits and B.hits and not clear:
        diffs = {}
        for ta, _ in A.hits:
            for tb, _ in B.hits:
                d = round((ta - tb) / cfg['hit_tol_s'])
                diffs[d] = diffs.get(d, 0) + 1
        for d, nvotes in sorted(diffs.items(), key=lambda kv: -kv[1])[:6]:
            off = d * cfg['hit_tol_s']
            if all(abs(c['offset'] - off) > 0.5 for c in cands):
                ez, er = env_at(off)
                cands.append({'offset': off, 'z': ez, 'r': er, 'how': 'sharp hits', 'hit_votes': nvotes})
    # the waveform over every lag: finds short or buried takes (and repeats) the envelopes miss
    wave_second = None
    if deep and not clear:
        found = _phat_search(A, B)
        for n_found, (off, pz) in enumerate(found):
            if pz < 8.0:
                continue
            near = [c for c in cands if abs(c['offset'] - off) <= 0.05]
            if near:
                near[0]['search_z'] = max(pz, near[0].get('search_z', 0.0))
                near[0]['offset'] = off           # the waveform's offset is the finer one
            elif all(abs(c['offset'] - off) > 0.5 for c in cands):
                ez, er = env_at(off)
                cands.append({'offset': off, 'z': ez, 'r': er, 'how': 'waveform', 'search_z': pz})
        if len(found) > 1:
            wave_second = found[1][1]
    ok = []
    for c in cands:
        off = c['offset']
        ov_b = (max(0.0, -off), min(B.dur, A.dur - off))
        if ov_b[1] - ov_b[0] < min(min_ov, 2.0):
            continue
        chk = _check_windows(A, B, off, ov_b, cfg)
        if not chk:
            continue
        hits = _hits_agree(A, B, chk['mid_offset'], cfg['hit_tol_s'])
        wz = chk.get('waveform_z') or 0.0
        sz = c.get('search_z') or 0.0
        windows_ok = chk['agree'] / chk['n'] >= 0.6
        lone_margin = c['z'] - (runner_up or 0.0)
        # one window is no independent check: it needs the waveform to agree, or an overwhelming match
        checked = ((chk['n'] >= 2 and windows_ok) or wz >= 8.0 or sz >= 15.0
                   or (c['z'] >= cfg['sure_z'] and lone_margin >= 4.0 and windows_ok))
        strong = (c['z'] >= cfg['likely_z'] or (hits >= 2 and c['z'] >= 4.0) or sz >= 12.0
                  or (wz >= 7.0 and c['z'] >= 4.5 and chk['n'] >= 2))     # weak envelope, clear waveform
        if c['how'] == 'waveform':
            # found by the waveform alone: steady hums and tones can line up anywhere, so the waveform must also
            # agree across the whole overlap, and be overwhelming unless the onsets back it
            checked = checked and wz >= 8.0 and (sz >= 15.0 or c['z'] >= 4.0)
        c.update(check=chk, hits_agree=hits, overlap_b=ov_b, runner_up_z=runner_up,
                 score=max(c['z'], 0.6 * sz) + 2.0 * min(hits, 3))
        if checked and strong:
            ok.append(c)
    if not ok:
        return {'why': 'no offset passes the checks', 'z': float(z[k]), 'runner_up_z': runner_up}
    ok.sort(key=lambda c: -c['score'])
    top, rivals = ok[0], ok[1:]
    rival = max([c['score'] for c in rivals], default=None)
    if rival is None:
        unverified = max([v for v in (runner_up, 0.6 * wave_second if wave_second else None) if v is not None],
                         default=None)
        rival = unverified - 1.5 if unverified is not None else 0.0
    margin = top['score'] - rival
    top['margin'] = margin
    if margin >= 3.0 and top['score'] >= cfg['sure_z']:
        top['level'] = 'sure'
    elif margin >= 2.0:
        top['level'] = 'likely'
    else:
        top['level'] = 'ambiguous'
        top['alts'] = [dict(c, level='ambiguous') for c in rivals if c['score'] >= top['score'] - 3.0]
    return top


# ============================================================================ the shoot

def _device_key(path, info):
    """A guess at which device made a file: camera make/model when the file says, else its name pattern."""
    cam = info.get('camera')
    if cam:
        return str(cam)
    stem = Path(path).stem
    m = re.match(r'^([A-Za-z_\- ]*?)[\d_\-]*$', stem)
    prefix = (m.group(1) if m else re.sub(r'\d.*$', '', stem)).strip('_- ') or 'file'
    if stem.upper().startswith(('GX', 'GH', 'GOPR', 'GP')):
        prefix = 'GoPro'
    size = f"{info.get('width')}x{info.get('height')}" if info.get('width') else 'audio'
    return f'{prefix} {Path(path).suffix.lower().lstrip(".")} {size}'


def _collect(files, folder):
    out = []
    folders = [folder] if isinstance(folder, (str, Path)) else list(folder or [])
    for f in files or []:
        if Path(f).is_dir():
            folders.append(f)
        else:
            out.append(str(Path(f).resolve()))
    for d in folders:
        for p in sorted(Path(d).iterdir()):
            if p.is_file() and p.suffix.lower() in MEDIA:
                out.append(str(p.resolve()))
    seen, uniq = set(), []
    for f in out:
        if f.lower() not in seen:
            seen.add(f.lower())
            uniq.append(f)
    return uniq


def _cands(m):
    return [m] + list(m.get('alts') or []) if m and m.get('level') else []


def _solve(names, edges, anchor, tol, clocks=None, devices=None, F=None):
    """Place files by voting from the anchor outwards. edges: {(a, b): match} with A time = B time + offset; an
    'ambiguous' match offers several offsets. A file goes where most weight agrees; an ambiguous offset needs a second
    link or the recording clock (its offset learnt from the device's placed files) to back it, and an offset that
    would make one device film two clips at once counts for little.
    Returns {name: {'at', 'k', 'via', 'level', 'how', 'votes', 'conflicts'}} for the anchor's component."""
    clocks, devices = clocks or {}, devices or {}
    placed = {anchor: {'at': 0.0, 'k': 1.0, 'via': None, 'level': 'reference', 'votes': None, 'conflicts': []}}

    def films_twice(u, at, k):
        if F is None:
            return False
        end = at + k * F[u].dur
        for p, pl in placed.items():
            if p != u and devices.get(p) == devices.get(u):
                pend = pl['at'] + pl['k'] * F[p].dur
                if at < pend - 1.0 and pl['at'] < end - 1.0:
                    return True
        return False

    while True:
        best = None
        for u in names:
            if u in placed:
                continue
            cands = []
            for p, pl in placed.items():
                m, flip = edges.get((p, u)), False
                if m is None and (u, p) in edges:
                    m, flip = edges[(u, p)], True
                for c in _cands(m):
                    a, b = c['check']['line']
                    lv = c['level']
                    sc = c.get('score', c.get('z') or 0.0)
                    w = {'sure': sc + 3.0, 'likely': sc, 'ambiguous': 0.3 * sc, 'assumed': 0.01,
                         'continuous': 50.0}.get(lv, 0.0)
                    if not flip:        # p time = u time * (1 + b) + a
                        at, k = pl['at'] + pl['k'] * a, pl['k'] * (1 + b)
                    else:               # u time = p time * (1 + b) + a  ->  p time = (u time - a) / (1 + b)
                        at, k = pl['at'] - pl['k'] * a / (1 + b), pl['k'] / (1 + b)
                    if films_twice(u, at, k):
                        w *= 0.1
                    cands.append({'at': at, 'k': k, 'w': w, 'from': p, 'level': lv, 'z': sc})
            if not cands:
                continue
            guess = _clock_guess(u, placed, clocks, devices)
            groups = []
            for c in cands:
                votes = [d for d in cands if abs(d['at'] - c['at']) <= tol]
                score = sum(d['w'] for d in votes)
                by_clock = guess is not None and abs(c['at'] - guess) <= 3.0
                if by_clock:
                    score += max(d['z'] for d in votes)
                groups.append((score, c['w'], c, votes, by_clock))
            score, _, top, votes, by_clock = max(groups, key=lambda g: (g[0], g[1]))
            sources = {d['from'] for d in votes}
            if all(d['level'] == 'ambiguous' for d in votes) and len(sources) < 2 and not by_clock:
                continue                # an ambiguous offset alone does not place a file
            if best is None or score > best[0]:
                best = (score, u, top, votes, [d for d in cands if d not in votes], by_clock, sources)
        if best is None:
            return placed
        score, u, top, votes, against, by_clock, sources = best
        level, how = top['level'], None
        if all(d['level'] == 'ambiguous' for d in votes):
            level = 'likely'
            how = 'repeating sound; picked by ' + ('the recording clock' if by_clock else
                                                   f'{len(sources)} files agreeing')
        placed[u] = {'at': top['at'], 'k': top['k'], 'via': top['from'], 'level': level, 'how': how,
                     'votes': sorted(sources),
                     'conflicts': [{'with': d['from'], 'would_be_at': _r(d['at'], 3)} for d in against
                                   if d['level'] != 'ambiguous']}


def _clock_guess(u, placed, clocks, devices):
    """Where u's recording clock puts it on the timeline, through the clock offset of its device's placed files (or
    of every placed file when those agree within 3 s), or None."""
    if clocks.get(u) is None:
        return None
    same = [p for p in placed if clocks.get(p) is not None and devices.get(p) == devices.get(u)]
    pool = same or [p for p in placed if clocks.get(p) is not None]
    if not pool:
        return None
    bias = [placed[p]['at'] - clocks[p] for p in pool]
    if np.ptp(bias) > 3.0:
        return None
    return clocks[u] + float(np.median(bias))


def _near(A, B, off, reach_s, cfg):
    """Best offset of B against A within +-reach_s of `off`, scored against that stretch of lags only.
    Returns (offset_s, local z) or None."""
    hop_s = A.hop / A.sr
    n_ov = max(8, int(min(cfg['min_overlap_s'], 0.8 * min(A.dur, B.dur)) / hop_s))
    lo = max(-(len(B.env) - n_ov), int(math.floor((off - reach_s) / hop_s)))
    hi = min(len(A.env) - n_ov, int(math.ceil((off + reach_s) / hop_s)))
    if hi - lo < 20:
        return None
    lags, rho, cnt, z = _scored_lags(A.env, B.env, lo, hi, n_ov)
    k = int(np.argmax(z))
    return float(lags[k]) * hop_s, float(z[k])


def _rescue(names, placed, F, clocks, devices, edges, cfg):
    """Files sound alone could not place: look again only near where the recording clock puts them, or where a
    loud clap of theirs lines up with a sharp hit of a placed file. A narrow search can trust a weaker match.
    Returns the files placed this way."""
    done = []
    grew = True
    while grew:
        grew = False
        for u in names:
            if u in placed:
                continue
            B = F[u]
            best = None
            guess = _clock_guess(u, placed, clocks, devices)
            own = sorted(B.hits, key=lambda h: -h[1])
            clap = own[0] if own and own[0][1] >= 20 and (len(own) < 2 or own[0][1] - own[1][1] >= 6) else None
            for p in sorted(placed):
                A, pl = F[p], placed[p]
                tries = []
                if guess is not None:
                    tries.append((guess - pl['at'], 3.0, 'sound near the recording clock'))
                if clap is not None:
                    for th, _ in A.hits:
                        tries.append((th - clap[0], 0.1, 'a clap'))
                for off0, reach, how in tries:
                    got = _near(A, B, off0, max(reach, 0.3), cfg)
                    if got is None or abs(got[0] - off0) > reach + 0.02:
                        continue
                    off, zl = got
                    if zl < (5.0 if how != 'a clap' else 4.0):
                        continue
                    if how == 'a clap':
                        off = off0                  # the clap itself is the finer measure (2 ms)
                    ov_b = (max(0.0, -off), min(B.dur, A.dur - off))
                    chk = _check_windows(A, B, off, ov_b, cfg) if ov_b[1] - ov_b[0] >= 2.0 else None
                    if not chk:
                        continue
                    if how == 'a clap':             # in loud noise the windows cannot agree; the clap must
                        hits = _hits_agree(A, B, off, cfg['hit_tol_s'])
                        if hits < 1:
                            continue
                        if chk['agree'] / chk['n'] < 0.6 or (chk.get('waveform_z') or 0) < 6.0:
                            chk = dict(chk, line=(off, 0.0), mid_offset=off, sigma_s=0.002, slope_se=None)
                    else:
                        if chk['agree'] / chk['n'] < 0.6 or (chk.get('waveform_z') or 0) < 5.0:
                            continue
                        hits = _hits_agree(A, B, chk['mid_offset'], cfg['hit_tol_s'])
                    score = zl + (chk.get('waveform_z') or 0) / 2 + 2 * min(hits, 3)
                    if best is None or score > best[0]:
                        best = (score, p, {'offset': off, 'z': zl, 'how': how, 'check': chk, 'hits_agree': hits,
                                           'level': 'likely', 'overlap_b': ov_b})
            if best is None:
                continue
            _, p, m = best
            edges.pop((u, p), None)
            edges[(p, u)] = m
            a, b = m['check']['line']
            pl = placed[p]
            placed[u] = {'at': pl['at'] + pl['k'] * a, 'k': pl['k'] * (1 + b), 'via': p, 'level': 'likely',
                         'how': m['how'], 'votes': [p], 'conflicts': []}
            done.append(u)
            grew = True
    return done


def _agreeing(m, pA, pB, tol):
    """The offset of match m (best or an alternative) that agrees with where A and B were placed, or None."""
    for c in _cands(m):
        a, b = c['check']['line']
        tm = c['check'].get('mid', 0.0)
        implied = pA['at'] + pA['k'] * (a + (1 + b) * tm) - pB['k'] * tm
        if abs(implied - pB['at']) <= tol:
            return c
    return None


def _refine(placed, edges, anchor, tol):
    """Least squares over every match that agrees with the voted placement: clock rates first (log k), then
    positions, each weighted by how tightly its windows agreed. Several links to a file average out their errors."""
    names = [n for n in placed if n != anchor]
    if not names:
        return
    idx = {n: i for i, n in enumerate(names)}
    used = []
    for (A, B), m in edges.items():
        if A not in placed or B not in placed:
            continue
        c = _agreeing(m, placed[A], placed[B], tol)
        if c is None:
            continue
        a, b = c['check']['line']
        tm = c['check'].get('mid', 0.0)
        sig = c['check'].get('sigma_s') or 0.05
        se = c['check'].get('slope_se') or 2e-4
        used.append((A, B, a, b, tm, sig, se))
    if not used:
        return

    def solve(rows, rhs, w):
        M = np.array(rows) * np.sqrt(w)[:, None]
        x, *_ = np.linalg.lstsq(M, np.array(rhs) * np.sqrt(w), rcond=None)
        return x

    def row(A, B):
        v = np.zeros(len(names))
        if B in idx:
            v[idx[B]] += 1
        if A in idx:
            v[idx[A]] -= 1
        return v

    rows, rhs, w = [], [], []
    for A, B, a, b, tm, sig, se in used:
        rows.append(row(A, B))
        rhs.append(math.log1p(b))
        w.append(1.0 / se ** 2)
    logk = solve(rows, rhs, np.array(w))
    k = {n: math.exp(logk[idx[n]]) for n in names}
    k[anchor] = 1.0
    rows, rhs, w = [], [], []
    for A, B, a, b, tm, sig, se in used:
        rows.append(row(A, B))
        rhs.append(k[A] * (a + (1 + b) * tm) - k[B] * tm)
        w.append(1.0 / sig ** 2)
    pos = solve(rows, rhs, np.array(w))
    linked = {n: [] for n in names}
    for A, B, *_ in used:
        if A in linked:
            linked[A].append(B)
        if B in linked:
            linked[B].append(A)
    inv = {n: 0.0 for n in names}
    for A, B, a, b, tm, sig, se in used:
        for x in (A, B):
            if x in inv:
                inv[x] += 1.0 / sig ** 2
    for n in names:
        if linked[n]:
            placed[n].update(at=float(pos[idx[n]]), k=k[n], links=sorted(set(linked[n])), sigma=inv[n] ** -0.5)


def _continuous(names, F, devices, placed, edges):
    """Files of one recorder that sound puts end to end (within 0.1 s) are one recording split into files: link them
    sample-exactly. Returns the number of such joins."""
    n = 0
    for dev in sorted(set(devices[x] for x in names)):
        files = sorted(x for x in names if devices[x] == dev and F[x].audio_only and x in placed)
        for prev, nxt in zip(files, files[1:]):
            gap = placed[nxt]['at'] - (placed[prev]['at'] + placed[prev]['k'] * F[prev].dur)
            if abs(gap) < 0.1:
                edges[(prev, nxt)] = {'level': 'continuous', 'how': 'one recording split into files', 'z': 50.0,
                                      'gap_by_sound_ms': _r(gap * 1000, 2),
                                      'check': {'line': (F[prev].dur, 0.0), 'mid': 0.0, 'sigma_s': 1e-4,
                                                'slope_se': 1e-7, 'agree': 0, 'n': 0, 'windows': []}}
                edges.pop((nxt, prev), None)
                n += 1
    return n


def _clocks(names, infos, F):
    """Recording start per file from its metadata, in seconds after the earliest one (None where a file has none)."""
    import letitedit.server.core_tools as core_tools
    starts = {}
    for n in names:
        try:
            starts[n] = core_tools.rec_start(infos[n])
        except Exception:  # noqa: BLE001
            starts[n] = None
    known = [v for v in starts.values() if v is not None]
    if not known:
        return {}
    t0 = min(known)
    return {n: ((v - t0).total_seconds() if v is not None else None) for n, v in starts.items()}


def _split_edges(names, F, devices, edges):
    """A recorder that splits one recording into files: each next file of the same audio-only device gets a weak
    'assumed' link right after the one before, used only when sound links nothing else to it."""
    for dev in sorted(set(devices[n] for n in names)):
        files = sorted(n for n in names if devices[n] == dev and F[n].audio_only)
        for prev, nxt in zip(files, files[1:]):
            m = edges.get((prev, nxt)) or edges.get((nxt, prev))
            if m and m.get('level'):
                continue
            edges[(prev, nxt)] = {'level': 'assumed', 'how': 'next file of a split recording', 'z': 0.1,
                                  'check': {'line': (F[prev].dur, 0.0), 'agree': 0, 'n': 0, 'windows': []}}


def _load_recordings(core_tools, devices, hop, paths, sr):
    F, infos, silent = {}, {}, []
    for p in paths:
        info = core_tools.probe(p)
        infos[p] = info
        if not info.get('audio'):
            silent.append(p)
            continue
        y = _decode(p, sr)
        if not y.size or float(np.abs(y).max(initial=0)) < 1e-5:
            silent.append(p)
            continue
        F[p] = _File(p, info, y, sr, hop)
    names = list(F)
    dev = {p: _device_key(p, infos[p]) for p in paths}
    for k, v in (devices or {}).items():
        for p in paths:
            if Path(p).name.lower() == Path(k).name.lower() or p.lower() == str(Path(k).resolve()).lower():
                dev[p] = str(v)
    return F, infos, silent, names, dev


def _match_recordings(F, cfg, dev, infos, names):
    clocks = _clocks(names, infos, F)
    edges = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            A, B = (F[a], F[b]) if F[a].dur >= F[b].dur else (F[b], F[a])
            if dev[a] == dev[b] and clocks.get(a) is not None and clocks.get(b) is not None and (
                    clocks[a] + F[a].dur < clocks[b] - 2.0 or clocks[b] + F[b].dur < clocks[a] - 2.0):
                edges[(A.path, B.path)] = {'why': 'same device, recorded at other times (by its clock)'}
                continue
            edges[(A.path, B.path)] = _match(A, B, cfg)
    return clocks, edges


def _place_recordings(F, cfg, clocks, dev, edges, names, ref):
    def place():
        got = _solve(names, edges, ref, cfg['place_tol_s'], clocks, dev, F)
        _refine(got, edges, ref, cfg['place_tol_s'])
        if _continuous(names, F, dev, got, edges):
            _refine(got, edges, ref, cfg['place_tol_s'])
        return got

    placed = place()
    # second pass, only for what is left: search the waveform itself against every placed file (slower, finds short
    # or buried takes), then solve again
    deeper = False
    for u in [n for n in names if n not in placed]:
        for p in sorted(placed):
            if edges.get((p, u), {}).get('level') or edges.get((u, p), {}).get('level'):
                continue
            A, B = (F[p], F[u]) if F[p].dur >= F[u].dur else (F[u], F[p])
            if 'same device' in str(edges.get((A.path, B.path), {}).get('why', '')):
                continue
            m = _match(A, B, cfg, deep=True)
            if m.get('level'):
                edges[(A.path, B.path)] = m
                deeper = True
    if deeper:
        placed = place()
    if _rescue(names, placed, F, clocks, dev, edges, cfg):
        _refine(placed, edges, ref, cfg['place_tol_s'])
    # other groups: linked to each other, not to the reference
    groups, rest = [], [n for n in names if n not in placed]
    while rest:
        aud = [p for p in rest if F[p].audio_only]
        a = max(aud or rest, key=lambda p: F[p].dur)
        g = _solve(rest, edges, a, cfg['place_tol_s'], clocks, dev, F)
        if len(g) > 1:
            groups.append({'anchor': a, 'files': {n: {'at': _r(v['at'], 4)} for n, v in g.items()}})
        rest = [n for n in rest if n not in g]

    return placed, groups


def _sync_timeline_rows(F, cfg, dev, edges, fix_drift, fps, infos, names, placed, ref):
    # timeline: drift, speed, shift so the earliest file starts at 0
    fps_v = float(fps or next((infos[p].get('fps') for p in names if infos[p].get('fps')), 30.0) or 30.0)
    rows = {}
    for n, pl in placed.items():
        k, at = pl['k'], pl['at']
        dur = F[n].dur
        drift_s = (k - 1.0) * dur
        speed = 1.0
        fixed = False
        if n != ref and fix_drift and abs(drift_s) > cfg['drift_fix_frames'] / fps_v:
            speed, fixed = 1.0 / k, True
        elif n != ref:
            at = at + (k - 1.0) * dur / 2          # no speed change: right in the middle, half the drift at each end
        rows[n] = {'file': n, 'device': dev[n], 'at': at, 'duration_s': dur, 'speed': speed, 'drift_fixed': fixed,
                   'drift_ms_over_clip': _r(drift_s * 1000, 2), 'drift_ppm': _r((k - 1.0) * 1e6, 1),
                   'level': 'reference' if n == ref else pl.get('level'), 'via': pl.get('via'),
                   'links': [Path(x).name for x in pl.get('links') or []], 'votes': pl.get('votes'), 'conflicts': pl.get('conflicts') or []}
        if n != ref:
            m0 = edges.get((pl['via'], n))
            m = _agreeing(m0, placed[pl['via']], pl, cfg['place_tol_s']) if m0 else None
            if m0 is None:
                m0 = edges.get((n, pl['via']))
                m = _agreeing(m0, pl, placed[pl['via']], cfg['place_tol_s']) if m0 else None
            m = m or m0
            if pl.get('how'):
                rows[n]['how'] = pl['how']
            if m and m.get('check'):
                rows[n]['evidence'] = {'how': m.get('how'), 'match_z': _r(m.get('z'), 2), 'envelope_r': _r(m.get('r'), 3),
                                       'runner_up_z': _r(m.get('runner_up_z'), 2),
                                       'windows_agree': f"{m['check']['agree']}/{m['check']['n']}",
                                       'window_spread_ms': _r(1000 * float(np.std([w['offset'] for w in m['check']['windows']]
                                                                                   or [0])), 2),
                                       'sharp_hits_agree': m.get('hits_agree'), 'waveform_z': m['check'].get('waveform_z'),
                                       'waveform_shift_ms': m['check'].get('waveform_shift_ms'), 'windows': m['check']['windows']}
                sig = pl.get('sigma') or m['check'].get('sigma_s') or 0.004
                rows[n]['precision'] = ('about 0.5 ms' if sig < 1e-3 else 'about 2 ms' if sig < 3e-3 else
                                        'up to about 20 ms: the waveform could not confirm it')
    shift = -min(r['at'] for r in rows.values())
    ref_at = rows[ref]['at'] + shift            # the reference starts on a frame: its sound is what is heard
    shift += math.ceil(ref_at * fps_v - 1e-9) / fps_v - ref_at
    for r in rows.values():
        r['at'] = r['at'] + shift
        r['end'] = r['at'] + r['duration_s'] / r['speed']
    return fps_v, rows


def _sync_warnings(F, clocks, edges, groups, names, placed, rows, silent):
    # same device overlapping itself: two devices, or a wrong match
    by_dev = {}
    for r in sorted(rows.values(), key=lambda r: r['at']):
        by_dev.setdefault(r['device'], []).append(r)
    warnings, notes = [], []
    for d, rs in by_dev.items():
        for x, y in zip(rs, rs[1:]):
            if y['at'] < x['end'] - 0.5:
                cx, cy = clocks.get(x['file']), clocks.get(y['file'])
                both = (f'{Path(x["file"]).name} and {Path(y["file"]).name} look like one device ({d}) but overlap by '
                        f'{x["end"] - y["at"]:.1f} s')
                if cx is not None and cy is not None and cx < cy + F[y['file']].dur and cy < cx + F[x['file']].dur:
                    notes.append(both + ': their own clocks overlap too, so they are two devices of one model (put on '
                                 'separate tracks; `devices` names them)')
                else:
                    warnings.append(both + ': two devices of one model (give `devices`), or a wrong match')
    for r in rows.values():
        if str(r.get('precision', '')).startswith('up to'):
            warnings.append(f'{Path(r["file"]).name}: placed by the shape of its sound only (its waveform is too buried '
                            'in noise or echo to confirm), so it may be off by up to about 20 ms; check a clap or a '
                            'sharp sound by eye (sheet=True shows the cameras at one)')
    unplaced = []
    for n in names:
        if n in placed:
            continue
        best = max(((edges.get((n, m)) or edges.get((m, n)) or {}).get('z') or -1, m) for m in names if m != n)
        unplaced.append({'file': n, 'why': 'its sound matches no other file well enough',
                         'best_match_z': _r(best[0], 2), 'best_with': Path(best[1]).name if best[0] > -1 else None,
                         'in_group': next((g['anchor'] for g in groups if n in g['files']), None)})
    for p in silent:
        unplaced.append({'file': p, 'why': 'no sound to sync by'})
    return warnings, notes, unplaced


def sync_shoot(files=None, folder=None, reference=None, project=None, synced_clips=None, devices=None,
               fix_drift=True, fps=None, sheet=False, out_dir=None, **settings):
    """Line up every file of a shoot on one timeline by sound.

    files / folder  the recordings (any mix of video and audio files; a folder is read one level deep).
    reference       the file the timeline is measured from (default: the longest audio-only file, else the longest).
    devices         {file name or path: device name} where the guess from metadata and names is wrong.
    project         write a letitedit project here: one video track per camera (main camera on V1), the recorders'
                    sound on audio tracks, the cameras' own sound muted when a recorder covers them.
    synced_clips    a folder: write a copy of every placed camera clip with the recorder's sound in place of its own
                    (picture copied untouched; drift corrected in the sound), ready for any other tool.
    sheet           also draw the timeline (lanes per device, clips colored by level, sharp hits) and the cameras'
                    frames at a sharp hit side by side; saved in out_dir (default a new temp folder).
    fix_drift       correct clock drift with a tiny speed change when it would move a clip end by more than
                    drift_fix_frames frames (default True).
    settings        any of DEFAULTS (rate, hop_s, min_overlap_s, sure_z, likely_z, window_s, windows_max, agree_s,
                    place_tol_s, drift_fix_frames, hit_tol_s).

    Returns the timeline (per file: at, in/out, speed, level sure/likely/assumed, how it was placed, the match
    evidence and drift), files that could not be placed and why, groups linked to each other but not to the reference,
    sharp hits found per file, and every setting used."""
    import letitedit.server.core_tools as core_tools
    t_start = time.time()
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in settings.items() if v is not None and k in DEFAULTS})
    unknown = [k for k in settings if k not in DEFAULTS]
    if unknown:
        raise ValueError(f'unknown settings {unknown}; known: {sorted(DEFAULTS)}')
    paths = _collect(files, folder)
    if len(paths) < 2:
        raise ValueError('give two or more files (or a folder holding them)')
    sr = int(cfg['rate'])
    hop = max(1, int(round(sr * cfg['hop_s'])))
    F, infos, silent, names, dev = _load_recordings(core_tools, devices, hop, paths, sr)

    clocks, edges = _match_recordings(F, cfg, dev, infos, names)

    if reference:
        ref = next((p for p in names if Path(p).name.lower() == Path(reference).name.lower()
                    or p.lower() == str(Path(reference).resolve()).lower()), None)
        if ref is None:
            raise ValueError(f'reference {reference} is not among the files with sound')
    else:
        aud = [p for p in names if F[p].audio_only]
        ref = max(aud or names, key=lambda p: F[p].dur)

    _split_edges(names, F, dev, edges)

    placed, groups = _place_recordings(F, cfg, clocks, dev, edges, names, ref)
    fps_v, rows = _sync_timeline_rows(F, cfg, dev, edges, fix_drift, fps, infos, names, placed, ref)
    warnings, notes, unplaced = _sync_warnings(F, clocks, edges, groups, names, placed, rows, silent)

    matches = []
    for (a, b), m in sorted(edges.items(), key=lambda kv: -(kv[1].get('z') or 0)):
        if (m.get('z') or 0) < 4.0 or m.get('level') in ('assumed', 'continuous'):
            continue
        chk = m.get('check') or {}
        matches.append({'a': Path(a).name, 'b': Path(b).name, 'offset_s': _r(chk.get('mid_offset', m.get('offset')), 4),
                        'z': _r(m.get('z'), 2), 'runner_up_z': _r(m.get('runner_up_z'), 2), 'level': m.get('level'),
                        'how': m.get('how'), 'windows_agree': f"{chk.get('agree')}/{chk.get('n')}" if chk else None,
                        'sharp_hits_agree': m.get('hits_agree')})
    timeline = [{**r, 'at': _r(r['at'], 4), 'end': _r(r['end'], 4), 'duration_s': _r(r['duration_s'], 3),
                 'speed': _r(r['speed'], 8)} for r in sorted(rows.values(), key=lambda r: (r['at'], r['file']))]
    result = {'reference': ref, 'timeline': timeline, 'not_placed': unplaced, 'other_groups': groups,
              'matches': matches, 'notes': notes,
              'warnings': warnings,
              'sharp_hits': {Path(n).name: [_r(t, 3) for t, _ in sorted(F[n].hits)[:12]] for n in names if F[n].hits},
              'meaning': 'timeline time = at + file time / speed; level: reference | sure | likely | assumed',
              'settings': {**cfg, 'fix_drift': fix_drift, 'fps': fps_v}}
    if sheet:
        import letitedit.sound.av_tools as av_tools
        folder_out = av_tools._out_dir('sync', out_dir)
        result['sheet'] = _draw_timeline(folder_out / 'sync-timeline.png', timeline, unplaced, F)
        result['frames_sheet'] = _draw_hit_frames(folder_out / 'sync-frames-at-hit.jpg', timeline, F)
    if project and synced_clips is None and any(F[r['file']].audio_only for r in timeline):
        synced_clips = str(Path(project).with_name(Path(project).stem + ' synced clips'))
    if synced_clips:
        result['synced_clips'] = _write_synced(synced_clips, timeline, F)
    if project:
        result['project'] = _write_project(project, timeline, F, fps_v,
                                           {c['from']: c['file'] for c in result.get('synced_clips') or []})
    result['seconds'] = _r(time.time() - t_start, 2)
    if sheet:
        import json
        result['details_file'] = str(folder_out / 'sync.json')
        (folder_out / 'sync.json').write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
    return result


# ============================================================================ outputs

_COLORS = {'reference': (42, 133, 151), 'sure': (76, 160, 90), 'likely': (214, 160, 50), 'assumed': (120, 130, 150),
           'continuous': (120, 130, 150)}


def _font(size):
    from PIL import ImageFont
    for f in ('segoeui.ttf', 'arial.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_timeline(path, timeline, unplaced, F):
    """Lanes per device, every placed file as a bar colored by how sure, sharp hits as ticks, time ruler."""
    from PIL import Image, ImageDraw
    W, left, lane_h, top = 1600, 230, 34, 40
    devs = []
    for r in sorted(timeline, key=lambda r: (not F[r['file']].audio_only, r['device'])):
        if r['device'] not in devs:
            devs.append(r['device'])
    end = max(r['end'] for r in timeline) or 1.0
    sx = (W - left - 20) / end
    H = top + lane_h * len(devs) * 2 + 30 + 18 * (len(unplaced) + 1)
    im = Image.new('RGB', (W, H), (22, 26, 29))
    d = ImageDraw.Draw(im)
    f, fs = _font(14), _font(12)
    step = next(x for x in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600) if end / x <= 16)
    for t in np.arange(0, end + 1e-6, step):
        x = left + t * sx
        d.line([(x, top - 6), (x, H - 18 * (len(unplaced) + 1) - 10)], fill=(50, 56, 60))
        d.text((x + 2, 8), f'{int(t // 60)}:{int(t % 60):02d}', fill=(170, 170, 170), font=fs)
    y = top
    for dv in devs:
        rows = [r for r in timeline if r['device'] == dv]
        lanes = _lanes(rows)
        for lane in lanes:
            d.text((8, y + 8), dv[:30], fill=(220, 220, 220), font=f)
            for r in lane:
                x0, x1 = left + r['at'] * sx, left + r['end'] * sx
                col = _COLORS.get(str(r['level']).split(' ')[0], (150, 150, 150))
                d.rectangle([x0, y + 4, max(x0 + 2, x1), y + lane_h - 4], fill=col)
                d.text((x0 + 4, y + 9), Path(r['file']).name, fill=(255, 255, 255), font=fs)
                for t, _ in F[r['file']].hits:
                    xt = left + (r['at'] + t / r['speed']) * sx
                    d.line([(xt, y + 2), (xt, y + 8)], fill=(255, 240, 120), width=2)
            y += lane_h
    y += 10
    d.text((8, y), 'reference = teal, sure = green, likely = amber, assumed = grey; yellow ticks = sharp hits',
           fill=(170, 170, 170), font=fs)
    for u in unplaced:
        y += 18
        d.text((8, y), f'not placed: {Path(u["file"]).name} - {u["why"]}', fill=(230, 140, 110), font=fs)
    im.save(path)
    return str(path)


def _draw_hit_frames(path, timeline, F):
    """At the strongest sharp hit that two or more cameras (or one camera and a recorder) cover: each camera's frame
    there, side by side, labelled. None when no such hit."""
    import letitedit.server.core_tools as core_tools
    from PIL import Image, ImageDraw
    cams = [r for r in timeline if not F[r['file']].audio_only]
    best = None
    for r in timeline:
        for t, strength in F[r['file']].hits:
            T = r['at'] + t / r['speed']
            cover = [c for c in cams if c['at'] + 0.2 <= T <= c['end'] - 0.2]
            if cover and (len(cover) >= 2 or F[r['file']].audio_only):
                key = (len(cover), strength)
                if best is None or key > best[0]:
                    best = (key, T, cover)
    if best is None:
        return None
    _, T, cover = best
    tiles = []
    for c in cover[:6]:
        im = core_tools._thumb(c['file'], (T - c['at']) * c['speed'], width=360)
        if im is None:
            continue
        band = Image.new('RGB', (im.width, 24), (22, 26, 29))
        ImageDraw.Draw(band).text((6, 4), f'{Path(c["file"]).name} @ {(T - c["at"]) * c["speed"]:.2f}s',
                                  fill=(235, 235, 235), font=_font(13))
        tile = Image.new('RGB', (im.width, im.height + 24))
        tile.paste(band, (0, 0))
        tile.paste(im, (0, 24))
        tiles.append(tile)
    if not tiles:
        return None
    h = max(t.height for t in tiles)
    out = Image.new('RGB', (sum(t.width for t in tiles) + 6 * (len(tiles) - 1), h + 28), (22, 26, 29))
    x = 0
    for t in tiles:
        out.paste(t, (x, 28))
        x += t.width + 6
    ImageDraw.Draw(out).text((6, 6), f'every camera at the sharp hit at timeline {T:.3f} s', fill=(255, 240, 120),
                             font=_font(14))
    out.save(path, quality=88)
    return str(path)

def _lanes(rows):
    """Rows packed into lanes so no two overlap (one lane per device unless a device overlaps itself)."""
    lanes = []
    for r in sorted(rows, key=lambda r: r['at']):
        for lane in lanes:
            if lane[-1]['end'] <= r['at'] + 1e-6:
                lane.append(r)
                break
        else:
            lanes.append([r])
    return lanes


def _write_project(project, timeline, F, fps, synced=None):
    """Cameras on video tracks (the most-used device on V1), recorders on audio tracks. With synced copies the
    cameras are those copies, carrying the recorder's sound sample-exactly, and the recorder tracks are muted (kept
    for reference); without, the cameras' own sound is muted where a recorder covers them (positions are whole
    frames there, so sound and picture can differ by up to half a frame)."""
    import letitedit.timeline.edit_import as edit_import
    synced = synced or {}
    cams = [r for r in timeline if not F[r['file']].audio_only]
    recs = [r for r in timeline if F[r['file']].audio_only]
    cover = [(r['at'], r['end']) for r in recs]
    by_dev = {}
    for r in cams:
        by_dev.setdefault(r['device'], []).append(r)
    order = sorted(by_dev, key=lambda d: -sum(r['end'] - r['at'] for r in by_dev[d]))
    tracks, vt = [], 0
    for d in order:
        for lane in _lanes(by_dev[d]):
            vt += 1
            items = []
            for r in lane:
                if r['file'] in synced:      # sound already in the clip, sample-exact; the picture is untouched
                    items.append({'clip': synced[r['file']], 'in': 0.0, 'out': r['duration_s'], 'at': r['at'],
                                  'name': Path(r['file']).name})
                    continue
                it = {'clip': r['file'], 'in': 0.0, 'out': r['duration_s'], 'at': r['at'], 'name': Path(r['file']).name}
                if abs(r['speed'] - 1.0) > 1e-9:
                    it['speed'] = r['speed']
                covered = sum(max(0.0, min(e, r['end']) - max(s, r['at'])) for s, e in cover)
                if covered >= 0.5 * (r['end'] - r['at']):
                    it['effects'] = ['mute']
                items.append(it)
            tracks.append({'name': f'V{vt}', 'kind': 'video', 'items': items})
    rdev = {}
    for r in recs:
        rdev.setdefault(r['device'], []).append(r)
    at = 0
    for d in sorted(rdev):
        for lane in _lanes(rdev[d]):
            at += 1
            tracks.append({'name': f'A{at}', 'kind': 'audio', 'items': [
                {'clip': r['file'], 'in': 0.0, 'out': r['duration_s'], 'at': r['at'], 'name': Path(r['file']).name,
                 **({'speed': r['speed']} if abs(r['speed'] - 1.0) > 1e-9 else {}),
                 **({'effects': ['mute']} if synced else {})} for r in lane]})
    out = edit_import.import_edit({'tracks': tracks}, project, form='list', fps=fps)
    out['layout'] = {t['name']: [Path(i['clip']).name for i in t['items']] for t in tracks}
    out['sound'] = ('the camera clips are the synced copies (recorder sound inside, sample-exact); the recorder '
                    'tracks are muted, kept for reference') if synced else         "the recorder tracks play; the cameras' own sound is muted where a recorder covers them"
    return out


def _write_synced(folder, timeline, F, rate=48000):
    """Each camera clip with the recorders' sound over its span (its own sound where no recorder covers it)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    recs = [r for r in timeline if F[r['file']].audio_only]
    sound = {}
    made = []
    for r in timeline:
        if F[r['file']].audio_only:
            continue
        dur = r['duration_s']
        n = int(round(dur * rate))
        t_file = np.arange(n) / rate
        t_line = r['at'] + t_file / r['speed']
        own = _decode(r['file'], rate)
        out = np.zeros(n, np.float32)
        out[:min(n, len(own))] = own[:n]
        covered = np.zeros(n, bool)
        for q in recs:
            mask = (t_line >= q['at']) & (t_line < q['end'])
            if not mask.any():
                continue
            if q['file'] not in sound:
                sound[q['file']] = _decode(q['file'], rate)
            y = sound[q['file']]
            src = (t_line[mask] - q['at']) * q['speed'] * rate
            out[mask] = np.interp(src, np.arange(len(y)), y).astype(np.float32)
            covered |= mask
        if not covered.any():
            continue
        path = folder / f'{Path(r["file"]).stem} synced{Path(r["file"]).suffix}'
        cmd = [_ffmpeg(), '-v', 'error', '-y', '-nostdin', '-threads', '4', '-i', r['file'],
               '-f', 'f32le', '-ar', str(rate), '-ac', '1', '-i', '-', '-map', '0:v:0', '-map', '1:a:0',
               '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-ac', '2', '-map_metadata', '0', '-shortest', str(path)]
        proc = subprocess.run(cmd, input=out.tobytes(), capture_output=True, creationflags=NO_WINDOW)
        if proc.returncode:
            raise RuntimeError(f'could not write {path}: {proc.stderr.decode(errors="replace")[-300:]}')
        made.append({'file': str(path), 'from': r['file'], 'recorder_sound_s': _r(covered.sum() / rate, 2),
                     'own_sound_s': _r((~covered).sum() / rate, 2)})
    return made
