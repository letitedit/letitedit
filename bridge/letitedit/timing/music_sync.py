"""Music against picture for the timing layer: the 'music' lane and the 'sync' view (builder B4, TIMING-SPEC.md).

    song_grid(path, settings=None, refresh=False) -> one audio file's beat grid: beats (refined to their transients),
        downbeats and bars (3/4 or 4/4 per song), tempo, phrases, drops, energy by bar, energy sections, loudness
        every 0.1 s, how sure the beat finder is (beat_confidence, beat_quality)
    music(source, settings=None, refresh=False) -> the 'music' lane of a project or a video without the store
    lane(ctx)       -> the 'music' lane for timing_signals (registered at import when the store is importable)
    sync(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief')
                    -> the 'sync' view: picture events (cuts, motion peaks, visual beats, text pops, SFX onsets)
                       against the beat grid, in frames; speech gaps against music swells; song sections against
                       story sections; SFX against the impacts they belong to; images (paths) to look at
    register()      -> registers the lane and the view (called at import; safe to call again)

Where the beats come from
- The beat finder (bridge/beat_finder.py): Beat This! (Foscarin, Schlueter & Widmer, ISMIR 2024; MIT, checkpoint 'final0'), shipped with the app and run on the CPU with ONNX
  Runtime. It gives a beat and a downbeat probability every 20 ms. Its own peak picking drops beats on soft acoustic music, so the beats are placed here by dynamic programming
  over that probability (Ellis 2007) with a local tempo from a tempogram path, the metrical level chosen by the probability's and the onset envelope's autocorrelation with a mild
  tempo preference, every beat moved to its transient (soundtrack._refine: the sharpest 1 ms energy rise within 35 ms), and bars from a small bar-position HMM over the downbeat
  probability (3/4 or 4/4, bars may be cut short). Measured on synthetic songs with exact beats (cache\\timing-tests\\b4): beat F 0.97-1.00 on all nine styles, downbeats 1.00 on eight.
- There is no other beat finder (4 Nov). If it can't run on a file, the grid is empty and beat_finder_error says why: nothing guesses.
- beat_confidence is the mean beat probability at the chosen beats (0-1); beat_quality: clear / weak / none from the thresholds sync.beat_clear_min / sync.beat_weak_min.

Where the music is analysed
- A project: every music clip's own file (tracks named music/song/score/bed, or long audio-only files on other
  non-effects tracks), mapped through the timeline: in/out, speed, the crossfade into the next piece (each piece owns
  its beats up to the middle of the crossfade), clip and track gain (static and keyframes) and audio fades. The
  level as heard is the song's K-weighted loudness every 0.1 s plus that gain (the master and Shotcut's track
  auto-duck are not modelled: the lane says so).
- A video: its own sound, or the music stem (Demucs htdemucs, model_tools.separate: drums + bass + other) when
  someone talks in it (options/settings stem: auto | separate | mix). The lane's `stem` says which.

Every measure in the view names its unit, method and the threshold used (bridge/timing_thresholds.json, keys 'sync.').
Offsets are signed frames on the edit's own grid: offset = event - beat, so a positive offset is a picture event
after the beat (the beat's sound leads the picture). Nothing is judged good or bad without its number; the
references (AOTC Dune: hard hits with the sound about half a frame before the cut) are reported as references.
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.append(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))   # started with -I, which leaves this folder off sys.path; last, so it shadows nothing
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)


# ---- this module's parts: every name in them imported back, so each is the same object as before
# the settings, small helpers and the thresholds
from letitedit.timing.music_sync_base import (  # noqa: E402,F401
    _SAI_ROOT, CACHE_ROOT, THRESHOLDS_FILE, NO_WINDOW, LANE, LANE_VERSION, SONG_VERSION, SCHEMA_VERSION, SR,
    BT_FPS, CHECKPOINT, LAG_LO, LAG_HI, MUSIC_NAME, SFX_NAME, VOICE_NAME, AUDIO_EXT, DEFAULTS, THRESHOLDS, _r,
    _clock, _hash, _clean, _write_json, _read_json, _file_key, _decode, _TH, _thresholds_file, th, used_thresholds,
    merge_thresholds, TRAJECTORY_DEFAULTS
)
# picture events, the measures, speech against music, song sections against story sections, SFX against impacts
from letitedit.timing.music_sync_measure import (  # noqa: E402,F401
    _lane_events, _fallback_motion, _sfx_onset_in_clip, picture_events, _beat_arrays, _nearest, _period_at,
    _neighbour_ok, measure_events, _chance, summarize, _hist, monotony, hard_hits, _speech, _level_at,
    speech_vs_music, story_sections, sections_vs_story, _spearman, sfx_vs_impacts
)
# the strips drawn
from letitedit.timing.music_sync_draw import (  # noqa: E402,F401
    COL, KIND_COL, KIND_LABEL, DEFAULT_KINDS, font, _out_dir, _fmt_off, draw_overview, draw_strips
)


import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import numpy as np

HERE = _paths.BRIDGE
CACHE = CACHE_ROOT / 'music-sync'


# ============================================================================ the beat finder (bridge/beat_finder.py)

def beat_this_status():
    """{'available': bool, 'why': [...]}: can the beat finder run here?"""
    import letitedit.sound.beat_finder as beat_finder
    reason = beat_finder.available()
    return {'available': not reason, 'why': [reason] if reason else []}


def beat_this(path, y=None, key=None, refresh=False):
    """The beat finder's frame-wise beat / downbeat probabilities of an audio file (cached by content), or None when it can't run here (beat_this_status says why)."""
    import letitedit.sound.beat_finder as beat_finder
    key = key or _file_key(path)
    f = CACHE / 'beat-finder' / f'{key}-{beat_finder.MODEL_NAME}.json'
    if not refresh:
        d = _read_json(f)
        if d and d.get('beat_act'):
            return d
    if beat_finder.available():
        return None
    d = beat_finder.frames(_decode(path, SR) if y is None else y, SR)
    _write_json(f, d)
    return d


def find_beats(path, y=None, force_bpb=None, refresh=False):
    """(beats, positions in the bar, extra) of an audio file; None when it has no steady beat. Raises RuntimeError with the plain reason when the beat finder can't run on it."""
    path = str(path)
    if y is None:
        y = _decode(path, SR)
    try:
        bt = beat_this(path, y=y, refresh=refresh)
    except Exception as e:  # noqa: BLE001 - said plainly, never guessed around
        raise RuntimeError(f'the beat finder failed on {Path(path).name}: {type(e).__name__}: {str(e)[:300]}') from e
    if bt is None:
        raise RuntimeError('; '.join(beat_this_status()['why']) or 'the beat finder is not available')
    return _grid_from_beat_this(y, bt, force_bpb)


# ============================================================================ the beat grid of one audio file

def _acf(x):
    x = np.asarray(x, np.float64) - float(np.mean(x))
    if not len(x):
        return np.zeros(1)
    ac = np.correlate(x, x, 'full')[len(x) - 1:]
    return ac / (ac[0] + 1e-12)


def _onset_env50(y, n):
    """The classic spectral-flux onset envelope (a measure of attacks; it finds no beats), resampled to Beat This!'s 50 frames/s."""
    import letitedit.footage.perception as perception
    bm = perception._beats_module()
    env = bm.onset_envelope(y, SR)
    fps0 = SR / bm.HOP
    t = np.arange(n) / BT_FPS
    return np.interp(t, (np.arange(len(env)) + 2048 / bm.HOP / 2) / fps0, env), env


def _level_choice(a, env50, bt_beats, prior_bpm=105.0, prior_oct=0.8):
    """Beat period (frames at 50/s) among Beat This!'s own level (its median beat interval) and its multiples and
    fractions, scored by the autocorrelation of its probability and of the onset envelope times a log-normal tempo
    preference; Beat This!'s own level gets a bonus (x1.25). Returns (period, candidates)."""
    acb, aco = _acf(a), _acf(env50)
    if len(bt_beats) >= 8:
        base = float(np.median(np.diff(bt_beats))) * BT_FPS
    else:
        hi = min(LAG_HI + 1, len(acb))
        base = float(LAG_LO + int(np.argmax(acb[LAG_LO:hi]))) if hi > LAG_LO else 25.0
    cands = []
    for mult in (1 / 3, 1 / 2, 1.0, 2.0, 3.0):
        L = base * mult
        if not (LAG_LO <= L <= LAG_HI):
            continue
        i = int(round(L))
        sb = float(acb[max(0, i - 1):i + 2].max()) if i + 1 < len(acb) else 0.0
        so = float(aco[max(0, i - 1):i + 2].max()) if i + 1 < len(aco) else 0.0
        bpm = 60 * BT_FPS / L
        pr = math.exp(-0.5 * (math.log2(bpm / prior_bpm) / prior_oct) ** 2)
        score = (0.5 * max(sb, 0) + 0.5 * max(so, 0)) * pr * (1.25 if mult == 1.0 else 1.0)
        cands.append({'bpm': round(bpm, 2), 'period_frames': round(L, 3), 'score': round(score, 4),
                      'acf_beat_prob': round(sb, 3), 'acf_onsets': round(so, 3), 'tempo_preference': round(pr, 3),
                      'beat_this_level': mult == 1.0})
    if not cands:
        return base, []
    cands.sort(key=lambda c: -c['score'])
    return cands[0]['period_frames'], cands


def _tempogram_path(a, L0, win_s=8.0, hop_s=1.0, lam=6.0, prior_oct=0.35):
    """Local beat period per frame: windowed autocorrelation of the probability, a Viterbi path over periods that
    stays near L0 (log-normal) and moves smoothly (cost lam x |log2 ratio| per window)."""
    n = len(a)
    W, H = int(win_s * BT_FPS), int(hop_s * BT_FPS)
    lags = np.arange(LAG_LO, LAG_HI + 1)
    starts = list(range(0, max(1, n - W + 1), H)) or [0]
    E = []
    for s in starts:
        seg = a[s:s + W]
        ac = _acf(seg) if len(seg) > LAG_HI + 2 else np.zeros(LAG_HI + 2)
        E.append(np.clip(ac[lags], 0, None))
    E = np.asarray(E)
    pri = np.exp(-0.5 * (np.log2(lags / max(L0, 1e-6)) / prior_oct) ** 2)
    logE = np.log(E * pri[None, :] + 1e-3)
    lg = np.log2(lags)
    T = -lam * np.abs(lg[:, None] - lg[None, :])
    V = logE[0].copy()
    B = np.zeros((len(starts), len(lags)), int)
    for t in range(1, len(starts)):
        cand = V[:, None] + T
        B[t] = np.argmax(cand, 0)
        V = cand[B[t], np.arange(len(lags))] + logE[t]
    path = [int(np.argmax(V))]
    for t in range(len(starts) - 1, 0, -1):
        path.append(int(B[t, path[-1]]))
    path = path[::-1]
    Ls = []
    for t, k in enumerate(path):
        L = float(lags[k])
        e = E[t]
        if 0 < k < len(lags) - 1:
            y0, y1, y2 = e[k - 1], e[k], e[k + 1]
            den = y0 - 2 * y1 + y2
            if abs(den) > 1e-9:
                L += float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5))
        Ls.append(L)
    cpos = np.asarray(starts) + W / 2
    return np.interp(np.arange(n), cpos, Ls)


def _dp_track(a, P, tightness=100.0):
    """Ellis-style dynamic programming beat tracking with a local period P[i] (frames)."""
    n = len(a)
    env = a / (a.std() + 1e-9)
    score = env.astype(np.float64).copy()
    back = np.full(n, -1)
    for i in range(n):
        p = P[i]
        lo, hi = max(1, int(round(p / 2))), int(round(2 * p))
        j = i - np.arange(lo, hi + 1)
        j = j[j >= 0]
        if not len(j):
            continue
        cand = score[j] - tightness * np.log((i - j) / p) ** 2
        m = int(np.argmax(cand))
        if cand[m] > 0:
            score[i] = env[i] + cand[m]
            back[i] = j[m]
    pe = int(math.ceil(P[-1])) if n else 1
    tail = np.arange(max(0, n - pe), n)
    if not len(tail):
        return np.zeros(0, int)
    i = int(tail[np.argmax(score[tail])])
    out = []
    while i >= 0:
        out.append(i)
        i = back[i]
    return np.asarray(out[::-1])


def _peak_time(a, k, w=2):
    lo, hi = max(0, k - w), min(len(a), k + w + 1)
    m = lo + int(np.argmax(a[lo:hi]))
    if 1 <= m < len(a) - 1:
        y0, y1, y2 = a[m - 1], a[m], a[m + 1]
        den = y0 - 2 * y1 + y2
        off = 0.5 * (y0 - y2) / den if abs(den) > 1e-12 else 0.0
        return (m + float(np.clip(off, -0.5, 0.5))) / BT_FPS
    return m / BT_FPS


def _bar_hmm(dact, bpb, change=0.02):
    """Viterbi over bar positions (0 = downbeat) for each beat from its downbeat probability; a bar may be cut short
    (probability `change`). Returns (positions, log-likelihood)."""
    n = len(dact)
    eps = 1e-4
    e0 = np.log(np.clip(dact, eps, 1 - eps))
    e1 = np.log(np.clip(1 - dact, eps, 1 - eps))
    V = np.where(np.arange(bpb) == 0, e0[0], e1[0]) - math.log(bpb)
    B = np.zeros((n, bpb), int)
    lstay, ljump = math.log(1 - change), math.log(change / max(1, bpb - 1))
    for i in range(1, n):
        nv = np.empty(bpb)
        c = V + np.where(np.arange(bpb) == bpb - 1, lstay, ljump)
        q = int(np.argmax(c))
        nv[0], B[i, 0] = c[q] + e0[i], q
        for p in range(1, bpb):
            nv[p], B[i, p] = V[p - 1] + lstay + e1[i], p - 1
        V = nv
    p = int(np.argmax(V))
    ll = float(V[p])
    pos = [p]
    for i in range(n - 1, 0, -1):
        p = int(B[i, p])
        pos.append(p)
    return np.asarray(pos[::-1]), ll


def _f_any(est, ref, tol=0.07):
    """Best beat F-measure of est against ref at the same, half or double level ((F, level))."""
    ref = np.asarray(ref, float)
    est = np.asarray(est, float)
    if len(ref) < 4 or len(est) < 4:
        return 0.0, None
    mids = (ref[1:] + ref[:-1]) / 2
    best = (0.0, None)
    for name, r in (('same', ref), ('half', ref[0::2]), ('half', ref[1::2]),
                    ('double', np.sort(np.concatenate([ref, mids])))):
        used = np.zeros(len(r), bool)
        hit = 0
        for e in est:
            d = np.abs(r - e)
            d[used] = 9
            k = int(np.argmin(d))
            if d[k] <= tol:
                used[k] = True
                hit += 1
        p, rc = hit / len(est), hit / len(r)
        f = 2 * p * rc / (p + rc) if p + rc else 0.0
        if f > best[0]:
            best = (f, name)
    return round(best[0], 3), best[1]


def _grid_from_beat_this(y, bt, force_bpb=None):
    """(beats, positions, extra) from Beat This! probabilities (see the module doc)."""
    import letitedit.sound.soundtrack as st
    a = np.asarray(bt['beat_act'], float)
    d = np.asarray(bt['down_act'], float)
    bb = np.asarray(bt.get('beats') or [], float)
    env50, _ = _onset_env50(y, len(a))
    L0, cands = _level_choice(a, env50, bb)
    P = _tempogram_path(a, L0)
    frames = _dp_track(a, P)
    if len(frames) < 4:
        return None
    times = np.maximum.accumulate(np.array([_peak_time(a, int(k)) for k in frames]))
    ref, moved = st._refine(y, SR, times.tolist())
    ref = np.asarray(ref, float)
    k_at = [int(round(t * BT_FPS)) for t in times]
    dk = np.array([d[max(0, k - 2):k + 3].max() for k in k_at])
    bk = np.array([a[max(0, k - 2):k + 3].max() for k in k_at])
    best = None
    for bpb in ([int(force_bpb)] if force_bpb else (3, 4)):
        pos, ll = _bar_hmm(dk, bpb)
        norm = ll / max(1, len(dk))
        if best is None or norm > best[2]:
            best = (bpb, pos, norm)
    bpb, pos, _ = best
    per = [float(dk[pos == p].mean()) if np.any(pos == p) else 0.0 for p in range(bpb)]
    contrast = per[0] - max(per[1:]) if bpb > 1 else 0.0
    local_bpm = 60 * BT_FPS / P
    extra = {'beat_act': bk, 'down_act': dk, 'bpb': bpb, 'moved': int(moved), 'level_choice': cands,
             'downbeat_by_position': [round(x, 3) for x in per], 'downbeat_contrast': round(contrast, 3),
             'bpm_range': [round(float(np.percentile(local_bpm, 5)), 1), round(float(np.percentile(local_bpm, 95)), 1)],
             'bpm': round(float(np.median(local_bpm)), 2)}
    return ref, pos, extra


def _bar_features(y, beats, pos, bpb, sections):
    """Bars, energy by bar, phrases (4-bar grid fitted to the bar-to-bar novelty, plus energy-section starts and
    strong novelty peaks) and drops (the next two bars 3 dB+ louder than the two before, into a loud stretch): the
    soundtrack tool's method, on this grid."""
    import letitedit.sound.soundtrack as st
    import letitedit.footage.perception as perception
    L = len(y) / SR
    mel, chroma = st._frame_features(y)
    bm = perception._beats_module()
    env = bm.onset_envelope(y, SR)
    fps = SR / st.HOP
    downs = [i for i, p in enumerate(pos) if p == 0]
    bars = []
    for k, i in enumerate(downs):
        end = beats[downs[k + 1]] if k + 1 < len(downs) else min(L, beats[i] + bpb * float(np.median(np.diff(beats))))
        if end - beats[i] > 0.2:
            bars.append([float(beats[i]), float(end)])
    out = {'bars': bars, 'energy_by_bar': [], 'loud_db_by_bar': [], 'phrases': [], 'drops': [], 'phrase_offset': 0}
    J = len(bars)
    if J < 2:
        return out
    loud, dens, timbre, chrom = [], [], [], []
    for a, b in bars:
        i0, i1 = int(a * SR), max(int(a * SR) + 1, int(b * SR))
        loud.append(10 * math.log10(float(np.mean(y[i0:i1] ** 2)) + 1e-10))
        f0 = min(int(round(a * fps)), len(mel) - 1)
        f1 = min(max(f0 + 1, int(round(b * fps))), len(mel))
        seg_env = env[f0:min(f1, len(env))]
        dens.append(float(seg_env.mean()) if len(seg_env) else 0.0)
        timbre.append(mel[f0:f1].mean(0))
        c = chroma[f0:f1].mean(0)
        chrom.append(c / (np.linalg.norm(c) + 1e-9))
    loud, dens = np.asarray(loud), np.asarray(dens)

    def scaled(x):
        lo, hi = np.percentile(x, 5), np.percentile(x, 95)
        return np.full_like(x, 0.5) if hi - lo < 1e-9 else np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    energy = 0.75 * scaled(loud) + 0.25 * scaled(dens)
    out['energy_by_bar'] = [round(float(e), 3) for e in energy]
    out['loud_db_by_bar'] = [round(float(v), 2) for v in loud]
    tz = np.asarray(timbre)
    tz = (tz - tz.mean(0)) / (tz.std(0) + 1e-6)
    F = np.hstack([tz / math.sqrt(tz.shape[1]), 0.8 * np.asarray(chrom)])
    F = F / (np.linalg.norm(F, axis=1, keepdims=True) + 1e-9)
    nov = st._novelty(F, 4)
    plen = 4
    offs = [float(np.mean(nov[1:J][((np.arange(1, J) - o) % plen) == 0])) if J > plen else 0.0 for o in range(plen)]
    off = int(np.argmax(offs))
    starts = np.asarray([b[0] for b in bars])
    phrases = {j for j in range(J) if (j - off) % plen == 0}
    for s in sections or []:
        j = int(np.argmin(np.abs(starts - float(s[0]))))
        if abs(starts[j] - float(s[0])) <= 2.0:
            phrases.add(j)
    if J > 8:
        thr = float(np.percentile(nov[1:J], 85))
        phrases |= {j for j in range(1, J) if nov[j] >= thr and nov[j] > 0.3}
    phrases.add(0)
    out['phrases'] = sorted(phrases)
    out['phrase_offset'] = off
    drops = []
    for j in range(2, J - 1):
        jump = float(np.mean(loud[j:j + 2]) - np.mean(loud[j - 2:j]))
        after = float(np.mean(energy[j:j + 4]))
        if jump >= 3.0 and after >= 0.7:
            drops.append({'bar': j, 't': round(bars[j][0], 4), 'jump_db': round(jump, 2)})
    drops.sort(key=lambda x: -x['jump_db'])
    kept = []
    for x in drops:
        if all(abs(x['bar'] - k['bar']) > 2 for k in kept):
            kept.append(x)
    out['drops'] = sorted(kept[:10], key=lambda x: x['bar'])
    return out


def _loudness_curve(y, every_s=0.1):
    """K-weighted loudness (LUFS-like, mono) of each `every_s` window."""
    import letitedit.sound.music as music
    from scipy.signal import lfilter
    (b1, a1), (b2, a2) = music._k_weighting(SR)
    k = lfilter(b2, a2, lfilter(b1, a1, np.asarray(y, np.float64)))
    hop = int(round(every_s * SR))
    n = len(k) // hop
    if n < 1:
        return []
    p = np.mean(k[:n * hop].reshape(n, hop) ** 2, axis=1)
    return [round(float(-0.691 + 10 * math.log10(v + 1e-12)), 2) for v in p]


def song_grid(path, settings=None, refresh=False):
    """The beat grid and structure of one audio file (any file ffmpeg reads; cached by content). See the module doc
    for the method; keys: path, key, duration, tracker, beats, pos (0 = downbeat), beats_per_bar, bars, bpm,
    bpm_range, beat_confidence, beat_quality, downbeat_contrast, beat_strength (0-1 onset strength at each beat),
    beat_act, phrases, drops, energy_by_bar, sections, loudness {every_s, lufs}, integrated_lufs,
    warnings."""
    st_ = dict(DEFAULTS)
    st_.update({k: v for k, v in (settings or {}).items() if v is not None})
    path = str(path)
    if not Path(path).is_file():
        raise FileNotFoundError(f'no audio file at {path}')
    key = _file_key(path)
    tag = _hash({'bpb': st_.get('beats_per_bar'), 'v': SONG_VERSION}, 8)
    f = CACHE / 'songs' / f'{key}-{tag}.json'
    if not refresh:
        d = _read_json(f)
        if d and d.get('v') == SONG_VERSION:
            d['path'] = path
            return d
    warnings = []
    y = _decode(path, SR)
    L = len(y) / SR
    res = {'v': SONG_VERSION, 'path': path, 'key': key, 'duration': round(L, 3)}
    if L < 4 or float(np.abs(y).max(initial=0)) < 1e-4:
        res.update(tracker=None, beats=[], pos=[], bars=[], beats_per_bar=None, bpm=None, beat_confidence=0.0,
                   beat_quality='none', sections=[], phrases=[], drops=[], energy_by_bar=[], beat_strength=[],
                   loudness={'every_s': 0.1, 'lufs': _loudness_curve(y) if len(y) else []}, integrated_lufs=None,
                   warnings=[f'too short or silent to find a beat ({L:.1f} s)'])
        _write_json(f, res)
        return res
    sections = []
    try:
        import letitedit.footage.perception as perception
        sections = perception.music(path).get('sections') or []
    except Exception:  # noqa: BLE001 - sections are a measure of energy, and the beats don't need them
        sections = []
    failed, grid = None, None
    try:
        grid = find_beats(path, y=y, force_bpb=st_.get('beats_per_bar'), refresh=refresh)
    except RuntimeError as e:
        failed = str(e)
    if grid is not None:
        beats, pos, ex = grid
        bpb = ex['bpb']
        conf = float(np.mean(ex['beat_act'])) if len(ex['beat_act']) else 0.0
        q = 'clear' if conf >= th('sync.beat_clear_min') else 'weak' if conf >= th('sync.beat_weak_min') else 'none'
        res.update(tracker='beat_this+dp', tracker_note=(
            'Beat This! (ISMIR 2024, checkpoint final0, CPU) beat/downbeat probabilities; beats by dynamic '
            'programming with a local tempo, refined to transients; bars by a bar-position HMM'),
            bpm=ex['bpm'], bpm_range=ex['bpm_range'], beats_per_bar=bpb, beat_confidence=round(conf, 3),
            beat_quality=q, downbeat_contrast=ex['downbeat_contrast'],
            downbeat_by_position=ex['downbeat_by_position'], beat_act=[round(float(v), 3) for v in ex['beat_act']],
            level_choice=ex['level_choice'][:3], refined_beats=ex['moved'])
        if ex['downbeat_contrast'] < 0.3:
            warnings.append(f'the downbeat is uncertain (downbeat probability by bar position '
                            f'{ex["downbeat_by_position"]}): bar lines may sit on another beat of the bar')
        lc = ex['level_choice']
        if len(lc) >= 2 and lc[1]['score'] >= 0.85 * lc[0]['score']:
            warnings.append(f'the tempo level is ambiguous: {lc[0]["bpm"]} bpm chosen, {lc[1]["bpm"]} bpm nearly as '
                            'likely (beat offsets are measured on the chosen level)')
    else:
        beats, pos, bpb = np.zeros(0), np.zeros(0, int), None
        res.update(tracker=None if failed else 'beat_this+dp', bpm=None, beats_per_bar=None, beat_confidence=0.0, beat_quality='none', beat_act=None)
        if failed:
            res['beat_finder_error'] = failed
            warnings.append(f"The beat finder couldn't run, so there are no beats for this song: {failed}")
        else:
            warnings.append('no steady beat found: there is no beat grid to measure against')
    res['beats'] = [round(float(b), 4) for b in beats]
    res['pos'] = [int(p) for p in pos]
    # onset strength at each beat (0-1, on the song's own 95th percentile)
    _, env = _onset_env50(y, 1)
    import letitedit.footage.perception as perception
    hop = perception._beats_module().HOP
    if len(beats):
        ef = np.asarray(env, float)
        p95 = float(np.percentile(ef, 95)) or 1.0
        strength = []
        for t in beats:
            k = int(round(t * SR / hop))
            strength.append(round(min(1.5, float(ef[max(0, k - 2):k + 3].max(initial=0.0)) / p95), 3))
        res['beat_strength'] = strength
    else:
        res['beat_strength'] = []
    feats = _bar_features(y, np.asarray(beats, float), np.asarray(pos, int), bpb or 4, sections) \
        if len(beats) >= 8 else {'bars': [], 'energy_by_bar': [], 'loud_db_by_bar': [], 'phrases': [], 'drops': [],
                                 'phrase_offset': 0}
    res.update(feats)
    res['sections'] = [[_r(a, 2), _r(b, 2), n, _r(rel, 1)] for a, b, n, rel in sections]
    res['loudness'] = {'every_s': 0.1, 'lufs': _loudness_curve(y, 0.1), 'unit': 'LUFS-like (K-weighted, mono)'}
    try:
        import letitedit.sound.music as music
        res['integrated_lufs'] = round(float(music.loudness(path)), 2)
    except Exception:  # noqa: BLE001
        res['integrated_lufs'] = None
    res['warnings'] = warnings
    if failed:      # not kept: it may run next time
        return res
    _write_json(f, res)
    return res


# ============================================================================ music in a project

def _effects_gain(effects, t_rel, length):
    """dB added by an item's effects at t_rel seconds into it (gain static/keyframes, audio fades); -inf when muted."""
    total = 0.0
    for e in effects or []:
        if e == 'mute':
            return -math.inf
        if not isinstance(e, dict):
            continue
        if 'mute' in e:
            return -math.inf
        g = e.get('gain')
        if isinstance(g, (int, float)) and not isinstance(g, bool):
            total += float(g)
        elif isinstance(g, dict) and g.get('keys'):
            keys = [(float(k[0]), float(k[1])) for k in g['keys'] if isinstance(k, (list, tuple)) and len(k) >= 2]
            if keys:
                ts, vs = zip(*sorted(keys))
                total += float(np.interp(t_rel, ts, vs))
        for name, start in (('fade_in_audio', True), ('fade_out_audio', False)):
            if name in e:
                v = e[name]
                try:
                    n = float(v.get('len', 0) if isinstance(v, dict) else v)
                except (TypeError, ValueError):
                    n = 0.0
                if n > 0:
                    x = t_rel / n if start else (length - t_rel) / n
                    if x < 1:
                        total += 20 * math.log10(max(x, 1e-4))
    return total


def _track_gain(track, t):
    g = track.get('gain', 0)
    if isinstance(g, (int, float)) and not isinstance(g, bool):
        return float(g)
    if isinstance(g, dict) and g.get('keys'):
        keys = [(float(k[0]), float(k[1])) for k in g['keys'] if isinstance(k, (list, tuple)) and len(k) >= 2]
        if keys:
            ts, vs = zip(*sorted(keys))
            return float(np.interp(t, ts, vs))
    return 0.0


def music_items(script, settings=None):
    """[(track, item, start_s, end_s, why)] of the music clips of an edit script."""
    import letitedit.timeline.edit_sync as edit_sync
    st_ = dict(DEFAULTS)
    st_.update(settings or {})
    out = []
    for t in script.get('tracks') or []:
        if t.get('kind') != 'audio' and not MUSIC_NAME.search(t.get('name', '')):
            continue
        named = bool(MUSIC_NAME.search(t.get('name', '')))
        if not named and (SFX_NAME.search(t.get('name', '')) or VOICE_NAME.search(t.get('name', ''))):
            continue
        for it, s, e in edit_sync.layout(t):
            clip = it.get('clip')
            if not clip:
                continue
            if named:
                out.append((t, it, s, e, f'on the music track {t["name"]!r}'))
            elif Path(clip).suffix.lower() in AUDIO_EXT and (e - s) >= float(st_['music_audio_min_s']):
                out.append((t, it, s, e, f'an audio-only file of {e - s:.1f} s on track {t["name"]!r} (taken as '
                                         'music; name the track Music to make it explicit)'))
    return out


def _muted_or_guide(t, it, warnings):
    """Whether a music clip is heard: muted (hidden track, mute effect), or the guide song added when posting
    (its beats count, its level doesn't)."""
    muted = t.get('hide') in ('audio', 'both') or 'mute' in (it.get('effects') or []) or \
        any(isinstance(x, dict) and 'mute' in x for x in it.get('effects') or [])
    import letitedit.sound.guide_song as guide_song
    guide = guide_song.is_guide_name(t.get('name'))    # T72: added when posting, so its beats count and its level doesn't
    if guide:
        muted = True
        note = (f'{t["name"]!r} is a song the person adds when posting: picture is measured against its beats; it is '
                'not in the export, so its level is not measured')
        if note not in warnings:
            warnings.append(note)
    return muted, guide


def _crossfades(it, k, lst, s, e):
    """Seconds of crossfade into this clip (its transition over the clip before) and out of it (the next
    clip's)."""
    xin = 0.0
    if it.get('transition') and k > 0 and lst[k - 1][3] > s:
        try:
            import letitedit.timeline.edit_script as es
            xin = float(es.transition_spec(it['transition'])['len'])
        except Exception:  # noqa: BLE001
            xin = 0.0
    xout = 0.0
    if k + 1 < len(lst):
        nt, nit, ns, ne, _ = lst[k + 1]
        if nit.get('transition') and ns < e:
            xout = e - ns
    return xin, xout


def _drop_overlapping_beats(beats, warnings):
    """Beats of two music clips overlapping without a crossfade: within 60 ms, the louder clip keeps its
    beat."""
    # two music clips overlapping on different tracks without a crossfade: keep the louder one's beats there
    kept = []
    for b in beats:
        if kept and abs(b['t'] - kept[-1]['t']) < 0.06 and b['piece'] != kept[-1]['piece']:
            if (b.get('level_db') or -999) > (kept[-1].get('level_db') or -999):
                kept[-1] = b
            continue
        kept.append(b)
    if len(kept) < len(beats):
        warnings.append(f'{len(beats) - len(kept)} beats of overlapping music clips were dropped (the louder clip '
                        'keeps its beats)')
    beats = kept
    return beats


def project_music(script, fps, frames, settings=None, refresh=False):
    """The music lane data of a project from its music clips' own files mapped through the timeline."""
    st_ = dict(DEFAULTS)
    st_.update(settings or {})
    warnings, unsupported = [], []
    found = music_items(script, st_)
    dur = frames / float(fps)
    every = float(st_['level_every_s'])
    nlev = int(math.ceil(dur / every)) + 1
    lev_pow = np.zeros(nlev)
    inten_num = np.zeros(nlev)
    inten_den = np.zeros(nlev)
    pieces, beats, sections, songs = [], [], [], {}
    if not found:
        return {'beats': [], 'pieces': [], 'songs': {}, 'sections': [], 'level_db': [], 'intensity': [],
                'warnings': ['no music on the timeline (no track named music/song/score/bed and no long audio-only '
                             'clip)'], 'unsupported': [], 'stem': 'none: no music clips'}
    # each track's items in order: crossfades (an incoming item's transition overlaps the item before it)
    by_track = {}
    for t, it, s, e, why in found:
        by_track.setdefault(id(t), []).append((t, it, s, e, why))
    for _, lst in by_track.items():
        lst.sort(key=lambda x: x[2])
        for k, (t, it, s, e, why) in enumerate(lst):
            clip = it['clip']
            speed = float(it.get('speed') or 1.0)
            if it.get('reverse'):
                unsupported.append(f'{it.get("id")}: reversed music is not mapped')
                continue
            if t.get('duck'):
                if 'track auto-duck is not modelled' not in ' '.join(unsupported):
                    unsupported.append(f'track auto-duck is not modelled (track {t["name"]}): the level as heard '
                                       'ignores it')
            muted, guide = _muted_or_guide(t, it, warnings)
            xin, xout = _crossfades(it, k, lst, s, e)
            own0, own1 = s + xin / 2, e - xout / 2
            try:
                g = song_grid(clip, st_, refresh=refresh)
            except FileNotFoundError:
                warnings.append(f'{it.get("id")}: music file missing: {clip}')
                continue
            except Exception as ex:  # noqa: BLE001 - one bad file must not lose the others
                warnings.append(f'{it.get("id")}: could not analyse {Path(clip).name}: {type(ex).__name__}: {ex}')
                continue
            songs[clip] = {k2: g.get(k2) for k2 in ('tracker', 'bpm', 'bpm_range', 'beats_per_bar', 'beat_confidence',
                                                     'beat_quality', 'downbeat_contrast', 'duration',
                                                     'integrated_lufs', 'warnings')}
            a_in = float(it.get('in') or 0.0)
            length = e - s

            def to_tl(ts, s=s, a_in=a_in, speed=speed):
                return s + (ts - a_in) / speed
            # beats owned by this piece
            bars_starts = [b[0] for b in g.get('bars') or []]
            phrase_t = {round(bars_starts[j], 4) for j in g.get('phrases') or [] if j < len(bars_starts)}
            drop_t = {round(d['t'], 4) for d in g.get('drops') or []}
            bar_idx = (np.searchsorted(np.asarray(bars_starts), np.asarray(g['beats']) + 1e-4, side='right') - 1) \
                if bars_starts else np.full(len(g['beats']), -1)
            n_own = 0
            for i, (tb, p) in enumerate(zip(g['beats'], g['pos'])):
                tt = to_tl(tb)
                if not (own0 - 1e-6 <= tt < own1 - 1e-6) or tt < 0 or tt >= dur:
                    continue
                gain = _effects_gain(it.get('effects'), tt - s, length) + _track_gain(t, tt)
                li = int(tb / 0.1)
                lv = g['loudness']['lufs'][li] if li < len(g['loudness']['lufs']) else None
                heard = None if (lv is None or muted or gain == -math.inf) else lv + gain
                beats.append({'t': round(tt, 4), 'f': int(round(tt * fps)), 'downbeat': p == 0, 'pos': int(p) + 1,
                              'bar': int(bar_idx[i]) if len(bar_idx) and bar_idx[i] >= 0 else None,
                              'phrase': bool(p == 0 and round(tb, 4) in phrase_t),
                              'drop': bool(p == 0 and round(tb, 4) in drop_t),
                              'strength': (g.get('beat_strength') or [None] * len(g['beats']))[i],
                              'prob': (g.get('beat_act') or [None] * len(g['beats']))[i],
                              'level_db': _r(heard, 1), 'audible': guide or (heard is not None and heard >= st_['audible_db']),
                              'piece': it.get('id'), 'song_t': round(tb, 4)})
                n_own += 1
            # level as heard and intensity (every `every` s)
            lufs = g['loudness']['lufs']
            for j in range(max(0, int(s / every)), min(nlev, int(math.ceil(e / every)) + 1)):
                tt = j * every
                if tt < s or tt >= e or muted:
                    continue
                ts = a_in + (tt - s) * speed
                li = int(ts / 0.1)
                if li >= len(lufs):
                    continue
                gain = _effects_gain(it.get('effects'), tt - s, length) + _track_gain(t, tt)
                if gain == -math.inf:
                    continue
                lev_pow[j] += 10 ** ((lufs[li] + gain) / 10)
                eb = g.get('energy_by_bar') or []
                if eb and bars_starts:
                    bj = int(np.searchsorted(bars_starts, ts + 1e-4)) - 1
                    if 0 <= bj < len(eb):
                        w = 10 ** ((gain) / 10)
                        inten_num[j] += eb[bj] * w
                        inten_den[j] += w
            for a0, b0, name, rel in g.get('sections') or []:
                ta, tb2 = max(own0, to_tl(a0)), min(own1, to_tl(b0))
                if tb2 - ta >= 0.5:
                    sections.append({'t0': round(ta, 3), 't1': round(tb2, 3), 'f0': int(round(ta * fps)),
                                     'f1': int(round(tb2 * fps)), 'label': name, 'energy': rel,
                                     'energy_unit': 'dB vs the song\'s loudest section', 'piece': it.get('id')})
            pieces.append({'id': it.get('id'), 'track': t['name'], 'clip': clip, 'why': why, 't0': round(s, 4),
                           't1': round(e, 4), 'f0': int(round(s * fps)), 'f1': int(round(e * fps)),
                           'in_s': a_in, 'out_s': it.get('out'), 'speed': speed, 'muted': muted and not guide,
                           **({'guide_song': True} if guide else {}),
                           'crossfade_in_s': round(xin, 3), 'crossfade_out_s': round(xout, 3),
                           'owns': [round(own0, 4), round(own1, 4)], 'beats': n_own,
                           'tracker': g.get('tracker'), 'beat_quality': g.get('beat_quality'),
                           'beat_confidence': g.get('beat_confidence'), 'bpm': _r((g.get('bpm') or 0) * speed, 2)
                           if g.get('bpm') else None})
            for w in g.get('warnings') or []:
                msg = f'{Path(clip).name}: {w}'
                if msg not in warnings:
                    warnings.append(msg)
    beats.sort(key=lambda b: b['t'])
    beats = _drop_overlapping_beats(beats, warnings)
    level = [None if p <= 0 else round(10 * math.log10(p), 1) for p in lev_pow]
    inten = [None if d <= 0 else round(float(n / d), 3) for n, d in zip(inten_num, inten_den)]
    return {'beats': beats, 'pieces': pieces, 'songs': songs, 'sections': sorted(sections, key=lambda x: x['t0']),
            'level_db': level, 'intensity': inten, 'warnings': warnings, 'unsupported': unsupported,
            'stem': 'the music clips\' own files mapped through the timeline (in/out, speed, crossfades, clip and '
                    'track gain, audio fades)'}


# ============================================================================ music in a video

def _speech_share(video, dur):
    """(share of the duration with speech, how) from cached words, else the voice detector."""
    try:
        import letitedit.footage.speech as speech_words
        ws = speech_words.cached_words(video)
    except Exception:  # noqa: BLE001
        ws = None
    if ws:
        tot = sum(max(0.0, min(float(w['e']), float(w['s']) + 1.5) - float(w['s'])) for w in ws)
        return min(1.0, tot / max(dur, 1e-6)), 'cached words'
    try:
        import letitedit.sound.music as music
        prof = music.voice_profile(video)
        tot = sum(max(0.0, b - a) for a, b in prof.get('voice') or [])
        return min(1.0, tot / max(dur, 1e-6)), 'voice detector'
    except Exception as e:  # noqa: BLE001
        return None, f'speech unknown ({type(e).__name__})'


def video_music(video, fps, frames, settings=None, refresh=False):
    """The music lane data of a video file: its own sound or its music stem (see the module doc)."""
    st_ = dict(DEFAULTS)
    st_.update(settings or {})
    warnings, unsupported = [], []
    dur = frames / float(fps)
    mode = str(st_.get('stem') or 'auto')
    share, how = (None, None)
    if mode == 'auto':
        share, how = _speech_share(video, dur)
        mode = 'separate' if (share or 0) >= 0.1 else 'mix'
    path, stem = video, 'the video\'s own sound (no separation)'
    if mode == 'separate':
        try:
            import letitedit.sound.model_tools as model_tools
            sep = model_tools.separate(video, parts=['music'])
            path = sep['files']['music']
            stem = ('music stem: Demucs htdemucs drums + bass + other (model_tools.separate), because someone talks '
                    f'in the video (speech {round((share or 0) * 100)}% of it, from {how})' if share is not None else
                    'music stem: Demucs htdemucs drums + bass + other (model_tools.separate)')
        except Exception as e:  # noqa: BLE001 - analyse the mix instead
            warnings.append(f'music separation failed ({type(e).__name__}: {str(e)[:200]}); the mix was analysed, '
                            'speech may disturb the beat grid')
            path, stem = video, 'the video\'s own sound (separation failed)'
    elif share is not None:
        stem = f'the video\'s own sound (speech {round(share * 100)}% of it, from {how}: no separation needed)'
    g = song_grid(path, st_, refresh=refresh)
    beats = []
    bars_starts = [b[0] for b in g.get('bars') or []]
    phrase_t = {round(bars_starts[j], 4) for j in g.get('phrases') or [] if j < len(bars_starts)}
    drop_t = {round(d['t'], 4) for d in g.get('drops') or []}
    lufs = g['loudness']['lufs']
    for i, (tb, p) in enumerate(zip(g['beats'], g['pos'])):
        if tb >= dur:
            continue
        li = int(tb / 0.1)
        lv = lufs[li] if li < len(lufs) else None
        bar = int(np.searchsorted(np.asarray(bars_starts), tb + 1e-4, side='right') - 1) if bars_starts else None
        bar = bar if bar is not None and bar >= 0 else None
        beats.append({'t': round(tb, 4), 'f': int(round(tb * fps)), 'downbeat': p == 0, 'pos': int(p) + 1,
                      'bar': bar, 'phrase': bool(p == 0 and round(tb, 4) in phrase_t),
                      'drop': bool(p == 0 and round(tb, 4) in drop_t),
                      'strength': (g.get('beat_strength') or [None] * len(g['beats']))[i],
                      'prob': (g.get('beat_act') or [None] * len(g['beats']))[i], 'level_db': lv,
                      'audible': lv is not None and lv >= st_['audible_db'], 'piece': 'file', 'song_t': round(tb, 4)})
    every = float(st_['level_every_s'])
    nlev = int(math.ceil(dur / every)) + 1
    level = []
    for j in range(nlev):
        li = int(j * every / 0.1)
        level.append(lufs[li] if li < len(lufs) else None)
    inten = [None] * nlev
    eb = g.get('energy_by_bar') or []
    if eb and bars_starts:
        for j in range(nlev):
            bj = int(np.searchsorted(bars_starts, j * every + 1e-4)) - 1
            if 0 <= bj < len(eb):
                inten[j] = eb[bj]
    sections = [{'t0': a, 't1': min(b, dur), 'f0': int(round(a * fps)), 'f1': int(round(min(b, dur) * fps)),
                 'label': n, 'energy': rel, 'energy_unit': 'dB vs the loudest section', 'piece': 'file'}
                for a, b, n, rel in g.get('sections') or [] if a < dur]
    spans_hint = None
    if mode == 'mix':
        unsupported.append('the music was not separated from other sound: level and sections include speech and '
                           'effects; a quiet music bed under talk may not be found')
        # where the music is: around beats the beat finder is fairly sure of (probability >= 0.3)
        tb = [(b['t'], b.get('prob')) for b in beats]
        per = float(np.median(np.diff([x for x, _ in tb]))) if len(tb) > 2 else 0.5
        spans_hint = []
        for t, p in tb:
            if p is not None and p < 0.3:
                continue
            a, b2 = t - 0.6 * per, t + 0.6 * per
            if spans_hint and a <= spans_hint[-1][1] + 1.5 * per:
                spans_hint[-1][1] = b2
            else:
                spans_hint.append([a, b2])
        spans_hint = [[max(0.0, a), min(dur, b2)] for a, b2 in spans_hint if b2 - a >= 2 * per]
    songs = {path: {k2: g.get(k2) for k2 in ('tracker', 'bpm', 'bpm_range', 'beats_per_bar', 'beat_confidence',
                                             'beat_quality', 'downbeat_contrast', 'duration',
                                             'integrated_lufs', 'warnings')}}
    warnings += [w for w in g.get('warnings') or []]
    return {'beats': beats, 'pieces': [{'id': 'file', 'track': None, 'clip': path, 't0': 0.0, 't1': round(dur, 4),
                                        'f0': 0, 'f1': int(frames), 'tracker': g.get('tracker'),
                                        'beat_quality': g.get('beat_quality'),
                                        'beat_confidence': g.get('beat_confidence'), 'bpm': g.get('bpm')}],
            'songs': songs, 'sections': sections, 'level_db': level, 'intensity': inten, 'warnings': warnings,
            'unsupported': unsupported, 'stem': stem, 'music_spans_hint': spans_hint}


# ============================================================================ the lane

def _spans_from_level(level, every, floor_db, join_s=0.6, min_s=0.5):
    """Where the music is audible: level >= floor_db, gaps up to join_s joined."""
    out = []
    for j, v in enumerate(level or []):
        if v is None or v < floor_db:
            continue
        a, b = j * every, (j + 1) * every
        if out and a <= out[-1][1] + join_s:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [s for s in out if s[1] - s[0] >= min_s]

def _finish_lane(data, fps, frames, st_):
    beats = data['beats']
    dur = frames / float(fps)
    every_e = float(st_['energy_every_s'])
    every_l = float(st_['level_every_s'])
    lev = data.get('level_db') or []
    inten = data.get('intensity') or []
    ne = int(math.ceil(dur / every_e))
    k = max(1, int(round(every_e / every_l)))
    energy, intensity = [], []
    for j in range(ne):
        seg = [v for v in lev[j * k:(j + 1) * k] if v is not None]
        energy.append(round(10 * math.log10(np.mean([10 ** (v / 10) for v in seg])), 1) if seg else None)
        segi = [v for v in inten[j * k:(j + 1) * k] if v is not None]
        intensity.append(round(float(np.mean(segi)), 3) if segi else None)
    ibi = np.diff([b['t'] for b in beats]) if len(beats) > 2 else np.zeros(0)
    ibi = ibi[(ibi > 0.15) & (ibi < 2.5)]
    tempo = round(60.0 / float(np.median(ibi)), 2) if len(ibi) else None
    confs = [p.get('beat_confidence') for p in data.get('pieces') or [] if p.get('beat_confidence') is not None]
    quals = [p.get('beat_quality') for p in data.get('pieces') or [] if p.get('beat_quality')]
    trackers = sorted({p.get('tracker') for p in data.get('pieces') or [] if p.get('tracker')})
    bars = []
    downs = [b for b in beats if b['downbeat']]
    for a, b in zip(downs, downs[1:] + [None]):
        bars.append({'t0': a['t'], 't1': b['t'] if b else None, 'f0': a['f'], 'bar': a.get('bar'),
                     'phrase': a.get('phrase'), 'drop': a.get('drop'), 'piece': a.get('piece')})
    spans = []
    for p in data.get('pieces') or []:
        if not p.get('muted'):
            spans.append([p['t0'], p['t1']])
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 0.05:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    # audible: the level as heard over the floor (a drop-out or a deep fade is not music the viewer hears)
    aud = _spans_from_level(lev, every_l, float(st_['audible_db']))
    if data.get('music_spans_hint') is not None:
        aud = [[max(a, c), min(b, d)] for a, b in aud for c, d in data['music_spans_hint'] if min(b, d) > max(a, c)]
    merged = [[max(a, c), min(b, d)] for a, b in merged for c, d in aud if min(b, d) - max(a, c) >= 0.3]
    # T72: a song added when posting has no level here, and the picture is measured against it all the same
    merged = sorted(merged + [[p['t0'], p['t1']] for p in data.get('pieces') or [] if p.get('guide_song')])
    return {
        'method': ('beat grid per song (Beat This! probabilities + dynamic programming + transient refinement + '
                   'bar HMM), ' + data['stem']),
        'beats': beats, 'bars': bars, 'tempo_bpm': tempo,
        'beat_confidence': round(float(np.mean(confs)), 3) if confs else None,
        'beat_quality': (min(quals, key=['none', 'weak', 'clear'].index) if quals and all(
            q in ('none', 'weak', 'clear') for q in quals) else (quals[0] if quals else 'none')),
        'tracker': ', '.join(trackers) if trackers else None, 'sections': data.get('sections') or [],
        'energy': energy, 'energy_every_s': every_e,
        'energy_unit': 'dB (K-weighted loudness of the music as heard, power mean over each step)',
        'intensity': intensity, 'intensity_unit': '0-1 song energy by bar (loudness 75% + onset density 25%), '
                                                  'scaled within each song',
        'level_db': lev, 'level_every_s': every_l, 'stem': data['stem'], 'pieces': data.get('pieces') or [],
        'songs': data.get('songs') or {}, 'music_spans': [[round(a, 3), round(b, 3)] for a, b in merged],
        'music_spans_about': 'where a music clip plays and its level as heard is at least audible_db (videos '
                             'analysed as a mix: also around beats the beat finder is fairly sure of)',
        'phrases': [{'t': b['t'], 'f': b['f'], 'piece': b.get('piece')} for b in beats if b.get('phrase')],
        'drops': [{'t': b['t'], 'f': b['f'], 'piece': b.get('piece')} for b in beats if b.get('drop')],
        'warnings': data.get('warnings') or [], 'unsupported': data.get('unsupported') or [],
        'conventions': 'beat t in seconds on the source timeline, f = round(t * fps); pos 1 = the downbeat; '
                       'bar = the song\'s bar number (0-based); level_db every level_every_s from t = 0',
        'settings': _clean(st_)}


def lane(ctx):
    """The music: beats, downbeats, bars, phrases, drops, tempo, song sections and energy of the music in the edit."""
    st_ = dict(DEFAULTS)
    st_.update({k: v for k, v in (ctx.get('settings') or {}).items() if k in DEFAULTS and v is not None})
    fps, frames = float(ctx['fps']), int(ctx['frames'])
    if ctx.get('kind') == 'project':
        script = ctx.get('script')
        if script is None:
            import letitedit.timeline.edit_script as es
            script = es.read(ctx['project'])
        data = project_music(script, fps, frames, st_)
    else:
        data = video_music(ctx['video'], fps, frames, st_)
    return _finish_lane(data, fps, frames, st_)


lane.defaults = dict(DEFAULTS)


def music(source, settings=None, refresh=False):
    """The music lane of a project (.mlt) or a video without the store (no preview render needed)."""
    st_ = dict(DEFAULTS)
    st_.update({k: v for k, v in (settings or {}).items() if v is not None})
    src = str(source)
    if src.lower().endswith('.mlt') or Path(src).is_dir():
        import letitedit.timeline.edit_script as es
        import letitedit.timeline.timeline_model as tm
        path = es._resolve(src)
        script = es.read(path)
        tl = tm.load(path)
        data = project_music(script, float(tl.fps), int(tl.frames), st_, refresh=refresh)
        out = _finish_lane(data, float(tl.fps), int(tl.frames), st_)
        out.update(fps=float(tl.fps), frames=int(tl.frames), kind='project')
        return _clean(out)
    import letitedit.footage.shots as shots
    info = shots.probe(src)
    fps = float(info['fps'])
    frames = int(info.get('frames') or round(float(info['duration']) * fps))
    data = video_music(src, fps, frames, st_, refresh=refresh)
    out = _finish_lane(data, fps, frames, st_)
    out.update(fps=fps, frames=frames, kind='video')
    return _clean(out)


# ============================================================================ the view

VIEW_SUMMARY = ('picture events (cuts, motion peaks, visual beats, text pops, SFX onsets) against the music\'s beat '
                'grid in frames: on-beat shares against chance, phase locking, monotony runs, hard hits; music swells '
                'in speech gaps; song sections against story sections; SFX against their impacts')
VIEW_OPTIONS = {'kinds': 'event kinds to measure (default: cuts, motion_peaks, visual_beats, text_pops, sfx; '
                         'caption_pops on request: captions follow the speech)',
                'thresholds': '{sync.key or key: value} overrides for this call',
                'settings': '{lane: {...}} measuring settings (music: stem, beats_per_bar)',
                'refresh': 'recompute the measurements', 'story_plan': 'path of a story_plan.json to use',
                'deliverable': 'which deliverable\'s plan sections (long / short) when the plan has several',
                'strip_s': 'seconds per strip row (default 12)', 'pages': 'strip pages to draw (default 4)',
                'speech_lane': 'videos: ask the store for the speech lane (prosody) for the words (default false: it '
                               'transcribes the video, about 6 min for a 30 s render the first time; without it the '
                               'cached transcript or the voice detector is used)'}


def _signals(source, start_s, end_s, options):
    """signals() from the store with the lanes this view reads; the music lane alone without the store."""
    opts = options or {}
    want = ['edit', LANE]
    try:
        import letitedit.timing.timing_signals as timing_signals
        reg = timing_signals.lanes()
        for name in ('motion', 'visual_beats', 'motion_events', 'audio'):
            if name in reg:
                want.append(name)
        is_proj = timing_signals._is_project(source)
        if not is_proj and 'speech' in reg and opts.get('speech_lane', False):
            want.append('speech')         # opt-in: the prosody lane transcribes the video (minutes the first time)
        sig = timing_signals.signals(source, start_s, end_s, lanes=want, refresh=bool(opts.get('refresh')),
                                     settings=opts.get('settings'))
        return sig, None
    except ImportError:
        pass
    # without the store: the music lane and a plain edit lane (cuts from the edit script / shots.detect)
    src = str(source)
    ml = music(src, settings=(opts.get('settings') or {}).get(LANE), refresh=bool(opts.get('refresh')))
    fps, frames = ml['fps'], ml['frames']
    if ml['kind'] == 'project':
        import letitedit.timeline.edit_script as es
        import letitedit.timeline.edit_sync as edit_sync
        script = es.read(src)
        main = edit_sync.main_track(script)
        cuts = []
        for it, s, e in edit_sync.layout(main)[1:]:
            cuts.append({'f': int(round(s * fps)), 'kind': 'dissolve' if it.get('transition') else 'cut',
                         'to_item': it.get('id')})
        ed = {'cuts': cuts, 'text_pops': [], 'items': [], 'source_of_cuts': 'edit script main track (no store)'}
        sig = {'kind': 'project', 'project': src, 'source': src, 'fps': fps, 'frames': frames, 'render': None,
               'lanes': {'edit': ed, LANE: ml}, 'warnings': ['timing_signals not importable: no motion, no text '
                                                             'pops; cuts from the main track only']}
    else:
        import letitedit.footage.shots as shots
        det = shots.detect(src)
        cuts = [{'f': int(c['frame']), 'kind': c['kind']} for c in det['cuts']]
        sig = {'kind': 'video', 'project': None, 'source': src, 'fps': fps, 'frames': frames, 'render': None,
               'lanes': {'edit': {'cuts': cuts, 'source_of_cuts': 'shots.detect'}, LANE: ml},
               'warnings': ['timing_signals not importable']}
    return sig, 'standalone'


def _filter(events, fps, start_s, end_s, items, cuts_sel):
    out = []
    for e in events:
        t = e['f'] / fps
        if start_s is not None and t < float(start_s):
            continue
        if end_s is not None and t >= float(end_s):
            continue
        out.append(e)
    return out


def sync(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief'):
    """The 'sync' view (see the module doc). Returns the result dict with 'images' (paths)."""
    t_all = time.time()
    opts = dict(options or {})
    given = opts.get('thresholds') or {}
    sig, mode = _signals(source, start_s, end_s, opts)
    if opts.get('cuts_at'):
        import letitedit.timing.timing_signals as timing_signals
        sig = timing_signals.add_cuts(sig, opts['cuts_at'])
    fps, frames = float(sig['fps']), int(sig['frames'])
    warnings = list(sig.get('warnings') or [])
    unsupported = []
    ml = (sig.get('lanes') or {}).get(LANE) or {}
    if ml.get('error'):
        raise ValueError(f'the music lane failed: {ml["error"]}')
    events, notes, unsup, motion_energy = picture_events(sig, opts, ml)
    unsupported += unsup
    kinds = [k for k in (opts.get('kinds') or list(DEFAULT_KINDS)) if k in events]
    # selection: range, items (their spans; cuts into or out of them), cuts
    sel_items = set(items or [])
    item_spans = [(it['f0'], it['f1']) for it in ((sig.get('lanes') or {}).get('edit') or {}).get('items') or []
                  if it.get('id') in sel_items]
    if sel_items and not item_spans:
        warnings.append(f'items {sorted(sel_items)} not found in the edit lane: no item filter applied')
        sel_items = set()
    for k in kinds:
        evs = _filter(events[k], fps, start_s, end_s, items, cuts)
        if sel_items:
            evs = [e for e in evs if e.get('from_item') in sel_items or e.get('to_item') in sel_items
                   or any(a <= e['f'] < b for a, b in item_spans)]
        if cuts and k == 'cuts':
            want_f = set()
            for c in cuts:
                if isinstance(c, bool):
                    continue
                if isinstance(c, int):
                    want_f.add(int(c))
                else:
                    try:
                        want_f.add(int(round(float(c) * fps)))
                    except (TypeError, ValueError):
                        continue
            evs = [e for e in evs if any(abs(e['f'] - f) <= 1 for f in want_f)]
        events[k] = evs
    measured = {k: measure_events(events[k], ml, fps) for k in kinds}
    summaries = {k: summarize(measured[k], fps, given) for k in kinds}
    mono = monotony(measured.get('cuts') or [], given)
    hh = hard_hits(measured.get('cuts') or [], given)
    svm = speech_vs_music(sig, ml, given)
    spans, words, _, _ = _speech(sig, given)
    svs = sections_vs_story(sig, ml, opts, given)
    sfx = sfx_vs_impacts(measured.get('sfx') or [], measured.get('motion_peaks') or [], measured.get('cuts') or [],
                         fps, words, given)
    # images
    out_dir = _out_dir('sync')
    title = f'Sync: {Path(str(source)).name}'
    pieces = ml.get('pieces') or []
    music_info = [f"music: {ml.get('stem')}"[:150],
                  f"beat finder {ml.get('tracker')}; tempo {ml.get('tempo_bpm')} bpm; beat quality "
                  f"{ml.get('beat_quality')} (confidence {ml.get('beat_confidence')}); {len(ml.get('beats') or [])} "
                  f"beats, {len(pieces)} music piece(s)"]
    story = story_sections(sig, opts)
    t0 = float(start_s) if start_s is not None else 0.0
    t1 = float(end_s) if end_s is not None else frames / fps
    labels = dict(KIND_LABEL, **({'sfx': 'sound onsets'} if sig.get('kind') == 'video' else {}))
    q = ml.get('beat_quality')
    caution = None
    if q in ('weak', 'none'):
        caution = (f'beat grid {q}: the beat finder is unsure of the beat here (confidence {ml.get("beat_confidence")}); '
                   'read the offsets as rough')
    images = [draw_overview(out_dir / 'sync-overview.png', title, summaries, mono, music_info, kinds, measured, labels,
                            caution)]
    if ml.get('beats'):
        impacts = {o['f']: o for o in sfx.get('onsets') or [] if o.get('impact')}
        images += draw_strips(out_dir, sig, ml, measured, spans, story, t0, t1,
                              secs_per_row=float(opts.get('strip_s') or 12.0),
                              max_pages=int(opts.get('pages') or 4), impacts=impacts,
                              on_k=float(th('sync.on_beat_frames', given)))
    else:
        unsupported.append('no beat grid (no music, or no steady beat): offsets cannot be measured')
    # result
    try:
        import letitedit.timing.timing_views as timing_views
        base = timing_views.common_fields(source=str(source), sig=sig if mode is None else None, view='sync',
                                          inputs=[start_s, end_s, items, cuts, opts, detail])
    except ImportError:
        base = {'schema_version': SCHEMA_VERSION, 'result_id': _hash([str(source), start_s, end_s, items, cuts, opts]),
                'project_revision': None, 'source_fingerprints': {}, 'checked_ranges': [], 'unchecked_ranges': [],
                'warnings': [], 'unsupported': [], 'preview_artifacts': [], 'changes': []}
    lim = None if detail == 'full' else 60
    res = dict(base)
    res.update({
        'view': 'sync', 'images': [str(p) for p in images], 'fps': fps, 'frames': frames,
        'music': {k: ml.get(k) for k in ('tracker', 'tempo_bpm', 'beat_quality', 'beat_confidence', 'stem',
                                         'music_spans', 'songs')},
        'music_pieces': [{k: p.get(k) for k in ('id', 'track', 'clip', 't0', 't1', 'bpm', 'beat_quality',
                                                'beat_confidence', 'crossfade_in_s', 'owns', 'beats')}
                         for p in pieces][:20],
        'summary': summaries, 'monotony': mono, 'hard_hits': hh, 'speech_vs_music': svm,
        'sections_vs_story': svs, 'sfx_vs_impacts': sfx,
        'events': {k: (measured[k] if lim is None else measured[k][:lim]) for k in kinds},
        'events_from': notes,
        'thresholds': used_thresholds('sync.', given),
        'options_used': {k: opts.get(k) for k in VIEW_OPTIONS if k in opts}, 'options_available': VIEW_OPTIONS,
        'conventions': ('offsets in frames on the edit\'s grid: event - nearest beat (+ = the picture event after '
                        'the beat, the sound leads); chance = the share expected if events fell at random phases '
                        '(2 x threshold / beat period); events count only where music plays'),
        'seconds': round(time.time() - t_all, 2)})
    res['warnings'] = list(base.get('warnings') or []) + warnings + list(ml.get('warnings') or [])
    res['unsupported'] = list(base.get('unsupported') or []) + unsupported + list(ml.get('unsupported') or [])
    res['preview_artifacts'] = list(res['images'])
    return _clean(res)


# ============================================================================ registration

_REGISTERED = {'lane': False, 'view': False, 'thresholds': False}


def register():
    """Register the 'music' lane and the 'sync' view when the store and the view registry are importable, and add
    this module's threshold keys to timing_thresholds.json (missing keys only). Safe to call again."""
    if not _REGISTERED['lane']:
        try:
            import letitedit.timing.timing_signals as timing_signals
            if hasattr(timing_signals, 'register_lane'):
                timing_signals.register_lane(LANE, lane, depends=(), version=LANE_VERSION)
                _REGISTERED['lane'] = True
        except Exception:  # noqa: BLE001 - no store: music() and sync() work on their own
            pass
    if not _REGISTERED['view']:
        try:
            import letitedit.timing.timing_views as timing_views
            if hasattr(timing_views, 'register_view'):
                timing_views.register_view('sync', sync, VIEW_SUMMARY)
                _REGISTERED['view'] = True
        except Exception:  # noqa: BLE001
            pass
    if not _REGISTERED['thresholds']:
        try:
            merge_thresholds(THRESHOLDS)
            _REGISTERED['thresholds'] = True
        except Exception:  # noqa: BLE001 - the defaults in code still apply
            pass
    return dict(_REGISTERED)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        import argparse
        ap = argparse.ArgumentParser(description='music lane / sync view')
        ap.add_argument('source')
        ap.add_argument('--view', action='store_true', help='run the sync view (else the music lane alone)')
        ap.add_argument('--start', type=float, default=None)
        ap.add_argument('--end', type=float, default=None)
        a = ap.parse_args(sys.argv[1:])
        if a.view:
            r = sync(a.source, a.start, a.end)
            print(json.dumps({k: v for k, v in r.items() if k not in ('events',)}, indent=1, default=str)[:20000])
        else:
            r = music(a.source)
            print(json.dumps({k: (v if not isinstance(v, list) or len(v) < 12 else f'[{len(v)} items]')
                              for k, v in r.items()}, indent=1, default=str))
else:
    register()
